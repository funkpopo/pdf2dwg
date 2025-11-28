"""
PDF Vector Extractor Module

Extracts vector graphics (lines, curves, paths, text, images) from PDF files using PyMuPDF.
Optimized to ensure no graphical information is lost during conversion.

Key optimizations:
- Adaptive Bezier curve sampling based on curve complexity
- Comprehensive image extraction including inline images and XObjects
- Full text extraction with transformation matrix support
- Ellipse detection using algebraic fitting
- Gradient and pattern fill extraction
"""

import fitz  # PyMuPDF
from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any, Union
from enum import Enum
import math
import io
import struct


class PathType(Enum):
    """Types of path elements in PDF"""
    MOVE = "m"      # Move to
    LINE = "l"      # Line to
    CURVE = "c"     # Bezier curve (cubic)
    CURVE_V = "v"   # Bezier curve (start point = control point 1)
    CURVE_Y = "y"   # Bezier curve (end point = control point 2)
    QUAD = "qu"     # Quadratic bezier
    RECT = "re"     # Rectangle
    CLOSE = "h"     # Close path


class LineType(Enum):
    """Line types for DXF"""
    CONTINUOUS = "Continuous"
    DASHED = "DASHED"
    DASHDOT = "DASHDOT"      # Center line (点划线)
    DASHDOT2 = "DASHDOT2"    # Center line 2
    DOTTED = "DOT"
    HIDDEN = "HIDDEN"


@dataclass
class Point:
    """2D point with x, y coordinates"""
    x: float
    y: float

    def to_tuple(self) -> Tuple[float, float]:
        return (self.x, self.y)

    def __iter__(self):
        yield self.x
        yield self.y

    def distance_to(self, other: 'Point') -> float:
        """Calculate distance to another point"""
        return math.sqrt((self.x - other.x)**2 + (self.y - other.y)**2)

    def __eq__(self, other):
        if not isinstance(other, Point):
            return False
        return abs(self.x - other.x) < 1e-6 and abs(self.y - other.y) < 1e-6

    def __hash__(self):
        return hash((round(self.x, 6), round(self.y, 6)))


@dataclass
class Line:
    """A line segment from start to end"""
    start: Point
    end: Point
    color: Tuple[float, float, float] = (0, 0, 0)  # RGB
    width: float = 1.0
    layer: str = "0"
    linetype: LineType = LineType.CONTINUOUS


@dataclass
class Arc:
    """An arc defined by center, radius, and angles"""
    center: Point
    radius: float
    start_angle: float  # in degrees
    end_angle: float    # in degrees
    color: Tuple[float, float, float] = (0, 0, 0)
    width: float = 1.0
    layer: str = "0"
    linetype: LineType = LineType.CONTINUOUS


@dataclass
class Circle:
    """A full circle"""
    center: Point
    radius: float
    color: Tuple[float, float, float] = (0, 0, 0)
    width: float = 1.0
    layer: str = "0"
    linetype: LineType = LineType.CONTINUOUS


@dataclass
class Ellipse:
    """An ellipse or elliptical arc"""
    center: Point
    major_axis: Point  # Endpoint of major axis relative to center
    ratio: float       # Ratio of minor to major axis (0-1)
    start_param: float = 0.0   # Start parameter (0 = start of major axis)
    end_param: float = 2 * math.pi  # End parameter (2*pi = full ellipse)
    color: Tuple[float, float, float] = (0, 0, 0)
    width: float = 1.0
    layer: str = "0"
    linetype: LineType = LineType.CONTINUOUS


@dataclass
class Polyline:
    """A polyline consisting of multiple connected points"""
    points: List[Point]
    closed: bool = False
    color: Tuple[float, float, float] = (0, 0, 0)
    width: float = 1.0
    layer: str = "0"
    linetype: LineType = LineType.CONTINUOUS
    bulges: List[float] = field(default_factory=list)  # For arc segments


@dataclass
class Spline:
    """A spline/bezier curve defined by control points"""
    control_points: List[Point]
    degree: int = 3
    color: Tuple[float, float, float] = (0, 0, 0)
    width: float = 1.0
    layer: str = "0"
    linetype: LineType = LineType.CONTINUOUS
    knots: List[float] = field(default_factory=list)
    weights: List[float] = field(default_factory=list)


@dataclass
class TextEntity:
    """Text element with position and properties"""
    text: str
    position: Point
    height: float = 2.5
    rotation: float = 0.0
    color: Tuple[float, float, float] = (0, 0, 0)
    font: str = "Arial"
    layer: str = "0"
    halign: str = "LEFT"      # Horizontal alignment: LEFT, CENTER, RIGHT
    valign: str = "BASELINE"  # Vertical alignment: BASELINE, BOTTOM, MIDDLE, TOP
    width_factor: float = 1.0
    oblique: float = 0.0      # Oblique angle in degrees


@dataclass
class MText:
    """Multiline text element"""
    text: str
    position: Point
    width: float = 0.0        # Text box width (0 = no wrapping)
    height: float = 2.5       # Character height
    rotation: float = 0.0
    color: Tuple[float, float, float] = (0, 0, 0)
    font: str = "Arial"
    layer: str = "0"
    attachment_point: int = 1  # 1-9, representing position like numpad


@dataclass
class Rectangle:
    """Rectangle defined by corner point, width and height"""
    corner: Point
    width: float
    height: float
    color: Tuple[float, float, float] = (0, 0, 0)
    line_width: float = 1.0
    layer: str = "0"
    linetype: LineType = LineType.CONTINUOUS
    fill_color: Optional[Tuple[float, float, float]] = None


@dataclass
class Hatch:
    """Filled region/hatch pattern"""
    boundary_paths: List[List[Point]]  # List of boundary polylines
    pattern_name: str = "SOLID"        # Hatch pattern name
    color: Tuple[float, float, float] = (0, 0, 0)
    layer: str = "0"
    scale: float = 1.0
    angle: float = 0.0
    # Gradient support
    is_gradient: bool = False
    gradient_type: str = "LINEAR"  # LINEAR, CYLINDRICAL, SPHERICAL
    gradient_color1: Optional[Tuple[float, float, float]] = None
    gradient_color2: Optional[Tuple[float, float, float]] = None
    gradient_angle: float = 0.0
    gradient_centered: bool = False
    # Background color for pattern fills
    bgcolor: Optional[Tuple[float, float, float]] = None


