/// <reference types="vitest/config" />
import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, type Plugin } from 'vite';

// Set by the CI that builds the deployment (GitHub Actions: GITHUB_*, Workers Builds: WORKERS_CI_*,
// Pages: CF_PAGES_*); absent locally.
const env = process.env;
const build = {
  commit: env.GITHUB_SHA ?? env.WORKERS_CI_COMMIT_SHA ?? env.CF_PAGES_COMMIT_SHA ?? 'local',
  branch: env.GITHUB_REF_NAME ?? env.WORKERS_CI_BRANCH ?? env.CF_PAGES_BRANCH ?? 'local',
  builtAt: new Date().toISOString(),
};

// Emits /version.json so a deployment can be checked against the commit it was built from.
function versionFile(): Plugin {
  return {
    name: 'werkbank-version-file',
    apply: 'build',
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'version.json', source: JSON.stringify(build, null, 2) + '\n' });
    },
  };
}

// Same location logic as engine/werkbank_engine/config.py (default_home).
function engineConfigFile(): string {
  if (env.WERKBANK_HOME) return join(env.WERKBANK_HOME, 'config.json');
  if (process.platform === 'win32') {
    return join(env.APPDATA ?? join(homedir(), 'AppData', 'Roaming'), 'Werkbank', 'config.json');
  }
  if (process.platform === 'darwin') return join(homedir(), 'Library', 'Application Support', 'Werkbank', 'config.json');
  return join(env.XDG_CONFIG_HOME ?? join(homedir(), '.config'), 'werkbank', 'config.json');
}

function readEngineConfig(): { token: string; port: number } | null {
  try {
    const config = JSON.parse(readFileSync(engineConfigFile(), 'utf8')) as { token?: unknown; port?: unknown };
    if (typeof config.token !== 'string') return null;
    const port = Number(env.WERKBANK_PORT ?? config.port ?? 8765);
    return { token: config.token, port };
  } catch {
    return null;
  }
}

// `npm run dev` only: inject the local engine's token, as the engine does when it serves the UI.
function devEngineToken(): Plugin {
  return {
    name: 'werkbank-dev-engine-token',
    apply: 'serve',
    transformIndexHtml() {
      const config = readEngineConfig();
      return config ? [{ tag: 'meta', attrs: { name: 'werkbank-token', content: config.token }, injectTo: 'head' }] : [];
    },
  };
}

const enginePort = readEngineConfig()?.port ?? 8765;
const engineOrigin = `http://127.0.0.1:${enginePort}`;

export default defineConfig({
  plugins: [react(), tailwindcss(), versionFile(), devEngineToken()],
  define: {
    __BUILD__: JSON.stringify(build),
  },
  server: {
    proxy: {
      '/api': {
        target: engineOrigin,
        changeOrigin: true, // Host must be 127.0.0.1:<port> for the engine's DNS-rebinding check
        configure(proxy) {
          // The dev server's own origin stands in for the engine's; any other Origin passes through
          // unchanged, so the engine still rejects foreign sites.
          proxy.on('proxyReq', (proxyReq, req) => {
            const origin = req.headers.origin;
            if (origin && /^http:\/\/(localhost|127\.0\.0\.1):\d+$/.test(origin)) proxyReq.setHeader('origin', engineOrigin);
          });
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    include: ['test/**/*.test.{ts,tsx}'],
  },
});
