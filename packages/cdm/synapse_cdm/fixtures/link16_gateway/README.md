# SC Link16 Gateway fixtures — the `link16_gateway` adapter, contract `sc-link16-gateway/1.0.0`

These are the harness fixtures for the `link16_gateway` adapter. Every payload is one report of
SC Link16 Gateway 1.0.0, an internal JSON interface this repository defines (its schema is
published at `schemas/link16_gateway/report.schema.json` in the repository, and the documentation
page `docs/docs/cdm/link16-gateway.mdx` is its contract). **None of them is JREAP C or Link 16:
there are no native bytes, frames or J-series words anywhere in this directory, and no file here is
normative Link 16 evidence.** Every report is synthetic and says so (`"synthetic": true`, names
carrying SYNTHETIC, SIMULATED or TEST); nothing derives from recorded data.

The six reports of the SynapseCommand JREAP C and Link 16 engineering handoff 1.0.0 are carried
byte-identical, and so are its six reference projections, under `reference/`. The handoff's
README says its examples share a fixed record identifier for separate test cases and are not a
batch to ingest together; nothing here feeds them as one. `spec/link16_gateway_pin.json` records
the SHA-256 and size of every handoff file carried here, of the three contract schemas published
beside the package, and of the specification, which is not carried.

## The harness fixtures

| Fixture | What it exercises |
|---|---|
| `air_flight_level.json` (handoff) | FL 180 against the FL reference, GNSS: the vertical is kept as stated, `alt_m` null |
| `air_msl.json` (handoff) | 5000 ft MSL, INERTIAL: no datum conversion, `alt_m` null |
| `air_sensor.json` (handoff) | 10000 ft HAE, SENSOR: the feet become 3048.0 m in `vertical` and `alt_m`, the feet stay in the residual |
| `land_unknown_position.json` (handoff) | no position and no motion, SUSPECT: an Entity and no Track; the identity projects to UNKNOWN |
| `subsurface_unknown_method.json` (handoff) | position method UNKNOWN, the depth kept in `source_fields` and never turned into a height |
| `surface_zero.json` (handoff) | latitude 0 and longitude 0, NEUTRAL: zeros are values, not sentinels |
| `air_hae_metres_friendly.json` | 1524.0 m HAE copied to `alt_m`, FRIENDLY, GNSS, climbing |
| `air_hae_feet_gnss_hostile.json` | 10001 ft HAE on GNSS (so the 3.0.0 compatibility projection keeps it), HOSTILE, descending |
| `surface_baro_pending_null_quality.json` | a BARO height, ESTIMATED, PENDING, no motion and a null quality code |
| `land_agl_assumed_friend_earlier_components.json` | an AGL height in feet, MANUAL, FACILITY, ASSUMED_FRIEND; position and motion times earlier than `effective_at`, and zero speed, course and climb |
| `subsurface_unit_other_depth_unknown_reference.json` | a vertical of −30 m with reference UNKNOWN, UNIT, OTHER, every motion value null |
| `unknown_domain_poles_uint64_unicode.json` | domain UNKNOWN, latitude 90 and longitude 180, a non-null `identity_code`, `sequence` and `incarnation` at 2^64−1, a non-ASCII track number, `time_basis` SOURCE, open `source_fields` (dotted and quoted keys, empty object and list) and a versioned extension |
| `air_south_pole_antimeridian_resolved.json` | latitude −90 and longitude −180, a height of 0 m MSL, RESOLVED_SOURCE, NEUTRAL |
| `air_sensor_octets.bin` | `air_sensor.json` byte for byte, as octets, so the strict octet path runs on a positive report |
| `unknown_domain_poles_uint64_unicode_octets.bin` | the compact UTF-8 encoding of the Unicode report, raw multi-byte characters and no escapes |

The seven reports written for this adapter on 2026-10-10 are the handoff's `air_sensor` report
with the fields named above edited; each new one has its own `record_id`. Open objects nest at most
two containers below themselves, so every golden nests at most eight containers deep.

`golden/` holds the adapter's output over each, written by
`python -m synapse_cdm.harness --adapter link16_gateway --update-golden` and read value by value
before being kept. At the landing they carry `"schema_version": "3.0.0"`, the number the package
declares until the release that types CDM 3.1.0 re-stamps them.

