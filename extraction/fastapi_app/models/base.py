"""
数据库模型基础类
包含所有表共用的系统字段
"""
from loguru import logger
from datetime import datetime, UTC
import pytz
from sqlalchemy import (BIGINT, Column, String, DateTime, Boolean, Text, select, Select, func, or_, and_, Result,
                        inspect, ColumnElement, delete, update)
from sqlalchemy.engine.row import Row
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import Session, validates
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Type, TypeVar, Callable, Any, Sequence, Literal
from pydantic import BaseModel as PydanticBaseModel

from decorators.db import before_insert, before_update
from ..schemas.enums import FieldFilterModeEnum
from ..schemas.schema import (PaginationResponse, FieldFilterSchema, TimeFilterSchema, SimpleQueryOne,
                              PaginationSchema, SimpleQueryPagination, PaginationBaseSchema)
from ..core.database import Base, transaction, readonly
from ..core.context import (
    current_context, safe_get_context_tenant_id, safe_get_context_belong_org_id,
    safe_get_context_username, safe_get_context_manage_orgs
)
from ..utils.tiny_func import simple_exception

PydanticModel = TypeVar('PydanticModel', bound=PydanticBaseModel)


class _SessionQueryProxy:
    """
    轻量查询代理：
    - 未传入 db 时由 get_query 创建；
    - 链式方法（如 filter、order_by 等）返回新的代理；
    - 终止方法（如 all、first、one、count 等）执行后自动关闭会话；
    - 尽量保持与 SQLAlchemy Query 用法一致。
    """

    def __init__(self, session: Session, query):
        self._session = session
        self._query = query
        self._closed = False

    def _close(self):
        if not self._closed:
            try:
                self._session.close()
            except Exception:
                pass
            self._closed = True

    def _wrap_result(self, result):
        try:
            from sqlalchemy.orm import Query as SAQuery  # type: ignore
            is_query = isinstance(result, SAQuery)
        except Exception:
            # 兜底：基于常见 Query 接口特征判断
            is_query = hasattr(result, 'filter') and hasattr(result, 'all')

        if is_query:
            return _SessionQueryProxy(self._session, result)
        else:
            # 终止调用后关闭会话
            self._close()
            return result

    def __getattr__(self, item):
        attr = getattr(self._query, item)
        if callable(attr):
            def wrapper(*args, **kwargs):
                result = attr(*args, **kwargs)
                return self._wrap_result(result)
            return wrapper
        return attr

    def __iter__(self):
        try:
            result_list = list(self._query)
            return iter(result_list)
        finally:
            self._close()

    def __del__(self):
        self._close()

class EpochTimestamp(TypeDecorator):
    """
    将数据库中的 BIGINT Unix 时间戳与 Python datetime 双向转换，兼容秒/毫秒。
    不修改表结构，仅在 ORM 层做适配。
    """
    impl = BIGINT
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, datetime):
            return int(value.timestamp())
        try:
            return int(value)
        except Exception:
            raise TypeError(f"Unsupported timestamp value for BIGINT: {type(value)}")

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        # 兼容毫秒/秒
        if value > 10 ** 12:
            value = value / 1000.0
        return datetime.fromtimestamp(value)

class TimestampMixin:
    """
    时间戳混入类
    为模型添加创建时间、更新时间、创建人、更新人字段
    """
    @declared_attr
    def id(cls):
        """ID"""
        # 使用毫秒时间戳拼接随机数生成分布式唯一ID（客户端默认值）
        return Column(
            BIGINT,
            primary_key=True,
            autoincrement=False,
            comment="ID",
        )
    
    @declared_attr
    def created_at(cls):
        """创建时间"""
        return Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, comment="创建时间")
    
    @declared_attr
    def updated_at(cls):
        """更新时间"""
        return Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC),
                      nullable=False, comment="更新时间")
    
    @declared_attr
    def created_by(cls):
        """创建人"""
        return Column(Text, nullable=True, comment="创建人")
    
    @declared_attr
    def updated_by(cls):
        """更新人"""
        return Column(Text, nullable=True, comment="更新人")
    
    @declared_attr
    def is_delete(cls):
        """是否删除"""
        return Column(Boolean, nullable=True, default=False, comment="是否删除")

    @declared_attr
    def org_id(cls):
        """业务数据组织ID"""
        return Column(Text, nullable=True, comment="业务数据组织ID")


