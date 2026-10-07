# TacticalAPI blue-force read side → CDM: implementation record

Written 2026-10-04, before any code, as the specification of the `tacticalapi` adapter. The code
and the fixtures are held to this file. A rule that proves wrong is changed here, with a dated
note under "Changes", never worked around in code.

**Moved into this repository on 2026-10-06, when the adapter landed** (the adapter was built and
verified out of tree first, where this file was its `MAPPING.md`). The record now also holds what
the out-of-tree project kept in its README and the modules cite: "The maintainer's rulings
(2026-10-06)", "Licence of the embedded field table" and "Open items", below the typed block
layout. Sections 1 to 8 and the typed block layout name the repository's paths. The "Changes"
section is history and is annotated, not tidied: where an entry names the project's layout, read
`src/synapse_tacticalapi/` as `packages/cdm/synapse_cdm/adapters/`, `fixtures/tacticalapi/` as
`packages/cdm/synapse_cdm/fixtures/tacticalapi/`, `tools/gen_field_table.py`,
`tools/contract_comments.py` and `tools/protoc_text.py` as `gates/tacticalapi_field_table.py`,
`gates/tacticalapi_contract_comments.py` and `gates/protoc_text.py`,
`tests/test_tacticalapi_{adapter,codec,fixtures}.py` as `tests/test_cdm_tacticalapi_*.py` of the
same names, `tests/test_tools.py` as `tests/test_cdm_tacticalapi_tools.py`, `tests/protowire.py`
as `tests/tacticalapi_protowire.py`, `tests/contract_comment_digests.json` as
`tests/tacticalapi_comment_digests.json`, and `tests/test_promotion_gates.py` as
`tests/test_cdm_tacticalapi_contract_text.py`, which keeps the gates the repository has no
equivalent of (the others are the repository's own gates now). "README.md" there is this file's
rulings, licence and open-items sections, "MAPPING.md" is this file, "this project" is the
out-of-tree project, and `check.sh` has no counterpart: its stages are the repository's CI and the
commands of the adapter's documentation page.

Conventions: `pkg/` is `packages/cdm/synapse_cdm/` of this repository. "The contract" is the ten
interface definition files pinned outside every repository, in the directory
`SYNAPSE_CDM_TACTICALAPI_PROTO_DIR` names, beside their hash record `proto_pin.json` (upstream
commit `58661c9`, 2026-09-01; the upstream has no tag or release). Field names below are the contract's own names. "Refused" means
`to_cdm` raises a `ValueError` subclass whose message starts with the reason code given; nothing
is returned. The one exception is past the declared `max_input_bytes` (bytes) or `max_depth`
(dict, and the bytes inputs §2.1 names that the host reads as JSON text), where the base class
refuses first with `InputTooLarge` / `InputTooDeep` (changed 2026-10-04; see "Changes", adapter
stage, item 3).

The host measures every input before this adapter runs, and two inputs only an in-process caller
can build meet the host's own behaviour there rather than a refusal (stated 2026-10-04, final
verification, items 20 and 21). A `str` is measured as UTF-8 text by
`synapse_cdm.adapter.wire_size`, so a `str` holding a lone surrogate raises `UnicodeEncodeError`
there (a `ValueError` subclass) before the adapter can refuse it `not-an-any-envelope`. A `dict`
that contains itself is walked by `synapse_cdm.adapter.container_depth`, which has no early exit,
so `to_cdm` does not return; the codec's own entry points (`validate_twin`, `twin_of`) stop at
the first container past `max_depth` and refuse it `nesting-too-deep`. Both are the host
package's, listed under "Open items" below. So is a third (stated 2026-10-04, final
verification, item 37): the host's measure tests the input, and every value inside a `dict`
at any depth, with `isinstance`, which asks an object's `__class__`, and then calls the methods
of what it took for octets, text, a `dict` or a `list`. So an object whose `__class__` claims
one of those types and is not one (as the input, or as a `dict` or `list` inside one), or any
object inside a `dict` whose `__class__` raises, raises there, whatever it raises. Where such
an object reaches the codec instead (a scalar or a key), the codec reads the value's own type
and refuses it by name (§3.2). Code an in-process object runs of its own while it is read, such
as an overridden method of a `dict` or `list` subclass, may raise anything, and that is not
bounded either; `validate_source` writes such an exception as one bounded line (§6), unless
the object raised one of the three refusal classes itself: a refusal's text is written as
raised, so a forged one is as long as its author made it (stated 2026-10-05, after the final
verification, item 38).

## 1. Scope

- **In:** the two read-side responses of the `BlueForceTracking` service:
  `rheinmetall.tactical_api.v0.GetBlueForcesResponse` and
  `rheinmetall.tactical_api.v0.SubscribeBlueForceEventsResponse`.
- **Out, refused with `unsupported-message-type`:** every other message of the contract (own pose,
  situation objects, all requests, the write-side blue-force messages) and any type not in the
  contract. The refusal names the two supported types.
- **Never in the adapter:** gRPC, sessions, stream bookkeeping, keep-alive timing. The caller
  receives the message and hands it over.
- **Direction:** ingest only. No encoder exists in the shipped modules.

## 2. Unit of ingest and the two input forms

One `to_cdm` call takes one response message. A stream is a sequence of calls.

### 2.1 Bytes form

A serialized `google.protobuf.Any`: field 1 `type_url` (string), field 2 `value` (the response
message's bytes). A serialized message does not name its own type; the `Any` wrapper is
protobuf's own way of doing so, and the receiving client knows which call it made.

- The type name is the part of `type_url` after the last `/`. A `type_url` with no `/` is refused
  (`malformed-type-url`). The prefix is carried verbatim and not otherwise checked.
- gRPC framing is not read. This is the `capture-envelope` limitation.
- The host, not this adapter, measures some bytes inputs as JSON text.
  `synapse_cdm.adapter.enforce_depth_bound` decodes the octets as `json.loads` would (UTF-8 here,
  an invalid octet read as U+FFFD), strips white space as `str.lstrip` does (U+0085 and U+00A0
  included), and reads the rest as JSON when its first character is `[` or `{`, refusing it
  `InputTooDeep` when it nests more than `max_depth` brackets. A payload the decoder reads begins
  with a tag of the `Any`: 0x12 (`value` first; not white space, so never read as JSON) or 0x0a
  (`type_url` first; a newline, white space) followed by the `type_url`'s length varint, so the
  rule is: the payload is read as JSON when it begins 0x0a and that varint's octets decode to a
  bracket, or to white space followed by a bracket. Within `max_input_bytes` that is six
  lengths whatever the `type_url` holds — 91 and 123 (one octet, `[` and `{`), and 1 491 650,
  1 495 106, 2 015 938
  and 2 019 394 (the three-octet varints c2 85 5b, c2 a0 5b, c2 85 7b, c2 a0 7b: U+0085 or
  U+00A0, then the bracket) — and twenty more when the `type_url` itself begins, after any white
  space, with a bracket (c2 85 or c2 a0 followed by one of the ten single-octet white-space
  characters, 148 162 … 528 450). No other varint within the bound decodes to white space and
  then a bracket, over-long ones included: a one-octet length is white space only below 50, and
  a supported `type_url` is at least 50 octets; a two-octet varint decodes to U+FFFD first; of
  the three-octet varints only c2 85 … and c2 a0 … begin with a white-space character; and past
  three octets the last octet is shifted by 21 bits or more, so within the bound it is 0, 1 or
  2, none of them white space or a bracket ("Changes", adapter stage, item 3, and final
  verification, items 7 and 19).

### 2.2 Dict form (the "twin")

The dict the harness loads from a `.parsed.json` file, and what a caller that already holds a
decoded message passes. It is the ProtoJSON rendering of the same `Any`, with these rules:

| Aspect | Rule |
|---|---|
| Type | key `@type` holds the full `type_url`; the message's fields sit beside it |
| Field names | the contract's own names (`blue_forces`, `last_contact_time`), never lowerCamelCase |
| Presence | a key is present if and only if the field was on the wire. A scalar that was on the wire with its default value is present with that value |
| `Timestamp` | RFC 3339 text in UTC with `Z` and 0, 3, 6 or 9 fractional digits |
| Wrapper types (`StringValue`, `DoubleValue`) | the bare value |
| `double` | JSON number |
| `int64` | decimal text; `int32` a JSON number |
| `bool` | `true` / `false` |
| Enum | the contract's value name; a number the contract does not name stays a JSON number |
| `oneof` | the one member that was on the wire |
| Unknown wire fields | key `@unknown` on the message that held them: a list of `{"number", "wire_type", "hex"}` in wire order, `hex` being the field's raw value bytes in lowercase (for wire type 0 the varint's octets as written, for wire type 2 the payload without its length prefix) |
| `null` | refused (`null-in-twin`): presence is stated by the key, and `null` is ambiguous |
| Key order | `@type`, the known fields by field number, a dict-form input's unknown keys in input order, `@unknown` |

The adapter translates the twin. The bytes path is: decode bytes to a twin, then translate the
twin. Both forms of one message therefore produce the same CDM objects.

A key in a dict-form input that the contract does not name (and is not `@unknown`, nor the
response's own `@type`) is an unknown field and is carried (§3.3), never refused. A key `@type`
below the response itself — in the header, an element, a `geo_point` — is such a key: it is
carried at its own path under `residual.data.response` or `residual.data.blue_force` and listed
in `residual.data.unknown` like any other (stated 2026-10-04, final verification, item 12).

A dict-form input is held to this table exactly; a value in another spelling is refused
(`invalid-twin-value`), with two normalisations to the spelling the bytes path writes for the same
wire value: a `double` given as a JSON integer becomes a float, and a `Timestamp` given with 3, 6
or 9 fractional digits is rewritten with the fewest of 0, 3, 6 or 9 that hold it. An integer
given for a `double` that a double cannot hold exactly (2^53 + 1, say) is refused
(`invalid-twin-value`): converting it would round it, which is a repair. A repeated field
or `@unknown` given as an empty list is dropped, since nothing of it could have been on the wire.

Every accepted value is returned as a plain `int`, `str`, `float` or `bool`, never as a subclass
of one (an `IntEnum` member given for an `int32` or an unnamed enum number comes back as its
number), and every container of the result is new. A `bool` stays excluded: it is never
accepted where an `int32`, an enum number or a `double` is due, although Python counts it as an
integer. The plain value is taken with the base type's own conversion (`str.__str__`,
`int.__int__`, `float.__float__`), so it holds the subclass instance's own content: `str()` of a
`(str, Enum)` member is `Class.MEMBER`, not the characters it holds, and two inputs that compare
equal translate alike. Keys are made plain the same way before they are read, and two keys of
one object that hold the same text (a subclass may hash otherwise than its text, so a dict can
hold both) are refused (`invalid-twin-value`) rather than one of them dropped (changed
2026-10-04, final verification, item 13).

An integer anywhere inside the value of a key the contract does not name must lie within
−2^63 … 2^64 − 1, else it is refused (`invalid-twin-value`): ProtoJSON writes no wider integer,
and past some 4 300 decimal digits Python's own JSON writer and reader cannot write the number
or read it back (added 2026-10-04, final verification, item 14). `json.loads` never makes one
that long; an in-process caller can.

## 3. Decoder (`tacticalapi_codec.py`)

Standard library only. Decode only. It builds no CDM object and reads no file.

### 3.1 Embedded field table

- Covers exactly the closure of the two supported responses: the two responses,
  `ResponseHeader`, `BlueForce`, `BlueForceType`, `Identity`, `SymbolIdentifier`,
  `NumericIdentifier`, `Point`, `GeoPoint`, the enums `SymbolCatalog`,
  `VerticalDistanceReferenceCode` and `MeasurementCode`, plus the well-known types `Any`,
  `Timestamp`, `StringValue` and `DoubleValue`.
- Holds names and numbers only: message name → field number → (field name, kind, type, repeated,
  oneof group); enum name → number → value name. No comment text from the contract.
- Generated by a tool from `protoc`'s own descriptor of the pinned files, never typed by hand. A
  test regenerates it from the pinned files and holds the embedded table equal; that test reports
  `BLOCKED_EXTERNAL_EVIDENCE` and skips when the pinned files or `protoc` are absent.
- The decoder reads the table under proto3's rules (an absent scalar is its type's zero, an enum
  is open), so the tool stops rather than print a table when a closure message or enum comes from
  a file whose syntax is not `proto3`, or a field is `required` or states a default value
  (added 2026-10-04, final verification).

### 3.2 Refusals (reason codes)

