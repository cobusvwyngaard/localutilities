# CLAUDE.md — Werkbank

Read `DESIGN.md` before starting any task. It is the source of truth; if a request conflicts with it, say so before proceeding.

## What this is
A local-first utilities suite. React UI (`apps/web`) + Python FastAPI engine (`engine`) on `127.0.0.1:8765`. Cloudflare (an assets-only Worker, deployed from GitHub Actions on `main`) hosts only the static UI. No file is ever sent to a remote server.

## Non-negotiables
- **No cloud processing.** Never add a feature that uploads user files anywhere.
- **Subprocesses:** `asyncio.create_subprocess_exec` with argument lists only. Never `shell=True`, never string-built commands.
- **Engine binds to `127.0.0.1` only.** Every `/api/*` route checks bearer token, `Origin` allow-list and `Host` header (`engine/werkbank_engine/security.py`). New routes must use the shared dependency, not reimplement checks.
- **Validate every tool parameter** against the schema in `packages/shared` (enums and ranges). Unknown keys are rejected.
- **Client never supplies filesystem paths** — only file IDs, Inbox-relative names, or URLs.
- **Never commit binaries** (ffmpeg, WASM cores, ML models, test media > 1 MB).
- No PDF password cracking, no DRM removal.

## Conventions
- South African English in all UI text (colour, normalise, licence, organise).
- One tool = one registry entry in `packages/shared/src/tools.ts` + an engine module in `engine/werkbank_engine/tools/<id>.py` and/or a browser module in `apps/web/src/tools/<id>/`. Regenerate `tools.json` after registry changes (`npm run gen:registry`).
- Heavy browser work runs in a Web Worker; libraries lazy-loaded per tool.
- Prefer lossless paths first (stream copy / remux) and tell the user when no quality was lost.
- Outputs never overwrite: append ` (2)`, ` (3)`.
- Python: uv, ruff, pytest. TypeScript: strict mode, ESLint, Vitest, Playwright.

## Commands
- Engine dev: `cd engine && uv run uvicorn werkbank_engine.main:app --host 127.0.0.1 --port 8765 --reload` (on Windows leave out `--reload`: uvicorn's reload mode uses an event loop that cannot run subprocesses), or `uv run werkbank-engine`
- Web dev: `npm run dev -w apps/web` (proxies `/api` to the engine and injects the local engine's token)
- Tests: `cd engine && uv run pytest` (engine), `npm test` (web + registry), `npm run build && npm run e2e` (Playwright acceptance tests; need uv, FFmpeg, Deno)
- Lint/types: `npm run lint`, `npm run typecheck`, `cd engine && uv run ruff check . && uv run ruff format --check .`
- Build UI for engine to serve: `npm run build -w apps/web`
- Windows scripts (`scripts/*.ps1`, `*.cmd`) must stay ASCII-only and Windows PowerShell 5.1 compatible.
- The start scripts run `uv run --no-sync` (a sync would undo an in-app yt-dlp update); the installers sync from the lockfile and then update yt-dlp. After adding an engine dependency, users must re-run the installer.
- Engine tool modules: `engine/werkbank_engine/tools/<id with dots as underscores>.py` with `HEAVY` and `async def run(ctx)`, registered in `tools/__init__.py`; the engine refuses to start if a registry tool has no implementation.

## When adding a tool
1. Registry entry with params, `runsIn`, `browserLimitBytes`.
2. Engine implementation + pytest with a fixture file; snapshot the generated argument list.
3. Browser implementation if `runsIn` includes `browser`.
4. Health dependency declared, so the UI can disable the tool with a precise fix-it message when a dependency is missing.
5. Update the feature table in `DESIGN.md`.

## External dependency facts (verified Sept 2026 — re-check if something breaks)
- YouTube refuses cloud and CI addresses ("Sign in to confirm you're not a bot"): YouTube downloads can only be tested on a home connection.
- Ghostscript is not in winget (removed Sept 2025).
- yt-dlp needs Deno (or another supported JS runtime) plus `yt-dlp-ejs` for YouTube; keep yt-dlp current.
- Cloudflare static hosting (Workers Static Assets): 25 MiB per-file limit — load the ffmpeg.wasm core from a pinned CDN URL with SRI or from R2.
- Deployment: `.github/workflows/ci.yml` deploys `main` with `npx wrangler deploy` after all checks pass (secret `CLOUDFLARE_API_TOKEN`). Never deploy from any other branch.
- Chrome 142+ shows a Local Network Access prompt when the hosted page calls the engine; Safari blocks it entirely. Mode A (same-origin) avoids both.
- pdf-lib cannot decrypt PDFs; use pikepdf (engine) or a qpdf WASM build (browser).
