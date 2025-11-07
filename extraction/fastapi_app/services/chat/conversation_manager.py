"""
In-memory conversation manager for temporary session state
"""
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from ...schemas.chat import Message, MessageRole

logger = logging.getLogger(__name__)


@dataclass
class ConversationSession:
    """
    内存中的对话会话状态
    """
    conversation_id: str
    bot_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_activity: datetime = field(default_factory=datetime.utcnow)
    messages: List[Message] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)  # 用于存储临时上下文信息
    
    def add_message(self, message: Message):
        """添加消息到会话"""
        self.messages.append(message)
        self.last_activity = datetime.utcnow()
    
    def get_recent_messages(self, limit: int = 10) -> List[Message]:
        """获取最近的消息"""
        return self.messages[-limit:] if len(self.messages) > limit else self.messages
    
    def is_expired(self, timeout_minutes: int = 30) -> bool:
        """检查会话是否已过期"""
        return datetime.utcnow() - self.last_activity > timedelta(minutes=timeout_minutes)


class InMemoryConversationManager:
    """
    内存中的对话管理器
    用于管理活跃对话的临时状态，不持久化
    """
    
    def __init__(self, session_timeout_minutes: int = 30):
        self._sessions: Dict[str, ConversationSession] = {}
        self.session_timeout_minutes = session_timeout_minutes
        logger.info("In-memory conversation manager initialized")
    
    def create_session(self, conversation_id: str, bot_id: str) -> ConversationSession:
        """
        创建新的对话会话
        
        Args:
            conversation_id: 对话ID
            bot_id: 机器人ID
            
        Returns:
            ConversationSession: 新创建的会话
        """
        session = ConversationSession(
            conversation_id=conversation_id,
            bot_id=bot_id
        )
        self._sessions[conversation_id] = session
        logger.info(f"Created conversation session: {conversation_id}")
        return session
    
    def get_session(self, conversation_id: str) -> Optional[ConversationSession]:
        """
        获取对话会话
        
        Args:
            conversation_id: 对话ID
            
        Returns:
            ConversationSession | None: 会话对象或None
        """
        session = self._sessions.get(conversation_id)
        if session and session.is_expired(self.session_timeout_minutes):
            # 清理过期会话
            self.remove_session(conversation_id)
            return None
        return session
    
    def add_message(self, conversation_id: str, message: Message) -> bool:
        """
        向会话添加消息
        
        Args:
            conversation_id: 对话ID
            message: 消息对象
            
        Returns:
            bool: 是否成功添加
        """
        session = self.get_session(conversation_id)
        if session:
            session.add_message(message)
            return True
        return False
    
    def get_conversation_history(
        self, 
        conversation_id: str, 
        limit: int = 10
    ) -> List[Message]:
        """
        获取对话历史
        
        Args:
            conversation_id: 对话ID
            limit: 消息数量限制
            
        Returns:
            List[Message]: 消息列表
        """
        session = self.get_session(conversation_id)
        if session:
            return session.get_recent_messages(limit)
        return []
    
    def update_context(
        self, 
        conversation_id: str, 
        key: str, 
        value: Any
    ) -> bool:
        """
        更新会话上下文
        
        Args:
            conversation_id: 对话ID
            key: 上下文键
            value: 上下文值
            
        Returns:
            bool: 是否成功更新
        """
        session = self.get_session(conversation_id)
        if session:
            session.context[key] = value
            session.last_activity = datetime.utcnow()
            return True
        return False
    
    def get_context(self, conversation_id: str, key: str) -> Any:
        """
        获取会话上下文
        
        Args:
            conversation_id: 对话ID
            key: 上下文键
            
        Returns:
            Any: 上下文值
        """
        session = self.get_session(conversation_id)
        if session:
            return session.context.get(key)
        return None
    
    def remove_session(self, conversation_id: str) -> bool:
        """
        移除会话
        
        Args:
            conversation_id: 对话ID
            
        Returns:
            bool: 是否成功移除
        """
        if conversation_id in self._sessions:
            del self._sessions[conversation_id]
            logger.info(f"Removed conversation session: {conversation_id}")
            return True
        return False
    
    def session_exists(self, conversation_id: str) -> bool:
        """
        检查会话是否存在
        
        Args:
            conversation_id: 对话ID
            
        Returns:
            bool: 会话是否存在
        """
        return self.get_session(conversation_id) is not None
    
    def cleanup_expired_sessions(self) -> int:
        """
        清理过期的会话
        
        Returns:
            int: 清理的会话数量
        """
        expired_sessions = []
        for conversation_id, session in self._sessions.items():
            if session.is_expired(self.session_timeout_minutes):
                expired_sessions.append(conversation_id)
        
        for conversation_id in expired_sessions:
            self.remove_session(conversation_id)
        
        if expired_sessions:
            logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")
        
        return len(expired_sessions)
    
    def get_active_sessions_count(self) -> int:
        """
        获取活跃会话数量
        
        Returns:
            int: 活跃会话数量
        """
        return len(self._sessions)
    
    def get_session_info(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话信息
        
        Args:
            conversation_id: 对话ID
            
        Returns:
            Dict[str, Any] | None: 会话信息字典
        """
        session = self.get_session(conversation_id)
        if session:
            return {
                "conversation_id": session.conversation_id,
                "bot_id": session.bot_id,
                "created_at": session.created_at.isoformat(),
                "last_activity": session.last_activity.isoformat(),
                "message_count": len(session.messages),
                "context_keys": list(session.context.keys())
            }
        return None


# 全局实例
conversation_manager = InMemoryConversationManager()