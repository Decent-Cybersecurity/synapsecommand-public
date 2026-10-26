"""The release gates of round R9, clause by clause, and the release evidence report (R46, R48).

A documentary gate is held by a test that reads the file and asserts the statement (R46: "a
checked file or runtime assertion, not an unreviewed tick box"); a release gate is held by the
evidence report's entry, which the tests here check against the trace export (a real collection of
the suite) and against the report's own record of the session's runs: every case with a result
derived the one way the report says, every BLOCKED naming its resource, no gate that needs the
reference platform reading PASS, external_customer_interoperability NOT_TESTED in a member of its
own, and the report describing exactly this tree (the SHA-256 over its files).

All of it is offline: the report is read, never regenerated, here. `tests/release_evidence.py`
writes it from the runs of a release session.
"""

from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import re

import pytest

import release_evidence
from hla_support import (
    PACKAGE_ROOT, TOOL_PLACES, CaptureBuilder, case, collected_bindings, contract_json,
    event_discover, event_generation_end, event_generation_start, event_reflect, place_text,
    strict_json,
)
from synapse_hla import _fom, host, replay

README = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
INSTALL = (PACKAGE_ROOT / "docs" / "installation.md").read_text(encoding="utf-8")
LICENCES = (PACKAGE_ROOT / "licences" / "README.md").read_text(encoding="utf-8")
EVIDENCE = PACKAGE_ROOT / "docs" / "evidence" / "evidence-report.json"
INDEX = contract_json("case-index.json")


def flat(text: str) -> str:
    """Text with its line breaks and runs of spaces read as one space."""
    return " ".join(text.split())


def section(text: str, heading: str) -> str:
    """The text under a markdown heading, up to the next heading of the same or a higher level."""
    level = heading.split(" ", 1)[0]
    start = text.index(heading + "\n") + len(heading) + 1
    rest = text[start:]
    stop = re.search(rf"^#{{1,{len(level)}}} ", rest, re.M)
    return rest[:stop.start()] if stop else rest


@pytest.fixture(scope="module")
def bindings(tmp_path_factory):
    return collected_bindings(tmp_path_factory.mktemp("release-trace"))


@pytest.fixture(scope="module")
def report():
    return strict_json(EVIDENCE.read_bytes())


