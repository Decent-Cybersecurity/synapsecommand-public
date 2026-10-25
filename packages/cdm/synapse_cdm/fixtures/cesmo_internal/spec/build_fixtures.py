"""Write the SYNTHETIC fixtures of `cesmo_internal` that the kit does not ship, and their records.

The five valid documents of the SynapseCommand STANAG 4658 CESMO and EOB Engineering Kit 1.0
(Decent Cybersecurity, 4 October 2026) are carried byte-identical beside this directory, and so is
its expected projection, under `reference/`; this script never writes them (their SHA-256, as the
kit's own `SHA256SUMS.txt` states it, is in `cesmo_internal_pin.json`, and the adapter test holds
the carried files to it).
Everything else here is derived from them in the kit's invented vocabulary (`TEST-NET`,
`TEST-SOURCE-A`, `EXERCISE-1`, `EMITTER-n`, `mode: synthetic`): the authored documents, the octet
twin, every refusal under `malformed/` and the three `PROVENANCE.json` records. Every position a
valid authored document states lies inside CONTRIBUTING.md's Baltic rectangle (56.0-58.5 N,
20.0-24.5 E); the kit's own `upsert.json` states 0, 0 on purpose, and the refusals cut from it
keep that 0, 0, except `e_schema_latitude_91.json`, whose latitude 91 is its fault.

    python -I -B fixtures/cesmo_internal/spec/build_fixtures.py          # write
    python -I -B fixtures/cesmo_internal/spec/build_fixtures.py --check  # compare only

Edit this script and run it; never edit a fixture by hand.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
MALFORMED = ROOT / "malformed"
REFERENCE = ROOT / "reference"

CONTRACT = "sc.cesmo.internal/1.0"
SOURCE = {
    "network_id": "TEST-NET",
    "originator_id": "TEST-SOURCE-A",
    "identity_epoch": "EXERCISE-1",
}
NOTICE = "Invented synthetic values; no operational source"
KIT = (
    "the SynapseCommand STANAG 4658 CESMO and EOB Engineering Kit 1.0 (Decent Cybersecurity, "
    "4 October 2026), synthetic example; released into this repository by the maintainer on "
    "2026-10-24"
)
PIN = "cesmo_internal/spec/cesmo_internal_pin.json"

#: The kit files carried byte-identical; this script reads the fixtures and writes none of them.
KIT_FILES = (
    ROOT / "empty-complete-snapshot.json",
    ROOT / "observation.json",
    ROOT / "status.json",
    ROOT / "upsert.json",
    ROOT / "withdrawal.json",
    REFERENCE / "expected-upsert-cdm.json",
)


def text(document) -> bytes:
    """The kit's own layout: two-space indentation, a final newline."""
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def exchange(
    message_id, records, *, observed_at="2026-10-04T12:00:00Z", snapshot=None, source=None
):
    doc = {
        "contract": CONTRACT,
        "mode": "synthetic",
        "source": dict(source or SOURCE),
        "message_id": message_id,
        "observed_at": observed_at,
        "records": records,
    }
    if snapshot is not None:
        doc["snapshot"] = snapshot
    return doc


def kit(name: str) -> dict:
    return json.loads((ROOT / name).read_bytes())


# --------------------------------------------------------------------- the authored documents


