"""
Test cases for build_json_response function
"""
import pytest
from .controller import build_json_response


def test_build_json_response_basic():
    """Test basic transformation of extraction result"""
    extraction_result = {
        "identity": {
            "part_number": "28408900001",
            "part_description": "Connector - Male, ECM70 (Bedrock) ECU (70 Way)",
            "series_family": None,
            "revision": "01",
            "date_code": "05/11/16",
            "lot_cavity_number": None,
            "net_weight": "1 gram per pin",
            "extraction_basis": [
                {
                    "field_name": "part_number",
                    "value": "28408900001",
                    "basis": "Document header, Part No. field",
                    "context": "Part No. 28408900001",
                    "reasoning": "Matches standard part number format",
                    "page_number": "1",
                    "coordinates": {"x": 845.0, "y": 55.0, "width": 150.0, "height": 20.0}
                }
            ]
        }
    }
    
    images = [
        {"id": "img_001", "url": "http://example.com/img1.jpg", "page_number": 1}
    ]
    
    result = build_json_response(
        extraction_result=extraction_result,
        images=images,
        product_id="PROD_001",
        feature_ids=["identity"]
    )
    
    # Verify structure
    assert result["product_id"] == "PROD_001"
    assert len(result["features"]) == 1
    
    feature = result["features"][0]
    assert feature["feature_id"] == "identity"
    assert feature["drawing_id"] == "img_001"
    assert len(feature["result"]) == 1
    
    # Verify result structure
    result_obj = feature["result"][0]
    assert "result" in result_obj
    assert "part_number" in result_obj["result"]
    assert result_obj["result"]["part_number"]["value"] == "28408900001"
    assert result_obj["result"]["part_number"]["page_number"] == 1
    assert result_obj["result"]["part_number"]["reasoning"] == "Matches standard part number format"


def test_build_json_response_multiple_sections():
    """Test transformation with multiple extraction sections"""
    extraction_result = {
        "identity": {
            "part_number": "28408900001",
            "extraction_basis": [
                {
                    "field_name": "part_number",
                    "value": "28408900001",
                    "page_number": "1",
                    "reasoning": "Part number"
                }
            ]
        },
        "mechanical": {
            "pin_count": "70-way",
            "extraction_basis": [
                {
                    "field_name": "pin_count",
                    "value": "70-way",
                    "page_number": "2",
                    "reasoning": "Pin count"
                }
            ]
        }
    }
    
    images = [
        {"id": "img_001", "url": "http://example.com/img1.jpg", "page_number": 1},
        {"id": "img_002", "url": "http://example.com/img2.jpg", "page_number": 2}
    ]
    
    result = build_json_response(
        extraction_result=extraction_result,
        images=images,
        product_id="PROD_001"
    )
    
    assert len(result["features"]) == 2
    
    # Check identity feature
    identity_feature = next(f for f in result["features"] if f["feature_id"] == "identity")
    assert identity_feature["drawing_id"] == "img_001"
    
    # Check mechanical feature
    mechanical_feature = next(f for f in result["features"] if f["feature_id"] == "mechanical")
    assert mechanical_feature["drawing_id"] == "img_002"


def test_build_json_response_empty_extraction():
    """Test with empty extraction result"""
    result = build_json_response(
        extraction_result={},
        product_id="PROD_001"
    )
    
    assert result["product_id"] == "PROD_001"
    assert result["features"] == []


def test_build_json_response_no_images():
    """Test transformation without images mapping"""
    extraction_result = {
        "identity": {
            "part_number": "28408900001",
            "extraction_basis": [
                {
                    "field_name": "part_number",
                    "value": "28408900001",
                    "page_number": "1",
                    "reasoning": "Part number"
                }
            ]
        }
    }
    
    result = build_json_response(
        extraction_result=extraction_result,
        product_id="PROD_001"
    )
    
    assert result["product_id"] == "PROD_001"
    assert len(result["features"]) == 1
    assert result["features"][0]["drawing_id"] == ""


def test_build_json_response_field_without_basis():
    """Test field without extraction_basis"""
    extraction_result = {
        "identity": {
            "part_number": "28408900001",
            "part_description": "Connector",
            "extraction_basis": [
                {
                    "field_name": "part_number",
                    "value": "28408900001",
                    "page_number": "1",
                    "reasoning": "Part number"
                }
            ]
        }
    }
    
    result = build_json_response(
        extraction_result=extraction_result,
        product_id="PROD_001"
    )
    
    result_obj = result["features"][0]["result"][0]["result"]
    
    # part_number should have basis info
    assert result_obj["part_number"]["reasoning"] == "Part number"
    
    # part_description should use default values
    assert result_obj["part_description"]["value"] == "Connector"
    assert result_obj["part_description"]["reasoning"] == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

