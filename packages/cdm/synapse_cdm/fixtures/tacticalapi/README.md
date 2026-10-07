# TacticalAPI fixtures — adapter #22, contract `rheinmetall.tactical_api.v0` at commit 58661c9

These are the harness fixtures for the `tacticalapi` adapter (blue-force read side, ingest only).
Every payload is the bytes the implementation record (`docs/tacticalapi-implementation.md` in the
repository) reads in §2.1: one serialized `google.protobuf.Any` wrapping one
`GetBlueForcesResponse` or `SubscribeBlueForceEventsResponse`. Beside each harness payload is its
`.parsed.json` twin, the dict form of the same message (the record's §2.2) as the package's decoder
renders it, because the harness's lossless column harvests leaves from a JSON document and a byte
string has none. The harness translates both, and both must give the same CDM objects.

This repository is not affiliated with, endorsed by or reviewed by Rheinmetall, the publisher of the
interface; the name appears only to say which published contract the payloads follow.

**Every payload is synthetic, and every one starts as protoc's own encoding of a text source;
none was written from scratch by hand. Fourteen are protoc's bytes unchanged. Seven were changed
afterwards by `spec/build_fixtures.py`: three have hand-encoded fields appended (two in `cases/`
and the harness fixture `snapshot_with_unknown_fields`), and four in `malformed/` are protoc's
bytes after one byte surgery each (both described below).**
`spec/build_fixtures.py` holds each case's text source as its own literal, copies it to
`sources/`, and has protoc 36.2 encode it against the ten pinned interface definition files
(located and hash-checked through `synapse_cdm.normative_binding.resolve`, never copied here). The
same script stores protoc's own reading of every payload under `independent/`, renders the twins,
writes every `PROVENANCE.json` and records the SHA-256 and size of every file in
`spec/tacticalapi_pin.json`. Every name carries the word EXERCISE, every UUID is the uuid5 of an
EXERCISE name, every position is an invented point in a Baltic exercise area off the Courland
coast (one is on the equator, where a zero latitude is the point), and nothing derives from any
recorded message. `python spec/build_fixtures.py --check` regenerates the whole set in memory and
names every file that differs, is missing or is extra; it needs protoc and the pinned files, and
reports `BLOCKED_EXTERNAL_EVIDENCE` without them. Nothing else here needs either.

## The harness fixtures

| Fixture | Message | What it exercises, and what makes it awkward |
|---|---|---|
| `snapshot_three_forces` | `GetBlueForcesResponse` | Three blue forces keyed by three identity kinds (a uuid, a string, an int32). The first has a MIL-STD-2525D numeric symbol, a height on the WGS 84 ellipsoid, `own_blue_force` and an organisation unit; the second a 2525C string symbol, a height at mean sea level, a course and speed, and a callsign with a non-ASCII letter; the third is unmanned, mounted on the second, with an estimated position and no height. Fractional seconds in 3 and 9 digits. |
| `delta_with_deletion` | `SubscribeBlueForceEventsResponse` | A streamed update: one blue force moved, keyed by the fourth identity kind, an int64 of 2^53 + 1, which a JSON number cannot hold exactly (the twin holds it as decimal text); a height against QNH. The second element deletes the snapshot's `EXERCISE-VEH-201`. Fractional seconds in 6 digits. |
| `awkward_zeros` | `GetBlueForcesResponse` | Zeros that are values: course 0 and speed 0 as present wrappers, a height of 0 on the topographic surface, an empty callsign and an empty error message on a successful header, an empty `blue_force_type`, an int32 identity of 0. The latitude is exactly 0 with a longitude of 9.25: protoc writes no proto3 scalar holding its default, so the latitude is absent from the wire, and a reader cannot tell it from an unset one. A second blue force's `location_time` is a present, empty Timestamp (seconds 0, nanos 0, what a default-constructed one serialises to) beside a real `last_contact_time`, which the adapter uses instead (the record's §5.3); its course is 360, the full turn, which `course_deg` cannot hold, so it is not mapped, where the first's course 0 is (the record's §5.6, added 2026-10-06). |
| `awkward_symbols_and_codes` | `SubscribeBlueForceEventsResponse` | A 2525C string symbol of 14 characters, a vertical reference code (12) and a measurement code (7) the contract does not name, the vendor's own symbol catalog with a laser-ranged position, and a 2525D numeric code whose standard-identity digit is 2 (assumed friend) rather than 3. |
| `snapshot_with_unknown_fields` | `GetBlueForcesResponse` | The content of `cases/unknown_field_carried` (below) under a name the harness selects, so that the harness's lossless column and the goldens meet the residual: four fields this contract revision does not define, appended by hand, on the response, the header, the first blue force and the second's geo_point. |

