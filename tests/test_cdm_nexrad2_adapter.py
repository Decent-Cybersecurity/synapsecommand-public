"""`nexrad2`, #25 in the ordinal table: one NEXRAD Level II volume -> sweep Events and a site.

Every expectation here is a literal written from the fixture builder's own literals
(`fixtures/nexrad2/spec/build_fixtures.py`, an encoder written from ICDs 2620010J and 2620002Y
that shares no code with the adapter) and the ICD's tables, never read back from the adapter: an
instant is the volume's Modified Julian Date and milliseconds worked by hand, a converted value is
Table XVII-I's F = (N - OFFSET) / SCALE written out, an identifier is the uuid5 of the documented
namespace and name built here, and every refusal is its code and its whole text. The twins the
builder writes are the decode's expectation: each is compared with what the adapter decodes from
its octets.

Package-only: it reads the adapter, the packaged fixtures under `fixtures/nexrad2/` and runs the
packaged builder's `--check`, all through `synapse_cdm.__file__`.
"""

import copy
import datetime as dt
import json
import pathlib
import pickle
import struct
import uuid

import pytest
from pydantic import ValidationError

import synapse_cdm
from synapse_cdm import observation_contracts as oc
from synapse_cdm import times
from synapse_cdm.adapter import InputTooDeep, discover
from synapse_cdm.adapters import nexrad2
from synapse_cdm.adapters.nexrad2 import Nexrad2Adapter, Nexrad2Refused
from synapse_cdm.enums import VerticalReference, VerticalUnit
from synapse_cdm.geo import VerticalPosition
from synapse_cdm.manifest import LimitKind, UnknownFields
from synapse_cdm.models import SourceRef
from tests import observation_support as support

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "nexrad2"
MALFORMED = FIXTURES / "malformed"
GOLDEN = FIXTURES / "golden"
#: `ids.NAMESPACE`, written out: identity is checked against the documented scheme, not the code.
NAMESPACE = uuid.UUID("6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50")
FROZEN = "2026-04-29T06:15:00.000Z"
ICD = "ICD 2620002Y"

CASES = sorted(p.stem for p in FIXTURES.glob("*.ar2v"))
BUILDER = support.load_builder(FIXTURES / "spec" / "build_fixtures.py", "nexrad2_builder")


def _uuid(kind: str, system: str, external: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}|{system}|{external}"))


def _f32(value: float) -> float:
    """The double a Real*4 written with `value` reads back as (the writer's rounding)."""
    return struct.unpack(">f", struct.pack(">f", value))[0]


def _translate(name: str, clock=None) -> list[dict]:
    adapter = Nexrad2Adapter(clock=clock or times.frozen_clock())
    return [
        o.model_dump(mode="json") for o in adapter.to_cdm((FIXTURES / f"{name}.ar2v").read_bytes())
    ]


