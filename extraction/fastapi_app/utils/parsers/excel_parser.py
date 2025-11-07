import logging
from typing import Dict, Any

import pandas as pd

logger = logging.getLogger(__name__)

class ExcelFileParser():
    """Parser for Excel files (XLS, XLSX)."""
    
    def parse(self, file_path: str) -> Dict[str, Any]:
        """
        Parse Excel file and extract content.
        
        Args:
            file_path: The local path of the Excel file to parse
            product: Optional OqcProduct instance containing product information
            
        Returns:
            Dict containing the extracted content
        """
        try:
            # 读取Excel文件
            df_dict = pd.read_excel(file_path, sheet_name=None)
            
            # 转换为Markdown格式
            markdown_content = self._excel_to_markdown(df_dict)
            
            # 构建结果对象
            result = {
                "type": "excel",
                "text": markdown_content,
                "tables": []  # 保持与原有格式兼容
            }
            
            return result
        except Exception as excel_error:
            logger.error(f"Excel处理错误: {str(excel_error)}", exc_info=True)
            return {"error": f"Excel文件处理失败: {str(excel_error)}"}

    def _excel_to_markdown(self, df_dict: Dict[str, pd.DataFrame]) -> str:
        """将Excel内容转换为Markdown格式。"""
        markdown_parts = []
        
        for sheet_name, df in df_dict.items():
            # 添加工作表名称作为标题
            markdown_parts.append(f"## {sheet_name}")
            markdown_parts.append("")  # 空行
            
            # 检查DataFrame是否为空
            if df.empty:
                markdown_parts.append("*空工作表*")
                markdown_parts.append("")  # 空行
                continue
            
            # 将DataFrame转换为markdown表格
            # 处理表头
            headers = [str(col) for col in df.columns]
            markdown_parts.append("| " + " | ".join(headers) + " |")
            
            # 添加分隔行
            markdown_parts.append("| " + " | ".join(["---" for _ in headers]) + " |")
            
            # 处理数据行
            for _, row in df.iterrows():
                # 确保所有值都转换为字符串，并处理None/NaN
                row_values = []
                for val in row:
                    if pd.isna(val):
                        row_values.append("")
                    else:
                        row_values.append(str(val))
                markdown_parts.append("| " + " | ".join(row_values) + " |")
            
            # 在每个表格后添加空行
            markdown_parts.append("")
        
        return "\n".join(markdown_parts)

    def _process_excel(self, file_path: str) -> Dict[str, Any]:
        """Process Excel file and extract content."""
        try:            
            # 读取Excel文件
            df_dict = pd.read_excel(file_path, sheet_name=None)
            
            # 转换为Markdown格式
            markdown_content = self._excel_to_markdown(df_dict)
            
            # 构建初始结果对象
            result = {
                "full_extraction": {
                    "text": markdown_content,
                    "tables": []  # 保持与原有格式兼容
                }
            }

            return result
        except Exception as excel_error:
            logger.error(f"Excel处理错误: {str(excel_error)}", exc_info=True)
            return {"error": f"Excel文件处理失败: {str(excel_error)}"}