"""Build the STANAG 4676 fixture set. Synthetic only — no recorded NITS traffic.

Run from the repository root:

    python packages/cdm/synapse_cdm/fixtures/nits/spec/build_fixtures.py

Each case is written as a TWIN: a `.nits.xml` document and a `.parsed.json` holding the parsed
form the never-drop check measures against. Both go through `to_cdm()` when the harness replays
the directory, and a test asserts the two produce identical CDM objects — which is what makes the
provisional XML element binding checkable rather than merely declared.

IDENTIFIERS. RFC 9562 §5.8 version 8 is reserved for custom and experimental use, so a producer
issuing v4 or v7 cannot collide with these, and every one carries the `f1c7` prefix the Legion
fixtures established. Local IDs are small integers under a version-8 `lidScopeUID`, which is
exactly the composite the identity settlement requires before a lid may be a SourceId.

STATION IDENTIFICATION. `IDData.nationality` uses `ZZZ`, which is not a NATO trigraph in
APP-11(D) — and unlike the CAT021 SAC there is no pinned allocation list behind that claim, so
it is the weakest claim in this fixture set and this comment is where it says so.

ESSENCE. Every document states a non-REAL essence, because the harness constructs the adapter
with synthetic=True and a REAL essence against that declaration is a conflict refusal by design.
The REAL case is exercised in tests, where the declaration can be set to match.
"""
import json
import pathlib

import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))

from synapse_cdm.adapters.stanag4676 import _serialise  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent

U = "f1c70000-0000-8000-8000-0000000000{:02d}"
SCOPE = "f1c75c09-0000-8000-8000-000000000001"

LABEL = (
    '<slab:originatorConfidentialityLabel '
    'xmlns:slab="urn:nato:stanag:4774:confidentialitymetadatalabel:1:0">'
    '<slab:ConfidentialityInformation>'
    '<slab:PolicyIdentifier>NATO</slab:PolicyIdentifier>'
    '<slab:Classification>NATO UNCLASSIFIED</slab:Classification>'
    '<slab:Category Type="PERMISSIVE" TagName="Releasable to">'
    '<slab:GenericValue>NATO</slab:GenericValue>'
    '</slab:Category>'
    '</slab:ConfidentialityInformation>'
    '<slab:CreationDateTime>2026-04-29T06:00:00Z</slab:CreationDateTime>'
    '</slab:originatorConfidentialityLabel>'
)

SENSOR_UID = U.format(10)
TRACKER_UID = U.format(11)
COLLECTION_UID = U.format(12)


def root(**overrides):
    document = {
        "profile": ["STANDALONE"],
        "fileUID": U.format(1),
        "lidScopeUID": SCOPE,
        "numFiles": 1,
        "msgCreatedTime": "2026-04-29T06:00:00Z",
        "nitsVersion": "B.2",
        "originatorConfidentialityLabel": LABEL,
        "product": {"uid": U.format(2), "id": "SYN-NITS-001",
                    "name": "Synthetic NITS Track Product", "shortName": "SNTP",
                    "effectivity": "2026A"},
        "collection": [{"uid": COLLECTION_UID, "intent": "EXERCISE", "essence": "SIMULATED",
                        "targetID": "AREA-ALPHA"}],
        "sensor": [{
            "uid": SENSOR_UID, "lid": 1,
            "sensorID": {"stationID": "SYNSENS01", "nationality": "ZZZ"},
            "name": "Synthetic EO sensor", "description": "fixture sensor",
            "modality": "IMAGE_SIGNATURE", "url": "https://example.invalid/sensor",
            "collectionMode": "STARE", "absTimeUncertainty": 0.05,
            "relTimeUncertainty": 0.001, "comment": "not parsed for embedded data",
            "esmSensor": {},
            "imagingSensor": {"motionImageryCoreID": "0102030405060708",
                              "frameHeight": 1080, "frameWidth": 1920, "fpaIndex": 1,
                              "filter": [[0.4, 0.9], [0.7, 0.8]], "phenomenology": "VIS",
                              "band": "VIS-1"},
            "radarSensor": {"platformID": "SYN-TAIL-1", "missionID": 7, "jobID": 3},
        }],
        "tracker": [{
            "type": "AUTOMATIC_TRACKER", "uid": TRACKER_UID, "lid": 2,
            "trackerID": {"stationID": "SYNTRAK01", "nationality": "ZZZ"},
            "name": "Synthetic tracker", "description": "fixture tracker", "version": "0.1",
            "supplementaryData": [{"type": "DIGITAL_ELEVATION_MODEL", "name": "SYN-DEM",
                                   "version": "2026.1", "description": "fixture DEM"}],
        }],
    }
    document.update(overrides)
    return document


