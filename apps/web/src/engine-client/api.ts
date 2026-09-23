// Typed calls to the engine's job API (engine/werkbank_engine/routes.py). Every call carries the
// bearer token; downloads go through fetch too, because a plain link cannot send the token.
import { engineFetch } from './health.ts';

export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled';

export interface JobSnapshot {
  id: string;
  tool: string;
  toolTitle: string;
  title: string;
  status: JobStatus;
  progress: number | null;
  message: string | null;
  notes: string[];
  error: string | null;
  outputs: Array<{ index: number; name: string; size: number }>;
  log: string[];
  createdAt: number;
  startedAt: number | null;
  finishedAt: number | null;
}

export type InputRef = { fileId: string } | { inbox: string } | { url: string };

export interface InboxFile {
  name: string;
  size: number;
  modified: number;
}

export const isFinished = (status: JobStatus) => status === 'done' || status === 'failed' || status === 'cancelled';

async function json<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export async function uploadFile(token: string, file: File): Promise<{ fileId: string; name: string }> {
  const response = await engineFetch(`/api/files?name=${encodeURIComponent(file.name)}`, token, {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: file,
  });
  return json(response);
}

export async function listInbox(token: string): Promise<{ folder: string; files: InboxFile[] }> {
  return json(await engineFetch('/api/inbox', token));
}

export async function createJob(
  token: string,
  tool: string,
  params: Record<string, unknown>,
  inputs: InputRef[],
): Promise<JobSnapshot> {
  const response = await engineFetch('/api/jobs', token, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tool, params, inputs }),
  });
  return json(response);
}

export async function listJobs(token: string): Promise<JobSnapshot[]> {
  return json(await engineFetch('/api/jobs', token));
}

export async function cancelJob(token: string, id: string): Promise<JobSnapshot> {
  return json(await engineFetch(`/api/jobs/${encodeURIComponent(id)}`, token, { method: 'DELETE' }));
}

export async function revealOutput(token: string, id: string, index: number): Promise<void> {
  await engineFetch(`/api/jobs/${encodeURIComponent(id)}/outputs/${index}/reveal`, token, { method: 'POST' });
}

export async function downloadOutput(token: string, id: string, index: number, name: string): Promise<void> {
  const response = await engineFetch(`/api/jobs/${encodeURIComponent(id)}/outputs/${index}`, token);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export async function updateYtdlp(token: string): Promise<{ version: string | null }> {
  return json(await engineFetch('/api/admin/update-ytdlp', token, { method: 'POST' }));
}

/** Splits a server-sent-events buffer into complete `data:` payloads and the unfinished rest. */
export function parseSse(buffer: string): { events: string[]; rest: string } {
  const blocks = buffer.replace(/\r\n/g, '\n').split('\n\n');
  const rest = blocks.pop() ?? '';
  const events = blocks
    .map((block) =>
      block
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trimStart())
        .join('\n'),
    )
    .filter((data) => data.length > 0);
  return { events, rest };
}

/** Follows a job's server-sent events (fetch, so the token can be sent) until it finishes. */
export async function followJob(
  token: string,
  id: string,
  onSnapshot: (job: JobSnapshot) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await engineFetch(`/api/jobs/${encodeURIComponent(id)}/events`, token, { signal });
  const reader = response.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { value, done } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    const { events, rest } = parseSse(buffer);
    buffer = rest;
    for (const data of events) onSnapshot(JSON.parse(data) as JobSnapshot);
  }
}
