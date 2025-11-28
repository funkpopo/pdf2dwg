"""
DWG Converter Module

Converts DXF files to DWG format using ODA File Converter.
The ODA File Converter is a free tool from Open Design Alliance.
"""

import os
import subprocess
import shutil
import tempfile
import platform
from pathlib import Path
from typing import Optional, List, Tuple
from enum import Enum


class DWGVersion(Enum):
    """Supported DWG versions for output"""
    ACAD9 = "ACAD9"
    ACAD10 = "ACAD10"
    ACAD12 = "ACAD12"
    ACAD13 = "ACAD13"
    ACAD14 = "ACAD14"
    ACAD2000 = "ACAD2000"
    ACAD2004 = "ACAD2004"
    ACAD2007 = "ACAD2007"
    ACAD2010 = "ACAD2010"
    ACAD2013 = "ACAD2013"
    ACAD2018 = "ACAD2018"


class DWGConverter:
    """
    Convert DXF files to DWG format using ODA File Converter.

    The ODA File Converter must be installed separately:
    - Download from: https://www.opendesign.com/guestfiles/oda_file_converter
    - Available for Windows, Linux, and macOS
    """

    # Default installation paths for ODA File Converter
    DEFAULT_PATHS = {
        "Windows": [
            r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe",
            r"C:\Program Files (x86)\ODA\ODAFileConverter\ODAFileConverter.exe",
            r"C:\Program Files\ODA\ODAFileConverter 25.12.0\ODAFileConverter.exe",
            r"C:\Program Files (x86)\ODA\ODAFileConverter 25.12.0\ODAFileConverter.exe",
        ],
        "Linux": [
            "/usr/bin/ODAFileConverter",
            "/usr/local/bin/ODAFileConverter",
            "/opt/ODAFileConverter/ODAFileConverter",
        ],
        "Darwin": [  # macOS
            "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter",
            "/usr/local/bin/ODAFileConverter",
        ]
    }

    def __init__(self, converter_path: Optional[str] = None):
        """
        Initialize DWG converter.

        Args:
            converter_path: Path to ODA File Converter executable.
                          If None, will try to find it automatically.
        """
        self.converter_path = converter_path or self._find_converter()

    def _find_converter(self) -> Optional[str]:
        """
        Find ODA File Converter on the system.

        Returns:
            Path to converter executable or None if not found
        """
        system = platform.system()

        # Check default paths
        paths = self.DEFAULT_PATHS.get(system, [])
        for path in paths:
            if os.path.isfile(path):
                return path

        # Try to find in PATH
        exe_name = "ODAFileConverter"
        if system == "Windows":
            exe_name += ".exe"

        found = shutil.which(exe_name)
        if found:
            return found

        # Check environment variable
        env_path = os.environ.get("ODA_FILE_CONVERTER")
        if env_path and os.path.isfile(env_path):
            return env_path

        return None

    def is_available(self) -> bool:
        """Check if ODA File Converter is available"""
        return self.converter_path is not None and os.path.isfile(self.converter_path)

    def convert(self, input_path: str, output_path: str,
                version: DWGVersion = DWGVersion.ACAD2010,
                audit: bool = True) -> Tuple[bool, str]:
        """
        Convert a single DXF file to DWG.

        Args:
            input_path: Path to input DXF file
            output_path: Path for output DWG file
            version: Target DWG version
            audit: Whether to run audit on the file

        Returns:
            Tuple of (success, message)
        """
        if not self.is_available():
            return False, self._get_install_instructions()

        input_path = os.path.abspath(input_path)
        output_path = os.path.abspath(output_path)

        if not os.path.isfile(input_path):
            return False, f"Input file not found: {input_path}"

        # ODA File Converter works with directories
        # Create temp directory structure
        with tempfile.TemporaryDirectory() as temp_dir:
            input_dir = os.path.join(temp_dir, "input")
            output_dir = os.path.join(temp_dir, "output")
            os.makedirs(input_dir)
            os.makedirs(output_dir)

            # Copy input file
            input_filename = os.path.basename(input_path)
            temp_input = os.path.join(input_dir, input_filename)
            shutil.copy2(input_path, temp_input)

            # Build command
            # ODAFileConverter "input_folder" "output_folder" version type recurse audit
            cmd = [
                self.converter_path,
                input_dir,
                output_dir,
                version.value,
                "DWG",
                "0",  # Don't recurse subdirectories
                "1" if audit else "0"
            ]

            try:
                # Run converter
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minute timeout
                )

                # Check for output file
                output_filename = os.path.splitext(input_filename)[0] + ".dwg"
                temp_output = os.path.join(output_dir, output_filename)

                if os.path.isfile(temp_output):
                    # Ensure output directory exists
                    os.makedirs(os.path.dirname(output_path), exist_ok=True)
                    shutil.copy2(temp_output, output_path)
                    return True, f"Successfully converted to {output_path}"
                else:
                    error_msg = result.stderr or result.stdout or "Unknown error"
                    return False, f"Conversion failed: {error_msg}"

            except subprocess.TimeoutExpired:
                return False, "Conversion timed out after 5 minutes"
            except Exception as e:
                return False, f"Conversion error: {str(e)}"

    def convert_batch(self, input_dir: str, output_dir: str,
                      version: DWGVersion = DWGVersion.ACAD2010,
                      recursive: bool = False,
                      audit: bool = True) -> Tuple[bool, str]:
        """
        Convert all DXF files in a directory to DWG.

        Args:
            input_dir: Directory containing DXF files
            output_dir: Directory for output DWG files
            version: Target DWG version
            recursive: Process subdirectories
            audit: Whether to run audit on files

        Returns:
            Tuple of (success, message)
        """
        if not self.is_available():
            return False, self._get_install_instructions()

        input_dir = os.path.abspath(input_dir)
        output_dir = os.path.abspath(output_dir)

        if not os.path.isdir(input_dir):
            return False, f"Input directory not found: {input_dir}"

        os.makedirs(output_dir, exist_ok=True)

        cmd = [
            self.converter_path,
            input_dir,
            output_dir,
            version.value,
            "DWG",
            "1" if recursive else "0",
            "1" if audit else "0"
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout for batch
            )

            # Count output files
            dwg_count = sum(1 for f in os.listdir(output_dir) if f.endswith('.dwg'))

            if dwg_count > 0:
                return True, f"Converted {dwg_count} file(s) to {output_dir}"
            else:
                error_msg = result.stderr or result.stdout or "No files converted"
                return False, f"Batch conversion failed: {error_msg}"

        except subprocess.TimeoutExpired:
            return False, "Batch conversion timed out after 1 hour"
        except Exception as e:
            return False, f"Batch conversion error: {str(e)}"

    def _get_install_instructions(self) -> str:
        """Get installation instructions for ODA File Converter"""
        system = platform.system()

        msg = """
ODA File Converter is required but not found.

Please download and install from:
https://www.opendesign.com/guestfiles/oda_file_converter

"""
        if system == "Windows":
            msg += """Windows installation:
1. Download ODAFileConverter_25.12.0.exe
2. Run the installer
3. Default path: C:\\Program Files\\ODA\\ODAFileConverter\\

Alternatively, set the ODA_FILE_CONVERTER environment variable to the path.
"""
        elif system == "Linux":
            msg += """Linux installation:
1. Download ODAFileConverter_QT5_lnxX64_8.3dll_25.12.deb (or .rpm)
2. Install: sudo dpkg -i ODAFileConverter*.deb
3. The executable should be at /usr/bin/ODAFileConverter

Alternatively, set the ODA_FILE_CONVERTER environment variable to the path.
"""
        elif system == "Darwin":
            msg += """macOS installation:
1. Download ODAFileConverter_25.12.0.dmg
2. Mount and drag to Applications
3. Path: /Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter

Alternatively, set the ODA_FILE_CONVERTER environment variable to the path.
"""

        return msg


