"""YAML front matter splitting, parsing and rewriting."""

from __future__ import annotations

import pytest

from paper_handler import frontmatter as fm

DOC = """---
title: "Hello"
year: 2026
tags: [a, b]
---

Body text.
"""

BODY = "\nBody text.\n"


def test_split_separates_block_and_body() -> None:
    block, body = fm.split(DOC)
    assert block.startswith("---\n")
    assert block.endswith("---\n")
    assert body == BODY


def test_parse_reads_mapping() -> None:
    assert fm.parse(DOC) == {"title": "Hello", "year": 2026, "tags": ["a", "b"]}


def test_no_front_matter() -> None:
    block, body = fm.split("just text\n")
    assert block == ""
    assert body == "just text\n"
    assert fm.parse("just text\n") == {}


def test_leading_content_is_not_a_delimiter() -> None:
    # `----` and `---foo` are ordinary text; only a bare `---` line opens.
    for text in ("----\nrest\n", "---foo\nrest\n", " ---\nrest\n"):
        block, body = fm.split(text)
        assert block == ""
        assert body == text


def test_unclosed_front_matter_raises() -> None:
    with pytest.raises(fm.FrontMatterError, match="never closed"):
        fm.split("---\ntitle: x\n\nbody without close\n")


def test_non_mapping_front_matter_raises() -> None:
    with pytest.raises(fm.FrontMatterError, match="must be a mapping"):
        fm.parse("---\n- just\n- a list\n---\n")


def test_render_roundtrip() -> None:
    meta = fm.parse(DOC)
    assert fm.parse(fm.render(meta)) == meta


def test_replace_keeps_body_byte_for_byte() -> None:
    body = "\nBody with `---` inside and trailing\n  whitespace\n\n"
    original = "---\ntitle: x\n---\n" + body
    out = fm.replace(original, {"title": "y"})
    assert out.endswith(body)
    assert fm.parse(out) == {"title": "y"}


def test_replace_adds_front_matter_when_missing() -> None:
    out = fm.replace("no front matter\n", {"title": "added"})
    assert fm.parse(out) == {"title": "added"}
    assert out.endswith("no front matter\n")


def test_comment_inside_front_matter_is_dropped() -> None:
    # Documented limitation of PyYAML: comments in the block do not survive a
    # rewrite.  Assert it so the behaviour is pinned rather than discovered.
    text = "---\n# a comment\ntitle: x\n---\nbody\n"
    out = fm.replace(text, fm.parse(text))
    assert "# a comment" not in out
    assert fm.parse(out)["title"] == "x"
    assert out.endswith("body\n")


def test_read_write_file(tmp_path) -> None:
    path = tmp_path / "index.qmd"
    path.write_text(DOC, encoding="utf-8")
    fm.write(path, {"title": "Replaced"})
    assert fm.read(path) == {"title": "Replaced"}
    assert path.read_text(encoding="utf-8").endswith(BODY)
