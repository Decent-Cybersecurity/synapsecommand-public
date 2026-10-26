"""The capture: the chain object, `verify_capture` and its report (R15, R16, R17, RED-04 to RED-07,
RED-20, RED-V-01, OPS-21).

Every capture a test feeds the verifier is either the bundled one, a byte-level edit of it, or one
the tests' own builder assembled and chained with `json` and `hashlib` (`hla_support`), never one
the product wrote. The expected report of a refused capture follows from RED-06 by hand: a fault
on line n leaves lines 1 to n-1 verified, so `verified_seq` is n-2 (null for a fault on the header)
and `verified_bytes` the length of those lines with their LFs, both counted here from the test's
own lines. Every report is validated against the product's `verify-report` schema (CR-L03).
"""

import dataclasses
import functools
import inspect
import json
import os
import random
import re
import socket

import pytest
from jsonschema import Draft202012Validator

from hla_support import (
    FIXTURE_HEADER_SHA256, PACKAGE_ROOT, CaptureBuilder, canonical, capture_bytes, case,
    chain_lines, event_diagnostic, event_discover, event_generation_end, event_generation_start,
    event_reflect, event_remove, example_json, fixture_capture_records, fixture_json,
    one_generation,
    package_bytes, record_digest, registry, sha256_hex, strict_json,
)
import synapse_hla
from sockguard import sitecustomize as sockguard
from synapse_hla import HlaError, _fom, capture, errors, verify_capture
from synapse_hla.capture import CaptureChain, CaptureReader
from synapse_hla.limits import V1

R = "\N{REPLACEMENT CHARACTER}"

#: Where each line of the bundled capture ends, LF included: the cumulative byte lengths of its
#: ten lines (1453, 294, 343, 497, 439, 558, 558, 348, 272 and 241 bytes, each plus its LF), counted
#: on the fixture and held to it by `test_the_line_ends_are_the_fixtures`.
LINE_ENDS = (1454, 1749, 2093, 2591, 3031, 3590, 4149, 4498, 4771, 5013)
#: The digest the bundled footer carries: the chain head of the whole capture.
FIXTURE_LAST_SHA256 = "6a89145f412a43c7197fe5735a1addfa16e6452b8466be859be1612527027eb8"


@functools.cache
def fixture_bytes() -> bytes:
    return package_bytes("fixtures", "session.capture.jsonl")


def fixture_lines() -> list[bytes]:
    return fixture_bytes().split(b"\n")[:-1]


@functools.cache
def report_validator() -> Draft202012Validator:
    schema = strict_json(package_bytes("local_schemas", "verify-report.schema.json"))
    return Draft202012Validator(schema, registry=registry())


def read(path, limits=None) -> dict:
    if limits is None:
        report = verify_capture(path)
    else:
        reader = CaptureReader(path, limits=limits)
        for _ in reader.records():
            pass
        report = reader.report
    report_validator().validate(report)
    assert json.loads(json.dumps(report)) == report
    return report


def verify(tmp_path, data: bytes, limits=None) -> dict:
    path = tmp_path / "capture.jsonl"
    path.write_bytes(data)
    return read(path, limits)


def upto(lines, count: int) -> int:
    """The length of the first `count` lines with their LFs."""
    return sum(len(line) + 1 for line in lines[:count])


def assert_stopped(report, code, path, line, lines, *, frames=None):
    """RED-06: the fault on `line`; lines before it verified; capture_complete false."""
    status = "INCOMPLETE" if code == errors.E_CAPTURE_INCOMPLETE else "INVALID"
    got = {k: report[k] for k in ("status", "code", "path", "verified_seq", "verified_bytes",
                                  "capture_complete")}
    assert got == {"status": status, "code": code, "path": path,
                   "verified_seq": line - 2 if line >= 2 else None,
                   "verified_bytes": upto(lines, line - 1), "capture_complete": False}
    assert type(report["message"]) is str and report["message"]
    if frames is not None:
        assert report["frames"] == frames


def crafted(builder=None, mutate=None, *, keep=frozenset()):
    """Lines and bytes of a session built and chained by the tests' builder, `mutate`d first."""
    records = (builder if builder is not None else one_generation()).records()
    if mutate is not None:
        mutate(records)
    lines = chain_lines(records, keep=keep)
    return lines, capture_bytes(lines)


def test_the_line_ends_are_the_fixtures():
    ends, total = [], 0
    for line in fixture_lines():
        total += len(line) + 1
        ends.append(total)
    assert tuple(ends) == LINE_ENDS and len(fixture_bytes()) == LINE_ENDS[-1]


# =============================================================================== the chain object

@case("G-R15", "G-R16", paragraphs=("SPEC:68", "SPEC:72"))
def test_the_chain_reproduces_the_bundled_capture_byte_for_byte():
    """The production chain, given the parsed records, writes the bundled file exactly: canonical
    lines, seq from 1, seq 1 chained to the header bytes, every digest, the footer's included."""
    records = fixture_capture_records()
    chain = CaptureChain()
    out = [chain.header(records[0])]
    for frame in records[1:-1]:
        out.append(chain.frame(frame["generation"], int(frame["elapsed_ns"]), frame["event"]))
    footer = records[-1]
    out.append(chain.footer(footer["status"], footer["reason_code"], footer["last_generation"]))
    assert b"".join(out) == fixture_bytes()
    assert all(line.endswith(b"\n") and line.count(b"\n") == 1 for line in out)
    assert (chain.next_seq, chain.frames, chain.last_generation, chain.open_generation) == (
        10, 8, 1, None)
    assert chain.last_sha256 == FIXTURE_LAST_SHA256


@case("G-R15")
def test_the_header_record_holds_the_contract_constants_the_config_and_the_pin_map():
    """R15: capture_version 1, the profile, adapter_version 1.0.0, the full validated config, the
    dependency and FOM digests (the packaged pin map, RED-V-03) and the audit time."""
    header = fixture_capture_records()[0]
    built = capture.header_record(header["config"], pins=_fom.header_pins(),
                                  record_created_at="2026-01-01T00:00:00.000000Z")
    assert built == header
    assert (built["capture_version"], built["profile"], built["adapter_version"]) == (
        1, "SC-HLA-RPR2-OBS-1", "1.0.0")


def test_a_chain_built_session_verifies(tmp_path):
    chain = CaptureChain()
    builder = one_generation()
    header, body = builder.header, builder.body
    data = chain.header(header)
    for record in body[:-1]:
        data += chain.frame(record["generation"], int(record["elapsed_ns"]), record["event"])
    data += chain.footer("COMPLETE", None, chain.last_generation)
    assert data == builder.data()
    report = verify(tmp_path, data)
    assert (report["status"], report["verified_seq"], report["frames"]) == ("COMPLETE", 6, 5)


def _chain_after(frames=()):
    chain = CaptureChain()
    chain.header(fixture_capture_records()[0])
    for generation, elapsed, event in frames:
        chain.frame(generation, elapsed, event)
    return chain


#: (frames already written, the refused call, code, path): each a line the reader would refuse,
#: refused by the chain with the reader's code and path, before anything is returned.
CHAIN_REFUSALS = [
    ([], lambda c: c.frame(1, 0, {"type": "generation_start", "federation_name": 1.5}),
     errors.E_CAPTURE_SCHEMA, "line:2#/event/federation_name"),
    ([], lambda c: c.frame(1, 0, {"type": "generation_start", "federation_name": "x",
                                  "object_token": "o1"}),
     errors.E_CAPTURE_SCHEMA, "line:2#/event/object_token"),
    ([], lambda c: c.frame(1, 0, event_reflect()), errors.E_CAPTURE_SCHEMA, "line:2#/event/type"),
    ([], lambda c: c.frame(2, 0, event_generation_start()), errors.E_CAPTURE_SCHEMA,
     "line:2#/generation"),
    ([], lambda c: c.frame(1, 5, event_generation_start()), errors.E_CAPTURE_SCHEMA,
     "line:2#/elapsed_ns"),
    ([(1, 0, event_generation_start()), (1, 0, event_discover())],
     lambda c: c.frame(1, 0, event_discover(name="x" + chr(0xD800))),
     errors.E_CAPTURE_SCHEMA, "line:4#/event/name"),
    ([(1, 0, event_generation_start()), (1, 10, event_discover())],
     lambda c: c.frame(1, 9, event_reflect()), errors.E_CAPTURE_SCHEMA, "line:4#/elapsed_ns"),
    ([(1, 0, event_generation_start())],
     lambda c: c.frame(1, 0, event_reflect(attributes=(("Spatial", "02"), ("EntityType", "01")))),
     errors.E_CAPTURE_SCHEMA, "line:3#/event/attributes/1/name"),
    ([(1, 0, event_generation_start())], lambda c: c.footer("COMPLETE", None, 1),
     errors.E_CAPTURE_SCHEMA, "line:3#/type"),
    ([(1, 0, event_generation_start()), (1, 0, event_generation_end())],
     lambda c: c.footer("COMPLETE", None, 2), errors.E_CAPTURE_SCHEMA, "line:4#/last_generation"),
    ([], lambda c: c.footer("FAILED", None, 0), errors.E_CAPTURE_SCHEMA, "line:2#/reason_code"),
    ([], lambda c: c.footer("DONE", None, 0), errors.E_CAPTURE_SCHEMA, "line:2#/status"),
    # The header's epoch, 2026-01-01, plus 10^24 - 1 ns lies far beyond year 9998.
    ([(1, 0, event_generation_start())],
     lambda c: c.frame(1, 10 ** 24 - 1, event_reflect()), errors.E_CONFIG,
     "line:1#/config/time_policy/epoch"),
]


@case("G-R15", "G-R16")
@pytest.mark.parametrize("frames,call,code,path", CHAIN_REFUSALS,
                         ids=[f"c{i}" for i in range(len(CHAIN_REFUSALS))])
def test_the_chain_refuses_a_line_the_reader_would_refuse_and_stays_as_it_was(
        frames, call, code, path):
    chain = _chain_after(frames)
    before = (chain.next_seq, chain.last_sha256, chain.frames, chain.open_generation)
    with pytest.raises(HlaError) as info:
        call(chain)
    assert (type(info.value), info.value.code, info.value.path) == (HlaError, code, path)
    assert (chain.next_seq, chain.last_sha256, chain.frames, chain.open_generation) == before


def test_the_chain_refuses_a_header_the_reader_would_refuse():
    header = fixture_capture_records()[0]
    with pytest.raises(HlaError) as info:
        CaptureChain().header({**header, "pins": None})
    assert (info.value.code, info.value.path) == (errors.E_CAPTURE_SCHEMA, "line:1#/pins")
    bad = json.loads(json.dumps(header))
    bad["config"]["time_policy"]["epoch"] = "2026-02-30T00:00:00.000000Z"
    with pytest.raises(HlaError) as info:
        CaptureChain().header(bad)
    assert (info.value.code, info.value.path) == (
        errors.E_CONFIG, "line:1#/config/time_policy/epoch")


