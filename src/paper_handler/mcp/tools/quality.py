"""Quality tools: lint and bibliography checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from paper_handler import bib as bib_mod
from paper_handler import documents
from paper_handler.mcp.context import (
    ToolError,
    bib_paths,
    int_arg,
    paper_or_single,
    rel,
    session,
    str_arg,
    text_of,
)
from paper_handler.mcp.registry import schema, tool


@tool(
    "paper_lint",
    "Structural and style diagnostics: placeholders, heading hierarchy, missing sections, "
    "long paragraphs/sentences, abstract length, undefined citations, readability. "
    "Returns at most `max_issues`; the counts are always complete.",
    schema(
        {
            "name": {"type": "string"},
            "max_issues": {"type": "integer", "default": 15},
        }
    ),
)
def paper_lint(args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    item = paper_or_single(str_arg(args, "name") or None, current)
    report = documents.lint(text_of(item), bib_paths(item))
    limit = int_arg(args, "max_issues", 15) or 15
    issues = report["issues"]
    report["issues"] = issues[:limit]
    report["omitted"] = max(0, len(issues) - limit)
    report["paper"] = item.name
    return report


@tool(
    "paper_bib_check",
    "Check references.bib for structural problems (brace balance, duplicate or empty keys).",
    schema({"name": {"type": "string"}, "file": {"type": "string"}}),
)
def paper_bib_check(args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    explicit = str_arg(args, "file")
    if explicit:
        targets = [Path(explicit).expanduser()]
    else:
        item = paper_or_single(str_arg(args, "name") or None, current)
        targets = bib_paths(item) or [item.dir / "references.bib"]

    files: list[dict[str, Any]] = []
    problems: list[str] = []
    entries = 0
    for target in targets:
        if not target.is_file():
            files.append(
                {"file": rel(target, current), "entries": 0, "problems": ["no such file"]}
            )
            problems.append(f"{rel(target, current)}: no such file")
            continue
        found = bib_mod.check(target)
        count = len(bib_mod.keys(target))
        entries += count
        files.append(
            {
                "file": rel(target, current),
                "entries": count,
                "problems": found,
            }
        )
        problems.extend(f"{rel(target, current)}: {problem}" for problem in found)
    return {
        "ok": not problems,
        "entries": entries,
        "files": files,
        "problems": problems,
    }


@tool(
    "paper_bib_init",
    "Create a starter references.bib in a paper.",
    schema({"name": {"type": "string"}, "force": {"type": "boolean", "default": False}}),
)
def paper_bib_init(args: dict[str, Any]) -> dict[str, Any]:
    from paper_handler.mcp.context import bool_arg

    current = session()
    item = paper_or_single(str_arg(args, "name") or None, current)
    target = item.dir / "references.bib"
    try:
        created = bib_mod.init(target, overwrite=bool_arg(args, "force"))
    except bib_mod.BibError as exc:
        raise ToolError(str(exc)) from exc
    return {
        "ok": True,
        "file": rel(created, current),
        "next": "Add real entries, then paper_bib_check.",
    }


__all__ = ["paper_bib_check", "paper_bib_init", "paper_lint"]
