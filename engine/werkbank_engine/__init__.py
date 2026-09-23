"""Werkbank local engine (DESIGN.md §6)."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("werkbank-engine")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0+unknown"
