"""Evidence records, the loss report, fixture provenance and the badges (§31–§36).

FOUR THINGS ARE PROVED HERE AND EACH ONE HAS A FAILURE MODE THAT IS INVISIBLE WITHOUT IT.

An evidence record's failure mode is a record that reproduces because nothing in it was
measured — so `verify` is exercised against a MUTATED record as well as against a fresh one,
and the mutation has to be reported.

The loss report's failure mode is a classifier whose categories overlap, so that a dropped
field lands somewhere reassuring. One synthetic adapter exercises all six categories at once,
and the arithmetic that ties DROPPED to the harness's own `unrepresented()` is asserted per
adapter rather than argued in a docstring.

Fixture provenance's failure mode is a check that skips when the record is missing. §33's "once
migration is complete" is this round, so every rule is proved RED as well as green: the tests
below construct a directory that breaks each rule in turn and require the finding.

A badge's failure mode is a badge that keeps rendering after the thing it described stopped
being measured. So the absent-not-red rule gets its own test per badge.
"""
import json
import pathlib
import re

import pytest

import synapse_cdm
from synapse_cdm import (evidence, harness, ids, lossless, manifest, suite, times,
                         version)
from synapse_cdm.adapter import Adapter, fixture_root, packaged_fixtures, roster
from synapse_cdm.enums import Affiliation, EntityType
from synapse_cdm.models import Entity

from tests import probe_metadata

PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
REPO = PACKAGE.parents[2]
ROOT = fixture_root()


def shipped() -> dict:
    """The adapters this PACKAGE ships, not everything the registry holds (test_cdm_suite.py)."""
    return {name: cls for name, cls in roster().items()
            if cls.__module__.startswith("synapse_cdm.adapters.")}


# ============================================================ §33: the provenance records

def test_the_covered_set_is_derived_from_the_tree_and_is_the_set_the_records_are_in():
    """Which directories §33 reaches, taken as a reading rather than as a list.

    A hard-coded roster of directories is the defect this repository has written gates against
    more than once: the list goes stale, and the family added last is the one nobody covered.
    """
    covered = evidence.covered_directories(ROOT)
    names = {d.relative_to(ROOT).as_posix() for d in covered}
    assert len(covered) == len(names), "a directory is covered twice"
    for directory in covered:
        assert evidence.provenance_path(directory).is_file(), \
            f"{directory.relative_to(ROOT)} is covered by §33 and has no record"
        assert evidence.harness_selects(directory), \
            f"{directory.relative_to(ROOT)} is covered and holds no fixture, so it should not be"


def test_fft_is_the_one_fixture_directory_with_no_record_and_the_reason_is_readable():
    """The exemption §33's own brief names, asserted as a reading of the tree.

    `fixtures/fft` holds a README and a `spec/` pin record and no payload: the harness selects
    NOTHING there. A provenance record listing zero fixtures would be a file asserting nothing,
    and its absence is what says the directory is not a fixture family.
    """
    fft = ROOT / "fft"
    assert fft.is_dir(), "fixtures/fft has moved; this exemption needs re-reading"
    assert evidence.harness_selects(fft) == [], (
        f"fixtures/fft now holds {len(evidence.harness_selects(fft))} selectable file(s), so it "
        "is a fixture family and §33 reaches it")
    assert not evidence.provenance_path(fft).is_file()
    assert fft not in evidence.covered_directories(ROOT)


def test_no_record_is_written_into_a_golden_or_a_spec_directory():
    """The two directory kinds §33 must NOT reach, and both are repository untouchables.

    `golden/` holds an adapter's OUTPUT over a fixture that is already covered, and `spec/` holds
    pinned specification records with a gate of their own (`gates/pin_paths.py`) and a tracked
    extension inventory. A file added to either would move a figure this repository re-derives
    every round.
    """
    stray = sorted(p.relative_to(ROOT).as_posix()
                   for p in ROOT.rglob(harness.PROVENANCE_FILE)
                   if harness.GOLDEN_DIR in p.parts or "spec" in p.parts)
    assert not stray, f"provenance records in untouchable directories: {stray}"


def test_every_record_lists_every_fixture_and_no_fixture_it_does_not_have():
    """§33's rule, unconditionally, over the whole tree. This is the gate, not a sample."""
    assert evidence.provenance_problems(ROOT) == []


