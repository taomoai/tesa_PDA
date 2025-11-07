import json
import logging
from os import getenv
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import UploadFile
from sqlalchemy import select, Select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_app.core.database import readonly, transaction, get_async_session
from fastapi_app.core.context import WithAuthenticatedContext
from fastapi_app.core.llm import get_llm_client
from fastapi_app.schemas.schema import PaginationSchema, FieldFilterSchema
from fastapi_app.modules.common_service.oss.oss import AzureOSS
from fastapi_app.modules.document_extraction import ExtractionPipeline
from fastapi_app.utils.exceptions import ServiceCheckFailed
from .model import PdaDocumentExtractionTask
from .schema import PdaTaskCreate, PdaTaskUpdate, PdaTaskPagination, PdaTaskResponse
from .document_processor import PdaDocumentProcessor
from .extraction_config import create_pda_extraction_config, ExtractionConfigManager, DocumentType


def row_processor(row) -> dict:
    """将联表查询结果行转换为用于Pydantic模型的字典"""
    task_dict = row.PdaDocumentExtractionTask.to_dict()

    # 生成预览URL
    preview_url = None
    if task_dict.get('file_url'):
        try:
            oss_client = AzureOSS()
            preview_url = oss_client.get_preview_url(task_dict['file_url'], expires=3600)  # 1小时过期
        except Exception as e:
            logging.warning(f"生成预览URL失败: {str(e)}")

    return {
        **task_dict,
        "preview_url": preview_url,
    }


