"""The TacticalAPI fixture set (the record's §7), held to protoc, to its sources and to its
records. The record is `docs/tacticalapi-implementation.md`, the adapter's specification; this module came
from the adapter's out-of-tree project on 2026-10-06, when the adapter landed.

The decoder is the oracle for nothing here. Three kinds of evidence are used:

* PROTOC'S READING — `independent/<case>.any.txtpb` and `independent/<case>.value.txtpb`, protoc's
  own `--decode` of every written payload, read with `gates.protoc_text` (a reader that knows the
  text format and nothing of the contract) and turned into a twin by `reading_twin` below, one
  convention of the record §2.2 at a time. Every committed `.parsed.json` must equal it, key order
  included.
* THE SOURCE — `sources/<case>.txtpb`, the literal protoc encoded, turned into a twin the same way
  after the one rule protoc applies when it writes (`as_written`), plus the fields the builder
  states it appended by hand.
* THE FILES THEMSELVES — every SHA-256 of the pin through `synapse_cdm.evidence.digest`, every
  provenance record through `synapse_cdm.evidence.provenance_problems`, every JSON file's nesting
  through `synapse_cdm.adapter.json_nesting_depth`.

The decoder is then read twice: its twin of every payload must be the committed file byte for
byte (so the file is its output and not an edit), and every payload malformed at the wire level
must be refused with the code README.md names. Only the builder's own regeneration needs protoc
and the pinned files; it skips with BLOCKED_EXTERNAL_EVIDENCE without them, and nothing else here
does.

HOW EACH CONVENTION OF §2.2 MAPS FROM PROTOC'S TEXT
---------------------------------------------------
The field kinds come from the codec's field table, which
`test_embedded_table_matches_the_pinned_descriptor` holds to protoc's own descriptor of the
pinned files; nothing of the decoder's wire reading or rendering is used.

  §2.2               protoc prints                                  the twin holds
  Type               `type_url: "<url>"` in the envelope reading     `@type`: the url
  Field names        the contract's field names                     the same names
  Presence           a field it read; it omits a proto3 scalar      a key per printed field
                     holding its default, and protoc never writes
                     one, so for protoc's bytes "printed" and "on
                     the wire" coincide
  Timestamp          `{ seconds: S nanos: N }`, each omitted at 0   RFC 3339 in Z, the fewest of 0,
                                                                    3, 6 or 9 digits (`rfc3339`)
  StringValue,       `{ value: V }`, or `{ }` for the default       the bare value; "" or 0.0
  DoubleValue
  double             a number in shortest form (`21`, `57.2154`)    a float
  int64              a decimal integer                              decimal text
  int32              a decimal integer                              a number
  bool               `true` (false is never on protoc's wire)       true
  enum               the value name, or the bare number of a        the name, or the number
                     value the contract does not name
  oneof              the one member it read                         that member alone
  unknown fields     `<number>: <decimal>` (wire type 0) or         `@unknown` entries in wire
                     `<number>: "<octets>"` (wire type 2), after    order; `hex` the varint as
                     the known fields, in wire order                written (protoc's bytes are
                                                                    canonical) or the octets
  key order          fields by number, unknown fields last          the same
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sys
import types
import uuid

import pytest
from synapse_cdm import evidence, harness
from synapse_cdm.adapter import json_nesting_depth
from synapse_cdm.normative_binding import BLOCKED_STATUS, NormativeBindingBlocked

from synapse_cdm.adapters import tacticalapi_codec as codec
from synapse_cdm.adapters.tacticalapi_codec import TacticalapiRefused

from gates import protoc_text
from gates import tacticalapi_field_table as gen_field_table
from gates.protoc_text import Identifier
from tests import tacticalapi_protowire as pw

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = pathlib.Path(codec.__file__).resolve().parents[1]
#: The package's whole fixture root, as the host's evidence and harness read it.
FIXTURES_ROOT = PKG / "fixtures"
SET = FIXTURES_ROOT / "tacticalapi"
#: The adapter's specification in the repository.
RECORD = ROOT / "docs" / "tacticalapi-implementation.md"
BUILDER_PATH = SET / "spec/build_fixtures.py"
PIN_PATH = SET / "spec/tacticalapi_pin.json"


def _load_builder():
    """`spec/build_fixtures.py` as a module: its case table is what the tree is held to.

    Compiled in memory from the source on disk, as the host's generator loaders are
    (`tests/test_cdm_generator_loading.py`), never through the ordinary
    source loader: that loader consults and writes `__pycache__`, so it would leave bytecode
    inside the fixture set, and a `.pyc` is revalidated only on the source's mtime in whole
    seconds and its size, so an edit reverted within one second would be judged by bytecode of
    the edit. Changed 2026-10-04 (final verification, licence-2); the path is read from
    `BUILDER_PATH` when called, so a test can point it at a copy."""
    name = "tacticalapi_build_fixtures"
    module = types.ModuleType(name)
    module.__file__ = str(BUILDER_PATH)
    sys.modules[name] = module           # dataclasses look the module up by name as it runs
    exec(compile(BUILDER_PATH.read_text(encoding="utf-8"), str(BUILDER_PATH), "exec"),
         module.__dict__)
    return module


builder = _load_builder()
TWINNED = [case for case in builder.CASES if case.home != "malformed"]
MALFORMED = [case for case in builder.CASES if case.home == "malformed"]


def CASE_IDS(case) -> str:
    return case.path("")

#: The record §7, by name: the harness fixtures, the refusal set and the accepted counterexamples.
HARNESS_FIXTURES = ("snapshot_three_forces", "delta_with_deletion", "awkward_zeros",
                    "awkward_symbols_and_codes", "snapshot_with_unknown_fields")
MALFORMED_PAYLOADS = ("truncated_varint", "length_past_end", "wire_type_mismatch",
                      "unsupported_message_type", "success_false", "blue_force_without_identity",
                      "two_oneof_members", "latitude_91")
CASES = ("unknown_field_carried", "empty_geo_point", "empty_successful_response",
         "deleted_without_timestamps", "duplicate_identity", "d_code_second_set_zero",
         "unknown_fields_without_carrier", "error_message_without_carrier")

#: FOR THE ADAPTER STAGE: the refusal payloads the decoder reads cleanly, which the adapter must
#: refuse, with the reason code README.md names for each. `test_the_adapter_level_refusals_...`
#: holds this to README.md and shows each one decodes, and that protoc reads it the same way.
REFUSED_BY_THE_ADAPTER = {
    "success_false.binpb": "response-not-successful",
    "blue_force_without_identity.binpb": "blue-force-without-identity",
    "latitude_91.binpb": "coordinate-out-of-range",
}

#: The uuid5 names behind every `uuid_identity` of the set; nothing else may stand in for one.
EXERCISE_UUID_NAMES = ("EXERCISE-COBRA-6", "EXERCISE-RECCE-7", "EXERCISE-SENTRY-9")


def read(relative: str) -> str:
    return (SET / relative).read_text(encoding="utf-8")


def test_loading_the_builder_writes_no_bytecode_beside_it(tmp_path, monkeypatch):
    """licence-2 (2026-10-04, final verification): the local replica of the host's
    `tests/test_cdm_generator_loading.py::test_loading_a_generator_writes_no_bytecode_beside_it`.
    The builder is copied at its own depth (it finds the package's root from `__file__`, three
    directories above its own) and the loader is pointed at the copy. Bytecode writing is forced on, so a loader that went back to
    the ordinary source loader would write `__pycache__` here whatever the environment says."""
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    monkeypatch.setattr(sys, "path", list(sys.path))      # the builder inserts the package root
    monkeypatch.setitem(sys.modules, "tacticalapi_build_fixtures",
                        sys.modules["tacticalapi_build_fixtures"])
    spec = tmp_path / "synapse_cdm" / "fixtures" / "tacticalapi" / "spec"
    spec.mkdir(parents=True)
    copy = spec / BUILDER_PATH.name
    copy.write_bytes(BUILDER_PATH.read_bytes())
    monkeypatch.setitem(globals(), "BUILDER_PATH", copy)
    loaded = _load_builder()
    assert loaded.__file__ == str(copy) and loaded.HERE == spec.resolve()
    assert [case.name for case in loaded.CASES] == [case.name for case in builder.CASES]
    assert sorted(path.name for path in spec.iterdir()) == [BUILDER_PATH.name], (
        "loading the builder wrote beside it; compile it in memory instead")


# ================================================================================ the inventory


def test_the_set_is_what_mapping_section_7_lists():
    assert [case.name for case in builder.CASES if case.home == ""] == list(HARNESS_FIXTURES)
    assert [case.name for case in builder.CASES if case.home == "cases"] == list(CASES)
    assert [case.name for case in MALFORMED] == list(MALFORMED_PAYLOADS)
    assert sorted(p.name for p in (SET / "malformed").iterdir()) == sorted(
        [f"{name}.binpb" for name in MALFORMED_PAYLOADS] + ["PROVENANCE.json"])
    assert sorted(p.name for p in (SET / "cases").iterdir()) == sorted(
        [f"{name}{suffix}" for name in CASES for suffix in (".binpb", ".parsed.json")]
        + ["PROVENANCE.json"])


def test_the_harness_selects_exactly_the_top_level_payloads_and_their_twins():
    """`synapse_cdm.harness.select_fixtures`, the one definition of "a fixture", over the set."""
    selected = [p.relative_to(SET).as_posix() for p in harness.select_fixtures(SET)]
    assert selected == sorted(f"{name}{suffix}" for name in HARNESS_FIXTURES
                              for suffix in (".binpb", ".parsed.json"))


# ======================================================================== the decoder's twins


@pytest.mark.parametrize("case", TWINNED, ids=CASE_IDS)
def test_every_twin_is_the_decoders_reading_of_its_payload(case):
    raw = (SET / case.path(".binpb")).read_bytes()
    text = read(case.path(".parsed.json"))
    decoded = codec.decode(raw)
    assert text == json.dumps(decoded, indent=2, ensure_ascii=True) + "\n"
    # Both forms of one message give one twin (the record §2.2).
    assert codec.validate_twin(json.loads(text)) == decoded
    assert codec.twin_of(json.loads(text)) == codec.twin_of(raw)


# ===================================================================== protoc's own reading


def rfc3339(seconds: int, nanos: int) -> str:
    """§2.2's Timestamp text, written here with `datetime` and not by the decoder: UTC, `Z`, and the
    fewest of 0, 3, 6 or 9 fractional digits that hold `nanos` exactly."""
    instant = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(seconds=seconds)
    text = (f"{instant.year:04d}-{instant.month:02d}-{instant.day:02d}T"
            f"{instant.hour:02d}:{instant.minute:02d}:{instant.second:02d}")
    digits = f"{nanos:09d}"
    width = next(width for width in (0, 3, 6, 9) if digits[width:] == "0" * (9 - width))
    return f"{text}.{digits[:width]}Z" if width else f"{text}Z"


def test_the_timestamp_rendering_here_is_the_one_section_2_2_states():
    assert rfc3339(0, 0) == "1970-01-01T00:00:00Z"
    assert rfc3339(1790661600, 250_000_000) == "2026-09-29T06:00:00.250Z"
    assert rfc3339(1790662499, 1000) == "2026-09-29T06:14:59.000001Z"
    assert rfc3339(1790663399, 1) == "2026-09-29T06:29:59.000000001Z"
    assert rfc3339(-62135596800, 0) == "0001-01-01T00:00:00Z"


def unknown_entry(number: int, value) -> dict:
    """An unknown field as protoc printed it, as a §2.2 `@unknown` entry."""
    if isinstance(value, int) and not isinstance(value, bool):
        return {"number": number, "wire_type": 0, "hex": pw.varint(value).hex()}
    if isinstance(value, bytes):
        return {"number": number, "wire_type": 2, "hex": value.hex()}
    raise AssertionError(f"unknown field {number} is printed as {value!r}; the set appends wire "
                         "types 0 and 2 only, with octets protoc prints as a string")


def reading_value(field: codec.Field, value):
    if field.kind == "message":
        assert isinstance(value, list), f"{field.name} is printed as {value!r}, not a message"
        if field.type == codec.TIMESTAMP:
            assert {name for name, _ in value} <= {"seconds", "nanos"}, value
            return rfc3339(protoc_text.single(value, "seconds", 0),
                           protoc_text.single(value, "nanos", 0))
        if field.type == codec.STRING_VALUE:
            assert {name for name, _ in value} <= {"value"}, value
            return protoc_text.text(value, "value", "")
        if field.type == codec.DOUBLE_VALUE:
            assert {name for name, _ in value} <= {"value"}, value
            return float(protoc_text.single(value, "value", 0.0))
        return reading_twin(value, field.type)
    if field.kind == "string":
        return value.decode("utf-8")
    if field.kind == "double":
        return float(value)
    if field.kind == "int64":
        return str(value)
    if field.kind == "bool":
        return {"true": True, "false": False}[value]
    if field.kind == "enum" and isinstance(value, Identifier):
        return str(value)
    assert field.kind in ("int32", "enum") and isinstance(value, int), (field, value)
    return value


def reading_twin(fields: list, type_name: str) -> dict:
    """One message as protoc's text states it, rendered as the twin §2.2 describes (the table in
    the module docstring): known fields by number, then unknown fields under `@unknown`."""
    by_name = codec.FIELDS_BY_NAME[type_name]
    known: dict[int, object] = {}
    unknown = []
    for name, value in fields:
        if name.isdigit():               # protoc prints a field the type does not name by number
            unknown.append(unknown_entry(int(name), value))
            continue
        number, field = by_name[name]
        rendered = reading_value(field, value)
        if field.repeated:
            known.setdefault(number, []).append(rendered)
        else:
            assert number not in known, f"{name} is printed twice"
            known[number] = rendered
    twin = {codec.MESSAGES[type_name][number].name: known[number] for number in sorted(known)}
    if unknown:
        twin["@unknown"] = unknown
    return twin


def protoc_twin(case) -> dict:
    """The twin protoc's two readings of a payload state. The envelope reading must account for
    every octet of the payload before the value reading is believed."""
    envelope = protoc_text.parse(read(f"independent/{case.name}.any.txtpb"))
    assert [name for name, _ in envelope] == ["type_url", "value"]
    type_url = protoc_text.text(envelope, "type_url")
    value = protoc_text.single(envelope, "value")
    url = type_url.encode("utf-8")
    # 0x0a = field 1 (type_url) << 3 | 2; 0x12 = field 2 (value) << 3 | 2; each with its length.
    assert (SET / case.path(".binpb")).read_bytes() == (
        b"\x0a" + pw.varint(len(url)) + url + b"\x12" + pw.varint(len(value)) + value)
    response = protoc_text.parse(read(f"independent/{case.name}.value.txtpb"))
    return {"@type": type_url, **reading_twin(response, type_url.rsplit("/", 1)[1])}


@pytest.mark.parametrize("case", TWINNED, ids=CASE_IDS)
def test_every_twin_is_protocs_own_reading_of_its_payload(case):
    committed = json.loads(read(case.path(".parsed.json")))
    expected = protoc_twin(case)
    assert committed == expected
    assert json.dumps(committed) == json.dumps(expected)           # the key order too


# ================================================================================= the sources


def is_default(field: codec.Field, value) -> bool:
    if field.kind == "bool":
        return value == "false"
    if field.kind == "string":
        return value == b""
    if field.kind == "enum" and isinstance(value, Identifier):
        return codec.ENUM_NUMBERS[field.type][str(value)] == 0
    return value == 0


def as_written(fields: list, type_name: str) -> list:
    """A source's fields as protoc writes them: a proto3 scalar holding its default is left off
    the wire unless it is a oneof member; a message field is written whenever it is set."""
    kept = []
    for name, value in fields:
        _, field = codec.FIELDS_BY_NAME[type_name][name]
        if field.kind == "message":
            kept.append((name, as_written(value, field.type)))
        elif field.oneof is not None or not is_default(field, value):
            kept.append((name, value))
    return kept


def node_at(twin: dict, path: str) -> dict:
    """The object a twin path names, spelled as `codec.unknown_fields` spells it."""
    node = twin
    for part in filter(None, path.split(".")):
        name, _, index = part.partition("[")
        node = node[name][int(index.rstrip("]"))] if index else node[name]
    return node


def source_twin(case) -> dict:
    text = (SET / f"sources/{case.name}.txtpb").read_text(encoding="ascii")
    assert text == case.source, "the committed source is not the builder's literal"
    [(name, body)] = protoc_text.parse(text)
    assert name.startswith("[") and name.endswith("]"), name
    type_url = name[1:-1]
    twin = {"@type": type_url,
            **reading_twin(as_written(body, type_url.rsplit("/", 1)[1]),
                           type_url.rsplit("/", 1)[1])}
    for append in case.appends:
        node_at(twin, append.at).setdefault("@unknown", []).append(
            {"number": append.number, "wire_type": append.wire_type, "hex": append.value.hex()})
    return twin


@pytest.mark.parametrize("case", TWINNED, ids=CASE_IDS)
def test_every_twin_is_its_source_as_protoc_writes_it(case):
    committed = json.loads(read(case.path(".parsed.json")))
    assert committed == source_twin(case)
    assert json.dumps(committed) == json.dumps(source_twin(case))


@pytest.mark.parametrize("case", builder.CASES, ids=CASE_IDS)
def test_every_committed_source_is_the_builders_literal(case):
    """Every case, the eight `malformed/` ones included, which have no twin and so reach the
    comparison above only through the protoc-gated rebuild: the committed source is the
    builder's literal octet for octet. Needs neither protoc nor the pinned files (added
    2026-10-04, final verification)."""
    committed = (SET / f"sources/{case.name}.txtpb").read_bytes()
    assert committed == case.source.encode("ascii")


def test_the_sources_are_one_per_case_and_nothing_else():
    assert sorted(path.name for path in (SET / "sources").iterdir()) == sorted(
        [f"{case.name}.txtpb" for case in builder.CASES] + [harness.PROVENANCE_FILE])
    # Twenty-one since 2026-10-04 (final verification): `snapshot_with_unknown_fields` at the
    # top level and `cases/error_message_without_carrier` were added (the record §7).
    assert len(MALFORMED) == 8 and len(builder.CASES) == 21


def test_the_readme_opening_counts_what_was_changed_after_protoc():
    """README.md's first claim, held to the case table: fourteen payloads are protoc's bytes
    unchanged, three have fields appended by hand (two in `cases/`, one harness fixture), and
    four `malformed/` ones had one byte surgery each. The counts moved from 13, 2 and 4 on
    2026-10-04 (final verification), when two fixtures were added."""
    appended = [case.name for case in builder.CASES if case.appends]
    cut = [case.name for case in builder.CASES if case.surgery is not None]
    assert sorted(case.path("") for case in builder.CASES if case.appends) == [
        "cases/unknown_field_carried", "cases/unknown_fields_without_carrier",
        "snapshot_with_unknown_fields"]
    assert {case.home for case in builder.CASES if case.surgery is not None} == {"malformed"}
    assert (len(builder.CASES) - len(appended) - len(cut), len(appended), len(cut)) == (14, 3, 4)
    opening = read("README.md").split("\n\n")[3]
    assert opening.startswith("**Every payload is synthetic, and every one starts as protoc's "
                              "own encoding of a text source;")
    for said in ("Fourteen are protoc's bytes unchanged.", "Seven were changed",
                 "three have hand-encoded fields appended (two in `cases/` and the harness "
                 "fixture `snapshot_with_unknown_fields`)",
                 "four in `malformed/` are protoc's bytes after one byte surgery each"):
        assert said in opening.replace("\n", " "), said


def test_the_declared_limitation_and_mapping_section_7_count_what_was_changed_after_protoc():
    """licence-4 / mapping-9 (2026-10-04, final verification): the `no-endpoint-exercised`
    limitation, which the manifest publishes, and the record §7 said every fixture was written by
    protoc. Both now say what README.md says, held here to the same case table."""
    from synapse_cdm.adapters.tacticalapi import TacticalapiAdapter
    appended = sum(1 for case in builder.CASES if case.appends)
    cut = sum(1 for case in builder.CASES if case.surgery is not None)
    unchanged = len(builder.CASES) - appended - cut
    words = {14: "Fourteen", 7: "Seven", 3: "three", 4: "four"}
    summary = {entry.id: entry.summary for entry in TacticalapiAdapter.metadata.limitations}[
        "no-endpoint-exercised"]
    for said in (f"{words[unchanged]} are protoc's bytes unchanged.",
                 f"{words[appended + cut]} were changed afterwards",
                 f"{words[appended]} have hand-encoded fields appended",
                 f"{words[cut]} refusal payloads are protoc's bytes after one byte surgery each"):
        assert said in summary, said
    assert "written by protoc" not in summary
    mapping = RECORD.read_text(encoding="utf-8")
    section_7 = mapping.split("## 7. Fixtures", 1)[1].split("\n## ", 1)[0].replace("\n", " ")
    assert len(builder.CASES) == 21
    assert "Fourteen of the twenty-one are `protoc`'s bytes unchanged." in section_7
    assert "Seven were changed afterwards" in section_7
    assert "Written by `protoc` from text sources" not in section_7


def test_the_harness_fixture_with_unknown_fields_is_the_cases_one_under_another_name():
    """mapping-11 (2026-10-04, final verification): the harness selects no `cases/` file, so the
    residual bindings met the lossless column and the goldens only through a copy at the top
    level. The copy is the case itself, octet for octet, from the same source and appends."""
    [top] = [case for case in builder.CASES if case.name == "snapshot_with_unknown_fields"]
    [kept] = [case for case in builder.CASES if case.name == "unknown_field_carried"]
    assert (top.home, kept.home) == ("", "cases")
    assert (top.source, top.appends) == (kept.source, kept.appends)
    for suffix in (".binpb", ".parsed.json"):
        assert (SET / top.path(suffix)).read_bytes() == (SET / kept.path(suffix)).read_bytes()
    assert codec.unknown_fields(json.loads(read(top.path(".parsed.json"))))


@pytest.mark.parametrize("case", [case for case in TWINNED if case.appends], ids=CASE_IDS)
def test_the_unknown_fields_are_exactly_the_ones_appended_by_hand(case):
    committed = json.loads(read(case.path(".parsed.json")))
    found = sorted((entry["path"], entry["number"], entry["wire_type"], entry["hex"])
                   for entry in codec.unknown_fields(committed))
    assert found == sorted((append.at, append.number, append.wire_type, append.value.hex())
                           for append in case.appends)


def walk(node: dict, type_name: str):
    """(field, value) for every known field of a twin, depth first; `@unknown` entries as
    (None, entry)."""
    by_name = codec.FIELDS_BY_NAME[type_name]
    for key, value in node.items():
        if key == "@type":
            continue
        if key == "@unknown":
            yield from ((None, entry) for entry in value)
            continue
        field = by_name[key][1]
        for item in (value if field.repeated else [value]):
            yield field, item
            if field.kind == "message" and field.type not in codec.WELL_KNOWN_TYPES:
                yield from walk(item, field.type)


def conventions(twin: dict) -> set:
    seen = set()
    for field, value in walk(twin, codec.type_name_of(twin["@type"])):
        if field is None:
            seen.add(f"unknown wire type {value['wire_type']}")
        elif field.type == codec.TIMESTAMP:
            fraction = re.search(r"\.([0-9]+)Z$", value)
            seen.add(f"timestamp with {len(fraction.group(1)) if fraction else 0} digits")
        elif field.type in (codec.STRING_VALUE, codec.DOUBLE_VALUE):
            seen.add("wrapper holding its default" if value in ("", 0.0) else "wrapper")
        elif field.kind == "enum":
            seen.add("enum by name" if isinstance(value, str) else "enum by number")
        elif field.kind != "message":
            seen.add(field.kind)
        if field is not None and field.oneof is not None:
            seen.add("oneof member")
        if field is not None and field.repeated:
            seen.add("repeated")
    return seen


def test_the_comparisons_meet_every_convention_of_section_2_2():
    """A comparison that never met a convention would pass for the wrong reason: every row of the
    module docstring's table occurs in some twin the two comparisons above read."""
    seen = set().union(*(conventions(json.loads(read(case.path(".parsed.json"))))
                         for case in TWINNED))
    assert seen >= {
        "timestamp with 0 digits", "timestamp with 3 digits", "timestamp with 6 digits",
        "timestamp with 9 digits", "wrapper", "wrapper holding its default", "enum by name",
        "enum by number", "oneof member", "repeated", "string", "double", "int64", "int32",
        "bool", "unknown wire type 0", "unknown wire type 2",
    }, seen


