"""Story 1.3: the closed AD-12 error shape and its 16 codes."""

import pytest

from domain.errors import DomainError, ErrorCode, FieldError, error_body

AD_12_CODES = {
    "required",
    "invalid_value",
    "out_of_range",
    "invalid_format",
    "unknown_field",
    "inactive_field",
    "human_locked",
    "not_agent_writable",
    "proposal_submitted",
    "stale_revision",
    "declaration_required",
    "turn_in_progress",
    "rate_limited",
    "lock_not_held",
    "feedback_required",
    "speech_unavailable",
}


def test_story_1_3_error_codes_are_exactly_the_16_ad12_codes() -> None:
    assert {code.value for code in ErrorCode} == AD_12_CODES
    assert len(ErrorCode) == 16


def test_story_1_3_domain_error_has_the_closed_shape() -> None:
    error = DomainError(
        [
            FieldError("C1", ErrorCode.REQUIRED, "Enter the first name."),
            FieldError("H10", ErrorCode.INVALID_VALUE, "Choose Yes or No."),
        ]
    )

    assert error.to_dict() == {
        "errors": [
            {"field": "C1", "code": "required", "message": "Enter the first name."},
            {"field": "H10", "code": "invalid_value", "message": "Choose Yes or No."},
        ]
    }


def test_story_1_3_domain_error_allows_one_error_per_field() -> None:
    with pytest.raises(ValueError, match="C1"):
        DomainError(
            [
                FieldError("C1", ErrorCode.REQUIRED, "Enter the first name."),
                FieldError("C1", ErrorCode.INVALID_FORMAT, "Use letters only."),
            ]
        )


def test_story_1_3_domain_error_needs_an_error() -> None:
    with pytest.raises(ValueError):
        DomainError([])


def test_story_1_3_single_error_and_error_body() -> None:
    error = DomainError.single(
        "revision", ErrorCode.STALE_REVISION, "Reload the draft."
    )

    assert error.errors == (
        FieldError("revision", ErrorCode.STALE_REVISION, "Reload the draft."),
    )
    assert error_body(error.errors) == error.to_dict()
    assert "revision: stale_revision" in str(error)
