"""Toolchain discovery and the ``doctor`` report.

The Nix side ships a single derivation (``nix/toolchain.nix``) with everything
``quarto render`` needs on PATH; this module only *observes* what is actually
there, so it works identically inside the Nix dev shell, a bare virtualenv, or
a system install with the distro's Quarto.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass

#: (label, executable, version-args) — order is report order.
PROBES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("quarto", "quarto", ("--version",)),
    ("pandoc", "pandoc", ("--version",)),
    ("typst", "typst", ("--version",)),
    ("pdflatex", "pdflatex", ("--version",)),
    ("lualatex", "lualatex", ("--version",)),
    ("latexmk", "latexmk", ("--version",)),
    ("jupyter", "jupyter", ("--version",)),
    ("python", "python", ("--version",)),
)


@dataclass(frozen=True)
class Probe:
    """One line of the doctor report."""

    name: str
    found: bool
    detail: str


class ToolchainError(RuntimeError):
    """A required tool is missing or failed to run."""


def which(executable: str) -> str | None:
    return shutil.which(executable)


def _version(executable: str, args: tuple[str, ...]) -> str:
    try:
        proc = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"error: {exc}"
    output = (proc.stdout or proc.stderr).strip()
    return output.splitlines()[0] if output else "present"


def probe() -> list[Probe]:
    """Inspect every known tool and report what is available."""
    results: list[Probe] = []
    for name, executable, args in PROBES:
        path = which(executable)
        results.append(
            Probe(
                name=name,
                found=path is not None,
                detail=_version(path, args) if path else "not on PATH",
            )
        )
    return results


def require(executable: str) -> str:
    """Return the path to *executable* or raise :class:`ToolchainError`."""
    path = which(executable)
    if path is None:
        raise ToolchainError(
            f"{executable!r} is not on PATH. "
            "Install the paper-handler toolchain (`nix develop`, or import the "
            "module and set my.programs.paper-handler.enable = true)."
        )
    return path


def doctor_text(results: list[Probe] | None = None) -> str:
    """Render the human-readable report (also used by the Nix check)."""
    probes = probe() if results is None else results
    width = max(len(p.name) for p in probes)
    lines = ["paper-handler doctor", ""]
    for item in probes:
        mark = "ok  " if item.found else "MISS"
        lines.append(f"  {mark}  {item.name:<{width}}  {item.detail}")
    lines.append("")
    if not next(p for p in probes if p.name == "quarto").found:
        lines.append("quarto is required — nothing will render without it.")
    else:
        engines = [p.name for p in probes if p.found and p.name in ("typst", "pdflatex")]
        lines.append(
            "PDF engines available: " + (", ".join(engines) or "none (HTML only)")
        )
    return "\n".join(lines)


def doctor_json(results: list[Probe] | None = None) -> str:
    """Render the report as JSON, for CI and the Nix check."""
    probes = probe() if results is None else results
    return json.dumps(
        {
            "ok": any(p.found for p in probes if p.name == "quarto"),
            "probes": [asdict(p) for p in probes],
        },
        indent=2,
    )


def doctor_ok(results: list[Probe] | None = None) -> bool:
    """True when Quarto — the one hard requirement — is present."""
    probes = probe() if results is None else results
    return any(p.found for p in probes if p.name == "quarto")
