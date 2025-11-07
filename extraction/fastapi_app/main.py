"""
FastAPI 主应用
负责创建FastAPI应用实例和路由注册
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
import asyncio
import logging
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from fastapi_app.core.config import get_settings, set_base_config
from fastapi_app.api.v1.router import router as fastapi_router  # 在database前导入，保证在创建表结构前所有路由用到的表都先加载
from fastapi_app.modules import all_routers  # 在database前导入，保证在创建表结构前所有路由用到的表都先加载
from fastapi_app.core.database import init_async_database, close_async_database, init_database, sync_database_model
from fastapi_app.core.connection_monitor import start_connection_monitoring, stop_connection_monitoring, cleanup_all_database_connections

from fastapi_app.middlewares.catch import catch_exception
from fastapi_app.services.master_data.startup_fixes import run_all_startup_fixes

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理
    启动时初始化异步数据库连接，关闭时清理资源
    """
    # 启动时的初始化
    logger.info("[FastAPI] Application starting up...")

    init_database()  # 初始化同步数据库连接，同时支持两种连接方式
    # 初始化异步数据库连接（内部已处理异常，不会终止应用）
    await init_async_database()
    logger.info("[FastAPI] Async database initialization completed")
    
    # 创建数据库表
    try:
        # 创建所有表，并检查全表，缺失表字段则添加。
        # 注意：只会对代码定义但不存在的字段进行创建，不会对已有字段进行修改。若要修改字段，为保证精确修改，仍需要单独处理。
        await sync_database_model()
    except Exception as e:
        logger.error(f"[FastAPI] Failed to create database tables: {e}")

    try:
        run_all_startup_fixes()
    except Exception as e:
        logger.error(f"[FastAPI] Failed to run startup fixes: {e}")

    # 设置基本配置
    set_base_config(app)

    # 启动数据库连接监控
    try:
        start_connection_monitoring()
        logger.info("[FastAPI] Database connection monitoring started")
    except Exception as e:
        logger.error(f"[FastAPI] Failed to start connection monitoring: {e}")

    yield

    # 关闭时的清理
    logger.info("[FastAPI] Application shutting down...")
    # 关闭数据库连接（添加超时控制）
    try:
        # 设置 3 秒超时
        await asyncio.wait_for(close_async_database(), timeout=3.0)
        logger.info("[FastAPI] Async database connections closed")
    except asyncio.TimeoutError:
        logger.warning("[FastAPI] Timeout closing async database (3s), forcing shutdown")
        # 强制关闭数据库连接
        from fastapi_app.core.database import async_engine
        if async_engine:
            try:
                # 直接 dispose，不等待
                await asyncio.wait_for(async_engine.dispose(), timeout=1.0)
            except:
                pass
    except asyncio.CancelledError:
        logger.debug("[FastAPI] Database close cancelled (normal during shutdown)")
    except Exception as e:
        logger.error(f"[FastAPI] Error closing async database: {e}")

    # 停止数据库连接监控并清理连接
    try:
        stop_connection_monitoring()
        logger.info("[FastAPI] Database connection monitoring stopped")

        # 清理所有数据库连接（同步操作，不需要超时）
        cleanup_all_database_connections()
        logger.info("[FastAPI] All database connections cleaned up")
    except Exception as e:
        logger.error(f"[FastAPI] Error cleaning up database connections: {e}")

def create_fastapi_app() -> FastAPI:
    """
    创建FastAPI应用实例
    注意：在混合模式下，生命周期将由主应用管理
    """
    settings = get_settings()

    # 配置Azure SDK日志级别，减少冗余日志输出
    azure_loggers = [
        'azure.storage.blob',
        'azure.core.pipeline.policies.http_logging_policy',
        'azure.storage.common.storageclient',
        'azure.storage.blob._blob_service_client',
        'azure.storage.blob._container_client',
        'azure.storage.blob._blob_client',
        'azure.core.pipeline.transport',
        'azure.core.pipeline.policies',
        'azure.identity',
        'urllib3.connectionpool'
    ]

    for logger_name in azure_loggers:
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    # 创建FastAPI应用，使用自己的生命周期管理
    app = FastAPI(
        title="TaomoAI Server API v2", 
        description="基于FastAPI的新版本API服务，支持异步PostgreSQL连接",
        version="2.0.0",
        docs_url="/docs",  # 作为主应用时的文档路径
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        debug=settings.debug,
        lifespan=lifespan  # 使用自己的生命周期管理
    )

    # 设置CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应该限制具体域名
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    catch_exception(app)  # 添加全局异常处理

    # 注册API路由
    app.include_router(fastapi_router, prefix="/api_v2")

    return app