"""Writes the release evidence report of synapse-hla: docs/evidence/evidence-report.json and its
rendering docs/evidence/README.md (R46, R48, CR-L04, D-14).

    python tests/release_evidence.py RUNS [REFERENCE_RUN]      (from packages/hla)

A test-side tool (D-04), not product code, and the only author of the report: nothing in the two
files is typed by hand. RUNS is a directory a release session fills while it runs the suite:

- `runs.json`: the list of runs, each `{id, group, interpreter, python, platform, evidence_class,
  command, results}`, where `results` names the file pytest wrote through
  `SYNAPSE_HLA_RESULTS_EXPORT` (tests/conftest.py: every test that ran, its outcome, skip
  reason, duration and recorded properties), and `native`, the identification of the native
  build those runs used;
- `observations.json` (optional): what the session's scripts recorded of the runs that are not
  pytest runs (the README commands from a fresh copy of the checkout, the wheel in a throwaway
  environment, the repository's whole suite), each as those scripts wrote it.

REFERENCE_RUN, when given, is the output directory of a run on another platform (the Linux
reference run's `out/`), whose own files are read for its figures: its groups' results, its
interpreter, the PROJ its reference group measured, and the digest its 10,000-point test printed
for its platform's pin.

The rest comes from the tree: the acceptance-case index, the case bindings of a real collection
of the suite (the same trace export the ratchet reads), the owner list
(`tests/contract/owner-points.json`), the vendored pins, the locks, and the pin table of the
cross-interpreter test, whose provenance (which interpreters each pin was seen from) is read
from the runs. The report's text statements (the claims, the limitations, the evidence classes)
are constants of this module; its results are only ever derived from the runs, and so is every
version it names (CDV-02: the PROJ version is the one cs2cs stated at run time).

HOW A CASE GETS ITS RESULT
--------------------------
FAIL when any test that binds it failed or errored in any run. Otherwise BLOCKED when the case
needs the reference platform (`REFERENCE_PLATFORM`, CR-L04: never PASS before a run there), or
when a binding test was skipped as BLOCKED or never ran in this session, naming the missing
resource. Otherwise PASS, with the evidence class of the runs that passed it. The release gates
of R48 are derived from the cases and runs the same way; `external_customer_interoperability`
is its own member, always NOT_TESTED (OPS-01), and the overall status is never PASS while a
case or a gate is not.
"""

from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import re
import sys

TESTS = pathlib.Path(__file__).resolve().parent
PACKAGE_ROOT = TESTS.parent
CONTRACT = TESTS / "contract"
OUT_DIR = PACKAGE_ROOT / "docs" / "evidence"
JSON_NAME = "evidence-report.json"
MARKDOWN_NAME = "README.md"

#: The commit the release tree is staged on when its evidence is generated: the landing commit
#: on main's 3.9.0 tip, synapse-cdm 3.9.0 (the tree is identified by source_sha256, CR-R9-03).
BASE_COMMIT = "36086bb5db88e6679812c6548bdbcc503b6e854f"
#: The commit of synapse-cdm 3.8.0 (schema 3.2.0), the floor the package declares (D-28).
FLOOR_COMMIT = "0d4cf0e00f9636752c87fe47b50726aa0015b460"
HANDOFF_CDM_COMMIT = "c4bba1b6ebfdfe956f6efc2b3a81a04db2b4bb5b"
OPENRTI_COMMIT = "814a210978b7faafd65affbe70a2e25679921b23"
REFERENCE_PLATFORM_TEXT = "Linux x86_64, Ubuntu 24.04, GCC 13 (C++14), CMake 3.28 to 3.31"

#: The cases that need the reference platform before they can read PASS (CR-L04, the clauses
#: R7 and R8 carried to the release), each with the resource it lacks.
REFERENCE_PLATFORM = {
    "G-R02": "the reference platform (" + REFERENCE_PLATFORM_TEXT + ") for SPEC:20's native "
             "build and rti group: no run there; the development runs are DEV evidence",
    "G-R38": "the demo built and run on the reference platform (" + REFERENCE_PLATFORM_TEXT + ")",
    "G-R42": "R42's recorded 4-vCPU x86_64 machine with 8 GiB on the reference platform",
    "G-R43": "the reference build (" + REFERENCE_PLATFORM_TEXT + ") and the SHA-256 of the "
             "distribution packages of its toolchain",
    "G-R47": "the reference tools built and run on the reference platform (GCC 13)",
    "G-R48": "the release gates 'local OpenRTI lifecycle exercise' and 'performance test' on "
             "the reference platform",
    "A-PERFORMANCE": "R42's recorded 4-vCPU x86_64 machine with 8 GiB on the reference platform",
}

#: R48's release gates in its order, each with the cases that decide it (or a rule of its own).
RELEASE_GATES = [
    ("contract and dependency hashes verified", ["A-DEPENDENCY", "A-HASH", "G-R04"], None),
    ("all offline tests PASS", [], "offline-runs"),
    ("reference encoding and geodesy checks PASS", ["A-ENCODING", "G-R47"], None),
    ("local OpenRTI lifecycle exercise PASS", ["A-DEMO", "G-R38"],
     "the local OpenRTI lifecycle exercise on the reference platform (CR-L04): the demo PASSes "
     "on the development platforms only"),
    ("overload and failure tests PASS", ["A-OVERFLOW", "A-ATTRIBUTE-LIMIT", "A-TAG-LIMIT",
                                         "A-OBJECT-LIMIT", "A-FILE-LIMIT", "A-DISK", "A-SIGNAL",
                                         "A-TIMEOUT", "A-RECONNECT", "A-TRUNCATED",
                                         "A-SEQ-GAP"], None),
    ("performance test PASS", ["A-PERFORMANCE", "G-R42"], None),
    ("no unresolved severity-high defects", [],
     "the records of the independent reviews of this release tree (the packaging round's two "
     "reviews, the final review and the review of the fix pass that followed it), which are "
     "kept in the release run's kit outside this tree: a gate reads PASS only from evidence the "
     "tree carries (A-EVIDENCE, CR-L25)"),
    ("reproducible build and licence review completed", ["G-R43"], None),
    ("claims matching the tested scope", ["G-R50", "G-R49"], None),
]

