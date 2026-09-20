"""Audit F04: the published JSON Schema and the Python models refuse the same bytes.

Every case here is ONE JSON document run through BOTH validators — `KINDS[kind].model_validate`
over the parsed document, and `jsonschema.Draft202012Validator` over the generator's output — and
the test asserts what each says. The dialect is the one every published file declares
(`$schema: draft/2020-12`), through `schemas.validator_for`: `format` asserted explicitly and
`pattern` read as ECMA-262 reads it, because the stock Python `jsonschema` package reads `$` as
Python's `re` does and accepts a trailing newline the dialect refuses.

WHAT WAS FOUND ON THE UNMODIFIED TREE (2026-09-19), and what each block below now proves:

* `SourceRef.adapter_version` was `minLength: 1` on the wire and semver in Python, so "banana",
  "01.2.3", "1.2.3\\n", "-1.2.3" and "v1.2.3" were valid documents the model refused.
  `schema_version` had no schema constraint at all. Both now carry `version.SEMVER_PATTERN`.
* A timestamp string reached the model through `times.parse`, which takes "…44Z", "+02:00" and a
  naive string, while the schema's `pattern` takes only "…44.000Z". On the JSON path
  (`model_validate_json`, which is what conformance runs) the model now takes only the wire
  form (`times.parse_wire`); the Python path — the constructor and `model_validate(dict)`, which
  every adapter uses with its source's own string by declared design — keeps `times.parse`.
  The "Python JSON-validation path" of the finding is the JSON path, and every model check in
  this module runs on it.
* A geometry without `type` is refused by pydantic (the discriminator needs the tag) and
  accepted by the schema when exactly one `oneOf` branch matches, because the OpenAPI
  `discriminator` keyword is not JSON Schema and `jsonschema` ignores it. Requiring `type` in the
  schema would grow a `required` list on a published object, which `tests/test_cdm_schemas.py`
  holds to be a MAJOR — so it stays a documented semantic rule (SEM-001) with a deliberate,
  tested outcome at each level, and S10 records the MAJOR option.
* Enums, bounds, nullable-vs-absent and unknown fields already agreed; the tests say so on bytes.
"""
import copy
import json
import pathlib
import re
import uuid

import jsonschema
import pytest
from pydantic import ValidationError

from synapse_cdm import times
from synapse_cdm.models import KINDS
from synapse_cdm.schemas import DIALECT, generate, validator_for
from synapse_cdm.version import SEMVER_PATTERN, SEMVER_RE

REPO = pathlib.Path(__file__).resolve().parents[1]
PUBLISHED = REPO / "schemas"

_GENERATED = generate()

T = "2026-04-29T06:00:00.000Z"
T_LATER = "2026-04-29T07:00:00.000Z"
SOURCE = {"system": "TEST", "adapter": "test", "adapter_version": "1.0.0", "synthetic": True}
IDS = [{"system": "TEST", "external_id": "X-1"}]
POINT = {"type": "Point", "coordinates": [21.0, 57.0]}
LINE = {"type": "LineString", "coordinates": [[21.0, 57.0], [22.0, 58.0]]}
RING = [[21.0, 57.0], [22.0, 57.0], [22.0, 58.0], [21.0, 57.0]]
POLYGON = {"type": "Polygon", "coordinates": [RING]}
PAYLOAD = {"frequency_band": "L1", "interference_type": "JAMMING"}


def _id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"f04:{name}"))


def entity(**overrides) -> dict:
    doc = {"object_kind": "entity", "source": SOURCE, "source_ids": IDS,
           "entity_id": _id("entity"), "entity_type": "UNIT", "affiliation": "UNKNOWN",
           "valid_from": T}
    doc.update(overrides)
    return doc


def event(**overrides) -> dict:
    doc = {"object_kind": "event", "source": SOURCE, "source_ids": IDS,
           "event_id": _id("event"), "event_type": "GNSS_INTERFERENCE", "severity": "WARNING",
           "observed_at": T, "received_at": T, "payload": dict(PAYLOAD)}
    doc.update(overrides)
    return doc


