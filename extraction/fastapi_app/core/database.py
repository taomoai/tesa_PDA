"""
FastAPI 数据库连接管理
支持同步和异步数据库连接
"""
import sys
import asyncio
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from typing import Generator, AsyncGenerator, Optional, Callable, TypeVar, Any, Type
from sqlalchemy import create_engine, Engine, inspect, text, DefaultClause
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from sqlalchemy.orm import DeclarativeBase
from fastapi import FastAPI
from loguru import logger
from fastapi_app.core.config import get_settings

# SQLAlchemy Base类
Base: type[DeclarativeBase] = declarative_base()

# 全局变量
engine: Engine | None = None
SessionLocal: Callable[[], Session] | None = None

# 异步数据库支持
async_engine: AsyncEngine | None = None
AsyncSessionLocal: Callable[[], AsyncSession] | None = None

# 通用返回值类型
R = TypeVar("R")

def init_database(is_celery_worker=False) -> None:
    """
    初始化同步数据库连接

    Args:
        is_celery_worker: 是否为Celery worker进程，如果是则使用专用的连接池配置
    """
    global engine, SessionLocal

    settings = get_settings()
    db_config = settings.database

    # 配置SQLAlchemy日志级别
    import logging
    if not db_config.echo_sql:
        logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
        logging.getLogger('sqlalchemy.dialects').setLevel(logging.WARNING)
        logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)

    # 根据是否为 Celery worker 使用不同的连接池配置
    if is_celery_worker:
        # Celery worker 专用配置：更小的连接池，更短的回收时间
        pool_size = 2  # 每个worker只需要2个连接
        max_overflow = 3  # 最多3个额外连接
        pool_recycle = 300  # 5分钟回收
        pool_timeout = 10  # 10秒超时
        app_name = "fastapi_celery_worker_sync"
        logger.info(f"[FastAPI Celery Worker] Using optimized sync connection pool - Size: {pool_size}, Max overflow: {max_overflow}")
    else:
        # 主应用配置
        pool_size = min(db_config.pool_size, 5)  # 限制基础连接池大小为5
        max_overflow = min(db_config.max_overflow, 10)  # 限制溢出连接数为10
        pool_recycle = 1800   # 30分钟后回收连接
        pool_timeout = 20     # 获取连接的超时时间（秒）
        app_name = "fastapi_app_sync"
        logger.info(f"[FastAPI App] Using standard sync connection pool - Size: {pool_size}, Max overflow: {max_overflow}")

    # 创建数据库引擎 - 优化连接池配置以减少连接泄漏
    engine = create_engine(
        settings.database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,  # 连接前检查连接是否有效
        pool_recycle=pool_recycle,
        pool_timeout=pool_timeout,
        pool_reset_on_return='rollback' if is_celery_worker else 'commit',  # Celery worker使用rollback更安全
        echo=db_config.echo_sql,
        # 连接参数
        connect_args={
            "connect_timeout": 10,  # 连接超时
            "application_name": app_name  # 应用名称，便于数据库监控
        }
    )
    
    # 创建会话工厂
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    try:
        # 测试数据库连接
        with engine.connect() as conn:
            logger.info(f"[FastAPI] Sync database connection established: {db_config.host}:{db_config.port}/{db_config.database}")

            # 记录连接池状态
            pool = engine.pool
            logger.info(f"[FastAPI] Sync connection pool status - Size: {pool.size()}, Checked out: {pool.checkedout()}, Overflow: {pool.overflow()}")

    except Exception as e:
        logger.error(f"[FastAPI] Sync database connection failed: {e}")
        raise


