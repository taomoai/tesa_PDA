"""
CSV generator for EFERSPEC product properties.
Generates CSV files with proper column headers and formatting.
"""

import json
import csv
import os
from pathlib import Path
from typing import List, Dict, Any
from loguru import logger


class ProductPropertiesCSVGenerator:
    """Generate CSV files for product properties from extracted JSON data."""
    
    # CSV column headers
    CSV_HEADERS = [
        "Product Spec",
        "No.",
        "Item Description",
        "Item No.",
        "Unit",
        "Target Value",
        "Test Method",
        "Test Type"
    ]
    
    def __init__(self, output_dir: str = "output/product"):
        """
        Initialize the CSV generator.
        
        Args:
            output_dir: Directory to save CSV files
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
    
    def extract_nart_from_filename(self, filename: str) -> str:
        """
        Extract NART (Product Spec) from filename.
        
        Example: E-FER-68542-70000-20-06_extracted.json -> 68542-70000-20
        
        Args:
            filename: The extracted JSON filename
            
        Returns:
            NART string (e.g., '68542-70000-20')
        """
        # Remove extension and suffix
        base_name = filename.replace("_extracted.json", "").replace("_pipeline_summary.json", "")
        
        # Remove prefix (E-FER-)
        if base_name.startswith("E-FER-"):
            base_name = base_name[6:]  # Remove "E-FER-"
        
        # Extract NART (first three parts: XXXXX-XXXXX-XX)
        parts = base_name.split("-")
        if len(parts) >= 3:
            nart = "-".join(parts[:3])
            return nart
        
        return base_name
    
    def load_extracted_data(self, json_file: str) -> Dict[str, Any]:
        """
        Load extracted data from JSON file.
        
        Args:
            json_file: Path to the extracted JSON file
            
        Returns:
            Extracted data dictionary
        """
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load JSON file {json_file}: {str(e)}")
            return {}
    
    def convert_to_csv_rows(self, nart: str, extracted_data: Dict[str, Any]) -> List[Dict[str, str]]:
        """
        Convert extracted data to CSV rows.
        
        Args:
            nart: Product Spec (NART)
            extracted_data: Extracted data from JSON
            
        Returns:
            List of dictionaries representing CSV rows
        """
        rows = []
        
        # Get characteristics_and_properties section
        characteristics = extracted_data.get("characteristics_and_properties", {})
        properties = characteristics.get("properties", [])
        
        for prop in properties:
            row = {
                "Product Spec": nart,
                "No.": prop.get("no", ""),
                "Item Description": prop.get("item", ""),
                "Item No.": prop.get("item_no", ""),
                "Unit": prop.get("unit", ""),
                "Target Value": prop.get("target_value_with_unit", ""),
                "Test Method": prop.get("test_method", ""),
                "Test Type": prop.get("test_type", "")
            }
            rows.append(row)
        
        return rows
    
    def generate_csv_from_json(self, json_file: str, output_csv: str = None) -> str:
        """
        Generate CSV file from extracted JSON file.
        
        Args:
            json_file: Path to the extracted JSON file
            output_csv: Output CSV file path (optional)
            
        Returns:
            Path to the generated CSV file
        """
        # Extract NART from filename
        filename = os.path.basename(json_file)
        nart = self.extract_nart_from_filename(filename)
        
        # Load extracted data
        extracted_data = self.load_extracted_data(json_file)
        
        # Convert to CSV rows
        rows = self.convert_to_csv_rows(nart, extracted_data)
        
        if not rows:
            logger.warning(f"No properties found in {json_file}")
            return None
        
        # Determine output file path
        if output_csv is None:
            output_csv = os.path.join(self.output_dir, f"{nart}_properties.csv")
        
        # Write CSV file
        try:
            with open(output_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.CSV_HEADERS, delimiter='|')
                writer.writeheader()
                writer.writerows(rows)
            
            logger.info(f"Generated CSV: {output_csv} ({len(rows)} rows)")
            return output_csv
        
        except Exception as e:
            logger.error(f"Failed to write CSV file {output_csv}: {str(e)}")
            return None
    
    def generate_combined_csv(self, json_files: List[str], output_csv: str = None) -> str:
        """
        Generate a combined CSV file from multiple extracted JSON files.
        
        Args:
            json_files: List of paths to extracted JSON files
            output_csv: Output CSV file path (optional)
            
        Returns:
            Path to the generated CSV file
        """
        all_rows = []
        
        for json_file in json_files:
            if not os.path.exists(json_file):
                logger.warning(f"JSON file not found: {json_file}")
                continue
            
            # Extract NART from filename
            filename = os.path.basename(json_file)
            nart = self.extract_nart_from_filename(filename)
            
            # Load extracted data
            extracted_data = self.load_extracted_data(json_file)
            
            # Convert to CSV rows
            rows = self.convert_to_csv_rows(nart, extracted_data)
            all_rows.extend(rows)
        
        if not all_rows:
            logger.warning("No properties found in any JSON files")
            return None
        
        # Determine output file path
        if output_csv is None:
            output_csv = os.path.join(self.output_dir, "product_properties_combined.csv")
        
        # Write CSV file
        try:
            with open(output_csv, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.CSV_HEADERS, delimiter='|')
                writer.writeheader()
                writer.writerows(all_rows)
            
            logger.info(f"Generated combined CSV: {output_csv} ({len(all_rows)} rows)")
            return output_csv
        
        except Exception as e:
            logger.error(f"Failed to write CSV file {output_csv}: {str(e)}")
            return None
    
    def generate_all_csvs(self) -> Dict[str, str]:
        """
        Generate CSV files for all extracted JSON files in the output directory.
        
        Returns:
            Dictionary mapping NART to CSV file path
        """
        results = {}
        json_files = list(Path(self.output_dir).glob("*_extracted.json"))
        
        logger.info(f"Found {len(json_files)} extracted JSON files")
        
        for json_file in json_files:
            try:
                csv_file = self.generate_csv_from_json(str(json_file))
                if csv_file:
                    filename = os.path.basename(json_file)
                    nart = self.extract_nart_from_filename(filename)
                    results[nart] = csv_file
            except Exception as e:
                logger.error(f"Error processing {json_file}: {str(e)}")
        
        return results


if __name__ == "__main__":
    # Example usage
    generator = ProductPropertiesCSVGenerator()
    
    # Generate CSV for a single file
    json_file = "output/product/E-FER-68542-70000-20-06_extracted.json"
    if os.path.exists(json_file):
        csv_file = generator.generate_csv_from_json(json_file)
        print(f"Generated: {csv_file}")
    
    # Generate combined CSV for all files
    combined_csv = generator.generate_all_csvs()
    print(f"Generated {len(combined_csv)} CSV files")

