# `synapse_cdm` — the Canonical Data Model and adapter framework

Thirteen integration adapters are shipped: PNTMAP GNSS alerts, TAK / Cursor-on-Target, AIS /
NMEA 0183 AIVDM, ADS-B 1090ES extended squitter, Picogrid Legion, ASTERIX category 021,
STANAG 4676 / AEDP-12 Edition B NITS tracks, STANAG 4607 / AEDP-4607 Edition A GMTI,
STANAG 4609 / MISP-2019.1 UAS Datalink Local Set KLV metadata,
ASTERIX category 048 monoradar target reports, ASTERIX category 034 monoradar service
messages, ASTERIX category 062 SDPS system track messages, and ASTERIX category 023 CNS/ATM
ground station and service status reports. Without a canonical model in the middle, thirteen
adapters means seventy-eight translations and thirteen private notions of "a contact".
With one, an adapter is a thin translator and nothing else.

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
| [`cat034`](adapters/asterix_cat034.py) 1.0.0 | bidirectional | ASTERIX category 034 monoradar service messages, EUROCONTROL SPEC-0149-2b **Edition 1.29** (all 14 UAP FRNs, all 12 data items, RE and SP) → `Entity` + `Event` **per record**; Entities → one data block, **byte for byte**, on its own tested codec layer ([`cat034_codec`](adapters/cat034_codec.py)). **The first adapter whose primary object is the sensor itself** — every record describes the radar station, so `entity_type` is `SENSOR`, the SAC/SIC that `cat048` parks as a sensor identifier is a `SourceId` here, and no object carries `Kinematics` because the one bearing the category states is the antenna's. Table 2's M/O/X matrix is the encoding rule for eleven of the twelve items, and it is what rules out ever deriving a `Geometry` from the Generic Polar Window: the window and the station's own position are mutually exclusive across all seven message types |
| [`cat062`](adapters/asterix_cat062.py) 1.0.0 | bidirectional | ASTERIX category 062 SDPS track messages, EUROCONTROL SPEC-0149-9 **Edition 1.21** with the Reserved Expansion Field **Edition 1.3** (all 35 UAP slots, all 27 data items, all five REF items, SP) → `Entity` + `Event` **per record**; Entities → one data block, **byte for byte**, on its own tested codec layer ([`cat062_codec`](adapters/cat062_codec.py)). **The first adapter whose input is already the output of a fusion process** — an SDPS system track, correlated from radars, Mode S interrogators, multilateration, ADS-B and ADS-C and then correlated with a flight plan. The per-technology update ages, the thirty-one per-parameter ages, the amalgamation and coasting flags, the contributing-sensor lists and the tracker's own estimated standard deviations are the **upstream system's statements about its own processing**, collected under `attributes.fusion_provenance` with the SAC/SIC of the system that made them, and acted on nowhere. Identity is the Mode S address where the record states one; the system track number is **never** the basis, because sixteen bits allocated by the emitting system and recycled would merge two airframes into one entity |
| [`cat023`](adapters/asterix_cat023.py) 1.0.0 | bidirectional | ASTERIX category 023 CNS/ATM ground station and service status reports, EUROCONTROL SPEC-0149-16 **Edition 1.3** (all 14 UAP FRNs, all 9 data items, RE and SP) → `Entity` + `Event` **per record**, and a **second `Entity` for the SERVICE** on the two report types that are about one; Entities → one data block, **byte for byte**, on its own tested codec layer ([`cat023_codec`](adapters/cat023_codec.py)). **The first adapter here that emits two Entities from one record** — §4.5.1.2 requires each of a station's services to be reported independently, so a service is an object keyed on the pair `(SAC/SIC, Service Identification)` and both ids ride on one `Event`, which records the relationship without joining anything. Nine items and **not one coordinate**: `Entity.position` is `None` on every object and `Event.geometry` is `None` permanently, because `I023/200` is a radius with no centre. Three of its nine items have an `FX` bit that names an extension the document never defines, and all three refuse |

