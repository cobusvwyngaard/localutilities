import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { ENGINE_PORT, HOSTED_PORT } from '../playwright.config.ts';

const ENGINE = `http://127.0.0.1:${ENGINE_PORT}`;
const HOSTED = `http://127.0.0.1:${HOSTED_PORT}`;

function engineToken(): string {
  const config = JSON.parse(readFileSync(join(process.env.E2E_WERKBANK_HOME!, 'config.json'), 'utf8'));
  return config.token as string;
}

/** Console errors include Content-Security-Policy violations. */
function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  page.on('pageerror', (error) => errors.push(String(error)));
  return errors;
}

test.describe('Mode A: UI served by the local engine', () => {
  test('shows 🟢 with dependency versions', async ({ page }) => {
    const errors = collectErrors(page);
    await page.goto(`${ENGINE}/`);

    const indicator = page.getByTestId('engine-indicator');
    await expect(indicator).toHaveAttribute('data-tone', 'green', { timeout: 30_000 });
    await expect(indicator).toContainText('🟢');
    await expect(indicator).toContainText(/Engine \d+\.\d+\.\d+/);
    await expect(page.getByRole('heading', { name: 'Local mode' })).toBeVisible();

    for (const id of ['ffmpeg', 'ffprobe', 'deno', 'yt-dlp', 'pikepdf']) {
      const row = page.getByTestId(`dep-${id}`);
      await expect(row).toHaveAttribute('data-available', 'true');
      await expect(row).toContainText(/✓ \S+/);
    }
    expect(errors).toEqual([]);
  });

  test('the API needs the token that only the engine-served page has', async ({ request }) => {
    expect((await request.get(`${ENGINE}/api/health`)).status()).toBe(401);
    const ok = await request.get(`${ENGINE}/api/health`, { headers: { Authorization: `Bearer ${engineToken()}` } });
    expect(ok.status()).toBe(200);
    expect((await ok.json()).status).toBe('ok');
  });

  test('refuses foreign Host headers (DNS rebinding) and foreign origins', async ({ request }) => {
    const rebinding = await request.get(`${ENGINE}/`, { headers: { Host: `evil.example:${ENGINE_PORT}` } });
    expect(rebinding.status()).toBe(403);
    expect(await rebinding.text()).not.toContain('werkbank-token');

    const foreign = await request.get(`${ENGINE}/api/health`, {
      headers: { Authorization: `Bearer ${engineToken()}`, Origin: 'https://evil.example' },
    });
    expect(foreign.status()).toBe(403);
  });
});

test.describe('Mode B: hosted static build (Cloudflare config)', () => {
  test('shows ⚪ and never contacts the laptop', async ({ page }) => {
    const loopback: string[] = [];
    page.on('request', (request) => {
      const port = new URL(request.url()).port;
      if (port === String(ENGINE_PORT) || port === '8765') loopback.push(request.url());
    });
    const errors = collectErrors(page);
    await page.goto(`${HOSTED}/`);

    const indicator = page.getByTestId('engine-indicator');
    await expect(indicator).toHaveAttribute('data-tone', 'grey');
    await expect(indicator).toContainText('⚪');
    await expect(indicator).toContainText('Browser only');
    await expect(page.getByRole('heading', { name: 'Browser-only mode' })).toBeVisible();

    await page.getByRole('link', { name: /^PDF/ }).click();
    await expect(page.getByRole('heading', { name: 'PDF' })).toBeVisible();
    await expect(page.getByText('No tools here yet.')).toBeVisible();

    await page.waitForTimeout(500);
    expect(loopback).toEqual([]);
    expect(errors).toEqual([]);
  });

  test('serves the security headers, SPA fallback and version.json', async ({ request }) => {
    const index = await request.get(`${HOSTED}/`);
    const headers = index.headers();
    expect(headers['content-security-policy']).toContain("frame-ancestors 'none'");
    expect(headers['x-frame-options']).toBe('DENY');
    expect(headers['x-content-type-options']).toBe('nosniff');
    expect(headers['cross-origin-embedder-policy']).toBeUndefined();
    expect(await index.text()).not.toContain('werkbank-token');

    const deepLink = await request.get(`${HOSTED}/some/deep/link`);
    expect(deepLink.status()).toBe(200);
    expect(await deepLink.text()).toContain('<div id="root">');

    const version = await request.get(`${HOSTED}/version.json`);
    expect(version.headers()['cache-control']).toContain('no-store');
    expect(await version.json()).toHaveProperty('commit');
  });
});
