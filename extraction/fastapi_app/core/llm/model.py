from datetime import datetime
from sqlalchemy import BIGINT, JSON, Column, Text, DateTime, Boolean, Integer
from fastapi_app.core.database import Base

class LLMProvider(Base):
    """供应商模型"""
    __tablename__ = 'llm_providers'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False, comment='供应商名称')
    biz_name = Column(Text, nullable=False, comment='业务名称')
    api_key = Column(Text, nullable=True, comment='API密钥')
    model_name = Column(Text, nullable=False, comment='模型名称')
    parameters = Column(JSON, nullable=True, comment='模型参数')
    description = Column(Text, nullable=True, comment='描述')
    status = Column(Text, nullable=False, comment='状态')
    is_delete = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    def to_dict(self):
        return {
            "name": self.name,
            "biz_name": self.biz_name,
            "api_key": self.api_key,
            "model_name": self.model_name,
            "parameters": self.parameters,
            "description": self.description
        }
    

class LLMConfig(Base):
    """AI配置模型"""
    __tablename__ = 'llm_configs'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False, comment='实例名称')
    parameters = Column(JSON, nullable=True, comment='模型参数')
    provider_biz_name = Column(Text, nullable=False, comment='供应商业务名称')
    description = Column(Text, nullable=True, comment='描述')
    is_delete = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    def to_dict(self):
        return {
            "name": self.name,
            "provider_biz_name": self.provider_biz_name,
            "description": self.description,
            "parameters": self.parameters   
        }


class LLMCallHistory(Base):
    """AI调用历史"""
    __tablename__ = 'llm_call_histories'
    
    id = Column(BIGINT, primary_key=True, autoincrement=False)
    provider = Column(Text, nullable=False, comment='供应商')
    model_name = Column(Text, nullable=False, comment='模型名称')
    params = Column(JSON, nullable=False, comment='参数')
    response = Column(JSON, nullable=False, comment='响应')
    status = Column(Text, nullable=False, comment='状态')
    created_by = Column(BIGINT, nullable=True, comment='创建者')
    status = Column(Text, nullable=False, comment='调用状态')
    created_at = Column(DateTime, default=datetime.now, nullable=False)