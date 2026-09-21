"""C2SIM (SISO-STD-019-2020 v1.0 Core + SMX + LOX, schema C2SIMArtifacts v1.0.1) <-> CDM.
Adapter #18, bidirectional, `residual: structured`, the first whose objects sit under a nested
repeatable container and the reason the ledger grew the `[_]` wildcard.

WHAT A MESSAGE BECOMES
----------------------
One `Message` carries one `MessageBody`, and the four bodies this adapter reads become:

    C2SIMInitializationBody      one `Entity` per ForceSide (UNIT, no position — a side is the
                                 top of the organisation tree and has no location), per Unit
                                 (UNIT) and per Aircraft / Vehicle / SurfaceVessel /
                                 SubsurfaceVessel (PLATFORM); one `PlanObject` (ROUTE) per Route
                                 map graphic. Every other object class the schema admits there
                                 (Person, NonMilitaryOrganization, CommunicationNetwork, Overlay,
                                 the other physical entities and map graphics, Action,
                                 PlanPhaseReference) is carried in the residual, untyped, and
                                 named by `validate_source` — limitation `untyped-object-class`.
    ReportBody                   one `Event` per `ReportContent`: TRACK_UPDATE for a
                                 PositionReportContent, STATUS_CHANGE for an
                                 ObservationReportContent or a TaskStatus. The REPORT's identity
                                 (ReportID + content index) is the event's; the SUBJECT's
                                 identity is `related_entities[0]` — a second report about the
                                 same unit is a second event about the same entity, never a
                                 second entity.
    OrderBody                    one `Event` (PLAN_INJECT) per order, its tasks typed in the
                                 `c2sim-order/1` payload; plus one `PlanObject` per Route map
                                 graphic the order carries.

Acknowledgement, Plan, Request, ObjectInitialization, SystemAcknowledgement and SystemCommand
bodies are refused by name (limitation `unsupported-message-body`): the exercise client, not the
adapter, holds session state, and a translator that read a system command would be halfway to
acting on it.

WHY PLAN_INJECT, AND WHAT THE PAYLOAD CONTRACT IS
-------------------------------------------------
An order is a plan injected into an exercise: `EventType.PLAN_INJECT` is the member the CDM
declared for exactly that and no shipped adapter had emitted (ADR 0007, which declined to DEFINE
it and left its meaning to be discovered by use). This adapter is the first use, and it gives the
payload a named, versioned contract — `payload["c2sim"]` validates against
`c2sim_codec.OrderPayload`, `contract: "c2sim-order/1"` — rather than registering a model in
`PAYLOAD_MODELS`: a registration would bind EVERY producer's PLAN_INJECT payload to C2SIM's shape
and is a schema MINOR that re-stamps every golden of the fourteen adapters this arc may not
touch (decision D32 in the implementation record). Reports use the same pattern under
`c2sim-report/1`, and an initialisation object's typed block is `attributes["c2sim"]`
(`c2sim-object/1`): identity, classifications as source vocabulary, every organisational
relationship with its endpoints as C2SIM UUIDs, the physical state, the message header and the
scenario setting. All three are pydantic models a consumer validates with `model_validate`.

IDENTITY
--------
Every C2SIM object carries a UUID, and identity is `ids.derive("C2SIM", <uuid>, kind)` — kind
`object` for a force side, unit, platform or map graphic, `report` for a report content
(`<ReportID>#<index>`), `order` for an order. The C2SIM UUID is `source_ids[0].external_id`; the
message's `MessageID` is `source.original_id` (the record that described the object); the
header's `SendingTime` is `source.observed_at` (the record's own instant). A reference — Side,
Superior, Subordinate, CommandRelation, ForceSideRelation, PerformingEntity, SubjectEntity … —
is carried as the C2SIM UUID it names, and `related_entities` on an event holds the derived ids
of the entities the order or report concerns, so relationship endpoints and report associations
survive both directions.

AFFILIATION IS A VIEWPOINT
--------------------------
`Affiliation` is relative to "us", and C2SIM states hostility BETWEEN SIDES
(`ForceSideRelation/HostilityStatusCode`), so an affiliation needs the caller's side:
`C2simAdapter(own_side="<uuid>")`. With it, an entity on the own side is FRIENDLY and an entity on
side S reads the own side's stated relation to S — FR → FRIENDLY, HO → HOSTILE, NEUTRL → NEUTRAL,
every other code (assumed, suspect, pending, joker, faker…) → UNKNOWN with the code preserved.
Without it, every entity is UNKNOWN. Nothing is read off a name, a SIDC or a colour, and the
basis is written on every entity (`attributes.c2sim.affiliation_basis`).

TIME
----
`c2sim_codec`'s model: a DateTime is the scenario clock's own reading and resolves as stated; a
SimulationTime is scenario seconds since the scenario epoch and resolves only against a
caller-supplied `ExerciseClock` (the exercise client reads the epoch off the initialisation's
`ScenarioSetting/DateTime` and hands it over — the adapter is stateless); a RelativeTime never
resolves here. An event whose `observed_at` would need an unresolved instant is refused, with the
form and what would resolve it named. The header's `SendingTime` is message time and stays at
`source.observed_at`; `received_at` is the injected clock.

EGRESS
------
`from_cdm` emits one Message per call: an initialisation from Entities and PlanObjects, an order
from one order Event (plus its Route PlanObjects), a report from the Events of one report. The
header comes from the objects' own typed block when every object carries the same one, else from
the constructed `Envelope`; an essential element the record does not state — a UUID, a Unit's
EchelonCode, an EntityType, a task's PerformingEntity, a Route's second point — refuses the
export naming the element and the object; a task whose action code is outside the two pinned
forms is refused, never substituted. A record that came through this adapter is rebuilt from its
typed block with its residual's leftovers merged back at their own positions, so what went
unmapped comes back; a fresh record is built from the typed block alone. Elements outside the
pinned vocabulary (the `unknown` list of a residual) are NOT re-emitted, so an emitted document
validates against the pinned closure — `validate_source` names them on the way in.

PARSER LIMITS
-------------
`secure_xml.parse` with the three declared bounds (octets before the parser exists, depth and
elements on the element that crosses them), DTDs, entities, external references and XInclude
refused there; a parsed twin is held to `max_depth` by the base class; the object count is read
off the message before any object is built.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any

from synapse_cdm import ids, lossless, secure_xml, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import c2sim_codec as codec
from synapse_cdm.adapters.c2sim_codec import (
    ExerciseClock, Header, ObjectBlock, OrderPayload, ReportPayload, Scenario,
)
from synapse_cdm.enums import (
    Affiliation, EntityType, EventType, ObjectType, PositionSource, Severity, VerticalReference,
    VerticalUnit,
)
from synapse_cdm.geo import VerticalPosition
from synapse_cdm.manifest import (AdapterMetadata, Capabilities, ClaimStatus, Direction,
                                   Evidence, FormatRef, LicenseClass, LimitBasis, LimitKind,
                                   Limitation, Limits, Maturity, MaturityLevel, Residual,
                                   UnknownFields, WireBinding)
from synapse_cdm.models import (
    CDMBase, Entity, Event, Kinematics, PlanObject, Position, Residual as ResidualBlock, Route,
    SourceRef, TemporalValidity, Waypoint,
)

SYSTEM = "C2SIM"

# The four declared bounds, each an IMPLEMENTATION CAP (the standard states no maximum) and
# each declared in the metadata FROM its constant.
#
# 4 MiB: an aggregated C2SIMInitializationBody for a brigade-sized exercise — a few hundred
# units at ~2 KiB each — is under 1 MiB; the largest fixture here is under 12 KiB.
C2SIM_MAX_INPUT_BYTES = 4_194_304
# 192 deep — elements for XML, containers for a twin: a unit's latitude sits 14 elements below
# the root (Message/MessageBody/C2SIMInitializationBody/ObjectDefinitions/Entity/ActorEntity/
# CollectiveEntity/MilitaryOrganization/Unit/CurrentState/PhysicalState/Location/
# GeodeticCoordinate/Latitude), the deepest shipped XML nests 15 and the deepest shipped JSON —
# the initialisation's twin, whose lists add a container per repeatable element — nests 18; the
# repository's rule keeps a bound at least eight times the deepest shipped document, and 192 is
# 24 × 8 with room for a deeper fixture.
C2SIM_MAX_DEPTH = 192
# 200 000 elements across the document: ~60 elements per unit, so a few thousand units.
C2SIM_MAX_ELEMENTS = 200_000
# 5 000 canonical objects per message: object-bearing elements (AbstractObject, Entity,
# ReportContent, Task) are counted on the twin before any object is built.
C2SIM_MAX_OBJECTS = 5_000

XML_LIMITS = secure_xml.XmlLimits(max_bytes=C2SIM_MAX_INPUT_BYTES, max_depth=C2SIM_MAX_DEPTH,
                                  max_elements=C2SIM_MAX_ELEMENTS)


class ObjectCountExceeded(ValueError):
    """A message carrying more object-bearing elements than `C2SIM_MAX_OBJECTS`."""


class EgressRefused(ValueError):
    """An export this adapter declines: an essential element the record does not state, a task
    outside the pinned forms, or objects that cannot share one message."""


@dataclasses.dataclass(frozen=True)
class Envelope:
    """The header of a FRESH message on egress, supplied by the caller — the four required
    strings the schema needs and the record cannot know. `message_id` and `conversation_id` are
    UUID texts; they are never drawn here (a random id is a message nobody can replay)."""

    message_id: str
    conversation_id: str
    from_sending_system: str
    to_receiving_system: str
    communicative_act: str = "Inform"
    sending_time: str | None = None
    in_reply_to_message_id: str | None = None
    security_classification: str | None = None
    #: For a FRESH initialisation: which system simulates which actors —
    #: `((system name, (actor UUID, ...)), ...)` — the `SystemEntityList` elements
    #: `C2SIMInitializationBody` requires [1..*]. Exercise knowledge, never derived from a record.
    system_entities: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def __post_init__(self) -> None:
        for name in ("message_id", "conversation_id"):
            if not codec.UUID_PATTERN.fullmatch(getattr(self, name) or ""):
                raise ValueError(f"Envelope.{name} must be a UUID text, not {getattr(self, name)!r}")
        for name in ("from_sending_system", "to_receiving_system"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"Envelope.{name} must be a non-empty system name")
        if self.communicative_act not in codec.ENUMERATIONS["CommunicativeActTypeCode"]:
            raise ValueError(f"Envelope.communicative_act {self.communicative_act!r} is not in "
                             f"CommunicativeActTypeCodeType {codec.ENUMERATIONS['CommunicativeActTypeCode']}")
        if self.sending_time is not None:
            codec.parse_iso_date_time(self.sending_time, "Envelope.sending_time")
        for entry in self.system_entities:
            if (not isinstance(entry, tuple) or len(entry) != 2 or not isinstance(entry[0], str)
                    or not entry[0].strip() or not entry[1]
                    or not all(codec.UUID_PATTERN.fullmatch(str(u)) for u in entry[1])):
                raise ValueError("Envelope.system_entities is ((system name, (actor UUID, ...)), ...) "
                                 "with at least one UUID per system")

    def header(self) -> Header:
        return Header(message_id=self.message_id, conversation_id=self.conversation_id,
                      from_sending_system=self.from_sending_system,
                      to_receiving_system=self.to_receiving_system,
                      protocol=codec.PROTOCOL, protocol_version=codec.PROTOCOL_VERSION,
                      communicative_act=self.communicative_act, sending_time=self.sending_time,
                      in_reply_to_message_id=self.in_reply_to_message_id,
                      security_classification=self.security_classification,
                      protocol_matches_pin=True)


# --------------------------------------------------------------------------- the MAPPINGS ledger

# Source keys are relative to the Message's content — the twin's shape (c2sim_codec.twin_of).
_INIT = "MessageBody.C2SIMInitializationBody"
_INIT_ENTITY = _INIT + ".ObjectDefinitions[_].Entity[_]"
_INIT_ABSTRACT = _INIT + ".ObjectDefinitions[_].AbstractObject[_]"
_ORDER = "MessageBody.DomainMessageBody.OrderBody"
_ORDER_ENTITY = _ORDER + ".Entity[_]"
_REPORT = "MessageBody.DomainMessageBody.ReportBody"
_CONTENT = _REPORT + ".ReportContent[_]"
_UNIT = "ActorEntity.CollectiveEntity.MilitaryOrganization.Unit"
_ROUTE = "PhysicalEntity.MapGraphic.TacticalGraphic.Line.Route"


def _m(to: str, rule: str = "identity") -> lossless.Mapping:
    return lossless.Mapping(to, rule)


def _r(to: str) -> lossless.Mapping:
    return lossless.Mapping(to, kind="residual")


def _instant_leaves(source: str, dest: str) -> dict:
    """The leaves of one `TimeInstant` element in its three forms -> one typed `Instant`."""
    return {
        f"{source}.DateTime.IsoDateTime": _m(f"{dest}.iso_date_time"),
        f"{source}.DateTime.Name": _m(f"{dest}.name"),
        f"{source}.SimulationTime.DelayTimeAmount.IsoTimeDuration": _m(f"{dest}.elapsed"),
        f"{source}.SimulationTime.Name": _m(f"{dest}.name"),
        f"{source}.RelativeTime.DelayTimeAmount.IsoTimeDuration": _m(f"{dest}.elapsed"),
        f"{source}.RelativeTime.EventReference": _m(f"{dest}.event_reference"),
        f"{source}.RelativeTime.TimeReferenceCode": _m(f"{dest}.time_reference_code"),
        f"{source}.RelativeTime.Name": _m(f"{dest}.name"),
    }


def _location_leaves(source: str, dest: str) -> dict:
    return {
        f"{source}.GeodeticCoordinate.Latitude": _m(f"{dest}.latitude", "numeric_text"),
        f"{source}.GeodeticCoordinate.Longitude": _m(f"{dest}.longitude", "numeric_text"),
        f"{source}.GeodeticCoordinate.AltitudeMSL": _m(f"{dest}.altitude_msl_m", "numeric_text"),
        f"{source}.GeodeticCoordinate.AltitudeAGL": _m(f"{dest}.altitude_agl_m", "numeric_text"),
        f"{source}.RelativeLocation.EntityReference": _m(f"{dest}.entity_reference"),
        f"{source}.RelativeLocation.SpatialOffset": _r(f"{dest}.spatial_offset"),
    }


def _health_leaves(source: str, dest: str) -> dict:
    return {
        f"{source}.OperationalStatus.OperationalStatusCode": _m(f"{dest}.code"),
        f"{source}.Strength.StrengthPercentage": _m(f"{dest}.strength_percentage", "numeric_text"),
        f"{source}.Resources.Resource[*]": _r(f"{dest}.resources[*]"),
    }


def _state_leaves(source: str, dest: str) -> dict:
    physical = f"{source}.CurrentState.PhysicalState"
    return {
        f"{physical}.DateTime.IsoDateTime": _m(f"{dest}.date_time.iso_date_time"),
        f"{physical}.DateTime.Name": _m(f"{dest}.date_time.name"),
        **_location_leaves(f"{physical}.Location[*]", f"{dest}.locations[*]"),
        f"{physical}.Speed": _m(f"{dest}.speed_mps", "numeric_text"),
        f"{physical}.DirectionOfMovement.Heading.HeadingAngle": _m(f"{dest}.heading_deg", "numeric_text"),
        f"{physical}.DirectionOfMovement": _r(f"{dest}.direction_of_movement"),
        f"{physical}.Orientation": _r(f"{dest}.orientation"),
        **_health_leaves(f"{physical}.EntityHealthStatus[*]", f"{dest}.health[*]"),
    }


def _actor_leaves(source: str) -> dict:
    """A Unit or Platform element's leaves -> `entity:attributes.c2sim.*`."""
    a = "entity:attributes.c2sim"
    org = f"{a}.organisation"
    return {
        f"{source}.UUID": _m(f"{a}.uuid"),
        f"{source}.Name": _m(f"{a}.name"),
        f"{source}.Marking": _m(f"{a}.marking"),
        f"{source}.EntityType[*].APP6-SIDC.SIDCString": _m(f"{a}.classifications[*].sidc"),
        **{f"{source}.EntityType[*].DISEntityType.{name}": _m(f"{a}.classifications[*].dis.{name}")
           for name, _ in codec.CONTENT["DISEntityType"]},
        f"{source}.EntityType[*].NamedEntityType.EntityTypeString": _m(f"{a}.classifications[*].name"),
        f"{source}.EntityDescriptor.Side": _m(f"{org}.side"),
        f"{source}.EntityDescriptor.Superior": _m(f"{org}.superior"),
        f"{source}.EntityDescriptor.AffiliatedWith[*]": _m(f"{org}.affiliated_with[*]"),
        f"{source}.EntityDescriptor.AllegianceRelationship[*].ActorReference":
            _m(f"{org}.allegiance_relationships[*].actor"),
        f"{source}.EntityDescriptor.AllegianceRelationship[*].AllegianceRelationshipCode":
            _m(f"{org}.allegiance_relationships[*].code"),
        f"{source}.EntityDescriptor.CommunicationsNetwork[*]": _m(f"{org}.communications_networks[*]"),
        f"{source}.Subordinate[*]": _m(f"{org}.subordinates[*]"),
        f"{source}.CommandRelation[*].ActorReference": _m(f"{org}.command_relations[*].actor"),
        f"{source}.CommandRelation[*].CommandRelationCode": _m(f"{org}.command_relations[*].code"),
        f"{source}.CurrentTask[*]": _m(f"{org}.current_tasks[*]"),
        f"{source}.EchelonCode": _m(f"{org}.echelon"),
        **_state_leaves(source, f"{a}.state"),
    }