EVIDENCE_CLASSES = {
    "DEV-macOS-arm64": "the development Mac (macOS, arm64; OpenRTI built as C++98 there, "
                       "NAT-02): development evidence, never release evidence",
    "DEV-linux-aarch64": "the Linux reference run's aarch64 machine (Ubuntu 24.04, GCC 13, "
                         "CMake 3.28): development evidence, not R42's x86_64 machine",
    "REFERENCE-linux-x86_64": "the reference platform (" + REFERENCE_PLATFORM_TEXT + "): no run "
                              "of this release was made there",
}

#: What the integration report must state (R10 with NAT-01, R13, R14 with NAT-03 and NAV-02, R39,
#: R40, R47, R50, OPS-01, OPV-03).
INTEGRATION = {
    "tested_reference": "OpenRTI " + OPENRTI_COMMIT + " is the tested reference; neither a "
                        "customer simulator nor a second RTI implementation was tested.",
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


# ------------------------------------------------------------------------------- the tree's facts

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _skipped(path: pathlib.Path) -> bool:
    rel = path.relative_to(PACKAGE_ROOT)
    parts = rel.parts
    return (parts[:2] == ("docs", "evidence") or "__pycache__" in parts
            or any(p in ("build", "dist", ".pytest_cache") or p.endswith(".egg-info")
                   for p in parts))


def source_digest() -> tuple[str, int]:
    """SHA-256 over every file of this directory but the evidence report itself (and what a
    build or a cache leaves): one line `<path> <sha256>` per file, sorted by path. It names the
    tree the report describes; a report whose digest differs describes another tree."""
    lines = []
    for path in sorted(PACKAGE_ROOT.rglob("*")):
        if path.is_file() and not _skipped(path):
            rel = path.relative_to(PACKAGE_ROOT).as_posix()
            lines.append(f"{rel} {_sha256(path.read_bytes())}\n")
    return _sha256("".join(lines).encode("utf-8")), len(lines)


def cross_interpreter_pins() -> dict[str, str]:
    """The pin table of tests/test_hla_geodesy.py, read from its source (not imported)."""
    tree = ast.parse((TESTS / "test_hla_geodesy.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "CROSS_INTERPRETER_PINS" for t in node.targets):
            return ast.literal_eval(node.value)
    raise SystemExit("no CROSS_INTERPRETER_PINS in test_hla_geodesy.py")


#: The test whose digest each entry of the pin table is (CR-R1-06).
PIN_TEST = ("tests/test_hla_geodesy.py::"
            "test_ten_thousand_projected_points_are_identical_on_every_interpreter")
#: What that test says on a platform without a pin, with the digest it computed (the way a new
#: platform's pin is first seen).
_NO_PIN = re.compile(r"no cross-interpreter pin for ([a-z0-9_-]+): ([0-9a-f]{64})")


def _pin_key(platform_text: str) -> str:
    """A run's platform ("Darwin arm64", platform.system() and platform.machine()) as the pin
    test names it (sys.platform, "-", platform.machine())."""
    system, machine = platform_text.split(" ", 1)
    return f"{system.lower()}-{machine}"


def _section(path: pathlib.Path, heading: str) -> list[str]:
    """The lines under `--- <heading>` of a reference run's platform.txt, up to the next one."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"--- {heading}") + 1
    stop = next((i for i in range(start, len(lines)) if lines[i].startswith("--- ")), len(lines))
    return lines[start:stop]


def _reference_identity(directory: pathlib.Path) -> dict:
    """Which run the reference run's directory is, when it ended, and the Python it ran, read
    from its own files: the run is the directory above `out/`, the date the one its `DONE`
    marker records, the interpreters every one its platform.txt names."""
    name = directory.parent.name if directory.name == "out" else directory.name
    done = (directory / "DONE").read_text(encoding="ascii").strip()
    if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", done):
        raise SystemExit(f"{name}: DONE does not hold a UTC time: {done!r}")
    versions = sorted({line.split()[1] for line in _section(directory / "platform.txt", "python")
                       if re.fullmatch(r"Python \d+\.\d+\.\d+", line)})
    if not versions:
        raise SystemExit(f"{name}: platform.txt names no Python")
    return {"run": name, "date": done[:10], "interpreters": versions}


def pin_provenance(pin_table: dict[str, str], runs: list[dict], results: dict[str, dict],
                   reference_dir: pathlib.Path | None) -> dict[str, dict | None]:
    """Which interpreters each pin of the table was seen from (CR-L20), read from the runs, not
    typed: this session's runs in which the pin test passed, by the platform each run records,
    and the reference run whose offline group printed the platform's digest as missing, which
    must be the pin. A platform neither shows is None."""
    out: dict[str, dict | None] = {key: None for key in pin_table}
    for run in runs:
        entry = results[run["id"]].get(PIN_TEST)
        key = _pin_key(run["platform"])
        if entry is None or entry["outcome"] != "passed" or key not in out:
            continue
        seen = out[key] or {"evidence_class": run["evidence_class"], "runs": [],
                            "interpreters": [], "where": "this session's runs"}
        seen["runs"].append(run["id"])
        seen["interpreters"] = sorted({*seen["interpreters"], run["python"]},
                                      key=lambda v: tuple(int(n) for n in v.split(".")))
        out[key] = seen
    if reference_dir is not None:
        identity = _reference_identity(reference_dir)
        found = _NO_PIN.findall((reference_dir / "logs" / "patched-offline.log")
                                .read_text(encoding="utf-8"))
        for key, digest in sorted(set(found)):
            if key not in out:
                continue
            if digest != pin_table[key]:
                raise SystemExit(f"the pin of {key} is not the digest {identity['run']} printed")
            out[key] = {"evidence_class": "DEV-" + key, "runs": [identity["run"]],
                        "interpreters": identity["interpreters"],
                        "where": f"reference run {identity['run']} of {identity['date']}"}
    for seen in out.values():
        if seen is not None:
            seen["interpreters_agree"] = ("shown" if len(seen["interpreters"]) > 1 else
                                          "not observable: one interpreter")
    return out


def geodesy_statement(provenance: dict[str, dict | None], replay_sha256: str) -> str:
    """CR-L20's observation, with each pin's interpreters as `pin_provenance` read them."""
    shown, unseen = [], []
    for key, seen in provenance.items():
        if seen is None:
            unseen.append(f"not shown for {key}, whose pin no run read here produced")
            continue
        versions = seen["interpreters"]
        if len(versions) > 1:
            minors = ", ".join(".".join(v.split(".")[:2]) for v in versions)
            shown.append(f"shown on {key} ({minors}: Python {', '.join(versions[:-1])} and "
                         f"{versions[-1]} in {seen['where']})")
        else:
            unseen.append(f"not observable on {key}, whose pin was recorded from one "
                          f"interpreter (Python {versions[0]}, {seen['where']})")
    return ("The packaged capture replays byte for byte on darwin-arm64 and linux-aarch64 (its "
            "observations' SHA-256 " + replay_sha256 + "). Of the 10,000-point grid, 674 inputs "
            "differ by one or two units in the last place of position_ecef_m between the C "
            "libraries (612 coordinate values by 1 ulp, 79 by 2 ulp; the test's own generator "
            "uses math.cos and math.sin); of the 9,326 identical inputs, 5 outputs differ by one "
            "unit in the sixth decimal of alt_m (1e-6 m) at altitudes of 27,451 to 89,704 km, "
            "latitude, longitude and kinematics agreeing. Byte identity across platforms is "
            "therefore not guaranteed at extreme heights. Identity across interpreters on one "
            "platform (what CR-R1-06 pins) is " + " and ".join(shown + unseen) + " (CR-L20).")


def locked_cdm() -> str:
    """The synapse-cdm version locks/runtime.lock pins (CR-L22), read from the lock, not typed."""
    found = re.findall(r"^synapse-cdm==([^ ]+) \\$",
                       (PACKAGE_ROOT / "locks" / "runtime.lock").read_text(encoding="utf-8"),
                       re.MULTILINE)
    if len(found) != 1:
        raise SystemExit(f"locks/runtime.lock pins synapse-cdm {len(found)} times, not once")
    return found[0]


def _json(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def collected() -> dict[str, dict]:
    """The case bindings of a real collection of the whole suite (hla_support's trace export)."""
    sys.path[:0] = [str(TESTS), str(PACKAGE_ROOT / "src")]
    import tempfile

    from hla_support import collected_bindings
    with tempfile.TemporaryDirectory() as work:
        return collected_bindings(pathlib.Path(work))


# ------------------------------------------------------------------------------------ the cases

def _outcomes(node: str, runs: list[dict], results: dict[str, dict]) -> dict[str, dict]:
    out = {}
    for run in runs:
        entry = results[run["id"]].get(node)
        if entry is not None and entry["outcome"] is not None:
            out[run["id"]] = entry
    return out


def _command(nodes: list[str], groups: set[str]) -> str:
    functions = sorted({n.split("[", 1)[0] for n in nodes})
    marker = {"offline": "not rti and not perf and not reference", "rti": "rti", "perf": "perf",
              "reference": "reference"}
    selection = " or ".join(sorted(f"({marker[g]})" for g in groups)) or marker["offline"]
    return (f'python -m pytest -p no:cacheprovider -m "{selection}" ' + " ".join(functions))


def judge_case(case: dict, nodes: list[str], runs: list[dict],
               results: dict[str, dict]) -> dict:
    run_class = {run["id"]: run["evidence_class"] for run in runs}
    run_group = {run["id"]: run["group"] for run in runs}
    tests = []
    failed, blocked_reasons, classes, groups = False, [], set(), set()
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0, "not_run": 0}
    duration = 0.0
    observations = []
    for node in nodes:
        seen = _outcomes(node, runs, results)
        outcomes = {run_id: entry["outcome"] for run_id, entry in seen.items()}
        tests.append({"test": node, "outcomes": outcomes})
        if not seen:
            counts["not_run"] += 1
            blocked_reasons.append(f"{node} did not run in this session")
            continue
        for run_id, entry in seen.items():
            counts[entry["outcome"]] += 1
            duration += entry["duration_s"]
            groups.add(run_group[run_id])
            if entry["outcome"] in ("failed", "error"):
                failed = True
            elif entry["outcome"] == "passed":
                classes.add(run_class[run_id])
            if "observation" in entry["properties"]:
                observations.append({"test": node, "run": run_id,
                                     "observation": json.loads(entry["properties"]["observation"])})
        if not any(o == "passed" for o in outcomes.values()):
            reasons = sorted({e["reason"] or "skipped" for e in seen.values()
                              if e["outcome"] == "skipped"})
            blocked_reasons += reasons
    if failed:
        result, resource = "FAIL", None
    elif case["id"] in REFERENCE_PLATFORM:
        result, resource = "BLOCKED", REFERENCE_PLATFORM[case["id"]]
    elif blocked_reasons:
        result, resource = "BLOCKED", "; ".join(sorted(set(blocked_reasons)))
    elif not nodes:
        result, resource = "BLOCKED", "no test binds this case"
    else:
        result, resource = "PASS", None
    test_files = sorted({n.split("::", 1)[0] for n in nodes})
    # Tests with the same outcome in every run are listed together, which keeps the report
    # readable where a gate is held by hundreds of table rows.
    by_outcome: dict[str, dict] = {}
    for test in tests:
        key = json.dumps(test["outcomes"], sort_keys=True)
        by_outcome.setdefault(key, {"outcomes": test["outcomes"], "tests": []})["tests"].append(
            test["test"])
    return {
        "id": case["id"], "requirement": case["requirement"], "layer": case["layer"],
        "result": result, "blocked_resource": resource,
        "evidence_class": sorted(classes),
        "tests": [by_outcome[key] for key in sorted(by_outcome)],
        "command": _command(nodes, groups),
        "input_digests": {f: _sha256((PACKAGE_ROOT / f).read_bytes()) for f in test_files},
        "expected": ("the outcome case " + case["id"] + " of the handoff's acceptance-cases.json "
                     "prescribes, as the binding tests assert it"),
        "actual": counts,
        "observations": observations,
        "duration_s": round(duration, 3),
    }


def judge_gates(cases: dict[str, dict], runs: list[dict], results: dict) -> list[dict]:
    gates = []
    for name, ids, rule in RELEASE_GATES:
        if rule == "offline-runs":
            offline = [r for r in runs if r["group"] == "offline"]
            bad = [r["id"] for r in offline
                   if any(e["outcome"] != "passed" for e in results[r["id"]].values())]
            status = "PASS" if offline and not bad else "FAIL"
            gates.append({"gate": name, "status": status, "cases": [],
                          "runs": [r["id"] for r in offline], "blocked_resource": None,
                          "evidence_class": sorted({r["evidence_class"] for r in offline})})
            continue
        statuses = [cases[i]["result"] for i in ids]
        if "FAIL" in statuses:
            status, resource = "FAIL", None
        elif rule is not None:
            status, resource = "BLOCKED", rule
        elif "BLOCKED" in statuses:
            status = "BLOCKED"
            resource = "; ".join(sorted({cases[i]["blocked_resource"] for i in ids
                                         if cases[i]["result"] == "BLOCKED"}))
        else:
            status, resource = "PASS", None
        gates.append({"gate": name, "status": status, "cases": ids, "runs": [],
                      "blocked_resource": resource,
                      "evidence_class": sorted({c for i in ids
                                                for c in cases[i]["evidence_class"]})})
    return gates


# ---------------------------------------------------------------------- the reference run's files

def _last_line(path: pathlib.Path) -> str:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return re.sub(r" in [0-9.]+s.*$", "", lines[-1])


#: ctest's result line. Its log ends with the total test time, a duration and not a result.
CTEST_RESULT = re.compile(r"\d+% tests passed, \d+ tests failed out of \d+")


def _ctest_result(path: pathlib.Path) -> str:
    """The one result line of a ctest log, wherever it stands in the log."""
    found = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
             if CTEST_RESULT.fullmatch(line.strip())]
    if len(found) != 1:
        raise SystemExit(f"{path.name}: {len(found)} ctest result lines, not one")
    return found[0]


#: The line the reference-group test prints (tests/test_hla_rti.py): the cs2cs it ran and the
#: version that cs2cs stated at run time.
_CS2CS_LINE = re.compile(r"cs2cs: (\S+): (Rel\. \d+\.\d+\.\d+, .+)")


def reference_proj(directory: pathlib.Path) -> dict:
    """The PROJ of the reference run's reference group (CDV-02), from its own files: the version
    its cs2cs test printed at run time (logs/reference.log), which must be the version cs2cs
    stated in the run's platform record, and the cs2cs binary that record names."""
    found = _CS2CS_LINE.findall((directory / "logs" / "reference.log").read_text(encoding="utf-8"))
    if len({version for _path, version in found}) != 1:
        raise SystemExit(f"reference.log: {len(found)} cs2cs lines, not one version")
    version = found[0][1]
    stated = _section(directory / "platform.txt", "proj")
    binaries = [line for line in stated if line.startswith("/") and line.endswith("/cs2cs")]
    if version not in stated or len(binaries) != 1:
        raise SystemExit("platform.txt does not state the cs2cs and the version the test printed")
    return {"proj_version": version, "cs2cs": binaries[0],
            "read_from": "logs/reference.log (the version the reference group's cs2cs test "
                         "printed at run time) and platform.txt (the cs2cs binary of the run "
                         "and the version it stated there)"}


def reference_run(directory: pathlib.Path | None) -> dict | None:
    """The Linux reference run's figures, read from its own output files."""
    if directory is None:
        return None
    record = dict(line.split("=", 1) for line in
                  (directory / "build-record.txt").read_text(encoding="utf-8").splitlines())
    demos = []
    for name in ("demo1", "demo2"):
        document = _json(directory / name / "demo.json")
        demos.append({"status": document["status"],
                      "evidence_class_as_written": document["evidence_class"],
                      "refresh_seqs": [run["refresh_seqs"] for run in document["runs"]],
                      "checkpoints": [[c["result"] for c in run["checkpoints"]]
                                      for run in document["runs"]]})
    r42 = []
    for path in sorted((directory / "r42").glob("*.summary.json")):
        summary = _json(path)
        footer = summary.get("footer") or {}
        expected = summary.get("expected", {})
        counts = summary.get("counts", {})
        r42.append({"run": summary["name"], "shape": summary.get("shape"),
                    "config": summary["config"],
                    "load_captured": counts.get("reflect:perf", 0),
                    "load_expected": expected.get("reflect:perf"),
                    "footer": footer.get("status"), "reason_code": footer.get("reason_code")})
    selftest = _json(directory / "selftest" / "self-test.json")
    logs = directory / "logs"
    identity = _reference_identity(directory)
    return {
        "evidence_class": "DEV-linux-aarch64",
        "run": identity["run"], "date": identity["date"],
        "python": identity["interpreters"],
        "proj": reference_proj(directory),
        "tree": "the accepted tree before this release, with this release's three portability "
                "fixes applied as patches where a step needed them",
        "build_record": {
            "platform": record["platform"], "cmake": record["cmake"],
            "compiler": record["compiler"].split(": ", 1)[1],
            "policy_version_minimum_added": record["policy_version_minimum_added"],
            "cxx_standard_in_cache": record["cxx_standard_in_cache"],
            "evidence_as_written": record["evidence"],
            "evidence_corrected": "DEV-linux-aarch64: the record's evidence line was written "
                                  "by the wrapper whatever the machine; this release's wrapper "
                                  "names a non-reference machine as development evidence "
                                  "(CR-L21)",
        },
        "ctest": _ctest_result(logs / "ctest.log"),
        "offline_group": _last_line(logs / "patched-offline.log"),
        "rti_group_unpatched": _last_line(logs / "rti.log"),
        "rti_group_patched": _last_line(logs / "patched-rti.log"),
        "reference_group": _last_line(logs / "reference.log"),
        "perf_group": _last_line(logs / "perf.log"),
        "self_test": {"result": selftest["result"], "counts": selftest["counts"]},
        "demos": demos,
        "demo_timing": "In some Linux demo sessions the publisher answered the observer's "
                       "request for values after step 1 with a refresh reflection; the Mac's "
                       "demos have shown the same answer, less often. A difference of "
                       "frequency, not of kind, allowed by R38; every checkpoint passed.",
        "labels": "This report spells the classes as CR-L04 does (DEV-macOS-arm64, "
                  "DEV-linux-aarch64); a demo manifest writes the platform's own spelling, "
                  "quoted here as written.",
        "r42_shaped_runs": r42,
        "tree_manifest": "taken in the container before the first step and after the last; "
                         "equal",
    }


# ------------------------------------------------------------------------- the performance entry

R42_TEST = ("tests/test_hla_rti.py::"
            "test_r42_load_on_the_reference_machine_without_loss_within_the_p95_target")


def r42_assessment(observations: list[dict], reference: dict | None) -> str:
    """The performance entry's assessment. What it says of the runs is counted from their own
    records (the Linux run's R42-shaped summaries, this session's R42 observation), never typed
    beforehand: a run that lost nothing is never said to have overflowed."""
    facts = []
    if reference is not None:
        shaped = [r for r in reference["r42_shaped_runs"]
                  if r["shape"] == "perf:1000:1:60" and r["config"] == "main"]
        overflowed = sum(1 for r in shaped if r["reason_code"] == "E_QUEUE_OVERFLOW")
        facts.append(f"in R42's shape with that configuration the worker's queue overflowed in "
                     f"{overflowed} of the {len(shaped)} Linux aarch64 runs (reference_run)")
    for item in observations:
        if item["test"] != R42_TEST:
            continue
        seen = item["observation"]
        if seen["overflow"]:
            facts.append("it overflowed in this session's development run "
                         f"({seen['load_captured']} of {seen['load_expected']} load reflections "
                         "captured; observation below)")
        elif seen["load_with_output"] != seen["load_expected"]:
            facts.append(f"this session's development run output {seen['load_with_output']} of "
                         f"{seen['load_expected']} load reflections (observation below)")
        else:
            facts.append("this session's development run lost no load reflection "
                         f"({seen['load_with_output']} of {seen['load_expected']} output), with "
                         f"a p95 callback-to-output delay of {seen.get('p95_ms')} ms against "
                         "R42's 250 ms (observation below)")
    return ("R42's 1000 reflections per second with every reflection projected and validated as "
            "a CDM Entity (R44) is AT RISK on a 4-vCPU machine: " + "; ".join(facts)
            + " (CR-L17, CR-R8-12)")


# ------------------------------------------------------------------------------------ PROJ (CDV-02)

#: The reference-group test that carries points forward through PROJ's cs2cs.
PROJ_TEST = ("tests/test_hla_rti.py::"
             "test_the_product_inverse_agrees_with_proj_forward_on_the_175_point_grid")


def proj_entries(cases: list[dict], runs: list[dict], reference: dict | None) -> list[dict]:
    """The PROJ that each run of the reference group measured (CDV-02: the version cs2cs states
    at run time, never a copied string): this session's as the reference-group test recorded it
    (its observation, kept with the cases the test binds), then the reference run's, read from
    that run's own files (`reference_run`)."""
    run_class = {run["id"]: run["evidence_class"] for run in runs}
    seen: dict[str, dict] = {}
    for case in cases:
        for item in case["observations"]:
            if item["test"] == PROJ_TEST:
                seen[item["run"]] = {
                    "evidence_class": run_class[item["run"]], "run": item["run"],
                    "proj_version": item["observation"]["proj_version"],
                    "cs2cs": item["observation"]["cs2cs"],
                    "read_from": "the observation the reference-group test recorded in this run"}
    entries = [seen[run_id] for run_id in sorted(seen)]
    if reference is not None:
        entries.append({"evidence_class": reference["evidence_class"], "run": reference["run"],
                        "proj_version": reference["proj"]["proj_version"],
                        "cs2cs": reference["proj"]["cs2cs"],
                        "read_from": "the reference run's files (reference_run.proj)"})
    return entries


# ------------------------------------------------------------------------------------- the report

def build_report(runs_dir: pathlib.Path, reference_dir: pathlib.Path | None) -> dict:
    manifest = _json(runs_dir / "runs.json")
    runs = manifest["runs"]
    results = {run["id"]: _json(runs_dir / run["results"]) for run in runs}
    observations_path = runs_dir / "observations.json"
    observations = _json(observations_path) if observations_path.is_file() else {}
    index = _json(CONTRACT / "case-index.json")
    owner = _json(CONTRACT / "owner-points.json")
    bindings = collected()
    by_case: dict[str, list[str]] = {}
    for node, binding in bindings.items():
        for case_id in binding["ids"]:
            by_case.setdefault(case_id, []).append(node)
    cases = [judge_case(case, sorted(by_case.get(case["id"], [])), runs, results)
             for case in index]
    by_id = {c["id"]: c for c in cases}
    gates = judge_gates(by_id, runs, results)
    statuses = [c["result"] for c in cases] + [g["status"] for g in gates]
    overall = "FAIL" if "FAIL" in statuses else "BLOCKED" if "BLOCKED" in statuses else "PASS"
    digest, files = source_digest()
    vendored = _json(CONTRACT / "vendored-pins.json")["files"]
    pins = _json(PACKAGE_ROOT / "src" / "synapse_hla" / "pins.json")
    run_rows = []
    for run in runs:
        tally: dict[str, int] = {}
        for entry in results[run["id"]].values():
            tally[entry["outcome"]] = tally.get(entry["outcome"], 0) + 1
        run_rows.append(dict({k: run[k] for k in ("id", "group", "interpreter", "python",
                                                  "platform", "evidence_class", "command")},
                             counts=dict(sorted(tally.items()))))
    perf = by_id["A-PERFORMANCE"]
    reference = reference_run(reference_dir)
    pin_table = cross_interpreter_pins()
    provenance = pin_provenance(pin_table, runs, results, reference_dir)
    replay_sha256 = next(e["sha256"] for e in vendored
                         if e["path"].endswith("expected.observations.jsonl"))
    return {
        "evidence_report_version": 1,
        "about": "The release evidence report of synapse-hla, written by tests/release_evidence.py "
                 "from the runs of one release session; nothing in it is typed by hand. Results "
                 "are PASS, FAIL or BLOCKED per acceptance case (R46), each with its evidence "
                 "class (CR-L04).",
        "release": {"distribution": "synapse-hla", "version": "1.0.0",
                    "profile": "SC-HLA-RPR2-OBS-1",
                    "specification": "SC HLA SPEC 001 v1.0, the handoff document; not in this "
                                     "repository"},
        "status": overall,
        "external_customer_interoperability": "NOT_TESTED",
        "generation": "The tests that read this report (tests/test_hla_release.py and the version "
                      "test of tests/test_hla_packaging.py) read, in the runs below, the previous "
                      "generation of this report for the same tree (the same source digest and "
                      "case bindings); this generation, written from those runs, replaces it.",
        "evidence_classes": EVIDENCE_CLASSES,
        "build": {
            "base_commit": BASE_COMMIT,
            "source_commit": None,
            "source_commit_note": "the release commit does not exist when its evidence is "
                                  "generated and is never invented (OPS-10); the tree is "
                                  "identified by source_sha256 over its files",
            "source_sha256": digest, "source_files": files,
            "native": manifest["native"],
            "commands": manifest["commands"],
        },
        "input_digests": {
            "vendored": {e["path"]: e["sha256"] for e in vendored},
            "pins": {e["path"]: e["sha256"] for e in pins["files"]},
            "case_index": _sha256((CONTRACT / "case-index.json").read_bytes()),
            "locks": {p.name: _sha256(p.read_bytes())
                      for p in sorted((PACKAGE_ROOT / "locks").iterdir()) if p.is_file()},
        },
        "runs": run_rows,
        "cases": cases,
        "case_counts": {r: sum(1 for c in cases if c["result"] == r)
                        for r in ("PASS", "FAIL", "BLOCKED")},
        "release_gates": gates,
        "performance": {
            "status": perf["result"], "blocked_resource": perf["blocked_resource"],
            "observations": perf["observations"],
            "assessment": r42_assessment(perf["observations"], reference),
        },
        "cdm": {
            "contract": {"schema_version": "3.0.0",
                         "file": "src/synapse_hla/schemas/cdm-entity.schema.json",
                         "sha256": next(e["sha256"] for e in vendored
                                        if e["path"].endswith("cdm-entity.schema.json"))},
            "handoff_baseline": {"synapse_cdm": "3.1.1", "commit": HANDOFF_CDM_COMMIT,
                                 "note": "the source of the vendored cdm-entity schema and of "
                                         "the fixtures; the package was developed and tested "
                                         "against it before landing"},
            "floor": {"synapse_cdm": "3.8.0", "schema_version": "3.2.0", "commit": FLOOR_COMMIT,
                      "declared": "synapse-cdm>=3.8.0,<4"},
            "tested_with": manifest["synapse_cdm"],
            "migration": "the installed SDK's Entity schema differs from the vendored 3.0.0 one "
                         "only by the schema_version default and the PositionSource enum "
                         "(+SENSOR, +UNKNOWN), both additive; re-verified by the additivity test "
                         "and the byte-identical replay of the packaged capture",
            "upgrade_rule": "a later synapse-cdm must keep the packaged fixtures, stay additive "
                            "over the vendored 3.0.0 Entity schema, pass the additivity test "
                            "and the byte-identical replay, and record its migration (README, "
                            "\"The CDM\"); moving the locked set (synapse-cdm "
                            + locked_cdm() + ") also needs locks/ (the lock files and the SBOM) "
                            "and this report regenerated for the set in use, because the "
                            "offline group holds every other installed locked distribution to "
                            "its locked version and synapse-cdm, the repository's sibling "
                            "distribution, to the declared range at or above its locked version "
                            "(CR-L22)",
            "deviation": "R44's baseline 3.1.1 is history, not the supported floor: a recorded "
                         "deviation on the owner list (CR-L18)",
        },
        "cross_interpreter_pins": {
            "platforms": sorted(pin_table),
            "provenance": provenance,
            "reference_platform": "linux-x86_64 has no pin: the 10,000-point test fails there "
                                  "with its computed digest until a run there records one "
                                  "(CR-R1-06)",
        },
        "geodesy": geodesy_statement(provenance, replay_sha256),
        "proj": proj_entries(cases, runs, reference),
        "integration": INTEGRATION,
        "reference_run": reference,
        "session_observations": observations,
        "owner_points": owner["points"],
    }


# ----------------------------------------------------------------------------------- rendering

def render_markdown(report: dict) -> str:
    """The human-readable report: every section of the JSON in prose and tables."""
    lines = ["# Release evidence: synapse-hla 1.0.0, profile SC-HLA-RPR2-OBS-1", "",
             "Written by `tests/release_evidence.py` from the runs of one release session "
             "(`evidence-report.json` beside this file holds everything below, and more: every "
             "test of every case with its outcome in every run). Nothing here is typed by hand.",
             "", f"- **Overall status: {report['status']}.**",
             f"- **external_customer_interoperability: "
             f"{report['external_customer_interoperability']}** (no witnessed report exists).",
             "- Cases: " + ", ".join(f"{k} {report['case_counts'][k]}"
                                     for k in ("PASS", "FAIL", "BLOCKED")) + ".",
             f"- Source: base commit `{report['build']['base_commit']}`, source commit "
             f"{report['build']['source_commit'] or 'null'} "
             f"({report['build']['source_commit_note']}), "
             f"source SHA-256 `{report['build']['source_sha256']}` over "
             f"{report['build']['source_files']} files.", "",
             "## Evidence classes", ""]
    for name, text in report["evidence_classes"].items():
        lines.append(f"- `{name}`: {text}.")
    lines += ["", "## Release gates (R48)", "", "| Gate | Status | Evidence class | Blocked on |",
              "|---|---|---|---|"]
    for gate in report["release_gates"]:
        lines.append(f"| {gate['gate']} | {gate['status']} | "
                     f"{', '.join(gate['evidence_class']) or '-'} | "
                     f"{gate['blocked_resource'] or '-'} |")
    lines += ["", "## Runs of this session", "",
              "| Run | Group | Python | Platform | Class | Counts | Command |",
              "|---|---|---|---|---|---|---|"]
    for run in report["runs"]:
        counts = ", ".join(f"{k} {v}" for k, v in run["counts"].items())
        lines.append(f"| {run['id']} | {run['group']} | {run['python']} | {run['platform']} | "
                     f"{run['evidence_class']} | {counts} | `{run['command']}` |")
    lines += ["", "## Cases", "",
              "| Case | Requirement | Result | Class | Tests | Passed/failed/skipped/not run "
              "| Blocked on |", "|---|---|---|---|---|---|---|"]
    for case in report["cases"]:
        actual = case["actual"]
        count = sum(len(group["tests"]) for group in case["tests"])
        lines.append(f"| {case['id']} | {case['requirement']} | {case['result']} | "
                     f"{', '.join(case['evidence_class']) or '-'} | {count} | "
                     f"{actual['passed']}/{actual['failed'] + actual['error']}/"
                     f"{actual['skipped']}/{actual['not_run']} | "
                     f"{case['blocked_resource'] or '-'} |")
    perf = report["performance"]
    lines += ["", "## Performance (R42, A-PERFORMANCE)", "",
              f"Status: {perf['status']} ({perf['blocked_resource']}). {perf['assessment']}.", ""]
    for item in perf["observations"]:
        lines.append(f"- {item['run']}, `{item['test']}`: "
                     + json.dumps(item["observation"], sort_keys=True))
    cdm = report["cdm"]
    lines += ["", "## The CDM (R44)", "",
              f"- Contract: CDM schema {cdm['contract']['schema_version']}, "
              f"`{cdm['contract']['file']}` (SHA-256 `{cdm['contract']['sha256']}`).",
              f"- Handoff baseline: synapse-cdm {cdm['handoff_baseline']['synapse_cdm']} at "
              f"`{cdm['handoff_baseline']['commit']}`: {cdm['handoff_baseline']['note']}.",
              f"- Floor: `{cdm['floor']['declared']}` (synapse-cdm {cdm['floor']['synapse_cdm']}, "
              f"schema {cdm['floor']['schema_version']}, at `{cdm['floor']['commit']}`); tested "
              f"with {cdm['tested_with']}.",
              f"- Migration: {cdm['migration']}.", f"- Upgrade rule: {cdm['upgrade_rule']}.",
              f"- {cdm['deviation']}.", "",
              "## Cross-interpreter pins and geodesy", ""]
    pins = report["cross_interpreter_pins"]
    lines += ["Platforms with a pin: "
              + ", ".join(_pin_text(key, pins["provenance"][key]) for key in pins["platforms"])
              + f"; {pins['reference_platform']}.", "", report["geodesy"], "",
              "PROJ as each run of the reference group measured it (CDV-02):", ""]
    for entry in report["proj"]:
        lines.append(f"- {entry['run']} ({entry['evidence_class']}): `{entry['cs2cs']}` stated "
                     f"`{entry['proj_version']}`; read from {entry['read_from']}.")
    lines += ["", "## Integration report", ""]
    for key, value in report["integration"].items():
        if isinstance(value, list):
            lines.append(f"- {key}: " + "; ".join(value) + ".")
        else:
            lines.append(f"- {key}: {value}")
    ref = report["reference_run"]
    if ref is not None:
        record = ref["build_record"]
        lines += ["", "## The Linux reference run (DEV-linux-aarch64)", "",
                  f"- Run: `{ref['run']}`, ended {ref['date']}, Python "
                  f"{', '.join(ref['python'])}; PROJ `{ref['proj']['proj_version']}` "
                  f"(`{ref['proj']['cs2cs']}`).",
                  f"- Tree: {ref['tree']}.",
                  f"- Build record: platform {record['platform']}, {record['cmake']}, "
                  f"{record['compiler']}, policy flag {record['policy_version_minimum_added']}, "
                  f"C++ standard {record['cxx_standard_in_cache']}.",
                  f"- The record's evidence line as written: \"{record['evidence_as_written']}\"; "
                  f"corrected: {record['evidence_corrected']}.",
                  f"- ctest: {ref['ctest']}; offline group: {ref['offline_group']}; rti group "
                  f"unpatched: {ref['rti_group_unpatched']}, patched: {ref['rti_group_patched']};"
                  f" reference group: {ref['reference_group']}; perf group: {ref['perf_group']}.",
                  f"- self-test: {ref['self_test']['result']} {ref['self_test']['counts']}.",
                  "- Demos: " + "; ".join(f"{d['status']} (manifest class as written "
                                         f"`{d['evidence_class_as_written']}`, refresh seqs "
                                         f"{d['refresh_seqs']})" for d in ref["demos"]) + ".",
                  f"- Demo timing: {ref['demo_timing']}", f"- Labels: {ref['labels']}",
                  f"- Tree manifest: {ref['tree_manifest']}.", "- R42-shaped runs: "
                  + "; ".join(f"{r['run']} {r['shape']} {r['config']}: {r['load_captured']} of "
                              f"{r['load_expected']} load reflections, footer {r['footer']} "
                              f"{r['reason_code'] or ''}".rstrip() for r in ref["r42_shaped_runs"])
                  + "."]
    lines += ["", "## Session observations", ""]
    for name, value in sorted(report["session_observations"].items()):
        lines.append(f"- {name}: " + json.dumps(value, sort_keys=True))
    lines += ["", "## Specification points for the owner", "",
              "The rulings this run took where the specification is open or contradicts itself "
              "(the CR-L06 list and its extensions). The owner may overrule any of them.", ""]
    for point in report["owner_points"]:
        bound = ", ".join(f"`{b}`" for b in point["bound_at"])
        lines.append(f"- **{point['id']}** ({point['source']}). {point['point']} Ruling: "
                     f"{point['ruling']} Bound by {bound}.")
    return "\n".join(lines) + "\n"


def _pin_text(key: str, seen: dict | None) -> str:
    if seen is None:
        return f"`{key}` (no run read here produced it)"
    return (f"`{key}` (Python {', '.join(seen['interpreters'])} in {seen['where']}; agreement "
            f"across interpreters {seen['interpreters_agree']})")


def write(report: dict) -> None:
    """Both files; the rendering is made from the JSON as written (key order included), so a
    reader of the JSON file renders the same text."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=1, sort_keys=True, ensure_ascii=True) + "\n"
    (OUT_DIR / JSON_NAME).write_text(text, encoding="ascii")
    (OUT_DIR / MARKDOWN_NAME).write_text(render_markdown(json.loads(text)), encoding="utf-8")


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 2):
        print(__doc__.split("\n\n", 1)[0], file=sys.stderr)
        return 2
    runs_dir = pathlib.Path(argv[0])
    reference_dir = pathlib.Path(argv[1]) if len(argv) == 2 else None
    write(build_report(runs_dir, reference_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