def message(**overrides):
    block = {"numDetections": 0, "numTracks": 1,
             "baseTime": "2026-04-29T06:00:00Z", "relTimeIncrement": 1.0}
    block.update(overrides)
    return block


def wgs84_point(rel_time, lat, lon, alt=None, **extra):
    position = [lat, lon] + ([alt] if alt is not None else [])
    point = {"relTime": rel_time, "dynamics": [{"cs": "WGS_84", "pos": position}]}
    point.update(extra)
    return point


def doc(**message_kwargs):
    """One root holding exactly one TrackMessage. Every case but the DATASTREAM one uses it."""
    return root(message=[message(**message_kwargs)])


CASES: dict[str, dict] = {}


# 1 — the minimal STANDALONE track, and the reference case for everything else.
CASES["standalone_basic_track"] = doc(track=[{
    "uid": U.format(20), "lid": 3,
    "trackSource": {"sensorUID": [SENSOR_UID], "trackerUID": [TRACKER_UID],
                    "collectionUID": [COLLECTION_UID]},
    "segment": [{"uid": U.format(21), "status": "MAINTAINING",
                 "tp": [wgs84_point(0, 56.9496, 24.1052, 12.0),
                        wgs84_point(1, 56.9500, 24.1060, 12.5),
                        wgs84_point(2, 56.9505, 24.1071, 13.0)]}],
    "object": [{"uid": U.format(22), "description": "a synthetic surface contact",
                "numberOfObjects": 1, "objectColor": [[12, 34, 56]],
                "confidence": {"type": "PROBABILITY", "value": 80, "sourceReliability": 70,
                               "valid": True},
                "dims": [4.5, 1.8, 1.6, -1.0, 0.0, 0.0, -1.0, 0.0, -1.0], "priority": 5,
                "objectClass": [{"table": "LAND_EQUIPMENT", "entity": "Ground Vehicle",
                                 "entityType": "Truck", "code": "150101"}],
                "id1241": {"identity": "NEUTRAL", "identitySourceModality": "IMAGE_SIGNATURE",
                           "environment": "LAND"}}],
}])

# 2 — three contiguous segments under ONE TrackData: amendment A's one-Track rule and the
#     per-segment index ranges, both in one document.
CASES["three_contiguous_segments_one_track"] = doc(numTracks=1, track=[{
    "uid": U.format(23),
    "segment": [
        {"uid": U.format(24), "status": "INITIATING", "initiationReason": "ENTERED_FOV",
         "confidence": {"type": "PROBABILITY", "value": 90},
         "tp": [wgs84_point(0, 56.90, 24.00), wgs84_point(1, 56.91, 24.01)]},
        {"uid": U.format(25), "status": "MAINTAINING",
         "segmentSource": {"sensorUID": [SENSOR_UID]},
         "comment": "handed to the imaging sensor",
         "tp": [wgs84_point(2, 56.92, 24.02), wgs84_point(3, 56.93, 24.03)]},
        {"uid": U.format(26), "status": "TERMINATED", "terminationReason": "EXITED_FOV",
         "tp": [wgs84_point(4, 56.94, 24.04)]},
    ],
    "object": [{"uid": U.format(27),
                "id1241": {"identity": "FRIEND", "environment": "LAND"}}],
}])