| Code | Condition |
|---|---|
| `input-too-large` | more bytes than the declared `max_input_bytes` |
| `truncated-varint` / `varint-too-long` | a varint that ends early, or runs past 10 bytes, or whose tenth byte sets bits past the 64th, or a tag written in more than five bytes (a tag is a 32-bit value; changed 2026-10-04, final verification) |
| `length-exceeds-input` | a declared length, or the 8 or 4 bytes of a fixed-width field, that the remaining bytes of the enclosing message cannot hold (checked before slicing) |
| `unsupported-wire-type` | wire types 3, 4 (groups), 6, 7 |
| `field-number-zero` | a tag with field number 0 |
| `field-number-too-large` | a tag with a field number past 2^29 − 1 |
| `wire-type-mismatch` | a field the table names, arriving with another wire type |
| `invalid-utf8` | a string field that is not valid UTF-8 (dict form: a text value that cannot be written as UTF-8) |
| `non-finite-number` | NaN or an infinity in any `double` the table names, and in the dict form also an integer given for a `double` past the double range, and NaN or an infinity anywhere in the value of a key the contract does not name. A NaN or an infinity given for any other known field (an `int32`, a `bool`, a text field, an enum, a message) or inside an `@unknown` entry is not a value of that field's JSON type and is refused `invalid-twin-value` (changed 2026-10-04, final verification) |
| `timestamp-out-of-range` | seconds outside 0001-01-01T00:00:00Z … 9999-12-31T23:59:59Z, or nanos outside 0 … 999 999 999 |
| `value-out-of-range` | an `int32` or enum outside −2^31 … 2^31 − 1 read as a signed 64-bit value, a `bool` other than 0 or 1, an `int64` text outside the `int64` range |
| `repeated-singular-field` | a singular field occurring twice in one message |
| `multiple-oneof-members` | two members of one `oneof` in one message |
| `unknown-field-in-well-known-type` | a field number `Any`, `Timestamp`, `StringValue` or `DoubleValue` does not define (§3.3) |
| `nesting-too-deep` | twin nesting past the declared `max_depth`, counted in containers (one per object or list) as `synapse_cdm.adapter.container_depth` counts them, so both forms of a message have one depth. The codec's walk stops at the first container past the bound, so a dict that contains itself is refused here too (changed 2026-10-04, final verification, item 21) |
| `too-many-objects` | more blue forces than the declared `max_objects` allows (checked before objects are built) |
| `too-many-unknown-fields` | more unknown fields in one input than the codec's `MAX_UNKNOWN_FIELDS` (§3.3); in the adapter, more carried than that, a message- or header-level field counting once per Entity that carries it (changed 2026-10-04) and once per Event that carries it (changed 2026-10-06, §5.9) |
| `carried-copies-too-large` | adapter only, both forms: the message-level data every Entity and every Event carries, measured once, times the number of elements, past `MAX_CARRIED_COPY_CHARS` (§4, §6); checked after the `too-many-unknown-fields` count and before any object is built (added 2026-10-04, final verification; the Event's copies counted since 2026-10-06, §5.9) |
| `malformed-type-url`, `unsupported-message-type` | §1, §2.1 |
| `not-an-any-envelope` | the input holds no `type_url`, i.e. it is not the envelope of §2.1; also an input that is neither octets (`bytes`, `bytearray`, `memoryview`) nor, for the dict form, a `dict`, including one handed to a direct codec call that reads octets (changed 2026-10-04, final verification) |
| `invalid-twin-value` | dict form only: a value whose JSON type or spelling is not the one §2.2 gives its field, a malformed `@unknown` entry, two keys of one object holding the same text, or an integer outside −2^63 … 2^64 − 1 in the value of a key the contract does not name (§2.2; the last two added 2026-10-04, final verification) |

Nothing is repaired. Several of these are encodings a lenient protobuf parser accepts
(`repeated-singular-field`, `multiple-oneof-members`, `wire-type-mismatch`, and the varints
`value-out-of-range` and `varint-too-long` name that a lenient parser truncates, reads as true or
reads although a tag is padded past five bytes); this decoder refuses them and says so in the
`non-canonical-encoding-refused` limitation.

A refusal's message is one printable line of bounded length, whatever the input held (added
2026-10-04, final verification). Every value it takes from the input, in the codec and in the
adapter, is quoted by one helper, `tacticalapi_codec.quote`: the value's repr, cut to 120
characters with the number of characters left out stated; a value whose repr raises (an integer
past Python's digit limit, or an in-process caller's object whose `__repr__` raises anything) is
described by its type instead, and the refusal it was quoted for is still the one raised
(widened 2026-10-04, final verification, item 20). A dict key enters a refusal only
through one other helper, as itself when it is a field name of the table or `@unknown` and
quoted otherwise, so a key holding a line break or a lone surrogate arrives escaped. The
`type_url` is quoted once. The repr is taken as plain text (`str.__str__`, since a `__repr__`
may return a `str` subclass that writes itself otherwise), and a type name that a refusal or a
`validate_source` line writes goes through a third helper, `tacticalapi_codec.quote_type`,
which reads the type's own name and escapes and cuts it as `quote` does (item 34). Every type
test the codec applies to a value of the input reads the value's own type, `type(value)`, never
its `__class__`, which an in-process caller's object can define to name a type it is not, or to
raise; such an object is refused as any value of the wrong type is, under its own type's name
(item 37).

### 3.3 Unknown fields are carried

- A field number the table does not name, at any level, is kept with its number, wire type and
  raw bytes, and decoding continues. The exception is a well-known type: `Any` merges into the
  twin's top level and `Timestamp`, `StringValue` and `DoubleValue` are bare values, so none has an
  object to carry `@unknown`; a field one of them does not define is refused
  (`unknown-field-in-well-known-type`). These types are frozen upstream, so such a field is a
  malformed encoding, not a newer contract revision.
- At most `MAX_UNKNOWN_FIELDS` (65 536) unknown fields are carried per input, both forms, all
  levels together (`too-many-unknown-fields`); without a count, each carried field costs some
  hundred times its two-byte wire minimum. The adapter counts the copies it carries: a message-
  or header-level field once for every Entity that carries it (changed 2026-10-04) and once for
  every Event that carries it (changed 2026-10-06, §5.9), so on one element such a field counts
  twice and an element's own field once.
- An enum number the contract does not name is kept as the number.
- The adapter places every unknown field in `residual.data.unknown` with the path of the message
  that held it, and also at its own relative path under `residual.data.response` or
  `residual.data.blue_force` (changed 2026-10-04); every Event carries the message- and
  header-level ones the same way (changed 2026-10-06, §5.9); `validate_source` names each one.
- A new upstream commit is a new pin and a new adapter version, never a silent update.

## 4. Message-level rules

| Source | Rule |
|---|---|
| `header.success` | must be `true`. Absent header, absent `success` or `false` → refused (`response-not-successful`), quoting `error_message` when present |
| `header.error_message` on a successful response | carried in the typed block's `message` member |
| zero blue forces, no unknown field, no `error_message` text | returns `[]` (a successful empty snapshot is not a failure). An `error_message` present and empty holds no text, so it does not stop this row |
| zero blue forces, unknown fields present | refused (`unknown-fields-without-carrier`): no object exists to carry them |
| zero blue forces, no unknown field, a header `error_message` of one or more characters | refused (`error-message-without-carrier`), for the reason the row above gives: no object exists to carry it. The refusal shows the text through `tacticalapi_codec.quote` (added 2026-10-04, final verification, item 11) |
| message- and header-level unknown fields | carried on every `Entity` and, since 2026-10-06, every `Event` of the message (§5.9) |
| message-level carried data of all the `Entity`s and `Event`s past `MAX_CARRIED_COPY_CHARS` (§6) | refused (`carried-copies-too-large`), in both forms, after the `too-many-unknown-fields` count and before any object is built. The data is what every `Entity` carries: the typed block's `message` member (type, `type_url`, list name, index, header with its `error_message`) and the message- and header-level unknown fields in both places an `Entity` carries them (`residual.data.response`, and their entries of `residual.data.unknown`); and what every `Event` carries since 2026-10-06 (§5.9), those unknown fields again in the same two places; every copy counted. It is measured as the number of characters of its compact JSON text with ASCII escaping, which is what `json.dumps(value, separators=(",", ":"))` writes, each value of it once (`residual.data.response` only when it is carried, i.e. not empty); the size times the number of elements, with each `Entity`'s index counted with its own digits, is the measure held to the bound. The text is written once per message, never per `Entity` (added 2026-10-04, final verification; the measure changed the same day, item 14) |
| two elements with the same identity | both translated, in order. Nothing is merged or dropped |

The message-level refusals are checked in this order: `response-not-successful`, then (zero blue
forces only) `unknown-fields-without-carrier`, then `error-message-without-carrier`, then, for a
message with blue forces, `too-many-unknown-fields` and `carried-copies-too-large`, and the
element rules of §5 as each element is translated.

Each element of `blue_forces` / `updated_blue_forces` yields one `Entity` followed by one `Event`,
in list order.

## 5. Element rules

`SYSTEM = "TacticalAPI"`; it is `source_ids[].system`, the residual namespace and
`metadata.format.name`.

### 5.1 Typed block (never-drop carrier)

`Entity.attributes["tacticalapi"]` is a named, versioned contract, `tacticalapi-blueforce/1`:

- `contract`: the contract name.
- `message`: the type name, the `type_url` as stated, which list the element came from, its index
  and the header as stated.
- `blue_force`: the element exactly as the twin states it, known fields only, values unchanged
  (times as text, `int64` as decimal text, enums as stated).

Canonical CDM fields are projections of this block. Because the block holds the element whole,
nothing a conditional rule declines to project is lost. A pydantic model in the codec, with extra
keys forbidden, validates the block. The builder fixes the exact key layout to fit the ledger
grammar in `pkg/lossless.py` and records it under "Typed block layout (as built)" below.

Every basis named in the tables below is a top-level key of `Entity.attributes` (or of
`Event.payload` for event fields), as `tak` does.

### 5.2 Identity

| Source | CDM | Rule |
|---|---|---|
| `identity.<member>` | `source_ids[0]` = (`TacticalAPI`, `<member>:<value>`); `entity_id = ids.derive("TacticalAPI", "<member>:<value>", kind="entity")`; `entity_id_basis` | The member name is kept so the text `7` and the integer `7` stay two identities |
| identity absent, or no member set | refused (`blue-force-without-identity`) | An entity cannot be keyed |
| a string member holding the empty string | refused (`empty-identity`) | |
| `mount_host`, `associated_organization_unit_identity` | typed block only | No CDM home; no entity id is derived for another object |

The identity value is kept verbatim: nothing is trimmed, case-folded or otherwise normalised
before it is keyed, since a rewritten key would be a repair. The consequence for a
`uuid_identity`: UUID text is case-insensitive on input under the RFC the contract cites for
that member, but `7E0789F0-…` and `7e0789f0-…` are two `external_id`s and two `entity_id`s
here, so two producers that spell one UUID in different letter case yield two entities (stated
2026-10-04, final verification, item 27).

### 5.3 Time

| Source | CDM | Rule |
|---|---|---|
| `point_location.location_time` | `Entity.valid_from`, `Event.observed_at` | First choice |
| `last_contact_time` | the same two fields | Used when the location time is absent or zero |
| neither present, or each present one zero | the injected clock (`self.now()`) | Applies to live and deleted elements alike; the read side marks no field mandatory |
| a Timestamp read as seconds 0 and nanos 0 (`1970-01-01T00:00:00Z`) | not a source time | Mirrors §5.5: proto3 cannot tell it from an unset one (a default-constructed Timestamp serialises to it), and the CDM forbids an unknown time becoming 1970-01-01. The next choice in the order above is used, both forms alike, and the stated text stays in the typed block. Applies to `location_time` and to `last_contact_time` (limitation `proto3-zero-indistinguishable`; added 2026-10-04, final verification, item 16) |
| a Timestamp read as seconds 0 and nanos 1 … 999 999 (`1970-01-01T00:00:00.000000001Z` … `1970-01-01T00:00:00.000999999Z`) | a source time like any other | A stated value: a default-constructed Timestamp has nanos 0, so this one was set, and the adapter does not infer that it is unset. The CDM renders instants to the millisecond, truncating, so it becomes `1970-01-01T00:00:00.000Z`, the text the CDM forbids for an unknown time, and the host's check J cannot tell that output from the forbidden one. `validate_source` reports each such Timestamp in one line, and it is used as stated, in both forms (stated 2026-10-04, final verification, item 33) |
| `0001-01-01T00:00:00Z`, the earliest instant a Timestamp holds | a source time like any other | A stated value. Some platforms write it for a time never set, so `validate_source` reports it in one line, and it is used as stated |

`valid_from_basis` and `observed_at_basis` always say which of the three was used, naming the
source field, each zero Timestamp passed over, or stating that the source gave no time and the
receipt instant stands in. `validate_source` names each zero Timestamp. The CDM renders instants
to milliseconds; the source text is in the typed block unchanged. `Event.received_at` is always
`self.now()`.

