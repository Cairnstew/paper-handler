"""End-to-end CLI behaviour, driven through Click's test runner.

Tool lookups are made to fail deterministically (see the ``no_tools`` fixture)
so these tests assert on paper-handler's own behaviour rather than on whether
Quarto happens to be installed on the machine running the suite.  The real
Quarto render is exercised by the Nix `render-smoke` check instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from paper_handler import frontmatter as fm
from paper_handler.cli import cli, main


def output_of(result) -> str:
    """stdout + stderr, tolerating either Click 8.1's mixed or 8.2's split streams."""
    parts = [result.output]
    try:
        parts.append(result.stderr)
    except (ValueError, AttributeError):  # mixed-stream runner
        pass
    return "\n".join(p for p in parts if p)


def test_version(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_help_lists_every_command(runner: CliRunner) -> None:
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for name in (
        "doctor",
        "init",
        "new",
        "render",
        "list",
        "outline",
        "lint",
        "mcp",
        "research",
        "meta",
        "templates",
        "bib",
    ):
        assert name in result.output


def test_init_creates_a_corpus(runner: CliRunner, tmp_path: Path) -> None:
    root = tmp_path / "fresh"
    result = runner.invoke(cli, ["init", str(root), "--engine", "latex"])
    assert result.exit_code == 0, output_of(result)

    config = root / "paper-handler.toml"
    assert config.is_file()
    assert 'engine = "latex"' in config.read_text(encoding="utf-8")
    assert (root / "_quarto.yml").is_file()
    assert (root / "papers").is_dir()


def test_init_refuses_to_clobber(runner: CliRunner, corpus: Path) -> None:
    result = runner.invoke(cli, ["init", str(corpus)])
    assert result.exit_code == 1
    assert "already exists" in output_of(result)

    assert runner.invoke(cli, ["init", str(corpus), "--force"]).exit_code == 0


def test_new_then_list(runner: CliRunner, corpus: Path) -> None:
    created = runner.invoke(
        cli, ["new", "graph-nets", "--title", "Graph Networks"]
    )
    assert created.exit_code == 0, output_of(created)
    assert "created" in created.output
    assert "paper-handler render" in created.output

    entry = corpus / "papers" / "graph-nets" / "index.qmd"
    assert entry.is_file()
    meta = fm.read(entry)
    assert meta["title"] == "Graph Networks"
    assert meta["format"] == "typst"

    listed = runner.invoke(cli, ["list"])
    assert listed.exit_code == 0
    assert "graph-nets" in listed.output
    assert "Graph Networks" in listed.output
    assert "no" in listed.output  # not yet rendered


def test_list_json(make_paper, runner: CliRunner, corpus: Path) -> None:
    make_paper("alpha", title="Alpha Paper", status="submitted")
    result = runner.invoke(cli, ["list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == [
        {
            "name": "alpha",
            "title": "Alpha Paper",
            "engine": "typst",
            "status": "submitted",
            "rendered": False,
            "entry": str(corpus / "papers" / "alpha" / "index.qmd"),
            "pdf": str(corpus / "papers" / "alpha" / "index.pdf"),
        }
    ]


def test_list_empty_corpus(runner: CliRunner, corpus: Path) -> None:
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "no papers" in result.output
    assert "paper-handler new" in result.output


def test_new_rejects_unknown_template(runner: CliRunner, corpus: Path) -> None:
    result = runner.invoke(cli, ["new", "x", "--template", "nope"])
    assert result.exit_code == 1
    assert "available" in output_of(result)
    assert "typst-article" in output_of(result)


def test_new_rejects_bad_name(runner: CliRunner, corpus: Path) -> None:
    result = runner.invoke(cli, ["new", "Bad Name"])
    assert result.exit_code == 1
    assert "invalid paper name" in output_of(result)


def test_new_refuses_existing(runner: CliRunner, corpus: Path) -> None:
    assert runner.invoke(cli, ["new", "twice"]).exit_code == 0
    clash = runner.invoke(cli, ["new", "twice"])
    assert clash.exit_code == 1
    assert "already exists" in output_of(clash)
    assert runner.invoke(cli, ["new", "twice", "--force"]).exit_code == 0


def test_render_requires_quarto(runner: CliRunner, corpus: Path, no_tools: Path) -> None:
    assert runner.invoke(cli, ["new", "alpha"]).exit_code == 0
    result = runner.invoke(cli, ["render", "papers/alpha"])
    assert result.exit_code == 1
    assert "not on PATH" in output_of(result)


def test_render_all_stops_on_missing_tool(runner: CliRunner, corpus: Path, no_tools: Path) -> None:
    assert runner.invoke(cli, ["new", "alpha"]).exit_code == 0
    result = runner.invoke(cli, ["render", "--all"])
    assert result.exit_code == 1
    assert "not on PATH" in output_of(result)


def test_render_target_and_all_conflict(runner: CliRunner, corpus: Path) -> None:
    result = runner.invoke(cli, ["render", "papers", "--all"])
    assert result.exit_code == 1
    assert "not both" in output_of(result)


def test_render_no_target_and_nothing_here(runner: CliRunner, corpus: Path) -> None:
    result = runner.invoke(cli, ["render"])
    assert result.exit_code == 1
    assert "--all" in output_of(result)


def test_render_all_empty_corpus(runner: CliRunner, corpus: Path) -> None:
    result = runner.invoke(cli, ["render", "--all"])
    assert result.exit_code == 1
    assert "no papers found" in output_of(result)


def test_doctor_without_quarto(runner: CliRunner, no_tools: Path) -> None:
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 1
    assert "quarto is required" in output_of(result)
    assert "MISS" in result.output


def test_doctor_json_without_quarto(runner: CliRunner, no_tools: Path) -> None:
    result = runner.invoke(cli, ["doctor", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert all(p["found"] is False for p in payload["probes"])


def test_templates_list_shows_builtins(runner: CliRunner, corpus: Path) -> None:
    result = runner.invoke(cli, ["templates", "list"])
    assert result.exit_code == 0
    assert "typst-article" in result.output
    assert "latex-article" in result.output
    assert "built-in" in result.output


def test_templates_add_needs_quarto(runner: CliRunner, corpus: Path, no_tools: Path) -> None:
    result = runner.invoke(cli, ["templates", "add", "quarto-journals/acm"])
    assert result.exit_code == 1
    assert "not on PATH" in output_of(result)


def test_outline_json(make_paper, runner: CliRunner, corpus: Path, monkeypatch) -> None:
    directory = make_paper("alpha", title="Alpha")
    monkeypatch.chdir(directory)

    result = runner.invoke(cli, ["outline", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["title"] == "Alpha"
    assert payload["sections"][0]["heading"] == "Introduction"

    text = runner.invoke(cli, ["outline"])
    assert text.exit_code == 0
    assert "Introduction" in text.output


def test_lint_clean_paper_exits_zero(
    make_paper, runner: CliRunner, corpus: Path, monkeypatch
) -> None:
    directory = make_paper("alpha")
    monkeypatch.chdir(directory)

    result = runner.invoke(cli, ["lint"])
    assert result.exit_code == 0, output_of(result)
    assert "0 error(s)" in result.output

    as_json = runner.invoke(cli, ["lint", "--json"])
    payload = json.loads(as_json.output)
    assert payload["errors"] == 0
    assert "readability" in payload


def test_lint_undefined_citation_exits_one(
    make_paper, runner: CliRunner, corpus: Path, monkeypatch
) -> None:
    directory = make_paper("alpha", extra="Cite @missing2020.")
    monkeypatch.chdir(directory)

    result = runner.invoke(cli, ["lint"])
    assert result.exit_code == 1
    assert "undefined-citation" in result.output


def test_meta_get_and_set(make_paper, runner: CliRunner, corpus: Path, monkeypatch) -> None:
    directory = make_paper("alpha", title="Alpha")
    monkeypatch.chdir(directory)

    got = runner.invoke(cli, ["meta", "get", "title"])
    assert got.exit_code == 0
    assert got.output.strip() == "Alpha"

    missing = runner.invoke(cli, ["meta", "get", "nope"])
    assert missing.exit_code == 1
    assert "no 'nope'" in output_of(missing)

    set_result = runner.invoke(cli, ["meta", "set", "status", "submitted"])
    assert set_result.exit_code == 0, output_of(set_result)
    assert fm.read(directory / "index.qmd")["status"] == "submitted"


def test_meta_set_parses_yaml_values(
    make_paper, runner: CliRunner, corpus: Path, monkeypatch
) -> None:
    directory = make_paper("alpha")
    monkeypatch.chdir(directory)

    runner.invoke(cli, ["meta", "set", "volume", "12"])
    assert fm.read(directory / "index.qmd")["volume"] == 12

    runner.invoke(cli, ["meta", "set", "keywords", "[a, b]"])
    assert fm.read(directory / "index.qmd")["keywords"] == ["a", "b"]


def test_meta_get_requires_a_paper(runner: CliRunner, corpus: Path) -> None:
    result = runner.invoke(cli, ["meta", "get", "title"])
    assert result.exit_code == 1
    assert "no paper" in output_of(result)


def test_bib_init_and_check(make_paper, runner: CliRunner, corpus: Path, monkeypatch) -> None:
    directory = make_paper("alpha")
    (directory / "references.bib").unlink()
    monkeypatch.chdir(directory)

    created = runner.invoke(cli, ["bib", "init"])
    assert created.exit_code == 0, output_of(created)
    assert (directory / "references.bib").is_file()

    checked = runner.invoke(cli, ["bib", "check"])
    assert checked.exit_code == 0
    assert "ok" in checked.output


def test_bib_check_reports_problems(
    make_paper, runner: CliRunner, corpus: Path, monkeypatch
) -> None:
    directory = make_paper("alpha")
    monkeypatch.chdir(directory)
    (directory / "references.bib").write_text(
        "@article{a,\n  title = {Unclosed,\n}\n", encoding="utf-8"
    )
    result = runner.invoke(cli, ["bib", "check"])
    assert result.exit_code == 1
    assert "unbalanced braces" in output_of(result)


def test_config_flag_selects_file(runner: CliRunner, corpus: Path, tmp_path: Path) -> None:
    chosen = tmp_path / "alt.toml"
    chosen.write_text('engine = "latex"\npapers_dir = "alt-papers"\n', encoding="utf-8")

    listed = runner.invoke(cli, ["--config", str(chosen), "list"])
    assert listed.exit_code == 0
    assert "alt-papers" in listed.output  # "no papers in <path>" names the dir


def test_env_var_overrides_corpus_config(runner: CliRunner, corpus: Path, monkeypatch) -> None:
    other = corpus / "elsewhere"
    other.mkdir()
    monkeypatch.setenv("PAPER_HANDLER_PAPERS_DIR", str(other))
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert str(other) in result.output


def test_main_entry_renders_domain_errors(no_tools: Path, monkeypatch) -> None:
    """`main()` (the console script) turns domain exceptions into exit 1."""
    monkeypatch.setattr("sys.argv", ["paper-handler", "doctor"])
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 1
