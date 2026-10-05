"""Turn-start, turn-end and AI-write log lines (Story 4.5, AD-9, Observability, security.md rule
38): the AC15 App Insights alert fires on exactly these -- a write whose ``proposal_id`` differs
from its turn's own, or a write carrying an unknown or already-ended ``turn_id``. Shared by
``adapters.chat.turns`` (turn start/end) and both the real ``/mcp`` ``patch_draft`` tool
(``adapters.mcp.server``) and the test stub's own scripted patch step (``adapters.chat.stub``), so
every AI write is logged identically wherever it happens (AD-18: the stub reuses this exact seam
rather than re-deriving it).

Every log line carries ``event`` plus ``proposal_id``/``turn_id``/``conversation_id`` as top-level
JSON fields (``adapters.logging_setup.JsonFormatter``); Container Apps ships stdout to the same Log
Analytics workspace the alert's KQL query reads (``ContainerAppConsoleLogs``), so no separate
export is needed. None of these names are redacted (``proposal_id``/``turn_id``/``conversation_id``
aren't schema question ids and don't match a sensitive-key pattern); the message text itself never
carries an answer value.
"""

import logging
from uuid import UUID

logger = logging.getLogger("formapp.chat")


def _fields(
    proposal_id: object, turn_id: object, conversation_id: str | None
) -> dict[str, object]:
    return {
        "proposal_id": str(proposal_id),
        "turn_id": str(turn_id) if turn_id is not None else None,
        "conversation_id": conversation_id,
    }


def log_turn_start(
    *, proposal_id: object, turn_id: UUID, conversation_id: str | None
) -> None:
    """One turn begins (AC1, AC14): logged the moment the lock has moved to ``ai`` and
    ``current_turn_id`` is bound, before the gateway is ever called."""
    logger.info(
        "chat turn started",
        extra={"event": "turn_start", **_fields(proposal_id, turn_id, conversation_id)},
    )


def log_turn_end(
    *, proposal_id: object, turn_id: object, conversation_id: str | None
) -> None:
    """One turn ends (AC1, AC14): logged once, whether the stream finished cleanly or failed."""
    logger.info(
        "chat turn ended",
        extra={"event": "turn_end", **_fields(proposal_id, turn_id, conversation_id)},
    )


def log_ai_write(
    *, proposal_id: object, turn_id: UUID, conversation_id: str | None
) -> None:
    """One ``patch_draft`` call actually changed at least one field (AC14): ``proposal_id`` is
    always the row the write actually landed on, never the token's own claimed ``pid`` (security.md
    rule 38 -- the two agree by construction here, since a rejected/cross-proposal attempt never
    reaches this call at all, but the alert still checks for it independently)."""
    logger.info(
        "ai write applied",
        extra={"event": "ai_write", **_fields(proposal_id, turn_id, conversation_id)},
    )
