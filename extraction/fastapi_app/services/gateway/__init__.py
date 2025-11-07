"""
边界网关服务

实现事件处理和转发，使用装饰器方式注册事件处理器。
目前仅保留 Coating Data 外部事件处理器。
"""

from .gateway_service import GatewayService

__all__ = [
    'GatewayService'
]