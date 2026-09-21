"""The C2SIM codec: the pinned schema's content model as data, XML <-> parsed twin, the typed
contract blocks the adapter writes, and the time model. No canonical object is built here —
`adapters/c2sim.py` does that — and nothing here reads a file or a socket.

THE SCHEMA AS DATA
------------------
`CONTENT` is every complex global element of the pinned composite schema (`C2SIM_SMX_LOX.xsd`
from OpenC2SIM/C2SIMArtifacts v1.0.1, SHA-256 `33b02101…`, generated from the SISO-STD-019-2020 /
SISO-STD-020-2020 v1.0 ontologies) with its children IN SCHEMA ORDER and whether each child may
repeat. It was generated from the XSD on 2026-09-21 by walking each element's type through its
`xs:sequence`, `xs:choice` and `xs:group` references (a choice's alternatives are listed in
order; an element under an unbounded particle is marked repeatable) and is the one table three
things read: the twin builder (a repeatable child is ALWAYS a list, so a twin's shape does not
depend on how many of a child a document happened to carry), the emitter (children are written in
the schema's sequence, so a merge of canonical values and residual leftovers stays valid), and
the unknown-element reader (a child the table does not name under its parent is outside the
pinned vocabulary). The table is data derived from the standard, not prose about it; every name
in it is the schema's own.

`ENUMERATIONS` holds the closed vocabularies the adapter READS a value against — never rewrites:
a status code outside its enumeration is carried verbatim with `in_pinned_enumeration: false`,
which is what "preserve unknown codes without inventing a replacement meaning" looks like as
data. `TaskActionCode`'s 453 values are NOT here: the adapter admits exactly the two pinned
forms (`SUPPORTED_TASK_ACTIONS`, decision D1) and refuses every other code by name.

THE PARSED TWIN
---------------
`twin_of(root)` is the document as a dict — the CONTENT of the one root element the schema
permits (`Message`), whose name is therefore implied rather than spelled: `C2SIMHeader`,
`MessageBody`, and any attribute or foreign member the root itself carried. An element in the
C2SIM namespace is keyed by its local name, an element in any other namespace by its Clark form
`{uri}local`, an attribute as `@name` (or `@{uri}name`), a text-only element as its text, a
repeatable child as a list, and insertion order is document order. It is the form the harness
replays from `*.parsed.json` and the form the preservation ledger walks; a unit's position sits
sixteen containers deep in it, which is the harness loader's own margin (`LOADER_MAX_DEPTH / 4`)
and the reason the root wrapper is not a seventeenth. `element_of("Message", twin)` is its
inverse, ordering children by `CONTENT` where the parent is known and by insertion order where
it is not.

THE TIME MODEL
--------------
A C2SIM `TimeInstant` has three forms and every one is kept as it was stated (`Instant`):

    DateTime        an ISO instant in Z — the scenario clock's own reading. Resolved as stated.
    SimulationTime  a duration since the scenario start ("A time measured as a time duration
                    since the time instant of the scenario start", C2SIM.rdf). Resolved ONLY
                    against a caller-supplied `ExerciseClock` (epoch + elapsed); with none it
                    stays unresolved and the adapter refuses to build an object that needs the
                    instant. Elapsed simulation seconds are never Unix time.
    RelativeTime    a delay from another event's start or end. Never resolved here: the event's
                    own time is not in the message.

`ExerciseClock.rate` is the scenario-seconds-per-wall-second ratio the exercise runs at. It is
recorded on every object that used the clock and it enters NO conversion: a SimulationTime is
scenario seconds since the scenario epoch, and rate relates wall-clock to scenario time, which
is a different question. The header's `SendingTime` is message time — the record's own instant,
kept at `source.observed_at` and never mixed with either of the above.

`IsoTimeDuration` is the schema's `P00Y00M00DT00H00M00S` pattern. A duration with a non-zero
year or month component has no fixed length in seconds and is carried as text only
(`elapsed_seconds: None`).
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import re
import xml.etree.ElementTree as ET
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from synapse_cdm import times

NAMESPACE = "http://www.sisostds.org/schemas/C2SIM/1.1"
NS = "{" + NAMESPACE + "}"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"

#: SISO-STD-019-2020 §8.2 and the Core ontology's `C2SIMHeader` restrictions — a profile rule,
#: since the XSD types both as unrestricted `xs:string`.
PROTOCOL = "SISO-STD-C2SIM"
PROTOCOL_VERSION = "1.0.0"

#: Decision D1: the two standard-defined, non-engagement exercise task forms this adapter
#: carries, both Core individuals of `TaskActionCodeType` (schema lines 3406–3407).
SUPPORTED_TASK_ACTIONS = ("HoldInPlace", "MoveToLocation")

#: The versioned contract identifiers of the typed blocks below.
OBJECT_CONTRACT = "c2sim-object/1"
ORDER_CONTRACT = "c2sim-order/1"
REPORT_CONTRACT = "c2sim-report/1"

#: The object classes the adapter types, and what each becomes. Everything else in an
#: initialisation is carried in the residual, untyped, and named by `validate_source`.
ACTOR_CLASSES = ("Unit", "Aircraft", "Vehicle", "SurfaceVessel", "SubsurfaceVessel")
PLATFORM_CLASSES = ("Aircraft", "Vehicle", "SurfaceVessel", "SubsurfaceVessel")

# --------------------------------------------------------------------------- the schema as data

#: element -> ((child, repeatable), ...) in schema sequence order. Generated from the pinned XSD
#: (see the module docstring); every name is the schema's.
CONTENT: dict[str, tuple[tuple[str, bool], ...]] = {
    "APP6-SIDC": (("SIDCString", False),),
    "AbstractObject": (("AbstractOrganization", False), ("CommunicationNetwork", False), ("ForceSide", False), ("Overlay", False)),
    "AbstractOrganization": (("Name", True), ("UUID", False), ("CountryCode", False), ("EthnicGroupCode", False), ("OrganizationTypeCode", False), ("ReligionCode", False)),
    "AcknowledgementBody": (("FromSender", False), ("ToReceiver", False), ("AcknowledgeTypeCode", False)),
    "Action": (("Event", False), ("Task", False)),
    "ActionCode": (("EventCode", False), ("TaskActionCode", False)),
    "ActionTemporalRelationship": (("ActionTemporalAssociationCode", False), ("Duration", False), ("TemporalAssociationWithAction", False)),
    "ActivityObservation": (("ActorReference", False), ("ConfidenceLevel", False), ("UncertaintyInterval", False), ("ActionCode", False)),
    "ActorEntity": (("CollectiveEntity", False), ("Person", False), ("Platform", False)),
    "Aircraft": (("CurrentTask", True), ("EntityDescriptor", False), ("Resource", True), ("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False)),
    "AllegianceRelationship": (("ActorReference", False), ("AllegianceRelationshipCode", False)),
    "Boundary": (("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False), ("Owner", False)),
    "C2SIMContent": (("AbstractObject", False), ("Action", False), ("Code", False), ("Entity", False), ("EntityDescriptor", False), ("EntityState", False), ("EntityType", False), ("Observation", False), ("PhysicalConcept", False), ("PlanPhase", False), ("PlanPhaseTrigger", False), ("Relationship", False), ("Resource", False), ("RuleOfEngagement", False)),
    "C2SIMHeader": (("CommunicativeActTypeCode", False), ("ConversationID", False), ("FromSendingSystem", False), ("InReplyToMessageID", False), ("MessageID", False), ("Protocol", False), ("ProtocolVersion", False), ("ReplyToSystem", False), ("SecurityClassificationCode", False), ("SendingTime", False), ("ToReceivingSystem", False)),
    "C2SIMInitializationBody": (("InitializationDataFile", True), ("ObjectDefinitions", True), ("ScenarioSetting", False), ("SystemEntityList", True)),
    "CartesianOffset": (("East", False), ("North", False), ("Up", False)),
    "Code": (("ActionCode", False), ("ActionTemporalAssociationCode", False), ("AllegianceRelationshipCode", False), ("CommandRelationCode", False), ("DesiredEffectCode", False), ("EchelonCode", False), ("HostilityStatusCode", False), ("OperationalStatusCode", False), ("OrganizationCode", False), ("PlanPhaseCompletionCondition", False), ("ReinforcedReducedType", False), ("SecurityClassificationCode", False), ("TaskFunctionalAssociationCode", False), ("TimeReferenceCode", False), ("WeaponRuleOfEngagementCode", False)),
    "CollectiveEntity": (("MilitaryOrganization", False), ("NonMilitaryOrganization", False)),
    "CommandRelation": (("ActorReference", False), ("CommandRelationCode", False)),
    "CommunicationNetwork": (("Name", True), ("UUID", False)),
    "CulturalFeature": (("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False)),
    "CurrentState": (("PhysicalState", False),),
    "DISEntityType": (("DISCategory", False), ("DISCountry", False), ("DISDomain", False), ("DISExtra", False), ("DISKind", False), ("DISSpecific", False), ("DISSubCategory", False)),
    "DateTime": (("Name", False), ("IsoDateTime", False)),
    "DelayTimeAmount": (("IsoTimeDuration", False),),
    "DirectionOfMovement": (("EulerAngles", False), ("Heading", False)),
    "DomainMessageBody": (("AcknowledgementBody", False), ("OrderBody", False), ("PlanBody", False), ("ReportBody", False), ("RequestBody", False)),
    "Duration": (("IsoTimeDuration", False),),
    "EndTime": (("DateTime", False), ("RelativeTime", False), ("SimulationTime", False)),
    "Entity": (("ActorEntity", False), ("PhysicalEntity", False)),
    "EntityDescriptor": (("AffiliatedWith", True), ("AllegianceRelationship", True), ("CommunicationsNetwork", True), ("Side", False), ("Superior", False)),
    "EntityHealthStatus": (("OperationalStatus", False), ("Resources", False), ("Strength", False)),
    "EntityState": (("PhysicalState", False),),
    "EntityType": (("APP6-SIDC", False), ("DISEntityType", False), ("NamedEntityType", False)),
    "EnvironmentalObject": (("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False)),
    "EulerAngles": (("HeadingAngle", False), ("Phi", False), ("Psi", False), ("Theta", False)),
    "Event": (("ActionTemporalRelationship", True), ("Location", True), ("MapGraphicID", True), ("Name", False), ("UUID", False), ("Duration", False), ("EventCode", False), ("StartTime", False)),
    "EventTrigger": (("Event", False),),
    "ForceSide": (("Name", True), ("UUID", False), ("ForceSideRelation", True)),
    "ForceSideRelation": (("HostilityStatusCode", False), ("OtherSide", False)),
    "GeodeticCoordinate": (("AltitudeAGL", False), ("AltitudeMSL", False), ("Latitude", False), ("Longitude", False)),
    "GeographicFeature": (("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False)),
    "Heading": (("HeadingAngle", False),),
    "HealthObservation": (("ActorReference", False), ("ConfidenceLevel", False), ("UncertaintyInterval", False), ("EntityHealthStatus", True)),
    "InitializationConcept": (("InitializationDataFile", False), ("ObjectDefinitions", False), ("ScenarioSetting", False), ("SystemEntityList", False)),
    "InitializationDataFile": (("IntializationFileType", False), ("Name", False), ("SystemName", False)),
    "IntervalTime": (("Duration", False), ("EndTime", False), ("StartTime", False)),
    "IssuedTime": (("Name", False), ("IsoDateTime", False)),
    "Line": (("Boundary", False), ("Route", False)),
    "Location": (("GeodeticCoordinate", False), ("RelativeLocation", False)),
    "LocationObservation": (("ActorReference", False), ("ConfidenceLevel", False), ("UncertaintyInterval", False), ("DirectionOfMovement", False), ("Location", False), ("Speed", False)),
    "METOCGraphic": (("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False)),
    "MIPRequestContent": (("MIPRequestCategoryCode", False),),
    "ManeuverWarfareTask": (("ActionTemporalRelationship", True), ("Location", True), ("MapGraphicID", True), ("Name", False), ("UUID", False), ("AffectedEntity", True), ("DesiredEffectCode", True), ("Duration", False), ("EndTime", False), ("PerformingEntity", False), ("StartTime", False), ("TaskActionCode", False), ("RuleOfEngagement", True), ("TaskFunctionalRelation", True)),
    "MapGraphic": (("METOCGraphic", False), ("TacticalGraphic", False), ("UnitSymbol", False)),
    "Message": (("C2SIMHeader", False), ("MessageBody", False)),
    "MessageBody": (("C2SIMInitializationBody", False), ("DomainMessageBody", False), ("ObjectInitializationBody", False), ("SystemAcknowledgementBody", False), ("SystemCommandBody", False)),
    "MessageCode": (("AcknowledgeTypeCode", False), ("CommunicativeActTypeCode", False), ("MIPRequestCategoryCode", False), ("SystemCommandTypeCode", False), ("TaskStatusCode", False)),
    "MessageConcept": (("C2SIMHeader", False), ("Message", False), ("MessageBody", False), ("MessageCode", False), ("ReportContent", False), ("RequestContent", False)),
    "MilitaryOrganization": (("Unit", False),),
    "MipWeaponUseROE": (("WeaponROECode", False),),
    "NBC_Event": (("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False), ("Owner", False)),
    "NameObservation": (("ActorReference", False), ("ConfidenceLevel", False), ("UncertaintyInterval", False), ("HostilityStatusCode", False), ("Marking", False), ("Name", False), ("Side", False)),
    "NamedEntityType": (("EntityTypeString", False),),
    "NonMilitaryOrganization": (("CurrentTask", True), ("EntityDescriptor", False), ("Resource", True), ("CurrentState", False), ("Subordinate", True), ("EntityType", True), ("Name", False), ("UUID", False)),
    "ObjectDefinitions": (("AbstractObject", True), ("Action", True), ("Entity", True), ("PlanPhaseReference", True)),
    "ObjectInitializationBody": (("InitializationDataFile", True), ("ObjectDefinitions", False), ("ScenarioSetting", False), ("SystemEntityList", False)),
    "Observation": (("ActivityObservation", False), ("HealthObservation", False), ("LocationObservation", False), ("NameObservation", False), ("ResourceObservation", False), ("SubjectTypeObservation", False)),
    "ObservationReportContent": (("Duration", False), ("TimeOfObservation", False), ("Observation", True)),
    "OnOrderTrigger": (("TaskReference", False),),
    "OperationalStatus": (("OperationalStatusCode", False),),
    "OrderBody": (("FromSender", False), ("ToReceiver", False), ("Entity", True), ("IssuedTime", False), ("OrderID", False), ("RequestingEntity", False), ("Task", True), ("TaskReference", True)),
    "OrganizationCode": (("CountryCode", False), ("EthnicGroupCode", False), ("OrganizationTypeCode", False), ("ReligionCode", False)),
    "Orientation": (("EulerAngles", False), ("Heading", False)),
    "Overlay": (("Name", True), ("UUID", False), ("EntityReference", True)),
    "Person": (("CurrentTask", True), ("EntityDescriptor", False), ("Resource", True), ("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False)),
    "PhysicalConcept": (("EntityHealthStatus", False), ("Location", False), ("Orientation", False), ("SpatialOffset", False), ("TemporalConcept", False)),
    "PhysicalEntity": (("CulturalFeature", False), ("EnvironmentalObject", False), ("GeographicFeature", False), ("MapGraphic", False)),
    "PhysicalState": (("DateTime", False), ("DirectionOfMovement", False), ("EntityHealthStatus", True), ("Location", True), ("Orientation", False), ("Speed", False)),
    "PlanBody": (("FromSender", False), ("ToReceiver", False), ("PlanPhase", True), ("PlanPhaseReference", True), ("ToBeExecutedNow", False)),
    "PlanPhase": (("PlanPhaseCompletionCondition", False), ("PlanPhaseTrigger", False), ("SubPhase", True), ("TaskReference", True)),
    "PlanPhaseTrigger": (("EventTrigger", False), ("OnOrderTrigger", False), ("PriorPhaseCompletionTrigger", False)),
    "Platform": (("Aircraft", False), ("SubsurfaceVessel", False), ("SurfaceVessel", False), ("Vehicle", False)),
    "Point": (("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False), ("Owner", False)),
    "PositionReportContent": (("Duration", False), ("TimeOfObservation", False), ("EntityHealthStatus", True), ("Location", False), ("SubjectEntity", False)),
    "PriorPhaseCompletionTrigger": (("TriggerPhase", False),),
    "Relationship": (("ActionTemporalRelationship", False), ("AllegianceRelationship", False), ("CommandRelation", False), ("ForceSideRelation", False), ("TaskFunctionalRelation", False)),
    "RelativeLocation": (("EntityReference", False), ("SpatialOffset", False)),
    "RelativeTime": (("Name", False), ("DelayTimeAmount", False), ("EventReference", False), ("TimeReferenceCode", False)),
    "ReportBody": (("FromSender", False), ("ToReceiver", False), ("ReportContent", True), ("ReportID", False), ("ReportingEntity", False)),
    "ReportContent": (("ObservationReportContent", False), ("PositionReportContent", False), ("TaskStatus", False)),
    "RequestBody": (("FromSender", False), ("ToReceiver", False), ("RequestContent", True), ("RequestingEntity", False)),
    "RequestContent": (("MIPRequestContent", False), ("TaskRequestContent", False)),
    "Resource": (("EntityType", True), ("Name", False), ("Quantity", False)),
    "ResourceObservation": (("ActorReference", False), ("ConfidenceLevel", False), ("UncertaintyInterval", False), ("Resource", True)),
    "Resources": (("Resource", True),),
    "Route": (("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False), ("Owner", False)),
    "RuleOfEngagement": (("MipWeaponUseROE", False),),
    "ScenarioSetting": (("DateTime", False), ("Version", False)),
    "SendingTime": (("Name", False), ("IsoDateTime", False)),
    "SimulationTime": (("Name", False), ("DelayTimeAmount", False)),
    "SpatialOffset": (("CartesianOffset", False),),
    "StartTime": (("DateTime", False), ("RelativeTime", False), ("SimulationTime", False)),
    "Strength": (("StrengthPercentage", False),),
    "SubPhase": (("PlanPhaseCompletionCondition", False), ("PlanPhaseTrigger", False), ("SubPhase", True), ("TaskReference", True)),
    "SubjectTypeObservation": (("ActorReference", False), ("ConfidenceLevel", False), ("UncertaintyInterval", False), ("EntityType", True)),
    "SubsurfaceVessel": (("CurrentTask", True), ("EntityDescriptor", False), ("Resource", True), ("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False)),
    "SurfaceVessel": (("CurrentTask", True), ("EntityDescriptor", False), ("Resource", True), ("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False)),
    "SystemAcknowledgementBody": (("AcknowledgeTypeCode", False),),
    "SystemCommandBody": (("SystemCommandTypeCode", False),),
    "SystemEntityList": (("ActorReference", True), ("SystemName", False)),
    "TacticalArea": (("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False), ("Owner", False)),
    "TacticalGraphic": (("Line", False), ("NBC_Event", False), ("Point", False), ("TacticalArea", False), ("TaskGraphic", False)),
    "Task": (("ManeuverWarfareTask", False),),
    "TaskFunctionalRelation": (("FunctionalAssociationWithTask", False), ("TaskFunctionalAssociationCode", False)),
    "TaskGraphic": (("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False), ("Owner", False)),
    "TaskRequestContent": (("Task", True),),
    "TaskStatus": (("Duration", False), ("TimeOfObservation", False), ("CurrentTask", False), ("TaskStatusCode", False)),
    "TemporalConcept": (("Duration", False), ("IntervalTime", False), ("TimeInstant", False)),
    "TimeInstant": (("DateTime", False), ("RelativeTime", False), ("SimulationTime", False)),
    "TimeOfObservation": (("DateTime", False), ("RelativeTime", False), ("SimulationTime", False)),
    "Unit": (("CurrentTask", True), ("EntityDescriptor", False), ("Resource", True), ("CurrentState", False), ("Subordinate", True), ("EntityType", True), ("Name", False), ("UUID", False), ("CommandRelation", True), ("EchelonCode", False)),
    "UnitSymbol": (("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False), ("HigherFormation", False), ("OperationalStatus", False), ("ReinforcedReducedType", False), ("SpecialC2HQ", False)),
    "Vehicle": (("CurrentTask", True), ("EntityDescriptor", False), ("Resource", True), ("EntityType", True), ("Name", False), ("UUID", False), ("CurrentState", False), ("Marking", False)),
    "WeaponROECode": (("ActionCode", False), ("ActionTemporalAssociationCode", False), ("AllegianceRelationshipCode", False), ("CommandRelationCode", False), ("DesiredEffectCode", False), ("EchelonCode", False), ("HostilityStatusCode", False), ("OperationalStatusCode", False), ("OrganizationCode", False), ("PlanPhaseCompletionCondition", False), ("ReinforcedReducedType", False), ("SecurityClassificationCode", False), ("TaskFunctionalAssociationCode", False), ("TimeReferenceCode", False), ("WeaponRuleOfEngagementCode", False)),
}

#: The closed vocabularies the adapter reads a value AGAINST (never rewrites). From the same XSD.
ENUMERATIONS: dict[str, tuple[str, ...]] = {
    "OperationalStatusCode": ('FullyOperational', 'MostlyOperational', 'NotOperational', 'PartlyOperational'),
    "TaskStatusCode": ('TASKABRT', 'TASKCMPLT', 'TASKINPRG', 'TASKPEND', 'TASKSTRT'),
    "HostilityStatusCode": ('AFR', 'AHO', 'AIV', 'ANT', 'FAKER', 'FR', 'HO', 'IV', 'JOKER', 'NEUTRL', 'PENDNG', 'SUSPCT', 'UNK'),
    "CommunicativeActTypeCode": ('Accept', 'Agree', 'Confirm', 'Inform', 'Propose', 'Refuse', 'Request'),
    "AllegianceRelationshipCode": ('FriendlyTo', 'HostileTo', 'NeutralTo', 'UnkownAllegianceTo'),
    "TimeReferenceCode": ('IntervalEndTime', 'IntervalStartTime'),
    "ActionTemporalAssociationCode": ('ENDEND', 'ENDENE', 'ENDENL', 'ENDSNE', 'ENDSNL', 'ENDSTR', 'SAEAST', 'SAENDO', 'SASTEA', 'SBEAST', 'SDUREA', 'SDUREB', 'STREND', 'STRENE', 'STRENL', 'STRSNE', 'STRSNL', 'STRSTR'),
    "TaskFunctionalAssociationCode": ('ALT', 'HASPRV', 'HASSEC', 'HSA', 'IMO', 'INRSTO', 'IOT', 'ISAPRQ', 'ISCAUS', 'TPL', 'UAR'),
    "SecurityClassificationCode": ('Confidential', 'Secret', 'TopSecret', 'Unclassified'),
}

#: The three `HostilityStatusCode` values that state a fact this package's `Affiliation` can
#: carry; every other value (assumed, suspect, pending, joker, faker, IV…) is a judgement or a
#: role and reads UNKNOWN with the code preserved beside it (enums.Affiliation's own rule).
HOSTILITY_TO_AFFILIATION = {"FR": "FRIENDLY", "HO": "HOSTILE", "NEUTRL": "NEUTRAL"}

# ----------------------------------------------------------------------------- the parsed twin


def _key_of(tag: str) -> str:
    """ElementTree tag -> twin key: local name inside the C2SIM namespace, Clark form outside it."""
    return tag[len(NS):] if tag.startswith(NS) else tag


def _tag_of(key: str) -> str:
    return key if key.startswith("{") else NS + key


def repeatable(parent: str, child: str) -> bool:
    return any(name == child and many for name, many in CONTENT.get(parent, ()))


def declared_children(parent: str) -> tuple[str, ...]:
    return tuple(name for name, _ in CONTENT.get(parent, ()))


ROOT = "Message"


def twin_of(root: ET.Element) -> dict:
    """The document as its parsed twin: the content of `<Message>`, order as sent. A root that
    is not the C2SIM `Message` is refused here with its namespace named — a document in another
    namespace or version is not read."""
    key = _key_of(root.tag)
    if key != ROOT:
        if key.startswith("{"):
            namespace, local = key[1:].split("}", 1)
            raise ValueError(f"C2SIM root element <{local}> is in namespace {namespace!r}; the pinned "
                             f"profile is {NAMESPACE!r} (C2SIMArtifacts v1.0.1, SISO-STD-019-2020 v1.0) "
                             "and a document in another namespace or version is refused, not read")
        raise ValueError(f"C2SIM root element is <{key}>, not <{ROOT}> (MessageType, schema line 2703)")
    node = _node_of(root, ROOT)
    return node if isinstance(node, dict) else {}


def _node_of(element: ET.Element, key: str) -> Any:
    node: dict[str, Any] = {}
    for name, value in element.attrib.items():
        node["@" + name] = value
    for child in element:
        child_key = _key_of(child.tag)
        value = _node_of(child, child_key)
        if repeatable(key, child_key):
            node.setdefault(child_key, []).append(value)
        elif child_key in node:
            existing = node[child_key]
            node[child_key] = existing + [value] if isinstance(existing, list) else [existing, value]
        else:
            node[child_key] = value
    text = (element.text or "").strip()
    if not node:
        return text
    if text:
        node["#text"] = text
    return node


def element_of(key: str, node: Any) -> ET.Element:
    """The inverse of `_node_of`: one twin node -> one element (subtree)."""
    element = ET.Element(_tag_of(key))
    if not isinstance(node, dict):
        element.text = "" if node is None else str(node)
        return element
    for child_key in _ordered(key, node):
        value = node[child_key]
        if child_key.startswith("@"):
            element.set(child_key[1:], "" if value is None else str(value))
        elif child_key == "#text":
            element.text = str(value)
        elif isinstance(value, list):
            for item in value:
                if item is None:
                    continue
                element.append(element_of(child_key, item))
        else:
            element.append(element_of(child_key, value))
    return element


def _ordered(key: str, node: dict) -> list[str]:
    """Attributes and text first, then the children in `CONTENT` order where the parent is
    known, unknown children after them in insertion order."""
    declared = declared_children(key)
    rank = {name: i for i, name in enumerate(declared)}
    keys = list(node)
    specials = [k for k in keys if k.startswith("@") or k == "#text"]
    known = sorted((k for k in keys if k in rank), key=lambda k: rank[k])
    unknown = [k for k in keys if k not in rank and k not in specials]
    return specials + known + unknown


def serialise(twin: dict) -> bytes:
    """A twin (the Message's content) -> the document's octets, declaration and default
    namespace included, indented for reading."""
    ET.register_namespace("", NAMESPACE)
    ET.register_namespace("xsi", XSI_NAMESPACE)
    element = element_of(ROOT, twin)
    ET.indent(element, space="  ")
    return (b'<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(element, encoding="utf-8", xml_declaration=False) + b"\n")


def strip_unknown(key: str, node: Any) -> Any:
    """The node without anything `unknowns_in` would list: foreign-namespace elements and
    attributes, and C2SIM-namespace children the parent's content model does not name. What
    egress applies so an emitted document stays inside the pinned vocabulary."""
    if not isinstance(node, dict):
        return node
    out: dict = {}
    for child_key, value in node.items():
        if child_key == "#text":
            out[child_key] = value
            continue
        if child_key.startswith("@") or child_key.startswith("{"):
            continue
        if key in CONTENT and child_key not in declared_children(key):
            continue
        if isinstance(value, list):
            out[child_key] = [None if item is None else strip_unknown(child_key, item) for item in value]
        else:
            out[child_key] = strip_unknown(child_key, value)
    return out


@dataclasses.dataclass(frozen=True)
class Unknown:
    """One element or attribute outside the pinned vocabulary, with where it was."""

    namespace: str | None
    name: str
    path: str
    position: int

    def as_dict(self) -> dict:
        return {"namespace": self.namespace, "name": self.name, "path": self.path,
                "position": self.position}


def unknowns_in(twin: dict) -> list[Unknown]:
    """Every element or attribute the pinned schema does not declare at its position: any
    element or attribute outside the C2SIM namespace, and any C2SIM-namespace child the parent's
    content model does not name. Document order; a path is relative to the Message's content."""
    found: list[Unknown] = []

    def walk(key: str, node: Any, path: str) -> None:
        if not isinstance(node, dict):
            return
        for position, (child_key, value) in enumerate(node.items()):
            child_path = f"{path}.{child_key}" if path else child_key
            if child_key == "#text":
                continue
            if child_key.startswith("@"):
                name = child_key[1:]
                namespace = name[1:name.index("}")] if name.startswith("{") else None
                found.append(Unknown(namespace, name.split("}")[-1], child_path, position))
                continue
            if child_key.startswith("{"):
                found.append(Unknown(child_key[1:child_key.index("}")], child_key.split("}")[-1],
                                     child_path, position))
                continue
            if key in CONTENT and child_key not in declared_children(key):
                found.append(Unknown(NAMESPACE, child_key, child_path, position))
                continue
            if isinstance(value, list):
                for index, item in enumerate(value):
                    walk(child_key, item, f"{child_path}[{index}]")
            else:
                walk(child_key, value, child_path)

    walk(ROOT, twin, "")
    return found


# --------------------------------------------------------------------------------------- time

ISO_DATE_TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
ISO_DURATION = re.compile(r"P([0-9]{2})Y([0-9]{2})M([0-9]{2})DT([0-9]{2})H([0-9]{2})M([0-9]{2})S")
UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def parse_iso_date_time(text: Any, where: str) -> _dt.datetime:
    """`IsoDateTimeBaseType`'s pattern, then a real calendar check. Anything else is a malformed
    timestamp and is refused with the path."""
    if not isinstance(text, str) or not ISO_DATE_TIME.fullmatch(text):
        raise ValueError(f"C2SIM {where} is {text!r}, not the schema's IsoDateTime form "
                         "YYYY-MM-DDThh:mm:ssZ (a malformed timestamp is refused, never guessed)")
    try:
        return _dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)
    except ValueError as e:
        raise ValueError(f"C2SIM {where} is {text!r}, which is not a calendar instant: {e}") from e


