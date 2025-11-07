"""
PDA-specific extraction configuration.
Defines sections, schemas, and extraction rules for different document types.
Supports multiple document types (E-FER, etc.) with type-specific extraction configurations.
"""

from typing import Optional, Dict, List
from enum import Enum
from pydantic import BaseModel, Field, conlist
from fastapi_app.modules.document_extraction import SectionConfig, ExtractionConfig, PageRangeConfig


class DocumentType(str, Enum):
    """
    Supported document types for extraction.

    To add a new document type:
    1. Add a new enum value (e.g., NEWDOC = "newdoc")
    2. Update from_filename() to detect the new type
    3. Create a configuration factory function (e.g., create_newdoc_extraction_config())
    4. Register it in ExtractionConfigManager._config_factories

    See extraction_config_examples.py for examples of adding new document types.
    """
    EFERSPEC = "eferspec"  # E-FER specification documents
    LINER = "liner"  # Liner material specification documents
    BACKING = "backing"  # Backing material specification documents
    ADHESIVE = "adhesive"  # Adhesive material specification documents
    CONNECTOR_SPECS = "connector_specs"  # Connector specifications documents

    @classmethod
    def from_filename(cls, filename: str) -> "DocumentType":
        """
        Detect document type from filename.

        Filename patterns:
        - *connector* -> CONNECTOR_SPECS
        - E-FER-*.pdf -> EFERSPEC
        - *eferspec* -> EFERSPEC
        - *liner* -> LINER
        - *backing* -> BACKING
        - *adhesive* -> ADHESIVE
        - Other -> EFERSPEC (default)

        Args:
            filename: The filename to analyze

        Returns:
            DocumentType enum value
        """
        filename_lower = filename.lower()

        # Connector specifications documents
        if "connector" in filename_lower:
            return cls.CONNECTOR_SPECS

        # Adhesive material specification documents
        if "adhesive" in filename_lower:
            return cls.ADHESIVE

        # Backing material specification documents
        if "backing" in filename_lower:
            return cls.BACKING

        # Liner material specification documents
        if "liner" in filename_lower:
            return cls.LINER

        # E-FER specification documents typically have pattern like E-FER-XXXXX-XXXXX-XX-XX.pdf
        if "e-fer" in filename_lower or "eferspec" in filename_lower:
            return cls.EFERSPEC

        # Default to E-FER if no specific pattern matches
        # This can be extended with more document types in the future
        return cls.EFERSPEC


# ============================================================================
# Pydantic Schemas for Backing specification documents
# ============================================================================

class BackingProductInfo(BaseModel):
    """Product information for Backing documents."""
    tesa_nart: Optional[str] = Field(None, description="Tesa NART number, e.g., '20169-9xxxx-00'")
    trade_name_of_product: Optional[str] = Field(None, description="Trade Name of Product, e.g., 'Tenolan OCN 0003 - 1931'")
    internal_name: Optional[str] = Field(None, description="Internal name, e.g., 'PTE BLACK 0 .36'")
    material_class: Optional[str] = Field(None, description="Material class, e.g., 'PET Films Colored'")
    material_class_code: Optional[str] = Field(None, description="Material class code, e.g., 'R5201'")
    supplier_name: Optional[str] = Field(None, description="Supplier name")
    supplier_address: Optional[str] = Field(None, description="Supplier address")
    supplier_number: Optional[str] = Field(None, description="Supplier number")
    producer: Optional[str] = Field(None, description="Producer name")
    chemical_composition: Optional[str] = Field(None, description="Chemical composition description")


class PhysicalAndChemicalDataItem(BaseModel):
    """Physical and chemical data item with detailed test figure breakdown."""
    property: Optional[str] = Field(None, description="Property name, e.g., 'Thickness'")

    # Tesa test figures - broken down into components
    tesa_test_figures_value: Optional[str] = Field(None, description="Tesa test target value, e.g., '4.5'")
    tesa_test_figures_tolerance: Optional[str] = Field(None, description="Tesa test tolerance, e.g., '±0.5'")
    tesa_test_figures_unit: Optional[str] = Field(None, description="Tesa test unit, e.g., 'µm'")
    tesa_standard: Optional[str] = Field(None, description="Tesa standard/test method")

    # Supplier test figures - broken down into components
    supplier_test_figures_value: Optional[str] = Field(None, description="Supplier test target value, e.g., '4.5'")
    supplier_test_figures_tolerance: Optional[str] = Field(None, description="Supplier test tolerance, e.g., '±0.5'")
    supplier_test_figures_unit: Optional[str] = Field(None, description="Supplier test unit, e.g., 'µm'")
    supplier_standard: Optional[str] = Field(None, description="Supplier standard/test method")


class BackingTechnicalData(BaseModel):
    """
    Technical data section for Backing documents.

    Note: Changed from nested structure to direct list field.
    The field name 'items' is used to avoid double-nesting when serialized.
    """
    items: Optional[list[PhysicalAndChemicalDataItem]] = Field(
        None, description="Physical and chemical data items - list of properties with test figures"
    )


# ============================================================================
# Pydantic Schemas for Adhesive specification documents
# ============================================================================

class AdhesiveProductInfo(BaseModel):
    """Product information for Adhesive documents."""
    company: Optional[str] = Field(None, description="Company name, e.g., 'tesa'")
    nart_co_pv: Optional[str] = Field(None, description="NART CO:PV number, e.g., '14064-80000-80 CO:00 PV: 80'")
    document_type: Optional[str] = Field(None, description="Document type, e.g., 'Internal specification'")
    material_type: Optional[str] = Field(None, description="Material type, e.g., 'Coating Material'")
    date: Optional[str] = Field(None, description="Document date, e.g., '07.03.2016'")
    version: Optional[str] = Field(None, description="Document version, e.g., '01'")
    status: Optional[str] = Field(None, description="Document status, e.g., 'Released'")
    nart: Optional[str] = Field(None, description="NART number, e.g., '14064-80000-80'")
    id: Optional[str] = Field(None, description="Product ID, e.g., 'CELLO 33.135-35'")


class AdhesiveProductComponent(BaseModel):
    """Product component for Adhesive documents."""
    nart: Optional[str] = Field(None, description="NART number, e.g., '14064-90000-80'")
    product_identification: Optional[str] = Field(None, description="Product identification, e.g., 'CELLO 33.135-42 OV'")
    solids_content_kg: Optional[str] = Field(None, description="Solids content in kg, e.g., '985,92'")
    weight_of_contents_kg: Optional[str] = Field(None, description="Weight of contents in kg, e.g., '2.347,420'")
    tolerance_percent: Optional[str] = Field(None, description="Tolerance in percent, e.g., '1,00'")


class AdhesiveProductComponents(BaseModel):
    """Product components section for Adhesive documents."""
    components: Optional[list[AdhesiveProductComponent]] = Field(
        None, description="List of product components"
    )


class AdhesiveCharacteristicItem(BaseModel):
    """Characteristic property item for Adhesive documents."""
    item_no: Optional[str] = Field(None, description="Item number, e.g., '01', '02'")
    description: Optional[str] = Field(None, description="Property description, e.g., 'Solids content, in total C4000'")
    unit: Optional[str] = Field(None, description="Unit, e.g., '%'")
    target_value: Optional[str] = Field(None, description="Target value, e.g., '35'")
    target_value_unit: Optional[str] = Field(None, description="Target value unit/tolerance, e.g., '±1.8'")
    test_method: Optional[str] = Field(None, description="Test method code, e.g., 'JOPMF008'")
    test_type: Optional[str] = Field(None, description="Test type, e.g., 'F'")


class AdhesiveCharacteristicsAndProperties(BaseModel):
    """Characteristics and properties section for Adhesive documents."""
    characteristics: Optional[list[AdhesiveCharacteristicItem]] = Field(
        None, description="List of characteristic properties"
    )


# ============================================================================
# Pydantic Schemas for Connector Specs specification documents
# ============================================================================

class TextCoordinate(BaseModel):
    """Coordinates of text location in image."""
    x: Optional[float] = Field(None, description="X coordinate (left position in pixels)")
    y: Optional[float] = Field(None, description="Y coordinate (top position in pixels)")
    width: Optional[float] = Field(None, description="Width of text bounding box in pixels")
    height: Optional[float] = Field(None, description="Height of text bounding box in pixels")


class ExtractionBasis(BaseModel):
    """Record of extraction basis for a single field."""
    field_name: str = Field(..., description="Field name")
    value: Optional[str] = Field(None, description="Extracted value")
    basis: Optional[str] = Field(None, description="Extraction basis/source location in document")
    context: Optional[str] = Field(None, description="Context text surrounding the extracted value (for text-based extractions)")
    reasoning: Optional[str] = Field(None, description="Reasoning for why this value was selected")
    page_number: Optional[str] = Field(None, description="Page number where extracted")
    coordinates: Optional[TextCoordinate] = Field(None, description="Coordinates of text location in the image (x, y, width, height in pixels)")


class ConnectorIdentity(BaseModel):
    """Identity/基础标识 information for Connector Specs documents."""
    part_number: Optional[str] = Field(None, description="料号 - Unique part number, e.g., '0930071A02'")
    part_description: Optional[str] = Field(None, description="零件描述 - Structure + Pin count + angle + plating, e.g., '140-way right-angle connector'")
    series_family: Optional[str] = Field(None, description="系列/家族代号 - Series/Family code, e.g., 'TE 1438136-1'")
    revision: Optional[str] = Field(None, description="版本号 - Revision number, e.g., 'Rev AA'")
    date_code: Optional[str] = Field(None, description="日期代码 - Manufacturing date code")
    lot_cavity_number: Optional[str] = Field(None, description="批次/模腔号 - Lot/Cavity number for traceability")
    net_weight: Optional[str] = Field(None, description="净重 - Net weight")
    extraction_basis: Optional[List[ExtractionBasis]] = Field(None, description="Extraction basis for each field")


class ConnectorMechanical(BaseModel):
    """Mechanical/机械参数 parameters for Connector Specs documents."""
    pin_count: Optional[str] = Field(None, description="针数 - Total pin count, e.g., '140-way / 190-way'")
    pin_rows: Optional[str] = Field(None, description="排数 - Number of rows, e.g., '2 rows'")
    pin_pitch: Optional[str] = Field(None, description="针脚间距 - Pin pitch in mm, e.g., '2.54 mm'")
    pin_size: Optional[str] = Field(None, description="针脚尺寸 - Pin size (width/thickness/shape), e.g., '0.64 mm square / 1.5 mm rectangular'")
    pin_type_orientation: Optional[str] = Field(None, description="针型/出针方向 - Pin type/orientation, e.g., 'Right-angle (90°)'")
    true_position: Optional[str] = Field(None, description="位置公差 - True position tolerance, e.g., '≤ 0.35 mm'")
    mounting_type: Optional[str] = Field(None, description="安装方式 - Mounting type, e.g., 'THT (wave solder)'")
    pcb_protrusion: Optional[str] = Field(None, description="插板长度 - PCB protrusion length, e.g., '1.75 mm'")
    housing_dimensions: Optional[str] = Field(None, description="外形尺寸 - Housing dimensions (W×H×D)")
    extraction_basis: Optional[List[ExtractionBasis]] = Field(None, description="Extraction basis for each field")


