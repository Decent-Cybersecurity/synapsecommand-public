# synapsecommand — public

SynapseCommand's integration layer: the **Canonical Data Model**, its published JSON Schema,
and the adapter SDK and validation harness that go with it. Apache 2.0 — see [`LICENSE`](LICENSE)
and [`NOTICE`](NOTICE), the latter for the attribution and for what the licence does *not* cover:
the specification documents this repository pins are recorded by hash and remain under their own
publishers' terms. [`PUBLICATION.md`](PUBLICATION.md) records when this repository became public,
which protections are enforced on it and how each was verified, and its ledger of what publication
left open and what has since been ruled on.

This is the contract layer, and it is public because that is what a contract is for. **Fourteen
integration adapters are shipped and harness-verified**: `pntmap` (ingest), `tak`, `ais`,
`adsb`, `legion` (ingest), `cat021`, `stanag4676`, `gmti`, `stanag4609`, `cat048`, `cat034`,
`cat062`, `cat023` and `stanag4586` (ingest) — byte-exact on the wire wherever the format is
binary and the direction is bidirectional. Without a
canonical model in the middle, N adapters means N(N−1)/2 translations and N private notions of
"a contact" — ninety-one and fourteen as of today; with one, an adapter is a thin translator and
nothing else.

```
external format ──▶ Adapter.to_cdm() ──▶ Entity | Event | Track | PlanObject ──▶ consumer
consumer        ──▶ Adapter.from_cdm() ─▶ external format          (egress, e.g. TAK)
```

## Layout

```
packages/cdm/       the synapse-cdm distribution — models, adapter SDK, harness, fixtures
schemas/            published JSON Schema, GENERATED from the models — never hand-edited
tests/              the suite; bare `pytest` from this directory runs all of it
gates/              checks too slow or too networked for the suite; each is a protocol act
docs/               the documentation site (Docusaurus, deployed to Cloudflare Pages)
```

`schemas/` is at the root deliberately: it is the artefact for consumers that are not Python,
and a Go or TypeScript reader should not have to understand a Python package layout to find it.
It is generated, and a test fails the build if it drifts from the models.

## Using it

You do not need this repository to use the CDM. The distribution is `synapse-cdm`, it depends on
`pydantic` and `jsonschema` and nothing else, and it carries the models, the adapter SDK, the
harness and **every fixture the fourteen shipped adapters are verified against** — which is what
makes conformance something you can prove rather than take on trust.

**Install.** From PyPI, and nothing else is needed:

```bash
pip install synapse-cdm
```