def bound_ids(bindings: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for node, binding in bindings.items():
        for case_id in binding["ids"]:
            out.setdefault(case_id, []).append(node)
    return out


# ================================================================ R01, R46: everything is bound

@case("G-R01", "G-R46")
def test_every_requirement_has_a_gate_and_every_case_a_concrete_test(bindings):
    """R01 (every numbered requirement, schema and vector is normative; the acceptance cases
    prescribe mandatory tests) and R46 (every case has a concrete automated test; every R01 to R50
    has a gate in requirements.json): the case index (`tests/contract/case-index.json`) is the
    pinned stand-in for the handoff's acceptance-cases.json and requirements.json, which never
    enter the repository (D-05, D-06: it carries each case's id, requirement and layer as the
    bundle has them, and the evidence report records its digest; final review finding
    F-trace-02), and it holds the 147 cases with one gate for each of R01 to R50, a real
    collection of the suite binds every one of them, no case is pending in any round, the rounds
    are finished through R9 and no clause is carried any more (nothing is left to a later
    round: the clauses that need the reference platform are held by the evidence report's
    BLOCKED entries)."""
    ids = [c["id"] for c in INDEX]
    assert len(ids) == len(set(ids)) == 147
    gates = sorted(i for i in ids if i.startswith("G-"))
    assert gates == sorted(f"G-R{n:02d}" for n in range(1, 51))
    bound = bound_ids(bindings)
    assert sorted(set(ids) - set(bound)) == []
    pending = contract_json("pending.json")
    assert pending["finished_through"] == "R9"
    assert all(members == [] for members in pending["pending"].values())
    assert contract_json("carried.json") == []


#: SPEC:251's mandatory test topics, each with the cases that hold it (read off the case index by
#: hand: the topic's own acceptance cases).
MANDATORY_TOPICS = {
    "each field boundary and spatial variant": ["V-SPATIAL-1", "V-SPATIAL-9", "N-TRUNC-1",
                                                "N-TRAIL-9", "V-SPATIAL-PADDING"],
    "partial-update permutations": ["A-PARTIAL-ORDER"],
    "absent versus invalid force": ["A-FORCE-ABSENT", "A-FORCE-INVALID", "A-FORCE-UNMAPPED"],
    "stale-cache prevention": ["A-REPAIR"],
    "atomic callback rejection": ["A-ATOMIC"],
    "duplicate and changed identities": ["A-COLLISION", "A-ID-CHANGE"],
    "removals and reincarnation": ["A-REMOVE", "A-REINCARNATE"],
    "generations and reconnect": ["A-END", "A-RECONNECT"],
    "missing time and declared external time": ["A-NO-TIME", "A-TIME-CONTEXT"],
    "hashes and corrupt or truncated captures": ["A-HASH", "A-TRUNCATED", "A-SEQ-GAP"],
    "schema drift": ["A-DEPENDENCY"],
    "UTF-8 and duplicate-key failures": ["A-UTF8", "A-DUPLICATE-KEY"],
    "forbidden API calls": ["A-NO-PUBLISH", "A-NO-CREATE"],
    "bounded allocations": ["A-OBJECT-LIMIT", "A-ATTRIBUTE-LIMIT", "A-TAG-LIMIT", "A-OVERFLOW"],
    "shutdown and crash recovery": ["A-SIGNAL", "A-TIMEOUT", "A-PREFIX"],
    "course follows velocity, not psi": ["A-ATTITUDE"],
}


@case("G-R46", paragraphs=("SPEC:251",))
def test_the_mandatory_topics_of_r46_are_held_by_bound_cases_that_pass(bindings, report):
    """SPEC:251: the mandatory tests (field boundaries and variants, partial updates, absent and
    invalid force, stale caches, atomic rejection, identities, removals, generations and
    reconnect, time, hashes and truncation, schema drift, UTF-8 and duplicate keys, forbidden
    calls, bounded allocations, shutdown and crash recovery, course against psi) each have their
    cases in the index, bound by collected tests, and each of them PASSes in the evidence report
    (whose results are the release session's; this test reads them, it does not make them). A
    topic case that is BLOCKED or FAIL fails this test (review finding R9-r1-F1)."""
    known = {c["id"] for c in INDEX}
    bound = bound_ids(bindings)
    results = {c["id"]: c["result"] for c in report["cases"]}
    for topic, ids in MANDATORY_TOPICS.items():
        for case_id in ids:
            assert case_id in known and bound.get(case_id), (topic, case_id)
            assert results[case_id] == "PASS", (topic, case_id, results[case_id])


# ======================================================================= the evidence report

def test_the_source_digest_covers_the_package_but_the_report():
    """The digest the report carries is over every file of the package directory except
    docs/evidence (and caches and build output), one sorted line per file."""
    digest, files = release_evidence.source_digest()
    assert re.fullmatch(r"[0-9a-f]{64}", digest) and files > 100
    names = [p.relative_to(PACKAGE_ROOT).as_posix() for p in PACKAGE_ROOT.rglob("*")
             if p.is_file() and not release_evidence._skipped(p)]
    assert "README.md" in names and "pyproject.toml" in names
    assert not [n for n in names if n.startswith("docs/evidence/")]


@case("G-R46", "G-R05", "A-EVIDENCE", "G-R02", paragraphs=("SPEC:8", "SPEC:259"))
def test_the_evidence_report_identifies_its_build_and_lists_every_case(bindings, report):
    """R46's implementation report and R05's "source commit and build commands in every report":
    the report is the release evidence of SPEC:8, it describes exactly this tree (its SHA-256 over
    the package's files), names the base commit and says why the source commit is null (OPS-10:
    never invented), names the native build and the commands; it lists the 147 cases with their
    requirement and layer, each with exactly the tests a real collection binds to it, a result
    PASS, FAIL or BLOCKED, the command that reruns them, the digests of the test files that hold
    it (its inputs), the expected and actual evidence and the duration; and every run with its
    interpreter, platform, evidence class, command and counts, no command holding a machine's
    absolute path. SPEC:259: the expectations are the supplied fixtures', pinned by digest."""
    assert report["evidence_report_version"] == 1
    assert report["release"] == {"distribution": "synapse-hla", "version": "1.0.0",
                                 "profile": "SC-HLA-RPR2-OBS-1",
                                 "specification": "SC HLA SPEC 001 v1.0, the handoff document; "
                                                  "not in this repository"}
    build = report["build"]
    digest, files = release_evidence.source_digest()
    assert (build["source_sha256"], build["source_files"]) == (digest, files), (
        "the evidence report describes another tree: regenerate it after the last change")
    assert build["base_commit"] == "9c0f1d7e35fbe1d0d93926dd6726f0274c7a3e9d"
    assert build["source_commit"] is None and "never invented" in build["source_commit_note"]
    assert build["native"]["worker_sha256"] and build["native"]["cmake"]
    assert build["commands"]["openrti"].startswith("bash tools/build_openrti.sh")
    vendored = {e["path"]: e["sha256"] for e in contract_json("vendored-pins.json")["files"]}
    assert report["input_digests"]["vendored"] == vendored
    for path, digest_ in vendored.items():
        assert hashlib.sha256((PACKAGE_ROOT / path).read_bytes()).hexdigest() == digest_, path
    bound = bound_ids(bindings)
    assert [(c["id"], c["requirement"], c["layer"]) for c in report["cases"]] == [
        (c["id"], c["requirement"], c["layer"]) for c in INDEX]
    run_ids = {run["id"] for run in report["runs"]}
    for entry in report["cases"]:
        listed = [test for group in entry["tests"] for test in group["tests"]]
        assert sorted(listed) == sorted(bound[entry["id"]]), entry["id"]
        assert len(listed) == len(set(listed)), entry["id"]
        assert entry["result"] in ("PASS", "FAIL", "BLOCKED")
        assert entry["command"].startswith("python -m pytest -p no:cacheprovider -m ")
        for name, digest_ in entry["input_digests"].items():
            assert hashlib.sha256((PACKAGE_ROOT / name).read_bytes()).hexdigest() == digest_
        assert entry["expected"] and set(entry["actual"]) == {"passed", "failed", "error",
                                                              "skipped", "not_run"}
        assert type(entry["duration_s"]) is float
        for group in entry["tests"]:
            assert set(group["outcomes"]) <= run_ids
    absolute = re.compile(r"(?:^|[\s=\"'])/(?:Users|home|private|tmp|var|opt|root)/")
    for run in report["runs"]:
        assert run["evidence_class"] in release_evidence.EVIDENCE_CLASSES
        assert not absolute.search(run["command"]), run["command"]
        assert run["counts"] and set(run["counts"]) <= {"passed", "failed", "error", "skipped"}
    markdown = (PACKAGE_ROOT / "docs" / "evidence" / "README.md").read_text(encoding="utf-8")
    assert markdown == release_evidence.render_markdown(report)


#: The cases that need the reference platform before they can read PASS (CR-L04, the clauses R7
#: and R8 carried to the release), each with the resource the report must name, written here and
#: not read from the evidence tool (review finding R9-r1-F1): the tool's own list must equal this
#: one, so shortening it after a run on the reference platform is a visible change of this test,
#: made with the lead's ruling. The platform: SPEC:20 (Linux x86_64, Ubuntu 24.04, GCC 13 with
#: C++14, CMake 3.28 to 3.31); R42's machine: SPEC:235 (4 vCPU, 8 GiB).
REFERENCE_PLATFORM_CASES = {
    "G-R02": "the reference platform (Linux x86_64, Ubuntu 24.04, GCC 13 (C++14), CMake 3.28 to "
             "3.31) for SPEC:20's native build and rti group: no run there; the development runs "
             "are DEV evidence",
    "G-R38": "the demo built and run on the reference platform (Linux x86_64, Ubuntu 24.04, GCC "
             "13 (C++14), CMake 3.28 to 3.31)",
    "G-R42": "R42's recorded 4-vCPU x86_64 machine with 8 GiB on the reference platform",
    "G-R43": "the reference build (Linux x86_64, Ubuntu 24.04, GCC 13 (C++14), CMake 3.28 to "
             "3.31) and the SHA-256 of the distribution packages of its toolchain",
    "G-R47": "the reference tools built and run on the reference platform (GCC 13)",
    "G-R48": "the release gates 'local OpenRTI lifecycle exercise' and 'performance test' on the "
             "reference platform",
    "A-PERFORMANCE": "R42's recorded 4-vCPU x86_64 machine with 8 GiB on the reference platform",
}

#: R48's nine release gates in its order (SPEC:255), each with the cases that decide it, as the
#: report must list them (CR-new-R9-07): the hashes gate from the hash and dependency cases and
#: R04, the reference encoding gate from A-ENCODING and R47, the lifecycle gate from the demo
#: cases, the overload gate from the overload and failure cases, the performance gate from R42,
#: the build gate from R43, the claims gate from R50 and R49; the offline gate and the defects
#: gate have rules of their own (the offline runs; the reviews).
RELEASE_GATE_CASES = [
    ("contract and dependency hashes verified", ["A-DEPENDENCY", "A-HASH", "G-R04"]),
    ("all offline tests PASS", []),
    ("reference encoding and geodesy checks PASS", ["A-ENCODING", "G-R47"]),
    ("local OpenRTI lifecycle exercise PASS", ["A-DEMO", "G-R38"]),
    ("overload and failure tests PASS", ["A-OVERFLOW", "A-ATTRIBUTE-LIMIT", "A-TAG-LIMIT",
                                         "A-OBJECT-LIMIT", "A-FILE-LIMIT", "A-DISK", "A-SIGNAL",
                                         "A-TIMEOUT", "A-RECONNECT", "A-TRUNCATED",
                                         "A-SEQ-GAP"]),
    ("performance test PASS", ["A-PERFORMANCE", "G-R42"]),
    ("no unresolved severity-high defects", []),
    ("reproducible build and licence review completed", ["G-R43"]),
    ("claims matching the tested scope", ["G-R50", "G-R49"]),
]
#: Release gate 7's resource (CR-L25, final review): the reviews of this tree are recorded in the
#: release run's kit, not in the tree, so the gate reads BLOCKED naming them.
DEFECTS_GATE_RESOURCE = (
    "the records of the independent reviews of this release tree (the packaging round's two "
    "reviews, the final review and the review of the fix pass that followed it), which are kept "
    "in the release run's kit outside this tree: a gate reads PASS only from evidence the tree "
    "carries (A-EVIDENCE, CR-L25)")
#: The gates that cannot PASS before a run on the reference platform (CR-L04): the reference
#: tools (G-R47), the lifecycle exercise (the demo there), the performance run (R42's machine)
#: and the reference build (G-R43).
REFERENCE_PLATFORM_GATES = ["reference encoding and geodesy checks PASS",
                            "local OpenRTI lifecycle exercise PASS", "performance test PASS",
                            "reproducible build and licence review completed"]


def derived_result(entry: dict) -> str:
    """The rule of release_evidence's module text, recomputed from the entry's own outcomes and
    this test's own list of the reference-platform cases."""
    outcomes = [o for group in entry["tests"] for o in group["outcomes"].values()]
    if any(o in ("failed", "error") for o in outcomes):
        return "FAIL"
    if entry["id"] in REFERENCE_PLATFORM_CASES:
        return "BLOCKED"
    if not entry["tests"] or any(not any(o == "passed" for o in group["outcomes"].values())
                                 for group in entry["tests"]):
        return "BLOCKED"
    return "PASS"


@case("A-EVIDENCE", "G-R48", "G-R46")
def test_the_evidence_report_never_hides_not_tested_or_blocked_behind_a_pass(report):
    """A-EVIDENCE (an external simulator is absent: external_customer_interoperability is
    NOT_TESTED, never an implicit PASS), R48 (no global PASS hides that field) and R46 (missing
    dependencies and an unavailable reference platform are BLOCKED; a skipped external test never
    makes the release fully PASS): the field is a member of its own reading NOT_TESTED; each
    case's result is the one its own outcomes give under the report's rule; every BLOCKED names
    its resource; R48's nine gates are listed in its order with statuses derived from their
    cases, the lifecycle and performance gates BLOCKED; and the overall status is FAIL or BLOCKED
    whenever any case or gate is not PASS."""
    assert report["external_customer_interoperability"] == "NOT_TESTED"
    for entry in report["cases"]:
        assert entry["result"] == derived_result(entry), entry["id"]
        if entry["result"] == "BLOCKED":
            assert entry["blocked_resource"], entry["id"]
        else:
            assert entry["blocked_resource"] is None, entry["id"]
        if entry["result"] == "PASS":
            assert entry["evidence_class"], entry["id"]
    gates = report["release_gates"]
    assert [(g["gate"], g["cases"]) for g in gates] == RELEASE_GATE_CASES
    assert [(name, ids) for name, ids, _rule in release_evidence.RELEASE_GATES] == (
        RELEASE_GATE_CASES)
    by_case = {c["id"]: c for c in report["cases"]}
    for gate in gates:
        statuses = [by_case[i]["result"] for i in gate["cases"]]
        assert gate["status"] in ("PASS", "FAIL", "BLOCKED")
        if "FAIL" in statuses:
            assert gate["status"] == "FAIL"
        elif "BLOCKED" in statuses:
            assert gate["status"] == "BLOCKED"
        if gate["status"] == "BLOCKED":
            assert gate["blocked_resource"]
    assert gates[3]["status"] in ("BLOCKED", "FAIL") and gates[5]["status"] in ("BLOCKED", "FAIL")
    everything = [c["result"] for c in report["cases"]] + [g["status"] for g in gates]
    if set(everything) != {"PASS"}:
        assert report["status"] in ("FAIL", "BLOCKED")
    assert report["status"] == ("FAIL" if "FAIL" in everything else "BLOCKED"
                                if "BLOCKED" in everything else "PASS")
    assert report["case_counts"] == {r: everything[:147].count(r)
                                     for r in ("PASS", "FAIL", "BLOCKED")}


@case("G-R02", "G-R38", "G-R47", "G-R43", "G-R42", "G-R48", "G-R03",
      paragraphs=("SPEC:20",))
def test_every_gate_that_needs_the_reference_platform_reads_blocked_naming_it(report):
    """CR-L04 and the clauses R7 and R8 carried to the release: SPEC:20's reference platform
    (Linux x86_64, Ubuntu 24.04, GCC 13 with C++14, CMake 3.28 to 3.31) has had no run, so the
    native build and rti group there (G-R02), the demo there (G-R38), the reference tools there
    (G-R47), the reference build (G-R43), R42's machine (G-R42, A-PERFORMANCE) and R48's
    lifecycle, performance, reference encoding and reproducible build gates read BLOCKED (or
    FAIL), never PASS, each naming that resource; the defects gate reads BLOCKED naming the
    records of this tree's reviews, which the tree does not carry (CR-L25); the
    results of this session carry the development class of the machine that made them, and the
    README says which platform is the reference one. The list of those cases is this test's own
    literal, which the evidence tool's list must equal (review finding R9-r1-F1)."""
    assert release_evidence.REFERENCE_PLATFORM == REFERENCE_PLATFORM_CASES
    by_case = {c["id"]: c for c in report["cases"]}
    for case_id, resource in REFERENCE_PLATFORM_CASES.items():
        # Never PASS: BLOCKED on the platform, or FAIL when a binding test failed (a failure is
        # never hidden behind a BLOCKED either).
        assert by_case[case_id]["result"] in ("BLOCKED", "FAIL"), case_id
        if by_case[case_id]["result"] == "BLOCKED":
            assert by_case[case_id]["blocked_resource"] == resource, case_id
    by_gate = {g["gate"]: g for g in report["release_gates"]}
    for name in REFERENCE_PLATFORM_GATES:
        assert by_gate[name]["status"] in ("BLOCKED", "FAIL"), name
        if by_gate[name]["status"] == "BLOCKED":
            assert "reference" in by_gate[name]["blocked_resource"] or (
                "R42" in by_gate[name]["blocked_resource"]), name
    defects = by_gate["no unresolved severity-high defects"]
    assert (defects["status"], defects["blocked_resource"]) == ("BLOCKED", DEFECTS_GATE_RESOURCE)
    assert release_evidence.RELEASE_GATES[6] == ("no unresolved severity-high defects", [],
                                                 DEFECTS_GATE_RESOURCE)
    for run in report["runs"]:
        assert run["evidence_class"].startswith("DEV-"), run
    assert set(report["evidence_classes"]) == {"DEV-macOS-arm64", "DEV-linux-aarch64",
                                               "REFERENCE-linux-x86_64"}
    assert "no run of this release was made there" in report["evidence_classes"][
        "REFERENCE-linux-x86_64"]
    text = flat(README)
    assert ("Neither is the reference platform the specification names (Linux x86_64, Ubuntu "
            "24.04, GCC 13, CMake 3.28 to 3.31): every release gate that needs it, the "
            "performance run of R42 among them, reads BLOCKED in the evidence report") in text
    pins = release_evidence.cross_interpreter_pins()
    assert report["cross_interpreter_pins"]["platforms"] == sorted(pins) == [
        "darwin-arm64", "linux-aarch64"]


#: CR-L20's observation as the geodesy entry states it (DECISIONS C.14; final review findings
#: F-release-02 and F-core-delta-01), phrase by phrase. The Linux pin's provenance was read by
#: hand from the reference run's own files: `out/platform.txt` names Python 3.12.3 and no other
#: under `--- python`, `out/DONE` holds 2026-10-25T14:07:30Z, and `out/logs/patched-offline.log`
#: has the 10,000-point test fail with "no cross-interpreter pin for linux-aarch64: 2af1d796...",
#: the digest of the table's entry.
GEODESY_PHRASES = [
    "The packaged capture replays byte for byte on darwin-arm64 and linux-aarch64 (its "
    "observations' SHA-256 d55fd510bf633395192f4ead01cab1753216d870a9219d023a8525138ef05125).",
    "Of the 10,000-point grid, 674 inputs differ by one or two units in the last place of "
    "position_ecef_m between the C libraries (612 coordinate values by 1 ulp, 79 by 2 ulp;",
    "of the 9,326 identical inputs, 5 outputs differ by one unit in the sixth decimal of alt_m "
    "(1e-6 m) at altitudes of 27,451 to 89,704 km, latitude, longitude and kinematics agreeing.",
    "Byte identity across platforms is therefore not guaranteed at extreme heights.",
    "Identity across interpreters on one platform (what CR-R1-06 pins) is shown on darwin-arm64 "
    "(3.11, 3.12, 3.14: Python ",
    " in this session's runs) and not observable on linux-aarch64, whose pin was recorded from "
    "one interpreter (Python 3.12.3, reference run ref-1 of 2026-10-25) (CR-L20).",
]
LINUX_PIN_PROVENANCE = {"evidence_class": "DEV-linux-aarch64", "runs": ["ref-1"],
                        "interpreters": ["3.12.3"], "where": "reference run ref-1 of 2026-10-25",
                        "interpreters_agree": "not observable: one interpreter"}


@case("A-EVIDENCE", "G-R46")
def test_the_geodesy_entry_states_cr_l20s_observation_and_where_each_pin_came_from(report):
    """CR-L20 (A-EVIDENCE: claims matching the tested scope): the report's geodesy entry states
    the observation in full - the packaged capture byte for byte on both platforms, the 674
    inputs that differ in the last place (612 coordinate values by 1 ulp, 79 by 2 ulp), the five
    altitudes at extreme heights - and states identity across interpreters as shown on
    darwin-arm64 and NOT observable on linux-aarch64, whose pin came from one interpreter. The pin
    block carries each pin's provenance, read from the runs: darwin-arm64 from exactly the
    session's offline runs with the patch versions they record (3.11, 3.12 and 3.14, the pin test
    passing in each), linux-aarch64 from the reference run (the literal above, read by hand from
    its files). The CR-L20 owner point and the README's limitation say the same; the README no
    longer says "on one platform", and its "What it is" no longer says the records are the same
    "on every interpreter" but where that was shown (RF review note 4)."""
    geodesy = report["geodesy"]
    for phrase in GEODESY_PHRASES:
        assert phrase in geodesy, phrase
    pins = report["cross_interpreter_pins"]
    provenance = pins["provenance"]
    assert pins["platforms"] == sorted(provenance) == ["darwin-arm64", "linux-aarch64"]
    assert provenance["linux-aarch64"] == LINUX_PIN_PROVENANCE
    offline = [run for run in report["runs"]
               if run["group"] == "offline" and run["platform"] == "Darwin arm64"]
    darwin = provenance["darwin-arm64"]
    assert darwin["runs"] == [run["id"] for run in offline]
    assert darwin["interpreters"] == [run["python"] for run in offline]
    assert [".".join(v.split(".")[:2]) for v in darwin["interpreters"]] == ["3.11", "3.12", "3.14"]
    assert (darwin["evidence_class"], darwin["where"], darwin["interpreters_agree"]) == (
        "DEV-macOS-arm64", "this session's runs", "shown")
    versions = darwin["interpreters"]
    assert (f"shown on darwin-arm64 (3.11, 3.12, 3.14: Python {versions[0]}, {versions[1]} and "
            f"{versions[2]} in this session's runs) and not observable") in geodesy
    point = next(p for p in report["owner_points"] if p["id"] == "CR-L20")["ruling"]
    for phrase in ("linux-aarch64, recorded from one interpreter (Python 3.12.3, reference run "
                   "ref-1 of 2026-10-25)",
                   "is shown on darwin-arm64 and not observable on linux-aarch64",
                   "(612 coordinate values by 1 ulp, 79 by 2 ulp)"):
        assert phrase in point, phrase
    what = flat(section(README, "## What it is"))
    assert ("Identity across interpreters is shown on macOS arm64 from Python 3.11, 3.12 and "
            "3.14, where all three were run; Linux aarch64 ran one interpreter (Python 3.12.3), "
            "so it was not observable there") in what
    assert "on every interpreter" not in what
    limitation = flat(section(README, "### Limitations of this baseline"))
    assert ("Replays are byte-identical across Python 3.11, 3.12 and 3.14 on macOS arm64, where "
            "all three were run against its pin; Linux aarch64's pin was recorded from one "
            "interpreter (Python 3.12.3), so identity across interpreters was not observable "
            "there.") in limitation
    assert "on one platform" not in limitation


#: The PROJ the Linux reference run's reference group measured, read by hand from that run's
#: files: `out/logs/reference.log` holds the line the cs2cs test printed at run time, ending
#: "Rel. 9.4.0, March 1st, 2024", and `out/platform.txt`'s `--- proj` section states that version
#: and the binary /usr/bin/cs2cs.
LINUX_PROJ = {"evidence_class": "DEV-linux-aarch64", "run": "ref-1",
              "proj_version": "Rel. 9.4.0, March 1st, 2024", "cs2cs": "/usr/bin/cs2cs",
              "read_from": "the reference run's files (reference_run.proj)"}
#: What cs2cs prints as its version (PROJ's own form): "Rel. <major>.<minor>.<patch>, <date>".
PROJ_RELEASE = re.compile(r"Rel\. \d+\.\d+\.\d+, \S.*")
#: The tools that write the report and the data it is written from: none may hold a version.
REPORT_TOOLS = ["tests/release_evidence.py", "tests/release_sbom.py", "tests/conftest.py",
                "tests/hla_support.py"]


@case("G-R47", "A-EVIDENCE")
def test_the_report_carries_the_proj_version_cs2cs_stated_in_each_run_of_the_reference_group(
        report):
    """CDV-02 (final review finding F-release-01): the release evidence records the PROJ version
    cs2cs stated at run time and the cs2cs that stated it, never a copied string. For every run
    class that ran the reference group - this session's reference run (DEV-macOS-arm64) and the
    Linux reference run (DEV-linux-aarch64) - the report's `proj` list holds a version of PROJ's
    own form and the fixed place of the cs2cs (`hla_support.TOOL_PLACES`, Homebrew's prefix
    spelled `$HOMEBREW_PREFIX`, R49). This session's entry is the observation the reference-group
    test recorded, carried with each case the test binds (G-R47, G-R29); the Linux entry is read
    from that run's own files (`reference_run.proj`, the literal above). And it is measured, not
    typed: no tool that writes the report or its inputs holds a PROJ version string (a tool with
    the string typed in fails here), and the rendering shows each version."""
    entries = report["proj"]
    ran = {run["evidence_class"] for run in report["runs"] if run["group"] == "reference"}
    ran.add(report["reference_run"]["evidence_class"])
    assert ran == {"DEV-macOS-arm64", "DEV-linux-aarch64"}
    assert sorted(entry["evidence_class"] for entry in entries) == sorted(ran)
    places = {place_text("cs2cs", pathlib.Path(p).expanduser()) for p in TOOL_PLACES["cs2cs"]}
    for entry in entries:
        assert PROJ_RELEASE.fullmatch(entry["proj_version"]), entry
        assert entry["cs2cs"] in places, entry
    assert [e for e in entries if e["evidence_class"] == "DEV-linux-aarch64"] == [LINUX_PROJ]
    assert {k: report["reference_run"]["proj"][k] for k in ("proj_version", "cs2cs")} == {
        k: LINUX_PROJ[k] for k in ("proj_version", "cs2cs")}
    mac = [e for e in entries if e["evidence_class"] == "DEV-macOS-arm64"]
    assert [e["run"] for e in mac] == [run["id"] for run in report["runs"]
                                       if run["group"] == "reference"]
    by_case = {c["id"]: c for c in report["cases"]}
    for case_id in ("G-R47", "G-R29"):
        carried = [(o["run"], o["observation"]) for o in by_case[case_id]["observations"]
                   if o["test"] == release_evidence.PROJ_TEST]
        assert carried == [(e["run"], {"cs2cs": e["cs2cs"], "proj_version": e["proj_version"]})
                           for e in mac], case_id
    typed = re.compile(r"Rel\. \d+\.\d+\.\d+")
    tools = [PACKAGE_ROOT / name for name in REPORT_TOOLS] + sorted(
        p for p in (PACKAGE_ROOT / "tools").rglob("*") if p.is_file())
    for path in tools:
        assert not typed.search(path.read_text(encoding="utf-8")), path
    markdown = (PACKAGE_ROOT / "docs" / "evidence" / "README.md").read_text(encoding="utf-8")
    for entry in entries:
        assert f"`{entry['cs2cs']}` stated `{entry['proj_version']}`" in markdown, entry


@case("G-R05", "G-R02", paragraphs=("SPEC:8", "SPEC:28"))
def test_the_deliverables_of_r05_are_in_the_release(report):
    """R05 and SPEC:8: src/native (the worker), src/synapse_hla (validation, decoding, state and
    projection), the synthetic publisher and the demo orchestration (tools/publisher and the
    package's `_demo`, since tools holds no Python under the repository's rules, D-04), the tests,
    the packaged schemas (the FOM modules are a recorded deviation, OPV-03), the hashed lock
    files, the SBOM, the licence notices, the installation guide and the release evidence report;
    SPEC:28's architecture: the native worker is the one process with an RTI connection, the
    Python host owns the capture and the reducer, the reducer opens no socket and the projector
    reads no clock (the purity tests), replay reads the same frames through the same reducer."""
    for path in ("src/native/worker/main.cpp", "src/native/CMakeLists.txt",
                 "src/synapse_hla/codec.py", "src/synapse_hla/reducer.py",
                 "src/synapse_hla/projector.py", "src/synapse_hla/_demo.py",
                 "tools/publisher/publisher.cpp", "tools/build_openrti.sh", "tests/conftest.py",
                 "src/synapse_hla/schemas/cdm-entity.schema.json", "locks/runtime.lock",
                 "locks/test.lock", "locks/build.lock", "locks/native-toolchain.json",
                 "locks/sbom.cdx.json", "LICENSE", "NOTICE", "licences/README.md",
                 "docs/installation.md", "docs/evidence/evidence-report.json",
                 "docs/evidence/README.md"):
        assert (PACKAGE_ROOT / path).is_file(), path
    assert "OPV-03" in report["integration"]["fom_outside"]
    assert "**FOM modules outside the repository (OPV-03).**" in README
    for name in ("reducer", "projector", "replay", "codec", "geodesy"):
        tree = ast.parse((PACKAGE_ROOT / "src" / "synapse_hla" / f"{name}.py").read_text("utf-8"))
        imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
                    for a in n.names}
        imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree)
                     if isinstance(n, ast.ImportFrom)}
        assert not imported & {"socket", "subprocess", "time"}, name