## `reference/`: the handoff's own projections

The six `<stem>.cdm.json` files are the handoff reference mapper's projections of the six handoff
reports, byte-identical. They state `"schema_version": "4.0.0"` and `"system": "SC Link16
Gateway"`, which this repository does not use (CDM 3.1.0 carries the two position methods, and the
system is the one token `SC_LINK16_GATEWAY`); they are never re-stamped. The mapping test compares
the adapter's projection with each, ignoring only those two keys and the null-valued keys the
models add, and asserts the values of the ignored keys separately.

## `malformed/`: reports the adapter refuses

`.json` where the document is valid JSON (the harness hands a `.json` file to the adapter as a
dict), `.bin` where the defect is in the octets and a dict could not carry it. Each is the handoff's
`air_sensor` report with one defect. The adapter test holds every file to its expected code, both
ways.

| File | Defect | Code |
|---|---|---|
| `missing_required_key.json` | no `synthetic` | SCHEMA_INVALID |
| `unknown_top_level_key.json` | a key the contract does not define | SCHEMA_INVALID |
| `unknown_nested_key.json` | an unknown key inside `position` | SCHEMA_INVALID |
| `number_as_string.json` | `lat_deg` as a string | SCHEMA_INVALID |
| `partial_coordinates.json` | `lat_deg` without `lon_deg` | SCHEMA_INVALID |
| `latitude_out_of_range.json` | `lat_deg` 91 | SCHEMA_INVALID |
| `course_360.json` | `course_deg` 360 | SCHEMA_INVALID |
| `flight_level_unit_reference_mismatch.json` | unit FL with reference MSL | SCHEMA_INVALID |
| `sequence_above_uint64.json` | `sequence` 2^64 | SCHEMA_INVALID |
| `uppercase_record_id.json` | a record identifier with an upper-case hex digit | SCHEMA_INVALID |
| `identifier_trailing_newline.json` | `gateway_id` ending in a newline | SCHEMA_INVALID |
| `missing_origin_scope.json` | no `origin_scope` | SCHEMA_INVALID |
| `non_ascii_digit_timestamp.json` | an Arabic-Indic digit in the year of `received_at` | TIME_UNRESOLVED |
| `timestamp_without_milliseconds.json` | `effective_at` without milliseconds | TIME_UNRESOLVED |
| `second_60_effective_at.json` | second 60 in `effective_at` | TIME_UNRESOLVED |
| `second_60_component.json` | second 60 in `position.observed_at` | TIME_UNRESOLVED |
| `hour_24_component.json` | hour 24 in `kinematics.observed_at` | TIME_UNRESOLVED |
| `february_30.json` | 30 February in `received_at` | TIME_UNRESOLVED |
| `component_after_effective.json` | `position.observed_at` one millisecond after `effective_at` | TIME_UNRESOLVED |
| `live_report_under_synthetic.json` | `"synthetic": false` under a synthetic adapter | SYNTHETIC_MISMATCH |
| `top_level_array.bin` | the report inside a JSON array | SCHEMA_INVALID |
| `duplicate_key.bin` | `profile` twice | JSON_INVALID |
| `nan_literal.bin` | `NaN` | JSON_INVALID |
| `infinity_literal.bin` | `Infinity` | JSON_INVALID |
| `number_overflow.bin` | `1e400` | JSON_INVALID |
| `number_underflow.bin` | `1e-400` | JSON_INVALID |
| `integer_not_double_exact.bin` | 2^53 + 1 | JSON_INVALID |
| `invalid_utf8.bin` | a byte 0xFF in a string | JSON_INVALID |
| `byte_order_mark.bin` | a UTF-8 byte order mark | JSON_INVALID |
| `lone_surrogate_escape.bin` | an escaped lone surrogate | JSON_INVALID |
| `depth_33.bin` | 33 nested containers | LIMIT_EXCEEDED |
| `nodes_10001.bin` | 10 001 JSON value nodes | LIMIT_EXCEEDED |

A report above 1 MiB or nesting deeper than 64 is not a file here (the wheel would carry a
mebibyte for one refusal): the adapter test and the conformance suite generate them.
