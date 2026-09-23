import type { ToolDef } from '@werkbank/shared';
import type { DependencyStatus } from './health.ts';
import type { EngineState } from './indicator.ts';

export type Availability =
  | { ok: true }
  | { ok: false; reason: 'needs-engine' | 'engine-unavailable'; message: string }
  | { ok: false; reason: 'missing-dependency'; message: string; missing: DependencyStatus[] };

/** Whether a tool can run now, and if not, what the user can do about it (DESIGN.md §3.1). */
export function availability(tool: ToolDef, state: EngineState): Availability {
  if (!tool.runsIn.includes('engine')) return { ok: true };
  switch (state.kind) {
    case 'browser-only':
      return {
        ok: false,
        reason: 'needs-engine',
        message: 'This tool runs on the Werkbank engine. Start Werkbank on your laptop and open http://127.0.0.1:8765 there.',
      };
    case 'connecting':
      return { ok: false, reason: 'engine-unavailable', message: 'Connecting to the engine…' };
    case 'unreachable':
    case 'unauthorised':
      return { ok: false, reason: 'engine-unavailable', message: 'The engine is not reachable. Start Werkbank again, then reload this page.' };
    case 'connected': {
      const missing = state.health.dependencies.filter((d) => tool.requires.includes(d.id as never) && !d.available);
      if (missing.length === 0) return { ok: true };
      return {
        ok: false,
        reason: 'missing-dependency',
        message: `Needs ${missing.map((d) => d.name).join(' and ')}, which ${missing.length === 1 ? 'is' : 'are'} not installed.`,
        missing,
      };
    }
  }
}