def render_iso_date_time(instant: _dt.datetime) -> str:
    if instant.tzinfo is None:
        raise ValueError("an instant without a zone cannot be rendered as IsoDateTime")
    return instant.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def duration_seconds(text: Any, where: str) -> int | None:
    """Seconds in an `IsoTimeDuration`, or None when its year or month component is non-zero
    (neither has a fixed length). Refuses anything off the schema's pattern."""
    if not isinstance(text, str) or not ISO_DURATION.fullmatch(text):
        raise ValueError(f"C2SIM {where} is {text!r}, not the schema's IsoTimeDuration form "
                         "PnnYnnMnnDTnnHnnMnnS")
    years, months, days, hours, minutes, seconds = (int(g) for g in ISO_DURATION.fullmatch(text).groups())
    if years or months:
        return None
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def render_duration(seconds: int) -> str:
    if not isinstance(seconds, int) or seconds < 0:
        raise ValueError(f"a duration is a non-negative whole number of seconds, not {seconds!r}")
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days > 99:
        raise ValueError(f"{seconds} seconds is more than the 99 days the schema's pattern can spell")
    return f"P00Y00M{days:02d}DT{hours:02d}H{minutes:02d}M{secs:02d}S"


@dataclasses.dataclass(frozen=True)
class ExerciseClock:
    """The caller's exercise epoch and rate — the ONLY way a SimulationTime becomes an instant.

    `epoch` is the scenario start (`ScenarioSetting/DateTime` of the exercise's initialisation
    is where it comes from; the adapter is stateless, so the exercise client hands it over).
    `rate` is scenario seconds per wall-clock second, recorded and never applied — see the
    module docstring. `basis` says in words where the epoch came from, and every object that
    used the clock carries it.
    """

    epoch: _dt.datetime
    basis: str
    rate: float = 1.0

    def __post_init__(self) -> None:
        epoch = times.parse(self.epoch) if isinstance(self.epoch, str) else self.epoch
        if not isinstance(epoch, _dt.datetime) or epoch.tzinfo is None:
            raise ValueError("ExerciseClock.epoch must be an RFC 3339 text or an aware datetime")
        object.__setattr__(self, "epoch", epoch)
        if not isinstance(self.basis, str) or len(self.basis.strip()) < 8:
            raise ValueError("ExerciseClock.basis must say, in words, where the epoch came from")
        if not isinstance(self.rate, (int, float)) or isinstance(self.rate, bool) or self.rate <= 0:
            raise ValueError("ExerciseClock.rate is scenario seconds per wall-clock second, > 0")

    def as_dict(self) -> dict:
        return {"epoch": times.render(self.epoch), "rate": float(self.rate), "basis": self.basis}


