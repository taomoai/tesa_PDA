"""
Generic LLM-based structured extraction using Pydantic.
"""

import logging
import json
import re
import asyncio
from typing import Optional, Type, TypeVar
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

T = TypeVar('T')


class LLMExtractor(ABC):
    """Abstract base class for LLM extractors."""
    
    @abstractmethod
    async def extract(
        self,
        text: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None
    ) -> Optional[T]:
        """
        Extract structured data from text using LLM.
        
        Args:
            text: Input text to extract from
            response_model: Pydantic model for response structure
            system_prompt: Custom system prompt
            
        Returns:
            Extracted data as Pydantic model instance or None on error
        """
        pass


class LLMClientExtractor(LLMExtractor):
    """
    Generic LLM extractor using unified LLM client.
    """
    
    def __init__(self, llm_client):
        """
        Initialize the LLM extractor.
        
        Args:
            llm_client: LLM client instance (from get_llm_client)
        """
        self.llm_client = llm_client
    
    def _normalize_field_names(self, data):
        """
        Normalize field names in the data structure.
        Converts field names to lowercase and replaces spaces with underscores.

        Args:
            data: Dictionary or list to normalize

        Returns:
            Normalized data structure
        """
        if isinstance(data, dict):
            normalized = {}
            for key, value in data.items():
                normalized_key = key.lower().replace(' ', '_')
                normalized[normalized_key] = self._normalize_field_names(value)
            return normalized
        elif isinstance(data, list):
            return [self._normalize_field_names(item) for item in data]
        else:
            return data

    def _is_valid_property_item(self, item: dict) -> bool:
        """
        Check if a property item is a valid data row (not a header, separator, or note).

        A valid property item should have:
        - 'no' field with a non-null value (item number like '01', '02', etc.)
        - 'item_no' field with a non-null value (P-number like 'P4079')

        Invalid items (to skip):
        - All fields are null
        - 'no' is null (typically notes/conditions)
        - Only 'item' and 'unit' have values but 'no' and 'item_no' are null

        Args:
            item: Dictionary representing a property item

        Returns:
            True if this is a valid data row, False otherwise
        """
        # Check if all fields are null
        if all(v is None for v in item.values()):
            return False

        # Check if 'no' is null (invalid data row)
        if item.get('no') is None:
            return False

        # Check if 'item_no' is null (invalid data row)
        if item.get('item_no') is None:
            return False

        return True

    def _clean_properties_list(self, data):
        """
        Clean the properties list by removing invalid items (headers, separators, notes).

        Args:
            data: Dictionary that may contain a 'properties' list

        Returns:
            Cleaned data with invalid items removed
        """
        if isinstance(data, dict) and 'properties' in data and isinstance(data['properties'], list):
            # Filter out invalid property items
            valid_properties = [
                item for item in data['properties']
                if isinstance(item, dict) and self._is_valid_property_item(item)
            ]
            data['properties'] = valid_properties
            logger.info(f"Cleaned properties list: {len(data['properties'])} valid items out of {len(data.get('properties', []))} total")

        return data

    def _normalize_target_value(self, value: str) -> str:
        """
        Normalize target_value_with_unit field:
        - Replace commas with dots for decimal points (European format → Standard format)

        Args:
            value: The target value string

        Returns:
            Normalized value with dots instead of commas
        """
        if not isinstance(value, str):
            return value

        # Replace commas with dots for decimal points
        # This handles European format (6,00) → Standard format (6.00)
        normalized = value.replace(',', '.')
        return normalized

    def _normalize_properties_values(self, data):
        """
        Normalize values in properties list (e.g., replace commas with dots in target_value_with_unit).

        Args:
            data: Dictionary that may contain a 'properties' list

        Returns:
            Data with normalized values
        """
        if isinstance(data, dict) and 'properties' in data and isinstance(data['properties'], list):
            for item in data['properties']:
                if isinstance(item, dict) and 'target_value_with_unit' in item:
                    if item['target_value_with_unit'] is not None:
                        item['target_value_with_unit'] = self._normalize_target_value(item['target_value_with_unit'])

        return data
    
    async def extract(
        self,
        text: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        max_retries: int = 3
    ) -> Optional[T]:
        """
        Extract structured data from text using LLM.
        
        Args:
            text: Input text to extract from
            response_model: Pydantic model for response structure
            system_prompt: Custom system prompt
            max_retries: Maximum number of retry attempts
            
        Returns:
            Extracted data as Pydantic model instance or None on error
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for extraction")
            return None
        
        if not self.llm_client:
            logger.error("LLM client not initialized")
            return None
        
        # Generate JSON schema from Pydantic model
        schema = response_model.model_json_schema()
        
        # Build extraction prompt
        extraction_prompt = f"""{system_prompt or 'Extract structured data from the provided text.'}

