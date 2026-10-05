"""Story 4.2: the entry point builds the Foundry-backed host from settings, or stops on bad ones."""

import json
import logging

import httpx
import pytest
from agent_framework.observability import OBSERVABILITY_SETTINGS, enable_instrumentation
from agent_framework_foundry import FoundryChatClient
from opentelemetry.sdk.trace import TracerProvider

from formapp_agent import main as entry
from formapp_agent import telemetry
from formapp_agent.host import FormappResponsesHost
from tests.conftest import make_settings
from tests.test_settings import VALID_ENV

pytestmark = pytest.mark.anyio


async def test_story_4_2_create_app_uses_model_deployment_name_from_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda _p: None)
    monkeypatch.setattr(telemetry, "_provider_set", False)

    app = entry.create_app(
        make_settings(model_deployment_name="synthetic-deployment-name")
    )

    (agent_client,) = [app._agent.client]  # type: ignore[attr-defined]
    assert isinstance(agent_client, FoundryChatClient)
    assert agent_client.model == "synthetic-deployment-name"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://agent.test"
    ) as client:
        assert (await client.get("/readiness")).status_code == 200


def test_story_4_2_main_stops_on_missing_setting(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in VALID_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MODEL_DEPLOYMENT_NAME", "synthetic-deployment-name")

    assert entry.main() == 2

    err = capsys.readouterr().err
    assert "FORMAPP_MCP_URL is required but not set" in err
    assert "synthetic-deployment-name" not in err


def test_story_4_2_main_runs_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in VALID_ENV.items():
        monkeypatch.setenv(name, value)
    started: list[FormappResponsesHost] = []
    monkeypatch.setattr(FormappResponsesHost, "run", lambda self: started.append(self))
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda _p: None)
    monkeypatch.setattr(telemetry, "_provider_set", False)

    assert entry.main() == 0
    assert len(started) == 1


def test_story_4_2_create_app_configures_redacted_logging_and_no_message_capture(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    installed: list[object] = []
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", installed.append)
    monkeypatch.setattr(telemetry, "_provider_set", False)
    enable_instrumentation(enable_sensitive_data=True)

    entry.create_app(make_settings())

    assert not OBSERVABILITY_SETTINGS.SENSITIVE_DATA_ENABLED
    (provider,) = installed
    assert isinstance(provider, TracerProvider)
    assert provider.sampler.get_description().startswith("ParentBased")
    capsys.readouterr()
    logging.getLogger("formapp_agent.test").info(
        "sent Bearer %s", "synthetic-bearer-value"
    )
    (line,) = capsys.readouterr().out.splitlines()
    record = json.loads(line)
    assert record["message"] == "sent Bearer [REDACTED]"