class Contract(BaseModel):
    """Every typed block is closed: a key the contract does not name is a mistake, not data."""
    model_config = ConfigDict(extra="forbid")


class Instant(Contract):
    """A C2SIM `TimeInstant` as stated, plus how (and whether) it resolved to an instant."""
    form: Literal["DateTime", "SimulationTime", "RelativeTime"]
    name: str | None = None
    iso_date_time: str | None = None
    elapsed: str | None = None
    elapsed_seconds: int | None = None
    event_reference: str | None = None
    time_reference_code: str | None = None
    resolved: str | None = None
    resolution: str


def read_instant(node: Any, where: str, clock: ExerciseClock | None) -> Instant:
    """One `TimeInstant` node (`{"DateTime": …}` / `{"SimulationTime": …}` / `{"RelativeTime": …}`)."""
    if not isinstance(node, dict) or len([k for k in node if not k.startswith("@")]) != 1:
        raise ValueError(f"C2SIM {where} must hold exactly one of DateTime, SimulationTime or "
                         f"RelativeTime; found {sorted(node) if isinstance(node, dict) else node!r}")
    form = next(k for k in node if not k.startswith("@"))
    inner = node[form]
    if form == "DateTime":
        return read_date_time(inner, f"{where}.DateTime")
    if form == "SimulationTime":
        if not isinstance(inner, dict) or "DelayTimeAmount" not in inner:
            raise ValueError(f"C2SIM {where}.SimulationTime has no DelayTimeAmount")
        elapsed = _text(inner["DelayTimeAmount"], "IsoTimeDuration", f"{where}.SimulationTime.DelayTimeAmount")
        seconds = duration_seconds(elapsed, f"{where}.SimulationTime.DelayTimeAmount.IsoTimeDuration")
        resolved, resolution = None, ("unresolved: a SimulationTime is scenario seconds since the "
                                      "scenario epoch and this adapter was given no ExerciseClock "
                                      "(C2simAdapter(exercise=ExerciseClock(epoch, basis)))")
        if clock is not None and seconds is not None:
            resolved = times.render(clock.epoch + _dt.timedelta(seconds=seconds))
            resolution = f"epoch+elapsed: {seconds} s after {times.render(clock.epoch)} ({clock.basis})"
        elif clock is not None:
            resolution = ("unresolved: the elapsed duration has a year or month component, which "
                          "has no fixed length in seconds")
        return Instant(form="SimulationTime", name=_optional_text(inner, "Name"), elapsed=elapsed,
                       elapsed_seconds=seconds, resolved=resolved, resolution=resolution)
    if form == "RelativeTime":
        if not isinstance(inner, dict):
            raise ValueError(f"C2SIM {where}.RelativeTime is not an element with children")
        for required in ("DelayTimeAmount", "EventReference", "TimeReferenceCode"):
            if required not in inner:
                raise ValueError(f"C2SIM {where}.RelativeTime has no {required}")
        elapsed = _text(inner["DelayTimeAmount"], "IsoTimeDuration", f"{where}.RelativeTime.DelayTimeAmount")
        seconds = duration_seconds(elapsed, f"{where}.RelativeTime.DelayTimeAmount.IsoTimeDuration")
        code = _scalar(inner["TimeReferenceCode"], f"{where}.RelativeTime.TimeReferenceCode")
        return Instant(form="RelativeTime", name=_optional_text(inner, "Name"), elapsed=elapsed,
                       elapsed_seconds=seconds,
                       event_reference=_uuid(inner["EventReference"], f"{where}.RelativeTime.EventReference"),
                       time_reference_code=code, resolved=None,
                       resolution="unresolved: relative to the start or end of an event this message "
                                  "does not carry; never resolved by the adapter")
    raise ValueError(f"C2SIM {where} holds {form!r}, which is not a TimeInstant form")