class UnixTimestampMixin:
    """
    使用 BIGINT 存储 Unix 时间戳的历史表兼容混入。
    不改变表结构，FastAPI 侧读取为 datetime，写入自动转 BIGINT。
    """
    @declared_attr
    def created_at(cls):
        return Column(EpochTimestamp(), nullable=False, comment="创建时间（BIGINT epoch）")

    @declared_attr
    def updated_at(cls):
        return Column(EpochTimestamp(), nullable=False, comment="更新时间（BIGINT epoch）")


class _StaticBase:
    """混入类：用于提供给BaseModel继承的静态方法集合"""

    @staticmethod
    def apply_one_timeRange(stmt: Select, time_range: TimeFilterSchema, field: ColumnElement, apply_order=True) -> Select:
        """
        [通用筛选] 将单个字段的时间范围条件应用于给定的查询对象。

        :param stmt: 原始的 SQLAlchemy Select 语句对象
        :param time_range: 时间范围筛选对象
        :param field: 表模型的字段对象，如：User.id
        :param apply_order: 是否在应用时间范围条件的时候同时应用order排序，默认是
        :return: 应用了时间范围条件的查询对象
        """
        if field is None:  # 字段不存在，跳过当前筛选条件
            return stmt

        stmt = stmt.where(
            and_(
                field >= time_range.begin if time_range.begin else True,
                field <= time_range.end if time_range.end else True
            )
        )
        if apply_order:
            stmt = _StaticBase.apply_order(stmt, field, time_range.order)
        return stmt

    @staticmethod
    def apply_one_filter(stmt: Select, field_filter: FieldFilterSchema, field: ColumnElement, apply_order=True) -> Select:
        """
        [通用筛选] 将单个字段的筛选条件应用于给定的查询对象。

        :param stmt: 原始的 SQLAlchemy Select 语句对象
        :param field_filter: 一个筛选对象，会忽略field_name，以field为实际字段
        :param field: 表模型的字段对象，如：User.id
        :param apply_order: 是否在应用筛选条件的时候同时应用order排序，默认是
        :return: 应用了筛选条件的查询对象
        """
        if field is None:  # 字段不存在，跳过当前筛选条件
            return stmt

        ft = field_filter
        bool_map = {'true': True, 'false': False}

        # 无筛选值则不添加筛选；只有一个值则使用 =；多个则使用 in
        if fvs := ft.values:
            # 列类型为布尔值，则兼容传值为字符串形式的 true/false
            if field.type.python_type is bool and fvs:
                fvs = [bool_map.get(v.lower(), v) if isinstance(v, str) else v for v in fvs]

            if ft.mode in {FieldFilterModeEnum.CONTAINS, FieldFilterModeEnum.STARTS_WITH,
                           FieldFilterModeEnum.ENDS_WITH}:
                if field.type.python_type is not str:
                    raise ValueError(
                        f"筛选模式 {ft.mode} 只支持字符串类型，而字段 {ft.field_name} 的类型为 {field.type.python_type}")
                if any(not isinstance(v, str) for v in fvs):
                    raise ValueError(
                        f"字段 {ft.field_name} 的筛选模式 {ft.mode} 只支持字符串类型，而筛选值 {fvs} 中有非字符串值")

            match ft.mode:
                case FieldFilterModeEnum.EQUAL:
                    stmt = stmt.where(field == fvs[0]) if len(fvs) == 1 else stmt.where(field.in_(fvs))
                case FieldFilterModeEnum.NOT_EQUAL:
                    stmt = stmt.where(field != fvs[0]) if len(fvs) == 1 else stmt.where(field.notin_(fvs))
                case FieldFilterModeEnum.CONTAINS:
                    stmt = stmt.where(or_(func.lower(field).contains(v.lower()) for v in fvs))
                case FieldFilterModeEnum.STARTS_WITH:
                    stmt = stmt.where(or_(func.lower(field).startswith(v.lower()) for v in fvs))
                case FieldFilterModeEnum.ENDS_WITH:
                    stmt = stmt.where(or_(func.lower(field).endswith(v.lower()) for v in fvs))
                case FieldFilterModeEnum.GREATER_THAN:
                    stmt = stmt.where(or_(field > v for v in fvs))
                case FieldFilterModeEnum.LESS_THAN:
                    stmt = stmt.where(or_(field < v for v in fvs))
                case FieldFilterModeEnum.GREATER_THAN_OR_EQUAL:
                    stmt = stmt.where(or_(field >= v for v in fvs))
                case FieldFilterModeEnum.LESS_THAN_OR_EQUAL:
                    stmt = stmt.where(or_(field <= v for v in fvs))

        if apply_order:
            stmt = _StaticBase.apply_order(stmt, field, ft.order)
        return stmt

    @staticmethod
    def apply_order(stmt: Select, field: ColumnElement, order: Literal['desc', 'asc', 'DESC', 'ASC'] | None):
        """
        将排序条件应用于一个已有的 Select 语句对象。
        这是一个静态工具方法，可以作用于任何 Select 语句。

        :param stmt: 原始的 Select 语句对象。
        :param field: 表模型的字段对象，如：User.id
        :param order: 排序条件字符串，格式为 "字段名 [ASC|DESC]"。
        :return: 应用了排序条件的新 Select 语句对象。
        """
        if not order:
            return stmt
        order = order.lower()
        if order not in ('desc', 'asc'):
            return stmt
        return stmt.order_by(field.desc() if order == "desc" else field.asc())

    @staticmethod
    def apply_filters_and_order(stmt: Select, model_cls: Type['BaseModel'], filters: list[FieldFilterSchema] = None, time_ranges: list[TimeFilterSchema] = None, apply_order=True) -> Select:
        """
        将筛选和排序条件应用于一个已有的 Select 语句对象。
        这是一个静态工具方法，可以作用于任何 Select 语句。

        :param stmt: 原始的 Select 语句对象。
        :param model_cls: 筛选条件所针对的主要 ORM 模型类。
        :param filters: 字段筛选列表。
        :param time_ranges: 时间范围筛选列表。
        :param apply_order: 是否在应用筛选条件的时候同时应用order排序，默认是
        :return: 应用了筛选和排序条件后的新 Select 语句对象。
        """
        filters = filters or []
        time_ranges = time_ranges or []
        get_field = generate_get_field(model_cls)

        for ft in filters:
            field = get_field(ft.field_name)
            if field is None:
                continue
            stmt = _StaticBase.apply_one_filter(stmt=stmt, field_filter=ft, field=field, apply_order=apply_order)

        for time_range in time_ranges:
            field = get_field(time_range.field_name)
            if field is None:
                continue
            stmt = _StaticBase.apply_one_timeRange(stmt=stmt, time_range=time_range, field=field, apply_order=apply_order)

        return stmt


