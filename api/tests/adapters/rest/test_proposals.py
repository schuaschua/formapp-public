"""Story 1.8: POST/GET /api/proposals and GET /api/proposals/:id (AD-5, AD-8, FR8, FR10, FR11, FR13).

Story 1.10's ``PATCH /api/proposals/:id/answers`` tests (AD-6, AD-12, AD-15) live here too, next to
the fixtures they share.
"""

from collections.abc import Callable, Iterator
from datetime import date, timedelta
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb

from adapters.rest.app import create_app
from adapters.rest.principal import TEST_PRINCIPALS
from adapters.settings import Settings
from domain.customer_numbers import format_customer_number
from domain.schema import load_schema, thaw
from tests.fakes import FakeClock
from tests.support import AS_AGENT_A, AS_AGENT_B

Admin = Callable[[str], psycopg.Connection[Any]]

DRAFT_FIELDS = {
    "id",
    "status",
    "schema_version",
    "revision",
    "lock",
    "active",
    "answers",
    "provenance",
    "quote",
    "display_name",
    "submitted_at",
    "customer_number",
}


@pytest.fixture
def client(db_settings: Settings, migrated_db: str) -> Iterator[TestClient]:
    settings = db_settings.model_copy(
        update={"database_name": migrated_db, "formapp_test_mode": True}
    )
    # X-Session-Id as a client default (security.md rule 23): every write in this file needs it, and
    # it merges with each call's own AS_AGENT_A/AS_AGENT_B principal header.
    with TestClient(
        create_app(settings), headers={"X-Session-Id": "test-session"}
    ) as test_client:
        yield test_client


@pytest.fixture
def clock() -> FakeClock:
    """A fake clock for the PATCH tests that check ``updated_at`` (AD-18: never sleep)."""
    return FakeClock()


@pytest.fixture
def patch_client(
    db_settings: Settings, migrated_db: str, clock: FakeClock
) -> Iterator[TestClient]:
    """Like ``client``, but wired to ``clock`` so a test can assert an exact ``updated_at``."""
    settings = db_settings.model_copy(
        update={"database_name": migrated_db, "formapp_test_mode": True}
    )
    with TestClient(
        create_app(settings, clock=clock), headers={"X-Session-Id": "test-session"}
    ) as test_client:
        yield test_client


def _wire_answers(answers: dict[str, Any]) -> dict[str, Any]:
    return {
        question_id: {
            "value": value,
            "source": "human",
            "updated_at": "2026-09-27T00:00:00Z",
        }
        for question_id, value in answers.items()
    }