# ============================================================================== the content


def test_the_harness_fixtures_hold_all_four_identity_kinds_and_nanosecond_digits():
    kinds, times = set(), []
    for name in HARNESS_FIXTURES:
        twin = json.loads(read(f"{name}.parsed.json"))
        for field, value in walk(twin, codec.type_name_of(twin["@type"])):
            if field is not None and field.oneof == "type":
                kinds.add(field.name)
            if field is not None and field.type == codec.TIMESTAMP:
                times.append(value)
    assert kinds == {"uuid_identity", "string_identity", "int32_identity", "int64_identity"}
    assert any(re.search(r"\.[0-9]{9}Z$", text) for text in times), times


def names_in(fields: list):
    """Every name a source states: callsigns, point names, error messages, string identities and
    UUID identities, with the field that holds each."""
    for name, value in fields:
        if name in ("callsign", "name", "error_message"):
            yield name, protoc_text.text(value, "value", "")
        elif name in ("string_identity", "uuid_identity"):
            yield name, value.decode("utf-8")
        elif isinstance(value, list):
            yield from names_in(value)


def test_every_name_in_the_set_carries_exercise_and_every_uuid_is_an_exercise_uuid5():
    uuids = {str(uuid.uuid5(uuid.NAMESPACE_URL, f"urn:exercise:{name}"))
             for name in EXERCISE_UUID_NAMES}
    seen_uuids = set()
    for case in builder.CASES:
        for field, text in names_in(protoc_text.parse(case.source)):
            if field == "uuid_identity":
                assert text in uuids, (case.name, text)
                seen_uuids.add(text)
            elif text:               # awkward_zeros' empty callsign and error message are values
                assert "EXERCISE" in text, (case.name, field, text)
        for append in case.appends:
            if append.wire_type == 2:
                assert b"EXERCISE" in append.value, (case.name, append)
    assert seen_uuids == uuids


