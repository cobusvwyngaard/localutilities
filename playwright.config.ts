// End-to-end acceptance tests for the Phase 0 criteria (DESIGN.md §9):
//   Mode A — the UI served by the real engine shows 🟢 with dependency versions;
//   Mode B — the static build, served by Cloudflare's local runtime with the real wrangler.jsonc and
//            _headers, shows ⚪ and never contacts the laptop.
// Needs a built UI (`npm run build`), uv, FFmpeg and Deno. Run with `npm run e2e`.
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

export const ENGINE_PORT = 18765;
export const HOSTED_PORT = 18787;

// The config is evaluated in every worker too; keep one engine home for the whole run.
process.env.E2E_WERKBANK_HOME ??= mkdtempSync(join(tmpdir(), 'werkbank-e2e-'));
const home = process.env.E2E_WERKBANK_HOME;

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
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
      env: { ...process.env, WERKBANK_HOME: home, WERKBANK_FOLDERS: join(home, 'folders') },
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
