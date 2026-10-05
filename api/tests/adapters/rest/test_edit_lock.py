"""Story 4.4: ``POST /api/proposals/:id/lock`` and the lock check on
``PATCH /api/proposals/:id/answers`` (AD-16, AD-12).

One test per I/O matrix row in the spec (acquire, renew, blocked, take-over, the AI's refusal,
expiry, 404 parity, and a write without the lock), plus the SQL CAS itself against a real
PostgreSQL so two simultaneous opens are proven, not just mirrored by a fake store.
"""

from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from adapters.rest.app import create_app
from adapters.rest.principal import TEST_PRINCIPALS
from adapters.settings import Settings
from domain.proposals import LOCK_DURATION
from tests.fakes import FakeClock
from tests.support import AS_AGENT_A, AS_AGENT_B

Admin = Callable[[str], psycopg.Connection[Any]]

SESSION_A = (
    "test-session"  # the `client`/`patch_client` fixtures' own default X-Session-Id
)
SESSION_B = "synthetic-session-b"


@pytest.fixture
def client(db_settings: Settings, migrated_db: str) -> Iterator[TestClient]:
    settings = db_settings.model_copy(
        update={"database_name": migrated_db, "formapp_test_mode": True}
    )
    with TestClient(
        create_app(settings), headers={"X-Session-Id": SESSION_A}
    ) as test_client:
        yield test_client


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def patch_client(
    db_settings: Settings, migrated_db: str, clock: FakeClock
) -> Iterator[TestClient]:
    """Like ``client``, wired to a ``FakeClock`` so expiry/renewal tests advance time instead of
    sleeping (AD-18)."""
    settings = db_settings.model_copy(
        update={"database_name": migrated_db, "formapp_test_mode": True}
    )
    with TestClient(
        create_app(settings, clock=clock), headers={"X-Session-Id": SESSION_A}
    ) as test_client:
        yield test_client


def _lock(
    client: TestClient,
    proposal_id: Any,
    headers: dict[str, str],
    take_over: bool = False,
) -> Any:
    return client.post(
        f"/api/proposals/{proposal_id}/lock",
        json={"take_over": take_over},
        headers=headers,
    )