def test_every_fixture_in_this_repository_declares_itself_synthetic_and_public():
    """Pre-ruled default 5, read off the records rather than off a README sentence.

    Three fixture directories — `pntmap`, `stanag4586`, `tak` — have no README at all, so the
    README's stance cannot be the evidence for them. The records are.
    """
    total = 0
    for directory in evidence.covered_directories(ROOT):
        for entry in evidence.read_provenance(directory).fixtures:
            total += 1
            assert entry.synthetic is True
            assert entry.classification == "PUBLIC"
            assert entry.operational_data is False
            assert entry.personal_data is False
    assert total == sum(len(evidence.harness_selects(d))
                        for d in evidence.covered_directories(ROOT))
    assert total > 500, f"only {total} fixtures declared; the sweep has stopped seeing the tree"


def test_every_origin_is_a_sentence_and_none_of_them_is_unknown():
    """§33's `origin`, and the one value the brief allows only with a report entry beside it."""
    unknown = []
    for directory in evidence.covered_directories(ROOT):
        for entry in evidence.read_provenance(directory).fixtures:
            assert len(entry.origin.strip()) >= 20
            if entry.origin.strip().lower().startswith("unknown"):
                unknown.append(f"{directory.relative_to(ROOT)}/{entry.file}")
    assert not unknown, (
        f"these fixtures declare an unknown origin: {unknown[:8]}. Every one of them belongs in "
        "the round report's `What remains a person's`, so this list is not allowed to grow "
        "silently")


def test_every_standard_ref_names_a_pin_record_that_exists():
    seen = 0
    for directory in evidence.covered_directories(ROOT):
        for entry in evidence.read_provenance(directory).fixtures:
            if entry.standard_ref:
                seen += 1
                assert (ROOT / entry.standard_ref).is_file()
    assert seen, "no record cites a pin; the optional field has stopped being exercised"


@pytest.fixture()
def probe_dir(tmp_path):
    """A two-fixture directory with a valid record, for the red-then-green rules below."""
    directory = tmp_path / "probe"
    directory.mkdir()
    (directory / "one.json").write_text("{}\n")
    (directory / "two.json").write_text("{}\n")
    (directory / "README.md").write_text("not a fixture\n")
    rows = [{"file": name, "synthetic": True, "classification": "PUBLIC",
             "operational_data": False, "personal_data": False,
             "origin": "Hand-written in this test module, for the rule it is proving."}
            for name in ("one.json", "two.json")]
    evidence.provenance_path(directory).write_text(json.dumps(
        {"schema_id": evidence.PROVENANCE_SCHEMA_ID, "directory": "probe", "fixtures": rows},
        indent=2, sort_keys=True) + "\n")
    return tmp_path


def _problems(root):
    return evidence.provenance_problems(root)


def test_the_provenance_check_passes_on_the_probe_before_anything_is_broken(probe_dir):
    assert _problems(probe_dir) == []


def test_a_missing_record_is_a_finding(probe_dir):
    evidence.provenance_path(probe_dir / "probe").unlink()
    assert any("no PROVENANCE.json" in p for p in _problems(probe_dir))


def test_a_fixture_on_disk_and_not_in_the_record_is_a_finding(probe_dir):
    (probe_dir / "probe" / "three.json").write_text("{}\n")
    assert any("three.json: on disk and not in" in p for p in _problems(probe_dir))


def test_a_record_naming_a_file_that_is_not_there_is_a_finding(probe_dir):
    (probe_dir / "probe" / "two.json").unlink()
    assert any("lists two.json, which is not there" in p for p in _problems(probe_dir))


def test_a_non_synthetic_fixture_is_a_finding(probe_dir):
    path = evidence.provenance_path(probe_dir / "probe")
    payload = json.loads(path.read_text())
    payload["fixtures"][0]["synthetic"] = False
    path.write_text(json.dumps(payload))
    assert any("synthetic is False" in p for p in _problems(probe_dir))


def test_a_classification_other_than_public_is_a_finding(probe_dir):
    path = evidence.provenance_path(probe_dir / "probe")
    payload = json.loads(path.read_text())
    payload["fixtures"][1]["classification"] = "CONTROLLED"
    path.write_text(json.dumps(payload))
    assert any("is not 'PUBLIC'" in p for p in _problems(probe_dir))


def test_an_unreadable_or_foreign_record_is_a_finding_and_not_a_crash(probe_dir):
    path = evidence.provenance_path(probe_dir / "probe")
    payload = json.loads(path.read_text())
    payload["schema_id"] = "somebody.else/v9"
    path.write_text(json.dumps(payload))
    assert any("is not a valid record" in p for p in _problems(probe_dir))