def convert_dxf_to_dwg(dxf_path: str, dwg_path: Optional[str] = None,
                       version: str = "ACAD2010",
                       converter_path: Optional[str] = None) -> Tuple[bool, str]:
    """
    Convenience function to convert DXF to DWG.

    Args:
        dxf_path: Path to input DXF file
        dwg_path: Path for output DWG file (default: same name with .dwg extension)
        version: Target DWG version (ACAD2000, ACAD2004, ACAD2007, ACAD2010, ACAD2013, ACAD2018)
        converter_path: Optional path to ODA File Converter

    Returns:
        Tuple of (success, message)
    """
    if dwg_path is None:
        dwg_path = os.path.splitext(dxf_path)[0] + ".dwg"

    try:
        dwg_version = DWGVersion[version]
    except KeyError:
        return False, f"Invalid version: {version}. Valid options: {[v.name for v in DWGVersion]}"

    converter = DWGConverter(converter_path)
    return converter.convert(dxf_path, dwg_path, dwg_version)


def try_ezdxf_odafc(dxf_path: str, dwg_path: str,
                    version: str = "R2010") -> Tuple[bool, str]:
    """
    Try to convert using ezdxf's ODA File Converter addon.

    This is an alternative method that uses ezdxf's built-in integration.

    Args:
        dxf_path: Path to input DXF file
        dwg_path: Path for output DWG file
        version: Target DWG version (R2010, R2013, R2018, etc.)

    Returns:
        Tuple of (success, message)
    """
    try:
        import ezdxf
        from ezdxf.addons import odafc

        # Load DXF
        doc = ezdxf.readfile(dxf_path)

        # Export as DWG
        odafc.export_dwg(doc, dwg_path, version=version)

        if os.path.isfile(dwg_path):
            return True, f"Successfully converted to {dwg_path}"
        else:
            return False, "Conversion completed but output file not found"

    except ImportError:
        return False, "ezdxf odafc addon not available"
    except Exception as e:
        return False, f"ezdxf conversion error: {str(e)}"
