# Usage Examples for extract_images_to_json

## Example 1: Basic Usage with Single Image

### Request
```bash
curl -X POST "http://localhost:8000/pda-document-extraction-tasks/extract-images-to-json" \
  -H "Content-Type: application/json" \
  -d '{
    "images": [
      {
        "id": "img_001",
        "url": "http://example.com/connector_spec_page1.jpg",
        "page_number": 1
      }
    ],
    "product_id": "PROD_CONN_001",
    "feature_ids": [{
      id: xxxxxx,
      name: "identity"
    }]
  }'
```
xxxxxx is the feature_id, which is the section name == identity

### Response
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "product_id": "PROD_CONN_001",
    "features": [
      {
        "feature_id": "xxxxxx",
        "drawing_id": "img_001",
        "result": [
          {
            "result": {
              "part_number": {
                "value": "28408900001",
                "page_number": 1,
                "reasoning": "Matches standard part number format and appears in official header"
              },
              "part_description": {
                "value": "Connector - Male, ECM70 (Bedrock) ECU (70 Way)",
                "page_number": 1,
                "reasoning": "Appears as main title describing the connector type"
              },
              "revision": {
                "value": "01",
                "page_number": 1,
                "reasoning": "Document revision number found in header"
              }
            }
          }
        ]
      }
    ]
  }
}
```

## Example 2: Multiple Pages with Different Features

### Request
```bash
curl -X POST "http://localhost:8000/pda-document-extraction-tasks/extract-images-to-json" \
  -H "Content-Type: application/json" \
  -d '{
    "images": [
      {
        "id": "img_page1",
        "url": "http://example.com/connector_page1.jpg",
        "page_number": 1
      },
      {
        "id": "img_page2",
        "url": "http://example.com/connector_page2.jpg",
        "page_number": 2
      },
      {
        "id": "img_page3",
        "url": "http://example.com/connector_page3.jpg",
        "page_number": 3
      }
    ],
    "product_id": "PROD_CONN_002",
    "feature_ids": ["identity", "mechanical", "electrical"]
  }'
```

### Response
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "product_id": "PROD_CONN_002",
    "features": [
      {
        "feature_id": "identity",
        "drawing_id": "img_page1",
        "result": [
          {
            "result": {
              "part_number": {
                "value": "09R31699A",
                "page_number": 1,
                "reasoning": "Part number from document header"
              }
            }
          }
        ]
      },
      {
        "feature_id": "mechanical",
        "drawing_id": "img_page2",
        "result": [
          {
            "result": {
              "pin_count": {
                "value": "190-way",
                "page_number": 2,
                "reasoning": "Pin count from mechanical specifications table"
              },
              "pin_pitch": {
                "value": "2.54 mm",
                "page_number": 2,
                "reasoning": "Pin pitch specification"
              }
            }
          }
        ]
      },
      {
        "feature_id": "electrical",
        "drawing_id": "img_page3",
        "result": [
          {
            "result": {
              "max_voltage": {
                "value": "26V",
                "page_number": 3,
                "reasoning": "Maximum voltage from electrical specifications"
              },
              "current_per_pin": {
                "value": "7A",
                "page_number": 3,
                "reasoning": "Current per pin rating"
              }
            }
          }
        ]
      }
    ]
  }
}
```

## Example 3: Python Client Usage

```python
import requests
import json

def extract_connector_specs(images, product_id, feature_ids):
    """Extract connector specifications from images"""
    
    url = "http://localhost:8000/pda-document-extraction-tasks/extract-images-to-json"
    
    payload = {
        "images": images,
        "product_id": product_id,
        "feature_ids": feature_ids
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    response = requests.post(url, json=payload, headers=headers)
    
    if response.status_code == 200:
        result = response.json()
        if result["code"] == 0:
            return result["data"]
        else:
            print(f"Error: {result['message']}")
            return None
    else:
        print(f"HTTP Error: {response.status_code}")
        return None

# Usage
images = [
    {
        "id": "img_001",
        "url": "http://example.com/connector_spec.jpg",
        "page_number": 1
    }
]

result = extract_connector_specs(
    images=images,
    product_id="PROD_001",
    feature_ids=["identity"]
)

if result:
    print(json.dumps(result, indent=2))
```

## Example 4: Processing Multiple Products

```python
import asyncio
import aiohttp

async def process_multiple_products(products):
    """Process multiple products in parallel"""
    
    async with aiohttp.ClientSession() as session:
        tasks = []
        for product in products:
            task = extract_product_specs(session, product)
            tasks.append(task)
        
        results = await asyncio.gather(*tasks)
        return results

async def extract_product_specs(session, product):
    """Extract specs for a single product"""
    
    url = "http://localhost:8000/pda-document-extraction-tasks/extract-images-to-json"
    
    payload = {
        "images": product["images"],
        "product_id": product["id"],
        "feature_ids": product["features"]
    }
    
    async with session.post(url, json=payload) as response:
        if response.status == 200:
            data = await response.json()
            return data.get("data")
        return None

# Usage
products = [
    {
        "id": "PROD_001",
        "images": [{"id": "img_001", "url": "...", "page_number": 1}],
        "features": ["identity", "mechanical"]
    },
    {
        "id": "PROD_002",
        "images": [{"id": "img_002", "url": "...", "page_number": 1}],
        "features": ["identity", "electrical"]
    }
]

results = asyncio.run(process_multiple_products(products))
```

## Example 5: Error Handling

```python
import requests

def extract_with_error_handling(images, product_id, feature_ids):
    """Extract with comprehensive error handling"""
    
    try:
        url = "http://localhost:8000/pda-document-extraction-tasks/extract-images-to-json"
        
        # Validate inputs
        if not images:
            raise ValueError("Images list cannot be empty")
        if not product_id:
            raise ValueError("Product ID is required")
        
        payload = {
            "images": images,
            "product_id": product_id,
            "feature_ids": feature_ids or []
        }
        
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        
        if result.get("code") != 0:
            raise Exception(f"API Error: {result.get('message')}")
        
        return result.get("data")
        
    except requests.exceptions.Timeout:
        print("Request timeout - extraction took too long")
        return None
    except requests.exceptions.ConnectionError:
        print("Connection error - cannot reach API")
        return None
    except ValueError as e:
        print(f"Validation error: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None
```

## Response Structure Details

### Product Level
- `product_id`: Identifier for the product being extracted
- `features`: Array of extracted features

### Feature Level
- `feature_id`: Identifier for the feature (e.g., "identity", "mechanical")
- `drawing_id`: Image ID where this feature was found
- `result`: Array containing extraction results

### Result Level
- `result`: Object containing field-level data

### Field Level
- `value`: Extracted value
- `page_number`: Page where value was found
- `reasoning`: Explanation for why this value was selected

## Common Issues and Solutions

### Issue: Empty drawing_id
**Cause**: Image page_number doesn't match any provided image
**Solution**: Ensure images array includes all page numbers referenced in extraction

### Issue: Missing fields in result
**Cause**: Field not found in document or extraction failed
**Solution**: Check extraction_basis in raw result for details

### Issue: Null values in result
**Cause**: Field exists but has no value
**Solution**: This is normal - null values are preserved in output

