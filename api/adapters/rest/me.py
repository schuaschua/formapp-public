"""``GET /api/me``: the signed-in agent's names for the web app's header (Story 1.6)."""

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from adapters.rest.principal import current_principal
from domain.principal import Principal

router = APIRouter()


@router.get("/api/me")
async def me(
    principal: Annotated[Principal, Depends(current_principal)],
) -> JSONResponse:
    """Her display name and first name; the oid never goes on the wire."""
    return JSONResponse(
        {"name": principal.name, "first_name": principal.first_name},
        # Personal to the signed-in agent: never cached, so sign-out takes effect at once.
        headers={"Cache-Control": "no-store"},
    )