| [`stanag4609`](adapters/stanag4609.py) 1.0.0 | bidirectional | STANAG 4609 / MISP-2019.1 **UAS Datalink Local Set** KLV metadata, MISB ST 0601.14a (**26 of its 141 items** — the witnessed set one pinned real stream attests; the other 115 rows read `not yet`) → `Entity` + `Event` **per packet**; Entities → one payload, **byte for byte**, on two tested codec layers ([`klv_codec`](adapters/klv_codec.py) for the framing, [`klv_uas_codec`](adapters/klv_uas_codec.py) for the tag table). **The first adapter here whose format defines a real checksum** — `ST 0601.14-32` makes it mandatory in every packet, where the five binary siblings each had to record that theirs defines none — and the first to ship a **codec ruling**: the one real stream carries an item at four octets where its own standard states a Required Length of two, so the length-divergence policy skips that item and records a structured defect annotation rather than rejecting the packet or reinterpreting the octets. `entity_id` is **packet-scoped**, because the witnessed set carries no identifier at all — items 3, 4, 10, 59 and 94 are the five that could and the stream has none of them, so consecutive packets of one aircraft get different ids and gap 30 records the cost |
    external format ──▶ Adapter.to_cdm() ──▶ Entity | Event | Track | PlanObject ──▶ platform
    platform        ──▶ Adapter.from_cdm() ─▶ external format          (egress, e.g. TAK)

## Quick start

**Using it.** Nothing but the package, from any directory:

```bash
pip install synapse-cdm

python -m synapse_cdm.harness --adapter pntmap        # replays the fixtures that came with it
python -m synapse_cdm.schemas --out ./schemas         # writes the six JSON Schemas, anywhere

python -m synapse_cdm.harness --list-adapters         # the names --adapter takes
```

`--fixtures` is optional for an adapter this package ships: omitted, the harness asks the import
system where its own fixtures are and replays those, wherever the package is installed. Pass it
to replay your own set. Both commands also install as `cdm-harness` and `cdm-schemas`.

**`--list-adapters` shipped in 1.1.0.** It was on `main` and absent from 1.0.0 for one release,
and this paragraph carried that warning; on an installed 1.0.0 the third command above still fails
with argparse's `unrecognized arguments`, which is worth knowing only if that is the version you
have. From 1.1.0 the roster is a command rather than a table to trust. See MIGRATIONS.md,
"1.1.0".

The wheel deliberately carries no copy of the published schemas — a third copy of a generated
artefact is a third thing that can go stale — so `python -m synapse_cdm.schemas --out <dir>`
produces them on demand instead, and they are identical to the ones the repository publishes.

**Working on it.** From a clone of the repository:

```bash
pip install -e "packages/cdm[test]"                   # the package, its two deps, and pytest
pytest -q                                             # the whole suite
python -m synapse_cdm.schemas --check --out schemas   # fail if the published schemas are stale
python gates/wheel_install.py                         # and that the WHEEL is what was tested
```

`pytest.ini` puts `packages/cdm` on the path, so the suite judges the working tree rather than
whatever wheel happens to be in the environment. That is deliberate and it has a cost — nothing
in the suite exercises the artefact a partner receives — which is what `gates/wheel_install.py`
is for: it builds the distribution, installs it into a clean environment and runs the harness and
half the suite against **that**.

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

**5. Ship fixtures.** At least three synthetic payloads in this package's `fixtures/<name>/`,
including one that exercises the awkward path (a missing position, an unknown type, a vendor
block you have never seen). No real data, ever. If your adapter lives outside this package, put
them wherever you like and pass `--fixtures` — the harness is not fussy about where they are, only
about there being some.

**6. Record the golden output and read it.**

```bash
python -m synapse_cdm.harness --adapter tak --update-golden
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
python -m synapse_cdm.harness --adapter <name|module:Class> [--fixtures <dir>] [--json]
                              [--schemas <dir>] [--now <RFC3339>] [--update-golden]
                              [--synthetic true|false]
python -m synapse_cdm.harness --list-adapters [--json]
```

`--list-adapters` prints the registry and exits `0`: name, version, direction, **fixture
directory** and system. The fixture column is there because `stanag4676` replays `fixtures/nits`
and that relation was folklore until `Adapter.fixture_dir` made it a declaration — folklore that
produced a nine-adapter sweep reporting nine greens with one of them vacuous. Before this flag the
roster was reachable only by getting something wrong: `--adapter typo` returns it inside a
`LookupError`, and a bare invocation returns argparse's usage line, which names `--adapter` and
not one value it takes. **It shipped in 1.1.0**; on 1.0.0 — the one release without it —
the roster needed a clone or an editable install.

Six checks per fixture, and an unrun check reports `SKIP` — never `PASS`:

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

**Exit codes: `0` every fixture passed, `1` fixtures ran and some failed, `2` the run could not
happen — no fixture matched, the `--schemas` directory held no schemas, or `--fixtures` was
omitted for an adapter this package does not ship.** The third one exists because `2` and `1` send a reader to different places — `1` says
debug the adapter, `2` says fix the path you passed — and because a run that matched nothing used
to exit `0` with `0 passed, 0 failed`. It does not any more: an absent directory, an empty one and
one whose only content is a `spec/` subdirectory are the same failure, and the message names the
adapter, the directory searched and the rule that selected nothing. `--json` prints nothing at all
in that case, because the shape of a report is itself a claim that fixtures were judged.

