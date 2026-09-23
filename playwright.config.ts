// End-to-end acceptance tests for the Phase 0 criteria (DESIGN.md §9):
//   Mode A — the UI served by the real engine shows 🟢 with dependency versions;
//   Mode B — the static build, served by Cloudflare's local runtime with the real wrangler.jsonc and
//            _headers, shows ⚪ and never contacts the laptop.
//   Phase 1 — the four tools through the real UI: live progress, cancel, remux, PDF unlock, download.
// Needs a built UI (`npm run build`), uv, FFmpeg and Deno. Run with `npm run e2e`.
import { mkdirSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

export const ENGINE_PORT = 18765;
export const HOSTED_PORT = 18787;
export const MEDIA_PORT = 18799;

// The config is evaluated in every worker too; keep one engine home for the whole run.
process.env.E2E_WERKBANK_HOME ??= mkdtempSync(join(tmpdir(), 'werkbank-e2e-'));
const home = process.env.E2E_WERKBANK_HOME;
process.env.E2E_MEDIA ??= join(home, 'media');
mkdirSync(process.env.E2E_MEDIA, { recursive: true });

export default defineConfig({
  testDir: 'e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: false, // the tests share one engine (one heavy job at a time)
  workers: 1,
  timeout: 120_000,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: {
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        // Lets a pre-installed Chromium be used where `playwright install` is not possible.
        launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined },
      },
    },
  ],
  webServer: [
    {
      command: `uv run --project engine --frozen werkbank-engine --port ${ENGINE_PORT}`,
      url: `http://127.0.0.1:${ENGINE_PORT}/`,
      env: { ...process.env, WERKBANK_HOME: home, WERKBANK_FOLDERS: join(home, 'folders'), WERKBANK_WORK: join(home, 'work') },
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      // A plain web server for the downloader test (yt-dlp's generic extractor).
      command: `uv run --project engine --frozen python -m http.server ${MEDIA_PORT} --bind 127.0.0.1 --directory "${process.env.E2E_MEDIA}"`,
      url: `http://127.0.0.1:${MEDIA_PORT}/`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `npx wrangler dev --ip 127.0.0.1 --port ${HOSTED_PORT}`,
      url: `http://127.0.0.1:${HOSTED_PORT}/`,
      env: { ...process.env, WRANGLER_SEND_METRICS: 'false' },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
