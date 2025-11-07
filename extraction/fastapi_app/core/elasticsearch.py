"""
异步Elasticsearch客户端管理
"""
import os
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List
from elasticsearch import AsyncElasticsearch
from loguru import logger

from .config import get_settings


class AsyncESClient:
    """异步ES客户端单例"""
    _instance: Optional['AsyncESClient'] = None
    _client: Optional[AsyncElasticsearch] = None
    _initialized: bool = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def initialize(self) -> bool:
        """初始化ES客户端"""
        if self._initialized and self._client:
            return True

        # 检查ES是否启用
        settings = get_settings()
        if not settings.es_enabled:
            logger.info("[AsyncES] ES logging is disabled by configuration (ES_ENABLED=false)")
            self._client = None
            self._initialized = False
            return False

        try:
            hosts = settings.es_hosts.split(',')

            logger.info(f"[AsyncES] Initializing with hosts: {hosts}")

            # 准备客户端配置
            client_config = {
                "hosts": hosts,
                "request_timeout": settings.es_timeout,
                "max_retries": settings.es_max_retries,
                "retry_on_timeout": True,
                "maxsize": 20,
                "verify_certs": False,  # 对于HTTP连接，禁用证书验证
            }

            # 如果配置了认证信息，添加认证
            if settings.es_username and settings.es_password:
                client_config["basic_auth"] = (settings.es_username, settings.es_password)
                logger.info(f"[AsyncES] Using basic auth with username: {settings.es_username}")

            self._client = AsyncElasticsearch(**client_config)

            # 测试连接
            await self._client.ping()
            self._initialized = True
            logger.info("[AsyncES] Client initialized successfully")
            return True

        except Exception as e:
            logger.warning(f"[AsyncES] Failed to initialize client: {str(e)}")
            logger.warning(f"[AsyncES] ES logging will be disabled. Set ES_ENABLED=false to suppress this warning.")
            self._client = None
            self._initialized = False
            return False
    
    async def close(self):
        """关闭ES客户端"""
        if self._client:
            try:
                # 添加 2 秒超时
                await asyncio.wait_for(self._client.close(), timeout=2.0)
                logger.info("[AsyncES] Client closed")
            except asyncio.TimeoutError:
                logger.warning("[AsyncES] Timeout closing client (2s), forcing close")
            except Exception as e:
                logger.error(f"[AsyncES] Error closing client: {e}")
            finally:
                self._client = None
                self._initialized = False
    
    def get_client(self) -> Optional[AsyncElasticsearch]:
        """获取ES客户端实例"""
        return self._client
    
    def is_available(self) -> bool:
        """检查ES是否可用"""
        return self._initialized and self._client is not None


# 全局实例
_es_client = AsyncESClient()


async def init_async_es() -> bool:
    """初始化异步ES客户端"""
    return await _es_client.initialize()


async def close_async_es():
    """关闭异步ES客户端"""
    await _es_client.close()


def get_async_es_client() -> Optional[AsyncElasticsearch]:
    """获取异步ES客户端"""
    return _es_client.get_client()


def is_es_available() -> bool:
    """检查ES是否可用"""
    return _es_client.is_available()


class ESIndexManager:
    """ES索引管理器"""
    
    def __init__(self):
        self.client = get_async_es_client()
    
    async def ensure_index_exists(self, index_name: str, mapping: Dict[str, Any]) -> bool:
        """确保索引存在，如果不存在则创建"""
        if not self.client:
            logger.warning("[ESIndexManager] ES client not available")
            return False
        
        try:
            # 检查索引是否存在
            exists = await self.client.indices.exists(index=index_name)
            if exists:
                logger.debug(f"[ESIndexManager] Index {index_name} already exists")
                return True
            
            # 创建索引
            await self.client.indices.create(
                index=index_name,
                body={
                    "mappings": mapping,
                    "settings": {
                        "number_of_shards": 1,
                        "number_of_replicas": 0,
                        "refresh_interval": "5s"
                    }
                }
            )
            logger.info(f"[ESIndexManager] Created index: {index_name}")
            return True
            
        except Exception as e:
            logger.error(f"[ESIndexManager] Failed to create index {index_name}: {str(e)}")
            return False
    
    async def delete_old_indices(self, pattern: str, days_to_keep: int = 30):
        """删除旧的索引（基于日期模式）"""
        if not self.client:
            return
        
        try:
            # 获取匹配的索引
            indices = await self.client.indices.get(index=f"{pattern}-*")
            current_date = datetime.now()
            
            for index_name in indices.keys():
                try:
                    # 从索引名提取日期
                    date_part = index_name.split('-')[-1]  # 假设格式为 prefix-YYYY.MM.DD
                    index_date = datetime.strptime(date_part, '%Y.%m.%d')
                    
                    # 计算天数差
                    days_diff = (current_date - index_date).days
                    
                    if days_diff > days_to_keep:
                        await self.client.indices.delete(index=index_name)
                        logger.info(f"[ESIndexManager] Deleted old index: {index_name}")
                        
                except ValueError:
                    # 索引名格式不匹配，跳过
                    continue
                    
        except Exception as e:
            logger.error(f"[ESIndexManager] Failed to delete old indices: {str(e)}")


