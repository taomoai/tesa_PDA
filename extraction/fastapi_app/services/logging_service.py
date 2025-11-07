"""
日志服务 - 负责将日志写入ES
"""
import asyncio
import json
from datetime import datetime
from typing import Dict, Any, Optional, List
from loguru import logger

from fastapi_app.core.elasticsearch import (
    get_async_es_client, 
    ESIndexManager, 
    get_daily_index_name,
    SYSTEM_LOG_MAPPING,
    OPERATION_LOG_MAPPING,
    is_es_available
)


class LoggingService:
    """日志服务"""

    def __init__(self):
        self.es_client = get_async_es_client()
        self.index_manager = ESIndexManager()
        self._write_queue = asyncio.Queue(maxsize=1000)
        self._worker_task: Optional[asyncio.Task] = None
        self._running = False
        self._es_available = is_es_available()

    async def start(self):
        """启动日志服务"""
        if self._running:
            return

        # 检查ES是否可用
        self._es_available = is_es_available()
        if not self._es_available:
            logger.info("[LoggingService] ES not available, logging service will not start")
            return

        self._running = True
        self._worker_task = asyncio.create_task(self._log_writer_worker())
        logger.info("[LoggingService] Started")
    
    async def stop(self):
        """停止日志服务"""
        if not self._running:
            return
        
        self._running = False

        # 等待队列清空（添加超时，最多等待 1 秒）
        try:
            start_time = asyncio.get_event_loop().time()
            while not self._write_queue.empty():
                if asyncio.get_event_loop().time() - start_time > 1.0:
                    logger.warning(f"[LoggingService] Queue not empty after 1s, dropping {self._write_queue.qsize()} logs")
                    break
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"[LoggingService] Error waiting for queue: {e}")

        # 等待工作线程结束（添加超时）
        if self._worker_task:
            self._worker_task.cancel()
            try:
                # 最多等待 1 秒
                await asyncio.wait_for(self._worker_task, timeout=1.0)
            except asyncio.TimeoutError:
                logger.warning("[LoggingService] Worker task timeout (1s), forcing stop")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"[LoggingService] Error stopping worker: {e}")

        logger.info("[LoggingService] Stopped")
    
    async def _log_writer_worker(self):
        """日志写入工作线程"""
        batch_size = 50
        batch_timeout = 5.0  # 5秒超时
        batch = []
        last_flush = datetime.now()
        
        while self._running:
            try:
                # 尝试获取日志条目
                try:
                    log_entry = await asyncio.wait_for(
                        self._write_queue.get(), 
                        timeout=1.0
                    )
                    batch.append(log_entry)
                except asyncio.TimeoutError:
                    # 超时，检查是否需要刷新批次
                    pass
                
                # 检查是否需要刷新批次
                now = datetime.now()
                should_flush = (
                    len(batch) >= batch_size or 
                    (batch and (now - last_flush).total_seconds() >= batch_timeout)
                )
                
                if should_flush and batch:
                    await self._flush_batch(batch)
                    batch.clear()
                    last_flush = now
                    
            except Exception as e:
                logger.error(f"[LoggingService] Worker error: {str(e)}")
                await asyncio.sleep(1)
        
        # 处理剩余的批次
        if batch:
            await self._flush_batch(batch)
    
    async def _flush_batch(self, batch: List[Dict[str, Any]]):
        """刷新批次到ES"""
        if not self.es_client or not is_es_available():
            logger.debug(f"[LoggingService] ES not available, dropping {len(batch)} logs")
            return

        try:
            logger.debug(f"[LoggingService] Starting to flush batch of {len(batch)} entries")

            # 按索引分组
            index_groups = {}
            for entry in batch:
                index_name = entry['_index']
                if index_name not in index_groups:
                    index_groups[index_name] = []
                index_groups[index_name].append(entry)

            logger.debug(f"[LoggingService] Grouped entries into {len(index_groups)} indices: {list(index_groups.keys())}")

            # 批量写入每个索引
            for index_name, entries in index_groups.items():
                logger.debug(f"[LoggingService] Processing {len(entries)} entries for index {index_name}")

                # 确保索引存在
                mapping = (SYSTEM_LOG_MAPPING if 'system_logs' in index_name
                          else OPERATION_LOG_MAPPING)
                await self.index_manager.ensure_index_exists(index_name, mapping)

                # 准备批量操作
                actions = []
                for entry in entries:
                    actions.append({
                        "index": {
                            "_index": index_name,
                            "_id": entry.get('_id')
                        }
                    })
                    actions.append(entry['_source'])

                # 执行批量写入
                if actions:
                    logger.debug(f"[LoggingService] Executing bulk write with {len(actions)//2} documents to {index_name}")
                    result = await self.es_client.bulk(body=actions)

                    # 检查结果
                    if result.get('errors'):
                        logger.error(f"[LoggingService] Bulk write had errors: {result}")
                        # 记录具体的错误信息
                        for item in result.get('items', []):
                            if 'index' in item and 'error' in item['index']:
                                error_info = item['index']['error']
                                logger.error(f"[LoggingService] Document error: {error_info}")
                        raise Exception(f"Bulk write failed with errors")
                    else:
                        logger.debug(f"[LoggingService] Successfully wrote {len(actions)//2} documents to {index_name}")

            logger.debug(f"[LoggingService] Successfully flushed {len(batch)} log entries")

        except Exception as e:
            logger.warning(f"[LoggingService] Failed to flush batch: {str(e)}")
            logger.debug(f"[LoggingService] Batch flush error details:", exc_info=True)
    
    async def log_system_request(self, log_data: Dict[str, Any]):
        """记录系统日志"""
        if not self._running or not self._es_available:
            logger.warning(f"[LoggingService] ❌ 服务不可用，丢弃日志: {log_data.get('request_id', 'unknown')}")
            return

        try:
            # 确保数据类型正确处理
            processed_data = self._process_log_data(log_data)

            # 准备日志条目
            index_name = get_daily_index_name('system_logs')
            entry = {
                '_index': index_name,
                '_source': {
                    '@timestamp': datetime.utcnow().isoformat(),
                    **processed_data
                }
            }

            logger.info(f"[LoggingService] 准备写入ES索引: {index_name}, request_id={processed_data.get('request_id', 'unknown')}")

            # 添加到队列
            try:
                self._write_queue.put_nowait(entry)
                logger.info(f"[LoggingService] ✅ 日志已加入队列，队列大小: {self._write_queue.qsize()}")
            except asyncio.QueueFull:
                logger.warning("[LoggingService] ❌ 日志队列已满，丢弃条目")

        except Exception as e:
            logger.error(f"[LoggingService] ❌ 系统日志入队失败: {str(e)}")

    def _process_log_data(self, log_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理日志数据，确保数据类型正确"""
        processed = {}
        for key, value in log_data.items():
            if value is None:
                processed[key] = None
            elif key in ['user_id', 'tenant_id', 'operator_id', 'record_id'] and value is not None:
                # 将大整数转为字符串存储，避免ES中的精度问题
                processed[key] = str(value) if value else None
            elif key == 'ip' and value is not None:
                # 确保 IP 字段是有效的 IP 地址格式
                if value == 'system' or not self._is_valid_ip(value):
                    processed[key] = '127.0.0.1'  # 默认使用本地IP
                else:
                    processed[key] = value
            elif key == 'log_type' and value is not None:
                # log_type 字段需要确保是字符串，并且不被意外修改
                processed[key] = str(value).strip() if value else None
                logger.debug(f"[LoggingService] Processing log_type: {processed[key]}")
            elif key == 'request_params' and value is not None:
                # request_params 存储为 text 类型（支持模糊搜索）
                if isinstance(value, (dict, list)):
                    import json
                    processed[key] = json.dumps(value, ensure_ascii=False)
                else:
                    processed[key] = str(value)
            elif key == 'changes' and value is not None:
                # 处理 changes 字段，确保 old_value 和 new_value 是字符串
                processed[key] = self._process_changes(value)
            elif key in ['request_body', 'response_body'] and value is not None:
                # request_body 和 response_body 存储为 flattened 类型
                # flattened 类型需要接收对象（dict）或数组（list），不能是纯字符串
                if isinstance(value, str):
                    # 如果是字符串，尝试解析为 JSON 对象
                    try:
                        import json
                        parsed = json.loads(value)
                        # 确保解析结果是对象或数组
                        if isinstance(parsed, (dict, list)):
                            processed[key] = parsed
                        else:
                            # 如果解析结果是标量值，包装成对象
                            processed[key] = {'_value': parsed}
                    except (json.JSONDecodeError, ValueError):
                        # 如果解析失败，包装成对象（避免 flattened 类型错误）
                        processed[key] = {'_raw': value}
                elif isinstance(value, (dict, list)):
                    # 如果已经是对象或数组，直接存储（flattened 会自动处理）
                    processed[key] = value
                else:
                    # 其他类型，转换为字符串并包装成对象
                    processed[key] = {'_value': str(value)}

            else:
                processed[key] = value
        return processed

    def _process_changes(self, changes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """处理 changes 字段，确保 old_value 和 new_value 是字符串"""
        if not isinstance(changes, list):
            return changes

        processed_changes = []
        for change in changes:
            if not isinstance(change, dict):
                processed_changes.append(change)
                continue

            processed_change = {}
            for field_key, field_value in change.items():
                if field_key in ['old_value', 'new_value']:
                    # 将 old_value 和 new_value 转换为字符串
                    if field_value is None:
                        processed_change[field_key] = None
                    elif isinstance(field_value, (dict, list)):
                        import json
                        processed_change[field_key] = json.dumps(field_value, ensure_ascii=False)
                    else:
                        processed_change[field_key] = str(field_value)
                else:
                    processed_change[field_key] = field_value

            processed_changes.append(processed_change)

        return processed_changes

    def _is_valid_ip(self, ip_str: str) -> bool:
        """检查是否是有效的IP地址"""
        try:
            import ipaddress
            ipaddress.ip_address(ip_str)
            return True
        except ValueError:
            return False
    
    async def log_operation(self, log_data: Dict[str, Any]):
        """记录操作日志"""
        if not self._running or not self._es_available:
            logger.debug(f"[LoggingService] Service not available, dropping log: {log_data.get('request_id', 'unknown')}")
            return

        try:
            # 确保数据类型正确处理
            processed_data = self._process_log_data(log_data)

            # 准备日志条目
            index_name = get_daily_index_name('operation_logs')
            entry = {
                '_index': index_name,
                '_source': {
                    '@timestamp': datetime.utcnow().isoformat(),
                    **processed_data
                }
            }

            # 调试：打印即将写入ES的数据
            logger.debug(f"[LoggingService] Writing operation log to ES: {json.dumps(entry['_source'], ensure_ascii=False)}")

            # 添加到队列
            try:
                self._write_queue.put_nowait(entry)
            except asyncio.QueueFull:
                logger.warning("[LoggingService] Log queue full, dropping entry")

        except Exception as e:
            logger.warning(f"[LoggingService] Failed to queue operation log: {str(e)}")


# 全局日志服务实例
_logging_service: Optional[LoggingService] = None


async def init_logging_service():
    """初始化日志服务"""
    global _logging_service
    if _logging_service is None:
        _logging_service = LoggingService()
        await _logging_service.start()
        logger.info("[LoggingService] Initialized")


async def close_logging_service():
    """关闭日志服务"""
    global _logging_service
    if _logging_service:
        await _logging_service.stop()
        _logging_service = None


def get_logging_service() -> Optional[LoggingService]:
    """获取日志服务实例"""
    return _logging_service


async def log_system_request(log_data: Dict[str, Any]):
    """记录系统日志的便捷函数"""
    service = get_logging_service()
    if service:
        logger.info(f"[log_system_request] 开始记录系统日志: {log_data.get('request_id', 'unknown')}")
        await service.log_system_request(log_data)
        logger.info(f"[log_system_request] ✅ 系统日志记录完成")
    else:
        logger.warning(f"[log_system_request] ❌ 日志服务不可用，丢弃日志: {log_data.get('request_id', 'unknown')}")


async def log_operation(log_data: Dict[str, Any]):
    """记录操作日志的便捷函数"""
    service = get_logging_service()
    if service:
        await service.log_operation(log_data)