def read_date_time(node: Any, where: str) -> Instant:
    """A `DateTimeType` node: `{"IsoDateTime": …}` with an optional `Name`."""
    if not isinstance(node, dict) or "IsoDateTime" not in node:
        raise ValueError(f"C2SIM {where} has no IsoDateTime")
    text = _scalar(node["IsoDateTime"], f"{where}.IsoDateTime")
    instant = parse_iso_date_time(text, f"{where}.IsoDateTime")
    return Instant(form="DateTime", name=_optional_text(node, "Name"), iso_date_time=text,
                   resolved=times.render(instant), resolution="stated")


def instant_node(instant: Instant) -> dict:
    """The `TimeInstant` twin node for a typed `Instant` — the inverse of `read_instant`."""
    if instant.form == "DateTime":
        if not instant.iso_date_time:
            raise ValueError("a DateTime instant needs iso_date_time")
        return {"DateTime": date_time_node(instant)}
    if instant.form == "SimulationTime":
        if not instant.elapsed:
            raise ValueError("a SimulationTime instant needs its elapsed duration")
        inner: dict = {}
        if instant.name is not None:
            inner["Name"] = instant.name
        inner["DelayTimeAmount"] = {"IsoTimeDuration": instant.elapsed}
        return {"SimulationTime": inner}
    if not (instant.elapsed and instant.event_reference and instant.time_reference_code):
        raise ValueError("a RelativeTime instant needs elapsed, event_reference and time_reference_code")
    inner = {}
    if instant.name is not None:
        inner["Name"] = instant.name
    inner.update({"DelayTimeAmount": {"IsoTimeDuration": instant.elapsed},
                  "EventReference": instant.event_reference,
                  "TimeReferenceCode": instant.time_reference_code})
    return {"RelativeTime": inner}


