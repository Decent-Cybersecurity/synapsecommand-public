# Documentation site

Docusaurus 3 (TypeScript) for the Canonical Data Model. Deployed to Cloudflare Pages.

```bash
cd docs
npm install
npm start            # dev server; regenerates the schema reference first
npm run build        # production build into docs/build
npm run ci           # what CI runs: check:schemas && typecheck && build && check:admonitions
```

## What is generated and what is written

| Path | Author |
| --- | --- |
| `docs/schema-reference/**` | **generated** by `scripts/generate-schema-docs.mjs` from `/schemas` |
| `src/data/worked-example.json` | **generated** from the real PNTMAP fixture and its golden output |
| everything else under `docs/` | written by hand |

The generated files are **committed**. Generated-and-gitignored would make the drift check
meaningless — there would be nothing to drift — and would hide every schema change from code
review. The same argument the CDM makes for committing its golden files applies here, and so
does the same warning: read the diff, because a regenerated page is how a defect becomes the
documentation.

### The drift gate

```bash
npm run check:schemas
```

Fails if the committed pages are not what the generator produces from `/schemas` **now**. It
catches three things an mtime comparison cannot: a hand-edited generated page, a
partially-committed regeneration, and a schema change with no regeneration.

It is a **content** check rather than a timestamp check for one reason: git does not record
modification times, so on a fresh clone — which is exactly what Cloudflare Pages and CI do —
every file carries the checkout time and an mtime gate is a coin flip. mtimes are still read
and reported when there is drift, because "schemas/entity.schema.json is newer than this page"
is the sentence that tells a developer which end to fix. It is a diagnostic, never the verdict.

This is the second of two gates on the same contract:

```
packages/cdm/synapse_cdm/models.py            the single source
  └─ python -m synapse_cdm.schemas --check     →  schemas/*.schema.json
       └─ npm run check:schemas                →  docs/docs/schema-reference/**
```

### The render gate

```bash
npm run check:admonitions        # after npm run build — it reads build/
```

Fails if a `:::` directive reached a rendered page as literal text, or if a directive rendered as
nothing at all. It exists because every admonition on this site was broken and no gate noticed:
`future.v4: true` disables the MDX-v1 compatibility shim that rewrote `:::note Title` into the
`:::note[Title]` form `remark-directive` requires, so all twelve directives across eleven pages
emitted as paragraphs — and `docusaurus build` exits 0, because a directive it cannot parse is
not an error.

It reads the **built output** rather than the sources on purpose: a source-side lint would have
to re-implement the parser's opinion about what a valid directive is, and being wrong about that
was the defect. `<pre>` blocks are stripped before the scan, so a page that documents directive
syntax in a code block does not trip it.

## Cloudflare Pages — and a push does not deploy

**The Pages project has no Git integration.** `wrangler pages project list` reports
`Git Provider: No`, so Cloudflare never clones this repository and never runs a build. Every
deployment in the project's history is a **direct upload** of an already-built `docs/build`,
stamped with the commit SHA wrangler reads from git at upload time. **A push to `main` changes
nothing on the live site.**

That is worth stating flatly because the opposite was asserted once, in a commit message, and
stood for one round. It could not be caught by the five rounds between the claim and this one:
none of them touched a page under `docs/`, so there was nothing for a deploy to have changed and
nothing to notice.

### The deploy

Two commands, from the repository root, in this order:

```bash
cd docs && npm run ci        # gen:schemas → check:schemas → typecheck → build → check:admonitions
npx wrangler pages deploy docs/build --project-name synapsecommand-docs --branch main
```

The directory argument is optional — `pages_build_output_dir` in `wrangler.toml` supplies it, and
a no-argument deploy uploads the same file set. Wrangler will warn that the working tree is
dirty; it always will, because every pinned specification PDF is deliberately untracked, so
`--commit-dirty=true` is the normal case here rather than a signal.

`npm run build` runs the generator via npm's `prebuild` hook. There is no way to build and skip
it, which is the point: a deploy renders the schemas as they are in the commit being deployed.

### The settings, which are inert while there is no Git integration

| Setting | Value |
| --- | --- |
| Build command | `cd docs && npm install && npm run build` |
| Build output directory | `docs/build` |
| Root directory | `/` |
| Node version | `22` (pinned by `.node-version` at the repository root) |

Recorded rather than deleted: this is what the project would need if the Git integration were
ever connected, and the build-output row is the one that is load-bearing today, because it is the
value `wrangler.toml` also carries. `tests/test_cdm_deploy_workflow.py` requires this file and
`wrangler.toml` to agree about the mechanism and about that directory.

### The workflow, written down for the first time

**Commit first; deploy second, explicitly, and only when a rendered page changed.** The order
matters — wrangler stamps the deployment with the commit SHA, so deploying before committing
records a SHA that is not what was uploaded. "Only when a rendered page changed" is why the
mistaken claim survived a round: a commit that touches no file under `docs/` needs no deploy, and
five of them in a row make a wrong belief about deployment unfalsifiable.

## Structure

```
docs/
  intro.mdx                    Introduction — the seven rules and where each is enforced
  cdm/                         one page per canonical object
    index.mdx  entity.mdx  event.mdx  track.mdx  plan-object.mdx
  schema-reference/            GENERATED from /schemas
  writing-an-adapter.mdx       the tutorial, with the worked example
  changelog.mdx                curated summary of packages/cdm/synapse_cdm/MIGRATIONS.md
scripts/
  lib/schema-to-mdx.mjs        the generator; pure functions, nothing written here
  lib/paths.mjs                every path resolved from import.meta.url, not process.cwd()
  generate-schema-docs.mjs     writes the generated tree
  check-schema-docs.mjs        the drift gate
  check-built-admonitions.mjs  the render gate; reads build/, so it runs AFTER the build
src/
  components/WorkedExample/    the side-by-side fixture -> golden view
  data/worked-example.json     GENERATED
  css/custom.css               placeholder branding; four values to rebrand
```

## Branding

Placeholder, deliberately: the product name, one desaturated teal accent, no logo, no social
card. An invented visual identity is harder to remove later than it is to add now, and this
repository is public. Dark mode is the default and the toggle is kept.
