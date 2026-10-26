"""The SC4545-CORE-1 fuzz gate, `gates/nsif_fuzz.py`: its constants, its generator and operators,
the reduced schedule run twice, its child batches, how it records a crash and a hang, and the
static rule that it never evaluates what it generates (REQ-085, REQ-086).

The full run (100,000 mutations per target, in child interpreters) is a documented command whose
summary is in `docs/stanag4545-implementation.md`; this module runs the 1,000-mutation schedule in
process on every test run. Expectations are literals: the generator's published reference outputs
(Vigna's SplitMix64 test values), operator results written out by hand, and the codes and stages a
regression must keep. Repository-bound: it loads the gate by path from `gates/`, which the wheel
does not carry, and reads the geometry test module the gate takes its corner literals from.
"""

from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import types

import pytest

import synapse_cdm
from synapse_cdm.adapters import nsif_codec as nc

REPO = pathlib.Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "gates" / "nsif_fuzz.py"
RECORD = REPO / "docs" / "stanag4545-implementation.md"
FIXTURES = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures" / "stanag4545"

#: Every crash or hang the full run found, minimised, as (target, input, code, stage): the input
#: is the target's own argument form. The run of record found none (the record's fuzz summary).
REGRESSIONS: tuple = ()

#: The keys of one target's summary, in order.
SUMMARY_KEYS = [
    "target",
    "schedule",
    "seeds",
    "seed_sha256",
    "mutations",
    "accepted",
    "refused",
    "crash",
    "hang",
    "outcome_sha256",
]

#: Words no key of a report may contain: the gate records outcomes, never a duration or a rate.
TIME_WORDS = ("time", "elapsed", "duration", "seconds", "throughput")


@pytest.fixture(scope="module")
def gate():
    """The gate module, from its SOURCE, loaded as `tests/test_cdm_dis7_benchmark.py` loads its
    gate."""
    module = types.ModuleType("_nsif_fuzz_gate")
    module.__file__ = str(GATE_PATH)
    exec(compile(GATE_PATH.read_text(encoding="utf-8"), str(GATE_PATH), "exec"), module.__dict__)
    return module


@pytest.fixture(scope="module")
def quick_reports(gate, tmp_path_factory):
    folder = tmp_path_factory.mktemp("nsif_fuzz")
    reports = []
    for name in ("first.json", "second.json"):
        path = folder / name
        assert gate.main(["--quick", "--out", str(path)]) == 0
        reports.append(json.loads(path.read_text(encoding="utf-8")))
    return reports


def test_the_gate_constants_are_the_required_ones(gate):
    assert gate.FULL_MUTATIONS == 100000
    assert gate.QUICK_MUTATIONS == 1000
    assert gate.BASE_SEED == 0x4545
    assert gate.SCHEDULE == "nsif-fuzz/1"
    assert gate.TARGETS == ("cursor", "extensions", "image_subheader", "geometry", "window_index")
    assert gate.BATCH_SIZE == 1000
    assert (gate.BATCH_WATCHDOG, gate.SINGLE_WATCHDOG) == (600, 10)
    assert gate.SET_OCTETS == (0x00, 0xFF, 0x30, 0x39, 0x20, 0x2D, 0x2B)
    assert gate.INT_MAX == 9223372036854775807


def test_splitmix64_gives_the_reference_outputs(gate):
    # The reference implementation's outputs for seeds 0 and 1234567.
    zero = gate.SplitMix64(0)
    assert [zero.next() for _ in range(3)] == [
        0xE220A8397B1DCDAF,
        0x6E789E6AA1B965F4,
        0x06C45D188009454F,
    ]
    other = gate.SplitMix64(1234567)
    assert [other.next() for _ in range(5)] == [
        6457827717110365317,
        3203168211198807973,
        9817491932198370423,
        4593380528125082431,
        16408922859458223821,
    ]


def test_each_mutation_is_seeded_with_the_base_xor_the_target_xor_the_index(gate):
    assert gate.generator(0, 0).state == 0x4545
    assert gate.generator(2, 7).state == 0x4545 ^ 2 ^ 7
    assert gate.generator(4, 99999).state == 0x4545 ^ 4 ^ 99999
    first, second = gate.generator(3, 12), gate.SplitMix64(0x4545 ^ 3 ^ 12)
    assert [first.next() for _ in range(4)] == [second.next() for _ in range(4)]
    draws = gate.SplitMix64(0)
    assert [draws.below(10) for _ in range(3)] == [
        0xE220A8397B1DCDAF % 10,
        0x6E789E6AA1B965F4 % 10,
        0x06C45D188009454F % 10,
    ]


