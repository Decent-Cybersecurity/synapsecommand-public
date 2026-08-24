#!/usr/bin/env node
/**
 * The build-output gate: no `:::` directive may reach a rendered page as literal text.
 *
 * WHY THIS EXISTS
 * ---------------
 * Every admonition on this site was broken for an unknown length of time and nobody noticed,
 * because nothing ever read the built HTML. All twelve `:::` directives across eleven pages
 * emitted as literal `:::note Source of truth` … `:::` paragraphs, and every gate the site had
 * was green throughout: `check:schemas` compares generated pages against the schemas, `tsc`
 * checks types, and `docusaurus build` exits 0 because a directive it cannot parse is not an
 * error — it is a paragraph.
 *
 * The cause was `future.v4: true`. That flag sets `mdx1CompatDisabledByDefault`, which turns off
 * the preprocessor that rewrote the MDX-v1 title form `:::note Title` into the directive-label
 * form `:::note[Title]` that `remark-directive` actually requires. The repair was to write the
 * twelve directives in the form the parser wants, rather than to switch the compatibility shim
 * back on — the shim is removed in Docusaurus v4, so that fix would have expired and the defect
 * would have come back at the upgrade with nothing watching for it.
 *
 * THIS is what watches for it. It is a build-OUTPUT check on purpose: a source-side lint would
 * have to re-implement the parser's opinion about what a valid directive is, and being wrong
 * about that is the whole defect. Asking the rendered page is the only question with no second
 * opinion in it.
 *
 * TWO DIRECTIONS, because the failure has two shapes
 * --------------------------------------------------
 *   1. a directive rendering as LITERAL TEXT — the shape that actually happened;
 *   2. a directive VANISHING — rendering as neither an admonition nor visible text, which a
 *      literal-text scan alone would call a pass.
 *
 * So the source directives are counted too, and the built admonitions must match that count.
 * The expected number is DERIVED from the sources rather than hardcoded, so adding a thirteenth
 * admonition does not require editing this file — only breaking one does.
 *
 * WHAT IS EXCLUDED, AND HOW
 * -------------------------
 * A page that documents directive syntax would legitimately contain `:::` inside a code block.
 * There is no such page today — checked, and stated here rather than assumed — but a docs site
 * acquires one eventually, so `<pre>` blocks are stripped before the scan. That is the narrowest
 * exclusion that covers the real case: Docusaurus renders every fenced code block inside `<pre>`,
 * and prose never is.
 */
import fs from 'node:fs';
import path from 'node:path';

import {DOCS_DIR, SITE_DIR} from './lib/paths.mjs';

const BUILD_DIR = path.join(SITE_DIR, 'build');

/** Every `.html` under `build/`. */
function builtPages(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...builtPages(full));
    else if (entry.name.endsWith('.html')) out.push(full);
  }
  return out;
}

/** Every `.mdx` under `docs/`, including the generated reference pages. */
function sourcePages(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, {withFileTypes: true})) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sourcePages(full));
    else if (entry.name.endsWith('.mdx') || entry.name.endsWith('.md')) out.push(full);
  }
  return out;
}

/** Code blocks are the one place `:::` is legitimate. Docusaurus renders them inside `<pre>`. */
const stripCode = (html) => html.replace(/<pre[\s\S]*?<\/pre>/g, '');

if (!fs.existsSync(BUILD_DIR)) {
  console.error(
    'check-built-admonitions: build/ does not exist. This gate reads the RENDERED output, so ' +
      'it has to run after `npm run build` — that is its whole point.',
  );
  process.exit(1);
}

// ---------------------------------------------------------------- what the sources ask for
const OPENING = /^:::([a-z]+)(.*)$/;
let expected = 0;
const badSyntax = [];
for (const file of sourcePages(DOCS_DIR)) {
  const rel = path.relative(SITE_DIR, file);
  let inFence = false;
  for (const [i, line] of fs.readFileSync(file, 'utf8').split('\n').entries()) {
    if (line.trimStart().startsWith('```')) {
      inFence = !inFence;
      continue;
    }
    if (inFence || !line.startsWith(':::') || line.trim() === ':::') continue;
    const m = OPENING.exec(line);
    expected += 1;
    // Caught here as well as in the output, because the message can name the repair.
    if (m && m[2] !== '' && !m[2].startsWith('[')) {
      badSyntax.push(
        `${rel}:${i + 1}: ${line.trim()}\n      -> write it as :::${m[1]}[${m[2].trim()}]`,
      );
    }
  }
}

if (badSyntax.length) {
  console.error(
    `check-built-admonitions: ${badSyntax.length} directive(s) use the MDX-v1 bare-title form, ` +
      'which this site\'s `future.v4: true` config does not translate:\n    ' +
      badSyntax.join('\n    '),
  );
  process.exit(1);
}

// ---------------------------------------------------------------- what the output delivers
const literal = [];
let rendered = 0;
for (const page of builtPages(BUILD_DIR)) {
  const html = fs.readFileSync(page, 'utf8');
  // The TYPED class, one per admonition. `theme-admonition` alone double-counts: Docusaurus
  // emits `class="theme-admonition theme-admonition-note"`, and a `\b` boundary matches inside
  // the second one too — which is how the first version of this gate reported 24 for 12.
  rendered += (html.match(/theme-admonition-[a-z]+/g) ?? []).length;
  const prose = stripCode(html);
  if (prose.includes(':::')) {
    literal.push(path.relative(SITE_DIR, page));
  }
}

if (literal.length) {
  console.error(
    `check-built-admonitions: ${literal.length} rendered page(s) contain a literal ':::' outside ` +
      `a code block:\n    ${literal.join('\n    ')}\n` +
      '  A directive the parser did not recognise is not a build error — it is a paragraph. ' +
      'That is how every admonition on this site stayed broken silently.',
  );
  process.exit(1);
}

if (rendered !== expected) {
  console.error(
    `check-built-admonitions: the sources open ${expected} directive(s) and the build rendered ` +
      `${rendered} admonition(s). Nothing appeared as literal text, so the missing ones did not ` +
      'fail loudly — they vanished, which a literal-text scan alone would have called a pass.',
  );
  process.exit(1);
}

console.log(
  `check-built-admonitions: OK — ${expected} directives in the sources, ${rendered} admonitions ` +
    `rendered, 0 literal ':::' in ${builtPages(BUILD_DIR).length} built pages`,
);
