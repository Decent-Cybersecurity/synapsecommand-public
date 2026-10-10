"""`Link16GatewayAdapter`: the contract, the strict parser, the two egress modes and the metadata.

The specification is the SC Link16 Gateway 1.0.0 engineering handoff (its section 6 contract, its
sections 9 and 10 mapping and export rules, its section 16 error table), read with this
repository's rulings on it (the in-tree record `docs/link16-gateway-implementation.md` and the
documentation page `docs/docs/cdm/link16-gateway.mdx`). Every expected value below is written from
those texts by hand — a refusal is asserted as its whole message, `CODE: path — rule` — and never
read back from the adapter's own output.

PACKAGE-ONLY: everything this module reads ships in the wheel (the adapter, its fixture tree and
the in-memory schemas `synapse_cdm.schemas.generate()` returns). The repository-bound half — the
frozen 3.0.0 contract and the published `schemas/link16_gateway/` copies — is
`tests/test_cdm_link16_gateway_mapping.py`.
"""
from __future__ import annotations

import ast
import copy
import dataclasses
import datetime as dt
import hashlib
import json
import pathlib
import random
import re

import jsonschema
import pytest
import synapse_cdm
from synapse_cdm import harness, schemas
from synapse_cdm.adapter import REGISTRY, InputTooDeep, InputTooLarge, container_depth, \
    json_nesting_depth
from synapse_cdm.enums import Affiliation, EntityType, PositionSource
from synapse_cdm.manifest import (ClaimStatus, Direction, LicenseClass, LimitKind, MaturityLevel,
                                  Residual, UnknownFields, WireBinding)
from synapse_cdm.models import Entity, Kinematics, Position, Quality, TrackSample
from synapse_cdm.models import Residual as ResidualBlock
from synapse_cdm.version import SCHEMA_VERSION

from synapse_cdm.adapters import link16_gateway as module
from synapse_cdm.adapters.link16_gateway import (ADAPTER_CODES, CODES, REPORT_SCHEMA,
                                                 ExportContext, Link16GatewayAdapter,
                                                 Link16GatewayRefusal, parse_report,
                                                 validate_report)

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
SET = PKG / "fixtures" / "link16_gateway"
MALFORMED_DIR = SET / "malformed"
MODULE_SOURCE = PKG / "adapters" / "link16_gateway.py"

#: The fifteen harness fixtures (the top level of the directory), by name.
POSITIVE = (
    "air_flight_level.json", "air_hae_feet_gnss_hostile.json", "air_hae_metres_friendly.json",
    "air_msl.json", "air_sensor.json", "air_sensor_octets.bin",
    "air_south_pole_antimeridian_resolved.json", "land_agl_assumed_friend_earlier_components.json",
    "land_unknown_position.json", "subsurface_unit_other_depth_unknown_reference.json",
    "subsurface_unknown_method.json", "surface_baro_pending_null_quality.json",
    "surface_zero.json", "unknown_domain_poles_uint64_unicode.json",
    "unknown_domain_poles_uint64_unicode_octets.bin",
)

#: Every file under malformed/, with the whole refusal message the contract gives it. Written from
#: the fixture README's defect column and the module's rule table, never read off a run.
MALFORMED_CODES = {
    "missing_required_key.json": "SCHEMA_INVALID: synthetic — required",
    "unknown_top_level_key.json": "SCHEMA_INVALID: (report) — additionalProperties",
    "unknown_nested_key.json": "SCHEMA_INVALID: position — additionalProperties",
    "number_as_string.json": "SCHEMA_INVALID: position.lat_deg — type",
    "partial_coordinates.json": "SCHEMA_INVALID: position.lon_deg — required",
    "latitude_out_of_range.json": "SCHEMA_INVALID: position.lat_deg — maximum",
    "course_360.json": "SCHEMA_INVALID: kinematics.course_deg — exclusiveMaximum",
    "flight_level_unit_reference_mismatch.json":
        "SCHEMA_INVALID: position.vertical — FL unit and FL reference together",
    "sequence_above_uint64.json": "SCHEMA_INVALID: sequence — uint64",
    "uppercase_record_id.json": "SCHEMA_INVALID: record_id — canonical lowercase UUID",
    "identifier_trailing_newline.json": "SCHEMA_INVALID: gateway_id — pattern",
    "missing_origin_scope.json": "SCHEMA_INVALID: origin_scope — required",
    "non_ascii_digit_timestamp.json": "TIME_UNRESOLVED: received_at — not YYYY-MM-DDTHH:mm:ss.sssZ",
    "timestamp_without_milliseconds.json":
        "TIME_UNRESOLVED: effective_at — not YYYY-MM-DDTHH:mm:ss.sssZ",
    "second_60_effective_at.json": "TIME_UNRESOLVED: effective_at — not a calendar instant",
    "second_60_component.json": "TIME_UNRESOLVED: position.observed_at — not a calendar instant",
    "hour_24_component.json": "TIME_UNRESOLVED: kinematics.observed_at — not a calendar instant",
    "february_30.json": "TIME_UNRESOLVED: received_at — not a calendar instant",
    "component_after_effective.json":
        "TIME_UNRESOLVED: position.observed_at — component time after effective_at",
    "live_report_under_synthetic.json": "SYNTHETIC_MISMATCH: synthetic — constructor value differs",
    "top_level_array.bin": "SCHEMA_INVALID: (report) — type",
    "duplicate_key.bin": "JSON_INVALID: (report) — duplicate object key",
    "nan_literal.bin": "JSON_INVALID: (report) — non-finite number literal",
    "infinity_literal.bin": "JSON_INVALID: (report) — non-finite number literal",
    "number_overflow.bin": "JSON_INVALID: (report) — number overflows a finite double",
    "number_underflow.bin": "JSON_INVALID: (report) — number underflows a double to zero",
    "integer_not_double_exact.bin":
        "JSON_INVALID: (report) — integer not exactly representable as a double",
    "invalid_utf8.bin": "JSON_INVALID: (report) — not UTF-8",
    "byte_order_mark.bin": "JSON_INVALID: (report) — byte order mark",
    "lone_surrogate_escape.bin": "JSON_INVALID: (report) — invalid Unicode scalar value",
    "depth_33.bin": "LIMIT_EXCEEDED: (report) — nesting above 32",
    "nodes_10001.bin": "LIMIT_EXCEEDED: (report) — more than 10000 JSON value nodes",
}

#: A string no fixture holds, planted in payloads so a refusal that echoed a value would show it.
MARKER = "QZX-PAYLOAD-MARKER-7731"


def raw_of(name: str):
    return harness.load_raw(SET / name)


def report(name: str = "air_sensor.json") -> dict:
    """A fresh dict of one positive report (the handoff's air_sensor by default)."""
    return json.loads((SET / name).read_bytes())


def octets(doc) -> bytes:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def refused(call, *args, **kwargs) -> str:
    with pytest.raises(Link16GatewayRefusal) as caught:
        call(*args, **kwargs)
    return str(caught.value)


def dumped(objects) -> list[dict]:
    return [o.model_dump(mode="json") for o in objects]


# ============================================================================ 1-2 registration

def test_registration_and_class_attributes():
    assert REGISTRY["link16_gateway"] is Link16GatewayAdapter
    cls = Link16GatewayAdapter
    assert (cls.name, cls.version, cls.direction, cls.system) == \
        ("link16_gateway", "1.0.0", "bidirectional", "SC_LINK16_GATEWAY")
    assert cls.fixture_dir is None
    assert cls.ROUNDTRIP_TOLERANCE == "values"
    assert cls.TRANSFORMS == {}
    # Not overridden: an override would make the CLIs refuse a caller's `--fixtures`.
    assert "fixture_instance" not in cls.__dict__
    assert module.PROFILE == "sc-link16-gateway/1.0.0"
    assert (module.MAX_REPORT_BYTES, module.MAX_REPORT_DEPTH, module.MAX_REPORT_NODES,
            module.MAX_DEPTH) == (1_048_576, 32, 10_000, 64)


def test_metadata_values_field_by_field():
    meta = Link16GatewayAdapter.metadata
    assert (meta.id, meta.name, meta.adapter_version) == \
        ("link16_gateway", "SC Link16 Gateway report translator", "1.0.0")
    assert (meta.format.name, meta.format.version) == ("SC Link16 Gateway", "1.0.0")
    assert meta.binding is WireBinding.PROVISIONAL_INTERNAL_PROFILE
    assert meta.direction is Direction.BIDIRECTIONAL
    assert meta.license_class is LicenseClass.OPEN
    assert meta.claim_status is ClaimStatus.PROVISIONAL
    assert meta.claim_external_system is None
    assert meta.profiles == []
    assert meta.maturity.level is MaturityLevel.L4
    assert meta.maturity.external_exercise is None
    basis = meta.maturity.basis
    assert basis.count("`values` tolerance (`ROUNDTRIP_TOLERANCE`)") == 1
    assert "conformance run --adapter link16_gateway" in basis
    assert re.findall(r"tests/\S+::\w+", basis) == [
        "tests/test_cdm_link16_gateway_adapter.py::test_mirror_reproduces_every_packaged_report"]
    assert "L5 is NOT declared" in basis and "says nothing about native JREAP C" in basis
    caps = meta.capabilities
    assert caps.wire is True
    assert caps.directions_exercised == ["ingest", "egress"]
    assert len(caps.message_types) == 3
    assert caps.message_types[1].startswith("egress, mode mirror (default)")
    assert caps.message_types[2].startswith("egress, mode export")
    limits = caps.limits
    assert (limits.max_input_bytes, limits.max_depth, limits.max_objects,
            limits.max_decompressed_bytes, limits.max_parse_seconds) == \
        (1_048_576, 64, None, None, None)
    assert set(limits.declared_because) == {"max_input_bytes", "max_depth"}
    assert set(limits.absent_because) == {"max_objects", "max_decompressed_bytes",
                                          "max_parse_seconds"}
    assert {b.kind for b in limits.declared_because.values()} == {LimitKind.IMPLEMENTATION_CAP}
    assert limits.declared_because["max_input_bytes"].test == \
        "tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound"
    assert limits.declared_because["max_depth"].test == (
        "tests/test_cdm_link16_gateway_adapter.py::"
        "test_depth_32_is_limit_free_33_is_limit_exceeded_65_is_input_too_deep")
    for basis_ in limits.declared_because.values():
        assert "IMPLEMENTATION CAP" in basis_.source
        assert "is NOT the format's normative maximum" in basis_.source
        assert "class-definition" in basis_.enforced_at
    assert caps.unknown_fields is UnknownFields.NONE
    assert "rejects every key it does not define" in caps.unknown_fields_basis
    assert [x.id for x in meta.limitations] == [
        "provisional-internal-profile", "no-native-bytes", "one-report-per-call",
        "octet-only-refusals", "contract-limits", "position-methods-cdm-3-1",
        "hae-feet-converted", "affiliation-four", "motion-time-residual", "no-symbol",
        "egress-evidence-is-mirror", "synthetic-fixtures", "evidence-availability",
        "resource-limits"]
    texts = {x.id: x.summary for x in meta.limitations}
    assert "provisional" in texts["provisional-internal-profile"]
    assert "BLOCKED_EXTERNAL_EVIDENCE" in texts["no-native-bytes"]
    assert texts["evidence-availability"].startswith("`evidence.available` is false because")
    assert meta.limitations_empty_reason is None
    assert meta.residual is Residual.STRUCTURED
    assert meta.payload_adapter is None and meta.constituents == []
    assert meta.evidence.available is False