def _route_leaves(source: str) -> dict:
    """A Route map graphic's leaves -> the PlanObject: its points to the waypoints, its name to
    the label, its identity, classifications, marking, owner and message to the typed block at
    `route.metadata.c2sim`. The state's instant name, AGL heights, speed and health stay in the
    residual at their own positions."""
    physical = f"{source}.CurrentState.PhysicalState"
    b = "plan_object:route.metadata.c2sim"
    return {
        f"{source}.UUID": _m(f"{b}.uuid"),
        f"{source}.Name": _m("plan_object:label"),
        f"{source}.Marking": _m(f"{b}.marking"),
        f"{source}.Owner": _m(f"{b}.owner"),
        f"{source}.EntityType[*].APP6-SIDC.SIDCString": _m(f"{b}.classifications[*].sidc"),
        **{f"{source}.EntityType[*].DISEntityType.{name}": _m(f"{b}.classifications[*].dis.{name}")
           for name, _ in codec.CONTENT["DISEntityType"]},
        f"{source}.EntityType[*].NamedEntityType.EntityTypeString": _m(f"{b}.classifications[*].name"),
        f"{physical}.DateTime.IsoDateTime": _m("plan_object:validity.observed_at", "instant"),
        f"{physical}.Location[*].GeodeticCoordinate.Latitude":
            _m("plan_object:route.waypoints[*].position.lat", "numeric_text"),
        f"{physical}.Location[*].GeodeticCoordinate.Longitude":
            _m("plan_object:route.waypoints[*].position.lon", "numeric_text"),
        f"{physical}.Location[*].GeodeticCoordinate.AltitudeMSL":
            _m("plan_object:route.waypoints[*].position.vertical.value", "numeric_text"),
    }


def _entity_element_leaves(prefix: str) -> dict:
    out: dict = {}
    out.update(_actor_leaves(f"{prefix}.{_UNIT}"))
    for cls in codec.PLATFORM_CLASSES:
        out.update(_actor_leaves(f"{prefix}.ActorEntity.Platform.{cls}"))
    out.update(_route_leaves(f"{prefix}.{_ROUTE}"))
    return out


def _force_side_leaves(prefix: str) -> dict:
    a = "entity:attributes.c2sim"
    return {
        f"{prefix}.ForceSide.UUID": _m(f"{a}.uuid"),
        f"{prefix}.ForceSide.Name[*]": _m(f"{a}.names[*]"),
        f"{prefix}.ForceSide.ForceSideRelation[*].HostilityStatusCode":
            _m(f"{a}.organisation.force_side_relations[*].hostility"),
        f"{prefix}.ForceSide.ForceSideRelation[*].OtherSide":
            _m(f"{a}.organisation.force_side_relations[*].other_side"),
    }


def _report_leaves() -> dict:
    p = "event:payload.c2sim"
    position = f"{_CONTENT}.PositionReportContent"
    observation = f"{_CONTENT}.ObservationReportContent"
    status = f"{_CONTENT}.TaskStatus"
    obs = f"{observation}.Observation[*]"
    o = f"{p}.observations[*]"
    out = {
        f"{_REPORT}.FromSender": _m(f"{p}.from_sender"),
        f"{_REPORT}.ToReceiver": _m(f"{p}.to_receiver"),
        f"{_REPORT}.ReportID": _m(f"{p}.report_id"),
        f"{_REPORT}.ReportingEntity": _m(f"{p}.reporting_entity"),
    }
    for content in (position, observation, status):
        out.update(_instant_leaves(f"{content}.TimeOfObservation", f"{p}.time_of_observation"))
        out[f"{content}.Duration.IsoTimeDuration"] = _m(f"{p}.duration")
    out.update(_location_leaves(f"{position}.Location", f"{p}.location"))
    out.update(_health_leaves(f"{position}.EntityHealthStatus[*]", f"{p}.health[*]"))
    out[f"{position}.SubjectEntity"] = _m(f"{p}.subject_entity")
    for form in ("HealthObservation", "LocationObservation", "NameObservation"):
        out[f"{obs}.{form}.ActorReference"] = _m(f"{o}.actor_reference")
        out[f"{obs}.{form}.ConfidenceLevel"] = _m(f"{o}.confidence_level", "numeric_text")
        out[f"{obs}.{form}.UncertaintyInterval"] = _m(f"{o}.uncertainty_interval", "numeric_text")
    out.update(_health_leaves(f"{obs}.HealthObservation.EntityHealthStatus[*]", f"{o}.health[*]"))
    out.update(_location_leaves(f"{obs}.LocationObservation.Location", f"{o}.location"))
    out[f"{obs}.LocationObservation.Speed"] = _m(f"{o}.speed_mps", "numeric_text")
    out[f"{obs}.LocationObservation.DirectionOfMovement.Heading.HeadingAngle"] = _m(f"{o}.heading_deg", "numeric_text")
    out[f"{obs}.LocationObservation.DirectionOfMovement"] = _r(f"{o}.direction_of_movement")
    out[f"{obs}.NameObservation.Name"] = _m(f"{o}.name")
    out[f"{obs}.NameObservation.Marking"] = _m(f"{o}.marking")
    out[f"{obs}.NameObservation.HostilityStatusCode"] = _m(f"{o}.hostility_status")
    out[f"{obs}.NameObservation.Side"] = _m(f"{o}.side")
    out[obs] = _r(f"{o}.raw")
    out[f"{status}.CurrentTask"] = _m(f"{p}.current_task")
    out[f"{status}.TaskStatusCode"] = _m(f"{p}.task_status_code")
    return out


def _order_leaves() -> dict:
    p = "event:payload.c2sim"
    task = f"{_ORDER}.Task[*].ManeuverWarfareTask"
    t = f"{p}.tasks[*]"
    out = {
        f"{_ORDER}.FromSender": _m(f"{p}.from_sender"),
        f"{_ORDER}.ToReceiver": _m(f"{p}.to_receiver"),
        f"{_ORDER}.IssuedTime.IsoDateTime": _m(f"{p}.issued_time.iso_date_time"),
        f"{_ORDER}.IssuedTime.Name": _m(f"{p}.issued_time.name"),
        f"{_ORDER}.OrderID": _m(f"{p}.order_id"),
        f"{_ORDER}.RequestingEntity": _m(f"{p}.requesting_entity"),
        f"{_ORDER}.TaskReference[*]": _m(f"{p}.task_references[*]"),
        f"{task}.UUID": _m(f"{t}.uuid"),
        f"{task}.Name": _m(f"{t}.name"),
        f"{task}.TaskActionCode": _m(f"{t}.action_code"),
        f"{task}.PerformingEntity": _m(f"{t}.performing_entity"),
        f"{task}.AffectedEntity[*]": _m(f"{t}.affected_entities[*]"),
        f"{task}.DesiredEffectCode[*]": _m(f"{t}.desired_effects[*]"),
        f"{task}.Duration.IsoTimeDuration": _m(f"{t}.duration"),
        **_instant_leaves(f"{task}.StartTime", f"{t}.start_time"),
        **_instant_leaves(f"{task}.EndTime", f"{t}.end_time"),
        **_location_leaves(f"{task}.Location[*]", f"{t}.locations[*]"),
        f"{task}.MapGraphicID[*]": _m(f"{t}.map_graphic_ids[*]"),
        f"{task}.ActionTemporalRelationship[*].ActionTemporalAssociationCode":
            _m(f"{t}.temporal_relationships[*].code"),
        f"{task}.ActionTemporalRelationship[*].Duration.IsoTimeDuration":
            _m(f"{t}.temporal_relationships[*].duration"),
        f"{task}.ActionTemporalRelationship[*].TemporalAssociationWithAction":
            _m(f"{t}.temporal_relationships[*].action"),
        f"{task}.TaskFunctionalRelation[*].FunctionalAssociationWithTask":
            _m(f"{t}.functional_relations[*].task"),
        f"{task}.TaskFunctionalRelation[*].TaskFunctionalAssociationCode":
            _m(f"{t}.functional_relations[*].code"),
        f"{task}.RuleOfEngagement[*]": _r(f"{t}.rules_of_engagement[*]"),
    }
    return out