def test_the_chain_applies_the_line_and_frame_limits_through_the_seam():
    header = fixture_capture_records()[0]
    with pytest.raises(HlaError) as info:
        CaptureChain(limits=dataclasses.replace(V1, line_bytes=1452)).header(header)
    assert (info.value.code, info.value.path) == (errors.E_LIMIT, "line:1")
    chain = CaptureChain(limits=dataclasses.replace(V1, frames_per_session=2))
    chain.header(header)
    chain.frame(1, 0, event_generation_start())
    chain.frame(1, 0, event_discover())
    with pytest.raises(HlaError) as info:
        chain.frame(1, 0, event_generation_end())
    assert (info.value.code, info.value.path) == (errors.E_LIMIT, "line:4")


def caller_bug(exception, call, *args) -> None:
    """`call` raises exactly `exception`: HlaError is a ValueError too (CR-L01), and a caller bug
    must not be mistaken for a refused record."""
    with pytest.raises(exception) as info:
        call(*args)
    assert type(info.value) is exception


@pytest.mark.parametrize("call,exception", [
    (lambda c: c.frame("1", 0, event_generation_start()), TypeError),
    (lambda c: c.frame(True, 0, event_generation_start()), TypeError),
    (lambda c: c.frame(1, "0", event_generation_start()), TypeError),
    (lambda c: c.frame(1, -1, event_generation_start()), ValueError),
    (lambda c: c.frame(1, 10 ** 24, event_generation_start()), ValueError),
    (lambda c: c.frame(1, 0, [event_generation_start()]), TypeError),
    (lambda c: c.frame(1, 0, {"type": "generation_start", "federation_name": b"x"}), TypeError),
    (lambda c: c.header(fixture_capture_records()[0]), ValueError),
])
def test_wrong_python_arguments_are_caller_bugs(call, exception):
    chain = CaptureChain()
    chain.header(fixture_capture_records()[0])
    caller_bug(exception, call, chain)


def test_the_chain_keeps_its_order():
    caller_bug(ValueError, CaptureChain().frame, 1, 0, event_generation_start())
    caller_bug(ValueError, CaptureChain().footer, "COMPLETE", None, 0)
    chain = CaptureChain()
    chain.header(fixture_capture_records()[0])
    chain.footer("COMPLETE", None, 0)
    caller_bug(ValueError, chain.frame, 1, 0, event_generation_start())
    caller_bug(ValueError, chain.footer, "COMPLETE", None, 0)
    caller_bug(ValueError, chain.header, fixture_capture_records()[0])


@pytest.mark.parametrize("limits", [None, {}, dataclasses.asdict(V1), "V1"])
def test_the_limits_seam_takes_a_limits_object_only(tmp_path, limits):
    """OPS-21: the seam is the frozen Limits; anything else is a caller bug, for the chain and
    for the reader alike, and a subclass of Limits is not Limits either."""
    class Wider(type(V1)):
        pass

    for value in (limits, Wider(**dataclasses.asdict(V1))):
        caller_bug(TypeError, lambda v=value: CaptureChain(limits=v))
        caller_bug(TypeError, lambda v=value: CaptureReader(tmp_path / "c.jsonl", limits=v))


@pytest.mark.parametrize("flag", [1, 0, None, "yes"])
def test_the_reducers_elapsed_flag_is_a_bool(flag):
    """The line rules' one switch, which only the reducer sets (round R4: elapsed_ns may decrease
    in reduce_frame for RED-09), is exactly a bool; anything else is a caller bug."""
    from synapse_hla.capture import _LineRules
    caller_bug(TypeError, lambda: _LineRules(V1, elapsed_may_decrease=flag))
    assert _LineRules(V1, elapsed_may_decrease=True) != _LineRules(V1)
    assert _LineRules(V1) == _LineRules(V1)


# ============================================================================ the bundled capture

@case("G-R15", "G-R16", "G-R17")
def test_verify_accepts_the_bundled_capture_with_the_report_of_red_06(tmp_path):
    """The report as literals: header digest from FACTS.md, the chain head and the footer from
    the fixture, 5013 bytes (the bundle's manifest size), nine records after the header."""
    footer = fixture_capture_records()[-1]
    expected = {
        "verify_report_version": 1, "status": "COMPLETE", "code": None, "path": None,
        "message": None, "verified_seq": 9, "verified_bytes": 5013, "frames": 8,
        "header_sha256": FIXTURE_HEADER_SHA256, "last_sha256": FIXTURE_LAST_SHA256,
        "capture_complete": True, "footer": footer,
    }
    packaged = PACKAGE_ROOT / "src" / "synapse_hla" / "fixtures" / "session.capture.jsonl"
    assert read(packaged) == expected
    assert read(str(packaged)) == expected
    assert verify(tmp_path, fixture_bytes()) == expected


def test_the_public_function_takes_one_argument_and_reads_with_the_v1_limits():
    assert list(inspect.signature(verify_capture).parameters) == ["capture_path"]
    assert synapse_hla.verify_capture is capture.verify_capture
    default = inspect.signature(CaptureReader).parameters["limits"]
    assert default.kind is inspect.Parameter.KEYWORD_ONLY and default.default is V1


# ================================================================================ the five cases

@case("A-HASH", "G-R15", paragraphs=("SPEC:68",))
@pytest.mark.parametrize("line,old,new", [
    (4, b'"hex":"000100020003"', b'"hex":"000100020004"'),   # EntityIdentifier, last octet
    (5, b'"hex":"01"', b'"hex":"02"'),                       # ForceIdentifier
    (6, b'"hex":"0200', b'"hex":"0300'),                     # Spatial, the algorithm octet
    (7, b"415854a8c0", b"415854a8c1"),                       # Spatial, inside position x
])
def test_a_hex_byte_changed_without_its_hash(tmp_path, line, old, new):
    """A-HASH: E_CAPTURE_HASH at the changed line, which is where the chain breaks (its own
    sha256 no longer covers it); every line before it verified."""
    lines = fixture_lines()
    assert lines[line - 1].count(old) == 1
    lines[line - 1] = lines[line - 1].replace(old, new)
    report = verify(tmp_path, capture_bytes(lines))
    assert_stopped(report, errors.E_CAPTURE_HASH, f"line:{line}#/sha256", line, lines,
                   frames=line - 2)
    assert report["footer"] is None


@case("A-TRUNCATED", "G-R17")
@pytest.mark.parametrize("keep", [40, 1, 347])
def test_footer_removed_and_last_frame_truncated(tmp_path, keep):
    """A-TRUNCATED: E_CAPTURE_INCOMPLETE at the cut line, the verified prefix reported (seq 7,
    the first eight lines); the partial line is never parsed."""
    lines = fixture_lines()
    data = capture_bytes(lines[:8]) + lines[8][:keep]
    report = verify(tmp_path, data)
    assert_stopped(report, errors.E_CAPTURE_INCOMPLETE, "line:9", 9, lines, frames=7)
    assert (report["verified_seq"], report["verified_bytes"]) == (7, 4498)
    assert report["footer"] is None and report["last_sha256"] == fixture_capture_records()[7][
        "sha256"]


@case("A-SEQ-GAP", "G-R15", paragraphs=("SPEC:68",))
def test_a_validly_rehashed_capture_with_a_skipped_seq(tmp_path):
    """A-SEQ-GAP: seq 4 is skipped (3 is followed by 5) and every digest recomputed; the chain
    holds, the numbering does not: E_CAPTURE_SEQUENCE at line 5, seq 3 the last verified."""
    records = fixture_capture_records()
    for record in records[4:]:
        record["seq"] += 1
    lines = chain_lines(records)
    assert lines[:4] == fixture_lines()[:4]
    report = verify(tmp_path, capture_bytes(lines))
    assert_stopped(report, errors.E_CAPTURE_SEQUENCE, "line:5#/seq", 5, lines, frames=3)
    assert (report["verified_seq"], report["verified_bytes"]) == (3, 2591)


@case("G-R15", paragraphs=("SPEC:68",))
@pytest.mark.parametrize("seqs,line", [
    ((2, 3, 4, 5, 6), 2),      # seq does not start at 1
    ((1, 2, 2, 3, 4), 4),      # a repeat
    ((1, 2, 3, 4, 7), 6),      # a gap at the footer
])
def test_seq_starts_at_1_and_increments_by_one(tmp_path, seqs, line):
    def renumber(records):
        for record, seq in zip(records[1:], seqs):
            record["seq"] = seq
    builder = (CaptureBuilder().frame(1, 0, event_generation_start())
               .frame(1, 0, event_discover()).frame(1, 0, event_remove())
               .frame(1, 0, event_generation_end()).footer())
    lines, data = crafted(builder, renumber)
    assert_stopped(verify(tmp_path, data), errors.E_CAPTURE_SEQUENCE, f"line:{line}#/seq", line,
                   lines)


@case("G-R15", "G-R17", paragraphs=("SPEC:68",))
@pytest.mark.parametrize("line", [2, 10])
@pytest.mark.parametrize("member,value", [("seq", None), ("prev_sha256", None), ("sha256", None),
                                          ("sha256", "A" * 64), ("prev_sha256", "0" * 63)])
def test_every_frame_and_the_footer_carry_seq_and_both_digests(tmp_path, line, member, value):
    """R15 and R17: a frame (line 2) and the footer (line 10) each need seq, prev_sha256 and
    sha256, the digests as 64 lower-case hexadecimal characters (SPEC:68); without one, or with a
    malformed one, the record fails its schema: E_CAPTURE_SCHEMA at that member."""
    lines = fixture_lines()
    record = json.loads(lines[line - 1])
    if value is None:
        del record[member]
    else:
        record[member] = value
    lines[line - 1] = canonical(record)
    assert_stopped(verify(tmp_path, capture_bytes(lines)), errors.E_CAPTURE_SCHEMA,
                   f"line:{line}#/{member}", line, lines)


