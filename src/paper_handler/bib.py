"""BibTeX helpers: starting a ``references.bib`` and sanity-checking one.

Deliberately not a BibTeX parser — validate only what breaks renders silently
or confusingly (unbalanced braces, duplicate keys, empty keys) rather than
trying to model the format.
"""

from __future__ import annotations

import re
from pathlib import Path

#: `@type{key,` — the only shape we need to recognise to find keys.
_ENTRY = re.compile(r"^\s*@\w+\s*\{\s*([^,\s{}]*)\s*,", re.MULTILINE)

STARTER = """\
% references.bib — started by `paper-handler bib init`.
% Add entries in BibTeX form; cite them in a .qmd with [@key].

@article{doe2024,
  author  = {Doe, Jane and Roe, Richard},
  title   = {An Example of Reproducible Academic Writing},
  journal = {Journal of Placeholder Results},
  year    = {2024},
  volume  = {12},
  pages   = {1--18},
  doi     = {10.0000/example},
}
"""


class BibError(RuntimeError):
    """The bibliography could not be read or created."""


def init(path: Path, *, overwrite: bool = False) -> Path:
    """Create a starter ``references.bib`` at *path*."""
    path = Path(path)
    if path.exists() and not overwrite:
        raise BibError(f"{path} already exists (pass --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(STARTER, encoding="utf-8")
    return path


def keys(path: Path) -> list[str]:
    """Every citation key in *path*, in order of appearance."""
    return _ENTRY.findall(Path(path).read_text(encoding="utf-8"))


def check(path: Path) -> list[str]:
    """Return a list of problems; an empty list means the file looks usable."""
    path = Path(path)
    if not path.is_file():
        return [f"{path}: no such file"]

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{path}: not readable as text ({exc})"]

    problems: list[str] = []
    if not text.strip():
        return [f"{path}: file is empty"]

    # Brace balance is checked outside comments and strings; a naive count is
    # enough here because BibTeX itself is brace-counting too.
    stripped = "\n".join(
        line.split("%", 1)[0] for line in text.splitlines()
    )
    opens, closes = stripped.count("{"), stripped.count("}")
    if opens != closes:
        problems.append(f"{path}: unbalanced braces ({opens} '{{' vs {closes} '}}')")

    found = _ENTRY.findall(text)
    if not found:
        problems.append(f"{path}: no @type{{key, ...}} entries found")

    seen: dict[str, int] = {}
    for key in found:
        if not key:
            problems.append(f"{path}: an entry has an empty citation key")
            continue
        seen[key] = seen.get(key, 0) + 1
    for key, count in sorted(seen.items()):
        if count > 1:
            problems.append(f"{path}: duplicate citation key {key!r} ({count} times)")

    return problems