def _twin(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.parsed.json").read_text(encoding="utf-8"))


def _refusal(payload) -> Nexrad2Refused:
    with pytest.raises(Nexrad2Refused) as raised:
        Nexrad2Adapter(clock=times.frozen_clock()).to_cdm(payload)
    return raised.value


def _observation(obj: dict) -> dict:
    return obj["payload"]["observation"]


def _flags(obj: dict) -> list[tuple]:
    return [
        (f["name"], f["value"], f["namespace"], f["applies_to"])
        for f in _observation(obj)["quality_flags"]
    ]


# ================================================================== the declaration


def test_the_adapter_is_registered_and_declares_what_the_round_ruled():
    cls = discover()["nexrad2"]
    assert cls is Nexrad2Adapter
    assert (cls.name, cls.version, cls.direction, cls.system) == (
        "nexrad2",
        "1.0.0",
        "ingest",
        "NEXRAD",
    )
    assert nexrad2.__doc__.splitlines()[0] == (
        "`nexrad2`, #25 in the ordinal table: one NEXRAD Level II volume -> CDM, ingest only."
    )
    meta = cls.metadata
    assert (
        meta.format.name,
        meta.format.version,
        meta.binding.value,
        meta.license_class.value,
        meta.maturity.level.value,
        meta.claim_status.value,
        meta.residual.value,
    ) == (
        "NEXRAD Level II (Archive II)",
        "ICD 2620010J (Archive II/User) and ICD 2620002Y (RDA/RPG), Build 23.0",
        "standard-encoding",
        "PUBLIC_GOVERNMENT",
        "L3",
        "VERIFIED",
        "structured",
    )
    limits = meta.capabilities.limits
    # U-07: one volume <= 32 MiB; the ICD ceilings: 325,888 + 192 x 2 MiB; Table XVII-A's 32
    # elevation numbers and the site; the twin's seven levels under the dis7 envelope's 16.
    assert (
        limits.max_input_bytes,
        limits.max_depth,
        limits.max_objects,
        limits.max_decompressed_bytes,
        limits.max_parse_seconds,
    ) == (33554432, 16, 33, 325888 + 192 * 2097152, None)
    assert 325888 + 192 * 2097152 == 402979072
    assert sorted(limits.absent_because) == ["max_parse_seconds"]
    assert sorted(limits.declared_because) == [
        "max_decompressed_bytes",
        "max_depth",
        "max_input_bytes",
        "max_objects",
    ]
    for field in ("max_input_bytes", "max_decompressed_bytes", "max_depth"):
        basis = limits.declared_because[field]
        assert basis.kind is LimitKind.IMPLEMENTATION_CAP, field
        assert basis.source.endswith(
            "This is an IMPLEMENTATION CAP and is NOT the format's normative maximum."
        ), field
    objects = limits.declared_because["max_objects"]
    assert objects.kind is LimitKind.NORMATIVE
    assert "Table XVII-A" in objects.source and "range 1 to 32" in objects.source
    # Each bound quotes the figure it rests on.
    assert "3,601,535 to 8,908,516 octets" in limits.declared_because["max_input_bytes"].source
    assert "research-nexrad-level2 F03" in limits.declared_because["max_input_bytes"].source
    decompressed = limits.declared_because["max_decompressed_bytes"].source
    assert "325,888" in decompressed and "<= 1.72 MB" in decompressed
    assert "402,979,072" in decompressed and "F03/F12" in decompressed
    for field, basis in limits.declared_because.items():
        module, _, test = basis.test.partition("::")
        if module == "tests/test_cdm_nexrad2_adapter.py":
            assert callable(globals().get(test)), (field, test)
    record = nexrad2.MAX_RECORD_BYTES_BASIS
    assert (nexrad2.MAX_RECORD_BYTES, record.kind) == (2097152, LimitKind.IMPLEMENTATION_CAP)
    assert "1,718,880" in record.source and callable(globals()[record.test.split("::")[1]])
    assert meta.capabilities.unknown_fields is UnknownFields.NONE
    assert [lim.id for lim in meta.limitations] == [
        "values-by-reference",
        "volume-octets-by-reference",
        "one-volume-per-call",
        "messages-refused-by-name",
        "metadata-not-decoded",
        "geometry-is-the-site",
        "strict-icd-ranges",
        "zdr-bias-unscaled",
        "evidence-availability",
    ]
    assert [(lim.id, lim.unsupported_paths) for lim in meta.limitations[:2]] == [
        ("values-by-reference", ["gates"]),
        ("volume-octets-by-reference", ["wire_hex"]),
    ]


def test_the_ledger_binds_the_volume_to_the_site_and_each_sweep_to_its_own_event():
    mappings = Nexrad2Adapter.MAPPINGS
    assert list(mappings) == [
        "volume_header.icao",
        "volume_header",
        "site.latitude",
        "site.longitude",
        "site.site_height",
        "site",
        "records",
        "sweeps[*].elevation_number",
        "sweeps[*]",
    ]
    assert [m.to for m in mappings["volume_header.icao"]] == [
        "entity:residual.data.volume_header.icao",
        "entity:source_ids[0].external_id",
    ]
    assert [(m.to, m.rule) for m in mappings["site.site_height"]] == [
        ("entity:residual.data.site.site_height", "identity"),
        ("entity:position.vertical.value", "number"),
    ]
    assert (mappings["sweeps[*]"].to, mappings["sweeps[*]"].kind) == (
        "#[*]:residual.data",
        "residual",
    )
    assert sorted(Nexrad2Adapter.TRANSFORMS) == ["gates", "wire_hex"]
    assert all(r.startswith("derived: ") for r in Nexrad2Adapter.TRANSFORMS.values())


@pytest.mark.parametrize("name", CASES)
def test_every_twin_leaf_is_mapped_parked_or_a_declared_limitation(name):
    from synapse_cdm import lossless, manifest

    twin = _twin(name)
    dumped = Nexrad2Adapter(clock=times.frozen_clock()).to_cdm(twin)
    book = lossless.ledger(
        twin,
        [o.model_dump(mode="json") for o in dumped],
        Nexrad2Adapter.MAPPINGS,
        unsupported=manifest.unsupported_paths(Nexrad2Adapter.metadata.limitations),
    )
    assert book.lost == ()
    counts = book.counts
    assert counts["LOST"] == 0 and counts["MAPPED"] >= 5
    # The gate runs and the octets, and nothing else, are the declared limitation.
    limited = {
        e.source_path.split("[")[0].split(".")[0]
        for e in book.entries
        if e.category == "DECLARED_LIMITATION"
    }
    assert limited == {"gates", "wire_hex"}


# ================================================================== the fixture set


def test_the_fixture_set_is_listed_synthetic_and_paired_with_its_twins():
    assert CASES == [
        "all_moments_one_elevation",
        "coded_gates_and_bad_radial",
        "one_sweep_across_two_records",
        "sails_repeated_lowest_angle",
        "two_elevations_two_records",
    ]
    assert support.provenance_problems(FIXTURES) == []
    assert support.twin_problems(FIXTURES) == []
    assert sorted(p.name for p in MALFORMED.glob("*.ar2v")) == sorted(
        f"{name}.ar2v" for name in MALFORMED_REFUSALS
    )


def test_the_builder_check_is_current_and_writes_nothing(tmp_path):
    assert support.builder_problems(FIXTURES, tmp_path) == []


@pytest.mark.parametrize("name", CASES)
def test_every_site_and_position_follows_the_identifier_convention(name):
    twin = _twin(name)
    assert support.radar_site_problems(twin["volume_header"]["icao"]) == []
    site = twin["site"]
    assert (
        support.positions_outside_the_rectangle({"lat": site["latitude"], "lon": site["longitude"]})
        == []
    )
    assert support.positions_outside_the_rectangle(_translate(name)) == []


@pytest.mark.parametrize("name", CASES)
def test_the_decode_of_each_volume_is_the_twin_its_builder_wrote(name):
    """The twin is written by the builder from the literals it encoded; the adapter's decode of
    the octets must be exactly it, type for type."""
    octets = (FIXTURES / f"{name}.ar2v").read_bytes()
    twin = _twin(name)
    assert twin["wire_hex"] == octets.hex()
    assert json.dumps(nexrad2.twin_of(octets), sort_keys=True) == json.dumps(twin, sort_keys=True)


@pytest.mark.parametrize("name", CASES)
def test_the_octets_and_the_twin_translate_to_one_result(name):
    twin_objects = [
        o.model_dump(mode="json")
        for o in Nexrad2Adapter(clock=times.frozen_clock()).to_cdm(_twin(name))
    ]
    assert twin_objects == _translate(name)


@pytest.mark.parametrize("name", CASES)
def test_the_two_goldens_of_a_pair_are_one_translation(name):
    payload = json.loads((GOLDEN / f"{name}.cdm.json").read_text())
    twin = json.loads((GOLDEN / f"{name}.parsed.cdm.json").read_text())
    assert payload == twin == _translate(name)


# ================================================================== one volume, by hand


#: Table XVII-I's typical values, as the builder writes them: gates, word size, scale, offset.
TYPICAL = {
    "REF": (1840, 8, 2.0, 66.0),
    "VEL": (1200, 8, 2.0, 129.0),
    "SW": (1200, 8, 2.0, 129.0),
    "ZDR": (1200, 16, 32.0, 418.0),
    "PHI": (1200, 16, _f32(2.8361), 2.0),
    "RHO": (1200, 8, 300.0, -60.5),
    "CFP": (1840, 8, 1.0, 8.0),
}
UNITS = {
    "REF": "dBZ",
    "VEL": "m/s",
    "SW": "m/s",
    "ZDR": "dB",
    "PHI": "deg",
    "RHO": "N/A",
    "CFP": "dB",
}


def _locator(record: int, message: int, elevation: int, moment=None) -> dict:
    return {
        "frame_sha256": None,
        "granule_id": None,
        "kind": "radar",
        "ldm_record": record,
        "message": message,
        "elevation_number": elevation,
        "azimuth_number": None,
        "moment": moment,
    }


def _moment(
    name,
    radials,
    missing,
    low,
    high,
    *,
    record=1,
    message=0,
    elevation=1,
    scale="typical",
    offset="typical",
):
    gates, word, typical_scale, typical_offset = TYPICAL[name]
    begins = 8 if name == "CFP" else 2
    return {
        "name": name,
        "namespace": f"{ICD} Table XVII-I",
        "unit": {"unit": UNITS[name], "unit_namespace": f"{ICD} Table XVII-I"},
        "gate_count": gates,
        "first_gate_range": {"value": 2.125, "unit": "km", "unit_namespace": f"{ICD} Table XVII-B"},
        "gate_interval": {"value": 0.25, "unit": "km", "unit_namespace": f"{ICD} Table XVII-B"},
        "values": {
            "mode": "reference",
            "locator": _locator(record, message, elevation, name),
            "shape": [radials, gates],
            "dtype": f"Integer*{word // 8}",
            "encoding": (
                f"{ICD} Table XVII-B: each radial's {gates} gate words of {word} bits in its data "
                "moment block, inside the volume's bzip2 LDM records; F = (N - OFFSET) / SCALE "
                f"with the block's own scale and offset (note 15, 20); N below {begins} is a "
                "coded value, not a measurement; the summary's min and max are F in the "
                "moment's unit and missing_count counts the coded gates"
            ),
            "scale": typical_scale if scale == "typical" else scale,
            "offset": typical_offset if offset == "typical" else offset,
            "fill": None,
            "summary": {
                "count": radials * gates,
                "missing_count": missing,
                "min": low,
                "max": high,
            },
        },
    }


def _moment_flags(name, coded: dict, tover=5.0, snr=2.0, control=0) -> list[tuple]:
    if name == "CFP":
        names = (
            "filter_not_applied_count",
            "point_clutter_filter_count",
            "dual_pol_only_filtered_count",
            "reserved_code_count",
        )
        note = "note 30"
    else:
        names = ("below_threshold_count", "range_folded_count")
        note = "note 21"
    return [(n, coded.get(n, 0), f"{ICD} Table XVII-I {note}", name) for n in names] + [
        ("tover_db", tover, f"{ICD} Table XVII-B", name),
        ("snr_threshold_db", snr, f"{ICD} Table XVII-B", name),
        ("control_flags", control, f"{ICD} Table XVII-B", name),
    ]


#: The VOL, ELV and RAD constants every builder radial states unless a case changes them, in
#: their units: dBZ0 -44.625, Tx powers 312.5 kW, system ZDR 0.25 dB, initial PHIDP 60 deg, VCP
#: 212, processing status 0, ZDR bias 3 as stated, ATMOS -12/1000, ELV dBZ0 -44.375, unambiguous
#: range 1150/10 km, noise -80.5 and -80.25 dBm, Nyquist 2875/100 m/s, flags 0, calibration
#: -44.5 and -44.75 dBZ.
def _constant_flags(**over) -> list[tuple]:
    rows = [
        ("vol_dbz0_db", -44.625, "Table XVII-E"),
        ("horizontal_tx_power_kw", 312.5, "Table XVII-E"),
        ("vertical_tx_power_kw", 312.5, "Table XVII-E"),
        ("system_zdr_db", 0.25, "Table XVII-E"),
        ("initial_system_phidp_deg", 60.0, "Table XVII-E"),
        ("vcp_number", 212, "Table XVII-E"),
        ("processing_status", 0, "Table XVII-E"),
        ("zdr_bias_estimate_raw", 3, "Table XVII-E"),
        ("atmospheric_attenuation_db_per_km", -0.012, "Table XVII-F"),
        ("elv_dbz0_db", -44.375, "Table XVII-F"),
        ("unambiguous_range_km", 115.0, "Table XVII-H"),
        ("noise_level_h_dbm", -80.5, "Table XVII-H"),
        ("noise_level_v_dbm", -80.25, "Table XVII-H"),
        ("nyquist_velocity_mps", 28.75, "Table XVII-H"),
        ("radial_flags", 0, "Table XVII-H"),
        ("calibration_dbz0_h_dbz", -44.5, "Table XVII-H"),
        ("calibration_dbz0_v_dbz", -44.75, "Table XVII-H"),
    ]
    return [(name, over.get(name, value), f"{ICD} {table}", "sweep") for name, value, table in rows]


def _status_flags(statuses: list[int], spot=0, bad=0) -> list[tuple]:
    rows = [("bad_data_radial_count", bad, f"{ICD} Table III-C", "sweep")]
    rows += [
        ("radial_status", status, f"{ICD} Table III-C", f"radial {az}")
        for az, status in enumerate(statuses, start=1)
    ]
    rows.append(("spot_blanking", spot, f"{ICD} Table XVII-A", "sweep"))
    return rows


#: The default gates of every builder radial: one code 0 and one code 1, then a constant: REF 130
#: -> (130 - 66) / 2 = 32.0 dBZ, VEL 129 -> 0.0, SW 131 -> 1.0, ZDR 418 -> 0.0, PHI 600 ->
#: 598 / 2.8361, RHO 255 -> (255 + 60.5) / 300, CFP all 8 -> 0.0 (note 30: data begins at 8).
DEFAULT_F = {
    "REF": (130 - 66.0) / 2.0,
    "VEL": (129 - 129.0) / 2.0,
    "SW": (131 - 129.0) / 2.0,
    "ZDR": (418 - 418.0) / 32.0,
    "PHI": (600 - 2.0) / _f32(2.8361),
    "RHO": (255 - (-60.5)) / 300.0,
    "CFP": (8 - 8.0) / 1.0,
}


def _default_sweep(radials: int, *, record=1, message=0, elevation=1) -> tuple[list, list]:
    moments, flags = [], []
    for name in ("REF", "VEL", "SW", "ZDR", "PHI", "RHO", "CFP"):
        missing = 0 if name == "CFP" else 2 * radials
        f = DEFAULT_F[name]
        moments.append(
            _moment(
                name, radials, missing, f, f, record=record, message=message, elevation=elevation
            )
        )
        coded = (
            {}
            if name == "CFP"
            else {"below_threshold_count": radials, "range_folded_count": radials}
        )
        flags += _moment_flags(name, coded)
    return moments, flags


def test_the_all_moments_volume_becomes_one_sweep_and_its_site_as_written_by_hand():
    objects = _translate("all_moments_one_elevation")
    assert [o["object_kind"] for o in objects] == ["event", "entity"]
    event, entity = objects
    site_id = _uuid("entity", "NEXRAD", "ZZZZ")
    # MJD 20573 is 2026-04-29 (1970-01-01 is day 1); 22,200,000 ms is 06:10:00.000.
    assert (dt.date(1970, 1, 1) + dt.timedelta(days=20573 - 1)).isoformat() == "2026-04-29"
    start, last = "2026-04-29T06:10:00.000Z", "2026-04-29T06:10:00.027Z"
    stamp = {
        "system": "NEXRAD",
        "adapter": "nexrad2",
        "adapter_version": "1.0.0",
        "synthetic": True,
        "format_name": "NEXRAD Level II (Archive II)",
        "format_version": "ICD 2620010J (Archive II/User) and ICD 2620002Y (RDA/RPG), Build 23.0",
        "original_id": "AR2V0006.001",
        "source_hash": None,
        "observed_at": start,
    }
    assert {k: entity["source"][k] for k in stamp} == stamp
    assert entity["source"]["record_index"] is None
    assert entity["source"]["transformations"] == [nexrad2.T_VOLUME_INSTANT]
    assert entity["entity_id"] == site_id
    assert entity["source_ids"] == [{"system": "NEXRAD", "external_id": "ZZZZ"}]
    assert (entity["entity_type"], entity["affiliation"], entity["valid_from"]) == (
        "SENSOR",
        "UNKNOWN",
        start,
    )
    assert entity["position"] == {
        "lat": 57.25,
        "lon": 22.5,
        "alt_m": None,
        "position_source": "MANUAL",
        "accuracy_m": None,
        "vertical": {"value": 120.0, "unit": "m", "reference": "MSL", "uncertainty": None},
    }
    assert entity["attributes"] == {
        "site_class": "radar_site",
        "position_basis": (
            "the VOL data block (ICD 2620002Y Table XVII-E) every radial of the volume states "
            "alike: latitude and longitude in degrees"
        ),
        "vertical_basis": (
            "the VOL block's Site Height, the height of the site base above mean sea level in "
            "metres (ICD 2620002Y Table XVII-E); alt_m is metres above the ellipsoid and this is "
            "not one, and the tower height stays in the residual"
        ),
        "valid_from_basis": (
            "the volume header's start of the volume (ICD 2620010J Figure 1: the date and time "
            "of the start volume radial, from the RDA)"
        ),
    }
    twin = _twin("all_moments_one_elevation")
    assert entity["residual"] == {
        "namespace": "NEXRAD Level II (Archive II)",
        "data": {k: twin[k] for k in ("volume_header", "site", "records")},
    }
    assert twin["volume_header"] == {
        "tape": "AR2V0006.",
        "extension": "001",
        "julian_date": 20573,
        "milliseconds": 22200000,
        "icao": "ZZZZ",
    }
    assert twin["site"] == {
        "latitude": 57.25,
        "longitude": 22.5,
        "site_height": 120,
        "tower_height": 30,
    }
    # 7.3.5: 15 x 77, 32, 13 x 48, 18 x 5, 3, 5, 2; each message's first segment typed, the
    # rest type 0: 76 + 47 + 4 = 127 zeros.
    metadata = twin["records"][0]
    assert (metadata["decompressed_bytes"], metadata["messages"], metadata["message_types"]) == (
        325888,
        134,
        {"0": 127, "2": 1, "3": 1, "5": 1, "13": 1, "15": 1, "18": 1, "32": 1},
    )
    assert (twin["records"][1]["messages"], twin["records"][1]["message_types"]) == (2, {"31": 2})
    # One radial is 32 + 4 x 10 header octets, VOL 52, ELV 12, RAD 28, and seven moment blocks
    # of 28 octets plus REF 1840, VEL 1200, SW 1200, ZDR 2400, PHI 2400, RHO 1200, CFP 1840:
    # 12,440 octets, inside 9,360 to 14,296; its message is 16 + 12,440 octets = 6,228 halfwords.
    radial = twin["sweeps"][0]["radials"][0]
    assert 72 + 52 + 12 + 28 + 7 * 28 + 1840 + 1200 + 1200 + 2400 + 2400 + 1200 + 1840 == 12440
    assert (radial["radial_length"], radial["message_header"]["size"]) == (12440, 6228)

    assert (event["event_type"], event["severity"]) == ("ENVIRONMENTAL_OBSERVATION", "INFO")
    assert event["event_id"] == _uuid("event", "NEXRAD", f"ZZZZ/{start}/elevation 1")
    assert event["source_ids"] == [{"system": "NEXRAD", "external_id": f"ZZZZ/{start}/elevation 1"}]
    assert {k: event["source"][k] for k in stamp} == stamp
    assert event["source"]["record_index"] == 1
    assert event["source"]["transformations"] == [
        nexrad2.T_VOLUME_INSTANT,
        nexrad2.T_COLLECTION_INSTANT,
        nexrad2.T_SCALED,
        nexrad2.T_GATES,
        nexrad2.T_NAME,
    ]
    assert (event["observed_at"], event["received_at"]) == (last, FROZEN)
    assert event["validity"] == {
        "observed_at": None,
        "valid_from": None,
        "valid_to": None,
        "effective": {"start": start, "end": last},
    }
    assert event["related_entities"] == [site_id]
    assert event["geometry"] == {"type": "Point", "coordinates": [22.5, 57.25]}
    assert event["quality"] == {
        "source_quality": None,
        "confidence": None,
        "accuracy_m": None,
        "uncertainty": {"collection_time_accuracy_s": 2.0},
    }
    assert list(event["payload"]) == ["observation"]
    assert event["residual"] == {
        "namespace": "NEXRAD Level II (Archive II)",
        "data": twin["sweeps"][0],
    }
    moments, moment_flags = _default_sweep(2)
    assert _observation(event) == {
        "contract": "radar-sweep/1",
        "product_class": "observation",
        "product_version": {
            "run": None,
            "version": "AR2V0006.",
            "production_time_verbatim": None,
            "producer": None,
        },
        "time": {
            "source_time_system": {
                "name": "GMT",
                "stated_by": "source",
                "basis": (
                    "ICD 2620002Y Table XVII-A: Collection Time is milliseconds past midnight "
                    "GMT, with the Modified Julian Date (1 = 1970-01-01)"
                ),
            },
            "reference_time": None,
            "reference_time_significance": None,
            "forecast_offset": None,
            "statistical_process": None,
        },
        "locator": _locator(1, 0, 1),
        "quality_flags": [
            {"name": n, "value": v, "namespace": ns, "applies_to": a}
            for n, v, ns, a in moment_flags + _status_flags([3, 4]) + _constant_flags()
        ],
        "quality_flags_basis": None,
        "site_id": "ZZZZ",
        "elevation_number": 1,
        "elevation_angle": {"value": 0.5, "unit": "deg", "unit_namespace": f"{ICD} Table XVII-A"},
        "radial_count": 2,
        "coverage_pattern": {
            "code": "212",
            "namespace": f"{ICD} Table XVII-E, Volume Coverage Pattern Number",
            "meaning": None,
        },
        "moments": moments,
    }
    # The contract the Event carries validates as radar-sweep/1.
    assert type(oc.parse_observation(_observation(event))) is oc.RadarSweep


def test_two_elevations_in_two_records_are_two_sweeps_with_their_own_locators_and_constants():
    objects = _translate("two_elevations_two_records")
    assert [o["object_kind"] for o in objects] == ["event", "event", "entity"]
    first, second, entity = objects
    start = "2026-04-29T06:10:00.000Z"
    assert [_observation(o)["elevation_number"] for o in (first, second)] == [1, 2]
    assert [o["event_id"] for o in (first, second)] == [
        _uuid("event", "NEXRAD", f"ZZZZ/{start}/elevation 1"),
        _uuid("event", "NEXRAD", f"ZZZZ/{start}/elevation 2"),
    ]
    # Elevation 1: radials at +0 and +0.5 s; elevation 2 at +12.0 and +12.25 s.
    assert [(o["validity"]["effective"], o["observed_at"]) for o in (first, second)] == [
        ({"start": start, "end": "2026-04-29T06:10:00.500Z"}, "2026-04-29T06:10:00.500Z"),
        (
            {"start": "2026-04-29T06:10:12.000Z", "end": "2026-04-29T06:10:12.250Z"},
            "2026-04-29T06:10:12.250Z",
        ),
    ]
    assert [o["source"]["record_index"] for o in (first, second)] == [1, 2]
    assert _observation(first)["locator"] == _locator(1, 0, 1)
    assert _observation(second)["locator"] == _locator(2, 0, 2)
    assert [m["values"]["locator"] for m in _observation(second)["moments"]] == [
        _locator(2, 0, 2, name) for name in ("REF", "VEL", "SW", "ZDR", "PHI", "RHO", "CFP")
    ]
    # The status message (type 2) is message 1 of record 1, so the second radial is message 2.
    radials = first["residual"]["data"]["radials"]
    assert [(r["ldm_record"], r["message"]) for r in radials] == [(1, 0), (1, 2)]
    records = entity["residual"]["data"]["records"]
    assert [r["message_types"] for r in records[1:]] == [{"2": 1, "31": 2}, {"31": 2}]
    # 7.3.4: the second radial record's control word was written negative; its absolute value
    # is the stream's size.
    assert records[2]["control_word"] == -records[2]["compressed_bytes"] < 0
    assert records[1]["control_word"] == records[1]["compressed_bytes"] > 0
    # Elevation 2 states another unambiguous range (1750 -> 175.0 km) and Nyquist velocity
    # (2650 -> 26.5 m/s) and a 1.0-degree azimuth spacing.
    assert _flags(second)[-17:] == _constant_flags(
        unambiguous_range_km=175.0, nyquist_velocity_mps=26.5
    )
    assert _flags(first)[-17:] == _constant_flags()
    assert [r["azimuth_spacing"] for r in second["residual"]["data"]["radials"]] == [2, 2]
    assert _flags(second)[37:41] == _status_flags([0, 4])


def test_a_rescanned_lowest_angle_is_three_sweeps_by_number_and_never_merged_by_angle():
    objects = _translate("sails_repeated_lowest_angle")
    assert [o["object_kind"] for o in objects] == ["event", "event", "event", "entity"]
    sweeps = [_observation(o) for o in objects[:3]]
    assert [(s["elevation_number"], s["elevation_angle"]["value"]) for s in sweeps] == [
        (1, 0.5),
        (2, 0.875),
        (3, 0.5),
    ]
    start = "2026-04-29T06:10:00.000Z"
    assert [o["event_id"] for o in objects[:3]] == [
        _uuid("event", "NEXRAD", f"XZZA/{start}/elevation {n}") for n in (1, 2, 3)
    ]
    assert len({o["event_id"] for o in objects[:3]}) == 3
    assert [o["observed_at"] for o in objects[:3]] == [
        "2026-04-29T06:10:00.030Z",
        "2026-04-29T06:10:20.030Z",
        "2026-04-29T06:10:40.030Z",
    ]
    entity = objects[3]
    assert entity["entity_id"] == _uuid("entity", "NEXRAD", "XZZA")
    # Site height -5 m is a stated height below mean sea level, carried as such.
    assert entity["position"] == {
        "lat": 56.75,
        "lon": 21.25,
        "alt_m": None,
        "position_source": "MANUAL",
        "accuracy_m": None,
        "vertical": {"value": -5.0, "unit": "m", "reference": "MSL", "uncertainty": None},
    }
    assert entity["source"]["original_id"] == "AR2V0007.002"
    assert [s["product_version"]["version"] for s in sweeps] == ["AR2V0007."] * 3
    # Status 5 starts the last elevation of the VCP (Table III-C).
    assert [_flags(o)[37:41] for o in objects[:3]] == [
        _status_flags([3, 2]),
        _status_flags([0, 2]),
        _status_flags([5, 4]),
    ]


def test_coded_gates_stay_distinct_and_a_bad_radial_and_a_changing_scale_are_stated():
    objects = _translate("coded_gates_and_bad_radial")
    event = objects[0]
    observation = _observation(event)
    moments = {m["name"]: m for m in observation["moments"]}
    # REF: radial 1 has five 0s, three 1s, a 2 and 130s; radial 2 seven 1s and 255s; radial 3
    # two 0s and 100s. Below threshold 5 + 2 = 7, range folded 3 + 7 = 10: two counts, never one.
    # Data: 2 -> -32.0, 130 -> 32.0, 255 -> 94.5, 100 -> 17.0 dBZ.
    assert moments["REF"] == _moment("REF", 3, 17, (2 - 66.0) / 2, (255 - 66.0) / 2)
    assert ((2 - 66.0) / 2, (255 - 66.0) / 2) == (-32.0, 94.5)
    # VEL: radial 1 four 1s, 127s and 131s at scale 2; radial 2 two 0s and 129s; radial 3 129s
    # at scale 1 (note 20: a scale may change from radial to radial). One scale is not stated,
    # and the extremes are each radial's codes with its own scale: -1.0 and 1.0 m/s.
    assert moments["VEL"] == _moment("VEL", 3, 6, (127 - 129.0) / 2, (131 - 129.0) / 2, scale=None)
    # CFP: radial 1 states note 30's codes 0 (x2), 1 (x3), 2 (x4), 3 and 7 (reserved, x2).
    assert moments["CFP"] == _moment("CFP", 3, 11, 0.0, 0.0)
    flags = _flags(event)
    assert flags[:5] == _moment_flags("REF", {"below_threshold_count": 7, "range_folded_count": 10})
    assert flags[5:10] == _moment_flags(
        "VEL", {"below_threshold_count": 2, "range_folded_count": 4}
    )
    assert flags[30:37] == _moment_flags(
        "CFP",
        {
            "filter_not_applied_count": 2,
            "point_clutter_filter_count": 3,
            "dual_pol_only_filtered_count": 4,
            "reserved_code_count": 2,
        },
    )
    # Radial 2's status is 0x81: intermediate radial, bad data (Table III-C). Spot blanking is
    # 6, 6, 7 (note 8: 7 = this radial spot blanked), so it is stated per radial.
    assert flags[37:44] == [
        ("bad_data_radial_count", 1, f"{ICD} Table III-C", "sweep"),
        ("radial_status", 3, f"{ICD} Table III-C", "radial 1"),
        ("radial_status", 0x81, f"{ICD} Table III-C", "radial 2"),
        ("radial_status", 4, f"{ICD} Table III-C", "radial 3"),
        ("spot_blanking", 6, f"{ICD} Table XVII-A", "radial 1"),
        ("spot_blanking", 6, f"{ICD} Table XVII-A", "radial 2"),
        ("spot_blanking", 7, f"{ICD} Table XVII-A", "radial 3"),
    ]
    assert flags[44:] == _constant_flags()
    # The antenna's angle differs per radial (0.4921875, 0.5, 0.5078125), so no one angle.
    assert observation["elevation_angle"] is None
    assert [r["elevation_angle"] for r in event["residual"]["data"]["radials"]] == [
        0.4921875,
        0.5,
        0.5078125,
    ]


def test_a_sweep_across_two_records_is_located_at_its_first_radial():
    objects = _translate("one_sweep_across_two_records")
    assert [o["object_kind"] for o in objects] == ["event", "entity"]
    event = objects[0]
    observation = _observation(event)
    assert (observation["radial_count"], observation["locator"]) == (3, _locator(1, 0, 1))
    assert event["source"]["record_index"] == 1
    assert [(r["ldm_record"], r["message"]) for r in event["residual"]["data"]["radials"]] == [
        (1, 0),
        (1, 1),
        (2, 0),
    ]
    assert observation["moments"][0]["values"]["shape"] == [3, 1840]


def test_the_injected_digests_reach_the_stamp_and_every_locator():
    digest, frame = "a" * 64, "b" * 64
    adapter = Nexrad2Adapter(
        times.frozen_clock(),
        source_hash={"algorithm": "sha256", "value": digest},
        frame_sha256=frame,
    )
    objects = [
        o.model_dump(mode="json")
        for o in adapter.to_cdm((FIXTURES / "two_elevations_two_records.ar2v").read_bytes())
    ]
    assert [o["source"]["source_hash"] for o in objects] == [
        {"algorithm": "sha256", "value": digest}
    ] * 3
    locators = [
        loc
        for o in objects[:2]
        for loc in [_observation(o)["locator"]]
        + [m["values"]["locator"] for m in _observation(o)["moments"]]
    ]
    assert len(locators) == 16 and {loc["frame_sha256"] for loc in locators} == {frame}
    for bad in (
        {"source_hash": {"algorithm": "md5", "value": digest}},
        {"source_hash": {"algorithm": "sha256", "value": "A" * 64}},
        {"frame_sha256": "b" * 63},
        {"frame_sha256": b"b" * 64},
    ):
        with pytest.raises((ValueError, ValidationError)):
            Nexrad2Adapter(times.frozen_clock(), **bad)


def test_the_receipt_clock_reaches_received_at_and_nothing_else():
    later = times.frozen_clock(dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc))
    for name in CASES:
        a, b = _translate(name), _translate(name, later)
        for x, y in zip(a, b):
            if x["object_kind"] == "event":
                assert y["received_at"] == "2026-05-01T00:00:00.000Z"
                x = {**x, "received_at": None}
                y = {**y, "received_at": None}
            assert x == y


