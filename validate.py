#!/usr/bin/env python3
"""memreckon validation harness.

Runs, in order:
  1. the full unit/integration test suite (stdlib unittest),
  2. a byte-compile of every source file,
  3. the four-stamp fixture proof through the public audit API
     (VERIFIED / REFUTED / STALE / UNVERIFIABLE, both store adapters),
  4. a ledger write + chain-verification round trip,
  5. required-file presence (README, LICENSE, NAME_CHECK, COMPLIANCE),
  6. a secrets scan over the exact tree that would be published.

Exit code 0 only if every stage passes. Failures are fixed, never
silenced: this harness is the repo's deploy gate.
"""

from __future__ import annotations

import compileall
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "fixtures"))

SECRET_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
]

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules"}


def stage(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    return ok


def main() -> int:
    results: list[bool] = []

    # 1. Test suite ------------------------------------------------------
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    tail = (proc.stderr or proc.stdout).strip().splitlines()
    results.append(
        stage("test suite", proc.returncode == 0, tail[-1] if tail else "")
    )
    if proc.returncode != 0:
        print(proc.stdout[-3000:])
        print(proc.stderr[-3000:])

    # 2. Byte-compile ------------------------------------------------------
    ok = compileall.compile_dir(str(ROOT / "src"), quiet=1) and compileall.compile_dir(
        str(ROOT / "tests"), quiet=1
    )
    results.append(stage("byte-compile", bool(ok)))

    # 3. Four-stamp fixture proof -------------------------------------------
    import build_fixture
    from memreckon import model
    from memreckon.adapters import MarkdownAdapter, MemoryVaultAdapter
    from memreckon.audit import run_audit
    from memreckon.ledger import LedgerWriter, verify_ledger

    expected = {
        "Dependency requests": model.VERIFIED,
        "Test suite": model.REFUTED,
        "slugify helper": model.STALE,
        "Review style": model.UNVERIFIABLE,
    }
    proof_ok = True
    detail = ""
    with tempfile.TemporaryDirectory() as tmp:
        paths = build_fixture.build(Path(tmp) / "fx")
        for adapter, key in (
            (MemoryVaultAdapter(), "memoryvault"),
            (MarkdownAdapter(), "markdown"),
        ):
            result = run_audit(adapter, paths[key], paths["repo"])
            got = {}
            for entry in result.entries:
                verdict = result.verdict_for(entry.id)
                for prefix in expected:
                    if entry.text.startswith(prefix):
                        got[prefix] = verdict.stamp
            if got != expected:
                proof_ok = False
                detail = f"{key}: {got}"
        # 4. Ledger round trip ------------------------------------------------
        ledger_path = Path(tmp) / "ledger.jsonl"
        with LedgerWriter(ledger_path) as w:
            w.append("audit", {"tool": "memreckon-validate"})
            w.append("summary", {"counts": {}})
        chain_ok, problems = verify_ledger(ledger_path)
        results.append(stage("ledger chain round trip", chain_ok, "; ".join(problems)))
    results.append(stage("four-stamp fixture proof (both adapters)", proof_ok, detail))

    # 5. Required files ------------------------------------------------------
    required = ["README.md", "LICENSE", "NAME_CHECK.md", "COMPLIANCE.md", "pyproject.toml"]
    missing = [name for name in required if not (ROOT / name).exists()]
    results.append(
        stage("required files", not missing, f"missing: {missing}" if missing else "")
    )

    # 6. Secrets scan ----------------------------------------------------------
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in (".pyc",):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                hits.append(f"{path.relative_to(ROOT)}: {pattern.pattern[:24]}...")
    results.append(stage("secrets scan", not hits, "; ".join(hits)))

    print()
    if all(results):
        print("ALL CHECKS PASSED")
        return 0
    print("VALIDATION FAILED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
