"""The path-bound preservation ledger (audit remediation F02).

The value-presence heuristic (`lossless.value_presence_heuristic`, formerly `unrepresented`)
harvests a SET of normalised scalars and reports the source values that appear nowhere. One
surviving value therefore proves that every source field holding that value survived — which is
the counterexample the audit gave and the first test below reproduces. The ledger binds each
source LEAF (path, array index, occurrence, type) to a declared destination and a declared rule,
and reports what it could not bind, by category, without echoing payload values.

Three layers: the ledger alone (fast, one case per regression the brief lists), deliberately
corrupted adapters run through `harness.run` (one per loss kind, so the wiring is what is
tested and not only the helper), and the reporting — which basis a verdict rests on.
"""
import copy
import json
import pathlib

import pytest

from synapse_cdm import harness, ids, lossless, manifest, suite, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters.pntmap import PntmapAdapter
from synapse_cdm.enums import Affiliation, EntityType
from synapse_cdm.lossless import Mapping
from synapse_cdm.models import Entity
import synapse_cdm

from tests import probe_metadata

PNTMAP_FIXTURES = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures" / "pntmap"


# --- the audit's counterexample -------------------------------------------------------------------

COUNTEREXAMPLE_RAW = {"speed": 12, "heading": 12}
COUNTEREXAMPLE_OUTPUT = [{"speed": 12}]
COUNTEREXAMPLE_MAPPINGS = {"speed": Mapping("*:speed"), "heading": Mapping("*:heading")}


def test_the_heuristic_is_blind_to_the_counterexample_and_is_named_for_it():
    """One surviving 12 satisfies the heuristic for BOTH fields. That is the defect, kept on
    record under a name that says what it is."""
    assert lossless.value_presence_heuristic(COUNTEREXAMPLE_RAW, COUNTEREXAMPLE_OUTPUT) == {}
    assert not hasattr(lossless, "unrepresented"), \
        "the old name would let a caller keep treating the heuristic's empty result as proof"


def test_the_ledger_reports_the_dropped_heading_the_heuristic_missed():
    book = lossless.ledger(COUNTEREXAMPLE_RAW, COUNTEREXAMPLE_OUTPUT, COUNTEREXAMPLE_MAPPINGS)
    assert book.counts["MAPPED"] == 1
    assert book.counts["LOST"] == 1
    (lost,) = book.lost
    assert lost.source_path == "heading"
    assert lost.category == "LOST" and lost.loss == "MISSING"
    assert lost.expected == {"destination": "*:heading", "rule": "identity", "tolerance": None}
    assert lost.observed == {"destination": None, "type": "absent"}
    assert "12" not in json.dumps(book.as_dict()), "diagnostics must not echo payload values"


def test_the_ledger_is_a_partition_of_every_source_leaf():
    raw = {"a": 1, "b": [None, "", {}], "c": {"d": False}}
    book = lossless.ledger(raw, [{"attributes": {"source_extras": raw}}], {})
    assert book.total == 5
    assert sum(book.counts.values()) == 5
    assert book.counts["RESIDUAL"] == 5
    assert sorted(e.source_path for e in book.entries) == ["a", "b[0]", "b[1]", "b[2]", "c.d"]


# --- the fourteen regression cases, on the ledger alone -------------------------------------------

def _entity(**attributes) -> dict:
    return {"object_kind": "entity", "attributes": attributes}


def _one(book: lossless.Ledger, path: str) -> lossless.Entry:
    return next(e for e in book.entries if e.source_path == path)


def test_duplicate_scalar_values_are_two_leaves_and_each_needs_its_own_destination():
    raw = {"speed": 12, "heading": 12}
    book = lossless.ledger(raw, [_entity(speed=12)],
                           {"speed": Mapping("entity:attributes.speed"),
                            "heading": Mapping("entity:attributes.heading")})
    assert _one(book, "speed").category == "MAPPED"
    assert _one(book, "heading").loss == "MISSING"


def test_swapped_fields_are_value_mismatches_at_both_destinations():
    raw = {"lat": 57.5, "lon": 21.8}
    book = lossless.ledger(raw, [_entity(lat=21.8, lon=57.5)],
                           {"lat": Mapping("entity:attributes.lat", "number"),
                            "lon": Mapping("entity:attributes.lon", "number")})
    assert {e.loss for e in book.lost} == {"VALUE_MISMATCH"}
    assert len(book.lost) == 2, "the heuristic would have passed this: both values are present"
    assert lossless.value_presence_heuristic(raw, [_entity(lat=21.8, lon=57.5)]) == {}


