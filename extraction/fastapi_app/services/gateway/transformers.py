"""
事件转换器

实现反腐化层(ACL)的事件转换逻辑，
将外部事件格式转换为内部标准格式
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime
from loguru import logger

from fastapi_app.bus import Event
from fastapi_app.bus.topics import Topics


class EventTransformer(ABC):
    """
    事件转换器抽象基类
    
    定义了所有转换器必须实现的接口
    """
    
    @abstractmethod
    def can_transform(self, external_event: Event) -> bool:
        """
        检查是否能够转换指定的外部事件
        
        Args:
            external_event: 外部事件
            
        Returns:
            bool: 是否支持转换
        """
        pass
    
    @abstractmethod
    def transform(self, external_event: Event) -> Optional[Event]:
        """
        将外部事件转换为内部事件
        
        Args:
            external_event: 外部事件
            
        Returns:
            Optional[Event]: 转换后的内部事件，None表示跳过
        """
        pass
    
    def validate_external_payload(self, payload: Dict[str, Any]) -> bool:
        """
        验证外部事件载荷
        
        Args:
            payload: 事件载荷
            
        Returns:
            bool: 是否有效
        """
        return isinstance(payload, dict) and len(payload) > 0
    
    def add_internal_metadata(self, event: Event, source: str = "gateway") -> None:
        """
        添加内部元数据
        
        Args:
            event: 事件对象
            source: 事件来源
        """
        event.source = source
        event.metadata.update({
            'transformed_at': datetime.utcnow().isoformat(),
            'transformer': self.__class__.__name__
        })


# 删除了不需要的转换器类：UserEventTransformer、OrderEventTransformer、InventoryEventTransformer