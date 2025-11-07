from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field
from datetime import datetime
from pydantic_validation_decorator import NotBlank, Network
from fastapi_app.schemas.schema import PaginationResponse
from fastapi_app.utils.safe_js import json_encoders_config


# --------枚举值-------------
class PdaTaskStatusEnum(str, Enum):
    """
    PDA文档处理状态枚举

    - pending: 已接收待解析
    - parsing: 解析中
    - parsing_failed: 解析失败
    - success: 成功
    """
    PENDING = "pending"  # 已接收待解析
    PARSING = 'parsing'  # 解析中
    PARSING_FAILED = 'parsing_failed'  # 解析失败
    SUCCESS = 'success'  # 成功


@dataclass(frozen=True)
class PdaTaskSummaryEnum:
    """
    PDA文档处理失败概要枚举
    """
    PROCESS_DOCUMENT_FAILED = "Process document failed"  # 处理文档失败
    AI_CLIENT_ERROR = "AI client get failed"  # AI客户端获取失败
    AI_CALL_FAILED = "AI call failed"  # AI调用失败
    AI_READING_FAILED = "AI reading failed"  # AI提取失败
    UNEXPECTED_ERROR = "Unexpected error"  # 预期之外的错误


# ------------数据模型------------
class PdaTaskCreate(BaseModel):
    """创建PDA文档任务模型（内部使用）"""
    file_name: str = Field(..., description="文件名")
    file_url: str = Field(..., description="文件URL")
    tenant_id: int = Field(..., description="租户ID")

    @NotBlank(field_name='file_name', message='pda.task.file_name_required')
    def get_file_name(self):
        return self.file_name

    @NotBlank(field_name='file_url', message='pda.task.file_url_required')
    @Network(field_name='file_url', field_type='HttpUrl', message='pda.task.file_url_invalid')
    def get_file_url(self):
        return self.file_url

    def validate_fields(self):
        self.get_file_name()
        self.get_file_url()


class PdaTaskUpdate(BaseModel):
    """更新PDA文档任务模型（内部代码使用）"""
    status: Optional[PdaTaskStatusEnum] = Field(default=None, description=PdaTaskStatusEnum.__doc__)
    finish_time: Optional[datetime] = Field(default=None, description="处理完成时间")
    failed_summary: Optional[str] = Field(default=None, description="处理失败概要")
    failed_reason: Optional[str] = Field(default=None, description="处理失败具体原因")
    raw_text: Optional[str] = Field(default=None, description="原始解析文本")
    structured_result: Optional[Dict[str, Any]] = Field(default=None, description="结构化处理结果")
    extral: Optional[Dict[str, Any]] = Field(default=None, description="额外信息")
    updated_by: Optional[str] = Field(default=None, description="更新人")


class PdaTaskListResponseItem(BaseModel):
    """PDA文档任务列表响应模型"""
    # 基本属性
    id: str = Field(..., description="记录ID")
    file_name: str = Field(..., description="文件名")
    file_url: str = Field(..., description="文件URL")
    preview_url: Optional[str] = Field(default=None, description="文件预览URL")
    task_id: Optional[str] = Field(default=None, description="任务ID")
    upload_time: datetime = Field(..., description="上传时间")
    finish_time: Optional[datetime] = Field(default=None, description="处理完成时间")
    # 处理状态与失败信息
    status: PdaTaskStatusEnum = Field(..., description=PdaTaskStatusEnum.__doc__)
    failed_summary: Optional[str] = Field(default=None, description="处理失败概要")
    failed_reason: Optional[str] = Field(default=None, description="处理失败具体原因")
    # 处理结果
    raw_text: Optional[str] = Field(default=None, description="原始解析文本")
    structured_result: Optional[Dict[str, Any]] = Field(default=None, description="结构化处理结果")

    class Config:
        from_attributes = True
        json_encoders = json_encoders_config


class PdaTaskResponse(PdaTaskListResponseItem):
    """PDA文档任务详情响应模型"""
    tenant_id: str = Field(..., description="租户ID")
    org_id: Optional[str] = Field(default=None, description="组织ID")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")
    created_by: str = Field(..., description="创建人")
    updated_by: Optional[str] = Field(default=None, description="更新人")

    class Config:
        from_attributes = True
        json_encoders = json_encoders_config


PdaTaskPagination = PaginationResponse[PdaTaskResponse]
'''文档处理分页模型'''