@case("G-R15", paragraphs=("SPEC:68",))
def test_seq_1_is_chained_to_the_exact_header_bytes(tmp_path):
    """R15: prev_sha256 of seq 1 is the SHA-256 of the header line's exact bytes without its LF.
    A header changed to another valid one breaks that link (E_CAPTURE_HASH at line 2), and so
    does a seq 1 chained to the header bytes with the LF."""
    lines = fixture_lines()
    changed = lines[0].replace(b'"record_created_at":"2026-01-01T00:00:00.000000Z"',
                               b'"record_created_at":"2026-01-01T00:00:00.000001Z"')
    assert changed != lines[0]
    trial = [changed] + lines[1:]
    assert_stopped(verify(tmp_path, capture_bytes(trial)), errors.E_CAPTURE_HASH,
                   "line:2#/prev_sha256", 2, trial)
    records = fixture_capture_records()
    records[1]["prev_sha256"] = canonical_sha_with_lf = sha256_hex(lines[0] + b"\n")
    records[1].pop("sha256")
    records[1]["sha256"] = record_digest(records[1])
    trial = lines[:1] + [canonical(records[1])] + lines[2:]
    assert canonical_sha_with_lf != FIXTURE_HEADER_SHA256
    assert_stopped(verify(tmp_path, capture_bytes(trial)), errors.E_CAPTURE_HASH,
                   "line:2#/prev_sha256", 2, trial)


def _space_after_first(line: bytes, token: bytes, inserted: bytes = b" ") -> bytes:
    at = line.index(token) + len(token)
    return line[:at] + inserted + line[at:]


def _type_first(line: bytes) -> bytes:
    record = json.loads(line)
    reordered = {"type": record.pop("type"), **record}
    return json.dumps(reordered, separators=(",", ":"), ensure_ascii=True).encode("ascii")


#: (line, edit): each spelling differs from the canonical one and nothing else does; the record,
#: and so every digest, is unchanged.
NONCANONICAL = [
    (4, lambda line: _space_after_first(line, b'",')),
    (6, lambda line: _space_after_first(line, b'":')),
    (3, lambda line: b" " + line),
    (2, lambda line: line + b" "),
    (1, lambda line: _space_after_first(line, b'",')),
    (10, lambda line: _space_after_first(line, b"{")),
    (5, lambda line: _space_after_first(line, b'":', b"\t")),
    (8, lambda line: _type_first(line)),
    (9, lambda line: json.dumps(json.loads(line), sort_keys=True).encode("ascii")),
]


@case("A-CANONICAL", "G-R15", paragraphs=("SPEC:68",))
@pytest.mark.parametrize("line,edit", NONCANONICAL, ids=[f"n{i}" for i in range(len(NONCANONICAL))])
def test_spaces_or_another_order_in_an_otherwise_valid_line(tmp_path, line, edit):
    """A-CANONICAL: E_CAPTURE_SCHEMA, the noncanonical representation, at that line (no
    pointer: the line as a whole is misspelled); its digests are still right."""
    lines = fixture_lines()
    edited = edit(lines[line - 1])
    assert edited != lines[line - 1] and json.loads(edited) == json.loads(lines[line - 1])
    lines[line - 1] = edited
    assert_stopped(verify(tmp_path, capture_bytes(lines)), errors.E_CAPTURE_SCHEMA,
                   f"line:{line}", line, lines)


@case("A-CANONICAL", "G-R15", paragraphs=("SPEC:68",))
@pytest.mark.parametrize("old,new", [
    (b"\\u00e9", b"\\u00E9"),                                  # an upper-case escape
    (b"\\u00e9", "\N{LATIN SMALL LETTER E WITH ACUTE}".encode("utf-8")),   # unescaped
    (b"/x", b"\\/x"),                                         # an escaped slash
    (b"\\ud83d\\ude00", b"\\ud83D\\ude00"),                   # a pair half upper-case
])
def test_an_escape_spelled_another_way_is_noncanonical(tmp_path, old, new):
    """SPEC:68: escapes in lower-case hexadecimal, slash unescaped, non-ASCII escaped."""
    name = "\N{LATIN SMALL LETTER E WITH ACUTE}/x\N{GRINNING FACE}"
    builder = (CaptureBuilder().frame(1, 0, event_generation_start())
               .frame(1, 0, event_discover(name=name)).frame(1, 0, event_generation_end())
               .footer())
    lines, data = crafted(builder)
    assert verify(tmp_path, data)["status"] == "COMPLETE"
    assert lines[2].count(old) == 1
    lines[2] = lines[2].replace(old, new)
    assert_stopped(verify(tmp_path, capture_bytes(lines)), errors.E_CAPTURE_SCHEMA, "line:3", 3,
                   lines)


# ===================================================================== RED-04: explicit refusals

def _set(index, path, value):
    def mutate(records):
        target = records[index]
        for token in path[:-1]:
            target = target[token]
        target[path[-1]] = value
    return mutate


#: (mutation of the one_generation session's records, line, pointer). Records: 0 header,
#: 1 generation_start, 2 discover, 3 reflect, 4 remove, 5 generation_end, 6 footer.
RED_04 = [
    ("float-generation", _set(2, ("generation",), 1.0), 3, "/generation"),
    ("float-seq", _set(3, ("seq",), 3.0), 4, "/seq"),
    ("float-last-generation", _set(6, ("last_generation",), 1.0), 7, "/last_generation"),
    ("float-in-header", _set(0, ("capture_version",), 1.0), 1, "/capture_version"),
    ("integer-beyond-2-53", _set(1, ("generation",), 9007199254740992), 2, "/generation"),
    ("surrogate-in-name", _set(2, ("event", "name"), "a" + chr(0xD800)), 3, "/event/name"),
    ("surrogate-in-tag-key", _set(3, ("event", chr(0xDC00)), 1), 4, f"/event/{R}"),
    ("surrogate-in-header", _set(0, ("config", "source_system"), chr(0xDBFF)), 1,
     "/config/source_system"),
    ("unsorted-attributes", _set(3, ("event", "attributes"),
                                 [{"name": "EntityType", "hex": "01"},
                                  {"name": "EntityIdentifier", "hex": "02"}]),
     4, "/event/attributes/1/name"),
    ("duplicate-attribute", _set(3, ("event", "attributes"),
                                 [{"name": "Spatial", "hex": "01"},
                                  {"name": "Spatial", "hex": "01"}]),
     4, "/event/attributes/1/name"),
    ("third-attribute-out-of-order", _set(3, ("event", "attributes"),
                                          [{"name": "A", "hex": ""}, {"name": "B", "hex": ""},
                                           {"name": "Ba", "hex": ""}, {"name": "B", "hex": ""}]),
     4, "/event/attributes/3/name"),
]


@case("G-R15", "G-R16", paragraphs=("SPEC:289", "SPEC:72"))
@pytest.mark.parametrize("mutate,line,pointer", [r[1:] for r in RED_04], ids=[r[0] for r in RED_04])
def test_what_schema_canonical_form_and_hash_would_accept_but_red_04_refuses(
        tmp_path, mutate, line, pointer):
    """RED-04: `1.0` passes jsonschema and Python's canonical round trip, and a lone surrogate or
    an unsorted attribute list passes both too; each is rechained here so that only the explicit
    check stands between it and acceptance."""
    lines, data = crafted(mutate=mutate)
    assert_stopped(verify(tmp_path, data), errors.E_CAPTURE_SCHEMA, f"line:{line}#{pointer}",
                   line, lines)


@case("G-R16", paragraphs=("SPEC:72",))
@pytest.mark.parametrize("names", [
    ("EntityIdentifier", "EntityType", "ForceIdentifier", "Spatial"),
    ("Zeta", "alpha"),          # ASCII order: every upper-case letter before every lower-case
    ("A", "AA", "B"),
    (),
])
def test_attributes_strictly_ascending_by_ascii_name_are_accepted(tmp_path, names):
    attributes = tuple((name, "00") for name in names)
    builder = (CaptureBuilder().frame(1, 0, event_generation_start())
               .frame(1, 0, event_reflect(attributes=attributes))
               .frame(1, 0, event_generation_end()).footer())
    assert verify(tmp_path, builder.data())["status"] == "COMPLETE"


def _lines_with(line_index, text: bytes):
    lines, _ = crafted()
    lines[line_index] = text
    return lines


#: (lines, the line refused, its pointer or "" for the whole line): byte-level faults the
#: tests' canonical writer cannot produce, so each is spelled out.
def _byte_level():
    lines, _ = crafted()
    frame = lines[1]
    rows = [
        ("bom-first", [b"\xef\xbb\xbf" + lines[0]] + lines[1:], 1, ""),
        ("bom-later", lines[:2] + [b"\xef\xbb\xbf" + lines[2]] + lines[3:], 3, ""),
        ("crlf", [line + b"\r" for line in lines], 1, ""),
        ("cr-as-space", lines[:1] + [frame.replace(b",", b",\r", 1)] + lines[2:], 2, ""),
        ("invalid-utf8", lines[:1] + [frame.replace(b"SC_DEMO", b"SC_\xffDEMO", 1)] + lines[2:],
         2, ""),
        ("blank-line", lines[:2] + [b""] + lines[2:], 3, ""),
        ("array-line", lines[:1] + [b"[1,2]"] + lines[1:], 2, ""),
        ("not-json", lines[:1] + [b"frame"] + lines[1:], 2, ""),
        ("deep", lines[:1] + [b"[" * 40 + b"]" * 40] + lines[1:], 2, ""),
        ("duplicate-key", lines[:1] + [frame.replace(b'{"elapsed_ns":"0",',
                                                     b'{"elapsed_ns":"0","elapsed_ns":"0",', 1)]
         + lines[2:], 2, "/elapsed_ns"),
        ("nan", lines[:1] + [frame.replace(b'"generation":1,', b'"generation":NaN,', 1)]
         + lines[2:], 2, "/generation"),
        ("exponent", lines[:1] + [frame.replace(b'"generation":1,', b'"generation":1e0,', 1)]
         + lines[2:], 2, "/generation"),
        ("negative-zero", lines[:1] + [frame.replace(b'"generation":1,', b'"generation":-0,', 1)]
         + lines[2:], 2, ""),
    ]
    for row in rows:
        assert row[1] != lines, row[0]
    return rows


BYTE_LEVEL = _byte_level()


@case("G-R15")
@pytest.mark.parametrize("lines,line,pointer", [r[1:] for r in BYTE_LEVEL],
                         ids=[r[0] for r in BYTE_LEVEL])
def test_utf8_jsonl_one_strict_object_per_lf_terminated_line(tmp_path, lines, line, pointer):
    """R15: UTF-8, no BOM, no blank line, one JSON object per line, no CR (RED-04), no duplicate
    key, no non-finite or float token; each E_CAPTURE_SCHEMA at its line."""
    path = f"line:{line}" + (f"#{pointer}" if pointer else "")
    assert_stopped(verify(tmp_path, capture_bytes(lines)), errors.E_CAPTURE_SCHEMA, path, line,
                   lines)


# ==================================================================== RED-05: lifecycle framing

START = event_generation_start()
END = event_generation_end()
DIAG = event_diagnostic()


