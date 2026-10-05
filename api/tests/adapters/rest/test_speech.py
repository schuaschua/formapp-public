"""Story 6.1: ``GET /api/speech/token`` (spine AD-12, AD-18, AD-19).

``adapters.rest.principal``'s 401 sweep (``test_story_1_6_every_registered_api_route_needs_sign_in``)
already proves every ``/api`` route -- this route included -- 401s with no principal at all; this
file adds the turn-token-only case the spec calls out by name, plus the 200 shape and the
``speech_unavailable`` 503 mapping, all against the ``StubSpeechTokenIssuer`` (AD-18: never a real
Azure call).
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from adapters.rest.app import create_app
from adapters.speech.stub import StubSpeechTokenIssuer
from tests.fakes import FakeClock
from tests.support import AS_AGENT_A, make_settings

SIGN_IN_REQUIRED = {
    "errors": [
        {
            "field": "principal",
            "code": "required",
            "message": "Sign in with Microsoft to continue.",
        }
    ]
}


@pytest.fixture
def issuer() -> StubSpeechTokenIssuer:
    return StubSpeechTokenIssuer(clock=FakeClock())


@pytest.fixture
def client(issuer: StubSpeechTokenIssuer) -> Iterator[TestClient]:
    app = create_app(make_settings(database_port=1), speech_token_issuer=issuer)
    with TestClient(app, headers=AS_AGENT_A) as test_client:
        yield test_client


def test_story_6_1_signed_in_agent_gets_the_token_shape(
    client: TestClient,
) -> None:
    response = client.get("/api/speech/token")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "token",
        "auth_mode",
        "region",
        "endpoint",
        "voice",
        "locale",
        "expires_at",
    }
    assert body["token"].startswith("aad#")
    assert body["auth_mode"] == "aad"
    assert body["region"] == "southeastasia"
    assert body["voice"] == "en-SG-LunaNeural"
    assert body["locale"] == "en-SG"
    assert body["expires_at"].endswith("Z")
    assert response.headers["cache-control"] == "no-store"


def test_story_6_1_no_principal_gets_401_and_no_token() -> None:
    app = create_app(
        make_settings(database_port=1),
        speech_token_issuer=StubSpeechTokenIssuer(clock=FakeClock()),
    )

    with TestClient(app) as client:
        response = client.get("/api/speech/token")

    assert response.status_code == 401
    assert response.json() == SIGN_IN_REQUIRED


def test_story_6_1_turn_token_only_call_gets_401_and_no_token() -> None:
    """A turn token (however it's carried) never populates the REST principal (AD-4, AD-8):
    AuthRequiredMiddleware only ever looks at X-MS-CLIENT-PRINCIPAL (or, in test mode, the test
    principal header), never Authorization -- so a call carrying only a turn-token-shaped bearer
    value, and no principal header at all, 401s exactly like an anonymous call."""
    app = create_app(
        make_settings(database_port=1),
        speech_token_issuer=StubSpeechTokenIssuer(clock=FakeClock()),
    )
    turn_token_shaped = "synthetic.turn.token-not-a-principal"  # noqa: S105 -- test-only, not a real token

    with TestClient(app) as client:
        response = client.get(
            "/api/speech/token",
            headers={"Authorization": f"Bearer {turn_token_shaped}"},
        )

    assert response.status_code == 401
    assert response.json() == SIGN_IN_REQUIRED


def test_story_6_1_speech_failure_is_the_ad12_speech_unavailable_shape(
    client: TestClient, issuer: StubSpeechTokenIssuer
) -> None:
    issuer.fail = True

    response = client.get("/api/speech/token")

    assert response.status_code == 503
    assert response.json() == {
        "errors": [
            {
                "field": "speech",
                "code": "speech_unavailable",
                "message": "Speech is unavailable right now. Try again shortly.",
            }
        ]
    }
