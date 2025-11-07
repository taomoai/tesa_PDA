import json
from pydantic import BaseModel, Field, ConfigDict, Json, field_validator
from typing import TypeVar, Generic, Any, Literal
from pydantic_validation_decorator import Size, FieldValidationError
from datetime import datetime, date
from fastapi_app.schemas.enums import FieldFilterModeEnum

# 定义泛型类型变量
T = TypeVar('T')

class FieldFilterSchema(BaseModel):
    """字段过滤参数Schema"""
    field_name: str = Field(..., description='字段名')
    values: list[Any] | None = Field(default=None, description='过滤值list')
    order: Literal['desc', 'asc', 'DESC', 'ASC'] | None = Field(default=None, description='排序方式')
    mode: FieldFilterModeEnum = Field(default=FieldFilterModeEnum.EQUAL, description='过滤模式')

    def get_order(self):
        if self.order and self.order.lower() not in {'asc', 'desc'}:
            raise FieldValidationError(model_name=self.__class__.__name__,
                                       field_name='order',
                                       field_value=self.order,
                                       message='排序方式只能是desc或asc')
        return self.order

    def validate_fields(self):
        """校验所有字段"""
        self.get_order()
        if self.values is None:  # 兼容 values 传 null
            self.values = []


class TimeFilterSchema(BaseModel):
    """时间范围筛选Schema"""
    field_name: str = Field(..., description='字段名')
    begin: date | datetime | None = Field(default=None, description='日期/时间起始点')
    end: date | datetime | None = Field(default=None, description='日期/时间结束点')
    order: Literal['desc', 'asc', 'DESC', 'ASC'] | None = Field(default=None, description='排序方式')

    def get_order(self):
        if self.order and self.order.lower() not in {'asc', 'desc'}:
            raise FieldValidationError(model_name=self.__class__.__name__,
                                       field_name='order',
                                       field_value=self.order,
                                       message='排序方式只能是desc或asc')
        return self.order

    def validate_fields(self):
        """校验所有字段"""
        self.get_order()


class PaginationBaseSchema(BaseModel):
    """通用基本分页查询参数Schema，只有页码和每页数量两个参数"""
    pageNum: int = Field(default=1, description='页码')
    pageSize: int = Field(default=20, description='每页数量')


class PaginationSchema(PaginationBaseSchema):
    """通用分页查询参数Schema"""
    filters: Json[list[FieldFilterSchema]] | None = Field(
        default_factory=list,
        description='**筛选条件（json字符串url编码）**\n'
                    '- 对每一列的筛选条件\n'
                    '- 格式：`[{...},{...}]`\n'
                    '- 对于每个 `{...}` 的结构：\n'
                    '  + field_name: 字段名，**必须**\n'
                    '  + values：`list`，值列表，默认空\n'
                    '  + order：desc/asc，不区分大小写，默认空\n'
                    '  + mode：过滤模式，对于`values`的每个值使用相同的模式。枚举如下：\n'
                    '    - `=`：全等，**默认值**\n'
                    '    - `!=`：不等\n'
                    '    - `contains`：包含\n'
                    '    - `starts_with`：以此开头\n'
                    '    - `ends_with`：以此结尾\n'
                    '    - `>`：大于\n'
                    '    - `<`：小于\n'
                    '    - `>=`：大于等于\n'
                    '    - `<=`：小于等于\n'
                    '- 此字段完整示例传参：\n'
                    '```\n'
                    '[\n'
                    '  {"field_name": "name", "values": ["刘", "abc"], "mode": "contains", "order": "desc"},\n'
                    '  {"field_name": "age", "values": [10], "mode": "<", "order": "asc"}\n'
                    ']\n'
                    '```\n'
                    '- **注意**：以字符串形式的json传入，注意做url编码'
        ,
        examples=['[{"field_name": "id", "values": ["123"]}]']
    )
    timeRanges: Json[list[TimeFilterSchema]] | None = Field(
        default_factory=list,
        description='**时间范围筛选（json字符串url编码）**\n'
                    '- 对每一列时间字段的筛选条件。只传begin代表大于此时间，只传end代表小于此时间，都传代表在此时间段内。\n'
                    '- 格式：`[{...},{...}]`\n'
                    '- 对于每个 `{...}` 的结构：\n'
                    '  + field_name: 字段名，**必须**\n'
                    '  + begin：日期/时间起始点，默认空\n'
                    '  + end：日期/时间结束点，默认空\n'
                    '  + order：desc/asc，不区分大小写，默认空'
                    '- 此字段完整示例传参：\n'
                    '```\n'
                    '[\n'
                    '  {"field_name": "created_at", "begin": "2025-09-01"},\n'
                    '  {"field_name": "upload_at", "begin": "2025-09-01T11:16:50.495Z", "end": "2025-11-01T11:16:50.495Z", "order": "asc"}\n'
                    ']\n'
                    '```\n'
                    '- **注意**：以字符串形式的json传入，注意做url编码'
        ,
        examples=['[{"field_name": "created_at", "begin": "2025-09-01T11:16:50.495Z"}]']
    )

    @field_validator('filters', 'timeRanges', mode='before')
    @classmethod
    def stringify_lists(cls, v: Any):
        """
        在验证前运行，将 list 输入转换为 JSON 字符串。
        这使得模型可以灵活地接受 str 或 list[dict] 或 list[FieldFilterSchema | TimeFilterSchema]。

        此方法兼容了以下三种传参方式::

            a = PaginationSchema(filters=[FieldFilterSchema(field_name="a",  values=["1"])])  # pydantic 模型

            b = PaginationSchema(filters=[{"field_name": "a", "values": ["1"]}])  # python 基本类型

            c = PaginationSchema(filters='[{"field_name": "a", "values": ["1"]}]')  # json 字符串
        """
        if isinstance(v, list):
            if all(map(lambda x: isinstance(x, (FieldFilterSchema, TimeFilterSchema)), v)):
                # 如果 list 中的元素都是 FieldFilterSchema 或 TimeFilterSchema，则转为 dict
                v = [x.model_dump() for x in v]
            # 将其 dump 成 string，以便 Json[T] 类型可以解析
            return json.dumps(v)
        if v is None or v == '':  # None/'' 转为空 list
            return '[]'
        # 如果输入是 str, 或其他，直接返回，让 Pydantic 继续处理
        return v

    @Size(field_name='pageNum', ge=1, message='页码数不应小于1')
    def check_page_num(self):
        """验证页码"""
        return self.pageNum

    @Size(field_name='pageSize', ge=1, le=5000, message='每页数量应在1~5000之间')
    def check_page_size(self):
        """验证每页数量"""
        return self.pageSize

    def validate_fields(self):
        """校验所有字段"""
        self.check_page_num()
        self.check_page_size()
        if self.filters:
            for ft in self.filters:
                ft.validate_fields()
        if self.timeRanges:
            for tr in self.timeRanges:
                tr.validate_fields()


