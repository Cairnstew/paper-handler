"""MCP (Model Context Protocol) server for paper-handler.

Entry points:

* ``paper-handler mcp`` — run over stdio from the CLI package.
* ``paper-handler-mcp`` — the same server as a standalone console script.

The server is deliberately dependency-free (stdlib JSON-RPC over stdio) and
every tool returns compact JSON, so an agent can write a paper section by
section without ever loading the whole document into its context.
"""

from __future__ import annotations

__all__ = ["server"]