#: A wall-clock figure as the logs of a run print it ("9.42 sec", "in 120.91s", "(0:02:00)"):
#: durations are not results, so none of them is quoted as one.
DURATION = re.compile(r"\d+(?:\.\d+)?\s*(?:s|sec|seconds)\b|\(\d+:\d\d:\d\d\)")


def test_a_ctest_log_gives_its_result_line_never_its_closing_time(tmp_path):
    """ctest ends its log with the total test time; the report quotes the line that states the
    result, wherever it stands, and refuses a log without exactly one (review finding R9-r1-F2).
    The log here is the shape of ctest's own output, written by hand."""
    log = tmp_path / "ctest.log"
    log.write_text("Test project /work/native\n"
                   "  1/2 Test #1: smoke-version .....   Passed    0.01 sec\n"
                   "  2/2 Test #2: smoke-arguments ...   Passed    0.02 sec\n\n"
                   "100% tests passed, 0 tests failed out of 2\n\n"
                   "Total Test time (real) =   0.05 sec\n", encoding="utf-8")
    assert release_evidence._ctest_result(log) == "100% tests passed, 0 tests failed out of 2"
    log.write_text("Total Test time (real) =   0.05 sec\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        release_evidence._ctest_result(log)


@case("G-R46")
def test_the_reference_runs_figures_are_its_results_and_carry_no_duration(report):
    """R46's actual evidence for the Linux run (DEV-linux-aarch64, D-24): each group's line is the
    result its log states, never a wall-clock figure (review finding R9-r1-F2). The expected
    lines were read by hand from the run's logs (`out/logs/ctest.log`, `patched-offline.log`,
    `rti.log`, `patched-rti.log`, `reference.log`, `perf.log`): ctest's result line, then each
    pytest summary without its duration."""
    ref = report["reference_run"]
    expected = {
        "ctest": "100% tests passed, 0 tests failed out of 100",
        "offline_group": "1 failed, 3084 passed, 213 deselected",
        "rti_group_unpatched": "3 failed, 207 passed, 3088 deselected",
        "rti_group_patched": "210 passed, 3088 deselected",
        "reference_group": "1 passed, 3297 deselected",
        "perf_group": "2 passed, 3296 deselected",
    }
    assert {key: ref[key] for key in expected} == expected
    for key in expected:
        assert not DURATION.search(ref[key]), (key, ref[key])
    markdown = (PACKAGE_ROOT / "docs" / "evidence" / "README.md").read_text(encoding="utf-8")
    assert "- ctest: 100% tests passed, 0 tests failed out of 100; offline group:" in markdown
    assert "Total Test time" not in markdown


@case("G-R42", "A-PERFORMANCE")
def test_the_performance_assessment_states_what_the_runs_recorded(report):
    """R42's entry in the report: the status is BLOCKED or FAIL (never PASS off the reference
    machine), and the assessment says of each run only what that run recorded. Of the Linux
    run's three R42-shaped runs under the demo's main configuration, two ended FAILED with
    E_QUEUE_OVERFLOW (`out/r42/r42-main-2` and `-3`; `-1` COMPLETE, read by hand from its
    summaries); this session's run is said to have overflowed exactly when its own observation
    says so, and otherwise its p95 delay is quoted from that observation."""
    performance = report["performance"]
    assert performance["status"] in ("BLOCKED", "FAIL")
    assessment = performance["assessment"]
    assert assessment.startswith(
        "R42's 1000 reflections per second with every reflection projected and validated as a "
        "CDM Entity (R44) is AT RISK on a 4-vCPU machine: in R42's shape with that configuration "
        "the worker's queue overflowed in 2 of the 3 Linux aarch64 runs (reference_run)")
    observed = [item["observation"] for item in performance["observations"]
                if item["test"] == release_evidence.R42_TEST]
    assert len(observed) == 1
    seen = observed[0]
    if seen["overflow"]:
        assert "it overflowed in this session's development run" in assessment
    else:
        assert "overflowed in this session" not in assessment
        if seen["load_with_output"] == seen["load_expected"]:
            assert (f"lost no load reflection ({seen['load_with_output']} of "
                    f"{seen['load_expected']} output), with a p95 callback-to-output delay of "
                    f"{seen['p95_ms']} ms") in assessment


# ================================================================== R44 and the carried G-R44

@case("G-R44")
def test_the_cdm_history_and_the_upgrade_rule_are_recorded(report):
    """R44's two clauses carried to the release (CR-R3-11) under D-28 and CR-L18: the release
    evidence names the handoff's CDM baseline, commit c4bba1b6 with synapse-cdm 3.1.1 and schema
    3.0.0, as the source of the vendored Entity schema, the floor 3.8.0 at its commit 0d4cf0e and
    the version the session tested with, which (CR-L22) satisfies the declared range and is at
    most the installed one, and marks the 3.1.1 baseline a recorded deviation on the owner list;
    the README records the migration (the two differences and the re-verification) and the
    upgrade rule, and the installation guide states the rule too. The rule includes what the
    offline group enforces of the installed set: moving the locked set needs the locks, the SBOM
    and the evidence report regenerated (review finding R9-r1-F4), and synapse-cdm, the sibling,
    is held to the declared range at or above its locked version (CR-L22), so a later one fails
    no test by design and an earlier one fails three, which the README and the guide count as
    observed with each installed (review finding R9-r2-F8: the locks test, the SBOM test and this
    one)."""
    import importlib.metadata
    cdm = report["cdm"]
    assert cdm["handoff_baseline"] == {
        "synapse_cdm": "3.1.1", "commit": "c4bba1b6ebfdfe956f6efc2b3a81a04db2b4bb5b",
        "note": "the source of the vendored cdm-entity schema and of the fixtures; the package "
                "was developed and tested against it before landing"}
    assert cdm["floor"] == {"synapse_cdm": "3.8.0", "schema_version": "3.2.0",
                            "commit": "0d4cf0e00f9636752c87fe47b50726aa0015b460",
                            "declared": "synapse-cdm>=3.8.0,<4"}
    assert cdm["contract"]["schema_version"] == "3.0.0"
    tested = tuple(int(part) for part in cdm["tested_with"].split("."))
    installed = tuple(int(part) for part in importlib.metadata.version("synapse-cdm").split("."))
    assert (3, 8, 0) <= tested < (4, 0, 0), cdm["tested_with"]
    assert tested <= installed, cdm["tested_with"]
    assert "CR-L18" in cdm["deviation"]
    assert cdm["upgrade_rule"].endswith(
        "; moving the locked set (synapse-cdm 3.9.0) also needs locks/ (the lock files and the "
        "SBOM) and this report regenerated for the set in use, because the offline group holds "
        "every other installed locked distribution to its locked version and synapse-cdm, the "
        "repository's sibling distribution, to the declared range at or above its locked "
        "version (CR-L22)")
    assert "CR-L18" in [p["id"] for p in report["owner_points"]]
    text = flat(section(README, "## The CDM"))
    for statement in ("synapse-cdm 3.1.1 at commit `c4bba1b6ebfdfe956f6efc2b3a81a04db2b4bb5b` "
                      "(CDM schema 3.0.0)",
                      "moved to the repository's main line at synapse-cdm 3.8.0 (CDM schema "
                      "3.2.0), which is the floor it declares (`synapse-cdm>=3.8.0,<4`), and "
                      "landed at synapse-cdm 3.9.0 (the same CDM schema), the release `locks/` "
                      "pins and the evidence report was tested with",
                      "the `default` of `schema_version` (3.0.0 to 3.2.0",
                      "the `PositionSource` enum, which gained `SENSOR` and `UNKNOWN`",
                      "`d55fd510bf633395192f4ead01cab1753216d870a9219d023a8525138ef05125`",
                      "**The upgrade rule (R44).**",
                      "An upgrade must keep the packaged fixtures unchanged, pass that test and "
                      "the byte-identical replay, and record its migration here",
                      "Moving the locked set to another synapse-cdm than the locked 3.9.0 also "
                      "needs `locks/` regenerated for the set in use (`locks/tested-set.in`, the "
                      "three lock files with the command each names in its first lines, and the "
                      "SBOM with `python tests/release_sbom.py`) and the evidence report with it",
                      "So with a later synapse-cdm inside the range installed no test fails by "
                      "design, and with an earlier one three do until then: the two that hold the "
                      "installed set to the locks and the SBOM, and the one that holds the "
                      "version the evidence report was tested with to at most the installed "
                      "one"):
        assert statement in text, statement
    guide = flat(section(INSTALL, "## Upgrading synapse-cdm (R44)"))
    for statement in ("keep the packaged fixtures unchanged",
                      "the new SDK's Entity schema must be additive over the 3.0.0 one",
                      "the packaged capture must still replay to the packaged expected "
                      "observations byte for byte", "record the migration",
                      "with a later SDK inside the declared range none fails by design, and with "
                      "an earlier one than the locked 3.9.0 three fail by design until step 4 is "
                      "done: the two that hold the installed set to the locks and the SBOM, and "
                      "the one that holds the version the evidence report was tested with to at "
                      "most the installed one",
                      "4. regenerate `locks/` for the set in use (`locks/tested-set.in`, the "
                      "three lock files with the command each names in its first lines, and the "
                      "SBOM with `python tests/release_sbom.py`) and the evidence report with it"):
        assert statement in guide, statement


# ==================================================== the documents' statements (carried clauses)

#: The evidence report's integration section (the integration report), member by member, as R10
#: with NAT-01, R13, R14 with NAT-03 and NAV-02, R39, R40, R47, R50, OPS-01 and OPV-03 ask it to
#: state; written here, not read from the evidence tool (review finding R9-r1-F1).
INTEGRATION_REPORT = {
    "tested_reference": "OpenRTI 814a210978b7faafd65affbe70a2e25679921b23 is the tested "
                        "reference; neither a customer simulator nor a second RTI implementation "
                        "was tested.",
    "public_reference": "OpenRTI's participation demonstrates a public reference, not standards "
                        "certification or a second independent RTI federation test.",
    "co_publication": "Through the pinned OpenRTI, objects from other processes whose federate "
                      "publishes only a subclass of PhysicalEntity are not discovered; the "
                      "synthetic publisher publishes at PhysicalEntity and at GroundVehicle.",
    "orderly_exit": "When rtinode exits or the connection ends with FIN, the observer gets no "
                    "connectionLost but a removal of every object it knows; last-received "
                    "values are never kept.",
    "retractable": "A retractable update is captured and quarantines its object; no claim is "
                   "made that replay can undo a retractable update.",
    "demo_clock": "The demo uses external_elapsed only under the documented synthetic 1x "
                  "scenario-clock assumption (the scenario clock runs at 1x from the configured "
                  "epoch); its second run uses time policy none and fabricates no Entity.",
    "fom_outside": "The five RPR FOM modules and the OpenRTI source archive are not in the "
                   "repository: the release evidence kit supplies them, held to their pins (a "
                   "recorded deviation from R05, OPV-03).",
    "transport": "RTI traffic is neither authenticated nor encrypted by this adapter; a remote "
                 "deployment relies on an externally secured network.",
    "allowed_claim": "Receives and replays the tested RPR FOM 2.0 physical-entity attribute "
                     "subset through the pinned OpenRTI baseline and projects externally timed "
                     "state into CDM.",
    "excluded_claims": ["all-HLA support", "full RPR FOM support",
                        "verified integration with any site or installation, the one that "
                        "motivated the specification included",
                        "verified SWORD, WASP or Nebula integration",
                        "automatic simulator control", "source-authoritative UTC timing",
                        "DIS/HLA identity fusion", "authenticated RTI transport"],
}

#: (gate, what each document must say, in its own words): the README, the installation guide
#: and the evidence report's integration section (the integration report).
STATEMENTS = {
    "NAT-01": (
        "Objects from other processes whose federate publishes only a subclass of "
        "`PhysicalEntity` (for example `GroundVehicle`) are not discovered.",
        "Objects whose publishing federate publishes only a subclass of `PhysicalEntity` are not "
        "discovered through the pinned OpenRTI",
        "co_publication"),
    "NAV-02": (
        "OpenRTI reports no connection loss to the observer: it removes every object the "
        "observer knows, and the session stays open with no objects until it is stopped. "
        "Last-received values are never kept in that case.",
        "OpenRTI gives the observer no connection loss but a removal of every object it knows; "
        "last-received values are not kept.",
        "orderly_exit"),
    "R13": (
        "A retractable update or removal is captured and quarantines its object; nothing in this "
        "release can undo one, live or in replay.",
        "A retractable update or removal is captured and quarantines its object. Nothing in this "
        "release can undo a retractable update, live or in replay.",
        "retractable"),
    "R39-clock": (
        "the scenario clock runs at 1x from the configured epoch",
        "under the documented synthetic assumption that the scenario clock runs at 1x from the "
        "configured epoch",
        "demo_clock"),
    "R39-reference": (
        "OpenRTI is the tested reference; neither a customer simulator nor a second RTI "
        "implementation was tested.",
        "OpenRTI is the tested reference; no customer simulator and no second RTI implementation "
        "is tested.",
        "tested_reference"),
}


@case("G-R10", "G-R14", "G-R13", "G-R39", "G-R47", "G-R35", "G-R40",
      paragraphs=("SPEC:166", "SPEC:211"))
def test_the_documents_state_the_baseline_limitations(report):
    """The clauses carried to the release: R10 with NAT-01 (subclass-only publishers are not
    discovered through the pinned OpenRTI), R14 with NAT-03 and NAV-02 (an orderly RTI exit gives
    no connectionLost but a removal of every known object; last-received values are not kept),
    R13 (a retractable update is captured and quarantines its object; no claim that replay can
    undo one), R39 (the documented synthetic 1x scenario-clock assumption; OpenRTI the tested
    reference, no customer simulator, no second RTI; SPEC:211), R47 (OpenRTI's participation is a
    public reference, not certification or a second independent RTI federation test), SPEC:166
    (export-capture copies a verified original capture byte for byte and is no HLA re-export)
    and R40 (no transport security is claimed): each in the README, the installation guide and
    the evidence report's integration section."""
    readme, guide = flat(README), flat(INSTALL)
    integration = report["integration"]
    assert integration == INTEGRATION_REPORT
    assert release_evidence.INTEGRATION == INTEGRATION_REPORT
    for key, (in_readme, in_guide, member) in STATEMENTS.items():
        assert flat(in_readme) in readme, key
        assert flat(in_guide) in guide, key
        assert integration[member] == INTEGRATION_REPORT[member], key
    assert "1x scenario-clock assumption" in integration["demo_clock"]
    assert ("that OpenRTI's participation is standards certification or a second independent "
            "RTI federation test: it demonstrates a public reference") in readme
    assert ("`export-capture` copies only a verified original capture, byte for byte: it does "
            "not edit, re-encode or re-export HLA data, it constructs no HLA packets and replays "
            "no traffic into an RTI.") in readme
    assert ("`export-capture` copies a verified original capture byte for byte. It is not an HLA "
            "re-export: it does not edit or re-encode HLA data, constructs no HLA packets and "
            "replays no traffic into an RTI.") in guide
    assert ("RTI traffic is neither authenticated nor encrypted by this adapter, and a remote "
            "deployment relies on an externally secured network") in readme
    assert integration["transport"].startswith("RTI traffic is neither authenticated nor "
                                               "encrypted by this adapter")


# ============================================================================ R49: the README

#: The commands of a fresh engineer, in the README's order (R49).
README_COMMANDS = [
    'python3.12 -m venv "$WORK/venv"',
    '"$WORK/venv/bin/python" -m pip install --require-hashes -r locks/test.lock',
    '"$WORK/venv/bin/python" -m pip install --require-hashes -r locks/build.lock',
    '"$WORK/venv/bin/python" -m pip install --no-deps --no-build-isolation .',
    'bash tools/build_openrti.sh "$SYNAPSE_HLA_FOM_DIR/openrti-814a210.tar.gz" "$WORK/openrti"',
    'cmake -S src/native -B "$WORK/native" -DOPENRTI_PREFIX="$WORK/openrti/install"',
    'cmake --build "$WORK/native"',
    'ctest --test-dir "$WORK/native"',
    'cmake --install "$WORK/native" --prefix "$PKG"',
    "venv/bin/synapse-hla --version",
    "venv/bin/synapse-hla self-test --out selftest",
    "venv/bin/synapse-hla demo --out demo",
    "venv/bin/synapse-hla inspect --capture demo/main/capture.jsonl",
    "venv/bin/synapse-hla verify --capture demo/main/capture.jsonl",
    "venv/bin/synapse-hla replay --capture demo/main/capture.jsonl --out replay",
    "cmp demo/main-replay/observations.jsonl replay/observations.jsonl",
]
#: Every file and directory the README's table says those commands create.
GENERATED = ["build-record.txt", "bin/rtinode", "include/rti1516e/", "share/OpenRTI/",
             "sc-hla-federate", "sc-hla-publisher", "sc-hla-harness", "sc-hla-test-federate",
             "sc-hla-reference-encode", "sc-hla-reference-fom-check", "smoke/", "licences/",
             "self-test.json", "fixture-replay/", "demo/demo.json", "main/", "main-replay/",
             "no-time/", "no-time-replay/", "capture.jsonl", "observations.jsonl",
             "diagnostics.jsonl", "run.json"]


def readme_command_block() -> list[str]:
    block = section(README, "### 2. Commands, expected exit codes and the files they create")
    code = block.split("```\n", 2)[1]
    return [line.split("  #", 1)[0].rstrip() for line in code.splitlines()]


@case("G-R49")
def test_the_readme_shows_the_commands_of_a_clean_checkout_their_exits_and_their_files():
    """R49: from a clean checkout, the documented toolchain, the pinned OpenRTI build, the
    adapter build, self-test, demo, inspecting the report and reproducing the replay, in that
    order, each command with its expected exit code; the files every step creates; the exit codes
    of the command line (OPS-02's table); toolchain packages for Ubuntu and macOS, among them the
    runtime libraries and the test tools of the Linux reference run (libexpat1, zlib1g,
    libstdc++6, lsof, proj-bin) and uv with the step that primes its cache for the rti group."""
    lines = readme_command_block()
    commands = [line for line in lines if line and not line.startswith(("export ", "PKG=",
                                                                         "cd "))]
    assert commands == README_COMMANDS
    exits = [line for line in section(README, "### 2. Commands, expected exit codes and the "
                                              "files they create").split("```\n", 2)[1]
             .splitlines() if line.split("  #", 1)[0].rstrip() in README_COMMANDS]
    assert all(line.endswith("# exit 0") for line in exits) and len(exits) == len(commands)
    table = section(README, "### 2. Commands, expected exit codes and the files they create")
    for name in GENERATED:
        assert f"`{name}" in table or f"/{name}" in table or f" {name}" in table, name
    exit_table = section(README, "## The command line")
    for row in ("| 0 |", "| 2 |", "| 3 |", "| 4 |", "| 5 |", "| 6 |", "| 130, 143 |", "| 1 |"):
        assert row in exit_table, row
    toolchain = section(README, "### 1. Toolchain")
    for package in ("build-essential", "g++-13", "cmake", "libexpat1-dev", "zlib1g-dev",
                    "libexpat1", "zlib1g", "libstdc++6", "lsof", "proj-bin", "uv"):
        assert f"`{package}`" in toolchain, package
    # The rti group's installed-form test builds the wheel offline: the one online step that puts
    # the pinned build backend into uv's cache (review finding R9-r1-F3).
    tests = section(README, "## Running the tests")
    assert ('uv build --wheel --out-dir "$WORK/dist" --build-constraints locks/build.lock '
            "--require-hashes") in tests
    assert "Without it the installed-form test reports `BLOCKED`" in flat(tests)


#: CR-R7-01's exit statuses of the worker as the README lists them (final review finding
#: F-native-01), each with the enumerator of `src/native/worker/process.h` that carries it; the
#: meanings are that header's comments in the README's words.
WORKER_EXITS = {
    0: ("kExitStopped", "the orderly stop completed, or `--version`"),
    1: ("kExitFailure", "a terminal condition was reported on file descriptor 3"),
    64: ("kExitUsage", "the argument vector is neither `--version` nor the three tokens of "
                       "OPS-08"),
    70: ("kExitStatusChannel", "file descriptor 3 is not open, or not a pipe (NAT-09)"),
    71: ("kExitChannelLost", "stdout or file descriptor 3 broke (EPIPE): nobody is left to "
                             "report to"),
    72: ("kExitParentGone", "the host that started the worker has gone"),
}


@case("G-R49")
def test_the_readme_lists_the_workers_exit_statuses_as_process_h_defines_them():
    """CR-R7-01 ("The host reads only 0 / not 0. README lists them."): the README's command-line
    section lists the worker's six exit statuses with their meanings and says the host reads
    only 0 and not 0; the statuses are exactly the enumerators of process.h's ExitStatus, value
    for value."""
    source = (PACKAGE_ROOT / "src" / "native" / "worker" / "process.h").read_text("utf-8")
    enum = re.search(r"enum ExitStatus : int \{(.*?)\};", source, re.S).group(1)
    enumerators = {int(value): name for name, value in re.findall(r"(k\w+) = (\d+),", enum)}
    assert enumerators == {status: name for status, (name, _meaning) in WORKER_EXITS.items()}
    text = section(README, "## The command line")
    for status, (_name, meaning) in WORKER_EXITS.items():
        assert f"| {status} | {meaning} |" in text, status
    assert ("The native worker `sc-hla-federate` has exit statuses of its own (CR-R7-01). The "
            "host reads only 0 and not 0 (0 after its orderly stop)") in flat(text)


@case("G-R49", "G-R36")
def test_the_readme_states_what_a_stop_before_observes_session_self_test_and_an_overflow_do():
    """Three statements the final review asked the README to make (R49: the documentation states
    what the commands do): F-host-02, a stop that reaches observe before its session exists (its
    own configuration and FOM pre-flight) exits 130 or 143 like the other commands, and observe
    stops in order only once a session exists (CR-R6-05); F-host-04, the scope of self-test (the
    vectors, the packaged schemas' validity, the pins, the packaged replay; not the demo's
    checkpoints, not the schemas' strictness); F-native-05, what the one-second drain after an
    overflow loses (SPEC:277) and that only the footer marks it."""
    text = flat(README)
    for statement in (
            "| 130, 143 | stopped by SIGINT or SIGTERM before the command had its result; "
            "`observe` stops its session in order once one exists, and a stop before that "
            "(during its own configuration and FOM pre-flight) exits 130 or 143 like the other "
            "commands |",
            "It runs, offline and without pytest, the packaged attribute vectors, the geodesy "
            "points, the identity example and both example configurations, checks that every "
            "packaged schema is a valid schema and every fixture has its recorded digest, checks "
            "the FOM pins, and replays the packaged capture against its expected observations; "
            "it does not run the demo's checkpoints and does not test how strict the schemas "
            "are.",
            "After an overflow, as after any failure the worker reports, the host reads the "
            "worker's complete frames for at most one second and then stops it: frames the "
            "worker had already accepted but the host had not read by then are lost, and only "
            "the footer's `E_QUEUE_OVERFLOW` marks them (R41)."):
        assert statement in text, statement[:60]
    assert "`observe` instead stops" not in text


#: Absolute paths of a particular machine, credentials and references to an earlier chat.
FORBIDDEN_IN_DOCUMENTS = [
    re.compile(r"(?:^|[\s(`'\"=])/(?:Users|home|private|tmp|var/folders|root|opt/homebrew)/"),
    re.compile(r"[A-Za-z]:\\\\"),
    re.compile(r"(?i)password|passwd|secret|api[_ -]?key|access[_ -]?token|bearer "),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:chat|conversation|earlier session|as discussed)\b"),
]
DOCUMENTS = ["README.md", "docs/installation.md", "licences/README.md", "docs/evidence/README.md",
             "docs/evidence/evidence-report.json"]


