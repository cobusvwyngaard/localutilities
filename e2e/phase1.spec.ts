// Phase 1 acceptance (DESIGN.md §9), through the real UI and the real engine:
// live progress and a clean cancel, remux-first conversion, PDF unlock (both kinds), downloads.
import { existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { ENGINE_PORT, HOSTED_PORT, MEDIA_PORT } from '../playwright.config.ts';

const ENGINE = `http://127.0.0.1:${ENGINE_PORT}`;
const media = (name: string) => join(process.env.E2E_MEDIA!, name);
const outbox = () => join(process.env.E2E_WERKBANK_HOME!, 'folders', 'Outbox');

async function openTool(page: Page, id: string): Promise<void> {
  await page.goto(`${ENGINE}/#/tool/${id}`);
  await expect(page.getByTestId('engine-indicator')).toHaveAttribute('data-tone', 'green', { timeout: 30_000 });
}

/** The newest job card (jobs are listed newest first). */
const latestJob = (page: Page) => page.getByTestId('job').first();

test('convert: remux without quality loss, then download the result', async ({ page }) => {
  await openTool(page, 'video.convert');
  await page.locator('input[type=file]').setInputFiles(media('clip.mp4'));
  await page.getByLabel('Convert to').selectOption('mkv');
  await page.getByRole('button', { name: 'Start' }).click();

  const job = latestJob(page);
  await expect(job).toHaveAttribute('data-status', 'done', { timeout: 60_000 });
  await expect(job).toContainText('No quality loss: streams were copied, not re-encoded.');
  await expect(job).toContainText('clip (converted).mkv');

  const [download] = await Promise.all([page.waitForEvent('download'), job.getByRole('button', { name: 'Download' }).click()]);
  expect(download.suggestedFilename()).toBe('clip (converted).mkv');
});

test('compress: live progress, and cancel leaves nothing behind', async ({ page }) => {
  await openTool(page, 'video.compress');
  await page.locator('input[type=file]').setInputFiles(media('long.mp4'));
  await page.getByLabel('Preset').selectOption('archive');
  await page.getByRole('button', { name: 'Start' }).click();

  const job = latestJob(page);
  const bar = job.getByRole('progressbar');
  await expect(async () => {
    expect(Number(await bar.getAttribute('aria-valuenow'))).toBeGreaterThan(2);
  }).toPass({ timeout: 60_000 });
  const first = Number(await bar.getAttribute('aria-valuenow'));
  await expect(async () => {
    expect(Number(await bar.getAttribute('aria-valuenow'))).toBeGreaterThan(first);
  }).toPass({ timeout: 30_000 }); // it keeps moving without a reload: live updates

  await job.getByRole('button', { name: 'Cancel' }).click();
  await expect(job).toHaveAttribute('data-status', 'cancelled');
  const leftovers = existsSync(outbox()) ? readdirSync(outbox()).filter((f) => f.startsWith('long')) : [];
  expect(leftovers).toEqual([]);
});

test('PDF unlock: restrictions without a password, open password only when correct', async ({ page }) => {
  await openTool(page, 'pdf.unlock');
  await page.locator('input[type=file]').setInputFiles(media('restricted.pdf'));
  await page.getByRole('button', { name: 'Start' }).click();
  await expect(latestJob(page)).toHaveAttribute('data-status', 'done');
  await expect(latestJob(page)).toContainText('Removed the permissions (owner) password. No password was needed.');

  await page.locator('input[type=file]').setInputFiles(media('locked.pdf'));
  await page.getByRole('button', { name: 'Start' }).click();
  await expect(latestJob(page)).toHaveAttribute('data-status', 'failed');
  await expect(latestJob(page)).toContainText('open (user) password');

  await page.locator('input[type=file]').setInputFiles(media('locked.pdf'));
  await page.getByLabel(/Open password/).fill('wrong');
  await page.getByRole('button', { name: 'Start' }).click();
  await expect(latestJob(page)).toHaveAttribute('data-status', 'failed');
  await expect(latestJob(page)).toContainText('does not open this PDF');

  await page.locator('input[type=file]').setInputFiles(media('locked.pdf'));
  await page.getByLabel(/Open password/).fill('open-sesame');
  await page.getByRole('button', { name: 'Start' }).click();
  await expect(latestJob(page)).toHaveAttribute('data-status', 'done');
  await expect(latestJob(page)).toContainText('locked (unlocked).pdf');
  await expect(page.locator('body')).not.toContainText('open-sesame');
});

test('download: yt-dlp fetches a file from a web address', async ({ page }) => {
  await openTool(page, 'download.media');
  await page.getByLabel('Web address').fill(`http://127.0.0.1:${MEDIA_PORT}/clip.mp4`);
  await page.getByRole('button', { name: 'Start' }).click();
  await expect(latestJob(page)).toHaveAttribute('data-status', 'done', { timeout: 60_000 });
  await expect(latestJob(page)).toContainText('Downloaded 1 file.');
  await expect(latestJob(page)).toContainText('[clip].mp4');
});

test('the hosted site explains that tools need the engine', async ({ page }) => {
  await page.goto(`http://127.0.0.1:${HOSTED_PORT}/#/tool/video.compress`);
  await expect(page.getByTestId('tool-unavailable')).toContainText('Start Werkbank on your laptop');
  await expect(page.getByRole('button', { name: 'Start' })).toBeDisabled();
  await expect(page.getByRole('heading', { name: 'Jobs' })).toHaveCount(0);
});
