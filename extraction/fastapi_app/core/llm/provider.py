"""
Novita 模型的具体实现，使用 OpenAI 客户端访问 Novita API。
"""

from contextlib import aclosing
from sys import api_version
from typing import Optional
from dotenv import load_dotenv

from litellm.files.main import ModelResponse
from loguru import logger
import litellm
from langsmith.run_helpers import traceable as run_traceable

from fastapi_app.core.database import get_async_db_context
from fastapi_app.core.llm.model import LLMCallHistory
from fastapi_app.utils.exceptions import AICallFailed
from flask_app.utils.snowflake import snowflake

class Provider():
    """
    Provider 是所有 AI 模型的抽象基类，定义了所有 AI 模型实现必须遵循的接口。
    """
    
    def __init__(self, 
                 api_key: Optional[str] = None, 
                 secret_key: Optional[str] = None,
                 model_name: str | None = None,
                 parameters: dict = {},
                 model_group: str | None = None,
                 custom_llm_provider: str | None = None,
                 api_base: str | None = None,
                 **kwargs):
            """
            初始化 Provider 模型。
            
            Args:
                api_key: API密钥
                secret_key: API密钥（某些提供商需要）
                model_name: 模型名称
                parameters: 模型参数
                model_group: 模型组名称
                custom_llm_provider: 自定义LLM提供商名称
                api_base: API基础URL
            """
            # 加载环境变量
            load_dotenv()
            
            # 凭证
            self.api_key = api_key
            self.secret_key = secret_key
            self.model_name = model_name or 'default'
            self.model_group = model_group
            
            # 提供商配置
            self.custom_llm_provider = custom_llm_provider
            self.api_base = api_base
            
            # 会话控制
            self.conversation = []
            self.max_conversation_length = 20
            
            # 对话角色
            self.user_role = 'user'
            self.assistant_role = 'assistant'
            self.system_role = 'system'
            
            # 模型参数
            self.parameters = parameters or {
                "temperature": 0,
                "top_p": 0.01
            }
    
    async def call_llm(self, 
                        prompt: str, 
                        image_url: str | None = None, 
                        **kwargs) -> str:
        """
        非流式调用LLM模型
        
        Args:
            prompt: 提示词文本
            image_url: 图片URL (可选)
            
        Returns:
            str: 完整的响应文本
        """
        return await self._call_llm_sync_impl(prompt, image_url, **kwargs)
    
    async def call_llm_stream(self, 
                              prompt: str, 
                              image_url: str | None = None, 
                              **kwargs):
        """
        流式调用LLM模型
        
        Args:
            prompt: 提示词文本
            image_url: 图片URL (可选)
            
        Returns:
            AsyncGenerator[str, None]: 异步生成器，产生累积的响应文本
        """

        async for chunk in self._call_llm_stream_impl(prompt, image_url, **kwargs):
            yield chunk
    
    async def _prepare_and_call(self, prompt: str, image_url: str | None = None, stream: bool = False, **kwargs):
        """
        准备参数并调用LLM的内部方法
        """
        try:
            logger.info(f"开始调用模型 {self.model_name}，提示词: {prompt[:200]}..." if len(prompt) > 200 else prompt)
            parameters = kwargs.get("parameters", self.parameters)
            model_name = kwargs.get("model_name", self.model_name)
            api_key = kwargs.get("api_key", self.api_key)
            provider = kwargs.get("provider", self.custom_llm_provider)
            api_base = kwargs.get("api_base", self.api_base)
            api_version = kwargs.get("api_version")
            content = []
            content.append({"type": "text", "text": prompt})
            
            if image_url:
                logger.info(f"包含图片URL: {image_url}")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": image_url}
                })
            
            # 准备消息格式和调用参数
            role = self.user_role
            messages = [{"role": role, "content": content}]

            call_params = {
                "model": model_name,
                "messages": messages,
                "stream": stream,
                "api_key": api_key,
            }
            
            if parameters:
                call_params.update(parameters)
            if provider:
                call_params["custom_llm_provider"] = provider
            if api_base:
                call_params["api_base"] = api_base
            if api_version:
                call_params["api_version"] = api_version

            call_params['timeout'] = 30.0

            @run_traceable
            async def completion():
                return await litellm.acompletion(**call_params)
            
            # 调用 litellm 获取响应
            response = await completion()
            await self.write_log(call_params, response)
            return response
        except Exception as e:
            error_msg = f"模型 {self.model_name} 调用失败: {str(e)}, 提示词: {prompt[:100]}..." if len(prompt) > 100 else prompt
            logger.error(error_msg)
            raise AICallFailed(reason=f"无法获取模型 {self.model_name} 响应: {str(e)}", code=101, error=e, model_name=self.model_name, prompt=prompt)
    
    async def _call_llm_sync_impl(self, prompt: str, image_url: str | None = None, **kwargs) -> str | None:
        """
        非流式调用的内部实现
        """
        response = await self._prepare_and_call(prompt, image_url, stream=False, **kwargs)
        return response.choices[0].message.content
    
    async def _call_llm_stream_impl(self, prompt: str, image_url: str | None = None, **kwargs):
        """
        流式调用的内部实现
        """
        response = await self._prepare_and_call(prompt, image_url, stream=True, **kwargs)
        result = ""
        async for chunk in response:
            chunk_result = chunk.choices[0].delta
            if not chunk_result.content:
                continue
            result += chunk_result.content
            yield result

    async def write_log(self, call_params: dict, response: ModelResponse):
        try:
            # TODO: Implement proper user context for FastAPI
            # current_info = get_current_info()
            call_history = LLMCallHistory()
            # Generate ID using snowflake (consistent with Flask app)
            call_history.id = snowflake.generate_id()
            call_history.provider = self.custom_llm_provider or ""
            call_history.model_name = self.model_name or ""
            call_history.params = call_params or {}
            # Handle different response types
            if response:
                try:
                    # For streaming responses, response might be a CustomStreamWrapper
                    if hasattr(response, 'model_dump'):
                        call_history.response = response.model_dump()
                    else:
                        # For streaming or other custom wrapper types, store basic info
                        call_history.response = {
                            "type": type(response).__name__,
                            "is_stream": hasattr(response, '__iter__'),
                            "model": getattr(response, 'model', 'unknown')
                        }
                except Exception as e:
                    logger.warning(f"Could not serialize response: {e}")
                    call_history.response = {"error": "serialization_failed", "type": type(response).__name__}
            else:
                call_history.response = {}
            # Set default value for created_by until proper user context is implemented
            call_history.created_by = 0  # Default system user
            # Set status field - this is required by the database schema
            call_history.status = "success" if response else "failed"

            # 使用FastAPI的异步数据库会话
            async with get_async_db_context() as session:
                session.add(call_history)
                # 会话会在上下文管理器中自动提交
        except Exception as e:
            logger.error(f"LLM写入调用日志失败: {str(e)}")

