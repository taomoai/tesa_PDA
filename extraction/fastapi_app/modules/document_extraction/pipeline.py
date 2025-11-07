"""
Document extraction pipeline using raw text extraction.
Extracts complete text from PDF and passes it to LLM for structured extraction.
Supports OCR fallback for scanned PDFs.
"""

import logging
import re
import json
from typing import Optional, Dict, Any
from pathlib import Path
import tempfile
import os
import asyncio

from .llm_extractor import LLMClientExtractor
from .config import ExtractionConfig

logger = logging.getLogger(__name__)


class ExtractionPipeline:
    """
    Document extraction pipeline using raw text extraction.

    This pipeline:
    1. Extracts complete text from PDF using pdfplumber
    2. Passes the full text to LLM for each section
    3. Returns structured data according to section schemas

    This approach preserves the original PDF format and allows LLM to see
    complete context for more accurate extraction.
    """

    def __init__(self, config: ExtractionConfig, llm_client, vision_llm_client=None, force_vision_extraction=False, enable_pagination=False, pagination_chunk_size=2):
        """
        Initialize the extraction pipeline.

        Args:
            config: ExtractionConfig with section definitions
            llm_client: LLM client instance for text extraction (from get_llm_client)
            vision_llm_client: Optional LLM client for vision-based extraction (e.g., drawing_vl_llm)
            force_vision_extraction: If True, always use vision-based extraction (for Liner documents)
            enable_pagination: If True, split large documents into chunks for extraction (default: False)
            pagination_chunk_size: Number of pages per chunk (default: 2)
        """
        self.config = config
        self.llm_client = llm_client
        self.vision_llm_client = vision_llm_client or llm_client  # Fallback to text LLM if no vision LLM provided
        self.extractor = LLMClientExtractor(llm_client)
        self.vision_extractor = LLMClientExtractor(self.vision_llm_client) if vision_llm_client else self.extractor
        self.force_vision_extraction = force_vision_extraction
        self.enable_pagination = enable_pagination
        self.pagination_chunk_size = pagination_chunk_size

        self.pdf_path: Optional[str] = None
        self.images: Optional[list] = None
        self.full_text: str = ""
        self.chunk_texts: Dict[str, str] = {}
        self.extraction_results: Dict[str, Any] = {}
        self.used_ocr: bool = False  # Track if vision extraction was used

    async def _convert_pdf_to_images(self, pdf_path: str) -> Optional[list]:
        """
        Convert PDF to images for vision-based extraction.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            List of PIL Image objects or None if conversion fails
        """
        try:
            import pdf2image

            logger.info("Converting PDF to images for vision-based extraction...")

            # Convert PDF to images
            images = pdf2image.convert_from_path(pdf_path)
            if not images:
                logger.warning("No images generated from PDF")
                return None

            logger.info(f"✅ Successfully converted PDF to {len(images)} images")
            self.used_ocr = True  # Mark that we're using image-based extraction
            return images

        except Exception as e:
            logger.error(f"PDF to image conversion failed: {str(e)}")
            return None

    async def _save_images_to_temp(self, images: list) -> Optional[list]:
        """
        Save PIL images to temporary files and return file paths.

        Args:
            images: List of PIL Image objects

        Returns:
            List of temporary file paths or None if saving fails
        """
        try:
            temp_paths = []
            temp_dir = tempfile.mkdtemp()

            for page_num, image in enumerate(images, 1):
                temp_path = os.path.join(temp_dir, f"page_{page_num:03d}.png")
                image.save(temp_path, format='PNG')
                temp_paths.append(temp_path)
                logger.info(f"Saved page {page_num} to {temp_path}")

            return temp_paths

        except Exception as e:
            logger.error(f"Failed to save images to temp: {str(e)}")
            return None
    
    async def _extract_section(self, section_config, section_text: str):
        """
        Extract a single section using LLM.

        Args:
            section_config: SectionConfig for this section
            section_text: Text to extract from

        Returns:
            Extracted result or None on error
        """
        try:
            logger.info(f"🔄 Extracting section: {section_config.section_name}")

            result = await self.extractor.extract(
                text=section_text,
                response_model=section_config.schema,
                system_prompt=section_config.system_prompt
            )

            return result
        except Exception as e:
            logger.error(f"Error extracting {section_config.section_name}: {str(e)}", exc_info=True)
            raise

    async def _extract_section_with_pagination(self, section_config, section_text: str, chunk_size: int = 2):
        """
        Extract a section with pagination support for large documents.

        Splits the text into chunks (default 2 pages per chunk), extracts from each chunk,
        and merges the results.

        Args:
            section_config: SectionConfig for this section
            section_text: Full text to extract from
            chunk_size: Number of pages per chunk (default: 2)

        Returns:
            Merged extracted result or None on error
        """
        try:
            logger.info(f"🔄 Extracting section with pagination: {section_config.section_name}")

            # Split text into chunks
            chunks = self._split_text_into_chunks(section_text, chunk_size)

            if len(chunks) <= 1:
                # If only one chunk, use regular extraction
                logger.info(f"Document has {len(chunks)} chunk(s), using regular extraction")
                return await self._extract_section(section_config, section_text)

            logger.info(f"Document split into {len(chunks)} chunks of {chunk_size} pages each")

            # Extract from each chunk
            chunk_results = []
            for i, chunk in enumerate(chunks, 1):
                logger.info(f"Extracting chunk {i}/{len(chunks)} for {section_config.section_name}")
                try:
                    result = await self.extractor.extract(
                        text=chunk,
                        response_model=section_config.schema,
                        system_prompt=section_config.system_prompt
                    )
                    if result:
                        chunk_results.append(result)
                except Exception as e:
                    logger.warning(f"Error extracting chunk {i}: {str(e)}")
                    continue

            if not chunk_results:
                logger.error(f"Failed to extract any chunks for {section_config.section_name}")
                return None

            # Merge results
            merged_result = self._merge_extraction_results(chunk_results, section_config.schema)
            logger.info(f"✅ Merged {len(chunk_results)} chunks for {section_config.section_name}")
            return merged_result

        except Exception as e:
            logger.error(f"Error in paginated extraction for {section_config.section_name}: {str(e)}", exc_info=True)
            raise

    def _merge_extraction_results(self, results: list, schema):
        """
        Merge extraction results from multiple chunks.

        For list-based results (e.g., properties list), concatenates all items.
        For dict-based results, merges intelligently based on schema.

        Args:
            results: List of extracted results (Pydantic model instances)
            schema: The Pydantic schema class

        Returns:
            Merged result as Pydantic model instance
        """
        if not results:
            return None

        if len(results) == 1:
            return results[0]

        try:
            # Convert all results to dicts
            result_dicts = [r.model_dump() for r in results]

            # Merge based on schema structure
            merged_dict = {}

            for key in result_dicts[0].keys():
                values = [d.get(key) for d in result_dicts]

                # Check if this field is a list (e.g., properties, components)
                if isinstance(values[0], list):
                    # Concatenate all lists, removing duplicates while preserving order
                    merged_list = []
                    seen = set()
                    for value_list in values:
                        if value_list:
                            for item in value_list:
                                # Create a hashable representation for deduplication
                                item_str = json.dumps(item, sort_keys=True, default=str)
                                if item_str not in seen:
                                    seen.add(item_str)
                                    merged_list.append(item)
                    merged_dict[key] = merged_list
                else:
                    # For non-list fields, use the first non-null value
                    merged_dict[key] = next((v for v in values if v is not None), None)

            # Create merged result instance
            merged_result = schema(**merged_dict)
            logger.info(f"Merged results: {len(merged_dict)} fields processed")
            return merged_result

        except Exception as e:
            logger.error(f"Error merging extraction results: {str(e)}")
            # Return first result as fallback
            return results[0]

    def _extract_text_for_section(self, pdf_path: str, section_config) -> str:
        """
        Extract text from PDF for a specific section based on page range config.

        Args:
            pdf_path: Path to the PDF file
            section_config: SectionConfig with optional page_range_config

        Returns:
            Extracted text for the section
        """
        try:
            import pdfplumber
        except ImportError:
            logger.error("pdfplumber library not installed")
            return ""

        section_text = ""

        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)

                # Determine page range for this section
                if section_config.page_range_config:
                    start_page, end_page = section_config.page_range_config.get_page_range(total_pages)
                    logger.info(
                        f"Section '{section_config.section_name}' using page range {start_page}-{end_page} "
                        f"({section_config.page_range_config.description or 'custom range'})"
                    )
                else:
                    start_page, end_page = 1, total_pages
                    logger.info(f"Section '{section_config.section_name}' using full document (all {total_pages} pages)")

                # Extract text from specified page range
                for page_num in range(start_page, end_page + 1):
                    if page_num <= total_pages:
                        page = pdf.pages[page_num - 1]
                        text = page.extract_text() or ""
                        if text.strip():
                            section_text += f"\n--- Page {page_num} ---\n{text}"

        except Exception as e:
            logger.error(f"Error extracting text for section {section_config.section_name}: {e}")

        return section_text

    def _split_text_into_chunks(self, text: str, chunk_size: int = 2) -> list:
        """
        Split PDF text into chunks by page.

        Args:
            text: Full text with page markers (e.g., "--- Page 1 ---\n...")
            chunk_size: Number of pages per chunk (default: 2)

        Returns:
            List of text chunks, each containing chunk_size pages
        """
        # Split by page markers
        page_pattern = r'\n--- Page (\d+) ---\n'
        pages = re.split(page_pattern, text)

        chunks = []
        current_chunk = ""
        page_count = 0

        # Process pages (skip empty strings from split)
        i = 0
        while i < len(pages):
            if pages[i].strip().isdigit():  # This is a page number
                page_num = pages[i]
                page_content = pages[i + 1] if i + 1 < len(pages) else ""

                if current_chunk:
                    current_chunk += f"\n--- Page {page_num} ---\n{page_content}"
                else:
                    current_chunk = f"--- Page {page_num} ---\n{page_content}"

                page_count += 1

                # If we've accumulated chunk_size pages, save the chunk
                if page_count >= chunk_size:
                    chunks.append(current_chunk)
                    current_chunk = ""
                    page_count = 0

                i += 2
            else:
                i += 1

        # Add remaining content as final chunk
        if current_chunk.strip():
            chunks.append(current_chunk)

        return chunks if chunks else [text]  # Return original text if no chunks created

    async def process_images(self, images: list) -> Optional[Dict[str, Any]]:
        """
        Process a list of images through the extraction pipeline.

        Args:
            images: List of PIL Image objects

        Returns:
            Dictionary with extracted data for each section or None on error
        """
        try:
            # Step 1: Check if we should force vision-based extraction (for Liner documents)
            if self.force_vision_extraction:
                # Use vision-based extraction with images
                logger.info(f"Step 2: Extracting sections using vision-based LLM with {len(images)} images...")
                results = await self._extract_from_images(images)

                if results:
                    logger.info("✅ Vision-based extraction completed successfully")
                    return results
                else:
                    logger.error("Vision-based extraction failed")
                    return None

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            return None


    async def process_pdf(self, pdf_path: str) -> Optional[Dict[str, Any]]:
        """
        Process a PDF file through the extraction pipeline.

        Extracts text from PDF and passes it to LLM for each section.
        For scanned PDFs, converts to images and uses vision-based extraction.
        Supports page range optimization to reduce AI calls.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            Dictionary with extracted data for each section or None on error
        """
        if not Path(pdf_path).exists():
            logger.error(f"PDF file not found: {pdf_path}")
            return None

        self.pdf_path = pdf_path

        try:
            import pdfplumber
        except ImportError:
            logger.error("pdfplumber library not installed")
            return None

        try:
            # Step 1: Check if we should force vision-based extraction (for Liner documents)
            if self.force_vision_extraction:
                logger.info("Step 1: Force vision-based extraction enabled (Liner document type)")
                images = await self._convert_pdf_to_images(pdf_path)

                if not images:
                    logger.error("Failed to convert PDF to images")
                    return None

                # Use vision-based extraction with images
                logger.info(f"Step 2: Extracting sections using vision-based LLM with {len(images)} images...")
                results = await self._extract_from_images(images)

                if results:
                    logger.info("✅ Vision-based extraction completed successfully")
                    return results
                else:
                    logger.error("Vision-based extraction failed")
                    return None

            # Step 1: Try to extract raw text from PDF
            logger.info("Step 1: Attempting to extract raw text from PDF...")
            full_text = ""

            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    text = page.extract_text() or ""
                    if text.strip():
                        full_text += f"\n--- Page {page_num} ---\n{text}"

            # Step 2: If no text extracted, try image-based extraction
            if not full_text.strip():
                logger.warning("No text extracted from PDF, attempting image-based extraction...")
                images = await self._convert_pdf_to_images(pdf_path)

                if not images:
                    logger.error("Failed to convert PDF to images")
                    return None

                # Use vision-based extraction with images
                logger.info(f"Step 2: Extracting sections using vision-based LLM with {len(images)} images...")
                results = await self._extract_from_images(images)

                if results:
                    logger.info("✅ Vision-based extraction completed successfully")
                    return results
                else:
                    logger.error("Vision-based extraction failed")
                    return None

            logger.info(f"Step 1 complete: Extracted {len(full_text)} characters from PDF")
            self.full_text = full_text
            self.chunk_texts["full_text"] = full_text

            # Step 2: Extract each section using LLM with text (concurrent execution)
            if self.enable_pagination:
                logger.info(f"Step 2: Extracting sections using LLM with pagination (chunk size: {self.pagination_chunk_size} pages)...")
            else:
                logger.info("Step 2: Extracting sections using LLM with text (concurrent)...")

            # Create tasks for all sections
            extraction_tasks = []
            for section_config in self.config.sections:
                # Get text for this section (may be limited by page range config)
                if section_config.page_range_config:
                    section_text = self._extract_text_for_section(pdf_path, section_config)
                else:
                    section_text = full_text

                # Decide whether to use pagination for this section
                # Use pagination only if:
                # 1. Pagination is enabled globally
                # 2. The section doesn't have a page_range_config (or has a large range)
                # 3. The section is one that can have many items (characteristics_and_properties, physical_and_chemical_data)
                use_pagination = (
                    self.enable_pagination and
                    section_config.section_name in ["characteristics_and_properties", "physical_and_chemical_data"]
                )

                # Create extraction task
                if use_pagination:
                    task = self._extract_section_with_pagination(section_config, section_text, self.pagination_chunk_size)
                else:
                    task = self._extract_section(section_config, section_text)
                extraction_tasks.append(task)

            # Execute all extraction tasks concurrently
            section_results = await asyncio.gather(*extraction_tasks, return_exceptions=True)

            # Aggregate results
            results = {}
            for section_config, result in zip(self.config.sections, section_results):
                if isinstance(result, Exception):
                    logger.warning(f"❌ Failed to extract {section_config.section_name}: {str(result)}")
                elif result:
                    results[section_config.section_name] = result.model_dump()
                    logger.info(f"✅ Extracted {section_config.section_name}")
                else:
                    logger.warning(f"❌ Failed to extract {section_config.section_name}")

            self.extraction_results = results
            logger.info("✅ Pipeline execution complete")
            return results

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            return None

    async def _upload_images_to_oss(self, images: list) -> Optional[list]:
        """
        Upload PDF images to OSS and get accessible URLs.

        Args:
            images: List of PIL Image objects

        Returns:
            List of OSS URLs or None if upload fails
        """
        try:
            from io import BytesIO
            from fastapi_app.modules.common_service.oss.oss import AliyunOSS, AzureOSS

            image_urls = []

            # Try to use Aliyun OSS first, fallback to Azure
            try:
                oss_client = AliyunOSS()
                logger.info("Using Aliyun OSS for image upload")
            except Exception as e:
                logger.warning(f"Aliyun OSS not available: {e}, trying Azure OSS")
                try:
                    oss_client = AzureOSS()
                    logger.info("Using Azure OSS for image upload")
                except Exception as e2:
                    logger.error(f"Both OSS services unavailable: {e2}")
                    return None

            # Upload each image
            for page_num, image in enumerate(images, 1):
                try:
                    # Convert PIL image to BytesIO
                    img_byte_arr = BytesIO()
                    image.save(img_byte_arr, format='PNG')
                    img_byte_arr.seek(0)

                    # Upload to OSS
                    file_name = f"pdf_page_{page_num}.png"
                    image_url = oss_client.upload_file(img_byte_arr, file_name, format='PNG')
                    image_urls.append(image_url)
                    logger.info(f"✅ Uploaded page {page_num} to OSS: {image_url}")

                except Exception as e:
                    logger.warning(f"Failed to upload page {page_num}: {str(e)}")
                    continue

            if not image_urls:
                logger.error("No images could be uploaded to OSS")
                return None

            logger.info(f"📸 Successfully uploaded {len(image_urls)} images to OSS")
            return image_urls

        except Exception as e:
            logger.error(f"OSS upload error: {e}", exc_info=True)
            return None

    async def _extract_section_from_images(self, section_config, image_urls: list):
        """
        Extract a single section from images using vision-based LLM.

        Args:
            section_config: SectionConfig for this section
            image_urls: List of image URLs

        Returns:
            Extracted result or None on error
        """
        try:
            logger.info(f"🔄 Extracting section: {section_config.section_name} from {len(image_urls)} images")

            result = await self.vision_extractor.extract_from_images(
                image_urls=image_urls,
                response_model=section_config.schema,
                system_prompt=section_config.system_prompt
            )

            return result
        except Exception as e:
            logger.error(f"Error extracting {section_config.section_name} from images: {str(e)}", exc_info=True)
            raise

    async def _extract_from_images(self, images: list) -> Optional[Dict[str, Any]]:
        """
        Extract structured data from PDF images using vision-based LLM.

        Args:
            images: List of PIL Image objects

        Returns:
            Dictionary with extracted data for each section or None on error
        """
        try:
            results = {}

            # Upload images to OSS to get accessible URLs
            # logger.info("Uploading images to OSS...")
            # image_urls = [image['url'] for image in images]

            image_urls = await self._upload_images_to_oss(images)

            if not image_urls:
                logger.error("No image URLs provided")
                return None

            # Create tasks for all sections
            extraction_tasks = []
            for section_config in self.config.sections:
                task = self._extract_section_from_images(section_config, image_urls)
                extraction_tasks.append(task)

            # Execute all extraction tasks concurrently
            section_results = await asyncio.gather(*extraction_tasks, return_exceptions=True)

            # Aggregate results
            for section_config, result in zip(self.config.sections, section_results):
                if isinstance(result, Exception):
                    logger.warning(f"❌ Failed to extract {section_config.section_name} from images: {str(result)}")
                elif result:
                    results[section_config.section_name] = result.model_dump()
                    logger.info(f"✅ Extracted {section_config.section_name} from images")
                else:
                    logger.warning(f"❌ Failed to extract {section_config.section_name} from images")

            self.extraction_results = results
            return results if results else None

        except Exception as e:
            logger.error(f"Image extraction error: {e}", exc_info=True)
            return None

    def get_pipeline_summary(self) -> Dict[str, Any]:
        """
        Get summary of the pipeline execution.

        Returns:
            Dictionary with pipeline statistics
        """
        return {
            "pdf_path": self.pdf_path,
            "full_text_length": len(self.full_text),
            "sections_extracted": len(self.extraction_results),
            "section_names": list(self.extraction_results.keys()),
            "extraction_results": self.extraction_results
        }