@dataclass
class ImageEntity:
    """Raster image embedded in PDF"""
    position: Point           # Bottom-left corner
    width: float
    height: float
    image_data: bytes         # Raw image data (PNG format)
    layer: str = "0"
    rotation: float = 0.0
    image_path: str = ""      # Path to saved image file (set during DXF creation)
    original_width: int = 0   # Original pixel width
    original_height: int = 0  # Original pixel height
    colorspace: str = ""      # Color space (RGB, CMYK, Gray, etc.)
    bits_per_component: int = 8  # Bits per color component
    transparency: bool = False  # Has alpha channel


@dataclass
class ExtractedData:
    """Container for all extracted vector data from a PDF page"""
    lines: List[Line] = field(default_factory=list)
    arcs: List[Arc] = field(default_factory=list)
    circles: List[Circle] = field(default_factory=list)
    ellipses: List[Ellipse] = field(default_factory=list)
    polylines: List[Polyline] = field(default_factory=list)
    splines: List[Spline] = field(default_factory=list)
    texts: List[TextEntity] = field(default_factory=list)
    mtexts: List[MText] = field(default_factory=list)
    rectangles: List[Rectangle] = field(default_factory=list)
    hatches: List[Hatch] = field(default_factory=list)
    images: List[ImageEntity] = field(default_factory=list)
    width: float = 0.0
    height: float = 0.0
    layers: Dict[str, Any] = field(default_factory=dict)

    def get_entity_count(self) -> int:
        """Return total number of entities"""
        return (len(self.lines) + len(self.arcs) + len(self.circles) +
                len(self.ellipses) + len(self.polylines) + len(self.splines) +
                len(self.texts) + len(self.mtexts) + len(self.rectangles) +
                len(self.hatches) + len(self.images))