You MUST extract data from the provided text and return ONLY a valid JSON object.

JSON Schema:
{json.dumps(schema, indent=2, ensure_ascii=False)}

Text to extract from:
{text}

CRITICAL INSTRUCTIONS:
1. Return ONLY valid JSON, no other text
2. Use the exact field names from the schema
3. For arrays, return a list of objects with the correct structure
4. Extract all available data from the text
5. Do not include explanations or schema definitions
6. Ensure proper JSON formatting with correct brackets and quotes"""
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Extraction attempt {attempt + 1}/{max_retries}")

                # Call the LLM
                response_text = await self.llm_client.call_llm(extraction_prompt)
                logger.info(f"📝 FULL LLM RESPONSE (Text extraction):\n{response_text}")

                # Parse the JSON response
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                    response_data = json.loads(json_str)
                else:
                    response_data = json.loads(response_text)
                
                # Normalize field names
                normalized_data = self._normalize_field_names(response_data)

                # Clean properties list if present (remove invalid items like headers, notes)
                normalized_data = self._clean_properties_list(normalized_data)

                # Normalize property values (e.g., replace commas with dots in target_value_with_unit)
                normalized_data = self._normalize_properties_values(normalized_data)

                # Create the Pydantic model instance
                result = response_model(**normalized_data)
                logger.info("✅ Extraction successful")
                return result
                
            except json.JSONDecodeError as e:
                logger.warning(f"Extraction attempt {attempt + 1} failed: JSON decode error - {e}")
                continue
            except Exception as e:
                logger.warning(f"Extraction attempt {attempt + 1} failed: {e}")
                continue
        
        logger.error(f"Extraction failed after {max_retries} attempts")
        return None

    async def extract_from_image(
        self,
        image_url: str,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        max_retries: int = 3
    ) -> Optional[T]:
        """
        Extract structured data from an image using vision-based LLM.

        Args:
            image_url: URL or data URL of the image
            prompt: Prompt to send to the LLM
            response_model: Pydantic model for response structure
            system_prompt: Custom system prompt
            max_retries: Maximum number of retry attempts

        Returns:
            Extracted data as Pydantic model instance or None on error
        """
        if not image_url:
            logger.warning("Empty image URL provided for extraction")
            return None

        if not self.llm_client:
            logger.error("LLM client not initialized")
            return None

        # Generate JSON schema from Pydantic model
        schema = response_model.model_json_schema()

        # Build extraction prompt for vision
        extraction_prompt = f"""{system_prompt or 'Extract structured data from the provided image.'}

You MUST analyze the image and extract data, then return ONLY a valid JSON object.

JSON Schema:
{json.dumps(schema, indent=2, ensure_ascii=False)}

{prompt}

