"""Build the STANAG 4607 fixture set. Synthetic only — no recorded GMTI traffic.

Run from the repository root:

    python build_fixtures.py                      # from the directory this file is in

Each case is written as a TWIN: a `.gmti` binary packet and a `.parsed.json` holding the decoded
form the never-drop check measures against. Both go through `to_cdm()` when the harness replays
the directory, and a test asserts the two produce identical CDM objects.

THIS FILE IS THE FIXTURE SET'S REVIEWABLE FORM, AND THAT IS NOT A CONVENIENCE
-----------------------------------------------------------------------------
A GMTI packet is 32 bytes of header followed by length-prefixed binary segments. It cannot carry
a comment, and it cannot be rebuilt from its own twin by hand: `P2`, every `S2`, every existence
mask and every target-report width are functions of the contents. So the module with the
arithmetic in it IS the documentation of what each fixture says — exactly the position
`fixtures/cat021/spec/build_fixtures.py` occupies for the ASTERIX set, and the reason `pyproject`
ships `fixtures/**/*.py` in the wheel.

THE ENCODER AND THE DECODER MUST NOT SHARE A BUG INVISIBLY
-----------------------------------------------------------
Every binary here is produced by `gmtif.encode_packet`, which is the same module the adapter
decodes with — so a symmetric error would round-trip perfectly and be invisible. Two things guard
against that. `test_cdm_gmtif_codec` checks every encoding against byte patterns worked out by
hand from Annex C, including the two worked examples the standard itself prints. And
`test_the_hand_verified_fixture_matches_the_annex_c_byte_layout` takes ONE fixture —
`mission_dwell_hi_res_targets` — and asserts its first 71 bytes against a hand-written expectation
built from Table 3-1, Table 3-6 and Table 3-7 field by field, with the hexadecimal spelled out in
the test. If the encoder and the decoder ever agree with each other and disagree with the
document, that test is what says so.

IDENTIFIERS. GMTIF carries no UUIDs — every identifier on this wire is an alphanumeric string or
an integer — so the RFC 9562 version-8 rule the Legion and NITS fixtures follow has nothing here
to apply to, and a test asserts that no fixture contains a UUID-shaped string rather than leaving
the convention looking forgotten. Instead:

  * `P3` Nationality and `P5` Classification System use `ZZ`, which is not in Table 3-3's list of
    national examples and is not `XN`. Unlike the CAT021 SAC there is **no pinned allocation list**
    behind that claim — Table 3-3 is explicitly "National Examples" plus "additional codes as
    registered with the Custodian" — so it is the weakest identifier claim in this set and this
    comment is where it says so.
  * `P8` Platform ID is `ZZSYN00001`, a tail number no nation issues, safe only because `P3` is
    non-allocated: §3.1.8 scopes platform uniqueness to "the set of platforms it owns", so the two
    claims are coupled.
  * `M3` Platform Type and `J2` Sensor ID Type take values from the **Available for Future Use**
    ranges (57-254 and 36-254), so no fixture ever claims to be an E-8C carrying an APY-7. That
    also exercises the `unresolved_raw` path on every fixture for free.

P7 IS NEVER A PURELY-REAL VALUE HERE, AND THAT IS FORCED
--------------------------------------------------------
The harness constructs the adapter with `synthetic=True`, and a `P7` of 0 or 128 — purely real
data — against that declaration is a conflict refusal by design (amendment 2). So every fixture
states 1, 2, 129 or 130, and the purely-real cases — including the **tagging-device exemption**,
which only bites when `P7` is real — are exercised in `tests/test_cdm_gmtif_adapter.py` where the
declaration can be set to match. Every refusal path is a unit test for the same reason the NITS
set gives: a fixture whose `to_cdm` raises is a harness FAIL, and a refusal that reads as a
failure is a refusal nobody keeps.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))

from synapse_cdm.adapters import gmtif as g            # noqa: E402
from synapse_cdm.adapters import gmtif_codec as codec  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent.parent

NATIONALITY = "ZZ"
PLATFORM = "ZZSYN00001"
MISSION_ID = 4242
JOB_ID = 77

# Table 3-2 value 5, UNCLASSIFIED — a real classification a producer can state, which is exactly
# why it is safe here and forbidden as an egress DEFAULT.
P4_UNCLASSIFIED = 5
#: Two caveat bits set, so `code_bits` is non-trivial and the "raw integer plus set bits, never
#: codeword names" rule has something to demonstrate. Which codewords those bits mean is precisely
#: what the standard and guide Annex G disagree about, so the fixture asserts nothing about it.
P6_TWO_BITS = 0x0041

REFERENCE = (2026, 4, 29)


# ------------------------------------------------------------------ grid snapping
#
# A binary angle can only hold multiples of its LSB, so a fixture that asked for 57.3 deg would be
# asking for a value the wire cannot carry. These snap to the field's own grid and return the
# value that will actually be on the wire, so the `.parsed.json` twin and the bytes agree exactly.

def sa32(deg: float) -> float:
    return codec.from_raw("SA32", int(round(deg * (1 << 30) / 45)) & 0xFFFFFFFF)


def ba32(deg: float) -> float:
    return codec.from_raw("BA32", int(round((deg % 360.0) * (1 << 29) / 45)) & 0xFFFFFFFF)


def sa16(deg: float) -> float:
    return codec.from_raw("SA16", int(round(deg * (1 << 14) / 45)) & 0xFFFF)


def ba16(deg: float) -> float:
    return codec.from_raw("BA16", int(round((deg % 360.0) * (1 << 13) / 45)) & 0xFFFF)


def b16(value: float) -> float:
    return round(value * 128) / 128.0


def b32(value: float) -> float:
    return round(value * (1 << 23)) / float(1 << 23)


def h32(value: float) -> float:
    return round(value * (1 << 16)) / float(1 << 16)


# ------------------------------------------------------------------ segment builders


def _finish(segment: dict) -> dict:
    """Encode once with no declared size, then stamp the size the bytes actually need.

    `encode_packet` recomputes it and refuses a mismatch, so the value written here is checked
    rather than trusted.
    """
    segment.pop("size", None)
    segment["size"] = len(g._encode_segment(segment))
    return segment


def mission(*, year: int = REFERENCE[0], month: int = REFERENCE[1], day: int = REFERENCE[2],
            plan: str = "SYNMSN0001", flight: str = "SYNFLT0001",
            platform_type: int = 200, configuration: str = "SYN-CFG-1") -> dict:
    return _finish({"type": 1, "ordinal": 0, "fields": {
        "M1": plan, "M2": flight, "M3": platform_type, "M4": configuration,
        "M5": year, "M6": month, "M7": day,
    }})


def dwell(*, fields: dict, targets: list[dict] | None = None,
          target_fields: tuple[str, ...] | None = None, ordinal: int = 0) -> dict:
    """A Dwell Segment whose existence mask is DERIVED from the fields supplied.

    Deriving it is the point: a hand-written mask and a hand-written field list are two chances to
    disagree, and the disagreement would be a fixture that tests the wrong thing.
    """
    targets = targets or []
    names = set(fields)
    if target_fields is None:
        target_fields = tuple(targets[0]) if targets else ()
    present = names | set(target_fields)
    mask = 0
    for name, _mco in g.mask_order("dwell"):
        if name in present:
            mask |= 1 << g.mask_bit("dwell", name)
    return _finish({"type": 2, "ordinal": ordinal, "mask": mask, "fields": fields,
                    "targets": [{k: t[k] for k in target_fields} for t in targets]})


#: The nine Mandatory Dwell Segment fields, with values every case can share.
def dwell_mandatory(*, d5: int, d6: int = 30_600_000, ordinal: int = 0) -> dict:
    return {
        "D2": 3, "D3": 11, "D4": 1, "D5": d5, "D6": d6,
        "D7": sa32(57.31), "D8": ba32(24.72), "D9": 8_500_00,   # 8500.00 m in centimetres
        "D24": sa32(57.05), "D25": ba32(24.40), "D26": b16(12.5), "D27": ba16(1.5),
    }


def hrr(*, ordinal: int, revisit: int = 3, dwell_index: int = 11,
        scatterers: bytes = b"\x10\x20\x30\x40") -> dict:
    """An HRR Segment with `H23 = 5` (Full RDM), which requires `H15` and permits `H21`/`H22`."""
    fields = {
        "H2": revisit, "H3": dwell_index, "H4": 1, "H6": 2, "H8": 4,
        "H10": 40, "H11": b16(30.0), "H12": b16(15.0), "H13": h32(120.5), "H14": h32(4.25),
        "H15": b32(9.5), "H16": 0, "H17": 1, "H18": 1, "H19": b16(48.0),
        "H23": 5, "H24": 0b10000000, "H25": 1, "H26": 0,
    }
    mask = 0
    for name in list(fields) + ["H32.1"]:
        mask |= 1 << g.mask_bit("hrr", name)
    return _finish({"type": 3, "ordinal": ordinal, "mask": mask, "fields": fields,
                    "scatterers_hex": scatterers.hex()})


def job_definition(*, ordinal: int, job: int = JOB_ID, priority: int = 20) -> dict:
    return _finish({"type": 5, "ordinal": ordinal, "fields": {
        "J1": job, "J2": 200, "J3": "SYNRDR", "J4": 0b00000001, "J5": priority,
        "J6": sa32(57.6), "J7": ba32(24.1), "J8": sa32(57.6), "J9": ba32(25.1),
        "J10": sa32(56.6), "J11": ba32(25.1), "J12": sa32(56.6), "J13": ba32(24.1),
        "J14": 1, "J15": 300,
        # Every nominal field at its documented No-Statement value: §2.4's fourth category, and
        # what `unavailable_fields` has to keep apart from a masked-out field.
        "J16": 65535, "J17": 65535, "J18": 65535, "J19": 255, "J20": 65535,
        "J21": 65535, "J22": 180.0, "J23": 65535, "J24": 255, "J25": 255, "J26": 255,
        "J27": 1, "J28": 1,
    }})


def free_text(*, ordinal: int, text: str = "SYNTHETIC FIXTURE MESSAGE") -> dict:
    return _finish({"type": 6, "ordinal": ordinal, "fields": {
        "F1": "SYNORIG", "F2": "SYNRECIP", "F3": text}})


def test_status(*, ordinal: int, t4: int = 30_601_000, hardware: int = 0b00010000,
                mode: int = 0b00010000) -> dict:
    return _finish({"type": 10, "ordinal": ordinal, "fields": {
        "T1": JOB_ID, "T2": 3, "T3": 11, "T4": t4, "T5": hardware, "T6": mode}})


def processing_history(*, ordinal: int, records: int = 2) -> dict:
    fields = {"C1": records, "C2": "ZZ", "C3": PLATFORM, "C4": MISSION_ID, "C5": JOB_ID}
    made = [{"C6.1": index + 1, "C6.2": "ZY", "C6.3": f"ZYSYN0000{index + 1}",
             "C6.4": 900 + index, "C6.5": 500 + index,
             "C6.6": 0x0001 if index == 0 else 0x0800}
            for index in range(records)]
    return _finish({"type": 12, "ordinal": ordinal, "fields": fields, "records": made})


def platform_location(*, ordinal: int, l1: int, lat: float = 57.33, lon: float = 24.75,
                      alt_cm: int = 8_600_00, track: float = 92.0,
                      speed_mm_s: int = 118_000, vertical_dm_s: int = -3) -> dict:
    return _finish({"type": 13, "ordinal": ordinal, "fields": {
        "L1": l1, "L2": sa32(lat), "L3": ba32(lon), "L4": alt_cm,
        "L5": ba16(track), "L6": speed_mm_s, "L7": vertical_dm_s}})


def job_request(*, ordinal: int) -> dict:
    return _finish({"type": 101, "ordinal": ordinal, "fields": {
        "R1": "SYNREQ01", "R2": "SYNTASK01", "R3": 5,
        "R4": sa32(57.6), "R5": ba32(24.1), "R6": sa32(57.6), "R7": ba32(25.1),
        "R8": sa32(56.6), "R9": ba32(25.1), "R10": sa32(56.6), "R11": ba32(24.1),
        "R12": 1, "R13": 300, "R14": 40,
        "R15": 2026, "R16": 4, "R17": 29, "R18": 6, "R19": 30, "R20": 0,
        "R21": 120, "R22": 600, "R23": 300, "R24": 255, "R25": "None", "R26": 0}})


def job_acknowledge(*, ordinal: int) -> dict:
    return _finish({"type": 102, "ordinal": ordinal, "fields": {
        "A1": JOB_ID, "A2": "SYNREQ01", "A3": "SYNTASK01", "A4": 200, "A5": "SYNRDR", "A6": 20,
        "A7": sa32(57.6), "A8": ba32(24.1), "A9": sa32(57.6), "A10": ba32(25.1),
        "A11": sa32(56.6), "A12": ba32(25.1), "A13": sa32(56.6), "A14": ba32(24.1),
        "A15": 1, "A16": 600, "A17": 300, "A18": 1,
        "A19": 2026, "A20": 4, "A21": 29, "A22": 6, "A23": 32, "A24": 0, "A25": "ZZ"}})


def unsupported(*, ordinal: int, code: int, body: bytes) -> dict:
    return _finish({"type": code, "ordinal": ordinal, "unsupported": g.reserved_name(code),
                    "raw_hex": body.hex()})


def packet(segments: list[dict], *, p7: int = 129, job: int = JOB_ID,
           p4: int = P4_UNCLASSIFIED, p5: str = NATIONALITY, p6: int = P6_TWO_BITS) -> dict:
    """A whole packet, with `P2` and every ordinal derived rather than declared."""
    ordered = []
    for index, segment in enumerate(segments):
        segment = dict(segment)
        segment["ordinal"] = index
        ordered.append(segment)
    size = g.PACKET_HEADER_BYTES + sum(s["size"] for s in ordered)
    return {"header": {
        "P1": g.VERSION_ID, "P2": size, "P3": NATIONALITY, "P4": p4, "P5": p5, "P6": p6,
        "P7": p7, "P8": PLATFORM, "P9": MISSION_ID, "P10": job,
    }, "segments": ordered}


# ------------------------------------------------------------------ target reports

HI_RES = ("D32.1", "D32.2", "D32.3", "D32.6", "D32.7", "D32.8", "D32.9", "D32.10", "D32.11")
DELTA = ("D32.4", "D32.5", "D32.10")


def hi_res_target(*, index: int, lat: float, lon: float, height_m: int = 40,
                  los_cm_s: int = -450, wrap_cm_s: int = 3000, snr_db: int = 17,
                  classification: int = 130, probability: int = 70) -> dict:
    return {"D32.1": index, "D32.2": sa32(lat), "D32.3": ba32(lon), "D32.6": height_m,
            "D32.7": los_cm_s, "D32.8": wrap_cm_s, "D32.9": snr_db,
            "D32.10": classification, "D32.11": probability}


def delta_target(*, delta_lat: int, delta_lon: int, classification: int = 130) -> dict:
    return {"D32.4": delta_lat, "D32.5": delta_lon, "D32.10": classification}


CASES: dict[str, dict] = {}

# 1 — the base case. Mission + Job Definition + one Dwell with three hi-res target reports, each
#     with a different classification so the mapping table is exercised in one packet: a wheeled
#     vehicle (PLATFORM), a person (UNKNOWN, and the CAT021 divergence) and a ground rotator
#     (UNKNOWN, which is amendment 1 — it was FACILITY in Phase 1).
#     THIS IS THE HAND-VERIFIED FIXTURE. Its first 71 bytes are asserted against a byte layout
#     written out from Tables 3-1, 3-6 and 3-7 in `test_cdm_gmtif_adapter.py`.
CASES["mission_dwell_hi_res_targets"] = packet([
    mission(),
    job_definition(ordinal=1),
    dwell(fields=dwell_mandatory(d5=3), target_fields=HI_RES, targets=[
        hi_res_target(index=0, lat=57.10, lon=24.50, classification=130),
        hi_res_target(index=1, lat=57.12, lon=24.52, classification=137, snr_db=9),
        hi_res_target(index=2, lat=57.14, lon=24.54, classification=146, snr_db=22),
    ]),
])

# 2 — the sparsest conformant Dwell Segment: nine Mandatory fields, nothing else, and a target
#     report carrying only the hi-res location pair. One mask-decode bug shifts every field after
#     it, so the sparse and full cases have to be a matched pair.
CASES["sparse_mask_minimum_dwell"] = packet([
    mission(),
    dwell(fields=dwell_mandatory(d5=1), target_fields=("D32.2", "D32.3"),
          targets=[{"D32.2": sa32(57.02), "D32.3": ba32(24.41)}]),
])

# 3 — the other half of that pair: every Conditional and Optional group the row set names, all
#     satisfied at once. D32.2/D32.3 are present so D32.4/D32.5 and D10/D11 are absent — the
#     exclusive group means a full mask still cannot set every bit.
CASES["full_mask_every_optional_group"] = packet([
    mission(),
    job_definition(ordinal=1),
    dwell(fields={
        **dwell_mandatory(d5=2),
        "D12": 250, "D13": 310, "D14": 190,
        "D15": ba16(91.5), "D16": 120_000, "D17": -2,
        "D18": 3, "D19": 900, "D20": 400,
        "D21": ba16(92.0), "D22": sa16(1.5), "D23": sa16(-4.0),
        "D28": ba16(270.0), "D29": sa16(-12.0), "D30": sa16(0.5),
        "D31": 30,
    }, target_fields=(
        "D32.1", "D32.2", "D32.3", "D32.6", "D32.7", "D32.8", "D32.9", "D32.10", "D32.11",
        "D32.12", "D32.13", "D32.14", "D32.15", "D32.18",
    ), targets=[
        {**hi_res_target(index=0, lat=57.06, lon=24.42, classification=2),
         "D32.12": 800, "D32.13": 140, "D32.14": 12, "D32.15": 90, "D32.18": -14},
        {**hi_res_target(index=1, lat=57.08, lon=24.44, classification=1),
         "D32.12": 820, "D32.13": 150, "D32.14": 13, "D32.15": 95, "D32.18": -10},
    ]),
])

# 4 — Annex C-3's own worked example, reproduced exactly: reference date one day earlier and
#     D6 = 117,935,200 ms, which the standard says is 08:45:35.2 UTC of the NEXT day. Exact
#     addition, no modulo, and the number in the row set and the number in this fixture are the
#     same number on purpose.
CASES["multi_day_dwell_time"] = packet([
    mission(year=2026, month=4, day=28),
    dwell(fields=dwell_mandatory(d5=1, d6=117_935_200), target_fields=("D32.2", "D32.3"),
          targets=[{"D32.2": sa32(57.00), "D32.3": ba32(24.30)}]),
])

# 5 — reduced-bandwidth target reports whose dwell area STRADDLES THE PRIME MERIDIAN. This is the
#     fixture the integer-domain reconstruction exists for: the reference longitude is just east
#     of 0 and one delta is negative, so a float-degrees implementation puts that target 360 deg
#     away and the golden file catches it.
CASES["delta_targets_across_the_prime_meridian"] = packet([
    mission(),
    dwell(fields={
        **dwell_mandatory(d5=3),
        "D24": sa32(51.50), "D25": ba32(0.02),
        "D10": sa32(0.0001), "D11": ba32(0.0002),
    }, target_fields=DELTA, targets=[
        delta_target(delta_lat=120, delta_lon=90, classification=2),
        # Negative delta longitude against a reference of +0.02 deg: the recovered longitude
        # underflows past zero and the guide's mod-2^32 wrap is what lands it near 359.9 deg,
        # which reduces to a small NEGATIVE longitude.
        delta_target(delta_lat=-80, delta_lon=-300, classification=10),
        delta_target(delta_lat=0, delta_lon=0, classification=17),
    ]),
])

# 6 — a Dwell Segment and a Platform Location Segment in one packet, so the platform Track holds
#     BOTH kinds of instant and `platform_track_basis.mixed` is true. Amendment 3's whole point.
CASES["platform_location_mixed_time_basis"] = packet([
    mission(),
    dwell(fields=dwell_mandatory(d5=1, d6=30_600_000),
          target_fields=("D32.2", "D32.3", "D32.10"),
          targets=[{"D32.2": sa32(57.04), "D32.3": ba32(24.44), "D32.10": 6}]),
    platform_location(ordinal=2, l1=30_660_000),
    platform_location(ordinal=3, l1=30_720_000, lat=57.36, lon=24.79, track=95.0),
])

# 7 — P7 = 2, "Operation, Synthesized Data … a mix of real and simulated data". It contradicts
#     neither a purely-real nor a purely-synthetic declaration, so it PARKS VISIBLY with no
#     refusal — amendment 2's third branch, which the Phase 1 reading resolved onto the boolean.
CASES["synthesized_data_parks_without_refusal"] = packet([
    mission(),
    dwell(fields=dwell_mandatory(d5=1), target_fields=("D32.2", "D32.3", "D32.10"),
          targets=[{"D32.2": sa32(57.03), "D32.3": ba32(24.43), "D32.10": 4}]),
], p7=2)

# 8 — target reports whose D32.10 declares them simulated, under a P7 that also says simulated.
#     Neither writes source.synthetic; the classification is parked in full.
CASES["simulated_classifications_never_flip_synthetic"] = packet([
    mission(),
    dwell(fields=dwell_mandatory(d5=4), target_fields=("D32.2", "D32.3", "D32.10"), targets=[
        {"D32.2": sa32(57.00), "D32.3": ba32(24.40), "D32.10": 129},
        # 144 is Clutter, Simulated — and 144 - 128 = 16 is Ground Rotator LIVE, which is what an
        # arithmetic decoder would say. The golden file is where the lookup-not-arithmetic rule
        # stops being prose.
        {"D32.2": sa32(57.01), "D32.3": ba32(24.41), "D32.10": 144},
        {"D32.2": sa32(57.02), "D32.3": ba32(24.42), "D32.10": 148},
        {"D32.2": sa32(57.03), "D32.3": ba32(24.43), "D32.10": 255},
    ]),
], p7=1)

# 9 — a Tagging Device report (142) beside a simulated one (129) and a reserved one (200). The
#     label-keyed exemption is visible in the basis text; the case where it BITES needs a purely
#     real P7 and therefore synthetic=False, so it lives in the unit tests.
CASES["tagging_device_beside_simulated_targets"] = packet([
    mission(),
    dwell(fields=dwell_mandatory(d5=3),
          target_fields=("D32.10", "D32.2", "D32.3", "D32.16", "D32.17"), targets=[
        {"D32.10": 142, "D32.2": sa32(57.20), "D32.3": ba32(24.60),
         "D32.16": 64, "D32.17": 909_001},
        {"D32.10": 129, "D32.2": sa32(57.21), "D32.3": ba32(24.61),
         "D32.16": 3, "D32.17": 909_002},
        {"D32.10": 200, "D32.2": sa32(57.22), "D32.3": ba32(24.62),
         "D32.16": 0, "D32.17": 0},
    ]),
], p7=1)

# 10 — a reserved segment type and a REGISTERED Controlled Extension between two supported
#      segments. Both are skipped by S2, parked with their bytes, and recorded; the Dwell Segment
#      after them must still decode correctly, which is what proves the skip was exact.
CASES["reserved_and_extension_segments_recorded"] = packet([
    mission(),
    unsupported(ordinal=1, code=8, body=bytes(range(0x40, 0x4A))),
    unsupported(ordinal=2, code=132, body=b"\xde\xad\xbe\xef"),
    dwell(fields=dwell_mandatory(d5=1), target_fields=("D32.2", "D32.3"),
          targets=[{"D32.2": sa32(57.09), "D32.3": ba32(24.49)}]),
])

# 11 — an HRR Segment whose H2/H3 name the Dwell Segment beside it, so the observed_at chain's
#      second step runs; and a second whose H2/H3 name a dwell that is not in this packet, so the
#      third step runs and the reference lands in unresolved_references.
CASES["hrr_signature_parked_both_time_branches"] = packet([
    mission(),
    dwell(fields=dwell_mandatory(d5=1), target_fields=("D32.1", "D32.2", "D32.3"),
          targets=[{"D32.1": 0, "D32.2": sa32(57.15), "D32.3": ba32(24.55)}]),
    hrr(ordinal=2, revisit=3, dwell_index=11),
    hrr(ordinal=3, revisit=9, dwell_index=99, scatterers=b"\xaa\xbb"),
])

# 12 — the two segments that state no time of any kind, so observed_at falls to the receipt
#      instant with the basis saying so. T5 bit 4 is a failed DATALINK, which is the most
#      gradeable thing in the format and is still INFO.
CASES["free_text_and_test_status"] = packet([
    mission(),
    free_text(ordinal=1, text="SYNTHETIC FIXTURE MESSAGE, LINE ONE\nLINE TWO"),
    test_status(ordinal=2),
])

# 13 — a two-record provenance chain: Area Filtering then Security Filtering, each naming a
#      different modifying system. Carried in full, resolved never.
CASES["processing_history_chain"] = packet([
    mission(),
    processing_history(ordinal=1, records=2),
])

# 14 — a Job Definition, a Job Request and a Job Acknowledge with NO dwell data, so P10 is 0 per
#      §3.1.10 while J1 is 77. Under a literal J1/P10 cross-check this packet is unrepresentable
#      — §3.7.1 gives J1 a floor of 1 — and the guide's own Figure 2-1 shows exactly such a
#      packet. Ambiguity 16, and this fixture is what pins the narrowing.
CASES["tasking_segments_parked_with_job_id_zero"] = packet([
    mission(),
    job_definition(ordinal=1),
    job_request(ordinal=2),
    job_acknowledge(ordinal=3),
], job=0)

# 15 — a Dwell Segment with D5 = 0 and the target-report existence-mask bits SET, which §3.4.1
#      makes conformant: "it shall be assumed that the target report fields are not present even
#      if the existence mask indicates they are". A Free Text Segment follows it, so reading one
#      byte too many corrupts a value the golden file checks. This is also gap 22's fixture: the
#      packet states that the radar looked and found nothing, and the CDM says nothing about it.
_empty = dwell(fields=dwell_mandatory(d5=0), target_fields=HI_RES, targets=[])
CASES["dwell_with_no_targets_and_target_bits_set"] = packet([
    mission(),
    _empty,
    free_text(ordinal=2, text="NO MOVERS IN DWELL"),
])

# 16 — a second Mission Segment mid-packet with the SAME reference date, plus a Platform Location
#      Segment: §3.3 sends the Mission Segment "at least once every two minutes" and guide §A.1.3
#      prefers it in every packet, so a packet carrying two is ordinary rather than exotic.
CASES["repeated_mission_segment"] = packet([
    mission(),
    platform_location(ordinal=1, l1=30_600_000),
    mission(),
    platform_location(ordinal=3, l1=30_630_000, lat=57.34, lon=24.76),
], job=0)


def write() -> int:
    HERE.mkdir(parents=True, exist_ok=True)
    for name, parsed in CASES.items():
        raw = g.encode_packet(parsed)
        # Decode what was just encoded and compare: a builder that wrote a packet the decoder
        # cannot read would ship a fixture that fails at replay time rather than at build time.
        round_tripped = g.decode_packet(raw)
        if g.encode_packet(round_tripped) != raw:
            raise SystemExit(f"{name}: encode(decode(encode(spec))) is not byte-identical")
        (HERE / f"{name}.gmti").write_bytes(raw)
        (HERE / f"{name}.parsed.json").write_text(
            json.dumps(round_tripped, indent=2, sort_keys=True) + "\n")
    return len(CASES)


if __name__ == "__main__":
    print(f"wrote {write()} twins to {HERE}")
