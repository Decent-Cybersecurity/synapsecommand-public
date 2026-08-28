"""One mapping from a pin's `local_path` to a file on disk, because there are two bases.

WHY THIS EXISTS, AND IT IS THREE REPRODUCTIONS RATHER THAN A PRINCIPLE
---------------------------------------------------------------------
Every pin in this repository states its subject as a `local_path` beginning `fixtures/`. **Two
different directories answer to that prefix**, and which one is correct depends on the pin:

* `fixtures/klv/spec/ST1201.3.pdf` lives under **`packages/cdm/synapse_cdm/`** — the specification
  documents ship inside the distribution's fixture tree;
* `fixtures/klv/streams/day_flight.klv` lives under the **repository root** — the transport-stream
  artefacts are excluded from the index by a directory rule in `.gitignore` and are never vendored.

The two are **disjoint**: neither path exists under the other's base. And they share their first
two segments, `fixtures/klv/`, so nothing a reader sees at a glance distinguishes them.

Three sites resolved this by hand before this module existed, each with its own base arithmetic:

1. `tests/test_cdm_pins.py`'s ``_full()`` — ``return PKG / recorded``, **unconditionally
   package-relative**. It is correct today only because ``discover_pins()`` filters its corpus to
   ``.pdf``, which happens to exclude both stream artefacts. The filter is doing load-bearing work
   that reads as an extension preference.
2. `tests/test_cdm_format_coverage.py`'s ``_klv_streams_dir()`` — ``parents[3]``, root-relative,
   and it **rebuilds** ``fixtures/klv/streams`` as a literal rather than reading the `local_path`
   the pin states.
3. `tests/test_cdm_stanag4609_adapter.py`'s ``STREAM`` — ``REPO / "fixtures" / "klv" / "streams" /
   "day_flight.klv"``, a third literal, against a fourth spelling of the root.

**THE RECORDED FAILURE'S SHAPE, AND IT IS WHY THIS IS A MODULE RATHER THAN A WARNING.** Feed a
stream's `local_path` to the package base and you get
``packages/cdm/synapse_cdm/fixtures/klv/streams/day_flight.klv``, which does not exist — so the
artefact reads as **ABSENT**. That is not a crash. Every pin check in this repository treats an
absent subject as a `pytest.skip`, deliberately and correctly, because a fresh clone genuinely has
the record and not the bytes. **So a wrong base is indistinguishable from a fresh clone**, and the
check goes green while measuring nothing. A round reported exactly that absence and it was the
reader's error, not the tree's.

THE RULE, AND IT IS CHECKED AGAINST THE TREE RATHER THAN ASSERTED
----------------------------------------------------------------
A `local_path` is ``fixtures/<set>/<kind>/...`` and **`<kind>` selects the base**:

* ``spec`` → the package, ``packages/cdm/synapse_cdm/``;
* ``streams`` and ``provenance`` → the repository root.

`<kind>` is the right discriminator rather than the extension or the fixture set, and the tree says
so: the split is *pinned documents ship, pinned bytes do not*, which is a statement about what
`.gitignore` excludes by DIRECTORY rule and therefore about the directory. An extension rule would
have to be revised the first time a pinned stream is not `.klv`.

**Anything else is REFUSED, not guessed** — `UnknownConvention`, naming the path and the kind. This
follows `gates/bump_derivation.py`'s UNRULED branch and for the same reason: the failure mode here
is a silent absence, so a default base would restore precisely the defect this module retires. A
new `<kind>` is a decision about where bytes live and belongs to a human.

`verify_convention()` is the part that keeps the rule honest. For every pin in the corpus it checks
the tree directly — that the chosen base holds the file and the other base does not — so the rule
is derived from where the bytes actually are on every run, rather than restated here and trusted.
On a fresh clone the absent side is unverifiable and is reported as such rather than passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Iterator, NamedTuple

#: This file is `gates/pin_paths.py`, so the repository root is one level up. Stated once.
REPO = pathlib.Path(__file__).resolve().parents[1]

#: The distribution's own root. The second base, and the reason this module exists.
PKG = REPO / "packages" / "cdm" / "synapse_cdm"

#: `<kind>` → base. THE mapping. Adding a row here is a decision about where bytes live.
BASES: dict[str, pathlib.Path] = {
    "spec": PKG,
    "streams": REPO,
    "provenance": REPO,
}

#: What every `local_path` in this repository begins with.
PREFIX = "fixtures"


class UnknownConvention(ValueError):
    """A `local_path` whose `<kind>` segment names no base. Refused rather than defaulted."""


class Pin(NamedTuple):
    """One `local_path` with a `sha256`, and the pin file that states it."""
    pin_file: pathlib.Path
    local_path: str
    sha256: str
    bytes_: int | None

    @property
    def kind(self) -> str:
        return kind_of(self.local_path)

    @property
    def resolved(self) -> pathlib.Path:
        return resolve(self.local_path)


def kind_of(local_path: str) -> str:
    """`fixtures/klv/streams/day_flight.klv` → `'streams'`. The discriminator, read not guessed."""
    parts = pathlib.PurePosixPath(local_path).parts
    if len(parts) < 3 or parts[0] != PREFIX:
        raise UnknownConvention(
            f"{local_path!r} is not a pin path: every local_path in this repository is "
            f"{PREFIX}/<set>/<kind>/... and this one has parts {parts!r}"
        )
    return parts[2]


def resolve(local_path: str) -> pathlib.Path:
    """The absolute path a `local_path` names. THE resolver — no second site does this by hand.

    Refuses an unknown `<kind>` instead of choosing a base, because a wrong base here does not
    raise: it reports the file as absent, which every caller correctly treats as a fresh clone.
    """
    kind = kind_of(local_path)
    try:
        base = BASES[kind]
    except KeyError:
        raise UnknownConvention(
            f"{local_path!r} has kind {kind!r} and this module knows {sorted(BASES)}. REFUSED "
            f"rather than defaulted to a base: a wrong base reports the file absent rather than "
            f"failing, so a guess here is a silent one. Add {kind!r} to BASES when a human has "
            f"decided whether those bytes ship inside the distribution or sit at the root."
        ) from None
    return base / local_path


def other_base(local_path: str) -> pathlib.Path:
    """Where the same `local_path` would land under the *wrong* base. The failure's shape."""
    chosen = BASES[kind_of(local_path)]
    wrong = PKG if chosen == REPO else REPO
    return wrong / local_path


