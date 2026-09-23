import { useState } from 'react';
import type { InputSpec } from '@werkbank/shared';
import { errorMessage, listInbox, type InboxFile } from '../engine-client/api.ts';
import { formatBytes } from '../format.ts';

export interface Selection {
  files: File[];
  inbox: string[];
  url: string;
}

export const emptySelection: Selection = { files: [], inbox: [], url: '' };

export function selectionCount(s: Selection): number {
  return s.files.length + s.inbox.length + (s.url.trim() ? 1 : 0);
}

export function accepts(spec: InputSpec, name: string): boolean {
  if (!spec.accept) return true;
  const dot = name.lastIndexOf('.');
  return dot !== -1 && spec.accept.includes(name.slice(dot).toLowerCase());
}

const button =
  'rounded-md border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800';

export function InputPicker({
  spec,
  token,
  value,
  disabled,
  onChange,
}: {
  spec: InputSpec;
  token: string | null;
  value: Selection;
  disabled: boolean;
  onChange: (s: Selection) => void;
}) {
  const [dragging, setDragging] = useState(false);
  const [warning, setWarning] = useState<string | null>(null);
  const [inbox, setInbox] = useState<{ folder: string; files: InboxFile[] } | null>(null);
  const room = spec.max - selectionCount(value);

  const addFiles = (list: FileList | File[]) => {
    const all = Array.from(list);
    const ok = all.filter((f) => accepts(spec, f.name));
    const rejected = all.length - ok.length;
    const taken = ok.slice(0, Math.max(0, room));
    const messages = [];
    if (rejected) messages.push(`${rejected} file${rejected === 1 ? ' is' : 's are'} not a supported type.`);
    if (ok.length > taken.length) messages.push(`At most ${spec.max} file${spec.max === 1 ? '' : 's'} per job.`);
    setWarning(messages.join(' ') || null);
    if (taken.length) onChange({ ...value, files: [...value.files, ...taken] });
  };

  const openInbox = async () => {
    if (!token) return;
    try {
      setInbox(await listInbox(token));
    } catch (error) {
      setWarning(errorMessage(error));
    }
  };

  if (spec.kinds.includes('url')) {
    return (
      <label htmlFor="input-url" className="block text-sm font-medium">
        Web address
        <input
          id="input-url"
          type="url"
          inputMode="url"
          placeholder="https://…"
          className="mt-1 block w-full rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950"
          value={value.url}
          disabled={disabled}
          onChange={(e) => onChange({ ...value, url: e.target.value })}
        />
      </label>
    );
  }

  const inboxChoices = inbox?.files.filter((f) => accepts(spec, f.name) && !value.inbox.includes(f.name)) ?? [];
  return (
    <div className="space-y-3">
      <div
        data-testid="drop-zone"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (!disabled) addFiles(e.dataTransfer.files);
        }}
        className={`rounded-lg border-2 border-dashed p-5 text-center text-sm ${
          dragging ? 'border-emerald-500 bg-emerald-50 dark:bg-emerald-950' : 'border-zinc-300 dark:border-zinc-700'
        }`}
      >
        <p>Drop files here, or</p>
        <div className="mt-2 flex flex-wrap justify-center gap-2">
          <label className={`${button} cursor-pointer ${disabled || room <= 0 ? 'pointer-events-none opacity-50' : ''}`}>
            Choose files
            <input
              type="file"
              className="sr-only"
              multiple={spec.max > 1}
              accept={spec.accept?.join(',')}
              disabled={disabled || room <= 0}
              onChange={(e) => {
                if (e.target.files) addFiles(e.target.files);
                e.target.value = '';
              }}
            />
          </label>
          <button type="button" className={button} disabled={disabled || !token} onClick={() => void openInbox()}>
            Choose from Inbox
          </button>
        </div>
        {spec.accept && <p className="mt-2 text-xs text-zinc-500">{spec.accept.join(' ')}</p>}
      </div>

      {inbox && (
        <div className="rounded-lg border border-zinc-200 p-3 text-sm dark:border-zinc-800" data-testid="inbox-list">
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="break-all text-xs text-zinc-500">Inbox: {inbox.folder}</span>
            <button type="button" className="text-xs underline" onClick={() => setInbox(null)}>
              Close
            </button>
          </div>
          {inboxChoices.length === 0 ? (
            <p className="text-zinc-500">No matching files in the Inbox. Copy files into that folder, then try again.</p>
          ) : (
            <ul className="max-h-48 space-y-1 overflow-y-auto">
              {inboxChoices.map((f) => (
                <li key={f.name}>
                  <button
                    type="button"
                    disabled={room <= 0}
                    className="w-full rounded px-2 py-1 text-left hover:bg-zinc-100 disabled:opacity-50 dark:hover:bg-zinc-800"
                    onClick={() => onChange({ ...value, inbox: [...value.inbox, f.name] })}
                  >
                    {f.name} <span className="text-zinc-500">({formatBytes(f.size)})</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {warning && <p className="text-sm text-amber-700 dark:text-amber-400">{warning}</p>}

      {selectionCount(value) > 0 && (
        <ul className="space-y-1 text-sm" aria-label="Selected files">
          {value.files.map((f, i) => (
            <li key={`f-${i}-${f.name}`} className="flex items-center justify-between gap-2">
              <span className="break-all">
                {f.name} <span className="text-zinc-500">({formatBytes(f.size)})</span>
              </span>
              <button
                type="button"
                className="text-xs underline"
                disabled={disabled}
                onClick={() => onChange({ ...value, files: value.files.filter((_, j) => j !== i) })}
              >
                Remove
              </button>
            </li>
          ))}
          {value.inbox.map((name) => (
            <li key={`i-${name}`} className="flex items-center justify-between gap-2">
              <span className="break-all">
                {name} <span className="text-zinc-500">(Inbox)</span>
              </span>
              <button
                type="button"
                className="text-xs underline"
                disabled={disabled}
                onClick={() => onChange({ ...value, inbox: value.inbox.filter((n) => n !== name) })}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