def track(**overrides) -> dict:
    doc = {"object_kind": "track", "source": SOURCE, "source_ids": IDS,
           "track_id": _id("track"), "entity_id": _id("entity"),
           "samples": [{"observed_at": T, "position": {"lat": 57.0, "lon": 21.0,
                                                       "position_source": "GNSS"}}]}
    doc.update(overrides)
    return doc


def plan_object(**overrides) -> dict:
    doc = {"object_kind": "plan_object", "source": SOURCE, "source_ids": IDS,
           "object_id": _id("plan"), "object_type": "ROUTE", "geometry": LINE}
    doc.update(overrides)
    return doc


BUILDERS = {"entity": entity, "event": event, "track": track, "plan_object": plan_object}


def schema_errors(kind: str, doc: dict) -> list[str]:
    """The published schema's findings through the package's validator construction:
    draft 2020-12, `format` asserted, `pattern` read as ECMA-262 (see `schemas.validator_for`)."""
    return sorted(f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}"
                  for e in validator_for(_GENERATED[kind]).iter_errors(doc))


def model_errors(kind: str, doc: dict) -> list[str]:
    """The Python JSON path's findings over the same document, as bytes, in STRICT mode —
    what `conformance.assess_a` runs. Lax JSON mode coerces "true" to a boolean and "0.5" to a
    number; the schema's `type` does not, and `test_lax_json_coercions_are_off_on_the_wire`
    is where that difference is pinned."""
    try:
        KINDS[kind].model_validate_json(json.dumps(doc), strict=True)
    except ValidationError as e:
        return sorted(f"{'/'.join(str(p) for p in err['loc'])}: {err['msg']}"
                      for err in e.errors())
    return []


def both(kind: str, doc: dict) -> tuple[list[str], list[str]]:
    return schema_errors(kind, doc), model_errors(kind, doc)


def with_path(doc: dict, path: tuple, value) -> dict:
    out = copy.deepcopy(doc)
    node = out
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return out


# ------------------------------------------------------------- the dialect, stated not assumed

def test_every_published_schema_declares_the_dialect_the_tests_validate_with():
    for path in sorted(PUBLISHED.glob("*.schema.json")):
        assert json.loads(path.read_text())["$schema"] == DIALECT, path.name
    for kind, schema in _GENERATED.items():
        assert schema["$schema"] == DIALECT, kind
        jsonschema.Draft202012Validator.check_schema(schema)


def test_the_only_format_keyword_is_uuid_and_format_checking_is_configured_explicitly():
    """`format` is an ANNOTATION in JSON Schema unless the validator is told to assert it.

    The published schemas carry exactly one `format` — `uuid`, on the identifier fields — and
    the answer for `"entity_id": "banana"` depends on the caller: with `FormatChecker()` the
    schema refuses it, as the model does; without one the schema accepts it. Every schema run
    in this module and in `conformance.assess_a` passes the checker, so the two agree by
    configuration and this test is what makes that configuration a stated fact.
    """
    def formats(node):
        if isinstance(node, dict):
            if isinstance(node.get("format"), str):        # a PROPERTY named format is a dict
                yield node["format"]
            for sub in node.values():
                yield from formats(sub)
        elif isinstance(node, list):
            for sub in node:
                yield from formats(sub)
    found = {kind: sorted(set(formats(schema))) for kind, schema in _GENERATED.items()}
    assert all(set(v) <= {"uuid"} for v in found.values()), found
    doc = entity(entity_id="banana")
    assert any(f.startswith("entity_id:") for f in schema_errors("entity", doc))
    assert any(f.startswith("entity_id:") for f in model_errors("entity", doc))
    unchecked = jsonschema.Draft202012Validator(_GENERATED["entity"])
    assert not [e for e in unchecked.iter_errors(doc)], \
        "without a FormatChecker the schema accepts a non-UUID; that is why one is always passed"
    assert [e for e in validator_for(_GENERATED["entity"]).iter_errors(doc)]