def test_the_harness_and_the_suite_both_stop_selecting_the_record(probe_dir):
    """One rule, two modules, and they are compared rather than left to agree by habit."""
    directory = probe_dir / "probe"
    assert harness.PROVENANCE_FILE in harness.FIXTURE_PATTERN
    assert {p.name for p in suite._fixtures(directory)} == {"one.json", "two.json"}
    for adapter_dir in evidence.covered_directories(ROOT):
        assert {p.name for p in suite._fixtures(adapter_dir)} == \
            {p.name for p in evidence.harness_selects(adapter_dir)}


def test_the_shipped_fixture_counts_are_unchanged_by_the_new_exclusion():
    """The number the harness selects is what it was before §33's records landed: 538."""
    total = sum(len(harness_paths) for harness_paths in
                (evidence.harness_selects(ROOT / name) for name in sorted(
                    p.name for p in ROOT.iterdir() if p.is_dir())))
    assert total == 538, f"the harness now selects {total} top-level fixtures, not 538"


# ================================================================= §34: the six categories

class _SixCategories(Adapter):
    """One adapter that produces all six of §34's categories from one payload.

    Built rather than found, because no shipped adapter produces DERIVED or UNSUPPORTED today —
    check D passes for all fourteen and none of them declares a machine-readable exception — so
    a test that only ran on the roster would leave two of the six categories unproved.
    """

    name = "six-categories"
    version = "1.0.0"
    direction = "ingest"
    system = "PROBE"
    fixture_dir = None
    #: `speed_kt` is NORMALIZED (a plain reason) and `heading_from` is DERIVED (the `derived:`
    #: marker M pre-ruled as the mechanism, in the reason string of the map that already exists).
    TRANSFORMS = {"speed_kt": "knots to metres per second",
                  "heading_from": "derived: computed from two positions"}
    metadata = probe_metadata(
        "six-categories", version="1.0.0",
        limitations=[
            "a plain sentence, which contributes nothing to the classifier by design",
            manifest.Limitation(id="no-vendor-block", summary="the vendor block is not mapped",
                                unsupported_paths=["vendor"],
                                severity="low", notes="§34's explicit documented exception"),
        ],
    )

    def to_cdm(self, raw):
        return [Entity(
            entity_id=ids.derive(self.system, str(raw["callsign"]), kind="entity"),
            source_ids=[{"system": self.system, "external_id": str(raw["callsign"])}],
            entity_type=EntityType.UNKNOWN, affiliation=Affiliation.UNKNOWN,
            valid_from=self.now(), source=self.source_ref(),
            attributes={"source_extras": {"note": raw["note"]}},
        )]


_PAYLOAD = {
    "callsign": "PROBE-1",       # PRESERVED — the value is in `name`
    "speed_kt": 120,             # NORMALIZED — declared in TRANSFORMS with a plain reason
    "heading_from": "two fixes",  # DERIVED    — declared with the `derived:` marker
    "note": "parked here",       # RESIDUAL   — reaches `attributes.source_extras`
    "vendor": {"firmware": "9.9"},  # UNSUPPORTED — a structured Limitation declares the path
    "orphan": "nowhere at all",  # DROPPED    — none of the above
}


def _six() -> lossless.LossReport:
    adapter = _SixCategories(clock=times.frozen_clock())
    objects = [obj.model_dump(mode="json") for obj in adapter.to_cdm(_PAYLOAD)]
    return lossless.classify(_PAYLOAD, objects, _SixCategories.TRANSFORMS,
                             manifest.unsupported_paths(_SixCategories.metadata.limitations))


def test_all_six_categories_are_reachable_and_each_holds_the_path_it_should():
    report = _six()
    assert report.PRESERVED == ("callsign",)
    assert report.NORMALIZED == ("speed_kt",)
    assert report.DERIVED == ("heading_from",)
    assert report.RESIDUAL == ("note",)
    assert report.UNSUPPORTED == ("vendor.firmware",)
    assert report.DROPPED == ("orphan",)
    assert report.total == 6


def test_the_categories_are_a_partition_and_not_six_overlapping_lists():
    report = _six()
    seen = [path for name in lossless.CATEGORIES for path in getattr(report, name)]
    assert len(seen) == len(set(seen)), f"a path is in two categories: {sorted(seen)}"
    assert lossless.CATEGORIES == ("PRESERVED", "NORMALIZED", "DERIVED", "RESIDUAL",
                                   "UNSUPPORTED", "DROPPED")


