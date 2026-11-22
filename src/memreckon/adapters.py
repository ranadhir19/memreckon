"""Store adapters: lift remembered statements out of a memory store.

An adapter's only job is faithful ingestion -- it never judges truth.
Two adapters ship in v1:

``memoryvault``
    Ranadhir's memoryvault-agents store, in any of its durable forms:
    a directory of MemoryDoc Markdown files (frontmatter ``facts`` list),
    a single such file, or the JSON state export of its in-memory store
    (``{"memories": [...]}``). No code is shared with memoryvault-agents;
    this adapter implements its documented file formats so the auditor can
    sit on top of the store as a read-path layer.

``markdown``
    The generic plain-Markdown adapter: CLAUDE.md / AGENTS.md /
    ai-memory-style files. Every bullet or paragraph line is an entry.
    This is the adapter that makes memreckon work on any store whose
    memory is, in the end, text files -- which is most of them.

New stores are added by implementing ``StoreAdapter`` and registering in
``ADAPTERS``; the extraction, checking, ledger, and gate layers do not
change.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

from .frontmatter import parse_frontmatter, split_frontmatter
from .model import Entry

_BODY_FACT_RE = re.compile(r"^\s*[-*]\s+\*\*(.+?)\*\*:\s*(.+?)\s*$")


class StoreAdapter(Protocol):
    name: str

    def can_handle(self, path: Path) -> bool: ...

    def entries(self, path: Path) -> list[Entry]: ...


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fact_provenance(fact: dict[str, Any]) -> str:
    src = fact.get("source") or fact.get("sources") or ""
    if isinstance(src, list):
        return ", ".join(str(s) for s in src)
    return str(src)


class MemoryVaultAdapter:
    """Ingest memoryvault-agents MemoryDocs (Markdown or JSON state)."""

    name = "memoryvault"

    def can_handle(self, path: Path) -> bool:
        if path.is_file() and path.suffix == ".json":
            return True
        if path.is_file() and path.suffix == ".md":
            block, _ = split_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
            return block is not None and "facts:" in block
        if path.is_dir():
            return any(
                self.can_handle(p) for p in path.rglob("*.md")
            ) or any(p.suffix == ".json" for p in path.rglob("*.json"))
        return False

    def entries(self, path: Path) -> list[Entry]:
        out: list[Entry] = []
        for f in _iter_store_files(path, (".md", ".json")):
            if f.suffix == ".json":
                out.extend(self._entries_from_json(f))
            else:
                out.extend(self._entries_from_markdown(f))
        return out

    # -- JSON state export ------------------------------------------------
    def _entries_from_json(self, f: Path) -> list[Entry]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
        docs: Iterable[Any]
        if isinstance(data, dict):
            docs = data.get("memories", [])
        elif isinstance(data, list):
            docs = data
        else:
            docs = []
        out: list[Entry] = []
        for doc in docs:
            if isinstance(doc, dict):
                out.extend(self._entries_from_doc(doc, f.name, doc.get("path", "")))
        return out

    # -- MemoryDoc Markdown ------------------------------------------------
    def _entries_from_markdown(self, f: Path) -> list[Entry]:
        text = f.read_text(encoding="utf-8", errors="replace")
        block, body = split_frontmatter(text)
        if block is not None:
            meta = parse_frontmatter(block)
            facts = meta.get("facts")
            if isinstance(facts, list) and facts and isinstance(facts[0], dict):
                doc = {
                    "path": f.name,
                    "facts": facts,
                    "updated_at": meta.get("updated_at"),
                }
                return self._entries_from_doc(doc, f.name, f.name)
        # Fallback: the rendered body carries the same facts as
        # "- **subject**: value" lines.
        out: list[Entry] = []
        mtime = f.stat().st_mtime
        for idx, line in enumerate(body.splitlines()):
            m = _BODY_FACT_RE.match(line)
            if m:
                subject, value = m.group(1).strip(), m.group(2).strip()
                out.append(self._entry(f.name, idx, subject, value, mtime, ""))
        return out

    def _entries_from_doc(
        self, doc: dict[str, Any], source_name: str, doc_path: str
    ) -> list[Entry]:
        out: list[Entry] = []
        doc_updated = _as_float(doc.get("updated_at"))
        facts = doc.get("facts") or []
        for idx, fact in enumerate(facts):
            if not isinstance(fact, dict):
                continue
            subject = str(fact.get("subject", "")).strip()
            value = str(fact.get("value", "")).strip()
            if not subject and not value:
                continue
            locator = f"{doc_path or source_name}#fact[{idx}]"
            updated = _as_float(fact.get("updated_at"))
            if updated is None:
                updated = doc_updated
            out.append(
                self._entry(
                    locator,
                    idx,
                    subject,
                    value,
                    updated,
                    _fact_provenance(fact),
                )
            )
        return out

    def _entry(
        self,
        locator: str,
        idx: int,
        subject: str,
        value: str,
        updated: Optional[float],
        provenance: str,
    ) -> Entry:
        text = f"{subject}: {value}" if subject else value
        return Entry(
            id=Entry.make_id(self.name, locator, text),
            store=self.name,
            locator=locator,
            text=text,
            subject=subject,
            value=value,
            updated_at=updated,
            provenance=provenance,
        )


class MarkdownAdapter:
    """Ingest plain-Markdown memory files (CLAUDE.md / AGENTS.md style)."""

    name = "markdown"

    def can_handle(self, path: Path) -> bool:
        if path.is_file():
            return path.suffix in (".md", ".markdown", ".txt")
        return path.is_dir()

    def entries(self, path: Path) -> list[Entry]:
        out: list[Entry] = []
        for f in _iter_store_files(path, (".md", ".markdown", ".txt")):
            out.extend(self._entries_from_file(f))
        return out

    def _entries_from_file(self, f: Path) -> list[Entry]:
        text = f.read_text(encoding="utf-8", errors="replace")
        _, body = split_frontmatter(text)
        mtime = f.stat().st_mtime
        out: list[Entry] = []
        in_fence = False
        for lineno, raw in enumerate(body.splitlines(), start=1):
            line = raw.strip()
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or not line:
                continue
            if line.startswith("#") or line in ("---", "***", "___"):
                continue
            if line.startswith("<!--"):
                continue
            # Bullets and numbered items become single entries; other
            # lines are entries too (a paragraph line is a statement).
            line = re.sub(r"^[-*+]\s+", "", line)
            line = re.sub(r"^\d+[.)]\s+", "", line)
            if len(line) < 4:
                continue
            locator = f"{f.name}:{lineno}"
            out.append(
                Entry(
                    id=Entry.make_id(self.name, locator, line),
                    store=self.name,
                    locator=locator,
                    text=line,
                    subject="",
                    value=line,
                    updated_at=mtime,
                    provenance="",
                )
            )
        return out


def _iter_store_files(path: Path, suffixes: tuple[str, ...]) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(
            p
            for p in path.rglob("*")
            if p.is_file() and p.suffix in suffixes and ".git" not in p.parts
        )
    return []


ADAPTERS: dict[str, StoreAdapter] = {
    MemoryVaultAdapter.name: MemoryVaultAdapter(),
    MarkdownAdapter.name: MarkdownAdapter(),
}


def get_adapter(name: str, path: Path) -> StoreAdapter:
    """Resolve an adapter by name, or auto-detect when name == 'auto'."""
    if name != "auto":
        return ADAPTERS[name]
    for candidate in (ADAPTERS["memoryvault"], ADAPTERS["markdown"]):
        if candidate.can_handle(path):
            return candidate
    return ADAPTERS["markdown"]