### 5.4 Affiliation, type, symbol

| Source | CDM | Rule |
|---|---|---|
| no caller affiliation (the default) | `Entity.affiliation = UNKNOWN`; `affiliation_basis` | The message carries no affiliation field. That the service's own definition names the members of its list blue forces is a statement about the service, not a field of the message, and the adapter asserts no affiliation from it or from the deployment context a message arrives in: the `stanag4586` reading of a format with no affiliation field (its module docstring, "WHY AFFILIATION IS UNKNOWN"). Never read from a symbol code. R3, ruled 2026-10-06; `FRIENDLY` until then |
| an affiliation the caller supplies, `TacticalapiAdapter(affiliation=<member>)` | `Entity.affiliation` = that member, on every Entity the instance emits; `affiliation_basis` says the caller supplied it | Caller context, as `c2sim` takes its `own_side`: one of the four `Affiliation` members. The adapter compares it with nothing in the message, a symbol code included (adapters do not judge). R3, ruled 2026-10-06 |
| a supplied affiliation that is not an `Affiliation` member | the constructor refuses it: `ValueError`, text beginning `invalid-affiliation` | Anything but the four members or `None`, a text that spells a member included, is refused when the adapter is built; nothing is converted. The type is read from the value itself (`type(value)`, item 37). A construction refusal is not a refusal of an input: it is no `TacticalapiRefused`, and the code is not among §3.2's |
| `blue_force_type.is_vehicle` or `.is_unmanned` true | `entity_type = PLATFORM` | |
| otherwise | `entity_type = UNKNOWN`; `entity_type_basis` | A bare `bool` has no presence: false and unset are the same, so "not a vehicle" is not readable as person or unit |
| `symbol` with catalog `SYMBOL_CATALOG_MIL2525_D`, numeric form, first set in 1 000 000 000 … 9 999 999 999, second set in 0 … 9 999 999 999 | `Entity.symbol` = the first set followed by the second set zero-padded to ten digits | Not rewritten. A set absent from the wire reads 0: an absent second set is the valid value `0000000000`; an absent or zero first set is not a code and is not promoted |
| any other `symbol` (other catalog, string form, no identifier, out-of-range set) | typed block only; `Entity.symbol` is `None` | No converter exists and none is written. The string's length is reported by `validate_source` under the two catalogs the contract states it for (§6), not enforced |
| no `symbol` | `Entity.symbol` is `None` | No symbol is derived (R4, ruled 2026-10-06: confirmed as built) |

`symbol_basis` states which row applied. When a promoted symbol's standard-identity digit is not
the friend digit, the symbol is carried unchanged and `validate_source` names the disagreement.
It is a source-consistency observation against the service's own definition (its members are
blue forces), not against `Entity.affiliation`: that is `UNKNOWN` unless the caller supplies
one, and a supplied one is not compared with the symbol either (stated 2026-10-06, R3).

`fixture_instance` (Adapter API 3.1.0) is not overridden: the harness, the conformance suite and
the evidence generator build the adapter as the base class does, with no caller affiliation, so
the packaged fixtures are replayed with the default and the goldens hold `UNKNOWN` (2026-10-06,
R3).
A 2525D symbol with neither member of its `identifier` oneof on the wire is not promoted, and
its basis says it sets no identifier, not that it is in the string form (corrected 2026-10-04,
final verification, item 25).

### 5.5 Position

A `Position` is emitted if and only if `point_location.geo_point` is present and at least one of
`latitude_coordinate` / `longitude_coordinate` was on the wire.

| Source | CDM | Rule |
|---|---|---|
| `latitude_coordinate`, `longitude_coordinate` | `Position.lat`, `.lon`; `Event.geometry` = Point `[lon, lat]` | Taken as WGS 84 decimal degrees. The contract says the point is on the WGS 84 ellipsoid and gives no angular unit; degrees is inferred from every other angle in the contract (limitation `coordinate-unit-not-stated`). One coordinate absent from the wire reads 0.0 and `position_basis` says so |
| neither coordinate on the wire, or no `geo_point` | `position` is `None`, no event geometry; `position_basis` | Under proto3 an unset pair and 0°N 0°E are the same bytes; the CDM forbids a zero position standing for unknown (limitation `proto3-zero-indistinguishable`) |
| latitude outside −90 … 90 or longitude outside −180 … 180 | refused (`coordinate-out-of-range`) | |
| `vertical_distance` with a reference code | `Position.vertical` = (value, metres, reference per the table below); `alt_m` = value only for code 11 | No datum conversion. With no `vertical_distance`, `vertical` is `None` whatever the code says |
| `measurement_code` | `Position.position_source` per the table below; `position_source_basis` | The code itself stays in the typed block |

Vertical reference codes (all twelve; any other number is treated as code 0):

| Code | Contract value | `VerticalReference` | Why |
|---|---|---|---|
| 0 | UNSPECIFIED | `UNKNOWN` | A value this interface version does not know |
| 1 | UNKNOWN | `UNKNOWN` | Stated unknown |
| 2 | CHART_DATUM | `UNKNOWN` | No CDM member for a tidal chart datum |
| 3 | LOCAL_DATUM | `UNKNOWN` | No CDM member for a local datum |
| 4 | MEAN_SEA_LEVEL | `MSL` | |
| 5 | PRESSURE_DATUM_QFE | `BARO` | Altimeter reading against a stated pressure setting |
| 6 | PRESSURE_DATUM_QNH | `BARO` | As above |
| 7 | PRESSURE_DATUM_STANDARD_ATMOSPHERE | `BARO` | The CDM's `FL` reference is valid only with the `FL` unit, and the source states metres |
| 8 | TOPOGRAPHIC_SURFACE | `AGL` | Height above the surface beneath the object |
| 9 | WATER_BOTTOM | `UNKNOWN` | No CDM member |
| 10 | WGS84_GEOID | `MSL` | The CDM defines `MSL` as a geoid model |
| 11 | WGS84_REFERENCE_ELLIPSOID | `HAE` | `alt_m` is set, because the value is metres above the ellipsoid |

Measurement codes:

| Code | Contract value | `PositionSource` | Why |
|---|---|---|---|
| 2 | GPS | `GNSS` | |
| 3 | INS | `INERTIAL` | |
| 4 | ESTIMATE | `MANUAL` | The contract's code for a position a person entered by judgement rather than measured |
| 0, 1, 5, any other number, or code absent | UNSPECIFIED, UNKNOWN, LRS, unnamed | `ESTIMATED` | `position_source` is required and has four members, none meaning unknown or laser-ranged; the basis states the source's own code (`tak` precedent) |

### 5.6 Kinematics

| Source | CDM | Rule |
|---|---|---|
| `point_location.speed` | `Kinematics.speed_mps` | Metres per second as stated. Negative → refused (`negative-speed`) |
| `point_location.course` in [0, 360) | `Kinematics.course_deg`; `course_basis` | Degrees as stated, read as degrees true. The contract states degrees and no north reference, and `course_deg` means degrees true, so the north reference is ASSUMED true and `course_basis` says so on every Entity whose course is mapped (limitation `course-reference-not-stated`; R5, ruled 2026-10-06; §8 question 2 stays open). The range is the host's: `Kinematics.course_deg` is `ge=0.0, lt=360.0`. -0.0 compares equal to 0, so it is in range and mapped as stated, as a speed of -0.0 is |
| `point_location.course` of 360, below 0 or past 360 | typed block only; `course_deg` is `None`; `course_basis` | Not mapped and not normalised (no modulo, no clamping): the value stays in the typed block, `course_basis` states it and why it is not mapped, and `validate_source` names it by its path (R5, ruled 2026-10-06) |
| a NaN or an infinity in `point_location.course` | refused (`non-finite-number`) | By the codec, before this rule: §3.2 refuses a NaN or an infinity in every double the table names, in both forms, so R5 adds no rule of its own for one |
| neither present | `kinematics` is `None` | Absent is unknown, never zero. A wrapper present with value 0 is a real 0 |
| `speed`, or a course in [0, 360), present | `kinematics` holds what is present, the other member `None` | `kinematics` exists when the speed or a mapped course is present, so a course with no speed is kinematics of its own; a point stating only a course outside [0, 360) has `kinematics` `None` and its `course_basis` (changed 2026-10-06, R5: the rule "`course` without `speed` → `kinematics` is `None`", added 2026-10-04 while course had no CDM home, is replaced) |

### 5.7 Deletion

| Source | CDM | Rule |
|---|---|---|
| `is_deleted` true | `Entity.status` = (state `is_deleted`, namespace `TacticalAPI`, `since` `None`); `Event.event_type = STATUS_CHANGE` | The state token is the source's own field name. No `valid_to` is invented: the contract says only that the blue force is no longer present, not when it ceased (R6, ruled 2026-10-06: confirmed as built) |
| otherwise | no status; `Event.event_type = TRACK_UPDATE` | |

A deleted element with no timestamps is translated like any other (§5.3), never a reason to refuse
the message.

### 5.8 Event

| Field | Value |
|---|---|
| `event_id` | `ids.derive("TacticalAPI", "<external_id>@<instant>", kind="event")` for a live report and `ids.derive("TacticalAPI", "<external_id>@<instant>#is_deleted", kind="event")` for a deleted element (`is_deleted` true); `event_id_basis` names which. `<instant>` is `observed_at` as the adapter writes it itself: UTC, to the millisecond (truncated), `Z`, and a four-digit zero-padded year. Two elements of one message with the same identity and the same instant (as rendered) and the same deletion state therefore get the same `event_id`: the identifier names one report of one blue force at one instant, and both elements are such a report. An id never depends on an element's place in a message. The adapter does not disambiguate them and does not merge them (§4): both Events are emitted, in order (stated 2026-10-04, final verification) |
| `severity` | `INFO`; `severity_basis`: the contract carries no urgency field |
| `related_entities` | the element's `entity_id` |
| `geometry` | §5.5 |
| `payload` | `contract` (`tacticalapi-blueforce/1`), the bases, and nothing that is not already in the entity's typed block |
| `observed_at`, `received_at` | §5.3 |
| `source_ids` | the element's identity, as on its Entity (§5.2) |
| `source.record_index` | the element's 0-based index in its list, on the Entity and on the Event alike; the rest of `source` is the host's stamp (`Adapter.source_ref()`), each object holding its own copy (§5.9) |
| `residual` | the message-level part of its Entity's residual (§5.9; since 2026-10-06, `None` until then) |

The deletion suffix (changed 2026-10-04, final verification, item 15): a blue force reported live
and then reported deleted with the same stored times — the contract's own deletion path, where
nothing newer was heard — gave a `TRACK_UPDATE` and a `STATUS_CHANGE` with one `event_id`, and a
consumer that deduplicates on the id would discard the deletion. A live report's input is
unchanged, so only deleted elements' ids moved. The two cannot collide: a live input ends in the
instant's `Z` and a deleted one in `#is_deleted`. `source.record_index` and `Event.source_ids`
are stated here as the code wrote them from the start (stated 2026-10-04, final verification,
item 28).

The instant is written by the adapter (changed 2026-10-04, final verification, item 17), in the
shape `times.render` writes, so the id does not depend on the platform's `strftime`. On this
platform the two texts are equal for every year the adapter admits, so no id moved for this
reason. Up to synapse-cdm 3.1.1, `times.render` wrote the year with `strftime('%Y')`, which
glibc under CPython 3.11 and 3.12 writes unpadded below the year 1000, so there `valid_from` and
`observed_at` of such an instant (`1-01-01T00:00:00.000Z`) would have failed the CDM schema's
timestamp pattern; it was listed under "Open items". Since synapse-cdm 3.2.0 `render`
writes four digits itself, so the two texts are equal for every year on every platform. The
adapter keeps its own writer: the id depends on no host version (resolved 2026-10-06, item 39).

### 5.9 Residual

`residual` is structured, namespace `TacticalAPI`, and every Entity and every Event carries one
whose `data` is never empty (changed 2026-10-06, the landing; layout under "Typed block layout (as
built)"):

