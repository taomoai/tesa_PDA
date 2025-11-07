from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from enum import Enum


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(BaseModel):
    role: MessageRole
    content: str
    timestamp: Optional[datetime] = None


class ConversationCreateResponse(BaseModel):
    conversation_id: str


class MessageRequest(BaseModel):
    query: str
    stream: bool = True


class SSEEvent(BaseModel):
    event: str
    data: dict


class ToolExecution(BaseModel):
    tool_name: str
    input_query: str
    output: str
    execution_time: float


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ERROR = "error"


class ConversationSummary(BaseModel):
    conversation_id: str
    created_at: datetime
    message_count: int
    status: ConversationStatus