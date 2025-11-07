"""
Message database model
"""
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, Text, ForeignKey
from sqlalchemy.orm import relationship

from ..base import BaseModel


class Message(BaseModel):
    """
    消息表 - 存储对话中的消息记录
    """
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(36), nullable=False, index=True)
    
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    
    # 扩展字段，用于存储工具执行信息等
    extra_data = Column(Text, nullable=True)  # JSON格式的元数据
    def __repr__(self):
        return f"<Message(id={self.id}, conversation_id={self.conversation_id}, role={self.role})>"

    def to_dict(self):
        """
        转换为字典
        """
        custom_dict = {
            'id': self.id,
            'conversation_id': self.conversation_id,
            'role': self.role,
            'content': self.content,
            'extra_data': self.extra_data,
        }
        return super().to_dict(custom_dict)