- **An Entity's** `residual.data.unknown` lists every unknown field the Entity carries, with the
  path of the message that held it — the message- and header-level ones first, then the
  element's, each in twin order — and is `[]` when there is none. The same fields sit at their
  own relative paths under `residual.data.response` (message and header level) and
  `residual.data.blue_force` (the element's), so the ledger can bind each leaf; each of those two
  keys is present only when it holds something.
- **An Event's** residual is the message-level part of its Entity's: `residual.data.response` as
  on its Entity when present, and `residual.data.unknown` listing the message- and header-level
  entries of its Entity's `unknown`, in the same order, `[]` when there are none. It carries
  nothing of the element's: the element's unknown fields are its Entity's alone.

Until 2026-10-06 an object with nothing unknown carried `None`, and an Event always did. The
repository's lossless sweep (`tests/test_cdm_lossless.py`) holds every object of every
harness-selected fixture of a `structured` adapter to a residual with data, so the smallest
record that is never empty, `{"unknown": []}`, is what such an object now carries; nothing that
had a place before moved, and the ten goldens were written again for that residual alone. The
Event's copies of the message-level fields count against `MAX_UNKNOWN_FIELDS` (§3.3) and
`MAX_CARRIED_COPY_CHARS` (§4, §6) beside the Entity's, so the two bounds still hold every copy
the objects of a message carry.

Every Entity and every Event owns the containers it carries: its residual (and an Entity's typed
block) are its own copies, so changing one object's changes no other object's, no other place in
the same object, and not the input. Strings may be shared, since they cannot change (added
2026-10-04, final verification). Each Entity and each Event also owns its `source` (`SourceRef`) and that stamp's
`transformations` list: equal values, separate objects, so a change to one object's stamp shows
on no other (added 2026-10-04, final verification, item 22).

## 6. Declared metadata

| Field | Value |
|---|---|
| `name` / `metadata.id` | `tacticalapi` |
| class | `TacticalapiAdapter` in `pkg/adapters/tacticalapi.py`, registered as `tacticalapi` |
| constructor | `TacticalapiAdapter(clock=None, *, synthetic=True, affiliation=None)`: the base class's two arguments and `affiliation`, §5.4's caller context (added 2026-10-06, R3). `fixture_instance` is not overridden |
| `version` | `1.0.0` |
| `system` | `TacticalAPI` |
| `format.name` | `TacticalAPI` |
| `format.version` | `rheinmetall.tactical_api.v0, commit 58661c9 (2026-09-01); no tag or release exists` |
| `direction` | `ingest` |
| `binding` | `standard-encoding` (R2, confirmed 2026-10-06) |
| `license_class` | `OPEN` (R7, ruled 2026-10-06; changed from `LICENSED`). ARCHITECTURE.md §3.2 defines OPEN as a source standard publicly available under terms permitting free implementation. The upstream files are public on the publisher's repository, and the maintainer ruled that the Eclipse Public License 2.0 governs them (R8); the maintainer also ruled that this adapter, which holds field names, numbers and enum values and no upstream software or interface definition text, is not a controlled item (R10), so `CONTROLLED` does not apply. `LICENSED`, the earlier placeholder, is a standard obtained for a fee or under a signed agreement, which the upstream's terms are not |
| `maturity.level` | `L3`; `external_exercise` `None` |
| `claim_status` | `VERIFIED` (R2, confirmed 2026-10-06; changed 2026-10-04, final verification, item 18) |
| `capabilities` | `wire: true`; `directions_exercised: ["ingest"]`; the two message types; `unknown_fields: preserved` with its basis |
| `capabilities.limits` | `max_input_bytes`, `max_depth`, `max_objects` declared as implementation caps, each enforced before objects are built and tested at the bound and one past it; the other two absent with reasons. The values and their bases are the constants `MAX_INPUT_BYTES`, `MAX_DEPTH`, `MAX_OBJECTS` in `tacticalapi_codec.py`; `MAX_UNKNOWN_FIELDS` and `MAX_CARRIED_COPY_CHARS`, which the manifest has no field for, are declared beside `max_objects`, and the `resource-limits` limitation names both |
| `MAX_CARRIED_COPY_CHARS` | 16 × 2^20 = 16 777 216, the bound of §4's carried message-level data, in characters of compact JSON text with ASCII escaping, across all the elements of a message. Basis: four times the 4 MiB message ceiling `MAX_INPUT_BYTES` rests on; the `message` member of an ordinary successful snapshot is 200 characters of that text (230 for a stream update; its `type_url` and header about 100), so 10 000 such elements use about an eighth of it (a snapshot) to just under a seventh (a stream update). Without it a 4 MiB `error_message` on 10 000 elements would serialise to some 40 GiB. The measure is the JSON text since 2026-10-04 (final verification, item 14): the earlier one counted every number as one and every string by its characters, and a dict-form twin read from 3.6 million characters of JSON text (740 integers of 4 300 digits under a response-level key) measured inside the bound and serialised to some 64 billion; a string of control characters writes six characters for each. With integers held to the 64-bit range (§2.2), every value's measure is the text it adds to every Entity (added 2026-10-04, final verification), and to every Event that carries it since 2026-10-06 (§5.9) |
| `residual` | `structured`, with a `MAPPINGS` ledger |
| `evidence.available` | `false` until the first release that attaches the adapter's evidence records (limitation `evidence-availability`, renamed 2026-10-06 from `evidence-not-available`, which named the out-of-tree project) |

Limitations to declare (structured entries; none uses the word "provisional"):
`blue-force-read-side-only`, `capture-envelope`, `pinned-commit-v0`, `coordinate-unit-not-stated`,
`course-reference-not-stated`, `symbol-2525d-only`, `proto3-zero-indistinguishable`,
`non-canonical-encoding-refused`, `source-time-optional`, `no-endpoint-exercised`,
`evidence-availability` (the `evidence.available` sentence), and `resource-limits`.

`claim_status` is `VERIFIED` beside `binding: standard-encoding` (2026-10-04, final
verification, item 18). The host maintainer's ruling (B) of 2026-09-20 (ARCHITECTURE.md §3.4 and
`tests/test_cdm_manifests.py`) makes `VERIFIED` what green public gates
assert against the standard's own encoding, and the in-tree gate holds every shipped adapter to
`VERIFIED` (`PROVISIONAL` beside a provisional binding) and admits nothing else; the in-tree
ingest-only adapters at L3 (`aixm511`, `aixm52`, `geopackage`, `legion`, `pntmap`,
`stanag4586`) declare it, and `AdapterMetadata` accepts the pair. `IMPLEMENTED`, the earlier
default, would fail that gate on promotion. The maintainer confirmed the binding and the claim on
2026-10-06 (R2, "The maintainer's rulings" below); the other choice, the provisional binding
with the `PROVISIONAL` claim, is not taken. Out of tree a local replica of the gate held it; in
this repository the gate itself does.

`detect(raw)` answers true for an input whose type name is one of the two supported types. A
dict's `@type` is found and read as `to_cdm` finds and reads it
(`tacticalapi_codec.twin_type_url`): the one top-level key whose text is `@type`, a `str`
subclass included, holding text that can be written as UTF-8; no such key, two of them, or any
other value answers false (changed 2026-10-04, final verification, item 35). The form is read
from the input's own type, so an object whose `__class__` claims octets or a `dict` is neither
form, and the answer is `None`, "cannot tell" (item 37).
`validate_source(raw)` lists, without refusing: each unknown field, each symbol not promoted and
why, an identity-digit disagreement, each zero Timestamp passed over, each Timestamp less than a
millisecond after the epoch (item 33) and each at 0001-01-01T00:00:00Z (§5.3), each element with
no source time left, and a symbol string whose
length is not 15 under `SYMBOL_CATALOG_APP6_B` or `SYMBOL_CATALOG_MIL2525_C`, the two catalogs
the contract states the 15-character string form for; under any other catalog it states no
length and none is reported (changed 2026-10-04, final verification, item 26); and each
`point_location.course` outside [0, 360), which is not mapped (§5.6; added 2026-10-06, R5). Its lines are
bounded as refusals are: the one text of the input a line names, an unknown key, goes through
`tacticalapi_codec.quote` (item 24). A refusal, this adapter's `TacticalapiRefused` or the base
class's `InputTooLarge` or `InputTooDeep`, is written as its text, which is bounded where the
codec or the host made it (not where an in-process object raised one of those classes itself,
item 38); the text of any other exception (the host's own, on an input only an in-process caller
can build, as the opening paragraph states) goes through a fourth helper,
`tacticalapi_codec.quote_error`, which takes it as plain text and escapes and cuts it as `quote`
does, and describes it by its type when the text itself raises (item 37).

A value built from shared sub-lists (an in-process caller's `[v, v]` nested n deep; JSON text
cannot share a container) is walked and copied as the tree it stands for, 2^n nodes: n = 20, a
value of some 21 list objects within the depth bound, takes of the order of a second and a
hundred MiB in `validate_twin`, and of a few seconds and several hundred MiB in `to_cdm`, as
measured on one machine (two runs there differed by up to a factor of two), and each further
level doubles both. No node budget is declared for it; it is reachable only by an
in-process caller (stated 2026-10-04, final verification, item 21; worded to the order of
magnitude, item 36).

## 7. Fixtures (`fixtures/tacticalapi/`)

All synthetic; names carry the word EXERCISE. Every payload is synthetic, and every one starts
as `protoc`'s own encoding of a text source that `spec/build_fixtures.py` holds as its own
literal; none was written from scratch by hand. Fourteen of the twenty-one are `protoc`'s bytes
unchanged. Seven were changed afterwards by `spec/build_fixtures.py`: three have hand-encoded
fields appended (two in `cases/` and the harness fixture `snapshot_with_unknown_fields`), and
four in `malformed/` are `protoc`'s bytes after one byte surgery each (corrected 2026-10-04,
final verification, item 29: this paragraph and the `no-endpoint-exercised` limitation said
every fixture was written by `protoc`, which six payloads of the earlier nineteen were not).
`protoc`'s own readings of the written bytes are stored under `independent/`. Tests compare the
adapter with those readings and with the source literals, so the adapter is never its own
oracle. CI needs neither `protoc` nor the pinned files.

| Where | Content |
|---|---|
| top level (`<case>.binpb` + `<case>.parsed.json`) | `snapshot_three_forces`: three identity kinds, a 2525D numeric symbol, a 2525C string symbol, heights on the ellipsoid and at mean sea level. `delta_with_deletion`: a streamed update with one deleted blue force. `awkward_zeros`: wrapper-present zeros (course 0, speed 0) and latitude exactly 0 with a non-zero longitude, and a second blue force whose `location_time` is the zero Timestamp beside a real `last_contact_time` (§5.3) and whose course is 360, outside the range `course_deg` holds, beside the first's mapped course 0 (§5.6; added 2026-10-06, R5). `awkward_symbols_and_codes`: a 14-character symbol string, an unnamed measurement code, the vendor catalog. `snapshot_with_unknown_fields`: `cases/unknown_field_carried` under a name the harness selects, so the harness's lossless column, check D and the golden cover the residual bindings (added 2026-10-04, final verification, item 29). Five fixtures, ten harness files |
| `golden/` | written by the harness with `--update-golden`, read before being kept |
| `malformed/` | truncated varint; length past the end; wrong wire type on a named field; type outside the supported two; `success` false; blue force without identity; two `oneof` members; latitude 91 (binary payloads, since the 16-level JSON limit and the refusals are about bytes; dict-form refusals are tested with in-memory dicts) |
| `cases/` (read by name in tests, never selected by the harness) | unknown field carried; empty `GeoPoint`; empty successful response; deleted element with no timestamps; duplicate identity in one message; 2525D code whose second set is all zeros; unknown fields with no carrier; an error message with no carrier (§4) |
| `sources/` | the text sources `protoc` encoded |
| `independent/` | `protoc`'s decode of each written payload it can read, in two parts: `<case>.any.txtpb` (`--decode=google.protobuf.Any` of the payload) and `<case>.value.txtpb` (`--decode` of the envelope's value as the type its `type_url` names). The pin records protoc's verdict on every `malformed/` payload, including the ones it refuses to read |
| `spec/` | `build_fixtures.py` (with `--check`, which reproduces every generated file byte for byte) and `tacticalapi_pin.json` (`carried_here: false`, per-fixture hashes) |
| every directory above except `golden/` and `spec/` | a `PROVENANCE.json` (`synthetic: true`, `classification: "PUBLIC"`) |

No shipped `.json` nests deeper than 16 levels.

## 8. Questions for the upstream publisher (not yet asked; three ruled by the maintainer instead)

1. The angular unit of `latitude_coordinate` and `longitude_coordinate`.
2. The north reference of `Point.course`. Still open: meanwhile R5 (the rulings, ruled 2026-10-06)
   assumes true north, and every mapped course says so in its basis (§5.6).
3. Whether a deleted blue force keeps its timestamps and identity fields.
4. Whether the string symbol form is 15 characters (the published test client sends 14).
5. Whether a stream marks the end of the initial snapshot.
6. Which licence statement governs the interface definition files. *Ruled by the maintainer on
   2026-10-06, not asked:* the Eclipse Public License 2.0, the statement of the upstream
   repository's licence file (the rulings, R8).
