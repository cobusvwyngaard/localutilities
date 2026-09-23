import { useCallback, useEffect, useRef, useState } from 'react';
import { EngineHttpError, fetchHealth } from '../engine-client/health.ts';
import type { EngineState } from '../engine-client/indicator.ts';
import type { PageMode } from '../engine-client/mode.ts';

const POLL_MS = 15_000;
const FOLLOW_UP_MS = 2_000; // while the engine is still testing hardware encoders

/** Tracks the engine's health while the page is open (Mode A only). */
export function useEngine(mode: PageMode): { state: EngineState; recheck: () => Promise<void> } {
  const token = mode.kind === 'engine' ? mode.token : null;
  const [state, setState] = useState<EngineState>(token ? { kind: 'connecting' } : { kind: 'browser-only' });
  const requestRef = useRef<(refresh: boolean) => Promise<void>>(async () => {});

  useEffect(() => {
    if (!token) return;
    let controller: AbortController | null = null;
    let followUp: number | undefined;

    // Only the latest request may update state; older ones are aborted.
    const request = (refresh: boolean): Promise<void> => {
      controller?.abort();
      const current = new AbortController();
      controller = current;
      return fetchHealth(token, refresh, current.signal).then(
        (health) => {
          if (current.signal.aborted) return;
          setState({ kind: 'connected', health });
          window.clearTimeout(followUp);
          if (health.hardwareEncoders.checking) followUp = window.setTimeout(() => void request(false), FOLLOW_UP_MS);
        },
        (error: unknown) => {
          if (current.signal.aborted) return;
          const unauthorised = error instanceof EngineHttpError && error.status === 401;
          setState(unauthorised ? { kind: 'unauthorised' } : { kind: 'unreachable' });
        },
      );
    };

    requestRef.current = request;
    void request(false);
    const timer = window.setInterval(() => void request(false), POLL_MS);
    const onFocus = () => void request(false);
    window.addEventListener('focus', onFocus);
    return () => {
      window.clearInterval(timer);
      window.clearTimeout(followUp);
      window.removeEventListener('focus', onFocus);
      controller?.abort();
    };
  }, [token]);

  const recheck = useCallback(() => requestRef.current(true), []);
  return { state, recheck };
}