def test_changed_units_fail_the_declared_scale_rule():
    raw = {"speed_kt": 10}
    good = lossless.ledger(raw, [_entity(speed_mps=5.14444)],
                           {"speed_kt": Mapping("entity:attributes.speed_mps", "scale",
                                                tolerance=1e-3, params={"factor": 0.514444})})
    assert good.counts["MAPPED"] == 1
    bad = lossless.ledger(raw, [_entity(speed_mps=10)],
                          {"speed_kt": Mapping("entity:attributes.speed_mps", "scale",
                                               tolerance=1e-3, params={"factor": 0.514444})})
    assert _one(bad, "speed_kt").loss == "TRANSFORM_MISMATCH"


def test_a_dropped_repeated_array_element_is_a_multiplicity_loss():
    raw = {"tags": ["a", "a", "b"]}
    mappings = {"tags[*]": Mapping("entity:attributes.tags[*]")}
    assert lossless.ledger(raw, [_entity(tags=["a", "a", "b"])], mappings).counts["LOST"] == 0
    book = lossless.ledger(raw, [_entity(tags=["a", "b"])], mappings)
    assert book.losses["MULTIPLICITY"] == 1, "tags[2] has no destination in a shorter array"
    assert book.counts["LOST"] == 2, "and tags[1] finds 'b' where it expected its own 'a'"


def test_wrong_ordering_is_reported_as_order_and_not_as_a_value_loss():
    raw = {"tags": ["a", "b"]}
    book = lossless.ledger(raw, [_entity(tags=["b", "a"])],
                           {"tags[*]": Mapping("entity:attributes.tags[*]")})
    assert {e.loss for e in book.lost} == {"ORDER"}


def test_false_and_zero_are_different_types():
    raw = {"flag": False, "count": 0}
    book = lossless.ledger(raw, [_entity(flag=0, count=False)],
                           {"flag": Mapping("entity:attributes.flag"),
                            "count": Mapping("entity:attributes.count")})
    assert {e.loss for e in book.lost} == {"TYPE_MISMATCH"}
    assert len(book.lost) == 2


def test_null_is_a_value_and_absent_is_a_loss():
    raw = {"nothing": None}
    kept = lossless.ledger(raw, [_entity(nothing=None)], {"nothing": Mapping("entity:attributes.nothing")})
    assert kept.counts["MAPPED"] == 1
    gone = lossless.ledger(raw, [_entity()], {"nothing": Mapping("entity:attributes.nothing")})
    assert _one(gone, "nothing").loss == "MISSING"
    assert _one(gone, "nothing").observed["type"] == "absent"


def test_empty_strings_and_empty_containers_are_leaves_with_types():
    raw = {"empty": "", "items": [], "detail": {}}
    kept = lossless.ledger(raw, [_entity(empty="", items=[], detail={})],
                           {"empty": Mapping("entity:attributes.empty"),
                            "items": Mapping("entity:attributes.items"),
                            "detail": Mapping("entity:attributes.detail")})
    assert kept.counts["MAPPED"] == 3
    swapped = lossless.ledger(raw, [_entity(empty=None, items={}, detail=[])],
                              {"empty": Mapping("entity:attributes.empty"),
                               "items": Mapping("entity:attributes.items"),
                               "detail": Mapping("entity:attributes.detail")})
    assert {e.loss for e in swapped.lost} == {"TYPE_MISMATCH"} and len(swapped.lost) == 3


def test_nested_repeated_keys_are_addressed_by_their_full_path():
    raw = {"k": {"k": {"k": 1}}}
    book = lossless.ledger(raw, [_entity(k={"k": 1})], {"k.k.k": Mapping("entity:attributes.k.k.k")})
    assert _one(book, "k.k.k").loss == "MISSING"
    assert lossless.ledger(raw, [_entity(k={"k": {"k": 1}})],
                           {"k.k.k": Mapping("entity:attributes.k.k.k")}).counts["MAPPED"] == 1


def test_a_key_holding_a_separator_is_one_token_and_not_a_path():
    raw = {"a.b": 5, "c[0]": 6}
    quoted = {'"a.b"': Mapping('entity:attributes."a.b"'), '"c[0]"': Mapping('entity:attributes."c[0]"')}
    assert lossless.ledger(raw, [_entity(**{"a.b": 5, "c[0]": 6})], quoted).counts["MAPPED"] == 2
    expanded = lossless.ledger(raw, [_entity(a={"b": 5}, c=[6])], quoted)
    assert {e.loss for e in expanded.lost} == {"MISSING"} and len(expanded.lost) == 2
    assert lossless.parse_path('"a.b".c[0]') == ("a.b", "c", 0)
    assert lossless.render_path(("a.b", "c", 0)) == '"a.b".c[0]'


def test_an_unknown_field_is_residual_at_its_own_path_or_it_is_lost():
    raw = {"known": 1, "unknown_extra": "x"}
    mappings = {"known": Mapping("entity:attributes.known")}
    parked = lossless.ledger(raw, [_entity(known=1, source_extras={"unknown_extra": "x"})], mappings)
    assert _one(parked, "unknown_extra").category == "RESIDUAL"
    assert _one(parked, "unknown_extra").observed["destination"] == "#0:attributes.source_extras.unknown_extra"
    dropped = lossless.ledger(raw, [_entity(known=1)], mappings)
    assert _one(dropped, "unknown_extra").loss == "MISSING"


