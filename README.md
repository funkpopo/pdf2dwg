# PDF to DWG Converter

Convert PDF files to AutoCAD-compatible DWG/DXF format.

## Features

- Extract vector graphics from PDF (lines, polylines, curves, text)
- Support multi-page PDF (single, separate, merge modes)
- Auto-detect arcs and circles
- Preserve color and line width

## Installation

```bash
pip install -r requirements.txt
```

### ODA File Converter (Optional, for DWG output)

Download from: https://www.opendesign.com/guestfiles/oda_file_converter

> Without ODA File Converter, you can still output DXF format.

## Usage

### Command Line

```bash
# Basic conversion
pdf2dwg drawing.pdf

# Specify output file
pdf2dwg drawing.pdf output.dwg

# Convert to DXF format
pdf2dwg drawing.pdf -f dxf

# Set scale
pdf2dwg drawing.pdf -s 2.0

# Merge all pages
pdf2dwg drawing.pdf -m merge

# Convert specific pages (0-indexed)
pdf2dwg drawing.pdf -p 0,2,4

# Specify DWG version
pdf2dwg drawing.pdf -v ACAD2018

# Show all options
pdf2dwg --help
```

### Python API

```python
from pdf2dwg import PDFToDWGConverter

converter = PDFToDWGConverter()
result = converter.convert("input.pdf", "output.dwg")

if result.success:
    print(f"Output: {result.output_files}")
```

## Dependencies

- **PyMuPDF** - PDF parsing
- **ezdxf** - DXF generation
- **click** - CLI
- **ODA File Converter** - DXF to DWG conversion (external)

## License

GPL License
