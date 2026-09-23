# ruff: noqa: S101 - a test script: assertions are the point
"""Smoke test for the unpacked portable app: start Werkbank.exe the way a user would (no PATH
changes, no uv), then drive the real API: health, a lossless convert, a compress, a PDF unlock,
a yt-dlp download from a local web server and, with --update-ytdlp, the yt-dlp self-update.

    uv run --project engine python scripts/portable/smoke.py build/portable/dist/Werkbank [--update-ytdlp]

Needs pikepdf (to make the test PDF), which the engine's development environment has.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pikepdf

EXE = ".exe" if sys.platform == "win32" else ""
BUNDLED = ("ffmpeg", "ffprobe", "deno", "yt-dlp")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Engine:
    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self.token = ""

    def request(self, method: str, path: str, body: bytes | None = None, content_type: str = "") -> dict:
        headers = {"Authorization": f"Bearer {self.token}", "Origin": self.base}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:  # noqa: S310 - fixed http://127.0.0.1
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise AssertionError(
                f"{method} {path}: {exc.code} {exc.read().decode(errors='replace')}"
            ) from None
        return json.loads(raw) if raw else {}

    def wait_until_serving(self, proc: subprocess.Popen, timeout: float = 120) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise AssertionError(f"Werkbank exited early with code {proc.returncode}")
            with contextlib.suppress(OSError), urllib.request.urlopen(self.base + "/", timeout=5) as resp:  # noqa: S310
                match = re.search(r'name="werkbank-token" content="([^"]+)"', resp.read().decode())
                if match:
                    self.token = match.group(1)
                    return
            time.sleep(0.5)
        raise AssertionError("Werkbank did not serve its UI in time")

    def upload(self, path: Path) -> str:
        return self.request("POST", f"/api/files?name={path.name}", path.read_bytes())["fileId"]

    def job(self, tool: str, inputs: list[dict], params: dict | None = None) -> dict:
        body = json.dumps({"tool": tool, "params": params or {}, "inputs": inputs}).encode()
        job = self.request("POST", "/api/jobs", body, "application/json")
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            job = self.request("GET", f"/api/jobs/{job['id']}")
            if job["status"] in ("done", "failed", "cancelled"):
                if job["status"] != "done":
                    raise AssertionError(f"{tool} {job['status']}: {job.get('error')}")
                print(f"  {tool}: done; {' | '.join(job.get('notes') or [])}")
                return job
            time.sleep(0.5)
        raise AssertionError(f"{tool} did not finish")


def make_media(ffmpeg: Path, folder: Path) -> Path:
    clip = folder / "clip.mp4"
    subprocess.run(  # noqa: S603 - fixed argument list
        [str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=4",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)],
        check=True,
    )  # fmt: skip
    return clip


def make_restricted_pdf(folder: Path) -> Path:
    path = folder / "restricted.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(
        path,
        encryption=pikepdf.Encryption(
            owner="owner-secret", user="", allow=pikepdf.Permissions(extract=False)
        ),
    )
    return path


@contextlib.contextmanager
def media_server(folder: Path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(folder))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def main() -> None:
    # Job notes contain non-ASCII text (e.g. "→"); a redirected Windows console defaults to cp1252.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("app_dir", type=Path)
    parser.add_argument(
        "--update-ytdlp", action="store_true", help="also run the yt-dlp self-update (internet)"
    )
    args = parser.parse_args()
    app_dir: Path = args.app_dir.resolve()
    exe = app_dir / f"Werkbank{EXE}"
    bin_dir = app_dir / "bin"

    tmp = Path(tempfile.mkdtemp(prefix="werkbank-smoke-"))
    port = free_port()
    # Only data locations are redirected; programs must come from the app's own bin folder.
    env = {k: v for k, v in os.environ.items() if not k.startswith("WERKBANK_")}
    env.update(
        WERKBANK_HOME=str(tmp / "home"),
        WERKBANK_FOLDERS=str(tmp / "folders"),
        WERKBANK_WORK=str(tmp / "work"),
    )
    # Nothing but the system folders on PATH (the engine must use its own bin folder).
    if sys.platform == "win32":
        system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
        env["PATH"] = os.pathsep.join([system_root, str(Path(system_root) / "System32")])
    else:
        env["PATH"] = "/usr/bin:/bin"

    engine = Engine(port)
    started = time.monotonic()
    proc = subprocess.Popen([str(exe), "--port", str(port), "--no-open"], env=env, cwd=tmp)  # noqa: S603
    try:
        engine.wait_until_serving(proc)
        print(f"Serving after {time.monotonic() - started:.1f} s")
        health = engine.request("GET", "/api/health?refresh=true")
        for dep in health["dependencies"]:
            mark = "OK" if dep["available"] else "--"
            where = f"{dep['path'] or ''} {dep['detail'] or ''}"
            print(f"  {dep['id']:<12} {mark} {dep['version'] or ''} {where}")
        assert health["status"] == "ok", health["status"]
        deps = {d["id"]: d for d in health["dependencies"]}
        for dep_id in BUNDLED:
            assert Path(deps[dep_id]["path"]).parent == bin_dir, (
                f"{dep_id} not from the bundle: {deps[dep_id]['path']}"
            )
        assert deps["pikepdf"]["available"], "pikepdf missing from the bundle"
        assert "standalone" in (deps["yt-dlp"]["detail"] or "")

        media = tmp / "media"
        media.mkdir()
        clip = make_media(bin_dir / f"ffmpeg{EXE}", media)
        converted = engine.job("video.convert", [{"fileId": engine.upload(clip)}], {"target": "mkv"})
        assert any("No quality loss" in n for n in converted["notes"]), converted["notes"]
        engine.job("video.compress", [{"fileId": engine.upload(clip)}], {"preset": "share"})
        engine.job("audio.convert", [{"fileId": engine.upload(clip)}], {"target": "mp3"})
        engine.job("pdf.unlock", [{"fileId": engine.upload(make_restricted_pdf(media))}])
        with media_server(media) as base:
            downloaded = engine.job("download.media", [{"url": f"{base}/clip.mp4"}])
        assert downloaded["outputs"], "download produced no file"

        if args.update_ytdlp:
            result = engine.request("POST", "/api/admin/update-ytdlp")
            print(f"  yt-dlp update: version {result['version']}; {result['output'].splitlines()[-1]}")
        print("Portable app smoke test: OK")
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=20)
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    main()
