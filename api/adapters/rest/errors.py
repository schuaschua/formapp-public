"""Maps domain errors and request validation errors to AD-12 responses (spine AD-12)."""

from collections.abc import Mapping
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from adapters.rest.principal import SIGN_IN_REQUIRED, SignInRequired
from domain.errors import DomainError, ErrorCode, FieldError, error_body
from domain.proposals import ProposalNotFoundError
from domain.throttle import ThrottledError

# HTTP status per code; anything not listed is a 422 validation failure.
_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.STALE_REVISION: 409,
    ErrorCode.PROPOSAL_SUBMITTED: 409,
    ErrorCode.TURN_IN_PROGRESS: 409,
    ErrorCode.LOCK_NOT_HELD: 409,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.SPEECH_UNAVAILABLE: 503,
}


def status_for(error: DomainError) -> int:
    """The response status for a domain error.

    A rate limit (429) outranks a conflict (409), which outranks an upstream-unavailable failure
    (503), which outranks field validation (422): a caller must first wait, then reload, before
    fixing fields, before being told an upstream dependency (Speech) is down.
    """
    statuses = {_STATUS_BY_CODE.get(item.code, 422) for item in error.errors}
    for status in (429, 409, 503):
        if status in statuses:
            return status
    return 422


async def _domain_error(_: Request, exc: Exception) -> JSONResponse:
    error = cast(DomainError, exc)  # registered for DomainError only
    return JSONResponse(error.to_dict(), status_code=status_for(error))


async def _request_validation_error(_: Request, exc: Exception) -> JSONResponse:
    validation_error = cast(RequestValidationError, exc)  # registered for it only
    # FastAPI's default body echoes the input values; AD-12 gives field, code and message only.
    errors: dict[str, FieldError] = {}
    for item in validation_error.errors():
        field = _field_name(item)
        if field in errors:
            continue  # at most one error per field (AD-12)
        code = (
            ErrorCode.REQUIRED
            if item.get("type") == "missing"
            else ErrorCode.INVALID_VALUE
        )
        errors[field] = FieldError(
            field=field, code=code, message=str(item.get("msg", "Invalid value."))
        )
    return JSONResponse(error_body(errors.values()), status_code=422)


# Where FastAPI found the value, not part of the field's name.
_LOCATION_SOURCES = ("body", "query", "path", "header", "cookie")


def _field_name(item: Mapping[str, Any]) -> str:
    """The AD-12 field for a validation error; "request" when it isn't about one field."""
    location = list(item.get("loc", ()))
    if location and location[0] in _LOCATION_SOURCES:
        location = location[1:]
    # A body that isn't valid JSON is located by character offset, not by field.
    if item.get("type") == "json_invalid" or all(isinstance(p, int) for p in location):
        return "request"
    return ".".join(str(part) for part in location)


async def _sign_in_required(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(SIGN_IN_REQUIRED, status_code=401)


async def _throttled(_: Request, exc: Exception) -> JSONResponse:
    # Story 4.8: a dedicated 429 body carrying retry_after_seconds, never the AD-12 FieldError
    # shape (spec Boundaries -- FieldError has no room for it).
    error = cast(ThrottledError, exc)  # registered for ThrottledError only
    return JSONResponse(
        {
            "code": ErrorCode.RATE_LIMITED.value,
            "message": "Too many chat turns. Wait, then try again.",
            "retry_after_seconds": error.retry_after_seconds,
        },
        status_code=429,
    )


async def _proposal_not_found(_: Request, __: Exception) -> JSONResponse:
    # A plain body, not the AD-12 shape: a 404 here is neither a validation nor a write failure, and
    # the body must be identical whether the proposal is unowned or simply doesn't exist (FR13, NFR6).
    return JSONResponse({"detail": "Not found."}, status_code=404)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(SignInRequired, _sign_in_required)
    app.add_exception_handler(ProposalNotFoundError, _proposal_not_found)
    app.add_exception_handler(ThrottledError, _throttled)
    app.add_exception_handler(RequestValidationError, _request_validation_error)