`golden/` holds the adapter's output over each, `<case>.cdm.json` for the payload and
`<case>.parsed.cdm.json` for its twin, written by the harness with `--update-golden` on
2026-10-04 and read value by value against the record before being kept. They were written again
on 2026-10-06, when the adapter landed in this repository, because every Entity and every Event now
carries a residual (the record's §5.9): the residual of each object was the only value that moved,
read against the goldens of 2026-10-04 path by path, and every other value is as it was. The two
files of a case are identical, which `tests/test_cdm_tacticalapi_adapter.py` asserts. The builder
neither writes nor compares them.

## `cases/`: accepted counterexamples, read by name in the tests

The harness never selects this directory. Each payload has its twin beside it.

| Payload | What it exercises |
|---|---|
| `unknown_field_carried` | Four fields this contract revision does not define, appended by hand after protoc wrote the rest: a string (field 3) on the response, varints on the header (field 3), on the first blue force (field 11) and on the second's geo_point (field 6). |
| `empty_geo_point` | A geo_point that is present and empty: no coordinate on the wire, so no position. |
| `empty_successful_response` | A successful snapshot with no blue force. |
| `deleted_without_timestamps` | A deleted blue force that states its identity and no time of any kind. |
| `duplicate_identity` | One identity twice in one message, ten seconds apart. |
| `d_code_second_set_zero` | A 2525D numeric code whose second set is all zeros, so `second_ten_digits` is absent from the wire and reads 0. |
| `unknown_fields_without_carrier` | Two unknown fields (on the response and on the header) of a successful response with no blue force to carry them; the adapter refuses it. |
| `error_message_without_carrier` | A successful response with no blue force whose header states an error message; with no object to carry the text, the adapter refuses it (`error-message-without-carrier`). protoc's own encoding, unchanged. |

protoc's text form names fields by name, so it cannot state a field the type does not define. The
three payloads that need one (two here, and the harness fixture `snapshot_with_unknown_fields`)
get it by hand: the builder appends the field's octets to the message and re-encodes every
enclosing length. Only wire types 0 and 2 are appended, because protoc prints an
unknown fixed-width field as hexadecimal and the tests' text reader would read it back as a plain
number; the decoder's own tests carry all four wire types.

## `malformed/`: the refusal set (check H)

Binary payloads only. Four are protoc's own encoding of a message refused for what it says. protoc
will not write malformed data, so the other four are protoc's bytes changed afterwards by one
byte surgery each, a function in `spec/build_fixtures.py` named for what it breaks; the pin
repeats each description and protoc's own verdict on the result. "By" says which layer refuses:
the decoder refuses the payload before any CDM object exists; the adapter refuses a payload the
decoder reads cleanly.

| File | What is wrong with it | How it was made | Refused with | By |
|---|---|---|---|---|
| `truncated_varint.binpb` | A varint ends inside its message | protoc's bytes with the last octet of the blue force's `last_contact_time` (the final octet of its seconds varint) removed and the three enclosing lengths re-encoded one shorter, so every length is honest and the varint alone runs out | `truncated-varint` | decoder |
| `length_past_end.binpb` | A declared length runs past the end of the input | protoc's bytes with the last eight octets (the longitude's double) cut off, as a capture cut short; the Any's value still declares them | `length-exceeds-input` | decoder |
| `wire_type_mismatch.binpb` | A named field arrives with another wire type | protoc's bytes with the latitude (a double, wire type 1) rewritten as the 32-bit float of the same value (wire type 5) and the enclosing lengths re-encoded | `wire-type-mismatch` | decoder |
| `unsupported_message_type.binpb` | The Any wraps the write side's `AddOrUpdateBlueForcesResponse` | protoc's own encoding, unchanged | `unsupported-message-type` | decoder |
| `success_false.binpb` | An unsuccessful response that still lists a blue force; `success` is absent from the wire (protoc writes no false), which reads false | protoc's own encoding, unchanged | `response-not-successful` | adapter |
| `blue_force_without_identity.binpb` | A blue force with a callsign and a position and no identity | protoc's own encoding, unchanged | `blue-force-without-identity` | adapter |
| `two_oneof_members.binpb` | An identity holding both a `string_identity` and an `int32_identity` | protoc's bytes with an `int32_identity` appended to the identity and the enclosing lengths re-encoded | `multiple-oneof-members` | decoder |
| `latitude_91.binpb` | A latitude of 91 degrees | protoc's own encoding, unchanged | `coordinate-out-of-range` | adapter |

Two of the decoder's refusals are encodings a lenient parser accepts, and protoc's own readings
under `independent/` show what it makes of them: it reads the float latitude as an unknown field
and drops the latitude, and it keeps the last of the two identity members. protoc refuses
`length_past_end` outright and refuses the value of `truncated_varint`.

## The other directories

- `sources/` holds the text source of every payload, one `<case>.txtpb` each, exactly the literal
  `spec/build_fixtures.py` handed to protoc. A `#` comment at the top of each says what it is for
  and, where it matters, what protoc leaves off the wire.
- `independent/` holds protoc's reading of every payload it can read, in two parts, because
  protoc's printer does not expand an `Any`: `<case>.any.txtpb` is `protoc
  --decode=google.protobuf.Any` of the whole payload (the type_url and the value's octets), and
  `<case>.value.txtpb` is `protoc --decode` of those octets as the type the type_url names.
  `tests/test_cdm_tacticalapi_fixtures.py` reads every twin against these readings and against
  the source, convention by convention of the record's §2.2, so the decoder is never its own
  oracle.
- `spec/` holds `build_fixtures.py` and `tacticalapi_pin.json`, the record of all of the above:
  the contract's commit (not carried here), the protoc version, the commands, every file's
  SHA-256 and size, what was appended or cut, and protoc's verdict on every refusal payload.
- Every directory that holds a payload, a source or a reading has a `PROVENANCE.json`
  (`synthetic: true`, `classification: "PUBLIC"`); `golden/` and `spec/` have none.

## Reproducing

From the repository root, the harness reads this directory through the package and needs no
fixture path:

```
python -m synapse_cdm.harness --adapter tacticalapi --schemas schemas
python -m synapse_cdm.suite conformance run --adapter tacticalapi --require A,B,C,D,F,G,H,J,K,L,O
```

Neither needs protoc or the pinned files. `python spec/build_fixtures.py --check`, above, needs
both.
