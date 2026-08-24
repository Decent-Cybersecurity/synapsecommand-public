/**
 * JSON Schema -> MDX. The documentation site's schema reference is GENERATED, never written.
 *
 * The reason is the same one that put `python -m synapse_cdm.schemas --check` in CI: a second
 * copy of a contract is allowed to exist only when something mechanical keeps it identical.
 * `schemas/*.schema.json` is already a publication of the Pydantic models; a hand-written
 * reference page would be a publication of a publication, and the failure mode is silent —
 * a Go consumer reads the documented shape, validates against the real schema, and gets a
 * rejection for a field the page said was optional.
 *
 * So this module is the only author of everything under `docs/schema-reference/`, and
 * `check-schema-docs.mjs` re-runs it into a temporary directory and diffs. Drift is a failed
 * build, not a stale page.
 *
 * WHAT IT DELIBERATELY DOES NOT DO
 * --------------------------------
 * It does not summarise, reorder or improve the schema's own words. Every description on
 * every page is the description in the schema, which is the docstring on the model. One
 * source, three renderings (Python, JSON Schema, MDX), and no editorial layer in between
 * where a claim could drift from the code.
 */
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

/** Human title and ordering for the six published schemas. Order is the reading order. */
const PAGES = [
  {file: 'cdm_object.schema.json', slug: 'cdm-object', title: 'CDMObject (the union)'},
  {file: 'entity.schema.json', slug: 'entity', title: 'Entity'},
  {file: 'event.schema.json', slug: 'event', title: 'Event'},
  {file: 'track.schema.json', slug: 'track', title: 'Track'},
  {file: 'plan_object.schema.json', slug: 'plan-object', title: 'PlanObject'},
  {
    file: 'payload_gnss_interference.schema.json',
    slug: 'payload-gnss-interference',
    title: 'GnssInterferencePayload',
  },
];

const BANNER =
  '{/* GENERATED FILE — DO NOT EDIT.\n' +
  '    Written by docs/scripts/generate-schema-docs.mjs from the JSON Schema named below.\n' +
  '    Edit the Pydantic model in packages/cdm/synapse_cdm/models.py, re-export with\n' +
  '    `python -m synapse_cdm.schemas --out schemas`, then re-run `npm run gen:schemas`. */}';

/**
 * Escape schema text for MDX, treating `inline code` spans differently from prose.
 *
 * The distinction is load-bearing and getting it wrong is visible on the page. In MDX v3,
 * `{` opens a JSX expression and `<` opens a tag — but NOT inside a code span, whose content
 * is literal. So escaping uniformly turns the published timestamp pattern
 * `^...T[0-9]{2}:...` into `[0-9]&#123;2&#125;` on screen, because a code span does not decode
 * HTML entities: the reader is shown the escape rather than the pattern they must implement.
 *
 * Therefore:
 *   - outside code, `{ } < >` are escaped as entities (they would otherwise be MDX syntax);
 *   - inside code, nothing is escaped except `|`, which breaks a GFM table cell even in a
 *     code span and whose `\|` form GFM renders as a literal pipe.
 *
 * `mode: 'cell'` additionally collapses whitespace, because a newline ends a table ROW and a
 * multi-line docstring would truncate the table at that point.
 */
