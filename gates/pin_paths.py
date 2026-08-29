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


# ------------------------------------------------------------------ the decomposition, DERIVED

class Decomposition(NamedTuple):
    """The parts of a pin-as-control run, derived from the corpus rather than narrated.

    WHY THIS IS A TYPE AND NOT A PARAGRAPH. A round reported the corpus as "eighteen documents,
    three of them under `spec/history/`". The eighteen was right. **No pinned copy is under
    `spec/history/` at all** — the sub-clause named a location the corpus does not have, and it
    survived because it was a SUB-CLAUSE rather than an addend: the total still added up, and the
    total is what the gate read. A decomposition nobody derives is a decomposition nobody checks.
    """
    pairs: int
    copies: int
    per_pin_file: dict[str, int]
    silent_pin_files: tuple[str, ...]
    per_location: dict[str, int]
    per_kind: dict[str, int]


def decompose(pins: list[Pin] | None = None, root: pathlib.Path | None = None) -> Decomposition:
    """Every part of the control run, each counted from the pins themselves.

    `per_pin_file` counts PAIRS — a pin file states pairs, and two of them may name one copy.
    `per_location` and `per_kind` count DISTINCT COPIES after resolution, because that is what
    "eighteen documents and two stream artefacts" is a decomposition OF.
    """
    pins = discover(root) if pins is None else pins
    base = (root or PKG) / "fixtures"

    per_pin_file: dict[str, int] = {}
    for pin in pins:
        key = str(pin.pin_file.relative_to(REPO))
        per_pin_file[key] = per_pin_file.get(key, 0) + 1

    silent = tuple(sorted(
        str(f.relative_to(REPO)) for f in base.rglob("*_pin.json")
        if str(f.relative_to(REPO)) not in per_pin_file
    ))

    seen: set[str] = set()
    per_location: dict[str, int] = {}
    per_kind: dict[str, int] = {}
    for pin in pins:
        resolved = str(pin.resolved)
        if resolved in seen:
            continue
        seen.add(resolved)
        location = str(pathlib.PurePosixPath(pin.local_path).parent)
        per_location[location] = per_location.get(location, 0) + 1
        per_kind[pin.kind] = per_kind.get(pin.kind, 0) + 1

    return Decomposition(
        pairs=len(pins), copies=len(seen),
        per_pin_file=dict(sorted(per_pin_file.items())), silent_pin_files=silent,
        per_location=dict(sorted(per_location.items())), per_kind=dict(sorted(per_kind.items())))


def check_parts(d: Decomposition) -> list[str]:
    """The partition half: every part set must add to the total it is a part set OF."""
    problems: list[str] = []
    if sum(d.per_pin_file.values()) != d.pairs:
        problems.append(
            f"per-pin-file counts sum to {sum(d.per_pin_file.values())}, not the {d.pairs} pairs "
            f"discovered")
    for name, part in (("location", d.per_location), ("kind", d.per_kind)):
        if sum(part.values()) != d.copies:
            problems.append(
                f"per-{name} counts sum to {sum(part.values())}, not the {d.copies} distinct "
                f"copies after resolution")
    for name, part in (("pin file", d.per_pin_file), ("location", d.per_location),
                       ("kind", d.per_kind)):
        empty = sorted(k for k, v in part.items() if v <= 0)
        if empty:
            problems.append(f"{name} part(s) with no copies at all: {empty}")
    return problems


def check_stated(stated: dict[str, int], d: Decomposition | None = None) -> list[str]:
    """Compare a decomposition SOMEBODY STATED against the derived one. THE guard.

    Locations only, because that is the axis the recorded failure moved on. Three complaints, and
    the FIRST is the one a sum check cannot make:

    * **PHANTOM** — a location stated that the corpus does not have. This is the recorded failure's
      shape exactly, and a guard that only added the parts up would pass it: `spec/history/` was
      never an addend, it was a sub-clause of a correct eighteen.
    * **MISSING** — a location the corpus has and the statement omits.
    * **COUNT** — a location both agree exists and disagree about.
    """
    d = decompose() if d is None else d
    problems: list[str] = []
    for location in sorted(set(stated) - set(d.per_location)):
        problems.append(
            f"PHANTOM location {location!r}: stated as holding {stated[location]} pinned "
            f"copy/copies, and the corpus resolves NONE into it. The corpus has "
            f"{sorted(d.per_location)}. A total that still adds up does not make a part real")
    for location in sorted(set(d.per_location) - set(stated)):
        problems.append(
            f"MISSING location {location!r}: the corpus resolves {d.per_location[location]} "
            f"pinned copy/copies into it and the statement does not mention it")
    for location in sorted(set(stated) & set(d.per_location)):
        if stated[location] != d.per_location[location]:
            problems.append(
                f"COUNT at {location!r}: stated {stated[location]}, derived "
                f"{d.per_location[location]}")
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

    dec = decompose([r.pin for r in readings])
    print(f"pairs         {dec.pairs} local_path+sha256 pairs, stated by "
          f"{len(dec.per_pin_file)} of {len(dec.per_pin_file) + len(dec.silent_pin_files)} "
          f"pin files")
    for pin_file, n in dec.per_pin_file.items():
        print(f"  {n:>3} {pin_file}")
    for pin_file in dec.silent_pin_files:
        print(f"    . {pin_file} — states no local_path+sha256 pair")
    print(f"copies        {dec.copies} distinct, after resolution")
    for kind, n in dec.per_kind.items():
        print(f"  {kind:<11} {n} distinct, base {BASES[kind].relative_to(REPO) or '.'}")
    for location, n in dec.per_location.items():
        print(f"    {n:>3} {location}")
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
    parts = check_parts(dec)
    for p in parts:
        print(f"DECOMPOSITION {p}")
    failed = mismatched + len(problems) + len(parts)
    print(f"{len(distinct)} copies, {failed} failed")
    return 1 if failed else 0