def date_time_node(instant: Instant) -> dict:
    node: dict = {}
    if instant.name is not None:
        node["Name"] = instant.name
    node["IsoDateTime"] = instant.iso_date_time
    return node


# --------------------------------------------------------------------------- reading helpers


def _scalar(value: Any, where: str) -> str:
    """The text of a text-only element. An element with children where text was expected is
    refused, and so is a repeated element where one was expected."""
    if isinstance(value, dict):
        if set(value) <= {"#text"} or all(k.startswith("@") or k == "#text" for k in value):
            return str(value.get("#text", ""))
        raise ValueError(f"C2SIM {where} has child elements where the schema declares text")
    if isinstance(value, list):
        raise ValueError(f"C2SIM {where} appears {len(value)} times where the schema declares one")
    if value is None:
        return ""
    return str(value)


def _text(node: Any, child: str, where: str) -> str:
    if not isinstance(node, dict) or child not in node:
        raise ValueError(f"C2SIM {where} has no {child}")
    return _scalar(node[child], f"{where}.{child}")


def _optional_text(node: Any, child: str) -> str | None:
    if isinstance(node, dict) and child in node:
        return _scalar(node[child], child)
    return None


def _uuid(value: Any, where: str) -> str:
    text = _scalar(value, where)
    if not UUID_PATTERN.fullmatch(text):
        raise ValueError(f"C2SIM {where} is {text!r}, not the schema's UUID form")
    return text


def _number(value: Any, where: str) -> float:
    text = _scalar(value, where)
    try:
        number = float(text)
    except ValueError as e:
        raise ValueError(f"C2SIM {where} is {text!r}, not a number") from e
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"C2SIM {where} is {text!r}; a NaN or an infinity has no place here")
    return number


def as_list(node: dict, child: str) -> list:
    """A repeatable child as a list, `[]` when absent."""
    value = node.get(child)
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# ----------------------------------------------------------------------- the typed blocks


class Header(Contract):
    """`C2SIMHeader`, typed. Every block ingest writes carries one; a FRESH record may leave it
    None and let the adapter's `Envelope` supply the header on egress. `protocol_matches_pin` is the adapter's reading of the two profile
    strings against SISO-STD-019-2020 §8.2; the strings themselves are carried verbatim."""
    message_id: str
    conversation_id: str
    from_sending_system: str
    to_receiving_system: str
    protocol: str
    protocol_version: str
    communicative_act: str
    sending_time: str | None = None
    in_reply_to_message_id: str | None = None
    reply_to_system: str | None = None
    security_classification: str | None = None
    protocol_matches_pin: bool


def read_header(node: Any) -> Header:
    where = "Message.C2SIMHeader"
    if not isinstance(node, dict):
        raise ValueError(f"C2SIM {where} is missing or empty; a message carries a header "
                         "(MessageType, schema line 2693)")
    missing = [name for name in ("CommunicativeActTypeCode", "ConversationID", "FromSendingSystem",
                                 "MessageID", "Protocol", "ProtocolVersion", "ToReceivingSystem")
               if name not in node]
    if missing:
        raise ValueError(f"C2SIM {where} lacks required field(s) {missing} (C2SIMHeaderType's "
                         "sequence declares each [1..1]); refused, nothing is invented")
    sending = None
    if "SendingTime" in node:
        sending = read_date_time(node["SendingTime"], f"{where}.SendingTime").iso_date_time
    protocol = _scalar(node["Protocol"], f"{where}.Protocol")
    version = _scalar(node["ProtocolVersion"], f"{where}.ProtocolVersion")
    return Header(
        message_id=_uuid(node["MessageID"], f"{where}.MessageID"),
        conversation_id=_uuid(node["ConversationID"], f"{where}.ConversationID"),
        from_sending_system=_scalar(node["FromSendingSystem"], f"{where}.FromSendingSystem"),
        to_receiving_system=_scalar(node["ToReceivingSystem"], f"{where}.ToReceivingSystem"),
        protocol=protocol, protocol_version=version,
        communicative_act=_scalar(node["CommunicativeActTypeCode"], f"{where}.CommunicativeActTypeCode"),
        sending_time=sending,
        in_reply_to_message_id=(_uuid(node["InReplyToMessageID"], f"{where}.InReplyToMessageID")
                                if "InReplyToMessageID" in node else None),
        reply_to_system=_optional_text(node, "ReplyToSystem"),
        security_classification=_optional_text(node, "SecurityClassificationCode"),
        protocol_matches_pin=(protocol == PROTOCOL and version == PROTOCOL_VERSION),
    )


