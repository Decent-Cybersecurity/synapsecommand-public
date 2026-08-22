# synapsecommand — public

SynapseCommand's integration layer: the **Canonical Data Model**, its published JSON Schema,
and the adapter SDK and validation harness that go with it. Apache 2.0.

This is the contract layer, and it is public because that is what a contract is for. Five
integration adapters are landing — PNTMAP GNSS alerts, Picogrid Legion, TAK / Cursor-on-Target,
STANAG 4676 tracks, the simulation feed. Without a canonical model in the middle, five adapters
means ten translations and five private notions of "a contact"; with one, an adapter is a thin
translator and nothing else.

```
external format ──▶ Adapter.to_cdm() ──▶ Entity | Event | Track | PlanObject ──▶ consumer
consumer        ──▶ Adapter.from_cdm() ─▶ external format          (egress, e.g. TAK)
```

## Layout

```
packages/cdm/       the synapse_cdm distribution — models, adapter SDK, harness, fixtures
schemas/            published JSON Schema, GENERATED from the models — never hand-edited
tests/              the suite; bare `pytest` from this directory runs all of it
```

`schemas/` is at the root deliberately: it is the artefact for consumers that are not Python,
and a Go or TypeScript reader should not have to understand a Python package layout to find it.
It is generated, and a test fails the build if it drifts from the models.

## Getting started

```bash
pip install -e packages/cdm     # editable, for working on the CDM itself
pytest -q                       # 161 tests; needs no install (see pytest.ini)
```

Run the reference adapter through the harness — the gate every adapter has to pass:

```bash
python -m synapse_cdm.harness --adapter pntmap \
    --fixtures packages/cdm/synapse_cdm/fixtures/pntmap --schemas schemas
```

## Where the documentation lives

| Document | What it answers |
|---|---|
| [`packages/cdm/synapse_cdm/README.md`](packages/cdm/synapse_cdm/README.md) | the four objects, the seven rules and where each is enforced, and how to write adapter #2 |
| [`packages/cdm/synapse_cdm/FORMAT_COVERAGE.md`](packages/cdm/synapse_cdm/FORMAT_COVERAGE.md) | field-by-field CoT / STANAG 4676 / GeoJSON mappings and the named gaps |
| [`packages/cdm/synapse_cdm/MIGRATIONS.md`](packages/cdm/synapse_cdm/MIGRATIONS.md) | what MAJOR/MINOR/PATCH mean for `schema_version`, and the procedure for changing the schema |

## Dependencies, and what is deliberately absent

`pydantic` and `jsonschema`. Nothing else — in particular nothing from the SynapseCommand
product repository, which is what made lifting this out into its own repository possible and
what keeps it possible. There is also no crypto here: the `integrity` field is designed and
deliberately unpopulated, because a signature computed inside a translator is held by nothing
that audits it. Both properties are enforced by AST over the package sources in
`tests/test_cdm_boundary.py` rather than by this paragraph.