def every_kind() -> dict:
    """One record of each kind in one Exchange: an observation naming an emitter at an asserted
    position with a height, an upsert of that emitter, a withdrawal of an emitter this message
    never asserts, and a source status."""
    return exchange(
        "MSG-6",
        [
            {
                "record_id": "OBS-2",
                "kind": "observation",
                "revision": 1,
                "observed_at": "2026-10-04T12:00:05Z",
                "object_id": "EMITTER-2",
                "position": {
                    "latitude_deg": 57.25,
                    "longitude_deg": 21.5,
                    "hae_m": 41.5,
                    "method": "inertial",
                },
                "signal": {
                    "frequency_hz": 9400000000.5,
                    "bandwidth_hz": 0,
                    "bearing_deg_true": 0,
                    "sensor_id": "SENSOR-1",
                },
                "extensions": {"notice": NOTICE},
            },
            {
                "record_id": "EOB-2",
                "kind": "eob_upsert",
                "revision": 1,
                "observed_at": "2026-10-04T12:00:06Z",
                "object_id": "EMITTER-2",
                "position": {"latitude_deg": 57.25, "longitude_deg": 21.5, "method": "manual"},
                "signal": {"frequency_hz": 9400000000.5},
                "affiliation": "FRIENDLY",
                "confidence": 1,
                "extensions": {"notice": NOTICE},
            },
            {
                "record_id": "DEL-2",
                "kind": "eob_delete",
                "revision": 2,
                "observed_at": "2026-10-04T12:00:07Z",
                "object_id": "EMITTER-3",
            },
            {
                "record_id": "STATE-2",
                "kind": "status",
                "revision": 1,
                "observed_at": "2026-10-04T12:00:08Z",
                "extensions": {"state": "degraded", "state_namespace": "synthetic-test-only"},
            },
        ],
    )


def complete_snapshot_with_upserts() -> dict:
    """A complete snapshot that carries records: two upserts at the snapshot's revision, one with
    every measurement block and a height, one with none and no affiliation or confidence."""
    return exchange(
        "MSG-7",
        [
            {
                "record_id": "EOB-3",
                "kind": "eob_upsert",
                "revision": 8,
                "observed_at": "2026-10-04T11:59:30Z",
                "object_id": "EMITTER-2",
                "position": {
                    "latitude_deg": 57.5,
                    "longitude_deg": 22.25,
                    "hae_m": 312.5,
                    "method": "gnss",
                },
                "signal": {
                    "frequency_hz": 2900000000,
                    "bandwidth_hz": 5000000,
                    "pulse_width_s": 0.000001,
                    "pri_s": 0.001,
                    "power_dbm": -71.5,
                    "sensor_id": "SENSOR-2",
                },
                "uncertainty": {
                    "semi_major_m": 250,
                    "semi_minor_m": 250,
                    "orientation_deg": 0,
                    "probability": 1,
                    "frame": "ENU_TRUE_NORTH",
                },
                "affiliation": "HOSTILE",
                "confidence": 0.75,
                "extensions": {"notice": NOTICE},
            },
            {
                "record_id": "EOB-4",
                "kind": "eob_upsert",
                "revision": 8,
                "observed_at": "2026-10-04T11:59:31Z",
                "object_id": "EMITTER-4",
            },
        ],
        snapshot={"snapshot_id": "SNAP-2", "complete": True, "revision": 8},
    )


def observation_position_no_object() -> dict:
    """An observation with an asserted position and an ellipse but no emitter identifier: an
    Event with a Point and no related entity, and no Entity."""
    return exchange(
        "MSG-8",
        [
            {
                "record_id": "OBS-3",
                "kind": "observation",
                "revision": 1,
                "observed_at": "2026-10-04T12:00:10Z",
                "position": {"latitude_deg": 56.5, "longitude_deg": 23.75, "method": "estimated"},
                "signal": {"frequency_hz": 435000000, "power_dbm": -92.25},
                "uncertainty": {
                    "semi_major_m": 1200,
                    "semi_minor_m": 300,
                    "orientation_deg": 179.5,
                    "probability": 0.9,
                    "frame": "ENU_TRUE_NORTH",
                },
                "confidence": 0.5,
                "extensions": {"notice": NOTICE},
            }
        ],
    )


def sub_millisecond() -> dict:
    """Six fraction digits: non-zero in the fourth to sixth (truncated by the CDM, so the token is
    listed), zero in them (nothing dropped, no token), one digit, and an envelope time with a
    non-zero sixth digit for the partial snapshot's event."""
    return exchange(
        "MSG-9",
        [
            {
                "record_id": "EOB-5",
                "kind": "eob_upsert",
                "revision": 9,
                "observed_at": "2026-10-04T12:00:09.123456Z",
                "object_id": "EMITTER-5",
                "position": {"latitude_deg": 58.0, "longitude_deg": 24.0, "method": "estimated"},
            },
            {
                "record_id": "EOB-6",
                "kind": "eob_upsert",
                "revision": 9,
                "observed_at": "2026-10-04T12:00:09.120000Z",
                "object_id": "EMITTER-6",
            },
            {
                "record_id": "EOB-7",
                "kind": "eob_upsert",
                "revision": 9,
                "observed_at": "2026-10-04T12:00:09.5Z",
                "object_id": "EMITTER-7",
            },
        ],
        observed_at="2026-10-04T12:00:09.000250Z",
        snapshot={"snapshot_id": "SNAP-3", "complete": False, "revision": 9},
    )


