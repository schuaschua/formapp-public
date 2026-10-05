"""The FastAPI application factory.

Run with ``uvicorn adapters.rest.app:create_app --factory``. Startup reads the settings (and stops,
naming the variable, if one is missing), creates the database engine and computes the bundled Alembic
head. It never runs migrations: the deploy pipeline does (spine AD-10, AD-11). It also sets up the
JSON logs and, when a connection string is set, telemetry to Application Insights (Story 1.5), and
mounts the ``/mcp`` Streamable HTTP server (Story 4.3, AD-3, AD-4) alongside the REST routes.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from adapters.chat.gateway import AgentGateway
from adapters.clock import SystemClock
from adapters.db.engine import build_password_source, create_engine
from adapters.db.readiness import bundled_head
from adapters.db.scope import install_scope
from adapters.logging_setup import configure_logging
from adapters.mcp.server import MCPDispatchMiddleware, build_mcp_app
from adapters.rest.chat import router as chat_router
from adapters.rest.errors import register_error_handlers
from adapters.rest.health import router as health_router
from adapters.rest.me import router as me_router
from adapters.rest.middleware import (
    AuthRequiredMiddleware,
    SecurityHeadersMiddleware,
    SessionHeaderMiddleware,
    build_security_headers,
    content_security_policy,
)
from adapters.rest.products import router as products_router
from adapters.rest.proposals import router as proposals_router
from adapters.rest.spa import register_spa
from adapters.rest.speech import router as speech_router
from adapters.settings import Settings, load_settings
from adapters.telemetry import configure_telemetry, instrument_app
from domain.clock import Clock
from domain.speech import SpeechTokenIssuer


def _default_agent_gateway(
    settings: Settings, clock: Clock, engine: AsyncEngine
) -> AgentGateway:
    """The ``AgentGateway`` ``create_app`` builds when the caller gives none (Story 4.5, AD-18):
    the scripted stub in test mode (never a real Foundry call), the Foundry implementation
    otherwise -- both imported lazily, so a test-mode process never has to import ``openai`` or
    construct a real Azure credential, and a demo process never imports the test-only stub."""
    if settings.formapp_test_mode:
        from adapters.chat.stub import StubAgentGateway

        return StubAgentGateway(
            engine=engine, signing_key=settings.turn_token_signing_key, clock=clock
        )
    from azure.identity.aio import ManagedIdentityCredential

    from adapters.chat.foundry import FoundryAgentGateway

    return FoundryAgentGateway(
        project_endpoint=settings.foundry_project_endpoint or "",
        agent_name=settings.foundry_agent_name or "",
        model=settings.foundry_model or "",
        credential=ManagedIdentityCredential(client_id=settings.azure_client_id)
        if settings.azure_client_id
        else None,
    )


def _default_speech_token_issuer(settings: Settings, clock: Clock) -> SpeechTokenIssuer:
    """The ``SpeechTokenIssuer`` ``create_app`` builds when the caller gives none (Story 6.1,
    AD-18): the stub in test mode (never a real Azure call), the production issuer otherwise --
    both imported lazily, mirroring ``_default_agent_gateway``."""
    if settings.formapp_test_mode:
        from adapters.speech.stub import StubSpeechTokenIssuer

        return StubSpeechTokenIssuer(clock=clock)
    from azure.identity.aio import ManagedIdentityCredential

    from adapters.speech.azure import AzureSpeechTokenIssuer

    return AzureSpeechTokenIssuer(
        region=settings.speech_region or "",
        endpoint=settings.speech_endpoint or "",
        resource_id=settings.speech_resource_id or "",
        client_id=settings.speech_identity_client_id or "",
        voice=settings.speech_voice or "",
        locale=settings.speech_locale or "",
        clock=clock,
        credential=ManagedIdentityCredential(
            client_id=settings.speech_identity_client_id
        )
        if settings.speech_identity_client_id
        else None,
    )


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    engine: AsyncEngine | None = None,
    agent_gateway: AgentGateway | None = None,
    speech_token_issuer: SpeechTokenIssuer | None = None,
) -> FastAPI:
    """Build the app; tests pass their own settings, clock, engine, agent_gateway or
    speech_token_issuer (spine AD-18)."""
    settings = settings or load_settings()
    # Telemetry first, so the logging setup puts its redaction filter on any handler a library adds
    # (Story 1.5). Without a connection string, telemetry stays off.
    telemetry_on = configure_telemetry(settings)
    configure_logging(settings.log_level)
    clock = clock or SystemClock()
    owns_engine = engine is None
    app_engine = engine or create_engine(
        settings, build_password_source(settings, clock)
    )
    # One shared scope function for every transaction on this engine (Story 4.3 Part B, AD-17):
    # REST's AuthRequiredMiddleware and MCP's _authorize each set it around their own call, and
    # every SqlProposalStore/SqlProductCatalogue transaction picks it up automatically.
    install_scope(app_engine)
    mcp_server, mcp_app = build_mcp_app(
        app_engine, settings.turn_token_signing_key, clock
    )
    agent_gateway = agent_gateway or _default_agent_gateway(settings, clock, app_engine)
    speech_token_issuer = speech_token_issuer or _default_speech_token_issuer(
        settings, clock
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            # The session manager's task group only exists inside this context manager (Story
            # 4.3); a /mcp call before startup or after shutdown would otherwise 500.
            async with mcp_server.session_manager.run():
                yield
        finally:
            if owns_engine:
                await app_engine.dispose()

    # No OpenAPI or docs pages: the API is formapp's own, and CORS stays off (security.md rule 22).
    app = FastAPI(
        title="formapp api",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.clock = clock
    app.state.engine = app_engine
    app.state.agent_gateway = agent_gateway
    app.state.speech_token_issuer = speech_token_issuer
    app.state.expected_head = bundled_head()

    register_error_handlers(app)
    app.include_router(health_router)
    app.include_router(me_router)
    app.include_router(products_router)
    app.include_router(proposals_router)
    app.include_router(chat_router)
    app.include_router(speech_router)
    register_spa(app, settings.formapp_static_dir)

    # The last added is the outermost: headers go on every response, including the sign-in 401
    # and the forgery 403; a signed-out call gets the 401 before the 403 (Story 1.6). /mcp is
    # dispatched before any of these reach FastAPI's router (adapters.mcp.server's docstring on
    # why), but Auth/SessionHeader are harmless no-ops for it either way (both only match /api*),
    # and it still gets the security headers and safe-500 handling (Story 4.3).
    app.add_middleware(MCPDispatchMiddleware, mcp_app=mcp_app)
    app.add_middleware(SessionHeaderMiddleware)
    app.add_middleware(AuthRequiredMiddleware, settings=settings)
    # Story 6.1: connect-src widens to the configured Speech hosts only when Speech settings are
    # set (never in local/test/CI); the CSP's static base is otherwise unchanged (Story 1.4 parity).
    app.add_middleware(
        SecurityHeadersMiddleware,
        security_headers=build_security_headers(content_security_policy(settings)),
    )
    if telemetry_on:
        instrument_app(app)
    return app
