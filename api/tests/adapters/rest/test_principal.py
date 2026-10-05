"""Story 1.6: the principal from X-MS-CLIENT-PRINCIPAL, test principals, and 401 on every /api route.

All names and ids are synthetic (security.md rule 1).
"""

import base64
import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient

from adapters.rest.app import create_app
from adapters.rest.principal import (
    PRINCIPAL_HEADER,
    TEST_PRINCIPAL_HEADER,
    TEST_PRINCIPALS,
    current_principal,
    parse_client_principal,
    principal_from_scope,
)
from domain.principal import Principal
from tests.support import AS_AGENT_A, AS_AGENT_B, make_settings

OID_CLAIM = "http://schemas.microsoft.com/identity/claims/objectidentifier"
SYNTHETIC_OID = "5a1e0000-0000-4000-8000-00000000a11e"
SIGN_IN_REQUIRED = {
    "errors": [
        {
            "field": "principal",
            "code": "required",
            "message": "Sign in with Microsoft to continue.",
        }
    ]
}


def encode(document: object) -> str:
    return base64.b64encode(json.dumps(document).encode()).decode()


def client_principal(*claims: tuple[str, str], **extra: Any) -> str:
    return encode(
        {
            "auth_typ": "aad",
            "claims": [{"typ": typ, "val": val} for typ, val in claims],
            "name_typ": "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
            "role_typ": "http://schemas.microsoft.com/ws/2008/06/identity/claims/role",
            **extra,
        }
    )


SIGNED_IN = client_principal(
    (OID_CLAIM, SYNTHETIC_OID), ("name", "Ally Macbeal"), ("given_name", "Ally")
)


def scope(headers: dict[str, str]) -> dict[str, Any]:
    return {
        "type": "http",
        "headers": [
            (name.lower().encode(), value.encode()) for name, value in headers.items()
        ],
    }


# --- The principal function (I/O matrix) --------------------------------------------------------


def test_story_1_6_signed_in_header_gives_oid_and_names() -> None:
    assert parse_client_principal(SIGNED_IN) == Principal(
        oid=SYNTHETIC_OID, name="Ally Macbeal", first_name="Ally"
    )


def test_story_1_6_short_oid_claim_is_accepted() -> None:
    header = client_principal(("oid", SYNTHETIC_OID), ("name", "Ally Macbeal"))

    principal = parse_client_principal(header)

    assert principal is not None
    assert principal.oid == SYNTHETIC_OID


def test_story_1_6_header_without_padding_is_accepted() -> None:
    assert parse_client_principal(SIGNED_IN.rstrip("=")) is not None


@pytest.mark.parametrize(
    ("claims", "first_name"),
    [
        ((("given_name", "Ally"),), "Ally"),
        (
            (
                (
                    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname",
                    "Allison",
                ),
            ),
            "Allison",
        ),
        ((), "Ally"),
        ((("given_name", "  "),), "Ally"),
    ],
)
def test_story_1_6_first_name_is_given_name_else_first_word(
    claims: tuple[tuple[str, str], ...], first_name: str
) -> None:
    header = client_principal(
        (OID_CLAIM, SYNTHETIC_OID), ("name", "Ally Macbeal"), *claims
    )

    principal = parse_client_principal(header)

    assert principal is not None
    assert principal.first_name == first_name


def test_story_1_6_without_name_or_given_name_first_name_is_the_name() -> None:
    principal = parse_client_principal(client_principal((OID_CLAIM, SYNTHETIC_OID)))

    assert principal == Principal(oid=SYNTHETIC_OID, name="", first_name="")


def test_story_1_6_name_falls_back_to_the_name_type_claim() -> None:
    header = client_principal(
        (OID_CLAIM, SYNTHETIC_OID),
        (
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
            "ally@example.test",
        ),
    )

    principal = parse_client_principal(header)

    assert principal is not None
    assert principal.name == "ally@example.test"


@pytest.mark.parametrize(
    "header",
    [
        "",
        "   ",
        "not base64 at all!",
        base64.b64encode(b"\xff\xfe not utf-8").decode(),
        base64.b64encode(b"not json").decode(),
        encode(["a", "list"]),
        encode({"claims": "not a list"}),
        encode({"claims": ["not a claim", {"typ": 1, "val": SYNTHETIC_OID}]}),
        client_principal(("name", "Ally Macbeal")),
        client_principal((OID_CLAIM, "   "), ("name", "Ally Macbeal")),
        base64.b64encode(b"[" * 100_000 + b"]" * 100_000).decode(),
    ],
    ids=[
        "empty",
        "blank",
        "not-base64",
        "not-utf8",
        "not-json",
        "not-an-object",
        "claims-not-a-list",
        "bad-claims",
        "no-oid",
        "blank-oid",
        "deeply-nested",
    ],
)
def test_story_1_6_malformed_header_gives_no_principal(header: str) -> None:
    assert parse_client_principal(header) is None


def test_story_1_6_missing_header_gives_no_principal() -> None:
    assert principal_from_scope(scope({}), make_settings()) is None


@pytest.mark.parametrize(
    ("name", "value"), [("agent-a", AS_AGENT_A), ("agent-b", AS_AGENT_B)]
)
def test_story_1_6_test_mode_accepts_the_test_principals(
    name: str, value: dict[str, str]
) -> None:
    principal = principal_from_scope(
        scope(value), make_settings(formapp_test_mode=True)
    )

    assert principal == TEST_PRINCIPALS[name]


