"""
仓储层（repository）基类

仓储层：
- 用于在 ORM model 层与 service 层中间架开一层，让 model 层更纯粹
- 处理与特定模型相关的所有数据访问逻辑 (CRUD)
- 可以在这一层添加业务逻辑
"""
from typing import TypeVar, Generic, Type, Sequence, Callable, Any
from loguru import logger
from sqlalchemy import (
    select, delete, update, Select, func, or_, Result, ColumnElement, Row, Executable, inspect
)
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel as PydanticBaseModel, ValidationError

from fastapi_app.models.base_model import BaseModel
from fastapi_app.schemas.schema import (
    PaginationResponse, PaginationBaseSchema, SimpleQueryOne, SimpleQueryPagination, FieldFilterSchema,
    TimeFilterSchema, PaginationSchema
)
from fastapi_app.core.context import (
    safe_get_context_tenant_id, safe_get_context_belong_org_id, safe_get_context_manage_orgs, current_context
)
from fastapi_app.models.QueryBuilder import QueryBuilder


T = TypeVar("T", bound=BaseModel)
PydanticModel = TypeVar('PydanticModel', bound=PydanticBaseModel)


class BaseRepository(Generic[T]):
    """
    通用仓储基类，封装了基础的 CRUD、分页和权限控制。

    - 所有操作都不会提交和回滚，需手动在外侧控制
    - 建议通过依赖注入获取 db 会话，以自动管理db的提交关闭

    继承写法示例::

        from sqlalchemy.ext.asyncio import AsyncSession
        from fastapi_app.models.base_repository import BaseRepository
        from .model import Supplier

        class SupplierRepository(BaseRepository[Supplier]):  # <<-- 重点1：需用中括号来指定具体 ORM 表模型
            def __init__(self, db: AsyncSession):
                super().__init__(db, model=Supplier)  # <<-- 重点2：需在初始化时指定 ORM 表模型
    """

    def __init__(self, db: AsyncSession, model: type[T]):
        """
        仓储初始化

        :param db: 异步数据库会话 (通过依赖注入)
        :param model: 仓储负责的 ORM 模型
        """
        assert issubclass(model, BaseModel), "model 必须是 BaseModel 的子类"
        self.db = db
        self.model: type[T] = model
        self._inspector = inspect(model)

    def column(self, field_name: str) -> ColumnElement:
        """根据本表字段名称，转为列对象"""
        try:
            field_prop = self._inspector.get_property(field_name)
            if not hasattr(field_prop, 'columns'):
                raise ValueError(
                    f"ORM模型 {self.model.__name__} 表的字段 {field_name} 不是一个列属性，实际类型为 {type(field_prop)}")
            return field_prop.columns[0]
        except Exception as e:
            raise ValueError(f"ORM模型 {self.model.__name__} 表的字段 {field_name} 不存在: {str(e)}")

    async def execute_query(self, builder: QueryBuilder, apply_org_filter: bool = True) -> Result:
        """通用查询执行器，自动应用数据权限。"""
        if apply_org_filter:
            builder = await self.apply_organization_filter(builder)
        try:
            return await self.db.execute(builder.stmt)
        except Exception as e:
            logger.error(f"execute_query 执行异常: {e}，SQL语句：{builder.sql()}")
            raise

    async def execute_pure(self, statement: Executable | QueryBuilder) -> Result:
        """纯粹执行一条语句，无任何附加内容"""
        stmt = statement.stmt if isinstance(statement, QueryBuilder) else statement
        try:
            return await self.db.execute(stmt)
        except Exception as e:
            sql = QueryBuilder.to_sql(stmt) if isinstance(stmt, Select) else stmt
            logger.error(f"execute_pure 执行异常: {e}，SQL语句：{sql}")
            raise

    # ------------- 公共 增/删/改 方法 -------------

    async def insert(self, schema: PydanticModel = None, **field_values) -> T:
        """创建一条新记录。两个参数至少其中一个必须有值。

        示例::

            await insert(UserSchema(name='John', age=20), tenant_id=1234)

        :param schema: 需创建的数据模型
        :param field_values: schema中不包含的额外的字段数据，重复字段名将覆盖 schema 的字段值
        :return: 新记录
        """
        if not schema and not field_values:
            raise ValueError("insert() 参数至少需要一个值")
        data: dict = schema.model_dump() if schema else {}
        data.update(field_values)
        new_record = self.model(**data)
        self.db.add(new_record)
        await self.db.flush()
        return new_record

    async def delete(self, id: str | int, sure_delete: bool = False):
        """[通用DELETE] 执行删除操作

        [！注意！] 物理删除！

        :param id: 需要删除的记录id
        :param sure_delete: 物理删除！冗余确认一次，传入 True 才会执行删除
        """
        if not sure_delete:
            return
        stmt = delete(self.model).where(self.column("id") == id)
        await self.db.execute(stmt)
        await self.db.flush()

    async def update(self, record: T, schema: PydanticModel) -> T:
        """
        [通用UPDATE] 对一条记录执行更新操作

        :param record: 查库得到的一条记录对象
        :param schema: 与记录的字段一一对应的 pydantic 数据模型实例，未设置字段将不会更新
        :return: 执行更新后的记录对象
        """
        update_data = schema.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if hasattr(record, key):
                setattr(record, key, value)
        await self.db.flush()
        return record

    async def update_where(self, where: Sequence[ColumnElement[bool]], values: dict) -> int:
        """
        [通用批量UPDATE] 根据给定的条件批量更新记录

        示例::

            count = await user_repo.update_where(
                where=[
                    User.type == '皇帝',
                    User.age < 10,
                    User.name.contains('刘')
                ],
                values={'is_active': False},
            )
            print(f'更新了 {count} 条记录')

        :param where: 过滤条件列表/元组
        :param values: 更新字段及值
        :return: 执行更新的记录数量
        """
        if not where:
            raise ValueError("批量更新必须提供至少一个WHERE条件，以防止意外更新全表。")
        stmt = update(self.model).where(*where).values(**values).execution_options(synchronize_session='fetch')
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    # ------------- QueryBuilder 工厂方法（生成QueryBuilder） -------------

    def new_QueryBuilder(self, *field: str | ColumnElement, exclude_deleted=True) -> QueryBuilder[T]:
        """
        工厂方法：创建一个与本仓储模型绑定的 QueryBuilder

        示例用法::

            qb1 = user_repo.new_QueryBuilder('id', 'name', 'code')
            qb2 = user_repo.new_QueryBuilder(User.id, User.name, User.code)

        :param field: 指定 select 的每个字段名/字段对象
        :param exclude_deleted: 是否默认排除已删除，默认是
        :return: 构建的 QueryBuilder 对象
        """
        return QueryBuilder(model=self.model, fields=list(field), exclude_deleted=exclude_deleted)

    def new_simple_QueryBuilder(self, label_field='name', value_field='id') -> QueryBuilder[T]:
        """
        简单查询可选项，将字段别名为label和value，返回 Select 语句对象

        :param label_field: json字段 label 对应的ORM模型字段名
        :param value_field: json字段 value 对应的ORM模型字段名
        :return: 构建的 QueryBuilder 对象
        """
        try:
            context_info = current_context.get()
        except LookupError:
            raise LookupError('当前请求上下文为空')
        tenant_id = context_info.tenant_id
        return QueryBuilder.new_label_value(model=self.model, tenant_id=tenant_id, label_field=label_field, value_field=value_field)

    def new_Select(self, *entities, **__kw) -> QueryBuilder[T]:
        """构建一个Select对象，并以自身Model，将其作为核心，构建一个QueryBuilder"""
        return QueryBuilder(model=self.model, stmt=select(*entities, **__kw))

    # ------------- 公共业务方法 -------------

    async def apply_organization_filter(self, builder: QueryBuilder) -> QueryBuilder[T]:
        """
        [数据权限] 将组织数据范围过滤器应用于给定的查询对象。
        查询将限定在当前用户所属组织及其所有子组织内。

        :param builder: 原始的 SQLAlchemy Select 查询 QueryBuilder 对象
        :return: 应用了组织筛选条件的查询对象
        """
        from fastapi_app.core.cache import orgCacheManager
        # if self.model.__tablename__ == 'master_data_organizations': # 组织表本身做查询时筛选排除
        #     return query
        belong_org: str | None = safe_get_context_belong_org_id()
        manage_orgs: list = safe_get_context_manage_orgs()
        tenant_id = safe_get_context_tenant_id()
        if not tenant_id:
            raise ValueError("当前上下文 tenant_id 为空")
        org_id_column = self.column('org_id')
        if not belong_org and not manage_orgs:  # 无组织ID，则只能看无所属组织的数据/-1组织
            return builder.where(or_(org_id_column.is_(None), org_id_column == '-1')) # -1 代表所有人都能看

        # 获取当前用户权限范围内的所有可见组织ID
        # scoped_org_ids = await orgCacheManager.get_scoped_org_ids_by_tree(belong_org=belong_org, manage_orgs=manage_orgs, tenant_id=tenant_id)
        scoped_org_ids = await orgCacheManager.get_scoped_org_ids_by_simple(belong_org=belong_org,
                                                                            manage_orgs=manage_orgs,
                                                                            tenant_id=tenant_id)
        scoped_org_ids.append('-1')
        # 应用筛选
        return builder.where(org_id_column.in_(scoped_org_ids))

    # ------------- 公共便捷查询方法 -------------
    # 无数据权限：select_ 开头

    async def select_by_id(self, id: int | str, exclude_deleted: bool = True) -> T | None:
        """根据主键ID获取一条记录"""
        builder = self.new_QueryBuilder().where(self.column('id') == id)
        if exclude_deleted:
            builder.where(self.column('is_delete') == False)
        # 简单查询，不应用组织权限 (通常查询单个ID是明确的操作)
        result = await self.execute_pure(builder)
        return result.scalar_one_or_none()

    async def select_by_ids(self, ids: list[int] | list[str]) -> Sequence[T]:
        """根据ID列表获取数据"""
        if not ids:
            return []
        builder = self.new_QueryBuilder().where(self.column('id').in_(ids))
        result = await self.execute_pure(builder)
        return result.scalars().all()

    async def select_tenant_all_models(self, tenant_id: int) -> Sequence[T]:
        """获取指定租户下所有记录。无 tenant_id 字段将会报错。

        :param tenant_id: 租户id
        :return: 查询得到的所有记录
        """
        builder = self.new_QueryBuilder().where(self.column('tenant_id') == tenant_id)
        result = await self.execute_pure(builder)
        return result.scalars().all()

    async def select_by(self, *fields: str | ColumnElement, **by) -> Sequence[T] | Sequence[Row]:
        """获取数据：直接指定字段精确筛选

        - 无数据权限
        - 已默认加上 is_delete=False
        - 如果指定了字段，返回 Row 序列；如果未指定字段 (全模型查询)，返回模型实例序列

        示例::

            await select_by(name='John', age=11)

            await select_by(User.id, User.name, name='John', age=11)

            await select_by('id', 'name', name='John', age=11)

        :param fields: 指定获取的字段，不传则全字段查询
        :param by: 每个筛选字段对应值
        :return: 查询得到的所有记录
        """
        builder = self.new_QueryBuilder(*fields)
        builder.filter_by(**by)
        result = await self.execute_pure(builder)
        if fields:
            # 如果指定了字段，返回 Row 序列 (e.g., [(1, 'John'), (2, 'Jane')])
            return result.all()
        # 如果未指定字段 (全模型查询)，返回模型实例序列
        return result.scalars().all()

    async def select_query(self, filters: list[FieldFilterSchema] = None, time_ranges: list[TimeFilterSchema] = None, select_fields: list[str] = None) -> Sequence[T] | Sequence[Row]:
        """
        应用筛选条件构建SQL语句并执行（无数据权限筛选）

        - 如果指定了字段，返回 Row 序列；如果未指定字段 (全模型查询)，返回模型实例序列

        :param filters: 多个字段筛选
        :param time_ranges: 时间段筛选
        :param select_fields: select本表的列名，默认所有字段
        :return: 查询得到的所有记录对象
        """
        select_fields = select_fields or []
        builder = self.new_QueryBuilder(*select_fields).apply_pagination(
            PaginationSchema(filters=filters, timeRanges=time_ranges)
        )
        result = await self.execute_pure(builder)
        if select_fields:
            # 如果指定了字段，返回 Row 序列 (e.g., [(1, 'John'), (2, 'Jane')])
            return result.all()
        # 如果未指定字段 (全模型查询)，返回模型实例序列
        return result.scalars().all()

    # 有数据权限：get_ 开头

    async def get_by(self, *fields: str | ColumnElement, **by) -> Sequence[T] | Sequence[Row]:
        """获取数据：直接指定字段精确筛选【有数据权限】

        - 【有数据权限】
        - 已默认加上 is_delete=False
        - 如果指定了字段，返回 Row 序列；如果未指定字段 (全模型查询)，返回模型实例序列

        示例::

            await get_by(name='John', age=11)

            await get_by(User.id, User.name, name='John', age=11)

            await get_by('id', 'name', name='John', age=11)

        :param fields: 指定获取的字段，不传则全字段查询
        :param by: 每个筛选字段对应值
        :return: 查询得到的所有记录
        """
        builder = self.new_QueryBuilder(*fields)
        builder.filter_by(**by)
        result = await self.execute_query(builder)
        if fields:
            # 如果指定了字段，返回 Row 序列 (e.g., [(1, 'John'), (2, 'Jane')])
            return result.all()
        # 如果未指定字段 (全模型查询)，返回模型实例序列
        return result.scalars().all()

    async def get_query(self, filters: list[FieldFilterSchema] = None, time_ranges: list[TimeFilterSchema] = None, select_fields: list[str] = None) -> Sequence[T] | Sequence[Row]:
        """
        应用筛选条件构建SQL语句并执行（有数据权限筛选）

        - 如果指定了字段，返回 Row 序列；如果未指定字段 (全模型查询)，返回模型实例序列

        :param filters: 多个字段筛选
        :param time_ranges: 时间段筛选
        :param select_fields: select本表的列名，默认所有字段
        :return: 查询得到的所有记录对象
        """
        select_fields = select_fields or []
        builder = self.new_QueryBuilder(*select_fields).apply_pagination(
            PaginationSchema(filters=filters, timeRanges=time_ranges)
        )
        result = await self.execute_query(builder)
        if select_fields:
            # 如果指定了字段，返回 Row 序列 (e.g., [(1, 'John'), (2, 'Jane')])
            return result.all()
        # 如果未指定字段 (全模型查询)，返回模型实例序列
        return result.scalars().all()

    # 公共查询方法（数据权限可选）

    async def paginate_selections(self, page_query: PaginationBaseSchema, *, label_field='name', value_field='id', apply_org_filter=False) -> SimpleQueryPagination:
        """
        可选项分页查询：执行本表的两个字段的查询，将分别命名为 label、value

        - 返回的分页数据中，每条数据结构为 ``{"label":"xxx","value":1}``
        """
        builder = self.new_simple_QueryBuilder(label_field=label_field, value_field=value_field)
        return await self.paginate(builder, pageSize=page_query.pageSize,  pageNum=page_query.pageNum,
                                   schema=SimpleQueryOne,
                                   processor=lambda r: {'label': r.label, 'value': r.value},
                                   apply_org_filter=apply_org_filter)

    async def paginate(
            self,
            builder: QueryBuilder,
            *,
            pageSize: int,
            pageNum: int,
            schema: Type[PydanticModel],
            processor: Callable[[Row], dict] = None,
            apply_org_filter=True
    ) -> PaginationResponse[PydanticModel]:
        """
        通用分页数据处理异步方法

        - 自动加上组织的数据权限筛选
        - 自动添加保底的以id倒序排序

        :param builder: 已经构建好筛选条件的 QueryBuilder 实例
        :param pageSize: 分页数量
        :param pageNum: 页码
        :param schema: 每一条记录对应的 Pydantic 数据模型
        :param processor: 可选的行处理器函数。它接收一个数据库行（ORM对象或Row对象），
                          返回一个用于实例化 Pydantic 模型的字典。
                          如果为 None，则默认使用 row.to_dict()。
        :param apply_org_filter: 是否添加组织ID筛选，默认是
        :return: 分页响应模型实例
        """
        builder.order_by(self.column('id').desc()) # 自动添加保底排序
        if apply_org_filter:
            builder = await self.apply_organization_filter(builder)
        stmt = builder.build()

        # 1. 获取总数
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self.execute_pure(count_stmt)
        total = total_result.scalar_one()

        # 2. 获取分页数据
        offset = (pageNum - 1) * pageSize
        data_stmt = stmt.offset(offset).limit(pageSize)
        data_result = await self.execute_pure(data_stmt)
        rows = data_result.all()  # .all() 返回 Row 列表

        if processor:
            # 有处理器则直接将每一行交给处理器处理
            row_responses = [schema(**processor(row)) for row in rows]
        else:
            if not rows:
                # 如果 rows 为空，提前返回
                return PaginationResponse.create(items=[], total=total, page_num=pageNum, page_size=pageSize)

            # 检查第一行数据结构
            first_row = rows[0]
            row_responses = []
            try:
                if isinstance(first_row[0], self.model) and len(first_row) == 1:
                    # 场景1：`select(Model)`
                    # row 是 (<Model>,)，row[0] 是 Model 实例
                    if hasattr(self.model, 'to_dict'):  # 优先使用模型的 to_dict() 方法
                        row_responses = [schema.model_validate(row[0].to_dict()) for row in rows]
                    else: # 使用 Pydantic v2 的 model_validate (等同于 from_orm)
                        row_responses = [schema.model_validate(row[0]) for row in rows]
                else:
                    # 场景2：`select(Model.id, Model.name)` 或 `label/value`
                    # row 是 (1, 'John') 或 ('Label', 1)
                    # Row 对象支持 _mapping (类字典)，使用 Pydantic v2 直接从 mapping 验证
                    row_responses = [schema.model_validate(row._mapping) for row in rows]
            except ValidationError:  # pydantic 验证异常：原样抛出
                raise
            except Exception as e:
                logger.error(f"Paginate 默认处理器映射失败: {e}。Schema: {schema}。Row: {first_row._mapping}")
                raise TypeError(
                    f"无法自动将查询结果 {first_row._mapping} 映射到 Pydantic 模型 {schema}。"
                    f"如果 QueryBuilder 没有 SELECT 整个模型 (e.g., new_QueryBuilder())，"
                    f"请【必须】提供一个 'processor' 函数来手动转换数据。"
                )

        return PaginationResponse.create(
            items=row_responses,
            total=total,
            page_num=pageNum,
            page_size=pageSize
        )