@before_insert
@before_update
class BaseModel(Base, TimestampMixin, _StaticBase):
    """
    抽象基础模型类
    所有业务模型都应该继承此类
    """
    __abstract__ = True

    def update_audit_fields(self, username: str = None):
        """
        更新审计字段，在更新记录时调用此方法来设置更新人

        :param username: 操作人/用户表中的 username
        """
        self.updated_at = datetime.now(UTC)
        username = username or safe_get_context_username()
        if username:
            self.updated_by = str(username)

    def set_create_audit_fields(self, username: str = None):
        """
        设置创建审计字段，在创建记录时调用此方法来设置创建人

        :param username: 操作人/用户表中的id
        """
        now = datetime.now(UTC)
        self.created_at = now
        self.updated_at = now
        username = username or safe_get_context_username()
        if username:
            self.created_by = str(username)
            self.updated_by = str(username)

    def soft_delete(self, username: str = None):
        """
        软删除，在删除记录时调用此方法来设置删除人

        :param username: 操作人/用户表中的id
        """
        self.is_delete = True
        self.updated_at = datetime.now(UTC)
        username = username or safe_get_context_username()
        if username:
            self.updated_by = str(username)

    @classmethod
    @readonly()
    async def select_by_id(cls, id: str | int, *, exclude_deleted=True, db: AsyncSession = None) -> Optional['BaseModel']:
        """
        [通用SELECT] 根据本表ID（主键）获取一条记录

        默认会排除 is_delete=True 的数据

        :param id: 主键
        :param exclude_deleted: 是否排除已删除，默认排除
        :param db: 异步数据库连接对象
        :return: 唯一一条记录，或者None
        """
        query = select(cls).where(cls.id == id)
        if exclude_deleted:
            query = query.where(cls.is_delete == False)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @classmethod
    @transaction()
    async def update_async(cls, record: 'BaseModel', data: PydanticModel, *, db: AsyncSession = None) -> 'BaseModel':
        """[通用UPDATE] 对一条记录执行更新操作

        :param record: 查库得到的一条记录对象
        :param data: 与记录的字段一一对应的pydantic数据模型实例，未设置字段将不会更新
        :param db: 异步数据库连接对象，若传入则复用同一个连接
        :return: 执行更新后的记录对象
        """
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if hasattr(record, key):
                setattr(record, key, value)
        await db.flush()
        return record

    @classmethod
    @transaction()
    async def update_where_async(cls, *, where: Sequence[ColumnElement[bool]], values: dict, db: AsyncSession = None) -> int:
        """[通用批量UPDATE] 根据给定的条件批量更新记录

        示例::

            count = await User.update_where_async(
                where=[
                    User.type == '皇帝',
                    User.age < 10,
                    User.name.contains('刘')
                ],
                values={'is_active': False},
                db=db
            )
            print(f'更新了 {count} 条记录')


        :param where: 过滤条件列表/元组
        :param values: 更新字段及值
        :param db: 异步数据库连接对象，若传入则复用同一个连接
        :return: 执行更新的记录数量
        """
        if not where:
            raise ValueError("批量更新必须提供至少一个WHERE条件，以防止意外更新全表。")
        stmt = update(cls).where(*where).values(**values).execution_options(synchronize_session='fetch')
        result = await db.execute(stmt)
        return result.rowcount

    @classmethod
    @transaction()
    async def delete_async(cls, id: str | int, sure_delete: bool = False, *, db: AsyncSession = None):
        """[通用DELETE] 执行删除操作

        [！注意！] 物理删除！

        :param id: 需要删除的记录id
        :param sure_delete: 物理删除！冗余确认一次，传入 True 才会执行删除
        :param db: 异步数据库连接对象，若传入则复用同一个连接
        """
        if not sure_delete:
            return
        stmt = delete(cls).where(cls.id == id)
        await db.execute(stmt)

    @classmethod
    @readonly()
    async def selects_by_ids(cls, ids: list[str], *, db: AsyncSession = None) -> list['BaseModel']:
        """根据ID列表获取数据"""
        query = cls.build_query(filters=[
            FieldFilterSchema(field_name='id', values=ids),
        ])
        result = await db.execute(query)
        return result.scalars().all()

    @classmethod
    async def apply_organization_filter(cls, query: Select) -> Select:
        """
        [数据权限] 将组织数据范围过滤器应用于给定的查询对象。
        查询将限定在当前用户所属组织及其所有子组织内。

        :param query: 原始的 SQLAlchemy Select 查询对象
        :return: 应用了组织筛选条件的查询对象
        """
        from fastapi_app.core.cache import orgCacheManager
        # if cls.__tablename__ == 'master_data_organizations': # 组织表本身做查询时筛选排除
        #     return query
        belong_org: str | None = safe_get_context_belong_org_id()
        manage_orgs: list = safe_get_context_manage_orgs()
        tenant_id = safe_get_context_tenant_id()
        if not tenant_id:
            raise ValueError("当前上下文 tenant_id 为空")
        if not belong_org and not manage_orgs:  # 无组织ID，则只能看无所属组织的数据/-1组织
            return query.where(or_(cls.org_id.is_(None), cls.org_id == '-1'))  # -1 代表所有人都能看

        # 获取当前用户权限范围内的所有可见组织ID
        # scoped_org_ids = await orgCacheManager.get_scoped_org_ids_by_tree(belong_org=belong_org, manage_orgs=manage_orgs, tenant_id=tenant_id)
        scoped_org_ids = await orgCacheManager.get_scoped_org_ids_by_simple(belong_org=belong_org, manage_orgs=manage_orgs, tenant_id=tenant_id)
        scoped_org_ids.append('-1')
        # 应用筛选
        return query.where(cls.org_id.in_(scoped_org_ids))

    @classmethod
    @readonly()
    async def asyncExecuteQuery(cls, query: Select, *, db: AsyncSession = None) -> Result:
        """执行查询。所有手动编写的业务数据select都应该经过本方法执行，或分页的 paginate_async（自动加上组织的数据权限筛选）"""
        query = await cls.apply_organization_filter(query)
        logger.info(f"execute_query SQL语句: {query}")
        return await db.execute(query)

    @classmethod
    def get_query(cls, db: Optional[Session] = None):
        """
        获取查询对象
        - 传入 db：直接返回可用的 Query
        - 不传 db：返回一个查询代理对象，保持调用方式不变；
          当调用终止方法（如 all/first/one/count 等）后自动关闭内部会话。
        """
        assert db is None or isinstance(db, Session), f"db 只能为 Session 实例，而非 {type(db)}"
        if db is not None:
            return db.query(cls).filter(cls.is_delete == False)

        # 未传入会话时，创建一个会话并返回查询代理
        from fastapi_app.core.database import SessionLocal as _SessionLocal
        if _SessionLocal is None:
            raise RuntimeError("Database not initialized")

        session = _SessionLocal()  # type: ignore[misc]
        query = session.query(cls).filter(cls.is_delete == False)
        return _SessionQueryProxy(session, query)

    @classmethod
    def build_query(cls, filters: list[FieldFilterSchema] = None, time_ranges: list[TimeFilterSchema] = None, select_fields: list[str] = None) -> Select:
        """
        获取异步查询对象，仅返回Select语句对象，不会执行查询

        :param filters: 多个字段筛选
        :param time_ranges: 时间段筛选
        :param select_fields: select本表的列名，默认所有字段
        :return: Select对象
        """
        # 指定列查询；无指定则查询所有列。
        selected_columns = []
        if select_fields:
            for field_name in select_fields:
                if field_name == '*':
                    selected_columns = [cls]
                    break
                if hasattr(cls, field_name):
                    selected_columns.append(getattr(cls, field_name))
        if not selected_columns:
            selected_columns = [cls]

        query = select(*selected_columns).where(cls.is_delete == False)
        return cls.apply_filters_and_order(stmt=query, model_cls=cls, filters=filters, time_ranges=time_ranges)

    @classmethod
    @readonly()
    async def get_query_async(cls, filters: list[FieldFilterSchema] = None, time_ranges: list[TimeFilterSchema] = None, select_fields: list[str] = None, *, db: AsyncSession = None, ) -> Result:
        """
        构建SQL语句并执行（有数据权限筛选）

        :param db: 异步数据库连接，若传入则复用同一个连接
        :param filters: 多个字段筛选
        :param time_ranges: 时间段筛选
        :param select_fields: select本表的列名，默认所有字段
        :return: 执行后的 Result 对象
        """
        query = cls.build_query(filters=filters, time_ranges=time_ranges, select_fields=select_fields)
        return await cls.asyncExecuteQuery(query, db=db)

    @classmethod
    def build_simple_query(cls, label_field='name', value_field='id') -> Select:
        """
        简单查询可选项，将字段别名为label和value，返回 Select 语句对象

        :param label_field: json字段 label 对应的ORM模型字段名
        :param value_field: json字段 value 对应的ORM模型字段名
        :return: 构建的 select 语句对象
        """
        inspector = inspect(cls)
        try:
            is_active_col: ColumnElement = inspector.get_property('is_active').columns[0]
            tenant_id_col: ColumnElement = inspector.get_property('tenant_id').columns[0]
            is_delete_col: ColumnElement = inspector.get_property('is_delete').columns[0]
            label_col: ColumnElement = inspector.get_property(label_field).columns[0]
            value_col: ColumnElement = inspector.get_property(value_field).columns[0]
        except AttributeError as e:
            # 捕获并提供更友好的错误信息
            raise AttributeError(f'ORM模型 "{cls.__name__}" 缺少必要的字段。错误: {e}')

        try:
            context_info = current_context.get()
        except LookupError:
            raise LookupError('当前请求上下文为空')
        tenant_id = context_info.tenant_id

        query = select(
            label_col.label("label"),
            value_col.label("value")
        ).where(
            and_(
                is_delete_col == False,
                is_active_col == True,
                tenant_id_col == tenant_id
            )
        )
        return query

    @classmethod
    @readonly()
    async def simple_query_async(cls, page_query: PaginationBaseSchema, *, label_field='name', value_field='id',
                                 db: AsyncSession = None, apply_org_filter=False) -> SimpleQueryPagination:
        """
        简单查询可选项（下拉数据），返回只含label和value两个字段的分页模型。

        对于获取下拉可选项，默认不添加组织ID筛选。

        :param page_query: 分页查询条件
        :param label_field: json字段 label 对应的ORM模型字段名
        :param value_field: json字段 value 对应的ORM模型字段名
        :param db: 异步数据库连接对象，若传入则复用同一个连接
        :param apply_org_filter: 是否添加组织ID筛选，默认否
        :return: 分页查询结果
        """
        query = cls.build_simple_query(label_field=label_field, value_field=value_field)
        return await cls.paginate_async(db=db, stmt=query, pageSize=page_query.pageSize,
                                        pageNum=page_query.pageNum, model=SimpleQueryOne,
                                        processor=lambda r: {'label': r.label, 'value': r.value},
                                        apply_org_filter=apply_org_filter)

    @classmethod
    @readonly()
    async def paginate_async(cls, *, stmt: Select, pageSize: int, pageNum: int, model: Type[PydanticModel], db: AsyncSession = None,
                             processor: Callable[[Row], dict] = None, apply_org_filter=True) -> PaginationResponse[PydanticModel]:
        """
        通用分页数据处理异步方法

        - 自动加上组织的数据权限筛选
        - 自动添加保底的以id倒序排序

        :param stmt: Select对象
        :param pageSize: 分页数量
        :param pageNum: 页码
        :param model: 每一条记录对应的 Pydantic 数据模型
        :param db: 异步数据库连接对象，若传入则复用同一个连接
        :param processor: 可选的行处理器函数。它接收一个数据库行（ORM对象或Row对象），
                          返回一个用于实例化 Pydantic 模型的字典。
                          如果为 None，则默认使用 row.to_dict()。
        :param apply_org_filter: 是否添加组织ID筛选，默认是
        :return: 分页响应模型实例
        """
        if apply_org_filter:
            stmt = await cls.apply_organization_filter(stmt)
        stmt = stmt.order_by(cls.id.desc())
        total_stmt = select(func.count()).select_from(stmt.subquery())
        total: int = (await db.execute(total_stmt)).scalar_one()
        offset = (pageNum - 1) * pageSize
        rows = (await db.execute(stmt.offset(offset).limit(pageSize))).all()
        
        if processor:
            # 有处理器则直接将每一行交给处理器处理
            row_responses = [model(**processor(row)) for row in rows]
        else:
            # 如果没有处理器，假定查询的是单个ORM对象
            row_responses = [model(**row[0].to_dict()) for row in rows]

        return PaginationResponse.create(
            items=row_responses,
            total=total,
            page_num=pageNum,
            page_size=pageSize
        )

    def to_dict(self, custom_fields=None, exclude_fields=None):
        """
        基础的字典转换方法
        Args:
            custom_fields (dict): 自定义字段字典
            exclude_fields (list): 需要排除的字段列表，如果不传则使用默认排除字段
        Returns:
            dict: 合并后的字典
        """
        # 默认排除字段
        default_exclude = ['is_delete']

        # 如果传入了exclude_fields，则与默认排除字段合并
        exclude_fields = set(default_exclude + (exclude_fields or []))

        def format_timestamp(value):
            """处理时间戳的辅助函数"""
            if value is None or isinstance(value, str):
                return None
            # 如果是datetime类型，直接返回
            # return value.astimezone(pytz.timezone('Asia/Shanghai')).strftime('%Y-%m-%dT%H:%M:%S.%f%z')
            return value.astimezone(pytz.timezone('Asia/Shanghai')).isoformat()

        base_dict = {
            # 注意这里做了到字符串的转换
            'id': self.id,
            'is_delete': self.is_delete,
            'status': getattr(self, 'status', None),
            'created_at': format_timestamp(self.created_at),
            'updated_at': format_timestamp(self.updated_at),
            'created_by': self.created_by,
            'updated_by': self.updated_by,
        }

        if custom_fields:
            base_dict.update(custom_fields)

        # 排除字段
        for field in exclude_fields:
            base_dict.pop(field, None)

        return base_dict


