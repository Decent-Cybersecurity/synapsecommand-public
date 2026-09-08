"""Evidence records — the machine-generated basis for every compatibility claim (§31–§36).

WHAT A CLAIM WAS BEFORE THIS MODULE
------------------------------------
An adapter has declared its maturity rung and its claim status since P1, and the conformance
suite has computed an eligible rung since P2. Both are true statements and neither is EVIDENCE:
one is what the adapter says about itself, the other is what a tool said on a machine nobody
can name, on a tree nobody recorded, at a moment nobody wrote down. A third party reading
`manifests/adsb.json` cannot tell whether `maturity: L4` was earned or typed.

An evidence record is that missing thing: one JSON document per adapter carrying the manifest it
measured, the commit it measured at, every version axis in force, the suite's own report
verbatim, the loss report, and a digest of every fixture file the run read. `verify` re-derives
all of it and reports what differs. §36's reproducibility is therefore a COMMAND rather than a
promise, and a claim that cannot be reproduced is visible as a diff rather than as a rumour.

WHY `hashlib` IS IMPORTED HERE AND NOWHERE ELSE UNDER THIS PACKAGE — M's ruling, 2026-09-08
--------------------------------------------------------------------------------------------
`tests/test_cdm_boundary.py` forbids `hashlib` in every module of this package, for a reason that
is about SIGNING: "the `integrity` field is designed, not implemented … Signing belongs to the
ledger, which holds the keys and is audited; a signature computed inside a translator is neither".
That reason is untouched. SHA-256 here is CONTENT IDENTIFICATION — "did this file change?" — and
carries no key, authenticates nothing and proves nothing about who produced it. The ruling names
the permitted uses (fixture hashes, artifact hashes, evidence-record integrity identifiers,
deterministic content addressing) and leaves every forbidden one forbidden (encryption, key
derivation, authentication, signatures, MACs, password hashing, token generation, any security
protocol primitive). The boundary gate is narrowed to THIS MODULE BY NAME and still fails for
every other module in the package, which is what keeps the allowance from becoming a hole.

WHY THE RECORD IS NOT TRACKED (F4.1, M's pre-ruled default 1)
--------------------------------------------------------------
`evidence/` is in `.gitignore`. A record names the commit it measured, so a tracked record is
either stale the moment it is committed or committed twice — and a fixture digest changes on
every fixture edit, so tracking it would put a mechanical diff in every fixture round. CI
generates the set on every run and uploads it as an artefact; the release round attaches it to
the GitHub Release, which is the point at which `evidence.available` becomes true for a consumer
who cannot run this package. It is false until then, and M ruled that too.
"""
from __future__ import annotations

import argparse
import copy
import datetime as _dt
import hashlib
import json
import pathlib
import subprocess
import sys
import sysconfig
import time
from typing import Any, Iterable

from pydantic import ConfigDict, field_validator

from synapse_cdm import harness, suite, times, version
from synapse_cdm.adapter import Adapter, fixture_root, load_adapter, packaged_fixtures
from synapse_cdm.manifest import Strict
from synapse_cdm.manifests import manifest, shipped
from synapse_cdm.version import (ADAPTER_API_VERSION, EVIDENCE_SCHEMA_VERSION,
                                 MANIFEST_SCHEMA_VERSION, PACKAGE_VERSION, SC_OES_VERSION,
                                 SCHEMA_VERSION)

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2

#: `evidence/<adapter>/<adapter-version>/evidence.json` (§31). The adapter VERSION is a path
#: segment and not a filename suffix, so a consumer can list the versions of one adapter's
#: evidence with a directory listing rather than by parsing names.
RECORD_NAME = "evidence.json"

