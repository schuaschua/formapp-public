"""The feedback snapshot's one anonymising primitive (Story 7.3/FORM-239, spine AD-20, FR65): a
salted SHA-256 hex digest, used for both the exported ``agent_hash`` (of ``given_by``, the agent's
`oid`) and the exported ``proposal_hash`` (of the proposal id) -- the same formula for both, so the
snapshot never carries a raw `oid` or a raw database primary key, only a deterministic, opaque
stand-in a lead can still group and count by across nightly runs.

A pure function, so it needs no database, no Storage and no Foundry to test (spine AD-18): given the
same salt, the same input always hashes to the same digest, and a different salt changes every
digest (the salt is `FEEDBACK_EXPORT_SALT`, a Container Apps secret -- `jobs.feedback` reads it,
never this module).
"""

import hashlib


def salted_hash(value: str, salt: str) -> str:
    """A stable, opaque SHA-256 hex digest of ``value`` salted with ``salt``. Never logged, and the
    only thing derived from ``value`` that ever leaves `api` for the snapshot (security.md rule 2)."""
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()
