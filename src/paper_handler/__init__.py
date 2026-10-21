"""paper-handler — scaffold, render and manage academic papers with Quarto."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("paper-handler")
except PackageNotFoundError:  # running from a bare source checkout
    __version__ = "0.1.0"

__all__ = ["__version__"]
