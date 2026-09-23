import { missingRequired, type HealthReport } from './health.ts';

export type EngineState =
  | { kind: 'browser-only' }
  | { kind: 'connecting' }
  | { kind: 'connected'; health: HealthReport }
  | { kind: 'unreachable' }
  | { kind: 'unauthorised' };

export type Tone = 'green' | 'grey' | 'red';

export interface Indicator {
  tone: Tone;
  symbol: '🟢' | '⚪' | '🔴';
  label: string;
  description: string;
}

/** The header indicator (DESIGN.md §7): 🟢 connected · ⚪ browser-only · 🔴 dependency missing. */
export function indicatorFor(state: EngineState): Indicator {
  switch (state.kind) {
    case 'browser-only':
      return {
        tone: 'grey',
        symbol: '⚪',
        label: 'Browser only',
        description: 'Tools run inside this browser. Engine tools need Werkbank running on your laptop.',
      };
    case 'connecting':
      return { tone: 'grey', symbol: '⚪', label: 'Connecting…', description: 'Contacting the local engine.' };
    case 'unreachable':
      return {
        tone: 'grey',
        symbol: '⚪',
        label: 'Engine not reachable',
        description: 'The local engine stopped responding. Start Werkbank again, then reload this page.',
      };
    case 'unauthorised':
      return {
        tone: 'red',
        symbol: '🔴',
        label: 'Engine refused access',
        description: 'The engine did not accept this page’s token. Reload the page.',
      };
    case 'connected': {
      const missing = missingRequired(state.health);
      if (missing.length === 0) {
        return {
          tone: 'green',
          symbol: '🟢',
          label: `Engine ${state.health.engine.version}`,
          description: 'Connected to the Werkbank engine on this computer.',
        };
      }
      return {
        tone: 'red',
        symbol: '🔴',
        label: `Engine: ${missing.length === 1 ? `${missing[0].name} missing` : `${missing.length} dependencies missing`}`,
        description: `Missing: ${missing.map((d) => d.name).join(', ')}. See the status page for how to fix it.`,
      };
    }
  }
}