#: The fields `verify` does not compare, and why each one (§36). Nothing else is masked: a
#: difference anywhere else is a difference in what was measured, which is the whole point.
#:
#: THE RULE IS "A MEASURED DURATION IS NOT A MEASUREMENT OF THE TREE", and the list is the
#: enumeration of where one appears rather than a pattern. A pattern (`*seconds`, `*duration*`)
#: would mask a future field nobody had looked at, which is the shape of mask that makes a
#: reproducibility check stop meaning anything.
#:
#:   generated_at          — the instant. Two runs are never at one instant.
#:   test_run.duration_s   — wall time for the whole run. Two runs of one deterministic suite
#:                           differ by scheduling.
#:   conformance.checks.H.details.refusals[].seconds
#:                         — how long ONE malformed payload took to be refused (`suite.py:357`).
#:                           FOUND BY THIS ROUND'S OWN §36 PROOF rather than reasoned about: two
#:                           generations from one fresh clone differed in exactly one field, and
#:                           it was `stanag4676`'s second refusal reading 0.0 and then 0.0001.
#:                           It is a real measurement and it belongs in the record — check H's
#:                           whole point is a five-second bound — but it measures THIS MACHINE AT
#:                           THIS MOMENT, which is what `test_run.duration_s` is masked for.
#:   source_commit         — ONLY when the tree is dirty, and `verify` says which. A dirty tree
#:                           has no commit that describes it, so comparing the field would be
#:                           comparing a label to a thing it does not name.
MASKED = ("generated_at", "test_run.duration_s",
          "conformance.checks.H.details.refusals[].seconds")

#: What a masked field is replaced BY. A sentinel and not a deletion, because two records where
#: one has the field and the other does not are still different records, and `compare` has to be
#: able to say so.
MASK_SENTINEL = "<masked>"


# --------------------------------------------------------------------------- §33: provenance

#: §33's identifier. Spelled `schema_id` and not `schema` on THIS REPOSITORY'S OWN PRECEDENT:
#: `manifests.py:37` carries §13's `schema:` key under the same name, for the same reason —
#: `schema` shadows an attribute of `pydantic.BaseModel` and a model cannot declare it. One
#: spelling for one idea across two publications beats matching two specifications' prose and
#: making a consumer learn which document each key came from.
PROVENANCE_SCHEMA_ID = "synapse.fixture-provenance/v1"

#: Pre-ruled default 5, as a constant rather than as a literal at four sites. A reading that
#: refutes either of these is a STOP for the round that finds it, not a value to widen.
SYNTHETIC_REQUIRED = True
CLASSIFICATION_REQUIRED = "PUBLIC"


class FixtureOrigin(Strict):
    """One fixture's provenance row (§33).

    `origin` is PROSE and required, and that is deliberate in a module whose other new field
    exists precisely to stop prose being machine-read: nothing computes on it. It is the
    sentence a human auditor needs — which document, which generator, which worked example —
    and the machine-readable claims beside it are the four booleans and the classification.
    """

    file: str
    synthetic: bool
    classification: str
    operational_data: bool
    personal_data: bool
    origin: str
    standard_ref: str | None = None

    @field_validator("origin")
    @classmethod
    def _an_origin_is_a_sentence(cls, value: str) -> str:
        if len(value.strip()) < 20:
            raise ValueError(f"origin {value!r} is too short to be an origin. §33 asks where a "
                             "fixture came from; a word is not an answer and 'unknown' has its "
                             "own spelling")
        return value


class FixtureProvenance(Strict):
    """One directory's `PROVENANCE.json`."""

    schema_id: str
    directory: str
    fixtures: list[FixtureOrigin]

    @field_validator("schema_id")
    @classmethod
    def _the_known_grammar(cls, value: str) -> str:
        if value != PROVENANCE_SCHEMA_ID:
            raise ValueError(f"schema_id {value!r} is not {PROVENANCE_SCHEMA_ID!r}; a record "
                             "whose grammar this package does not know is not one it may read")
        return value


def provenance_path(directory: pathlib.Path) -> pathlib.Path:
    return directory / harness.PROVENANCE_FILE


def read_provenance(directory: pathlib.Path) -> FixtureProvenance:
    """The directory's record, validated. Raises `FileNotFoundError` if there is none."""
    return FixtureProvenance.model_validate_json(provenance_path(directory).read_text())