**The fixture directory is not always the adapter's name, and you no longer have to know that.**
`stanag4676` reads its fixtures from `fixtures/nits` — the adapter is named for a covering
document and the directory for the bytes it holds — and pointing `--fixtures` at
`fixtures/stanag4676` is the invocation that used to pass vacuously, because that directory holds
only pinned standards. Each adapter now DECLARES its directory (`Adapter.fixture_dir`) and the
harness resolves it through `importlib.resources`, so omitting `--fixtures` is always right for a
shipped adapter. `tests/test_cdm_harness.py` holds the same map written out by hand and requires
the two to agree, so a new adapter cannot join the roster without one.

**`--fixtures` is required for `module:ClassName`**, and refused rather than guessed at. This
package ships fixtures for the adapters IT ships; guessing at `fixtures/<your name>` would either
miss — a failure naming a directory you never mentioned — or HIT, because your adapter's name
collided with one of ours, and then your code is judged against our payloads and every check
passes or fails for reasons that have nothing to do with it.

### Four things the harness cannot check for you

Adapter #11 mutation-checked its own assertions and each mutation found a hole that a green run
had been hiding. They generalise, so they are here rather than in one adapter's notes. The last
arrived later and by a different route — from verifying a published release rather than from
mutating an adapter — and it is a property of the DISTRIBUTION rather than of any adapter.

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

**A wheel-only consumer cannot run any round-trip proof for an adapter with a non-JSON egress,
and the harness says so in a sentence that points where the wheel does not reach.** `roundtrip`
reports `SKIP` when `from_cdm()` returns bytes it cannot compare structurally, and the SKIP text
reads "the adapter must ship its own round-trip test in `tests/`". That instruction is correct and
it is unreachable from a wheel: `tests/` is not packaged, so a consumer who installed from PyPI
reads a pointer to a directory they do not have. It is not a defect in any adapter and not a defect
in a release — it is the shape of the distribution, and it has been true of every version. What it
costs is specific rather than general: `lossless` and the schema checks still run and still prove
what they prove, so the floor a wheel-only consumer gets is **ingress** conformance, and egress
byte-exactness is proved only in a clone. Every adapter that declares an egress direction is
affected — eleven of the thirteen shipped adapters, every one of which emits something the check
cannot parse as JSON, leaving only the two ingest-only adapters unaffected for a different reason.
Two things would change it and neither is free: packaging the round-trip tests, which puts a test
suite inside a runtime distribution; or giving the harness a comparison that works on the emitted
bytes per format, which is the codec-level work each of those adapters already does in `tests/`.
Recorded here rather than fixed in passing, and recorded as reach rather than as a count of one
release: it is what a wheel-only conformance claim does NOT cover, and the person who needs to know
is the one reading `20 passed, 0 failed` from an installed copy.

**The roster sweep is a manual protocol act, and prose counts are what it is for.** When an
adapter joins the shipped roster, every document that restates how many adapters there are has to
move with it, and the ones that also do the pair arithmetic have to move twice — and nothing in
the harness reads prose. This paragraph states no total, on the same reasoning as the last of the
rules below: a restated count re-drifts and a citation cannot. The allowlist named at the end of
this section is the enumeration, and it is a floor rather than a census, because an allowlist
cannot find a site nobody has added to it. The sweep is:

1. **`grep` every spelled-out number within 120 characters of the word "adapter"**, across
   `*.md`, `*.mdx` and `*.py`. The narrower form — grepping for the *previous* count word, "eight"
   or "nine" — is what the adapter #11 sweep started with, and it missed
   `synapse_cdm/__init__.py`, which still said "five adapters means ten translations" four
   adapters later. A site that is stale by more than one release does not contain the previous
   count word, so searching for it cannot find the sites that have drifted furthest.
2. **Check the pair arithmetic at every site that states a number**, not just the count. Two
   documents disagreed on whether it is `N×(N−1)` or `N(N−1)/2`, which for the nine adapters of
   the day was 72 against 36; neither was wrong on its own page and together they were a
   contradiction. At today's thirteen adapters it is 156 against 78.
3. **Read every sentence that states the count TWICE.** `symbology.py` and
   `docs/docs/cdm/entity.mdx` both carry "so that thirteen adapters cannot grow thirteen slightly
   different opinions", and commit 94c000a had to repair that sentence half-updated —
   "seven adapters cannot grow six" — which reads as prose either way.
4. **Read the gap list's own tallies.** `FORMAT_COVERAGE.md` gap 1 counts how many adapters park
   a private name key, and it had been undercounting itself by one adapter since adapter #6. A
   count that IS the argument decays exactly like any other.
