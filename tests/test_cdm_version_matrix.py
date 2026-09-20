"""The writer-by-reader matrix `version.compatible()` answers for, run on the frozen contracts.

WHY THIS EXISTS
---------------
Until the audit remediation (F01, 2026-09-19) `version.compatible(written_with, read_by)` returned
`major(written) == major(read)`, and `MIGRATIONS.md` said a 1.0.0 reader "accepts a 1.2.0 object,
because MINOR additions are optional by definition". The historical schemas say otherwise: every
published CDM schema carries `additionalProperties: false`, so a 2.0.0 reader validating a 2.1.0
object that carries `quality`, `status` or `residual` — populated OR explicitly null — refuses it.
The helper promised a direction the evidence does not support, and it promised it for minors that
do not exist yet.

The evidence is `tests/frozen/cdm/`: the four object schemas as each release tag published them,
keyed by the `schema_version` they declare (the package tag is provenance only — package 2.2.0
ships CDM 2.1.0). `MANIFEST.json` records tag, commit and sha256 per file. Nothing here reads the
network or mutable `main`, and nothing edits a frozen file: a frozen schema that no longer matches
its recorded digest is a test failure, not a fixture refresh.

WHAT IS PROVED, AND WHAT IS NOT
-------------------------------
* new reader / old writer: a 2.0.0 document is ACCEPTED by the current models and the current
  schema. Demonstrated on the pasted golden of `test_cdm_models.py` and on a derived document for
  every kind.
* old reader / new writer: a current document carrying a 2.1.0 field is REFUSED by the frozen
  2.0.0 validator, whether the field is populated or `null`. The helper says REFUSED for it.
* a minor nobody has published is UNKNOWN to the helper and `compatible()` is False for it.
* the version grammar is exact: a trailing newline, a leading zero, a prefix, a suffix, a sign or
  whitespace is a `ValueError`, on either argument, never a silent `int()`.

Version eligibility is never a substitute for validating the payload: a SUPPORTED verdict says the
frozen matrix accepted documents of that shape, not that THIS document is valid.

THE 3.0.0 CONTRACT, FROZEN IN THE COMMIT THAT TYPED IT (2026-09-20)
---------------------------------------------------------------------
The current contract is a MAJOR away from the two above: F04 narrowed the PUBLISHED schema —
`pattern` on every version field and on `Entity.symbol`, `uniqueItems` on `ontology_types` — and
MIGRATIONS.md's table puts "a type narrowed" on the MAJOR row. So the within-major evidence is
now stated on the frozen pair (2.0.0 → 2.1.0), the different-major rule is stated on the current
one, and the narrowing that earned the MAJOR is shown: a document the frozen 2.1.0 schema accepts
(`"adapter_version": "banana"`, F04's own counterexample) is refused by the frozen 3.0.0 schema
and by the current one. A well-formed old document still PARSES under the current models — that
is shape, not eligibility, and the helper says REFUSED for the pair because the promise is about
every document of the contract.

CONTRACT CHANGE OF THIS MODULE, 2026-09-20 — the `SELF` provenance. A contract frozen at a
release commit is frozen IN the commit its tag names, and a file cannot carry the hash of the
commit that contains it. The 2.0.0 and 2.1.0 freezes were taken from tags that already existed,
so their provenance carries a commit; a freeze taken in the release commit records the tag and
`SELF`. What replaces the `rev-list == commit` assertion for a SELF contract is stronger, not
weaker: once the tag exists, the tagged tree's `schemas/<kind>.schema.json` AND its frozen copy
must both be the frozen bytes, and the tagged `version.py` must claim the contract. `SELF` is
admitted for the CURRENT contract only, under the tag `v{PACKAGE_VERSION}`. Without the tag,
the digest test stands, as it always has.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import subprocess

import jsonschema
import pytest

from synapse_cdm import version
from synapse_cdm.geo import LineString
from synapse_cdm.models import KINDS, OperationalStatus, Quality, Residual, TemporalValidity
from synapse_cdm.schemas import generate
from synapse_cdm.version import SCHEMA_VERSION, Direction, Verdict
from tests.test_cdm_models import GOLDEN_AT_2_0_0, T0, _entity, _event, _plan_object, _track

REPO = pathlib.Path(__file__).resolve().parents[1]
FROZEN = REPO / "tests" / "frozen" / "cdm"
MANIFEST = json.loads((FROZEN / "MANIFEST.json").read_text())
CONTRACTS = tuple(sorted(MANIFEST["contracts"]))
OLDEST, CURRENT = CONTRACTS[0], CONTRACTS[-1]
#: The newest frozen contract of the OLDEST major: the within-major pair the READER_NEWER and
#: WRITER_NEWER evidence is stated on now that CURRENT is a major away from both.
PREVIOUS = max(c for c in CONTRACTS if c.split(".")[0] == OLDEST.split(".")[0])
assert OLDEST < PREVIOUS < CURRENT, CONTRACTS
#: A freeze taken in the release commit its tag names records this instead of a commit hash.
SELF = "SELF"

BUILDERS = {"entity": _entity, "event": _event, "track": _track, "plan_object": _plan_object}

#: What the current writer can put in the properties 2.1.0 introduced. `validity` is
#: plan_object-only; the other three live on `CDMBase` and so on every kind.
POPULATED = {
    "quality": Quality(confidence=0.5),
    "status": OperationalStatus(state="ACTIVE", namespace="test"),
    "residual": Residual(namespace="test", data={"left_over": 1}),
    "validity": TemporalValidity(valid_from=T0),
}


def _frozen(contract: str, kind: str) -> dict:
    return json.loads((FROZEN / contract / f"{kind}.schema.json").read_text())


def _validator(contract: str, kind: str) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(_frozen(contract, kind))


def _current_validator(kind: str) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(generate()[kind])


def _refusals(validator, document) -> list[str]:
    return sorted(f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
                  for e in validator.iter_errors(document))


def _new_properties(kind: str) -> set[str]:
    """The top-level properties the current contract has and the oldest frozen one has not."""
    return set(_frozen(CURRENT, kind)["properties"]) - set(_frozen(OLDEST, kind)["properties"])


def _document(kind: str, **overrides) -> dict:
    """A current writer's document, without the nulls a 2.0.0 writer would not have spelled."""
    return BUILDERS[kind](**overrides).model_dump(mode="json", exclude_none=True)