function escapeMdx(text, {mode} = {mode: 'prose'}) {
  if (text === undefined || text === null) return '';
  let value = String(text);
  if (mode === 'cell') value = value.replace(/\s+/g, ' ').trim();

  // Split on backtick spans, keeping the delimiters, so the two rules can be applied to
  // alternating segments. Uneven backticks degrade to "treat the tail as prose", which is
  // the safe direction: over-escaping renders oddly, under-escaping fails the build.
  return value
    .split(/(`[^`]*`)/g)
    .map((segment) => {
      const isCode = segment.startsWith('`') && segment.endsWith('`') && segment.length > 1;
      if (isCode) return mode === 'cell' ? segment.replace(/\|/g, '\\|') : segment;
      let out = segment.replace(/\{/g, '&#123;').replace(/\}/g, '&#125;').replace(/</g, '&lt;');
      if (mode === 'cell') out = out.replace(/\|/g, '\\|').replace(/>/g, '&gt;');
      return out;
    })
    .join('');
}

const cell = (text) => escapeMdx(text, {mode: 'cell'});
const prose = (text) => escapeMdx(text, {mode: 'prose'});

const defName = (ref) => (ref || '').replace('#/$defs/', '');
const anchor = (name) => `#${name.toLowerCase()}`;

/**
 * Render a property's type as a readable expression, following `$ref` into a link.
 *
 * Emits RAW `|`, `<` and `>`: escaping is the caller's job via cell()/prose(), so the same
 * expression can be rendered into a table cell and into prose without two spellings of it.
 *
 * `anyOf: [X, {type: null}]` is how Pydantic spells an optional field, and it is rendered as
 * `X | null` rather than as "anyOf" because the null branch is the single most load-bearing
 * fact about a CDM field: absent means UNKNOWN, and a reader has to see which fields are
 * allowed to be absent without decoding JSON Schema keywords.
 */
function typeExpr(schema, {linkDefs = true} = {}) {
  if (!schema || typeof schema !== 'object') return '—';

  if (schema.$ref) {
    const name = defName(schema.$ref);
    return linkDefs ? `[${name}](${anchor(name)})` : name;
  }
  if (schema.const !== undefined) return `\`${JSON.stringify(schema.const)}\``;

  if (Array.isArray(schema.anyOf) || Array.isArray(schema.oneOf)) {
    const branches = schema.anyOf || schema.oneOf;
    return branches.map((b) => typeExpr(b, {linkDefs})).join(' | ');
  }
  if (Array.isArray(schema.allOf) && schema.allOf.length === 1) {
    return typeExpr(schema.allOf[0], {linkDefs});
  }
  if (Array.isArray(schema.enum)) return 'string (enum)';

  if (schema.type === 'array') {
    return `array<${schema.items ? typeExpr(schema.items, {linkDefs}) : 'any'}>`;
  }
  if (schema.type === 'object') {
    const values = schema.additionalProperties;
    if (values && typeof values === 'object') {
      return `object<string, ${typeExpr(values, {linkDefs})}>`;
    }
    return 'object';
  }
  if (schema.type === 'null') return 'null';
  if (Array.isArray(schema.type)) return schema.type.join(' | ');
  if (schema.type) {
    return schema.format ? `${schema.type} (${schema.format})` : schema.type;
  }
  return 'any';
}

/**
 * The constraints a consumer must actually honour, gathered from wherever they live.
 *
 * They are collected from the property AND from the non-null branches of an `anyOf`, because
 * Pydantic puts `ge`/`le` on the branch rather than on the optional field itself — so reading
 * only the top level reports "no constraints" for `confidence`, whose whole point is 0..1.
 */
function constraints(schema) {
  const out = [];
  const walk = (node) => {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node.enum)) out.push(`one of: ${node.enum.map((v) => `\`${v}\``).join(', ')}`);
    if (node.pattern) out.push(`pattern \`${node.pattern}\``);
    if (node.minimum !== undefined) out.push(`≥ ${node.minimum}`);
    if (node.maximum !== undefined) out.push(`≤ ${node.maximum}`);
    if (node.exclusiveMinimum !== undefined) out.push(`> ${node.exclusiveMinimum}`);
    if (node.exclusiveMaximum !== undefined) out.push(`< ${node.exclusiveMaximum}`);
    if (node.minLength !== undefined) out.push(`min length ${node.minLength}`);
    if (node.maxLength !== undefined) out.push(`max length ${node.maxLength}`);
    if (node.minItems !== undefined) out.push(`min items ${node.minItems}`);
    if (node.maxItems !== undefined) out.push(`max items ${node.maxItems}`);
    (node.anyOf || node.oneOf || node.allOf || []).forEach((branch) => {
      if (branch && branch.type !== 'null') walk(branch);
    });
  };
  walk(schema);
  return [...new Set(out)];
}

/**
 * One `| name | type | required | description |` row per property.
 *
 * The required column reads `yes` / `no` rather than a tick, because a tick and an empty cell
 * are indistinguishable to a screen reader and this table is the contract.
 */
function fieldTable(properties, required) {
  const names = Object.keys(properties || {});
  if (names.length === 0) return '_No properties — see the type expression above._\n';

  const req = new Set(required || []);
  const rows = names.sort().map((name) => {
    const spec = properties[name] || {};
    const notes = constraints(spec);
    const isConst = spec.const !== undefined;
    const description = [
      spec.description || '',
      spec.default !== undefined && !isConst ? `Default \`${JSON.stringify(spec.default)}\`.` : '',
      notes.length ? `(${notes.join('; ')})` : '',
    ]
      .filter(Boolean)
      .join(' ');
    return `| \`${name}\` | ${cell(typeExpr(spec))} | ${req.has(name) ? '**yes**' : 'no'} | ${cell(
      description,
    )} |`;
  });

  return [
    '| Field | Type | Required | Description |',
    '| --- | --- | --- | --- |',
    ...rows,
    '',
  ].join('\n');
}