# ================================================================================ the refusals

#: One row of README.md's malformed/ table: file, what is wrong, how made, code, which layer.
README_ROW = re.compile(r"^\| `(?P<file>[a-z0-9_]+\.binpb)` \|[^|\n]*\|[^|\n]*\| "
                        r"`(?P<code>[a-z0-9-]+)` \| (?P<by>decoder|adapter) \|$", re.MULTILINE)


def readme_refusals() -> dict[str, tuple[str, str]]:
    rows = {}
    for match in README_ROW.finditer(read("README.md")):
        assert match["file"] not in rows, f"README.md lists {match['file']} twice"
        rows[match["file"]] = (match["code"], match["by"])
    return rows


def test_readme_names_a_refusal_for_every_malformed_payload_and_the_records_agree():
    rows = readme_refusals()
    assert set(rows) == {f"{name}.binpb" for name in MALFORMED_PAYLOADS}
    pin = {entry["file"]: entry for entry in json.loads(PIN_PATH.read_text())["malformed"]["files"]}
    for case in MALFORMED:
        file = f"{case.name}.binpb"
        assert rows[file] == (case.refused_with, case.refused_by)
        entry = pin[f"malformed/{file}"]
        assert (entry["refused_with"], entry["refused_by"]) == rows[file]
        assert entry["made_by"] == (case.surgery.says if case.surgery is not None
                                    else "protoc's own encoding of the source, unchanged")
        code, by = rows[file]
        assert code in (codec.DECODER_CODES if by == "decoder" else codec.ADAPTER_CODES)


