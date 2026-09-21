"""GeoJSON (RFC 7946) Feature / FeatureCollection <-> CDM. Adapter #16, the fifth bidirectional
one, and the FIRST to declare `residual: structured` — the origin-identifying container
ARCHITECTURE.md §5 gives to every adapter written after the fourteen.

WHAT A FEATURE BECOMES, AND WHAT IT DOES NOT
--------------------------------------------
The default mapping profile is `geo-object/1`: one Feature becomes one `PlanObject` of type
`ANNOTATION` — geographic content with a geometry and no operational meaning. NOTHING in
`properties` is promoted to a canonical field. A property named `type`, `name`, `status` or
`colour` is exactly as opaque as one named `zxq`: reading affiliation, entity class or a label out
of an ordinary property would be an inference made inside a translator, invisible to the audit
trail, and wrong the first time a dataset's `status: "hostile"` turns out to describe a weather
front. The properties ride through, whole and typed, in the residual; a versioned mapping profile
that gives them operational meaning is a separate, named thing this adapter does not implement.

A Feature whose `geometry` is `null` cannot be a `PlanObject` (geometry is required there — an
overlay with no drawing is nothing to draw), so it becomes an `Entity` of type `OVERLAY_OBJECT`
with `position: None`, affiliation UNKNOWN and no symbol: the faithful representation of "a thing
the source describes at no location". That path needs a `valid_from`, which the source does not
state, and so it needs the caller's as-of context (below); without one the document is refused
rather than stamped with the epoch, the clock or the file's mtime.

THE RESIDUAL, AND WHY ITS SHAPE IS THE SOURCE'S
-----------------------------------------------
`Residual.data` mirrors the document: `document` is the top-level object without what became
canonical — for a FeatureCollection that is its `type`, `bbox` and every foreign member, and for a
bare Feature it is the Feature itself minus its geometry's `type` and `coordinates` — and
`feature` (collection form only) is the record: `type`, `id`, `bbox`, `properties` (including
`null`), foreign members, and the geometry's own extra members under `geometry` when it had any.
The geometry's `type` and `coordinates` are the only leaves that leave the residual, because they
are the only leaves the CDM models. Every other leaf is at the relative path the ledger looks for
it at, so `MAPPINGS` is checkable rather than descriptive.

IDENTITY: THE NAMESPACE AND THE FALLBACK ARE THE CALLER'S, NEVER RANDOM
-----------------------------------------------------------------------
`object_id` / `entity_id` is uuid5 over (namespace, key, "feature") — `ids.derive`, the same
function every adapter uses — where the namespace is `GeoJSON` or `GeoJSON:<dataset>` when the
caller names a dataset, and the key is the feature's `id` as JSON text, so a numeric `7` and a
string `"7"` are two identities and `source.original_id` shows which. A feature with no `id`
falls to the caller's chosen policy:

    refuse          (default) the document is refused; nothing is guessed
    record-index    key = the feature's 0-based position. Deterministic and NOT stable across
                    dataset updates: an insertion or deletion shifts every later feature
    property:<name> key = the named property's string or number value. Stable exactly as long
                    as the source keeps that property stable; a feature lacking it is refused

Both non-default policies say what they are in `source.transformations` on every object they
key, because a consumer accumulating features across updates has to know whether the id it is
keying on can move.

WHAT IS REFUSED, BY NAME
------------------------
A `crs` member anywhere (RFC 7946 §4 removed it; a document carrying one is the 2008
specification's profile, which this adapter does not implement — strip it after confirming the
data is WGS84 longitude/latitude, never relabel a projected dataset). A `GeometryCollection`
(`geo.py` refuses it, deliberately). A bare geometry at the top level (no id, no properties: wrap
it in a Feature). An empty `coordinates` array (the RFC lets a processor read it as null; this
one does not turn a stated geometry into an absent one). A non-finite number anywhere. A feature
past `GEOJSON_MAX_FEATURES`, a position past `GEOJSON_MAX_POSITIONS`, a document past
`GEOJSON_MAX_INPUT_BYTES` or `GEOJSON_MAX_DEPTH`. Nothing is truncated, repaired or filtered.

RING ORIENTATION (RFC 7946 §3.1.6)
----------------------------------
Exterior rings SHOULD be counterclockwise and holes clockwise, and the same section says parsers
SHOULD NOT reject a Polygon that ignores the rule. Both halves are honoured: a ring is kept in the
order it arrived, never reversed, and every ring that breaks the rule is named in
`source.transformations` and by `validate_source()` so the departure is reported, not repaired.

BOUNDING BOXES
--------------
`bbox` is kept verbatim in the residual at every level it appears. The `geo-object/1` profile
projects no canonical `BoundingBox`: `PlanObject` carries bounds only inside an `Area`, and
`geo.BoundingBox` refuses the one form RFC 7946 §5.2 permits and a named-field box cannot carry —
a box crossing the antimeridian, `west > east`. Every bbox is noted in `source.transformations`;
an antimeridian-crossing one is noted as such.

EGRESS AND THE TWO PROFILES
---------------------------
`from_cdm` emits a FeatureCollection (or a Feature, when the one object came from a bare Feature)
under one of two export profiles chosen at construction:

    generic     features rebuilt from the residual, verbatim; a record from another adapter or
                a freshly constructed one gets `id` = its CDM identifier, its geometry and
                `properties: {}` — generic GeoJSON is not claimed to carry any semantics
    exchange    `synapsecommand-exchange/1`: the same, plus namespace-separated `sc:*` properties
                carrying kind, identifiers, provenance and as-of, and an `sc:profile` member on
                the collection. A source property already named `sc:...` is never overwritten —
                the export is refused

SEMANTIC ROUND-TRIP EQUIVALENCE, DEFINED
----------------------------------------
Two GeoJSON documents are equivalent when: the top-level `type` agrees; the feature sequence has
the same length and ORDER; each feature's `id` is equal as a JSON value (a number is not a
string); each geometry's `type` agrees and its `coordinates` are equal element by element as
numbers with the same nesting and the same position arity (an integer `1` and a float `1.0` are
the same number); a `null` geometry stays `null`; `properties` are equal as JSON values with
`null` kept, array order kept and object key order ignored; every foreign member at every level
is equal as a JSON value; every `bbox` is equal element by element. Object key order, whitespace
and number spelling are outside the equivalence: egress writes `json.dumps(sort_keys=True,
indent=2)`, ARCHITECTURE.md §6.2's canonical form.

PARSER LIMITS
-------------
Size before the depth scan, the depth scan before `json.loads` (`adapter.enforce_input_bound`,
`adapter.enforce_depth_bound`, wrapped round `to_cdm` at class definition); the feature count and
the position count on the parsed document before any canonical object is built. A payload past a
bound is refused whole.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import math
from typing import Any

from synapse_cdm import ids, lossless, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.enums import Affiliation, EntityType, ObjectType
from synapse_cdm.manifest import (AdapterMetadata, Capabilities, ClaimStatus, Direction,
                                   Evidence, FormatRef, LicenseClass, LimitBasis, LimitKind,
                                   Limitation, Limits, Maturity, MaturityLevel, Residual,
                                   UnknownFields, WireBinding)
from synapse_cdm.models import CDMBase, Entity, PlanObject, SourceRef, TemporalValidity

SYSTEM = "GeoJSON"

#: The default mapping profile: a Feature is geographic content and nothing more.
MAPPING_PROFILE = "geo-object/1"

#: The two export profiles `from_cdm` writes, and the prefix the second one reserves.
EXPORT_GENERIC = "generic"
EXPORT_EXCHANGE = "synapsecommand-exchange/1"
EXPORT_PROFILES = (EXPORT_GENERIC, EXPORT_EXCHANGE)
EXCHANGE_PREFIX = "sc:"

#: The identity fallbacks for a feature with no `id` (module docstring). `property:<name>` is
#: spelled with its name and matched by prefix.
IDENTITY_REFUSE = "refuse"
IDENTITY_RECORD_INDEX = "record-index"
IDENTITY_PROPERTY_PREFIX = "property:"

#: The six geometry types the CDM models (`geo.Geometry`), in RFC 7946 §3.1's order.
GEOMETRY_TYPES = ("Point", "MultiPoint", "LineString", "MultiLineString", "Polygon",
                  "MultiPolygon")
#: How many arrays deep the positions of each type sit below `coordinates`.
_POSITION_DEPTH = {"Point": 0, "MultiPoint": 1, "LineString": 1, "MultiLineString": 2,
                   "Polygon": 2, "MultiPolygon": 3}

# The four declared bounds. Each is an IMPLEMENTATION CAP — RFC 7946 states no maximum for any
# of them — and each is declared in the metadata below FROM its constant so the number the
# manifest publishes is the number that is enforced.
#
# 8 MiB of octets: eight times the JSON adapters' 1 MiB, because a FeatureCollection is a
# dataset rather than a message — the largest fixture here is under 4 KiB and a synthetic
# municipal layer of twenty thousand small features serialises to about 2 MiB.
GEOJSON_MAX_INPUT_BYTES = 8_388_608
# 128 containers deep, derived the way `pntmap` derived its 64: a MultiPolygon feature in a
# collection nests eight containers (collection, features, feature, geometry, coordinates, and
# three more arrays), the deepest JSON document shipped under `fixtures/geojson/`, goldens
# included, nests nine, and the repository's rule (`tests/test_cdm_parser_safety.py`) keeps a
# bound at least eight times the deepest shipped document; properties may nest freely inside
# it. Every walk after the parse recurses once per level and stays far under the interpreter's
# limit.
GEOJSON_MAX_DEPTH = 128
# 20 000 features: one canonical object per feature, so this is §3.5's `max_objects`, checked
# on the parsed document's `features` length before a single object is built.
GEOJSON_MAX_FEATURES = 20_000
# 500 000 positions across the whole document: a position is a small list of floats and a
# `Polygon` validator visits every one, so the count is taken during the structural walk and
# the document is refused at the position that crosses it, before any model is constructed.
GEOJSON_MAX_POSITIONS = 500_000


class FeatureCountExceeded(ValueError):
    """A FeatureCollection with more features than `GEOJSON_MAX_FEATURES`. A `ValueError`, like
    every refusal here, so the conformance suite reads it as a refusal and not a crash."""


class PositionCountExceeded(ValueError):
    """A document with more positions than `GEOJSON_MAX_POSITIONS`."""


@dataclasses.dataclass(frozen=True)
class AsOf:
    """The caller's as-of context: the instant a static dataset is a snapshot of, and WHY.

    A GeoJSON file states no time. The CDM's `PlanObject` needs none, so the context is optional
    for a feature with geometry and lands, when given, at `validity.observed_at` — §27's "when the
    source saw it", the closest of the four to a snapshot instant. `Entity` (the null-geometry
    path) needs `valid_from`, so there the context is REQUIRED. `basis` is prose and is recorded
    in `source.transformations` on every object the instant reaches, because a time the caller
    supplied is a claim the caller made and the object must say so.
    """

    instant: _dt.datetime
    basis: str

    def __post_init__(self) -> None:
        instant = times.parse(self.instant) if isinstance(self.instant, str) else self.instant
        if not isinstance(instant, _dt.datetime) or instant.tzinfo is None:
            raise ValueError("AsOf.instant must be an RFC 3339 text or an aware datetime")
        object.__setattr__(self, "instant", instant)
        if not isinstance(self.basis, str) or len(self.basis.strip()) < 8:
            raise ValueError("AsOf.basis must say, in words, where the instant came from — the "
                             "dataset's own published date, a download time, an operator's "
                             "statement — because the object records it")


def _refuse_constant(name: str) -> Any:
    raise ValueError(f"GeoJSON refuses {name}: RFC 7946 §3.1.1 positions and RFC 8259 numbers are "
                     "finite, and a NaN or an infinity has no place on a map")


def ring_orientation(ring: list) -> str:
    """`counterclockwise`, `clockwise` or `degenerate`, by the signed shoelace area of the ring
    in the [lon, lat] plane — the reading RFC 7946 §3.1.6's right-hand rule is stated in."""
    area = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = float(ring[i][0]), float(ring[i][1])
        x2, y2 = float(ring[i + 1][0]), float(ring[i + 1][1])
        area += x1 * y2 - x2 * y1
    if area > 0:
        return "counterclockwise"
    if area < 0:
        return "clockwise"
    return "degenerate"


