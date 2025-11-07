"""
事件总线配置相关的数据模式
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from fastapi_app.models.event_bus import EventBusType, EventBusStatus


class EventBusConfigBase(BaseModel):
    """事件总线配置基础模式"""
    config_key: str = Field(..., min_length=1, max_length=50, description="配置唯一标识")
    name: str = Field(..., min_length=1, max_length=100, description="配置名称")
    description: Optional[str] = Field(None, description="配置描述")
    bus_type: EventBusType = Field(..., description="总线类型")
    is_default: bool = Field(False, description="是否为默认配置")
    is_internal: bool = Field(True, description="是否为内部总线")
    connection_config: Dict[str, Any] = Field(..., description="连接配置")
    extra_config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="额外配置")
    
    @field_validator('config_key')
    def validate_config_key(cls, v):
        """验证配置key格式"""
        if not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError('配置key只能包含字母、数字、下划线和连字符')
        return v.lower()
    
    @field_validator('connection_config')
    def validate_connection_config(cls, v, values):
        """根据总线类型验证连接配置"""
        bus_type = values.get('bus_type')
        if not bus_type:
            return v
        
        required_fields = {
            EventBusType.REDIS: ['host', 'port'],
            EventBusType.RABBITMQ: ['host', 'port', 'username', 'password'],
            EventBusType.KAFKA: ['bootstrap_servers'],
            EventBusType.MEMORY: []  # 内存总线不需要必须字段
        }
        
        required = required_fields.get(bus_type, [])
        for field in required:
            if field not in v:
                raise ValueError(f'{bus_type.value}总线配置缺少必须字段: {field}')
        
        return v


class EventBusConfigCreate(EventBusConfigBase):
    """创建事件总线配置请求"""
    created_by: Optional[str] = Field(None, description="创建者")
    
    class Config:
        json_schema_extra = {
            "example": {
                "config_key": "redis_main",
                "name": "Redis主总线",
                "description": "主要的Redis事件总线配置",
                "bus_type": "redis",
                "is_default": True,
                "is_internal": True,
                "connection_config": {
                    "host": "localhost",
                    "port": 6379,
                    "password": None,
                    "db": 0
                },
                "extra_config": {
                    "socket_timeout": 5
                },
                "created_by": "admin"
            }
        }


class EventBusConfigUpdate(BaseModel):
    """更新事件总线配置请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="配置名称")
    description: Optional[str] = Field(None, description="配置描述")
    is_default: Optional[bool] = Field(None, description="是否为默认配置")
    is_internal: Optional[bool] = Field(None, description="是否为内部总线")
    connection_config: Optional[Dict[str, Any]] = Field(None, description="连接配置")
    extra_config: Optional[Dict[str, Any]] = Field(None, description="额外配置")
    updated_by: Optional[str] = Field(None, description="更新者")


class EventBusStatusUpdate(BaseModel):
    """更新事件总线状态请求"""
    status: EventBusStatus = Field(..., description="新状态")
    updated_by: Optional[str] = Field(None, description="更新者")


class EventBusConfigResponse(BaseModel):
    """事件总线配置响应"""
    id: int
    config_key: str
    name: str
    description: Optional[str]
    bus_type: str
    bus_type_display: str = Field(..., description="总线类型显示名称")
    status: str
    status_display: str = Field(..., description="状态显示名称")
    is_default: bool
    is_internal: bool
    connection_config: Dict[str, Any]
    extra_config: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]
    updated_by: Optional[str]
    
    class Config:
        from_attributes = True


class EventBusConfigList(BaseModel):
    """事件总线配置列表响应"""
    items: List[EventBusConfigResponse]
    total: int
    page: int = Field(1, ge=1, description="页码")
    page_size: int = Field(10, ge=1, le=100, description="每页数量")
    
    @property
    def total_pages(self) -> int:
        """总页数"""
        return (self.total + self.page_size - 1) // self.page_size


class EventBusConfigTemplate(BaseModel):
    """事件总线配置模板"""
    bus_type: EventBusType
    bus_type_display: str
    template_config: Dict[str, Any]
    required_fields: List[str]
    optional_fields: List[str]
    description: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "bus_type": "redis",
                "bus_type_display": "Redis发布订阅",
                "template_config": {
                    "host": "localhost",
                    "port": 6379,
                    "password": None,
                    "db": 0
                },
                "required_fields": ["host", "port"],
                "optional_fields": ["password", "db", "socket_timeout"],
                "description": "Redis发布订阅模式的事件总线"
            }
        }