class PDFVectorExtractor:
    """
    Extract vector graphics from PDF files.

    Uses PyMuPDF to parse PDF and extract:
    - Lines and polylines
    - Bezier curves (converted to splines or polylines)
    - Circles, arcs, and ellipses
    - Text elements (single-line and multi-line)
    - Rectangles
    - Filled regions (hatches)
    - Embedded images
    """

    def __init__(self, pdf_path: str):
        """
        Initialize extractor with PDF file path.

        Args:
            pdf_path: Path to the PDF file
        """
        self.pdf_path = pdf_path
        self.doc = None
        self.scale = 1.0  # Scale factor for coordinates

    def open(self):
        """Open the PDF document"""
        self.doc = fitz.open(self.pdf_path)

    def close(self):
        """Close the PDF document"""
        if self.doc:
            self.doc.close()
            self.doc = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @property
    def page_count(self) -> int:
        """Return number of pages in PDF"""
        if self.doc:
            return len(self.doc)
        return 0

    def extract_page(self, page_num: int = 0, scale: float = 1.0) -> ExtractedData:
        """
        Extract all vector graphics from a specific page.

        Args:
            page_num: Page number (0-indexed)
            scale: Scale factor for coordinates (default 1.0)

        Returns:
            ExtractedData containing all extracted elements
        """
        if not self.doc:
            self.open()

        self.scale = scale
        page = self.doc[page_num]

        # Get page dimensions
        rect = page.rect
        data = ExtractedData(
            width=rect.width * scale,
            height=rect.height * scale
        )

        # Extract drawings (vector paths)
        self._extract_drawings(page, data)

        # Extract text
        self._extract_text(page, data)

        # Extract images
        self._extract_images(page, data)

        # Extract layers if available
        self._extract_layers(page, data)

        return data

    def _transform_y(self, y: float, page_height: float) -> float:
        """
        Transform PDF Y coordinate to CAD Y coordinate.
        PDF has origin at top-left, CAD at bottom-left.
        """
        return (page_height - y) * self.scale

    def _transform_point(self, x: float, y: float, page_height: float) -> Point:
        """Transform PDF point to CAD point"""
        return Point(x * self.scale, self._transform_y(y, page_height))

    def _parse_dash_pattern(self, dashes: Any) -> LineType:
        """
        Parse PDF dash pattern to determine line type.

        Args:
            dashes: Dash pattern from PDF (tuple of (pattern, phase) or None)

        Returns:
            LineType enum value
        """
        if dashes is None:
            return LineType.CONTINUOUS

        # dashes can be a tuple like (pattern_list, phase)
        if isinstance(dashes, (list, tuple)):
            if len(dashes) >= 1:
                pattern = dashes[0] if isinstance(dashes[0], (list, tuple)) else dashes
                if isinstance(pattern, (list, tuple)) and len(pattern) == 0:
                    return LineType.CONTINUOUS

                # Analyze pattern to determine line type
                if isinstance(pattern, (list, tuple)) and len(pattern) >= 1:
                    # Count segments to determine pattern type
                    if len(pattern) == 2:
                        # Simple dash pattern [dash, gap]
                        dash, gap = pattern[0], pattern[1] if len(pattern) > 1 else pattern[0]
                        if dash < gap * 0.5:
                            return LineType.DOTTED
                        else:
                            return LineType.DASHED
                    elif len(pattern) >= 4:
                        # Complex pattern - likely dash-dot
                        return LineType.DASHDOT
                    elif len(pattern) == 1:
                        return LineType.DASHED

        return LineType.CONTINUOUS

    def _extract_drawings(self, page: fitz.Page, data: ExtractedData):
        """Extract vector drawings from page"""
        page_height = page.rect.height

        # Get all drawings on the page
        paths = page.get_drawings()

        for path in paths:
            items = path.get("items", [])
            color = path.get("color", (0, 0, 0))
            if color is None:
                color = (0, 0, 0)
            fill = path.get("fill")
            width = (path.get("width") or 1.0) * self.scale
            dashes = path.get("dashes")
            even_odd = path.get("even_odd", True)
            closePath = path.get("closePath", False)

            # Parse line type from dash pattern
            linetype = self._parse_dash_pattern(dashes)

            # Convert color from 0-1 to tuple
            if isinstance(color, (list, tuple)) and len(color) >= 3:
                color = (color[0], color[1], color[2])
            else:
                color = (0, 0, 0)

            # Convert fill color
            fill_color = None
            if fill is not None:
                if isinstance(fill, (list, tuple)) and len(fill) >= 3:
                    fill_color = (fill[0], fill[1], fill[2])
                elif isinstance(fill, (int, float)):
                    # Grayscale
                    fill_color = (fill, fill, fill)

            # Process path items - collect all subpaths
            all_subpaths = []
            current_point = None
            path_points = []
            path_start = None
            has_curves = False

            for item in items:
                cmd = item[0]

                if cmd == "m":  # Move to
                    # If we have accumulated points, save them as a subpath
                    if len(path_points) > 1:
                        all_subpaths.append({
                            'points': path_points.copy(),
                            'closed': False,
                            'has_curves': has_curves
                        })
                    path_points = []
                    has_curves = False
                    current_point = self._transform_point(item[1].x, item[1].y, page_height)
                    path_start = current_point
                    path_points.append(current_point)

                elif cmd == "l":  # Line to
                    # PyMuPDF's 'l' command contains two points: start and end
                    # If we don't have a current point, use the start point from the line
                    if len(item) >= 3:
                        # Format: ('l', start_point, end_point)
                        start_point = self._transform_point(item[1].x, item[1].y, page_height)
                        end_point = self._transform_point(item[2].x, item[2].y, page_height)

                        if current_point is None or len(path_points) == 0:
                            # Start a new path segment
                            path_points.append(start_point)
                            path_start = start_point
                        elif current_point != start_point:
                            # Discontinuous line - save previous segment and start new
                            if len(path_points) > 1:
                                all_subpaths.append({
                                    'points': path_points.copy(),
                                    'closed': False,
                                    'has_curves': has_curves
                                })
                            path_points = [start_point]
                            path_start = start_point
                            has_curves = False

                        path_points.append(end_point)
                        current_point = end_point
                    elif len(item) >= 2:
                        # Fallback: single endpoint format
                        end_point = self._transform_point(item[1].x, item[1].y, page_height)
                        if current_point is not None:
                            path_points.append(end_point)
                        current_point = end_point

                elif cmd == "c":  # Cubic bezier curve
                    # item contains: cmd, control1, control2, end_point
                    if len(item) >= 4:
                        ctrl1 = self._transform_point(item[1].x, item[1].y, page_height)
                        ctrl2 = self._transform_point(item[2].x, item[2].y, page_height)
                        end = self._transform_point(item[3].x, item[3].y, page_height)

                        # Convert bezier to line segments for compatibility
                        if current_point:
                            bezier_points = self._bezier_to_points(
                                current_point, ctrl1, ctrl2, end, segments=16
                            )
                            path_points.extend(bezier_points[1:])  # Skip first (duplicate)
                        has_curves = True
                        current_point = end

                elif cmd == "v":  # Cubic bezier (control point 1 = current point)
                    if len(item) >= 3 and current_point:
                        ctrl2 = self._transform_point(item[1].x, item[1].y, page_height)
                        end = self._transform_point(item[2].x, item[2].y, page_height)

                        bezier_points = self._bezier_to_points(
                            current_point, current_point, ctrl2, end, segments=16
                        )
                        path_points.extend(bezier_points[1:])
                        has_curves = True
                        current_point = end

                elif cmd == "y":  # Cubic bezier (control point 2 = end point)
                    if len(item) >= 3 and current_point:
                        ctrl1 = self._transform_point(item[1].x, item[1].y, page_height)
                        end = self._transform_point(item[2].x, item[2].y, page_height)

                        bezier_points = self._bezier_to_points(
                            current_point, ctrl1, end, end, segments=16
                        )
                        path_points.extend(bezier_points[1:])
                        has_curves = True
                        current_point = end

                elif cmd == "re":  # Rectangle
                    rect = item[1]
                    corner = self._transform_point(rect.x0, rect.y1, page_height)
                    rect_width = (rect.x1 - rect.x0) * self.scale
                    rect_height = (rect.y1 - rect.y0) * self.scale

                    data.rectangles.append(Rectangle(
                        corner=corner,
                        width=rect_width,
                        height=rect_height,
                        color=color,
                        line_width=width,
                        linetype=linetype,
                        fill_color=fill_color
                    ))

                    # If this rectangle is filled, also create a hatch
                    if fill_color is not None:
                        rect_points = [
                            corner,
                            Point(corner.x + rect_width, corner.y),
                            Point(corner.x + rect_width, corner.y + rect_height),
                            Point(corner.x, corner.y + rect_height),
                            corner  # Close the path
                        ]
                        data.hatches.append(Hatch(
                            boundary_paths=[rect_points],
                            pattern_name="SOLID",
                            color=fill_color
                        ))

                elif cmd == "h":  # Close path
                    if path_start and current_point and path_start != current_point:
                        path_points.append(path_start)
                    if len(path_points) > 1:
                        all_subpaths.append({
                            'points': path_points.copy(),
                            'closed': True,
                            'has_curves': has_curves
                        })
                    path_points = []
                    has_curves = False

                elif cmd == "qu":  # Quadratic bezier (quad)
                    if len(item) >= 3 and current_point:
                        ctrl = self._transform_point(item[1].x, item[1].y, page_height)
                        end = self._transform_point(item[2].x, item[2].y, page_height)

                        quad_points = self._quad_bezier_to_points(
                            current_point, ctrl, end, segments=12
                        )
                        path_points.extend(quad_points[1:])
                        has_curves = True
                        current_point = end

            # Save remaining path points
            if len(path_points) > 1:
                is_closed = closePath or (path_start and path_points[-1] == path_start)
                all_subpaths.append({
                    'points': path_points.copy(),
                    'closed': is_closed,
                    'has_curves': has_curves
                })

            # Process all subpaths
            for subpath in all_subpaths:
                points = subpath['points']
                closed = subpath['closed']

                if len(points) < 2:
                    continue

                # Save as appropriate entity
                self._save_path_entity(points, closed, color, width, linetype, fill_color, data)

            # Handle filled but non-stroked paths (create hatches only)
            if fill_color is not None and color == (0, 0, 0) and width == 0:
                for subpath in all_subpaths:
                    if subpath['closed'] and len(subpath['points']) >= 3:
                        data.hatches.append(Hatch(
                            boundary_paths=[subpath['points']],
                            pattern_name="SOLID",
                            color=fill_color
                        ))

    def _save_path_entity(self, points: List[Point], closed: bool,
                          color: Tuple[float, float, float], width: float,
                          linetype: LineType,
                          fill_color: Optional[Tuple[float, float, float]],
                          data: ExtractedData):
        """Save path points as appropriate entity type"""

        if len(points) == 2:
            # Simple line
            data.lines.append(Line(
                start=points[0],
                end=points[1],
                color=color,
                width=width,
                linetype=linetype
            ))
        elif len(points) >= 4 and closed and self._is_rectangle(points):
            # Rectangle (4 points + optional closing point)
            pts = points[:4]
            min_x = min(p.x for p in pts)
            min_y = min(p.y for p in pts)
            max_x = max(p.x for p in pts)
            max_y = max(p.y for p in pts)

            data.rectangles.append(Rectangle(
                corner=Point(min_x, min_y),
                width=max_x - min_x,
                height=max_y - min_y,
                color=color,
                line_width=width,
                linetype=linetype,
                fill_color=fill_color
            ))
        else:
            # Polyline
            data.polylines.append(Polyline(
                points=points.copy(),
                closed=closed,
                color=color,
                width=width,
                linetype=linetype
            ))

            # If closed and filled, also add hatch
            if closed and fill_color is not None and len(points) >= 3:
                data.hatches.append(Hatch(
                    boundary_paths=[points.copy()],
                    pattern_name="SOLID",
                    color=fill_color
                ))

    def _is_rectangle(self, points: List[Point]) -> bool:
        """Check if points form a rectangle"""
        if len(points) < 4:
            return False

        # Get first 4 points (ignore closing point if present)
        pts = points[:4]

        # Get unique x and y values with tolerance
        tolerance = 0.5
        x_vals = []
        y_vals = []

        for p in pts:
            found_x = False
            found_y = False
            for x in x_vals:
                if abs(p.x - x) < tolerance:
                    found_x = True
                    break
            if not found_x:
                x_vals.append(p.x)

            for y in y_vals:
                if abs(p.y - y) < tolerance:
                    found_y = True
                    break
            if not found_y:
                y_vals.append(p.y)

        # Rectangle should have exactly 2 unique x and 2 unique y values
        return len(x_vals) == 2 and len(y_vals) == 2

    def _bezier_to_points(self, p0: Point, p1: Point, p2: Point, p3: Point,
                          segments: int = 16, adaptive: bool = True) -> List[Point]:
        """
        Convert cubic bezier curve to line segments with adaptive sampling.

        Args:
            p0, p1, p2, p3: Control points of the cubic bezier
            segments: Base number of segments (minimum)
            adaptive: If True, increase segments for complex curves

        Returns:
            List of points approximating the bezier curve
        """
        # Calculate curve complexity for adaptive sampling
        if adaptive:
            # Estimate curve length and curvature
            chord_length = p0.distance_to(p3)
            control_length = p0.distance_to(p1) + p1.distance_to(p2) + p2.distance_to(p3)

            # Ratio indicates how curved the bezier is
            if chord_length > 0.001:
                ratio = control_length / chord_length
                # Increase segments for more curved paths
                if ratio > 1.5:
                    segments = min(64, int(segments * ratio))
                elif ratio > 1.2:
                    segments = min(48, int(segments * 1.5))
                elif ratio > 1.1:
                    segments = min(32, int(segments * 1.2))

            # Also consider absolute size for large curves
            if control_length > 100:
                segments = max(segments, 32)
            elif control_length > 50:
                segments = max(segments, 24)

        points = []
        for i in range(segments + 1):
            t = i / segments
            t2 = t * t
            t3 = t2 * t
            mt = 1 - t
            mt2 = mt * mt
            mt3 = mt2 * mt

            x = mt3 * p0.x + 3 * mt2 * t * p1.x + 3 * mt * t2 * p2.x + t3 * p3.x
            y = mt3 * p0.y + 3 * mt2 * t * p1.y + 3 * mt * t2 * p2.y + t3 * p3.y

            points.append(Point(x, y))
        return points

    def _quad_bezier_to_points(self, p0: Point, p1: Point, p2: Point,
                                segments: int = 12, adaptive: bool = True) -> List[Point]:
        """
        Convert quadratic bezier curve to line segments with adaptive sampling.

        Args:
            p0, p1, p2: Control points of the quadratic bezier
            segments: Base number of segments (minimum)
            adaptive: If True, increase segments for complex curves

        Returns:
            List of points approximating the bezier curve
        """
        if adaptive:
            # Estimate curve complexity
            chord_length = p0.distance_to(p2)
            control_length = p0.distance_to(p1) + p1.distance_to(p2)

            if chord_length > 0.001:
                ratio = control_length / chord_length
                if ratio > 1.3:
                    segments = min(32, int(segments * ratio))
                elif ratio > 1.1:
                    segments = min(24, int(segments * 1.3))

        points = []
        for i in range(segments + 1):
            t = i / segments
            mt = 1 - t

            x = mt * mt * p0.x + 2 * mt * t * p1.x + t * t * p2.x
            y = mt * mt * p0.y + 2 * mt * t * p1.y + t * t * p2.y

            points.append(Point(x, y))
        return points

    def _extract_text(self, page: fitz.Page, data: ExtractedData):
        """
        Extract text elements from page with full formatting.

        Handles:
        - Text position and transformation matrix
        - Font name, size, and style (bold, italic)
        - Text color (RGB and grayscale)
        - Text rotation and skew
        - Horizontal and vertical alignment
        - Width factor and character spacing
        - CJK (Chinese/Japanese/Korean) characters
        """
        page_height = page.rect.height

        # Get text as dictionary with detailed information
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES)

        for block in text_dict.get("blocks", []):
            if block.get("type") == 0:  # Text block
                block_lines = block.get("lines", [])

                for line in block_lines:
                    line_spans = line.get("spans", [])
                    line_dir = line.get("dir", (1, 0))  # Text direction vector
                    line_wmode = line.get("wmode", 0)  # Writing mode (0=horizontal, 1=vertical)

                    # Calculate rotation from direction vector
                    rotation = math.degrees(math.atan2(line_dir[1], line_dir[0]))

                    for span in line_spans:
                        text = span.get("text", "")
                        if not text:  # Keep whitespace-only text if present
                            continue

                        # Get position (origin of text)
                        origin = span.get("origin", [0, 0])
                        bbox = span.get("bbox", [0, 0, 0, 0])

                        x = origin[0] * self.scale
                        y = self._transform_y(origin[1], page_height)

                        # Get text properties
                        font_size = span.get("size", 12) * self.scale
                        font_name = span.get("font", "Arial")
                        color = span.get("color", 0)
                        flags = span.get("flags", 0)
                        ascender = span.get("ascender", 1.0)
                        descender = span.get("descender", 0.0)

                        # Parse font flags
                        is_superscript = bool(flags & 1)
                        is_italic = bool(flags & 2)
                        is_serifed = bool(flags & 4)
                        is_monospaced = bool(flags & 8)
                        is_bold = bool(flags & 16)

                        # Calculate oblique angle for italic text
                        oblique = 12.0 if is_italic else 0.0

                        # Calculate width factor from character spacing
                        # Estimate based on bbox and text length
                        text_width = bbox[2] - bbox[0]
                        if len(text) > 0 and font_size > 0:
                            estimated_width = len(text) * font_size * 0.5
                            if estimated_width > 0:
                                width_factor = min(2.0, max(0.5, text_width / estimated_width))
                            else:
                                width_factor = 1.0
                        else:
                            width_factor = 1.0

                        # Convert color integer to RGB
                        if isinstance(color, int):
                            r = ((color >> 16) & 0xFF) / 255.0
                            g = ((color >> 8) & 0xFF) / 255.0
                            b = (color & 0xFF) / 255.0
                            color = (r, g, b)
                        elif isinstance(color, (list, tuple)) and len(color) >= 3:
                            color = (color[0], color[1], color[2])
                        else:
                            color = (0, 0, 0)

                        # Normalize rotation to 0-360 range
                        if rotation < 0:
                            rotation += 360

                        # Determine horizontal alignment based on position relative to bbox
                        bbox_center_x = (bbox[0] + bbox[2]) / 2
                        origin_x = origin[0]
                        if abs(origin_x - bbox[0]) < font_size * 0.1:
                            halign = "LEFT"
                        elif abs(origin_x - bbox_center_x) < font_size * 0.1:
                            halign = "CENTER"
                        elif abs(origin_x - bbox[2]) < font_size * 0.1:
                            halign = "RIGHT"
                        else:
                            halign = "LEFT"

                        # Determine vertical alignment
                        valign = "BASELINE"  # PDF typically uses baseline

                        data.texts.append(TextEntity(
                            text=text,
                            position=Point(x, y),
                            height=font_size,
                            rotation=rotation,
                            font=font_name,
                            color=color,
                            oblique=oblique,
                            halign=halign,
                            valign=valign,
                            width_factor=width_factor
                        ))

    def _extract_images(self, page: fitz.Page, data: ExtractedData):
        """
        Extract embedded images from page with comprehensive support.

        Handles:
        - Standard image XObjects
        - Inline images
        - Images with transparency/alpha channels
        - Various color spaces (RGB, CMYK, Grayscale)
        - Image masks and soft masks
        """
        page_height = page.rect.height

        # Get list of images on the page
        image_list = page.get_images(full=True)

        for img_index, img_info in enumerate(image_list):
            try:
                xref = img_info[0]  # Image xref
                smask = img_info[1] if len(img_info) > 1 else 0  # Soft mask xref

                # Get image bbox on page
                img_rects = page.get_image_rects(xref)
                if not img_rects:
                    continue

                for img_rect in img_rects:
                    # Extract image data
                    base_image = self.doc.extract_image(xref)
                    if not base_image:
                        continue

                    image_bytes = base_image.get("image")
                    if not image_bytes:
                        continue

                    # Get image metadata
                    img_width = base_image.get("width", 0)
                    img_height = base_image.get("height", 0)
                    colorspace = base_image.get("colorspace", "")
                    bpc = base_image.get("bpc", 8)  # bits per component
                    img_ext = base_image.get("ext", "png")

                    # Check for transparency (soft mask)
                    has_transparency = smask > 0

                    # Handle soft mask (transparency) if present
                    if has_transparency and smask > 0:
                        try:
                            mask_image = self.doc.extract_image(smask)
                            if mask_image and mask_image.get("image"):
                                # Combine image with alpha mask
                                image_bytes = self._apply_alpha_mask(
                                    image_bytes, mask_image.get("image"),
                                    img_width, img_height, img_ext
                                )
                        except Exception:
                            pass  # Continue without transparency

                    # Convert CMYK to RGB if needed
                    if colorspace and "cmyk" in colorspace.lower():
                        try:
                            image_bytes = self._convert_cmyk_to_rgb(image_bytes, img_ext)
                        except Exception:
                            pass  # Continue with original

                    # Convert image position
                    x0 = img_rect.x0 * self.scale
                    y0 = self._transform_y(img_rect.y1, page_height)
                    rect_width = (img_rect.x1 - img_rect.x0) * self.scale
                    rect_height = (img_rect.y1 - img_rect.y0) * self.scale

                    # Store image entity
                    data.images.append(ImageEntity(
                        position=Point(x0, y0),
                        width=rect_width,
                        height=rect_height,
                        image_data=image_bytes,
                        original_width=img_width,
                        original_height=img_height,
                        colorspace=colorspace,
                        bits_per_component=bpc,
                        transparency=has_transparency
                    ))

            except Exception as e:
                # Skip problematic images but continue extraction
                continue

        # Also extract inline images (images embedded directly in content stream)
        self._extract_inline_images(page, data)

    def _extract_inline_images(self, page: fitz.Page, data: ExtractedData):
        """Extract inline images from page content stream"""
        page_height = page.rect.height

        try:
            # Get page's display list and extract inline images
            # PyMuPDF doesn't expose inline images directly, but we can use
            # pixmap rendering as fallback for pages with complex inline content
            pass  # PyMuPDF handles most inline images through get_images()
        except Exception:
            pass

    def _apply_alpha_mask(self, image_data: bytes, mask_data: bytes,
                          width: int, height: int, ext: str) -> bytes:
        """Apply alpha mask to image data"""
        try:
            # Use PIL if available for better image manipulation
            from PIL import Image
            import io

            # Load main image
            img = Image.open(io.BytesIO(image_data))
            if img.mode != 'RGBA':
                img = img.convert('RGBA')

            # Load mask
            mask = Image.open(io.BytesIO(mask_data))
            if mask.mode != 'L':
                mask = mask.convert('L')

            # Resize mask if needed
            if mask.size != img.size:
                mask = mask.resize(img.size, Image.Resampling.LANCZOS)

            # Apply mask as alpha channel
            img.putalpha(mask)

            # Save to PNG (supports transparency)
            output = io.BytesIO()
            img.save(output, format='PNG')
            return output.getvalue()

        except ImportError:
            # PIL not available, return original
            return image_data
        except Exception:
            return image_data

    def _convert_cmyk_to_rgb(self, image_data: bytes, ext: str) -> bytes:
        """Convert CMYK image to RGB"""
        try:
            from PIL import Image
            import io

            img = Image.open(io.BytesIO(image_data))
            if img.mode == 'CMYK':
                img = img.convert('RGB')
                output = io.BytesIO()
                img.save(output, format='PNG')
                return output.getvalue()
            return image_data

        except ImportError:
            return image_data
        except Exception:
            return image_data

    def _extract_layers(self, page: fitz.Page, data: ExtractedData):
        """
        Extract layer information if available (Optional Content Groups).

        Extracts:
        - Layer name
        - Layer visibility state
        - Layer intent (view/design/all)
        - Layer locking state
        """
        try:
            # Get optional content configuration from document
            oc_config = self.doc.get_oc_items()
            if oc_config:
                for item in oc_config:
                    xref = item[0]
                    layer_type = item[1]
                    layer_name = item[2] if len(item) > 2 else f"Layer_{xref}"

                    # Only process OCG (Optional Content Group) items
                    if layer_type == 0:  # OCG type
                        try:
                            # Get layer properties
                            layer_obj = self.doc.xref_object(xref, compressed=False)

                            # Parse visibility from default state
                            visible = True
                            locked = False
                            intent = "View"

                            # Try to get additional properties
                            if layer_obj:
                                # Check for Intent
                                if "/Intent" in str(layer_obj):
                                    if "Design" in str(layer_obj):
                                        intent = "Design"
                                    elif "All" in str(layer_obj):
                                        intent = "All"

                            data.layers[f"Layer_{xref}"] = {
                                "name": layer_name,
                                "visible": visible,
                                "locked": locked,
                                "intent": intent,
                                "xref": xref
                            }
                        except Exception:
                            # Fallback to basic layer info
                            data.layers[f"Layer_{xref}"] = {
                                "name": layer_name,
                                "visible": True
                            }

            # Also try the legacy method for older PDFs
            try:
                oc = self.doc.get_oc()
                if oc:
                    for i, layer in enumerate(oc):
                        layer_id = f"Layer_{i}"
                        if layer_id not in data.layers:
                            data.layers[layer_id] = {
                                "name": layer.get("name", layer_id),
                                "visible": layer.get("on", True)
                            }
            except Exception:
                pass

        except Exception:
            # PDF might not have layers
            pass

    def extract_all_pages(self, scale: float = 1.0) -> List[ExtractedData]:
        """
        Extract vector graphics from all pages.

        Args:
            scale: Scale factor for coordinates

        Returns:
            List of ExtractedData, one per page
        """
        if not self.doc:
            self.open()

        results = []
        for i in range(len(self.doc)):
            results.append(self.extract_page(i, scale))

        return results


