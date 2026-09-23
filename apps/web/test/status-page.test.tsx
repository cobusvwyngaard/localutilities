import { cleanup, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { EngineIndicator } from '../src/components/EngineIndicator.tsx';
import { StatusPage } from '../src/components/StatusPage.tsx';
import { sampleHealth } from './engine-client.test.ts';

afterEach(cleanup);
const noop = async () => {};

describe('StatusPage', () => {
  it('lists dependency versions and fix-it commands when connected', () => {
    render(<StatusPage state={{ kind: 'connected', health: sampleHealth() }} onRecheck={noop} />);
    expect(screen.getByText('Local mode')).toBeTruthy();
    const ffmpeg = screen.getByTestId('dep-ffmpeg');
    expect(within(ffmpeg).getByText('✓ 7.1.1')).toBeTruthy();
    const pandoc = screen.getByTestId('dep-pandoc');
    expect(within(pandoc).getByText('winget install --id JohnMacFarlane.Pandoc -e')).toBeTruthy();
    expect(screen.getByText('Usable: h264_nvenc')).toBeTruthy();
    expect(screen.getByText('120 GB free of 500 GB')).toBeTruthy();
  });

  it('says so while hardware encoders are still being tested', () => {
    const health = sampleHealth({ hardwareEncoders: { listed: [], usable: [], checking: true } });
    render(<StatusPage state={{ kind: 'connected', health }} onRecheck={noop} />);
    expect(screen.getByText('Checking which ones work on this computer…')).toBeTruthy();
  });

  it('explains browser-only mode without engine details', () => {
    render(<StatusPage state={{ kind: 'browser-only' }} onRecheck={noop} />);
    expect(screen.getByText('Browser-only mode')).toBeTruthy();
    expect(screen.queryByText('Dependencies')).toBeNull();
    const link = screen.getByRole('link', { name: 'Download Werkbank for Windows' });
    expect(link.getAttribute('href')).toBe(
      'https://github.com/cobusvwyngaard/localutilities/releases/latest/download/Werkbank-windows-x64.zip',
    );
  });

  it('does not offer the download when the page is served by the engine', () => {
    render(<StatusPage state={{ kind: 'connected', health: sampleHealth() }} onRecheck={noop} />);
    expect(screen.queryByRole('link', { name: 'Download Werkbank for Windows' })).toBeNull();
  });
});

describe('EngineIndicator', () => {
  it('exposes its tone for styling and tests', () => {
    render(<EngineIndicator state={{ kind: 'browser-only' }} />);
    expect(screen.getByTestId('engine-indicator').dataset.tone).toBe('grey');
  });
});
