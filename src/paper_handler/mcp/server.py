"""A dependency-free MCP server over stdio.

Only the parts of the protocol paper-handler needs are implemented: tool
listing/calls, resources (including URI templates), prompts, and ping.  That
keeps the server in the same hermetically-built CLI package — no extra Python
closure, no background process, no network.

stdout is the protocol stream.  Nothing else in this package may print to it;
diagnostics go to stderr and only when ``--debug`` is set.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from typing import Any, TextIO

from paper_handler import __version__
from paper_handler.mcp import prompts, resources

# Importing the package registers every tool.
from paper_handler.mcp import tools as _tools  # noqa: F401
from paper_handler.mcp.context import ToolError, compact
from paper_handler.mcp.registry import ToolSpec, get_tool, tool_specs

LATEST_PROTOCOL = "2025-06-18"
SUPPORTED_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")

INSTRUCTIONS = (
    "Academic paper tools. Start with paper_list or paper_context. Responses are "
    "compact JSON. Write one section per paper_write_section call and run paper_lint "
    "after each. Read paper://style-guide once for the house style."
)


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _tool_payload(spec: ToolSpec, arguments: dict[str, Any], debug: bool) -> dict[str, Any]:
    try:
        data = spec.handler(arguments)
    except ToolError as exc:
        return {
            "content": [{"type": "text", "text": str(exc)}],
            "isError": True,
        }
    except Exception as exc:  # noqa: BLE001 - a tool must not kill the server
        if debug:
            traceback.print_exc(file=sys.stderr)
        return {
            "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
            "isError": True,
        }

    payload: dict[str, Any] = {
        "content": [{"type": "text", "text": compact(data)}],
        "isError": False,
    }
    if isinstance(data, dict):
        payload["structuredContent"] = data
    return payload


def _initialize(params: dict[str, Any]) -> dict[str, Any]:
    requested = params.get("protocolVersion")
    version = requested if requested in SUPPORTED_PROTOCOLS else LATEST_PROTOCOL
    return {
        "protocolVersion": version,
        "capabilities": {
            "tools": {"listChanged": False},
            "resources": {"subscribe": False, "listChanged": False},
            "prompts": {"listChanged": False},
        },
        "serverInfo": {"name": "paper-handler", "version": __version__},
        "instructions": INSTRUCTIONS,
    }


def handle(message: Any, *, debug: bool = False) -> dict[str, Any] | None:
    """Handle one decoded JSON-RPC message.  Notifications return ``None``."""
    if not isinstance(message, dict):
        return _error(None, -32600, "invalid request")

    has_id = "id" in message
    request_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    if not isinstance(params, dict):
        return _error(request_id, -32602, "params must be an object") if has_id else None

    try:
        if method == "initialize":
            result = _initialize(params)
        elif method in ("notifications/initialized", "initialized"):
            return None
        elif method == "ping":
            result = {}
        elif method == "logging/setLevel":
            result = {}
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "inputSchema": spec.input_schema,
                    }
                    for spec in tool_specs()
                ]
            }
        elif method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str) or not name:
                raise JsonRpcError(-32602, "tools/call requires a tool name")
            try:
                spec = get_tool(name)
            except KeyError as exc:
                raise JsonRpcError(-32602, f"unknown tool {name!r}") from exc
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise JsonRpcError(-32602, "arguments must be an object")
            result = _tool_payload(spec, arguments, debug)
        elif method == "resources/list":
            result = {"resources": resources.list_resources()}
        elif method == "resources/templates/list":
            result = {"resourceTemplates": resources.list_templates()}
        elif method == "resources/read":
            uri = params.get("uri")
            if not isinstance(uri, str) or not uri:
                raise JsonRpcError(-32602, "resources/read requires a uri")
            result = resources.read(uri)
        elif method == "prompts/list":
            result = {"prompts": prompts.list_prompts()}
        elif method == "prompts/get":
            name = params.get("name")
            if not isinstance(name, str) or not name:
                raise JsonRpcError(-32602, "prompts/get requires a name")
            try:
                result = prompts.get(name, params.get("arguments") or {})
            except KeyError as exc:
                raise JsonRpcError(-32602, f"unknown prompt {name!r}") from exc
        else:
            raise JsonRpcError(-32601, f"method not found: {method}")
    except JsonRpcError as exc:
        return _error(request_id, exc.code, exc.message) if has_id else None
    except ToolError as exc:
        return _error(request_id, -32602, str(exc)) if has_id else None
    except Exception as exc:  # noqa: BLE001 - keep the server alive
        if debug:
            traceback.print_exc(file=sys.stderr)
        message_text = f"{type(exc).__name__}: {exc}"
        return _error(request_id, -32603, message_text) if has_id else None

    return _result(request_id, result) if has_id else None


def run(stdin: TextIO | None = None, stdout: TextIO | None = None, *, debug: bool = False) -> None:
    """Serve newline-delimited JSON-RPC until EOF."""
    source = stdin or sys.stdin
    sink = stdout or sys.stdout
    for raw in source:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            response: dict[str, Any] | None = _error(None, -32700, "parse error")
        else:
            response = handle(message, debug=debug)
        if response is None:
            continue
        sink.write(compact(response) + "\n")
        sink.flush()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="paper-handler-mcp",
        description="MCP server for paper-handler (stdio transport).",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--debug", action="store_true", help="log exceptions to stderr")
    args = parser.parse_args(argv)
    try:
        run(debug=args.debug)
    except KeyboardInterrupt:
        pass
    except BrokenPipeError:
        pass


if __name__ == "__main__":
    main()