def _old_document(kind: str) -> dict:
    """A document as the OLDEST frozen contract's writer would have written it: only what the
    builder set (a 2.0.0 writer never spelled `transformations: []` or `vertical: null`), plus
    the stamps every writer puts on — `object_kind`, `schema_version` and the geometry `type`
    discriminator, which `model_dump()` always emits — with `schema_version` stating the old
    contract."""
    overrides = {"geometry": LineString(type="LineString", coordinates=[[21.0, 57.0], [22.0, 58.0]])} \
        if kind == "plan_object" else {}
    document = BUILDERS[kind](**overrides).model_dump(mode="json", exclude_unset=True)
    document.update(object_kind=kind, schema_version=OLDEST)
    assert not (set(document) & _new_properties(kind))
    assert not _refusals(_validator(OLDEST, kind), document), \
        "the derived old document is not itself valid under the old contract"
    return document


# --- the frozen evidence is what it says it is -----------------------------------------------

def test_the_manifest_covers_the_four_kinds_for_every_contract():
    for contract, entry in MANIFEST["contracts"].items():
        assert set(entry["files"]) == set(KINDS), contract
        tag, commit = entry["provenance"]["tag"], entry["provenance"]["commit"]
        assert tag, contract
        if commit == SELF:
            assert contract == CURRENT, (
                f"{contract} records provenance {SELF} and is not the current contract. A freeze "
                "taken in a release commit is the current one by construction; an older contract "
                "was frozen from a tag that existed and carries that tag's commit")
            assert tag == f"v{version.PACKAGE_VERSION}", (
                f"{contract} is frozen {SELF} under {tag}, and the release commit that types "
                f"SCHEMA_VERSION {CURRENT} is the one v{version.PACKAGE_VERSION} names")
        else:
            assert re.fullmatch(r"[0-9a-f]{40}", commit), (contract, commit)


