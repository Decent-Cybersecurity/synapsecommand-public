# SC CESMO Internal Exchange fixtures — the `cesmo_internal` adapter, contract `sc.cesmo.internal/1.0`

These are the harness fixtures for the `cesmo_internal` adapter. Every payload is one Exchange of SC
CESMO Internal Exchange 1.0, the internal JSON contract of the SynapseCommand STANAG 4658 CESMO and
EOB Engineering Kit 1.0 (Decent Cybersecurity, 4 October 2026); its schema is published at
`schemas/cesmo_internal/cesmo-internal-1.0.schema.json` in the repository. **None of them is STANAG
4658, AEDP-13 or a CESMO unit: there are no native bytes, messages or frames anywhere in this
directory, the kit declares that binding BLOCKED on its unresolved dependency register N01-N12, and
no file here is normative evidence.** Every Exchange is synthetic and says so (`"mode":
"synthetic"`) in the kit's invented vocabulary: network `TEST-NET`, originator `TEST-SOURCE-A`,
identity epoch `EXERCISE-1`, emitters `EMITTER-n`, sensors `SENSOR-n`; nothing derives from recorded
data, from an operational source or from any order of battle.

The kit's five examples are carried byte-identical, and so is its expected CDM projection of
`upsert.json`, under `reference/`. `spec/cesmo_internal_pin.json` records the SHA-256 and size of
every kit file as the kit's own `SHA256SUMS.txt` states it, the ones carried here and the ones that
are not (the specification, its README, the reference validator and its tests, the offline
configuration example and the dependency register). `spec/build_fixtures.py` writes everything else
in this directory from the kit's examples and checks it (`--check`). Every position a valid
authored document states lies inside CONTRIBUTING.md's Baltic rectangle. The kit's `upsert.json`
states latitude 0 and longitude 0 on purpose (a real zero, not an unknown), and the refusals under
`malformed/` cut from it keep that 0, 0, except `e_schema_latitude_91.json`, whose latitude 91 is
the fault it carries.

## The harness fixtures

| Fixture | What it exercises |
|---|---|
| `observation.json` (kit) | an observation with a bearing and no `object_id`: one DETECTION Event, no Entity, no geometry, no related entity |
| `upsert.json` (kit) | an `eob_upsert` at latitude 0, longitude 0 with a signal, an ellipse, confidence 0 and affiliation UNKNOWN: the emitter Entity then its TRACK_UPDATE Event, `accuracy_m` null, the ellipse unchanged |
| `withdrawal.json` (kit) | an `eob_delete`: a STATUS_CHANGE Event, operation `withdraw`, naming the scoped emitter |
| `status.json` (kit) | a source `status`: a STATUS_CHANGE Event, operation `status`, no emitter |
| `empty-complete-snapshot.json` (kit) | a complete snapshot with no record: one STATUS_CHANGE Event, operation `snapshot` |
| `every-kind.json` | one record of each kind: an observation naming `EMITTER-2` at an asserted INERTIAL position with a height (a Point with three coordinates), the upsert of `EMITTER-2` (MANUAL, FRIENDLY, confidence 1), a withdrawal of `EMITTER-3`, which no record of the message asserts, and a degraded source status |
| `complete-snapshot-with-upserts.json` | a complete snapshot that carries records: two upserts at its revision 8, one with every signal field, a circular ellipse at orientation 0 and probability 1, GNSS with a height, HOSTILE and confidence 0.75, one with nothing but its identifiers (UNKNOWN, confidence null, no position), then the snapshot Event |
| `observation-position-no-object.json` | an observation with an asserted ESTIMATED position, an ellipse at orientation 179.5 and no `object_id`: a Point and no related entity |
| `sub-millisecond.json` | a partial snapshot whose times carry six fraction digits non-zero in the fourth to sixth (`.123456`, truncation recorded), six digits zero there (`.120000`, nothing dropped, nothing recorded), one digit (`.5`), and an envelope time `.000250` for the snapshot Event |
| `cdm-shaped-extension-keys.json` | an observation and an upsert whose `extensions` hold keys spelled like CDM fields (`track_id`, `object_id`, `entity_id`, `event_id`, `last_seen_at`, `valid_from`) with source-form values, so the conformance suite's J and K meet them inside the residual |
| `tokens-at-64.json` | every token field (network, originator, epoch, message, record, object, sensor and snapshot identifiers) at the contract's 64 characters |
| `upsert_octets.bin` | `upsert.json` byte for byte, as octets, so the strict octet path runs on a valid document |

`golden/` holds the adapter's output over each, written by
`python -m synapse_cdm.harness --adapter cesmo_internal --update-golden` under the harness clock and
read value by value before being kept; the adapter test pins each golden's objects, kinds, event
types, operations, identities, times and transformations by literal.

## `reference/`: the kit's own projection

