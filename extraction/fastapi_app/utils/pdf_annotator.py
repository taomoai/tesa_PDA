"""
PDF 标注工具 - 在PDF上绘制提取结果的位置框
"""
import json
import logging
from typing import Dict, List, Optional, Any

import pdf2image
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)


class PDFAnnotator:
    """用于在PDF上标注提取结果位置的工具类"""

    def __init__(self, pdf_path: str):
        """
        初始化PDF标注器

        Args:
            pdf_path: PDF文件路径
        """
        self.pdf_path = pdf_path
        self.pdf_images = None
        self.page_count = 0

    def load_pdf_as_images(self, dpi: int = 200) -> Optional[List[Image.Image]]:
        """
        将PDF转换为图片列表

        Args:
            dpi: 转换分辨率（默认200，与提取过程保持一致）

        Returns:
            PIL Image对象列表，如果失败返回None
        """
        try:
            logger.info(f"Converting PDF to images at {dpi} DPI: {self.pdf_path}")

            self.pdf_images = pdf2image.convert_from_path(self.pdf_path, dpi=dpi)
            self.page_count = len(self.pdf_images)

            logger.info(f"✅ Successfully converted PDF to {self.page_count} images")
            return self.pdf_images
        except Exception as e:
            logger.error(f"Failed to convert PDF to images: {str(e)}")
            return None
    
    def draw_rectangles_on_image(
        self,
        image: Image.Image,
        coordinates_list: List[Dict[str, float]],
        color: tuple = (255, 0, 0),  # Red in RGB
        width: int = 3,
        label: Optional[str] = None
    ) -> Image.Image:
        """
        在图片上绘制矩形框

        注意：坐标已经是图片像素坐标，不需要缩放

        Args:
            image: PIL Image对象
            coordinates_list: 坐标列表，每个元素为 {"x": x, "y": y, "width": w, "height": h}
                             坐标已经是图片像素坐标
            color: 矩形颜色 (R, G, B)
            width: 线条宽度
            label: 可选的标签文本

        Returns:
            标注后的图片
        """
        draw = ImageDraw.Draw(image)

        for i, coords in enumerate(coordinates_list):
            try:
                x = coords.get('x', 0)
                y = coords.get('y', 0)
                w = coords.get('width', 0)
                h = coords.get('height', 0)

                # 坐标已经是图片像素坐标，直接使用
                x2 = x + w
                y2 = y + h

                # 绘制矩形框
                draw.rectangle([x, y, x2, y2], outline=color, width=width)

                # 如果提供了标签，绘制标签
                if label:
                    draw.text((x, y - 15), label, fill=color)

            except Exception as e:
                logger.warning(f"Failed to draw rectangle {i}: {str(e)}")
                continue

        return image
    
    def annotate_extraction_results(
        self,
        extraction_data: Dict[str, Any],
        output_path: str,
        color: tuple = (255, 0, 0)
    ) -> bool:
        """
        根据提取结果在PDF上标注位置
        
        Args:
            extraction_data: 提取结果JSON数据
            output_path: 输出PDF路径
            color: 标注颜色 (R, G, B)
            
        Returns:
            成功返回True，失败返回False
        """
        try:
            # 加载PDF为图片
            if not self.pdf_images:
                if not self.load_pdf_as_images():
                    return False
            
            # 收集所有需要标注的坐标信息
            annotations_by_page = {}
            
            def collect_coordinates(obj, path=""):
                """递归收集所有extraction_basis中的坐标信息"""
                if isinstance(obj, dict):
                    if "extraction_basis" in obj and isinstance(obj["extraction_basis"], list):
                        for item in obj["extraction_basis"]:
                            if isinstance(item, dict):
                                page_num = item.get("page_number")
                                coords = item.get("coordinates")
                                field_name = item.get("field_name", "")
                                value = item.get("value", "")
                                
                                if page_num and coords:
                                    page_idx = int(page_num) - 1  # Convert to 0-based index
                                    if page_idx not in annotations_by_page:
                                        annotations_by_page[page_idx] = []
                                    
                                    annotations_by_page[page_idx].append({
                                        "coordinates": coords,
                                        "field_name": field_name,
                                        "value": value
                                    })
                    
                    # 递归处理嵌套的字典
                    for key, value in obj.items():
                        if key != "extraction_basis":
                            collect_coordinates(value, f"{path}.{key}")
                
                elif isinstance(obj, list):
                    for item in obj:
                        collect_coordinates(item, path)
            
            collect_coordinates(extraction_data)
            
            logger.info(f"Found annotations for {len(annotations_by_page)} pages")
            
            # 在每一页上绘制标注
            annotated_images = []
            for page_idx, image in enumerate(self.pdf_images):
                if page_idx in annotations_by_page:
                    logger.info(f"Annotating page {page_idx + 1} with {len(annotations_by_page[page_idx])} annotations")

                    # 转换为RGB（如果需要）
                    if image.mode != 'RGB':
                        image = image.convert('RGB')

                    # 绘制所有标注
                    for annotation in annotations_by_page[page_idx]:
                        coords = annotation["coordinates"]
                        field_name = annotation["field_name"]

                        # 创建坐标列表
                        coords_list = [coords]
                        image = self.draw_rectangles_on_image(
                            image,
                            coords_list,
                            color=color,
                            width=3,
                            label=field_name
                        )

                annotated_images.append(image)
            
            # 保存为PDF
            if annotated_images:
                # 转换所有图片为RGB模式
                rgb_images = [img.convert('RGB') if img.mode != 'RGB' else img for img in annotated_images]
                
                # 保存为PDF
                rgb_images[0].save(
                    output_path,
                    save_all=True,
                    append_images=rgb_images[1:] if len(rgb_images) > 1 else []
                )
                logger.info(f"✅ Annotated PDF saved to: {output_path}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to annotate PDF: {str(e)}")
            return False


def annotate_pdf_from_extraction(
    pdf_path: str,
    extraction_json_path: str,
    output_pdf_path: str,
    color: tuple = (255, 0, 0)
) -> bool:
    """
    便捷函数：根据提取结果JSON文件标注PDF
    
    Args:
        pdf_path: 原始PDF文件路径
        extraction_json_path: 提取结果JSON文件路径
        output_pdf_path: 输出PDF文件路径
        color: 标注颜色 (R, G, B)，默认红色
        
    Returns:
        成功返回True，失败返回False
    """
    try:
        # 加载提取结果
        with open(extraction_json_path, 'r', encoding='utf-8') as f:
            extraction_data = json.load(f)
        
        # 创建标注器并执行标注
        annotator = PDFAnnotator(pdf_path)
        return annotator.annotate_extraction_results(
            extraction_data,
            output_pdf_path,
            color=color
        )
        
    except Exception as e:
        logger.error(f"Failed to annotate PDF from extraction: {str(e)}")
        return False