class ConnectorElectrical(BaseModel):
    """Electrical/电气参数 parameters for Connector Specs documents."""
    max_voltage: Optional[str] = Field(None, description="最大电压 - Maximum voltage, e.g., '26V / 14V continuous'")
    current_per_pin: Optional[str] = Field(None, description="单PIN电流 - Current per pin in Amperes, e.g., '0.64 mm: 7A, 1.5 mm: 15A'")
    contact_resistance: Optional[str] = Field(None, description="接触电阻 - Contact resistance in mΩ, e.g., '≤ 20 mΩ'")
    dielectric_withstand: Optional[str] = Field(None, description="介电强度 - Dielectric withstand voltage, e.g., '1000 V'")
    extraction_basis: Optional[List[ExtractionBasis]] = Field(None, description="Extraction basis for each field")


class ConnectorEnvironmental(BaseModel):
    """Environmental/Reliability/环境与可靠性 parameters for Connector Specs documents."""
    operating_temp: Optional[str] = Field(None, description="工作温度 - Operating temperature range, e.g., '-40°C to +105°C / +125°C'")
    solder_temp: Optional[str] = Field(None, description="焊接温度 - Solder temperature limit, e.g., '260°C'")
    durability: Optional[str] = Field(None, description="插拔寿命 - Durability/insertion cycles, e.g., '≥ 10 cycles'")
    seal_requirement: Optional[str] = Field(None, description="密封等级 - Seal requirement, e.g., 'Pass immersion test'")
    extraction_basis: Optional[List[ExtractionBasis]] = Field(None, description="Extraction basis for each field")


class ConnectorMaterial(BaseModel):
    """Material/材料 information for Connector Specs documents."""
    housing_resin: Optional[str] = Field(None, description="胶壳材料 - Housing resin material, e.g., 'GE Valox 508R (PBT)'")
    resin: Optional[str] = Field(None, description="树脂 - Resin material")
    resin_regrind_allowance: Optional[str] = Field(None, description="回料比例 - Resin regrind allowance, e.g., '≤ 15%'")
    pin_base_material: Optional[str] = Field(None, description="PIN基材 - Pin base material, e.g., 'Brass (0.64 mm) / Copper (1.5 mm)'")
    plating_material: Optional[str] = Field(None, description="表面镀层 - Plating material, e.g., 'Ni 2–3.5 μm + Sn 2.5–4 μm + Ag 2–4 μm'")
    extraction_basis: Optional[List[ExtractionBasis]] = Field(None, description="Extraction basis for each field")


# ============================================================================
# Pydantic Schemas for Liner specification documents
# ============================================================================

class LinerSummaryInfo(BaseModel):
    """Summary information for Liner documents."""
    tesa_nart: Optional[str] = Field(None, description="Tesa NART number, e.g., '21061-9xxxx-xx'")
    version: Optional[str] = Field(None, description="Document version, e.g., '01'")
    rdb_id: Optional[str] = Field(None, description="RDB ID, e.g., '22635'")
    supplier: Optional[str] = Field(None, description="Supplier name")
    supplier_address: Optional[str] = Field(None, description="Supplier address")
    supplier_number: Optional[str] = Field(None, description="Supplier number, e.g., 'AP0120'")
    producer: Optional[str] = Field(None, description="Producer name")
    supplier_trade_name: Optional[str] = Field(None, description="Supplier trade name")
    internal_tesa_name: Optional[str] = Field(None, description="Internal Tesa name")
    material_class: Optional[str] = Field(None, description="Material class description")
    material_class_code: Optional[str] = Field(None, description="Material class code, e.g., 'R6240'")
    chemical_composition: Optional[str] = Field(None, description="Chemical composition description")


class SensoryCharacteristic(BaseModel):
    """Sensory characteristic item."""
    id: Optional[str] = Field(None, description="Item ID, e.g., '1.1.1'")
    property: Optional[str] = Field(None, description="Property name, e.g., 'Colour'")
    requirement: Optional[str] = Field(None, description="Requirement description")
    test_method: Optional[str] = Field(None, description="Test method description")


class PhysicalDataItem(BaseModel):
    """Physical data item."""
    id: Optional[str] = Field(None, description="Item ID, e.g., '1.2.1'")
    property: Optional[str] = Field(None, description="Property name, e.g., 'Thickness'")
    limits: Optional[str] = Field(None, description="Limits/range, e.g., '50 ± 4'")
    unit: Optional[str] = Field(None, description="Unit, e.g., 'μm'")
    test_method: Optional[str] = Field(None, description="Test method description")


class SiliconeCoatingWeightItem(BaseModel):
    """Silicone coating weight item."""
    id: Optional[str] = Field(None, description="Item ID, e.g., '1.3.1'")
    property: Optional[str] = Field(None, description="Property name")
    limits: Optional[str] = Field(None, description="Limits/range")
    unit: Optional[str] = Field(None, description="Unit")
    test_method: Optional[str] = Field(None, description="Test method description")


class ReleaseForceItem(BaseModel):
    """Release force item."""
    id: Optional[str] = Field(None, description="Item ID, e.g., '1.4.1'")
    property: Optional[str] = Field(None, description="Property name")
    limits: Optional[str] = Field(None, description="Limits/range")
    unit: Optional[str] = Field(None, description="Unit")
    test_method: Optional[str] = Field(None, description="Test method description")


class LossOfPeelAdhesionItem(BaseModel):
    """Loss of peel adhesion item."""
    id: Optional[str] = Field(None, description="Item ID, e.g., '1.5.1'")
    property: Optional[str] = Field(None, description="Property name")
    limits: Optional[str] = Field(None, description="Limits/range")
    unit: Optional[str] = Field(None, description="Unit")
    test_method: Optional[str] = Field(None, description="Test method description")


class TechnicalDataNotes(BaseModel):
    """Notes section for technical data."""
    critical_properties: Optional[str] = Field(None, description="Critical properties note")
    test_climate: Optional[str] = Field(None, description="Test climate conditions")
    tolerances: Optional[str] = Field(None, description="Tolerance information")
    sample_testing_time: Optional[str] = Field(None, description="Sample testing time information")
    test_methods: Optional[str] = Field(None, description="Test methods information")


class AnchorageOfPrintInkItem(BaseModel):
    """Anchorage of print ink item."""
    id: Optional[str] = Field(None, description="Item ID, e.g., '1.6.1'")
    property: Optional[str] = Field(None, description="Property name, e.g., 'Silicone anchorage of print ink'")
    requirement: Optional[str] = Field(None, description="Requirement description")
    test_method: Optional[str] = Field(None, description="Test method description")

class LinerTechnicalData(BaseModel):
    """Technical data section for Liner documents."""
    sensory_characteristics: Optional[dict | list[SensoryCharacteristic] | str] = Field(
        None, description="Sensory characteristics (can be object, list, or string)"
    )
    physical_data: Optional[dict | list[PhysicalDataItem] | str] = Field(
        None, description="Physical data items (can be object, list, or string)"
    )
    silicone_coating_weight: Optional[dict | list[SiliconeCoatingWeightItem] | str] = Field(
        None, description="Silicone coating weight items (can be object, list, or string)"
    )
    release_force: Optional[dict | list[ReleaseForceItem] | str] = Field(
        None, description="Release force items (can be object, list, or string)"
    )
    loss_of_peel_adhesion: Optional[dict | list[LossOfPeelAdhesionItem] | str] = Field(
        None, description="Loss of peel adhesion items (can be object, list, or string)"
    )
    anchorage_of_print_ink: Optional[dict | list[AnchorageOfPrintInkItem] | str] = Field(
        None, description="Anchorage of print ink items (can be object, list, or string)"
    )


# ============================================================================
# Pydantic Schemas for E-FER specification documents
# ============================================================================

class DocumentInfo(BaseModel):
    """Document header information."""
    product_name: str = Field(..., description="Product name, e.g., 'TESA 62573 PV55'")
    co: str = Field(..., description="Co number, e.g., '00'")
    pv: str = Field(..., description="PV number, e.g., '55'")
    nart: str = Field(..., description="NART number, e.g., '62573-70000-55'")
    version: str = Field(..., description="Document version, e.g., '04'")
    status: str = Field(..., description="Document status, e.g., 'Released'")
    date: str = Field(..., description="Document date, e.g., '04.09.2024'")
    product_identification: Optional[str] = Field(default=None, description="Product identification")


class ProductComponent(BaseModel):
    """Product component information."""
    nart: Optional[str] = Field(None, description="NART number")
    co: Optional[str] = Field(None, description="Co number")
    pr: Optional[str] = Field(None, description="Pr number")
    pv: Optional[str] = Field(None, description="PV number")
    product_identification: Optional[str] = Field(None, description="Product identification")
    value: Optional[str] = Field(None, description="Component value/weight")
    unit: Optional[str] = Field(None, description="Unit of measurement")
    nart_variant: Optional[str] = Field(
        None,
        description="NART variant/subclass if this component belongs to a specific NART variant (e.g., '68537-80000-40')"
    )


class ProductComponentGroup(BaseModel):
    """Group of product components (alternatives separated by OR)."""
    components: conlist(ProductComponent, min_length=1) = Field(
        ...,
        description="List of product components in this group (alternatives)"
    )
    is_alternative_group: bool = Field(
        default=False,
        description="True if components in this group are alternatives (separated by OR)"
    )


class ProductComponentsList(BaseModel):
    """List of product component groups."""
    primary_nart: Optional[str] = Field(
        None,
        description="Primary NART number from document header (e.g., '68537-70000-40')"
    )
    component_groups: conlist(ProductComponentGroup, min_length=1) = Field(
        ...,
        description="List of product component groups"
    )


class PropertyItem(BaseModel):
    """Characteristic property item."""
    no: Optional[str] = Field(None, description="Item number, e.g., '01', '02'")
    item: Optional[str] = Field(None, description="Item name, e.g., 'Total weight, without liner'. If multi-line, merge all lines with space or newline as appropriate.")
    item_no: Optional[str] = Field(None, description="Item-No. (P-number), e.g., 'P4079'")
    unit: Optional[str] = Field(None, description="Unit, e.g., 'g/m²', 'μΜ', 'cN/cm'")
    target_value_with_unit: Optional[str] = Field(None, description="Target value with tolerance/range WITHOUT surrounding parentheses, e.g., '37 ± 4', '50 ±5', '<= 10', '1.0 - 1.9', 'i.O. / OK'")
    target_value_with_unit_extra_info: Optional[str] = Field(None, description="Extra explanatory notes/references related to target value (NOT test methods), e.g., 's. Sonstige', 'Hinweise / see indications'")
    test_method: Optional[str] = Field(None, description="Test method code, e.g., 'J0PM0005'. If multi-line, merge all lines with space or newline as appropriate.")
    test_type: Optional[str] = Field(None, description="Test type, e.g., 'I/SC-P', 'L'")


class CharacteristicsAndProperties(BaseModel):
    """Characteristics and properties section."""
    properties: conlist(PropertyItem, min_length=1) = Field(
        ...,
        description="List of characteristic properties"
    )


# ============================================================================
# Section Configurations for Liner specification documents
# ============================================================================

