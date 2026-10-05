"""OpenTelemetry to Application Insights through the Azure Monitor distro (Story 1.5).

Telemetry is on only when ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set (the foundation stack passes
it as a Container Apps secret). Without it nothing is configured, imported or exported, and the app
runs as before (local runs, CI). Application Insights accepts only Entra-authenticated ingestion, so
in Azure the exporter signs in as the api managed identity (``AZURE_CLIENT_ID``).

When on, it records FastAPI request spans (not ``/healthz`` or ``/readyz``), PostgreSQL dependency
spans through the psycopg (v3) instrumentation and exceptions, sampled at ``TELEMETRY_SAMPLING_RATIO``
(azure.md rule 16). Headers are never captured as span attributes. Log records are not exported:
they go to stdout only (ContainerAppConsoleLogs), carrying the trace and span IDs, so they are
ingested once and no exporter ever sees a raw exception.

The service name (``cloud_RoleName`` in Application Insights) is fixed in code to ``formapp-api``,
the same way ``agent/formapp_agent/telemetry.py`` fixes the agent's; the distro's own default
(``unknown_service:python``) would otherwise apply.
"""

import traceback
from collections.abc import Callable
from typing import Any

from azure.identity import ManagedIdentityCredential
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.trace import Status, StatusCode, TracerProvider

from adapters.settings import Settings, SettingsError

# Without this, the distro's own default resource names the service "unknown_service:python" (its
# fallback when neither this nor OTEL_SERVICE_NAME is set), and Application Insights shows every
# request under cloud_RoleName "unknown_service" instead of api's own name.
SERVICE = "formapp-api"

# Probes are called every few seconds and say nothing about users' requests (Story 1.5). The
# instrumentation searches the full URL (scheme://host/path, no query string) with these regexes;
# they match exactly /healthz and /readyz, with an optional trailing slash.
EXCLUDED_URLS = "^[a-z]+://[^/]+/healthz/?$,^[a-z]+://[^/]+/readyz/?$"

# The distro instruments FastAPI globally, before any app exists, without our excluded URLs; this
# module instruments the app itself instead.
DISTRO_INSTRUMENTATION_OPTIONS: dict[str, dict[str, bool]] = {
    "fastapi": {"enabled": False},
}

_configured = False


def _distro_configure() -> Callable[..., None]:
    # Imported only when telemetry is on, so local runs never load the exporter.
    from azure.monitor.opentelemetry import configure_azure_monitor

    return configure_azure_monitor


def configure_telemetry(
    settings: Settings, *, configure: Callable[..., None] | None = None
) -> bool:
    """Start the distro once per process if a connection string is set; return whether it is on."""
    global _configured
    connection_string = settings.applicationinsights_connection_string
    if connection_string is None:
        return False
    if not _configured:
        options: dict[str, Any] = {"resource": Resource.create({SERVICE_NAME: SERVICE})}
        if settings.azure_client_id:
            # Application Insights has local authentication off: ingestion is authorised by the api
            # identity's Entra token (Monitoring Metrics Publisher). Local runs may send without one.
            options["credential"] = ManagedIdentityCredential(
                client_id=settings.azure_client_id
            )
        try:
            (configure or _distro_configure())(
                **options,
                connection_string=connection_string.get_secret_value(),
                sampling_ratio=settings.telemetry_sampling_ratio,
                instrumentation_options=DISTRO_INSTRUMENTATION_OPTIONS,
                # Logs go to stdout only; exporting them too would ingest every line twice.
                disable_logging=True,
            )
        except ValueError:
            # The distro's own message could quote the value; the settings check normally
            # catches a bad string first.
            raise SettingsError(
                "Invalid configuration: APPLICATIONINSIGHTS_CONNECTION_STRING is invalid"
            ) from None
        # PostgreSQL dependency spans; statements are recorded without parameter values.
        PsycopgInstrumentor().instrument()
        _configured = True
    return True


def instrument_app(app: FastAPI, tracer_provider: TracerProvider | None = None) -> None:
    """Trace the app's requests, except the probes; the global provider unless one is given."""
    kwargs: dict[str, Any] = {}
    if tracer_provider is not None:
        kwargs["tracer_provider"] = tracer_provider
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=EXCLUDED_URLS,
        # One span per request, not one per ASGI message: less ingestion, same information.
        exclude_spans=["receive", "send"],
        **kwargs,
    )


def record_unhandled_exception(exc: BaseException) -> None:
    """Record an unhandled exception on the request span, without its message.

    An exception's message can hold answer values or connection details (security.md rules 2, 30),
    so only its type and the frames it passed through are recorded; Application Insights shows the
    event as an exception on the request.
    """
    span = trace.get_current_span()
    if not span.is_recording():
        return
    name = type(exc).__name__
    exception_type = f"{type(exc).__module__}.{type(exc).__qualname__}"
    # File, line and function only: a source line can quote a value.
    frames = "".join(
        f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n'
        for frame in traceback.extract_tb(exc.__traceback__)
    )
    span.add_event(
        "exception",
        {
            "exception.type": exception_type,
            "exception.message": f"Unhandled {name}",
            "exception.stacktrace": f"Traceback (most recent call last):\n{frames}{exception_type}",
            "exception.escaped": "False",
        },
    )
    span.set_status(Status(StatusCode.ERROR, name))