def test_a_residual_flattened_to_dotted_keys_is_an_undeclared_residual():
    raw = {"extra": {"list": ["p", "q"]}}
    intact = lossless.ledger(raw, [_entity(source_extras={"extra": {"list": ["p", "q"]}})], {})
    assert intact.counts["RESIDUAL"] == 2
    flat = lossless.ledger(raw, [_entity(source_extras={"extra.list[0]": "p", "extra.list[1]": "q"})], {})
    assert {e.loss for e in flat.lost} == {"UNDECLARED_RESIDUAL"} and len(flat.lost) == 2
    declared = lossless.ledger(raw, [{"object_kind": "event", "payload": {"source_extras": {"list": ["p", "q"]}}}],
                               {"extra": Mapping("event:payload.source_extras", kind="residual")})
    assert declared.counts["RESIDUAL"] == 2


def test_a_value_in_the_wrong_object_is_wrong_object():
    raw = {"heading": 12}
    objects = [{"object_kind": "entity", "attributes": {}},
               {"object_kind": "event", "attributes": {"heading": 12}}]
    book = lossless.ledger(raw, objects, {"heading": Mapping("entity:attributes.heading")})
    assert _one(book, "heading").loss == "WRONG_OBJECT"
    assert _one(book, "heading").observed["destination"] == "#1:attributes.heading"


def test_a_transformation_declaration_that_the_output_does_not_satisfy_is_a_mismatch():
    raw = {"level": "high"}
    rule = Mapping("entity:attributes.level", "enum_map", params={"table": {"high": "HIGH"}})
    assert lossless.ledger(raw, [_entity(level="HIGH")], {"level": rule}).counts["MAPPED"] == 1
    book = lossless.ledger(raw, [_entity(level="LOW")], {"level": rule})
    assert _one(book, "level").loss == "TRANSFORM_MISMATCH"
    undeclared_word = lossless.ledger({"level": "extreme"}, [_entity(level="HIGH")], {"level": rule})
    assert _one(undeclared_word, "level").loss == "TRANSFORM_MISMATCH", \
        "a word outside the declared table is not covered by the declaration"


# --- the legitimate cases the brief says must keep passing --------------------------------------

def test_a_multi_object_mapping_holds_only_when_every_destination_holds():
    raw = {"when": "2026-04-29T06:12:44Z"}
    both = (Mapping("entity:valid_from", "instant"), Mapping("event:observed_at", "instant"))
    objects = [{"object_kind": "entity", "valid_from": "2026-04-29T06:12:44.000Z"},
               {"object_kind": "event", "observed_at": "2026-04-29T06:12:44.000Z"}]
    assert lossless.ledger(raw, objects, {"when": both}).counts["MAPPED"] == 1
    objects[1]["observed_at"] = "2026-04-29T06:12:45.000Z"
    book = lossless.ledger(raw, objects, {"when": both})
    assert _one(book, "when").loss == "TRANSFORM_MISMATCH"
    assert _one(book, "when").expected["destination"] == "event:observed_at"


def test_authorised_rounding_passes_within_its_tolerance_and_fails_outside_it():
    raw = {"precise": 1.23456}
    rounded = Mapping("entity:attributes.precise", "round", params={"decimals": 3})
    assert lossless.ledger(raw, [_entity(precise=1.235)], {"precise": rounded}).counts["MAPPED"] == 1
    assert _one(lossless.ledger(raw, [_entity(precise=1.23)], {"precise": rounded}),
                "precise").loss == "TRANSFORM_MISMATCH"
    within = Mapping("entity:attributes.precise", "number", tolerance=0.01)
    assert lossless.ledger(raw, [_entity(precise=1.23)], {"precise": within}).counts["MAPPED"] == 1


def test_a_declared_limitation_is_surfaced_as_its_own_category_and_not_hidden():
    raw = {"vendor": {"firmware": "9.9"}, "kept": 1}
    book = lossless.ledger(raw, [_entity(kept=1)], {"kept": Mapping("entity:attributes.kept")},
                           unsupported=["vendor"])
    assert _one(book, "vendor.firmware").category == "DECLARED_LIMITATION"
    assert _one(book, "vendor.firmware").expected["rule"] == "limitation:vendor"
    assert book.counts["LOST"] == 0
    assert book.as_dict()["counts"]["DECLARED_LIMITATION"] == 1


def test_a_free_text_transform_reason_exempts_nothing_from_the_ledger():
    raw = {"speed_kt": 10}
    assert lossless.value_presence_heuristic(raw, [_entity()], {"speed_kt": "converted"}) == {}
    book = lossless.ledger(raw, [_entity()], {"speed_kt": Mapping("entity:attributes.speed_mps", "scale",
                                                                 params={"factor": 0.514444})})
    assert _one(book, "speed_kt").loss == "MISSING"


