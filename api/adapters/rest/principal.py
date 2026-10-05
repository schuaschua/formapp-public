"""Who is calling: the signed-in principal from Container Apps sign-in (Story 1.6, spine AD-4, AD-8).

Container Apps authentication (Easy Auth, Entra) signs the agent in and passes her claims to the app
in ``X-MS-CLIENT-PRINCIPAL``: base64 JSON ``{auth_typ, claims: [{typ, val}], name_typ, role_typ}``.
The platform strips any client-sent copy of that header, so the app can trust it; the post-deploy
smoke check proves this after every deploy. The header, names and oids are never logged
(security.md rules 4, 30).

In test mode only (never in demo, AD-18), ``X-Formapp-Test-Principal: agent-a`` or ``agent-b``
stands in for a signed-in agent, so the 401 sweep and ownership tests run without Entra.
"""

import base64
import binascii
import json
from collections.abc import Mapping

from fastapi import Request
from starlette.types import Scope

from adapters.settings import Settings
from domain.errors import ErrorCode, FieldError, error_body
from domain.principal import Principal, first_name_of

PRINCIPAL_HEADER = "X-MS-CLIENT-PRINCIPAL"
TEST_PRINCIPAL_HEADER = "X-Formapp-Test-Principal"

# Where the middleware leaves the principal for the request (scope["state"]).
_STATE_KEY = "principal"

# Entra sends the object id under its long claim type; the short form is accepted too.
_OID_CLAIMS = ("http://schemas.microsoft.com/identity/claims/objectidentifier", "oid")
_NAME_CLAIM = "name"
_GIVEN_NAME_CLAIMS = (
    "given_name",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname",
)

# AD-18 test principals: fixed synthetic agents (security.md rule 1).
TEST_PRINCIPALS: Mapping[str, Principal] = {
    "agent-a": Principal(
        oid="00000000-0000-4000-8000-00000000000a",
        name="Alice Synthetic",
        first_name="Alice",
    ),
    "agent-b": Principal(
        oid="00000000-0000-4000-8000-00000000000b",
        name="Bala Synthetic",
        first_name="Bala",
    ),
}

# The AD-12 body for a call without a signed-in principal.
SIGN_IN_REQUIRED = error_body(
    [
        FieldError(
            field="principal",
            code=ErrorCode.REQUIRED,
            message="Sign in with Microsoft to continue.",
        )
    ]
)


class SignInRequired(Exception):
    """A route needed a principal and the request had none; answered with a 401."""


def parse_client_principal(value: str) -> Principal | None:
    """The principal in an ``X-MS-CLIENT-PRINCIPAL`` value, or None if it is missing or malformed."""
    value = value.strip()
    if not value:
        return None
    try:
        # Tolerate missing padding; anything that isn't base64 JSON is no principal.
        raw = base64.b64decode(value + "=" * (-len(value) % 4), validate=True)
        document = json.loads(raw.decode("utf-8"))
    # RecursionError: deeply nested JSON must be no principal, not a 500.
    except (binascii.Error, UnicodeDecodeError, ValueError, RecursionError):
        return None
    claims = _claims(document)
    oid = next((claims[typ] for typ in _OID_CLAIMS if claims.get(typ)), "")
    if not oid:
        return None
    name = claims.get(_NAME_CLAIM, "")
    if not name and isinstance(document, dict):
        name_type = document.get("name_typ")
        if isinstance(name_type, str):
            name = claims.get(name_type, "")
    given_name = next(
        (claims[typ] for typ in _GIVEN_NAME_CLAIMS if claims.get(typ)), None
    )
    return Principal(oid=oid, name=name, first_name=first_name_of(name, given_name))


def _claims(document: object) -> dict[str, str]:
    """Claim type -> the first non-blank value; entries that aren't strings are ignored."""
    claims: dict[str, str] = {}
    if not isinstance(document, dict):
        return claims
    items = document.get("claims")
    if not isinstance(items, list):
        return claims
    for item in items:
        if not isinstance(item, dict):
            continue
        typ, val = item.get("typ"), item.get("val")
        if isinstance(typ, str) and isinstance(val, str) and val.strip():
            claims.setdefault(typ, val.strip())
    return claims


def _header(scope: Scope, name: str) -> str | None:
    wanted = name.lower().encode()
    for key, value in scope.get("headers", []):
        if key.lower() == wanted:
            return str(value.decode("latin-1"))
    return None


def principal_from_scope(scope: Scope, settings: Settings) -> Principal | None:
    """The one place that decides who is calling (AD-8); None when nobody is signed in."""
    if settings.formapp_test_mode:
        test_name = _header(scope, TEST_PRINCIPAL_HEADER)
        if test_name is not None:
            # An unknown test principal is nobody, never a fall-through to the real header.
            return TEST_PRINCIPALS.get(test_name.strip())
    header = _header(scope, PRINCIPAL_HEADER)
    return parse_client_principal(header) if header is not None else None


def remember_principal(scope: Scope, principal: Principal | None) -> None:
    """Keep the principal on the request for ``current_principal``."""
    scope.setdefault("state", {})[_STATE_KEY] = principal


def current_principal(request: Request) -> Principal:
    """FastAPI dependency: the signed-in principal the middleware found for this request."""
    principal = request.scope.get("state", {}).get(_STATE_KEY)
    if not isinstance(principal, Principal):
        raise SignInRequired
    return principal