/** A `$defs` entry gets the same treatment as a root object: prose, then its own table. */
function defSection(name, schema) {
  const lines = [`### ${name}`, ''];
  if (schema.description) lines.push(prose(schema.description), '');

  if (Array.isArray(schema.enum)) {
    lines.push('Closed vocabulary — a value outside this list is invalid, and `UNKNOWN` is a', '');
    lines.push('member rather than a null wherever the enum has one.', '');
    lines.push('| Value |', '| --- |', ...schema.enum.map((v) => `| \`${v}\` |`), '');
    return lines.join('\n');
  }
  if (schema.properties) {
    lines.push(fieldTable(schema.properties, schema.required));
    if (schema.additionalProperties === false) {
      lines.push(
        '`additionalProperties: false` — unknown keys are rejected. Source-specific fields',
        'belong in the declared extension bags (`Entity.attributes`, `Event.payload`).',
        '',
      );
    }
    return lines.join('\n');
  }
  lines.push(`Type: ${typeExpr(schema)}`, '');
  return lines.join('\n');
}

/** Build one page's MDX. Pure function of (schema JSON, metadata) — nothing read from disk. */
export function renderSchemaPage({schema, source, sha256, title, slug, position}) {
  const lines = [
    '---',
    `title: ${JSON.stringify(title)}`,
    `sidebar_label: ${JSON.stringify(title)}`,
    `sidebar_position: ${position}`,
    `description: ${JSON.stringify(
      (schema.description || `JSON Schema reference for ${title}.`).split('\n')[0].slice(0, 180),
    )}`,
    '---',
    '',
    BANNER,
    '',
    `# ${title}`,
    '',
    '| | |',
    '| --- | --- |',
    `| Source file | \`schemas/${source}\` |`,
    `| \`$id\` | \`${schema.$id || '—'}\` |`,
    `| CDM schema version | \`${schema['x-cdm-schema-version'] || '—'}\` |`,
    `| SHA-256 of source | \`${sha256}\` |`,
    '',
  ];

  if (schema.description) lines.push(prose(schema.description), '');

  if (schema.oneOf) {
    // cdm_object: the discriminated union rather than one object.
    const key = schema.discriminator?.propertyName || 'object_kind';
    lines.push(
      '## The union',
      '',
      `A mixed stream is validated against this schema without guessing: the \`${key}\``,
      'discriminator names which of the four canonical shapes an object is, so a consumer',
      'validates one object at a time and never has to try all four.',
      '',
      '| Discriminator value | Object |',
      '| --- | --- |',
    );
    const mapping = schema.discriminator?.mapping || {};
    const entries = Object.keys(mapping).length
      ? Object.entries(mapping).map(([value, ref]) => [value, defName(ref)])
      : schema.oneOf.map((branch) => ['—', defName(branch.$ref)]);
    entries.forEach(([value, name]) => {
      lines.push(`| \`${value}\` | [${name}](${anchor(name)}) |`);
    });
    lines.push('');
  } else {
    lines.push('## Fields', '', fieldTable(schema.properties, schema.required));
    if (schema.additionalProperties === false) {
      lines.push(
        ':::info[`additionalProperties: false`]',
        'Unknown keys are **rejected**. That is safe only because the CDM pairs strictness',
        'with a declared escape hatch — `Entity.attributes` and `Event.payload` accept',
        'anything — so an adapter never has to choose between dropping a field and failing',
        'validation.',
        ':::',
        '',
      );
    }
  }

  const defs = schema.$defs || {};
  const defNames = Object.keys(defs).sort();
  if (defNames.length) {
    lines.push(
      '## Referenced definitions',
      '',
      'Every `$ref` on this page resolves to one of these, inlined here so the page is a',
      'complete reference and not a starting point for chasing pointers.',
      '',
    );
    defNames.forEach((name) => lines.push(defSection(name, defs[name]), ''));
  }

  return `${lines.join('\n').replace(/\n{3,}/g, '\n\n').trimEnd()}\n`;
}

/** The section landing page. Generated too — an index that drifts is worse than none. */
function renderIndex(pages, schemaVersion) {
  const rows = pages.map(
    (p) => `| [${p.title}](./${p.slug}.mdx) | \`schemas/${p.file}\` | \`${p.sha256.slice(0, 12)}…\` |`,
  );
  return `---
title: "JSON Schema Reference"
sidebar_label: "Overview"
sidebar_position: 0
description: "Generated reference for the six published CDM JSON Schemas."
---

${BANNER}

# JSON Schema Reference

The CDM's canonical form is the Pydantic model. These schemas are its **publication** — what
a consumer that is not Python actually reads and validates against — and the pages below are
a rendering of those files, generated by \`docs/scripts/generate-schema-docs.mjs\`.

Nothing here is hand-written, and that is the point. Three copies of one contract exist
(model, schema, page), each mechanically derived from the one above it:

\`\`\`
packages/cdm/synapse_cdm/models.py          the single source
  └─ python -m synapse_cdm.schemas          →  schemas/*.schema.json   (tested by --check)
       └─ npm run gen:schemas               →  these pages             (tested by npm run check:schemas)
\`\`\`

Both arrows are gated. \`python -m synapse_cdm.schemas --check --out schemas\` fails if the
schemas drift from the models, and \`npm run check:schemas\` fails if these pages drift from
the schemas — so a field renamed in Python cannot reach a reader through a stale page.

**CDM schema version: \`${schemaVersion}\`.** Compatibility is decided by
\`version.compatible()\`, not by string equality: a 1.0.0 reader accepts anything 1.x, because
MINOR additions are optional by definition and a fleet that stops ingesting the moment one
adapter is upgraded is a self-inflicted outage.

| Page | Source file | SHA-256 |
| --- | --- | --- |
${rows.join('\n')}
`;
}

