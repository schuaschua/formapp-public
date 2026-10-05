"""Liveness and readiness probes (spine AD-10, NFR22). Public: no sign-in needed."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.utils import suppress_instrumentation

from adapters.db.readiness import check_readiness

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """200 while the process is up; it never touches the database."""
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz(request: Request) -> JSONResponse:
    """200 only when the database is reachable, at the bundled head, and api isn't a migrator."""
    state = request.app.state
    # The probe runs every 10 seconds and isn't traced (Story 1.5); without this, each of its
    # database queries would be exported as a PostgreSQL dependency with no request.
    with suppress_instrumentation():
        readiness = await check_readiness(
            state.engine, state.expected_head, state.settings.db_migration_role
        )
    if readiness.ready:
        return JSONResponse({"status": "ready"})
    # The reason is logged, not returned: this endpoint is public.
    return JSONResponse({"status": "not_ready"}, status_code=503)
