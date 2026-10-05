"""Story 4.3 P0: every attack on the turn token is rejected, on every tool, and nothing about the
proposal (or any other proposal) is ever read or written on a rejection (spine AD-4, AD-16,
security.md rule 36).

Against a real migrated database, driven over the real Streamable HTTP wire, so these prove the
whole stack -- the ASGI dispatch, the Authorization header extraction, decode/resolve, and the
adapter's rejection mapping -- not just the domain functions underneath (those have their own,
narrower unit tests in ``tests/domain/test_turn_tokens.py``).
"""

import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import jwt
import psycopg
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from adapters.db.proposals import SqlProposalStore
from adapters.db.scope import for_owner, scoped
from adapters.rest.app import create_app
from adapters.rest.principal import TEST_PRINCIPALS
from adapters.settings import Settings
from domain.proposals import AI_TURN_SAFETY_WINDOW, LOCK_DURATION, create_draft
from domain.turn_tokens import TURN_TOKEN_TTL, issue_turn_token
from tests.adapters.mcp.support import call_tool, running_app
from tests.fakes import FakeClock
from tests.support import TEST_SIGNING_KEY

pytestmark = pytest.mark.p0

Admin = Callable[[str], psycopg.Connection[Any]]

OWNER_A = TEST_PRINCIPALS["agent-a"].oid
OWNER_B = TEST_PRINCIPALS["agent-b"].oid
FORGED_KEY = SecretStr("attacker-controlled-signing-key-x")
_TEST_KEY = SecretStr(TEST_SIGNING_KEY)

# Every tool, with the arguments it needs (Story 4.3, AC5/AC7): each attack scenario runs all five.
TOOL_CALLS: tuple[tuple[str, dict[str, Any] | None], ...] = (
    ("get_form_schema", None),
    ("get_draft", None),
    ("patch_draft", {"answers": {"C1": "Ally"}}),
    ("validate_draft", None),
    ("get_products", None),
)

_LOCK_NOT_HELD_BODY_CODE = "lock_not_held"


def _app(db_settings: Settings, migrated_db: str, clock: FakeClock) -> FastAPI:
    settings = db_settings.model_copy(update={"database_name": migrated_db})
    return create_app(settings, clock=clock)


async def _create_and_lock(app: FastAPI, owner_oid: str, clock: FakeClock) -> UUID:
    """A fresh draft with the edit lock already held by ``ai`` (no turn id yet -- ``_mint_bound``
    is what sets that, since it has to match whatever ``issue_turn_token`` mints).

    A direct store call, outside any REST or MCP request: unlike production, nothing sets the
    row-level security scope here, so this fixture sets it itself, to ``owner_oid``'s own scope
    (Story 4.3 Part B, AD-17).
    """
    store = SqlProposalStore(app.state.engine)
    with scoped(for_owner(owner_oid)):
        proposal = await create_draft(store, owner_oid, clock)
        await store.set_turn(
            proposal.id,
            lock_holder="ai",
            lock_expires_at=clock.now() + LOCK_DURATION,
            current_turn_id=None,
        )
    return proposal.id


async def _mint_bound(
    app: FastAPI, proposal_id: UUID, owner_oid: str, clock: FakeClock
) -> str:
    """Mint a real turn token via ``issue_turn_token`` (AC1, unmodified) and thread its own freshly
    minted ``tid`` into the store's ``current_turn_id`` -- the coordination Story 4.5's chat
    adapter will do for real; here it's what makes the minted token genuinely turn-bound. Calling
    this twice for the same proposal begins a fresh turn, the way :func:`begin_turn` does, but
    lets the token's own ``tid`` decide the value rather than minting an unrelated one.

    Also a direct store call outside any request; scoped to ``owner_oid`` for the same reason as
    ``_create_and_lock`` (AD-17)."""
    store = SqlProposalStore(app.state.engine)
    with scoped(for_owner(owner_oid)):
        token = await issue_turn_token(
            store, proposal_id, owner_oid, clock, app.state.settings.turn_token_signing_key
        )
        tid = UUID(jwt.decode(token, options={"verify_signature": False})["tid"])
        await store.set_turn(
            proposal_id,
            lock_holder="ai",
            lock_expires_at=clock.now() + LOCK_DURATION,
            current_turn_id=tid,
        )
    return token


async def _bound_proposal(app: FastAPI, owner_oid: str, clock: FakeClock) -> tuple[UUID, str]:
    """A fresh draft, already turn-bound to the AI, with a token that genuinely matches."""
    proposal_id = await _create_and_lock(app, owner_oid, clock)
    token = await _mint_bound(app, proposal_id, owner_oid, clock)
    return proposal_id, token


def _row_snapshot(admin: Admin, dbname: str, proposal_id: UUID) -> tuple[Any, ...]:
    with admin(dbname) as connection:
        row = connection.execute(
            "SELECT answers, revision, lock_holder, lock_expires_at, current_turn_id "
            "FROM proposal WHERE id = %s",
            (str(proposal_id),),
        ).fetchone()
    assert row is not None
    return tuple(row)