# ============================================================================ 3-4 translation

@pytest.mark.parametrize("name", POSITIVE)
def test_mirror_reproduces_every_packaged_report(name):
    """The maturity basis's own citation: every packaged report goes in, comes out as the CDM, and
    mirror egress gives the same report back — from the octets and from the dict alike, and again
    after the objects have crossed the wire as JSON."""
    raw = (SET / name).read_bytes()
    expected = json.loads(raw)
    adapter = Link16GatewayAdapter()
    for given in (raw, json.loads(raw)):
        objects = adapter.to_cdm(given)
        assert adapter.from_cdm(objects) == expected
        rewired = [type(o).model_validate_json(o.model_dump_json()) for o in objects]
        assert adapter.from_cdm(rewired) == expected


def test_the_fixture_directory_holds_exactly_the_positive_set():
    assert tuple(p.name for p in harness.select_fixtures(SET)) == POSITIVE


@pytest.mark.parametrize("name", POSITIVE)
def test_every_packaged_fixture_translates_and_validates_against_the_generated_schemas(name):
    generated = schemas.generate()
    validators = {kind: schemas.validator_for(generated[kind]) for kind in ("entity", "track")}
    objects = Link16GatewayAdapter().to_cdm(raw_of(name))
    assert [o.object_kind for o in objects] in (["entity"], ["entity", "track"])
    for obj in dumped(objects):
        errors = list(validators[obj["object_kind"]].iter_errors(obj))
        assert errors == [], [e.message for e in errors]
        assert obj["schema_version"] == SCHEMA_VERSION


# ============================================================================ 5 malformed set

@pytest.mark.parametrize("name", sorted(MALFORMED_CODES))
def test_malformed_fixtures_are_refused_with_their_expected_codes(name):
    assert refused(Link16GatewayAdapter().to_cdm, harness.load_raw(MALFORMED_DIR / name)) == \
        MALFORMED_CODES[name]


def test_the_malformed_table_and_directory_agree():
    on_disk = {p.name for p in harness.select_fixtures(MALFORMED_DIR)}
    assert on_disk == set(MALFORMED_CODES)
    assert len(on_disk) == 32
    # .json only for a valid JSON document: the harness hands a .json file over as a dict.
    for name in on_disk:
        if name.endswith(".json"):
            json.loads((MALFORMED_DIR / name).read_bytes())


# ============================================================================ 6-8 the parser

OCTET_CASES = [
    # (bytes edit on air_sensor.json, expected message)
    ((b'"profile": "sc-link16-gateway/1.0.0",',
      b'"profile": "sc-link16-gateway/1.0.0", "profile": "sc-link16-gateway/1.0.0",'),
     "JSON_INVALID: (report) — duplicate object key"),
    ((b'"lat_deg": 48.15', b'"lat_deg": NaN'), "JSON_INVALID: (report) — non-finite number literal"),
    ((b'"lat_deg": 48.15', b'"lat_deg": -Infinity'),
     "JSON_INVALID: (report) — non-finite number literal"),
    ((b'"speed_mps": 125', b'"speed_mps": 1.8e308'),
     "JSON_INVALID: (report) — number overflows a finite double"),
    ((b'"climb_mps": null', b'"climb_mps": 2e-324'),
     "JSON_INVALID: (report) — number underflows a double to zero"),
    ((b'"climb_mps": null', b'"climb_mps": -0.00000e-999'), None),        # a true zero
    ((b'"climb_mps": null', b'"climb_mps": 2.5e-324'), None),             # rounds to 5e-324
    ((b'"speed_mps": 125', b'"speed_mps": 9007199254740992'), None),      # 2^53 is exact
    ((b'"speed_mps": 125', b'"speed_mps": 9007199254740993'),
     "JSON_INVALID: (report) — integer not exactly representable as a double"),
    ((b'"speed_mps": 125', b'"speed_mps": ' + b"9" * 4301), "JSON_INVALID: (report) — not a JSON text"),
    ((b'"SIMULATED-REPORTER"', b'"SIMULATED-\\udc00"'),
     "JSON_INVALID: (report) — invalid Unicode scalar value"),
    ((b'"SIMULATED-REPORTER"', b'"SIMULATED-\tREPORTER"'), "JSON_INVALID: (report) — not a JSON text"),
    ((b"SIMULATED-REPORTER", b"SIMULATED-\xed\xa0\x80"), "JSON_INVALID: (report) — not UTF-8"),
    ((b'"extensions": {}', b'"extensions": {},'), "JSON_INVALID: (report) — not a JSON text"),
]


@pytest.mark.parametrize("edit,expected", OCTET_CASES, ids=[str(i) for i in range(len(OCTET_CASES))])
def test_octet_only_refusals(edit, expected):
    base = (SET / "air_sensor.json").read_bytes()
    assert base.count(edit[0]) == 1
    payload = base.replace(*edit)
    adapter = Link16GatewayAdapter()
    if expected is None:
        assert adapter.to_cdm(payload)[0].entity_type is EntityType.PLATFORM
    else:
        assert refused(adapter.to_cdm, payload) == expected


def test_a_byte_order_mark_and_utf16_are_refused_and_trailing_whitespace_is_not():
    base = (SET / "air_sensor.json").read_bytes()
    adapter = Link16GatewayAdapter()
    assert refused(adapter.to_cdm, b"\xef\xbb\xbf" + base) == \
        "JSON_INVALID: (report) — byte order mark"
    assert refused(adapter.to_cdm, base.decode().encode("utf-16")) == \
        "JSON_INVALID: (report) — not UTF-8"
    assert len(adapter.to_cdm(b" \n" + base + b"\r\n\t ")) == 2


class _Key(str):
    pass


class _Doc(dict):
    pass


def _with(path: str, value) -> dict:
    doc = report()
    node = doc
    keys = path.split(".")
    for k in keys[:-1]:
        node = node[k]
    node[keys[-1]] = value
    return doc


DICT_CASES = [
    (lambda: _with("source_fields", {1: "x"}), "JSON_INVALID: (report) — object key is not a string"),
    (lambda: _with("source_fields", {_Key("k"): "x"}),
     "JSON_INVALID: (report) — object key is not a string"),
    (lambda: _with("source_fields", {"k": _Key("v")}), "JSON_INVALID: (report) — not a JSON value"),
    (lambda: _with("source_fields", {"k": ("a", "b")}), "JSON_INVALID: (report) — not a JSON value"),
    (lambda: _with("source_fields", {"k": _Doc()}), "JSON_INVALID: (report) — not a JSON value"),
    (lambda: _with("reporter", "SIMULATED-\ud800"),
     "JSON_INVALID: (report) — invalid Unicode scalar value"),
    (lambda: _with("source_fields", {"\udfff": 1}),
     "JSON_INVALID: (report) — invalid Unicode scalar value"),
    (lambda: _with("position.lat_deg", float("nan")), "JSON_INVALID: (report) — non-finite number"),
    (lambda: _with("kinematics.climb_mps", float("-inf")),
     "JSON_INVALID: (report) — non-finite number"),
    (lambda: _with("kinematics.speed_mps", 2 ** 53 + 1),
     "JSON_INVALID: (report) — integer not exactly representable as a double"),
    (lambda: _with("position.lat_deg", True), "SCHEMA_INVALID: position.lat_deg — type"),
    (lambda: _with("source_fields", {"k": 2 ** 1024}),
     "JSON_INVALID: (report) — integer not exactly representable as a double"),
]


@pytest.mark.parametrize("build,expected", DICT_CASES, ids=[str(i) for i in range(len(DICT_CASES))])
def test_dict_path_refusals(build, expected):
    assert refused(Link16GatewayAdapter().to_cdm, build()) == expected


def test_input_types():
    adapter = Link16GatewayAdapter()
    for value in ("{}", (SET / "air_sensor.json").read_text(), [report()], 7, None, (1,),
                  _Doc(report())):
        assert refused(adapter.to_cdm, value) == \
            "JSON_INVALID: (report) — expected JSON octets or a dict"
    raw = (SET / "air_sensor.json").read_bytes()
    expected = dumped(adapter.to_cdm(raw))
    assert dumped(adapter.to_cdm(bytearray(raw))) == expected
    assert dumped(adapter.to_cdm(memoryview(raw))) == expected
    assert dumped(adapter.to_cdm(report())) == expected


# ============================================================================ 9-11 the bounds

def _deep(depth: int) -> dict:
    """air_sensor with `extensions` nested so the whole report is `depth` containers deep."""
    nested: object = 0
    for _ in range(depth - 2):
        nested = [nested]
    return _with("extensions", {"a": nested})


def test_depth_32_is_limit_free_33_is_limit_exceeded_65_is_input_too_deep():
    adapter = Link16GatewayAdapter()
    for depth, outcome in ((32, None), (33, "LIMIT_EXCEEDED: (report) — nesting above 32"),
                           (64, "LIMIT_EXCEEDED: (report) — nesting above 32"),
                           (65, InputTooDeep)):
        doc = _deep(depth)
        assert container_depth(doc) == depth
        assert json_nesting_depth(octets(doc).decode()) == depth
        for form in (octets(doc), doc):
            if outcome is None:
                assert [o.object_kind for o in adapter.to_cdm(form)] == ["entity", "track"]
            elif outcome is InputTooDeep:
                with pytest.raises(InputTooDeep):
                    adapter.to_cdm(form)
            else:
                assert refused(adapter.to_cdm, form) == outcome
    # The contract's bound holds for a direct caller of the parser too.
    assert refused(parse_report, octets(_deep(65))) == \
        "LIMIT_EXCEEDED: (report) — nesting above 32"


