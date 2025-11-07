import logging
from typing import Dict, Any, List

import pdfplumber
from pdfplumber.table import Table

import flask_app.modules.common_service.pdf.controller as pdf_controller

logger = logging.getLogger(__name__)

# 抑制 pdfplumber 和相关库的详细调试日志
logging.getLogger('pdfplumber').setLevel(logging.WARNING)
logging.getLogger('pdfminer').setLevel(logging.WARNING)
logging.getLogger('pdf2image').setLevel(logging.WARNING)

class PDFFileParser():
    """Parser for PDF files."""
    
    def __init__(self):
        # 技术数据表常见的表头
        self.tech_data_headers = [
            'Classification', 'Unit', 'Typical Values', 'Tolerance', 'Remarks',
            'Property', 'Test Method', 'Value', 'Specification',
            '项目', '单位', '标准值', '公差', '备注'
        ]
        
    def _is_tech_data_table(self, table: List[List[str]]) -> bool:
        """
        判断是否为技术数据表
        """
        if not table or not table[0]:
            return False
            
        headers = [str(h).strip() if h else '' for h in table[0]]
        # 检查表头是否包含技术数据表的特征
        return any(header in headers for header in self.tech_data_headers)
        
    def _clean_table_cell(self, cell: str) -> str:
        """
        清理表格单元格内容
        """
        if cell is None:
            return ''
        cell = str(cell).strip()
        # 修复常见的OCR错误
        cell = cell.replace('JCPM', 'J0PM')  # 修复方法代码

        # 智能修复角度符号 - 只在特定上下文中替换 'o' 为 '°'
        # 匹配数字后跟 'o' 的情况，如 "180o" -> "180°"
        import re
        cell = re.sub(r'(\d+)o\b', r'\1°', cell)  # 数字后的单独 'o'
        cell = re.sub(r'(\d+)o([A-Z])', r'\1°\2', cell)  # 数字后的 'o' 跟大写字母

        cell = cell.replace('㎡', 'm²')      # 统一单位表示
        cell = cell.replace('μm', 'μm')      # 统一单位表示
        # 移除多余的换行
        cell = ' '.join(cell.split())
        return cell
        
    def _process_table_rows(self, table: List[List[str]], headers: List[str]) -> List[Dict[str, str]]:
        """
        处理整个表格的行，处理跨行的备注信息
        """
        if not table or len(table) <= 1:  # 空表格或只有表头
            return []
            
        data = []
        current_remarks = None
        rows = table[1:]  # 跳过表头
        
        for i, row in enumerate(rows):
            if not row or not any(self._clean_table_cell(cell) for cell in row):  # 跳过空行
                continue
                
            # 清理每个单元格
            cleaned_cells = [self._clean_table_cell(cell) for cell in row]
            row_dict = {}
            remarks = []
            
            # 特殊处理带*号的行
            is_special_row = any(cell.startswith('*') for cell in cleaned_cells if cell)
            
            # 检查当前行是否包含新的备注信息
            remarks_index = headers.index('Remarks') if 'Remarks' in headers else -1
            if remarks_index >= 0 and remarks_index < len(cleaned_cells):
                current_cell = cleaned_cells[remarks_index]
                if current_cell:
                    current_remarks = current_cell
            
            for j, header in enumerate(headers):
                if j < len(cleaned_cells):
                    cell_value = cleaned_cells[j]
                    
                    # 处理带*号的特殊行
                    if is_special_row and j == 0 and cell_value.startswith('*'):
                        cell_value = cell_value.lstrip('*').strip()
                    
                    # 如果是备注列且为空，使用之前的备注
                    if header == 'Remarks' and not cell_value and current_remarks:
                        cell_value = current_remarks
                    
                    # 处理测试方法和代码
                    if cell_value and any(method in cell_value for method in ['ASTM', 'JIS', 'J0PM']):
                        if header != 'Remarks':
                            if 'Remarks' in headers:
                                remarks.append(cell_value)
                                continue
                    
                    # 处理带括号的代码和单位
                    if cell_value:
                        # 处理括号中的信息
                        if '(' in cell_value and ')' in cell_value:
                            main_value = cell_value.split('(')[0].strip()
                            code = cell_value[cell_value.find('('):].strip()
                            if main_value:
                                if header == 'Classification':
                                    row_dict[header] = cell_value  # 保留完整的分类名称
                                else:
                                    row_dict[header] = main_value
                                    if code not in remarks:
                                        remarks.append(code)
                        else:
                            row_dict[header] = cell_value
                    
                    # 特殊处理单位列
                    if header == 'Unit' and not cell_value and j + 1 < len(cleaned_cells):
                        next_cell = cleaned_cells[j + 1]
                        # 检查下一个单元格是否包含单位信息
                        if next_cell and any(unit in next_cell.lower() for unit in ['min', 'hr', '℃', 'g', 'μm', 'n/cm', '%']):
                            row_dict[header] = next_cell
                            cleaned_cells[j + 1] = ''  # 清空已使用的单位信息
            
            # 合并所有备注信息
            if remarks and 'Remarks' in headers:
                row_dict['Remarks'] = ' '.join(remarks) if not current_remarks else current_remarks
            elif current_remarks and 'Remarks' in headers:
                row_dict['Remarks'] = current_remarks
                
            if row_dict:
                data.append(row_dict)
                
        return data
        
    def _extract_table_with_settings(self, page) -> List[Table]:
        """
        使用优化的设置提取表格
        """
        # 尝试不同的表格提取设置
        settings = [
            # 默认设置
            {
                'vertical_strategy': 'text',
                'horizontal_strategy': 'text',
                'intersection_x_tolerance': 5,  # 增加容差
                'intersection_y_tolerance': 5,
                'text_x_tolerance': 5,  # 添加文本容差
                'text_y_tolerance': 3
            },
            # 严格设置
            {
                'vertical_strategy': 'lines',
                'horizontal_strategy': 'lines',
                'explicit_vertical_lines': [],
                'explicit_horizontal_lines': [],
                'snap_tolerance': 3,
                'join_tolerance': 3,
                'edge_min_length': 3,
                'min_words_vertical': 3
            },
            # 混合设置
            {
                'vertical_strategy': 'text',
                'horizontal_strategy': 'lines',
                'intersection_x_tolerance': 8,  # 增加容差
                'intersection_y_tolerance': 5,
                'snap_tolerance': 5,
                'join_tolerance': 5,
                'text_x_tolerance': 8,  # 添加文本容差
                'text_y_tolerance': 3
            }
        ]
        
        for setting in settings:
            try:
                # 使用 find_tables 而不是 extract_tables
                tables_found = page.find_tables(table_settings=setting)
                if tables_found:
                    # 从找到的表格中提取数据
                    tables = [table.extract() for table in tables_found]
                    if tables and any(self._is_tech_data_table(table) for table in tables):
                        return tables
            except Exception as e:
                logger.warning(f"表格提取尝试失败，尝试下一个设置: {str(e)}")
                continue
                
        # 如果所有设置都失败，使用默认设置
        try:
            return page.extract_tables()
        except Exception as e:
            logger.error(f"默认表格提取失败: {str(e)}")
            return []
        
    def _process_text_blocks(self, blocks: List[Dict]) -> List[Dict]:
        """
        优化的文本块处理逻辑
        """
        if not blocks:
            return []
            
        processed = []
        current = blocks[0]
        
        for next_block in blocks[1:]:
            # 更精确的合并条件
            same_paragraph = (
                # 垂直距离检查
                abs(next_block['y'] - (current['y'] + current['height'])) < min(current['height'], next_block['height']) * 1.2
                # 水平对齐检查
                and (
                    abs(next_block['x'] - current['x']) < current['width'] * 0.1  # 左对齐
                    or abs((next_block['x'] + next_block['width']) - (current['x'] + current['width'])) < current['width'] * 0.1  # 右对齐
                )
                # 字体检查
                and next_block['font'] == current['font']
                and abs(next_block['size'] - current['size']) <= 1
            )
            
            if same_paragraph:
                # 智能空格添加
                space = ' ' if not (current['text'].endswith('-') or current['text'].endswith('/')) else ''
                current['text'] = f"{current['text']}{space}{next_block['text']}"
                current['height'] = next_block['y'] + next_block['height'] - current['y']
                current['width'] = max(current['width'], next_block['width'])
            else:
                processed.append(current)
                current = next_block
                
        processed.append(current)
        return processed
        
    def parse(self, file_url: str) -> Dict[str, Any]:
        """
        Parse PDF file and extract content.

        Args:
            file_url: The URL of the PDF file to parse
            product: Optional OqcProduct instance containing product information

        Returns:
            Dict containing the extracted content with page_count
        """
        try:
            logger.info(f"开始解析PDF文件: {file_url}")

            with pdfplumber.open(file_url) as pdf:
                # 检查页数限制（PDF 最多 4 页）
                page_count = len(pdf.pages)
                if page_count > 4:
                    error_msg = f"PDF 文档页数超过限制。当前页数: {page_count}, 最大允许页数: 4"
                    logger.error(error_msg)
                    return {
                        "type": "pdf",
                        "error": error_msg,
                        "page_count": page_count,
                        "max_pages": 4,
                        "is_page_limit_exceeded": True
                    }

                logger.info(f"PDF 文档页数检查通过: {page_count} 页")

                all_text = []
                tables = []

                for i, page in enumerate(pdf.pages):
                    # 获取页面尺寸
                    page_width = page.width
                    page_height = page.height
                    
                    # 提取所有文本块，包含位置信息
                    words = page.extract_words(
                        x_tolerance=3,
                        y_tolerance=3,
                        keep_blank_chars=True,  # 保留空白字符以便更好地处理格式
                        use_text_flow=True,
                        horizontal_ltr=True,
                        vertical_ttb=True,
                        extra_attrs=['fontname', 'size']
                    )
                    
                    # 按垂直位置分组
                    y_groups = {}
                    for word in words:
                        y_key = round(word['top'])
                        if y_key not in y_groups:
                            y_groups[y_key] = []
                        y_groups[y_key].append(word)
                    
                    # 处理每个垂直位置的词
                    text_blocks = []
                    for y_key in sorted(y_groups.keys()):
                        line_words = sorted(y_groups[y_key], key=lambda w: w['x0'])
                        
                        # 智能空格处理
                        line_text_parts = []
                        prev_word = None
                        
                        for word in line_words:
                            if prev_word:
                                gap = word['x0'] - prev_word['x1']
                                # 根据上下文判断是否需要添加空格
                                if gap > word['size'] * 1.5:
                                    # 检查是否是特殊情况（如单位、括号等）
                                    if not (prev_word['text'].endswith(('(', '-', '/', '°'))
                                            or word['text'].startswith((')', '°', '%'))):
                                        line_text_parts.append(' ' * (int(gap / word['size'])))
                            line_text_parts.append(word['text'])
                            prev_word = word
                        
                        line_text = ''.join(line_text_parts)
                        text_blocks.append({
                            'text': line_text,
                            'y': y_key,
                            'x': line_words[0]['x0'],
                            'width': line_words[-1]['x1'] - line_words[0]['x0'],
                            'height': line_words[0]['height'],
                            'font': line_words[0].get('fontname', ''),
                            'size': line_words[0].get('size', 0)
                        })
                    
                    # 使用优化的文本块处理
                    processed_blocks = self._process_text_blocks(text_blocks)
                    page_text = '\n'.join(block['text'] for block in processed_blocks)
                    all_text.append(page_text)
                    
                    # 使用优化的表格提取
                    page_tables = self._extract_table_with_settings(page)
                    if page_tables:
                        for j, table in enumerate(page_tables):
                            if table and len(table) > 0:
                                # 清理和标准化表格数据
                                headers = [self._clean_table_cell(h) for h in table[0]]
                                data = self._process_table_rows(table, headers)
                                
                                if data:  # 只添加非空表格
                                    tables.append({
                                        "page": i+1,
                                        "table_index": j,
                                        "data": data,
                                        "is_tech_data": self._is_tech_data_table(table)
                                    })
            
            # 检查提取结果
            text_content = "\n\n".join(all_text)
            if not text_content.strip():
                # 尝试OCR
                pdf2Image = pdf_controller.PDFController()
                with open(file_url, 'rb') as fileObj:
                    images = pdf2Image.convert_pdf_to_images(fileObj)
                return {
                    "type": "images",
                    "image_urls": images.get("image_urls")
                }
            
            return {
                "type": "pdf",
                "text": text_content,
                "tables": tables,
                "page_count": page_count,
                "is_page_limit_exceeded": False
            }
                
        except Exception as pdf_error:
            logger.error(f"PDF处理错误: {str(pdf_error)}", exc_info=True)
            return {"error": f"PDF文件处理失败: {str(pdf_error)}"} 