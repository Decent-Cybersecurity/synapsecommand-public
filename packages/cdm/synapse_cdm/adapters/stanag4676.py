"""STANAG 4676 / AEDP-12 Edition B Version 2 — NITS documents in, CDM out, and back. Adapter #7.

It implements the STANAG 4676 row set in FORMAT_COVERAGE.md class by class and attribute by
attribute; that section is this module's specification, `MODEL` below is the same 48 classes and
273 attributes in machine-readable form, and a test asserts that the two agree in both directions
— so an attribute nobody decided about fails the build rather than being quietly absent.

WHAT THE INPUT IS
-----------------
`to_cdm()` takes ONE `NITSRoot` object: the XML instance document, or the already-parsed dict a
fixture twin holds. The standard draws this boundary itself — §2.5.1, "a conformant instantiation
of the model shall contain one and only one NITSRoot object", and §2.1.1.2, "the method by which
STANAG 4676 data are transmitted is out of scope for this standard". So there is no socket here,
no file-server poller, no MIME multipart splitter and no cache of previously transmitted objects.

THE XML ELEMENT NAMES ARE PROVISIONAL, AND THAT IS THE ONE HONEST WAY TO SHIP THIS
----------------------------------------------------------------------------------
The normative XML schema is distributed through NATO national representatives (Ed B §B.5) and
could not be obtained or hashed for this repository, and the standard warns that tag names were
shortened "to as little as two letters" to fight file size. So the reader binds UML attribute
names to element names **provisionally**, through the single table `ELEMENT_NAMES`, and every
divergence the XSD turns out to carry is a data change to that table rather than a code change.
The parsed-dict path is unaffected by any of it: a caller holding a parsed document keyed by UML
attribute name gets identical CDM output either way, which is why the fixtures ship as twins and
why a test asserts the two produce the same objects.

ONE TRACK PER TRACKDATA
-----------------------
`TrackSegment` is not an identity boundary. §2.5.25 defines it as points "adjacent in time" that
exist so a producer can invalidate a group, report a status, or attach different source
information to "a specific portion of the track" — and says a producer may put every point of a
track in one segment if it likes. A thing you may or may not break into pieces at your discretion
is not the thing that has the identity, so `TrackData` is, and every point of every segment
becomes a sample of one `Track`. The segments are parked at `attributes.nits_segments`, each
against the half-open range of sample indices it covers.

Two consequences, both refusals rather than repairs. Points out of time order across segments are
refused, quoting both instants — Legion's rule, because sorting hides a source defect the caller
needs to see. And a `TrackData` whose segments overlap in time is refused quoting the hypothesis
structure: that is the multi-hypothesis producer of Table 2.5.25-1, and interleaving ten
hypotheses into one sample list would be a physically absurd track while selecting the
highest-confidence one would be silent best-hypothesis selection. Neither is a translator's to do.

WHAT A PAYLOAD FIELD MAY NOT DO
-------------------------------
`CollectionInformation.essence` states whether these data came from a real sensor, and it does
NOT set `source.synthetic`, which is a deployment declaration. That is the rule the CAT021 row set
states for I021/040 SIM and the Legion row set for its EXERCISE_* identities; a rule with an
exception whenever the payload field looks close enough is a default. A parked essence that
contradicts the declaration is a logged conflict refusal in either direction — never a silent
flip, because a feed configured real that receives SIMULATED data has been misconfigured or
mis-fed, and both are conditions an operator must be told about.

FAKER IS FRIENDLY HERE, AND TWO SHIPPED ADAPTERS DISAGREE
----------------------------------------------------------
Ed B Table 2.5.34-3 defines `FAKER` as "Friendly track, object or entity acting as exercise
hostile", `JOKER` as the exercise-suspect equivalent, and `KILO` as "Friendly high-value object".
All three state the identity in the definition's first word, so all three yield `FRIENDLY` and the
exercise role is parked at `attributes.exercise_role`. `TRAVELER` and `ZOMBIE` are defined as
*suspect*, which has no CDM member, so they set nothing and gap 2 records the loss.

`TRAVELER` and `ZOMBIE` do not DOWNGRADE a stated identity either, whatever it says. Ed B makes
`identity` and `identityAmplification` two separate attributes with no stated co-occurrence
restriction, so `FRIEND` + `ZOMBIE` is the designated identity field plus an amplifier the
standard permits beside it — and a subordinate field rewriting a primary assertion is the move
`essence` is forbidden from making against `source.synthetic`. Note the asymmetry with `FAKER` is
a principle rather than an inconsistency: an amplification is READ when the CDM has a member for
what it states, and recorded when it does not.

And `FAKER` "overriding" a contradicting identity is not adjudication either, which is the half
of that principle easiest to misread. Its definition IS "Friendly track, object or entity acting
as exercise hostile" — the identity claim is inside the amplification literal, so reading `FAKER`
is reading a stated fact, not weighing it against `identity` and picking a winner. `ZOMBIE`'s
definition asserts *suspicion*, which is exactly the judgement `enums.Affiliation` deliberately
lacks a member for, so there is nothing to read and it only records.

The principle self-terminates. If `Affiliation` ever grows `SUSPECT`, `ZOMBIE` and `TRAVELER`
move from recorded to read by this same rule and nothing else has to change —
`test_the_two_suspect_amplifications_never_yield_friendly` is the tripwire, and it fails the
build the moment that member appears.

`symbology.AFFILIATION_FROM_COT` maps CoT's `j` and `k` to HOSTILE and `legion.AFFILIATION` maps
JOKER and FAKER to HOSTILE. This adapter deliberately diverges, and the divergence is stated in
FORMAT_COVERAGE.md rather than resolved here: those are published behaviours of shipped adapters
with fixtures and golden files behind them, and changing one is a 1.1.0 question with a migration
note, not a side effect of writing a seventh adapter. The argument for this direction is that the
CDM already models exercise context separately (`SourceRef.synthetic`, the 2525D context digit),
so painting a friendly as HOSTILE is a fratricide-adjacent over-claim in exactly the direction
this codebase refuses everywhere else — `symbology`'s own table says "suspect — not HOSTILE;
suspicion is not identification".

POSITION_SOURCE SPLITS, AND THE SPLIT IS WHAT A COMMANDER READS UNDER JAMMING
------------------------------------------------------------------------------
Ed B defines `SensorInformation.modality` as the "category of the sensor according to the type of
signal it can detect", and for `AIS`, `ADS-B` and `BFT` the detected signal IS a GNSS-derived
position the object broadcast about itself. So when the `TrackSource` reference chain resolves
WITHIN this document to one of those, the fix is `GNSS` — a fact the sensor read, and the same
reading `adapters/ais.py` and `adapters/adsb.py` give their own positions. When the reference
dangles into a DATASTREAM file we do not have, or the modality is `MIXED`, `OTHER` or `XXXX`, or
the sensors disagree, it stays `ESTIMATED`. The chain is resolved per SEGMENT, because §2.5.24
scopes a `segmentSource` to a specific portion of the track.

TRANSFORMS IS EMPTY, AND THAT IS A CLAIM
-----------------------------------------
Every source value is present in the output verbatim as well as converted: raw coordinate arrays,
raw velocity arrays, raw `relTime` integers, `relTimeIncrement`, the confidentiality label as the
exact fragment that arrived, and every unmapped element through `lossless.residual`. So the
never-drop rule is satisfied by PRESENCE rather than by a declared exemption, and
`lossless.unrepresented()` runs at full strength with nothing excused.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Sequence

from synapse_cdm import ids, lossless, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    PositionSource,
    Severity,
)
from synapse_cdm.geo import LineString, Point, Polygon
from synapse_cdm.models import CDMBase, Entity, Event, Kinematics, Position, Track, TrackSample
from synapse_cdm.symbology import sidc_from_affiliation

SYSTEM = "NITS"

#: `NITSRoot.nitsVersion` for the edition this adapter implements: "Edition letter and Version
#: number, separated by a period". Edition B Version 2.
NITS_VERSION = "B.2"

#: Versions this adapter refuses by name. Edition A is a different root, a different time model
#: and a different security model — a separate adapter, not a mode.
REFUSED_VERSION_PREFIX = "A."


class NitsError(ValueError):
    """A NITS document this adapter refuses to translate. Every message quotes what it read."""


# ============================================================== the Edition B data model
#
# 48 classes, 273 attributes, transcribed from AEDP-12 Ed. B v2 §2.5, §2.6 and Annex D. This is
# the row set in machine-readable form and `test_the_model_table_matches_the_row_set` checks the
# two against each other in BOTH directions, so neither can drift.
#
#   multiplicity  the standard's own, with "1" where it states none (its CONVENTIONS say so)
#   kind          s str · i int · f float · b bool · F float list · I int list · u UUID
#                 · x verbatim XML fragment · anything else is a class name in this table
#
# The three classes the standard defines with no attributes at all are present and empty on
# purpose: "a placeholder for future additions and does not currently include any attributes"
# is a decision, and a class missing from this table would be indistinguishable from an oversight.

Spec = tuple[str, str]

MODEL: dict[str, dict[str, Spec]] = {
    "NITSRoot": {
        "profile": ("1..*", "s"), "streamUID": ("0..1", "u"), "fileUID": ("0..1", "u"),
        "fileLID": ("0..1", "i"), "lidScopeUID": ("0..1", "u"), "numFiles": ("0..1", "i"),
        "msgCreatedTime": ("1", "s"), "nitsVersion": ("1", "s"),
        "product": ("0..1", "ProductIdentification"),
        "collection": ("0..*", "CollectionInformation"),
        "sensor": ("0..*", "SensorInformation"), "tracker": ("0..*", "TrackerInformation"),
        "message": ("0..*", "TrackMessage"),
    },
    "ProductIdentification": {
        "uid": ("0..1", "u"), "lid": ("0..1", "i"), "id": ("1", "s"), "name": ("1", "s"),
        "shortName": ("0..1", "s"), "effectivity": ("0..1", "s"),
    },
    "CollectionInformation": {
        "uid": ("0..1", "u"), "lid": ("0..1", "i"), "intent": ("1", "s"),
        "essence": ("1", "s"), "targetID": ("0..1", "s"),
    },
    "SensorInformation": {
        "uid": ("0..1", "u"), "lid": ("0..1", "i"), "sensorID": ("0..1", "IDData"),
        "name": ("1", "s"), "description": ("0..1", "s"), "modality": ("1", "s"),
        "url": ("0..1", "s"), "collectionMode": ("0..1", "s"),
        "absTimeUncertainty": ("0..1", "f"), "relTimeUncertainty": ("0..1", "f"),
        "comment": ("0..1", "s"), "esmSensor": ("0..1", "ESMSensor"),
        "imagingSensor": ("0..1", "ImagingSensor"),
        "radarSensor": ("0..1", "RadarSensor4607"),
    },
    "ESMSensor": {},
    "RadarSensor4607": {
        "platformID": ("1", "s"), "missionID": ("1", "i"), "jobID": ("1", "i"),
    },
    "ImagingSensor": {
        "motionImageryCoreID": ("1", "s"), "frameHeight": ("0..1", "i"),
        "frameWidth": ("0..1", "i"), "fpaIndex": ("0..1", "i"), "filter": ("0..*", "F"),
        "phenomenology": ("0..1", "s"), "band": ("0..1", "s"),
    },
    "TrackerInformation": {
        "type": ("1", "s"), "uid": ("0..1", "u"), "lid": ("0..1", "i"),
        "trackerID": ("0..1", "IDData"), "name": ("1", "s"), "description": ("0..1", "s"),
        "version": ("1", "s"), "supplementaryData": ("0..*", "SupplementaryData"),
    },
    "SupplementaryData": {
        "type": ("1", "s"), "name": ("1", "s"), "version": ("1", "s"),
        "description": ("0..1", "s"),
    },
    "TrackMessage": {
        "numDetections": ("0..1", "i"), "numTracks": ("0..1", "i"), "baseTime": ("1", "s"),
        "relTimeIncrement": ("1", "f"),
        "dynSrcInfo": ("0..*", "DynamicSourceInformation"),
        "detection": ("0..*", "Detection"), "track": ("0..*", "TrackData"),
        "processedTrack": ("0..*", "ProcessedTrack"),
        "trackLinkage": ("0..*", "TrackLinkage"), "motionEvent": ("0..*", "MotionEvent"),
    },
    "DynamicSourceInformation": {
        "uid": ("0..1", "u"), "lid": ("0..1", "i"), "relTime": ("0..1", "i"),
        "sensorUID": ("0..1", "u"), "sensorLID": ("0..1", "i"),
        "sensorLocation": ("0..1", "PositionPoints"), "groupID": ("0..1", "s"),
        "numDetections": ("0..1", "i"), "numReportedDetections": ("0..1", "i"),
        "dynCFT": ("0..*", "DynamicCFT"),
        "sourceMI": ("0..1", "MotionImageryInformation"),
        "sourceRadar": ("0..1", "RadarInformation"),
        "sourceESM": ("0..1", "ESMInformation"),
    },
    "DynamicCFT": {
        "uid": ("0..1", "u"), "lid": ("0..1", "i"),
        "cft": ("1", "CoordinateFrameTransformation"),
    },
    "CoordinateFrameTransformation": {
        "from": ("1", "s"), "translation": ("1", "F"), "rotation": ("1", "F"),
    },
    "MotionImageryInformation": {
        "frameBoundingBox": ("0..1", "Polygon"), "frameNumber": ("0..1", "i"),
        "niirs": ("0..1", "f"), "vniirs": ("0..1", "f"), "sea": ("0..1", "f"),
        "tea": ("0..1", "f"), "gsd": ("0..1", "F"), "grd": ("0..1", "F"),
        "useableFOV": ("0..1", "Polygon"), "processedFOV": ("0..1", "Polygon"),
    },
    "RadarInformation": {"revisitIndex": ("1", "i"), "dwellIndex": ("1", "i")},
    "ESMInformation": {},
    "Detection": {
        "uid": ("0..1", "u"), "lid": ("0..1", "i"), "relTime": ("0..1", "i"),
        "centroid": ("0..*", "PositionPoints"), "outline": ("0..*", "Shape"),
        "sensorUID": ("0..1", "u"), "sensorLID": ("0..1", "i"), "dynSrcUID": ("0..1", "u"),
        "dynSrcLID": ("0..1", "i"), "confidence": ("0..1", "Confidence"),
        "source": ("0..1", "TrackSource"), "esm": ("0..1", "ESM"), "im": ("0..1", "Image"),
        "radar": ("0..1", "Radar4607"), "sm": ("0..*", "SensorMeasurement"),
    },
    "ESM": {},
    "Radar4607": {"reportIndex": ("1", "i"), "hrrType": ("1", "i")},
    "Image": {
        "pixelMask": ("0..1", "PixelMask"), "centroidPixel": ("0..1", "I"),
        "color": ("0..1", "I"), "chip": ("0..1", "ImageChip"),
    },
    "ImageChip": {"type": ("1", "s"), "uri": ("0..1", "s"), "image": ("0..1", "s")},
    "SensorMeasurement": {
        "quantity": ("1", "s"), "method": ("1", "s"), "value": ("1", "f"),
        "uncertainty": ("0..1", "f"),
    },
    "TrackData": {
        "uid": ("0..1", "u"), "lid": ("0..1", "i"),
        "trackSource": ("0..1", "TrackSource"), "segment": ("0..*", "TrackSegment"),
        "object": ("0..*", "TrackedObject"),
    },
    "TrackSource": {
        "sensorUID": ("0..*", "u"), "sensorLID": ("0..*", "i"), "trackerUID": ("0..*", "u"),
        "trackerLID": ("0..*", "i"), "collectionUID": ("0..*", "u"),
        "collectionLID": ("0..*", "i"), "productUID": ("0..*", "u"),
        "productLID": ("0..*", "i"),
    },
    "TrackSegment": {
        "uid": ("0..1", "u"), "lid": ("0..1", "i"),
        "segmentSource": ("0..1", "TrackSource"), "confidence": ("0..1", "Confidence"),
        "comment": ("0..1", "s"), "status": ("0..1", "s"),
        "initiationReason": ("0..1", "s"), "terminationReason": ("0..1", "s"),
        "tp": ("0..*", "TrackPoint"),
    },
    "TrackPoint": {
        "uid": ("0..1", "u"), "lid": ("0..1", "i"), "relTime": ("0..1", "i"),
        "dynSrcUID": ("0..1", "u"), "dynSrcLID": ("0..1", "i"),
        "associatedDetection": ("0..1", "b"), "processType": ("0..1", "s"),
        "confidence": ("0..1", "Confidence"), "comment": ("0..1", "s"),
        "outline": ("0..1", "Shape"), "outlineObscured": ("0..1", "Shape"),
        "nearestConfuser": ("0..1", "f"),
        "nearestConfuserConfidence": ("0..1", "Confidence"),
        "sm": ("0..*", "SensorMeasurement"), "dynamics": ("0..*", "Dynamics"),
        "evidence": ("0..*", "Evidence"),
    },
    "Dynamics": {
        "cs": ("1", "s"), "pos": ("1", "F"), "vel": ("0..1", "F"), "acc": ("0..1", "F"),
        "cov": ("0..1", "CovarianceMatrix"), "cftUID": ("0..1", "u"), "cftLID": ("0..1", "i"),
    },
    "Evidence": {
        "type": ("1", "s"), "subtype": ("0..1", "s"), "uid": ("0..1", "u"),
        "lid": ("0..1", "i"), "detectionUID": ("0..*", "u"), "detectionLID": ("0..*", "i"),
        "confidence": ("0..1", "Confidence"),
    },
    "TrackedObject": {
        "uid": ("0..1", "u"), "lid": ("0..1", "i"), "description": ("0..1", "s"),
        "numberOfObjects": ("0..1", "i"), "objectColor": ("0..*", "I"),
        "confidence": ("0..1", "Confidence"), "dims": ("0..1", "F"),
        "priority": ("0..1", "i"), "iffCode": ("0..*", "IFFCode"),
        "objectClass": ("0..*", "ObjectClass"),
        "idSourceInformation": ("0..*", "IDSourceInformation"),
        "id1241": ("0..1", "ID1241"), "exampleDetectionUID": ("0..*", "u"),
        "exampleDetectionLID": ("0..*", "i"),
    },
    "IFFCode": {"value": ("1", "s"), "mode": ("1", "s")},
    "ObjectClass": {
        "table": ("1", "s"), "entity": ("0..1", "s"), "entityType": ("0..1", "s"),
        "entitySubtype": ("0..1", "s"), "sector1Modifier": ("0..1", "s"),
        "sector2Modifier": ("0..1", "s"), "code": ("1", "s"),
    },
    "IDSourceInformation": {
        "idQualityNumber": ("1", "s"), "sourceDeclarationBinary": ("1", "i"),
        "sourceDeclarationExtension": ("1", "i"), "relTimeCreation": ("1", "i"),
        "relTimeExchange": ("1", "i"), "idSourceNumber": ("1", "IDSourceNumber"),
    },
    "IDSourceNumber": {
        "sourceType": ("1", "s"), "sourceSubtype": ("1", "s"),
        "sourceDeviceClass": ("1", "s"),
    },
    "ID1241": {
        "identity": ("0..1", "s"), "identityAmplification": ("0..1", "s"),
        "identitySourceModality": ("0..1", "s"), "environment": ("0..1", "s"),
    },
    "ProcessedTrack": {
        "type": ("1", "s"), "uid": ("0..1", "u"), "lid": ("0..1", "i"),
        "confidence": ("0..1", "Confidence"), "inputUID": ("0..*", "u"),
        "inputLID": ("0..*", "i"), "outputUID": ("0..1", "u"), "outputLID": ("0..1", "i"),
    },
    "TrackLinkage": {
        "type": ("1", "s"), "uid": ("0..1", "u"), "lid": ("0..1", "i"),
        "relTime": ("0..1", "i"), "confidence": ("0..1", "Confidence"),
        "preUID": ("0..*", "u"), "postUID": ("0..*", "u"), "preLID": ("0..*", "i"),
        "postLID": ("0..*", "i"),
    },
    "MotionEvent": {
        "type": ("1", "s"), "uid": ("0..1", "u"), "lid": ("0..1", "i"),
        "trackUID": ("0..*", "u"), "trackLID": ("0..*", "i"), "startRelTime": ("1", "i"),
        "endRelTime": ("0..1", "i"), "confidence": ("0..1", "Confidence"),
        "region": ("0..1", "Shape"), "tripwire": ("0..1", "PositionPoints"),
    },
    # ---- COMMON
    "Shape": {
        "dims": ("1", "i"), "cs": ("1", "s"), "cftUID": ("0..1", "u"),
        "cftLID": ("0..1", "i"),
    },
    "Polygon": {"nRings": ("0..1", "i"), "vertices": ("1", "F")},
    "Ellipsoid": {"center": ("1", "F"), "ellipsoidParameters": ("1", "CovarianceMatrix")},
    "PixelMask": {
        "pixelPolygon": ("0..1", "PixelPolygon"), "pixelRun": ("0..1", "PixelRun"),
    },
    "PixelPolygon": {"nRings": ("0..1", "i"), "integerArray": ("1", "I")},
    "PixelRun": {"rs": ("0..*", "I"), "cs": ("0..*", "I")},
    "IDData": {"stationID": ("1", "s"), "nationality": ("1", "s")},
    "CovarianceMatrix": {"covarianceType": ("1", "s")},
    "Confidence": {
        "type": ("1", "s"), "value": ("1", "i"), "sourceReliability": ("0..1", "i"),
        "valid": ("0..1", "b"),
    },
    "PositionPoints": {
        "dims": ("1", "i"), "cs": ("1", "s"), "points": ("1", "F"),
        "cftUID": ("0..1", "u"), "cftLID": ("0..1", "i"),
    },
    "UUID": {"gidp": ("0..1", "i")},
}

#: `Polygon` and `Ellipsoid` are concrete specializations of the abstract `Shape`, so they carry
#: its four attributes as well as their own. The standard says an abstract type never appears on
#: the wire and that a conformant document names the concrete type with `xsi:type`.
SHAPE_SPECIALIZATIONS = ("Polygon", "Ellipsoid")

#: The classes whose payload is the element's own content rather than a named attribute. Their
#: value lands under this key so the attribute table above stays a table of *attributes*.
CORE_VALUE_KEY = "value"
CORE_VALUE_CLASSES = {"CovarianceMatrix": "F", "UUID": "s"}

#: The STANAG 4774 confidentiality elements. Syntax, not model — Ed B's core model is silent
#: (§2.1.1.6) and the XML binding in Annex B.2 makes the originator label mandatory on the root.
#: Carried as the exact serialised fragment, never parsed into fields.
LABEL_ORIGINATOR = "originatorConfidentialityLabel"
LABEL_ALTERNATIVE = "alternativeConfidentialityLabel"
LABEL_METADATA = "metadataConfidentialityLabel"
LABEL_ELEMENTS = (LABEL_ORIGINATOR, LABEL_ALTERNATIVE, LABEL_METADATA)
LABEL_NAMESPACE = "urn:nato:stanag:4774:confidentialitymetadatalabel:1:0"


# ================================================================= world vocabularies

#: `ID1241.identity` -> the CDM's four members. STANAG 1241 Ed. 5, six literals; gap 2 is the
#: two that have no member. ASSUMED_FRIEND is not FRIENDLY (an assumption is not an
#: identification) and SUSPECT is not HOSTILE (suspicion is not identification either) — both
#: understate, and the original always survives in `attributes.nits_id1241`.
IDENTITY: dict[str, Affiliation] = {
    "FRIEND": Affiliation.FRIENDLY,
    "HOSTILE": Affiliation.HOSTILE,
    "NEUTRAL": Affiliation.NEUTRAL,
    "UNKNOWN": Affiliation.UNKNOWN,
    "ASSUMED_FRIEND": Affiliation.UNKNOWN,
    "SUSPECT": Affiliation.UNKNOWN,
}

#: `ID1241.identityAmplification`. Three literals whose Ed B definition BEGINS with "Friendly",
#: and two whose definition begins with "A suspect".
#:
#: The three friendly ones set the affiliation and override a contradicting `identity`, because
#: the standard states the identity in the definition rather than leaving it open — reading a
#: definition is translation. The two suspect ones state an identity the CDM has no member for,
#: so they set nothing; `identity` governs and gap 2 records the loss.
AMPLIFICATION_FRIENDLY = ("FAKER", "JOKER", "KILO")
AMPLIFICATION_SUSPECT = ("TRAVELER", "ZOMBIE")
#: The two that are exercise ROLES as well as identities. KILO is friendly and is not a role.
AMPLIFICATION_EXERCISE_ROLE = ("FAKER", "JOKER")

#: APP-6(D) table -> `Entity.entity_type`. All fourteen codes accounted for; the four that read
#: UNKNOWN are the ones where the CDM has no member, not the ones nobody thought about.
APP6_TABLE: dict[str, EntityType] = {
    "AIR": EntityType.PLATFORM,
    "AIR_MISSILE": EntityType.PLATFORM,
    "SPACE": EntityType.PLATFORM,
    "LAND_UNIT": EntityType.UNIT,
    "LAND_CIVILIAN_UNIT/ORGANIZATION": EntityType.UNIT,
    "LAND_EQUIPMENT": EntityType.PLATFORM,
    "LAND_INSTALLATION": EntityType.FACILITY,
    "CONTROL_MEASURE": EntityType.OVERLAY_OBJECT,
    # No CDM member for a person: UNIT would claim an organisation and EVACUEE_GROUP a category.
    "DISMOUNTED_INDIVIDUAL": EntityType.UNKNOWN,
    "SEA_SURFACE": EntityType.PLATFORM,
    "SEA_SUBSURFACE": EntityType.PLATFORM,
    "MINE_WARFARE": EntityType.UNKNOWN,      # not a platform, a unit or a facility
    "ACTIVITIES": EntityType.UNKNOWN,        # an activity is not a thing that exists
    "ATMOSPHERIC": EntityType.UNKNOWN,       # weather
}

#: `CollectionEssenceType`. Parked, never mapped — see the module docstring. Listed so the
#: conflict check can tell a real-sensor essence from the other three rather than guessing.
ESSENCE_REAL = "REAL"
ESSENCE_NOT_REAL = ("SIMULATED", "SYNTHETIC", "SURROGATE")

#: `CoordinateSystemType`, all six.
CS_WGS84 = "WGS_84"
CS_ECEF = "ECEF"
CS_ECI = "ECI_J2K"
CS_LOCAL_CARTESIAN = "LOCAL_CARTESIAN"
CS_LOCAL_SPHERICAL = "LOCAL_SPHERICAL"
CS_PIXELS = "PIXELS"

#: The order a `Dynamics` block is preferred in when a `TrackPoint` states several. Systems not
#: in this tuple never produce a `Position`.
CS_PREFERENCE = (CS_WGS84, CS_ECEF, CS_LOCAL_CARTESIAN)

#: The two absolute Cartesian systems `CoordinateFrameTransformation.from` is restricted to. Only
#: one of them can be resolved to the ground without an external, time-varying dependency.
CFT_FROM_RESOLVABLE = (CS_ECEF,)
CFT_FROM_ALLOWED = (CS_ECEF, CS_ECI)

#: `ModalityType` values whose detected signal is a COOPERATIVE SELF-REPORT. Ed B defines
#: modality as the "category of the sensor according to the type of signal it can detect", and
#: for these three the signal detected IS a GNSS-derived position the object broadcast about
#: itself — a fact the sensor read, not an inference this adapter is making. `adapters/ais.py`
#: and `adapters/adsb.py` both map their own positions to GNSS for the same reason.
COOPERATIVE_MODALITIES = ("AIS", "ADS-B", "BFT")

#: The three that name no signal in particular, so they refine nothing.
UNINFORMATIVE_MODALITIES = ("MIXED", "OTHER", "XXXX")

#: `IFFMode`. Only MODE_S carries a value that is an identifier in another format's terms, and
#: only when it parses unambiguously as six hex digits — `IFFCode.value` is a bare String with no
#: stated syntax for any of the seven modes.
IFF_MODE_S = "MODE_S"
IFF_MODE_3 = "MODE3"
#: The two whose reading would be an identification decision belonging to an IFF authority.
IFF_AUTHENTICATED = ("MODE4", "MODE5")
ICAO24_RE = re.compile(r"^[0-9A-Fa-f]{6}$")
#: The key `adsb.py` and `asterix_cat021.py` both derive from, so one airframe seen by three
#: adapters gets one `entity_id` without any of them knowing the others exist.
ICAO24_SYSTEM = "ICAO24"

#: `SourceId.system` values this adapter issues.
UID_SYSTEM = "NITS_UID"
LID_SYSTEM = "NITS_LID"
IC_ID_SYSTEM = "NITS_IC_ID"

#: `TrackStatus` values. Parked; `TERMINATED` does not close `Entity.valid_to`, because four of
#: the six termination reasons say the SENSOR stopped seeing the object.
TRACK_STATUS_TERMINATED = "TERMINATED"


# ==================================================================== the ellipsoid
#
# WGS 84, spelled out rather than imported so the transforms below can be checked against a
# published definition by eye. Ed B names the datum itself — "WGS 84 ECEF coordinates" — so
# unlike Legion the ellipsoid does not have to be inferred, and NIMA TR8350.2 Third Edition is
# in the standard's own reference list.
WGS84_A = 6378137.0
WGS84_INVERSE_FLATTENING = 298.257223563
WGS84_F = 1.0 / WGS84_INVERSE_FLATTENING
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
WGS84_B = WGS84_A * (1.0 - WGS84_F)
WGS84_EP2 = (WGS84_A ** 2 - WGS84_B ** 2) / WGS84_B ** 2

#: Seven decimals is about 11 mm at the equator — finer than the transform's own error and finer
#: than anything a NITS source states. Rounding at all is what keeps a golden file stable across
#: platform float formatting.
COORDINATE_DECIMALS = 7
ALTITUDE_DECIMALS = 3
SPEED_DECIMALS = 6


def ecef_to_geodetic(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Geocentric X/Y/Z metres -> (latitude, longitude, height) on the WGS84 ellipsoid.

    The closed-form Bowring/Ferrari solution: a pure function of its input, so a golden file
    means something and two runs on two machines agree. Written out here rather than imported
    from `adapters/legion.py` — an adapter importing another adapter is a coupling nothing in
    this package has — and `test_the_two_ecef_transforms_agree_bit_for_bit` asserts the two
    produce identical results over a grid spanning both poles, the antimeridian and heights from
    -400 m to 400 km. Agreement is checked rather than assumed.
    """
    longitude = math.atan2(y, x)
    p = math.hypot(x, y)
    if p == 0.0:
        return (90.0 if z >= 0 else -90.0), math.degrees(longitude), abs(z) - WGS84_B
    theta = math.atan2(z * WGS84_A, p * WGS84_B)
    latitude = math.atan2(z + WGS84_EP2 * WGS84_B * math.sin(theta) ** 3,
                          p - WGS84_E2 * WGS84_A * math.cos(theta) ** 3)
    curvature = WGS84_A / math.sqrt(1.0 - WGS84_E2 * math.sin(latitude) ** 2)
    return (math.degrees(latitude), math.degrees(longitude),
            p / math.cos(latitude) - curvature)


