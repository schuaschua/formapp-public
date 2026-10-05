"""Story 6.1: ``AzureSpeechTokenIssuer`` -- unit tests only, with a fake async credential injected
(spine AD-18: never a real Azure call, and the 2026-09-27 outage lesson). Proves the request shape
(the Speech scope), the ``aad#<resourceId>#<token>`` response format, in-process caching, the
2-minute early-refresh window, and that a credential failure becomes ``SpeechUnavailableError``.
"""

import asyncio
from datetime import timedelta

import pytest

from adapters.speech.azure import SPEECH_SCOPE, AzureSpeechTokenIssuer
from domain.speech import SpeechUnavailableError
from tests.fakes import FakeAccessToken, FakeClock

# A plausible resource id shape, never a real one (security.md rule 1).
RESOURCE_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/"
    "rg-sample-demo-sea/providers/Microsoft.CognitiveServices/accounts/cog-sample-demo-sea"
)
CLIENT_ID = "00000000-1111-2222-3333-444444444444"


class _FakeCredential:
    """Async stand-in for ManagedIdentityCredential (mirrors
    ``adapters.chat.test_foundry._FakeCredential``, plus ``expires_on`` for the caching/refresh
    assertions here); never reaches Azure."""

    def __init__(
        self, clock: FakeClock, lifetime: timedelta = timedelta(hours=1)
    ) -> None:
        self._clock = clock
        self._lifetime = lifetime
        self.requested_scopes: list[tuple[str, ...]] = []
        self.calls = 0
        self.fail = False

    async def get_token(self, *scopes: str) -> FakeAccessToken:
        self.requested_scopes.append(scopes)
        if self.fail:
            raise RuntimeError("synthetic credential failure")
        self.calls += 1
        expires = self._clock.now() + self._lifetime
        return FakeAccessToken(
            token=f"synthetic-entra-token-{self.calls}",
            expires_on=int(expires.timestamp()),
        )


def _issuer(clock: FakeClock, credential: _FakeCredential) -> AzureSpeechTokenIssuer:
    return AzureSpeechTokenIssuer(
        region="southeastasia",
        endpoint="https://cog-sample-demo-sea.cognitiveservices.azure.com",
        resource_id=RESOURCE_ID,
        client_id=CLIENT_ID,
        voice="en-SG-LunaNeural",
        locale="en-SG",
        clock=clock,
        credential=credential,
    )


def test_story_6_1_token_has_the_aad_authorization_format() -> None:
    clock = FakeClock()
    issuer = _issuer(clock, _FakeCredential(clock))

    token = asyncio.run(issuer.token())

    assert token.token == f"aad#{RESOURCE_ID}#synthetic-entra-token-1"
    assert token.region == "southeastasia"
    assert token.endpoint == "https://cog-sample-demo-sea.cognitiveservices.azure.com"
    assert token.voice == "en-SG-LunaNeural"
    assert token.locale == "en-SG"


def test_story_6_1_the_token_provider_requests_the_speech_scope() -> None:
    clock = FakeClock()
    credential = _FakeCredential(clock)
    issuer = _issuer(clock, credential)

    asyncio.run(issuer.token())

    assert credential.requested_scopes == [(SPEECH_SCOPE,)]


def test_story_6_1_a_fresh_token_is_cached_and_the_credential_is_not_called_again() -> (
    None
):
    clock = FakeClock()
    credential = _FakeCredential(clock, lifetime=timedelta(hours=1))
    issuer = _issuer(clock, credential)

    first = asyncio.run(issuer.token())
    clock.advance(timedelta(minutes=5))
    second = asyncio.run(issuer.token())

    assert second is first
    assert credential.calls == 1


def test_story_6_1_a_token_within_2_minutes_of_expiry_is_refreshed() -> None:
    clock = FakeClock()
    credential = _FakeCredential(clock, lifetime=timedelta(minutes=10))
    issuer = _issuer(clock, credential)

    first = asyncio.run(issuer.token())
    # 1 second inside the 2-minute early-refresh window (10 - 2 = 8 minutes from the first mint).
    clock.advance(timedelta(minutes=8, seconds=1))
    second = asyncio.run(issuer.token())

    assert credential.calls == 2
    assert second.token != first.token


def test_story_6_1_a_token_just_outside_the_refresh_window_is_still_cached() -> None:
    clock = FakeClock()
    credential = _FakeCredential(clock, lifetime=timedelta(minutes=10))
    issuer = _issuer(clock, credential)

    asyncio.run(issuer.token())
    # 1 second before the 2-minute early-refresh window starts.
    clock.advance(timedelta(minutes=7, seconds=59))
    asyncio.run(issuer.token())

    assert credential.calls == 1


def test_story_6_1_a_credential_failure_raises_speech_unavailable() -> None:
    clock = FakeClock()
    credential = _FakeCredential(clock)
    credential.fail = True
    issuer = _issuer(clock, credential)

    with pytest.raises(SpeechUnavailableError):
        asyncio.run(issuer.token())


def test_story_6_1_no_credential_given_defers_building_one_until_the_first_token_request() -> (
    None
):
    """Mirrors ``adapters.chat.test_foundry``'s regression: construction alone must never build a
    real credential (spine AD-18), so a plain ``create_app()`` in test mode never touches
    azure-identity."""
    issuer = AzureSpeechTokenIssuer(
        region="southeastasia",
        endpoint="https://cog-sample-demo-sea.cognitiveservices.azure.com",
        resource_id=RESOURCE_ID,
        client_id=CLIENT_ID,
        voice="en-SG-LunaNeural",
        locale="en-SG",
        clock=FakeClock(),
    )

    assert issuer._credential is None  # proving the deferred-build seam directly


def test_story_6_1_demo_mode_builds_the_real_managed_identity_credential() -> None:
    """Regression, mirrors adapters.chat.test_foundry's own: outside test mode create_app() must
    build the real async ManagedIdentityCredential at startup (needs aiohttp), never defer it, so a
    misconfigured demo process fails fast rather than crashing on the first request."""
    from azure.identity.aio import ManagedIdentityCredential

    from adapters.clock import SystemClock
    from adapters.rest.app import _default_speech_token_issuer
    from tests.support import make_settings

    settings = make_settings(
        database_port=1,
        formapp_test_mode=False,
        azure_client_id=CLIENT_ID,
        foundry_project_endpoint="https://synthetic-foundry.example.test/api/projects/formapp",
        foundry_agent_name="formapp-agent",
        foundry_model="synthetic-model",
        speech_region="southeastasia",
        speech_endpoint="https://cog-sample-demo-sea.cognitiveservices.azure.com",
        speech_resource_id=RESOURCE_ID,
        speech_identity_client_id=CLIENT_ID,
        speech_locale="en-SG",
        speech_voice="en-SG-LunaNeural",
    )

    issuer = _default_speech_token_issuer(settings, SystemClock())

    assert isinstance(issuer, AzureSpeechTokenIssuer)
    assert isinstance(issuer._credential, ManagedIdentityCredential)
    asyncio.run(issuer._credential.close())
