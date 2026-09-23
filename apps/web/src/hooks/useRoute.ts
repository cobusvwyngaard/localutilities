import { useSyncExternalStore } from 'react';
import { categories, type Category } from '@werkbank/shared';

// Hash routes keep the static build host-agnostic: #/ (status) and #/category/<id>.
export type Route = { page: 'home' } | { page: 'category'; category: Category };

export function parseRoute(hash: string): Route {
  const match = /^#\/category\/([a-z]+)$/.exec(hash);
  const category = categories.find((c) => c.id === match?.[1]);
  return category ? { page: 'category', category: category.id } : { page: 'home' };
}

export function hrefFor(route: Route): string {
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