def test_a_mapping_refuses_an_unknown_rule_and_a_destination_without_a_target():
    with pytest.raises(ValueError):
        Mapping("entity:x", "invent")
    with pytest.raises(ValueError):
        Mapping("x")
    with pytest.raises(ValueError):
        Mapping("entity:x", "scale", kind="residual")


# --- deliberately corrupted adapters, through the harness ---------------------------------------

PROBE_RAW = {
    "speed": 12, "heading": 12, "lat": 57.5, "lon": 21.8, "speed_kt": 10, "level": "high",
    "tags": ["a", "a", "b"], "flag": False, "count": 0, "empty": "", "nothing": None,
    "items": [], "nested": {"k": {"k": 1}}, "a.b": 5, "precise": 1.23456,
    "vendor": {"firmware": "9.9"}, "unknown_extra": "x", "extra": {"list": ["p", "q"]},
}
PROBE_CONSUMED = ("speed", "heading", "lat", "lon", "speed_kt", "level", "tags", "flag", "count",
                  "empty", "nothing", "items", "nested", "a.b", "precise", "vendor")


class _Probe(Adapter):
    """Maps every consumed field to `attributes` by a declared rule and parks the rest.
    Subclasses corrupt ONE thing each, in `mutate`, so each loss kind has one adapter."""
    name = "preservation-probe"
    version = "1.0.0"
    direction = "ingest"
    system = "PROBE"
    fixture_dir = None
    metadata = probe_metadata("preservation-probe", version="1.0.0", limitations=[
        manifest.Limitation(id="no-vendor-block", summary="the vendor block is not mapped",
                            unsupported_paths=["vendor"], severity="low",
                            notes="a declared limitation, surfaced as one"),
    ])
    # The heuristic still runs beside the ledger and still needs its free-text exemptions for
    # a value that changes form; the LEDGER checks the same paths by rule. Both are declared so
    # the probe shows the two readings side by side.
    TRANSFORMS = {"speed_kt": "knots to metres per second (the ledger's scale rule checks it)",
                  "precise": "rounded to three decimals (the ledger's round rule checks it)",
                  "level": "upper-cased enum (the ledger's enum_map rule checks it)",
                  "vendor": "not mapped: a structured Limitation declares the path"}
    MAPPINGS = {
        "speed": Mapping("entity:attributes.speed"),
        "heading": Mapping("entity:attributes.heading"),
        "lat": Mapping("entity:attributes.lat", "number"),
        "lon": Mapping("entity:attributes.lon", "number"),
        "speed_kt": Mapping("entity:attributes.speed_mps", "scale", tolerance=1e-3,
                            params={"factor": 0.514444}),
        "level": Mapping("entity:attributes.level", "enum_map", params={"table": {"high": "HIGH"}}),
        "tags[*]": Mapping("entity:attributes.tags[*]"),
        "flag": Mapping("entity:attributes.flag"),
        "count": Mapping("entity:attributes.count"),
        "empty": Mapping("entity:attributes.empty"),
        "nothing": Mapping("entity:attributes.nothing"),
        "items": Mapping("entity:attributes.items"),
        "nested.k.k": Mapping("entity:attributes.nested.k.k"),
        '"a.b"': Mapping('entity:attributes."a.b"'),
        "precise": Mapping("entity:attributes.precise", "round", params={"decimals": 3}),
    }

    def mutate(self, attributes: dict, raw: dict) -> list | None:
        return None

    def to_cdm(self, raw):
        raw = self._as_parsed(raw) if isinstance(raw, (bytes, bytearray, str)) else raw
        attributes = {
            "speed": raw["speed"], "heading": raw["heading"], "lat": raw["lat"], "lon": raw["lon"],
            "speed_mps": round(raw["speed_kt"] * 0.514444, 5), "level": raw["level"].upper(),
            "tags": list(raw["tags"]), "flag": raw["flag"], "count": raw["count"],
            "empty": raw["empty"], "nothing": raw["nothing"], "items": list(raw["items"]),
            "nested": copy.deepcopy(raw["nested"]), "a.b": raw["a.b"],
            "precise": round(raw["precise"], 3),
            "source_extras": lossless.residual(raw, PROBE_CONSUMED),
        }
        extra = self.mutate(attributes, raw)
        entity = Entity(source=self.source_ref(),
                        source_ids=[{"system": self.system, "external_id": "probe-1"}],
                        entity_id=ids.derive(self.system, "probe-1", kind="entity"),
                        entity_type=EntityType.UNKNOWN, affiliation=Affiliation.UNKNOWN,
                        valid_from=self.now(), attributes=attributes)
        return [entity] + (extra or [])

    @staticmethod
    def _as_parsed(raw):
        return json.loads(bytes(raw).decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)


