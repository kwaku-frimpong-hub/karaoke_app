"""Tests for the single-image SPA serving (deployment, main.py)."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def _build_spa(tmp_path: Path) -> str:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>karaoke spa</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('hi')", encoding="utf-8")
    (dist / "manifest.webmanifest").write_text(
        '{"name":"karaoke"}', encoding="utf-8"
    )
    return str(dist)


def test_spa_serves_deep_links(tmp_path: Path) -> None:
    client = TestClient(create_app(static_dir=_build_spa(tmp_path)))

    # The root "/" is the M2 liveness endpoint (contract); the SPA is reached
    # through its routes, whose hard loads fall back to index.html.
    assert client.get("/").json()["status"] == "ok"
    assert client.get("/join/ABC123").text == "<html>karaoke spa</html>"
    assert client.get("/host/sessions/whatever").text == "<html>karaoke spa</html>"


def test_spa_serves_assets_and_root_files(tmp_path: Path) -> None:
    client = TestClient(create_app(static_dir=_build_spa(tmp_path)))

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert asset.text == "console.log('hi')"

    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.text == '{"name":"karaoke"}'


def test_spa_does_not_swallow_api_404s(tmp_path: Path) -> None:
    client = TestClient(create_app(static_dir=_build_spa(tmp_path)))

    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_spa_guards_against_path_traversal(tmp_path: Path) -> None:
    client = TestClient(create_app(static_dir=_build_spa(tmp_path)))

    # A traversal attempt must not escape the static dir (falls back to index).
    response = client.get("/%2e%2e/%2e%2e/etc/passwd")
    assert response.status_code == 200
    assert response.text == "<html>karaoke spa</html>"


def test_spa_disabled_without_static_dir() -> None:
    client = TestClient(create_app(static_dir=None))
    # Without a static dir there is no SPA fallback for deep links.
    assert client.get("/").status_code == 200  # liveness endpoint
    assert client.get("/join/ABC123").status_code == 404
