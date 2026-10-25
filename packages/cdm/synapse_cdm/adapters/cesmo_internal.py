"""SC CESMO Internal Exchange 1.0 (`sc.cesmo.internal/1.0`) -> CDM. Adapter #34.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
Stage A of the "SynapseCommand STANAG 4658 CESMO and EOB Engineering Kit 1.0" (Decent
Cybersecurity, 4 October 2026): the kit's INTERNAL JSON exchange contract, one Exchange per call,
mapped to canonical objects. An Exchange is what a gateway outside this repository emits after it
has decoded, checked and journalled its native traffic; this adapter reads that Exchange and
nothing else. It is NOT STANAG 4658 interoperability: no CESMO unit, no AEDP-13 Edition B message
and no native byte is parsed or produced, and the normative binding is BLOCKED on the kit's
unresolved dependency register N01-N12. The gateway, the EOB state projector, the journal, egress,
the offline configuration and the normative edition plugin (kit §13-§18, §20) are not in this
repository; nothing here holds state, so no revision, withdrawal or snapshot is APPLIED, only
translated. The kit is cited by title and date; its prose is not carried, its five synthetic
fixtures and its expected output are (`fixtures/cesmo_internal/`).

The contract — the schema literal, the strict parser, the caps, the validator and `CesmoError` —
is `adapters/cesmo_internal_codec.py`. This module calls the JSON decoder itself only in
`detect`, its lenient discriminator test.

WHAT AN EXCHANGE BECOMES (kit §12, in the kit's order)
-----------------------------------------------------
Per record, in source order: `observation` -> Event DETECTION; `eob_upsert` -> Entity
(EntityType.UNKNOWN, `attributes.cesmo.role = "emitter"`) THEN Event TRACK_UPDATE; `eob_delete` ->
Event STATUS_CHANGE (`payload.cesmo.operation = "withdraw"`, never a destruction); `status` ->
Event STATUS_CHANGE (`"status"`). An envelope `snapshot` adds one STATUS_CHANGE Event after every
record object (`"snapshot"`). Severity is INFO, the adapter's informational category, never a
threat judgement. No Track (one assertion is not a motion history) and no PlanObject. A Point
geometry, and on the Entity a Position, exist only for a record's explicitly asserted emitter
`position`; `hae_m` is the third coordinate and `Position.alt_m`, `Position.vertical` and
`accuracy_m` stay null, and the uncertainty ellipse stays verbatim in `attributes`/`payload`.

Identity is kit §11 exactly: `J(list) = json.dumps(list, ensure_ascii=True, separators=(",",
":"))`; the emitter key `J([mode, network_id, originator_id, identity_epoch, object_id])`, the
event key `J([mode, network_id, originator_id, identity_epoch, message_id, record_id])`, the
snapshot event's with `record_id = "$snapshot"`, each hashed by `ids.derive` under
`SC_CESMO_INTERNAL` as an `entity` or an `event`. The mode is in every key, so a `live` record
never shares an identity with the same `synthetic` one.

Every object carries `Residual(namespace="SC CESMO Internal Exchange", data={"envelope": <the
envelope without records>, "record": <the record verbatim>})`; the snapshot event's residual is
`{"envelope": ...}`, the snapshot being inside the envelope. `SourceRef.transformations` lists,
in kit L152's order, `identity-scoping-v1` (always), `timestamp-millisecond-truncation-v1` (only
when the record's time, or for the snapshot event the envelope's, has a non-zero fourth to sixth
fraction digit the CDM's millisecond rendering drops) and `position-method-enum-v1` (on every
object of a record carrying a `position`).

`cdm_schema="3.0.0"` stamps the objects "3.0.0", the contract the kit's
`expected-upsert-cdm.json` was written against; nothing this adapter emits needs a CDM 3.1.0
member, and a 3.0.0 reader is handed `synapse_cdm.projection.dump_for(obj, "3.0.0")`. The
default stamps `SCHEMA_VERSION`.

REFUSALS
--------
Every refusal is a `CesmoError` (a `ValueError`) with the kit's §19 code; the codec's docstring
gives the order and the recorded deviations from the kit's `validate_contract.py` 1.0. `to_cdm`
is marked `__input_bounded__`: it runs the SDK's own byte and depth bounds itself and re-raises
their refusals as `CesmoInputTooLarge` / `CesmoInputTooDeep`, each both the SDK's class and a
`CesmoError` with code E_LIMIT.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from synapse_cdm import ids
from synapse_cdm.adapter import (
    Adapter,
    InputTooDeep,
    InputTooLarge,
    enforce_depth_bound,
    enforce_input_bound,
    json_nesting_depth,
)
from synapse_cdm.adapters import cesmo_internal_codec as codec
from synapse_cdm.adapters.cesmo_internal_codec import (
    CONTRACT,
    MAX_DEPTH,
    MAX_INPUT_BYTES,
    MAX_OBJECTS,
    SNAPSHOT_RECORD_ID,
    CesmoError,
    CesmoInputTooDeep,
    CesmoInputTooLarge,
)
from synapse_cdm.enums import Affiliation, EntityType, EventType, PositionSource, Severity
from synapse_cdm.geo import Point
from synapse_cdm.lossless import Mapping
from synapse_cdm.manifest import (
    AdapterMetadata,
    Capabilities,
    ClaimStatus,
    Direction,
    Evidence,
    FormatRef,
    LicenseClass,
    LimitBasis,
    LimitKind,
    Limitation,
    Limits,
    Maturity,
    MaturityLevel,
    UnknownFields,
    WireBinding,
)
from synapse_cdm.manifest import Residual as ResidualStance
from synapse_cdm.models import CDMBase, Entity, Event, Position, Residual, SourceHash, SourceId
from synapse_cdm.version import SCHEMA_VERSION

#: `metadata.format.name`: the residual namespace and `SourceRef.format_name` (kit L78).
FORMAT_NAME = "SC CESMO Internal Exchange"
FORMAT_VERSION = "1.0.0"
#: `SourceRef.system` and the system every identity is derived under (kit L146).
SYSTEM = "SC_CESMO_INTERNAL"
#: The `cdm_schema` value that stamps the objects for a CDM 3.0.0 reader.
COMPAT_SCHEMA = "3.0.0"

T_IDENTITY = "identity-scoping-v1"
T_TIME = "timestamp-millisecond-truncation-v1"
T_METHOD = "position-method-enum-v1"
#: The explicit mapping basis every emitter Entity states (kit L169; the expected file's text).
MAPPING_BASIS = "source-asserted EOB object; no RF identification performed"

#: The record kind -> (event type, `payload.cesmo.operation`) (kit §12, DECISIONS C-05 a).
OPERATIONS = {
    "observation": (EventType.DETECTION, "observation"),
    "eob_upsert": (EventType.TRACK_UPDATE, "upsert"),
    "eob_delete": (EventType.STATUS_CHANGE, "withdraw"),
    "status": (EventType.STATUS_CHANGE, "status"),
}
#: The position method enum projection (kit §9: an exact map).
METHODS = {
    "estimated": PositionSource.ESTIMATED,
    "gnss": PositionSource.GNSS,
    "inertial": PositionSource.INERTIAL,
    "manual": PositionSource.MANUAL,
}
#: The affiliation projection, a literal table: the contract's four tokens are the CDM's four,
#: and an absent affiliation is UNKNOWN (kit L169). No transformation is recorded for it.
AFFILIATIONS = {
    "FRIENDLY": Affiliation.FRIENDLY,
    "HOSTILE": Affiliation.HOSTILE,
    "NEUTRAL": Affiliation.NEUTRAL,
    "UNKNOWN": Affiliation.UNKNOWN,
}

_CAP = "This is an IMPLEMENTATION CAP and is NOT the format's normative maximum."
_TESTS = "tests/test_cdm_cesmo_internal_adapter.py::"
_CONFIG = "cesmo_internal configuration:"


def key(values: list) -> str:
    """Kit §11's J: compact, ASCII-escaped JSON of the scoped tuple, in its fixed order."""
    return json.dumps(values, ensure_ascii=True, separators=(",", ":"))