def _build_mappings() -> dict:
    """The path-bound preservation declarations, in the order the ledger tries them: every
    specific leaf first, then the residual subtrees — each object's own element under its own
    residual key, a report's content and an order's task likewise — and last the empty key: the
    message itself, whose every unconsumed leaf (the header, the scenario setting, system entity
    lists, the untyped object classes) sits on every object under `residual.data` at the path the
    twin gives it (`C2SIMHeader…`, `MessageBody…`)."""
    out: dict = {}
    out.update(_force_side_leaves(_INIT_ABSTRACT))
    out.update(_entity_element_leaves(_INIT_ENTITY))
    out.update(_entity_element_leaves(_ORDER_ENTITY))
    out.update(_report_leaves())
    out.update(_order_leaves())
    # The residual prefixes name the TYPED classes only: an untyped class (a Person, an Overlay)
    # matches none of them and falls to the empty key — the message residual, where it sits
    # whole at its own index.
    out[f"{_INIT_ABSTRACT}.ForceSide"] = _r("*:residual.data.AbstractObject.ForceSide")
    for prefix in (_INIT_ENTITY, _ORDER_ENTITY):
        out[f"{prefix}.{_UNIT}"] = _r(f"*:residual.data.Entity.{_UNIT}")
        for cls in codec.PLATFORM_CLASSES:
            out[f"{prefix}.ActorEntity.Platform.{cls}"] = _r(f"*:residual.data.Entity.ActorEntity.Platform.{cls}")
        out[f"{prefix}.{_ROUTE}"] = _r(f"*:residual.data.Entity.{_ROUTE}")
    out[_CONTENT] = _r("event:residual.data.ReportContent")
    out[f"{_ORDER}.Task[*]"] = _r("event:residual.data.Task[*]")
    out[""] = _r("*:residual.data")
    return out


# ----------------------------------------------------------------------------------- the adapter


