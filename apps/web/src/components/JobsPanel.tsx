import { useState } from 'react';
import {
  cancelJob,
  downloadOutput,
  errorMessage,
  isFinished,
  revealOutput,
  type JobSnapshot,
} from '../engine-client/api.ts';
import { formatBytes } from '../format.ts';

const STATUS: Record<JobSnapshot['status'], { label: string; className: string }> = {
  queued: { label: 'Waiting', className: 'bg-zinc-200 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200' },
  running: { label: 'Running', className: 'bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-100' },
  done: { label: 'Done', className: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100' },
  failed: { label: 'Failed', className: 'bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-100' },
  cancelled: { label: 'Cancelled', className: 'bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300' },
};

const small = 'rounded border border-zinc-300 px-2 py-0.5 text-xs hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800';

export function JobCard({ job, token }: { job: JobSnapshot; token: string }) {
  const [problem, setProblem] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);
  const status = STATUS[job.status];
  const percent = job.progress === null ? null : Math.round(job.progress * 100);
  const act = (action: () => Promise<unknown>) => {
    setProblem(null);
    action().catch((e: unknown) => setProblem(errorMessage(e)));
  };

  return (
    <li data-testid="job" data-status={job.status} className="space-y-2 rounded-lg border border-zinc-200 bg-white p-3 text-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">{job.toolTitle}</p>
          <p className="break-all text-zinc-600 dark:text-zinc-400">{job.title}</p>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${status.className}`}>{status.label}</span>
      </div>

      {!isFinished(job.status) && (
        <div>
          <div
            className="h-2 overflow-hidden rounded bg-zinc-200 dark:bg-zinc-800"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={percent ?? undefined}
            aria-label="Progress"
          >
            <div
              className={`h-full bg-sky-600 transition-[width] ${percent === null ? 'w-1/3 animate-pulse' : ''}`}
              style={percent === null ? undefined : { width: `${percent}%` }}
            />
          </div>
          <p className="mt-1 text-xs text-zinc-500">
            {job.message ?? (job.status === 'queued' ? 'Waiting for another job to finish' : 'Starting')}
            {percent !== null && ` — ${percent} %`}
          </p>
        </div>
      )}

      {job.notes.length > 0 && (
        <ul className="space-y-0.5 text-xs text-zinc-600 dark:text-zinc-400">
          {job.notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}

      {job.error && (
        <div className="text-xs">
          <p className="whitespace-pre-wrap text-red-700 dark:text-red-400">{job.error}</p>
          {job.log.length > 0 && (
            <button type="button" className="mt-1 underline" onClick={() => setShowLog((s) => !s)}>
              {showLog ? 'Hide details' : 'Details'}
            </button>
          )}
          {showLog && <pre className="mt-1 max-h-40 overflow-auto rounded bg-zinc-100 p-2 dark:bg-zinc-800">{job.log.join('\n')}</pre>}
        </div>
      )}

      {job.outputs.length > 0 && (
        <ul className="space-y-1">
          {job.outputs.map((o) => (
            <li key={o.index} className="flex flex-wrap items-center justify-between gap-2">
              <span className="min-w-0 break-all text-xs">
                {o.name} <span className="text-zinc-500">({formatBytes(o.size)})</span>
              </span>
              <span className="flex gap-1">
                <button type="button" className={small} onClick={() => act(() => downloadOutput(token, job.id, o.index, o.name))}>
                  Download
                </button>
                <button type="button" className={small} onClick={() => act(() => revealOutput(token, job.id, o.index))}>
                  Show in folder
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      {!isFinished(job.status) && (
        <button type="button" className={small} onClick={() => act(() => cancelJob(token, job.id))}>
          Cancel
        </button>
      )}
      {problem && <p className="text-xs text-red-700 dark:text-red-400">{problem}</p>}
    </li>
  );
}

export function JobsPanel({ jobs, token }: { jobs: JobSnapshot[]; token: string | null }) {
  if (!token) return null;
  const active = jobs.filter((j) => !isFinished(j.status)).length;
  return (
    <aside aria-labelledby="jobs-title" className="xl:w-80 xl:shrink-0">
      <h2 id="jobs-title" className="mb-2 text-lg font-semibold">
        Jobs {active > 0 && <span className="text-sm font-normal text-zinc-500">({active} active)</span>}
      </h2>
      {jobs.length === 0 ? (
        <p className="text-sm text-zinc-500">No jobs yet. Results are saved to your Outbox folder.</p>
      ) : (
        <ul className="space-y-2">
          {jobs.map((job) => (
            <JobCard key={job.id} job={job} token={token} />
          ))}
        </ul>
      )}
    </aside>
  );
}
