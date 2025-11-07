"""
PDA 文档处理异步任务
"""
import json
import logging
from datetime import datetime, UTC

from fastapi_app.core.database import get_async_session
from fastapi_app.core.context import WithAuthenticatedContext
from fastapi_app.core.context import ContextInfo
from .model import PdaDocumentExtractionTask
from .schema import PdaTaskStatusEnum, PdaTaskSummaryEnum, PdaTaskUpdate
from .service import PdaTaskService


async def parse_document(task_params: dict):
    """
    异步任务：解析PDA文档
    
    Args:
        task_params: 任务参数，包含 doc_task 和 context_info
    """
    try:
        doc_task = task_params.get('doc_task')
        context_info_dict = task_params.get('context_info')
        
        if not doc_task or not context_info_dict:
            logging.error("PDA任务参数不完整")
            return
        
        # 重建上下文信息
        context_info = ContextInfo(**context_info_dict)
        
        with WithAuthenticatedContext(context_info):
            async with get_async_session() as db:
                service = PdaTaskService(db=db)
                
                # 更新状态为解析中
                await service.update_task_status(
                    doc_task['id'],
                    PdaTaskUpdate(status=PdaTaskStatusEnum.PARSING)
                )
                
                try:
                    # 处理文档
                    file_url = doc_task.get('file_url')
                    result = await service.process_document(file_url)
                    
                    # 更新任务为成功
                    await service.update_task_status(
                        doc_task['id'],
                        PdaTaskUpdate(
                            status=PdaTaskStatusEnum.SUCCESS,
                            finish_time=datetime.now(UTC),
                            raw_text=result.get('raw_text'),
                            structured_result=result.get('structured_result')
                        )
                    )
                    
                    logging.info(f"PDA文档处理成功: {doc_task['id']}")
                    
                except Exception as e:
                    logging.error(f"PDA文档处理失败: {str(e)}")
                    
                    # 更新任务为失败
                    await service.update_task_status(
                        doc_task['id'],
                        PdaTaskUpdate(
                            status=PdaTaskStatusEnum.PARSING_FAILED,
                            finish_time=datetime.now(UTC),
                            failed_summary=PdaTaskSummaryEnum.PROCESS_DOCUMENT_FAILED,
                            failed_reason=str(e)
                        )
                    )
                    
    except Exception as e:
        logging.error(f"PDA异步任务执行失败: {str(e)}")


async def parse_document_success(task_id: str, task_params: dict):
    """
    异步任务成功回调
    
    Args:
        task_id: 任务ID
        task_params: 任务参数
    """
    logging.info(f"PDA文档处理任务成功: {task_id}")


async def parse_document_failure(task_id: str, task_params: dict, error: str):
    """
    异步任务失败回调
    
    Args:
        task_id: 任务ID
        task_params: 任务参数
        error: 错误信息
    """
    logging.error(f"PDA文档处理任务失败: {task_id}, 错误: {error}")

