"""YAML front matter parsing and rewriting for ``.qmd`` files.

Only the front matter block is touched; the document body is passed through
byte-for-byte.  Because PyYAML does not retain comments, rewriting a block
drops comments *inside* the front matter — body comments are unaffected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

OPEN = "---"
CLOSE = ("---", "...")


class FrontMatterError(ValueError):
    """A document's front matter was malformed."""


def _delimiter(line: str) -> str:
    """A line with its newline removed.  Delimiters must start at column 0.

    Quarto/Pandoc only recognise ``---`` at the very start of the file, so
    ``----``, ``---foo`` and `` ---`` are ordinary text — ``strip()`` here
    would be too permissive.
    """
    return line.rstrip("\r\n")


def split(text: str) -> tuple[str, str]:
    """Split *text* into ``(front_matter_block, body)``.

    The block includes its opening and closing delimiters.  When the document
    has no front matter the block is ``""`` and the whole text is the body.
    """
    lines = text.splitlines(keepends=True)
    if not lines or _delimiter(lines[0]) != OPEN:
        return "", text
    for index in range(1, len(lines)):
        if _delimiter(lines[index]) in CLOSE:
            return "".join(lines[: index + 1]), "".join(lines[index + 1 :])
    raise FrontMatterError("front matter opened with '---' but never closed")


def parse(text: str) -> dict[str, Any]:
    """Return the front matter mapping, or ``{}`` when there is none."""
    block, _ = split(text)
    if not block:
        return {}
    body = block.splitlines()[1:-1]
    data = yaml.safe_load("\n".join(body))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise FrontMatterError(f"front matter must be a mapping, got {type(data).__name__}")
    return data


def render(meta: dict[str, Any]) -> str:
    """Serialise *meta* as a complete delimited front matter block."""
    dumped = yaml.safe_dump(
        meta,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).rstrip("\n")
    return f"{OPEN}\n{dumped}\n{OPEN}\n"


def replace(text: str, meta: dict[str, Any]) -> str:
    """Return *text* with its front matter replaced by *meta*.

    A document that had no front matter gains one, with the original body
    preserved beneath it.
    """
    _, body = split(text)
    return render(meta) + body


def read(path: Path) -> dict[str, Any]:
    """Parse the front matter of the file at *path*."""
    return parse(Path(path).read_text(encoding="utf-8"))


def write(path: Path, meta: dict[str, Any]) -> Path:
    """Replace the front matter of the file at *path* in place."""
    path = Path(path)
    path.write_text(replace(path.read_text(encoding="utf-8"), meta), encoding="utf-8")
    return path
