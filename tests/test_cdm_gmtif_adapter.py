"""The STANAG 4607 / AEDP-4607 Ed A V1 adapter: the row set and its seven amendments, executed.

FORMAT_COVERAGE.md's GMTIF section is this adapter's specification, and these tests are what makes
that a checkable claim rather than a preface. They fall into five groups:

1. **The layout tables against the row set**, in both directions, so neither can drift — 212
   fields, and a field in one and not the other fails the build.
2. **One fixture verified by hand against Annex C.** Every binary in the fixture set is produced
   by the same module the adapter decodes with, so a symmetric error would round-trip perfectly
   and be invisible. `test_the_hand_verified_fixture_matches_the_annex_c_byte_layout` writes out
   76 bytes field by field from Tables 3-1, 3-6 and 3-7 and asserts them, so the encoder and the
   decoder cannot agree with each other and disagree with the document.
3. **Every refusal, inline.** A fixture whose `to_cdm` raises is a harness FAIL, so refusals are
   unit tests with a packet built in the test — the rule the NITS set states.
4. **The seven amendments**, each asserted in the direction that would catch it being quietly
   reverted now that there is code to revert it in. Two overturned a Phase 1 reading, so those
   are asserted both ways.
5. **The round trip**, which is the claim the harness cannot make: `roundtrip` reports SKIP on
   both halves of every twin because `from_cdm()` returns binary, so
   `test_every_fixture_round_trips_byte_for_byte` is where byte-exactness is established.
"""
import datetime as _dt
import json
import pathlib
import re

import pytest

import synapse_cdm
from synapse_cdm import times
from synapse_cdm.adapters import gmtif, gmtif_codec as codec
from synapse_cdm.adapters.gmtif import GmtifAdapter, GmtifError
from synapse_cdm.enums import Affiliation, EntityType, EventType, PositionSource, Severity
from synapse_cdm.models import Entity, Event, Kinematics, Position, SourceId, Track, TrackSample

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PACKAGE / "fixtures" / "gmti"
DOC = PACKAGE / "FORMAT_COVERAGE.md"

BINARIES = sorted(FIXTURES.glob("*.gmti"))


def adapter(**kwargs) -> GmtifAdapter:
    kwargs.setdefault("clock", times.frozen_clock())
    return GmtifAdapter(**kwargs)