def test_the_octet_operators_do_what_the_schedule_says(gate):
    assert gate.flip_bit(b"\x00\x01", 1, 1) == b"\x00\x03"
    assert gate.flip_bit(b"\x80", 0, 7) == b"\x00"
    assert gate.set_octet(b"abc", 1, 0x2D) == b"a-c"
    assert gate.insert_octet(b"ab", 1, 0x2B) == b"a+b"
    assert gate.insert_octet(b"ab", 2, 0x20) == b"ab "
    assert gate.delete_octet(b"abc", 0) == b"bc"
    assert gate.truncate(b"abcdef", 0) == b""
    assert gate.truncate(b"abcdef", 4) == b"abcd"
    assert gate.duplicate_slice(b"abcdef", 1, 2, 4) == b"abcdbcef"
    assert gate.duplicate_slice(b"abcdef", 0, 1, 0) == b"aabcdef"
    assert gate.decimal_runs(b"ab012c3") == [(2, 3), (6, 1)]
    assert gate.decimal_runs(b"0123") == [(0, 4)]
    assert gate.decimal_runs(b"/:") == []
    assert gate.overwrite_decimal(b"x0123y", 1, 3, 0) == b"x0003y"
    assert gate.overwrite_decimal(b"x0123y", 1, 3, 1) == b"x9993y"
    assert gate.overwrite_decimal(b"x0123y", 1, 3, 2) == b"x10003y"
    assert [gate.perturb(5, operator) for operator in range(5)] == [6, 4, 10, 0, 2**63 - 1]


def test_the_outcome_lines_have_the_recorded_form(gate):
    assert gate.line(0, ("accepted",)) == "0:accepted"
    assert gate.line(17, ("refused", "E_LENGTH", "header")) == "17:refused:E_LENGTH:header"
    assert gate.line(99999, ("crash",)) == "99999:crash"
    assert gate.line(5, ("hang",)) == "5:hang"
    rows = [[0, "accepted"], [1, "refused", "E_DIGITS", "header"], [2, "accepted"]]
    summary = gate.summarise("cursor", [b"x"], 3, rows)
    text = "0:accepted\n1:refused:E_DIGITS:header\n2:accepted\n"
    assert summary["outcome_sha256"] == hashlib.sha256(text.encode("ascii")).hexdigest()
    assert summary["refused"] == {"E_DIGITS:header": 1}
    assert (summary["accepted"], summary["crash"], summary["hang"]) == (2, [], [])
    assert list(summary) == SUMMARY_KEYS


def test_the_seeds_are_every_packaged_vector_and_the_slices_they_parse_into(gate):
    seeds = gate.build_seeds()
    vectors = sorted(FIXTURES.rglob("*.ntf"))
    assert len(vectors) == 64
    assert sorted(seeds["cursor"]) == sorted(path.read_bytes() for path in vectors)
    # Five of the 64 are the kit's negatives and parse into nothing; the other 59 hold one image
    # each except header_only, which holds none.
    assert len({data for data, _ in seeds["image_subheader"]}) == len(seeds["image_subheader"])
    sections = {section for section, _, _ in seeds["extensions"]}
    assert sections == {"UDHD", "XHD", "UDID", "IXSHD", "TXSHD"}
    assert ("UDHD", b"00000", None) in seeds["extensions"]
    # unknown_duplicate_tre's two TREs, framed as overflow DES 1's payload after an empty area.
    assert any(
        data.startswith(b"00003001") and overflow_at == 8
        for _, data, overflow_at in seeds["extensions"]
    )
    literals = gate.geometry_literals()
    assert all(len(octets) == 60 for octets in literals) and len(literals) >= 50
    assert b"480000N0170000E480000N0180000E470000N0180000E470000N0170000E" in literals
    for octets in literals:
        assert ("G", octets) in seeds["geometry"] and ("D", octets) in seeds["geometry"]
    # The asymmetric literal vector in mode P with the sub-window (1, 2, 3, 2, (1, 0)): its
    # first position and band.
    assert ("P", 3, 2, 2, 3, 2, 1, 2, 1) in seeds["window_index"]
    for target in gate.TARGETS:
        texts = [gate.seed_text_of(target)(seed) for seed in seeds[target]]
        assert len(set(texts)) == len(texts), target


def test_a_child_batch_answers_what_the_parent_computes(gate):
    seeds = gate.build_seeds()
    for target in ("cursor", "geometry", "window_index"):
        digest = gate.seed_digest(target, seeds[target])
        rows = gate._child(target, 40, 25, gate.BATCH_WATCHDOG, digest)
        assert rows == gate.run_batch(target, seeds[target], 40, 25), target


def test_a_crash_records_its_input_and_type(gate, monkeypatch):
    def broken(target, item):
        raise KeyError("planted")

    monkeypatch.setattr(gate, "call", broken)
    seeds = gate.build_seeds()["cursor"]
    rows = gate.run_batch("cursor", seeds, 3, 2)
    item = gate.make_input("cursor", seeds, 3)
    assert rows[0] == [3, "crash", "KeyError", hashlib.sha256(item).hexdigest()]
    summary = gate.summarise("cursor", seeds, 2, rows)
    assert summary["crash"][0] == {
        "index": 3,
        "exception": "KeyError",
        "input_sha256": hashlib.sha256(item).hexdigest(),
    }
    assert summary["outcome_sha256"] == hashlib.sha256(b"3:crash\n4:crash\n").hexdigest()


