"""Serves the built web app with SPA fallback (Story 1.3) and asset caching (Story 1.4).

Any GET that no route answers, outside the reserved prefixes, returns the matching file from the
static folder, or index.html so the React router can handle the path. Unknown /api paths get a JSON
404, never index.html. The fallback hangs off the 404 handler rather than a catch-all route, so routes
added later always win, whatever order they are registered in.
"""

import re
from pathlib import Path, PurePosixPath
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, Response
from starlette.exceptions import HTTPException

# Paths the SPA never answers: the API, the MCP server, Container Apps auth and the probes.
RESERVED_PREFIXES = ("/api", "/mcp", "/.auth", "/healthz", "/readyz")

_SPA_METHODS = frozenset({"GET", "HEAD"})

# Vite names its build output assets/<name>-<content hash>.<ext>, so a changed file gets a new name
# and the old one can be cached for good (Story 1.4). Anything else, including index.html (which
# names those files), is revalidated on every use.
_HASHED_ASSETS_DIR = "assets"
_HASHED_NAME = re.compile(r"^[^/]+-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$")
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
_NO_CACHE = {"Cache-Control": "no-cache"}


def _is_reserved(path: str) -> bool:
    return any(
        path == prefix or path.startswith(prefix + "/") for prefix in RESERVED_PREFIXES
    )


def _find_file(root: Path, path: str) -> Path | None:
    relative = path.lstrip("/")
    if not relative:
        return None
    try:
        candidate = (root / relative).resolve()
        # resolve() collapses "..", so a path outside the static folder is refused.
        if candidate.is_relative_to(root) and candidate.is_file():
            return candidate
    except (ValueError, OSError):
        # A NUL byte or an over-long name: no such file.
        return None
    return None


def register_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve static files and index.html for GETs that match no route."""
    root = static_dir.resolve()

    async def not_found(request: Request, exc: Exception) -> Response:
        http_error = cast(HTTPException, exc)  # registered for HTTPException only
        path = request.url.path
        if (
            http_error.status_code == 404
            and request.method in _SPA_METHODS
            and not _is_reserved(path)
        ):
            index = root / "index.html"
            asset = _find_file(root, path)
            if asset is not None and asset != index:
                parts = asset.relative_to(root).parts
                hashed = (
                    len(parts) == 2
                    and parts[0] == _HASHED_ASSETS_DIR
                    and _HASHED_NAME.match(parts[1]) is not None
                )
                return FileResponse(asset, headers=_IMMUTABLE if hashed else _NO_CACHE)
            # A missing file (a name with an extension) is a 404, not the app; every other path
            # is a client-side route.
            if (asset == index or not PurePosixPath(path).suffix) and index.is_file():
                return FileResponse(index, headers=_NO_CACHE)
        return await http_exception_handler(request, http_error)

    app.add_exception_handler(HTTPException, not_found)
