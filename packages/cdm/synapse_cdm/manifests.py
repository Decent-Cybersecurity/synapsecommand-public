"""Adapter manifests — GENERATED from the declarations, never hand-written.

    python -m synapse_cdm.manifests --out manifests          # write/refresh
    python -m synapse_cdm.manifests --check --out manifests  # fail if stale (CI)

WHY THIS EXISTS BESIDE `schemas.py` RATHER THAN INSIDE IT
---------------------------------------------------------
`schemas.py` publishes the SHAPE of the canonical objects; this publishes the CONTENT of every
adapter's declaration. Both are generated projections and both are drift-tested for the reason
`schemas.py` argues at length — a second copy of a contract is allowed to exist only when
something mechanical keeps it identical — but they are two different artefacts with two
different version axes (`SCHEMA_VERSION` and `MANIFEST_SCHEMA_VERSION`), and one module writing
both would put those two axes in one place and invite the derivation `version.py` forbids.

WHERE THE FILES LIVE, AND WHY IT IS NOT INSIDE THE WHEEL — M's ruling F1.4, 2026-09-07
--------------------------------------------------------------------------------------
`manifests/<adapter-id>.json` at the REPOSITORY ROOT, a peer of `schemas/`. Manifests are
framework-level interoperability artefacts rather than Python package internals: a non-Python
consumer should be able to discover them without knowing the package layout, and the runtime
metadata stays available from the `Adapter` classes for anyone who has the wheel. Shipping the
same payload inside the wheel as well would be a third copy of one fact, which is the thing this
module and `schemas.py` both exist to prevent.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from synapse_cdm.adapter import roster
from synapse_cdm.manifest import AdapterManifest, ApiRef, CdmRef
from synapse_cdm.version import (ADAPTER_API_VERSION, MANIFEST_SCHEMA_VERSION, SCHEMA_VERSION,
                                 parse)

#: §13's `schema:` key. The identifier a consumer matches on to know which manifest grammar it is
#: holding; its major is `MANIFEST_SCHEMA_VERSION`'s, spelled the way §13 spells it.
SCHEMA_ID = "synapse.adapter-manifest/v1"


def manifest(cls) -> AdapterManifest:
    """One adapter's published manifest, from its own declaration and this tree's version axes.

    Nothing here is a second statement of anything the adapter says: the envelope carries the
    three facts that belong to the PUBLICATION rather than to the adapter — which manifest
    grammar, which Adapter API, which CDM — and `adapter` is the declaration verbatim.
    """
    return AdapterManifest(
        schema_id=SCHEMA_ID,
        manifest_schema_version=MANIFEST_SCHEMA_VERSION,
        # `api.version` is the MAJOR, and §1.2 is explicit that it means "this adapter declares
        # metadata and honours the v2 contract" and NOT "this adapter uses the new method names".
        api=ApiRef(version=str(parse(ADAPTER_API_VERSION)[0])),
        cdm=CdmRef(supported=f"{parse(SCHEMA_VERSION)[0]}.x", schema_version=SCHEMA_VERSION),
        adapter=cls.metadata,
    )


def shipped() -> dict:
    """The adapters THIS PACKAGE ships, which is not the same set as the registry.

    `REGISTRY` is a module-level global and `__init_subclass__` adds to it, so any `Adapter`
    subclass defined anywhere is in it once that module has been imported — a partner's adapter
    resolved by `module:ClassName`, or one of the doubles this repository's own test suite
    defines. `manifests/` is a PUBLICATION of what this distribution ships, so publishing from
    the registry would write a file for whatever happened to be imported, and the drift check
    would then pass or fail depending on import order.

    A third party publishing their own adapter's manifest calls `manifest(cls)`, which is public
    and takes any `Adapter` subclass. What is scoped here is the DIRECTORY this repository
    maintains, not the ability to make a manifest.
    """
    return {name: cls for name, cls in roster().items()
            if cls.__module__.startswith(f"{__package__}.adapters.")}


def generate() -> dict[str, dict]:
    """`{adapter id: manifest}` for every adapter this package ships, in registry order.

    Keyed on the REGISTRY name rather than on the metadata's `id` even though
    `adapter.__init_subclass__` requires the two to be equal: the file name is a fact about the
    roster, and deriving it from the thing under judgement is how a mismatch would name its own
    file and disappear.
    """
    return {name: manifest(cls).model_dump(mode="json") for name, cls in shipped().items()}


def _serialise(payload: dict) -> str:
    """The goldens' form, which ARCHITECTURE.md §6.2 fixes for everything this framework hashes."""
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def write(out_dir: pathlib.Path) -> list[pathlib.Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, payload in generate().items():
        path = out_dir / f"{name}.json"
        path.write_text(_serialise(payload))
        written.append(path)
    return written


def check(out_dir: pathlib.Path) -> list[str]:
    """Paths that are missing, stale or ORPHANED. Empty means the publication is current.

    The third direction is the one a `for adapter in roster()` loop cannot give itself: a file
    for an adapter the registry no longer has is a manifest a consumer can still fetch, for a
    translator that no longer exists. So the sweep runs both ways.
    """
    problems = []
    expected = generate()
    for name, payload in expected.items():
        path = out_dir / f"{name}.json"
        if not path.exists():
            problems.append(f"{path}: missing — run python -m synapse_cdm.manifests --out {out_dir}")
        elif path.read_text() != _serialise(payload):
            problems.append(f"{path}: stale — the adapter's metadata changed; re-export")
    if out_dir.is_dir():
        for path in sorted(out_dir.glob("*.json")):
            if path.name.removesuffix(".json") not in expected:
                problems.append(f"{path}: orphaned — no adapter of that name is registered")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="manifests", type=pathlib.Path)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the files on disk are missing, stale or orphaned")
    args = parser.parse_args(argv)
    if args.check:
        problems = check(args.out)
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{'STALE' if problems else 'CURRENT'}: {args.out} vs "
              f"{len(generate())} shipped adapters at manifest schema {MANIFEST_SCHEMA_VERSION}")
        return 1 if problems else 0
    for path in write(args.out):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
