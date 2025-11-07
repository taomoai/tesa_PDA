"""
外部 API 调用日志记录工具

用于统一记录调用外部 API（如 Mendix）的请求和响应信息到系统日志中
"""

import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional
from loguru import logger
from fastapi_app.services.logging_service import log_system_request


def _extract_status_code_from_error(error_message: str) -> Optional[int]:
    """
    从错误信息中提取 HTTP 状态码

    :param error_message: 错误信息字符串
    :return: 提取到的状态码，如果没有找到则返回 None
    """
    if not error_message:
        return None

    # 常见的状态码模式
    patterns = [
        r"HTTP请求失败:\s*(\d{3})",  # HTTP请求失败: 500
        r"Server error '(\d{3})",    # Server error '500'
        r"status.*?(\d{3})",         # status 500, status code 500
        r"状态码.*?(\d{3})",         # 状态码: 500, 状态码非200: 400
        r"HTTPStatusError.*?(\d{3})", # HTTPStatusError 500
        r"ResponseFailed.*?(\d{3})",  # ResponseFailed 500
    ]

    for pattern in patterns:
        match = re.search(pattern, error_message, re.IGNORECASE)
        if match:
            try:
                status_code = int(match.group(1))
                # 验证状态码范围
                if 100 <= status_code <= 599:
                    return status_code
            except (ValueError, IndexError):
                continue

    return None


