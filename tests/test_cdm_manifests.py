"""The manifests are a generated publication of the adapters' own declarations, so a test has to
forbid drift, and §16 names six ways CI must fail that a drift check cannot see.

Same reasoning as `tests/test_cdm_schemas.py` for the JSON Schemas: a second copy of a contract
is allowed to exist only when something mechanical keeps it identical. Without the first test
below, `manifests/` is a snapshot of whenever somebody last remembered to re-export, and a
consumer choosing an adapter on its declared maturity would be choosing on a number the code
stopped agreeing with.

THE SIX CI CLAUSES OF §16, AND WHERE EACH ONE IS PROVEN
--------------------------------------------------------
    manifest missing ................ test_every_registered_adapter_has_a_manifest_and_the_reverse
                                      test_the_check_refuses_a_missing_manifest
    schema invalid .................. test_every_manifest_validates_against_the_published_schema
                                      test_the_schema_refuses_a_manifest_missing_a_required_field
    impossible direction declared ... test_an_impossible_direction_is_refused (three of them)
    unknown maturity value used ..... test_an_unknown_maturity_value_is_refused
    required limitation missing ..... test_an_empty_limitations_list_needs_a_stated_reason
    adapter version inconsistent .... `tests/test_cdm_adapter_contract.py`, at class definition —
                                      which is EARLIER than CI and is where the enforcement point
                                      belongs (`adapter.py`'s docstring: a contract checked at
                                      call time is a contract discovered in production)
"""
import json
import pathlib
import re

import jsonschema
import pytest

from synapse_cdm import adapter, harness, manifests, schemas, suite, times
from synapse_cdm.manifest import (AdapterMetadata, Capabilities, ClaimStatus, Direction,
                                  MaturityLevel)
from synapse_cdm.version import ADAPTER_API_VERSION, MANIFEST_SCHEMA_VERSION, SCHEMA_VERSION

from tests import probe_metadata

REPO = pathlib.Path(__file__).resolve().parents[1]
PUBLISHED = REPO / "manifests"
MANIFEST_SCHEMA = REPO / "schemas" / "manifests" / "adapter-manifest.schema.json"

#: The adapters this package SHIPS. Scoped exactly as `tests/test_cdm_prose_counts.py` scopes it,
#: and for the same reason: `REGISTRY` holds every double any imported test module defined.
def shipped() -> dict:
    return {name: cls for name, cls in adapter.discover().items()
            if cls.__module__.startswith("synapse_cdm.adapters.")}


# ------------------------------------------------------------------ the publication is current


def test_the_published_manifests_are_current():
    problems = manifests.check(PUBLISHED)
    assert not problems, "\n".join(problems) + (
        "\n\nRun: python -m synapse_cdm.manifests --out manifests"
    )


def test_every_registered_adapter_has_a_manifest_and_the_reverse():
    """CLOSURE, BOTH DIRECTIONS, and neither half is redundant.

    An adapter with no manifest is §16's first CI clause. A manifest with no adapter is the
    direction a `for adapter in roster()` loop cannot fail on: the file stays fetchable, and a
    consumer discovers a translator that no longer exists.
    """
    on_disk = {p.name.removesuffix(".json") for p in PUBLISHED.glob("*.json")}
    registered = set(shipped())
    assert registered == on_disk, (
        f"the roster and `manifests/` disagree.\n"
        f"  registered with no manifest: {sorted(registered - on_disk)}\n"
        f"  manifest with no adapter:    {sorted(on_disk - registered)}\n"
        "Run `python -m synapse_cdm.manifests --out manifests`; a file left behind by a removed "
        "adapter has to be deleted deliberately"
    )
    assert registered, "no adapters registered, so this closure compared two empty sets"