class ApiResponse(BaseModel, Generic[T]):
    """通用API响应模型"""
    code: int = Field(0, description="响应状态码")
    message: str = Field(..., description="响应消息")
    data: T | None = Field(..., description="响应数据")


class PaginationResponse(BaseModel, Generic[T]):
    """通用分页响应模型"""
    items: list[T] = Field(..., description='数据列表')
    total: int = Field(..., description='总数量')
    pageNum: int = Field(..., description='当前页码')
    pageSize: int = Field(..., description='每页大小')
    totalPages: int = Field(..., description='总页数')
    hasNext: bool = Field(..., description='是否有下一页')
    
    @classmethod
    def create(cls, items: list[T], total: int, page_num: int, page_size: int):
        """创建分页响应"""
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        return cls(
            items=items,
            total=total,
            pageNum=page_num,
            pageSize=page_size,
            totalPages=total_pages,
            hasNext=page_num < total_pages
        )


class SimpleQueryOne(BaseModel):
    """一条简单查询结果的模型"""
    label: str = Field(..., description="用于显示的标签")
    value: str = Field(..., description="实际值")


SimpleQueryPagination = PaginationResponse[SimpleQueryOne]
'''简单查询分页结果模型'''


class BatchDeleteResult(BaseModel):
    """通用批量删除结果模型"""
    deleted_count: int = Field(0, description='已删除数量')
    total_requested: int = Field(0, description='请求删除总数')


class ExcelImportOneStatus(BaseModel):
    """Excel导入结果的单项数据模型"""
    row_num: int = Field(..., description="Excel中的行号")
    status: Literal['skipped', 'validation_failed', 'updated', 'failed', 'unresolved'] = Field(..., description="处理结果状态结果：跳过、校验失败、更新、失败、未解决")
    reason: str = Field(..., description="原因描述")


class ExcelImportResult(BaseModel):
    """Excel导入结果模型"""
    total_rows: int = Field(default=0, description="读取的总行数")
    success_count: int = Field(default=0, description="成功数量 (created + updated)")
    failed_count: int = Field(default=0, description="失败数量")
    skipped_count: int = Field(default=0, description="跳过数量")
    unresolved_count: int = Field(default=0, description="未解决/暂存数量")
    created_ids: list[str] = Field(default_factory=list, description="创建成功的记录ID列表")
    updated_ids: list[str] = Field(default_factory=list, description="更新成功的记录ID列表")
    details: list[ExcelImportOneStatus] = Field(default_factory=list, description="每一行的详细处理结果")


class UserInfo(BaseModel):
    """用户信息数据模型"""
    id: int = Field(..., description="用户ID")
    username: str = Field(..., description="用户的用户名")
    email: str = Field(..., description="用户的电子邮件地址")
    first_name: str | None = Field(default=None, description="用户的名")
    last_name: str | None = Field(default=None, description="用户的姓")
    company: str | None = Field(default=None, description="用户所在公司")
    business_type: str | None = Field(default=None, description="用户所属业务类型")
    role: str | None = Field(default=None, description="用户角色")
    country: str | None = Field(default=None, description="用户所在国家")
    type: str = Field(..., description="用户账户类型")
    status: str = Field(..., description="用户账户状态")
    is_delete: bool = Field(default=False, description="是否已删除")

    # 启用 from_attributes 模式，允许 Pydantic 从对象属性中读取数据
    model_config = ConfigDict(from_attributes=True)


class ContextInfo(BaseModel):
    """上下文信息"""
    user: UserInfo = Field(..., description='用户表信息')
    user_id: int = Field(..., description='用户ID')
    role_codes: list[str] = Field(..., description='用户的角色代码列表')
    tenant_id: int = Field(..., description='租户ID')
    belong_org: str | None = Field(default=None, description='用户在该租户的所属组织ID')
    manage_orgs: list[str] | None = Field(default=None, description='用户在该租户的管理组织ID列表')
    username: str = Field(..., description="用户姓名")