@case("G-R49")
@pytest.mark.parametrize("name", DOCUMENTS)
def test_the_documents_hold_no_machine_path_credential_or_earlier_chat(name):
    """R49: no credential, no machine-specific absolute path and no reference to an earlier chat
    in the README, the installation guide, the licence statement and the evidence report."""
    text = (PACKAGE_ROOT / name).read_text(encoding="utf-8")
    for pattern in FORBIDDEN_IN_DOCUMENTS:
        assert not pattern.search(text), (name, pattern.pattern, pattern.search(text))


#: R02's excluded services, in the README's words.
UNSUPPORTED = ["Interactions", "publication", "ownership transfer", "DDM regions",
               "save and restore", "time regulation", "time-constrained advancement",
               "dead-reckoning execution", "entity control", "commands",
               "firing and detonation", "undoing a retractable update"]


@case("G-R49", "G-R02")
def test_the_profile_declaration_enumerates_the_four_attributes_and_the_unsupported_services():
    """R49 (the completed product ships a profile declaration that enumerates its four subscribed
    attributes and unsupported services) and R02: the README's declaration (shipped in the
    wheel's metadata as its description) names the profile, the API, the five modules in R04's
    order, exactly the four attributes the worker subscribes to (read from its source) at
    PhysicalEntity, and every service R02 excludes, and the substitutes R02 forbids."""
    declaration = flat(section(README, "## Profile declaration"))
    attributes = re.findall(r"`(EntityIdentifier|EntityType|Spatial|ForceIdentifier)`",
                            declaration.split("**Subscribed attributes.**", 1)[1].split(
                                "**Services used.**", 1)[0])
    worker = (PACKAGE_ROOT / "src" / "native" / "worker" / "observer.cpp").read_text("utf-8")
    worker += (PACKAGE_ROOT / "src" / "native" / "worker" / "constants.h").read_text("utf-8")
    subscribed = sorted(set(re.findall(r'"(EntityIdentifier|EntityType|Spatial|ForceIdentifier)"',
                                       worker)))
    assert sorted(attributes) == subscribed == ["EntityIdentifier", "EntityType",
                                                "ForceIdentifier", "Spatial"]
    assert "`HLAobjectRoot.BaseEntity.PhysicalEntity`" in declaration
    assert "Profile `SC-HLA-RPR2-OBS-1`" in declaration
    assert "HLA Evolved (IEEE 1516-2010) through the C++ rti1516e API" in declaration
    modules = re.findall(r"`(RPR-[A-Za-z]+_v2\.0\.xml)`", declaration)
    assert modules == list(_fom.FOM_MODULES)
    unsupported = declaration.split("**Unsupported services.**", 1)[1]
    for service in UNSUPPORTED:
        assert service in unsupported, service
    for substitute in ("HLA 1.3", "IEEE 1516-2000", "HLA 4", "RPR FOM draft 17", "RPR FOM 3.0"):
        assert substitute in unsupported, substitute