def radii_of_curvature(latitude_deg: float) -> tuple[float, float]:
    """(meridional M, prime-vertical N) at a geodetic latitude, on the same named ellipsoid.

    These are what turn a `WGS_84` velocity — stated in DEGREES PER SECOND for latitude and
    longitude — into metres per second. They are closed forms in latitude alone; the height that
    goes with them comes from the position, and its absence is why the conversion has two
    branches rather than one.
    """
    phi = math.radians(latitude_deg)
    w = 1.0 - WGS84_E2 * math.sin(phi) ** 2
    return WGS84_A * (1.0 - WGS84_E2) / w ** 1.5, WGS84_A / math.sqrt(w)


def enu_from_ecef(latitude_deg: float, longitude_deg: float,
                  vx: float, vy: float, vz: float) -> tuple[float, float, float]:
    """An ECEF velocity, rotated into the local east/north/up frame at a geodetic position."""
    phi, lam = math.radians(latitude_deg), math.radians(longitude_deg)
    sin_phi, cos_phi, sin_lam, cos_lam = (math.sin(phi), math.cos(phi),
                                          math.sin(lam), math.cos(lam))
    east = -sin_lam * vx + cos_lam * vy
    north = -sin_phi * cos_lam * vx - sin_phi * sin_lam * vy + cos_phi * vz
    up = cos_phi * cos_lam * vx + cos_phi * sin_lam * vy + sin_phi * vz
    return east, north, up