def _r(path: str) -> Mapping:
    return Mapping(f"event:residual.data.record.{path}", kind="residual")


def _build_mappings() -> dict:
    """The ledger. Every leaf of a record lands in `residual.data.record` of an Event (every
    record makes one) and every leaf of the envelope in `residual.data.envelope` of every Event;
    each leaf the projection reads onto every Event of its record is ALSO declared canonical, the
    residual member first so the entry's category is the canonical one. A record makes one or two
    objects, so the bindings are by kind (`event:`), not by index (`#[*]`); which Event holds which
    record, and the Entity-only fields (`object_id` in the identity key, `affiliation`,
    `confidence`, `position.method`), are asserted by the mapping tests. More specific keys come
    first: the ledger takes the first pattern that matches. The observed time's tolerance is the
    CDM's millisecond rendering, which truncates (`timestamp-millisecond-truncation-v1`)."""
    return {
        "records": Mapping(
            "event:residual.data.envelope.records", "absent_if", params={"sentinel": []}
        ),
        "records[*].record_id": (_r("record_id"), Mapping("event:source.original_id")),
        "records[*].kind": (
            _r("kind"),
            Mapping(
                "event:event_type",
                "enum_map",
                params={"table": {k: v.value for k, (v, _op) in OPERATIONS.items()}},
            ),
        ),
        "records[*].observed_at": (
            _r("observed_at"),
            Mapping("event:observed_at", "instant", tolerance=0.001),
            Mapping("event:source.observed_at", "instant", tolerance=0.001),
        ),
        "records[*].position.longitude_deg": (
            _r("position.longitude_deg"),
            Mapping("event:geometry.coordinates[0]", "number"),
        ),
        "records[*].position.latitude_deg": (
            _r("position.latitude_deg"),
            Mapping("event:geometry.coordinates[1]", "number"),
        ),
        "records[*].position.hae_m": (
            _r("position.hae_m"),
            Mapping("event:geometry.coordinates[2]", "number"),
        ),
        "records[*]": Mapping("event:residual.data.record", kind="residual"),
        "snapshot.snapshot_id": (
            Mapping("event:residual.data.envelope.snapshot.snapshot_id", kind="residual"),
            Mapping("event:source.original_id"),
        ),
        "": Mapping("event:residual.data.envelope", kind="residual"),
    }


