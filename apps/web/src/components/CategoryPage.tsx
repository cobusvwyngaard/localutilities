import { categories, tools, type Category } from '@werkbank/shared';
import { availability } from '../engine-client/availability.ts';
import type { EngineState } from '../engine-client/indicator.ts';
import { hrefFor } from '../hooks/useRoute.ts';

export function CategoryPage({ category, state }: { category: Category; state: EngineState }) {
  const title = categories.find((c) => c.id === category)?.title ?? category;
  const list = tools.filter((t) => t.category === category);
  return (
    <section aria-labelledby="category-title" className="space-y-4">
      <h1 id="category-title" className="text-2xl font-semibold">
        {title}
      </h1>
      {list.length === 0 ? (
        <p className="rounded-lg border border-dashed border-zinc-300 p-6 text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
          No tools here yet. They are added phase by phase (see DESIGN.md §9).
        </p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {list.map((t) => {
            const ok = availability(t, state).ok;
            return (
              <li key={t.id}>
                <a
                  href={hrefFor({ page: 'tool', tool: t.id })}
                  className="block h-full rounded-lg border border-zinc-200 bg-white p-4 hover:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-600"
                >
                  <h2 className="font-medium">{t.title}</h2>
                  <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">{t.description}</p>
                  {!ok && <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">Needs the engine on your laptop</p>}
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