def test_the_check_refuses_a_missing_manifest(tmp_path):
    """The live gate, proven able to fail. A drift check nobody has seen refuse is a green light."""
    written = manifests.write(tmp_path)
    assert manifests.check(tmp_path) == []
    victim = sorted(written)[0]
    victim.unlink()
    problems = manifests.check(tmp_path)
    assert any("missing" in p and victim.name in p for p in problems), problems
    # ... and the other direction: a file for an adapter that is not registered.
    manifests.write(tmp_path)
    (tmp_path / "no_such_adapter.json").write_text("{}\n")
    assert any("orphaned" in p for p in manifests.check(tmp_path)), manifests.check(tmp_path)


# ------------------------------------------------------------------------ the schema, published


def test_the_manifest_schema_is_published_under_the_directory_the_spec_names():
    """§12: `schemas/manifests/` with a versioned adapter-manifest schema."""
    assert MANIFEST_SCHEMA.exists(), (
        f"{MANIFEST_SCHEMA.relative_to(REPO)} is missing. It is generated — run "
        "`python -m synapse_cdm.schemas --out schemas`"
    )
    schema = json.loads(MANIFEST_SCHEMA.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["x-manifest-schema-version"] == MANIFEST_SCHEMA_VERSION
    assert schema["$id"] == (
        f"urn:synapsecommand:manifest:{MANIFEST_SCHEMA_VERSION}:adapter-manifest"), schema["$id"]
    # It is a DIFFERENT contract on a DIFFERENT axis from the CDM object schemas, and the keys
    # say so rather than leaving a reader to infer it from the directory name.
    assert "x-cdm-schema-version" not in schema, (
        "the manifest schema declares a CDM schema version. The two axes are independent "
        "(`version.py`), and a manifest schema carrying the CDM's number invites exactly the "
        "derivation `version.py` forbids"
    )


def test_the_published_schema_is_what_the_models_generate_now():
    """The drift direction, through `schemas.check()` — one mechanism, not a second one here."""
    assert not schemas.check(REPO / "schemas")
    assert json.loads(MANIFEST_SCHEMA.read_text()) == schemas.manifest_schema()


@pytest.mark.parametrize("path", sorted(PUBLISHED.glob("*.json")), ids=lambda p: p.name)
def test_every_manifest_validates_against_the_published_schema(path):
    """§16's "schema invalid", against the file a non-Python consumer would actually fetch."""
    schema = json.loads(MANIFEST_SCHEMA.read_text())
    jsonschema.Draft202012Validator(schema).validate(json.loads(path.read_text()))


def test_the_schema_refuses_a_manifest_missing_a_required_field():
    """Non-vacuity: a schema that accepts anything would pass every case above."""
    schema = json.loads(MANIFEST_SCHEMA.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    good = json.loads((PUBLISHED / "pntmap.json").read_text())
    validator.validate(good)
    for field in ("schema_id", "adapter", "api", "cdm"):
        broken = dict(good)
        broken.pop(field)
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(broken)
    without_limitations = json.loads(json.dumps(good))
    without_limitations["adapter"].pop("limitations")
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(without_limitations)


# --------------------------------------------------------- the envelope states this tree's axes


@pytest.mark.parametrize("path", sorted(PUBLISHED.glob("*.json")), ids=lambda p: p.name)
def test_each_manifest_declares_the_versions_this_tree_carries(path):
    payload = json.loads(path.read_text())
    assert payload["schema_id"] == manifests.SCHEMA_ID
    assert payload["manifest_schema_version"] == MANIFEST_SCHEMA_VERSION
    assert payload["api"]["version"] == ADAPTER_API_VERSION.split(".")[0]
    assert payload["cdm"]["schema_version"] == SCHEMA_VERSION
    assert payload["cdm"]["supported"] == f"{SCHEMA_VERSION.split('.')[0]}.x"
    assert payload["adapter"]["id"] == path.name.removesuffix(".json")


# ------------------------------------------------------------- §16's impossible combinations
#
# One test per bullet, each constructing the bad metadata rather than editing a file: the
# refusal belongs to the model, so proving it against a hand-broken JSON file would prove only
# that jsonschema works.


def test_an_impossible_direction_is_refused():
    """§2's three added directions carry OBLIGATIONS, and each obligation is a refusal."""
    with pytest.raises(ValueError, match="MODEL with capabilities.wire true"):
        AdapterMetadata(**{**probe_metadata("m").model_dump(), "direction": Direction.MODEL})
    with pytest.raises(ValueError, match="TRANSPORT names no payload adapter"):
        AdapterMetadata(**{**probe_metadata("t").model_dump(),
                           "direction": Direction.TRANSPORT,
                           "capabilities": _wireless(probe_metadata("t").capabilities)})
    with pytest.raises(ValueError, match="COMPOSITE names no constituents"):
        AdapterMetadata(**{**probe_metadata("c").model_dump(),
                           "direction": Direction.COMPOSITE,
                           "capabilities": _wireless(probe_metadata("c").capabilities)})
    # And the fourth shape: a declared direction disagreeing with the capability block that says
    # which directions are exercised. Two statements of one fact, compared.
    with pytest.raises(ValueError, match="disagree"):
        AdapterMetadata(**{**probe_metadata("d", direction="bidirectional").model_dump(),
                           "direction": Direction.INGEST})


def _wireless(capabilities: Capabilities) -> dict:
    payload = capabilities.model_dump()
    payload["wire"] = False
    payload["directions_exercised"] = []
    return payload


def test_an_unknown_maturity_value_is_refused():
    """§16's "unknown maturity value used" — the enum is the refusal, and L7 is the witness."""
    with pytest.raises(ValueError):
        MaturityLevel("L7")
    with pytest.raises(ValueError):
        AdapterMetadata(**{**probe_metadata("x").model_dump(),
                           "maturity": {"level": "L7", "basis": "invented",
                                        "external_exercise": None}})


def test_l6_must_name_the_independent_system_it_was_exercised_against():
    """§3.3's prohibition, in the only form a model can carry it.

    L6 is the rung this repository cannot award itself — every fixture here is synthetic — so
    the model does not forbid L6, it forbids an L6 with nothing outside this repository behind
    it. No shipped adapter declares L6 and this is what stops one being typed.
    """
    with pytest.raises(ValueError, match="L6 with no `external_exercise`"):
        AdapterMetadata(**{**probe_metadata("x").model_dump(),
                           "maturity": {"level": "L6", "basis": "typed",
                                        "external_exercise": None}})
    assert all(cls.metadata.maturity.level is not MaturityLevel.L6 for cls in shipped().values())


def test_an_empty_limitations_list_needs_a_stated_reason():
    """§16's "required limitation field missing", and §3.1's "MUST NOT be defaulted to empty"."""
    with pytest.raises(ValueError, match="limitations is empty"):
        AdapterMetadata(**{**probe_metadata("x").model_dump(), "limitations": []})
    # An adapter genuinely audited and found to have none SAYS so, which is a different
    # statement from silence — and the model accepts that one.
    stated = AdapterMetadata(**{**probe_metadata("x").model_dump(), "limitations": [],
                                "limitations_empty_reason": "audited on such a date; none found"})
    assert stated.limitations == []


def test_a_claim_of_integration_names_the_external_system():
    """§15: INTEGRATED and DEPLOYED are about the world, and the world has a name in them."""
    for status in (ClaimStatus.INTEGRATED, ClaimStatus.DEPLOYED):
        with pytest.raises(ValueError, match="no `claim_external_system`"):
            AdapterMetadata(**{**probe_metadata("x").model_dump(), "claim_status": status.value})
    assert all(cls.metadata.claim_status is ClaimStatus.VERIFIED for cls in shipped().values()), (
        "a shipped adapter claims something other than VERIFIED. Every one of them passes this "
        "repository's public gates and none of them has been run against an independent "
        "implementation, which is exactly what VERIFIED asserts and EXERCISED does not"
    )


def test_an_absent_limit_needs_a_reason_and_a_declared_one_may_not_have_one():
    """§3.5: "a limit that does not apply MUST be declared absent with a reason"."""
    limits = probe_metadata("x").capabilities.limits.model_dump()
    from synapse_cdm.manifest import Limits
    with pytest.raises(ValueError, match="absent with no reason"):
        Limits(**{**limits, "absent_because": {}})
    with pytest.raises(ValueError, match="both declared and explained as absent"):
        Limits(**{**limits, "max_depth": 8})
    # Round P5, M's F5.4: a DECLARED bound needs a basis exactly as an absent one needs a reason.
    from synapse_cdm.manifest import LimitBasis, LimitKind
    basis = LimitBasis(kind=LimitKind.IMPLEMENTATION_CAP, source="a probe picks a number",
                       enforced_at="the base class", test="this test")
    without_absence = {k: v for k, v in limits["absent_because"].items() if k != "max_depth"}
    with pytest.raises(ValueError, match="declared with no basis"):
        Limits(**{**limits, "max_depth": 8, "absent_because": without_absence})
    with pytest.raises(ValueError, match="absent and carry a basis anyway"):
        Limits(**{**limits, "declared_because": {"max_objects": basis}})
    with pytest.raises(ValueError, match="which are not limits"):
        Limits(**{**limits, "max_depth": 8, "absent_because": without_absence,
                  "declared_because": {"max_depth": basis, "max_wombats": basis}})

    assert Limits(**{**limits, "max_depth": 8, "absent_because": without_absence,
                     "declared_because": {"max_depth": basis}}).max_depth == 8


def test_a_null_format_version_must_be_stated_as_a_limitation():
    """A null edition is a READING, and a reading a consumer cannot find is a forgotten field."""
    payload = probe_metadata("x").model_dump()
    payload["format"] = {"name": "some standard", "version": None}
    with pytest.raises(ValueError, match="format.version is null and no limitation says so"):
        AdapterMetadata(**payload)


# ------------------------------------------------- maturity is a claim about evidence (§3.6)


#: The clause in a bidirectional adapter's `maturity.basis` that names the tolerance its class
#: declares. Two statements of one fact, held together the way `tests/test_cdm_evidence.py` holds
#: `evidence.available` to its sentence: it binds the WORD in the backticks, not the prose around
#: it, so a later round may rewrite the reason without this check breaking or going vacuous.
TOLERANCE_CLAIM = re.compile(r"`(bytes|values)` tolerance \(`ROUNDTRIP_TOLERANCE`\)")

#: §3.3's rungs as an ordinal, for the one comparison the release notes state as a rule.
RUNG = {level: int(level.value[1:]) for level in MaturityLevel}


def test_no_adapter_declares_a_maturity_its_current_evidence_does_not_support():
    """THE RUNG, RE-DERIVED FROM A SUITE RUN, not read back out of the declaration.

    UNTIL 2026-09-16 THIS TEST ASSERTED THAT THE ROUNDTRIP COLUMN WAS NOT PASS, so that its own
    reasoning could not go stale in silence: the harness could not read non-JSON egress, every
    bidirectional adapter declared L4 on a round-trip test in `tests/` the suite could not see,
    and the suite computed L3 beside it. That assertion failed by design the day the harness
    began comparing the emitted octets itself under each class's `ROUNDTRIP_TOLERANCE`, and the
    rungs are derived from the column now, which is what the old message asked for.

    What the evidence supports, per adapter, and what may be declared against it:

    * `A`, `B` and `C` PASS — that is L1, L2 and L3 — and the run is CONFORMANT.
    * declared <= eligible, on the ordinal. "A declared rung above an eligible one is a defect,
      not a note" (`release_notes.py`); a declared rung BELOW is a reading, and every adapter
      here reads below, for a reason its basis states.
    * ingest-only: `E` is a DECLARED SKIP and exactly L3 is declared. There is no egress
      direction for information to be lost in, so the roundtrip rung is passed vacuously — and
      a rung passed vacuously is not a rung declared (ARCHITECTURE.md §3.6, rule 4).
    * bidirectional: `E` is PASS, from the column, and exactly L4 is declared. L5 is eligible
      for all fourteen and rests on `M` being inapplicable to every one of them — the same
      vacuous-rung reading, one rung up. The basis names the tolerance the class declares and
      cites exactly one test in `tests/` as the adapter's own statement of the claim.
    """
    schema_dir = REPO / "schemas"
    for name, cls in sorted(shipped().items()):
        # The frozen clock, because the golden check compares byte for byte against
        # files written under it — `times.py:39`. A real clock turns every golden into
        # a FAIL and the rung would read as unsupported for a reason that is the
        # test's own.
        instance = cls(clock=times.frozen_clock())
        report = suite.run(instance, adapter.packaged_fixtures(cls), schema_dir=schema_dir)
        assert report["result"] == "CONFORMANT", \
            f"{name}: the suite is not green, so no rung is supported"
        checks = report["checks"]
        for letter in "ABC":
            assert checks[letter]["verdict"] == "PASS", f"{name}: {letter} is {checks[letter]}"

        level = cls.metadata.maturity.level
        basis = cls.metadata.maturity.basis
        eligible = MaturityLevel(report["maturity_eligible"])
        assert RUNG[level] <= RUNG[eligible], (
            f"{name} declares {level.value} and the suite computes {eligible.value}. A declared "
            "rung above an eligible one is a defect, not a note"
        )
        if cls.metadata.direction is Direction.INGEST:
            assert checks["E"]["verdict"] == "SKIP" and checks["E"]["declared_inapplicable"], name
            assert level is MaturityLevel.L3, (
                f"{name} is ingest-only and declares {level.value}. There is no egress direction "
                "for information to be lost in, so the roundtrip rung is passed vacuously — and "
                "a rung passed vacuously is not a rung declared (ARCHITECTURE.md §3.6, rule 4)"
            )
            continue
        assert checks["E"]["verdict"] == "PASS", (
            f"{name}: E is {checks['E']['verdict']} — {checks['E'].get('reason')}. The harness "
            "compares egress for every emitter since 2026-09-16, and L4 rests on that column"
        )
        assert checks["E"]["details"]["fail"] == 0 and checks["E"]["details"]["pass"] >= 1, name
        assert level is MaturityLevel.L4, f"{name} is bidirectional and declares {level.value}"
        assert TOLERANCE_CLAIM.findall(basis) == [cls.ROUNDTRIP_TOLERANCE], (
            f"{name}: the basis says {TOLERANCE_CLAIM.findall(basis)} where the class declares "
            f"ROUNDTRIP_TOLERANCE {cls.ROUNDTRIP_TOLERANCE!r} — exactly one clause, agreeing"
        )
        assert f"conformance run --adapter {name}" in basis, \
            f"{name}: the basis does not name the suite command whose reading it rests on"
        cited = [token.rstrip(".,;") for token in basis.split()
                 if token.startswith("tests/") and "::" in token]
        assert len(cited) == 1, (
            f"{name} declares L4 and its `maturity.basis` cites {cited}. The adapter's OWN "
            "statement of the round-trip claim is one test, so the basis names exactly one and a "
            "reader can go and run it"
        )
        path, _, function = cited[0].partition("::")
        module = REPO / path
        assert module.exists(), f"{name}: {path} does not exist"
        assert f"def {function}(" in module.read_text(), (
            f"{name}: {path} carries no `{function}`. The rung rests on that test and the "
            "citation has gone stale, which is the figure this repository never leaves unchecked"
        )