def create_liner_extraction_config() -> ExtractionConfig:
    """
    Create extraction configuration for Liner specification documents.

    Liner documents contain:
    - Summary information (product info, supplier, material class) - typically on first page
    - Technical data (sensory characteristics, physical data, coating weight, release force, etc.) - throughout document

    Page Range Optimization:
    - summary_info: Only extract from first page (first_page_only=True)
      Reason: Product information, supplier details, and material class are typically on the first page
    - technical_data: Extract from all pages (no page range restriction)
      Reason: Technical specifications and test data can span multiple pages

    Returns:
        ExtractionConfig with all Liner sections
    """
    sections = [
        SectionConfig(
            section_name="summary_info",
            title_patterns=["Summary", "summaryInfo", "Product Information", "Material Information", "Tesa NART"],
            schema=LinerSummaryInfo,
            page_range_config=PageRangeConfig(
                first_page_only=True,
                description="Summary information is typically on the first page only"
            ),
            system_prompt=(
                "You are a data extraction expert specializing in material specification documents. "
                "Extract ALL summary information from the Liner document. Look for:\n"
                "- Tesa NART number (e.g., '21061-9xxxx-xx')\n"
                "- Version number (e.g., '01')\n"
                "- RDB ID\n"
                "- Supplier name and address\n"
                "- Supplier number\n"
                "- Producer name\n"
                "- Supplier trade name (commercial product name)\n"
                "- Internal Tesa name\n"
                "- Material class and material class code\n"
                "- Chemical composition\n"
                "Search the entire document for these fields. They may appear in different sections or pages. "
                "Extract exact values as they appear in the document.\n\n"
                "IMPORTANT: Return ONLY valid JSON with these exact field names:\n"
                "{\n"
                "  \"tesa_nart\": \"value or null\",\n"
                "  \"version\": \"value or null\",\n"
                "  \"rdb_id\": \"value or null\",\n"
                "  \"supplier\": \"value or null\",\n"
                "  \"supplier_address\": \"value or null\",\n"
                "  \"supplier_number\": \"value or null\",\n"
                "  \"producer\": \"value or null\",\n"
                "  \"supplier_trade_name\": \"value or null\",\n"
                "  \"internal_tesa_name\": \"value or null\",\n"
                "  \"material_class\": \"value or null\",\n"
                "  \"material_class_code\": \"value or null\",\n"
                "  \"chemical_composition\": \"value or null\"\n"
                "}"
            ),
            description="Summary information for Liner documents"
        ),
        SectionConfig(
            section_name="technical_data",
            title_patterns=["Technical Data", "technicalData", "Characteristics", "Properties", "Test Data"],
            schema=LinerTechnicalData,
            system_prompt=(
                "You are a data extraction expert specializing in technical specifications and material properties. "
                "Extract ALL technical data from the Liner document. Look for these sections:\n"
                "1. SENSORY CHARACTERISTICS (1.1): colour, surface quality, silicone layer, silicone anchorage\n"
                "2. PHYSICAL DATA (1.2): thickness, weight per unit area, tensile force, elongation, shrinkage, moisture\n"
                "3. SILICONE COATING WEIGHT (1.3): weight values and units for easy side and tight side\n"
                "4. RELEASE FORCE (1.4): force values and units for different materials (natural rubber, acrylic) and sides\n"
                "5. LOSS OF PEEL ADHESION (1.5): adhesion loss values for easy side and tight side\n"
                "6. ANCHORAGE OF PRINT INK (1.6): For each item (1.6.1, 1.6.2, etc.), extract:\n"
                "   - id: item number (e.g., '1.6.1', '1.6.2')\n"
                "   - property: test name/description (e.g., 'Anchorage on dense paper side')\n"
                "   - requirement: test requirement/acceptance criteria\n"
                "   - test_method: test method code/standard (e.g., 'JOPMi031', 'Tesa 4124 at RT', 'JOPMi0133')\n"
                "For each data item, extract: id, property name, limits/requirement, unit, and test method. "
                "Search all pages of the document. Extract exact values and units as they appear. "
                "Include all tables, specifications, and test results found in the document.\n\n"
                "IMPORTANT: Return ONLY valid JSON with these exact field names:\n"
                "{\n"
                "  \"sensory_characteristics\": [list of items or null],\n"
                "  \"physical_data\": [list of items or null],\n"
                "  \"silicone_coating_weight\": [list of items or null],\n"
                "  \"release_force\": [list of items or null],\n"
                "  \"loss_of_peel_adhesion\": [list of items or null],\n"
                "  \"anchorage_of_print_ink\": [{\"id\": \"1.6.1\", \"property\": \"...\", \"requirement\": \"...\", \"test_method\": \"...\"}, ...]\n"
                "}"
            ),
            description="Technical data section for Liner documents"
        )
    ]

    return ExtractionConfig(sections)


# ============================================================================
# Section Configurations for Backing specification documents
# ============================================================================

def create_backing_extraction_config() -> ExtractionConfig:
    """
    Create extraction configuration for Backing specification documents.

    Backing documents contain:
    - Product information (NART, OCN, trade name, material class, supplier info, etc.) - typically on first page
    - Physical and chemical data (properties with Tesa and supplier test figures and standards) - throughout document

    Page Range Optimization:
    - product_info: Only extract from first page (first_page_only=True)
      Reason: Product information, trade name, material class, and supplier details are typically on the first page
    - physical_and_chemical_data: Extract from all pages (no page range restriction)
      Reason: Technical data tables can span multiple pages

    Returns:
        ExtractionConfig with all Backing sections
    """
    sections = [
        SectionConfig(
            section_name="product_info",
            title_patterns=["Product Information", "productInfo", "Product Details", "Material Information"],
            schema=BackingProductInfo,
            page_range_config=PageRangeConfig(
                first_page_only=True,
                description="Product information is typically on the first page only"
            ),
            system_prompt=(
                "You are a data extraction expert specializing in material specification documents. "
                "Extract ALL product information from the Backing document. Look for:\n"
                "- Tesa NART number (e.g., '20532-9xxxx-xx')\n"
                "- Trade Name of Product (e.g., 'Hostaphan TT 4.5') - CRITICAL: This is often in a table with 'Trade Name of Product' label\n"
                "- Internal name (e.g., 'PTE BLACK')\n"
                "- Material class (e.g., 'PET Films')\n"
                "- Material class code (e.g., 'R5201')\n"
                "- Supplier name and address\n"
                "- Supplier number\n"
                "- Producer name\n"
                "- Chemical composition\n"
                "Search the entire document for these fields. They may appear in different sections, tables, or pages. "
                "Extract exact values as they appear in the document.\n"
                "CRITICAL: Look for 'Trade Name of Product' field in specification tables - this is different from internal names.\n\n"
                "IMPORTANT: Return ONLY valid JSON with these exact field names:\n"
                "{\n"
                "  \"tesa_nart\": \"value or null\",\n"
                "  \"trade_name_of_product\": \"value or null\",\n"
                "  \"internal_name\": \"value or null\",\n"
                "  \"material_class\": \"value or null\",\n"
                "  \"material_class_code\": \"value or null\",\n"
                "  \"supplier_name\": \"value or null\",\n"
                "  \"supplier_address\": \"value or null\",\n"
                "  \"supplier_number\": \"value or null\",\n"
                "  \"producer\": \"value or null\",\n"
                "  \"chemical_composition\": \"value or null\"\n"
                "}"
            ),
            description="Product information for Backing documents"
        ),
        SectionConfig(
            section_name="physical_and_chemical_data",
            title_patterns=["Physical and Chemical Data", "physicalAndChemicalData", "Technical Data", "Properties", "Test Data"],
            schema=BackingTechnicalData,
            system_prompt=(
                "You are a data extraction expert specializing in technical specifications and material properties. "
                "Extract ALL rows from the physical and chemical data table(s) in the Backing document.\n\n"
                "TABLE EXTRACTION RULES:\n"
                "1. Identify all tables containing physical and chemical data properties\n"
                "2. Extract EVERY ROW from these tables - do not skip any rows\n"
                "3. Each row represents one property with its test figures and standards\n"
                "4. The table typically has columns for:\n"
                "   - Property name (left column)\n"
                "   - Tesa test figures (value, tolerance, unit)\n"
                "   - Tesa standard/method\n"
                "   - Supplier test figures (value, tolerance, unit)\n"
                "   - Supplier standard/method\n\n"
                "EXTRACTION RULES FOR EACH ROW:\n"
                "- property: Extract the property name from the first column (e.g., 'Thickness', 'Weight per unit area', 'Tensile strength MD', 'Shrinkage CD', 'Halogen content')\n"
                "- tesa_test_figures_value: Extract the main value from Tesa column (e.g., '2', '≥4', 'Not detected', '4,400', '0-3.0')\n"
                "- tesa_test_figures_tolerance: Extract tolerance if present (e.g., '±0.5', '±1.8'), otherwise null\n"
                "- tesa_test_figures_unit: Extract unit if present (e.g., 'µm', 'g/m²', 'N/cm', '%', 'ppm'), otherwise null\n"
                "- tesa_standard: Extract Tesa standard/test method code (e.g., 'J0PMC002', 'DIN 53370')\n"
                "- supplier_test_figures_value: Extract the main value from Supplier column\n"
                "- supplier_test_figures_tolerance: Extract tolerance if present, otherwise null\n"
                "- supplier_test_figures_unit: Extract unit if present, otherwise null\n"
                "- supplier_standard: Extract Supplier standard/test method code\n\n"
                "VALUE PARSING RULES:\n"
                "1. For '4.5 ± 0.5 µm': value='4.5', tolerance='±0.5', unit='µm'\n"
                "2. For '36±1.8 µm': value='36', tolerance='±1.8', unit='µm'\n"
                "3. For '0-3.0%': value='0-3.0', tolerance=null, unit='%'\n"
                "4. For '≥4 N/cm': value='≥4', tolerance=null, unit='N/cm'\n"
                "5. For 'Not detected': value='Not detected', tolerance=null, unit=null\n"
                "6. For '4,400 ppm': value='4,400', tolerance=null, unit='ppm'\n"
                "7. For 'According to reference sample': value='According to reference sample', tolerance=null, unit=null\n"
                "8. For 'Density =1.4 g/cm³': value='Density =1.4', tolerance=null, unit='g/cm³'\n\n"
                "CRITICAL REQUIREMENTS:\n"
                "- Extract EVERY row from the table - do not skip any rows\n"
                "- If a row exists in the table, it MUST appear in the output\n"
                "- Do not filter or omit rows based on content\n"
                "- Search all pages for all tables with physical and chemical data\n"
                "- Extract exact values and units as they appear in the document\n\n"
                "IMPORTANT: Return ONLY valid JSON with this exact field name:\n"
                "{\n"
                "  \"items\": [\n"
                "    {\n"
                "      \"property\": \"...\",\n"
                "      \"tesa_test_figures_value\": \"...\",\n"
                "      \"tesa_test_figures_tolerance\": \"...\",\n"
                "      \"tesa_test_figures_unit\": \"...\",\n"
                "      \"tesa_standard\": \"...\",\n"
                "      \"supplier_test_figures_value\": \"...\",\n"
                "      \"supplier_test_figures_tolerance\": \"...\",\n"
                "      \"supplier_test_figures_unit\": \"...\",\n"
                "      \"supplier_standard\": \"...\"\n"
                "    },\n"
                "    ...\n"
                "  ]\n"
                "}"
            ),
            description="Physical and chemical data section for Backing documents"
        )
    ]

    return ExtractionConfig(sections)


# ============================================================================
# Section Configurations for Adhesive specification documents
# ============================================================================

