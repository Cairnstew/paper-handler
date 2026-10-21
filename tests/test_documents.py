"""Document structure, section editing, citation extraction and linting."""

from __future__ import annotations

from pathlib import Path

import pytest

from paper_handler import documents

TEXT = """\
---
title: "A Paper"
status: draft
abstract: |
  This is a deliberately short abstract so the linter flags it.
---

## Introduction

First paragraph. It cites [@doe2024] and @roe2021.

```markdown
## Not a heading
```

## Method

We do the thing.

### Details

Nested detail.

## Results

| A | B |
|---|---|
| 1 | 2 |
"""

def test_sections_ignore_frontmatter_and_fences() -> None:
    sections = documents.parse_sections(TEXT)
    assert [s.heading for s in sections] == ["Introduction", "Method", "Details", "Results"]
    assert [s.level for s in sections] == [2, 2, 3, 2]


def test_section_body_offsets() -> None:
    sections = documents.parse_sections(TEXT)
    intro = sections[0]
    body = documents.body_of(TEXT, intro)
    assert body.startswith("\nFirst paragraph")
    assert "## Method" not in body
    # A parent section owns its nested subsections.
    method = documents.body_of(TEXT, sections[1])
    assert method.startswith("\nWe do the thing.")
    assert "### Details" in method
    assert "## Results" not in method
    assert documents.body_of(TEXT, sections[2]).strip() == "Nested detail."


def test_outline_reports_words_and_missing_sections() -> None:
    pack = documents.outline(TEXT)
    assert pack["title"] == "A Paper"
    assert pack["status"] == "draft"
    assert pack["sections"][0]["heading"] == "Introduction"
    assert pack["sections"][0]["words"] > 0
    assert "conclusion" in pack["missing"]


def test_find_section_is_case_insensitive_and_rejects_ambiguity() -> None:
    sections = documents.parse_sections(TEXT)
    assert documents.find_section(sections, "method").level == 2

    duplicated = "## Notes\na\n\n### Notes\nb\n"
    with pytest.raises(documents.DocumentError, match="ambiguous"):
        documents.find_section(documents.parse_sections(duplicated), "Notes")
    assert (
        documents.find_section(documents.parse_sections(duplicated), "Notes", 3).level == 3
    )


def test_replace_section_preserves_everything_else() -> None:
    updated = documents.replace_section(TEXT, "Method", "New method text.")
    assert "New method text." in updated
    assert "We do the thing." not in updated
    assert "title: \"A Paper\"" in updated
    assert "First paragraph." in updated
    assert "## Results" in updated


def test_append_section_keeps_existing_body() -> None:
    updated = documents.append_section(TEXT, "Method", "One more detail.")
    assert "We do the thing." in updated
    assert "One more detail." in updated
    # `Details` is nested inside Method, so appending goes after it and before
    # the next same-level heading.
    assert (
        updated.index("### Details")
        < updated.index("One more detail.")
        < updated.index("## Results")
    )


def test_insert_section_after_anchor_and_at_end() -> None:
    middle = documents.insert_section(
        TEXT, "Related Work", "Prior work.", after="Introduction"
    )
    assert (
        middle.index("## Introduction")
        < middle.index("## Related Work")
        < middle.index("## Method")
    )

    after = documents.insert_section(TEXT, "Discussion", "Discuss.", after="Results")
    assert after.index("## Results") < after.index("## Discussion")

    at_end = documents.insert_section(TEXT, "Conclusion", "Done.")
    assert at_end.rstrip().endswith("Done.")


def test_insert_duplicate_heading_errors() -> None:
    with pytest.raises(documents.DocumentError, match="already exists"):
        documents.insert_section(TEXT, "Method", "duplicate")


def test_edit_file_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "paper.qmd"
    path.write_text(TEXT, encoding="utf-8")

    receipt = documents.edit_file(path, "Method", "Replacement body.", mode="replace")
    assert receipt["mode"] == "replace"
    assert receipt["heading"] == "Method"
    assert receipt["words_added"] == 2
    assert path.read_text(encoding="utf-8").count("Replacement body.") == 1

    with pytest.raises(documents.DocumentError, match="mode"):
        documents.edit_file(path, "Method", "x", mode="rename")


def test_set_abstract(tmp_path: Path) -> None:
    path = tmp_path / "paper.qmd"
    path.write_text(TEXT, encoding="utf-8")
    receipt = documents.set_abstract(path, "A new abstract with several words.")
    assert receipt["abstract_words"] == 6
    assert "A new abstract" in path.read_text(encoding="utf-8")


def test_citations_ignore_code_and_email() -> None:
    text = "Cite [@a2024; @b2025], @c2024. Mail a@example.com. `@code` and [@d2024]."
    assert documents.citations(text) == ["a2024", "b2025", "c2024", "d2024"]


def test_readability_is_stable_on_prose() -> None:
    report = documents.readability(
        "# H\n\nThis is a short sentence. This is another short sentence."
    )
    assert report["words"] == 10
    assert report["sentences"] == 2
    assert report["flesch"] > 0


def test_lint_flags_placeholders_missing_sections_and_undefined_citations(
    tmp_path: Path,
) -> None:
    bib = tmp_path / "references.bib"
    bib.write_text(
        "@article{doe2024,\n  author = {Doe, Jane},\n  title = {T},\n  year = {2024},\n}\n",
        encoding="utf-8",
    )
    text = """\
---
title: Untitled
abstract: "Too short."
---

# Introduction

TODO: write this. Cite @missing2020.

#### Results

![](plot.png)
"""
    report = documents.lint(text, bib)
    codes = {issue["code"] for issue in report["issues"]}
    assert "placeholder" in codes
    assert "undefined-citation" in codes
    assert "missing-section" in codes
    assert "heading-jump" in codes
    assert "image-alt" in codes
    assert "abstract-short" in codes
    assert report["errors"] >= 1
    assert report["ok"] is False


def test_lint_clean_document(tmp_path: Path) -> None:
    bib = tmp_path / "references.bib"
    bib.write_text(
        "@article{doe2024,\n  author = {Doe, Jane},\n  title = {T},\n  year = {2024},\n}\n",
        encoding="utf-8",
    )
    abstract = " ".join(["This paper studies a narrow question and reports one result."] * 12)
    text = f"""\
---
title: Clean
abstract: "{abstract}"
---

# Introduction

This is a claim with evidence [@doe2024].

# Method

We describe the method.

# Results

The result is reported.

# Conclusion

The claim holds within the stated limits.
"""
    report = documents.lint(text, bib)
    assert report["ok"] is True
    assert not [issue for issue in report["issues"] if issue["severity"] == "error"]


def test_unused_bibliography_is_only_info(tmp_path: Path) -> None:
    bib = tmp_path / "references.bib"
    bib.write_text(
        "@article{unused,\n  author = {A},\n  title = {T},\n  year = {2024},\n}\n",
        encoding="utf-8",
    )
    report = documents.lint("# Introduction\n\nNo citations.\n\n# Conclusion\n\nDone.\n", bib)
    assert any(issue["code"] == "unused-citation" for issue in report["issues"])
    assert report["ok"] is True
