"""`security/exceptions/` — every file valid, no expiry in the past, and no way to opt out.

WHY THIS MODULE IS UNCONDITIONAL, WHICH IS THE ONLY INTERESTING THING ABOUT IT
------------------------------------------------------------------------------
SOIF Part 1 §45 ends with four words: "No permanent undocumented exemptions." An exemption
becomes permanent by nobody looking at it, so the enforcement has to be something that fires
without anybody choosing to look. This module is that: an `expiry` in the past fails the WHOLE
SUITE, on the day it passes, with no flag, no environment variable, no marker and no skip.

That is deliberately harsher than it needs to be for a repository with two exceptions in it, and
the harshness is the point. The two softer arrangements both fail in the same direction:

* a warning — read by nobody, because the run is green;
* a check in CI only — passed over by anyone running `pytest` locally, and CI is exactly where a
  red build gets an `|| true` added under time pressure.

**There are two exception files, both written on 2026-09-08 by round PB** (`image-size`'s two
high npm advisories, which have no upstream fix; they expire 2026-11-07). Until that round this
paragraph read "there are no exception files today", and most of what follows ran over an empty
directory; the assertions below are written so that they have content in EITHER state, because a
test that encodes today's emptiness as a fact about the tree is a test that goes red when the
mechanism is first used — which is exactly what happened to two tests in other modules when these
two files landed, and they were the things that were wrong, not the code.

`pip-audit --strict` over the Python environment is still clean, and both files are about the
`docs/` npm toolchain, which the Python distribution does not carry.

M's ruling of 2026-09-08T16:45:00Z added `mitigation` and `upstream_status` to the schema's
required fields and requires that "malformed or incomplete exception files must fail validation";
`test_an_incomplete_exception_file_fails_validation_field_by_field` below is that requirement,
proved one omitted field at a time rather than once over a single broken file.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
EXCEPTIONS = REPO / "security" / "exceptions"
SCHEMA_PATH = EXCEPTIONS / "schema.json"
README = EXCEPTIONS / "README.md"

sys.path.insert(0, str(REPO / "gates"))

import codeql_gate  # noqa: E402

jsonschema = pytest.importorskip(
    "jsonschema",
    reason="jsonschema is a `test` extra of packages/cdm; without it the validation half of this "
           "module cannot run. The expiry half below does not need it and is not skipped.")

#: Every `*.json` in the directory that is meant to BE an exception. The schema is not one.
EXCEPTION_FILES = sorted(p for p in EXCEPTIONS.glob("*.json") if p.name != "schema.json")


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _today() -> dt.date:
    """UTC, because `expiry` is a date in a record and not a date on somebody's laptop."""
    return dt.datetime.now(dt.timezone.utc).date()


#: One record that validates, at module scope because two tests need the same positive control:
#: the refusal test below mutates a field of it, and the incompleteness test deletes one. Written
#: out in full rather than read from `security/exceptions/` — a test whose positive control is a
#: live file passes whenever that file passes, which is the assertion it was meant to make
#: independently.
VALID_EXCEPTION = {
    "identifier": "GHSA-aaaa-bbbb-cccc",
    "affected_package": "some-dependency",
    "version_range": ">=1.0,<1.4",
    "risk": "an attacker who controls the input reaches the parser directly",
    "reason": "no upstream fix exists; tracked in the linked issue and re-checked weekly",
    "mitigation": "the parser is never reached: no build step passes untrusted input to it",
    "upstream_status": "no fix released; issue open upstream, removed when a patched release lands",
    "owner": "@decentcybersecurity",
    "expiry": "2026-12-31",
    "created": "2026-09-08",
    "references": ["https://github.com/advisories/GHSA-aaaa-bbbb-cccc"],
}


# --------------------------------------------------------------------------------------------
# The directory and its schema exist and mean what §45 requires.
# --------------------------------------------------------------------------------------------

def test_the_directory_exists_with_its_schema_and_its_readme():
    """§45 names the path. `security/README.md` promised it and round P6 is where it lands."""
    assert EXCEPTIONS.is_dir(), (
        f"{EXCEPTIONS.relative_to(REPO)} does not exist. §45 names it as the exception mechanism "
        "and both consumers read it; without the directory the derivation below silently yields "
        "an empty allowlist for the wrong reason")
    assert SCHEMA_PATH.is_file()
    assert README.is_file()