def header_node(header: Header) -> dict:
    node: dict = {"CommunicativeActTypeCode": header.communicative_act,
                  "ConversationID": header.conversation_id,
                  "FromSendingSystem": header.from_sending_system}
    if header.in_reply_to_message_id is not None:
        node["InReplyToMessageID"] = header.in_reply_to_message_id
    node["MessageID"] = header.message_id
    node["Protocol"] = header.protocol
    node["ProtocolVersion"] = header.protocol_version
    if header.reply_to_system is not None:
        node["ReplyToSystem"] = header.reply_to_system
    if header.security_classification is not None:
        node["SecurityClassificationCode"] = header.security_classification
    if header.sending_time is not None:
        node["SendingTime"] = {"IsoDateTime": header.sending_time}
    node["ToReceivingSystem"] = header.to_receiving_system
    return node


class Scenario(Contract):
    """`ScenarioSetting`: the scenario's start instant and version string."""
    date_time: Instant
    version: str


class Classification(Contract):
    """One `EntityType` alternative, as source vocabulary: an APP-6 SIDC string, a DIS enumeration
    tuple or a named type. Nothing here becomes a CDM symbol — the CDM's `symbol` is a 20-digit
    MIL-STD-2525D code and an APP-6(C) 15-character string is not one."""
    form: Literal["APP6-SIDC", "DISEntityType", "NamedEntityType"]
    sidc: str | None = None
    dis: dict[str, str] | None = None
    name: str | None = None


class CommandRelation(Contract):
    actor: str
    code: str


class Allegiance(Contract):
    actor: str
    code: str
    in_pinned_enumeration: bool


class ForceSideRelation(Contract):
    other_side: str
    hostility: str
    in_pinned_enumeration: bool


class Organisation(Contract):
    """Every source-stated organisational relationship of an actor, endpoints as C2SIM UUIDs."""
    side: str | None = None
    superior: str | None = None
    subordinates: list[str] = Field(default_factory=list)
    affiliated_with: list[str] = Field(default_factory=list)
    allegiance_relationships: list[Allegiance] = Field(default_factory=list)
    command_relations: list[CommandRelation] = Field(default_factory=list)
    force_side_relations: list[ForceSideRelation] = Field(default_factory=list)
    communications_networks: list[str] = Field(default_factory=list)
    current_tasks: list[str] = Field(default_factory=list)
    echelon: str | None = None


class HealthStatus(Contract):
    """One `EntityHealthStatus`: an operational status code (read against the pinned
    enumeration, carried verbatim either way), a strength percentage, or a resources block
    (kept as the source shaped it)."""
    form: Literal["OperationalStatus", "Strength", "Resources"]
    code: str | None = None
    in_pinned_enumeration: bool | None = None
    strength_percentage: float | None = None
    resources: list[dict] | None = None


class Location(Contract):
    """One `Location`: geodetic (degrees; MSL and AGL heights kept apart, in metres, never
    converted) or relative to another entity (kept as stated)."""
    form: Literal["GeodeticCoordinate", "RelativeLocation"]
    latitude: float | None = None
    longitude: float | None = None
    altitude_msl_m: float | None = None
    altitude_agl_m: float | None = None
    entity_reference: str | None = None
    spatial_offset: dict | None = None


class PhysicalState(Contract):
    """`CurrentState/PhysicalState`: the state's own instant, every location in order, motion,
    and health. `direction_of_movement` and `orientation` keep the raw node when the form is
    Euler angles (the CDM's course is a heading)."""
    date_time: Instant | None = None
    locations: list[Location] = Field(default_factory=list)
    speed_mps: float | None = None
    heading_deg: float | None = None
    direction_of_movement: dict | None = None
    orientation: dict | None = None
    health: list[HealthStatus] = Field(default_factory=list)


class ObjectBlock(Contract):
    """`Entity.attributes["c2sim"]` — or, for a Route map graphic, `PlanObject.route.metadata
    ["c2sim"]` — the `c2sim-object/1` contract: what the message said about one force side, unit,
    platform or route, typed, with the message it came in. `owner` is the Route's; `state` is
    typed for actors (a route's points are the PlanObject's own waypoints)."""
    contract: Literal["c2sim-object/1"] = OBJECT_CONTRACT
    object_class: str
    uuid: str
    name: str | None = None
    names: list[str] = Field(default_factory=list)
    classifications: list[Classification] = Field(default_factory=list)
    marking: str | None = None
    owner: str | None = None
    organisation: Organisation | None = None
    state: PhysicalState | None = None
    affiliation_basis: str | None = None
    message: Header | None = None
    scenario: Scenario | None = None
    exercise_clock: dict | None = None


class TemporalRelationship(Contract):
    code: str
    in_pinned_enumeration: bool
    duration: str | None = None
    duration_seconds: int | None = None
    action: str
    resolved_in_order: bool


class FunctionalRelation(Contract):
    code: str
    in_pinned_enumeration: bool
    task: str
    resolved_in_order: bool


class TaskBlock(Contract):
    """One `ManeuverWarfareTask` of an order. `action_code` is one of the two pinned forms —
    the adapter refuses any other before this block exists."""
    uuid: str
    name: str | None = None
    action_code: str
    performing_entity: str
    affected_entities: list[str] = Field(default_factory=list)
    desired_effects: list[str] = Field(default_factory=list)
    start_time: Instant | None = None
    end_time: Instant | None = None
    duration: str | None = None
    duration_seconds: int | None = None
    locations: list[Location] = Field(default_factory=list)
    map_graphic_ids: list[str] = Field(default_factory=list)
    temporal_relationships: list[TemporalRelationship] = Field(default_factory=list)
    functional_relations: list[FunctionalRelation] = Field(default_factory=list)
    rules_of_engagement: list[dict] = Field(default_factory=list)


class OrderPayload(Contract):
    """`Event.payload["c2sim"]` for an order — the `c2sim-order/1` contract."""
    contract: Literal["c2sim-order/1"] = ORDER_CONTRACT
    order_id: str
    from_sender: str
    to_receiver: str
    issued_time: Instant
    requesting_entity: str | None = None
    tasks: list[TaskBlock]
    task_references: list[str] = Field(default_factory=list)
    message: Header | None = None
    exercise_clock: dict | None = None


class Observation(Contract):
    """One `Observation` of an observation report. `Health`, `Location` and `Name` forms are
    typed; the other three keep their node under `raw`, untyped and whole."""
    form: Literal["ActivityObservation", "HealthObservation", "LocationObservation",
                  "NameObservation", "ResourceObservation", "SubjectTypeObservation"]
    typed: bool
    actor_reference: str | None = None
    confidence_level: float | None = None
    uncertainty_interval: float | None = None
    health: list[HealthStatus] | None = None
    location: Location | None = None
    speed_mps: float | None = None
    heading_deg: float | None = None
    direction_of_movement: dict | None = None
    name: str | None = None
    marking: str | None = None
    hostility_status: str | None = None
    hostility_in_pinned_enumeration: bool | None = None
    side: str | None = None
    raw: dict | None = None


class ReportPayload(Contract):
    """`Event.payload["c2sim"]` for one report content — the `c2sim-report/1` contract. The
    report's identity (`report_id` + `content_index`) is the event's; the subject's is in
    `subject_entity` and in `related_entities`."""
    contract: Literal["c2sim-report/1"] = REPORT_CONTRACT
    kind: Literal["PositionReportContent", "ObservationReportContent", "TaskStatus"]
    report_id: str
    content_index: int
    content_count: int
    reporting_entity: str
    from_sender: str
    to_receiver: str
    subject_entity: str | None = None
    time_of_observation: Instant
    duration: str | None = None
    duration_seconds: int | None = None
    location: Location | None = None
    health: list[HealthStatus] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    current_task: str | None = None
    task_status_code: str | None = None
    task_status_in_pinned_enumeration: bool | None = None
    message: Header | None = None
    exercise_clock: dict | None = None


# ----------------------------------------------------------- reading the shared sub-structures


