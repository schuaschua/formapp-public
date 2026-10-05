"""Story 4.3/5.1/5.2: the seven MCP tools' happy paths and basic error mapping (AC5, AC6), against
a real migrated database, driven over the real Streamable HTTP wire (spine AD-3, AD-4, AD-5,
AD-13, AD-14)."""

import asyncio
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

import jwt
import psycopg
from fastapi import FastAPI
from psycopg.types.json import Jsonb

from adapters.db.proposals import SqlProposalStore
from adapters.db.scope import for_owner, scoped
from adapters.rest.app import create_app
from adapters.rest.principal import TEST_PRINCIPALS
from adapters.settings import Settings
from domain.proposals import LOCK_DURATION, create_draft
from domain.turn_tokens import issue_turn_token
from tests.adapters.mcp.support import call_tool, running_app
from tests.fakes import FakeClock

OWNER_A = TEST_PRINCIPALS["agent-a"].oid

# Migration 0013's "Ally Macbeal" (Story 5.1's own demo customer, reused here for linking).
_SEEDED_CUSTOMER_ID = "00000000-0000-4000-8000-000000000001"

Admin = Callable[[str], psycopg.Connection[Any]]


def _app(db_settings: Settings, migrated_db: str, clock: FakeClock) -> FastAPI:
    settings = db_settings.model_copy(update={"database_name": migrated_db})
    return create_app(settings, clock=clock)


async def _bound_proposal(app: FastAPI, clock: FakeClock) -> tuple[UUID, str]:
    """A fresh draft, already turn-bound to the AI (Story 4.3's own test-only plumbing: nothing in
    this story sets this in production -- Story 4.5's chat adapter does). ``issue_turn_token``
    mints its own fresh ``tid`` (AC1); this helper is what Story 4.5 will eventually be, threading
    that same ``tid`` through to the store's ``current_turn_id`` so the minted token is genuinely
    turn-bound.

    These are direct store calls, outside any REST or MCP request -- unlike production, nothing
    sets the row-level security scope for them, so the fixture sets it itself (Story 4.3 Part B,
    AD-17): OWNER_A's own scope, matching the row it is about to create and update.
    """
    store = SqlProposalStore(app.state.engine)
    with scoped(for_owner(OWNER_A)):
        proposal = await create_draft(store, OWNER_A, clock)
        token = await issue_turn_token(
            store, proposal.id, OWNER_A, clock, app.state.settings.turn_token_signing_key
        )
        tid = UUID(jwt.decode(token, options={"verify_signature": False})["tid"])
        await store.set_turn(
            proposal.id,
            lock_holder="ai",
            lock_expires_at=clock.now() + LOCK_DURATION,
            current_turn_id=tid,
        )
    return proposal.id, token


