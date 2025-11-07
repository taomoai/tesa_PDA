"""
优先级资源管理器

负责根据事件总线优先级动态分配和管理系统资源
"""
import asyncio
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from loguru import logger
from datetime import datetime, timedelta

from fastapi_app.models.event_bus import EventBusPriority


@dataclass
class ResourceAllocation:
    """资源分配信息"""
    max_connections: int
    rate_limit: Optional[int]  # 每分钟最大消息数
    timeout: int  # 毫秒
    retry_attempts: int
    circuit_breaker_enabled: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'max_connections': self.max_connections,
            'rate_limit': self.rate_limit,
            'timeout': self.timeout,
            'retry_attempts': self.retry_attempts,
            'circuit_breaker_enabled': self.circuit_breaker_enabled
        }


@dataclass
class SystemLoadMetrics:
    """系统负载指标"""
    cpu_usage: float  # CPU使用率 0-1
    memory_usage: float  # 内存使用率 0-1
    connection_count: int  # 当前连接数
    message_rate: float  # 每秒消息数
    error_rate: float  # 错误率 0-1
    
    def overall_load(self) -> float:
        """计算整体负载分数 0-1"""
        return (self.cpu_usage * 0.3 + 
                self.memory_usage * 0.2 + 
                min(self.connection_count / 100, 1.0) * 0.2 + 
                min(self.message_rate / 1000, 1.0) * 0.2 + 
                self.error_rate * 0.1)


