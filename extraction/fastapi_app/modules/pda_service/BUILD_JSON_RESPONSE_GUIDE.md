# build_json_response Function Guide

## Overview

The `build_json_response` function transforms raw extraction results from the document extraction pipeline into a standardized output format that maps extraction sections to features with page numbers and drawing IDs.

## Function Signature

```python
def build_json_response(
    extraction_result: Dict[str, Any],
    images: Optional[List[Dict[str, Any]]] = None,
    product_id: Optional[str] = None,
    feature_ids: Optional[List[str]] = None
) -> Dict[str, Any]:
```

## Parameters

- **extraction_result** (Dict[str, Any]): Raw extraction result from the pipeline containing sections like `identity`, `mechanical`, `electrical`, etc.
- **images** (Optional[List[Dict[str, Any]]]): List of image dictionaries with structure: `{id: "img_id", url: "...", page_number: 1}`
- **product_id** (Optional[str]): Product ID to include in the response
- **feature_ids** (Optional[List[str]]): List of feature IDs to map to extraction sections

## Output Format

```json
{
  "product_id": "PROD_001",
  "features": [
    {
      "feature_id": "identity",
      "drawing_id": "img_001",
      "result": [
        {
          "result": {
            "part_number": {
              "value": "28408900001",
              "page_number": 1,
              "reasoning": "Matches standard part number format"
            },
            "part_description": {
              "value": "Connector - Male, ECM70",
              "page_number": 1,
              "reasoning": "Appears as main title"
            }
          }
        }
      ]
    }
  ]
}
```

## Key Features

### 1. Section to Feature Mapping
Each section in the extraction result (e.g., `identity`, `mechanical`, `electrical`) becomes a feature in the output.

### 2. Page Number Extraction
- Extracts `page_number` from the `extraction_basis` array
- Uses the first basis entry's page number as the section's page number
- Defaults to page 1 if not found

### 3. Drawing ID Mapping
- Maps `page_number` to `drawing_id` using the provided images list
- Creates a lookup table: `images_by_page[page_number] = image_id`
- Returns empty string if no matching image found

### 4. Field Value Extraction
For each field in a section:
- Looks up the corresponding `extraction_basis` entry by `field_name`
- Extracts: `value`, `page_number`, and `reasoning`
- Falls back to field value directly if no basis found

## Usage Example

```python
from fastapi_app.modules.pda_service.controller import build_json_response

# Raw extraction result from pipeline
extraction_result = {
    "identity": {
        "part_number": "28408900001",
        "part_description": "Connector - Male",
        "extraction_basis": [
            {
                "field_name": "part_number",
                "value": "28408900001",
                "page_number": "1",
                "reasoning": "Part number format"
            }
        ]
    }
}

# Images with page mapping
images = [
    {"id": "img_001", "url": "http://...", "page_number": 1}
]

# Transform to output format
result = build_json_response(
    extraction_result=extraction_result,
    images=images,
    product_id="PROD_001",
    feature_ids=["identity"]
)
```

## Integration with Controller

The function is called in `PdaTaskController.extract_images_to_json`:

```python
@staticmethod
async def extract_images_to_json(
    images: list[Dict[str, Any]], 
    product_id: str, 
    feature_ids: list[str]
) -> ApiResponse[dict]:
    """提取图片到JSON"""
    try:
        async with get_async_session() as db:
            service = PdaTaskService(db=db)
            result = await service.extract_images_to_json(
                images, 
                doc_type=DocumentType.CONNECTOR_SPECS
            )

            if not result:
                return ResponseUtil.error(...)

            # Transform extraction result
            formatted_result = build_json_response(
                extraction_result=result,
                images=images,
                product_id=product_id,
                feature_ids=feature_ids
            )

            return ResponseUtil.success(data=formatted_result)
    except Exception as e:
        logging.error(...)
        return ResponseUtil.error(...)
```

## API Endpoint

**POST** `/pda-document-extraction-tasks/extract-images-to-json`

### Request Body
```json
{
  "images": [
    {
      "id": "img_001",
      "url": "http://example.com/image.jpg",
      "page_number": 1
    }
  ],
  "product_id": "PROD_001",
  "feature_ids": ["identity", "mechanical"]
}
```

### Response
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "product_id": "PROD_001",
    "features": [...]
  }
}
```

## Testing

Run the test suite:
```bash
python -m pytest fastapi_app/modules/pda_service/test_build_json_response.py -v
```

Test cases cover:
- Basic transformation with single section
- Multiple sections with different page numbers
- Empty extraction results
- Missing images mapping
- Fields without extraction basis

## Notes

1. **Page Number Handling**: Always convert page_number to int for consistency
2. **Drawing ID Lookup**: Empty string returned if image not found for page
3. **Null Values**: Fields with null values are still included in output
4. **Extraction Basis**: Only included if explicitly provided in extraction result
5. **Feature ID Mapping**: Uses section name if feature_ids not provided or empty

