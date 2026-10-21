"""BibTeX starter file and structural checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from paper_handler import bib

VALID = """\
@article{alpha2024,
  author = {A},
  title = {T},
  year = {2024},
}

@book{beta2021,
  author = {B},
  title = {U},
  year = {2021},
}
"""


def test_init_creates_starter(tmp_path: Path) -> None:
    path = bib.init(tmp_path / "refs" / "references.bib")
    assert path.is_file()
    assert "paper-handler bib init" in path.read_text(encoding="utf-8")
    assert bib.keys(path) == ["doe2024"]


def test_init_refuses_overwrite(tmp_path: Path) -> None:
    path = bib.init(tmp_path / "references.bib")
    with pytest.raises(bib.BibError, match="already exists"):
        bib.init(path)
    bib.init(path, overwrite=True)  # --force


def test_check_accepts_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "references.bib"
    path.write_text(VALID, encoding="utf-8")
    assert bib.check(path) == []
    assert bib.keys(path) == ["alpha2024", "beta2021"]


def test_check_missing_file(tmp_path: Path) -> None:
    assert bib.check(tmp_path / "nope.bib")[0].endswith("no such file")


def test_check_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "references.bib"
    path.write_text("   \n", encoding="utf-8")
    assert any("empty" in p for p in bib.check(path))


def test_check_unbalanced_braces(tmp_path: Path) -> None:
    path = tmp_path / "references.bib"
    path.write_text("@article{a2024,\n  title = {Never closed,\n}\n", encoding="utf-8")
    assert any("unbalanced braces" in p for p in bib.check(path))


def test_check_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "references.bib"
    path.write_text(VALID + "\n@article{alpha2024,\n  title = {Again},\n}\n", encoding="utf-8")
    assert any("duplicate citation key 'alpha2024'" in p for p in bib.check(path))


def test_check_ignores_braces_in_comments(tmp_path: Path) -> None:
    # A comment containing a stray brace must not trip the balance check.
    path = tmp_path / "references.bib"
    path.write_text(VALID + "\n% unmatched { in a comment\n", encoding="utf-8")
    assert bib.check(path) == []


def test_check_no_entries(tmp_path: Path) -> None:
    path = tmp_path / "references.bib"
    path.write_text("% just a comment\n", encoding="utf-8")
    assert any("no @type" in p for p in bib.check(path))


def test_check_empty_key(tmp_path: Path) -> None:
    path = tmp_path / "references.bib"
    path.write_text("@article{,\n  title = {Anonymous},\n}\n", encoding="utf-8")
    assert any("empty citation key" in p for p in bib.check(path))