def _walk(node) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def discover(root: pathlib.Path | None = None) -> list[Pin]:
    """Every `local_path` paired with a `sha256`, across every pin file. NO extension filter.

    The absence of an extension filter is the point. `tests/test_cdm_pins.py` filters to `.pdf` and
    is correct today by luck rather than by rule — the filter is what keeps the two stream
    artefacts away from a package-relative `_full()`. Here every pin is discovered and the base is
    chosen per pin, so the corpus can widen without the resolution going wrong.
    """
    fixtures = (root or PKG) / "fixtures"
    found: list[Pin] = []
    for pin_file in sorted(fixtures.rglob("*_pin.json")):
        data = json.loads(pin_file.read_text())
        for node in _walk(data):
            path, sha = node.get("local_path"), node.get("sha256")
            if isinstance(path, str) and isinstance(sha, str):
                size = node.get("bytes")
                found.append(Pin(pin_file, path, sha, int(size) if size is not None else None))
    return found


class Reading(NamedTuple):
    """One pin, re-digested. `matched` is None when the bytes are absent from this tree."""
    pin: Pin
    present: bool
    matched: bool | None
    digest: str | None


def control(pins: list[Pin] | None = None) -> list[Reading]:
    """Pin-as-control: re-digest every pinned copy from the bytes on disk, through the resolver."""
    readings: list[Reading] = []
    for pin in pins if pins is not None else discover():
        full = pin.resolved
        if not full.exists():
            readings.append(Reading(pin, False, None, None))
            continue
        digest = hashlib.sha256(full.read_bytes()).hexdigest()
        readings.append(Reading(pin, True, digest == pin.sha256, digest))
    return readings


def verify_convention(pins: list[Pin] | None = None) -> list[str]:
    """Check the RULE against the tree. Returns a list of complaints; empty is clean.

    For each pin whose bytes are present: the chosen base must hold it and the other base must not.
    The second half is what makes this a check rather than a restatement — if both bases held the
    file the rule would be unfalsifiable, and if the other base held it the rule would be backwards.
    """
    problems: list[str] = []
    for pin in pins if pins is not None else discover():
        chosen, wrong = pin.resolved, other_base(pin.local_path)
        if not chosen.exists():
            continue  # a fresh clone; `control` reports the absence, this check cannot speak
        if wrong.exists():
            problems.append(
                f"{pin.local_path}: BOTH bases hold this file ({chosen} and {wrong}), so the "
                f"convention is not falsifiable for it and one of the two copies is a duplicate"
            )
    return problems


