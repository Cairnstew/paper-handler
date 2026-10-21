"""The house style that tools point an agent at.

Kept deliberately short: it is a context resource, not an essay.  The same
rules are summarised in every ``paper_context`` pack so a model that never
reads the resource still gets the essentials.
"""

from __future__ import annotations

#: Served as the ``paper://style-guide`` MCP resource.
STYLE_GUIDE = """\
# Academic writing style

Structure
- Abstract 120–250 words: problem, approach, headline result, implication.
- Sections in order: Introduction, Related Work, Method, Results, Discussion, Conclusion.
- Each section opens with its claim; each paragraph makes one point.
- State limitations explicitly before the conclusion.

Prose
- Prefer active voice and concrete verbs.
- One idea per sentence; split anything over ~30 words.
- Define every acronym at first use; use it consistently afterwards.
- Avoid "very", "obviously", "clearly", "novel" unless you show the evidence.
- Past tense for what you did and measured; present tense for what is true.
- No placeholder text ("TODO", "TBD", "lorem ipsum", "{{...}}") in a finished draft.

Evidence
- Cite a source for every empirical claim and every borrowed method.
- Never invent a citation key: reuse keys from references.bib or add a real entry.
- Every figure and table needs a caption that states its takeaway.
- Report the measure, the baseline, and the effect size, not just "better".

Editing loop
1. `paper_context` for the outline and existing citations.
2. `paper_write_section` one section at a time (`mode: replace|append|insert`).
3. `paper_lint` after each section; fix errors, then warnings.
4. `paper_render` only when the draft is complete.
"""

#: Six rules small enough to sit inside a context pack.
STYLE_RULES = [
    "One claim per paragraph; section opens with its point.",
    "Active voice; split sentences over ~30 words.",
    "Define acronyms at first use; avoid filler intensifiers.",
    "Cite every empirical claim; never invent a citation key.",
    "Captions state the takeaway, not the chart type.",
    "Abstract 120-250 words; state limitations explicitly.",
]
