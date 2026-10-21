"""MCP server behaviour, driven through the JSON-RPC handler and stdio."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

from paper_handler import frontmatter as fm
from paper_handler.mcp import server
from paper_handler.mcp.registry import tool_specs


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
    result = response["result"]
    return json.loads(result["content"][0]["text"])


def test_initialize_negotiates_a_supported_version() -> None:
    response = server.handle(
        rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    )
    result = response["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["serverInfo"]["name"] == "paper-handler"
    assert "paper_context" in result["instructions"]
    assert result["capabilities"]["tools"]["listChanged"] is False


def test_unknown_protocol_falls_back_to_latest() -> None:
    response = server.handle(rpc("initialize", {"protocolVersion": "1999-01-01"}))
    assert response["result"]["protocolVersion"] == server.LATEST_PROTOCOL


def test_tools_list_has_the_writing_core() -> None:
    response = server.handle(rpc("tools/list"))
    names = {item["name"] for item in response["result"]["tools"]}
    assert {
        "paper_context",
        "paper_list",
        "paper_lint",
        "paper_new",
        "paper_outline",
        "paper_read_section",
        "paper_render",
        "paper_write_abstract",
        "paper_write_section",
    } <= names
    context = next(item for item in response["result"]["tools"] if item["name"] == "paper_context")
    assert context["inputSchema"]["type"] == "object"


def test_registry_is_nonempty_and_sorted() -> None:
    names = [spec.name for spec in tool_specs()]
    assert names == sorted(names)
    assert len(names) >= 10


def test_ping_and_notification() -> None:
    assert server.handle(rpc("ping"))["result"] == {}
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_paper_list(make_paper, corpus: Path) -> None:
    make_paper("alpha", title="Alpha Paper", status="submitted")
    data = payload(call("paper_list"))
    assert data["count"] == 1
    assert data["papers"][0]["name"] == "alpha"
    assert data["papers"][0]["status"] == "submitted"
    assert data["papers"][0]["words"] > 0


def test_paper_context_is_compact_and_budgeted(make_paper, corpus: Path) -> None:
    make_paper("alpha", title="Alpha")
    data = payload(call("paper_context", {"name": "alpha", "budget": 1200}))
    assert data["paper"] == "alpha"
    assert data["title"] == "Alpha"
    assert data["sections"]
    assert data["style"]
    assert data["citations"]["defined_count"] == 1
    assert data["truncated"] is False

    small = payload(call("paper_context", {"name": "alpha", "budget": 1}))
    assert small["truncated"] is True
    assert "citations_note" in small


def test_paper_outline(make_paper, corpus: Path) -> None:
    make_paper("alpha")
    data = payload(call("paper_outline", {"name": "alpha"}))
    assert data["paper"] == "alpha"
    assert data["sections"][0]["heading"] == "Introduction"

    # A corpus-relative path is accepted as well as a bare name.
    relative = payload(call("paper_outline", {"name": "papers/alpha"}))
    assert relative["paper"] == "alpha"


def test_read_and_edit_sections(make_paper, corpus: Path) -> None:
    directory = make_paper("alpha")

    replaced = payload(
        call(
            "paper_write_section",
            {"name": "alpha", "heading": "Introduction", "content": "A new introduction."},
        )
    )
    assert replaced["ok"] is True
    assert "A new introduction." in (directory / "index.qmd").read_text(encoding="utf-8")

    inserted = payload(
        call(
            "paper_write_section",
            {
                "name": "alpha",
                "heading": "Method",
                "content": "We measure things.",
                "mode": "insert",
                "after": "Introduction",
            },
        )
    )
    assert inserted["ok"] is True
    text = (directory / "index.qmd").read_text(encoding="utf-8")
    assert text.index("## Introduction") < text.index("## Method")

    appended = payload(
        call(
            "paper_write_section",
            {
                "name": "alpha",
                "heading": "Method",
                "content": "One more detail.",
                "mode": "append",
            },
        )
    )
    assert appended["ok"] is True
    text = (directory / "index.qmd").read_text(encoding="utf-8")
    assert "We measure things." in text and "One more detail." in text

    read = payload(call("paper_read_section", {"name": "alpha", "heading": "Method"}))
    assert "We measure things." in read["text"]
    assert read["truncated"] is False

    clipped = payload(
        call("paper_read_section", {"name": "alpha", "heading": "Method", "max_tokens": 1})
    )
    assert clipped["truncated"] is True


def test_write_section_rejects_empty_content(make_paper, corpus: Path) -> None:
    make_paper("alpha")
    response = call(
        "paper_write_section", {"name": "alpha", "heading": "Introduction", "content": "  "}
    )
    assert response["result"]["isError"] is True
    assert "empty" in response["result"]["content"][0]["text"]


def test_write_section_rejects_unknown_heading(make_paper, corpus: Path) -> None:
    make_paper("alpha")
    response = call(
        "paper_write_section", {"name": "alpha", "heading": "Nope", "content": "text"}
    )
    assert response["result"]["isError"] is True
    assert "no section" in response["result"]["content"][0]["text"]


def test_write_abstract(make_paper, corpus: Path) -> None:
    directory = make_paper("alpha")
    data = payload(
        call(
            "paper_write_abstract",
            {"name": "alpha", "text": "One two three four."},
        )
    )
    assert data["abstract_words"] == 4
    assert fm.read(directory / "index.qmd")["abstract"] == "One two three four."


def test_meta_get_and_set(make_paper, corpus: Path) -> None:
    directory = make_paper("alpha")
    set_result = payload(
        call("paper_meta_set", {"name": "alpha", "key": "status", "value": "submitted"})
    )
    assert set_result["value"] == "submitted"
    assert fm.read(directory / "index.qmd")["status"] == "submitted"

    got = payload(call("paper_meta_get", {"name": "alpha", "key": "status"}))
    assert got["status"] == "submitted"

    all_meta = payload(call("paper_meta_get", {"name": "alpha"}))
    assert all_meta["meta"]["title"] == "A Sample Paper"


def test_lint_reports_counts_and_truncates(make_paper, corpus: Path) -> None:
    make_paper("alpha")
    data = payload(call("paper_lint", {"name": "alpha", "max_issues": 1}))
    assert "errors" in data and "warnings" in data
    assert len(data["issues"]) <= 1
    assert data["omitted"] >= 0


def test_bib_check_and_init(make_paper, corpus: Path) -> None:
    directory = make_paper("alpha")
    check = payload(call("paper_bib_check", {"name": "alpha"}))
    assert check["ok"] is True
    assert check["entries"] == 1

    (directory / "references.bib").unlink()
    init = payload(call("paper_bib_init", {"name": "alpha"}))
    assert init["ok"] is True
    assert (directory / "references.bib").is_file()


def test_render_without_quarto_is_a_tool_error(make_paper, corpus: Path, no_tools: Path) -> None:
    make_paper("alpha")
    response = call("paper_render", {"name": "alpha"})
    assert response["result"]["isError"] is True
    assert "not on PATH" in response["result"]["content"][0]["text"]


def test_render_rejects_name_and_all(make_paper, corpus: Path) -> None:
    make_paper("alpha")
    response = call("paper_render", {"name": "alpha", "all": True})
    assert response["result"]["isError"] is True
    assert "not both" in response["result"]["content"][0]["text"]


def test_new_paper(make_paper, corpus: Path) -> None:
    # `paper_new` needs an empty slot; the fixture's paper is irrelevant.
    data = payload(call("paper_new", {"name": "fresh", "title": "Fresh Paper"}))
    assert data["ok"] is True
    assert data["entry"] == "papers/fresh/index.qmd"
    assert (corpus / "papers" / "fresh" / "index.qmd").is_file()


def test_unknown_tool_is_a_protocol_error(make_paper, corpus: Path) -> None:
    response = call("paper_nope")
    assert response["error"]["code"] == -32602
    assert "unknown tool" in response["error"]["message"]


def test_resources_and_templates(make_paper, corpus: Path) -> None:
    make_paper("alpha")
    listed = server.handle(rpc("resources/list"))["result"]["resources"]
    assert {item["uri"] for item in listed} >= {"paper://style-guide", "paper://corpus"}

    templates = server.handle(rpc("resources/templates/list"))["result"]["resourceTemplates"]
    assert any(item["uriTemplate"] == "paper://papers/{name}/outline" for item in templates)

    style = server.handle(rpc("resources/read", {"uri": "paper://style-guide"}))
    assert "Academic writing style" in style["result"]["contents"][0]["text"]

    corpus_resource = server.handle(rpc("resources/read", {"uri": "paper://corpus"}))
    assert "alpha" in corpus_resource["result"]["contents"][0]["text"]

    outline = server.handle(rpc("resources/read", {"uri": "paper://papers/alpha/outline"}))
    outline_data = json.loads(outline["result"]["contents"][0]["text"])
    assert outline_data["paper"] == "alpha"

    context = server.handle(rpc("resources/read", {"uri": "paper://papers/alpha/context"}))
    context_data = json.loads(context["result"]["contents"][0]["text"])
    assert context_data["paper"] == "alpha"


def test_unknown_resource_is_an_error(make_paper, corpus: Path) -> None:
    response = server.handle(rpc("resources/read", {"uri": "paper://nope"}))
    assert response["error"]["code"] == -32602


def test_prompts(make_paper, corpus: Path) -> None:
    listed = server.handle(rpc("prompts/list"))["result"]["prompts"]
    assert {item["name"] for item in listed} == {
        "write_paper",
        "revise_paper",
        "review_paper",
        "research_to_paper",
    }

    prompt = server.handle(
        rpc("prompts/get", {"name": "write_paper", "arguments": {"name": "alpha"}})
    )
    text = prompt["result"]["messages"][0]["content"]["text"]
    assert "alpha" in text and "paper_context" in text

    missing = server.handle(rpc("prompts/get", {"name": "nope"}))
    assert missing["error"]["code"] == -32602


def test_run_reports_parse_errors_and_keeps_going() -> None:
    source = io.StringIO(
        '{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
        "not json\n"
        '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        '{"jsonrpc":"2.0","id":2,"method":"ping"}\n'
    )
    sink = io.StringIO()
    server.run(source, sink)
    lines = [json.loads(line) for line in sink.getvalue().splitlines()]
    assert len(lines) == 3
    assert lines[0]["result"] == {}
    assert lines[1]["error"]["code"] == -32700
    assert lines[2]["result"] == {}


def test_stdio_subprocess_is_clean(make_paper, corpus: Path) -> None:
    """The packaged entry point must emit only JSON-RPC on stdout."""
    make_paper("alpha")
    requests = (
        json.dumps(
            rpc(
                "initialize",
                {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {}},
            )
        )
        + "\n"
        + json.dumps(rpc("tools/call", {"name": "paper_list", "arguments": {}}, request_id=2))
        + "\n"
        + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        + "\n"
    )
    # pytest adds `src` to sys.path via pyproject's `pythonpath` setting, but
    # that does not propagate to a subprocess.  Point the child at the checkout
    # explicitly so this test also works inside the Nix sandbox.
    env = os.environ.copy()
    source = str(Path(__file__).resolve().parents[1] / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{source}{os.pathsep}{existing}" if existing else source

    completed = subprocess.run(
        [sys.executable, "-m", "paper_handler.mcp"],
        input=requests,
        cwd=corpus,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert len(lines) == 2
    replies = [json.loads(line) for line in lines]
    assert replies[0]["result"]["serverInfo"]["name"] == "paper-handler"
    listed = json.loads(replies[1]["result"]["content"][0]["text"])
    assert listed["papers"][0]["name"] == "alpha"
    assert completed.stderr == ""