# ================================================================================ R50: claims

@case("G-R50", paragraphs=("SPEC:10", "SPEC:267", "SPEC:269", "SPEC:271"))
def test_the_claims_are_r50s_allowed_claim_and_its_exclusions(report):
    """R50: the allowed claim in substance, every excluded claim, and no silent widening of 1.0;
    SPEC:10 (not a certification: the named profile and the tested OpenRTI baseline only, no
    compatibility with a specific simulator or installation); SPEC:267 (the RPR modules come from
    the identified immutable public copy, not a direct download, with their notices); SPEC:269
    (the services OpenRTI's own README lists as missing, ownership, DDM, save and restore, are
    unsupported here, and its connection-loss behaviour is stated as a limitation); SPEC:271
    (the specification's targets are requirements, not measurements; customer compatibility is
    a later evidence task, NOT_TESTED). The evidence report states the same claims."""
    claims = flat(section(README, "## Claims"))
    allowed = flat(INTEGRATION_REPORT["allowed_claim"])
    assert "It " + allowed[0].lower() + allowed[1:] in claims
    excluded = section(README, "### What it does not claim")
    for item in ("support for HLA in general, or for the RPR FOM beyond the four attributes",
                 "verified integration with any site or installation (the one that motivated "
                 "the specification included), or with SWORD, WASP or Nebula",
                 "control of a simulator or simulation", "source-authoritative UTC timing",
                 "fusion of HLA identities with DIS identities",
                 "authenticated or encrypted RTI transport"):
        assert item in flat(excluded), item
    assert ("Future extensions need a new profile version, new schemas and new tests; version "
            "1.0 of this profile is not widened silently.") in claims
    assert ("This release is not a certification. It establishes the named profile and the "
            "tested OpenRTI baseline only, and not compatibility with any specific simulator or "
            "installation.") in claims
    assert ("acceptance targets (the performance target among them) are requirements this "
            "release is measured against, not results") in claims
    assert "Compatibility with a customer's system is a later evidence task." in claims
    licences = flat(LICENCES)
    assert ("They come from the immutable public repository copy at commit "
            "`9627bab695779a659800c7921af5d65c0f5d0e00`, not from a direct download from SISO, "
            "and keep their SISO identification.") in licences
    unsupported = flat(section(README, "## Profile declaration"))
    for missing in ("ownership transfer", "DDM regions", "save and restore"):
        assert missing in unsupported
    assert "**Orderly RTI exit (NAT-03, NAV-02).**" in README
    assert report["integration"]["allowed_claim"] == INTEGRATION_REPORT["allowed_claim"]
    assert report["integration"]["excluded_claims"] == INTEGRATION_REPORT["excluded_claims"]
    for widening in ("all of HLA", "full RPR FOM support is", "certified", "verified with SWORD"):
        assert widening not in README, widening


