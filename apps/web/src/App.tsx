import { useMemo } from 'react';
import { CategoryPage } from './components/CategoryPage.tsx';
import { EngineIndicator } from './components/EngineIndicator.tsx';
import { JobsPanel } from './components/JobsPanel.tsx';
import { Sidebar } from './components/Sidebar.tsx';
import { StatusPage } from './components/StatusPage.tsx';
import { ToolPage } from './components/ToolPage.tsx';
import { updateYtdlp } from './engine-client/api.ts';
import { detectMode } from './engine-client/mode.ts';
import { useEngine } from './hooks/useEngine.ts';
import { useJobs } from './hooks/useJobs.ts';
import { useRoute } from './hooks/useRoute.ts';

export function App() {
  const mode = useMemo(() => detectMode(), []);
  const { state, recheck } = useEngine(mode);
  const token = mode.kind === 'engine' ? mode.token : null;
  const { jobs, add } = useJobs(token);
  const route = useRoute();
  const onUpdateYtdlp = token
    ? async () => {
        const result = await updateYtdlp(token);
        await recheck();
        return result.version;
      }
    : undefined;

  return (
    <div className="min-h-screen bg-zinc-100 text-zinc-900 dark:bg-zinc-950 dark:text-zinc-100">
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3">
          <a href="#/" className="text-lg font-semibold tracking-tight">
            Werkbank
          </a>
          <EngineIndicator state={state} />
        </div>
      </header>
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6 md:flex-row md:flex-wrap xl:flex-nowrap">
        <Sidebar route={route} />
        <main className="min-w-0 flex-1">
          {route.page === 'tool' ? (
            <ToolPage key={route.tool} toolId={route.tool} state={state} token={token} onJob={add} />
          ) : route.page === 'category' ? (
            <CategoryPage category={route.category} state={state} />
          ) : (
            <StatusPage state={state} onRecheck={recheck} onUpdateYtdlp={onUpdateYtdlp} />
          )}
        </main>
        <div className="md:w-full xl:w-auto">
          <JobsPanel jobs={jobs} token={token} />
        </div>
      </div>
      <footer className="mx-auto max-w-7xl px-4 pb-6 text-xs text-zinc-500">
        Build {__BUILD__.commit.slice(0, 7)} ({__BUILD__.branch}) · Files are never uploaded to a server.
      </footer>
    </div>
  );
}
