from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alfred.api import create_app
from alfred.db.session import Sessions

PAGE = "<!doctype html><title>Alfred</title>"


@pytest.fixture
def site(sessions: Sessions, tmp_path: Path) -> TestClient:
    """The API together with a built frontend: a page, an asset, and a secret next to it."""
    web = tmp_path / "dist"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text(PAGE)
    (web / "assets" / "app.js").write_text("console.log('alfred')")
    (tmp_path / "secret.txt").write_text("not part of the site")
    return TestClient(create_app(sessions, tmp_path / "uploads", web))


def test_the_frontend_and_its_files_are_served(site: TestClient) -> None:
    assert site.get("/").text == PAGE
    assert site.get("/assets/app.js").text == "console.log('alfred')"
    assert site.get("/api/health").json() == {"status": "ok"}  # the API still answers


def test_pages_that_exist_only_in_the_browser_get_the_app(site: TestClient) -> None:
    response = site.get("/courses/123/new")

    assert response.status_code == 200
    assert response.text == PAGE


def test_an_unknown_api_path_is_a_404_not_a_web_page(site: TestClient) -> None:
    response = site.get("/api/nope")

    assert response.status_code == 404
    assert PAGE not in response.text


def test_files_outside_the_frontend_folder_are_not_served(site: TestClient) -> None:
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
        assert "not part of the site" not in site.get(path).text


def test_without_a_built_frontend_only_the_api_is_served(client: TestClient) -> None:
    assert client.get("/").status_code == 404
    assert client.get("/api/health").status_code == 200