def test_derived_is_the_transforms_marker_and_not_a_second_map():
    """M's pre-ruled default 2, asserted on the mechanism rather than on the outcome."""
    assert not hasattr(_SixCategories, "DERIVATIONS")
    assert lossless.DERIVED_MARKER == "derived:"
    plain = dict(_SixCategories.TRANSFORMS, heading_from="computed from two positions")
    adapter = _SixCategories(clock=times.frozen_clock())
    objects = [obj.model_dump(mode="json") for obj in adapter.to_cdm(_PAYLOAD)]
    without = lossless.classify(_PAYLOAD, objects, plain)
    assert without.DERIVED == () and "heading_from" in without.NORMALIZED


def test_unsupported_comes_only_from_a_structured_limitation():
    """A prose limitation contributes nothing, which is §34's whole reason for the new shape."""
    assert manifest.unsupported_paths(_SixCategories.metadata.limitations) == ("vendor",)
    assert manifest.unsupported_paths(["a sentence", "another sentence"]) == ()
    adapter = _SixCategories(clock=times.frozen_clock())
    objects = [obj.model_dump(mode="json") for obj in adapter.to_cdm(_PAYLOAD)]
    undeclared = lossless.classify(_PAYLOAD, objects, _SixCategories.TRANSFORMS)
    assert undeclared.UNSUPPORTED == ()
    assert "vendor.firmware" in undeclared.DROPPED


@pytest.mark.parametrize("name", sorted(shipped()))
def test_dropped_is_exactly_the_harness_check_d_set_minus_the_declared_exceptions(name):
    """The arithmetic that ties the new classifier to the check that already gates the roster.

    If these two ever disagreed, `--strict` and check D would be two answers to one question and
    a reader would have to pick. They cannot disagree by construction, and this is where that is
    measured — on every shipped adapter, on every classifiable fixture.
    """
    cls = shipped()[name]
    adapter = cls(clock=times.frozen_clock())
    declared = manifest.unsupported_paths(adapter.metadata.limitations)
    checked = 0
    for path in evidence.harness_selects(packaged_fixtures(cls)):
        raw = harness.load_raw(path)
        if not isinstance(raw, (dict, list)):
            continue
        objects = [obj.model_dump(mode="json") for obj in adapter.to_cdm(raw)]
        report = lossless.classify(raw, objects, cls.TRANSFORMS, declared)
        missing = set(lossless.unrepresented(raw, objects, cls.TRANSFORMS))
        assert set(report.DROPPED) == missing - set(report.UNSUPPORTED)
        checked += 1
    assert checked or name in ("adsb", "ais"), f"{name}: nothing was classified"


@pytest.mark.parametrize("name", sorted(shipped()))
def test_no_shipped_adapter_drops_a_source_value(name):
    """The brief's STOP condition, run as a test rather than taken once in a round report."""
    cls = shipped()[name]
    report = suite.run(cls(clock=times.frozen_clock()), packaged_fixtures(cls))
    assert report["loss_report"]["counts"]["DROPPED"] == 0, \
        report["loss_report"]["paths"]["DROPPED"][:8]


def test_the_suite_carries_the_loss_report_in_json_and_six_lines_in_text():
    cls = shipped()["pntmap"]
    report = suite.run(cls(clock=times.frozen_clock()), packaged_fixtures(cls))
    loss = report["loss_report"]
    assert set(loss["counts"]) == set(lossless.CATEGORIES)
    assert loss["total"] == sum(loss["counts"].values())
    assert set(loss) >= {"paths", "counts", "total", "fixtures", "unsupported_declared"}
    lines = suite.loss_lines(loss)
    assert len(lines) == 6
    text = suite.render_report(report)
    for name in lossless.CATEGORIES:
        assert name in text


def test_strict_is_implied_by_require_d_and_is_what_fails_on_a_dropped_path():
    """F4.4's default, and the case that makes `--strict` different from check D's verdict."""
    cls = shipped()["pntmap"]
    report = suite.run(cls(clock=times.frozen_clock()), packaged_fixtures(cls))
    assert suite.exit_status(report, ("D",), strict=True) == suite.EXIT_OK
    report["loss_report"]["counts"]["DROPPED"] = 1
    assert suite.exit_status(report, ("D",), strict=True) == suite.EXIT_FAILED
    assert suite.exit_status(report, ("D",), strict=False) == suite.EXIT_OK
    assert suite.exit_status(report, (), strict=False) == suite.EXIT_OK


def test_the_cli_turns_require_d_into_strict_without_being_told():
    assert suite.main(["conformance", "run", "--adapter", "pntmap", "--require", "D",
                       "--format", "json"]) == suite.EXIT_OK


# ==================================================================== §32/§36: the record

@pytest.fixture(scope="module")
def record() -> evidence.EvidenceRecord:
    return evidence.generate("pntmap")


