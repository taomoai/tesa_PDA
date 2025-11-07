import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, UTC

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import get_async_session
from fastapi_app.core.context import current_context
from fastapi_app.schemas.schema import ApiResponse, PaginationSchema
from fastapi_app.utils.response import ResponseUtil
from fastapi_app.utils.tiny_func import simple_exception
from fastapi_app.i18n import get_locale_text
from .service import PdaTaskService
from .schema import PdaTaskResponse, PdaTaskPagination, PdaTaskStatusEnum, PdaTaskSummaryEnum, PdaTaskUpdate
from .extraction_config import DocumentType


def build_json_response(
    extraction_result: Dict[str, Any],
    images: Optional[List[Dict[str, Any]]] = None,
    product_id: Optional[str] = None,
    feature_ids: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Transform extraction results into the required output format.

    Maps extraction sections to features and builds the response structure:
    {
        product_id: "xxx",
        features: [
            {
                feature_id: "xxx",
                drawing_id: "xxx",
                result: [
                    {
                        result: {
                            field_name: {
                                value: "xxxx",
                                page_number: 1,
                                reasoning: "xxxx"
                            }
                        }
                    }
                ]
            }
        ]
    }

    Args:
        extraction_result: Raw extraction result from pipeline
        images: List of image dicts with id, url, page_number
        product_id: Product ID for the response
        feature_ids: List of feature IDs to map to extraction sections

    Returns:
        Formatted response dict with product_id and features array
    """
    # Initialize response structure
    response = {
        "product_id": product_id or "unknown",
        "features": []
    }

    # If no extraction result, return empty features
    if not extraction_result:
        return response

    # Create a mapping of images by page_number for quick lookup
    images_by_page = {}
    if images:
        for img in images:
            page_num = img.get('page_number', 1)
            images_by_page[page_num] = img.get('id', '')

    # Map extraction sections to features
    # Each section in extraction_result becomes a feature
    logging.info(f"[PDA] Extraction result sections: {extraction_result}")
    for section_name, section_data in extraction_result.items():
        if not isinstance(section_data, dict):
            continue

        # Determine feature_id from section name or use provided feature_ids
        feature_id = section_name
        logging.info(f"[PDA] Mapping section '{section_name}' to feature_id '{feature_id}'")
        logging.info(f"[PDA] feature_ids provided: {feature_ids}")
        for feature in (feature_ids or []):
            if str(feature.get("name")).lower() == section_name.lower():
                feature_id = str(feature.get("id"))
                break

        # Extract page_number from extraction_basis if available
        page_number = 1
        drawing_id = ""

        # Check if section has extraction_basis with page_number
        # Normalize extraction_basis to a list so we don't iterate over None
        basis_list = section_data.get('extraction_basis')
        if basis_list is None:
            # be defensive: if extraction_basis exists but is None, treat as empty list
            logging.debug(f"[PDA] section '{section_name}' has extraction_basis=None; treating as empty list")
            basis_list = []
        elif not isinstance(basis_list, list):
            # Unexpected type - log and coerce to empty list to avoid TypeError
            logging.warning(f"[PDA] section '{section_name}' extraction_basis is not a list (type={type(basis_list)}); ignoring basis")
            basis_list = []

        if len(basis_list) > 0:
            first_basis = basis_list[0]
            if isinstance(first_basis, dict):
                page_number = int(first_basis.get('page_number', 1))
                # Get drawing_id from images_by_page mapping
                drawing_id = images_by_page.get(page_number, "")

        # Build result array with field information
        result_array = []
        result_obj = {"result": {}}

        # Process each field in the section
        for field_name, field_value in section_data.items():
            if field_name == 'extraction_basis':
                continue

            # Find extraction basis for this field (use normalized basis_list)
            field_basis = None
            for basis in basis_list:
                if isinstance(basis, dict) and basis.get('field_name') == field_name:
                    field_basis = basis
                    break

            # Build field result object
            if field_basis:
                result_obj["result"][field_name] = {
                    "value": field_basis.get('value', field_value),
                    "page_number": int(field_basis.get('page_number', page_number)),
                    "reasoning": field_basis.get('reasoning', '')
                }
            else:
                # If no basis found, use the field value directly
                result_obj["result"][field_name] = {
                    "value": field_value,
                    "page_number": page_number,
                    "reasoning": ""
                }

        result_array.append(result_obj)

        # Build feature object
        feature = {
            "feature_id": feature_id,
            "drawing_id": drawing_id,
            "result": result_array
        }

        response["features"].append(feature)

    return response

class PdaTaskController:
    """PDA文档任务控制器"""

    @staticmethod
    async def upload_document(tenant_id: int, file: UploadFile, job_number: Optional[str] = None) -> ApiResponse[str]:
        """上传PDA文档"""
        try:
            pda_task_id = await PdaTaskService.upload_create_pda_task(tenant_id, file, job_number)
            return ResponseUtil.success(data=str(pda_task_id), message=get_locale_text('pda.task.created'))
        except Exception as e:
            logging.error(f'[FastAPI] 上传PDA文档失败: {simple_exception(e)}')
            return ResponseUtil.error(message=get_locale_text('pda.task.create_failed').format(error=str(e)))

    @staticmethod
    async def get_task_list(page_query: PaginationSchema) -> ApiResponse[PdaTaskPagination]:
        """获取PDA任务列表"""
        try:
            context_info = current_context.get()
            tenant_id = context_info.tenant_id
            
            async with get_async_session() as db:
                service = PdaTaskService(db=db)
                result = await service.get_pda_task_list(tenant_id, page_query)
                return ResponseUtil.success(data=result)
        except Exception as e:
            logging.error(f'[FastAPI] 获取PDA任务列表失败: {simple_exception(e)}')
            return ResponseUtil.error(message=get_locale_text('pda.task.list_retrieve_failed').format(error=str(e)))

    @staticmethod
    async def get_task_details(doc_task_id: str) -> ApiResponse[PdaTaskResponse]:
        """获取PDA任务详情"""
        try:
            context_info = current_context.get()
            tenant_id = context_info.tenant_id
            
            async with get_async_session() as db:
                service = PdaTaskService(db=db)
                task = await service.get_pda_task_by_id(doc_task_id, tenant_id)
                
                if not task:
                    return ResponseUtil.error(message=get_locale_text('pda.task.not_found'))
                
                return ResponseUtil.success(data=PdaTaskResponse.model_validate(task))
        except Exception as e:
            logging.error(f'[FastAPI] 获取PDA任务详情失败: {simple_exception(e)}')
            return ResponseUtil.error(message=get_locale_text('pda.task.detail_retrieve_failed').format(error=str(e)))

    @staticmethod
    async def internal_update_task_status(doc_task_id: str, update_data: PdaTaskUpdate) -> ApiResponse[bool]:
        """内部使用：更新PDA任务状态"""
        try:
            async with get_async_session() as db:
                service = PdaTaskService(db=db)
                success = await service.update_task_status(doc_task_id, update_data)
                
                if success:
                    return ResponseUtil.success(data=True, message=get_locale_text('pda.task.updated'))
                else:
                    return ResponseUtil.error(message=get_locale_text('pda.task.update_failed'))
        except Exception as e:
            logging.error(f'[FastAPI] 更新PDA任务状态失败: {simple_exception(e)}')
            return ResponseUtil.error(message=get_locale_text('pda.task.update_failed').format(error=str(e)))

    @staticmethod
    async def extract_images_to_json(images: list[Dict[str, Any]], product_id: str, feature_ids: list[Dict[str, Any]]) -> ApiResponse[dict]:
        """提取图片到JSON"""
        try:
            logging.info(f'[FastAPI] 开始提取图片到JSON，product_id={product_id}, images_count={len(images)}')
            logging.info(f'[FastAPI] feature_ids={feature_ids}')
            async with get_async_session() as db:
                service = PdaTaskService(db=db)
                result = await service.extract_images_to_json(images, doc_type=DocumentType.CONNECTOR_SPECS)

                if not result:
                    return ResponseUtil.error(message=('pda.task.extract_images_to_json_failed'))

                # Transform extraction result into required output format
                formatted_result = build_json_response(
                    extraction_result=result,
                    images=images,
                    product_id=product_id,
                    feature_ids=feature_ids
                )

                return ResponseUtil.success(data=formatted_result)
        except Exception as e:
            logging.error(f'[FastAPI] 提取图片到JSON失败: {simple_exception(e)}')
            return ResponseUtil.error(message=get_locale_text('pda.task.extract_images_to_json_failed').format(error=str(e)))

pda_task_controller = PdaTaskController()

