"""Importing this package registers every tool in the registry.

Add a module here (and decorate its handlers with ``@tool``) to extend the
server; ``server.py`` never needs to change.
"""

from __future__ import annotations

from paper_handler.mcp.tools import build, corpus, quality, research, writing  # noqa: F401,E402

__all__ = ["build", "corpus", "quality", "research", "writing"]
