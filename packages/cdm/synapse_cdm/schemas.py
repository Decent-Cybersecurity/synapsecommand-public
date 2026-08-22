"""JSON Schema export — generated from the Pydantic models, never hand-written.

WHY GENERATED
-------------
Two definitions of one contract drift, and the drift is discovered by a consumer at runtime.
The Pydantic models are the single source; the files under /schemas are a PUBLICATION of them,
for consumers that are not Python — a Go service, a TAK plugin, a validator in CI.

Because they are a publication, they can go stale the moment someone edits a model and forgets
to re-export. So `check()` compares the files on disk with what the models generate now, and
tests/test_cdm_schemas.py fails the build on a difference. That is the same gate the repository
already puts on CLAUDE.md/AGENTS.md agreement and on the agent roster: the copy is allowed to
exist only because a test makes drift impossible.

    python -m synapse_cdm.schemas --out schemas          # write/refresh
    python -m synapse_cdm.schemas --check --out schemas   # fail if stale (CI)
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from pydantic import BaseModel, TypeAdapter

from synapse_cdm.models import KINDS, PAYLOAD_MODELS, CDMObject
from synapse_cdm.version import SCHEMA_VERSION

BASE_ID = "https://synapsecommand.local/cdm"


def _schema(model: type[BaseModel], name: str) -> dict:
    schema = model.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"{BASE_ID}/{SCHEMA_VERSION}/{name}.schema.json"
    schema["x-cdm-schema-version"] = SCHEMA_VERSION
    return schema


def generate() -> dict[str, dict]:
    """Every published schema, by file stem.

    Includes a `cdm_object` union schema so a consumer reading a mixed stream can validate
    without first deciding which kind it is holding — the discriminator does that work, and a
    consumer forced to guess would guess wrong on the object it has never seen before.
    """
    out: dict[str, dict] = {name: _schema(model, name) for name, model in KINDS.items()}
    for event_type, model in PAYLOAD_MODELS.items():
        stem = f"payload_{event_type.value.lower()}"
        out[stem] = _schema(model, stem)
    union = TypeAdapter(CDMObject).json_schema(mode="serialization")
    union["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    union["$id"] = f"{BASE_ID}/{SCHEMA_VERSION}/cdm_object.schema.json"
    union["x-cdm-schema-version"] = SCHEMA_VERSION
    out["cdm_object"] = union
    return out


def _serialise(schema: dict) -> str:
    # sort_keys, because an export whose key order depends on dict insertion produces a diff
    # on every re-run and teaches everyone to ignore diffs in this directory.
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def write(out_dir: pathlib.Path) -> list[pathlib.Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in generate().items():
        path = out_dir / f"{name}.schema.json"
        path.write_text(_serialise(schema))
        written.append(path)
    return written


def check(out_dir: pathlib.Path) -> list[str]:
    """Paths that are missing or stale. Empty list means the publication is current."""
    problems = []
    for name, schema in generate().items():
        path = out_dir / f"{name}.schema.json"
        if not path.exists():
            problems.append(f"{path}: missing — run python -m synapse_cdm.schemas --out {out_dir}")
        elif path.read_text() != _serialise(schema):
            problems.append(f"{path}: stale — the models changed; re-export")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="schemas", type=pathlib.Path)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the files on disk are missing or stale")
    args = parser.parse_args(argv)
    if args.check:
        problems = check(args.out)
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{'STALE' if problems else 'CURRENT'}: {args.out} vs models at {SCHEMA_VERSION}")
        return 1 if problems else 0
    for path in write(args.out):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
