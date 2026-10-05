"""Story 1.3: the built web app is served with SPA fallback; unknown /api paths get JSON 404."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from adapters.rest.app import create_app
from tests.support import AS_AGENT_A, assert_web_security_headers, make_settings

INDEX = "<!doctype html><title>formapp</title><div id=root></div>"


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    build = tmp_path / "static"
    (build / "assets").mkdir(parents=True)
    (build / "index.html").write_text(INDEX)
    (build / "assets" / "index-C5nuqmFd.js").write_text("console.log('formapp')")
    (build / "assets" / "logo.svg").write_text("<svg/>")
    (build / "robots.txt").write_text("User-agent: *")
    (tmp_path / "secret.txt").write_text("outside the static folder")
    return build


@pytest.fixture
def client(static_dir: Path) -> Iterator[TestClient]:
    settings = make_settings(database_port=1, formapp_static_dir=static_dir)
    # Signed in, so /api paths reach routing; Story 1.6 covers the signed-out 401.
    with TestClient(create_app(settings), headers=AS_AGENT_A) as test_client:
        yield test_client


@pytest.mark.parametrize(
    "path", ["/", "/proposals/42", "/proposals/42/pages/3", "/welcome"]
)
def test_story_1_3_spa_routes_return_index_html(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"


def test_story_1_3_static_asset_is_served(client: TestClient) -> None:
    response = client.get("/assets/index-C5nuqmFd.js")

    assert response.status_code == 200
    assert response.text == "console.log('formapp')"


def test_story_1_3_unknown_api_path_is_json_404(client: TestClient) -> None:
    response = client.get("/api/nope")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert INDEX not in response.text


@pytest.mark.parametrize(
    "path", ["/api", "/mcp", "/mcp/tools", "/.auth/me", "/healthz/x", "/readyz/x"]
)
def test_story_1_3_reserved_paths_never_fall_back(
    client: TestClient, path: str
) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"


def test_story_1_3_path_traversal_stays_in_the_static_folder(
    client: TestClient,
) -> None:
    response = client.get("/..%2Fsecret.txt")

    assert "outside the static folder" not in response.text


@pytest.mark.parametrize("path", ["/assets/app-old.js", "/favicon.ico", "/docs/v1.2"])
def test_story_1_3_missing_file_with_an_extension_is_json_404(
    client: TestClient, path: str
) -> None:
    response = client.get(path)

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"
    assert INDEX not in response.text


def test_story_1_3_index_html_is_never_cached_on_any_route(client: TestClient) -> None:
    for path in ("/index.html", "/", "/proposals/42"):
        response = client.get(path)
        assert response.text == INDEX
        assert response.headers["cache-control"] == "no-cache", path


@pytest.mark.parametrize("path", ["/%00", "/assets/app%00.js", "/proposals/%00x"])
def test_story_1_3_nul_byte_path_is_not_a_server_error(
    client: TestClient, path: str
) -> None:
    response = client.get(path)

    assert response.status_code in (200, 404)
    assert "outside the static folder" not in response.text


def test_story_1_3_no_build_gives_json_404(tmp_path: Path) -> None:
    settings = make_settings(database_port=1, formapp_static_dir=tmp_path / "missing")

    with TestClient(create_app(settings)) as client:
        response = client.get("/proposals/42")

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/json"


def test_story_1_4_hashed_assets_are_cached_for_good(client: TestClient) -> None:
    response = client.get("/assets/index-C5nuqmFd.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


@pytest.mark.parametrize("path", ["/robots.txt", "/assets/logo.svg"])
def test_story_1_4_unhashed_files_are_revalidated(
    client: TestClient, path: str
) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("path", ["/", "/proposals/42", "/assets/index-C5nuqmFd.js"])
def test_story_1_4_web_app_responses_carry_the_security_headers(
    client: TestClient, path: str
) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert_web_security_headers(response.headers)
