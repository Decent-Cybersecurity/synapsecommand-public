# `synapse_cdm` — the Canonical Data Model and adapter framework

Nine integration adapters are shipped: PNTMAP GNSS alerts, TAK / Cursor-on-Target, AIS /
NMEA 0183 AIVDM, ADS-B 1090ES extended squitter, Picogrid Legion, ASTERIX category 021,
STANAG 4676 / AEDP-12 Edition B NITS tracks, STANAG 4607 / AEDP-4607 Edition A GMTI, and
ASTERIX category 048 monoradar target reports. Without a canonical model in the middle, nine
adapters means thirty-six translations and nine private notions of "a contact". With one, an
adapter is a thin translator and nothing else.

**Shipped so far:**

| Adapter | Direction | Reads / writes |
|---|---|---|
| [`pntmap`](adapters/pntmap.py) 1.0.0 | ingest | PNTMAP GNSS interference alerts (JSON) → `Entity` + `Event`. The reference adapter — read it first |
| [`tak`](adapters/tak.py) 1.0.0 | bidirectional | Cursor-on-Target atoms (XML) → `Entity` + `Event`; `PlanObject` → a `u-d-f` drawing, `Entity` → an atom |
| [`ais`](adapters/ais.py) 1.0.0 | bidirectional | AIS NMEA 0183 AIVDM/AIVDO sentences (types 1/2/3, 4, 5, 18/19, 21) → `Entity` + `Event`; `Entity` or `Track` → sentences. The sentinel-heaviest format so far, and the one with no extension point |
| [`adsb`](adapters/adsb.py) 1.0.0 | bidirectional | ADS-B 1090ES extended squitter frames, Mode S DF17/DF18 (type codes 1-4, 5-8, 0 and 9-18, 19, 20-22, 28, 31) → `Entity` + `Event`; `Entity` or `Track` → DF17 frames. A binary format with a CRC gate, two altitudes that are two different measurements, and no unambiguous position in a single frame |
| [`legion`](adapters/legion.py) 1.0.0 | ingest | Picogrid Legion Platform API v3 response documents (Entity, Track, Entity/Track Location, Locations list, Event) → `Entity` + `Event` + `Track`. The first REST upstream: transport stays with the caller, one page is one Track, and the coordinates default to geocentric metres |
| [`cat021`](adapters/asterix_cat021.py) 1.0.0 | bidirectional | ASTERIX category 021 ADS-B target reports, EUROCONTROL SPEC-0149-12 Ed 2.6 with the Reserved Expansion Field Ed 1.5 (all 42 data items, RE and SP) → `Entity` + `Event` **per record**; Entities or a `Track` → one data block. A time of day that carries no date, a quality vocabulary that needs another item to say what it means, and a ground station whose verdicts it carries without re-deciding |
| [`stanag4676`](adapters/stanag4676.py) 1.0.0 | bidirectional | STANAG 4676 / AEDP-12 **Edition B Version 2** NITS tracks — the full UML model, 48 classes and 273 attributes → an `Entity` + a `Track` per `TrackData` and an `Event` per detection, motion event, linkage and retraction; back to one STANDALONE `NITSRoot`. Six coordinate systems of which three cannot yield a position, a mandatory STANAG 4774 confidentiality label that is carried and never invented, and a format that models fusion without asking a translator to perform it. **The XML element binding is provisional** — the normative XSD is distributed through national representatives and is not pinned here |
| [`gmti`](adapters/gmtif.py) 1.0.0 | bidirectional | STANAG 4607 / AEDP-4607 **Edition A Version 1** GMTI packets — the packet header, the segment header and all ten defined segments, 212 fields → one `Entity` + `Track` for the **platform** and an `Entity` + `DETECTION` `Event` **per target report**; back to one packet, **byte for byte**. The first non-text wire format: seven numeric encodings on their own tested codec layer ([`gmtif_codec`](adapters/gmtif_codec.py)), existence masks that govern every subsequent field offset, and a format whose targets are detections rather than tracks — so **no target `Track` is ever emitted**, because associating reports across dwells is what a GMTI tracker does and the standard's own guide sends the reader to the sensor vendor for the rule |
| [`cat048`](adapters/asterix_cat048.py) 1.0.0 | bidirectional | ASTERIX category 048 monoradar target reports, EUROCONTROL SPEC-0149-4 **Edition 1.32** (all 28 UAP data items, SP and RE) → `Entity` + `Event` **per record**; Entities → one data block, **byte for byte**, on its own tested codec layer ([`cat048_codec`](adapters/cat048_codec.py)). The sensor-side complement of `cat021`, and the first adapter whose ordinary case is a `DETECTION` rather than a `TRACK_UPDATE` — a radar detects where AIS, ADS-B and CAT021 receive self-reports. **Position is derived only when the caller injects a `sensor_position`**: the format states slant range and azimuth from a station whose location it never carries, and the geodesy is not in the specification at all |

    external format ──▶ Adapter.to_cdm() ──▶ Entity | Event | Track | PlanObject ──▶ platform
    platform        ──▶ Adapter.from_cdm() ─▶ external format          (egress, e.g. TAK)

