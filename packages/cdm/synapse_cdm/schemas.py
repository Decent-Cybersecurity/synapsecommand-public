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
import pathlib
import re
import sys
from typing import Any

import jsonschema
from pydantic import BaseModel, TypeAdapter

from synapse_cdm import canonical
from synapse_cdm.manifest import AdapterManifest
from synapse_cdm.models import KINDS, PAYLOAD_MODELS, CDMObject
from synapse_cdm.version import MANIFEST_SCHEMA_VERSION, SCHEMA_VERSION

#: The base every schema's `$id` is built from. A URN, and the choice is RULED rather than
#: conventional — see below, because the obvious answer is an `https://` URL and it is wrong here.
#:
#: WHAT A CONSUMER ACTUALLY DOES WITH `$id`, which is what decided it:
#:
#: 1. **Registers the schema under it**, so `$ref` can resolve. That needs uniqueness and
#:    stability and nothing else.
#: 2. **May try to FETCH it.** This is the one that rules out `https://`. Every `$ref` in these
#:    eight schemas is internal — `#/$defs/...`, none references another by `$id` — so nothing
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


#: JSON Schema's dialect, as every published file declares it.
DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _ecma_end_anchors(pattern: str) -> str:
    """`$` outside a character class and not escaped -> `\\Z`, so Python reads it as ECMA does.

    JSON Schema regexes are ECMA-262 (draft 2020-12 §6.4), where `$` without the multiline
    flag matches only at the end of input. Python's `re` also lets `$` match BEFORE a final
    newline, and the `jsonschema` package implements `pattern` with `re.search` — so a vanilla
    Python validator accepts `"1.2.3\\n"` against `^…$` while a JavaScript, Go or Rust validator
    refuses it (audit F04, 2026-09-19). `\\Z` is Python's end-of-input-only anchor.
    """
    out: list[str] = []
    in_class = False
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            out.append(pattern[i:i + 2])
            i += 2
            continue
        if in_class:
            in_class = ch != "]"
        elif ch == "[":
            in_class = True
        elif ch == "$":
            ch = r"\Z"
        out.append(ch)
        i += 1
    return "".join(out)


def _pattern_as_ecma(validator, pattern, instance, schema):
    if validator.is_type(instance, "string") \
            and re.search(_ecma_end_anchors(pattern), instance) is None:
        yield jsonschema.ValidationError(f"{instance!r} does not match {pattern!r}")


#: `Draft202012Validator` with `pattern` read as ECMA-262 reads it. Everything in this package
#: that validates a document against a published schema — `conformance`, `harness`, the tests —
#: builds its validator through `validator_for()` below, so the Python answer is the answer a
#: consumer in another language gets. The only difference from the stock class is the anchor
#: rule above; every other keyword is the library's.
EcmaPatternValidator = jsonschema.validators.extend(
    jsonschema.Draft202012Validator, {"pattern": _pattern_as_ecma})


def validator_for(schema: dict) -> Any:
    """The validator this package uses for a published schema: 2020-12, ECMA-262 `pattern`,
    and `format` ASSERTED (`FormatChecker()`), because `format` is an annotation otherwise and
    the published `uuid` format would accept "banana" as an identifier the models refuse."""
    return EcmaPatternValidator(schema, format_checker=jsonschema.FormatChecker())


def _schema(model: type[BaseModel], name: str) -> dict:
    schema = model.model_json_schema(mode="serialization")
    schema["$schema"] = DIALECT
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
    union["$schema"] = DIALECT
    union["$id"] = f"{BASE_ID}:{SCHEMA_VERSION}:cdm_object"
    union["x-cdm-schema-version"] = SCHEMA_VERSION
    out["cdm_object"] = union
    out[MANIFEST_STEM] = manifest_schema()
    out[EVIDENCE_STEM] = evidence_schema()
    out[EXERCISE_STEM] = exercise_schema()
    return out


#: The manifest schema's stem, and it carries a DIRECTORY. `write()` and `check()` treat a stem
#: as a path relative to `--out`, so `schemas/manifests/` (spec §12) is reached without a second
#: exporter — and `tests/test_cdm_schemas.py`'s parametrised checks glob `schemas/*.schema.json`
#: at the top level only, so the manifest schema is not swept into the CDM object checks that
#: assert `x-cdm-schema-version` and a `urn:synapsecommand:cdm:` identifier. It is a different
#: contract on a different axis and it says so in its own keys.
MANIFEST_STEM = "manifests/adapter-manifest"