#: Extension keys spelled like CDM fields, holding source-form values: the case that made the
#: conformance suite walk a residual before `suite.PARKED` gained `residual` (DECISIONS C-02).
CDM_SHAPED = {
    "track_id": "TRK-7",
    "object_id": "NATIVE-9",
    "entity_id": "NATIVE-10",
    "event_id": "NATIVE-11",
    "last_seen_at": "2026-10-04T11:59:00Z",
    "valid_from": "2026-10-04T11:58:00Z",
    "notice": NOTICE,
}


def cdm_shaped_extension_keys() -> dict:
    return exchange(
        "MSG-10",
        [
            {
                "record_id": "OBS-4",
                "kind": "observation",
                "revision": 1,
                "observed_at": "2026-10-04T12:00:11Z",
                "object_id": "EMITTER-8",
                "signal": {"bearing_deg_true": 359.5, "sensor_id": "SENSOR-3"},
                "extensions": dict(CDM_SHAPED),
            },
            {
                "record_id": "EOB-8",
                "kind": "eob_upsert",
                "revision": 1,
                "observed_at": "2026-10-04T12:00:12Z",
                "object_id": "EMITTER-8",
                "affiliation": "NEUTRAL",
                "extensions": dict(CDM_SHAPED),
            },
        ],
    )


def pad(prefix: str) -> str:
    """A token of exactly 64 characters, the contract's maximum."""
    return prefix + "0" * (64 - len(prefix))


def tokens_at_64() -> dict:
    """Every token field at 64 characters: the identity keys at their longest."""
    return exchange(
        pad("MSG-"),
        [
            {
                "record_id": pad("EOB-"),
                "kind": "eob_upsert",
                "revision": 3,
                "observed_at": "2026-10-04T12:00:13Z",
                "object_id": pad("EMITTER-"),
                "signal": {"frequency_hz": 1000000000, "sensor_id": pad("SENSOR-")},
            }
        ],
        snapshot={"snapshot_id": pad("SNAP-"), "complete": False, "revision": 3},
        source={
            "network_id": pad("TEST-NET-"),
            "originator_id": pad("TEST-SOURCE-A-"),
            "identity_epoch": pad("EXERCISE-1-"),
        },
    )


AUTHORED = {
    "every-kind.json": every_kind,
    "complete-snapshot-with-upserts.json": complete_snapshot_with_upserts,
    "observation-position-no-object.json": observation_position_no_object,
    "sub-millisecond.json": sub_millisecond,
    "cdm-shaped-extension-keys.json": cdm_shaped_extension_keys,
    "tokens-at-64.json": tokens_at_64,
}


# --------------------------------------------------------------------------------- refusals


def edited(base: str, edit) -> bytes:
    """A kit document parsed, edited in place by `edit`, and written in the kit's layout."""
    doc = kit(base)
    edit(doc)
    return text(doc)


def record(doc: dict) -> dict:
    return doc["records"][0]


def octets(replace: tuple[bytes, bytes], base: str = "upsert.json") -> bytes:
    raw = (ROOT / base).read_bytes()
    old, new = replace
    if raw.count(old) != 1:
        raise SystemExit(f"build_fixtures: {old!r} is not in {base} exactly once")
    return raw.replace(old, new)


def deep_extension(depth: int) -> bytes:
    """upsert.json with nested arrays under `extensions`, so the document nests `depth`
    containers: the root, `records`, the record and `extensions` are four."""
    nested = "[" * (depth - 4) + "]" * (depth - 4)
    return octets((b'"source_category": "synthetic-emitter",', f'"nested": {nested},'.encode()))


def semantic_snapshot_with_observation(doc: dict) -> None:
    doc["snapshot"] = {"snapshot_id": "SNAP-9", "complete": True, "revision": 1}


