"""
DXF Writer Module

Creates DXF files from extracted PDF vector data using ezdxf library.
The generated DXF files are compatible with AutoCAD and other CAD software.
Supports all entity types including hatches, images, and line types.
"""

import ezdxf
from ezdxf import units
from ezdxf.enums import TextEntityAlignment
from ezdxf.tools.standards import linetypes
from typing import Optional, Tuple, Dict, List
import math
import os
import tempfile

from .pdf_extractor import (
    ExtractedData, Line, Arc, Circle, Ellipse, Polyline,
    Spline, TextEntity, MText, Rectangle, Hatch, ImageEntity, Point, LineType
)


class DXFWriter:
    """
    Write extracted vector data to DXF format.

    Supports:
    - Lines, polylines, and polygons
    - Circles, arcs, and ellipses
    - Splines (approximated from bezier curves)
    - Text with font, size, and rotation
    - Multiline text (MTEXT)
    - Layers with colors
    - Line types (continuous, dashed, dashdot, etc.)
    - Hatches (filled regions)
    - Raster images
    - Multiple DXF versions (R12, R2000, R2004, R2007, R2010, R2013, R2018)
    """

    # AutoCAD Color Index (ACI) mapping for common colors
    COLOR_MAP = {
        (1.0, 0.0, 0.0): 1,    # Red
        (1.0, 1.0, 0.0): 2,    # Yellow
        (0.0, 1.0, 0.0): 3,    # Green
        (0.0, 1.0, 1.0): 4,    # Cyan
        (0.0, 0.0, 1.0): 5,    # Blue
        (1.0, 0.0, 1.0): 6,    # Magenta
        (1.0, 1.0, 1.0): 7,    # White
        (0.0, 0.0, 0.0): 7,    # Black (displayed as white/black based on background)
        (0.5, 0.5, 0.5): 8,    # Gray
    }

    # DXF version mapping
    VERSION_MAP = {
        "R12": "R12",
        "R2000": "R2000",
        "R2004": "R2004",
        "R2007": "R2007",
        "R2010": "R2010",
        "R2013": "R2013",
        "R2018": "R2018",
    }

    # Line type mapping from PDF to DXF
    LINETYPE_MAP = {
        LineType.CONTINUOUS: "Continuous",
        LineType.DASHED: "DASHED",
        LineType.DASHDOT: "DASHDOT",
        LineType.DASHDOT2: "DASHDOT2",
        LineType.DOTTED: "DOT",
        LineType.HIDDEN: "HIDDEN",
    }

    def __init__(self, version: str = "R2010", use_true_color: bool = True):
        """
        Initialize DXF writer.

        Args:
            version: DXF version (R12, R2000, R2004, R2007, R2010, R2013, R2018)
            use_true_color: Use 24-bit RGB colors instead of ACI (requires R2004+)
        """
        self.version = self.VERSION_MAP.get(version, "R2010")
        self.doc = None
        self.msp = None
        self.layers_created = set()
        self.linetypes_created = set()
        self.image_counter = 0
        self.output_dir = ""
        # True color requires R2004 or later
        self.use_true_color = use_true_color and self.version not in ("R12", "R2000")

    def create_document(self, data: ExtractedData, output_path: str = "") -> ezdxf.document.Drawing:
        """
        Create a new DXF document from extracted data.

        Args:
            data: ExtractedData from PDF extraction
            output_path: Output path (used for saving images relative to DXF)

        Returns:
            ezdxf Drawing object
        """
        self.output_dir = os.path.dirname(os.path.abspath(output_path)) if output_path else ""

        # Create new document with specified version
        self.doc = ezdxf.new(self.version)

        # Set units to millimeters (common for technical drawings)
        self.doc.units = units.MM

        # Set up text styles for CJK (Chinese/Japanese/Korean) support
        self._setup_text_styles()

        # Set up line types
        self._setup_linetypes()

        # Get modelspace for adding entities
        self.msp = self.doc.modelspace()

        # Create layers based on extracted data
        self._setup_layers(data)

        # Add all entities
        self._add_lines(data.lines)
        self._add_circles(data.circles)
        self._add_arcs(data.arcs)
        self._add_ellipses(data.ellipses)
        self._add_polylines(data.polylines)
        self._add_splines(data.splines)
        self._add_rectangles(data.rectangles)
        self._add_hatches(data.hatches)
        self._add_texts(data.texts)
        self._add_mtexts(data.mtexts)
        self._add_images(data.images)

        return self.doc

    def _setup_text_styles(self):
        """Set up text styles with CJK font support"""
        # Create a text style that uses a TrueType font supporting Chinese
        if not self.doc.styles.has_entry("CJK"):
            self.doc.styles.add(
                "CJK",
                font="SimSun",  # 宋体 - most common Chinese font on Windows
            )

        # Also add a style for standard text
        if not self.doc.styles.has_entry("Standard"):
            try:
                self.doc.styles.add("Standard", font="Arial")
            except Exception:
                pass  # Standard style might already exist

    def _setup_linetypes(self):
        """Set up standard line types"""
        # Add standard linetypes if not already present
        standard_linetypes = [
            ("DASHED", "Dashed __ __ __ __", [0.5, -0.25]),
            ("DASHDOT", "Dash dot __ . __ . __", [0.5, -0.25, 0.0, -0.25]),
            ("DASHDOT2", "Dash dot (.5x) _._._._._._", [0.25, -0.125, 0.0, -0.125]),
            ("DOT", "Dot . . . . . . . .", [0.0, -0.25]),
            ("HIDDEN", "Hidden __ __ __ __", [0.25, -0.125]),
            ("CENTER", "Center ____ _ ____ _", [1.25, -0.25, 0.25, -0.25]),
        ]

        for name, description, pattern in standard_linetypes:
            if not self.doc.linetypes.has_entry(name):
                try:
                    self.doc.linetypes.add(name, pattern=pattern, description=description)
                    self.linetypes_created.add(name)
                except Exception:
                    pass  # Linetype might already exist or pattern might be invalid

    def _setup_layers(self, data: ExtractedData):
        """
        Set up layers in the document.

        Creates layers based on:
        - PDF optional content groups (layers)
        - Preserves layer visibility and properties
        - Creates default layer "0" for fallback
        """
        # Create default layer
        if "0" not in self.doc.layers:
            self.doc.layers.add("0")
        self.layers_created.add("0")

        # Create layers from extracted data with full properties
        for layer_id, layer_info in data.layers.items():
            layer_name = layer_info.get("name", layer_id)
            if layer_name and layer_name not in self.layers_created:
                try:
                    # Create layer with properties
                    layer = self.doc.layers.add(layer_name)

                    # Set layer visibility (on/off)
                    is_visible = layer_info.get("visible", True)
                    if not is_visible:
                        layer.off()

                    # Set layer color if specified
                    layer_color = layer_info.get("color")
                    if layer_color and isinstance(layer_color, (list, tuple)) and len(layer_color) >= 3:
                        if self.use_true_color:
                            layer.true_color = self._rgb_to_true_color(layer_color)
                        else:
                            layer.color = self._rgb_to_aci(layer_color)

                    # Set layer locked status
                    is_locked = layer_info.get("locked", False)
                    if is_locked:
                        layer.lock()

                    # Set layer plot style
                    plot_style = layer_info.get("plot_style")
                    if plot_style:
                        try:
                            layer.dxf.plotstyle_name = plot_style
                        except Exception:
                            pass

                    self.layers_created.add(layer_name)
                except Exception:
                    pass  # Layer might already exist

    def _get_or_create_layer(self, layer_name: str) -> str:
        """
        Get layer name, creating it if necessary.

        Args:
            layer_name: Desired layer name

        Returns:
            The layer name (may fall back to "0" if creation fails)
        """
        if not layer_name:
            return "0"

        if layer_name not in self.layers_created:
            try:
                self.doc.layers.add(layer_name)
                self.layers_created.add(layer_name)
            except Exception:
                layer_name = "0"  # Fallback to default layer
        return layer_name

    def _get_linetype(self, linetype: LineType) -> str:
        """Get DXF linetype name from LineType enum"""
        dxf_linetype = self.LINETYPE_MAP.get(linetype, "Continuous")

        # Ensure linetype exists in document
        if dxf_linetype != "Continuous" and not self.doc.linetypes.has_entry(dxf_linetype):
            return "Continuous"

        return dxf_linetype

    def _rgb_to_aci(self, color: Tuple[float, float, float]) -> int:
        """
        Convert RGB color to AutoCAD Color Index (ACI).

        Args:
            color: RGB tuple with values 0-1

        Returns:
            ACI color number (1-255)
        """
        # Check for exact match in color map
        for rgb, aci in self.COLOR_MAP.items():
            if self._colors_match(color, rgb):
                return aci

        # Calculate nearest ACI color based on RGB values
        r, g, b = color

        # Handle near-black colors
        if r < 0.1 and g < 0.1 and b < 0.1:
            return 7  # Use white (adapts to background)

        # Handle near-white colors
        if r > 0.9 and g > 0.9 and b > 0.9:
            return 7  # White

        # Simple mapping based on dominant color
        if r > 0.7 and g < 0.3 and b < 0.3:
            return 1  # Red
        elif r > 0.7 and g > 0.7 and b < 0.3:
            return 2  # Yellow
        elif r < 0.3 and g > 0.7 and b < 0.3:
            return 3  # Green
        elif r < 0.3 and g > 0.7 and b > 0.7:
            return 4  # Cyan
        elif r < 0.3 and g < 0.3 and b > 0.7:
            return 5  # Blue
        elif r > 0.7 and g < 0.3 and b > 0.7:
            return 6  # Magenta

        # Gray scale mapping
        gray = (r + g + b) / 3
        if gray < 0.25:
            return 250  # Dark gray
        elif gray < 0.5:
            return 251
        elif gray < 0.75:
            return 252
        else:
            return 253  # Light gray

    def _rgb_to_true_color(self, color: Tuple[float, float, float]) -> int:
        """
        Convert RGB color (0-1 range) to DXF true color value.

        Args:
            color: RGB tuple with values 0-1

        Returns:
            24-bit RGB color value for DXF true_color attribute
        """
        r = int(min(255, max(0, color[0] * 255)))
        g = int(min(255, max(0, color[1] * 255)))
        b = int(min(255, max(0, color[2] * 255)))
        return (r << 16) | (g << 8) | b

    def _get_color_attribs(self, color: Tuple[float, float, float]) -> Dict:
        """
        Get color attributes for entity.

        Returns either ACI color or true color based on settings.

        Args:
            color: RGB tuple with values 0-1

        Returns:
            Dictionary with color attributes
        """
        if self.use_true_color:
            # Use true color (24-bit RGB)
            return {"true_color": self._rgb_to_true_color(color)}
        else:
            # Use ACI color
            return {"color": self._rgb_to_aci(color)}

    def _colors_match(self, c1: Tuple[float, float, float],
                      c2: Tuple[float, float, float], tolerance: float = 0.1) -> bool:
        """Check if two colors match within tolerance"""
        return (abs(c1[0] - c2[0]) < tolerance and
                abs(c1[1] - c2[1]) < tolerance and
                abs(c1[2] - c2[2]) < tolerance)

    def _add_lines(self, lines: List[Line]):
        """Add line entities to modelspace"""
        for line in lines:
            layer = self._get_or_create_layer(line.layer)
            linetype = self._get_linetype(line.linetype)

            attribs = {
                "layer": layer,
                "linetype": linetype,
                "lineweight": self._mm_to_lineweight(line.width)
            }
            attribs.update(self._get_color_attribs(line.color))

            self.msp.add_line(
                start=(line.start.x, line.start.y),
                end=(line.end.x, line.end.y),
                dxfattribs=attribs
            )

    def _add_circles(self, circles: List[Circle]):
        """Add circle entities to modelspace"""
        for circle in circles:
            layer = self._get_or_create_layer(circle.layer)
            linetype = self._get_linetype(circle.linetype)

            attribs = {
                "layer": layer,
                "linetype": linetype,
                "lineweight": self._mm_to_lineweight(circle.width)
            }
            attribs.update(self._get_color_attribs(circle.color))

            self.msp.add_circle(
                center=(circle.center.x, circle.center.y),
                radius=circle.radius,
                dxfattribs=attribs
            )

    def _add_arcs(self, arcs: List[Arc]):
        """Add arc entities to modelspace"""
        for arc in arcs:
            layer = self._get_or_create_layer(arc.layer)
            linetype = self._get_linetype(arc.linetype)

            attribs = {
                "layer": layer,
                "linetype": linetype,
                "lineweight": self._mm_to_lineweight(arc.width)
            }
            attribs.update(self._get_color_attribs(arc.color))

            self.msp.add_arc(
                center=(arc.center.x, arc.center.y),
                radius=arc.radius,
                start_angle=arc.start_angle,
                end_angle=arc.end_angle,
                dxfattribs=attribs
            )

    def _add_ellipses(self, ellipses: List[Ellipse]):
        """Add ellipse entities to modelspace"""
        for ellipse in ellipses:
            layer = self._get_or_create_layer(ellipse.layer)
            linetype = self._get_linetype(ellipse.linetype)

            attribs = {
                "layer": layer,
                "linetype": linetype,
            }
            attribs.update(self._get_color_attribs(ellipse.color))

            try:
                self.msp.add_ellipse(
                    center=(ellipse.center.x, ellipse.center.y),
                    major_axis=(ellipse.major_axis.x, ellipse.major_axis.y, 0),
                    ratio=ellipse.ratio,
                    start_param=ellipse.start_param,
                    end_param=ellipse.end_param,
                    dxfattribs=attribs
                )
            except Exception:
                # Fallback: convert to polyline approximation
                pass

    def _add_polylines(self, polylines: List[Polyline]):
        """Add polyline entities to modelspace"""
        for polyline in polylines:
            if len(polyline.points) < 2:
                continue

            layer = self._get_or_create_layer(polyline.layer)
            linetype = self._get_linetype(polyline.linetype)

            attribs = {
                "layer": layer,
                "linetype": linetype,
                "lineweight": self._mm_to_lineweight(polyline.width)
            }
            attribs.update(self._get_color_attribs(polyline.color))

            points = [(p.x, p.y) for p in polyline.points]

            self.msp.add_lwpolyline(
                points,
                close=polyline.closed,
                dxfattribs=attribs
            )

    def _add_splines(self, splines: List[Spline]):
        """Add spline entities to modelspace"""
        for spline in splines:
            if len(spline.control_points) < 2:
                continue

            layer = self._get_or_create_layer(spline.layer)
            linetype = self._get_linetype(spline.linetype)

            attribs = {
                "layer": layer,
                "linetype": linetype,
            }
            attribs.update(self._get_color_attribs(spline.color))

            # Convert control points to fit points for better compatibility
            fit_points = [(p.x, p.y) for p in spline.control_points]

            try:
                # Try to add as spline
                self.msp.add_spline(
                    fit_points,
                    degree=min(spline.degree, len(fit_points) - 1),
                    dxfattribs=attribs
                )
            except Exception:
                # Fallback to polyline if spline fails
                self.msp.add_lwpolyline(
                    fit_points,
                    dxfattribs=attribs
                )

    def _add_rectangles(self, rectangles: List[Rectangle]):
        """Add rectangle entities as closed polylines"""
        for rect in rectangles:
            layer = self._get_or_create_layer(rect.layer)
            linetype = self._get_linetype(rect.linetype)

            attribs = {
                "layer": layer,
                "linetype": linetype,
                "lineweight": self._mm_to_lineweight(rect.line_width)
            }
            attribs.update(self._get_color_attribs(rect.color))

            # Create rectangle as closed polyline
            points = [
                (rect.corner.x, rect.corner.y),
                (rect.corner.x + rect.width, rect.corner.y),
                (rect.corner.x + rect.width, rect.corner.y + rect.height),
                (rect.corner.x, rect.corner.y + rect.height),
            ]

            self.msp.add_lwpolyline(
                points,
                close=True,
                dxfattribs=attribs
            )

    def _add_hatches(self, hatches: List[Hatch]):
        """
        Add hatch (filled region) entities to modelspace.

        Supports:
        - Solid fills
        - Pattern fills with scale and angle
        - Gradient fills (linear, cylindrical, spherical)
        - Background colors for pattern fills
        """
        for hatch_data in hatches:
            layer = self._get_or_create_layer(hatch_data.layer)
            color_attribs = self._get_color_attribs(hatch_data.color)

            try:
                # Create hatch entity
                hatch_attribs = {"layer": layer}
                hatch_attribs.update(color_attribs)

                hatch = self.msp.add_hatch(dxfattribs=hatch_attribs)

                # Handle gradient fills
                if hatch_data.is_gradient and hatch_data.gradient_color1 and hatch_data.gradient_color2:
                    # Set gradient fill
                    color1 = self._rgb_to_true_color(hatch_data.gradient_color1)
                    color2 = self._rgb_to_true_color(hatch_data.gradient_color2)

                    # Gradient type mapping
                    gradient_type_map = {
                        "LINEAR": 0,
                        "CYLINDRICAL": 1,
                        "SPHERICAL": 2,
                    }
                    gtype = gradient_type_map.get(hatch_data.gradient_type.upper(), 0)

                    try:
                        hatch.set_gradient(
                            color1=color1,
                            color2=color2,
                            rotation=hatch_data.gradient_angle,
                            centered=hatch_data.gradient_centered,
                            one_color=False
                        )
                    except Exception:
                        # Fallback to solid fill with first color
                        hatch.set_solid_fill()
                elif hatch_data.pattern_name == "SOLID":
                    hatch.set_solid_fill()
                else:
                    # Pattern fill
                    try:
                        hatch.set_pattern_fill(
                            hatch_data.pattern_name,
                            scale=hatch_data.scale,
                            angle=hatch_data.angle
                        )
                        # Set background color if provided
                        if hatch_data.bgcolor:
                            try:
                                bg_color = self._rgb_to_true_color(hatch_data.bgcolor)
                                hatch.dxf.bgcolor = bg_color
                            except Exception:
                                pass
                    except Exception:
                        # Fallback to solid fill if pattern not found
                        hatch.set_solid_fill()

                # Add boundary paths
                for boundary_points in hatch_data.boundary_paths:
                    if len(boundary_points) >= 3:
                        path_points = [(p.x, p.y) for p in boundary_points]
                        hatch.paths.add_polyline_path(path_points, is_closed=True)

            except Exception:
                # Skip problematic hatches
                pass

    def _add_texts(self, texts: List[TextEntity]):
        """Add text entities to modelspace"""
        for text in texts:
            if not text.text.strip():
                continue

            layer = self._get_or_create_layer(text.layer)
            color_attribs = self._get_color_attribs(text.color)

            # Use TEXT entity with CJK style for proper Chinese character support
            try:
                attribs = {
                    "layer": layer,
                    "insert": (text.position.x, text.position.y),
                    "style": "CJK",
                    "rotation": text.rotation,
                }
                attribs.update(color_attribs)

                # Add oblique angle if text is italic
                if text.oblique != 0:
                    attribs["oblique"] = text.oblique

                # Add width factor if different from 1.0
                if abs(text.width_factor - 1.0) > 0.01:
                    attribs["width"] = text.width_factor

                self.msp.add_text(
                    text.text,
                    height=text.height,
                    dxfattribs=attribs
                )
            except Exception:
                # Skip problematic text
                pass

    def _add_mtexts(self, mtexts: List[MText]):
        """Add multiline text entities to modelspace"""
        for mtext in mtexts:
            if not mtext.text.strip():
                continue

            layer = self._get_or_create_layer(mtext.layer)
            color_attribs = self._get_color_attribs(mtext.color)

            try:
                attribs = {
                    "layer": layer,
                    "insert": (mtext.position.x, mtext.position.y),
                    "char_height": mtext.height,
                    "rotation": mtext.rotation,
                    "attachment_point": mtext.attachment_point,
                    "style": "CJK",
                }
                attribs.update(color_attribs)

                if mtext.width > 0:
                    attribs["width"] = mtext.width

                self.msp.add_mtext(
                    mtext.text,
                    dxfattribs=attribs
                )
            except Exception:
                # Fallback to regular text
                try:
                    attribs = {
                        "layer": layer,
                        "insert": (mtext.position.x, mtext.position.y),
                        "style": "CJK",
                    }
                    attribs.update(color_attribs)

                    self.msp.add_text(
                        mtext.text,
                        height=mtext.height,
                        dxfattribs=attribs
                    )
                except Exception:
                    pass

    def _add_images(self, images: List[ImageEntity]):
        """Add raster image entities to modelspace"""
        for image in images:
            if not image.image_data:
                continue

            try:
                # Save image to file
                self.image_counter += 1
                image_filename = f"image_{self.image_counter}.png"

                if self.output_dir:
                    image_path = os.path.join(self.output_dir, image_filename)
                else:
                    image_path = image_filename

                # Write image data to file
                with open(image_path, 'wb') as f:
                    f.write(image.image_data)

                # Calculate image size in pixels (we need this for DXF)
                # Use a default DPI of 96 if we can't determine actual size
                pixels_per_mm = 96 / 25.4  # 96 DPI

                # Add image definition
                image_def = self.doc.add_image_def(
                    filename=image_path,
                    size_in_pixel=(
                        int(image.width * pixels_per_mm),
                        int(image.height * pixels_per_mm)
                    )
                )

                # Add image to modelspace
                layer = self._get_or_create_layer(image.layer)

                self.msp.add_image(
                    insert=(image.position.x, image.position.y),
                    size_in_units=(image.width, image.height),
                    image_def=image_def,
                    rotation=image.rotation,
                    dxfattribs={
                        "layer": layer,
                    }
                )

                # Store the path back to the image entity
                image.image_path = image_path

            except Exception as e:
                # Skip problematic images
                continue

    def _mm_to_lineweight(self, width: float) -> int:
        """
        Convert line width in mm to DXF lineweight value.

        DXF lineweights are in 1/100 mm units.
        """
        # Standard lineweights in 1/100 mm
        standard_weights = [0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50,
                          53, 60, 70, 80, 90, 100, 106, 120, 140, 158,
                          200, 211]

        weight_100 = int(width * 100)

        # Find nearest standard weight
        nearest = min(standard_weights, key=lambda x: abs(x - weight_100))
        return nearest

    def save(self, filepath: str):
        """
        Save the DXF document to file.

        Args:
            filepath: Output file path
        """
        if self.doc:
            # Use UTF-8 encoding for proper Chinese character support
            self.doc.saveas(filepath, encoding='utf-8')

    def save_to_bytes(self) -> bytes:
        """
        Save the DXF document to bytes.

        Returns:
            DXF file content as bytes
        """
        if self.doc:
            import io
            stream = io.BytesIO()
            self.doc.write(stream)
            return stream.getvalue()
        return b""


