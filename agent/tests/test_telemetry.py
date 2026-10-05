"""Story 4.2: sampled traces, the exporter only when configured, and message capture always off."""

import logging

import httpx
import pytest
from agent_framework.observability import OBSERVABILITY_SETTINGS
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from evals.scripted_client import ScriptedChatClient
from formapp_agent import telemetry
from formapp_agent.host import build_app
from tests.conftest import make_settings
from tests.test_settings import CONNECTION_STRING

pytestmark = pytest.mark.anyio


def _processors(provider: TracerProvider) -> list[object]:
    return list(provider._active_span_processor._span_processors)


def test_story_4_2_sampling_is_parent_based_ratio() -> None:
    provider = telemetry.build_tracer_provider(
        make_settings(telemetry_sampling_ratio=0.25)
    )

    description = provider.sampler.get_description()
    assert description.startswith("ParentBased")
    assert "TraceIdRatioBased{0.25}" in description
    provider.shutdown()


def test_story_4_2_telemetry_off_exports_nothing() -> None:
    provider = telemetry.build_tracer_provider(make_settings())

    assert _processors(provider) == []
    provider.shutdown()


def test_story_4_2_exporter_only_with_connection_string() -> None:
    from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

    provider = telemetry.build_tracer_provider(
        make_settings(applicationinsights_connection_string=CONNECTION_STRING)
    )

    (processor,) = _processors(provider)
    assert isinstance(processor, BatchSpanProcessor)
    assert isinstance(processor._batch_processor._exporter, AzureMonitorTraceExporter)
    provider.shutdown()


def test_story_4_2_message_capture_forced_off(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    installed: list[object] = []
    monkeypatch.setattr(telemetry, "_provider_set", False)
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", installed.append)
    configure = telemetry.observability_setup(make_settings())

    # The host asks for sensitive data whenever its environment variable isn't "false".
    configure(connection_string=None, log_level="INFO", enable_sensitive_data=True)
    configure(connection_string=None, log_level="INFO", enable_sensitive_data=True)

    assert OBSERVABILITY_SETTINGS.ENABLED
    assert not OBSERVABILITY_SETTINGS.SENSITIVE_DATA_ENABLED
    assert len(installed) == 1
    assert isinstance(installed[0], TracerProvider)
    logging.getLogger("formapp_agent.test").info("json line")
    assert '"message": "json line"' in capsys.readouterr().out


def _non_resilience_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
        # The hosting package's own startup noise (crash-recovery and experimental-API notices);
        # none of it is about telemetry, and it appears on every start regardless of settings.
        and not record.name.startswith("azure.ai.agentserver")
    ]


async def test_story_4_2_missing_connection_string_warns_once_at_startup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda _p: None)
    monkeypatch.setattr(telemetry, "_provider_set", False)
    settings = make_settings()

    with caplog.at_level(logging.WARNING):
        app = build_app(
            settings,
            ScriptedChatClient(),
            configure_observability=telemetry.observability_setup(settings),
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://agent.test"
        ) as client:
            response = await client.get("/readiness")

    assert response.status_code == 200
    # Named, never valued (NFR17): there is no connection string to quote.
    assert _non_resilience_warnings(caplog) == [
        "APPLICATIONINSIGHTS_CONNECTION_STRING is not set; telemetry export is off"
    ]


def test_story_4_2_configured_connection_string_does_not_warn(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda _p: None)
    monkeypatch.setattr(telemetry, "_provider_set", False)
    configure = telemetry.observability_setup(
        make_settings(applicationinsights_connection_string=CONNECTION_STRING)
    )

    with caplog.at_level(logging.WARNING):
        configure(connection_string=None, log_level="INFO", enable_sensitive_data=False)

    # Building the real exporter with a synthetic (non-Azure) endpoint logs its own unrelated
    # statsbeat notice; only the telemetry-off warning is this test's concern.
    assert not any(
        "APPLICATIONINSIGHTS_CONNECTION_STRING" in message
        for message in _non_resilience_warnings(caplog)
    )