def scalars_from_enu(east: float, north: float, up: float) -> tuple[float, float, float]:
    """(east, north, up) m/s -> the CDM's three scalars. Course reduced into [0, 360)."""
    speed = math.hypot(east, north)
    course = math.degrees(math.atan2(east, north)) % 360.0
    return (round(speed, SPEED_DECIMALS), round(course, SPEED_DECIMALS),
            round(up, SPEED_DECIMALS))


def _determinant(r: Sequence[float]) -> float:
    return (r[0] * (r[4] * r[8] - r[5] * r[7])
            - r[1] * (r[3] * r[8] - r[5] * r[6])
            + r[2] * (r[3] * r[7] - r[4] * r[6]))


def _inverse_3x3(r: Sequence[float], det: float) -> list[float]:
    """The true inverse, needed when the rotation matrix carries skew or scale.

    §2.5.13 and guide §B.3.3.1.1, under an AEDP-12 Requirement: "In the event the rotation matrix
    contains skew, scale or other components, the true inverse of the rotation matrix must be
    used rather than the transposition."
    """
    c = [
        r[4] * r[8] - r[5] * r[7], r[2] * r[7] - r[1] * r[8], r[1] * r[5] - r[2] * r[4],
        r[5] * r[6] - r[3] * r[8], r[0] * r[8] - r[2] * r[6], r[2] * r[3] - r[0] * r[5],
        r[3] * r[7] - r[4] * r[6], r[1] * r[6] - r[0] * r[7], r[0] * r[4] - r[1] * r[3],
    ]
    return [v / det for v in c]


#: How far |det R| may sit from 1 and still count as a rotation, so the transposition shortcut
#: the standard offers is the one applied. Beyond it the true inverse is used instead.
ROTATION_TOLERANCE = 1e-9


def local_to_absolute(local: Sequence[float], translation: Sequence[float],
                      rotation: Sequence[float]) -> tuple[list[float], str]:
    """Local Cartesian -> the CFT's absolute Cartesian frame. Returns the point and the method.

    `A = R^T L + T` when |det R| == 1, per §2.5.13; the true inverse otherwise. A two-dimensional
    local coordinate sets L3 = 0.0, which is an AEDP-12 Requirement and therefore a STATED input
    rather than an assumed one — the difference that keeps `LOCAL_CARTESIAN` converting where a
    two-dimensional `WGS_84` velocity parks.
    """
    l1, l2 = float(local[0]), float(local[1])
    l3 = float(local[2]) if len(local) > 2 else 0.0
    det = _determinant(rotation)
    if abs(abs(det) - 1.0) <= ROTATION_TOLERANCE:
        m = [rotation[0], rotation[3], rotation[6],
             rotation[1], rotation[4], rotation[7],
             rotation[2], rotation[5], rotation[8]]
        method = "transposed rotation matrix (|det R| = 1)"
    else:
        m = _inverse_3x3(rotation, det)
        method = f"true inverse of the rotation matrix (det R = {det!r}, not a pure rotation)"
    absolute = [m[0] * l1 + m[1] * l2 + m[2] * l3 + float(translation[0]),
                m[3] * l1 + m[4] * l2 + m[5] * l3 + float(translation[1]),
                m[6] * l1 + m[7] * l2 + m[8] * l3 + float(translation[2])]
    return absolute, method


# ======================================================================= reading XML
#
# PROVISIONAL. The normative XSD could not be obtained (Ed B §B.5: DiWEB, through a national
# representative), and the standard says tags were shortened "to as little as two letters". So
# element names bind to UML attribute names through this one table, and every name the XSD turns
# out to differ on is a line here rather than a change to the reader.

ELEMENT_NAMES: dict[str, str] = {}   # UML attribute name -> XML element name, where they differ

#: The reverse, built once. Empty today by construction, and that emptiness is the provisional
#: binding stated as data: nothing is renamed because nothing is known to be renamed.
UML_NAMES = {xml: uml for uml, xml in ELEMENT_NAMES.items()}

_XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _numbers(text: str | None, cast) -> list:
    """A whitespace-separated array. `NaN` survives as a float, because a Polygon's ring
    delimiter IS a NaN and normalising it would join two rings into one."""
    return [cast(token) for token in (text or "").split()]


def _scalar(kind: str, text: str | None) -> Any:
    raw = (text or "").strip()
    if kind == "i":
        return int(raw)
    if kind == "f":
        return float(raw)
    if kind == "b":
        return raw.upper() in ("TRUE", "1")
    if kind == "F":
        # `_float_or_token`, NOT `float`: an all-NaN null point is a Polygon's RING DELIMITER
        # (an AEDP-12 Requirement), so parsing it to a float would join two rings into one.
        return _numbers(raw, _float_or_token)
    if kind == "I":
        return _numbers(raw, int)
    return raw


def _read_element(element: ET.Element, class_name: str) -> Any:
    """One XML element -> the parsed-dict form of `class_name`, driven by `MODEL`."""
    fields = dict(MODEL[class_name])
    if class_name in SHAPE_SPECIALIZATIONS:
        fields.update(MODEL["Shape"])
    out: dict[str, Any] = {}

    core = CORE_VALUE_CLASSES.get(class_name)
    if core is not None and (element.text or "").strip():
        out[CORE_VALUE_KEY] = _scalar(core, element.text)

    for name, value in element.attrib.items():
        attribute = _local(name)
        if attribute in fields:
            out[attribute] = _scalar(fields[attribute][1], value)

    for child in element:
        tag = _local(child.tag)
        if child.tag.startswith(f"{{{LABEL_NAMESPACE}}}") or tag in LABEL_ELEMENTS:
            out.setdefault(tag, _verbatim(child))
            continue
        attribute = UML_NAMES.get(tag, tag)
        spec = fields.get(attribute)
        if spec is None:
            out.setdefault("_unmodelled", {}).setdefault(tag, []).append(_verbatim(child))
            continue
        multiplicity, kind = spec
        if kind == "Shape":
            concrete = _local(child.get(_XSI_TYPE) or "")
            if concrete not in SHAPE_SPECIALIZATIONS:
                raise NitsError(
                    f"<{tag}> is typed Shape, which is abstract and \"will never be found "
                    f"directly in the data stream\" (Ed B CONVENTIONS), and its xsi:type is "
                    f"{child.get(_XSI_TYPE)!r}. A conformant document names the concrete type; "
                    f"guessing between {' and '.join(SHAPE_SPECIALIZATIONS)} from which "
                    "attributes happen to be present would be inferring a type the document was "
                    "required to state"
                )
            value = _read_element(child, concrete)
            value["_type"] = concrete
        elif kind in MODEL:
            value = _read_element(child, kind)
            if kind in SHAPE_SPECIALIZATIONS:
                value["_type"] = kind
        elif kind == "u":
            value = _read_uuid(child)
        else:
            value = _scalar(kind, child.text)
        if multiplicity.endswith("*"):
            out.setdefault(attribute, []).append(value)
        else:
            out[attribute] = value
    return out


def _read_uuid(element: ET.Element) -> Any:
    """A UUID element. A `gidp` makes it an IC Identifier, which is a DIFFERENT identifier."""
    text = (element.text or "").strip()
    gidp = element.get("gidp")
    return {CORE_VALUE_KEY: text, "gidp": int(gidp)} if gidp is not None else text


def _verbatim(element: ET.Element) -> str:
    """An element serialised back to a string, for anything carried and not interpreted."""
    return ET.tostring(element, encoding="unicode").strip()


#: A confidentiality label, matched in the SOURCE TEXT rather than rebuilt from the parse tree.
#:
#: This is not an optimisation. `ET.tostring()` on a parsed element re-renders the namespace
#: prefix — `slab:` comes back as `ns0:` — and re-indents the content, so a label round-tripped
#: through the parser is a DIFFERENT fragment from the one that arrived. Whether it is the same
#: LABEL is not a question a track translator is competent to answer, and the settlement says
#: byte-for-byte. So the bytes are sliced out of the document and never parsed.
_LABEL_RE = {
    name: re.compile(
        rf"<(?:(?P<p{i}>[\w.-]+):)?{name}\b.*?</(?:(?P=p{i}):)?{name}\s*>", re.DOTALL)
    for i, name in enumerate(LABEL_ELEMENTS)
}


def parse_document(payload: bytes | str) -> dict:
    """One NITS XML instance document -> the parsed-dict form the row set is written against."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as e:
        raise NitsError(f"not well-formed XML: {e}") from e
    if _local(root.tag) != "NITSRoot":
        raise NitsError(
            f"root element is <{_local(root.tag)}>, and Ed B §B.1 requires <NITSRoot>. An "
            "Edition A document has <TrackMessage> at the root and is a different adapter — "
            "see the edition settlement in FORMAT_COVERAGE.md"
        )
    document = _read_element(root, "NITSRoot")
    source = payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else payload
    for name, pattern in _LABEL_RE.items():
        found = pattern.search(source)
        if found:
            document[name] = _self_contained(found.group(0), source)
        else:
            document.pop(name, None)
    return document


_XMLNS_RE = re.compile(r'xmlns(?::([\w.-]+))?\s*=\s*"([^"]*)"')
_PREFIX_RE = re.compile(r"</?([\w.-]+):")


def _self_contained(fragment: str, source: str) -> str:
    """A sliced label, with any namespace declaration it inherited put back on it.

    A conformant document may declare `xmlns:slab` once on `<NITSRoot>` and use the prefix
    throughout, so the raw slice is not parseable on its own — and egress has to be able to
    re-emit it. Rather than re-serialising the parse tree, which is what loses the prefix in the
    first place, the inherited declarations are carried onto the fragment. The result is the
    same label, still with the producer's own prefix, and now standalone.
    """
    declared = {m.group(1) for m in _XMLNS_RE.finditer(fragment.split(">", 1)[0])}
    used = {m.group(1) for m in _PREFIX_RE.finditer(fragment)} - declared
    if not used:
        return fragment
    available = {m.group(1): m.group(2) for m in _XMLNS_RE.finditer(source)}
    additions = "".join(f' xmlns:{prefix}="{available[prefix]}"'
                        for prefix in sorted(used) if prefix in available)
    if not additions:
        return fragment
    head, _, rest = fragment.partition(">")
    return f"{head}{additions}>{rest}"


# ====================================================================== time
#
# baseTime + relTime x relTimeIncrement, and nothing to reconstruct: baseTime is absolute and in
# UTC, so unlike CAT021 the injected clock supplies no part of the instant. It supplies
# received_at and msgCreatedTime on egress, and nothing else in this module.

#: An offset-bearing timestamp is converted; a NAIVE one is refused. `times.parse` assumes UTC
#: for a naive value and declares the assumption, which is right for a receipt timestamp and
#: wrong for a time base that scales every relTime in the message.
_OFFSET_RE = re.compile(r"(Z|z|[+-]\d{2}:?\d{2})$")


class TimeBase:
    """One `TrackMessage`'s time base, with the raw values kept for egress to re-emit."""

    __slots__ = ("base_time", "increment", "raw_base_time", "raw_increment", "whole_ms")

    def __init__(self, base_time: _dt.datetime, increment: float,
                 raw_base_time: str, raw_increment: float) -> None:
        self.base_time = base_time
        self.increment = increment
        self.raw_base_time = raw_base_time
        self.raw_increment = raw_increment
        # 1/128 s and 1/29.97 s are the cases the relative time model exists to serve, and
        # neither is a whole number of milliseconds. Where the product is not, the CDM instant
        # is a truncation and the park is the record.
        self.whole_ms = abs(increment * 1000.0 - round(increment * 1000.0)) < 1e-9

    def at(self, rel_time: Any, *, where: str) -> _dt.datetime:
        """Resolve one relTime. An omitted value is ZERO — the standard's rule, not ours."""
        if rel_time is None:
            steps = 0
        elif isinstance(rel_time, bool) or not isinstance(rel_time, (int, float)):
            raise NitsError(
                f"{where}: relTime is {rel_time!r}, and the standard types it a long and says "
                "\"this should be an integer value\". Refusing to coerce"
            )
        elif isinstance(rel_time, float) and not rel_time.is_integer():
            raise NitsError(
                f"{where}: relTime is {rel_time!r}, which is not a whole number of increments"
            )
        else:
            steps = int(rel_time)
        try:
            return self.base_time + _dt.timedelta(seconds=steps * self.increment)
        except (OverflowError, OSError, ValueError) as e:
            raise NitsError(
                f"{where}: relTime {steps} x relTimeIncrement {self.raw_increment} from "
                f"baseTime {self.raw_base_time} is not a representable instant ({e})"
            ) from e