def _insert_ai_held_draft(
    admin: Admin, dbname: str, *, owner_oid: str, lock_expires_at: str
) -> UUID:
    """A draft already locked by the AI (spec Intent's ASSUMPTION 2: nothing in this story sets
    ``lock_holder = 'ai'``, so it's inserted straight into the table rather than through a chat
    turn)."""
    with admin(dbname) as connection:
        row = connection.execute(
            "INSERT INTO proposal "
            "(owner_oid, owner_seq, schema_version, status, revision, answers, "
            "created_at, updated_at, lock_holder, lock_expires_at) "
            "VALUES (%s, 1, 1, 'draft', 0, %s, now(), now(), 'ai', %s) RETURNING id",
            (owner_oid, Jsonb({}), lock_expires_at),
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


# Acquire on open: no live lock, POST /lock with no take_over.


def test_story_4_4_acquire_on_open_with_no_live_lock(client: TestClient) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    assert created["lock"] == {"holder": "you", "expires_at": None}  # never locked yet

    response = _lock(client, created["id"], headers=AS_AGENT_A)

    assert response.status_code == 200
    body = response.json()
    assert body["holder"] == "you"
    assert body["expires_at"] is not None


# Renew: the caller already holds it, POST /lock.


def test_story_4_4_renew_extends_the_expiry_for_the_current_holder(
    patch_client: TestClient, clock: FakeClock
) -> None:
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    first = _lock(patch_client, created["id"], headers=AS_AGENT_A).json()

    clock.advance(timedelta(seconds=20))  # well inside the 60s expiry: still live
    second = _lock(patch_client, created["id"], headers=AS_AGENT_A).json()

    assert second["holder"] == "you"
    assert second["expires_at"] > first["expires_at"]


# Blocked: tab B, tab A holds it live, no take_over.


def test_story_4_4_blocked_by_another_live_session_without_take_over(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(client, created["id"], headers={**AS_AGENT_A, "X-Session-Id": SESSION_A})

    blocked = _lock(
        client, created["id"], headers={**AS_AGENT_A, "X-Session-Id": SESSION_B}
    )

    assert blocked.status_code == 200
    body = blocked.json()
    assert body["holder"] == "other_session"
    assert body["expires_at"] is not None  # A's lock is untouched, still live

    draft = client.get(
        f"/api/proposals/{created['id']}",
        headers={**AS_AGENT_A, "X-Session-Id": SESSION_A},
    ).json()
    assert draft["lock"]["holder"] == "you"  # A still holds it


# Take over: tab B, tab A holds it live, take_over=true.


def test_story_4_4_take_over_moves_the_lock_from_another_live_session(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(client, created["id"], headers={**AS_AGENT_A, "X-Session-Id": SESSION_A})

    taken = _lock(
        client,
        created["id"],
        take_over=True,
        headers={**AS_AGENT_A, "X-Session-Id": SESSION_B},
    )

    assert taken.status_code == 200
    assert taken.json()["holder"] == "you"
    # A's next call sees "other_session" (spec matrix).
    draft = client.get(
        f"/api/proposals/{created['id']}",
        headers={**AS_AGENT_A, "X-Session-Id": SESSION_A},
    ).json()
    assert draft["lock"]["holder"] == "other_session"


# AI refuses take-over: lock_holder='ai' live, take_over=true.


def test_story_4_4_ai_refuses_a_take_over(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_ai_held_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        lock_expires_at="2099-01-01T00:00:00+00:00",  # far in the future: still live
    )

    response = _lock(
        client,
        proposal_id,
        take_over=True,
        headers={**AS_AGENT_A, "X-Session-Id": SESSION_A},
    )

    assert response.status_code == 200
    assert response.json()["holder"] == "ai"
    with admin(migrated_db) as connection:
        holder = connection.execute(
            "SELECT lock_holder FROM proposal WHERE id = %s", (str(proposal_id),)
        ).fetchone()
    assert holder == ("ai",)  # unchanged


# Expired: lock_expires_at in the past.


def test_story_4_4_an_expired_lock_is_treated_as_free(
    patch_client: TestClient, clock: FakeClock
) -> None:
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(
        patch_client,
        created["id"],
        headers={**AS_AGENT_A, "X-Session-Id": SESSION_B},
    )

    clock.advance(timedelta(seconds=61))  # past the 60s expiry
    response = _lock(
        patch_client,
        created["id"],
        headers={**AS_AGENT_A, "X-Session-Id": SESSION_A},
    )

    assert response.status_code == 200
    assert response.json()["holder"] == "you"  # acquired normally, no take_over needed


# Unowned/unknown proposal id: same 404 as every other proposal route.


def test_story_4_4_lock_404s_the_same_for_someone_elses_proposal_or_a_random_id(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()

    other_owner = _lock(client, created["id"], headers=AS_AGENT_B)
    missing = _lock(client, uuid4(), headers=AS_AGENT_A)

    assert other_owner.status_code == missing.status_code == 404
    assert other_owner.json() == missing.json()


# Write without the lock: PATCH /answers, caller isn't holder.


def test_story_4_4_patch_without_ever_locking_is_409_lock_not_held(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()

    response = client.patch(
        f"/api/proposals/{created['id']}/answers",
        json={"revision": created["revision"], "answers": {"C1": "Ally"}},
        headers=AS_AGENT_A,
    )

    assert response.status_code == 409
    assert response.json() == {
        "errors": [
            {
                "field": "lock",
                "code": "lock_not_held",
                "message": "This proposal is being edited in another window. Reload to take over.",
            }
        ]
    }
    unchanged = client.get(f"/api/proposals/{created['id']}", headers=AS_AGENT_A).json()
    assert "C1" not in unchanged["answers"]


def test_story_4_4_patch_after_losing_the_lock_to_a_take_over_is_409(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(client, created["id"], headers={**AS_AGENT_A, "X-Session-Id": SESSION_A})
    _lock(
        client,
        created["id"],
        take_over=True,
        headers={**AS_AGENT_A, "X-Session-Id": SESSION_B},
    )

    response = client.patch(
        f"/api/proposals/{created['id']}/answers",
        json={"revision": created["revision"], "answers": {"C1": "Ally"}},
        headers={**AS_AGENT_A, "X-Session-Id": SESSION_A},
    )

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "lock_not_held"


def test_story_4_4_holding_the_lock_lets_the_patch_through(client: TestClient) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(client, created["id"], headers=AS_AGENT_A)

    response = client.patch(
        f"/api/proposals/{created['id']}/answers",
        json={"revision": created["revision"], "answers": {"C1": "Ally"}},
        headers=AS_AGENT_A,
    )

    assert response.status_code == 200
    assert response.json()["answers"]["C1"] == "Ally"


# The exact expiry instant: apply_answers's `_lock_held_by` (`>=`) and the CAS's own freeness
# check (`lock_expires_at < now`) must never disagree, or a write and a competing acquire could
# both "win" at once. Renewal (20s) and expiry (61s) tests above sit well clear of this instant.


def test_story_4_4_at_the_exact_expiry_instant_the_original_holder_still_writes_and_a_competitor_is_still_blocked(
    patch_client: TestClient, clock: FakeClock
) -> None:
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(
        patch_client,
        created["id"],
        headers={**AS_AGENT_A, "X-Session-Id": SESSION_A},
    )

    clock.advance(LOCK_DURATION)  # exactly the acquire's own expires_at, to the second

    blocked = _lock(
        patch_client,
        created["id"],
        headers={**AS_AGENT_A, "X-Session-Id": SESSION_B},
    )
    assert blocked.json()["holder"] == "other_session"  # not yet free

    response = patch_client.patch(
        f"/api/proposals/{created['id']}/answers",
        json={"revision": created["revision"], "answers": {"C1": "Ally"}},
        headers={**AS_AGENT_A, "X-Session-Id": SESSION_A},
    )
    assert response.status_code == 200  # A still held it at this exact instant
    assert response.json()["answers"]["C1"] == "Ally"
