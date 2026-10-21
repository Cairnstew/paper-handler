"""Research handoff tools: import, context, sync and citation-key lookup.

The bundle is read as files (never by importing ``researcher_python``), so the
server stays hermetic and a handoff made on another machine still works.
"""

from __future__ import annotations

from typing import Any

from paper_handler import research as research_mod
from paper_handler.mcp.context import (
    ToolError,
    bool_arg,
    compact,
    int_arg,
    paper_or_single,
    rel,
    session,
    str_arg,
)
from paper_handler.mcp.registry import schema, tool
from paper_handler.scaffold import ScaffoldError, scaffold


def _load(path: str) -> research_mod.Handoff:
    try:
        return research_mod.load_handoff(path)
    except research_mod.ResearchError as exc:
        raise ToolError(str(exc)) from exc


@tool(
    "paper_research_import",
    "Scaffold a paper from a researcher-python handoff bundle and wire its "
    "bibliographies. The manual references.bib is never overwritten.",
    schema(
        {
            "handoff": {"type": "string", "description": "bundle directory or handoff.json"},
            "name": {"type": "string", "description": "new paper name"},
            "title": {"type": "string"},
            "engine": {"type": "string", "enum": ["typst", "latex", "both"]},
            "template": {"type": "string", "default": "research-article"},
            "force": {"type": "boolean", "default": False},
        },
        ["handoff", "name"],
    ),
)
def paper_research_import(args: dict[str, Any]) -> dict[str, Any]:
    bundle = _load(str_arg(args, "handoff", required=True))
    current = session()
    try:
        result = scaffold(
            str_arg(args, "name", required=True),
            current.config,
            template=str_arg(args, "template", default="research-article"),
            engine=str_arg(args, "engine") or None,
            title=str_arg(args, "title") or None,
            force=bool_arg(args, "force"),
        )
        receipt = research_mod.attach_to_paper(result.paper.dir, bundle)
    except (ScaffoldError, research_mod.ResearchError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    return {
        **receipt,
        "entry": rel(result.paper.entry, current),
        "next": "paper_research_context for keys, then paper_write_section.",
    }


@tool(
    "paper_research_context",
    "Compact evidence brief for an imported paper: counts, screening, top core "
    "papers and citation keys. Bounded by `budget`; never returns the bundle.",
    schema(
        {
            "name": {"type": "string"},
            "budget": {"type": "integer", "default": 1200},
            "max_papers": {"type": "integer", "default": 10},
            "max_keys": {"type": "integer", "default": 60},
        }
    ),
)
def paper_research_context(args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    item = paper_or_single(str_arg(args, "name") or None, current)
    handoff = research_mod.load_paper_handoff(item.dir)
    if handoff is None:
        raise ToolError(f"{item.name}: no research/handoff.json attached")
    data = research_mod.brief(
        handoff,
        max_papers=int_arg(args, "max_papers", 10) or 10,
        max_keys=int_arg(args, "max_keys", 60) or 60,
    )
    budget = int_arg(args, "budget", 1200) or 1200
    truncated = False
    if len(compact(data)) > budget * 4:
        data["papers"] = data["papers"][:5]
        data["keys"] = data["keys"][:20]
        truncated = True
    data["truncated"] = truncated
    return data


@tool(
    "paper_research_sync",
    "Refresh a paper's generated research/ files from a newer handoff bundle. "
    "Manuscript text and the manual references.bib are untouched.",
    schema(
        {
            "name": {"type": "string"},
            "handoff": {"type": "string", "description": "bundle directory or handoff.json"},
        },
        ["handoff"],
    ),
)
def paper_research_sync(args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    item = paper_or_single(str_arg(args, "name") or None, current)
    bundle = _load(str_arg(args, "handoff", required=True))
    try:
        receipt = research_mod.attach_to_paper(item.dir, bundle)
    except research_mod.ResearchError as exc:
        raise ToolError(str(exc)) from exc
    return {**receipt, "entry": rel(item.entry, current)}


@tool(
    "paper_cite_key",
    "Resolve a DOI/arXiv id/title from the attached handoff to its BibTeX key. "
    "Use this before citing a record whose key you do not know.",
    schema(
        {
            "name": {"type": "string"},
            "identifier": {"type": "string", "description": "DOI, arXiv id, title, or key"},
        },
        ["identifier"],
    ),
)
def paper_cite_key(args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    item = paper_or_single(str_arg(args, "name") or None, current)
    handoff = research_mod.load_paper_handoff(item.dir)
    if handoff is None:
        raise ToolError(f"{item.name}: no research/handoff.json attached")
    identifier = str_arg(args, "identifier", required=True)
    key = handoff.key_for(identifier)
    if key is None:
        raise ToolError(
            f"{identifier!r} is not in the handoff; add a real bibliography entry "
            "or re-import the handoff"
        )
    entry = next((entry for entry in handoff.entries if entry.key == key), None)
    return {
        "ok": True,
        "paper": item.name,
        "identifier": identifier,
        "key": key,
        **({"title": entry.title, "year": entry.year} if entry else {}),
    }


@tool(
    "paper_research_prisma",
    "Insert or replace a Quarto appendix that includes the generated PRISMA "
    "screening flow (research/prisma.md).",
    schema(
        {
            "name": {"type": "string"},
            "heading": {"type": "string", "default": "Screening"},
            "level": {"type": "integer", "default": 2},
            "after": {"type": "string", "description": "insert after this section"},
        }
    ),
)
def paper_research_prisma(args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    item = paper_or_single(str_arg(args, "name") or None, current)
    try:
        receipt = research_mod.append_prisma(
            item.dir,
            heading=str_arg(args, "heading", default="Screening") or "Screening",
            level=int_arg(args, "level", 2) or 2,
            after=str_arg(args, "after") or None,
        )
    except (research_mod.ResearchError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    return {
        **receipt,
        "entry": rel(item.entry, current),
        "next": "paper_render to build the appendix.",
    }


__all__ = [
    "paper_cite_key",
    "paper_research_context",
    "paper_research_import",
    "paper_research_prisma",
    "paper_research_sync",
]