def _corrupted(kind: str, fn, **overrides):
    return type(f"_Corrupt_{kind}", (_Probe,), {
        "name": f"preservation-probe-{kind.lower()}",
        "metadata": probe_metadata(f"preservation-probe-{kind.lower()}", version="1.0.0",
                                   limitations=list(_Probe.metadata.limitations)),
        "mutate": fn,
        **overrides,
    })


def _drop_heading(self, a, raw):
    del a["heading"]


def _swap(self, a, raw):
    a["lat"], a["lon"] = a["lon"], a["lat"]


def _no_conversion(self, a, raw):
    a["speed_mps"] = raw["speed_kt"]


def _dedupe(self, a, raw):
    a["tags"] = ["a", "b"]


def _reorder(self, a, raw):
    a["tags"] = ["b", "a", "a"]


def _false_to_zero(self, a, raw):
    a["flag"] = 0


def _null_to_absent(self, a, raw):
    del a["nothing"]


def _empty_to_null(self, a, raw):
    a["empty"] = None
    a["items"] = None


def _flatten_nested(self, a, raw):
    a["nested"] = {"k": 1}


def _expand_dotted(self, a, raw):
    del a["a.b"]
    a["a"] = {"b": raw["a.b"]}


def _drop_unknown(self, a, raw):
    del a["source_extras"]["unknown_extra"]


def _flatten_residual(self, a, raw):
    a["source_extras"] = {"unknown_extra": "x", "extra.list[0]": "p", "extra.list[1]": "q"}


def _wrong_enum(self, a, raw):
    a["level"] = "LOW"


def _second_object_holds_it(self, a, raw):
    del a["heading"]
    twin = Entity(source=self.source_ref(),
                  source_ids=[{"system": self.system, "external_id": "probe-2"}],
                  entity_id=ids.derive(self.system, "probe-2", kind="entity"),
                  entity_type=EntityType.UNKNOWN, affiliation=Affiliation.UNKNOWN,
                  valid_from=self.now(), attributes={"heading": raw["heading"]})
    return [twin]


#: (loss kind, the corruption, the source path it shows on, class attributes the case overrides).
#: The WRONG_OBJECT case binds `heading` to the FIRST object by index — with a kind target both
#: entities would be candidates and the twin would satisfy it, which is the point of `#0`.
CORRUPTIONS = [
    ("MISSING", _drop_heading, "heading", {}),
    ("VALUE_MISMATCH", _swap, "lat", {}),
    ("TRANSFORM_MISMATCH", _no_conversion, "speed_kt", {}),
    ("MULTIPLICITY", _dedupe, "tags[2]", {}),
    ("ORDER", _reorder, "tags[0]", {}),
    ("TYPE_MISMATCH", _false_to_zero, "flag", {}),
    ("MISSING", _null_to_absent, "nothing", {}),
    ("TYPE_MISMATCH", _empty_to_null, "empty", {}),
    ("MISSING", _flatten_nested, "nested.k.k", {}),
    ("MISSING", _expand_dotted, '"a.b"', {}),
    ("MISSING", _drop_unknown, "unknown_extra", {}),
    ("UNDECLARED_RESIDUAL", _flatten_residual, "extra.list[0]", {}),
    ("TRANSFORM_MISMATCH", _wrong_enum, "level", {}),
    ("WRONG_OBJECT", _second_object_holds_it, "heading",
     {"MAPPINGS": {**_Probe.MAPPINGS, "heading": Mapping("#0:attributes.heading")}}),
]


@pytest.fixture
def probe_fixtures(tmp_path):
    (tmp_path / "probe.json").write_text(json.dumps(PROBE_RAW))
    return tmp_path


def _run(cls, fixtures) -> dict:
    return harness.run(cls(clock=times.frozen_clock()), fixtures)


def test_the_valid_probe_passes_and_the_report_says_the_verdict_rests_on_the_ledger(probe_fixtures):
    report = _run(_Probe, probe_fixtures)
    (result,) = report["results"]
    assert result["checks"]["lossless"] == "PASS", result["problems"]
    book = result["preservation"]
    assert book["basis"] == "ledger" and book["counts"]["LOST"] == 0
    assert book["counts"]["DECLARED_LIMITATION"] == 1, "vendor.firmware, declared and surfaced"
    assert book["counts"]["RESIDUAL"] == 3, "unknown_extra, extra.list[0], extra.list[1]"
    assert book["counts"]["MAPPED"] == 17
    assert report["preservation"]["basis"] == "ledger"
    text = harness.render_report(report)
    assert "lossless basis: LEDGER" in text and "declared mapping(s)" in text
    assert set(result["checks"]) == set(harness._COLUMNS), "no seventh column: the ledger is folded in"


@pytest.mark.parametrize("kind,mutation,path,overrides", CORRUPTIONS,
                         ids=[f"{k}:{p}" for k, _, p, _o in CORRUPTIONS])
