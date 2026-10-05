"""Story 1.5: PostgreSQL calls become dependency spans, except the readiness probe's queries.

Database tests run against PostgreSQL (CI: a PostgreSQL 18 service).
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from sqlalchemy import text

from adapters.rest.app import create_app
from adapters.settings import Settings


@pytest.fixture
def traced() -> Iterator[tuple[TracerProvider, InMemorySpanExporter]]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    PsycopgInstrumentor().instrument(tracer_provider=provider)
    try:
        yield provider, exporter
    finally:
        PsycopgInstrumentor().uninstrument()


def test_story_1_5_database_query_is_a_postgresql_dependency_span(
    traced: tuple[TracerProvider, InMemorySpanExporter],
    db_settings: Settings,
    migrated_db: str,
) -> None:
    provider, exporter = traced
    app = create_app(db_settings.model_copy(update={"database_name": migrated_db}))
    exporter.clear()  # the fixtures' own set-up queries

    async def read() -> None:
        with provider.get_tracer("tests").start_as_current_span("request"):
            async with app.state.engine.connect() as connection:
                await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )

    with TestClient(app) as client:
        client.portal.call(read)  # type: ignore[union-attr]  # set inside the with block

    finished = exporter.get_finished_spans()
    request = next(s for s in finished if s.name == "request")
    dependencies = [
        s
        for s in finished
        if s.kind == SpanKind.CLIENT
        and (s.attributes or {}).get("db.system") == "postgresql"
        and "alembic_version" in str((s.attributes or {}).get("db.statement"))
    ]
    assert dependencies
    assert all(
        s.parent is not None and s.parent.span_id == request.context.span_id
        for s in dependencies
    )


def test_story_1_5_readiness_queries_are_not_exported(
    traced: tuple[TracerProvider, InMemorySpanExporter],
    db_settings: Settings,
    migrated_db: str,
) -> None:
    _, exporter = traced
    app = create_app(db_settings.model_copy(update={"database_name": migrated_db}))
    exporter.clear()  # the fixtures' own set-up queries

    with TestClient(app) as client:
        assert client.get("/readyz").status_code == 200

    assert exporter.get_finished_spans() == ()