def _insert_named_draft(
    admin: Admin,
    dbname: str,
    *,
    owner_oid: str,
    owner_seq: int,
    c1: str = "Ally",
    c13: str = "Macbeal",
) -> UUID:
    """A draft with C1/C13 already answered, inserted straight into the table (Story 1.10 not
    built yet, so there is no write endpoint to reach this state through the API)."""
    answers = _wire_answers({"C1": c1, "C13": c13})
    with admin(dbname) as connection:
        row = connection.execute(
            "INSERT INTO proposal "
            "(owner_oid, owner_seq, schema_version, status, revision, answers, "
            "created_at, updated_at) "
            "VALUES (%s, %s, 1, 'draft', 0, %s, now(), now()) RETURNING id",
            (owner_oid, owner_seq, Jsonb(answers)),
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def _insert_priced_draft(
    admin: Admin,
    dbname: str,
    *,
    owner_oid: str,
    owner_seq: int,
    answers: dict[str, Any],
    created_at: str,
    customer_id: UUID | None = None,
) -> UUID:
    """A draft with P1/P2/C2 already answered at a chosen ``created_at``, inserted straight into
    the table (Story 1.10's PATCH isn't built yet, so there is no write endpoint to reach this
    state through the API; Story 2.2 Part B needs a stored draft to price). ``customer_id``: Story
    3.3's "already linked" submit scenario -- a proposal that already points at a stored customer."""
    with admin(dbname) as connection:
        row = connection.execute(
            "INSERT INTO proposal "
            "(customer_id, owner_oid, owner_seq, schema_version, status, revision, answers, "
            "created_at, updated_at) "
            "VALUES (%s, %s, %s, 1, 'draft', 0, %s, %s, %s) RETURNING id",
            (
                str(customer_id) if customer_id is not None else None,
                owner_oid,
                owner_seq,
                Jsonb(_wire_answers(answers)),
                created_at,
                created_at,
            ),
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def _insert_submitted_draft(
    admin: Admin,
    dbname: str,
    *,
    owner_oid: str,
    owner_seq: int,
    submitted_at: str,
    answers: dict[str, Any] | None = None,
) -> UUID:
    """A submitted proposal, inserted straight into the table (Story 3.2: there is no submit
    endpoint yet, that's Story 3.3/FORM-21)."""
    with admin(dbname) as connection:
        row = connection.execute(
            "INSERT INTO proposal "
            "(owner_oid, owner_seq, schema_version, status, revision, answers, "
            "created_at, updated_at, submitted_at) "
            "VALUES (%s, %s, 1, 'submitted', 0, %s, now(), now(), %s) RETURNING id",
            (owner_oid, owner_seq, Jsonb(_wire_answers(answers or {})), submitted_at),
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def _lock(client: TestClient, proposal_id: Any, **headers: str) -> Any:
    """POST the Story 4.4 edit lock as ``AS_AGENT_A`` (plus the client's default X-Session-Id),
    so a PATCH right after always finds the caller holding it."""
    response = client.post(
        f"/api/proposals/{proposal_id}/lock", json={}, headers={**AS_AGENT_A, **headers}
    )
    assert response.status_code == 200, response.json()
    return response.json()


def _update_answers(
    client: TestClient, proposal_id: UUID, answers: dict[str, Any]
) -> None:
    """PATCH these answers onto a stored draft (Story 1.10), at its current revision. Acquires the
    Story 4.4 edit lock first, since a write now requires holding it."""
    _lock(client, proposal_id)
    current = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    response = client.patch(
        f"/api/proposals/{proposal_id}/answers",
        json={"revision": current["revision"], "answers": answers},
        headers=AS_AGENT_A,
    )
    assert response.status_code == 200, response.json()


# Story 2.2 Part B: the seeded catalogue's FSH (160.00) + Maternity & newborn (R07, 30.00) at
# Ally's age 31 (band 3), the epic's own reference case.
ALLY_ANSWERS = {"P1": "FSH", "P2": ["R07"], "C2": "1994-11-20"}
ALLY_CREATED_AT = "2026-09-25T03:00:00+00:00"
ALLY_QUOTE = {
    "monthly": 219.95,
    "yearly": 2507.42,
    "lines": [
        {"item": "FamilyShield Life & Health", "monthly": 185.22, "yearly": 2111.51},
        {"item": "Maternity & newborn", "monthly": 34.73, "yearly": 395.91},
    ],
}


def test_story_1_8_post_creates_a_fresh_untitled_draft(client: TestClient) -> None:
    response = client.post("/api/proposals", headers=AS_AGENT_A)

    assert response.status_code == 201
    body = response.json()
    assert body.keys() == DRAFT_FIELDS
    assert body["status"] == "draft"
    assert body["revision"] == 0
    assert body["lock"] == {"holder": "you", "expires_at": None}
    # Story 1.10's create-time defaults: every active, unanswered x-simple question is "No".
    assert body["answers"] == {
        "Y3": "No",
        "H7": "No",
        "H8": "No",
        "H9": "No",
        "H10": "No",
        "H11": "No",
        "H12": "No",
        "H13": "No",
        "H14": "No",
    }
    assert {entry["source"] for entry in body["provenance"].values()} == {"default"}
    assert body["quote"] is None
    assert body["display_name"] == "Untitled_Proposal_001"
    assert isinstance(body["schema_version"], int)
    assert isinstance(body["active"], list) and body["active"]
    UUID(body["id"])  # doesn't raise


def test_story_1_8_two_creates_by_one_agent_number_up(client: TestClient) -> None:
    first = client.post("/api/proposals", headers=AS_AGENT_A).json()
    second = client.post("/api/proposals", headers=AS_AGENT_A).json()

    assert first["display_name"] == "Untitled_Proposal_001"
    assert second["display_name"] == "Untitled_Proposal_002"


def test_story_1_8_two_agents_each_start_at_001(client: TestClient) -> None:
    a = client.post("/api/proposals", headers=AS_AGENT_A).json()
    b = client.post("/api/proposals", headers=AS_AGENT_B).json()

    assert a["display_name"] == b["display_name"] == "Untitled_Proposal_001"


def test_story_1_8_get_list_returns_only_the_callers_drafts_newest_first(
    client: TestClient,
) -> None:
    client.post("/api/proposals", headers=AS_AGENT_A)
    client.post("/api/proposals", headers=AS_AGENT_B)
    client.post("/api/proposals", headers=AS_AGENT_A)

    response = client.get("/api/proposals?status=draft", headers=AS_AGENT_A)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert [set(row.keys()) for row in body] == [
        {
            "id",
            "display_name",
            "status",
            "created_at",
            "submitted_at",
            "customer_number",
        }
        for _ in body
    ]
    assert [row["display_name"] for row in body] == [
        "Untitled_Proposal_002",
        "Untitled_Proposal_001",
    ]
    assert {row["status"] for row in body} == {"draft"}


def test_story_1_8_list_is_empty_for_an_agent_with_no_drafts(
    client: TestClient,
) -> None:
    response = client.get("/api/proposals?status=draft", headers=AS_AGENT_A)

    assert response.status_code == 200
    assert response.json() == []


def test_story_1_8_list_with_no_status_param_defaults_to_drafts(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()

    response = client.get("/api/proposals", headers=AS_AGENT_A)

    assert response.status_code == 200
    body = response.json()
    assert [row["id"] for row in body] == [created["id"]]
    assert {row["status"] for row in body} == {"draft"}


def test_story_1_8_named_draft_shows_c1_and_c13_instead_of_untitled(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    _insert_named_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=1,
    )

    response = client.get("/api/proposals?status=draft", headers=AS_AGENT_A)

    assert response.status_code == 200
    [row] = response.json()
    assert row["display_name"] == "Ally_Macbeal_Proposal_001"


def test_form_217_display_name_underscores_a_two_word_first_name_and_trims_whitespace(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    _insert_named_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=8,
        c1="  Wei  Ling ",
        c13=" Tan",
    )

    response = client.get("/api/proposals?status=draft", headers=AS_AGENT_A)

    assert response.status_code == 200
    [row] = response.json()
    assert row["display_name"] == "Wei_Ling_Tan_Proposal_008"


def test_story_1_8_get_by_id_returns_the_draft_shape(client: TestClient) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()

    response = client.get(f"/api/proposals/{created['id']}", headers=AS_AGENT_A)

    assert response.status_code == 200
    assert response.json() == created


def test_story_1_8_get_by_id_404s_the_same_for_someone_elses_proposal_or_a_random_id(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()

    other_owner = client.get(f"/api/proposals/{created['id']}", headers=AS_AGENT_B)
    missing = client.get(f"/api/proposals/{uuid4()}", headers=AS_AGENT_A)

    assert other_owner.status_code == missing.status_code == 404
    assert other_owner.json() == missing.json()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/proposals"),
        ("GET", "/api/proposals?status=draft"),
        ("GET", f"/api/proposals/{uuid4()}"),
        ("GET", f"/api/proposals/{uuid4()}/schema"),
        ("POST", f"/api/proposals/{uuid4()}/validate"),
        ("DELETE", f"/api/proposals/{uuid4()}"),
    ],
)
def test_story_1_8_every_proposal_route_401s_without_a_principal(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path)

    assert response.status_code == 401
    assert "errors" in response.json()


def test_story_1_9_get_schema_returns_the_pinned_version_verbatim(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()

    response = client.get(f"/api/proposals/{created['id']}/schema", headers=AS_AGENT_A)

    assert response.status_code == 200
    expected = load_schema(created["schema_version"])
    assert response.json() == thaw(expected)


def test_story_1_9_get_schema_404s_the_same_for_someone_elses_proposal_or_a_random_id(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()

    other_owner = client.get(
        f"/api/proposals/{created['id']}/schema", headers=AS_AGENT_B
    )
    missing = client.get(f"/api/proposals/{uuid4()}/schema", headers=AS_AGENT_A)

    assert other_owner.status_code == missing.status_code == 404
    assert other_owner.json() == missing.json()


# Story 2.2 Part B: quote on the draft, resolved through GET /api/proposals/:id.


def test_story_2_2_get_by_id_prices_the_ally_reference_case(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_priced_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=1,
        answers=ALLY_ANSWERS,
        created_at=ALLY_CREATED_AT,
    )

    response = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A)

    assert response.status_code == 200
    body = response.json()
    assert body.keys() == DRAFT_FIELDS
    assert body["quote"] == ALLY_QUOTE
    assert body["answers"]["P1"] == "FSH"
    assert body["answers"]["P2"] == ["R07"]


@pytest.mark.parametrize(
    "answers",
    [
        pytest.param({"P1": "FSH"}, id="no C2"),
        pytest.param({"C2": "1994-11-20"}, id="no P1"),
        pytest.param({"P1": "NOSUCHPRODUCT", "C2": "1994-11-20"}, id="unknown P1"),
        pytest.param(
            # R01 belongs to LT20, not FSH.
            {"P1": "FSH", "P2": ["R01"], "C2": "1994-11-20"},
            id="P2 rider foreign to P1",
        ),
        pytest.param(
            # Over 126 at ALLY_CREATED_AT: outside the 0-70 band range.
            {"P1": "FSH", "C2": "1900-01-01"},
            id="age has no band",
        ),
    ],
)
def test_story_2_2_quote_is_null_for_the_unpriceable_cases(
    client: TestClient,
    admin: Admin,
    migrated_db: str,
    answers: dict[str, Any],
) -> None:
    proposal_id = _insert_priced_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=1,
        answers=answers,
        created_at=ALLY_CREATED_AT,
    )

    response = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A)

    assert response.status_code == 200
    assert response.json()["quote"] is None


def test_story_2_2_quote_recomputes_when_p1_changes(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    # LT20 (age 31, band 3): 60.00 x 1.05^3 = 69.4575 -> 69.46 monthly, 791.82 yearly.
    proposal_id = _insert_priced_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=1,
        answers={"P1": "LT20", "C2": "1994-11-20"},
        created_at=ALLY_CREATED_AT,
    )
    before = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    assert before["quote"] == {
        "monthly": 69.46,
        "yearly": 791.82,
        "lines": [{"item": "SecureLife Term", "monthly": 69.46, "yearly": 791.82}],
    }

    _update_answers(client, proposal_id, ALLY_ANSWERS)

    after = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    assert after["quote"] == ALLY_QUOTE


def test_story_2_2_quote_recomputes_when_p2_changes(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_priced_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=1,
        answers=ALLY_ANSWERS,
        created_at=ALLY_CREATED_AT,
    )
    before = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    assert before["quote"] == ALLY_QUOTE

    # Add FSH's Child cover (R06, baseline 12.00) alongside R07.
    _update_answers(client, proposal_id, {"P2": ["R07", "R06"]})

    after = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    assert after["quote"] == {
        "monthly": 233.84,
        "yearly": 2665.78,
        "lines": [
            {
                "item": "FamilyShield Life & Health",
                "monthly": 185.22,
                "yearly": 2111.51,
            },
            {"item": "Maternity & newborn", "monthly": 34.73, "yearly": 395.91},
            {"item": "Child cover", "monthly": 13.89, "yearly": 158.36},
        ],
    }


def test_story_2_2_quote_recomputes_when_c2_changes(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    # Born on the created_at MYT calendar date: exactly 18, band 0 (LT20 60.00 x 1.05^0).
    proposal_id = _insert_priced_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=1,
        answers={"P1": "LT20", "C2": "2008-09-25"},
        created_at=ALLY_CREATED_AT,
    )
    before = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    assert before["quote"] == {
        "monthly": 60.00,
        "yearly": 684.00,
        "lines": [{"item": "SecureLife Term", "monthly": 60.00, "yearly": 684.00}],
    }

    # Ally's DOB: age 31 at the same created_at, band 3.
    _update_answers(client, proposal_id, {"C2": "1994-11-20"})

    after = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    assert after["quote"] == {
        "monthly": 69.46,
        "yearly": 791.82,
        "lines": [{"item": "SecureLife Term", "monthly": 69.46, "yearly": 791.82}],
    }


def test_story_2_2_quote_is_never_stored_in_answers(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_priced_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=1,
        answers=ALLY_ANSWERS,
        created_at=ALLY_CREATED_AT,
    )

    response = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A)
    assert response.json()["quote"] is not None  # sanity: this draft does price

    with admin(migrated_db) as connection:
        row = connection.execute(
            "SELECT answers FROM proposal WHERE id = %s", (str(proposal_id),)
        ).fetchone()
    assert row is not None
    assert "quote" not in row[0]


# Story 1.10: PATCH /api/proposals/:id/answers (AD-6, AD-12, AD-15).


def _patch(
    client: TestClient, proposal_id: Any, revision: int, answers: dict[str, Any]
) -> Any:
    return client.patch(
        f"/api/proposals/{proposal_id}/answers",
        json={"revision": revision, "answers": answers},
        headers=AS_AGENT_A,
    )


def test_story_1_10_patch_stores_the_diff_and_bumps_revision(
    patch_client: TestClient, clock: FakeClock
) -> None:
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(patch_client, created["id"])

    clock.advance(timedelta(minutes=1))
    response = _patch(patch_client, created["id"], created["revision"], {"C1": "Ally"})

    assert response.status_code == 200
    body = response.json()
    assert body["revision"] == created["revision"] + 1
    assert body["answers"]["C1"] == "Ally"
    assert body["provenance"]["C1"] == {
        "source": "human",
        "updated_at": "2026-09-26T09:01:00Z",
    }


def test_story_1_10_patch_leaves_an_unchanged_value_untouched(
    patch_client: TestClient, clock: FakeClock
) -> None:
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(patch_client, created["id"])
    first = _patch(
        patch_client, created["id"], created["revision"], {"C1": "Ally"}
    ).json()

    clock.advance(timedelta(minutes=1))
    second = _patch(
        patch_client, created["id"], first["revision"], {"C1": "Ally"}
    ).json()

    assert second["revision"] == first["revision"] + 1  # the transaction still ran
    assert second["provenance"]["C1"] == first["provenance"]["C1"]  # untouched


def test_story_1_10_patch_with_a_stale_revision_writes_nothing(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(client, created["id"])
    _patch(client, created["id"], created["revision"], {"C1": "Ally"})

    stale = _patch(client, created["id"], created["revision"], {"C1": "Bob"})

    assert stale.status_code == 409
    assert stale.json() == {
        "errors": [
            {
                "field": "revision",
                "code": "stale_revision",
                "message": "Reload the draft.",
            }
        ]
    }
    unchanged = client.get(f"/api/proposals/{created['id']}", headers=AS_AGENT_A).json()
    assert unchanged["answers"]["C1"] == "Ally"


def test_story_1_10_patch_404s_the_same_for_someone_elses_proposal_or_a_random_id(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(client, created["id"])

    other_owner = client.patch(
        f"/api/proposals/{created['id']}/answers",
        json={"revision": created["revision"], "answers": {"C1": "Ally"}},
        headers=AS_AGENT_B,
    )
    missing = _patch(client, uuid4(), 0, {"C1": "Ally"})

    assert other_owner.status_code == missing.status_code == 404
    assert other_owner.json() == missing.json()

    # Sanity: agent A's own PATCH, on the same draft and revision, does succeed.
    own = _patch(client, created["id"], created["revision"], {"C1": "Ally"})
    assert own.status_code == 200


def test_story_1_10_patch_rejects_d1_whatever_its_value(client: TestClient) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(client, created["id"])

    response = _patch(client, created["id"], created["revision"], {"D1": True})

    assert response.status_code == 422
    assert response.json() == {
        "errors": [
            {
                "field": "D1",
                "code": "inactive_field",
                "message": "This question isn't showing on the form right now.",
            }
        ]
    }
    unchanged = client.get(f"/api/proposals/{created['id']}", headers=AS_AGENT_A).json()
    assert "D1" not in unchanged["answers"]


@pytest.mark.parametrize(
    ("answers", "field", "code"),
    [
        pytest.param({"Z9": "x"}, "Z9", "unknown_field", id="unknown question id"),
        pytest.param({"H1": 500}, "H1", "out_of_range", id="H1 over its maximum"),
        pytest.param({"C7": "abc"}, "C7", "invalid_format", id="C7 not an email"),
        pytest.param({"G1": "Yes"}, "G1", "inactive_field", id="inactive question"),
        pytest.param({"N6": None}, "N6", "invalid_value", id="null on a choice"),
        pytest.param(
            {"C2": "not-a-date"}, "C2", "invalid_format", id="C2 malformed date"
        ),
        pytest.param(
            {"C2": "2020-01-01"}, "C2", "out_of_range", id="C2 age outside 18-70"
        ),
    ],
)
def test_story_1_10_patch_rejects_invalid_answers_and_writes_nothing(
    client: TestClient, answers: dict[str, Any], field: str, code: str
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(client, created["id"])
    if "N6" in answers:
        # N6 must already have an answer of its own before this PATCH nulls it. (FORM-222: N6
        # stands in for "any Yes/No choice question" here -- N3 dropped from the released schema
        # with page 1.)
        _patch(client, created["id"], created["revision"], {"N6": "Yes"})
        created = client.get(
            f"/api/proposals/{created['id']}", headers=AS_AGENT_A
        ).json()

    response = _patch(client, created["id"], created["revision"], answers)

    assert response.status_code == 422
    body = response.json()
    assert len(body["errors"]) == 1
    assert body["errors"][0]["field"] == field
    assert body["errors"][0]["code"] == code
    unchanged = client.get(f"/api/proposals/{created['id']}", headers=AS_AGENT_A).json()
    assert unchanged["revision"] == created["revision"]


def test_story_1_10_patch_reports_more_than_one_field_error_at_once(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(client, created["id"])

    response = _patch(
        client, created["id"], created["revision"], {"Z9": "x", "H1": 500}
    )

    assert response.status_code == 422
    body = response.json()
    assert {(error["field"], error["code"]) for error in body["errors"]} == {
        ("Z9", "unknown_field"),
        ("H1", "out_of_range"),
    }
    unchanged = client.get(f"/api/proposals/{created['id']}", headers=AS_AGENT_A).json()
    assert unchanged["revision"] == created["revision"]


def test_story_1_10_patch_accepts_a_field_the_same_patch_activates(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(client, created["id"])

    response = _patch(
        client, created["id"], created["revision"], {"C3": "female", "G1": "Yes"}
    )

    assert response.status_code == 200
    body = response.json()
    assert {"N8", "G1", "H15", "G2", "G3"} <= set(body["active"])
    assert body["answers"]["G1"] == "Yes"
    assert body["answers"]["H15"] == "No"  # x-simple, now active: defaulted
    assert "N8" not in body["answers"]  # x-fill: ask, now active, but never defaulted


def test_story_1_10_patch_clears_a_text_answer_to_null(client: TestClient) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(client, created["id"])
    _patch(
        client, created["id"], created["revision"], {"N6": "Yes", "N7": "a pack a day"}
    )
    after_first = client.get(
        f"/api/proposals/{created['id']}", headers=AS_AGENT_A
    ).json()

    response = _patch(client, created["id"], after_first["revision"], {"N7": None})

    assert response.status_code == 200
    body = response.json()
    assert body["answers"]["N7"] is None
    assert body["provenance"]["N7"]["source"] == "human"


def test_story_1_10_patch_recomputes_the_active_set_and_removes_inactive_answers(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(client, created["id"])
    activated = _patch(
        client, created["id"], created["revision"], {"C3": "female", "G1": "Yes"}
    ).json()
    assert {"G1", "H15"} <= activated["answers"].keys()

    response = _patch(client, created["id"], activated["revision"], {"C3": "male"})

    assert response.status_code == 200
    body = response.json()
    assert not {"G1", "G2", "G3", "H15", "N8"} & body["answers"].keys()
    assert not {"G1", "G2", "G3", "H15", "N8"} & set(body["active"])


def test_story_1_10_patch_updates_display_name_once_c1_and_c13_are_saved(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(client, created["id"])
    assert created["display_name"].startswith("Untitled_Proposal_")
    seq = created["display_name"].removeprefix("Untitled_Proposal_")

    response = _patch(
        client, created["id"], created["revision"], {"C1": "Ally", "C13": "Macbeal"}
    )

    assert response.json()["display_name"] == f"Ally_Macbeal_Proposal_{seq}"


# Story 2.3: the PATCH route threads the real seeded catalogue's products into apply_answers.
# patch_client's clock reads 2026-09-26T09:00 UTC == 2026-09-26T17:00 MYT.
AGE_31_DOB = "1994-11-20"  # 31 on that clock: within FSH's 18-55 range.
AGE_58_DOB = "1968-01-01"  # 58 on that clock: past FSH's 18-55 range.


def test_story_2_3_patch_accepts_p1_in_range(patch_client: TestClient) -> None:
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(patch_client, created["id"])
    _patch(patch_client, created["id"], created["revision"], {"C2": AGE_31_DOB})
    with_c2 = patch_client.get(
        f"/api/proposals/{created['id']}", headers=AS_AGENT_A
    ).json()

    response = _patch(patch_client, created["id"], with_c2["revision"], {"P1": "FSH"})

    assert response.status_code == 200
    assert response.json()["answers"]["P1"] == "FSH"


def test_form_18_patch_accepts_p1_outside_the_product_age_range(
    patch_client: TestClient,
) -> None:
    """Owner decision (owner, 2026-09-27): P1 is no longer checked against the product's age range."""
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(patch_client, created["id"])
    _patch(patch_client, created["id"], created["revision"], {"C2": AGE_58_DOB})
    with_c2 = patch_client.get(
        f"/api/proposals/{created['id']}", headers=AS_AGENT_A
    ).json()

    response = _patch(patch_client, created["id"], with_c2["revision"], {"P1": "FSH"})

    assert response.status_code == 200
    stored = patch_client.get(
        f"/api/proposals/{created['id']}", headers=AS_AGENT_A
    ).json()
    assert stored["answers"]["P1"] == "FSH"


def test_story_2_3_patch_rejects_a_rider_foreign_to_p1(
    patch_client: TestClient,
) -> None:
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(patch_client, created["id"])

    # ELH has no riders of its own; R07 is FSH's Maternity & newborn.
    response = _patch(
        patch_client,
        created["id"],
        created["revision"],
        {"P1": "ELH", "P2": ["R07"]},
    )

    assert response.status_code == 422
    body = response.json()
    assert len(body["errors"]) == 1
    assert body["errors"][0] == {
        "field": "P2",
        "code": "invalid_value",
        "message": "Choose only this product's riders.",
    }


def test_story_2_3_patch_rejects_n5_on_a_no_sum_assured_product(
    patch_client: TestClient,
) -> None:
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(patch_client, created["id"])

    response = _patch(
        patch_client, created["id"], created["revision"], {"P1": "CFH", "N5": 50000}
    )

    assert response.status_code == 422
    assert response.json()["errors"][0] == {
        "field": "N5",
        "code": "invalid_value",
        "message": "This product has no sum assured to set.",
    }


def test_story_2_3_patch_accepts_a_c2_change_that_invalidates_a_stored_p1(
    patch_client: TestClient,
) -> None:
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(patch_client, created["id"])
    _patch(patch_client, created["id"], created["revision"], {"C2": AGE_31_DOB})
    with_c2 = patch_client.get(
        f"/api/proposals/{created['id']}", headers=AS_AGENT_A
    ).json()
    _patch(patch_client, created["id"], with_c2["revision"], {"P1": "FSH"})
    with_p1 = patch_client.get(
        f"/api/proposals/{created['id']}", headers=AS_AGENT_A
    ).json()

    response = _patch(
        patch_client, created["id"], with_p1["revision"], {"C2": AGE_58_DOB}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answers"]["C2"] == AGE_58_DOB
    assert body["answers"]["P1"] == "FSH"  # kept unchanged; Story 3.1's job to flag it


# Story 3.1: POST /api/proposals/:id/validate (AD-7, AD-12, AD-15).

# Every active question on the released schema, answered validly (the domain tests' own
# COMPLETE_ANSWERS, mirrored here against the seeded catalogue -- FSH: 18-55, RM200,000-600,000
# sum assured, terms 20_yrs/30_yrs, rider R07 -- from migration 0003).
COMPLETE_ANSWERS: dict[str, Any] = {
    "N1": "life_health",
    "N2": 200,
    "N3": "No",
    "N5": 300000,
    "N6": "No",
    "P1": "FSH",
    "P2": ["R07"],
    "P3": "20_yrs",
    "Y1": "monthly",
    "Y2": "credit_card",
    "Y3": "No",
    "C1": "Ally",
    "C2": "1994-11-20",
    "C3": "male",
    "C4": "MY",
    "C5": "MY",
    "C6": "S1234567",
    "C7": "ally@example.test",
    "C8": "+60123456789",
    "C9": "Graphic designer",
    "C10": "1 Jalan Test",
    "C11": "single",
    "C12": "30k_60k",
    "C13": "Macbeal",
    "C14": "Kuala Lumpur",
    "C15": "50450",
    "H1": 165,
    "H2": 58,
    "H3": "none",
    "H4": ["none"],
    "H5": ["none"],
    "H6": "No",
    "H7": "No",
    "H8": "No",
    "H9": "No",
    "H10": "No",
    "H11": "No",
    "H12": "No",
    "H13": "No",
    "H14": "No",
}


def _insert_complete_draft(
    admin: Admin,
    dbname: str,
    *,
    overrides: dict[str, Any] | None = None,
    omit: tuple[str, ...] = (),
    created_at: str = ALLY_CREATED_AT,
    owner_seq: int = 1,
    customer_id: UUID | None = None,
) -> UUID:
    answers = {**COMPLETE_ANSWERS, **(overrides or {})}
    for question_id in omit:
        answers.pop(question_id, None)
    return _insert_priced_draft(
        admin,
        dbname,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=owner_seq,
        answers=answers,
        created_at=created_at,
        customer_id=customer_id,
    )


def _validate(
    client: TestClient, proposal_id: Any, headers: dict[str, str] = AS_AGENT_A
) -> Any:
    return client.post(f"/api/proposals/{proposal_id}/validate", headers=headers)


def test_story_3_1_validate_is_clean_for_a_complete_valid_draft(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(admin, migrated_db)

    response = _validate(client, proposal_id)

    assert response.status_code == 200
    assert response.json() == {"errors": []}


def test_story_3_1_validate_reports_exactly_three_errors(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(
        admin,
        migrated_db,
        overrides={"C2": "1994-02-30", "P1": "XYZ"},
        omit=("H1",),
    )

    response = _validate(client, proposal_id)

    assert response.status_code == 200
    body = response.json()
    assert {(error["field"], error["code"]) for error in body["errors"]} == {
        ("C2", "invalid_format"),
        ("P1", "invalid_value"),
        ("H1", "required"),
    }
    assert len(body["errors"]) == 3


@pytest.mark.parametrize(
    "dob",
    [
        pytest.param("2008-09-26", id="17 at created_at"),
        pytest.param("1955-09-25", id="71 at created_at"),
    ],
)
def test_story_3_1_validate_rejects_c2_outside_the_age_range_at_created_at(
    client: TestClient, admin: Admin, migrated_db: str, dob: str
) -> None:
    # No seeded product's own age range reaches as wide as 17-71 (the domain tests cover that
    # isolated case with a synthetic product), so this only asserts C2's own x-age-range check
    # fires -- P1 (FSH, 18-55) may fail its own age rule too, which is fine, that's covered by
    # its own tests below.
    proposal_id = _insert_complete_draft(admin, migrated_db, overrides={"C2": dob})

    response = _validate(client, proposal_id)

    assert response.status_code == 200
    assert ("C2", "out_of_range") in {
        (error["field"], error["code"]) for error in response.json()["errors"]
    }


def test_story_3_1_validate_checks_c2_age_at_created_at_not_now(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    # Same C2, one draft created a year later than the other: only the created_at differs, and only
    # the earlier one is out of range at 17 (AD-7: never "now").
    dob = "2008-09-26"
    younger = _insert_complete_draft(
        admin,
        migrated_db,
        overrides={"C2": dob},
        created_at="2026-09-25T03:00:00+00:00",
        owner_seq=1,
    )
    older = _insert_complete_draft(
        admin,
        migrated_db,
        overrides={"C2": dob},
        created_at="2027-09-25T03:00:00+00:00",
        owner_seq=2,
    )

    younger_errors = _validate(client, younger).json()["errors"]
    older_errors = _validate(client, older).json()["errors"]

    assert any(error["field"] == "C2" for error in younger_errors)
    assert not any(error["field"] == "C2" for error in older_errors)


def test_story_3_1_validate_reports_product_rider_term_and_sum_assured_rules(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(
        admin,
        migrated_db,
        overrides={
            "C2": "1966-09-20",  # age 60: outside FSH's 18-55 range, allowed since FORM-18
            "P2": ["R01"],  # belongs to LT20, not FSH
            "P3": "99_yrs",  # not one of FSH's policy terms
            "N5": 700000,  # over FSH's 600000 sum-assured maximum
        },
    )

    response = _validate(client, proposal_id)

    assert response.status_code == 200
    assert {(error["field"], error["code"]) for error in response.json()["errors"]} == {
        ("P2", "invalid_value"),
        ("P3", "invalid_value"),
        ("N5", "out_of_range"),
    }


def test_story_3_1_validate_unknown_product_skips_its_dependent_rules(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(
        admin,
        migrated_db,
        overrides={"P1": "XYZ", "P2": ["ANY"], "P3": "any_term", "N5": 999},
    )

    response = _validate(client, proposal_id)

    assert response.status_code == 200
    assert response.json()["errors"] == [
        {
            "field": "P1",
            "code": "invalid_value",
            "message": "Choose one of the listed products.",
        }
    ]


def test_story_3_1_validate_never_reports_inactive_questions_or_d1(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(
        admin,
        migrated_db,
        overrides={"G1": "not-a-valid-answer", "D1": "not-a-boolean"},
    )

    response = _validate(client, proposal_id)

    assert response.status_code == 200
    assert response.json() == {"errors": []}


def test_story_3_1_validate_never_mutates_the_stored_draft(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(admin, migrated_db, overrides={"P1": "XYZ"})
    before = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()

    response = _validate(client, proposal_id)
    assert response.status_code == 200
    assert response.json()["errors"] != []  # sanity: this draft isn't clean

    after = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    assert after == before


def test_story_3_1_validate_404s_the_same_for_someone_elses_proposal_or_a_random_id(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(admin, migrated_db)

    other_owner = _validate(client, proposal_id, AS_AGENT_B)
    missing = _validate(client, uuid4(), AS_AGENT_A)

    assert other_owner.status_code == missing.status_code == 404
    assert other_owner.json() == missing.json()


# Story 3.2: the Submitted list, the shared write path's proposal_submitted rejection, and
# restart durability (AD-2, AD-8, FR9, FR20, FR46).


def test_story_3_2_get_submitted_list_returns_only_the_callers_own_newest_submitted_first(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    _insert_submitted_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=1,
        submitted_at="2026-09-20T09:00:00+00:00",
    )
    _insert_submitted_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=2,
        submitted_at="2026-09-25T09:00:00+00:00",
    )
    _insert_submitted_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-b"].oid,
        owner_seq=1,
        submitted_at="2026-09-26T09:00:00+00:00",
    )

    response = client.get("/api/proposals?status=submitted", headers=AS_AGENT_A)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert [set(row.keys()) for row in body] == [
        {
            "id",
            "display_name",
            "status",
            "created_at",
            "submitted_at",
            "customer_number",
        }
        for _ in body
    ]
    assert [row["display_name"] for row in body] == [
        "Untitled_Proposal_002",
        "Untitled_Proposal_001",
    ]
    assert {row["status"] for row in body} == {"submitted"}
    assert all(row["submitted_at"] is not None for row in body)


def test_story_3_2_submitted_list_is_empty_for_an_agent_with_no_submitted_proposals(
    client: TestClient,
) -> None:
    response = client.get("/api/proposals?status=submitted", headers=AS_AGENT_A)

    assert response.status_code == 200
    assert response.json() == []


def test_story_3_2_patch_rejects_a_write_to_a_submitted_proposal_and_writes_nothing(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_submitted_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=1,
        submitted_at="2026-09-25T09:00:00+00:00",
        answers={"C1": "Ally"},
    )

    response = _patch(client, proposal_id, 0, {"C1": "Bob"})

    assert response.status_code == 409
    assert response.json() == {
        "errors": [
            {
                "field": "proposal",
                "code": "proposal_submitted",
                "message": "This proposal has already been submitted and can't be changed.",
            }
        ]
    }
    unchanged = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    assert unchanged["answers"]["C1"] == "Ally"
    assert unchanged["revision"] == 0


def test_story_3_2_get_by_id_reads_back_a_submitted_proposal_unchanged(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    # No submit endpoint yet (that's Story 3.3/FORM-21): a straight DB read after a direct insert
    # already proves the durability FR46 asks for -- nothing here is cached in memory to survive.
    proposal_id = _insert_submitted_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=1,
        submitted_at="2026-09-25T09:00:00+00:00",
        answers={"C1": "Ally", "C13": "Macbeal"},
    )

    response = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A)

    assert response.status_code == 200
    body = response.json()
    assert body.keys() == DRAFT_FIELDS
    assert body["status"] == "submitted"
    assert body["answers"]["C1"] == "Ally"
    assert body["answers"]["C13"] == "Macbeal"
    assert body["display_name"] == "Ally_Macbeal_Proposal_001"
    assert body["submitted_at"] is not None


# Story 4.9: PATCH /api/proposals/:id/answers logs a human override of a previously non-human
# answer into answer_overrides, in the same transaction (AD-17, EXPERIENCE.md line 229).


def _insert_draft_with_answers(
    admin: Admin,
    dbname: str,
    *,
    owner_oid: str,
    owner_seq: int,
    answers: dict[str, Any],
) -> UUID:
    """A draft with these exact ``answers`` entries (any ``source``), inserted straight into the
    table -- there is no write path that stores an ``ai``-sourced answer through this REST-only
    test file (that's Story 4.5's chat/MCP adapter), so a stored ``source: "ai"`` fixture needs a
    direct insert."""
    with admin(dbname) as connection:
        row = connection.execute(
            "INSERT INTO proposal "
            "(owner_oid, owner_seq, schema_version, status, revision, answers, "
            "created_at, updated_at) "
            "VALUES (%s, %s, 1, 'draft', 0, %s, now(), now()) RETURNING id",
            (owner_oid, owner_seq, Jsonb(answers)),
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def _overrides(admin: Admin, dbname: str, proposal_id: Any) -> list[dict[str, Any]]:
    with admin(dbname) as connection:
        rows = connection.execute(
            "SELECT question_id, schema_version, previous_value, previous_source, new_value, "
            "model_deployment, overridden_by, at FROM answer_overrides "
            "WHERE proposal_id = %s ORDER BY question_id",
            (str(proposal_id),),
        ).fetchall()
    return [
        {
            "question_id": row[0],
            "schema_version": row[1],
            "previous_value": row[2],
            "previous_source": row[3],
            "new_value": row[4],
            "model_deployment": row[5],
            "overridden_by": row[6],
            "at": row[7],
        }
        for row in rows
    ]


def test_story_4_9_default_answer_overridden_by_human_is_logged(
    patch_client: TestClient, admin: Admin, migrated_db: str
) -> None:
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    # sanity: H10 is AD-15-defaulted at creation
    assert created["provenance"]["H10"]["source"] == "default"
    _lock(patch_client, created["id"])

    response = _patch(patch_client, created["id"], created["revision"], {"H10": "Yes"})

    assert response.status_code == 200
    body = response.json()
    overrides = _overrides(admin, migrated_db, created["id"])
    assert len(overrides) == 1
    [override] = overrides
    assert override["question_id"] == "H10"
    assert override["schema_version"] == created["schema_version"]
    assert override["previous_value"] == "No"
    assert override["previous_source"] == "default"
    assert override["new_value"] == "Yes"
    assert override["model_deployment"] == "model-deployment-not-configured"
    assert override["overridden_by"] == TEST_PRINCIPALS["agent-a"].oid
    assert (
        override["at"].isoformat().replace("+00:00", "Z")
        == body["provenance"]["H10"]["updated_at"]
    )


def test_story_4_9_ai_answer_cleared_by_human_is_logged_with_a_null_new_value(
    patch_client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_draft_with_answers(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=1,
        answers={
            "N6": {
                "value": "Yes",
                "source": "human",
                "updated_at": "2026-09-26T00:00:00Z",
            },
            "N7": {
                "value": "a pack a day",
                "source": "ai",
                "updated_at": "2026-09-26T00:00:00Z",
            },
        },
    )
    _lock(patch_client, proposal_id)
    created = patch_client.get(
        f"/api/proposals/{proposal_id}", headers=AS_AGENT_A
    ).json()
    assert created["provenance"]["N7"]["source"] == "ai"  # sanity

    response = _patch(patch_client, proposal_id, created["revision"], {"N7": None})

    assert response.status_code == 200
    assert response.json()["answers"]["N7"] is None
    overrides = _overrides(admin, migrated_db, proposal_id)
    assert len(overrides) == 1
    [override] = overrides
    assert override["question_id"] == "N7"
    assert override["previous_value"] == "a pack a day"
    assert override["previous_source"] == "ai"
    assert override["new_value"] is None


def test_story_5_2_editing_a_linked_field_is_logged_with_previous_source_db(
    patch_client: TestClient, admin: Admin, migrated_db: str
) -> None:
    """Story 5.2: link_customer stores copied particulars at ``source: "db"``; overrides_for is
    already generic over any non-human ``before`` source (domain.answer_overrides docstring), so a
    later human edit of a linked field needs no new code -- only this regression test (spec Code
    Map)."""
    proposal_id = _insert_draft_with_answers(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=1,
        answers={
            "C9": {
                "value": "12 Jalan Bunga Raya",
                "source": "db",
                "updated_at": "2026-09-26T00:00:00Z",
            }
        },
    )
    _lock(patch_client, proposal_id)
    created = patch_client.get(
        f"/api/proposals/{proposal_id}", headers=AS_AGENT_A
    ).json()
    assert created["provenance"]["C9"]["source"] == "db"  # sanity

    response = _patch(
        patch_client, proposal_id, created["revision"], {"C9": "9 Jalan Baru"}
    )

    assert response.status_code == 200
    assert response.json()["answers"]["C9"] == "9 Jalan Baru"
    overrides = _overrides(admin, migrated_db, proposal_id)
    assert len(overrides) == 1
    [override] = overrides
    assert override["question_id"] == "C9"
    assert override["previous_value"] == "12 Jalan Bunga Raya"
    assert override["previous_source"] == "db"
    assert override["new_value"] == "9 Jalan Baru"


def test_story_4_9_overriding_an_already_human_answer_logs_no_row(
    patch_client: TestClient, admin: Admin, migrated_db: str
) -> None:
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(patch_client, created["id"])
    first = _patch(
        patch_client, created["id"], created["revision"], {"C1": "Ally"}
    ).json()
    assert first["provenance"]["C1"]["source"] == "human"

    second = _patch(patch_client, created["id"], first["revision"], {"C1": "Alicia"})

    assert second.status_code == 200
    assert second.json()["answers"]["C1"] == "Alicia"
    # C1 had no stored entry at all before the first PATCH (never answered -- ASSUMPTION: no row
    # for that one either), and the second PATCH overrides an already-"human" value (AC4): neither
    # write logs anything.
    assert _overrides(admin, migrated_db, created["id"]) == []


def test_story_4_9_a_no_op_write_logs_no_row(
    patch_client: TestClient, admin: Admin, migrated_db: str
) -> None:
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    assert created["provenance"]["H10"]["source"] == "default"
    _lock(patch_client, created["id"])

    response = _patch(patch_client, created["id"], created["revision"], {"H10": "No"})

    assert response.status_code == 200
    # A no-op: apply_answers never re-stamps source when the incoming value matches what's stored.
    assert response.json()["provenance"]["H10"]["source"] == "default"
    assert _overrides(admin, migrated_db, created["id"]) == []


def test_story_4_9_a_stale_revision_write_logs_no_override_row(
    patch_client: TestClient, admin: Admin, migrated_db: str
) -> None:
    """AC5 (rollback-together): a stale ``expected_revision`` writes nothing at all -- the proposal
    ``UPDATE``'s own ``WHERE`` misses, so ``update_answers`` returns ``None`` before computing or
    inserting any override row, never a best-effort side write. [interpreted per the FORM-30 brief:
    forcing the *override insert itself* to fail isn't reachable through the public write path (it
    would need a direct schema-level fault), so this proves the weaker, brief-suggested half of
    AC5 -- a write that never reaches the proposal UPDATE also never reaches the override insert --
    while the "both write on the same connection inside one `engine.begin()`" structure is what
    guarantees the stronger half (an override-insert failure rolls the proposal UPDATE back too)."""
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    assert created["provenance"]["H10"]["source"] == "default"
    _lock(patch_client, created["id"])
    # The one real write.
    _patch(patch_client, created["id"], created["revision"], {"H10": "Yes"})

    stale = _patch(patch_client, created["id"], created["revision"], {"H10": "No"})

    assert stale.status_code == 409
    overrides = _overrides(admin, migrated_db, created["id"])
    # Only the first, successful write's row -- the stale one added none.
    assert len(overrides) == 1
    assert overrides[0]["new_value"] == "Yes"


# Story 3.3/FORM-21: POST /api/proposals/:id/submit (FR18-20, AD-2, AD-8, AD-12, AD-13, AD-16).


def _insert_customer(admin: Admin, dbname: str, **values: Any) -> UUID:
    """A pre-existing ``customer`` row (Story 3.3's "already linked" scenario). FORM-218:
    ``customer_number`` is NOT NULL, so a test that doesn't care what it is gets an arbitrary,
    valid, out-of-band one (never one migration 0015's backfill or a real submit's sequence would
    draw, since both start at 1000)."""
    values.setdefault("customer_number", format_customer_number(9999))
    with admin(dbname) as connection:
        row = connection.execute(
            sql.SQL("INSERT INTO customer ({}) VALUES ({}) RETURNING id").format(
                sql.SQL(", ").join(map(sql.Identifier, values)),
                sql.SQL(", ").join(map(sql.Placeholder, values)),
            ),
            values,
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


def _submit(
    client: TestClient,
    proposal_id: Any,
    revision: int,
    *,
    declaration_agreed: bool = True,
    rating: int | None = 4,
    comment: str | None = "It saved me a lot of typing.",
    headers: dict[str, str] = AS_AGENT_A,
) -> Any:
    return client.post(
        f"/api/proposals/{proposal_id}/submit",
        json={
            "revision": revision,
            "declaration_agreed": declaration_agreed,
            "feedback": {"rating": rating, "comment": comment},
        },
        headers=headers,
    )


def test_story_3_3_submit_happy_path_new_customer(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(admin, migrated_db)
    _lock(client, proposal_id)

    response = _submit(client, proposal_id, 0)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submitted"
    assert body["submitted_at"] is not None
    assert body["answers"]["D1"] is True
    assert body["provenance"]["D1"]["source"] == "human"
    assert body["revision"] == 1
    with admin(migrated_db) as connection:
        linked = connection.execute(
            "SELECT customer_id FROM proposal WHERE id = %s", (str(proposal_id),)
        ).fetchone()
        assert linked is not None and linked[0] is not None
        # Scoped to the customer this submit itself created, never the whole table: Story 5.1's
        # migration (0013) already seeds ~10 synthetic customers ahead of this one (spec Boundaries
        # note on re-chaining onto dev's head).
        customers = connection.execute(
            "SELECT first_name, last_name, date_of_birth FROM customer WHERE id = %s",
            (linked[0],),
        ).fetchall()
        feedback = connection.execute(
            "SELECT proposal_id, rating, comment, given_by FROM proposal_feedback"
        ).fetchall()
    assert customers == [("Ally", "Macbeal", date(1994, 11, 20))]
    assert feedback == [
        (
            proposal_id,
            4,
            "It saved me a lot of typing.",
            TEST_PRINCIPALS["agent-a"].oid,
        )
    ]


def test_story_3_3_submit_happy_path_linked_customer_updates_not_duplicates(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    customer_id = _insert_customer(
        admin, migrated_db, first_name="Old", last_name="Name"
    )
    proposal_id = _insert_complete_draft(admin, migrated_db, customer_id=customer_id)
    _lock(client, proposal_id)

    with admin(migrated_db) as connection:
        before_count = connection.execute("SELECT count(*) FROM customer").fetchone()

    response = _submit(client, proposal_id, 0)

    assert response.status_code == 200
    with admin(migrated_db) as connection:
        # Scoped to this one customer id, never the whole table: Story 5.1's migration (0013)
        # already seeds ~10 synthetic customers ahead of this one (spec Boundaries note on
        # re-chaining onto dev's head).
        row = connection.execute(
            "SELECT id, first_name, last_name FROM customer WHERE id = %s",
            (customer_id,),
        ).fetchall()
        after_count = connection.execute("SELECT count(*) FROM customer").fetchone()
        linked = connection.execute(
            "SELECT customer_id FROM proposal WHERE id = %s", (str(proposal_id),)
        ).fetchone()
    # Updated in place, never duplicated: same one row, and the table gained no new customer.
    assert row == [(customer_id, "Ally", "Macbeal")]
    assert after_count == before_count
    assert linked == (customer_id,)


def test_story_218_submit_response_shows_the_new_customers_number(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(admin, migrated_db)
    _lock(client, proposal_id)

    response = _submit(client, proposal_id, 0)

    assert response.status_code == 200
    body = response.json()
    assert body["customer_number"] is not None
    with admin(migrated_db) as connection:
        (stored_number,) = connection.execute(
            "SELECT customer_number FROM customer WHERE id = "
            "(SELECT customer_id FROM proposal WHERE id = %s)",
            (str(proposal_id),),
        ).fetchone()
    assert body["customer_number"] == stored_number


def test_story_218_submit_response_keeps_a_linked_customers_existing_number(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    customer_id = _insert_customer(
        admin,
        migrated_db,
        first_name="Old",
        last_name="Name",
        customer_number=format_customer_number(2024),
    )
    proposal_id = _insert_complete_draft(admin, migrated_db, customer_id=customer_id)
    _lock(client, proposal_id)

    response = _submit(client, proposal_id, 0)

    assert response.status_code == 200
    assert response.json()["customer_number"] == format_customer_number(2024)


def test_story_218_submitted_list_shows_the_customer_number(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(admin, migrated_db)
    _lock(client, proposal_id)
    submitted = _submit(client, proposal_id, 0)
    assert submitted.status_code == 200

    response = client.get("/api/proposals?status=submitted", headers=AS_AGENT_A)

    assert response.status_code == 200
    (row,) = response.json()
    assert row["customer_number"] == submitted.json()["customer_number"]


def test_story_3_3_missing_declaration_saves_nothing(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(admin, migrated_db)
    _lock(client, proposal_id)
    with admin(migrated_db) as connection:
        before_count = connection.execute("SELECT count(*) FROM customer").fetchone()

    response = _submit(client, proposal_id, 0, declaration_agreed=False)

    assert response.status_code == 422
    assert response.json() == {
        "errors": [
            {
                "field": "declaration",
                "code": "declaration_required",
                "message": "Confirm the declaration before submitting.",
            }
        ]
    }
    unchanged = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    assert unchanged["status"] == "draft"
    assert unchanged["revision"] == 0
    assert "D1" not in unchanged["answers"]
    # No new customer: Story 5.1's migration (0013) already seeds ~10 synthetic ones, so this
    # compares against the count just before the rejected submit, not an absolute zero.
    with admin(migrated_db) as connection:
        after_count = connection.execute("SELECT count(*) FROM customer").fetchone()
    assert after_count == before_count


@pytest.mark.parametrize(
    "rating",
    [
        pytest.param(None, id="missing"),
        pytest.param(0, id="below range"),
        pytest.param(6, id="above range"),
    ],
)
def test_story_3_3_bad_rating_saves_nothing(
    client: TestClient,
    admin: Admin,
    migrated_db: str,
    rating: int | None,
) -> None:
    proposal_id = _insert_complete_draft(admin, migrated_db)
    _lock(client, proposal_id)

    response = _submit(client, proposal_id, 0, rating=rating)

    assert response.status_code == 422
    body = response.json()
    assert len(body["errors"]) == 1
    assert body["errors"][0]["field"] == "feedback"
    assert body["errors"][0]["code"] == "feedback_required"
    unchanged = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    assert unchanged["status"] == "draft"


def test_story_3_3_fails_validation_reuses_validates_own_errors(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(admin, migrated_db, omit=("H1",))
    _lock(client, proposal_id)

    response = _submit(client, proposal_id, 0)

    assert response.status_code == 422
    assert response.json() == {
        "errors": [{"field": "H1", "code": "required", "message": "Answer required"}]
    }
    unchanged = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    assert unchanged["status"] == "draft"


def test_story_3_3_stale_revision_saves_nothing(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(admin, migrated_db)
    _lock(client, proposal_id)

    response = _submit(client, proposal_id, 5)

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "stale_revision"
    unchanged = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    assert unchanged["status"] == "draft"


def test_story_3_3_lock_not_held_saves_nothing(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(admin, migrated_db)
    # Locked under a different X-Session-Id than the one _submit's default headers carry (the
    # client fixture's own "test-session"), so the submit call below isn't the live holder.
    _lock(client, proposal_id, **{"X-Session-Id": "other-session"})

    response = _submit(client, proposal_id, 0)

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "lock_not_held"
    unchanged = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()
    assert unchanged["status"] == "draft"


def test_story_3_3_already_submitted_saves_nothing(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_submitted_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=1,
        submitted_at="2026-09-25T09:00:00+00:00",
    )

    response = _submit(client, proposal_id, 0)

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "proposal_submitted"


def test_story_3_3_submit_404s_the_same_for_someone_elses_proposal_or_a_random_id(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_complete_draft(admin, migrated_db)
    _lock(client, proposal_id)

    other_owner = _submit(client, proposal_id, 0, headers=AS_AGENT_B)
    missing = _submit(client, uuid4(), 0)

    assert other_owner.status_code == missing.status_code == 404
    assert other_owner.json() == missing.json()


def test_story_3_3_cancel_either_modal_leaves_the_draft_untouched(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    # "Cancel" is a pure web-app interaction (no api call at all): the api-side proof that nothing
    # changes is simply that a draft never submitted stays exactly as it was.
    proposal_id = _insert_complete_draft(admin, migrated_db)

    unchanged = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A).json()

    assert unchanged["status"] == "draft"
    assert unchanged["revision"] == 0


def test_story_3_3_restart_durability_reads_back_customer_and_feedback(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    # No in-memory cache anywhere in this stack (Story 3.2's own durability test makes the same
    # argument): a straight read right after the write already proves FR46 for the new rows too.
    proposal_id = _insert_complete_draft(admin, migrated_db)
    _lock(client, proposal_id)
    submitted = _submit(client, proposal_id, 0)
    assert submitted.status_code == 200

    response = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "submitted"
    assert body["answers"]["D1"] is True
    assert body["answers"]["C1"] == "Ally"
    assert body["submitted_at"] is not None


# --- Story FORM-227: DELETE /api/proposals/:id (AD-2, AD-8, migration 0016) ---------------------


def test_form_227_delete_removes_the_draft_and_204s(client: TestClient) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(client, created["id"])

    response = client.delete(f"/api/proposals/{created['id']}", headers=AS_AGENT_A)

    assert response.status_code == 204
    assert response.content == b""
    missing = client.get(f"/api/proposals/{created['id']}", headers=AS_AGENT_A)
    assert missing.status_code == 404


def test_form_227_delete_404s_the_same_for_someone_elses_proposal_or_a_random_id(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()

    other_owner = client.delete(f"/api/proposals/{created['id']}", headers=AS_AGENT_B)
    missing = client.delete(f"/api/proposals/{uuid4()}", headers=AS_AGENT_A)

    assert other_owner.status_code == missing.status_code == 404
    assert other_owner.json() == missing.json()
    # Not actually deleted by the wrong owner's attempt.
    still_there = client.get(f"/api/proposals/{created['id']}", headers=AS_AGENT_A)
    assert still_there.status_code == 200


def test_form_227_delete_rejects_a_submitted_proposal(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_submitted_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        owner_seq=1,
        submitted_at="2026-09-25T09:00:00+00:00",
    )

    response = client.delete(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A)

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "proposal_submitted"
    still_there = client.get(f"/api/proposals/{proposal_id}", headers=AS_AGENT_A)
    assert still_there.status_code == 200


def test_form_227_delete_rejects_a_different_sessions_live_lock(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    # Locked under a different X-Session-Id than the client fixture's own default
    # ("test-session"), so the delete call below isn't the live holder.
    _lock(client, created["id"], **{"X-Session-Id": "other-session"})

    response = client.delete(f"/api/proposals/{created['id']}", headers=AS_AGENT_A)

    assert response.status_code == 409
    assert response.json()["errors"][0]["code"] == "lock_not_held"
    still_there = client.get(f"/api/proposals/{created['id']}", headers=AS_AGENT_A)
    assert still_there.status_code == 200


def test_form_227_delete_succeeds_when_the_callers_own_session_holds_the_lock(
    client: TestClient,
) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    # Locked under the client fixture's own default X-Session-Id ("test-session"): the delete
    # call below is that same live holder, so the lock never blocks it (unlike every other write).
    _lock(client, created["id"])

    response = client.delete(f"/api/proposals/{created['id']}", headers=AS_AGENT_A)

    assert response.status_code == 204


def test_form_227_delete_succeeds_when_the_lock_is_free(client: TestClient) -> None:
    created = client.post("/api/proposals", headers=AS_AGENT_A).json()
    # Never locked at all: free, and a delete is allowed on a free lock (spec Boundaries).

    response = client.delete(f"/api/proposals/{created['id']}", headers=AS_AGENT_A)

    assert response.status_code == 204


def test_form_227_delete_cascades_a_draft_with_answer_overrides(
    patch_client: TestClient, admin: Admin, migrated_db: str
) -> None:
    """AC1 (spec Acceptance Criteria): a draft with prior human-answer overrides -- generated here
    through the real Story 4.9 write path, not a raw insert -- has both its own row and every
    referencing ``answer_overrides`` row gone in the same transaction once deleted."""
    created = patch_client.post("/api/proposals", headers=AS_AGENT_A).json()
    _lock(patch_client, created["id"])
    # H9 defaults to "No" (source: default) from creation -- unlike G1, which stays inactive (no
    # entry at all) until C3 is answered, so overriding G1 alone here would 422 as inactive_field,
    # and even paired with C3 in the same PATCH would log no override row (domain.answer_overrides:
    # a question with no *before* entry logs nothing). A human PATCH overriding H9 logs an override
    # row (Story 4.9, AC1) -- exactly the "answer_overrides rows" scenario the spec's I/O matrix
    # names.
    patched = _patch(patch_client, created["id"], created["revision"], {"H9": "Yes"})
    assert patched.status_code == 200
    assert _overrides(admin, migrated_db, created["id"]) != []

    response = patch_client.delete(
        f"/api/proposals/{created['id']}", headers=AS_AGENT_A
    )

    assert response.status_code == 204
    assert _overrides(admin, migrated_db, created["id"]) == []
    missing = patch_client.get(f"/api/proposals/{created['id']}", headers=AS_AGENT_A)
    assert missing.status_code == 404
