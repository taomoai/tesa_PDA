import os
import tempfile
import uuid
from typing import Dict, Any, Optional
from urllib.parse import urlparse
import requests
from loguru import logger

from fastapi_app.utils.exceptions import ProcessDocumentFailed
from fastapi_app.utils.parsers.word_parser import WordFileParser
from fastapi_app.utils.parsers.pdf_parser import PDFFileParser
from fastapi_app.utils.parsers.image_parser import ImageFileParser
from fastapi_app.utils.parsers.excel_parser import ExcelFileParser
from fastapi_app.utils.tiny_func import simple_exception


class PdaDocumentProcessor:
    """PDA文档处理器，统一处理不同类型的文档"""
    
    def __init__(self):
        self.word_parser = WordFileParser()
        self.pdf_parser = PDFFileParser()
        self.image_parser = ImageFileParser()
        self.excel_parser = ExcelFileParser()
    
    def _get_file_extension(self, file_url: str) -> str:
        """获取文件扩展名"""
        parsed_url = urlparse(file_url)
        path = parsed_url.path
        return os.path.splitext(path)[1].lower().lstrip('.')
    
    def _download_file(self, file_url: str) -> str:
        """下载文件到临时目录"""
        try:
            # 检查是否为 Azure Blob Storage URL
            if 'blob.core.chinacloudapi.cn' in file_url or 'blob.core.windows.net' in file_url:
                # 使用 AzureOSS 安全下载方法（内部认证，无需 SAS 令牌）
                from fastapi_app.modules.common_service.oss.oss import AzureOSS
                oss_client = AzureOSS()

                # 使用安全下载方法
                file_content, file_name, content_type = oss_client.download_file_securely(file_url)
                logger.info(f"安全下载完成: {file_name}, 内容类型: {content_type}")

                # 生成临时文件路径
                file_extension = self._get_file_extension(file_url)
                temp_file = tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=f'.{file_extension}',
                    prefix=f'pda_{uuid.uuid4().hex[:8]}_'
                )

                # 写入文件内容
                with open(temp_file.name, 'wb') as f:
                    f.write(file_content.getvalue())

                logger.info(f"文件下载完成: {file_url} -> {temp_file.name}")
                return temp_file.name
            else:
                # 使用 requests 下载其他 URL
                response = requests.get(file_url, stream=True, timeout=30)
                response.raise_for_status()

                # 生成临时文件路径
                file_extension = self._get_file_extension(file_url)
                temp_file = tempfile.NamedTemporaryFile(
                    delete=False,
                    suffix=f'.{file_extension}',
                    prefix=f'pda_{uuid.uuid4().hex[:8]}_'
                )

                # 写入文件内容
                with temp_file as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                logger.info(f"文件下载完成: {file_url} -> {temp_file.name}")
                return temp_file.name

        except Exception as e:
            logger.error(f"下载文件失败: {file_url}, 错误: {str(e)}")
            raise Exception(f"下载文件失败: {str(e)}")
    
    def _cleanup_temp_file(self, file_path: str):
        """清理临时文件"""
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
                logger.debug(f"临时文件已清理: {file_path}")
        except Exception as e:
            logger.warning(f"清理临时文件失败: {file_path}, 错误: {str(e)}")
    
    def process_document(self, file_url: str) -> Dict[str, Any]:
        """
        处理文档并提取内容
        
        :param file_url: 文档URL
        :return: 解析结果，包含 text 字段
        :raise ProcessDocumentFailed: 文档处理失败
                    - code=-1: 不支持的文件类型
                    - code=1: 文档处理失败
        """
        temp_file_path = None

        # 1. 获取文件类型
        file_extension = self._get_file_extension(file_url)
        logger.info(f"开始处理PDA文档: {file_url}, 类型: {file_extension}")

        try:
            # 2. 下载文件
            temp_file_path = self._download_file(file_url)
            
            # 3. 根据文件类型选择解析器
            if file_extension in ['docx', 'doc']:
                result = self.word_parser.parse(temp_file_path)
            elif file_extension == 'pdf':
                result = self.pdf_parser.parse(temp_file_path)
            elif file_extension in ['jpg', 'jpeg', 'png']:
                result = self.image_parser.parse(temp_file_path)
            elif file_extension in ['xls', 'xlsx']:
                result = self.excel_parser.parse(temp_file_path)
            else:
                raise ProcessDocumentFailed(code=-1, reason=f"不支持的文件类型: {file_extension}", extension=file_extension)
            
            logger.info(f"PDA文档解析完成: {file_url}")
            return result
            
        except Exception as e:
            logger.error(f"PDA文档处理失败: {file_url}, 错误: {simple_exception(e)}")
            raise ProcessDocumentFailed(code=1, reason=f"文档处理失败: {e}", extension=file_extension, error=e) from e
            
        finally:
            # 清理临时文件
            if temp_file_path:
                self._cleanup_temp_file(temp_file_path)