@pytest.mark.parametrize("file", sorted(f"{name}.binpb" for name in MALFORMED_PAYLOADS
                                        if f"{name}.binpb" not in REFUSED_BY_THE_ADAPTER))
def test_a_payload_malformed_for_the_decoder_is_refused_with_the_code_readme_names(file):
    code, by = readme_refusals()[file]
    assert by == "decoder"
    raw = (SET / "malformed" / file).read_bytes()
    for call in (codec.decode, codec.twin_of):
        with pytest.raises(TacticalapiRefused) as caught:
            call(raw)
        assert caught.value.code == code, str(caught.value)
        assert str(caught.value).startswith(f"{code}: ")


@pytest.mark.parametrize("file", sorted(REFUSED_BY_THE_ADAPTER))
def test_the_adapter_level_refusals_decode_cleanly_and_protoc_reads_them_the_same(file):
    """Listed for the adapter stage (REFUSED_BY_THE_ADAPTER): the decoder reads each cleanly, and
    protoc's own reading states the condition the adapter refuses."""
    assert readme_refusals()[file] == (REFUSED_BY_THE_ADAPTER[file], "adapter")
    case = next(case for case in MALFORMED if f"{case.name}.binpb" == file)
    decoded = codec.decode((SET / "malformed" / file).read_bytes())
    assert decoded == protoc_twin(case)
    elements = decoded.get("blue_forces") or decoded.get("updated_blue_forces")
    if file == "success_false.binpb":
        assert "success" not in decoded["header"] and elements
    elif file == "blue_force_without_identity.binpb":
        assert [element for element in elements if "identity" not in element]
    else:
        assert elements[0]["point_location"]["geo_point"]["latitude_coordinate"] == 91.0


