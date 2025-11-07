from sqlalchemy import Column, String, BIGINT, Boolean, Text
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import readonly
from fastapi_app.models.base import BaseModelUnixTs as BaseModel
from fastapi_app.schemas.schema import FieldFilterSchema


class Tenant(BaseModel):
    """租户模型"""
    __tablename__ = 'tenants'
    # 兼容历史表结构：tenants 表不存在 created_by/updated_by 列
    created_by = None
    updated_by = None

    name = Column(String(100), unique=True, nullable=False)
    code = Column(Text, unique=True, nullable=False)
    logo = Column(String(255))
    description = Column(String(500))
    business_type = Column(String(50))
    country = Column(String(50))
    status = Column(String(20), default='ENABLED')

    def to_dict(self):
        """转换为字典 (用于列表)"""
        custom_fields = {
            'name': self.name,
            'logo': self.logo,
            'description': self.description,
            'business_type': self.business_type,
            'country': self.country
        }
        return super().to_dict(custom_fields)

    def to_detail_dict(self):
        """转换为详情字典 (包含管理员信息)"""
        base_dict = self.to_dict()
        base_dict['admin'] = None  # 初始化管理员信息字段
        return base_dict

    @classmethod
    @readonly()
    async def select_tenant_id_by_code(cls, code: str, *, db: AsyncSession = None) -> int | None:
        """根据 tenant_code 获取 tenant_id"""
        query = cls.build_query(select_fields=['id'], filters=[
            FieldFilterSchema(field_name='code', values=[code])
        ])
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @classmethod
    @readonly()
    async def select_all_tenant_ids(cls, *, db: AsyncSession = None) -> list[int]:
        """获取所有有效租户的 ID"""
        query = cls.build_query(select_fields=['id'], filters=[
            FieldFilterSchema(field_name='status', values=['ENABLED']),
            FieldFilterSchema(field_name='is_delete', values=[False])
        ])
        result = await db.execute(query)
        return [row.id for row in result.all()]