# ===================================================================== R03, R04: distribution, FOM

@case("G-R03", paragraphs=("SPEC:20",))
def test_a_separate_distribution_that_is_no_cdm_adapter_and_changes_no_cdm_schema():
    """R03: the distribution synapse-hla, import synapse_hla, the executable sc-hla-federate (the
    CMake target and the name the host runs); every module of the package imported registers
    nothing in synapse_cdm's adapter registry and none subclasses its Adapter; the CDM Entity
    schema the projector validates against is the handoff's, byte for byte (no change to it);
    SPEC:20: the README names the reference platform and the pinned OpenRTI commit."""
    import importlib
    import tomllib

    from synapse_cdm import adapter as cdm_adapter
    project = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    assert project["name"] == "synapse-hla" and "entry-points" not in project
    before = dict(cdm_adapter.REGISTRY)
    for path in sorted((PACKAGE_ROOT / "src" / "synapse_hla").glob("*.py")):
        module = importlib.import_module(f"synapse_hla.{path.stem}" if path.stem != "__init__"
                                         else "synapse_hla")
        for value in vars(module).values():
            if isinstance(value, type) and value is not cdm_adapter.Adapter:
                assert not issubclass(value, cdm_adapter.Adapter), (path.stem, value)
    assert dict(cdm_adapter.REGISTRY) == before
    assert not [k for k in cdm_adapter.REGISTRY if "hla" in str(k).lower()]
    cmake = (PACKAGE_ROOT / "src" / "native" / "CMakeLists.txt").read_text("utf-8")
    assert "add_executable(sc-hla-federate worker/main.cpp)" in cmake
    assert host.WORKER_NAME == "sc-hla-federate"
    pins = {e["path"]: e["sha256"] for e in contract_json("vendored-pins.json")["files"]}
    entity = (PACKAGE_ROOT / "src/synapse_hla/schemas/cdm-entity.schema.json").read_bytes()
    assert hashlib.sha256(entity).hexdigest() == pins[
        "src/synapse_hla/schemas/cdm-entity.schema.json"]
    assert "It is not a registered CDM adapter" in flat(README)
    assert "`814a210978b7faafd65affbe70a2e25679921b23`" in README