def read_time_base(message: dict, index: int) -> TimeBase:
    """`TrackMessage.baseTime` and `.relTimeIncrement`, with three refusals that quote."""
    raw_base = message.get("baseTime")
    where = f"TrackMessage[{index}]"
    if raw_base is None or not str(raw_base).strip():
        raise NitsError(
            f"{where}: baseTime is absent and its multiplicity is [1]. Every relTime in this "
            "message is an integer with no meaning without it, and the injected clock does not "
            "substitute — writing the receipt instant into a message-wide time base would date "
            "every track point in the file to the moment we happened to read it"
        )
    text = str(raw_base).strip()
    if not _OFFSET_RE.search(text):
        raise NitsError(
            f"{where}: baseTime {text!r} carries no UTC offset. The standard says the value "
            "\"should be reported in Coordinated Universal Time\" — should, not shall — so a "
            "naive value may be local, and assuming UTC would move every point in this message "
            "by whole hours. Refused before it reaches times.parse, whose naive-is-UTC "
            "assumption is right for a receipt timestamp and wrong for a time base"
        )
    raw_increment = message.get("relTimeIncrement")
    if raw_increment is None:
        raise NitsError(f"{where}: relTimeIncrement is absent and its multiplicity is [1]")
    increment = float(raw_increment)
    if not math.isfinite(increment) or increment <= 0.0:
        raise NitsError(
            f"{where}: relTimeIncrement is {raw_increment!r}. It is a scale factor in decimal "
            "seconds; zero collapses every instant in the message onto baseTime, which is a "
            "plausible-looking file of simultaneous track points"
        )
    return TimeBase(times.parse(text), increment, text, raw_increment)


# ============================================================== coordinates
#
# Position is a DERIVED, ONE-WAY VIEW and the source coordinates are the record. Every array is
# re-emitted verbatim beside the value computed from it, which is what keeps TRANSFORMS empty.

#: A `DoubleArray` token that is not a finite number is kept as its literal text rather than as
#: a float. The ring delimiter in a complex Polygon IS `NaN` (an AEDP-12 Requirement), so it has
#: to survive a JSON round trip byte for byte — and `NaN` is not valid JSON. Keeping the token
#: as a string keeps the fixture strictly parseable, keeps the delimiter distinguishable from a
#: coordinate, and keeps the lossless check comparing a stable value.
def _float_or_token(token: str) -> Any:
    try:
        value = float(token)
    except ValueError:
        return token
    return token if not math.isfinite(value) else value


def _is_delimiter(value: Any) -> bool:
    return not isinstance(value, (int, float)) or isinstance(value, bool)


class Sensors:
    """The `SensorInformation` blocks reachable inside one payload, by UID and by LID.

    STANDALONE guarantees at least one sensor block in the document (unless the tracks are
    ground truth), so a reference there resolves. A DATASTREAM reference may point at a block in
    a previously transmitted file, which this adapter does not fetch — that is the dangling
    branch, and it is recorded rather than refused.
    """

    def __init__(self, document: dict) -> None:
        self.by_uid: dict[str, dict] = {}
        self.by_lid: dict[int, dict] = {}
        for sensor in document.get("sensor") or []:
            uid = _uuid_text(sensor.get("uid"))
            if uid:
                self.by_uid[uid] = sensor
            if sensor.get("lid") is not None:
                self.by_lid[int(sensor["lid"])] = sensor

    def referenced_by(self, source: Any) -> tuple[list[dict], list[str]]:
        """(resolved SensorInformation blocks, references that dangle in this payload)."""
        if not isinstance(source, dict):
            return [], []
        resolved, dangling = [], []
        for reference in source.get("sensorUID") or []:
            uid = _uuid_text(reference)
            found = self.by_uid.get(uid)
            resolved.append(found) if found else dangling.append(f"sensorUID {uid}")
        for reference in source.get("sensorLID") or []:
            found = self.by_lid.get(int(reference))
            resolved.append(found) if found else dangling.append(f"sensorLID {reference}")
        return resolved, dangling


def position_source_for(source: Any, sensors: Sensors,
                        profiles: Sequence[str]) -> tuple[PositionSource, str]:
    """`SensorInformation.modality`, where the reference chain resolves, else ESTIMATED.

    Two branches and both are stated, because the difference between them is not a detail: it is
    whether a commander can tell a cooperative self-reported fix from a tracker's estimate under
    jamming. The conservative branch is the wider one on purpose — a dangling reference, a
    modality that names no signal, or a mix of cooperative and non-cooperative sensors all give
    ESTIMATED, which understates.
    """
    profile = "/".join(profiles) or "unstated"
    resolved, dangling = sensors.referenced_by(source)
    if not resolved and not dangling:
        return PositionSource.ESTIMATED, (
            "ESTIMATED: the TrackSource references no sensor, so there is no modality to read. A "
            "NITS track point is a tracker's estimate unless something says otherwise")
    if dangling:
        return PositionSource.ESTIMATED, (
            f"ESTIMATED: {', '.join(dangling)} does not resolve within this NITSRoot object "
            f"(profile {profile}). Under DATASTREAM the SensorInformation may be in a previously "
            "transmitted file, which this adapter does not fetch — so the modality is unknown "
            "here, and unknown means the conservative reading rather than a refusal")
    modalities = [s.get("modality") for s in resolved]
    if any(m in UNINFORMATIVE_MODALITIES for m in modalities):
        return PositionSource.ESTIMATED, (
            f"ESTIMATED: modality {modalities!r} includes a value that names no signal in "
            f"particular (one of {', '.join(UNINFORMATIVE_MODALITIES)}), so it refines nothing")
    if all(m in COOPERATIVE_MODALITIES for m in modalities):
        return PositionSource.GNSS, (
            f"GNSS: TrackSource resolves within this NITSRoot object (profile {profile}) to "
            f"sensor modality {modalities!r}, and Ed B defines modality as the \"category of the "
            "sensor according to the type of signal it can detect\" — for these the detected "
            "signal is a GNSS-derived position the object broadcast about itself. That is a fact "
            "the sensor read, and adapters/ais.py and adapters/adsb.py map their own positions "
            "the same way")
    return PositionSource.ESTIMATED, (
        f"ESTIMATED: modality {modalities!r} is not a cooperative self-report, so the position is "
        "the tracker's estimate. Note the per-frame route through TrackPoint.dynSrcUID -> "
        "DynamicSourceInformation.sensorUID is deliberately NOT read: TrackSource is the "
        "reference the settlement names, and reading two chains that can disagree would need a "
        "precedence rule nobody has written")


class Frames:
    """The `CoordinateFrameTransformation`s reachable inside one payload, by UID and by LID.

    Under the DATASTREAM profile a CFT may live in a previously transmitted file, so a reference
    that does not resolve HERE is an unresolved reference and is recorded as one — not as the
    source saying it does not know.
    """

    def __init__(self) -> None:
        self.by_uid: dict[str, dict] = {}
        self.by_lid: dict[int, dict] = {}
        self.unresolved: list[dict] = []

    def add(self, dyn_cft: dict) -> None:
        cft = dyn_cft.get("cft")
        if not isinstance(cft, dict):
            return
        uid = _uuid_text(dyn_cft.get("uid"))
        if uid:
            self.by_uid[uid] = cft
        if dyn_cft.get("lid") is not None:
            self.by_lid[int(dyn_cft["lid"])] = cft

    def resolve(self, holder: dict, where: str) -> tuple[dict | None, str]:
        uid, lid = _uuid_text(holder.get("cftUID")), holder.get("cftLID")
        if uid is None and lid is None:
            return None, "no coordinate frame transformation referenced"
        found = self.by_uid.get(uid) if uid else self.by_lid.get(int(lid))
        if found is None:
            reference = f"cftUID {uid}" if uid else f"cftLID {lid}"
            self.unresolved.append({"at": where, "reference": reference,
                                    "class": "DynamicCFT"})
            return None, (f"{reference} does not resolve within this NITSRoot object; under the "
                          "DATASTREAM profile it may be in a previously transmitted file, which "
                          "this adapter does not fetch")
        return found, f"resolved {'cftUID ' + uid if uid else 'cftLID ' + str(lid)}"


def _cft_complete(cft: dict) -> tuple[bool, str]:
    """Complete means: `from` present and allowed, three translations, nine rotations."""
    origin = cft.get("from")
    if origin not in CFT_FROM_ALLOWED:
        return False, (f"CFT `from` is {origin!r}; the standard restricts it to "
                       f"{' and '.join(CFT_FROM_ALLOWED)}")
    translation, rotation = cft.get("translation"), cft.get("rotation")
    if not isinstance(translation, list) or len(translation) != 3:
        return False, f"CFT translation has {len(translation or [])} values, needs exactly 3"
    if not isinstance(rotation, list) or len(rotation) != 9:
        return False, f"CFT rotation has {len(rotation or [])} values, needs exactly 9"
    if origin not in CFT_FROM_RESOLVABLE:
        return False, (
            f"CFT `from` is {origin}: reaching the ground needs the Earth rotation angle at the "
            "observation epoch, an IAU precession-nutation model and daily Earth-orientation "
            "parameters — a second standard and a live external dependency"
        )
    if abs(_determinant(rotation)) < 1e-12:
        return False, "CFT rotation matrix is singular and has no inverse"
    return True, "complete"


def resolve_dynamics(block: dict, frames: Frames, where: str,
                     position_source: PositionSource = PositionSource.ESTIMATED) -> dict:
    """One `Dynamics` block -> {position, kinematics, basis, kinematics_basis}.

    Six coordinate systems, three of which never produce a `Position`:

      WGS_84            direct, one transform: the axis order
      ECEF              Bowring/Ferrari on the named constants
      LOCAL_CARTESIAN   only through a complete CFT whose `from` is ECEF
      LOCAL_SPHERICAL   never — the slot labelled azimuthal is the argument of z = r cos phi,
                        so a producer's slot convention is unverifiable from the data
      ECI_J2K           never — needs daily Earth-orientation parameters
      PIXELS            never — needs a sensor model and a terrain surface
    """
    cs = block.get("cs")
    pos = block.get("pos")
    vel = block.get("vel")
    out: dict[str, Any] = {"position": None, "kinematics": None}
    numbers = [v for v in (pos or []) if not _is_delimiter(v)]

    if cs == CS_LOCAL_SPHERICAL:
        out["basis"] = (
            "LOCAL_SPHERICAL: attributes-only. Table 2.5.27-2 orders the array (radial, polar, "
            "azimuthal) and the mandated conversion binds those slots positionally to r, theta, "
            "phi and then puts phi — the slot labelled azimuthal — in the zenith position of "
            "z = r cos phi. A label-driven and an equation-driven producer therefore swap "
            "bearing and elevation, both conformantly, and both decode to a valid point on a "
            "sphere, so nothing in the data distinguishes them. Applying the equations would be "
            "confidently wrong half the time. The CFT could not finish the job either: it "
            "\"cannot be used to directly convert to a non-Cartesian coordinate system\"")
        out["kinematics_basis"] = "not derived: the position it would decompose against is not"
        return out
    if cs in (CS_ECI, CS_PIXELS):
        out["basis"] = (
            f"{cs}: attributes-only. "
            + ("reaching the ground needs the Earth rotation angle at epoch, an IAU "
               "precession-nutation model and daily Earth-orientation parameters"
               if cs == CS_ECI else
               "a pixel maps to the ground only through a sensor model, exterior orientation "
               "and a terrain surface, none of which NITS carries — and the format concedes it "
               "by restricting CoordinateFrameTransformation.from to the two absolute Cartesian "
               "systems"))
        out["kinematics_basis"] = "not derived: the position it would decompose against is not"
        return out

    if cs == CS_WGS84:
        if len(numbers) < 2:
            raise NitsError(f"{where}: WGS_84 pos has {len(numbers)} values, a fix needs two")
        latitude, longitude = float(numbers[0]), float(numbers[1])
        height = float(numbers[2]) if len(numbers) > 2 else None
        out["basis"] = (
            "WGS_84 geodetic, read as (latitude, longitude, ellipsoid height) per "
            "Table 2.5.27-2 — note this is the OPPOSITE axis order from GeoJSON. No datum "
            "conversion. The source array is re-emitted verbatim at attributes.nits_position")
    elif cs == CS_ECEF:
        if len(numbers) < 3:
            raise NitsError(
                f"{where}: ECEF pos has {len(numbers)} values; a geocentric position needs "
                "three, and inferring the third would invent a location")
        latitude, longitude, height = ecef_to_geodetic(*(float(v) for v in numbers[:3]))
        out["basis"] = (
            f"ECEF geocentric metres converted to geodetic on the WGS 84 ellipsoid "
            f"(a={WGS84_A} m, 1/f={WGS84_INVERSE_FLATTENING}) by the closed-form "
            "Bowring/Ferrari solution. Ed B names the datum itself: \"WGS 84 ECEF coordinates\"")
    elif cs == CS_LOCAL_CARTESIAN:
        cft, reference = frames.resolve(block, where)
        if cft is None:
            out["basis"] = f"LOCAL_CARTESIAN: attributes-only — {reference}"
            out["kinematics_basis"] = "not derived: the position it would decompose against is not"
            return out
        complete, why = _cft_complete(cft)
        if not complete:
            out["basis"] = f"LOCAL_CARTESIAN: attributes-only — incomplete CFT: {why}"
            out["kinematics_basis"] = "not derived: the position it would decompose against is not"
            return out
        if len(numbers) < 2:
            raise NitsError(f"{where}: LOCAL_CARTESIAN pos has {len(numbers)} values, needs two")
        absolute, method = local_to_absolute(numbers, cft["translation"], cft["rotation"])
        latitude, longitude, height = ecef_to_geodetic(*absolute)
        out["basis"] = (
            f"LOCAL_CARTESIAN through {reference} to {cft['from']} by the {method}, then "
            f"ECEF to geodetic on the WGS 84 ellipsoid (a={WGS84_A} m, "
            f"1/f={WGS84_INVERSE_FLATTENING}). A two-dimensional local coordinate sets L3 = 0.0, "
            "which is an AEDP-12 Requirement and therefore a stated input")
        if len(numbers) == 2:
            out["basis"] += "; the specified transform may still yield a non-zero third absolute "\
                            "component, so the result is treated as three-dimensional"
    else:
        out["basis"] = f"coordinate system {cs!r} is not one of the six the standard defines"
        out["kinematics_basis"] = "not derived: the position it would decompose against is not"
        return out

    out["position"] = Position(
        lat=round(latitude, COORDINATE_DECIMALS),
        lon=round(longitude, COORDINATE_DECIMALS),
        alt_m=None if height is None else round(height, ALTITUDE_DECIMALS),
        position_source=position_source,
    )
    out["kinematics"], out["kinematics_basis"] = _kinematics(
        cs, vel, numbers, latitude, longitude, height, block, frames, where)
    return out