def covered_directories(root: pathlib.Path | None = None) -> list[pathlib.Path]:
    """Every directory §33 requires a record in, derived from the tree and never enumerated.

    THREE KINDS, and the third is M's ruling of 2026-09-08 rather than the brief's own text:

    1. every fixture directory the harness SELECTS from — the fourteen with at least one
       selected file. `fixtures/fft` has none (it ships a pin record and a README and no
       payload), so it is not one, and the test below says so in as many words;
    2. every `malformed/` subdirectory, because §21's refusal set is a fixture family that a
       tracked test replays;
    3. every AUXILIARY subdirectory a tracked test replays — `egress/`, `local/`, `refusals/`,
       `framing/`, `imapb/`. The harness is never pointed at them, which is why the brief's own
       rule does not reach them; M ruled that "every fixture family used by tracked tests must
       have provenance coverage", and a family the harness does not select from is still a
       family somebody's test depends on.

    `golden/` is NOT one, at any depth. A golden is an OUTPUT of an adapter over a fixture that
    is already covered, so a provenance record there would state the origin of a file whose
    origin is the file beside it. `spec/` is not one either: it holds pinned SPECIFICATION
    records rather than payloads, it is a repository untouchable with its own gate
    (`gates/pin_paths.py`), and the pin records already carry their own provenance in a richer
    form than this schema has.
    """
    root = root or fixture_root()
    found: list[pathlib.Path] = []
    for adapter_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        if harness_selects(adapter_dir):
            found.append(adapter_dir)
        for child in sorted(p for p in adapter_dir.rglob("*") if p.is_dir()):
            if child.name in (harness.GOLDEN_DIR, "spec") or harness.GOLDEN_DIR in child.parts:
                continue
            if "spec" in child.relative_to(adapter_dir).parts:
                continue
            if harness_selects(child):
                found.append(child)
    return found


def harness_selects(directory: pathlib.Path) -> list[pathlib.Path]:
    """`harness.py`'s four predicates over one directory. The one definition of 'a fixture'."""
    return sorted(p for p in directory.iterdir()
                  if p.is_file() and not p.name.startswith(".")
                  and p.name not in ("README.md", harness.PROVENANCE_FILE))


def provenance_problems(root: pathlib.Path | None = None) -> list[str]:
    """§33 as a list of findings. Empty means every covered directory declares every fixture.

    Unconditional from this round on — §33's "once migration is complete" is THIS round, and a
    test that skipped when a record was absent would be a test that passed the day somebody
    deleted one.
    """
    root = root or fixture_root()
    problems: list[str] = []
    for directory in covered_directories(root):
        rel = directory.relative_to(root).as_posix()
        path = provenance_path(directory)
        if not path.is_file():
            problems.append(f"{rel}: no {harness.PROVENANCE_FILE}, and it holds "
                            f"{len(harness_selects(directory))} fixture(s) a tracked test reads")
            continue
        try:
            record = read_provenance(directory)
        except Exception as e:                          # noqa: BLE001 - reported, not raised
            problems.append(f"{rel}: {harness.PROVENANCE_FILE} is not a valid record: {e}")
            continue
        if record.directory != rel:
            problems.append(f"{rel}: the record calls itself {record.directory!r}")
        on_disk = {p.name for p in harness_selects(directory)}
        listed = {entry.file for entry in record.fixtures}
        for name in sorted(on_disk - listed):
            problems.append(f"{rel}/{name}: on disk and not in {harness.PROVENANCE_FILE}")
        for name in sorted(listed - on_disk):
            problems.append(f"{rel}: {harness.PROVENANCE_FILE} lists {name}, which is not there")
        for entry in record.fixtures:
            if entry.synthetic is not SYNTHETIC_REQUIRED:
                problems.append(f"{rel}/{entry.file}: synthetic is {entry.synthetic}. Every "
                                "fixture in this repository is synthetic (README.md's own "
                                "stance); a false here is a finding and not a value to accept")
            if entry.classification != CLASSIFICATION_REQUIRED:
                problems.append(f"{rel}/{entry.file}: classification "
                                f"{entry.classification!r} is not {CLASSIFICATION_REQUIRED!r}")
            if entry.standard_ref and not (root / entry.standard_ref).is_file():
                problems.append(f"{rel}/{entry.file}: standard_ref {entry.standard_ref!r} "
                                "names no file under the fixture root")
    return problems


