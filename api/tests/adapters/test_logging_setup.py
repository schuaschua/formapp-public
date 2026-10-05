"""Story 1.5: structured JSON logs on stdout, with trace, span and proposal IDs, and redaction.

All values are synthetic (security.md rule 1); each is distinctive so a test can prove it never
reaches a log line.
"""

import asyncio
import base64
import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider

from adapters.logging_setup import (
    REDACTED,
    JsonFormatter,
    RedactionFilter,
    configure_logging,
    proposal_context,
    redact_text,
    redact_value,
)
from adapters.rest.app import create_app
from tests.adapters.mcp.support import call_tool, running_app
from tests.support import make_settings

logger = logging.getLogger("tests.story_1_5")

# The sensitive items the AC names, one distinctive synthetic value each.
TURN_TOKEN = (
    "eyJwaWQiOiJzeW50aGV0aWMtcHJvcG9zYWwifQ.c3ludGhldGljLXR1cm4tdG9rZW4tc2lnbmF0dXJl"  # noqa: S105 -- synthetic, checked it never logs
)
BEARER = "synthetic-bearer-credential-0001"
PRINCIPAL = base64.b64encode(
    json.dumps(
        {"auth_typ": "aad", "claims": [{"typ": "oid", "val": "synthetic-oid-0001"}]}
    ).encode()
).decode()
CONNECTION_STRING = (
    "InstrumentationKey=00000000-5157-4a11-9000-00000000c0de;"
    "IngestionEndpoint=https://synthetic-ingest.example.test/;"
    "LiveEndpoint=https://synthetic-live.example.test/;"
    "ApplicationId=00000000-5157-4a11-9000-0000000a9901"
)
# A JWT-shaped synthetic Entra token (header, claims, signature).
DB_TOKEN_PARTS = (
    "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9",
    "eyJhdWQiOiJzeW50aGV0aWMtZGF0YWJhc2UtYXVkaWVuY2UifQ",
    "c3ludGhldGljLWRhdGFiYXNlLXRva2VuLXNpZ25hdHVyZQ",
)
DB_TOKEN = ".".join(DB_TOKEN_PARTS)
DB_URL_PASSWORD = "synthetic-db-password-0001"  # noqa: S105 -- synthetic, checked it never logs
ANSWERS = {"C1": "Ally", "C2": "Macbeal", "C6": "900101145678", "N4": "synthetic-n4"}

SECRETS = [
    TURN_TOKEN,
    BEARER,
    PRINCIPAL,
    "synthetic-oid-0001",
    "00000000-5157-4a11-9000-00000000c0de",
    "synthetic-ingest.example.test",
    "synthetic-live.example.test",
    "00000000-5157-4a11-9000-0000000a9901",
    DB_TOKEN,
    "c3ludGhldGljLWRhdGFiYXNlLXRva2VuLXNpZ25hdHVyZQ",
    DB_URL_PASSWORD,
    *ANSWERS.values(),
]


