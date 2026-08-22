# Picogrid Legion fixtures

These are the ingest fixtures for `adapters/legion.py`. They were written **before** the
adapter, alongside the row set in `FORMAT_COVERAGE.md`, so the mapping could be reviewed against
real documents before any code was committed to it — and `golden/` was added only once the
adapter existed, because a golden is the output of an adapter and writing one earlier would have
recorded an expectation nobody had run.

**Every one is synthetic.** No recorded Legion traffic, no real organisation, no real device.
Each document was hand-written from the `example` values in the pinned OpenAPI schemas and
from the schemas themselves, then checked against the field inventory in `spec/openapi_pin.json`.

That pin lives in `spec/` rather than beside the fixtures for a reason worth knowing: the harness
replays every FILE in a fixture directory through `to_cdm()`, so a reference document sitting next
to the payloads is fed to the adapter and fails as an unrecognised document. Subdirectories are
skipped, which is the same reason the TAK and AIS egress fixtures live in one.

## The identifiers, and why UUID version 8

Legion identifies everything with a `format: uuid` string, and a UUID has no reserved test range
the way the AIS numbering plan has an unallocated MID or the ICAO address space has a block below
`004000`. So the previous two fixture sets' trick — pick a structurally valid value from a range
nobody allocates — needs a different mechanism here.

RFC 9562 §5.8 provides it. **Version 8 is reserved for custom and experimental use**, and a
system generating identifiers normally emits version 4 (random) or version 7 (time-ordered).
So every fixture id here is a version 8 UUID:

```
f1c70000-RRRR-8000-8000-0000000000NN
         ^^^^ ^                ^^
         |    version nibble = 8
         |                     sequence
         resource kind
```

- `f1c7` — the leading group, hex for the only pronounceable thing available in `[0-9a-f]`:
  *fictitious*. Every fixture id in this directory starts with it, so one glance at any
  identifier anywhere downstream says where it came from.
- `RRRR` — the resource kind: `0000` organisation, `0001` entity, `0002` location, `0003` event.
- **`8` in the version position** — the property that matters. A Legion-issued id cannot collide
  with one of these, because Legion issues v4 and v7 and this is v8. It is the same *kind* of
  guarantee MID 299 gave the AIS fixtures, and a stronger one: MID 299 rests on an allocation
  table that could change, while this rests on the version field meaning what RFC 9562 says.
- `8` in the variant position keeps the variant bits at `10`, so the string is a well-formed
  RFC 9562 UUID and not merely a plausible one. A parser that validates will accept it.

The scheme is asserted rather than described: `tests/test_cdm_format_coverage.py` checks that
every id in every fixture here is version 8 and carries the `f1c7` prefix, so a real id pasted in
during debugging fails the build instead of shipping.

Names are prefixed `EXERCISE` and describe nothing real. Positions are Baltic-plausible — the
approaches to Riga, the Gulf of Riga and Ventspils — and are not any vessel's or aircraft's real
track.

## The ECEF coordinates are computed, not invented

Legion's default coordinate reference system is **`EPSG:4978`, geocentric X/Y/Z in metres** (see
the row set — this is the single largest hazard in the mapping). Fixtures that exercise the
default therefore carry ECEF triples, and those were computed from the geodetic position on the
WGS84 ellipsoid rather than made up, so a future adapter's conversion has something true to
land on:

| Fixture position | Geodetic (lat, lon, h) | ECEF (X, Y, Z) metres |
|---|---|---|
| Riga mast | 56.9236, 23.9711, 25 | 3188199.36, 1417551.34, 5321282.59 |
| Gulf of Riga | 57.5981, 23.8412, 12 | 3133607.51, 1384778.07, 5361895.07 |
| Ventspils | 57.3908, 21.5606, 8 | *(this fixture uses `EPSG:4326` instead — see below)* |
| Patrol sample 1 | 57.4102, 23.2088, 40 | 3164936.13, 1357068.79, 5350676.28 |
| Patrol sample 2 | 57.5514, 23.4471, 45 | 3147102.14, 1364945.34, 5359134.15 |
| Patrol sample 3 | 57.6903, 23.6912, 52 | 3129298.52, 1373092.81, 5367424.3 |