7. Consent to use the interface name. *Ruled by the maintainer on 2026-10-06, not asked:* the
   name is kept without written consent, and the maintainer accepts the risk the upstream
   README's reservation of the publisher's names states (the rulings, R9).
8. Which export-control regime and classification, if any, the upstream's note on export control
   means for the interface definition files, and whether it reaches an adapter that holds only
   their names and numbers (the rulings, R10; added 2026-10-04, final verification, item 31).
   *Ruled by the maintainer on 2026-10-06, not asked:* the adapter holds field names, numbers
   and enum values of a publicly published interface, no upstream software and no interface
   definition text, and is not a controlled item; nothing is classified (the rulings, R10).

## Typed block layout (as built)

Written 2026-10-04 by the adapter stage. The model is `tacticalapi_codec.TypedBlock` (pydantic,
extra keys forbidden, strict types, `null` refused); the block is dumped with `exclude_unset`, so
a key is present if and only if the twin states it.

`Entity.attributes["tacticalapi"]`, contract `tacticalapi-blueforce/1`:

| Key | Holds |
|---|---|
| `contract` | `"tacticalapi-blueforce/1"` |
| `message.type` | the type name, `rheinmetall.tactical_api.v0.GetBlueForcesResponse` or `...SubscribeBlueForceEventsResponse` |
| `message.type_url` | the `type_url` (dict form: `@type`) as stated, prefix included |
| `message.list` | `"blue_forces"` or `"updated_blue_forces"`: the repeated field that held the element |
| `message.index` | the element's 0-based index in that list |
| `message.header` | the `ResponseHeader`'s known fields as stated: `success` (always `true` here), `error_message` when on the wire |
| `blue_force` | the element's known fields as the twin states them, at the twin's own paths, nested messages as objects: `identity`, `last_contact_time`, `callsign`, `symbol` (`symbol_catalog`, `string_identifier`, `numeric_identifier.first_ten_digits` / `.second_ten_digits`), `blue_force_type` (`is_vehicle`, `is_unmanned`, `is_leader`), `own_blue_force`, `point_location` (`name`, `location_time`, `geo_point` (`latitude_coordinate`, `longitude_coordinate`, `vertical_distance`, `vertical_distance_reference_code`, `measurement_code`), `course`, `speed`), `mount_host`, `associated_organization_unit_identity`, `is_deleted` |

One block model per message (`IdentityBlock`, `SymbolBlock`, `NumericIdentifierBlock`,
`BlueForceTypeBlock`, `PointBlock`, `GeoPointBlock`, `BlueForceBlock`, `HeaderBlock`), each with
exactly the field table's fields of that message; a test holds the two equal. Unknown fields
(dict-form keys the contract does not name, `@unknown`) are never in the block.

Every key is a bare name of the ledger grammar in `pkg/lossless.py`, so a twin leaf
`blue_forces[i].<path>` is bound by `MAPPINGS` to `entity:attributes.tacticalapi.blue_force.<path>`
(rule `identity`), `@type` to `...message.type_url` and `header.<field>` to
`...message.header.<field>`. Source keys use `[_]`: an element's Entity is found by kind
(`entity:`), because the output interleaves an Entity and an Event per element and the
index-bound target `#[*]` would name the wrong object. Three leaves are also held to the
canonical field they always project to: the two coordinates (`entity:position.lat` / `.lon`,
rule `number`, and `event:geometry.coordinates[1]` / `[0]`) and `point_location.speed`
(`entity:kinematics.speed_mps`, `number`). A fourth, `point_location.course`, is held to
`entity:kinematics.course_deg` since 2026-10-06 (R5), beside the typed block: a course outside
[0, 360) is not mapped (§5.6), so the row uses `absent_if`, the one rule whose expected outcome
can be absence, with the sentinel 360 (the full turn, which some sources write for north) and
`number` for every other value. The grammar takes one sentinel per rule and no range, so a
negative course, or one past 360, is translated as §5.6 says and the ledger reports its leaf
LOST all the same: a reading of the grammar, recorded here, not a loss (a test says so, as for
item 23 below). No shipped fixture holds one; `awkward_zeros` holds a course of 360.
`point_location.location_time` was held to its projection as well (`entity:valid_from` and
`event:observed_at`, rule `instant`) until 2026-10-04 (final verification, item 16): a zero
Timestamp is now passed over (§5.3), so the projection holds only for a text that is not the zero
one, and the ledger grammar has no rule that is skipped for one source value and applied to the
rest (`absent_if` asks the destination to be absent, and `valid_from` never is). It is held to
the typed block only, as `last_contact_time` always was; the tests and the goldens hold the
projection.

The other top-level keys of `Entity.attributes`: `entity_id_basis`, `valid_from_basis`,
`affiliation_basis`, `entity_type_basis`, `symbol_basis`, `position_basis` (always),
`position_source_basis` (only when a `Position` is emitted), and `course_basis` (only when the
element states `point_location.course`, mapped or not; added 2026-10-06, R5). `Event.payload`: `contract`,
`observed_at_basis`, `event_id_basis`, `severity_basis`.

`Entity.residual` (namespace `TacticalAPI`; on every Entity since 2026-10-06, `None` until then
when the Entity carried no unknown field):

| Key | Holds |
|---|---|
| `data.response` | the response reduced to what the contract does not name, at the twin's own paths: its dict-form unknown keys with their values, its `@unknown` list, and `header` reduced the same way. Absent when empty |
| `data.blue_force` | the element reduced the same way, at its own relative paths (`point_location.geo_point.@unknown`, ...). Absent when empty |
| `data.unknown` | every unknown field this Entity carries, as `tacticalapi_codec.unknown_fields` gives it (`{"path", "number", "wire_type", "hex"}` or `{"path", "key", "value"}`, `path` the twin path of the message that held it): the message- and header-level ones first, then the element's, each in twin order. Always present, `[]` when the Entity carries none (since 2026-10-06) |

`MAPPINGS` binds `blue_forces[_]` / `updated_blue_forces[_]` (after every known leaf) to
`entity:residual.data.blue_force` and the empty key (last) to `entity:residual.data.response`,
both as residual subtrees. `Event.residual` (namespace `TacticalAPI`, since 2026-10-06; `None`
until then): `data.response` as on its Entity, absent when empty, and `data.unknown`, the
message- and header-level entries of its Entity's `data.unknown`, `[]` when there are none. The
event's payload holds nothing that is not in the entity's typed block; `MAPPINGS` binds no leaf
to the Event's residual, since every leaf it holds is bound on its Entity.

The ledger grammar cannot condition a mapping on the message type (`@type`): `MAPPINGS` binds
both list names for every message. So a dict-form `GetBlueForcesResponse` twin holding the key
`updated_blue_forces` (the other response's list name, which this message's contract does not
name) is translated correctly — the key is an unknown field, carried at
`residual.data.response.updated_blue_forces` and listed in `residual.data.unknown` — and the
ledger still looks for its leaves in a typed block and reports them lost. That is a reading of
the grammar, recorded here, not a loss; the adapter's behaviour does not change for it (stated
2026-10-04, final verification, item 23).

## The maintainer's rulings (2026-10-06)

The maintainer ruled on every row on 2026-10-06; until then each held a default the out-of-tree
project had taken or stood unresolved. R3, R5 and R7 changed a default, and R8 settled an open question in a
way that changed what the project records; R1, R2, R4 and R6 confirmed what was built; R9 and
R10 settled questions the project could not settle itself and changed no rule of the adapter.
"Changes", item 40, below, lists what moved for each.

| # | Question | Ruling | Ruled |
|---|---|---|---|
| R1 | Scope | Kept as built: the BlueForceTracking read side only, ingest only, maturity L3 declared. The scope may be widened later, as a separate arc | ruled 2026-10-06 |
| R2 | Unit of ingest and binding claim | Confirmed: one response wrapped in `google.protobuf.Any`; `standard-encoding` with the `capture-envelope` limitation and the claim `VERIFIED`, which the host's ruling (B) of 2026-09-20 pairs with that binding and the in-tree manifest gate requires (§6). The other choice, the provisional binding with the `PROVISIONAL` claim, is not taken | confirmed 2026-10-06 |
| R3 | Affiliation | Changed: `Entity.affiliation` is `UNKNOWN` for every blue force, with an `affiliation_basis` saying that the message carries no affiliation field, that the service's own definition names its members blue forces, and that the adapter asserts no affiliation from deployment context (the `stanag4586` precedent). A caller that knows better passes one of the four `Affiliation` members to the constructor, `TacticalapiAdapter(affiliation=...)` (the `c2sim` precedent of caller context, its `own_side`), and every Entity gets it with a basis saying the caller supplied it; anything else is refused at construction (`invalid-affiliation`). `fixture_instance` is not overridden, so the packaged fixtures replay with no caller affiliation and the goldens hold `UNKNOWN`. The default was `FRIENDLY` (§5.4) | changed 2026-10-06 |
| R4 | Symbol | Confirmed as built: `Entity.symbol` only from a MIL-STD-2525D numeric code; every other symbol is carried, not converted, and no symbol is derived | confirmed 2026-10-06 |
| R5 | Course | Changed: `point_location.course` maps to `Kinematics.course_deg` as degrees true when it is a number in [0, 360) (a NaN or an infinity never reaches the rule: the codec refuses both, `non-finite-number`); the contract states degrees and no north reference, so the basis on every mapped value says the north reference is assumed true. A course outside that range, 360 included, is not mapped and not normalised, stays in the typed block and is named by `validate_source`. The default was to carry the course only (§5.6) | changed 2026-10-06 |
| R6 | Deleted entries | Confirmed as built: `Entity.status` and a `STATUS_CHANGE` event; no `valid_to` | confirmed 2026-10-06 |
| R7 | `license_class` | Changed: `OPEN`. In the host's classes (ARCHITECTURE.md §3.2, a statement about the source standard's terms) OPEN is a source standard publicly available under terms permitting free implementation; the upstream files are public, under the Eclipse Public License 2.0 (R8), and R10 rules out `CONTROLLED`. The default was `LICENSED`, a placeholder whose host definition (a standard obtained for a fee or under a signed agreement) does not describe the upstream's terms | changed 2026-10-06 |
| R8 | Licence of the embedded field table | Ruled: the Eclipse Public License 2.0, as the upstream repository's licence file states; the alternative the file headers offer, a BSD three-clause licence, is not taken. Recorded in the fixture set's `spec/tacticalapi_pin.json` and under "Licence of the embedded field table" below | ruled 2026-10-06 |
| R9 | Use of the interface name | Ruled: the name "tacticalapi" / "TacticalAPI" is kept and no written consent is sought; the maintainer accepts the risk named by the upstream README's reservation of the publisher's names pending its written consent. §8, question 7, is ruled, not asked | ruled 2026-10-06 |
| R10 | Export control | Ruled unaffected: the adapter holds field names, numbers and enum values of a publicly published interface, no upstream software and no interface definition text, and is therefore not a controlled item; nothing is classified. The upstream's note that export-control law may apply to using the files names no regime or classification; it stays recorded, with the ruling beside it in the fixture set's `spec/tacticalapi_pin.json` (the pinned files' own record, `proto_pin.json`, is read-only and keeps the note alone). §8, question 8, is ruled, not asked | ruled 2026-10-06 |

## Licence of the embedded field table

The field table in `pkg/adapters/tacticalapi_codec.py` is derived from the interface definition
files of github.com/Rheinmetall/tacticalapi at commit `58661c9`. The maintainer ruled
on 2026-10-06 that the Eclipse Public License 2.0 (EPL-2.0) governs those files (R8). The table
carries field names, field numbers and enum values only, and no text of the files. The rest of
the adapter is under this repository's licence, Apache-2.0. Both copies of `NOTICE` state the
derivation (added 2026-10-06, at the landing), `tests/test_cdm_packaging.py` holds both to the
statement, and the wheel gate (`gates/wheel_install.py`, its `licences` check) holds the built
wheel's copy to it.

## Open items

For the maintainer; each is outside what the adapter may change or decide (each is the host
package's), and this file says where each was found. Moved here from the out-of-tree project's
README on 2026-10-06.

- Resolved in synapse-cdm 3.2.0 (noted 2026-10-06; MIGRATIONS.md 3.2.0, "DIS 7 UNIT 1B" and the
  bump ruling for `times.py:render`): up to 3.1.1, `synapse_cdm.times.render` wrote the year
  with `strftime('%Y')`, which glibc under CPython 3.11 and 3.12 leaves unpadded below the year
  1000, so `valid_from` and `observed_at` of such an instant would fail the CDM schema there.
  Since 3.2.0 `render` writes four digits itself on every platform. The adapter's event ids have
  not depended on it since 2026-10-04 (§5.8); no id, golden or test moved.
- `synapse_cdm.adapter.container_depth` walks a `dict` that contains itself without end, so
  `to_cdm` does not return for one; the codec's own walk now stops past the bound (the opening paragraph). (Noted 2026-10-06: synapse-cdm 3.2.0 records this as a known SDK defect,
  not fixed, in its MIGRATIONS.md section and release notes; its `dis7` adapter guards its own
  input against cycles before the host measures it, as this codec does. The items below are not
  recorded there.)
- `synapse_cdm.adapter.wire_size` raises `UnicodeEncodeError` for a `str` input holding a lone
  surrogate, before any adapter can refuse it (the opening paragraph).
- `synapse_cdm.adapter.wire_size` and `container_depth` test types with `isinstance`, which asks
  an object's `__class__`, and then call the methods of what they took for octets, text, a
  `dict` or a `list`. An in-process object whose `__class__` claims one of those types, or
  (inside a `dict`) raises, therefore raises there, before any adapter can refuse it; the codec
  reads each value's own type (the opening paragraph and "Changes", final verification,
  item 37).
