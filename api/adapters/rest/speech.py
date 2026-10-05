"""``GET /api/speech/token`` (Story 6.1, spine AD-18, AD-19): mints a browser Speech token through
the ``SpeechTokenIssuer`` seam, for the dedicated speech identity (never api's own). Sign-in is
enforced by the ``/api/*`` middleware (Story 1.6); unlike a proposal route, this needs no ownership
check -- a Speech token isn't proposal- or agent-scoped, only Entra-signed-in-gated.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from adapters.rest.principal import current_principal
from domain.errors import DomainError, ErrorCode
from domain.principal import Principal
from domain.speech import SpeechUnavailableError

router = APIRouter()

# Every minted token authenticates Speech with Entra (AD-19); there is no other auth_mode to pick.
AUTH_MODE = "aad"


def _iso(moment: datetime) -> str:
    """ISO 8601 UTC, ``Z``-suffixed (coding-style.md rule 5, mirrors domain.proposals._iso)."""
    return moment.isoformat().replace("+00:00", "Z")


@router.get("/api/speech/token")
async def get_speech_token(
    request: Request,
    # Depends on current_principal only to require sign-in (AD-4, AD-8); a Speech token carries no
    # per-agent data, so the principal itself is otherwise unused here.
    _principal: Annotated[Principal, Depends(current_principal)],
) -> JSONResponse:
    """A cached-or-freshly-minted Speech token; AD-12 ``speech_unavailable`` (503) when Speech or
    its credential fails (spec I/O matrix). FORM-230: includes ``locale`` (api settings via
    Terraform, `en-SG`), so `web/`'s recognition language is never hard-coded (AD-19)."""
    try:
        token = await request.app.state.speech_token_issuer.token()
    except SpeechUnavailableError as exc:
        raise DomainError.single(
            "speech",
            ErrorCode.SPEECH_UNAVAILABLE,
            "Speech is unavailable right now. Try again shortly.",
        ) from exc
    return JSONResponse(
        {
            "token": token.token,
            "auth_mode": AUTH_MODE,
            "region": token.region,
            "endpoint": token.endpoint,
            "voice": token.voice,
            "locale": token.locale,
            "expires_at": _iso(token.expires_at),
        },
        # A fresh mint each time it's genuinely needed, never cached by the browser (mirrors
        # adapters.rest.me's personal-to-the-caller Cache-Control).
        headers={"Cache-Control": "no-store"},
    )
