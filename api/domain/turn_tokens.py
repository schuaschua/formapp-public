"""Turn tokens: the short-lived, per-turn JWT that authorizes an MCP call (Story 4.3, spine AD-4).

A turn token is minted once, by :func:`issue_turn_token`, for one proposal and one turn -- it
carries the owning agent's oid (``sub``), the bound proposal (``pid``) and a fresh turn id
(``tid``), and expires at most ten minutes after it is minted. Every ``/mcp`` call carries it as
``Authorization: Bearer <token>`` (security.md rule 6) and :func:`resolve_turn` is the one place
that turns it back into the proposal it names, refusing unless the token is still valid *and* the
proposal's turn hasn't moved on (AD-4, AD-16, security.md rule 36). The signing key never appears
in a log line or an exception message (security.md rule 7); callers must not either.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from pydantic import SecretStr

from domain.clock import Clock
from domain.errors import DomainError, ErrorCode
from domain.proposals import Proposal, ProposalStore, ensure_owned, turn_bound

_ALGORITHM = "HS256"
_REQUIRED_CLAIMS = ("sub", "pid", "tid", "exp")

# AC1: exp is at most 10 minutes after the injectable clock's now.
TURN_TOKEN_TTL = timedelta(minutes=10)

_TURN_NOT_ACTIVE_MESSAGE = "This turn is no longer active."


class TurnTokenError(Exception):
    """The bearer token is missing, malformed, badly signed, expired, or names a proposal the
    signed subject doesn't own (spine AD-4, security.md rule 6). The message never says which of
    these it was, and never quotes the token (security.md rule 7): the MCP adapter maps every
    instance to the same ``lock_not_held`` rejection (security.md rule 36)."""


@dataclass(frozen=True, slots=True)
class TurnTokenClaims:
    """One decoded turn token's claims (Story 4.3, AD-4).

    ``sub`` is the owning agent's Entra oid, ``pid`` the proposal it is bound to, ``tid`` the fresh
    UUIDv4 minted for this one turn, ``exp`` when it stops being valid.
    """

    sub: str
    pid: UUID
    tid: UUID
    exp: datetime


async def issue_turn_token(
    store: ProposalStore,
    proposal_id: UUID,
    principal_oid: str,
    clock: Clock,
    signing_key: SecretStr,
) -> str:
    """Mint a turn token for ``principal_oid``'s own proposal (Story 4.3, AD-4, AC1).

    Raises ``ProposalNotFoundError`` (via :func:`domain.proposals.ensure_owned`) unless she owns
    it -- only an owner ever gets a token naming her proposal. ``exp`` is exactly
    :data:`TURN_TOKEN_TTL` after the injectable clock's now (AD-18); ``tid`` is a fresh UUIDv4,
    minted here and nowhere else -- this is the one place a turn is born.
    """
    await ensure_owned(store, proposal_id, principal_oid)
    now = clock.now()
    payload = {
        "sub": principal_oid,
        "pid": str(proposal_id),
        "tid": str(uuid4()),
        "exp": now + TURN_TOKEN_TTL,
    }
    return jwt.encode(payload, signing_key.get_secret_value(), algorithm=_ALGORITHM)


def decode_turn_token(token: str, signing_key: SecretStr, clock: Clock) -> TurnTokenClaims:
    """Verify and decode a turn token (Story 4.3, AD-4).

    Raises ``TurnTokenError`` for anything that isn't a validly signed, complete token in this
    exact shape. Expiry is checked against the injectable clock (AD-18), never the wall clock, so
    PyJWT's own ``exp`` check is disabled and done here instead with ``clock.now()``.
    """
    try:
        payload = jwt.decode(
            token,
            signing_key.get_secret_value(),
            algorithms=[_ALGORITHM],
            options={"require": list(_REQUIRED_CLAIMS), "verify_exp": False},
            leeway=0,
        )
    except jwt.PyJWTError as exc:
        raise TurnTokenError("Invalid turn token.") from exc

    try:
        sub = payload["sub"]
        pid = UUID(str(payload["pid"]))
        tid = UUID(str(payload["tid"]))
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
    except (KeyError, ValueError, TypeError, OSError, OverflowError) as exc:
        raise TurnTokenError("Malformed turn token.") from exc
    if not isinstance(sub, str) or not sub:
        raise TurnTokenError("Malformed turn token.")
    if clock.now() >= exp:
        raise TurnTokenError("Expired turn token.")
    return TurnTokenClaims(sub=sub, pid=pid, tid=tid, exp=exp)


async def resolve_turn(
    store: ProposalStore, token: str, signing_key: SecretStr, clock: Clock
) -> Proposal:
    """Decode ``token`` and return the proposal it names, only while its turn is still live
    (Story 4.3, AD-4, AD-16, security.md rule 36).

    Raises ``TurnTokenError`` for a bad token or an owner mismatch (a tampered ``pid``, or another
    agent's own otherwise-valid token -- never revealing which, so neither leaks anything about a
    proposal she doesn't own). Once the token is otherwise valid, raises ``DomainError``
    (``lock_not_held``) if the proposal's turn has moved on: the lock isn't held by ``ai``, has
    expired, or ``current_turn_id`` no longer matches this token's ``tid`` (a stale token replayed
    after a new turn began).
    """
    claims = decode_turn_token(token, signing_key, clock)
    proposal = await store.get(claims.pid)
    if proposal is None or proposal.owner_oid != claims.sub:
        raise TurnTokenError("This token doesn't name a proposal its subject owns.")
    if not turn_bound(proposal, claims, clock.now()):
        raise DomainError.single("turn", ErrorCode.LOCK_NOT_HELD, _TURN_NOT_ACTIVE_MESSAGE)
    return proposal
