"""The SC CESMO Internal Exchange 1.0 schema: the module literal, the published copy and the kit.

`adapters/cesmo_internal_codec.py` carries the kit's `cesmo-internal-1.0.schema.json` as the
literal `SCHEMA`, because the wheel has no `schemas/` directory; the repository publishes the same
file at `schemas/cesmo_internal/cesmo-internal-1.0.schema.json`, byte-identical to the kit's. This
module holds the three equal: the literal to the published copy key for key and in order, and the
published copy to the SHA-256 and size the kit's own `SHA256SUMS.txt` states, which the fixture
set's pin record carries (the kit is never read: it is not in this repository).

REPOSITORY-BOUND: `schemas/cesmo_internal/` at the repository root, which the wheel does not carry.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import jsonschema
import synapse_cdm
from synapse_cdm.adapters.cesmo_internal_codec import SCHEMA, VALIDATOR

ROOT = pathlib.Path(__file__).resolve().parent.parent
PUBLISHED = ROOT / "schemas" / "cesmo_internal" / "cesmo-internal-1.0.schema.json"
PIN = (
    pathlib.Path(synapse_cdm.__file__).resolve().parent
    / "fixtures"
    / "cesmo_internal"
    / "spec"
    / "cesmo_internal_pin.json"
)
#: The kit's SHA256SUMS.txt line for the schema (4 October 2026).
KIT_SHA256 = "daa02a5817c3f1c6a317b3733e5aac308cb837befbbb8c08c1b9af2833488531"


def test_the_published_copy_is_the_kits_file():
    octets = PUBLISHED.read_bytes()
    assert hashlib.sha256(octets).hexdigest() == KIT_SHA256
    assert len(octets) == 5692
    pin = {f["file"]: f for f in json.loads(PIN.read_bytes())["files"]}
    assert pin["cesmo-internal-1.0.schema.json"]["sha256"] == KIT_SHA256
    assert pin["cesmo-internal-1.0.schema.json"]["bytes"] == 5692


def test_the_module_literal_is_the_published_copy_key_for_key_and_in_order():
    published = json.loads(PUBLISHED.read_bytes())
    assert published == SCHEMA
    assert json.dumps(published) == json.dumps(SCHEMA)
    assert published["$id"] == "urn:sc:cesmo:internal:1.0"
    assert published["title"] == "SC CESMO internal exchange only - not an AEDP-13 wire schema"


def test_the_schema_is_a_valid_2020_12_schema_and_the_validator_reads_it():
    jsonschema.Draft202012Validator.check_schema(SCHEMA)
    assert VALIDATOR.schema is SCHEMA


def test_every_published_schema_directory_is_one_the_tree_documents():
    """The published copy sits beside the link16_gateway contract schemas, not among the CDM's
    own top-level `*.schema.json` (which carry `x-cdm-schema-version`)."""
    assert sorted(p.name for p in PUBLISHED.parent.iterdir()) == ["cesmo-internal-1.0.schema.json"]
    assert "x-cdm-schema-version" not in SCHEMA
