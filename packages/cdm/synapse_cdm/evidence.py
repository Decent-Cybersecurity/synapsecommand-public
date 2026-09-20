"""Evidence records — the machine-generated basis for every compatibility claim (§31–§36).

WHAT A CLAIM WAS BEFORE THIS MODULE
------------------------------------
An adapter has declared its maturity rung and its claim status since P1, and the conformance
suite has computed an eligible rung since P2. Both are true statements and neither is EVIDENCE:
one is what the adapter says about itself, the other is what a tool said on a machine nobody
can name, on a tree nobody recorded, at a moment nobody wrote down. A third party reading
`manifests/adsb.json` cannot tell whether `maturity: L4` was earned or typed.

An evidence record is that missing thing: one JSON document per adapter carrying the manifest it
measured, the commit it measured at, every version axis in force, the suite's own report with
one field made portable (`suite.portable`: `conformance.adapter.fixtures` reads `<packaged>/<dir>`
and never the absolute path the run read — since 2026-09-16, because the path made every record
machine-specific), the loss report, and a digest of every fixture file the run read. `verify`
re-derives all of it and reports what differs, comparing every field but `MASKED`, `ENVIRONMENT`
and a dirty `source_commit`. §36's reproducibility is therefore a COMMAND rather than a promise,
and a claim that cannot be reproduced is visible as a diff rather than as a rumour.

WHAT KIND OF EVIDENCE IT IS (audit remediation F07, 2026-09-20)
-----------------------------------------------------------------
A record also says which of five KINDS of evidence it holds (`EvidenceCategory`): the
internal fixture run and this package's own round trip, which the suite produces; and an
independently derived expected result, a validation against the source format's normative
schema, and an exchange with an independently implemented endpoint, which only an exercise
report (`ExerciseReport`, written by `synapse evidence exercise` from an operator's
specification) can make PRESENT. `maturity_support` holds the declared rung to the categories
it requires and reports local completion separately from outstanding external validation.
`snapshot` names the exact source state — commit, and a digest of the dirty diff when there
is one — never the record's own final commit. No shipped exercise report exists; every
external category reads ABSENT for every adapter, and `external_exercise` stays null.

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
import enum
import hashlib
import json
import pathlib
import subprocess
import sys
import sysconfig
import time
from typing import Any, Iterable

from pydantic import ConfigDict, field_validator, model_validator

from synapse_cdm import canonical, harness, suite, times
from synapse_cdm.adapter import fixture_root, load_adapter, packaged_fixtures
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
#:   source_commit         — ONLY when the tree is dirty, and `verify` says which. A dirty tree
#:                           has no commit that describes it, so comparing the field would be
#:                           comparing a label to a thing it does not name.
#:
#: A THIRD ENTRY WAS HERE UNTIL 2026-09-08 AND THE FIELD IT NAMED NO LONGER EXISTS. It was
#: `conformance.checks.H.details.refusals[].seconds`, how long ONE malformed payload took to be
#: refused, found by round P4's §36 proof rather than reasoned about: two generations from one
#: fresh clone differed in exactly one field, and it was `stanag4676`'s second refusal reading
#: 0.0 and then 0.0001. Round PB took the reading out of `suite.py`'s report instead of masking
#: it, on M's ruling of 2026-09-08 — the same value reddened
#: `test_two_sweeps_of_one_tree_are_byte_identical` on two release-pipeline runners out of two,
#: and those two tests compare the bytes UNMASKED, so a mask here could never have made the
#: artefact reproducible. What check H publishes now is `over_time_bound`, a boolean, and
#: `timeout_s`, the declared bound. Deterministic output should not depend on a consumer knowing
#: which fields to ignore.
MASKED = ("generated_at", "test_run.duration_s")

#: Fields that describe the HOST the record was made on rather than the tree it measured
#: (2026-09-16). They are RECORDED — §32 asks for the envelope, and a reader matching a record
#: against a wheel tag needs both — and `verify` prints them where they differ, but they are
#: never compared: two reproductions of one tree on two machines are the same evidence, and a
#: record that could only be reproduced on the interpreter that wrote it would be reproducible
#: by nobody a release is for. Enumerated rather than patterned, for MASKED's reason. Found the
#: way the third MASKED entry was found: a CI record verified from another checkout differed in
#: exactly these two fields and the fixtures path, none of which says anything about the tree.
ENVIRONMENT = ("test_run.python", "test_run.platform")

#: What a masked field is replaced BY. A sentinel and not a deletion, because two records where
#: one has the field and the other does not are still different records, and `compare` has to be
#: able to say so.
MASK_SENTINEL = "<masked>"


# --------------------------------------------------------------------------- §33: provenance

#: §33's identifier. Spelled `schema_id` and not `schema` on THIS REPOSITORY'S OWN PRECEDENT:
#: `manifests.SCHEMA_ID` carries §13's `schema:` key under the same name, for the same reason —
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
    """`harness.select_fixtures`, the one definition of 'a fixture', under this module's name."""
    return harness.select_fixtures(directory)


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


# ------------------------------------------ F07: the snapshot, the categories, the exercise

