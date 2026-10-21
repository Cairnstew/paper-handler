"""Toolchain probing and the doctor report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_handler import toolchain
from paper_handler.toolchain import Probe, ToolchainError

PRESENT = [
    Probe("quarto", True, "1.10.18"),
    Probe("pandoc", True, "3.7.0.2"),
    Probe("typst", True, "0.13.1"),
    Probe("pdflatex", False, "not on PATH"),
    Probe("lualatex", False, "not on PATH"),
    Probe("latexmk", False, "not on PATH"),
    Probe("jupyter", False, "not on PATH"),
    Probe("python", True, "3.14.7"),
]

ABSENT = [Probe(name, False, "not on PATH") for name, _, _ in toolchain.PROBES]


def test_doctor_ok_tracks_quarto_only() -> None:
    assert toolchain.doctor_ok(PRESENT) is True
    assert toolchain.doctor_ok(ABSENT) is False


def test_doctor_text_reports_everything() -> None:
    text = toolchain.doctor_text(PRESENT)
    assert "paper-handler doctor" in text
    assert "1.10.18" in text
    assert "MISS  pdflatex" in text
    assert "PDF engines available: typst" in text


def test_doctor_text_explains_missing_quarto() -> None:
    text = toolchain.doctor_text(ABSENT)
    assert "quarto is required" in text


def test_doctor_json_is_machine_readable() -> None:
    payload = json.loads(toolchain.doctor_json(PRESENT))
    assert payload["ok"] is True
    assert {p["name"] for p in payload["probes"]} == {name for name, _, _ in toolchain.PROBES}
    assert json.loads(toolchain.doctor_json(ABSENT))["ok"] is False


def test_probe_reports_missing_when_path_is_empty(no_tools: Path) -> None:
    results = toolchain.probe()
    assert all(not r.found for r in results)
    assert all(r.detail == "not on PATH" for r in results)
    assert toolchain.doctor_ok() is False


def test_probe_reports_the_version_of_a_found_tool(monkeypatch, tmp_path: Path) -> None:
    # Deterministic PATH rather than the ambient one: the Nix sandbox does not
    # put the venv's own `python` on PATH, so probing for a real interpreter
    # would be machine-dependent.
    fake = tmp_path / "quarto"
    fake.write_text("#!/bin/sh\necho '1.10.18'\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))

    results = {r.name: r for r in toolchain.probe()}
    assert results["quarto"].found is True
    assert results["quarto"].detail == "1.10.18"
    assert results["typst"].found is False


def test_require_raises_with_actionable_message(no_tools: Path) -> None:
    with pytest.raises(ToolchainError, match="nix develop"):
        toolchain.require("quarto")


def test_require_returns_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = tmp_path / "quarto"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert toolchain.require("quarto") == str(fake)


def test_which_honours_a_per_tool_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = tmp_path / "quarto"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("PAPER_HANDLER_QUARTO", str(fake))
    assert toolchain.which("quarto") == str(fake)

    monkeypatch.setenv("PAPER_HANDLER_QUARTO", str(tmp_path))
    assert toolchain.which("quarto") == str(fake)


def test_which_honours_a_toolchain_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = tmp_path / "typst"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("PAPER_HANDLER_TOOLCHAIN_DIR", str(tmp_path))
    assert toolchain.which("typst") == str(fake)


def test_require_rejects_an_unresolvable_override(
    monkeypatch: pytest.MonkeyPatch, no_tools: Path
) -> None:
    monkeypatch.setenv("PAPER_HANDLER_QUARTO", "/does/not/exist/quarto")
    with pytest.raises(ToolchainError, match="PAPER_HANDLER_QUARTO"):
        toolchain.require("quarto")


def test_doctor_runs_a_smoke_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(toolchain, "probe", lambda: PRESENT)
    monkeypatch.setattr(
        toolchain, "smoke_render", lambda: {"ok": False, "detail": "Aeson exception"}
    )
    report = toolchain.doctor_report()
    assert report["ok"] is False
    assert report["render"]["ok"] is False
    assert "Aeson exception" in report["render"]["detail"]

    monkeypatch.setattr(
        toolchain, "smoke_render", lambda: {"ok": True, "detail": "ok"}
    )
    assert toolchain.doctor_report()["ok"] is True
