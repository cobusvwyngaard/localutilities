"""DESIGN.md §10 security tests: wrong token, foreign Origin, foreign Host, non-local clients."""

from __future__ import annotations

import re

from starlette.testclient import TestClient

from werkbank_engine.config import Settings
from werkbank_engine.main import api
from werkbank_engine.security import require_api_access

HOSTED = "https://localutilities.cobus-w.workers.dev"


def test_health_needs_the_token(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_wrong_token_is_rejected(client: TestClient, settings: Settings) -> None:
    for value in (f"Bearer {settings.token}x", f"Basic {settings.token}", settings.token, "Bearer "):
        assert client.get("/api/health", headers={"Authorization": value}).status_code == 401


def test_correct_token_is_accepted(client: TestClient, auth: dict[str, str]) -> None:
    r = client.get("/api/health", headers=auth)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-store"


def test_foreign_origin_is_rejected(client: TestClient, auth: dict[str, str]) -> None:
    for origin in (
        "https://evil.example",
        "null",
        "http://127.0.0.1:9999",
        "https://localutilities.pages.dev",
    ):
        r = client.get("/api/health", headers={**auth, "Origin": origin})
        assert r.status_code == 403, origin
        assert "access-control-allow-origin" not in r.headers


def test_allowed_origins_get_cors_headers(client: TestClient, auth: dict[str, str]) -> None:
    for origin in ("http://127.0.0.1:8765", "http://localhost:8765", HOSTED):
        r = client.get("/api/health", headers={**auth, "Origin": origin})
        assert r.status_code == 200, origin
        assert r.headers["access-control-allow-origin"] == origin


def test_state_changing_request_without_origin_is_rejected(client: TestClient, auth: dict[str, str]) -> None:
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        r = client.request(method, "/api/health", headers=auth)
        assert r.status_code == 403, method
        assert "Origin" in r.text


def test_foreign_host_is_rejected_everywhere(client: TestClient, auth: dict[str, str]) -> None:
    # DNS rebinding: an attacker's domain resolving to 127.0.0.1 sends its own Host header.
    for path in ("/api/health", "/", "/assets/index-abc123.js"):
        for host in ("evil.example:8765", "127.0.0.1:9999", "127.0.0.1", "0.0.0.0:8765"):
            r = client.get(path, headers={**auth, "Host": host})
            assert r.status_code == 403, (path, host)
            assert "werkbank-token" not in r.text


def test_non_loopback_client_is_rejected(settings: Settings, client: TestClient) -> None:
    remote = TestClient(client.app, base_url="http://127.0.0.1:8765", client=("192.168.1.20", 5555))
    r = remote.get("/", headers={"Authorization": f"Bearer {settings.token}"})
    assert r.status_code == 403
    assert "werkbank-token" not in r.text


def test_preflight_from_allowed_origin(client: TestClient) -> None:
    r = client.options(
        "/api/health",
        headers={
            "Origin": HOSTED,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == HOSTED
    assert "authorization" in r.headers["access-control-allow-headers"]
    assert r.headers["access-control-allow-private-network"] == "true"


def test_preflight_from_foreign_origin(client: TestClient) -> None:
    r = client.options(
        "/api/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"}
    )
    assert r.status_code == 403
    assert "access-control-allow-origin" not in r.headers


def test_security_headers_on_every_response(client: TestClient, auth: dict[str, str]) -> None:
    for path in ("/", "/api/health", "/assets/index-abc123.js"):
        r = client.get(path, headers=auth)
        assert r.headers["x-frame-options"] == "DENY", path
        assert "frame-ancestors 'none'" in r.headers["content-security-policy"], path
        assert r.headers["x-content-type-options"] == "nosniff", path


def test_every_api_operation_requires_the_token(client: TestClient) -> None:
    # Behavioural check over every operation FastAPI knows about, however it was registered.
    paths = client.app.openapi()["paths"]
    assert paths, "expected at least one API operation"
    for path, operations in paths.items():
        assert path.startswith("/api/"), f"{path}: API routes must live under /api"
        url = re.sub(r"\{[^}]+\}", "x", path)
        for method in operations:
            r = client.request(method.upper(), url, headers={"Origin": "http://127.0.0.1:8765"})
            assert r.status_code == 401, f"{method.upper()} {path} answered {r.status_code} without a token"


def test_api_router_carries_the_shared_dependency() -> None:
    assert any(d.dependency is require_api_access for d in api.dependencies)