def _kinematics(cs: str, vel: Any, pos: list, latitude: float, longitude: float,
                height: float | None, block: dict, frames: Frames,
                where: str) -> tuple[Kinematics | None, str]:
    """`Dynamics.vel` -> the CDM's three scalars, or a parked whole with a stated reason.

    WGS_84 SPLITS on the optional height axis, and that is the whole of amendment D. The scale
    factors are the radii of curvature at (phi, h): phi is always given, h is not, and h = 0
    would be a FABRICATED input to the conversion rather than a rounding of a real one.
    """
    if vel is None:
        return None, "the block states no velocity"
    components = [v for v in vel if not _is_delimiter(v)]
    if cs == CS_WGS84:
        if height is None or len(components) < 3:
            return None, (
                "WGS_84 velocity parked whole: the position states no ellipsoid height, so by "
                "the standard's all-or-nothing rule the velocity states no elevation speed "
                "either. Converting degrees per second to metres per second needs the radii of "
                "curvature at (latitude, height), and h = 0 would be a fabricated input to that "
                "conversion rather than a rounded one. The raw array is at attributes.nits_"
                "velocity")
        meridional, prime_vertical = radii_of_curvature(latitude)
        north = math.radians(float(components[0])) * (meridional + height)
        east = math.radians(float(components[1])) * (prime_vertical + height) \
            * math.cos(math.radians(latitude))
        up = float(components[2])
        basis = (
            f"WGS_84 angular rates scaled by the radii of curvature at (latitude={latitude!r}, "
            f"height={height!r}) on the WGS 84 ellipsoid (a={WGS84_A} m, "
            f"1/f={WGS84_INVERSE_FLATTENING}): v_north = dlat/dt * (M + h), "
            "v_east = dlon/dt * (N + h) * cos(lat), both after converting degrees to radians")
    elif cs == CS_ECEF:
        if len(components) < 3:
            return None, f"ECEF velocity has {len(components)} components, needs three"
        east, north, up = enu_from_ecef(latitude, longitude, *(float(v) for v in components[:3]))
        basis = ("ECEF velocity rotated into the local east/north/up frame at the geodetic "
                 "position derived from the same Dynamics block")
    elif cs == CS_LOCAL_CARTESIAN:
        cft, _ = frames.resolve(block, where)
        if cft is None:
            return None, "no complete CFT, so the local velocity has no absolute frame"
        complete, why = _cft_complete(cft)
        if not complete:
            return None, f"incomplete CFT: {why}"
        if len(components) < 2:
            return None, f"LOCAL_CARTESIAN velocity has {len(components)} components, needs two"
        # A velocity is a free vector: the rotation applies and the translation does not.
        rotated, method = local_to_absolute(components, (0.0, 0.0, 0.0), cft["rotation"])
        east, north, up = enu_from_ecef(latitude, longitude, *rotated)
        basis = (f"LOCAL_CARTESIAN velocity rotated to {cft['from']} by the {method} — a "
                 "velocity is a free vector, so the translation does not apply — then into the "
                 "local east/north/up frame at the derived position")
    else:
        return None, f"no conversion defined for a velocity in {cs}"

    speed, course, climb = scalars_from_enu(east, north, up)
    return Kinematics(speed_mps=speed, course_deg=course, climb_mps=climb), basis


# ================================================================ identity
#
# A uid is universally unique "across all data streams from all data providers"; a lid is unique
# only "within a single NITSRoot object", and only sharable across objects whose lidScopeUID
# matches. So a bare lid is NOT an identifier, and promoting one would tell every downstream
# consumer something the standard says is false. That is I021/170's rule applied to a number.

def _uuid_text(value: Any) -> str | None:
    """A UUID attribute -> its text, or the composed IC Identifier when a `gidp` is present."""
    if value is None:
        return None
    if isinstance(value, dict):
        core = value.get(CORE_VALUE_KEY)
        gidp = value.get("gidp")
        if core is None:
            return None
        return f"guide://{gidp}/{core}" if gidp is not None else str(core)
    return str(value)


def _uuid_system(value: Any) -> str:
    return IC_ID_SYSTEM if isinstance(value, dict) and value.get("gidp") is not None \
        else UID_SYSTEM


def key_of(block: dict, lid_scope: str | None) -> tuple[str, str, str] | None:
    """(system, external_id, basis) for one class instance, or None when it has no usable key."""
    uid = _uuid_text(block.get("uid"))
    if uid:
        return _uuid_system(block.get("uid")), uid, "uid"
    lid = block.get("lid")
    if lid is not None and lid_scope:
        return LID_SYSTEM, f"{lid_scope}:{lid}", "lid scoped by lidScopeUID"
    return None


# ================================================================ geometry
#
# Three corrections stand between a NITS Polygon and a GeoJSON one, and getting any of them
# wrong yields a well-formed polygon in the wrong place or with the wrong interior:
# axis order, winding, and explicit closure.

def _tuples(values: Sequence[Any], dims: int) -> list[list[Any]]:
    return [list(values[i:i + dims]) for i in range(0, len(values) - dims + 1, dims)]


def _rings(vertices: Sequence[Any], dims: int) -> list[list[list[Any]]]:
    """Split one flat array into rings on the all-`NaN` null point."""
    rings: list[list[list[Any]]] = [[]]
    for point in _tuples(vertices, dims):
        if all(_is_delimiter(v) for v in point):
            rings.append([])
        else:
            rings[-1].append(point)
    return [ring for ring in rings if ring]


def _signed_area(ring: Sequence[Sequence[float]]) -> float:
    total = 0.0
    for (x1, y1), (x2, y2) in zip(ring, list(ring[1:]) + [ring[0]]):
        total += x1 * y2 - x2 * y1
    return total / 2.0


def geometry_from_shape(shape: dict, frames: Frames, where: str) -> tuple[Any, str]:
    """A `Shape` -> a GeoJSON `Polygon`, or None with the reason it could not be one."""
    if shape.get("_type") != "Polygon":
        return None, (f"{shape.get('_type')} is not rendered as a geometry: an Ellipsoid is an "
                      "uncertainty region whose parameters ARE a covariance matrix, not a "
                      "footprint, and drawing one would put a confidence region on the map as "
                      "though it were an object")
    cs = shape.get("cs")
    lonlat, reason = _to_lonlat_points(shape.get("vertices") or [], int(shape.get("dims") or 2),
                                       cs, shape, frames, where)
    if lonlat is None:
        return None, reason
    rings = lonlat
    if not rings:
        return None, "the polygon has no rings"
    # NITS: clockwise ring = included, counter-clockwise = excluded, viewed from above.
    # RFC 7946: exterior counter-clockwise and FIRST, holes clockwise. So every ring reverses
    # and the included one moves to the front.
    included = [r for r in rings if _signed_area(r) < 0]
    excluded = [r for r in rings if _signed_area(r) >= 0]
    if len(included) != 1:
        return None, (
            f"the polygon has {len(included)} clockwise (included) rings. RFC 7946 admits one "
            "exterior ring per Polygon and geo.py models no MultiPolygon, so a set of disjoint "
            "regions — the standard's own 'set of islands' — is parked whole rather than being "
            "split into geometries the CDM cannot hold together")
    ordered = [included[0]] + excluded
    coordinates = []
    for ring in ordered:
        flipped = list(reversed(ring))
        # "The first point is assumed to also be the last point" (§2.6.2). geo.py requires the
        # closing position explicitly and refuses to repair an open ring, so restating a point
        # the format says is already there is the one case where adding a coordinate is right.
        if flipped[0] != flipped[-1]:
            flipped.append(list(flipped[0]))
        coordinates.append(flipped)
    return Polygon(coordinates=coordinates), (
        f"{cs} polygon: axis order transposed to [lon, lat], every ring reversed because NITS "
        "winds an included ring clockwise while RFC 7946 winds an exterior ring "
        "counter-clockwise, the included ring moved first, and each ring closed explicitly")


def geometry_from_points(points: dict, frames: Frames, where: str) -> tuple[Any, str]:
    """A `PositionPoints` -> a `Point` or a `LineString`. Never closed: §2.6.10 says so."""
    dims = int(points.get("dims") or 2)
    lonlat, reason = _to_lonlat_points(points.get("points") or [], dims, points.get("cs"),
                                       points, frames, where, rings=False)
    if lonlat is None:
        return None, reason
    flat = lonlat[0]
    if len(flat) == 1:
        return Point(coordinates=flat[0]), f"{points.get('cs')} single point"
    return LineString(coordinates=flat), (
        f"{points.get('cs')} vertices in the order the standard says they should be drawn; "
        "unlike a polygon they do not form a closed shape")


def _to_lonlat_points(values: Sequence[Any], dims: int, cs: str | None, holder: dict,
                      frames: Frames, where: str,
                      rings: bool = True) -> tuple[list[list[list[float]]] | None, str]:
    """Vertices in a NITS coordinate system -> [lon, lat] rings, or None with the reason."""
    if cs not in (CS_WGS84, CS_ECEF, CS_LOCAL_CARTESIAN):
        return None, (f"{cs} is attributes-only, so its vertices cannot become a geometry — "
                      "see the coordinate settlement")
    cft = None
    if cs == CS_LOCAL_CARTESIAN:
        cft, reference = frames.resolve(holder, where)
        if cft is None:
            return None, f"LOCAL_CARTESIAN vertices with no resolvable CFT — {reference}"
        complete, why = _cft_complete(cft)
        if not complete:
            return None, f"LOCAL_CARTESIAN vertices with an incomplete CFT: {why}"
    groups = _rings(values, dims) if rings else [_tuples(values, dims)]
    out = []
    for ring in groups:
        converted = []
        for point in ring:
            numbers = [float(v) for v in point]
            if cs == CS_WGS84:
                latitude, longitude = numbers[0], numbers[1]
            elif cs == CS_ECEF:
                if len(numbers) < 3:
                    return None, "an ECEF vertex needs three components"
                latitude, longitude, _ = ecef_to_geodetic(*numbers[:3])
            else:
                absolute, _ = local_to_absolute(numbers, cft["translation"], cft["rotation"])
                latitude, longitude, _ = ecef_to_geodetic(*absolute)
            converted.append([round(longitude, COORDINATE_DECIMALS),
                              round(latitude, COORDINATE_DECIMALS)])
        out.append(converted)
    return out, "converted"


# ================================================================ the adapter