#: Where one adapter's exercise reports live, beside its record:
#: `evidence/<adapter>/<adapter-version>/exercises/<slug>.json`. A record names each one it
#: read, relative to its own directory and hashed, so `verify` can re-read the same files.
EXERCISES_DIR = "exercises"


class Snapshot(Strict):
    """The exact source state a record measured (audit remediation F07, 2026-09-20).

    `commit` is HEAD at generation and `unknown` outside a checkout. `dirty` says whether the
    tree differed from that commit; when it did, `tracked_diff_sha256` is SHA-256 over
    `git diff HEAD` (every staged and unstaged change to a tracked file) and `untracked` hashes
    every file git lists as untracked and not ignored, so two dirty states can be told apart —
    `source_commit`'s `-dirty` suffix could only say that one was dirty. `digest` is one SHA-256
    over the canonical serialisation of those two readings, the figure a report quotes; `null`
    on a clean tree, where the commit is the whole description.

    NOT THE RECORD'S OWN FINAL COMMIT. Records are not tracked (module docstring), so the
    commit that will eventually carry a release's records is never inside them, and no circle
    exists between a record and the commit it lands in. A file named `evidence.json` is left
    out of `untracked` for the same reason: it is the output, not the state.
    """

    commit: str
    dirty: bool
    tracked_diff_sha256: str | None
    untracked: list[FileHash]
    digest: str | None


class EvidenceCategory(str, enum.Enum):
    """F07's five KINDS of evidence — different kinds, not interchangeable maturity labels.

    The first two this repository produces on its own, from the suite over the packaged
    synthetic set. The last three only an outside party can supply, through an exercise report
    (`ExerciseReport`), and until one exists each reads ABSENT: never invented, never inferred
    from the internal two. A second process running this package's own encoder and decoder, or
    an expected output generated by the code under test, is the internal kind and says so.
    """

    INTERNAL_FIXTURE = "internal_fixture"
    SELF_ROUND_TRIP = "self_round_trip"
    INDEPENDENT_EXPECTED = "independent_expected"
    NORMATIVE_SCHEMA = "normative_schema"
    INDEPENDENT_ENDPOINT = "independent_endpoint"


#: The categories only an exercise report can make PRESENT, in the enum's order.
EXTERNAL_CATEGORIES: tuple[EvidenceCategory, ...] = (
    EvidenceCategory.INDEPENDENT_EXPECTED, EvidenceCategory.NORMATIVE_SCHEMA,
    EvidenceCategory.INDEPENDENT_ENDPOINT)

#: Why each external category reads ABSENT when no exercise report exists — the basis the record
#: carries, and (F05, 2026-09-20) the basis the generated support matrix prints, so the two are
#: one statement.
EXTERNAL_ABSENT_BASIS: dict[EvidenceCategory, str] = {
    EvidenceCategory.INDEPENDENT_EXPECTED:
        "no expected result derived by another implementation: every golden in this "
        "repository was written by the code under test",
    EvidenceCategory.NORMATIVE_SCHEMA:
        "check B validates the CDM's own published schema, which this repository wrote; no "
        "authorised normative schema of the source format is held offline (F05)",
    EvidenceCategory.INDEPENDENT_ENDPOINT:
        "no exchange with an independently implemented endpoint has been recorded; "
        "`external_exercise` is null and L6 is not awardable from this repository's own "
        "evidence (ARCHITECTURE.md §3.3)",
}


