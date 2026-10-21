"""Read and attach a researcher-python handoff bundle.

The two projects share a **file contract**, not a runtime dependency.  A bundle
is written by ``researcher-python handoff`` and contains only the records the
author included (normally ``core`` + ``general``), a BibTeX file whose keys
were assigned in one pass, and a map from DOI/arXiv id or folded title to that
citation key.

A paper keeps the bundle under ``<paper>/research/`` and cites it through a
second bibliography file, so the author's own ``references.bib`` is never
rewritten:

.. code-block:: yaml

    bibliography:
      - references.bib
      - research/references.bib

Nothing here imports ``researcher_python``.  The bundle is validated, copied,
and then read as plain JSON/BibTeX, which keeps the CLI hermetic and makes a
handoff reproducible from a checkout or a CI artifact.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paper_handler import documents, frontmatter

#: Bump only when the bundle shape changes incompatibly.
HANDOFF_SCHEMA_VERSION = 1

#: Files copied into ``<paper>/research/``; ``prisma.md`` is optional.
BUNDLE_FILES = (
    "handoff.json",
    "papers.json",
    "references.bib",
    "citation-map.json",
    "matrix.md",
    "synthesis.md",
    "prisma.md",
    "README.md",
)

_GENERATED_BIB = "research/references.bib"
_MANUAL_BIB = "references.bib"


class ResearchError(ValueError):
    """A handoff bundle is missing, malformed, or too new."""


def _normal_title(value: str) -> str:
    """Match researcher-python's ``normalize_title`` folding exactly."""
    text = str(value or "").lower().replace("&", " and ")
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


@dataclass(frozen=True)
class CitationEntry:
    identifier: str
    title: str
    key: str
    year: int | None
    label: str


@dataclass(frozen=True)
class Handoff:
    """A validated handoff bundle on disk."""

    root: Path
    manifest: dict[str, Any]
    papers: list[dict[str, Any]]
    entries: list[CitationEntry]
    by_id: dict[str, str]
    by_title: dict[str, str]

    @property
    def topic(self) -> str:
        return str(self.manifest.get("topic") or "")

    @property
    def labels(self) -> list[str]:
        raw = self.manifest.get("labels") or []
        return [str(item) for item in raw]

    @property
    def counts(self) -> dict[str, int]:
        raw = self.manifest.get("counts") or {}
        return {str(key): int(value) for key, value in raw.items()}

    @property
    def screening_ready(self) -> bool:
        return bool((self.manifest.get("screening") or {}).get("ready"))

    @property
    def included(self) -> int:
        return int(self.counts.get("included", len(self.papers)))

    def keys(self) -> list[str]:
        return [entry.key for entry in self.entries]

    def key_for(self, identifier: str) -> str | None:
        """Resolve an id, folded title, or an already-known citation key."""
        raw = str(identifier or "").strip()
        if not raw:
            return None
        if raw in set(self.keys()):
            return raw
        if raw in self.by_id:
            return self.by_id[raw]
        return self.by_title.get(_normal_title(raw))


def _bundle_root(path: Path) -> Path:
    """Accept a bundle directory, a handoff.json, or a workspace/handoff dir."""
    path = Path(path).expanduser().resolve()
    if path.is_file() and path.name == "handoff.json":
        return path.parent
    if path.is_dir():
        if (path / "handoff.json").is_file():
            return path
        nested = path / "handoff"
        if (nested / "handoff.json").is_file():
            return nested
    raise ResearchError(
        f"{path}: no handoff.json (run `researcher-python handoff <workspace> --out <dir>`)"
    )


