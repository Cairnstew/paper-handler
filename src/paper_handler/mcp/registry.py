"""A tiny tool registry.

Adding an MCP tool is one decorated function: the decorator records its name,
description, JSON Schema and handler, and the server discovers everything from
:func:`tool_specs`.  There is no central switch statement to edit.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: A handler receives the tool arguments and returns JSON-serialisable data.
Handler = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler


_TOOLS: dict[str, ToolSpec] = {}


def tool(
    name: str,
    description: str,
    input_schema: dict[str, Any] | None = None,
) -> Callable[[Handler], Handler]:
    """Register a handler as an MCP tool."""

    def register(handler: Handler) -> Handler:
        if name in _TOOLS:
            raise RuntimeError(f"duplicate MCP tool {name!r}")
        _TOOLS[name] = ToolSpec(
            name=name,
            description=description,
            input_schema=input_schema or {"type": "object", "properties": {}},
            handler=handler,
        )
        return handler

    return register


def tool_specs() -> list[ToolSpec]:
    return sorted(_TOOLS.values(), key=lambda spec: spec.name)


def get_tool(name: str) -> ToolSpec:
    try:
        return _TOOLS[name]
    except KeyError as exc:
        raise KeyError(f"unknown tool {name!r}") from exc


def schema(
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    *,
    additional: bool = False,
) -> dict[str, Any]:
    """Build a JSON Schema object without repeating the boilerplate."""
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": additional,
    }
