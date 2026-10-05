"""Story 2.1: GET /api/products lists the stored catalogue in snake_case JSON (AD-2, NFR5).

Story 2.3's ``?proposal_id=`` (the priced-and-eligible listing) lives here too.
"""

from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from adapters.rest.app import create_app
from adapters.rest.principal import TEST_PRINCIPALS
from adapters.settings import Settings
from tests.support import AS_AGENT_A, EXPECTED_PRODUCTS, EXPECTED_RIDERS

TEST_PRINCIPAL = AS_AGENT_A
Admin = Callable[[str], psycopg.Connection[Any]]
PRODUCT_FIELDS = (
    "code",
    "name",
    "type",
    "covers_dependents",
    "policy_terms",
    "sum_assured_min",
    "sum_assured_max",
    "default_sum_assured",
    "default_term",
    "min_age",
    "max_age",
    "baseline_monthly",
)


def _expected_body() -> list[dict[str, Any]]:
    """The seeded catalogue as the endpoint must return it, ordered by code."""
    body = []
    for row in EXPECTED_PRODUCTS:
        product = dict(zip(PRODUCT_FIELDS, row, strict=True))
        product["riders"] = [
            {"code": code, "name": name, "baseline_monthly": baseline}
            for code, product_code, name, baseline in EXPECTED_RIDERS
            if product_code == product["code"]
        ]
        body.append(product)
    return body


def _as_decimals(value: Any) -> Any:
    """Parse the JSON body's numbers straight into Decimal, as coding-style.md rule 4 says."""
    if isinstance(value, dict):
        return {key: _as_decimals(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_decimals(item) for item in value]
    if isinstance(value, float):
        return Decimal(str(value))
    return value


@pytest.fixture
def client(db_settings: Settings, migrated_db: str) -> Iterator[TestClient]:
    settings = db_settings.model_copy(
        update={"database_name": migrated_db, "formapp_test_mode": True}
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def test_story_2_1_signed_in_agent_gets_every_product_with_its_riders(
    client: TestClient,
) -> None:
    response = client.get("/api/products", headers=TEST_PRINCIPAL)

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 5
    assert _as_decimals(body) == _expected_body()
    # Money is a JSON number, never a string; CFH has no sum assured.
    assert all(isinstance(product["baseline_monthly"], float) for product in body)
    cfh = next(product for product in body if product["code"] == "CFH")
    assert (
        cfh["sum_assured_min"],
        cfh["sum_assured_max"],
        cfh["default_sum_assured"],
    ) == (None, None, None)


def test_story_2_1_products_401_without_a_principal(client: TestClient) -> None:
    response = client.get("/api/products")

    assert response.status_code == 401
    assert "errors" in response.json()


def _insert_draft(
    admin: Admin,
    dbname: str,
    *,
    owner_oid: str,
    answers: dict[str, Any],
    created_at: str = "2026-09-25T03:00:00+00:00",
) -> UUID:
    """A draft with a chosen C2 (or none), inserted straight into the table -- Story 2.3 needs a
    stored proposal to resolve the insured's age from, and there is no write endpoint here."""
    wire_answers = {
        question_id: {"value": value, "source": "human", "updated_at": created_at}
        for question_id, value in answers.items()
    }
    with admin(dbname) as connection:
        row = connection.execute(
            "INSERT INTO proposal "
            "(owner_oid, owner_seq, schema_version, status, revision, answers, "
            "created_at, updated_at) "
            "VALUES (%s, 1, 1, 'draft', 0, %s, %s, %s) RETURNING id",
            (owner_oid, Jsonb(wire_answers), created_at, created_at),
        ).fetchone()
    assert row is not None
    return UUID(str(row[0]))


# Story 2.3: Ally's age (31, band 3) through FSH, the epic's own reference case.
ALLY_MONTHLY = 185.22
ALLY_YEARLY = 2111.51


def test_story_2_3_proposal_id_with_a_known_age_lists_only_eligible_products_priced(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        answers={"C2": "1994-11-20"},
    )

    response = client.get(
        f"/api/products?proposal_id={proposal_id}", headers=TEST_PRINCIPAL
    )

    assert response.status_code == 200
    body = response.json()
    # FSH's min/max age is 18-55: a 31-year-old is eligible for every seeded product but LWL
    # (which the seed doesn't gate that low, so this just checks FSH's own priced fields).
    fsh = next(product for product in body if product["code"] == "FSH")
    assert (fsh["monthly"], fsh["yearly"]) == (ALLY_MONTHLY, ALLY_YEARLY)
    assert "baseline_monthly" not in fsh
    rider = next(r for r in fsh["riders"] if r["code"] == "R07")
    assert (rider["monthly"], rider["yearly"]) == (34.73, 395.91)
    assert "baseline_monthly" not in rider
    # Every eligible product carries its other stored fields unchanged.
    assert fsh["sum_assured_min"] == 200000.0
    assert fsh["default_term"] == "20_yrs"


def test_form_18_proposal_id_keeps_products_outside_the_insureds_age(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    # FSH's max age is 55 and she was born in 1960; since FORM-18 (owner decision 2026-09-27)
    # no product is hidden by its age range.
    proposal_id = _insert_draft(
        admin,
        migrated_db,
        owner_oid=TEST_PRINCIPALS["agent-a"].oid,
        answers={"C2": "1960-01-01"},
    )

    response = client.get(
        f"/api/products?proposal_id={proposal_id}", headers=TEST_PRINCIPAL
    )

    assert response.status_code == 200
    assert "FSH" in [product["code"] for product in response.json()]


def test_story_2_3_proposal_id_with_no_c2_lists_every_product_at_baseline(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_draft(
        admin, migrated_db, owner_oid=TEST_PRINCIPALS["agent-a"].oid, answers={}
    )

    response = client.get(
        f"/api/products?proposal_id={proposal_id}", headers=TEST_PRINCIPAL
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 5  # nothing excluded
    fsh = next(product for product in body if product["code"] == "FSH")
    assert (fsh["monthly"], fsh["yearly"]) == (160.0, 1824.0)  # band 0 == baseline


def test_story_2_3_proposal_id_of_another_agents_proposal_404s_and_reveals_nothing(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    proposal_id = _insert_draft(
        admin, migrated_db, owner_oid=TEST_PRINCIPALS["agent-b"].oid, answers={}
    )

    response = client.get(
        f"/api/products?proposal_id={proposal_id}", headers=AS_AGENT_A
    )

    # ensure_owned's own body (adapters/rest/errors.py `_proposal_not_found`): a plain, identical
    # 404 whether the proposal is unowned or doesn't exist at all -- never the AD-12 shape (FR13,
    # NFR6).
    assert response.status_code == 404
    assert response.json() == {"detail": "Not found."}


def test_story_2_3_proposal_id_of_an_unknown_proposal_404s_the_same_way(
    client: TestClient, admin: Admin, migrated_db: str
) -> None:
    response = client.get(
        f"/api/products?proposal_id={UUID(int=0)}", headers=TEST_PRINCIPAL
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found."}