@pytest.mark.parametrize("contract", CONTRACTS)
@pytest.mark.parametrize("kind", sorted(KINDS))
def test_every_frozen_schema_matches_its_recorded_digest_and_declares_its_key(contract, kind):
    record = MANIFEST["contracts"][contract]["files"][kind]
    raw = (REPO / record["path"]).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == record["sha256"], record["path"]
    assert json.loads(raw)["properties"]["schema_version"]["default"] == contract
    assert json.loads(raw)["additionalProperties"] is False, \
        "the matrix below relies on the frozen contracts rejecting unknown properties"


@pytest.mark.parametrize("contract", CONTRACTS)
@pytest.mark.parametrize("kind", sorted(KINDS))
def test_every_frozen_schema_is_the_tagged_bytes(contract, kind):
    """Re-derived from `git show <tag>:<path>` when this checkout has the tag; the digest test
    above is what stands in a tarball. Neither branch is a skip: both assert the checksum."""
    entry = MANIFEST["contracts"][contract]
    record = entry["files"][kind]
    tag = entry["provenance"]["tag"]
    have_tag = shutil.which("git") and subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"], cwd=REPO,
        capture_output=True).returncode == 0
    if not have_tag:
        assert hashlib.sha256((REPO / record["path"]).read_bytes()).hexdigest() == record["sha256"]
        return
    shown = subprocess.check_output(["git", "show", f"{tag}:{record['source']}"], cwd=REPO)
    assert hashlib.sha256(shown).hexdigest() == record["sha256"], (tag, record["source"])
    assert shown == (REPO / record["path"]).read_bytes()
    if entry["provenance"]["commit"] == SELF:
        # The freeze was taken IN the commit the tag names, so the tagged tree must carry it —
        # the frozen copy at the tag is these bytes, and the tagged version.py claims the
        # contract. That binds the freeze to the tag's tree, which is what a commit hash would
        # have said and more.
        frozen_at_tag = subprocess.check_output(["git", "show", f"{tag}:{record['path']}"], cwd=REPO)
        assert frozen_at_tag == shown, (tag, record["path"])
        version_at_tag = subprocess.check_output(
            ["git", "show", f"{tag}:packages/cdm/synapse_cdm/version.py"], cwd=REPO, text=True)
        assert f'SCHEMA_VERSION = "{contract}"' in version_at_tag, (
            f"{tag} does not type SCHEMA_VERSION {contract}, so it is not the release commit the "
            f"{SELF} provenance names")
        return
    assert subprocess.check_output(["git", "rev-list", "-n1", tag], cwd=REPO,
                                   text=True).strip() == entry["provenance"]["commit"]


def test_the_helper_knows_exactly_the_contracts_that_are_frozen():
    """`version.KNOWN_CONTRACTS` is the helper's whole knowledge of the current major; the
    frozen directory is the evidence for it. Neither may run ahead of the other."""
    assert tuple(sorted(version.KNOWN_CONTRACTS)) == CONTRACTS
    assert SCHEMA_VERSION == CURRENT, "the current contract must be frozen before it is claimed"


# --- new reader, old writer: demonstrated ----------------------------------------------------

