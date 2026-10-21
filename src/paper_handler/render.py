"""Driving ``quarto render``.

Every render runs with the *paper's own directory* as the working directory
rather than the corpus root.  That makes every relative path in a paper —
``bibliography``, ``include``, ``fig-path`` — resolve the way an author
reading the file expects, independent of where the CLI was invoked from.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from paper_handler.project import ENGINE_TO_FORMAT, Paper
from paper_handler.toolchain import ToolchainError, require


class RenderError(RuntimeError):
    """Quarto itself failed (as opposed to a missing tool)."""


@dataclass
class RenderReport:
    """Outcome of one or more renders."""

    succeeded: list[Paper] = field(default_factory=list)
    failed: list[Paper] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def count(self) -> int:
        return len(self.succeeded) + len(self.failed)


def _command(entry_name: str, engine: str, extra_args: tuple[str, ...]) -> list[str]:
    quarto = require("quarto")
    # `--to` pins the output format so a paper whose front matter says `pdf`
    # can still be rendered to Typst (and vice versa) without editing it.
    return [quarto, "render", entry_name, "--to", ENGINE_TO_FORMAT[engine], *extra_args]


def render_paper(paper: Paper, *, engine: str, extra_args: tuple[str, ...] = ()) -> int:
    """Render one paper.  Returns Quarto's exit status (0 means success)."""
    if not paper.entry.is_file():
        raise RenderError(f"{paper.entry} does not exist")
    try:
        command = _command(paper.entry.name, engine, extra_args)
    except ToolchainError:
        raise
    completed = subprocess.run(command, cwd=paper.dir, check=False)
    return completed.returncode


def render_captured(
    paper: Paper, *, engine: str, extra_args: tuple[str, ...] = ()
) -> tuple[int, str, str]:
    """Render one paper with stdout/stderr captured.

    The MCP server must never let Quarto write to its own stdout — that stream
    *is* the protocol.  The CLI keeps using :func:`render_paper`, which streams
    progress to the terminal.
    """
    if not paper.entry.is_file():
        raise RenderError(f"{paper.entry} does not exist")
    command = _command(paper.entry.name, engine, extra_args)
    completed = subprocess.run(
        command,
        cwd=paper.dir,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode, completed.stdout or "", completed.stderr or ""


def render_many(
    papers: list[Paper],
    *,
    engine: str,
    extra_args: tuple[str, ...] = (),
    keep_going: bool = False,
) -> RenderReport:
    """Render *papers* in order, stopping at the first failure unless asked not to."""
    report = RenderReport()
    for paper in papers:
        status = render_paper(paper, engine=engine, extra_args=extra_args)
        if status == 0:
            report.succeeded.append(paper)
        else:
            report.failed.append(paper)
            if not keep_going:
                break
    return report


def render_path(path, *, engine: str, extra_args: tuple[str, ...] = (), papers_dir=None) -> int:
    """Render an explicit file or directory that may not be in the corpus index."""
    from pathlib import Path

    from paper_handler.project import find_entry

    target = Path(path)
    if target.is_dir():
        entry = find_entry(target)
        if entry is None:
            raise RenderError(f"{target}: no index.qmd or main.qmd found")
        paper = Paper(
            name=target.name,
            dir=target,
            entry=entry,
            title=target.name,
            engine=engine,
            status="draft",
        )
    elif target.is_file():
        paper = Paper(
            name=target.stem,
            dir=target.parent,
            entry=target,
            title=target.stem,
            engine=engine,
            status="draft",
        )
    else:
        raise RenderError(f"{target}: no such file or directory")
    return render_paper(paper, engine=engine, extra_args=extra_args)
