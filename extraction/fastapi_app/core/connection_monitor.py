"""
数据库连接监控和自动清理工具
用于监控和管理数据库连接，防止连接泄漏
"""
import asyncio
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

from .database import engine, async_engine, SessionLocal, AsyncSessionLocal


class ConnectionMonitor:
    """数据库连接监控器"""
    
    def __init__(self, check_interval: int = 300):  # 5分钟检查一次
        self.check_interval = check_interval
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.last_check_time = datetime.now()
        
    def start(self):
        """启动连接监控"""
        if self.running:
            logger.warning("连接监控器已经在运行")
            return
            
        self.running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info(f"数据库连接监控器已启动，检查间隔: {self.check_interval}秒")
        
    def stop(self):
        """停止连接监控"""
        self.running = False
        if self.monitor_thread and self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=5)
        logger.info("数据库连接监控器已停止")
        
    def _monitor_loop(self):
        """监控循环"""
        while self.running:
            try:
                self._check_connections()
                self.last_check_time = datetime.now()
            except Exception as e:
                logger.error(f"连接监控检查失败: {e}")
                
            # 等待下次检查
            for _ in range(self.check_interval):
                if not self.running:
                    break
                time.sleep(1)
                
    def _check_connections(self):
        """检查连接状态"""
        logger.info("开始检查数据库连接状态...")
        
        # 检查同步连接池
        if engine is not None:
            try:
                pool = engine.pool
                pool_info = {
                    'size': pool.size(),
                    'checked_out': pool.checkedout(),
                    'overflow': pool.overflow(),
                    'checked_in': pool.checkedin()
                }
                logger.info(f"同步连接池状态: {pool_info}")
                
                # 如果连接数过多，记录警告
                if pool_info['checked_out'] > pool_info['size'] * 0.8:
                    logger.warning(f"同步连接池使用率过高: {pool_info['checked_out']}/{pool_info['size']}")
                    
            except Exception as e:
                logger.error(f"检查同步连接池失败: {e}")
                
        # 检查异步连接池
        if async_engine is not None:
            try:
                pool = async_engine.pool
                pool_info = {
                    'size': pool.size(),
                    'checked_out': pool.checkedout(),
                    'overflow': pool.overflow(),
                    'checked_in': pool.checkedin()
                }
                logger.info(f"异步连接池状态: {pool_info}")
                
                # 如果连接数过多，记录警告
                if pool_info['checked_out'] > pool_info['size'] * 0.8:
                    logger.warning(f"异步连接池使用率过高: {pool_info['checked_out']}/{pool_info['size']}")
                    
            except Exception as e:
                logger.error(f"检查异步连接池失败: {e}")
                
        # 检查ConnectionManager缓存
        try:
            from ..modules.datafabric_service.database_meta.connection.connection_manager import ConnectionManager
            connection_manager = ConnectionManager.get_instance()
            if hasattr(connection_manager, '_engine_cache'):
                cache_count = len(connection_manager._engine_cache)
                logger.info(f"ConnectionManager 缓存引擎数量: {cache_count}")
                
                # 检查每个缓存引擎的连接池状态
                for cache_key, cached_engine in connection_manager._engine_cache.items():
                    try:
                        pool = cached_engine.pool
                        pool_info = {
                            'size': pool.size(),
                            'checked_out': pool.checkedout(),
                            'overflow': pool.overflow(),
                            'checked_in': pool.checkedin()
                        }
                        logger.debug(f"缓存引擎 {cache_key} 连接池状态: {pool_info}")
                        
                        # 如果连接数过多，记录警告
                        if pool_info['checked_out'] > pool_info['size'] * 0.8:
                            logger.warning(f"缓存引擎 {cache_key} 连接池使用率过高: {pool_info['checked_out']}/{pool_info['size']}")
                            
                    except Exception as e:
                        logger.error(f"检查缓存引擎 {cache_key} 失败: {e}")
                        
        except Exception as e:
            logger.error(f"检查 ConnectionManager 缓存失败: {e}")
            
    def get_status(self) -> Dict:
        """获取监控状态"""
        return {
            'running': self.running,
            'last_check_time': self.last_check_time.isoformat(),
            'check_interval': self.check_interval
        }