def right_hand_rule_departures(geometry: dict) -> list[str]:
    """Every ring of a Polygon or MultiPolygon that does not follow RFC 7946 §3.1.6, named.
    Empty for any other type."""
    kind = geometry.get("type")
    if kind == "Polygon":
        polygons = [geometry.get("coordinates") or []]
    elif kind == "MultiPolygon":
        polygons = list(geometry.get("coordinates") or [])
    else:
        return []
    out: list[str] = []
    for p, polygon in enumerate(polygons):
        for r, ring in enumerate(polygon):
            if not isinstance(ring, list) or len(ring) < 4:
                continue
            orientation = ring_orientation(ring)
            wanted = "counterclockwise" if r == 0 else "clockwise"
            if orientation != wanted:
                where = f"part {p} ring {r}" if kind == "MultiPolygon" else f"ring {r}"
                role = "exterior" if r == 0 else "hole"
                out.append(f"{where} ({role}) is {orientation}; RFC 7946 §3.1.6 asks for "
                           f"{wanted} (a SHOULD) and lets a parser accept either — kept as sent, "
                           "not reversed")
    return out


def bbox_note(bbox: Any, where: str) -> str | None:
    """The `source.transformations` line for a bbox, or None for none. Names the antimeridian
    case — RFC 7946 §5.2's `west > east` — which `geo.BoundingBox` refuses by construction."""
    if bbox is None:
        return None
    note = (f"bbox: kept verbatim at {where}; the {MAPPING_PROFILE} profile projects no canonical "
            "BoundingBox (PlanObject carries bounds only inside an Area)")
    if isinstance(bbox, list) and len(bbox) in (4, 6) and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in bbox):
        west, east = bbox[0], bbox[2] if len(bbox) == 4 else bbox[3]
        if west > east:
            note += (f" — and this box crosses the antimeridian (west {west} > east {east}, "
                     "RFC 7946 §5.2), a form geo.BoundingBox refuses because the same four "
                     "numbers also read as a box that covers everything else")
    return note


