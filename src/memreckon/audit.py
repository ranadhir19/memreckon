"""The audit pipeline: ingest -> extract -> check -> stamp -> ledger.

Staleness rule (applied uniformly, stated here so it can be argued with):
when a checker's substantive check PASSES but an artifact the claim is
about was modified *after* the memory recorded it, the stamp is STALE --
the statement happens to still be true, but the memory predates the
current state of the thing it describes and was never re-confirmed
against it. REFUTED always wins over STALE (a false statement is false,
however fresh). Claims whose store gave no timestamp cannot be assessed
for freshness; they keep their substantive stamp and the evidence says
so.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from . import model
from .adapters import StoreAdapter
from .checkers import CHECKERS, CheckContext, manifest_packages
from .extract import extract_claim
from .ledger import LedgerWriter
from .model import Entry, Verdict

STALE_EPSILON_S = 1.0


@dataclass
class AuditResult:
    entries: list[Entry]
    verdicts: list[Verdict]
    store: str
    repo: str

    def counts(self) -> dict[str, int]:
        out = {stamp: 0 for stamp in model.STAMPS}
        out["judgment"] = 0
        out["total"] = len(self.verdicts)
        for v in self.verdicts:
            out[v.stamp] += 1
            if v.claim_type == model.JUDGMENT:
                out["judgment"] += 1
        return out

    def verdict_for(self, entry_id: str) -> Optional[Verdict]:
        for v in self.verdicts:
            if v.entry_id == entry_id:
                return v
        return None


def audit_entries(
    entries: list[Entry],
    repo: Path,
    store_name: str,
    run_commands: bool = False,
    test_timeout: int = 120,
    store_path: Optional[Path] = None,
) -> AuditResult:
    repo = repo.resolve()
    exclude = [store_path.resolve()] if store_path else []
    ctx = CheckContext(
        repo=repo,
        run_commands=run_commands,
        test_timeout=test_timeout,
        exclude=exclude,
    )
    packages = manifest_packages(repo)
    verdicts: list[Verdict] = []
    for entry in entries:
        claim = extract_claim(entry, packages)
        verdicts.append(_check_one(entry, claim, ctx))
    return AuditResult(entries=entries, verdicts=verdicts, store=store_name, repo=str(repo))


def _check_one(entry: Entry, claim, ctx: CheckContext) -> Verdict:
    now = time.time()
    if claim.claim_type == model.JUDGMENT:
        return Verdict(
            entry_id=entry.id,
            stamp=model.UNVERIFIABLE,
            claim_type=claim.claim_type,
            reason=model.R_JUDGMENT,
            evidence={"note": "entry makes no mechanically checkable claim"},
            checked_at=now,
        )
    checker = CHECKERS[claim.claim_type]
    raw = checker(claim, ctx)
    if raw.outcome == "unable":
        return Verdict(
            entry_id=entry.id,
            stamp=model.UNVERIFIABLE,
            claim_type=claim.claim_type,
            reason=raw.reason,
            evidence=raw.evidence,
            checked_at=now,
        )
    if raw.outcome == "fail":
        return Verdict(
            entry_id=entry.id,
            stamp=model.REFUTED,
            claim_type=claim.claim_type,
            reason="contradicted-by-live-repo",
            evidence=raw.evidence,
            checked_at=now,
        )
    # Substantive pass: apply the staleness rule.
    evidence = dict(raw.evidence)
    if entry.updated_at is None:
        evidence["freshness"] = "not assessed -- the store recorded no timestamp"
        return Verdict(
            entry_id=entry.id,
            stamp=model.VERIFIED,
            claim_type=claim.claim_type,
            evidence=evidence,
            checked_at=now,
        )
    newest: Optional[tuple[float, str]] = None
    for rel in raw.targets:
        target = ctx.repo / rel
        try:
            mtime = target.stat().st_mtime
        except OSError:
            continue
        if newest is None or mtime > newest[0]:
            newest = (mtime, rel)
    if newest is not None and newest[0] > entry.updated_at + STALE_EPSILON_S:
        evidence["stale"] = {
            "artifact": newest[1],
            "artifact_modified_at": newest[0],
            "memory_recorded_at": entry.updated_at,
            "note": "the artifact changed after the memory was written; "
            "the claim still holds, but the memory was never re-confirmed",
        }
        return Verdict(
            entry_id=entry.id,
            stamp=model.STALE,
            claim_type=claim.claim_type,
            reason="artifact-newer-than-memory",
            evidence=evidence,
            checked_at=now,
        )
    return Verdict(
        entry_id=entry.id,
        stamp=model.VERIFIED,
        claim_type=claim.claim_type,
        evidence=evidence,
        checked_at=now,
    )


def run_audit(
    adapter: StoreAdapter,
    store_path: Path,
    repo: Path,
    ledger_path: Optional[Path] = None,
    run_commands: bool = False,
    test_timeout: int = 120,
) -> AuditResult:
    entries = adapter.entries(store_path)
    result = audit_entries(
        entries,
        repo,
        store_name=adapter.name,
        run_commands=run_commands,
        test_timeout=test_timeout,
        store_path=store_path,
    )
    if ledger_path is not None:
        by_id = {e.id: e for e in entries}
        with LedgerWriter(ledger_path) as ledger:
            ledger.append(
                "audit",
                {
                    "tool": "memreckon",
                    "store": adapter.name,
                    "store_path": str(store_path),
                    "repo": str(repo.resolve()),
                    "entries": len(entries),
                },
            )
            for v in result.verdicts:
                entry = by_id[v.entry_id]
                ledger.append(
                    "verdict",
                    {
                        "verdict": v.to_dict(),
                        "entry": {
                            "id": entry.id,
                            "locator": entry.locator,
                            "text": entry.text,
                            "updated_at": entry.updated_at,
                            "provenance": entry.provenance,
                        },
                    },
                )
            ledger.append("summary", {"counts": result.counts()})
    return result


def render_report(result: AuditResult) -> str:
    counts = result.counts()
    lines = [
        "# memreckon audit report",
        "",
        f"- Store adapter: `{result.store}`",
        f"- Repository checked against: `{result.repo}`",
        f"- Entries audited: {counts['total']}",
        "",
        "| Stamp | Count |",
        "|---|---|",
    ]
    for stamp in model.STAMPS:
        lines.append(f"| {stamp} | {counts[stamp]} |")
    lines += ["", "## Entries", ""]
    by_id = {e.id: e for e in result.entries}
    for v in result.verdicts:
        entry = by_id[v.entry_id]
        lines.append(f"### [{v.stamp}] {entry.text}")
        lines.append(f"- locator: `{entry.locator}` · claim type: `{v.claim_type}`")
        if v.reason:
            lines.append(f"- reason: `{v.reason}`")
        for key, val in v.evidence.items():
            lines.append(f"- evidence · {key}: `{val}`")
        lines.append("")
    lines += [
        "## How to read this",
        "",
        "- VERIFIED -- the claim was re-checked against the live repository and holds.",
        "- REFUTED -- the live repository contradicts the claim. Quarantine it.",
        "- STALE -- the claim still holds, but what it describes changed after the",
        "  memory was written; it was never re-confirmed. Re-confirm before relying on it.",
        "- UNVERIFIABLE -- not mechanically checkable, or the check could not run.",
        "  memreckon never upgrades these: an unverifiable memory is an unconfirmed one.",
    ]
    return "\n".join(lines) + "\n"
