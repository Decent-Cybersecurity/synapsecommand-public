#!/usr/bin/env python3
"""Build the STANAG 4586 fixture set. THE SOURCE OF TRUTH FOR BOTH ARTEFACTS.

    python build_fixtures.py                          # from the directory this file is in
    python -m synapse_cdm.harness --adapter stanag4586 --update-golden   # then READ it

Edit this file, never the `.s4586` octets and never the `.parsed.json` twins.

WHY THE ENCODER LIVES HERE AND NOT IN THE SHIPPED CODEC
--------------------------------------------------------
`adapters/stanag4586_codec.py` decodes and does not encode, and that is the scope ruling rather
than an oversight: an adapter that emits DLI is on its way to being a UCS component, and every
command message in this format is an instruction to an actuator. Fixture construction is not that
— it builds test octets that never leave this repository — so the frame builder is here, in a
generator, where `gates/bump_derivation.py` correctly does not count it as public surface
(`fixtures/` is excluded from the module half, `gates/bump_derivation.py:295`) and where nothing
can wire it to a socket.

EVERYTHING IS SYNTHETIC
-----------------------
No recorded DLI traffic and no real air vehicle. Source IDs are built from Owning ID 7, which
§1.7.6 leaves for the Custodian to assign and which no NATO allocation known here uses; 255 is
avoided because the document reserves it. Positions are in the Gulf of Riga, matching the other
fixture sets in this repository.

THE LAYOUT SUMS AGAINST THE DOCUMENT'S OWN WIDTHS
--------------------------------------------------
Every field's octet count comes from `stanag4586_codec.MESSAGES`, which transcribes the Type
column of each message's own table, and `check_layouts()` asserts that a built message's data
length equals the presence-vector width plus the widths of the fields its vector marks present.
So a fixture whose octet count drifts from the document fails here rather than in a golden diff.
`tests/test_cdm_stanag4586_adapter.py` calls it, so it cannot be skipped by not running this file.
"""
from __future__ import annotations

import json
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
FIXTURES = HERE.parent.parent
sys.path.insert(0, str(FIXTURES.parent.parent.parent))

from synapse_cdm.adapters import stanag4586_codec as dli          # noqa: E402

#: Owning ID 7, then a per-vehicle tail. §1.7.6's structure, and never 0xFF.
VEHICLE_A = (7 << 24) | 0x000101
VEHICLE_B = (7 << 24) | 0x000202
CUCS = (7 << 24) | 0x00FF01


def encode_unsigned(value: int, octets: int) -> bytes:
    return int(value).to_bytes(octets, "big", signed=False)


def encode_integer(value: int, octets: int) -> bytes:
    return int(value).to_bytes(octets, "big", signed=True)


def radians_to_bam(radians: float, octets: int) -> int:
    """The inverse of §1.7.3's scaling, rounded to the nearest representable integer."""
    bits = octets * 8
    raw = round(radians / (math.pi / (2 ** (bits - 1))))
    limit = 2 ** (bits - 1)
    return max(-limit, min(limit - 1, raw))


def encode_field(spec: dli.FieldSpec, value: float | int) -> bytes:
    """One field's octets, from a value in the document's own units."""
    if spec.kind == "timestamp":
        return encode_unsigned(int(value), spec.octets)
    if spec.kind == "bam":
        return encode_integer(radians_to_bam(float(value), spec.octets), spec.octets)
    if spec.is_enumerated or spec.scale is None:
        raw = int(value)
    else:
        raw = round(float(value) / spec.scale)
    if spec.kind == "integer":
        return encode_integer(raw, spec.octets)
    return encode_unsigned(raw, spec.octets)


def build_message(number: int, values: dict[str, float | int]) -> bytes:
    """The message data — presence vector then the present fields, in field order.

    `values` is keyed by Unique ID, which is the document's own key. A field absent from the map
    is absent from the presence vector, which is the whole point of the vector and is how the
    partial-presence fixtures are written.
    """
    spec = dli.MESSAGES[number]
    by_uid = {f.unique_id: f for f in spec.fields}
    unknown = set(values) - set(by_uid)
    if unknown:
        raise KeyError(f"message #{number} has no field(s) {sorted(unknown)}")
    vector = 0
    body = b""
    for field in spec.fields:
        if field.unique_id not in values:
            continue
        vector |= 1 << (field.index - 1)
        body += encode_field(field, values[field.unique_id])
    return encode_unsigned(vector, spec.presence_vector_octets) + body


