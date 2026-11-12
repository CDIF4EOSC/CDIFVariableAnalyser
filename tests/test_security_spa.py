"""The /app SPA fallback serves files from frontend/dist only (issue #6)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ddicdi.api.main import create_app

INDEX = "<!doctype html><title>studio</title>"
SECRET = "TOP-SECRET-CONTENT"


@pytest.fixture()
def spa(tmp_path: Path) -> tuple[TestClient, Path]:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX)
    (dist / "favicon.svg").write_text("<svg/>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    secret = tmp_path / "secret.txt"
    secret.write_text(SECRET)
    (dist / "leak.txt").symlink_to(secret)  # a symlink inside dist that points out of it
    return TestClient(create_app(frontend_dist=dist)), secret


def test_legit_files_and_client_routes(spa):
    client, _ = spa
    assert client.get("/app/favicon.svg").text == "<svg/>"
    assert client.get("/app/assets/app.js").text == "console.log(1)"
    for route in ("/app", "/app/", "/app/files/abc/variables"):
        r = client.get(route)
        assert r.status_code == 200 and r.text == INDEX, route


def _attacks(secret: Path) -> list[str]:
    return [
        "/app/..%2fsecret.txt",
        "/app/%2e%2e/secret.txt",
        "/app/%2e%2e%2fsecret.txt",
        "/app/assets/..%2f..%2fsecret.txt",
        "/app//etc/hosts",
        "/app/%2Fetc%2Fhosts",
        "/app/%2F%2Fetc%2Fhosts",
        f"/app/{secret}",  # doubled slash: /app//tmp/.../secret.txt
        f"/app/%2F{str(secret).lstrip('/')}",
        "/app/leak.txt",
        "/app/%00",
        "/app/index.html%00.txt",
        "/app/..%00/secret.txt",
    ]


def test_traversal_and_absolute_paths_never_leave_dist(spa):
    client, secret = spa
    hosts = Path("/etc/hosts").read_text() if Path("/etc/hosts").is_file() else None
    for url in _attacks(secret):
        r = client.get(url)
        assert r.status_code in (200, 404), (url, r.status_code)
        assert SECRET not in r.text, url
        if hosts:
            assert r.text != hosts, url
        if r.status_code == 200:
            # The request reached the SPA handler and fell back to index.html.
            assert r.text == INDEX, url


def test_raw_dot_segments_in_asgi_path(spa):
    """Bypass the client's URL normalisation: hand the ASGI app a raw ``..`` path."""
    client, secret = spa
    for raw in ("/app/../secret.txt", "/app/assets/../../secret.txt", f"/app/{secret}"):
        r = client.request("GET", "http://testserver" + raw.replace("..", "%2e%2e"))
        assert SECRET not in r.text, raw
