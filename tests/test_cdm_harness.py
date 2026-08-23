"""The harness itself. It is the gate every future adapter passes, so it needs its own gate.

The tests that matter most are the NEGATIVE ones: a harness that reports PASS on a lossy
adapter, on a schema-violating one, or on a non-deterministic one is worse than no harness,
because it converts an unchecked adapter into a certified one.
"""
import json
import pathlib
import uuid

import pytest

from synapse_cdm import harness, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters.pntmap import PntmapAdapter
from synapse_cdm.enums import Affiliation, EntityType
import synapse_cdm
from synapse_cdm.models import Entity

# The package lives under packages/cdm/ while this suite sits at the repo root, so its
# internal files are located through the import system rather than by walking up from
# this file: a relative hop between the two breaks the moment either one moves, and this
# way the files checked are the ones belonging to the package that is actually importable.
FIXTURES = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures" / "pntmap"


def _adapter(cls=PntmapAdapter):
    return cls(clock=times.frozen_clock())


def test_the_reference_adapter_passes_every_check():
    report = harness.run(_adapter(), FIXTURES)
    assert report["failed"] == 0, harness.render_report(report)
    assert report["passed"] >= 3, "the brief asks for at least three fixtures"
    for result in report["results"]:
        assert result["checks"] == {"translate": "PASS", "schema": "PASS",
                                    "provenance": "PASS", "lossless": "PASS",
                                    "roundtrip": "SKIP", "golden": "PASS"}


def test_the_report_renders_and_names_the_adapter_and_its_transforms():
    text = harness.render_report(harness.run(_adapter(), FIXTURES))
    assert "pntmap 1.0.0 (ingest)" in text
    assert "alert_time" in text, "declared transforms must be visible on every run"
    assert "4 passed, 0 failed" in text


def test_it_validates_against_the_published_schemas_on_disk():
    """The published files are what non-Python consumers read, so they are what get tested."""
    schemas_dir = pathlib.Path(__file__).resolve().parents[1] / "schemas"
    report = harness.run(_adapter(), FIXTURES, schema_dir=schemas_dir)
    assert report["failed"] == 0
    assert str(schemas_dir) in report["schemas"]


# --- the negative cases ----------------------------------------------------------------------

class _LossyAdapter(Adapter):
    """Drops everything except the alert id. A plausible-looking adapter that loses data."""
    name = "test_lossy"
    version = "0.1.0"
    direction = "ingest"
    system = "PNTMAP"

    def to_cdm(self, raw):
        return [Entity(source=self.source_ref(),
                       source_ids=[{"system": "PNTMAP", "external_id": raw["alert_id"]}],
                       entity_id=uuid.uuid4(), entity_type=EntityType.INTERFERENCE_SOURCE,
                       affiliation=Affiliation.UNKNOWN, valid_from=raw["alert_time"])]


class _CrashingAdapter(_LossyAdapter):
    name = "test_crashing"

    def to_cdm(self, raw):
        raise RuntimeError("upstream shape changed")


def test_a_lossy_adapter_fails_the_lossless_check():
    report = harness.run(_adapter(_LossyAdapter), FIXTURES)
    assert report["failed"] == len(report["results"])
    problems = "\n".join(p for r in report["results"] for p in r["problems"])
    assert "appears nowhere in the CDM output" in problems
    assert "signal_strength_dbm" in problems or "severity" in problems


def test_a_crashing_adapter_fails_only_its_own_fixtures_and_the_run_continues():
    """The harness that dies at case five reports the other nineteen as failures untested."""
    report = harness.run(_adapter(_CrashingAdapter), FIXTURES)
    assert len(report["results"]) == 4, "every fixture must still be judged"
    for result in report["results"]:
        assert result["checks"]["translate"] == "FAIL"
        assert result["checks"]["schema"] == "SKIP", "an unrun check must not read as passed"
        assert "upstream shape changed" in " ".join(result["problems"])
        assert "traceback" in result


def test_golden_drift_is_caught_and_localised(tmp_path):
    """A changed translation must fail with the PATH that changed, not just 'not equal'."""
    fixture = tmp_path / "one.json"
    fixture.write_text((FIXTURES / "jamming_gulf_of_riga.json").read_text())
    golden_dir = tmp_path / "golden"
    golden_dir.mkdir()
    good = harness.run(_adapter(), tmp_path, update_golden=True)
    assert good["results"][0]["checks"]["golden"] == "WROTE"

    recorded = json.loads((golden_dir / "one.cdm.json").read_text())
    recorded[0]["affiliation"] = "FRIENDLY"
    (golden_dir / "one.cdm.json").write_text(json.dumps(recorded, indent=2, sort_keys=True))

    drifted = harness.run(_adapter(), tmp_path)
    assert drifted["failed"] == 1
    problems = " ".join(drifted["results"][0]["problems"])
    assert "[0].affiliation: 'FRIENDLY' -> 'HOSTILE'" in problems