def create_adhesive_extraction_config() -> ExtractionConfig:
    """
    Create extraction configuration for Adhesive specification documents.

    Adhesive documents contain:
    - Product information (company, NART, document type, material type, date, version, status, ID) - typically on first page
    - Product components (list of components with NART, identification, solids content, weight, tolerance) - typically on first few pages
    - Characteristics and properties (list of properties with item number, description, unit, target value, test method) - throughout document

    Page Range Optimization:
    - product_info: Only extract from first page (first_page_only=True)
      Reason: Product information is typically on the first page only
    - product_components: Extract from first 3 pages (page_range=(1, 3))
      Reason: Product components table is typically in the first few pages
    - characteristics_and_properties: Extract from all pages (no page range restriction)
      Reason: Characteristics and properties can span multiple pages

    Returns:
        ExtractionConfig with all Adhesive sections
    """
    sections = [
        SectionConfig(
            section_name="product_info",
            title_patterns=["Product Information", "productInfo", "Product Details", "Material Information"],
            schema=AdhesiveProductInfo,
            page_range_config=PageRangeConfig(
                first_page_only=True,
                description="Product information is typically on the first page only"
            ),
            system_prompt=(
                "You are a data extraction expert specializing in adhesive material specification documents. "
                "Extract ALL product information from the Adhesive document. Look for:\n"
                "- Company name (e.g., 'tesa')\n"
                "- NART CO:PV number (e.g., '14064-80000-80 CO:00 PV: 80')\n"
                "- Document type (e.g., 'Internal specification')\n"
                "- Material type (e.g., 'Coating Material')\n"
                "- Date (e.g., '07.03.2016')\n"
                "- Version (e.g., '01')\n"
                "- Status (e.g., 'Released')\n"
                "- NART number (e.g., '14064-80000-80')\n"
                "- Product ID (e.g., 'CELLO 33.135-35')\n"
                "Search the entire document for these fields. They may appear in different sections or pages. "
                "Extract exact values as they appear in the document.\n\n"
                "IMPORTANT: Return ONLY valid JSON with these exact field names:\n"
                "{\n"
                "  \"company\": \"value or null\",\n"
                "  \"nart_co_pv\": \"value or null\",\n"
                "  \"document_type\": \"value or null\",\n"
                "  \"material_type\": \"value or null\",\n"
                "  \"date\": \"value or null\",\n"
                "  \"version\": \"value or null\",\n"
                "  \"status\": \"value or null\",\n"
                "  \"nart\": \"value or null\",\n"
                "  \"id\": \"value or null\"\n"
                "}"
            ),
            description="Product information for Adhesive documents"
        ),
        SectionConfig(
            section_name="product_components",
            title_patterns=["Product Components", "productComponents", "Components", "Component List"],
            schema=AdhesiveProductComponents,
            system_prompt=(
                "You are a data extraction expert specializing in adhesive material specification documents. "
                "Extract ALL product components from the Adhesive document. Look for a table or list containing:\n"
                "- NART number (e.g., '14064-90000-80')\n"
                "- Product identification (e.g., 'CELLO 33.135-42 OV')\n"
                "- Solids content in kg (e.g., '985,92')\n"
                "- Weight of contents in kg (e.g., '2.347,420')\n"
                "- Tolerance in percent (e.g., '1,00')\n\n"
                "EXTRACTION RULES:\n"
                "1. Extract EVERY component from the table - do not skip any rows\n"
                "2. For each component, extract all fields exactly as they appear\n"
                "3. If a field is not present or is empty, use null\n"
                "4. Preserve the original formatting of numbers (e.g., '985,92' not '985.92')\n\n"
                "IMPORTANT: Return ONLY valid JSON with this exact field name:\n"
                "{\n"
                "  \"components\": [\n"
                "    {\n"
                "      \"nart\": \"...\",\n"
                "      \"product_identification\": \"...\",\n"
                "      \"solids_content_kg\": \"...\",\n"
                "      \"weight_of_contents_kg\": \"...\",\n"
                "      \"tolerance_percent\": \"...\"\n"
                "    },\n"
                "    ...\n"
                "  ]\n"
                "}"
            ),
            description="Product components section for Adhesive documents"
        ),
        SectionConfig(
            section_name="characteristics_and_properties",
            title_patterns=["Characteristics and Properties", "characteristicsAndProperties", "Properties", "Test Data"],
            schema=AdhesiveCharacteristicsAndProperties,
            system_prompt=(
                "You are a data extraction expert specializing in adhesive material specification documents. "
                "Extract ALL characteristics and properties from the Adhesive document. Look for a table containing:\n"
                "- Item number (e.g., '01', '02')\n"
                "- Description (e.g., 'Solids content, in total C4000')\n"
                "- Unit (e.g., '%')\n"
                "- Target value (e.g., '35')\n"
                "- Target value unit/tolerance (e.g., '±1.8')\n"
                "- Test method (e.g., 'JOPMF008')\n"
                "- Test type (e.g., 'F')\n\n"
                "EXTRACTION RULES:\n"
                "1. Extract EVERY row from the table - do not skip any rows\n"
                "2. For each property, extract all fields exactly as they appear\n"
                "3. If a field is not present or is empty, use null\n"
                "4. Search all pages of the document for all tables with characteristics and properties\n"
                "5. Extract exact values as they appear in the document\n\n"
                "IMPORTANT: Return ONLY valid JSON with this exact field name:\n"
                "{\n"
                "  \"characteristics\": [\n"
                "    {\n"
                "      \"item_no\": \"...\",\n"
                "      \"description\": \"...\",\n"
                "      \"unit\": \"...\",\n"
                "      \"target_value\": \"...\",\n"
                "      \"target_value_unit\": \"...\",\n"
                "      \"test_method\": \"...\",\n"
                "      \"test_type\": \"...\"\n"
                "    },\n"
                "    ...\n"
                "  ]\n"
                "}"
            ),
            description="Characteristics and properties section for Adhesive documents"
        )
    ]

    return ExtractionConfig(sections)


# ============================================================================
# Section Configurations for Connector Specs specification documents
# ============================================================================