class PriorityResourceManager:
    """
    优先级资源管理器
    
    根据数据源优先级和系统负载动态调整资源分配
    """
    
    def __init__(self):
        self.base_allocations = self._get_base_allocations()
        self.current_allocations: Dict[int, ResourceAllocation] = {}
        self.system_load = SystemLoadMetrics(0.0, 0.0, 0, 0.0, 0.0)
        self.load_history: List[SystemLoadMetrics] = []
        self.max_history_size = 60  # 保存最近60次负载记录
        
        # 负载阈值配置
        self.load_thresholds = {
            'high': 0.8,     # 高负载阈值
            'medium': 0.6,   # 中等负载阈值
            'low': 0.3       # 低负载阈值
        }
        
        self._initialize_allocations()
    
    def _get_base_allocations(self) -> Dict[int, ResourceAllocation]:
        """获取基础资源分配配置"""
        return {
            EventBusPriority.CRITICAL.value: ResourceAllocation(
                max_connections=10,
                rate_limit=None,  # 不限流
                timeout=30000,
                retry_attempts=5,
                circuit_breaker_enabled=False
            ),
            EventBusPriority.IMPORTANT.value: ResourceAllocation(
                max_connections=5,
                rate_limit=1000,  # 1000/分钟
                timeout=15000,
                retry_attempts=3,
                circuit_breaker_enabled=True
            ),
            EventBusPriority.NORMAL.value: ResourceAllocation(
                max_connections=2,
                rate_limit=100,   # 100/分钟
                timeout=5000,
                retry_attempts=1,
                circuit_breaker_enabled=True
            )
        }
    
    def _initialize_allocations(self):
        """初始化当前资源分配"""
        for priority, base_allocation in self.base_allocations.items():
            self.current_allocations[priority] = ResourceAllocation(
                max_connections=base_allocation.max_connections,
                rate_limit=base_allocation.rate_limit,
                timeout=base_allocation.timeout,
                retry_attempts=base_allocation.retry_attempts,
                circuit_breaker_enabled=base_allocation.circuit_breaker_enabled
            )
    
    def get_resource_allocation(self, priority: int) -> ResourceAllocation:
        """
        获取指定优先级的资源分配
        
        Args:
            priority: 优先级值
            
        Returns:
            ResourceAllocation: 资源分配配置
        """
        return self.current_allocations.get(
            priority, 
            self.current_allocations[EventBusPriority.NORMAL.value]
        )
    
    def update_system_load(self, load_metrics: SystemLoadMetrics):
        """
        更新系统负载指标
        
        Args:
            load_metrics: 新的负载指标
        """
        self.system_load = load_metrics
        self.load_history.append(load_metrics)
        
        # 保持历史记录大小
        if len(self.load_history) > self.max_history_size:
            self.load_history.pop(0)
        
        # 根据负载调整资源分配
        self._adjust_allocations_based_on_load()
        
        logger.debug(f"[PriorityResourceManager] System load updated: {load_metrics.overall_load():.2f}")
    
    def _adjust_allocations_based_on_load(self):
        """根据系统负载调整资源分配"""
        overall_load = self.system_load.overall_load()
        
        if overall_load > self.load_thresholds['high']:
            self._apply_high_load_strategy()
        elif overall_load > self.load_thresholds['medium']:
            self._apply_medium_load_strategy()
        elif overall_load < self.load_thresholds['low']:
            self._apply_low_load_strategy()
        else:
            self._apply_normal_load_strategy()
    
    def _apply_high_load_strategy(self):
        """高负载策略：保护关键资源，限制非关键资源"""
        logger.info("[PriorityResourceManager] Applying high load strategy")
        
        # 关键优先级：保持资源，但增加超时
        critical = self.current_allocations[EventBusPriority.CRITICAL.value]
        critical.timeout = min(critical.timeout * 1.2, 60000)  # 最大60秒
        
        # 重要优先级：减少连接，增加限流
        important = self.current_allocations[EventBusPriority.IMPORTANT.value]
        important.max_connections = max(important.max_connections // 2, 2)
        if important.rate_limit:
            important.rate_limit = max(important.rate_limit // 2, 50)
        
        # 普通优先级：暂停或严格限制
        normal = self.current_allocations[EventBusPriority.NORMAL.value]
        normal.max_connections = 1
        if normal.rate_limit:
            normal.rate_limit = max(normal.rate_limit // 4, 10)
        normal.circuit_breaker_enabled = True
    
    def _apply_medium_load_strategy(self):
        """中等负载策略：适度限制非关键资源"""
        logger.info("[PriorityResourceManager] Applying medium load strategy")
        
        # 关键优先级：保持原有资源
        critical = self.current_allocations[EventBusPriority.CRITICAL.value]
        base_critical = self.base_allocations[EventBusPriority.CRITICAL.value]
        critical.max_connections = base_critical.max_connections
        critical.timeout = base_critical.timeout
        
        # 重要优先级：适度限制
        important = self.current_allocations[EventBusPriority.IMPORTANT.value]
        base_important = self.base_allocations[EventBusPriority.IMPORTANT.value]
        important.max_connections = max(base_important.max_connections - 1, 3)
        if important.rate_limit and base_important.rate_limit:
            important.rate_limit = int(base_important.rate_limit * 0.7)
        
        # 普通优先级：明显限制
        normal = self.current_allocations[EventBusPriority.NORMAL.value]
        base_normal = self.base_allocations[EventBusPriority.NORMAL.value]
        normal.max_connections = max(base_normal.max_connections - 1, 1)
        if normal.rate_limit and base_normal.rate_limit:
            normal.rate_limit = int(base_normal.rate_limit * 0.5)
    
    def _apply_low_load_strategy(self):
        """低负载策略：增加资源分配"""
        logger.info("[PriorityResourceManager] Applying low load strategy")
        
        # 为所有优先级增加资源
        for priority in self.current_allocations:
            current = self.current_allocations[priority]
            base = self.base_allocations[priority]
            
            # 增加连接数
            current.max_connections = min(base.max_connections + 2, base.max_connections * 2)
            
            # 放宽限流
            if current.rate_limit and base.rate_limit:
                current.rate_limit = int(base.rate_limit * 1.5)
            
            # 减少超时时间
            current.timeout = max(base.timeout * 0.8, 1000)
    
    def _apply_normal_load_strategy(self):
        """正常负载策略：恢复基础配置"""
        for priority in self.current_allocations:
            base = self.base_allocations[priority]
            current = self.current_allocations[priority]
            
            # 逐渐恢复到基础配置
            current.max_connections = base.max_connections
            current.rate_limit = base.rate_limit
            current.timeout = base.timeout
            current.retry_attempts = base.retry_attempts
    
    def get_priority_adjustment_recommendation(self, config_key: str, current_priority: int) -> Optional[int]:
        """
        根据系统负载推荐优先级调整
        
        Args:
            config_key: 配置键
            current_priority: 当前优先级
            
        Returns:
            Optional[int]: 推荐的新优先级，None表示不需要调整
        """
        overall_load = self.system_load.overall_load()
        
        # 高负载时，建议将非关键数据源降级
        if overall_load > self.load_thresholds['high']:
            if current_priority == EventBusPriority.IMPORTANT.value:
                return EventBusPriority.NORMAL.value
        
        # 低负载时，可以考虑提升优先级
        elif overall_load < self.load_thresholds['low']:
            if current_priority == EventBusPriority.NORMAL.value:
                return EventBusPriority.IMPORTANT.value
        
        return None
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取资源管理统计信息"""
        current_load = self.system_load.overall_load()
        
        # 计算平均负载
        avg_load = 0.0
        if self.load_history:
            avg_load = sum(load.overall_load() for load in self.load_history) / len(self.load_history)
        
        # 负载趋势
        load_trend = "stable"
        if len(self.load_history) >= 5:
            recent_avg = sum(load.overall_load() for load in self.load_history[-5:]) / 5
            older_avg = sum(load.overall_load() for load in self.load_history[-10:-5]) / 5 if len(self.load_history) >= 10 else recent_avg
            
            if recent_avg > older_avg + 0.1:
                load_trend = "increasing"
            elif recent_avg < older_avg - 0.1:
                load_trend = "decreasing"
        
        return {
            'current_load': current_load,
            'average_load': avg_load,
            'load_trend': load_trend,
            'load_level': self._get_load_level(current_load),
            'resource_allocations': {
                priority: allocation.to_dict() 
                for priority, allocation in self.current_allocations.items()
            },
            'adjustment_history_size': len(self.load_history),
            'thresholds': self.load_thresholds
        }
    
    def _get_load_level(self, load: float) -> str:
        """获取负载级别描述"""
        if load > self.load_thresholds['high']:
            return "high"
        elif load > self.load_thresholds['medium']:
            return "medium"
        elif load < self.load_thresholds['low']:
            return "low"
        else:
            return "normal"
    
    async def monitor_and_adjust(self, interval_seconds: int = 30):
        """
        定期监控和调整资源分配
        
        Args:
            interval_seconds: 监控间隔（秒）
        """
        logger.info(f"[PriorityResourceManager] Starting resource monitoring (interval: {interval_seconds}s)")
        
        while True:
            try:
                # 这里可以集成真实的系统监控
                # 目前使用模拟数据
                await self._collect_system_metrics()
                await asyncio.sleep(interval_seconds)
                
            except Exception as e:
                logger.error(f"[PriorityResourceManager] Error in monitoring loop: {e}")
                await asyncio.sleep(interval_seconds)
    
    async def _collect_system_metrics(self):
        """收集系统指标（示例实现）"""
        # 这里应该集成真实的系统监控工具
        # 例如：psutil, prometheus, 等
        import random
        
        # 模拟系统负载
        simulated_load = SystemLoadMetrics(
            cpu_usage=random.uniform(0.1, 0.9),
            memory_usage=random.uniform(0.2, 0.8),
            connection_count=random.randint(10, 150),
            message_rate=random.uniform(10, 500),
            error_rate=random.uniform(0.0, 0.1)
        )
        
        self.update_system_load(simulated_load)


# 全局资源管理器实例
priority_resource_manager = PriorityResourceManager()


def get_priority_resource_manager() -> PriorityResourceManager:
    """获取优先级资源管理器实例"""
    return priority_resource_manager