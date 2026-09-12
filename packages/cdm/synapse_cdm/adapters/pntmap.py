"""PNTMAP GNSS interference alert -> one Entity (the emitter) + one Event (the interference).

THE REFERENCE ADAPTER. It is worth reading before writing adapter #2 because every rule the
CDM cares about shows up here at least once:

- ONE payload, TWO objects. The alert describes a thing that exists (an interference source,
  at a place, over an interval) and a thing that happened (interference, observed, over an
  area). Those are different canonical kinds and forcing them into one would lose whichever
  half the container was not shaped for.
- NO BUSINESS LOGIC, demonstrated where it is most tempting. A jamming emitter is almost
  certainly hostile, and this adapter still writes `affiliation: UNKNOWN` unless the payload
  states an attribution. Inferring HOSTILE would be an intelligence judgement made inside a
  translator, invisible to the audit trail, and unattributable — and it would be wrong the
  first time the "jammer" turns out to be a friendly EW exercise. The source's own words are
  kept in `attributes`; the judgement is the fusion layer's to make, on the record.
- UNKNOWN POSITION STAYS NULL. An alert with no geolocated emitter produces an entity with
  `position: None`, never (0, 0) — see fixtures/spoofing_no_geolocation.json.
- NEVER DROP. Everything not mapped to a canonical field is parked by `lossless.residual()`
  under `attributes.source_extras` / `payload.source_extras`, so a field this adapter has
  never seen still arrives intact.
- THE DECLARED TRANSFORM. `alert_time` is re-rendered into the CDM's fixed-millisecond form,
  so its string changes and the lossless check would flag it. It is declared in TRANSFORMS
  with a reason, and the harness prints that reason on every run.
- DERIVED IDENTITY WITH A STATED BASIS. `entity_id` is uuid5 over the emitter's own id when
  the payload has one, and over the alert id when it does not — and the basis is recorded in
  `attributes`, because an id keyed on a per-alert field is NOT stable across alerts and a
  consumer accumulating a track needs to know that.

THE SC-OES REFERENCE PRODUCER, AND WHAT IT REFUSES TO SAY
---------------------------------------------------------
This is the one adapter in this repository that emits SC-OES wire semantics. Every other adapter
stays CDM Conformant without being an SC-OES semantic producer, and that distinction is
deliberate (`spec/sc-oes/profiles/pnt.md`, "Implementation status").

The block carries THREE fields:

    oes.spec_version  the SC-OES version whose semantics this producer claims — SC_OES_VERSION,
                      because a producer inside this repository claims this repository's spec
    oes.event_class   OBSERVATION, ASSERTED as a literal. `02-event-classes.md` forbids deriving
                      the class from `type_id`, from the payload or from the producer's identity,
                      so it is written here rather than looked up in the event registry
    oes.type_id       sc.pnt.gnss_interference.v1, the governed type the PNT profile scopes

and every remaining field of `OesMetadata` is left at its "nothing is asserted" default. Each one
was decided by reading the source, not by reading this list:

- `confidence` — THE ONE THAT IS NOT OBVIOUS. PNTMAP does supply `interference.confidence` on
  every alert, so emitting it would not be fabrication. It is not emitted because that number is
  already carried, unchanged, at `Entity.confidence` on the emitter this event relates to: the
  producer states one confidence and the CDM already has it, and restating it under a second
  subject would put one source number in two places with two meanings. Nothing is lost, and the
  field stays available to a later round that decides the observation is where the number belongs.
- `verification` — the source never says whether anything corroborated the alert.
  `06-verification-and-confidence.md`: an implementation MUST NOT default it to `UNVERIFIED`.
- `status` — PNTMAP reports an occurrence, not a managed condition, and never names a lifecycle
  state. `05-lifecycle.md` forbids defaulting it to `ACTIVE`.
- `effective_from` — the only candidate is `alert_time`, which is already `observed_at`, and
  `04-temporality.md` forbids defaulting the effective interval to the observation time.
- `effective_to` — `valid_until` is how long the ALERT stands, not when the interference ceases.
  Reading one as the other would put a statement about a message onto the world.
- `security` — no marking of any kind appears anywhere in the source.
- `entity_relations` — the emitter is already in `related_entities`; what the source does not give
  is a ROLE, and a role here has to be a governed ontology term. Choosing one would be the
  intelligence judgement the second bullet above refuses.
- `event_relations`, `evidence`, `extensions` — one alert, no cited artefact, and every vendor
  field already rides through into `source_extras` losslessly.

PAYLOAD SHAPE (synthetic, representative — no real PNTMAP data in this repository)
---------------------------------------------------------------------------------
    {
      "alert_id": "PNTMAP-2026-04-29-0117",
      "alert_time": "2026-04-29T06:12:44Z",
      "valid_until": "2026-04-29T07:00:00Z",          optional
      "severity": "critical",                          info | advisory | warning | critical
      "interference": {"type": "jamming",              jamming | spoofing | unknown
                       "band": "L1",
                       "signal_strength_dbm": -71.5,
                       "confidence": 0.87},
      "emitter": {"emitter_id": "EMT-4471",            optional - see identity basis above
                  "lat": 57.512, "lon": 21.884,        optional - absent means unknown
                  "geolocation_method": "tdoa",
                  "accuracy_m": 2500,
                  "attribution": "hostile"},           optional - the ONLY thing that may set
                                                       affiliation
      "affected_area": {GeoJSON Polygon},              optional
      ...anything else rides through into source_extras
    }
"""
from __future__ import annotations

