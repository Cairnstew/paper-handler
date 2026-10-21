"""Markdown/QMD document structure: outlines, section edits, and style checks.

The MCP server exposes these functions directly, so every result is a plain
``dict`` with short field names and no printing.  That keeps an agent's context
small: it can ask for an outline, fetch one section, replace that section, and
get a receipt — without ever round-tripping the whole paper.

Headings inside fenced code blocks are ignored, and character offsets in
:class:`Section` are absolute offsets into the original text, so edits never
need to re-parse the document.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paper_handler import frontmatter

#: ATX heading: 1-6 hashes, a space, the title.  Trailing hashes are optional.
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")

#: Fenced code open/close marker.
FENCE_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")

#: Pandoc-style citation: ``[@key]``, ``@key``, ``[-@key]``.  The lookbehind
#: keeps e-mail addresses (``a@b``) from being read as citations.
CITATION_RE = re.compile(r"(?<![\w@])@([A-Za-z][\w:./+-]*)")

#: A fenced code block, including its fences.
CODE_BLOCK_RE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,}).*?^[ \t]{0,3}\1[ \t]*$", re.M | re.S)

PLACEHOLDERS = (
    "{{",
    "replace this stub",
    "lorem ipsum",
)

REQUIRED_SECTIONS = ("introduction", "conclusion")


class DocumentError(ValueError):
    """A document could not be parsed or edited."""


@dataclass(frozen=True)
class Section:
    """One heading plus the body that belongs to it."""

    heading: str
    level: int
    #: Offset of the ``#`` that starts the heading.
    start: int
    #: Offset just past the heading line (i.e. the start of the body).
    heading_end: int
    #: Offset of the next heading at the same or a higher level, or EOF.
    end: int


# ── parsing ────────────────────────────────────────────────────────────────


def _body_offset(text: str) -> int:
    """Length of the front matter block, or 0 when there is none."""
    try:
        block, _ = frontmatter.split(text)
    except frontmatter.FrontMatterError as exc:
        raise DocumentError(str(exc)) from exc
    return len(block)


def parse_sections(text: str) -> list[Section]:
    """Every ATX heading outside front matter and fenced code, in document order."""
    offset = _body_offset(text)
    lines = text[offset:].splitlines(keepends=True)

    headings: list[tuple[int, int, str, int]] = []  # start, heading_end, title, level
    fence: str | None = None
    cursor = offset
    for line in lines:
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if fence is None:
                fence = marker[0] * len(marker)
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            cursor += len(line)
            continue
        if fence is None:
            match = HEADING_RE.match(line.rstrip("\r\n"))
            if match:
                hashes, title = match.group(1), match.group(2).strip()
                headings.append((cursor, cursor + len(line), title, len(hashes)))
        cursor += len(line)

    sections: list[Section] = []
    for index, (start, heading_end, title, level) in enumerate(headings):
        end = len(text)
        for later_start, _, _, later_level in headings[index + 1 :]:
            if later_level <= level:
                end = later_start
                break
        sections.append(Section(title, level, start, heading_end, end))
    return sections


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


def find_section(
    sections: list[Section], heading: str, level: int | None = None
) -> Section:
    """Find *heading* case-insensitively, rejecting ambiguity."""
    matches = [s for s in sections if _norm(s.heading) == _norm(heading)]
    if level is not None:
        matches = [s for s in matches if s.level == level]
    if not matches:
        raise DocumentError(f"no section headed {heading!r}")
    if len(matches) > 1:
        levels = ", ".join(str(s.level) for s in matches)
        raise DocumentError(
            f"section {heading!r} is ambiguous (levels {levels}); pass `level`"
        )
    return matches[0]


def word_count(text: str) -> int:
    """Rough prose word count: Unicode word runs, code included."""
    return len(re.findall(r"\b[\w'-]+\b", strip_code(text)))


#: Headings whose body is not part of the assessable word count.
_REFERENCES_HEADING = re.compile(r"^(references|bibliography|works cited)$", re.I)
_APPENDIX_HEADING = re.compile(r"^(appendix|appendices)\b", re.I)


def _prose_words(text: str) -> int:
    """Words excluding heading lines, for assessable-word totals."""
    return word_count(re.sub(r"^#{1,6}.*$", " ", text, flags=re.M))


def word_components(text: str) -> dict[str, int | None]:
    """Body, references and appendix word counts, kept separate.

    A word limit applies to the assessable body, not to the reference list or
    an appendix.  The legacy single ``words`` number counted everything after
    the front matter, which read as over-limit on a paper that was not.
    """
    body_start = _body_offset(text)
    sections = parse_sections(text)
    references_at = next(
        (s.start for s in sections if _REFERENCES_HEADING.match(s.heading)), None
    )
    appendix_at = next(
        (s.start for s in sections if _APPENDIX_HEADING.match(s.heading)), None
    )
    body_end = min(
        pos for pos in (references_at, appendix_at, len(text)) if pos is not None
    )
    references = 0
    if references_at is not None:
        end = appendix_at if appendix_at is not None and appendix_at > references_at else len(text)
        references = _prose_words(text[references_at:end])
    appendix = _prose_words(text[appendix_at:]) if appendix_at is not None else 0
    meta = frontmatter.parse(text) if body_start else {}
    abstract = meta.get("abstract")
    return {
        "body": _prose_words(text[body_start:body_end]),
        "references": references,
        "appendix": appendix,
        "abstract": word_count(abstract) if isinstance(abstract, str) else None,
    }


def strip_code(text: str) -> str:
    """Remove fenced code blocks, inline code and image/link tags."""
    text = CODE_BLOCK_RE.sub(" ", text)
    text = re.sub(r"`[^`\n]*`", " ", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return text


def body_of(text: str, section: Section) -> str:
    """The section body without its heading line."""
    return text[section.heading_end : section.end]


# ── outline ────────────────────────────────────────────────────────────────


def outline(text: str) -> dict[str, Any]:
    """A compact, machine-readable outline of *text*."""
    sections = parse_sections(text)
    meta = frontmatter.parse(text) if _body_offset(text) else {}
    items = [
        {
            "heading": section.heading,
            "level": section.level,
            "words": word_count(body_of(text, section)),
        }
        for section in sections
    ]
    headings = {_norm(item["heading"]) for item in items}
    words = word_components(text)
    return {
        "title": meta.get("title"),
        "status": meta.get("status", "draft"),
        "abstract_words": words["abstract"],
        "words": words["body"],
        "words_body": words["body"],
        "words_references": words["references"],
        "words_appendix": words["appendix"],
        "sections": items,
        "missing": [name for name in REQUIRED_SECTIONS if name not in headings],
    }


# ── editing ────────────────────────────────────────────────────────────────


def _replace_body(text: str, section: Section, body: str) -> str:
    prefix = text[: section.heading_end]
    suffix = text[section.end :]
    cleaned = body.strip("\n")
    block = f"\n{cleaned}\n" if cleaned else "\n"
    if suffix:
        block += "\n"
    else:
        block = block.rstrip("\n") + "\n"
    return prefix + block + suffix


def replace_section(text: str, heading: str, body: str, level: int | None = None) -> str:
    """Replace the body of an existing section, preserving its heading."""
    section = find_section(parse_sections(text), heading, level)
    return _replace_body(text, section, body)


def append_section(text: str, heading: str, body: str, level: int | None = None) -> str:
    """Append *body* to an existing section."""
    section = find_section(parse_sections(text), heading, level)
    existing = body_of(text, section).strip("\n")
    merged = f"{existing}\n\n{body.strip()}" if existing else body.strip()
    return _replace_body(text, section, merged)


def insert_section(
    text: str,
    heading: str,
    body: str,
    *,
    level: int = 2,
    after: str | None = None,
    before: str | None = None,
) -> str:
    """Insert a new section, after/before an anchor, otherwise at the end.

    ``after=""`` or ``before=""`` inserts at the start of the body (after the
    front matter), which is how front matter such as a declaration is placed
    ahead of the first existing section.  Passing both anchors is an error.
    """
    if after is not None and before is not None:
        raise DocumentError("pass either after or before, not both")
    if any(_norm(s.heading) == _norm(heading) for s in parse_sections(text)):
        raise DocumentError(f"section {heading!r} already exists")

    block = f"{'#' * level} {heading}\n\n{body.strip()}\n"
    if after is not None:
        position = _body_offset(text) if after == "" else find_section(
            parse_sections(text), after
        ).end
    elif before is not None:
        position = _body_offset(text) if before == "" else find_section(
            parse_sections(text), before
        ).start
    else:
        position = len(text)

    prefix = text[:position]
    suffix = text[position:]
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    return prefix + block + ("\n" + suffix if suffix else "")


def edit_file(
    path: Path,
    heading: str,
    content: str,
    *,
    mode: str = "replace",
    level: int | None = None,
    after: str | None = None,
    before: str | None = None,
    create: bool = False,
) -> dict[str, Any]:
    """Apply one section edit to *path* and return a compact receipt.

    ``create=True`` lets ``mode="replace"`` create the section when it does not
    exist, instead of failing with an error indistinguishable from a typo.
    """
    if mode not in ("replace", "append", "insert"):
        raise DocumentError("mode must be replace, append or insert")
    text = Path(path).read_text(encoding="utf-8")
    actual_mode = mode
    if mode == "replace":
        try:
            updated = replace_section(text, heading, content, level)
        except DocumentError:
            if not create:
                raise
            updated = insert_section(
                text,
                heading,
                content,
                level=level or 2,
                after=after,
                before=before,
            )
            actual_mode = "insert"
    elif mode == "append":
        updated = append_section(text, heading, content, level)
    else:
        updated = insert_section(
            text,
            heading,
            content,
            level=level or 2,
            after=after,
            before=before,
        )
    Path(path).write_text(updated, encoding="utf-8")
    words = word_components(updated)
    return {
        "mode": actual_mode,
        "heading": heading,
        "words_added": word_count(content),
        "words": words["body"],
        "words_body": words["body"],
        "words_references": words["references"],
        "words_appendix": words["appendix"],
        "abstract_words": words["abstract"],
        "sections": outline(updated)["sections"],
    }


def set_abstract(path: Path, abstract: str) -> dict[str, Any]:
    """Set the front-matter ``abstract`` and return a compact receipt."""
    path = Path(path)
    meta = frontmatter.read(path)
    meta["abstract"] = abstract.strip()
    frontmatter.write(path, meta)
    return {"abstract_words": word_count(abstract)}


# ── citations ──────────────────────────────────────────────────────────────


def citations(text: str) -> list[str]:
    """Citation keys referenced by *text*, in first-appearance order."""
    seen: dict[str, None] = {}
    for match in CITATION_RE.finditer(strip_code(text)):
        seen.setdefault(match.group(1).rstrip(".,;:"), None)
    return list(seen)


# ── lint ───────────────────────────────────────────────────────────────────


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _issue(
    severity: str,
    code: str,
    message: str,
    *,
    section: str | None = None,
    line: int | None = None,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        **({"section": section} if section else {}),
        **({"line": line} if line else {}),
    }


def _syllables(word: str) -> int:
    word = word.lower()
    groups = re.findall(r"[aeiouy]+", word)
    count = len(groups)
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def readability(text: str) -> dict[str, Any]:
    """Flesch reading ease and grade, computed on prose only."""
    prose = strip_code(text[_body_offset(text) :])
    prose = re.sub(r"^#{1,6}.*$", " ", prose, flags=re.M)
    prose = re.sub(r"\$[^$]*\$", " ", prose)
    prose = re.sub(r"\[[^\]]*@[^\]]*\]", " ", prose)
    prose = re.sub(r"[*_>#|]", " ", prose)
    prose = re.sub(r"\s+", " ", prose).strip()

    words = re.findall(r"[A-Za-z][A-Za-z'-]*", prose)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", prose) if s.strip()]
    if not words or not sentences:
        return {"words": 0, "sentences": 0, "avg_sentence": 0.0, "flesch": None}
    syllables = sum(_syllables(word) for word in words)
    avg_sentence = len(words) / len(sentences)
    flesch = 206.835 - 1.015 * avg_sentence - 84.6 * (syllables / len(words))
    grade = 0.39 * avg_sentence + 11.8 * (syllables / len(words)) - 15.59
    return {
        "words": len(words),
        "sentences": len(sentences),
        "avg_sentence": round(avg_sentence, 1),
        "flesch": round(flesch, 1),
        "grade": round(grade, 1),
    }


def lint(
    text: str,
    bib_paths: Path | list[Path] | tuple[Path, ...] | None = None,
) -> dict[str, Any]:
    """Structural and style diagnostics, cheapest useful checks only.

    *bib_paths* may be one path or several; a paper can keep its own
    ``references.bib`` beside a generated ``research/references.bib``.
    """
    issues: list[dict[str, Any]] = []
    sections = parse_sections(text)
    meta = frontmatter.parse(text) if _body_offset(text) else {}
    body_start = _body_offset(text)

    if bib_paths is None:
        paths: list[Path] = []
    elif isinstance(bib_paths, (str, Path)):
        paths = [Path(bib_paths)]
    else:
        paths = [Path(path) for path in bib_paths]
    paths = [path for path in paths if path.is_file()]

    # Placeholders are almost always a half-written paper.
    for number, line in enumerate(text.splitlines(), start=1):
        lowered = line.casefold()
        if any(token in lowered for token in PLACEHOLDERS) or re.search(
            r"\b(TODO|TBD|FIXME)\b", line
        ):
            issues.append(
                _issue(
                    "warning",
                    "placeholder",
                    "placeholder text left in the document",
                    line=number,
                )
            )

    # Heading hierarchy and duplicates.
    previous_level = 0
    seen: dict[str, int] = {}
    for section in sections:
        if previous_level and section.level > previous_level + 1:
            issues.append(
                _issue(
                    "warning",
                    "heading-jump",
                    f"heading level jumps from {previous_level} to {section.level}",
                    section=section.heading,
                    line=_line_of(text, section.start),
                )
            )
        previous_level = section.level
        key = _norm(section.heading)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            issues.append(
                _issue(
                    "warning",
                    "duplicate-heading",
                    "heading appears more than once",
                    section=section.heading,
                    line=_line_of(text, section.start),
                )
            )

    headings = {_norm(s.heading) for s in sections}
    for required in REQUIRED_SECTIONS:
        if required not in headings:
            issues.append(
                _issue("warning", "missing-section", f"no {required.title()} section")
            )

    # Empty and over-long sections.
    for section in sections:
        body = body_of(text, section)
        words = word_count(body)
        if not body.strip() and section.heading.casefold() not in ("references", "appendix"):
            issues.append(
                _issue("info", "empty-section", "section has no body", section=section.heading)
            )
        for paragraph in re.split(r"\n\s*\n", body):
            if word_count(paragraph) > 180:
                issues.append(
                    _issue(
                        "warning",
                        "long-paragraph",
                        "paragraph is over 180 words; split it",
                        section=section.heading,
                    )
                )
                break

    # Long sentences, capped so a bad draft does not flood the context.
    prose = strip_code(text[body_start:])
    prose = re.sub(r"^#{1,6}.*$", " ", prose, flags=re.M)
    long_sentences = 0
    for sentence in re.split(r"(?<=[.!?])\s+", prose):
        if len(sentence.split()) > 40:
            long_sentences += 1
            if long_sentences <= 5:
                issues.append(
                    _issue(
                        "info",
                        "long-sentence",
                        "sentence is over 40 words; split it",
                        line=None,
                    )
                )

    # Abstract length.
    abstract = meta.get("abstract")
    if isinstance(abstract, str):
        words = word_count(abstract)
        if words < 80:
            issues.append(
                _issue(
                    "warning",
                    "abstract-short",
                    f"abstract is only {words} words (aim for 120-250)",
                )
            )
        elif words > 300:
            issues.append(
                _issue("warning", "abstract-long", f"abstract is {words} words (aim for 120-250)")
            )

    # Images without alt text.
    for number, line in enumerate(text.splitlines(), start=1):
        if re.search(r"!\[\s*\]\(", line):
            issues.append(
                _issue("warning", "image-alt", "image has no alt text", line=number)
            )

    # Citations versus the bibliography (possibly several files).
    referenced = citations(text)
    if paths:
        from paper_handler import bib as bib_mod

        defined: set[str] = set()
        for path in paths:
            defined.update(bib_mod.keys(path))
        unresolved = [key for key in referenced if key not in defined]
        for key in unresolved:
            issues.append(
                _issue(
                    "error",
                    "undefined-citation",
                    f"citation {key!r} is not in the bibliography",
                )
            )
        unused = sorted(defined - set(referenced))
        if unused:
            issues.append(
                _issue(
                    "info",
                    "unused-citation",
                    f"{len(unused)} bibliography entries are never cited",
                )
            )
    elif referenced:
        issues.append(
            _issue(
                "info",
                "no-bibliography",
                "citations are used but no bibliography file is present",
            )
        )

    report = readability(text)
    if report["avg_sentence"] and report["avg_sentence"] > 30:
        issues.append(
            _issue(
                "info",
                "readability",
                f"average sentence is {report['avg_sentence']} words; aim under 25",
            )
        )

    errors = sum(1 for issue in issues if issue["severity"] == "error")
    warnings = sum(1 for issue in issues if issue["severity"] == "warning")
    words = word_components(text)
    return {
        "ok": errors == 0,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
        "readability": report,
        "words": words["body"],
        "words_body": words["body"],
        "words_references": words["references"],
        "words_appendix": words["appendix"],
        "abstract_words": words["abstract"],
    }
