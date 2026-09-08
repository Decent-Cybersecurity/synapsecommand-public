#!/usr/bin/env node
/**
 * Write the generated schema-reference pages (and the worked-example data) to disk.
 *
 * Run by `npm run gen:schemas`, and by `npm run build` before Docusaurus starts — so a
 * deploy always renders the schemas as they are in the commit being deployed, never a page
 * somebody forgot to regenerate.
 *
 * The output is COMMITTED, deliberately. Generated-and-gitignored would make the drift check
 * meaningless (there would be nothing to drift) and would hide every schema change from code
 * review; the same argument the CDM makes for committing its golden files applies here, and
 * so does the same warning — read the diff, because a regenerated page is how a defect
 * becomes the documentation.
 */
import fs from 'node:fs';
import path from 'node:path';

import {buildGeneratedTree} from './lib/schema-to-mdx.mjs';
import {DOCS_DIR, FIXTURES_DIR, SCHEMAS_DIR} from './lib/paths.mjs';

/**
 * The page as it is on disk, or `null` if there is no page there.
 *
 * A read that handles ENOENT rather than an `existsSync` in front of a `readFileSync`: the
 * question "is it there?" and the act "read it" are ONE operation here, so nothing can change
 * between them (CodeQL `js/file-system-race`, which flagged the write below on 2026-09-08 —
 * "the file may have changed since it was checked"). `null` still means "no page yet", which
 * is what the `new` / `updated` line prints from, so the output is unchanged.
 */
function readIfPresent(target) {
  try {
    return fs.readFileSync(target, 'utf8');
  } catch (error) {
    if (error.code === 'ENOENT') return null;
    throw error;
  }
}

const tree = buildGeneratedTree({schemasDir: SCHEMAS_DIR, fixturesDir: FIXTURES_DIR});

let written = 0;
let unchanged = 0;
for (const [relative, contents] of Object.entries(tree)) {
  const target = path.resolve(DOCS_DIR, relative);
  fs.mkdirSync(path.dirname(target), {recursive: true});
  const current = readIfPresent(target);
  if (current === contents) {
    unchanged += 1;
    continue;
  }
  fs.writeFileSync(target, contents);
  written += 1;
  console.log(`  ${current === null ? 'new    ' : 'updated'}  ${relative}`);
}

console.log(
  `generate-schema-docs: ${written} written, ${unchanged} already current ` +
    `(${Object.keys(tree).length} files from ${path.relative(process.cwd(), SCHEMAS_DIR)})`,
);
