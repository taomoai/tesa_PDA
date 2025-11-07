#!/usr/bin/env python3
"""
从所有extracted json文件中提取product维度的数据，生成CSV文件
"""

import json
import csv
from pathlib import Path
from typing import List, Dict, Any

def extract_product_spec_from_filename(filename: str) -> str:
    """
    从文件名提取 Product Specification
    例如: E-FER-68735-70000-40-02_extracted.json -> E-FER-68735-70000-40
    """
    # 移除 _extracted.json 后缀
    base_name = filename.replace('_extracted.json', '')

    # 移除最后的 -XX (版本号)
    parts = base_name.split('-')
    if len(parts) >= 4:
        # 保留前4部分: E-FER-XXXXX-XXXXX-XX
        return '-'.join(parts[:-1])

    return base_name

def extract_product_data(json_file: Path) -> List[Dict[str, Any]]:
    """
    从单个extracted json文件中提取product维度的数据

    返回格式:
    [
        {
            'Product Spec': '62565-70000-57',
            'No.': '01',
            'Item Description': 'Total weight after 1st coating, without liner',
            'Item No.': 'P4079',
            'Unit': 'g/m²',
            'Target Value': '37 ± 5',
            'Test Method': 'J0PM0005',
            'Test Type': 'I'
        },
        ...
    ]
    """
    rows = []

    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 获取NART
        nart = data.get('document_header', {}).get('nart', '')

        # 获取所有properties
        properties = data.get('characteristics_and_properties', {}).get('properties', [])

        # 为每个property创建一行
        for prop in properties:
            row = {
                'Product Spec': nart,
                'No.': prop.get('no', ''),
                'Item Description': prop.get('item', ''),
                'Item No.': prop.get('item_no', ''),
                'Unit': prop.get('unit', ''),
                'Target Value': prop.get('target_value_with_unit', ''),
                'Test Method': prop.get('test_method', ''),
                'Test Type': prop.get('test_type', '')
            }
            rows.append(row)

    except Exception as e:
        print(f"Error processing {json_file}: {e}")

    return rows

def extract_component_data(json_file: Path) -> List[Dict[str, Any]]:
    """
    从单个extracted json文件中提取component维度的数据

    返回格式:
    [
        {
            'Product Specification': 'E-FER-68735-70000-40',
            'block identification': 'product_identification_value',
            'NART': 'nart_value'
        },
        ...
    ]
    """
    rows = []

    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 从文件名提取 Product Specification
        filename = json_file.name
        product_spec = extract_product_spec_from_filename(filename)

        # 获取所有component groups
        product_components = data.get('product_components', {})
        component_groups = product_components.get('component_groups', [])

        # 遍历每个component group
        for group in component_groups:
            components = group.get('components', [])

            # 为每个component创建一行
            for comp in components:
                # 只有当 product_identification 和 nart 都不为空时才添加
                product_id = comp.get('product_identification', '').strip()
                nart = comp.get('nart', '').strip()

                if product_id and nart:
                    row = {
                        'Product Specification': product_spec,
                        'block identification': product_id,
                        'NART': nart
                    }
                    rows.append(row)

    except Exception as e:
        print(f"Error processing {json_file}: {e}")

    return rows

def main():
    """主函数"""
    output_dir = Path('output')
    csv_properties_output = output_dir / 'product_properties_summary.csv'
    csv_components_output = output_dir / 'product_components_summary.csv'

    # 找到所有extracted json文件
    extracted_files = sorted(output_dir.glob('*_extracted.json'))
    print(f"Found {len(extracted_files)} extracted JSON files")

    # ========== 生成 Properties CSV ==========
    print("\n=== Generating Properties CSV ===")
    all_properties_rows = []
    for json_file in extracted_files:
        print(f"Processing {json_file.name}...")
        rows = extract_product_data(json_file)
        all_properties_rows.extend(rows)
        print(f"  -> Extracted {len(rows)} properties")

    # 写入Properties CSV
    if all_properties_rows:
        fieldnames = [
            'Product Spec',
            'No.',
            'Item Description',
            'Item No.',
            'Unit',
            'Target Value',
            'Test Method',
            'Test Type'
        ]

        # 使用UTF-8-BOM编码，这样Excel会正确识别特殊字符如±
        with open(csv_properties_output, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_properties_rows)

        print(f"\n✅ Properties CSV file generated: {csv_properties_output}")
        print(f"Total rows: {len(all_properties_rows)}")
        print(f"File size: {csv_properties_output.stat().st_size / 1024:.2f} KB")
    else:
        print("No properties data extracted!")

    # ========== 生成 Components CSV ==========
    print("\n=== Generating Components CSV ===")
    all_components_rows = []
    for json_file in extracted_files:
        print(f"Processing {json_file.name}...")
        rows = extract_component_data(json_file)
        all_components_rows.extend(rows)
        print(f"  -> Extracted {len(rows)} components")

    # 写入Components CSV
    if all_components_rows:
        fieldnames = [
            'Product Specification',
            'block identification',
            'NART'
        ]

        # 使用UTF-8-BOM编码，这样Excel会正确识别特殊字符如±
        with open(csv_components_output, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_components_rows)

        print(f"\n✅ Components CSV file generated: {csv_components_output}")
        print(f"Total rows: {len(all_components_rows)}")
        print(f"File size: {csv_components_output.stat().st_size / 1024:.2f} KB")
    else:
        print("No components data extracted!")

    print(f"\nEncoding: UTF-8 with BOM (compatible with Excel)")

if __name__ == '__main__':
    main()

