"""
保留 base.py，重写一个 base_model.py 来定义更精简、更纯粹的 BaseModel

数据库模型基础类
包含所有表共用的系统字段
"""
from datetime import datetime, UTC
import pytz
from sqlalchemy import BIGINT, Column, String, DateTime, Boolean, Text
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import Session, validates
from sqlalchemy.ext.declarative import declared_attr
from decorators.db import before_insert, before_update
from fastapi_app.core.database import Base
from fastapi_app.core.context import safe_get_context_username


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
        return Column(BIGINT, primary_key=True, autoincrement=False, comment="ID")

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


@before_insert
@before_update
class BaseModel(Base, TimestampMixin):
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


@before_insert
@before_update
class BaseModelUnixTs(UnixTimestampMixin, BaseModel):
    """
    抽象基础模型（兼容 BIGINT 时间戳表）。
    不改表结构，仅用 UnixTimestampMixin 覆盖时间字段。
    """
    __abstract__ = True