def test_thirty_two_elevations_are_thirty_three_objects():
    radials = [
        (
            "radial",
            BUILDER.radial(
                elevation=n, azimuth=1, angle=0.25, status=0, ms=BUILDER._ms(n), elevation_angle=0.5
            ),
        )
        for n in range(1, 33)
    ]
    octets, _ = BUILDER.build_volume({"icao": "ZZZZ", "site": BUILDER.SITE, "records": [radials]})
    objects = Nexrad2Adapter(times.frozen_clock()).to_cdm(octets)
    assert len(objects) == 33 == Nexrad2Adapter.metadata.capabilities.limits.max_objects
    assert [o.payload["observation"]["elevation_number"] for o in objects[:32]] == list(
        range(1, 33)
    )
    over = BUILDER.radial(
        elevation=33, azimuth=1, angle=0.25, status=0, ms=BUILDER._ms(33), elevation_angle=0.5
    )
    octets, _ = BUILDER.build_volume(
        {"icao": "ZZZZ", "site": BUILDER.SITE, "records": [radials[:1] + [("radial", over)]]}
    )
    refusal = _refusal(octets)
    assert (refusal.code, str(refusal)) == (
        "elevation-number-out-of-range",
        "elevation-number-out-of-range: LDM record 1, message 1: Elevation Number is not a "
        "finite value in 1 to 32 (ICD 2620002Y)",
    )


