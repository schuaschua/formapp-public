"""Story 7.3/FORM-239: `domain.feedback_export.salted_hash`, the one anonymising primitive the
feedback snapshot uses for both `proposal_hash` and `agent_hash` (spine AD-20, FR65)."""

from domain.feedback_export import salted_hash


def test_form_239_same_value_and_salt_hash_the_same_way() -> None:
    assert salted_hash("agent-oid-a", "salt-1") == salted_hash("agent-oid-a", "salt-1")


def test_form_239_different_salts_hash_differently() -> None:
    assert salted_hash("agent-oid-a", "salt-1") != salted_hash("agent-oid-a", "salt-2")


def test_form_239_different_values_hash_differently() -> None:
    assert salted_hash("agent-oid-a", "salt-1") != salted_hash("agent-oid-b", "salt-1")


def test_form_239_the_digest_never_contains_the_raw_value() -> None:
    digest = salted_hash("synthetic-agent-oid", "synthetic-salt")
    assert "synthetic-agent-oid" not in digest
    # A SHA-256 hex digest: 64 lowercase hex characters.
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)