def _session(frames, footer=("COMPLETE", None, None)):
    builder = CaptureBuilder()
    for generation, elapsed, event in frames:
        builder.frame(generation, elapsed, event)
    return builder.footer(*footer)


#: (id, frames, footer, expected): "COMPLETE"/"FAILED", or (line refused, pointer). Frame k
#: (from 0) is line k + 2.
FRAMING = [
    ("gen0-diagnostics-before-the-first-join",
     [(0, 0, DIAG), (0, 0, DIAG), (1, 0, START), (1, 5, END)], ("COMPLETE", None, 1), "COMPLETE"),
    ("gen0-diagnostics-between-generations",
     [(1, 0, START), (1, 10, END), (0, 10, DIAG), (0, 20, DIAG), (2, 30, START), (2, 40, END)],
     ("COMPLETE", None, 2), "COMPLETE"),
    ("reconnect-with-both-boundaries",
     [(1, 0, START), (1, 10, event_generation_end("connection_lost")),
      (0, 10, event_diagnostic("E_RTI_CONNECT")), (2, 20, START), (2, 30, END)],
     ("COMPLETE", None, 2), "COMPLETE"),
    ("unreachable-rti", [(0, 0, DIAG), (0, 0, DIAG), (0, 0, DIAG)],
     ("FAILED", "E_RTI_CONNECT", 0), "FAILED"),
    ("header-and-footer-only", [], ("COMPLETE", None, 0), "COMPLETE"),
    ("diagnostic-inside-a-generation",
     [(1, 0, START), (1, 0, event_diagnostic("E_RTI_TIMEOUT", token="o1")), (1, 0, END)],
     ("COMPLETE", None, 1), "COMPLETE"),
    ("equal-elapsed", [(1, 0, START), (1, 10, event_reflect()), (1, 10, event_reflect()),
                       (1, 10, END)], ("COMPLETE", None, 1), "COMPLETE"),
    ("failed-with-limit", [(1, 0, START), (1, 0, event_generation_end("limit"))],
     ("FAILED", "E_LIMIT", 1), "FAILED"),
    # refused
    ("gen0-discover-before-join", [(0, 0, event_discover())], ("COMPLETE", None, 0),
     (2, "/event/type")),
    ("gen0-frame-inside-a-generation", [(1, 0, START), (0, 0, DIAG)], ("COMPLETE", None, 1),
     (3, "/generation")),
    ("frame-after-generation-end", [(1, 0, START), (1, 0, END), (1, 0, event_reflect())],
     ("COMPLETE", None, 1), (4, "/event/type")),
    ("generation-starts-at-2", [(2, 0, START)], ("COMPLETE", None, 2), (2, "/generation")),
    ("generation-skips-one", [(1, 0, START), (1, 0, END), (3, 0, START)], ("COMPLETE", None, 3),
     (4, "/generation")),
    ("generation-repeats", [(1, 0, START), (1, 0, END), (1, 0, START)], ("COMPLETE", None, 1),
     (4, "/generation")),
    ("second-start-inside", [(1, 0, START), (1, 0, START)], ("COMPLETE", None, 1),
     (3, "/event/type")),
    ("reconnect-without-end", [(1, 0, START), (2, 10, START)], ("COMPLETE", None, 2),
     (3, "/event/type")),
    ("end-without-start", [(0, 0, END)], ("COMPLETE", None, 0), (2, "/event/type")),
    ("end-twice", [(1, 0, START), (1, 0, END), (1, 0, END)], ("COMPLETE", None, 1),
     (4, "/event/type")),
    ("other-generation-inside", [(1, 0, START), (1, 0, END), (2, 0, START),
                                 (1, 0, event_reflect())], ("COMPLETE", None, 2),
     (5, "/generation")),
    ("diagnostic-between-generations-numbered-n", [(1, 0, START), (1, 0, END), (1, 0, DIAG)],
     ("COMPLETE", None, 1), (4, "/generation")),
    ("elapsed-before-the-first-join", [(0, 5, DIAG)], ("COMPLETE", None, 0), (2, "/elapsed_ns")),
    ("first-start-not-at-zero", [(0, 0, DIAG), (1, 7, START)], ("COMPLETE", None, 1),
     (3, "/elapsed_ns")),
    ("elapsed-1-before-the-first-join", [(0, 1, DIAG)], ("COMPLETE", None, 0),
     (2, "/elapsed_ns")),
    ("first-start-at-1", [(1, 1, START)], ("COMPLETE", None, 1), (2, "/elapsed_ns")),
    ("first-start-at-1-after-diagnostics", [(0, 0, DIAG), (1, 1, START)], ("COMPLETE", None, 1),
     (3, "/elapsed_ns")),
    ("elapsed-decreases", [(1, 0, START), (1, 10, event_reflect()), (1, 9, event_reflect())],
     ("COMPLETE", None, 1), (4, "/elapsed_ns")),
    ("elapsed-decreases-across-generations",
     [(1, 0, START), (1, 100, END), (0, 99, DIAG)], ("COMPLETE", None, 1), (4, "/elapsed_ns")),
    ("footer-while-a-generation-is-open", [(1, 0, START)], ("COMPLETE", None, 1), (3, "/type")),
    ("footer-last-generation-too-high", [(1, 0, START), (1, 0, END)], ("COMPLETE", None, 7),
     (4, "/last_generation")),
    ("footer-last-generation-too-low", [(1, 0, START), (1, 0, END)], ("COMPLETE", None, 0),
     (4, "/last_generation")),
    ("complete-with-a-reason", [], ("COMPLETE", "E_IO", 0), (2, "/reason_code")),
    ("failed-without-a-reason", [], ("FAILED", None, 0), (2, "/reason_code")),
    ("failed-with-a-warning-code", [], ("FAILED", "W_FOM_UNVERIFIED", 0), (2, "/reason_code")),
    ("failed-with-an-unknown-code", [], ("FAILED", "E_NOT_A_CODE", 0), (2, "/reason_code")),
]


@case("G-R16", "G-R08", "G-R17", paragraphs=("SPEC:275",))
@pytest.mark.parametrize("frames,footer,expected", [r[1:] for r in FRAMING],
                         ids=[r[0] for r in FRAMING])
def test_lifecycle_framing(tmp_path, frames, footer, expected):
    """RED-05 as amended and OPV-01: generation-0 diagnostics while no generation is open, with
    elapsed_ns 0 up to the first generation_start; generations 1, 2, 3 in brackets of exactly one
    start and one end; elapsed_ns never decreasing over the session (R16; the origin persists
    across reconnects, SPEC:42); last_generation the highest started; COMPLETE without a reason,
    FAILED with a catalogue E_ code (R17). A reconnect stays COMPLETE only with both boundaries
    recorded. Each fault is E_CAPTURE_SCHEMA."""
    builder = _session(frames, footer)
    lines = builder.lines()
    report = verify(tmp_path, builder.data())
    if expected in ("COMPLETE", "FAILED"):
        assert (report["status"], report["code"], report["verified_seq"], report["frames"],
                report["capture_complete"], report["footer"]["status"]) == (
            expected, None, len(frames) + 1, len(frames), expected == "COMPLETE", expected)
    else:
        line, pointer = expected
        assert_stopped(report, errors.E_CAPTURE_SCHEMA, f"line:{line}#{pointer}", line, lines)


@case("G-R16")
def test_token_numbering_and_discover_metadata_are_not_verified(tmp_path):
    """RED-05: a reflect for a token never discovered (A-UNKNOWN's o99) is capturable; RED-07: an
    inconsistent rediscovery is the reducer's fault, not the capture's."""
    builder = (CaptureBuilder().frame(1, 0, START)
               .frame(1, 0, event_reflect("o99"))
               .frame(1, 0, event_discover("o1", name="A"))
               .frame(1, 0, event_discover("o1", name="B", reported_class="Other"))
               .frame(1, 0, event_remove("o5")).frame(1, 0, event_discover("o5"))
               .frame(1, 0, END).footer())
    assert verify(tmp_path, builder.data())["status"] == "COMPLETE"


# ================================================================ RED-06: ends, prefixes, order

@case("G-R17")
def test_incomplete_captures_report_the_verified_prefix(tmp_path):
    """R17 and RED-06: a missing footer or a partial final line is E_CAPTURE_INCOMPLETE with the
    first line that is missing or not whole as the path; every record ends in LF, the footer too."""
    lines = fixture_lines()
    cases = [
        (b"", 1, None, 0),
        (lines[0], 1, None, 0),                                   # the header, no LF
        (capture_bytes(lines[:1]), 2, 0, 1454),                   # the header only
        (capture_bytes(lines[:9]), 10, 8, 4771),                  # no footer
        (capture_bytes(lines), 10, 8, 4771),                      # replaced below: no final LF
        (capture_bytes(lines[:9]) + b'{"x":"\xc3', 10, 8, 4771),  # a cut inside a UTF-8 sequence
    ]
    cases[4] = (capture_bytes(lines, tail=b""), 10, 8, 4771)
    for data, line, seq, size in cases:
        report = verify(tmp_path, data)
        assert {k: report[k] for k in ("status", "code", "path", "verified_seq", "verified_bytes",
                                       "capture_complete", "footer")} == {
            "status": "INCOMPLETE", "code": "E_CAPTURE_INCOMPLETE", "path": f"line:{line}",
            "verified_seq": seq, "verified_bytes": size, "capture_complete": False,
            "footer": None}
        assert report["header_sha256"] == (FIXTURE_HEADER_SHA256 if seq is not None else None)


@case("G-R17")
def test_nothing_may_follow_the_footer(tmp_path):
    """The footer is terminal: a further line, whole or cut, is E_CAPTURE_SCHEMA at its line even
    though the footer before it verified."""
    lines = fixture_lines()
    footer = fixture_capture_records()[-1]
    for data in (capture_bytes(lines + [lines[-1]]), capture_bytes(lines) + b"{",
                 capture_bytes(lines + [lines[-2]])):
        report = verify(tmp_path, data)
        assert {k: report[k] for k in ("status", "code", "path", "verified_seq", "verified_bytes",
                                       "capture_complete", "footer")} == {
            "status": "INVALID", "code": "E_CAPTURE_SCHEMA", "path": "line:11",
            "verified_seq": 9, "verified_bytes": 5013, "capture_complete": False,
            "footer": footer}


@case("G-R17")
def test_a_failed_footer_verifies_as_failed_and_not_complete(tmp_path):
    records = fixture_capture_records()
    records[-1]["status"] = "FAILED"
    records[-1]["reason_code"] = "E_IO"
    lines = chain_lines(records)
    report = verify(tmp_path, capture_bytes(lines))
    assert {k: report[k] for k in ("status", "code", "path", "message", "verified_seq",
                                   "verified_bytes", "capture_complete")} == {
        "status": "FAILED", "code": None, "path": None, "message": None, "verified_seq": 9,
        "verified_bytes": upto(lines, 10), "capture_complete": False}
    assert report["footer"] == json.loads(lines[-1])