Each triple has magnitude ≈ 6 363 km, which is the Earth's radius at that latitude — the cheap
sanity check that distinguishes an ECEF coordinate from a mistake.

## The fixtures

| Fixture | Resource | What it is there to catch |
|---|---|---|
| `entity_sensor_mast_riga.json` | Entity | The ordinary case, and the CRS hazard: it carries **no `crs` key at all**, so the coordinates are ECEF by the schema's stated default. An adapter that read them as `[lon, lat]` would place this mast in the Gulf of Guinea. Also `category: SENSOR` (the one enum that maps), an embedded `location_latest`, a `covariance` matrix, a free-form `metadata` bag, and `classification` present as an empty object |
| `entity_location_ecef_gulf_of_riga.json` | Location | A standalone location with the full kinematic set — `bearing`, `speed`, and the four vectors (`velocity`, `acceleration`, `angular_velocity`, `orientation`) whose units and reference frames the spec never states. All four must park; only `bearing` may reach `Kinematics`. Carries the embedded `entity` **subset**, which omits five fields the standalone Entity endpoint returns |
| `entity_location_lla_ventspils.json` | Location | The other CRS: `EPSG:4326` with `[longitude, latitude, altitude]` per the prose companion. Also two edge cases — `bearing: 360`, which must be reduced to `0` because `course_deg` is `[0, 360)`, and `speed: null`, which is the API *stating* it does not know and therefore belongs in `unavailable_fields`. And a non-null `parent_id`, pointing at the mast: parked, never resolved |
| `entity_exercise_affiliation_and_nulls.json` | Entity | `affiliation: EXERCISE_FRIEND` — the collapse and the split at once: FRIENDLY on the CDM object, the exercise marking recorded separately, and `source.synthetic` **not** rewritten by payload content. Also the absent-versus-null discipline: `deleted_at`, `top_classification` and `top_classification_probability` are explicitly `null` while `classification` and `metadata` are simply absent, and those are different facts |
| `event_gunshot_detection.json` | Event | `event_type: GUNSHOT` — a detection **class**, not a CDM `EventType`, so it parks and `DETECTION` is supplied instead. Severity stays `INFO`: Legion states no urgency, and grading a gunshot would be this translator judging operational significance. Also `actor_id` equal to `source_id`, which must still not put the actor in `related_entities` |
| `locations_list_patrol_three.json` | Locations list | The envelope that becomes one CDM `Track`: `crs` declared once for all results, three time-ordered samples, and `paging.has_more: true` with `total_count: 9`. The Track is therefore **partial and measurably so** — three of nine — and the adapter must park that rather than following `paging.next`, which is the pagination-is-framing line |

## What the fixtures found

Writing the adapter against these six documents produced four corrections, and they are listed
because the fixtures are what produced them rather than a review:

1. **The list path dropped every sample's metadata.** Pruning `results` wholesale from the parked
   residual took each location's `id`, `source`, timestamps and `position.type` with it. The
   harness's never-drop check failed on the first run; only the coordinates the adapter re-emits
   verbatim are pruned now.
2. **`metadata` is NOT missing from the embedded entity.** A hand-read of the spec listed six
   omitted fields; the pinned inventory says five. `test_the_omitted_field_list_is_what_the_
   pinned_spec_says_it_is` derives the set from the pin and caught it.
3. **Six `TRANSFORMS` exemptions had no subject.** A timestamp this adapter does not consume
   parks verbatim, so its exact string is already present and no exemption is needed.
4. **The pin file was being replayed as a payload**, which is why it moved to `spec/`.

## What is deliberately not here

- **No tasking fixture.** Tasking is out of scope and the reason is structural: a task has no
  geometry and `PlanObject.geometry` is required. A fixture would imply a mapping exists.
- **No feed-data fixture.** Deferred, not rejected — its `payload` shape is declared by a
  separate Feed Definition resource, so translating one is a cross-resource join.
- **No search-response fixture.** A search returns the same objects in the same envelope; the
  adapter translates what a search returned and knows nothing about the query.
- **No `EPSG:4979` fixture.** That value is in the enum and defined in no document, so the row
  set refuses it. A fixture would require inventing the axis order the refusal exists over.