def provenance_summary(directories: Iterable[pathlib.Path],
                       root: pathlib.Path | None = None) -> dict:
    """What the `Synthetic Fixtures` badge is grounded in, per adapter (§35).

    §32's field list does not name this, and the badge §35 requires cannot exist without it: the
    brief's own rule is "no badge without the evidence field that grounds it", so the missing
    field is a gap in the list rather than a reason to hand-assign the badge. Deliberately a
    SUMMARY and not a copy of every row — the rows are on disk beside the fixtures, and a record
    that inlined 566 of them would be a second copy of a file the digests already pin.
    """
    root = root or fixture_root()
    total = synthetic = 0
    classifications: set[str] = set()
    covered: list[str] = []
    for directory in directories:
        record = read_provenance(directory)
        covered.append(directory.relative_to(root).as_posix())
        for entry in record.fixtures:
            total += 1
            synthetic += 1 if entry.synthetic else 0
            classifications.add(entry.classification)
    return {"directories": sorted(covered), "fixtures": total, "synthetic": synthetic,
            "classifications": sorted(classifications)}


# ------------------------------------------------------------------------ §32: the record

class FileHash(Strict):
    """One file, by content. `path` is relative to the FIXTURE ROOT and never absolute.

    An absolute path would make every record machine-specific and §36's reproducibility check
    would fail on the one difference that says nothing about the tree.
    """

    path: str
    sha256: str
    bytes: int


class TestRun(Strict):
    """§32's envelope around the run this record is evidence of.

    WHICH run, since §32 does not say and two readings are available. It is the CONFORMANCE
    SUITE over this adapter — the thing `verify` re-runs and the thing `conformance` holds the
    report of — and not `pytest`. `passed`/`failed`/`skipped` are therefore counts of the
    fifteen CHECKS by verdict, which is the vocabulary the suite already speaks, and `command`
    is the exact line a reader can paste to get the same report.
    """

    command: str
    exit: int
    passed: int
    failed: int
    skipped: int
    duration_s: float
    python: str
    platform: str


class Generator(Strict):
    """§32's `generator{package_version, command}` — what MADE the record, not what it measured."""

    package_version: str
    command: str


class ProvenanceSummary(Strict):
    """See `provenance_summary()` for why this field exists although §32 does not list it."""

    directories: list[str]
    fixtures: int
    synthetic: int
    classifications: list[str]


class EvidenceRecord(Strict):
    """§32's record. STRICT, like every model in `manifest.py` and for the same reason.

    `adapter` is the MANIFEST embedded whole rather than the adapter's id: a record that named
    the manifest would be a record whose subject could change under it, and the one thing this
    document exists to do is fix what was measured.

    `source_commit` carries a `-dirty` suffix when the working tree had uncommitted changes at
    generation. That keeps §32's field list exactly as written while still recording the fact
    `verify` needs in order to say — as the brief requires — WHICH state it is comparing.
    """

    model_config = ConfigDict(extra="forbid")

    evidence_schema_version: str
    generated_at: str
    generator: Generator
    source_commit: str
    package_version: str
    cdm_version: str
    sc_oes_version: str
    adapter_api_version: str
    manifest_version: str
    adapter: dict
    test_run: TestRun
    conformance: dict
    loss_report: dict
    fixture_hashes: list[FileHash]
    fixture_provenance: ProvenanceSummary
    artifact_hashes: list[FileHash]


def _python_version() -> str:
    """`3.12.11`, from `sys.version_info` and NOT from the `platform` module.

    `platform` is a FORBIDDEN ROOT in `tests/test_cdm_boundary.py`: it is a top-level package of
    the private product repository this one was lifted out of, and that gate is what makes the
    README's independence claim enforceable. The stdlib module of the same name would satisfy the
    field and trip the gate, and widening a gate that guards a publication boundary in order to
    read a version string would be the worst trade in this file. `sysconfig.get_platform()`
    answers the other half — `macosx-15.0-arm64`, `linux-x86_64` — and is the identifier the
    packaging tools already use, so it is also the one a reader can match against a wheel tag.
    """
    return ".".join(str(part) for part in sys.version_info[:3])