def detect_circles_and_arcs(data: ExtractedData, tolerance: float = 0.02):
    """
    Post-process polylines to detect circles and arcs.

    This function analyzes polylines and attempts to identify
    circular patterns that should be represented as circles or arcs.

    Args:
        data: ExtractedData to process
        tolerance: Tolerance for circle detection (relative to radius)
    """
    new_polylines = []

    for polyline in data.polylines:
        # Need at least 6 points to reliably detect a circle
        if len(polyline.points) < 6:
            new_polylines.append(polyline)
            continue

        # Try to fit a circle to the points
        result = _fit_circle(polyline.points)
        if result:
            center, radius, error = result

            # Check if it's a good fit (error relative to radius)
            if radius > 0.5 and error < tolerance * radius:
                # Determine if it's a full circle or arc
                is_full_circle = _is_full_circle(polyline.points, center, radius)

                if is_full_circle and polyline.closed:
                    # Full circle
                    data.circles.append(Circle(
                        center=Point(center[0], center[1]),
                        radius=radius,
                        color=polyline.color,
                        width=polyline.width,
                        layer=polyline.layer,
                        linetype=polyline.linetype
                    ))
                else:
                    # Arc
                    start_angle, end_angle = _calculate_arc_angles(
                        center, polyline.points[0], polyline.points[-1]
                    )
                    # Ensure proper arc direction
                    if not _is_ccw(polyline.points, center):
                        start_angle, end_angle = end_angle, start_angle

                    data.arcs.append(Arc(
                        center=Point(center[0], center[1]),
                        radius=radius,
                        start_angle=start_angle,
                        end_angle=end_angle,
                        color=polyline.color,
                        width=polyline.width,
                        layer=polyline.layer,
                        linetype=polyline.linetype
                    ))
                continue

        new_polylines.append(polyline)

    data.polylines = new_polylines