def two_records(doc: dict, change) -> None:
    second = copy.deepcopy(record(doc))
    change(second)
    doc["records"].append(second)


#: file -> (octets, the defect, the code the adapter test expects)
def refusals() -> dict[str, tuple[bytes, str, str]]:
    upsert = (ROOT / "upsert.json").read_bytes()
    return {
        "e_schema_duplicate_key.bin": (
            octets((b'"mode": "synthetic",', b'"mode": "live",\n  "mode": "synthetic",')),
            "`mode` twice",
            "E_SCHEMA",
        ),
        "e_schema_nan_literal.bin": (
            octets((b'"confidence": 0', b'"confidence": NaN')),
            "`NaN`",
            "E_SCHEMA",
        ),
        "e_schema_infinity_literal.bin": (
            octets((b'"frequency_hz": 1000000000', b'"frequency_hz": Infinity')),
            "`Infinity`",
            "E_SCHEMA",
        ),
        "e_schema_number_overflow.bin": (
            octets((b'"frequency_hz": 1000000000', b'"frequency_hz": 1e400')),
            "`1e400`, past binary64",
            "E_SCHEMA",
        ),
        "e_schema_number_underflow.bin": (
            octets((b'"frequency_hz": 1000000000', b'"frequency_hz": 1e-400')),
            "`1e-400`, which binary64 holds only as zero",
            "E_SCHEMA",
        ),
        "e_schema_integer_past_binary64.bin": (
            octets((b'"revision": 4', b'"revision": ' + b"9" * 310)),
            "a 310-digit integer",
            "E_SCHEMA",
        ),
        "e_schema_byte_order_mark.bin": (
            b"\xef\xbb\xbf" + upsert,
            "a UTF-8 byte order mark",
            "E_SCHEMA",
        ),
        "e_schema_invalid_utf8.bin": (
            octets((b'"notice": "Zero', b'"notice": "\xffZero')),
            "a byte 0xFF in a string",
            "E_SCHEMA",
        ),
        "e_schema_lone_surrogate_escape.bin": (
            octets((b'"notice": "Zero', b'"notice": "\\ud800Zero')),
            "an escaped lone surrogate",
            "E_SCHEMA",
        ),
        "e_schema_trailing_content.bin": (
            upsert + b"{}\n",
            "a second JSON text after the document",
            "E_SCHEMA",
        ),
        "e_schema_top_level_array.bin": (
            b"[" + upsert + b"]",
            "the document inside a JSON array",
            "E_SCHEMA",
        ),
        "e_limit_depth_17.bin": (deep_extension(17), "17 nested containers", "E_LIMIT"),
        "e_schema_trailing_newline_token.json": (
            edited("upsert.json", lambda d: record(d).update(object_id="EMITTER-1\n")),
            "`object_id` ending in a newline",
            "E_SCHEMA",
        ),
        "e_schema_hour_24.json": (
            edited("upsert.json", lambda d: record(d).update(observed_at="2026-10-04T24:00:00Z")),
            "hour 24 in the record's `observed_at`",
            "E_SCHEMA",
        ),
        "e_schema_february_30.json": (
            edited("upsert.json", lambda d: d.update(observed_at="2026-02-30T12:00:00Z")),
            "30 February in the envelope's `observed_at`",
            "E_SCHEMA",
        ),
        "e_schema_second_60.json": (
            edited("upsert.json", lambda d: record(d).update(observed_at="2026-10-04T12:00:60Z")),
            "second 60 (a leap second) in the record's `observed_at`",
            "E_SCHEMA",
        ),
        "e_schema_non_ascii_digit.json": (
            edited("upsert.json", lambda d: d.update(observed_at="2026-10-0٤T12:00:00Z")),
            "an Arabic-Indic digit four in the envelope's `observed_at`",
            "E_SCHEMA",
        ),
        "e_schema_snapshot_record_id.json": (
            edited("upsert.json", lambda d: record(d).update(record_id="$snapshot")),
            "the reserved `$snapshot` as a `record_id`",
            "E_SCHEMA",
        ),
        "e_schema_unknown_top_level_key.json": (
            edited("upsert.json", lambda d: d.update(unknown_header=1)),
            "a key the envelope does not define",
            "E_SCHEMA",
        ),
        "e_schema_unknown_record_key.json": (
            edited("upsert.json", lambda d: record(d).update(operation="upsert")),
            "a key the record does not define",
            "E_SCHEMA",
        ),
        "e_schema_missing_required_key.json": (
            edited("upsert.json", lambda d: d.pop("message_id")),
            "no `message_id`",
            "E_SCHEMA",
        ),
        "e_schema_revision_not_integer.json": (
            edited("upsert.json", lambda d: record(d).update(revision=4.0)),
            "`revision` 4.0, a number and not an integer",
            "E_SCHEMA",
        ),
        "e_schema_probability_zero.json": (
            edited("upsert.json", lambda d: record(d)["uncertainty"].update(probability=0)),
            "ellipse `probability` 0",
            "E_SCHEMA",
        ),
        "e_schema_orientation_180.json": (
            edited("upsert.json", lambda d: record(d)["uncertainty"].update(orientation_deg=180)),
            "ellipse `orientation_deg` 180",
            "E_SCHEMA",
        ),
        "e_schema_latitude_91.json": (
            edited("upsert.json", lambda d: record(d)["position"].update(latitude_deg=91)),
            "`latitude_deg` 91",
            "E_SCHEMA",
        ),
        "e_unsupported_message_unknown_contract.json": (
            edited("upsert.json", lambda d: d.update(contract="sc.cesmo.internal/2.0")),
            "a contract this adapter does not implement",
            "E_UNSUPPORTED_MESSAGE",
        ),
        "e_mode_mismatch_live.json": (
            edited("upsert.json", lambda d: d.update(mode="live")),
            "`mode` live under the default (synthetic) constructor",
            "E_MODE_MISMATCH",
        ),
        "e_semantic_repeated_record_id.json": (
            edited(
                "upsert.json", lambda d: two_records(d, lambda r: r.update(object_id="EMITTER-9"))
            ),
            "two records with one `record_id`",
            "E_SEMANTIC",
        ),
        "e_semantic_upsert_without_object_id.json": (
            edited("upsert.json", lambda d: record(d).pop("object_id")),
            "an `eob_upsert` without `object_id`",
            "E_SEMANTIC",
        ),
        "e_semantic_empty_records_without_snapshot.json": (
            edited("upsert.json", lambda d: d.update(records=[])),
            "no record and no snapshot",
            "E_SEMANTIC",
        ),
        "e_semantic_ellipse_axes_reversed.json": (
            edited(
                "upsert.json",
                lambda d: record(d)["uncertainty"].update(semi_major_m=100, semi_minor_m=400),
            ),
            "`semi_minor_m` above `semi_major_m`",
            "E_SEMANTIC",
        ),
        "e_semantic_ellipse_without_position.json": (
            edited("upsert.json", lambda d: record(d).pop("position")),
            "an ellipse and no position",
            "E_SEMANTIC",
        ),
        "e_semantic_snapshot_with_observation.json": (
            edited("observation.json", semantic_snapshot_with_observation),
            "a snapshot holding an `observation`",
            "E_SEMANTIC",
        ),
        "e_semantic_snapshot_revision_mismatch.json": (
            edited(
                "upsert.json",
                lambda d: d.update(
                    snapshot={"snapshot_id": "SNAP-9", "complete": True, "revision": 5}
                ),
            ),
            "a snapshot at revision 5 holding a record at revision 4",
            "E_SEMANTIC",
        ),
        "e_semantic_snapshot_repeats_object_id.json": (
            edited(
                "upsert.json",
                lambda d: (
                    d.update(snapshot={"snapshot_id": "SNAP-9", "complete": True, "revision": 4}),
                    two_records(d, lambda r: r.update(record_id="EOB-9")),
                ),
            ),
            "a snapshot naming one `object_id` twice",
            "E_SEMANTIC",
        ),
        "e_semantic_status_with_object_id.json": (
            edited("status.json", lambda d: record(d).update(object_id="EMITTER-1")),
            "a `status` naming an emitter",
            "E_SEMANTIC",
        ),
        "e_semantic_withdrawal_with_position.json": (
            edited(
                "withdrawal.json",
                lambda d: record(d).update(
                    position={"latitude_deg": 57.0, "longitude_deg": 22.0, "method": "manual"}
                ),
            ),
            "an `eob_delete` carrying a position",
            "E_SEMANTIC",
        ),
    }


