"""Story 1.3: security headers on every response, the X-Session-Id forgery check, CORS off."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from adapters.rest.app import create_app
from adapters.rest.middleware import CONTENT_SECURITY_POLICY, content_security_policy
from tests.support import (
    AS_AGENT_A,
    assert_web_security_headers,
    make_settings,
    parse_csp,
    parse_permissions_policy,
)

EXPECTED_HEADERS = {
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "referrer-policy": "same-origin",
}


@pytest.fixture
def app_client() -> Iterator[TestClient]:
    app = create_app(make_settings(database_port=1))

    @app.get("/api/test-boom")
    async def boom() -> None:
        raise RuntimeError("synthetic failure with secret-ish detail")

    @app.post("/api/test-echo")
    async def echo() -> dict[str, str]:
        return {"status": "accepted"}

    # Signed in as a test agent: these tests are about the headers and the forgery check.
    with TestClient(app, raise_server_exceptions=False, headers=AS_AGENT_A) as client:
        yield client


def _assert_security_headers(headers: object) -> None:
    for name, value in EXPECTED_HEADERS.items():
        assert headers[name] == value  # type: ignore[index]
    assert_web_security_headers(headers)


def test_story_1_4_csp_parsing_handles_directives_without_a_value() -> None:
    assert parse_csp(
        "default-src 'self';  upgrade-insecure-requests ; img-src 'self'  data:"
    ) == {
        "default-src": "'self'",
        "upgrade-insecure-requests": "",
        "img-src": "'self' data:",
    }
    assert parse_permissions_policy("camera=(), usb=(self)") == {
        "camera": "()",
        "usb": "(self)",
    }


@pytest.mark.parametrize(
    ("method", "path", "headers", "status"),
    [
        ("GET", "/healthz", {}, 200),
        ("GET", "/api/nope", {}, 404),
        ("POST", "/api/test-echo", {}, 403),
        ("POST", "/api/test-echo", {"X-Session-Id": "tab-1"}, 200),
        ("GET", "/api/test-boom", {}, 500),
        ("GET", "/proposals/42", {}, 404),
    ],
)
def test_story_1_3_every_response_carries_the_security_headers(
    app_client: TestClient, method: str, path: str, headers: dict[str, str], status: int
) -> None:
    response = app_client.request(method, path, headers=headers)

    assert response.status_code == status
    _assert_security_headers(response.headers)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_story_1_3_non_get_api_without_session_id_is_forbidden(
    app_client: TestClient, method: str
) -> None:
    response = app_client.request(method, "/api/proposals")

    assert response.status_code == 403
    assert response.json() == {
        "errors": [
            {
                "field": "X-Session-Id",
                "code": "required",
                "message": "This request must come from the formapp web app. "
                "Reload the page and try again.",
            }
        ]
    }


def test_story_1_3_blank_session_id_is_forbidden(app_client: TestClient) -> None:
    response = app_client.post("/api/test-echo", headers={"X-Session-Id": "  "})

    assert response.status_code == 403


def test_story_1_3_session_id_lets_non_get_calls_through(
    app_client: TestClient,
) -> None:
    response = app_client.post("/api/test-echo", headers={"X-Session-Id": "tab-1"})

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}


def test_story_1_3_get_api_needs_no_session_id(app_client: TestClient) -> None:
    assert app_client.get("/api/nope").status_code == 404


def test_story_1_3_non_api_paths_skip_the_forgery_check(app_client: TestClient) -> None:
    # Not an /api path: the forgery check doesn't apply, and the SPA answers GET only.
    assert app_client.post("/proposals/42").status_code == 404


def test_story_1_3_unhandled_error_is_a_plain_500(
    app_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    response = app_client.get("/api/test-boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert "secret-ish" not in response.text
    assert "secret-ish" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_story_1_3_cors_stays_disabled(app_client: TestClient) -> None:
    response = app_client.options(
        "/api/proposals",
        headers={
            "Origin": "https://evil.example.test",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert "access-control-allow-origin" not in response.headers
    get = app_client.get("/healthz", headers={"Origin": "https://evil.example.test"})
    assert "access-control-allow-origin" not in get.headers


# --- Story 6.1: connect-src widens only when Speech is configured -------------------------------


def test_story_6_1_csp_is_unchanged_when_speech_is_not_configured() -> None:
    # make_settings() leaves every speech_* field unset (local/test/CI), so the CSP api actually
    # serves stays exactly the static _CSP_DIRECTIVES base (web parity, Story 1.4).
    assert content_security_policy(make_settings()) == CONTENT_SECURITY_POLICY


def test_story_6_1_csp_widens_connect_src_when_speech_is_configured() -> None:
    settings = make_settings(
        speech_region="southeastasia",
        speech_endpoint="https://cog-sample-demo-sea.cognitiveservices.azure.com",
        speech_resource_id="synthetic-resource-id",
        speech_identity_client_id="00000000-1111-2222-3333-444444444444",
        speech_locale="en-SG",
        speech_voice="en-SG-LunaNeural",
    )

    directives = parse_csp(content_security_policy(settings))

    assert directives["connect-src"] == (
        "'self' "
        "https://cog-sample-demo-sea.cognitiveservices.azure.com "
        "wss://cog-sample-demo-sea.cognitiveservices.azure.com "
        "https://southeastasia.stt.speech.microsoft.com "
        "wss://southeastasia.stt.speech.microsoft.com "
        "https://southeastasia.tts.speech.microsoft.com "
        "wss://southeastasia.tts.speech.microsoft.com"
    )
    # Every other directive is untouched.
    unchanged = parse_csp(content_security_policy(settings))
    del unchanged["connect-src"]
    baseline = parse_csp(CONTENT_SECURITY_POLICY)
    del baseline["connect-src"]
    assert unchanged == baseline


def test_story_6_1_the_running_app_serves_the_widened_csp_when_speech_is_configured() -> (
    None
):
    settings = make_settings(
        database_port=1,
        speech_region="southeastasia",
        speech_endpoint="https://cog-sample-demo-sea.cognitiveservices.azure.com",
        speech_resource_id="synthetic-resource-id",
        speech_identity_client_id="00000000-1111-2222-3333-444444444444",
        speech_locale="en-SG",
        speech_voice="en-SG-LunaNeural",
    )
    app = create_app(settings)

    with TestClient(app, headers=AS_AGENT_A) as client:
        response = client.get("/api/me")

    connect_src = parse_csp(response.headers["content-security-policy"])["connect-src"]
    assert "https://cog-sample-demo-sea.cognitiveservices.azure.com" in connect_src
    assert "https://southeastasia.stt.speech.microsoft.com" in connect_src