def test_each_corruption_fails_the_lossless_column_with_its_own_category(probe_fixtures, kind, mutation,
                                                                          path, overrides):
    report = _run(_corrupted(f"{kind}_{mutation.__name__}", mutation, **overrides), probe_fixtures)
    (result,) = report["results"]
    assert result["checks"]["lossless"] == "FAIL"
    assert result["verdict"] == "FAIL"
    book = result["preservation"]
    assert book["losses"][kind] >= 1, book["diagnostics"]
    hit = next(d for d in book["diagnostics"] if d["source_path"] == path)
    assert hit["category"] == "LOST" and hit["loss"] == kind, hit
    assert set(hit) == {"source_path", "category", "loss", "expected", "observed"}
    assert set(hit["expected"]) == {"destination", "rule", "tolerance"}
    assert set(hit["observed"]) == {"destination", "type"}
    problems = "\n".join(result["problems"])
    assert f"lossless: {path}: LOST/{kind}" in problems
    assert "57.5" not in json.dumps(book) and "probe-1" not in json.dumps(book), \
        "the ledger names paths and types, never values"


def test_the_heuristic_passes_most_of_the_corruptions_the_ledger_catches(probe_fixtures):
    """The reason the ledger exists, measured on the wiring: for these the old check is green.

    `speed_kt` and `level` are the free-text `TRANSFORMS` exemption hiding a wrong conversion;
    `nothing` and `empty` are the heuristic's "uninteresting" filter; the rest are its set
    semantics. `flag` (`false` written as `0`) it does catch, and that is recorded here too.
    """
    blind = []
    for kind, mutation, path, overrides in CORRUPTIONS:
        cls = _corrupted(f"blind_{mutation.__name__}", mutation, **overrides)
        objects = harness._dump(cls(clock=times.frozen_clock()).to_cdm(PROBE_RAW))
        if not lossless.value_presence_heuristic(PROBE_RAW, objects, cls.TRANSFORMS):
            blind.append(path)
    assert {"heading", "lat", "tags[2]", "tags[0]", "speed_kt", "level", "nothing", "empty",
            '"a.b"'} <= set(blind), blind
    assert "flag" not in blind
    assert len(blind) >= 9


# --- reporting: which basis a verdict rests on ---------------------------------------------------

class _Undeclared(_Probe):
    name = "preservation-undeclared"
    metadata = probe_metadata("preservation-undeclared", version="1.0.0")
    MAPPINGS = {}


def test_an_adapter_without_mappings_is_judged_by_the_heuristic_and_the_report_says_so(probe_fixtures):
    report = _run(_Undeclared, probe_fixtures)
    (result,) = report["results"]
    assert result["checks"]["lossless"] == "PASS"
    assert result["preservation"] == {"basis": "heuristic", "declared_mappings": 0}
    assert report["preservation"]["basis"] == "heuristic"
    text = harness.render_report(report)
    assert "lossless basis: HEURISTIC" in text and "NOT proof of preservation" in text


def test_the_suite_carries_the_basis_under_check_d_and_the_ledger_under_the_loss_report(probe_fixtures):
    declared = suite.run(_Probe(clock=times.frozen_clock()), probe_fixtures)
    assert declared["checks"]["D"]["verdict"] == "PASS"
    assert declared["checks"]["D"]["details"]["basis"] == "ledger"
    book = declared["loss_report"]["ledger"]
    assert book["basis"] == "ledger" and book["fixtures"] == 1 and book["counts"]["LOST"] == 0
    assert set(book["counts"]) == set(lossless.LEDGER_CATEGORIES)
    assert set(book["losses"]) == set(lossless.LOSS_KINDS)
    assert "PRESERVATION LEDGER (F02)" in suite.render_report(declared)

    undeclared = suite.run(_Undeclared(clock=times.frozen_clock()), probe_fixtures)
    assert undeclared["checks"]["D"]["details"]["basis"] == "heuristic"
    assert undeclared["loss_report"]["ledger"]["basis"] == "heuristic"
    assert "not run — the adapter declares no MAPPINGS" in suite.render_report(undeclared)

    broken = suite.run(_corrupted("suite_missing", _drop_heading)(clock=times.frozen_clock()),
                       probe_fixtures)
    assert broken["checks"]["D"]["verdict"] == "FAIL"
    assert broken["loss_report"]["ledger"]["losses"]["MISSING"] == 1
    assert broken["loss_report"]["ledger"]["diagnostics"][0]["source_path"] == "heading"
    assert broken["result"] == "NON-CONFORMANT"


