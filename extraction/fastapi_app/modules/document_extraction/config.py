"""
Configuration for document extraction pipeline.
Defines section mappings, schemas, and extraction rules.
"""

from typing import Type, Optional, List, Tuple
from pydantic import BaseModel


class PageRangeConfig:
    """Configuration for page range optimization."""

    def __init__(
        self,
        first_page_only: bool = False,
        page_range: Optional[Tuple[int, Optional[int]]] = None,
        description: Optional[str] = None
    ):
        """
        Initialize page range configuration.

        Args:
            first_page_only: If True, only extract from the first page
            page_range: Tuple of (start_page, end_page) for extraction (1-indexed, inclusive)
                       e.g., (1, 3) means extract from pages 1-3
                       e.g., (3, None) means extract from page 3 to the last page
            description: Description of why this page range is used
        """
        if first_page_only and page_range:
            raise ValueError("Cannot specify both first_page_only and page_range")

        self.first_page_only = first_page_only
        self.page_range = page_range
        self.description = description

    def get_page_range(self, total_pages: int) -> Tuple[int, int]:
        """
        Get the actual page range for extraction.

        Args:
            total_pages: Total number of pages in the document

        Returns:
            Tuple of (start_page, end_page) (1-indexed, inclusive)
        """
        if self.first_page_only:
            return (1, 1)
        elif self.page_range:
            start, end = self.page_range
            # Ensure range is within bounds
            start = max(1, start)
            # If end is None, use total_pages (extract to the end)
            if end is None:
                end = total_pages
            else:
                end = min(total_pages, end)
            return (start, end)
        else:
            return (1, total_pages)

    def should_extract_page(self, page_num: int, total_pages: int) -> bool:
        """
        Check if a specific page should be extracted.

        Args:
            page_num: Page number to check (1-indexed)
            total_pages: Total number of pages in the document

        Returns:
            True if this page should be extracted
        """
        start, end = self.get_page_range(total_pages)
        return start <= page_num <= end


class SectionConfig:
    """Configuration for a document section."""

    def __init__(
        self,
        section_name: str,
        title_patterns: List[str],
        schema: Type[BaseModel],
        system_prompt: Optional[str] = None,
        description: Optional[str] = None,
        page_range_config: Optional[PageRangeConfig] = None
    ):
        """
        Initialize section configuration.

        Args:
            section_name: Unique identifier for the section (e.g., 'document_header', 'product_components')
            title_patterns: List of title patterns to match (e.g., ['Product components', 'Components'])
            schema: Pydantic model for this section's data
            system_prompt: Custom system prompt for LLM extraction
            description: Human-readable description of the section
            page_range_config: Optional PageRangeConfig for page range optimization
        """
        self.section_name = section_name
        self.title_patterns = title_patterns
        self.schema = schema
        self.system_prompt = system_prompt or self._default_system_prompt()
        self.description = description or section_name
        self.page_range_config = page_range_config
    
    def _default_system_prompt(self) -> str:
        """Generate a default system prompt based on schema."""
        return (
            f"You are a data extraction expert. Extract all information from the provided text "
            f"and return it in the exact format specified. "
            f"Return ONLY valid JSON, no other text."
        )
    
    def matches_title(self, text: str) -> bool:
        """
        Check if text matches any of the title patterns.
        
        Args:
            text: Text to check
            
        Returns:
            True if text matches any pattern
        """
        text_lower = text.strip().lower()
        return any(pattern.lower() in text_lower for pattern in self.title_patterns)


class ExtractionConfig:
    """Configuration for the entire extraction pipeline."""
    
    def __init__(self, sections: List[SectionConfig]):
        """
        Initialize extraction configuration.
        
        Args:
            sections: List of SectionConfig objects
        """
        self.sections = sections
        self._section_map = {s.section_name: s for s in sections}
    
    def get_section(self, section_name: str) -> Optional[SectionConfig]:
        """
        Get section configuration by name.
        
        Args:
            section_name: Name of the section
            
        Returns:
            SectionConfig or None if not found
        """
        return self._section_map.get(section_name)
    
    def find_section_by_title(self, title: str) -> Optional[SectionConfig]:
        """
        Find section configuration by title text.
        
        Args:
            title: Title text to match
            
        Returns:
            SectionConfig or None if no match found
        """
        for section in self.sections:
            if section.matches_title(title):
                return section
        return None
    
    def list_sections(self) -> List[str]:
        """
        List all section names.
        
        Returns:
            List of section names
        """
        return [s.section_name for s in self.sections]
    
    def get_schema_for_section(self, section_name: str) -> Optional[Type[BaseModel]]:
        """
        Get Pydantic schema for a section.
        
        Args:
            section_name: Name of the section
            
        Returns:
            Pydantic model class or None
        """
        section = self.get_section(section_name)
        return section.schema if section else None

