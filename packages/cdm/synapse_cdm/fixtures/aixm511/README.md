# AIXM 5.1.1 fixtures — adapter #19, EUROCONTROL & FAA AIXM 5.1.1 (April 2016)

These are the harness fixtures for `adapters/aixm511.py`: five synthetic `message:AIXMBasicMessage`
documents, each as the XML the wire carries and as a `.parsed.json` twin — the codec's dict form of
the same document (`aixm_codec.twin_of`: the GML object-property pairs collapsed one level per pair
with the object's name under `"$"`, repeatable properties always lists, attributes as `@prefix:name`,
document order kept). The harness translates both; the twin is what the path-bound preservation
ledger walks, so every leaf of every document is accounted for.

**Every one is synthetic.** Hand-written on 2026-09-21 for the case each exercises. Every designator
starts with `SYN`, every UUID sits under the `a1a40000-` prefix, every position is a fictitious place
and no file derives from any published aeronautical data set. `spec/aixm511_pin.json` records each
file's SHA-256 and byte count. Two independent readings hold the adapter's own parse honest: every
`.xml` validates against the pinned XSD closure through an actual validator (`normative_validation.py`,
lxml, the `validate` extra — `BLOCKED_EXTERNAL_EVIDENCE` and never a pass when the resource is
absent), and every twin is re-derived from the XML with the standard library alone in
`tests/test_cdm_aixm511_adapter.py::test_every_parsed_twin_corresponds_to_its_raw_fixture`.

**Required configuration for the normative reading, and nothing for translation.** `to_cdm` needs
no configuration, no file outside the package and no network. The schema validation above runs
only when two things are present: the `validate` optional extra (`pip install
"synapse-cdm[validate]"`, lxml) and the environment variable `SYNAPSE_CDM_AIXM511_XSD_DIR` naming a directory OUTSIDE
this repository that holds `xsd_pin.json` and the pinned closure of AIXM 5.1.1 (`aixm-5.1.1/message/AIXM_BasicMessage.xsd` and its closure) — and, for the Digital NOTAM reading, `SYNAPSE_CDM_DNOTAM_XSD_DIR` for the Event Schema 2.0.m; the layout is
`normative_binding.py`'s and the resolver is `normative_validation.py`. The AIXM closures spell
remote `schemaLocation`s, so the directory's OASIS catalog must be on `XML_CATALOG_FILES` for
libxml2 to resolve every import offline. With either absent the check records
`BLOCKED_EXTERNAL_EVIDENCE` and passes nothing.

## The fixtures, and what each one is for

