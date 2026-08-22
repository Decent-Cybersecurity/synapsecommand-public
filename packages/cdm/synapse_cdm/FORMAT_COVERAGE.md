# Format coverage — does the CDM actually carry what these formats need?

The brief asks the model to "map cleanly to Cursor-on-Target, STANAG 4676 track structures and
GeoJSON". This file is that check, done field by field rather than asserted. It is also a
working document for whoever writes the next adapter: the mapping column is the adapter's
specification.

`tests/test_cdm_format_coverage.py` resolves every path in the **CDM field** column against the
actual Pydantic models and fails the build on one that does not exist. That is the only reason
this table can be trusted six months from now — a renamed field breaks the test, not just the
prose.

Paths use `[]` for a list element, e.g. `Track.samples[].observed_at`.

## The status column

`Status` says **who implements the row**, not whether the mapping is believed to be right. The
distinction matters: an unimplemented row is a specification, and a specification nobody has
run is a guess with a table around it.

| Status | Means |
|---|---|
| `tak 1.0.0` | implemented by `adapters/tak.py`, with a fixture and a golden file |
| `tak 1.0.0 · parked` | implemented, but the value lands in `attributes` because of a named gap below |
| `tak 1.0.0 · egress` | implemented in the `from_cdm()` direction |
| `models` | provided by the models themselves; no adapter code is involved |
| `not yet` | no adapter implements this row. The mapping is a specification, not a claim |

## Cursor-on-Target (TAK) — ingest and egress

Implemented by `adapters/tak.py` (bidirectional). Ingest translates a CoT **atom** into an
`Entity` + an `Event`; egress turns a `PlanObject` into a `u-d-f` drawing and an `Entity` back
into an atom. A drawing arriving on *ingest* is deliberately not special-cased — see that
module's docstring for why.

| CoT | CDM field | Status | Notes |
|---|---|---|---|
| `event/@uid` | `Entity.source_ids[].external_id` | `tak 1.0.0` | system `TAK`; the UID is what TAK dedupes on |
| `event/@type` | `Entity.affiliation` | `tak 1.0.0` | via `symbology.affiliation_from_cot`; original string parked at `attributes.cot_type` |
| `event/@type` | `Entity.entity_type` | `tak 1.0.0` | battle-dimension letter (`G`/`A`/`S`) → UNIT/PLATFORM/…; `G` + function `I` → FACILITY, because calling a bridge a UNIT is a false statement and CoT says which |
| `event/@time` | `Event.observed_at` | `tak 1.0.0` | re-rendered to fixed milliseconds — a declared transform |
| `event/@start` | `Entity.valid_from` | `tak 1.0.0` | absent in the wild; falls back to `@time` and RECORDS the fallback at `attributes.valid_from_basis` |
| `event/@stale` | `Entity.valid_to` | `tak 1.0.0` | CoT staleness IS an interval end — maps exactly |
| `event/@how` | `Position.position_source` | `tak 1.0.0` | `m-g` machine/GPS → GNSS, `h-e` human entered → MANUAL; an unrecognised `how` → ESTIMATED, which understates rather than overstates the fix |
| `point/@lat` | `Position.lat` | `tak 1.0.0` | `0.0` is a real coordinate, not a "no position" sentinel |
| `point/@lon` | `Position.lon` | `tak 1.0.0` | absent `@lat`/`@lon` → `position: None`, never (0, 0) |
| `point/@hae` | `Position.alt_m` | `tak 1.0.0` | both WGS84 HAE metres — no conversion. CoT's `9999999` sentinel → null |
| `point/@ce` | `Position.accuracy_m` | `tak 1.0.0` | circular error, metres. `9999999` → null |
| `point/@le` | `Entity.attributes` | `tak 1.0.0 · parked` | **gap 6** — no canonical linear (vertical) error field; parked at `attributes.vertical_error_m` |
| `detail/track/@speed` | `Kinematics.speed_mps` | `tak 1.0.0` | CoT speed is m/s — no conversion |
| `detail/track/@course` | `Kinematics.course_deg` | `tak 1.0.0` | degrees true; CoT's `360.0` is reduced to `0.0`, the same bearing and the only one the field admits |
| `detail/contact/@callsign` | `Entity.attributes` | `tak 1.0.0 · parked` | **gap 1** — no canonical name field; parked at `attributes.callsign` |
| `detail/remarks` | `Entity.attributes` | `tak 1.0.0` | free text, no canonical home by design |
| `detail/__group/@name` | `Entity.attributes` | `tak 1.0.0` | colour-based team, not an affiliation |
| drawing `u-d-f` shapes | `PlanObject.geometry` | `tak 1.0.0 · egress` | one `<link point="lat,lon,hae"/>` per vertex — note CoT's lat,lon order is the reverse of GeoJSON's |
| drawing stroke/fill | `PlanObject.style` | `tak 1.0.0 · egress` | hints only — style may never carry meaning. Unmapped style keys ride on `<synapse_style/>` rather than being dropped |
| drawing label | `PlanObject.label` | `tak 1.0.0 · egress` | `<contact callsign="…"/>`; an unlabelled object emits no element at all |
| `event/@stale` (egress) | `PlanObject.expires_at` | `tak 1.0.0 · egress` | omitted rather than emptied when there is no expiry |