class ExternalAPILogger:
    """外部 API 调用日志记录器"""
    
    def __init__(self, api_name: str, base_url: str = None):
        """
        初始化外部 API 日志记录器
        
        :param api_name: API 名称（如 "Mendix", "WeChat", "Alipay" 等）
        :param base_url: API 基础 URL
        """
        self.api_name = api_name
        self.base_url = base_url
        self.call_id = str(uuid.uuid4())
        self.start_time = None
        self.request_data = {}
        self.response_data = {}
        
    def start_call(self,
                   endpoint: str,
                   method: str = "POST",
                   request_body: Optional[Dict] = None,
                   headers: Optional[Dict] = None,
                   additional_info: Optional[Dict] = None):
        """
        开始记录 API 调用

        :param endpoint: API 端点
        :param method: HTTP 方法
        :param request_body: 请求体
        :param headers: 请求头（敏感信息会被脱敏）
        :param additional_info: 额外信息（如 task_id, tenant_id 等）
        """
        self.start_time = time.time()

        # 构建完整 URL
        full_url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}" if self.base_url else endpoint

        # 脱敏处理请求头
        safe_headers = self._sanitize_headers(headers) if headers else None

        self.request_data = {
            "call_id": self.call_id,
            "api_name": self.api_name,
            "url": full_url,
            "method": method,
            "request_body": request_body,
            "request_headers": json.dumps(safe_headers) if safe_headers else None,
            "additional_info": json.dumps(additional_info) if additional_info else None,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # 控制台日志
        logger.info(f"[ExternalAPI] {self.api_name} 调用开始: {self.call_id} -> {method} {full_url}")
        
    def end_call(self,
                 response_body: Optional[Dict] = None,
                 status_code: Optional[int] = None,
                 error: Optional[str] = None,
                 additional_response_info: Optional[Dict] = None):
        """
        结束记录 API 调用

        :param response_body: 响应体
        :param status_code: HTTP 状态码
        :param error: 错误信息（如果有）
        :param additional_response_info: 响应相关的额外信息
        """
        end_time = time.time()
        duration = end_time - self.start_time if self.start_time else 0

        # 合并请求时的 additional_info 和响应时的额外信息
        request_additional_info = json.loads(self.request_data.get("additional_info", "{}")) if self.request_data.get("additional_info") else {}
        merged_additional_info = request_additional_info.copy()
        if additional_response_info:
            merged_additional_info.update(additional_response_info)

        self.response_data = {
            "response_body": response_body,
            "status_code": status_code,
            "error": error,
            "duration_ms": round(duration * 1000, 2),
            "success": error is None and (status_code is None or 200 <= status_code < 300),
            "additional_info": json.dumps(merged_additional_info) if merged_additional_info else None,
            "end_timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # 控制台日志
        status = "成功" if self.response_data["success"] else "失败"
        logger.info(f"[ExternalAPI] {self.api_name} 调用{status}: {self.call_id} - {duration:.3f}s")
        
        if error:
            logger.error(f"[ExternalAPI] {self.api_name} 调用错误: {self.call_id} - {error}")
    
    async def save_log(self):
        """
        保存日志到系统日志
        """
        try:
            # 获取当前用户信息（如果可用）
            user_id = None
            tenant_id = None
            try:
                from fastapi_app.core.context import current_context
                context = current_context.get()
                user_id = context.username
                tenant_id = context.tenant_id
            except Exception:
                pass

            # 构建与系统日志一致的字段格式
            log_data = {
                # 基础字段（与 _log_to_es 保持一致）
                'request_id': self.call_id,
                'request_path': self.request_data.get('url', ''),  # 使用完整URL作为路径
                'request_method': self.request_data.get('method', 'POST'),
                'request_params': None,  # 外部API调用通常没有query参数
                'request_body': self.request_data.get('request_body'),
                'response_status': str(self.response_data.get('status_code', '')) if self.response_data.get('status_code') else None,
                'response_body': self.response_data.get('response_body'),
                'response_time': self.response_data.get('duration_ms', 0) / 1000.0,  # 转换为秒
                'ip': '127.0.0.1',  # 系统内部调用，使用本地IP
                'user_agent': f"TaomoAI-Server/{self.api_name}",  # 标识为系统调用
                'user_id': user_id,
                'tenant_id': tenant_id,
                'framework': 'System',  # 标识为系统调用

                # 方向和类型标识
                'log_type': 'external_api_call',  # 标识为系统调用外部接口
                'direction': 'outbound',  # 请求方向：出站

                # 外部API特有字段
                'api_name': self.api_name,
                'call_id': self.call_id,
                'success': self.response_data.get('success', False),
                'error': self.response_data.get('error'),
                'additional_info': self.response_data.get('additional_info'),
                'request_headers': self.request_data.get('request_headers'),
                'timestamp': self.request_data.get('timestamp'),
                'end_timestamp': self.response_data.get('end_timestamp')
            }

            # 记录到系统日志
            await log_system_request(log_data)

            logger.debug(f"[ExternalAPI] 日志已保存: {self.call_id}")

        except Exception as e:
            logger.error(f"[ExternalAPI] 保存日志失败: {self.call_id} - {str(e)}")
    
    def _sanitize_headers(self, headers: Dict) -> Dict:
        """
        脱敏处理请求头，隐藏敏感信息
        
        :param headers: 原始请求头
        :return: 脱敏后的请求头
        """
        sensitive_keys = {
            'authorization', 'auth', 'token', 'password', 'secret', 'key',
            'x-api-key', 'x-auth-token', 'cookie', 'set-cookie'
        }
        
        safe_headers = {}
        for key, value in headers.items():
            key_lower = key.lower()
            if any(sensitive in key_lower for sensitive in sensitive_keys):
                # 保留前几个字符，其余用 * 替代
                if isinstance(value, str) and len(value) > 8:
                    safe_headers[key] = value[:4] + "*" * (len(value) - 8) + value[-4:]
                else:
                    safe_headers[key] = "***"
            else:
                safe_headers[key] = value
                
        return safe_headers


# 便捷函数
async def log_external_api_call(api_name: str,
                               endpoint: str,
                               method: str = "POST",
                               request_body: Optional[Dict] = None,
                               response_body: Optional[Dict] = None,
                               headers: Optional[Dict] = None,
                               status_code: Optional[int] = None,
                               error: Optional[str] = None,
                               base_url: Optional[str] = None,
                               additional_info: Optional[Dict] = None,
                               duration_ms: Optional[float] = None):
    """
    便捷函数：一次性记录完整的外部 API 调用

    :param api_name: API 名称（如 "Mendix", "WeChat", "Alipay" 等）
    :param endpoint: API 端点
    :param method: HTTP 方法
    :param request_body: 请求体
    :param response_body: 响应体
    :param headers: 请求头
    :param status_code: HTTP 状态码
    :param error: 错误信息
    :param base_url: 基础 URL
    :param additional_info: 额外信息（如 task_id, tenant_id, product_id 等）
    :param duration_ms: 请求耗时（毫秒），如果不提供则使用0
    """
    api_logger = ExternalAPILogger(api_name, base_url)

    # 开始记录
    api_logger.start_call(
        endpoint=endpoint,
        method=method,
        request_body=request_body,
        headers=headers,
        additional_info=additional_info
    )

    # 结束记录
    api_logger.end_call(
        response_body=response_body,
        status_code=status_code,
        error=error
    )

    # 如果提供了duration_ms，覆盖计算的时间
    if duration_ms is not None:
        api_logger.response_data['duration_ms'] = duration_ms

    # 保存日志
    await api_logger.save_log()


async def log_external_api_call_unified(api_name: str,
                                       url: str,
                                       method: str = "POST",
                                       request_body: Optional[Dict] = None,
                                       response_body: Optional[Dict] = None,
                                       headers: Optional[Dict] = None,
                                       status_code: Optional[int] = None,
                                       error: Optional[str] = None,
                                       duration_seconds: Optional[float] = None,
                                       additional_info: Optional[Dict] = None):
    """
    统一格式的外部API调用日志记录函数
    直接使用与系统日志一致的字段格式，避免字段转换

    :param api_name: API 名称（如 "Mendix", "WeChat", "Alipay" 等）
    :param url: 完整的API URL
    :param method: HTTP 方法
    :param request_body: 请求体
    :param response_body: 响应体
    :param headers: 请求头（敏感信息会被脱敏）
    :param status_code: HTTP 状态码
    :param error: 错误信息
    :param duration_seconds: 请求耗时（秒）
    :param additional_info: 额外信息（如 task_id, tenant_id, product_id 等）
    """
    try:
        # 生成唯一的调用ID
        call_id = str(uuid.uuid4())

        logger.info(f"[log_external_api_call_unified] 开始处理: {api_name} -> {url} (调用ID: {call_id})")

        # 获取当前用户信息（如果可用）
        user_id = None
        tenant_id = None
        try:
            from fastapi_app.core.context import current_context
            context = current_context.get()
            user_id = context.username
            tenant_id = context.tenant_id
        except Exception:
            pass

        # 如果从上下文获取不到 tenant_id（如在 Celery 任务中），尝试从 additional_info 中获取
        if not tenant_id and additional_info and 'tenant_id' in additional_info:
            tenant_id = additional_info['tenant_id']
            logger.info(f"[log_external_api_call_unified] 从 additional_info 中获取 tenant_id: {tenant_id}")

        # 如果从上下文获取不到 user_id，也尝试从 additional_info 中获取
        if not user_id and additional_info and 'user_id' in additional_info:
            user_id = additional_info['user_id']

        # 脱敏处理请求头
        safe_headers = None
        if headers:
            external_logger = ExternalAPILogger(api_name)
            safe_headers = external_logger._sanitize_headers(headers)

        # 如果没有提供 status_code 但有错误信息，尝试从错误信息中解析状态码
        if status_code is None and error:
            status_code = _extract_status_code_from_error(error)
            if status_code:
                logger.info(f"[log_external_api_call_unified] 从错误信息中解析出状态码: {status_code}")

        # 构建与系统日志完全一致的字段格式
        log_data = {
            # 基础字段（与 _log_to_es 完全一致）
            'request_id': call_id,
            'request_path': url,
            'request_method': method,
            'request_params': None,  # 外部API调用通常没有query参数
            'request_body': request_body,
            'response_status': str(status_code) if status_code else None,
            'response_body': response_body,
            'response_time': duration_seconds or 0.0,
            'ip': '127.0.0.1',  # 系统内部调用，使用本地IP
            'user_agent': f"TaomoAI-Server/{api_name}",
            'user_id': user_id,
            'tenant_id': tenant_id,
            'framework': 'System',

            # 方向和类型标识
            'log_type': 'external_api_call',
            'direction': 'outbound',

            # 外部API特有字段
            'api_name': api_name,
            'call_id': call_id,
            'success': error is None and (status_code is None or 200 <= status_code < 300),
            'error': error,
            'request_headers': json.dumps(safe_headers) if safe_headers else None,
            'additional_info': json.dumps(additional_info) if additional_info else None,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }

        # 打印即将存储的日志数据结构
        logger.info(f"[log_external_api_call_unified] 构建的日志数据:")
        logger.info(f"  - request_id: {log_data.get('request_id')}")
        logger.info(f"  - request_path: {log_data.get('request_path')}")
        logger.info(f"  - request_method: {log_data.get('request_method')}")
        logger.info(f"  - response_status: {log_data.get('response_status')}")
        logger.info(f"  - log_type: {log_data.get('log_type')}")
        logger.info(f"  - api_name: {log_data.get('api_name')}")
        logger.info(f"  - direction: {log_data.get('direction')}")
        logger.info(f"  - framework: {log_data.get('framework')}")
        logger.info(f"  - success: {log_data.get('success')}")
        logger.info(f"  - error: {log_data.get('error')}")
        logger.info(f"  - tenant_id: {log_data.get('tenant_id')}")

        # 记录到系统日志
        logger.info(f"[log_external_api_call_unified] 开始调用 log_system_request...")
        await log_system_request(log_data)
        logger.info(f"[log_external_api_call_unified] ✅ log_system_request 调用完成")

        # 控制台日志
        status = "成功" if log_data['success'] else "失败"
        logger.info(f"[ExternalAPI] {api_name} 调用{status}: {call_id} -> {method} {url} - {duration_seconds or 0:.3f}s")

        if error:
            logger.error(f"[ExternalAPI] {api_name} 调用错误: {call_id} - {error}")

    except Exception as e:
        logger.error(f"[ExternalAPI] ❌ 记录外部API调用日志失败: {str(e)}")
        logger.error(f"[ExternalAPI] 错误详情:", exc_info=True)