def test_the_record_carries_every_field_section_32_names(record):
    payload = record.model_dump(mode="json")
    for field in ("adapter", "source_commit", "package_version", "cdm_version", "sc_oes_version",
                  "adapter_api_version", "manifest_version", "evidence_schema_version",
                  "test_run", "conformance", "loss_report", "fixture_hashes", "artifact_hashes",
                  "generated_at", "generator"):
        assert field in payload, field
    for field in ("command", "exit", "passed", "failed", "skipped", "duration_s", "python",
                  "platform"):
        assert field in payload["test_run"], field
    assert set(payload["generator"]) == {"package_version", "command"}


def test_the_version_axes_in_the_record_are_the_constants_and_not_copies(record):
    assert record.package_version == version.PACKAGE_VERSION
    assert record.cdm_version == version.SCHEMA_VERSION
    assert record.sc_oes_version == version.SC_OES_VERSION
    assert record.adapter_api_version == version.ADAPTER_API_VERSION
    assert record.manifest_version == version.MANIFEST_SCHEMA_VERSION
    assert record.evidence_schema_version == version.EVIDENCE_SCHEMA_VERSION


def test_the_embedded_manifest_is_the_published_one(record):
    published = json.loads((REPO / "manifests" / "pntmap.json").read_text())
    assert record.adapter == published


def test_the_conformance_block_is_the_suites_own_report_verbatim(record):
    fresh = suite.run(shipped()["pntmap"](clock=times.frozen_clock()),
                      packaged_fixtures(shipped()["pntmap"]))
    assert record.conformance == fresh
    assert record.loss_report == fresh["loss_report"]


def test_every_fixture_the_suite_read_is_hashed_with_a_relative_path(record):
    paths = {entry.path for entry in record.fixture_hashes}
    assert paths, "no fixture was hashed"
    for entry in record.fixture_hashes:
        assert not entry.path.startswith("/"), "an absolute path makes the record machine-local"
        assert len(entry.sha256) == 64
        assert (ROOT / entry.path).is_file()
        assert (ROOT / entry.path).stat().st_size == entry.bytes
    assert any("/golden/" in p for p in paths), "the goldens are not hashed"
    assert any("/malformed/" in p for p in paths), "the malformed payloads are not hashed"
    assert not any(p.endswith(harness.PROVENANCE_FILE) or p.endswith("README.md")
                   for p in paths), "a file the suite does not read is in fixture_hashes"


def test_the_artifact_hashes_are_empty_until_a_release_names_something(record):
    """§32: "MAY initially be empty". PR is the round that fills it."""
    assert record.artifact_hashes == []


#: The clause in an adapter's `limitations` that states the field's value in words. The prose and
#: the boolean are two statements of one fact, and the round that flipped the boolean (PE) found
#: fourteen sentences still saying the opposite — which is why the agreement is asserted rather
#: than reviewed. Deliberately loose about the rest of the sentence: it binds the WORD after
#: "is", not the wording around it, so a later round may rewrite the reason without this check
#: either breaking or going vacuous.
AVAILABILITY_CLAIM = re.compile(r"`evidence\.available` is (true|false)\b")


def _limitation_text(entry) -> str:
    """One `limitations` element as prose. M's ruling of 2026-09-07 made the list heterogeneous."""
    return entry if isinstance(entry, str) else entry.summary


def test_evidence_available_is_true_on_every_shipped_adapter():
    """P4's condition, discharged: the records are attached to a published Release.

    M's ruling of 2026-09-08 was that producible is not available, and the field stayed false
    through P4-P8 for that reason. What made it true is not this package: `evidence-2.1.2.tar.gz`
    is an asset of the `v2.1.2` Release, so a consumer who cannot run the harness can still fetch
    the records. See PUBLICATION.md entry 19 and MIGRATIONS.md's PE record.
    """
    declared = {name: cls.metadata.evidence.available for name, cls in shipped().items()}
    assert len(declared) == 14, f"the shipped roster is {sorted(declared)}, not the fourteen"
    assert set(declared.values()) == {True}, \
        f"these adapters still deny available evidence: {[n for n, v in declared.items() if not v]}"


