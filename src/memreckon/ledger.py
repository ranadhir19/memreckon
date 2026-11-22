"""The audit ledger: an append-only, hash-chained record of verdicts.

Every audit run writes a JSONL ledger. Each record carries the SHA-256 of
the previous record, so editing, deleting, or reordering any verdict
after the fact breaks the chain and is detectable with
``memreckon verify-ledger``. This is tamper-*evidence*, stated plainly:
the chain proves a ledger was not altered after it was written; it does
not by itself prove who wrote it. (Identity signing belongs to the
store's own attestation layer; memreckon audits content, not authorship.)
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from .model import canonical_json

GENESIS = "0" * 64
LEDGER_VERSION = 1


def _record_hash(prev: str, body: dict[str, Any]) -> str:
    payload = prev + "\x00" + canonical_json(body)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LedgerWriter:
    """Append hash-chained records to a JSONL file."""

    def __init__(self, path: Path):
        self.path = path
        self.seq = 0
        self.prev = GENESIS
        if path.exists() and path.stat().st_size > 0:
            last = self._last_record(path)
            if last is not None:
                self.seq = int(last.get("seq", 0))
                self.prev = str(last.get("hash", GENESIS))
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", encoding="utf-8")

    @staticmethod
    def _last_record(path: Path) -> Optional[dict[str, Any]]:
        last: Optional[dict[str, Any]] = None
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        last = json.loads(line)
                    except ValueError:
                        return None
        return last

    def append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.seq += 1
        body = {
            "v": LEDGER_VERSION,
            "seq": self.seq,
            "ts": time.time(),
            "kind": kind,
            "payload": payload,
        }
        digest = _record_hash(self.prev, body)
        record = {**body, "prev": self.prev, "hash": digest}
        self._fh.write(canonical_json(record) + "\n")
        self._fh.flush()
        self.prev = digest
        return record

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "LedgerWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def verify_ledger(path: Path) -> tuple[bool, list[str]]:
    """Recompute the chain. Returns (ok, problems)."""
    problems: list[str] = []
    prev = GENESIS
    expected_seq = 0
    seen_any = False
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            seen_any = True
            try:
                record = json.loads(line)
            except ValueError:
                problems.append(f"line {lineno}: not valid JSON")
                break
            expected_seq += 1
            if record.get("seq") != expected_seq:
                problems.append(
                    f"line {lineno}: seq {record.get('seq')} != expected {expected_seq}"
                )
            if record.get("prev") != prev:
                problems.append(f"line {lineno}: prev hash does not match chain")
            body = {k: record[k] for k in ("v", "seq", "ts", "kind", "payload") if k in record}
            if _record_hash(prev, body) != record.get("hash"):
                problems.append(f"line {lineno}: hash mismatch -- record was altered")
            prev = str(record.get("hash", ""))
    if not seen_any:
        problems.append("ledger is empty")
    return (not problems), problems


def read_verdicts(path: Path) -> list[dict[str, Any]]:
    """All verdict payloads from a ledger, in order."""
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("kind") == "verdict":
                out.append(record["payload"])
    return out
