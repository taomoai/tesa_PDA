"""
Novita 模型的具体实现，使用 OpenAI 客户端访问 Novita API。
"""
from fastapi_app.core.llm.provider import Provider

class Novita(Provider):
    """
    Novita AI 模型实现。
    使用 OpenAI 兼容的API接口，通过 Novita 访问多种大语言模型。
    """
    
    def __init__(self, **kwargs):
        super().__init__(custom_llm_provider="novita", api_base="https://api.novita.ai/v3/openai", **kwargs)