#: The refusal for a JSON document of the wrong SHAPE at the top level.
_NOT_AN_OBJECT = ("GeoJSON payload is a JSON {kind}, not an object. RFC 7946 §3's GeoJSON object "
                  "is a JSON object with a `type` member; an array, a string, a number or null is "
                  "not one and is refused rather than read")


class GeojsonAdapter(Adapter):
    name = "geojson"
    version = "1.0.0"
    direction = "bidirectional"
    system = SYSTEM

    #: Adapter API v2's declaration (ARCHITECTURE.md §3). Licence class OPEN: RFC 7946 is an IETF
    #: RFC, published under the IETF Trust's provisions, freely retrievable and freely implemented.
    metadata = AdapterMetadata(
        id="geojson",
        name="GeoJSON",
        adapter_version="1.0.0",
        format=FormatRef(name="GeoJSON", version="RFC 7946 (August 2016)"),
        binding=WireBinding.STANDARD,
        direction=Direction.BIDIRECTIONAL,
        license_class=LicenseClass.OPEN,
        maturity=Maturity(
            level=MaturityLevel.L4,
            basis="L4 ROUND-TRIP VERIFIED, from evidence that runs today. The harness's "
                  "`translate`, `schema` and `provenance` checks are PASS on every fixture of "
                  "this adapter (L1 to L3). Its `lossless` column rests on the PATH-BOUND LEDGER "
                  "and not on the heuristic alone: this adapter declares `MAPPINGS` for every "
                  "source leaf — geometry type and coordinates at every nesting depth, the "
                  "feature id, and residual subtrees for properties, bbox and every foreign "
                  "member at every level — with the `#[*]` target holding each feature's leaves "
                  "to its own object, and the ledger reports no LOST leaf on any fixture. Its "
                  "`roundtrip` column is PASS on every fixture under the `values` tolerance "
                  "(`ROUNDTRIP_TOLERANCE`) the class declares — the comparison the harness makes "
                  "for every JSON emitter: `from_cdm` rebuilds each "
                  "feature from the canonical geometry and the structured residual and no source "
                  "value is absent from what it emits, so `synapse conformance run --adapter "
                  "geojson` computes E = PASS and D on the ledger basis. The adapter's own "
                  "statement of the round-trip claim, under the module docstring's definition of "
                  "semantic equivalence, is "
                  "tests/test_cdm_geojson_adapter.py::test_semantic_round_trip_of_every_fixture. "
                  "L5 is NOT declared: the rung above L4 rests on `M` (streaming) being "
                  "inapplicable, and a rung passed vacuously is not a rung declared "
                  "(ARCHITECTURE.md §3.6, rule 4).",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest", "egress"],
            message_types=[
                "RFC 7946 Feature — one feature becomes one ANNOTATION PlanObject, or an "
                "OVERLAY_OBJECT Entity with no position when its geometry is null",
                "RFC 7946 FeatureCollection — one object per feature, in the collection's order, "
                "with the collection's own members kept in every object's residual",
                "FeatureCollection or Feature on egress, under the `generic` or the "
                "`synapsecommand-exchange/1` export profile",
            ],
            limits=Limits(
                max_input_bytes=GEOJSON_MAX_INPUT_BYTES,
                max_depth=GEOJSON_MAX_DEPTH,
                max_objects=GEOJSON_MAX_FEATURES,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_decompressed_bytes":
                        "this adapter accepts no archived or compressed payload, so there is "
                        "no expansion to bound",
                    "max_parse_seconds":
                        "no wall-clock bound is enforced by this adapter; the conformance "
                        "suite's parser worker kills a decode that overruns its deadline, and "
                        "the three bounds above make every walk in this module linear in a "
                        "bounded input",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "RFC 7946 states no maximum document size. 8 MiB "
                            "(`GEOJSON_MAX_INPUT_BYTES`, `adapters/geojson.py`) is chosen on "
                            "2026-09-20 as eight times the JSON message adapters' 1 MiB, because a "
                            "FeatureCollection is a dataset rather than a message: the largest "
                            "fixture in `fixtures/geojson/` is under 4 KiB and twenty thousand "
                            "small synthetic features serialise to about 2 MiB. This is an "
                            "IMPLEMENTATION CAP and is NOT the format's normative maximum."),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the payload is measured and refused "
                            "before any decoder in this module runs"),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "RFC 7946 states no maximum nesting; a MultiPolygon feature inside a "
                            "collection nests eight containers, the deepest JSON document shipped "
                            "under `fixtures/geojson/` (goldens included) nests nine, and "
                            "`properties` may nest freely. 128 (`GEOJSON_MAX_DEPTH`, "
                            "`adapters/geojson.py`) is chosen on 2026-09-20 for `pntmap`'s reason "
                            "and by the repository's rule of at least eight times the deepest "
                            "shipped document: every walk after the parse recurses once per level "
                            "and on CPython 3.11 `json.loads` itself raises `RecursionError` a "
                            "little under a thousand containers deep (`adapter.InputTooDeep`), so "
                            "the bound is read off the characters before the decoder runs. This "
                            "is an IMPLEMENTATION CAP and is NOT the format's normative maximum."),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_depth_bound` beside `enforce_input_bound` (`adapter.py`, "
                            "`_bind_input_bound`): JSON text is measured off its characters by "
                            "`json_nesting_depth` and a parsed document off its containers by "
                            "`container_depth`, before `_as_document` or `json.loads` runs; past "
                            "the bound the wrapper raises `InputTooDeep`, a `ValueError` naming "
                            "both numbers"),
                        test="tests/test_cdm_parser_safety.py::test_the_json_adapters_declare_a_depth_bound_and_refuse_a_document_past_it",
                    ),
                    "max_objects": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "RFC 7946 states no maximum feature count. One feature becomes one "
                            "canonical object, so `max_objects` is the feature count: 20 000 "
                            "(`GEOJSON_MAX_FEATURES`, `adapters/geojson.py`), chosen on 2026-09-20 "
                            "as the size of a large municipal layer and well inside what the byte "
                            "bound admits. This is an IMPLEMENTATION CAP and is NOT the format's "
                            "normative maximum. A second cap the manifest schema has no field for is "
                            "declared beside it in the module: `GEOJSON_MAX_POSITIONS` (500 000), "
                            "the positions across the whole document."),
                        enforced_at=(
                            "`GeojsonAdapter.to_cdm` reads `len(features)` on the parsed document "
                            "and raises `FeatureCountExceeded` (a `ValueError`) before any "
                            "canonical object is built; the position count is taken during the "
                            "structural walk of each geometry and raises `PositionCountExceeded` "
                            "at the position that crosses it, before any model is constructed"),
                        test="tests/test_cdm_geojson_adapter.py::test_the_feature_bound_admits_a_collection_at_it_and_refuses_one_feature_past",
                    ),
                },
            ),
            unknown_fields=UnknownFields.PRESERVED,
            unknown_fields_basis=(
                "RFC 7946 §6.1 permits foreign members on every GeoJSON object; every member this "
                "adapter does not consume — at collection, feature and geometry level — is kept "
                "verbatim in the structured residual at its own relative path"),
        ),
        limitations=[
            Limitation(
                id="geometry-collection",
                summary="`GeometryCollection` is refused, not translated: `geo.py` keeps it out "
                        "of the CDM union deliberately (a heterogeneous geometry has no single "
                        "semantics for a consumer), so a feature carrying one refuses the whole "
                        "document. The RFC's other six geometry types are all carried",
                unsupported_paths=[],
            ),
            Limitation(
                id="bare-geometry",
                summary="a GeoJSON text whose top-level object is a geometry (RFC 7946 §3 permits "
                        "it) is refused: it has no id and no properties to carry, so nothing "
                        "identifies it. Wrap it in a Feature",
                unsupported_paths=[],
            ),
            Limitation(
                id="empty-coordinates",
                summary="a geometry whose `coordinates` array is empty is refused. RFC 7946 §3.1 "
                        "lets a processor read it as a null geometry; this adapter does not turn "
                        "a stated geometry into an absent one silently",
                unsupported_paths=[],
            ),
            Limitation(
                id="legacy-crs",
                summary="a `crs` member at any level is refused. RFC 7946 §4 removed it; a "
                        "document carrying one follows the 2008 specification, and no legacy "
                        "profile is implemented here. Projected coordinates are never relabelled "
                        "as WGS84",
                unsupported_paths=[],
            ),
            Limitation(
                id="empty-collection",
                summary="an empty FeatureCollection translates to no object, which is what it "
                        "carries; its collection-level members then have no object to ride in "
                        "and the preservation ledger reports them LOST for that document. Stated "
                        "here so the empty result is never read as a filtered one",
                unsupported_paths=[],
            ),
            Limitation(
                id="no-source-time",
                summary="RFC 7946 states no instant for a Feature or a FeatureCollection, so "
                        "no object carries a timestamp unless the caller supplies an as-of "
                        "context (`GeojsonAdapter(as_of=AsOf(instant, basis))`), which lands at "
                        "`validity.observed_at` (PlanObject) or `valid_from` (Entity) with its "
                        "basis in `source.transformations`. The conformance suite's check J "
                        "reads this id as the declared reason it has no timestamp to judge",
                unsupported_paths=[],
            ),
            Limitation(
                id="bbox-not-projected",
                summary="`bbox` at every level is kept verbatim in the residual and is NOT "
                        "projected to a canonical `BoundingBox`: `PlanObject` carries bounds only "
                        "inside an `Area`, and `geo.BoundingBox` refuses an antimeridian-crossing "
                        "box (west > east) by construction. Every bbox is noted in "
                        "`source.transformations`, the antimeridian case as such",
                unsupported_paths=[],
            ),
            "egress accepts `PlanObject` and `Entity` (an entity's `position` becomes a Point, "
            "or a null geometry when it has none); an `Event` or a `Track` is not compatible "
            "with the geo-object profile and egress refuses it rather than choosing a geometry "
            "for it",
            "egress under the exchange profile refuses a source property already named "
            "`sc:...` rather than overwriting it; the `sc:` keys of a re-ingested exchange "
            "document are ordinary source properties on ingest (this adapter never reads its "
            "own export keys back as canonical meaning), so such a document exports under the "
            "generic profile only",
            "the evidence RECORD for this adapter is not IN the distribution: `evidence/` is "
            "untracked and unpackaged. `evidence.available` is false because no published "
            "Release carries this adapter's records yet; it becomes true at the first release "
            "that attaches them",
            "of §3.5's five resource limits this adapter enforces THREE — `max_input_bytes` "
            "and `max_depth` by the base class before decode, and `max_objects` (the feature "
            "count) in this module before any object is built — plus a position count the "
            "manifest schema has no field for. The other two are absent with their reasons in "
            "`capabilities.limits.absent_because`",
        ],
        limitations_empty_reason=None,
        residual=Residual.STRUCTURED,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=False),
    )

    #: JSON: `from_cdm` emits a canonical serialisation whose key order is sorted and whose
    #: whitespace is its own, so octet equality with the source is not a promise this format
    #: lets an emitter make; the harness compares a JSON emitter by VALUE (`_check_roundtrip`)
    #: and this declaration names that comparison rather than leaving the `bytes` default to
    #: describe one the harness never performs on a `.json` fixture.
    ROUNDTRIP_TOLERANCE = "values"

    #: Nothing a source states changes value in translation: coordinates are carried as numbers
    #: (an integer becomes the same float), the feature id as text beside its JSON form, and
    #: every other leaf verbatim. The map is empty because there is nothing to excuse.
    TRANSFORMS: dict[str, str] = {}

    # The path-bound preservation declarations (F02), in the order the ledger tries them —
    # SPECIFIC keys before the residual subtree that would otherwise absorb them. Two families:
    # the FeatureCollection form (`features[*]...`, `#[*]` holding each feature's leaves to its
    # own object) and the bare-Feature form (`#0`). The empty key is the document itself: every
    # top-level member no earlier key claimed — `type`, `bbox`, foreign members — is a residual
    # leaf under `residual.data.document` on every object.
    MAPPINGS = {
        # -- FeatureCollection form
        "features[*].id": (
            lossless.Mapping("#[*]:source_ids[0].external_id", "text"),
            lossless.Mapping("#[*]:residual.data.feature.id"),
        ),
        "features[*].geometry.type": lossless.Mapping("#[*]:geometry.type"),
        "features[*].geometry.coordinates[*]": lossless.Mapping(
            "#[*]:geometry.coordinates[*]", "number"),
        "features[*].geometry.coordinates[*][*]": lossless.Mapping(
            "#[*]:geometry.coordinates[*][*]", "number"),
        "features[*].geometry.coordinates[*][*][*]": lossless.Mapping(
            "#[*]:geometry.coordinates[*][*][*]", "number"),
        "features[*].geometry.coordinates[*][*][*][*]": lossless.Mapping(
            "#[*]:geometry.coordinates[*][*][*][*]", "number"),
        "features[*].geometry": lossless.Mapping("#[*]:residual.data.feature.geometry",
                                                 kind="residual"),
        "features[*].properties": lossless.Mapping("#[*]:residual.data.feature.properties",
                                                   kind="residual"),
        "features[*]": lossless.Mapping("#[*]:residual.data.feature", kind="residual"),
        # -- bare Feature form
        "id": (
            lossless.Mapping("#0:source_ids[0].external_id", "text"),
            lossless.Mapping("#0:residual.data.document.id"),
        ),
        "geometry.type": lossless.Mapping("#0:geometry.type"),
        "geometry.coordinates[*]": lossless.Mapping("#0:geometry.coordinates[*]", "number"),
        "geometry.coordinates[*][*]": lossless.Mapping("#0:geometry.coordinates[*][*]", "number"),
        "geometry.coordinates[*][*][*]": lossless.Mapping(
            "#0:geometry.coordinates[*][*][*]", "number"),
        "geometry.coordinates[*][*][*][*]": lossless.Mapping(
            "#0:geometry.coordinates[*][*][*][*]", "number"),
        "geometry": lossless.Mapping("#0:residual.data.document.geometry", kind="residual"),
        "properties": lossless.Mapping("#0:residual.data.document.properties", kind="residual"),
        # -- the document's own members, both forms
        "": lossless.Mapping("*:residual.data.document", kind="residual"),
    }

    def __init__(self, clock: times.Clock | None = None, *, synthetic: bool = True,
                 dataset: str | None = None, identity: str = IDENTITY_REFUSE,
                 as_of: AsOf | None = None, export: str = EXPORT_GENERIC) -> None:
        """`dataset` names the identity namespace (`GeoJSON:<dataset>`; None = the unnamed
        dataset, `GeoJSON`, and two datasets ingested under it that share a feature id are one
        object — a caller with more than one dataset names each). `identity` is the fallback for
        a feature with no `id`. `as_of` is the snapshot context. `export` is the egress profile.
        Every one is part of the determinism tuple (ARCHITECTURE.md §6.1)."""
        super().__init__(clock, synthetic=synthetic)
        if dataset is not None and (not isinstance(dataset, str) or not dataset.strip()):
            raise ValueError("dataset must be a non-empty name or None")
        if identity not in (IDENTITY_REFUSE, IDENTITY_RECORD_INDEX) and not (
                identity.startswith(IDENTITY_PROPERTY_PREFIX)
                and identity[len(IDENTITY_PROPERTY_PREFIX):]):
            raise ValueError(f"identity must be {IDENTITY_REFUSE!r}, {IDENTITY_RECORD_INDEX!r} "
                             f"or '{IDENTITY_PROPERTY_PREFIX}<name>', not {identity!r}")
        if as_of is not None and not isinstance(as_of, AsOf):
            raise TypeError("as_of must be an AsOf(instant, basis)")
        if export not in EXPORT_PROFILES:
            raise ValueError(f"export must be one of {EXPORT_PROFILES}, not {export!r}")
        self._dataset = dataset
        self._identity = identity
        self._as_of = as_of
        self._export = export

    @property
    def namespace(self) -> str:
        """The identity namespace every object's `source_ids[].system` carries."""
        return SYSTEM if self._dataset is None else f"{SYSTEM}:{self._dataset}"

    # ------------------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        document = self._as_document(raw)
        _refuse_non_finite(document)
        kind = document.get("type")
        if kind == "FeatureCollection":
            features = document.get("features")
            if not isinstance(features, list):
                raise ValueError("GeoJSON FeatureCollection has no `features` array (RFC 7946 "
                                 "§3.3 requires one, possibly empty)")
            if len(features) > GEOJSON_MAX_FEATURES:
                raise FeatureCountExceeded(
                    f"GeoJSON FeatureCollection carries {len(features)} features and this "
                    f"adapter declares max_objects = {GEOJSON_MAX_FEATURES}. Refused whole, "
                    "before any object is built: nothing is truncated")
            _refuse_crs(document, "the FeatureCollection")
            consumed = ("document.features",)
            top = {"document": document}
            objects: list[CDMBase] = []
            budget = [GEOJSON_MAX_POSITIONS]
            for index, feature in enumerate(features):
                objects.append(self._feature(feature, index, top, consumed + (
                    "feature.geometry.type", "feature.geometry.coordinates"), budget,
                    where=f"features[{index}]", feature_key="feature"))
            return objects
        if kind == "Feature":
            _refuse_crs(document, "the Feature")
            return [self._feature(document, None, {}, ("document.geometry.type",
                                                        "document.geometry.coordinates"),
                                  [GEOJSON_MAX_POSITIONS], where="the Feature",
                                  feature_key="document")]
        if kind in GEOMETRY_TYPES or kind == "GeometryCollection":
            raise ValueError(f"GeoJSON payload is a bare {kind} geometry; this adapter takes a "
                             "Feature or a FeatureCollection (limitation `bare-geometry`: a "
                             "geometry alone has no id and no properties to carry). Wrap it in "
                             "a Feature")
        raise ValueError(f"GeoJSON payload has type {kind!r}; RFC 7946 §1.4 names Feature, "
                         "FeatureCollection and the seven geometry types, and this adapter "
                         "reads the first two. Keys present: " + ", ".join(sorted(document)))

    def _feature(self, feature: Any, index: int | None, top: dict, consumed: tuple[str, ...],
                 budget: list[int], *, where: str, feature_key: str) -> CDMBase:
        if not isinstance(feature, dict):
            raise ValueError(f"GeoJSON {where} is a JSON {type(feature).__name__}, not a "
                             "Feature object")
        if feature.get("type") != "Feature":
            raise ValueError(f"GeoJSON {where} has type {feature.get('type')!r}; a member of "
                             "`features` is a Feature (RFC 7946 §3.3)")
        for required in ("geometry", "properties"):
            if required not in feature:
                raise ValueError(f"GeoJSON {where} has no `{required}` member; RFC 7946 §3.2 "
                                 "requires one on every Feature (its value may be null)")
        _refuse_crs(feature, where)
        properties = feature["properties"]
        if properties is not None and not isinstance(properties, dict):
            raise ValueError(f"GeoJSON {where}.properties is a JSON "
                             f"{type(properties).__name__}; RFC 7946 §3.2 allows an object or "
                             "null")
        geometry = feature["geometry"]
        notes: list[str] = []
        if geometry is not None:
            _check_geometry(geometry, budget, where=f"{where}.geometry")
            notes += [f"ring orientation: {line}" for line in right_hand_rule_departures(geometry)]
            geometry_note = bbox_note(geometry.get("bbox"),
                                      f"residual.data.{feature_key}.geometry.bbox")
            if geometry_note:
                notes.append(geometry_note)
        feature_note = bbox_note(feature.get("bbox"), f"residual.data.{feature_key}.bbox")
        if feature_note:
            notes.append(feature_note)
        collection_note = bbox_note(top.get("document", {}).get("bbox"),
                                    "residual.data.document.bbox") if top else None
        if collection_note:
            notes.append(collection_note)

        key, external_id, original_id, identity_note = self._identity_of(feature, index, where)
        if identity_note:
            notes.append(identity_note)
        source_ids = [{"system": self.namespace, "external_id": external_id}]
        object_id = ids.derive(self.namespace, key, kind="feature")

        view = dict(top)
        view[feature_key] = feature
        residual = lossless.residual_block(self, view, consumed)

        if geometry is None:
            if self._as_of is None:
                raise ValueError(
                    f"GeoJSON {where} has a null geometry. The {MAPPING_PROFILE} profile keeps "
                    "it as an Entity with no position, and an Entity's `valid_from` is required; "
                    "the source states no time, so the caller's as-of context is needed "
                    "(GeojsonAdapter(as_of=AsOf(instant, basis))). Refused rather than stamped "
                    "with the epoch, the clock or a file time")
            notes.append(f"valid_from: the caller's as-of context — {self._as_of.basis}")
            return Entity(
                source=self._source(index, original_id, notes),
                source_ids=source_ids,
                entity_id=object_id,
                entity_type=EntityType.OVERLAY_OBJECT,
                affiliation=Affiliation.UNKNOWN,
                symbol=None,
                position=None,
                valid_from=self._as_of.instant,
                attributes={},
                residual=residual,
            )
        validity = None
        if self._as_of is not None:
            validity = TemporalValidity(observed_at=self._as_of.instant)
            notes.append(f"validity.observed_at: the caller's as-of context — {self._as_of.basis}")
        return PlanObject(
            source=self._source(index, original_id, notes),
            source_ids=source_ids,
            object_id=object_id,
            object_type=ObjectType.ANNOTATION,
            label=None,
            geometry={"type": geometry["type"], "coordinates": geometry["coordinates"]},
            style={},
            validity=validity,
            residual=residual,
        )

    def _identity_of(self, feature: dict, index: int | None, where: str
                     ) -> tuple[str, str, str | None, str | None]:
        """(derivation key, external_id, original_id, note) for one feature."""
        if "id" in feature:
            feature_id = feature["id"]
            if isinstance(feature_id, bool) or not isinstance(feature_id, (str, int, float)):
                raise ValueError(f"GeoJSON {where}.id is a JSON {_json_type(feature_id)}; RFC "
                                 "7946 §3.2 allows a string or a number")
            if isinstance(feature_id, str) and not feature_id:
                raise ValueError(f"GeoJSON {where}.id is an empty string, which identifies "
                                 "nothing")
            text = json.dumps(feature_id)
            return text, str(feature_id), text, None
        if self._identity == IDENTITY_RECORD_INDEX:
            if index is None:
                raise ValueError(f"GeoJSON {where} has no `id` and the record-index policy needs "
                                 "a position in a collection; a bare Feature has none")
            return (f"#{index}", f"#{index}", None,
                    f"identity: {IDENTITY_RECORD_INDEX} — no `id` on the feature, so the object "
                    f"id is derived from its position {index} in the collection; NOT stable "
                    "across dataset updates (an insertion or deletion moves every later feature)")
        if self._identity.startswith(IDENTITY_PROPERTY_PREFIX):
            name = self._identity[len(IDENTITY_PROPERTY_PREFIX):]
            properties = feature.get("properties") or {}
            if name not in properties:
                raise ValueError(f"GeoJSON {where} has no `id` and no property {name!r}, which "
                                 f"the {self._identity!r} policy keys on; refused rather than "
                                 "guessed")
            value = properties[name]
            if isinstance(value, bool) or not isinstance(value, (str, int, float)) or value == "":
                raise ValueError(f"GeoJSON {where}.properties.{name} is a JSON "
                                 f"{_json_type(value)}; an identity property is a non-empty "
                                 "string or a number")
            return (f"{name}={json.dumps(value)}", str(value), None,
                    f"identity: {self._identity} — no `id` on the feature, so the object id is "
                    f"derived from properties.{name}; stable exactly as long as the source keeps "
                    "that property stable")
        raise ValueError(f"GeoJSON {where} has no `id` and the adapter's identity policy is "
                         f"{IDENTITY_REFUSE!r}: nothing is guessed. Choose "
                         f"GeojsonAdapter(identity={IDENTITY_RECORD_INDEX!r}) or "
                         f"identity='{IDENTITY_PROPERTY_PREFIX}<name>' and read what each can "
                         "and cannot guarantee in adapters/geojson.py")

    def _source(self, index: int | None, original_id: str | None, notes: list[str]) -> SourceRef:
        source = self.source_ref()
        return source.model_copy(update={"record_index": index, "original_id": original_id,
                                         "transformations": list(notes)})

    @staticmethod
    def _as_document(raw: bytes | dict) -> dict:
        """JSON text or a dict -> the top-level object. A JSON value that is not an object is
        REFUSED with a `ValueError`; a NaN or infinity token is refused by the decoder."""
        if isinstance(raw, (bytes, bytearray, str)):
            document = json.loads(raw, parse_constant=_refuse_constant)
            if not isinstance(document, dict):
                raise ValueError(_NOT_AN_OBJECT.format(kind=_json_type(document)))
            return document
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list):
            raise ValueError(_NOT_AN_OBJECT.format(kind="array"))
        raise TypeError(f"GeoJSON adapter takes JSON bytes or a dict, got {type(raw).__name__}")

    # ---------------------------------------------------------------------------- v2 surface

    def detect(self, raw: bytes | dict) -> bool | None:
        """The cheap structural test: a JSON object whose `type` is Feature or FeatureCollection.
        Text is read only inside the byte bound."""
        if isinstance(raw, dict):
            return raw.get("type") in ("Feature", "FeatureCollection")
        if isinstance(raw, (bytes, bytearray, str)):
            octets = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
            if len(octets) > GEOJSON_MAX_INPUT_BYTES:
                return False
            try:
                document = json.loads(octets, parse_constant=_refuse_constant)
            except ValueError:
                return False
            return isinstance(document, dict) and document.get("type") in (
                "Feature", "FeatureCollection")
        return None

    def validate_source(self, raw: bytes | dict) -> list[str]:
        """Refusals first, then RFC 7946's SHOULDs this adapter accepts but names: every ring
        that breaks the right-hand rule."""
        try:
            document = self._as_document(raw)
            self.to_cdm(raw)
        except Exception as problem:                     # noqa: BLE001 - reported, not raised
            return [f"{type(problem).__name__}: {problem}"]
        features = document["features"] if document.get("type") == "FeatureCollection" \
            else [document]
        problems: list[str] = []
        for index, feature in enumerate(features):
            geometry = feature.get("geometry")
            if isinstance(geometry, dict):
                problems += [f"features[{index}].geometry: {line}"
                             for line in right_hand_rule_departures(geometry)]
        return problems

    # ------------------------------------------------------------------------------ egress

    def from_cdm(self, objects: list[CDMBase]) -> bytes:
        """The objects as a GeoJSON document under the constructed export profile, in
        ARCHITECTURE.md §6.2's canonical serialisation."""
        features: list[dict] = []
        documents: list[dict] = []
        bare: list[bool] = []
        for position, obj in enumerate(objects):
            feature, document, from_bare_feature = self._feature_of(obj, position)
            features.append(feature)
            documents.append(document)
            bare.append(from_bare_feature)
        distinct = [d for i, d in enumerate(documents)
                    if d and d not in documents[:i]]
        if len(distinct) > 1:
            raise ValueError("GeoJSON egress: the objects carry two different collection-level "
                             "blocks (they came from different source documents); export each "
                             "document's objects separately, because merging would keep one "
                             "collection's members and drop the other's")
        if distinct and any(not d for d in documents):
            raise ValueError("GeoJSON egress: some objects carry a source collection's members "
                             "and others carry none; the collection's members would be claimed "
                             "for objects that were never in it. Export the two sets separately")
        if len(features) == 1 and bare[0]:
            # One object that came from a bare Feature goes back as one: the document form is
            # part of what the residual preserved. Several bare Features, or a bare Feature
            # beside a fresh record, are a collection with no members of its own.
            out: dict = features[0]
        else:
            out = {**(distinct[0] if distinct else {}), "type": "FeatureCollection",
                   "features": features}
        if self._export == EXPORT_EXCHANGE:
            self._reserve(out, "the collection")
            out[EXCHANGE_PREFIX + "profile"] = EXPORT_EXCHANGE
        return (json.dumps(out, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False)
                + "\n").encode("utf-8")

    def _feature_of(self, obj: CDMBase, position: int) -> tuple[dict, dict, bool]:
        """(feature, collection block, came-from-a-bare-Feature) for one object. The collection
        block is `{}` for an object that did not come through this adapter or came from a bare
        Feature, whose members are all the record's own."""
        residual = obj.residual
        own = residual is not None and residual.namespace == self.metadata.format.name \
            and isinstance(residual.data, dict)
        document = dict(residual.data.get("document") or {}) if own else {}
        from_bare_feature = False
        if own and document.get("type") == "Feature":
            record, document, from_bare_feature = dict(document), {}, True
        elif own and "feature" in residual.data:
            record = dict(residual.data["feature"])
        else:
            record = {}
        if isinstance(obj, PlanObject):
            geometry: Any = obj.geometry.model_dump(mode="json")
            identifier = str(obj.object_id)
        elif isinstance(obj, Entity):
            geometry = None if obj.position is None else {
                "type": "Point",
                "coordinates": [obj.position.lon, obj.position.lat] + (
                    [obj.position.alt_m] if obj.position.alt_m is not None else [])}
            identifier = str(obj.entity_id)
        else:
            raise ValueError(f"GeoJSON egress: a {obj.object_kind} is not compatible with the "
                             f"{MAPPING_PROFILE} profile — it has no geometry this adapter may "
                             "choose for it; PlanObject and Entity are the two kinds it emits")
        extras = record.get("geometry")
        if isinstance(extras, dict) and geometry is not None:
            geometry = {**extras, **geometry}
        feature = {"type": "Feature", **record, "geometry": geometry}
        if "id" not in feature and not record:
            feature["id"] = identifier
        feature.setdefault("properties", {})
        if self._export == EXPORT_EXCHANGE:
            feature["properties"] = self._exchange_properties(obj, feature.get("properties"))
        return feature, document, from_bare_feature

    def _exchange_properties(self, obj: CDMBase, properties: Any) -> dict:
        """The source properties plus the `sc:*` namespace. A source key inside the namespace is
        never overwritten: the export is refused."""
        out = dict(properties) if isinstance(properties, dict) else {}
        self._reserve(out, "a feature's properties")
        block: dict[str, Any] = {
            "object_kind": obj.object_kind,
            "schema_version": obj.schema_version,
            "source_system": obj.source.system,
            "source_adapter": obj.source.adapter,
            "source_adapter_version": obj.source.adapter_version,
            "synthetic": obj.source.synthetic,
            "source_ids": [s.model_dump(mode="json") for s in obj.source_ids],
        }
        if isinstance(obj, PlanObject):
            block["object_id"] = str(obj.object_id)
            block["object_type"] = obj.object_type.value
            if obj.label is not None:
                block["label"] = obj.label
            if obj.validity is not None and obj.validity.observed_at is not None:
                block["as_of"] = times.render(obj.validity.observed_at)
        else:
            block["entity_id"] = str(obj.entity_id)
            block["entity_type"] = obj.entity_type.value
            block["affiliation"] = obj.affiliation.value
            block["valid_from"] = times.render(obj.valid_from)
        if properties is None:
            block["properties_null"] = True
        for key, value in block.items():
            out[EXCHANGE_PREFIX + key] = value
        return out

    @staticmethod
    def _reserve(members: dict, where: str) -> None:
        taken = sorted(k for k in members if isinstance(k, str) and k.startswith(EXCHANGE_PREFIX))
        if taken:
            raise ValueError(f"GeoJSON egress under {EXPORT_EXCHANGE}: {where} already carries "
                             f"{taken}, inside the reserved `{EXCHANGE_PREFIX}` namespace. A "
                             "source property is never overwritten by an export key; export "
                             f"under the {EXPORT_GENERIC!r} profile instead")


