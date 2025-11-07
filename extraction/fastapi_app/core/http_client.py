import asyncio
from typing import Dict, Any, Optional, Union
import httpx
from loguru import logger
from fastapi_app.utils.exceptions import ResponseFailed


class HttpClient:
    """统一的HTTP客户端封装"""
    
    def __init__(self, base_url: str = "", timeout: int = 30):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
    
    def _make_url(self, endpoint: str) -> str:
        """构建完整URL"""
        if endpoint.startswith('http'):
            return endpoint
        return f"{self.base_url}/{endpoint.lstrip('/')}"
    
    async def _handle_response(self, response: httpx.Response) -> Dict[str, Any]:
        """处理响应数据"""
        try:
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP错误: {e.response.status_code} - {e.response.text}")
            raise ResponseFailed(reason=f"HTTP请求失败: {e.response.status_code}", code=-1, status_code=e.response.status_code, error=e, data=response.text)
        except Exception as e:
            logger.error(f"响应解析失败: {str(e)}")
            raise ResponseFailed(reason=f"响应解析失败: {str(e)}", code=-2, status_code=response.status_code, error=e, data=response.text)
    
    async def post(self, 
                   endpoint: str, 
                   json_data: Optional[Dict] = None,
                   headers: Optional[Dict] = None) -> Dict[str, Any]:
        """发送POST请求"""
        url = self._make_url(endpoint)
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(f"发送POST请求到: {url}")
            response = await client.post(
                url,
                json=json_data,
                headers=headers
            )
            return await self._handle_response(response)
    
    async def get(self,
                  endpoint: str,
                  params: Optional[Dict] = None,
                  headers: Optional[Dict] = None) -> Dict[str, Any]:
        """发送GET请求"""
        url = self._make_url(endpoint)
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            logger.info(f"发送GET请求到: {url}")
            response = await client.get(
                url,
                params=params,
                headers=headers
            )
            return await self._handle_response(response)
