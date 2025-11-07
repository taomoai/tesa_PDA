"""
数据库连接配置工具函数
提供统一的数据库连接参数构建逻辑，供主服务和binlog服务共享使用
"""
from typing import Dict, Any
from loguru import logger
from fastapi_app.core.config import DatabaseSettings


def is_azure_postgresql(host: str) -> bool:
    """
    检查是否为Azure PostgreSQL
    
    Args:
        host: 数据库主机地址
        
    Returns:
        bool: 是否为Azure PostgreSQL
    """
    azure_domains = [
        'database.chinacloudapi.cn',  # Azure China
        'database.azure.com',         # Azure Global
        'postgres.database.azure.com' # Azure PostgreSQL specific
    ]
    
    return any(domain in host for domain in azure_domains)


def build_asyncpg_connection_params(db_config: DatabaseSettings, application_name: str = None) -> Dict[str, Any]:
    """
    构建asyncpg连接参数，统一处理SSL等配置

    Args:
        db_config: 数据库配置对象
        application_name: 应用名称，用于数据库监控

    Returns:
        Dict[str, Any]: asyncpg连接参数字典
    """
    # 基础连接参数
    connect_kwargs = {
        'host': db_config.host,
        'port': db_config.port,
        'user': db_config.user,
        'password': db_config.password,
        'database': db_config.database,
    }

    # 添加服务器设置
    server_settings = {}
    if application_name:
        server_settings['application_name'] = application_name

    if server_settings:
        connect_kwargs['server_settings'] = server_settings

    # 检查是否为Azure PostgreSQL
    if is_azure_postgresql(db_config.host):
        connect_kwargs['ssl'] = 'require'
        logger.info(f"[DB Connection] Detected Azure PostgreSQL ({db_config.host}), enabling SSL connection")

    # 记录连接信息（隐藏密码）
    safe_params = dict(connect_kwargs)
    safe_params['password'] = '***'
    logger.info(f"[DB Connection] Connection parameters: {safe_params}")

    return connect_kwargs


def build_sqlalchemy_connection_args(db_config: DatabaseSettings, application_name: str = None) -> Dict[str, Any]:
    """
    构建SQLAlchemy连接参数，统一处理SSL等配置
    
    Args:
        db_config: 数据库配置对象
        application_name: 应用名称，用于数据库监控
        
    Returns:
        Dict[str, Any]: SQLAlchemy连接参数字典
    """
    connect_args = {}
    
    # 添加服务器设置
    server_settings = {}
    if application_name:
        server_settings['application_name'] = application_name
    
    if server_settings:
        connect_args['server_settings'] = server_settings
    
    # 检查是否为Azure PostgreSQL
    if is_azure_postgresql(db_config.host):
        connect_args['ssl'] = 'require'
        logger.info(f"[DB Connection] Detected Azure PostgreSQL ({db_config.host}), enabling SSL for SQLAlchemy")
    
    return connect_args


def build_database_url(db_config: DatabaseSettings, driver: str = 'postgresql') -> str:
    """
    构建数据库连接URL
    
    Args:
        db_config: 数据库配置对象
        driver: 数据库驱动名称，如 'postgresql' 或 'postgresql+asyncpg'
        
    Returns:
        str: 数据库连接URL
    """
    base_url = f"{driver}://{db_config.user}:{db_config.password}@{db_config.host}:{db_config.port}/{db_config.database}"
    
    # 如果是Azure PostgreSQL，添加SSL参数到URL
    if is_azure_postgresql(db_config.host):
        base_url += "?ssl=require"
    
    return base_url


def get_safe_database_url(db_config: DatabaseSettings, driver: str = 'postgresql') -> str:
    """
    获取安全的数据库连接URL（隐藏密码）
    
    Args:
        db_config: 数据库配置对象
        driver: 数据库驱动名称
        
    Returns:
        str: 隐藏密码的数据库连接URL
    """
    safe_url = f"{driver}://{db_config.user}:***@{db_config.host}:{db_config.port}/{db_config.database}"
    
    # 如果是Azure PostgreSQL，添加SSL参数
    if is_azure_postgresql(db_config.host):
        safe_url += "?ssl=require"
    
    return safe_url
