"""The test-only ``SpeechTokenIssuer`` (Story 6.1, AD-18): a fixed synthetic token, driven by the
injectable ``Clock``, with an optional scripted failure -- never a real Azure call.

``create_app`` builds one of these automatically whenever ``FORMAPP_TEST_MODE`` is on and no
``speech_token_issuer`` is given (mirrors ``adapters.chat.stub.StubAgentGateway``).
"""

from datetime import timedelta

from domain.clock import Clock
from domain.speech import SpeechToken, SpeechUnavailableError

# Synthetic defaults (security.md rule 1): a plausible resource id shape, never a real one.
_SYNTHETIC_RESOURCE_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/"
    "rg-sample-demo-sea/providers/Microsoft.CognitiveServices/accounts/cog-sample-demo-sea"
)


class StubSpeechTokenIssuer:
    """Scripted, in-process ``SpeechTokenIssuer`` (AD-18): see this module's docstring."""

    def __init__(
        self,
        *,
        clock: Clock,
        region: str = "southeastasia",
        endpoint: str = "https://cog-sample-demo-sea.cognitiveservices.azure.com",
        resource_id: str = _SYNTHETIC_RESOURCE_ID,
        voice: str = "en-SG-LunaNeural",
        locale: str = "en-SG",
        lifetime: timedelta = timedelta(minutes=10),
        fail: bool = False,
    ) -> None:
        self._clock = clock
        self._region = region
        self._endpoint = endpoint
        self._resource_id = resource_id
        self._voice = voice
        self._locale = locale
        self._lifetime = lifetime
        # A test flips this to make the next (and every later) call fail, without rebuilding the
        # issuer (mirrors adapters.chat.stub's FailStep, minus needing a whole script for one flag).
        self.fail = fail
        self.calls = 0

    async def token(self) -> SpeechToken:
        self.calls += 1
        if self.fail:
            raise SpeechUnavailableError("Speech is unavailable (test double).")
        return SpeechToken(
            token=f"aad#{self._resource_id}#synthetic-entra-token-{self.calls}",
            region=self._region,
            endpoint=self._endpoint,
            voice=self._voice,
            locale=self._locale,
            expires_at=self._clock.now() + self._lifetime,
        )
