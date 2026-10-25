"""What the three STANAG 4559 translators share: the abstract base `Stanag4559Adapter`, their
declaration, their ledger and their one wrapper rule (SC ISR 4559 001, revision 1.0 of 4 October
2026, sections 5, 9 and 20).

Not an adapter: the base is `abstract`, so it registers nothing, and each of
`stanag4559_catalog`, `stanag4559_stream` and `stanag4559_workflow` defines its OWN `to_cdm`
that calls `Stanag4559Adapter.translate`. That is not style. `adapter._bind_input_bound` wraps the
class that DEFINES `to_cdm`, and an abstract base is never wrapped, so a decoder inherited from
one would run with no size or depth bound at all (`tests/test_cdm_stanag4559_catalog_adapter.py`
shows the trap on a test double).

THE CAPABILITY REPORT (DECISIONS L-01 of the arc that landed these translators, 2026-10-24)
-----------------------------------------------------------------------------------------
What is implemented: the PURE TRANSLATION LAYER of the specification — `synapse_cdm/isr_record.py`
(the record contract `urn:synapsecommand:isr:record:1`, section 6's transport rules, section 28's
second pass, section 7's identity) and the three ingest-only translators, each turning one record
of its family into exactly one `STATUS_CHANGE` `Event` (section 9).

What is NOT implemented, and is not part of this distribution: the stateful ISR gateway of
sections 5 to 7 and 10 to 19 (`packages/isr-gateway`: authentication, authorisation, the policy
service, persistence, product transfer, CORBA and SOAP sessions, subscriptions, stream replay
control, workflow mutation). Every wire profile of section 3 — C17 (AEDP-17 library access), S18
(AEDP-18 streams) and W19 (AEDP-19 workflow) — is UNIMPLEMENTED. No STANAG 4559 or AEDP-17/18/19
wire message is read or written here, no NATO binding package (IDL, WSDL, XSD, metadata
dictionary) is held, no peer was exercised, and no NATO wire interoperability is claimed: the
bundle's own `nato_wire_compatibility_verified: false` stands. The input is this project's
internal record, which section 6 says "is not a representation to send to a NATO peer"; that is
why the binding is `provisional-internal-profile` and the claim `PROVISIONAL` (section 9: "do not
relabel local JSON as standard NATO wire encoding").

WHERE EACH RULE COMES FROM
--------------------------
- One record -> one Event, `event_type` STATUS_CHANGE, `severity` INFO, the record verbatim under
  `payload.record` beside `kind`, `record_id`, `revision_key` and `time_basis` (section 9).
- `observed_at`: `source_time` when the record states one (`time_basis` SOURCE), otherwise the
  gateway's `captured_at` (`time_basis` GATEWAY_RECEIPT); `source.observed_at` is `source_time`
  or null, never invented; `received_at` is the injected clock (section 9). A body time
  (`modified_at`, `source_changed_at`) is never promoted to `observed_at` (section 28).
- `geometry`: the catalogue or stream `coverage`, or a workflow record's `geometry` when its
  service is `gaoi` ("workflow GAOI geometry"), validated by section 28's polygon rules;
  otherwise null. No Entity, no target point at a box's centre (sections 8 and 9).
- `source`: system NSILI, the translator's own name and version, format "SC ISR gateway record"
  1.0.0, `original_id` = `origin.object_id`, `source_hash` = sha256 and `raw_ref.sha256`,
  `record_index` 0, `transformations` = ["ISR-ID-001"] (section 9; `isr_record` defines the rule).
- `source_ids`: one `{system: NSILI, external_id: object_key}` (section 9).
- Refusals before any output, one code per rule (`isr_record.IsrRecordRefused`; this module adds
  `wrong-family` for a record handed to another family's translator).

DEVIATIONS FROM THE SPECIFICATION (DECISIONS section C of the arc)
-----------------------------------------------------------------
- The specification's sequence DOCUMENTED -> IMPLEMENTED -> PROVISIONAL is not what this
  repository admits: a `provisional-internal-profile` binding claims PROVISIONAL from the start
  (`tests/test_cdm_manifests.py`).
- `source.source_hash` cannot record the capture representation section 9 asks for: `SourceHash`
  is closed. The representation (`wire` or `decoded`) survives at
  `payload.record.raw_ref.representation`.
- `time_basis` value SOURCE is taken from the bundle's goldens; the specification's text names only
  GATEWAY_RECEIPT.
- No gateway, no wire profile, no peer exercise (above).

THE RESIDUAL STANCE (DECISIONS L-03, 2026-10-24)
------------------------------------------------
`residual: legacy`. The bundle's goldens, which are the specification's acceptance oracle
(CDM-001), carry `"residual": null` and the whole record under `payload.record`, so a structured
container would duplicate the record and change the bytes. ARCHITECTURE.md section 5 records this
dated exception to "every Part 2 adapter uses the structured container".
"""

