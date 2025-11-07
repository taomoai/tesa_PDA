from typing import Optional
from fastapi import APIRouter, Path, Depends, UploadFile, File, Form, Body, HTTPException, Request
from pydantic_validation_decorator import ValidateFields
from typing import Dict, Any

from fastapi_app.core.dependency import as_query
from fastapi_app.core.database import get_async_session
from fastapi_app.schemas.schema import ApiResponse, PaginationSchema, PaginationBaseSchema
from fastapi_app.models.auth.tenant import Tenant
from .controller import pda_task_controller
from .schema import PdaTaskResponse, PdaTaskPagination, PdaTaskUpdate

# 创建路由器
pda_router = APIRouter(prefix="/pda-document-extraction-tasks", tags=["PDA-文档任务"])


@pda_router.post("/upload", summary="上传PDA文档", response_model=ApiResponse[str])
async def upload_document(
    request: Request,
    file: UploadFile = File(..., description="PDA文档文件"),
    job_number: Optional[str] = Form(None, description="工号，用于查询用户对应的 org id")
) -> ApiResponse[str]:
    """上传PDA文档"""
    # 从请求上下文获取租户ID
    tenant_id = getattr(request.state, 'tenant_id', None)
    if not tenant_id:
        # 如果没有租户ID，尝试从数据库查询默认租户
        async with get_async_session() as async_db:
            tenant_id = await Tenant.select_tenant_id_by_code(code="default", db=async_db)
            if not tenant_id:
                raise HTTPException(
                    status_code=400,
                    detail="未找到租户信息"
                )
    
    return await pda_task_controller.upload_document(tenant_id=tenant_id, file=file, job_number=job_number)


@pda_router.put("/inner-update/{doc_task_id}", summary="仅内部使用：更新PDA任务", response_model=ApiResponse[bool])
@ValidateFields(validate_model='pda_task_update')
async def update_pda_task(
        doc_task_id: str = Path(..., description='PDA文档处理任务ID (主键)'),
        pda_task_update: PdaTaskUpdate = Body(..., description='更新数据'),
) -> ApiResponse[bool]:
    """更新PDA任务状态（内部使用）"""
    return await pda_task_controller.internal_update_task_status(doc_task_id=doc_task_id, update_data=pda_task_update)


@pda_router.get("/", summary="获取PDA任务列表", response_model=ApiResponse[PdaTaskPagination])
@ValidateFields(validate_model='page_query')
async def get_pda_tasks(page_query: PaginationSchema = Depends(as_query(PaginationSchema))) -> ApiResponse[PdaTaskPagination]:
    """获取PDA任务列表"""
    return await pda_task_controller.get_task_list(page_query)


@pda_router.get("/{doc_task_id}", summary="获取PDA任务详情", response_model=ApiResponse[PdaTaskResponse])
async def get_pda_task_details(
    doc_task_id: str = Path(..., description="PDA文档处理任务ID（主键）")
) -> ApiResponse[PdaTaskResponse]:
    """获取PDA任务详情"""
    return await pda_task_controller.get_task_details(doc_task_id)

@pda_router.post("/extract-images-to-json", summary="提取图片到JSON", response_model=ApiResponse[dict])
async def extract_images_to_json(
    images: list[Dict[str, Any]] = Body(..., description="图片列表, [{id: \"\", url: \"\"}]"),
    product_id: str = Body(..., description="产品ID"),
    feature_ids: list[Dict[str, Any]] = Body(..., description="特征ID列表")
) -> ApiResponse[dict]:
    """提取图片到JSON"""
    return await pda_task_controller.extract_images_to_json(images, product_id, feature_ids)