# ------------------------------------------------------------------------- structural checks


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _refuse_crs(member: dict, where: str) -> None:
    if "crs" in member:
        raise ValueError(f"GeoJSON {where} carries a `crs` member. RFC 7946 §4 removed it — a "
                         "document with one follows the 2008 specification, and this adapter "
                         "implements no legacy profile (limitation `legacy-crs`). Confirm the "
                         "data is WGS84 longitude/latitude and strip the member; a projected "
                         "dataset is never relabelled as WGS84")


def _refuse_non_finite(document: Any) -> None:
    """Every float in the document is finite. A parsed twin bypasses the decoder's constant
    hook, so the walk is what refuses `nan` and `inf` from that path."""
    pending = [document]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)
        elif isinstance(node, float) and not math.isfinite(node):
            _refuse_constant(repr(node))


def _check_geometry(geometry: Any, budget: list[int], *, where: str) -> None:
    """Shape, emptiness, position arity and the position budget, BEFORE any model is built. The
    coordinate ranges and ring closure are `geo.py`'s to refuse."""
    if not isinstance(geometry, dict):
        raise ValueError(f"GeoJSON {where} is a JSON {_json_type(geometry)}; a geometry is an "
                         "object or null (RFC 7946 §3.2)")
    _refuse_crs(geometry, where)
    kind = geometry.get("type")
    if kind == "GeometryCollection":
        raise ValueError(f"GeoJSON {where} is a GeometryCollection, which the CDM does not model "
                         "(limitation `geometry-collection`; geo.py's decision). The document is "
                         "refused rather than the feature dropped")
    if kind not in GEOMETRY_TYPES:
        raise ValueError(f"GeoJSON {where}.type is {kind!r}; the six geometry types this adapter "
                         f"carries are {', '.join(GEOMETRY_TYPES)}")
    if "coordinates" not in geometry:
        raise ValueError(f"GeoJSON {where} has no `coordinates` member (RFC 7946 §3.1)")
    _walk_positions(geometry["coordinates"], _POSITION_DEPTH[kind], budget, where=where)


