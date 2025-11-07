from contextlib import asynccontextmanager
from fastapi import FastAPI

from loguru import logger
from utils.load_env import load_env

# 导入新的FastAPI应用（现在使用fastapi_app包名，避免冲突）
from fastapi_app.main import create_fastapi_app

# 全局 Flask 应用实例（用于在 FastAPI 中访问 Flask 上下文）
_flask_app_instance = None


def create_hybrid_app() -> FastAPI:
    """
    创建混合应用：FastAPI作为主应用，Flask应用通过mount挂载
    """
    # 配置SQLAlchemy日志级别，避免过多SQL查询日志输出
    import logging
    import warnings
    logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.dialects').setLevel(logging.WARNING) 
    logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy.orm').setLevel(logging.WARNING)
    
    # 抑制apispec关于重复模式名称的警告
    warnings.filterwarnings('ignore', message='Multiple schemas resolved to the name.*', category=UserWarning)
        
    logger.info("="*60)
    logger.info("🚀 创建TaomoAI混合应用")
    logger.info("="*60)

    # 2. 创建FastAPI主应用（直接使用FastAPI业务应用作为主应用）
    logger.info("⚡ 创建FastAPI主应用...")
    main_app = create_fastapi_app()
    
    # 3. 更新主应用配置
    main_app.title = "TaomoAI Hybrid Server"
    main_app.description = "Flask到FastAPI渐进式迁移的混合应用"
    main_app.version = "2.0.0"
    
    logger.info("✅ 混合应用创建完成")
    logger.info("="*60)
    logger.info("📍 服务地址:")
    logger.info("   主应用:      http://localhost:3008")
    logger.info("   Flask API:   http://localhost:3008/api/*")
    logger.info("   FastAPI:     http://localhost:3008/* (主应用)")
    logger.info("   API文档:     http://localhost:3008/docs")
    logger.info("="*60)
    
    return main_app


# 延迟创建应用实例，避免重复初始化
_app_instance = None

def get_app():
    """获取应用实例，确保只创建一次"""
    global _app_instance
    if _app_instance is None:
        _app_instance = create_hybrid_app()
    return _app_instance

# 为uvicorn提供应用实例 - 只在非reload模式下预创建
def create_app():
    """应用工厂函数，用于uvicorn调用"""
    return get_app()

# 为了兼容直接导入的情况，提供懒加载的app变量
def __getattr__(name):
    """模块级别的懒加载，只在需要时创建应用实例"""
    if name == "app":
        return get_app()
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


if __name__ == "__main__":
    import uvicorn

    # 启动服务器 - 使用应用工厂模式避免重复初始化
    uvicorn.run(
        "main_hybrid:create_app",  # 使用工厂函数而不是预创建的实例
        host="0.0.0.0",
        port=3008,
        reload=False,
        reload_excludes=[
            "*.log", 
            "*.pyc", 
            "__pycache__/*",
            ".git/*",
            ".venv/*",
            "test_output/*",
            "*.db",
            "*.sqlite",
            ".pytest_cache/*"
        ],
        app_dir=".",
        log_config=None,  # 使用自定义日志配置
        factory=True  # 明确指示这是一个应用工厂函数
    )