#: Two faults on one line: the order of RED-06 decides (UTF-8, JSON and duplicate keys, float
#: and surrogate, canonical, schema, seq, prev_sha256, sha256), then the line's place.
def _precedence():
    lines, _ = crafted()
    frame = lines[2]                         # the discover, line 3
    record = json.loads(frame)

    def rechained(change, keep_link=False, seq=None):
        changed = dict(record, **change)
        if seq is not None:
            changed["seq"] = seq
        if not keep_link:
            changed.pop("sha256")
            changed["sha256"] = record_digest(changed)
        return canonical(changed)

    return [
        ("schema-before-seq", rechained({"extra": 1}, seq=9), "E_CAPTURE_SCHEMA", "/extra"),
        ("seq-before-prev", rechained({"prev_sha256": "0" * 64}, seq=9), "E_CAPTURE_SEQUENCE",
         "/seq"),
        ("prev-before-sha", rechained({"prev_sha256": "0" * 64, "sha256": "1" * 64}, True),
         "E_CAPTURE_HASH", "/prev_sha256"),
        ("sha-alone", rechained({"sha256": "1" * 64}, True), "E_CAPTURE_HASH", "/sha256"),
        ("canonical-before-hash", _space_after_first(rechained({"sha256": "1" * 64}, True), b"{"),
         "E_CAPTURE_SCHEMA", ""),
        ("float-before-canonical",
         _space_after_first(frame.replace(b'"generation":1,', b'"generation":1.0,'), b"{"),
         "E_CAPTURE_SCHEMA", "/generation"),
        ("utf8-before-duplicate",
         frame.replace(b'{"elapsed_ns":"0",', b'{"elapsed_ns":"\xff","elapsed_ns":"0",'),
         "E_CAPTURE_SCHEMA", ""),
        ("duplicate-stage-before-float-stage",
         frame.replace(b'"generation":1,', b'"generation":1.0,')
              .replace(b'"type":"frame"}', b'"type":"frame","type":"frame"}'),
         "E_CAPTURE_SCHEMA", "/type"),
        ("duplicate-before-float-in-document-order",
         frame.replace(b'{"elapsed_ns":"0",', b'{"elapsed_ns":"0","elapsed_ns":"0",')
              .replace(b'"generation":1,', b'"generation":1.0,'),
         "E_CAPTURE_SCHEMA", "/elapsed_ns"),
        ("hash-before-framing", rechained({"elapsed_ns": "0", "generation": 0,
                                           "sha256": "1" * 64}, True), "E_CAPTURE_HASH",
         "/sha256"),
        ("seq-before-framing", rechained({"generation": 0}, seq=9), "E_CAPTURE_SEQUENCE", "/seq"),
        ("framing-alone", rechained({"generation": 0}), "E_CAPTURE_SCHEMA", "/generation"),
    ]


PRECEDENCE = _precedence()


@case("G-R15")
@pytest.mark.parametrize("line,code,pointer", [r[1:] for r in PRECEDENCE],
                         ids=[r[0] for r in PRECEDENCE])
def test_two_faults_on_one_line_follow_the_check_order(tmp_path, line, code, pointer):
    lines, _ = crafted()
    lines[2] = line
    path = "line:3" + (f"#{pointer}" if pointer else "")
    assert_stopped(verify(tmp_path, capture_bytes(lines)), code, path, 3, lines)


@case("G-R15")
def test_of_two_faulty_lines_the_first_decides(tmp_path):
    lines = fixture_lines()
    hash_broken = lines[5].replace(b'"hex":"0200', b'"hex":"0300')
    misspelled = _space_after_first(lines[3], b'",')
    first = lines[:3] + [misspelled] + lines[4:5] + [hash_broken] + lines[6:]
    assert_stopped(verify(tmp_path, capture_bytes(first)), errors.E_CAPTURE_SCHEMA, "line:4", 4,
                   first)
    second = lines[:3] + [lines[3].replace(b'"hex":"01', b'"hex":"02')] + lines[4:5] + [
        _space_after_first(lines[5], b'",')] + lines[6:]
    assert_stopped(verify(tmp_path, capture_bytes(second)), errors.E_CAPTURE_HASH,
                   "line:4#/sha256", 4, second)
    # A fault before a truncation is the result; incompleteness is never reached.
    third = lines[:3] + [misspelled] + lines[4:9]
    assert_stopped(verify(tmp_path, capture_bytes(third) + lines[9][:10]),
                   errors.E_CAPTURE_SCHEMA, "line:4", 4, third)


# ======================================================== RED-V-01: the header's configuration

def _header_with(change):
    header = fixture_capture_records()[0]
    change(header)
    return header


def _config(path, value):
    def change(header):
        target = header["config"]
        for token in path[:-1]:
            target = target[token]
        target[path[-1]] = value
    return change


#: (header change, code, path): the semantic faults RED-V-01 lists are E_CONFIG with the
#: config pointer under line 1; faults of the header's schema stay E_CAPTURE_SCHEMA.
HEADER_FAULTS = [
    ("epoch-feb-30", _config(("time_policy", "epoch"), "2026-02-30T00:00:00.000000Z"),
     "E_CONFIG", "line:1#/config/time_policy/epoch"),
    ("epoch-hour-25", _config(("time_policy", "epoch"), "2026-01-01T25:00:00.000000Z"),
     "E_CONFIG", "line:1#/config/time_policy/epoch"),
    ("epoch-1969", _config(("time_policy", "epoch"), "1969-12-31T23:59:59.999999Z"),
     "E_CONFIG", "line:1#/config/time_policy/epoch"),
    ("epoch-9999", _config(("time_policy", "epoch"), "9999-01-01T00:00:00.000000Z"),
     "E_CONFIG", "line:1#/config/time_policy/epoch"),
    ("force-key-256", _config(("force_map",), {"256": "HOSTILE"}),
     "E_CONFIG", "line:1#/config/force_map/256"),
    ("demo-not-synthetic", _config(("synthetic",), False), "E_CONFIG", "line:1#/config/synthetic"),
    ("declaration-mismatch", _config(("profile_declaration",), "external-fom-unverified"),
     "E_CONFIG", "line:1#/config/profile_declaration"),
    ("endpoint-out-of-range", _config(("endpoint",), "rti://999.1.1.1:99999"),
     "E_CONFIG", "line:1#/config/endpoint"),
    ("endpoint-remote", _config(("endpoint",), "rti://10.0.0.5:14321"),
     "E_CONFIG", "line:1#/config/endpoint"),
    ("source-control", _config(("source_system",), "a\tb"),
     "E_CONFIG", "line:1#/config/source_system"),
    ("basis-not-printable", _config(("time_policy", "basis"), "a\x7f"),
     "E_CONFIG", "line:1#/config/time_policy/basis"),
    # the header schema includes the config schema by reference
    ("config-schema", _config(("session_id",), "a b"), "E_CAPTURE_SCHEMA",
     "line:1#/config/session_id"),
    ("config-missing-member", lambda h: h["config"].pop("synthetic"), "E_CAPTURE_SCHEMA",
     "line:1#/config/synthetic"),
    # OPS-03: the audit time is checked by explicit code, never by format
    ("audit-feb-30", lambda h: h.update(record_created_at="2026-02-30T00:00:00.000000Z"),
     "E_CAPTURE_SCHEMA", "line:1#/record_created_at"),
    ("audit-1969", lambda h: h.update(record_created_at="1969-12-31T23:59:59.999999Z"),
     "E_CAPTURE_SCHEMA", "line:1#/record_created_at"),
    ("audit-milliseconds", lambda h: h.update(record_created_at="2026-01-01T00:00:00.000Z"),
     "E_CAPTURE_SCHEMA", "line:1#/record_created_at"),
    ("pins-missing", lambda h: h.pop("pins"), "E_CAPTURE_SCHEMA", "line:1#/pins"),
    ("pin-not-a-digest", lambda h: h["pins"].update({"NOTICES.txt": "ABC"}), "E_CAPTURE_SCHEMA",
     "line:1#/pins/NOTICES.txt"),
    ("extra-member", lambda h: h.update(extra=1), "E_CAPTURE_SCHEMA", "line:1#/extra"),
    ("capture-version", lambda h: h.update(capture_version=2), "E_CAPTURE_SCHEMA",
     "line:1#/capture_version"),
    ("adapter-version", lambda h: h.update(adapter_version="1.0.1"), "E_CAPTURE_SCHEMA",
     "line:1#/adapter_version"),
    ("profile", lambda h: h.update(profile="SC-HLA-RPR2-OBS-2"), "E_CAPTURE_SCHEMA",
     "line:1#/profile"),
    ("type", lambda h: h.update(type="frame"), "E_CAPTURE_SCHEMA", "line:1#/type"),
]


@case("G-R15", "G-R08", paragraphs=("SPEC:289",))
@pytest.mark.parametrize("change,code,path", [r[1:] for r in HEADER_FAULTS],
                         ids=[r[0] for r in HEADER_FAULTS])
def test_the_headers_configuration_is_validated_in_full(tmp_path, change, code, path):
    """RED-V-01: hash-valid captures whose header config passes the schema but not the semantic
    rules are refused before anything else is read; nothing is verified."""
    builder = one_generation(CaptureBuilder(_header_with(change)))
    lines = builder.lines()
    assert_stopped(verify(tmp_path, builder.data()), code, path, 1, lines)
    assert verify(tmp_path, builder.data())["header_sha256"] is None


@case("G-R15")
def test_a_frame_as_the_first_line_or_a_header_later_is_refused(tmp_path):
    lines, _ = crafted()
    as_first = lines[1:]
    report = verify(tmp_path, capture_bytes(as_first))
    assert (report["code"], report["path"], report["verified_seq"]) == (
        "E_CAPTURE_SCHEMA", "line:1#/elapsed_ns", None)
    second_header = lines[:2] + [lines[0]] + lines[2:]
    assert_stopped(verify(tmp_path, capture_bytes(second_header)), errors.E_CAPTURE_SCHEMA,
                   "line:3#/type", 3, second_header)