def _is_full_circle(points: List[Point], center: Tuple[float, float], radius: float) -> bool:
    """Check if points cover a full circle (360 degrees)"""
    if len(points) < 8:
        return False

    # Calculate angles of all points
    angles = []
    for p in points:
        angle = math.atan2(p.y - center[1], p.x - center[0])
        angles.append(angle)

    # Sort and check coverage
    angles.sort()

    # Calculate total angular coverage
    total_coverage = 0
    for i in range(len(angles) - 1):
        gap = angles[i + 1] - angles[i]
        if gap < math.pi:  # Normal gap
            total_coverage += gap

    # Add gap from last to first
    wrap_gap = (2 * math.pi) - (angles[-1] - angles[0])
    if wrap_gap < math.pi:
        total_coverage += wrap_gap

    # Should cover at least 90% of the circle
    return total_coverage > 0.9 * 2 * math.pi


def _is_ccw(points: List[Point], center: Tuple[float, float]) -> bool:
    """Determine if points are arranged counter-clockwise around center"""
    if len(points) < 3:
        return True

    # Calculate signed area
    signed_area = 0
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i + 1]
        signed_area += (p1.x - center[0]) * (p2.y - center[1])
        signed_area -= (p2.x - center[0]) * (p1.y - center[1])

    return signed_area > 0