- `validate_source` writes a refusal's text whole. An in-process object that raises
  `TacticalapiRefused`, `InputTooLarge` or `InputTooDeep` itself can therefore put a text of any
  length, on several lines, into its one entry ("Changes", item 38). Left as it is:
  bounding it is a small change, and it was found after the last fix round.
- No test raises a plain `ValueError` on the path of `validate_source` that handles an exception
  which is not a refusal; the code is right and the gap is recorded (item 38).
- A released `memoryview` leaves `decode`, `twin_of`, `to_cdm` and `detect` with Python's own
  `ValueError` and no reason code (item 38). The codec's entry check could refuse it
  `not-an-any-envelope`; the same error in the host's `wire_size` is the host package's.

## Changes

**2026-10-04, decoder stage.** Each of these was found while implementing §2.2 and §3 as written.

1. **`unknown-field-in-well-known-type` (new code; §3.2, §3.3).** §3.3 carries an unknown field
   "at any level" and §2.2 places it under `@unknown` on the message that held it, but the twin
   renders `Any` (merged into the top level), `Timestamp`, `StringValue` and `DoubleValue` (bare
   values) without an object of their own, so the two rules cannot both hold for those four.
   Carrying the field elsewhere would give `@unknown` a second entry shape. These types are frozen
   upstream; a field they do not define is a malformed encoding, so it is refused.
2. **`invalid-twin-value` (new code; §2.2, §3.2).** §3.2 had no code for a dict-form value of the
   wrong JSON type or spelling (an `int64` given as a number, an offset in a `Timestamp`, a
   malformed `@unknown` entry). The dict form is held to §2.2 exactly; the two normalisations it
   does apply are now stated in §2.2.
3. **`value-out-of-range` (new code; §3.2).** An `int32` or enum varint outside the 32-bit range
   and a `bool` other than 0 or 1 had no code. A lenient parser truncates the first and reads the
   second as true; both are repairs, so both are refused. The dict form uses the same code for an
   `int32`, enum or `int64` outside its range.