def read_location(node: Any, where: str) -> Location:
    if not isinstance(node, dict) or len([k for k in node if not k.startswith("@")]) != 1:
        raise ValueError(f"C2SIM {where} must hold exactly one of GeodeticCoordinate or "
                         f"RelativeLocation; found {sorted(node) if isinstance(node, dict) else node!r}")
    form = next(k for k in node if not k.startswith("@"))
    inner = node[form]
    if form == "GeodeticCoordinate":
        if not isinstance(inner, dict):
            raise ValueError(f"C2SIM {where}.GeodeticCoordinate is not an element with children")
        for required in ("Latitude", "Longitude"):
            if required not in inner:
                raise ValueError(f"C2SIM {where}.GeodeticCoordinate has no {required}; a "
                                 "location with no coordinate is refused, never placed at 0, 0")
        latitude = _number(inner["Latitude"], f"{where}.GeodeticCoordinate.Latitude")
        longitude = _number(inner["Longitude"], f"{where}.GeodeticCoordinate.Longitude")
        if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
            raise ValueError(f"C2SIM {where}.GeodeticCoordinate is outside the schema's "
                             f"latitude [-90, 90] / longitude [-180, 180]: {latitude}, {longitude}")
        return Location(
            form="GeodeticCoordinate", latitude=latitude, longitude=longitude,
            altitude_msl_m=(_number(inner["AltitudeMSL"], f"{where}.GeodeticCoordinate.AltitudeMSL")
                            if "AltitudeMSL" in inner else None),
            altitude_agl_m=(_number(inner["AltitudeAGL"], f"{where}.GeodeticCoordinate.AltitudeAGL")
                            if "AltitudeAGL" in inner else None))
    if form == "RelativeLocation":
        if not isinstance(inner, dict) or "EntityReference" not in inner:
            raise ValueError(f"C2SIM {where}.RelativeLocation has no EntityReference")
        offset = inner.get("SpatialOffset")
        return Location(form="RelativeLocation",
                        entity_reference=_uuid(inner["EntityReference"], f"{where}.RelativeLocation.EntityReference"),
                        spatial_offset=offset if isinstance(offset, dict) else None)
    raise ValueError(f"C2SIM {where} holds {form!r}, which is not a Location form")


def location_node(location: Location) -> dict:
    if location.form == "GeodeticCoordinate":
        inner: dict = {}
        if location.altitude_agl_m is not None:
            inner["AltitudeAGL"] = _render_number(location.altitude_agl_m)
        if location.altitude_msl_m is not None:
            inner["AltitudeMSL"] = _render_number(location.altitude_msl_m)
        if location.latitude is None or location.longitude is None:
            raise ValueError("a geodetic location needs latitude and longitude")
        inner["Latitude"] = _render_number(location.latitude)
        inner["Longitude"] = _render_number(location.longitude)
        return {"GeodeticCoordinate": inner}
    if not location.entity_reference:
        raise ValueError("a relative location needs entity_reference")
    inner = {"EntityReference": location.entity_reference}
    if location.spatial_offset is not None:
        inner["SpatialOffset"] = location.spatial_offset
    return {"RelativeLocation": inner}


def _render_number(value: float) -> str:
    """`xs:double` text: an integral value without a trailing `.0`, otherwise Python's shortest
    repr — the same number back."""
    if float(value).is_integer():
        return str(int(value))
    return repr(float(value))


def read_health(node: Any, where: str) -> HealthStatus:
    if not isinstance(node, dict) or len([k for k in node if not k.startswith("@")]) != 1:
        raise ValueError(f"C2SIM {where} must hold exactly one of OperationalStatus, Resources or Strength")
    form = next(k for k in node if not k.startswith("@"))
    inner = node[form]
    if form == "OperationalStatus":
        code = _text(inner, "OperationalStatusCode", f"{where}.OperationalStatus")
        return HealthStatus(form="OperationalStatus", code=code,
                            in_pinned_enumeration=code in ENUMERATIONS["OperationalStatusCode"])
    if form == "Strength":
        return HealthStatus(form="Strength",
                            strength_percentage=_number(_text(inner, "StrengthPercentage", f"{where}.Strength"),
                                                        f"{where}.Strength.StrengthPercentage"))
    if form == "Resources":
        if not isinstance(inner, dict):
            raise ValueError(f"C2SIM {where}.Resources is not an element with children")
        return HealthStatus(form="Resources", resources=[r for r in as_list(inner, "Resource")])
    raise ValueError(f"C2SIM {where} holds {form!r}, which is not an EntityHealthStatus form")


def health_node(status: HealthStatus) -> dict:
    if status.form == "OperationalStatus":
        return {"OperationalStatus": {"OperationalStatusCode": status.code}}
    if status.form == "Strength":
        return {"Strength": {"StrengthPercentage": _render_number(status.strength_percentage)}}
    return {"Resources": {"Resource": list(status.resources or [])}}


def read_classification(node: Any, where: str) -> Classification:
    if not isinstance(node, dict) or len([k for k in node if not k.startswith("@")]) != 1:
        raise ValueError(f"C2SIM {where} must hold exactly one of APP6-SIDC, DISEntityType or NamedEntityType")
    form = next(k for k in node if not k.startswith("@"))
    inner = node[form]
    if form == "APP6-SIDC":
        return Classification(form=form, sidc=_text(inner, "SIDCString", f"{where}.APP6-SIDC"))
    if form == "DISEntityType":
        if not isinstance(inner, dict):
            raise ValueError(f"C2SIM {where}.DISEntityType is not an element with children")
        fields = {}
        for name, _ in CONTENT["DISEntityType"]:
            fields[name] = _text(inner, name, f"{where}.DISEntityType")
        return Classification(form=form, dis=fields)
    if form == "NamedEntityType":
        return Classification(form=form, name=_text(inner, "EntityTypeString", f"{where}.NamedEntityType"))
    raise ValueError(f"C2SIM {where} holds {form!r}, which is not an EntityType form")


def classification_node(classification: Classification) -> dict:
    if classification.form == "APP6-SIDC":
        return {"APP6-SIDC": {"SIDCString": classification.sidc}}
    if classification.form == "DISEntityType":
        return {"DISEntityType": {name: (classification.dis or {})[name]
                                  for name, _ in CONTENT["DISEntityType"]}}
    return {"NamedEntityType": {"EntityTypeString": classification.name}}


def read_direction(node: Any, where: str) -> tuple[float | None, dict | None]:
    """An `OrientationType` node -> (heading in degrees when the form is Heading, the raw node
    when it is EulerAngles)."""
    if isinstance(node, dict) and "Heading" in node and len(node) == 1:
        angle = _number(_text(node["Heading"], "HeadingAngle", f"{where}.Heading"), f"{where}.Heading.HeadingAngle")
        return angle, None
    return None, node if isinstance(node, dict) else {"#text": node}


def read_physical_state(node: Any, where: str, clock: ExerciseClock | None) -> PhysicalState:
    if not isinstance(node, dict) or "PhysicalState" not in node:
        raise ValueError(f"C2SIM {where} has no PhysicalState (EntityStateType's one alternative)")
    state = node["PhysicalState"]
    if not isinstance(state, dict):
        raise ValueError(f"C2SIM {where}.PhysicalState is not an element with children")
    where = f"{where}.PhysicalState"
    locations = as_list(state, "Location")
    heading, direction = (None, None)
    if "DirectionOfMovement" in state:
        heading, direction = read_direction(state["DirectionOfMovement"], f"{where}.DirectionOfMovement")
    orientation = state.get("Orientation")
    return PhysicalState(
        date_time=read_date_time(state["DateTime"], f"{where}.DateTime") if "DateTime" in state else None,
        locations=[read_location(item, f"{where}.Location[{i}]") for i, item in enumerate(locations)],
        speed_mps=_number(state["Speed"], f"{where}.Speed") if "Speed" in state else None,
        heading_deg=heading, direction_of_movement=direction,
        orientation=(orientation if isinstance(orientation, dict) else
                     ({"#text": orientation} if orientation is not None else None)),
        health=[read_health(item, f"{where}.EntityHealthStatus[{i}]")
                for i, item in enumerate(as_list(state, "EntityHealthStatus"))])


def physical_state_node(state: PhysicalState) -> dict:
    inner: dict = {}
    if state.date_time is not None:
        inner["DateTime"] = date_time_node(state.date_time)
    if state.heading_deg is not None:
        inner["DirectionOfMovement"] = {"Heading": {"HeadingAngle": _render_number(state.heading_deg)}}
    elif state.direction_of_movement is not None:
        inner["DirectionOfMovement"] = state.direction_of_movement
    if state.health:
        inner["EntityHealthStatus"] = [health_node(h) for h in state.health]
    inner["Location"] = [location_node(loc) for loc in state.locations]
    if state.orientation is not None:
        inner["Orientation"] = state.orientation
    if state.speed_mps is not None:
        inner["Speed"] = _render_number(state.speed_mps)
    return {"PhysicalState": inner}


