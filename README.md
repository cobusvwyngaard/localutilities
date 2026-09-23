# Werkbank

Local-first utilities suite. See [`DESIGN.md`](DESIGN.md) (source of truth) and [`CLAUDE.md`](CLAUDE.md) (conventions).

## Hosted UI (Mode B)

The static UI in `apps/web` is deployed to Cloudflare as an assets-only Worker
(Workers Static Assets, configured in [`wrangler.jsonc`](wrangler.jsonc)):

- **URL:** https://localutilities.cobus-w.workers.dev
- **Deploys:** automatically on every push to `main`, from GitHub Actions
  ([`.github/workflows/deploy.yml`](.github/workflows/deploy.yml)): `npm ci` → build → `npx wrangler deploy`
  → checks that the live `/version.json` shows the pushed commit. Other branches never deploy.
  Can also be run by hand from the Actions tab ("Deploy" → "Run workflow").
- **Needs:** repository secret `CLOUDFLARE_API_TOKEN` (Cloudflare API token, "Edit Cloudflare Workers" template)
- **Check what is live:** `/version.json` shows the commit and branch the deployment was built from

No file processing happens on Cloudflare; it only serves static files.

## Development

```sh
npm ci
npm run dev -w apps/web     # dev server, proxies /api to the engine on 127.0.0.1:8765
npm run build -w apps/web   # production build into apps/web/dist
```
