"""memreckon command line.

    memreckon audit  --store PATH --repo PATH [--out DIR] [--adapter NAME]
    memreckon gate   --store PATH --repo PATH [--out FILE] [--format md|json]
                     [--fail-on-refuted]
    memreckon verify-ledger LEDGER.jsonl
    memreckon mcp    (stdio JSON-RPC tool server)

Exit codes: 0 success; 1 a verification failed (ledger chain broken, or
gate found REFUTED entries under --fail-on-refuted); 2 usage/IO error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, model
from .adapters import get_adapter
from .audit import render_report, run_audit
from .gate import render_gate_json, render_gate_markdown
from .ledger import verify_ledger
from .mcp_server import serve as serve_mcp


def _audit_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--store", required=True, help="memory store path (file or directory)")
    p.add_argument("--repo", required=True, help="live repository to check claims against")
    p.add_argument(
        "--adapter",
        default="auto",
        choices=["auto", "memoryvault", "markdown"],
        help="store adapter (default: auto-detect)",
    )
    p.add_argument(
        "--run-commands",
        action="store_true",
        help="execute commands named by command-outcome claims (default: off; "
        "such claims are UNVERIFIABLE without it)",
    )
    p.add_argument("--test-timeout", type=int, default=120, help="per-check timeout, seconds")


def _summary_line(result) -> str:
    c = result.counts()
    return (
        f"{c['total']} entries: {c[model.VERIFIED]} verified, "
        f"{c[model.REFUTED]} refuted, {c[model.STALE]} stale, "
        f"{c[model.UNVERIFIABLE]} unverifiable"
    )


def cmd_audit(args: argparse.Namespace) -> int:
    store_path, repo = Path(args.store), Path(args.repo)
    if not store_path.exists() or not repo.is_dir():
        print("error: --store must exist and --repo must be a directory", file=sys.stderr)
        return 2
    adapter = get_adapter(args.adapter, store_path)
    out_dir = Path(args.out) if args.out else None
    ledger_path = (out_dir / "ledger.jsonl") if out_dir else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    result = run_audit(
        adapter,
        store_path,
        repo,
        ledger_path=ledger_path,
        run_commands=args.run_commands,
        test_timeout=args.test_timeout,
    )
    if out_dir:
        (out_dir / "report.md").write_text(render_report(result), encoding="utf-8")
        print(f"ledger: {ledger_path}\nreport: {out_dir / 'report.md'}")
    else:
        print(render_report(result))
    print(_summary_line(result))
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    store_path, repo = Path(args.store), Path(args.repo)
    if not store_path.exists() or not repo.is_dir():
        print("error: --store must exist and --repo must be a directory", file=sys.stderr)
        return 2
    adapter = get_adapter(args.adapter, store_path)
    result = run_audit(
        adapter,
        store_path,
        repo,
        run_commands=args.run_commands,
        test_timeout=args.test_timeout,
    )
    rendered = (
        render_gate_json(result) if args.format == "json" else render_gate_markdown(result)
    )
    if args.out:
        Path(args.out).write_text(rendered, encoding="utf-8")
        print(f"gate context written to {args.out}", file=sys.stderr)
    else:
        print(rendered)
    print(_summary_line(result), file=sys.stderr)
    if args.fail_on_refuted and result.counts()[model.REFUTED]:
        return 1
    return 0


def cmd_verify_ledger(args: argparse.Namespace) -> int:
    ok, problems = verify_ledger(Path(args.ledger))
    if ok:
        print("ledger chain OK")
        return 0
    for problem in problems:
        print(f"BROKEN: {problem}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memreckon",
        description="Audit agent memory: re-check remembered claims against the "
        "live repository and stamp them VERIFIED / REFUTED / STALE / UNVERIFIABLE.",
    )
    parser.add_argument("--version", action="version", version=f"memreckon {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="audit a store, write ledger + report")
    _audit_args(p_audit)
    p_audit.add_argument("--out", help="output directory for ledger.jsonl and report.md")
    p_audit.set_defaults(func=cmd_audit)

    p_gate = sub.add_parser("gate", help="render gated session-start context")
    _audit_args(p_gate)
    p_gate.add_argument("--out", help="write context to this file instead of stdout")
    p_gate.add_argument("--format", default="md", choices=["md", "json"])
    p_gate.add_argument(
        "--fail-on-refuted",
        action="store_true",
        help="exit 1 when any memory is REFUTED (for session-start hooks)",
    )
    p_gate.set_defaults(func=cmd_gate)

    p_verify = sub.add_parser("verify-ledger", help="verify a ledger's hash chain")
    p_verify.add_argument("ledger")
    p_verify.set_defaults(func=cmd_verify_ledger)

    p_mcp = sub.add_parser("mcp", help="serve memreckon's tools over stdio (MCP-style)")
    p_mcp.set_defaults(func=lambda _args: serve_mcp())

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
