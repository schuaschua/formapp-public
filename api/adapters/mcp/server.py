"""The ``/mcp`` Streamable HTTP server: seven fixed form tools, authorized by a turn token (Story
4.3, spine AD-2, AD-3, AD-4; ``find_customer`` added by Story 5.1, ``link_customer`` by Story 5.2,
both AD-13).

**[ASSUMPTION] mcp mounting.** The spec named ``mcp.server.fastmcp.FastMCP`` (mcp 1.x); the
installed ``mcp==2.2.0`` renamed it to ``mcp.server.mcpserver.MCPServer`` and moved
``stateless_http`` from its constructor to ``streamable_http_app(stateless_http=True)`` -- both
adjusted here, noted per the spec's own instruction to verify against the installed version.

**[ASSUMPTION] mounting under FastAPI, not ``app.mount()``.** ``FastAPI.mount("/mcp", mcp_app)``
302/307-redirects a bare ``POST /mcp`` (no trailing slash) to ``/mcp/``: Starlette's router
requires a path segment after a ``Mount``'s own prefix to match without a redirect, and the MCP
client's own Streamable HTTP transport calls with ``follow_redirects=False`` (a change of method
across a redirect is unsafe for a POST), so the redirect just breaks the call. Instead,
:class:`MCPDispatchMiddleware` is a pure ASGI middleware, added like ``SecurityHeadersMiddleware``
and friends (``adapters.rest.middleware``): it hands anything under ``/mcp`` straight to the mounted
MCP app, bypassing FastAPI's router (and its redirect) entirely, and passes everything else through
unchanged. This is also why the DNS-rebinding "Host header" check
(``mcp.server.transport_security.TransportSecuritySettings``, on by default only for the
``host="127.0.0.1"``/``"localhost"`` defaults ``streamable_http_app()`` assumes) is turned off
below: the real boundary here is the turn token, checked on every call regardless of Host/Origin,
so a mismatching default host allowlist must never 421 a legitimate call.

**[ASSUMPTION] ``get_draft``'s ``lock.holder`` for the AI's own call.** ``draft_view``/``lock_view``
are called with ``session_id="ai"`` (:data:`domain.proposals._AI_HOLDER`), so
``relative_holder("ai", "ai")`` returns ``"you"``: the AI sees itself as the current holder, same
as a human sees her own lock (spec Intent).

**``find_customer`` and AD-17 (Story 5.1).** ``customer`` has no row-level security -- AD-17 only
forces it on ``proposal``/``answer_overrides`` -- and ``find_customer`` searches every stored
customer, not scoped by owner (AD-13). It still runs inside ``_authorize`` like every other tool,
so a valid turn token is required (per the story's own acceptance criteria); the ``app.proposal_id``
scope ``_authorize`` sets for that check is simply never read by a query that only touches
``customer``, so it's a harmless no-op here.

Every tool first resolves the caller's turn token -- the ``Authorization: Bearer`` header MCP's own
``Context`` exposes -- through :func:`domain.turn_tokens.resolve_turn`. On any rejection (a bad
token, or a turn that has moved on) the tool's own body never runs: the call still succeeds at the
MCP protocol level, but its result is the same closed AD-12 shape (``{"errors": [...]}"``) every
other rejection uses, coded ``lock_not_held`` regardless of which check failed (security.md rule
36) -- a forged signature, an expired token, a tampered ``pid``, another agent's own valid token,
a stale ``tid``, and a token for the wrong turn are all indistinguishable to the caller. None of the
seven tools takes a parameter that names or could carry a *proposal* id (AD-3): ``patch_draft``'s
``answers``, ``find_customer``'s ``first_name``/``last_name``/``date_of_birth`` and
``link_customer``'s ``customer_id`` are the only arguments any tool takes; ``customer_id`` names a
customer, never a proposal, so it isn't the forbidden kind of ``*_id`` (Story 5.1/5.2, AD-3) -- the
proposal itself is always the token's own ``pid``.

``_authorize`` is an async context manager (Story 4.3 Part B, AD-17, security.md rule 37): as soon
as the token's signature is verified, it sets the row-level security scope to ``app.proposal_id``
from the token's own (still-unverified-by-ownership) ``pid`` -- narrowing every transaction in the
tool's body to that one row, before :func:`domain.turn_tokens.resolve_turn` even reads it to check
that the token's subject owns it -- and keeps that scope active for the rest of the tool's body, so
``patch_draft``'s own write transaction is scoped too. A row that doesn't exist, or exists but is
owned by someone else, is invisible either way; ``resolve_turn`` then raises the same
``TurnTokenError`` it always did, never a 500.
"""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast
from uuid import UUID

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.applications import Starlette
from starlette.types import ASGIApp, Receive, Scope, Send

