import { describe, expect, it } from 'vitest';
import type { HealthReport } from '../src/engine-client/health.ts';
import { indicatorFor } from '../src/engine-client/indicator.ts';
import { detectMode } from '../src/engine-client/mode.ts';
import { formatBytes } from '../src/format.ts';
import { hrefFor, parseRoute } from '../src/hooks/useRoute.ts';

export function sampleHealth(overrides: Partial<HealthReport> = {}): HealthReport {
  return {
    status: 'ok',
    engine: { version: '0.1.0', python: '3.12.3', platform: 'Windows-11' },
    dependencies: [
      { id: 'ffmpeg', name: 'FFmpeg', required: true, available: true, version: '7.1.1', path: 'C:/x/ffmpeg.exe', neededFor: 'All audio and video tools', fix: null, detail: null },
      { id: 'deno', name: 'Deno', required: true, available: true, version: '2.9.6', path: 'C:/x/deno.exe', neededFor: 'YouTube downloads', fix: null, detail: null },
      { id: 'pandoc', name: 'Pandoc', required: false, available: false, version: null, path: null, neededFor: 'Markdown', fix: 'winget install --id JohnMacFarlane.Pandoc -e', detail: 'Not found on PATH' },
    ],
    hardwareEncoders: { listed: ['h264_nvenc', 'h264_qsv'], usable: ['h264_nvenc'] },
    disk: { path: 'C:/Users/x/Werkbank/Outbox', freeBytes: 120 * 1024 ** 3, totalBytes: 500 * 1024 ** 3 },
    folders: { inbox: 'C:/Users/x/Werkbank/Inbox', outbox: 'C:/Users/x/Werkbank/Outbox' },
    tools: 0,
    checkedAt: '2026-09-23T17:00:00Z',
    ...overrides,
  };
}

describe('detectMode', () => {
  it('is browser-only without the engine token', () => {
    document.head.innerHTML = '';
    expect(detectMode()).toEqual({ kind: 'browser' });
  });

  it('is engine mode when the engine injected its token', () => {
    document.head.innerHTML = '<meta name="werkbank-token" content="abc123" />';
    expect(detectMode()).toEqual({ kind: 'engine', token: 'abc123' });
  });

  it('ignores an empty token', () => {
    document.head.innerHTML = '<meta name="werkbank-token" content="  " />';
    expect(detectMode()).toEqual({ kind: 'browser' });
  });
});

describe('indicatorFor', () => {
  it('⚪ in browser-only mode', () => {
    expect(indicatorFor({ kind: 'browser-only' })).toMatchObject({ tone: 'grey', symbol: '⚪', label: 'Browser only' });
  });

  it('🟢 when all required dependencies are present', () => {
    const indicator = indicatorFor({ kind: 'connected', health: sampleHealth() });
    expect(indicator).toMatchObject({ tone: 'green', symbol: '🟢', label: 'Engine 0.1.0' });
  });

  it('🔴 naming the missing required dependency (optional ones do not count)', () => {
    const health = sampleHealth();
    health.dependencies[1] = { ...health.dependencies[1], available: false, version: null };
    const indicator = indicatorFor({ kind: 'connected', health });
    expect(indicator).toMatchObject({ tone: 'red', symbol: '🔴', label: 'Engine: Deno missing' });
  });

  it('🔴 with a count when several are missing', () => {
    const health = sampleHealth();
    health.dependencies = health.dependencies.map((d) => ({ ...d, available: false }));
    expect(indicatorFor({ kind: 'connected', health }).label).toBe('Engine: 2 dependencies missing');
  });

  it('explains an unreachable engine and a rejected token', () => {
    expect(indicatorFor({ kind: 'unreachable' }).tone).toBe('grey');
    expect(indicatorFor({ kind: 'unauthorised' }).tone).toBe('red');
  });
});

describe('routes', () => {
  it('round-trips category routes and falls back to the status page', () => {
    expect(parseRoute(hrefFor({ page: 'category', category: 'pdf' }))).toEqual({ page: 'category', category: 'pdf' });
    expect(parseRoute('#/category/nope')).toEqual({ page: 'home' });
    expect(parseRoute('')).toEqual({ page: 'home' });
  });
});

describe('formatBytes', () => {
  it('uses binary units', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(120 * 1024 ** 3)).toBe('120 GB');
    expect(formatBytes(-1)).toBe('—');
  });
});
