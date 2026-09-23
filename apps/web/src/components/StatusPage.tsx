import { useState } from 'react';
import type { DependencyStatus, HealthReport } from '../engine-client/health.ts';
import { indicatorFor, type EngineState } from '../engine-client/indicator.ts';
import { formatBytes } from '../format.ts';

const card = 'rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900';

function ModeCard({ state }: { state: EngineState }) {
  const indicator = indicatorFor(state);
  const local = state.kind !== 'browser-only';
  return (
    <section className={card} aria-labelledby="mode-title">
      <h2 id="mode-title" className="flex items-center gap-2 text-lg font-semibold">
        <span aria-hidden="true">{indicator.symbol}</span>
        {local ? 'Local mode' : 'Browser-only mode'}
      </h2>
      {local ? (
        <p className="mt-2 text-sm text-zinc-700 dark:text-zinc-300">
          This page is served by the Werkbank engine on this computer. Files are processed here and never
          leave it.
        </p>
      ) : (
        <div className="mt-2 space-y-2 text-sm text-zinc-700 dark:text-zinc-300">
          <p>
            This page comes from Cloudflare, but nothing you process is uploaded: browser tools run inside
            this browser.
          </p>
          <p>
            Tools that need the engine (downloads, large videos, OCR) run on your laptop. Start Werkbank there
            and open <code className="rounded bg-zinc-100 px-1 dark:bg-zinc-800">http://127.0.0.1:8765</code>.
          </p>
        </div>
      )}
      {indicator.tone === 'red' || state.kind === 'unreachable' || state.kind === 'connecting' ? (
        <p className="mt-2 text-sm font-medium">{indicator.description}</p>
      ) : null}
    </section>
  );
}

function FixCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="flex items-center gap-2">
      <code className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs dark:bg-zinc-800">{command}</code>
      <button
        type="button"
        className="rounded border border-zinc-300 px-1.5 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
        onClick={() => {
          void navigator.clipboard?.writeText(command).then(() => setCopied(true));
        }}
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
    </span>
  );
}

function UpdateButton({ onUpdate }: { onUpdate: () => Promise<string | null> }) {
  const [state, setState] = useState<{ busy: boolean; message: string | null }>({ busy: false, message: null });
  return (
    <span className="flex flex-wrap items-center gap-2">
      <button
        type="button"
        disabled={state.busy}
        className="rounded border border-zinc-300 px-1.5 text-xs hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
        onClick={() => {
          setState({ busy: true, message: null });
          onUpdate().then(
            (version) => setState({ busy: false, message: version ? `Now ${version}` : 'Updated' }),
            (e: unknown) => setState({ busy: false, message: e instanceof Error ? e.message : String(e) }),
          );
        }}
      >
        {state.busy ? 'Updating…' : 'Update yt-dlp'}
      </button>
      {state.message && <span className="text-xs">{state.message}</span>}
    </span>
  );
}

function DependencyRow({ dep, onUpdateYtdlp }: { dep: DependencyStatus; onUpdateYtdlp?: () => Promise<string | null> }) {
  return (
    <li
      data-testid={`dep-${dep.id}`}
      data-available={dep.available}
      className="grid gap-x-4 gap-y-1 border-t border-zinc-200 py-2.5 text-sm sm:grid-cols-[10rem_14rem_1fr] dark:border-zinc-800"
    >
      <div className="font-medium">
        {dep.name}
        {dep.required && <span className="ml-1 text-xs font-normal text-zinc-500">required</span>}
      </div>
      <div>
        {dep.available ? (
          <span className="text-emerald-700 dark:text-emerald-400">✓ {dep.version ?? 'found'}</span>
        ) : (
          <span className={dep.required ? 'font-medium text-red-700 dark:text-red-400' : 'text-zinc-500'}>
            ✗ {dep.required ? 'Missing' : 'Not installed'}
          </span>
        )}
        {dep.detail && <div className="text-xs text-zinc-500">{dep.detail}</div>}
      </div>
      <div className="space-y-1 text-zinc-600 dark:text-zinc-400">
        <div>{dep.neededFor}</div>
        {!dep.available && dep.fix ? <FixCommand command={dep.fix} /> : null}
        {dep.id === 'yt-dlp' && dep.available && onUpdateYtdlp ? <UpdateButton onUpdate={onUpdateYtdlp} /> : null}
      </div>
    </li>
  );
}