@case("G-R04")
def test_the_five_modules_their_order_pins_source_and_attribution():
    """R04: the five modules in the order Foundation, Enumerations, Base, Physical, Switches with
    their file names and digests in the packaged pins.json, retrieved from the immutable public
    copy at commit 9627bab695779a659800c7921af5d65c0f5d0e00; their SISO identification and
    notices kept (the modules are used only when their bytes match the pins, so nothing in them
    can have been changed); the attribution "Reprinted with permission from SISO Inc." preserved
    in the release's licence statement; no module and no standards prose in the package."""
    pins = strict_json((PACKAGE_ROOT / "src" / "synapse_hla" / "pins.json").read_bytes())
    assert pins["rpr_mirror_commit"] == "9627bab695779a659800c7921af5d65c0f5d0e00"
    assert list(_fom.FOM_MODULES) == ["RPR-Foundation_v2.0.xml", "RPR-Enumerations_v2.0.xml",
                                      "RPR-Base_v2.0.xml", "RPR-Physical_v2.0.xml",
                                      "RPR-Switches_v2.0.xml"]
    pinned = {e["path"] for e in pins["files"]}
    assert set(_fom.FOM_MODULES) <= pinned
    assert '"Reprinted with permission from SISO Inc."' in LICENCES
    assert not list(PACKAGE_ROOT.rglob("*.xml"))


