"""Scaffolding a paper from a built-in or corpus-local template."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from paper_handler import frontmatter as fm
from paper_handler.config import Config
from paper_handler.scaffold import (
    TemplateNotFoundError,
    builtin_templates_dir,
    list_templates,
    scaffold,
)


def test_builtin_templates_are_packaged() -> None:
    """Guards against templates being dropped from the wheel."""
    names = {t.name for t in list_templates()}
    assert {"typst-article", "latex-article"} <= names
    for template in list_templates():
        assert (template.path / "index.qmd").is_file(), template.name
        assert (template.path / "references.bib").is_file(), template.name


def test_scaffold_creates_and_substitutes(corpus: Path) -> None:
    config = Config(engine="typst", papers_dir=corpus / "papers")
    result = scaffold(
        "smoke-test",
        config,
        title="Smoke Test Paper",
        today="2026-10-21",
    )

    entry = corpus / "papers" / "smoke-test" / "index.qmd"
    assert result.paper.entry == entry
    assert entry.is_file()
    assert (entry.parent / "references.bib").is_file()

    meta = fm.read(entry)
    assert meta["title"] == "Smoke Test Paper"
    assert meta["format"] == "typst"
    assert meta["date"] == "2026-10-21"

    text = entry.read_text(encoding="utf-8")
    assert "{{" not in text, "unsubstituted placeholder left in the paper"
    assert result.paper.name == "smoke-test"
    assert result.template.name == "typst-article"


def test_scaffold_from_read_only_template(corpus: Path) -> None:
    """Built-in templates are read-only in /nix/store.

    ``copytree`` preserves mode bits, so scaffolding has to restore owner write
    access or placeholder substitution fails with ``EACCES``.  This only
    reproduces from an installed package, never from a writable checkout.
    """
    template = corpus / "papers" / ".templates" / "read-only"
    template.mkdir(parents=True)
    (template / "index.qmd").write_text(
        "---\ntitle: \"{{title}}\"\nformat: {{format}}\n---\nbody\n", encoding="utf-8"
    )
    (template / "references.bib").write_text("% empty\n", encoding="utf-8")

    template.chmod(0o555)
    for path in template.iterdir():
        path.chmod(0o444)
    try:
        config = Config(engine="typst", papers_dir=corpus / "papers")
        result = scaffold("readonly", config, template="read-only", today="2026-01-01")
    finally:
        for path in template.iterdir():
            path.chmod(0o644)
        template.chmod(0o755)

    assert "{{" not in result.paper.entry.read_text(encoding="utf-8")
    assert result.paper.entry.stat().st_mode & stat.S_IWUSR


def test_default_template_follows_engine(corpus: Path) -> None:
    latex = Config(engine="latex", papers_dir=corpus / "papers")
    assert scaffold("a", latex, today="2026-01-01").template.name == "latex-article"
    assert fm.read(corpus / "papers" / "a" / "index.qmd")["format"] == "pdf"

    both = Config(engine="both", papers_dir=corpus / "papers")
    assert scaffold("b", both, today="2026-01-01").template.name == "typst-article"
    assert fm.read(corpus / "papers" / "b" / "index.qmd")["format"] == "typst"


def test_engine_argument_overrides_config(corpus: Path) -> None:
    config = Config(engine="typst", papers_dir=corpus / "papers")
    result = scaffold("c", config, engine="latex", today="2026-01-01")
    assert result.paper.engine == "latex"
    assert fm.read(result.paper.entry)["format"] == "pdf"


def test_title_defaults_to_title_cased_name(corpus: Path) -> None:
    config = Config(papers_dir=corpus / "papers")
    result = scaffold("deep-learning-101", config, today="2026-01-01")
    assert result.paper.title == "Deep Learning 101"


def test_rejects_unsafe_names(corpus: Path) -> None:
    from paper_handler.scaffold import ScaffoldError

    config = Config(papers_dir=corpus / "papers")
    for bad in ("../escape", "Has Space", "UPPER", "-leading", "", "a/b"):
        with pytest.raises(ScaffoldError, match="invalid paper name"):
            scaffold(bad, config)


def test_refuses_existing_without_force(corpus: Path) -> None:
    from paper_handler.scaffold import ScaffoldError

    config = Config(papers_dir=corpus / "papers")
    scaffold("dup", config, today="2026-01-01")
    with pytest.raises(ScaffoldError, match="already exists"):
        scaffold("dup", config, today="2026-01-01")
    # ...but --force replaces it wholesale.
    scaffold("dup", config, force=True, today="2026-01-01")


def test_unknown_template_lists_available(corpus: Path) -> None:
    config = Config(papers_dir=corpus / "papers")
    with pytest.raises(TemplateNotFoundError, match="typst-article"):
        scaffold("x", config, template="does-not-exist")


def test_corpus_template_overrides_builtin(corpus: Path, tmp_path: Path) -> None:
    templates = corpus / "papers" / ".templates" / "typst-article"
    templates.mkdir(parents=True)
    (templates / "index.qmd").write_text(
        "---\ntitle: \"{{title}}\"\nformat: {{format}}\n---\nlocal template\n",
        encoding="utf-8",
    )

    config = Config(engine="typst", papers_dir=corpus / "papers")
    assert {t.name: t.builtin for t in list_templates(config.effective_templates_dir)}[
        "typst-article"
    ] is False

    result = scaffold("local", config, today="2026-01-01")
    assert result.template.path == templates
    assert "local template" in result.paper.entry.read_text(encoding="utf-8")


def test_bundled_templates_dir_exists_on_disk() -> None:
    assert builtin_templates_dir().is_dir()


def test_scaffold_skips_build_artifacts(corpus: Path) -> None:
    """Copy must not carry `.quarto/`, `__pycache__`, `*_files/` or PDFs across."""
    templates = corpus / "papers" / ".templates" / "noisy"
    templates.mkdir(parents=True)
    (templates / "index.qmd").write_text(
        "---\ntitle: \"{{title}}\"\nformat: {{format}}\n---\nbody\n", encoding="utf-8"
    )
    (templates / "references.bib").write_text("% empty\n", encoding="utf-8")
    (templates / ".quarto").mkdir()
    (templates / ".quarto" / "state.json").write_text("{}")
    (templates / "__pycache__").mkdir()
    (templates / "index.pdf").write_text("stale")
    (templates / "figure_files").mkdir()
    (templates / "figure_files" / "plot.png").write_text("png")

    config = Config(engine="typst", papers_dir=corpus / "papers")
    result = scaffold("clean", config, template="noisy", today="2026-01-01")

    assert {p.name for p in result.paper.dir.iterdir()} == {"index.qmd", "references.bib"}
