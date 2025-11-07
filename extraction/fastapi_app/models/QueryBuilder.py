from typing import Literal, Any, TypeVar, Generic, Callable

from loguru import logger
from sqlalchemy import select, Select, ColumnElement, and_, inspect, func, or_
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql._typing import (
    _ColumnExpressionArgument, _ColumnExpressionOrStrLabelArgument, _JoinTargetArgument,
    _OnClauseArgument, _FromClauseArgument, _SelectStatementForCompoundArgument
)
from sqlalchemy.sql.base import _NoArg

from fastapi_app.schemas.enums import FieldFilterModeEnum
from fastapi_app.schemas.schema import TimeFilterSchema, FieldFilterSchema, PaginationSchema

T = TypeVar("T", bound=DeclarativeBase)


class QueryBuilder(Generic[T]):
    """
    SELECT 语句构建器

    - sqlalchemy 的表模型基类的任意实体表模型类都可使用
    - 本构建器的链式调用将会始终更新内部的 Select 对象
    """

    def __init__(self,
                 model: type[T],
                 *,
                 fields: list[str | ColumnElement | type[DeclarativeBase]] | None = None,
                 exclude_deleted: bool = True,
                 stmt: Select | None = None):
        """
        SELECT 语句构建器

        - 初始化后将构建一个 select 基本语句，加上 is_delete=False 的筛选

        :param model: ORM 主表模型
        :param fields: select 的列/模型，可以视为对原 select 方法传参的扩展。
                       - 默认 (None): [model] (即 select(User))
                       - ['*']: [model] (即 select(User))
                       - ['name', 'email']: [model.name, model.email]
                       - [Supplier, Account.id]: [Supplier, Account.id]
                       - ['*', Supplier]: [model, Supplier] (即 select(User, Supplier))
        :param exclude_deleted: 是否默认排除已删除，默认是
        :param stmt: 直接指定一个 Select 对象作为核心来构建，若指定，则 fields 参数不应传入
        """
        assert stmt is None or isinstance(stmt, Select), "参数 stmt 必须是 sqlalchemy.Select 对象"
        self.reset_model(model)

        if isinstance(stmt, Select):
            assert not fields, "指定了 stmt 参数，则 fields 参数不应传入"
            self.stmt = stmt
        else:
            selected_columns: list[ColumnElement | type[DeclarativeBase]] = []
            if fields:
                for field in fields:
                    if field == '*':
                        # 添加主模型, 允许 ['*', Supplier] 这样的组合
                        if model not in selected_columns:
                            selected_columns.append(model)

                    # 支持字符串字段，直接从主模型获取
                    elif isinstance(field, str):
                        selected_columns.append(self.get_column(field))

                    # 支持 ORM 模型类
                    elif isinstance(field, type) and issubclass(field, DeclarativeBase):
                        selected_columns.append(field)

                    # 支持任意列对象
                    elif isinstance(field, ColumnElement):
                        selected_columns.append(field)
                    else:
                        raise TypeError(f"fields 列表中的项 '{field}' (类型 {type(field)}) 不是可识别的类型")

            # 如果循环后列表仍为空 (例如 fields=None 或 fields=[])，则默认使用主模型
            if not selected_columns:
                selected_columns = [model]

            self.stmt = select(*selected_columns)

            is_delete_column = self.get_column('is_delete', raise_for_missing=False)
            if is_delete_column is not None and exclude_deleted:
                self.where(is_delete_column == False)  # is_delete=False

    def __str__(self):
        return f'QueryBuilder(model={self.model.__name__}, stmt={self.stmt})'

    @property
    def stmt(self) -> Select:
        """
        获取当前查询语句
        :return: Select 语句对象
        """
        return self.__stmt

    @stmt.setter
    def stmt(self, stmt: Select):
        """
        设置当前查询语句
        :param stmt: Select 语句对象
        """
        assert isinstance(stmt, Select), f"参数 stmt 必须是 sqlalchemy.Select 对象，但实际是 {type(stmt)}"
        self.__stmt = stmt

    def reset_model(self, model: type[T]):
        """重设 ORM model，用于应用不同表的筛选条件"""
        self.model = model
        self._inspector = inspect(model)

    def get_column(self, field_name: str, raise_for_missing: bool = True) -> None | ColumnElement:
        """根据字段名获取列对象

        - 获取失败则默认抛错。可指定不抛错，而是返回None
        """
        try:
            field_prop = self._inspector.get_property(field_name)
            if not hasattr(field_prop, 'columns'):
                msg = f"ORM模型 {self.model.__name__} 表的字段 {field_name} 不是一个列属性，实际类型为 {type(field_prop)}"
                logger.warning(msg)
                if raise_for_missing:
                    raise ValueError(msg)
                return None
            return field_prop.columns[0]
        except (AttributeError, InvalidRequestError) as e:
            msg = f"ORM模型 {self.model.__name__} 表的字段 {field_name} 不存在: {str(e)}"
            logger.warning(msg)
            if raise_for_missing:
                raise ValueError(msg)
            return None

    def sql(self) -> str:
        """获取当前查询语句的SQL文本"""
        return self.to_sql(self.stmt)

    def build(self) -> Select:
        """返回当前已构建的select对象"""
        return self.stmt

    # -------------------- 构建 SELECT 语句基本方法（复写自Select的常用方法） --------------------

    def where(self, *whereclause: _ColumnExpressionArgument[bool]) -> 'QueryBuilder[T]':
        """添加 where 条件

        - 同 select(...).where 的用法
        - 示例：``where(User.id==1,func.lower(User.name).contains('john'))``
        """
        self.stmt = self.stmt.where(*whereclause)
        return self

    def filter_by(self, **kwargs: Any) -> 'QueryBuilder[T]':
        """添加 filter_by 语句

        - 同 select(...).filter_by 的用法
        - 示例：``filter_by(id=1)``
        """
        self.stmt = self.stmt.filter_by(**kwargs)
        return self

    def having(self, *having: _ColumnExpressionArgument[bool]) -> 'QueryBuilder[T]':
        """添加 having 语句

        - 同 select(...).having 的用法
        - 示例：``having(func.count(User.id)>10)``
        """
        self.stmt = self.stmt.having(*having)
        return self

    def distinct(self, *expr: _ColumnExpressionArgument[Any]) -> 'QueryBuilder[T]':
        """添加 distinct 语句

        - 同 select(...).distinct 的用法
        - 示例：``distinct(User.id)``
        """
        self.stmt = self.stmt.distinct(*expr)
        return self

    def select_from(self, *froms: _FromClauseArgument) -> 'QueryBuilder[T]':
        """添加 from 语句

        - 同 select(...).select_from 的用法
        - 示例：``select_from(User)``
        """
        self.stmt = self.stmt.select_from(*froms)
        return self

    def order_by(self, __first: Literal[None, _NoArg.NO_ARG] | _ColumnExpressionOrStrLabelArgument[Any] = _NoArg.NO_ARG,
                 *clauses: _ColumnExpressionOrStrLabelArgument[Any]):
        """添加 order by 语句

        - 同 select(...).order_by 的用法
        - 示例：``order_by(User.id.desc(),Account.id.desc())``
        """
        self.stmt = self.stmt.order_by(__first, *clauses)
        return self

    def group_by(self, __first: Literal[None, _NoArg.NO_ARG] | _ColumnExpressionOrStrLabelArgument[Any] = _NoArg.NO_ARG,
        *clauses: _ColumnExpressionOrStrLabelArgument[Any],) -> 'QueryBuilder[T]':
        """添加 group by 语句

        - 同 select(...).group_by 的用法
        - 示例：``group_by(User.id)``
        """
        self.stmt = self.stmt.group_by(__first, *clauses)
        return self

    def join(self, target: _JoinTargetArgument, onclause: _OnClauseArgument | None = None, *, isouter: bool = False,
             full: bool = False) -> 'QueryBuilder[T]':
        """添加 join 语句

        - 同 select(...).join 的用法
        - 示例：``join(User.id==Account.user_id)``
        """
        self.stmt = self.stmt.join(target, onclause, isouter=isouter, full=full)
        return self

    def outerjoin(self, target: _JoinTargetArgument, onclause: _OnClauseArgument | None = None, *,
                  full: bool = False) -> 'QueryBuilder[T]':
        """添加 outer join 语句

        - 同 select(...).outerjoin 的用法
        - 示例：``outerjoin(User.id==Account.user_id)``
        """
        self.stmt = self.stmt.outerjoin(target, onclause, full=full)
        return self

    def join_from(self, from_: _FromClauseArgument, target: _JoinTargetArgument,
                  onclause: _OnClauseArgument | None = None, *, isouter: bool = False,
                  full: bool = False) -> 'QueryBuilder[T]':
        """添加 join_from 语句

        - 同 select(...).join_from 的用法
        - 示例：``join_from(User, User.id==Account.user_id)``
        """
        self.stmt = self.stmt.join_from(from_, target, onclause, isouter=isouter, full=full)
        return self

    def outerjoin_from(self, from_: _FromClauseArgument, target: _JoinTargetArgument,
                       onclause: _OnClauseArgument | None = None, *, full: bool = False) -> 'QueryBuilder[T]':
        """
        添加 outer join_from 语句

        - 同 select(...).outerjoin_from 的用法
        - 示例：``outerjoin_from(User, User.id==Account.user_id)``
        """
        self.stmt = self.stmt.outerjoin_from(from_, target, onclause, full=full)
        return self

    def union(self, *other: _SelectStatementForCompoundArgument) -> 'QueryBuilder[T]':
        """添加 union 语句

        - 同 select(...).union 的用法
        - 示例：``union(select(User.id))``
        """
        self.stmt = self.stmt.union(*other)
        return self

    # -------------------- 筛选条件应用方法 --------------------
    def apply_contains_filter(self, column: ColumnElement, values: list[str] | None):
        """便捷添加一个忽略大小写的 where 条件。仅对字符串类型的列有效。"""
        assert values is None or (isinstance(values, list) and all(isinstance(v, str) for v in values)), "values 参数必须是字符串列表"
        if values:
            self.where(or_(func.lower(column).contains(v.lower()) for v in values))
        return self

    def apply_order(self, field: ColumnElement, order: Literal['desc', 'asc', 'DESC', 'ASC'] | None) -> 'QueryBuilder[T]':
        """
        应用排序条件

        - 此方法需传入具体的表模型字段

        :param field: 表模型的字段对象，如：User.id
        :param order: 排序条件字符串，格式为 "字段名 [ASC|DESC]"。
        :return: 应用了排序条件的新 Select 语句对象。
        """
        if not order:
            return self
        order = order.lower()
        if order not in ('desc', 'asc'):
            return self
        self.stmt = self.stmt.order_by(field.desc() if order == "desc" else field.asc())
        return self

    def _apply_time_range_clause(self, column: ColumnElement, time_range: TimeFilterSchema) -> 'QueryBuilder[T]':
        """
        [私有] 仅应用时间范围的 where 逻辑

        :param column: 已解析的列对象。
        :param time_range: 时间筛选条件。
        """
        self.where(
            and_(
                column >= time_range.begin if time_range.begin else True,
                column <= time_range.end if time_range.end else True
            )
        )
        return self

    def _apply_filter_clause(self, column: ColumnElement, field_filter: FieldFilterSchema) -> 'QueryBuilder[T]':
        """
        [私有] 仅应用字段筛选的 where 逻辑

        :param column: 已解析的列对象。
        :param field_filter: 字段筛选条件。
        """
        ft = field_filter
        bool_map = {'true': True, 'false': False}

        # 无筛选值则不添加筛选
        if not (fvs := ft.values):
            return self

        # 列类型为布尔值，则兼容传值为字符串形式的 true/false
        if column.type.python_type is bool and fvs:
            fvs = [bool_map.get(v.lower(), v) if isinstance(v, str) else v for v in fvs]

        if ft.mode in {FieldFilterModeEnum.CONTAINS, FieldFilterModeEnum.STARTS_WITH, FieldFilterModeEnum.ENDS_WITH}:
            if column.type.python_type is not str:
                logger.error(f"筛选模式 {ft.mode} 只支持字符串类型，而字段 {ft.field_name} 的类型为 {column.type.python_type}")
            if any(not isinstance(v, str) for v in fvs):
                raise ValueError(f"字段 {ft.field_name} 的筛选模式 {ft.mode} 只支持字符串类型，而筛选值 {fvs} 中有非字符串值")

        match ft.mode:
            case FieldFilterModeEnum.EQUAL:
                self.where(column == fvs[0]) if len(fvs) == 1 else self.where(column.in_(fvs))
            case FieldFilterModeEnum.NOT_EQUAL:
                self.where(column != fvs[0]) if len(fvs) == 1 else self.where(column.notin_(fvs))
            case FieldFilterModeEnum.CONTAINS:
                self.where(or_(func.lower(column).contains(str(v).lower()) for v in fvs))
            case FieldFilterModeEnum.STARTS_WITH:
                self.where(or_(func.lower(column).startswith(str(v).lower()) for v in fvs))
            case FieldFilterModeEnum.ENDS_WITH:
                self.where(or_(func.lower(column).endswith(str(v).lower()) for v in fvs))
            case FieldFilterModeEnum.GREATER_THAN:
                self.where(or_(column > v for v in fvs))
            case FieldFilterModeEnum.LESS_THAN:
                self.where(or_(column < v for v in fvs))
            case FieldFilterModeEnum.GREATER_THAN_OR_EQUAL:
                self.where(or_(column >= v for v in fvs))
            case FieldFilterModeEnum.LESS_THAN_OR_EQUAL:
                self.where(or_(column <= v for v in fvs))

        return self

    def _apply_having_clause(self, column: ColumnElement, field_filter: FieldFilterSchema) -> 'QueryBuilder[T]':
        """
        [私有] 仅应用字段筛选的 having 逻辑

        :param column: 已解析的列对象 (通常是聚合函数)。
        :param field_filter: 字段筛选条件。
        """
        ft = field_filter
        bool_map = {'true': True, 'false': False}

        # 无筛选值则不添加筛选
        if not (fvs := ft.values):
            return self

        # (这里的类型检查逻辑与 _apply_filter_clause 完全一致)
        if column.type.python_type is bool and fvs:
            fvs = [bool_map.get(v.lower(), v) if isinstance(v, str) else v for v in fvs]

        if ft.mode in {FieldFilterModeEnum.CONTAINS, FieldFilterModeEnum.STARTS_WITH,
                       FieldFilterModeEnum.ENDS_WITH}:
            if column.type.python_type is not str:
                logger.error(f"筛选模式 {ft.mode} 只支持字符串类型，而字段 {ft.field_name} 的类型为 {column.type.python_type}")
            if any(not isinstance(v, str) for v in fvs):
                logger.error(f"字段 {ft.field_name} 的筛选模式 {ft.mode} 只支持字符串类型，而筛选值 {fvs} 中有非字符串值")

        # 核心区别：使用 self.having() 而不是 self.where()
        match ft.mode:
            case FieldFilterModeEnum.EQUAL:
                self.having(column == fvs[0]) if len(fvs) == 1 else self.having(column.in_(fvs))
            case FieldFilterModeEnum.NOT_EQUAL:
                self.having(column != fvs[0]) if len(fvs) == 1 else self.having(column.notin_(fvs))
            case FieldFilterModeEnum.CONTAINS:
                self.having(or_(func.lower(column).contains(str(v).lower()) for v in fvs))
            case FieldFilterModeEnum.STARTS_WITH:
                self.having(or_(func.lower(column).startswith(str(v).lower()) for v in fvs))
            case FieldFilterModeEnum.ENDS_WITH:
                self.having(or_(func.lower(column).endswith(str(v).lower()) for v in fvs))
            case FieldFilterModeEnum.GREATER_THAN:
                self.having(or_(column > v for v in fvs))
            case FieldFilterModeEnum.LESS_THAN:
                self.having(or_(column < v for v in fvs))
            case FieldFilterModeEnum.GREATER_THAN_OR_EQUAL:
                self.having(or_(column >= v for v in fvs))
            case FieldFilterModeEnum.LESS_THAN_OR_EQUAL:
                self.having(or_(column <= v for v in fvs))

        return self

    # ----- 【核心】分页查询 -----
    def apply_pagination(
            self,
            page_query: PaginationSchema,
            *,
            column_map: dict[str, ColumnElement] | None = None,
            having_map: dict[str, ColumnElement] | None = None,
            contains_fields: set[str] | None = None,
            custom_filter_handlers: dict[str, Callable[['QueryBuilder[T]', FieldFilterSchema], ColumnElement | None]] | None = None
    ) -> 'QueryBuilder[T]':
        """
        应用分页查询中的所有筛选和排序条件。

        - 此方法是处理筛选和排序的推荐方式，尤其是在处理联表查询时。
        - 保证排序条件的应用顺序与 page_query 中定义的顺序一致。
        - 此方法会按以下优先级解析字段并应用筛选：
            1. custom_filter_handlers: 使用自定义函数处理筛选，函数返回值用于排序。
            2. having_map: 字段将使用 HAVING 子句 (用于聚合筛选)。
            3. column_map: 字段将使用 WHERE 子句 (用于联表筛选)。
            4. self.model: 字段将使用 WHERE 子句 (用于主表筛选)。


        示例::

            # 假设 page_query 包含以下 filters:
            # [
            #   {"field_name": "name", "values": ["john"], "order": "asc"},
            #   {"field_name": "account_count", "values": [2], "mode": ">="},
            #   {"field_name": "email_domain", "values": ["example.com"]},
            #   {"field_name": "description", "values": ["dev"]}
            # ]
            page_query: PaginationSchema = ... # (从请求参数获取)

            # 定义自定义处理器 (用于 custom_filter_handlers)
            def handle_email_domain(builder: QueryBuilder[User], ft: FieldFilterSchema) -> ColumnElement | None:
                if ft.values:       # 自行应用 .where() 逻辑
                    builder.where(or_(User.email.endswith(f"@{domain}") for domain in ft.values))
                return User.email   # 返回用于排序的列

            # 定义聚合列 (用于 having_map)
            account_count_col = func.count(Account.id).label("account_count")

            # 主句构建（这个主句也能在 QueryBuilder 中构建）
            stmt = select(User, account_count_col).outerjoin(
                Account, User.id == Account.user_id
            ).group_by(User.id)

            builder = QueryBuilder(model=User, stmt=stmt)

            # ===================核心调用方式：=====================
            builder.apply_pagination(
                page_query,
                column_map={'company_name': Company.name}, # 映射联表字段 (WHERE)
                having_map={'account_count': account_count_col}, # 映射聚合字段 (HAVING)
                contains_fields={'name', 'description', 'company_name'},  # 设为模糊查询的字段 (主表或Map中的字段均可)
                custom_filter_handlers={'email_domain': handle_email_domain} # 注册自定义处理器
            )



        :param page_query: 包含 filters 和 timeRanges 的分页查询对象。
        :param column_map: WHERE 条件的字段映射(联表)，用于将 "field_name" 字符串映射到实际的 SQLAlchemy 列对象。
        :param having_map: HAVING 条件的字段映射(聚合)，用于将 "field_name" 字符串映射到聚合列对象。
        :param contains_fields: 自动设为忽略大小写模糊查询的字段名集合。
        :param custom_filter_handlers:
                自定义筛选处理器。字典的 key 是 field_name，value 是一个函数，
                该函数接收 (builder, filter_schema) 并应用筛选逻辑，然后返回用于排序的 ColumnElement (或 None)。

        :return: 返回自身，支持链式调用。
        :rtype: QueryBuilder[T]
        """
        column_map = column_map or {}
        having_map = having_map or {}
        contains_fields = contains_fields or set()
        custom_filter_handlers = custom_filter_handlers or {}

        # 核心：一个列表，用于按顺序收集所有排序条件
        order_clauses: list[tuple[ColumnElement, str | None]] = []

        # 1. 处理字段筛选 (Field Filters)
        for ft in (page_query.filters or []):
            field_name: str = ft.field_name
            col: None | ColumnElement = None

            # 优先级 1: 检查 Custom Handlers
            if field_name in custom_filter_handlers:
                handler = custom_filter_handlers[field_name]
                # 自定义处理器负责应用筛选 (where/having)
                # 并返回用于排序的列
                col = handler(self, ft)

            # 优先级 2: 检查 Having Map
            elif field_name in having_map:
                col = having_map[field_name]
                self._apply_having_clause(col, ft)

            # 优先级 3 & 4: 检查 Column Map 和主模型 (应用 Where 逻辑)
            else:
                if field_name in column_map:
                    col = column_map[field_name]
                else:
                    col = self.get_column(field_name, raise_for_missing=False)

                if col is None:
                    logger.warning(f"[QueryBuilder] 字段 '{field_name}' 在 maps 和主模型中均未找到，已跳过。")
                    continue

                # 仅在这里应用 Where 逻辑
                ft_clone = ft.model_copy()
                if field_name in contains_fields:
                    ft_clone.mode = FieldFilterModeEnum.CONTAINS
                self._apply_filter_clause(col, ft_clone)

            # 按顺序添加排序条件
            order_clauses.append((col, ft.order))

        # 2. 处理时间范围筛选 (Time Ranges)：时间范围始终用 WHERE 子句
        for tr in (page_query.timeRanges or []):
            field_name: str = tr.field_name
            col: None | ColumnElement = column_map.get(field_name)
            if col is None:
                col = self.get_column(field_name, raise_for_missing=False)

            if col is None:
                logger.warning(f"[QueryBuilder] 时间字段 '{field_name}' 在 {self.model.__name__} 或 column_map 中均未找到，已跳过。")
                continue

            self._apply_time_range_clause(col, tr)
            order_clauses.append((col, tr.order))

        # 3. 按收集到的顺序，一次性应用所有排序
        for col, order in order_clauses:
            if col is not None:
                self.apply_order(col, order)

        return self

    # -------------------- 静态公共方法 --------------------

    @staticmethod
    def to_sql(stmt: Select) -> str:
        """[静态方法] 将指定 SELECT 语句对象转为sql语句"""
        return str(stmt.compile(compile_kwargs={"literal_binds": True}))

    @staticmethod
    def get_column_by_name(model: type[T], field_name: str) -> ColumnElement:
        """[静态方法] 根据字段名获取列对象"""
        inspector = inspect(model)
        try:
            field_prop = inspector.get_property(field_name)
            if not hasattr(field_prop, 'columns'):
                raise ValueError(
                    f"ORM模型 {model.__name__} 表的字段 {field_name} 不是一个列属性，实际类型为 {type(field_prop)}")
            return field_prop.columns[0]
        except (AttributeError, InvalidRequestError) as e:
            raise ValueError(f"ORM模型 {model.__name__} 表的字段 {field_name} 不存在: {str(e)}")

    # -------------------- 构建新的 QueryBuilder 对象 --------------------

    @staticmethod
    def new_label_value(model: type[T], tenant_id: int, label_field='name', value_field='id') -> 'QueryBuilder[T]':
        """
        构建 QueryBuilder 对象，将字段别名为 label 和 value

        - 返回全新的QueryBuilder

        :param model: ORM 表模型类
        :param tenant_id: 租户ID
        :param label_field: json字段 label 对应的ORM模型字段名
        :param value_field: json字段 value 对应的ORM模型字段名
        :return: 新的 QueryBuilder 对象
        """
        inspector = inspect(model)
        try:
            is_active_col: ColumnElement = inspector.get_property('is_active').columns[0]
            tenant_id_col: ColumnElement = inspector.get_property('tenant_id').columns[0]
            is_delete_col: ColumnElement = inspector.get_property('is_delete').columns[0]
            label_col: ColumnElement = inspector.get_property(label_field).columns[0]
            value_col: ColumnElement = inspector.get_property(value_field).columns[0]
        except (AttributeError, InvalidRequestError) as e:
            # 捕获并提供更友好的错误信息
            raise AttributeError(f'ORM模型 "{model.__name__}" 缺少必要的字段。错误: {e}')
        return QueryBuilder(model=model, fields=[label_col.label('label'), value_col.label('value')]).where(
            is_delete_col == False,
            is_active_col == True,
            tenant_id_col == tenant_id
        )