#: Epoch, elapsed values of three frames after generation_start, and the line refused (None when
#: accepted). 9998-12-31T23:59:59.999999Z is the last instant (SPEC:289); elapsed 999 ns is 0
#: whole microseconds and keeps it, 1000 ns is one microsecond past it. From 23:59:59.000000 the
#: margin is 999999 us: 999999999 ns truncates to it, 10^9 ns passes it.
OVERFLOW = [
    ("9998-12-31T23:59:59.999999Z", (0, 999, 999), None),
    ("9998-12-31T23:59:59.999999Z", (0, 999, 1000), 5),
    ("9998-12-31T23:59:59.000000Z", (999999999, 999999999, 999999999), None),
    ("9998-12-31T23:59:59.000000Z", (0, 999999999, 1000000000), 5),
    ("2026-01-01T00:00:00.000000Z", (0, 0, 10 ** 24 - 1), 5),
    ("1970-01-01T00:00:00.000000Z", (0, 253370764799999999000, 253370764799999999999), None),
    ("1970-01-01T00:00:00.000000Z", (0, 0, 253370764800000000000), 5),
]


@case("G-R08", paragraphs=("SPEC:289", "SPEC:42"))
@pytest.mark.parametrize("epoch,elapsed,line", OVERFLOW,
                         ids=[f"o{i}" for i in range(len(OVERFLOW))])
def test_effective_time_never_passes_year_9998(tmp_path, epoch, elapsed, line):
    """SPEC:289 and RED-V-01: epoch + elapsed_ns // 1000 microseconds, in integers (CR-L05), checked
    for every frame; passing the bound is E_CONFIG at the epoch, and verification stops at the
    frame that passes it. elapsed_ns is a decimal string of up to 24 digits (SPEC:42)."""
    header = _header_with(_config(("time_policy", "epoch"), epoch))
    builder = CaptureBuilder(header).frame(1, 0, START)
    for value in elapsed:
        builder.frame(1, value, event_reflect())
    builder.frame(1, elapsed[-1], END).footer()
    lines = builder.lines()
    report = verify(tmp_path, builder.data())
    if line is None:
        assert report["status"] == "COMPLETE"
    else:
        assert_stopped(report, errors.E_CONFIG, "line:1#/config/time_policy/epoch", line, lines)


@case("G-R08", paragraphs=("SPEC:42",))
def test_without_an_epoch_there_is_no_effective_time_to_overflow(tmp_path):
    """Time policy none assigns no effective time, so the largest elapsed_ns the schema allows
    verifies; elapsed_ns is stored as a canonical decimal string (SPEC:42, R16)."""
    header = fixture_capture_records()[0]
    header["config"] = example_json("config-existing.json")
    builder = (CaptureBuilder(header).frame(1, 0, START)
               .frame(1, 10 ** 24 - 1, END).footer())
    assert verify(tmp_path, builder.data())["status"] == "COMPLETE"
    assert json.loads(builder.lines()[2])["elapsed_ns"] == "9" * 24


# ======================================================================= frame field rules (R16)

def _frame_change(index, change):
    def mutate(records):
        change(records[index])
    return mutate


def _event(index, **members):
    return _frame_change(index, lambda r: r["event"].update(members))


def _drop(index, *path):
    def change(record):
        target = record
        for token in path[:-1]:
            target = target[token]
        del target[path[-1]]
    return _frame_change(index, change)


#: (mutation of one_generation's records, line, pointer) - each E_CAPTURE_SCHEMA. Records:
#: 1 generation_start, 2 discover, 3 reflect, 4 remove, 5 generation_end.
FIELD_RULES = [
    ("frame-without-generation", _drop(1, "generation"), 2, "/generation"),
    ("frame-without-elapsed", _drop(1, "elapsed_ns"), 2, "/elapsed_ns"),
    ("frame-without-event", _drop(1, "event"), 2, "/event"),
    ("frame-extra-member", _frame_change(1, lambda r: r.update(host="x")), 2, "/host"),
    ("elapsed-leading-zero", _frame_change(3, lambda r: r.update(elapsed_ns="01000")), 4,
     "/elapsed_ns"),
    ("elapsed-negative", _frame_change(3, lambda r: r.update(elapsed_ns="-1")), 4, "/elapsed_ns"),
    ("elapsed-integer", _frame_change(3, lambda r: r.update(elapsed_ns=1000)), 4, "/elapsed_ns"),
    ("elapsed-fraction", _frame_change(3, lambda r: r.update(elapsed_ns="1000.5")), 4,
     "/elapsed_ns"),
    ("elapsed-25-digits", _frame_change(3, lambda r: r.update(elapsed_ns="1" * 25)), 4,
     "/elapsed_ns"),
    ("generation-negative", _frame_change(1, lambda r: r.update(generation=-1)), 2,
     "/generation"),
    ("event-type-unknown", _event(1, type="teleport"), 2, "/event/type"),
    ("start-with-token", _event(1, object_token="o1"), 2, "/event/object_token"),
    ("end-with-token", _event(5, object_token="o1"), 6, "/event/object_token"),
    ("end-reason-unknown", _event(5, reason="crash"), 6, "/event/reason"),
    ("discover-without-name", _drop(2, "event", "name"), 3, "/event/name"),
    ("discover-without-class", _drop(2, "event", "reported_class"), 3, "/event/reported_class"),
    ("token-not-o", _event(2, object_token="1"), 3, "/event/object_token"),
    ("token-o0", _event(2, object_token="o0"), 3, "/event/object_token"),
    ("token-leading-zero", _event(2, object_token="o01"), 3, "/event/object_token"),
    ("token-17-chars", _event(2, object_token="o" + "1" * 16), 3, "/event/object_token"),
    ("reflect-without-tag", _drop(3, "event", "tag_hex"), 4, "/event/tag_hex"),
    ("reflect-hex-upper", _event(3, attributes=[{"name": "Spatial", "hex": "0A"}]), 4,
     "/event/attributes/0/hex"),
    ("reflect-hex-odd", _event(3, attributes=[{"name": "Spatial", "hex": "0"}]), 4,
     "/event/attributes/0/hex"),
    ("reflect-five-attributes", _event(3, attributes=[{"name": n, "hex": ""}
                                                      for n in "ABCDE"]), 4, "/event/attributes"),
    ("reflect-attribute-handle", _event(3, attributes=[{"name": "A", "hex": "", "handle": 1}]),
     4, "/event/attributes/0/handle"),
    ("reflect-transport", _event(3, transport="UDP"), 4, "/event/transport"),
    ("reflect-sent-order", _event(3, sent_order="FIFO"), 4, "/event/sent_order"),
    ("reflect-time-without-hex", _event(3, logical_time={"implementation": "HLAfloat64Time"}),
     4, "/event/logical_time"),
    ("reflect-time-hex-odd", _event(3, logical_time={"implementation": "x", "hex": "4"}), 4,
     "/event/logical_time"),
    ("reflect-retractable-text", _event(3, retractable="false"), 4, "/event/retractable"),
    ("reflect-producing-federate", _event(3, producing_federate="f1"), 4,
     "/event/producing_federate"),
    ("reflect-regions", _event(3, regions=[]), 4, "/event/regions"),
    ("remove-with-sent-order", _event(4, sent_order="RECEIVE"), 5, "/event/sent_order"),
    ("remove-without-received-order", _drop(4, "event", "received_order"), 5,
     "/event/received_order"),
    ("tag-8194-hex", _event(3, tag_hex="00" * 4097), 4, "/event/tag_hex"),
    ("value-8194-hex", _event(3, attributes=[{"name": "Spatial", "hex": "00" * 4097}]), 4,
     "/event/attributes/0/hex"),
    ("time-514-hex", _event(3, logical_time={"implementation": "x", "hex": "00" * 257}), 4,
     "/event/logical_time"),
    ("attribute-name-129", _event(3, attributes=[{"name": "a" * 129, "hex": ""}]), 4,
     "/event/attributes/0/name"),
]


@case("G-R16", paragraphs=("SPEC:72",))
@pytest.mark.parametrize("mutate,line,pointer", [r[1:] for r in FIELD_RULES],
                         ids=[r[0] for r in FIELD_RULES])
def test_event_fields_are_fully_defined_by_the_schema(tmp_path, mutate, line, pointer):
    """R16 and SPEC:72: each frame has generation, elapsed_ns (a canonical decimal string) and an
    event of one of six types with exactly its fields; lower-case even-length hex; at most four
    attributes; transport and order enums; logical time null or {implementation, hex}; no
    producing-federate handle and no region data in version 1."""
    lines, data = crafted(mutate=mutate)
    assert_stopped(verify(tmp_path, data), errors.E_CAPTURE_SCHEMA, f"line:{line}#{pointer}",
                   line, lines)


@case("G-R16", paragraphs=("SPEC:72",))
def test_raw_bytes_and_order_metadata_are_kept_exactly(tmp_path):
    """R16 and SPEC:72: the tag, the order metadata, the logical time bytes and each attribute's
    bytes (padding included: the SPATIAL-PADDING vector) go through the chain and the reader
    unchanged, at their bounds: 4096-byte value and tag, 256-byte logical time."""
    padding = next(v for v in fixture_json("attributes-positive.json")
                   if v["id"] == "SPATIAL-PADDING")
    event = event_reflect("o7", attributes=(("EntityIdentifier", "ffff00000001"),
                                            ("Spatial", padding["hex"]),
                                            ("ZUnknown", "ab" * 4096)),
                          tag_hex="00ff" * 2048,
                          logical_time={"implementation": "HLAfloat64Time", "hex": "40" * 256},
                          retractable=False)
    event["sent_order"] = "TIMESTAMP"
    event["received_order"] = "TIMESTAMP"
    event["transport"] = "BEST_EFFORT"
    chain = CaptureChain()
    data = chain.header(fixture_capture_records()[0])
    data += chain.frame(1, 0, START) + chain.frame(1, 3, event) + chain.frame(1, 3, END)
    data += chain.footer("COMPLETE", None, 1)
    path = tmp_path / "raw.jsonl"
    path.write_bytes(data)
    reader = CaptureReader(path)
    seen = [line.record for line in reader.records()]
    assert reader.report["status"] == "COMPLETE"
    assert seen[2]["event"] == event
    assert seen[2]["event"]["attributes"][1]["hex"] == padding["hex"]


# ========================================================== byte limits of strings (SPEC:289)

E2 = "\N{LATIN SMALL LETTER E WITH ACUTE}"      # 2 UTF-8 bytes
G4 = "\N{GRINNING FACE}"                         # 4 UTF-8 bytes

#: (event change, line, pointer or None): 1024 UTF-8 bytes are allowed, 1025 or more are not,
#: whatever the character count the schema's maxLength sees.
BYTE_LIMITS = [
    (_event(2, name="a" * 1024), 3, None),
    (_event(2, name="a" * 1025), 3, "/event/name"),
    (_event(2, name=E2 * 512), 3, None),
    (_event(2, name=E2 * 513), 3, "/event/name"),
    (_event(2, name=G4 * 256), 3, None),
    (_event(2, name=G4 * 256 + "a"), 3, "/event/name"),
    (_event(2, reported_class=E2 * 512), 3, None),
    (_event(2, reported_class="a" + E2 * 512), 3, "/event/reported_class"),
]