def build_frame(number: int, data: bytes, *, source: int, destination: int = CUCS,
                checksum_octets: int = 2, sequence: int = dli.SEQUENCE_NOT_USED,
                idd_version: int = dli.IDD_VERSION_EDITION_3, ack: bool = False,
                corrupt_checksum: bool = False) -> bytes:
    """§3.3.1's sixteen-octet wrapper, the data, and an optional checksum."""
    code = {0: 0b00, 2: 0b01, 4: 0b10}[checksum_octets]
    properties = (0x8000 if ack else 0) | ((idd_version & 0x7F) << 8) | (code << 6)
    head = (encode_unsigned(sequence, 2)
            + encode_unsigned(len(data), 2)
            + encode_unsigned(source, 4)
            + encode_unsigned(destination, 4)
            + encode_unsigned(number, 2)
            + encode_unsigned(properties, 2))
    frame = head + data
    if checksum_octets == 0:
        return frame
    total = dli.compute_checksum(frame, checksum_octets)
    if corrupt_checksum:
        total = (total + 1) & ((1 << (checksum_octets * 8)) - 1)
    return frame + encode_unsigned(total, checksum_octets)


def check_layouts() -> None:
    """Every decoded message's stated presence-vector width holds its field count, and every
    built message's length equals the widths the document states for the fields it carries."""
    for number, spec in dli.MESSAGES.items():
        if not spec.presence_vector_is_wide_enough():
            raise AssertionError(
                f"message #{number} declares a {spec.presence_vector_octets}-octet presence "
                f"vector (Table {spec.table}) but has {len(spec.fields)} fields"
            )
        every = {f.unique_id: 0 for f in spec.fields}
        data = build_message(number, every)
        expected = spec.presence_vector_octets + sum(f.octets for f in spec.fields)
        if len(data) != expected:
            raise AssertionError(
                f"message #{number} with every field present builds {len(data)} octets; the "
                f"document's own widths sum to {expected}"
            )


import datetime as dt  # noqa: E402


def stamp(when: dt.datetime) -> int:
    """§1.7.2's count: milliseconds since 2000-01-01 UTC."""
    return round((when - dli.EPOCH).total_seconds() * 1000.0)


#: The fixture era of this repository's other synthetic sets.
T0 = dt.datetime(2026, 4, 29, 6, 12, 44, tzinfo=dt.timezone.utc)

#: Gulf of Riga, as every other synthetic set here.
LAT = math.radians(57.512)
LON = math.radians(21.884)


def _inertial(when: dt.datetime, *, lat: float = LAT, lon: float = LON,
              altitude_type: int = 3, altitude_m: float = 1500.0,
              north: float = 62.0, east: float = 35.0, down: float = -2.5,
              drop: tuple[str, ...] = ()) -> bytes:
    values: dict[str, float | int] = {
        "0101.01": stamp(when),
        "0101.04": lat,
        "0101.05": lon,
        "0101.06": altitude_m,
        "0101.07": altitude_type,
        "0101.08": north,
        "0101.09": east,
        "0101.10": down,
        "0101.14": math.radians(3.0),
        "0101.15": math.radians(1.5),
        "0101.16": math.radians(29.4),
    }
    for uid in drop:
        values.pop(uid, None)
    return build_message(4000, values)


