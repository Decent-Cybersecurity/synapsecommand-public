# Format coverage — does the CDM actually carry what these formats need?

The brief asks the model to "map cleanly to Cursor-on-Target, STANAG 4676 track structures and
GeoJSON". This file is that check, done field by field rather than asserted. It is also a
working document for whoever writes adapters #2 and #4: the mapping column is the adapter's
specification.

`tests/test_cdm_format_coverage.py` resolves every path in the **CDM field** column against the
actual Pydantic models and fails the build on one that does not exist. That is the only reason
this table can be trusted six months from now — a renamed field breaks the test, not just the
prose.

Paths use `[]` for a list element, e.g. `Track.samples[].observed_at`.

## Cursor-on-Target (TAK) — ingest and egress

| CoT | CDM field | Notes |
|---|---|---|
| `event/@uid` | `Entity.source_ids[].external_id` | system `TAK`; the UID is what TAK dedupes on |
| `event/@type` | `Entity.affiliation` | via `symbology.affiliation_from_cot`; original string parked in `attributes` |
| `event/@type` | `Entity.entity_type` | battle-dimension letter (`G`/`A`/`S`) → UNIT/PLATFORM/… |
| `event/@time` | `Event.observed_at` | |
| `event/@start` | `Entity.valid_from` | |
| `event/@stale` | `Entity.valid_to` | CoT staleness IS an interval end — maps exactly |
| `event/@how` | `Position.position_source` | `m-g` machine/GPS → GNSS, `h-e` human entered → MANUAL |
| `point/@lat` | `Position.lat` | |
| `point/@lon` | `Position.lon` | |
| `point/@hae` | `Position.alt_m` | both WGS84 HAE metres — no conversion |
| `point/@ce` | `Position.accuracy_m` | circular error, metres |
| `point/@le` | `Entity.attributes` | **gap 6** — no canonical linear (vertical) error field |
| `detail/track/@speed` | `Kinematics.speed_mps` | CoT speed is m/s — no conversion |
| `detail/track/@course` | `Kinematics.course_deg` | degrees true |
| `detail/contact/@callsign` | `Entity.attributes` | **gap 1** — no canonical name field |
| `detail/remarks` | `Entity.attributes` | free text, no canonical home by design |
| `detail/__group/@name` | `Entity.attributes` | colour-based team, not an affiliation |
| drawing `u-d-f` shapes | `PlanObject.geometry` | egress: the COA sketch direction |
| drawing stroke/fill | `PlanObject.style` | hints only — style may never carry meaning |
| drawing label | `PlanObject.label` | |
| `event/@stale` (egress) | `PlanObject.expires_at` | |

## STANAG 4676 — track ingest

| STANAG 4676 | CDM field | Notes |
|---|---|---|
| `TrackMessage/trackUUID` | `Track.track_id` | derive with `ids.derive` when absent |
| `Track/trackNumber` | `Track.source_ids[].external_id` | the operator-facing track number |
| `TrackPoint/trackPointPosition/latitude` | `Track.samples[].position.lat` | |
| `TrackPoint/trackPointPosition/longitude` | `Track.samples[].position.lon` | |
| `TrackPoint/trackPointPosition/hae` | `Track.samples[].position.alt_m` | |
| `TrackPoint/trackPointTime` | `Track.samples[].observed_at` | ordering is validated by `Track` |
| `TrackPoint/trackPointSource` | `Track.samples[].position.position_source` | |
| `TrackPoint/trackPointObjectMass` etc. | `Entity.attributes` | source-specific, parked |
| `TrackPoint/trackPointVelocity` (u,v,w) | `Kinematics.speed_mps` | **gap 4** — vector → scalar+course, a declared transform |
| `TrackPoint/trackPointVelocity` (w) | `Kinematics.climb_mps` | sign convention differs; declare it |
| `Track/trackQuality` | `Track.track_quality` | **gap 3** — 4676 is integer 0–15, CDM is float 0–1 |
| `Track/objectClassification` | `Entity.entity_type` | plus original in `attributes` |
| `Track/classificationConfidence` | `Entity.confidence` | |
| `IdentityIndicator` | `Entity.affiliation` | **gap 2** — 7 values collapse to 4 |
| `exerciseIndicator` | `Entity.source.synthetic` | maps exactly — and this is why `synthetic` has no default |
| `TrackMessage/security/…` | `Entity.attributes` | classification marking lives at the platform gateway, not here |

## GeoJSON (RFC 7946)

| GeoJSON | CDM field | Notes |
|---|---|---|
| `Point` | `Event.geometry` | `[lon, lat]` order enforced in `geo.py` |
| `LineString` | `PlanObject.geometry` | routes |
| `Polygon` | `Event.geometry` | jamming footprints; ring closure enforced |
| `Feature.properties` | `PlanObject.style` | **gap 5** — Feature/FeatureCollection not modelled |
| `bbox` | — | not carried; derivable from geometry |

## Gaps, and what each one costs

1. **No canonical name.** A CoT callsign and a 4676 track number are the strings an operator
   reads, and today they land in `attributes`. Every consumer that wants to label a contact
   has to know which adapter's key to look under, which is exactly the kind of private
   knowledge the CDM exists to abolish. *Proposed: `Entity.label` in 1.1.0 (MINOR — optional
   field).* Deliberately not added on day one: it needs one owner naming its precedence rules
   across sources, not a field added in passing.
2. **Affiliation collapse, 7 → 4.** PENDING, ASSUMED_FRIEND and SUSPECT have no CDM member
   (see `enums.Affiliation` for why: they are judgements, not wire facts). Recoverable only
   because the adapter parks the original — which the lossless check enforces rather than
   trusts.
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
   a 300 m vertical error decides whether two aircraft are deconflicted.