CRITICAL INSTRUCTIONS:
1. Return ONLY valid JSON, no other text
2. Use the exact field names from the schema
3. For arrays, return a list of objects with the correct structure
4. Extract all available data from the image
5. Do not include explanations or schema definitions
6. Ensure proper JSON formatting with correct brackets and quotes"""

        for attempt in range(max_retries):
            try:
                logger.info(f"Vision extraction attempt {attempt + 1}/{max_retries}")

                # Call the LLM with image URL
                response_text = await self.llm_client.call_llm(
                    extraction_prompt,
                    image_url=image_url
                )
                logger.info(f"📝 FULL LLM RESPONSE (Single image extraction):\n{response_text}")

                # Parse the JSON response
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                    response_data = json.loads(json_str)
                else:
                    response_data = json.loads(response_text)

                # Normalize field names
                normalized_data = self._normalize_field_names(response_data)

                # Create the Pydantic model instance
                result = response_model(**normalized_data)
                logger.info("✅ Vision extraction successful")
                return result

            except json.JSONDecodeError as e:
                logger.warning(f"Vision extraction attempt {attempt + 1} failed: JSON decode error - {e}")
                continue
            except Exception as e:
                logger.warning(f"Vision extraction attempt {attempt + 1} failed: {e}")
                continue

        logger.error(f"Vision extraction failed after {max_retries} attempts")
        return None

    async def _extract_from_single_page(
        self,
        page_idx: int,
        total_pages: int,
        image_url: str,
        schema: dict,
        system_prompt: Optional[str] = None,
        max_retries: int = 3
    ) -> Optional[dict]:
        """
        Extract data from a single page image.

        Args:
            page_idx: Page index (1-based)
            total_pages: Total number of pages
            image_url: URL of the image
            schema: JSON schema for response
            system_prompt: Custom system prompt
            max_retries: Maximum number of retry attempts

        Returns:
            Extracted data as dict or None on error
        """
        logger.info(f"🔄 Extracting from page {page_idx}/{total_pages}: {image_url}")

        # Build extraction prompt for single page
        extraction_prompt = f"""{system_prompt or 'Extract structured data from the provided document image.'}

You are analyzing page {page_idx} of a {total_pages}-page document.

JSON Schema for the response:
{json.dumps(schema, indent=2, ensure_ascii=False)}

