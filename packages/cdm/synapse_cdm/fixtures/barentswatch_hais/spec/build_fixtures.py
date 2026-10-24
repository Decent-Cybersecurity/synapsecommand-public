"""Write the SYNTHETIC fixture set of `barentswatch_hais` from the literal documents below.

Every MMSI is under MID 299, the European block no administration holds (the `ais` fixtures'
convention, `fixtures/ais/README.md`: a ship station is `299xxxxxx`, an aid to navigation
`99|299|xxxx`), every name begins `EX`, every position lies inside CONTRIBUTING.md's Baltic
rectangle (56.0 to 58.5 N, 20.0 to 24.5 E), and the day is 2026-10-19 UTC. No value is copied from
a real BarentsWatch response. Edit this script and run it; never edit a fixture by hand:

    python -I -B spec/build_fixtures.py          # rewrite the set
    python -I -B spec/build_fixtures.py --check  # print CURRENT when the tree matches

Each valid fixture is a pair: `<name>.hais`, the response's octets as the API sends them (compact
UTF-8 JSON), and `<name>.parsed.json`, the same document parsed, which is what the harness's
`lossless` column reads. `synthetic_track(n)` is also imported by the tests to build a realistic
size array in memory.
"""

from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
MALFORMED = ROOT / "malformed"

DAY = "2026-10-19"
PIN = "barentswatch_hais/spec/barentswatch_hais_pin.json"


def stamp(seconds: int, offset: str = "+00:00") -> str:
    """A msgtime `seconds` after 00:00:00 on DAY, in the API's `+00:00` form."""
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{DAY}T{hours:02d}:{minutes:02d}:{secs:02d}{offset}"


def element(mmsi: int, seconds: int, lat: float | None, lon: float | None, **extra) -> dict:
    """One element in the key order the API writes."""
    point = {
        "courseOverGround": 45.0,
        "latitude": lat,
        "longitude": lon,
        "name": "EX BALTIC ONE",
        "rateOfTurn": 0,
        "shipType": 70,
        "speedOverGround": 10.0,
        "trueHeading": 44,
        "navigationalStatus": 0,
        "mmsi": mmsi,
        "msgtime": stamp(seconds),
        "stream": "terra",
    }
    point.update(extra)
    return point


def synthetic_track(n: int, mmsi: int = 299009999) -> list[dict]:
    """`n` elements, one every 15 s, newest first, as the API delivers a busy day. 5000 points
    climb 0.5 degrees north and 1.0 degree east from 56.5 N 20.5 E, inside the rectangle."""
    points = []
    for k in range(n):
        seconds = (k * 15) % 86400
        points.append(
            element(
                mmsi,
                seconds,
                round(56.5 + k * 0.0001, 6),
                round(20.5 + k * 0.0002, 6),
                speedOverGround=round(8.0 + (k % 40) * 0.1, 1),
                courseOverGround=round((k * 0.7) % 360, 1),
                trueHeading=int((k * 0.7) % 360),
                name="EX BULK ONE",
            )
        )
    return list(reversed(points))


# ------------------------------------------------------------------ valid fixtures

UNDERWAY = 299000101
underway_newest_first = list(
    reversed(
        [
            element(
                UNDERWAY,
                36000 + 60 * k,
                57.10 + 0.01 * k,
                21.10 + 0.02 * k,
                speedOverGround=11.2 + 0.1 * k,
                courseOverGround=52.5,
                trueHeading=51,
                rateOfTurn=0 if k != 3 else -2,
            )
            for k in range(6)
        ]
    )
)
# Floats like 11.2 + 0.3 carry binary noise; round them so the file reads like the API's.
for _p in underway_newest_first:
    _p["latitude"] = round(_p["latitude"], 6)
    _p["longitude"] = round(_p["longitude"], 6)
    _p["speedOverGround"] = round(_p["speedOverGround"], 1)