def test_the_field_the_prose_and_the_manifest_all_state_the_same_availability():
    """Three copies of one fact, held together mechanically so they cannot drift apart again.

    The failure this refuses is the one PE was written to repair: the boolean and the sentence
    beside it disagreeing, with the generated manifest carrying both. It is an AGREEMENT check
    and not a `True` check on purpose — the test above is what pins the value, and this one keeps
    working whichever way a later ruling moves it.
    """
    offenders = []
    for name, cls in sorted(shipped().items()):
        declared = cls.metadata.evidence.available
        published = json.loads((REPO / "manifests" / f"{name}.json").read_text())
        if published["adapter"]["evidence"]["available"] != declared:
            offenders.append(f"{name}: manifests/{name}.json says "
                             f"{published['adapter']['evidence']['available']}, the module says "
                             f"{declared}")
        said = [m.group(1) for entry in cls.metadata.limitations
                for m in AVAILABILITY_CLAIM.finditer(_limitation_text(entry))]
        if said != [str(declared).lower()]:
            offenders.append(f"{name}: the limitations state {said} where the field is {declared}"
                             " — exactly one limitation says the field's value in words")
    assert not offenders, "the field, its prose and its manifest disagree:\n  " + \
        "\n  ".join(offenders)


def test_the_availability_claim_pattern_can_see_the_sentences_it_reads():
    """A pattern matching nothing would make the agreement above green on fourteen silences."""
    assert AVAILABILITY_CLAIM.findall("`evidence.available` is true because the records") == \
        ["true"], "the pattern no longer recognises the sentence the fourteen adapters carry"
    assert AVAILABILITY_CLAIM.findall(
        "`evidence.available` is false for that reason and not because the checks do not run") == \
        ["false"], "the pattern no longer recognises the sentence those fourteen carried before"
    assert AVAILABILITY_CLAIM.findall("evidence is available to anyone who asks") == [], \
        "the pattern matches prose that states no value, so the agreement check reads noise"


def test_the_record_validates_against_its_own_published_schema(record):
    import jsonschema
    schema = json.loads((REPO / "schemas" / "evidence" / "evidence.schema.json").read_text())
    jsonschema.validate(record.model_dump(mode="json"), schema)
    assert schema["x-evidence-schema-version"] == version.EVIDENCE_SCHEMA_VERSION


def test_the_published_evidence_schema_is_not_stale():
    from synapse_cdm import schemas
    assert schemas.check(REPO / "schemas") == []
    assert schemas.EVIDENCE_STEM == "evidence/evidence"


def test_two_records_generated_from_this_tree_differ_only_in_the_masked_fields():
    """§36's reproducibility, as an assertion rather than as a paragraph."""
    first = evidence.generate("pntmap").model_dump(mode="json")
    second = evidence.generate("pntmap").model_dump(mode="json")
    assert evidence.compare(first, second) == []
    assert set(evidence.MASKED) == {"generated_at", "test_run.duration_s"}


def test_the_refusal_list_needs_no_mask_because_it_carries_no_wall_clock_reading():
    """What replaced the one masked field that lived inside a list (round PB, 2026-09-08).

    Round P4's §36 proof found it: two generations from one fresh clone differed in exactly one
    field, and it was `stanag4676`'s second refusal reading `0.0` and then `0.0001`. It was
    masked. M ruled on 2026-09-08 that a mask is the wrong repair — `evidence.compare` was not
    the only consumer, and the two tests that compare `--format json`'s BYTES do so unmasked —
    so `suite.py` stopped writing the reading and publishes the outcome of the bound instead.

    The assertion is therefore the absence, plus the two deterministic fields that took its
    place, plus the reason it can be an absence: two generations of one adapter's refusal list
    are equal WITHOUT any masking at all.
    """
    record = evidence.generate("stanag4676").model_dump(mode="json")
    details = record["conformance"]["checks"]["H"]["details"]
    refusals = details["refusals"]
    assert refusals
    assert all("seconds" not in r for r in refusals)
    assert all(isinstance(r["over_time_bound"], bool) for r in refusals)
    assert details["timeout_s"] == suite.DEFAULT_TIMEOUT_S
    # No mask, no sentinel: the list survives `masked()` unchanged, which is the whole claim.
    assert evidence.masked(record)["conformance"]["checks"]["H"]["details"]["refusals"] == refusals
    again = evidence.generate("stanag4676").model_dump(mode="json")
    assert again["conformance"]["checks"]["H"]["details"] == details


