"""
FastAPI 配置管理
"""
import os
import json
from pathlib import Path
from typing import Dict, Any, Optional
from functools import lru_cache
from pydantic_settings import BaseSettings
from loguru import logger
from fastapi import FastAPI


class DatabaseSettings(BaseSettings):
    """数据库配置"""
    host: str
    port: int
    database: str
    user: str
    password: str
    pool_size: int
    max_overflow: int
    echo_sql: bool


class CeleryRedisSettings(BaseSettings):
    """Celery Redis配置"""
    url: str | None
    host: str
    port: int
    password: str
    db: int
    use_ssl: bool


class Settings(BaseSettings):
    """应用配置"""
    
    # 应用基础配置
    app_name: str = "TaomoAI FastAPI Server"
    app_version: str = "2.0.0"
    debug: bool = False
    
    # 服务器配置
    host: str = "0.0.0.0"
    port: int = 3008
    
    # 数据库配置 - 先设为可选，在get_settings中动态创建
    database_url: Optional[str] = None
    database: Optional[DatabaseSettings] = None
    
    # 数据来源Tag的 code 配置
    internal_data: str = "INTERNAL_DATA"
    external_data: str = "EXTERNAL_DATA"

    # 认证配置
    secret_key: Optional[str] = None
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # 日志配置
    log_level: str = "INFO"

    # Elasticsearch 配置
    es_enabled: bool = True  # ES日志功能开关
    es_hosts: str
    es_username: Optional[str] = None
    es_password: Optional[str] = None
    es_timeout: int = 10
    es_max_retries: int = 3

    # Celery Redis 配置
    celery_broker_settings: CeleryRedisSettings
    celery_result_backend_settings: CeleryRedisSettings
    
    class Config:
        env_file = ".env"
        # Allow extra fields from configuration file
        extra = "allow"


def load_project_config() -> Dict[str, Any]:
    """
    加载项目配置文件（复用Flask的配置）
    """
    env = os.getenv('ENV', 'production')
    config_path = Path(__file__).parent.parent.parent / "configs" / f"config_{env}.json"
    
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def set_base_config(app: FastAPI):
    """加载基本配置并设置到 FastAPI 的全局参数 app.state.config 上"""
    assert isinstance(app, FastAPI), "'app' must be an instance of FastAPI"
    base_config_path = Path(__file__).parent.parent.parent / "configs" / "config_base.json"
    config = json.loads(base_config_path.read_text(encoding='utf-8'))
    app.state.config = config

def load_celery_config():
    """加载celery的redis配置，返回：broder和result backend的settings"""
    # 从环境变量中获取Redis配置信息
    # 强烈推荐使用环境变量来配置，以保证安全性和可移植性。
    REDIS_HOST = os.environ.get('REDIS_HOST', 'localhost')
    REDIS_PORT = os.environ.get('REDIS_PORT', '6379')
    REDIS_PASSWORD = os.environ.get('REDIS_PASSWORD', '')  # Redis密码
    REDIS_DB = os.environ.get('REDIS_DB', '0')  # Redis数据库编号
    REDIS_SSL = True if os.environ.get('REDIS_SSL', 'false').lower() == 'true' else False

    # 从环境变量中获取消息代理（Broker）的地址
    # 这是Celery用于发送和接收任务消息的中间件，如Redis或RabbitMQ
    # 如果设置了CELERY_BROKER_URL环境变量，直接使用；否则构建Redis URL
    BROKER_URL = os.environ.get('CELERY_BROKER_URL')
    broker_settings = CeleryRedisSettings(
        url=BROKER_URL,
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        db=REDIS_DB,
        use_ssl=REDIS_SSL
    )

    # 从环境变量中获取结果后端（Result Backend）的地址
    # 结果后端用于存储任务的执行结果和状态
    # 通常也使用Redis或RabbitMQ，也可以与Broker使用同一个地址
    # 可以为结果后端单独配置Redis实例
    RESULT_BACKEND_HOST = os.environ.get('RESULT_BACKEND_HOST', REDIS_HOST)
    RESULT_BACKEND_PORT = os.environ.get('RESULT_BACKEND_PORT', REDIS_PORT)
    RESULT_BACKEND_PASSWORD = os.environ.get('RESULT_BACKEND_PASSWORD', REDIS_PASSWORD)
    RESULT_BACKEND_DB = os.environ.get('RESULT_BACKEND_DB', REDIS_DB)
    RESULT_BACKEND_SSL = True if os.environ.get('RESULT_BACKEND_SSL', 'false').lower() == 'true' else False
    RESULT_BACKEND_URL = os.environ.get('CELERY_RESULT_BACKEND')

    result_backend_settings = CeleryRedisSettings(
        url=RESULT_BACKEND_URL,
        host=RESULT_BACKEND_HOST,
        port=RESULT_BACKEND_PORT,
        password=RESULT_BACKEND_PASSWORD,
        db=RESULT_BACKEND_DB,
        use_ssl=RESULT_BACKEND_SSL
    )
    return broker_settings, result_backend_settings


