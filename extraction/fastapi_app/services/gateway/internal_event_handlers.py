from loguru import logger
import asyncio

from fastapi_app.bus import internal_event_handler
from fastapi_app.bus.event import Event
from fastapi_app.bus.topics import Topics
from fastapi_app.modules.monitor_service.bak.monitor.utils import process_new, process
from fastapi_app.modules.monitor_service.monitor.model import Monitor
from fastapi_app.modules.monitor_service.monitor.service import MonitorAlgorithmService
from flask_app.common.init_db import db
from flask_app.modules.datafabric_service.resources.service import ResourceService


# Flask 应用上下文管理器
class FlaskContextManager:
    """Flask 应用上下文管理器，用于在 FastAPI 中调用 Flask 服务"""

    def __init__(self):
        self.flask_app = None
        self._load_flask_app()

    def _load_flask_app(self):
        """加载 Flask 应用"""
        try:
            from main_hybrid import get_flask_app as get_hybrid_flask_app
            self.flask_app = get_hybrid_flask_app()
        except ImportError:
            try:
                from flask_app.app import create_flask_app
                self.flask_app = create_flask_app()
            except Exception as e:
                logger.warning(f"[FlaskContextManager] Failed to load Flask app: {str(e)}")
                self.flask_app = None

    async def execute_with_flask_context(self, func, *args, **kwargs):
        """在 Flask 应用上下文中执行函数"""
        def _execute():
            with self.flask_app.app_context():
                return func(*args, **kwargs)

        return await asyncio.to_thread(_execute)

# 创建全局实例
flask_context_manager = FlaskContextManager()

@internal_event_handler(Topics.INTERNAL_MONITOR_DATA)
async def handle_monitor_data(event: Event) -> None:
    """处理来自监控系统的事件"""
    logger.info(f"[GatewayEventHandlers] Received monitor data event: {event.event_id}")

    # 通知 Monitor 有数据进入
    logger.info("=" * 80)
    logger.info(f"  事件ID: {event.event_id}")
    logger.info(f"  事件主题: {event.topic}")
    logger.info(f"  数据源: {event.source}")
    logger.info(f"  事件时间戳: {event.timestamp}")
    logger.info(f"  关联ID: {event.correlation_id}")
    logger.info(f"  事件数据: {event.payload}")

    # TODO 调用Datafabric
    # TODO 根据event source调用不同类型monitor， monitor里面会有配置的resource_id以及resources参数配置

    monitors = await Monitor.select_monitor_by_type(event.source)  # 原方法会做全局的组织ID的筛选，使用Model上的方法不做组织ID筛选
    if not monitors:
        logger.error(f"[GatewayEventHandlers] Monitor not found: {event.source}")
        return

    logger.info(f"[GatewayEventHandlers] Monitors: {monitors}")

    for monitor in monitors:
        try:
            data_source_config = monitor.data_source_config
            resource_id = data_source_config.get("resource_id")
            params = data_source_config.get("params")
            if not resource_id:
                logger.error(f"[GatewayEventHandlers] Resource ID or params not found: {event.source}")
                continue

            logger.info(f"[GatewayEventHandlers] Resource ID: {resource_id}")
            logger.info(f"[GatewayEventHandlers] Params: {params}")

            # 调用 resource 接口拿到数据 - 使用 Flask 上下文管理器
            def execute_resource_call():
                """执行资源调用的函数"""
                resource_service = ResourceService()
                return resource_service.execute_resource(resource_id=resource_id, params=params)

            try:
                resource = await flask_context_manager.execute_with_flask_context(
                    execute_resource_call
                )
            except Exception as e:
                logger.error(f"[GatewayEventHandlers] Failed to execute resource: {str(e)}")
                continue
            if not resource:
                logger.error(f"[GatewayEventHandlers] Data not found: {event.source}")
                continue

            resource_data = resource.get("data")
            if not resource_data:
                logger.error(f"[GatewayEventHandlers] Data not found: {event.source}")
                continue

            logger.info(f"[GatewayEventHandlers] Data: {resource_data}")

            # 查询 monitor 对应的算法
            monitor_algorithm_service = MonitorAlgorithmService()
            algorithms = await monitor_algorithm_service.select_monitor_algorithm(monitor_id=monitor.id)
            if not algorithms:
                logger.error(f"[GatewayEventHandlers] Algorithms not found: {monitor.id}")
                continue
            
            data = resource_data.get("data")
            
            logger.info(f"[GatewayEventHandlers] Data: {data}")
            
            # pump 三个里面只会有一个
            pump = 0
            cfg = resource_data.get("cfg")
            if cfg.get("buffer_pump_speed"):
                pump = cfg.get("buffer_pump_speed")
            elif cfg.get("degassing1_pump_speed"):
                pump = cfg.get("degassing1_pump_speed")
            elif cfg.get("degassing2_pump_speed"):
                pump = cfg.get("degassing2_pump_speed")

            def process_wrapper(config, batch, index, post_func):
                process(
                    config=config, batch=batch, index=index, post_func=post_func)

                db.session.commit()

            try: 
                data = await flask_context_manager.execute_with_flask_context(
                    process_wrapper,
                    config={
                        "event_id": event.event_id,
                        "monitor_id": "178459787531522048",
                        "task_id": "coating",
                        "alg_config": {},
                        "tenant_id": monitor.tenant_id,
                    }, batch={
                        "data": data,
                        "time": cfg.get("timestamp"),
                        "os": cfg.get("slot_die_os_gap"),
                        "mid": cfg.get("slot_die_mid_gap"),
                        "ds": cfg.get("slot_die_ds_gap"),
                        "pump": pump,
                    }, index=None, post_func=None)

                logger.info(f"[GatewayEventHandlers] Processed data result: {data}")
            except Exception as e:
                logger.error(f"[GatewayEventHandlers] Error: {str(e)}")
                continue

            logger.info(f"[GatewayEventHandlers] Processed data: {data}")
        except Exception as e:
            logger.error(f"[GatewayEventHandlers] Error: {str(e)}")
            continue
    
