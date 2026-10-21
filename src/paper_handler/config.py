"""Configuration discovery for paper-handler.

Layers are applied lowest-precedence first, so the last one applied wins:

1. ``/etc/paper-handler/config.toml`` — written by the NixOS module.
2. ``$XDG_CONFIG_HOME/paper-handler/config.toml`` (default ``~/.config``) —
   written by the Home Manager module.
3. ``paper-handler.toml`` found by walking *up* from the working directory.
   The nearest one wins, which is how a corpus carries its own settings with
   no global state.
4. An explicit file named by ``PAPER_HANDLER_CONFIG``.
5. The individual ``PAPER_HANDLER_*`` environment variables.

Relative paths are resolved against the directory of the file they came from
(so a corpus that says ``papers_dir = "papers"`` keeps meaning that wherever
you invoke the CLI from inside it), and against the working directory when
they came from an environment variable.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import tomli_w

#: Values accepted by ``engine``.
ENGINES: tuple[str, ...] = ("typst", "latex", "both")

#: Typst is the default: fast compilation, good error messages, and the small
#: closure.  Flip to ``latex`` for journal templates that ship LaTeX classes.
DEFAULT_ENGINE = "typst"

#: Per-corpus config filename.
PROJECT_FILE = "paper-handler.toml"

#: Environment variables that override every config file layer.
ENV_ENGINE = "PAPER_HANDLER_ENGINE"
ENV_PAPERS_DIR = "PAPER_HANDLER_PAPERS_DIR"
ENV_TEMPLATES_DIR = "PAPER_HANDLER_TEMPLATES_DIR"
ENV_CONFIG = "PAPER_HANDLER_CONFIG"

_PATH_KEYS = ("papers_dir", "templates_dir")
_STRING_KEYS = ("engine",)


class ConfigError(ValueError):
    """A config file or environment variable was invalid."""


@dataclass(frozen=True)
class Config:
    """Resolved paper-handler settings."""

    engine: str = DEFAULT_ENGINE
    papers_dir: Path | None = None
    templates_dir: Path | None = None
    #: The file the deepest file layer came from, for diagnostics.
    source: Path | None = None

    def __post_init__(self) -> None:
        if self.engine not in ENGINES:
            raise ConfigError(f"engine must be one of {', '.join(ENGINES)}; got {self.engine!r}")

    @property
    def effective_templates_dir(self) -> Path | None:
        """``templates_dir`` when set, else ``<papers_dir>/.templates``."""
        if self.templates_dir is not None:
            return self.templates_dir
        if self.papers_dir is not None:
            return self.papers_dir / ".templates"
        return None

    def write(self, path: Path) -> Path:
        """Write this config to *path* as TOML, creating parent directories."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {"engine": self.engine}
        for key in _PATH_KEYS:
            value = getattr(self, key)
            if value is not None:
                payload[key] = str(value)
        path.write_text(tomli_w.dumps(payload), encoding="utf-8")
        return path


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a TOML table at the top level")
    return data


def _find_project_file(start: Path) -> Path | None:
    """Walk *start* and its parents looking for ``paper-handler.toml``."""
    current = start.resolve()
    for directory in (current, *current.parents):
        candidate = directory / PROJECT_FILE
        if candidate.is_file():
            return candidate
    return None


def _default_config_paths() -> list[Path]:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    config_home = Path(xdg) if xdg else Path.home() / ".config"
    return [
        Path("/etc/paper-handler/config.toml"),
        config_home / "paper-handler" / "config.toml",
    ]


def _apply_layer(config: Config, data: Mapping[str, Any], source: Path, base: Path) -> Config:
    """Merge one TOML layer onto *config*.  Unknown keys are ignored."""
    updates: dict[str, Any] = {}
    for key in _STRING_KEYS + _PATH_KEYS:
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, str):
            raise ConfigError(f"{source}: {key} must be a string, got {type(value).__name__}")
        if key in _PATH_KEYS:
            path_value = Path(value).expanduser()
            # Relative paths are anchored at the config file, not at $PWD, so a
            # corpus stays self-describing no matter where you invoke it from.
            path_value = path_value if path_value.is_absolute() else (base / path_value)
            updates[key] = path_value.resolve()
        else:
            updates[key] = value
    return replace(config, **updates, source=source)


def load_config(
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    config_path: Path | None = None,
) -> Config:
    """Resolve the effective :class:`Config`.

    *config_path* (or ``PAPER_HANDLER_CONFIG``) short-circuits file discovery
    entirely, which is what the CLI's ``--config`` flag does.
    """
    environ = os.environ if env is None else env

    explicit = config_path or (Path(environ[ENV_CONFIG]) if environ.get(ENV_CONFIG) else None)
    if explicit is not None:
        explicit = Path(explicit)
        if not explicit.is_file():
            raise ConfigError(f"{explicit}: no such config file")
        # Short-circuit *discovery* only: the file replaces /etc, XDG and the
        # corpus walk, but the PAPER_HANDLER_* variables still outrank it, as
        # the precedence list above promises.
        config = _apply_layer(Config(), _read_toml(explicit), explicit, explicit.parent)
    else:
        config = Config()
        for path in _default_config_paths():
            if path.is_file():
                config = _apply_layer(config, _read_toml(path), path, path.parent)

        project_file = _find_project_file(Path.cwd() if cwd is None else cwd)
        if project_file is not None:
            config = _apply_layer(
                config, _read_toml(project_file), project_file, project_file.parent
            )

    # Environment wins over every file layer.  `replace` re-runs
    # __post_init__, so a bad PAPER_HANDLER_ENGINE still raises ConfigError.
    if environ.get(ENV_ENGINE):
        config = replace(config, engine=environ[ENV_ENGINE])
    if environ.get(ENV_PAPERS_DIR):
        config = replace(config, papers_dir=Path(environ[ENV_PAPERS_DIR]).expanduser())
    if environ.get(ENV_TEMPLATES_DIR):
        config = replace(config, templates_dir=Path(environ[ENV_TEMPLATES_DIR]).expanduser())
    return config


def resolve_papers_dir(config: Config, override: Path | None = None) -> Path:
    """The corpus directory to operate on.  Creates nothing along the way."""
    if override is not None:
        return Path(override).expanduser().resolve()
    if config.papers_dir is not None:
        return config.papers_dir.resolve()
    # Last resort: a `papers/` directory beside the corpus config, or in $PWD.
    project_file = _find_project_file(Path.cwd())
    anchor = project_file.parent if project_file is not None else Path.cwd()
    return (anchor / "papers").resolve()