class Stanag4676Adapter(Adapter):
    """One NITSRoot object in, CDM objects out, and one NITSRoot object back."""

    name = "stanag4676"
    version = "1.0.0"
    direction = "bidirectional"
    system = SYSTEM

    #: `fixtures/nits`, not `fixtures/stanag4676`. The adapter is named for the STANDARD, because
    #: STANAG 4676 is a covering document; the directory is named for the PAYLOAD, because a
    #: directory holds bytes. `fixtures/stanag4676` holds only pinned specifications, and pointing
    #: the harness at it used to print "0 passed, 0 failed" and exit 0 — a gate sweep over nine
    #: adapters reporting nine greens with one of them having replayed nothing. Declared here so
    #: the harness resolves it and nobody has to remember.
    fixture_dir = "nits"

    #: Empty, and that is a claim. Every source value is present verbatim as well as converted,
    #: so the never-drop rule is satisfied by PRESENCE and `lossless.unrepresented()` runs at
    #: full strength with nothing excused. A declared transform is a hole with a reason attached.
    TRANSFORMS: dict[str, str] = {}

    def __init__(self, clock: times.Clock | None = None, *, synthetic: bool = True,
                 confidentiality_label: str | None = None) -> None:
        """`confidentiality_label` is a DEPLOYMENT DECLARATION, in `source.synthetic`'s category.

        It is the second of the three egress label paths and the only one that is not read from
        a source: a CDM-native track — from AIS, ADS-B, CAT021, Legion or CoT — has no parked
        4774 label, and Ed B Annex B.2 makes one mandatory on the root element. Supplying it here
        is explicit and logged; defaulting it would be inventing a marking nobody applied.
        """
        super().__init__(clock, synthetic=synthetic)
        self._label = confidentiality_label

    # ------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        document = parse_document(raw) if isinstance(raw, (bytes, bytearray, str)) else raw
        if not isinstance(document, dict):
            raise NitsError(f"expected a NITSRoot document, got {type(document).__name__}")
        return self._translate(document)

    def _translate(self, document: dict) -> list[CDMBase]:
        version = str(document.get("nitsVersion") or "")
        if version.startswith(REFUSED_VERSION_PREFIX):
            raise NitsError(
                f"nitsVersion is {version!r}. Edition A is a different root (TrackMessage rather "
                "than NITSRoot), a different time model (absolute per item rather than "
                "baseTime + relTime) and a different security model (an inline Security class "
                "rather than STANAG 4774), and Ed B §2.1.1.1 says the two are incompatible and "
                "that the model was re-architected \"from scratch\". A separate adapter, not a "
                "mode — a best-effort decode would produce a message full of points at the epoch"
            )

        lid_scope = _uuid_text(document.get("lidScopeUID"))
        profiles = document.get("profile") or []
        if isinstance(profiles, str):
            profiles = [profiles]
        label = self._read_label(document)
        essence_basis = self._check_essence(document)

        sensors = Sensors(document)
        frames = Frames()
        for message in document.get("message") or []:
            for dyn in message.get("dynSrcInfo") or []:
                for dyn_cft in dyn.get("dynCFT") or []:
                    frames.add(dyn_cft)

        root_context = {k: v for k, v in document.items() if k != "message"}
        received = self.now()
        objects: list[CDMBase] = []
        for index, message in enumerate(document.get("message") or []):
            base = read_time_base(message, index)
            message_context = {k: v for k, v in message.items()
                               if k not in ("track", "detection", "processedTrack",
                                            "trackLinkage", "motionEvent")}
            shared = {
                "root": root_context, "message": message_context, "message_index": index,
                "base": base, "frames": frames, "sensors": sensors, "lid_scope": lid_scope,
                "profiles": list(profiles), "label": label, "essence_basis": essence_basis,
                "received": received,
            }
            for track_data in message.get("track") or []:
                objects += self._from_track_data(track_data, shared)
            for detection in message.get("detection") or []:
                objects.append(self._from_detection(detection, shared))
            for processed in message.get("processedTrack") or []:
                objects.append(self._from_analysis(processed, shared, "processedTrack",
                                                   "nits_processed_track", None))
            for linkage in message.get("trackLinkage") or []:
                objects.append(self._from_analysis(linkage, shared, "trackLinkage",
                                                   "nits_track_linkage",
                                                   linkage.get("relTime")))
            for event in message.get("motionEvent") or []:
                objects.append(self._from_motion_event(event, shared))
        return objects

    # ------------------------------------------------------- document-level reading

    def _read_label(self, document: dict) -> dict[str, str]:
        """The 4774 elements, verbatim. Carried, never parsed into fields."""
        return {name: document[name] for name in LABEL_ELEMENTS if document.get(name)}

    def _check_essence(self, document: dict) -> str:
        """`CollectionEssenceType` against the deployment declaration. A conflict is a refusal.

        Symmetric on purpose. A feed declared real that receives SIMULATED data has been
        misconfigured or mis-fed; a feed declared synthetic that receives REAL data is a replay
        of genuine data through a synthetic pipeline. Both are configuration questions an
        operator must be told about, and a silent flip in either direction hides one.
        """
        essences = [c.get("essence") for c in (document.get("collection") or [])
                    if isinstance(c, dict) and c.get("essence")]
        if not essences:
            return ("the document states no CollectionInformation, so no essence to check; "
                    f"source.synthetic is the deployment declaration ({self._synthetic})")
        for essence in essences:
            real = essence == ESSENCE_REAL
            if real and self._synthetic:
                raise NitsError(
                    f"CollectionInformation.essence is {essence!r} — derived from real sensor "
                    "data — and this deployment declares source.synthetic=true. essence is a "
                    "payload field and synthetic is a deployment declaration, so the adapter "
                    "will not flip one to match the other in either direction; the conflict is "
                    "reported instead"
                )
            if not real and not self._synthetic:
                raise NitsError(
                    f"CollectionInformation.essence is {essence!r} — not derived from real "
                    "sensor data — and this deployment declares source.synthetic=false. A "
                    "payload field may not rewrite a deployment declaration, so the conflict is "
                    "reported rather than resolved"
                )
        return (f"essence {essences!r} parked and checked against the deployment declaration "
                f"source.synthetic={self._synthetic}; essence never sets it")

    # ------------------------------------------------------------- TrackData

    def _from_track_data(self, track_data: dict, shared: dict) -> list[CDMBase]:
        base: TimeBase = shared["base"]
        frames: Frames = shared["frames"]
        lid_scope = shared["lid_scope"]
        where = f"TrackData in TrackMessage[{shared['message_index']}]"

        objects_stated = track_data.get("object") or []
        entity_key = None
        for stated in objects_stated:
            entity_key = key_of(stated, lid_scope)
            if entity_key:
                break
        entity_basis = "TrackedObject key"
        if entity_key is None:
            entity_key = key_of(track_data, lid_scope)
            entity_basis = ("TrackData key — weaker, because a track is a hypothesis about an "
                            "object, so two tracks of one truck yield two entities and resolving "
                            "the stitch is the fusion this adapter declines")
        if entity_key is None:
            raise NitsError(
                f"{where}: neither the TrackData nor any TrackedObject carries a uid, or a lid "
                "with a lidScopeUID to scope it. A bare lid is unique inside one NITSRoot object "
                "and nowhere else, so keying on it would collide with every other producer's "
                "track 7 — there is no stable identity to derive from"
            )
        system, external_id, key_basis = entity_key
        entity_id = ids.derive(system, external_id, kind="entity")
        # The TRACK's identity is the TrackData's own, and falls back to the object's only when
        # the TrackData carries no key. A segment never contributes: amendment A.
        track_key = key_of(track_data, lid_scope) or entity_key
        track_id = ids.derive(track_key[0], track_key[1], kind="track")

        samples, segments, retractions, unpositioned = self._samples(
            track_data, shared, entity_id)

        affiliation, affiliation_basis, exercise_role = self._affiliation(objects_stated)
        entity_type, type_basis = self._entity_type(objects_stated)
        source_ids = self._source_ids(track_data, objects_stated, lid_scope)

        state = samples[-1] if samples else None
        attributes: dict[str, Any] = {
            "nits_root": shared["root"],
            "nits_message": shared["message"],
            "nits_message_index": shared["message_index"],
            "nits_track": track_data,
            "nits_segments": segments,
            # baseTime, relTimeIncrement and every relTime as written. relTimeIncrement is a
            # double in decimal seconds, so 1/128 s or 1/29.97 s — the cases the relative time
            # model exists to serve — are not whole milliseconds, and a CDM Timestamp renders
            # three decimal places. The integers are the record; egress re-emits from here.
            "nits_times": {
                "baseTime": base.raw_base_time,
                "relTimeIncrement": base.raw_increment,
                "whole_milliseconds": base.whole_ms,
                "relTime": [p.get("relTime") for s in (track_data.get("segment") or [])
                            for p in (s.get("tp") or [])],
            },
            "nits_profiles": shared["profiles"],
            "profile_basis": self._profile_basis(shared["profiles"], frames),
            "synthetic_basis": shared["essence_basis"],
            "identity_basis": f"{key_basis}; entity_id from the {entity_basis}",
            "affiliation_basis": affiliation_basis,
            "entity_type_basis": type_basis,
            "symbol_basis": ("derived from the affiliation via symbology.sidc_from_affiliation. "
                             "An APP-6 code, where one is stated, is parked at attributes.app6 "
                             "and never composed into a SIDC: an APP-6 entity code supplies one "
                             "of the eight things a 2525D SIDC encodes and composing one would "
                             "mean inventing six"),
            "track_quality_basis": (
                "None. Edition B states no track-level quality: TrackData has five attributes "
                "and none is a confidence. TrackSegment.confidence governs a PORTION of a track, "
                "so filling track_quality from one would mean picking a segment or aggregating "
                "across them, and mapping it only when there happens to be one segment would "
                "make a canonical field depend on how a producer chunked its output"),
            "valid_to_basis": (
                "None. Four of the six TrackTerminationReason literals — SENSOR_OFF, EXITED_FOV, "
                "LOST, OBSCURED — say the SENSOR stopped seeing the object, not that the object "
                "ceased to exist. A truck that drives under a bridge is still a truck"),
            "consolidation_basis": (
                "§2.1.1.2.3 requires a CONSUMER to interpret an object as the consolidation of "
                "every instance sharing its ID across all in-scope data streams, ordered by "
                "NITSRoot.msgCreatedTime. This is a translation of ONE document: the material to "
                "consolidate is carried in full and the consolidation is not performed"),
            "integrity_basis": (
                "NITS carries no checksum at any level. This document passed structural checks "
                "and nothing more"),
        }
        if exercise_role:
            attributes["exercise_role"] = exercise_role
        if shared["label"]:
            attributes["confidentiality_label"] = shared["label"]
            attributes["confidentiality_label_basis"] = "round_tripped: read from the source document"
        app6 = [o.get("objectClass") for o in objects_stated if o.get("objectClass")]
        if app6:
            attributes["app6"] = app6
        attributes["tracked_object_instances"] = len(objects_stated)
        if len(objects_stated) > 1:
            attributes["tracked_object_group_basis"] = (
                "several TrackedObject instances: \"the data consumer shall interpret the track "
                "data as applying to the set of multiple objects as a group\", and Track."
                "entity_id is singular, so the group is one Entity and every instance is parked")
        if frames.unresolved:
            attributes["unresolved_references"] = frames.unresolved
        if unpositioned:
            # NOT silently skipped: a Track whose sample count is below the segment's point
            # count is a track with holes in it, and a consumer has to be able to see that.
            attributes["nits_unpositioned_points"] = unpositioned
        attributes["position_basis"] = (
            state["basis"] if state else
            "; ".join(dict.fromkeys(p["basis"] for p in unpositioned))
            or "this TrackData states no track point")
        attributes["kinematics_basis"] = (
            state["kinematics_basis"] if state else
            "no positioned track point, so no local horizon to decompose a velocity against")
        if samples:
            attributes["nits_position"] = [s["raw"] for s in samples]
            # The state's own segment, not the first: position and kinematics come from the
            # last positioned point, so the basis has to be that point's segment's.
            attributes["position_source_basis"] = next(
                (s["position_source_basis"] for s in reversed(segments)
                 if s["sample_range"][0] <= len(samples) - 1 < s["sample_range"][1]),
                "no positioned sample")
            valid_from = state["observed_at"]
            valid_from_basis = (
                f"the last positioned TrackPoint of this TrackData (sample {len(samples) - 1}). "
                "Position and kinematics come from the SAME point: taking them from different "
                "points would put two instants into one Entity with nothing recording the "
                "offset, which is CAT021's gap 13 manufactured here rather than inherited")
            attributes["nits_track_first_instant"] = times.render(samples[0]["observed_at"])
        else:
            valid_from = base.base_time
            valid_from_basis = ("TrackMessage.baseTime: this TrackData yields no positioned "
                                "track point, so there is no sample instant to use")
        attributes["valid_from_basis"] = valid_from_basis

        entity = Entity(
            source=self.source_ref(), source_ids=source_ids, entity_id=entity_id,
            entity_type=entity_type, affiliation=affiliation,
            symbol=sidc_from_affiliation(affiliation, synthetic=self._synthetic),
            position=state["position"] if state else None,
            kinematics=state["kinematics"] if state else None,
            attributes=attributes, valid_from=valid_from, valid_to=None,
            confidence=self._confidence(objects_stated),
        )
        out: list[CDMBase] = [entity]
        if samples:
            out.append(Track(
                source=self.source_ref(), source_ids=source_ids,
                track_id=track_id,
                entity_id=entity_id,
                samples=[TrackSample(position=s["position"], observed_at=s["observed_at"])
                         for s in samples],
                track_quality=None,
            ))
        out += [self._retraction_event(segment, shared, entity_id) for segment in retractions]
        return out

    # ------------------------------------------------------------- samples

    def _samples(self, track_data: dict, shared: dict,
                 entity_id: Any) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
        """Every point of every segment, in document order, with the two refusals A requires."""
        base: TimeBase = shared["base"]
        frames: Frames = shared["frames"]
        lid_scope = shared["lid_scope"]
        samples: list[dict] = []
        segments: list[dict] = []
        retractions: list[dict] = []
        unpositioned: list[dict] = []

        # BOTH conditions, independently, and every violation of either is quoted in one
        # refusal. First-match-wins would name whichever happened to be checked first — and a
        # refusal that names the wrong cause is a guess wearing a refusal's clothes.
        violations = self._overlaps(self._spans(track_data, base))

        for order, segment in enumerate(track_data.get("segment") or []):
            where = f"TrackSegment[{order}]"
            points = segment.get("tp") or []
            start = len(samples)
            # §2.5.24: a TrackSource inside a segment overrides the track's for that portion of
            # the track and no more, so the sensor chain is resolved per segment.
            source, source_basis = position_source_for(
                segment.get("segmentSource") or track_data.get("trackSource"),
                shared["sensors"], shared["profiles"])
            for position_in_segment, point in enumerate(points):
                instant = base.at(point.get("relTime"),
                                  where=f"{where}.tp[{position_in_segment}]")
                resolved = self._point_position(point, frames,
                                                f"{where}.tp[{position_in_segment}]",
                                                source)
                if resolved["position"] is None:
                    unpositioned.append({
                        "segment": order, "point": position_in_segment,
                        "observed_at": times.render(instant),
                        "basis": resolved["basis"], "blocks": point.get("dynamics") or []})
                    continue
                if samples and instant < samples[-1]["observed_at"]:
                    violations.append(
                        f"OUT OF ORDER: {where}.tp[{position_in_segment}] resolves to "
                        f"{times.render(instant)}, which precedes "
                        f"{times.render(samples[-1]['observed_at'])} from the preceding point. "
                        "Points are emitted in document order and a track that runs backwards is "
                        "refused rather than sorted: sorting would hide a source defect the "
                        "caller needs to see")
                samples.append({**resolved, "observed_at": instant})
            span = {
                "index": order, "sample_range": [start, len(samples)],
                "point_count": len(points),
                "uid": _uuid_text(segment.get("uid")), "lid": segment.get("lid"),
                "status": segment.get("status"),
                "initiationReason": segment.get("initiationReason"),
                "terminationReason": segment.get("terminationReason"),
                "confidence": segment.get("confidence"),
                "comment": segment.get("comment"),
                "source": segment.get("segmentSource"),
                "position_source": source.value,
                "position_source_basis": source_basis,
            }
            segments.append(span)
            if not points and segment.get("confidence") is not None:
                retractions.append(segment)

        if violations:
            raise NitsError(
                f"this TrackData violates {len(violations)} track-ordering rule(s), and every "
                "one of them is quoted, because a refusal that names only the cause it happened "
                "to check first is a guess about which one the producer meant:\n  - "
                + "\n  - ".join(violations))
        return samples, segments, retractions, unpositioned

    @staticmethod
    def _spans(track_data: dict, base: TimeBase) -> list:
        """(order, first instant, last instant, segment) for every segment that has points."""
        spans = []
        for order, segment in enumerate(track_data.get("segment") or []):
            points = segment.get("tp") or []
            if not points:
                continue
            instants = [base.at(p.get("relTime"), where=f"TrackSegment[{order}].tp[{i}]")
                        for i, p in enumerate(points)]
            spans.append((order, min(instants), max(instants), segment))
        return spans

    @staticmethod
    def _overlaps(spans: list) -> list[str]:
        """Every pair of segments overlapping in time. The multi-hypothesis case, and a refusal.

        Table 2.5.25-1's own example: a multi-hypothesis tracker "generates 10 hypothesized
        tracks … isn't sure which of these hypothesized track segments is part of the actual
        track, so it reports all of them". Interleaving them into one sample list would be a
        physically absurd track; minting a track_id per segment would make identity depend on a
        producer's chunking; and taking the highest-confidence segment would be silent
        best-hypothesis selection. All three are decisions a translator may not make.

        Returns the violations rather than raising, so the caller can quote them ALONGSIDE any
        out-of-order violations. The two conditions overlap in practice — segments that overlap
        in time are usually also out of order — and whichever is checked first would otherwise
        be the only cause a producer ever hears about.
        """
        found = []
        for (a_order, a_start, a_end, _a), (b_order, b_start, b_end, _b) in \
                [(x, y) for i, x in enumerate(spans) for y in spans[i + 1:]]:
            if a_start <= b_end and b_start <= a_end:
                found.append(
                    f"OVERLAPPING SEGMENTS: TrackSegment[{a_order}] spans "
                    f"{times.render(a_start)}...{times.render(a_end)} and "
                    f"TrackSegment[{b_order}] spans {times.render(b_start)}..."
                    f"{times.render(b_end)}: they overlap in time inside one TrackData. That is "
                    f"the multi-hypothesis structure of Table 2.5.25-1 — {len(spans)} segments, "
                    f"confidences {[s[3].get('confidence') for s in spans]!r} — and this adapter "
                    "refuses it rather than interleaving incompatible paths into one history, "
                    "minting a track per segment, or selecting the highest-confidence segment. "
                    "Which of those a consumer wants is a consumer's decision")
        return found

    def _point_position(self, point: dict, frames: Frames, where: str,
                        position_source: PositionSource = PositionSource.ESTIMATED) -> dict:
        """The `Dynamics` block a sample's position comes from, by the preference order."""
        blocks = point.get("dynamics") or []
        resolved = [resolve_dynamics(block, frames, where, position_source) for block in blocks]
        chosen = None
        for system in CS_PREFERENCE:
            for block, result in zip(blocks, resolved):
                if block.get("cs") == system and result["position"] is not None:
                    chosen = (block, result)
                    break
            if chosen:
                break
        if chosen is None:
            return {"position": None, "kinematics": None, "raw": [b for b in blocks],
                    "basis": "; ".join(r["basis"] for r in resolved) or "no Dynamics block",
                    "kinematics_basis": "no position, so no local horizon to decompose against"}
        block, result = chosen
        disagreement = self._disagreement(blocks, resolved, result)
        raw = {"chosen_cs": block.get("cs"), "blocks": blocks}
        if disagreement is not None:
            raw["position_disagreement_m"] = disagreement
        return {**result, "raw": raw}

    @staticmethod
    def _disagreement(blocks: list, resolved: list, chosen: dict) -> float | None:
        """Two resolvable blocks disagreeing is the source's to explain, not ours to average."""
        worst = None
        for result in resolved:
            other = result["position"]
            if other is None or other is chosen["position"]:
                continue
            metres = math.hypot(
                (other.lat - chosen["position"].lat) * 111_320.0,
                (other.lon - chosen["position"].lon) * 111_320.0
                * math.cos(math.radians(chosen["position"].lat)))
            worst = metres if worst is None else max(worst, metres)
        return None if worst is None else round(worst, 3)

    # ------------------------------------------------------------- identity fields

    def _affiliation(self, objects_stated: list) -> tuple[Affiliation, str, str | None]:
        """`ID1241` -> affiliation, the basis, and the exercise role where there is one."""
        for stated in objects_stated:
            id1241 = stated.get("id1241")
            if not isinstance(id1241, dict):
                continue
            identity = id1241.get("identity")
            amplification = id1241.get("identityAmplification")
            mapped = IDENTITY.get(identity) if identity else None

            if amplification in AMPLIFICATION_FRIENDLY:
                role = amplification if amplification in AMPLIFICATION_EXERCISE_ROLE else None
                basis = (
                    f"IdentityAmplification {amplification!r}, which Ed B Table 2.5.34-3 defines "
                    f"beginning \"Friendly\" — so the standard states the identity and reading it "
                    f"is translation, not adjudication. FRIENDLY"
                    + (f", overriding identity {identity!r}, which an exercise produces and "
                       "which the amplification contradicts" if mapped and
                       mapped is not Affiliation.FRIENDLY else "")
                    + (f". The exercise role is parked at attributes.exercise_role"
                       if role else ""))
                return Affiliation.FRIENDLY, basis, role

            if amplification in AMPLIFICATION_SUSPECT:
                # SUSPECT has no CDM member (gap 2), so the amplification sets nothing — and it
                # does NOT downgrade a stated identity either, whatever that identity is.
                #
                # Ed B Table 2.5.34-1 makes these two separate attributes: `identity` is "the
                # estimated identity/status ... in accordance with STANAG 1241" and
                # `identityAmplification` is "additional identity/status information
                # (amplification)". No co-occurrence restriction is stated, so FRIEND + ZOMBIE is
                # the designated identity field plus an amplifier the standard permits beside it,
                # not a contradiction for a translator to adjudicate. Downgrading the primary
                # assertion because of a secondary field is the move `CollectionInformation.
                # essence` is forbidden from making against source.synthetic, and resolving the
                # tension is the fusion-layer judgement `enums.Affiliation` says we do not make.
                return (mapped or Affiliation.UNKNOWN), (
                    f"identity {identity!r} governs — it is the designated identity attribute, "
                    f"and IdentityAmplification {amplification!r} is \"additional identity/"
                    "status information\" that Ed B permits beside it with no stated "
                    "co-occurrence restriction. The amplification states a SUSPECT identity, "
                    "which has no CDM member: gap 2, recorded rather than rounded towards "
                    "HOSTILE and never used to downgrade the stated identity"), None

            if mapped is not None:
                lossy = identity in ("ASSUMED_FRIEND", "SUSPECT")
                return mapped, (
                    f"ID1241.identity {identity!r}"
                    + (" — gap 2: no CDM member, and it collapses to UNKNOWN rather than to "
                       "FRIENDLY or HOSTILE, because an assumption is not an identification and "
                       "suspicion is not identification" if lossy else "")), None
            if identity is not None:
                return Affiliation.UNKNOWN, (
                    f"ID1241.identity {identity!r} is not one of the six STANAG 1241 Ed. 5 "
                    "literals; the XSD types every enumeration as a union with xs:string, so an "
                    "unrecognised value is conformant and is parked rather than refused"), None
        return Affiliation.UNKNOWN, (
            "no TrackedObject states an ID1241 identity. UNKNOWN because the document is SILENT, "
            "which is a different fact from a wider vocabulary having been collapsed"), None

    def _entity_type(self, objects_stated: list) -> tuple[EntityType, str]:
        """`ObjectClass.table` -> entity type. Disagreement between stated classes is UNKNOWN."""
        tables = [oc.get("table") for stated in objects_stated
                  for oc in (stated.get("objectClass") or []) if oc.get("table")]
        if not tables:
            return EntityType.UNKNOWN, "no TrackedObject states an ObjectClass"
        mapped = {APP6_TABLE.get(t, EntityType.UNKNOWN) for t in tables}
        if len(mapped) == 1:
            only = next(iter(mapped))
            unknown_reason = ""
            if only is EntityType.UNKNOWN:
                unknown_reason = (" — the CDM has no member for it, which is a decision and not "
                                  "an omission; the code is parked at attributes.app6")
            return only, f"APP-6 table(s) {sorted(set(tables))!r}{unknown_reason}"
        return EntityType.UNKNOWN, (
            f"APP-6 tables {sorted(set(tables))!r} map to different CDM entity types, and "
            "choosing between a producer's own competing classifications is a judgement")

    def _source_ids(self, track_data: dict, objects_stated: list, lid_scope: str | None) -> list:
        """Every stable key this TrackData offers, including the one three adapters share."""
        from synapse_cdm.models import SourceId

        seen: list[SourceId] = []

        def add(system: str, external_id: str) -> None:
            if not any(s.system == system and s.external_id == external_id for s in seen):
                seen.append(SourceId(system=system, external_id=external_id))

        for block in [track_data] + list(objects_stated):
            key = key_of(block, lid_scope)
            if key:
                add(key[0], key[1])
        for stated in objects_stated:
            for iff in stated.get("iffCode") or []:
                if iff.get("mode") == IFF_MODE_S and ICAO24_RE.match(str(iff.get("value", ""))):
                    # The same 24-bit address adsb.py and asterix_cat021.py key on, so one
                    # airframe seen by three adapters derives one entity_id. Narrow on purpose:
                    # IFFCode.value is a bare String with no stated syntax for any mode, so a
                    # value that is not unambiguously six hex digits is parked and not keyed.
                    add(ICAO24_SYSTEM, str(iff["value"]).lower())
        return seen

    @staticmethod
    def _confidence(objects_stated: list) -> float | None:
        """`TrackedObject.confidence` -> `Entity.confidence`, PROBABILITY only.

        A HUMAN_INSTINCT 30 and a P-VALUE 30 are not the same number and the CDM's float cannot
        hold the difference, so only the one type whose meaning the field can carry is mapped.
        `valid = false` is a retraction and is never read as a confidence.
        """
        for stated in objects_stated:
            block = stated.get("confidence")
            if isinstance(block, dict) and block.get("type") == "PROBABILITY" \
                    and block.get("valid") is not False:
                return round(float(block["value"]) / 100.0, 6)
        return None

    @staticmethod
    def _profile_basis(profiles: list, frames: Frames) -> str:
        known = [p for p in profiles if p in ("STANDALONE", "DATASTREAM")]
        unknown = [p for p in profiles if p not in ("STANDALONE", "DATASTREAM")]
        return (
            f"profile {profiles!r}; recognised {known!r}"
            + (f"; unregistered literal(s) {unknown!r} parked, because new profiles are "
               "registerable and the XSD types the enumeration as a union with xs:string"
               if unknown else "")
            + ". No reference is followed: resolving a DATASTREAM reference means caching "
              "objects across payloads, which is state, and state is where fusion hides. An "
              "absent profile is not a claim — §2.5.1 says a consumer shall not infer "
              "non-conformance from silence"
            + (f". {len(frames.unresolved)} reference(s) did not resolve within this payload "
               "and are listed at attributes.unresolved_references; they are NOT in "
               "unavailable_fields, because the source knows and said so in another file"
               if frames.unresolved else ""))

    # ------------------------------------------------------------- the Events

    def _event(self, shared: dict, *, key_source: dict, kind: str, event_type: EventType,
               observed_at: _dt.datetime, observed_basis: str, payload: dict,
               geometry: Any = None, related: list | None = None) -> Event:
        from synapse_cdm.models import SourceId

        lid_scope = shared["lid_scope"]
        key = key_of(key_source, lid_scope)
        source_ids = [SourceId(system=key[0], external_id=key[1])] if key else []
        event_key = key[1] if key else \
            f"{kind}:{shared['message_index']}:{times.render(observed_at)}"
        base_payload = {
            "nits_root": shared["root"],
            "nits_message": shared["message"],
            "nits_message_index": shared["message_index"],
            "nits_profiles": shared["profiles"],
            "observed_at_basis": observed_basis,
            "severity_basis": (
                "INFO. NITS grades nothing — not even its own COLLISION motion event, whose "
                "definition §2.5.37 hands to the data producer. Grading a producer-defined "
                "event would mean grading something whose threshold we do not know"),
            "synthetic_basis": shared["essence_basis"],
            "consolidation_basis": (
                "carried, not applied: §2.1.1.2.3's consolidation across data streams is a "
                "consumer obligation and this is a translation of one document"),
        }
        if shared["label"]:
            base_payload["confidentiality_label"] = shared["label"]
        base_payload.update(payload)
        return Event(
            source=self.source_ref(),
            source_ids=source_ids or [SourceId(system=UID_SYSTEM, external_id=event_key)],
            event_id=ids.derive(UID_SYSTEM, event_key, kind="event"),
            event_type=event_type, severity=Severity.INFO,
            related_entities=related or [], geometry=geometry, payload=base_payload,
            observed_at=observed_at, received_at=shared["received"],
        )

    def _from_detection(self, detection: dict, shared: dict) -> Event:
        base: TimeBase = shared["base"]
        frames: Frames = shared["frames"]
        where = f"Detection in TrackMessage[{shared['message_index']}]"
        observed = base.at(detection.get("relTime"), where=where)
        geometry, geometry_basis = None, "the detection states no centroid"
        for centroid in detection.get("centroid") or []:
            geometry, geometry_basis = geometry_from_points(centroid, frames, where)
            if geometry is not None:
                break
        return self._event(
            shared, key_source=detection, kind="detection", event_type=EventType.DETECTION,
            observed_at=observed, geometry=geometry,
            observed_basis=self._rel_basis(detection.get("relTime"), base, where),
            payload={
                "nits_detection": detection,
                "geometry_basis": geometry_basis,
                "related_entities_basis": (
                    "empty. A detection is evidence FOR a track point and the association runs "
                    "the other way, from Evidence inside a TrackPoint. Walking that reference "
                    "backwards is a join — gap 19"),
            })

    def _from_analysis(self, block: dict, shared: dict, kind: str, park_key: str,
                       rel_time: Any) -> Event:
        base: TimeBase = shared["base"]
        where = f"{kind} in TrackMessage[{shared['message_index']}]"
        if rel_time is None and kind == "processedTrack":
            observed = base.base_time
            basis = ("TrackMessage.baseTime. ProcessedTrack is the only class in the model with "
                     "no time attribute of any kind, so no instant was stated")
        else:
            observed = base.at(rel_time, where=where)
            basis = self._rel_basis(rel_time, base, where)
        return self._event(
            shared, key_source=block, kind=kind, event_type=EventType.STATUS_CHANGE,
            observed_at=observed, observed_basis=basis,
            payload={
                park_key: block,
                "related_entities_basis": (
                    "empty. This class names TRACK identifiers, and related_entities holds "
                    "entity_id values — deriving entity ids from track ids would assert an "
                    "entity-level relationship the wire never carried. Gap 19"),
                "fusion_basis": (
                    "carried verbatim and never acted on: the adapter does not merge, split, "
                    "stitch or re-run anything. A tracker stating a conclusion is a producer's "
                    "statement; acting on it is a consumer's decision"),
            })

    def _from_motion_event(self, event: dict, shared: dict) -> Event:
        base: TimeBase = shared["base"]
        frames: Frames = shared["frames"]
        where = f"MotionEvent in TrackMessage[{shared['message_index']}]"
        start = event.get("startRelTime")
        unavailable: list[str] = []
        if start is None:
            observed = base.base_time
            basis = (
                "MotionEvent.startRelTime is absent. It is the ONE relTime in the model whose "
                "absence does not mean zero — its own description says \"where the startRelTime "
                "is unknown, it means the data producer does not know the start time, i.e. the "
                "value does not default to baseTime\" — and its multiplicity is [1], so the two "
                "statements cannot both be satisfied and a conformant document always carries "
                "it. The instant here is TrackMessage.baseTime as a substitute the producer did "
                "not state")
            unavailable.append("startRelTime")
        else:
            observed = base.at(start, where=where)
            basis = self._rel_basis(start, base, where)

        geometry, geometry_basis = None, "the event states neither a region nor a tripwire"
        if isinstance(event.get("region"), dict):
            geometry, geometry_basis = geometry_from_shape(event["region"], frames, where)
        if geometry is None and isinstance(event.get("tripwire"), dict):
            geometry, geometry_basis = geometry_from_points(event["tripwire"], frames, where)

        payload = {
            "nits_motion_event": event,
            "motion_event_type": event.get("type"),
            "motion_event_type_basis": (
                "parked, not mapped to EventType. EventType is an axis about what kind of REPORT "
                "this is; a maneuver vocabulary is about what the subject did. Legion's "
                "event_type reached the same settlement when its detection classes collided with "
                "the CDM enum of the same name"),
            "geometry_basis": geometry_basis,
            "end_time_basis": (
                "endRelTime absent means \"unknown OR instantaneous\" — two facts under one "
                "silence, recorded as the one silence rather than one being chosen"
                if event.get("endRelTime") is None else
                f"endRelTime {event['endRelTime']!r} resolves to "
                f"{times.render(base.at(event['endRelTime'], where=where))}"),
            "related_entities_basis": (
                "empty. trackUID/trackLID name TRACK identifiers, not entity ids — gap 19"),
        }
        if unavailable:
            payload["unavailable_fields"] = unavailable
        return self._event(shared, key_source=event, kind="motionEvent",
                           event_type=EventType.STATUS_CHANGE, observed_at=observed,
                           observed_basis=basis, payload=payload, geometry=geometry)

    def _retraction_event(self, segment: dict, shared: dict, entity_id: Any) -> Event:
        base: TimeBase = shared["base"]
        return self._event(
            shared, key_source=segment, kind="segmentRetraction",
            event_type=EventType.STATUS_CHANGE, observed_at=base.base_time,
            observed_basis=("TrackMessage.baseTime: a TrackSegment carries no relTime of its "
                            "own, and this one carries no points to take an instant from"),
            related=[entity_id],
            payload={
                "nits_segment_retraction": segment,
                "retraction_basis": (
                    "a TrackSegment with a Confidence and no track points is a statement ABOUT "
                    "a history rather than part of one (§2.1.1.2.3 c), and Track.samples "
                    "requires at least one sample — so it becomes an Event. The retraction is "
                    "carried and NOT applied: applying it means holding the object it retracts"),
            })

    @staticmethod
    def _rel_basis(rel_time: Any, base: TimeBase, where: str) -> str:
        stated = ("omitted, which the standard defines as zero — a STATED instant, not an "
                  "absence, so it is not in unavailable_fields" if rel_time is None
                  else f"relTime {rel_time!r}")
        precision = ("" if base.whole_ms else
                     f". relTimeIncrement {base.raw_increment!r} s is not a whole number of "
                     "milliseconds, so this Timestamp is a truncation and the raw integers at "
                     "attributes.nits_times are the record")
        return (f"{where}: baseTime {base.raw_base_time} + {stated} x relTimeIncrement "
                f"{base.raw_increment!r} s{precision}")

    # ------------------------------------------------------------------ egress

    #: The increment a CDM-native document is emitted with. 0.001 s makes the CDM's own
    #: three-decimal Timestamp exactly representable as an integer count, so nothing rounds.
    NATIVE_INCREMENT = 0.001

    def from_cdm(self, objects: list[CDMBase]) -> bytes:
        """CDM objects -> one STANDALONE NITSRoot document.

        Not byte-exact, and it cannot be: XML permits insignificant whitespace, attribute order
        and namespace prefix choice, none of which carries information. The claim that IS made is
        that every value re-emitted equals the value read — raw relTime integers, coordinate
        arrays, the confidentiality label — because they come from the park rather than from a
        recomputation.
        """
        entities = [o for o in objects if isinstance(o, Entity)]
        tracks = [o for o in objects if isinstance(o, Track)]
        events = [o for o in objects if isinstance(o, Event)]
        if not entities and not tracks:
            raise NitsError(
                "nothing to emit: a NITSRoot with no TrackData and no Detection would be a "
                "document that says only that a producer exists")

        document = self._egress_root(entities, events)
        message = self._egress_message(entities, tracks, events)
        document["message"] = [message]
        self._refuse_dangling(document)
        return _serialise(document)

    def _egress_root(self, entities: list[Entity], events: list[Event]) -> dict:
        parked_roots = []
        for holder in [e.attributes for e in entities] + [e.payload for e in events]:
            root = holder.get("nits_root")
            if isinstance(root, dict) and root not in parked_roots:
                parked_roots.append(root)
        if len(parked_roots) > 1:
            # NARROW, and the narrowing is the point. This refuses a VERBATIM ROUND TRIP of two
            # NITSRoot contexts under one root: §2.1.1.2.3 says that when two objects' lidScopeUID
            # values differ, "the same local ID value can be used to represent different things",
            # and re-scoping round-tripped identifiers would break the cross-file correlation
            # those identifiers exist to provide.
            #
            # It does NOT refuse CDM-native egress from many sources. That path mints fresh
            # identifiers — see `_native_track`, which keys on the CDM's own UUIDs and emits no
            # local ID at all — so no parked identifier survives and no collision is possible.
            # A consolidated picture goes through the mint path.
            raise NitsError(
                f"{len(parked_roots)} different NITSRoot contexts are parked across these "
                "objects, which would be a verbatim round trip of two documents under one root. "
                "Each carries its own lidScopeUID, and §2.1.1.2.3 says that when two differ the "
                "same local ID may name different things — so merging them would make identifiers "
                "from two scopes collide silently, and re-scoping them would destroy the "
                "cross-file correlation they exist for. Emit them separately, or build the "
                "consolidated picture from CDM-native objects, which mint fresh identifiers"
            )
        label = self._egress_label(entities, events)
        if parked_roots:
            document = dict(parked_roots[0])
        else:
            document = {
                "profile": ["STANDALONE"],
                "nitsVersion": NITS_VERSION,
                "product": {"id": f"{self.name}-{self.version}",
                            "name": "Synapse CDM egress"},
            }
        document.update(label)
        document["profile"] = ["STANDALONE"]
        document["nitsVersion"] = NITS_VERSION
        document["msgCreatedTime"] = times.render(self.now())
        return document

    def _egress_label(self, entities: list[Entity], events: list[Event]) -> dict[str, str]:
        """Three paths: the park, the deployment's configured label, or a refusal.

        Ed B Annex B.2 makes `originatorConfidentialityLabel` mandatory on the root element, so
        every emitted document needs one and "somewhere" is enumerated rather than defaulted.
        """
        for holder in [e.attributes for e in entities] + [e.payload for e in events]:
            parked = holder.get("confidentiality_label")
            if isinstance(parked, dict) and parked.get(LABEL_ORIGINATOR):
                return dict(parked)
        if self._label:
            return {LABEL_ORIGINATOR: self._label}
        raise NitsError(
            "no confidentiality label. Ed B Annex B.2 requires an "
            f"<{LABEL_ORIGINATOR}> on the root element, and there are exactly three ways to get "
            "one: re-emit the parked label of a round-tripped NITS object, take an explicit "
            "deployment-supplied label from Stanag4676Adapter(confidentiality_label=...), or "
            "refuse. There is no safe fourth: UNCLASSIFIED is the dangerous direction, a label "
            "copied from a neighbouring object is a marking its originator never applied to this "
            "one, and an empty element is non-conformant"
        )

    def _egress_message(self, entities: list[Entity], tracks: list[Track],
                        events: list[Event]) -> dict:
        parked_messages = [e.attributes.get("nits_message") for e in entities
                           if isinstance(e.attributes.get("nits_message"), dict)]
        message: dict[str, Any] = dict(parked_messages[0]) if parked_messages else {}

        parked_tracks = [e.attributes["nits_track"] for e in entities
                         if isinstance(e.attributes.get("nits_track"), dict)]
        native = [t for t in tracks
                  if not any(e.entity_id == t.entity_id and "nits_track" in e.attributes
                             for e in entities)]
        if parked_tracks:
            message["track"] = parked_tracks
        if native:
            base_time = min(s.observed_at for t in native for s in t.samples)
            message.setdefault("baseTime", times.render(base_time))
            message.setdefault("relTimeIncrement", self.NATIVE_INCREMENT)
            increment = float(message["relTimeIncrement"])
            base = times.parse(message["baseTime"])
            message.setdefault("track", [])
            for track in native:
                message["track"].append(self._native_track(track, base, increment))
        for key, parked in (("detection", "nits_detection"),
                            ("processedTrack", "nits_processed_track"),
                            ("trackLinkage", "nits_track_linkage"),
                            ("motionEvent", "nits_motion_event")):
            carried = [e.payload[parked] for e in events
                       if isinstance(e.payload.get(parked), dict)]
            if carried:
                message[key] = carried
        for event in events:
            retraction = event.payload.get("nits_segment_retraction")
            if isinstance(retraction, dict):
                message.setdefault("track", [])
                if not any(retraction in (td.get("segment") or []) for td in message["track"]):
                    message["track"].append({"segment": [retraction]})
        if "baseTime" not in message:
            raise NitsError("no baseTime: nothing in these objects states a time base")
        return message

    def _native_track(self, track: Track, base: _dt.datetime, increment: float) -> dict:
        """A CDM-native Track -> one TrackData with one TrackSegment.

        §2.5.25 permits it outright: "if the data producer deems it unnecessary to break a track
        into multiple track segments, then all track points of the track can be included is a
        single TrackSegment object".
        """
        points = []
        for sample in track.samples:
            offset = (sample.observed_at - base).total_seconds() / increment
            if abs(offset - round(offset)) > 1e-6:
                raise NitsError(
                    f"sample at {times.render(sample.observed_at)} is {offset!r} increments "
                    f"after baseTime at relTimeIncrement {increment} s, which is not a whole "
                    "number. Rounding would move the point; the increment has to divide the "
                    "instants exactly"
                )
            position = [sample.position.lat, sample.position.lon]
            if sample.position.alt_m is not None:
                position.append(sample.position.alt_m)
            points.append({"relTime": int(round(offset)),
                           "dynamics": [{"cs": CS_WGS84, "pos": position}]})
        # Keyed on the CDM's own UUIDs and carrying NO local ID: `lidScopeUID` is required only
        # "if local IDs are found in the object", so a document built entirely this way needs no
        # scope and cannot collide with anything. That is what makes multi-source egress a mint
        # rather than a merge.
        return {"uid": str(track.track_id), "segment": [{"tp": points}],
                "object": [{"uid": str(track.entity_id)}]}

    @staticmethod
    def _refuse_dangling(document: dict) -> None:
        """A STANDALONE file whose references point nowhere is a silent non-conformance."""
        available = {
            "sensorUID": {_uuid_text(s.get("uid")) for s in document.get("sensor") or []},
            "trackerUID": {_uuid_text(t.get("uid")) for t in document.get("tracker") or []},
            "collectionUID": {_uuid_text(c.get("uid")) for c in document.get("collection") or []},
        }
        for message in document.get("message") or []:
            for track in message.get("track") or []:
                for holder, where in [(track.get("trackSource"), "TrackData.trackSource")] + [
                        (s.get("segmentSource"), f"TrackSegment[{i}].segmentSource")
                        for i, s in enumerate(track.get("segment") or [])]:
                    if not isinstance(holder, dict):
                        continue
                    for attribute, present in available.items():
                        for reference in holder.get(attribute) or []:
                            if _uuid_text(reference) not in present:
                                raise NitsError(
                                    f"{where}.{attribute} references {_uuid_text(reference)!r}, "
                                    "which is not in this document. The STANDALONE profile "
                                    "requires every referent inline, and a dangling reference is "
                                    "a non-conformance a consumer discovers as silently missing "
                                    "sensor metadata"
                                )