@pytest.mark.parametrize("kind", sorted(BUILDERS))
def test_the_baseline_document_of_every_kind_passes_both_validators(kind):
    assert both(kind, BUILDERS[kind]()) == ([], [])


# ------------------------------------------------------------- version strings (the finding)

NOT_A_VERSION = ("banana", "01.2.3", "1.2.3\n", " 1.2.3", "1.2.3 ", "v1.2.3", "1.2.3-rc1",
                 "-1.2.3", "1.2", "1.2.3.4", "")


def test_the_one_pattern_feeds_both_sides():
    """One string, two homes: the pydantic `Field(pattern=)` and the emitted schema."""
    published = json.loads((PUBLISHED / "entity.schema.json").read_text())
    assert published["$defs"]["SourceRef"]["properties"]["adapter_version"]["pattern"] \
        == SEMVER_PATTERN
    assert published["properties"]["schema_version"]["pattern"] == SEMVER_PATTERN
    for kind in KINDS:
        schema = _GENERATED[kind]
        assert schema["$defs"]["SourceRef"]["properties"]["adapter_version"]["pattern"] \
            == SEMVER_PATTERN, kind
        assert schema["properties"]["schema_version"]["pattern"] == SEMVER_PATTERN, kind
    union = _GENERATED["cdm_object"]
    assert union["$defs"]["SourceRef"]["properties"]["adapter_version"]["pattern"] \
        == SEMVER_PATTERN
    for kind in KINDS:
        assert union["$defs"][KINDS[kind].__name__]["properties"]["schema_version"]["pattern"] \
            == SEMVER_PATTERN, kind
    assert SEMVER_PATTERN == "^" + SEMVER_RE.pattern + "$"


@pytest.mark.parametrize("bad", NOT_A_VERSION, ids=repr)
def test_a_malformed_adapter_version_is_refused_by_both_validators(bad):
    schema, model = both("entity", with_path(entity(), ("source", "adapter_version"), bad))
    assert any(f.startswith("source/adapter_version:") for f in schema), (bad, schema)
    assert any(f.startswith("source/adapter_version:") for f in model), (bad, model)


@pytest.mark.parametrize("bad", NOT_A_VERSION, ids=repr)
def test_a_malformed_schema_version_is_refused_by_both_validators(bad):
    schema, model = both("entity", entity(schema_version=bad))
    assert any(f.startswith("schema_version:") for f in schema), (bad, schema)
    assert any(f.startswith("schema_version:") for f in model), (bad, model)


def test_the_trailing_newline_is_the_case_the_regex_engines_disagree_on():
    """The anchor trap, on every engine in play, with the answer each one gives.

    * Python `re.match(...$)`: ACCEPTS "1.2.3\\n" — `$` matches before a final newline.
    * The Python `jsonschema` package, stock: ACCEPTS it, because its `pattern` is `re.search`.
      This is the engine a Python consumer reaches for, and it deviates from the dialect.
    * ECMA-262 (what JSON Schema specifies) and pydantic-core's Rust engine: REFUSE it.
    * `schemas.validator_for` — the package's construction, used by conformance, the harness
      and this module: REFUSES it, by reading `$` as ECMA does.
    * `re.fullmatch` / `SEMVER_RE.fullmatch` — the validators: REFUSE it.
    """
    assert re.match(SEMVER_PATTERN, "1.2.3\n") is not None          # the trap, demonstrated
    assert re.fullmatch(SEMVER_PATTERN, "1.2.3\n") is None
    assert SEMVER_RE.fullmatch("1.2.3\n") is None
    doc = with_path(entity(), ("source", "adapter_version"), "1.2.3\n")
    stock = jsonschema.Draft202012Validator(_GENERATED["entity"])
    assert [e for e in stock.iter_errors(doc)] == [], \
        "the stock Python jsonschema `pattern` now refuses a trailing newline; retire the shim"
    assert any(f.startswith("source/adapter_version:") for f in schema_errors("entity", doc))
    assert any(f.startswith("source/adapter_version:") for f in model_errors("entity", doc))