def test_the_reference_adapter_declares_mappings_and_every_fixture_leaf_is_bound():
    """pntmap is the one shipped adapter reassessed under the ledger in F02's session; the
    other thirteen are recorded in the register as heuristic-only."""
    report = harness.run(PntmapAdapter(clock=times.frozen_clock()), PNTMAP_FIXTURES)
    assert report["preservation"]["basis"] == "ledger"
    assert report["preservation"]["declared_mappings"] == len(PntmapAdapter.MAPPINGS) == 16
    for result in report["results"]:
        book = result["preservation"]
        assert book["counts"]["LOST"] == 0, (result["fixture"], book["diagnostics"])
        assert book["counts"]["MAPPED"] >= 9, result["fixture"]
        assert book["total"] == sum(book["counts"].values())


# --- the index-bound target `#[*]` (2026-09-20, adapter expansion phase 1) -----------------------
#
# A one-object-per-record payload cannot name its objects by kind (every feature is the same kind)
# or by a fixed `#N` (the count is the payload's), and `*` credits a value that landed on the wrong
# record's object. `#[*]` binds the object index to the source key's first `[*]`.

TWO_RECORDS = {"features": [{"id": "A", "properties": {"name": "north", "n": 7}},
                            {"id": "B", "properties": {"name": "south", "n": 7}}]}
INDEX_BOUND = {
    "features[*].id": Mapping("#[*]:source_ids[0].external_id", "text"),
    "features[*].properties.n": Mapping("#[*]:residual.data.properties.n", "number"),
    "features[*]": Mapping("#[*]:residual.data", kind="residual"),
}


def _record(external_id, **props):
    return {"object_kind": "plan_object", "source_ids": [{"system": "T", "external_id": external_id}],
            "residual": {"namespace": "T", "data": {"properties": props}}}


def test_the_index_bound_target_holds_each_record_to_its_own_object():
    book = lossless.ledger(TWO_RECORDS, [_record("A", name="north", n=7),
                                         _record("B", name="south", n=7)], INDEX_BOUND)
    assert book.lost == ()
    assert _one(book, "features[1].properties.name").observed["destination"] == \
        "#1:residual.data.properties.name"
    assert _one(book, "features[1].properties.n").observed["destination"] == \
        "#1:residual.data.properties.n"


def test_a_value_on_the_other_records_object_is_wrong_object_under_the_index_bound_target():
    """The repeated-identical-scalar case: both records carry `n: 7`, so a `*` target would be
    satisfied by either object. `#[*]` is not: object 1 carries nothing and object 0 carries
    record 1's name, and the ledger says WRONG_OBJECT rather than MAPPED."""
    swapped = [_record("A", name="south", n=7), _record("B", name="north", n=7)]
    book = lossless.ledger(TWO_RECORDS, swapped, INDEX_BOUND)
    assert {e.source_path for e in book.lost} == \
        {"features[0].properties.name", "features[1].properties.name"}
    assert _one(book, "features[0].properties.name").loss == "VALUE_MISMATCH"
    dropped = [_record("A", name="north", n=7),
               {**_record("B", n=7), "residual": {"namespace": "T", "data": {"properties": {"n": 7}}}}]
    book = lossless.ledger(TWO_RECORDS, dropped, INDEX_BOUND)
    assert [e.source_path for e in book.lost] == ["features[1].properties.name"]
    # Object 1 holds nothing at the path and object 0 holds record 0's name there, so the
    # ledger's standing diagnosis is WRONG_OBJECT ("is it in an object of another kind?"), which
    # names where a reader should look; MISSING is what it reads when no object holds the path.
    assert _one(book, "features[1].properties.name").loss == "WRONG_OBJECT"
    star = {k: Mapping(m.to.replace("#[*]", "*"), m.rule, kind=m.kind) for k, m in INDEX_BOUND.items()}
    assert lossless.ledger(TWO_RECORDS, swapped, star).lost == (), \
        "the `*` target is blind to the swap, which is why `#[*]` exists"


def test_the_first_bound_index_is_the_object_and_the_rest_go_to_the_path():
    raw = {"features": [{"coordinates": [[1.0, 2.0], [3.0, 4.0]]}]}
    objects = [{"object_kind": "plan_object", "geometry": {"coordinates": [[1.0, 2.0], [3.0, 4.0]]}}]
    book = lossless.ledger(raw, objects, {
        "features[*].coordinates[*][*]": Mapping("#[*]:geometry.coordinates[*][*]", "number")})
    assert book.lost == ()
    assert _one(book, "features[0].coordinates[1][0]").observed["destination"] == \
        "#0:geometry.coordinates[1][0]"


def test_the_index_bound_target_is_refused_on_a_key_that_binds_no_index():
    with pytest.raises(ValueError, match="binds no \\[\\*\\]"):
        lossless.ledger({"id": "A"}, [_record("A")], {"id": Mapping("#[*]:source_ids[0].external_id")})


