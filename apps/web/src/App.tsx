import { useMemo } from 'react';
import { CategoryPage } from './components/CategoryPage.tsx';
import { EngineIndicator } from './components/EngineIndicator.tsx';
import { Sidebar } from './components/Sidebar.tsx';
import { StatusPage } from './components/StatusPage.tsx';
import { detectMode } from './engine-client/mode.ts';
import { useEngine } from './hooks/useEngine.ts';
import { useRoute } from './hooks/useRoute.ts';

export function App() {
  const mode = useMemo(() => detectMode(), []);
  const { state, recheck } = useEngine(mode);
  const route = useRoute();

  return (
    <div className="min-h-screen bg-zinc-100 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <a href="#/" className="text-lg font-semibold tracking-tight">
            Werkbank
          </a>
          <EngineIndicator state={state} />
        </div>
      </header>
      <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6 md:flex-row">
        <Sidebar route={route} />
        <main className="min-w-0 flex-1">
          {route.page === 'category' ? (
            <CategoryPage category={route.category} />
          ) : (
            <StatusPage state={state} onRecheck={recheck} />
          )}
        </main>
      </div>
      <footer className="mx-auto max-w-6xl px-4 pb-6 text-xs text-zinc-500">
        Build {__BUILD__.commit.slice(0, 7)} ({__BUILD__.branch}) · Files are never uploaded to a server.
      </footer>
    </div>
  );
}