def test_the_pasted_two_zero_zero_golden_is_read_by_the_newer_contracts():
    """Shape: the 2.0.0 golden validates under the frozen 2.1.0 schema (the within-major
    evidence) and still parses under the current one. Eligibility is the helper's answer and
    it is REFUSED across the major — see the narrowing test below for why."""
    assert not _refusals(_validator("2.0.0", "entity"), GOLDEN_AT_2_0_0)
    assert not _refusals(_validator(PREVIOUS, "entity"), GOLDEN_AT_2_0_0)
    assert not _refusals(_current_validator("entity"), GOLDEN_AT_2_0_0)
    assert KINDS["entity"].model_validate(GOLDEN_AT_2_0_0).schema_version == "2.0.0"
    assert version.assess("2.0.0", PREVIOUS).verdict is Verdict.SUPPORTED
    assert version.assess("2.0.0", SCHEMA_VERSION).verdict is Verdict.REFUSED


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_an_old_document_of_every_kind_is_accepted_by_the_newer_reader_of_its_major(kind):
    """The READER_NEWER evidence, within major 2, on the frozen pair 2.0.0 → 2.1.0."""
    old = _old_document(kind)
    assert not _refusals(_validator(PREVIOUS, kind), old), kind
    assert version.compatible(OLDEST, PREVIOUS) is True
    result = version.assess(OLDEST, PREVIOUS)
    assert result.verdict is Verdict.SUPPORTED and result.direction is Direction.READER_NEWER
    assert "test_cdm_version_matrix" in result.basis


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_an_old_document_is_shape_readable_by_the_current_models_and_still_not_eligible(kind):
    """Since the 3.0.0 MAJOR (2026-09-20). A well-formed old document parses under the current
    models and is not rewritten; the helper still REFUSES the pair by major, in the reader-newer
    direction, because eligibility is a promise about EVERY document of the old contract and the
    narrowing test below shows one the current schema refuses."""
    old = _old_document(kind)
    assert not _refusals(_current_validator(kind), old), kind
    revived = KINDS[kind].model_validate(old)
    assert revived.schema_version == OLDEST, "not rewritten to the current version"
    for older in (OLDEST, PREVIOUS):
        result = version.assess(older, SCHEMA_VERSION)
        assert result.verdict is Verdict.REFUSED and result.direction is Direction.READER_NEWER
        assert "major" in result.basis
        assert version.compatible(older, SCHEMA_VERSION) is False


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_the_narrowing_that_made_the_current_contract_a_major_is_shown_on_the_frozen_pair(kind):
    """F04's counterexample, on the frozen bytes: `"adapter_version": "banana"` is accepted by
    the frozen 2.1.0 schema (`minLength: 1` was its whole constraint) and refused by the frozen
    3.0.0 schema and by the current one (`pattern`). That is MIGRATIONS.md's "a type narrowed"
    row — a document accepted under the published older contract becomes invalid — and it is
    why the pair is REFUSED rather than a WRITER_NEWER refinement."""
    document = _document(kind)
    document["schema_version"] = PREVIOUS
    document["source"] = dict(document["source"], adapter_version="banana")
    assert not _refusals(_validator(PREVIOUS, kind), document), \
        f"the frozen {PREVIOUS} {kind} schema refused the counterexample; the narrowing is not shown"
    for refuser in (_validator(CURRENT, kind), _current_validator(kind)):
        refusals = _refusals(refuser, dict(document, schema_version=CURRENT))
        assert any("source/adapter_version" in r and "does not match" in r for r in refusals), \
            refusals


# --- old reader, new writer: refused, and the helper says so ---------------------------------

@pytest.mark.parametrize("kind", sorted(KINDS))
def test_a_current_document_with_new_fields_populated_is_refused_by_the_old_reader(kind):
    new = _new_properties(kind)
    assert new, kind
    document = _document(kind, **{k: POPULATED[k] for k in new if k in POPULATED})
    assert new & set(document), "the document must actually carry a newer property"
    assert not _refusals(_current_validator(kind), document)
    refusals = _refusals(_validator(OLDEST, kind), document)
    assert refusals, f"the {OLDEST} {kind} schema accepted a {CURRENT} document"
    assert any("Additional properties are not allowed" in r and f"'{k}'" in r
               for r in refusals for k in new), refusals


@pytest.mark.parametrize("kind", sorted(KINDS))
def test_a_current_document_with_new_fields_explicitly_null_is_refused_by_the_old_reader(kind):
    """Null is not absence: `{"quality": null}` is a property the old reader has never heard of."""
    document = _document(kind)
    document.update({k: None for k in _new_properties(kind)})
    assert not _refusals(_current_validator(kind), document)
    KINDS[kind].model_validate(document)
    refusals = _refusals(_validator(OLDEST, kind), document)
    assert refusals, f"the {OLDEST} {kind} schema accepted explicit nulls for {CURRENT} fields"
    assert any("Additional properties are not allowed" in r and f"'{k}'" in r
               for r in refusals for k in _new_properties(kind)), refusals


