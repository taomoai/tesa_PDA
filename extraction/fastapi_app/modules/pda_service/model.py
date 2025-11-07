from datetime import datetime, UTC
from typing import Optional

import pytz
from sqlalchemy import Column, String, Text, Boolean, BIGINT, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import transaction, readonly
from fastapi_app.models.base import BaseModel
from fastapi_app.schemas.schema import FieldFilterSchema
from .schema import PdaTaskCreate, PdaTaskStatusEnum

class PdaDocumentExtractionTask(BaseModel):
    """PDA文档处理表 - 存储上传的文件信息以及处理结果"""
    __tablename__ = 'pda_document_extraction_tasks'

    # 基本字段
    id = Column(String(36), primary_key=True, index=True, comment='ID')
    file_name = Column(Text, nullable=False, comment='文件名')
    file_url = Column(Text, nullable=False, comment='文件URL')
    task_id = Column(Text, nullable=True, index=True, comment='任务ID')
    upload_time = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, comment="上传时间")
    finish_time = Column(DateTime(timezone=True), nullable=True, comment="处理完成时间")
    status: Mapped[PdaTaskStatusEnum] = mapped_column(String(20), nullable=False, default=PdaTaskStatusEnum.PENDING,
                                                      comment='处理状态(pending/parsing/parsing_failed/success)')
    failed_summary = Column(Text, nullable=True, comment='处理失败概要')
    failed_reason = Column(Text, nullable=True, comment='处理失败具体原因')

    # 系统关联字段
    tenant_id = Column(BIGINT, nullable=False, index=True, comment='租户ID')
    org_id = Column(String(36), nullable=True, index=True, comment='组织ID')

    # 处理结果
    raw_text = Column(Text, nullable=True, comment='原始解析文本')
    structured_result = Column(JSONB, nullable=True, comment='结构化处理结果')
    extral = Column(JSONB, nullable=True, comment='额外信息')

    def to_dict(self):
        """转换为字典"""
        def format_timestamp(value):
            """处理时间戳的辅助函数"""
            if value is None or isinstance(value, str):
                return None
            return value.astimezone(pytz.timezone('Asia/Shanghai')).isoformat()

        custom_dict = {
            'id': self.id,
            'file_name': self.file_name,
            'file_url': self.file_url,
            'task_id': self.task_id,
            'upload_time': format_timestamp(self.upload_time),
            'finish_time': format_timestamp(self.finish_time),
            'status': self.status,
            'failed_summary': self.failed_summary,
            'failed_reason': self.failed_reason,
            'raw_text': self.raw_text,
            'structured_result': self.structured_result,
            'created_by': self.created_by,
            'updated_by': self.updated_by,
            'tenant_id': str(self.tenant_id),
            'org_id': self.org_id,
            'extral': self.extral,
        }
        # 添加基础模型的系统字段
        return super().to_dict(custom_dict)

    @classmethod
    @transaction()
    async def insert_pda_document_extraction_task(cls, task_data: PdaTaskCreate, *, db: AsyncSession = None):
        """插入PDA文档处理任务"""
        db_task = cls(**task_data.model_dump())
        db.add(db_task)
        await db.flush()
        return db_task

    @classmethod
    @readonly()
    async def select_pda_task_by_id(cls, record_id: str, tenant_id: int, *, db: AsyncSession = None) -> Optional['PdaDocumentExtractionTask']:
        """根据主键ID和租户ID获取任务"""
        query = cls.build_query(filters=[
            FieldFilterSchema(field_name='id', values=[record_id]),
            FieldFilterSchema(field_name='tenant_id', values=[tenant_id]),
        ])
        result = await db.execute(query)
        return result.scalar_one_or_none()

