"""Structured JSON logs on stdout, with trace and span IDs, and redaction (Story 4.2).

A copy of ``api/adapters/logging_setup.py`` (Story 1.5), without the proposal context: the agent
never knows which proposal a turn is for, and it must not import from ``api/`` (AD-1).

Every log line is one JSON object: ISO 8601 UTC time, level, logger, message and the current trace
and span IDs (when a span is active).

Stdout is the only log route: the hosting platform collects it, and the Azure Monitor exporter
sends traces only. The redaction filter runs on every root handler, so no handler ever sees an
uncleaned record. It removes Authorization and principal headers, turn tokens, connection strings,
database tokens and answer values (security.md rules 2, 7, 30; azure.md
rule 16; NFR7, NFR17). It works on structure first (mapping keys) and on text patterns second; code
should still log answers only by question ID, never their values.
"""

import json
import logging
import numbers
import re
import sys
import traceback
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from typing import Any
from uuid import UUID

from opentelemetry import trace

REDACTED = "[REDACTED]"

# --- Redaction --------------------------------------------------------------------------------

# Mapping keys whose values are never logged, compared lower-case with "_" read as "-". Headers
# (Authorization, X-MS-CLIENT-PRINCIPAL*, X-MS-TOKEN-*, x-client-turn-token, cookies), tokens,
# passwords, secrets, connection strings and answers.
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "principal",
    "token",
    "password",
    "passwd",
    "secret",
    "connection-string",
    "connectionstring",
    "signing-key",
    "api-key",
    "answer",
)
_SENSITIVE_KEYS = frozenset({"value", "values", "formdata", "body", "pwd"})
# Schema question IDs (C1, H10): the key can be logged, the value never (security.md rule 2).
_QUESTION_ID = re.compile(r"^[A-Z][0-9]{1,2}$")

_HEADER_NAMES = (
    r"authorization|proxy-authorization|cookie|set-cookie|"
    r"x-ms-client-principal(?:-[a-z]+)?|x-ms-token-[a-z0-9-]+|x-client-turn-token"
)
_TEXT_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # A header written as text: "Authorization: Bearer ...", "'x-ms-client-principal': '...'".
    (
        re.compile(
            rf"""(["']?\b(?:{_HEADER_NAMES})["']?\s*[:=]\s*)(["']?)[^"'\r\n,}}]+""",
            re.IGNORECASE,
        ),
        rf"\1\2{REDACTED}",
    ),
    # Bearer and Basic credentials anywhere.
    (
        re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
        rf"\1 {REDACTED}",
    ),
    # Signed tokens (JWTs such as Entra database tokens, and dot-separated signed turn tokens):
    # two or three base64url segments of 16+ characters, mixing upper case, lower case and digits,
    # so host names, paths and dotted module names don't match.
    (
        re.compile(
            r"(?<![A-Za-z0-9_.-])"
            r"(?=[A-Za-z0-9_.-]*[A-Z])(?=[A-Za-z0-9_.-]*[a-z])(?=[A-Za-z0-9_.-]*[0-9])"
            r"[A-Za-z0-9_-]{16,}(?:\.[A-Za-z0-9_-]{16,}){1,2}=*(?![A-Za-z0-9_.-])"
        ),
        REDACTED,
    ),
    (re.compile(r"\beyJ[A-Za-z0-9_+/-]{8,}(?:\.[A-Za-z0-9_-]*){0,2}=*"), REDACTED),
    # Connection strings: Application Insights, storage, libpq key=value and URL credentials.
    (
        re.compile(
            r"\b(InstrumentationKey|IngestionEndpoint|LiveEndpoint|ApplicationId|AccountKey|"
            r"SharedAccessKey|SharedAccessSignature|password|pwd)(\s*=\s*)[^;\s'\"]+",
            re.IGNORECASE,
        ),
        rf"\1\2{REDACTED}",
    ),
    (re.compile(r"(://)[^/\s:@]+:[^@\s]+@"), rf"\1{REDACTED}@"),
)