def digest(path: pathlib.Path) -> tuple[str, int]:
    """SHA-256 and size. Content identification (M's ruling); see the module docstring."""
    payload = path.read_bytes()
    return hashlib.sha256(payload).hexdigest(), len(payload)


def measured_files(directory: pathlib.Path) -> list[pathlib.Path]:
    """Every file the suite READ for one adapter: fixtures, goldens, malformed payloads.

    Sorted by path so the list is an ordering and not an inode walk, and `README.md` /
    `PROVENANCE.json` are excluded because the suite does not read them — the provenance record
    is summarised in its own field instead, where a reader looking for it will look.
    """
    found: list[pathlib.Path] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.name in ("README.md", harness.PROVENANCE_FILE):
            continue
        if "spec" in path.relative_to(directory).parts:
            continue
        found.append(path)
    return found


def source_commit(start: pathlib.Path | None = None) -> str:
    """`<sha>` or `<sha>-dirty`, or `unknown` outside a checkout (an installed wheel).

    `unknown` rather than a raised error, because a record generated from site-packages is still
    a true record of a run — it simply cannot name a commit, and saying so is more useful than
    refusing to write one.
    """
    start = start or pathlib.Path(__file__).resolve().parent
    def git(*args: str) -> str | None:
        try:
            done = subprocess.run(["git", "-C", str(start), *args], capture_output=True,
                                  text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):    # pragma: no cover - no git on PATH
            return None
        return done.stdout if done.returncode == 0 else None
    head = git("rev-parse", "HEAD")
    if head is None:
        return "unknown"
    dirty = git("status", "--porcelain")
    return head.strip() + ("-dirty" if (dirty or "").strip() else "")


def generate(adapter_name: str, *, fixtures: pathlib.Path | None = None,
             now: _dt.datetime | None = None) -> EvidenceRecord:
    """One adapter's evidence record, from a run taken here and now."""
    adapter_class = load_adapter(adapter_name)
    frozen = times.FROZEN_NOW
    adapter = adapter_class(clock=times.frozen_clock(frozen), synthetic=True)
    directory = fixtures or packaged_fixtures(adapter_class)
    root = fixture_root()

    command = (f"python -m synapse_cdm.suite conformance run --adapter {adapter_name} "
               "--format json")
    started = time.monotonic()
    report = suite.run(adapter, directory, clock=times.frozen_clock(frozen), frozen_at=frozen)
    duration = time.monotonic() - started
    verdicts = [entry["verdict"] for entry in report["checks"].values()]

    hashes = []
    for path in measured_files(directory):
        sha, size = digest(path)
        hashes.append(FileHash(path=path.relative_to(root).as_posix(), sha256=sha, bytes=size))

    covered = [d for d in covered_directories(root)
               if d == directory or directory in d.parents]
    return EvidenceRecord(
        evidence_schema_version=EVIDENCE_SCHEMA_VERSION,
        generated_at=times.render(now or _dt.datetime.now(_dt.timezone.utc)),
        generator=Generator(package_version=PACKAGE_VERSION,
                            command=f"python -m synapse_cdm.evidence generate "
                                    f"--adapter {adapter_name}"),
        source_commit=source_commit(),
        package_version=PACKAGE_VERSION,
        cdm_version=SCHEMA_VERSION,
        sc_oes_version=SC_OES_VERSION,
        adapter_api_version=ADAPTER_API_VERSION,
        manifest_version=MANIFEST_SCHEMA_VERSION,
        adapter=manifest(adapter_class).model_dump(mode="json"),
        test_run=TestRun(command=command, exit=suite.exit_status(report),
                         passed=verdicts.count(suite.PASS), failed=verdicts.count(suite.FAIL),
                         skipped=verdicts.count(suite.SKIP), duration_s=round(duration, 6),
                         python=_python_version(), platform=sysconfig.get_platform()),
        conformance=report,
        loss_report=report["loss_report"],
        fixture_hashes=hashes,
        fixture_provenance=ProvenanceSummary(**provenance_summary(covered, root)),
        # §32: "MAY initially be empty". It stays empty until PR, which is the round that has
        # artefacts — a wheel and an sdist built from a release commit — to name.
        artifact_hashes=[],
    )


