"""
FastAPI 数据库模型
定义数据库表结构
"""

from .base import BaseModel, TimestampMixin
from .chat import Conversation, Message
from .coating import CoatingRunningParams, CoatingDataboxValues

__all__ = [
    "BaseModel", "TimestampMixin",
    "Conversation", "Message",
    "CoatingRunningParams", "CoatingDataboxValues",
]