def fixtures() -> dict[str, bytes]:
    """Each entry is one datagram. The name states what the fixture is FOR."""
    out: dict[str, bytes] = {}

    # 1. The ordinary case, and the only one where an Entity gets a position AND an altitude.
    out["inertial_states_wgs84_altitude"] = build_frame(
        4000, _inertial(T0), source=VEHICLE_A)

    # 2. Ambiguity 3 made concrete: a baro altitude must NOT reach Position.alt_m.
    out["altitude_type_baro_never_reaches_alt_m"] = build_frame(
        4000, _inertial(T0, altitude_type=1, altitude_m=1500.0), source=VEHICLE_A)

    # 3. Half a coordinate pair is no position, not a degraded one.
    out["longitude_absent_from_the_presence_vector"] = build_frame(
        4000, _inertial(T0, drop=("0101.05",)), source=VEHICLE_A)

    # 4. THE REFUSAL FIXTURE. Two positioned #4000 for one vehicle: the Entity states no position
    #    and says why, and both instants survive as Track samples.
    out["two_inertial_states_leave_the_entity_unpositioned"] = (
        build_frame(4000, _inertial(T0), source=VEHICLE_A)
        + build_frame(4000, _inertial(T0 + dt.timedelta(seconds=4),
                                      lat=math.radians(57.5210), lon=math.radians(21.8955)),
                      source=VEHICLE_A))

    # 5. All four decoded messages for one vehicle — the keying rule under load, and the case
    #    where #4000 and #3010 both carry a roll rate at scales fifty times apart.
    out["four_decoded_messages_one_vehicle"] = (
        build_frame(4000, build_message(4000, {
            "0101.01": stamp(T0), "0101.04": LAT, "0101.05": LON,
            "0101.06": 1500.0, "0101.07": 3,
            "0101.08": 62.0, "0101.09": 35.0, "0101.10": -2.5,
            "0101.17": 0.05, "0101.18": -0.02, "0101.19": 0.015,
        }), source=VEHICLE_A)
        + build_frame(3002, build_message(3002, {
            "0104.01": stamp(T0 + dt.timedelta(milliseconds=200)),
            "0104.10": 65.0, "0104.11": 1, "0104.12": 74,
            "3002.01": 3, "3002.03": 71,
        }), source=VEHICLE_A)
        + build_frame(3009, build_message(3009, {
            "0102.01": stamp(T0 + dt.timedelta(milliseconds=400)),
            "0102.06": 71.5, "0102.07": 66.0, "0102.08": 281.0,
            "0102.12": 1498.0, "0102.15": 1476.0, "0102.16": 1500.0,
        }), source=VEHICLE_A)
        + build_frame(3010, build_message(3010, {
            "0103.01": stamp(T0 + dt.timedelta(milliseconds=600)),
            "0103.04": 0.15, "0103.05": -0.05, "0103.06": 9.79,
            "0103.07": 0.05, "0103.08": -0.02, "0103.09": 0.015,
        }), source=VEHICLE_A))

    # 6. An undecoded type is parked and the datagram still translates. #6000 IFF Status Report
    #    is a real Edition 3 message (Table B1-78) that this adapter does not decode.
    out["an_undecoded_message_type_is_parked"] = (
        build_frame(4000, _inertial(T0), source=VEHICLE_A)
        + build_frame(6000, bytes.fromhex("0001020304050607"), source=VEHICLE_A))

    # 7. Two vehicles in one datagram are two Entities and never one.
    out["two_vehicles_are_two_entities"] = (
        build_frame(4000, _inertial(T0), source=VEHICLE_A)
        + build_frame(4000, _inertial(T0 + dt.timedelta(seconds=1),
                                      lat=math.radians(57.402), lon=math.radians(21.771)),
                      source=VEHICLE_B))

    # 8. No checksum at all — §3.3.1.11 makes it optional, and absent is not the same as failing.
    out["no_checksum_is_not_a_failing_checksum"] = build_frame(
        4000, _inertial(T0), source=VEHICLE_A, checksum_octets=0)

    # 9. A four-octet checksum, the other width Table B1-4 assigns.
    out["four_octet_checksum"] = build_frame(
        4000, _inertial(T0), source=VEHICLE_A, checksum_octets=4)

    # 10. A checksum that does not validate is FLAGGED, not refused — a producer's error has to
    #     reach the operator as data. `stanag4609` has the same fixture for the same reason.
    out["a_checksum_that_does_not_validate_is_flagged"] = build_frame(
        4000, _inertial(T0), source=VEHICLE_A, corrupt_checksum=True)

    # 11. Zero ground speed yields no course, because a bearing would be invented.
    out["zero_ground_speed_yields_no_course"] = build_frame(
        4000, _inertial(T0, north=0.0, east=0.0), source=VEHICLE_A)

    # 12. A frame declaring an IDD version that is not Edition 3's 30: decoded against Edition 3
    #     anyway, with the defect that says so. This is the shape an Edition 4 frame would arrive
    #     in, and the fixture exists so that arrival is visible rather than silent.
    out["an_idd_version_that_is_not_edition_3"] = build_frame(
        4000, _inertial(T0), source=VEHICLE_A, idd_version=40)

    return out


def main() -> None:
    check_layouts()
    written = 0
    for name, octets in fixtures().items():
        (FIXTURES / f"{name}.s4586").write_bytes(octets)
        frames = dli.decode_frames(octets)
        parsed = {
            "datagram_hex": octets.hex(),
            "octets": len(octets),
            "frames": [
                {
                    "message_type": f.wrapper.message_type,
                    "message_name": (dli.MESSAGES[f.wrapper.message_type].name
                                     if f.wrapper.message_type in dli.MESSAGES
                                     else "not decoded by this adapter"),
                    "source_id": f.wrapper.source_id,
                    "destination_id": f.wrapper.destination_id,
                    "message_length": f.wrapper.message_length,
                    "idd_version": f.wrapper.idd_version,
                    "checksum_octets": f.checksum_octets,
                    "checksum_valid": f.checksum_valid,
                    "defects": [d["kind"] for d in f.defects],
                }
                for f in frames
            ],
        }
        (FIXTURES / f"{name}.parsed.json").write_text(
            json.dumps(parsed, indent=2, sort_keys=True) + "\n")
        written += 2
    print(f"wrote {written} files into {FIXTURES} ({len(fixtures())} datagrams, each twice)")


if __name__ == "__main__":
    main()
