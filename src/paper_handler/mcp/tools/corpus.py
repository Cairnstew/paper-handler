"""Corpus-level tools: list, create, inspect, doctor."""

from __future__ import annotations

from typing import Any

from paper_handler import documents, project, toolchain
from paper_handler.mcp.context import (
    ToolError,
    bool_arg,
    close_corpus,
    open_corpus,
    paper_or_single,
    rel,
    session,
    str_arg,
)
from paper_handler.mcp.registry import schema, tool
from paper_handler.scaffold import ScaffoldError, list_templates, scaffold


@tool(
    "paper_list",
    "List the papers in the corpus with title, status, engine, render state and word count. "
    "Start here; it is much cheaper than reading any paper.",
    schema(),
)
def paper_list(_args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    papers = project.discover(current.corpus)
    return {
        "corpus": str(current.corpus),
        "count": len(papers),
        "papers": [
            {
                "name": item.name,
                "title": item.title,
                "status": item.status,
                "engine": item.engine,
                "rendered": item.rendered,
                "words": documents.word_count(
                    item.entry.read_text(encoding="utf-8", errors="replace")
                ),
            }
            for item in papers
        ],
    }


@tool(
    "paper_new",
    "Scaffold a new paper from a template. Returns the entry path; then write it "
    "section by section with paper_write_section.",
    schema(
        {
            "name": {"type": "string", "description": "lowercase-dashed directory name"},
            "title": {"type": "string"},
            "engine": {"type": "string", "enum": ["typst", "latex", "both"]},
            "template": {"type": "string"},
            "force": {"type": "boolean", "default": False},
        },
        ["name"],
    ),
)
def paper_new(args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    name = str_arg(args, "name", required=True)
    try:
        result = scaffold(
            name,
            current.config,
            template=str_arg(args, "template") or None,
            engine=str_arg(args, "engine") or None,
            title=str_arg(args, "title") or None,
            force=bool_arg(args, "force"),
        )
    except (ScaffoldError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    return {
        "ok": True,
        "name": result.paper.name,
        "entry": rel(result.paper.entry, current),
        "template": result.template.name,
        "next": "Call paper_context, then paper_write_section for each heading.",
    }


@tool(
    "paper_init",
    "Initialise a paper corpus (config, _quarto.yml, papers/ directory).",
    schema(
        {
            "directory": {"type": "string", "default": "."},
            "engine": {"type": "string", "enum": ["typst", "latex", "both"]},
            "papers_dir": {"type": "string", "default": "papers"},
            "force": {"type": "boolean", "default": False},
        }
    ),
)
def paper_init(args: dict[str, Any]) -> dict[str, Any]:
    from pathlib import Path

    from paper_handler.project import CorpusExistsError, init_corpus

    try:
        created = init_corpus(
            Path(str_arg(args, "directory", default=".")),
            engine=str_arg(args, "engine") or None,
            papers_dir_name=str_arg(args, "papers_dir", default="papers"),
            force=bool_arg(args, "force"),
        )
    except (CorpusExistsError, OSError) as exc:
        raise ToolError(str(exc)) from exc
    return {"ok": True, **created, "next": "Call paper_new."}


@tool(
    "paper_templates",
    "List built-in and corpus-local paper templates.",
    schema(),
)
def paper_templates(_args: dict[str, Any]) -> dict[str, Any]:
    current = session()
    return {
        "templates": [
            {"name": item.name, "builtin": item.builtin}
            for item in list_templates(current.config.effective_templates_dir)
        ]
    }


@tool(
    "paper_doctor",
    "Report which render tools (quarto, typst, pdflatex, ...) are available.",
    schema(),
)
def paper_doctor(_args: dict[str, Any]) -> dict[str, Any]:
    probes = toolchain.probe()
    return {
        "ok": any(item.name == "quarto" and item.found for item in probes),
        "present": [item.name for item in probes if item.found],
        "missing": [item.name for item in probes if not item.found],
        "versions": {item.name: item.detail for item in probes if item.found},
    }


@tool(
    "paper_open_corpus",
    "Pin a corpus for this MCP session (a corpus root or a papers/ directory). "
    "Use it when the server was launched outside the corpus.",
    schema({"path": {"type": "string"}}, ["path"]),
)
def paper_open_corpus(args: dict[str, Any]) -> dict[str, Any]:
    try:
        current = open_corpus(str_arg(args, "path", required=True))
    except ToolError:
        raise
    papers = project.discover(current.corpus)
    return {
        "ok": True,
        "corpus": str(current.corpus),
        "count": len(papers),
        "papers": [item.name for item in papers],
    }


@tool(
    "paper_close_corpus",
    "Forget the session corpus and return to cwd/config discovery.",
    schema(),
)
def paper_close_corpus(_args: dict[str, Any]) -> dict[str, Any]:
    close_corpus()
    return {"ok": True, "corpus": None}


@tool(
    "paper_meta_get",
    "Read one front-matter key, or the whole front matter when key is omitted.",
    schema({"name": {"type": "string"}, "key": {"type": "string"}}),
)
def paper_meta_get(args: dict[str, Any]) -> dict[str, Any]:
    from paper_handler import frontmatter

    current = session()
    item = paper_or_single(str_arg(args, "name") or None, current)
    meta = frontmatter.read(item.entry)
    key = str_arg(args, "key")
    if key:
        if key not in meta:
            raise ToolError(f"{item.name}: no {key!r} in front matter")
        return {"paper": item.name, key: meta[key]}
    return {"paper": item.name, "meta": meta}


@tool(
    "paper_meta_set",
    "Set a front-matter key. The value is parsed as YAML, so 2026 becomes a number and "
    "'[a, b]' a list.",
    schema(
        {
            "name": {"type": "string"},
            "key": {"type": "string"},
            "value": {"type": "string"},
        },
        ["key", "value"],
    ),
)
def paper_meta_set(args: dict[str, Any]) -> dict[str, Any]:
    import yaml

    from paper_handler import frontmatter

    current = session()
    item = paper_or_single(str_arg(args, "name") or None, current)
    key = str_arg(args, "key", required=True)
    value = str_arg(args, "value", required=True)
    try:
        parsed: Any = yaml.safe_load(value)
    except yaml.YAMLError:
        parsed = value
    meta = frontmatter.read(item.entry)
    meta[key] = parsed
    frontmatter.write(item.entry, meta)
    return {"ok": True, "paper": item.name, "key": key, "value": parsed}


__all__ = [
    "paper_close_corpus",
    "paper_doctor",
    "paper_init",
    "paper_list",
    "paper_meta_get",
    "paper_meta_set",
    "paper_new",
    "paper_open_corpus",
    "paper_templates",
]
