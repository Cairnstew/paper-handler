"""Research handoff import, citation mapping and multi-bibliography linting."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from paper_handler import documents
from paper_handler import frontmatter as fm
from paper_handler import research as research_mod
from paper_handler.cli import cli

FIXTURE = Path(__file__).parent / "fixtures" / "research-handoff"


def test_load_handoff_contract() -> None:
    handoff = research_mod.load_handoff(FIXTURE)
    assert handoff.topic == "Reproducible paper tooling"
    assert handoff.included == 2
    assert handoff.screening_ready is True
    assert handoff.counts["excluded"] == 1
    assert handoff.keys() == ["smith2020attention", "jones2021tooling"]
    assert handoff.key_for("10.5555/attention.2020") == "smith2020attention"
    assert handoff.key_for("Attention and Reproducible Writing") == "smith2020attention"
    assert handoff.key_for("smith2020attention") == "smith2020attention"
    assert handoff.key_for("not in the bundle") is None


def test_brief_is_compact_and_ordered() -> None:
    brief = research_mod.brief(research_mod.load_handoff(FIXTURE), max_papers=1, max_keys=1)
    assert brief["included"] == 2
    assert brief["papers"][0]["key"] == "smith2020attention"
    assert len(brief["keys"]) == 1
    assert brief["key_count"] == 2
    assert "paper_write_section" in brief["next"]


def test_newer_schema_is_rejected(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    shutil.copytree(FIXTURE, bundle)
    manifest = json.loads((bundle / "handoff.json").read_text())
    manifest["schema_version"] = 99
    (bundle / "handoff.json").write_text(json.dumps(manifest))

    with pytest.raises(research_mod.ResearchError, match="newer than supported"):
        research_mod.load_handoff(bundle)


def test_attach_wires_two_bibliographies(make_paper, corpus: Path) -> None:
    paper = make_paper("alpha")
    handoff = research_mod.load_handoff(FIXTURE)

    receipt = research_mod.attach_to_paper(paper, handoff)
    assert receipt["included"] == 2
    assert (paper / "research" / "references.bib").is_file()
    assert (paper / "research" / "citation-map.json").is_file()
    assert (paper / "references.bib").is_file()

    meta = fm.read(paper / "index.qmd")
    assert meta["bibliography"] == ["references.bib", "research/references.bib"]

    # Cite one key from each bibliography file.
    text = (paper / "index.qmd").read_text()
    text += "\n\nCite [@smith2020attention] and [@a2024].\n"
    (paper / "index.qmd").write_text(text)
    report = documents.lint(text, [paper / "references.bib", paper / "research" / "references.bib"])
    assert not [issue for issue in report["issues"] if issue["code"] == "undefined-citation"]


def test_attach_is_idempotent_and_preserves_manual_bib(make_paper, corpus: Path) -> None:
    paper = make_paper("alpha")
    handoff = research_mod.load_handoff(FIXTURE)
    manual = paper / "references.bib"
    manual.write_text("% my own entry\n@article{manual2024,\n title = {Manual},\n}\n")

    research_mod.attach_to_paper(paper, handoff)
    research_mod.attach_to_paper(paper, handoff)
    assert manual.read_text().startswith("% my own entry")


def test_multi_bibliography_lint_flags_only_undefined(tmp_path: Path) -> None:
    first = tmp_path / "a.bib"
    second = tmp_path / "b.bib"
    first.write_text("@article{one2020,\n title = {One},\n}\n")
    second.write_text("@article{two2021,\n title = {Two},\n}\n")
    text = "# Introduction\n\nCite [@one2020] and [@two2021].\n"

    report = documents.lint(text, [first, second])
    assert not [issue for issue in report["issues"] if issue["code"] == "undefined-citation"]

    report = documents.lint(text, [first])
    assert [issue["code"] for issue in report["issues"]].count("undefined-citation") == 1


def test_cli_import_context_and_status(runner: CliRunner, corpus: Path) -> None:
    imported = runner.invoke(
        cli,
        ["research", "import", str(FIXTURE), "--paper", "alpha", "--title", "Alpha"],
    )
    assert imported.exit_code == 0, imported.output
    assert "imported 2 records" in imported.output
    assert (corpus / "papers" / "alpha" / "research" / "references.bib").is_file()

    context = runner.invoke(cli, ["research", "context", "papers/alpha", "--json"])
    assert context.exit_code == 0, context.output
    data = json.loads(context.output)
    assert data["included"] == 2
    assert data["keys"] == ["smith2020attention", "jones2021tooling"]

    status = runner.invoke(cli, ["research", "status", "papers/alpha"])
    assert status.exit_code == 0
    assert "included: 2" in status.output
    assert "core: 1" in status.output


def test_cli_sync_refreshes_generated_files(
    make_paper, runner: CliRunner, corpus: Path
) -> None:
    paper = make_paper("alpha")
    result = runner.invoke(
        cli, ["research", "sync", str(paper), "--handoff", str(FIXTURE)]
    )
    assert result.exit_code == 0, result.output
    assert (paper / "research" / "handoff.json").is_file()
    assert "synced 2 records" in result.output


def test_paper_handoff_absent_returns_none(make_paper, corpus: Path) -> None:
    paper = make_paper("alpha")
    assert research_mod.load_paper_handoff(paper) is None


def test_cli_prisma_appends_an_include(runner: CliRunner, corpus: Path) -> None:
    imported = runner.invoke(
        cli,
        ["research", "import", str(FIXTURE), "--paper", "alpha", "--title", "Alpha"],
    )
    assert imported.exit_code == 0, imported.output

    result = runner.invoke(cli, ["research", "prisma", "papers/alpha"])
    assert result.exit_code == 0, result.output
    text = (corpus / "papers" / "alpha" / "index.qmd").read_text()
    assert "## Screening" in text
    assert "{{< include research/prisma.md >}}" in text

    # Idempotent: a second call replaces, not duplicates.
    again = runner.invoke(cli, ["research", "prisma", "papers/alpha"])
    assert again.exit_code == 0
    assert (corpus / "papers" / "alpha" / "index.qmd").read_text().count(
        "## Screening"
    ) == 1
