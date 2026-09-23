// Writes dist/tools.json, the registry the engine reads. Run with `npm run gen:registry`.
// `--check` fails instead of writing when the committed file is out of date (used in CI).
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { categories, dependencyIds, tools, validateRegistry } from '../src/index.ts';

const out = resolve(dirname(fileURLToPath(import.meta.url)), '../dist/tools.json');

const errors = validateRegistry(tools, categories);
if (errors.length > 0) {
  console.error(`Tool registry is invalid:\n  ${errors.join('\n  ')}`);
  process.exit(1);
}

const json = JSON.stringify({ schemaVersion: 1, categories, dependencyIds, tools }, null, 2) + '\n';

if (process.argv.includes('--check')) {
  let current = '';
  try {
    current = readFileSync(out, 'utf8');
  } catch {
    // missing file is reported below
  }
  if (current !== json) {
    console.error('packages/shared/dist/tools.json is out of date. Run `npm run gen:registry` and commit the result.');
    process.exit(1);
  }
  console.log('tools.json is up to date.');
} else {
  mkdirSync(dirname(out), { recursive: true });
  writeFileSync(out, json);
  console.log(`Wrote ${out} (${tools.length} tools).`);
}
