"""
FastAPI 认证中间件
"""
import re
from typing import Callable
from fastapi import Request, Response, BackgroundTasks
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger
from fastapi_app.core.context import current_context, WithRequestContext, WithAuthenticatedContext
from fastapi_app.i18n import get_language_from_request, get_locale_text
from fastapi_app.core.database import get_async_session
from fastapi_app.modules.auth_service.account.model import Role
from fastapi_app.modules.auth_service.user.model import User
from fastapi_app.schemas.schema import UserInfo, ContextInfo
from flask_app.modules.common_service.enums.enums import Common, Role as RoleEnums


class AuthMiddleware(BaseHTTPMiddleware):
    """
    认证中间件
    验证JWT令牌并设置用户上下文到 request.state
    """

    # 白名单（支持精确或正则）
    WHITELIST_PATTERNS = [
        r"^/$",
        r"^/health$",
        r"^/favicon\.ico$",
        # 文档与 OpenAPI
        r"^/docs/?$",
        r"^/redoc/?$",
        r"^/openapi\.json$",
        # 放行挂载到 /api 的 Flask 子应用，由 Flask 自行做鉴权
        r"^/api(/.*)?$",
        # v2 API 常见开放入口
        r"^/api_v2/docs/?$",
        r"^/api_v2/redoc/?$",
        r"^/api_v2/openapi\.json$",
        r"^/api_v2/auth/login$",
        r"^/api_v2/auth/register$",
        r"^/api_v2/auth/outer_login$",
        r"^/api_v2/health$",
        # 放行 SSO 接口
        r"^/sso/login$",
        r"^/sso/authorize$",
        # 放行 chat 接口
        r"^/api_v2/chat(/.*)?$",
        r"^/api_v2/master-data(/.*)?$",
        # 放行上传文件接口
        r"^/api_v2/oqc-document-extraction-tasks/upload$"
        # 放行OQC上传文件、更新记录接口
        r"^/api_v2/oqc-document-extraction-tasks/inner-update/(\d+)$",
        r"^/api_v2/oqc-document-extraction-tasks/upload$",
        # 放行PDA接口
        r"^/api_v2/pda-document-extraction-tasks/extract-images-to-json$",
    ]

    def _is_whitelisted(self, path: str) -> bool:
        for pattern in self.WHITELIST_PATTERNS:
            try:
                if re.match(pattern, path):
                    return True
            except re.error:
                # 兜底：精确匹配
                if path == pattern:
                    return True
        return False

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        language: str = get_language_from_request(request)
        # 将语言储存在每个请求对象中
        request.state.language = language

        with WithRequestContext(request) as wrc: # 上下文ContextVar存储请求对象、创建基于请求的后台任务暂存器，自动处理token的set和reset
            logger.info(f"执行认证中间件")
            path = request.url.path
            # 白名单直接放行
            if self._is_whitelisted(path):
                response: Response = await call_next(request)
                wrc.submit_tasks(response)
                return response

            try:
                from flask_app.utils.jwt import decode_internal_token

                # 获取 Authorization: Bearer <token>
                auth_header = request.headers.get("Authorization")
                if not auth_header:
                    auth_header = request.get("token")
                    if auth_header:
                        auth_header = f"Bearer {auth_header}"
                if not auth_header:
                    return JSONResponse({"message": get_locale_text("auth.error.token_expired")}, status_code=401)

                parts = auth_header.split(" ")
                if len(parts) != 2 or parts[0].lower() != "bearer":
                    return JSONResponse({"message": get_locale_text("auth.error.invalid_format")}, status_code=401)

                token = parts[1]
                payload: dict = decode_internal_token(token)

                # 获取用户信息
                user_id = payload.get("user_id")
                if not user_id:
                    return JSONResponse({"message": get_locale_text("auth.error.token_expired")}, status_code=401)

                # 获取租户ID
                tenant_id = payload.get("tenant_id")
                belong_org = payload.get('belong_org')
                manage_orgs = payload.get('manage_orgs', [])

                # 使用独立的会话查询用户信息，避免在中间件中持久占用事务
                async with get_async_session() as db:
                    # 查询用户信息
                    user: User = await User.select_by_id(user_id, db=db)
                    
                    if not user or getattr(user, "is_delete", False) or user.status != Common.Status.ENABLED.value.value:
                        return JSONResponse({"message": get_locale_text("auth.error.token_expired")}, status_code=401)

                    role_codes = await Role.select_role_codes_by_user_id(user_id=user_id, tenant_id=tenant_id, db=db)

                if RoleEnums.Type.SUPER_ADMIN.value.value not in role_codes and not tenant_id:
                    logger.warning(f"❌ User {user_id} is not super admin and no tenant id provided")
                    return JSONResponse({"message": get_locale_text("auth.error.token_expired")}, status_code=401)

                # 计算 username
                if getattr(user, "first_name", None) and getattr(user, "last_name", None):
                    username = f"{user.first_name} {user.last_name}"
                elif getattr(user, "username", None):
                    username = user.username
                else:
                    username = getattr(user, "email", None) or "unknown"

                context_info = ContextInfo(
                    user=UserInfo.model_validate(user),
                    user_id=user_id,
                    role_codes=role_codes,
                    tenant_id=tenant_id,
                    belong_org=belong_org,
                    manage_orgs=manage_orgs,
                    username=username
                )
            except Exception as e:
                logger.error(f"认证过程发生错误: {str(e)}")
                return JSONResponse({"message": get_locale_text("auth.error.token_expired")}, status_code=401)

            with WithAuthenticatedContext(context_info): # 上下文ContextVar存储认证信息，自动处理token的set和reset
                # 同时将用户信息存储到 request.state 中，供其他中间件使用
                request.state.user_id = user_id
                request.state.tenant_id = tenant_id
                request.state.context_info = context_info

                response: Response = await call_next(request)
                wrc.submit_tasks(response)
                return response


async def get_current_user(request: Request) -> dict:
    """获取当前用户信息的依赖函数"""
    try:
        context = current_context.get()
        return {
            'user_id': context.user_id,
            'username': context.username,
            'tenant_id': context.tenant_id,
            'role_codes': context.role_codes
        }
    except Exception:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="未认证或认证信息无效")