class CesmoInternalAdapter(Adapter):
    """One SC CESMO Internal Exchange in; its Entities and Events out, in the kit's order."""

    name = "cesmo_internal"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    #: `PROVISIONAL` beside `provisional-internal-profile` (DECISIONS C-04, the `link16_gateway`
    #: precedent): the wire form is an internal contract this repository's owner defines, bound to
    #: no normative document. `OPEN`: the contract (its schema, published beside the package, and
    #: its fixtures) is in this repository under Apache-2.0. L3: an ingest-only adapter declares
    #: L3 (its round trip is inapplicable, and a rung passed vacuously is not a rung declared).
    metadata = AdapterMetadata(
        id="cesmo_internal",
        name=FORMAT_NAME,
        adapter_version="1.0.0",
        format=FormatRef(name=FORMAT_NAME, version=FORMAT_VERSION),
        binding=WireBinding.PROVISIONAL_INTERNAL_PROFILE,
        direction=Direction.INGEST,
        license_class=LicenseClass.OPEN,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED for the SC CESMO Internal Exchange 1.0 contract "
            "(sc.cesmo.internal/1.0), from evidence that runs today: `python -m "
            "synapse_cdm.harness --adapter cesmo_internal` reports translate, schema, provenance, "
            "lossless (basis: ledger, MAPPINGS declared, no LOST leaf) and golden PASS on every "
            "packaged fixture, and tests/test_cdm_cesmo_internal_adapter.py reproduces the kit's "
            "expected-upsert-cdm.json byte for byte. L4 is NOT declared: the adapter is "
            "ingest-only, so the roundtrip check is inapplicable rather than passed. The rung is "
            "about the internal contract and says nothing about STANAG 4658, whose binding is "
            "BLOCKED.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.PROVISIONAL,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[
                "SC CESMO Internal Exchange 1.0 (contract sc.cesmo.internal/1.0), one Exchange "
                "per call, as UTF-8 JSON octets or a dict: per record an observation Event "
                "(DETECTION), an eob_upsert emitter Entity and its TRACK_UPDATE Event, an "
                "eob_delete or status STATUS_CHANGE Event, and one STATUS_CHANGE Event for an "
                "envelope snapshot",
            ],
            limits=Limits(
                max_input_bytes=MAX_INPUT_BYTES,
                max_depth=MAX_DEPTH,
                max_objects=MAX_OBJECTS,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_decompressed_bytes": "no compression is accepted (kit L234, L247): "
                    "this adapter is handed one already-assembled Exchange, and any transport "
                    "compression is the gateway's, undone under its own bounds before the "
                    "Exchange exists",
                    "max_parse_seconds": "no wall-clock bound is enforced here: the kit's "
                    "two-second decoder deadline is a gateway worker watchdog (kit L243, L247), "
                    "this module reads no clock, and the byte, depth, value and record caps make "
                    "every walk linear in a bounded input; the conformance suite's parser worker "
                    "kills a decode that overruns its deadline",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The CESMO and EOB engineering kit's §19 caps a single internal "
                            "input at 1,048,576 bytes, enforced before the JSON parse "
                            "(`MAX_INPUT_BYTES`, `adapters/cesmo_internal_codec.py`); the kit "
                            "says its caps are implementation caps, not statements about CESMO "
                            "normative maxima. " + _CAP
                        ),
                        enforced_at=(
                            "`CesmoInternalAdapter.to_cdm` is marked `__input_bounded__` at "
                            "class-definition time, so the base class does not wrap it again; it "
                            "calls the SDK's `enforce_input_bound` first and re-raises "
                            "`InputTooLarge` as `CesmoInputTooLarge` (also a `CesmoError`, "
                            "E_LIMIT) before the codec reads an octet; the codec judges the same "
                            "cap on the input octets for a direct caller"
                        ),
                        test="tests/test_cdm_input_bounds.py::"
                        "test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The kit's §19 caps JSON nesting at 16, the root object counted as "
                            "level 1, and the codec enforces that inside (`MAX_CONTRACT_DEPTH`), "
                            "refusing 17 to 64 as E_LIMIT. 64 (`MAX_DEPTH`) is the SDK's bound, "
                            "the figure most JSON-reading adapters of synapse_cdm declare, and at "
                            "least eight times the deepest JSON document this adapter ships "
                            "(tests/test_cdm_parser_safety.py's eight-times rule). " + _CAP
                        ),
                        enforced_at=(
                            "`CesmoInternalAdapter.to_cdm` calls the SDK's "
                            "`enforce_depth_bound` on the JSON text or the dict before the codec "
                            "runs, and re-raises `InputTooDeep` as `CesmoInputTooDeep` (also a "
                            "`CesmoError`, E_LIMIT)"
                        ),
                        test=_TESTS + "test_depth_16_and_64_and_their_successors",
                    ),
                    "max_objects": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The kit's §19 caps CDM objects per Exchange at 2,001: its worst "
                            "case, 1,000 eob_upsert records (an Entity and an Event each) plus "
                            "the snapshot event (`MAX_OBJECTS`). " + _CAP
                        ),
                        enforced_at=(
                            "structurally, before any object is built: the schema's maxItems "
                            "refuses a 1,001st record as E_SCHEMA, a record makes at most two "
                            "objects and an Exchange at most one snapshot event"
                        ),
                        test=_TESTS + "test_the_object_cap_is_reached_exactly_and_not_passed",
                    ),
                },
            ),
            unknown_fields=UnknownFields.NONE,
            unknown_fields_basis=(
                "the contract rejects every key it does not define, at every level, as E_SCHEMA "
                "(kit L102: unknown fields are rejected except inside explicit extensions "
                "objects); a record's `extensions` object is the contract's own open object, "
                "carried whole in residual.data.record like every other leaf, so an injected "
                "unknown key is refused, not preserved"
            ),
        ),
        limitations=[
            Limitation(
                id="provisional-internal-profile",
                summary="the wire form is SC CESMO Internal Exchange 1.0 (sc.cesmo.internal/1.0), "
                "an internal JSON contract defined by this repository's owner in its CESMO and "
                "EOB engineering kit: a provisional internal profile bound to no normative "
                "document. Green gates prove agreement with that contract only",
            ),
            Limitation(
                id="stanag-4658-binding-blocked",
                summary="this adapter is not STANAG 4658 interoperability: no CESMO unit, no "
                "AEDP-13 Edition B message and no native byte is parsed or produced. The "
                "STANAG 4658 / AEDP-13 wire binding is BLOCKED on the kit's unresolved "
                "dependency register N01-N12, and the internal contract's producer, the "
                "gateway, is not in this repository",
            ),
            Limitation(
                id="stateless-translation",
                summary="the EOB state projector, the gateway's journal, receipts, policy and "
                "egress, the offline configuration and the normative edition plugin (kit "
                "sections 13 to 18 and 20) are not in this repository: each Exchange is "
                "translated alone, so a revision, a withdrawal or a complete snapshot is carried "
                "as an assertion and applied to no state, and a reused message_id or a "
                "conflicting revision (E_ID_CONFLICT, E_REVISION_CONFLICT) is not detected here",
            ),
            Limitation(
                id="one-exchange-per-call",
                summary="exactly one Exchange per call, as UTF-8 JSON octets or as a dict; text, "
                "a list, a stream and a chunked snapshot are refused (E_SCHEMA)",
            ),
            Limitation(
                id="octet-only-refusals",
                summary="duplicate keys, a byte order mark, invalid UTF-8, non-finite literals, "
                "numbers past binary64 and the 1,048,576-octet cap are judged on octets only: a "
                "dict was parsed by its caller, who already lost them, and is never "
                "re-serialised to be measured",
            ),
            Limitation(
                id="contract-limits",
                summary="the kit's section 19 caps are enforced as E_LIMIT: 1,048,576 input "
                "octets, nesting 16 containers, 100,000 JSON values and 4,096 code points per "
                "text value or key; 1,000 records is the schema's maxItems (E_SCHEMA); past the "
                "manifest's 64 containers the SDK's InputTooDeep refuses first, raised as "
                "CesmoInputTooDeep, also E_LIMIT",
            ),
            Limitation(
                id="stricter-than-the-kit-validator",
                summary="the adapter refuses what the kit's validate_contract.py 1.0 admits "
                "against its own specification: a token ending in a newline, hour 24 (admitted "
                "on Python 3.14), a non-ASCII digit, and a number past binary64 or underflowing "
                "to zero; it caps the input octets, not a re-serialisation, and reports the "
                "first failure by numeric path order",
            ),
            Limitation(
                id="emitter-entity-only",
                summary="no Track and no PlanObject: one assertion is not a motion history. An "
                "emitter is an Entity of type UNKNOWN with attributes.cesmo.role 'emitter', "
                "made only by an eob_upsert; an observation never fabricates one. No "
                "geolocation, signal identification, emitter correlation or threat ranking is "
                "performed, and severity INFO is a category, not a threat judgement",
            ),
            Limitation(
                id="asserted-position-only",
                summary="a Point geometry and an Entity position exist only for a record's "
                "explicitly asserted emitter position, hae_m as the third coordinate and alt_m; "
                "Position.vertical and accuracy_m stay null, the uncertainty ellipse stays "
                "verbatim in attributes and payload (a probability ellipse is not a one-sigma "
                "scalar), and a bearing never becomes geometry",
            ),
            Limitation(
                id="millisecond-rendering",
                summary="the CDM writes instants to the millisecond: a source time with a "
                "non-zero fourth to sixth fraction digit is truncated in observed_at and "
                "valid_from, its SourceRef lists timestamp-millisecond-truncation-v1, and the "
                "source string stays in payload and residual",
            ),
            Limitation(
                id="binary64-numbers",
                summary="numbers are compared and carried as binary64: the kit's exact-decimal "
                "rule (section 9) governs a native codec's unit conversions, which this adapter "
                "does not perform, so a frequency's digits beyond binary64 are not preserved",
            ),
            Limitation(
                id="synthetic-fixtures-only",
                summary="every packaged fixture is synthetic and labelled so (TEST-NET, "
                "TEST-SOURCE-A, EXERCISE-1, mode synthetic): the kit's five examples carried "
                "byte-identical and documents written from them; nothing is a capture, a native "
                "vector or an order-of-battle datum",
            ),
            Limitation(
                id="evidence-availability",
                summary="the evidence RECORD for this adapter is not IN the distribution: "
                "`evidence/` is untracked and unpackaged, CI generates the set on every "
                "run, and the release pipeline generates the records for every shipped "
                "adapter and attaches them to the GitHub Release of the version it "
                "publishes. `evidence.available` is true because every published "
                "distribution that carries this adapter has that Release, so its records "
                "are retrievable by a third party; it says nothing about what the wheel "
                "contains",
            ),
        ],
        limitations_empty_reason=None,
        residual=ResidualStance.STRUCTURED,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=True),
    )

    #: Nothing is exempted: every leaf survives in the residual, and the canonical projections
    #: are declared in `MAPPINGS`.
    TRANSFORMS: dict[str, str] = {}
    MAPPINGS = _build_mappings()

    def __init__(
        self,
        clock: Any = None,
        *,
        synthetic: bool = True,
        source_hash: SourceHash | dict | None = None,
        cdm_schema: str | None = None,
    ) -> None:
        """`synthetic` defaults to True, the kit's fixtures' partition (kit L154); an Exchange
        whose `mode` disagrees is E_MODE_MISMATCH. `source_hash` is the digest of the Exchange
        a trusted caller computed (the gateway, or the offline host over the file it read), a
        `SourceHash` or `{"algorithm": ..., "value": ...}`, carried onto every object and never
        computed or taken from the document (kit L150). `cdm_schema=None` stamps
        `SCHEMA_VERSION`; `"3.0.0"` stamps the contract the kit's expected output was written
        against. The receipt time is the injected clock's."""
        if type(synthetic) is not bool:
            raise TypeError(f"{_CONFIG} synthetic must be a bool")
        if cdm_schema is not None and (
            type(cdm_schema) is not str or cdm_schema not in (SCHEMA_VERSION, COMPAT_SCHEMA)
        ):
            raise ValueError(f"{_CONFIG} cdm_schema must be None, SCHEMA_VERSION or '3.0.0'")
        super().__init__(clock, synthetic=synthetic)
        self._source_hash = None if source_hash is None else SourceHash.model_validate(source_hash)
        self._schema = COMPAT_SCHEMA if cdm_schema == COMPAT_SCHEMA else SCHEMA_VERSION

    # ------------------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        self._bounds(raw)
        return self._project(codec.validate(raw, synthetic=self._synthetic))

    # The SDK's bounds are run above and re-raised as the contract's E_LIMIT, so the base class
    # must not wrap this method a second time (`adapter._bind_input_bound`).
    to_cdm.__input_bounded__ = True

    @classmethod
    def _bounds(cls, raw: Any) -> None:
        """The SDK's byte and depth bounds, run here and re-raised as the contract's E_LIMIT."""
        try:
            enforce_input_bound(cls, raw)
            if type(raw) is dict:
                # The value cap first, in a walk that stops at its bound: the SDK's depth walk of
                # a cyclic dict, or of one sharing a subtree many times over, would not end.
                codec.count_values(raw)
            enforce_depth_bound(cls, raw)
        except InputTooLarge as refusal:
            raise CesmoInputTooLarge("E_LIMIT", "", str(refusal)) from None
        except InputTooDeep as refusal:
            raise CesmoInputTooDeep("E_LIMIT", "", str(refusal)) from None

    def _project(self, document: dict) -> list[CDMBase]:
        source = document["source"]
        scope = [
            document["mode"],
            source["network_id"],
            source["originator_id"],
            source["identity_epoch"],
        ]
        envelope = {k: v for k, v in document.items() if k != "records"}
        received = self.now()
        out: list[CDMBase] = []
        for index, record in enumerate(document["records"]):
            out.extend(self._record(index, record, scope, envelope, document, received))
        snapshot = document.get("snapshot")
        if snapshot is not None:
            out.append(self._snapshot(snapshot, scope, envelope, document, received))
        return out

    def _stamp(self, original_id: str, index: int | None, observed: Any, transforms: list[str]):
        return self.source_ref().model_copy(
            update={
                "original_id": original_id,
                "source_hash": None
                if self._source_hash is None
                else self._source_hash.model_copy(),
                "record_index": index,
                "observed_at": observed,
                "transformations": list(transforms),
            }
        )

    def _record(self, index, record, scope, envelope, document, received) -> list[CDMBase]:
        observed, truncated = codec.instant(record["observed_at"])
        transforms = [T_IDENTITY] + ([T_TIME] if truncated else [])
        position = record.get("position")
        if position is not None:
            transforms.append(T_METHOD)
        event_type, operation = OPERATIONS[record["kind"]]
        event_key = key(scope + [document["message_id"], record["record_id"]])
        emitter = None
        if "object_id" in record:
            emitter_key = key(scope + [record["object_id"]])
            emitter = (emitter_key, ids.derive(SYSTEM, emitter_key, kind="entity"))
        out: list[CDMBase] = []
        if record["kind"] == "eob_upsert":
            out.append(self._entity(index, record, emitter, observed, transforms, envelope))
        geometry = None
        if position is not None:
            coordinates = [float(position["longitude_deg"]), float(position["latitude_deg"])]
            if "hae_m" in position:
                coordinates.append(float(position["hae_m"]))
            geometry = Point(coordinates=coordinates)
        payload = {
            **copy.deepcopy(record),
            "operation": operation,
            "source_scope": copy.deepcopy(document["source"]),
        }
        out.append(
            Event(
                schema_version=self._schema,
                source=self._stamp(record["record_id"], index, observed, transforms),
                source_ids=[SourceId(system=SYSTEM, external_id=event_key)],
                residual=self._residual(envelope, record),
                event_id=ids.derive(SYSTEM, event_key, kind="event"),
                event_type=event_type,
                severity=Severity.INFO,
                # A status is source-level and names no emitter (kit L164); an eob_delete and an
                # observation with object_id name the scoped emitter whether or not its Entity is
                # in this message (L148).
                related_entities=[] if emitter is None else [emitter[1]],
                geometry=geometry,
                payload={"cesmo": payload},
                observed_at=observed,
                received_at=received,
            )
        )
        return out

    def _entity(self, index, record, emitter, observed, transforms, envelope) -> Entity:
        attributes: dict[str, Any] = {
            "contract": CONTRACT,
            "role": "emitter",
            "operation": "upsert",
            "revision": record["revision"],
        }
        for name in ("uncertainty", "signal"):
            if name in record:
                attributes[name] = copy.deepcopy(record[name])
        attributes["mapping_basis"] = MAPPING_BASIS
        position = record.get("position")
        confidence = record.get("confidence")
        return Entity(
            schema_version=self._schema,
            source=self._stamp(record["record_id"], index, observed, transforms),
            source_ids=[SourceId(system=SYSTEM, external_id=emitter[0])],
            residual=self._residual(envelope, record),
            entity_id=emitter[1],
            entity_type=EntityType.UNKNOWN,
            affiliation=AFFILIATIONS[record.get("affiliation", "UNKNOWN")],
            position=None
            if position is None
            else Position(
                lat=float(position["latitude_deg"]),
                lon=float(position["longitude_deg"]),
                alt_m=float(position["hae_m"]) if "hae_m" in position else None,
                position_source=METHODS[position["method"]],
            ),
            attributes={"cesmo": attributes},
            valid_from=observed,
            confidence=None if confidence is None else float(confidence),
        )

    def _snapshot(self, snapshot, scope, envelope, document, received) -> Event:
        observed, truncated = codec.instant(document["observed_at"])
        transforms = [T_IDENTITY] + ([T_TIME] if truncated else [])
        event_key = key(scope + [document["message_id"], SNAPSHOT_RECORD_ID])
        return Event(
            schema_version=self._schema,
            source=self._stamp(snapshot["snapshot_id"], None, observed, transforms),
            source_ids=[SourceId(system=SYSTEM, external_id=event_key)],
            residual=Residual(namespace=FORMAT_NAME, data={"envelope": copy.deepcopy(envelope)}),
            event_id=ids.derive(SYSTEM, event_key, kind="event"),
            event_type=EventType.STATUS_CHANGE,
            severity=Severity.INFO,
            related_entities=[],
            geometry=None,
            payload={
                "cesmo": {
                    "snapshot": copy.deepcopy(snapshot),
                    "operation": "snapshot",
                    "source_scope": copy.deepcopy(document["source"]),
                }
            },
            observed_at=observed,
            received_at=received,
        )

    @staticmethod
    def _residual(envelope: dict, record: dict) -> Residual:
        return Residual(
            namespace=FORMAT_NAME,
            data={"envelope": copy.deepcopy(envelope), "record": copy.deepcopy(record)},
        )

    # ---------------------------------------------------------------------- the v2 surface

    def detect(self, raw: bytes | dict) -> bool | None:
        """The contract discriminator, never validation (kit L93): a dict's `contract`; octets
        or text parsed leniently, within the declared bounds, False when they are not one JSON
        object; any other type None."""
        if type(raw) is dict:
            return raw.get("contract") == CONTRACT
        if type(raw) in (bytes, bytearray, memoryview):
            try:
                text = bytes(raw).decode("utf-8")
            except UnicodeDecodeError:
                return False
        elif type(raw) is str:
            text = raw
        else:
            return None
        if (
            len(text.encode("utf-8", "surrogatepass")) > MAX_INPUT_BYTES
            or json_nesting_depth(text) > MAX_DEPTH
        ):
            return False
        try:
            document = json.loads(text)
        except ValueError:
            return False
        return type(document) is dict and document.get("contract") == CONTRACT

    def validate_source(self, raw: bytes | dict) -> list[str]:
        """The contract's diagnostics, `"<CODE> <path> <detail>"` each, in the order `to_cdm`
        judges them (the first is the refusal it raises); `[]` for an accepted Exchange. Never
        raises for a refusal, and never quotes the payload."""
        try:
            self._bounds(raw)
        except CesmoError as refusal:
            return [str(refusal)]
        return codec.diagnostics(raw, synthetic=self._synthetic)