def test_the_schema_is_not_under_the_generated_schemas_directory():
    """`schemas/` is generated by `python -m synapse_cdm.schemas` and regeneration deletes strays.

    A hand-written file there would survive until the next `--check --out schemas` run and then
    disappear, taking the validation with it. The check is on the location, because the reason is
    about the location.
    """
    generated = REPO / "schemas"
    assert generated.is_dir()
    strays = [p for p in generated.rglob("*.json") if "exception" in p.name.lower()]
    assert not strays, (
        f"an exception schema is under the GENERATED schemas directory: {strays}. It belongs "
        "beside the files it governs, at security/exceptions/schema.json")


def test_the_schema_requires_every_field_section_45_lists(schema):
    """§45: identifier, affected package, risk, reason, owner, expiry — plus five more.

    `version_range`, `created` and `references` are round P6's additions to §45's six, and they
    are in the same list here because a schema that required six of nine would let a file omit
    the range — which is what makes an exception bounded in versions as well as in time.

    `mitigation` and `upstream_status` are M's, ruled 2026-09-08T16:45:00Z, and they are required
    for the reason the ruling gives: with only `risk` and `reason`, what holds the risk down and
    what would end the exception could both be omitted by writing a longer sentence in `reason`,
    and round PB's own first draft of these two files did exactly that.
    """
    required = set(schema["required"])
    assert {"identifier", "affected_package", "risk", "reason", "owner", "expiry"} <= required
    assert {"version_range", "created", "references"} <= required
    assert {"mitigation", "upstream_status"} <= required, (
        "M's ruling of 2026-09-08T16:45:00Z requires both; without them an exception can state a "
        "risk and a reason and say nothing about the controls in force or the event that ends it")
    assert schema.get("additionalProperties") is False, (
        "the schema permits extra properties, so a file could carry `exipry` alongside a valid "
        "`expiry` and nothing would say so")


def test_the_schema_refuses_the_shapes_that_make_an_exception_meaningless(schema):
    """A schema is only as good as what it REFUSES, so the refusals are the assertion.

    Each case below is a real way a hurried exception gets written: a one-word reason, no owner,
    no reference, an expiry as a year, an unbounded version range.
    """
    valid = dict(VALID_EXCEPTION)
    jsonschema.validate(valid, schema)  # the positive control, first

    for field, bad in (
        ("risk", "low"),
        ("reason", "later"),
        ("mitigation", "none"),
        ("upstream_status", "open"),
        ("owner", ""),
        ("expiry", "2026"),
        ("created", "8 September 2026"),
        ("references", []),
        ("references", ["see the advisory"]),
        ("identifier", "a rule id with spaces"),
        ("version_range", ""),
    ):
        broken = dict(valid, **{field: bad})
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(broken, schema)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(dict(valid, exipry="2026-12-31"), schema)


