// Placeholder shell for the Phase 0 deployment check. The real UI shell and
// engine indicator arrive with the rest of Phase 0 (DESIGN.md §9).
export function App() {
  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', maxWidth: 640, margin: '3rem auto', padding: '0 1rem' }}>
      <h1>Werkbank</h1>
      <p>⚪ Browser-only — no local engine connected.</p>
      <p style={{ color: '#666', fontSize: '0.875rem' }}>
        Build {__BUILD__.commit.slice(0, 7)} ({__BUILD__.branch}) · {__BUILD__.builtAt}
      </p>
    </main>
  );
}