from __future__ import annotations

import copy
from typing import Any, ClassVar

from synapse_cdm import ids, isr_record, lossless, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.enums import EventType, Severity
from synapse_cdm.manifest import (
    AdapterMetadata,
    Capabilities,
    ClaimStatus,
    Direction,
    Evidence,
    FormatRef,
    LicenseClass,
    LimitBasis,
    Limitation,
    LimitKind,
    Limits,
    Maturity,
    MaturityLevel,
    Residual as ResidualStance,
    UnknownFields,
    WireBinding,
)
from synapse_cdm.models import CDMBase, Event, SourceHash, SourceId

#: Section 20's `max_metadata_bytes`, 16 MiB, taken as the bound on one record (see `metadata`).
MAX_INPUT_BYTES = 16_777_216
#: Eight times the deepest JSON document shipped beside these fixtures (a workflow golden nesting
#: eleven containers, 88), rounded up to a multiple of 32 (see `metadata`). The record module's own
#: bound, declared here as the translators' `max_depth`, so the base class refuses at the number
#: `isr_record.parse` and `isr_record.validate` hold for a direct caller.
MAX_DEPTH = isr_record.MAX_DEPTH

#: The time bases `payload.time_basis` states (section 9; SOURCE from the bundle's goldens).
TIME_BASIS_SOURCE = "SOURCE"
TIME_BASIS_RECEIPT = "GATEWAY_RECEIPT"

#: The workflow service whose geometry is projected to `Event.geometry` (section 9).
GAOI_SERVICE = "gaoi"

_TESTS = "tests/test_cdm_{name}_adapter.py::"

#: Section 7's identity components, each DERIVED into `object_key` or `revision_key` by
#: `ISR-ID-001` and carried verbatim under `payload.record` as well.
_IDENTITY_COMPONENTS = {
    "tenant_id": "object_key",
    "security_domain": "object_key",
    "origin.authority": "object_key",
    "family": "object_key",
    "origin.object_id": "object_key",
    "revision.token": "revision_key",
    "revision.semantic_sha256": "revision_key",
}


def transforms() -> dict[str, str]:
    """`TRANSFORMS`: the identity components and the rule that derives the keys from them."""
    return {
        path: (
            f"derived: {isr_record.IDENTITY_RULE}, a component of the canonical JSON array whose "
            f"unpadded base64url is the {key} (SC ISR 4559 001 section 7); the value itself is "
            "carried verbatim under payload.record"
        )
        for path, key in _IDENTITY_COMPONENTS.items()
    }