class PdaTaskService:
    """PDA文档任务服务"""

    def __init__(self, db: AsyncSession = None):
        """初始化服务"""
        self.db = db
        self.document_processor = PdaDocumentProcessor()
        self.extraction_config = create_pda_extraction_config()

    @staticmethod
    def build_base_stmt() -> Select:
        """构建一个查询的基本Select语句"""
        return select(
            PdaDocumentExtractionTask,
        ).where(PdaDocumentExtractionTask.is_delete == False)

    @staticmethod
    async def upload_create_pda_task(tenant_id: int, file: UploadFile, job_number: Optional[str] = None) -> int:
        """上传并创建PDA文档任务，返回新增数据ID"""
        if not job_number:
            raise ServiceCheckFailed(reason='工号是必须的', i18n_key='pda.task.job_number_required')

        from fastapi_app.modules.common_service.task_center.service import TaskCenterService
        from fastapi_app.modules.common_service.task_center.schema import TaskCenterCreateSchema
        from fastapi_app.modules.master_data_service.employee.service import EmployeeService

        # 上传文件到 AzureOSS
        oss_client = AzureOSS()
        file_format = file.filename.split('.')[-1].upper()
        file_url = oss_client.upload_file(file_obj=file.file, file_name=file.filename, format=file_format,
                                          is_public=False)

        # 手动构建用户上下文
        async with get_async_session() as session:
            employee_service = EmployeeService(db=session)
            employee = await employee_service.get_employee_by_number(job_number, tenant_id)
            context_info = await employee_service.build_context_info_by_account_id(employee.account_id)

        with WithAuthenticatedContext(context_info):
            async with get_async_session() as session:
                # 创建文档处理记录
                new_task = await PdaDocumentExtractionTask.insert_pda_document_extraction_task(PdaTaskCreate(
                    file_name=file.filename,
                    file_url=file_url,
                    tenant_id=tenant_id,
                ), db=session)
                await session.commit()
                logging.info(f"PDA任务记录创建成功， {new_task}")

                # 创建和提交异步任务记录
                taskService = TaskCenterService(session)
                task_queue_name = getenv("PDA_PARSE_TASK_QUEUE", "default")
                logging.info(f"PDA任务队列名称: {task_queue_name}")
                task_id = await taskService.create_task(task_data=TaskCenterCreateSchema(
                    title='PDA解析上传文档',
                    module='pda_service',
                    content='PDA解析上传文档',
                    task_params={'doc_task': new_task.to_dict(), 'context_info': context_info.model_dump()},
                    task_func_name='parse_document',
                    task_queue=task_queue_name,
                    success_func_name='parse_document_success',
                    failure_func_name='parse_document_failure'
                ), created_by=-1, username='system', tenant_id=tenant_id)
                logging.info(f"PDA异步任务记录创建成功， {task_id}")

                # 回写任务ID
                new_task.task_id = str(task_id)
                await session.commit()
                await session.flush()
                logging.info(f"PDA任务ID回写成功， {new_task}")

        return new_task.id

    @readonly()
    async def get_pda_task_by_id(self, record_id: str, tenant_id: int) -> Optional[PdaDocumentExtractionTask]:
        """根据主键ID和租户ID获取任务"""
        result = await PdaDocumentExtractionTask.get_query_async(db=self.db, filters=[
            FieldFilterSchema(field_name='id', values=[record_id]),
            FieldFilterSchema(field_name='tenant_id', values=[tenant_id]),
        ])
        return result.scalar_one_or_none()

    async def process_document(self, file_url: str, custom_schema: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        处理文档：解析 -> 结构化

        Args:
            file_url: 文件URL
            custom_schema: 自定义的结构化模式

        Returns:
            Dict: 包含 raw_text 和 structured_result 的结果
        """
        try:
            # 1. 解析文档
            parse_result = self.document_processor.process_document(file_url)
            raw_text = parse_result.get('text', '')

            if not raw_text:
                raise Exception("文档解析结果为空")

            # 2. 调用LLM进行结构化处理
            llm_client = await get_llm_client("pda_llm")

            # 构建结构化提示词
            schema_str = json.dumps(custom_schema, ensure_ascii=False, indent=2) if isinstance(custom_schema, dict) else str(custom_schema)
            structuring_prompt = f"""You are a data extraction expert. Extract structured data from the following text according to the provided schema.

Text:
{raw_text}

Schema:
{schema_str}

Return the extracted data as valid JSON that matches the schema."""

            llm_result = await llm_client.call_llm(structuring_prompt)

            # 清理和解析JSON结果
            try:
                llm_result = llm_result.replace("```json", "").replace("```", "").strip()
                structured_result = json.loads(llm_result)
            except json.JSONDecodeError as e:
                logging.error(f"解析LLM返回结果失败: {str(e)}")
                structured_result = {"error": "Failed to parse LLM result", "raw_response": llm_result}

            return {
                "raw_text": raw_text,
                "structured_result": structured_result
            }

        except Exception as e:
            logging.error(f"文档处理失败: {str(e)}")
            raise

    @readonly()
    async def get_pda_task_list(self, tenant_id: int, page_query: PaginationSchema) -> PdaTaskPagination:
        """获取PDA任务列表"""
        stmt = self.build_base_stmt().where(
            PdaDocumentExtractionTask.tenant_id == tenant_id
        )

        # 应用分页
        if page_query.page and page_query.page_size:
            stmt = stmt.offset((page_query.page - 1) * page_query.page_size).limit(page_query.page_size)

        result = await self.db.execute(stmt)
        tasks = result.scalars().all()

        # 获取总数
        count_stmt = select(PdaDocumentExtractionTask).where(
            PdaDocumentExtractionTask.tenant_id == tenant_id
        )
        count_result = await self.db.execute(count_stmt)
        total = len(count_result.scalars().all())

        return PdaTaskPagination(
            data=[PdaTaskResponse.model_validate(task) for task in tasks],
            total=total,
            page=page_query.page or 1,
            page_size=page_query.page_size or 10
        )

    @transaction()
    async def update_task_status(self, doc_task_id: str, update_data: PdaTaskUpdate) -> bool:
        """更新任务状态"""
        task = await self.get_pda_task_by_id(doc_task_id, update_data.tenant_id if hasattr(update_data, 'tenant_id') else None)

        if not task:
            return False

        # 更新字段
        update_dict = update_data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            if value is not None:
                setattr(task, key, value)

        await self.db.flush()
        return True

    async def extract_images_to_json(self, images: list[str], doc_type: Optional[DocumentType] = None) -> Optional[Dict[str, Any]]:
        """
        Extract structured data from a list of images.

        Args:
            images: List of image paths
            doc_type: Document type (auto-detected from filename if not specified)

        Returns:
            Dictionary with extracted data or None on error
        """
        try:
            # Get extraction configuration for the document type
            extraction_config = ExtractionConfigManager.get_config_by_type(doc_type)
            logging.info(f"Loaded extraction config for {doc_type.value} with {len(extraction_config.sections)} sections")

            # For image-based extraction, always use vision-based extraction
            # This includes Liner, Backing, Adhesive, and Connector documents
            force_vision_extraction = (
                doc_type == DocumentType.LINER or
                doc_type == DocumentType.BACKING or
                doc_type == DocumentType.ADHESIVE or
                doc_type == DocumentType.CONNECTOR_SPECS
            )
            if force_vision_extraction:
                logging.info(f"{doc_type.value} document detected - forcing vision-based extraction for images")

            # Get LLM clients
            llm_client = await get_llm_client("oqc_tesa_llm")

            # Get vision LLM client for scanned PDFs
            try:
                vision_llm_client = await get_llm_client("drawing_vl_llm")
                logging.info("Using drawing_vl_llm for vision-based extraction")
            except Exception as e:
                logging.warning(f"Vision LLM client not available: {e}, will use text LLM for all extraction")
                vision_llm_client = None

            # Create and run extraction pipeline
            pipeline = ExtractionPipeline(extraction_config, llm_client, vision_llm_client, force_vision_extraction=force_vision_extraction)
            results = await pipeline.process_images(images)
            return results

        except Exception as e:
            logging.error(f"Images extraction failed: {e}", exc_info=True)
            return None


    async def extract_pdf_to_json(
        self,
        pdf_path: str,
        output_dir: str = "output",
        doc_type: Optional[DocumentType] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Extract structured data from a PDF file.

        Automatically detects document type from filename if not specified.
        Supports multiple document types (E-FER, etc.) with type-specific extraction.

        Args:
            pdf_path: Path to the PDF file
            output_dir: Directory to save output files
            doc_type: Document type (auto-detected from filename if not specified)

        Returns:
            Dictionary with extracted data or None on error
        """
        try:
            pdf_file = Path(pdf_path)
            logging.info(f"Starting PDF extraction: {pdf_path}")

            # Auto-detect document type from filename if not specified
            if doc_type is None:
                doc_type = DocumentType.from_filename(pdf_file.name)
                logging.info(f"Auto-detected document type: {doc_type.value}")
            else:
                logging.info(f"Using specified document type: {doc_type.value}")

            # Get extraction configuration for the document type
            extraction_config = ExtractionConfigManager.get_config_by_type(doc_type)
            logging.info(f"Loaded extraction config for {doc_type.value} with {len(extraction_config.sections)} sections")

            # Create output directory
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Get LLM clients
            llm_client = await get_llm_client("oqc_tesa_llm")

            # Get vision LLM client for scanned PDFs
            try:
                vision_llm_client = await get_llm_client("drawing_vl_llm")
                logging.info("Using drawing_vl_llm for vision-based extraction")
            except Exception as e:
                logging.warning(f"Vision LLM client not available: {e}, will use text LLM for all extraction")
                vision_llm_client = None

            # For Liner and Backing documents, always use vision-based extraction
            force_vision_extraction = (doc_type == DocumentType.LINER or doc_type == DocumentType.BACKING or doc_type == DocumentType.CONNECTOR_SPECS)
            if force_vision_extraction:
                doc_type_name = "Liner" if doc_type == DocumentType.LINER else "Backing"
                logging.info(f"{doc_type_name} document detected - forcing vision-based extraction")

            # Enable pagination for EFERSPEC documents to handle large PDFs
            enable_pagination = (doc_type == DocumentType.EFERSPEC)
            if enable_pagination:
                logging.info("EFERSPEC document detected - enabling pagination extraction for large documents")

            # Create and run extraction pipeline
            pipeline = ExtractionPipeline(
                extraction_config,
                llm_client,
                vision_llm_client,
                force_vision_extraction=force_vision_extraction,
                enable_pagination=enable_pagination,
                pagination_chunk_size=2
            )
            results = await pipeline.process_pdf(pdf_path)

            if not results:
                logging.error("PDF extraction failed")
                return None

            # Save results
            pdf_name = Path(pdf_path).stem

            # Save extracted data
            output_file = output_path / f"{pdf_name}_extracted.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            logging.info(f"Saved extracted data to: {output_file}")

            logging.info("✅ PDF extraction completed successfully")
            return results

        except Exception as e:
            logging.error(f"PDF extraction failed: {e}", exc_info=True)
            return None

    async def extract_pdf_with_custom_config(
        self,
        pdf_path: str,
        config,
        output_dir: str = "output"
    ) -> Optional[Dict[str, Any]]:
        """
        Extract structured data from a PDF file using custom configuration.

        Args:
            pdf_path: Path to the PDF file
            config: Custom ExtractionConfig
            output_dir: Directory to save output files

        Returns:
            Dictionary with extracted data or None on error
        """
        try:
            logging.info(f"Starting PDF extraction with custom config: {pdf_path}")

            # Create output directory
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Get LLM client
            llm_client = await get_llm_client("oqc_tesa_llm")

            # Enable pagination for EFERSPEC documents to handle large PDFs
            # Check if this is an EFERSPEC config by looking at section names
            enable_pagination = any(
                section.section_name == "characteristics_and_properties"
                for section in config.sections
            )
            if enable_pagination:
                logging.info("EFERSPEC-like document detected - enabling pagination extraction for large documents")

            # Create and run extraction pipeline
            pipeline = ExtractionPipeline(
                config,
                llm_client,
                enable_pagination=enable_pagination,
                pagination_chunk_size=2
            )
            results = await pipeline.process_pdf(pdf_path)

            if not results:
                logging.error("PDF extraction failed")
                return None

            logging.info("✅ PDF extraction completed successfully")
            return results

        except Exception as e:
            logging.error(f"PDF extraction failed: {e}", exc_info=True)
            return None

