"""MCP resources: the style guide, corpus index, and per-paper context.

Resources are pull-based context.  A client that wants the writing rules can
read one short document once, instead of the server repeating them in every
tool response.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from paper_handler import documents, project
from paper_handler.mcp import context
from paper_handler.mcp.context import ToolError
from paper_handler.mcp.style import STYLE_GUIDE


def _static_resources() -> list[dict[str, Any]]:
    return [
        {
            "uri": "paper://style-guide",
            "name": "Academic style guide",
            "description": "Short house style for structure, prose and evidence.",
            "mimeType": "text/markdown",
        },
        {
            "uri": "paper://corpus",
            "name": "Paper corpus index",
            "description": "Every paper with title, status, engine and word count.",
            "mimeType": "application/json",
        },
        {
            "uri": "paper://templates",
            "name": "Paper templates",
            "description": "Built-in and corpus-local templates.",
            "mimeType": "application/json",
        },
    ]


def list_resources() -> list[dict[str, Any]]:
    return _static_resources()


def list_templates() -> list[dict[str, Any]]:
    return [
        {
            "uriTemplate": "paper://papers/{name}/outline",
            "name": "Paper outline",
            "description": "Heading tree with word counts and missing sections.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "paper://papers/{name}/context",
            "name": "Paper context pack",
            "description": "Budgeted context for writing one paper.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "paper://papers/{name}/research",
            "name": "Paper research brief",
            "description": "Counts, screening state, core papers and citation keys.",
            "mimeType": "application/json",
        },
    ]


def read(uri: str) -> dict[str, Any]:
    parsed = urlparse(uri)
    if parsed.scheme != "paper":
        raise ToolError(f"unknown resource URI {uri!r}")

    current = context.session()

    if parsed.netloc == "style-guide":
        payload: Any = STYLE_GUIDE
        mime = "text/markdown"
    elif parsed.netloc == "corpus":
        papers = project.discover(current.corpus)
        payload = {
            "corpus": str(current.corpus),
            "papers": [
                {
                    "name": paper.name,
                    "title": paper.title,
                    "status": paper.status,
                    "engine": paper.engine,
                    "rendered": paper.rendered,
                }
                for paper in papers
            ],
        }
        mime = "application/json"
    elif parsed.netloc == "templates":
        from paper_handler.scaffold import list_templates as templates

        payload = [
            {"name": item.name, "builtin": item.builtin}
            for item in templates(current.config.effective_templates_dir)
        ]
        mime = "application/json"
    elif parsed.netloc == "papers":
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 2 or parts[1] not in ("outline", "context", "research"):
            raise ToolError(f"unknown paper resource {uri!r}")
        name, kind = parts
        item = context.paper(name, current)
        if kind == "outline":
            payload = {"paper": item.name, **documents.outline(context.text_of(item))}
        elif kind == "research":
            from paper_handler import research as research_mod

            handoff = research_mod.load_paper_handoff(item.dir)
            if handoff is None:
                raise ToolError(f"{item.name}: no research/handoff.json attached")
            payload = research_mod.brief(handoff)
        else:
            # Reuse the tool so the budget and trimming rules stay in one place.
            from paper_handler.mcp.tools import writing

            payload = writing.paper_context({"name": item.name, "budget": 1200})
        mime = "application/json"
    else:
        raise ToolError(f"unknown resource URI {uri!r}")

    text = payload if isinstance(payload, str) else context.compact(payload)
    return {"contents": [{"uri": uri, "mimeType": mime, "text": text}]}


__all__ = ["list_resources", "list_templates", "read"]