SENTINEL = 299000202
nulls_and_sentinels = [
    # Newest first. The newest element states the speed and course sentinels, so the Entity has
    # a position and NO kinematics.
    element(
        SENTINEL,
        43500,
        58.20,
        22.40,
        speedOverGround=102.3,
        courseOverGround=360.0,
        trueHeading=511,
        rateOfTurn=-128,
        navigationalStatus=15,
        shipType=0,
        name=None,
    ),
    # Position 'not available' by the AIS sentinels: carried, never sampled.
    element(
        SENTINEL,
        43400,
        91.0,
        181.0,
        speedOverGround=None,
        courseOverGround=None,
        trueHeading=None,
        rateOfTurn=None,
        name=None,
    ),
    # Speed at the 102.2 floor: a real reading, kept and flagged.
    element(
        SENTINEL,
        43300,
        58.18,
        22.36,
        speedOverGround=102.2,
        courseOverGround=None,
        trueHeading=None,
        rateOfTurn=None,
        name=None,
    ),
    # Latitude null: no position, so no sample.
    element(SENTINEL, 43200, None, 22.30, name=None),
    # Every optional value null.
    element(
        SENTINEL,
        43100,
        58.15,
        22.30,
        speedOverGround=None,
        courseOverGround=None,
        trueHeading=None,
        rateOfTurn=None,
        navigationalStatus=None,
        shipType=None,
        name=None,
        stream=None,
    ),
    # Zero speed and course 0.0 are measurements, not absences.
    element(
        SENTINEL,
        43000,
        58.14,
        22.28,
        speedOverGround=0.0,
        courseOverGround=0.0,
        trueHeading=0,
        rateOfTurn=0,
        navigationalStatus=1,
        name=None,
    ),
]

#: An aid to navigation: `99|299|0010`, which the ais adapter's MMSI rule types FACILITY.
AID = 992990010
single_point = [
    element(
        AID,
        7322,
        56.75,
        20.95,
        name="EX SOLO BUOY",
        shipType=0,
        navigationalStatus=15,
        speedOverGround=0.0,
        courseOverGround=0.0,
        trueHeading=None,
        rateOfTurn=None,
    ),
]

EXTRA = 299000404
unknown_extra_key = [
    element(
        EXTRA,
        50000,
        57.50,
        23.00,
        name="EX EXTRA",
        receiverHint="synthetic-extra",
        extraBlock={"qualityLevel": 3, "tags": ["synthetic-a", "synthetic-b"]},
    ),
    # Only the four required keys: every optional key absent rather than null.
    {"mmsi": EXTRA, "msgtime": stamp(49900), "latitude": 57.49, "longitude": 22.98},
    element(EXTRA, 49800, 57.48, 22.96, name="EX EXTRA", stream="sat"),
]

DUP = 299000505
_twin = element(DUP, 20000, 57.30, 21.60, name="EX TWIN")
duplicate_instants_unordered = [
    element(DUP, 20060, 57.31, 21.62, name="EX TWIN"),
    dict(_twin),
    # A conflicting pair: one instant, two different positions.
    element(DUP, 20120, 57.32, 21.64, name="EX TWIN"),
    element(DUP, 20120, 57.33, 21.65, name="EX TWIN"),
    # Identical re-delivery of the first element above.
    dict(_twin),
    # +02:00 offset and sub-millisecond digits: 2026-10-19T07:33:20.1239+02:00 is
    # 05:33:20.1239 UTC, rendered 05:33:20.123Z (truncated), just after the identical pair.
    element(DUP, 0, 57.29, 21.58, name="EX TWIN") | {"msgtime": f"{DAY}T07:33:20.1239+02:00"},
]

VALID = {
    "underway_newest_first": underway_newest_first,
    "nulls_and_sentinels": nulls_and_sentinels,
    "single_point": single_point,
    "unknown_extra_key": unknown_extra_key,
    "duplicate_instants_unordered": duplicate_instants_unordered,
}

