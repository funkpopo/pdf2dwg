"""
Command Line Interface for PDF to DWG Converter

Usage:
    pdf2dwg input.pdf output.dwg
    pdf2dwg input.pdf --output output.dxf --format dxf
    pdf2dwg input.pdf --scale 2.0 --pages 0,1,2
"""

import os
import sys
import click
from pathlib import Path
from typing import Optional, List

from .converter import PDFToDWGConverter, OutputFormat, PageMode, ConversionResult
from .dwg_converter import DWGVersion


def parse_pages(ctx, param, value) -> Optional[List[int]]:
    """Parse comma-separated page numbers"""
    if value is None:
        return None
    try:
        return [int(p.strip()) for p in value.split(",")]
    except ValueError:
        raise click.BadParameter("Pages must be comma-separated integers (e.g., 0,1,2)")


@click.command()
@click.argument("input_file", type=click.Path(exists=True))
@click.argument("output_file", type=click.Path(), required=False)
@click.option(
    "-o", "--output",
    type=click.Path(),
    help="Output file path (alternative to positional argument)"
)
@click.option(
    "-f", "--format",
    type=click.Choice(["dwg", "dxf", "both"], case_sensitive=False),
    default="dwg",
    help="Output format (default: dwg)"
)
@click.option(
    "-s", "--scale",
    type=float,
    default=1.0,
    help="Scale factor for coordinates (default: 1.0)"
)
@click.option(
    "-v", "--version",
    type=click.Choice(["ACAD2000", "ACAD2004", "ACAD2007", "ACAD2010", "ACAD2013", "ACAD2018"]),
    default="ACAD2010",
    help="Target DWG version (default: ACAD2010)"
)
@click.option(
    "--dxf-version",
    type=click.Choice(["R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018"]),
    default="R2010",
    help="Target DXF version (default: R2010)"
)
@click.option(
    "-p", "--pages",
    callback=parse_pages,
    help="Specific pages to convert (0-indexed, comma-separated, e.g., 0,1,2)"
)
@click.option(
    "-m", "--mode",
    type=click.Choice(["single", "separate", "merge"], case_sensitive=False),
    default="single",
    help="Page mode: single (first page only), separate (each page to file), merge (all in one)"
)
@click.option(
    "--keep-dxf",
    is_flag=True,
    help="Keep intermediate DXF file when converting to DWG"
)
@click.option(
    "--no-geometry-detection",
    is_flag=True,
    help="Disable automatic circle/arc detection from polylines"
)
@click.option(
    "--oda-path",
    type=click.Path(),
    help="Path to ODA File Converter executable"
)
@click.option(
    "-q", "--quiet",
    is_flag=True,
    help="Suppress progress output"
)
@click.version_option(version="1.0.0")
def main(
    input_file: str,
    output_file: Optional[str],
    output: Optional[str],
    format: str,
    scale: float,
    version: str,
    dxf_version: str,
    pages: Optional[List[int]],
    mode: str,
    keep_dxf: bool,
    no_geometry_detection: bool,
    oda_path: Optional[str],
    quiet: bool,
):
    """
    Convert PDF files to DWG/DXF format for AutoCAD.

    \b
    Examples:
        pdf2dwg drawing.pdf                    # Convert to drawing.dwg
        pdf2dwg drawing.pdf output.dwg         # Convert to specified output
        pdf2dwg drawing.pdf -f dxf             # Convert to DXF format
        pdf2dwg drawing.pdf -s 2.0             # Scale by 2x
        pdf2dwg drawing.pdf -m merge           # Merge all pages
        pdf2dwg drawing.pdf -p 0,2,4           # Convert specific pages

    \b
    Requirements:
        - For DWG output: ODA File Converter must be installed
          Download from: https://www.opendesign.com/guestfiles/oda_file_converter
        - For DXF output: No additional requirements
    """
    # Determine output path
    out_path = output or output_file
    if out_path is None:
        # Default to same name with appropriate extension
        ext = ".dwg" if format.lower() == "dwg" else ".dxf"
        out_path = os.path.splitext(input_file)[0] + ext

    # Map format string to enum
    format_map = {
        "dwg": OutputFormat.DWG,
        "dxf": OutputFormat.DXF,
        "both": OutputFormat.BOTH,
    }
    output_format = format_map[format.lower()]

    # Map mode string to enum
    mode_map = {
        "single": PageMode.SINGLE,
        "separate": PageMode.SEPARATE,
        "merge": PageMode.MERGE,
    }
    page_mode = mode_map[mode.lower()]

    # Map version string to enum
    dwg_version = DWGVersion[version]

    # Create converter
    converter = PDFToDWGConverter(oda_path)

    # Set up progress reporting
    if not quiet:
        def progress_callback(message: str, progress: float):
            bar_width = 30
            filled = int(bar_width * progress)
            bar = "=" * filled + "-" * (bar_width - filled)
            click.echo(f"\r[{bar}] {int(progress * 100):3d}% {message}", nl=False)
            if progress >= 1.0:
                click.echo()  # New line when complete

        converter.set_progress_callback(progress_callback)

    # Check DWG converter availability
    if output_format in (OutputFormat.DWG, OutputFormat.BOTH):
        if not converter.can_convert_to_dwg():
            click.echo(click.style("Warning: ODA File Converter not found.", fg="yellow"))
            click.echo(converter.get_dwg_install_instructions())

            if output_format == OutputFormat.DWG:
                click.echo(click.style("Falling back to DXF format...", fg="yellow"))
                output_format = OutputFormat.DXF
                out_path = os.path.splitext(out_path)[0] + ".dxf"

    # Run conversion
    if not quiet:
        click.echo(f"Converting: {input_file}")
        click.echo(f"Output: {out_path}")

    result = converter.convert(
        input_path=input_file,
        output_path=out_path,
        scale=scale,
        output_format=output_format,
        dwg_version=dwg_version,
        dxf_version=dxf_version,
        page_mode=page_mode,
        pages=pages,
        detect_geometry=not no_geometry_detection,
        keep_dxf=keep_dxf,
    )

    # Report result
    if result.success:
        if not quiet:
            click.echo(click.style("\n✓ Conversion successful!", fg="green"))
            click.echo(f"  Pages processed: {result.pages_processed}")
            click.echo(f"  Entities: {result.entities_count}")
            click.echo("  Output files:")
            for f in result.output_files:
                click.echo(f"    - {f}")
        sys.exit(0)
    else:
        click.echo(click.style(f"\n✗ Conversion failed: {result.message}", fg="red"), err=True)
        sys.exit(1)


@click.command()
def check_oda():
    """Check if ODA File Converter is installed and working."""
    from .dwg_converter import DWGConverter

    converter = DWGConverter()

    if converter.is_available():
        click.echo(click.style("✓ ODA File Converter found!", fg="green"))
        click.echo(f"  Path: {converter.converter_path}")
    else:
        click.echo(click.style("✗ ODA File Converter not found", fg="red"))
        click.echo(converter._get_install_instructions())


if __name__ == "__main__":
    main()
