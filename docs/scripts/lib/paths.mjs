/**
 * Where things are, resolved from this file rather than from the working directory.
 *
 * `process.cwd()` is wrong here: these scripts are run from `docs/` by npm, from the repo
 * root by CI, and from wherever Cloudflare's build container happens to start. Resolving
 * against `import.meta.url` makes every path independent of all three.
 */
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));

/** `docs/` — the Docusaurus site root. */
export const SITE_DIR = path.resolve(HERE, '..', '..');

/** `docs/docs/` — where the MDX content lives. */
export const DOCS_DIR = path.join(SITE_DIR, 'docs');

/** The repository root, one level above the site. */
export const REPO_ROOT = path.resolve(SITE_DIR, '..');

/** `schemas/` at the repository root — the published contract, the input to the generator. */
export const SCHEMAS_DIR = path.join(REPO_ROOT, 'schemas');

/** The reference adapter's fixtures, source of the worked example. */
export const FIXTURES_DIR = path.join(
  REPO_ROOT,
  'packages',
  'cdm',
  'synapse_cdm',
  'fixtures',
  'pntmap',
);