CRITICAL INSTRUCTIONS:
1. Carefully examine this page
2. Extract ALL available data from this page
3. Return ONLY a valid JSON object matching the schema
4. Use the exact field names from the schema
5. For arrays, return a list of objects with the correct structure
6. Do NOT include any explanations, markdown, or schema definitions
7. Ensure proper JSON formatting with correct brackets and quotes
8. For null/missing values, use null (not empty string or "N/A")"""

        for attempt in range(max_retries):
            try:
                logger.info(f"Vision extraction attempt {attempt + 1}/{max_retries} for page {page_idx}")

                # Extract from single page
                response_text = await self.llm_client.call_llm(
                    extraction_prompt,
                    image_url=image_url
                )

                logger.info(f"LLM response received for page {page_idx}: {len(response_text)} characters")

                # Parse the JSON response
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                    response_data = json.loads(json_str)
                else:
                    response_data = json.loads(response_text)

                logger.info(f"✅ Successfully extracted from page {page_idx}")
                return response_data

            except json.JSONDecodeError as e:
                logger.warning(f"Page {page_idx} extraction attempt {attempt + 1} failed: JSON decode error - {e}")
                continue
            except Exception as e:
                logger.warning(f"Page {page_idx} extraction attempt {attempt + 1} failed: {e}")
                continue

        logger.warning(f"Failed to extract from page {page_idx} after {max_retries} attempts")
        return None

    async def extract_from_images(
        self,
        image_urls: list,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        max_retries: int = 3
    ) -> Optional[T]:
        """
        Extract structured data from multiple images using vision-based LLM.

        Strategy: Extract from each page separately, then merge results.

        Args:
            image_urls: List of image URLs or data URLs
            response_model: Pydantic model for response structure
            system_prompt: Custom system prompt
            max_retries: Maximum number of retry attempts

        Returns:
            Extracted data as Pydantic model instance or None on error
        """
        if not image_urls:
            logger.warning("Empty image URLs list provided for extraction")
            return None

        if not self.llm_client:
            logger.error("LLM client not initialized")
            return None

        # Generate JSON schema from Pydantic model
        schema = response_model.model_json_schema()

        # Extract from each page concurrently
        logger.info(f"🔄 Starting concurrent extraction from {len(image_urls)} pages...")

        # Create extraction tasks for all pages
        extraction_tasks = []
        for page_idx, image_url in enumerate(image_urls, 1):
            task = self._extract_from_single_page(
                page_idx=page_idx,
                total_pages=len(image_urls),
                image_url=image_url,
                schema=schema,
                system_prompt=system_prompt,
                max_retries=max_retries
            )
            extraction_tasks.append(task)

        # Execute all extraction tasks concurrently
        page_results_with_idx = await asyncio.gather(*extraction_tasks, return_exceptions=True)

        # Filter out exceptions and extract successful results
        page_results = []
        for page_idx, result in enumerate(page_results_with_idx, 1):
            if isinstance(result, Exception):
                logger.warning(f"❌ Failed to extract from page {page_idx}: {str(result)}")
            elif result is not None:
                page_results.append(result)
                logger.info(f"✅ Successfully extracted from page {page_idx}")

                # Check if all fields are complete after merging
                merged_data = self._merge_page_results(page_results, schema)
                if self._is_section_complete(merged_data, schema):
                    logger.info(f"🛑 Section complete after page {page_idx}, stopping further processing")
                    # Return early with merged data
                    return self._create_result_from_merged_data(merged_data, response_model)

        if not page_results:
            logger.error("Failed to extract from any page")
            return None

        # Merge results from all pages
        logger.info(f"Merging results from {len(page_results)} pages")
        logger.info(f"📊 PAGE RESULTS BEFORE MERGE:")
        for idx, page_result in enumerate(page_results, 1):
            for field_name, field_value in page_result.items():
                if isinstance(field_value, list):
                    logger.info(f"   Page {idx}: {len(field_value)} items in {field_name}")
                    for item in field_value:
                        # Try to get a meaningful identifier from the item
                        if isinstance(item, dict):
                            identifier = item.get('property') or item.get('name') or item.get('id') or str(item)[:50]
                            logger.info(f"      - {identifier}")

        merged_data = self._merge_page_results(page_results, schema)

        logger.info(f"📊 MERGED DATA:")
        for field_name, field_value in merged_data.items():
            if isinstance(field_value, list):
                logger.info(f"   Total items after merge in {field_name}: {len(field_value)}")
                for item in field_value:
                    # Try to get a meaningful identifier from the item
                    if isinstance(item, dict):
                        identifier = item.get('property') or item.get('name') or item.get('id') or str(item)[:50]
                        logger.info(f"      - {identifier}")

        # Post-process extraction_basis if present
        if 'extraction_basis' in merged_data and merged_data['extraction_basis']:
            logger.info(f"🔄 Post-processing extraction_basis with AI... ({len(merged_data['extraction_basis'])} entries)")
            merged_data = await self._post_process_extraction_basis(merged_data, schema)
        else:
            logger.info("No extraction_basis to post-process")

        return self._create_result_from_merged_data(merged_data, response_model)

    async def _post_process_extraction_basis(self, merged_data: dict, schema: dict) -> dict:
        """
        Post-process extraction_basis using AI to:
        1. Evaluate the quality and accuracy of each extraction_basis entry
        2. Keep only the most complete and accurate extraction basis for each field
        3. Update field values based on the best extraction_basis entries
        4. Remove duplicate or conflicting entries
        5. Ensure extraction_basis entries match the final field values

        Args:
            merged_data: The merged data with extraction_basis
            schema: The JSON schema for the section

        Returns:
            Updated merged_data with cleaned extraction_basis and updated field values
        """
        try:
            logger.info("🔄 Starting post-processing of extraction_basis...")
            if not self.llm_client:
                logger.warning("LLM client not available for post-processing")
                return merged_data

            # Get all field names (excluding extraction_basis)
            schema_properties = schema.get('properties', {})
            field_names = [f for f in schema_properties.keys() if f != 'extraction_basis']

            # Build the post-processing prompt with very explicit instructions
            post_process_prompt = f"""You are a data quality specialist. Your task is to review and clean extraction records.

CURRENT EXTRACTION RESULTS:
{json.dumps(merged_data, indent=2, ensure_ascii=False)}