@case("G-R16", paragraphs=("SPEC:72",))
@pytest.mark.parametrize("mutate,line,pointer", BYTE_LIMITS,
                         ids=[f"b{i}" for i in range(len(BYTE_LIMITS))])
def test_name_and_class_are_bounded_in_utf8_bytes(tmp_path, mutate, line, pointer):
    """SPEC:289: string limits stated in bytes are counted in UTF-8 bytes, beside maxLength."""
    lines, data = crafted(mutate=mutate)
    report = verify(tmp_path, data)
    if pointer is None:
        assert report["status"] == "COMPLETE"
    else:
        assert_stopped(report, errors.E_CAPTURE_SCHEMA, f"line:{line}#{pointer}", line, lines)


@pytest.mark.parametrize("message,refused", [
    ("m" * 1024, False), (E2 * 512, False), (E2 * 512 + "m", True), (G4 * 257, True),
])
def test_a_captured_diagnostic_message_is_bounded_in_utf8_bytes(tmp_path, message, refused):
    """R37: a diagnostic message is at most 1024 UTF-8 bytes (SPEC:289's byte counting)."""
    builder = _session([(0, 0, event_diagnostic(message=message))], ("FAILED", "E_RTI_CONNECT", 0))
    lines = builder.lines()
    report = verify(tmp_path, builder.data())
    if refused:
        assert_stopped(report, errors.E_CAPTURE_SCHEMA, "line:2#/event/diagnostic/message", 2,
                       lines)
    else:
        assert report["status"] == "FAILED"


def _diagnostic(code, severity, message="m"):
    event = event_diagnostic(code, message)
    event["diagnostic"]["severity"] = severity
    return event


#: (id, code, severity, message, pointer refused or None). Every code of the catalogue with the
#: severity of its prefix is a capturable diagnostic as far as verification goes; anything else
#: is not (round R4's CR-new-R4-02: a captured diagnostic becomes an output record as it stands).
CAPTURED_DIAGNOSTICS = [
    ("error-code", "E_RTI_CONNECT", "ERROR", "m", None),
    ("warning-code", "W_DUPLICATE_REMOVE", "WARNING", "m", None),
    ("code-outside-the-catalogue", "E_SOMETHING_NEW", "ERROR", "m", "/event/diagnostic/code"),
    ("warning-outside-the-catalogue", "W_SOMETHING", "WARNING", "m", "/event/diagnostic/code"),
    ("error-code-as-a-warning", "E_RTI_CONNECT", "WARNING", "m", "/event/diagnostic/severity"),
    ("warning-code-as-an-error", "W_FOM_UNVERIFIED", "ERROR", "m", "/event/diagnostic/severity"),
    # 1025 UTF-8 bytes in 513 characters: within the schema's maxLength, past the byte bound.
    ("code-before-message", "E_SOMETHING_NEW", "WARNING", E2 * 512 + "m",
     "/event/diagnostic/code"),
    ("message-before-severity", "E_IO", "WARNING", E2 * 512 + "m", "/event/diagnostic/message"),
]


@case("G-R15")
@pytest.mark.parametrize("code,severity,message,pointer", [r[1:] for r in CAPTURED_DIAGNOSTICS],
                         ids=[r[0] for r in CAPTURED_DIAGNOSTICS])
def test_a_captured_diagnostic_carries_a_catalogue_code_and_its_severity(tmp_path, code, severity,
                                                                         message, pointer):
    """OPS-19 and RED-03 at verification (round R4, proposed CR-new-R4-02): the event schema
    admits any ^[EW]_[A-Z_]+$ code and either severity, but a captured diagnostic becomes one
    output record as it stands (RED-01), so its code must be one of the 32 and its severity the
    one its prefix gives; otherwise E_CAPTURE_SCHEMA at the member, the checks in the line's
    member order (code, message, severity)."""
    builder = _session([(0, 0, _diagnostic(code, severity, message))],
                       ("FAILED", "E_RTI_CONNECT", 0))
    lines = builder.lines()
    report = verify(tmp_path, builder.data())
    if pointer is None:
        assert report["status"] == "FAILED"
    else:
        assert_stopped(report, errors.E_CAPTURE_SCHEMA, f"line:2#{pointer}", 2, lines)


# ====================================================================== OPS-21: limits and I/O

@case("G-R15")
def test_the_capture_limits_through_the_seam(tmp_path):
    """OPS-21: verify enforces the frame-count and file-size limits, and the line bound, with
    E_LIMIT; each at the value the bundled capture just meets, and one below it."""
    lines = fixture_lines()
    data = fixture_bytes()

    def limited(**values):
        return verify(tmp_path, data, dataclasses.replace(V1, **values))

    assert limited(frames_per_session=8)["status"] == "COMPLETE"
    assert_stopped(limited(frames_per_session=7), errors.E_LIMIT, "line:9", 9, lines, frames=7)
    assert limited(capture_file_bytes=5013)["status"] == "COMPLETE"
    assert_stopped(limited(capture_file_bytes=5012), errors.E_LIMIT, "line:10", 10, lines)
    assert limited(line_bytes=1453)["status"] == "COMPLETE"
    assert_stopped(limited(line_bytes=1452), errors.E_LIMIT, "line:1", 1, lines)


@case("G-R15")
def test_the_line_bound_at_its_real_value(tmp_path):
    """SPEC:226: a capture line is at most 65536 bytes without its LF; at the bound the line is
    read (and refused as JSON), one byte more is E_LIMIT, ended or not."""
    lines, _ = crafted()
    for body, code in ((b"x" * 65536, errors.E_CAPTURE_SCHEMA), (b"x" * 65537, errors.E_LIMIT)):
        trial = lines[:1] + [body] + lines[1:]
        assert_stopped(verify(tmp_path, capture_bytes(trial)), code, "line:2", 2, trial)
    assert_stopped(verify(tmp_path, capture_bytes(lines[:1]) + b"x" * 65537), errors.E_LIMIT,
                   "line:2", 2, lines)


def test_a_path_that_cannot_be_read_is_e_io(tmp_path, monkeypatch):
    """The one HlaError of verify_capture: E_IO with the API's argument name (CR-L01), whatever
    makes the path unusable: absent, a directory, a FIFO, a NUL byte, a lone surrogate the
    file-system encoding cannot write (as str and as a path object), a name too long for the
    file system, a symbolic link loop, a path through a regular file, and a file the process may
    not open."""
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    regular = tmp_path / "regular"
    regular.write_bytes(fixture_bytes())
    paths = [tmp_path / "absent.jsonl", tmp_path, fifo, str(tmp_path / "a\x00b"),
             chr(0xD800), str(tmp_path / f"a{chr(0xDBFF)}.jsonl"), tmp_path / chr(0xDFFF),
             "n" * 5000, str(tmp_path / ("n" * 300)), loop, regular / "capture.jsonl"]
    for path in paths:
        with pytest.raises(HlaError) as info:
            verify_capture(path)
        assert (type(info.value), info.value.code, info.value.path) == (
            HlaError, errors.E_IO, "capture_path")
    # Permission denied, for any user: a file of mode 0 is still readable by root, so the
    # refusal the operating system gives is raised by the open itself, for this one call.
    def refused(*_args, **_kwargs):
        raise PermissionError(13, "Permission denied")

    with monkeypatch.context() as patch:
        patch.setattr(capture.os, "open", refused)
        with pytest.raises(HlaError) as info:
            verify_capture(regular)
    assert (type(info.value), info.value.code, info.value.path) == (
        HlaError, errors.E_IO, "capture_path")
    assert read(regular)["status"] == "COMPLETE"


def test_a_reader_reads_once_and_reports_only_at_its_end(tmp_path):
    """A CaptureReader is one pass: its report exists once records() has run to its end, and a
    second pass is refused (RuntimeError, a caller bug) rather than reading a file that may have
    changed into the same report."""
    path = tmp_path / "capture.jsonl"
    path.write_bytes(fixture_bytes())
    reader = CaptureReader(path)
    caller_bug(RuntimeError, lambda: reader.report)
    records = reader.records()
    next(records)
    caller_bug(RuntimeError, lambda: reader.report)
    for _ in records:
        pass
    assert reader.report["status"] == "COMPLETE"
    caller_bug(RuntimeError, lambda: list(reader.records()))
    assert reader.report["status"] == "COMPLETE"


def test_what_a_consumer_does_to_the_yielded_records_never_reaches_the_report(tmp_path):
    """The reader hands each verified record to its consumer (R4's replay) and keeps its own
    state: a consumer that changes or empties every record it is given, during the pass or after
    the report exists, changes nothing the report says."""
    path = tmp_path / "capture.jsonl"
    path.write_bytes(fixture_bytes())
    footer = fixture_capture_records()[-1]
    reader = CaptureReader(path)
    yielded = []
    for line in reader.records():
        yielded.append(line.record)
        if line.record["type"] == "footer":
            line.record["status"] = "FAILED"
            line.record["reason_code"] = "E_IO"
        else:
            line.record.clear()
    report = reader.report
    expected = {
        "verify_report_version": 1, "status": "COMPLETE", "code": None, "path": None,
        "message": None, "verified_seq": 9, "verified_bytes": 5013, "frames": 8,
        "header_sha256": FIXTURE_HEADER_SHA256, "last_sha256": FIXTURE_LAST_SHA256,
        "capture_complete": True, "footer": footer,
    }
    assert report == expected
    yielded[-1].clear()
    assert reader.report == expected and report["footer"] == footer


@case("G-R15", "G-R17", paragraphs=("SPEC:293",))
def test_verify_needs_no_endpoint_and_contacts_none(tmp_path, monkeypatch):
    """SPEC:293: framing, hash chain and schemas are validated even if the recorded endpoint no
    longer exists; verification opens no socket. OPS-11: verify never checks the pins."""
    attempts = []
    for name in sockguard.GUARDED:
        monkeypatch.setattr(socket, name, lambda *a, _n=name, **k: attempts.append(_n))
    header = _header_with(_config(("endpoint",), "rti://203.0.113.9:14321"))
    header["config"]["allow_remote"] = True
    header["pins"] = {}
    report = verify(tmp_path, one_generation(CaptureBuilder(header)).data())
    assert report["status"] == "COMPLETE" and attempts == []
    header["pins"] = {"other.txt": "0" * 64}
    assert verify(tmp_path, one_generation(CaptureBuilder(header)).data())["status"] == "COMPLETE"


# ================================================================================ hostile input