def test_the_helper_does_not_promise_the_old_reader_the_new_document():
    """The reproduction: the first line was `True` before F01 (then on `(CURRENT, OLDEST)`,
    which was the within-major pair until 3.0.0)."""
    assert version.compatible(PREVIOUS, OLDEST) is False
    result = version.assess(PREVIOUS, OLDEST)
    assert result.verdict is Verdict.REFUSED and result.direction is Direction.WRITER_NEWER
    assert "additionalProperties" in result.basis
    for older in (OLDEST, PREVIOUS):
        assert version.compatible(CURRENT, older) is False
        result = version.assess(CURRENT, older)
        assert result.verdict is Verdict.REFUSED and result.direction is Direction.WRITER_NEWER
        assert "major" in result.basis


# --- the relationships nobody has evidence for ------------------------------------------------

@pytest.mark.parametrize("written,read", [
    ("3.9.0", SCHEMA_VERSION),     # a minor from the future, read by today
    (SCHEMA_VERSION, "3.9.0"),     # today's document, read by a contract not yet published
    ("2.9.0", "2.0.0"),            # an unpublished minor of the frozen major
    ("2.9.0", "2.1.0"),
])
def test_an_unpublished_minor_of_this_major_is_unknown_not_safe(written, read):
    result = version.assess(written, read)
    assert result.verdict is Verdict.UNKNOWN
    assert version.compatible(written, read) is False, "unknown is not presumed safe"


def test_the_same_minor_is_supported_whatever_the_patch():
    """A PATCH moves descriptions only (MIGRATIONS.md's table), so the shape is the same."""
    for written, read in [("2.1.3", "2.1.0"), ("2.1.0", "2.1.3"), ("2.0.0", "2.0.0"),
                          ("3.0.4", "3.0.0"), ("3.0.0", "3.0.4")]:
        result = version.assess(written, read)
        assert result.verdict is Verdict.SUPPORTED and result.direction is Direction.SAME, (written, read)
        assert version.compatible(written, read) is True


@pytest.mark.parametrize("written,read", [("1.0.0", "2.1.0"), ("2.1.0", "1.0.0"),
                                          ("3.0.0", "2.1.0"), ("2.1.0", "3.0.0"),
                                          ("2.0.0", "3.0.0"), ("3.0.0", "2.0.0")])
def test_a_different_major_is_refused_in_both_directions(written, read):
    result = version.assess(written, read)
    assert result.verdict is Verdict.REFUSED and "major" in result.basis
    assert version.compatible(written, read) is False


# --- the grammar --------------------------------------------------------------------------------

MALFORMED = ("2.1.0\n", "2.1.0\r\n", "01.0.0", "2.01.0", "v2.1.0", "2.1.0-rc1", "2.1.0+build",
             " 2.1.0", "2.1.0 ", "-1.0.0", "2.-1.0", "2.1", "2.1.0.0", "2_1_0", "", "2.1.0\t")


@pytest.mark.parametrize("bad", MALFORMED)
def test_a_malformed_version_is_refused_on_either_side(bad):
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        version.compatible(bad, SCHEMA_VERSION)
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        version.compatible(SCHEMA_VERSION, bad)
    with pytest.raises(ValueError, match="MAJOR.MINOR.PATCH"):
        version.parse(bad)


def test_a_trailing_newline_is_the_case_dollar_would_have_admitted():
    """`re.match(..., "$")` accepts "2.1.0\\n"; `fullmatch` does not. Split-and-int accepted it
    too, and answered `compatible` for it. Neither route may survive."""
    assert version.SEMVER_RE.fullmatch("2.1.0\n") is None
    assert version.SEMVER_RE.match("2.1.0\n") is not None, "the pattern without fullmatch"
    with pytest.raises(ValueError):
        version.assess("2.1.0\n", "2.1.0")


def test_the_result_is_printable_and_names_both_sides():
    text = str(version.assess("2.0.0", "2.1.0"))
    assert "2.0.0" in text and "2.1.0" in text and "SUPPORTED" in text
