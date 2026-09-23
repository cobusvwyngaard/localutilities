import { useSyncExternalStore } from 'react';
import { categories, tools, type Category } from '@werkbank/shared';

// Hash routes keep the static build host-agnostic: #/ (status), #/category/<id>, #/tool/<id>.
export type Route = { page: 'home' } | { page: 'category'; category: Category } | { page: 'tool'; tool: string };

export function parseRoute(hash: string): Route {
  const toolMatch = /^#\/tool\/([a-z0-9.-]+)$/.exec(hash);
  if (toolMatch && tools.some((t) => t.id === toolMatch[1])) return { page: 'tool', tool: toolMatch[1] };
  const match = /^#\/category\/([a-z]+)$/.exec(hash);
  const category = categories.find((c) => c.id === match?.[1]);
  return category ? { page: 'category', category: category.id } : { page: 'home' };
}

export function hrefFor(route: Route): string {
  if (route.page === 'tool') return `#/tool/${route.tool}`;
  return route.page === 'home' ? '#/' : `#/category/${route.category}`;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener('hashchange', onChange);
  return () => window.removeEventListener('hashchange', onChange);
}

export function useRoute(): Route {
  const hash = useSyncExternalStore(subscribe, () => window.location.hash);
  return parseRoute(hash);
}