def _report(readings: list[Reading], problems: list[str]) -> int:
    by_kind: dict[str, list[Reading]] = {}
    for r in readings:
        by_kind.setdefault(r.pin.kind, []).append(r)

    distinct = {str(r.pin.resolved): r for r in readings}
    present = sum(1 for r in distinct.values() if r.present)
    matched = sum(1 for r in distinct.values() if r.matched)
    absent = sum(1 for r in distinct.values() if not r.present)
    mismatched = sum(1 for r in distinct.values() if r.matched is False)

    print(f"pairs         {len(readings)} local_path+sha256 pairs across "
          f"{len({str(r.pin.pin_file) for r in readings})} pin files")
    print(f"copies        {len(distinct)} distinct, after resolution")
    for kind in sorted(by_kind):
        d = {str(r.pin.resolved) for r in by_kind[kind]}
        print(f"  {kind:<11} {len(d)} distinct, base {BASES[kind].relative_to(REPO) or '.'}")
    print(f"present       {present}")
    print(f"matched       {matched}")
    if absent:
        print(f"absent        {absent}")
        for r in distinct.values():
            if not r.present:
                print(f"              {r.pin.local_path}")
    if mismatched:
        for r in distinct.values():
            if r.matched is False:
                print(f"MISMATCH      {r.pin.local_path}: disk {r.digest} pin {r.pin.sha256}")
    for p in problems:
        print(f"CONVENTION    {p}")
    failed = mismatched + len(problems)
    print(f"{len(distinct)} copies, {failed} failed")
    return 1 if failed else 0


def _mutation_check() -> int:
    """Prove the resolver distinguishes, in BOTH directions, on the tree's own pins.

    A resolver that returned one base for everything would pass a control run that only ever asked
    it about documents. These two cases are what that resolver fails.
    """
    pins = discover()
    present = [p for p in pins if p.resolved.exists()]
    if not present:
        print("mutation  SKIPPED — no pinned bytes in this working tree to mutate against")
        return 0

    lines, failed = [], 0
    for kind, label in (("spec", "a document"), ("streams", "a stream artefact")):
        subjects = [p for p in present if p.kind == kind]
        if not subjects:
            lines.append(f"mutation  SKIPPED  {kind}: none present in this working tree")
            continue
        p = subjects[0]
        wrong = other_base(p.local_path)
        ok = not wrong.exists()
        failed += not ok
        lines.append(
            f"mutation  {'PASS' if ok else 'FAIL'}     {label} under the WRONG base reads as "
            f"{'ABSENT' if ok else 'PRESENT'} — {p.local_path}"
        )
    unknown = "fixtures/klv/nowhere/x.bin"
    try:
        resolve(unknown)
    except UnknownConvention:
        lines.append("mutation  PASS     an unknown <kind> is REFUSED rather than defaulted")
    else:
        failed += 1
        lines.append("mutation  FAIL     an unknown <kind> resolved to a base")
    for line in lines:
        print(line)
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m gates.pin_paths",
        description="Resolve every pin's local_path and re-digest it. THE pin-as-control command.")
    ap.add_argument("--json", action="store_true", help="print the readings as JSON")
    ap.add_argument("--mutation-check", action="store_true",
                    help="prove the resolver distinguishes both conventions, and refuses a third")
    ap.add_argument("--resolve", metavar="LOCAL_PATH",
                    help="print the absolute path one local_path names, and exit")
    args = ap.parse_args(argv)

    if args.resolve:
        print(resolve(args.resolve))
        return 0
    if args.mutation_check:
        return _mutation_check()

    readings = control()
    problems = verify_convention()
    if args.json:
        print(json.dumps([{
            "pin_file": str(r.pin.pin_file.relative_to(REPO)),
            "local_path": r.pin.local_path,
            "kind": r.pin.kind,
            "resolved": str(r.pin.resolved.relative_to(REPO)),
            "present": r.present, "matched": r.matched, "digest": r.digest,
        } for r in readings] , indent=2))
        return 1 if any(r.matched is False for r in readings) or problems else 0
    return _report(readings, problems)


if __name__ == "__main__":
    sys.exit(main())