AVAILABLE FIELDS:
{', '.join(field_names)}

YOUR TASK - FOLLOW THESE STEPS EXACTLY:

STEP 1: Group extraction_basis entries by field_name
- For each field, list all extraction_basis entries for that field
- Note the values and basis information for each entry

STEP 2: For each field with multiple extraction_basis entries:
- Compare the entries and select the BEST ONE based on:
  * Completeness: More detailed/specific information is better
  * Accuracy: More precise values are better
  * Source quality: Entries with specific locations and clear evidence are better
- The selected entry's value should become the final field value
- All other entries for this field should be removed

STEP 3: For each field with a null value but extraction_basis entries:
- Select the best extraction_basis entry
- Use its value as the new field value
- Keep only this one entry in extraction_basis

STEP 4: Remove ALL extraction_basis entries for fields that have null values (after step 3)

STEP 5: Ensure each field has at most ONE extraction_basis entry

IMPORTANT RULES:
- extraction_basis should ONLY contain entries for fields with non-null values
- Each field should have at most ONE extraction_basis entry (the most accurate one)
- If a field value is null but has extraction_basis entries, choose the best one and update the field value
- If a field value conflicts with extraction_basis, prefer the extraction_basis value if it's more detailed/accurate
- Preserve ALL fields in extraction_basis entries: field_name, value, basis, context, reasoning, page_number, coordinates
- context: surrounding text that provides context for the extracted value
- reasoning: explanation of why this value was selected

EXAMPLE:
If you have:
- field_name: "pin_size", value: "0.64mm / 1.5mm", basis: "...", context: "...", reasoning: "...", page_number: "3"
- field_name: "pin_size", value: "0.64mm Square Pin / 1.5mm Rect. Pin", basis: "...", context: "...", reasoning: "...", page_number: "4"

The second one is more detailed, so:
- Update the field value to "0.64mm Square Pin / 1.5mm Rect. Pin"
- Keep only the second extraction_basis entry
- Remove the first extraction_basis entry

CRITICAL: You MUST return field_updates for ALL fields that have extraction_basis entries, even if the value doesn't change!