from adapters.chat.logging_events import log_ai_write
from adapters.db.customers import SqlCustomerStore
from adapters.db.products import SqlProductCatalogue
from adapters.db.proposals import SqlProposalStore
from adapters.db.scope import for_proposal, scoped
from domain.clock import Clock
from domain.customer_fields import db_columns
from domain.customers import find_customers, parse_partial_date
from domain.errors import DomainError, ErrorCode
from domain.pricing import age_at
from domain.products import PricedProduct, list_products, priced_products
from domain.proposals import (
    Proposal,
    _date_of_birth,
    apply_agent_patch,
    draft_view,
    quote_view,
    resolve_quote,
    validate_proposal,
)
from domain.proposals import link_customer as link_customer_rule
from domain.schema import load_schema, thaw
from domain.turn_tokens import (
    TurnTokenClaims,
    TurnTokenError,
    decode_turn_token,
    resolve_turn,
)

MCP_PATH = "/mcp"

_REJECTED_MESSAGE = "This turn is no longer active."
_AI_SESSION_ID = "ai"
_CENTS = Decimal("0.01")
_MALFORMED_CUSTOMER_ID_MESSAGE = "This isn't a valid customer id."


#  Only these methods are dispatched to the MCP app. A stateless server (this one) never returns
# an Mcp-Session-Id, so a real client only ever POSTs (and, at most, DELETEs a session that never
# existed here); GET opens the Streamable HTTP transport's long-lived SSE listen stream, which
# never completes -- forwarding it would turn a request into a hang instead of a quick 404
# (caught by the reserved-prefix check in adapters.rest.spa: GET /mcp and /mcp/tools must 404, not
# hang or fall back to the SPA).
_DISPATCHED_METHODS = frozenset({"POST", "DELETE"})


