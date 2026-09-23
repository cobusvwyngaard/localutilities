import { useState } from 'react';
import { categories, tools } from '@werkbank/shared';
import { createJob, errorMessage, uploadFile, type InputRef, type JobSnapshot } from '../engine-client/api.ts';
import { availability } from '../engine-client/availability.ts';
import type { EngineState } from '../engine-client/indicator.ts';
import { hrefFor } from '../hooks/useRoute.ts';
import { emptySelection, InputPicker, selectionCount, type Selection } from './InputPicker.tsx';
import { defaultsFor, ParamField, type ParamValue } from './ParamField.tsx';

const card = 'rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900';

export function ToolPage({
  toolId,
  state,
  token,
  onJob,
}: {
  toolId: string;
  state: EngineState;
  token: string | null;
  onJob: (job: JobSnapshot) => void;
}) {
  const tool = tools.find((t) => t.id === toolId);
  const [params, setParams] = useState<Record<string, ParamValue>>(() => (tool ? defaultsFor(tool) : {}));
  const [selection, setSelection] = useState<Selection>(emptySelection);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!tool) return null;

  const available = availability(tool, state);
  const category = categories.find((c) => c.id === tool.category);
  const count = selectionCount(selection);
  const canStart = available.ok && !busy && token !== null && count >= tool.inputs.min && count <= tool.inputs.max;

  const start = async () => {
    if (!token) return;
    setError(null);
    try {
      const inputs: InputRef[] = [];
      for (const [i, file] of selection.files.entries()) {
        setBusy(`Adding ${file.name} (${i + 1} of ${selection.files.length})…`);
        inputs.push({ fileId: (await uploadFile(token, file)).fileId });
      }
      inputs.push(...selection.inbox.map((name) => ({ inbox: name })));
      if (selection.url.trim()) inputs.push({ url: selection.url.trim() });
      setBusy('Starting…');
      onJob(await createJob(token, tool.id, params, inputs));
      setSelection(emptySelection);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section aria-labelledby="tool-title" className="space-y-4">
      <div>
        {category && (
          <a href={hrefFor({ page: 'category', category: category.id })} className="text-sm text-zinc-500 hover:underline">
            {category.title}
          </a>
        )}
        <h1 id="tool-title" className="text-2xl font-semibold">
          {tool.title}
        </h1>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">{tool.description}</p>
      </div>

      {!available.ok && (
        <div
          role="status"
          data-testid="tool-unavailable"
          className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100"
        >
          <p>{available.message}</p>
          {available.reason === 'missing-dependency' && (
            <ul className="mt-2 space-y-1">
              {available.missing.map((d) => (
                <li key={d.id}>
                  {d.name}: <code className="rounded bg-white/60 px-1 dark:bg-black/30">{d.fix}</code>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <form
        className={`${card} space-y-4`}
        onSubmit={(e) => {
          e.preventDefault();
          void start();
        }}
      >
        <InputPicker spec={tool.inputs} token={token} value={selection} disabled={!available.ok || !!busy} onChange={setSelection} />
        <div className="grid gap-4 sm:grid-cols-2">
          {Object.entries(tool.params).map(([name, def]) => (
            <div key={name} className={def.type === 'enum' || def.type === 'text' ? 'sm:col-span-2' : ''}>
              <ParamField
                name={name}
                def={def}
                value={params[name]}
                disabled={!available.ok || !!busy}
                onChange={(v) => setParams((p) => ({ ...p, [name]: v }))}
              />
            </div>
          ))}
        </div>
        {error && (
          <p role="alert" className="text-sm text-red-700 dark:text-red-400">
            {error}
          </p>
        )}
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={!canStart}
            className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
          >
            Start
          </button>
          {busy && <span className="text-sm text-zinc-500">{busy}</span>}
        </div>
      </form>
    </section>
  );
}