@lru_cache()
def get_settings() -> Settings:
    """
    获取应用配置（带缓存）
    优先从环境变量获取，配置文件作为备用
    """
    # 尝试加载项目配置作为备用
    project_config = None
    try:
        project_config = load_project_config()
        logger.info("Successfully loaded project configuration file")
    except Exception as e:
        logger.warning(f"Failed to load project config file: {e}, using environment variables only")
    
    # 创建数据库配置对象
    database_settings = None
    database_url = None

    # 优先从环境变量获取数据库配置
    if all([os.getenv('DB_HOST'), os.getenv('DB_PORT'), os.getenv('DB_DATABASE'), os.getenv('DB_USER'), os.getenv('DB_PASSWORD')]):
        # 获取密码并处理可能的引号问题
        raw_password = os.getenv('DB_PASSWORD')
        # 如果密码被双引号包围，去掉引号
        if raw_password and raw_password.startswith('"') and raw_password.endswith('"'):
            clean_password = raw_password[1:-1]
            logger.info("[FastAPI Config] Removed surrounding quotes from password")
        else:
            clean_password = raw_password

        database_settings = DatabaseSettings(
                host=os.getenv('DB_HOST'),
                port=int(os.getenv('DB_PORT')),
                database=os.getenv('DB_DATABASE'),
                user=os.getenv('DB_USER'),
                password=clean_password,
                pool_size=int(os.getenv('DB_POOL_SIZE', '5')),
                max_overflow=int(os.getenv('DB_MAX_OVERFLOW', '10')),
                echo_sql=os.getenv('DB_ECHO_SQL', 'false').lower() in ('true', '1', 'yes')
            )
        logger.info("Using database configuration from environment variables")
        logger.info(f"Database config: host={database_settings.host}, database={database_settings.database}, user={database_settings.user}")
        starts_with_quote = raw_password.startswith('"') if raw_password else False
        logger.info(f"Password length: {len(clean_password) if clean_password else 0}, starts with quote: {starts_with_quote}")

    # 如果环境变量不完整，从配置文件获取数据库配置
    elif project_config and 'database_pg' in project_config:
        db_config = project_config['database_pg']
        database_settings = DatabaseSettings(
            host=db_config['host'],
            port=db_config['port'],
            database=db_config['database'],
            user=db_config['user'],
            password=db_config['password'],
            pool_size=db_config.get('pool_size', 5),
            max_overflow=db_config.get('max_overflow', 10),
            echo_sql=db_config.get('echo_sql', False)
        )
        logger.info("Using database configuration from project config file")
        logger.info(f"Database config: host={database_settings.host}, database={database_settings.database}, user={database_settings.user}")
        logger.info(f"Password length: {len(database_settings.password) if database_settings.password else 0}")

    else:
        logger.error("No complete database configuration found in environment variables or config file")
        raise RuntimeError("Missing database configuration")
    
    # 构建数据库URL
    if database_settings:
        database_url = f"postgresql://{database_settings.user}:{database_settings.password}@{database_settings.host}:{database_settings.port}/{database_settings.database}"
    
    # 从环境变量或配置文件获取应用配置
    debug = os.getenv('DEBUG')
    if debug is None and project_config:
        debug = project_config.get('app', {}).get('debug', False)
    
    log_level = os.getenv('LOG_LEVEL')
    if log_level is None and project_config:
        log_level = project_config.get('logging', {}).get('level', 'INFO')

    # ES配置
    es_enabled_str = os.getenv('ES_ENABLED', 'true').lower()
    es_enabled = es_enabled_str in ('true', '1', 'yes', 'on')
    es_hosts = os.getenv('ES_HOSTS', 'http://localhost:9200')
    es_username = os.getenv('ES_USERNAME')
    es_password = os.getenv('ES_PASSWORD')
    es_timeout = int(os.getenv('ES_TIMEOUT', '10'))
    es_max_retries = int(os.getenv('ES_MAX_RETRIES', '3'))
    
    logger.info(f"ES配置: {es_enabled}, {es_hosts}, {es_username}, {es_password}, {es_timeout}, {es_max_retries}")  

    broker_settings, result_backend_settings = load_celery_config()

    return Settings(
        debug=debug,
        database_url=database_url,
        database=database_settings,
        log_level=log_level,
        es_enabled=es_enabled,
        es_hosts=es_hosts,
        es_username=es_username,
        es_password=es_password,
        es_timeout=es_timeout,
        es_max_retries=es_max_retries,
        celery_broker_settings=broker_settings,
        celery_result_backend_settings=result_backend_settings,
    )