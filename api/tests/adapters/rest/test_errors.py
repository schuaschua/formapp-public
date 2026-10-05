"""Story 1.3: domain errors and request validation errors leave api in the AD-12 shape."""

from collections.abc import Iterator

import pytest
from fastapi import Header
from fastapi.testclient import TestClient
from pydantic import BaseModel

from adapters.rest.app import create_app
from domain.errors import DomainError, ErrorCode, FieldError
from tests.support import AS_AGENT_A, make_settings


class Payload(BaseModel):
    age: int


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(make_settings(database_port=1))

    @app.get("/api/test-error/{code}")
    async def raise_code(code: ErrorCode) -> None:
        raise DomainError.single("C1", code, "Synthetic message.")

    @app.get("/api/test-mixed")
    async def raise_mixed() -> None:
        raise DomainError(
            [
                FieldError("C1", ErrorCode.REQUIRED, "Enter the first name."),
                FieldError("revision", ErrorCode.STALE_REVISION, "Reload the draft."),
            ]
        )

    @app.post("/api/test-body")
    async def body(payload: Payload) -> dict[str, int]:
        return {"age": payload.age}

    @app.get("/api/test-header")
    async def header(x_synthetic_flag: int = Header()) -> dict[str, int]:
        return {"flag": x_synthetic_flag}

    @app.get("/api/test-query")
    async def query(age: int) -> dict[str, int]:
        return {"age": age}

    with TestClient(app, headers=AS_AGENT_A) as test_client:
        yield test_client


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("required", 422),
        ("invalid_value", 422),
        ("inactive_field", 422),
        ("stale_revision", 409),
        ("lock_not_held", 409),
        ("turn_in_progress", 409),
        ("proposal_submitted", 409),
        ("rate_limited", 429),
        ("speech_unavailable", 503),
    ],
)
def test_story_1_3_domain_error_maps_to_ad12_response(
    client: TestClient, code: str, status: int
) -> None:
    response = client.get(f"/api/test-error/{code}")

    assert response.status_code == status
    assert response.json() == {
        "errors": [{"field": "C1", "code": code, "message": "Synthetic message."}]
    }


def test_story_1_3_mixed_errors_take_the_most_specific_status(
    client: TestClient,
) -> None:
    response = client.get("/api/test-mixed")

    assert response.status_code == 409
    assert [error["field"] for error in response.json()["errors"]] == ["C1", "revision"]


def test_story_1_3_request_validation_is_ad12_without_echoing_input(
    client: TestClient,
) -> None:
    invalid = client.get("/api/test-query", params={"age": "synthetic-not-a-number"})
    missing = client.get("/api/test-query")

    assert invalid.status_code == 422
    assert [(e["field"], e["code"]) for e in invalid.json()["errors"]] == [
        ("age", "invalid_value")
    ]
    assert "synthetic-not-a-number" not in invalid.text
    assert missing.json()["errors"][0]["code"] == "required"


def test_story_1_3_header_and_body_fields_drop_their_location_prefix(
    client: TestClient,
) -> None:
    header = client.get("/api/test-header", headers={"x-synthetic-flag": "nope"})
    body = client.post(
        "/api/test-body", json={"age": "nope"}, headers={"X-Session-Id": "tab-1"}
    )

    assert [e["field"] for e in header.json()["errors"]] == ["x-synthetic-flag"]
    assert [e["field"] for e in body.json()["errors"]] == ["age"]


def test_story_1_3_invalid_json_is_a_request_error(client: TestClient) -> None:
    response = client.post(
        "/api/test-body",
        content=b'{"age": 4',
        headers={"X-Session-Id": "tab-1", "Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert [(e["field"], e["code"]) for e in response.json()["errors"]] == [
        ("request", "invalid_value")
    ]