| Fixture | Families | Exercises |
|---|---|---|
| `airspace_baseline_polygon.xml` | Airspace | one BASELINE slice (sequence 1, correction 0, validTime open with `indeterminatePosition="unknown"`, a featureLifetime); one BASE volume, FL 195 STD over 2500 FT MSL, the pinned Surface form (PolygonPatch, exterior Ring, one Curve, one GeodesicString) under EPSG:4326 (latitude first); an activation with a Timesheet, so the status is typed and not asserted; an annotation the adapter does not type |
| `airspace_deltas_same_feature.xml` | Airspace | three later slices of the SAME feature: a TEMPDELTA activating it (ACTIVE, no schedule, so it is the Entity's status), its correction (sequence 2, correction 1) ending two hours earlier, a PERMDELTA at an instant renaming it and withdrawing `localType` with `xsi:nil`; no geometry, so no PlanObject and every other property reads UNCHANGED |
| `airport_runway_navaid.xml` | AirportHeliport, Runway, RunwayDirection, Navaid (+ an OrganisationAuthority, a feature outside the families) | an ARP ElevatedPoint (EPSG:4326, 12 FT above MSL, EGM_96), a NORMAL availability; a runway referring to its aerodrome by `urn:uuid`; a runway direction referring to its runway by `#gml:id`, CLOSED under a Timesheet (typed, not asserted); a VOR/DME whose location is CRS84 (longitude first), OPERATIONAL, two component equipments the document does not carry (unresolved, kept), a runway direction by `#uuid.<uuid>` and a served airport by `urn:uuid` |
| `vertical_structure_two_parts.xml` | VerticalStructure | a lit tower: one part with a point location (250 FT MSL) and a 120 M vertical extent, one part (an antenna, 15 M) with no geometry; the Entity's position is the located part's |
| `airspace_hole_crs84_snapshot.xml` | Airspace | a danger area with a hole (exterior Ring of one Curve with a linear segment, interior LinearRing) under CRS84; a nil upper limit (unknown) and a GND lower limit — a column described without a number at either end; a SNAPSHOT slice with no sequence or correction number |

`golden/` holds the adapter's output over each, written by
`python -m synapse_cdm.harness --adapter aixm511 --update-golden` and read before being kept.

## What the goldens show, and where to look

- **One Entity per time slice.** `entity_id` is derived from the feature's `gml:identifier`, so
  the four slices of `SYNTSA1` across the first two fixtures are four states of one entity;
  `source_ids[1]` is the slice's own identity (`<uuid>/<interpretation>/<sequence>/<correction>`),
  `source.original_id` its `gml:id`. `valid_from` / `valid_to` are the slice's `gml:validTime`
  (begin included, end excluded — Temporality Concept 1.1 §4.4.1).
- **The typed block** is `attributes.aixm` (`aixm-timeslice/1`, `aixm511.TimeSliceBlock`): feature
  and slice identity, validTime and featureLifetime as stated, every pinned property as a
  `PropertyState` (absent / nil / stated, read as not stated / nil / unchanged / withdrawn under
  the interpretation), geometry components with their volumes (limits with unit, reference, kind
  and the CDM projection or the reason there is none; the surface read under its CRS), activation
  and availability with their Timesheets, the ARP or location, the parts, every reference with its
  form and resolution, and a verbatim `source` copy beside each complex reading.
- **The PlanObject** beside an Airspace slice that states a projectable BASE geometry:
  CONTROL_MEASURE, `label` the designator, `geometry` and `area.geometry` the polygon in
  [lon, lat], `area.vertical` where the limits project (FL 195 → FL/FL, 2500 FT MSL → ft/MSL;
  UNL, GND and nil bounds stay absent with the reason in `source.transformations`),
  `area.validity` the slice's. Its id is derived from the same identifier under its own kind.
- **A feature outside the families** (the OrganisationAuthority) is an Entity of type UNKNOWN
  with the generic reading only — identity, interpretation, numbers, validTime; its properties
  in the residual, no position, no status — and `validate_source` names it. The exception is
  the seven complex elements the ledger binds at slice level whatever the family
  (`aixm511.CARRIED_ELEMENTS`): a DME's `location` or a Taxiway's repeated `availability` is
  carried at the same block field, source verbatim, still with no position or status
  (`cases/other_feature_location_availability.xml`).
- **The residual** is the parsed twin minus what the typed block consumed, list positions kept:
  another feature's slices read `null` at their positions (they are that feature's objects), the
  annotation stays under its slice, a fully typed slice leaves nothing, and a member that is not a
  feature at all would ride whole on every object.

## The other directories

- `malformed/` — seventeen documents refused under the default constructor (conformance check H):
  a DTD, an undefined entity, an XInclude, a truncation; AIXM 5.1's namespace and a wrong root; a
  feature with no identifier; an arc, a circle, another CRS, a third dimension, an open ring; a
  cancelled slice with no as-of context; an interpretation outside the four; a document with no
  member of the families; an interval running backwards; a non-integer sequence number. The arc,
  the circle and the cancelled slice are also translated in the tests under the explicit
  `unsupported_geometry="report"` and `as_of=` contexts.
- `cases/` — nine documents read by name in the tests: the EPSG:4326 / CRS84 axis-order pair, an
  interior ring of curves (too deep for a shipped twin), a composition with a cycle of contributor
  references, every reference form, twelve ways of stating a vertical limit, nil / absent /
  withdrawn states, a schema-valid BASELINE with a TimeInstant (TS_001, reported), and two
  features outside the families (a DME with `location` and `availability`, a Taxiway with a
  repeated `availability`) whose ledger-bound structures the generic reading carries.
- `counterexamples/` — five well-formed, schema-invalid documents with the layer that rejects
  each declared in its README.
- `independent/` — a bounded extract of the Donlon fictitious data set with an independent
  ElementTree reading of the same members; see its README.
- `spec/` — `aixm511_pin.json` (every fixture's hash, the documents consulted) and
  `build_fixtures.py` (the Donlon extract). The schema closure itself is held outside the
  repository (decision D2) under the `aixm511` normative binding.