Quick start, from the repository root:

```bash
pip install -e packages/cdm                 # or: pip install synapse_cdm
pytest -q                                   # the suite runs without installing anything

python -m synapse_cdm.harness --adapter pntmap --fixtures packages/cdm/synapse_cdm/fixtures/pntmap
python -m synapse_cdm.schemas --check --out schemas   # fail if the published schemas are stale
```

The two commands also install as `cdm-harness` and `cdm-schemas`. `pytest` needs no install
because `pytest.ini` puts `packages/cdm` on the path — the suite judges the working tree, not
whatever wheel happens to be in the environment.

## The four canonical objects

| Object | Means | Key fields |
|---|---|---|
| `Entity` | something that **exists** | `entity_id`, `entity_type`, `affiliation`, `position`, `kinematics`, `valid_from/to`, `confidence`, `attributes` |
| `Event` | something that **happened** | `event_id`, `event_type`, `severity`, `related_entities`, `geometry`, `payload`, `observed_at`, `received_at` |
| `Track` | an entity's **position history** | `track_id`, `entity_id`, `samples[]`, `track_quality` |
| `PlanObject` | something we **push out** | `object_id`, `object_type`, `geometry`, `style`, `label`, `expires_at` |

Every one of them also carries, from `CDMBase`:

- `schema_version` — semver, in **every** serialised object (see [MIGRATIONS.md](MIGRATIONS.md));
- `source` — `{system, adapter, adapter_version, synthetic}`: which translator produced this;
- `source_ids[]` — the external identifiers the object is known by, **at least one**;
- `object_kind` — the discriminator, so a mixed stream can be validated without guessing;
- `integrity` — the PQC signature block: **designed, deliberately not implemented**.

One source payload legitimately becomes several objects. A PNTMAP alert is an
`INTERFERENCE_SOURCE` entity *and* a `GNSS_INTERFERENCE` event, so `to_cdm()` returns a list.

## The rules, and where each one is enforced

**1. Adapters never drop data.** A field with no canonical home goes into `Entity.attributes`
or `Event.payload`, parked under `source_extras` by `lossless.residual()`. Enforced: the
harness compares every scalar in the source payload against the CDM output and **fails** the
adapter on a value that appears nowhere. Values that legitimately change (a unit conversion, a
re-rendered timestamp) are declared in the adapter's `TRANSFORMS` with a reason, and the
harness **prints every declaration on every run** — an exemption is a visible line in the
report, not a silent skip.

**2. Adapters are pure translation.** No filtering, no enrichment, no thresholds. Each of
those is a decision, and a decision made inside a translator is invisible to the audit trail
and unattributable. The reference adapter demonstrates the rule where it is most tempting: a
GNSS jamming emitter gets `affiliation: UNKNOWN` unless the payload states an attribution.

**3. An unknown position is `null`, never `(0, 0)`.** Structural, not conventional:
`Position` requires `lat` and `lon`, so "unknown" cannot be spelled as zeros — it is spelled
by the absence of a `Position`. Note the mirror-image defect: `0.0` **is** a real coordinate,
so `if not lat` is as wrong as null-to-zero. Both directions have a fixture and a test.