const CATEGORY = {
  label: 'JSON Schema Reference',
  position: 3,
  link: {type: 'doc', id: 'schema-reference/index'},
  customProps: {generated: true},
};

/**
 * Produce every generated file as {relativePath: contents}.
 *
 * Returned as a map rather than written directly so that `check-schema-docs.mjs` can compare
 * against what is on disk WITHOUT writing anything. A checker that has to write first cannot
 * be run on a read-only checkout, and one that writes then diffs cannot report the drift it
 * just destroyed.
 */
export function buildGeneratedTree({schemasDir, fixturesDir}) {
  const files = {};
  const pages = [];

  PAGES.forEach((page, index) => {
    const abs = path.join(schemasDir, page.file);
    if (!fs.existsSync(abs)) {
      throw new Error(
        `schemas/${page.file} is missing. The reference is generated from the six published ` +
          `schemas; re-export them with: python -m synapse_cdm.schemas --out schemas`,
      );
    }
    const text = fs.readFileSync(abs, 'utf8');
    const sha256 = crypto.createHash('sha256').update(text).digest('hex');
    const schema = JSON.parse(text);
    files[`schema-reference/${page.slug}.mdx`] = renderSchemaPage({
      schema,
      source: page.file,
      sha256,
      title: page.title,
      slug: page.slug,
      position: index + 1,
    });
    pages.push({...page, sha256, schemaVersion: schema['x-cdm-schema-version']});
  });

  const versions = [...new Set(pages.map((p) => p.schemaVersion))];
  if (versions.length !== 1) {
    throw new Error(
      `the published schemas disagree about x-cdm-schema-version (${versions.join(', ')}) — ` +
        're-export them all from one commit: python -m synapse_cdm.schemas --out schemas',
    );
  }

  files['schema-reference/index.mdx'] = renderIndex(pages, versions[0]);
  files['schema-reference/_category_.json'] = `${JSON.stringify(CATEGORY, null, 2)}\n`;

  // The worked example is generated from the SAME mechanism, for the same reason: it quotes a
  // real fixture and its real golden output, and a hand-copied excerpt of a golden file is a
  // claim about the adapter that no test checks. Read from disk here, compared by the checker.
  files['../src/data/worked-example.json'] = `${JSON.stringify(
    readWorkedExample(fixturesDir),
    null,
    2,
  )}\n`;

  return files;
}

/** The PNTMAP fixture/golden pair shown side by side in the adapter tutorial. */
function readWorkedExample(fixturesDir) {
  const name = 'jamming_gulf_of_riga';
  const rawPath = path.join(fixturesDir, `${name}.json`);
  const goldenPath = path.join(fixturesDir, 'golden', `${name}.cdm.json`);
  for (const p of [rawPath, goldenPath]) {
    if (!fs.existsSync(p)) {
      throw new Error(
        `worked example source ${p} is missing — regenerate the goldens with:\n` +
          '  python -m synapse_cdm.harness --adapter pntmap ' +
          '--fixtures packages/cdm/synapse_cdm/fixtures/pntmap --update-golden',
      );
    }
  }
  const source = fs.readFileSync(rawPath, 'utf8');
  const golden = fs.readFileSync(goldenPath, 'utf8');
  return {
    fixture: `packages/cdm/synapse_cdm/fixtures/pntmap/${name}.json`,
    golden: `packages/cdm/synapse_cdm/fixtures/pntmap/golden/${name}.cdm.json`,
    // Re-serialised through JSON.parse so the page cannot show something that is not valid
    // JSON, and pretty-printed identically on both sides so the columns align by eye.
    source: `${JSON.stringify(JSON.parse(source), null, 2)}\n`,
    output: `${JSON.stringify(JSON.parse(golden), null, 2)}\n`,
    sourceSha256: crypto.createHash('sha256').update(source).digest('hex'),
    goldenSha256: crypto.createHash('sha256').update(golden).digest('hex'),
  };
}

export {PAGES};