def _with_nodes(total: int) -> dict:
    base_nodes = 44                    # air_sensor.json: 1 report + 28 values + 15 nested values
    return _with("extensions", {"a": [0] * (total - base_nodes - 1)})


def _count_nodes(value) -> int:
    count, pending = 0, [value]
    while pending:
        node = pending.pop()
        count += 1
        if isinstance(node, dict):
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    return count


def test_nodes_10000_admitted_10001_refused():
    assert _count_nodes(report()) == 44
    adapter = Link16GatewayAdapter()
    admitted, over = _with_nodes(10_000), _with_nodes(10_001)
    assert (_count_nodes(admitted), _count_nodes(over)) == (10_000, 10_001)
    for form in (admitted, octets(admitted)):
        assert len(adapter.to_cdm(form)) == 2
    for form in (over, octets(over)):
        assert refused(adapter.to_cdm, form) == \
            "LIMIT_EXCEEDED: (report) — more than 10000 JSON value nodes"


def _sized(total: int) -> dict:
    """air_sensor padded through `source_fields` to exactly `total` octets of compact UTF-8."""
    doc = _with("source_fields", {"pad": ""})
    doc["source_fields"]["pad"] = "x" * (total - len(octets(doc)))
    assert len(octets(doc)) == total
    return doc


def test_one_octet_over_1_mib_is_input_too_large_and_a_dict_over_1_mib_is_limit_exceeded():
    adapter = Link16GatewayAdapter()
    at, over = _sized(1_048_576), _sized(1_048_577)
    assert len(adapter.to_cdm(octets(at))) == 2
    assert len(adapter.to_cdm(at)) == 2
    with pytest.raises(InputTooLarge):
        adapter.to_cdm(octets(over))
    assert refused(adapter.to_cdm, over) == "LIMIT_EXCEEDED: (report) — report above 1048576 octets"
    # A direct caller past the base class's wrapper meets the contract's own bound.
    assert refused(Link16GatewayAdapter.to_cdm.__wrapped__, adapter, octets(over)) == \
        "LIMIT_EXCEEDED: (report) — report above 1048576 octets"
    assert refused(parse_report, octets(over)) == \
        "LIMIT_EXCEEDED: (report) — report above 1048576 octets"
    # The dict is measured by its compact UTF-8 encoding: a non-ASCII character counts twice.
    wide = _with("source_fields", {"pad": "é" * 524_288})
    assert len(json.dumps(wide, ensure_ascii=False)) < 1_048_576 < len(octets(wide))
    assert refused(adapter.to_cdm, wide) == "LIMIT_EXCEEDED: (report) — report above 1048576 octets"


# ============================================================================ 12-19 the contract

SCHEMA_CASES = [
    # (edit, expected message); every planted value is the marker, which no message may carry
    (("reporter", ""), "SCHEMA_INVALID: reporter — minLength"),
    (("track_number", "T" * 65), "SCHEMA_INVALID: track_number — maxLength"),
    (("time_evidence", "e" * 513), "SCHEMA_INVALID: time_evidence — maxLength"),
    (("profile", MARKER), "SCHEMA_INVALID: profile — const"),
    (("domain", MARKER), "SCHEMA_INVALID: domain — enum"),
    (("identity", MARKER), "SCHEMA_INVALID: identity — enum"),
    (("tenant", MARKER + " "), "SCHEMA_INVALID: tenant — pattern"),
    (("sequence", "01"), "SCHEMA_INVALID: sequence — pattern"),
    (("incarnation", "1" * 21), "SCHEMA_INVALID: incarnation — pattern"),
    (("synthetic", "true"), "SCHEMA_INVALID: synthetic — type"),
    (("identity_code", ""), "SCHEMA_INVALID: identity_code — minLength"),
    (("quality_code", 7), "SCHEMA_INVALID: quality_code — type"),
    (("source_fields", [MARKER]), "SCHEMA_INVALID: source_fields — type"),
    (("extensions", None), "SCHEMA_INVALID: extensions — type"),
    (("position.lon_deg", -180.0001), "SCHEMA_INVALID: position.lon_deg — minimum"),
    (("position.method", MARKER), "SCHEMA_INVALID: position.method — enum"),
    (("position.vertical.unit", "km"), "SCHEMA_INVALID: position.vertical.unit — enum"),
    (("position.vertical.value", None), "SCHEMA_INVALID: position.vertical.value — type"),
    (("kinematics.speed_mps", -0.5), "SCHEMA_INVALID: kinematics.speed_mps — minimum"),
    (("kinematics.course_deg", -1), "SCHEMA_INVALID: kinematics.course_deg — minimum"),
    (("kinematics." + MARKER, 1), "SCHEMA_INVALID: kinematics — additionalProperties"),
    ((MARKER, MARKER), "SCHEMA_INVALID: (report) — additionalProperties"),
    (("kinematics", {}), "SCHEMA_INVALID: kinematics.observed_at — required"),
]


@pytest.mark.parametrize("edit,expected", SCHEMA_CASES, ids=[str(i) for i in range(len(SCHEMA_CASES))])
def test_schema_refusals_name_path_and_keyword_and_never_a_value(edit, expected):
    message = refused(Link16GatewayAdapter().to_cdm, _with(*edit))
    assert message == expected
    assert MARKER not in message


