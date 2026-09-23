import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

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
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'version.json', source: JSON.stringify(build, null, 2) + '\n' });
    },
  };
}

export default defineConfig({
  plugins: [react(), versionFile()],
  define: {
    __BUILD__: JSON.stringify(build),
  },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8765' },
  },
});
