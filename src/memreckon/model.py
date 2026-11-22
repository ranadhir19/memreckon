"""Core data shapes for memreckon.

An ``Entry`` is one remembered statement, lifted out of a memory store by
an adapter. A ``Claim`` is the mechanically checkable reading of an entry
(extracted deterministically -- no model calls). A ``Verdict`` is the
result of re-checking a claim against the live repository, stamped one of
VERIFIED / REFUTED / STALE / UNVERIFIABLE.

The honesty contract of the whole tool lives here: a claim that cannot be
mechanically checked is UNVERIFIABLE with a reason code. It is never
upgraded, guessed at, or silently passed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# The four stamps.
VERIFIED = "VERIFIED"
REFUTED = "REFUTED"
STALE = "STALE"
UNVERIFIABLE = "UNVERIFIABLE"
STAMPS = (VERIFIED, REFUTED, STALE, UNVERIFIABLE)

# Mechanically checkable claim types (v1 taxonomy), plus JUDGMENT for
# everything that is not mechanically checkable.
FILE_EXISTS = "file-exists"
SYMBOL_EXISTS = "symbol-exists"
TEST_OUTCOME = "test-outcome"
DEPENDENCY_VERSION = "dependency-version"
CONFIG_VALUE = "config-value"
COMMAND_OUTCOME = "command-outcome"
GIT_STATE = "git-state"
JUDGMENT = "judgment"
CLAIM_TYPES = (
    FILE_EXISTS,
    SYMBOL_EXISTS,
    TEST_OUTCOME,
    DEPENDENCY_VERSION,
    CONFIG_VALUE,
    COMMAND_OUTCOME,
    GIT_STATE,
    JUDGMENT,
)

# Reason codes for UNVERIFIABLE verdicts.
R_JUDGMENT = "not-mechanically-checkable"
R_NO_TEST_SUITE = "no-test-suite-discovered"
R_COMMANDS_DISABLED = "command-execution-disabled"
R_NOT_A_GIT_REPO = "not-a-git-repository"
R_KEY_NOT_FOUND = "config-key-not-found"
R_AMBIGUOUS = "ambiguous-reference"
R_CHECK_ERROR = "check-could-not-run"


@dataclass
class Entry:
    """One remembered statement from a memory store."""

    id: str
    store: str  # adapter name, e.g. "memoryvault" | "markdown"
    locator: str  # where in the store: "project/state.md#fact[0]" etc.
    text: str  # the claim-bearing text ("subject: value" or the raw line)
    subject: str = ""
    value: str = ""
    updated_at: Optional[float] = None  # epoch seconds, if the store knows
    provenance: str = ""  # source id / author info the store carried

    @staticmethod
    def make_id(store: str, locator: str, text: str) -> str:
        h = hashlib.sha256(f"{store}\x00{locator}\x00{text}".encode("utf-8"))
        return "e_" + h.hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Claim:
    """The checkable reading of an entry."""

    entry_id: str
    claim_type: str
    params: dict[str, Any] = field(default_factory=dict)
    # Artifact paths (relative to the repo) the claim is *about*; used by
    # the staleness rule after a substantive pass.
    targets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Verdict:
    """The outcome of re-checking one claim against the live repository."""

    entry_id: str
    stamp: str  # one of STAMPS
    claim_type: str
    reason: str = ""  # reason code (UNVERIFIABLE) or short explanation
    evidence: dict[str, Any] = field(default_factory=dict)
    checked_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def canonical_json(obj: Any) -> str:
    """Deterministic JSON encoding used for ledger hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
