"""Story 1.3: /healthz is 200 while the process is up; it never needs the database."""

from fastapi.testclient import TestClient

from adapters.rest.app import create_app
from tests.support import make_settings


def test_story_1_3_healthz_200_without_a_database() -> None:
    # Port 1: nothing listens, so this proves liveness never touches PostgreSQL.
    with TestClient(create_app(make_settings(database_port=1))) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_story_1_3_no_openapi_or_docs_pages() -> None:
    with TestClient(create_app(make_settings(database_port=1))) as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404