def test_protocs_own_verdict_on_each_decoder_refusal():
    """What protoc made of the payloads the decoder refuses. It refuses the two truncations; it
    reads the two non-canonical encodings and repairs them, as the record §3.2 says a lenient
    parser does: the float latitude becomes an unknown field and the latitude is lost, and the
    last of two oneof members is kept."""
    def reading(name: str, part: str):
        path = SET / f"independent/{name}.{part}.txtpb"
        return protoc_text.parse(path.read_text(encoding="utf-8")) if path.is_file() else None

    assert reading("length_past_end", "any") is None
    assert reading("length_past_end", "value") is None
    assert reading("truncated_varint", "any") is not None
    assert reading("truncated_varint", "value") is None

    geo_point = protoc_text.single(protoc_text.single(protoc_text.single(
        reading("wire_type_mismatch", "value"), "blue_forces"), "point_location"), "geo_point")
    assert [name for name, _ in geo_point] == ["longitude_coordinate", "1"]

    identity = protoc_text.single(protoc_text.single(
        reading("two_oneof_members", "value"), "blue_forces"), "identity")
    assert identity == [("int32_identity", 407)]

    envelope = reading("unsupported_message_type", "any")
    assert protoc_text.text(envelope, "type_url").endswith(".AddOrUpdateBlueForcesResponse")

    pin = {entry["file"]: entry["protoc_reading"]
           for entry in json.loads(PIN_PATH.read_text())["malformed"]["files"]}
    assert pin["malformed/length_past_end.binpb"].startswith(
        "protoc --decode=google.protobuf.Any refuses")
    assert "refuses the value" in pin["malformed/truncated_varint.binpb"]