class ConnectionCleaner:
    """数据库连接清理器"""
    
    @staticmethod
    def cleanup_all_connections():
        """清理所有数据库连接"""
        logger.info("开始清理所有数据库连接...")
        
        # 清理同步连接池
        if engine is not None:
            try:
                pool = engine.pool
                logger.info(f"清理前同步连接池状态 - Size: {pool.size()}, Checked out: {pool.checkedout()}")
                engine.dispose()
                logger.info("同步数据库连接池已清理")
            except Exception as e:
                logger.error(f"清理同步连接池失败: {e}")
                
        # 清理异步连接池
        if async_engine is not None:
            try:
                pool = async_engine.pool
                logger.info(f"清理前异步连接池状态 - Size: {pool.size()}, Checked out: {pool.checkedout()}")
                
                # 异步清理需要在事件循环中执行
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(async_engine.dispose())
                    logger.info("已安排清理异步数据库连接池")
                except RuntimeError:
                    # 没有运行中的事件循环，直接运行
                    asyncio.run(async_engine.dispose())
                    logger.info("异步数据库连接池已清理")
                    
            except Exception as e:
                logger.error(f"清理异步连接池失败: {e}")
                
        # 清理ConnectionManager缓存
        try:
            from ..modules.datafabric_service.database_meta.connection.connection_manager import ConnectionManager
            connection_manager = ConnectionManager.get_instance()
            if hasattr(connection_manager, '_engine_cache'):
                cache_count = len(connection_manager._engine_cache)
                logger.info(f"清理 {cache_count} 个 ConnectionManager 缓存引擎")
                
                for cache_key, cached_engine in list(connection_manager._engine_cache.items()):
                    try:
                        cached_engine.dispose()
                        logger.debug(f"已清理缓存引擎: {cache_key}")
                    except Exception as e:
                        logger.error(f"清理缓存引擎 {cache_key} 失败: {e}")
                        
                connection_manager._engine_cache.clear()
                logger.info("ConnectionManager 引擎缓存已清理")
                
        except Exception as e:
            logger.error(f"清理 ConnectionManager 缓存失败: {e}")
            
        logger.info("数据库连接清理完成")
        
    @staticmethod
    def force_close_idle_connections():
        """强制关闭空闲连接"""
        logger.info("开始强制关闭空闲连接...")
        
        # 对于SQLAlchemy连接池，我们可以调用invalidate来强制关闭所有连接
        if engine is not None:
            try:
                engine.pool.invalidate()
                logger.info("同步连接池中的空闲连接已失效")
            except Exception as e:
                logger.error(f"失效同步连接池连接失败: {e}")
                
        if async_engine is not None:
            try:
                async_engine.pool.invalidate()
                logger.info("异步连接池中的空闲连接已失效")
            except Exception as e:
                logger.error(f"失效异步连接池连接失败: {e}")


# 全局连接监控器实例
connection_monitor = ConnectionMonitor()


def start_connection_monitoring():
    """启动连接监控"""
    connection_monitor.start()


def stop_connection_monitoring():
    """停止连接监控"""
    connection_monitor.stop()


def cleanup_all_database_connections():
    """清理所有数据库连接的便捷函数"""
    ConnectionCleaner.cleanup_all_connections()


def get_connection_status() -> Dict:
    """获取连接状态的便捷函数"""
    status = {
        'monitor': connection_monitor.get_status(),
        'pools': {}
    }

    # 获取连接池状态
    if engine is not None:
        try:
            pool = engine.pool
            status['pools']['sync'] = {
                'size': pool.size(),
                'checked_out': pool.checkedout(),
                'overflow': pool.overflow(),
                'checked_in': pool.checkedin()
            }
        except Exception as e:
            status['pools']['sync'] = {'error': str(e)}

    if async_engine is not None:
        try:
            pool = async_engine.pool
            status['pools']['async'] = {
                'size': pool.size(),
                'checked_out': pool.checkedout(),
                'overflow': pool.overflow(),
                'checked_in': pool.checkedin()
            }
        except Exception as e:
            status['pools']['async'] = {'error': str(e)}

    return status
