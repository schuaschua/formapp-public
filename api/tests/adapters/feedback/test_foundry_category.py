"""Story 7.2/FORM-238: ``FoundryCategoryPort`` -- unit tests only, with a fake ``client``/
``credential`` injected (spine AD-18: never a real Foundry/Azure call). Proves the request shape
(no tools, temperature 0, the rating/comment in the input) and the response mapping (the model's
raw text, a failed response becomes ``CategoryPortError``), not the real ``openai`` SDK's own
behaviour.
"""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from adapters.feedback.foundry import FOUNDRY_SCOPE, FoundryCategoryPort
from jobs.ports import CategoryPortError


class _FakeResponses:
    def __init__(self, response: Any, calls: list[dict[str, Any]]) -> None:
        self._response = response
        self._calls = calls

    async def create(self, **kwargs: Any) -> Any:
        self._calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, response: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses = _FakeResponses(response, self.calls)


class _FakeCredential:
    def __init__(self, token: str = "synthetic-entra-token") -> None:
        self.requested_scopes: list[tuple[str, ...]] = []
        self._token = token

    async def get_token(self, *scopes: str) -> Any:
        self.requested_scopes.append(scopes)
        return SimpleNamespace(token=self._token)


def _port(
    client: Any, credential: _FakeCredential | None = None
) -> FoundryCategoryPort:
    return FoundryCategoryPort(
        project_endpoint="https://synthetic-foundry.example.test/api/projects/formapp",
        agent_name="formapp-agent",
        model="synthetic-model",
        credential=credential or _FakeCredential(),
        client=client,
    )


def test_categorise_returns_the_models_output_text() -> None:
    client = _FakeClient(SimpleNamespace(output_text="Praise", status="completed"))
    port = _port(client)

    answer = asyncio.run(port.categorise(rating=5, comment="Great tool!"))

    assert answer == "Praise"


def test_categorise_calls_with_no_tools_and_temperature_zero() -> None:
    client = _FakeClient(SimpleNamespace(output_text="Speed", status="completed"))
    port = _port(client)

    asyncio.run(port.categorise(rating=2, comment="Too slow"))

    [call] = client.calls
    assert call["tools"] == []
    assert call["temperature"] == 0
    assert call["model"] == "synthetic-model"
    assert "Too slow" in call["input"]
    assert "2" in call["input"]


def test_categorise_raises_category_port_error_on_a_failed_status() -> None:
    client = _FakeClient(SimpleNamespace(output_text="", status="failed"))
    port = _port(client)

    with pytest.raises(CategoryPortError):
        asyncio.run(port.categorise(rating=1, comment="synthetic"))


def test_categorise_raises_category_port_error_on_any_sdk_failure() -> None:
    class _BrokenResponses:
        async def create(self, **_: Any) -> Any:
            raise RuntimeError("synthetic network failure")

    client = SimpleNamespace(responses=_BrokenResponses())
    port = _port(client)

    with pytest.raises(CategoryPortError):
        asyncio.run(port.categorise(rating=1, comment="synthetic"))


def test_token_requests_the_foundry_scope() -> None:
    credential = _FakeCredential()
    client = _FakeClient(SimpleNamespace(output_text="Other", status="completed"))
    port = _port(client, credential)

    asyncio.run(port.categorise(rating=3, comment="synthetic"))
    # Force the api_key callable (the token provider) to run once, the way the real SDK would when
    # it needs a fresh bearer token for a request.
    asyncio.run(port._token())  # noqa: SLF001 -- exercising the constructor-injected seam directly

    assert credential.requested_scopes == [(FOUNDRY_SCOPE,)]


def test_demo_mode_builds_the_real_managed_identity_credential() -> None:
    """Outage-lesson regression (mirrors adapters.chat.test_foundry's own 2026-09-27 regression
    test): the production job entrypoint builds the real async ManagedIdentityCredential without
    making a call, so an import/constructor-level break shows up here, not at 02:00 in demo."""
    from azure.identity.aio import ManagedIdentityCredential

    from jobs.feedback import _default_category_port
    from jobs.settings import JobSettings

    settings = JobSettings(
        formapp_deployment="local",
        database_host="synthetic-host",
        database_name="synthetic-db",
        database_user="synthetic-user",
        azure_client_id="00000000-1111-2222-3333-444444444444",
        foundry_project_endpoint="https://synthetic-foundry.example.test/api/projects/formapp",
        foundry_agent_name="formapp-agent",
        foundry_model="synthetic-model",
    )

    port = _default_category_port(settings)

    assert isinstance(port, FoundryCategoryPort)
    assert isinstance(port._credential, ManagedIdentityCredential)  # noqa: SLF001
    asyncio.run(port._credential.close())  # noqa: SLF001
