"""Corpus discovery, engine inference and target resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from paper_handler import project


def test_discover_empty_corpus(tmp_path: Path) -> None:
    assert project.discover(tmp_path / "missing") == []
    empty = tmp_path / "empty"
    empty.mkdir()
    assert project.discover(empty) == []


def test_discover_directories_and_loose_qmd(make_paper, corpus: Path) -> None:
    make_paper("alpha", title="Alpha", status="submitted")
    make_paper("beta", engine="latex")

    (corpus / "papers" / "draft-only.qmd").write_text(
        "---\ntitle: \"Loose\"\nformat: pdf\n---\nbody\n", encoding="utf-8"
    )
    # Noise that must be ignored.
    (corpus / "papers" / ".hidden").mkdir()
    (corpus / "papers" / ".hidden" / "index.qmd").write_text("---\ntitle: x\n---\n")
    (corpus / "papers" / "no-entry" / "notes.md").parent.mkdir()
    (corpus / "papers" / "no-entry" / "notes.md").write_text("hi\n")

    papers = project.discover(corpus / "papers")
    by_name = {p.name: p for p in papers}

    assert set(by_name) == {"alpha", "beta", "draft-only"}
    assert by_name["alpha"].title == "Alpha"
    assert by_name["alpha"].status == "submitted"
    assert by_name["alpha"].engine == "typst"
    assert by_name["beta"].engine == "latex"
    assert by_name["draft-only"].title == "Loose"
    assert by_name["draft-only"].engine == "latex"
    assert by_name["draft-only"].dir == corpus / "papers"


def test_main_qmd_is_a_fallback_entry(tmp_path: Path) -> None:
    directory = tmp_path / "paper"
    directory.mkdir()
    (directory / "main.qmd").write_text("---\ntitle: Main\n---\n", encoding="utf-8")
    assert project.find_entry(directory) == directory / "main.qmd"


def test_ambiguous_qmd_has_no_entry(tmp_path: Path) -> None:
    directory = tmp_path / "paper"
    directory.mkdir()
    (directory / "one.qmd").write_text("---\ntitle: One\n---\n")
    (directory / "two.qmd").write_text("---\ntitle: Two\n---\n")
    assert project.find_entry(directory) is None


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [
        ("typst", "typst"),
        ("pdf", "latex"),
        ({"typst": {"keep-typ": True}}, "typst"),
        ({"pdf": {"documentclass": "article"}}, "latex"),
        ({"html": None}, None),
        (None, None),
    ],
)
def test_engine_from_format(fmt, expected) -> None:
    assert project.engine_from_meta({"format": fmt}) == expected


def test_explicit_engine_key_beats_format() -> None:
    assert project.engine_from_meta({"engine": "latex", "format": "typst"}) == "latex"


def test_pdf_property_follows_entry(tmp_path: Path) -> None:
    directory = tmp_path / "p"
    directory.mkdir()
    entry = directory / "index.qmd"
    entry.write_text("---\ntitle: t\n---\n")
    paper = project._build(directory, entry, "p")
    assert paper.pdf == directory / "index.pdf"
    assert paper.rendered is False


def test_locate_rejects_path_outside_corpus(make_paper, corpus: Path) -> None:
    make_paper("inside")
    outside = corpus / "elsewhere"
    outside.mkdir()
    (outside / "index.qmd").write_text("---\ntitle: x\n---\n")

    inside = project.locate(corpus / "papers" / "inside", corpus / "papers")
    assert inside.name == "inside"

    with pytest.raises(ValueError, match="not inside the corpus"):
        project.locate(outside, corpus / "papers")


def test_locate_by_entry_file_and_directory(make_paper, corpus: Path) -> None:
    directory = make_paper("alpha")
    papers_dir = corpus / "papers"

    assert project.locate(directory / "index.qmd", papers_dir).name == "alpha"
    assert project.locate(directory, papers_dir).dir == directory
    assert project.locate(papers_dir / "alpha", papers_dir).dir == directory


def test_locate_missing_entry_errors(make_paper, corpus: Path) -> None:
    empty = corpus / "papers" / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="no index.qmd"):
        project.locate(empty, corpus / "papers")