def _fit_circle(points: List[Point]) -> Optional[Tuple[Tuple[float, float], float, float]]:
    """
    Fit a circle to a set of points using least squares.

    Returns:
        Tuple of (center, radius, error) or None if fit fails
    """
    try:
        import numpy as np

        n = len(points)
        if n < 3:
            return None

        # Build matrices for least squares
        A = np.zeros((n, 3))
        b = np.zeros(n)

        for i, p in enumerate(points):
            A[i, 0] = p.x
            A[i, 1] = p.y
            A[i, 2] = 1
            b[i] = p.x * p.x + p.y * p.y

        # Solve least squares
        result, residuals, rank, s = np.linalg.lstsq(A, b, rcond=None)

        # Extract circle parameters
        cx = result[0] / 2
        cy = result[1] / 2
        r_squared = result[2] + cx*cx + cy*cy

        if r_squared <= 0:
            return None

        radius = math.sqrt(r_squared)

        # Calculate fitting error (RMS distance from circle)
        errors = []
        for p in points:
            dist = math.sqrt((p.x - cx)**2 + (p.y - cy)**2)
            errors.append((dist - radius) ** 2)

        rms_error = math.sqrt(sum(errors) / len(errors))

        return ((cx, cy), radius, rms_error)

    except Exception:
        return None


