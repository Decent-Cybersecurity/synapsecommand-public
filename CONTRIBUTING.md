# Contributing

This repository holds the SynapseCommand **Canonical Data Model** — the contract layer that
thirty-two integration adapters translate into. A contract is the wrong place for a surprise, so the
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

### Check the message before you push, and there is deliberately no hook

`gates/commit_message.py` checks a commit message against the two rules this repository has
learned the hard way — the trailer block must say what it appears to say, and a sign-off must
actually be there. Run it on your commit before pushing:

```bash
python3 gates/commit_message.py --rev HEAD
```

It also reads a message straight from a file, which is useful while you are still writing one:

```bash
python3 gates/commit_message.py --file .git/COMMIT_EDITMSG
```

**There is no hook, and that is a decision rather than something nobody got round to.** A hook
lives in one clone, so installing one would protect whoever ran the command and no one else — and
every other gate in this repository travels with the tree. The `DCO` GitHub App checks every
commit in a pull request regardless, so a missing sign-off cannot reach `main` through the normal
route; the command above is what closes the gap for anyone pushing directly, which is where a
missing sign-off actually got through on 2026-09-04. That incident is recorded in
[`PUBLICATION.md`](PUBLICATION.md) entry 2, and the reasoning is in the gate's own docstring.

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

## Every commit in a pull request is checked