# 3 — ECEF, and the closed-form transform the Legion adapter also performs.
CASES["ecef_track_with_velocity"] = doc(track=[{
    "uid": U.format(28),
    "segment": [{"tp": [
        {"relTime": 0, "dynamics": [{"cs": "ECEF",
                                     "pos": [3183000.0, 1421000.0, 5322000.0],
                                     "vel": [10.0, -5.0, 2.0],
                                     "acc": [0.1, 0.0, -0.1],
                                     "cov": {"covarianceType": "POS3D",
                                             "value": [25.0, 0.0, 0.0, 25.0, 0.0, 9.0]}}]},
        {"relTime": 1, "dynamics": [{"cs": "ECEF",
                                     "pos": [3183010.0, 1420995.0, 5322002.0],
                                     "vel": [10.0, -5.0, 2.0]}]},
    ]}],
    "object": [{"uid": U.format(29), "id1241": {"identity": "UNKNOWN"}}],
}])

# 4 — the WGS-84 kinematics split: a height axis present, so the conversion runs.
CASES["wgs84_velocity_with_height"] = doc(track=[{
    "uid": U.format(30),
    "segment": [{"tp": [
        {"relTime": 0, "dynamics": [{"cs": "WGS_84", "pos": [56.95, 24.10, 100.0],
                                     "vel": [0.0009, 0.0016, 1.5]}]},
    ]}],
    "object": [{"uid": U.format(31)}],
}])

# 5 — the other branch: no height axis, so the velocity parks whole.
CASES["wgs84_velocity_without_height"] = doc(track=[{
    "uid": U.format(32),
    "segment": [{"tp": [
        {"relTime": 0, "dynamics": [{"cs": "WGS_84", "pos": [56.95, 24.10],
                                     "vel": [0.0009, 0.0016]}]},
    ]}],
    "object": [{"uid": U.format(33)}],
}])

# 6 — LOCAL_CARTESIAN with a complete ECEF CFT beside a WGS_84 block, so the preference order
#     and the disagreement check both run.
CASES["local_cartesian_with_complete_cft"] = doc(
    dynSrcInfo=[{
        "uid": U.format(40), "lid": 4, "relTime": 0,
        "sensorUID": SENSOR_UID,
        "sensorLocation": {"dims": 3, "cs": "WGS_84", "points": [56.90, 24.00, 250.0]},
        "groupID": "FRAME-GROUP-1", "numDetections": 2, "numReportedDetections": 1,
        "dynCFT": [{"uid": U.format(41), "lid": 5, "cft": {
            "from": "ECEF",
            "translation": [3183000.0, 1421000.0, 5322000.0],
            "rotation": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]}}],
        "sourceMI": {"frameNumber": 41, "niirs": 5.5, "vniirs": 5.0, "sea": 33.0, "tea": 47.0,
                     "gsd": [0.25], "grd": [0.35],
                     "frameBoundingBox": {"_type": "Polygon", "dims": 2, "cs": "WGS_84",
                                          "nRings": 1,
                                          "vertices": [56.9, 24.0, 56.9, 24.1, 57.0, 24.1,
                                                       57.0, 24.0]},
                     "useableFOV": {"_type": "Polygon", "dims": 2, "cs": "PIXELS", "nRings": 1,
                                    "vertices": [0.0, 0.0, 0.0, 1919.0, 1079.0, 1919.0]},
                     "processedFOV": {"_type": "Polygon", "dims": 2, "cs": "PIXELS",
                                      "nRings": 1,
                                      "vertices": [10.0, 10.0, 10.0, 1900.0, 1000.0, 1900.0]}},
        "sourceRadar": {"revisitIndex": 2, "dwellIndex": 7},
        "sourceESM": {},
    }],
    track=[{
        "uid": U.format(34),
        "segment": [{"tp": [{
            "relTime": 0, "dynSrcUID": U.format(40),
            "dynamics": [
                {"cs": "LOCAL_CARTESIAN", "pos": [10.0, 20.0, 5.0],
                 "vel": [1.0, 0.0, 0.0], "cftUID": U.format(41)},
                {"cs": "WGS_84", "pos": [56.9496, 24.1052, 12.0]},
            ]}]}],
        "object": [{"uid": U.format(35)}],
    }])