# ==================================================================== writing XML
#
# The same provisional binding as the reader, driven by the same `MODEL`, so the two cannot
# disagree about a name. Elements are written in the standard's own attribute order, which is
# what makes a golden file stable.

def _text(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, list):
        return " ".join(_text(v) for v in value)
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _write(parent: ET.Element, name: str, value: Any, class_name: str) -> None:
    fields = dict(MODEL[class_name])
    if class_name in SHAPE_SPECIALIZATIONS:
        fields.update(MODEL["Shape"])
    kind = fields[name][1]
    tag = ELEMENT_NAMES.get(name, name)
    if kind == "Shape":
        concrete = value.get("_type")
        child = ET.SubElement(parent, tag, {_XSI_TYPE: concrete})
        _write_class(child, value, concrete)
    elif kind in MODEL:
        child = ET.SubElement(parent, tag)
        _write_class(child, value, kind)
    elif kind == "u" and isinstance(value, dict):
        child = ET.SubElement(parent, tag, {"gidp": str(value["gidp"])})
        child.text = _text(value[CORE_VALUE_KEY])
    else:
        ET.SubElement(parent, tag).text = _text(value)


def _write_class(element: ET.Element, block: dict, class_name: str) -> None:
    fields = dict(MODEL[class_name])
    if class_name in SHAPE_SPECIALIZATIONS:
        fields.update(MODEL["Shape"])
    core = CORE_VALUE_CLASSES.get(class_name)
    if core is not None and CORE_VALUE_KEY in block:
        element.text = _text(block[CORE_VALUE_KEY])
    for name, (multiplicity, _kind) in fields.items():
        if name not in block or block[name] is None:
            continue
        value = block[name]
        if multiplicity.endswith("*"):
            for item in value:
                _write(element, name, item, class_name)
        else:
            _write(element, name, value, class_name)
    for tag, fragments in (block.get("_unmodelled") or {}).items():
        for fragment in fragments:
            element.append(ET.fromstring(fragment))