### What the TAK adapter fills that CoT does not state

Found by building it. Each of these is a CDM field with no CoT source, so it is derived or
declared — and each one says so in the object itself rather than leaving a consumer to guess.

| CoT | CDM field | Status | Notes |
|---|---|---|---|
| *(derived)* | `Entity.symbol` | `tak 1.0.0` | CoT states a type, not a 2525D SIDC. Derived from affiliation via `symbology.sidc_from_affiliation`, and `attributes.symbol_basis` says so |
| `event/@uid` + `@time` | `Event.event_id` | `tak 1.0.0` | keyed on BOTH: a CoT uid identifies the object and repeats on every report, so uid alone would collapse a thousand reports into one event |
| *(none — CoT has no urgency field)* | `Event.severity` | `tak 1.0.0` | `INFO`, with `payload.severity_basis` recording that this is the format's silence and not a misread severity |
| *(none)* | `Event.event_type` | `tak 1.0.0` | `TRACK_UPDATE`. `DETECTION` would claim a sensor found something new, which one message cannot establish |
| everything unmapped | `Entity.attributes` | `tak 1.0.0` | `attributes.source_extras`, structure intact — `@version`, `contact/@endpoint`, `__group/@role`, `status/@battery` and anything a future CoT extension adds |
| `PlanObject.object_id` (egress) | `PlanObject.object_id` | `tak 1.0.0 · egress` | on `<synapse_plan/>`: the uid carries the TAK identifier, so without this a consumer holding the drawing cannot get back to the CDM object |

## STANAG 4676 — track ingest

No adapter yet. Every row below is a specification for whoever writes it.

| STANAG 4676 | CDM field | Status | Notes |
|---|---|---|---|
| `TrackMessage/trackUUID` | `Track.track_id` | `not yet` | derive with `ids.derive` when absent |
| `Track/trackNumber` | `Track.source_ids[].external_id` | `not yet` | the operator-facing track number |
| `TrackPoint/trackPointPosition/latitude` | `Track.samples[].position.lat` | `not yet` | |
| `TrackPoint/trackPointPosition/longitude` | `Track.samples[].position.lon` | `not yet` | |
| `TrackPoint/trackPointPosition/hae` | `Track.samples[].position.alt_m` | `not yet` | |
| `TrackPoint/trackPointTime` | `Track.samples[].observed_at` | `not yet` | ordering is validated by `Track` |
| `TrackPoint/trackPointSource` | `Track.samples[].position.position_source` | `not yet` | |
| `TrackPoint/trackPointObjectMass` etc. | `Entity.attributes` | `not yet` | source-specific, parked |
| `TrackPoint/trackPointVelocity` (u,v,w) | `Kinematics.speed_mps` | `not yet` | **gap 4** — vector → scalar+course, a declared transform |
| `TrackPoint/trackPointVelocity` (w) | `Kinematics.climb_mps` | `not yet` | sign convention differs; declare it |
| `Track/trackQuality` | `Track.track_quality` | `not yet` | **gap 3** — 4676 is integer 0–15, CDM is float 0–1 |
| `Track/objectClassification` | `Entity.entity_type` | `not yet` | plus original in `attributes` |
| `Track/classificationConfidence` | `Entity.confidence` | `not yet` | |
| `IdentityIndicator` | `Entity.affiliation` | `not yet` | **gap 2** — 7 values collapse to 4 |
| `exerciseIndicator` | `Entity.source.synthetic` | `not yet` | maps exactly — and this is why `synthetic` has no default |
| `TrackMessage/security/…` | `Entity.attributes` | `not yet` | classification marking lives at the platform gateway, not here |

