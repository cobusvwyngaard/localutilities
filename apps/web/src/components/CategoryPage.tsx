import { categories, tools, type Category } from '@werkbank/shared';

export function CategoryPage({ category }: { category: Category }) {
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
          {list.map((t) => (
            <li key={t.id} className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
              <h2 className="font-medium">{t.title}</h2>
              <p className="text-sm text-zinc-600 dark:text-zinc-400">{t.description}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
