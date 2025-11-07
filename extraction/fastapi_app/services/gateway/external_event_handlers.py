"""
网关事件处理器 - 使用装饰器方式注册

重构后的处理器，使用@event_handler装饰器进行自动注册
"""
from typing import List, Optional
from loguru import logger
import time
import asyncio

from fastapi_app.bus import Event, external_event_handler
from fastapi_app.bus.topics import Topics

# 全局变量：记录上次发送事件的时间戳
_last_monitor_event_time = 0
# 发送间隔：5秒
MONITOR_EVENT_INTERVAL = 5
# 异步锁：保护时间戳的并发访问
_monitor_event_lock = asyncio.Lock()

async def _handle_transformation_error(original_event: Event, error: Exception) -> None:
    """
    处理转换错误
    
    Args:
        original_event: 原始外部事件
        error: 转换错误
    """
    
    # 创建错误事件
    error_event = Event(
        topic="system.gateway.transformation_error.v1",
        payload={
            'original_event_id': original_event.event_id,
            'original_topic': original_event.topic,
            'error_message': str(error),
            'error_type': error.__class__.__name__,
            'original_payload': original_event.payload
        },
        correlation_id=original_event.correlation_id,
        source='gateway'
    )
    
    try:
        # 发布错误事件到内部总线，用于监控和告警
        from fastapi_app.core.event_bus import get_internal_event_bus
        await get_internal_event_bus().publish(error_event)
        logger.info(f"[GatewayEventHandlers] Published transformation error event: {error_event.event_id}")
    except Exception as publish_error:
        logger.error(f"[GatewayEventHandlers] Failed to publish error event: {publish_error}")


# =============== 外部事件处理器 ===============
@external_event_handler(Topics.EXTERNAL_CUSTOMER_NEW, bus_config_key="rabbitmq_coating_data")
async def handle_coating_data_new(event: Event) -> None:
    """处理来自涂料数据源的新数据事件"""
    logger.info(f"[GatewayEventHandlers] Received coating data event: {event.event_id}")
    
    try:
        # 从event中获取涂料数据
        coating_data = event.payload
        
        # 打印涂料数据详情
        logger.info("=" * 80)
        logger.info("[涂料数据源] QMS传感器数据接收:")
        logger.info(f"  事件ID: {event.event_id}")
        logger.info(f"  事件主题: {event.topic}")
        logger.info(f"  数据源: {event.source}")
        logger.info(f"  事件时间戳: {event.timestamp}")
        logger.info(f"  关联ID: {event.correlation_id}")
        logger.info(f"  原始数据: {coating_data}")
        
        if isinstance(coating_data, dict):
            logger.info(f"  数据时间戳: {coating_data.get('timestamp', '未知')}")
        else:
            logger.warning(f"  ⚠️  数据格式异常: {type(coating_data)}")
            logger.info(f"  原始数据: {coating_data}")
        
        logger.info("=" * 80)
        
        # ETL和数据存储
        from ...services.coating import CoatingDataService

        # 读取数据类型（Total / PLC / Coating Thickness Gauge）
        data_type = None
        if isinstance(coating_data, dict):
            data_type = coating_data.get('data_type')

        # 解析 value 为 {key: value}
        external_map = {}
        if isinstance(coating_data, dict):
            external_map = CoatingDataService.parse_value_kv_list(coating_data.get('value'))

        # 准备保存结果变量
        saved_running = None
        saved_databox = None

        # 统一时间戳
        ts = coating_data.get('timestamp') if isinstance(coating_data, dict) else None

        logger.info(f"[GatewayEventHandlers] Data type: {data_type}, timestamp: {ts}")
        if data_type == 'total':
            # Total：value 内包含完整键，需拆分并分别入库（同一 timestamp）
            running_piece = CoatingDataService._map_external_to_running_fields(external_map)
            databox_piece = CoatingDataService._map_external_to_databox_fields(external_map)

            running_piece['timestamp'] = ts
            databox_piece['timestamp'] = ts

            saved_running = await CoatingDataService.save_running_params(running_piece)
            saved_databox = await CoatingDataService.save_databox_and_process(databox_piece)

            # 若任一为空，做一次“克隆补全”，确保双表都新增
            if saved_running is None:
                saved_running = await CoatingDataService.clone_latest_running_with_timestamp(ts)
            if saved_databox is None:
                saved_databox = await CoatingDataService.clone_latest_databox_with_timestamp(ts)

        elif data_type == 'PLC':
            # PLC：工艺/运行参数为主，字段不完整，用最近完整记录补全
            saved_running = await CoatingDataService.save_running_with_merge(ts, external_map)
            # 同步另一张表，使用最新记录+该时间戳克隆
            saved_databox = await CoatingDataService.clone_latest_databox_with_timestamp(ts)

        elif data_type == 'coating thickness gauge':
            # Coating Thickness Gauge：测厚仪/Databox，为主，字段不完整，用最近完整记录补全
            saved_databox = await CoatingDataService.save_databox_with_merge(ts, external_map)
            # 同步另一张表
            saved_running = await CoatingDataService.clone_latest_running_with_timestamp(ts)
        else:
            logger.error(f"[GatewayEventHandlers] Failed to save coating data to database")


        if data_type == 'coating thickness gauge':
            # 使用异步锁保护时间戳检查和更新的临界区
            async with _monitor_event_lock:
                # 检查是否超过5秒间隔才发送事件
                current_time = time.time()
                global _last_monitor_event_time

                if current_time - _last_monitor_event_time >= MONITOR_EVENT_INTERVAL:
                    # 更新上次发送时间
                    _last_monitor_event_time = current_time

                    # 发送内部事件给监控系统
                    monitor_event = Event(
                        topic=Topics.INTERNAL_MONITOR_DATA,
                        source="coating_data_source",
                        event_id=event.event_id,
                        timestamp=event.timestamp,
                        correlation_id=event.correlation_id,
                        metadata=event.metadata,
                        payload={
                            'running_params': saved_running.to_dict() if saved_running else None,
                            'databox_and_process': saved_databox.to_dict() if saved_databox else None,
                        }
                    )
                    from fastapi_app.core.event_bus import get_internal_event_bus
                    await get_internal_event_bus().publish(monitor_event)
                    logger.info(f"[GatewayEventHandlers] Sent monitor event (5s interval)")
                else:
                    # 5秒内不发送事件，只记录日志
                    logger.debug(f"[GatewayEventHandlers] Skipped monitor event (within 5s interval)")
        logger.info(f"[GatewayEventHandlers] Successfully processed coating data: {event.event_id}")
        
    except Exception as e:
        logger.error(f"[GatewayEventHandlers] Error handling coating data: {e}")
        logger.error(f"[GatewayEventHandlers] Event payload: {event.payload}")
        await _handle_transformation_error(event, e)