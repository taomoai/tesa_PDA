"""
事件相关的数据模式
"""
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class EventPublishRequest(BaseModel):
    """发布事件请求"""
    topic: str = Field(..., description="事件主题")
    payload: Dict[str, Any] = Field(..., description="事件载荷")
    correlation_id: Optional[str] = Field(None, description="关联ID")
    
    class Config:
        json_schema_extra = {
            "example": {
                "topic": "user.created.v1",
                "payload": {
                    "user_id": "12345",
                    "email": "user@example.com",
                    "name": "Test User"
                },
                "correlation_id": "req-123"
            }
        }


class EventStatusResponse(BaseModel):
    """事件状态响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="状态消息")
    event_id: Optional[str] = Field(None, description="事件ID")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Event published successfully",
                "event_id": "550e8400-e29b-41d4-a716-446655440000"
            }
        }