@before_insert
@before_update
class BaseModelFastAPI(BaseModel):
    """在FastAPI中新建的表模型基类，增加两个通用字段：tenant_id、is_active，ID字段统一为字符串类型"""
    __abstract__ = True
    tenant_id = Column(BIGINT, nullable=False, index=True, comment='租户ID')
    is_active = Column(Boolean, nullable=False, default=True, comment='是否有效，默认为true(有效)')

    @declared_attr
    def id(cls):
        """ID"""
        return Column(String(36), primary_key=True, autoincrement=False, comment="ID")

    @validates('id')
    def validate_id(self, key, value):
        """
        在 id 赋值前进行验证和类型转换，如果传入 int 则转为 str。
        - key: 字段名，即 'id'
        - value: 传入的值
        """
        if isinstance(value, int):
            return str(value)
        return value

    @validates('tenant_id')
    def validate_tenant_id(self, key, value):
        """
        在 tenant_id 赋值前进行验证和类型转换，支持传入 int 或 全数字格式的字符串。
        - key: 字段名，即 'tenant_id'
        - value: 传入的值
        """
        if value is None:
            raise ValueError("tenant_id 不能为空")

        if isinstance(value, int):
            return value
        elif isinstance(value, str):
            # 如果是字符串，检查是否为纯数字
            if value.isdigit():
                return int(value)  # 转换为 int
        raise TypeError(f"提供的 tenant_id 值 '{value}' 不是一个有效的数字或字符串")

    def to_dict(self, custom_fields: dict = None, exclude_fields: list = None):
        custom_dict = {
            'tenant_id': str(self.tenant_id),
            'is_active': self.is_active
        }
        if custom_fields and isinstance(custom_fields, dict):
            custom_dict.update(custom_fields)
        return super(BaseModelFastAPI, self).to_dict(custom_fields=custom_dict, exclude_fields=exclude_fields)

    @classmethod
    @readonly()
    async def select_all_ids(cls, tenant_id: int, *, db: AsyncSession = None) -> list[str]:
        """查询所有ID"""
        stmt_all_ids = select(cls.id).where(
            and_(
                cls.tenant_id == tenant_id,
                cls.is_delete == False
            )
        )
        return list(set((await db.execute(stmt_all_ids)).scalars().all()))

