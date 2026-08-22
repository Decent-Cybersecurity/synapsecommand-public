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

const tree = buildGeneratedTree({schemasDir: SCHEMAS_DIR, fixturesDir: FIXTURES_DIR});

let written = 0;
let unchanged = 0;
for (const [relative, contents] of Object.entries(tree)) {
  const target = path.resolve(DOCS_DIR, relative);
  fs.mkdirSync(path.dirname(target), {recursive: true});
  const current = fs.existsSync(target) ? fs.readFileSync(target, 'utf8') : null;
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
