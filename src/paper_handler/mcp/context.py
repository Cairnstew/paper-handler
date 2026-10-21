"""Shared helpers for MCP tools: config, paper lookup, and compact output."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paper_handler import project
from paper_handler.config import Config, load_config, resolve_papers_dir
from paper_handler.project import Paper


class ToolError(RuntimeError):
    """A tool was called with unusable input; surfaced as ``isError``."""


@dataclass(frozen=True)
class Session:
    config: Config
    corpus: Path

    @property
    def root(self) -> Path:
        """The directory that contains ``papers/`` (used for short paths)."""
        return self.corpus.parent


def session() -> Session:
    if _SESSION_CORPUS is not None:
        return Session(config=Config(papers_dir=_SESSION_CORPUS), corpus=_SESSION_CORPUS)
    config = load_config()
    return Session(config=config, corpus=resolve_papers_dir(config))


#: An explicit corpus chosen by ``paper_open_corpus`` for a long-lived server.
#: Without it a global MCP registration only works when launched from a corpus
#: root, which is not true for an editor or a vault.
_SESSION_CORPUS: Path | None = None


def open_corpus(path: str | Path) -> Session:
    """Pin the session corpus, resolving a corpus root or a papers directory."""
    global _SESSION_CORPUS
    target = Path(path).expanduser().resolve()
    if not target.is_dir():
        raise ToolError(f"{target}: not a directory")

    if (target / "paper-handler.toml").is_file():
        config = load_config(cwd=target)
        corpus = resolve_papers_dir(config)
    elif (target / "papers").is_dir():
        corpus = (target / "papers").resolve()
        config = Config(papers_dir=corpus)
    else:
        corpus = target
        config = Config(papers_dir=corpus)
    _SESSION_CORPUS = corpus
    return Session(config=config, corpus=corpus)


def close_corpus() -> None:
    global _SESSION_CORPUS
    _SESSION_CORPUS = None


def rel(path: Path, session_: Session) -> str:
    """A corpus-relative path, to keep responses short."""
    try:
        return str(Path(path).resolve().relative_to(session_.root.resolve()))
    except ValueError:
        return str(path)


def paper(name: str, session_: Session | None = None) -> Paper:
    """Resolve a paper by name, entry file, or corpus-relative directory."""
    session_ = session_ or session()
    raw = str(name or "").strip()
    if not raw:
        raise ToolError("paper name is required")

    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        candidates = [candidate]
    else:
        # Accept a bare name (`example`), a corpus-relative path
        # (`papers/example`), or a path from the current directory.
        candidates = [session_.corpus / candidate, session_.root / candidate, candidate]
    resolved_candidate = next((path for path in candidates if path.exists()), None)
    if resolved_candidate is None:
        raise ToolError(f"no paper named {raw!r} in {session_.corpus}")

    resolved = resolved_candidate.resolve()
    try:
        resolved.relative_to(session_.corpus.resolve())
    except ValueError as exc:
        raise ToolError(f"{raw!r} is outside the corpus") from exc

    try:
        return project.locate(resolved, session_.corpus)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def paper_or_single(name: str | None, session_: Session | None = None) -> Paper:
    """Use *name* when given, else the only paper in the corpus."""
    if name:
        return paper(name, session_)
    session_ = session_ or session()
    papers = project.discover(session_.corpus)
    if len(papers) == 1:
        return papers[0]
    if not papers:
        raise ToolError(f"no papers in {session_.corpus}")
    names = ", ".join(p.name for p in papers)
    raise ToolError(f"paper name is required (corpus has: {names})")


def text_of(paper_: Paper) -> str:
    try:
        return paper_.entry.read_text(encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"cannot read {paper_.entry}: {exc}") from exc


def bib_path(paper_: Paper) -> Path | None:
    candidate = paper_.dir / "references.bib"
    return candidate if candidate.is_file() else None


def bib_paths(paper_: Paper) -> list[Path]:
    """Every bibliography a paper may cite: manual first, generated second."""
    candidates = (
        paper_.dir / "references.bib",
        paper_.dir / "research" / "references.bib",
    )
    return [path for path in candidates if path.is_file()]


def compact(data: Any) -> str:
    """The one serialisation used for tool text content."""
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False, default=str)


def truncate(text: str, max_tokens: int | None) -> tuple[str, bool]:
    """Trim *text* to roughly *max_tokens* (4 characters per token)."""
    if max_tokens is None or max_tokens <= 0:
        return text, False
    limit = max_tokens * 4
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    boundary = max(cut.rfind("\n"), cut.rfind(" "))
    if boundary > limit // 2:
        cut = cut[:boundary]
    return cut.rstrip() + "\n… [truncated]", True


def str_arg(
    args: Mapping[str, Any],
    key: str,
    *,
    default: str | None = None,
    required: bool = False,
) -> str:
    value = args.get(key, default)
    if value is None or value == "":
        if required:
            raise ToolError(f"{key} is required")
        return ""
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value


def bool_arg(args: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = args.get(key, default)
    if not isinstance(value, bool):
        raise ToolError(f"{key} must be a boolean")
    return value


def int_arg(
    args: Mapping[str, Any], key: str, default: int | None = None
) -> int | None:
    value = args.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{key} must be an integer")
    return value