def get_daily_index_name(prefix: str, date: Optional[datetime] = None) -> str:
    """获取基于日期的索引名"""
    if date is None:
        date = datetime.now()
    env = os.getenv("ENV", "production")
    return f"{prefix}-{env}-{date.strftime('%Y.%m.%d')}"


# 索引映射定义
SYSTEM_LOG_MAPPING = {
    "properties": {
        # 基础字段
        "@timestamp": {"type": "date"},
        "tenant_id": {"type": "keyword"},  # 租户ID（精确匹配）
        "log_type": {"type": "keyword"},  # 日志分类类型（精确匹配）：error, custom, info, warning 等
        "module": {"type": "keyword"},  # 模块名称（精确匹配）

        # HTTP 请求相关字段
        "request_path": {
            "type": "text",
            "fields": {
                "keyword": {"type": "keyword"}  # 支持精确匹配和模糊搜索
            }
        },
        "request_method": {"type": "keyword"},
        "request_params": {
            "type": "text",  # 查询参数使用 text 类型，支持模糊匹配
            "fields": {
                "keyword": {"type": "keyword", "ignore_above": 256}
            }
        },
        "request_body": {
            "type": "flattened"  # 使用 flattened 类型，支持任意深度的嵌套对象，避免字段类型冲突
        },
        "response_status": {"type": "keyword"},  # HTTP状态码（精确匹配）
        "response_body": {
            "type": "flattened"  # 使用 flattened 类型，支持任意深度的嵌套对象，避免字段类型冲突
        },
        "response_time": {"type": "float"},

        # 用户和网络信息
        "ip": {"type": "ip"},
        "user_agent": {
            "type": "text",
            "fields": {
                "keyword": {"type": "keyword", "ignore_above": 256}
            }
        },
    }
}

OPERATION_LOG_MAPPING = {
    "properties": {
        # 基础字段
        "@timestamp": {"type": "date"},
        "tenant_id": {"type": "keyword"},  # 租户ID（精确匹配）
        "log_type": {"type": "keyword"},  # 日志分类类型（精确匹配）：error, custom, info, warning 等

        # 操作人信息
        "operator_name": {
            "type": "text",
            "fields": {
                "keyword": {"type": "keyword"}  # 支持精确匹配和模糊搜索
            }
        },

        # 操作信息
        "module": {"type": "keyword"},  # 模块名称（精确匹配）
        "operation_type": {"type": "keyword"},  # 操作类型（精确匹配）：INSERT, UPDATE, DELETE 等
        "table_name": {"type": "keyword"},

        # 操作内容
        "content": {
            "type": "text",
            "fields": {
                "keyword": {"type": "keyword", "ignore_above": 256}
            }
        },
        "message": {
            "type": "text",
            "fields": {
                "keyword": {"type": "keyword"}  # 国际化消息key，支持模糊搜索
            }
        },

        # 网络信息
        "ip": {"type": "ip"},
        "user_agent": {
            "type": "text",
            "fields": {
                "keyword": {"type": "keyword", "ignore_above": 256}
            }
        },

        # 变更详情
        "changes": {
            "type": "nested",
            "properties": {
                "field": {"type": "keyword"},
                "field_name": {"type": "keyword"},
                "old_value": {
                    "type": "text",
                    "fields": {
                        "keyword": {"type": "keyword", "ignore_above": 256}
                    }
                },
                "new_value": {
                    "type": "text",
                    "fields": {
                        "keyword": {"type": "keyword", "ignore_above": 256}
                    }
                },
                "change_type": {"type": "keyword"}  # ADD, UPDATE, DELETE
            }
        }
    }
}