# Where an answer value starts in text: "C1": ..., 'value': ..., "answers": ..., C1=...
_ANSWER_KEY = re.compile(
    r"""(?:["'](?:[A-Z][0-9]{1,2}|values?|answers?)["']\s*:\s*)"""
    r"""|(?:(?<![A-Za-z0-9_])[A-Z][0-9]{1,2}\s*=\s*)"""
)
_PLAIN_VALUE_END = re.compile(r"[^,;\s&)}\]]*")
_CLOSING = {"{": "}", "[": "]"}


def _quoted_end(text: str, start: int) -> int:
    """Index just past the string literal opening at ``start`` (or the end of the text)."""
    quote = text[start]
    index = start + 1
    while index < len(text):
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == quote:
            return index + 1
        index += 1
    return len(text)


def _value_end(text: str, start: int) -> int:
    """Index just past the value at ``start``: a string, a balanced object or list, or a word."""
    if start >= len(text):
        return start
    if text[start] in "\"'":
        return _quoted_end(text, start)
    if text[start] in _CLOSING:
        depth = 0
        index = start
        while index < len(text):
            char = text[index]
            if char in "\"'":
                index = _quoted_end(text, index)
                continue
            if char in "{[":
                depth += 1
            elif char in "}]":
                depth -= 1
                if depth == 0:
                    return index + 1
            index += 1
        return len(text)
    match = _PLAIN_VALUE_END.match(text, start)
    return match.end() if match else start


def _redact_answer_values(text: str) -> str:
    parts: list[str] = []
    position = 0
    while match := _ANSWER_KEY.search(text, position):
        end = _value_end(text, match.end())
        if end == match.end():
            parts.append(text[position : match.end()])
        else:
            parts.append(text[position : match.end()] + f"'{REDACTED}'")
        position = max(end, match.end())
        if position >= len(text):
            break
    parts.append(text[position:])
    return "".join(parts)


def _is_sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    if _QUESTION_ID.match(key):
        return True
    normalised = key.lower().replace("_", "-")
    return normalised in _SENSITIVE_KEYS or any(
        part in normalised for part in _SENSITIVE_KEY_PARTS
    )


def redact_text(text: str) -> str:
    """Replace secrets and answer values that appear in free text."""
    text = _redact_answer_values(text)
    for pattern, replacement in _TEXT_RULES:
        text = pattern.sub(replacement, text)
    return text


def redact_value(value: Any) -> Any:
    """A copy of ``value`` safe to log: sensitive mapping keys lose their values, text is cleaned."""
    # Numbers, IDs and times are kept as they are, so %d and %.2f formatting still works.
    if value is None or isinstance(value, numbers.Number | UUID | date | time):
        return value
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bytes | bytearray):
        return redact_text(bytes(value).decode("utf-8", errors="replace"))
    if isinstance(value, Mapping) or hasattr(value, "items"):
        try:
            items = list(value.items())
        except Exception:  # noqa: BLE001 -- an odd mapping is logged as text instead
            return redact_text(str(value))
        cleaned: dict[str, Any] = {}
        for k, v in items:
            key = _key_text(k)
            cleaned[key] = REDACTED if _is_sensitive_key(key) else redact_value(v)
        return cleaned
    if isinstance(value, list | tuple | set | frozenset):
        return [redact_value(item) for item in value]
    # Anything else is logged by its text, which is cleaned like any other text.
    return redact_text(str(value))


def _key_text(key: object) -> str:
    # JSON keys must be strings; a tuple or number key is logged by its text.
    return key.decode("latin-1") if isinstance(key, bytes) else str(key)


# Attributes every LogRecord has; anything else on a record came from ``extra``.
_RECORD_ATTRIBUTES = frozenset(
    vars(logging.LogRecord("", logging.INFO, "", 0, "", None, None))
) | {"message", "asctime", "taskName"}