class CategoryStatus(str, enum.Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CategoryReading(Strict):
    """One category's status, the reading it rests on, and the reports — relative to the record's
    directory and hashed — that made it PRESENT. `sources` is empty unless it is."""

    status: CategoryStatus
    basis: str
    sources: list[FileHash]


#: What each DECLARED rung requires, by category. L1–L3 rest on the internal fixture run, L4
#: and L5 add this package's own round trip, L6 is an exchange with an independent endpoint
#: (ARCHITECTURE.md §3.3). A requirement is satisfied by PRESENT only: NOT_APPLICABLE is a rung
#: passed vacuously, and a rung passed vacuously is not a rung declared (§3.6, rule 4, as
#: `tests/test_cdm_manifests.py` already reads it for the roundtrip check).
RUNG_CATEGORIES: dict[str, tuple[EvidenceCategory, ...]] = {
    "L0": (),
    "L1": (EvidenceCategory.INTERNAL_FIXTURE,),
    "L2": (EvidenceCategory.INTERNAL_FIXTURE,),
    "L3": (EvidenceCategory.INTERNAL_FIXTURE,),
    "L4": (EvidenceCategory.INTERNAL_FIXTURE, EvidenceCategory.SELF_ROUND_TRIP),
    "L5": (EvidenceCategory.INTERNAL_FIXTURE, EvidenceCategory.SELF_ROUND_TRIP),
    "L6": (EvidenceCategory.INTERNAL_FIXTURE, EvidenceCategory.SELF_ROUND_TRIP,
           EvidenceCategory.INDEPENDENT_ENDPOINT),
}


class MaturitySupport(Strict):
    """The declared rung held to the categories that back it, with local code completion and
    outstanding external validation reported SEPARATELY (F07's acceptance).

    `eligible_level` stays the suite's — it computes a rung from check verdicts and is not
    touched here. This block asks a different question: of the categories the DECLARED rung
    requires, which are PRESENT. `local_complete` is true when everything this repository can
    produce on its own is PRESENT or NOT_APPLICABLE and the run is CONFORMANT;
    `external_outstanding` names every external category still ABSENT, so a reader never has
    to infer from a green local reading that the outside validation happened.
    """

    declared: str
    eligible: str
    required: list[str]
    satisfied: bool
    local_complete: bool
    external_outstanding: list[str]


class Party(Strict):
    """One side of an exercise: an implementation and its version."""

    implementation: str
    version: str


class ExerciseInput(Strict):
    """One input the exercise read: its digest, where it came from and who authorised its use.

    `path` is as the specification named it, relative to the specification's own directory.
    """

    path: str
    sha256: str
    bytes: int
    provenance: str
    authorised_by: str


AGREE, DIFFER = "AGREE", "DIFFER"
DIRECTIONS = ("ingress", "egress")


class ExerciseResult(Strict):
    """One direction exercised: the command, the expected and observed digests, the verdict.

    The verdict is COMPUTED from the two digests by the runner and re-checked here, so a report
    that says AGREE over two digests that differ is refused at load rather than believed.
    """

    direction: str
    command: str
    expected_sha256: str
    observed_sha256: str
    verdict: str
    note: str

    @model_validator(mode="after")
    def _verdict_is_the_digests(self) -> "ExerciseResult":
        if self.direction not in DIRECTIONS:
            raise ValueError(f"direction {self.direction!r} is neither of {DIRECTIONS}")
        computed = AGREE if self.expected_sha256 == self.observed_sha256 else DIFFER
        if self.verdict != computed:
            raise ValueError(f"verdict {self.verdict!r} where the digests say {computed}: a "
                             "verdict is derived from the two digests, never typed")
        return self


def _folded(name: str) -> str:
    return "".join(ch for ch in name.casefold() if ch.isalnum())


#: Names this package answers to, folded to letters and digits. A peer under any of them is this
#: package talking to itself, and the brief's words are the rule: "a second process running the
#: same encoder/decoder … is not independence".
SELF_NAMES = frozenset({"synapsecdm", "synapsecommand", "synapsecommandpublic"})


class ExerciseReport(Strict):
    """F07's runner report: an exchange with, or an expected result from, something that is not
    this package.

    Records both sides' implementation and version, the edition and profile exercised, every
    input with its provenance and authorised digest, the directions and commands, expected
    versus observed as digests with a computed verdict, the limitations, the environment, and
    the snapshot of THIS side's source. Validity is structural and about independence; whether
    the exchange SUCCEEDED is in `results[].verdict`, and a report of a failed exchange is a
    valid report. Nothing here is generated from this repository's own fixtures: no shipped
    report exists, and `generate` reads ABSENT for every external category until one does.
    """

    evidence_schema_version: str
    adapter_id: str
    adapter_version: str
    category: EvidenceCategory
    performed_at: str
    this_side: Party
    peer: Party
    edition: str
    profile: str | None
    inputs: list[ExerciseInput]
    directions: list[str]
    results: list[ExerciseResult]
    limitations: list[str]
    environment: dict[str, str]
    snapshot: Snapshot

    @model_validator(mode="after")
    def _independent_and_complete(self) -> "ExerciseReport":
        if self.category not in EXTERNAL_CATEGORIES:
            raise ValueError(
                f"category {self.category.value} is produced by the suite itself; an exercise "
                f"report carries one of {[c.value for c in EXTERNAL_CATEGORIES]}")
        if not self.peer.implementation.strip() or not self.peer.version.strip():
            raise ValueError("peer.implementation and peer.version are required: an exercise "
                             "against an unnamed implementation is not evidence of independence")
        if _folded(self.peer.implementation) in SELF_NAMES:
            raise ValueError(
                f"peer {self.peer.implementation!r} is this package. A second process running the "
                "same encoder/decoder is not independence (F07); name the other implementation")
        if not self.edition.strip():
            raise ValueError("edition is empty: which edition of the format was exercised")
        if not self.inputs:
            raise ValueError("inputs is empty: an exercise read something, and its provenance and "
                             "digest are what make the result reproducible")
        if not self.results:
            raise ValueError("results is empty: nothing was exercised")
        exercised = sorted({r.direction for r in self.results})
        if exercised != sorted(set(self.directions)):
            raise ValueError(f"directions {self.directions} do not agree with the results' "
                             f"{exercised}")
        return self


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
    # F07 (2026-09-20): the exact snapshot, the five categories, and the declared rung held
    # to them. Additive; `source_commit` stays as §32 lists it and is derived from `snapshot`.
    snapshot: Snapshot
    evidence_categories: dict[str, CategoryReading]
    maturity_support: MaturitySupport


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


def _git(start: pathlib.Path, *args: str) -> bytes | None:
    """`git -C <start> <args>`'s stdout as BYTES, or None where git is absent or refuses.

    Bytes and not text, because `git diff` over a binary or a non-UTF-8 file is still a diff
    and the digest is over what git wrote, not over what a decoder made of it.
    """
    try:
        done = subprocess.run(["git", "-C", str(start), *args], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):    # pragma: no cover - no git on PATH
        return None
    return done.stdout if done.returncode == 0 else None


def snapshot(start: pathlib.Path | None = None) -> Snapshot:
    """The exact source state of the checkout `start` is in — see `Snapshot` for each field.

    `commit: unknown` and clean rather than a raised error outside a checkout, because a record
    generated from site-packages is still a true record of a run — it simply cannot name a
    commit, and saying so is more useful than refusing to write one.
    """
    start = start or pathlib.Path(__file__).resolve().parent
    head = _git(start, "rev-parse", "HEAD")
    if head is None:
        return Snapshot(commit="unknown", dirty=False, tracked_diff_sha256=None,
                        untracked=[], digest=None)
    # From the TOP of the checkout, not from `start`: `git ls-files` lists relative to the
    # working directory and only below it, and a snapshot taken from the package directory
    # would have missed every untracked file outside `synapse_cdm/` (caught 2026-09-20).
    top = pathlib.Path((_git(start, "rev-parse", "--show-toplevel") or b"").decode().strip())
    diff = _git(top, "diff", "HEAD", "--no-ext-diff", "--no-color") or b""
    tracked = hashlib.sha256(diff).hexdigest() if diff else None
    listed = _git(top, "ls-files", "--others", "--exclude-standard", "-z") or b""
    untracked: list[FileHash] = []
    for rel in sorted(p for p in listed.decode("utf-8", "surrogateescape").split("\0") if p):
        path = top / rel
        if not path.is_file() or path.name == RECORD_NAME:
            continue
        sha, size = digest(path)
        untracked.append(FileHash(path=rel, sha256=sha, bytes=size))
    dirty = tracked is not None or bool(untracked)
    summary = None
    if dirty:
        payload = {"tracked_diff_sha256": tracked,
                   "untracked": [entry.model_dump(mode="json") for entry in untracked]}
        summary = hashlib.sha256(canonical.serialise(payload).encode("utf-8")).hexdigest()
    return Snapshot(commit=head.decode().strip(), dirty=dirty, tracked_diff_sha256=tracked,
                    untracked=untracked, digest=summary)


def source_commit(start: pathlib.Path | None = None) -> str:
    """`<sha>` or `<sha>-dirty`, or `unknown` outside a checkout — §32's field, read off the
    snapshot so the two can never disagree about whether the tree was dirty."""
    snap = snapshot(start)
    return snap.commit + ("-dirty" if snap.dirty else "")


# ------------------------------------------------------------ F07: categories and support

def _check_is(checks: dict, letter: str, verdict: str) -> bool:
    entry = checks.get(letter) or {}
    return entry.get("verdict") == verdict


def read_exercises(directory: pathlib.Path | None, adapter_id: str,
                   adapter_version: str) -> list[tuple[pathlib.Path, ExerciseReport]]:
    """Every `*.json` under `directory`, as validated reports for THIS adapter and version.

    A report that does not validate, or that names another adapter or version, is a
    `ValueError` naming the file rather than a report silently left out: a directory of
    reports is a claim, and the claim is refused whole when one of its parts is not what it
    says. An absent directory is the ordinary offline case and reads as no reports.
    """
    if directory is None or not directory.is_dir():
        return []
    found = []
    for path in sorted(directory.glob("*.json")):
        try:
            report = ExerciseReport.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError as e:
            raise ValueError(f"{path}: not a valid exercise report — {e}") from e
        if (report.adapter_id, report.adapter_version) != (adapter_id, adapter_version):
            raise ValueError(
                f"{path}: reports {report.adapter_id} {report.adapter_version}, and this record "
                f"is {adapter_id} {adapter_version}")
        found.append((path, report))
    return found


def categories(conformance: dict, provenance: ProvenanceSummary,
               exercises: list[tuple[pathlib.Path, ExerciseReport]],
               record_dir: pathlib.Path | None = None) -> dict[str, CategoryReading]:
    """The five readings, each DERIVED: the internal two from the suite's verdicts and the
    provenance summary, the external three from the validated reports and nothing else."""
    checks = conformance.get("checks") or {}
    out: dict[str, CategoryReading] = {}

    failed = [letter for letter in "ABC" if not _check_is(checks, letter, suite.PASS)]
    synthetic = provenance.fixtures > 0 and provenance.fixtures == provenance.synthetic
    if synthetic and not failed:
        out[EvidenceCategory.INTERNAL_FIXTURE.value] = CategoryReading(
            status=CategoryStatus.PRESENT,
            basis=f"checks A, B and C PASS over {provenance.fixtures} packaged fixtures, every "
                  "one synthetic (§33) — this repository's own evidence, produced by the code "
                  "under test", sources=[])
    else:
        why = (f"checks {', '.join(failed)} are not PASS" if failed
               else "no synthetic fixture set was read")
        out[EvidenceCategory.INTERNAL_FIXTURE.value] = CategoryReading(
            status=CategoryStatus.ABSENT, basis=why, sources=[])

    e_entry = checks.get("E") or {}
    if _check_is(checks, "E", suite.PASS):
        out[EvidenceCategory.SELF_ROUND_TRIP.value] = CategoryReading(
            status=CategoryStatus.PRESENT,
            basis="check E PASS: source → CDM → source under the class's declared tolerance, "
                  "encoded and decoded by THIS package on both legs — self round trip, which "
                  "is not independence", sources=[])
    elif _check_is(checks, "E", suite.SKIP) and e_entry.get("declared_inapplicable"):
        out[EvidenceCategory.SELF_ROUND_TRIP.value] = CategoryReading(
            status=CategoryStatus.NOT_APPLICABLE,
            basis=f"check E SKIP, declared inapplicable: {e_entry.get('reason') or 'no egress'}",
            sources=[])
    else:
        out[EvidenceCategory.SELF_ROUND_TRIP.value] = CategoryReading(
            status=CategoryStatus.ABSENT,
            basis=f"check E is {e_entry.get('verdict', 'absent')}", sources=[])

    for category in EXTERNAL_CATEGORIES:
        mine = [(path, report) for path, report in exercises if report.category is category]
        if not mine:
            out[category.value] = CategoryReading(status=CategoryStatus.ABSENT,
                                                  basis=EXTERNAL_ABSENT_BASIS[category],
                                                  sources=[])
            continue
        sources = []
        for path, _report in mine:
            sha, size = digest(path)
            rel = (path.relative_to(record_dir).as_posix() if record_dir and
                   record_dir in path.parents else f"{EXERCISES_DIR}/{path.name}")
            sources.append(FileHash(path=rel, sha256=sha, bytes=size))
        peers = sorted({f"{r.peer.implementation} {r.peer.version}" for _p, r in mine})
        agreed = sum(1 for _p, r in mine for result in r.results if result.verdict == AGREE)
        total = sum(len(r.results) for _p, r in mine)
        out[category.value] = CategoryReading(
            status=CategoryStatus.PRESENT,
            basis=f"{len(mine)} exercise report(s) against {', '.join(peers)}; {agreed} of "
                  f"{total} exercised direction(s) AGREE", sources=sources)
    return out


def maturity_support(declared: str, eligible: str,
                     readings: dict[str, CategoryReading], conformant: bool) -> MaturitySupport:
    """`MaturitySupport` for one record — see the class for what each field answers."""
    required = [c.value for c in RUNG_CATEGORIES.get(declared, ())]
    satisfied = all(readings[c].status is CategoryStatus.PRESENT for c in required)
    local = (EvidenceCategory.INTERNAL_FIXTURE.value, EvidenceCategory.SELF_ROUND_TRIP.value)
    local_complete = conformant and all(
        readings[c].status in (CategoryStatus.PRESENT, CategoryStatus.NOT_APPLICABLE)
        for c in local)
    outstanding = [c.value for c in EXTERNAL_CATEGORIES
                   if readings[c.value].status is CategoryStatus.ABSENT]
    return MaturitySupport(declared=declared, eligible=eligible, required=required,
                           satisfied=satisfied, local_complete=local_complete,
                           external_outstanding=outstanding)


def generate(adapter_name: str, *, fixtures: pathlib.Path | None = None,
             now: _dt.datetime | None = None,
             exercises: pathlib.Path | None = None) -> EvidenceRecord:
    """One adapter's evidence record, from a run taken here and now.

    `exercises` is the directory of this adapter's exercise reports (`EXERCISES_DIR` beside
    the record), read and validated when it exists; `None` or a missing directory is the
    ordinary offline case and every external category reads ABSENT. Nothing here needs a
    partner system, a credential or the network.
    """
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
    # The packaged directory is named the way the `--all` sweep names it — `<packaged>/<dir>` —
    # and not by the absolute path `run()` read (2026-09-16). An absolute path made every record
    # machine-specific, which is the failure `FileHash` was already spelled relative to avoid: a
    # CI record verified from any other checkout differed on the one field that says nothing
    # about the tree. A caller-supplied `--fixtures` directory stays as given: it is machine-
    # specific by the caller's choice, and `verify` — which regenerates from the packaged set —
    # can never reproduce such a record anyway.
    if directory == packaged_fixtures(adapter_class):
        report = suite.portable(report, suite.packaged_label(adapter_class))
    verdicts = [entry["verdict"] for entry in report["checks"].values()]

    hashes = []
    for path in measured_files(directory):
        sha, size = digest(path)
        hashes.append(FileHash(path=path.relative_to(root).as_posix(), sha256=sha, bytes=size))

    covered = [d for d in covered_directories(root)
               if d == directory or directory in d.parents]
    published = manifest(adapter_class).model_dump(mode="json")
    provenance = ProvenanceSummary(**provenance_summary(covered, root))
    reports = read_exercises(exercises, published["adapter"]["id"],
                             published["adapter"]["adapter_version"])
    readings = categories(report, provenance, reports,
                          record_dir=exercises.parent if exercises else None)
    snap = snapshot()
    return EvidenceRecord(
        evidence_schema_version=EVIDENCE_SCHEMA_VERSION,
        generated_at=times.render(now or _dt.datetime.now(_dt.timezone.utc)),
        generator=Generator(package_version=PACKAGE_VERSION,
                            command=f"python -m synapse_cdm.evidence generate "
                                    f"--adapter {adapter_name}"),
        source_commit=snap.commit + ("-dirty" if snap.dirty else ""),
        package_version=PACKAGE_VERSION,
        cdm_version=SCHEMA_VERSION,
        sc_oes_version=SC_OES_VERSION,
        adapter_api_version=ADAPTER_API_VERSION,
        manifest_version=MANIFEST_SCHEMA_VERSION,
        adapter=published,
        test_run=TestRun(command=command, exit=suite.exit_status(report),
                         passed=verdicts.count(suite.PASS), failed=verdicts.count(suite.FAIL),
                         skipped=verdicts.count(suite.SKIP), duration_s=round(duration, 6),
                         python=_python_version(), platform=sysconfig.get_platform()),
        conformance=report,
        loss_report=report["loss_report"],
        fixture_hashes=hashes,
        fixture_provenance=provenance,
        # §32: "MAY initially be empty", and it is empty for a reason of ORDER rather than of a
        # round not yet run (corrected 2026-09-16; it used to say "until PR"). The field is for
        # the release artefacts — wheel, sdist, the two SBOMs — but `publish.yml` generates and
        # tars the records in the `gate` job, BEFORE the `build` job produces `dist/*`, and
        # `verify` re-derives a record from the tree, so a digest of a file that is not in the
        # tree would never reproduce. Those digests are published where they can be: in
        # `SHA256SUMS` beside the artefacts, and in `releases/witness/<version>.json` as
        # `artifact_sha256` and `sbom_sha256`. Filling this field is a post-build step that
        # rewrites the records and moves the field into the recorded-not-compared class above;
        # that is a change to the pipeline's sequence and belongs to a release round.
        artifact_hashes=[],
        snapshot=snap,
        evidence_categories=readings,
        maturity_support=maturity_support(
            published["adapter"]["maturity"]["level"], report["maturity_eligible"], readings,
            conformant=report.get("result") == "CONFORMANT"),
    )


# ------------------------------------------------------------------- F07: the exercise runner

def _resolve(base: pathlib.Path, named: str) -> pathlib.Path:
    path = pathlib.Path(named)
    return path if path.is_absolute() else base / path


def _hashed_input(base: pathlib.Path, entry: dict) -> ExerciseInput:
    path = _resolve(base, entry["path"])
    if not path.is_file():
        raise ValueError(f"input {entry['path']} is not a file under {base}")
    sha, size = digest(path)
    return ExerciseInput(path=entry["path"], sha256=sha, bytes=size,
                         provenance=entry["provenance"], authorised_by=entry["authorised_by"])


def exercise(adapter_name: str, spec: dict, *, base: pathlib.Path,
             now: _dt.datetime | None = None) -> ExerciseReport:
    """Build one exercise report from an operator's specification — the runner half of F07.

    `spec` names what only the operator knows: the category, the peer's implementation and
    version, the edition and profile, every input with its provenance and who authorised its
    use, and per direction the command that was run and the paths of the EXPECTED and OBSERVED
    outputs. The runner supplies everything that can be derived: every digest, each verdict
    from its two digests, this side's implementation and version, the environment, and the
    snapshot of this checkout. Paths resolve against `base`, the specification's directory.

    The runner never runs the peer and never fetches anything: a partner exchange happens where
    the partner is, and this is the record of it. What it refuses, the model refuses —
    a peer that is this package, an empty input set, a verdict that is not the digests'.
    """
    adapter_class = load_adapter(adapter_name)
    published = manifest(adapter_class).model_dump(mode="json")["adapter"]
    results = []
    for entry in spec.get("results") or []:
        expected = _resolve(base, entry["expected"])
        observed = _resolve(base, entry["observed"])
        for label, path in (("expected", expected), ("observed", observed)):
            if not path.is_file():
                raise ValueError(f"{label} output {path} is not a file")
        expected_sha, observed_sha = digest(expected)[0], digest(observed)[0]
        results.append(ExerciseResult(
            direction=entry["direction"], command=entry["command"],
            expected_sha256=expected_sha, observed_sha256=observed_sha,
            verdict=AGREE if expected_sha == observed_sha else DIFFER,
            note=entry.get("note", "")))
    peer = spec.get("peer") or {}
    return ExerciseReport(
        evidence_schema_version=EVIDENCE_SCHEMA_VERSION,
        adapter_id=published["id"], adapter_version=published["adapter_version"],
        category=spec.get("category", ""),
        performed_at=times.render(now or _dt.datetime.now(_dt.timezone.utc)),
        this_side=Party(implementation="synapse-cdm", version=PACKAGE_VERSION),
        peer=Party(implementation=peer.get("implementation", ""),
                   version=peer.get("version", "")),
        edition=spec.get("edition", ""), profile=spec.get("profile"),
        inputs=[_hashed_input(base, entry) for entry in spec.get("inputs") or []],
        directions=list(spec.get("directions") or []),
        results=results,
        limitations=list(spec.get("limitations") or []),
        environment={"python": _python_version(), "platform": sysconfig.get_platform(),
                     **{str(k): str(v) for k, v in (spec.get("environment") or {}).items()}},
        snapshot=snapshot(),
    )


def exercise_path(out_dir: pathlib.Path, report: ExerciseReport, slug: str) -> pathlib.Path:
    if not slug or not all(ch.isalnum() or ch in "-_" for ch in slug):
        raise ValueError(f"slug {slug!r}: letters, digits, '-' and '_' only")
    return (out_dir / report.adapter_id / report.adapter_version / EXERCISES_DIR
            / f"{slug}.json")


def write_exercise(report: ExerciseReport, out_dir: pathlib.Path, slug: str) -> pathlib.Path:
    path = exercise_path(out_dir, report, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical.serialise(report.model_dump(mode="json")))
    return path


def serialise(record: EvidenceRecord) -> str:
    """ARCHITECTURE.md §6.2's one serialisation — `canonical.serialise` — over the record."""
    return canonical.serialise(record.model_dump(mode="json"))


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

    A `[]` segment in a path means "every element of this list". NO ENTRY IN `MASKED` USES ONE
    TODAY (round PB, 2026-09-08, removed the only one by removing the field it named), and the
    segment is kept because it is part of the path language `also=` accepts and because the
    alternative — a mask that cannot reach inside a list — is what forced `compare` to collapse
    lists in the first place. A path whose shape the record does not have is silently a no-op,
    deliberately: a mask that RAISED when its field was absent would make `compare` fail on a
    truncated record instead of reporting the truncation.
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
    """Every field that differs, excluding `MASKED`, `ENVIRONMENT` and a dirty `source_commit`.

    Lists are compared as whole values rather than element-wise: `fixture_hashes` differing by
    one entry is one finding about the fixture set, and 733 findings about 733 files would bury
    it. The masking happens BEFORE that collapse, which is why it is a rewrite of the payload
    rather than a filter over flattened keys — a value inside a list cannot be excluded by name
    once the list has become one leaf.

    The environment fields are excluded here and reported by `environment_differences`, so a
    caller can print what differed without a difference there ever counting as a problem (§36).
    """
    also = ("source_commit",) if (recorded.get("source_commit", "").endswith("-dirty")
                                  or fresh.get("source_commit", "").endswith("-dirty")) else ()
    also = (*ENVIRONMENT, *also)
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


def environment_differences(recorded: dict, fresh: dict) -> list[str]:
    """The `ENVIRONMENT` fields on which the two records differ, one line each, never a problem.

    Printed by `verify` after its verdict so a reader can see that a record made on one host was
    reproduced on another — which is the claim §36 is for — without the difference between the
    hosts ever failing the reproduction.
    """
    left, right = _flatten(recorded), _flatten(fresh)
    return [f"{key}: record says {left.get(key)!r}, this tree gives {right.get(key)!r}"
            for key in ENVIRONMENT if left.get(key) != right.get(key)]


def verify(path: pathlib.Path) -> tuple[list[str], str]:
    """Re-derive the record at `path` and report every unmasked difference.

    Returns (problems, what was masked). Re-hashes every fixture and re-runs the suite: the
    point is not to read the record back, which proves nothing, but to produce a new one from
    this tree and compare. The second element names the `ENVIRONMENT` fields too, as recorded
    and not compared; `environment_differences` says which of them actually differed.
    """
    problems, said, _environment = reproduce(path)
    return problems, said


def reproduce(path: pathlib.Path) -> tuple[list[str], str, list[str]]:
    """`verify` with its third reading: (problems, what was masked, environment differences).

    One generation serves all three, because a second `generate` for the environment lines
    would double the cost of every `verify` for a difference that is never a problem.
    """
    recorded = json.loads(path.read_text())
    adapter_id = recorded["adapter"]["adapter"]["id"]
    # F07: the reports the record cites are re-read from beside it, and a cited report that is
    # missing or changed is a problem in its own words — `compare` would also see the category
    # flip to ABSENT, but the file is what a reader has to go and look at.
    problems = []
    for name, reading in (recorded.get("evidence_categories") or {}).items():
        for source in reading.get("sources") or []:
            cited = path.parent / source["path"]
            if not cited.is_file():
                problems.append(f"evidence_categories.{name}.sources: {source['path']} is "
                                "cited and not beside the record")
            elif digest(cited)[0] != source["sha256"]:
                problems.append(f"evidence_categories.{name}.sources: {source['path']} does "
                                "not hash to what the record cites")
    exercises = path.parent / EXERCISES_DIR
    fresh = generate(adapter_id, exercises=exercises).model_dump(mode="json")
    said = list(MASKED)
    if recorded.get("source_commit", "").endswith("-dirty") or \
            fresh.get("source_commit", "").endswith("-dirty"):
        said.append("source_commit (the tree is dirty, so no commit describes it; "
                    "`snapshot` is compared instead)")
    said.append(f"environment: {', '.join(ENVIRONMENT)} (recorded, not compared)")
    problems.extend(compare(recorded, fresh))
    return problems, ", ".join(said), environment_differences(recorded, fresh)


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
        # F02: "yes" needs the LEDGER — every source leaf bound to a destination and a rule
        # with nothing LOST. A clean reading that rests on the value-presence heuristic alone
        # is "heuristic", amber: measured, not proven. A red reading is a measured failure.
        book = loss.get("ledger") or {}
        proven = (book.get("basis") == "ledger"
                  and not (book.get("counts") or {}).get("LOST", 1))
        if not clean:
            message, colour = "no", _RED
        elif proven:
            message, colour = "yes", _GREEN
        else:
            message, colour = "heuristic", _AMBER
        out["lossless-verified"] = _badge("Lossless Verified", message, colour)
    provenance = record.get("fixture_provenance") or {}
    if "fixtures" in provenance and "synthetic" in provenance:
        every = provenance["fixtures"] and provenance["fixtures"] == provenance["synthetic"]
        out["synthetic-fixtures"] = _badge("Synthetic Fixtures", "all" if every else "not all",
                                           _GREEN if every else _RED)
    readings = record.get("evidence_categories")
    if isinstance(readings, dict):
        # F07: the external categories PRESENT, by name, or "none". Amber and not red — an
        # absence is the honest reading for every adapter here today, not a measured failure.
        present = [c.value for c in EXTERNAL_CATEGORIES
                   if (readings.get(c.value) or {}).get("status") == CategoryStatus.PRESENT.value]
        out["independent-evidence"] = _badge(
            "Independent Evidence", ", ".join(present) if present else "none",
            _GREEN if present else _AMBER)
    return out


def repository_badges(records: Iterable[dict]) -> dict[str, dict]:
    """The repository-level set: the same seven, over the whole roster, worst-case per badge.

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
            path.write_text(canonical.serialise(badge))
            written.append(path)
    for slug, badge in sorted(repository_badges(records.values()).items()):
        path = out_dir / "repository" / f"{slug}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical.serialise(badge))
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
    gen.add_argument("--exercises", type=pathlib.Path, default=None,
                     help="a directory of exercise reports for --adapter; default "
                          f"<--out>/<adapter>/<version>/{EXERCISES_DIR} when it exists")

    check = actions.add_parser("verify", help="re-derive a record from this tree and compare")
    check.add_argument("file", type=pathlib.Path, nargs="+")

    run = actions.add_parser("exercise", help="write an F07 exercise report from a specification")
    run.add_argument("--adapter", required=True, help="registered name")
    run.add_argument("--spec", type=pathlib.Path, required=True,
                     help="JSON: category, peer{implementation,version}, edition, profile, "
                          "inputs[{path,provenance,authorised_by}], directions, "
                          "results[{direction,command,expected,observed,note}], limitations")
    run.add_argument("--slug", required=True, help="the report's file name, without .json")
    run.add_argument("--out", type=pathlib.Path, default=pathlib.Path("evidence"))

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
            problems, masked, environment = reproduce(path)
            for problem in problems:
                print(f"{path}: {problem}", file=sys.stderr)
            print(f"{'DIFFERS' if problems else 'REPRODUCED'}: {path} "
                  f"(masked: {masked})")
            # To stdout, after the verdict and never affecting it: a record from another host
            # reproducing here is the reading §36 exists for, and the host is worth naming.
            for line in environment:
                print(f"  environment differs, not compared — {line}")
            failed += 1 if problems else 0
        return EXIT_FAILED if failed else EXIT_OK

    if args.action == "exercise":
        if not args.spec.is_file():
            print(f"synapse evidence: {args.spec} does not exist", file=sys.stderr)
            return EXIT_USAGE
        try:
            spec = json.loads(args.spec.read_text(encoding="utf-8"))
            report = exercise(args.adapter, spec, base=args.spec.resolve().parent)
            written = write_exercise(report, args.out, args.slug)
        except (LookupError, ValueError, KeyError) as e:
            print(f"synapse evidence: exercise refused — {e}", file=sys.stderr)
            return EXIT_USAGE
        agreed = sum(1 for r in report.results if r.verdict == AGREE)
        print(f"wrote {written} ({report.category.value}; {agreed} of {len(report.results)} "
              "direction(s) AGREE)")
        return EXIT_OK

    if not args.all and not args.adapter:
        parser.error("generate needs --adapter <name> or --all")
    if args.all and args.fixtures:
        parser.error("--fixtures names one directory and --all runs the whole roster")
    if args.all and args.exercises:
        parser.error("--exercises names one adapter's directory and --all runs the whole roster")
    names = sorted(shipped()) if args.all else [args.adapter]
    for name in names:
        try:
            exercises = args.exercises
            if exercises is None:
                meta = manifest(load_adapter(name)).adapter
                exercises = args.out / meta.id / meta.adapter_version / EXERCISES_DIR
            record = generate(name, fixtures=args.fixtures, exercises=exercises)
        except LookupError as e:
            print(f"synapse evidence: {e}", file=sys.stderr)
            return EXIT_USAGE
        except ValueError as e:
            print(f"synapse evidence: {e}", file=sys.stderr)
            return EXIT_FAILED
        print(f"wrote {write(record, args.out)}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
