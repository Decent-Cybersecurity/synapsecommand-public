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

#: The base every schema's `$id` is built from. A URN, and the choice is RULED rather than
#: conventional — see below, because the obvious answer is an `https://` URL and it is wrong here.
#:
#: WHAT A CONSUMER ACTUALLY DOES WITH `$id`, which is what decided it:
#:
#: 1. **Registers the schema under it**, so `$ref` can resolve. That needs uniqueness and
#:    stability and nothing else.
#: 2. **May try to FETCH it.** This is the one that rules out `https://`. Every `$ref` in these
#:    six schemas is internal — `#/$defs/...`, no schema references another by `$id` — so nothing
#:    here needs retrieval to work. But an `https://` identifier INVITES retrieval, and this
#:    repository does not serve these files at any URL and will not promise to: the documentation
#:    site renders reference PAGES generated from `/schemas`, not the schema files. An identifier
#:    that promises a fetch and 404s is worse than one that promises nothing.
#: 3. **Compares it to tell one schema and version from another.** The version is in the path
#:    either way.
#:
#: So the requirement is *identify*, not *locate*, and a URN says exactly that.
#:
#: WHAT THIS REPLACES, AND WHY IT WAS NOT MERELY UNRESOLVABLE BUT WRONG. It was
#: `https://synapsecommand.local/cdm`. RFC 6762 reserves `.local` for multicast DNS — a name
#: scoped to the local link — so that identifier did not just fail to resolve, it asserted a scope
#: that is false for a published contract. The pre-publication audit found it.
#:
#: REJECTED, each on a stated ground. `https://docs.synapsecommand.com/schemas/...` — resolvable
#: only if these exact URLs are served forever, which is a promise this repository is not in a
#: position to make, and a broken promise here is a broken `$ref` for someone else. A `tag:` URI
#: (RFC 4151) is the most formally correct non-dereferenceable choice and was rejected for
#: obscurity: tooling and readers both handle `urn:` without explanation. And the formality is
#: named rather than hidden — `synapsecommand` is not an IANA-registered URN namespace under
#: RFC 8141, which is common practice for JSON Schema `$id`s and is a smaller problem than an
#: identifier that tooling will try to dereference.
#:
#: CHANGED BEFORE FIRST PUBLICATION, DELIBERATELY. A `$id` is a consumer-visible identifier, and
#: moving one after consumers exist would break every registration keyed on it. There are none:
#: the repository is unpublished and `SCHEMA_VERSION` is still 1.0.0. That is exactly why the
#: correction belongs now rather than behind a version bump — a bump exists to protect consumers,
#: and publishing the wrong identifier in order to deprecate it later protects nobody.
BASE_ID = "urn:synapsecommand:cdm"


def _schema(model: type[BaseModel], name: str) -> dict:
    schema = model.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    # Colon-delimited throughout and no file extension: a URN names the SCHEMA, not a file,
    # and `urn:...cdm/1.0.0/entity.schema.json` would read as a half-converted URL — the
    # locate-shaped thing the ruling above rejected, wearing a urn: prefix.
    schema["$id"] = f"{BASE_ID}:{SCHEMA_VERSION}:{name}"
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
    union["$id"] = f"{BASE_ID}:{SCHEMA_VERSION}:cdm_object"
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
