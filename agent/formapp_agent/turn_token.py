"""The current turn's token, and the MCP header built from it (spine AD-4, security.md rule 7).

The token arrives in the ``x-client-turn-token`` request header and leaves only as the MCP
``Authorization: Bearer`` header. It is held in a ``ContextVar`` for the length of one turn, so it
never enters the agent's run arguments, messages, metadata or prompts, and each turn sees only its
own token. The header provider ignores the run arguments it is given for the same reason.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

# The Responses host passes only x-client-* headers, with lower-case names.
CLIENT_TURN_HEADER = "x-client-turn-token"

_current_turn_token: ContextVar[str | None] = ContextVar(
    "formapp_turn_token", default=None
)


def token_from_headers(client_headers: Mapping[str, str] | None) -> str | None:
    """The turn token from the request's client headers, or None when it is missing or blank."""
    if not client_headers:
        return None
    value = client_headers.get(CLIENT_TURN_HEADER)
    if value is None:
        return None
    value = value.strip()
    return value or None


@contextmanager
def turn_token_scope(token: str) -> Iterator[None]:
    """Make ``token`` the current turn's token inside this block, and clear it afterwards."""
    reset = _current_turn_token.set(token)
    try:
        yield
    finally:
        try:
            _current_turn_token.reset(reset)
        except ValueError:
            # The block was closed from another context (a response generator closed by the
            # garbage collector); clear the token there instead of leaving it behind.
            _current_turn_token.set(None)


def header_provider(_run_kwargs: Mapping[str, Any]) -> dict[str, str]:
    """The MCP request headers for the current turn: ``Authorization: Bearer <token>`` or none."""
    token = _current_turn_token.get()
    if token is None:
        return {}
    return {"Authorization": f"Bearer {token}"}