**4. An unknown scalar is `None`, never `0`.** 0 kt is measured stillness, 0° is due north,
confidence 0 is certainty-that-*not*. A source's "value not available" sentinel (AIS sends
102.3 for unknown speed) is translated, never passed through.

**5. Every object states whether it is exercise data.** `source.synthetic` is required and has
**no default** — mislabelling exercise data as live can reach an operational picture, and
mislabelling live data as exercise hides it from an operator. Neither direction is safe to
guess, so the format makes someone state it.

**6. Identity is derived, never drawn.** `entity_id` is `uuid5(namespace, system|external_id)`
(`ids.py`), so the tenth report about one emitter updates one entity instead of creating a
tenth. It also makes golden-output tests possible at all. An adapter with no stable upstream
identifier must record what it keyed on (`attributes.entity_id_basis`).

**7. Time has one serialised form.** RFC 3339 UTC, exactly three decimals, always `Z` — the
same pattern the Track contract pins, because two timestamps meaning the same instant must
compare equal as *strings* in golden diffs and chain hashes. `received_at` comes from an
injected clock; adapter code never calls `datetime.now()`.

## Writing the next adapter

Read `adapters/pntmap.py` first — every rule above appears in it at least once. Then read
`adapters/ais.py` if your format is binary, packs several fields into one wire value, or spells
"unknown" as an in-band number — it has ten such sentinels, one of which (draught 0.0) is also
a plausible reading, and it is the one adapter whose egress format has nowhere to park a field
it cannot map. Or read `adapters/tak.py`, which is where the awkward cases live: XML rather than JSON, a bidirectional
`from_cdm()`, a source sentinel that must become null, an enum collapse that has to stay
recoverable, and the two fixture forms an XML adapter needs in order to be checked at all.

Read `adapters/adsb.py` for the case where the format does not give you the value at all. Three
of its problems recur in any surveillance feed: a **frame with no timestamp**, so `observed_at`
is receipt time and has to say so; a **position that needs a second message** to resolve, which
is where the line between translation and fusion gets drawn and where a reference position
supplied as *configuration* is legitimate while a cache is not; and **two fields that look like
one** — a barometric and a GNSS altitude, which must not be collapsed into `alt_m` however
convenient it would be. It is also the adapter whose gate earned its keep most visibly: the
byte-exact round trip found two silent data losses that every other check passed.

Then:

**1. Declare the class.** The contract is checked at class-definition time, so a mistake here
fails at import rather than at 03:00 on the first outbound push.

```python
class TakAdapter(Adapter):
    name = "tak"                     # unique; how the harness and every SourceRef name you
    version = "0.1.0"                # semver; goes into source.adapter_version
    direction = "bidirectional"      # then you MUST override from_cdm()
    system = "TAK"

    TRANSFORMS = {"event.@time": "re-rendered into the CDM's fixed-millisecond form"}

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        ...
```

**2. Map the fields.** [FORMAT_COVERAGE.md](FORMAT_COVERAGE.md) already holds the CoT and
STANAG 4676 mappings, row by row, with the six known gaps named — that table is your
specification, and a test resolves every path in it against the models so it cannot go stale.

**3. Park everything else.** List the dotted paths you consumed, hand them to
`lossless.residual(raw, consumed)`, and put the result in `attributes["source_extras"]` /
`payload["source_extras"]`. Do not enumerate leftovers by hand: the block a source adds in its
next firmware release is exactly the one nobody remembers.

**4. Refuse what you cannot read.** A missing required field or an unmappable severity raises.
Do not default it — an alert that arrives labelled `INFO` because its severity was unreadable
is worse than one that fails loudly. An enum that *has* an `UNKNOWN` member is different: use
it, and keep the source's own word in `attributes`.

**5. Ship fixtures.** At least three synthetic payloads under
`packages/cdm/synapse_cdm/fixtures/<name>/`, including one that exercises the awkward path (a missing
position, an unknown type, a vendor block you have never seen). No real data, ever.

**6. Record the golden output and read it.**

```bash
python -m synapse_cdm.harness --adapter tak --fixtures packages/cdm/synapse_cdm/fixtures/tak --update-golden
```