class RedactionFilter(logging.Filter):
    """Cleans a record in place (message, arguments and extra fields) before any handler emits it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            self._clean(record)
        except Exception:  # noqa: BLE001 -- a record that can't be cleaned is replaced, never raised
            _blank(record)
        return True

    @staticmethod
    def _clean(record: logging.LogRecord) -> None:
        if not isinstance(record.msg, str):
            record.msg = redact_value(record.msg)
        if record.args:
            if isinstance(record.args, Mapping):
                record.args = redact_value(record.args)
            else:
                record.args = tuple(redact_value(arg) for arg in record.args)
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 -- a bad format string must not drop the record
            message = str(record.msg)
        record.msg = redact_text(message)
        record.args = None
        for key, value in list(vars(record).items()):
            if key in _RECORD_ATTRIBUTES or key.startswith("_"):
                continue
            setattr(
                record, key, REDACTED if _is_sensitive_key(key) else redact_value(value)
            )
        # No handler ever sees the raw exception: its message can hold values.
        if record.exc_info:
            record.exc_text = "".join(traceback.format_exception(*record.exc_info))
            record.exc_info = None
        if record.exc_text:
            record.exc_text = redact_text(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_text(record.stack_info)


def _blank(record: logging.LogRecord) -> None:
    """Replace everything a record carries that could hold a value."""
    record.msg = f"{REDACTED} (log record could not be cleaned)"
    record.args = None
    record.exc_info = None
    record.exc_text = None
    record.stack_info = None
    for key in list(vars(record)):
        if key not in _RECORD_ATTRIBUTES and not key.startswith("_"):
            setattr(record, key, REDACTED)


# --- JSON formatting --------------------------------------------------------------------------

# A server's colour copy of each message; the JSON line has the plain message.
_DROPPED_EXTRAS = frozenset({"color_message"})


class JsonFormatter(logging.Formatter):
    """One JSON object per record, with trace and span IDs where there are any."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            entry["trace_id"] = trace.format_trace_id(span_context.trace_id)
            entry["span_id"] = trace.format_span_id(span_context.span_id)
        for key, value in vars(record).items():
            if (
                key in _RECORD_ATTRIBUTES
                or key in _DROPPED_EXTRAS
                or key.startswith("_")
                or key in entry
            ):
                continue
            entry[key] = value
        if record.exc_info:
            # Only a cleaned traceback; the filter normally did this already.
            entry["exception"] = redact_text(self.formatException(record.exc_info))
        elif record.exc_text:
            entry["exception"] = redact_text(record.exc_text)
        if record.stack_info:
            entry["stack"] = redact_text(record.stack_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


# --- Wiring -----------------------------------------------------------------------------------

# The agent server runs on Hypercorn, which configures these itself; they go through the root logger.
_SERVER_LOGGERS = ("hypercorn.error", "hypercorn.access")
# Chatty libraries whose INFO lines are HTTP traces of their own (the telemetry exporter's too).
_QUIET_LOGGERS = ("azure", "urllib3")


class _StdoutJsonHandler(logging.Handler):
    """Writes each record to the current ``sys.stdout``; repeated setup replaces this handler."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            sys.stdout.write(self.format(record) + "\n")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001 -- logging must never break the request
            self.handleError(record)


def configure_logging(level: int | str = logging.INFO) -> None:
    """Send every log record as redacted JSON to stdout; safe to call more than once."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, _StdoutJsonHandler):
            root.removeHandler(handler)
    handler = _StdoutJsonHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    # Every root handler gets the filter, including any a library added before this ran.
    for existing in root.handlers:
        if not any(isinstance(f, RedactionFilter) for f in existing.filters):
            existing.addFilter(RedactionFilter())

    for name in _SERVER_LOGGERS:
        server_logger = logging.getLogger(name)
        server_logger.handlers.clear()
        server_logger.propagate = True
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