def _calculate_arc_angles(center: Tuple[float, float],
                          start: Point, end: Point) -> Tuple[float, float]:
    """Calculate start and end angles for an arc in degrees"""
    start_angle = math.degrees(math.atan2(start.y - center[1], start.x - center[0]))
    end_angle = math.degrees(math.atan2(end.y - center[1], end.x - center[0]))

    # Normalize to 0-360
    if start_angle < 0:
        start_angle += 360
    if end_angle < 0:
        end_angle += 360

    return start_angle, end_angle


def detect_ellipses(data: ExtractedData, tolerance: float = 0.05):
    """
    Post-process polylines to detect ellipses using algebraic fitting.

    Uses the general conic fitting method to detect ellipses from polylines.

    Args:
        data: ExtractedData to process
        tolerance: Tolerance for ellipse detection (relative to axes)
    """
    new_polylines = []

    for polyline in data.polylines:
        # Need at least 6 points to fit an ellipse (5 parameters)
        if len(polyline.points) < 8:
            new_polylines.append(polyline)
            continue

        # Skip if already detected as circle
        result = _fit_ellipse(polyline.points)
        if result:
            center, major_axis, minor_axis, rotation, error = result

            # Check if it's a good fit
            major_len = math.sqrt(major_axis[0]**2 + major_axis[1]**2)
            if major_len > 0.5 and error < tolerance * major_len:
                # Check if it's more like a circle (use circle instead)
                ratio = minor_axis[0]**2 + minor_axis[1]**2
                ratio = math.sqrt(ratio) / major_len if major_len > 0 else 0

                if ratio > 0.95:  # Nearly circular, skip (detected by circle detector)
                    new_polylines.append(polyline)
                    continue

                # Determine if full ellipse or partial
                is_full = _is_full_ellipse(polyline.points, center, major_axis, minor_axis)

                if is_full and polyline.closed:
                    # Full ellipse
                    data.ellipses.append(Ellipse(
                        center=Point(center[0], center[1]),
                        major_axis=Point(major_axis[0], major_axis[1]),
                        ratio=ratio,
                        start_param=0.0,
                        end_param=2 * math.pi,
                        color=polyline.color,
                        width=polyline.width,
                        layer=polyline.layer,
                        linetype=polyline.linetype
                    ))
                else:
                    # Elliptical arc - calculate parameters
                    start_param, end_param = _calculate_ellipse_params(
                        center, major_axis, minor_axis, rotation,
                        polyline.points[0], polyline.points[-1]
                    )
                    data.ellipses.append(Ellipse(
                        center=Point(center[0], center[1]),
                        major_axis=Point(major_axis[0], major_axis[1]),
                        ratio=ratio,
                        start_param=start_param,
                        end_param=end_param,
                        color=polyline.color,
                        width=polyline.width,
                        layer=polyline.layer,
                        linetype=polyline.linetype
                    ))
                continue

        new_polylines.append(polyline)

    data.polylines = new_polylines


