"""The published JSON Schemas are a copy of the models, so a test has to forbid drift.

Same reasoning as tests/test_instruction_files_agree.py: a second copy of a contract is
allowed to exist only when something mechanical keeps it identical. Without this test the
files under /schemas are a snapshot of whenever somebody last remembered to re-export, and a
Go consumer validating against them would reject objects the Python side happily produces.
"""
import json
import pathlib

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
    assert schema["$id"].endswith(f"{path.name}")


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
