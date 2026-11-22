"""Gate mode: turn an audit into session-start context an agent can trust.

The failure this prevents is quiet and common: a harness injects memory
at session start, one entry is simply false now (the file was deleted,
the tests broke, the version moved), and the agent builds on it for
hours. The gate renders memory in four clearly separated sections:

- TRUSTED     -- VERIFIED entries, safe to inject as fact.
- STALE       -- still true when checked, but flagged with the warning.
- UNVERIFIED  -- not mechanically checkable; labelled unconfirmed,
                 never presented as fact.
- QUARANTINED -- REFUTED entries, shown *only* with their contradicting
                 evidence, so a human can fix the store -- and so the
                 agent knows the claim is false rather than merely absent.

Nothing is silently deleted: quarantine is a flag with evidence, and the
store itself is never modified by memreckon.
"""

from __future__ import annotations

import json
import time
from typing import Any

from . import model
from .audit import AuditResult


def _evidence_line(verdict) -> str:
    ev = verdict.evidence or {}
    parts = []
    for key in ("path", "symbol", "package", "key", "kind", "command", "runner"):
        if key in ev:
            parts.append(f"{key}={ev[key]}")
    if "exit_code" in ev:
        parts.append(f"exit_code={ev['exit_code']}")
    if "manifest_spec" in ev:
        parts.append(f"manifest={ev['manifest_spec']}")
    if "actual" in ev:
        parts.append(f"actual={ev['actual']}")
    if "stale" in ev and isinstance(ev["stale"], dict):
        parts.append(f"changed artifact: {ev['stale'].get('artifact')}")
    return "; ".join(parts)


def render_gate_markdown(result: AuditResult) -> str:
    counts = result.counts()
    by_id = {e.id: e for e in result.entries}
    sections: dict[str, list[str]] = {
        model.VERIFIED: [],
        model.STALE: [],
        model.UNVERIFIABLE: [],
        model.REFUTED: [],
    }
    for v in result.verdicts:
        entry = by_id[v.entry_id]
        sections[v.stamp].append(f"- {entry.text}  _(via {entry.locator})_")

    lines = [
        "# Session context -- audited by memreckon",
        "",
        f"Audited {time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime())} against "
        f"`{result.repo}`: {counts[model.VERIFIED]} verified, {counts[model.STALE]} stale, "
        f"{counts[model.UNVERIFIABLE]} unverified, {counts[model.REFUTED]} refuted.",
        "",
        "## Trusted (verified against the live repository)",
        "",
    ]
    lines += sections[model.VERIFIED] or ["- (none)"]
    lines += ["", "## Stale -- still true when checked, but re-confirm before relying on it", ""]
    lines += sections[model.STALE] or ["- (none)"]
    lines += ["", "## Unverified -- not mechanically checkable; treat as unconfirmed", ""]
    lines += sections[model.UNVERIFIABLE] or ["- (none)"]
    lines += ["", "## QUARANTINED -- refuted by the live repository; do NOT act on these", ""]
    quarantined = []
    for v in result.verdicts:
        if v.stamp == model.REFUTED:
            entry = by_id[v.entry_id]
            quarantined.append(
                f"- ~~{entry.text}~~ -- refuted: {_evidence_line(v)} _(via {entry.locator})_"
            )
    lines += quarantined or ["- (none)"]
    lines.append("")
    return "\n".join(lines)


def gate_payload(result: AuditResult) -> dict[str, Any]:
    """Structured gate output (for hooks and the MCP-style adapter)."""
    by_id = {e.id: e for e in result.entries}
    out: dict[str, Any] = {
        "counts": result.counts(),
        "trusted": [],
        "stale": [],
        "unverified": [],
        "quarantined": [],
    }
    bucket = {
        model.VERIFIED: "trusted",
        model.STALE: "stale",
        model.UNVERIFIABLE: "unverified",
        model.REFUTED: "quarantined",
    }
    for v in result.verdicts:
        entry = by_id[v.entry_id]
        item = {
            "text": entry.text,
            "locator": entry.locator,
            "claim_type": v.claim_type,
            "stamp": v.stamp,
        }
        if v.stamp == model.REFUTED:
            item["contradicting_evidence"] = v.evidence
        out[bucket[v.stamp]].append(item)
    out["context_markdown"] = render_gate_markdown(result)
    return out


def render_gate_json(result: AuditResult) -> str:
    return json.dumps(gate_payload(result), indent=2)