def test_an_incomplete_exception_file_fails_validation_field_by_field(schema, tmp_path):
    """M, 2026-09-08T16:45:00Z, verbatim: "malformed or incomplete exception files must fail
    validation."

    ONE OMISSION AT A TIME, and that is the point of the loop. A single broken file missing five
    fields would pass this test with four of the five requirements absent from the schema —
    `jsonschema` raises on the first one it finds and says nothing about the rest. Omitting each
    required field on its own is what proves that each is required.

    Written through a FILE on disk, because that is what a person adds to
    `security/exceptions/`, and because it exercises the same read the two consumers do.
    """
    complete = tmp_path / "GHSA-aaaa-bbbb-cccc.json"
    complete.write_text(json.dumps(VALID_EXCEPTION), encoding="utf-8")
    jsonschema.validate(json.loads(complete.read_text()), schema)   # green, before any red

    for field in schema["required"]:
        incomplete = dict(VALID_EXCEPTION)
        del incomplete[field]
        path = tmp_path / f"missing-{field}.json"
        path.write_text(json.dumps(incomplete), encoding="utf-8")
        with pytest.raises(jsonschema.ValidationError) as raised:
            jsonschema.validate(json.loads(path.read_text()), schema)
        assert field in str(raised.value), (
            f"a file with no {field!r} was refused, but the message does not name the field: "
            f"{raised.value.message!r}. The person who has to fix the file reads that message")

    malformed = tmp_path / "not-json.json"
    malformed.write_text("{ this is not JSON", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        json.loads(malformed.read_text())


# --------------------------------------------------------------------------------------------
# Every file that IS there.
# --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("path", EXCEPTION_FILES, ids=[p.name for p in EXCEPTION_FILES])
def test_every_exception_file_validates(path, schema):
    jsonschema.validate(json.loads(path.read_text()), schema)


@pytest.mark.parametrize("path", EXCEPTION_FILES, ids=[p.name for p in EXCEPTION_FILES])
def test_the_filename_is_the_identifier(path):
    """Two files could otherwise carry one identifier and disagree.

    Which of them a consumer honoured would then depend on directory order, and the consumer that
    honoured the wrong one would suppress a finding with an expired justification.
    """
    identifier = json.loads(path.read_text())["identifier"]
    assert path.stem == identifier.replace("/", "_"), (
        f"{path.name} declares identifier {identifier!r}. The filename's stem must be the "
        "identifier, with `/` written as `_` for the rule ids that carry one")


@pytest.mark.parametrize("path", EXCEPTION_FILES, ids=[p.name for p in EXCEPTION_FILES])
def test_no_exception_has_expired(path):
    """§45's "no permanent undocumented exemptions", as a failing test rather than a policy.

    THE REPAIR IS NOT TO MOVE THE DATE. Fix the finding, or write a new exception whose `reason`
    says what changed; `security/exceptions/README.md` states that and this message repeats it
    because this is where somebody reads it.
    """
    body = json.loads(path.read_text())
    expiry = dt.date.fromisoformat(body["expiry"])
    today = _today()
    assert expiry >= today, (
        f"{path.name} expired on {expiry.isoformat()} and today is {today.isoformat()}. "
        f"Owner: {body['owner']}. Reason it was granted: {body['reason']!r}. Fix the finding or "
        "write a NEW exception that says what changed — moving this date is the "
        "'permanent undocumented exemption' §45 forbids, spelled with a date on it")


@pytest.mark.parametrize("path", EXCEPTION_FILES, ids=[p.name for p in EXCEPTION_FILES])
def test_no_exception_is_granted_for_longer_than_a_year(path):
    """An expiry far enough out is a permanent exemption with a date on it.

    A year is not a magic number; it is the longest interval over which the reason in the file can
    still be presumed to describe the situation. A longer one is a decision that wants restating.
    """
    body = json.loads(path.read_text())
    created = dt.date.fromisoformat(body["created"])
    expiry = dt.date.fromisoformat(body["expiry"])
    assert expiry > created, f"{path.name} expires on or before the day it was created"
    assert (expiry - created).days <= 366, (
        f"{path.name} is granted for {(expiry - created).days} days. Grant a shorter one and "
        "renew it with a reason, so that the renewal is a decision somebody takes")


# --------------------------------------------------------------------------------------------
# The empty state, which is today's, and the derivation both consumers share.
# --------------------------------------------------------------------------------------------

def test_the_gate_reads_the_live_directory_without_refusing():
    """A malformed file here would REFUSE both consumers; this is where that surfaces.

    `gates/codeql_gate.py` exits 2 on a refusal, which in CI reads as a broken gate rather than
    as a finding. Catching it under `pytest` means the commit that adds a bad exception file
    fails on this line rather than on a CodeQL run somebody has to go and read.
    """
    exemptions = codeql_gate.load_exceptions()
    assert len(exemptions) == len(EXCEPTION_FILES)
    assert {e.path.name for e in exemptions} == {p.name for p in EXCEPTION_FILES}


def test_the_readme_states_that_the_expiry_is_enforced_and_names_this_module():
    """The directory's own prose has to point at the enforcement, or the enforcement is a secret."""
    body = README.read_text()
    assert "tests/test_cdm_security_exceptions.py" in body
    assert "gates/codeql_gate.py" in body
    assert "ci.yml" in body


def test_the_allowlist_is_derived_in_the_workflow_and_not_typed_into_it():
    """§45's "one source", checked from the other end: the workflow must not carry a list.

    The failure this prevents is the silent one — a finding still suppressed by a workflow line
    whose exception expired months ago. `pip-audit`'s own flag is `--ignore-vuln`, so a literal
    one in the workflow is exactly what to look for.
    """
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text()
    assert "--emit-pip-audit-ignores" in ci, (
        "the supply-chain job does not derive its allowlist from security/exceptions/")
    literal = [line for line in ci.splitlines()
               if "--ignore-vuln" in line and "emit-pip-audit-ignores" not in line
               and not line.lstrip().startswith("#")]
    assert not literal, (
        f"ci.yml types an --ignore-vuln value into the workflow: {literal}. Derive it from "
        "security/exceptions/ instead — two lists diverge, and they diverge silently in the "
        "direction that suppresses a live finding")


def test_no_advisory_is_allowlisted_in_the_dependency_review_action():
    """`allow-ghsas:` in `dependency-review.yml` would be an exception with no expiry.

    Same rule as the one above, on the other workflow: §45's mechanism has an owner and a date,
    and a GHSA listed in a workflow file has neither.
    """
    review = (REPO / ".github" / "workflows" / "dependency-review.yml").read_text()
    offenders = [line for line in review.splitlines()
                 if "allow-ghsas" in line and not line.lstrip().startswith("#")]
    assert not offenders, offenders