def test_the_mask_still_reaches_inside_a_list_when_a_caller_names_one():
    """`MASKED` uses no `[]` path today; `also=` can, and `compare` depends on that reach.

    Kept as a test of the mechanism rather than of a field, because the day some later round
    finds a second value inside a list, the repair it reaches for has to still work — and the
    two properties that made the old mask correct are the ones nothing else exercises: it
    rewrites a COPY, and it leaves the siblings of the masked key alone.
    """
    record = evidence.generate("stanag4676").model_dump(mode="json")
    path = "conformance.checks.H.details.refusals[].fixture"
    before = [dict(r) for r in record["conformance"]["checks"]["H"]["details"]["refusals"]]
    hidden = evidence.masked(record, also=(path,))
    refusals = hidden["conformance"]["checks"]["H"]["details"]["refusals"]
    assert refusals and all(r["fixture"] == evidence.MASK_SENTINEL for r in refusals)
    assert [r["exception"] for r in refusals] == [r["exception"] for r in before]
    # The ORIGINAL is untouched: a mask that mutated its input would corrupt the record on its
    # way to disk.
    assert record["conformance"]["checks"]["H"]["details"]["refusals"] == before


def test_no_unmasked_wall_clock_reading_has_appeared_anywhere_in_a_record():
    """The self-policing half, because a mask list is only as good as its completeness.

    Sweeps every leaf of a record for a key that names a duration and requires it to be either
    masked or explicitly accounted for here. A new timing field added to the suite's report by
    some later round would otherwise reach the record, make §36 unsatisfiable, and be diagnosed
    as "verify is flaky" rather than as what it is.
    """
    record = evidence.masked(evidence.generate("stanag4676").model_dump(mode="json"))

    def walk(node, path=""):
        if isinstance(node, dict):
            for key, value in node.items():
                yield from walk(value, f"{path}.{key}" if path else key)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                yield from walk(value, f"{path}[{index}]")
        else:
            yield path, node

    #: Names that hold a BOUND (a declaration, identical on every machine) rather than a
    #: measurement. `timeout_s` is the five-second ceiling check H is run under, and it is a
    #: parameter of the run, not a reading taken during it.
    declared = {"timeout_s"}
    live = [f"{path} = {value!r}" for path, value in walk(record)
            if path.rsplit(".", 1)[-1] in ("seconds", "duration_s", "elapsed", "elapsed_s")
            and path.rsplit(".", 1)[-1] not in declared
            and value != evidence.MASK_SENTINEL]
    assert not live, (
        f"these wall-clock readings reach an evidence record unmasked: {live}. Either mask the "
        "path in evidence.MASKED — with the reason, as the existing two carry — or take the "
        "reading out of the report. An unmasked one makes `verify` fail at random")


def test_verify_reproduces_a_freshly_written_record(tmp_path, record):
    path = evidence.write(record, tmp_path)
    assert path == tmp_path / "pntmap" / "1.0.0" / "evidence.json"
    problems, masked = evidence.verify(path)
    assert problems == []
    assert "generated_at" in masked