# ================================================================== the bounds


def test_the_volume_is_held_to_its_decompression_bound_at_the_octet():
    """`decode_volume`'s `limit` is `max_decompressed_bytes`; lowered here to this volume's own
    total so the bound is exercised at the octet without inflating 384 MiB."""
    octets = (FIXTURES / "all_moments_one_elevation.ar2v").read_bytes()
    twin = _twin("all_moments_one_elevation")
    total = sum(r["decompressed_bytes"] for r in twin["records"])
    # The metadata record's 325,888 octets and two radial messages of 12 + 12,456 octets each.
    assert total == 325888 + 2 * (12 + 16 + 12440)
    nexrad2.decode_volume(octets, limit=total)
    with pytest.raises(Nexrad2Refused) as raised:
        nexrad2.decode_volume(octets, limit=total - 1)
    assert str(raised.value) == (
        f"decompresses-past-the-bound: the volume decompresses past max_decompressed_bytes = "
        f"{total - 1} octets in LDM record 1; refused before the octet past the bound was kept"
    )
    assert nexrad2.MAX_DECOMPRESSED_BYTES == 402979072


def test_a_record_is_held_to_its_own_bound_and_the_metadata_record_to_its_size():
    header = (FIXTURES / "all_moments_one_elevation.ar2v").read_bytes()[:24]
    metadata, _ = BUILDER.metadata_record(BUILDER.START_MS)
    meta_record = BUILDER.ldm_record(metadata)[0]
    status = BUILDER.fixed_segment(2, 135, BUILDER.START_MS)
    # 862 status segments are 2,096,384 octets, inside the 2 MiB record bound; 863 are not.
    at_bound = BUILDER.ldm_record(status * 862)[0]
    past = BUILDER.ldm_record(status * 863)[0]
    assert 862 * 2432 <= 2097152 < 863 * 2432
    refusal = _refusal(header + meta_record + at_bound)
    assert refusal.code == "no-radial"
    refusal = _refusal(header + meta_record + past)
    assert str(refusal) == (
        "record-past-its-bound: LDM record 1 decompresses past 2097152 octets, the bound on one "
        "radial record"
    )
    short = BUILDER.ldm_record(metadata[:-2432])[0]
    refusal = _refusal(header + short)
    assert str(refusal) == (
        "metadata-record-size: LDM record 0, the metadata record, is not 325888 octets "
        "(ICD 2620010J 7.3.5: 134 segments of 2432)"
    )


