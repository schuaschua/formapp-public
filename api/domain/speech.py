"""The ``SpeechTokenIssuer`` seam (Story 6.1, spine AD-18, AD-19): every mint of a browser Speech
token goes through this one interface. A production issuer (``adapters.speech.azure.AzureSpeechTokenIssuer``)
and a test issuer (``adapters.speech.stub.StubSpeechTokenIssuer``) are otherwise indistinguishable to
``adapters.rest.speech``, mirroring ``domain.clock.Clock`` and ``adapters.chat.gateway.AgentGateway``.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SpeechToken:
    """A minted Speech authorization token (AD-19): the ``aad#<resourceId>#<entraToken>`` form the
    Speech SDK accepts, with the metadata ``GET /api/speech/token`` returns alongside it."""

    token: str
    region: str
    endpoint: str
    voice: str
    # FORM-230: the recognition locale (`en-SG`, api settings via Terraform, AD-19) -- `web/`
    # never hard-codes it.
    locale: str
    expires_at: datetime


class SpeechUnavailableError(Exception):
    """Speech, or the credential used to reach it, failed to produce a token (AD-12
    ``speech_unavailable``, 503); the caller never sees the underlying Azure exception."""


class SpeechTokenIssuer(Protocol):
    """One seam to Speech token minting (AD-18, AD-19): nothing here ever sees a proposal id or a
    turn token -- the caller (``GET /api/speech/token``) only requires a signed-in principal."""

    async def token(self) -> SpeechToken:
        """The current Speech token, minting and caching a fresh one when needed. Raises
        :class:`SpeechUnavailableError` when Speech or its credential fails."""
        ...
