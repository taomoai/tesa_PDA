"""
事件总线配置数据库模型
"""
import enum
from typing import Dict, Any
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB

from ..base import BaseModel
import json


class EventBusType(enum.Enum):
    """
    事件总线类型枚举
    """
    MEMORY = "memory"
    REDIS = "redis"
    RABBITMQ = "rabbitmq"
    KAFKA = "kafka"
    
    @classmethod
    def get_all_types(cls):
        """获取所有支持的总线类型"""
        return [bus_type.value for bus_type in cls]
    
    @classmethod
    def get_display_names(cls):
        """获取显示名称映射"""
        return {
            cls.MEMORY: "内存总线",
            cls.REDIS: "Redis发布订阅",
            cls.RABBITMQ: "RabbitMQ消息队列",
            cls.KAFKA: "Apache Kafka"
        }
    
    def get_display_name(self):
        """获取当前类型的显示名称"""
        return self.get_display_names().get(self, self.value)


class EventBusStatus(enum.Enum):
    """
    事件总线状态枚举
    """
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"
    ERROR = "error"


class EventBusPriority(enum.Enum):
    """
    事件总线优先级枚举
    """
    CRITICAL = 1  # 关键级别 - 核心业务数据
    IMPORTANT = 2  # 重要级别 - 运营监控数据
    NORMAL = 3    # 普通级别 - 分析统计数据
    
    @classmethod
    def get_display_names(cls):
        """获取显示名称映射"""
        return {
            cls.CRITICAL: "关键",
            cls.IMPORTANT: "重要", 
            cls.NORMAL: "普通"
        }
    
    def get_display_name(self):
        """获取当前优先级的显示名称"""
        return self.get_display_names().get(self, str(self.value))
    
    def get_resource_config(self):
        """获取优先级对应的资源配置"""
        configs = {
            self.CRITICAL: {
                "max_connections": 10,
                "max_retry": 5,
                "timeout": 30000,
                "circuit_breaker": False,
                "rate_limit": None
            },
            self.IMPORTANT: {
                "max_connections": 5,
                "max_retry": 3, 
                "timeout": 15000,
                "circuit_breaker": True,
                "rate_limit": 1000  # 1000/分钟
            },
            self.NORMAL: {
                "max_connections": 2,
                "max_retry": 1,
                "timeout": 5000,
                "circuit_breaker": True,
                "rate_limit": 100   # 100/分钟
            }
        }
        return configs.get(self, configs[self.NORMAL])
    
    @classmethod
    def get_display_names(cls):
        """获取状态显示名称映射"""
        return {
            cls.ACTIVE: "活跃",
            cls.INACTIVE: "未激活",
            cls.MAINTENANCE: "维护中",
            cls.ERROR: "错误"
        }
    
    def get_display_name(self):
        """获取当前状态的显示名称"""
        return self.get_display_names().get(self, self.value)


class EventBusConfig(BaseModel):
    """
    事件总线配置表
    
    存储不同类型事件总线的配置信息
    """
    __tablename__ = "event_bus_configs"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # 基本信息
    config_key = Column(String(50), unique=True, index=True, nullable=False, comment="配置唯一标识")
    name = Column(String(100), nullable=False, comment="配置名称")
    description = Column(Text, comment="配置描述")
    
    # 总线配置
    bus_type = Column(String(20), nullable=False, comment="总线类型")
    status = Column(String(20), default="inactive", comment="状态")
    priority = Column(Integer, default=3, comment="优先级(1=关键,2=重要,3=普通)")
    is_default = Column(Boolean, default=False, comment="是否为默认配置")
    is_internal = Column(Boolean, default=True, comment="是否为内部总线")
    
    # 连接配置（JSON格式存储具体配置）
    connection_config = Column(JSONB, nullable=False, comment="连接配置")
    
    # 扩展配置
    extra_config = Column(JSONB, default={}, comment="额外配置")
    
    def __repr__(self):
        return f"<EventBusConfig(key='{self.config_key}', type='{self.bus_type}', status='{self.status}')>"
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        custom_dict = {
            'id': self.id,
            'config_key': self.config_key,
            'name': self.name,
            'description': self.description,
            'bus_type': self.bus_type,
            'status': self.status,
            'priority': self.priority,
            'is_default': self.is_default,
            'is_internal': self.is_internal,
            'connection_config': self.connection_config,
            'extra_config': self.extra_config,
        }
        return super().to_dict(custom_dict)
    
    def get_bus_config(self) -> Dict[str, Any]:
        """获取用于创建事件总线的配置"""
        config = {
            'type': self.bus_type
        }
        # 确保 JSON 配置为 dict
        def ensure_dict(value):
            if isinstance(value, dict):
                return value
            if isinstance(value, str) and value.strip():
                try:
                    return json.loads(value)
                except Exception:
                    return {}
            return {}
        
        # 根据总线类型添加具体配置
        if self.bus_type == 'redis':
            config['redis'] = ensure_dict(self.connection_config)
        elif self.bus_type == 'rabbitmq':
            config['rabbitmq'] = ensure_dict(self.connection_config)
        elif self.bus_type == 'kafka':
            config['kafka'] = ensure_dict(self.connection_config)
        elif self.bus_type == 'memory':
            config['memory'] = ensure_dict(self.connection_config)
        
        # 合并额外配置
        if self.extra_config:
            config.update(ensure_dict(self.extra_config))
        
        return config
    
    def get_priority_enum(self) -> 'EventBusPriority':
        """获取优先级枚举对象"""
        try:
            return EventBusPriority(self.priority)
        except ValueError:
            return EventBusPriority.NORMAL
    
    def get_priority_resource_config(self) -> Dict[str, Any]:
        """获取优先级对应的资源配置"""
        priority_enum = self.get_priority_enum()
        return priority_enum.get_resource_config()
    
    def merge_priority_config(self) -> Dict[str, Any]:
        """合并优先级配置到extra_config中"""
        extra_config = self.extra_config or {}
        priority_config = self.get_priority_resource_config()
        
        # 合并配置，extra_config中的设置优先
        merged_config = priority_config.copy()
        merged_config.update(extra_config)
        
        return merged_config
    
    def is_critical_priority(self) -> bool:
        """判断是否为关键优先级"""
        return self.priority == EventBusPriority.CRITICAL.value
    
    def is_high_priority(self) -> bool:
        """判断是否为高优先级（关键或重要）"""
        return self.priority <= EventBusPriority.IMPORTANT.value
    
    @classmethod
    def get_default_config_templates(cls) -> Dict[EventBusType, Dict[str, Any]]:
        """获取默认配置模板"""
        return {
            EventBusType.MEMORY: {
                'max_queue_size': 1000,
                'enable_persistence': False
            },
            EventBusType.REDIS: {
                'host': 'localhost',
                'port': 6379,
                'password': None,
                'db': 0,
                'decode_responses': True,
                'socket_timeout': 5,
                'socket_connect_timeout': 5
            },
            EventBusType.RABBITMQ: {
                'host': 'localhost',
                'port': 5672,
                'username': 'guest',
                'password': 'guest',
                'virtual_host': '/',
                'exchange_name': 'events',
                'exchange_type': 'topic',
                'durable': True
            },
            EventBusType.KAFKA: {
                'bootstrap_servers': ['localhost:9092'],
                'group_id': 'taomoai_group',
                'auto_offset_reset': 'latest',
                'enable_auto_commit': True,
                'session_timeout_ms': 30000,
                'heartbeat_interval_ms': 10000
            }
        }