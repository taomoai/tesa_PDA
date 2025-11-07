"""
FastAPI事件总线集成

提供事件总线的依赖注入和生命周期管理
"""
from typing import Dict, Any, Optional
from fastapi import Depends
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.bus import AbstractEventBus, create_event_bus, discover_handlers, get_handler_registry
from fastapi_app.services.gateway import GatewayService
from fastapi_app.services.event_bus import EventBusConfigService
from fastapi_app.core.database import get_async_db


class EventBusManager:
    """
    事件总线管理器
    
    负责管理内部事件总线、外部事件总线和网关服务的生命周期
    """
    
    def __init__(self):
        self.internal_bus: Optional[AbstractEventBus] = None
        self.external_buses: Dict[str, AbstractEventBus] = {}
        self.gateway_service: Optional[GatewayService] = None
        self._initialized = False
        self._failed_sources = []
        self._internal_config = None
        self._external_configs = []
        self.is_worker = False
    
    async def initialize(
        self,
        db_session: AsyncSession,
        internal_config_key: Optional[str] = None,
        external_config_keys: Optional[list] = None,
        enable_gateway: bool = False,
        is_worker: bool = False
    ) -> None:
        """
        初始化事件总线系统（支持多个外部数据源按优先级初始化）
        
        Args:
            db_session: 数据库会话
            internal_config_key: 内部总线配置key
            external_config_keys: 外部总线配置key列表，None表示获取所有活动外部配置
            enable_gateway: 是否启用边界网关
        """
        if self._initialized:
            logger.warning("[EventBusManager] Event bus already initialized")
            return
        
        try:
            logger.info(f"[EventBusManager] is_worker={is_worker} Initializing event bus system...")
            self.is_worker = is_worker
            # 创建配置服务
            config_service = EventBusConfigService(db_session)
            
            # 初始化内部总线
            await self._initialize_internal_bus(config_service, internal_config_key)
            
            # 如果启用网关，初始化外部数据源
            if enable_gateway:
                await self._initialize_external_sources(config_service, external_config_keys)
                
                # 创建网关服务
                if self.external_buses:
                    await self._initialize_gateway_service()
            
            self._initialized = True
            logger.info("[EventBusManager] Event bus system initialization completed")
            
        except Exception as e:
            logger.error(f"[EventBusManager] Failed to initialize event bus system: {e}")
            await self.cleanup()
            raise
    
    async def cleanup(self) -> None:
        """清理事件总线资源"""
        logger.info("[EventBusManager] Cleaning up event bus...")
        
        # 停止网关服务
        if self.gateway_service:
            await self.gateway_service.stop()
            self.gateway_service = None
        
        # 断开所有外部事件总线
        for config_key, external_bus in list(self.external_buses.items()):
            try:
                await external_bus.disconnect()
                logger.info(f"[EventBusManager] External event bus disconnected: {config_key}")
            except Exception as e:
                logger.error(f"[EventBusManager] Error disconnecting external bus {config_key}: {e}")
        self.external_buses.clear()
        

        
        # 断开内部事件总线
        if self.internal_bus:
            await self.internal_bus.disconnect()
            self.internal_bus = None
        
        self._failed_sources.clear()
        self._initialized = False
        logger.info("[EventBusManager] Event bus cleanup completed")
    
    def get_gateway_status(self) -> Optional[Dict[str, Any]]:
        """获取网关服务状态"""
        if not self.gateway_service:
            return None
        return self.gateway_service.get_status()
    
    async def gateway_health_check(self) -> bool:
        """网关健康检查"""
        if not self.gateway_service:
            return False
        return await self.gateway_service.health_check()
    
    def get_external_buses_info(self) -> Dict[str, Dict[str, Any]]:
        """获取所有外部总线信息"""
        buses_info = {}
        for config_key, bus in self.external_buses.items():
            config = next((c for c in self._external_configs if c.config_key == config_key), None)
            buses_info[config_key] = {
                'name': config.name if config else config_key,
                'bus_type': config.bus_type if config else 'unknown',
                'priority': config.priority if config else None,
                'connected': bus.is_connected if bus else False,
                'is_critical': config.is_critical_priority() if config else False,
                'is_high_priority': config.is_high_priority() if config else False
            }
        return buses_info
    
    async def _initialize_internal_bus(self, config_service, internal_config_key: Optional[str]):
        """初始化内部总线"""
        internal_config = None
        if internal_config_key:
            internal_config = await config_service.get_config_by_key(internal_config_key)
        else:
            internal_config = await config_service.get_default_config(is_internal=True)
        
        # 保存内部配置
        self._internal_config = internal_config
        
        if not internal_config:
            logger.warning("[EventBusManager] No internal bus config found, using memory adapter")
            internal_bus_config = {'type': 'memory', 'memory': {}}
        else:
            internal_bus_config = internal_config.get_bus_config()
            logger.info(f"[EventBusManager] Using internal bus config: {internal_config.config_key}")

        # 如果是 Worker 模式且使用 RabbitMQ，启用短连接模式
        if self.is_worker and internal_bus_config.get('type') == 'rabbitmq':
            logger.info("[EventBusManager] Worker mode detected, enabling short connections for RabbitMQ")
            if 'rabbitmq' not in internal_bus_config:
                internal_bus_config['rabbitmq'] = {}
            internal_bus_config['rabbitmq']['use_short_connections'] = True

        # 创建内部事件总线
        self.internal_bus = create_event_bus(internal_bus_config)
        await self.internal_bus.connect()
        logger.info("[EventBusManager] Internal event bus connected")
        
        # 自动发现并注册事件处理器
        await self._discover_and_register_handlers()
    
    async def _initialize_external_sources(self, config_service, external_config_keys: Optional[list]):
        """按优先级初始化外部数据源"""
        external_configs = []
        
        if external_config_keys:
            # 使用指定的配置keys
            for key in external_config_keys:
                config = await config_service.get_config_by_key(key)
                if config:
                    external_configs.append(config)
                else:
                    logger.warning(f"[EventBusManager] External config not found: {key}")
        else:
            # 获取所有外部数据源配置，按优先级排序
            external_configs = await config_service.get_external_sources_by_priority()
        
        if not external_configs:
            logger.warning("[EventBusManager] No external bus configs found")
            return
        
        # 保存外部配置
        self._external_configs = external_configs
        
        logger.info(f"[EventBusManager] Found {len(external_configs)} external data sources")
        
        # 按优先级初始化外部数据源
        for config in external_configs:
            try:
                await self._connect_external_source(config)
                logger.info(f"[EventBusManager] Priority {config.priority} source '{config.name}' connected")
                
                # 如果是关键优先级数据源失败，中止后续连接
                if config.is_critical_priority() and config.config_key not in self.external_buses:
                    error_msg = f"Critical source {config.name} failed to connect"
                    logger.error(f"[EventBusManager] {error_msg}")
                    raise RuntimeError(error_msg)
                    
            except Exception as e:
                self._failed_sources.append({
                    'config_key': config.config_key,
                    'name': config.name,
                    'priority': config.priority,
                    'error': str(e)
                })
                
                if config.is_critical_priority():
                    logger.error(f"[EventBusManager] Critical source {config.name} failed: {e}")
                    raise  # 关键数据源失败时抛出异常
                elif config.is_high_priority():
                    logger.error(f"[EventBusManager] Important source {config.name} failed: {e}")
                    # 重要数据源失败，记录但继续
                else:
                    logger.warning(f"[EventBusManager] Optional source {config.name} failed: {e}")
                    # 普通数据源失败，仅记录警告
        
        # 报告初始化结果
        success_count = len(self.external_buses)
        total_count = len(external_configs)
        logger.info(f"[EventBusManager] External sources initialized: {success_count}/{total_count} successful")
        
        if self._failed_sources:
            logger.warning(f"[EventBusManager] Failed sources: {[s['config_key'] for s in self._failed_sources]}")
    
    async def _connect_external_source(self, config):
        """连接单个外部数据源"""
        try:
            # 获取配置并合并优先级设置
            bus_config = config.get_bus_config()
            priority_config = config.merge_priority_config()
            
            # 将优先级配置合并到总线配置中
            bus_config.update(priority_config)
            
            logger.debug(f"[EventBusManager] Connecting {config.config_key} with config: {bus_config}")
            
            # 创建并连接外部总线
            external_bus = create_event_bus(bus_config)
            await external_bus.connect()
            
            self.external_buses[config.config_key] = external_bus
            logger.info(f"[EventBusManager] External bus connected: {config.config_key}")
            
        except Exception as e:
            logger.error(f"[EventBusManager] Failed to connect external source {config.config_key}: {e}")
            raise
    
    async def _initialize_gateway_service(self):
        """初始化网关服务"""
        if not self.external_buses:
            logger.warning("[EventBusManager] No external buses available for gateway")
            return
        
        try:
            # 确保内部总线存在
            if not self.internal_bus:
                raise ValueError("Internal bus is not initialized")
            
            logger.info(f"[EventBusManager] Creating gateway service with {len(self.external_buses)} external buses")
            
            self.gateway_service = GatewayService(
                external_buses=self.external_buses,
                internal_bus=self.internal_bus
            )
            await self.gateway_service.start()
            logger.info("[EventBusManager] Gateway service started")
            
        except Exception as e:
            logger.error(f"[EventBusManager] Failed to initialize gateway service: {e}")
            raise
    
    async def _discover_and_register_handlers(self) -> None:
        """自动发现并注册事件处理器"""
        if not self.internal_bus:
            return
        
        # 扫描服务模块查找事件处理器
        packages_to_scan = [
            'fastapi_app.services.gateway.internal_event_handlers',
            # 'fastapi_app.modules.common_service',  # 添加通用服务模块
        ]
        if self.is_worker == False:
            packages_to_scan.append('fastapi_app.modules.monitor_service.monitor.event_handler')
            packages_to_scan.append('fastapi_app.modules.monitor_service.alarm.event_handler')
            packages_to_scan.append('fastapi_app.modules.notification_service.event_handler')  # 添加通知服务
            packages_to_scan.append('fastapi_app.modules.common_service.database_operation_log')  # 添加事件处理模块
        
        total_discovered = 0
        for package in packages_to_scan:
            try:
                count = discover_handlers(package)
                total_discovered += count
            except Exception as e:
                logger.warning(f"[EventBusManager] Failed to discover handlers in {package}: {e}")
        
        # 注册发现的处理器
        registry = get_handler_registry()
        for topic, handlers in registry.items():
            for handler in handlers:
                await self.internal_bus.subscribe(topic, handler)
        
        logger.info(f"[EventBusManager] Registered {total_discovered} event handlers from {len(registry)} topics")
    
    def get_internal_bus(self) -> Optional[AbstractEventBus]:
        """获取内部事件总线"""
        return self.internal_bus
    
    def get_external_bus(self, config_key: Optional[str] = None) -> Optional[AbstractEventBus]:
        """获取外部事件总线"""
        if config_key:
            return self.external_buses.get(config_key)
        # 如果没有指定config_key，返回第一个可用的外部总线
        if self.external_buses:
            return next(iter(self.external_buses.values()))
        return None
    
    def get_all_external_buses(self) -> Dict[str, AbstractEventBus]:
        """获取所有外部事件总线"""
        return self.external_buses.copy()
    
    def get_gateway_service(self) -> Optional[GatewayService]:
        """获取网关服务"""
        return self.gateway_service
    
    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._initialized
    
    def get_status(self) -> Dict[str, Any]:
        """获取事件总线状态"""
        external_buses_status = {}
        for config_key, bus in self.external_buses.items():
            external_buses_status[config_key] = {
                'connected': bus.is_connected if hasattr(bus, 'is_connected') else True,
                'type': bus.config.get('type') if hasattr(bus, 'config') else 'unknown'
            }
        
        return {
            'initialized': self._initialized,
            'internal_bus_connected': (
                self.internal_bus.is_connected if self.internal_bus and hasattr(self.internal_bus, 'is_connected') else bool(self.internal_bus)
            ),
            'external_buses_count': len(self.external_buses),
            'external_buses_status': external_buses_status,
            'gateway_enabled': self.gateway_service is not None,
            'gateway_status': (
                self.gateway_service.get_status() if self.gateway_service and hasattr(self.gateway_service, 'get_status') else 'active' if self.gateway_service else None
            ),
            'failed_sources': self._failed_sources
        }


# 全局事件总线管理器实例
event_bus_manager = EventBusManager()


def get_event_bus_manager() -> EventBusManager:
    """获取事件总线管理器（用于依赖注入）"""
    return event_bus_manager


def get_internal_event_bus() -> AbstractEventBus:
    """获取内部事件总线（用于依赖注入）"""
    bus = event_bus_manager.get_internal_bus()
    if not bus:
        raise RuntimeError("Internal event bus not initialized")
    return bus


def get_external_event_bus() -> AbstractEventBus:
    """获取外部事件总线（用于依赖注入）"""
    bus = event_bus_manager.get_external_bus()
    if not bus:
        raise RuntimeError("External event bus not initialized")
    return bus


# 依赖注入函数
EventBusManagerDep = Depends(get_event_bus_manager)
InternalEventBusDep = Depends(get_internal_event_bus)
ExternalEventBusDep = Depends(get_external_event_bus)