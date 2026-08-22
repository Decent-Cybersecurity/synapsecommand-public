# CDM schema versioning and migrations

Every serialised object carries `schema_version`. A consumer reading an object off a queue has
no other way to know which shape it is holding, and "we will add versioning when we need it"
means adding it at the moment two incompatible producers are already in the field.

## What each bump means

| Bump | Change | Consumer impact |
|---|---|---|
| **MAJOR** | a field removed or renamed; a type narrowed; an enum member removed; an optional field made required; the `ids.NAMESPACE` changed | breaks readers; needs a migration entry below and a coordinated deployment |
| **MINOR** | an optional field added; an enum member added; a payload model registered; validation relaxed | old readers keep working, old data keeps validating |
| **PATCH** | descriptions, error-message wording, docs | none |

`version.compatible(written_with, read_by)` accepts the same major, **including a minor from
the future** — a 1.0.0 reader accepts a 1.2.0 object, because MINOR additions are optional by
definition and the alternative is a fleet that stops ingesting the moment one adapter is
upgraded. It refuses a different major outright.

Renaming a field is two releases, never one: add the new name in a MINOR, populate both, then
remove the old one in the next MAJOR. One release that renames is an outage for every consumer
that has not been redeployed in the same hour.

## Changing the schema — the procedure

1. Edit the Pydantic model. It is the single source; the files in `/schemas` are a publication.
2. Bump `version.SCHEMA_VERSION` per the table above.
3. Re-export: `python -m synapse_cdm.schemas --out schemas`. `tests/test_cdm_schemas.py` fails
   the build if you forget, and `--check` is the CI form.
4. Add an entry below, naming the reason — not just the change.
5. Re-run every adapter's golden files and **read the diffs**:
   `python -m synapse_cdm.harness --adapter <name> --fixtures <dir> --update-golden`.
   A golden file updated without being read is how a defect becomes the expectation.
6. If a documented gap in `FORMAT_COVERAGE.md` is now closed, close it there too —
   `tests/test_cdm_format_coverage.py::test_the_documented_gaps_are_still_gaps` fails
   deliberately when a gap field appears, so the document cannot silently disagree with the
   code.

## History

### 1.0.0 — initial contract

The four objects (`Entity`, `Event`, `Track`, `PlanObject`), `Position`, `Kinematics`,
`SourceId`, `SourceRef`, `Integrity`, `TrackSample`, and one registered payload model
(`GnssInterferencePayload` for `GNSS_INTERFERENCE`).

Two decisions in this release depart from the original specification, both because building
the reference adapter surfaced the reason:

- **`source_ids` moved from `Entity` to `CDMBase`**, required on every kind. The harness's
  lossless check found the gap on its first run: a PNTMAP alert whose emitter carries its own
  id produced an entity keyed on the emitter and an event keyed on nothing, so the alert's own
  identifier appeared nowhere in the output. A redelivery could not be recognised as a
  duplicate and an auditor holding the event could not get back to the source record.
- **`signal_strength` became `signal_strength_dbm`.** A bare `signal_strength` has been read
  as dBW, dBm and a 0–100 bar by three different consumers; the unit belongs in the name, as
  it already does in `speed_mps`, `alt_m` and `accuracy_m`.

## Proposed for 1.1.0 (MINOR — not yet implemented)

Both come from `FORMAT_COVERAGE.md`'s gap list, and both are deliberately deferred rather than
added in passing:

- **`Entity.label`** — a canonical human-readable name. A CoT callsign and a STANAG 4676 track
  number are the strings an operator reads, and today they land in `attributes`, so every
  consumer that wants to label a contact needs private knowledge of which adapter's key to
  look under. Deferred because it needs one owner naming its precedence rules across sources.
- **`Position.alt_accuracy_m`** — vertical accuracy. `accuracy_m` is horizontal only, so CoT's
  `@le` has no home. It matters for air tracks, where a 300 m vertical error decides whether
  two aircraft are deconflicted.
