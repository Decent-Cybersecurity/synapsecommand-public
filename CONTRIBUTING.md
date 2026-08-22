# Contributing

This repository holds the SynapseCommand **Canonical Data Model** — the contract layer that
five integration adapters translate into. A contract is the wrong place for a surprise, so the
rules below are short and they are enforced by something that fails a build rather than by
review alone.

Read [`packages/cdm/synapse_cdm/README.md`](packages/cdm/synapse_cdm/README.md) before changing
the model, and the tutorial at <https://docs.synapsecommand.com/writing-an-adapter> before
writing an adapter.

## Every commit must be signed off (DCO)

We use the [Developer Certificate of Origin](DCO) — the full text is in this repository as
[`DCO`](DCO), verbatim. There is no CLA to sign and no paperwork to send: you certify the
origin of your contribution in the commit itself.

Commit with `-s`:

```bash
git commit -s -m "Add the STANAG 4676 adapter"
```

That appends one trailer to your commit message:

```
Signed-off-by: Ada Lovelace <ada@example.org>
```

By adding that line you are stating that you have read the [DCO](DCO) and that your
contribution satisfies it — clause (a), (b) or (c) — and that you accept clause (d): the
contribution and the personal information in your sign-off are public and kept indefinitely.

### The name and email must be real, and must match the commit author

The sign-off is a statement of provenance, so it has to identify a person who can stand behind
it. `git commit -s` takes the trailer from your git configuration, which is also where the
author comes from — so set them once and the two agree automatically:

```bash
git config --global user.name "Ada Lovelace"
git config --global user.email "ada@example.org"
```

- Use your **real name**. Not a handle, not an initial, not a pseudonym.
- Use a **real, working email address** you can be reached at.
- The `Signed-off-by:` identity must **match the commit author**. A sign-off in someone else's
  name is a false statement about who certified the contribution, and a sign-off that does not
  match its author is one the project cannot rely on — which is the whole reason the check
  compares them rather than merely looking for the line.

GitHub's `noreply` addresses are acceptable if that is genuinely how you receive mail; anonymous
or invented addresses are not.

## Unsigned commits cannot be merged

The [DCO GitHub App](https://github.com/apps/dco) is installed on this repository. It checks
**every commit in a pull request**, not just the tip:

- one or more commits without a valid `Signed-off-by:` trailer → the **DCO check fails**;
- a failing DCO check is a **required status**, so the pull request **cannot be merged** until
  it passes.

This is not a formality that a maintainer can wave through. Please sign off as you go — it is
one flag, and fixing it afterwards means rewriting history.

### Forgot to sign off?

For the most recent commit:

```bash
git commit --amend -s --no-edit
git push --force-with-lease
```

`--force-with-lease` rather than `--force`: it refuses the push if someone else has moved the
branch since you last fetched, so a rewrite cannot silently discard another person's work.

For several commits, sign off the whole branch at once:

```bash
git rebase --signoff origin/main
git push --force-with-lease
```

The DCO check re-runs on the push and the pull request goes green with no further action.

## Contributing an adapter

An adapter is a **pure translator**: external format in, CDM out. No filtering, no enrichment,
no thresholds — each of those is a decision, and a decision made inside a translator is
invisible to the audit trail and unattributable.

Start with the tutorial at <https://docs.synapsecommand.com/writing-an-adapter>. It walks the
whole path with a real fixture beside the real output it produces. Then read
`packages/cdm/synapse_cdm/adapters/pntmap.py` (the reference adapter — every rule appears in it
at least once) and `adapters/tak.py` (where the awkward cases live: XML, bidirectional egress, a
source sentinel that must become `null`, an enum collapse that has to stay recoverable).

### It must pass the full harness

```bash
python -m synapse_cdm.harness --adapter <name> \
    --fixtures packages/cdm/synapse_cdm/fixtures/<name> --schemas schemas
```

Every check, every fixture, `0 failed`. The harness knows nothing about any particular adapter,
so it is the same gate for yours as for ours:

| Check | Fails when |
| --- | --- |
| `translate` | `to_cdm()` raised |
| `schema` | an object violates the **published** JSON Schema in `/schemas` — not the model, which would be testing the model against itself |
| `provenance` | `source.*` incomplete, `synthetic` unstated, `source_ids` empty, an event missing a timestamp |
| `lossless` | a source value appears nowhere in the output and is not a declared transform |
| `roundtrip` | an `egress`/`bidirectional` adapter lost a value on the way out |
| `golden` | the output differs from the recorded expectation |

An **unrun check reports `SKIP`, never `PASS`** — and a `SKIP` you were expecting to be a `PASS`
is a finding, not a pass. Two cases to know about:

- **`lossless` skips on a non-JSON fixture**, because there is no leaf structure to harvest from
  bytes. An XML or binary adapter must therefore ship each fixture **twice** — the raw bytes and
  the parsed form — or the never-drop rule is never actually checked for it. See
  `fixtures/tak/*.parsed.json`.
- **`roundtrip` skips for an adapter that emits XML or USMTF**, because the harness cannot
  compare a structure it cannot parse. Such an adapter must ship its own round-trip test. See
  `tests/test_cdm_tak_adapter.py`.

### Synthetic fixtures only

**No real data, ever** — not a captured feed, not a redacted one, not "just one message from the
exercise network". This repository is public, and a payload that was real when it was captured
does not stop being real because it was committed.

Every fixture is authored, and every object states it: `source.synthetic` is required and has no
default, because mislabelling exercise data as live can reach an operational picture and
mislabelling live data as exercise hides it from an operator. Neither direction is safe to
guess.

Ship at least three, and make one of them **awkward** — a missing position, an unknown type, a
vendor block you have never seen, a coordinate of exactly zero. The interesting fixture is the
one that is allowed to be ugly.

### Then

- Record golden output with `--update-golden`, and **read the diff before committing it**. A
  golden file updated without being read is how a defect becomes the expectation.
- Add tests: one per claim in your adapter's docstring.
- Update the row and the `Status` column in
  [`FORMAT_COVERAGE.md`](packages/cdm/synapse_cdm/FORMAT_COVERAGE.md). A test resolves every CDM
  path in that table against the real models, so it cannot go stale quietly.
- Do **not** add a field to the model to make your adapter tidier. `attributes` and `payload`
  exist for exactly that, and a schema change is a versioned, announced event — see
  [`MIGRATIONS.md`](packages/cdm/synapse_cdm/MIGRATIONS.md). If a canonical field is genuinely
  missing, open an issue naming the gap rather than adding it in passing.

## Running everything before you open a pull request

```bash
pip install -e packages/cdm                          # editable install
pytest -q                                            # the whole suite
python -m synapse_cdm.schemas --check --out schemas   # published schemas match the models

cd docs && npm install && npm run ci                 # docs: drift gate, typecheck, build
```

`synapse_cdm` depends on `pydantic` and `jsonschema` and nothing else. It imports nothing from
the SynapseCommand product repository and contains no crypto — both enforced by AST in
`tests/test_cdm_boundary.py`, so a pull request that breaks either fails rather than being
caught in review.

## Licence

By contributing you agree that your work is licensed under the
[Apache License 2.0](LICENSE), as stated in your DCO sign-off.
