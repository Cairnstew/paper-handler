"""How ``render`` invokes Quarto — command shape, working directory, stopping."""

from __future__ import annotations

from pathlib import Path

import pytest

from paper_handler import project
from paper_handler import render as render_mod
from paper_handler.project import Paper
from paper_handler.render import RenderError, render_many, render_paper, render_path
from paper_handler.toolchain import ToolchainError

QUARTO = "/nix/store/eeee-quarto/bin/quarto"


class _Result:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode


@pytest.fixture
def fake_quarto(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Record `quarto render` invocations instead of running Quarto."""
    calls: list[dict] = []
    codes: list[int] = []

    monkeypatch.setattr(render_mod, "require", lambda name: QUARTO)

    def fake_run(command, cwd=None, check=False):  # noqa: ANN001 - mirrors subprocess
        calls.append({"command": command, "cwd": cwd})
        return _Result(codes.pop(0) if codes else 0)

    monkeypatch.setattr(render_mod.subprocess, "run", fake_run)
    return {"calls": calls, "codes": codes}


def test_command_shape_and_cwd(make_paper, corpus: Path, fake_quarto: dict) -> None:
    directory = make_paper("alpha")
    paper = project.discover(corpus / "papers")[0]

    assert render_paper(paper, engine="latex", extra_args=("--quiet",)) == 0

    (call,) = fake_quarto["calls"]
    assert call["command"] == [QUARTO, "render", "index.qmd", "--to", "pdf", "--quiet"]
    # cwd is the paper directory, so `bibliography: references.bib` resolves.
    assert call["cwd"] == directory


@pytest.mark.parametrize(
    ("engine", "fmt"),
    [("typst", "typst"), ("both", "typst"), ("latex", "pdf")],
)
def test_engine_maps_to_quarto_format(
    make_paper, corpus: Path, fake_quarto: dict, engine: str, fmt: str
) -> None:
    make_paper("alpha")
    paper = project.discover(corpus / "papers")[0]
    render_paper(paper, engine=engine)
    assert fake_quarto["calls"][0]["command"][4] == fmt  # [quarto, render, name, --to, FMT]


def test_missing_entry_raises(make_paper, corpus: Path) -> None:
    # Discover first, then delete the entry: a paper whose document vanished
    # after being indexed must not silently succeed.
    paper = project.discover(corpus / "papers" / make_paper("alpha").name)[0]
    paper.entry.unlink()
    with pytest.raises(RenderError, match="does not exist"):
        render_paper(paper, engine="typst")


def test_missing_quarto_raises(make_paper, corpus: Path, no_tools: Path) -> None:
    make_paper("alpha")
    paper = project.discover(corpus / "papers")[0]
    with pytest.raises(ToolchainError, match="not on PATH"):
        render_paper(paper, engine="typst")


def test_render_many_stops_at_first_failure(make_paper, corpus: Path, fake_quarto: dict) -> None:
    for name in ("one", "two", "three"):
        make_paper(name)
    papers = project.discover(corpus / "papers")

    fake_quarto["codes"][:] = [1]
    report = render_many(papers, engine="typst")
    assert report.failed == [papers[0]]
    assert len(fake_quarto["calls"]) == 1  # stopped

    fake_quarto["calls"].clear()
    fake_quarto["codes"][:] = [1, 0, 0]
    report = render_many(papers, engine="typst", keep_going=True)
    assert [p.name for p in report.failed] == ["one"]
    assert [p.name for p in report.succeeded] == ["three", "two"]  # sorted by name
    assert len(fake_quarto["calls"]) == 3


def test_render_path_accepts_directory_and_file(
    make_paper, corpus: Path, fake_quarto: dict
) -> None:
    directory = make_paper("alpha")
    assert render_path(directory, engine="typst") == 0
    assert render_path(directory / "index.qmd", engine="typst") == 0
    assert len(fake_quarto["calls"]) == 2


def test_render_path_rejects_missing_and_empty(tmp_path: Path) -> None:
    with pytest.raises(RenderError, match="no such file"):
        render_path(tmp_path / "nope", engine="typst")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(RenderError, match="no index.qmd"):
        render_path(empty, engine="typst")


def test_render_report_counts() -> None:
    report = render_mod.RenderReport()
    assert report.ok and report.count == 0
    paper = Paper("x", Path("/x"), Path("/x/index.qmd"), "X", "typst", "draft")
    report.succeeded.append(paper)
    assert report.ok and report.count == 1
    report.failed.append(paper)
    assert not report.ok and report.count == 2
