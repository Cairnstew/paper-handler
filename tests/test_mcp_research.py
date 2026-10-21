"""MCP research handoff tools and the session corpus handle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paper_handler.mcp import server
from paper_handler.mcp.context import close_corpus

FIXTURE = Path(__file__).parent / "fixtures" / "research-handoff"


def rpc(method: str, params: dict | None = None, *, request_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }


def call(name: str, arguments: dict | None = None, *, request_id: int = 2) -> dict:
    return server.handle(
        rpc("tools/call", {"name": name, "arguments": arguments or {}}, request_id=request_id)
    )


def payload(response: dict) -> dict:
    return json.loads(response["result"]["content"][0]["text"])


@pytest.fixture(autouse=True)
def reset_corpus():
    close_corpus()
    yield
    close_corpus()


def test_research_tools_are_registered() -> None:
    listed = server.handle(rpc("tools/list"))["result"]["tools"]
    names = {item["name"] for item in listed}
    assert {
        "paper_open_corpus",
        "paper_close_corpus",
        "paper_research_import",
        "paper_research_context",
        "paper_research_prisma",
        "paper_research_sync",
        "paper_cite_key",
    } <= names


def test_open_and_close_corpus(corpus: Path, make_paper) -> None:
    make_paper("alpha")
    opened = payload(call("paper_open_corpus", {"path": str(corpus)}))
    assert opened["ok"] is True
    assert opened["count"] == 1
    assert opened["papers"] == ["alpha"]

    closed = payload(call("paper_close_corpus"))
    assert closed == {"ok": True, "corpus": None}


def test_import_context_and_cite(corpus: Path) -> None:
    imported = payload(
        call(
            "paper_research_import",
            {"handoff": str(FIXTURE), "name": "alpha", "title": "Alpha"},
        )
    )
    assert imported["ok"] is True
    assert imported["included"] == 2
    assert (corpus / "papers" / "alpha" / "research" / "references.bib").is_file()

    brief = payload(call("paper_research_context", {"name": "alpha", "budget": 1200}))
    assert brief["included"] == 2
    assert brief["screening"]["ready"] is True
    assert brief["keys"] == ["smith2020attention", "jones2021tooling"]
    assert brief["truncated"] is False
    assert len(json.dumps(brief)) < 1200 * 4

    by_id = payload(
        call("paper_cite_key", {"name": "alpha", "identifier": "10.5555/attention.2020"})
    )
    assert by_id["key"] == "smith2020attention"

    by_title = payload(
        call(
            "paper_cite_key",
            {"name": "alpha", "identifier": "Tooling for Scholarly Manuscripts"},
        )
    )
    assert by_title["key"] == "jones2021tooling"

    missing = call("paper_cite_key", {"name": "alpha", "identifier": "10.9999/nope"})
    assert missing["result"]["isError"] is True


def test_context_includes_research_summary(corpus: Path) -> None:
    payload(
        call(
            "paper_research_import",
            {"handoff": str(FIXTURE), "name": "alpha", "title": "Alpha"},
        )
    )
    context = payload(call("paper_context", {"name": "alpha", "budget": 4000}))
    assert context["research"]["included"] == 2
    assert context["research"]["screening_ready"] is True
    assert "paper_research_context" in context["research"]["note"]


def test_research_resource_and_prompt(corpus: Path) -> None:
    payload(
        call(
            "paper_research_import",
            {"handoff": str(FIXTURE), "name": "alpha", "title": "Alpha"},
        )
    )
    resource = server.handle(
        rpc("resources/read", {"uri": "paper://papers/alpha/research"})
    )
    data = json.loads(resource["result"]["contents"][0]["text"])
    assert data["keys"] == ["smith2020attention", "jones2021tooling"]

    prompt = server.handle(
        rpc(
            "prompts/get",
            {
                "name": "research_to_paper",
                "arguments": {"name": "alpha", "handoff": str(FIXTURE)},
            },
        )
    )
    text = prompt["result"]["messages"][0]["content"]["text"]
    assert "paper_research_import" in text
    assert str(FIXTURE) in text


def test_sync_refreshes_bundle(corpus: Path) -> None:
    payload(
        call(
            "paper_research_import",
            {"handoff": str(FIXTURE), "name": "alpha", "title": "Alpha"},
        )
    )
    synced = payload(
        call("paper_research_sync", {"name": "alpha", "handoff": str(FIXTURE)})
    )
    assert synced["ok"] is True
    assert synced["included"] == 2


def test_prisma_tool_appends_include(corpus: Path) -> None:
    payload(
        call(
            "paper_research_import",
            {"handoff": str(FIXTURE), "name": "alpha", "title": "Alpha"},
        )
    )
    receipt = payload(call("paper_research_prisma", {"name": "alpha"}))
    assert receipt["ok"] is True
    assert receipt["action"] == "insert"
    text = (corpus / "papers" / "alpha" / "index.qmd").read_text()
    assert "{{< include research/prisma.md >}}" in text


def test_bib_check_covers_both_bibliographies(corpus: Path) -> None:
    payload(
        call(
            "paper_research_import",
            {"handoff": str(FIXTURE), "name": "alpha", "title": "Alpha"},
        )
    )
    checked = payload(call("paper_bib_check", {"name": "alpha"}))
    assert checked["ok"] is True
    assert len(checked["files"]) == 2
    assert checked["entries"] >= 2