# ================================================================================ R37: diagnostics

@case("G-R37")
def test_a_diagnostic_carries_r37s_fields_a_bounded_message_and_never_the_source_text(tmp_path):
    """R37 through a replay: a reflection with a malformed EntityIdentifier (E_ATTRIBUTE_LENGTH)
    of an object whose name is a hostile 1024-byte string produces a diagnostic record with
    exactly severity, code, message, seq, generation, object_token and attribute; its message is
    at most 1024 UTF-8 bytes and quotes neither the object's name nor the tag; the raw source
    stays in the capture (the replay's copy holds the frame's bytes) and the capture is not
    discarded: the other records are still written."""
    name = "\x1b[31m" + "\N{RIGHT-TO-LEFT OVERRIDE}" * 300 + "n"
    assert len(name.encode("utf-8")) <= 1024
    tag = ("ab" * 2048)
    capture = (CaptureBuilder()
               .frame(1, 0, event_generation_start())
               .frame(1, 0, event_discover("o1", name))
               .frame(1, 1000, event_reflect("o1", (("EntityIdentifier", "0001"),),
                                             tag_hex=tag))
               .frame(1, 2000, event_generation_end()).footer()
               .write(tmp_path / "capture.jsonl"))
    summary = replay(capture, tmp_path / "run")
    assert summary["status"] == "COMPLETE"
    records = [json.loads(line) for line in
               (tmp_path / "run" / "diagnostics.jsonl").read_bytes().splitlines()]
    diagnostics = [r for r in records if r["kind"] == "diagnostic"]
    assert len(diagnostics) == 1
    payload = diagnostics[0]["payload"]
    assert set(payload) == {"severity", "code", "message", "seq", "generation", "object_token",
                            "attribute"}
    assert (payload["severity"], payload["code"], payload["seq"], payload["generation"],
            payload["object_token"], payload["attribute"]) == (
        # The frames are numbered from 1: generation_start, discover, then the reflection, 3.
        "ERROR", "E_ATTRIBUTE_LENGTH", 3, 1, "o1", "EntityIdentifier")
    assert 0 < len(payload["message"].encode("utf-8")) <= 1024
    assert name[:8] not in payload["message"] and "abab" not in payload["message"]
    assert (tmp_path / "run" / "capture.jsonl").read_bytes() == capture.read_bytes()
    observations = (tmp_path / "run" / "observations.jsonl").read_bytes()
    assert b'"kind":"snapshot"' in observations


# ================================================================== the owner list (CR-L06)

#: The CR-L06 list with every extension the rounds made (DECISIONS: the CR-L06 row; C.2, C.4,
#: C.5 and the checkpoint; C.6, C.8, C.9, C.11, C.12, C.13 with D, C.14), the one point R9 added,
#: and the final review's points (C.16, D.2's CR-L26), as owner-points.json must hold them.
OWNER_POINT_IDS = [
    "OPV-03", "NAT-05", "NAT-01", "NAT-02", "NAT-03, NAV-02", "OPS-01", "OPS-02", "OPS-04",
    "OPS-05, NAT-07", "OPS-21", "RED-09, COD-12", "OPS-27", "NAT-12", "NAT-14", "CDV-02",
    "CDV-01, COD-08", "COD-01", "COD-03", "COD-10", "COD-13", "RED-18, COD-15", "CR-R3-06",
    "CR-L09", "CR-L10", "CR-L11", "CR-L12", "CR-L13", "CR-L14", "CR-R2-06", "CR-R4-05",
    "RED-V-01, CR-R2-01, CR-R2-10", "CR-R2-13", "SPEC:68 key order", "CR-R2-22", "CR-R4-08",
    "CR-R4-09", "CR-R5-01", "CR-R5-20", "CR-R5-21", "Terminal code of two pending pipes",
    "CR-R6-01", "CR-R6-03", "CR-R6-05", "CR-R6-07", "CR-R6-F2", "CR-R6F-04", "CR-R7-03",
    "CR-R7-04", "CR-R7-05", "CR-R7-06", "CR-R7-09", "CR-R7-10", "CR-R7-22", "CR-R8-14",
    "CR-R8-15", "CR-R8-16", "CR-R8-17", "CR-R8-18", "CR-L17, CR-R8-12", "CR-L18", "CR-L20",
    "CR-new-R9-03", "F-native-03", "F-native-04", "F-release-03", "CR-L26", "F-trace-03",
    "F-host-05", "F-host-03"]


@case("G-R48", "G-R01")
def test_the_owner_list_is_complete_and_each_ruling_is_bound(bindings, report):
    """The section "Specification points for the owner" (R01: a discrepancy is a contract defect,
    never permission to guess, so every ruling the run took is laid before the owner): the
    evidence report holds owner-points.json's list, which is exactly the CR-L06 list as extended
    by the rounds, each entry with its point, the ruling taken and the tests that bind it, every
    one of which a real collection of the suite has."""
    points = contract_json("owner-points.json")["points"]
    assert [p["id"] for p in points] == OWNER_POINT_IDS
    assert report["owner_points"] == points
    functions = {node.split("[", 1)[0] for node in bindings} | {
        node.split("[", 1)[0] for node in _all_test_nodes()}
    for point in points:
        assert point["point"] and point["ruling"] and point["source"], point["id"]
        assert point["bound_at"], point["id"]
        for test in point["bound_at"]:
            assert test in functions, (point["id"], test)


def _all_test_nodes() -> set[str]:
    """Every test function of the suite, by file and name, read from the sources."""
    out = set()
    for path in sorted((PACKAGE_ROOT / "tests").glob("test_hla_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                out.add(f"tests/{path.name}::{node.name}")
    return out
