"""
边界网关处理器

已迁移到装饰器方式的事件处理器，请参考 event_handlers.py
原有的 GatewayHandlers 类已移除，因为只需要保留 Coating Data 处理器，
该处理器已通过 @external_event_handler 装饰器直接注册。
"""

# 此文件保留用于可能的未来扩展，当前所有事件处理都在 event_handlers.py 中进行