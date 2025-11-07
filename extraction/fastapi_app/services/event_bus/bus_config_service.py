"""
事件总线配置服务

提供事件总线配置的CRUD操作和业务逻辑
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from sqlalchemy.orm import selectinload
from loguru import logger
import asyncio
from functools import lru_cache
import time

from fastapi_app.core.database import readonly, transaction
from fastapi_app.models.event_bus import EventBusConfig, EventBusType, EventBusStatus, EventBusPriority
from fastapi_app.schemas.event_bus import (
    EventBusConfigCreate,
    EventBusConfigUpdate,
    EventBusConfigTemplate
)


class EventBusConfigService:
    """事件总线配置服务"""

    # 类级别的缓存，用于存储配置数据
    _config_cache: Dict[str, tuple[EventBusConfig, float]] = {}
    _cache_ttl = 300  # 缓存5分钟

    def __init__(self, db_session: AsyncSession):
        self.db = db_session

    @classmethod
    def _is_cache_valid(cls, timestamp: float) -> bool:
        """检查缓存是否有效"""
        return time.time() - timestamp < cls._cache_ttl

    @classmethod
    def _get_from_cache(cls, key: str) -> Optional[EventBusConfig]:
        """从缓存获取配置"""
        if key in cls._config_cache:
            config, timestamp = cls._config_cache[key]
            if cls._is_cache_valid(timestamp):
                return config
            else:
                # 缓存过期，删除
                del cls._config_cache[key]
        return None

    @classmethod
    def _set_cache(cls, key: str, config: EventBusConfig) -> None:
        """设置缓存"""
        cls._config_cache[key] = (config, time.time())

    @classmethod
    def clear_cache(cls) -> None:
        """清空缓存"""
        cls._config_cache.clear()
    
    @transaction()
    async def create_config(self, config_data: EventBusConfigCreate) -> EventBusConfig:
        """
        创建事件总线配置
        
        Args:
            config_data: 配置数据
            
        Returns:
            EventBusConfig: 创建的配置对象
        """
        # 检查配置key是否已存在
        existing = await self.get_config_by_key(config_data.config_key)
        if existing:
            raise ValueError(f"配置key '{config_data.config_key}' 已存在")
        
        # 如果设置为默认配置，先将其他同类型的默认配置取消
        if config_data.is_default:
            await self._clear_default_config(config_data.bus_type, config_data.is_internal)
        
        # 创建配置对象
        config = EventBusConfig(
            config_key=config_data.config_key,
            name=config_data.name,
            description=config_data.description,
            bus_type=config_data.bus_type.value if hasattr(config_data.bus_type, 'value') else config_data.bus_type,
            status='inactive',  # 新建配置默认为未激活
            is_default=config_data.is_default,
            is_internal=config_data.is_internal,
            connection_config=config_data.connection_config,
            extra_config=config_data.extra_config or {},
            created_by=config_data.created_by
        )
        
        self.db.add(config)
        await self.db.commit()
        await self.db.refresh(config)

        # 清空缓存，因为配置已更改
        self.clear_cache()

        logger.info(f"Created event bus config: {config.config_key}")
        return config
    
    @readonly()
    async def get_config_by_id(self, config_id: int) -> Optional[EventBusConfig]:
        """根据ID获取配置"""
        result = await self.db.execute(
            select(EventBusConfig).where(EventBusConfig.id == config_id)
        )
        return result.scalar_one_or_none()
    
    async def get_config_by_key(self, config_key: str) -> Optional[EventBusConfig]:
        """根据配置key获取配置（带缓存）"""
        # 先检查缓存
        cached_config = self._get_from_cache(config_key)
        if cached_config is not None:
            logger.debug(f"[EventBusConfigService] Cache hit for config_key: {config_key}")
            return cached_config

        # 缓存未命中，从数据库查询
        logger.debug(f"[EventBusConfigService] Cache miss for config_key: {config_key}, querying database")

        # 使用独立的数据库会话进行查询，避免持有长期连接
        from fastapi_app.core.database import get_async_db_context
        async with get_async_db_context() as session:
            result = await session.execute(
                select(EventBusConfig).where(EventBusConfig.config_key == config_key)
            )
            config = result.scalar_one_or_none()

            # 如果找到配置，加入缓存
            if config is not None:
                self._set_cache(config_key, config)

            return config
    
    async def get_default_config(
        self,
        bus_type: Optional[EventBusType] = None,
        is_internal: bool = True
    ) -> Optional[EventBusConfig]:
        """
        获取默认配置

        Args:
            bus_type: 总线类型，如果不指定则获取任意类型的默认配置
            is_internal: 是否为内部总线

        Returns:
            EventBusConfig: 默认配置对象
        """
        conditions = [
            EventBusConfig.is_default == True,
            EventBusConfig.is_internal == is_internal,
            EventBusConfig.status == 'active'
        ]

        if bus_type:
            conditions.append(EventBusConfig.bus_type == bus_type.value)

        # 使用独立的数据库会话进行查询
        from fastapi_app.core.database import get_async_db_context
        async with get_async_db_context() as session:
            result = await session.execute(
                select(EventBusConfig).where(and_(*conditions))
            )
            return result.scalar_one_or_none()
    
    @readonly()
    async def get_active_configs(
        self,
        is_internal: Optional[bool] = None
    ) -> List[EventBusConfig]:
        """
        获取所有活跃的配置

        Args:
            is_internal: 是否为内部总线，None表示获取所有

        Returns:
            List[EventBusConfig]: 活跃配置列表
        """
        conditions = [EventBusConfig.status == 'active']

        if is_internal is not None:
            conditions.append(EventBusConfig.is_internal == is_internal)

        result = await self.db.execute(
            select(EventBusConfig)
            .where(and_(*conditions))
            .order_by(EventBusConfig.is_default.desc(), EventBusConfig.created_at)
        )
        return result.scalars().all()
    
    @readonly()
    async def list_configs(
        self,
        page: int = 1,
        page_size: int = 10,
        bus_type: Optional[EventBusType] = None,
        status: Optional[EventBusStatus] = None,
        is_internal: Optional[bool] = None
    ) -> tuple[List[EventBusConfig], int]:
        """
        分页获取配置列表

        Returns:
            tuple: (配置列表, 总数)
        """
        conditions = []

        if bus_type:
            conditions.append(EventBusConfig.bus_type == bus_type.value)
        if status:
            conditions.append(EventBusConfig.status == status.value)
        if is_internal is not None:
            conditions.append(EventBusConfig.is_internal == is_internal)

        # 构建查询
        query = select(EventBusConfig)
        if conditions:
            query = query.where(and_(*conditions))

        # 获取总数
        count_query = select(func.count()).select_from(EventBusConfig)
        if conditions:
            count_query = count_query.where(and_(*conditions))

        total_result = await self.db.execute(count_query)
        total = total_result.scalar()

        # 获取分页数据
        query = query.order_by(
            EventBusConfig.is_default.desc(),
            EventBusConfig.created_at.desc()
        ).offset((page - 1) * page_size).limit(page_size)

        result = await self.db.execute(query)
        configs = result.scalars().all()

        return configs, total
    
    @transaction()
    async def update_config(
        self,
        config_id: int,
        update_data: EventBusConfigUpdate
    ) -> Optional[EventBusConfig]:
        """更新配置"""
        config = await self.get_config_by_id(config_id)
        if not config:
            return None
        
        # 如果要设置为默认配置，先清除其他默认配置
        if update_data.is_default is True and not config.is_default:
            await self._clear_default_config(config.bus_type, config.is_internal)
        
        # 更新字段
        update_fields = update_data.model_dump(exclude_unset=True)
        for field, value in update_fields.items():
            if field != 'updated_by':
                setattr(config, field, value)
        
        if update_data.updated_by:
            config.updated_by = update_data.updated_by
        
        await self.db.commit()
        await self.db.refresh(config)

        # 清空缓存，因为配置已更改
        self.clear_cache()

        logger.info(f"Updated event bus config: {config.config_key}")
        return config
    
    @transaction()
    async def update_status(
        self,
        config_id: int,
        status: str,
        updated_by: Optional[str] = None
    ) -> Optional[EventBusConfig]:
        """更新配置状态"""
        config = await self.get_config_by_id(config_id)
        if not config:
            return None
        
        config.status = status
        if updated_by:
            config.updated_by = updated_by
        
        await self.db.commit()
        await self.db.refresh(config)

        # 清空缓存，因为配置已更改
        self.clear_cache()

        logger.info(f"Updated event bus config status: {config.config_key} -> {status}")
        return config
    
    @transaction()
    async def delete_config(self, config_id: int) -> bool:
        """删除配置"""
        config = await self.get_config_by_id(config_id)
        if not config:
            return False
        
        # 不允许删除活跃状态的配置
        if config.status == 'active':
            raise ValueError("不能删除活跃状态的配置，请先停用")
        
        await self.db.delete(config)
        await self.db.commit()
        
        logger.info(f"Deleted event bus config: {config.config_key}")
        return True
    
    async def _clear_default_config(
        self,
        bus_type: EventBusType,
        is_internal: bool
    ) -> None:
        """清除同类型的默认配置"""
        result = await self.db.execute(
            select(EventBusConfig).where(
                and_(
                    EventBusConfig.bus_type == bus_type.value,
                    EventBusConfig.is_internal == is_internal,
                    EventBusConfig.is_default == True
                )
            )
        )

        existing_defaults = result.scalars().all()
        for config in existing_defaults:
            config.is_default = False

        if existing_defaults:
            logger.info(f"Cleared {len(existing_defaults)} default configs for {bus_type.value}")
    
    @staticmethod
    def get_config_templates() -> List[EventBusConfigTemplate]:
        """获取所有配置模板"""
        templates = []
        
        for bus_type in EventBusType:
            template_configs = EventBusConfig.get_default_config_templates()
            template_config = template_configs.get(bus_type, {})
            
            # 定义每种类型的必需和可选字段
            field_definitions = {
                EventBusType.MEMORY: {
                    'required': [],
                    'optional': ['max_queue_size', 'enable_persistence'],
                    'description': '内存总线，适用于单进程应用和测试环境'
                },
                EventBusType.REDIS: {
                    'required': ['host', 'port'],
                    'optional': ['password', 'db', 'decode_responses', 'socket_timeout'],
                    'description': 'Redis发布订阅模式，支持分布式部署'
                },
                EventBusType.RABBITMQ: {
                    'required': ['host', 'port', 'username', 'password'],
                    'optional': ['virtual_host', 'exchange_name', 'exchange_type', 'durable'],
                    'description': 'RabbitMQ消息队列，支持持久化和可靠消息传递'
                },
                EventBusType.KAFKA: {
                    'required': ['bootstrap_servers'],
                    'optional': ['group_id', 'auto_offset_reset', 'enable_auto_commit'],
                    'description': 'Apache Kafka，支持高吞吐量和水平扩展'
                }
            }
            
            field_info = field_definitions.get(bus_type, {})
            
            template = EventBusConfigTemplate(
                bus_type=bus_type,
                bus_type_display=bus_type.get_display_name(),
                template_config=template_config,
                required_fields=field_info.get('required', []),
                optional_fields=field_info.get('optional', []),
                description=field_info.get('description', '')
            )
            templates.append(template)
        
        return templates
    
    async def test_connection(self, config: EventBusConfig) -> Dict[str, Any]:
        """
        测试配置的连接
        
        Args:
            config: 配置对象
            
        Returns:
            Dict: 测试结果
        """
        try:
            from fastapi_app.bus import create_event_bus
            
            # 创建事件总线实例
            bus_config = config.get_bus_config()
            bus = create_event_bus(bus_config)
            
            # 尝试连接
            await bus.connect()
            
            # 测试连接状态
            is_connected = bus.is_connected
            
            # 断开连接
            await bus.disconnect()
            
            return {
                'success': is_connected,
                'message': '连接测试成功' if is_connected else '连接失败',
                'config_key': config.config_key,
                'bus_type': config.bus_type.value
            }
            
        except Exception as e:
            logger.error(f"Connection test failed for {config.config_key}: {e}")
            return {
                'success': False,
                'message': f'连接测试失败: {str(e)}',
                'config_key': config.config_key,
                'bus_type': config.bus_type.value
            }
    
    async def get_configs_by_priority(
        self,
        priority: Optional[int] = None,
        is_internal: Optional[bool] = None,
        status: str = 'active',
        order_by_priority: bool = True
    ) -> List[EventBusConfig]:
        """
        按优先级获取配置列表
        
        Args:
            priority: 指定优先级，None表示获取所有
            is_internal: 是否内部总线
            status: 状态过滤
            order_by_priority: 是否按优先级排序
            
        Returns:
            List[EventBusConfig]: 配置列表
        """
        conditions = [EventBusConfig.status == status]
        
        if priority is not None:
            conditions.append(EventBusConfig.priority == priority)
        
        if is_internal is not None:
            conditions.append(EventBusConfig.is_internal == is_internal)
        
        query = select(EventBusConfig).where(and_(*conditions))
        
        if order_by_priority:
            query = query.order_by(EventBusConfig.priority.asc(), EventBusConfig.id.asc())
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_external_sources_by_priority(self) -> List[EventBusConfig]:
        """
        获取外部数据源配置，按优先级排序
        
        Returns:
            List[EventBusConfig]: 外部数据源配置列表
        """
        return await self.get_configs_by_priority(
            is_internal=False,
            status='active',
            order_by_priority=True
        )
    
    async def get_critical_configs(self, is_internal: Optional[bool] = None) -> List[EventBusConfig]:
        """
        获取关键优先级的配置
        
        Args:
            is_internal: 是否内部总线
            
        Returns:
            List[EventBusConfig]: 关键优先级的配置列表
        """
        return await self.get_configs_by_priority(
            priority=EventBusPriority.CRITICAL.value,
            is_internal=is_internal,
            status='active'
        )
    
    async def get_high_priority_configs(self, is_internal: Optional[bool] = None) -> List[EventBusConfig]:
        """
        获取高优先级（关键+重要）的配置
        
        Args:
            is_internal: 是否内部总线
            
        Returns:
            List[EventBusConfig]: 高优先级的配置列表
        """
        conditions = [
            EventBusConfig.status == 'active',
            EventBusConfig.priority <= EventBusPriority.IMPORTANT.value
        ]
        
        if is_internal is not None:
            conditions.append(EventBusConfig.is_internal == is_internal)
        
        query = select(EventBusConfig).where(and_(*conditions)).order_by(
            EventBusConfig.priority.asc(), EventBusConfig.id.asc()
        )
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_priority_statistics(self) -> Dict[str, Any]:
        """
        获取优先级统计信息
        
        Returns:
            Dict[str, Any]: 优先级统计数据
        """
        # 按优先级统计
        priority_query = select(
            EventBusConfig.priority,
            func.count(EventBusConfig.id).label('count')
        ).where(
            EventBusConfig.status == 'active'
        ).group_by(EventBusConfig.priority)
        
        priority_result = await self.db.execute(priority_query)
        priority_stats = {row.priority: row.count for row in priority_result.fetchall()}
        
        # 按内外部统计
        internal_query = select(
            EventBusConfig.is_internal,
            EventBusConfig.priority,
            func.count(EventBusConfig.id).label('count')
        ).where(
            EventBusConfig.status == 'active'
        ).group_by(EventBusConfig.is_internal, EventBusConfig.priority)
        
        internal_result = await self.db.execute(internal_query)
        internal_stats = {}
        for row in internal_result.fetchall():
            key = 'internal' if row.is_internal else 'external'
            if key not in internal_stats:
                internal_stats[key] = {}
            internal_stats[key][row.priority] = row.count
        
        return {
            'priority_distribution': priority_stats,
            'internal_external_distribution': internal_stats,
            'priority_names': {
                priority.value: priority.get_display_name() 
                for priority in EventBusPriority
            }
        }