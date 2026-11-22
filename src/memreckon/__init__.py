"""memreckon -- the memory auditor for AI coding agents.

Memory stores remember; nothing checks whether what they remember is
still true. memreckon is the read-path verification layer that sits on
top of a store it does not own: it re-checks the mechanically checkable
claims in agent memory (files, symbols, tests, dependency versions,
config values, git state) against the live repository and stamps every
entry VERIFIED / REFUTED / STALE / UNVERIFIABLE in a hash-chained
ledger, with a gate mode that quarantines refuted memories -- with their
contradicting evidence -- instead of letting the next session trust them.
"""

__version__ = "0.1.0"