async def init_async_database(is_celery_worker=False) -> None:
    """
    初始化异步数据库连接

    Args:
        is_celery_worker: 是否为Celery worker进程，如果是则使用专用的连接池配置
    """
    global async_engine, AsyncSessionLocal

    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from sqlalchemy import text
    except ImportError:
        logger.warning("[FastAPI] Async database support not available (install asyncpg for PostgreSQL async support)")
        return

    settings = get_settings()
    db_config = settings.database

    # 检查数据库配置是否存在
    if not db_config:
        logger.error("[FastAPI] Database configuration not found")
        logger.error("[FastAPI] Please check your environment variables or config file")
        return

    # 根据是否为 Celery worker 使用不同的连接池配置
    if is_celery_worker:
        # Celery worker 专用配置：更小的连接池，更短的回收时间
        pool_size = 2  # 每个worker只需要2个连接
        max_overflow = 3  # 最多3个额外连接
        pool_recycle = 300  # 5分钟回收
        pool_timeout = 10  # 10秒超时
        app_name = "fastapi_celery_worker_async"
        logger.info(f"[FastAPI Celery Worker] Using optimized async connection pool - Size: {pool_size}, Max overflow: {max_overflow}")
    else:
        # 主应用配置
        pool_size = min(db_config.pool_size, 5)  # 限制基础连接池大小为5
        max_overflow = min(db_config.max_overflow, 10)  # 限制溢出连接数为10
        pool_recycle = 1800   # 30分钟后回收连接
        pool_timeout = 20     # 获取连接的超时时间（秒）
        app_name = "fastapi_app_async"
        logger.info(f"[FastAPI App] Using standard async connection pool - Size: {pool_size}, Max overflow: {max_overflow}")

    logger.info(f"[FastAPI] Database config - Host: {db_config.host}, Port: {db_config.port}, DB: {db_config.database}, User: {db_config.user}")

    # 构建异步数据库URL
    async_url = f"postgresql+asyncpg://{db_config.user}:{db_config.password}@{db_config.host}:{db_config.port}/{db_config.database}"

    # 记录连接信息（隐藏密码）
    safe_url = f"postgresql+asyncpg://{db_config.user}:***@{db_config.host}:{db_config.port}/{db_config.database}"
    logger.info(f"[FastAPI] Attempting async database connection: {safe_url}")

    try:
        # 创建异步数据库引擎 - 优化连接池配置以减少连接泄漏
        async_engine = create_async_engine(
            async_url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,  # 连接前检查连接是否有效
            pool_recycle=pool_recycle,
            pool_timeout=pool_timeout,
            pool_reset_on_return='rollback' if is_celery_worker else 'commit',  # Celery worker使用rollback更安全
            echo=db_config.echo_sql,
            future=True,
            # 连接参数
            connect_args={
                "server_settings": {
                    "application_name": app_name  # 应用名称，便于数据库监控
                }
            }
        )
        
        # 创建异步会话工厂
        AsyncSessionLocal = async_sessionmaker(
            async_engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        # 测试异步数据库连接
        async with async_engine.begin() as conn:
            result = await conn.execute(text("SELECT 1"))
            row = result.fetchone()  # 获取查询结果，不需要await
            logger.info(f"[FastAPI] Async database connection established: {db_config.host}:{db_config.port}/{db_config.database}")
            logger.info(f"[FastAPI] Connection test result: {row}")

            # 记录异步连接池状态
            pool = async_engine.pool
            logger.info(f"[FastAPI] Async connection pool status - Size: {pool.size()}, Checked out: {pool.checkedout()}, Overflow: {pool.overflow()}")

    except Exception as e:
        logger.error(f"[FastAPI] Async database connection failed: {e}")
        logger.error(f"[FastAPI] Connection URL: {safe_url}")
        # 重置全局变量
        async_engine = None
        AsyncSessionLocal = None
        # 不再抛出异常，允许应用继续启动，但记录错误
        logger.warning("[FastAPI] Application will continue without async database support")


async def close_async_database(timeout: float = 3.0) -> None:
    """
    关闭异步数据库连接

    Args:
        timeout: 关闭超时时间（秒），默认 3 秒
    """
    global async_engine, AsyncSessionLocal
    if async_engine:
        try:
            # 使用 shield 保护关闭操作不被取消
            dispose_task = asyncio.create_task(async_engine.dispose())

            try:
                # 使用 shield 保护任务不被外部取消
                await asyncio.wait_for(
                    asyncio.shield(dispose_task),
                    timeout=timeout
                )
                logger.info("[FastAPI] Async database connection closed")
            except asyncio.TimeoutError:
                # 超时：任务仍在运行
                logger.warning(f"[FastAPI] Timeout closing async database ({timeout}s), forcing shutdown")
                # 不取消任务，让它在后台完成
            except asyncio.CancelledError:
                # 被取消：静默处理，不记录错误
                logger.debug("[FastAPI] Database close operation cancelled (normal during shutdown)")
            except Exception as e:
                logger.error(f"[FastAPI] Error disposing async engine: {e}")

        except asyncio.CancelledError:
            # 外层被取消：静默处理
            logger.debug("[FastAPI] Database close cancelled")
        except Exception as e:
            logger.error(f"[FastAPI] Error closing async database: {e}")
        finally:
            async_engine = None
            AsyncSessionLocal = None


def get_db() -> Generator[Session, None, None]:
    """
    获取同步数据库会话（FastAPI 依赖注入）
    正确的依赖实现应为生成器：yield 会话，异常回滚并在最终关闭。
    """
    if SessionLocal is None:
        raise RuntimeError("Database not initialized")

    db: Session = SessionLocal()
    try:
        yield db
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            db.close()
        except Exception:
            pass


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """
    获取异步数据库会话
    用作FastAPI的异步依赖注入
    """
    if AsyncSessionLocal is None:
        logger.warning("[FastAPI] Async database not initialized")
        yield None
        return
        
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"[FastAPI] Async database session error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    获取异步数据库会话
    用于服务层的数据库操作
    """
    if AsyncSessionLocal is None:
        raise RuntimeError("Async database not initialized")
        
    session = AsyncSessionLocal()
    try:
        yield session
    except Exception as e:
        await session.rollback()
        logger.error(f"[FastAPI] Async database session error: {e}")
        raise
    finally:
        await session.close()


@asynccontextmanager
async def get_async_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    获取异步数据库会话上下文管理器
    用于手动管理会话生命周期（自动提交）
    """
    if AsyncSessionLocal is None:
        raise RuntimeError("Async database not initialized")
        
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except Exception as e:
        await session.rollback()
        logger.error(f"[FastAPI] Async database context error: {e}")
        raise
    finally:
        await session.close()


def is_async_db_available() -> bool:
    """
    检查异步数据库是否可用
    """
    return async_engine is not None and AsyncSessionLocal is not None


def get_connection_pool_status() -> dict:
    """
    获取数据库连接池状态信息
    """
    status = {
        "sync_pool": None,
        "async_pool": None
    }

    try:
        if engine and hasattr(engine, 'pool'):
            pool = engine.pool
            status["sync_pool"] = {
                "size": pool.size(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow()
            }
    except Exception as e:
        logger.error(f"获取同步连接池状态失败: {e}")
        status["sync_pool"] = {"error": str(e)}

    try:
        if async_engine and hasattr(async_engine, 'pool'):
            pool = async_engine.pool
            status["async_pool"] = {
                "size": pool.size(),
                "checked_out": pool.checkedout(),
                "overflow": pool.overflow()
            }
    except Exception as e:
        logger.error(f"获取异步连接池状态失败: {e}")
        status["async_pool"] = {"error": str(e)}

    return status


def log_connection_pool_status():
    """
    记录数据库连接池状态到日志
    """
    status = get_connection_pool_status()
    logger.info(f"[Database] Connection pool status: {status}")


def _select_session_from_kwargs(kwargs: dict) -> Optional[Session]:
    """
    从kwargs中挑选已有的同步会话，支持参数名：db 或 session
    """
    if "db" in kwargs and isinstance(kwargs.get("db"), Session):
        return kwargs["db"]
    if "session" in kwargs and isinstance(kwargs.get("session"), Session):
        return kwargs["session"]
    return None


async def _select_async_session_from_kwargs(kwargs: dict):
    """
    从kwargs中挑选已有的异步会话，支持参数名：db 或 session
    这里不直接引用 AsyncSession 以避免在未安装异步依赖时导入错误
    """
    existing = kwargs.get("db") or kwargs.get("session")
    return existing


def readonly(param_name: str = "db") -> Callable[[Callable[..., R]], Callable[..., R]]:
    """
    只读操作修饰器（支持同步/异步函数）。

    专门用于查询操作，不创建事务，只提供数据库会话。

    使用方式：
        - 被修饰的函数应接受一个会话参数，默认名为 `db`，也可通过 param_name 指定；
        - 如果调用时已通过 `db` 或 `session` 传入会话，则复用；
        - 如果调用时 `instance` 的属性 `db` 或 `session` 已赋值会话，则复用；
        - 否则自动创建会话，函数执行完毕后关闭会话；
        - 对于异步函数，使用异步会话；同步函数使用同步会话。

    参数：
        - param_name: 当未显式传入 `db`/`session` 时，注入会话使用的参数名称。
    """

    def decorator(func: Callable[..., R]) -> Callable[..., R]:
        import inspect

        if inspect.iscoroutinefunction(func):

            async def async_wrapper(*args: Any, **kwargs: Any):  # type: ignore[override]
                # 复用外部传入的会话
                existing_session = await _select_async_session_from_kwargs(kwargs)

                if existing_session is not None:
                    # 外部会话：直接使用
                    return await func(*args, **kwargs)

                instance = args[0] if args else None
                if instance is not None:
                    existing_attr_session = getattr(instance, 'db', None) or getattr(instance, "session", None)
                    if existing_attr_session is not None:
                        # 实例已持有会话，直接复用
                        return await func(*args, **kwargs)

                # 内部会话：需要异步支持
                if AsyncSessionLocal is None:
                    raise RuntimeError("Async database not initialized")

                async with AsyncSessionLocal() as session:  # type: ignore[call-arg]
                    try:
                        # 参数或属性注入
                        injected_attr = False
                        prev_attr_value: Any = None

                        if "db" not in kwargs and "session" not in kwargs:
                            # 优先尝试形参注入；如无对应形参，则注入到实例属性
                            import inspect
                            signature = inspect.signature(func)
                            if param_name in signature.parameters:
                                kwargs[param_name] = session
                            elif instance is not None:
                                # 注入到实例属性，如 self.db
                                if hasattr(instance, param_name):
                                    prev_attr_value = getattr(instance, param_name)
                                    injected_attr = True
                                else:
                                    injected_attr = True
                                setattr(instance, param_name, session)

                        # 执行函数（不使用事务）
                        result = await func(*args, **kwargs)

                        # 确保只读操作后回滚任何可能的事务
                        if session.in_transaction():
                            await session.rollback()

                        return result
                    finally:
                        # 恢复/清理实例属性
                        if injected_attr and instance is not None:
                            if prev_attr_value is not None:
                                setattr(instance, param_name, prev_attr_value)
                            else:
                                try:
                                    delattr(instance, param_name)
                                except Exception:
                                    pass

            return async_wrapper  # type: ignore[return-value]

        # 同步函数
        def sync_wrapper(*args: Any, **kwargs: Any):  # type: ignore[override]
            # 复用外部传入的会话
            existing_session = _select_session_from_kwargs(kwargs)

            if existing_session is not None:
                # 外部会话：直接使用
                return func(*args, **kwargs)

            instance = args[0] if args else None
            if instance is not None:
                existing_attr_session = getattr(instance, 'db', None) or getattr(instance, "session", None)
                if existing_attr_session is not None:
                    # 实例已持有会话，直接复用
                    return func(*args, **kwargs)

            if SessionLocal is None:
                raise RuntimeError("Database not initialized")
            session: Session = SessionLocal()
            try:
                # 参数或属性注入
                injected_attr = False
                prev_attr_value: Any = None
                if "db" not in kwargs and "session" not in kwargs:
                    import inspect
                    signature = inspect.signature(func)
                    if param_name in signature.parameters:
                        kwargs[param_name] = session
                    elif instance is not None:
                        if hasattr(instance, param_name):
                            prev_attr_value = getattr(instance, param_name)
                            injected_attr = True
                        else:
                            injected_attr = True
                        setattr(instance, param_name, session)

                # 执行函数（不使用事务）
                result = func(*args, **kwargs)

                # 确保只读操作后回滚任何可能的事务
                if session.in_transaction():
                    session.rollback()

                return result
            finally:
                # 恢复/清理实例属性
                try:
                    if 'injected_attr' in locals() and injected_attr and (args and args[0] is not None):
                        instance = args[0]
                        if prev_attr_value is not None:
                            setattr(instance, param_name, prev_attr_value)
                        else:
                            try:
                                delattr(instance, param_name)
                            except Exception:
                                pass
                except Exception:
                    pass
                session.close()

        return sync_wrapper  # type: ignore[return-value]

    return decorator


def transaction(param_name: str = "db") -> Callable[[Callable[..., R]], Callable[..., R]]:
    """
    通用事务修饰器（支持同步/异步函数）。

    使用方式：
        - 被修饰的函数应接受一个会话参数，默认名为 `db`，也可通过 param_name 指定；
        - 如果调用时已通过 `db` 或 `session` 传入会话，则复用并不负责提交/关闭；
        - 如果调用时 `instance` 的属性 `db` 或 `session` 已赋值会话，则复用并不负责提交/关闭；
        - 否则自动创建会话并开启事务，成功提交，异常时回滚并关闭；
        - 对于异步函数，使用异步会话与事务上下文；同步函数使用同步会话与事务上下文。

    参数：
        - param_name: 当未显式传入 `db`/`session` 时，注入会话使用的参数名称。
    """

    def decorator(func: Callable[..., R]) -> Callable[..., R]:
        import inspect

        if inspect.iscoroutinefunction(func):

            async def async_wrapper(*args: Any, **kwargs: Any):  # type: ignore[override]
                # 复用外部传入的会话
                existing_session = await _select_async_session_from_kwargs(kwargs)

                if existing_session is not None:
                    # 外部会话：不创建事务，由外层控制
                    return await func(*args, **kwargs)

                instance = args[0] if args else None
                if instance is not None:
                    existing_attr_session = getattr(instance, 'db', None) or getattr(instance, "session", None)
                    if existing_attr_session is not None:
                        # 实例已持有会话，直接复用，不管理事务生命周期
                        return await func(*args, **kwargs)

                # 内部会话：需要异步支持
                if AsyncSessionLocal is None:
                    raise RuntimeError("Async database not initialized")

                async with AsyncSessionLocal() as session:  # type: ignore[call-arg]
                    # 参数或属性注入
                    injected_attr = False
                    prev_attr_value: Any = None

                    if "db" not in kwargs and "session" not in kwargs:
                        # 优先尝试形参注入；如无对应形参，则注入到实例属性
                        import inspect
                        signature = inspect.signature(func)
                        if param_name in signature.parameters:
                            kwargs[param_name] = session
                        elif instance is not None:
                            # 注入到实例属性，如 self.db
                            if hasattr(instance, param_name):
                                prev_attr_value = getattr(instance, param_name)
                                injected_attr = True
                            else:
                                injected_attr = True
                            setattr(instance, param_name, session)

                    # 在事务中执行
                    try:
                        async with session.begin():
                            try:
                                result = await func(*args, **kwargs)
                            except Exception:
                                # begin 上下文会自动回滚，但确保异常不被吞掉
                                raise
                        # begin 上下文自动提交
                        return result
                    finally:
                        # 恢复/清理实例属性
                        if injected_attr and instance is not None:
                            if prev_attr_value is not None:
                                setattr(instance, param_name, prev_attr_value)
                            else:
                                try:
                                    delattr(instance, param_name)
                                except Exception:
                                    pass

            return async_wrapper  # type: ignore[return-value]

        # 同步函数
        def sync_wrapper(*args: Any, **kwargs: Any):  # type: ignore[override]
            # 复用外部传入的会话
            existing_session = _select_session_from_kwargs(kwargs)

            if existing_session is not None:
                # 外部会话：不创建事务，由外层控制
                return func(*args, **kwargs)

            instance = args[0] if args else None
            if instance is not None:
                existing_attr_session = getattr(instance, 'db', None) or getattr(instance, "session", None)
                if existing_attr_session is not None:
                    # 实例已持有会话，直接复用，不管理事务生命周期
                    return func(*args, **kwargs)

            if SessionLocal is None:
                raise RuntimeError("Database not initialized")
            session: Session = SessionLocal()
            try:
                # 参数或属性注入
                injected_attr = False
                prev_attr_value: Any = None
                if "db" not in kwargs and "session" not in kwargs:
                    import inspect
                    signature = inspect.signature(func)
                    if param_name in signature.parameters:
                        kwargs[param_name] = session
                    elif instance is not None:
                        if hasattr(instance, param_name):
                            prev_attr_value = getattr(instance, param_name)
                            injected_attr = True
                        else:
                            injected_attr = True
                        setattr(instance, param_name, session)

                # 在事务中执行
                with session.begin():
                    result = func(*args, **kwargs)
                # begin 上下文自动提交
                return result
            except Exception:
                # begin 上下文会自动回滚，但防御性处理
                session.rollback()
                raise
            finally:
                # 恢复/清理实例属性
                try:
                    if 'injected_attr' in locals() and injected_attr and (args and args[0] is not None):
                        instance = args[0]
                        if prev_attr_value is not None:
                            setattr(instance, param_name, prev_attr_value)
                        else:
                            try:
                                delattr(instance, param_name)
                            except Exception:
                                pass
                except Exception:
                    pass
                session.close()

        return sync_wrapper  # type: ignore[return-value]

    return decorator


async def create_tables():
    """
    创建所有数据库表
    """
    global async_engine
    
    if async_engine is None:
        # 异步引擎不可用时，尝试使用同步方式创建数据表（降级策略）
        try:
            settings = get_settings()
            temp_engine = engine
            created_temp_engine = False

            if temp_engine is None:
                # 创建一个临时同步引擎用于建表
                temp_engine = create_engine(
                    settings.database_url,
                    pool_pre_ping=True,
                    echo=settings.database.echo_sql if settings.database else False
                )
                created_temp_engine = True

            # 导入所有模型以确保它们被注册到Base.metadata中
            from fastapi_app.models.chat import Conversation, Message
            from fastapi_app.models.coating import CoatingRunningParams, CoatingDataboxValues
            from fastapi_app.core.llm.model import LLMProvider, LLMConfig, LLMCallHistory
            from fastapi_app.modules.monitor_service.monitor.model import Monitor, MonitorAlgorithm, MonitorEventResult, MonitorEventData
            from fastapi_app.modules.monitor_service.monitor_inspection.model import MonitorInspection
            from fastapi_app.modules.monitor_service.alarm.model import Alarm, AlarmDataResult
            from fastapi_app.modules.master_data_service.product.model import ProductInspectionItemsResult
            

            # 记录即将创建的所有表
            try:
                table_names = sorted(list(Base.metadata.tables.keys()))
                logger.info(f"[FastAPI] Tables registered for creation (sync): {table_names}")
            except Exception:
                pass
            logger.info("[FastAPI] Creating database tables with sync engine fallback...")
            Base.metadata.create_all(bind=temp_engine)
            logger.info("[FastAPI] Database tables created successfully (sync fallback)")

            if created_temp_engine:
                try:
                    temp_engine.dispose()
                except Exception:
                    pass

            return
        except Exception as e:
            logger.error(f"[FastAPI] Sync fallback create tables failed: {e}")
            return
    
    try:
        # 导入所有模型以确保它们被注册到Base.metadata中
        from fastapi_app.models.chat import Conversation, Message
        from fastapi_app.models.coating import CoatingRunningParams, CoatingDataboxValues
        from fastapi_app.core.llm.model import LLMProvider, LLMConfig, LLMCallHistory
        from fastapi_app.modules.monitor_service.monitor.model import Monitor, MonitorAlgorithm, MonitorEventResult, MonitorEventData, MonitorRecommendData
        from fastapi_app.modules.monitor_service.alarm.model import Alarm, AlarmDataResult
        from fastapi_app.modules.monitor_service.algorithm.model import Algorithm
        from fastapi_app.modules.master_data_service.product.model import ProductInspectionItemsResult, ProductExtractionConfig
        from fastapi_app.modules.monitor_service.monitor_inspection.model import MonitorInspection
        
        logger.info("[FastAPI] Creating database tables...")
        
        # 记录即将创建的所有表
        try:
            table_names = sorted(list(Base.metadata.tables.keys()))
            logger.info(f"[FastAPI] Tables registered for creation (async): {table_names}")
        except Exception:
            pass

        # 使用异步引擎创建表
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        logger.info("[FastAPI] Database tables created successfully")
        
    except Exception as e:
        logger.error(f"[FastAPI] Error creating database tables: {e}")
        raise


async def sync_database_model():
    """
    在应用启动时，自动同步数据库 Model。

    此函数旨在提供一个轻量级的、无需迁移工具的数据库结构同步方案。
    它的工作流程如下：
    1.  使用 `Base.metadata.create_all()` 创建所有在数据库中尚不存在的表。
    2.  使用 SQLAlchemy Inspector 检查已存在的表。
    3.  对比模型定义与数据库中的实际列，找出模型中新增的、但数据库表中缺失的列。
    4.  为所有缺失的列，自动生成并执行 `ALTER TABLE ... ADD COLUMN ...` 语句。

    注意：此方法仅支持【新增列】。不支持删除列、修改列类型、修改约束等复杂操作。
    """
    logger.info("[FastAPI] 开始检查并同步数据库 Model...")

    # Model 同步是管理类操作，使用同步引擎执行更稳定可靠
    sync_engine = engine
    created_temp_engine = False

    # 如果同步引擎未初始化 (例如在纯异步应用场景)，则临时创建一个
    if sync_engine is None:
        try:
            settings = get_settings()
            sync_engine = create_engine(
                settings.database_url,
                echo=False  # 在同步操作中通常关闭SQL回显，保持日志清晰
            )
            created_temp_engine = True
            logger.info("[FastAPI] 已创建临时同步引擎用于 Model 同步。")
        except Exception as e:
            logger.error(f"[FastAPI] 创建临时同步引擎失败，无法同步 Model: {e}")
            return

    try:
        # 步骤 1: 确保所有模型都已加载
        from fastapi_app.models.chat import Conversation, Message
        from fastapi_app.models.coating import CoatingRunningParams, CoatingDataboxValues
        from fastapi_app.core.llm.model import LLMProvider, LLMConfig, LLMCallHistory
        from fastapi_app.modules.monitor_service.monitor.model import Monitor, MonitorAlgorithm, MonitorEventResult, \
            MonitorEventData, MonitorRecommendData
        from fastapi_app.modules.monitor_service.alarm.model import Alarm, AlarmDataResult
        from fastapi_app.modules.monitor_service.algorithm.model import Algorithm
        from fastapi_app.modules.master_data_service.product.model import ProductInspectionItemsResult, \
            ProductExtractionConfig
        from fastapi_app.modules.monitor_service.monitor_inspection.model import MonitorInspection

        # 步骤 2: 创建数据库中尚不存在的表
        logger.info("[FastAPI] 正在创建尚未存在的表...")
        Base.metadata.create_all(bind=sync_engine)
        logger.info("[FastAPI] 缺少的表已创建完成。")

        # 步骤 3: 检查并添加缺失的字段
        logger.info("[FastAPI] 正在检查已存在表的缺失字段...")
        inspector = inspect(sync_engine)

        with sync_engine.connect() as connection:
            for table_name, table in Base.metadata.tables.items():
                db_columns = {c['name'] for c in inspector.get_columns(table_name)}
                model_columns = {c.name for c in table.columns}

                # 找出模型中有，但数据库表中没有的字段
                missing_columns = model_columns - db_columns

                if missing_columns:
                    logger.warning(f"[FastAPI] 表 '{table_name}' 检测到缺失字段: {', '.join(missing_columns)}")
                    failed_count = 0
                    # 使用事务来确保对单个表的所有字段添加是原子性的
                    with connection.begin():
                        for column_name in missing_columns:
                            column_obj = table.columns[column_name]

                            # 1. 动态构建并执行 ALTER TABLE 语句
                            column_type = column_obj.type.compile(sync_engine.dialect)
                            ddl_parts = [f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}" {column_type}']

                            # 2. 处理默认值 (包括 Enum 类型)
                            default_clause_text = None
                            if column_obj.server_default:
                                # server_default 是为 DDL 设计的，可以直接编译
                                default_clause_text = column_obj.server_default.compile(dialect=sync_engine.dialect)
                            elif column_obj.default and not callable(column_obj.default.arg):
                                # default 是客户端值，需转换为 SQL 字面量
                                value = column_obj.default.arg
                                if isinstance(value, Enum):
                                    value = value.value  # 提取 Enum 的值

                                # 使用列类型的 literal_processor 安全地将 Python 值转为 SQL 字符串
                                # 这会正确处理字符串引号、布尔值等
                                processor = column_obj.type.literal_processor(dialect=sync_engine.dialect)
                                if processor:
                                    default_clause_text = processor(value)
                                else:
                                    # 为没有 processor 的类型提供一个基础回退
                                    if isinstance(value, str):
                                        # 手动处理字符串转义，尽管不完美，但能覆盖简单场景
                                        escaped_value = value.replace("'", "''")
                                        default_clause_text = f"'{escaped_value}'"
                                    else:
                                        default_clause_text = str(value)

                            if default_clause_text is not None:
                                ddl_parts.append(f"DEFAULT {default_clause_text}")

                            # 3. 处理非空约束
                            if not column_obj.nullable:
                                ddl_parts.append("NOT NULL")

                            # --- 逻辑结束 ---

                            # 4. 组合并执行 DDL
                            sql_add_column = " ".join(ddl_parts)
                            logger.info(f"[FastAPI] 执行: {sql_add_column}")
                            try:
                                connection.execute(text(sql_add_column))
                                logger.info(f"[FastAPI]  -> 已添加字段 '{column_name}'。")
                            except Exception as e:
                                logger.error(f"[FastAPI]  -> 添加字段 '{column_name}' 失败: {e}")
                                failed_count += 1
                                continue

                            # 5. 如果模型字段定义了注释，则同步添加
                            if column_obj.comment:
                                try:
                                    sql_add_comment = text(f'COMMENT ON COLUMN "{table_name}"."{column_name}" IS :comment')
                                    connection.execute(sql_add_comment, {"comment": column_obj.comment})
                                    logger.info(f"[FastAPI]  -> 已为字段 '{column_name}' 添加注释。")
                                except Exception as e:
                                    logger.warning(f"[FastAPI]  -> 为字段 '{column_name}' 添加注释失败: {e}")
                                    failed_count += 1
                    if failed_count > 0:
                        logger.warning(f"[FastAPI] 表 '{table_name}' 的缺失字段添加失败了 {failed_count} 个字段。")
                    else:
                        logger.info(f"[FastAPI] 表 '{table_name}' 的缺失字段已添加。")

        logger.info("[FastAPI] 数据库 Model 同步完成。")

    except Exception as e:
        logger.error(f"[FastAPI] 同步数据库 Model 时发生错误: {e}")
        # 在关键的启动流程中，如果同步失败，最好抛出异常以中断启动
        raise
    finally:
        # 如果创建了临时引擎，记得在使用后销毁它
        if created_temp_engine and sync_engine:
            sync_engine.dispose()
            logger.info("[FastAPI] 临时同步引擎已销毁。")