# ======================================================================== the files and records


def test_no_json_under_fixtures_nests_deeper_than_16_levels():
    """Measured on the text, as the harness's loader measures it before `json.loads`."""
    found = sorted(FIXTURES_ROOT.rglob("*.json"))
    # Every twin, five provenance records and the pin, at least (golden/ adds the harness's).
    assert len(found) >= len(TWINNED) + 5 + 1, "the scan reached too few files"
    depths = {path.relative_to(FIXTURES_ROOT).as_posix():
              json_nesting_depth(path.read_text(encoding="utf-8")) for path in found}
    assert max(depths.values()) <= 16, {name: d for name, d in depths.items() if d > 16}


def test_every_directory_that_needs_a_provenance_record_has_a_valid_one():
    """`synapse_cdm.evidence.provenance_problems`, the package's own §33 checker, pointed at the
    package's fixture root: it derives the directories that need a record from the tree (every
    one the harness's selection rule finds a file in, except `golden/` and `spec/`), reads each
    record through the `FixtureProvenance` model and holds it to the files on disk.

    Re-scoped on 2026-10-06, when the set moved into the package: the fixture root is now the
    package's, whose covered directories are every adapter's, so the set equality below is taken
    over the directories at or under `tacticalapi`; the problem check still reads the whole root.
    """
    covered = {path.relative_to(FIXTURES_ROOT).as_posix()
               for path in evidence.covered_directories(FIXTURES_ROOT)}
    covered = {name for name in covered
               if name == "tacticalapi" or name.startswith("tacticalapi/")}
    assert covered == {"tacticalapi", "tacticalapi/cases", "tacticalapi/independent",
                       "tacticalapi/malformed", "tacticalapi/sources"}
    assert evidence.provenance_problems(FIXTURES_ROOT) == []
    for directory in sorted(covered):
        record = evidence.read_provenance(FIXTURES_ROOT / directory)
        assert record.fixtures and all(
            entry.synthetic and entry.classification == "PUBLIC"
            and not entry.operational_data and not entry.personal_data
            for entry in record.fixtures), directory
    assert not (SET / "spec" / harness.PROVENANCE_FILE).exists()