class MCPDispatchMiddleware:
    """Pure ASGI middleware: hands a POST/DELETE under ``mount_path`` to ``mcp_app`` directly,
    bypassing FastAPI's router (see this module's docstring for why); everything else (including a
    GET, which the SPA's reserved-prefix check must still 404) passes through unchanged."""

    def __init__(self, app: ASGIApp, *, mcp_app: ASGIApp, mount_path: str = MCP_PATH) -> None:
        self.app = app
        self.mcp_app = mcp_app
        self._prefix = mount_path
        self._nested_prefix = mount_path + "/"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] in _DISPATCHED_METHODS
            and (scope["path"] == self._prefix or scope["path"].startswith(self._nested_prefix))
        ):
            await self.mcp_app(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _money(value: Decimal) -> float:
    # coding-style.md rule 4: amounts go on the wire as JSON numbers rounded to 2 decimals, same
    # convention as adapters.rest.products.Money -- the MCP adapter maps its own wire shape rather
    # than sharing REST's pydantic response models (spine AD-2: adapters share domain code, not
    # each other's wire mapping).
    return float(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


def _optional_money(value: Decimal | None) -> float | None:
    return _money(value) if value is not None else None


def _priced_product_dict(product: PricedProduct) -> dict[str, Any]:
    return {
        "code": product.code,
        "name": product.name,
        "type": product.type.value,
        "covers_dependents": product.covers_dependents,
        "policy_terms": [
            {"code": term.code, "label": term.label} for term in product.policy_terms
        ],
        "sum_assured_min": _optional_money(product.sum_assured_min),
        "sum_assured_max": _optional_money(product.sum_assured_max),
        "default_sum_assured": _optional_money(product.default_sum_assured),
        "default_term": product.default_term,
        "min_age": product.min_age,
        "max_age": product.max_age,
        "monthly": _money(product.monthly),
        "yearly": _money(product.yearly),
        "riders": [
            {
                "code": rider.code,
                "name": rider.name,
                "monthly": _money(rider.monthly),
                "yearly": _money(rider.yearly),
            }
            for rider in product.riders
        ],
    }


def _quote_dict(view: dict[str, Any] | None) -> dict[str, Any] | None:
    if view is None:
        return None
    return {
        "monthly": _money(view["monthly"]),
        "yearly": _money(view["yearly"]),
        "lines": [
            {
                "item": line["item"],
                "monthly": _money(line["monthly"]),
                "yearly": _money(line["yearly"]),
            }
            for line in view["lines"]
        ],
    }


def _rejected(exc: TurnTokenError | DomainError) -> dict[str, Any]:
    """The uniform rejection body (security.md rule 36): whatever failed, the caller sees
    ``lock_not_held`` and nothing else -- a ``DomainError`` (already coded, e.g. a genuine
    ``proposal_submitted`` from mid-call, or ``resolve_turn``'s own ``lock_not_held``) is returned
    as-is; a ``TurnTokenError`` (a bad token, never coded) is mapped to the same shape."""
    if isinstance(exc, DomainError):
        return exc.to_dict()
    return DomainError.single("turn", ErrorCode.LOCK_NOT_HELD, _REJECTED_MESSAGE).to_dict()


def _bearer_token(headers: Any) -> str | None:
    """The ``Authorization`` header's bearer token, or ``None`` (security.md rule 6). Never logged,
    never echoed back in any tool result (security.md rule 7)."""
    if not headers:
        return None
    value = headers.get("authorization")
    if value is None:
        # Context.headers is whatever the transport handed it; Starlette's own Headers are
        # case-insensitive, but a plain dict might not be.
        value = next((v for k, v in headers.items() if k.lower() == "authorization"), None)
    if not isinstance(value, str) or not value.lower().startswith("bearer "):
        return None
    token = value[len("bearer ") :].strip()
    return token or None


def build_mcp_app(
    engine: AsyncEngine, signing_key: SecretStr, clock: Clock
) -> tuple[MCPServer, Starlette]:
    """Build the ``MCPServer`` and its Streamable HTTP ASGI app.

    The caller (``adapters.rest.app.create_app``) must run ``server.session_manager.run()`` inside
    the host app's own lifespan (the session manager's task group only exists inside that context
    manager) and mount the returned app with :class:`MCPDispatchMiddleware`.
    """
    store = SqlProposalStore(engine)
    catalogue = SqlProductCatalogue(engine)
    customer_store = SqlCustomerStore(engine)
    server = MCPServer("formapp")

    @asynccontextmanager
    async def _authorize(
        ctx: Context,
    ) -> AsyncIterator[tuple[Proposal, TurnTokenClaims] | dict[str, Any]]:
        token = _bearer_token(ctx.headers)
        if token is None:
            yield _rejected(TurnTokenError("Missing bearer token."))
            return
        try:
            claims = decode_turn_token(token, signing_key, clock)
        except TurnTokenError as exc:
            yield _rejected(exc)
            return
        # Scoped from here to the end of the caller's `async with` block (AD-17): narrows every
        # transaction in the tool's body -- including resolve_turn's own read below -- to this one
        # proposal, whether or not its owner turns out to match the token's subject.
        with scoped(for_proposal(claims.pid)):
            try:
                proposal = await resolve_turn(store, token, signing_key, clock)
            except (TurnTokenError, DomainError) as exc:
                yield _rejected(exc)
                return
            yield proposal, claims

    @server.tool()
    async def get_form_schema(ctx: Context) -> dict[str, Any]:
        """The exact form schema pinned on the proposal this turn is bound to (Story 4.3, AD-7)."""
        async with _authorize(ctx) as authorized:
            if isinstance(authorized, dict):
                return authorized
            proposal, _claims = authorized
            return cast(dict[str, Any], thaw(load_schema(proposal.schema_version)))

    @server.tool()
    async def get_draft(ctx: Context) -> dict[str, Any]:
        """The current draft: answers, active questions, provenance, lock and quote (AD-5)."""
        async with _authorize(ctx) as authorized:
            if isinstance(authorized, dict):
                return authorized
            proposal, _claims = authorized
            view = draft_view(proposal, session_id=_AI_SESSION_ID)
            view["id"] = str(view["id"])
            view["quote"] = _quote_dict(quote_view(await resolve_quote(proposal, catalogue)))
            return view

    @server.tool()
    async def patch_draft(answers: dict[str, Any], ctx: Context) -> dict[str, Any]:
        """Apply every valid, writable, active field in ``answers`` in one transaction, at
        ``source: ai`` (AD-3, AD-6, AD-14, AD-15). Returns ``{applied, errors, revision}``."""
        async with _authorize(ctx) as authorized:
            if isinstance(authorized, dict):
                return authorized
            proposal, claims = authorized
            schema = load_schema(proposal.schema_version)
            products = await list_products(catalogue)
            outcome: dict[str, Any] = {}

            def apply(current: Proposal) -> Proposal | None:
                updated, applied, errors = apply_agent_patch(
                    schema, current, answers, clock, products, claims
                )
                outcome["applied"] = applied
                outcome["errors"] = errors
                return updated

            try:
                updated = await store.apply_agent_patch(proposal.id, apply)
            except DomainError as exc:
                return _rejected(exc)
            if updated is None:  # pragma: no cover -- the row existed a moment ago (resolve_turn)
                return _rejected(TurnTokenError("This turn's proposal no longer exists."))
            if outcome["applied"]:
                # Story 4.5, AC14, security.md rule 38: proposal_id is the row this write actually
                # landed on (updated.id, same as proposal.id here -- apply_agent_patch never moves a
                # write to another row), never taken from the caller-supplied token alone.
                log_ai_write(
                    proposal_id=updated.id,
                    turn_id=claims.tid,
                    conversation_id=updated.conversation_id,
                )
            return {
                "applied": outcome["applied"],
                "errors": [error.to_dict() for error in outcome["errors"]],
                "revision": updated.revision,
            }

    @server.tool()
    async def validate_draft(ctx: Context) -> dict[str, Any]:
        """The same whole-proposal check as ``POST /api/proposals/:id/validate`` (Story 3.1)."""
        async with _authorize(ctx) as authorized:
            if isinstance(authorized, dict):
                return authorized
            proposal, _claims = authorized
            schema = load_schema(proposal.schema_version)
            errors = await validate_proposal(schema, proposal, catalogue)
            return {"errors": [error.to_dict() for error in errors]}

    @server.tool()
    async def get_products(ctx: Context) -> dict[str, Any]:
        """The priced-and-eligible products for this turn's proposal, same fields as
        ``GET /api/products?proposal_id=`` (Story 2.3), age at the proposal's ``created_at``."""
        async with _authorize(ctx) as authorized:
            if isinstance(authorized, dict):
                return authorized
            proposal, _claims = authorized
            date_of_birth = _date_of_birth(proposal.answers.get("C2", {}).get("value"))
            age = (
                age_at(date_of_birth, proposal.created_at)
                if date_of_birth is not None
                else None
            )
            priced = await priced_products(catalogue, age)
            return {"products": [_priced_product_dict(product) for product in priced]}

    @server.tool()
    async def find_customer(
        first_name: str | None = None,
        last_name: str | None = None,
        date_of_birth: str | None = None,
        customer_number: str | None = None,
        *,
        ctx: Context,
    ) -> dict[str, Any]:
        """At most 5 returning-customer candidates, searched across every stored customer
        regardless of who created it (Story 5.1, FORM-218/CAP-10, AD-3, AD-13). Each match carries
        exactly ``customer_id``, ``first_name``, ``last_name``, ``date_of_birth``, ``city`` and
        ``customer_number`` -- no other ``customer`` column.

        Give either ``customer_number`` alone (its own check digit means a mistyped one always
        matches nothing, never the wrong customer), or any non-empty subset of ``first_name``,
        ``last_name`` and ``date_of_birth`` -- a first name and a birth year and month alone are
        enough when they resolve to one customer; several matches means asking the insurance agent
        for the last name or the day and calling this again. ``date_of_birth`` is ``YYYY``,
        ``YYYY-MM`` or ``YYYY-MM-DD``, whichever the insurance agent's own words narrow it to
        (never ask her for a format); a value in none of those shapes matches nothing, the same as
        one that matches no seeded row. Giving nothing at all also matches nothing -- this never
        scans every customer with no filter."""
        async with _authorize(ctx) as authorized:
            if isinstance(authorized, dict):
                return authorized
            _proposal, _claims = authorized
            parsed_partial_dob = (
                parse_partial_date(date_of_birth) if date_of_birth is not None else None
            )
            if date_of_birth is not None and parsed_partial_dob is None:
                return {"matches": []}
            matches = await find_customers(
                customer_store,
                customer_number=customer_number,
                first_name=first_name,
                last_name=last_name,
                date_of_birth=parsed_partial_dob,
            )
            return {
                "matches": [
                    {
                        "customer_id": str(match.customer_id),
                        "first_name": match.first_name,
                        "last_name": match.last_name,
                        "date_of_birth": match.date_of_birth.isoformat(),
                        "city": match.city,
                        "customer_number": match.customer_number,
                    }
                    for match in matches
                ]
            }

    @server.tool()
    async def link_customer(customer_id: str, ctx: Context) -> dict[str, Any]:
        """Link this proposal to an existing customer and copy their C1-C15 particulars in one
        domain transaction (Story 5.2, AD-3, AD-13, AD-15): every ``x-fill: db`` answer is set at
        ``source: db``, skipping any already ``source: human``. Returns
        ``{"customer_id", "applied": [qid...], "skipped": [qid...], "revision"}`` on success, or
        the AD-12 error body -- ``invalid_value`` on field ``customer_id`` for an unknown or
        malformed id, ``proposal_submitted``, or ``lock_not_held`` (a stale/rejected turn,
        security.md rule 36)."""
        async with _authorize(ctx) as authorized:
            if isinstance(authorized, dict):
                return authorized
            proposal, claims = authorized
            try:
                customer_uuid = UUID(customer_id)
            except ValueError:
                return DomainError.single(
                    "customer_id", ErrorCode.INVALID_VALUE, _MALFORMED_CUSTOMER_ID_MESSAGE
                ).to_dict()
            schema = load_schema(proposal.schema_version)
            columns = db_columns(schema)
            outcome: dict[str, Any] = {}

            def apply(current: Proposal, customer_row: Mapping[str, Any] | None) -> Proposal:
                updated, skipped = link_customer_rule(
                    schema, current, customer_uuid, customer_row, clock, claims, columns
                )
                outcome["skipped"] = skipped
                return updated

            try:
                updated = await store.link_customer(proposal.id, customer_uuid, apply)
            except DomainError as exc:
                return _rejected(exc)
            if updated is None:  # pragma: no cover -- the row existed a moment ago (resolve_turn)
                return _rejected(TurnTokenError("This turn's proposal no longer exists."))
            skipped = outcome["skipped"]
            applied = [
                column.question_id for column in columns if column.question_id not in skipped
            ]
            if applied:
                # Story 5.2, AD-9: an AI write, logged the same condition style as patch_draft --
                # only when something was actually linked/copied.
                log_ai_write(
                    proposal_id=updated.id,
                    turn_id=claims.tid,
                    conversation_id=updated.conversation_id,
                )
            return {
                "customer_id": str(updated.customer_id),
                "applied": applied,
                "skipped": skipped,
                "revision": updated.revision,
            }

    mcp_app = server.streamable_http_app(
        stateless_http=True,
        streamable_http_path=MCP_PATH,
        # The turn token is the real boundary, checked on every call regardless of Host/Origin; a
        # default-mismatched allowlist (see this module's docstring) must never 421 a legitimate one.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    return server, mcp_app
