import type { EngineState } from '../engine-client/indicator.ts';
import { indicatorFor } from '../engine-client/indicator.ts';

const toneClasses = {
  green: 'border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950 dark:text-emerald-100',
  grey: 'border-zinc-300 bg-zinc-50 text-zinc-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200',
  red: 'border-red-300 bg-red-50 text-red-900 dark:border-red-800 dark:bg-red-950 dark:text-red-100',
} as const;

export function EngineIndicator({ state }: { state: EngineState }) {
  const indicator = indicatorFor(state);
  return (
    <a
      href="#/"
      data-testid="engine-indicator"
      data-tone={indicator.tone}
      title={indicator.description}
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-sm font-medium whitespace-nowrap ${toneClasses[indicator.tone]}`}
    >
      <span aria-hidden="true">{indicator.symbol}</span>
      <span>{indicator.label}</span>
    </a>
  );
}