def _forge(
    *,
    sub: str,
    pid: UUID,
    tid: UUID,
    now: Any,
    exp_delta: timedelta = TURN_TOKEN_TTL,
    key: SecretStr = _TEST_KEY,
) -> str:
    payload = {
        "sub": sub,
        "pid": str(pid),
        "tid": str(tid),
        "exp": now + exp_delta,
    }
    return jwt.encode(payload, key.get_secret_value(), algorithm="HS256")


async def _assert_every_tool_rejected(app: FastAPI, token: str | None) -> None:
    for name, arguments in TOOL_CALLS:
        result = await call_tool(app, token, name, arguments)
        assert len(result["errors"]) == 1, f"{name} did not reject uniformly: {result}"
        error = result["errors"][0]
        assert (error["field"], error["code"]) == (
            "turn",
            _LOCK_NOT_HELD_BODY_CODE,
        ), f"{name}: {error}"


def test_p0_a_forged_signature_is_rejected_on_every_tool(
    db_settings: Settings, migrated_db: str, admin: Admin
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> tuple[UUID, tuple[Any, ...]]:
        async with running_app(app):
            proposal_id, legit = await _bound_proposal(app, OWNER_A, clock)
            claims = jwt.decode(legit, options={"verify_signature": False})
            forged = _forge(
                sub=claims["sub"],
                pid=UUID(claims["pid"]),
                tid=UUID(claims["tid"]),
                now=clock.now(),
                key=FORGED_KEY,
            )
            await _assert_every_tool_rejected(app, forged)
            return proposal_id, _row_snapshot(admin, migrated_db, proposal_id)

    proposal_id, snapshot = asyncio.run(scenario())
    assert _row_snapshot(admin, migrated_db, proposal_id) == snapshot
    assert snapshot[1] == 0  # revision: nothing was ever applied


def test_p0_an_expired_token_is_rejected_on_every_tool(
    db_settings: Settings, migrated_db: str, admin: Admin
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> UUID:
        async with running_app(app):
            proposal_id, token = await _bound_proposal(app, OWNER_A, clock)
            clock.advance(TURN_TOKEN_TTL)  # exactly at exp: already expired
            await _assert_every_tool_rejected(app, token)
            return proposal_id

    proposal_id = asyncio.run(scenario())
    snapshot = _row_snapshot(admin, migrated_db, proposal_id)
    assert snapshot[1] == 0


def test_p0_a_tampered_pid_is_rejected_on_every_tool(
    db_settings: Settings, migrated_db: str, admin: Admin
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> tuple[UUID, UUID]:
        async with running_app(app):
            owned, legit = await _bound_proposal(app, OWNER_A, clock)
            other, _other_token = await _bound_proposal(app, OWNER_B, clock)
            claims = jwt.decode(legit, options={"verify_signature": False})
            # A well-formed, correctly signed token (this test controls the signing key only to
            # build the fixture) naming a proposal its own subject doesn't own.
            tampered = _forge(
                sub=claims["sub"], pid=other, tid=UUID(claims["tid"]), now=clock.now()
            )
            await _assert_every_tool_rejected(app, tampered)
            return owned, other

    owned, other = asyncio.run(scenario())
    assert _row_snapshot(admin, migrated_db, owned)[1] == 0
    assert _row_snapshot(admin, migrated_db, other)[1] == 0


def test_p0_a_stale_tid_is_rejected_on_every_tool(
    db_settings: Settings, migrated_db: str, admin: Admin
) -> None:
    """An earlier turn's token, replayed after a fresh AI turn began on the same proposal."""
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> UUID:
        async with running_app(app):
            proposal_id, stale = await _bound_proposal(app, OWNER_A, clock)
            # A fresh turn begins on the same proposal, replacing current_turn_id.
            await _mint_bound(app, proposal_id, OWNER_A, clock)
            await _assert_every_tool_rejected(app, stale)
            return proposal_id

    proposal_id = asyncio.run(scenario())
    assert _row_snapshot(admin, migrated_db, proposal_id)[1] == 0


def test_p0_a_token_for_a_is_rejected_once_the_turn_moves_to_b(
    db_settings: Settings, migrated_db: str, admin: Admin
) -> None:
    """A token for turn A, replayed after that turn ended and a human session B has since taken
    the now-free edit lock (the AI's own live lock can never be taken over -- Story 4.4 -- so the
    only way "the turn moves to B" is the turn ending first): the AI's still-unexpired,
    still-correctly-signed token is rejected all the same."""
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> UUID:
        async with running_app(app):
            proposal_id, token = await _bound_proposal(app, OWNER_A, clock)
            store = SqlProposalStore(app.state.engine)
            # Direct store calls outside any request; scoped to OWNER_A, same as the fixture above
            # (AD-17).
            with scoped(for_owner(OWNER_A)):
                await store.set_turn(
                    proposal_id, lock_holder=None, lock_expires_at=None, current_turn_id=None
                )
                await store.acquire_lock(
                    proposal_id,
                    "synthetic-human-session-b",
                    clock.now(),
                    clock.now() + timedelta(seconds=60),
                    take_over=False,
                )
            await _assert_every_tool_rejected(app, token)
            return proposal_id

    proposal_id = asyncio.run(scenario())
    assert _row_snapshot(admin, migrated_db, proposal_id)[1] == 0


def test_p0_another_agents_own_valid_token_touches_only_its_own_proposal(
    db_settings: Settings, migrated_db: str, admin: Admin
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> tuple[UUID, tuple[Any, ...], UUID, dict[str, Any]]:
        async with running_app(app):
            proposal_a, _token_a = await _bound_proposal(app, OWNER_A, clock)
            before_a = _row_snapshot(admin, migrated_db, proposal_a)
            proposal_b, token_b = await _bound_proposal(app, OWNER_B, clock)
            result = await call_tool(
                app, token_b, "patch_draft", {"answers": {"C1": "Bala"}}
            )
            return proposal_a, before_a, proposal_b, result

    proposal_a, before_a, proposal_b, result = asyncio.run(scenario())

    assert result == {"applied": ["C1"], "errors": [], "revision": 1}
    # B's own proposal changed; A's is byte-for-byte unchanged.
    assert _row_snapshot(admin, migrated_db, proposal_a) == before_a
    snapshot_b = _row_snapshot(admin, migrated_db, proposal_b)
    assert snapshot_b[1] == 1
    assert snapshot_b[0]["C1"]["value"] == "Bala"


def test_p0_the_5_minute_safety_expiry_is_rejected_even_with_a_matching_tid(
    db_settings: Settings, migrated_db: str, admin: Admin
) -> None:
    """Story 4.5, AC2: the turn token itself (10-minute TTL) is still valid, but the proposal's
    own 5-minute AI-lock safety window (:data:`~domain.proposals.AI_TURN_SAFETY_WINDOW`, distinct
    from the human lock's 60s ``LOCK_DURATION``) has passed -- still rejected, even though ``tid``
    matches."""
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> UUID:
        async with running_app(app):
            proposal_id = await _create_and_lock(app, OWNER_A, clock)
            store = SqlProposalStore(app.state.engine)
            # A direct store call outside any REST or MCP request: scoped to OWNER_A's own scope,
            # same as _create_and_lock/_mint_bound above (Story 4.3 Part B, AD-17).
            with scoped(for_owner(OWNER_A)):
                token = await issue_turn_token(
                    store, proposal_id, OWNER_A, clock, app.state.settings.turn_token_signing_key
                )
                tid = UUID(jwt.decode(token, options={"verify_signature": False})["tid"])
                await store.set_turn(
                    proposal_id,
                    lock_holder="ai",
                    lock_expires_at=clock.now() + AI_TURN_SAFETY_WINDOW,
                    current_turn_id=tid,
                )
            clock.advance(AI_TURN_SAFETY_WINDOW + timedelta(seconds=1))  # past it, not just at it
            await _assert_every_tool_rejected(app, token)
            return proposal_id

    proposal_id = asyncio.run(scenario())
    assert _row_snapshot(admin, migrated_db, proposal_id)[1] == 0


def test_p0_lock_not_held_by_ai_is_rejected_even_with_a_matching_tid(
    db_settings: Settings, migrated_db: str, admin: Admin
) -> None:
    """Story 4.5, AC2: the lock moved to a human session (current_turn_id left untouched) --
    rejected all the same, even though the token's ``tid`` still matches the stored one."""
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> UUID:
        async with running_app(app):
            proposal_id, token = await _bound_proposal(app, OWNER_A, clock)
            store = SqlProposalStore(app.state.engine)
            claims = jwt.decode(token, options={"verify_signature": False})
            # A direct store call outside any REST or MCP request: scoped to OWNER_A's own scope,
            # same as _create_and_lock/_mint_bound above (Story 4.3 Part B, AD-17).
            with scoped(for_owner(OWNER_A)):
                await store.set_turn(
                    proposal_id,
                    lock_holder="synthetic-human-session",
                    lock_expires_at=clock.now() + LOCK_DURATION,
                    current_turn_id=UUID(claims["tid"]),
                )
            await _assert_every_tool_rejected(app, token)
            return proposal_id

    proposal_id = asyncio.run(scenario())
    assert _row_snapshot(admin, migrated_db, proposal_id)[1] == 0


def test_p0_no_token_at_all_is_rejected_on_every_tool(
    db_settings: Settings, migrated_db: str, admin: Admin
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> UUID:
        async with running_app(app):
            proposal_id, _token = await _bound_proposal(app, OWNER_A, clock)
            await _assert_every_tool_rejected(app, None)
            return proposal_id

    proposal_id = asyncio.run(scenario())
    assert _row_snapshot(admin, migrated_db, proposal_id)[1] == 0
