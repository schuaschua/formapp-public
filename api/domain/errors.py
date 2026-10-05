"""The closed error shape and error codes (spine AD-12).

Every validation and write failure is ``{"errors": [{"field", "code", "message"}]}`` with one of the
16 codes below and at most one error per field. Adapters map a ``DomainError`` to a response.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    """The closed set of AD-12 error codes; adding one means amending AD-12."""

    REQUIRED = "required"
    INVALID_VALUE = "invalid_value"
    OUT_OF_RANGE = "out_of_range"
    INVALID_FORMAT = "invalid_format"
    UNKNOWN_FIELD = "unknown_field"
    INACTIVE_FIELD = "inactive_field"
    HUMAN_LOCKED = "human_locked"
    NOT_AGENT_WRITABLE = "not_agent_writable"
    PROPOSAL_SUBMITTED = "proposal_submitted"
    STALE_REVISION = "stale_revision"
    DECLARATION_REQUIRED = "declaration_required"
    TURN_IN_PROGRESS = "turn_in_progress"
    RATE_LIMITED = "rate_limited"
    LOCK_NOT_HELD = "lock_not_held"
    FEEDBACK_REQUIRED = "feedback_required"
    SPEECH_UNAVAILABLE = "speech_unavailable"


@dataclass(frozen=True, slots=True)
class FieldError:
    """One error on one field (a question id such as ``C1``, or a request-level name)."""

    field: str
    code: ErrorCode
    message: str

    def to_dict(self) -> dict[str, str]:
        """Return the wire form ``{"field", "code", "message"}``."""
        return {"field": self.field, "code": self.code.value, "message": self.message}


class DomainError(Exception):
    """A rule failure carrying one or more field errors, at most one per field (AD-12)."""

    def __init__(self, errors: Iterable[FieldError]) -> None:
        collected = tuple(errors)
        if not collected:
            raise ValueError("A DomainError needs at least one FieldError.")
        fields = [error.field for error in collected]
        duplicates = sorted({field for field in fields if fields.count(field) > 1})
        if duplicates:
            raise ValueError(
                f"At most one error per field (AD-12); repeated: {', '.join(duplicates)}."
            )
        super().__init__(
            ", ".join(f"{error.field}: {error.code.value}" for error in collected)
        )
        self.errors = collected

    @classmethod
    def single(cls, field: str, code: ErrorCode, message: str) -> "DomainError":
        """Build a DomainError with one field error."""
        return cls([FieldError(field=field, code=code, message=message)])

    def to_dict(self) -> dict[str, list[dict[str, str]]]:
        """Return the AD-12 body ``{"errors": [...]}``."""
        return error_body(self.errors)


def error_body(errors: Iterable[FieldError]) -> dict[str, list[dict[str, str]]]:
    """Return the AD-12 body for the given field errors."""
    return {"errors": [error.to_dict() for error in errors]}