The [DCO GitHub App](https://github.com/apps/dco) is installed on this repository. It checks
**every commit in a pull request**, not just the tip, and reports as a check named `DCO`:

- one or more commits without a valid `Signed-off-by:` trailer → the **`DCO` check fails**,
  naming the commit and its author in the check's own output;
- **that check is not currently a required status**, so it does not by itself block a merge.
  That is a **settled decision and not an oversight**: making it required would gate pushes to
  `main` on a check the DCO app only ever produces for pull requests, so it would refuse the
  maintainer's direct pushes with nothing able to make them pass. The ruling and its three grounds
  are in [`PUBLICATION.md`](PUBLICATION.md), ledger entry 1.

Do not read the second point as slack. A pull request carrying an unsigned commit will not be
merged; the only difference is that today it is a maintainer who refuses it rather than the
platform. That sentence used to claim the opposite — that the check was a required status and
the merge was impossible — and it was published to the world for one day while being false; the
first run of the check, on a deliberately unsigned commit, is what exposed it. Please sign off
as you go: it is one flag, and fixing it afterwards means rewriting history.

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
python -m synapse_cdm.harness --adapter <name> --schemas schemas
```

No `--fixtures`: an adapter in this package declares its own fixture directory
(`Adapter.fixture_dir`) and the harness resolves it through `importlib.resources`. An adapter
that lives outside this package is loaded as `module:ClassName` and then `--fixtures` is
required — the harness will not guess at a directory it cannot know.

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
- **`roundtrip` skips one half of every fixture pair for an adapter that emits bytes**, and
  judges the other half under the tolerance the class declares in `ROUNDTRIP_TOLERANCE`: the byte
  fixture under `bytes` (octet equality), the parsed twin under `values` (re-ingest, no source
  value missing — the tolerance XML needs). The SKIP text says which half carried the verdict.
  Until 2026-09-16 the column skipped every non-JSON emitter outright and pointed at `tests/`;
  see `tests/test_cdm_tak_adapter.py` for what the adapter's own statement of the claim looks
  like.

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

#### Identifiers and places in observation fixtures (added 2026-10-15)

The observation adapters — station text, weather radar, gridded fields, imagery and product
references — name things the earlier fixtures never had to: a station, a radar site, the extent
of a grid, a tile. Each of those names a real place or a real allocation when it is copied from a
live product, so a fixture that uses one is real data in the sense above even when every number
in it is invented. These rules say what a fixture uses instead. They extend the conventions the
existing fixture READMEs already follow — Baltic-plausible positions, `EX`-prefixed names, an
unallocated address block — and each states its argument, because a rule with no argument is
copied wrongly the first time it is inconvenient.

- **Station identifiers, one synthetic block per identifier grammar.** A station-text fixture
  states a station only from the block for its own grammar, so a parser is still exercised on the
  shape the format really has:
  - *alphanumeric five-character station ids* (the buoy and coastal-station form): `EX` followed
    by three digits, `EX001` to `EX099`. `EX` is this repository's exercise marker, as in the
    ADS-B callsigns;
  - *seven-digit numeric station ids* (the tide and water-level form): six zeros and one digit, or
    five zeros and two, `0000001` to `0000099`. Leading zeros make the id visibly synthetic, and
    they are the awkward case on purpose — a reader that turns the id into an integer loses them;
  - *nine- and twelve-digit air-quality site ids*: zeros and two final digits, `000000001` to
    `000000099` and `000000000001` to `000000000099`; the run of leading zeros makes the id
    visibly synthetic, as in the seven-digit block.
  - *Frost station ids* (MET Norway's `SN<station number>` form; the parallel-sensor suffix `:N`
    is apart from it): `SN` and five digits with leading zeros, `SN00001` to `SN00099`. The zeros
    make the id visibly synthetic, as in the seven-digit block; a Frost response states no
    position, so the adapter's own fixture station table places them inside the rectangle below
    (added 2026-10-22).
- **AIS MMSIs keep the `ais` fixtures' rule: MID 299.** The European block no administration
  holds — a ship station `299xxxxxx`, an aid to navigation `99|299|xxxx`, a coast station
  `00|299|xxxx` — for the reason `fixtures/ais/README.md` gives against the `999xxxxxx` test
  range: `99` is the aid-to-navigation prefix, so a vessel under it contradicts itself. A
  BarentsWatch track fixture follows the same rule (added 2026-10-22).
- **Radar site identifiers: `ZZZZ`, then `XZZA` to `XZZZ`.** A weather radar names itself with a
  four-letter location indicator. A synthetic radar takes `ZZZZ`, and a fixture that needs a
  second site takes `XZZA`, `XZZB` and so on, so every synthetic site is spelled from one visibly
  artificial pattern.
- **Places: the Baltic rectangle, 56.0° N to 58.5° N and 20.0° E to 24.5° E.** Every position, grid
  corner, footprint vertex and tile a new fixture states lies inside it. It is the smallest
  half-degree rectangle around the positions the existing fixture READMEs name — the Gulf of
  Riga, Ventspils, Liepāja, the water west of Saaremaa, the Riga apron and the Courland exercise
  area — whose fixtures span 56.15° N to 58.12° N and 20.42° E to 24.10° E, so a new fixture adds
  no place the repository did not already use. It does not cross the antimeridian, which
  `BoundingBox` refuses. A tile identifier always names a real place, so it follows this rule
  rather than an "unallocated" one: a fixture uses a tile whose footprint lies inside the
  rectangle, and a grid fixture states an extent inside it whatever projection the format uses.
- **Aircraft addresses keep the ADS-B rule**: a readsb trace fixture uses the `0029xx` block that
  `fixtures/adsb/README.md` argues for and its test pins.

Three further readings behind the identifier forms are conventions taken here on 2026-10-15 and
not verified against the allocating registers in this repository: that `ZZZZ` is the indicator for
"no other indicator", that `X` is not an aerodrome first letter, and that no real id in these
registers takes these shapes.

No fixture, test or document of these adapters spells the identifier of a real station, radar
site, model domain or tile, and none uses a value read from a live product — not as an example,
not as a test's expectation, not in a comment. A fixture README restates the rule it follows.

#### Writing a fixture builder (added 2026-10-15)

A binary fixture — a GRIB2 message, a radar volume, a PNG, a Parquet file — cannot document itself,
so it is written by `fixtures/<adapter>/spec/build_fixtures.py`, and the builder is the reviewable
form of the set. Every builder of the observation adapters follows these rules, because a builder
that cannot be re-run, or that writes something different on a second machine, is a fixture set
nobody can check:

- **`--check` rebuilds and compares, and writes nothing.** `python -I -B build_fixtures.py --check`
  builds every fixture and twin into memory or a temporary directory, compares the bytes with the
  committed files, prints `CURRENT` and exits 0, or prints `STALE: <names>` and exits 1. Without
  `--check` it writes the files. It runs under `-I` (so it locates the package from its own
  `__file__`, never from `PYTHONPATH`) and `-B` (so no bytecode lands under `spec/`).
- **Deterministic writers.** The same script writes the same bytes on every run and every
  machine: no clock, no random value, no host name; a gzip member is written with `mtime=0`; a tool
  that stamps its own version or a creation time into its output is either told not to or not
  used, and the version it does stamp is recorded in the set's pin.
- **No absolute path in a fixture or a pin.** A tool is run from a working directory relative to
  the fixture directory, and the commands a pin records are written relative to it, so nothing
  names the machine that built the set.
- **GDAL runs with `GDAL_PAM_ENABLED=NO`.** Otherwise it leaves a `.aux.xml` beside a raster, and
  the harness replays every file of a fixture directory as a payload.
- **Sources are literals in the script.** A builder's inputs are written in `build_fixtures.py`
  itself or under `sources/` with their own `PROVENANCE.json`: `spec/` ships only
  `build_fixtures.py`, `*_pin.json` and `*_terms.json` (`tests/test_cdm_packaging.py`).
- **A standard-library writer first.** Where the report on a format shows one is possible, the
  builder is pure Python, because that is the only builder every interpreter of the test matrix can
  re-run; a tool-written set is re-checked on a named tool build before each release and the
  reading is recorded in its pin.

`tests/observation_support.py` holds the checks an adapter's tests owe the set: `builder_problems`
runs `--check` the way the release check runs it and requires `CURRENT`, exit 0 and an unchanged
directory; `load_builder` compiles the builder in memory for an in-process assertion, as
`tests/test_cdm_generator_loading.py` requires of every loader; `provenance_problems` and
`twin_problems` hold the set to its `PROVENANCE.json` and every binary payload to its
`.parsed.json` twin; and `station_id_problems`, `radar_site_problems`,
`aircraft_address_problems`, `mmsi_problems` and `positions_outside_the_rectangle` hold it to the identifier rules
above.

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
pip install -e "packages/cdm[test,lint]"             # editable install, plus pytest and ruff
pytest -q                                            # the whole suite
python -m synapse_cdm.schemas --check --out schemas   # published schemas match the models
ruff check --config packages/cdm/pyproject.toml packages/cdm gates tests   # the lint gate publish.yml applies

python gates/wheel_install.py                        # the built WHEEL, in a clean environment

cd docs && npm install && npm run ci                 # docs: drift gate, typecheck, build
```

The `gates/wheel_install.py` line is a **gate rather than a test**, and the distinction is the
reason it is here.
`pytest.ini` puts `packages/cdm` on `sys.path`, so the suite judges the working tree and never an
installed copy — deliberately, because a stale wheel passing for the source is a green run that
means nothing. The cost is that nothing in the suite exercises the artefact a partner receives.
`gates/wheel_install.py` builds the distribution, installs the wheel into an environment with no
part of this repository on its path, and runs the harness and the package-only half of the suite
against **that**. It needs a network for `pip`, which is why it is not a suite member — since
2026-09-16 `ci.yml`'s `wheel` job runs it on every push, so a red arrives on the push rather than
at the release, and it is still not something `pytest` runs.

Add `--mutation-check` and it also builds a wheel with its fixtures stripped out and requires
itself to refuse it. Run that form if you touched packaging.

The `ruff` line is the lint gate `publish.yml` applies at a tag and `ci.yml` applies on every
push, run here with the same command; the `[lint]` extra installs ruff at the one version
`pyproject.toml` pins, so the reading is the workflows' reading.

The `[test]` extra carries `pytest` and `[lint]` carries `ruff`; the quotes are for `zsh`, which
would otherwise glob the brackets. `README.md` documents the same install and suite lines with the
`[test]` extra alone, and a test requires every extra either document names to be one
`pyproject.toml` declares.

`synapse_cdm` depends on `pydantic` and `jsonschema` and nothing else. It imports nothing from
the SynapseCommand product repository and contains no crypto — both enforced by AST in
`tests/test_cdm_boundary.py`, so a pull request that breaks either fails rather than being
caught in review.

## Licence

By contributing you agree that your work is licensed under the
[Apache License 2.0](LICENSE), as stated in your DCO sign-off.