`synapse-cdm` **1.0.0** was published on 2026-08-25 and the upload is recorded, measured and
closed as ledger entry 5 of [`PUBLICATION.md`](PUBLICATION.md) — including the check that the two
files on the index are byte-for-byte the two files this repository's wheel gate verified. The
import name is `synapse_cdm`, with an underscore, because a Python identifier cannot carry a
hyphen. Installing from a clone is the *contributor* path and is further down, under
[Working on this repository](#working-on-this-repository); a consumer never needs it.

**Validate a payload against the schema.** The published JSON Schema is generated from the
models, so the package writes it on demand rather than carrying a copy that could go stale:

```bash
python -m synapse_cdm.schemas --out ./schemas         # six schemas, from anywhere
```

```python
import json, jsonschema
from synapse_cdm import schemas

published = schemas.generate()          # or json.load(open("schemas/entity.schema.json"))
jsonschema.Draft202012Validator(published["entity"]).validate(json.loads(payload))
```

Six schemas: one per canonical object, one per registered payload model, and a `cdm_object`
union carrying the discriminator — so a consumer reading a mixed stream validates without first
deciding which kind it is holding.

`schemas.generate()` and the files under [`schemas/`](schemas) are the same bytes — a gate in the
suite fails the build if they ever differ. Use the files for a non-Python consumer; use the
function when you have the package.

**Run an adapter through the harness.** This is the gate every adapter here has to pass, and it
is the same code for yours as for ours:

```bash
python -m synapse_cdm.harness --adapter pntmap
```

No `--fixtures`: for an adapter this package ships, the harness asks the import system where its
own fixtures are and replays those, wherever it is installed. Six checks per fixture — translate,
schema, provenance, lossless, roundtrip, golden — and an unrun check reports `SKIP`, never `PASS`.

`python -m synapse_cdm.harness --list-adapters` prints the names `--adapter` takes, with each
one's version, direction and fixture directory. Until it existed the roster was reachable only
through a failure — a `LookupError` from a wrong name, or argparse's usage line, which names the
flag and not one value it takes. **It shipped in 1.1.0**, so `pip install synapse-cdm` is enough
and no clone is needed; see
[`MIGRATIONS.md`](packages/cdm/synapse_cdm/MIGRATIONS.md), "1.1.0".

## Writing your first adapter

The shortest honest path from an empty file to a green harness run. Nothing below is duplicated
from the protocol documents; each step names the one that decides it.

1. **Read the reference adapter.** `packages/cdm/synapse_cdm/adapters/pntmap.py`. Every rule
   appears in it at least once, and it is 250 lines.
2. **Learn the four objects and the seven rules** —
   [the package README](packages/cdm/synapse_cdm/README.md) has both, with the site of
   enforcement named for each rule. There are only four objects and one of them is probably
   yours.
3. **Declare the class.** `name`, `version`, `direction`, `system`. The contract is checked at
   class-definition time, so a mistake fails at import rather than on the first outbound push.
   Then **derive the id, never draw one** — `ids.derive(system, external_id)`. `entity_id` is
   required and has no default on purpose: a `uuid4()` per payload creates a tenth contact for
   the tenth report about one emitter, and makes golden output impossible to diff.
4. **Write the field mapping down first**, as a row set in
   [`FORMAT_COVERAGE.md`](packages/cdm/synapse_cdm/FORMAT_COVERAGE.md) — that file's conventions
   are the specification your `to_cdm()` implements, and a test resolves every CDM path in it
   against the real models, so it cannot go stale quietly.
5. **Park what has no home.** `attributes` / `payload`, via `lossless.residual()`. Never
   enumerate leftovers by hand: the block a source adds in its next firmware release is exactly
   the one nobody remembers.
6. **Ship at least three synthetic fixtures**, one of them awkward. No real data, ever — see
   [`CONTRIBUTING.md`](CONTRIBUTING.md).
7. **Run the harness and read what it says.** From outside this repository your adapter is a
   `module:ClassName`, and `--fixtures` is then required rather than guessed at:

   ```bash
   python -m synapse_cdm.harness --adapter my_package.adapters:MyAdapter --fixtures ./fixtures
   python -m synapse_cdm.harness --adapter my_package.adapters:MyAdapter --fixtures ./fixtures \
       --update-golden          # then READ the diff before committing it
   ```

Contributing the adapter back — sign-off, the fixture rules, what a pull request has to pass — is
[`CONTRIBUTING.md`](CONTRIBUTING.md), and the tutorial with a real fixture beside its real output
is <https://docs.synapsecommand.com/writing-an-adapter>.

## Working on this repository

```bash
pip install -e "packages/cdm[test]"   # the package, its two dependencies, and pytest
pytest -q                             # the whole suite
```

The `[test]` extra is what makes the second line work: `pytest.ini` puts `packages/cdm` on
`sys.path`, so the suite runs against the source tree and never against an installed copy — but
`pytest` itself, and `pydantic` and `jsonschema`, still have to be there. **Keep the quotes**;
`zsh` reads a bare `packages/cdm[test]` as a glob and fails before `pip` sees it.

That choice has a cost, and it is paid by a separate gate rather than ignored: nothing in the
suite exercises the artefact a partner receives. `gates/wheel_install.py` builds the
distribution, installs the wheel into a clean environment with no part of this repository on its
path, and runs the harness and half the suite against **that**:

```bash
python gates/wheel_install.py --mutation-check
```

It needs a network, which is why it is a protocol act rather than a suite member. The
`--mutation-check` half rebuilds the wheel with its fixtures stripped out and requires the gate
to refuse it — a gate nobody has seen fail is a gate nobody has seen.

## Releasing

**A release is a pushed tag.** `.github/workflows/publish.yml` does the rest:

```bash
git tag -a v1.7.0 -m "..."            # annotated; a lightweight tag is refused by the workflow
git push origin main --follow-tags
```

The workflow builds the sdist and wheel, runs the suite, runs `gates/wheel_install.py
--mutation-check` against what it built, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and then waits. The upload happens in the `pypi` environment, which
carries a required reviewer, and it uses **Trusted Publishing** — a short-lived OIDC token minted
for that one run. There is no API token in the workflow, in this repository's secrets, or anywhere
else it could be copied from.

`packages/cdm/synapse_cdm/MIGRATIONS.md`, "Releasing the package", is the authority: it states the
four conditions a release has to meet, which of them the workflow checks, and the one it cannot.

**The manual `twine` path is a documented fallback and is not the procedure.** It is written down
in MIGRATIONS.md under "The manual fallback" for the case where the workflow itself is broken, and
using it means an upload with no gate run against the artefact and no record in the Actions log.
`PUBLICATION.md` ledger entry 5 is what that looks like afterwards: it is the record of the 1.0.0
upload, done by hand, and of the step in its own sequence that nobody noticed had been skipped
until a stranger looked for the package on TestPyPI and found a 404.

## Where the documentation lives

The rendered site is built from `docs/` — see [`docs/README.md`](docs/README.md) for the
build and the Cloudflare Pages settings. Its JSON Schema reference is generated from
`schemas/` and gated against drift, so it cannot document a shape the schemas do not have.

| Document | What it answers |
|---|---|
| [`packages/cdm/synapse_cdm/README.md`](packages/cdm/synapse_cdm/README.md) | the four objects, the seven rules and where each is enforced, and how to write the next adapter |
| [`packages/cdm/synapse_cdm/FORMAT_COVERAGE.md`](packages/cdm/synapse_cdm/FORMAT_COVERAGE.md) | field-by-field CoT / STANAG 4676 / GeoJSON mappings and the named gaps |
| [`packages/cdm/synapse_cdm/MIGRATIONS.md`](packages/cdm/synapse_cdm/MIGRATIONS.md) | what MAJOR/MINOR/PATCH mean for `schema_version`, the procedure for changing the schema, and what a release requires |
| [`PUBLICATION.md`](PUBLICATION.md) | what became true when this repository went public, and the open ledger — including what still has to be configured on PyPI before the publish workflow can upload anything |

## Dependencies, and what is deliberately absent

`pydantic` and `jsonschema`. Nothing else — in particular nothing from the SynapseCommand
product repository, which is what made lifting this out into its own repository possible and
what keeps it possible. There is also no crypto here: the `integrity` field is designed and
deliberately unpopulated, because a signature computed inside a translator is held by nothing
that audits it. Both properties are enforced by AST over the package sources in
`tests/test_cdm_boundary.py` rather than by this paragraph.