## GeoJSON (RFC 7946)

| GeoJSON | CDM field | Status | Notes |
|---|---|---|---|
| `Point` | `Event.geometry` | `models` | `[lon, lat]` order enforced in `geo.py` |
| `LineString` | `PlanObject.geometry` | `models` | routes |
| `Polygon` | `Event.geometry` | `models` | jamming footprints; ring closure enforced |
| `Feature.properties` | `PlanObject.style` | `models` | **gap 5** — Feature/FeatureCollection not modelled |
| `bbox` | — | `not yet` | not carried; derivable from geometry |

## Gaps, and what each one costs

1. **No canonical name.** A CoT callsign and a 4676 track number are the strings an operator
   reads, and today they land in `attributes`. Every consumer that wants to label a contact
   has to know which adapter's key to look under, which is exactly the kind of private
   knowledge the CDM exists to abolish. *Proposed: `Entity.label` in 1.1.0 (MINOR — optional
   field).* Deliberately not added on day one: it needs one owner naming its precedence rules
   across sources, not a field added in passing. **Now confirmed by a shipped adapter** — the
   TAK adapter parks every callsign at `attributes.callsign`, so the private knowledge this
   gap describes already exists in the field.
2. **Affiliation collapse, 7 → 4.** PENDING, ASSUMED_FRIEND and SUSPECT have no CDM member
   (see `enums.Affiliation` for why: they are judgements, not wire facts). Recoverable only
   because the adapter parks the original — which the lossless check enforces rather than
   trusts. The TAK adapter parks both the letter (`attributes.cot_affiliation_letter`) and the
   full type string, and a test asserts that SUSPECT becomes UNKNOWN and **not** HOSTILE:
   suspicion is not identification, and that is the direction the collapse must not round
   towards.
3. **Track quality scale.** 4676 integer 0–15 → CDM float 0–1 is `value / 15`, a declared
   transform. Note that 4676 quality 0 means "worst", not "unknown", and CDM `None` means
   unknown — so a missing 4676 quality must become `None`, never `0.0`.
4. **Velocity representation.** 4676 carries a 3-vector; the CDM carries speed/course/climb.
   The conversion is exact arithmetic and reversible, so it is a declared transform rather
   than a gap in meaning — but an adapter must declare it or the lossless check will (correctly)
   flag every velocity component.
5. **Feature / FeatureCollection.** Not modelled. `PlanObject` is the CDM's Feature-equivalent
   (geometry + style + label), and a FeatureCollection is a list of PlanObjects. Adding the
   GeoJSON wrappers would give two ways to say one thing.
6. **Vertical accuracy.** CoT `@le` has no canonical home; `Position.accuracy_m` is horizontal
   only. *Proposed: `Position.alt_accuracy_m` in 1.1.0 (MINOR).* Matters for air tracks, where
   a 300 m vertical error decides whether two aircraft are deconflicted. **Now confirmed by a
   shipped adapter**: `air_track_due_north.xml` carries `le="120.0"` on a track at 7 620 m, and
   that 120 m sits in `attributes` where no consumer will look for it.