def manifest_schema() -> dict:
    """The published shape of `manifests/<id>.json`, generated from `manifest.AdapterManifest`.

    Generated from the MANIFEST model rather than from `AdapterMetadata` alone, and the
    difference matters: the published file is the manifest — envelope and declaration — so a
    schema generated from the declaration by itself would reject every file it is supposed to
    validate. `AdapterMetadata` is in here, as the `adapter` property's `$def`.
    """
    schema = AdapterManifest.model_json_schema(mode="serialization")
    schema["$schema"] = DIALECT
    schema["$id"] = f"urn:synapsecommand:manifest:{MANIFEST_SCHEMA_VERSION}:adapter-manifest"
    schema["x-manifest-schema-version"] = MANIFEST_SCHEMA_VERSION
    return schema


#: The evidence schema's stem, and it carries a directory for the same reason `MANIFEST_STEM`
#: does: `schemas/evidence/` (spec §32) is reached by `write()`'s one `mkdir(parents=True)` line
#: rather than by a second exporter. `tests/test_cdm_schemas.py` globs `schemas/*.schema.json` at
#: the top level and `docs/scripts/check-schema-docs.mjs:44` uses a non-recursive `readdirSync`,
#: so neither sweeps a subdirectory — which is why the documentation site's "9 generated files"
#: is unmoved by this addition, by design rather than by luck.
EVIDENCE_STEM = "evidence/evidence"


def evidence_schema() -> dict:
    """The published shape of `evidence/<adapter>/<version>/evidence.json` (§32).

    THE IMPORT IS DEFERRED AND THE CYCLE IS THE REASON. `synapse_cdm.evidence` needs the
    conformance suite, which needs the harness, which needs THIS module — so an import at the top
    of this file would be a cycle at interpreter start. The alternative was to define the record's
    models somewhere that imports nothing, which would have split one contract across two modules
    to satisfy an import graph. One deferred import, named here, is the cheaper honesty.
    """
    from synapse_cdm.evidence import EvidenceRecord
    from synapse_cdm.version import EVIDENCE_SCHEMA_VERSION

    schema = EvidenceRecord.model_json_schema(mode="serialization")
    schema["$schema"] = DIALECT
    schema["$id"] = f"urn:synapsecommand:evidence:{EVIDENCE_SCHEMA_VERSION}:evidence"
    schema["x-evidence-schema-version"] = EVIDENCE_SCHEMA_VERSION
    return schema


#: The exercise report's stem (audit remediation F07, 2026-09-20), beside the record's under
#: `schemas/evidence/` and on the same axis: a report is what makes an external category of the
#: record PRESENT, so its shape moves with the record's and carries the record's version.
EXERCISE_STEM = "evidence/exercise"


def exercise_schema() -> dict:
    """The published shape of `evidence/<adapter>/<version>/exercises/<slug>.json` (F07).

    The same deferred import as `evidence_schema`, for the same cycle.
    """
    from synapse_cdm.evidence import ExerciseReport
    from synapse_cdm.version import EVIDENCE_SCHEMA_VERSION

    schema = ExerciseReport.model_json_schema(mode="serialization")
    schema["$schema"] = DIALECT
    schema["$id"] = f"urn:synapsecommand:evidence:{EVIDENCE_SCHEMA_VERSION}:exercise"
    schema["x-evidence-schema-version"] = EVIDENCE_SCHEMA_VERSION
    return schema


def _serialise(schema: dict) -> str:
    # sort_keys, because an export whose key order depends on dict insertion produces a diff
    # on every re-run and teaches everyone to ignore diffs in this directory. The form is
    # `canonical.serialise`'s, ARCHITECTURE.md §6.2's, and not a copy of it.
    return canonical.serialise(schema)


def write(out_dir: pathlib.Path) -> list[pathlib.Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in generate().items():
        path = out_dir / f"{name}.schema.json"
        # A stem may carry a directory (see MANIFEST_STEM); nothing else needs this and it costs
        # one line, which is cheaper than a second exporter for one file.
        path.parent.mkdir(parents=True, exist_ok=True)
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
