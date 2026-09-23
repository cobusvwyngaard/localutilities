"""Serves the built UI (apps/web/dist) in Mode A, with the API token injected into index.html."""

from __future__ import annotations

import html

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from werkbank_engine import __version__
from werkbank_engine.config import Settings

# Cloudflare-only files and the template itself are never served directly.
_NOT_SERVED = frozenset({"index.html", "_headers", "_redirects"})

NOT_BUILT_PAGE = """<!doctype html>
<html lang="en-ZA"><head><meta charset="utf-8"><title>Werkbank</title></head>
<body><h1>Werkbank engine is running</h1>
<p>The user interface has not been built yet. In the repository folder, run:</p>
<pre>npm ci
npm run build -w apps/web</pre>
<p>then reload this page. (The portable app includes the built interface.)</p></body></html>
"""


def inject_engine_meta(index_html: str, token: str) -> str:
    meta = (
        f'<meta name="werkbank-token" content="{html.escape(token, quote=True)}" />'
        f'<meta name="werkbank-engine-version" content="{html.escape(__version__, quote=True)}" />'
    )
    head_end = index_html.find("</head>")
    if head_end == -1:
        raise ValueError("index.html has no </head>")
    return index_html[:head_end] + meta + index_html[head_end:]


class _ImmutableStaticFiles(StaticFiles):
    """Vite puts content hashes in /assets file names, so they can be cached for a year."""

    def file_response(self, *args, **kwargs) -> Response:
        response = super().file_response(*args, **kwargs)
        response.headers["cache-control"] = "public, max-age=31536000, immutable"
        return response


def mount_web_ui(app: FastAPI, settings: Settings) -> None:
    dist = settings.web_dist.resolve()
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", _ImmutableStaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def web_ui(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        if path:
            candidate = (dist / path).resolve()
            if candidate.is_relative_to(dist) and candidate.is_file() and candidate.name not in _NOT_SERVED:
                return FileResponse(candidate, headers={"cache-control": "no-cache"})
        index = dist / "index.html"
        if not index.is_file():
            return HTMLResponse(NOT_BUILT_PAGE, status_code=503, headers={"cache-control": "no-store"})
        page = inject_engine_meta(index.read_text(encoding="utf-8"), settings.token)
        return HTMLResponse(page, headers={"cache-control": "no-store"})
