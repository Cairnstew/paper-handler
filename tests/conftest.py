"""Shared fixtures.

Every test runs with config discovery sandboxed: no ``/etc`` layer, an
``XDG_CONFIG_HOME`` inside the test's own ``tmp_path``, and no
``PAPER_HANDLER_*`` variables leaking in from the ambient shell.  Without that,
a developer's real corpus settings (or a host where the NixOS module is
enabled) would silently change test behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from paper_handler import config as config_mod

_ENV_VARS = (
    config_mod.ENV_ENGINE,
    config_mod.ENV_PAPERS_DIR,
    config_mod.ENV_TEMPLATES_DIR,
    config_mod.ENV_CONFIG,
)


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Sandbox config discovery.  Returns the fake XDG config directory."""
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    # Only the XDG layer, never /etc — the latter exists on hosts where the
    # module is enabled, and would make these tests machine-dependent.
    user_config = xdg / "paper-handler" / "config.toml"
    monkeypatch.setattr(config_mod, "_default_config_paths", lambda: [user_config])
    return xdg


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_config: Path) -> Path:
    """A ready-made corpus that is also the working directory."""
    root = tmp_path / "corpus"
    (root / "papers").mkdir(parents=True)
    (root / "paper-handler.toml").write_text(
        'engine = "typst"\npapers_dir = "papers"\n', encoding="utf-8"
    )
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def no_tools(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A PATH with nothing on it, so tool lookups deterministically fail."""
    empty = tmp_path / "no-bin"
    empty.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty))
    return empty


@pytest.fixture
def make_paper(corpus: Path):
    """Factory: drop a paper directory with front matter into the corpus."""

    def _make(
        name: str = "sample",
        *,
        title: str = "A Sample Paper",
        engine: str = "typst",
        status: str = "draft",
        extra: str = "",
    ) -> Path:
        directory = corpus / "papers" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "index.qmd").write_text(
            "---\n"
            f"title: \"{title}\"\n"
            f"format: {'typst' if engine in ('typst', 'both') else 'pdf'}\n"
            f"status: {status}\n"
            "---\n\n"
            "## Introduction\n\nBody.\n"
            f"{extra}",
            encoding="utf-8",
        )
        (directory / "references.bib").write_text(
            "@article{a2024,\n  author = {A},\n  title = {T},\n  year = {2024},\n}\n",
            encoding="utf-8",
        )
        return directory

    return _make
