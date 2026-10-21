"""Toolchain discovery and the ``doctor`` report.

The Nix side ships a single derivation (``nix/toolchain.nix``) with everything
``quarto render`` needs on PATH; this module only *observes* what is actually
there, so it works identically inside the Nix dev shell, a bare virtualenv, or
a system install with the distro's Quarto.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

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
    """Resolve *executable*, honouring an explicit override.

    A long-lived MCP server cannot change its own PATH, so two environment
    knobs exist: ``PAPER_HANDLER_<TOOL>`` (an exact path, or a directory
    containing it) and ``PAPER_HANDLER_TOOLCHAIN_DIR`` (a bin directory
    searched first).  An explicit override that does not resolve is a
    misconfiguration, not a reason to silently fall through to PATH.
    """
    override = os.environ.get(f"PAPER_HANDLER_{executable.upper().replace('-', '_')}")
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_dir():
            candidate = candidate / executable
        return str(candidate) if candidate.is_file() else None

    toolchain_dir = os.environ.get("PAPER_HANDLER_TOOLCHAIN_DIR")
    if toolchain_dir:
        candidate = Path(toolchain_dir).expanduser() / executable
        if candidate.is_file():
            return str(candidate)

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
    if path is not None:
        return path

    env_name = f"PAPER_HANDLER_{executable.upper().replace('-', '_')}"
    if os.environ.get(env_name):
        raise ToolchainError(
            f"{env_name}={os.environ[env_name]!r} does not resolve to an "
            f"executable file for {executable!r}."
        )
    raise ToolchainError(
        f"{executable!r} is not on PATH. "
        "Install the paper-handler toolchain (`nix develop`, or import the "
        "module and set my.programs.paper-handler.enable = true), or point "
        f"`{env_name}` at the binary (or at its bin directory)."
    )


def smoke_render() -> dict[str, object]:
    """Render a minimal document so ``doctor`` tests rendering, not presence.

    Presence is not health: Quarto can start, find Typst, and still fail every
    render because its bundled Pandoc and the on-PATH Pandoc disagree.  The
    smoke test exercises the default HTML path, which needs no PDF engine.
    """
    quarto = which("quarto")
    if quarto is None:
        return {"ok": False, "detail": "quarto not found"}

    with tempfile.TemporaryDirectory(prefix="paper-handler-smoke-") as directory:
        entry = Path(directory) / "index.qmd"
        entry.write_text(
            "---\ntitle: smoke\nformat: html\n---\n\n# Smoke\n\nText.\n",
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [quarto, "render", "index.qmd", "--to", "html"],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "detail": f"render failed to start: {exc}"}

    if proc.returncode == 0:
        return {"ok": True, "detail": "minimal HTML render ok"}
    output = (proc.stderr or proc.stdout).strip()
    hint = render_hint(output)
    detail = output[-1200:] if len(output) > 1200 else output
    return {"ok": False, "detail": hint or detail or "render failed"}


def render_hint(text: str) -> str | None:
    """Translate Quarto's opaque Aeson failures into an actionable hint."""
    lowered = text.casefold()
    if "aeson exception" in lowered or "unknown option" in lowered:
        return (
            "Quarto rendered but its Pandoc is incompatible with the installed "
            "version (Aeson exception / unknown option). Run `quarto check` "
            "and use a matching Quarto/Pandoc pair; this is a toolchain "
            "problem, not a document problem."
        )
    return None


def doctor_report(results: list[Probe] | None = None) -> dict[str, object]:
    """The full doctor result: probes, optional smoke render, and ``ok``.

    ``results`` is the injectable test seam: when supplied, no smoke render
    runs and ``ok`` means only that Quarto is present.
    """
    probes = probe() if results is None else results
    render = smoke_render() if results is None else None
    quarto = any(p.found for p in probes if p.name == "quarto")
    ok = quarto and (render is None or bool(render["ok"]))
    return {
        "ok": ok,
        "probes": [asdict(p) for p in probes],
        "render": render,
    }


def format_report(report: dict[str, object]) -> str:
    probes = [Probe(**item) for item in report["probes"]]  # type: ignore[arg-type]
    width = max(len(p.name) for p in probes)
    lines = ["paper-handler doctor", ""]
    for item in probes:
        mark = "ok  " if item.found else "MISS"
        lines.append(f"  {mark}  {item.name:<{width}}  {item.detail}")
    lines.append("")
    if not any(p.found for p in probes if p.name == "quarto"):
        lines.append("quarto is required — nothing will render without it.")
    else:
        engines = [p.name for p in probes if p.found and p.name in ("typst", "pdflatex")]
        lines.append(
            "PDF engines available: " + (", ".join(engines) or "none (HTML only)")
        )
    render = report.get("render")
    if render is not None:
        detail = str(render["detail"])
        lines.append(f"render: {'ok' if render['ok'] else 'BROKEN'}  {detail}")
    return "\n".join(lines)


def doctor_text(results: list[Probe] | None = None) -> str:
    """Render the human-readable report (also used by the Nix check)."""
    return format_report(doctor_report(results))


def doctor_json(results: list[Probe] | None = None) -> str:
    """Render the report as JSON, for CI and the Nix check."""
    return json.dumps(doctor_report(results), indent=2)


def doctor_ok(results: list[Probe] | None = None) -> bool:
    """True when Quarto renders; with injected probes, only that it is present."""
    return bool(doctor_report(results)["ok"])