# 7 — LOCAL_SPHERICAL with a COMPLETE CFT: still attributes-only, and that is the point.
CASES["local_spherical_is_attributes_only"] = doc(
    dynSrcInfo=[{"uid": U.format(42), "dynCFT": [{"uid": U.format(43), "cft": {
        "from": "ECEF", "translation": [3183000.0, 1421000.0, 5322000.0],
        "rotation": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]}}]}],
    numTracks=1,
    track=[{
        "uid": U.format(36),
        "segment": [{"tp": [
            {"relTime": 0, "dynamics": [{"cs": "LOCAL_SPHERICAL", "pos": [500.0, 45.0, 30.0],
                                         "cftUID": U.format(43)}]},
            {"relTime": 1, "dynamics": [{"cs": "WGS_84", "pos": [56.96, 24.11, 20.0]}]},
        ]}],
        "object": [{"uid": U.format(37)}],
    }])

# 8 — a complex multi-ring polygon on a MotionEvent region: all three corrections at once, with
#     the ring delimiter carried as the literal token `NaN`.
CASES["motion_event_complex_polygon"] = doc(
    numTracks=1,
    track=[{"uid": U.format(50),
            "segment": [{"tp": [wgs84_point(0, 56.80, 24.20)]}],
            "object": [{"uid": U.format(51)}]}],
    motionEvent=[{
        "type": "INSIDE_ROI", "uid": U.format(52), "trackUID": [U.format(50)],
        "startRelTime": 0, "endRelTime": 2,
        "confidence": {"type": "HUMAN_INSTINCT", "value": 60},
        "region": {
            "_type": "Polygon", "dims": 2, "cs": "WGS_84", "nRings": 2,
            # Outer ring clockwise (included), inner ring counter-clockwise (excluded),
            # separated by an all-NaN null point. Both are reversed and reordered on the way
            # into RFC 7946.
            "vertices": [56.7, 24.1, 56.9, 24.1, 56.9, 24.3, 56.7, 24.3,
                         "NaN", "NaN",
                         56.78, 24.18, 56.78, 24.22, 56.82, 24.22, 56.82, 24.18],
        },
    }])

# 9 — a tripwire, which is a LineString and is never closed.
CASES["motion_event_tripwire"] = doc(
    numTracks=1,
    track=[{"uid": U.format(53), "segment": [{"tp": [wgs84_point(0, 56.70, 24.30)]}],
            "object": [{"uid": U.format(54)}]}],
    motionEvent=[{"type": "CROSSING_TRIPWIRE", "uid": U.format(55), "startRelTime": 1,
                  "tripwire": {"dims": 2, "cs": "WGS_84",
                               "points": [56.69, 24.28, 56.71, 24.32]}}])

