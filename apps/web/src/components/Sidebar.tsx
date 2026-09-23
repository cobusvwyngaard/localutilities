import { categories, tools } from '@werkbank/shared';
import { hrefFor, type Route } from '../hooks/useRoute.ts';

export function Sidebar({ route }: { route: Route }) {
  const linkClass = (active: boolean) =>
    `flex items-center justify-between gap-3 rounded-md px-3 py-2 text-sm whitespace-nowrap ${
      active
        ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
        : 'text-zinc-700 hover:bg-zinc-200 dark:text-zinc-300 dark:hover:bg-zinc-800'
    }`;

  return (
    <nav aria-label="Categories" className="md:w-52 md:shrink-0">
      <ul className="flex gap-1 overflow-x-auto pb-1 md:flex-col md:overflow-visible md:pb-0">
        <li>
          <a href={hrefFor({ page: 'home' })} className={linkClass(route.page === 'home')}>
            Status
          </a>
        </li>
        {categories.map((c) => {
          const count = tools.filter((t) => t.category === c.id).length;
          const active = route.page === 'category' && route.category === c.id;
          return (
            <li key={c.id}>
              <a href={hrefFor({ page: 'category', category: c.id })} className={linkClass(active)}>
                <span>{c.title}</span>
                <span className="tabular-nums opacity-60">{count}</span>
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