def test_a_broken_result_contract_is_a_crash(gate, monkeypatch):
    stub = types.SimpleNamespace(NsifError=nc.NsifError, sample_index=lambda *arguments: -1)
    monkeypatch.setattr(gate, "nsif_codec", stub)
    assert gate.classify("window_index", ("B", 1, 1, 2, 2, 1, 0, 0, 0)) == (
        "crash",
        "InvariantBroken",
    )


def test_footprint_refusing_is_a_crash_because_footprint_is_total(gate, monkeypatch):
    def refuses(icords, igeolo):
        raise nc.NsifError("E_FIELD", "geometry", None, "/x", "planted")

    monkeypatch.setattr(gate, "nsif_geometry", types.SimpleNamespace(footprint=refuses))
    assert gate.classify("geometry", ("G", b"")) == ("crash", "NsifError")


def test_a_slice_outside_the_input_is_a_crash(gate):
    with pytest.raises(gate.InvariantBroken):
        gate._inside((nc.Slice(3, 2),), 4)
    gate._inside((nc.Slice(2, 2), {"a": nc.Slice(0, 0)}), 4)


def test_a_batch_that_does_not_return_is_retried_one_input_at_a_time(gate, monkeypatch):
    seeds = gate.build_seeds()["cursor"]

    def child(target, start, count, watchdog, expected):
        # The batch of five starting at 5 and the single input 7 never answer.
        if (start == 5 and count > 1) or start == 7:
            return None
        return gate.run_batch(target, seeds, start, count)

    monkeypatch.setattr(gate, "_child", child)
    monkeypatch.setattr(gate, "BATCH_SIZE", 5)
    rows = gate.run_isolated("cursor", seeds, 12)
    expected = gate.run_batch("cursor", seeds, 0, 12)
    hung = gate.make_input("cursor", seeds, 7)
    assert rows[7] == [7, "hang", hashlib.sha256(hung).hexdigest()]
    assert rows[:7] + rows[8:] == expected[:7] + expected[8:]
    summary = gate.summarise("cursor", seeds, 12, rows)
    assert summary["hang"] == [{"index": 7, "input_sha256": hashlib.sha256(hung).hexdigest()}]


def test_the_quick_schedule_is_deterministic_and_finds_no_crash_or_hang(quick_reports):
    first, second = quick_reports
    assert first == second
    assert first["schedule"] == "nsif-fuzz/1" and first["mode"] == "in_process"
    assert [result["target"] for result in first["targets"]] == [
        "cursor",
        "extensions",
        "image_subheader",
        "geometry",
        "window_index",
    ]
    stages = set(nc.STAGES)
    for result in first["targets"]:
        assert list(result) == SUMMARY_KEYS
        assert result["mutations"] == 1000
        assert (result["crash"], result["hang"]) == ([], [])
        assert result["accepted"] + sum(result["refused"].values()) == 1000
        for key in result["refused"]:
            code, stage = key.split(":")
            assert code in nc.ERROR_CODES and stage in stages, key
    geometry = first["targets"][3]
    assert geometry["refused"] == {} and geometry["accepted"] == 1000


def test_the_report_holds_no_time_or_rate(quick_reports):
    def keys(value):
        if isinstance(value, dict):
            for key, item in value.items():
                yield key
                yield from keys(item)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)

    for key in keys(quick_reports[0]):
        assert not any(word in key.lower() for word in TIME_WORDS), key


def test_the_gate_never_evaluates_what_it_generates():
    tree = ast.parse(GATE_PATH.read_text(encoding="utf-8"))
    names = {"eval", "exec", "compile", "__import__"}
    subprocess_calls = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                assert target.id not in names, target.id
            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                dotted = f"{target.value.id}.{target.attr}"
                assert dotted not in {"os.system", "os.popen", "os.execv", "os.spawnv"}, dotted
                if target.value.id == "subprocess":
                    subprocess_calls += 1
                    argv = node.args[0]
                    assert isinstance(argv, ast.List)
                    first = argv.elts[0]
                    assert isinstance(first, ast.Attribute)
                    assert (first.value.id, first.attr) == ("sys", "executable")
            for keyword in node.keywords:
                if keyword.arg == "shell":
                    assert isinstance(keyword.value, ast.Constant)
                    assert keyword.value.value is False
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            roots = (
                {alias.name.split(".")[0] for alias in node.names}
                if isinstance(node, ast.Import)
                else {(node.module or "").split(".")[0]}
            )
            # No random source and no clock may feed the schedule.
            assert not roots & {"random", "secrets", "time", "datetime", "uuid"}, roots
    assert subprocess_calls == 1


def test_every_regression_still_raises_its_code_and_stage(gate):
    for target, item, code, stage in REGRESSIONS:
        assert gate.classify(target, item) == ("refused", code, stage)
    if not REGRESSIONS:
        assert not list((FIXTURES / "malformed").glob("fuzz_*.ntf"))
        assert "0 crashes, 0 hangs; no regression fixture was produced" in RECORD.read_text(
            encoding="utf-8"
        )