def create_dxf_from_data(data: ExtractedData, output_path: str,
                         version: str = "R2010") -> str:
    """
    Convenience function to create DXF file from extracted data.

    Args:
        data: ExtractedData from PDF extraction
        output_path: Output DXF file path
        version: DXF version

    Returns:
        Path to created DXF file
    """
    writer = DXFWriter(version)
    writer.create_document(data, output_path)
    writer.save(output_path)
    return output_path


def merge_pages_to_dxf(pages_data: List[ExtractedData], output_path: str,
                       version: str = "R2010", spacing: float = 50.0) -> str:
    """
    Merge multiple pages into a single DXF file.

    Pages are arranged horizontally with specified spacing.

    Args:
        pages_data: List of ExtractedData from multiple pages
        output_path: Output DXF file path
        version: DXF version
        spacing: Spacing between pages in mm

    Returns:
        Path to created DXF file
    """
    if not pages_data:
        raise ValueError("No pages to merge")

    # Create combined data
    combined = ExtractedData()
    x_offset = 0.0

    for i, page_data in enumerate(pages_data):
        page_layer = f"Page_{i+1}"

        # Offset all entities by x_offset
        for line in page_data.lines:
            new_line = Line(
                start=Point(line.start.x + x_offset, line.start.y),
                end=Point(line.end.x + x_offset, line.end.y),
                color=line.color,
                width=line.width,
                layer=page_layer,
                linetype=line.linetype
            )
            combined.lines.append(new_line)

        for circle in page_data.circles:
            new_circle = Circle(
                center=Point(circle.center.x + x_offset, circle.center.y),
                radius=circle.radius,
                color=circle.color,
                width=circle.width,
                layer=page_layer,
                linetype=circle.linetype
            )
            combined.circles.append(new_circle)

        for arc in page_data.arcs:
            new_arc = Arc(
                center=Point(arc.center.x + x_offset, arc.center.y),
                radius=arc.radius,
                start_angle=arc.start_angle,
                end_angle=arc.end_angle,
                color=arc.color,
                width=arc.width,
                layer=page_layer,
                linetype=arc.linetype
            )
            combined.arcs.append(new_arc)

        for ellipse in page_data.ellipses:
            new_ellipse = Ellipse(
                center=Point(ellipse.center.x + x_offset, ellipse.center.y),
                major_axis=ellipse.major_axis,
                ratio=ellipse.ratio,
                start_param=ellipse.start_param,
                end_param=ellipse.end_param,
                color=ellipse.color,
                width=ellipse.width,
                layer=page_layer,
                linetype=ellipse.linetype
            )
            combined.ellipses.append(new_ellipse)

        for polyline in page_data.polylines:
            new_points = [Point(p.x + x_offset, p.y) for p in polyline.points]
            new_polyline = Polyline(
                points=new_points,
                closed=polyline.closed,
                color=polyline.color,
                width=polyline.width,
                layer=page_layer,
                linetype=polyline.linetype
            )
            combined.polylines.append(new_polyline)

        for spline in page_data.splines:
            new_points = [Point(p.x + x_offset, p.y) for p in spline.control_points]
            new_spline = Spline(
                control_points=new_points,
                degree=spline.degree,
                color=spline.color,
                width=spline.width,
                layer=page_layer,
                linetype=spline.linetype
            )
            combined.splines.append(new_spline)

        for rect in page_data.rectangles:
            new_rect = Rectangle(
                corner=Point(rect.corner.x + x_offset, rect.corner.y),
                width=rect.width,
                height=rect.height,
                color=rect.color,
                line_width=rect.line_width,
                layer=page_layer,
                linetype=rect.linetype,
                fill_color=rect.fill_color
            )
            combined.rectangles.append(new_rect)

        for hatch in page_data.hatches:
            new_paths = []
            for path in hatch.boundary_paths:
                new_path = [Point(p.x + x_offset, p.y) for p in path]
                new_paths.append(new_path)
            new_hatch = Hatch(
                boundary_paths=new_paths,
                pattern_name=hatch.pattern_name,
                color=hatch.color,
                layer=page_layer,
                scale=hatch.scale,
                angle=hatch.angle
            )
            combined.hatches.append(new_hatch)

        for text in page_data.texts:
            new_text = TextEntity(
                text=text.text,
                position=Point(text.position.x + x_offset, text.position.y),
                height=text.height,
                rotation=text.rotation,
                color=text.color,
                font=text.font,
                layer=page_layer,
                halign=text.halign,
                valign=text.valign,
                width_factor=text.width_factor,
                oblique=text.oblique
            )
            combined.texts.append(new_text)

        for mtext in page_data.mtexts:
            new_mtext = MText(
                text=mtext.text,
                position=Point(mtext.position.x + x_offset, mtext.position.y),
                width=mtext.width,
                height=mtext.height,
                rotation=mtext.rotation,
                color=mtext.color,
                font=mtext.font,
                layer=page_layer,
                attachment_point=mtext.attachment_point
            )
            combined.mtexts.append(new_mtext)

        for image in page_data.images:
            new_image = ImageEntity(
                position=Point(image.position.x + x_offset, image.position.y),
                width=image.width,
                height=image.height,
                image_data=image.image_data,
                layer=page_layer,
                rotation=image.rotation
            )
            combined.images.append(new_image)

        # Update offset for next page
        x_offset += page_data.width + spacing

    # Create DXF
    return create_dxf_from_data(combined, output_path, version)
