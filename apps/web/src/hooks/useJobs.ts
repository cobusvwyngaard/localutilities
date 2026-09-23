import { useCallback, useEffect, useRef, useState } from 'react';
import { followJob, isFinished, listJobs, type JobSnapshot } from '../engine-client/api.ts';

/** The engine's jobs, newest first, each followed live until it finishes. */
export function useJobs(token: string | null): { jobs: JobSnapshot[]; add: (job: JobSnapshot) => void } {
  const [jobs, setJobs] = useState<JobSnapshot[]>([]);
  const followers = useRef(new Map<string, AbortController>());

  const upsert = useCallback((job: JobSnapshot) => {
    setJobs((previous) => {
      const index = previous.findIndex((j) => j.id === job.id);
      if (index === -1) return [job, ...previous];
      const next = [...previous];
      next[index] = job;
      return next;
    });
  }, []);

  const follow = useCallback(
    (job: JobSnapshot) => {
      const active = followers.current;
      if (!token || isFinished(job.status) || active.has(job.id)) return;
      const controller = new AbortController();
      active.set(job.id, controller);
      followJob(token, job.id, upsert, controller.signal)
        .catch(() => {
          // The engine stopped or the page is closing; the engine indicator reports it.
        })
        .finally(() => active.delete(job.id));
    },
    [token, upsert],
  );

  useEffect(() => {
    if (!token) return;
    const active = followers.current;
    listJobs(token).then(
      (list) => {
        setJobs(list);
        list.forEach(follow);
      },
      () => {},
    );
    return () => {
      active.forEach((controller) => controller.abort());
      active.clear();
    };
  }, [token, follow]);

  const add = useCallback(
    (job: JobSnapshot) => {
      upsert(job);
      follow(job);
    },
    [upsert, follow],
  );
  return { jobs, add };
}