# 10 — the Detection/Evidence tree, with every leaf class present.
CASES["detection_evidence_tree"] = doc(
    numDetections=1, numTracks=1,
    detection=[{
        "uid": U.format(60), "lid": 6, "relTime": 0,
        "centroid": [{"dims": 3, "cs": "WGS_84", "points": [56.95, 24.10, 8.0]}],
        "outline": [{"_type": "Ellipsoid", "dims": 2, "cs": "WGS_84",
                     "center": [56.95, 24.10, -1.0, 4.0, 0.0, 0.0, 4.0, 0.0, -1.0],
                     "ellipsoidParameters": {"covarianceType": "POS2D",
                                             "value": [16.0, 0.0, 16.0]}}],
        "sensorUID": SENSOR_UID, "dynSrcUID": U.format(40),
        "confidence": {"type": "P-VALUE", "value": 4, "valid": True},
        "source": {"sensorUID": [SENSOR_UID], "trackerUID": [TRACKER_UID]},
        "esm": {},
        "im": {"centroidPixel": [540, 960], "color": [200, 180, 160],
               "pixelMask": {"pixelPolygon": {"nRings": 1,
                                              "integerArray": [3, 1, 3, 3, 6, 3]},
                             "pixelRun": {"rs": [[3, 1, 6], [4, 3, 3]], "cs": [[2, 3, 5]]}},
               "chip": {"type": "png", "uri": "https://example.invalid/chip.png",
                        "image": "iVBORw0KGgo="}},
        "radar": {"reportIndex": 11, "hrrType": 2},
        "sm": [{"quantity": "SNR", "method": "MEAN", "value": 12.5, "uncertainty": 0.4}],
    }],
    track=[{
        "uid": U.format(61),
        "segment": [{"tp": [{
            "relTime": 0,
            "associatedDetection": True, "processType": "AUTOMATIC",
            "confidence": {"type": "PROBABILITY", "value": 75},
            "comment": "a track point comment",
            "nearestConfuser": 18.5,
            "nearestConfuserConfidence": {"type": "PROBABILITY", "value": 50},
            "outline": {"_type": "Polygon", "dims": 2, "cs": "WGS_84", "nRings": 1,
                        "vertices": [56.949, 24.105, 56.949, 24.106, 56.950, 24.106]},
            "outlineObscured": {"_type": "Polygon", "dims": 2, "cs": "WGS_84", "nRings": 1,
                                "vertices": [56.949, 24.105, 56.949, 24.1055, 56.9495, 24.1055]},
            "sm": [{"quantity": "RADIANCE", "method": "MAX", "value": 3.25}],
            "dynamics": [{"cs": "WGS_84", "pos": [56.9496, 24.1052, 12.0]}],
            "evidence": [{"type": "CIRCUMSTANTIAL", "subtype": "DUST_PLUME",
                          "uid": U.format(62), "detectionUID": [U.format(60)],
                          "confidence": {"type": "PROBABILITY", "value": 65}}],
        }]}],
        "object": [{"uid": U.format(63)}],
    }])

# 11 — FAKER: friendly, playing hostile. Amendment C's whole subject.
CASES["exercise_faker_is_friendly"] = doc(track=[{
    "uid": U.format(70),
    "segment": [{"tp": [wgs84_point(0, 57.10, 24.50, 1500.0)]}],
    "object": [{"uid": U.format(71),
                "iffCode": [{"mode": "MODE_S", "value": "0029AB"},
                            {"mode": "MODE3", "value": "7421"},
                            {"mode": "MODE5", "value": "AUTHENTICATED"}],
                "objectClass": [{"table": "AIR", "entity": "Military",
                                 "entityType": "Fixed Wing", "code": "110101"}],
                "id1241": {"identity": "HOSTILE", "identityAmplification": "FAKER",
                           "environment": "AIR"},
                "idSourceInformation": [{
                    "idQualityNumber": "Q3", "sourceDeclarationBinary": 1,
                    "sourceDeclarationExtension": 4, "relTimeCreation": 0,
                    "relTimeExchange": 1,
                    "idSourceNumber": {"sourceType": "IFF", "sourceSubtype": "MODE5",
                                       "sourceDeviceClass": "SYN-IFF-1"}}],
                "exampleDetectionUID": [U.format(60)]}],
}])

# 12 — ZOMBIE against a FRIEND identity: the suspect contradiction, which cannot be expressed.
CASES["amplification_zombie_contradicts_friend"] = doc(track=[{
    "uid": U.format(72),
    "segment": [{"tp": [wgs84_point(0, 57.20, 24.60)]}],
    "object": [{"uid": U.format(73),
                "id1241": {"identity": "FRIEND", "identityAmplification": "ZOMBIE"}}],
}])