Then **review the diff before committing it** — `--update-golden` is how a defect becomes the
expectation. Both defects found while building the reference adapter were caught by reading a
golden file, not by a failing test.

**7. Add the tests.** Copy the shape of `tests/test_cdm_pntmap_adapter.py`: one test per claim
in your adapter's docstring. If you are bidirectional, the harness already round-trips you —
declare `direction = "bidirectional"`, override `from_cdm()`, and the `roundtrip` column checks
that no source value goes missing on the way out. It compares values, not bytes: a byte-equal
round trip is neither achievable nor the point (key order changes, omitted optional fields come
back explicit, XML attribute order is arbitrary). An adapter emitting XML or USMTF gets `SKIP`
there and must ship its own round-trip test.

## The harness

```
python -m synapse_cdm.harness --adapter <name|module:Class> --fixtures <dir> [--json]
                              [--schemas schemas] [--now <RFC3339>] [--update-golden]
                              [--synthetic true|false]
```

Five checks per fixture, and an unrun check reports `SKIP` — never `PASS`:

| Check | Fails when |
|---|---|
| `translate` | `to_cdm()` raised. One bad fixture never stops the run; the rest are still judged. |
| `schema` | an object violates the **published** JSON Schema in `/schemas` (not the model — the schema is what other languages read). |
| `provenance` | `source.*` incomplete, `synthetic` unstated, `source_ids` empty, an event missing a timestamp. |
| `lossless` | a source value appears nowhere in the output and is not a declared transform. |
| `roundtrip` | for an `egress`/`bidirectional` adapter: a value present in the source payload is absent from what `from_cdm()` emits. `SKIP` for ingest-only adapters. |
| `golden` | the output differs from the recorded expectation, reported path by path. |

Nothing in the harness knows anything about any particular adapter — it resolves
`module:ClassName` as readily as a registered name, which is what makes it usable as the gate
for adapters the AI adapter factory generates and this repository has never seen.

### Three things the harness cannot check for you

Adapter #11 mutation-checked its own assertions and each mutation found a hole that a green run
had been hiding. All three generalise, so they are here rather than in one adapter's notes.

**A fixture whose behaviour is invariant under the harness clock exercises nothing.** The harness
injects ONE frozen instant for a whole fixture directory. CAT048's two midnight-rollover fixtures
describe times of day that resolve to the receipt date at that instant — so they produced correct
golden files, passed every check, and tested no rollover in either direction. A fixture that
depends on the *relationship* between the payload's time and the clock has to inject its own clock
from `tests/`, and the fixture row should say so; the harness pass is about the golden file, not
about the behaviour. This will recur for every format that states a time of day without a date,
which is most of them.

**A round trip proves self-consistency, never correctness. Correctness needs an external anchor.**
`encode(decode(x)) == x` and `inverse(direct(x)) == x` both pass when the two halves share a wrong
constant, because the error cancels. Replacing WGS-84's semi-major axis with its semi-minor — a
21 km error — passed every one of CAT048's geodesic inversion tests for exactly that reason. The
hole class is **any derive/invert pair whose shared constants encode a MODEL rather than a single
documented scale factor**: an LSB is one number a reviewer checks against the specification by
eye, an ellipsoid or a projection is not, and only the second kind can hide inside a round trip.
So audit the model separately, against something outside the implementation —

- `cat048_codec` pins WGS-84 by its published constants and by three geodesic distances computed
  independently of it (one degree of longitude at the equator, one of latitude, the quarter
  meridian).
- `gmtif_codec` already had the right shape and it is worth naming as the pattern: its strongest
  tests are the worked examples the standard itself prints — `BA16 0101100100011100` = 125.31006°
  and −34.876099° = `SA16 1100111001100110` — which are anchors the implementation cannot
  influence.
- `asterix_cat021`'s scale factors are the safe kind: each is a single stated LSB, checkable
  against the document without running anything.

**The roster sweep is a manual protocol act, and prose counts are what it is for.** When an
adapter joins the shipped roster, six documents restate how many adapters there are and three of
them do the pair arithmetic as well — and nothing in the harness reads prose. The sweep is:

1. **`grep` every spelled-out number within 120 characters of the word "adapter"**, across
   `*.md`, `*.mdx` and `*.py`. The narrower form — grepping for the *previous* count word, "eight"
   or "nine" — is what the adapter #11 sweep started with, and it missed
   `synapse_cdm/__init__.py`, which still said "five adapters means ten translations" four
   adapters later. A site that is stale by more than one release does not contain the previous
   count word, so searching for it cannot find the sites that have drifted furthest.
2. **Check the pair arithmetic at every site that states a number**, not just the count. Two
   documents disagreed on whether it is `N×(N−1)` or `N(N−1)/2`, which for nine adapters is 72
   against 36; neither was wrong on its own page and together they were a contradiction.
3. **Read every sentence that states the count TWICE.** `symbology.py` and
   `docs/docs/cdm/entity.mdx` both carry "so that nine adapters cannot grow nine slightly
   different opinions", and commit 94c000a had to repair that sentence half-updated —
   "seven adapters cannot grow six" — which reads as prose either way.
4. **Read the gap list's own tallies.** `FORMAT_COVERAGE.md` gap 1 counts how many adapters park
   a private name key, and it had been undercounting itself by one adapter since adapter #6. A
   count that IS the argument decays exactly like any other.

**A structured-status counter is blind to all of this.** The adapter #11 flip counter walked every
`Status`-bearing table row, correctly reported zero rows left saying `not yet`, and did not see
the two prose sentences in the same section that still described the row set as unimplemented.
Anything that parses tables will report clean while the paragraphs around them contradict them.

`tests/test_cdm_prose_counts.py` now pins the six sites the sweep has already had to fix, so a
half-edit at a KNOWN site fails a build. It is deliberately an allowlist and not a scanner — a
general prose-number check would flag "two altitudes that are two different measurements" and
need an exemption list larger than the sweep it replaced — so **finding a NEW site is still the
sweep's job**, and adding it to that allowlist is how the sweep's work stops being undone.

None of the three is something the five checks can produce, and that is the point of writing them
down here: a green harness run is a floor.

## Layout

Repository root, then the package:

```
packages/cdm/
  pyproject.toml    distribution metadata; version is READ FROM version.py, never restated
  synapse_cdm/
    models.py       the four objects, Position, Kinematics, SourceRef, Integrity, payloads
    enums.py        closed vocabularies; UNKNOWN is a member, never a null
    geo.py          GeoJSON Point/LineString/Polygon, [lon, lat], ring closure enforced
    times.py        one timestamp form, one injectable clock
    ids.py          derived stable identity (uuid5) and the id basis
    version.py      SCHEMA_VERSION and the compatibility rule
    symbology.py    MIL-STD-2525D standard identity, CoT affiliation letters
    lossless.py     the never-drop rule as a computable check
    adapter.py      the Adapter ABC, its class-definition-time gates, the registry
    schemas.py      JSON Schema export (+ --check for CI)
    harness.py      the adapter-agnostic validation harness
    adapters/       one module per external system (pntmap, tak, ais, adsb)
    fixtures/       synthetic payloads + golden outputs
schemas/            published JSON Schema, generated — never hand-edited
tests/test_cdm_*.py
```

`schemas/` sits at the repository root rather than inside the package because it is the
artefact for OTHER languages: a Go or TypeScript consumer clones this repository and reads
those files, and burying the one thing they need under a Python package layout would be a
Python assumption in a deliberately language-neutral contract. The generator writes both
copies from one source — `python -m synapse_cdm.schemas --check --out schemas` is the CI
form and fails on any drift.

`synapse_cdm` depends on nothing but `pydantic` and `jsonschema` — in particular nothing from
the SynapseCommand product repository (`agents/`, `core/`, `platform/`, `synapse-data/`,
`airtasking/`) — which is why it could be lifted out into this repository at all. It also
contains no crypto: the `integrity` field is designed and deliberately unpopulated, because a
signature computed inside a translator is held by nothing that audits it. Both properties are
enforced by AST over the package's own sources in `tests/test_cdm_boundary.py`, not by this
paragraph.