# ------------------------------------------------------------------ refused payloads

_ok = element(299000606, 1000, 57.0, 21.0)
MALFORMED_JSON = {
    "mixed_mmsi.json": [_ok, element(299000607, 900, 57.0, 21.0)],
    "missing_msgtime.json": [{k: v for k, v in _ok.items() if k != "msgtime"}],
    "missing_latitude.json": [{k: v for k, v in _ok.items() if k != "latitude"}],
    "msgtime_without_offset.json": [_ok | {"msgtime": f"{DAY}T00:16:40"}],
    "empty_array.json": [],
    "top_level_object.json": {"track": [_ok]},
    "mmsi_as_text.json": [_ok | {"mmsi": "299000606"}],
    "latitude_out_of_range.json": [_ok | {"latitude": 95.0}],
    "no_positioned_point.json": [
        _ok | {"latitude": 91.0, "longitude": 181.0},
        element(299000606, 900, None, 21.0),
    ],
    "negative_speed.json": [_ok | {"speedOverGround": -1.0}],
    "element_not_object.json": [_ok, [57.0, 21.0]],
}
_compact = json.dumps([_ok], separators=(",", ":"))
MALFORMED_OCTETS = {
    "duplicate_key.hais": _compact.replace(
        '"mmsi":299000606', '"mmsi":299000606,"mmsi":299000607'
    ).encode(),
    "nan_value.hais": _compact.replace('"speedOverGround":10.0', '"speedOverGround":NaN').encode(),
    "truncated.hais": _compact[: len(_compact) // 2].encode(),
    "not_utf8.hais": _compact.replace("EX BALTIC ONE", "EX \udcff").encode(
        "utf-8", "surrogateescape"
    ),
}

ORIGIN = (
    "Synthetic BarentsWatch Historic AIS track file written for the barentswatch_hais adapter by "
    "fixtures/barentswatch_hais/spec/build_fixtures.py from a literal document in that script, "
    "after the key set of the API's observed output; MMSIs are under the unallocated MID 299, "
    "names begin EX, positions lie inside CONTRIBUTING.md's Baltic rectangle, the day is "
    "2026-10-19, and nothing is recorded data."
)


def provenance(directory: str, names: list[str]) -> bytes:
    entries = [
        {
            "classification": "PUBLIC",
            "file": name,
            "operational_data": False,
            "origin": ORIGIN,
            "personal_data": False,
            "standard_ref": PIN,
            "synthetic": True,
        }
        for name in sorted(names)
    ]
    record = {
        "schema_id": "synapse.fixture-provenance/v1",
        "directory": directory,
        "fixtures": entries,
    }
    return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode()


def rendered() -> dict[pathlib.Path, bytes]:
    files: dict[pathlib.Path, bytes] = {}
    for name, doc in VALID.items():
        compact = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)
        files[ROOT / f"{name}.hais"] = compact.encode()
        files[ROOT / f"{name}.parsed.json"] = (
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
        ).encode()
    for name, doc in MALFORMED_JSON.items():
        files[MALFORMED / name] = (json.dumps(doc, indent=2) + "\n").encode()
    for name, data in MALFORMED_OCTETS.items():
        files[MALFORMED / name] = data
    files[ROOT / "PROVENANCE.json"] = provenance(
        "barentswatch_hais", [p.name for p in files if p.parent == ROOT]
    )
    files[MALFORMED / "PROVENANCE.json"] = provenance(
        "barentswatch_hais/malformed", [p.name for p in files if p.parent == MALFORMED]
    )
    return files


def main(argv: list[str]) -> int:
    files = rendered()
    if "--check" in argv:
        stale = [p for p, data in files.items() if not p.exists() or p.read_bytes() != data]
        print("CURRENT" if not stale else "STALE: " + ", ".join(p.name for p in stale))
        return 1 if stale else 0
    for path, data in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"wrote {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
