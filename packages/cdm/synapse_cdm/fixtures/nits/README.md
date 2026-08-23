# STANAG 4676 / AEDP-12 Ed B v2 fixtures

**Everything here is synthetic.** No recorded NITS traffic, no real collection, no real track,
no real platform. Every document is built from field values by `spec/build_fixtures.py`, which
is the only thing that should ever write to this directory:

```
python packages/cdm/synapse_cdm/fixtures/nits/spec/build_fixtures.py
python -m synapse_cdm.harness --adapter stanag4676 \
    --fixtures packages/cdm/synapse_cdm/fixtures/nits
```

## Twins, and why both halves are replayed

Each case ships as a **`.nits.xml` and a `.parsed.json`**, and the harness replays both. That is
not redundancy. The normative XML schema is distributed through NATO national representatives
(Ed B §B.5) and could not be obtained or hashed for this repository, so the adapter's element
names are a **provisional** binding of the UML attribute names through one table. The twin is
what makes the binding checkable: `test_the_xml_twin_and_the_parsed_twin_produce_identical_cdm`
asserts the two halves produce byte-identical CDM, and it found two reader defects on its first
run — an all-`NaN` ring delimiter parsed to a float, and a concretely-typed `Shape` left untagged.

The `.parsed.json` half also gives the harness's never-drop check something to harvest: a bytes
fixture has no leaf structure, so `lossless` reports SKIP on the XML half by design.

## Identifiers

RFC 9562 §5.8 reserves **version 8** for custom and experimental use, so a producer issuing v4 or
v7 cannot collide with one of these. Every UUID here is version 8 with the `f1c7` prefix the
Legion fixtures established, and a test asserts it per file. Local IDs are small integers under a
version-8 `lidScopeUID`, which is exactly the composite the identity settlement requires before a
`lid` may become a `SourceId`.

**The weakest claim in this set is the station identification**, and it says so here rather than
nowhere: `IDData.nationality` uses `ZZZ`, which is not a NATO trigraph in APP-11(D) — but unlike
the CAT021 System Area Code there is no pinned allocation list behind that, so the claim rests on
a reading rather than on a retrieved document.

## Why every document states a non-REAL essence

`CollectionInformation.essence` is parked and never sets `source.synthetic` (amendment B), and a
parked essence that contradicts the deployment declaration is a **conflict refusal**. The harness
constructs the adapter with `synthetic=True`, so a fixture stating `REAL` would be refused by
design. The `REAL` case is exercised in `tests/test_cdm_stanag4676_adapter.py`, where the
declaration can be set to match.

## What each case is here to catch

| Fixture | The decision it pins |
|---|---|
| `standalone_basic_track` | the reference case: one `TrackData`, WGS-84 points, an APP-6 class, a PROBABILITY confidence |
| `three_contiguous_segments_one_track` | **amendment A** — three segments, ONE `Track`, and a sample index range recorded per segment |
| `ecef_track_with_velocity` | the Bowring/Ferrari transform, and a velocity through the local horizon |
| `wgs84_velocity_with_height` | **amendment D**, converting branch: radii of curvature at a stated `(phi, h)` |
| `wgs84_velocity_without_height` | **amendment D**, parking branch: `h = 0` would be a fabricated input |
| `local_cartesian_with_complete_cft` | a complete ECEF CFT, the coordinate preference order, and the disagreement record |
| `local_spherical_is_attributes_only` | **amendment E** — a COMPLETE CFT and still no `Position` |
| `motion_event_complex_polygon` | all three polygon corrections, with a `NaN`-delimited hole |
| `motion_event_tripwire` | a `LineString` that is never closed |
| `detection_evidence_tree` | every leaf of the Detection/Evidence tree, including an image chip and a pixel mask |
| `exercise_faker_is_friendly` | **amendment C** — `FAKER` yields `FRIENDLY`, the role is parked, Mode 5 is not read |
| `amplification_zombie_contradicts_friend` | the suspect contradiction, which collapses to `UNKNOWN` |
| `linkage_processed_track_carried` | `TrackLinkage` and `ProcessedTrack`, carried and never acted on |
| `segment_retraction_is_an_event` | a retraction-only segment: an `Event`, not a `Track`, and not dropped |
| `datastream_unresolved_references` | the DATASTREAM profile and a reference that resolves nowhere in this payload |
| `fractional_increment_parks_raw_integers` | 1/128 s: the raw integers are the record and the `Timestamp` truncates |

## What is NOT here, and where it is instead

Every **refusal** — a missing `baseTime`, a naive one, a zero increment, an Edition A document,
points out of time order, overlapping multi-hypothesis segments, an essence conflict, a bare
`lid` with no scope, an abstract `Shape` with no `xsi:type`, an egress with no confidentiality
label, an egress with a dangling reference — lives in `tests/test_cdm_stanag4676_adapter.py` with
an inline document. A fixture whose `to_cdm()` raises is a harness FAIL, and a refusal that reads
as a failure is a refusal nobody will keep.
