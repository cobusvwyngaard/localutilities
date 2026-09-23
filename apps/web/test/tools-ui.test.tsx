import { cleanup, render, screen, within } from '@testing-library/react';
import { tools } from '@werkbank/shared';
import { afterEach, describe, expect, it } from 'vitest';
import { JobCard } from '../src/components/JobsPanel.tsx';
import { accepts, selectionCount } from '../src/components/InputPicker.tsx';
import { defaultsFor } from '../src/components/ParamField.tsx';
import { ToolPage } from '../src/components/ToolPage.tsx';
import { parseSse, type JobSnapshot } from '../src/engine-client/api.ts';
import { availability } from '../src/engine-client/availability.ts';
import { sampleHealth } from './engine-client.test.ts';

afterEach(cleanup);
const tool = (id: string) => tools.find((t) => t.id === id)!;

describe('parseSse', () => {
  it('returns complete events and keeps the unfinished rest', () => {
    const { events, rest } = parseSse('data: {"a":1}\n\n: keep-alive\n\ndata: {"b"');
    expect(events).toEqual(['{"a":1}']);
    expect(rest).toBe('data: {"b"');
  });

  it('handles CRLF line endings', () => {
    expect(parseSse('data: x\r\n\r\n').events).toEqual(['x']);
  });
});

describe('availability', () => {
  it('engine tools need the engine in browser-only mode', () => {
    const result = availability(tool('video.compress'), { kind: 'browser-only' });
    expect(result.ok).toBe(false);
    expect(!result.ok && result.reason).toBe('needs-engine');
  });

  it('names the missing dependency with its fix', () => {
    const health = sampleHealth();
    health.dependencies[1] = { ...health.dependencies[1], available: false, fix: 'winget install --id DenoLand.Deno -e' };
    const result = availability(tool('download.media'), { kind: 'connected', health });
    expect(result.ok).toBe(false);
    if (!result.ok && result.reason === 'missing-dependency') {
      expect(result.missing.map((d) => d.id)).toEqual(['deno']);
    } else {
      throw new Error('expected a missing dependency');
    }
    // Other tools do not need Deno.
    expect(availability(tool('video.convert'), { kind: 'connected', health }).ok).toBe(true);
  });
});

describe('inputs and defaults', () => {
  it('filters by extension, case-insensitively', () => {
    const spec = tool('pdf.unlock').inputs;
    expect(accepts(spec, 'Report.PDF')).toBe(true);
    expect(accepts(spec, 'report.docx')).toBe(false);
    expect(accepts(spec, 'no-extension')).toBe(false);
  });

  it('counts files, Inbox names and a URL', () => {
    expect(selectionCount({ files: [new File(['x'], 'a.mp4')], inbox: ['b.mp4'], url: ' ' })).toBe(2);
  });

  it('starts every parameter at its registry default', () => {
    expect(defaultsFor(tool('video.compress'))).toEqual({ preset: 'balanced', targetMb: 25, hardware: false });
    expect(defaultsFor(tool('pdf.unlock'))).toEqual({ password: '' });
  });
});

describe('ToolPage', () => {
  it('explains browser-only mode and disables the form', () => {
    render(<ToolPage toolId="video.compress" state={{ kind: 'browser-only' }} token={null} onJob={() => {}} />);
    expect(screen.getByTestId('tool-unavailable').textContent).toContain('http://127.0.0.1:8765');
    expect((screen.getByRole('button', { name: 'Start' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows the password field as a password input for PDF unlock', () => {
    render(<ToolPage toolId="pdf.unlock" state={{ kind: 'connected', health: sampleHealth() }} token="t" onJob={() => {}} />);
    const field = screen.getByLabelText(/Open password/) as HTMLInputElement;
    expect(field.type).toBe('password');
    expect(screen.queryByTestId('tool-unavailable')).toBeNull();
  });

  it('the downloader asks for a web address instead of files', () => {
    render(<ToolPage toolId="download.media" state={{ kind: 'connected', health: sampleHealth() }} token="t" onJob={() => {}} />);
    expect(screen.getByLabelText('Web address')).toBeTruthy();
    expect(screen.queryByTestId('drop-zone')).toBeNull();
  });
});

function job(overrides: Partial<JobSnapshot>): JobSnapshot {
  return {
    id: 'j1',
    tool: 'video.convert',
    toolTitle: 'Convert video',
    title: 'lecture.mkv',
    status: 'running',
    progress: 0.42,
    message: 'Converting lecture.mkv',
    notes: [],
    error: null,
    outputs: [],
    log: [],
    createdAt: 0,
    startedAt: 0,
    finishedAt: null,
    ...overrides,
  };
}

describe('JobCard', () => {
  it('shows live progress and a cancel button while running', () => {
    render(<JobCard job={job({})} token="t" />);
    expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('42');
    expect(screen.getByText('Converting lecture.mkv — 42 %')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeTruthy();
  });

  it('shows notes and outputs when done', () => {
    const done = job({
      status: 'done',
      progress: 1,
      notes: ['lecture.mkv: No quality loss: streams were copied, not re-encoded.'],
      outputs: [{ index: 0, name: 'lecture (converted).mp4', size: 2_097_152 }],
    });
    render(<JobCard job={done} token="t" />);
    const card = screen.getByTestId('job');
    expect(card.dataset.status).toBe('done');
    expect(within(card).getByText(/No quality loss/)).toBeTruthy();
    expect(within(card).getByText('lecture (converted).mp4')).toBeTruthy();
    expect(within(card).getByRole('button', { name: 'Show in folder' })).toBeTruthy();
    expect(within(card).queryByRole('button', { name: 'Cancel' })).toBeNull();
  });
});