def pinned_entries(pin: dict) -> list[dict]:
    return (pin["fixtures"] + pin["cases"]["files"] + pin["malformed"]["files"] + pin["sources"]
            + pin["independent"])


def test_every_file_matches_the_pin_and_the_pin_names_every_payload_source_and_reading():
    """The pin's hashes were taken in memory at build time; here they are re-derived with
    `synapse_cdm.evidence.digest` from the files on disk, without protoc."""
    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    entries = pinned_entries(pin)
    for entry in entries:
        assert evidence.digest(SET / entry["file"]) == (entry["sha256"], entry["bytes"]), entry
    on_disk = {path.relative_to(SET).as_posix() for path in SET.rglob("*") if path.is_file()
               and path.name not in ("README.md", harness.PROVENANCE_FILE)
               and path.relative_to(SET).parts[0] not in ("spec", builder.GOLDEN)}
    assert {entry["file"] for entry in entries} == on_disk
    assert pin["contract"]["carried_here"] is False

    def nodes(value):
        if isinstance(value, dict):
            yield value
            for item in value.values():
                yield from nodes(item)
        elif isinstance(value, list):
            for item in value:
                yield from nodes(item)
    # The c2sim pattern: no node pairs a local path with a hash.
    assert not [node for node in nodes(pin) if "local_path" in node]


