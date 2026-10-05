"""Security headers, the sign-in check and the forgery check (security.md rules 4, 22-25).

Pure ASGI middleware, so streamed responses (the chat SSE relay in Epic 4) pass through unbuffered.
"""

import json
import logging
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from adapters.db.scope import for_owner, scoped
from adapters.rest.principal import (
    SIGN_IN_REQUIRED,
    principal_from_scope,
    remember_principal,
)
from adapters.settings import Settings
from adapters.telemetry import record_unhandled_exception
from domain.errors import ErrorCode, FieldError, error_body

logger = logging.getLogger(__name__)

# Self only, no inline scripts or styles (security.md rule 24). The web app loads only its own
# hashed bundles, uses system fonts and calls only /api, so every fetch directive stays 'self'.
# web/vite.config.ts repeats this policy for its Playwright check; keep the two equal.
_CSP_DIRECTIVES = (
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "form-action 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
)
CONTENT_SECURITY_POLICY = "; ".join(_CSP_DIRECTIVES)

# Deny powerful browser features to the page and anything it could embed. The one exception is the
# microphone, allowed to this origin only, for the chat's hold-to-talk mic (Story 6.2, AD-19).
PERMISSIONS_POLICY = ", ".join(
    [
        *(
            f"{feature}=()"
            for feature in (
                "accelerometer",
                "camera",
                "geolocation",
                "gyroscope",
                "magnetometer",
                "payment",
                "usb",
            )
        ),
        "microphone=(self)",
    ]
)


def _speech_connect_src_hosts(settings: Settings) -> tuple[str, ...]:
    """Hosts ``connect-src`` must allow for Speech (Story 6.1, AD-19), empty when Speech isn't
    configured (local/test/CI -- ``make_settings()`` and the api-image/e2e ``check.sh`` sections
    never set these, so the static, unwidened ``_CSP_DIRECTIVES`` stays exactly what those run,
    keeping Story 1.4 parity with ``web/security-headers.ts``).

    Both the configured Speech endpoint's own host and the region's generic stt/tts hosts, each as
    ``https://`` and ``wss://`` (plan Implementation Notes: the AC asks for "the configured Speech
    endpoint AND region hosts", and a custom-subdomain endpoint and the generic regional hosts
    aren't guaranteed to be the same host).
    """
    if not (settings.speech_endpoint and settings.speech_region):
        return ()
    region = settings.speech_region
    hosts = {
        host
        for host in (
            urlsplit(settings.speech_endpoint).hostname,
            f"{region}.stt.speech.microsoft.com",
            f"{region}.tts.speech.microsoft.com",
        )
        if host
    }
    return tuple(
        f"{scheme}://{host}" for host in sorted(hosts) for scheme in ("https", "wss")
    )


def content_security_policy(settings: Settings) -> str:
    """The CSP the app actually serves (Story 6.1): ``_CSP_DIRECTIVES`` unchanged, except
    ``connect-src`` widened with ``_speech_connect_src_hosts`` when Speech is configured."""
    speech_hosts = _speech_connect_src_hosts(settings)
    if not speech_hosts:
        return CONTENT_SECURITY_POLICY
    directives = [
        " ".join(["connect-src", "'self'", *speech_hosts])
        if directive.startswith("connect-src ")
        else directive
        for directive in _CSP_DIRECTIVES
    ]
    return "; ".join(directives)


def build_security_headers(csp: str) -> tuple[tuple[bytes, bytes], ...]:
    return (
        (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
        (b"content-security-policy", csp.encode()),
        (b"x-content-type-options", b"nosniff"),
        (b"referrer-policy", b"same-origin"),
        (b"permissions-policy", PERMISSIONS_POLICY.encode()),
    )


# The default, unwidened headers (today's fixed tuple); create_app passes its own, built from
# content_security_policy(settings), to SecurityHeadersMiddleware.
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = build_security_headers(
    CONTENT_SECURITY_POLICY
)

SESSION_HEADER = "X-Session-Id"
_SAFE_METHODS = frozenset({"GET", "HEAD"})


def _is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


async def _send_json(send: Send, status: int, body: object) -> None:
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(payload)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": payload})


class SecurityHeadersMiddleware:
    """Adds the security headers to every response, including errors (security.md rule 24).

    It is the outermost application middleware, so it also turns an unhandled exception into a plain
    500 that carries the headers and no stack trace, SQL or path (security.md rule 25).
    """

    def __init__(
        self,
        app: ASGIApp,
        security_headers: tuple[tuple[bytes, bytes], ...] = SECURITY_HEADERS,
    ) -> None:
        self.app = app
        # Story 6.1: create_app passes its own tuple, built from content_security_policy(settings),
        # so the CSP's connect-src can widen for Speech without changing the static base
        # (_CSP_DIRECTIVES) that Story 1.4's web parity test parses out of this module's source.
        self.security_headers = security_headers

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                names = {name.lower() for name, _ in message.get("headers", [])}
                extra = [
                    header for header in self.security_headers if header[0] not in names
                ]
                message["headers"] = [*message.get("headers", []), *extra]
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        # Every unhandled error ends here: a 500 before the response starts, a cut-off response after.
        except Exception as exc:  # noqa: BLE001
            # The message can hold values or connection details; record and log only the type and
            # route (security.md rule 30).
            record_unhandled_exception(exc)
            logger.error(
                "Unhandled %s on %s %s.",
                type(exc).__name__,
                scope["method"],
                scope["path"],
            )
            if started:
                # Too late for a 500: end the response here. Re-raising would let the tracing
                # middleware record the exception with its message, and uvicorn log its traceback.
                return
            await _send_json(
                send_with_headers, 500, {"detail": "Internal Server Error"}
            )


class AuthRequiredMiddleware:
    """Answers every /api call without a signed-in principal with 401 (security.md rule 4, AD-8).

    Middleware rather than a per-route dependency, so routes added later and unknown /api paths are
    covered too. It sits outside the forgery check, so a signed-out call gets 401 before any 403.
    /healthz, /readyz, the static web files and /.auth/* are not /api paths and stay public.

    Once a principal is found, the whole downstream call runs with the row-level security scope set
    to her own oid (Story 4.3 Part B, AD-17): every ``proposal`` transaction any route opens from
    here on sees and changes only her own rows, a second guard under the domain's own ownership
    checks.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and _is_api_path(scope["path"]):
            principal = principal_from_scope(scope, self.settings)
            if principal is None:
                await _send_json(send, 401, SIGN_IN_REQUIRED)
                return
            remember_principal(scope, principal)
            with scoped(for_owner(principal.oid)):
                await self.app(scope, receive, send)
            return
        await self.app(scope, receive, send)


class SessionHeaderMiddleware:
    """Rejects a state-changing /api call without X-Session-Id with 403 (security.md rule 23).

    Browsers can't add a custom header to a cross-site form post, and CORS stays off, so the header
    proves the call came from formapp's own pages.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] not in _SAFE_METHODS
            and _is_api_path(scope["path"])
            and not _session_id(scope)
        ):
            error = FieldError(
                field=SESSION_HEADER,
                code=ErrorCode.REQUIRED,
                message="This request must come from the formapp web app. Reload the page and try again.",
            )
            await _send_json(send, 403, error_body([error]))
            return
        await self.app(scope, receive, send)


def _session_id(scope: Scope) -> str:
    wanted = SESSION_HEADER.lower().encode()
    for name, value in scope.get("headers", []):
        if name.lower() == wanted:
            return str(value.decode("latin-1").strip())
    return ""