@pytest.mark.parametrize("pattern, text, ecma_matches", [
    (r"^a$", "a", True),
    (r"^a$", "a\n", False),
    (r"[$]", "$", True),                 # a class member, not an anchor
    (r"\$", "$", True),                  # escaped, not an anchor
    (r"^[0-9]{20}$", "1" * 20 + "\n", False),
    (SEMVER_PATTERN, "1.2.3\n", False),
    (SEMVER_PATTERN, "1.2.3", True),
])
def test_the_ecma_anchor_reading_only_moves_the_bare_dollar(pattern, text, ecma_matches):
    from synapse_cdm.schemas import _ecma_end_anchors
    assert (re.search(_ecma_end_anchors(pattern), text) is not None) is ecma_matches
    if not ecma_matches:
        assert re.search(pattern, text) is not None, "Python re would have accepted it"


@pytest.mark.parametrize("good", ("0.0.0", "1.0.0", "9.9.9", "10.20.30", "2.1.0"))
def test_a_well_formed_version_is_accepted_by_both_validators(good):
    assert both("entity", with_path(entity(), ("source", "adapter_version"), good)) == ([], [])


# ------------------------------------------------------------- timestamps (the finding)

NOT_WIRE_TIMESTAMPS = ("2026-04-29T06:00:00Z", "2026-04-29T06:00:00.0Z", "2026-04-29T06:00:00.000z",
                       "2026-04-29T08:00:00.000+02:00", "2026-04-29T06:00:00.000",
                       "2026-04-29 06:00:00.000Z", "2026-04-29T06:00:00.000Z\n", "", "now")


@pytest.mark.parametrize("bad", NOT_WIRE_TIMESTAMPS, ids=repr)
def test_a_non_canonical_timestamp_string_is_refused_by_both_validators(bad):
    schema, model = both("entity", entity(valid_from=bad))
    assert any(f.startswith("valid_from:") for f in schema), (bad, schema)
    assert any(f.startswith("valid_from:") for f in model), (bad, model)


def test_the_two_paths_are_the_two_contracts():
    """JSON path: wire form only. Python path: the adapter's parser, as every adapter relies on.

    The second half is the deliberate residual: a consumer that parses JSON itself and calls
    `model_validate` on the dict is on the Python path and gets the coercion. Conformance runs
    the JSON path, and this test is where that decision is stated on bytes.
    """
    for written in ("2026-04-29T06:00:00Z", "2026-04-29T08:00:00+02:00", "2026-04-29T06:00:00"):
        stamp = times.parse(written)
        assert times.render(stamp) == T
        assert times.parse_wire(stamp) == stamp                      # object coercion stays
        with pytest.raises(ValueError, match="RFC 3339 UTC with exactly three decimal places"):
            times.parse_wire(written)
        doc = entity(valid_from=written)
        with pytest.raises(ValidationError, match="RFC 3339 UTC with exactly three decimal"):
            KINDS["entity"].model_validate_json(json.dumps(doc))       # JSON path: refused
        assert KINDS["entity"].model_validate(doc).valid_from == stamp  # Python path: coerced
    assert times.parse_wire(T) == times.parse(T)


# ------------------------------------------------------------- the geometry tag (SEM-001)

@pytest.mark.parametrize("untagged, matches", [
    ({"coordinates": [21.0, 57.0]}, "Point"),               # nesting depth 1: only Point
    ({"coordinates": [[RING]]}, "MultiPolygon"),            # depth 4: only MultiPolygon
], ids=["point-shaped", "multipolygon-shaped"])
def test_a_type_less_geometry_is_the_documented_residual_mismatch(untagged, matches):
    """Schema: accepted (one `oneOf` branch matches; `discriminator` is ignored). Model: refused.

    This is SEM-001 in `docs/cdm-semantic-rules.md`. The schema is NOT changed here — see the module
    docstring — and this test pins the outcome at each level so the mismatch is a stated fact
    with a rule identifier, not a surprise.
    """
    doc = plan_object(geometry=untagged)
    assert schema_errors("plan_object", doc) == []
    model = model_errors("plan_object", doc)
    assert model and all(f.startswith("geometry:") for f in model), model
    assert "discriminator 'type'" in model[0]
    branch = _GENERATED["plan_object"]["$defs"][matches]
    assert "type" not in branch["required"], "if `type` becomes required, retire SEM-001"


