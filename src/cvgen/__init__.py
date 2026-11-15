"""Build, verify and tailor CVs from Markdown."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("cvgen")
except PackageNotFoundError:
    __version__ = "0.1.0"