def test_an_index_past_the_output_is_a_loss_and_not_a_crash():
    """A second record whose object was never produced: no candidate object, and the ledger
    reports the leaf LOST — WRONG_OBJECT where another object carries the path (object 0's
    `source_ids[0].external_id`), MISSING where none does."""
    book = lossless.ledger(TWO_RECORDS, [_record("A", name="north", n=7)], INDEX_BOUND)
    assert _one(book, "features[1].id").category == "LOST"
    assert _one(book, "features[1].id").loss == "WRONG_OBJECT"
    assert _one(book, "features[1].properties.name").category == "LOST"


# --- the unbound wildcard `[_]` (2026-09-21, adapter expansion phase 3) --------------------------
#
# `_substitute` hands bound indices to a destination's `[*]`s first to first. An object under a
# NESTED repeatable container — a C2SIM unit sits under `ObjectDefinitions[*].Entity[*]` and its
# own lists under that — has destinations with fewer `[*]` than the source key binds, and the
# outermost index would land in the innermost list. `[_]` matches an index and binds nothing.

NESTED = {"groups": [{"items": [{"id": "A", "values": [1.5, 2.5]}]},
                     {"items": [{"id": "B", "values": [3.5]}]}]}


def _typed(external_id, values):
    return {"object_kind": "entity", "source_ids": [{"system": "T", "external_id": external_id}],
            "attributes": {"values": values}}


def test_the_unbound_wildcard_matches_an_index_and_binds_nothing():
    book = lossless.ledger(NESTED, [_typed("A", [1.5, 2.5]), _typed("B", [3.5])], {
        "groups[_].items[_].id": Mapping("entity:source_ids[0].external_id", "text"),
        "groups[_].items[_].values[*]": Mapping("entity:attributes.values[*]", "number")})
    assert book.lost == ()
    assert _one(book, "groups[1].items[0].values[0]").observed["destination"] == \
        "#1:attributes.values[0]"


def test_binding_the_outer_container_would_put_its_index_into_the_inner_list():
    """The defect `[_]` exists for, shown on the same payload: with every container bound, the
    first bound index (the group's) is what the destination's one `[*]` receives."""
    book = lossless.ledger(NESTED, [_typed("A", [1.5, 2.5]), _typed("B", [3.5])], {
        "groups[_].items[_].id": Mapping("entity:source_ids[0].external_id", "text"),
        "groups[*].items[*].values[*]": Mapping("entity:attributes.values[*]", "number")})
    assert {e.source_path for e in book.lost} == {"groups[0].items[0].values[1]",
                                                  "groups[1].items[0].values[0]"}
    assert _one(book, "groups[1].items[0].values[0]").expected["destination"] == \
        "entity:attributes.values[1]"


def test_the_unbound_wildcard_round_trips_through_the_path_grammar_and_is_refused_in_a_destination():
    tokens = lossless.parse_path("groups[_].items[*].id")
    assert tokens[1] is lossless.UNBOUND and tokens[3] is lossless.WILD
    assert lossless.render_path(tokens) == "groups[_].items[*].id"
    with pytest.raises(ValueError, match="belongs in a SOURCE key only"):
        Mapping("entity:attributes.values[_]", "number")


# --- the `numeric_text` rule (2026-09-21, adapter expansion phase 3) -----------------------------
#
# Every leaf of an XML twin is text, an `xs:double` included. `number` refuses a text source on
# purpose; the XML reading is its own rule, so the two cannot be confused.

def test_numeric_text_binds_the_text_of_a_number_to_the_number_it_denotes():
    raw = {"Latitude": "58.5125", "Speed": "0", "Heading": " 270.5 "}
    objects = [{"object_kind": "entity", "attributes": {"lat": 58.5125, "speed": 0.0, "heading": 270.5}}]
    book = lossless.ledger(raw, objects, {
        "Latitude": Mapping("entity:attributes.lat", "numeric_text"),
        "Speed": Mapping("entity:attributes.speed", "numeric_text"),
        "Heading": Mapping("entity:attributes.heading", "numeric_text")})
    assert book.lost == ()


def test_numeric_text_refuses_what_number_refuses_and_number_still_refuses_text():
    raw = {"Latitude": "58.5125", "Word": "north", "Nan": "nan"}
    objects = [{"object_kind": "entity", "attributes": {"lat": 58.5, "word": 1.0, "nan": 0.0}}]
    book = lossless.ledger(raw, objects, {
        "Latitude": Mapping("entity:attributes.lat", "numeric_text"),
        "Word": Mapping("entity:attributes.word", "numeric_text"),
        "Nan": Mapping("entity:attributes.nan", "numeric_text")})
    assert {e.source_path for e in book.lost} == {"Latitude", "Word", "Nan"}
    assert _one(book, "Latitude").loss == "TRANSFORM_MISMATCH"
    strict = lossless.ledger({"Latitude": "58.5125"}, [{"object_kind": "entity", "attributes": {"lat": 58.5125}}],
                             {"Latitude": Mapping("entity:attributes.lat", "number")})
    assert [e.source_path for e in strict.lost] == ["Latitude"], "a text source is not a `number`"