def test_verify_reports_a_mutated_record_rather_than_accepting_it(tmp_path, record):
    """The test that makes the one above mean something."""
    path = evidence.write(record, tmp_path)
    payload = json.loads(path.read_text())
    payload["cdm_version"] = "0.0.1"
    payload["fixture_hashes"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    problems, _ = evidence.verify(path)
    assert any("cdm_version" in p for p in problems), problems
    assert any("fixture_hashes" in p for p in problems), problems


def test_a_dirty_tree_masks_the_commit_and_says_so(record):
    dirty = record.model_dump(mode="json")
    dirty["source_commit"] = "abc123-dirty"
    clean = record.model_dump(mode="json")
    clean["source_commit"] = "def456"
    assert evidence.compare(dirty, clean) == []


def test_the_record_is_serialised_in_the_one_form_architecture_md_froze(record):
    text = evidence.serialise(record)
    assert text.endswith("\n")
    assert text == json.dumps(record.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def test_the_generator_names_itself_and_the_package_version(record):
    assert record.generator.package_version == version.PACKAGE_VERSION
    assert "synapse_cdm.evidence" in record.generator.command
    assert "--adapter pntmap" in record.generator.command


def test_generating_the_whole_roster_writes_one_record_per_adapter(tmp_path):
    assert evidence.main(["generate", "--all", "--out", str(tmp_path)]) == 0
    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("evidence.json"))
    assert len(written) == len(shipped()) == 14
    for name, cls in shipped().items():
        assert f"{name}/{cls.metadata.adapter_version}/evidence.json" in written


def test_the_provenance_summary_is_what_grounds_the_synthetic_badge(record):
    summary = record.fixture_provenance
    assert summary.fixtures == summary.synthetic
    assert summary.classifications == ["PUBLIC"]
    assert "pntmap" in summary.directories and "pntmap/malformed" in summary.directories


# ============================================================================ §35: badges

def _badge_record() -> dict:
    return evidence.generate("pntmap").model_dump(mode="json")


def test_the_six_badges_are_the_six_and_each_is_a_shields_endpoint():
    made = evidence.badges(_badge_record())
    assert set(made) == {"sc-cdm-compatible", "conformance-level", "roundtrip-verified",
                         "deterministic", "lossless-verified", "synthetic-fixtures"}
    for slug, badge in made.items():
        assert set(badge) == {"schemaVersion", "label", "message", "color"}, slug
        assert badge["schemaVersion"] == 1


@pytest.mark.parametrize("slug,field", [
    ("sc-cdm-compatible", ("conformance", "result")),
    ("conformance-level", ("conformance", "maturity_eligible")),
    ("roundtrip-verified", ("conformance", "checks", "E")),
    ("deterministic", ("conformance", "checks", "G")),
    ("lossless-verified", ("loss_report", "counts")),
    ("synthetic-fixtures", ("fixture_provenance", "synthetic")),
])
def test_a_badge_whose_grounding_field_is_absent_is_absent_and_not_red(slug, field):
    """§35's rule, per badge. ABSENT — not red, not grey, not "unknown".

    A red badge is a claim that the thing was measured and failed. A badge for a field that is
    not in the record has measured nothing, and rendering anything at all would be the failure
    mode a badge system actually has: a picture that outlives its evidence.
    """
    payload = _badge_record()
    assert slug in evidence.badges(payload), "the positive case has stopped working"
    node = payload
    for key in field[:-1]:
        node = node[key]
    del node[field[-1]]
    assert slug not in evidence.badges(payload), f"{slug} survived the removal of {field}"


def test_no_badge_can_be_hand_set_because_none_of_them_takes_a_message():
    """The rule §35 states, asserted on the SHAPE of the code rather than on its output."""
    import inspect
    source = inspect.getsource(evidence.badges)
    assert "record" in inspect.signature(evidence.badges).parameters
    assert len(inspect.signature(evidence.badges).parameters) == 1, \
        "badges() takes a second argument, so a caller can now influence what it says"
    assert "_badge(" in source


def test_the_repository_set_is_the_worst_reading_and_not_the_best():
    good = _badge_record()
    bad = json.loads(json.dumps(good))
    bad["conformance"]["result"] = "NON-CONFORMANT"
    bad["conformance"]["maturity_eligible"] = "L1"
    combined = evidence.repository_badges([good, bad])
    assert combined["sc-cdm-compatible"]["message"] == "no"
    assert combined["conformance-level"]["message"] == "L1"


def test_a_badge_absent_from_one_record_is_absent_from_the_repository_set():
    good = _badge_record()
    partial = json.loads(json.dumps(good))
    del partial["fixture_provenance"]["synthetic"]
    assert "synthetic-fixtures" not in evidence.repository_badges([good, partial])


def test_the_badge_command_writes_one_file_per_badge_per_adapter(tmp_path):
    assert evidence.main(["generate", "--adapter", "pntmap", "--out", str(tmp_path)]) == 0
    assert evidence.main(["badges", "--from", str(tmp_path)]) == 0
    written = sorted(p.relative_to(tmp_path / "badges").as_posix()
                     for p in (tmp_path / "badges").rglob("*.json"))
    assert "pntmap/deterministic.json" in written
    assert "repository/synthetic-fixtures.json" in written
    payload = json.loads((tmp_path / "badges" / "pntmap" / "deterministic.json").read_text())
    assert payload["label"] == "Deterministic"


def test_badges_refuses_an_empty_directory_rather_than_writing_nothing(tmp_path, capsys):
    assert evidence.main(["badges", "--from", str(tmp_path)]) == evidence.EXIT_USAGE
    assert "no evidence.json" in capsys.readouterr().err


# ============================================================== the CLI, and the one entry point

def test_synapse_evidence_and_synapse_badges_are_reachable_from_the_one_console_script():
    """ARCHITECTURE.md §8's single entry point, not a third and fourth console script."""
    assert suite.main(["evidence", "provenance"]) == 0
    parser = suite.build_parser()
    text = parser.format_help()
    assert "evidence" in text and "badges" in text


def test_evidence_generate_refuses_an_invocation_it_cannot_satisfy(capsys):
    with pytest.raises(SystemExit):
        evidence.main(["generate"])
    with pytest.raises(SystemExit):
        evidence.main(["generate", "--all", "--fixtures", "/tmp"])


def test_verify_reports_a_missing_file_as_a_usage_error(tmp_path, capsys):
    assert evidence.main(["verify", str(tmp_path / "nothing.json")]) == evidence.EXIT_USAGE