def _walk_positions(node: Any, depth: int, budget: list[int], *, where: str) -> None:
    """Descend `depth` arrays, refusing an empty one at any level, then check each position."""
    if depth == 0:
        if not isinstance(node, list) or not node:
            raise ValueError(f"GeoJSON {where}: a position is a non-empty array of numbers "
                             "(limitation `empty-coordinates`); found "
                             f"{_json_type(node) if not isinstance(node, list) else 'an empty array'}")
        if not 2 <= len(node) <= 3 or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) for v in node):
            raise ValueError(f"GeoJSON {where}: a position is [longitude, latitude] or "
                             f"[longitude, latitude, elevation] (RFC 7946 §3.1.1); found {node!r}")
        budget[0] -= 1
        if budget[0] < 0:
            raise PositionCountExceeded(
                f"GeoJSON document carries more than {GEOJSON_MAX_POSITIONS} positions "
                "(`GEOJSON_MAX_POSITIONS`); refused at the position that crossed the bound, "
                "before any model was built")
        return
    if not isinstance(node, list):
        raise ValueError(f"GeoJSON {where}.coordinates nests {_json_type(node)} where an array "
                         "of positions was expected")
    if not node:
        raise ValueError(f"GeoJSON {where} has an empty `coordinates` array at some level. RFC "
                         "7946 §3.1 lets a processor read it as null; this adapter refuses it "
                         "(limitation `empty-coordinates`) rather than turn a stated geometry "
                         "into an absent one")
    for child in node:
        _walk_positions(child, depth - 1, budget, where=where)