def create_connector_specs_extraction_config() -> ExtractionConfig:
    """
    Create extraction configuration for Connector Specs specification documents.

    Connector Specs documents contain multiple categories of specifications:
    - Identity information (part number, description, series, revision, etc.) - typically on first page
    - Mechanical parameters (pin count, pitch, size, orientation, dimensions, etc.) - throughout document
    - Electrical parameters (voltage, current, resistance, dielectric) - throughout document
    - Environmental/Reliability parameters (temperature, durability, seal) - throughout document
    - Material information (housing resin, plating, etc.) - throughout document

    Page Range Optimization:
    - Each section extracts from all pages (no page range restriction)
      Reason: Connector specifications can be distributed across multiple pages

    Returns:
        ExtractionConfig with all Connector Specs sections
    """
    sections = [
        SectionConfig(
            section_name="identity",
            title_patterns=["Identity", "Product Information", "Part Number", "基础标识", "料号"],
            schema=ConnectorIdentity,
            system_prompt=(
                "You are a data extraction expert specializing in connector specification documents. "
                "Extract ONLY Identity/基础标识 (Basic Identification) information from the document.\n\n"



                "EXTRACTION PRIORITY:\n"
                "⭐ PRIORITY 1 (HIGHEST): Extract from TEXT content in the document\n"
                "   - Look for text-based information in headers, tables, and specification sections\n"
                "   - This is the most reliable source for identity information\n"
                "⭐ PRIORITY 2: Extract from ENGINEERING DRAWINGS/DIAGRAMS if text is not available\n"
                "   - Only use visual information if the same field cannot be found in text\n"
                "⭐ FINAL RULE: If you find the same field in both text and drawings, ALWAYS prefer the TEXT version\n\n"

                "IDENTITY/基础标识 FIELDS AND EXTRACTION GUIDANCE:\n"
                "- part_number: [MUST] Unique part/material number (料号) - The unique identifier for this connector part\n"
                "  * EXTRACT WHEN: The document explicitly contains a field labeled 'Part No.', 'Part Number', 'P/N', 'Material Number', or '料号'\n"
                "  * EXTRACT WHEN: The value appears in the document header/title page with a clear label\n"
                "  * EXTRACT WHEN: The value is in a structured format (e.g., 'Part No.: 114-78033', 'P/N: 0930071A02')\n"
                "  * EXTRACT WHEN: The value is in the first page, typically in a specification table or header section\n"
                "  * EXAMPLE: '0930071A02', '28408900001', '114-78033', '09R31699A'\n"
                "  * DO NOT EXTRACT: If the number appears without a clear label (e.g., just '114-78033' in a title without 'Part No.' label)\n"
                "  * DO NOT EXTRACT: If inferred from filename or other non-document sources\n"
                "  * DO NOT EXTRACT: If it's a revision number or date code mixed with the part number\n"
                "  * SET TO NULL: If no clearly labeled part number field exists\n\n"

                "- part_description: [MUST] Complete product description (零件描述) - Describes structure, pin count, type, angle, and plating\n"
                "  * EXTRACT WHEN: The document has an explicit 'Description', 'Title', 'Product Name', or '零件描述' field\n"
                "  * EXTRACT WHEN: The description is a single, complete text string in the document (typically on first page)\n"
                "  * EXTRACT WHEN: The description includes key information like: connector type + pin count + angle + plating\n"
                "  * EXTRACT ONLY: The exact text as it appears in the document (preserve all details)\n"
                "  * EXAMPLE: 'Connector, 140 Pin, Right Angle, Gold Plated', 'Receptacle, 190 Way, Straight, Tin Plated'\n"
                "  * DO NOT EXTRACT: If you need to combine information from multiple locations\n"
                "  * DO NOT EXTRACT: If you need to rephrase or interpret the text\n"
                "  * DO NOT EXTRACT: If it's just a generic product name without specific details\n"
                "  * SET TO NULL: If no explicit description field exists\n\n"

                "- series_family: Series or family code designation\n"
                "  * EXTRACT WHEN: The document explicitly contains a field labeled 'Series', 'Family', 'Family Code', 'Product Family', or '系列/家族代号'\n"
                "  * EXTRACT WHEN: The value is clearly marked and distinct from other identifiers\n"
                "  * DO NOT EXTRACT: If inferred from part numbers or other identifiers\n"
                "  * DO NOT EXTRACT: If you need to parse or interpret the part number to extract this\n"
                "  * SET TO NULL: If no clearly labeled series/family field exists\n\n"

                "- revision: Document or part revision number\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Ver:', 'Version', 'Rev:', 'Revision', or 'Document Version' label\n"
                "  * EXTRACT WHEN: The value is clearly marked (e.g., 'Rev 2', 'Version 1.0', 'Rev: AA')\n"
                "  * EXTRACT WHEN: The value appears in the document header with a clear label\n"
                "  * DO NOT EXTRACT: If the revision appears without a clear label\n"
                "  * SET TO NULL: If no clearly labeled revision field exists\n\n"

                "- date_code: Manufacturing or document date\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Date:', 'Date Code', 'Document Date', 'Issued Date', or 'Issue Date' label\n"
                "  * EXTRACT WHEN: The value is in a recognizable date format (e.g., '19 SEP 24', '2024-11-03', '11/20/07')\n"
                "  * EXTRACT WHEN: The date appears in the document header with a clear label\n"
                "  * DO NOT EXTRACT: If the date appears without a clear label\n"
                "  * SET TO NULL: If no clearly labeled date field exists\n\n"

                "- lot_cavity_number: Lot number or mold cavity number for traceability\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Lot Number', 'Cavity Number', 'Mold Cavity', or 'MARKING' section with clear labels\n"
                "  * EXTRACT WHEN: The value is clearly marked and distinct\n"
                "  * DO NOT EXTRACT: If the number appears without a clear label\n"
                "  * SET TO NULL: If no clearly labeled lot/cavity field exists\n\n"

                "- net_weight: [MUST] Weight specification (净重) - Total weight of the connector\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Weight', 'Net Weight', 'Weight per pin', '净重', or 'Mass' label\n"
                "  * EXTRACT WHEN: The value includes units (e.g., 'grams', 'g', 'kg', 'lbs', 'mg')\n"
                "  * EXTRACT WHEN: The value is clearly marked in specifications or specification table\n"
                "  * EXTRACT WHEN: The value is a single number with unit (e.g., '45.5g', '0.0455 kg')\n"
                "  * EXAMPLE: '45.5g', '0.0455 kg', '1.6 oz', '45500 mg'\n"
                "  * DO NOT EXTRACT: If the weight appears without units\n"
                "  * DO NOT EXTRACT: If you need to calculate or infer the weight from other values\n"
                "  * DO NOT EXTRACT: If it's a weight range without a specific value\n"
                "  * SET TO NULL: If no clearly labeled weight field exists\n\n"

                "CRITICAL REQUIREMENTS:\n"
                "- Extract ONLY when the field has a CLEAR LABEL in the document\n"
                "- Extract ONLY exact values and units as they appear in the document\n"
                "- DO NOT infer, calculate, derive, or assume any values\n"
                "- DO NOT combine information from multiple sources\n"
                "- Identity data is typically found in the document header/title page\n"
                "- For EVERY field extracted with a non-null value, include it in extraction_basis\n"
                "- Do NOT include extraction_basis entries for null values\n"
                "- Preserve original formatting\n"
                "- For extraction_basis, specify the exact location and label in the document\n"
                "- For coordinates: provide the bounding box of the value in the document\n"
                "- Record the page number where the information was found\n\n"

                "IMPORTANT: Return ONLY valid JSON with this exact structure:\n"
                "{\n"
                "  \"part_number\": \"value or null\",\n"
                "  \"part_description\": \"value or null\",\n"
                "  \"series_family\": \"value or null\",\n"
                "  \"revision\": \"value or null\",\n"
                "  \"date_code\": \"value or null\",\n"
                "  \"lot_cavity_number\": \"value or null\",\n"
                "  \"net_weight\": \"value or null\",\n"
                "  \"extraction_basis\": [\n"
                "    {\"field_name\": \"part_number\", \"value\": \"09R31699A\", \"basis\": \"Document header, Part No. field\", \"context\": \"Part No. 09R31699A AA\", \"reasoning\": \"Explicitly labeled as 'Part No.' in the document header\", \"page_number\": \"1\", \"coordinates\": {\"x\": 1200, \"y\": 50, \"width\": 100, \"height\": 20}}\n"
                "  ]\n"
                "}\n\n"
                "NOTE: extraction_basis should ONLY contain entries for fields with non-null values!"
            ),
            description="Identity/基础标识 - Basic identification information"
        ),
        SectionConfig(
            section_name="mechanical",
            title_patterns=["Mechanical", "机械参数", "Pin Count", "Pin Pitch", "Dimensions"],
            schema=ConnectorMechanical,
            system_prompt=(
                "You are a data extraction expert specializing in connector specification documents. "
                "Extract ONLY Mechanical/机械参数 (Mechanical Parameters) information from the document.\n\n"



                "EXTRACTION PRIORITY:\n"
                "⭐ PRIORITY 1 (HIGHEST): Extract from ENGINEERING DRAWINGS and DIMENSIONAL DIAGRAMS\n"
                "   - Look for dimensional drawings with annotations (Figure 1, Figure 2, etc.)\n"
                "   - Look for connector layout diagrams with measurements\n"
                "   - Look for technical drawings showing pin spacing and overall size\n"
                "   - This is the most reliable source for mechanical parameters\n"
                "⭐ PRIORITY 2: Extract from TEXT content if drawings are not available\n"
                "   - Look for specification tables with dimension columns\n"
                "   - Look for text-based mechanical specifications\n"
                "⭐ FINAL RULE: If you find the same field in both drawings and text, ALWAYS prefer the DRAWING version\n\n"

                "MECHANICAL/机械参数 FIELDS AND EXTRACTION GUIDANCE:\n"
                "- pin_count: [MUST] Total number of pins/ways (针数) - The total number of pin positions in the connector\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Pin Count', 'Number of Pins', 'Way', 'Pin Capacity', '针数', or 'Positions' label\n"
                "  * EXTRACT WHEN: The value is clearly stated as a single number (e.g., 'Pin Count: 140', 'Positions: 190')\n"
                "  * EXTRACT WHEN: The value is in a specification table or clearly marked section\n"
                "  * EXAMPLE: '140', '190', '50', '100'\n"
                "  * DO NOT EXTRACT: If inferred from product title or other non-explicit sources\n"
                "  * DO NOT EXTRACT: If it's a range (e.g., '100-200 pins')\n"
                "  * DO NOT EXTRACT: If it's calculated from pin rows and columns\n"
                "  * SET TO NULL: If no clearly labeled pin count field exists\n\n"

                "- pin_rows: Number of rows in pin arrangement\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Row', 'Rows', or 'Pin Rows' label\n"
                "  * EXTRACT WHEN: The value is clearly stated as a number (e.g., 'Pin Rows: 2')\n"
                "  * DO NOT EXTRACT: If counted from pin assignment tables without explicit label\n"
                "  * SET TO NULL: If no clearly labeled pin rows field exists\n\n"

                "- pin_pitch: Distance between pin centers (may vary by pin type)\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Pin Pitch', 'Pitch', 'Center-to-center distance', or 'Spacing' label\n"
                "  * EXTRACT WHEN: The value is clearly stated with units (e.g., 'Pin Pitch: 0.6mm')\n"
                "  * EXTRACT WHEN: The value is visible in engineering drawings with clear dimension labels\n"
                "  * DO NOT EXTRACT: If calculated or inferred from diagrams without explicit label\n"
                "  * SET TO NULL: If no clearly labeled pin pitch field exists\n\n"

                "- pin_size: [MUST] Physical dimensions of pins (针脚尺寸) - Width, thickness, shape, and ALL pin types in the connector\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Pin Size', 'Pin Dimensions', 'Pin Width', 'Pin Thickness', or '针脚尺寸' label\n"
                "  * EXTRACT WHEN: The value includes specific dimensions with units AND shape (e.g., '0.64mm Square Pin', '1.5mm Rect. Pin')\n"
                "  * EXTRACT WHEN: Multiple pin types exist, list ALL of them (e.g., '0.64mm Square Pin / 1.5mm Rect. Pin')\n"
                "  * EXTRACT WHEN: The value is clearly marked in specifications table or technical drawings\n"
                "  * EXTRACT WHEN: The value describes the pin cross-section, profile, and shape\n"
                "  * IMPORTANT: Include ALL pin types and their dimensions if the connector has multiple pin sizes\n"
                "  * IMPORTANT: Include the shape information (Square, Rectangular, Round, etc.)\n"
                "  * EXAMPLE: '0.64mm Square Pin / 1.5mm Rect. Pin', '0.64mm × 0.15mm Square', 'Width 0.64mm, Thickness 0.15mm, Square pin'\n"
                "  * EXAMPLE: '0.5mm Round Pin / 1.0mm Square Pin / 1.5mm Rectangular Pin'\n"
                "  * DO NOT EXTRACT: If inferred from other information or diagrams without explicit label\n"
                "  * DO NOT EXTRACT: If it's just a pin type name without dimensions\n"
                "  * DO NOT EXTRACT: If only partial pin types are listed (must include ALL pin types in connector)\n"
                "  * SET TO NULL: If no clearly labeled pin size field exists\n\n"

                "- pin_type_orientation: [MUST] Pin gender and orientation (针型/出针方向) - Straight or right-angle, male or female\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Male', 'Female', 'Right-angle', 'Straight', '直脚', '弯脚', or 'Pin Type' label\n"
                "  * EXTRACT WHEN: The value is clearly stated in the document (e.g., 'Straight Male', 'Right-angle Female')\n"
                "  * EXTRACT WHEN: The value is visible in connector diagrams with clear labels\n"
                "  * EXTRACT WHEN: The value is in a specification table or product description\n"
                "  * EXAMPLE: 'Straight Male', 'Right-angle Female', 'Straight', 'Right-angle', '直脚', '弯脚'\n"
                "  * DO NOT EXTRACT: If inferred from other information or diagrams without explicit label\n"
                "  * DO NOT EXTRACT: If it's just a generic connector type\n"
                "  * SET TO NULL: If no clearly labeled pin type/orientation field exists\n\n"

                "- true_position: Position tolerance specification\n"
                "  * EXTRACT WHEN: The document explicitly contains 'True Position' or 'Position Tolerance' label\n"
                "  * EXTRACT WHEN: The value is clearly stated with tolerance specification\n"
                "  * EXTRACT WHEN: The value appears in technical specifications or drawings\n"
                "  * DO NOT EXTRACT: If inferred or assumed\n"
                "  * SET TO NULL: If no clearly labeled true position field exists\n\n"

                "- mounting_type: How connector is mounted (THT, SMT, wave solder, reflow, etc.)\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Mounting', 'Soldering', 'Reflow', or 'Wave Solder' label\n"
                "  * EXTRACT WHEN: The value is clearly stated in specifications\n"
                "  * EXTRACT WHEN: The value is visible in assembly diagrams with clear labels\n"
                "  * DO NOT EXTRACT: If inferred from other information\n"
                "  * SET TO NULL: If no clearly labeled mounting type field exists\n\n"

                "- pcb_protrusion: Length of pins protruding below PCB\n"
                "  * EXTRACT WHEN: The document explicitly contains 'PCB Protrusion' or 'Pin Protrusion' label\n"
                "  * EXTRACT WHEN: The value is clearly stated with measurement and units\n"
                "  * EXTRACT WHEN: The value is visible in technical drawings with dimension labels\n"
                "  * DO NOT EXTRACT: If calculated or inferred\n"
                "  * SET TO NULL: If no clearly labeled PCB protrusion field exists\n\n"

                "- housing_dimensions: Overall connector housing size (Width × Height × Depth)\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Housing Dimensions', 'Mechanical Dimensions', or 'Overall Dimensions' label\n"
                "  * EXTRACT WHEN: The value is clearly stated in text with all three dimensions and units\n"
                "  * EXTRACT WHEN: The value is visible in engineering drawings with clear dimension labels\n"
                "  * DO NOT EXTRACT: If calculated or inferred from component dimensions\n"
                "  * SET TO NULL: If no clearly labeled housing dimensions field exists\n\n"

                "CRITICAL REQUIREMENTS:\n"
                "- Extract ONLY when the field has a CLEAR LABEL in the document or drawing\n"
                "- Extract ONLY exact values and units as they appear in the document\n"
                "- DO NOT infer, calculate, derive, or assume any values\n"
                "- DO NOT combine information from multiple sources\n"
                "- For EVERY field extracted with a non-null value, include it in extraction_basis\n"
                "- Do NOT include extraction_basis entries for null values\n"
                "- Preserve original formatting\n"
                "- For extraction_basis, specify the exact location and label in the document\n"
                "- For coordinates: provide the bounding box of the value in the document\n"
                "- Record the page number where the information was found\n\n"

                "IMPORTANT: Return ONLY valid JSON with this exact structure:\n"
                "{\n"
                "  \"pin_count\": \"value or null\",\n"
                "  \"pin_rows\": \"value or null\",\n"
                "  \"pin_pitch\": \"value or null\",\n"
                "  \"pin_size\": \"value or null\",\n"
                "  \"pin_type_orientation\": \"value or null\",\n"
                "  \"true_position\": \"value or null\",\n"
                "  \"mounting_type\": \"value or null\",\n"
                "  \"pcb_protrusion\": \"value or null\",\n"
                "  \"housing_dimensions\": \"value or null\",\n"
                "  \"extraction_basis\": [\n"
                "    {\"field_name\": \"pin_count\", \"value\": \"190\", \"basis\": \"Specification table, Pin Count field\", \"context\": \"Pin Count: 190\", \"reasoning\": \"Explicitly labeled as 'Pin Count' in the specification table\", \"page_number\": \"1\", \"coordinates\": {\"x\": 200, \"y\": 150, \"width\": 50, \"height\": 20}}\n"
                "  ]\n"
                "}\n\n"
                "NOTE: extraction_basis should ONLY contain entries for fields with non-null values!"
            ),
            description="Mechanical/机械参数 - Mechanical parameters"
        ),
        SectionConfig(
            section_name="electrical",
            title_patterns=["Electrical", "电气参数", "Voltage", "Current", "Resistance"],
            schema=ConnectorElectrical,
            system_prompt=(
                "You are a data extraction expert specializing in connector specification documents. "
                "Extract ONLY Electrical/电气参数 (Electrical Parameters) information from the document.\n\n"



                "EXTRACTION PRIORITY:\n"
                "⭐ PRIORITY 1 (HIGHEST): Extract from TEXT content in the document\n"
                "   - Look for text-based information in specification tables, technical data sections\n"
                "   - This is the most reliable source for electrical parameters\n"
                "⭐ PRIORITY 2: Extract from ENGINEERING DRAWINGS/DIAGRAMS if text is not available\n"
                "   - Only use visual information if the same field cannot be found in text\n"
                "⭐ FINAL RULE: If you find the same field in both text and drawings, ALWAYS prefer the TEXT version\n\n"

                "ELECTRICAL/电气参数 FIELDS AND EXTRACTION GUIDANCE:\n"
                "- max_voltage: Maximum voltage rating\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Maximum Voltage', 'Max Voltage', or 'Voltage' label\n"
                "  * EXTRACT WHEN: The value is clearly stated in specifications table with units (e.g., 'Max Voltage: 20.0V')\n"
                "  * DO NOT EXTRACT: If inferred or calculated from other values\n"
                "  * SET TO NULL: If no clearly labeled maximum voltage field exists\n\n"

                "- current_per_pin: Maximum current per pin\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Current Per Pin', 'Max Current', or 'Amps' label\n"
                "  * EXTRACT WHEN: The value is clearly stated in specifications table with units\n"
                "  * DO NOT EXTRACT: If inferred or calculated from other values\n"
                "  * SET TO NULL: If no clearly labeled current per pin field exists\n\n"

                "- contact_resistance: Maximum contact resistance\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Contact Resistance' or 'Max Resistance' label\n"
                "  * EXTRACT WHEN: The value is clearly stated in specifications table with units (e.g., 'mΩ', 'Ω')\n"
                "  * DO NOT EXTRACT: If inferred or calculated from other values\n"
                "  * SET TO NULL: If no clearly labeled contact resistance field exists\n\n"

                "- dielectric_withstand: Dielectric withstand voltage\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Dielectric Withstand' or 'Dielectric Voltage' label\n"
                "  * EXTRACT WHEN: The value is clearly stated in specifications table with units and test conditions\n"
                "  * DO NOT EXTRACT: If inferred or calculated from other values\n"
                "  * SET TO NULL: If no clearly labeled dielectric withstand field exists\n\n"

                "CRITICAL REQUIREMENTS:\n"
                "- Extract ONLY when the field has a CLEAR LABEL in the document\n"
                "- Extract ONLY exact values and units as they appear in the document\n"
                "- DO NOT infer, calculate, derive, or assume any values\n"
                "- DO NOT combine information from multiple sources\n"
                "- Electrical data is typically found in tables (TABLE 1, TABLE 2, etc.)\n"
                "- For EVERY field extracted with a non-null value, include it in extraction_basis\n"
                "- Do NOT include extraction_basis entries for null values\n"
                "- Preserve original formatting (e.g., '26V', '≤ 20 mΩ', 'Volts', 'Amps')\n"
                "- For extraction_basis, specify the exact location and label in the document\n"
                "- For coordinates: provide the bounding box of the value in the table\n"
                "- Record the page number where the information was found\n\n"

                "IMPORTANT: Return ONLY valid JSON with this exact structure:\n"
                "{\n"
                "  \"max_voltage\": \"value or null\",\n"
                "  \"current_per_pin\": \"value or null\",\n"
                "  \"contact_resistance\": \"value or null\",\n"
                "  \"dielectric_withstand\": \"value or null\",\n"
                "  \"extraction_basis\": [\n"
                "    {\"field_name\": \"max_voltage\", \"value\": \"20.0 Volts\", \"basis\": \"TABLE 1, Maximum Voltage column\", \"context\": \"Maximum Voltage: 20.0 V\", \"reasoning\": \"Explicitly labeled as 'Maximum Voltage' in the electrical specifications table\", \"page_number\": \"3\", \"coordinates\": {\"x\": 300, \"y\": 200, \"width\": 80, \"height\": 20}}\n"
                "  ]\n"
                "}\n\n"
                "NOTE: extraction_basis should ONLY contain entries for fields with non-null values!"
            ),
            description="Electrical/电气参数 - Electrical parameters"
        ),
        SectionConfig(
            section_name="environmental",
            title_patterns=["Environmental", "Reliability", "环境与可靠性", "Temperature", "Durability"],
            schema=ConnectorEnvironmental,
            system_prompt=(
                "You are a data extraction expert specializing in connector specification documents. "
                "Extract ONLY Environmental/Reliability/环境与可靠性 information from the document.\n\n"



                "EXTRACTION PRIORITY:\n"
                "⭐ PRIORITY 1 (HIGHEST): Extract from TEXT content in the document\n"
                "   - Look for text-based information in specification tables, technical data sections\n"
                "   - This is the most reliable source for environmental and reliability parameters\n"
                "⭐ PRIORITY 2: Extract from ENGINEERING DRAWINGS/DIAGRAMS if text is not available\n"
                "   - Only use visual information if the same field cannot be found in text\n"
                "⭐ FINAL RULE: If you find the same field in both text and drawings, ALWAYS prefer the TEXT version\n\n"

                "ENVIRONMENTAL/RELIABILITY/环境与可靠性 FIELDS AND EXTRACTION GUIDANCE:\n"
                "- operating_temp: Operating temperature range\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Operating Temperature' or 'Temperature Range' label\n"
                "  * EXTRACT WHEN: The value is clearly stated in specifications (e.g., '-40 to 85°C')\n"
                "  * EXTRACT WHEN: The value appears in a specification table with clear label\n"
                "  * DO NOT EXTRACT: If inferred or calculated from other values\n"
                "  * SET TO NULL: If no clearly labeled operating temperature field exists\n\n"

                "- solder_temp: Maximum solder temperature\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Solder Temperature' or 'Reflow Temperature' label\n"
                "  * EXTRACT WHEN: The value is clearly stated in specifications (e.g., '260°C')\n"
                "  * EXTRACT WHEN: The value appears in a specification table with clear label\n"
                "  * DO NOT EXTRACT: If inferred or calculated from other values\n"
                "  * SET TO NULL: If no clearly labeled solder temperature field exists\n\n"

                "- durability: Insertion/mating durability cycles\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Insertion Durability', 'Mating Cycles', or 'Durability' label\n"
                "  * EXTRACT WHEN: The value is clearly stated with cycle count (e.g., '50 cycles')\n"
                "  * EXTRACT WHEN: The value appears in a specification table with clear label\n"
                "  * DO NOT EXTRACT: If inferred or calculated from other values\n"
                "  * SET TO NULL: If no clearly labeled durability field exists\n\n"

                "- seal_requirement: Seal integrity performance specification (NOT design description)\n"
                "  * IMPORTANT: Extract the PERFORMANCE LEVEL/TEST RESULT, NOT the design or material description\n"
                "  * EXTRACT WHEN: The document explicitly contains 'Seal Integrity', 'Immersion Test', or test result labels\n"
                "  * EXTRACT WHEN: Test result statements like 'Pass immersion test', 'Passes immersion test' are clearly stated\n"
                "  * EXTRACT WHEN: Quantitative specs like '≤ 1.0 [cc/min] @ 5 psi', '< 0.5 cc/min', 'No leakage' are clearly labeled\n"
                "  * DO NOT EXTRACT: Design descriptions like 'The connector shall have...', 'The seal is made of...'\n"
                "  * SET TO NULL: If no clearly labeled seal requirement field exists\n\n"

                "CRITICAL REQUIREMENTS:\n"
                "- Extract ONLY when the field has a CLEAR LABEL in the document\n"
                "- Extract ONLY exact values and units as they appear in the document\n"
                "- DO NOT infer, calculate, derive, or assume any values\n"
                "- DO NOT combine information from multiple sources\n"
                "- Environmental data is typically found in tables (TABLE 1, TABLE 2, etc.)\n"
                "- For EVERY field extracted with a non-null value, include it in extraction_basis\n"
                "- Do NOT include extraction_basis entries for null values\n"
                "- Preserve original formatting\n"
                "- For extraction_basis, specify the exact location and label in the document\n"
                "- For coordinates: provide the bounding box of the value in the table\n"
                "- Record the page number where the information was found\n\n"

                "IMPORTANT: Return ONLY valid JSON with this exact structure:\n"
                "{\n"
                "  \"operating_temp\": \"value or null\",\n"
                "  \"solder_temp\": \"value or null\",\n"
                "  \"durability\": \"value or null\",\n"
                "  \"seal_requirement\": \"value or null\",\n"
                "  \"extraction_basis\": [\n"
                "    {\"field_name\": \"operating_temp\", \"value\": \"-40 to 125 °C\", \"basis\": \"TABLE 1, Operating Temperature row\", \"context\": \"Operating Temperature: -40 to 125 °C\", \"reasoning\": \"Explicitly labeled as 'Operating Temperature' in the specifications table\", \"page_number\": \"3\", \"coordinates\": {\"x\": 250, \"y\": 180, \"width\": 120, \"height\": 20}}\n"
                "  ]\n"
                "}\n\n"
                "NOTE: extraction_basis should ONLY contain entries for fields with non-null values!"
            ),
            description="Environmental/Reliability/环境与可靠性 - Environmental and reliability parameters"
        ),
        SectionConfig(
            section_name="material",
            title_patterns=["Material", "材料", "Resin", "Plating", "Housing"],
            schema=ConnectorMaterial,
            system_prompt=(
                "You are a data extraction expert specializing in connector specification documents. "
                "Extract ONLY Material/材料 (Material Information) from the document.\n\n"



                "EXTRACTION PRIORITY:\n"
                "⭐ PRIORITY 1 (HIGHEST): Extract from TEXT content in the document\n"
                "   - Look for text-based information in Material section, specification tables\n"
                "   - This is the most reliable source for material information\n"
                "⭐ PRIORITY 2: Extract from ENGINEERING DRAWINGS/DIAGRAMS if text is not available\n"
                "   - Only use visual information if the same field cannot be found in text\n"
                "⭐ FINAL RULE: If you find the same field in both text and drawings, ALWAYS prefer the TEXT version\n\n"

                "MATERIAL/材料 FIELDS AND EXTRACTION GUIDANCE:\n"
                "IMPORTANT: Focus on the 'Material' section (with 'Material' as a major heading) and its subsections.\n"
                "All material fields should be extracted from this dedicated Material section when possible.\n\n"

                "- housing_resin: [MUST] Housing/insulator resin material specification (胶壳材料) - The plastic material of the connector body\n"
                "  * EXTRACT WHEN: The document has a 'Material' section with 'Insulator' or 'Housing' subsection\n"
                "  * EXTRACT WHEN: The value is explicitly labeled (e.g., 'Insulator: LCP', 'Housing: Amodell AS 4133-HS', 'Insulator: GE Valox 508R (PBT)')\n"
                "  * EXTRACT WHEN: The value includes material name and optionally glass fill percentage (e.g., 'PBT 30% Glass Filled')\n"
                "  * EXTRACT WHEN: The value is clearly marked in the Material section\n"
                "  * EXAMPLE: 'LCP', 'Amodell AS 4133-HS', 'GE Valox 508R (PBT)', 'PBT 30% Glass Filled', 'Nylon 6.6'\n"
                "  * DO NOT EXTRACT: If inferred from other information or product name\n"
                "  * DO NOT EXTRACT: If it's a design description rather than material specification\n"
                "  * SET TO NULL: If no clearly labeled housing/insulator material field exists\n\n"

                "- resin: [MUST] Insulator/Housing resin material (绝缘壳体的材料) - The plastic material of the connector insulator/housing body\n"
                "  * EXTRACT WHEN: The document has a 'Material' section with 'Insulator' or 'Housing' subsection\n"
                "  * EXTRACT WHEN: The value is explicitly labeled (e.g., 'Insulator: GE Valox 508R', 'Housing: LCP', 'Insulator: PBT 30% Glass Filled')\n"
                "  * EXTRACT WHEN: The value includes material name and optionally glass fill percentage or material grade\n"
                "  * EXTRACT WHEN: The value is clearly marked in the Material section under Insulator/Housing\n"
                "  * IMPORTANT: This is the SAME as housing_resin - both refer to the insulator material\n"
                "  * IMPORTANT: Do NOT extract seal material (like Wacker N198 silicone) for this field\n"
                "  * EXAMPLE: 'GE Valox 508R', 'LCP', 'PBT 30% Glass Filled', 'Amodell AS 4133-HS', 'Nylon 6.6'\n"
                "  * DO NOT EXTRACT: Seal or sealing material (e.g., 'Wacker N198 silicone', 'Epoxy sealant')\n"
                "  * DO NOT EXTRACT: If inferred from other information or product name\n"
                "  * DO NOT EXTRACT: If it's a design description rather than material specification\n"
                "  * SET TO NULL: If no clearly labeled insulator/housing material field exists\n\n"

                "- resin_regrind_allowance: [MUST] Percentage of regrind material allowed (回料比例) - Maximum percentage of recycled material\n"
                "  * EXTRACT WHEN: The document has 'Regrind', 'Regrind Allowance', 'Regrind %', or '回料比例' label in Material section\n"
                "  * EXTRACT WHEN: The value is explicitly stated with percentage (e.g., '25% regrind', 'Regrind Allowance: 25%', '≤ 15%')\n"
                "  * EXTRACT WHEN: The value is clearly marked in the Material section\n"
                "  * EXAMPLE: '25%', '≤ 15%', '0%', '10% maximum'\n"
                "  * DO NOT EXTRACT: If inferred or assumed\n"
                "  * DO NOT EXTRACT: If it's a range without a specific limit\n"
                "  * SET TO NULL: If no clearly labeled regrind allowance field exists\n\n"

                "- pin_base_material: Base material of pins before plating (针脚基材) - The metal material of pins before any plating\n"
                "  * EXTRACT WHEN: The document has a 'Material' section with 'Pins' or 'Pin Material' subsection\n"
                "  * EXTRACT WHEN: The value is explicitly labeled (e.g., 'Material: Copper Alloy', 'Pin Material: Brass', 'Base: Phosphor Bronze')\n"
                "  * EXTRACT WHEN: Multiple pin types exist, list ALL of them with their materials (e.g., '0.64mm Square Pin: CuMg 0.1, 1.5mm Rect. Pin: 425 Brass')\n"
                "  * EXTRACT WHEN: The value is clearly marked in the Material section\n"
                "  * IMPORTANT: If connector has multiple pin types, include ALL pin types and their corresponding base materials\n"
                "  * EXAMPLE: 'Copper Alloy', 'Brass', 'Phosphor Bronze', 'Beryllium Copper'\n"
                "  * EXAMPLE: '0.64mm Square Pin: CuMg 0.1, 1.5mm Rect. Pin: 425 Brass ½ Hard'\n"
                "  * EXAMPLE: '0.5mm Round Pin: Copper, 1.0mm Square Pin: Brass, 1.5mm Rect. Pin: Phosphor Bronze'\n"
                "  * DO NOT EXTRACT: If inferred from other information\n"
                "  * DO NOT EXTRACT: If it's the plating material instead of base material\n"
                "  * DO NOT EXTRACT: If only partial pin types are listed (must include ALL pin types)\n"
                "  * SET TO NULL: If no clearly labeled pin base material field exists\n\n"

                "- plating_material: [MUST] Plating specification (镀层) - Surface plating material, thickness, and layers for ALL pin types\n"
                "  * EXTRACT WHEN: The document has a 'Material' section with 'Pins' or 'Plating' subsection\n"
                "  * EXTRACT WHEN: The value is explicitly labeled with plating details (e.g., 'Nickel underplate, Gold plating', 'Gold 0.5µm over Nickel 2.5µm')\n"
                "  * EXTRACT WHEN: The value includes plating type, thickness, and layers (e.g., 'Gold', 'Tin', 'Silver', 'Nickel')\n"
                "  * EXTRACT WHEN: Multiple pin types exist, list plating for ALL pin types (e.g., 'Mating Area: Gold (0.76µm) over Nickel (2.0-3.5µm) (0.64mm Pin), Mating Area: Gold (0.76µm) over Nickel (2.0-3.5µm) (1.5mm Pin)')\n"
                "  * EXTRACT WHEN: The value is clearly marked in the Material section\n"
                "  * IMPORTANT: Include plating specifications for ALL pin types if connector has multiple pin sizes\n"
                "  * IMPORTANT: Include both mating area and solder area plating if specified\n"
                "  * IMPORTANT: Include thickness information (e.g., µm, thickness ranges)\n"
                "  * EXAMPLE: 'Gold', 'Tin', 'Silver', 'Nickel'\n"
                "  * EXAMPLE: 'Gold 0.5µm over Nickel 2.5µm', 'Nickel underplate, Gold plating'\n"
                "  * EXAMPLE: 'Mating Area: Hard Gold (>0.76µm) over Nickel (2.0-3.5µm); Solder Area: Matte Tin (2.5-4µm) over Nickel (2.0-3.5µm) (0.64mm Pin), Mating Area: Hard Gold (>0.76µm) over Nickel (2.0-3.5µm); Solder Area: Matte Tin (2.5-4µm) over Nickel (1.25-2.5µm) (1.5mm Pin)'\n"
                "  * DO NOT EXTRACT: If inferred or assumed\n"
                "  * DO NOT EXTRACT: If it's the base material instead of plating\n"
                "  * DO NOT EXTRACT: If only partial pin types are listed (must include ALL pin types)\n"
                "  * SET TO NULL: If no clearly labeled plating material field exists\n\n"

                "CRITICAL REQUIREMENTS:\n"
                "- Extract ONLY when the field has a CLEAR LABEL in the document\n"
                "- Extract ONLY exact values as they appear in the document\n"
                "- DO NOT infer, calculate, derive, or assume any values\n"
                "- DO NOT combine information from multiple sources\n"
                "- Material data is typically found in 'Material' section with subsections for Insulator, Pins, Seal, etc.\n"
                "- IMPORTANT: All fields should come from the same 'Material' section when possible\n"
                "- For EVERY field extracted with a non-null value, include it in extraction_basis\n"
                "- Do NOT include extraction_basis entries for null values\n"
                "- Preserve original formatting, units, and special characters (µm, %, etc.)\n"
                "- For extraction_basis, specify the exact location and label in the document\n"
                "- For coordinates: provide the bounding box of the value in the document\n"
                "- Record the page number where the information was found\n\n"

                "IMPORTANT: Return ONLY valid JSON with this exact structure:\n"
                "{\n"
                "  \"housing_resin\": \"value or null\",\n"
                "  \"resin\": \"value or null\",\n"
                "  \"resin_regrind_allowance\": \"value or null\",\n"
                "  \"pin_base_material\": \"value or null\",\n"
                "  \"plating_material\": \"value or null\",\n"
                "  \"extraction_basis\": [\n"
                "    {\"field_name\": \"housing_resin\", \"value\": \"Amodell AS 4133-HS; 33% Glass Filled\", \"basis\": \"Material section, Insulator subsection\", \"context\": \"MATERIAL - Insulator: Amodell AS 4133-HS; 33% Glass Filled, Color: Natural\", \"reasoning\": \"Explicitly labeled as 'Insulator' in the Material section\", \"page_number\": \"4\", \"coordinates\": {\"x\": 150, \"y\": 250, \"width\": 250, \"height\": 20}}\n"
                "  ]\n"
                "}\n\n"
                "NOTE: extraction_basis should ONLY contain entries for fields with non-null values!"
            ),
            description="Material/材料 - Material information"
        )
    ]

    return ExtractionConfig(sections)


