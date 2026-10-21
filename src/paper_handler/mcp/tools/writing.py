"""Writing tools: context packs, outlines, section reads and section edits.

These are the low-token path: an agent asks for an outline, fetches one
section, replaces that section, and gets a receipt.  The full document never
has to cross the wire.
"""

from __future__ import annotations

from typing import Any

from paper_handler import bib as bib_mod
from paper_handler import documents
from paper_handler import research as research_mod
from paper_handler.mcp.context import (
    ToolError,
    bib_paths,
    compact,
    int_arg,
    paper_or_single,
    session,
    str_arg,
    text_of,
    truncate,
)
from paper_handler.mcp.registry import schema, tool
from paper_handler.mcp.style import STYLE_RULES


def _citation_state(text: str, bib_files: list[Any]) -> dict[str, Any]:
    used = documents.citations(text)
    defined: list[str] = []
    for path in bib_files:
        defined.extend(bib_mod.keys(path))
    return {
        "used": used,
        "defined_count": len(defined),
        "defined": defined[:40],
        "unresolved": [key for key in used if key not in set(defined)],
    }


@tool(
    "paper_context",
    "A compact context pack for writing one paper: front matter summary, outline, "
    "citation keys, current diagnostics and house style. This is the best first call; "
    "it is bounded by `budget` tokens.",
    schema(
        {
            "name": {"type": "string", "description": "paper name (optional if corpus has one)"},
            "budget": {
                "type": "integer",
                "default": 1200,
                "description": "approximate token budget for the response",
            },
        }
    ),
)
def paper_context(args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    item = paper_or_single(str_arg(args, "name") or None, current)
    text = text_of(item)
    pack = documents.outline(text)
    handoff = research_mod.load_paper_handoff(item.dir)
    report = documents.lint(text, bib_paths(item))
    data: dict[str, Any] = {
        "paper": item.name,
        "title": pack["title"],
        "status": pack["status"],
        "engine": item.engine,
        "words": pack["words"],
        "abstract_words": pack["abstract_words"],
        "sections": pack["sections"],
        "missing": pack["missing"],
        "citations": _citation_state(text, bib_paths(item)),
        "issues": [
            {"severity": issue["severity"], "code": issue["code"], "message": issue["message"]}
            for issue in report["issues"][:6]
        ],
        "readability": report["readability"],
        "style": STYLE_RULES,
        "next": "paper_read_section for one heading, then paper_write_section; lint after each.",
    }
    if handoff is not None:
        data["research"] = {
            "topic": handoff.topic,
            "included": handoff.included,
            "screening_ready": handoff.screening_ready,
            "note": "call paper_research_context for citation keys and core papers",
        }

    budget = int_arg(args, "budget", 1200) or 1200
    truncated = False
    if len(compact(data)) > budget * 4:
        data.pop("readability", None)
        data.pop("citations", None)
        data.pop("research", None)
        data["citations_note"] = "omitted for budget; call paper_lint or paper_bib_check"
        truncated = True
    if len(compact(data)) > budget * 4:
        data["issues"] = data["issues"][:3]
        truncated = True
    data["truncated"] = truncated
    return data


@tool(
    "paper_outline",
    "The heading tree with per-section word counts, plus missing standard sections. "
    "Cheaper than reading the paper.",
    schema({"name": {"type": "string"}}),
)
def paper_outline(args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    item = paper_or_single(str_arg(args, "name") or None, current)
    pack = documents.outline(text_of(item))
    return {"paper": item.name, **pack}


@tool(
    "paper_read_section",
    "Read exactly one section (heading plus body), truncated to `max_tokens`. "
    "Use this instead of reading the whole file.",
    schema(
        {
            "name": {"type": "string"},
            "heading": {"type": "string"},
            "level": {"type": "integer"},
            "max_tokens": {"type": "integer", "default": 1200},
        },
        ["heading"],
    ),
)
def paper_read_section(args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    item = paper_or_single(str_arg(args, "name") or None, current)
    text = text_of(item)
    level = int_arg(args, "level")
    try:
        section = documents.find_section(
            documents.parse_sections(text),
            str_arg(args, "heading", required=True),
            level,
        )
    except documents.DocumentError as exc:
        raise ToolError(str(exc)) from exc
    body = documents.body_of(text, section).strip("\n")
    clipped, was_clipped = truncate(body, int_arg(args, "max_tokens", 1200))
    return {
        "paper": item.name,
        "heading": section.heading,
        "level": section.level,
        "words": documents.word_count(body),
        "text": clipped,
        "truncated": was_clipped,
    }


@tool(
    "paper_write_section",
    "Replace, append to, or insert a section. Content is markdown without the heading. "
    "Returns a small receipt and the updated outline — not the whole document.",
    schema(
        {
            "name": {"type": "string"},
            "heading": {"type": "string"},
            "content": {"type": "string", "description": "markdown body, no heading line"},
            "mode": {
                "type": "string",
                "enum": ["replace", "append", "insert"],
                "default": "replace",
            },
            "level": {"type": "integer", "default": 2},
            "after": {"type": "string", "description": "for insert: existing section to follow"},
        },
        ["heading", "content"],
    ),
)
def paper_write_section(args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    item = paper_or_single(str_arg(args, "name") or None, current)
    content = str_arg(args, "content", required=True)
    heading = str_arg(args, "heading", required=True)
    mode = str_arg(args, "mode", default="replace") or "replace"
    if not content.strip():
        raise ToolError("content is empty; refusing to write an empty section")
    try:
        receipt = documents.edit_file(
            item.entry,
            heading,
            content,
            mode=mode,
            level=int_arg(args, "level"),
            after=str_arg(args, "after") or None,
        )
    except documents.DocumentError as exc:
        raise ToolError(str(exc)) from exc

    text = text_of(item)
    report = documents.lint(text, bib_paths(item))
    nearby = [
        issue
        for issue in report["issues"]
        if issue["severity"] == "error" or issue.get("section") == heading
    ][:5]
    return {
        "ok": report["ok"],
        "paper": item.name,
        **receipt,
        "errors": report["errors"],
        "warnings": report["warnings"],
        "issues": nearby,
        "next": "paper_lint, then the next section; paper_render when complete.",
    }


@tool(
    "paper_write_abstract",
    "Set the front-matter abstract. Keeps the abstract out of the section flow; "
    "returns its word count and any diagnostics.",
    schema({"name": {"type": "string"}, "text": {"type": "string"}}, ["text"]),
)
def paper_write_abstract(args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    item = paper_or_single(str_arg(args, "name") or None, current)
    abstract = str_arg(args, "text", required=True)
    if not abstract.strip():
        raise ToolError("text is empty")
    receipt = documents.set_abstract(item.entry, abstract)
    report = documents.lint(text_of(item), bib_paths(item))
    return {
        "ok": report["ok"],
        "paper": item.name,
        **receipt,
        "errors": report["errors"],
        "warnings": report["warnings"],
    }


__all__ = [
    "paper_context",
    "paper_outline",
    "paper_read_section",
    "paper_write_abstract",
    "paper_write_section",
]