def test_a_missing_golden_file_is_skip_not_pass(tmp_path):
    (tmp_path / "one.json").write_text((FIXTURES / "jamming_gulf_of_riga.json").read_text())
    report = harness.run(_adapter(), tmp_path)
    assert report["results"][0]["checks"]["golden"] == "SKIP"
    assert "--update-golden" in " ".join(report["results"][0]["problems"])


def test_a_non_json_fixture_skips_the_lossless_check_loudly(tmp_path):
    (tmp_path / "cot.xml").write_bytes(b"<event uid='X'/>")
    report = harness.run(_adapter(_CrashingAdapter), tmp_path)
    assert report["results"][0]["checks"]["lossless"] == "SKIP"


def test_the_cli_exits_non_zero_on_failure(capsys):
    code = harness.main(["--adapter", "synapse_cdm.adapters.pntmap:PntmapAdapter",
                         "--fixtures", str(FIXTURES)])
    assert code == 0
    assert "4 passed, 0 failed" in capsys.readouterr().out

    # `__name__`, not the path spelled out: the string the harness resolves is this very
    # module, and a hardcoded copy of its own dotted name is a second source of truth that
    # goes stale the moment the suite is laid out differently.
    code = harness.main(["--adapter", f"{__name__}:_LossyAdapter",
                         "--fixtures", str(FIXTURES)])
    assert code == 1