@pytest.mark.parametrize("untagged", [
    {"coordinates": [[21.0, 57.0], [22.0, 58.0]]},          # depth 2: LineString or MultiPoint
    {"coordinates": [RING]},                                # depth 3: Polygon or MultiLineString
], ids=["line-or-multipoint", "polygon-or-multilinestring"])
def test_a_type_less_geometry_that_fits_two_branches_is_refused_by_both(untagged):
    """The 2.1.0 Multi* additions made these ambiguous under `oneOf`, so the schema refuses too."""
    doc = plan_object(geometry=untagged)
    assert any(f.startswith("geometry:") for f in schema_errors("plan_object", doc))
    assert any(f.startswith("geometry:") for f in model_errors("plan_object", doc))


def test_a_wrong_tag_is_refused_by_both():
    doc = plan_object(geometry={"type": "Circle", "coordinates": [21.0, 57.0]})
    assert schema_errors("plan_object", doc) and model_errors("plan_object", doc)


# ------------------------------------------------------------- enums, bounds, null, unknown

@pytest.mark.parametrize("path, value", [
    (("entity_type",), "BANANA"),
    (("affiliation",), "friend"),
    (("source", "synthetic"), "true"),
    (("confidence",), 1.5),
    (("confidence",), -0.1),
], ids=["enum-entity_type", "enum-case", "bool-as-string", "confidence>1", "confidence<0"])
def test_enums_and_bounds_are_refused_by_both_validators(path, value):
    schema, model = both("entity", with_path(entity(), path, value))
    key = "/".join(path)
    assert any(f.startswith(f"{key}:") for f in schema), (key, schema)
    assert any(f.startswith(f"{key}:") for f in model), (key, model)


@pytest.mark.parametrize("path, value", [
    (("source", "synthetic"), "true"),
    (("confidence",), "0.5"),
    (("source_ids", 0, "external_id"), 7),
], ids=["string-for-bool", "string-for-number", "number-for-string"])
def test_a_wrongly_typed_scalar_is_refused_by_both_validators(path, value):
    """`strict=True` on the wire: pydantic's lax JSON mode coerces the first two."""
    doc = with_path(entity(), path, value)
    key = "/".join(str(p) for p in path)
    assert any(f.startswith(f"{key}:") for f in schema_errors("entity", doc))
    assert any(f.startswith(f"{key}:") for f in model_errors("entity", doc))


@pytest.mark.parametrize("path, value", [
    (("source", "synthetic"), "true"),
    (("confidence",), "0.5"),
], ids=["string-for-bool", "string-for-number"])
def test_lax_json_coercions_are_off_on_the_wire(path, value):
    """pydantic's lax JSON mode takes these; the schema's `type` does not; strict mode agrees."""
    doc = with_path(entity(), path, value)
    key = "/".join(str(p) for p in path)
    assert any(f.startswith(f"{key}:") for f in schema_errors("entity", doc))
    assert any(f.startswith(f"{key}:") for f in model_errors("entity", doc))
    lax = KINDS["entity"].model_validate_json(json.dumps(doc))       # the coercion, demonstrated
    assert lax is not None


@pytest.mark.parametrize("position", [
    {"lat": 91.0, "lon": 21.0, "position_source": "GNSS"},
    {"lat": 57.0, "lon": -181.0, "position_source": "GNSS"},
    {"lat": 57.0, "lon": 21.0, "position_source": "GNSS", "accuracy_m": -1.0},
], ids=["lat>90", "lon<-180", "accuracy<0"])
def test_position_bounds_are_refused_by_both_validators(position):
    """`position` is nullable, so the schema reports the `anyOf` at the parent path."""
    schema, model = both("entity", entity(position=position))
    assert any(f.startswith("position") for f in schema), schema
    assert any(f.startswith("position/") for f in model), model