function EngineDetails({
  health,
  onRecheck,
  onUpdateYtdlp,
}: {
  health: HealthReport;
  onRecheck: () => Promise<void>;
  onUpdateYtdlp?: () => Promise<string | null>;
}) {
  const [busy, setBusy] = useState(false);
  const { listed, usable, checking } = health.hardwareEncoders;
  return (
    <>
      <section className={card} aria-labelledby="deps-title">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="deps-title" className="text-lg font-semibold">
            Dependencies
          </h2>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              void onRecheck().finally(() => setBusy(false));
            }}
            className="rounded-md border border-zinc-300 px-3 py-1 text-sm hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            {busy ? 'Checking…' : 'Check again'}
          </button>
        </div>
        <ul className="mt-3">
          {health.dependencies.map((d) => (
            <DependencyRow key={d.id} dep={d} onUpdateYtdlp={onUpdateYtdlp} />
          ))}
        </ul>
      </section>

      <section className={`${card} grid gap-4 text-sm sm:grid-cols-2`} aria-label="Engine details">
        <div>
          <h3 className="font-semibold">Engine</h3>
          <p className="text-zinc-600 dark:text-zinc-400">
            Version {health.engine.version} · Python {health.engine.python}
          </p>
          <p className="text-zinc-600 dark:text-zinc-400">{health.engine.platform}</p>
        </div>
        <div>
          <h3 className="font-semibold">Hardware video encoders</h3>
          <p className="text-zinc-600 dark:text-zinc-400">
            {checking
              ? 'Checking which ones work on this computer…'
              : usable.length > 0
                ? `Usable: ${usable.join(', ')}`
                : 'None usable — software encoding (slower, smaller files) will be used.'}
          </p>
          {!checking && listed.length > usable.length && (
            <p className="text-xs text-zinc-500">
              Built into FFmpeg but not usable on this hardware:{' '}
              {listed.filter((e) => !usable.includes(e)).join(', ')}
            </p>
          )}
        </div>
        <div>
          <h3 className="font-semibold">Folders</h3>
          <p className="break-all text-zinc-600 dark:text-zinc-400">Inbox: {health.folders.inbox}</p>
          <p className="break-all text-zinc-600 dark:text-zinc-400">Outbox: {health.folders.outbox}</p>
        </div>
        <div>
          <h3 className="font-semibold">Free disk space</h3>
          <p className="text-zinc-600 dark:text-zinc-400">
            {health.disk
              ? `${formatBytes(health.disk.freeBytes)} free of ${formatBytes(health.disk.totalBytes)}`
              : 'Unknown'}
          </p>
        </div>
        <div className="sm:col-span-2 text-xs text-zinc-500">
          {health.tools} tools installed · checked {new Date(health.checkedAt).toLocaleString('en-ZA')}
        </div>
      </section>
    </>
  );
}

export function StatusPage({
  state,
  onRecheck,
  onUpdateYtdlp,
}: {
  state: EngineState;
  onRecheck: () => Promise<void>;
  onUpdateYtdlp?: () => Promise<string | null>;
}) {
  return (
    <section aria-labelledby="status-title" className="space-y-4">
      <h1 id="status-title" className="text-2xl font-semibold">
        Status
      </h1>
      <ModeCard state={state} />
      {state.kind === 'connected' && (
        <EngineDetails health={state.health} onRecheck={onRecheck} onUpdateYtdlp={onUpdateYtdlp} />
      )}
    </section>
  );
}