import json
from typing import Any

from synapse_cdm import ids, lossless
from synapse_cdm.adapter import Adapter
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    InterferenceType,
    PositionSource,
    Severity,
)
from synapse_cdm.models import CDMBase, Entity, Event, Position
from synapse_cdm.oes import EventClass, OesMetadata
from synapse_cdm.symbology import sidc_from_affiliation
from synapse_cdm.version import SC_OES_VERSION
from synapse_cdm.manifest import (AdapterMetadata, Capabilities, ClaimStatus, Direction, Evidence,
                                   FormatRef, LicenseClass, LimitBasis, LimitKind, Limits,
                                   Maturity, MaturityLevel, Residual, UnknownFields)

SYSTEM = "PNTMAP"

# The governed SC-OES semantic type this producer claims. A LITERAL, and deliberately so: it is
# the producer's own assertion about what it is emitting, and reading it out of the packaged
# registry would make the claim depend on the registry rather than stand beside it. The registry
# is the authority on what the identifier MEANS; a test checks the two agree, which is a
# consistency check and not a derivation.
OES_TYPE_ID = "sc.pnt.gnss_interference.v1"

# The source's vocabulary -> ours. A value absent from a table is NOT silently defaulted: it
# raises for severity (an alert whose urgency we cannot read must not arrive labelled INFO)
# and resolves to UNKNOWN for interference type and affiliation (both have a member that
# means exactly "not known", so using it states the truth rather than guessing).
SEVERITY = {
    "info": Severity.INFO,
    "advisory": Severity.ADVISORY,
    "warning": Severity.WARNING,
    "critical": Severity.CRITICAL,
}
INTERFERENCE = {
    "jamming": InterferenceType.JAMMING,
    "spoofing": InterferenceType.SPOOFING,
    "unknown": InterferenceType.UNKNOWN,
}
ATTRIBUTION = {
    "hostile": Affiliation.HOSTILE,
    "friendly": Affiliation.FRIENDLY,
    "neutral": Affiliation.NEUTRAL,
    "unknown": Affiliation.UNKNOWN,
}
# How PNTMAP says it geolocated the emitter -> what that means for trusting the position.
# Everything here is ESTIMATED or better-stated; `tdoa` and `aoa` are inferred fixes, not
# reported ones, and calling them GNSS would be absurd for an alert about GNSS being denied.
GEOLOCATION = {
    "tdoa": PositionSource.ESTIMATED,
    "aoa": PositionSource.ESTIMATED,
    "reported": PositionSource.MANUAL,
    "surveyed": PositionSource.MANUAL,
}