def mappings(family: str) -> dict[str, Any]:
    """`MAPPINGS`: every projection named, and the whole record a residual subtree under
    `payload.record` (the empty key is the document itself). A workflow record's geometry is
    projected only for service `gaoi`, so the workflow ledger leaves it to the residual."""
    record = "event:payload.record"
    M = lossless.Mapping
    declared: dict[str, Any] = {
        "origin.object_id": (M("event:source.original_id"), M(f"{record}.origin.object_id")),
        "raw_ref.sha256": (M("event:source.source_hash.value"), M(f"{record}.raw_ref.sha256")),
        "kind": (M("event:payload.kind"), M(f"{record}.kind")),
        "source_time": (
            M(
                "event:source.observed_at",
                "absent_if",
                params={"sentinel": None, "else": "instant"},
            ),
            M(f"{record}.source_time"),
        ),
    }
    if family in ("catalog", "stream"):
        declared.update(
            {
                "body.coverage.type": (M("event:geometry.type"), M(f"{record}.body.coverage.type")),
                "body.coverage.coordinates[*][*][*]": (
                    M("event:geometry.coordinates[*][*][*]", "number"),
                    M(f"{record}.body.coverage.coordinates[*][*][*]"),
                ),
                "body.coverage.coordinates[*][*][*][*]": (
                    M("event:geometry.coordinates[*][*][*][*]", "number"),
                    M(f"{record}.body.coverage.coordinates[*][*][*][*]"),
                ),
            }
        )
    declared[""] = M(record, kind="residual")
    return declared


