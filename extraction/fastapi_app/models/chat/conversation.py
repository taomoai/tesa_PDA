"""
Conversation database model
"""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, Text, Boolean
from sqlalchemy.orm import relationship

from ..base import BaseModel


class Conversation(BaseModel):
    """
    对话表 - 存储对话的基本信息
    """
    __tablename__ = "chat_conversations"

    conversation_id = Column(String(36), primary_key=True, index=True)
    bot_id = Column(String(100), nullable=False, index=True)
    tenant_id = Column(String(100), nullable=True, index=True)
    user_id = Column(String(100), nullable=True, index=True)
    
    title = Column(String(200), nullable=True)  # 对话标题
    status = Column(String(20), default="active")  # active, completed, error
        
    def __repr__(self):
        return f"<Conversation(id={self.conversation_id}, bot_id={self.bot_id}, status={self.status})>"

    def to_dict(self):
        custom_dict = {
            'id': self.conversation_id,
            'bot_id': self.bot_id,
            'status': self.status,
        }
        return super().to_dict(custom_dict)