def test_an_exhausted_volume_budget_is_the_volume_s_refusal_even_at_the_record_bound():
    """R3 review R3-r1-03 (2026-10-15): when the volume's budget left equals one record's bound,
    a record past it has exhausted the VOLUME, and the refusal says so. One octet more budget and
    the record's own bound is what it crosses."""
    header = (FIXTURES / "all_moments_one_elevation.ar2v").read_bytes()[:24]
    metadata, _ = BUILDER.metadata_record(BUILDER.START_MS)
    past = BUILDER.ldm_record(BUILDER.fixed_segment(2, 135, BUILDER.START_MS) * 863)[0]
    octets = header + BUILDER.ldm_record(metadata)[0] + past
    # After the metadata record's 325,888 octets, 2,097,152 are left: exactly one record's bound.
    assert 325888 + 2097152 == 2423040
    with pytest.raises(Nexrad2Refused) as raised:
        nexrad2.decode_volume(octets, limit=2423040)
    assert str(raised.value) == (
        "decompresses-past-the-bound: the volume decompresses past max_decompressed_bytes = "
        "2423040 octets in LDM record 1; refused before the octet past the bound was kept"
    )
    with pytest.raises(Nexrad2Refused) as raised:
        nexrad2.decode_volume(octets, limit=2423041)
    assert str(raised.value) == (
        "record-past-its-bound: LDM record 1 decompresses past 2097152 octets, the bound on one "
        "radial record"
    )


def test_table_xvii_i_data_ranges_are_not_rules_and_the_declarations_say_so():
    """R3 review R3-r1-01 (2026-10-15): a moment's codes outside Table XVII-I's data range are
    read, converted with the radial's own scale and offset, and summarised unchecked — the PHI
    block's range is 2 to 1023, and a run of 65535 gives (65535 - 2.0) / f32(2.8361) degrees.
    The docstring and the coverage section state it."""
    moments = BUILDER.every_moment(PHI=[[0, 1], [1, 1], [65535, 1198]])
    radial = BUILDER.radial(
        elevation=1, azimuth=1, angle=0.25, status=0, ms=BUILDER._ms(1), elevation_angle=0.5,
        moments=moments,
    )  # fmt: skip
    octets, _ = BUILDER.build_volume(
        {"icao": "ZZZZ", "site": BUILDER.SITE, "records": [[("radial", radial)]]}
    )
    sweep = Nexrad2Adapter(times.frozen_clock()).to_cdm(octets)[0].payload["observation"]
    phi = next(m for m in sweep["moments"] if m["name"] == "PHI")
    value = (65535 - 2.0) / _f32(2.8361)
    assert phi["values"]["summary"] == {
        "count": 1200,
        "max": value,
        "min": value,
        "missing_count": 2,
    }
    assert "Table XVII-I's data ranges are NOT" in nexrad2.__doc__
    assert "the summary that results is not range-checked" in " ".join(nexrad2.__doc__.split())
    # The Limitation's sentence (and the manifest and support-matrix row generated from it) is
    # not amended in this round: `manifests/nexrad2.json` is outside R4's allowed set (build
    # report, section 7).
    coverage = " ".join((PKG / "FORMAT_COVERAGE.md").read_text(encoding="utf-8").split())
    assert (
        "Every range ICD 2620002Y Tables XVII-A, -B, -E, -F and -H state for a field the adapter "
        "reads is a validation rule; Table XVII-I's data ranges are not rules, and a moment's "
        "summary is not range-checked (narrowed 2026-10-15)."
    ) in coverage


def test_a_twin_past_the_depth_bound_is_refused_before_decode():
    twin = _twin("all_moments_one_elevation")
    node: dict = {}
    for _ in range(16):
        node = {"n": node}
    twin["site"] = node
    with pytest.raises(InputTooDeep, match="max_depth = 16"):
        Nexrad2Adapter(times.frozen_clock()).to_cdm(twin)


def test_a_twin_is_held_to_its_own_wire_and_to_its_keys():
    twin = _twin("all_moments_one_elevation")
    cases = {
        "an extra key": ({**twin, "extra": 1}, "not-a-twin"),
        "a missing key": ({k: v for k, v in twin.items() if k != "gates"}, "not-a-twin"),
        "upper-case hex": ({**twin, "wire_hex": twin["wire_hex"].upper()}, "bad-wire-hex"),
        "odd hex": ({**twin, "wire_hex": twin["wire_hex"][:-1]}, "bad-wire-hex"),
        "hex with a space": ({**twin, "wire_hex": " " + twin["wire_hex"]}, "bad-wire-hex"),
        "hex past the bound": ({**twin, "wire_hex": "00" * (33554432 + 1)}, "bad-wire-hex"),
        "not text": ({**twin, "wire_hex": 7}, "bad-wire-hex"),
    }
    for label, (document, code) in cases.items():
        assert _refusal(document).code == code, label
    for key, change in (
        ("volume_header", ("julian_date", 20574)),
        ("site", ("tower_height", 31)),
        ("site", ("latitude", 57)),  # an int where the decode reads 57.25: a value and a type
    ):
        changed = copy.deepcopy(twin)
        changed[key][change[0]] = change[1]
        refusal = _refusal(changed)
        assert str(refusal) == (
            f"twin-disagrees: the twin's {key} is not what its wire_hex decodes to"
        )
    changed = copy.deepcopy(twin)
    changed["site"]["site_height"] = 120.0  # equal in Python, another JSON type
    assert _refusal(changed).code == "twin-disagrees"
    changed = copy.deepcopy(twin)
    changed["gates"][0]["runs"][0] = [0, 2]
    assert str(_refusal(changed)) == (
        "twin-disagrees: the twin's gates is not what its wire_hex decodes to"
    )
    assert _refusal("AR2V0006.").code == "unsupported-input"
    assert _refusal([twin]).code == "unsupported-input"


def test_a_refusal_is_a_value_error_that_survives_pickling():
    refusal = _refusal(b"AR2V0005.001" + bytes(12))
    assert isinstance(refusal, ValueError)
    again = pickle.loads(pickle.dumps(refusal))
    assert (type(again), again.code, str(again)) == (Nexrad2Refused, refusal.code, str(refusal))
    assert copy.copy(refusal).code == refusal.code


# ================================================================== refusals


#: Each malformed payload, its code and its whole text, written from the builder's description of
#: what is wrong with it (malformed/README.md).
MALFORMED_REFUSALS = {
    "truncated_record": (
        "record-past-the-end",
        "LDM record 1: the control word's absolute value runs past the end of the volume",
    ),
    "short_volume_header": (
        "short-volume-header",
        "the volume is shorter than the 24-octet volume header (ICD 2620010J Figure 1)",
    ),
    "bzip2_crc_corrupt": (
        "bzip2-corrupt",
        "LDM record 1: the bzip2 stream is corrupt or fails its CRC",
    ),
    "bzip2_stream_cut_short": (
        "truncated-bzip2",
        "LDM record 1: the bzip2 stream ends before its end-of-stream marker",
    ),
    "negative_control_word_past_the_file": (
        "record-past-the-end",
        "LDM record 0: the control word's absolute value runs past the end of the volume",
    ),
    "message_1_legacy_radial": (
        "message-1",
        "LDM record 1, message 0: message 1, the legacy digital radar data message, replaced by "
        "message 31 as of Build 10; this module does not decode it",
    ),
    "message_29_model_data_record": (
        "message-29",
        "LDM record 2, message 0: message 29, the model data of an _MDM record (ICD 2620010J "
        "7.3.4); this module does not decode it",
    ),
    "compression_indicator_bzip2": (
        "radial-bzip2-compressed",
        "LDM record 1, message 0: the Compression Indicator says the radial is compressed with "
        "bzip2, which this module does not read",
    ),
    "compression_indicator_zlib": (
        "radial-zlib-compressed",
        "LDM record 1, message 0: the Compression Indicator says the radial is compressed with "
        "zlib, which this module does not read",
    ),
    "radial_length_out_of_range": (
        "radial-length-out-of-range",
        "LDM record 1, message 0: Radial Length is not a finite value in 9360 to 14296 "
        "(ICD 2620002Y)",
    ),
    "decompresses_past_the_bound": (
        "decompresses-past-the-bound",
        "the volume decompresses past max_decompressed_bytes = 402979072 octets in LDM record "
        "193; refused before the octet past the bound was kept",
    ),
    "metadata_record_past_its_size": (
        "metadata-record-size",
        "LDM record 0, the metadata record, decompresses past 325888 octets; ICD 2620010J 7.3.5 "
        "fixes it at 134 segments",
    ),
    "azimuth_number_zero": (
        "azimuth-number-out-of-range",
        "LDM record 1, message 0: Azimuth Number is not a finite value in 1 to 720 (ICD 2620002Y)",
    ),
    "unexpected_message_type": (
        "unexpected-message-type",
        "LDM record 1, message 1: a message type where a radial (31) or an RDA status message "
        "(2) is required (ICD 2620010J 7.3.4)",
    ),
    "archive_version_05": (
        "unsupported-archive-version",
        "the tape name's version is not 06 or 07, the two ICD 2620010J Figure 1 says the RPG "
        "supports as of Build 17.0",
    ),
    "not_an_archive_ii_volume": (
        "not-archive-ii",
        "the octets do not begin with an Archive II tape name, AR2V00",
    ),
}


@pytest.mark.parametrize("name", sorted(MALFORMED_REFUSALS))
def test_each_malformed_volume_is_refused_with_its_code_and_its_whole_text(name):
    code, text = MALFORMED_REFUSALS[name]
    refusal = _refusal((MALFORMED / f"{name}.ar2v").read_bytes())
    assert (refusal.code, str(refusal)) == (code, f"{code}: {text}")


def test_the_status_flood_is_refused_in_its_last_record_and_not_before():
    """The decompression-bound fixture's arithmetic, by hand: 862 status segments of 2,432
    octets are 2,096,384 octets a record; 325,888 + 192 of them is 402,831,616, inside
    402,979,072, and the 193rd record would reach 404,928,000."""
    assert 862 * 2432 == 2096384
    assert 325888 + 192 * 2096384 == 402831616 <= 402979072
    assert 325888 + 193 * 2096384 == 404928000 > 402979072