# ================================================================================== the builder


def test_the_builder_verifies_the_same_pin_as_the_field_table_generator():
    assert builder.PINNED_FILES == gen_field_table.PINNED_FILES
    assert builder.WELL_KNOWN_FILES == gen_field_table.WELL_KNOWN_FILES
    assert (builder.ENV_VAR, builder.RECORD, builder.RECORD_FIELDS) == (
        gen_field_table.ENV_VAR, gen_field_table.RECORD, gen_field_table.RECORD_FIELDS)


def tree_files() -> dict[str, bytes]:
    return {path.relative_to(SET).as_posix(): path.read_bytes() for path in SET.rglob("*")
            if path.is_file() and not builder.not_generated(path.relative_to(SET).as_posix())}


def test_the_check_names_each_file_that_differs_is_missing_or_is_extra():
    """`differences`, the comparison --check makes, on the tree itself (no protoc needed): equal
    to itself, then one file changed, one generated file absent from the tree, one tree file
    not generated. The hand-written files and golden/ are never compared."""
    tree = tree_files()
    assert "README.md" not in tree and "spec/build_fixtures.py" not in tree
    assert "spec/tacticalapi_pin.json" in tree and "independent/PROVENANCE.json" in tree
    assert builder.differences(tree) == []
    changed = {**tree, "awkward_zeros.binpb": tree["awkward_zeros.binpb"] + b"\x00"}
    assert builder.differences(changed) == [
        "awkward_zeros.binpb: differs from what this script generates"]
    missing = {**tree, "cases/not_built.binpb": b""}
    assert builder.differences(missing) == ["cases/not_built.binpb: missing from the tree"]
    extra = {name: octets for name, octets in tree.items() if name != "malformed/latitude_91.binpb"}
    assert builder.differences(extra) == [
        "malformed/latitude_91.binpb: in the tree and not generated by this script"]
    for exempt in ("README.md", "spec/build_fixtures.py", "golden/awkward_zeros.cdm.json",
                   "spec/__pycache__/build_fixtures.cpython-314.pyc", ".DS_Store"):
        assert builder.not_generated(exempt), exempt


def test_the_builder_reproduces_every_generated_file_byte_for_byte():
    """`build_fixtures.py --check`, in process: protoc, given the verified pin, writes the same
    payloads and readings, and the decoder renders the same twins, as the tree holds.

    Skipped — never passed — with a reason beginning BLOCKED_EXTERNAL_EVIDENCE when
    `SYNAPSE_CDM_TACTICALAPI_PROTO_DIR` is unset or empty, the directory does not verify against
    its record, or protoc is absent.
    """
    try:
        files = builder.generate()
    except NormativeBindingBlocked as blocked:
        pytest.skip(f"{BLOCKED_STATUS} at step {blocked.step!r}: {blocked.reason}")
    except builder.ProtocUnavailable as blocked:
        pytest.skip(f"{BLOCKED_STATUS} at step 'protoc': {blocked}")
    assert builder.differences(files) == []


def test_the_builder_refuses_an_unset_pin_rather_than_reading_anything(capsys, tmp_path):
    assert builder.main(["--check"], environ={}) == 3
    assert capsys.readouterr().err.startswith(f"{BLOCKED_STATUS} at step 'hook'")
    # An empty directory pytest made holds no record (the out-of-tree project's `tests/`
    # served until the move, 2026-10-06).
    with pytest.raises(NormativeBindingBlocked) as blocked:
        builder.resolve_pin(environ={builder.ENV_VAR: str(tmp_path)})
    assert blocked.value.step == "record"


def test_an_absent_protoc_is_blocked_external_evidence(monkeypatch):
    # A path that does not exist (nothing is created): PATH finds nothing and neither does this.
    absent = ROOT / "tests" / "no-such-directory" / "bin" / "protoc"
    assert not absent.exists()
    monkeypatch.setattr(builder.shutil, "which", lambda name: None)
    monkeypatch.setattr(builder, "PROTOC_FALLBACK", str(absent))
    with pytest.raises(builder.ProtocUnavailable) as blocked:
        builder.Protoc.locate(ROOT)
    assert blocked.value.status == BLOCKED_STATUS
