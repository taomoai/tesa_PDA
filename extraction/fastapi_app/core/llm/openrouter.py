"""
OpenRouter 模型的具体实现，使用 litellm 访问 OpenRouter API。
"""

import os
from fastapi_app.core.llm.provider import Provider

class OpenRouter(Provider):
    """
    OpenRouter AI 模型实现。
    使用 OpenAI 兼容的API接口，通过 OpenRouter 访问多种大语言模型。
    """
    
    def __init__(self, **kwargs):
        super().__init__(custom_llm_provider="openrouter", api_base="https://openrouter.ai/api/v1", **kwargs)
    