def metadata(
    name: str, title: str, family: str, message_type: str, extra: list[Limitation]
) -> AdapterMetadata:
    tests = _TESTS.format(name=name)
    return AdapterMetadata(
        id=name,
        name=title,
        adapter_version=isr_record.ADAPTER_VERSION,
        format=FormatRef(name=isr_record.FORMAT_NAME, version=isr_record.FORMAT_VERSION),
        # The record contract is this project's internal profile, not a NATO encoding (section 6;
        # DECISIONS L-04), and `manifest.py` holds a provisional binding to PROVISIONAL.
        binding=WireBinding.PROVISIONAL_INTERNAL_PROFILE,
        direction=Direction.INGEST,
        # OPEN: the format is this project's own record contract, carried in this tree under its
        # licence; no NATO publication is read or carried by these translators.
        license_class=LicenseClass.OPEN,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis=(
                f"L3 PROVENANCE VERIFIED, from evidence that runs today: `python -m "
                f"synapse_cdm.harness --adapter {name}` reports translate, schema, provenance, "
                "lossless (basis: ledger, MAPPINGS declared, no LOST leaf) and golden PASS on "
                f"every fixture, and {tests.rstrip(':')} reproduces the specification bundle's "
                f"three expected Events for the {family} family byte for byte. Every fixture is "
                "synthetic: the bundle's records, written for SC ISR 4559 001, with any footprint "
                "moved into this repository's Baltic rectangle. L4 is NOT declared: the adapter "
                "is ingest-only, so the roundtrip check is inapplicable rather than passed, and a "
                "rung passed vacuously is not a rung declared. No NATO binding package, wire "
                "message or peer is part of this evidence."
            ),
            external_exercise=None,
        ),
        claim_status=ClaimStatus.PROVISIONAL,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[message_type],
            limits=Limits(
                max_input_bytes=MAX_INPUT_BYTES,
                max_depth=MAX_DEPTH,
                max_objects=None,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_objects": "one record yields exactly one Event",
                    "max_decompressed_bytes": "no compressed payload is accepted: a record is "
                    "JSON text, and the raw capture its raw_ref names is never opened",
                    "max_parse_seconds": "no wall-clock bound is enforced: the translator reads "
                    "no clock. Its passes are linear in the record except section 28's polygon "
                    "pass, which is quadratic in one geometry's positions and is held to "
                    "isr_record.MAX_GEOMETRY_POSITIONS (refused geometry-over-cap before it "
                    "runs); section 20's parse_timeout_seconds is the gateway's isolated-worker "
                    "timeout, and the conformance suite's parser worker kills a decode that "
                    "overruns its deadline",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "SC ISR 4559 001 section 20 states max_metadata_bytes = 16777216 "
                            "('16 MiB uncompressed per response/record boundary') as a PROJECT "
                            "OPERATING DEFAULT of the gateway's configuration; it is not the "
                            "normative maximum of any standard, and the record contract states "
                            "none. The translator takes the same figure for one record "
                            "(`MAX_INPUT_BYTES`, `adapters/stanag4559_common.py`), so a record "
                            "the gateway's default admits is a record it admits. This is an "
                            "IMPLEMENTATION CAP and is NOT the format's normative maximum."
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps each translator's own `to_cdm` "
                            "with `enforce_input_bound` at class-definition time, so the octets "
                            "are measured and refused before `isr_record.parse` decodes them"
                        ),
                        test="tests/test_cdm_input_bounds.py::"
                        "test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The record contract states no nesting bound, and section 20's "
                            "max_xml_depth (64) bounds the gateway's XML decoding, not this JSON "
                            "record. A record nests eight containers at its deepest typed member "
                            "(a workflow graph attribute), and the deepest JSON document shipped "
                            "beside these fixtures is a workflow golden nesting eleven; 96 "
                            "(`isr_record.MAX_DEPTH`, `isr_record.py`) is eight times that, "
                            "rounded up to a multiple of 32. This is an IMPLEMENTATION CAP and is "
                            "NOT the format's normative maximum: the graph attribute `value` and "
                            "stream `replay_capabilities` are open JSON the contract does not "
                            "bound."
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__`'s wrapper calls "
                            "`adapter.enforce_depth_bound` on the JSON text or the parsed dict "
                            "before the translator's `to_cdm` runs"
                        ),
                        test="tests/test_cdm_parser_safety.py::"
                        "test_the_json_adapters_declare_a_depth_bound_and_refuse_a_document_past_it",
                    ),
                },
            ),
            unknown_fields=UnknownFields.NONE,
            unknown_fields_basis=(
                "the record contract is closed at every level and section 6 rejects unknown "
                "keys, so a key it does not define is REFUSED (unknown-key), never carried. "
                "Source extension material travels where the contract puts it — typed nodes and "
                "attributes of the body's graph, and stream replay_capabilities — and is carried "
                "verbatim under payload.record with the rest of the record"
            ),
        ),
        limitations=[
            Limitation(
                id="provisional-internal-profile",
                summary="provisional internal profile: the input is the SynapseCommand internal "
                "ISR gateway record urn:synapsecommand:isr:record:1 (SC ISR 4559 001 section 6), "
                "a contract chosen in this project and not a NATO encoding; no STANAG 4559 or "
                "AEDP-17/18/19 wire message is read, no NATO binding package is held, and no NATO "
                "wire interoperability is claimed (nato_wire_compatibility_verified: false)",
            ),
            Limitation(
                id="no-gateway",
                summary="the stateful ISR gateway of the specification (authentication, "
                "authorisation, policy, persistence, product transfer, CORBA and SOAP sessions, "
                "subscriptions, replay control, workflow mutation) is not part of this "
                "distribution; the C17, S18 and W19 wire profiles are UNIMPLEMENTED and no peer "
                "was exercised",
            ),
            Limitation(
                id="transport-rules-on-octets",
                summary="section 6's transport rules (no byte-order mark, strict UTF-8, no "
                "duplicate key, no NaN or infinity, no trailing document, integers within "
                "2**53-1) are enforced on octets or text; a parsed dict has passed through the "
                "caller's decoder first, which may already have collapsed a duplicate key",
            ),
            Limitation(
                id="digests-copied",
                summary="revision.semantic_sha256 and raw_ref.sha256 are copied, never "
                "recomputed: section 6 gives digest validation to the gateway, and only their "
                "syntax (64 lower-case hex digits) is checked here",
            ),
            Limitation(
                id="labels-carried-not-enforced",
                summary="security labels are carried verbatim in payload.record and enforce "
                "nothing (section 9: every event travels in an authenticated access-controlled "
                "gateway envelope); a DECLARED label's scheme is not checked against a policy "
                "vocabulary, which no binding package supplies",
            ),
            Limitation(
                id="dictionary-cardinality",
                summary="the metadata graph is held to the record contract's own cardinality "
                "only (unique node ids, resolving edges, contiguous occurrences of a repeated "
                "attribute, nil without a value); which attributes may repeat is a versioned "
                "NATO metadata dictionary's to say, none is held, so a conflicting duplicate of "
                "a scalar attribute is not detected (acceptance cases PARSE-009 and PARSE-010)",
            ),
            Limitation(
                id="observed-at-receipt-time",
                summary="a record with no source_time is an Event of the gateway's receipt: "
                "observed_at is captured_at and payload.time_basis is GATEWAY_RECEIPT (section "
                "9), so a consumer reads time_basis before treating observed_at as a source time",
            ),
            Limitation(
                id="source-hash-representation",
                summary="source.source_hash carries raw_ref.sha256 only: the capture "
                "representation section 9 asks to record beside it survives at "
                "payload.record.raw_ref.representation, because SourceHash is closed",
            ),
            Limitation(
                id="polygon-topology",
                summary="section 28's polygon topology is decided edge by edge and vertex by "
                "vertex in exact arithmetic (closed, distinct, non-degenerate, simple rings; no "
                "crossing or overlapping edges between rings; interior rings inside their "
                "exterior and not inside each other; MultiPolygon parts not inside one another "
                "at a vertex); interior connectivity is not decided, and a geometry of more than "
                f"{isr_record.MAX_GEOMETRY_POSITIONS} positions is refused (geometry-over-cap)",
            ),
            *extra,
            Limitation(
                id="residual-legacy",
                summary="the whole record is carried verbatim under payload.record and "
                "Event.residual is null, the specification's golden form; residual: legacy by "
                "the dated ruling of 2026-10-24 (ARCHITECTURE.md section 5)",
            ),
            Limitation(
                id="ingest-only",
                summary="ingest only: from_cdm is the inherited refusal, and the gateway's "
                "outbound commands are separate contracts (section 5), never an Event",
            ),
            Limitation(
                id="synthetic-fixtures-only",
                summary="every fixture is synthetic: the specification bundle's records, with "
                "any footprint moved into CONTRIBUTING.md's Baltic rectangle and the semantic "
                "digest recomputed by the bundle's rule; no recorded record is evidence here",
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
        residual=ResidualStance.LEGACY,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=True),
    )


class Stanag4559Adapter(Adapter):
    """The wrapper rule of section 9, once, for the three family translators."""

    abstract = True

    #: The record family this translator takes (`catalog`, `stream` or `workflow`).
    FAMILY: ClassVar[str] = ""

    def translate(self, raw: Any) -> list[CDMBase]:
        if isinstance(raw, (bytes, bytearray, memoryview, str)):
            record = isr_record.parse(raw)
        else:
            record = raw
        isr_record.validate(record)
        # A copy, so the Event never aliases the caller's dict; taken after `validate`, which has
        # proved it plain JSON.
        record = copy.deepcopy(record)
        if record["family"] != self.FAMILY:
            raise isr_record.IsrRecordRefused(
                "wrong-family",
                f"/family: {self.name} translates the {self.FAMILY} family and this record is of "
                "another family",
            )
        okey = isr_record.object_key(record)
        rkey = isr_record.revision_key(record)
        source_time = record["source_time"]
        observed = times.parse(source_time if source_time is not None else record["captured_at"])
        source = self.source_ref().model_copy(
            update={
                "original_id": record["origin"]["object_id"],
                "source_hash": SourceHash(algorithm="sha256", value=record["raw_ref"]["sha256"]),
                "record_index": 0,
                "observed_at": None if source_time is None else observed,
                "transformations": [isr_record.IDENTITY_RULE],
            }
        )
        body = record["body"]
        if self.FAMILY == "workflow":
            geometry = body["geometry"] if body["service"] == GAOI_SERVICE else None
        else:
            geometry = body["coverage"]
        event = Event(
            source=source,
            source_ids=[SourceId(system=isr_record.SYSTEM, external_id=okey)],
            event_id=ids.derive(isr_record.SYSTEM, rkey, kind="event"),
            event_type=EventType.STATUS_CHANGE,
            severity=Severity.INFO,
            related_entities=[],
            geometry=None if geometry is None else copy.deepcopy(geometry),
            payload={
                "kind": record["kind"],
                "record_id": str(ids.derive(isr_record.SYSTEM, okey, kind="isr-record")),
                "revision_key": rkey,
                "time_basis": TIME_BASIS_SOURCE if source_time is not None else TIME_BASIS_RECEIPT,
                "record": record,
            },
            observed_at=observed,
            received_at=self.now(),
        )
        return [event]
