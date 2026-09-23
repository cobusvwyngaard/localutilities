// Mode A: the engine serves this page and injects its token into <head> (DESIGN.md §6.2).
// Mode B: the page comes from Cloudflare; there is no token, so the UI stays browser-only.
// Mode B never probes 127.0.0.1 on its own: that would trigger Chrome's Local Network Access
// prompt on every visit. Connecting Mode B to an engine is an explicit opt-in (phase 2).

export type PageMode = { kind: 'engine'; token: string } | { kind: 'browser' };

export function detectMode(doc: Document = document): PageMode {
  const token = doc.querySelector<HTMLMetaElement>('meta[name="werkbank-token"]')?.content?.trim();
  return token ? { kind: 'engine', token } : { kind: 'browser' };
}
