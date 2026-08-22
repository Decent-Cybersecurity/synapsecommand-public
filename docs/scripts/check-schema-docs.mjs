#!/usr/bin/env node
/**
 * The build check: fail if the committed schema-reference pages are stale.
 *
 * WHY THIS IS A CONTENT CHECK AND NOT A TIMESTAMP CHECK
 * ----------------------------------------------------
 * The obvious reading of "fail if /schemas is newer than the generated pages" is to compare
 * mtimes, and mtime is the one thing that cannot be trusted here: **git does not record
 * modification times.** A fresh clone — which is exactly what Cloudflare Pages and CI do —
 * stamps every file with the checkout time, in whatever order the checkout happened to touch
 * them. So an mtime gate on a clean build is a coin flip: it passes when nothing is stale and
 * it also passes when everything is, and the day it fires it will be on a build where nothing
 * changed at all.
 *
 * The property actually worth gating is "the pages on disk are what the generator produces
 * from the schemas on disk", which is decidable, identical in CI and on a laptop, and STRICTER
 * than the timestamp version: it catches a hand-edited page, a partially-committed
 * regeneration and a schema change with no regeneration, none of which an mtime notices.
 * It is the same gate the CDM already puts one level up — `python -m synapse_cdm.schemas
 * --check --out schemas` compares content, for the same reason.
 *
 * mtimes are still READ, and reported when there is drift: "schemas/entity.schema.json is
 * newer than the page" is the sentence that tells a developer which end to fix. It is a
 * diagnostic, never the verdict — and an mtime difference with identical content is a `touch`,
 * which must not fail a build.
 */
import fs from 'node:fs';
import path from 'node:path';

import {buildGeneratedTree} from './lib/schema-to-mdx.mjs';
import {DOCS_DIR, FIXTURES_DIR, REPO_ROOT, SCHEMAS_DIR} from './lib/paths.mjs';

const rel = (p) => path.relative(REPO_ROOT, p);

let tree;
try {
  tree = buildGeneratedTree({schemasDir: SCHEMAS_DIR, fixturesDir: FIXTURES_DIR});
} catch (error) {
  console.error(`check-schema-docs: cannot generate — ${error.message}`);
  process.exit(1);
}

const newestSchemaMtime = fs
  .readdirSync(SCHEMAS_DIR)
  .filter((f) => f.endsWith('.schema.json'))
  .map((f) => ({file: f, mtime: fs.statSync(path.join(SCHEMAS_DIR, f)).mtimeMs}))
  .sort((a, b) => b.mtime - a.mtime)[0];

const missing = [];
const differing = [];

for (const [relative, expected] of Object.entries(tree)) {
  const target = path.resolve(DOCS_DIR, relative);
  if (!fs.existsSync(target)) {
    missing.push(rel(target));
    continue;
  }
  const actual = fs.readFileSync(target, 'utf8');
  if (actual === expected) continue;

  const older = fs.statSync(target).mtimeMs < (newestSchemaMtime?.mtime ?? 0);
  differing.push({
    path: rel(target),
    firstDifference: describeFirstDifference(expected, actual),
    olderThanSchemas: older,
  });
}

if (missing.length === 0 && differing.length === 0) {
  console.log(
    `check-schema-docs: CURRENT — ${Object.keys(tree).length} generated files match the ` +
      `schemas in ${rel(SCHEMAS_DIR)}`,
  );
  process.exit(0);
}

console.error('check-schema-docs: STALE — the generated documentation does not match /schemas.\n');

if (missing.length) {
  console.error('  Never generated:');
  missing.forEach((p) => console.error(`    ${p}`));
  console.error('');
}

if (differing.length) {
  console.error('  Out of date:');
  differing.forEach(({path: p, firstDifference, olderThanSchemas}) => {
    console.error(`    ${p}`);
    console.error(`      ${firstDifference}`);
    if (olderThanSchemas && newestSchemaMtime) {
      console.error(
        `      (schemas/${newestSchemaMtime.file} is newer than this page on this checkout — ` +
          'a timestamp is only a hint, the content difference above is the verdict)',
      );
    }
  });
  console.error('');
}

console.error('  Fix, in order:');
console.error('    1. python -m synapse_cdm.schemas --check --out schemas   # are the schemas current?');
console.error('    2. cd docs && npm run gen:schemas                       # regenerate the pages');
console.error('    3. read the diff before committing it — a regenerated page is how a');
console.error('       defect becomes the documentation');
process.exit(1);

/** Name the first line that differs. A 400-line "files differ" tells nobody anything. */
function describeFirstDifference(expected, actual) {
  const e = expected.split('\n');
  const a = actual.split('\n');
  for (let i = 0; i < Math.max(e.length, a.length); i += 1) {
    if (e[i] === a[i]) continue;
    const show = (s) => (s === undefined ? '(end of file)' : JSON.stringify(s.slice(0, 110)));
    return `line ${i + 1}: on disk ${show(a[i])}, generator produces ${show(e[i])}`;
  }
  return `identical line-by-line but ${actual.length} vs ${expected.length} bytes (line endings?)`;
}