5. **Count the SUBSETS too, and not only the roster.** A count that names a subset — "the
   `ICAO24` namespace serves N adapters", "the contract has been stable across all N of them" —
   looks safe because it is not the roster count, and drifts for the same reason with nothing
   watching. The SDK close-out sweep found both of those wrong: `version.py` argued the
   1.0.0-not-0.x ruling from "ten adapters are shipped … stable across all NINE of them", one
   sentence stating the count twice and half-updated; and `stanag4676.py` said three adapters
   share the `ICAO24` source-id namespace when `cat048` had made it four. The second is the
   harder shape, because the subset is derivable from the code and the prose was the only place
   it was ever counted.
6. **Know which counts are NOT drift, so the sweep does not churn them.** Two kinds are correct
   while disagreeing with today's roster, and both have to stay: a **past-tense narrative** about
   a specific past run (`harness.py` and `adapter.py` both describe "a gate sweep over all nine
   adapters", which is a thing that happened, not a claim about now — the past tense is what
   marks it, and where it would not, this repository writes "of the day"), and a **changelog
   entry**, where "now serves three adapters" means at that release and updating it would falsify
   the record. `tests/test_cdm_prose_counts.py` exempts the `MIGRATIONS.md` occurrence by path
   and then requires it to still be inside `## History` and still to be *behind* today's number,
   so the exemption cannot quietly come to cover a live claim.
7. **Prefer deleting a restated count to re-syncing it.** Two sites this round said what gap 1's
   table already said and both were stale — `ais.py` at "four keys across two adapters" and the
   NITS section at "four private keys… no seventh key" while the table read eight and seven.
   Neither was re-synced; both now cite gap 1 and state no number, because a second statement
   re-drifts and a citation cannot.
8. **PIN THE DERIVATION, not just the number — and this rule exists because a count was
   mis-derived twice, identically, by two rounds that had each just diagnosed the same class of
   defect.** The number in question is how many times one phrase occurs across this repository —
   the phrase written `1\.1\.0 candidate` throughout this rule, **as the regex rather than as
   itself, because a paragraph that spelled it out would change the count it describes** — which
   two consecutive commits asserted as an untouchable at **35** while the derivation each round
   actually typed was a `grep` over a hand-written list
   of extensions — `*.md`, `*.py`, `*.json` — which **excludes `docs/docs/changelog.mdx` and yields
   34**. The assertion was right and the derivation behind it was wrong, which is the worst
   arrangement of the two: nothing failed, and the next round inherited a method that disagrees
   with the answer it produces.

   **The repair is that the file set is `git ls-files` and there is no extension list anywhere.**
   Stated once, as one command a human can run:

   ```bash
   git ls-files -z | xargs -0 grep -Ioh '1\.1\.0 candidate' | wc -l    # 35
   ```

   and implemented once, in `tests/test_cdm_prose_counts.py`'s
   `occurrences_over_tracked_files()`, which **the guard itself calls** — so the check and the
   checker cannot disagree, because there is only one of them. Any extension a future round adds
   to the tree is inside the derivation the moment `git` tracks it, which is the property a
   remembered list of suffixes cannot have. The general rule: **a count whose derivation is a
   command somebody retypes each round is a count that will be re-derived differently.**

**A structured-status counter is blind to all of this.** The adapter #11 flip counter walked every
`Status`-bearing table row, correctly reported zero rows left saying `not yet`, and did not see
the two prose sentences in the same section that still described the row set as unimplemented.
Anything that parses tables will report clean while the paragraphs around them contradict them.

`tests/test_cdm_prose_counts.py` now pins the sites in eight documents — the ones the sweep had to
repair, and the ones it found correct and unguarded, which is the state every one of the others
was in before it drifted — so a half-edit at a KNOWN site fails a build. **It also pins one
phrase-occurrence count over the whole tracked tree**, which is rule 8's repair and the only check
in that module whose file set is `git ls-files` rather than an allowlisted path. It is deliberately an
allowlist and not a scanner — a general prose-number check would flag "two altitudes that are two
different measurements" and need an exemption list larger than the sweep it replaced — so
**finding a NEW site is still the sweep's job**, and adding it to that allowlist is how the
sweep's work stops being undone. This file is the one exception, and only inside one fact-class:
every number here that qualifies an adapter, a document or a site is swept file-locally, and each
is either pinned to a derivation or exempt on a ground recorded beside it.

None of them is something the six checks can produce, and that is the point of writing them
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
    adapters/       one module per external system (pntmap, tak, ais, adsb, …)
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
