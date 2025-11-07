#!/usr/bin/env python3
"""
将 backing 类型的 extracted JSON 文件转换为 CSV 表格格式

输出格式:
Backing | Property | Test Figures / Tolerances | tesa + DIN/ISO Standard

使用方法:
    python tests/convert_backing_to_csv.py                    # 转换 output/ 目录下所有 extracted.json 文件
    python tests/convert_backing_to_csv.py file1.json         # 转换指定文件
"""

import json
import csv
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional


def format_test_figures(value: Optional[str], tolerance: Optional[str], unit: Optional[str]) -> str:
    """
    格式化测试数据为 "value ± tolerance unit" 格式
    
    Examples:
        format_test_figures("12", "±1.5", "µm") -> "12 ± 1.5 µm"
        format_test_figures("≥16", None, "N/cm") -> "≥16 N/cm"
        format_test_figures("Like reference", None, None) -> "Like reference"
    """
    if not value:
        return ""
    
    parts = [value]
    
    if tolerance:
        parts.append(tolerance)
    
    if unit:
        parts.append(unit)
    
    return " ".join(parts)


def extract_backing_data(json_file: Path) -> List[Dict[str, Any]]:
    """
    从 backing 类型的 extracted JSON 文件中提取表格数据
    
    返回格式:
    [
        {
            'backing': 'PETDH302LWHITED12',
            'property': 'Thickness',
            'test_figures_tolerances': '12 ± 1.5 µm',
            'tesa_standard': 'J0PMC002'
        },
        ...
    ]
    """
    rows = []
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 获取 backing 名称（使用 internal_name 或 trade_name_of_product）
        product_info = data.get('product_info', {})
        backing_name = (
            product_info.get('internal_name') or 
            product_info.get('trade_name_of_product') or 
            product_info.get('tesa_nart') or
            json_file.stem.replace('_extracted', '')
        )
        
        # 获取 physical_and_chemical_data
        physical_data = data.get('physical_and_chemical_data', {})
        
        # 处理新格式（items 字段）和旧格式（直接的列表或其他字段名）
        items = None
        if isinstance(physical_data, dict):
            # 尝试多个可能的字段名
            items = (
                physical_data.get('items') or 
                physical_data.get('physical_and_chemical_data') or
                physical_data.get('physicalAndChemicalData')
            )
        elif isinstance(physical_data, list):
            items = physical_data
        
        if not items:
            print(f"  ⚠️  No physical_and_chemical_data found in {json_file.name}")
            return rows
        
        # 处理每个属性
        for item in items:
            if not isinstance(item, dict):
                continue
            
            property_name = item.get('property', '')
            if not property_name:
                continue
            
            # 格式化 tesa 测试数据
            tesa_test_figures = format_test_figures(
                item.get('tesa_test_figures_value'),
                item.get('tesa_test_figures_tolerance'),
                item.get('tesa_test_figures_unit')
            )
            
            # 获取 tesa 标准
            tesa_standard = item.get('tesa_standard', '')
            
            # 创建行数据
            row = {
                'backing': backing_name,
                'property': property_name,
                'test_figures_tolerances': tesa_test_figures,
                'tesa_standard': tesa_standard
            }
            rows.append(row)
        
        print(f"  ✅ Extracted {len(rows)} properties from {json_file.name}")
        
    except Exception as e:
        print(f"  ❌ Error processing {json_file.name}: {e}")
    
    return rows


def find_backing_files(search_dir: Path) -> List[Path]:
    """
    查找 backing 类型的 extracted JSON 文件

    Args:
        search_dir: 搜索目录（只搜索该目录，不递归子目录）

    Returns:
        找到的文件列表
    """
    # 只搜索 output 目录下的文件，不递归子目录
    files = sorted(search_dir.glob('*_extracted.json'))
    return files


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='Convert backing extracted JSON files to CSV format'
    )
    parser.add_argument(
        'files',
        nargs='*',
        help='Specific JSON files to convert (optional)'
    )
    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Output CSV file path (default: output/backing_data_summary.csv)'
    )

    args = parser.parse_args()

    output_dir = Path('output')

    # 确定要处理的文件
    if args.files:
        # 处理指定的文件
        extracted_files = []
        for file_path in args.files:
            path = Path(file_path)
            if not path.exists():
                # 尝试在 output 目录中查找
                path = output_dir / file_path

            if path.exists():
                extracted_files.append(path)
            else:
                print(f"⚠️  File not found: {file_path}")
    else:
        # 查找 output 目录下的所有 extracted JSON 文件
        extracted_files = find_backing_files(output_dir)
    
    if not extracted_files:
        print("❌ No backing extracted JSON files found!")
        print("\nTip: Make sure you have run the backing extraction first:")
        print("  python tests/test_batch_backing_extraction.py")
        return
    
    print(f"📁 Found {len(extracted_files)} backing extracted JSON file(s)\n")
    
    # 提取所有数据
    all_rows = []
    for json_file in extracted_files:
        print(f"Processing {json_file.name}...")
        rows = extract_backing_data(json_file)
        all_rows.extend(rows)
    
    # 写入 CSV
    if all_rows:
        # 确定输出文件路径
        if args.output:
            csv_output = Path(args.output)
        else:
            csv_output = output_dir / 'backing_data_summary.csv'
        
        # 确保输出目录存在
        csv_output.parent.mkdir(parents=True, exist_ok=True)
        
        fieldnames = [
            'backing',
            'property',
            'test_figures_tolerances',
            'tesa_standard'
        ]
        
        # 使用 UTF-8-BOM 编码，这样 Excel 会正确识别特殊字符
        with open(csv_output, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            # 写入表头（使用更友好的列名）
            writer.writerow({
                'backing': 'Backing',
                'property': 'Property',
                'test_figures_tolerances': 'Test Figures / Tolerances',
                'tesa_standard': 'tesa + DIN/ISO Standard'
            })
            
            writer.writerows(all_rows)
        
        print(f"\n✅ CSV file generated: {csv_output}")
        print(f"   Total rows: {len(all_rows)}")
        print(f"   File size: {csv_output.stat().st_size / 1024:.2f} KB")
        print(f"\n💡 You can open this file in Excel or any spreadsheet application")
    else:
        print("\n❌ No data extracted!")


if __name__ == '__main__':
    main()