`expected-upsert-cdm.json` is the kit's expected CDM output for `upsert.json`, byte-identical,
written against CDM 3.0.0 with the receipt clock 2026-10-04T12:00:01Z. The adapter test reproduces it
byte for byte from `upsert.json`, as octets and as a dict, under that clock and the adapter's
`cdm_schema="3.0.0"` stamp, dumped with `synapse_cdm.projection.dump_for(obj, "3.0.0")`; the default
projection differs from it only by `"schema_version": "3.2.0"` and the Event's `"validity": null`,
which the test asserts too.

## `malformed/`: Exchanges the adapter refuses

`.json` where the document is valid JSON (the harness hands a `.json` file to the adapter as a dict),
`.bin` where the defect is in the octets and a dict could not carry it. Each is a kit example with one
defect, and each file's name starts with the code the adapter test expects. A document above
1,048,576 octets, 1,001 records or nesting deeper than 64 is not a file here (the wheel would carry a
mebibyte for one refusal): the adapter test generates them.

| File | Defect | Code |
|---|---|---|
| `e_schema_duplicate_key.bin` | `mode` twice | E_SCHEMA |
| `e_schema_nan_literal.bin` | `NaN` | E_SCHEMA |
| `e_schema_infinity_literal.bin` | `Infinity` | E_SCHEMA |
| `e_schema_number_overflow.bin` | `1e400` | E_SCHEMA |
| `e_schema_number_underflow.bin` | `1e-400` | E_SCHEMA |
| `e_schema_integer_past_binary64.bin` | a 310-digit integer | E_SCHEMA |
| `e_schema_byte_order_mark.bin` | a UTF-8 byte order mark | E_SCHEMA |
| `e_schema_invalid_utf8.bin` | a byte 0xFF in a string | E_SCHEMA |
| `e_schema_lone_surrogate_escape.bin` | an escaped lone surrogate | E_SCHEMA |
| `e_schema_trailing_content.bin` | a second JSON text after the document | E_SCHEMA |
| `e_schema_top_level_array.bin` | the document inside a JSON array | E_SCHEMA |
| `e_limit_depth_17.bin` | 17 nested containers | E_LIMIT |
| `e_schema_trailing_newline_token.json` | `object_id` ending in a newline | E_SCHEMA |
| `e_schema_hour_24.json` | hour 24 in the record's `observed_at` | E_SCHEMA |
| `e_schema_february_30.json` | 30 February in the envelope's `observed_at` | E_SCHEMA |
| `e_schema_second_60.json` | second 60 in the record's `observed_at` | E_SCHEMA |
| `e_schema_non_ascii_digit.json` | an Arabic-Indic digit four in the envelope's `observed_at` | E_SCHEMA |
| `e_schema_snapshot_record_id.json` | the reserved `$snapshot` as a `record_id` | E_SCHEMA |
| `e_schema_unknown_top_level_key.json` | a key the envelope does not define | E_SCHEMA |
| `e_schema_unknown_record_key.json` | a key the record does not define | E_SCHEMA |
| `e_schema_missing_required_key.json` | no `message_id` | E_SCHEMA |
| `e_schema_revision_not_integer.json` | `revision` 4.0 | E_SCHEMA |
| `e_schema_probability_zero.json` | ellipse `probability` 0 | E_SCHEMA |
| `e_schema_orientation_180.json` | ellipse `orientation_deg` 180 | E_SCHEMA |
| `e_schema_latitude_91.json` | `latitude_deg` 91 | E_SCHEMA |
| `e_unsupported_message_unknown_contract.json` | contract `sc.cesmo.internal/2.0` | E_UNSUPPORTED_MESSAGE |
| `e_mode_mismatch_live.json` | `mode` live under the default (synthetic) constructor | E_MODE_MISMATCH |
| `e_semantic_repeated_record_id.json` | two records with one `record_id` | E_SEMANTIC |
| `e_semantic_upsert_without_object_id.json` | an `eob_upsert` without `object_id` | E_SEMANTIC |
| `e_semantic_empty_records_without_snapshot.json` | no record and no snapshot | E_SEMANTIC |
| `e_semantic_ellipse_axes_reversed.json` | `semi_minor_m` above `semi_major_m` | E_SEMANTIC |
| `e_semantic_ellipse_without_position.json` | an ellipse and no position | E_SEMANTIC |
| `e_semantic_snapshot_with_observation.json` | a snapshot holding an `observation` | E_SEMANTIC |
| `e_semantic_snapshot_revision_mismatch.json` | a snapshot at revision 5 holding a record at revision 4 | E_SEMANTIC |
| `e_semantic_snapshot_repeats_object_id.json` | a snapshot naming one `object_id` twice | E_SEMANTIC |
| `e_semantic_status_with_object_id.json` | a `status` naming an emitter | E_SEMANTIC |
| `e_semantic_withdrawal_with_position.json` | an `eob_delete` carrying a position | E_SEMANTIC |
