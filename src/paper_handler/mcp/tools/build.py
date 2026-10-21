"""Render and front-matter tools.

Quarto's output is captured, never inherited: the MCP server's stdout is the
protocol stream, and a stray banner would corrupt it.
"""

from __future__ import annotations

import time
from typing import Any

from paper_handler import project
from paper_handler.mcp.context import (
    ToolError,
    bool_arg,
    paper_or_single,
    rel,
    session,
    str_arg,
)
from paper_handler.mcp.registry import schema, tool
from paper_handler.render import RenderError, render_captured
from paper_handler.toolchain import ToolchainError, render_hint


def _tail(text: str, limit: int = 2000) -> str:
    text = text.strip()
    return text[-limit:] if len(text) > limit else text


@tool(
    "paper_render",
    "Render one paper (or the whole corpus with all=true) to PDF. Returns the output path, "
    "size and, on failure, a short stderr tail — not the full Quarto log.",
    schema(
        {
            "name": {"type": "string"},
            "all": {"type": "boolean", "default": False},
            "engine": {"type": "string", "enum": ["typst", "latex", "both"]},
            "keep_going": {"type": "boolean", "default": False},
        }
    ),
)
def paper_render(args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    engine = str_arg(args, "engine") or current.config.engine
    all_papers = bool_arg(args, "all")
    requested = str_arg(args, "name")
    if all_papers and requested:
        raise ToolError("pass either name or all=true, not both")

    if not all_papers:
        item = paper_or_single(requested or None, current)
        started = time.monotonic()
        try:
            status, stdout, stderr = render_captured(item, engine=engine)
        except (RenderError, ToolchainError) as exc:
            raise ToolError(str(exc)) from exc
        result: dict[str, Any] = {
            "ok": status == 0,
            "paper": item.name,
            "engine": engine,
            "seconds": round(time.monotonic() - started, 2),
            "pdf": rel(item.pdf, current),
            "bytes": item.pdf.stat().st_size if item.pdf.is_file() else 0,
        }
        if status != 0:
            output = stderr or stdout
            result["stderr_tail"] = _tail(output)
            hint = render_hint(output)
            if hint:
                result["hint"] = hint
        return result

    papers = project.discover(current.corpus)
    if not papers:
        raise ToolError(f"no papers found in {current.corpus}")
    rendered: list[str] = []
    failed: list[dict[str, Any]] = []
    started = time.monotonic()
    for item in papers:
        try:
            status, stdout, stderr = render_captured(item, engine=engine)
        except (RenderError, ToolchainError) as exc:
            failed.append({"paper": item.name, "error": str(exc)})
            if not bool_arg(args, "keep_going"):
                break
            continue
        if status == 0:
            rendered.append(item.name)
        else:
            output = stderr or stdout
            entry: dict[str, Any] = {"paper": item.name, "stderr_tail": _tail(output, 800)}
            hint = render_hint(output)
            if hint:
                entry["hint"] = hint
            failed.append(entry)
            if not bool_arg(args, "keep_going"):
                break
    return {
        "ok": not failed,
        "engine": engine,
        "rendered": rendered,
        "failed": failed,
        "seconds": round(time.monotonic() - started, 2),
    }


__all__ = ["paper_render"]