# 13 — the analysis classes, all three, carried and never acted on.
CASES["linkage_processed_track_carried"] = doc(
    numTracks=2,
    track=[
        {"uid": U.format(80), "segment": [{"tp": [wgs84_point(0, 56.60, 24.40)]}],
         "object": [{"uid": U.format(81)}]},
        {"uid": U.format(82), "segment": [{"tp": [wgs84_point(2, 56.62, 24.42)]}],
         "object": [{"uid": U.format(83)}]},
    ],
    processedTrack=[{"type": "FUSED", "uid": U.format(84),
                     "confidence": {"type": "PROBABILITY", "value": 70},
                     "inputUID": [U.format(80), U.format(82)], "outputUID": U.format(85)}],
    trackLinkage=[{"type": "STITCH", "uid": U.format(86), "relTime": 1,
                   "confidence": {"type": "PROBABILITY", "value": 55},
                   "preUID": [U.format(80)], "postUID": [U.format(82)]}])

# 14 — a retraction-only segment beside a real one: an Event, not a Track, and not dropped.
CASES["segment_retraction_is_an_event"] = doc(track=[{
    "uid": U.format(90),
    "segment": [
        {"uid": U.format(91), "tp": [wgs84_point(0, 56.50, 24.50)]},
        {"uid": U.format(92), "confidence": {"type": "PROBABILITY", "value": 0,
                                             "valid": False}},
    ],
    "object": [{"uid": U.format(93)}],
}])

# 15 — DATASTREAM: a reference pointing outside the file, recorded and never followed.
#
#      The CFT is the reference that dangles, and the SensorInformation is present. That is a
#      deliberate choice about what a HARNESS fixture can express: a DATASTREAM document may
#      also omit its SensorInformation, and a parked trackSource.sensorUID with no referent
#      makes egress refuse — correctly, because a STANDALONE file needs every referent inline.
#      The harness has no "legitimately refuses" verdict for its round-trip check, so that case
#      is a unit test with an inline document rather than a fixture whose egress must fail.
CASES["datastream_unresolved_references"] = {
    "profile": ["DATASTREAM"],
    "streamUID": U.format(3), "fileUID": U.format(4), "fileLID": 9,
    "lidScopeUID": SCOPE, "numFiles": 2,
    "msgCreatedTime": "2026-04-29T06:00:05Z", "nitsVersion": "B.2",
    "originatorConfidentialityLabel": LABEL,
    "sensor": [{"uid": SENSOR_UID, "name": "Synthetic EO sensor",
                "modality": "IMAGE_SIGNATURE"}],
    "message": [message(track=[{
        "uid": U.format(94),
        "trackSource": {"sensorUID": [SENSOR_UID]},
        "segment": [{"tp": [{
            "relTime": 0,
            "dynamics": [{"cs": "LOCAL_CARTESIAN", "pos": [1.0, 2.0],
                          "cftUID": U.format(98)}]}]}],
        "object": [{"lid": 7}],
    }])],
}

# 16 — a relTimeIncrement that is not a whole number of milliseconds: the parking rule, and the
#      one case where egress MUST re-emit from the park rather than recompute.
CASES["fractional_increment_parks_raw_integers"] = doc(
    baseTime="2026-04-29T06:00:00Z", relTimeIncrement=0.0078125, track=[{
        "uid": U.format(95),
        "segment": [{"tp": [wgs84_point(3, 56.40, 24.40), wgs84_point(131, 56.41, 24.41)]}],
        "object": [{"uid": U.format(96)}],
    }])


def write() -> int:
    HERE.mkdir(parents=True, exist_ok=True)
    for name, document in CASES.items():
        (HERE / f"{name}.parsed.json").write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n")
        # `pretty=True` inside _serialise, NOT minidom out here: the confidentiality label is
        # substituted after the pretty-printer runs, so the fixture XML holds the exact fragment
        # the .parsed.json twin states and the two cannot drift.
        (HERE / f"{name}.nits.xml").write_bytes(_serialise(document, pretty=True))
    return len(CASES)


if __name__ == "__main__":
    print(f"wrote {write()} twins to {HERE}")
