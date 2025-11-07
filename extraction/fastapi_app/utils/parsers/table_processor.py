"""
表格处理模块 - 用于处理和优化从 Word/PDF 中提取的表格

功能：
1. 表格格式转换（Markdown ↔ JSON）
2. 表格识别和分类
3. 表格验证和清理
4. 表格格式优化
"""

import logging
import re
import json
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class TableType(Enum):
    """表格类型枚举"""
    DATA_TABLE = "data_table"  # 数据表（测试项、值、方法等）
    INFO_TABLE = "info_table"  # 信息表（产品信息、规格等）
    COMPLEX_TABLE = "complex_table"  # 复杂表（合并单元格等）
    UNKNOWN = "unknown"  # 未知类型


class TableProcessor:
    """表格处理器"""
    
    def __init__(self):
        """初始化表格处理器"""
        # 数据表的特征关键词
        self.data_table_keywords = [
            'test', 'item', 'unit', 'value', 'method', 'result', 'ok/ng',
            '测试', '项目', '单位', '值', '方法', '结果', '是否合格',
            'inspection', '检测', 'specification', '规格'
        ]
        
        # 信息表的特征关键词
        self.info_table_keywords = [
            'product', 'model', 'specification', 'description',
            '产品', '型号', '规格', '描述', '说明'
        ]
    
    def identify_table_type(self, headers: List[str]) -> TableType:
        """
        识别表格类型
        
        Args:
            headers: 表格表头列表
            
        Returns:
            TableType: 表格类型
        """
        if not headers:
            return TableType.UNKNOWN
        
        # 将表头转换为小写进行比较
        headers_lower = [h.lower() for h in headers]
        headers_text = ' '.join(headers_lower)
        
        # 检查是否为数据表
        data_table_count = sum(1 for kw in self.data_table_keywords if kw in headers_text)
        if data_table_count >= 3:
            return TableType.DATA_TABLE
        
        # 检查是否为信息表
        info_table_count = sum(1 for kw in self.info_table_keywords if kw in headers_text)
        if info_table_count >= 2:
            return TableType.INFO_TABLE
        
        # 检查是否为复杂表
        if len(headers) > 10 or any('colspan' in str(h).lower() for h in headers):
            return TableType.COMPLEX_TABLE
        
        return TableType.UNKNOWN
    
    def parse_markdown_table(self, markdown_text: str) -> List[Dict[str, Any]]:
        """
        解析 Markdown 表格
        
        Args:
            markdown_text: Markdown 格式的表格文本
            
        Returns:
            List[Dict]: 表格数据列表
        """
        tables = []
        lines = markdown_text.split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # 检查是否是表格开始（以 | 开头）
            if line.startswith('|'):
                table_data = self._extract_markdown_table(lines, i)
                if table_data:
                    tables.append(table_data)
                    i += table_data['line_count']
                else:
                    i += 1
            else:
                i += 1
        
        return tables
    
    def _extract_markdown_table(self, lines: List[str], start_idx: int) -> Optional[Dict[str, Any]]:
        """
        从 Markdown 中提取单个表格
        
        Args:
            lines: 所有行
            start_idx: 表格开始行索引
            
        Returns:
            Dict: 表格数据或 None
        """
        try:
            # 提取表头
            header_line = lines[start_idx].strip()
            headers = [h.strip() for h in header_line.split('|')[1:-1]]
            
            if not headers:
                return None
            
            # 跳过分隔符行
            if start_idx + 1 >= len(lines):
                return None
            
            separator_line = lines[start_idx + 1].strip()
            if not all(c in '|-: ' for c in separator_line):
                return None
            
            # 提取数据行
            rows = []
            line_count = 2
            
            for i in range(start_idx + 2, len(lines)):
                line = lines[i].strip()
                
                # 检查是否是表格行
                if not line.startswith('|'):
                    break
                
                # 提取单元格
                cells = [c.strip() for c in line.split('|')[1:-1]]
                
                # 检查单元格数量是否匹配
                if len(cells) != len(headers):
                    break
                
                # 创建行字典
                row_dict = {}
                for j, header in enumerate(headers):
                    row_dict[header] = cells[j] if j < len(cells) else ''
                
                rows.append(row_dict)
                line_count += 1
            
            # 识别表格类型
            table_type = self.identify_table_type(headers)
            
            return {
                'headers': headers,
                'rows': rows,
                'type': table_type.value,
                'line_count': line_count
            }
        
        except Exception as e:
            logger.warning(f"解析 Markdown 表格失败: {str(e)}")
            return None
    
    def convert_to_json(self, table_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        将表格数据转换为 JSON 格式
        
        Args:
            table_data: 表格数据
            
        Returns:
            Dict: JSON 格式的表格数据
        """
        return {
            'headers': table_data.get('headers', []),
            'rows': table_data.get('rows', []),
            'type': table_data.get('type', 'unknown'),
            'row_count': len(table_data.get('rows', [])),
            'column_count': len(table_data.get('headers', []))
        }
    
    def clean_table_cell(self, cell: str) -> str:
        """
        清理表格单元格内容
        
        Args:
            cell: 单元格内容
            
        Returns:
            str: 清理后的内容
        """
        if not cell:
            return ''
        
        # 转换为字符串
        cell = str(cell).strip()
        
        # 移除多余的空格
        cell = ' '.join(cell.split())
        
        # 修复常见的 OCR 错误
        cell = re.sub(r'(\d+)o\b', r'\1°', cell)  # 数字后的 'o' -> '°'
        cell = re.sub(r'(\d+)o([A-Z])', r'\1°\2', cell)  # 数字后的 'o' 跟大写字母
        
        # 统一单位表示
        cell = cell.replace('㎡', 'm²')
        cell = cell.replace('μm', 'μm')
        
        return cell
    
    def validate_table(self, table_data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        验证表格数据的完整性和正确性
        
        Args:
            table_data: 表格数据
            
        Returns:
            Tuple[bool, List[str]]: (是否有效, 错误信息列表)
        """
        errors = []
        
        # 检查表头
        if not table_data.get('headers'):
            errors.append("表格缺少表头")
            return False, errors
        
        # 检查行数据
        if not table_data.get('rows'):
            errors.append("表格没有数据行")
            return False, errors
        
        # 检查每行的列数
        header_count = len(table_data['headers'])
        for i, row in enumerate(table_data['rows']):
            if isinstance(row, dict):
                if len(row) != header_count:
                    errors.append(f"第 {i+1} 行的列数不匹配（期望 {header_count}，实际 {len(row)}）")
        
        return len(errors) == 0, errors
    
    def format_table_for_ai(self, table_data: Dict[str, Any]) -> str:
        """
        格式化表格以便 AI 识别
        
        Args:
            table_data: 表格数据
            
        Returns:
            str: 格式化后的表格文本
        """
        headers = table_data.get('headers', [])
        rows = table_data.get('rows', [])
        
        if not headers or not rows:
            return ""
        
        # 生成 Markdown 表格
        lines = []
        
        # 表头
        lines.append('| ' + ' | '.join(headers) + ' |')
        lines.append('| ' + ' | '.join(['---'] * len(headers)) + ' |')
        
        # 数据行
        for row in rows:
            if isinstance(row, dict):
                cells = [str(row.get(h, '')).strip() for h in headers]
            else:
                cells = [str(c).strip() for c in row]
            
            lines.append('| ' + ' | '.join(cells) + ' |')
        
        return '\n'.join(lines)
    
    def extract_all_tables(self, text: str) -> List[Dict[str, Any]]:
        """
        从文本中提取所有表格
        
        Args:
            text: 包含表格的文本
            
        Returns:
            List[Dict]: 表格数据列表
        """
        tables = self.parse_markdown_table(text)
        
        # 清理每个表格的单元格内容
        for table in tables:
            for row in table.get('rows', []):
                if isinstance(row, dict):
                    for key in row:
                        row[key] = self.clean_table_cell(row[key])
        
        return tables