class PntmapAdapter(Adapter):
    name = "pntmap"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    #: Adapter API v2's declaration (ARCHITECTURE.md §3). Licence class from
    #: `spec/sc-oes/README.md` — "These materials inherit this repository's Apache-2.0
    #: licensing"; the payload is first-party
    metadata = AdapterMetadata(
        id="pntmap",
        name="PNTMAP",
        adapter_version="1.0.0",
        format=FormatRef(name="PNTMAP GNSS interference alert",
                         version=None),
        direction=Direction.INGEST,
        license_class=LicenseClass.OPEN,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED, from evidence that runs today. The harness's "
                  "`translate`, `schema` and `provenance` checks are PASS on every fixture of "
                  "this adapter. L4 is NOT declared and is not merely unproven: this adapter "
                  "is ingest-only, so there is no egress direction for information to be lost "
                  "in and the roundtrip check is inapplicable rather than absent "
                  "(ARCHITECTURE.md §3.6, rule 4). A rung passed vacuously is not a rung "
                  "declared, so the declaration stops at the last one positively verified.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        profiles=["PNT"],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[
                "GNSS interference alert — one alert becomes an INTERFERENCE_SOURCE entity "
                "and a `sc.pnt.gnss_interference.v1` event",
            ],
            limits=Limits(
                max_input_bytes=1048576,
                max_depth=None,
                max_objects=None,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_depth":
                        "a PNTMAP alert is JSON and nests to a fixed shallow shape; no depth "
                        "bound is declared yet",
                    "max_objects":
                        "no bound is enforced by this adapter today; the parser-safety "
                        "policy's concrete bounds are owed by P5 (ARCHITECTURE.md §9)",
                    "max_decompressed_bytes":
                        "this adapter accepts no archived or compressed payload, so there is "
                        "no expansion to bound",
                    "max_parse_seconds":
                        "no wall-clock bound is enforced by this adapter today; the "
                        "parser-safety policy's concrete bounds are owed by P5 "
                        "(ARCHITECTURE.md §9)",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "A PNTMAP GNSS interference alert is a JSON document and no "
                            "document in this tree states a maximum for one. 1 MiB is chosen "
                            "from the parser audit: the payload reaches `json.loads` "
                            "(`adapters/pntmap.py:375`) and the largest PNTMAP fixture in this "
                            "package is 719 octets. This is an IMPLEMENTATION CAP under M's "
                            "F5.4 ruling and is NOT the format's normative maximum."),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the payload is measured and refused "
                            "before any decoder in this module runs"),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                },
            ),
            unknown_fields=UnknownFields.PRESERVED,
            unknown_fields_basis=(
                "a PNTMAP alert IS a JSON document carrying vendor fields; every key this adapter "
                "does not consume is parked verbatim under `source_extras`"),
        ),
        limitations=[
            "no document in this repository DEFINES the PNTMAP alert payload — "
            "FORMAT_COVERAGE.md carries no PNTMAP section — so there is no edition to name "
            "and `format.version` is null; the licence class rests on the payload being "
            "first-party rather than on a licensing sentence about the format",
            "ingest only: this adapter does not emit PNTMAP alerts",
            "leftovers are parked in `Entity.attributes` / `Event.payload` under "
            "`source_extras` (`lossless.residual()`), not in the origin-identifying container "
            "ARCHITECTURE.md §5 gives to P3 — the Part 1 stance that section rules for the "
            "adapters already shipped",
            "the evidence RECORD for this adapter is not IN the distribution: `evidence/` is "
            "untracked and unpackaged, CI generates the set on every run and the release "
            "pipeline attaches it to the GitHub Release. `evidence.available` is true because "
            "the records for 2.1.2 are attached to the `v2.1.2` Release and retrievable by a "
            "third party, and it says nothing about what the wheel contains",
            "of §3.5's five resource limits this adapter enforces ONE — `max_input_bytes`, "
            "declared in `capabilities.limits` with its basis beside it and refused before "
            "decode by the base class (round P5). The other four are still absent, each with "
            "its own reason in `capabilities.limits.absent_because`; a depth, object-count, "
            "decompression or wall-clock bound is not enforced here today",
        ],
        limitations_empty_reason=None,
        residual=Residual.LEGACY,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=True),
    )

    TRANSFORMS = {
        "alert_time": "re-rendered from the source's second-precision Z form into the CDM's "
                      "fixed three-decimal form (times.render) — same instant, different "
                      "string",
        "valid_until": "re-rendered into the CDM's fixed three-decimal form (times.render)",
        "emitter.geolocation_method": "mapped to the PositionSource enum; the source's own "
                                      "word is kept at attributes.source_extras."
                                      "geolocation_method",
    }

    # Dotted paths this adapter maps to canonical fields. Everything else is collected by
    # lossless.residual() and parked. Kept as data rather than buried in the code below so
    # that "what does this adapter understand?" is answerable by reading one list.
    CONSUMED_TOP = ("alert_id", "alert_time", "valid_until", "severity")
    CONSUMED_INTERFERENCE = ("interference.type", "interference.band",
                             "interference.signal_strength_dbm", "interference.confidence")
    CONSUMED_EMITTER = ("emitter.emitter_id", "emitter.lat", "emitter.lon",
                        "emitter.geolocation_method", "emitter.accuracy_m",
                        "emitter.attribution")

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        alert = self._as_dict(raw)
        for required in ("alert_id", "alert_time", "interference"):
            if not alert.get(required):
                raise ValueError(
                    f"PNTMAP alert is missing {required!r} — refusing to translate a partial "
                    f"alert; keys present: {sorted(alert)}"
                )

        interference = alert["interference"] or {}
        emitter = alert.get("emitter") or {}
        source = self.source_ref()

        severity_word = str(alert.get("severity", "")).lower()
        if severity_word not in SEVERITY:
            raise ValueError(
                f"unknown PNTMAP severity {alert.get('severity')!r}; known: "
                f"{', '.join(SEVERITY)}. Refused rather than defaulted — an alert that "
                "arrives labelled INFO because its severity was unreadable is worse than one "
                "that fails loudly"
            )

        affiliation = ATTRIBUTION.get(str(emitter.get("attribution", "")).lower(),
                                      Affiliation.UNKNOWN)

        entity_id, id_basis = ids.derive_with_basis(
            SYSTEM,
            {"emitter.emitter_id": emitter.get("emitter_id"),
             "alert_id": alert.get("alert_id")},
            kind="entity",
        )
        event_id = ids.derive(SYSTEM, alert["alert_id"], kind="event")

        # The entity keeps the ALERT-level leftovers and the emitter's own leftovers. The
        # `interference` subtree is consumed WHOLE here — it is the event's subject, and
        # parking its leftovers on both objects would duplicate them, which is not loss but
        # is noise, and noise in an extension bag is where real fields go to hide.
        entity_extras = lossless.residual(
            alert,
            (*self.CONSUMED_TOP, *self.CONSUMED_EMITTER, "interference", "affected_area"),
        )
        # The emitter's consumed-but-remapped words, kept verbatim under their original key
        # so the source's structure is recoverable. `geolocation_method` is declared in
        # TRANSFORMS *and* kept here: the declaration explains the change, this keeps the
        # original readable.
        for key in ("geolocation_method", "attribution"):
            if emitter.get(key) is not None:
                entity_extras.setdefault("emitter", {})[key] = emitter[key]

        entity = Entity(
            source=source,
            entity_id=entity_id,
            source_ids=[{"system": SYSTEM, "external_id": str(
                emitter.get("emitter_id") or alert["alert_id"])}],
            entity_type=EntityType.INTERFERENCE_SOURCE,
            affiliation=affiliation,
            symbol=sidc_from_affiliation(affiliation, synthetic=self._synthetic),
            position=self._position(emitter),
            valid_from=alert["alert_time"],
            valid_to=alert.get("valid_until"),
            confidence=interference.get("confidence"),
            attributes={
                # Stated, not implied: a consumer accumulating this emitter across alerts has
                # to know whether the id it is keying on is stable.
                "entity_id_basis": id_basis,
                "symbol_basis": "derived from affiliation; the source states no SIDC",
                "interference_type": str(interference.get("type", "")).lower() or None,
                "source_extras": entity_extras,
            },
        )

        payload: dict[str, Any] = {
            "frequency_band": interference.get("band") or "UNKNOWN",
            "interference_type": INTERFERENCE.get(
                str(interference.get("type", "")).lower(), InterferenceType.UNKNOWN).value,
            "signal_strength_dbm": interference.get("signal_strength_dbm"),
            "source_extras": lossless.residual(
                {"interference": interference},
                self.CONSUMED_INTERFERENCE,
            ).get("interference", {}),
        }

        event = Event(
            source=source,
            # The alert's OWN identifier, not the emitter's: this is what PNTMAP deduplicates
            # on and what an auditor holding this event will search for in the source system.
            source_ids=[{"system": SYSTEM, "external_id": alert["alert_id"]}],
            event_id=event_id,
            event_type=EventType.GNSS_INTERFERENCE,
            severity=SEVERITY[severity_word],
            related_entities=[entity_id],
            geometry=alert.get("affected_area"),
            payload=payload,
            observed_at=alert["alert_time"],
            received_at=self.now(),
            # THREE FIELDS AND NOT ONE MORE. See the SC-OES section of the module docstring for
            # the field-by-field reading; the short form is that every other field of the block
            # is an assertion PNTMAP does not make, and the block's absent value is what says so.
            oes=OesMetadata(
                spec_version=SC_OES_VERSION,
                event_class=EventClass.OBSERVATION,
                type_id=OES_TYPE_ID,
            ),
        )
        return [entity, event]

    @staticmethod
    def _as_dict(raw: bytes | dict) -> dict:
        if isinstance(raw, (bytes, bytearray, str)):
            return json.loads(raw)
        if isinstance(raw, dict):
            return raw
        raise TypeError(f"PNTMAP adapter takes JSON bytes or a dict, got {type(raw).__name__}")

    @staticmethod
    def _position(emitter: dict) -> Position | None:
        """A Position only when the source actually geolocated the emitter.

        `lat is None or lon is None` -> None, and that is the whole null-never-zero rule at the
        one place it can be broken. Note that `0.0` is a legitimate coordinate and passes this
        test: the check is for ABSENCE, not for falsiness — `if not lat` would have silently
        discarded a real position on the Greenwich meridian or the equator.
        """
        lat, lon = emitter.get("lat"), emitter.get("lon")
        if lat is None or lon is None:
            return None
        method = str(emitter.get("geolocation_method", "")).lower()
        return Position(
            lat=float(lat),
            lon=float(lon),
            position_source=GEOLOCATION.get(method, PositionSource.ESTIMATED),
            accuracy_m=emitter.get("accuracy_m"),
        )
