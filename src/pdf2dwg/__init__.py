"""
PDF to DWG Converter

A Python tool to convert PDF files to DWG/DXF format for AutoCAD.
Supports vector graphics, text, images, and various line types.

Key Features:
- Adaptive Bezier curve sampling for high-precision conversion
- Circle, arc, and ellipse detection from polylines
- True color support (24-bit RGB)
- Comprehensive text extraction with CJK support
- Image extraction with transparency handling
"""

__version__ = "1.2.0"
__author__ = ""

# Main converter
from .converter import (
    PDFToDWGConverter,
    OutputFormat,
    PageMode,
    ConversionResult,
    quick_convert,
)

# PDF extraction
from .pdf_extractor import (
    PDFVectorExtractor,
    ExtractedData,
    detect_circles_and_arcs,
    detect_ellipses,
    # Entity types
    Point,
    Line,
    Arc,
    Circle,
    Ellipse,
    Polyline,
    Spline,
    TextEntity,
    MText,
    Rectangle,
    Hatch,
    ImageEntity,
    # Enums
    LineType,
)

# DXF writing
from .dxf_writer import (
    DXFWriter,
    create_dxf_from_data,
    merge_pages_to_dxf,
)

# DWG conversion
from .dwg_converter import (
    DWGConverter,
    DWGVersion,
    convert_dxf_to_dwg,
)

__all__ = [
    # Version
    "__version__",
    # Main converter
    "PDFToDWGConverter",
    "OutputFormat",
    "PageMode",
    "ConversionResult",
    "quick_convert",
    # PDF extraction
    "PDFVectorExtractor",
    "ExtractedData",
    "detect_circles_and_arcs",
    "detect_ellipses",
    # Entity types
    "Point",
    "Line",
    "Arc",
    "Circle",
    "Ellipse",
    "Polyline",
    "Spline",
    "TextEntity",
    "MText",
    "Rectangle",
    "Hatch",
    "ImageEntity",
    "LineType",
    # DXF writing
    "DXFWriter",
    "create_dxf_from_data",
    "merge_pages_to_dxf",
    # DWG conversion
    "DWGConverter",
    "DWGVersion",
    "convert_dxf_to_dwg",
]