def test_an_exclusive_bound_is_exclusive_on_both_sides():
    at_limit = entity(kinematics={"course_deg": 360.0})
    assert both("entity", at_limit)[0] and both("entity", at_limit)[1]
    below = entity(kinematics={"course_deg": 359.9})
    assert both("entity", below) == ([], [])


def test_null_and_absent_are_distinguished_the_same_way_on_both_sides():
    assert both("entity", entity(valid_to=None)) == ([], [])              # nullable, explicit
    assert both("entity", entity()) == ([], [])                           # nullable, absent
    assert both("entity", entity(valid_to=T_LATER)) == ([], [])
    schema, model = both("entity", entity(source=None))                   # required, not nullable
    assert any(f.startswith("source:") for f in schema) and any(f.startswith("source:")
                                                                 for f in model)
    absent = entity()
    del absent["valid_from"]
    schema, model = both("entity", absent)
    assert schema and model


@pytest.mark.parametrize("kind", sorted(BUILDERS))
def test_an_unknown_top_level_field_is_refused_by_both_validators(kind):
    schema, model = both(kind, BUILDERS[kind](vessel_flag="LV"))
    assert any("vessel_flag" in f for f in schema), schema
    assert any("vessel_flag" in f for f in model), model


def test_an_unknown_nested_field_is_refused_and_the_bags_stay_open():
    schema, model = both("entity", with_path(entity(), ("source", "vessel_flag"), "LV"))
    assert any("vessel_flag" in f for f in schema) and any("vessel_flag" in f for f in model)
    assert both("entity", entity(attributes={"vessel_flag": "LV", "n": [1, 2]})) == ([], [])
    assert both("event", event(payload={**PAYLOAD, "vendor_field": 7})) == ([], [])


def test_the_sidc_and_the_ontology_list_are_portable_now():
    """Two rules that were Python-only and have a JSON Schema spelling: `pattern`, `uniqueItems`."""
    schema, model = both("entity", entity(symbol="123"))
    assert any(f.startswith("symbol:") for f in schema) and any(f.startswith("symbol:")
                                                                 for f in model)
    assert both("entity", entity(symbol="10260000000000000000")) == ([], [])
    term = "https://ontology.synapsecommand.example/terms/Runway"
    schema, model = both("entity", entity(ontology_types=[term, term]))
    assert any(f.startswith("ontology_types:") for f in schema), schema
    assert any("SEM-010" in f and "duplicate" in f for f in model), model


# ------------------------------------------------------------- what stays semantic-only

@pytest.mark.parametrize("kind, doc, rule", [
    ("entity", entity(valid_from=T_LATER, valid_to=T), "SEM-007"),
    ("track", track(samples=[{"observed_at": T_LATER, "position": {"lat": 57.0, "lon": 21.0,
                                                                   "position_source": "GNSS"}},
                             {"observed_at": T, "position": {"lat": 57.0, "lon": 21.0,
                                                             "position_source": "GNSS"}}]),
     "SEM-012"),
    ("plan_object", plan_object(geometry=POLYGON,
                                area={"geometry": {"type": "Polygon",
                                                   "coordinates": [[[21.0, 57.0], [22.0, 57.0],
                                                                    [22.0, 58.0]]]}}),
     "SEM-002"),
    ("event", event(payload={"interference_type": "JAMMING"}), "SEM-011"),
], ids=["interval", "track-order", "ring-closure", "payload-shape"])
def test_a_cross_field_rule_is_schema_valid_and_model_refused_with_its_rule_id(kind, doc, rule):
    """The schema cannot say it; the model does, and says which rule. Conformance keeps the two
    verdicts apart — `tests/test_cdm_semantic_corpus.py` runs the whole corpus through it."""
    assert schema_errors(kind, doc) == []
    model = model_errors(kind, doc)
    assert model and any(rule in f for f in model), (rule, model)
