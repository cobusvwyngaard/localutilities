from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from tests.conftest import FakeTools, make_prober
from werkbank_engine.config import ConfigError, Settings, load_settings
from werkbank_engine.procs import ProcessError, run_exec


def _env(tmp_path: Path) -> dict[str, str]:
    return {"WERKBANK_HOME": str(tmp_path / "home"), "WERKBANK_FOLDERS": str(tmp_path / "folders")}


def test_token_is_generated_once_and_kept(tmp_path: Path) -> None:
    first = load_settings(_env(tmp_path))
    second = load_settings(_env(tmp_path))
    assert len(first.token) >= 43  # 32 random bytes, base64url
    assert first.token == second.token
    data = json.loads(first.config_file.read_text(encoding="utf-8"))
    assert data["port"] == 8765
    assert data["hostedOrigins"] == ["https://localutilities.cobus-w.workers.dev"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_config_file_is_private(tmp_path: Path) -> None:
    settings = load_settings(_env(tmp_path))
    assert settings.config_file.stat().st_mode & 0o777 == 0o600


def test_broken_config_gives_a_clear_error(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="Fix or delete it"):
        load_settings(_env(tmp_path))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("token", "short"),
        ("port", 80),
        ("port", True),
        ("hostedOrigins", ["http://insecure.example"]),
        ("hostedOrigins", ["https://example.com/path"]),
        ("hostedOrigins", "https://example.com"),
    ],
)
def test_invalid_config_values_are_rejected(tmp_path: Path, key: str, value: object) -> None:
    settings = load_settings(_env(tmp_path))
    data = json.loads(settings.config_file.read_text(encoding="utf-8"))
    data[key] = value
    settings.config_file.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(_env(tmp_path))


def test_allowed_hosts_and_origins_follow_the_port(tmp_path: Path) -> None:
    settings = load_settings({**_env(tmp_path), "WERKBANK_PORT": "18765"})
    assert settings.allowed_hosts == {"127.0.0.1:18765", "localhost:18765"}
    assert "http://127.0.0.1:18765" in settings.allowed_origins


def test_index_gets_the_token(client: TestClient, settings: Settings) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert f'<meta name="werkbank-token" content="{settings.token}" />' in r.text
    assert r.headers["cache-control"] == "no-store"


def test_spa_routes_fall_back_to_index(client: TestClient) -> None:
    r = client.get("/pdf/unlock")
    assert r.status_code == 200
    assert "werkbank-token" in r.text


def test_assets_are_served_and_cached(client: TestClient) -> None:
    r = client.get("/assets/index-abc123.js")
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]
    assert client.get("/version.json").json() == {"commit": "local"}


def test_cloudflare_files_and_traversal_are_not_served(client: TestClient) -> None:
    assert "X-Test" not in client.get("/_headers").text
    # dist/../home/config.json exists in the fixture layout; it must never be served.
    for path in ("/..%2Fhome%2Fconfig.json", "/..%2F..%2Fetc%2Fpasswd", "/%2E%2E/home/config.json"):
        r = client.get(path)
        assert "hostedOrigins" not in r.text, path
        assert "root:" not in r.text, path


def test_unknown_api_path_is_json_404(client: TestClient, auth: dict[str, str]) -> None:
    r = client.get("/api/nope", headers=auth)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_ui_not_built_page(tmp_path: Path, settings: Settings, fake_tools: FakeTools) -> None:
    from dataclasses import replace

    from werkbank_engine.health import HealthService
    from werkbank_engine.main import create_app

    service = HealthService(settings, tool_count=0, prober=make_prober(fake_tools))
    app = create_app(replace(settings, web_dist=tmp_path / "missing"), health_service=service)
    with TestClient(app, base_url="http://127.0.0.1:8765", client=("127.0.0.1", 1)) as c:
        r = c.get("/")
    assert r.status_code == 503
    assert "npm run build -w apps/web" in r.text


def test_run_exec_uses_argument_lists(tmp_path: Path) -> None:
    import asyncio

    marker = tmp_path / "pwned"
    # A shell would run the second command; an argument list passes it through as text.
    result = asyncio.run(
        run_exec([sys.executable, "-c", "import sys; print(sys.argv[1])", f"x; touch {marker}"])
    )
    assert result.stdout.strip() == f"x; touch {marker}"
    assert not marker.exists()


def test_run_exec_reports_missing_programs_and_timeouts() -> None:
    import asyncio

    with pytest.raises(ProcessError, match="cannot start"):
        asyncio.run(run_exec(["definitely-not-a-real-program-xyz"]))
    with pytest.raises(ProcessError, match="did not finish"):
        asyncio.run(run_exec([sys.executable, "-c", "import time; time.sleep(5)"], limit_seconds=0.3))


def test_cancelled_run_kills_the_process(tmp_path: Path) -> None:
    import asyncio

    marker = tmp_path / "finished"
    code = f"import time, pathlib; time.sleep(2); pathlib.Path({str(marker)!r}).write_text('x')"

    async def scenario() -> None:
        task = asyncio.create_task(run_exec([sys.executable, "-c", code]))
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    import time

    time.sleep(2.5)
    assert not marker.exists(), "the child kept running after cancellation"
