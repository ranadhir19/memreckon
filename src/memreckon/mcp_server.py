"""A thin MCP-style adapter: memreckon's tools over stdio JSON-RPC.

Implements the MCP tool-call shape (``initialize``, ``tools/list``,
``tools/call``, newline-delimited JSON-RPC 2.0 over stdio) with the
standard library only, so any MCP-speaking harness can ask for an audit
or a gated context without shelling out. It is deliberately thin: three
tools, no resources/prompts surface, no sampling. Stores that already
ship their own MCP server (memoryvault-agents does) keep it; this is the
auditor's interface, not a replacement store interface.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

from . import __version__
from .adapters import get_adapter
from .audit import render_report, run_audit
from .gate import gate_payload
from .ledger import verify_ledger

TOOLS = [
    {
        "name": "audit_store",
        "description": "Audit an agent memory store against a live repository. "
        "Returns per-entry VERIFIED / REFUTED / STALE / UNVERIFIABLE stamps.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "store_path": {"type": "string"},
                "repo_path": {"type": "string"},
                "adapter": {"type": "string", "default": "auto"},
                "run_commands": {"type": "boolean", "default": False},
            },
            "required": ["store_path", "repo_path"],
        },
    },
    {
        "name": "gate_context",
        "description": "Audit, then return session-start context with REFUTED "
        "memories quarantined (with contradicting evidence) instead of trusted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "store_path": {"type": "string"},
                "repo_path": {"type": "string"},
                "adapter": {"type": "string", "default": "auto"},
                "run_commands": {"type": "boolean", "default": False},
            },
            "required": ["store_path", "repo_path"],
        },
    },
    {
        "name": "verify_ledger",
        "description": "Verify the hash chain of a memreckon audit ledger.",
        "inputSchema": {
            "type": "object",
            "properties": {"ledger_path": {"type": "string"}},
            "required": ["ledger_path"],
        },
    },
]


def _run_audit_tool(args: dict[str, Any]):
    store_path = Path(args["store_path"])
    repo_path = Path(args["repo_path"])
    adapter = get_adapter(args.get("adapter", "auto"), store_path)
    return run_audit(
        adapter,
        store_path,
        repo_path,
        run_commands=bool(args.get("run_commands", False)),
    )


def call_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "audit_store":
        result = _run_audit_tool(args)
        return {
            "counts": result.counts(),
            "verdicts": [v.to_dict() for v in result.verdicts],
            "report_markdown": render_report(result),
        }
    if name == "gate_context":
        return gate_payload(_run_audit_tool(args))
    if name == "verify_ledger":
        ok, problems = verify_ledger(Path(args["ledger_path"]))
        return {"ok": ok, "problems": problems}
    raise ValueError(f"unknown tool: {name}")


def _response(req_id: Any, result: Optional[dict] = None, error: Optional[dict] = None) -> dict:
    out: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        out["error"] = error
    else:
        out["result"] = result if result is not None else {}
    return out


def handle_message(msg: dict[str, Any]) -> Optional[dict[str, Any]]:
    method = msg.get("method", "")
    req_id = msg.get("id")
    if method == "initialize":
        return _response(
            req_id,
            {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "memreckon", "version": __version__},
                "capabilities": {"tools": {}},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _response(req_id, {"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params") or {}
        try:
            payload = call_tool(params.get("name", ""), params.get("arguments") or {})
        except Exception as exc:  # surfaced as a tool error, never a crash
            return _response(
                req_id,
                {
                    "content": [{"type": "text", "text": f"error: {exc}"}],
                    "isError": True,
                },
            )
        return _response(
            req_id,
            {
                "content": [
                    {"type": "text", "text": json.dumps(payload, indent=2)}
                ],
                "structuredContent": payload,
            },
        )
    if req_id is not None:
        return _response(req_id, error={"code": -32601, "message": f"unknown method: {method}"})
    return None


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        reply = handle_message(msg)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
    return 0