4. **`field-number-too-large` (new code; §3.2).** A tag naming a field number past 2^29 − 1 is not
   a valid tag (protoc's own parser rejects it); it had no code and would otherwise have been
   carried as an unknown field with a number no contract can define.
5. **`too-many-unknown-fields` (new code and limit; §3.2, §3.3, §6).** Without a count, 4 MiB of
   two-byte unknown fields would become two million carried entries. The cap is per input, both
   forms, 65 536, chosen to admit six new upstream fields on each of `max_objects` elements.
6. **Clarified conditions (§3.2).** `varint-too-long` also covers a tenth byte setting bits past
   the 64th (a lenient parser drops them); `length-exceeds-input` also covers a fixed-width field
   and is bounded by the enclosing message, not the buffer; `nesting-too-deep` counts containers
   of the twin as the base class counts a parsed twin, so the bytes form and the dict form of one
   message have one depth. With that count the bytes form cannot exceed 7 (the closure has no
   recursive message and unknown fields are carried as octets), so the declared `max_depth` is
   reachable only through the dict form; the bytes-form guard is tested at a lowered bound.
7. **`hex` and key order (§2.2).** "The field's raw value bytes" is stated per wire type, and the
   twin's key order is stated, so the two forms of one message serialise identically.

**2026-10-04, fixture stage.**

1. **`independent/` holds two readings per payload, and none for a payload protoc cannot read
   (§7).** "`protoc`'s decode of each written payload" cannot hold as written. protoc's text
   printer does not expand an `Any`: `--decode=google.protobuf.Any` prints the `type_url` and
   the value as escaped octets, not the response. So each reading is two files, the envelope
   (whose two fields the tests hold to every octet of the payload) and the value decoded as the
   type the `type_url` names. And protoc refuses to read some of the refusal payloads
   (`length_past_end` at all, `truncated_varint` past the envelope), so those have no reading or
   only the envelope's; `spec/tacticalapi_pin.json` records protoc's verdict on each `malformed/`
   payload instead, and the tests assert it.

**2026-10-04, adapter stage.**

1. **Where an unknown field sits in the residual (§3.3, §5.9).** `residual.data.unknown` still
   lists every unknown field with the path of the message that held it, but a flat list cannot be
   the ledger's destination: a field's index in it depends on how many fields the other levels
   carry, and the ledger grammar binds a source index to a destination index or to nothing. So
   the unknown fields also sit at their own relative paths under `residual.data.response`
   (message and header level) and `residual.data.blue_force` (the element's), which `MAPPINGS`
   binds as residual subtrees; the layout is under "Typed block layout (as built)". §4's rule
   is read as written: message- and header-level fields on every Entity, an element's own on
   that element's Entity only. Events carry no residual.
2. **`too-many-unknown-fields` counts the carried copies (§3.2, §3.3, §6).** §4 carries a
   message- or header-level unknown field on every Entity, so the per-input count alone admits
   65 536 header-level fields beside 10 000 elements: a payload of some 200 KiB would become
   655 million carried entries, the multiplication §3.3's count exists to prevent. The adapter
   counts each such field once per Entity that carries it, adds the element-level ones, and
   refuses past `MAX_UNKNOWN_FIELDS` with the same code before any object is built. One element
   carrying 65 536 is still admitted.
3. **Past the declared size or depth, the base class refuses first ("Refused", §3.2).**
   `synapse_cdm.adapter` wraps every `to_cdm` at class definition: a bytes input past
   `max_input_bytes` raises `InputTooLarge` and a dict past `max_depth` raises `InputTooDeep`,
   both `ValueError` subclasses whose messages name the two numbers but do not begin with a
   reason code. A subclass cannot opt out of the wrapper and should not, so at the adapter's
   surface those two refusals are the base class's; `input-too-large` and `nesting-too-deep`
   stand behind them for a direct codec call. The same wrapper reads a bytes input whose first
   non-whitespace character is `{` or `[` as JSON text for depth; an `Any` whose `type_url` is
   91 or 123 octets long begins that way, so such a payload whose prefix and later octets open
   more than 64 brackets is refused `InputTooDeep` although the decoder reads it (§2.1 says the
   prefix is not otherwise checked). A test records it; the property is the host package's.
4. **Kinematics with a course and no speed (§5.6).** Course has no CDM home here, so
   `kinematics` is emitted if and only if `speed` is present; a point that states only a course
   has `kinematics` `None` and the course in the typed block. [Replaced 2026-10-06 by item 40
   (R5): a course in [0, 360) is mapped, and `kinematics` exists when the speed or a mapped
   course is present.]
5. **Which bases are always written (§5.4, §5.5).** `entity_type_basis` and `position_basis` are
   written on every Entity (stating which row applied), not only on the rows that name them;
   `position_source_basis` only when a `Position` is emitted, since without one there is no
   `position_source` to explain.

**2026-10-04, final verification.** The build pipeline's reviewers left minor findings open; the
orchestrator ruled on each, and these are the rules that changed or were stated. Each was
checked against the code and holds it.

1. **A tag in more than five bytes is `varint-too-long` (§3.2).** A tag is a 32-bit value, so its
   varint is at most five bytes; the decoder read a tag padded to six to ten bytes, which protoc
   refuses and a lenient parser reads. It was the one input class on which the decoder accepted
   what protoc refuses, and "Changes", decoder stage, item 4 refuses an over-wide field number by
   that same measure. The length is checked before the field number; a five-byte padded tag is
   still read. The `non-canonical-encoding-refused` limitation names it.
2. **A refusal is one printable line of bounded length (§3.2).** A dict key entered the refusal
   text raw, so a key holding a lone surrogate made a refusal that could not be written as UTF-8
   and a key holding a line break forged a second line; a 4 MiB `type_url` was quoted twice, an
   8 MiB refusal, and a megabyte given for a `bool` a megabyte-long one. Every value a refusal
   takes from the input now goes through one helper (`quote`: the repr, cut to 120 characters,
   saying how many were left out), in the adapter as in the codec, and a key through one other
   (a field name of the table or `@unknown` as itself, anything else quoted); the `type_url` is
   quoted once. Found on the way: a dict-form integer of more decimal digits than Python writes
   as text (`sys.get_int_max_str_digits()`) made the refusal itself raise a plain `ValueError`;
   `quote` describes such a value instead of writing it.
3. **The bytes readers take octets only (§3.2, `not-an-any-envelope`).** `decode`,
   `envelope_type_url` and `decode_message` read whatever they were given: a `str` or `None`
   raised a `TypeError` that is not a refusal, a list of small integers was read as octets, and
   `decode_message` read a `memoryview` in place, so it measured a wide-item view in items, not
   octets, and failed with `AttributeError` on its first string field (a defect, now fixed). The
   three share one entry check: `bytes`, `bytearray` or `memoryview`, measured in octets, copied
   to `bytes`; anything else is refused as `twin_of` refuses it.
4. **Dict form: no rounded double, and plain values (§2.2).** "A `double` given as a JSON integer
   becomes a float" let 2^53 + 1 become 2^53 without a word, which is a repair; such an integer is
   now refused (`invalid-twin-value`). An `int`, `str` or `float` subclass (an `IntEnum` member,
   say) was returned as given, so the twin was not made of plain JSON values for such a caller;
   every accepted value is now converted to its plain type before it is checked, and a `bool`
   stays excluded where an integer or a double is due.
5. **`carried-copies-too-large` and `MAX_CARRIED_COPY_CHARS` (new code and limit; §3.2, §4,
   §6).** §4 carries the message's own data (the typed block's `message` member, the message-
   and header-level unknown fields twice over) on every Entity, and only the count of carried
   unknown fields was bounded: a 4 MiB `error_message` on 10 000 elements serialises to some
   40 GiB. The data is measured once, by the measure §4 states, and refused when its size times
   the number of elements passes 16 Mi, after the `too-many-unknown-fields` count and before any
   object is built, in both forms. Its basis is in §6, it is declared in the `max_objects` limit
   basis beside `MAX_UNKNOWN_FIELDS`, and the `resource-limits` limitation names it. The measure
   walks with a stack. [Replaced by item 14: the measure is the characters of the carried data's
   compact JSON text, written once per measured value, and walks nothing of its own.]
6. **Every Entity owns its containers (§5.9).** All the Entities of one message shared the
   message-level residual containers, and an unknown key's value was one object at its path and
   in `residual.data.unknown`, so changing one place changed others. Each Entity now holds its own
   copy of every container it carries; strings are still shared. Serialised output is unchanged.
7. **The host's depth guard, made precise (§2.1, the opening paragraph).** "Changes", adapter
   stage, item 3 was checked and holds: `enforce_depth_bound` decodes a bytes input and reads it
   as JSON text when its first character after white space is `[` or `{`, which an `Any` whose
   `type_url` is 91 or 123 octets long is (its second octet is that length). "Open more than 64
   brackets" means nest them, as JSON text is read: a bracket closed before the next opens does
   not count, and a quote octet starts a string in which brackets are not counted. Only those two
   lengths matter for a payload the decoder reads, since a supported `type_url` is at least 50
   octets and no other single-octet length between 50 and 127 is a bracket or white space. The
   adapter stage's test covers 123; a test for 91, where the prefix alone cannot reach the bound
   and a callsign's brackets do, is added. The opening paragraph's "max_depth (dict)" now names
   these bytes inputs too. [Corrected by item 19: the sentence "Only those two lengths matter"
   is false. Multi-octet lengths whose varint decodes to white space and then a bracket are read
   as JSON too; §2.1 now states the rule and lists them.]
8. **One `event_id` for one report (§5.8, stated).** Two elements of one message with the same
   identity and the same rendered instant get the same `event_id`. That follows from §5.8's
   formula and is kept: the identifier names one report of one blue force at one instant, and the
   adapter does not disambiguate or merge (§4).
9. **`non-finite-number` in the dict form (§3.2, wording).** The row said "anywhere in the twin";
   the code refuses NaN or an infinity with that code only in a `double` and in the value of a key
   the contract does not name, and as `invalid-twin-value` for any other known field or inside an
   `@unknown` entry, where it is a value of the wrong JSON type. The row now says what the code
   does; a test records it.
10. **The field-table tool holds the closure to proto3 (§3.1).** The tool never read a file's
    syntax, a field's label `required` or its default value, so a later pin that kept the names
    and moved a file to proto2 or an edition would have printed a table the decoder reads under
    proto3's rules. It now stops on each; the current pin's closure is proto3 throughout and the
    table is unchanged.

A second review of the final tree (three reviewers: robustness, mapping, licence) left the
findings below; the orchestrator ruled on each, and these are the rules that changed or were
stated, each checked against the code and the tests.

11. **`error-message-without-carrier` (new code; §4).** A successful response with no blue force
    whose header stated an error_message returned `[]`, so the text was neither carried nor
    refused, while the same text under a header key the contract does not name was refused
    `unknown-fields-without-carrier`. The text is now refused by name for the same reason: no
    object exists to carry it. Order: success, unknown fields, then the error message. An
    error_message present and empty holds no text and still gives `[]`. A `cases/` fixture holds
    the payload.
12. **A nested `@type` is placed, not only listed (§2.2).** `unknown_only` left out a dict-form
    key `@type` at every level, so below the response it was listed in `residual.data.unknown`
    and absent from its own path, and the ledger reported it lost. It is left out on the
    response alone now.
13. **Plain values by the base type's own conversion (§2.2).** `str()` of a `(str, Enum)` member
    is `Class.MEMBER`, so such a member given for a string field, an enum name, `@type`, a
    Timestamp or an unknown key was replaced by its class-qualified name. `str.__str__`,
    `int.__int__` and `float.__float__` take the instance's own content. Two keys of one object
    that become one text are refused rather than one dropped.
14. **The carried-copy measure is the JSON text, and long integers are refused (§2.2, §3.2, §4,
    §6).** "One for every number" let a twin read from 3.6 million characters of JSON text be
    measured inside the bound and serialise to some 64 billion; a 5 000-digit integer under an
    unknown key was accepted and the Entity carrying it could then be neither written by
    `json.dumps` nor read back. An integer anywhere in an unknown key's value outside
    −2^63 … 2^64 − 1 is refused `invalid-twin-value`; the measure is the characters of the
    carried data's compact JSON text with ASCII escaping, each copy an Entity holds counted,
    each Entity's index with its own digits. The bound, the constant's name and the place of
    the check are unchanged. `json` is imported under `src/` to write that text; the host's
    parser-safety gate (`tests/test_cdm_parser_safety.py`) concerns `json.loads` and `json.load`
    only, and the boundary gate (`tests/test_cdm_boundary.py`) forbids no part of `json`. A
    third gate, the parser-safety audit (`tests/test_cdm_security_policy.py`), searches the text
    of every adapter module, docstrings included, for six parser names and wants an audit-table
    row for each module that holds one; this item's docstring named one of them, and item 32
    took it out.
15. **A deleted element's event id ends `#is_deleted` (§5.8).** See §5.8. In the goldens, only
    the event id of the deleted element of `delta_with_deletion` and its `event_id_basis`
    changed: the basis names the input, so it names the suffix.
16. **A zero Timestamp is not a source time (§5.3, §6, "Typed block layout (as built)").** A
    present Timestamp holding seconds 0 and nanos 0 became `valid_from` 1970-01-01, which the
    CDM forbids for an unknown time and the suite's check J fails, and it took precedence over a
    real `last_contact_time`. It is passed over now, in both forms, as §5.5 passes over a
    coordinate pair that is not on the wire; `0001-01-01T00:00:00Z` stays a source time and is
    reported. `awkward_zeros` gained a second blue force with such a location time; its golden
    gained that element's two objects. The ledger no longer holds `location_time` to
    `valid_from` (see the layout section).
17. **The event id's instant is the adapter's own text (§5.8).** `times.render` pads the year
    through `strftime`, which glibc on Python 3.11 does not do below 1000, so the id of such an
    instant differed by platform. The adapter writes the instant itself; no id moved.
18. **`claim_status` is `VERIFIED` (§6).** See §6. The test that asserted `IMPLEMENTED` asserts
    `VERIFIED`: a rule changed, not an assertion loosened.
19. **§2.1's lengths read as JSON (§2.1; corrects item 7).** Brute force over every length the
    declared bound admits, with the host's own leading-character test, gives six lengths read as
    JSON whatever the `type_url` holds and twenty more when it begins with a bracket. A test at
    1 491 650 is added.
20. **Any value whose repr raises is described (§3.2, the opening paragraph).** `quote` caught
    only `ValueError`, so an in-process value whose `__repr__` raised something else escaped a
    refusal as that exception. The opening paragraph now states that the host measures a `str`
    input first and that one holding a lone surrogate raises `UnicodeEncodeError` there.
21. **The codec's depth walk stops past the bound (§3.2, §6, the opening paragraph).** A dict
    that contains itself made `validate_twin` walk forever. It is refused `nesting-too-deep`
    now; the same walk in the host's `container_depth`, on the `to_cdm` path, is the host's and
    is recorded. The cost of shared sub-lists is stated in §6.
22. **Each object owns its provenance stamp (§5.9).** An Entity and its Event held one
    `SourceRef`, and every stamp of a message one `transformations` list. Each now has its own;
    serialised output is unchanged.
23. **The other response's list name (the layout section).** Recorded as a reading of the
    ledger grammar; the adapter already carries the key correctly and a test now says so.
24. **`validate_source` lines are bounded (§6).** An unknown key was written whole with `!r`;
    it now goes through `quote`.
25. **`symbol_basis` for a 2525D symbol with no identifier (§5.4).** It said "in the string
    form" for a symbol that holds no string.
26. **The 15-character note under two catalogs only (§6).** The contract states the length for
    `SYMBOL_CATALOG_APP6_B` and `SYMBOL_CATALOG_MIL2525_C` only, and `validate_source` reported
    it for every catalog; the vendor catalog's 22-character string in
    `awkward_symbols_and_codes` is no longer reported.
27. **Identity values are kept verbatim (§5.2, stated).** Nothing held it; a test with an
    upper-case `uuid_identity` now does.
28. **`source.record_index` and `Event.source_ids` (§5.8, stated).**
29. **Fixture provenance stated exactly; one harness fixture carries unknown fields (§7).** §7 and
    the `no-endpoint-exercised` limitation said every fixture was written by protoc; they now
    use the wording of `fixtures/tacticalapi/README.md`. No harness fixture carried an unknown
    field, so the harness's lossless column, check D and the goldens never met a residual
    binding; `snapshot_with_unknown_fields` (the content of `cases/unknown_field_carried`) is
    added, and the harness reports ten fixtures. The `cases/` copy stays.
30. **The measurement-code row worded afresh (§5.5).** Its "Why" cell repeated a run of the
    contract's comment on that value; it is now in this project's own words, as is the code
    comment beside the table.
31. **Export control is an open question (§8).** The pin record notes the upstream's warning
    that export-control law may apply to using the files, and neither this file nor README.md
    said so. §8 gains the question and README.md the ruling R10 (unresolved; nothing is
    published until it is ruled), and R7 now says `LICENSED` is a placeholder whose host
    definition does not describe the upstream's terms. No rule of the adapter changed.
    [Ruled 2026-10-06, item 40 (R10): the adapter is no controlled item and nothing is
    classified; R7 is `OPEN`.]

The second review's remaining findings changed no rule of this file: they added tests the
adapter already passed (an unsuccessful response with no blue force, a nanosecond part that
truncates, the catalogs other than 2525D, a short second symbol set, a negative height), and
local replicas of the host's promotion gates, the lint stage and the prose check, which
README.md, `check.sh` and `tests/test_promotion_gates.py` record.

A third review of the fixed tree (the same three reviewers) left nine findings; the orchestrator
ruled on each, and these are the rules that changed or were stated, each checked against the
code and the tests.

32. **No parser name in the adapter modules' text (item 14).** Item 14's docstring in
    `tacticalapi_codec.py` named the JSON reader's function, and the host's parser-safety audit
    gate (in `tests/test_cdm_security_policy.py`, the test that holds the audit table to its
    grep) searches each adapter module's text for six parser names: in-tree it would have
    asked for an audit-table row for a module that calls no parser. The docstring is
    reworded, and `tests/test_promotion_gates.py` holds a replica of the gate over `src/`. No
    rule of the adapter changed.
33. **A Timestamp less than a millisecond after the epoch (§5.3, §6, stated).** Item 16 passes
    over seconds 0 and nanos 0 only. Seconds 0 with nanos 1 … 999 999 is a value proto3 writes
    only when it was set, so it stays the source time, ahead of a real `last_contact_time` when
    it is the location time; passing it over would infer that a stated value is unset. Its CDM
    text is `1970-01-01T00:00:00.000Z`, the text the CDM forbids for an unknown time, so the
    host's check J reports it, and nothing in the output tells the two apart; `validate_source`
    names each such Timestamp in one line instead. No shipped fixture holds one.
34. **Type names in refusals are bounded too (§3.2).** "One printable line of bounded length,
    whatever the input held" had two holes, both open to an in-process caller only: `quote`
    returned the repr as `repr` gave it, so a `__repr__` returning a `str` subclass could format
    itself as two lines of five thousand characters, and eleven refusals of the codec and every
    `validate_source` line for a refusal wrote a type's name raw, so a class named with a line
    break or a hundred thousand characters made a refusal of two lines or of that length. The
    repr is taken as plain text, and every type name goes through `quote_type`.
35. **`detect` finds `@type` as `to_cdm` does (§6).** Item 13 made `validate_twin` read keys by
    their text, so a dict whose `@type` key is a `str` subclass hashing otherwise than its text
    was translated, while `detect` looked the key up with `raw.get("@type")`, missed it and
    answered false. Both now read the type through one function, `twin_type_url`. A dict with
    two keys holding `@type`, which `to_cdm` refuses, now answers false too.
36. **Two figures of §6 worded as measured (§6, wording).** The `MAX_CARRIED_COPY_CHARS` basis
    said 10 000 ordinary elements use "between an eighth and a seventh" of the bound; a
    snapshot's use 0.121 of it, under an eighth, and a stream update's 0.139. It now says about
    an eighth (a snapshot) to just under a seventh (a stream update), here and in the codec's
    comment. The cost of shared sub-lists gave one run's seconds and mebibytes as if exact;
    a reviewer's run took about half, so it is worded to the order of magnitude, as measured
    on one machine. Item 5 points to item 14, which replaced its measure. No rule changed.

The third review's other findings changed no rule of this file: tests the adapter already
passed (the string-length note under the catalogs the earlier test left out, and the
0001-01-01T00:00:00Z line held to that one instant), the comment-literal fingerprints taken
for every distinctive run of a comment-only literal's parts as well, so that a shortened copy
is found (README.md hard rule 2), a test that reads `check.sh` and holds its `repos` stage to
the prose and cache checks, and a promotion note on the provenance-directory test.

A fourth review of the fixed tree (the robustness re-checker, with the earlier rulings binding)
left two findings; these are the rules that changed or were stated, each checked against the
code and the tests.

37. **A type is read from the value, not from its `__class__` (§3.2, §6, the opening
    paragraph).** An in-process object whose `__class__` is a property naming `str` passed the
    codec's `isinstance` test, and `str.__str__` then raised a `TypeError`: `to_cdm` left with
    it, `validate_source` wrote its text, which holds the class name raw, as an entry of two
    lines, and since item 35 `detect` raised for such an object as a key, where it answered true
    before. A claimed `int`, `float`, container or octets also left as an exception that is not
    a refusal, a claimed `bool` was returned as given (read as not true where `success` is due,
    or failing later in the typed block's validation, six lines of text, or in the JSON writer),
    and a `__class__` that raises made `isinstance` raise it. Every type test
    of the codec's readers (the octet entry, the depth walk, the dict form) and of `detect` reads
    `type(value)` now, which no object can redefine; for every other value the two tests agree.
    Where the host's measure meets such an object first (a claimed container, octets or text),
    the error is the host's, stated in the opening paragraph and in README.md "Open items";
    `validate_source` writes a refusal's text as before and the text of any other exception
    through `quote_error`.

The fourth review's other finding changed no rule of this file: tests that hold every place
that writes a type name (with a class named with a line break and one of 100 000 characters,
each also claiming the type its place tests for), the two type names `quote`'s descriptions
write, and the words of the `validate_source` line for a time less than a millisecond after the
epoch.

**2026-10-05, after the final verification.** The last re-check passed and left three minor
notes. All three need an in-process caller; octets and JSON text cannot build any of them. No
rule, code or test changed for them; they are recorded here and in README.md "Open items".

38. **What the last re-check left open (the opening paragraph, §3.2, §6).**
    - *A forged refusal.* `validate_source` writes the text of `TacticalapiRefused`,
      `InputTooLarge` and `InputTooDeep` whole, because the codec and the host bound it where
      they make it. An in-process object whose own method or `__class__` property raises one of
      those three classes can put any text there, of any length and on several lines. The
      opening paragraph and §6 said every such exception became one bounded line; both now
      state the exception.
    - *A test gap.* No test raises a plain `ValueError` on the path of `validate_source` that
      handles an exception which is not a refusal, so a change that treated every `ValueError`
      as a refusal would pass the tests. The code is right: such an error is written through
      `quote_error` as one bounded line.
    - *A released `memoryview`.* It is of an octets type, so the entry check admits it, and
      reading its size then raises Python's own `ValueError`. `decode` and `twin_of` leave with
      that error, which has no reason code; `detect` raises it where it should answer; `to_cdm`
      leaves with the same error from the host's `wire_size`. §3.2's `not-an-any-envelope` does
      not cover it yet.

**2026-10-06, host release synapse-cdm 3.2.0.** The main checkout moved from `c4bba1b` (3.1.1)
to `298ed9b`, tag `v3.2.0`, the DIS 7 release, published the same day on GitHub and on PyPI
(both files attested to that commit by the repository's publish workflow). Every check of this
project was re-run there unchanged: 1092 tests, lint clean, 100 fixture files 0 differ, harness
10 passed and 0 failed, suite CONFORMANT with the same loss report and ledger, pinned files and
digests fresh. Three Opus readers swept the 128-file diff and every finding was refuted or
confirmed by a second reader; what follows is what the release changes for this project. No
rule of §1–§8 and no code path moved; the pinned interface definition files are unchanged
upstream (`58661c9`, still untagged).

39. **What synapse-cdm 3.2.0 changes for this adapter (§5.8, §6, README.md).**
    - *`times.render` writes four year digits itself.* The host defect behind item 17 is fixed
      (MIGRATIONS.md 3.2.0, "DIS 7 UNIT 1B"; the platforms were glibc under CPython 3.11 and
      3.12, where item 17 named 3.11 only). §5.8 and the `_id_instant` docstring now state it
      as history; the README open item is marked resolved. The adapter keeps its own writer, so
      no id, golden or test moved.
    - *`Adapter.fixture_instance` (Adapter API 3.0.0 → 3.1.0).* A classmethod whose default is
      the construction the harness, the conformance suite and the evidence generator performed
      before; this adapter does not override it, so nothing changes. Conformance check O now
      builds the adapter in a step of its own before it feeds the oversized payload; the verdict
      here is the same PASS.
    - *The roster is twenty* (`dis7` is ordinal 21, on `main`). The README promotion notes now
      say to branch from `main` at or after `v3.2.0`, not from the DIS 7 branch, and name two
      roster sites the `dis7` landing showed that no host test finds.
    - *Recorded, not fixed, by the host:* `adapter.container_depth` on a cyclic input, which the
      README open items already list; the lone-surrogate and `__class__` items are not recorded
      there. `evidence.digest_bytes` and the two harness helpers the release adds are not used
      here.
    - *The four host gate sets this project replicates* (`NETWORKING`, `FORBIDDEN_CRYPTO`,
      `FORBIDDEN_ROOTS`, the parser-audit pattern) are unchanged at `298ed9b`; the comments in
      `tests/test_promotion_gates.py` say so.

**2026-10-06, the maintainer's rulings.** The maintainer ruled on README.md's rows R1 to R10,
which had held the project's defaults or stood unresolved since 2026-10-04. R3, R5 and R7
changed a default and R8 settled an open question in a way that changed what the project
records; R1, R2, R4 and R6 confirmed what was built; R9 and R10 settled questions the project
could not settle itself. The rulings were applied in three steps (R7 with the rulings that change
no rule, then R5, then R3), each followed by every check of `check.sh`; what follows is what
moved. The README table now holds each ruled value with its date.

40. **The rulings of 2026-10-06 (§5.4, §5.6, §6, §7, §8, the layout section; README.md).**
    - *R3, affiliation: changed.* `Entity.affiliation` is `UNKNOWN` for every blue force, no
      longer `FRIENDLY`. Its basis says that the message carries no affiliation field, that the
      service's own definition names its members blue forces, and that the adapter asserts no
      affiliation from that or from deployment context (the `stanag4586` reading). The
      constructor takes `affiliation: Affiliation | None = None`, keyword only, beside the base
      class's `clock` and `synthetic` (the `c2sim` precedent, its `own_side`): one of the four
      members is every Entity's affiliation, with a basis saying the caller supplied it, and is
      compared with nothing in the message. Anything else is refused at construction with a
      `ValueError` whose text begins `invalid-affiliation` (no `TacticalapiRefused`: that names an
      input), a text that spells a member included, since converting it would be a repair; the
      type is read with `type(value)`. `fixture_instance` is not overridden, so the harness, the
      suite and the evidence generator replay the packaged fixtures with no caller affiliation
      and the goldens hold `UNKNOWN`. The `validate_source` line on a 2525D standard-identity
      digit other than the friend digit stays, reworded as an observation against the service's
      own definition rather than against `Entity.affiliation`. No limitation of the manifest named
      an affiliation value, so none changed for R3; the ledger holds no affiliation row. Tests: the
      default and its basis in both forms; each of the four members, in both forms, on every
      translated payload, with nothing else of the output moved; nineteen refused non-members;
      a supplied affiliation beside the digit-2 symbol, uncompared; the goldens equal to what
      `fixture_instance` writes.
    - *R5, course: changed.* `point_location.course` in [0, 360), the host's range for
      `Kinematics.course_deg` (`ge=0.0, lt=360.0`), is mapped as degrees true, and a new basis
      key, `course_basis`, written whenever the element states a course, says on every mapped
      value that the north reference is ASSUMED true (§8 question 2 stays open). A course of 360,
      a negative one or one past 360 is not mapped (`course_deg` stays `None`) and not
      normalised (no modulo, no clamping); it stays in the typed block, its `course_basis` says
      why, and `validate_source` names it by its path. A NaN or an infinity never reaches the
      rule: the codec already refuses either in every double the table names, in both forms
      (`non-finite-number`, §3.2), so no second rule was added and a test holds the existing one
      for the course. Decided where the ruling left it open: `kinematics` exists when the speed
      or a mapped course is present, so a course alone is kinematics of its own (adapter stage,
      item 4, replaced) and a point stating only an unmapped course has none; -0.0 compares
      equal to 0, is in range and is mapped as stated, as a speed of -0.0 is. The limitation
      `course-reference-not-stated` keeps its id and now states the assumption on every mapped
      value instead of a reason the course is unmapped. `MAPPINGS` holds the course leaf to the
      typed block and to `entity:kinematics.course_deg` by `absent_if` (sentinel 360, else
      `number`), replacing its typed-block-only row; the grammar has no range, so a negative
      course or one past 360 reads LOST there, a reading recorded in the layout section and in
      a test. `awkward_zeros` gained a course of 360 on its second element (protoc's own bytes,
      so §7's counts are unchanged) beside the first's course 0, which is now `course_deg` 0.0;
      the goldens gained `course_deg` 247.5, 12.5 and 0.0 and the `course_basis` of each element
      stating a course. The suite's loss report moved from PRESERVED 30 and RESIDUAL 58 to 31
      and 57 (DROPPED 0), and its ledger from MAPPED 116 to 117 (RESIDUAL 12, LOST 0, 86
      declared mappings).
    - *R7, `license_class`: changed to `OPEN`* (§6). ARCHITECTURE.md §3.2 defines OPEN as a
      source standard publicly available under terms permitting free implementation; the
      upstream files are public, under the Eclipse Public License 2.0 (R8), and R10 rules out
      `CONTROLLED`. `LICENSED`, the placeholder, described a standard obtained for a fee or under
      a signed agreement. The class is declared metadata only: no fixture, golden, provenance
      record or pin carries it, and the manifest `synapse_cdm.manifests.manifest` generates from
      the class now says `OPEN` (no manifest file is kept in this project).
    - *R8, the field table's licence: ruled the Eclipse Public License 2.0*, as the upstream
      licence file states; the headers' BSD three-clause alternative is not taken. Recorded in
      `spec/tacticalapi_pin.json` (its `terms`, regenerated through the builder; its shape is
      unchanged), in README.md's new section "Licence of the embedded field table", and in a
      promotion note on the host's `NOTICE` and its licence gate. No `PROVENANCE.json` named the
      R8 ruling, so none changed.
    - *R1, R2, R4 and R6: confirmed as built.* No rule moved. The bases and limitations that
      cited "default R4" and "default R6" now cite the ruling ("R4, ruled 2026-10-06"), which
      moved the `symbol_basis` text of every symbol-less Entity in the goldens; the code
      comments on R2 and R7 likewise.
    - *R9 and R10: ruled, not asked.* The name is kept without written consent, the risk the
      upstream's reservation of its names states accepted; the adapter, holding field names,
      numbers and enum values of a public interface and no upstream software or interface
      definition text, is ruled no controlled item, and nothing is classified. Both are in the
      pin's `terms` beside what the upstream says (the export-control note is now recorded there
      too; the pinned files' own `proto_pin.json` is read-only and keeps its note alone). §8
      questions 6, 7 and 8 are marked ruled, not asked; question 2 notes R5's assumption.
    - *What did not move.* The typed block's layout (no key added to or removed from the block;
      `course_basis` sits beside `affiliation_basis` among the bases), every refusal code of an
      input (`invalid-affiliation` refuses a construction, not an input), the declared limits,
      the fixture counts, and every rule of §1 to §3. 1 092 tests became
      1 208; lint, the fixture builder's `--check` (100 files, 0 differ), the harness (10
      passed), the suite (CONFORMANT) and the repository checks pass as before.

**2026-10-06, the landing: the adapter moves into the repository.** The out-of-tree project's
modules, fixtures, tests and tools moved into this repository as the layout note at the top of
this file maps them, and this file with them. What changed beyond the paths:

1. **Every object carries a residual (§5.9).** The repository's lossless sweep
   (`tests/test_cdm_lossless.py`) holds every object a `structured` adapter makes from its
   harness fixtures to a residual with data; out of tree 44 of the 48 objects of the ten harness
   files carried `None` (every Event, and every Entity with nothing unknown). The maintainer chose
   the smallest record that is never empty: `unknown` always, `[]` when nothing is unknown, with
   `response` and `blue_force` when they hold something, and on the Event the message-level part
   of its Entity's. The Event's copies of the message-level fields now count against
   `MAX_UNKNOWN_FIELDS` and `MAX_CARRIED_COPY_CHARS` beside the Entity's (§3.2, §3.3, §4, §6), so
   one element carries a header-level field twice in the count, and the refusal texts name the
   Events as well as the Entities. The ten goldens were written again; read path by path against
   those of 2026-10-04, the residual of each object is the only value that moved (44 values,
   each `None` before), and the four Entity residuals that existed are unchanged.
2. **`evidence-not-available` is `evidence-availability` (§6).** The limitation named the
   out-of-tree project and its `check.sh`; it now states the pre-release form the repository's
   `dis7` adapter used until its release: `evidence.available` is false because no published
   Release carries the adapter's records yet. The field stays `false`.
3. **The declared `max_input_bytes` cites `tests/test_cdm_input_bounds.py`.** The repository
   holds every shipped adapter's byte bound to its one test of the refusal one octet past it;
   `max_depth` and `max_objects` cite `tests/test_cdm_tacticalapi_adapter.py`. The bases, the
   maturity basis and the codec's refusal texts name the package's paths and this file.
4. **The fixture builder and its records.** The builder puts the package's root on the path
   instead of the project's `src/`, and imports the codec from the package; the pin's `adapter`
   states the ordinal 22 instead of a status, and the builder's prose names the package's decoder
   and the moved tests. Every generated file was written again by the builder (three provenance
   records and the pin changed, the rest byte for byte as before) and `--check` reads 0 differ.
5. **The tools are gates.** The field-table generator, the comment-literal tool and the
   text-format reader are under `gates/`; the generator's header names its new path in the codec's
   generated block, which it still reproduces byte for byte. The comment-literal tool's prose
   check and the literal scan of `tests/test_cdm_tacticalapi_contract_text.py` read the adapter's
   own files (`ARC_FILES`), not the whole repository.