class C2simAdapter(Adapter):
    name = "c2sim"
    version = "1.0.0"
    direction = "bidirectional"
    system = SYSTEM

    #: Adapter API v2's declaration (ARCHITECTURE.md §3). Licence class from
    #: `fixtures/c2sim/spec/c2sim_pin.json`: the schema and ontologies are MIT (OpenC2SIM
    #: Project, 2022); the SISO standard document is copyright SISO, held outside the repository.
    metadata = AdapterMetadata(
        id="c2sim",
        name="C2SIM",
        adapter_version="1.0.0",
        format=FormatRef(name="C2SIM",
                         version="SISO-STD-019-2020 v1.0 (Core + SMX) with SISO-STD-020-2020 "
                                 "(LOX); XML schema C2SIMArtifacts v1.0.1"),
        binding=WireBinding.STANDARD,
        direction=Direction.BIDIRECTIONAL,
        license_class=LicenseClass.OPEN,
        maturity=Maturity(
            level=MaturityLevel.L4,
            basis="L4 ROUND-TRIP VERIFIED, from evidence that runs today. The harness's "
                  "`translate`, `schema` and `provenance` checks are PASS on every fixture of "
                  "this adapter (L1 to L3). Its `lossless` column rests on the PATH-BOUND LEDGER: "
                  "this adapter declares `MAPPINGS` for every leaf it types — identity, names, "
                  "classifications, every organisational relationship, the physical state, the "
                  "header, report content and order tasks, with the `[_]` wildcard holding a "
                  "nested container's leaves to the right list — and residual subtrees for "
                  "everything else at its own position, and the ledger reports no LOST leaf on "
                  "any fixture. Its `roundtrip` column is PASS on every fixture under the "
                  "`values` tolerance (`ROUNDTRIP_TOLERANCE`) an XML emitter needs: `from_cdm` "
                  "rebuilds each element from the typed block and the residual and no source "
                  "value is absent after re-ingest, so `synapse conformance run --adapter c2sim` "
                  "computes E = PASS and D on the ledger basis. The adapter's own statement of "
                  "the round-trip claim is tests/test_cdm_c2sim_adapter.py::"
                  "test_semantic_round_trip_of_every_fixture; normative validation of every "
                  "emitted document against the pinned XSD closure is "
                  "test_every_emitted_document_validates_against_the_pinned_schema, which "
                  "records BLOCKED_EXTERNAL_EVIDENCE rather than passing when the resource or the "
                  "`validate` extra is absent. L5 is NOT declared: the rung above L4 rests on `M` "
                  "(streaming) being inapplicable, and a rung passed vacuously is not a rung "
                  "declared (ARCHITECTURE.md §3.6, rule 4). No independent endpoint has been "
                  "exercised: `examples/c2sim/exercise_client.py` is the procedure, and "
                  "`independent_endpoint` reads ABSENT until an exercise report exists.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest", "egress"],
            message_types=[
                "C2SIMInitializationBody — force sides, units and platforms (with source "
                "identifiers, entity classifications as source vocabulary, locations and "
                "organisational relationships) as Entities, Route map graphics as ROUTE "
                "PlanObjects; both directions",
                "ReportBody / PositionReportContent — one TRACK_UPDATE Event per content, "
                "reporting entity, subject, position, time of observation, health; both "
                "directions",
                "ReportBody / ObservationReportContent and TaskStatus — one STATUS_CHANGE Event "
                "per content, source status vocabulary verbatim; both directions",
                "OrderBody / ManeuverWarfareTask — one PLAN_INJECT Event per order with the "
                "`c2sim-order/1` payload, task action codes MoveToLocation and HoldInPlace only; "
                "both directions",
            ],
            limits=Limits(
                max_input_bytes=C2SIM_MAX_INPUT_BYTES,
                max_depth=C2SIM_MAX_DEPTH,
                max_objects=C2SIM_MAX_OBJECTS,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_decompressed_bytes":
                        "this adapter accepts no archived or compressed payload, so there is "
                        "no expansion to bound",
                    "max_parse_seconds":
                        "no wall-clock bound is enforced by this adapter; the conformance "
                        "suite's parser worker kills a decode that overruns its deadline, and "
                        "the byte, depth, element and object bounds make every walk in this "
                        "module linear in a bounded input",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "SISO-STD-019-2020 states no maximum document size. 4 MiB "
                            "(`C2SIM_MAX_INPUT_BYTES`, `adapters/c2sim.py`) is chosen on "
                            "2026-09-21: an aggregated initialisation for a brigade-sized "
                            "exercise is under 1 MiB and the largest fixture in "
                            "`fixtures/c2sim/` is under 12 KiB. This is an IMPLEMENTATION CAP "
                            "and is NOT the format's normative maximum."),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the payload is measured and refused "
                            "before any decoder in this module runs; `secure_xml.parse` reads "
                            "the same bound off the octets again before it creates a parser"),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "SISO-STD-019-2020 states no maximum nesting; a unit's latitude "
                            "sits 14 elements below the root, the deepest XML shipped under "
                            "`fixtures/c2sim/` nests 15 and the deepest JSON (the "
                            "initialisation's parsed twin) 18 containers. 192 (`C2SIM_MAX_DEPTH`, "
                            "`adapters/c2sim.py`) is chosen on 2026-09-21 by the repository's "
                            "rule of at least eight times the deepest shipped document, with "
                            "room. This is an IMPLEMENTATION CAP and is NOT the format's "
                            "normative maximum."),
                        enforced_at=(
                            "`secure_xml.parse` counts the depth in expat's StartElementHandler "
                            "and refuses on the element that crosses the bound, before the "
                            "rest of the document is read; a parsed twin (a dict) is held to "
                            "the same bound by `Adapter.__init_subclass__`'s "
                            "`enforce_depth_bound` before `to_cdm` runs"),
                        test="tests/test_cdm_c2sim_adapter.py::test_the_depth_bound_admits_a_document_at_it_and_refuses_one_past",
                    ),
                    "max_objects": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "SISO-STD-019-2020 states no maximum object count. 5 000 "
                            "(`C2SIM_MAX_OBJECTS`, `adapters/c2sim.py`) object-bearing elements "
                            "per message — AbstractObject, Entity, ReportContent, Task — chosen "
                            "on 2026-09-21 as a brigade-sized initialisation with room to spare. "
                            "A second cap the manifest schema has no field for is declared "
                            "beside it: `C2SIM_MAX_ELEMENTS` (200 000), the elements across the "
                            "document, refused by `secure_xml.parse` on the element that "
                            "crosses it. This is an IMPLEMENTATION CAP and is NOT the format's "
                            "normative maximum."),
                        enforced_at=(
                            "`C2simAdapter.to_cdm` counts the object-bearing elements on the "
                            "twin and raises `ObjectCountExceeded` (a `ValueError`) before any "
                            "canonical object is built"),
                        test="tests/test_cdm_c2sim_adapter.py::test_the_object_bound_admits_a_message_at_it_and_refuses_one_past",
                    ),
                },
            ),
            unknown_fields=UnknownFields.PRESERVED,
            unknown_fields_basis=(
                "an element or attribute the pinned schema does not declare at its position — "
                "any element outside the C2SIM namespace, any C2SIM-namespace child its parent's "
                "content model does not name — is kept in the structured residual at its own "
                "path and position and listed under `residual.data.unknown` with its namespace, "
                "path and position; `validate_source` names each one; none is re-emitted"),
        ),
        limitations=[
            Limitation(
                id="untyped-object-class",
                summary="an initialisation's Person, NonMilitaryOrganization, "
                        "CommunicationNetwork, Overlay, CulturalFeature, EnvironmentalObject, "
                        "GeographicFeature, non-Route map graphic, Action and PlanPhaseReference "
                        "produce no canonical object: each is carried whole in every object's "
                        "residual at its own path under `residual.data.MessageBody` and named by "
                        "`validate_source`. "
                        "The typed classes are ForceSide, Unit, the four Platform kinds and the "
                        "Route map graphic",
                unsupported_paths=[],
            ),
            Limitation(
                id="unsupported-message-body",
                summary="AcknowledgementBody, PlanBody, RequestBody, ObjectInitializationBody, "
                        "SystemAcknowledgementBody and SystemCommandBody are refused by name: "
                        "session and protocol state live in the exercise client "
                        "(`examples/c2sim/exercise_client.py`), never in the adapter",
                unsupported_paths=[],
            ),
            Limitation(
                id="pinned-task-forms",
                summary="a ManeuverWarfareTask whose TaskActionCode is not MoveToLocation or "
                        "HoldInPlace (decision D1) is refused with a diagnostic naming the two "
                        "supported forms, on ingest and on egress; no other task is ever "
                        "substituted",
                unsupported_paths=[],
            ),
            Limitation(
                id="untyped-observations",
                summary="ActivityObservation, ResourceObservation and SubjectTypeObservation "
                        "are carried whole under `payload.c2sim.observations[].raw` (typed: "
                        "false); Health, Location and Name observations are typed",
                unsupported_paths=[],
            ),
            Limitation(
                id="simulation-time-needs-a-clock",
                summary="a SimulationTime instant is scenario seconds since the scenario epoch "
                        "and resolves only against `C2simAdapter(exercise=ExerciseClock(epoch, "
                        "basis))`; a RelativeTime never resolves here. An Event whose "
                        "observed_at would need an unresolved instant is refused, naming the "
                        "form; a task's start and end times are carried typed either way",
                unsupported_paths=[],
            ),
            Limitation(
                id="affiliation-needs-own-side",
                summary="affiliation is read from the own side's stated ForceSideRelation only "
                        "when `C2simAdapter(own_side=<uuid>)` names it (FR, HO, NEUTRL; every "
                        "other hostility code reads UNKNOWN with the code kept); without it "
                        "every entity is UNKNOWN. Nothing is inferred from a name or a SIDC",
                unsupported_paths=[],
            ),
            Limitation(
                id="extension-not-reemitted",
                summary="elements and attributes outside the pinned vocabulary are preserved "
                        "and listed on ingest but are not written back on egress, so an "
                        "emitted document stays inside the schema the validator judges; a "
                        "re-ingested round trip therefore lacks them, and the harness fixtures "
                        "carry none",
                unsupported_paths=[],
            ),
            "the APP-6 SIDC string a source states is carried verbatim as a classification and "
            "never becomes `Entity.symbol`, which is a 20-digit MIL-STD-2525D code; positions "
            "carry `position_source: ESTIMATED`, the understating reading legion applies to a "
            "simulation's fixes, and their MSL or AGL height is kept in `vertical` unconverted "
            "with `alt_m` None",
            "egress of an Entity with no `attributes.c2sim` block is refused: the schema needs "
            "a UUID, at least one EntityType and, for a Unit, an EchelonCode, and none of these "
            "is invented from the CDM's own fields",
            "the evidence RECORD for this adapter is not IN the distribution: `evidence/` is "
            "untracked and unpackaged. `evidence.available` is false because no published "
            "Release carries this adapter's records yet; it becomes true at the first release "
            "that attaches them",
            "of §3.5's five resource limits this adapter enforces THREE — `max_input_bytes` "
            "by the base class before decode and again by `secure_xml` before a parser exists, "
            "`max_depth` and `max_objects` in this module before any object is built — plus an "
            "element count the manifest schema has no field for. The other two are absent with "
            "their reasons in `capabilities.limits.absent_because`",
            "XML is parsed with the standard library's expat through `secure_xml` and NOT with "
            "`defusedxml`, which is not a dependency of this package: a DOCTYPE is refused at "
            "its declaration before any entity is read, every entity reference other than the "
            "five predefined ones is refused, no external resource is fetched and XInclude is "
            "refused where it starts (`tests/test_cdm_secure_xml.py`). The tree is "
            "`xml.etree.ElementTree`'s own, built through its TreeBuilder",
        ],
        limitations_empty_reason=None,
        residual=Residual.STRUCTURED,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=False),
    )

    #: XML: attribute order, whitespace and the namespace prefix are the serialiser's, so octet
    #: equality is not a promise this format lets an emitter make; the harness re-ingests what
    #: `from_cdm` emitted and asks the never-drop question of the parsed twin.
    ROUNDTRIP_TOLERANCE = "values"

    #: Nothing a source states changes value in translation: every leaf is carried verbatim in
    #: its typed block or its residual, numbers as the same numbers, instants as the text stated.
    TRANSFORMS: dict[str, str] = {}

    MAPPINGS = _build_mappings()

    def __init__(self, clock: times.Clock | None = None, *, synthetic: bool = True,
                 own_side: str | None = None, exercise: ExerciseClock | None = None,
                 envelope: Envelope | None = None) -> None:
        """`own_side` is the C2SIM UUID of the force side affiliation is read from. `exercise`
        is the scenario epoch a SimulationTime resolves against. `envelope` is the header a
        FRESH egress message carries. Each is part of the determinism tuple (ARCHITECTURE.md
        §6.1); none is inferred."""
        super().__init__(clock, synthetic=synthetic)
        if own_side is not None and not codec.UUID_PATTERN.fullmatch(str(own_side)):
            raise ValueError(f"own_side must be a C2SIM UUID text, not {own_side!r}")
        if exercise is not None and not isinstance(exercise, ExerciseClock):
            raise TypeError("exercise must be an ExerciseClock(epoch, basis, rate)")
        if envelope is not None and not isinstance(envelope, Envelope):
            raise TypeError("envelope must be an Envelope(...)")
        self._own_side = own_side
        self._exercise = exercise
        self._envelope = envelope

    # ------------------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        twin = self._as_twin(raw)
        if not isinstance(twin, dict) or not twin:
            raise ValueError("a C2SIM twin is a JSON object holding the Message's content; this one is "
                             f"{'empty' if isinstance(twin, dict) else type(twin).__name__}")
        header = codec.read_header(twin.get("C2SIMHeader"))
        body = twin.get("MessageBody")
        if not isinstance(body, dict) or len([k for k in body if not k.startswith("@")]) != 1:
            raise ValueError("C2SIM Message.MessageBody must hold exactly one body element "
                             f"(MessageBodyType's choice); found "
                             f"{sorted(body) if isinstance(body, dict) else body!r}")
        kind = next(k for k in body if not k.startswith("@"))
        self._enforce_object_bound(body, kind)
        unknown = [u.as_dict() for u in codec.unknowns_in(twin)]
        if kind == "C2SIMInitializationBody":
            return self._initialisation(twin, header, body[kind], unknown)
        if kind == "DomainMessageBody":
            domain = body[kind]
            if not isinstance(domain, dict) or len([k for k in domain if not k.startswith("@")]) != 1:
                raise ValueError("C2SIM DomainMessageBody must hold exactly one body element")
            inner = next(k for k in domain if not k.startswith("@"))
            if inner == "OrderBody":
                return self._order(twin, header, domain[inner], unknown)
            if inner == "ReportBody":
                return self._report(twin, header, domain[inner], unknown)
            raise ValueError(f"C2SIM DomainMessageBody/{inner} is outside this adapter's "
                             "declared subset (limitation `unsupported-message-body`): "
                             "OrderBody and ReportBody are read; Acknowledgement, Plan and "
                             "Request bodies are not")
        raise ValueError(f"C2SIM MessageBody/{kind} is outside this adapter's declared subset "
                         "(limitation `unsupported-message-body`): C2SIMInitializationBody and "
                         "DomainMessageBody are read; ObjectInitializationBody, "
                         "SystemAcknowledgementBody and SystemCommandBody are the exercise "
                         "client's business")

    def _as_twin(self, raw: bytes | dict) -> dict:
        """XML octets -> the twin through the guarded parser; JSON text or a dict -> the twin
        as given (a parsed twin was held to `max_depth` by the base class already)."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, (bytes, bytearray, memoryview, str)):
            octets = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
            if octets.lstrip(b"\xef\xbb\xbf").lstrip()[:1] == b"{":
                document = json.loads(octets)
                if not isinstance(document, dict):
                    raise ValueError("a C2SIM parsed twin is a JSON object holding the Message's content")
                return document
            return codec.twin_of(secure_xml.parse(octets, XML_LIMITS).root)
        raise TypeError(f"C2SIM adapter takes XML bytes, a JSON twin or a parsed dict, got "
                        f"{type(raw).__name__}")

    @staticmethod
    def _enforce_object_bound(body: dict, kind: str) -> None:
        count = 0
        if kind == "C2SIMInitializationBody" and isinstance(body[kind], dict):
            for definitions in codec.as_list(body[kind], "ObjectDefinitions"):
                if isinstance(definitions, dict):
                    count += len(codec.as_list(definitions, "AbstractObject"))
                    count += len(codec.as_list(definitions, "Entity"))
        elif kind == "DomainMessageBody" and isinstance(body[kind], dict):
            for inner in body[kind].values():
                if isinstance(inner, dict):
                    count += len(codec.as_list(inner, "Entity")) + len(codec.as_list(inner, "Task"))
                    count += len(codec.as_list(inner, "ReportContent"))
        if count > C2SIM_MAX_OBJECTS:
            raise ObjectCountExceeded(
                f"C2SIM message carries {count} object-bearing elements and this adapter "
                f"declares max_objects = {C2SIM_MAX_OBJECTS}. Refused whole, before any object "
                "is built: nothing is truncated")

    # --- initialisation

    def _initialisation(self, twin: dict, header: Header, body: Any, unknown: list) -> list[CDMBase]:
        if not isinstance(body, dict):
            raise ValueError("C2SIM C2SIMInitializationBody is empty")
        if "ScenarioSetting" not in body:
            raise ValueError("C2SIM C2SIMInitializationBody has no ScenarioSetting "
                             "(C2SIMInitializationBodyType declares it [1..1])")
        setting = body["ScenarioSetting"]
        scenario = Scenario(date_time=codec.read_date_time(setting.get("DateTime") if isinstance(setting, dict) else None,
                                                           "C2SIMInitializationBody.ScenarioSetting.DateTime"),
                            version=codec._text(setting, "Version", "C2SIMInitializationBody.ScenarioSetting"))
        definitions = codec.as_list(body, "ObjectDefinitions")
        if not definitions:
            raise ValueError("C2SIM C2SIMInitializationBody has no ObjectDefinitions (declared [1..*])")
        # Pass one: every UUID declared in the message, so a reference can be resolved and a
        # duplicate refused before any object is built.
        declared: dict[str, str] = {}
        sides: dict[str, dict] = {}
        for d, definition in enumerate(definitions):
            if not isinstance(definition, dict):
                continue
            for a, abstract in enumerate(codec.as_list(definition, "AbstractObject")):
                self._declare(declared, abstract, f"ObjectDefinitions[{d}].AbstractObject[{a}]")
                if isinstance(abstract, dict) and isinstance(abstract.get("ForceSide"), dict):
                    sides[abstract["ForceSide"].get("UUID", "")] = abstract["ForceSide"]
            for e, entity in enumerate(codec.as_list(definition, "Entity")):
                self._declare(declared, entity, f"ObjectDefinitions[{d}].Entity[{e}]")
        consumed_message: set[tuple] = set()
        objects: list[CDMBase] = []
        pending: list[tuple[str, tuple, Any, str]] = []
        for d, definition in enumerate(definitions):
            if not isinstance(definition, dict):
                continue
            for a, abstract in enumerate(codec.as_list(definition, "AbstractObject")):
                path = ("MessageBody", "C2SIMInitializationBody", "ObjectDefinitions", d, "AbstractObject", a)
                if isinstance(abstract, dict) and "ForceSide" in abstract:
                    consumed_message.add(path)
                    pending.append(("AbstractObject", path, abstract, f"ObjectDefinitions[{d}].AbstractObject[{a}]"))
            for e, entity in enumerate(codec.as_list(definition, "Entity")):
                path = ("MessageBody", "C2SIMInitializationBody", "ObjectDefinitions", d, "Entity", e)
                if self._typed_class_of(entity) is not None:
                    consumed_message.add(path)
                    pending.append(("Entity", path, entity, f"ObjectDefinitions[{d}].Entity[{e}]"))
        message_residual = codec.prune(twin, consumed_message, ())
        for index, (key, path, node, where) in enumerate(pending):
            objects.append(self._object_from(key, node, where, index, header, scenario, declared,
                                             sides, message_residual, unknown, twin))
        return objects

    @staticmethod
    def _declare(declared: dict[str, str], node: Any, where: str) -> None:
        """Record the UUID of an object element (whatever its class) and refuse a duplicate."""
        found = _find_uuid(node)
        if found is None:
            return
        uuid, cls = found
        if not codec.UUID_PATTERN.fullmatch(uuid):
            raise ValueError(f"C2SIM {where} ({cls}) UUID {uuid!r} is not the schema's UUID form")
        if uuid in declared:
            raise ValueError(f"C2SIM {where} ({cls}) declares UUID {uuid}, already declared by "
                             f"{declared[uuid]}: two objects with one identity are refused, "
                             "never merged and never renumbered")
        declared[uuid] = f"{where} ({cls})"

    @staticmethod
    def _typed_class_of(entity: Any) -> tuple[str, dict, tuple] | None:
        """(class name, the class element, its path under Entity) for a typed class, else None."""
        if not isinstance(entity, dict):
            return None
        actor = entity.get("ActorEntity")
        if isinstance(actor, dict):
            collective = actor.get("CollectiveEntity")
            if isinstance(collective, dict):
                military = collective.get("MilitaryOrganization")
                if isinstance(military, dict) and isinstance(military.get("Unit"), dict):
                    return "Unit", military["Unit"], ("ActorEntity", "CollectiveEntity", "MilitaryOrganization", "Unit")
            platform = actor.get("Platform")
            if isinstance(platform, dict):
                for cls in codec.PLATFORM_CLASSES:
                    if isinstance(platform.get(cls), dict):
                        return cls, platform[cls], ("ActorEntity", "Platform", cls)
        physical = entity.get("PhysicalEntity")
        if isinstance(physical, dict):
            graphic = physical.get("MapGraphic")
            if isinstance(graphic, dict) and isinstance(graphic.get("TacticalGraphic"), dict):
                line = graphic["TacticalGraphic"].get("Line")
                if isinstance(line, dict) and isinstance(line.get("Route"), dict):
                    return "Route", line["Route"], ("PhysicalEntity", "MapGraphic", "TacticalGraphic", "Line", "Route")
        return None

    def _object_from(self, key: str, node: dict, where: str, index: int, header: Header,
                     scenario: Scenario | None, declared: dict[str, str], sides: dict[str, dict],
                     message_residual: Any, unknown: list, twin: dict) -> CDMBase:
        consumed: set[tuple] = set()
        if key == "AbstractObject":
            block, affiliation = self._force_side(node["ForceSide"], f"{where}.ForceSide", header, scenario,
                                                  declared, sides, consumed, ("ForceSide",))
            residual = self._residual(message_residual, key, codec.prune(node, consumed, ()), unknown, twin)
            return self._entity(block, affiliation, None, None, index, header, residual)
        cls, element, rel = self._typed_class_of(node)
        if cls == "Route":
            plan = self._route(element, f"{where}.{'.'.join(rel)}", index, header, scenario, consumed, rel)
            plan.residual = self._residual(message_residual, key, codec.prune(node, consumed, ()), unknown, twin)
            return plan
        block, affiliation, position, kinematics = self._actor(
            cls, element, f"{where}.{'.'.join(rel)}", header, scenario, declared, sides, consumed, rel)
        residual = self._residual(message_residual, key, codec.prune(node, consumed, ()), unknown, twin)
        return self._entity(block, affiliation, position, kinematics, index, header, residual)

    def _residual(self, message_residual: Any, key: str, own: Any, unknown: list, twin: dict | None = None):
        """`residual.data`: the message's content minus what became an object (`C2SIMHeader`,
        `MessageBody…`, any member the root itself carried), the object's own element under its
        element name, and the `unknown` list."""
        data: dict = {}
        if isinstance(message_residual, dict):
            data.update(message_residual)
        if own not in (None, codec._DROPPED, {}):
            data[key] = own
        if unknown:
            data["unknown"] = list(unknown)
        return ResidualBlock(namespace=self.metadata.format.name, data=data)

    def _force_side(self, side: Any, where: str, header: Header, scenario: Scenario | None,
                    declared: dict, sides: dict, consumed: set, rel: tuple) -> tuple[ObjectBlock, Affiliation]:
        if not isinstance(side, dict):
            raise ValueError(f"C2SIM {where} is empty")
        take = _Taker(side, consumed, rel)
        uuid = codec._uuid(take("UUID"), f"{where}.UUID")
        names = [codec._scalar(v, f"{where}.Name[{i}]") for i, v in enumerate(take.list("Name"))]
        relations = []
        for i, item in enumerate(take.list("ForceSideRelation")):
            code = codec._text(item, "HostilityStatusCode", f"{where}.ForceSideRelation[{i}]")
            other = codec._uuid(codec._text(item, "OtherSide", f"{where}.ForceSideRelation[{i}]"),
                                f"{where}.ForceSideRelation[{i}].OtherSide")
            self._resolve(other, declared, f"{where}.ForceSideRelation[{i}].OtherSide")
            relations.append(codec.ForceSideRelation(other_side=other, hostility=code,
                                                     in_pinned_enumeration=code in codec.ENUMERATIONS["HostilityStatusCode"]))
        affiliation, basis = self._affiliation_of(uuid, sides)
        block = ObjectBlock(object_class="ForceSide", uuid=uuid, names=names,
                            organisation=codec.Organisation(force_side_relations=relations),
                            affiliation_basis=basis, message=header, scenario=scenario,
                            exercise_clock=self._exercise.as_dict() if self._exercise else None)
        return block, affiliation

    def _actor(self, cls: str, actor: dict, where: str, header: Header, scenario: Scenario | None,
               declared: dict, sides: dict, consumed: set, rel: tuple):
        take = _Taker(actor, consumed, rel)
        uuid = codec._uuid(take("UUID"), f"{where}.UUID")
        name = take.optional("Name")
        classifications = [codec.read_classification(item, f"{where}.EntityType[{i}]")
                           for i, item in enumerate(take.list("EntityType"))]
        if not classifications:
            raise ValueError(f"C2SIM {where} has no EntityType (EntityGroup declares it [1..*])")
        marking = take.optional("Marking")
        organisation = codec.read_organisation(actor, where)
        if cls == "Unit" and organisation.echelon is None:
            raise ValueError(f"C2SIM {where} has no EchelonCode (UnitType declares it [1..1])")
        # The organisation reader consumed nothing itself; mark its leaves here, and resolve
        # every reference it holds against the message's declarations.
        take.subtree("EntityDescriptor")
        for child in ("Subordinate", "CommandRelation", "CurrentTask", "EchelonCode"):
            take.subtree(child)
        for reference, what in self._references_of(organisation):
            self._resolve(reference, declared, f"{where}.{what}")
        state = None
        position = None
        kinematics = None
        if "CurrentState" in actor:
            state = codec.read_physical_state(actor["CurrentState"], f"{where}.CurrentState", self._exercise)
            take.subtree("CurrentState")
            position, kinematics = self._position_of(state, f"{where}.CurrentState.PhysicalState")
        affiliation, basis = self._affiliation_of(organisation.side, sides)
        block = ObjectBlock(object_class=cls, uuid=uuid, name=name, classifications=classifications,
                            marking=marking, organisation=organisation, state=state,
                            affiliation_basis=basis, message=header, scenario=scenario,
                            exercise_clock=self._exercise.as_dict() if self._exercise else None)
        return block, affiliation, position, kinematics

    @staticmethod
    def _references_of(organisation: codec.Organisation) -> list[tuple[str, str]]:
        out = []
        if organisation.side:
            out.append((organisation.side, "EntityDescriptor.Side"))
        if organisation.superior:
            out.append((organisation.superior, "EntityDescriptor.Superior"))
        out += [(s, f"Subordinate[{i}]") for i, s in enumerate(organisation.subordinates)]
        out += [(a, f"EntityDescriptor.AffiliatedWith[{i}]") for i, a in enumerate(organisation.affiliated_with)]
        out += [(r.actor, f"EntityDescriptor.AllegianceRelationship[{i}].ActorReference")
                for i, r in enumerate(organisation.allegiance_relationships)]
        out += [(r.actor, f"CommandRelation[{i}].ActorReference")
                for i, r in enumerate(organisation.command_relations)]
        return out

    @staticmethod
    def _resolve(reference: str, declared: dict[str, str], where: str) -> None:
        if reference not in declared:
            raise ValueError(f"C2SIM {where} references UUID {reference}, which no object in this "
                             "message declares (an initialisation's organisational references "
                             "resolve within the aggregated message, SISO-STD-019-2020 §7.2); "
                             "refused rather than left dangling")

    def _affiliation_of(self, side: str | None, sides: dict[str, dict]) -> tuple[Affiliation, str]:
        if self._own_side is None:
            return Affiliation.UNKNOWN, ("UNKNOWN: no own side was named (C2simAdapter(own_side=...)); "
                                         "affiliation is a viewpoint and nothing is read off a name or a SIDC")
        if side is None:
            return Affiliation.UNKNOWN, f"UNKNOWN: the object states no Side to relate to own side {self._own_side}"
        if side == self._own_side:
            return Affiliation.FRIENDLY, f"FRIENDLY: the object's side is the own side {self._own_side}"
        own = sides.get(self._own_side)
        if own is None:
            return Affiliation.UNKNOWN, (f"UNKNOWN: own side {self._own_side} is not a ForceSide of this "
                                         "message, so its relation to side " + side + " is not stated here")
        for i, relation in enumerate(codec.as_list(own, "ForceSideRelation")):
            if isinstance(relation, dict) and codec._optional_text(relation, "OtherSide") == side:
                code = codec._optional_text(relation, "HostilityStatusCode") or ""
                mapped = codec.HOSTILITY_TO_AFFILIATION.get(code)
                if mapped is not None:
                    return Affiliation(mapped), (f"{mapped}: own side {self._own_side} states "
                                                 f"ForceSideRelation[{i}] HostilityStatusCode {code} "
                                                 f"towards side {side}")
                return Affiliation.UNKNOWN, (f"UNKNOWN: own side {self._own_side} states HostilityStatusCode "
                                             f"{code!r} towards side {side}, a code outside FR/HO/NEUTRL "
                                             "(a judgement or a role, not a fact this axis carries); kept "
                                             "in organisation.force_side_relations of the side")
        return Affiliation.UNKNOWN, (f"UNKNOWN: own side {self._own_side} states no ForceSideRelation "
                                     f"towards side {side}")

    @staticmethod
    def _position_of(state: codec.PhysicalState, where: str) -> tuple[Position | None, Kinematics | None]:
        """The FIRST geodetic location is the entity's position; every location stays typed in
        the block. MSL and AGL heights are carried in `vertical`, never converted; MSL wins when
        both are stated (AGL stays in the block)."""
        position = None
        first = state.locations[0] if state.locations else None
        if first is not None and first.form == "GeodeticCoordinate":
            vertical = None
            if first.altitude_msl_m is not None:
                vertical = VerticalPosition(value=first.altitude_msl_m, unit=VerticalUnit.METRES,
                                            reference=VerticalReference.MSL)
            elif first.altitude_agl_m is not None:
                vertical = VerticalPosition(value=first.altitude_agl_m, unit=VerticalUnit.METRES,
                                            reference=VerticalReference.AGL)
            position = Position(lat=first.latitude, lon=first.longitude, alt_m=None,
                                position_source=PositionSource.ESTIMATED, vertical=vertical)
        kinematics = None
        if state.speed_mps is not None or state.heading_deg is not None:
            if state.speed_mps is not None and state.speed_mps < 0:
                raise ValueError(f"C2SIM {where}.Speed is {state.speed_mps}; a speed is not negative")
            course = state.heading_deg
            if course is not None and not 0.0 <= course < 360.0:
                raise ValueError(f"C2SIM {where}.DirectionOfMovement.Heading.HeadingAngle is {course}; "
                                 "a heading is [0, 360)")
            kinematics = Kinematics(speed_mps=state.speed_mps, course_deg=course)
        return position, kinematics

    def _entity(self, block: ObjectBlock, affiliation: Affiliation, position: Position | None,
                kinematics: Kinematics | None, index: int, header: Header, residual) -> Entity:
        valid_from = self._valid_from(block)
        entity_type = EntityType.PLATFORM if block.object_class in codec.PLATFORM_CLASSES else EntityType.UNIT
        return Entity(
            source=self._source(index, header, [f"affiliation: {block.affiliation_basis}"]
                                + ([f"valid_from: {valid_from[1]}"] if valid_from[1] else [])),
            source_ids=[{"system": SYSTEM, "external_id": block.uuid}],
            entity_id=ids.derive(SYSTEM, block.uuid, kind="object"),
            entity_type=entity_type,
            affiliation=affiliation,
            symbol=None,
            position=position,
            kinematics=kinematics,
            attributes={"c2sim": block.model_dump(mode="json", exclude_none=True)},
            valid_from=valid_from[0],
            residual=residual,
        )

    @staticmethod
    def _valid_from(block: ObjectBlock) -> tuple[Any, str]:
        """The state's own instant when the source states one, else the scenario's start
        (an initialisation describes the scenario AT its start): both are source-stated."""
        if block.state is not None and block.state.date_time is not None:
            return times.parse(block.state.date_time.resolved), "CurrentState/PhysicalState/DateTime"
        if block.scenario is not None:
            return (times.parse(block.scenario.date_time.resolved),
                    "ScenarioSetting/DateTime — the scenario's start, which the initialisation describes")
        raise ValueError(f"C2SIM object {block.uuid} states no instant and the message has no "
                         "ScenarioSetting; an Entity needs valid_from and nothing is invented")

    def _route(self, route: dict, where: str, index: int, header: Header, scenario: Scenario | None,
               consumed: set, rel: tuple) -> PlanObject:
        take = _Taker(route, consumed, rel)
        uuid = codec._uuid(take("UUID"), f"{where}.UUID")
        name = take.optional("Name")
        classifications = [codec.read_classification(item, f"{where}.EntityType[{i}]")
                           for i, item in enumerate(take.list("EntityType"))]
        if not classifications:
            raise ValueError(f"C2SIM {where} has no EntityType (EntityGroup declares it [1..*])")
        block = ObjectBlock(object_class="Route", uuid=uuid, name=name, classifications=classifications,
                            marking=take.optional("Marking"),
                            owner=codec._uuid(take("Owner"), f"{where}.Owner") if "Owner" in route else None,
                            message=header, scenario=scenario,
                            exercise_clock=self._exercise.as_dict() if self._exercise else None)
        if "CurrentState" not in route:
            raise ValueError(f"C2SIM {where} has no CurrentState (PhysicalEntityGroup declares it [1..1])")
        state = codec.read_physical_state(route["CurrentState"], f"{where}.CurrentState", self._exercise)
        physical = ("CurrentState", "PhysicalState")
        take.leaf(physical + ("DateTime", "IsoDateTime"))
        waypoints = []
        for i, location in enumerate(state.locations):
            if location.form != "GeodeticCoordinate":
                raise ValueError(f"C2SIM {where}.CurrentState.PhysicalState.Location[{i}] is a "
                                 "RelativeLocation; a route's points are geodetic (limitation: "
                                 "a relative route point is not resolved here)")
            take.leaf(physical + ("Location", i, "GeodeticCoordinate", "Latitude"))
            take.leaf(physical + ("Location", i, "GeodeticCoordinate", "Longitude"))
            vertical = None
            if location.altitude_msl_m is not None:
                take.leaf(physical + ("Location", i, "GeodeticCoordinate", "AltitudeMSL"))
                vertical = VerticalPosition(value=location.altitude_msl_m, unit=VerticalUnit.METRES,
                                            reference=VerticalReference.MSL)
            waypoints.append(Waypoint(position=Position(lat=location.latitude, lon=location.longitude,
                                                        position_source=PositionSource.ESTIMATED,
                                                        vertical=vertical), sequence=i))
        if len(waypoints) < 2:
            raise ValueError(f"C2SIM {where} states {len(waypoints)} point(s); a Route is a line and "
                             "needs two (models.Route)")
        validity = None
        if state.date_time is not None:
            validity = TemporalValidity(observed_at=times.parse(state.date_time.resolved))
        return PlanObject(
            source=self._source(index, header, ["geometry: the LineString projection of the route's "
                                                "points, in the order stated"]),
            source_ids=[{"system": SYSTEM, "external_id": uuid}],
            object_id=ids.derive(SYSTEM, uuid, kind="object"),
            object_type=ObjectType.ROUTE,
            label=name if name else None,
            geometry={"type": "LineString",
                      "coordinates": [[w.position.lon, w.position.lat] for w in waypoints]},
            style={},
            validity=validity,
            route=Route(waypoints=waypoints,
                        metadata={"c2sim": block.model_dump(mode="json", exclude_none=True)}),
        )

    # --- reports

    def _report(self, twin: dict, header: Header, body: Any, unknown: list) -> list[CDMBase]:
        where = "ReportBody"
        if not isinstance(body, dict):
            raise ValueError(f"C2SIM {where} is empty")
        for required in ("FromSender", "ToReceiver", "ReportID", "ReportingEntity"):
            if required not in body:
                raise ValueError(f"C2SIM {where} has no {required} (ReportBodyType declares it [1..1])")
        sender = codec._uuid(body["FromSender"], f"{where}.FromSender")
        receiver = codec._uuid(body["ToReceiver"], f"{where}.ToReceiver")
        report_id = codec._uuid(body["ReportID"], f"{where}.ReportID")
        reporter = codec._uuid(body["ReportingEntity"], f"{where}.ReportingEntity")
        contents = codec.as_list(body, "ReportContent")
        if not contents:
            raise ValueError(f"C2SIM {where} has no ReportContent (declared [1..*])")
        prefix = ("MessageBody", "DomainMessageBody", "ReportBody")
        consumed_message = {prefix + (name,) for name in ("FromSender", "ToReceiver", "ReportID", "ReportingEntity")}
        consumed_message |= {prefix + ("ReportContent", i) for i in range(len(contents))}
        message_residual = codec.prune(twin, consumed_message, ())
        events: list[CDMBase] = []
        for index, content in enumerate(contents):
            events.append(self._report_event(content, index, len(contents), report_id, reporter, sender,
                                             receiver, header, message_residual, unknown, twin))
        return events

    def _report_event(self, content: Any, index: int, count: int, report_id: str, reporter: str,
                      sender: str, receiver: str, header: Header, message_residual: Any, unknown: list,
                      twin: dict) -> Event:
        where = f"ReportBody.ReportContent[{index}]"
        if not isinstance(content, dict) or len([k for k in content if not k.startswith("@")]) != 1:
            raise ValueError(f"C2SIM {where} must hold exactly one of ObservationReportContent, "
                             "PositionReportContent or TaskStatus")
        kind = next(k for k in content if not k.startswith("@"))
        if kind not in ("PositionReportContent", "ObservationReportContent", "TaskStatus"):
            raise ValueError(f"C2SIM {where} holds {kind!r}, which is not a ReportContent form")
        inner = content[kind]
        if not isinstance(inner, dict):
            raise ValueError(f"C2SIM {where}.{kind} is empty")
        consumed: set[tuple] = set()
        take = _Taker(inner, consumed, (kind,))
        if "TimeOfObservation" not in inner:
            raise ValueError(f"C2SIM {where}.{kind} has no TimeOfObservation (ReportContentGroup declares it [1..1])")
        observed = codec.read_instant(inner["TimeOfObservation"], f"{where}.{kind}.TimeOfObservation", self._exercise)
        take.subtree("TimeOfObservation")
        duration = take.optional("Duration", "IsoTimeDuration")
        seconds = codec.duration_seconds(duration, f"{where}.{kind}.Duration.IsoTimeDuration") if duration else None
        fields: dict[str, Any] = {}
        subject = None
        geometry = None
        event_type = EventType.STATUS_CHANGE
        if kind == "PositionReportContent":
            event_type = EventType.TRACK_UPDATE
            if "Location" not in inner:
                raise ValueError(f"C2SIM {where}.PositionReportContent has no Location; a position "
                                 "report without a position is refused (never placed at 0, 0)")
            location = codec.read_location(inner["Location"], f"{where}.PositionReportContent.Location")
            take.subtree("Location")
            if location.form == "GeodeticCoordinate":
                geometry = {"type": "Point", "coordinates": [location.longitude, location.latitude]}
            fields["location"] = location
            fields["health"] = [codec.read_health(item, f"{where}.PositionReportContent.EntityHealthStatus[{i}]")
                                for i, item in enumerate(take.list("EntityHealthStatus"))]
            if "SubjectEntity" in inner:
                subject = codec._uuid(take("SubjectEntity"), f"{where}.PositionReportContent.SubjectEntity")
        elif kind == "ObservationReportContent":
            observations = take.list("Observation")
            if not observations:
                raise ValueError(f"C2SIM {where}.ObservationReportContent has no Observation (declared [1..*])")
            fields["observations"] = [codec.read_observation(item, f"{where}.ObservationReportContent.Observation[{i}]")
                                      for i, item in enumerate(observations)]
        else:
            fields["current_task"] = codec._uuid(take("CurrentTask"), f"{where}.TaskStatus.CurrentTask")
            code = take("TaskStatusCode")
            fields["task_status_code"] = code
            fields["task_status_in_pinned_enumeration"] = code in codec.ENUMERATIONS["TaskStatusCode"]
        if observed.resolved is None:
            raise ValueError(f"C2SIM {where}.{kind}.TimeOfObservation is a {observed.form} that this "
                             f"adapter cannot resolve to an instant ({observed.resolution}); an Event's "
                             "observed_at is required and nothing is invented")
        payload = ReportPayload(kind=kind, report_id=report_id, content_index=index, content_count=count,
                                reporting_entity=reporter, from_sender=sender, to_receiver=receiver,
                                subject_entity=subject, time_of_observation=observed, duration=duration,
                                duration_seconds=seconds, message=header,
                                exercise_clock=self._exercise.as_dict() if self._exercise else None,
                                **fields)
        related = []
        if subject is not None:
            related.append(ids.derive(SYSTEM, subject, kind="object"))
        residual = self._residual(message_residual, "ReportContent", codec.prune(content, consumed, ()), unknown, twin)
        notes = [f"observed_at: TimeOfObservation ({observed.form}, {observed.resolution})",
                 "event_id: derived from ReportID and the content's index — the report's identity, "
                 "distinct from the subject's"]
        if geometry is not None:
            notes.append("geometry: the reported point as [lon, lat]; MSL/AGL heights stay typed "
                         "in payload.c2sim.location, never on the GeoJSON position")
        return Event(
            source=self._source(index, header, notes),
            source_ids=[{"system": SYSTEM, "external_id": f"{report_id}#{index}"}],
            event_id=ids.derive(SYSTEM, f"{report_id}#{index}", kind="report"),
            event_type=event_type,
            severity=Severity.INFO,
            related_entities=related,
            geometry=geometry,
            payload={"c2sim": payload.model_dump(mode="json", exclude_none=True)},
            observed_at=times.parse(observed.resolved),
            received_at=self.now(),
            residual=residual,
        )

    # --- orders

    def _order(self, twin: dict, header: Header, body: Any, unknown: list) -> list[CDMBase]:
        where = "OrderBody"
        if not isinstance(body, dict):
            raise ValueError(f"C2SIM {where} is empty")
        for required in ("FromSender", "ToReceiver", "IssuedTime", "OrderID"):
            if required not in body:
                raise ValueError(f"C2SIM {where} has no {required} (OrderBodyType declares it [1..1])")
        prefix = ("MessageBody", "DomainMessageBody", "OrderBody")
        consumed: set[tuple] = set()
        take = _Taker(body, consumed, prefix)
        sender = codec._uuid(take("FromSender"), f"{where}.FromSender")
        receiver = codec._uuid(take("ToReceiver"), f"{where}.ToReceiver")
        issued = codec.read_date_time(body["IssuedTime"], f"{where}.IssuedTime")
        take.subtree("IssuedTime")
        order_id = codec._uuid(take("OrderID"), f"{where}.OrderID")
        requesting = codec._uuid(take("RequestingEntity"), f"{where}.RequestingEntity") if "RequestingEntity" in body else None
        references = [codec._uuid(v, f"{where}.TaskReference[{i}]") for i, v in enumerate(take.list("TaskReference"))]
        tasks_raw = codec.as_list(body, "Task")
        task_uuids: dict[str, int] = {}
        for i, task in enumerate(tasks_raw):
            mwt = task.get("ManeuverWarfareTask") if isinstance(task, dict) else None
            if not isinstance(mwt, dict):
                raise ValueError(f"C2SIM {where}.Task[{i}] holds no ManeuverWarfareTask (TaskType's one alternative)")
            uuid = codec._uuid(mwt.get("UUID"), f"{where}.Task[{i}].ManeuverWarfareTask.UUID")
            if uuid in task_uuids:
                raise ValueError(f"C2SIM {where}.Task[{i}] declares UUID {uuid}, already declared by "
                                 f"Task[{task_uuids[uuid]}]: two tasks with one identity are refused")
            task_uuids[uuid] = i
        task_residuals: list = []
        tasks = []
        for i, task in enumerate(tasks_raw):
            task_consumed: set[tuple] = set()
            tasks.append(self._task(task["ManeuverWarfareTask"], f"{where}.Task[{i}].ManeuverWarfareTask",
                                    task_consumed, ("ManeuverWarfareTask",), task_uuids))
            pruned = codec.prune(task, task_consumed, ())
            task_residuals.append(None if pruned is codec._DROPPED else pruned)
            consumed.add(prefix + ("Task", i))
        # Entities carried by the order (Route map graphics and any typed class) become their
        # own objects after the order event.
        entities = codec.as_list(body, "Entity")
        pending = []
        for e, entity in enumerate(entities):
            if self._typed_class_of(entity) is not None:
                consumed.add(prefix + ("Entity", e))
                pending.append((prefix + ("Entity", e), entity, f"{where}.Entity[{e}]"))
        message_residual = codec.prune(twin, consumed, ())
        payload = OrderPayload(order_id=order_id, from_sender=sender, to_receiver=receiver, issued_time=issued,
                               requesting_entity=requesting, tasks=tasks, task_references=references,
                               message=header, exercise_clock=self._exercise.as_dict() if self._exercise else None)
        related: list = []
        for uuid in [t.performing_entity for t in tasks] + [a for t in tasks for a in t.affected_entities] + [sender, receiver]:
            derived = ids.derive(SYSTEM, uuid, kind="object")
            if derived not in related:
                related.append(derived)
        data: dict = {}
        if isinstance(message_residual, dict):
            data.update(message_residual)
        if any(t is not None for t in task_residuals):
            data["Task"] = task_residuals
        if unknown:
            data["unknown"] = list(unknown)
        event = Event(
            source=self._source(0, header, ["observed_at: OrderBody/IssuedTime (a DateTime, stated)",
                                            "event_id: derived from OrderID"]),
            source_ids=[{"system": SYSTEM, "external_id": order_id}],
            event_id=ids.derive(SYSTEM, order_id, kind="order"),
            event_type=EventType.PLAN_INJECT,
            severity=Severity.INFO,
            related_entities=related,
            geometry=None,
            payload={"c2sim": payload.model_dump(mode="json", exclude_none=True)},
            observed_at=times.parse(issued.resolved),
            received_at=self.now(),
            residual=ResidualBlock(namespace=self.metadata.format.name, data=data),
        )
        objects: list[CDMBase] = [event]
        declared: dict[str, str] = {}
        for _, entity, w in pending:
            self._declare(declared, entity, w)
        for index, (_, entity, w) in enumerate(pending, start=1):
            objects.append(self._object_from("Entity", entity, w, index, header, None, declared, {},
                                             message_residual, unknown, twin))
        return objects

    def _task(self, task: dict, where: str, consumed: set, rel: tuple, task_uuids: dict[str, int]) -> codec.TaskBlock:
        take = _Taker(task, consumed, rel)
        uuid = codec._uuid(take("UUID"), f"{where}.UUID")
        code = take("TaskActionCode") if "TaskActionCode" in task else None
        if code is None:
            raise ValueError(f"C2SIM {where} has no TaskActionCode (TaskGroup declares it [1..1])")
        if code not in codec.SUPPORTED_TASK_ACTIONS:
            raise ValueError(f"C2SIM {where}.TaskActionCode {code!r} is outside the pinned task forms "
                             f"{codec.SUPPORTED_TASK_ACTIONS} (limitation `pinned-task-forms`, decision "
                             "D1); refused — no other task is substituted")
        if "PerformingEntity" not in task:
            raise ValueError(f"C2SIM {where} has no PerformingEntity (TaskGroup declares it [1..1])")
        performing = codec._uuid(take("PerformingEntity"), f"{where}.PerformingEntity")
        start = end = None
        if "StartTime" in task:
            start = codec.read_instant(task["StartTime"], f"{where}.StartTime", self._exercise)
            take.subtree("StartTime")
        if "EndTime" in task:
            end = codec.read_instant(task["EndTime"], f"{where}.EndTime", self._exercise)
            take.subtree("EndTime")
        duration = take.optional("Duration", "IsoTimeDuration")
        seconds = codec.duration_seconds(duration, f"{where}.Duration.IsoTimeDuration") if duration else None
        locations = [codec.read_location(item, f"{where}.Location[{i}]") for i, item in enumerate(take.list("Location"))]
        if code == "MoveToLocation" and not locations and not codec.as_list(task, "MapGraphicID"):
            raise ValueError(f"C2SIM {where} is a MoveToLocation task with no Location and no "
                             "MapGraphicID; the standard defines the destination as the task's "
                             "Location or its MapGraphicID (C2SIM.rdf, MoveToLocation), so a "
                             "movement with no destination is refused")
        temporal = []
        for i, item in enumerate(take.list("ActionTemporalRelationship")):
            tcode = codec._text(item, "ActionTemporalAssociationCode", f"{where}.ActionTemporalRelationship[{i}]")
            action = codec._uuid(codec._text(item, "TemporalAssociationWithAction", f"{where}.ActionTemporalRelationship[{i}]"),
                                 f"{where}.ActionTemporalRelationship[{i}].TemporalAssociationWithAction")
            tdur = codec._optional_text(item.get("Duration"), "IsoTimeDuration") if isinstance(item, dict) else None
            temporal.append(codec.TemporalRelationship(
                code=tcode, in_pinned_enumeration=tcode in codec.ENUMERATIONS["ActionTemporalAssociationCode"],
                duration=tdur,
                duration_seconds=codec.duration_seconds(tdur, f"{where}.ActionTemporalRelationship[{i}].Duration.IsoTimeDuration") if tdur else None,
                action=action, resolved_in_order=action in task_uuids))
        functional = []
        for i, item in enumerate(take.list("TaskFunctionalRelation")):
            fcode = codec._text(item, "TaskFunctionalAssociationCode", f"{where}.TaskFunctionalRelation[{i}]")
            other = codec._uuid(codec._text(item, "FunctionalAssociationWithTask", f"{where}.TaskFunctionalRelation[{i}]"),
                                f"{where}.TaskFunctionalRelation[{i}].FunctionalAssociationWithTask")
            functional.append(codec.FunctionalRelation(
                code=fcode, in_pinned_enumeration=fcode in codec.ENUMERATIONS["TaskFunctionalAssociationCode"],
                task=other, resolved_in_order=other in task_uuids))
        return codec.TaskBlock(
            uuid=uuid, name=take.optional("Name"), action_code=code, performing_entity=performing,
            affected_entities=[codec._uuid(v, f"{where}.AffectedEntity[{i}]") for i, v in enumerate(take.list("AffectedEntity"))],
            desired_effects=[codec._scalar(v, f"{where}.DesiredEffectCode[{i}]") for i, v in enumerate(take.list("DesiredEffectCode"))],
            start_time=start, end_time=end, duration=duration, duration_seconds=seconds, locations=locations,
            map_graphic_ids=[codec._uuid(v, f"{where}.MapGraphicID[{i}]") for i, v in enumerate(take.list("MapGraphicID"))],
            temporal_relationships=temporal, functional_relations=functional,
            rules_of_engagement=[r for r in take.list("RuleOfEngagement") if isinstance(r, dict)])

    # --- shared

    def _source(self, index: int, header: Header, notes: list[str]) -> SourceRef:
        source = self.source_ref()
        observed = times.parse(header.sending_time) if header.sending_time else None
        return source.model_copy(update={"record_index": index, "original_id": header.message_id,
                                         "observed_at": observed, "transformations": list(notes)})

    # ---------------------------------------------------------------------------- v2 surface

    def detect(self, raw: bytes | dict) -> bool | None:
        """The cheap structural test: a C2SIM-namespace `Message` root (or a twin holding one)."""
        if isinstance(raw, dict):
            return "C2SIMHeader" in raw and "MessageBody" in raw
        if isinstance(raw, (bytes, bytearray, str)):
            octets = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
            if len(octets) > C2SIM_MAX_INPUT_BYTES:
                return False
            head = octets.lstrip(b"\xef\xbb\xbf").lstrip()
            if head[:1] == b"{":
                try:
                    document = json.loads(octets)
                except (ValueError, TypeError):
                    return False
                return isinstance(document, dict) and "C2SIMHeader" in document and "MessageBody" in document
            return b"<Message" in head[:4096] and codec.NAMESPACE.encode() in head[:4096]
        return None

    def validate_source(self, raw: bytes | dict) -> list[str]:
        """Refusals first; then what the adapter accepts but the pinned contract would not or the
        reader should know: unknown elements and attributes, untyped object classes, header
        strings off the profile rule, codes outside their enumerations, unresolved order
        dependencies, unresolved instants."""
        try:
            twin = self._as_twin(raw)
            objects = self.to_cdm(raw)
        except Exception as problem:                     # noqa: BLE001 - reported, not raised
            return [f"{type(problem).__name__}: {problem}"]
        problems: list[str] = []
        for u in codec.unknowns_in(twin):
            problems.append(f"{u.path}: element or attribute {u.name!r} (namespace {u.namespace!r}, "
                            f"position {u.position}) is outside the pinned vocabulary; preserved, "
                            "not re-emitted")
        header = codec.read_header(twin.get("C2SIMHeader"))
        if not header.protocol_matches_pin:
            problems.append(f"Message.C2SIMHeader: Protocol {header.protocol!r} / ProtocolVersion "
                            f"{header.protocol_version!r} differ from the profile rule "
                            f"{codec.PROTOCOL!r} / {codec.PROTOCOL_VERSION!r} (SISO-STD-019-2020 §8.2)")
        if header.communicative_act not in codec.ENUMERATIONS["CommunicativeActTypeCode"]:
            problems.append(f"Message.C2SIMHeader.CommunicativeActTypeCode {header.communicative_act!r} "
                            "is outside CommunicativeActTypeCodeType")
        body = twin.get("MessageBody", {})
        init = body.get("C2SIMInitializationBody") if isinstance(body, dict) else None
        if isinstance(init, dict):
            for d, definition in enumerate(codec.as_list(init, "ObjectDefinitions")):
                if not isinstance(definition, dict):
                    continue
                for a, abstract in enumerate(codec.as_list(definition, "AbstractObject")):
                    if not (isinstance(abstract, dict) and "ForceSide" in abstract):
                        cls = next(iter(abstract), "?") if isinstance(abstract, dict) else "?"
                        problems.append(f"ObjectDefinitions[{d}].AbstractObject[{a}]: {cls} is an "
                                        "untyped object class; carried in the residual only")
                for e, entity in enumerate(codec.as_list(definition, "Entity")):
                    if self._typed_class_of(entity) is None:
                        problems.append(f"ObjectDefinitions[{d}].Entity[{e}]: an untyped object class "
                                        f"({_class_path(entity)}); carried in the residual only")
                for a, _ in enumerate(codec.as_list(definition, "Action")):
                    problems.append(f"ObjectDefinitions[{d}].Action[{a}]: untyped; carried in the residual only")
        for obj in objects:
            block = obj.attributes.get("c2sim") if isinstance(obj, Entity) else None
            payload = obj.payload.get("c2sim") if isinstance(obj, Event) else None
            for path, value in lossless.leaves(block or payload or {}).items():
                if path.endswith("in_pinned_enumeration") and value is False:
                    problems.append(f"{obj.object_kind} {obj.source_ids[0].external_id}: {path[:-len('.in_pinned_enumeration')]} "
                                    "is a code outside its pinned enumeration; carried verbatim")
                if path.endswith("resolved_in_order") and value is False:
                    problems.append(f"{obj.object_kind} {obj.source_ids[0].external_id}: {path[:-len('.resolved_in_order')]} "
                                    "references a task outside this order; carried, not resolved")
                if path.endswith(".resolution") and str(value).startswith("unresolved"):
                    problems.append(f"{obj.object_kind} {obj.source_ids[0].external_id}: {path[:-len('.resolution')]} "
                                    f"{value}")
        return problems

    # ------------------------------------------------------------------------------ egress

    def from_cdm(self, objects: list[CDMBase]) -> bytes:
        """One Message from the objects of one message: an initialisation from Entities and
        PlanObjects, an order from one order Event (plus its Route PlanObjects), a report from
        the Events of one report. Refused with the reason when the objects cannot share a
        message or a record lacks an essential element."""
        if not objects:
            raise EgressRefused("C2SIM egress: no objects; a Message carries a body and an empty "
                                "body is not one of the schema's")
        for obj in objects:
            if not isinstance(obj, (Entity, Event, PlanObject)):
                raise EgressRefused(f"C2SIM egress: a {obj.object_kind} has no C2SIM form; "
                                    "Entities, PlanObjects and Events are what this adapter emits")
        events = [o for o in objects if isinstance(o, Event)]
        orders = [e for e in events if (e.payload.get("c2sim") or {}).get("contract") == codec.ORDER_CONTRACT]
        reports = [e for e in events if (e.payload.get("c2sim") or {}).get("contract") == codec.REPORT_CONTRACT]
        if len(orders) + len(reports) != len(events):
            stray = [str(e.event_id) for e in events if e not in orders and e not in reports]
            raise EgressRefused(f"C2SIM egress: event(s) {stray} carry no `payload.c2sim` block with a "
                                f"contract of {codec.ORDER_CONTRACT!r} or {codec.REPORT_CONTRACT!r}; an "
                                "order or a report is built from that block and nothing is invented")
        if orders and reports:
            raise EgressRefused("C2SIM egress: an order and a report cannot share one Message; "
                                "export them separately")
        if len(orders) > 1:
            raise EgressRefused(f"C2SIM egress: {len(orders)} orders; one Message carries one "
                                "OrderBody — export each order with its own call")
        if orders:
            return self._emit_order(orders[0], [o for o in objects if not isinstance(o, Event)])
        if reports:
            if any(not isinstance(o, Event) for o in objects):
                raise EgressRefused("C2SIM egress: a ReportBody carries report contents only; "
                                    "the Entities or PlanObjects here belong in an initialisation")
            return self._emit_report(reports)
        return self._emit_initialisation(objects)

    def _header_for(self, objects: list[CDMBase]) -> Header:
        """The objects' own header when every object carries the same one, else the constructed
        Envelope, else a refusal."""
        found: list[Header] = []
        for obj in objects:
            block = _typed_block(obj)
            if block is not None and isinstance(block.get("message"), dict):
                header = Header.model_validate(block["message"])
                if header not in found:
                    found.append(header)
        if len(found) > 1:
            if self._envelope is None:
                raise EgressRefused("C2SIM egress: the objects carry two different message headers "
                                    "(they came from different messages); export each message's "
                                    "objects separately, or construct the adapter with an Envelope "
                                    "for the new message")
            return self._envelope.header()
        if found:
            return found[0]
        if self._envelope is None:
            raise EgressRefused("C2SIM egress: no object carries a C2SIM header and no Envelope was "
                                "constructed (C2simAdapter(envelope=Envelope(message_id, "
                                "conversation_id, from_sending_system, to_receiving_system))); a "
                                "header's four required strings are not invented")
        return self._envelope.header()

    def _message(self, header: Header, body_key: str, body: dict, residuals: list[Any]) -> bytes:
        """Assemble and serialise, with the message-level residual leftovers (the first object's;
        every object of one message carries the same) merged back around the typed body."""
        message: dict = {"C2SIMHeader": codec.header_node(header), "MessageBody": {body_key: body}}
        leftover = next((r for r in residuals if isinstance(r, dict)), None)
        if leftover:
            # The header lives in the residual too (every object kind carries it there) and the
            # typed one wins, so only the body's leftovers are grafted.
            message = codec.merge(message, {"MessageBody": leftover})
        return codec.serialise(codec.strip_unknown("Message", message))

    def _emit_initialisation(self, objects: list[CDMBase]) -> bytes:
        header = self._header_for(objects)
        abstract: list = []
        entities: list = []
        scenario = None
        for obj in objects:
            block = _typed_block(obj)
            if isinstance(obj, Entity):
                if block is None:
                    raise EgressRefused(f"C2SIM egress: entity {obj.entity_id} has no `attributes.c2sim` "
                                        "block; the schema needs a UUID, an EntityType and (for a Unit) "
                                        "an EchelonCode, none of which the CDM's own fields state")
                typed = ObjectBlock.model_validate(block)
                if scenario is None and typed.scenario is not None:
                    scenario = typed.scenario
                own = (obj.residual.data.get("AbstractObject") if _own_residual(obj, self) else None)
                if typed.object_class == "ForceSide":
                    abstract.append(codec.merge({"ForceSide": self._force_side_node(typed, obj)}, own))
                else:
                    own = obj.residual.data.get("Entity") if _own_residual(obj, self) else None
                    entities.append(codec.merge(self._actor_entity_node(typed, obj), own))
            else:
                own = obj.residual.data.get("Entity") if _own_residual(obj, self) else None
                entities.append(codec.merge(self._route_entity_node(obj), own))
        if scenario is None:
            raise EgressRefused("C2SIM egress: no object states a ScenarioSetting (attributes.c2sim."
                                "scenario: date_time + version), which C2SIMInitializationBody "
                                "requires; nothing is invented")
        definitions: dict = {}
        if abstract:
            definitions["AbstractObject"] = abstract
        if entities:
            definitions["Entity"] = entities
        body: dict = {"ObjectDefinitions": [definitions],
                      "ScenarioSetting": {"DateTime": codec.date_time_node(scenario.date_time),
                                          "Version": scenario.version}}
        residuals = [o.residual.data.get("MessageBody") for o in objects if _own_residual(o, self)]
        carried = any(_dig(r, ("C2SIMInitializationBody", "SystemEntityList")) for r in residuals)
        if self._envelope is not None and self._envelope.system_entities:
            body["SystemEntityList"] = [{"ActorReference": list(actors), "SystemName": system}
                                        for system, actors in self._envelope.system_entities]
        elif not carried:
            raise EgressRefused("C2SIM egress: C2SIMInitializationBody requires at least one "
                                "SystemEntityList naming the system that simulates each actor "
                                "(declared [1..*]); no object carries one from a source message and "
                                "the Envelope names none (Envelope(system_entities=((system, "
                                "(uuid, ...)), ...))). Nothing is invented")
        return self._message(header, "C2SIMInitializationBody", body, residuals)

    @staticmethod
    def _force_side_node(typed: ObjectBlock, obj: CDMBase) -> dict:
        node: dict = {}
        if typed.names:
            node["Name"] = list(typed.names)
        node["UUID"] = typed.uuid
        relations = typed.organisation.force_side_relations if typed.organisation else []
        if relations:
            node["ForceSideRelation"] = [{"HostilityStatusCode": r.hostility, "OtherSide": r.other_side}
                                         for r in relations]
        return node

    def _actor_entity_node(self, typed: ObjectBlock, obj: Entity) -> dict:
        cls = typed.object_class
        if cls not in codec.ACTOR_CLASSES:
            raise EgressRefused(f"C2SIM egress: entity {typed.uuid} has object_class {cls!r}; this "
                                f"adapter emits {codec.ACTOR_CLASSES} and ForceSide")
        if not typed.classifications:
            raise EgressRefused(f"C2SIM egress: entity {typed.uuid} states no classification "
                                "(EntityGroup declares EntityType [1..*]); nothing is invented")
        org = typed.organisation or codec.Organisation()
        if cls == "Unit" and not org.echelon:
            raise EgressRefused(f"C2SIM egress: unit {typed.uuid} states no echelon (UnitType declares "
                                "EchelonCode [1..1]); nothing is invented")
        descriptor: dict = {}
        if org.affiliated_with:
            descriptor["AffiliatedWith"] = list(org.affiliated_with)
        if org.allegiance_relationships:
            descriptor["AllegianceRelationship"] = [{"ActorReference": a.actor, "AllegianceRelationshipCode": a.code}
                                                    for a in org.allegiance_relationships]
        if org.communications_networks:
            descriptor["CommunicationsNetwork"] = list(org.communications_networks)
        if org.side is not None:
            descriptor["Side"] = org.side
        if org.superior is not None:
            descriptor["Superior"] = org.superior
        node: dict = {}
        if org.current_tasks:
            node["CurrentTask"] = list(org.current_tasks)
        node["EntityDescriptor"] = descriptor
        if cls == "Unit":
            if typed.state is not None:
                node["CurrentState"] = codec.physical_state_node(typed.state)
            if org.subordinates:
                node["Subordinate"] = list(org.subordinates)
        node["EntityType"] = [codec.classification_node(c) for c in typed.classifications]
        if typed.name is not None:
            node["Name"] = typed.name
        node["UUID"] = typed.uuid
        if cls == "Unit":
            if org.command_relations:
                node["CommandRelation"] = [{"ActorReference": c.actor, "CommandRelationCode": c.code}
                                           for c in org.command_relations]
            node["EchelonCode"] = org.echelon
        else:
            if typed.state is not None:
                node["CurrentState"] = codec.physical_state_node(typed.state)
            if typed.marking is not None:
                node["Marking"] = typed.marking
        if typed.state is None and obj.position is not None:
            raise EgressRefused(f"C2SIM egress: entity {typed.uuid} has a position but its typed block "
                                "states no physical state; a Location is written from the block's "
                                "state (attributes.c2sim.state.locations), not projected back from "
                                "position, so the two cannot disagree")
        if cls == "Unit":
            return {"ActorEntity": {"CollectiveEntity": {"MilitaryOrganization": {"Unit": node}}}}
        return {"ActorEntity": {"Platform": {cls: node}}}

    @staticmethod
    def _route_entity_node(obj: PlanObject) -> dict:
        if obj.object_type is not ObjectType.ROUTE or obj.route is None:
            raise EgressRefused(f"C2SIM egress: plan object {obj.object_id} is not a ROUTE with "
                                "waypoints; the Route map graphic is the one PlanObject form this "
                                "adapter emits")
        block = _typed_block(obj)
        if block is None:
            raise EgressRefused(f"C2SIM egress: route {obj.object_id} has no `route.metadata.c2sim` "
                                "block; the schema needs a UUID and an EntityType for a Route map "
                                "graphic and neither is invented from the CDM's own fields")
        typed = ObjectBlock.model_validate(block)
        if typed.object_class != "Route":
            raise EgressRefused(f"C2SIM egress: plan object {obj.object_id} has object_class "
                                f"{typed.object_class!r}; the Route map graphic is the one PlanObject "
                                "form this adapter emits")
        if not typed.classifications:
            raise EgressRefused(f"C2SIM egress: route {typed.uuid} states no classification (EntityGroup "
                                "declares EntityType [1..*]); nothing is invented")
        node: dict = {"EntityType": [codec.classification_node(c) for c in typed.classifications]}
        if obj.label is not None:
            node["Name"] = obj.label
        node["UUID"] = typed.uuid
        state: dict = {}
        if obj.validity is not None and obj.validity.observed_at is not None:
            state["DateTime"] = {"IsoDateTime": codec.render_iso_date_time(obj.validity.observed_at)}
        locations = []
        for waypoint in sorted(obj.route.waypoints, key=lambda w: w.sequence):
            coordinate: dict = {}
            vertical = waypoint.position.vertical
            if vertical is not None and vertical.reference is VerticalReference.MSL and vertical.unit is VerticalUnit.METRES:
                coordinate["AltitudeMSL"] = codec._render_number(vertical.value)
            coordinate["Latitude"] = codec._render_number(waypoint.position.lat)
            coordinate["Longitude"] = codec._render_number(waypoint.position.lon)
            locations.append({"GeodeticCoordinate": coordinate})
        state["Location"] = locations
        node["CurrentState"] = {"PhysicalState": state}
        if typed.marking is not None:
            node["Marking"] = typed.marking
        if typed.owner is not None:
            node["Owner"] = typed.owner
        return {"PhysicalEntity": {"MapGraphic": {"TacticalGraphic": {"Line": {"Route": node}}}}}

    def _emit_order(self, event: Event, extras: list[CDMBase]) -> bytes:
        header = self._header_for([event] + extras)
        payload = OrderPayload.model_validate(event.payload["c2sim"])
        own = event.residual.data if _own_residual(event, self) else {}
        task_residuals = own.get("Task") or []
        tasks = []
        for i, task in enumerate(payload.tasks):
            if task.action_code not in codec.SUPPORTED_TASK_ACTIONS:
                raise EgressRefused(f"C2SIM egress: task {task.uuid} has action code {task.action_code!r}, "
                                    f"outside the pinned forms {codec.SUPPORTED_TASK_ACTIONS}; refused — "
                                    "no other task is substituted (limitation `pinned-task-forms`)")
            node = {"ManeuverWarfareTask": self._task_node(task)}
            left = task_residuals[i] if i < len(task_residuals) else None
            tasks.append(codec.merge(node, left))
        body: dict = {"FromSender": payload.from_sender, "ToReceiver": payload.to_receiver}
        entities = []
        for obj in extras:
            if isinstance(obj, PlanObject):
                left = obj.residual.data.get("Entity") if _own_residual(obj, self) else None
                entities.append(codec.merge(self._route_entity_node(obj), left))
            else:
                block = _typed_block(obj)
                if block is None:
                    raise EgressRefused(f"C2SIM egress: entity {obj.entity_id} beside an order has no "
                                        "`attributes.c2sim` block")
                left = obj.residual.data.get("Entity") if _own_residual(obj, self) else None
                entities.append(codec.merge(self._actor_entity_node(ObjectBlock.model_validate(block), obj), left))
        if entities:
            body["Entity"] = entities
        body["IssuedTime"] = codec.date_time_node(payload.issued_time)
        body["OrderID"] = payload.order_id
        if payload.requesting_entity is not None:
            body["RequestingEntity"] = payload.requesting_entity
        if tasks:
            body["Task"] = tasks
        if payload.task_references:
            body["TaskReference"] = list(payload.task_references)
        return self._message(header, "DomainMessageBody", {"OrderBody": body}, [own.get("MessageBody")])

    @staticmethod
    def _task_node(task: codec.TaskBlock) -> dict:
        node: dict = {}
        if task.temporal_relationships:
            rows = []
            for r in task.temporal_relationships:
                row: dict = {"ActionTemporalAssociationCode": r.code}
                if r.duration is not None:
                    row["Duration"] = {"IsoTimeDuration": r.duration}
                row["TemporalAssociationWithAction"] = r.action
                rows.append(row)
            node["ActionTemporalRelationship"] = rows
        if task.locations:
            node["Location"] = [codec.location_node(loc) for loc in task.locations]
        if task.map_graphic_ids:
            node["MapGraphicID"] = list(task.map_graphic_ids)
        if task.name is not None:
            node["Name"] = task.name
        node["UUID"] = task.uuid
        if task.affected_entities:
            node["AffectedEntity"] = list(task.affected_entities)
        if task.desired_effects:
            node["DesiredEffectCode"] = list(task.desired_effects)
        if task.duration is not None:
            node["Duration"] = {"IsoTimeDuration": task.duration}
        if task.end_time is not None:
            node["EndTime"] = codec.instant_node(task.end_time)
        if not task.performing_entity:
            raise EgressRefused(f"C2SIM egress: task {task.uuid} names no performing entity (TaskGroup "
                                "declares PerformingEntity [1..1]); nothing is invented")
        node["PerformingEntity"] = task.performing_entity
        if task.start_time is not None:
            node["StartTime"] = codec.instant_node(task.start_time)
        node["TaskActionCode"] = task.action_code
        if task.rules_of_engagement:
            node["RuleOfEngagement"] = list(task.rules_of_engagement)
        if task.functional_relations:
            node["TaskFunctionalRelation"] = [{"FunctionalAssociationWithTask": r.task,
                                               "TaskFunctionalAssociationCode": r.code}
                                              for r in task.functional_relations]
        return node

    def _emit_report(self, events: list[Event]) -> bytes:
        header = self._header_for(events)
        payloads = [ReportPayload.model_validate(e.payload["c2sim"]) for e in events]
        report_ids = {p.report_id for p in payloads}
        if len(report_ids) > 1:
            raise EgressRefused(f"C2SIM egress: the events belong to {len(report_ids)} reports "
                                f"({sorted(report_ids)}); one Message carries one ReportBody — export "
                                "each report's contents with their own call")
        for field in ("reporting_entity", "from_sender", "to_receiver"):
            if len({getattr(p, field) for p in payloads}) > 1:
                raise EgressRefused(f"C2SIM egress: the report contents disagree on {field}; they are "
                                    "not one report")
        ordered = sorted(zip(payloads, events), key=lambda pair: pair[0].content_index)
        contents = []
        for payload, event in ordered:
            left = event.residual.data.get("ReportContent") if _own_residual(event, self) else None
            contents.append(codec.merge(self._content_node(payload), left))
        first = ordered[0][0]
        body = {"FromSender": first.from_sender, "ToReceiver": first.to_receiver,
                "ReportContent": contents, "ReportID": first.report_id,
                "ReportingEntity": first.reporting_entity}
        residuals = [e.residual.data.get("MessageBody") for e in events if _own_residual(e, self)]
        return self._message(header, "DomainMessageBody", {"ReportBody": body}, residuals)

    @staticmethod
    def _content_node(payload: ReportPayload) -> dict:
        inner: dict = {}
        if payload.duration is not None:
            inner["Duration"] = {"IsoTimeDuration": payload.duration}
        inner["TimeOfObservation"] = codec.instant_node(payload.time_of_observation)
        if payload.kind == "PositionReportContent":
            if payload.health:
                inner["EntityHealthStatus"] = [codec.health_node(h) for h in payload.health]
            if payload.location is None:
                raise EgressRefused(f"C2SIM egress: position report {payload.report_id}#{payload.content_index} "
                                    "states no location; refused, never placed at 0, 0")
            inner["Location"] = codec.location_node(payload.location)
            if payload.subject_entity is not None:
                inner["SubjectEntity"] = payload.subject_entity
        elif payload.kind == "ObservationReportContent":
            if not payload.observations:
                raise EgressRefused(f"C2SIM egress: observation report {payload.report_id}#{payload.content_index} "
                                    "carries no observation (declared [1..*])")
            inner["Observation"] = [codec.observation_node(o) for o in payload.observations]
        else:
            if not payload.current_task or not payload.task_status_code:
                raise EgressRefused(f"C2SIM egress: task status {payload.report_id}#{payload.content_index} "
                                    "needs current_task and task_status_code")
            inner["CurrentTask"] = payload.current_task
            inner["TaskStatusCode"] = payload.task_status_code
        return {payload.kind: inner}


# ------------------------------------------------------------------------------------ helpers


class _Taker:
    """Reads a node's children and records each consumed leaf's path (relative to the object
    element) so `prune` can leave exactly the rest."""

    def __init__(self, node: dict, consumed: set[tuple], rel: tuple) -> None:
        self.node, self.consumed, self.rel = node, consumed, rel

    def __call__(self, child: str) -> str:
        if child not in self.node:
            raise ValueError(f"C2SIM element has no {child}")
        self.consumed.add(self.rel + (child,))
        return codec._scalar(self.node[child], child)

    def optional(self, child: str, inner: str | None = None) -> str | None:
        if child not in self.node:
            return None
        if inner is None:
            return self(child)
        self.consumed.add(self.rel + (child, inner))
        return codec._text(self.node[child], inner, child)

    def list(self, child: str) -> list:
        items = codec.as_list(self.node, child)
        for i in range(len(items)):
            self.consumed.add(self.rel + (child, i))
        return items

    def subtree(self, child: str) -> None:
        if child in self.node:
            self.consumed.add(self.rel + (child,))

    def leaf(self, path: tuple) -> None:
        self.consumed.add(self.rel + path)


def _find_uuid(node: Any) -> tuple[str, str] | None:
    """(UUID text, class element name) of an object element, by descending the single-child
    chain to the element that carries a UUID."""
    current, name = node, "?"
    for _ in range(8):
        if not isinstance(current, dict):
            return None
        if "UUID" in current:
            return codec._scalar(current["UUID"], "UUID"), name
        keys = [k for k in current if not k.startswith("@")]
        if len(keys) != 1:
            return None
        name, current = keys[0], current[keys[0]]
    return None


def _class_path(entity: Any) -> str:
    parts = []
    current = entity
    for _ in range(6):
        if not isinstance(current, dict):
            break
        keys = [k for k in current if not k.startswith("@")]
        if len(keys) != 1:
            break
        parts.append(keys[0])
        current = current[keys[0]]
    return "/".join(parts) or "?"


def _typed_block(obj: CDMBase) -> dict | None:
    if isinstance(obj, Entity):
        block = obj.attributes.get("c2sim")
    elif isinstance(obj, Event):
        block = obj.payload.get("c2sim")
    elif isinstance(obj, PlanObject) and obj.route is not None:
        block = obj.route.metadata.get("c2sim")
    else:
        return None
    return block if isinstance(block, dict) else None


def _own_residual(obj: CDMBase, adapter: Adapter) -> bool:
    return (isinstance(obj.residual, ResidualBlock)
            and obj.residual.namespace == adapter.metadata.format.name
            and isinstance(obj.residual.data, dict))


def _dig(node: Any, path: tuple) -> Any:
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


__all__ = ["C2simAdapter", "Envelope", "ExerciseClock", "EgressRefused", "ObjectCountExceeded",
           "C2SIM_MAX_INPUT_BYTES", "C2SIM_MAX_DEPTH", "C2SIM_MAX_ELEMENTS", "C2SIM_MAX_OBJECTS"]