def serialise(record: EvidenceRecord) -> str:
    """ARCHITECTURE.md §6.2's one serialisation, which every generated file here uses."""
    return json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def record_path(out_dir: pathlib.Path, record: EvidenceRecord) -> pathlib.Path:
    return (out_dir / record.adapter["adapter"]["id"]
            / record.adapter["adapter"]["adapter_version"] / RECORD_NAME)


def write(record: EvidenceRecord, out_dir: pathlib.Path) -> pathlib.Path:
    path = record_path(out_dir, record)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialise(record))
    return path


def _flatten(payload: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            out.update(_flatten(value, f"{prefix}.{key}" if prefix else str(key)))
    else:
        out[prefix] = payload
    return out


def masked(payload: dict, *, also: Iterable[str] = ()) -> dict:
    """A COPY of the record with every field in `MASKED` replaced by `MASK_SENTINEL`.

    A `[]` segment in a path means "every element of this list", which is how the per-refusal
    wall time is reached. Nothing else in a record is inside a list and masked, and a path whose
    shape the record does not have is silently a no-op — deliberately, because a mask that
    RAISED when its field was absent would make `compare` fail on a truncated record instead of
    reporting the truncation.
    """
    out = copy.deepcopy(payload)
    for path in (*MASKED, *also):
        _apply_mask(out, path.split("."))
    return out


def _apply_mask(node: Any, segments: list[str]) -> None:
    head, rest = segments[0], segments[1:]
    if head.endswith("[]"):
        children = node.get(head[:-2]) if isinstance(node, dict) else None
        for child in children or []:
            _apply_mask(child, rest)
        return
    if not isinstance(node, dict) or head not in node:
        return
    if rest:
        _apply_mask(node[head], rest)
    else:
        node[head] = MASK_SENTINEL


def compare(recorded: dict, fresh: dict) -> list[str]:
    """Every field that differs, excluding `MASKED` and a dirty `source_commit` (§36).

    Lists are compared as whole values rather than element-wise: `fixture_hashes` differing by
    one entry is one finding about the fixture set, and 733 findings about 733 files would bury
    it. The masking happens BEFORE that collapse, which is why it is a rewrite of the payload
    rather than a filter over flattened keys — a value inside a list cannot be excluded by name
    once the list has become one leaf.
    """
    also = ("source_commit",) if (recorded.get("source_commit", "").endswith("-dirty")
                                  or fresh.get("source_commit", "").endswith("-dirty")) else ()
    left = _flatten(masked(recorded, also=also))
    right = _flatten(masked(fresh, also=also))
    problems = []
    for key in sorted(set(left) | set(right)):
        if key not in left:
            problems.append(f"{key}: absent from the record, now {right[key]!r}")
        elif key not in right:
            problems.append(f"{key}: in the record as {left[key]!r}, now absent")
        elif left[key] != right[key]:
            problems.append(f"{key}: record says {left[key]!r}, this tree gives {right[key]!r}")
    return problems


def verify(path: pathlib.Path) -> tuple[list[str], str]:
    """Re-derive the record at `path` and report every unmasked difference.

    Returns (problems, what was masked). Re-hashes every fixture and re-runs the suite: the
    point is not to read the record back, which proves nothing, but to produce a new one from
    this tree and compare.
    """
    recorded = json.loads(path.read_text())
    adapter_id = recorded["adapter"]["adapter"]["id"]
    fresh = generate(adapter_id).model_dump(mode="json")
    said = list(MASKED)
    if recorded.get("source_commit", "").endswith("-dirty") or \
            fresh.get("source_commit", "").endswith("-dirty"):
        said.append("source_commit (the tree is dirty, so no commit describes it)")
    return compare(recorded, fresh), ", ".join(said)


# ------------------------------------------------------------------------------ §35: badges

#: shields.io's endpoint schema. Four keys and no fifth: this package renders no SVG, which is
#: pre-ruled default 4 — the badge service does that, and a package that drew its own badges
#: would be a package maintaining a picture format.
BADGE_SCHEMA_VERSION = 1

_GREEN, _AMBER, _RED = "brightgreen", "orange", "red"


def _badge(label: str, message: str, color: str) -> dict:
    return {"schemaVersion": BADGE_SCHEMA_VERSION, "label": label, "message": message,
            "color": color}


def badges(record: dict) -> dict[str, dict]:
    """One adapter's badges, keyed by slug. A badge whose grounding field is ABSENT is ABSENT.

    §35's rule, and the reason it is worth a test of its own: the failure mode a badge system has
    is not a wrong colour, it is a badge that keeps rendering after the thing it described stopped
    being measured. So every badge below reads ONE named field and is simply not emitted when
    that field is not in the record — not emitted red, which would be a claim, and not emitted
    grey, which would be a claim that the tool is fine.
    """
    out: dict[str, dict] = {}
    conformance = record.get("conformance") or {}
    checks = conformance.get("checks") or {}

    if "result" in conformance:
        conformant = conformance["result"] == "CONFORMANT"
        out["sc-cdm-compatible"] = _badge(
            "SC-CDM Compatible", "yes" if conformant else "no", _GREEN if conformant else _RED)
    if "maturity_eligible" in conformance:
        level = conformance["maturity_eligible"]
        out["conformance-level"] = _badge(
            "Conformance", level, _GREEN if level in ("L4", "L5", "L6") else _AMBER)
    for slug, letter, label in (("roundtrip-verified", "E", "Roundtrip Verified"),
                                ("deterministic", "G", "Deterministic")):
        entry = checks.get(letter)
        if isinstance(entry, dict) and "verdict" in entry:
            passed = entry["verdict"] == suite.PASS
            out[slug] = _badge(label, "yes" if passed else entry["verdict"].lower(),
                               _GREEN if passed else _AMBER)
    loss = record.get("loss_report") or {}
    lossless_entry = checks.get("D")
    if "counts" in loss and isinstance(lossless_entry, dict) and "verdict" in lossless_entry:
        clean = lossless_entry["verdict"] == suite.PASS and not loss["counts"]["DROPPED"]
        out["lossless-verified"] = _badge("Lossless Verified", "yes" if clean else "no",
                                          _GREEN if clean else _RED)
    provenance = record.get("fixture_provenance") or {}
    if "fixtures" in provenance and "synthetic" in provenance:
        every = provenance["fixtures"] and provenance["fixtures"] == provenance["synthetic"]
        out["synthetic-fixtures"] = _badge("Synthetic Fixtures", "all" if every else "not all",
                                           _GREEN if every else _RED)
    return out


def repository_badges(records: Iterable[dict]) -> dict[str, dict]:
    """The repository-level set: the same six, over the whole roster, worst-case per badge.

    A repository badge that reported the BEST adapter would be a badge that says nothing, so
    each one is the weakest reading among the records — and a badge absent from any one record
    is absent from the repository set too, on the same "no badge without its field" rule.
    """
    per = [badges(record) for record in records]
    if not per:
        return {}
    shared = set(per[0])
    for entry in per[1:]:
        shared &= set(entry)
    out: dict[str, dict] = {}
    for slug in sorted(shared):
        worst = min((entry[slug] for entry in per),
                    key=lambda badge: (_GREEN, _AMBER, _RED).index(badge["color"]) * -1)
        out[slug] = dict(worst)
        if slug == "conformance-level":
            out[slug] = _badge("Conformance", min(entry[slug]["message"] for entry in per),
                               worst["color"])
    return out


def read_records(evidence_dir: pathlib.Path) -> dict[str, dict]:
    """Every `evidence.json` under `evidence_dir`, keyed by adapter id, newest version last."""
    found: dict[str, dict] = {}
    for path in sorted(evidence_dir.rglob(RECORD_NAME)):
        payload = json.loads(path.read_text())
        found[payload["adapter"]["adapter"]["id"]] = payload
    return found


def write_badges(records: dict[str, dict], out_dir: pathlib.Path) -> list[pathlib.Path]:
    written = []
    for adapter_id, record in sorted(records.items()):
        for slug, badge in sorted(badges(record).items()):
            path = out_dir / adapter_id / f"{slug}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(badge, indent=2, sort_keys=True) + "\n")
            written.append(path)
    for slug, badge in sorted(repository_badges(records.values()).items()):
        path = out_dir / "repository" / f"{slug}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(badge, indent=2, sort_keys=True) + "\n")
        written.append(path)
    return written


# ---------------------------------------------------------------------------------- the CLI

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="synapse evidence", description=__doc__.splitlines()[0])
    actions = parser.add_subparsers(dest="action")

    gen = actions.add_parser("generate", help="write an evidence record per adapter")
    gen.add_argument("--adapter", default=None, help="registered name; omit with --all")
    gen.add_argument("--all", action="store_true", help="every adapter this package ships")
    gen.add_argument("--out", type=pathlib.Path, default=pathlib.Path("evidence"))
    gen.add_argument("--fixtures", type=pathlib.Path, default=None)

    check = actions.add_parser("verify", help="re-derive a record from this tree and compare")
    check.add_argument("file", type=pathlib.Path, nargs="+")

    prov = actions.add_parser("provenance", help="check §33's records over the fixture tree")
    prov.add_argument("--check", action="store_true", default=True)

    badge = actions.add_parser("badges", help="shields.io endpoint JSON, derived from evidence")
    badge.add_argument("--from", dest="source", type=pathlib.Path,
                       default=pathlib.Path("evidence"),
                       help="a directory of generated evidence records")
    badge.add_argument("--out", type=pathlib.Path, default=None,
                       help="default <--from>/badges")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.action is None:
        parser.error("usage: synapse evidence generate --all | verify <file> | provenance")

    if args.action == "provenance":
        problems = provenance_problems()
        for problem in problems:
            print(f"synapse evidence: {problem}", file=sys.stderr)
        print(f"{'INCOMPLETE' if problems else 'COMPLETE'}: "
              f"{len(covered_directories())} fixture directories under §33")
        return EXIT_FAILED if problems else EXIT_OK

    if args.action == "badges":
        records = read_records(args.source)
        if not records:
            print(f"synapse badges: no {RECORD_NAME} under {args.source}. A badge is derived "
                  "from a record and there is nothing to derive one from — run "
                  "`synapse evidence generate --all` first", file=sys.stderr)
            return EXIT_USAGE
        out = args.out or (args.source / "badges")
        written = write_badges(records, out)
        print(f"wrote {len(written)} badge(s) for {len(records)} adapter(s) and the repository "
              f"under {out}")
        return EXIT_OK

    if args.action == "verify":
        failed = 0
        for path in args.file:
            if not path.is_file():
                print(f"synapse evidence: {path} does not exist", file=sys.stderr)
                return EXIT_USAGE
            problems, masked = verify(path)
            for problem in problems:
                print(f"{path}: {problem}", file=sys.stderr)
            print(f"{'DIFFERS' if problems else 'REPRODUCED'}: {path} "
                  f"(masked: {masked})")
            failed += 1 if problems else 0
        return EXIT_FAILED if failed else EXIT_OK

    if not args.all and not args.adapter:
        parser.error("generate needs --adapter <name> or --all")
    if args.all and args.fixtures:
        parser.error("--fixtures names one directory and --all runs the whole roster")
    names = sorted(shipped()) if args.all else [args.adapter]
    for name in names:
        try:
            record = generate(name, fixtures=args.fixtures)
        except LookupError as e:
            print(f"synapse evidence: {e}", file=sys.stderr)
            return EXIT_USAGE
        print(f"wrote {write(record, args.out)}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
