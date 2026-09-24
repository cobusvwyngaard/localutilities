# Werkbank

Local-first utilities suite: media download, compression and conversion, PDF tools and more, with a
web interface. **Files are processed on your own machine and never uploaded.** See
[`DESIGN.md`](DESIGN.md) (the source of truth) and [`CLAUDE.md`](CLAUDE.md) (conventions).

Everything runs in a **portable Windows app** (nothing to install); the hosted site at
https://localutilities.cobus-w.workers.dev only shows the interface and the download link.

What it does (DESIGN.md §4.0):

- **Media:** download video/audio (yt-dlp), compress and convert video and audio (without
  re-encoding when possible).
- **Transcription:** speech in audio or video to TXT, SRT and VTT with Whisper (a fast model and an
  accurate one; English, Afrikaans and more).
- **PDF:** merge, split, select/reorder/delete pages, rotate, crop, pages per sheet and booklets,
  page numbers, watermarks, compress, protect (AES-256), unlock, remove metadata, redact, sign
  digitally, flatten forms, repair, OCR (English/Afrikaans), to images, from images, to text, tables
  to Excel/CSV, extract images and attachments, compare two PDFs, information report.
- Live progress, cancel, drag-and-drop, the Inbox/Outbox folders and a jobs list.

## Use it on Windows (Mode A) — nothing to install

1. Download **[Werkbank-windows-x64.zip](https://github.com/cobusvwyngaard/localutilities/releases/latest/download/Werkbank-windows-x64.zip)**
   (also linked from the hosted site's Status page).
2. Extract the whole zip to a folder in your user folder, e.g. `Documents\Werkbank`.
3. Double-click `Werkbank.exe`. A window opens that runs the engine, and your browser opens
   `http://127.0.0.1:8765`. Close that window to stop Werkbank.

No administrator rights, no installer, no PATH changes: the app contains its own Python, FFmpeg,
FFprobe, Deno, yt-dlp, whisper.cpp with two speech models, and Tesseract OCR (about 1 GB unpacked;
versions and SHA-256 pinned in
[`scripts/portable/programs.json`](scripts/portable/programs.json)). Windows SmartScreen may warn the
first time because the app is not code-signed: **More info → Run anyway** (no admin needed).

- **Update:** download the latest zip and replace the folder. yt-dlp updates itself from the Status
  page (sites such as YouTube change often); this needs the folder to be writable.
- **Results** are saved in the Outbox (never overwriting: ` (2)`, ` (3)` are added); big files can be
  put in the Inbox instead of being added through the browser.
- **Files and settings:** Inbox/Outbox in `%USERPROFILE%\Werkbank`; the engine's config (including
  its access token) in `%APPDATA%\Werkbank\config.json`. To remove Werkbank, delete its folder and
  these two.

CI builds the zip on every push ([`scripts/portable/build.py`](scripts/portable/build.py)), runs the
engine tests on Windows with the bundled programs, smoke-tests the unpacked app with nothing else on
PATH ([`smoke.py`](scripts/portable/smoke.py)), and on `main` publishes it as a GitHub release.

## Hosted UI (Mode B) and deployment

The static build of `apps/web` is served by an assets-only Cloudflare Worker
([`wrangler.jsonc`](wrangler.jsonc)). [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on
every push; on `main`, once every job passes and the portable app is released, it runs `npx wrangler deploy`
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
| Portable app | `npm run build`, then `uv run --project engine --group portable python scripts/portable/build.py` (Windows; `--local-programs` for a Linux test build), then `uv run --project engine python scripts/portable/smoke.py build/portable/dist/Werkbank` |
| Tool registry | `npm run gen:registry` after editing `packages/shared/src/tools.ts` (CI fails if `tools.json` is stale) |

## Layout

```
apps/web/          React UI (Vite, Tailwind), built for both modes
packages/shared/   tool registry (TypeScript) -> dist/tools.json for the engine
engine/            Python FastAPI engine (uv), 127.0.0.1 only
e2e/               Playwright acceptance tests
scripts/portable/  portable Windows app: build, pinned programs, smoke test
```
