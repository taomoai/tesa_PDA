"""
边界网关服务

负责管理外部事件总线和内部事件总线之间的连接和数据流转
"""
import asyncio
from typing import Dict, Any, Optional
from loguru import logger

from fastapi_app.bus import AbstractEventBus, discover_handlers, get_external_handlers_for_bus

class GatewayService:
    """
    边界网关服务
    
    职责：
    1. 管理外部和内部事件总线的连接
    2. 协调事件处理器的注册
    3. 监控网关状态
    4. 提供优雅关闭机制
    """
    
    def __init__(
        self, 
        external_buses: Dict[str, AbstractEventBus],
        internal_bus: AbstractEventBus
    ):
        """
        初始化网关服务
        
        Args:
            external_buses: 已连接的外部事件总线实例字典 {config_key: bus_instance}
            internal_bus: 已连接的内部事件总线实例
        """
        self.external_buses = external_buses
        self.internal_bus = internal_bus
        self._registered_handlers = {}  # 记录已注册的处理器 {config_key: {topic: [handlers]}}
        
        self._running = False
        self._startup_complete = False
    
    async def start(self) -> None:
        """启动网关服务"""
        if self._running:
            logger.warning("[GatewayService] Service is already running")
            return
        
        try:
            logger.info("[GatewayService] Starting gateway service...")
            
            # 检查所有总线连接状态
            for config_key, external_bus in self.external_buses.items():
                if not external_bus.is_connected:
                    raise ValueError(f"External bus {config_key} is not connected")
            
            if not self.internal_bus.is_connected:
                raise ValueError("Internal bus is not connected")
            
            logger.info(f"[GatewayService] All {len(self.external_buses)} external buses and internal bus are connected")
            
            # 自动发现网关事件处理器（内部 + 外部）
            discover_handlers('fastapi_app.services.gateway.internal_event_handlers')
            discover_handlers('fastapi_app.services.gateway.external_event_handlers')
            
            # 为每个外部总线注册装饰器处理器
            await self._register_decorator_handlers()
            
            self._running = True
            self._startup_complete = True
            
            logger.info("[GatewayService] Gateway service started successfully")
            
        except Exception as e:
            logger.error(f"[GatewayService] Failed to start gateway service: {e}")
            await self._cleanup()
            raise
    
    async def stop(self) -> None:
        """停止网关服务"""
        if not self._running:
            return
        
        logger.info("[GatewayService] Stopping gateway service...")
        
        self._running = False
        await self._cleanup()
        
        logger.info("[GatewayService] Gateway service stopped")
    
    async def _cleanup(self) -> None:
        """清理资源"""
        # 注意：网关服务不应该断开总线连接，因为总线是由EventBusManager管理的
        # 只清理处理器引用
        self._registered_handlers.clear()
        self._startup_complete = False
        logger.info("[GatewayService] Handlers cleaned up")
    
    async def _register_decorator_handlers(self) -> None:
        """注册装饰器处理器到对应的外部总线"""
        registered_count = 0
        total_topics = set()
        
        for config_key, external_bus in self.external_buses.items():
            # 获取外部总线的类型（从配置中）
            bus_type = self._get_bus_type_for_config(config_key)
            
            # 获取该总线特定的处理器
            bus_handlers = get_external_handlers_for_bus(config_key, bus_type)
            
            self._registered_handlers[config_key] = {}
            
            for topic, handlers in bus_handlers.items():
                if handlers:
                    # 为每个处理器在这个外部总线上注册
                    for handler in handlers:
                        await external_bus.subscribe(topic, handler)
                        registered_count += 1
                    
                    self._registered_handlers[config_key][topic] = handlers
                    total_topics.add(topic)
                    logger.info(f"[GatewayService] Registered {len(handlers)} handlers for topic '{topic}' on bus '{config_key}'")
            
            logger.info(f"[GatewayService] Bus '{config_key}' ({bus_type}) registered {len(bus_handlers)} topics")
        
        logger.info(f"[GatewayService] Total: {registered_count} handlers registered across {len(self.external_buses)} buses")
        logger.info(f"[GatewayService] Supported topics: {sorted(total_topics)}")
        
    def _get_bus_type_for_config(self, config_key: str) -> str:
        """从外部配置中获取总线类型"""
        # 从EventBusManager的外部配置中查找
        from fastapi_app.core.event_bus import event_bus_manager
        if hasattr(event_bus_manager, '_external_configs'):
            for config in event_bus_manager._external_configs:
                if config.config_key == config_key:
                    return config.bus_type
        
        # 如果找不到，从配置键名推断
        if 'rabbitmq' in config_key.lower():
            return 'rabbitmq'
        elif 'kafka' in config_key.lower():
            return 'kafka'  
        elif 'redis' in config_key.lower():
            return 'redis'
        else:
            return 'unknown'
    
    def get_status(self) -> Dict[str, Any]:
        """获取网关状态"""
        external_buses_status = {}
        total_external_topics = []
        
        for config_key, external_bus in self.external_buses.items():
            external_buses_status[config_key] = {
                'connected': external_bus.is_connected if external_bus else False,
                'bus_type': getattr(external_bus, 'bus_type', 'unknown') if external_bus else None,
                'subscribed_topics': external_bus.get_subscribed_topics() if external_bus else []
            }
            if external_bus:
                total_external_topics.extend(external_bus.get_subscribed_topics())
        
        return {
            'running': self._running,
            'startup_complete': self._startup_complete,
            'external_buses_count': len(self.external_buses),
            'external_buses_status': external_buses_status,
            'internal_bus_connected': self.internal_bus.is_connected if self.internal_bus else False,
            'internal_bus_type': getattr(self.internal_bus, 'bus_type', 'unknown') if self.internal_bus else None,
            'total_external_topics': len(set(total_external_topics)),  # 去重计数
            'subscribed_internal_topics': (
                self.internal_bus.get_subscribed_topics() 
                if self.internal_bus else []
            ),
            'handlers_count': sum(
                len(handlers)
                for bus_handlers in self._registered_handlers.values()
                for handlers in bus_handlers.values()
            )
        }
    
    async def health_check(self) -> bool:
        """健康检查"""
        if not self._running or not self._startup_complete:
            return False
        
        try:
            # 检查所有外部总线连接状态
            external_buses_ok = all(
                bus and bus.is_connected 
                for bus in self.external_buses.values()
            )
            
            # 检查内部总线连接状态
            internal_ok = self.internal_bus and self.internal_bus.is_connected
            
            return external_buses_ok and internal_ok
            
        except Exception as e:
            logger.error(f"[GatewayService] Health check failed: {e}")
            return False
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.stop()