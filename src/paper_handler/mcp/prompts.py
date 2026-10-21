"""MCP prompts: short, tool-directed writing loops.

Prompts are opt-in recipes.  They deliberately reference tools by name instead
of restating the style guide, so a client can load one prompt and then let the
tools carry the context.
"""

from __future__ import annotations

from typing import Any

_PROMPTS = [
    {
        "name": "write_paper",
        "description": "Draft or complete a paper section by section within a token budget.",
        "arguments": [
            {"name": "name", "description": "paper name", "required": True},
            {"name": "topic", "description": "what the paper argues", "required": False},
        ],
    },
    {
        "name": "revise_paper",
        "description": "Improve clarity and evidence in an existing paper.",
        "arguments": [
            {"name": "name", "description": "paper name", "required": True},
            {"name": "focus", "description": "e.g. clarity, citations, results", "required": False},
        ],
    },
    {
        "name": "review_paper",
        "description": "Review a paper as a critical reader and report concrete fixes.",
        "arguments": [{"name": "name", "description": "paper name", "required": True}],
    },
    {
        "name": "research_to_paper",
        "description": (
            "Run the researcher handoff import, then write the paper section by section."
        ),
        "arguments": [
            {"name": "name", "description": "new paper name", "required": True},
            {"name": "handoff", "description": "handoff bundle directory", "required": True},
        ],
    },
]


def list_prompts() -> list[dict[str, Any]]:
    return _PROMPTS


def get(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    arguments = arguments or {}
    paper = arguments.get("name") or "<paper>"

    if name == "write_paper":
        topic = arguments.get("topic") or "the paper's stated topic"
        text = f"""\
Write the paper `{paper}` in the paper-handler corpus. Topic: {topic}.

Work in small steps; do not load the whole document.
1. Call `paper_context` with {{"name": "{paper}"}}. Read the outline, citations and issues.
2. For each heading that needs work, call `paper_read_section`, then
   `paper_write_section` with the markdown body (no heading). Use mode `insert`
   for new sections and `replace` for existing ones.
3. Call `paper_lint` after each section. Fix errors first, then warnings.
4. When the sections are complete, call `paper_write_abstract` (120-250 words),
   then `paper_lint`, then `paper_render`.

Rules: one claim per paragraph; active voice; define acronyms; cite only keys
listed in `citations.defined`; never invent a citation key; no placeholder text.
Keep each tool response small and continue from the receipt/outline it returns."""
    elif name == "revise_paper":
        focus = arguments.get("focus") or "clarity and evidence"
        text = f"""\
Revise `{paper}` with a focus on {focus}.

1. `paper_context` for the outline and diagnostics.
2. `paper_lint` to get the full issue list; prioritise errors, then repeated warnings.
3. For each affected section: `paper_read_section`, rewrite only what is needed,
   and `paper_write_section` (mode `replace`). Keep the author's claims intact.
4. Re-run `paper_lint`; stop when errors are zero and warnings are only stylistic.
5. `paper_render` only if the user asked for a PDF.

Do not rewrite the whole paper in one call and do not invent citations."""
    elif name == "review_paper":
        text = f"""\
Review `{paper}` as a critical but constructive reader.

1. `paper_context` and `paper_lint`.
2. Read sections selectively with `paper_read_section` (Introduction, Method,
   Results, Discussion first).
3. Report, in order: (a) claims not supported by evidence, (b) missing citations,
   (c) unclear or overlong passages with the heading, (d) structural gaps.
4. End with 3-5 concrete, prioritised fixes. Do not edit files unless asked."""
    elif name == "research_to_paper":
        handoff = arguments.get("handoff") or "<handoff>"
        text = f"""\
Write `{paper}` from the research bundle `{handoff}`.

1. Open the corpus if needed: `paper_open_corpus({{"path": "<corpus>"}})`.
2. `paper_research_import` with handoff `{handoff}` and name `{paper}`.
3. `paper_research_context` for counts, screening, core papers and citation keys.
4. For each heading: `paper_read_section`, then `paper_write_section` (body only,
   no heading). Use only keys from the research brief; call `paper_cite_key`
   when you have a DOI/title but not the key.
5. `paper_lint` after each section; fix errors first, then warnings.
6. `paper_write_abstract`, `paper_lint`, `paper_render`.

Do not invent citations, do not copy the whole bundle into the manuscript, and
keep the handoff's core/general scope. The bundle is evidence; the prose is yours."""
    else:
        raise KeyError(f"unknown prompt {name!r}")

    return {
        "description": next(p["description"] for p in _PROMPTS if p["name"] == name),
        "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
    }


__all__ = ["get", "list_prompts"]
