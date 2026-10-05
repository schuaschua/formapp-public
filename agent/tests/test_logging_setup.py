"""Story 4.2: JSON logs with redaction; tokens, headers and answer values never reach stdout."""

import json
import logging

import pytest

from formapp_agent.logging_setup import REDACTED, configure_logging, redact_value
from tests.conftest import TURN_1

CONNECTION_STRING = (
    "InstrumentationKey=00000000-0000-0000-0000-000000000000;"
    "IngestionEndpoint=https://ingest.example.test/"
)


@pytest.fixture
def lines(capsys: pytest.CaptureFixture[str]) -> "LogLines":
    configure_logging(logging.DEBUG)
    return LogLines(capsys)


class LogLines:
    def __init__(self, capsys: pytest.CaptureFixture[str]) -> None:
        self.capsys = capsys

    def read(self) -> list[dict[str, object]]:
        return [
            json.loads(line)
            for line in self.capsys.readouterr().out.splitlines()
            if line
        ]


def test_story_4_2_token_and_headers_redacted_from_logs(lines: LogLines) -> None:
    log = logging.getLogger("formapp_agent.test")
    log.info("Authorization: Bearer %s", TURN_1)
    log.info("headers %s", {"x-client-turn-token": TURN_1, "traceparent": "00-abc"})
    log.info("token alone %s", TURN_1)
    log.info("sent", extra={"authorization": f"Bearer {TURN_1}", "question_id": "C1"})
    log.warning("conn %s", CONNECTION_STRING)
    log.info("answer %s", {"C1": "Ally", "values": ["Macbeal"]})
    log.info("inline C2=1994-11-20 and 'value': 'secret-ish'")
    log.info(b"bytes Bearer abcdefghijklmnop")

    records = lines.read()
    text = json.dumps(records)
    assert TURN_1 not in text
    assert "00000000-0000-0000-0000-000000000000" not in text
    assert "Ally" not in text and "Macbeal" not in text and "1994-11-20" not in text
    assert "secret-ish" not in text and "abcdefghijklmnop" not in text
    assert REDACTED in text
    assert records[3]["question_id"] == "C1"
    assert all({"time", "level", "logger", "message"} <= set(r) for r in records)


def test_story_4_2_exceptions_logged_without_values(lines: LogLines) -> None:
    log = logging.getLogger("formapp_agent.test")
    try:
        raise RuntimeError(f"failed with Bearer {TURN_1}")
    except RuntimeError:
        log.exception("tool call failed")
    log.info("stack", stack_info=True)

    records = lines.read()
    assert "RuntimeError" in str(records[0]["exception"])
    assert TURN_1 not in json.dumps(records)
    assert "stack" in records[1]


def test_story_4_2_bad_records_are_blanked_not_raised(lines: LogLines) -> None:
    log = logging.getLogger("formapp_agent.test")
    # A format string missing an argument, on purpose: the record must still be logged.
    log.info("two args %s %s", "only-one")  # noqa: PLE1206 -- the broken call under test

    class Unprintable:
        def __str__(self) -> str:
            raise ValueError("no")

    log.info("odd %s", Unprintable())

    records = lines.read()
    assert [record["message"] for record in records] == [
        "two args %s %s",
        f"{REDACTED} (log record could not be cleaned)",
    ]


def test_story_4_2_redact_value_keeps_ids_and_numbers() -> None:
    class Items:
        def items(self) -> list[tuple[object, object]]:
            return [(b"token", "x"), (1, 2.5)]

    assert redact_value(3) == 3
    assert redact_value(None) is None
    assert redact_value({"password": "p", "count": 2}) == {
        "password": REDACTED,
        "count": 2,
    }
    assert redact_value(("C1", "text")) == ["C1", "text"]
    assert redact_value(Items()) == {"token": REDACTED, "1": 2.5}
    assert redact_value(bytearray(b"plain")) == "plain"
    assert redact_value(object()).startswith("<object")