def test_the_cli_emits_a_machine_readable_report(capsys):
    """The adapter factory reads this, so it has to be JSON and it has to be complete."""
    harness.main(["--adapter", "pntmap", "--fixtures", str(FIXTURES), "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["adapter"]["name"] == "pntmap"
    assert report["passed"] == 4 and report["failed"] == 0
    assert set(report["results"][0]["checks"]) == {
        "translate", "schema", "provenance", "lossless", "roundtrip", "golden"}


def test_the_frozen_clock_is_the_default_so_two_runs_agree():
    first = harness.run(_adapter(), FIXTURES)
    second = harness.run(_adapter(), FIXTURES)
    assert first["results"] == second["results"]


# --- the round-trip check --------------------------------------------------------------------

class _RoundTripAdapter(PntmapAdapter):
    """A bidirectional PNTMAP adapter, for exercising the round-trip check itself.

    It reconstructs the source payload out of the CDM objects. Not shipped as a real adapter —
    PNTMAP is an ingest feed and there is nothing to push back to it — but the check has to be
    proven working before the TAK adapter relies on it.
    """
    name = "test_roundtrip"
    direction = "bidirectional"

    def from_cdm(self, objects):
        entity, event = objects
        payload = dict(entity.attributes.get("source_extras", {}))
        emitter = payload.pop("emitter", {})
        payload["alert_id"] = event.source_ids[0].external_id
        payload["alert_time"] = times.render(event.observed_at)
        payload["severity"] = event.severity.value.lower()
        payload["interference"] = {
            "type": entity.attributes.get("interference_type"),
            "band": event.payload.get("frequency_band"),
            "signal_strength_dbm": event.payload.get("signal_strength_dbm"),
            "confidence": entity.confidence,
            **event.payload.get("source_extras", {}),
        }
        payload["emitter"] = dict(emitter)
        if entity.source_ids[0].external_id != payload["alert_id"]:
            payload["emitter"]["emitter_id"] = entity.source_ids[0].external_id
        if entity.position is not None:
            payload["emitter"].update({"lat": entity.position.lat, "lon": entity.position.lon,
                                       "accuracy_m": entity.position.accuracy_m})
        if entity.valid_to is not None:
            payload["valid_until"] = times.render(entity.valid_to)
        if event.geometry is not None:
            payload["affected_area"] = event.geometry.model_dump(mode="json")
        return payload


class _DroppingRoundTripAdapter(_RoundTripAdapter):
    name = "test_roundtrip_dropping"

    def from_cdm(self, objects):
        payload = super().from_cdm(objects)
        payload["emitter"].pop("attribution", None)      # loses the attribution on the way out
        return payload


def test_roundtrip_passes_when_nothing_is_lost_on_the_way_out():
    report = harness.run(_adapter(_RoundTripAdapter), FIXTURES)
    for result in report["results"]:
        assert result["checks"]["roundtrip"] == "PASS", result["problems"]


def test_roundtrip_catches_a_value_lost_on_egress():
    report = harness.run(_adapter(_DroppingRoundTripAdapter), FIXTURES)
    failed = [r for r in report["results"] if r["checks"]["roundtrip"] == "FAIL"]
    assert failed, "a dropped attribution must fail the round trip"
    assert "attribution" in " ".join(failed[0]["problems"])


def test_roundtrip_is_skip_for_an_ingest_only_adapter_never_pass():
    report = harness.run(_adapter(), FIXTURES)
    assert {r["checks"]["roundtrip"] for r in report["results"]} == {"SKIP"}


class _BrokenEgressAdapter(_RoundTripAdapter):
    name = "test_broken_egress"

    def from_cdm(self, objects):
        raise NotImplementedError("not written yet")


def test_a_declared_egress_that_raises_fails_rather_than_skipping():
    report = harness.run(_adapter(_BrokenEgressAdapter), FIXTURES)
    assert all(r["checks"]["roundtrip"] == "FAIL" for r in report["results"])
    assert "NotImplementedError" in " ".join(report["results"][0]["problems"])


def test_a_fixture_directory_may_document_itself(tmp_path):
    """`README.md` is skipped, and skipped BY NAME rather than by extension.

    A fixture directory that explains what each payload is there to catch is right, and for a
    binary format it is close to mandatory: an armoured AIS payload cannot carry a comment the
    way a CoT fixture's XML can, so the prose has to live in a file beside it. Without this the
    README is replayed as a payload and the adapter fails its own gate on a document.

    Only that one name. A format whose payloads really are Markdown must still be replayable,
    which is why this is not a `*.md` exclusion — an extension rule would quietly make one
    class of adapter untestable to spare another a filename.
    """
    (tmp_path / "README.md").write_text("# what these fixtures are for\n")
    (tmp_path / "notes.md").write_text("not the README\n")
    report = harness.run(_adapter(), tmp_path)

    replayed = {r["fixture"] for r in report["results"]}
    assert "README.md" not in replayed
    assert "notes.md" in replayed, (
        "only README.md is skipped; any other .md file is a payload like any other"
    )


# ------------------------------------------------------- a run that exercises nothing FAILS
#
# The three shapes below are one failure wearing three costumes, and all three used to be
# survivable: an absent directory raised a bare `FileNotFoundError` naming neither the adapter
# nor the pattern, and an empty or subdirectory-only one printed "0 passed, 0 failed" and exited
# 0. The last of those is the dangerous one, because it is indistinguishable in a sweep from a
# run that judged everything. `--adapter stanag4676 --fixtures fixtures/stanag4676` was the real
# instance: that directory holds only `spec/`, the fixtures are in `fixtures/nits`, and a
# nine-adapter gate sweep reported nine greens with one of them having replayed nothing.

EMPTY_CASES = ("absent", "empty", "subdirectory-only")


def _empty_case(tmp_path: pathlib.Path, shape: str) -> pathlib.Path:
    """Idempotent, because the tests below call it twice — once to run, once to assert the path."""
    target = tmp_path / "fixtures"
    if shape == "absent":
        return target                      # never created
    target.mkdir(exist_ok=True)
    if shape == "subdirectory-only":
        (target / "spec").mkdir(exist_ok=True)
        (target / "spec" / "nato-something-edition-a.pdf").write_bytes(b"%PDF-1.7 not a fixture")
    return target


@pytest.mark.parametrize("shape", EMPTY_CASES)
def test_a_run_that_matches_no_fixture_raises_rather_than_reporting_a_pass(tmp_path, shape):
    """`run()` raises, so the check is in front of every caller and not only the CLI.

    Asserted as an exception rather than as a report field on purpose: a report is a claim that
    fixtures were judged, so there must be no well-formed report for a run that judged none. A
    caller who catches this gets to decide what to do; a caller who does not gets a traceback,
    which is the correct outcome for a verification run that verified nothing.
    """
    with pytest.raises(harness.NoFixturesFound) as caught:
        harness.run(_adapter(), _empty_case(tmp_path, shape))
    message = str(caught.value)
    # All three things a reader needs at the moment of failure: which run, where, and why.
    assert "'pntmap'" in message, "the message must name the ADAPTER — a sweep runs nine of them"
    assert str(_empty_case(tmp_path, shape)) in message, \
        "the message must name the DIRECTORY SEARCHED, which is the thing that is usually wrong"
    assert harness.FIXTURE_PATTERN in message, \
        "the message must quote the PATTERN that matched nothing, or the reader cannot tell " \
        "whether their files were skipped or absent"
    assert "FAILURE rather than a pass" in message, \
        "the message says outright that this is not a pass, because the old behaviour was one"


def test_a_subdirectory_only_directory_says_where_the_content_actually_is(tmp_path):
    """The `spec/`-only case is the one that bit, so it gets the extra line that solves it.

    "exists, 1 entry, none of them a fixture" is true and unhelpful; naming `spec/` and saying
    the harness does not recurse is what turns the failure into a fix. Pinned standards live in
    `spec/` beside `build_fixtures.py` for every adapter that has them, so this shape is a caller
    one level too high rather than an empty repository.
    """
    with pytest.raises(harness.NoFixturesFound) as caught:
        harness.run(_adapter(), _empty_case(tmp_path, "subdirectory-only"))
    message = str(caught.value)
    assert "spec/" in message, "the subdirectory that DOES hold something has to be named"
    assert "does not recurse" in message, \
        "the reason the content was not found has to be stated, or `spec/` beside 'no fixtures' " \
        "reads as a harness bug"
    assert "pinned standards live in spec/, fixtures do not" in message, \
        "the convention is what tells the caller this is the wrong directory and not an empty one"


def test_the_absent_directory_is_the_same_failure_and_says_so(tmp_path):
    """Absent and empty mean the same thing — nothing was exercised — so they share an exit code.

    Distinguishing them would be distinguishing two ways of proving nothing. The message still
    says which shape it was, because "DOES NOT EXIST" and "exists, 0 entries" send the reader to
    different fixes.
    """
    with pytest.raises(harness.NoFixturesFound) as caught:
        harness.run(_adapter(), _empty_case(tmp_path, "absent"))
    assert "DOES NOT EXIST" in str(caught.value)
    # And it is NOT a bare FileNotFoundError any more, which named neither adapter nor pattern.
    assert not isinstance(caught.value, FileNotFoundError)


@pytest.mark.parametrize("shape", EMPTY_CASES)
def test_the_cli_exits_with_a_distinct_code_and_writes_the_message_to_stderr(
        tmp_path, capsys, shape):
    """Exit 2, not 1, and stderr, not a report.

    2 rather than 1 because the two mean different things: 1 says fixtures ran and some failed,
    2 says the invocation was wrong. A caller told "1" debugs an adapter; a caller told "2" fixes
    a path. Both are non-zero, so any gate testing for zero still catches it.
    """
    code = harness.main(["--adapter", "pntmap",
                         "--fixtures", str(_empty_case(tmp_path, shape)), "--json"])
    assert code == harness.EXIT_NO_FIXTURES == 2, \
        "a vacuous run must not exit 0, and must be distinguishable from a fixture failure"
    captured = capsys.readouterr()
    assert "no fixtures found" in captured.err, "the message belongs on stderr"
    assert captured.out == "", \
        "--json must emit NOTHING for a run that did not happen: a well-formed report is a " \
        "claim that fixtures were judged, and a machine reading one would record a green"


def test_the_nine_shipped_adapters_all_have_a_real_fixture_directory():
    """The sweep the gate runs, as a test, so the directory names stop being folklore.

    This is the other half of the fix. Making a vacuous run fail loudly stops a wrong path from
    passing; this stops the wrong path from being typed, by pinning the adapter-name-to-fixture-
    directory map that the `stanag4676` / `nits` mismatch made a trap. Every entry is exercised
    for real — `harness.run` would raise on any that were not.
    """
    root = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures"
    expected = {"adsb": "adsb", "ais": "ais", "cat021": "cat021", "cat048": "cat048",
                "gmti": "gmti", "legion": "legion", "pntmap": "pntmap",
                "stanag4676": "nits", "tak": "tak"}
    from synapse_cdm import adapter as adapter_module
    shipped = {n for n, c in adapter_module.discover().items()
               if c.__module__.startswith("synapse_cdm.adapters.")}
    assert shipped == set(expected), (
        f"the shipped roster changed: {shipped ^ set(expected)}. A new adapter needs its fixture "
        "directory added here, and the name of that directory is not always the adapter's name"
    )
    for name, directory in sorted(expected.items()):
        path = root / directory
        assert path.is_dir(), f"{name}: {path} is not a directory"
        files = [p for p in path.iterdir() if p.is_file() and p.name != "README.md"
                 and not p.name.startswith(".")]
        assert files, (
            f"{name}: {path} holds no fixture files, so any harness run against it exercises "
            "nothing. If the fixtures moved, fix the map in this test"
        )