@before_insert
@before_update
class BaseModelUnixTs(UnixTimestampMixin, BaseModel):
    """
    抽象基础模型（兼容 BIGINT 时间戳表）。
    不改表结构，仅用 UnixTimestampMixin 覆盖时间字段。
    """
    __abstract__ = True


def generate_get_field(model_cls: Type[BaseModel]) -> Callable[[str], Optional[ColumnElement]]:
    """
    生成一个用于获取模型字段的函数。

    该函数工厂会创建一个闭包，其中包含了对特定模型类的SQLAlchemy inspector对象，
    用于检查模型的列属性并在运行时动态获取字段对象。

    :param model_cls: SQLAlchemy模型类
    :returns: 一个接受字段名并返回对应列对象的函数
    """

    # 获取 ORM 模型的自省器，用于检查模型的属性和列信息
    inspector = inspect(model_cls)

    def get_field(field_name: str) -> None | ColumnElement:
        """
        根据列名获取字段对象，获取失败返回 None。

        此函数会尝试通过SQLAlchemy的inspector对象查找指定名称的字段，
        并确保该字段是数据库列（而非关系属性等其他类型）。

        :param field_name: 数据库字段名称
        :returns: SQLAlchemy列对象，如果字段不存在或不是列属性则返回None
        """
        try:  
            # 预先判断是否有这个字段名，使用 inspect 检查字段存在性并获取其列对象
            field_prop = inspector.get_property(field_name)
            # 确保是列属性，而不是关系等其他类型的属性
            if not hasattr(field_prop, 'columns'):
                return None
            # 返回第一个（通常也是唯一的）列对象
            return field_prop.columns[0]
        except (AttributeError, InvalidRequestError) as e:
            logger.warning(f"应用筛选 {inspector} 表的字段 {field_name} 不存在: {str(e)}")
            return None

    return get_field