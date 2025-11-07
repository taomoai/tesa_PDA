"""
Database service for persistent conversation storage
"""
import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from ...core.database import get_async_session
from ...models.chat import Conversation, Message as DBMessage
from ...schemas.chat import Message, MessageRole, ConversationSummary, ConversationStatus

logger = logging.getLogger(__name__)


class ConversationDatabaseService:
    """
    对话数据库服务
    负责对话和消息的持久化存储
    """
    
    async def create_conversation(
        self,
        conversation_id: str,
        bot_id: str,
        tenant_id: Optional[str] = None,
        user_id: Optional[str] = None,
        title: Optional[str] = None
    ) -> Conversation:
        """
        创建新对话记录
        
        Args:
            conversation_id: 对话ID
            bot_id: 机器人ID
            tenant_id: 租户ID
            user_id: 用户ID  
            title: 对话标题
            
        Returns:
            Conversation: 创建的对话记录
        """
        async with get_async_session() as session:
            try:
                conversation = Conversation(
                    conversation_id=conversation_id,
                    bot_id=bot_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    title=title or f"对话 {conversation_id[:8]}",
                    status="active"
                )
                
                session.add(conversation)
                await session.commit()
                await session.refresh(conversation)
                
                logger.info(f"Created conversation in database: {conversation_id}")
                return conversation
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error creating conversation: {e}")
                raise
    
    async def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """
        获取对话记录
        
        Args:
            conversation_id: 对话ID
            
        Returns:
            Conversation | None: 对话记录或None
        """
        async with get_async_session() as session:
            try:
                result = await session.execute(
                    select(Conversation).where(Conversation.conversation_id == conversation_id)
                )
                return result.scalar_one_or_none()
                
            except Exception as e:
                logger.error(f"Error getting conversation: {e}")
                return None
    
    async def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[DBMessage]:
        """
        保存消息到数据库
        
        Args:
            conversation_id: 对话ID
            role: 消息角色
            content: 消息内容
            metadata: 元数据
            
        Returns:
            DBMessage | None: 保存的消息记录
        """
        async with get_async_session() as session:
            try:
                message = DBMessage(
                    conversation_id=conversation_id,
                    role=role,
                    content=content,
                    extra_data=json.dumps(metadata, ensure_ascii=False) if metadata else None
                )
                
                session.add(message)
                await session.commit()
                await session.refresh(message)
                
                logger.debug(f"Saved message to database: {message.id}")
                return message
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error saving message: {e}")
                return None
    
    async def get_conversation_messages(
        self,
        conversation_id: str,
        limit: int = 50,
        offset: int = 0
    ) -> List[Message]:
        """
        获取对话消息历史
        
        Args:
            conversation_id: 对话ID
            limit: 消息数量限制
            offset: 偏移量
            
        Returns:
            List[Message]: 消息列表
        """
        async with get_async_session() as session:
            try:
                result = await session.execute(
                    select(DBMessage)
                    .where(DBMessage.conversation_id == conversation_id)
                    .order_by(desc(DBMessage.created_at))
                    .limit(limit)
                    .offset(offset)
                )
                
                db_messages = result.scalars().all()
                
                # 转换为schema对象
                messages = []
                for db_msg in reversed(db_messages):  # 反转以获得时间顺序
                    try:
                        message = Message(
                            role=MessageRole(db_msg.role),
                            content=db_msg.content,
                            timestamp=db_msg.created_at
                        )
                        messages.append(message)
                    except Exception as e:
                        logger.warning(f"Error converting message {db_msg.id}: {e}")
                        continue
                
                return messages
                
            except Exception as e:
                logger.error(f"Error getting conversation messages: {e}")
                return []
    
    async def update_conversation_status(
        self,
        conversation_id: str,
        status: str
    ) -> bool:
        """
        更新对话状态
        
        Args:
            conversation_id: 对话ID
            status: 新状态
            
        Returns:
            bool: 是否成功更新
        """
        async with get_async_session() as session:
            try:
                result = await session.execute(
                    select(Conversation)
                    .where(Conversation.conversation_id == conversation_id)
                )
                conversation = result.scalar_one_or_none()
                
                if conversation:
                    conversation.status = status
                    conversation.updated_at = datetime.now()
                    await session.commit()
                    logger.info(f"Updated conversation status: {conversation_id} -> {status}")
                    return True
                
                return False
                
            except Exception as e:
                await session.rollback()
                logger.error(f"Error updating conversation status: {e}")
                return False
    
    async def conversation_exists(self, conversation_id: str) -> bool:
        """
        检查对话是否存在
        
        Args:
            conversation_id: 对话ID
            
        Returns:
            bool: 对话是否存在
        """
        async with get_async_session() as session:
            try:
                result = await session.execute(
                    select(Conversation.conversation_id)
                    .where(Conversation.conversation_id == conversation_id)
                )
                return result.scalar_one_or_none() is not None
                
            except Exception as e:
                logger.error(f"Error checking conversation existence: {e}")
                return False
    
    async def get_user_conversations(
        self,
        user_id: str,
        tenant_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[ConversationSummary]:
        """
        获取用户的对话列表
        
        Args:
            user_id: 用户ID
            tenant_id: 租户ID
            limit: 数量限制
            offset: 偏移量
            
        Returns:
            List[ConversationSummary]: 对话摘要列表
        """
        async with get_async_session() as session:
            try:
                query = select(Conversation).where(Conversation.user_id == user_id)
                
                if tenant_id:
                    query = query.where(Conversation.tenant_id == tenant_id)
                
                query = query.order_by(desc(Conversation.updated_at)).limit(limit).offset(offset)
                
                result = await session.execute(query)
                conversations = result.scalars().all()
                
                summaries = []
                for conv in conversations:
                    try:
                        # 获取消息数量
                        msg_count_result = await session.execute(
                            select(DBMessage).where(DBMessage.conversation_id == conv.conversation_id)
                        )
                        message_count = len(msg_count_result.scalars().all())
                        
                        summary = ConversationSummary(
                            conversation_id=conv.conversation_id,
                            created_at=conv.created_at,
                            message_count=message_count,
                            status=ConversationStatus(conv.status)
                        )
                        summaries.append(summary)
                        
                    except Exception as e:
                        logger.warning(f"Error creating summary for conversation {conv.conversation_id}: {e}")
                        continue
                
                return summaries
                
            except Exception as e:
                logger.error(f"Error getting user conversations: {e}")
                return []


# 全局实例
conversation_db_service = ConversationDatabaseService()