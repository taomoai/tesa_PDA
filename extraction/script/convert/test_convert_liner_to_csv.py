#!/usr/bin/env python3
"""
Test file for converting extracted liner JSON to CSV format.

This test demonstrates the conversion of liner extraction data to CSV with the format:
Liner | Serial Number | Description | Limits / Requirements | Units | Test Methods

Example output:
22872-9xxxx-00 | 1.1.1 | Colour | havanna, printed with tesa Logo FINAT TLMI-No. 16 | | J0PM0041 comparison with reference sample
"""

import json
import csv
import pytest
from pathlib import Path
from typing import List, Dict, Any


def extract_items_from_section(section_data: Any, liner_nart: str) -> List[Dict[str, str]]:
    """
    Extract items from a technical data section.
    
    Args:
        section_data: Section data (can be list, dict, or None)
        liner_nart: Liner NART number
        
    Returns:
        List of row dictionaries with columns:
        - Liner: NART number
        - Serial Number: Item ID (e.g., 1.1.1)
        - Description: Property name
        - Limits / Requirements: Limits or requirements
        - Units: Unit of measurement
        - Test Methods: Test method description
    """
    rows = []
    
    if not section_data:
        return rows
    
    # Handle list of items
    if isinstance(section_data, list):
        for item in section_data:
            if isinstance(item, dict):
                # Combine limits and requirement fields
                limits_requirements = item.get('limits') or item.get('requirement', '')
                
                row = {
                    'Liner': liner_nart,
                    'Serial Number': item.get('id', ''),
                    'Description': item.get('property', ''),
                    'Limits / Requirements': limits_requirements,
                    'Units': item.get('unit', ''),
                    'Test Methods': item.get('test_method', '')
                }
                rows.append(row)
    
    # Handle dict (single item or nested structure)
    elif isinstance(section_data, dict):
        # Check if it's a single item with id, property, etc.
        if 'id' in section_data or 'property' in section_data:
            limits_requirements = section_data.get('limits') or section_data.get('requirement', '')
            
            row = {
                'Liner': liner_nart,
                'Serial Number': section_data.get('id', ''),
                'Description': section_data.get('property', ''),
                'Limits / Requirements': limits_requirements,
                'Units': section_data.get('unit', ''),
                'Test Methods': section_data.get('test_method', '')
            }
            rows.append(row)
    
    return rows


