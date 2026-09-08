"""The published JSON Schemas are a copy of the models, so a test has to forbid drift.

Same reasoning as tests/test_instruction_files_agree.py: a second copy of a contract is
allowed to exist only when something mechanical keeps it identical. Without this test the
files under /schemas are a snapshot of whenever somebody last remembered to re-export, and a
Go consumer validating against them would reject objects the Python side happily produces.
"""
import json
import pathlib
import subprocess

import jsonschema
import pytest

from synapse_cdm import schemas
from synapse_cdm.models import KINDS
from synapse_cdm.version import SCHEMA_VERSION

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / "schemas"


def test_the_published_schemas_are_current():
    problems = schemas.check(PUBLISHED)
    assert not problems, "\n".join(problems) + (
        "\n\nRun: python -m synapse_cdm.schemas --out schemas"
    )


def test_every_kind_and_payload_is_published():
    expected = set(KINDS) | {"cdm_object", "payload_gnss_interference"}
    on_disk = {p.name.removesuffix(".schema.json") for p in PUBLISHED.glob("*.schema.json")}
    assert expected <= on_disk


@pytest.mark.parametrize("path", sorted(PUBLISHED.glob("*.schema.json")), ids=lambda p: p.name)
def test_each_schema_is_valid_json_schema_and_declares_its_version(path):
    schema = json.loads(path.read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["x-cdm-schema-version"] == SCHEMA_VERSION
    # THE FILE AND ITS `$id` MUST NAME THE SAME SCHEMA — a file whose `$id` names a different one
    # is a real defect, and that is what this line has always been for. What changed is the form
    # of the identifier: it used to end with the FILENAME, because the `$id` was a URL and the
    # last path segment was the file. It is a URN now — `urn:synapsecommand:cdm:1.0.0:entity` —
    # so the binding is to the file's STEM rather than to its name, and the version is asserted
    # inside the identifier rather than only beside it. See `schemas.BASE_ID` for why the URL was
    # wrong: it pointed at `synapsecommand.local`, which RFC 6762 reserves for link-local mDNS.
    stem = path.name.removesuffix(".schema.json")
    assert schema["$id"] == f"urn:synapsecommand:cdm:{SCHEMA_VERSION}:{stem}", (
        f"{path.name} declares $id {schema['$id']!r}; the ruled form is "
        f"urn:synapsecommand:cdm:{SCHEMA_VERSION}:{stem}"
    )
    # And it is a legal absolute URI, which is all JSON Schema requires of an `$id` — proven by
    # `check_schema` above rather than asserted here, since a malformed one fails that call.
    assert ":" in schema["$id"] and not schema["$id"].startswith("http")


def test_the_strict_timestamp_pattern_is_published_not_format_date_time():
    """A consumer must be able to enforce the fixed-millisecond form from the schema alone."""
    event = json.loads((PUBLISHED / "event.schema.json").read_text())
    assert r"\.[0-9]{3}Z$" in event["properties"]["observed_at"]["pattern"]


def test_additional_properties_are_forbidden_on_the_canonical_objects():
    for kind in KINDS:
        schema = json.loads((PUBLISHED / f"{kind}.schema.json").read_text())
        assert schema.get("additionalProperties") is False, (
            f"{kind}: a canonical object that accepts unknown keys is a dict with a docstring"
        )


# --- P3: the 2.1.0 move is ADDITIVE, and the schemas are where that is provable ----------------

#: The version keys every published schema carries. They MOVE on every schema bump by
#: construction, so comparing them against the previous tag would report the bump as a change to
#: the contract — which it is not. Excluded by name rather than by a pattern, so a third key
#: appearing is a failure rather than a silent exemption.
_VERSION_KEYS = ("$id", "x-cdm-schema-version")

#: The published stems, as `schemas.generate()` names them, minus the manifest schema — that one
#: is on a different axis (`MANIFEST_SCHEMA_VERSION`), publishes its own keys and is not part of
#: the CDM wire contract this section is about.
_CDM_STEMS = tuple(sorted(set(KINDS) | {"cdm_object", "payload_gnss_interference"}))


def _previous_tag_schema(stem):
    """The published schema as it stood at the last release tag, or None outside a checkout."""
    found = subprocess.run(["git", "show", f"v2.0.0:schemas/{stem}.schema.json"],
                           cwd=ROOT, capture_output=True, text=True)
    return json.loads(found.stdout) if found.returncode == 0 else None


def _leaves(value, path=""):
    if isinstance(value, dict):
        out = {}
        for key, sub in value.items():
            out.update(_leaves(sub, f"{path}.{key}" if path else key))
        return out
    if isinstance(value, list):
        out = {}
        for index, sub in enumerate(value):
            out.update(_leaves(sub, f"{path}[{index}]"))
        return out
    return {path: value}


@pytest.mark.parametrize("stem", _CDM_STEMS)
def test_no_published_path_was_removed_since_the_last_release(stem):
    """MIGRATIONS.md's MAJOR row, checked rather than asserted: nothing went away.

    A removed path is a field removed, an enum member removed or a type narrowed — every clause
    of the MAJOR row shows up here as a path that used to exist and does not. The round that
    declared `SCHEMA_VERSION` a MINOR is the round that has to be able to prove this.
    """
    old = _previous_tag_schema(stem)
    if old is None:
        pytest.skip("no v2.0.0 tag in this checkout")
    new = json.loads((PUBLISHED / f"{stem}.schema.json").read_text())
    gone = sorted(p for p in _leaves(old) if p not in _leaves(new)
                  and p.split(".")[-1] not in _VERSION_KEYS)
    assert gone == [], (
        f"schemas/{stem}.schema.json lost {gone} since v2.0.0. A path that disappears is "
        "MIGRATIONS.md's MAJOR row — a field removed, a type narrowed, an enum member gone — "
        "and it cannot ride in a MINOR")


@pytest.mark.parametrize("stem", _CDM_STEMS)
def test_no_pre_existing_object_gained_a_required_field_since_the_last_release(stem):
    """The MAJOR row's other clause: "an optional field made required".

    Checked separately from the sweep above because a `required` list GROWING is an addition by
    the leaf test's measure and a break by the contract's. A new model may of course require its
    own fields; what may not happen is an object that already existed demanding more.
    """
    old = _previous_tag_schema(stem)
    if old is None:
        pytest.skip("no v2.0.0 tag in this checkout")
    new = json.loads((PUBLISHED / f"{stem}.schema.json").read_text())

    def required_by_path(node, path="", out=None):
        out = {} if out is None else out
        if isinstance(node, dict):
            if isinstance(node.get("required"), list):
                out[path or "(root)"] = set(node["required"])
            for key, sub in node.items():
                required_by_path(sub, f"{path}.{key}" if path else key, out)
        elif isinstance(node, list):
            for index, sub in enumerate(node):
                required_by_path(sub, f"{path}[{index}]", out)
        return out

    before, after = required_by_path(old), required_by_path(new)
    grew = {path: sorted(after.get(path, set()) - names)
            for path, names in before.items() if after.get(path, set()) - names}
    assert grew == {}, (
        f"schemas/{stem}.schema.json made {grew} required on an object that already existed")


@pytest.mark.parametrize("stem", _CDM_STEMS)
def test_the_only_values_that_moved_since_the_last_release_are_the_ones_the_round_declared(stem):
    """Everything else is an ADDITION, so no pre-existing value may read differently.

    Two exceptions, both declared by round P3 and both stated here rather than filtered by a
    pattern: `schema_version`'s default, which IS the bump, and a `description`, which
    MIGRATIONS.md's PATCH row names in as many words.
    """
    old = _previous_tag_schema(stem)
    if old is None:
        pytest.skip("no v2.0.0 tag in this checkout")
    new = json.loads((PUBLISHED / f"{stem}.schema.json").read_text())
    before, after = _leaves(old), _leaves(new)
    moved = sorted(p for p, value in before.items()
                   if p in after and after[p] != value
                   and p.split(".")[-1] not in _VERSION_KEYS)
    undeclared = [p for p in moved
                  if not (p.endswith("properties.schema_version.default")
                          or p.split(".")[-1] == "description")]
    assert undeclared == [], (
        f"schemas/{stem}.schema.json changed {undeclared} in place. A MINOR adds; it does not "
        "restate an existing value")
