from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="pdf2dwg",
    version="1.2.0",
    author="funkpopo",
    author_email="s767609509@gmail.com",
    description="Convert PDF files to AutoCAD-compatible DWG/DXF format",
    long_description="README.md",
    long_description_content_type="text/markdown",
    url="https://github.com/funkpopo/pdf2dwg",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.12",
        "Topic :: Multimedia :: Graphics :: Graphics Conversion",
    ],
    python_requires=">=3.8",
    install_requires=[
        "PyMuPDF>=1.23.0",
        "ezdxf>=1.1.0",
        "click>=8.1.0",
        "tqdm>=4.65.0",
        "numpy>=1.24.0",
        "Pillow>=9.0.0",
        "scipy",
    ],
    entry_points={
        "console_scripts": [
            "pdf2dwg=pdf2dwg.cli:main",
        ],
    },
    keywords="pdf dwg dxf autocad cad converter vector graphics",
)