def test_story_1_6_test_principals_are_distinct_agents() -> None:
    a, b = TEST_PRINCIPALS["agent-a"], TEST_PRINCIPALS["agent-b"]

    assert a.oid != b.oid


def test_story_1_6_unknown_test_principal_is_nobody() -> None:
    headers = {TEST_PRINCIPAL_HEADER: "agent-c", PRINCIPAL_HEADER: SIGNED_IN}

    assert principal_from_scope(scope(headers), make_settings()) is None


def test_story_1_6_test_mode_off_ignores_the_test_principal() -> None:
    settings = make_settings(formapp_test_mode=False)

    assert principal_from_scope(scope(AS_AGENT_A), settings) is None
    # A real principal still works with test mode off.
    both = {**AS_AGENT_A, PRINCIPAL_HEADER: SIGNED_IN}
    principal = principal_from_scope(scope(both), settings)
    assert principal is not None
    assert principal.oid == SYNTHETIC_OID


# --- 401 on every /api route --------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    return create_app(make_settings(database_port=1, formapp_test_mode=False))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _api_calls(app: FastAPI) -> list[tuple[str, str]]:
    """Every (method, path) registered under /api, including routes in included routers."""
    calls: list[tuple[str, str]] = []
    # iter_route_contexts is how FastAPI's own OpenAPI generator walks included routers.
    for route in iter_route_contexts(app.routes):
        path = route.path
        if (
            isinstance(route.original_route, APIRoute)
            and path
            and (path == "/api" or path.startswith("/api/"))
        ):
            concrete = re.sub(r"\{[^}]+\}", "synthetic", path)
            calls.extend((method, concrete) for method in sorted(route.methods or ()))
    return calls


def test_story_1_6_every_registered_api_route_needs_sign_in(
    app: FastAPI, client: TestClient
) -> None:
    calls = _api_calls(app)
    assert ("GET", "/api/me") in calls

    for method, path in calls:
        response = client.request(method, path, headers={"X-Session-Id": "tab-1"})
        assert (method, path, response.status_code) == (method, path, 401)
        assert response.json() == SIGN_IN_REQUIRED


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api"),
        ("GET", "/api/nope"),
        ("POST", "/api/proposals"),
        ("PATCH", "/api/proposals/42"),
    ],
)
def test_story_1_6_unknown_api_paths_get_401_before_404_or_403(
    client: TestClient, method: str, path: str
) -> None:
    # No X-Session-Id either: the sign-in check comes first.
    response = client.request(method, path)

    assert response.status_code == 401
    assert response.json() == SIGN_IN_REQUIRED
    assert response.headers["x-content-type-options"] == "nosniff"


def test_story_1_6_forged_or_test_header_without_test_mode_gets_401(
    client: TestClient,
) -> None:
    assert client.get("/api/me", headers=AS_AGENT_A).status_code == 401
    assert (
        client.get("/api/me", headers={PRINCIPAL_HEADER: "forged"}).status_code == 401
    )


@pytest.mark.parametrize("path", ["/healthz", "/.auth/login/aad", "/proposals"])
def test_story_1_6_public_paths_need_no_sign_in(client: TestClient, path: str) -> None:
    # /healthz answers; /.auth and the SPA paths are never 401 from api (no static build here).
    status = client.get(path).status_code
    if path == "/healthz":
        assert status == 200
    else:
        assert status != 401
    assert client.get("/readyz").status_code == 503  # no database, but not 401


def test_story_1_6_current_principal_without_the_middleware_is_401() -> None:
    app = create_app(make_settings(database_port=1))

    # A route outside /api, where the middleware doesn't run, that still asks for a principal.
    @app.get("/outside-api")
    async def outside(
        principal: Principal = Depends(current_principal),  # noqa: B008 -- FastAPI dependency
    ) -> dict[str, str]:
        return {"name": principal.name}

    with TestClient(app, headers=AS_AGENT_A) as client:
        response = client.get("/outside-api")

    assert response.status_code == 401
    assert response.json() == SIGN_IN_REQUIRED


# --- GET /api/me --------------------------------------------------------------------------------


def test_story_1_6_me_returns_the_display_and_first_name(client: TestClient) -> None:
    response = client.get("/api/me", headers={PRINCIPAL_HEADER: SIGNED_IN})

    assert response.status_code == 200
    assert response.json() == {"name": "Ally Macbeal", "first_name": "Ally"}
    assert SYNTHETIC_OID not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_story_1_6_me_answers_as_the_test_principal_in_test_mode() -> None:
    with TestClient(create_app(make_settings(database_port=1))) as client:
        response = client.get("/api/me", headers=AS_AGENT_B)

    assert response.json() == {"name": "Bala Synthetic", "first_name": "Bala"}


def test_story_1_6_principal_data_is_never_logged(
    client: TestClient,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    capsys.readouterr()
    client.get("/api/me", headers={PRINCIPAL_HEADER: SIGNED_IN})
    client.get("/api/me", headers={PRINCIPAL_HEADER: "forged"})

    logged = capsys.readouterr().out + caplog.text
    for value in (SIGNED_IN, SYNTHETIC_OID, "Ally Macbeal", "forged"):
        assert value not in logged