def _volume(*records, version="06") -> bytes:
    """A volume of the builder's metadata record and these decompressed radial-record blobs."""
    header = (
        b"AR2V00"
        + version.encode()
        + b".001"
        + struct.pack(">II", BUILDER.MJD, BUILDER.START_MS)
        + b"ZZZZ"
    )
    metadata, _ = BUILDER.metadata_record(BUILDER.START_MS)
    return header + b"".join(BUILDER.ldm_record(blob)[0] for blob in (metadata, *records))


def _message(**over) -> bytes:
    """One message-31 radial from the builder's default radial with `over` applied."""
    site = over.pop("site", BUILDER.SITE)
    icao = over.pop("icao", "ZZZZ")
    defaults = dict(
        elevation=1, azimuth=1, angle=0.25, status=3, ms=BUILDER._ms(0), elevation_angle=0.5
    )
    for key in list(defaults):
        if key in over:
            defaults[key] = over.pop(key)
    r = BUILDER.radial(**defaults, **over)
    return BUILDER.message_31(BUILDER.radial_data(icao, site, r), 135, r["collection_time"])[0]


def _with(block: str, **over) -> dict:
    return getattr(BUILDER, block)(**over)


def _moments(name: str, **over) -> list:
    """The seven default moments with `over` applied to one of them."""
    moments = BUILDER.every_moment()
    for m in moments:
        if m["name"].strip() == name:
            m.update(over)
    return moments


_W = "LDM record 1, message 0"

#: (label, the radial's changes, code, text): one row per range ICD 2620002Y states for a field
#: the module reads, each just outside it, each written from the table it quotes.
RANGE_REFUSALS = [
    (
        "collection time past the day",
        {"ms": 86_400_000},
        "collection-time-out-of-range",
        f"{_W}: Collection Time is not a finite value in 0 to 86399999 (ICD 2620002Y)",
    ),
    (
        "modified julian date 0",
        {"julian_date": 0},
        "modified-julian-date-out-of-range",
        f"{_W}: Modified Julian Date is not a finite value in 1 to 65535 (ICD 2620002Y)",
    ),
    (
        "azimuth number 721",
        {"azimuth": 721},
        "azimuth-number-out-of-range",
        f"{_W}: Azimuth Number is not a finite value in 1 to 720 (ICD 2620002Y)",
    ),
    (
        "azimuth angle 360",
        {"angle": 360.0},
        "azimuth-angle-out-of-range",
        f"{_W}: Azimuth Angle is not a finite value in 0.0 to 359.9560546875 (ICD 2620002Y)",
    ),
    (
        "azimuth angle NaN",
        {"angle": float("nan")},
        "azimuth-angle-out-of-range",
        f"{_W}: Azimuth Angle is not a finite value in 0.0 to 359.9560546875 (ICD 2620002Y)",
    ),
    (
        "azimuth spacing 3",
        {"azimuth_spacing": 3},
        "azimuth-resolution-spacing-out-of-range",
        f"{_W}: Azimuth Resolution Spacing is not a finite value in 1 to 2 (ICD 2620002Y)",
    ),
    (
        "elevation number 0",
        {"elevation": 0},
        "elevation-number-out-of-range",
        f"{_W}: Elevation Number is not a finite value in 1 to 32 (ICD 2620002Y)",
    ),
    (
        "cut sector 4",
        {"cut_sector": 4},
        "cut-sector-number-out-of-range",
        f"{_W}: Cut Sector Number is not a finite value in 0 to 3 (ICD 2620002Y)",
    ),
    (
        "elevation angle 70.5",
        {"elevation_angle": 70.5},
        "elevation-angle-out-of-range",
        f"{_W}: Elevation Angle is not a finite value in -7.0 to 70.0 (ICD 2620002Y)",
    ),
    (
        "elevation angle infinite",
        {"elevation_angle": float("inf")},
        "elevation-angle-out-of-range",
        f"{_W}: Elevation Angle is not a finite value in -7.0 to 70.0 (ICD 2620002Y)",
    ),
    (
        "spot blanking 8",
        {"spot_blanking": 8},
        "radial-spot-blanking-status-out-of-range",
        f"{_W}: Radial Spot Blanking Status is not a finite value in 0 to 7 (ICD 2620002Y)",
    ),
    (
        "azimuth indexing 101",
        {"azimuth_indexing": 101},
        "azimuth-indexing-mode-out-of-range",
        f"{_W}: Azimuth Indexing Mode is not a finite value in 0 to 100 (ICD 2620002Y)",
    ),
    (
        "radial status 6",
        {"status": 6},
        "radial-status-out-of-range",
        f"{_W}: the Radial Status is none of Table III-C's twelve values",
    ),
    (
        "radial status 0x86",
        {"status": 0x86},
        "radial-status-out-of-range",
        f"{_W}: the Radial Status is none of Table III-C's twelve values",
    ),
    (
        "latitude below 0",
        {"site": {**BUILDER.SITE, "latitude": -1.0}},
        "lat-out-of-range",
        f"{_W}, VOL: Lat is not a finite value in 0.0 to 90.0 (ICD 2620002Y)",
    ),
    (
        "longitude past 180",
        {"site": {**BUILDER.SITE, "longitude": 180.5}},
        "long-out-of-range",
        f"{_W}, VOL: Long is not a finite value in -180.0 to 180.0 (ICD 2620002Y)",
    ),
    (
        "site height 12001",
        {"site": {**BUILDER.SITE, "site_height": 12001}},
        "site-height-out-of-range",
        f"{_W}, VOL: Site Height is not a finite value in -100 to 12000 (ICD 2620002Y)",
    ),
    (
        "tower height 1001",
        {"site": {**BUILDER.SITE, "tower_height": 1001}},
        "tower-height-out-of-range",
        f"{_W}, VOL: Tower Height is not a finite value in 0 to 1000 (ICD 2620002Y)",
    ),
    (
        "VOL version 0",
        {"vol": _with("vol", version_major=0)},
        "version-number-major-out-of-range",
        f"{_W}, VOL: Version Number (major) is not a finite value in 1 to 255 (ICD 2620002Y)",
    ),
    (
        "VOL dBZ0 99.5",
        {"vol": _with("vol", dbz0=99.5)},
        "calibration-constant-dbz0-out-of-range",
        f"{_W}, VOL: Calibration Constant (dBZ0) is not a finite value in -99.0 to 99.0 "
        "(ICD 2620002Y)",
    ),
    (
        "horizontal power 1000",
        {"vol": _with("vol", horizontal_tx_power=1000.0)},
        "horizontal-shv-tx-power-out-of-range",
        f"{_W}, VOL: Horizontal SHV Tx Power is not a finite value in 0.0 to 999.9000244140625 "
        "(ICD 2620002Y)",
    ),
    (
        "system ZDR 8",
        {"vol": _with("vol", system_zdr=8.0)},
        "system-differential-reflectivity-out-of-range",
        f"{_W}, VOL: System Differential Reflectivity is not a finite value in -7.875 to 7.75 "
        "(ICD 2620002Y)",
    ),
    (
        "initial PHIDP 361",
        {"vol": _with("vol", initial_system_phidp=361.0)},
        "initial-system-differential-phase-out-of-range",
        f"{_W}, VOL: Initial System Differential Phase is not a finite value in 0.0 to 360.0 "
        "(ICD 2620002Y)",
    ),
    (
        "VCP 0",
        {"vol": _with("vol", vcp=0)},
        "volume-coverage-pattern-number-out-of-range",
        f"{_W}, VOL: Volume Coverage Pattern Number is not a finite value in 1 to 767 "
        "(ICD 2620002Y)",
    ),
    (
        "VCP 768",
        {"vol": _with("vol", vcp=768)},
        "volume-coverage-pattern-number-out-of-range",
        f"{_W}, VOL: Volume Coverage Pattern Number is not a finite value in 1 to 767 "
        "(ICD 2620002Y)",
    ),
    (
        "ATMOS -0.021",
        {"elv": _with("elv", atmospheric_attenuation=-21)},
        "atmos-out-of-range",
        f"{_W}, ELV: ATMOS is not a finite value in -20 to -2 (ICD 2620002Y)",
    ),
    (
        "ATMOS -0.001",
        {"elv": _with("elv", atmospheric_attenuation=-1)},
        "atmos-out-of-range",
        f"{_W}, ELV: ATMOS is not a finite value in -20 to -2 (ICD 2620002Y)",
    ),
    (
        "ELV dBZ0 -99.5",
        {"elv": _with("elv", dbz0=-99.5)},
        "calibration-constant-dbz0-out-of-range",
        f"{_W}, ELV: Calibration Constant (dBZ0) is not a finite value in -99.0 to 99.0 "
        "(ICD 2620002Y)",
    ),
    (
        "unambiguous range 114.9",
        {"rad": _with("rad", unambiguous_range=1149)},
        "unambiguous-range-out-of-range",
        f"{_W}, RAD: Unambiguous Range is not a finite value in 1150 to 5110 (ICD 2620002Y)",
    ),
    (
        "noise -49",
        {"rad": _with("rad", noise_level_h=-49.0)},
        "noise-level-horizontal-out-of-range",
        f"{_W}, RAD: Noise Level (horizontal) is not a finite value in -100.0 to -50.0 "
        "(ICD 2620002Y)",
    ),
    (
        "nyquist 35.62",
        {"rad": _with("rad", nyquist_velocity=3562)},
        "nyquist-velocity-out-of-range",
        f"{_W}, RAD: Nyquist Velocity is not a finite value in 800 to 3561 (ICD 2620002Y)",
    ),
    (
        "calibration V 100",
        {"rad": _with("rad", calibration_v=100.0)},
        "calibration-constant-vertical-out-of-range",
        f"{_W}, RAD: Calibration Constant (vertical) is not a finite value in -99.0 to 99.0 "
        "(ICD 2620002Y)",
    ),
    (
        "REF gate count 0",
        {"moments": _moments("REF", gates=0, runs=[])},
        "number-of-data-moment-gates-out-of-range",
        f"{_W}, data block pointer 3 (REF): Number of Data Moment Gates is not a finite value in "
        "1 to 1840 (ICD 2620002Y)",
    ),
    (
        "first gate 32.769 km",
        {"moments": _moments("REF", first_gate_range=32769)},
        "data-moment-range-out-of-range",
        f"{_W}, data block pointer 3 (REF): Data Moment Range is not a finite value in 0 to 32768 "
        "(ICD 2620002Y)",
    ),
    (
        "gate interval 0.249 km",
        {"moments": _moments("VEL", gate_interval=249)},
        "data-moment-range-sample-interval-out-of-range",
        f"{_W}, data block pointer 4 (VEL): Data Moment Range Sample Interval is not a finite "
        "value in 250 to 4000 (ICD 2620002Y)",
    ),
    (
        "TOVER 20.1",
        {"moments": _moments("SW", tover=201)},
        "tover-out-of-range",
        f"{_W}, data block pointer 5 (SW): TOVER is not a finite value in 0 to 200 (ICD 2620002Y)",
    ),
    (
        "SNR threshold -12.125",
        {"moments": _moments("ZDR", snr_threshold=-97)},
        "snr-threshold-out-of-range",
        f"{_W}, data block pointer 6 (ZDR): SNR Threshold is not a finite value in -96 to 160 "
        "(ICD 2620002Y)",
    ),
    (
        "control flags 4",
        {"moments": _moments("PHI", control_flags=4)},
        "control-flags-out-of-range",
        f"{_W}, data block pointer 7 (PHI): Control Flags is not a finite value in 0 to 3 "
        "(ICD 2620002Y)",
    ),
    (
        "scale 0",
        {"moments": _moments("RHO", scale=0.0)},
        "floating-point-moment",
        f"{_W}, data block pointer 8 (RHO): a Scale of 0 marks floating-point gates (note 15), "
        "which this module does not read",
    ),
    (
        "scale negative",
        {"moments": _moments("RHO", scale=-300.0)},
        "scale-out-of-range",
        f"{_W}, data block pointer 8 (RHO): the Scale is not a finite value in 0 to 65535",
    ),
    (
        "scale NaN",
        {"moments": _moments("RHO", scale=float("nan"))},
        "scale-out-of-range",
        f"{_W}, data block pointer 8 (RHO): the Scale is not a finite value in 0 to 65535",
    ),
    (
        "offset infinite",
        {"moments": _moments("CFP", offset=float("inf"))},
        "offset-out-of-range",
        f"{_W}, data block pointer 9 (CFP): the Offset is not finite",
    ),
]


