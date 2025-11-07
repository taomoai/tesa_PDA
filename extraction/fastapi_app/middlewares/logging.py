"""
FastAPI 统一日志中间件 - 记录所有请求到ES
"""
import re
import time
import uuid
import json
from typing import Callable, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger
from fastapi_app.core.context import current_context
from fastapi_app.services.logging_service import log_system_request


log_type_map = {
    '/api_v2/master-data/update': 'mendix_to_ai',
    '/api_v2/oqc-document-extraction-tasks/upload': 'mendix_to_ai',
    '/api/users/login': 'login',
    '/api/users/outer_login': 'outer_login',
}

class LoggingMiddleware(BaseHTTPMiddleware):
    """
    统一日志中间件
    记录所有API请求的详细信息到ES（包括挂载的Flask路由）
    """

    def __init__(self, app):
        super().__init__(app)
        # 不需要记录的路径
        self.skip_paths = {
            '/favicon.ico',
            '/docs',
            '/redoc',
            '/openapi.json',
            '/health',
            '/api_v2/health',
            '/api_v2/docs',
            '/api_v2/redoc',
            '/api_v2/logs',
            '/api_v2/logs/system',
            '/api_v2/logs/operation',
            '/api/audit_log/logs',
            '/api/operation_log'
        }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        logger.info(f"执行日志中间件")
        # 生成请求ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # 记录请求开始
        start_time = time.time()
        client_ip = self._get_client_ip(request)

        # 初始化用户信息（稍后在响应处理后获取）
        user_name = None
        tenant_id = None

        # 读取请求体（如果需要）
        request_body = await self._get_request_body(request)

        # 控制台日志
        logger.info(
            f"[Request] {request_id}: {request.method} {request.url.path} {user_name} {tenant_id} {request_body} "
            f"from {client_ip}"
        )

        # 执行请求
        response = await call_next(request)

        # 计算处理时间
        process_time = time.time() - start_time

        # 获取响应体（关键：通过迭代器获取完整响应体）
        response_body = None
        try:
            res_body_bytes = b''
            async for chunk in response.body_iterator:
                res_body_bytes += chunk

            if res_body_bytes and len(res_body_bytes) < 10000:  # 限制10KB
                response_body = self._try_decode_json(res_body_bytes)

            # 重新构造响应，因为原来的 body_iterator 已经被消耗
            response = Response(
                content=res_body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
        except Exception as e:
            logger.debug(f"Failed to get response body: {e}")
            response_body = None

        # 获取用户信息（多种方式尝试）
        user_name = None
        tenant_id = None

        # 方式1：从 current_context 获取
        try:
            context = current_context.get()
            user_name = context.username
            tenant_id = context.tenant_id
            logger.debug(f"从 current_context 获取用户信息: user_name={user_name}, tenant_id={tenant_id}")
        except Exception as e:
            logger.debug(f"无法从 current_context 获取用户信息: {e}")

            # 方式2：从 request.state 获取（兜底）
            user_name = getattr(request.state, 'username', None)
            tenant_id = getattr(request.state, 'tenant_id', None)
            logger.debug(f"从 request.state 获取用户信息: user_name={user_name}, tenant_id={tenant_id}")

            # 方式3：如果还是没有，尝试从 JWT token 直接解析（最后兜底）
            if not user_name:
                try:
                    auth_header = request.headers.get("Authorization")
                    if auth_header and auth_header.startswith("Bearer "):
                        import jwt
                        from fastapi_app.core.config import load_project_config

                        token = auth_header.split(" ")[1]
                        project_config = load_project_config()
                        jwt_config = project_config.get("jwt", {})
                        secret_key = jwt_config.get("secret_key")

                        if secret_key:
                            payload = jwt.decode(token, secret_key, algorithms=["HS256"])
                            user_name = payload.get("username")
                            tenant_id = payload.get("tenant_id")
                            logger.debug(f"从 JWT token 获取用户信息: user_name={user_name}, tenant_id={tenant_id}")
                except Exception as jwt_e:
                    logger.debug(f"无法从 JWT token 获取用户信息: {jwt_e}")

        # 控制台日志
        logger.info(
            f"[Response] {request_id}: {response.status_code} in {process_time:.4f}s"
        )

        # 添加响应头
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(process_time)

        # 确定框架类型
        framework = "Flask" if request.url.path.startswith('/api/') else "FastAPI"
        response.headers["X-Framework"] = framework

        # 记录到ES（异步，不阻塞响应）
        if not self._should_skip_logging(request.url.path):
            await self._log_to_es(
                request, response, request_id, client_ip,
                process_time, framework, user_name, tenant_id, request_body, response_body
            )

        return response

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端IP"""
        # 检查代理头
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()

        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip

        return request.client.host if request.client else "unknown"

    async def _get_request_body(self, request: Request) -> Optional[str]:
        """获取请求体"""
        try:
            if request.method in ['POST', 'PUT', 'PATCH']:
                # 检查是否是 multipart/form-data 请求
                content_type = request.headers.get('content-type', '')
                if 'multipart/form-data' in content_type:
                    # 对于 multipart 请求，不记录原始体（太大且包含二进制数据）
                    # 返回一个标记对象，表示这是 multipart 请求
                    return {'_type': 'multipart/form-data', '_note': 'Binary file upload'}

                # 读取请求体
                body = await request.body()
                if body:
                    # 尝试解析为JSON
                    try:
                        return json.loads(body.decode('utf-8'))
                    except:
                        # 如果不是JSON，返回截断的字符串
                        decoded = body.decode('utf-8', errors='replace')[:1000]
                        # 对于非JSON的字符串，包装成对象以兼容 flattened 类型
                        return {'_raw': decoded}
        except Exception as e:
            logger.debug(f"Failed to read request body: {e}")
        return None

    def _should_skip_logging(self, path: str) -> bool:
        """判断是否跳过日志记录"""
        return any(skip_path in path for skip_path in self.skip_paths)

    def _try_decode_json(self, data_bytes: bytes):
        """尝试将 bytes 解码为 dict/list，如果失败则返回原始字符串"""
        try:
            return json.loads(data_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            decoded = data_bytes.decode("utf-8", errors="ignore")
            # 如果内容太长，截断
            if len(decoded) > 1000:
                return decoded[:1000] + "... [截断]"
            return decoded

    async def _get_response_body(self, response: Response) -> Optional[str]:
        """获取响应体内容 - 针对 FastAPI 优化"""
        try:
            # 对于 StreamingResponse，无法获取响应体
            if hasattr(response, '__class__') and 'Streaming' in response.__class__.__name__:
                return None

            # FastAPI 的 JSONResponse 处理
            if hasattr(response, '__class__') and 'JSON' in response.__class__.__name__:
                # 对于 JSONResponse，尝试从 body 属性获取
                if hasattr(response, 'body') and response.body:
                    try:
                        body_text = response.body.decode('utf-8')
                        # 验证是否为有效 JSON
                        import json
                        json.loads(body_text)
                        return body_text if len(body_text) < 10000 else body_text[:1000] + "... [截断]"
                    except:
                        pass

            # 通用方法：尝试多种方式获取响应体
            body_bytes = None

            # 方法1: 直接从 response.body 获取
            if hasattr(response, 'body') and response.body:
                body_bytes = response.body
            # 方法2: 从 _content 获取
            elif hasattr(response, '_content') and response._content:
                body_bytes = response._content

            if body_bytes and len(body_bytes) < 10000:  # 限制10KB
                response_text = body_bytes.decode('utf-8', errors='replace')

                # 尝试解析为JSON以验证格式
                try:
                    import json
                    json.loads(response_text)
                    return response_text
                except:
                    # 如果不是有效JSON，截断长文本
                    if len(response_text) > 1000:
                        return response_text[:1000] + "... [截断]"
                    return response_text

            # 如果以上方法都失败，返回 None（表示无法获取响应体）
            return None

        except Exception as e:
            logger.debug(f"Failed to get response body: {e}")
            return None

    async def _log_to_es(self, request: Request, response: Response,
                        request_id: str, client_ip: str, process_time: float,
                        framework: str, user_name: Optional[str], tenant_id: Optional[str],
                        request_body: Optional[str], response_body: Optional[str] = None):
        """记录日志到ES"""
        try:
            # 如果没有传入响应体，尝试获取（兜底逻辑）
            if response_body is None:
                response_body = await self._get_response_body(response)
            print(f"request_path: {request.url.path}")
            # 准备日志数据
            log_data = {
                'request_id': request_id,
                'request_path': request.url.path,
                'request_method': request.method,
                'request_params': dict(request.query_params) if request.query_params else None,
                'request_body': request_body,
                'response_status': str(response.status_code),
                'response_body': response_body,
                'response_time': process_time,
                'ip': client_ip,
                'user_agent': request.headers.get('User-Agent'),
                'user_id': user_name,
                'tenant_id': tenant_id,
                'framework': framework,
                'log_type': log_type_map.get(request.url.path, 'normal'),  # 标识为外部请求进入系统
                'direction': 'inbound'  # 请求方向：入站
            }

            logger.info(f"Log data: {json.dumps(log_data, ensure_ascii=False)}")

            # 异步记录到ES
            await log_system_request(log_data)

        except Exception as e:
            logger.error(f"Failed to log to ES: {e}")