def load_handoff(path: str | Path) -> Handoff:
    """Read and validate a handoff bundle."""
    root = _bundle_root(Path(path))
    manifest_path = root / "handoff.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchError(f"cannot read {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ResearchError(f"{manifest_path}: expected a JSON object")

    version = manifest.get("schema_version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version > HANDOFF_SCHEMA_VERSION
    ):
        raise ResearchError(
            f"{manifest_path}: handoff schema {version!r} is newer than supported "
            f"({HANDOFF_SCHEMA_VERSION}); upgrade paper-handler"
        )

    files = manifest.get("files") or {}
    if not isinstance(files, dict):
        raise ResearchError(f"{manifest_path}: 'files' must be an object")

    def file_for(name: str, fallback: str) -> Path:
        relative = files.get(name) or fallback
        return root / str(relative)

    papers_path = file_for("papers", "papers.json")
    map_path = file_for("citation_map", "citation-map.json")
    bib_path = file_for("bibliography", "references.bib")
    for required in (papers_path, map_path, bib_path):
        if not required.is_file():
            raise ResearchError(f"{root}: missing bundle file {required.name}")

    try:
        envelope = json.loads(papers_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchError(f"cannot read {papers_path}: {exc}") from exc
    if not isinstance(envelope, dict) or not isinstance(envelope.get("papers"), list):
        raise ResearchError(f"{papers_path}: expected an object with a 'papers' list")
    envelope_version = envelope.get("schema_version")
    if (
        not isinstance(envelope_version, bool)
        and isinstance(envelope_version, int)
        and envelope_version > 1
    ):
        raise ResearchError(
            f"{papers_path}: export schema {envelope_version} is newer than supported (1)"
        )

    try:
        citation_map = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchError(f"cannot read {map_path}: {exc}") from exc
    if not isinstance(citation_map, dict):
        raise ResearchError(f"{map_path}: expected a JSON object")

    entries: list[CitationEntry] = []
    for raw in citation_map.get("entries") or []:
        if not isinstance(raw, dict) or not raw.get("key"):
            continue
        entries.append(
            CitationEntry(
                identifier=str(raw.get("id") or ""),
                title=str(raw.get("title") or ""),
                key=str(raw["key"]),
                year=raw.get("year") if isinstance(raw.get("year"), int) else None,
                label=str(raw.get("label") or ""),
            )
        )
    by_id = {
        str(key): str(value)
        for key, value in (citation_map.get("by_id") or {}).items()
    }
    by_title = {
        str(key): str(value)
        for key, value in (citation_map.get("by_title") or {}).items()
    }

    return Handoff(
        root=root,
        manifest=manifest,
        papers=[p for p in envelope["papers"] if isinstance(p, dict)],
        entries=entries,
        by_id=by_id,
        by_title=by_title,
    )


def research_root(paper_dir: Path) -> Path:
    return Path(paper_dir) / "research"


def load_paper_handoff(paper_dir: Path) -> Handoff | None:
    """The handoff attached to a paper, or ``None`` when it has none."""
    root = research_root(paper_dir)
    if not (root / "handoff.json").is_file():
        return None
    return load_handoff(root)


def brief(
    handoff: Handoff,
    *,
    max_papers: int = 10,
    max_keys: int = 60,
) -> dict[str, Any]:
    """A compact evidence brief for a writing model (never the whole bundle)."""
    rank = {"core": 0, "general": 1}
    entries = sorted(
        handoff.entries,
        key=lambda entry: (rank.get(entry.label, 2), -(entry.year or 0), entry.key),
    )
    selected = entries[: max(0, max_papers)]
    keys = handoff.keys()
    return {
        "source": str(handoff.root),
        "topic": handoff.topic,
        "labels": handoff.labels,
        "counts": handoff.counts,
        "screening": {
            "ready": handoff.screening_ready,
            **(handoff.manifest.get("screening") or {}),
        },
        "included": handoff.included,
        "papers": [
            {
                "key": entry.key,
                "title": entry.title,
                "year": entry.year,
                "label": entry.label,
            }
            for entry in selected
        ],
        "keys": keys[: max(0, max_keys)],
        "key_count": len(keys),
        "next": (
            "Use these citation keys in paper_write_section; call paper_cite_key "
            "for an id/title not listed."
        ),
    }


def _set_bibliography(entry: Path) -> list[str]:
    """Ensure the front matter lists the manual and generated bibliographies."""
    meta = frontmatter.read(entry)
    existing = meta.get("bibliography")
    if isinstance(existing, str):
        paths = [existing]
    elif isinstance(existing, list):
        paths = [str(item) for item in existing]
    else:
        paths = []
    for required in (_MANUAL_BIB, _GENERATED_BIB):
        if required not in paths:
            paths.append(required)
    meta["bibliography"] = paths
    meta.setdefault("status", "draft")
    frontmatter.write(entry, meta)
    return paths


def _readme(handoff: Handoff) -> str:
    counts = handoff.counts
    screening = "ready" if handoff.screening_ready else "incomplete"
    return f"""\
# Research handoff

Attached from `{handoff.root}`.

- Topic: {handoff.topic or "(not set)"}
- Included labels: {", ".join(handoff.labels) or "(none)"}
- Screening: {screening}
- Included: {counts.get("included", handoff.included)} of {counts.get("records", "?")} records

`references.bib` and `citation-map.json` are generated by researcher-python;
do not edit them. Re-run the handoff and `paper-handler research sync` instead.
The author's own bibliography remains `../references.bib`.
"""


def attach_to_paper(paper_dir: Path, handoff: Handoff) -> dict[str, Any]:
    """Copy a bundle into ``<paper>/research/`` and wire the bibliographies.

    The manual ``references.bib`` is never overwritten.  Generated files are
    replaced, so re-import/sync is idempotent.
    """
    paper_dir = Path(paper_dir)
    entry = paper_dir / "index.qmd"
    if not entry.is_file():
        entry = paper_dir / "main.qmd"
    if not entry.is_file():
        raise ResearchError(f"{paper_dir}: no index.qmd or main.qmd found")

    target = research_root(paper_dir)
    target.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in BUNDLE_FILES:
        source = handoff.root / name
        if source.is_file():
            shutil.copyfile(source, target / name)
            copied.append(name)
    (target / "README.md").write_text(_readme(handoff), encoding="utf-8")
    if "README.md" not in copied:
        copied.append("README.md")

    manual = paper_dir / _MANUAL_BIB
    if not manual.exists():
        manual.write_text(
            "% references.bib — your own entries.\n"
            "% The researcher handoff is generated separately in research/references.bib.\n",
            encoding="utf-8",
        )
    bibliography = _set_bibliography(entry)

    return {
        "ok": True,
        "paper": paper_dir.name,
        "research": str(target),
        "included": handoff.included,
        "keys": len(handoff.keys()),
        "bibliography": bibliography,
        "files": copied,
    }


def append_prisma(
    paper_dir: Path,
    *,
    heading: str = "Screening",
    level: int = 2,
    after: str | None = None,
) -> dict[str, Any]:
    """Insert (or replace) an appendix that includes the generated PRISMA report.

    The report itself stays in ``research/prisma.md``; the manuscript only
    carries a Quarto include, so the flow can be regenerated without touching
    the prose.  Rendering is the caller's job.
    """
    paper_dir = Path(paper_dir)
    handoff = load_paper_handoff(paper_dir)
    if handoff is None:
        raise ResearchError(f"{paper_dir}: no research/handoff.json attached")
    report = research_root(paper_dir) / "prisma.md"
    if not report.is_file():
        raise ResearchError(
            f"{paper_dir}: research/prisma.md is missing (re-run the handoff with PRISMA)"
        )

    entry = paper_dir / "index.qmd"
    if not entry.is_file():
        entry = paper_dir / "main.qmd"
    if not entry.is_file():
        raise ResearchError(f"{paper_dir}: no index.qmd or main.qmd found")

    text = entry.read_text(encoding="utf-8")
    include = "{{< include research/prisma.md >}}"
    try:
        documents.find_section(documents.parse_sections(text), heading, level)
    except documents.DocumentError:
        updated = documents.insert_section(
            text, heading, include, level=level, after=after
        )
        action = "insert"
    else:
        updated = documents.replace_section(text, heading, include, level)
        action = "replace"
    entry.write_text(updated, encoding="utf-8")
    return {
        "ok": True,
        "paper": paper_dir.name,
        "heading": heading,
        "action": action,
        "include": "research/prisma.md",
        "sections": documents.outline(updated)["sections"],
    }