@pytest.mark.parametrize(
    "label, over, code, text", RANGE_REFUSALS, ids=[row[0] for row in RANGE_REFUSALS]
)
def test_every_range_the_icd_states_is_a_validation_rule(label, over, code, text):
    refusal = _refusal(_volume(_message(**over)))
    assert (refusal.code, str(refusal)) == (code, f"{code}: {text}")


def test_a_value_at_either_end_of_a_range_is_read():
    """The bounds are inclusive: each end of a few ranges translates."""
    for over in (
        {"azimuth": 720},
        {"angle": 359.9560546875},
        {"elevation": 32},
        {"elevation_angle": -7.0},
        {"spot_blanking": 7},
        {"cut_sector": 0},
        {"status": 0x85},
        {"site": {**BUILDER.SITE, "site_height": -100, "tower_height": 1000}},
        {"rad": _with("rad", unambiguous_range=5110, nyquist_velocity=800)},
        {"elv": _with("elv", atmospheric_attenuation=-20)},
        {"moments": _moments("REF", snr_threshold=160, tover=0, first_gate_range=0)},
    ):
        assert Nexrad2Adapter(times.frozen_clock()).to_cdm(_volume(_message(**over)))


def _patched(message: bytes, at: int, value: bytes) -> bytes:
    """`message` with `value` written at offset `at` of its radial (after CTM and header)."""
    position = 28 + at
    return message[:position] + value + message[position + len(value) :]


def _pointer(index: int) -> int:
    """The radial offset of data block pointer `index` (Table XVII-A: 32 + 4 x index)."""
    return 32 + 4 * index


STRUCTURE_REFUSALS = [
    (
        "another site's radial",
        lambda: _volume(_message(icao="XZZA")),
        "site-mismatch",
        f"{_W}: the Radar Identifier is not the volume header's ICAO identifier",
    ),
    (
        "compression indicator 3",
        lambda: _volume(_message(compression=3)),
        "radial-compression-unknown",
        f"{_W}: the Compression Indicator is not 0, 1 or 2 (ICD 2620002Y Table XVII-A)",
    ),
    (
        "radial length longer than its message",
        lambda: _volume(_message(radial_length_override=12442)),
        "radial-length-disagrees",
        f"{_W}: the Radial Length is not the length of the message's radial",
    ),
    (
        "a pointer before the blocks",
        lambda: _volume(_patched(_message(), _pointer(0), struct.pack(">I", 40))),
        "block-past-the-radial",
        f"{_W}, data block pointer 0 points outside the radial",
    ),
    (
        "a pointer past the radial",
        lambda: _volume(_patched(_message(), _pointer(9), struct.pack(">I", 12438))),
        "block-past-the-radial",
        f"{_W}, data block pointer 9 points outside the radial",
    ),
    (
        "two pointers to one block",
        lambda: _volume(_patched(_message(), _pointer(1), struct.pack(">I", 72))),
        "block-stated-twice",
        f"{_W}, data block pointer 1: a second VOL",
    ),
    (
        "an unknown moment",
        lambda: _volume(_patched(_message(), 72 + 52 + 12 + 28, b"DXYZ")),
        "unknown-moment",
        f"{_W}, data block pointer 3: a data moment Table XVII-I does not name",
    ),
    (
        "an unknown block type",
        lambda: _volume(_patched(_message(), 72 + 52, b"QELV")),
        "unknown-block",
        f"{_W}, data block pointer 1: a block that is not VOL, ELV, RAD or a data moment",
    ),
    (
        "a VOL block of 44 octets",
        lambda: _volume(_patched(_message(), 72 + 4, struct.pack(">H", 44))),
        "block-size",
        f"{_W}, data block pointer 0: the VOL block's LRTUP is not 52 (ICD 2620002Y Table XVII)",
    ),
    (
        "no RAD block",
        lambda: _volume(_patched(_message(), _pointer(2), struct.pack(">I", 0))),
        "constant-block-missing",
        f"{_W}: no RAD block (ICD 2620002Y Table XVII-A note 10: always present)",
    ),
    (
        "no REF moment",
        lambda: _volume(_patched(_message(), _pointer(3), struct.pack(">I", 0))),
        "reflectivity-missing",
        f"{_W}: no REF moment (ICD 2620002Y Table XVII-A note 9: always present)",
    ),
    # VEL's block starts at 72 + 52 + 12 + 28 + 1868 = 2032 and its NG is at its octet 8; 1201
    # gates of 8 bits run one octet into SW's block at 2032 + 28 + 1200 = 3260.
    (
        "overlapping blocks",
        lambda: _volume(_patched(_message(), 2032 + 8, struct.pack(">H", 1201))),
        "blocks-overlap",
        f"{_W}: two data blocks overlap",
    ),
    (
        "a word size of 12 bits",
        lambda: _volume(_message(moments=_moments("CFP", word_size=12))),
        "data-word-size-out-of-range",
        f"{_W}, data block pointer 9 (CFP): the Data Word Size is not 8 or 16 (ICD 2620002Y "
        "XVII-B)",
    ),
    (
        "a radial stated twice",
        lambda: _volume(_message() + _message()),
        "radial-stated-twice",
        "LDM record 1, message 1: elevation 1 already holds a radial with this azimuth number",
    ),
    (
        "times running backwards",
        lambda: _volume(_message(ms=BUILDER._ms(1)) + _message(azimuth=2, ms=BUILDER._ms(0))),
        "radial-times-out-of-order",
        "LDM record 1, message 1: the collection time precedes the previous radial's in "
        "elevation 1",
    ),
    (
        "a moment on one radial only",
        lambda: _volume(_message() + _message(azimuth=2, moments=BUILDER.every_moment()[:6])),
        "moment-not-on-every-radial",
        "LDM record 1, message 1: elevation 1's radials do not all state the same moments",
    ),
    (
        "a gate count that changes",
        lambda: _volume(
            _message()
            + _message(azimuth=2, moments=_moments("VEL", gates=1199, runs=[[129, 1199]]))
        ),
        "moment-geometry-varies",
        "LDM record 1, message 1: VEL's gate count, first-gate range, gate interval or word size "
        "differs within elevation 1",
    ),
    (
        "a site that moves",
        lambda: _volume(
            _message() + _message(azimuth=2, site={**BUILDER.SITE, "tower_height": 31})
        ),
        "site-varies",
        "LDM record 1, message 1: the VOL block's latitude, longitude or heights differ from the "
        "first radial's; a volume is one site",
    ),
    (
        "121 radials in one record",
        lambda: _volume(b"".join(_message(azimuth=a) for a in range(1, 122))),
        "too-many-radials",
        "LDM record 1 holds more than 120 radials (ICD 2620010J 7.3.4)",
    ),
    (
        "a message 31 of two segments",
        lambda: _volume(_message()[:24] + struct.pack(">HH", 2, 1) + _message()[28:]),
        "message-segments",
        f"{_W}: a message 31 states one segment, number 1 (ICD 2620002Y Table II)",
    ),
    (
        "a message 31 longer than its record",
        lambda: _volume(_message()[:12] + struct.pack(">H", 7000) + _message()[14:]),
        "truncated-message",
        f"{_W}: the message size runs past the record or holds no radial",
    ),
    (
        "a header cut short",
        lambda: _volume(_message() + b"\x00" * 20),
        "truncated-message",
        "LDM record 1, message 1: the message header is cut short",
    ),
    (
        "a status segment cut short",
        lambda: _volume(_message() + BUILDER.fixed_segment(2, 136, 0)[:2000]),
        "truncated-message",
        "LDM record 1, message 1: the RDA status segment is cut short",
    ),
    (
        "a type 0 segment among the radials",
        lambda: _volume(_message() + BUILDER.fixed_segment(0, 136, 0)),
        "unexpected-message-type",
        "LDM record 1, message 1: a message type where a radial (31) or an RDA status message "
        "(2) is required (ICD 2620010J 7.3.4)",
    ),
    (
        "a status-only volume",
        lambda: _volume(BUILDER.fixed_segment(2, 135, 0)),
        "no-radial",
        "the volume holds no message-31 radial",
    ),
    (
        "a header and nothing else",
        lambda: _volume()[:24],
        "no-radial",
        "the volume holds no message-31 radial",
    ),
]