def _spec():
    import importlib.util
    path = FIXTURES / "spec" / "build_fixtures.py"
    spec = importlib.util.spec_from_file_location("_gmti_build", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def kinds(objects):
    return [o.model_dump(mode="json")["object_kind"] for o in objects]


def entities(objects):
    return [o for o in objects if isinstance(o, Entity)]


def tracks(objects):
    return [o for o in objects if isinstance(o, Track)]


def events(objects):
    return [o for o in objects if isinstance(o, Event)]


def targets(objects):
    return [e for e in entities(objects) if "gmti_target_report" in e.attributes]


def platform(objects):
    return next(e for e in entities(objects) if "gmti_packet" in e.attributes)


# ==================================================== the layouts against the row set

GMTIF_HEADING = "## STANAG 4607 / AEDP-4607"


def _gmtif_section() -> str:
    r"""The GMTIF section of FORMAT_COVERAGE.md, ending at the NEXT top-level heading.

    Not at a named one. These tests originally sliced to `"\n## GeoJSON"`, which was correct only
    while STANAG 4607 happened to be the last format section in the document: the ASTERIX CAT048
    row set was then written between the two, and every GMTIF row-set test began reading CAT048's
    rows as if they were GMTIF's — `test_the_row_set_claims_this_adapter` failed with 130 stale
    `not yet` rows that all belonged to a different format. Finding the next `\n## ` is the same
    rule `tests/test_cdm_format_coverage.py::_section` already uses, and it does not need editing
    again when adapter #12 lands.

    MUTATION-CHECKED, and the check found something worth writing down. Two mutations were run
    against a scratch copy of the document:

    - **A decoy `## ` section with `not yet` rows, a decoy `| Form | Range | LSB |` table and the
      string "row 17", inserted immediately after the GMTIF section.** With this helper: all four
      call sites pass. With the old brittle slice: only ONE of the four fails. That asymmetry is
      the finding — three of the four call sites assert the *presence* of something, so a slice
      that is too WIDE can only ever mask a deletion, never produce a failure. Over-inclusion is
      invisible to them by construction, which is exactly how the original defect survived
      review.
    - **A shuffle: the GeoJSON section moved to sit BEFORE the GMTIF section.** With this helper:
      all four pass. With the brittle slice: `text.index("\n## GeoJSON")` lands before the start
      index, the slice is empty, and **all four fail**. So the shuffle is the mutation that proves
      every call site is load-bearing, and the decoy is the one that proves the failure mode is
      silent.
    """
    text = DOC.read_text()
    start = text.index(GMTIF_HEADING)
    nxt = text.find("\n## ", start + len(GMTIF_HEADING))
    return text[start:nxt if nxt != -1 else len(text)]


def _row_set_fields() -> set[str]:
    """Every field identifier the GMTIF row set gives a row, read from the document."""
    section = _gmtif_section()
    found = set()
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cell = line.strip("|").split("|")[0].strip().strip("`")
        head = cell.split(" ")[0]
        if re.fullmatch(r"(?:[PSMDHJFTCLRA])(?:\d+)(?:\.\d+)?", head):
            found.add(head)
    return found


def _implemented_fields() -> set[str]:
    out = {f[0] for layout in gmtif.LAYOUTS.values() for f in layout}
    out |= {f[0] for layout in gmtif.SUBRECORDS.values() for f in layout}
    out |= {f[0] for f in gmtif.HRR_SCATTERER_MASK}
    out |= set(gmtif.STRUCTURAL_FIELDS)
    return out


def test_the_layout_tables_match_the_row_set():
    """212 fields, checked in BOTH directions so neither the code nor the document can drift.

    The failure this guards against is the one a 212-field binary format invites: implementing the
    segments that mattered for the first fixture and leaving the tasking segments, the nominal
    sensor values and the HRR signature parameters as prose. A field with a row and no layout entry
    is a specification nobody executed; a field with a layout entry and no row is behaviour nobody
    decided about.
    """
    documented, implemented = _row_set_fields(), _implemented_fields()
    assert len(implemented) == 212, (
        f"the layouts implement {len(implemented)} fields and the row set claims 212. "
        "LAYOUTS + SUBRECORDS + HRR_SCATTERER_MASK + STRUCTURAL_FIELDS must add up"
    )
    missing = sorted(documented - implemented)
    assert not missing, f"fields with a row in FORMAT_COVERAGE.md and no layout entry: {missing}"
    extra = sorted(implemented - documented)
    assert not extra, f"fields the code implements and the row set has no row for: {extra}"


def test_the_seven_structural_fields_are_named_rather_than_fudged():
    """`S1`, `S2`, `D1`, `D32`, `H1`, `H32` and `C6` are structure, not values at an offset.

    They have rows in the row set and they are what COMPUTE the offsets, so a layout entry is the
    wrong shape for them — and a count that quietly excluded them would be a fudge. `S1`/`S2` are a
    layout of their own because the S1/S2 walk reads them before it knows the segment kind.
    """
    assert set(gmtif.STRUCTURAL_FIELDS) == {"D1", "D32", "H1", "H32", "C6"}
    assert [f[0] for f in gmtif.SEGMENT_HEADER] == ["S1", "S2"]
    for field, reason in gmtif.STRUCTURAL_FIELDS.items():
        assert len(reason) > 40, f"{field} needs a stated reason, not a placeholder"
    assert gmtif.MASKED["dwell"]["mask_field"] == "D1"
    assert gmtif.MASKED["hrr"]["mask_field"] == "H1"


@pytest.mark.parametrize("name", sorted(gmtif.SEGMENT_BYTES))
def test_every_segment_layout_sums_to_the_standards_own_byte_count(name):
    """A transposed form is invisible until it shifts a field. The byte total is what catches it.

    `SEGMENT_BYTES` restates the count the standard's own table implies, and summing the layout
    against it is the cheapest possible check on fourteen transcribed tables: a `BA16` written
    where a `BA32` belongs changes the total by two.
    """
    layout = (gmtif.LAYOUTS.get(name) or gmtif.SUBRECORDS[name])
    total = sum(width if form in ("A", "REST") else codec.WIDTHS[form]
                for _field, _mco, form, width in layout)
    assert total == gmtif.SEGMENT_BYTES[name], (
        f"the {name} layout sums to {total} bytes and the standard's table implies "
        f"{gmtif.SEGMENT_BYTES[name]}"
    )


def test_the_existence_mask_bit_order_is_the_figures_own():
    """Figures 3-1 and 3-4, spot-checked at both ends and at the body/subrecord seam.

    "The most-significant bit (bit 7) of the high-order byte (byte 7) corresponds to the first
    field (D2) … where the high-order byte shall be transmitted first." So `D2` is bit 63 of the
    64-bit mask and the sixteen low bits are spare — which is what the figure's two all-spare
    bytes are.
    """
    assert gmtif.mask_bit("dwell", "D2") == 63
    assert gmtif.mask_bit("dwell", "D9") == 56        # last bit of byte 7
    assert gmtif.mask_bit("dwell", "D10") == 55       # first bit of byte 6
    assert gmtif.mask_bit("dwell", "D31") == 34
    assert gmtif.mask_bit("dwell", "D32.1") == 33
    assert gmtif.mask_bit("dwell", "D32.18") == 16    # last used bit; 15..0 are spare
    assert len(gmtif.mask_order("dwell")) == 48
    assert gmtif.mask_bit("hrr", "H2") == 39
    assert gmtif.mask_bit("hrr", "H31") == 10
    assert gmtif.mask_bit("hrr", "H32.1") == 9
    assert gmtif.mask_bit("hrr", "H32.4") == 6        # 5..0 are spare
    assert len(gmtif.mask_order("hrr")) == 34


# ==================================================== the hand-verified fixture


def test_the_hand_verified_fixture_matches_the_annex_c_byte_layout():
    """The one check the encoder and the decoder cannot pass by agreeing with each other.

    Every binary in the fixture set is written by `gmtif.encode_packet` and read back by
    `gmtif.decode_packet`, so a symmetric error — a swapped byte order, a radix point off by one,
    a field in the wrong place — round-trips perfectly and shows up nowhere. This writes out the
    first 76 bytes of `mission_dwell_hi_res_targets` FIELD BY FIELD from the standard's own
    tables, with every value's hexadecimal spelled out, and asserts them against the file.

    Table 3-1 (Packet Header, 32 bytes), Table 3-6 (Segment Header, 5) and Table 3-7 (Mission
    Segment, 39). Read the comments as the derivation: each line is one row of one table.
    """
    data = (FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes()
    expected = (
        # ---- Table 3-1, Packet Header
        b"\x34\x31"                     # P1  2 A     "41" = Edition A Version 1 (§3.1.1)
        + len(data).to_bytes(4, "big")  # P2  4 I32   the whole packet, header included (§3.1.2)
        + b"\x5A\x5A"                   # P3  2 A     "ZZ"
        + b"\x05"                       # P4  1 E8    5 = UNCLASSIFIED (Table 3-2)
        + b"\x5A\x5A"                   # P5  2 A     "ZZ"
        + b"\x00\x41"                   # P6  2 FL    bits 6 and 0 set (Table 3-4)
        + b"\x81"                       # P7  1 E8    129 = Exercise, Simulated Data (Table 3-5)
        + b"ZZSYN00001"                 # P8 10 A     exactly 10 bytes, so no 0x20 padding
        + b"\x00\x00\x10\x92"           # P9  4 I32   4242
        + b"\x00\x00\x00\x4D"           # P10 4 I32   77
        # ---- Table 3-6, Segment Header
        + b"\x01"                       # S1  1 E8    1 = Mission Segment
        + b"\x00\x00\x00\x2C"           # S2  4 I32   44 = 5 header + 39 body (§3.2.2)
        # ---- Table 3-7, Mission Segment
        + b"SYNMSN0001  "               # M1 12 A     left-justified, 0x20-padded (§2.3)
        + b"SYNFLT0001  "               # M2 12 A
        + b"\xC8"                       # M3  1 E8    200, inside Table 3-8's 57-254 Available range
        + b"SYN-CFG-1 "                 # M4 10 A
        + b"\x07\xEA"                   # M5  2 I16   2026
        + b"\x04"                       # M6  1 I8    April
        + b"\x1D"                       # M7  1 I8    29
    )
    assert len(expected) == 32 + 5 + 39, "the hand layout itself does not sum to the tables"
    assert data[:len(expected)] == expected, (
        "the hand-written Annex C layout and the encoder disagree.\n"
        f"  hand: {expected.hex()}\n"
        f"  file: {data[:len(expected)].hex()}"
    )
    # And the header the decoder reads back out of those same bytes.
    header = gmtif.decode_packet(data)["header"]
    assert header == {"P1": "41", "P2": len(data), "P3": "ZZ", "P4": 5, "P5": "ZZ", "P6": 0x41,
                      "P7": 129, "P8": "ZZSYN00001", "P9": 4242, "P10": 77}


# ==================================================== twins, round trip, hygiene


def test_the_fixture_set_is_not_silently_empty():
    assert len(BINARIES) >= 16, f"expected the GMTIF fixture set, found {len(BINARIES)} packets"
    for path in BINARIES:
        assert path.with_suffix("").with_suffix(".parsed.json").exists() or \
            (FIXTURES / f"{path.stem}.parsed.json").exists(), f"{path.name} has no parsed twin"


@pytest.mark.parametrize("path", BINARIES, ids=lambda p: p.stem)
def test_the_binary_twin_and_the_parsed_twin_produce_identical_cdm(path):
    """The decoder and the accepted-dict path are ONE behaviour, and this is what makes it so.

    `to_cdm()` takes bytes or the decoded dict. If the two produced different CDM, every golden
    file would be true of one path and unverified for the other — and the harness replays both
    halves of every twin, so the divergence would be invisible in a green run.
    """
    parsed = json.loads((FIXTURES / f"{path.stem}.parsed.json").read_text())
    from_bytes = [o.model_dump(mode="json") for o in adapter().to_cdm(path.read_bytes())]
    from_dict = [o.model_dump(mode="json") for o in adapter().to_cdm(parsed)]
    assert from_bytes == from_dict


@pytest.mark.parametrize("path", BINARIES, ids=lambda p: p.stem)
def test_every_fixture_round_trips_byte_for_byte(path):
    """`encode(to_cdm(bytes)) == bytes`. The claim the harness explicitly cannot make.

    `_check_roundtrip` compares structures and `from_cdm()` returns binary, so the harness reports
    SKIP on both halves of every twin with a message saying the adapter must ship this test. Here
    it is, and it is a STRONGER claim than the harness's: not "no value went missing" but "the
    emitted packet is the same bytes".
    """
    raw = path.read_bytes()
    objects = adapter().to_cdm(raw)
    assert adapter().from_cdm(objects) == raw


@pytest.mark.parametrize("path", BINARIES, ids=lambda p: p.stem)
def test_decode_encode_is_the_identity_on_every_fixture(path):
    """The codec layer's own round trip, one level below the adapter's.

    Separated on purpose: if this fails and the test above also fails, the fault is in the codec
    or the layouts; if only the one above fails, it is in the parking or the egress assembly.
    """
    raw = path.read_bytes()
    assert gmtif.encode_packet(gmtif.decode_packet(raw)) == raw


def test_no_gmti_fixture_contains_a_uuid():
    """GMTIF carries no UUIDs, so the version-8 rule has nothing here to apply to — say so.

    The Legion and NITS fixture sets assert RFC 9562 §5.8 version 8 with an `f1c7` prefix on every
    identifier, because both formats are built on UUIDs. Every identifier on this wire is an
    alphanumeric string or an integer. Asserting the ABSENCE is what keeps the convention from
    looking forgotten in the one set it cannot apply to.
    """
    pattern = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                         r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
    for path in sorted(FIXTURES.glob("*.parsed.json")) + BINARIES:
        text = path.read_text() if path.suffix == ".json" else path.read_bytes().decode(
            "ascii", errors="replace")
        assert not pattern.search(text), f"{path.name} contains a UUID-shaped string"


def test_every_fixture_identifier_is_non_allocated_and_says_how_strong_that_claim_is():
    """`ZZ` is not in Table 3-3's national examples and is not `XN` — and nothing pins that.

    Unlike the CAT021 SAC, where `sac_pin.json` pins the ASTERIX allocation table and the
    fixture's unallocated value is asserted against it, Table 3-3 is explicitly "National
    Examples" plus "additional codes as registered with the Custodian". So this is the weakest
    identifier claim in the set, and the README is required to say so rather than implying a pin
    that does not exist.
    """
    listed = {"AL", "BE", "BU", "CA", "CR", "CZ", "DE", "ES", "FR", "GE", "GR", "HU", "IC", "IT",
              "LA", "LI", "LU", "MO", "NE", "NM", "NO", "PL", "PO", "RO", "SK", "SN", "SP", "UK",
              "US", "XN"}
    for path in sorted(FIXTURES.glob("*.parsed.json")):
        parsed = json.loads(path.read_text())
        for field in ("P3", "P5"):
            assert parsed["header"][field] not in listed, (
                f"{path.name} uses {parsed['header'][field]!r} for {field}, which Table 3-3 lists")
    readme = (FIXTURES / "README.md").read_text()
    assert "No allocation list is pinned" in readme and "weakest" in readme, (
        "the README must state that no allocation list backs the ZZ claim. A fixture set that "
        "implies a pin it does not have is the failure the CAT021 SAC pin exists to prevent"
    )


def test_the_fixture_builder_reproduces_the_committed_binaries():
    """A fixture nobody can rebuild is a fixture nobody can review.

    The build script is this set's documentation, so it has to still produce what is committed —
    otherwise the comments describe one packet and the bytes are another.
    """
    module = _spec()
    for name, parsed in module.CASES.items():
        expected = (FIXTURES / f"{name}.gmti").read_bytes()
        assert gmtif.encode_packet(parsed) == expected, f"{name} no longer builds to its committed bytes"


# ==================================================== the codec/adapter seam


def test_the_annex_c3_worked_example_is_the_fixtures_own_number():
    """Reference date 2026-04-28 plus D6 = 117 935 200 ms is 08:45:35.2 on the NEXT day.

    Annex C-3 prints exactly this arithmetic for exactly this value. Exact addition, no modulo, no
    refusal — and the fixture uses the standard's own number so the document and the packet cannot
    drift apart.
    """
    objects = adapter().to_cdm((FIXTURES / "multi_day_dwell_time.gmti").read_bytes())
    detection = events(objects)[0]
    assert times.render(detection.observed_at) == "2026-04-29T08:45:35.200Z"
    parsed = json.loads((FIXTURES / "multi_day_dwell_time.parsed.json").read_text())
    dwell = next(s for s in parsed["segments"] if s["type"] == 2)
    assert dwell["fields"]["D6"] == 117_935_200
    assert parsed["segments"][0]["fields"]["M7"] == 28
    basis = detection.payload["observed_at_basis"]
    assert "1 whole day(s) past the reference date" in basis
    assert "never a modulo" in basis


def test_a_dwell_time_beyond_a_day_is_never_reduced_modulo_a_day():
    """The repair §3.4.6 forbids, asserted directly rather than only through a fixture."""
    reference = gmtif.ReferenceDate(_dt.date(2026, 4, 28), "test")
    instant, basis = reference.at(117_935_200, field="D6", where="test")
    assert instant == _dt.datetime(2026, 4, 29, 8, 45, 35, 200_000, tzinfo=_dt.timezone.utc)
    assert instant != _dt.datetime(2026, 4, 28, 8, 45, 35, 200_000, tzinfo=_dt.timezone.utc)
    # And 41 days out, which Table 3-9 permits and which no modulo could survive.
    far, _ = reference.at(41 * gmtif.MS_PER_DAY + 1_000, field="D6", where="test")
    assert far.date() == _dt.date(2026, 6, 8)


def test_a_dwell_time_above_the_tables_maximum_converts_and_records():
    """Ambiguity 2: Table 3-9 says 4e9 ms and §3.3.7 plus Annex C-3 say the full I32 range.

    Converted, parked and recorded — refusing would reject a value two of the standard's three
    statements permit.
    """
    reference = gmtif.ReferenceDate(_dt.date(2026, 1, 1), "test")
    _instant, basis = reference.at(4_200_000_000, field="D6", where="test")
    assert "above Table 3-9's stated maximum" in basis
    assert "ambiguity 2" in basis


def test_longitudes_arrive_east_of_greenwich_and_are_reduced_exactly():
    """`BA32` covers [0, 360) and `Position.lon` is [-180, 180]. The reduction is exact."""
    assert gmtif._to_signed_longitude(24.7) == 24.7
    assert gmtif._to_signed_longitude(359.9) == pytest.approx(-0.1)
    assert gmtif._to_signed_longitude(180.0) == 180.0
    assert gmtif._to_unsigned_longitude(-0.1) == pytest.approx(359.9)


def test_the_delta_reconstruction_wraps_the_prime_meridian_and_a_float_version_would_not():
    """Guide §E.7's integer arithmetic, and the fixture that makes the difference visible.

    The dwell reference longitude is just east of 0 and one delta is negative, so the recovered
    longitude underflows past zero. The guide requires the unsigned case to be "congruent mod 2^n",
    which for a `BA32` IS the 360/0 seam — so the target lands at a small NEGATIVE longitude. A
    float-degrees implementation would put it 360 degrees away.
    """
    objects = adapter().to_cdm(
        (FIXTURES / "delta_targets_across_the_prime_meridian.gmti").read_bytes())
    longitudes = [t.position.lon for t in targets(objects)]
    assert longitudes[0] > 0, "the positive delta should stay east of Greenwich"
    assert longitudes[1] < 0, (
        f"the negative delta longitude did not wrap past zero: {longitudes[1]}. Guide §E.7 "
        "requires the unsigned case to wrap mod 2^32, which is the prime meridian"
    )
    assert -0.1 < longitudes[1] < 0, f"the wrap overshot: {longitudes[1]}"
    assert targets(objects)[0].attributes["position_basis"].startswith("delta_recovered")
    assert "guide §E.7" in targets(objects)[0].attributes["position_basis"]


def test_a_delta_report_whose_dwell_masks_out_the_scale_factors_is_refused():
    """§3.4.10's "if and only if", and the one place guessing would almost always work.

    A scale factor of zero puts every target at the dwell centre, which looks plausible on a map.
    There is nothing to default to either: the scale is chosen per dwell from the dwell's own
    extent (guide §E.7's "Choosing the Scale Factors"), so no fixed value exists.
    """
    module = _spec()
    spec = module.packet([
        module.mission(),
        module.dwell(fields=module.dwell_mandatory(d5=1),
                     target_fields=("D32.4", "D32.5"),
                     targets=[{"D32.4": 100, "D32.5": 100}]),
    ])
    with pytest.raises(GmtifError, match="SCALE FACTORS"):
        adapter().to_cdm(gmtif.encode_packet(spec))


def test_a_target_report_with_both_location_pairs_or_neither_is_refused():
    """§3.4.32.2 and §3.4.32.4 state the exclusion in both directions."""
    module = _spec()
    both = module.packet([
        module.mission(),
        module.dwell(fields={**module.dwell_mandatory(d5=1),
                             "D10": module.sa32(0.0001), "D11": module.ba32(0.0002)},
                     target_fields=("D32.2", "D32.3", "D32.4", "D32.5"),
                     targets=[{"D32.2": module.sa32(57.0), "D32.3": module.ba32(24.0),
                               "D32.4": 1, "D32.5": 1}]),
    ])
    with pytest.raises(GmtifError, match="TARGET LOCATION"):
        adapter().to_cdm(gmtif.encode_packet(both))
    neither = module.packet([
        module.mission(),
        module.dwell(fields=module.dwell_mandatory(d5=1), target_fields=("D32.9",),
                     targets=[{"D32.9": 12}]),
    ])
    with pytest.raises(GmtifError, match="TARGET LOCATION"):
        adapter().to_cdm(gmtif.encode_packet(neither))


def test_every_violated_conditional_group_is_named_in_one_refusal():
    """First-match-wins means a producer only hears about whichever check ran first.

    The STANAG 4676 segment-ordering rule, reached in a format where six groups can break at once.
    """
    module = _spec()
    spec = module.packet([
        module.mission(),
        module.dwell(fields={**module.dwell_mandatory(d5=1),
                             "D12": 250,                  # D13 and D14 absent
                             "D15": module.ba16(90.0),    # D16 and D17 absent
                             "D21": module.ba16(90.0)},   # D22 and D23 absent
                     target_fields=("D32.2", "D32.3"),
                     targets=[{"D32.2": module.sa32(57.0), "D32.3": module.ba32(24.0)}]),
    ])
    with pytest.raises(GmtifError) as caught:
        adapter().to_cdm(gmtif.encode_packet(spec))
    message = str(caught.value)
    for group in ("SENSOR POSITION UNCERTAINTY", "SENSOR VELOCITY", "PLATFORM ORIENTATION"):
        assert group in message, f"{group} is missing from the refusal: {message[:400]}"
    assert "violates 3 rule(s)" in message


def test_a_cleared_mandatory_mask_bit_is_a_refusal_quoting_the_bit():
    """Figures 3-1 and 3-4 give every Mandatory bit the value 1, and the mask sets the offsets."""
    module = _spec()
    spec = module.packet([
        module.mission(),
        module.dwell(fields=module.dwell_mandatory(d5=1), target_fields=("D32.2", "D32.3"),
                     targets=[{"D32.2": module.sa32(57.0), "D32.3": module.ba32(24.0)}]),
    ])
    # Clear D26's bit and drop the field, which is what a producer doing this would actually emit.
    segment = spec["segments"][1]
    segment["mask"] &= ~(1 << gmtif.mask_bit("dwell", "D26"))
    del segment["fields"]["D26"]
    segment.pop("size")
    segment["size"] = len(gmtif._encode_segment(segment))
    spec["header"]["P2"] = gmtif.PACKET_HEADER_BYTES + sum(s["size"] for s in spec["segments"])
    with pytest.raises(GmtifError, match="MANDATORY FIELD ABSENT: D26"):
        adapter().to_cdm(gmtif.encode_packet(spec))


def test_d5_zero_with_target_bits_set_is_conformant_and_the_next_segment_still_decodes():
    """§3.4.1's own exception to its own mask rules, and the byte that proves the skip was exact.

    "If field D5=0 … it shall be assumed that the target report fields (D32.1-D32.18) are not
    present even if the existence mask indicates they are." A reader that honoured the mask instead
    would consume bytes belonging to the Free Text Segment that follows, so the assertion on the
    text is what makes this test bite.
    """
    objects = adapter().to_cdm(
        (FIXTURES / "dwell_with_no_targets_and_target_bits_set.gmti").read_bytes())
    assert not targets(objects), "a D5 of zero must produce no target objects"
    text = next(e for e in events(objects) if "gmti_free_text" in e.payload)
    assert text.payload["gmti_free_text"]["fields"]["F3"] == "NO MOVERS IN DWELL"
    recorded = platform(objects).attributes["unresolved_raw"]
    assert any("D5 Target Report Count is 0 with target-report existence-mask bits set" in r
               for r in recorded), (
        "the override fired and must be recorded: a conformant packet whose mask says one thing "
        "and whose count says another is worth a line in the output")


def test_a_truncated_packet_is_refused_quoting_expected_against_available():
    """A partial parse of a byte-aligned format reads every later field from the wrong offset."""
    raw = (FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes()
    with pytest.raises(GmtifError, match="P2 Packet Size is"):
        adapter().to_cdm(raw[:-10])
    with pytest.raises(GmtifError, match="the Packet Header is 32"):
        adapter().to_cdm(raw[:20])


def test_a_segment_whose_s2_runs_past_the_end_is_refused():
    """`S2` is the only thing that makes a skip safe, and a skip past the end is not a skip."""
    raw = bytearray((FIXTURES / "free_text_and_test_status.gmti").read_bytes())
    # Inflate the Mission Segment's S2 without changing the packet length.
    offset = gmtif.PACKET_HEADER_BYTES + 1
    raw[offset:offset + 4] = (9999).to_bytes(4, "big")
    with pytest.raises(GmtifError, match="declares S2 = 9999"):
        adapter().to_cdm(bytes(raw))


def test_a_byte_outside_the_bcs_in_an_alphanumeric_field_is_a_refusal_quoting_the_offset():
    """Annex A: the use of ECS characters "shall be restricted to the BCS Subset". A "shall".

    Re-decoding a 0xE9 as Latin-1 would put an accented character into an operator's platform list
    that nobody transmitted; a replacement character would put a question mark there. Both are
    invented bytes, so the packet is refused and the offset is named.
    """
    raw = bytearray((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    # P1 0-1, P2 2-5, P3 6-7, P4 8, P5 9-10, P6 11-12, P7 13, P8 14-23 — so 14 is the first
    # byte of the Platform ID, and 13 is P7, which is an E8 and has no character set to violate.
    raw[14] = 0xE9
    with pytest.raises(codec.CodecError, match=r"offset 14"):
        adapter().to_cdm(bytes(raw))


def test_a_packet_from_another_edition_is_refused_with_the_version_quoted():
    """`P1` is the gate, and the reason is enumeration drift rather than structure.

    Guide Annex M item 28 moves Tagging Device from 143 to 142 and adds ten classifications
    between Edition 3 and Edition A. An Edition 3 packet decoded here misclassifies targets with
    NO structural symptom: every length checks out and the targets are the wrong kind of object.
    """
    raw = bytearray((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    raw[0:2] = b"30"
    with pytest.raises(GmtifError, match="P1 Version ID is '30'"):
        adapter().to_cdm(bytes(raw))
    assert "misclassify" in _refusal_text(bytes(raw))


def _refusal_text(raw: bytes) -> str:
    try:
        adapter().to_cdm(raw)
    except (GmtifError, codec.CodecError) as exc:
        return str(exc)
    raise AssertionError("expected a refusal")


def test_a_dwell_under_job_id_zero_is_refused():
    """§3.4: a Dwell Segment "may be sent only if the Job ID … is not equal to zero"."""
    module = _spec()
    spec = module.packet([
        module.mission(),
        module.dwell(fields=module.dwell_mandatory(d5=1), target_fields=("D32.2", "D32.3"),
                     targets=[{"D32.2": module.sa32(57.0), "D32.3": module.ba32(24.0)}]),
    ], job=0)
    with pytest.raises(GmtifError, match="P10 Job ID is 0"):
        adapter().to_cdm(gmtif.encode_packet(spec))


def test_the_job_id_cross_check_applies_only_where_the_standard_makes_the_two_equal():
    """Ambiguity 16, and the reading that keeps the guide's own Figure 2-1 conformant.

    §3.1.10 requires `P10 = 0` when the packet carries no Dwell, HRR or Range-Doppler segment, and
    §3.7.1 gives `J1` a floor of 1. So a literal `J1 == P10` check makes a Job-Definition-only
    packet — which Figure 2-1 draws — impossible to represent. The equality is therefore required
    only under §3.1.10's own condition.
    """
    objects = adapter().to_cdm(
        (FIXTURES / "tasking_segments_parked_with_job_id_zero.gmti").read_bytes())
    basis = platform(objects).attributes["job_p10_basis"]
    assert "P10 is 0 per §3.1.10" in basis and "ambiguity 16" in basis
    # And where the packet DOES carry dwell data, a mismatch is still a refusal.
    module = _spec()
    spec = module.packet([
        module.mission(),
        module.job_definition(ordinal=1, job=999),
        module.dwell(fields=module.dwell_mandatory(d5=1), target_fields=("D32.2", "D32.3"),
                     targets=[{"D32.2": module.sa32(57.0), "D32.3": module.ba32(24.0)}]),
    ])
    with pytest.raises(GmtifError, match="J1 Job ID is"):
        adapter().to_cdm(gmtif.encode_packet(spec))


# ==================================================== the reference date, amendment 4


def test_a_packet_with_a_dwell_and_no_mission_segment_is_refused():
    """Path three of three: neither the wire nor the caller stated a date."""
    module = _spec()
    spec = module.packet([
        module.dwell(fields=module.dwell_mandatory(d5=1), target_fields=("D32.2", "D32.3"),
                     targets=[{"D32.2": module.sa32(57.0), "D32.3": module.ba32(24.0)}]),
    ])
    with pytest.raises(GmtifError, match="no reference date"):
        adapter().to_cdm(gmtif.encode_packet(spec))
    assert "The\ninjected clock is NOT a third path" in _refusal_text(gmtif.encode_packet(spec)) \
        or "injected clock is NOT a third path" in _refusal_text(gmtif.encode_packet(spec))


def test_the_caller_can_supply_the_date_an_earlier_packet_stated():
    """Path two, and §3.3 is what licenses it: mission context carries across packets."""
    module = _spec()
    spec = module.packet([
        module.dwell(fields=module.dwell_mandatory(d5=1, d6=30_600_000),
                     target_fields=("D32.2", "D32.3"),
                     targets=[{"D32.2": module.sa32(57.0), "D32.3": module.ba32(24.0)}]),
    ])
    objects = adapter(mission_reference_date=_dt.date(2026, 4, 29)).to_cdm(
        gmtif.encode_packet(spec))
    detection = events(objects)[0]
    assert times.render(detection.observed_at) == "2026-04-29T08:30:00.000Z"
    assert detection.payload["reference_date_basis"].startswith("caller_supplied_stream_context")
    assert "THIS PACKET DID NOT CARRY IT" in detection.payload["reference_date_basis"]
    assert "NOT a deployment declaration" in detection.payload["reference_date_basis"]


def test_a_mission_segment_contradicting_the_callers_date_is_a_refusal_quoting_both():
    """Amendment 4b. Neither silently wins, and both failure modes are silent.

    Letting the wire win discards a caller statement that may indicate the caller has mis-tracked
    the stream. Letting the argument persist lets a stale date override the place §3.3 puts the
    answer.
    """
    raw = (FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes()
    with pytest.raises(GmtifError, match="Neither silently wins") as caught:
        adapter(mission_reference_date=_dt.date(2026, 4, 28)).to_cdm(raw)
    assert "2026-04-29" in str(caught.value) and "2026-04-28" in str(caught.value)


def test_a_caller_date_that_agrees_with_the_wire_is_not_a_contradiction():
    """The caller has simply confirmed what the packet says; the in-packet path is used."""
    raw = (FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes()
    objects = adapter(mission_reference_date=_dt.date(2026, 4, 29)).to_cdm(raw)
    basis = platform(objects).attributes["reference_date_basis"]
    assert basis.startswith("in_packet")
    assert "the caller supplied the same date, which agreed and was not used" in basis


def test_the_reference_date_provenance_is_on_every_emitted_instant():
    """Amendment 4a. A consumer holding an Event does not necessarily hold the owning Entity."""
    objects = adapter().to_cdm(
        (FIXTURES / "platform_location_mixed_time_basis.gmti").read_bytes())
    assert "reference_date_basis" in platform(objects).attributes
    for target in targets(objects):
        assert "reference_date_basis" in target.attributes
    for event in events(objects):
        assert "reference_date_basis" in event.payload, (
            f"an {event.event_type} event carries an absolute observed_at computed from the "
            "reference date and does not say where that date came from")
    for point in platform(objects).attributes["platform_track_points"]:
        assert "reference_date_basis" in point


def test_the_injected_clock_never_supplies_the_date():
    """The failure this forbids has no symptom: every other check passes.

    The frozen clock is 2026-04-29T06:15:00Z. If the clock's date leaked into the mission
    reference, a packet whose Mission Segment says 2026-04-28 would still produce instants on the
    29th — and nothing else in the output would look wrong.
    """
    objects = adapter().to_cdm((FIXTURES / "multi_day_dwell_time.gmti").read_bytes())
    detection = events(objects)[0]
    assert times.render(detection.received_at) == "2026-04-29T06:15:00.000Z"
    assert detection.observed_at.date() == _dt.date(2026, 4, 29)
    # …and the SAME packet read with a different clock produces the same observed_at.
    other = GmtifAdapter(clock=times.frozen_clock(
        _dt.datetime(2031, 1, 1, tzinfo=_dt.timezone.utc)))
    shifted = other.to_cdm((FIXTURES / "multi_day_dwell_time.gmti").read_bytes())
    assert events(shifted)[0].observed_at == detection.observed_at
    assert events(shifted)[0].received_at != detection.received_at


# ==================================================== amendment 1: no FACILITY


def test_a_rotator_classification_maps_unknown_and_never_facility():
    """Amendment 1, asserted BOTH ways because it overturned a Phase 1 reading.

    `Stationary Rotator` and `Ground Rotator` name a Doppler signature class. `FACILITY` would
    assert an installation from a motion characteristic, which is the inference this adapter
    already refuses for `M3` Platform Type.
    """
    for code in (5, 16, 133, 146):
        assert gmtif.classification_type(code) is EntityType.UNKNOWN, (
            f"D32.10 {code} ({gmtif.classification_label(code)}) maps "
            f"{gmtif.classification_type(code)}; amendment 1 makes it UNKNOWN")
    assert EntityType.FACILITY not in set(gmtif.TARGET_CLASSIFICATION.values().__iter__().__next__()
                                          .__class__ and
                                          [t for _label, t in gmtif.TARGET_CLASSIFICATION.values()]), (
        "FACILITY is back in the D32.10 table. Amendment 1 removed the only mapping that claimed "
        "it, so the collapse is now uniform: PLATFORM or UNKNOWN")
    objects = adapter().to_cdm((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    rotator = next(t for t in targets(objects)
                   if t.attributes["target_classification"] == 146)
    assert rotator.entity_type is EntityType.UNKNOWN
    assert "not about a structure" in rotator.attributes["entity_type_basis"]
    assert "refuses for M3 Platform Type" in rotator.attributes["entity_type_basis"]


def test_the_classification_mapping_is_uniform_platform_or_unknown():
    """Eighteen of the forty-three named values map, and every one of them maps to PLATFORM."""
    mapped = {code for code, (_label, kind) in gmtif.TARGET_CLASSIFICATION.items()
              if kind is not EntityType.UNKNOWN}
    assert mapped == {1, 2, 3, 4, 6, 8, 10, 17, 18,
                      129, 130, 131, 132, 134, 136, 138, 147, 148}
    assert len(mapped) == 18
    # 44 entries: the 43 named CLASSIFICATIONS the row set counts, plus 143, which Table 3-11
    # names explicitly as `Reserved` — a named value that is not a classification.
    assert len(gmtif.TARGET_CLASSIFICATION) == 44
    assert gmtif.TARGET_CLASSIFICATION[143][0] == "Reserved"
    named = {c for c, (label, _k) in gmtif.TARGET_CLASSIFICATION.items() if label != "Reserved"}
    assert len(named) == 43
    assert all(gmtif.TARGET_CLASSIFICATION[code][1] is EntityType.PLATFORM for code in mapped)
    assert all(kind in (EntityType.PLATFORM, EntityType.UNKNOWN)
               for _label, kind in gmtif.TARGET_CLASSIFICATION.values()), (
        "something other than PLATFORM or UNKNOWN is back in the D32.10 table — amendment 1 "
        "makes the collapse uniform")


def test_a_person_maps_unknown_and_the_cat021_divergence_is_stated_on_the_object():
    """Amendment 7. One concept, two answers, stated rather than resolved.

    The shipped CAT021 adapter maps emitter category 16 Parachutist to PLATFORM. This one maps
    D32.10 code 9 Person to UNKNOWN. The divergence is recorded in gap 20 with both arguments as a
    1.1.0 question, and the basis on every person object points at it.
    """
    assert gmtif.classification_type(9) is EntityType.UNKNOWN
    assert gmtif.classification_type(137) is EntityType.UNKNOWN
    objects = adapter().to_cdm((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    person = next(t for t in targets(objects) if t.attributes["target_classification"] == 137)
    assert person.entity_type is EntityType.UNKNOWN
    basis = person.attributes["entity_type_basis"]
    assert "diverges from the shipped CAT021 adapter" in basis
    assert "1.1.0 resolution question" in basis
    # The shipped adapter is untouched, and this is where that is pinned from the CDM side.
    from synapse_cdm.adapters import asterix_cat021
    assert "parachutist" in asterix_cat021.EMITTER_CATEGORY[16].lower()
    assert 16 not in asterix_cat021.EMITTER_CATEGORY_FACILITY, (
        "CAT021 emitter category 16 has become a FACILITY, which is neither adapter's answer")
    assert 16 not in asterix_cat021.EMITTER_CATEGORY_RESERVED, (
        "the CAT021 parachutist mapping has changed — it maps PLATFORM, which is the OTHER answer "
        "to this divergence. That is a published behaviour with a fixture and a golden file "
        "behind it, so changing it is a 1.1.0 question with a migration note")


def test_the_simulated_half_is_a_lookup_and_never_arithmetic():
    """`128 + n` maps to `n` for n = 0..13 and for no other n. 144-148 mirror 14-18 at +130."""
    # Written out as the mapping the table actually states, because the point is that this is a
    # LOOKUP: the halves mirror for 0..13 at +128 and then diverge.
    mirror = {n: 128 + n for n in range(14)}
    mirror.update({14: 144, 15: 145, 16: 146, 17: 147, 18: 148, 126: 254, 127: 255})
    for live, simulated in mirror.items():
        assert gmtif.classification_type(live) is gmtif.classification_type(simulated), (
            f"{live} and its mirror {simulated} map to different CDM types")
        assert simulated - live in (128, 130), f"{live} -> {simulated} is an unexpected offset"
    assert mirror[14] - 14 == 130, "14-18 mirror at +130, not +128 — the trap"
    assert 142 not in mirror.values(), "Tagging Device has no live counterpart"
    # The offset the trap lives in: 144 is Clutter-Simulated and 144 - 128 = 16 is Ground-Rotator.
    assert gmtif.classification_label(144) == "Clutter, Simulated Target"
    assert gmtif.classification_label(16) == "Ground Rotator Live"
    assert gmtif.classification_label(14) == "Clutter, Live Target"
    objects = adapter().to_cdm(
        (FIXTURES / "simulated_classifications_never_flip_synthetic.gmti").read_bytes())
    clutter = next(t for t in targets(objects)
                   if t.attributes["target_classification"] == 144)
    assert clutter.attributes["target_classification_text"] == "Clutter, Simulated Target"
    assert "+130" in clutter.attributes["entity_type_basis"]


# ==================================================== amendment 2: P7 never writes synthetic


def test_p7_never_writes_source_synthetic_and_agreement_is_not_an_exception():
    """Amendment 2, asserted both ways. It overturned a Phase 1 reading."""
    objects = adapter().to_cdm((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    entity = platform(objects)
    assert entity.source.synthetic is True                     # the DEPLOYMENT's value
    basis = entity.attributes["synthetic_basis"]
    assert "It NEVER sets source.synthetic" in basis
    assert "agreement is not an exception to that rule" in basis
    assert entity.attributes["gmti_packet"]["P7"] == 129        # parked verbatim


@pytest.mark.parametrize("p7,synthetic,expect", [
    (0, True, "PURELY real"),        # pure real against a synthetic declaration -> refusal
    (128, True, "PURELY real"),
    (1, False, "PURELY simulated"),  # pure simulated against a real declaration -> refusal
    (129, False, "PURELY simulated"),
])
def test_a_pure_p7_contradicting_the_deployment_declaration_is_a_logged_refusal(
        p7, synthetic, expect):
    module = _spec()
    spec = module.packet([module.mission()], p7=p7, job=0)
    with pytest.raises(GmtifError, match=expect):
        adapter(synthetic=synthetic).to_cdm(gmtif.encode_packet(spec))


@pytest.mark.parametrize("p7", [2, 130])
@pytest.mark.parametrize("synthetic", [True, False])
def test_synthesized_data_contradicts_neither_pure_declaration_and_never_refuses(p7, synthetic):
    """Amendment 2's third branch, and the one the Phase 1 reading resolved onto the boolean.

    §3.1.7 defines these values as "a mix of real and simulated data", so they contradict neither
    a purely-real nor a purely-synthetic declaration. Refusing would reject the case §3.1.7 exists
    to describe; resolving it onto `true` by reading `SourceRef.synthetic`'s docstring would be
    amendment B's forbidden move arrived at one step further back.
    """
    module = _spec()
    spec = module.packet([module.mission()], p7=p7, job=0)
    objects = adapter(synthetic=synthetic).to_cdm(gmtif.encode_packet(spec))
    entity = platform(objects)
    assert entity.source.synthetic is synthetic
    basis = entity.attributes["synthetic_basis"]
    assert "a mix of real and simulated data" in basis
    assert "parks visibly WITHOUT a refusal" in basis


def test_a_reserved_p7_states_nothing_and_no_conflict_check_runs():
    module = _spec()
    spec = module.packet([module.mission()], p7=50, job=0)
    for synthetic in (True, False):
        objects = adapter(synthetic=synthetic).to_cdm(gmtif.encode_packet(spec))
        basis = platform(objects).attributes["synthetic_basis"]
        assert "which Table 3-5 reserves" in basis
        assert "NOT the same as the packet not making one" in basis
        assert any("P7 = 50, reserved in Table 3-5" in r
                   for r in platform(objects).attributes["unresolved_raw"])


def test_a_simulated_target_inside_a_real_packet_is_a_separate_intra_payload_refusal():
    """Payload against payload, reported independently of the deployment check.

    `P7 = 2` — "a mix of real and simulated data" — is precisely the value this packet needed, and
    the refusal names it.
    """
    module = _spec()
    spec = module.packet([
        module.mission(),
        module.dwell(fields=module.dwell_mandatory(d5=1),
                     target_fields=("D32.2", "D32.3", "D32.10"),
                     targets=[{"D32.2": module.sa32(57.0), "D32.3": module.ba32(24.0),
                               "D32.10": 129}]),
    ], p7=0)
    with pytest.raises(GmtifError, match="INTRA-PAYLOAD contradiction") as caught:
        adapter(synthetic=False).to_cdm(gmtif.encode_packet(spec))
    message = str(caught.value)
    assert "P7 = 2" in message, "the refusal must name the value the packet needed"
    assert "different refusal from a conflict with the deployment declaration" in message


# ==================================================== amendment 6: the label-keyed exemption


def test_the_tagging_device_exemption_is_keyed_on_the_label_and_bites_under_a_real_p7():
    """Amendment 6. The value has been 140, then 143, then 142 — so the rule keys on the label.

    This is the case the fixture set cannot hold: it only bites when `P7` says purely real, which
    needs `synthetic=False`.
    """
    assert gmtif.CONFLICT_EXEMPT_LABELS == ("Tagging Device", "Reserved")
    assert gmtif._states_simulation(142) is False, "Tagging Device makes no simulation claim"
    assert gmtif._states_simulation(143) is False, "Reserved makes none either"
    assert gmtif._states_simulation(129) is True
    assert gmtif._states_simulation(144) is True
    assert gmtif._states_simulation(200) is False, "a bare reserved range is labelled Reserved"

    module = _spec()
    spec = module.packet([
        module.mission(),
        module.dwell(fields=module.dwell_mandatory(d5=1),
                     target_fields=("D32.2", "D32.3", "D32.10", "D32.16", "D32.17"),
                     targets=[{"D32.2": module.sa32(57.2), "D32.3": module.ba32(24.6),
                               "D32.10": 142, "D32.16": 64, "D32.17": 909_001}]),
    ], p7=0)
    objects = adapter(synthetic=False).to_cdm(gmtif.encode_packet(spec))
    tag = targets(objects)[0]
    assert tag.entity_type is EntityType.UNKNOWN
    assert "EXEMPTION FROM THE INTRA-PAYLOAD SIMULATION CHECK IS KEYED ON THIS LABEL" in \
        tag.attributes["entity_type_basis"]
    assert "140, then 143, then 142" in tag.attributes["entity_type_basis"]


def test_the_exemption_moves_with_the_label_if_the_number_ever_moves_again():
    """The property amendment 6 bought: renumbering the table does not change behaviour.

    Simulating the next edition — the label moving to 150 — must move the exemption with it,
    without a line of code changing. A rule keyed on 142 would silently start treating a tagging
    device as a simulated target.
    """
    original = dict(gmtif.TARGET_CLASSIFICATION)
    try:
        gmtif.TARGET_CLASSIFICATION[150] = ("Tagging Device", EntityType.UNKNOWN)
        gmtif.TARGET_CLASSIFICATION[142] = ("Reserved", EntityType.UNKNOWN)
        assert gmtif._states_simulation(150) is False
        assert gmtif._states_simulation(142) is False
    finally:
        gmtif.TARGET_CLASSIFICATION.clear()
        gmtif.TARGET_CLASSIFICATION.update(original)
    assert gmtif._states_simulation(142) is False and gmtif.classification_label(142) == \
        "Tagging Device"


def test_the_truth_tags_park_raw_under_both_readings_and_are_interpreted_as_neither():
    """The 140/142 prose is NOT re-based to 142 in code, and no SourceId is minted from D32.17."""
    objects = adapter().to_cdm(
        (FIXTURES / "tagging_device_beside_simulated_targets.gmti").read_bytes())
    tag = next(t for t in targets(objects) if t.attributes["target_classification"] == 142)
    report = tag.attributes["gmti_target_report"]
    assert report["D32.16"] == 64 and report["D32.17"] == 909_001
    systems = {sid.system for t in targets(objects) for sid in t.source_ids}
    assert systems == {"GMTIF-TARGET"}, (
        f"a SourceId was minted from something other than the positional composite: {systems}. "
        "The tag identification number is the one candidate in the format and it is deferred on a "
        "custodian's erratum")
    source = pathlib.Path(gmtif.__file__).read_text()
    assert "GMTIF-TAG" in source, "the deferred SourceId system name should still be documented"
    assert "code == 142" not in source and "D32.10\"] == 142" not in source, (
        "the prose's stale 140 must not be re-based to 142 in code: that is a translator making "
        "an editorial correction to a normative document")


# ==================================================== amendment 3: the platform track


def test_the_platform_track_parks_a_time_basis_per_sample():
    """Amendment 3. D6 is a dwell midpoint, L1 is an authoring instant, one Track holds both."""
    objects = adapter().to_cdm(
        (FIXTURES / "platform_location_mixed_time_basis.gmti").read_bytes())
    entity = platform(objects)
    points = entity.attributes["platform_track_points"]
    assert [p["time_basis"] for p in points] == ["dwell_center", "report_prepared",
                                                 "report_prepared"]
    assert [p["source_segment"] for p in points] == ["dwell", "platform_location",
                                                     "platform_location"]
    assert entity.attributes["platform_track_basis"]["mixed"] is True
    assert entity.attributes["platform_track_basis"]["counts"] == {"dwell_center": 1,
                                                                   "report_prepared": 2}
    note = entity.attributes["platform_track_basis"]["note"]
    assert "temporal center of the dwell" in note and "the time the report is prepared" in note
    assert "must\nnot smooth" in note or "must not smooth" in " ".join(note.split())
    # And the argument does NOT rest on guide §E.8.
    assert "not because guide §E.8" in " ".join(note.split())


def test_a_single_basis_track_says_so_rather_than_being_silent():
    objects = adapter().to_cdm((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    basis = platform(objects).attributes["platform_track_basis"]
    assert basis["mixed"] is False and basis["counts"] == {"dwell_center": 1}


def test_the_platform_track_is_the_only_track_and_no_target_ever_gets_one():
    """The fusion line for this format, asserted over every fixture at once."""
    for path in BINARIES:
        objects = adapter().to_cdm(path.read_bytes())
        for track in tracks(objects):
            assert track.entity_id == platform(objects).entity_id, (
                f"{path.name} produced a Track for something other than the platform")
        assert len(tracks(objects)) <= 1, f"{path.name} produced more than one Track"
        for target in targets(objects):
            assert not any(t.entity_id == target.entity_id for t in tracks(objects))
            assert "no Track" in target.attributes["track_basis"]
            assert "best recommended by the sensor manufacturer" in \
                target.attributes["track_basis"]


def test_platform_positions_running_backwards_are_refused_not_sorted():
    """Legion's rule: sorting would hide a source defect the caller needs to see."""
    module = _spec()
    spec = module.packet([
        module.mission(),
        module.platform_location(ordinal=1, l1=30_660_000),
        module.platform_location(ordinal=2, l1=30_600_000),
    ], job=0)
    with pytest.raises(GmtifError, match="run backwards in time"):
        adapter().to_cdm(gmtif.encode_packet(spec))


def test_the_platform_entity_takes_position_and_kinematics_from_the_same_sample():
    """Two instants in one Entity with nothing recording the offset is CAT021's gap 13."""
    objects = adapter().to_cdm(
        (FIXTURES / "platform_location_mixed_time_basis.gmti").read_bytes())
    entity = platform(objects)
    track = tracks(objects)[0]
    assert entity.position.lat == track.samples[-1].position.lat
    assert entity.valid_from == track.samples[-1].observed_at
    assert "from the same sample as the position" in entity.attributes["kinematics_basis"]


def test_a_dwell_with_no_sensor_velocity_yields_no_kinematics_rather_than_a_back_fill():
    objects = adapter().to_cdm((FIXTURES / "sparse_mask_minimum_dwell.gmti").read_bytes())
    entity = platform(objects)
    assert entity.position is not None
    assert entity.kinematics is None
    assert "never back-filled" in entity.attributes["kinematics_basis"]


# ==================================================== amendment 5: skip-and-record


def test_a_reserved_segment_is_skipped_by_s2_and_recorded_never_silently():
    """Amendment 5. §3.2.1's reservation plus §3.2.2's length, and never a silent skip."""
    objects = adapter().to_cdm(
        (FIXTURES / "reserved_and_extension_segments_recorded.gmti").read_bytes())
    entity = platform(objects)
    skipped = entity.attributes["source_extras"]["unsupported_segments"]
    assert [s["type"] for s in skipped] == [8, 132]
    assert skipped[0]["name"] == "Group Segment"
    assert "Releasability Segment" in skipped[1]["name"]
    assert "§L.4 empty" in skipped[1]["name"], (
        "a registered Controlled Extension must say that its field table does not exist")
    assert skipped[0]["raw_hex"] == bytes(range(0x40, 0x4A)).hex()
    assert skipped[1]["raw_hex"] == "deadbeef"
    assert skipped[0]["byte_count"] == 10
    basis = entity.attributes["unsupported_segment_basis"]
    assert "never a\nsilent skip" in basis or "never a silent skip" in " ".join(basis.split())
    assert "§3.2.1" in basis and "§3.2.2" in basis
    assert "would look like an empty dwell" in " ".join(basis.split())
    # The skip was EXACT: the Dwell Segment after the two unsupported ones still decoded.
    assert len(targets(objects)) == 1
    assert targets(objects)[0].position.lat == pytest.approx(57.09, abs=1e-6)


def test_the_module_does_not_cite_annex_g_as_authority():
    """Amendment 5 struck it. An annex whose own references name Edition 2 of 2007 is not authority.

    Asserted on the source rather than on behaviour, because the risk is a later editor
    re-justifying the skip by reaching for the convenient quote.
    """
    source = pathlib.Path(gmtif.__file__).read_text()
    assert "Subtest 18" not in source
    assert "Annex G is stale" in source, (
        "the docstring must say WHY Annex G is not cited, or the omission reads as an oversight "
        "and the citation comes back")


def test_a_controlled_extension_is_named_from_the_registry_rather_than_guessed():
    for code, name in gmtif.CONTROLLED_EXTENSIONS.items():
        assert name in gmtif.reserved_name(code)
        assert "§L.4 empty" in gmtif.reserved_name(code)
    assert gmtif.reserved_name(8) == "Group Segment"
    assert gmtif.reserved_name(50) == "Reserved for new Segments"
    assert gmtif.reserved_name(110) == "Reserved for future use"
    assert gmtif.reserved_name(200) == "Reserved for Extensions (unregistered)"


# ==================================================== the canonical fields the row set fixes


def test_accuracy_m_is_none_on_every_object_of_every_fixture():
    """Twelve uncertainty figures and not one is a horizontal 1-sigma metre value."""
    for path in BINARIES:
        objects = adapter().to_cdm(path.read_bytes())
        for entity in entities(objects):
            if entity.position is not None:
                assert entity.position.accuracy_m is None, path.name
        for track in tracks(objects):
            for sample in track.samples:
                assert sample.position.accuracy_m is None, path.name


def test_a_target_never_gets_kinematics_and_the_reason_is_on_the_object():
    """`D32.7` is ONE COMPONENT of a vector whose tangential part is unobservable."""
    objects = adapter().to_cdm((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    for target in targets(objects):
        assert target.kinematics is None
        basis = " ".join(target.attributes["kinematics_basis"].split())
        assert "along the line of sight" in basis
        assert "LOWER BOUND" in basis
        assert "Gap 21" in basis
        assert target.attributes["gmti_target_report"].get("D32.7") is not None


def test_affiliation_is_unknown_everywhere_and_nationality_is_not_read_as_one():
    for path in BINARIES:
        objects = adapter().to_cdm(path.read_bytes())
        for entity in entities(objects):
            assert entity.affiliation is Affiliation.UNKNOWN, path.name
            assert entity.symbol is None, path.name
    basis = platform(adapter().to_cdm(BINARIES[0].read_bytes())).attributes["affiliation_basis"]
    assert "P3 Nationality is the PLATFORM's country" in basis
    assert "invent a coalition membership from a country code" in " ".join(basis.split())


def test_severity_is_info_everywhere_including_a_failed_datalink():
    objects = adapter().to_cdm((FIXTURES / "free_text_and_test_status.gmti").read_bytes())
    status = next(e for e in events(objects) if "gmti_test_status" in e.payload)
    assert status.severity is Severity.INFO
    assert status.payload["hardware_failures"] == ["Datalink Status"]
    assert status.payload["mode_limits_exceeded"] == ["Temperature Limit Exceeded"]
    assert "failed\nDATALINK" in status.payload["severity_basis"] or \
        "FAILED DATALINK" in status.payload["severity_basis"]


def test_confidence_and_track_quality_are_none_and_say_why():
    objects = adapter().to_cdm((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    for entity in entities(objects):
        assert entity.confidence is None
    assert tracks(objects)[0].track_quality is None
    target = targets(objects)[0]
    assert target.attributes["gmti_target_report"]["D32.11"] == 70
    assert "70% sure this object exists" in " ".join(target.attributes["confidence_basis"].split())


def test_position_source_is_estimated_and_never_gnss():
    for path in BINARIES:
        objects = adapter().to_cdm(path.read_bytes())
        for entity in entities(objects):
            if entity.position is not None:
                assert entity.position.position_source is PositionSource.ESTIMATED, path.name


def test_the_height_unit_split_is_honoured_on_all_three_fields():
    """`D9` and `L4` are CENTIMETRES; `D32.6` is METRES. One factor for all three is 100x wrong."""
    objects = adapter().to_cdm(
        (FIXTURES / "platform_location_mixed_time_basis.gmti").read_bytes())
    parsed = json.loads((FIXTURES / "platform_location_mixed_time_basis.parsed.json").read_text())
    dwell = next(s for s in parsed["segments"] if s["type"] == 2)
    location = next(s for s in parsed["segments"] if s["type"] == 13)
    track = tracks(objects)[0]
    assert dwell["fields"]["D9"] == 850_000
    assert track.samples[0].position.alt_m == 8500.0            # centimetres / 100
    assert location["fields"]["L4"] == 860_000
    assert track.samples[1].position.alt_m == 8600.0            # centimetres / 100
    full = adapter().to_cdm((FIXTURES / "full_mask_every_optional_group.gmti").read_bytes())
    parsed_full = json.loads(
        (FIXTURES / "full_mask_every_optional_group.parsed.json").read_text())
    report = next(s for s in parsed_full["segments"] if s["type"] == 2)["targets"][0]
    assert report["D32.6"] == 40
    assert targets(full)[0].position.alt_m == 40.0              # metres, times one


def test_the_target_entity_key_is_positional_and_admits_it():
    objects = adapter().to_cdm((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    first = targets(objects)[0]
    assert first.source_ids[0].external_id == "ZZ/ZZSYN00001/4242/77/3/11/s2/r0"
    basis = " ".join(first.attributes["entity_key_basis"].split())
    assert "POSITIONAL" in basis and "re-segmentation" in basis and "Gap 20" in basis


def test_valid_to_is_none_and_the_row_set_calls_that_unsatisfactory():
    objects = adapter().to_cdm((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    for entity in entities(objects):
        assert entity.valid_to is None
    basis = " ".join(targets(objects)[0].attributes["valid_to_basis"].split())
    assert "least satisfactory" in basis and "Gap 20" in basis


def test_no_statement_values_are_kept_apart_from_masked_out_fields():
    """§2.4's fourth category: a Mandatory field present and still saying nothing."""
    objects = adapter().to_cdm((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    unavailable = platform(objects).attributes["unavailable_fields"]
    assert any(r.startswith("J24: present with its documented No-Statement value 255")
               for r in unavailable)
    assert any("J22: present with its documented No-Statement value 180.0 degrees" in r
               for r in unavailable)
    assert all("said it does not know" in r or "180.0 degrees" in r for r in unavailable)
    # A field the mask says is absent is NOT in this list.
    assert not any(r.startswith("D28") for r in unavailable)


def test_the_hrr_segment_parks_its_signature_and_takes_both_time_branches():
    objects = adapter().to_cdm(
        (FIXTURES / "hrr_signature_parked_both_time_branches.gmti").read_bytes())
    hrrs = [e for e in events(objects) if "gmti_hrr" in e.payload]
    assert len(hrrs) == 2
    assert hrrs[0].event_type is EventType.DETECTION
    # The first names the dwell beside it: observed_at is that dwell's D6.
    dwell_instant = tracks(objects)[0].samples[0].observed_at
    assert hrrs[0].observed_at == dwell_instant
    assert "H2/H3" in hrrs[0].payload["observed_at_basis"] or \
        "D6" in hrrs[0].payload["observed_at_basis"]
    # The second names a dwell that is not in the packet: the receipt instant, said so.
    assert hrrs[1].observed_at == hrrs[1].received_at
    assert "NO TIME OF ITS OWN" in hrrs[1].payload["observed_at_basis"]
    assert hrrs[1].payload["unresolved_references"]
    assert "parked whole" in hrrs[1].payload["scatterer_basis"]
    assert hrrs[1].payload["gmti_hrr"]["scatterers_hex"] == "aabb"
    assert not hrrs[0].related_entities, (
        "resolving H5 to a target report is a join even within the packet")


def test_the_processing_history_chain_is_carried_in_order_and_resolved_never():
    objects = adapter().to_cdm((FIXTURES / "processing_history_chain.gmti").read_bytes())
    event = next(e for e in events(objects) if "gmti_processing_history" in e.payload)
    assert [r["sequence"] for r in event.payload["chain"]] == [1, 2]
    assert event.payload["chain"][0]["processing_performed"] == ["Area Filtering"]
    assert event.payload["chain"][1]["processing_performed"] == ["Security Filtering"]
    assert event.payload["based_on_dataset_id"] == "ZZ/ZZSYN00001/4242/77"
    assert event.payload["unresolved_references"]
    assert "Gap 14 and gap 19" in " ".join(event.payload["resolution_basis"].split())


def test_the_absence_of_a_processing_history_segment_is_itself_recorded():
    """Guide FAQ Q11: it is not transmitted when no processing was applied."""
    with_history = adapter().to_cdm(
        (FIXTURES / "processing_history_chain.gmti").read_bytes())
    without = adapter().to_cdm((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    assert platform(with_history).attributes["processing_history_absent"] is False
    assert platform(without).attributes["processing_history_absent"] is True
    assert "the data are unmodified" in \
        " ".join(platform(without).attributes["processing_history_basis"].split())


def test_the_free_text_segment_is_carried_verbatim_and_never_parsed():
    objects = adapter().to_cdm((FIXTURES / "free_text_and_test_status.gmti").read_bytes())
    event = next(e for e in events(objects) if "gmti_free_text" in e.payload)
    assert event.payload["gmti_free_text"]["fields"]["F3"] == \
        "SYNTHETIC FIXTURE MESSAGE, LINE ONE\nLINE TWO"
    assert event.observed_at == event.received_at
    assert "NEVER parsed" in event.payload["text_basis"]
    assert "do not have any formal significance" in event.payload["originator_basis"]
    assert not any(sid.system == "GMTIF-FREETEXT" and sid.external_id == "SYNORIG"
                   for sid in event.source_ids)


def test_the_coverage_and_negative_information_basis_is_on_every_platform_entity():
    """Gap 22: a Dwell Segment with D5 = 0 is the format's primary product for an empty area."""
    objects = adapter().to_cdm(
        (FIXTURES / "dwell_with_no_targets_and_target_bits_set.gmti").read_bytes())
    basis = " ".join(platform(objects).attributes["coverage_basis"].split())
    assert "just as important as receiving targets in an area" in basis
    assert "Gap 22" in basis


# ==================================================== egress


def test_egress_of_a_round_tripped_packet_is_byte_exact_and_refuses_a_context_merge():
    """Nothing from another format's parked context may cross into an emitted packet."""
    raw_a = (FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes()
    raw_b = (FIXTURES / "free_text_and_test_status.gmti").read_bytes()
    a = adapter().to_cdm(raw_a)
    b = adapter().to_cdm(raw_b)
    assert adapter().from_cdm(a) == raw_a
    with pytest.raises(GmtifError, match="not the same packet"):
        adapter().from_cdm(a + b)


def test_egress_refuses_a_foreign_object_beside_a_round_tripped_packet():
    raw = (FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes()
    objects = adapter().to_cdm(raw)
    foreign = Entity(
        source={"system": "AIS", "adapter": "ais", "adapter_version": "1.0.0",
                "synthetic": True},
        source_ids=[SourceId(system="MMSI", external_id="299000001")],
        entity_id=objects[0].entity_id, entity_type=EntityType.PLATFORM,
        affiliation=Affiliation.UNKNOWN, valid_from=times.FROZEN_NOW,
    )
    foreign.entity_id = gmtif.ids.derive("AIS", "299000001")
    with pytest.raises(GmtifError, match="from other systems"):
        adapter().from_cdm(objects + [foreign])


def _native_platform(**overrides):
    fields = {
        "source": {"system": "TAK", "adapter": "tak", "adapter_version": "1.0.0",
                   "synthetic": True},
        "source_ids": [SourceId(system="TAK", external_id="SYN-UAV-1")],
        "entity_id": gmtif.ids.derive("TAK", "SYN-UAV-1"),
        "entity_type": EntityType.PLATFORM, "affiliation": Affiliation.UNKNOWN,
        "position": Position(lat=57.31, lon=24.72, alt_m=8500.0,
                             position_source=PositionSource.ESTIMATED),
        "kinematics": Kinematics(course_deg=92.0, speed_mps=118.0, climb_mps=-0.3),
        "valid_from": _dt.datetime(2026, 4, 29, 8, 30, tzinfo=_dt.timezone.utc),
    }
    fields.update(overrides)
    return Entity(**fields)


def test_cdm_native_egress_emits_a_mission_and_platform_location_segment_under_job_id_zero():
    """§3.1.10 provides for exactly this packet shape, so nothing has to be invented."""
    out = adapter(
        mission_reference_date=_dt.date(2026, 4, 29),
        platform_identity={"P3": "ZZ", "P8": "ZZSYN00002", "P9": 7},
        confidentiality_label={"P4": 5, "P5": "ZZ", "P6": 0},
    ).from_cdm([_native_platform()])
    parsed = gmtif.decode_packet(out)
    assert parsed["header"]["P10"] == 0, "§3.1.10 requires 0 when there is no dwell data"
    assert parsed["header"]["P8"] == "ZZSYN00002"
    assert [s["type"] for s in parsed["segments"]] == [1, 13]
    location = parsed["segments"][1]["fields"]
    assert location["L1"] == 8 * 3_600_000 + 30 * 60_000
    assert location["L2"] == pytest.approx(57.31, abs=1e-6)
    assert location["L4"] == 850_000                       # metres -> centimetres
    assert location["L6"] == 118_000                       # m/s -> mm/s
    assert location["L7"] == -3                            # m/s -> dm/s
    # And it decodes back to the same platform state.
    back = adapter().to_cdm(out)
    assert platform(back).position.lat == pytest.approx(57.31, abs=1e-6)


@pytest.mark.parametrize("kwargs,expect", [
    ({}, "platform_identity"),
    ({"platform_identity": {"P3": "ZZ", "P8": "Z1"}}, "mission_reference_date"),
])
def test_cdm_native_egress_refuses_without_the_deployment_declarations_it_needs(kwargs, expect):
    with pytest.raises(GmtifError, match=expect):
        adapter(confidentiality_label={"P4": 5, "P5": "ZZ", "P6": 0},
                **kwargs).from_cdm([_native_platform()])


def test_cdm_native_egress_refuses_a_non_platform_entity_and_names_the_seven_fields():
    """Amendment 6. A consumer forced to write its own writer must know what it has to assert.

    "Refused" on its own tells nobody anything. The message names each Mandatory field and says
    why no honest value exists for it — and `D27` is the one that settles the argument, because
    for a dwelling radar it is half the 3-dB beamwidth, which is a physical property of an antenna
    rather than a number anybody can configure.
    """
    with pytest.raises(GmtifError) as caught:
        adapter(mission_reference_date=_dt.date(2026, 4, 29),
                platform_identity={"P3": "ZZ", "P8": "Z1"},
                confidentiality_label={"P4": 5, "P5": "ZZ", "P6": 0}).from_cdm(
            [_native_platform(entity_type=EntityType.UNKNOWN)])
    message = str(caught.value)
    for field in ("D7/D8/D9", "D24/D25", "D26", "D27"):
        assert field in message, f"the refusal does not name {field}: {message[:200]}"
    assert "SIMPLE ESTIMATES FOR THE OBSERVED AREA" in message, (
        "§3.4's own words are what make these fields a statement about the OBSERVATION rather "
        "than about the deployment, which is the whole argument")
    assert "HALF THE 3-dB BEAMWIDTH" in message, (
        "D27 is the field that cannot be configured by anyone who does not own the radar, and it "
        "is what turns 'we decline' into 'nobody could'")
    assert "invented observation footprint" in message
    assert "what your writer has to be able to assert" in message, (
        "the refusal has to hand the consumer the list, or it is a dead end rather than a boundary")


def test_cdm_native_egress_refuses_a_multi_sample_track_rather_than_repeating_one_velocity():
    """Gap 16 on the egress side: L5-L7 are Mandatory per segment and the CDM holds one Kinematics."""
    entity = _native_platform()
    track = Track(
        source=entity.source, source_ids=entity.source_ids,
        track_id=gmtif.ids.derive("TAK", "SYN-UAV-1", kind="track"),
        entity_id=entity.entity_id,
        samples=[TrackSample(position=entity.position, observed_at=entity.valid_from),
                 TrackSample(position=entity.position,
                             observed_at=entity.valid_from + _dt.timedelta(minutes=1))],
    )
    with pytest.raises(GmtifError, match="more than one sample"):
        adapter(mission_reference_date=_dt.date(2026, 4, 29),
                platform_identity={"P3": "ZZ", "P8": "Z1"},
                confidentiality_label={"P4": 5, "P5": "ZZ", "P6": 0}).from_cdm([entity, track])


def test_egress_has_three_label_paths_and_a_silent_unclassified_is_forbidden():
    """`P4`, `P5` and `P6` are Mandatory on every packet, so every emitted packet needs them."""
    entity = _native_platform()
    base = dict(mission_reference_date=_dt.date(2026, 4, 29),
                platform_identity={"P3": "ZZ", "P8": "Z1"})
    # path 3: neither parked nor configured.
    with pytest.raises(GmtifError, match="no confidentiality label") as caught:
        adapter(**base).from_cdm([entity])
    assert "UNCLASSIFIED" in str(caught.value)
    assert "downgrade decision taken by a translator" in str(caught.value)
    # path 2: configured, and a partial triple is refused too.
    with pytest.raises(GmtifError, match="missing"):
        adapter(**base, confidentiality_label={"P4": 5}).from_cdm([entity])
    out = adapter(**base, confidentiality_label={"P4": 2, "P5": "ZZ", "P6": 0x0002}).from_cdm(
        [entity])
    assert gmtif.decode_packet(out)["header"]["P4"] == 2
    # path 1: the park wins over the configuration.
    raw = (FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes()
    objects = adapter().to_cdm(raw)
    assert adapter(**base, confidentiality_label={"P4": 1, "P5": "XX", "P6": 0}).from_cdm(
        objects) == raw


def test_the_parked_classification_label_is_a_triple_and_never_codeword_names():
    """`P6`'s bits mean different things in two pinned documents, so only the raw travels."""
    objects = adapter().to_cdm((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    label = platform(objects).attributes["confidentiality_label"]
    assert label == {"P4": 5, "classification": "UNCLASSIFIED", "P5": "ZZ", "system": "ZZ",
                     "P6": 0x41, "code_bits": [6, 0]}
    for forbidden in ("NOCONTRACT", "EUFOR", "ORCON", "ISAF", "PFP"):
        assert forbidden not in json.dumps(label)


# ==================================================== the row set's status column


def test_the_row_set_claims_this_adapter():
    """The status column has to move when the code does. This is the inverted Phase 1 test."""
    text = DOC.read_text()
    section = _gmtif_section()
    rows = [line for line in section.splitlines()
            if line.startswith("|") and not line.startswith("|---")]
    stale = [line for line in rows if "`not yet`" in line]
    assert not stale, (
        f"{len(stale)} GMTIF row(s) still say `not yet` while adapters/gmtif.py implements the "
        f"row set: {[r[:90] for r in stale[:3]]}")
    mapped = [line for line in rows if "`gmti 1.0.0" in line]
    assert len(mapped) >= 212, (
        f"the GMTIF row set is down to {len(mapped)} mapped rows, below the 212 fields it "
        "transcribes")
    legend = text[text.index("## The status column"):text.index("\n## Cursor-on-Target")]
    for marker in ("`gmti 1.0.0`", "`gmti 1.0.0 · parked`", "`gmti 1.0.0 · egress`"):
        assert marker in legend, f"the legend does not define {marker}"
    assert "adapters/gmtif.py" in section


# ==================================================== the harness, inside pytest


SCHEMAS = PACKAGE.parent.parent.parent / "schemas"


def test_the_harness_passes_every_fixture_against_the_published_schemas():
    """The golden gate, run in the suite rather than only from the command line.

    Without this, a change in a translation would leave 1 587 tests green and only show up when
    somebody remembered to run `python -m synapse_cdm.harness` — and it was a mutation check that
    found the hole: treating `D9` as metres rather than centimetres passed the whole suite. The
    goldens catch it, so the goldens have to be a build gate.
    """
    from synapse_cdm import harness

    report = harness.run(adapter(), FIXTURES, schema_dir=SCHEMAS)
    assert report["failed"] == 0, harness.render_report(report)
    assert report["passed"] >= 32

    for result in report["results"]:
        checks = result["checks"]
        assert checks["translate"] == "PASS", result
        assert checks["schema"] == "PASS", result
        assert checks["provenance"] == "PASS", result
        assert checks["golden"] == "PASS", result
        # The lossless check runs on the parsed twins and can only SKIP on the raw packets, which
        # have no leaf structure to harvest. Asserting the SPLIT rather than accepting "not FAIL"
        # is what stops a binaries-only fixture set from quietly disabling the never-drop rule.
        expected = "PASS" if result["fixture"].endswith(".parsed.json") else "SKIP"
        assert checks["lossless"] == expected, result
        # And roundtrip is SKIP on BOTH halves, because from_cdm returns binary and the harness
        # compares structures. That is not a gap: it is why this file ships
        # test_every_fixture_round_trips_byte_for_byte, which is a stronger claim.
        assert checks["roundtrip"] == "SKIP", result


def test_the_harness_runs_with_transforms_empty():
    """`TRANSFORMS` is a claim: every source value is present verbatim as well as converted.

    A declared transform is a hole with a reason attached, and the harness prints them on every
    run. An empty table means the never-drop check ran at full strength with nothing excused.
    """
    from synapse_cdm import harness

    report = harness.run(adapter(), FIXTURES, schema_dir=SCHEMAS)
    assert report["transforms"] == {}, (
        f"the GMTIF adapter has declared transforms: {report['transforms']}. Every decoded field "
        "is parked verbatim in attributes.gmti_packet / attributes.gmti_segments, so there should "
        "be nothing to excuse")


def test_the_harness_does_not_pick_up_the_spec_directory_or_the_readme():
    """`run()` replays every FILE through `to_cdm()`, so the builder and the README must not be one."""
    from synapse_cdm import harness

    report = harness.run(adapter(), FIXTURES, schema_dir=SCHEMAS)
    names = {result["fixture"] for result in report["results"]}
    assert "README.md" not in names
    assert "build_fixtures.py" not in names
    assert len(names) == 2 * len(BINARIES), (
        f"{len(names)} fixtures replayed for {len(BINARIES)} packets — every case must be a twin")


# ==================================================== the Phase 2 amendments
#
# Six amendments applied on review of 3d43871. Each is pinned in the direction that would catch it
# being quietly reverted, and the two that overturned a Phase 2 reading — geometry on a detection,
# and `snap` refusing rather than wrapping — are asserted BOTH ways.


def test_a_detection_event_carries_the_fix_as_a_point():
    """Amendment 1, asserted both ways. It reversed the Phase 2 reading, which was None everywhere.

    A GMTI target report IS a position measurement: the detection's location is the payload's
    primary content and `Event.geometry` is the CDM's field for where an event happened. Leaving it
    `None` put the one thing the report is about somewhere a consumer holding the `Event` alone
    cannot reach — `related_entities` is a list of ids, not a join a consumer can perform.
    """
    objects = adapter().to_cdm((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    detections = [e for e in events(objects) if e.event_type is EventType.DETECTION
                  and "gmti_target_report" in e.payload]
    assert len(detections) == 3
    for event in detections:
        assert event.geometry is not None, (
            "the Phase 2 reading is back: a DETECTION event with no geometry puts the detection's "
            "location out of reach of anything holding only the event")
        assert event.geometry.type == "Point"
        # [lon, lat], per RFC 7946 and geo._check_lonlat — and the Entity agrees.
        entity = next(e for e in targets(objects) if e.entity_id == event.related_entities[0])
        assert event.geometry.coordinates == [entity.position.lon, entity.position.lat]
        assert "IS a position measurement" in " ".join(event.payload["geometry_basis"].split())


def test_a_detection_point_has_two_coordinates_and_never_three():
    """`D32.6` Geodetic Height is Optional, so a third element would be present only sometimes.

    A `Point` whose length varies makes every consumer branch, and the height already has a
    canonical home in `Position.alt_m`. Both cases are in the fixture set: the full-mask packet
    states `D32.6` and the sparse one does not.
    """
    for name in ("full_mask_every_optional_group", "sparse_mask_minimum_dwell"):
        objects = adapter().to_cdm((FIXTURES / f"{name}.gmti").read_bytes())
        for event in events(objects):
            if event.geometry is not None:
                assert len(event.geometry.coordinates) == 2, name
    with_height = adapter().to_cdm(
        (FIXTURES / "full_mask_every_optional_group.gmti").read_bytes())
    assert targets(with_height)[0].position.alt_m == 40.0, (
        "the height must still arrive — on the Entity, which is where a state belongs")


def test_only_a_target_report_gets_a_geometry_and_the_others_say_why_not():
    """An HRR segment states range-Doppler indices in a sensor-relative space, not a position."""
    hrr_objects = adapter().to_cdm(
        (FIXTURES / "hrr_signature_parked_both_time_branches.gmti").read_bytes())
    hrrs = [e for e in events(hrr_objects) if "gmti_hrr" in e.payload]
    assert hrrs and all(e.geometry is None for e in hrrs)
    assert "sensor-relative space" in " ".join(hrrs[0].payload["geometry_basis"].split())
    text_objects = adapter().to_cdm((FIXTURES / "free_text_and_test_status.gmti").read_bytes())
    for event in events(text_objects):
        assert event.geometry is None
        assert event.event_type is EventType.STATUS_CHANGE


def test_where_a_detections_position_lives_diverges_across_four_adapters():
    """Amendment 1's cost: one concept, two answers, four shipped adapters. Stated, not resolved.

    `stanag4676.py` and `gmtif.py` put a detection's fix in `Event.geometry`; `asterix_cat021.py`
    and `adsb.py` leave it `None`. All four are published behaviours with fixtures and golden files
    behind them, so this is a 1.1.0 question with a migration note — the I021/170 precedent — and
    all four sides are pinned so it cannot be settled by accident.
    """
    import pathlib as _p
    from synapse_cdm.adapters import adsb, asterix_cat021, stanag4676
    # The two that leave it None, read from the source rather than from behaviour: both construct
    # their event with a literal `geometry=None`, which is the thing that would have to change.
    for module in (asterix_cat021, adsb):
        source = _p.Path(module.__file__).read_text()
        assert "geometry=None," in source, (
            f"{module.__name__} no longer sets geometry=None on its target-report event. If it now "
            "emits a Point, the divergence recorded in gap 20 has been resolved — update the gap, "
            "the migration note and this test together")
    # The two that set a Point.
    assert "geometry=geometry" in _p.Path(stanag4676.__file__).read_text()
    objects = adapter().to_cdm((FIXTURES / "mission_dwell_hi_res_targets.gmti").read_bytes())
    assert any(e.geometry is not None for e in events(objects))
    # And the gap has to carry both arguments, or whoever settles it inherits a majority.
    gaps = DOC.read_text()
    gap20 = gaps[gaps.index("20. **No detection"):gaps.index("21. **No home for a radar")]
    flat = " ".join(gap20.split())
    assert "WHERE A DETECTION'S POSITION LIVES" in flat
    assert "For a `Point` (the NITS and GMTIF answer)" in flat
    assert "For `None` (the CAT021 and ADS-B answer)" in flat
    assert "1.1.0" in flat
    for name in ("stanag4676.py", "gmtif.py", "asterix_cat021.py", "adsb.py"):
        assert name in flat, f"gap 20's divergence table does not name {name}"


def test_the_multi_sample_refusal_names_the_single_sample_exit():
    """Amendment 2. The refusal stands; what changed is that it hands the caller the way out.

    Truncating a history has a cost, so it is the caller's decision to take visibly rather than
    this adapter's to take silently — but a refusal that does not name the alternative reads as
    "egress does not work", which is not the decision.
    """
    entity = _native_platform()
    track = Track(
        source=entity.source, source_ids=entity.source_ids,
        track_id=gmtif.ids.derive("TAK", "SYN-UAV-1", kind="track"),
        entity_id=entity.entity_id,
        samples=[TrackSample(position=entity.position,
                             observed_at=entity.valid_from - _dt.timedelta(minutes=1)),
                 TrackSample(position=entity.position, observed_at=entity.valid_from)],
    )
    configured = dict(mission_reference_date=_dt.date(2026, 4, 29),
                      platform_identity={"P3": "ZZ", "P8": "Z1"},
                      confidentiality_label={"P4": 5, "P5": "ZZ", "P6": 0})
    with pytest.raises(GmtifError) as caught:
        adapter(**configured).from_cdm([entity, track])
    message = str(caught.value)
    assert "THE EXIT IS EXPLICIT AND IT IS YOURS" in message
    assert "single-sample Track" in message
    assert "at the time the report is prepared" in message, (
        "the reason has to be the standard's: L5 and L6 are each defined at the report's own "
        "instant, so repeating the latest velocity onto an earlier one fabricates a Mandatory "
        "measurement")
    assert "gap 16" in message
    # And the exit works: the last sample alone emits a valid packet.
    single = Track(
        source=entity.source, source_ids=entity.source_ids, track_id=track.track_id,
        entity_id=entity.entity_id, samples=[track.samples[-1]],
    )
    out = adapter(**configured).from_cdm([entity, single])
    assert [s["type"] for s in gmtif.decode_packet(out)["segments"]] == [1, 13]
    # …as does the Entity alone, which needs no Track at all.
    assert adapter(**configured).from_cdm([entity]) == out


def test_the_h6_h7_record_count_collision_is_recorded_and_not_merely_sidestepped():
    """Amendment 3. Parking the array is right; leaving the reason unwritten was not.

    The adapter never needs the count, so the contradiction cost nothing to sidestep — which is
    exactly why it would have gone unrecorded, and a Phase 3 author decoding the array has to
    resolve it first.
    """
    # Scoped to the ambiguity ROW, not to the whole section: the H6/H7 sentences also appear in
    # the field rows and in the adapter's own conditional-group refusal, so a section-wide check
    # would pass on those and the row could be deleted without anything noticing.
    text = DOC.read_text()
    rows = [line for line in text.splitlines() if line.startswith("| 17 | **`H6` and `H7`")]
    assert len(rows) == 1, "ambiguity 17, the H6/H7 record-count collision, is gone"
    row = " ".join(rows[0].split())
    assert "are reported in this segment" in row, "H6's own words"
    assert "shall define the total number of scatterer records" in row, "H7's own words"
    assert "Either H6 or H7 or both must be reported" in row, (
        "the sentence both paragraphs end with is what makes the collision reachable rather than "
        "hypothetical")
    assert "sparse" in row.lower() and "carrying **both**" in row, (
        "the unresolved case has to be NAMED: a sparse chip reporting both, where the two "
        "disagree about how many records follow")
    assert "written justification for the hex-blob parking" in row
    assert "custodian's act" in row and "Phase 3 author" in row, (
        "the row has to say whose act the resolution is and who will need it, or it reads as a "
        "note rather than as a handover")
    flat = " ".join(_gmtif_section().split())
    assert "row 17" in flat, "row 14 must cross-reference it, per the amendment-H discipline"
    # And the behaviour the row justifies: the array is bounded by S2, not by H6 or H7.
    objects = adapter().to_cdm(
        (FIXTURES / "hrr_signature_parked_both_time_branches.gmti").read_bytes())
    hrrs = [e for e in events(objects) if "gmti_hrr" in e.payload]
    assert hrrs[0].payload["gmti_hrr"]["scatterers_hex"] == "10203040"
    assert "bounded by S2" in " ".join(hrrs[0].payload["scatterer_basis"].split())
    # H25/H26 are still validated, because they size a record under EVERY reading.
    module = _spec()
    spec = module.packet([module.mission(), module.hrr(ordinal=1)], job=0)
    spec["segments"][1]["fields"]["H25"] = 3
    spec["segments"][1].pop("size")
    spec["segments"][1]["size"] = len(gmtif._encode_segment(spec["segments"][1]))
    spec["header"]["P2"] = gmtif.PACKET_HEADER_BYTES + sum(s["size"] for s in spec["segments"])
    with pytest.raises(GmtifError, match="SCATTERER RECORD WIDTH"):
        adapter().to_cdm(gmtif.encode_packet(spec))


@pytest.mark.parametrize("form,value", [
    ("SA32", 95.0), ("SA32", -95.0), ("SA16", 90.0), ("BA32", 400.0), ("BA32", -5.0),
    ("BA16", 720.0), ("B16", 300.0), ("B16", -256.0), ("H32", 40000.0), ("I16", 70000.0),
])
def test_snap_refuses_a_value_outside_the_field_and_never_wraps_or_clamps(form, value):
    """Amendment 4b, asserted both ways. The Phase 2 implementation WRAPPED, which is the worst.

    It masked the encoded integer to the field's width, so `snap("SA32", 95.0)` returned **-85.0**
    — a latitude on the other side of the equator — and `snap("B16", 300.0)` returned -44.0.
    Clamping to the boundary would have been less bad and still silent. Quantising to a field's own
    LSB is the format's stated resolution being applied; moving a value INTO range is not.
    """
    low, high, _lsb = codec._bounds(form)
    with pytest.raises(codec.CodecError, match="cannot carry") as caught:
        codec.snap(form, value)
    message = str(caught.value)
    assert repr(value) in message, "the refusal must quote the value"
    assert repr(low) in message and repr(high) in message, "…and the range"
    assert "neither masking it to the field width nor" in message, (
        "the message has to say what it is NOT doing, because both wrong answers look like "
        "successes to the caller")


@pytest.mark.parametrize("form,value", [
    ("SA32", 57.31), ("SA32", -89.9999), ("BA32", 24.72), ("BA32", 0.0), ("BA16", 92.0),
    ("SA16", 1.5), ("B16", 12.5), ("H32", 120.5), ("I32", 850000),
])
def test_snap_quantises_inside_the_field_because_that_is_the_formats_own_resolution(form, value):
    snapped = codec.snap(form, value)
    _low, _high, lsb = codec._bounds(form)
    assert abs(snapped - value) <= lsb / 2 + 1e-12, (
        f"snap moved {value} to {snapped}, further than half an LSB ({lsb})")
    # And the snapped value is exactly representable, which is the point.
    assert codec.from_raw(form, codec.to_raw(form, snapped)) == snapped


def test_snap_is_the_only_place_the_native_path_loses_anything_and_the_row_set_states_the_lsbs():
    """Amendment 4a. The precisions are a property of the FORMAT, listed once as such."""
    section = _gmtif_section()
    flat = " ".join(section.split())
    assert "the FORMAT'S stated resolution, not a translator's loss" in flat
    # Scoped to the resolution TABLE, sliced by its own header: every form name also appears in
    # the field rows' Form column, so a section-wide substring check would pass on those and a
    # row could be deleted with nothing noticing. That is exactly what the first version of this
    # assertion did, and a mutation check is what found it.
    lines = section.splitlines()
    header = next(i for i, line in enumerate(lines)
                  if line.startswith("| Form | Range | LSB |"))
    table = []
    for line in lines[header + 2:]:
        if not line.startswith("|"):
            break
        table.append(line)
    forms = {cell.strip() for row in table
             for cell in row.strip("|").split("|")[:1]
             for cell in cell.split("·")}
    required = {"`SA32`", "`BA32`", "`SA16`", "`BA16`", "`B16`", "`B32`", "`H32`"}
    missing = required - forms
    assert not missing, (
        f"the egress resolution table no longer lists {sorted(missing)}. Every scaled form the "
        "format uses has to state its own LSB there, because the table is what closes the "
        "'quantisation recorded nowhere' objection documentarily")
    assert len(table) >= 10, f"the resolution table is down to {len(table)} rows"
    assert "4.7 mm" in flat and "9.3 mm" in flat and "2.7 millidegrees" in flat
    assert "Quantising is legitimate; clamping and wrapping are not" in flat
    assert "came back as **−85°**" in flat, (
        "the defect amendment 4 fixed belongs on the record: a reader who sees only the rule "
        "cannot tell whether it was ever broken")
    # The round-trip path quantises nothing, which is what makes the byte-exact claim possible.
    assert "never\nquantises anything at all" in section or \
        "never quantises anything at all" in flat


def test_the_gap_for_an_observation_with_no_source_time_exists_and_names_all_three():
    """Amendment 5. A documented "Never receipt time" violated on three object kinds is a CDM gap.

    Asserted the awkward way round, like every other gap: `observed_at` must still be REQUIRED and
    there must still be no canonical basis field, so a gap quietly closed in code without the
    document being updated fails the build.
    """
    from synapse_cdm import models
    field = models.Event.model_fields["observed_at"]
    assert field.is_required(), (
        "Event.observed_at has become optional, which is one of the two proposals gap 23 makes. "
        "Update the gap, MIGRATIONS.md and models.Event.observed_at's docstring together — the "
        '"Never receipt time" wording is part of the v1.0.0 contract and rides the same release')
    for name in ("observed_at_basis", "observed_at_source", "time_basis"):
        assert name not in models.Event.model_fields, (
            f"Event.{name} now exists, which is gap 23's OTHER proposal — a typed, mandatory basis "
            "beside the instant. That is the smaller change and it leaves the wrong value in place "
            "with a label; write the decision down before the field")
    gaps = DOC.read_text()
    gap23 = gaps[gaps.index("23. **No way to carry an observation whose source states no time"):]
    flat = " ".join(gap23.split())
    for segment in ("Free Text", "Processing History", "HRR"):
        assert segment in flat, f"gap 23 must name the {segment} Segment as one of the three"
    assert "Never receipt time" in flat
    assert "payload.observed_at_basis" in flat and "convention rather than a contract" in flat, (
        "the interim has to be described as what it is: a key in an untyped dict that nothing "
        "validates and nothing requires")
    assert "Gap 13" in flat or "gap 13" in flat, (
        "the distinction from gap 13 is the whole reason this is a new number: 13 is a source "
        "stating SEVERAL instants, 23 is a source stating NONE")


def test_the_three_timeless_object_kinds_all_say_the_format_stated_no_time():
    """The interim convention, exercised on all three so none of them can quietly stop saying it."""
    seen = set()
    for name in ("free_text_and_test_status", "processing_history_chain",
                 "hrr_signature_parked_both_time_branches"):
        for event in events(adapter().to_cdm((FIXTURES / f"{name}.gmti").read_bytes())):
            if event.observed_at != event.received_at:
                continue
            basis = " ".join(event.payload["observed_at_basis"].split())
            assert basis.startswith("the injected clock"), basis
            assert "no time" in basis or "NO TIME OF ITS OWN" in basis, basis
            seen |= {k for k in ("gmti_free_text", "gmti_processing_history", "gmti_hrr")
                     if k in event.payload}
    assert seen == {"gmti_free_text", "gmti_processing_history", "gmti_hrr"}, (
        f"only {sorted(seen)} exercised the receipt-time fallback; gap 23 names three")
