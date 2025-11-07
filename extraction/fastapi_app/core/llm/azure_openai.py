"""
Azure OpenAI 模型的具体实现，使用 LiteLLM 调用 Azure OpenAI API。
"""
from fastapi_app.core.llm.provider import Provider
import logging

class AzureOpenAI(Provider):
    """
    Azure OpenAI AI 模型实现。
    使用 LiteLLM 调用 Azure OpenAI API。
    """
    
    def __init__(self, **kwargs):
        # 从 llm_config 的 parameters 中提取 Azure 特定参数
        llm_config = kwargs.get('llm_config')
        logging.info(f"AzureOpenAI llm_config: {llm_config}")
        
        llm_parameters = llm_config.get('parameters') or {}
        logging.info(f"AzureOpenAI llm_parameters: {llm_parameters}")

        azure_api_key = llm_parameters.get('AZURE_API_KEY') or kwargs.get('api_key')
        azure_endpoint = llm_parameters.get('AZURE_ENDPOINT')   
        azure_api_version = llm_parameters.get('AZURE_API_VERSION')
        deployment_name = llm_parameters.get('deployment_name') 

        kwargs['api_key'] = azure_api_key
        kwargs['model_name'] = "azure/" + deployment_name
        kwargs['api_version'] = azure_api_version

        super().__init__(custom_llm_provider="azure", api_base=azure_endpoint, **kwargs)