Return ONLY valid JSON with this structure:
{{
  "field_updates": {{
    "pin_size": "0.64mm Square Pin / 1.5mm Rect. Pin",
    "pin_count": "70",
    "pin_type_orientation": "Male",
    ...
  }},
  "extraction_basis": [
    {{"field_name": "pin_size", "value": "0.64mm Square Pin / 1.5mm Rect. Pin", "basis": "detailed_basis", "context": "Pin Size: 0.64mm Square Pin / 1.5mm Rect. Pin", "reasoning": "More detailed specification with pin shape information", "page_number": "4"}},
    {{"field_name": "pin_count", "value": "70", "basis": "Title field", "context": "70-way connector", "reasoning": "Explicitly stated in product title", "page_number": "1"}},
    ...
  ]
}}"""

            logger.info("Calling AI for extraction_basis post-processing and field value optimization...")
            response_text = await self.llm_client.call_llm(post_process_prompt)

            logger.info(f"Post-processing response received: {len(response_text)} characters")
            logger.info(f"Post-processing response: {response_text[:1000]}")

            # Parse the response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                logger.info(f"Extracted JSON from response: {json_str[:500]}")
                response_data = json.loads(json_str)
            else:
                logger.info("No JSON match found, trying direct parse")
                response_data = json.loads(response_text)

            # Update field values based on AI recommendations
            if 'field_updates' in response_data:
                logger.info(f"Processing {len(response_data['field_updates'])} field updates...")
                for field_name, new_value in response_data['field_updates'].items():
                    if field_name in merged_data:
                        old_value = merged_data[field_name]
                        if old_value != new_value:
                            logger.info(f"📝 Updated field '{field_name}': '{old_value}' -> '{new_value}'")
                            merged_data[field_name] = new_value
                        elif new_value is not None:
                            logger.info(f"✓ Field '{field_name}' confirmed: '{new_value}'")
                    else:
                        logger.warning(f"Field '{field_name}' not found in merged_data")
            else:
                logger.warning("No 'field_updates' in AI response")

            # Update extraction_basis
            if 'extraction_basis' in response_data:
                original_count = len(merged_data.get('extraction_basis', []))
                new_count = len(response_data['extraction_basis'])
                logger.info(f"✅ Post-processed extraction_basis: {original_count} entries -> {new_count} entries")

                # Log the cleaned entries
                for entry in response_data['extraction_basis']:
                    if isinstance(entry, dict):
                        logger.info(f"   ✓ {entry.get('field_name')}: {entry.get('value')} (page {entry.get('page_number')})")

                merged_data['extraction_basis'] = response_data['extraction_basis'] if response_data['extraction_basis'] else None

            return merged_data

        except Exception as e:
            logger.warning(f"Post-processing extraction_basis failed: {e}, keeping original data")
            import traceback
            logger.debug(traceback.format_exc())
            return merged_data

    def _create_result_from_merged_data(self, merged_data: dict, response_model):
        """
        Create a Pydantic model instance from merged data, cleaning up extraction_basis if present.

        Args:
            merged_data: The merged data from all pages
            response_model: The Pydantic model class

        Returns:
            Pydantic model instance or None on error
        """
        try:
            # Clean up extraction_basis: only keep entries for fields with non-null values
            # Only do this if extraction_basis exists in the merged data
            if 'extraction_basis' in merged_data and merged_data['extraction_basis']:
                cleaned_basis = []
                for basis_entry in merged_data['extraction_basis']:
                    # Only keep entries where value is not null
                    if isinstance(basis_entry, dict) and basis_entry.get('value') is not None:
                        cleaned_basis.append(basis_entry)

                logger.info(f"Cleaned extraction_basis: {len(merged_data['extraction_basis'])} entries -> {len(cleaned_basis)} entries")
                merged_data['extraction_basis'] = cleaned_basis if cleaned_basis else None

            # Create the Pydantic model instance
            result = response_model(**merged_data)
            logger.info("✅ Vision extraction from images successful")
            return result
        except Exception as e:
            logger.error(f"Failed to create model instance from merged data: {e}")
            return None

    def _is_section_complete(self, merged_data: dict, schema: dict) -> bool:
        """
        Check if all required fields in a section have non-null values.
        Only applies to schemas that have extraction_basis field.

        Args:
            merged_data: The merged data from pages
            schema: The JSON schema for the section

        Returns:
            True if all fields have non-null values, False otherwise
            Returns False if schema doesn't have extraction_basis (not applicable)
        """
        # Get all field names from schema
        schema_properties = schema.get('properties', {})

        # Only apply early stopping if schema has extraction_basis field
        if 'extraction_basis' not in schema_properties:
            logger.debug("Schema doesn't have extraction_basis field, skipping early stopping check")
            return False

        empty_fields = []
        for field_name in schema_properties.keys():
            # Skip extraction_basis field
            if field_name == 'extraction_basis':
                continue

            # Check if field has a value
            value = merged_data.get(field_name)

            # Consider field empty if:
            # 1. value is None (Python None)
            # 2. value is string "null" (JSON null representation)
            # 3. value is empty string
            is_empty = (
                value is None or
                (isinstance(value, str) and (value.strip() == "" or value.strip().lower() == "null"))
            )

            if is_empty:
                empty_fields.append(field_name)

        if empty_fields:
            logger.info(f"Found {len(empty_fields)} empty fields, continuing extraction: {empty_fields}")
            return False

        logger.info("✅ All fields have values, stopping extraction")
        return True

    def _get_field_type(self, field_schema: dict) -> str:
        """
        Extract the field type from schema, handling anyOf structures.

        Args:
            field_schema: The field schema definition

        Returns:
            The field type (e.g., 'array', 'object', 'string', etc.)
        """
        # Direct type
        if "type" in field_schema:
            return field_schema["type"]

        # Handle anyOf structure (e.g., Optional fields)
        if "anyOf" in field_schema:
            for option in field_schema["anyOf"]:
                if isinstance(option, dict) and "type" in option and option["type"] != "null":
                    return option["type"]

        # Handle allOf structure
        if "allOf" in field_schema:
            for option in field_schema["allOf"]:
                if isinstance(option, dict) and "type" in option:
                    return option["type"]

        return None

    def _merge_page_results(self, page_results: list, schema: dict) -> dict:
        """
        Merge extraction results from multiple pages.

        Strategy:
        - For string fields: use the first non-null value
        - For object fields: recursively merge
        - For array fields: combine all non-null items with deduplication for certain fields

        Args:
            page_results: List of extracted data from each page
            schema: JSON schema of the response model

        Returns:
            Merged data dictionary
        """
        if not page_results:
            return {}

        if len(page_results) == 1:
            return page_results[0]

        merged = {}
        properties = schema.get("properties", {})

        for field_name, field_schema in properties.items():
            # Collect all non-null values for this field across pages
            # For arrays, also filter out empty arrays
            values = []
            for result in page_results:
                val = result.get(field_name)
                if val is not None:
                    # For arrays, skip empty arrays
                    if isinstance(val, list) and len(val) == 0:
                        continue
                    values.append(val)

            if not values:
                merged[field_name] = None
            else:
                # Determine field type from schema (handles anyOf structures)
                # But also check the actual data type to handle Union types correctly
                field_type = self._get_field_type(field_schema)

                # Check actual data type of the first value
                # This is important for Union types like Optional[dict | list | str]
                first_value = values[0]
                actual_is_list = isinstance(first_value, list)
                actual_is_dict = isinstance(first_value, dict)

                # Priority: actual data type > schema type
                # This handles cases where schema is Union[dict, list, str] but actual data is list
                if actual_is_list:
                    # For array fields, merge all items from all pages
                    # Special handling for characteristics_and_properties to deduplicate
                    if field_name == "properties":
                        merged[field_name] = self._merge_arrays_with_dedup(values)
                    else:
                        merged[field_name] = self._merge_arrays(values)
                elif actual_is_dict or field_type == "object":
                    # For object fields, recursively merge
                    merged[field_name] = self._merge_objects(values)
                elif field_type == "array":
                    # Schema says array, merge as arrays
                    if field_name == "properties":
                        merged[field_name] = self._merge_arrays_with_dedup(values)
                    else:
                        merged[field_name] = self._merge_arrays(values)
                else:
                    # For string, number, boolean, etc., use the first non-null value
                    merged[field_name] = values[0]

        return merged

    def _merge_objects(self, objects: list) -> dict:
        """Merge multiple object values by combining their keys."""
        if not objects:
            return None
        if len(objects) == 1:
            return objects[0]

        merged = {}
        for obj in objects:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if value is not None and key not in merged:
                        merged[key] = value

        return merged if merged else None

    def _merge_arrays(self, arrays: list) -> list:
        """Merge multiple array values by combining all items from all pages."""
        if not arrays:
            return None

        merged = []

        for arr in arrays:
            if isinstance(arr, list):
                for item in arr:
                    merged.append(item)

        return merged if merged else None

    def _merge_arrays_with_dedup(self, arrays: list) -> list:
        """
        Merge multiple array values with deduplication for characteristics_and_properties.

        For properties, we deduplicate based on the 'no' field (item number).
        This prevents duplicate properties when extracting from multiple pages.

        Args:
            arrays: List of arrays to merge

        Returns:
            Merged and deduplicated array
        """
        if not arrays:
            return None

        merged = []
        seen_nos = set()

        for arr in arrays:
            if isinstance(arr, list):
                for item in arr:
                    # For properties, deduplicate by 'no' field
                    if isinstance(item, dict) and 'no' in item:
                        item_no = item.get('no')
                        if item_no not in seen_nos:
                            merged.append(item)
                            seen_nos.add(item_no)
                            logger.info(f"Added property: no={item_no}, item={item.get('item', 'N/A')[:50]}")
                        else:
                            logger.info(f"Skipped duplicate property: no={item_no}")
                    else:
                        # If no 'no' field, just append
                        merged.append(item)

        return merged if merged else None

