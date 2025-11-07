"""
PDA Service 模块

用于处理 PDA（Portable Data Assistant）文件上传、解析和结构化处理。
功能流程：
1. 上传文件到 OSS
2. 解析文件成文本
3. 调用大模型进行结构化处理
4. 返回结构化结果

模块结构：
- model.py: 数据模型
- schema.py: Pydantic 模式
- service.py: 业务逻辑
- controller.py: 控制器
- route.py: 路由定义
- document_processor.py: 文档处理器
- prompt.py: 提示词模板
"""

from .route import pda_router

all_routers = [pda_router]

__all__ = ["all_routers"]

