from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class CoreIdentity(BaseModel):
    Botname: str
    Active: bool
    Version: str
    DisplayName: str
    Description: str


class CoreLLMConfig(BaseModel):
    model_name: str
    system_prompt: str


class IntentRecognition(BaseModel):
    model_name: str
    enable_deep_thinking: bool = False
    prompt_template: str


class KnowledgeBaseModule(BaseModel):
    Intend_Search_KB: bool = False
    KB_List: List[str] = []
    Prompt_template_search_raw_rewrite_query: str = ""
    Prompt_template_search_qa_rewrite_query: str = ""
    Prompt_template_search_raw_result: str = ""
    Prompt_template_search_qa_result: str = ""


class KnowledgeGraphModule(BaseModel):
    Intend_Search_KG: bool = False
    KG_List: List[str] = []
    prompt_template_to_search: str = ""
    prompt_template_seach_result: str = ""


class Tool(BaseModel):
    tool_name: str
    description: str
    api_endpoint: str
    parameters: Dict[str, Any] = {}


class FunctionCallingModule(BaseModel):
    Tools_List: List[Tool] = []


class OrchestrationLogic(BaseModel):
    enable_react: bool = True
    react_max_iterations: int = 5
    react_thought_prompt: str = ""
    Orchestration_Strategy_Prompt: str


class AnswerSynthesis(BaseModel):
    prompt_template_with_tools: str
    prompt_template_direct_conversation: str
    format_prompt: str = ""


class ConversationMemory(BaseModel):
    Memory_Type: str = "sliding_window"
    Memory_Scope: int = 10


class SafetyAndFallback(BaseModel):
    Fallback_Response_Prompt: str
    Guardrail_Prompt: str = ""


class Metadata(BaseModel):
    Tenat_id: str
    CreatedAt: datetime
    UpdatedAt: datetime
    Owner_ID: str


class BotConfigSchema(BaseModel):
    Bot_ID: str
    CoreIdentity: CoreIdentity
    CoreLLMConfig: CoreLLMConfig
    IntentRecognition: IntentRecognition
    KnowledgeBaseModule: KnowledgeBaseModule
    KnowledgeGraphModule: KnowledgeGraphModule
    FunctionCallingModule: FunctionCallingModule
    OrchestrationLogic: OrchestrationLogic
    AnswerSynthesis: AnswerSynthesis
    ConversationMemory: ConversationMemory
    SafetyAndFallback: SafetyAndFallback
    Metadata: Metadata