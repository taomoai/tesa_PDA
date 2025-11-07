"""
Pydantic schemas for PDA document extraction.
Based on the specification document structure.
"""

from typing import Optional, List
from pydantic import BaseModel, Field, conlist


class DocumentInfo(BaseModel):
    """Document header information."""
    product_name: str = Field(..., description="Product name, e.g., 'TESA 62573 PV55'")
    co: str = Field(..., description="Co number, e.g., '00'")
    pv: str = Field(..., description="PV number, e.g., '55'")
    nart: str = Field(..., description="NART number, e.g., '62573-70000-55'")
    version: str = Field(..., description="Document version, e.g., '04'")
    status: str = Field(..., description="Document status, e.g., 'Released'")
    date: str = Field(..., description="Document date, e.g., '04.09.2024'")
    product_identification: Optional[str] = Field(None, description="Product identification")


class ProductComponent(BaseModel):
    """Product component information."""
    nart: Optional[str] = Field(None, description="NART number")
    co: Optional[str] = Field(None, description="Co number")
    pr: Optional[str] = Field(None, description="Pr number")
    pv: Optional[str] = Field(None, description="PV number")
    product_identification: Optional[str] = Field(None, description="Product identification")
    value: Optional[str] = Field(None, description="Component value/weight")
    unit: Optional[str] = Field(None, description="Unit of measurement")


class PropertyItem(BaseModel):
    """Characteristic property item."""
    no: Optional[str] = Field(None, description="Item number, e.g., '01', '02'")
    item: Optional[str] = Field(None, description="Item name, e.g., 'Total weight, without liner'")
    item_no: Optional[str] = Field(None, description="Item-No. (P-number), e.g., 'P4079'")
    unit: Optional[str] = Field(None, description="Unit, e.g., 'g/m²', 'μΜ', 'cN/cm'")
    target_value_with_unit: Optional[str] = Field(None, description="Target value with unit/tolerance as a single field, e.g., '37 ± 4', '50 ±5', '10 <='")
    test_method: Optional[str] = Field(None, description="Test method code, e.g., 'J0PM0005'")
    test_type: Optional[str] = Field(None, description="Test type, e.g., 'I/SC-P', 'L'")


class CharacteristicsAndProperties(BaseModel):
    """Characteristics and properties section."""
    properties: conlist(PropertyItem, min_length=1) = Field(
        ...,
        description="List of characteristic properties extracted from the document"
    )


class SpecificationDocument(BaseModel):
    """Complete specification document structure."""
    document_info: DocumentInfo = Field(..., description="Document header information")
    product_components: conlist(ProductComponent, min_length=1) = Field(
        ...,
        description="List of product components"
    )
    characteristics_and_properties: CharacteristicsAndProperties = Field(
        ...,
        description="Characteristics and properties section"
    )


class SpecificationDocumentWrapper(BaseModel):
    """Wrapper for the complete specification document."""
    specification_document: SpecificationDocument = Field(
        ...,
        description="The complete specification document"
    )

