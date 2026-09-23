# Werkbank

Local-first utilities suite: media download, compression and conversion, PDF tools and more, with a
web interface. **Files are processed on your own machine and never uploaded.** See
[`DESIGN.md`](DESIGN.md) (the source of truth) and [`CLAUDE.md`](CLAUDE.md) (conventions).

Two ways to use the same UI:

| | Where the UI comes from | Where the work happens |
|---|---|---|
| **Mode A — local** (primary) | The engine on your laptop, `http://127.0.0.1:8765` | Native tools (FFmpeg, yt-dlp, pikepdf, …) |
| **Mode B — hosted** | https://localutilities.cobus-w.workers.dev | Inside the browser only |

Status: **Phase 1** — on the engine (Mode A): download video/audio (yt-dlp), compress video and audio,
convert video and audio (without re-encoding when possible) and unlock PDFs, with live progress, cancel,
drag-and-drop, the Inbox/Outbox folders and a jobs list. The hosted site (Mode B) shows the tools but
they need the engine until the browser versions arrive in Phase 2 (DESIGN.md §9).

## Install on Windows (Mode A)

In PowerShell:

```powershell
winget install --id Git.Git -e          # only if Git is not installed yet
git clone https://github.com/cobusvwyngaard/localutilities.git "$HOME\localutilities"
cd "$HOME\localutilities"
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

The installer uses winget to install whatever is missing of **uv**, **FFmpeg**, **Deno** and
**Node.js LTS** (Windows may ask for permission for Node.js), sets up the engine, builds the UI,
puts a **Werkbank** shortcut on the desktop and starts Werkbank. Your browser opens
`http://127.0.0.1:8765`; the header shows 🟢 when everything is in place, or 🔴 with the exact
command to fix a missing dependency.

- **Start:** the desktop shortcut (or `scripts\start.cmd`). Closing the engine window stops it.
- **Update:** `git pull`, then run `scripts\install.ps1` again. yt-dlp can also be updated on its own
  from the Status page (sites such as YouTube change often).
- **Results** are saved in the Outbox (never overwriting: ` (2)`, ` (3)` are added); big files can be
  put in the Inbox instead of being added through the browser.
- **Files and settings:** Inbox/Outbox in `%USERPROFILE%\Werkbank`; the engine's config (including
  its access token) in `%APPDATA%\Werkbank\config.json`.

macOS / Linux (Debian, Ubuntu): `scripts/install.sh`, then `scripts/start.sh`.

## Hosted UI (Mode B) and deployment

The static build of `apps/web` is served by an assets-only Cloudflare Worker
([`wrangler.jsonc`](wrangler.jsonc)). [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on
every push; on `main`, once the web, engine and end-to-end jobs pass, it runs `npx wrangler deploy`
and then checks that the live `/version.json` reports the pushed commit. No other branch deploys.

- Needs the repository secret `CLOUDFLARE_API_TOKEN` ("Edit Cloudflare Workers" API token).
- Redeploy by hand: Actions → CI → Run workflow (on `main`).
- What is live: https://localutilities.cobus-w.workers.dev/version.json

## Development

```sh
npm ci                                   # UI, registry, lint and e2e tooling
(cd engine && uv sync)                   # engine + dev tools
npm run build                            # build the UI the engine serves
(cd engine && uv run werkbank-engine)    # engine on http://127.0.0.1:8765
npm run dev -w apps/web                  # UI dev server; proxies /api to the engine
```

| Check | Command |
|---|---|
| Lint, types | `npm run lint`, `npm run typecheck`, `cd engine && uv run ruff check . && uv run ruff format --check .` |
| Unit tests | `npm test` (UI + registry), `cd engine && uv run pytest` |
| End-to-end | `npm run build && npm run e2e` (needs uv, FFmpeg and Deno on PATH) |
| Tool registry | `npm run gen:registry` after editing `packages/shared/src/tools.ts` (CI fails if `tools.json` is stale) |

## Layout

```
apps/web/          React UI (Vite, Tailwind), built for both modes
packages/shared/   tool registry (TypeScript) -> dist/tools.json for the engine
engine/            Python FastAPI engine (uv), 127.0.0.1 only
e2e/               Playwright acceptance tests
scripts/           install and start scripts (Windows, macOS/Linux)
```