# ============================================================================
# Section Configurations for E-FER specification documents
# ============================================================================

def create_eferspec_extraction_config() -> ExtractionConfig:
    """
    Create extraction configuration for E-FER specification documents.

    E-FER documents contain:
    - Document header (product info) - typically on first page
    - Product components - typically on first few pages
    - Characteristics and properties - throughout document
    - Indications
    - Test planning
    - Scheme of authorizations

    Page Range Optimization:
    - document_header: Only extract from first page (first_page_only=True)
      Reason: Document header with product name, NART, version, status is on the first page
    - product_components: Extract from first 3 pages (page_range=(1, 3))
      Reason: Product components table is typically in the first few pages
    - characteristics_and_properties: Extract from all pages (no page range restriction)
      Reason: Characteristics and properties can span multiple pages

    Returns:
        ExtractionConfig with all E-FER sections
    """
    sections = [
        SectionConfig(
            section_name="document_header",
            title_patterns=["Internal specification"],
            schema=DocumentInfo,
            page_range_config=PageRangeConfig(
                first_page_only=True,
                description="Document header information is typically on the first page only"
            ),
            system_prompt=(
                "You are a data extraction expert. Extract document header information "
                "including product name (e.g., 'TESA 62565 PV57'), NART number, CO, PV, "
                "version, status (e.g., 'Released'), date, and product identification. "
                "Return data in the exact format specified."
            ),
            description="Document header information"
        ),
        SectionConfig(
            section_name="product_components",
            title_patterns=["Product components", "Components"],
            schema=ProductComponentsList,
            page_range_config=PageRangeConfig(
                page_range=(1, 3),  
                description="Product components table is typically in the first three pages"
            ),
            system_prompt=(
                "You are a data extraction expert. Extract ALL product components from the table with proper grouping.\n\n"
                "STRUCTURE UNDERSTANDING:\n"
                "1. Components separated by 'OR' are ALTERNATIVES in the same group (use is_alternative_group=true)\n"
                "2. Lines like '---68537-80000-40---' indicate a NART variant/subclass\n"
                "3. Components after a NART variant line belong to that variant (mark with nart_variant field)\n"
                "4. Components before any variant line belong to the primary NART\n\n"
                "TABLE STRUCTURE: NART | Co | Pr | PV | Product identification | value | unit\n\n"
                "EXTRACTION RULES:\n"
                "- Extract EVERY row in the table\n"
                "- Group components that are separated by 'OR' into the same ProductComponentGroup\n"
                "- Set is_alternative_group=true for groups with OR-separated components\n"
                "- For components after a NART variant line (e.g., '---68537-80000-40---'), set nart_variant to that NART\n"
                "- For components before any variant line, leave nart_variant as null\n"
                "- primary_nart should be the main NART from the document header\n\n"
                "EXAMPLE STRUCTURE:\n"
                "Group 1 (alternatives):\n"
                "  - Component: 22857-90000-00 (TRENNP. 152 WHITE...)\n"
                "  - Component: 23039-90000-08 (TRENNP.205 WHITE RED...)\n"
                "  is_alternative_group: true\n\n"
                "Group 2 (after variant ---68537-80000-40---):\n"
                "  - Component: 13734-70000-80 (nart_variant: '68537-80000-40')\n"
                "  - Component: 10164-70000-00 (nart_variant: '68537-80000-40')\n"
                "  is_alternative_group: true\n\n"
                "Return data in the exact format specified."
            ),
            description="Product components section with grouping and NART variants"
        ),
        SectionConfig(
            section_name="characteristics_and_properties",
            title_patterns=["Characteristics and properties"],
            schema=CharacteristicsAndProperties,
            page_range_config=PageRangeConfig(
                page_range=(3, None),
                description="Characteristics and properties table starts from page 3 onwards"
            ),
            system_prompt=(
                "You are a data extraction expert specializing in technical specifications. "
                "Extract ALL characteristics and properties from the table.\n\n"

                "TABLE STRUCTURE:\n"
                "The table typically contains columns: No | Item | Item-No. (P-number) | Unit | Target Value | Test Method | Test Type\n\n"

                "EXTRACTION RULES:\n"
                "1. Extract ONLY valid data rows from the table\n"
                "2. SKIP non-data rows such as:\n"
                "   - Table headers (rows with column names like 'No', 'Item', 'Unit', etc.)\n"
                "   - Separator lines (rows with dashes or empty cells)\n"
                "   - Condition/note rows (rows that describe conditions, like 'Range of temperature', 'Range of humidity')\n"
                "   - Rows where ALL fields are null/empty\n"
                "   - Rows where ONLY 'item' and 'unit' have values but 'no' and 'item_no' are null (these are typically notes/conditions)\n"
                "3. For each valid property row, extract all fields exactly as they appear\n"
                "4. If a field is not present or is empty, use null\n\n"

                "TARGET VALUE EXTRACTION (CRITICAL):\n"
                "The 'target_value_with_unit' field should contain the target value with tolerance/range.\n"
                "The 'target_value_with_unit_extra_info' field should contain ONLY explanatory notes/references (NOT test methods).\n"
                "IMPORTANT RULES:\n"
                "1. Remove any surrounding parentheses from the value\n"
                "2. Replace commas with dots for decimal points (European format → Standard format)\n"
                "   Example: '6,00 ± 2,50' → '6.00 ± 2.50'\n"
                "   Example: '4,60 ± 2,50' → '4.60 ± 2.50'\n"
                "3. Separate the main target value from extra information:\n"
                "   - Main value goes to 'target_value_with_unit' (e.g., 'i.O. / OK', '=< 50')\n"
                "   - Extra info goes to 'target_value_with_unit_extra_info' (e.g., 's. Sonstige', 'Hinweise / see indications')\n"
                "   - Test methods stay in 'test_method' field (e.g., '3RD_PARTY_LAB', 'J0PMA002')\n"
                "Examples:\n"
                "- If PDF shows: '( 37 ± 4 )' → target_value_with_unit: '37 ± 4', extra_info: null\n"
                "- If PDF shows: '( <= 10 )' → target_value_with_unit: '<= 10', extra_info: null\n"
                "- If PDF shows: '( 1.0 - 1.9 )' → target_value_with_unit: '1.0 - 1.9', extra_info: null\n"
                "- If PDF shows: '( 6,00 ± 2,50 )' → target_value_with_unit: '6.00 ± 2.50', extra_info: null\n"
                "- If PDF shows: 'i.O. / OK' with 's. Sonstige' below → target_value_with_unit: 'i.O. / OK', extra_info: 's. Sonstige'\n"
                "- If PDF shows: '=< 50' with 's. Sonstige' and 'Hinweise / see indications' → target_value_with_unit: '=< 50', extra_info: 's. Sonstige Hinweise / see indications'\n"
                "- If PDF shows: '37 ± 4' → target_value_with_unit: '37 ± 4', extra_info: null\n\n"

                "MULTI-LINE FIELD HANDLING (CRITICAL):\n"
                "Some fields like 'Item' (item name) and 'Test Method' may span multiple lines in the PDF table.\n"
                "When you encounter multi-line content:\n"
                "- For 'item' field: Merge all lines with appropriate spacing/newlines to preserve meaning\n"
                "  Example: If the PDF shows:\n"
                "    Line 1: 'Total weight, without'\n"
                "    Line 2: 'liner'\n"
                "  Extract as: 'Total weight, without liner' (merge with space)\n"
                "- For 'test_method' field: Merge all lines with appropriate spacing/newlines\n"
                "  Example: If the PDF shows:\n"
                "    Line 1: 'J0PM'\n"
                "    Line 2: '0005'\n"
                "  Extract as: 'J0PM0005' (merge without space) or 'J0PM 0005' (with space) depending on context\n"
                "- Preserve the original meaning and readability of the merged content\n"
                "- Do not add extra spaces or characters that weren't in the original\n\n"

                "FIELD EXTRACTION DETAILS:\n"
                "- no: Item number (e.g., '01', '02', '03')\n"
                "- item: Item name/description (may be multi-line, merge appropriately)\n"
                "- item_no: P-number identifier (e.g., 'P4079', 'P4080')\n"
                "- unit: Unit of measurement (e.g., 'g/m²', 'μm', 'cN/cm', '%')\n"
                "- target_value_with_unit: Target value with tolerance/range, WITHOUT surrounding parentheses (e.g., '37 ± 4', '50 ±5', '<= 10', 'i.O. / OK', '=< 50')\n"
                "- target_value_with_unit_extra_info: Extra explanatory notes/references in target value column (NOT test methods) (e.g., 's. Sonstige', 'Hinweise / see indications')\n"
                "  This field captures additional notes or references that appear below/with the target value\n"
                "- test_method: Test method code (may be multi-line, merge appropriately) (e.g., 'J0PM0005', 'DIN 53370', '3RD_PARTY_LAB')\n"
                "- test_type: Test type indicator (e.g., 'I/SC-P', 'L', 'F')\n\n"

                "CRITICAL REQUIREMENTS:\n"
                "- Extract ONLY valid data rows (skip headers, separators, and condition notes)\n"
                "- A valid data row MUST have at least 'no' and 'item_no' fields with non-null values\n"
                "- Skip rows where 'no' is null (these are typically notes or conditions)\n"
                "- Skip rows where all fields are null\n"
                "- Skip rows that appear to be table headers or separators\n"
                "- Search all pages for all tables with characteristics and properties\n"
                "- Extract exact values as they appear in the document\n"
                "- For multi-line fields, merge them intelligently to preserve meaning\n"
                "- REMOVE surrounding parentheses from target_value_with_unit field\n\n"

                "IMPORTANT: Return ONLY valid JSON with this exact field name:\n"
                "{\n"
                "  \"properties\": [\n"
                "    {\n"
                "      \"no\": \"...\",\n"
                "      \"item\": \"...\",\n"
                "      \"item_no\": \"...\",\n"
                "      \"unit\": \"...\",\n"
                "      \"target_value_with_unit\": \"...\",\n"
                "      \"target_value_with_unit_extra_info\": \"...\",\n"
                "      \"test_method\": \"...\",\n"
                "      \"test_type\": \"...\"\n"
                "    },\n"
                "    ...\n"
                "  ]\n"
                "}"
            ),
            description="Characteristics and properties section"
        )
    ]

    return ExtractionConfig(sections)