def _mutation_check() -> int:
    """Prove the resolver distinguishes, in BOTH directions, on the tree's own pins.

    A resolver that returned one base for everything would pass a control run that only ever asked
    it about documents. These two cases are what that resolver fails.
    """
    pins = discover()
    present = [p for p in pins if p.resolved.exists()]
    lines, failed = [], 0

    # The BYTES half only. The decomposition half below is a property of the pin RECORDS and runs
    # on a fresh clone too — gating it on bytes would be this module's own defect, a check that
    # goes green while measuring nothing.
    if not present:
        lines.append("mutation  SKIPPED  no pinned bytes in this working tree to mutate against")
    for kind, label in (("spec", "a document"), ("streams", "a stream artefact")):
        if not present:
            break
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

    # The decomposition guard, against the shape the record actually failed in.
    dec = decompose(pins)
    truthful = dict(dec.per_location)

    # THE RECORDED FAILURE'S SHAPE, reproduced exactly: not an addend, a SUB-CLAUSE. The round
    # said "eighteen documents, three of them under `spec/history/`" — so three copies were
    # re-attributed from a real location to one the corpus does not have, and the TOTAL WENT ON
    # ADDING UP. That is why the guard compares the parts and not their sum.
    phantom_at = PREFIX + "/klv/spec/history"
    assert phantom_at not in truthful, (
        "the phantom mutation's own subject exists: %r IS a location of this corpus, so this "
        "case would prove nothing. Pick a location the corpus does not have" % phantom_at)
    donor = "%s/klv/spec" % PREFIX
    assert truthful.get(donor, 0) >= 3, (
        "the mutation cannot be applied: it re-attributes three copies away from %r and the "
        "corpus resolves %d there. A mutation whose domain is empty is a case that passes "
        "without running" % (donor, truthful.get(donor, 0)))
    phantom = dict(truthful)
    phantom[donor] -= 3
    phantom[phantom_at] = 3

    caught = [c for c in check_stated(phantom, dec) if c.startswith("PHANTOM")]
    failed += not caught
    lines.append(
        "mutation  %s     the recorded failure is caught — %r stated, none resolved into it"
        % ("PASS" if caught else "FAIL", phantom_at))

    sum_only_blind = sum(phantom.values()) == dec.copies
    failed += not sum_only_blind
    lines.append(
        "mutation  %s     ...and a SUM-ONLY guard passes that same statement (%d == %d), which "
        "is the whole reason this guard compares parts"
        % ("PASS" if sum_only_blind else "FAIL", sum(phantom.values()), dec.copies))

    subclause_only = check_stated(truthful, dec)
    sum_still_right = sum(truthful.values()) == dec.copies
    ok = not subclause_only and sum_still_right
    failed += not ok
    lines.append(
        f"mutation  {'PASS' if ok else 'FAIL'}     the truthful decomposition passes both halves, "
        f"so the guard is not simply refusing everything")

    for label, mutated, prefix in (
            ("a wrong count at a real location",
             dict(truthful, **{next(iter(truthful)): truthful[next(iter(truthful))] + 1}), "COUNT"),
            ("an omitted location",
             {k: v for k, v in list(truthful.items())[1:]}, "MISSING")):
        got = [c for c in check_stated(mutated, dec) if c.startswith(prefix)]
        failed += not got
        lines.append(f"mutation  {'PASS' if got else 'FAIL'}     {label} is caught ({prefix})")
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
