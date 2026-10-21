"""Layered config discovery: /etc < XDG < project < --config < environment."""

from __future__ import annotations

from pathlib import Path

import pytest

from paper_handler.config import (
    Config,
    ConfigError,
    load_config,
    resolve_papers_dir,
)


def test_defaults() -> None:
    config = Config()
    assert config.engine == "typst"
    assert config.papers_dir is None
    assert config.source is None
    assert config.effective_templates_dir is None


def test_invalid_engine_rejected() -> None:
    with pytest.raises(ConfigError, match="engine must be one of"):
        Config(engine="latexmk")


def test_templates_dir_defaults_inside_corpus(tmp_path: Path) -> None:
    config = Config(papers_dir=tmp_path / "papers")
    assert config.effective_templates_dir == tmp_path / "papers" / ".templates"


def test_explicit_templates_dir_wins(tmp_path: Path) -> None:
    config = Config(papers_dir=tmp_path / "papers", templates_dir=tmp_path / "tpl")
    assert config.effective_templates_dir == tmp_path / "tpl"


def test_project_file_discovered_by_walking_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "corpus"
    deep = root / "papers" / "alpha" / "figures"
    deep.mkdir(parents=True)
    (root / "paper-handler.toml").write_text('engine = "latex"\n', encoding="utf-8")
    monkeypatch.chdir(deep)

    assert load_config().engine == "latex"


def test_nearest_project_file_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outer = tmp_path / "outer"
    inner = outer / "inner"
    inner.mkdir(parents=True)
    (outer / "paper-handler.toml").write_text('engine = "latex"\n', encoding="utf-8")
    (inner / "paper-handler.toml").write_text('engine = "typst"\n', encoding="utf-8")
    monkeypatch.chdir(inner)

    assert load_config().engine == "typst"


def test_relative_paths_anchor_at_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "paper-handler.toml").write_text('papers_dir = "corpus-papers"\n', encoding="utf-8")
    # Invoke from somewhere else entirely: the path must still mean "relative
    # to the config file", not "relative to $PWD".
    monkeypatch.chdir(tmp_path)

    config = load_config(cwd=root)
    assert config.papers_dir == (root / "corpus-papers").resolve()


def test_xdg_layer_applies(
    tmp_path: Path, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = isolated_config / "paper-handler" / "config.toml"
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text('engine = "latex"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert load_config().engine == "latex"


def test_project_overrides_xdg(
    tmp_path: Path, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = isolated_config / "paper-handler" / "config.toml"
    user.parent.mkdir(parents=True, exist_ok=True)
    user.write_text('engine = "latex"\n', encoding="utf-8")

    (tmp_path / "paper-handler.toml").write_text('engine = "typst"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert load_config().engine == "typst"


def test_environment_overrides_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "paper-handler.toml").write_text('engine = "typst"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PAPER_HANDLER_ENGINE", "latex")
    monkeypatch.setenv("PAPER_HANDLER_PAPERS_DIR", str(tmp_path / "elsewhere"))

    config = load_config()
    assert config.engine == "latex"
    assert config.papers_dir == tmp_path / "elsewhere"


def test_explicit_config_path_short_circuits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "paper-handler.toml").write_text('engine = "typst"\n', encoding="utf-8")
    chosen = tmp_path / "chosen.toml"
    chosen.write_text('engine = "latex"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert load_config(config_path=chosen).engine == "latex"


def test_missing_explicit_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="no such config file"):
        load_config(config_path=tmp_path / "nope.toml")


def test_environment_overrides_explicit_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--config` replaces discovery, not the documented top layer."""
    chosen = tmp_path / "chosen.toml"
    chosen.write_text('engine = "latex"\n', encoding="utf-8")
    monkeypatch.setenv("PAPER_HANDLER_ENGINE", "typst")

    assert load_config(config_path=chosen).engine == "typst"


def test_unknown_keys_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "paper-handler.toml").write_text(
        'engine = "typst"\nnot_a_real_key = 1\n', encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    assert load_config().engine == "typst"


def test_malformed_toml_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "paper-handler.toml").write_text("engine = \n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="cannot read"):
        load_config()


def test_write_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "paper-handler.toml"
    Config(engine="latex", papers_dir=Path("papers"), templates_dir=Path("tpl")).write(path)
    assert path.is_file()

    reloaded = load_config(config_path=path)
    assert reloaded.engine == "latex"
    # Round-tripping through a file resolves relative paths against that file.
    assert reloaded.papers_dir == (path.parent / "papers").resolve()
    assert reloaded.templates_dir == (path.parent / "tpl").resolve()


def test_resolve_papers_dir_prefers_override(tmp_path: Path) -> None:
    config = Config(papers_dir=tmp_path / "configured")
    assert resolve_papers_dir(config, tmp_path / "override") == (tmp_path / "override").resolve()


def test_resolve_papers_dir_falls_back_to_papers_beside_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "paper-handler.toml").write_text('engine = "typst"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert resolve_papers_dir(Config()) == (tmp_path / "papers").resolve()