HOSTILE = [
    ("\x1b[2J", f"/{R}[2J"),
    ("\N{RIGHT-TO-LEFT OVERRIDE}x", f"/{R}x"),
    ("\N{LINE SEPARATOR}", f"/{R}"),
    ("\x85\x00", f"/{R}{R}"),
    ("k" * 1000, "/" + "k" * 64),
    ("a/b", "/a~1b"),
]


@case("G-R15")
@pytest.mark.parametrize("name,pointer", HOSTILE, ids=[f"h{i}" for i in range(len(HOSTILE))])
def test_a_hostile_member_name_reaches_the_path_only_as_safe_text(tmp_path, name, pointer):
    """CR-R0-04 on the capture's refusal paths: in the report and in the chain's HlaError."""
    lines, data = crafted(mutate=_frame_change(2, lambda r: r.update({name: 1})))
    assert_stopped(verify(tmp_path, data), errors.E_CAPTURE_SCHEMA, f"line:3#{pointer}", 3, lines)
    lines, data = crafted(mutate=_event(2, **{name: 1}))
    assert_stopped(verify(tmp_path, data), errors.E_CAPTURE_SCHEMA, f"line:3#/event{pointer}", 3,
                   lines)
    chain = _chain_after([(1, 0, START)])
    with pytest.raises(HlaError) as info:
        chain.frame(1, 0, dict(event_discover(), **{name: 1}))
    assert (info.value.code, info.value.path) == (errors.E_CAPTURE_SCHEMA,
                                                  f"line:3#/event{pointer}")
    # The parse-level refusals carry the name too: a repeated member, a float under it.
    lines, _ = crafted()
    member = json.dumps(name).encode("ascii")
    for text in (lines[2][:-1] + b"," + member + b":1," + member + b":2}",
                 lines[2][:-1] + b"," + member + b":1.5}"):
        trial = lines[:2] + [text] + lines[3:]
        assert_stopped(verify(tmp_path, capture_bytes(trial)), errors.E_CAPTURE_SCHEMA,
                       f"line:3#{pointer}", 3, trial)


# ========================================================================== integrity, not trust

@case("G-R17")
def test_the_chain_detects_accidental_change_and_is_not_authentication(tmp_path):
    """R17: hash-chain integrity detects accidental modification; it is not authentication or a
    signature. A changed byte is caught (A-HASH); the same change with every digest recomputed by
    anyone, here the tests' builder, verifies COMPLETE, so the chain proves nothing about who
    wrote the file. The README says so."""
    records = fixture_capture_records()
    records[4]["event"]["attributes"][0]["hex"] = "02"
    lines = chain_lines(records)
    assert lines != fixture_lines()
    assert verify(tmp_path, capture_bytes(lines))["status"] == "COMPLETE"
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    assert "not authentication" in " ".join(readme.split())


# ======================================================================================== fuzz

@case("G-R15", "G-R17")
def test_every_truncation_inside_the_last_three_lines(tmp_path):
    """Cutting the bundled capture at every byte offset from the start of line 8 to one before
    its end: always E_CAPTURE_INCOMPLETE at the line after the last LF kept, whose lines are
    exactly the verified prefix; only the whole file is COMPLETE."""
    data = fixture_bytes()
    path = tmp_path / "cut.jsonl"
    for size in range(LINE_ENDS[6], len(data) + 1):
        kept = data[:size]
        path.write_bytes(kept)
        report = read(path)
        if size == len(data):
            assert report["status"] == "COMPLETE"
            continue
        whole = kept.count(b"\n")
        assert (report["status"], report["code"], report["path"], report["verified_seq"],
                report["verified_bytes"]) == (
            "INCOMPLETE", "E_CAPTURE_INCOMPLETE", f"line:{whole + 1}", whole - 1,
            kept.rfind(b"\n") + 1), size


def _flip_positions(data: bytes) -> list[int]:
    starts = [0] + [end for end in LINE_ENDS[:-1]]
    chosen = set()
    for start, end in zip(starts, LINE_ENDS):
        chosen |= {start, start + 1, (start + end) // 2, end - 2, end - 1}
    chosen |= set(random.Random(20261010).sample(range(len(data)), 150))
    return sorted(chosen)


@case("G-R15", "G-R17")
def test_one_flipped_bit_is_never_accepted(tmp_path):
    """One bit flipped at a fixed set of positions (every line's first two bytes, middle, last
    byte and LF, and 150 more from a fixed seed), cycling through the eight bits: always a report
    (never another exception) with a catalogue code and never acceptance; verification stops on
    the line holding the flipped byte or, when that line is a header that still verifies, on the
    next one, whose link to it breaks."""
    data = fixture_bytes()
    path = tmp_path / "flip.jsonl"
    codes = set()
    for position in _flip_positions(data):
        changed = bytearray(data)
        changed[position] ^= 1 << (position % 8)
        path.write_bytes(bytes(changed))
        report = read(path)
        assert report["status"] in ("INVALID", "INCOMPLETE"), position
        assert errors.is_code(report["code"]), position
        flipped_line = data[:position].count(b"\n") + 1
        stopped = 1 if report["verified_seq"] is None else report["verified_seq"] + 2
        assert stopped in (flipped_line, flipped_line + 1), (position, report["path"])
        assert re.fullmatch(r"line:[1-9][0-9]*(#/.*)?", report["path"])
        codes.add(report["code"])
    assert {"E_CAPTURE_SCHEMA", "E_CAPTURE_HASH", "E_CAPTURE_INCOMPLETE"} <= codes


# =============================================================================== the report schema

def test_the_report_schema_refuses_an_inconsistent_report():
    """CR-L03: the schema has additionalProperties false, a version member, and ties status to
    code, completion and footer, so a report that contradicts itself does not validate."""
    good = {"verify_report_version": 1, "status": "INCOMPLETE", "code": "E_CAPTURE_INCOMPLETE",
            "path": "line:2", "message": "m", "verified_seq": 0, "verified_bytes": 10,
            "frames": 0, "header_sha256": "0" * 64, "last_sha256": "0" * 64,
            "capture_complete": False, "footer": None}
    report_validator().validate(good)
    for change in ({"capture_complete": True}, {"status": "COMPLETE"}, {"code": "E_IO"},
                   {"code": None}, {"extra": 1}, {"verify_report_version": 2},
                   {"path": "line:0"}, {"path": "2"}, {"status": "INVALID", "code": None}):
        assert list(report_validator().iter_errors({**good, **change})), change


# ============================================================ generation_start's federation (CR-L09)

OTHER_FEDERATION = "SC_DEMO_ffffffffffffffff"


def _two_generations(second_federation: str) -> CaptureBuilder:
    """The configured federation joined, left on a lost connection, then joined again under
    `second_federation`: the second generation_start is seq 4, line 5."""
    builder = CaptureBuilder()
    builder.frame(1, 0, event_generation_start())
    builder.frame(1, 0, event_generation_end("connection_lost"))
    builder.frame(0, 1000, event_diagnostic("E_RTI_CONNECT", "the RTI went away"))
    builder.frame(2, 2000, event_generation_start(second_federation))
    builder.frame(2, 2000, event_generation_end("stop"))
    return builder.footer("COMPLETE", None, 2)


@case("G-R16", "G-R15")
@pytest.mark.parametrize("federation", [OTHER_FEDERATION, "sc_demo_0123456789abcdef",
                                        "SC_DEMO_0123456789abcde"],
                         ids=["other-name", "other-case", "one-character-shorter"])
def test_a_generation_of_another_federation_is_refused_by_verify_and_the_reader(tmp_path,
                                                                               federation):
    """CR-L09 (stricter reading, logged for the owner): a generation is a join of the configured
    federation. verify_capture and the streaming reader refuse a generation_start whose
    federation_name differs from the header's config.federation_name (exactly; case counts) as
    E_CAPTURE_SCHEMA at `line:<n>#/event/federation_name`, where the other generation_start
    rules are: the first join (line 2, nothing after the header verified) and a later one
    (line 5, after a lost connection; seq 1 to 3 verified)."""
    first = CaptureBuilder()
    first.frame(1, 0, event_generation_start(federation)).frame(1, 0, event_generation_end())
    first.footer()
    for builder, line, verified in ((first, 2, 0), (_two_generations(federation), 5, 3)):
        path = tmp_path / f"capture-{line}.jsonl"
        builder.write(path)
        report = read(path)
        assert (report["status"], report["code"], report["path"], report["verified_seq"]) == (
            "INVALID", "E_CAPTURE_SCHEMA", f"line:{line}#/event/federation_name", verified)
        reader = CaptureReader(path)
        numbers = [verified_line.number for verified_line in reader.records()]
        assert numbers == list(range(1, line))
        assert reader.report == report
    assert read(tmp_path / "capture-2.jsonl")["header_sha256"] == FIXTURE_HEADER_SHA256


def test_the_configured_federation_verifies_in_every_generation(tmp_path):
    path = tmp_path / "capture.jsonl"
    _two_generations("SC_DEMO_0123456789abcdef").write(path)
    report = read(path)
    assert (report["status"], report["verified_seq"], report["frames"]) == ("COMPLETE", 6, 5)


@case("G-R16")
def test_the_chain_refuses_a_generation_of_another_federation_and_stays_as_it_was():
    """CR-L09 for the writer's side: `CaptureChain.frame` refuses the same generation_start with
    the reader's code and path (`line:2#/event/federation_name`), and the chain is unchanged:
    the configured federation's generation_start is then seq 1, chained from the header."""
    chain = CaptureChain()
    header_line = chain.header(fixture_capture_records()[0])
    with pytest.raises(HlaError) as info:
        chain.frame(1, 0, event_generation_start(OTHER_FEDERATION))
    assert type(info.value) is HlaError
    assert (info.value.code, info.value.path) == ("E_CAPTURE_SCHEMA",
                                                  "line:2#/event/federation_name")
    assert (chain.next_seq, chain.open_generation, chain.frames) == (1, None, 0)
    line = chain.frame(1, 0, event_generation_start())
    record = strict_json(line[:-1])
    assert (record["seq"], record["prev_sha256"]) == (1, sha256_hex(header_line[:-1]))


@case("G-R16")
def test_the_reducer_refuses_a_generation_of_another_federation():
    """The reducer admits frames by the same rules (CR-R4-01), so `reduce_frame` refuses the
    frame with the same code and path and leaves its state as it was."""
    from synapse_hla import reducer
    records = CaptureBuilder().frame(1, 0, event_generation_start(OTHER_FEDERATION)).records()
    state = reducer.initial_state(records[0], True)
    with pytest.raises(HlaError) as info:
        reducer.reduce_frame(state, records[1])
    assert (info.value.code, info.value.path) == ("E_CAPTURE_SCHEMA",
                                                  "line:2#/event/federation_name")
    assert state.next_seq == 1 and state.generation is None