#: The placeholder a confidentiality label occupies while the rest of the document is being
#: serialised. It is substituted for the verbatim fragment LAST, after any pretty-printing.
_LABEL_PLACEHOLDER = "nits-confidentiality-label-placeholder"


def _serialise(document: dict, *, pretty: bool = False) -> bytes:
    """The document as XML, with every confidentiality label byte-for-byte as it arrived.

    The labels do NOT go through the element tree. Appending a parsed label and re-serialising
    rewrites the producer's namespace prefix — `slab:` comes out as `ns0:` — and a pretty-printer
    then re-indents its content, so what egress emitted would be a different fragment from what
    ingest read. That is the one thing the classification settlement says must not happen, so the
    labels are held out as placeholders and substituted into the finished text.
    """
    root = ET.Element("NITSRoot")
    present = [name for name in LABEL_ELEMENTS if document.get(name)]
    for index, _name in enumerate(present):
        ET.SubElement(root, _LABEL_PLACEHOLDER, {"n": str(index)})
    _write_class(root, {k: v for k, v in document.items() if k not in LABEL_ELEMENTS},
                 "NITSRoot")
    text = ET.tostring(root, encoding="unicode")
    if pretty:
        import xml.dom.minidom
        text = xml.dom.minidom.parseString(text).documentElement.toprettyxml(indent="  ")
    for index, name in enumerate(present):
        for form in (f'<{_LABEL_PLACEHOLDER} n="{index}" />',
                     f'<{_LABEL_PLACEHOLDER} n="{index}"/>'):
            text = text.replace(form, document[name])
    return ('<?xml version="1.0" encoding="utf-8"?>\n' + text).encode("utf-8")