def test_story_4_3_get_form_schema_returns_the_pinned_schema(
    db_settings: Settings, migrated_db: str
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            return await call_tool(app, token, "get_form_schema")

    schema = asyncio.run(scenario())

    # FORM-222: `_bound_proposal` creates through `create_draft`, so it's always pinned to the
    # latest version (v2 as of this change), not a fixed "v1".
    assert schema["$id"] == "urn:formapp:form-schema:v2"
    assert "C1" in schema["properties"]


def test_story_4_3_get_draft_sees_itself_as_the_holder(
    db_settings: Settings, migrated_db: str
) -> None:
    """[ASSUMPTION] get_draft's lock.holder for the AI's own call is "you" (draft_view/lock_view
    called with session_id="ai"), same as a human sees her own lock."""
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            return await call_tool(app, token, "get_draft")

    draft = asyncio.run(scenario())

    assert draft["lock"]["holder"] == "you"
    assert draft["status"] == "draft"
    assert draft["revision"] == 0
    assert draft["quote"] is None  # no P1/C2 answered yet


def test_story_4_3_patch_draft_applies_a_valid_field(
    db_settings: Settings, migrated_db: str
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            return await call_tool(app, token, "patch_draft", {"answers": {"C1": "Ally"}})

    result = asyncio.run(scenario())

    assert result == {"applied": ["C1"], "errors": [], "revision": 1}


def test_story_4_3_patch_draft_partially_applies_and_reports_errors(
    db_settings: Settings, migrated_db: str
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            return await call_tool(
                app, token, "patch_draft", {"answers": {"C1": "Ally", "D1": True, "Z9": "x"}}
            )

    result = asyncio.run(scenario())

    assert result["applied"] == ["C1"]
    assert result["revision"] == 1
    codes = {error["field"]: error["code"] for error in result["errors"]}
    assert codes == {"D1": "not_agent_writable", "Z9": "unknown_field"}


def test_story_4_3_validate_draft_flags_missing_required_fields(
    db_settings: Settings, migrated_db: str
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            return await call_tool(app, token, "validate_draft")

    result = asyncio.run(scenario())

    assert result["errors"]  # a fresh draft is missing required answers
    assert all(error["code"] == "required" for error in result["errors"])


def test_story_4_3_get_products_lists_every_product_when_age_is_unknown(
    db_settings: Settings, migrated_db: str
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            return await call_tool(app, token, "get_products")

    result = asyncio.run(scenario())

    assert len(result["products"]) == 5  # tests/support.py's EXPECTED_PRODUCTS
    codes = {product["code"] for product in result["products"]}
    assert codes == {"CFH", "ELH", "FSH", "LT20", "LWL"}
    first = result["products"][0]
    assert isinstance(first["monthly"], float)
    assert isinstance(first["yearly"], float)


def test_story_5_1_find_customer_matches_the_seeded_demo_customer(
    db_settings: Settings, migrated_db: str
) -> None:
    """Migration 0013 seeds "Ally Macbeal", born 1994-11-20, in Petaling Jaya (Story 5.1)."""
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            return await call_tool(
                app,
                token,
                "find_customer",
                {
                    "first_name": "ally",
                    "last_name": "MACBEAL",
                    "date_of_birth": "1994-11-20",
                },
            )

    result = asyncio.run(scenario())

    assert len(result["matches"]) == 1
    match = result["matches"][0]
    assert set(match) == {
        "customer_id",
        "first_name",
        "last_name",
        "date_of_birth",
        "city",
        "customer_number",
    }
    assert (match["first_name"], match["last_name"]) == ("Ally", "Macbeal")
    assert match["date_of_birth"] == "1994-11-20"
    assert match["city"] == "Petaling Jaya"
    assert match["customer_number"]


def test_story_5_1_find_customer_returns_an_empty_list_when_nothing_matches(
    db_settings: Settings, migrated_db: str
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            return await call_tool(
                app,
                token,
                "find_customer",
                {
                    "first_name": "Nobody",
                    "last_name": "Synthetic",
                    "date_of_birth": "1970-01-01",
                },
            )

    result = asyncio.run(scenario())

    assert result == {"matches": []}


def test_story_218_find_customer_by_number_matches_the_seeded_demo_customer(
    db_settings: Settings, migrated_db: str
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            # First, look up the number find_customer's own name search gives back.
            by_name = await call_tool(
                app,
                token,
                "find_customer",
                {"first_name": "Ally", "last_name": "Macbeal", "date_of_birth": "1994-11-20"},
            )
            number = by_name["matches"][0]["customer_number"]
            return number, await call_tool(
                app, token, "find_customer", {"customer_number": number}
            )

    number, result = asyncio.run(scenario())

    assert len(result["matches"]) == 1
    assert result["matches"][0]["customer_number"] == number
    assert result["matches"][0]["last_name"] == "Macbeal"


def test_story_218_find_customer_by_number_with_an_altered_check_digit_finds_nothing(
    db_settings: Settings, migrated_db: str
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            by_name = await call_tool(
                app,
                token,
                "find_customer",
                {"first_name": "Ally", "last_name": "Macbeal", "date_of_birth": "1994-11-20"},
            )
            number = by_name["matches"][0]["customer_number"]
            altered = number[:-1] + str((int(number[-1]) + 1) % 10)
            return await call_tool(
                app, token, "find_customer", {"customer_number": altered}
            )

    result = asyncio.run(scenario())

    assert result == {"matches": []}


def test_story_218_find_customer_by_first_name_and_year_month_is_unique(
    db_settings: Settings, migrated_db: str
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            return await call_tool(
                app,
                token,
                "find_customer",
                {"first_name": "ally", "date_of_birth": "1994-11"},
            )

    result = asyncio.run(scenario())

    assert len(result["matches"]) == 1
    assert result["matches"][0]["last_name"] == "Macbeal"


def test_story_218_find_customer_ambiguous_first_name_and_year_returns_several(
    db_settings: Settings, migrated_db: str
) -> None:
    """Migration 0013 seeds two "Tan"s a year apart (1988/1990) -- a year alone is ambiguous
    only when both fall in that year; a first-name-only search returns both (spec I/O matrix
    "Ambiguous")."""
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            return await call_tool(
                app, token, "find_customer", {"first_name": "Tan"}
            )

    result = asyncio.run(scenario())

    assert len(result["matches"]) == 2
    assert {match["last_name"] for match in result["matches"]} == {
        "Wei Ming",
        "Wei Min",
    }


def test_story_218_find_customer_with_no_filters_at_all_returns_no_matches(
    db_settings: Settings, migrated_db: str
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            return await call_tool(app, token, "find_customer", {})

    result = asyncio.run(scenario())

    assert result == {"matches": []}


_C_COLUMNS = frozenset(
    {
        "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12", "C13", "C14",
        "C15",
    }
)


def test_story_5_2_link_customer_copies_particulars_from_the_seeded_customer(
    db_settings: Settings, migrated_db: str
) -> None:
    """Migration 0013's "Ally Macbeal" links onto a fresh draft with no human-set particulars:
    every C1-C15 field is copied at source: db, nothing is skipped (spec I/O matrix "Clean link").
    """
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> tuple[Any, Any]:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            link_result = await call_tool(
                app, token, "link_customer", {"customer_id": _SEEDED_CUSTOMER_ID}
            )
            draft = await call_tool(app, token, "get_draft")
            return link_result, draft

    link_result, draft = asyncio.run(scenario())

    assert link_result["customer_id"] == _SEEDED_CUSTOMER_ID
    assert link_result["skipped"] == []
    assert set(link_result["applied"]) == _C_COLUMNS
    assert link_result["revision"] == 1

    assert draft["answers"]["C1"] == "Ally"
    assert draft["answers"]["C13"] == "Macbeal"
    assert draft["answers"]["C2"] == "1994-11-20"
    assert draft["answers"]["C14"] == "Petaling Jaya"
    assert draft["provenance"]["C1"]["source"] == "db"


def test_story_5_2_link_customer_skips_a_field_alice_already_set(
    db_settings: Settings, migrated_db: str, admin: Admin
) -> None:
    """A field the insurance agent already typed in (source: human) keeps her value and is
    reported as skipped (spec I/O matrix "Human field kept")."""
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            pid, token = await _bound_proposal(app, clock)
            with admin(migrated_db) as connection:
                connection.execute(
                    "UPDATE proposal SET answers = answers || %s WHERE id = %s",
                    (
                        Jsonb(
                            {
                                "C7": {
                                    "value": "alice@example.com",
                                    "source": "human",
                                    "updated_at": "2026-09-27T00:00:00Z",
                                }
                            }
                        ),
                        str(pid),
                    ),
                )
            return await call_tool(
                app, token, "link_customer", {"customer_id": _SEEDED_CUSTOMER_ID}
            )

    result = asyncio.run(scenario())

    assert result["skipped"] == ["C7"]
    assert "C7" not in result["applied"]


def test_story_5_2_link_customer_rejects_an_unknown_customer(
    db_settings: Settings, migrated_db: str
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)
    unknown_id = str(uuid4())

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            return await call_tool(
                app, token, "link_customer", {"customer_id": unknown_id}
            )

    result = asyncio.run(scenario())

    assert result["errors"] == [
        {
            "field": "customer_id",
            "code": "invalid_value",
            "message": "This customer doesn't exist.",
        }
    ]


def test_story_5_2_link_customer_rejects_a_malformed_customer_id(
    db_settings: Settings, migrated_db: str
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            return await call_tool(
                app, token, "link_customer", {"customer_id": "not-a-uuid"}
            )

    result = asyncio.run(scenario())

    [error] = result["errors"]
    assert (error["field"], error["code"]) == ("customer_id", "invalid_value")


def test_story_5_2_link_customer_rejects_a_submitted_proposal(
    db_settings: Settings, migrated_db: str, admin: Admin
) -> None:
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> Any:
        async with running_app(app):
            pid, token = await _bound_proposal(app, clock)
            with admin(migrated_db) as connection:
                connection.execute(
                    "UPDATE proposal SET status = 'submitted', submitted_at = now() "
                    "WHERE id = %s",
                    (str(pid),),
                )
            return await call_tool(
                app, token, "link_customer", {"customer_id": _SEEDED_CUSTOMER_ID}
            )

    result = asyncio.run(scenario())

    assert result["errors"][0]["code"] == "proposal_submitted"


def test_story_5_2_link_customer_never_copies_a_health_answer(
    db_settings: Settings, migrated_db: str
) -> None:
    """AD-13: H*/G* answers are never read from, or written by, link_customer -- only C1-C15.
    Linking can activate a gender-specific H/G question (C3 newly answered), which AD-15's shared
    recompute then defaults to "No" at ``source: "default"`` -- the same as every other write path
    -- never at ``source: "db"``, since link_customer's own copy loop only ever touches
    ``customer_columns``."""
    clock = FakeClock()
    app = _app(db_settings, migrated_db, clock)

    async def scenario() -> tuple[Any, Any]:
        async with running_app(app):
            _pid, token = await _bound_proposal(app, clock)
            link_result = await call_tool(
                app, token, "link_customer", {"customer_id": _SEEDED_CUSTOMER_ID}
            )
            after = await call_tool(app, token, "get_draft")
            return link_result, after

    link_result, after = asyncio.run(scenario())

    assert all(not qid.startswith(("H", "G")) for qid in link_result["applied"])
    h_or_g_sources = {
        qid: entry["source"]
        for qid, entry in after["provenance"].items()
        if qid.startswith(("H", "G"))
    }
    assert all(source == "default" for source in h_or_g_sources.values())