@pytest.mark.parametrize(
    "label, build, code, text", STRUCTURE_REFUSALS, ids=[row[0] for row in STRUCTURE_REFUSALS]
)
def test_every_structural_rule_refuses_with_its_code_and_its_whole_text(label, build, code, text):
    refusal = _refusal(build())
    assert (refusal.code, str(refusal)) == (code, f"{code}: {text}")


def _metadata_with(segment: int, message_type: int) -> bytes:
    metadata, _ = BUILDER.metadata_record(BUILDER.START_MS)
    at = segment * 2432 + 15
    return metadata[:at] + bytes([message_type]) + metadata[at + 1 :]


FRAMING_REFUSALS = [
    (
        "extension 000",
        lambda v: v[:9] + b"000" + v[12:],
        "bad-volume-header",
        "the extension number is not 001 to 999",
    ),
    (
        "tape without its dot",
        lambda v: v[:8] + b"_" + v[9:],
        "bad-volume-header",
        "the tape name is not AR2V00, two digits, '.'",
    ),
    (
        "a lower-case site",
        lambda v: v[:20] + b"zzzz" + v[24:],
        "bad-volume-header",
        "the volume header's ICAO identifier is not four letters",
    ),
    (
        "a header past the day",
        lambda v: v[:16] + struct.pack(">I", 86_400_000) + v[20:],
        "bad-volume-header",
        "the volume header's date or time is outside a day 1 to 65535 and 0 to 86399999 ms",
    ),
    (
        "three octets after the last record",
        lambda v: v + b"\x00\x00\x01",
        "truncated-record",
        "LDM record 2: fewer than four octets remain for a control word",
    ),
    (
        "a control word of 0",
        lambda v: v + b"\x00\x00\x00\x00",
        "empty-record",
        "LDM record 2: the control word states no octets",
    ),
    (
        "a record that is not bzip2",
        lambda v: v + b"\x00\x00\x00\x04GZIP",
        "not-bzip2",
        "LDM record 2 does not begin with the bzip2 magic BZh",
    ),
    (
        "octets after a stream inside its size",
        lambda v: (
            v[:24]
            + struct.pack(">i", struct.unpack(">i", v[24:28])[0] + 2)
            + v[28 : 28 + struct.unpack(">i", v[24:28])[0]]
            + b"\x00\x00"
            + v[28 + struct.unpack(">i", v[24:28])[0] :]
        ),
        "octets-after-bzip2",
        "LDM record 0: octets follow the bzip2 stream inside the size the control word states",
    ),
    (
        "message 1 in the metadata record",
        lambda v: _volume_with_metadata(v, _metadata_with(3, 1)),
        "message-1",
        "LDM record 0, message 3: message 1, the legacy digital radar data message, replaced by "
        "message 31 as of Build 10; this module does not decode it",
    ),
    (
        "a radial in the metadata record",
        lambda v: _volume_with_metadata(v, _metadata_with(100, 31)),
        "unexpected-message-type",
        "LDM record 0, message 100: a message type the metadata record does not hold "
        "(ICD 2620010J 7.3.5)",
    ),
]


def _volume_with_metadata(volume: bytes, metadata: bytes) -> bytes:
    size = abs(struct.unpack(">i", volume[24:28])[0])
    return volume[:24] + BUILDER.ldm_record(metadata)[0] + volume[28 + size :]


@pytest.mark.parametrize(
    "label, change, code, text", FRAMING_REFUSALS, ids=[row[0] for row in FRAMING_REFUSALS]
)
def test_the_volume_header_and_the_records_are_framed_strictly(label, change, code, text):
    valid = (FIXTURES / "all_moments_one_elevation.ar2v").read_bytes()
    refusal = _refusal(change(valid))
    assert (refusal.code, str(refusal)) == (code, f"{code}: {text}")


def test_version_07_and_every_extension_number_are_read():
    valid = (FIXTURES / "all_moments_one_elevation.ar2v").read_bytes()
    for changed in (valid[:6] + b"07" + valid[8:], valid[:9] + b"999" + valid[12:]):
        assert Nexrad2Adapter(times.frozen_clock()).to_cdm(changed)


def test_a_truncated_volume_is_refused_at_every_cut_or_read_as_a_shorter_whole():
    """Check N's property, run here over every cut of one volume: a cut is a refusal of this
    module's class, or — at a record boundary — a whole shorter volume."""
    valid = (FIXTURES / "two_elevations_two_records.ar2v").read_bytes()
    boundaries = []
    position = 24
    while position < len(valid):
        position += 4 + abs(struct.unpack(">i", valid[position : position + 4])[0])
        boundaries.append(position)
    read = []
    for cut in range(len(valid)):
        try:
            Nexrad2Adapter(times.frozen_clock()).to_cdm(valid[:cut])
            read.append(cut)
        except Nexrad2Refused:
            pass
    # Only the cut after the first radial record leaves a volume with radials: elevation 1.
    assert read == [boundaries[1]]


# ================================================================== the shared layer (R1 duties)


def test_a_radar_site_is_a_site_class_and_its_height_is_carried_as_stated():
    assert oc.SITE_ENTITY_TYPES["radar_site"].value == "SENSOR"
    source = SourceRef(system="NEXRAD", adapter="nexrad2", adapter_version="1.0.0", synthetic=True)
    when = dt.datetime(2026, 4, 29, 6, 10, tzinfo=dt.timezone.utc)
    msl = VerticalPosition(value=120.0, unit=VerticalUnit.METRES, reference=VerticalReference.MSL)
    hae = VerticalPosition(value=150.0, unit=VerticalUnit.METRES, reference=VerticalReference.HAE)
    common = dict(
        source=source,
        system="NEXRAD",
        station_id="ZZZZ",
        site_class="radar_site",
        valid_from=when,
        stated_position=(57.25, 22.5),
        stated_position_basis="the VOL block",
    )
    entity = oc.site_entity(**common, stated_vertical=msl, stated_vertical_basis="site height")
    assert (entity.position.alt_m, entity.position.vertical) == (None, msl)
    assert entity.attributes["vertical_basis"] == "site height"
    entity = oc.site_entity(**common, stated_vertical=hae, stated_vertical_basis="ellipsoidal")
    assert (entity.position.alt_m, entity.position.vertical) == (150.0, hae)
    without = oc.site_entity(**common)
    assert (without.position.vertical, "vertical_basis" in without.attributes) == (None, False)
    for kwargs, message in (
        ({"stated_vertical": msl}, "a height read from the payload states where it was read"),
        (
            {"stated_vertical": msl, "stated_vertical_basis": "  "},
            "a height read from the payload states where it was read",
        ),
        ({"stated_vertical_basis": "site height"}, "a vertical basis is stated and no height is"),
    ):
        with pytest.raises(ValueError) as raised:
            oc.site_entity(**common, **kwargs)
        assert str(raised.value) == message
    with pytest.raises(ValueError) as raised:
        oc.site_entity(
            source=source,
            system="NEXRAD",
            station_id="ZZZZ",
            site_class="radar_site",
            valid_from=when,
            stated_vertical=msl,
            stated_vertical_basis="site height",
        )
    assert str(raised.value) == "a stated height belongs to a position read from the payload"


_NOT_IN_UTC = (
    "the instant cannot be stated in UTC: read in UTC it falls before 0001-01-01 or after "
    "9999-12-31, which no timestamp holds"
)


def test_an_observed_at_no_utc_instant_holds_is_the_fixed_refusal_and_never_an_overflow():
    """R1b review F-2: an aware datetime whose UTC reading leaves the years 0001 to 9999 made
    `observation_event` raise OverflowError; it is the fixed ValueError `_in_utc` raises."""
    event = Nexrad2Adapter(times.frozen_clock()).to_cdm(
        (FIXTURES / "all_moments_one_elevation.ar2v").read_bytes()
    )[0]
    contract = oc.contract_of(event)
    plus = dt.timezone(dt.timedelta(hours=5))
    minus = dt.timezone(dt.timedelta(hours=-5))
    for observed in (
        dt.datetime(1, 1, 1, 0, 0, tzinfo=plus),
        dt.datetime(9999, 12, 31, 23, 0, tzinfo=minus),
    ):
        with pytest.raises(ValueError) as raised:
            oc.observation_event(
                source=event.source,
                source_ids=event.source_ids,
                observation=contract,
                observed_at=observed,
                received_at=event.received_at,
                validity=event.validity,
                related_entities=event.related_entities,
            )
        assert type(raised.value) is ValueError
        assert str(raised.value) == _NOT_IN_UTC


class _NoOffset(dt.tzinfo):
    """A tzinfo that is set and states no offset: a naive datetime in all but name."""

    def utcoffset(self, when):
        return None

    def dst(self, when):
        return None

    def tzname(self, when):
        return None


def test_an_injected_time_whose_zone_states_no_offset_is_refused_as_naive():
    """R1b review F-3: `tzinfo is not None` let a zone with no offset through, read in the
    host's own zone; `utcoffset() is not None` refuses it."""
    naive_in_all_but_name = dt.datetime(2026, 1, 1, 12, 0, tzinfo=_NoOffset())
    assert naive_in_all_but_name.tzinfo is not None
    assert naive_in_all_but_name.utcoffset() is None
    with pytest.raises(ValueError) as raised:
        oc.InjectedTime(naive_in_all_but_name, "a basis long enough")
    assert str(raised.value) == "InjectedTime.instant is an RFC 3339 text or an aware datetime"
    aware = oc.InjectedTime(
        dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.timezone.utc), "a basis long enough"
    )
    assert aware.rendered == "2026-01-01T12:00:00.000Z"