def _lines(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _assert_clean(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text, f"{secret[:12]}... leaked into the logs"


@pytest.fixture
def stdout_logs(capsys: pytest.CaptureFixture[str]) -> Iterator[None]:
    configure_logging()
    yield


def test_story_1_5_log_line_is_json_with_time_level_logger_message(
    stdout_logs: None, capsys: pytest.CaptureFixture[str]
) -> None:
    logger.info("Draft %s saved.", "Untitled_Proposal_001", extra={"question_id": "C1"})

    (line,) = _lines(capsys.readouterr().out)
    assert line["level"] == "INFO"
    assert line["logger"] == "tests.story_1_5"
    assert line["message"] == "Draft Untitled_Proposal_001 saved."
    assert line["question_id"] == "C1"
    # ISO 8601 UTC with milliseconds, e.g. 2026-09-26T10:15:00.123Z.
    assert line["time"].endswith("Z") and line["time"][10] == "T"
    assert len(line["time"]) == len("2026-09-26T10:15:00.123Z")
    # No span and no proposal: the IDs are absent, not empty.
    assert "trace_id" not in line
    assert "span_id" not in line
    assert "proposal_id" not in line


def test_story_1_5_log_line_carries_trace_and_span_ids(
    stdout_logs: None, capsys: pytest.CaptureFixture[str]
) -> None:
    tracer = TracerProvider().get_tracer("tests")
    with tracer.start_as_current_span("request") as span:
        logger.info("Inside a request.")
        context = span.get_span_context()

    (line,) = _lines(capsys.readouterr().out)
    assert line["trace_id"] == f"{context.trace_id:032x}"
    assert line["span_id"] == f"{context.span_id:016x}"


def test_story_1_5_log_line_carries_the_proposal_id_only_inside_its_scope(
    stdout_logs: None, capsys: pytest.CaptureFixture[str]
) -> None:
    with proposal_context(202):
        logger.info("Scoped to a proposal.")
    logger.info("Not scoped.")

    scoped, unscoped = _lines(capsys.readouterr().out)
    assert scoped["proposal_id"] == "202"
    assert "proposal_id" not in unscoped


def test_story_1_5_request_with_every_sensitive_item_is_redacted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = create_app(make_settings(database_port=1))

    # A careless handler that logs everything it gets, in every way a log call can carry it.
    @app.post("/api/story-1-5-careless")
    async def careless(request: Request) -> dict[str, str]:
        raw = (await request.body()).decode()
        body = await request.json()
        with proposal_context("202"):
            logger.info(
                "Request %s with headers %s", request.url.path, dict(request.headers)
            )
            logger.info("Request headers.", extra={"headers": request.headers})
            logger.info("Raw body %s", raw)
            logger.info("Parsed body.", extra={"payload": body})
            logger.info("Answers %s", body["answers"])
            logger.info(f"Authorization was {request.headers['authorization']}")
            logger.info("Turn token %s", request.headers["x-client-turn-token"])
            logger.info("Principal %s", request.headers["x-ms-client-principal"])
            logger.info("Connection string %s", CONNECTION_STRING)
            logger.info("Database token %s", DB_TOKEN)
            logger.info(
                "Connecting",
                extra={
                    "connection_string": CONNECTION_STRING,
                    "db_token": DB_TOKEN,
                    "turn_token": TURN_TOKEN,
                    "dsn": f"postgresql://api:{DB_URL_PASSWORD}@db.example.test/formapp",
                },
            )
            logger.info({"C1": ANSWERS["C1"], "authorization": f"Bearer {BEARER}"})
        return {"status": "ok"}

    with TestClient(app) as client:
        capsys.readouterr()
        response = client.post(
            "/api/story-1-5-careless",
            headers={
                "Authorization": f"Bearer {BEARER}",
                "X-MS-CLIENT-PRINCIPAL": PRINCIPAL,
                "X-MS-CLIENT-PRINCIPAL-ID": "synthetic-oid-0001",
                "x-client-turn-token": TURN_TOKEN,
                "X-Session-Id": "synthetic-session",
            },
            json={
                "answers": ANSWERS,
                "connection": CONNECTION_STRING,
                "db_token": DB_TOKEN,
            },
        )

    assert response.status_code == 200
    output = capsys.readouterr().out
    lines = [line for line in _lines(output) if line["logger"] == logger.name]
    _assert_clean(output)
    # The lines are still there and still useful: redaction removes values, not the log call.
    assert len(lines) == 12
    assert all(line["proposal_id"] == "202" for line in lines)
    assert lines[0]["message"].startswith(
        "Request /api/story-1-5-careless with headers"
    )
    assert lines[7]["message"] == f"Principal {REDACTED}"
    assert lines[1]["headers"]["authorization"] == REDACTED
    assert lines[1]["headers"]["x-session-id"] == "synthetic-session"
    assert lines[3]["payload"]["answers"] == REDACTED
    assert lines[10]["connection_string"] == REDACTED


def test_story_1_5_redaction_applies_to_every_root_handler(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Any other root handler (one a library adds) must only ever see redacted records."""
    seen: list[logging.LogRecord] = []

    class Exporter(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record)

    exporter = Exporter()
    root = logging.getLogger()
    root.addHandler(exporter)
    try:
        configure_logging()
        logger.info("Authorization: Bearer %s", BEARER, extra={"answers": ANSWERS})
    finally:
        root.removeHandler(exporter)

    (record,) = seen
    assert any(isinstance(f, RedactionFilter) for f in exporter.filters)
    assert BEARER not in record.getMessage()
    assert record.answers == REDACTED  # type: ignore[attr-defined]  # set through extra
    _assert_clean(capsys.readouterr().out)


def test_story_1_5_exception_text_is_redacted(
    stdout_logs: None, capsys: pytest.CaptureFixture[str]
) -> None:
    try:
        raise RuntimeError(f"connect failed: {CONNECTION_STRING}")
    except RuntimeError:
        logger.exception("Database sign-in failed.")

    output = capsys.readouterr().out
    (line,) = _lines(output)
    assert "RuntimeError" in line["exception"]
    _assert_clean(output)


def test_story_1_5_uvicorn_logs_go_through_the_json_handler(
    stdout_logs: None, capsys: pytest.CaptureFixture[str]
) -> None:
    uvicorn_error = logging.getLogger("uvicorn.error")
    uvicorn_error.info("Started server process [%d]", 7, extra={"color_message": "x"})

    assert not uvicorn_error.handlers
    (line,) = _lines(capsys.readouterr().out)
    assert line["logger"] == "uvicorn.error"
    assert line["message"] == "Started server process [7]"
    assert "color_message" not in line


def test_story_1_5_configuring_twice_keeps_one_stdout_handler(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging()
    configure_logging()
    logger.info("Once.")

    assert len(_lines(capsys.readouterr().out)) == 1


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("authorization: Basic c3ludGhldGljOnVzZXI=", "c3ludGhldGljOnVzZXI="),
        (
            "{'x-ms-token-aad-access-token': 'synthetic-aad-token'}",
            "synthetic-aad-token",
        ),
        ("Cookie=AppServiceAuthSession=synthetic-cookie", "synthetic-cookie"),
        ('{"H10": "Yes-synthetic", "value": 12345.67}', "Yes-synthetic"),
        ('{"value": 12345.67}', "12345.67"),
        ("host=db password=synthetic-libpq-pw dbname=formapp", "synthetic-libpq-pw"),
    ],
)
def test_story_1_5_text_patterns_are_redacted(text: str, secret: str) -> None:
    assert secret not in redact_text(text)


def test_story_1_5_question_ids_stay_but_their_values_go() -> None:
    cleaned = redact_value({"question_id": "C1", "C1": "Ally", "codes": ["N4"], "n": 3})

    assert cleaned == {"question_id": "C1", "C1": REDACTED, "codes": ["N4"], "n": 3}


def test_story_1_5_unusual_values_are_logged_as_redacted_text() -> None:
    class Odd:
        def __str__(self) -> str:
            return f"Odd(Bearer {BEARER})"

    class BrokenMapping:
        def items(self) -> list[Any]:
            raise RuntimeError("no items")

        def __str__(self) -> str:
            return f"broken token={TURN_TOKEN}"

    cleaned = redact_value([Odd(), b"Bearer bytes-credential-0001", BrokenMapping()])

    assert BEARER not in cleaned[0]
    assert "bytes-credential-0001" not in cleaned[1]
    assert TURN_TOKEN not in cleaned[2]


def test_story_1_5_a_bad_format_string_still_logs_redacted(
    stdout_logs: None, capsys: pytest.CaptureFixture[str]
) -> None:
    record = logging.LogRecord(
        "tests", logging.INFO, __file__, 1, f"Bearer {BEARER} %s %s", ("one",), None
    )

    assert RedactionFilter().filter(record)
    assert BEARER not in JsonFormatter().format(record)


def test_story_1_5_no_handler_sees_a_raw_exception(
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[logging.LogRecord] = []

    class OtherHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record)

    other = OtherHandler()
    root = logging.getLogger()
    root.addHandler(other)
    try:
        configure_logging()
        try:
            raise RuntimeError(f"sign-in failed: {CONNECTION_STRING}")
        except RuntimeError:
            logger.exception("Database sign-in failed.", stack_info=True)
    finally:
        root.removeHandler(other)

    (record,) = seen
    assert record.exc_info is None
    assert record.exc_text is not None and "RuntimeError" in record.exc_text
    (line,) = _lines(capsys.readouterr().out)
    assert "RuntimeError" in line["exception"]
    assert "stack" in line
    _assert_clean(record.exc_text)
    _assert_clean(json.dumps(line))


def test_story_1_5_a_record_that_cannot_be_cleaned_is_blanked_not_raised() -> None:
    class Unprintable:
        def __str__(self) -> str:
            raise RuntimeError(f"Bearer {BEARER}")

    record = logging.LogRecord(
        "tests", logging.INFO, __file__, 1, "Value %s", (Unprintable(),), None
    )
    record.extra_field = f"Bearer {BEARER}"

    assert RedactionFilter().filter(record)
    assert record.getMessage().startswith(REDACTED)
    assert record.extra_field == REDACTED  # type: ignore[attr-defined]  # set above


def test_story_1_5_numbers_ids_and_times_keep_their_formatting(
    stdout_logs: None, capsys: pytest.CaptureFixture[str]
) -> None:
    proposal = UUID("00000000-0000-4000-8000-000000000202")
    logger.info(
        "Saved %d answers, quote RM %.2f, proposal %s at %s",
        3,
        Decimal("123.456"),
        proposal,
        datetime(2026, 9, 26, 10, 15, tzinfo=UTC),
    )

    (line,) = _lines(capsys.readouterr().out)
    assert line["message"] == (
        f"Saved 3 answers, quote RM 123.46, proposal {proposal} at 2026-09-26 10:15:00+00:00"
    )


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("patch C1=Ally, C6 = 900101145678; H10=Yes-synthetic", "Ally"),
        ("patch C1=Ally, C6 = 900101145678; H10=Yes-synthetic", "900101145678"),
        ("patch C1=Ally, C6 = 900101145678; H10=Yes-synthetic", "Yes-synthetic"),
        ('{"N4": {"insurer": "Synthetic Life", "sum": 1}}', "Synthetic Life"),
        ("{'answers': {'C1': 'Ally', 'P1': ['a-synthetic', 'b']}}", "a-synthetic"),
        ('{"value": [{"x": "nested-synthetic"}]}', "nested-synthetic"),
        ("G2=[1, 2, 'list-synthetic']", "list-synthetic"),
    ],
)
def test_story_1_5_answer_values_in_text_are_redacted(text: str, secret: str) -> None:
    cleaned = redact_text(text)

    assert secret not in cleaned
    # The question IDs themselves stay (security.md rule 30).
    assert any(qid in cleaned for qid in ("C1", "N4", "answers", "value", "G2"))


def test_story_1_5_answer_redaction_keeps_the_rest_of_the_line() -> None:
    assert redact_text("C1=Ally, question C2 missing") == (
        f"C1='{REDACTED}', question C2 missing"
    )


@pytest.mark.parametrize(
    "text",
    [
        "pgsql-sample-demo-sea.postgres.database.azure.com",
        "/app/.venv/lib/python3.13/site-packages/opentelemetry/instrumentation/fastapi/__init__.py",
        "opentelemetry.instrumentation.fastapi_instrumentation.middleware",
        "adapters.rest.middleware",
        "azure.monitor.opentelemetry.exporter.export._base",
    ],
)
def test_story_1_5_host_names_paths_and_module_names_are_not_tokens(text: str) -> None:
    assert redact_text(text) == text


def test_story_1_5_non_string_keys_are_logged_as_text(
    stdout_logs: None, capsys: pytest.CaptureFixture[str]
) -> None:
    logger.info("Counts.", extra={"counts": {1: "one", ("C1", 2): "pair"}})

    (line,) = _lines(capsys.readouterr().out)
    assert line["counts"] == {"1": "one", "('C1', 2)": "pair"}


def test_story_1_5_proposal_context_of_none_sets_no_proposal(
    stdout_logs: None, capsys: pytest.CaptureFixture[str]
) -> None:
    with proposal_context(None):
        logger.info("No proposal.")

    (line,) = _lines(capsys.readouterr().out)
    assert "proposal_id" not in line


def test_story_1_5_proposal_id_goes_on_the_record_and_the_span() -> None:
    record = logging.LogRecord("tests", logging.INFO, __file__, 1, "x", None, None)
    tracer = TracerProvider().get_tracer("tests")
    with tracer.start_as_current_span("request") as span, proposal_context(202):
        RedactionFilter().filter(record)

    assert record.proposal_id == "202"  # type: ignore[attr-defined]  # set by the filter
    attributes = cast(ReadableSpan, span).attributes
    assert attributes is not None
    assert attributes["proposal_id"] == "202"


def test_story_1_5_log_level_setting_controls_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    create_app(make_settings(database_port=1, log_level="WARNING"))
    logger.info("Hidden.")
    logger.warning("Shown.")

    lines = [
        line
        for line in _lines(capsys.readouterr().out)
        if line["logger"] == logger.name
    ]
    assert [line["message"] for line in lines] == ["Shown."]
    configure_logging()


def test_story_4_3_a_rejected_mcp_call_never_logs_the_turn_token(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Story 4.3, security.md rule 6/7/36: /mcp's own equivalent of a REST 401/403 -- a bad
    bearer token rejected with the closed ``lock_not_held`` shape -- never logs the token string
    itself, on this or any other root handler (the redaction filter, not the caller, is the
    defence)."""
    app = create_app(make_settings(database_port=1))

    async def scenario() -> dict[str, Any]:
        async with running_app(app):
            capsys.readouterr()
            return await call_tool(app, TURN_TOKEN, "get_form_schema")

    result = asyncio.run(scenario())

    output = capsys.readouterr().out
    assert result["errors"][0]["code"] == "lock_not_held"
    _assert_clean(output)
    assert TURN_TOKEN not in output