def create_pda_extraction_config() -> ExtractionConfig:
    """
    Create extraction configuration for PDA documents.

    This is an alias for create_eferspec_extraction_config() for backward compatibility.
    Currently, PDA documents are E-FER specification documents.

    Returns:
        ExtractionConfig with all PDA sections
    """
    return create_eferspec_extraction_config()


class ExtractionConfigManager:
    """
    Manager for document type-specific extraction configurations.

    Provides a centralized way to get extraction configurations based on document type.
    Supports multiple document types with different extraction schemas.
    """

    # Mapping of document types to their configuration factory functions
    _config_factories: Dict[DocumentType, callable] = {
        DocumentType.EFERSPEC: create_eferspec_extraction_config,
        DocumentType.LINER: create_liner_extraction_config,
        DocumentType.BACKING: create_backing_extraction_config,
        DocumentType.ADHESIVE: create_adhesive_extraction_config,
        DocumentType.CONNECTOR_SPECS: create_connector_specs_extraction_config,
    }

    @classmethod
    def get_config_by_type(cls, doc_type: DocumentType) -> ExtractionConfig:
        """
        Get extraction configuration for a specific document type.

        Args:
            doc_type: The document type

        Returns:
            ExtractionConfig for the document type

        Raises:
            ValueError: If document type is not supported
        """
        if doc_type not in cls._config_factories:
            raise ValueError(f"Unsupported document type: {doc_type}")

        factory = cls._config_factories[doc_type]
        return factory()

    @classmethod
    def get_config_by_filename(cls, filename: str) -> ExtractionConfig:
        """
        Get extraction configuration by detecting document type from filename.

        Args:
            filename: The filename to analyze

        Returns:
            ExtractionConfig for the detected document type
        """
        doc_type = DocumentType.from_filename(filename)
        return cls.get_config_by_type(doc_type)

    @classmethod
    def register_config(cls, doc_type: DocumentType, factory: callable) -> None:
        """
        Register a new document type with its configuration factory.

        Args:
            doc_type: The document type to register
            factory: A callable that returns ExtractionConfig
        """
        cls._config_factories[doc_type] = factory

    @classmethod
    def list_supported_types(cls) -> list:
        """
        List all supported document types.

        Returns:
            List of supported DocumentType values
        """
        return list(cls._config_factories.keys())

