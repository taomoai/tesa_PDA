from sqlalchemy import select

from fastapi_app.core.database import get_async_session
from fastapi_app.core.llm.model import LLMConfig, LLMProvider
from fastapi_app.core.llm.novita import Novita
from fastapi_app.core.llm.openrouter import OpenRouter
from fastapi_app.core.llm.azure_openai import AzureOpenAI
from fastapi_app.utils.exceptions import AIClientError

provider_map = {
    "novita": Novita,
    "openrouter": OpenRouter,
    "azure_openai": AzureOpenAI
}

async def get_llm_client(name: str):
    """
    异步获取LLM客户端
    
    Args:
        name: LLM配置名称
        
    Returns:
        Provider实例

    Raises:
        AIClientError: 获取LLM客户端失败
            - code=-1: LLM相关配置不存在
            - code=-2: 不支持的LLM供应商
    """
    async with get_async_session() as session:
        # 使用join联合查询，联合条件为provider_biz_name=biz_name
        stmt = select(LLMConfig, LLMProvider).join(
            LLMProvider, 
            LLMConfig.provider_biz_name == LLMProvider.biz_name
        ).filter(
            LLMConfig.is_delete == False, 
            LLMConfig.name == name
        )
        
        result = await session.execute(stmt)
        row = result.first()
        
        if not row:
            raise AIClientError(reason=f"{name} 的LLM相关配置不存在", code=-1, name=name)
        
        llm_config, provider_info = row
        
        provider_class = provider_map.get(provider_info.name)
        if not provider_class:
            raise AIClientError(reason=f"不支持的LLM供应商: {provider_info.name}", code=-2, name=name)
        
        return provider_class(**provider_info.to_dict(), llm_config=llm_config.to_dict())
