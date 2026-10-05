"""Story 1.5: OpenTelemetry through the Azure Monitor distro, on only with a connection string.

No test exports anything: the distro is replaced by a recorder, and spans go to an in-memory exporter.
"""

import logging
import warnings
from collections.abc import Iterator
from typing import Any

import pytest
from azure.identity import ManagedIdentityCredential
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.utils import is_instrumentation_enabled
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from adapters import telemetry
from adapters.db.readiness import Readiness
from adapters.logging_setup import RedactionFilter
from adapters.rest.app import create_app
from adapters.settings import Settings, SettingsError
from tests.support import AS_AGENT_A, make_settings

CONNECTION_STRING = (
    "InstrumentationKey=00000000-5157-4a11-9000-00000000c0de;"
    "IngestionEndpoint=https://synthetic-ingest.example.test/"
)


class DistroRecorder:
    """Stands in for configure_azure_monitor: records the call and, like the real distro with
    logging export on, adds a root log handler (to prove the setup order covers it)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.handler = logging.NullHandler()

    def __call__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        logging.getLogger().addHandler(self.handler)


@pytest.fixture
def fresh_telemetry(monkeypatch: pytest.MonkeyPatch) -> Iterator[DistroRecorder]:
    """Telemetry not yet configured in this process; the distro replaced by a recorder."""
    recorder = DistroRecorder()
    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr(telemetry, "_distro_configure", lambda: recorder)
    yield recorder
    logging.getLogger().removeHandler(recorder.handler)
    PsycopgInstrumentor().uninstrument()


@pytest.fixture
def spans() -> tuple[TracerProvider, InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


def _settings(**overrides: Any) -> Settings:
    return make_settings(database_port=1, **overrides)


def test_story_1_5_without_connection_string_telemetry_is_off_without_warnings(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def must_not_start() -> Any:
        raise AssertionError("the distro must not start without a connection string")

    monkeypatch.setattr(telemetry, "_distro_configure", must_not_start)

    with (
        warnings.catch_warnings(record=True) as caught,
        caplog.at_level(logging.WARNING),
    ):
        warnings.simplefilter("always")
        settings = _settings()
        with TestClient(create_app(settings)) as client:
            response = client.get("/healthz")

    assert response.status_code == 200
    assert settings.applicationinsights_connection_string is None
    assert telemetry.configure_telemetry(settings) is False
    assert [str(w.message) for w in caught] == []
    assert caplog.records == []


def test_story_1_5_blank_connection_string_means_telemetry_off() -> None:
    settings = _settings(applicationinsights_connection_string="  ")

    assert settings.applicationinsights_connection_string is None
    assert telemetry.configure_telemetry(settings) is False


def test_story_1_5_with_connection_string_the_distro_starts_once(
    fresh_telemetry: DistroRecorder,
) -> None:
    settings = _settings(
        applicationinsights_connection_string=CONNECTION_STRING,
        telemetry_sampling_ratio=0.5,
    )

    assert telemetry.configure_telemetry(settings) is True
    assert telemetry.configure_telemetry(settings) is True

    (call,) = fresh_telemetry.calls
    assert call["connection_string"] == CONNECTION_STRING
    assert call["sampling_ratio"] == 0.5
    # FastAPI is instrumented per app, with the probe exclusions, not by the distro.
    assert call["instrumentation_options"] == {"fastapi": {"enabled": False}}
    # Logs are not exported: stdout (ContainerAppConsoleLogs) is their only route.
    assert call["disable_logging"] is True
    # A fixed service name, so Application Insights shows formapp-api instead of the distro's own
    # default (unknown_service:python).
    assert call["resource"].attributes.get("service.name") == "formapp-api"
    # PostgreSQL dependency spans come from the psycopg (v3) instrumentation.
    assert PsycopgInstrumentor().is_instrumented_by_opentelemetry


def test_story_1_5_create_app_with_connection_string_turns_telemetry_on(
    fresh_telemetry: DistroRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    instrumented: list[FastAPI] = []
    monkeypatch.setattr(
        "adapters.rest.app.instrument_app", lambda app: instrumented.append(app)
    )

    app = create_app(_settings(applicationinsights_connection_string=CONNECTION_STRING))

    assert len(fresh_telemetry.calls) == 1
    assert fresh_telemetry.calls[0]["disable_logging"] is True
    assert instrumented == [app]
    # Logging is set up after the distro, so every root handler, even one the distro adds,
    # carries the redaction filter.
    root_handlers = logging.getLogger().handlers
    assert fresh_telemetry.handler in root_handlers
    assert all(
        any(isinstance(f, RedactionFilter) for f in handler.filters)
        for handler in root_handlers
    )


def test_story_1_5_distro_rejecting_the_connection_string_is_a_settings_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def rejects(**_: Any) -> None:
        raise ValueError(f"Invalid connection string {CONNECTION_STRING}")

    monkeypatch.setattr(telemetry, "_configured", False)
    monkeypatch.setattr(telemetry, "_distro_configure", lambda: rejects)
    settings = _settings(applicationinsights_connection_string=CONNECTION_STRING)

    with pytest.raises(SettingsError) as caught:
        telemetry.configure_telemetry(settings)

    assert "APPLICATIONINSIGHTS_CONNECTION_STRING" in str(caught.value)
    assert "c0de" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert telemetry._configured is False
    assert not PsycopgInstrumentor().is_instrumented_by_opentelemetry


def test_story_1_5_requests_are_traced_but_probes_are_not(
    spans: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    provider, exporter = spans
    app = create_app(_settings())
    telemetry.instrument_app(app, tracer_provider=provider)

    with TestClient(app) as client:
        client.get("/healthz")
        client.get("/readyz")  # 503 here (no database), still not traced
        client.get("/healthz?probe=1")
        client.get("/healthz/")
        client.get("/api/unknown")

    server_spans = [
        s for s in exporter.get_finished_spans() if s.kind == SpanKind.SERVER
    ]
    # The instrumentation's default (older) HTTP conventions name the path http.target.
    assert [(s.attributes or {}).get("http.target") for s in server_spans] == [
        "/api/unknown"
    ]
    # One span per request: no per-message receive/send spans (less ingestion).
    assert len(exporter.get_finished_spans()) == 1


def test_story_1_5_unhandled_exception_is_recorded_without_its_message(
    spans: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    provider, exporter = spans
    app = create_app(_settings())

    @app.get("/api/story-1-5-boom")
    async def boom() -> None:
        raise RuntimeError("answer C1=Ally must not reach telemetry")

    telemetry.instrument_app(app, tracer_provider=provider)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/story-1-5-boom", headers=AS_AGENT_A)

    assert response.status_code == 500
    (span,) = exporter.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    (event,) = [e for e in span.events if e.name == "exception"]
    assert event.attributes is not None
    assert event.attributes["exception.type"] == "builtins.RuntimeError"
    assert "Ally" not in str(dict(event.attributes))
    assert "Ally" not in str(span.status.description)


def test_story_1_5_recording_without_a_span_does_nothing() -> None:
    # Telemetry off: the current span is the no-op span, and nothing fails.
    telemetry.record_unhandled_exception(RuntimeError("synthetic"))


def test_story_1_5_readiness_runs_with_instrumentation_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[bool] = []

    async def fake_check(*_: Any) -> Readiness:
        seen.append(is_instrumentation_enabled())
        return Readiness(ready=True)

    monkeypatch.setattr("adapters.rest.health.check_readiness", fake_check)
    with TestClient(create_app(_settings())) as client:
        assert client.get("/readyz").status_code == 200

    assert seen == [False]


def test_story_1_5_sampling_ratio_defaults_to_all() -> None:
    assert _settings().telemetry_sampling_ratio == 1.0


def test_story_1_5_only_the_exact_probe_paths_are_untraced(
    spans: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    provider, exporter = spans
    app = create_app(_settings())
    telemetry.instrument_app(app, tracer_provider=provider)

    with TestClient(app) as client:
        for path in ("/api/healthz", "/healthzz", "/healthz/extra", "/x/readyz"):
            client.get(path)

    traced = [
        (s.attributes or {}).get("http.target") for s in exporter.get_finished_spans()
    ]
    assert traced == ["/api/healthz", "/healthzz", "/healthz/extra", "/x/readyz"]


def test_story_1_5_exception_after_the_response_started_is_recorded_without_its_message(
    spans: tuple[TracerProvider, InMemorySpanExporter],
) -> None:
    provider, exporter = spans
    app = create_app(_settings())

    @app.get("/api/story-1-5-stream")
    async def stream() -> StreamingResponse:
        async def chunks() -> Any:
            yield b"first chunk"
            raise RuntimeError("answer C1=Ally must not reach telemetry")

        return StreamingResponse(chunks())

    telemetry.instrument_app(app, tracer_provider=provider)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/story-1-5-stream", headers=AS_AGENT_A)

    assert response.status_code == 200
    (span,) = exporter.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    (event,) = [e for e in span.events if e.name == "exception"]
    assert event.attributes is not None
    assert event.attributes["exception.message"] == "Unhandled RuntimeError"
    assert "Ally" not in str([dict(e.attributes or {}) for e in span.events])
    assert "Ally" not in str(span.status.description)


def test_story_1_5_ingestion_signs_in_as_the_api_managed_identity(
    fresh_telemetry: DistroRecorder,
) -> None:
    settings = _settings(
        applicationinsights_connection_string=CONNECTION_STRING,
        azure_client_id="00000000-1111-2222-3333-444444444444",
    )

    telemetry.configure_telemetry(settings)

    (call,) = fresh_telemetry.calls
    assert isinstance(call["credential"], ManagedIdentityCredential)


def test_story_1_5_local_runs_may_send_without_a_credential(
    fresh_telemetry: DistroRecorder,
) -> None:
    telemetry.configure_telemetry(
        _settings(applicationinsights_connection_string=CONNECTION_STRING)
    )

    (call,) = fresh_telemetry.calls
    assert "credential" not in call