# ---------------------------------------------------------------------------- the records


def row(name: str, origin: str) -> dict:
    return {
        "file": name,
        "synthetic": True,
        "classification": "PUBLIC",
        "operational_data": False,
        "personal_data": False,
        "origin": origin,
        "standard_ref": PIN,
    }


def provenance(directory: str, rows: list[dict]) -> bytes:
    return text(
        {"schema_id": "synapse.fixture-provenance/v1", "directory": directory, "fixtures": rows}
    )


def planned() -> dict[pathlib.Path, bytes]:
    files: dict[pathlib.Path, bytes] = {}
    for name, build in AUTHORED.items():
        files[ROOT / name] = text(build())
    files[ROOT / "upsert_octets.bin"] = (ROOT / "upsert.json").read_bytes()
    top = []
    for path in sorted(list(KIT_FILES) + list(files)):
        if path.parent != ROOT:
            continue
        if path in KIT_FILES:
            origin = (
                f"Synthetic SC CESMO Internal Exchange 1.0 document, byte-identical to fixtures/"
                f"{path.name} of {KIT}; invented identifiers (TEST-NET, TEST-SOURCE-A, EXERCISE-1, "
                "mode synthetic), no capture and no operational source. Its sha256 is in "
                "spec/cesmo_internal_pin.json."
            )
        elif path.suffix == ".bin":
            origin = (
                "The octets of upsert.json, byte for byte, as a non-.json payload so the harness "
                f"and the conformance suite run the strict octet path on a valid document; {KIT}."
            )
        else:
            origin = (
                "Synthetic SC CESMO Internal Exchange 1.0 document written on 2026-10-24 for the "
                "cesmo_internal adapter's landing by spec/build_fixtures.py, derived from "
                f"{KIT}, in its invented vocabulary (TEST-NET, TEST-SOURCE-A, EXERCISE-1, "
                "EMITTER-n, mode synthetic); README.md says what it exercises. Nothing derives "
                "from recorded data."
            )
        top.append(row(path.name, origin))
    files[ROOT / "PROVENANCE.json"] = provenance("cesmo_internal", top)
    bad = []
    for name, (data, defect, code) in sorted(refusals().items()):
        files[MALFORMED / name] = data
        bad.append(
            row(
                name,
                f"Synthetic refusal payload written on 2026-10-24 by spec/build_fixtures.py: a "
                f"synthetic example of {KIT}, with one defect ({defect}), refused as {code}; "
                "README.md lists each file. Nothing derives from recorded data.",
            )
        )
    files[MALFORMED / "PROVENANCE.json"] = provenance("cesmo_internal/malformed", bad)
    files[REFERENCE / "PROVENANCE.json"] = provenance(
        "cesmo_internal/reference",
        [
            row(
                "expected-upsert-cdm.json",
                "The kit's expected CDM projection of upsert.json (an Entity and an Event, CDM "
                "3.0.0, receipt clock 2026-10-04T12:00:01Z), byte-identical to "
                f"expected-upsert-cdm.json of {KIT}; synthetic, no capture.",
            )
        ],
    )
    return files


def kit_problems() -> list[str]:
    return [p.name for p in KIT_FILES if not p.is_file()]


def main(argv: list[str]) -> int:
    broken = kit_problems()
    if broken:
        print("KIT FILE MISSING: " + ", ".join(broken))
        return 1
    files = planned()
    if "--check" in argv:
        stale = [p for p, b in files.items() if not p.exists() or p.read_bytes() != b]
        print("CURRENT" if not stale else "STALE: " + ", ".join(p.name for p in stale))
        return 0 if not stale else 1
    MALFORMED.mkdir(parents=True, exist_ok=True)
    for path, data in files.items():
        path.write_bytes(data)
    print(f"wrote {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