def convert_liner_json_to_csv(json_file: Path, output_csv: Path) -> int:
    """
    Convert a single liner JSON file to CSV format.
    
    Args:
        json_file: Path to the extracted JSON file
        output_csv: Path to the output CSV file
        
    Returns:
        Number of rows written
    """
    print(f"Processing: {json_file.name}")
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Get NART number from summary_info
        summary_info = data.get('summary_info', {})
        liner_nart = (
            summary_info.get('tesa_nart') or 
            summary_info.get('tesaNART') or 
            summary_info.get('nart') or
            json_file.stem.split('_')[0]  # Fallback to filename
        )
        
        # Get technical_data section
        technical_data = data.get('technical_data', {})
        
        if not technical_data:
            print(f"  ⚠️  No technical_data found in {json_file.name}")
            return 0
        
        all_rows = []
        
        # Process each section in order
        sections = [
            'sensory_characteristics',
            'sensoryCharacteristics',  # Alternative naming
            'physical_data',
            'physicalData',  # Alternative naming
            'silicone_coating_weight',
            'siliconeCoatingWeight',  # Alternative naming
            'release_force',
            'releaseForce',  # Alternative naming
            'loss_of_peel_adhesion',
            'lossOfPeelAdhesion',  # Alternative naming
            'anchorage_of_print_ink',
            'anchorageOfPrintInk'  # Alternative naming
        ]
        
        for section_name in sections:
            section_data = technical_data.get(section_name)
            if section_data:
                rows = extract_items_from_section(section_data, liner_nart)
                all_rows.extend(rows)
                print(f"  ✅ {section_name}: {len(rows)} items")
        
        # Write to CSV
        if all_rows:
            fieldnames = ['Liner', 'Serial Number', 'Description', 'Limits / Requirements', 'Units', 'Test Methods']
            
            with open(output_csv, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(all_rows)
            
            print(f"  📊 Total items extracted: {len(all_rows)}")
            print(f"  💾 CSV written to: {output_csv}")
            return len(all_rows)
        else:
            print(f"  ⚠️  No data extracted")
            return 0
        
    except Exception as e:
        print(f"  ❌ Error processing {json_file.name}: {e}")
        return 0


def test_convert_single_liner():
    """Test converting a single liner JSON file to CSV."""
    # Find a sample liner file
    liner_dir = Path('output')
    
    if not liner_dir.exists():
        pytest.skip("No liner output directory found")
    
    json_files = list(liner_dir.glob('*_extracted.json'))
    
    if not json_files:
        pytest.skip("No extracted JSON files found")
    
    # Use the first file as test
    test_file = json_files[0]
    output_csv = Path('tests/output/test_liner_output.csv')
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    
    # Convert to CSV
    row_count = convert_liner_json_to_csv(test_file, output_csv)
    
    # Verify output
    assert output_csv.exists(), "CSV file should be created"
    assert row_count > 0, "Should have extracted at least one row"
    
    # Read and verify CSV structure
    with open(output_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        
        assert len(rows) == row_count, "Row count should match"
        
        # Verify columns
        expected_columns = ['Liner', 'Serial Number', 'Description', 'Limits / Requirements', 'Units', 'Test Methods']
        assert reader.fieldnames == expected_columns, "Columns should match expected format"
        
        # Verify first row has data
        if rows:
            first_row = rows[0]
            assert first_row['Liner'], "Liner field should not be empty"
            assert first_row['Serial Number'], "Serial Number field should not be empty"
            assert first_row['Description'], "Description field should not be empty"
            
            print(f"\n✅ Sample row:")
            print(f"  Liner: {first_row['Liner']}")
            print(f"  Serial Number: {first_row['Serial Number']}")
            print(f"  Description: {first_row['Description']}")
            print(f"  Limits / Requirements: {first_row['Limits / Requirements']}")
            print(f"  Units: {first_row['Units']}")
            print(f"  Test Methods: {first_row['Test Methods']}")


def test_convert_specific_liner_22872():
    """Test converting the specific liner file mentioned in the example (22872)."""
    liner_file = Path('output/liner/22872 V08_extracted.json')
    
    if not liner_file.exists():
        pytest.skip(f"Test file {liner_file} not found")
    
    output_csv = Path('tests/output/test_liner_22872.csv')
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    
    # Convert to CSV
    row_count = convert_liner_json_to_csv(liner_file, output_csv)
    
    assert row_count > 0, "Should have extracted rows"
    
    # Read and verify the specific example row
    with open(output_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        
        # Find the row with Serial Number 1.1.1 (Colour)
        colour_row = next((row for row in rows if row['Serial Number'] == '1.1.1'), None)
        
        assert colour_row is not None, "Should find row with Serial Number 1.1.1"
        assert colour_row['Liner'] == '22872-9xxxx-00', "Liner should be 22872-9xxxx-00"
        assert colour_row['Description'] == 'Colour', "Description should be Colour"
        assert 'havanna' in colour_row['Limits / Requirements'], "Should contain 'havanna'"
        assert 'tesa Logo' in colour_row['Limits / Requirements'], "Should contain 'tesa Logo'"
        assert 'J0PM0041' in colour_row['Test Methods'], "Test method should contain J0PM0041"
        
        print(f"\n✅ Verified example row:")
        print(f"  {colour_row['Liner']} | {colour_row['Serial Number']} | {colour_row['Description']} | {colour_row['Limits / Requirements']} | {colour_row['Units']} | {colour_row['Test Methods']}")


def test_batch_convert_all_liners():
    """Test converting all liner JSON files to a single CSV."""
    liner_dir = Path('output')
    
    if not liner_dir.exists():
        pytest.skip("No liner output directory found")
    
    json_files = list(liner_dir.glob('*_extracted.json'))
    
    if not json_files:
        pytest.skip("No extracted JSON files found")
    
    output_csv = Path('tests/output/all_liners.csv')
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    
    # Process all files
    all_rows = []
    
    for json_file in sorted(json_files):
        print(f"\nProcessing: {json_file.name}")
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            summary_info = data.get('summary_info', {})
            liner_nart = (
                summary_info.get('tesa_nart') or 
                summary_info.get('tesaNART') or 
                summary_info.get('nart') or
                json_file.stem.split('_')[0]
            )
            
            technical_data = data.get('technical_data', {})
            
            if technical_data:
                sections = [
                    'sensory_characteristics', 'sensoryCharacteristics',
                    'physical_data', 'physicalData',
                    'silicone_coating_weight', 'siliconeCoatingWeight',
                    'release_force', 'releaseForce',
                    'loss_of_peel_adhesion', 'lossOfPeelAdhesion',
                    'anchorage_of_print_ink', 'anchorageOfPrintInk'
                ]
                
                for section_name in sections:
                    section_data = technical_data.get(section_name)
                    if section_data:
                        rows = extract_items_from_section(section_data, liner_nart)
                        all_rows.extend(rows)
                
                print(f"  ✅ Extracted {len([r for r in all_rows if r['Liner'] == liner_nart])} items")
        
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    # Write all rows to CSV
    if all_rows:
        fieldnames = ['Liner', 'Serial Number', 'Description', 'Limits / Requirements', 'Units', 'Test Methods']
        
        with open(output_csv, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_rows)
        
        print(f"\n✅ Batch conversion completed!")
        print(f"  📊 Total rows: {len(all_rows)}")
        print(f"  📄 Output file: {output_csv}")
        
        assert len(all_rows) > 0, "Should have extracted at least one row"
        assert output_csv.exists(), "CSV file should be created"


if __name__ == '__main__':
    print("\n" + "=" * 80)
    print("Test 3: Batch convert all liners")
    print("=" * 80)
    test_batch_convert_all_liners()

