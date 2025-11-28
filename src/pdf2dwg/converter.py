"""
PDF to DWG Converter

Main converter class that orchestrates the full conversion pipeline:
PDF -> Vector Extraction -> DXF -> DWG
"""

import os
import tempfile
from pathlib import Path
from typing import Optional, List, Tuple, Callable
from dataclasses import dataclass
from enum import Enum

from .pdf_extractor import PDFVectorExtractor, ExtractedData, detect_circles_and_arcs, detect_ellipses
from .dxf_writer import DXFWriter, create_dxf_from_data, merge_pages_to_dxf
from .dwg_converter import DWGConverter, DWGVersion, convert_dxf_to_dwg


class OutputFormat(Enum):
    """Output format options"""
    DXF = "dxf"
    DWG = "dwg"
    BOTH = "both"


class PageMode(Enum):
    """How to handle multiple pages"""
    SINGLE = "single"      # Convert only first page
    SEPARATE = "separate"  # Each page to separate file
    MERGE = "merge"        # Merge all pages into one file


@dataclass
class ConversionResult:
    """Result of a conversion operation"""
    success: bool
    output_files: List[str]
    message: str
    pages_processed: int = 0
    entities_count: int = 0


class PDFToDWGConverter:
    """
    Main converter class for PDF to DWG conversion.

    Usage:
        converter = PDFToDWGConverter()
        result = converter.convert("input.pdf", "output.dwg")

        # Or with options
        result = converter.convert(
            "input.pdf",
            "output.dwg",
            scale=2.0,
            output_format=OutputFormat.DWG,
            dwg_version=DWGVersion.ACAD2010,
            page_mode=PageMode.MERGE
        )
    """

    def __init__(self, oda_converter_path: Optional[str] = None):
        """
        Initialize converter.

        Args:
            oda_converter_path: Optional path to ODA File Converter.
                               If None, will try to find automatically.
        """
        self.dwg_converter = DWGConverter(oda_converter_path)
        self._progress_callback: Optional[Callable[[str, float], None]] = None

    def set_progress_callback(self, callback: Callable[[str, float], None]):
        """
        Set a callback for progress updates.

        Args:
            callback: Function(message: str, progress: float) where progress is 0-1
        """
        self._progress_callback = callback

    def _report_progress(self, message: str, progress: float):
        """Report progress if callback is set"""
        if self._progress_callback:
            self._progress_callback(message, progress)

    def can_convert_to_dwg(self) -> bool:
        """Check if DWG conversion is available (ODA converter installed)"""
        return self.dwg_converter.is_available()

    def get_dwg_install_instructions(self) -> str:
        """Get installation instructions for ODA File Converter"""
        return self.dwg_converter._get_install_instructions()

    def convert(
        self,
        input_path: str,
        output_path: str,
        scale: float = 1.0,
        output_format: OutputFormat = OutputFormat.DWG,
        dwg_version: DWGVersion = DWGVersion.ACAD2010,
        dxf_version: str = "R2010",
        page_mode: PageMode = PageMode.SINGLE,
        pages: Optional[List[int]] = None,
        detect_geometry: bool = True,
        detect_ellipse: bool = True,
        keep_dxf: bool = False,
        use_true_color: bool = True,
    ) -> ConversionResult:
        """
        Convert PDF to DWG/DXF.

        Args:
            input_path: Path to input PDF file
            output_path: Path for output file(s)
            scale: Scale factor for coordinates (default 1.0)
            output_format: Output format (DXF, DWG, or BOTH)
            dwg_version: Target DWG version (if converting to DWG)
            dxf_version: Target DXF version
            page_mode: How to handle multiple pages
            pages: Specific pages to convert (0-indexed). None = all pages
            detect_geometry: Try to detect circles/arcs from polylines
            detect_ellipse: Try to detect ellipses from polylines
            keep_dxf: Keep intermediate DXF file when converting to DWG
            use_true_color: Use 24-bit RGB colors (requires DXF R2004+)

        Returns:
            ConversionResult with status and output files
        """
        input_path = os.path.abspath(input_path)
        output_path = os.path.abspath(output_path)

        # Validate input
        if not os.path.isfile(input_path):
            return ConversionResult(
                success=False,
                output_files=[],
                message=f"Input file not found: {input_path}"
            )

        # Check DWG converter availability
        if output_format in (OutputFormat.DWG, OutputFormat.BOTH):
            if not self.can_convert_to_dwg():
                return ConversionResult(
                    success=False,
                    output_files=[],
                    message=self.get_dwg_install_instructions()
                )

        self._report_progress("Opening PDF...", 0.0)

        try:
            # Extract vector data from PDF
            with PDFVectorExtractor(input_path) as extractor:
                page_count = extractor.page_count

                if page_count == 0:
                    return ConversionResult(
                        success=False,
                        output_files=[],
                        message="PDF has no pages"
                    )

                # Determine which pages to process
                if pages is not None:
                    pages_to_process = [p for p in pages if 0 <= p < page_count]
                elif page_mode == PageMode.SINGLE:
                    pages_to_process = [0]
                else:
                    pages_to_process = list(range(page_count))

                self._report_progress(f"Extracting {len(pages_to_process)} page(s)...", 0.1)

                # Extract all requested pages
                extracted_pages: List[ExtractedData] = []
                for i, page_num in enumerate(pages_to_process):
                    progress = 0.1 + 0.4 * (i / len(pages_to_process))
                    self._report_progress(f"Extracting page {page_num + 1}...", progress)

                    page_data = extractor.extract_page(page_num, scale)

                    # Optionally detect circles and arcs
                    if detect_geometry:
                        detect_circles_and_arcs(page_data)

                    # Optionally detect ellipses
                    if detect_ellipse:
                        detect_ellipses(page_data)

                    extracted_pages.append(page_data)

            # Create output files
            output_files = []
            total_entities = 0

            # Calculate total entities
            for data in extracted_pages:
                total_entities += data.get_entity_count()

            self._report_progress("Creating DXF...", 0.5)

            # Determine output paths
            output_dir = os.path.dirname(output_path)
            output_base = os.path.splitext(os.path.basename(output_path))[0]

            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            if page_mode == PageMode.MERGE or len(extracted_pages) == 1:
                # Single output file
                dxf_path = os.path.join(output_dir or ".", f"{output_base}.dxf")

                if len(extracted_pages) == 1:
                    create_dxf_from_data(extracted_pages[0], dxf_path, dxf_version)
                else:
                    merge_pages_to_dxf(extracted_pages, dxf_path, dxf_version)

                # Convert to DWG if needed
                if output_format in (OutputFormat.DWG, OutputFormat.BOTH):
                    self._report_progress("Converting to DWG...", 0.7)
                    dwg_path = os.path.join(output_dir or ".", f"{output_base}.dwg")
                    success, msg = self.dwg_converter.convert(dxf_path, dwg_path, dwg_version)

                    if success:
                        output_files.append(dwg_path)
                    else:
                        return ConversionResult(
                            success=False,
                            output_files=[],
                            message=f"DWG conversion failed: {msg}",
                            pages_processed=len(extracted_pages)
                        )

                if output_format in (OutputFormat.DXF, OutputFormat.BOTH) or keep_dxf:
                    output_files.append(dxf_path)
                elif os.path.isfile(dxf_path):
                    os.remove(dxf_path)  # Clean up intermediate DXF

            else:
                # Separate output files for each page
                for i, page_data in enumerate(extracted_pages):
                    page_num = pages_to_process[i]
                    progress = 0.5 + 0.4 * (i / len(extracted_pages))
                    self._report_progress(f"Processing page {page_num + 1}...", progress)

                    dxf_path = os.path.join(output_dir or ".", f"{output_base}_page{page_num + 1}.dxf")
                    create_dxf_from_data(page_data, dxf_path, dxf_version)

                    if output_format in (OutputFormat.DWG, OutputFormat.BOTH):
                        dwg_path = os.path.join(output_dir or ".", f"{output_base}_page{page_num + 1}.dwg")
                        success, msg = self.dwg_converter.convert(dxf_path, dwg_path, dwg_version)

                        if success:
                            output_files.append(dwg_path)
                        else:
                            # Continue with other pages, but note the failure
                            pass

                    if output_format in (OutputFormat.DXF, OutputFormat.BOTH) or keep_dxf:
                        output_files.append(dxf_path)
                    elif os.path.isfile(dxf_path):
                        os.remove(dxf_path)

            self._report_progress("Complete!", 1.0)

            return ConversionResult(
                success=True,
                output_files=output_files,
                message=f"Successfully converted {len(extracted_pages)} page(s)",
                pages_processed=len(extracted_pages),
                entities_count=total_entities
            )

        except Exception as e:
            return ConversionResult(
                success=False,
                output_files=[],
                message=f"Conversion error: {str(e)}"
            )

    def convert_to_dxf_only(
        self,
        input_path: str,
        output_path: str,
        scale: float = 1.0,
        dxf_version: str = "R2010",
        page_mode: PageMode = PageMode.SINGLE,
        pages: Optional[List[int]] = None,
    ) -> ConversionResult:
        """
        Convert PDF to DXF only (no DWG conversion).

        This method doesn't require ODA File Converter.
        """
        return self.convert(
            input_path=input_path,
            output_path=output_path,
            scale=scale,
            output_format=OutputFormat.DXF,
            dxf_version=dxf_version,
            page_mode=page_mode,
            pages=pages,
        )


def quick_convert(
    pdf_path: str,
    output_path: Optional[str] = None,
    to_dwg: bool = True
) -> Tuple[bool, str]:
    """
    Quick conversion function for simple use cases.

    Args:
        pdf_path: Path to input PDF
        output_path: Output path (optional, defaults to same name with .dwg/.dxf)
        to_dwg: Convert to DWG (True) or DXF (False)

    Returns:
        Tuple of (success, message or output path)
    """
    if output_path is None:
        ext = ".dwg" if to_dwg else ".dxf"
        output_path = os.path.splitext(pdf_path)[0] + ext

    converter = PDFToDWGConverter()

    if to_dwg and not converter.can_convert_to_dwg():
        # Fall back to DXF
        output_path = os.path.splitext(output_path)[0] + ".dxf"
        result = converter.convert_to_dxf_only(pdf_path, output_path)
        if result.success:
            return True, f"Converted to DXF (DWG requires ODA File Converter): {output_path}"
        return False, result.message

    output_format = OutputFormat.DWG if to_dwg else OutputFormat.DXF
    result = converter.convert(pdf_path, output_path, output_format=output_format)

    if result.success:
        return True, result.output_files[0] if result.output_files else output_path
    return False, result.message
