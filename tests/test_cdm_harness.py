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