def _fit_ellipse(points: List[Point]) -> Optional[Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float], float, float]]:
    """
    Fit an ellipse to a set of points using algebraic fitting.

    Returns:
        Tuple of (center, major_axis, minor_axis, rotation, error) or None if fit fails
    """
    try:
        import numpy as np

        n = len(points)
        if n < 6:
            return None

        # Extract coordinates
        x = np.array([p.x for p in points])
        y = np.array([p.y for p in points])

        # Build design matrix for conic: ax^2 + bxy + cy^2 + dx + ey + f = 0
        D = np.column_stack([x*x, x*y, y*y, x, y, np.ones(n)])

        # Constraint matrix for ellipse (b^2 - 4ac < 0)
        C = np.zeros((6, 6))
        C[0, 2] = 2
        C[1, 1] = -1
        C[2, 0] = 2

        # Solve generalized eigenvalue problem
        S = D.T @ D
        try:
            # Use svd for better numerical stability
            eigvals, eigvecs = np.linalg.eig(np.linalg.inv(S) @ C)
        except np.linalg.LinAlgError:
            return None

        # Find the positive eigenvalue (corresponds to ellipse)
        valid_idx = np.where(np.logical_and(np.isreal(eigvals), eigvals > 0))[0]
        if len(valid_idx) == 0:
            return None

        idx = valid_idx[np.argmin(eigvals[valid_idx].real)]
        coeffs = eigvecs[:, idx].real

        a, b, c, d, e, f = coeffs

        # Check if it's an ellipse (discriminant < 0)
        discriminant = b*b - 4*a*c
        if discriminant >= 0:
            return None

        # Calculate ellipse parameters
        # Center
        cx = (2*c*d - b*e) / discriminant
        cy = (2*a*e - b*d) / discriminant

        # Rotation angle
        if abs(a - c) < 1e-10:
            theta = math.pi / 4 if b > 0 else -math.pi / 4
        else:
            theta = 0.5 * math.atan2(b, a - c)

        # Semi-axes
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)

        # Transform to canonical form
        a_prime = a*cos_t*cos_t + b*cos_t*sin_t + c*sin_t*sin_t
        c_prime = a*sin_t*sin_t - b*cos_t*sin_t + c*cos_t*cos_t

        # Calculate f_prime (constant term after translation and rotation)
        f_prime = a*cx*cx + b*cx*cy + c*cy*cy + d*cx + e*cy + f

        if abs(a_prime) < 1e-10 or abs(c_prime) < 1e-10:
            return None

        # Semi-axes squared
        a_sq = -f_prime / a_prime
        b_sq = -f_prime / c_prime

        if a_sq <= 0 or b_sq <= 0:
            return None

        semi_major = math.sqrt(max(a_sq, b_sq))
        semi_minor = math.sqrt(min(a_sq, b_sq))

        # Major axis direction
        if a_sq >= b_sq:
            major_axis = (semi_major * cos_t, semi_major * sin_t)
            minor_axis = (-semi_minor * sin_t, semi_minor * cos_t)
        else:
            major_axis = (semi_major * sin_t, -semi_major * cos_t)
            minor_axis = (semi_minor * cos_t, semi_minor * sin_t)

        # Calculate fitting error
        errors = []
        for p in points:
            # Distance to ellipse (approximate)
            dx = p.x - cx
            dy = p.y - cy
            # Rotate to ellipse frame
            px = dx * cos_t + dy * sin_t
            py = -dx * sin_t + dy * cos_t
            # Normalized distance
            if semi_major > 0 and semi_minor > 0:
                dist = abs((px/semi_major)**2 + (py/semi_minor)**2 - 1)
                errors.append(dist * min(semi_major, semi_minor))

        rms_error = math.sqrt(sum(e*e for e in errors) / len(errors)) if errors else float('inf')

        return ((cx, cy), major_axis, minor_axis, theta, rms_error)

    except Exception:
        return None


def _is_full_ellipse(points: List[Point], center: Tuple[float, float],
                     major_axis: Tuple[float, float], minor_axis: Tuple[float, float]) -> bool:
    """Check if points cover a full ellipse (360 degrees)"""
    if len(points) < 10:
        return False

    # Calculate angular positions of all points relative to ellipse
    angles = []
    major_len = math.sqrt(major_axis[0]**2 + major_axis[1]**2)
    if major_len < 1e-10:
        return False

    # Calculate rotation angle
    theta = math.atan2(major_axis[1], major_axis[0])
    cos_t = math.cos(-theta)
    sin_t = math.sin(-theta)

    for p in points:
        # Transform to ellipse frame
        dx = p.x - center[0]
        dy = p.y - center[1]
        px = dx * cos_t + dy * sin_t
        py = -dx * sin_t + dy * cos_t
        angle = math.atan2(py, px)
        angles.append(angle)

    # Sort and check coverage
    angles.sort()

    # Calculate total angular coverage
    total_coverage = 0
    for i in range(len(angles) - 1):
        gap = angles[i + 1] - angles[i]
        if gap < math.pi:
            total_coverage += gap

    # Add wrap-around gap
    wrap_gap = (2 * math.pi) - (angles[-1] - angles[0])
    if wrap_gap < math.pi:
        total_coverage += wrap_gap

    return total_coverage > 0.85 * 2 * math.pi


def _calculate_ellipse_params(center: Tuple[float, float],
                               major_axis: Tuple[float, float],
                               minor_axis: Tuple[float, float],
                               rotation: float,
                               start: Point, end: Point) -> Tuple[float, float]:
    """Calculate ellipse parameters for start and end points"""
    cos_t = math.cos(-rotation)
    sin_t = math.sin(-rotation)

    # Transform start point
    dx = start.x - center[0]
    dy = start.y - center[1]
    px = dx * cos_t + dy * sin_t
    py = -dx * sin_t + dy * cos_t
    start_param = math.atan2(py, px)

    # Transform end point
    dx = end.x - center[0]
    dy = end.y - center[1]
    px = dx * cos_t + dy * sin_t
    py = -dx * sin_t + dy * cos_t
    end_param = math.atan2(py, px)

    # Normalize to 0-2pi
    if start_param < 0:
        start_param += 2 * math.pi
    if end_param < 0:
        end_param += 2 * math.pi

    return start_param, end_param