def read_organisation(actor: dict, where: str) -> Organisation:
    """The organisational relationships of an actor element (Unit/Platform/Person) from its
    `EntityDescriptor`, `Subordinate`, `CommandRelation`, `CurrentTask` and `EchelonCode`."""
    descriptor = actor.get("EntityDescriptor")
    if not isinstance(descriptor, dict):
        if descriptor is None:
            raise ValueError(f"C2SIM {where} has no EntityDescriptor (ActorEntityGroup declares it [1..1])")
        descriptor = {}
    d_where = f"{where}.EntityDescriptor"
    allegiances = []
    for i, item in enumerate(as_list(descriptor, "AllegianceRelationship")):
        code = _text(item, "AllegianceRelationshipCode", f"{d_where}.AllegianceRelationship[{i}]")
        allegiances.append(Allegiance(
            actor=_uuid(_text(item, "ActorReference", f"{d_where}.AllegianceRelationship[{i}]"),
                        f"{d_where}.AllegianceRelationship[{i}].ActorReference"),
            code=code, in_pinned_enumeration=code in ENUMERATIONS["AllegianceRelationshipCode"]))
    commands = [CommandRelation(actor=_uuid(_text(item, "ActorReference", f"{where}.CommandRelation[{i}]"),
                                            f"{where}.CommandRelation[{i}].ActorReference"),
                                code=_text(item, "CommandRelationCode", f"{where}.CommandRelation[{i}]"))
                for i, item in enumerate(as_list(actor, "CommandRelation"))]
    return Organisation(
        side=_uuid(descriptor["Side"], f"{d_where}.Side") if "Side" in descriptor else None,
        superior=_uuid(descriptor["Superior"], f"{d_where}.Superior") if "Superior" in descriptor else None,
        subordinates=[_uuid(v, f"{where}.Subordinate[{i}]") for i, v in enumerate(as_list(actor, "Subordinate"))],
        affiliated_with=[_uuid(v, f"{d_where}.AffiliatedWith[{i}]")
                         for i, v in enumerate(as_list(descriptor, "AffiliatedWith"))],
        allegiance_relationships=allegiances, command_relations=commands,
        communications_networks=[_uuid(v, f"{d_where}.CommunicationsNetwork[{i}]")
                                 for i, v in enumerate(as_list(descriptor, "CommunicationsNetwork"))],
        current_tasks=[_uuid(v, f"{where}.CurrentTask[{i}]") for i, v in enumerate(as_list(actor, "CurrentTask"))],
        echelon=_optional_text(actor, "EchelonCode"))


def read_observation(node: Any, where: str) -> Observation:
    if not isinstance(node, dict) or len([k for k in node if not k.startswith("@")]) != 1:
        raise ValueError(f"C2SIM {where} must hold exactly one observation form")
    form = next(k for k in node if not k.startswith("@"))
    inner = node[form]
    if form not in ("ActivityObservation", "HealthObservation", "LocationObservation",
                    "NameObservation", "ResourceObservation", "SubjectTypeObservation"):
        raise ValueError(f"C2SIM {where} holds {form!r}, which is not an Observation form")
    if not isinstance(inner, dict):
        raise ValueError(f"C2SIM {where}.{form} is not an element with children")
    common = {
        "actor_reference": _uuid(inner["ActorReference"], f"{where}.{form}.ActorReference") if "ActorReference" in inner else None,
        "confidence_level": _number(inner["ConfidenceLevel"], f"{where}.{form}.ConfidenceLevel") if "ConfidenceLevel" in inner else None,
        "uncertainty_interval": _number(inner["UncertaintyInterval"], f"{where}.{form}.UncertaintyInterval") if "UncertaintyInterval" in inner else None,
    }
    if form == "HealthObservation":
        health = [read_health(item, f"{where}.{form}.EntityHealthStatus[{i}]")
                  for i, item in enumerate(as_list(inner, "EntityHealthStatus"))]
        if not health:
            raise ValueError(f"C2SIM {where}.HealthObservation has no EntityHealthStatus (declared [1..*])")
        return Observation(form=form, typed=True, health=health, **common)
    if form == "LocationObservation":
        if "Location" not in inner:
            raise ValueError(f"C2SIM {where}.LocationObservation has no Location (declared [1..1])")
        heading, direction = (None, None)
        if "DirectionOfMovement" in inner:
            heading, direction = read_direction(inner["DirectionOfMovement"], f"{where}.{form}.DirectionOfMovement")
        return Observation(form=form, typed=True,
                           location=read_location(inner["Location"], f"{where}.{form}.Location"),
                           speed_mps=_number(inner["Speed"], f"{where}.{form}.Speed") if "Speed" in inner else None,
                           heading_deg=heading, direction_of_movement=direction, **common)
    if form == "NameObservation":
        hostility = _optional_text(inner, "HostilityStatusCode")
        return Observation(form=form, typed=True, name=_text(inner, "Name", f"{where}.{form}"),
                           marking=_optional_text(inner, "Marking"), hostility_status=hostility,
                           hostility_in_pinned_enumeration=(hostility in ENUMERATIONS["HostilityStatusCode"]
                                                            if hostility is not None else None),
                           side=_uuid(inner["Side"], f"{where}.{form}.Side") if "Side" in inner else None,
                           **common)
    return Observation(form=form, typed=False, raw={form: inner})


def observation_node(observation: Observation) -> dict:
    if not observation.typed:
        return dict(observation.raw or {})
    inner: dict = {}
    if observation.actor_reference is not None:
        inner["ActorReference"] = observation.actor_reference
    if observation.confidence_level is not None:
        inner["ConfidenceLevel"] = _render_number(observation.confidence_level)
    if observation.uncertainty_interval is not None:
        inner["UncertaintyInterval"] = _render_number(observation.uncertainty_interval)
    if observation.form == "HealthObservation":
        inner["EntityHealthStatus"] = [health_node(h) for h in observation.health or []]
    elif observation.form == "LocationObservation":
        if observation.heading_deg is not None:
            inner["DirectionOfMovement"] = {"Heading": {"HeadingAngle": _render_number(observation.heading_deg)}}
        elif observation.direction_of_movement is not None:
            inner["DirectionOfMovement"] = observation.direction_of_movement
        inner["Location"] = location_node(observation.location)
        if observation.speed_mps is not None:
            inner["Speed"] = _render_number(observation.speed_mps)
    else:
        if observation.hostility_status is not None:
            inner["HostilityStatusCode"] = observation.hostility_status
        if observation.marking is not None:
            inner["Marking"] = observation.marking
        inner["Name"] = observation.name
        if observation.side is not None:
            inner["Side"] = observation.side
    return {observation.form: inner}


# ----------------------------------------------------------------------------- pruning/merging


def prune(node: Any, consumed: set[tuple], path: tuple = ()) -> Any:
    """`node` minus every leaf at a consumed path, with the source's structure — including LIST
    POSITIONS — intact: an emptied list item becomes `None` so a leaf the adapter did not consume
    keeps the index the ledger looks for it at. An emptied dict is dropped from its parent; a
    dict that was empty in the source is kept (it is a leaf the source sent)."""
    if path in consumed:
        return _DROPPED
    if isinstance(node, dict):
        kept: dict = {}
        for key, sub in node.items():
            result = prune(sub, consumed, path + (key,))
            if result is not _DROPPED:
                kept[key] = result
        if not kept and node:
            return _DROPPED
        return kept
    if isinstance(node, list):
        items = []
        for index, sub in enumerate(node):
            result = prune(sub, consumed, path + (index,))
            items.append(None if result is _DROPPED else result)
        if all(item is None for item in items) and node:
            return _DROPPED
        return items
    return node


_DROPPED = object()


def merge(typed: Any, residual: Any) -> Any:
    """The typed node with the residual's leftovers grafted in at their own keys and positions.
    A key both hold keeps the typed value for scalars (the typed side re-rendered what it
    consumed) and merges dicts and lists element by element."""
    if residual is None or residual is _DROPPED:
        return typed
    if typed is None:
        return residual
    if isinstance(typed, dict) and isinstance(residual, dict):
        out = dict(typed)
        for key, value in residual.items():
            out[key] = merge(typed.get(key), value) if key in typed else value
        return out
    if isinstance(typed, list) and isinstance(residual, list):
        out = []
        for index in range(max(len(typed), len(residual))):
            t = typed[index] if index < len(typed) else None
            r = residual[index] if index < len(residual) else None
            out.append(merge(t, r))
        return out
    return typed
