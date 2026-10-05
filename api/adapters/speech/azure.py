"""The production ``SpeechTokenIssuer`` (Story 6.1, spine AD-18, AD-19): mints a Speech
authorization token as the dedicated speech managed identity (never api's own identity), and caches
it in-process until 2 minutes before it expires.

Never exercised against real Azure in any test (no test may call Azure, spine AD-18, and the
2026-09-27 outage lesson): the unit tests here construct this class directly with a fake
credential, exactly the seam this class exposes for that purpose.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from domain.clock import Clock
from domain.speech import SpeechToken, SpeechUnavailableError

# The token audience Speech's STS accepts for the aad# authorization-token form (Microsoft Learn,
# "Use the Speech resource with Microsoft Entra ID").
SPEECH_SCOPE = "https://cognitiveservices.azure.com/.default"

# Serve the cached token until this long before it actually expires (spec Boundaries): a caller
# mid-request never races a token that expires under it.
_EARLY_REFRESH = timedelta(minutes=2)


class _TokenCredential(Protocol):
    async def get_token(self, *scopes: str) -> Any: ...


class AzureSpeechTokenIssuer:
    """See this module's docstring. ``credential`` is a constructor seam for tests (spine AD-18);
    production code (``adapters.rest.app``) leaves it at its default."""

    def __init__(
        self,
        *,
        region: str,
        endpoint: str,
        resource_id: str,
        client_id: str,
        voice: str,
        locale: str,
        clock: Clock,
        credential: _TokenCredential | None = None,
    ) -> None:
        self._region = region
        self._endpoint = endpoint
        self._resource_id = resource_id
        self._client_id = client_id
        self._voice = voice
        self._locale = locale
        self._clock = clock
        # Built lazily in token() when not given: azure-identity's async transport needs aiohttp,
        # and a test-mode process never has to construct a real Azure credential (AD-18, mirrors
        # adapters.chat.foundry.FoundryAgentGateway._token).
        self._credential = credential
        self._cached: SpeechToken | None = None

    def _default_credential(self) -> _TokenCredential:
        from azure.identity.aio import ManagedIdentityCredential

        return ManagedIdentityCredential(client_id=self._client_id)

    async def token(self) -> SpeechToken:
        cached = self._cached
        if (
            cached is not None
            and self._clock.now() < cached.expires_at - _EARLY_REFRESH
        ):
            return cached
        if self._credential is None:
            self._credential = self._default_credential()
        try:
            access_token = await self._credential.get_token(SPEECH_SCOPE)
        except Exception as exc:  # any SDK/network failure means Speech is unavailable
            raise SpeechUnavailableError("Speech token request failed.") from exc
        speech_token = SpeechToken(
            token=f"aad#{self._resource_id}#{access_token.token}",
            region=self._region,
            endpoint=self._endpoint,
            voice=self._voice,
            locale=self._locale,
            expires_at=datetime.fromtimestamp(access_token.expires_on, tz=UTC),
        )
        self._cached = speech_token
        return speech_token