def test_schema_literal_equals_the_pinned_bundle_schema():
    """`REPORT_SCHEMA` is the handoff's report.schema.json as data. The digest is of the file's
    canonical JSON (sorted keys, compact, ASCII), computed from the handoff file on 2026-10-10;
    the file's own bytes are pinned in the pin record, and the repository-bound mapping test
    holds the published copy to both."""
    canonical = json.dumps(REPORT_SCHEMA, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    assert hashlib.sha256(canonical.encode()).hexdigest() == \
        "9ed1d775900e78064cbc7f25c42289edd936b7fc13ba827f5653383b06ed5b01"
    assert len(REPORT_SCHEMA["properties"]) == len(REPORT_SCHEMA["required"]) == 28
    assert REPORT_SCHEMA["additionalProperties"] is False
    assert REPORT_SCHEMA["$id"] == "urn:synapsecommand:sc-link16-gateway:report:1.0.0"
    pin = json.loads((SET / "spec" / "link16_gateway_pin.json").read_text())
    entry = next(f for f in pin["files"] if f["file"] == "report.schema.json")
    assert (entry["sha256"], entry["bytes"], entry["carried_here"]) == \
        ("57bb6d391652d571ddfce93e656368ee4f4ddb5e0f6c1a0cabb3eb989f8a7301", 7336, True)


@pytest.mark.parametrize("path", ["received_at", "effective_at", "position.observed_at",
                                  "kinematics.observed_at"])
def test_ecma_digit_reading_refuses_non_ascii_digits(path):
    """`\\d` is ECMA's `[0-9]`. Python's `\\d` matches U+0660..U+0669 and every other decimal
    digit, so a validator that kept it would accept text a JavaScript validator refuses. The
    shape of a timestamp is a time the adapter cannot resolve (D-17)."""
    doc = report()
    node, key = (doc, path) if "." not in path else (doc[path.split(".")[0]], path.split(".")[1])
    node[key] = node[key].replace("0", "٠", 1)
    assert refused(Link16GatewayAdapter().to_cdm, doc) == \
        f"TIME_UNRESOLVED: {path} — not YYYY-MM-DDTHH:mm:ss.sssZ"
    assert refused(Link16GatewayAdapter().to_cdm, _with("sequence", "١")) == \
        "SCHEMA_INVALID: sequence — pattern"
    assert module._ecma_digits(r"^\d{4}[\d.]$") == r"^[0-9]{4}[0-9.]$"
    assert module._ecma_digits(r"\\d") == r"\\d"


def test_a_shape_error_beside_another_schema_error_is_schema_invalid():
    doc = _with("received_at", "2026-10-04T12:00:00Z")
    doc["domain"] = "SPACE"
    assert refused(Link16GatewayAdapter().to_cdm, doc).startswith("SCHEMA_INVALID: ")


CALENDAR = [
    ("effective_at", "2026-10-04T12:00:60.000Z", "not a calendar instant"),
    ("received_at", "2026-10-04T24:00:00.000Z", "not a calendar instant"),
    ("position.observed_at", "2026-10-03T24:00:00.000Z", "not a calendar instant"),
    ("kinematics.observed_at", "2026-02-30T00:00:00.000Z", "not a calendar instant"),
    ("received_at", "2027-02-29T00:00:00.000Z", "not a calendar instant"),
    ("received_at", "0000-01-01T00:00:00.000Z", "not a calendar instant"),
    ("received_at", "2026-13-01T00:00:00.000Z", "not a calendar instant"),
    ("received_at", "2026-10-04T12:60:00.000Z", "not a calendar instant"),
]


@pytest.mark.parametrize("path,value,rule", CALENDAR)
def test_strict_calendar_refuses_second_60_hour_24_and_february_30(path, value, rule):
    """Built from the ASCII groups with the `datetime` constructor. `times.parse` is not used: on
    CPython 3.14 `datetime.fromisoformat` accepts hour 24 and moves it to the next midnight, and
    on 3.12 it refuses it, so the answer would depend on the interpreter."""
    assert refused(Link16GatewayAdapter().to_cdm, _with(path, value)) == \
        f"TIME_UNRESOLVED: {path} — {rule}"


def test_a_leap_day_is_a_calendar_instant():
    doc = _with("received_at", "2028-02-29T23:59:59.999Z")
    assert len(Link16GatewayAdapter().to_cdm(doc)) == 2


def test_component_time_after_effective_is_time_unresolved_and_earlier_is_kept():
    adapter = Link16GatewayAdapter()
    for component in ("position", "kinematics"):
        assert refused(adapter.to_cdm, _with(f"{component}.observed_at",
                                             "2026-10-04T12:00:00.001Z")) == \
            f"TIME_UNRESOLVED: {component}.observed_at — component time after effective_at"
    entity, track = adapter.to_cdm(raw_of("land_agl_assumed_friend_earlier_components.json"))
    assert track.samples[0].observed_at == dt.datetime(2026, 10, 4, 11, 59, 55,
                                                       tzinfo=dt.timezone.utc)
    assert entity.valid_from == dt.datetime(2026, 10, 4, 12, 0, tzinfo=dt.timezone.utc)
    assert entity.residual.data["report"]["kinematics"]["observed_at"] == \
        "2026-10-04T11:59:58.500Z"
    # Equal to effective_at is "at most", so it is kept.
    assert len(adapter.to_cdm(_with("kinematics.observed_at", "2026-10-04T12:00:00.000Z"))) == 2


def test_uuid_must_be_canonical_lowercase():
    adapter = Link16GatewayAdapter()
    cases = {
        "22222222-2222-4222-8222-22222222222B": "SCHEMA_INVALID: session_id — canonical lowercase UUID",
        "{22222222-2222-4222-8222-222222222222}": "SCHEMA_INVALID: session_id — canonical lowercase UUID",
        "22222222222242228222222222222222": "SCHEMA_INVALID: session_id — canonical lowercase UUID",
        "urn:uuid:22222222-2222-4222-8222-222222222222":
            "SCHEMA_INVALID: session_id — canonical lowercase UUID",
        "22222222-2222-4222-8222-222222222222\n":
            "SCHEMA_INVALID: session_id — canonical lowercase UUID",
    }
    for value, expected in cases.items():
        assert refused(adapter.to_cdm, _with("session_id", value)) == expected


def test_uint64_bounds_inclusive():
    adapter = Link16GatewayAdapter()
    top = str(2 ** 64 - 1)
    for key in ("sequence", "incarnation"):
        assert adapter.to_cdm(_with(key, top))[0].residual.data["report"][key] == \
            "18446744073709551615"
        assert refused(adapter.to_cdm, _with(key, "18446744073709551616")) == \
            f"SCHEMA_INVALID: {key} — uint64"
        assert refused(adapter.to_cdm, _with(key, "99999999999999999999")) == \
            f"SCHEMA_INVALID: {key} — uint64"


def test_fl_unit_and_reference_must_pair():
    adapter = Link16GatewayAdapter()
    for unit, reference in (("FL", "MSL"), ("ft", "FL"), ("m", "FL"), ("FL", "HAE")):
        assert refused(adapter.to_cdm, _with("position.vertical",
                                             {"value": 1, "unit": unit, "reference": reference})) \
            == "SCHEMA_INVALID: position.vertical — FL unit and FL reference together"
    entity = adapter.to_cdm(_with("position.vertical",
                                  {"value": 350, "unit": "FL", "reference": "FL"}))[0]
    assert (entity.position.vertical.value, entity.position.alt_m) == (350.0, None)


def test_synthetic_mismatch_both_ways():
    live = _with("synthetic", False)
    assert refused(Link16GatewayAdapter(synthetic=True).to_cdm, live) == \
        "SYNTHETIC_MISMATCH: synthetic — constructor value differs"
    assert refused(Link16GatewayAdapter(synthetic=False).to_cdm, report()) == \
        "SYNTHETIC_MISMATCH: synthetic — constructor value differs"
    entity, track = Link16GatewayAdapter(synthetic=False).to_cdm(live)
    assert (entity.source.synthetic, track.source.synthetic) == (False, False)
    # The live layer is another identity (the tuple holds `synthetic`).
    synthetic_entity = Link16GatewayAdapter().to_cdm(report())[0]
    assert entity.entity_id != synthetic_entity.entity_id


def test_constructor_refuses_bad_mode_context_schema_and_synthetic():
    context = _context()
    cases = [
        (dict(synthetic=1), TypeError, "synthetic must be a bool"),
        (dict(synthetic=None), TypeError, "synthetic must be a bool"),
        (dict(mode="Mirror"), ValueError, "mode must be 'mirror' or 'export'"),
        (dict(mode=None), ValueError, "mode must be 'mirror' or 'export'"),
        (dict(mode="export"), ValueError, "mode 'export' needs an ExportContext"),
        (dict(mode="export", export_context={}), TypeError, "export_context must be an ExportContext"),
        (dict(export_context=context), ValueError, "an ExportContext is given only in mode 'export'"),
        (dict(cdm_schema="4.0.0"), ValueError, "cdm_schema must be None, SCHEMA_VERSION or '3.0.0'"),
        (dict(cdm_schema="2.1.0"), ValueError, "cdm_schema must be None, SCHEMA_VERSION or '3.0.0'"),
        (dict(cdm_schema=3), ValueError, "cdm_schema must be None, SCHEMA_VERSION or '3.0.0'"),
    ]
    for kwargs, kind, text in cases:
        with pytest.raises(kind) as caught:
            Link16GatewayAdapter(**kwargs)
        assert str(caught.value) == f"link16_gateway configuration: {text}"
    for good in (None, SCHEMA_VERSION, "3.0.0"):
        Link16GatewayAdapter(cdm_schema=good)
    Link16GatewayAdapter(mode="export", export_context=context)


# ============================================================================ 21 mirror

def _projected(name: str = "air_sensor.json", **kwargs):
    adapter = Link16GatewayAdapter(**kwargs)
    return adapter, adapter.to_cdm(raw_of(name))


def test_mirror_refuses_every_deviation_as_cdm_source_conflict():
    adapter, (entity, track) = _projected()
    full = [entity, track]

    def edited(obj, **update):
        return obj.model_copy(update=update, deep=True)

    moved = entity.position.model_copy(update={"lat": 48.16})
    late = edited(track, samples=[TrackSample(position=track.samples[0].position,
                                              observed_at=dt.datetime(2026, 10, 4, 11, 59,
                                                                      tzinfo=dt.timezone.utc))])
    other_source = edited(entity, source=entity.source.model_copy(update={"adapter": "geojson"}))
    renamed = edited(entity, residual=ResidualBlock(namespace="GeoJSON",
                                                    data=entity.residual.data))
    extra_key = edited(entity, residual=ResidualBlock(namespace="SC Link16 Gateway",
                                                      data={**entity.residual.data, "x": 1}))
    bad_report = copy.deepcopy(entity.residual.data["report"])
    bad_report["position"]["lat_deg"] = 91
    invalid = edited(entity, residual=ResidualBlock(namespace="SC Link16 Gateway",
                                                    data={"report": bad_report}))
    _, (positionless,) = _projected("land_unknown_position.json")
    _, compat = _projected(cdm_schema="3.0.0")
    cases = [
        ([edited(entity, position=moved), track], "CDM_SOURCE_CONFLICT: entity.position.lat — "
         "differs from the projection of the preserved report"),
        ([edited(entity, valid_to=entity.valid_from), track], "CDM_SOURCE_CONFLICT: entity.valid_to "
         "— differs from the projection of the preserved report"),
        ([entity], "CDM_SOURCE_CONFLICT: (objects) — differs from the projection of the preserved "
         "report"),
        ([positionless, track], "CDM_SOURCE_CONFLICT: (objects) — differs from the projection of "
         "the preserved report"),
        ([entity, late], "CDM_SOURCE_CONFLICT: track.samples[0].observed_at — differs from the "
         "projection of the preserved report"),
        ([track, entity], "CDM_SOURCE_CONFLICT: (report) — one Entity, then at most one Track"),
        ([entity, track, track], "CDM_SOURCE_CONFLICT: (report) — one Entity, then at most one "
         "Track"),
        ([], "CDM_SOURCE_CONFLICT: (report) — one Entity, then at most one Track"),
        (tuple(full), "CDM_SOURCE_CONFLICT: (report) — one Entity, then at most one Track"),
        ([other_source, track], "CDM_SOURCE_CONFLICT: entity.source.adapter — not this adapter's "
         "Entity"),
        ([renamed, track], "CDM_SOURCE_CONFLICT: entity.residual — not this adapter's residual"),
        ([extra_key, track], "CDM_SOURCE_CONFLICT: entity.residual — not this adapter's residual"),
        ([invalid, track], "CDM_SOURCE_CONFLICT: entity.residual.data.report — not a valid report"),
        (compat, "CDM_SOURCE_CONFLICT: (objects) — differs from the projection of the preserved "
         "report"),
        ([edited(entity, affiliation=Affiliation.HOSTILE), track], "CDM_SOURCE_CONFLICT: "
         "entity.affiliation — differs from the projection of the preserved report"),
        ([entity, edited(track, residual=ResidualBlock(namespace="SC Link16 Gateway",
                                                        data={"record_id": "x"}))],
         "CDM_SOURCE_CONFLICT: track.residual — differs from the projection of the preserved "
         "report"),
    ]
    for objects, expected in cases:
        assert refused(adapter.from_cdm, objects) == expected
    assert refused(Link16GatewayAdapter(synthetic=False).from_cdm, full) == \
        "CDM_SOURCE_CONFLICT: entity.source.synthetic — constructor value differs"
    # The compatibility instance mirrors its own projection and refuses the full one.
    compat_adapter = Link16GatewayAdapter(cdm_schema="3.0.0")
    assert compat_adapter.from_cdm(compat) == report()
    assert refused(compat_adapter.from_cdm, full).startswith("CDM_SOURCE_CONFLICT: ")


def test_a_mirror_refusal_never_echoes_a_key_from_the_residual_or_attributes():
    adapter, (entity, track) = _projected()
    planted = entity.model_copy(update={"attributes": {MARKER: MARKER}}, deep=True)
    message = refused(adapter.from_cdm, [planted, track])
    assert message == ("CDM_SOURCE_CONFLICT: entity.attributes — differs from the projection of "
                       "the preserved report")


# ============================================================================ 22-29 export

def _context(**changes) -> ExportContext:
    fields = dict(
        record_id="20000000-0000-4000-8000-000000000001", gateway_id="synthetic-destination-1",
        session_id="20000000-0000-4000-8000-0000000000aa", sequence="7",
        received_at="2026-10-04T12:00:01.000Z", time_basis="RESOLVED_SOURCE",
        time_evidence="SYNTHETIC export: the runtime's composed request time", tenant="demo",
        realm="test-destination", synthetic=True, origin_scope="destination-scope-1",
        track_number="TEST-0900", incarnation="0", reporter="SIMULATED-EXPORTER",
        message_family="J3.2", native_profile="SYNTHETIC-NO-NATIVE-CODEC", domain="AIR",
        security_context="SYNTHETIC-UNCLASSIFIED", source_field_profile="synthetic-export/1",
        source_fields={"fixture": True}, provenance={"origin": "SYNTHETIC test"},
        position_observed_at="2026-10-04T12:00:00.000Z",
        kinematics_observed_at="2026-10-04T12:00:00.000Z",
        vertical_forms=(("m", "HAE"), ("ft", "MSL")), vertical_required=False)
    fields.update(changes)
    return ExportContext(**fields)


def _exporter(**changes) -> Link16GatewayAdapter:
    return Link16GatewayAdapter(mode="export", export_context=_context(**changes))


def _loss(path, code, disposition, rule):
    return {"path": path, "code": code, "disposition": disposition, "rule": rule}


#: The handoff fixtures' quality grade (`quality_code`), which projects to `source_quality`.
GRADE = "SYNTHETIC-GRADE-A"


def test_export_context_is_frozen_and_validated():
    context = _context()
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.tenant = "other"
    assert context.vertical_forms == (("m", "HAE"), ("ft", "MSL"))
    assert _context(vertical_forms=[["m", "HAE"], ("m", "HAE")]).vertical_forms == (("m", "HAE"),)
    assert context.source_fields == '{"fixture":true}'
    first = context.source_fields_object()
    first["fixture"] = False
    assert context.source_fields_object() == {"fixture": True}
    given = {"origin": "SYNTHETIC test"}
    held = _context(provenance=given)
    given["origin"] = MARKER
    assert held.provenance_object() == {"origin": "SYNTHETIC test"}
    bad = [
        (dict(record_id=MARKER), ValueError, "record_id — does not satisfy the report field's rule"),
        (dict(session_id="20000000-0000-4000-8000-0000000000AA"), ValueError,
         "session_id — does not satisfy the report field's rule"),
        (dict(gateway_id=MARKER + "\n"), ValueError,
         "gateway_id — does not satisfy the report field's rule"),
        (dict(sequence="18446744073709551616"), ValueError, "sequence — uint64"),
        (dict(incarnation="007"), ValueError, "incarnation — does not satisfy the report field's rule"),
        (dict(track_number=""), ValueError, "track_number — does not satisfy the report field's rule"),
        (dict(reporter="r" * 129), ValueError, "reporter — does not satisfy the report field's rule"),
        (dict(reporter="\ud800"), ValueError, "reporter — invalid Unicode scalar value"),
        (dict(tenant=7), TypeError, "tenant — must be a str"),
        (dict(time_basis="RECEIPT"), ValueError,
         "time_basis — not a member of the report field's enumeration"),
        (dict(domain=MARKER), ValueError, "domain — not a member of the report field's enumeration"),
        (dict(synthetic=1), TypeError, "synthetic — must be a bool"),
        (dict(vertical_required="yes"), TypeError, "vertical_required — must be a bool"),
        (dict(received_at="2026-10-04T24:00:00.000Z"), ValueError,
         "received_at — not a YYYY-MM-DDTHH:mm:ss.sssZ calendar instant"),
        (dict(position_observed_at=MARKER), ValueError,
         "position_observed_at — not a YYYY-MM-DDTHH:mm:ss.sssZ calendar instant"),
        (dict(kinematics_observed_at=0), TypeError,
         "kinematics_observed_at — must be a str timestamp"),
        (dict(source_fields=[MARKER]), TypeError, "source_fields — must be a JSON object (dict)"),
        (dict(provenance={"x": float("nan")}), ValueError,
         "provenance — not a bounded JSON object (non-finite number)"),
        (dict(vertical_forms=(("FL", "MSL"),)), ValueError,
         "vertical_forms — a pair the report's vertical object cannot state"),
        (dict(vertical_forms=(("m",),)), TypeError,
         "vertical_forms — each entry is a (unit, reference) pair"),
        (dict(vertical_forms="m HAE"), TypeError,
         "vertical_forms — must be a tuple of (unit, reference)"),
    ]
    for change, kind, text in bad:
        with pytest.raises(kind) as caught:
            _context(**change)
        assert str(caught.value) == f"link16_gateway configuration: export_context.{text}"
        assert MARKER not in str(caught.value)


def _object_of_depth(depth: int) -> dict:
    """A JSON object exactly `depth` containers deep: `{"a": [[…[0]…]]}`."""
    nested: object = 0
    for _ in range(depth - 1):
        nested = [nested]
    return {"a": nested}


def test_export_context_objects_are_bounded_where_they_land_and_together_at_export():
    """R2-F1 (2026-10-10): `source_fields` lands one container below the report's root and
    `provenance` three (`extensions`, `"sc-link16-export/1"`), so their depth bounds are 31 and
    29 — a context that constructs never fails an export on one field's depth. The two together are
    measured only in the assembled report, by the export's self-check."""
    entity = _entity_with(_hae_metres())
    prefix = "link16_gateway configuration: export_context."
    for name, bound in (("source_fields", 31), ("provenance", 29)):
        at, over = _object_of_depth(bound), _object_of_depth(bound + 1)
        assert (container_depth(at), container_depth(over)) == (bound, bound + 1)
        emitted = _exporter(**{name: at}).from_cdm([entity])
        assert container_depth(emitted) == 32                     # exactly the contract's bound
        with pytest.raises(ValueError) as caught:
            _context(**{name: over})
        assert str(caught.value) == (f"{prefix}{name} — not a bounded JSON object "
                                     f"(nesting above {bound})")
    # Nodes: the object itself is one node, the list one more, then its members.
    assert _count_nodes({"a": [0] * 9_998}) == 10_000
    _context(provenance={"a": [0] * 9_998})
    with pytest.raises(ValueError) as caught:
        _context(provenance={"a": [0] * 9_999})
    assert str(caught.value) == (f"{prefix}provenance — not a bounded JSON object "
                                 "(more than 10000 JSON value nodes)")
    # Size: 1 048 576 octets of compact UTF-8 alone; `{"a":""}` is 8 octets around the text.
    _context(source_fields={"a": "x" * (1_048_576 - 8)})
    with pytest.raises(ValueError) as caught:
        _context(source_fields={"a": "x" * (1_048_576 - 7)})
    assert str(caught.value) == (f"{prefix}source_fields — not a bounded JSON object "
                                 "(above 1048576 octets)")
    # Each object within its own bounds, the two together over the report's: the context
    # constructs, and every export with it is refused by the self-check, nothing emitted.
    for change, expected in (
            (dict(source_fields={"a": [0] * 6_000}, provenance={"a": [0] * 6_000}),
             "LIMIT_EXCEEDED: (report) — more than 10000 JSON value nodes"),
            (dict(source_fields={"a": "x" * 600_000}, provenance={"a": "x" * 600_000}),
             "LIMIT_EXCEEDED: (report) — report above 1048576 octets")):
        with pytest.raises(Link16GatewayRefusal) as caught:
            _exporter(**change).from_cdm([entity])
        assert (str(caught.value), caught.value.losses) == (expected, ())


def test_export_builds_a_valid_report_from_entity_and_track():
    entity, track = Link16GatewayAdapter().to_cdm(raw_of("air_hae_metres_friendly.json"))
    emitted = _exporter().from_cdm([entity, track])
    assert emitted == {
        "profile": "sc-link16-gateway/1.0.0",
        "record_id": "20000000-0000-4000-8000-000000000001",
        "gateway_id": "synthetic-destination-1",
        "session_id": "20000000-0000-4000-8000-0000000000aa",
        "sequence": "7",
        "received_at": "2026-10-04T12:00:01.000Z",
        "effective_at": "2026-10-04T12:00:00.000Z",
        "time_basis": "RESOLVED_SOURCE",
        "time_evidence": "SYNTHETIC export: the runtime's composed request time",
        "tenant": "demo",
        "realm": "test-destination",
        "synthetic": True,
        "origin_scope": "destination-scope-1",
        "reporter": "SIMULATED-EXPORTER",
        "track_number": "TEST-0900",
        "incarnation": "0",
        "message_family": "J3.2",
        "native_profile": "SYNTHETIC-NO-NATIVE-CODEC",
        "domain": "AIR",
        "entity_kind": "PLATFORM",
        "identity": "FRIENDLY",
        "identity_code": None,
        "position": {"observed_at": "2026-10-04T12:00:00.000Z", "lat_deg": 48.15,
                     "lon_deg": 17.11, "method": "GNSS",
                     "vertical": {"value": 1524.0, "unit": "m", "reference": "HAE"}},
        "kinematics": {"observed_at": "2026-10-04T12:00:00.000Z", "speed_mps": 125.0,
                       "course_deg": 90.0, "climb_mps": 2.5},
        "quality_code": GRADE,
        "security_context": "SYNTHETIC-UNCLASSIFIED",
        "source_fields": {"fixture": True},
        "extensions": {"sc-link16-export/1": {"source_field_profile": "synthetic-export/1",
                                              "provenance": {"origin": "SYNTHETIC test"},
                                              "losses": []}},
    }
    # It is a report: it passes the contract and re-ingests to the same canonical state.
    assert validate_report(emitted) == emitted
    again, again_track = Link16GatewayAdapter().to_cdm(octets(emitted))
    assert again.position == entity.position
    assert again_track.samples == track.samples
    assert (again.entity_type, again.affiliation, again.kinematics, again.valid_from,
            again.quality) == (entity.entity_type, entity.affiliation, entity.kinematics,
                               entity.valid_from, Quality(source_quality=GRADE))
    assert again.entity_id != entity.entity_id          # the destination's own identity tuple
    # An Entity alone, with no position and no motion, exports too.
    _, (positionless,) = _projected("land_unknown_position.json")
    alone = _exporter().from_cdm([positionless])
    assert (alone["position"], alone["kinematics"], alone["identity"], alone["quality_code"]) == \
        (None, None, "UNKNOWN", GRADE)
    assert alone["extensions"]["sc-link16-export/1"]["losses"] == []


def test_export_list_rules_are_cdm_source_conflict():
    entity, track = Link16GatewayAdapter().to_cdm(raw_of("air_hae_metres_friendly.json"))
    exporter = _exporter()
    two_samples = track.model_copy(update={"samples": track.samples * 2}, deep=True)
    stranger = track.model_copy(update={"entity_id": track.track_id}, deep=True)
    clash = track.model_copy(update={"track_id": entity.entity_id}, deep=True)
    shifted = track.model_copy(update={"samples": [TrackSample(
        position=track.samples[0].position.model_copy(update={"lon": 17.12}),
        observed_at=track.samples[0].observed_at)]}, deep=True)
    late = track.model_copy(update={"samples": [TrackSample(
        position=track.samples[0].position,
        observed_at=dt.datetime(2026, 10, 4, 11, 59, 59, tzinfo=dt.timezone.utc))]}, deep=True)
    no_position = entity.model_copy(update={"position": None}, deep=True)
    cases = [
        ([], "CDM_SOURCE_CONFLICT: (report) — exactly one Entity, first"),
        ([track], "CDM_SOURCE_CONFLICT: (report) — exactly one Entity, first"),
        ((entity, track), "CDM_SOURCE_CONFLICT: (report) — exactly one Entity, first"),
        ([entity, track, track], "CDM_SOURCE_CONFLICT: (report) — exactly one Entity, first"),
        ([entity, entity], "CDM_SOURCE_CONFLICT: (report) — the second object must be a Track"),
        ([entity, two_samples], "CDM_SOURCE_CONFLICT: track.samples — exactly one sample"),
        ([entity, stranger], "CDM_SOURCE_CONFLICT: track.entity_id — not the Entity's identifier"),
        ([entity, clash], "CDM_SOURCE_CONFLICT: track.track_id — duplicate identifier"),
        ([entity, shifted], "CDM_SOURCE_CONFLICT: track.samples[0].position — differs from the "
         "Entity position"),
        ([entity, late], "CDM_SOURCE_CONFLICT: track.samples[0].observed_at — differs from the "
         "export position time"),
        ([no_position, track], "CDM_SOURCE_CONFLICT: track.samples — a Track with no Entity "
         "position"),
    ]
    for objects, expected in cases:
        assert refused(exporter.from_cdm, objects) == expected


def _entity_with(position: Position | None, **update) -> Entity:
    entity = Link16GatewayAdapter().to_cdm(raw_of("air_hae_metres_friendly.json"))[0]
    return entity.model_copy(update={"position": position, "quality": None, **update}, deep=True)


def _hae_metres() -> Position:
    return Position(lat=1.0, lon=2.0, alt_m=100.0, position_source=PositionSource.GNSS)


def test_export_altitude_datum_unsupported_refused_or_omitted_with_loss():
    entity = _entity_with(_hae_metres())
    # The destination carries MSL only and altitude is mandatory: refused, never converted.
    with pytest.raises(Link16GatewayRefusal) as caught:
        _exporter(vertical_forms=(("m", "MSL"),), vertical_required=True).from_cdm([entity])
    assert str(caught.value) == ("ALTITUDE_DATUM_UNSUPPORTED: entity.position.alt_m — the "
                                 "destination form does not carry this datum")
    assert caught.value.losses == (_loss("entity.position.alt_m", "ALTITUDE_DATUM_UNSUPPORTED",
                                         "REFUSED",
                                         "the destination form does not carry this datum"),)
    # Optional: the height is omitted (null, never zero) and the loss rides in the report.
    emitted = _exporter(vertical_forms=(("m", "MSL"),)).from_cdm([entity])
    assert emitted["position"]["vertical"] is None
    assert emitted["extensions"]["sc-link16-export/1"]["losses"] == [
        _loss("entity.position.alt_m", "ALTITUDE_DATUM_UNSUPPORTED", "OMITTED",
              "the destination form does not carry this datum")]
    # alt_m alone is HAE metres, and a destination that carries it gets it as stated.
    assert _exporter(vertical_forms=(("m", "HAE"),)).from_cdm([entity])["position"]["vertical"] \
        == {"value": 100.0, "unit": "m", "reference": "HAE"}


def test_export_value_not_representable_cases():
    feet = _entity_with(Position(lat=1.0, lon=2.0, position_source=PositionSource.SENSOR,
                                 vertical={"value": 900.0, "unit": "ft", "reference": "HAE"}))
    with pytest.raises(Link16GatewayRefusal) as caught:
        _exporter(vertical_forms=(("m", "HAE"),), vertical_required=True).from_cdm([feet])
    assert str(caught.value) == ("VALUE_NOT_REPRESENTABLE: entity.position.vertical — the "
                                 "destination form does not carry this unit for this datum")
    no_height = _entity_with(Position(lat=1.0, lon=2.0, position_source=PositionSource.UNKNOWN))
    assert refused(_exporter(vertical_required=True).from_cdm, [no_height]) == (
        "VALUE_NOT_REPRESENTABLE: entity.position.vertical — the destination form requires a "
        "height and the position has none")
    assert _exporter().from_cdm([no_height])["position"] == {
        "observed_at": "2026-10-04T12:00:00.000Z", "lat_deg": 1.0, "lon_deg": 2.0,
        "method": "UNKNOWN", "vertical": None}
    sensor = _entity_with(None, entity_type=EntityType.SENSOR)
    assert refused(_exporter().from_cdm, [sensor]) == (
        "VALUE_NOT_REPRESENTABLE: entity.entity_type — the contract's entity_kind has no such "
        "member")
    closed = _entity_with(None, valid_to=dt.datetime(2026, 10, 4, 13, tzinfo=dt.timezone.utc))
    assert refused(_exporter().from_cdm, [closed]) == (
        "VALUE_NOT_REPRESENTABLE: entity.valid_to — a closed source state has no snapshot form")
    assert refused(_exporter(position_observed_at=None).from_cdm, [_entity_with(_hae_metres())]) \
        == "VALUE_NOT_REPRESENTABLE: entity.position — no export position time in the context"
    # Motion with no export motion time: omitted, with a loss.
    moving = _entity_with(None, kinematics=Kinematics(speed_mps=3.0))
    emitted = _exporter(kinematics_observed_at=None).from_cdm([moving])
    assert emitted["kinematics"] is None
    assert emitted["extensions"]["sc-link16-export/1"]["losses"] == [
        _loss("entity.kinematics", "VALUE_NOT_REPRESENTABLE", "OMITTED",
              "no export motion time in the context")]
    # Canonical fields the contract has no field for are never silent.
    rich = _entity_with(Position(lat=1.0, lon=2.0, position_source=PositionSource.GNSS,
                                 accuracy_m=5.0),
                        quality=Quality(confidence=0.5), confidence=0.25,
                        attributes={"k": "v"}, ontology_types=["x"])
    losses = _exporter().from_cdm([rich])["extensions"]["sc-link16-export/1"]["losses"]
    assert [x["path"] for x in losses] == [
        "entity.position.accuracy_m", "entity.quality.confidence", "entity.confidence",
        "entity.attributes", "entity.ontology_types"]
    assert {x["disposition"] for x in losses} == {"OMITTED"}


def test_a_track_quality_is_an_omitted_loss():
    """R2-F2 (2026-10-10): `Track.track_quality` has no report field; it is never silent. Since
    A1F (2026-10-10) the two objects' equal `source_quality` is `quality_code`, not a loss."""
    entity, track = Link16GatewayAdapter().to_cdm(raw_of("air_hae_metres_friendly.json"))
    graded = track.model_copy(update={"track_quality": 0.5}, deep=True)
    emitted = _exporter().from_cdm([entity, graded])
    assert emitted["extensions"]["sc-link16-export/1"]["losses"] == [
        _loss("track.track_quality", "VALUE_NOT_REPRESENTABLE", "OMITTED",
              "the contract has no field for it"),
    ]
    # Everything else is what the same pair without a track quality exports.
    plain = _exporter().from_cdm([entity, track])
    assert {k: v for k, v in emitted.items() if k != "extensions"} == \
        {k: v for k, v in plain.items() if k != "extensions"}


def test_export_never_reads_a_residual_or_a_clock():
    def clock():
        raise AssertionError("export read the clock")

    entity = _entity_with(_hae_metres())
    plain = entity.model_copy(update={"residual": None}, deep=True)
    # A1F (2026-10-10, CONTRACT-3): every report field the export writes is planted with a
    # value the Entity and the context do not hold, so a residual read of any one of them —
    # the identity and quality codes, position, kinematics, the identity token, the times,
    # source_fields and extensions, the profile constant and the context-supplied fields (fix
    # round 1: profile, tenant, incarnation, native_profile, domain, synthetic) — changes the report and fails
    # the equality below; the loop at the end shows that no emitted field matches the plant.
    residual_report = {
        **report(), "track_number": MARKER, "identity_code": MARKER, "quality_code": MARKER,
        "identity": "NEUTRAL", "entity_kind": "UNIT", "effective_at": "2026-10-04T11:00:00.000Z",
        "reporter": MARKER, "security_context": MARKER, "message_family": MARKER,
        "profile": MARKER, "tenant": MARKER, "incarnation": "1", "native_profile": MARKER,
        "domain": "LAND", "synthetic": False,
        "position": {"observed_at": "2026-10-04T11:00:00.000Z", "lat_deg": 10.0,
                     "lon_deg": 20.0, "method": "INERTIAL",
                     "vertical": {"value": 7.0, "unit": "ft", "reference": "MSL"}},
        "kinematics": {"observed_at": "2026-10-04T11:00:00.000Z", "speed_mps": 7.0,
                       "course_deg": 7.0, "climb_mps": -7.0},
        "source_fields": {MARKER: MARKER}, "extensions": {MARKER: {MARKER: MARKER}}}
    planted = entity.model_copy(update={
        "residual": ResidualBlock(namespace="SC Link16 Gateway", data={"report": residual_report}),
        "source": entity.source.model_copy(update={"adapter": "geojson"})}, deep=True)
    exporter = Link16GatewayAdapter(clock, mode="export", export_context=_context())
    emitted = exporter.from_cdm([planted])
    assert emitted == exporter.from_cdm([plain])
    assert MARKER not in json.dumps(emitted)
    for name in ("identity_code", "quality_code", "position", "kinematics", "identity",
                 "entity_kind", "effective_at", "source_fields", "extensions"):
        assert emitted[name] != residual_report[name], name
    assert len(emitted) == 28
    for name, value in emitted.items():
        assert name in residual_report and residual_report[name] != value, name


def test_export_synthetic_mismatch_three_ways():
    entity = _entity_with(_hae_metres())
    live_entity = entity.model_copy(update={"source": entity.source.model_copy(
        update={"synthetic": False})}, deep=True)
    expected = ("SYNTHETIC_MISMATCH: entity.source.synthetic — constructor, export context and "
                "objects disagree")
    assert refused(Link16GatewayAdapter(mode="export", export_context=_context(synthetic=False))
                   .from_cdm, [entity]) == expected
    assert refused(_exporter().from_cdm, [live_entity]) == expected
    assert refused(Link16GatewayAdapter(synthetic=False, mode="export",
                                        export_context=_context(synthetic=False)).from_cdm,
                   [entity]) == expected
    live = Link16GatewayAdapter(synthetic=False, mode="export",
                                export_context=_context(synthetic=False))
    assert live.from_cdm([live_entity])["synthetic"] is False


def test_sub_millisecond_valid_from_gives_a_truncated_loss():
    entity = _entity_with(None, valid_from=dt.datetime(2026, 10, 4, 12, 0, 0, 999_999,
                                                       tzinfo=dt.timezone.utc))
    emitted = _exporter().from_cdm([entity])
    assert emitted["effective_at"] == "2026-10-04T12:00:00.999Z"
    assert emitted["extensions"]["sc-link16-export/1"]["losses"] == [
        _loss("entity.valid_from", "VALUE_NOT_REPRESENTABLE", "TRUNCATED",
              "the contract's timestamps stop at the millisecond")]


def test_an_export_time_after_the_snapshot_fails_the_self_check():
    entity = _entity_with(_hae_metres())
    assert refused(_exporter(position_observed_at="2026-10-04T12:00:00.001Z").from_cdm,
                   [entity]) == \
        "TIME_UNRESOLVED: position.observed_at — component time after effective_at"


TOO_LONG = "the contract's quality_code holds 1 to 128 characters"
NOT_SCALAR = "the contract's quality_code holds Unicode scalar values only"
OTHER_GRADE = "the report carries the Entity's grade only"


def test_the_quality_code_bound_is_the_schema_literals():
    assert REPORT_SCHEMA["properties"]["quality_code"] == {
        "anyOf": [{"type": "string", "minLength": 1, "maxLength": 128}, {"type": "null"}]}
    assert module.QUALITY_CODE_MAX == 128


#: A1F (2026-10-10, CONTRACT-2): `quality_code` <- `Quality.source_quality`, the section 9 row
#: read backwards. (Entity quality, emitted quality_code, the losses in the report.)
QUALITY_EXPORT_CASES = [
    (Quality(source_quality=GRADE), GRADE, []),
    (None, None, []),
    (Quality(confidence=0.5), None,
     [_loss("entity.quality.confidence", "VALUE_NOT_REPRESENTABLE", "OMITTED",
            "the contract has no field for it")]),
    (Quality(source_quality="é" * 128), "é" * 128, []),          # 128 characters, 256 octets
    (Quality(source_quality="7"), "7", []),
    (Quality(source_quality=GRADE, accuracy_m=3.0, uncertainty={"cross_track_m": 2.0}), GRADE,
     [_loss("entity.quality.accuracy_m", "VALUE_NOT_REPRESENTABLE", "OMITTED",
            "the contract has no field for it"),
      _loss("entity.quality.uncertainty", "VALUE_NOT_REPRESENTABLE", "OMITTED",
            "the contract has no field for it")]),
]


@pytest.mark.parametrize("quality,code,losses", QUALITY_EXPORT_CASES,
                         ids=[str(i) for i in range(len(QUALITY_EXPORT_CASES))])
def test_export_writes_quality_code_from_source_quality(quality, code, losses):
    entity = _entity_with(None, quality=quality)
    emitted = _exporter().from_cdm([entity])
    assert emitted["quality_code"] == code
    assert emitted["extensions"]["sc-link16-export/1"]["losses"] == losses
    # The report is the contract's, and re-ingests to the same grade.
    again = Link16GatewayAdapter().to_cdm(octets(emitted))[0]
    assert again.quality == (None if code is None else Quality(source_quality=code))


def test_export_refuses_a_grade_quality_code_cannot_hold():
    over = _entity_with(_hae_metres(), quality=Quality(source_quality="é" * 129))
    with pytest.raises(Link16GatewayRefusal) as caught:
        _exporter(vertical_forms=()).from_cdm([over])
    assert str(caught.value) == f"VALUE_NOT_REPRESENTABLE: entity.quality.source_quality — {TOO_LONG}"
    # Every loss found before it, the refused one last.
    assert caught.value.losses == (
        _loss("entity.position.alt_m", "ALTITUDE_DATUM_UNSUPPORTED", "OMITTED",
              "the destination form does not carry this datum"),
        _loss("entity.quality.source_quality", "VALUE_NOT_REPRESENTABLE", "REFUSED", TOO_LONG))
    # The grade is never echoed.
    marked = _entity_with(None, quality=Quality(source_quality=MARKER * 6))
    assert len(MARKER * 6) == 138
    message = refused(_exporter().from_cdm, [marked])
    assert message == f"VALUE_NOT_REPRESENTABLE: entity.quality.source_quality — {TOO_LONG}"
    # A Quality built without validation can hold a lone surrogate, which no JSON text carries.
    lone = _entity_with(None, quality=Quality.model_construct(source_quality="\ud800"))
    with pytest.raises(Link16GatewayRefusal) as caught:
        _exporter().from_cdm([lone])
    assert (str(caught.value), caught.value.losses) == (
        f"VALUE_NOT_REPRESENTABLE: entity.quality.source_quality — {NOT_SCALAR}",
        (_loss("entity.quality.source_quality", "VALUE_NOT_REPRESENTABLE", "REFUSED",
               NOT_SCALAR),))


#: (Entity grade, Track grade, emitted quality_code, the losses in the report.)
TRACK_GRADE_CASES = [
    (GRADE, GRADE, GRADE, []),
    (GRADE, None, GRADE, []),
    (GRADE, "SYNTHETIC-GRADE-B", GRADE,
     [_loss("track.quality.source_quality", "VALUE_NOT_REPRESENTABLE", "OMITTED", OTHER_GRADE)]),
    (None, GRADE, None,
     [_loss("track.quality.source_quality", "VALUE_NOT_REPRESENTABLE", "OMITTED", OTHER_GRADE)]),
]


@pytest.mark.parametrize("entity_grade,track_grade,code,losses", TRACK_GRADE_CASES,
                         ids=[str(i) for i in range(len(TRACK_GRADE_CASES))])
def test_a_track_grade_is_carried_only_when_it_is_the_entity_s(entity_grade, track_grade, code,
                                                               losses):
    entity, track = Link16GatewayAdapter().to_cdm(raw_of("air_hae_metres_friendly.json"))
    entity = entity.model_copy(update={"quality": None if entity_grade is None else
                                       Quality(source_quality=entity_grade)}, deep=True)
    track = track.model_copy(update={"quality": None if track_grade is None else
                                     Quality(source_quality=track_grade)}, deep=True)
    emitted = _exporter().from_cdm([entity, track])
    assert emitted["quality_code"] == code
    assert emitted["extensions"]["sc-link16-export/1"]["losses"] == losses


FINITE = "the contract's numbers are finite"
INF, NAN = float("inf"), float("nan")


def _kinematics_entity(**values) -> Entity:
    return _entity_with(None, kinematics=Kinematics(**values))


def _height_entity(**position) -> Entity:
    return _entity_with(Position(lat=1.0, lon=2.0, position_source=PositionSource.GNSS,
                                 **position))


#: A1F (2026-10-10, CONTRACT-1): a non-finite canonical number the export would write is
#: refused at its own path, with a loss record, at the export step and not by the self-check.
#: (The Entity, the context changes, the refused path.) The last two rows are built without
#: validation, because the models refuse those values.
NON_FINITE_CASES = [
    (lambda: _kinematics_entity(speed_mps=INF), {}, "entity.kinematics.speed_mps"),
    (lambda: _kinematics_entity(speed_mps=1.0, climb_mps=INF), {}, "entity.kinematics.climb_mps"),
    (lambda: _kinematics_entity(climb_mps=-INF), {}, "entity.kinematics.climb_mps"),
    (lambda: _kinematics_entity(climb_mps=NAN), {}, "entity.kinematics.climb_mps"),
    (lambda: _height_entity(alt_m=INF), dict(vertical_forms=(("m", "HAE"),)),
     "entity.position.alt_m"),
    (lambda: _height_entity(alt_m=NAN), dict(vertical_forms=(("m", "HAE"),)),
     "entity.position.alt_m"),
    (lambda: _height_entity(vertical={"value": NAN, "unit": "ft", "reference": "MSL"}), {},
     "entity.position.vertical.value"),
    (lambda: _height_entity(vertical={"value": -INF, "unit": "m", "reference": "HAE"}), {},
     "entity.position.vertical.value"),
    (lambda: _entity_with(None, kinematics=Kinematics.model_construct(
        speed_mps=None, course_deg=INF, climb_mps=None)), {}, "entity.kinematics.course_deg"),
    (lambda: _entity_with(Position.model_construct(
        lat=NAN, lon=2.0, alt_m=None, position_source=PositionSource.GNSS, accuracy_m=None,
        vertical=None)), {}, "entity.position.lat"),
]


@pytest.mark.parametrize("build,changes,path", NON_FINITE_CASES,
                         ids=[str(i) for i in range(len(NON_FINITE_CASES))])
def test_export_refuses_a_non_finite_number_at_its_path(build, changes, path):
    with pytest.raises(Link16GatewayRefusal) as caught:
        _exporter(**changes).from_cdm([build()])
    assert str(caught.value) == f"VALUE_NOT_REPRESENTABLE: {path} — {FINITE}"
    assert caught.value.losses == (_loss(path, "VALUE_NOT_REPRESENTABLE", "REFUSED", FINITE),)


def test_a_non_finite_number_keeps_the_losses_before_it_and_one_never_written_is_no_refusal():
    # The losses found first ride in the refusal, the refused entry last.
    entity = _entity_with(Position(lat=1.0, lon=2.0, position_source=PositionSource.GNSS,
                                   accuracy_m=5.0), kinematics=Kinematics(climb_mps=NAN))
    with pytest.raises(Link16GatewayRefusal) as caught:
        _exporter().from_cdm([entity])
    assert caught.value.losses == (
        _loss("entity.position.accuracy_m", "VALUE_NOT_REPRESENTABLE", "OMITTED",
              "the contract's position has no accuracy"),
        _loss("entity.kinematics.climb_mps", "VALUE_NOT_REPRESENTABLE", "REFUSED", FINITE))
    # Motion with no export motion time is omitted whole, so its value is never written.
    emitted = _exporter(kinematics_observed_at=None).from_cdm([_kinematics_entity(speed_mps=INF)])
    assert emitted["kinematics"] is None
    assert emitted["extensions"]["sc-link16-export/1"]["losses"] == [
        _loss("entity.kinematics", "VALUE_NOT_REPRESENTABLE", "OMITTED",
              "no export motion time in the context")]
    # A height the destination does not carry is omitted by the vertical rule, never written.
    emitted = _exporter(vertical_forms=(("m", "MSL"),)).from_cdm([_height_entity(alt_m=INF)])
    assert emitted["position"]["vertical"] is None
    assert emitted["extensions"]["sc-link16-export/1"]["losses"] == [
        _loss("entity.position.alt_m", "ALTITUDE_DATUM_UNSUPPORTED", "OMITTED",
              "the destination form does not carry this datum")]


# ============================================================================ 30-36 the rest

def test_detect_and_validate_source():
    adapter = Link16GatewayAdapter()
    raw = (SET / "air_sensor.json").read_bytes()
    assert adapter.detect(report()) is True
    assert adapter.detect({"profile": "sc-link16-gateway/2.0.0"}) is False
    assert adapter.detect(raw) is True
    assert adapter.detect(b"\xef\xbb\xbf" + raw) is False
    assert adapter.detect(b"[1]") is False
    # R2-F3 (2026-10-10): octets of a JSON object are a report only with the profile constant.
    assert adapter.detect(b'{"profile":"x"}') is False
    assert adapter.detect(b'{"a":1}') is False
    assert adapter.detect(b'{"profile":"sc-link16-gateway/1.0.0"}') is True
    assert adapter.detect(octets(_sized(1_048_577))) is False
    assert adapter.detect(raw.decode()) is None
    assert adapter.detect([report()]) is None
    assert adapter.validate_source(raw_of("surface_zero.json")) == []
    assert adapter.validate_source(raw_of("air_hae_metres_friendly.json")) == []
    assert adapter.validate_source(raw) == [
        "position.vertical: HAE feet converted to metres (x 0.3048) in vertical and alt_m; the "
        "feet stay in residual.data.report.position.vertical"]
    assert adapter.validate_source(raw_of("land_unknown_position.json")) == [
        "identity: a finer source token was projected to UNKNOWN; the token stays in "
        "residual.data.report.identity"]
    assert adapter.validate_source(raw_of("air_msl.json")) == [
        "position.vertical: the reference is not HAE, so alt_m is null and no datum conversion "
        "was made"]
    assert Link16GatewayAdapter(cdm_schema="3.0.0").validate_source(raw) == [
        "position: not projected under CDM 3.0.0 (POSITION_NOT_PROJECTED_CDM3); the report "
        "stays whole in residual.data.report"]
    assert adapter.validate_source(harness.load_raw(MALFORMED_DIR / "course_360.json")) == [
        "Link16GatewayRefusal: SCHEMA_INVALID: kinematics.course_deg — exclusiveMaximum"]
    problems = adapter.validate_source(octets(_sized(1_048_577)))
    assert len(problems) == 1 and problems[0].startswith("InputTooLarge: ")


ALLOWED_IMPORTS = {"__future__", "copy", "dataclasses", "datetime", "json", "math", "re", "typing",
                   "jsonschema", "synapse_cdm"}


def test_imports_stay_inside_the_allowed_roots():
    tree = ast.parse(MODULE_SOURCE.read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots.add(node.module.split(".")[0])
    assert roots <= ALLOWED_IMPORTS, roots - ALLOWED_IMPORTS
    assert not roots & {"socket", "ssl", "hashlib", "hmac", "secrets", "uuid", "sqlite3", "http"}
    text = MODULE_SOURCE.read_text()
    for forbidden in ("utc_now", ".now(", "time.time", "self.now", "_clock("):
        assert forbidden not in text, forbidden


def test_refusal_codes_are_from_the_section_16_table():
    assert len(CODES) == len(set(CODES)) == 18
    assert len(ADAPTER_CODES) == len(set(ADAPTER_CODES)) == 8
    assert set(ADAPTER_CODES) < set(CODES)
    tree = ast.parse(MODULE_SOURCE.read_text())
    seen, forwarded = set(), []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and \
                node.func.id in ("_refuse", "Link16GatewayRefusal", "loss") and node.args:
            index = 1 if node.func.id == "loss" else 0
            arg = node.args[index]
            if isinstance(arg, ast.Constant):
                seen.add(arg.value)
            else:
                forwarded.append(ast.unparse(arg))
    assert seen <= set(ADAPTER_CODES), seen - set(ADAPTER_CODES)
    assert seen == set(ADAPTER_CODES), set(ADAPTER_CODES) - seen
    # The only non-literal codes are the two forwarding sites: `_refuse` and the export losses.
    assert forwarded == ["code", "code"]
    with pytest.raises(ValueError):
        Link16GatewayRefusal("NOT_A_CODE", "", "x")


def test_the_validator_carries_no_format_checker_whatever_is_installed(monkeypatch):
    assert module.VALIDATOR.format_checker is None
    # An environment where an optional package registers a strict date-time checker changes
    # nothing: the calendar refusal keeps its code.
    monkeypatch.setitem(jsonschema.FormatChecker.checkers, "date-time",
                        (lambda instance: False, ()))
    assert "date-time" in jsonschema.FormatChecker().checkers
    assert refused(Link16GatewayAdapter().to_cdm,
                   harness.load_raw(MALFORMED_DIR / "february_30.json")) == \
        "TIME_UNRESOLVED: received_at — not a calendar instant"
    assert len(Link16GatewayAdapter().to_cdm(report())) == 2


def test_the_residual_namespace_is_the_declared_format_name():
    name = Link16GatewayAdapter.metadata.format.name
    entity, track = Link16GatewayAdapter().to_cdm(raw_of("air_sensor.json"))
    assert entity.residual.namespace == track.residual.namespace == name == "SC Link16 Gateway"
    assert set(entity.residual.data) == {"report"}
    assert track.residual.data == {"record_id": "11111111-1111-4111-8111-111111111111"}


EDGE_CASES = [
    ("source_fields", {"": "empty key"}),
    ("reporter", "SIMULATED\u0000NUL"),
    ("source_fields", {"n": 2 ** 53}),
    ("position.lat_deg", -0.0),
    ("source_fields", {"tiny": 5e-324}),
    ("kinematics.climb_mps", 1e308),
    ("kinematics.speed_mps", 0),
    ("source_fields", {"$ref": "#/definitions/x"}),
    ("source_fields", {"entity_id": "not an identifier of ours"}),
    ("source_fields", {"seen_at": "2026-10-04T12:00:00Z"}),
    ("reporter", " "),
    ("track_number", "\U0001f600" * 64),
    ("position.vertical", {"value": 1e308, "unit": "ft", "reference": "HAE"}),
]


@pytest.mark.parametrize("path,value", EDGE_CASES, ids=[str(i) for i in range(len(EDGE_CASES))])
def test_edge_payloads_are_accepted_schema_valid_and_mirrored(path, value):
    doc = _with(path, value)
    generated = schemas.generate()
    adapter = Link16GatewayAdapter()
    for form in (doc, octets(doc)):
        objects = adapter.to_cdm(form)
        for obj in dumped(objects):
            assert list(schemas.validator_for(generated[obj["object_kind"]]).iter_errors(obj)) == []
        assert adapter.from_cdm(objects) == json.loads(octets(doc))


@pytest.mark.parametrize("edge", ["0001", "9999"])
def test_the_first_and_last_four_digit_years_are_instants(edge):
    stamp = "0001-01-01T00:00:00.000Z" if edge == "0001" else "9999-12-31T23:59:59.999Z"
    doc = report()
    for key in ("received_at", "effective_at"):
        doc[key] = stamp
    doc["position"]["observed_at"] = doc["kinematics"]["observed_at"] = stamp
    entity, track = Link16GatewayAdapter().to_cdm(octets(doc))
    assert entity.model_dump(mode="json")["valid_from"] == stamp
    assert Link16GatewayAdapter().from_cdm([entity, track]) == doc


#: The vocabulary a refusal message may be built from: the contract's own names and the module's
#: fixed rule phrases. Read off the schema and the module's AST, so a message that grew a value
#: would fail the grammar below.
def _vocabulary():
    names: set[str] = set()
    pending = [REPORT_SCHEMA]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            names |= set(node.get("properties", {}))
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
    rules = {"type", "required", "additionalProperties", "pattern", "maximum", "minimum",
             "exclusiveMaximum", "enum", "const", "minLength", "maxLength", "anyOf"}
    for node in ast.walk(ast.parse(MODULE_SOURCE.read_text())):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and \
                node.func.id == "_refuse" and len(node.args) == 3 and \
                isinstance(node.args[2], ast.Constant):
            rules.add(node.args[2].value)
    return names, rules


def _mutate(rng: random.Random, data: bytes) -> bytes:
    i = rng.randrange(len(data))
    op = rng.randrange(5)
    if op == 0:
        return data[:i] + bytes([data[i] ^ (1 << rng.randrange(8))]) + data[i + 1:]
    if op == 1:
        return data[:i] + bytes([rng.randrange(256)]) + data[i:]
    if op == 2:
        return data[:i] + data[i + 1:]
    if op == 3:
        return data[:i]
    j = min(len(data), i + rng.randrange(1, 24))
    return data[:j] + data[i:j] + data[j:]


FUZZ_SEED = 20261010
FUZZ_PER_INPUT = 80


def test_seeded_mutation_fuzz_refuses_only_with_the_contract_vocabulary():
    """Every positive report — the octet twins and the compact encodings of the JSON ones — with a
    marker planted in three strings, mutated a fixed number of times from a fixed seed. Each
    mutant translates or is refused with `Link16GatewayRefusal`, `InputTooLarge` or
    `InputTooDeep`, never another exception; a refusal names only the contract's own vocabulary
    and never the marker. No duration is measured."""
    names, rules = _vocabulary()
    grammar = re.compile(r"(?P<code>[A-Z_]+): (?P<path>\(report\)|[a-z_.\[\]0-9]+) — (?P<rule>.+)")
    rng = random.Random(FUZZ_SEED)
    adapter = Link16GatewayAdapter()
    translated = refused_count = 0
    for name in POSITIVE:
        doc = json.loads((SET / name).read_bytes())
        doc["reporter"] = doc["track_number"] = MARKER
        doc["source_fields"][MARKER] = MARKER
        data = octets(doc)
        for _ in range(FUZZ_PER_INPUT):
            mutant = _mutate(rng, data)
            try:
                adapter.to_cdm(mutant)
                translated += 1
                continue
            except (InputTooLarge, InputTooDeep) as problem:
                message = str(problem)
            except Link16GatewayRefusal as problem:
                message = str(problem)
                match = grammar.fullmatch(message)
                assert match, message
                assert match["code"] in ADAPTER_CODES
                assert match["rule"] in rules, message
                if match["path"] != "(report)":
                    tokens = re.sub(r"\[\d+\]", "", match["path"]).split(".")
                    assert set(tokens) <= names, message
            refused_count += 1
            assert MARKER not in message
    assert refused_count + translated == len(POSITIVE) * FUZZ_PER_INPUT
    assert refused_count > translated > 0
