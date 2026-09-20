"""The validation harness: replay recorded payloads through an adapter, judge the output.

    python -m synapse_cdm.harness --adapter pntmap
    python -m synapse_cdm.harness --list-adapters      # and this is how you learn the names

`--list-adapters` prints the registry — name, version, direction, fixture directory, system,
wire binding — and exits 0. Until it existed the roster was reachable only through a failure: `--adapter typo`
put it in a `LookupError`, and a bare invocation got argparse's usage line, which names the flag
and not one value it takes. A tool that had to be misused before its inventory could be read.
`load_adapter`'s refusal and this listing both read `adapter.roster()`, so they cannot name
different sets, and `tests/test_cdm_list_adapters.py` compares the two rendered outputs as well.

`--fixtures` is OPTIONAL for an adapter this package ships: omitted, the harness asks the import
system where its own fixtures are (`adapter.packaged_fixtures`) and replays those. It used to be
required, and every document filled it in with a path inside a CLONE of the repository this
package is developed in — a directory that exists there and nowhere else, printed one line below
`pip install synapse_cdm`. Pass `--fixtures` to replay your own set, and pass it you must for an
adapter loaded as `module:ClassName`, which lives outside this package and whose fixtures this
package cannot know the location of.

WHAT IT IS FOR
--------------
Today: the gate an adapter has to pass before it ships. Tomorrow: the gate GENERATED adapters
have to pass, which is why nothing in this file knows anything about any particular adapter.
It resolves the adapter by name or by `module:ClassName`, reads whatever fixtures it is
pointed at, and applies the same six checks to all of them. An adapter the harness has never
heard of is validated by the same code as the reference one, and that property is the whole
design constraint.

THE SIX CHECKS, AND WHY EACH ONE EARNS ITS PLACE
------------------------------------------------
It said FIVE until the SDK round's stale-count sweep, and it had said five since `roundtrip` was
added — a sixth column in `_COLUMNS`, a sixth row in every report, and a check with its own
docstring and its own SKIP semantics, missing from the list that claims to be the list. The
count is derived by `tests/test_cdm_harness.py` now, at every site that states it.
1. translate   to_cdm() runs and returns objects. A raised exception is a fixture-level FAIL,
               never a crashed run: one bad payload must not stop the other nineteen from
               being judged (the harness that dies at case five reports nineteen unknowns as
               failures, which is how a whole verification run gets thrown away).
2. schema      every object validates against the EXPORTED JSON Schema, not against the
               Pydantic model. Validating against the model would test the model against
               itself; the published schema is what non-Python consumers actually read, so
               the published schema is what gets tested.
3. provenance  every object carries source.system / adapter / adapter_version, `synthetic` is
               stated, entities carry at least one source_id, and events carry both
               timestamps. Provenance is the platform's whole audit story — an object that
               cannot say where it came from is inadmissible regardless of how well-formed it
               is.
4. lossless    every source leaf is accounted for. Two readings, one column (F02, 2026-09-19):
               the value-presence HEURISTIC (`lossless.value_presence_heuristic`) runs on every
               JSON fixture and catches a value that vanished outright; where the adapter
               declares `MAPPINGS`, the path-bound LEDGER (`lossless.ledger`) runs as well and
               a LOST leaf fails the column. The report says which basis the verdict rests on
               — `basis: ledger` or `basis: heuristic` — and a heuristic PASS is not proof of
               preservation. Declared transforms and mappings are printed.
5. roundtrip   for an egress or bidirectional adapter: raw -> CDM -> raw reproduces the
               source under the tolerance the class DECLARES — octet for octet by default, or
               no VALUE lost after re-ingest where the format (XML) cannot promise octets. See
               `_check_roundtrip`, which explains which half of a fixture pair carries the
               verdict and why an ingest-only adapter gets SKIP rather than PASS.
6. golden      the output matches the recorded expectation byte for byte, under a FROZEN
               clock. This is what catches an unintended change in a translation nobody meant
               to touch.

DETERMINISM
-----------
The clock is frozen (times.FROZEN_NOW) unless --now says otherwise, and ids are derived rather
than drawn (ids.py), so a fixture produces identical bytes on every machine and the golden
diff means something. An adapter that reaches for datetime.now() or uuid4() will fail the
golden check on its second run — which is the intended lesson.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import sys
import traceback
from typing import Any

from synapse_cdm import canonical, lossless, schemas, times
from synapse_cdm.adapter import (Adapter, is_shipped, json_nesting_depth, load_adapter,
                                 packaged_fixtures, roster)
from synapse_cdm.models import CDMBase

GOLDEN_DIR = "golden"
PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

#: How many ledger diagnostics one fixture's entry carries (F02). The COUNTS are always
#: complete; only the per-leaf lines are capped, so a report over a wide payload stays readable
#: and the entry says how many lines it left out.
DIAGNOSTIC_LIMIT = 20


def _unsupported_paths(adapter: Adapter) -> tuple[str, ...]:
    """The paths a structured Limitation declares, for the ledger's DECLARED_LIMITATION."""
    from synapse_cdm import manifest              # local: manifest imports nothing from here
    metadata = getattr(type(adapter), "metadata", None)
    if metadata is None:
        return ()
    return manifest.unsupported_paths(metadata.limitations)

#: The name of the per-directory provenance record (§33, M's pre-ruled default 3). Excluded by
#: NAME rather than by extension, because a fixture directory legitimately holds `.json`
#: payloads — `pntmap` and `legion` ship nothing else — so an extension rule would exclude the
#: fixtures and keep the record.
PROVENANCE_FILE = "PROVENANCE.json"

#: The rule that selects a fixture, written down so a run that selects NOTHING can quote it.
#: It is not a glob — it is four predicates over the directory's immediate children — and the
#: message says so rather than printing a `*` that would suggest a pattern the code never uses.
#:
#: The fourth exclusion arrived with §33's provenance records (round P4, 2026-09-08). It is the
#: same argument `README.md` already won: a file that DESCRIBES the fixture set is not a member
#: of it, and one that got replayed as a payload would report an adapter failure about a
#: document nobody claimed was a message.
FIXTURE_PATTERN = ("immediate children of the directory that are files, "
                   "excluding dotfiles, README.md and PROVENANCE.json")


def select_fixtures(directory: pathlib.Path) -> list[pathlib.Path]:
    """`FIXTURE_PATTERN`, executed: the one definition of "a fixture", sorted.

    The suite's `_fixtures` and the evidence generator's `harness_selects` restated these four
    predicates and a test held the three restatements equal; since 2026-09-16 both call this,
    so the three modules cannot select different sets, and the test holds one function to the
    sentence above it.
    """
    return sorted(p for p in directory.iterdir()
                  if p.is_file() and not p.name.startswith(".")
                  and p.name not in ("README.md", PROVENANCE_FILE))

#: Exit status for a run that could not happen. Distinct from 1, which means fixtures ran and
#: some failed: this one means the INVOCATION was wrong, and conflating the two would tell a
#: caller to debug an adapter when the thing to fix is the path they passed.
#:
#: Three conditions share it, and sharing is the ruling rather than an omission — a path the
#: caller passed is wrong in all three, and splitting them would be splitting one repair into
#: three exit codes nobody would remember: no fixtures matched, no schemas were found in a
#: `--schemas` directory, and `--fixtures` was omitted for an adapter this package does not ship
#: and therefore has no fixtures for. The NAME is kept for the first, which is the one every gate
#: sweep is written against.
EXIT_NO_FIXTURES = 2


class NoSchemasFound(RuntimeError):
    """A `--schemas` directory with no schemas in it. Raised, never validated around.

    `NoFixturesFound`'s argument, one check along: a run that validated nothing must not be
    reportable, and the report is where the misdirection happened — an empty validator table
    turns "the directory is missing" into one "unknown object_kind" line per object, which reads
    as a broken adapter. Both are INVOCATION errors and both exit `EXIT_NO_FIXTURES`, because
    both mean the same thing to a caller: fix the path, not the code.
    """


class NoFixturesFound(RuntimeError):
    """A harness run that matched zero fixtures. Raised, never reported as a pass.

    THE FAILURE THIS EXISTS FOR
    ---------------------------
    `--adapter stanag4676 --fixtures fixtures/stanag4676` used to print "0 passed, 0 failed" and
    exit 0. That directory held only a `spec/` subdirectory of pinned standards (it no longer
    exists); the adapter's fixtures are in `fixtures/nits`. So a gate sweep over all nine adapters
    reported nine greens while one of them had replayed nothing, and the run that proves the
    least looks exactly like the run that proves the most.

    It is the same failure `test_cdm_prose_counts.py` guards in prose — "a regex that silently
    matches nothing is worse than no test at all, it reads as a passing check on a site nobody is
    checking any more" — reached from the other direction. A verification tool's worst output is
    not a false failure; it is a true-looking pass over an empty set.
    """


#: F06 (2026-09-20): the fixture LOADER's own depth bound. `load_raw` is the one place in this
#: package that runs `json.loads` BEFORE any adapter's declared `max_depth` can apply — a `.json`
#: twin is parsed here and handed over as a dict, and the base class measures the dict only after
#: this parse has already recursed. On CPython 3.11 `json.loads` raises `RecursionError` a little
#: under a thousand containers deep (`adapter.InputTooDeep` carries the readings), so a twin that
#: deep crashed the harness in-process and reached the conformance worker as `PARSER_CRASH` in the
#: loader layer. The text is measured with `adapter.json_nesting_depth` first, and the figure is
#: the same 64 every declared `max_depth` uses: the deepest of the 941 `.json` files under the
#: fourteen fixture directories, goldens included, nests fifteen containers (read 2026-09-20).
#: A bound on octets is deliberately NOT defaulted: the twin of a 14-octet ADS-B
#: squitter is over 400 octets, no document states a figure, and the file is one the operator
#: named — `LOADER_MAX_BYTES` is a hosting application's knob and reads `None` until one sets it.
LOADER_MAX_DEPTH = 64
LOADER_MAX_BYTES: int | None = None


class FixtureTooLarge(ValueError):
    """A fixture file over the loader's byte bound, refused on `stat()` before it is read."""


class FixtureTooDeep(ValueError):
    """A `.json` fixture nesting past the loader's depth bound, refused before `json.loads`."""


def load_raw(path: pathlib.Path, *, max_bytes: int | None = None,
             max_depth: int | None = None) -> Any:
    """Fixtures are JSON on disk; adapters may take bytes or dict.

    A `.bin`/`.txt`/`.xml` fixture is handed over as raw bytes untouched — a STANAG or CoT XML
    adapter must be replayable from the bytes it will really receive, and pre-parsing it here
    would test a parser the adapter does not use in production.

    `max_bytes` (default `LOADER_MAX_BYTES`, i.e. none) is checked on the file's size BEFORE the
    file is read, and `max_depth` (default `LOADER_MAX_DEPTH`) on the characters BEFORE
    `json.loads` sees them — the two points where a bound still protects the allocation or the
    recursion it is about. Pass `0` or a negative number to switch either off explicitly.
    """
    max_bytes = LOADER_MAX_BYTES if max_bytes is None else max_bytes
    max_depth = LOADER_MAX_DEPTH if max_depth is None else max_depth
    if max_bytes is not None and max_bytes > 0:
        size = path.stat().st_size
        if size > max_bytes:
            raise FixtureTooLarge(
                f"{path.name} is {size} octets on disk and the fixture loader's max_bytes is "
                f"{max_bytes}. Refused before the file was read: `harness.LOADER_MAX_BYTES` is the "
                f"hosting application's bound on what one fixture may make this process allocate"
            )
    if path.suffix.lower() == ".json":
        text = path.read_text()
        if max_depth is not None and max_depth > 0:
            depth = json_nesting_depth(text)
            if depth > max_depth:
                raise FixtureTooDeep(
                    f"{path.name} nests {depth} containers deep and the fixture loader's "
                    f"max_depth is {max_depth}. Refused before json.loads: the decoder itself "
                    f"recurses once per container on CPython 3.11, so a twin measured after the "
                    f"parse is a twin the parse can fail on first (`harness.LOADER_MAX_DEPTH`)"
                )
        return json.loads(text)
    return path.read_bytes()


def _dump(objects: list[CDMBase]) -> list[dict]:
    return [obj.model_dump(mode="json") for obj in objects]


def _check_schema(dumped: list[dict], validators: dict[str, Any]) -> list[str]:
    problems = []
    for index, obj in enumerate(dumped):
        kind = obj.get("object_kind")
        validator = validators.get(kind)
        if validator is None:
            problems.append(f"object {index}: unknown object_kind {kind!r}")
            continue
        for error in sorted(validator.iter_errors(obj), key=str):
            location = "/".join(str(p) for p in error.absolute_path) or "(root)"
            problems.append(f"object {index} [{kind}] {location}: {error.message}")
    return problems


def _check_provenance(dumped: list[dict]) -> list[str]:
    problems = []
    for index, obj in enumerate(dumped):
        kind = obj.get("object_kind")
        source = obj.get("source") or {}
        for field in ("system", "adapter", "adapter_version"):
            if not source.get(field):
                problems.append(f"object {index} [{kind}]: source.{field} is missing or empty")
        if not isinstance(source.get("synthetic"), bool):
            problems.append(
                f"object {index} [{kind}]: source.synthetic must be stated as a boolean — "
                "an object that does not say whether it is exercise data cannot be filed"
            )
        if not obj.get("schema_version"):
            problems.append(f"object {index} [{kind}]: schema_version is missing")
        if not obj.get("source_ids"):
            problems.append(
                f"object {index} [{kind}]: source_ids is empty — the object cannot be traced "
                "back to any external identifier in the source system, so a redelivery cannot "
                "be recognised and an auditor cannot get back to the source record"
            )
        if kind == "event":
            for field in ("observed_at", "received_at"):
                if not obj.get(field):
                    problems.append(f"object {index} [event]: {field} is missing")
    return problems


def _diff(expected: Any, actual: Any, path: str = "") -> list[str]:
    """A path-by-path diff, because `!=` on two 400-line structures tells nobody anything."""
    if type(expected) is not type(actual) and not (
            isinstance(expected, (int, float)) and isinstance(actual, (int, float))):
        return [f"{path or '(root)'}: type {type(expected).__name__} -> {type(actual).__name__}"]
    if isinstance(expected, dict):
        out = []
        for key in sorted(set(expected) | set(actual)):
            here = f"{path}.{key}" if path else key
            if key not in expected:
                out.append(f"{here}: unexpected, now {actual[key]!r}")
            elif key not in actual:
                out.append(f"{here}: missing, was {expected[key]!r}")
            else:
                out += _diff(expected[key], actual[key], here)
        return out
    if isinstance(expected, list):
        if len(expected) != len(actual):
            return [f"{path or '(root)'}: length {len(expected)} -> {len(actual)}"]
        out = []
        for index, (e, a) in enumerate(zip(expected, actual)):
            out += _diff(e, a, f"{path}[{index}]")
        return out
    return [] if expected == actual else [f"{path or '(root)'}: {expected!r} -> {actual!r}"]


def _check_roundtrip(adapter: Adapter, objects: list[CDMBase], raw: Any,
                     raw_bytes: bytes | None = None) -> tuple[str, list[str]]:
    """For an adapter that also emits: does raw -> CDM -> raw lose anything?

    The brief asks for round-trip tests on bidirectional adapters, and the first of those
    (TAK / CoT) is the next one to be written — so the check exists before it is needed rather
    than being retrofitted around whatever the first egress adapter happens to do.

    A JSON emitter is measured with the same value-presence comparison as the lossless check,
    NOT with `==` on the two payloads: key order changes, a source that omitted an optional
    field gets it back explicitly. What must hold is that no VALUE from the original went
    missing on the way out.

    A NON-JSON EMITTER IS MEASURED UNDER THE TOLERANCE ITS CLASS DECLARES (2026-09-16). Until
    then this branch returned SKIP with a sentence pointing at `tests/` — a directory the wheel
    does not carry — and the suite's §3.6 rule 6 blocked L4 on that undeclared SKIP for every
    one of the eleven emitters whose own tests proved the round trip. Now `ROUNDTRIP_TOLERANCE`
    decides which half of a fixture pair carries the verdict, mirroring how `lossless` skips the
    byte fixture and relies on the parsed twin beside it:

      "bytes"   the BYTE fixture is judged — `from_cdm(to_cdm(raw))` against
                `adapter.roundtrip_reference(raw)`, octet for octet, and the first differing
                offset is named — and the parsed twin reports SKIP.
      "values"  the PARSED twin is judged — what `from_cdm` emitted is re-ingested and no
                source value may be absent, with `TRANSFORMS` and `ROUNDTRIP_TRANSFORMS`
                excused — and the byte fixture reports SKIP.

    Both SKIPs are the check saying which fixture it read instead, and `suite._fold` credits an
    adapter for the half it judged. Reported as SKIP — never PASS — for an ingest-only adapter.
    An unrun check that reads as passed is how a capability nobody tested acquires a green tick.
    """
    if adapter.direction == "ingest":
        return SKIP, []
    try:
        emitted = adapter.from_cdm(objects)
    except NotImplementedError:
        return FAIL, [
            f"roundtrip: adapter declares direction {adapter.direction!r} but from_cdm() "
            "raised NotImplementedError"
        ]
    except Exception as e:                              # noqa: BLE001 - same containment as
        return FAIL, [f"roundtrip: from_cdm raised {type(e).__name__}: {e}"]  # translate

    if isinstance(emitted, (bytes, bytearray, str)):
        try:
            emitted = json.loads(emitted)
        except ValueError:
            return _compare_emitted(adapter, emitted, raw, raw_bytes)
    if raw is None or not isinstance(emitted, (dict, list)):
        return SKIP, ["roundtrip: SKIPPED — no comparable structure on one side"]

    missing = lossless.value_presence_heuristic(raw, [emitted], type(adapter).TRANSFORMS)
    return (FAIL if missing else PASS), [
        f"roundtrip: value at {path_} = {value!r} was in the source payload but is absent "
        "from what from_cdm() emitted"
        for path_, value in sorted(missing.items())
    ]


def _compare_emitted(adapter: Adapter, emitted: bytes | bytearray | str, raw: Any,
                     raw_bytes: bytes | None) -> tuple[str, list[str]]:
    """The non-JSON half of `_check_roundtrip`, under the class's declared tolerance."""
    tolerance = type(adapter).ROUNDTRIP_TOLERANCE
    if tolerance == "bytes":
        if raw_bytes is None:
            return SKIP, ["roundtrip: SKIPPED — parsed twin of a byte fixture; the byte fixture "
                          "beside it carries the byte-exact comparison"]
        if isinstance(emitted, str):
            return FAIL, ["roundtrip: from_cdm returned text where the adapter declares a "
                          "byte-exact round trip (ROUNDTRIP_TOLERANCE 'bytes')"]
        reference = adapter.roundtrip_reference(bytes(raw_bytes))
        emitted = bytes(emitted)
        if emitted == reference:
            return PASS, []
        offset = next((i for i, (a, b) in enumerate(zip(emitted, reference)) if a != b),
                      min(len(emitted), len(reference)))
        return FAIL, [f"roundtrip: from_cdm emitted {len(emitted)} byte(s) against "
                      f"{len(reference)} ingested; first difference at offset {offset}"]
    # "values": re-ingest what was emitted and ask the never-drop question of it.
    if raw is None:
        return SKIP, ["roundtrip: SKIPPED — byte fixture under a declared 'values' tolerance; "
                      "the parsed twin beside it carries the value comparison"]
    try:
        again = _dump(adapter.to_cdm(
            emitted if isinstance(emitted, (bytes, bytearray)) else emitted.encode("utf-8")))
    except Exception as e:                              # noqa: BLE001 - same containment as
        return FAIL, [f"roundtrip: re-ingesting what from_cdm emitted raised "  # translate
                      f"{type(e).__name__}: {e}"]
    declared = {**type(adapter).TRANSFORMS, **type(adapter).ROUNDTRIP_TRANSFORMS}
    missing = lossless.value_presence_heuristic(raw, again, declared)
    return (FAIL if missing else PASS), [
        f"roundtrip: value at {path_} = {value!r} was in the source payload and is absent "
        "after egress and re-ingest"
        for path_, value in sorted(missing.items())
    ]


def _no_fixtures_message(adapter: Adapter, fixtures: pathlib.Path, *, existed: bool) -> str:
    """Name the adapter, the directory searched, and the rule that matched nothing.

    All three, because each answers a different question a reader has at the moment of failure:
    WHICH run was vacuous, WHERE it looked, and WHY nothing there counted. The subdirectory list
    is the fourth line and it is the one that usually solves it — a directory holding only
    `spec/` is a caller who pointed one level too high, and saying so beats making them look.
    """
    lines = [f"no fixtures found for adapter {adapter.name!r}: nothing was exercised, "
             f"so this run proves nothing and is a FAILURE rather than a pass",
             f"  directory searched : {fixtures}"]
    if not existed:
        lines.append("  directory          : DOES NOT EXIST")
    else:
        children = sorted(p.name + ("/" if p.is_dir() else "") for p in fixtures.iterdir())
        subdirs = [c for c in children if c.endswith("/")]
        lines.append(f"  directory          : exists, {len(children)} entr"
                     f"{'y' if len(children) == 1 else 'ies'}, none of them a fixture")
        if children:
            lines.append(f"  what is in it      : {', '.join(children)}")
        if subdirs:
            lines.append(f"  note               : the only content is in subdirector"
                         f"{'y' if len(subdirs) == 1 else 'ies'} "
                         f"{', '.join(subdirs)} — the harness does not recurse, so check "
                         f"whether the fixtures live one level down or in a different directory "
                         f"entirely (pinned standards live in spec/, fixtures do not)")
    lines.append(f"  pattern that matched nothing : {FIXTURE_PATTERN}")
    return "\n".join(lines)


def fixtures_required_message(reference: str, adapter_class: type[Adapter]) -> str:
    """The refusal of `--adapter module:ClassName` without `--fixtures`, minus the CLI's name.

    One text for this CLI and for `synapse conformance`, because the two refuse the same
    invocation for the same reason and a reader who meets both should read one sentence; each
    prints it behind its own name and returns its own exit constant.
    """
    return (f"--fixtures is required for {reference!r}: "
            f"{adapter_class.__module__}.{adapter_class.__qualname__} is not one of the "
            "adapters this package ships, so the package has no fixtures for it and will "
            "not guess at a directory")


def run(adapter: Adapter, fixtures: pathlib.Path, *, update_golden: bool = False,
        schema_dir: pathlib.Path | None = None) -> dict:
    """Replay every fixture. Returns a machine-readable report.

    Never raises on a bad FIXTURE — one unparseable payload is a fixture-level FAIL and the rest
    are still judged. It DOES raise `NoFixturesFound` on a bad INVOCATION, which is a different
    thing: a directory with no fixtures in it has no per-fixture verdict to record, so there is
    nothing for a report to carry and a report saying "0 failed" would be true and misleading.
    Raising here rather than in `main` puts the check in front of every caller, tests included.
    """
    if schema_dir is not None:
        published = {}
        for path in sorted(schema_dir.glob("*.schema.json")):
            published[path.name.removesuffix(".schema.json")] = json.loads(path.read_text())
        # A `--schemas` directory holding nothing is refused, for the same reason a fixtures
        # directory holding nothing is. It used to be survivable and the survival was the worst
        # kind: `published` stayed empty, so `validators` stayed empty, so EVERY object came back
        # "unknown object_kind 'entity'" — thirty-two fixtures' worth of failures blaming the
        # objects for a directory that was not there. The cause has to be named where it is known.
        if not published:
            raise NoSchemasFound(
                f"no *.schema.json in {schema_dir}"
                + ("" if schema_dir.is_dir() else " — the directory DOES NOT EXIST") +
                ". Check 2 validates against the PUBLISHED schemas, so with none of them there is "
                "nothing to validate against and every object would be reported as an unknown "
                "kind. Point --schemas at the published directory, write one with "
                "`python -m synapse_cdm.schemas --out <dir>`, or omit --schemas to generate them "
                "in-process from the models"
            )
        source_of_schemas = str(schema_dir)
    else:
        published = schemas.generate()
        source_of_schemas = "generated in-process from the models"
    validators = {
        # `schemas.validator_for` (audit F04): ECMA-262 `pattern`, `format` asserted — the
        # answer a consumer in another language gets, not Python `re`'s.
        kind: schemas.validator_for(published[kind])
        for kind in ("entity", "event", "track", "plan_object") if kind in published
    }

    # README.md is skipped by name, not by extension: a fixture directory that documents
    # itself is right, and for a binary format it is close to mandatory — an armoured AIS
    # payload cannot carry a comment the way a CoT fixture's XML can. Only that one name,
    # because a format whose payloads really are Markdown should still be replayable.
    #
    # An ABSENT directory and a directory holding no fixtures are the same failure and get the
    # same treatment, because they have the same meaning: nothing was exercised. Distinguishing
    # them in the exit code would be distinguishing two ways of proving nothing.
    if not fixtures.is_dir():
        raise NoFixturesFound(_no_fixtures_message(adapter, fixtures, existed=False))
    # A directory NAMED `golden` is a golden directory and not a fixture set, whatever it holds.
    paths = select_fixtures(fixtures) if fixtures.name != GOLDEN_DIR else []
    if not paths:
        raise NoFixturesFound(_no_fixtures_message(adapter, fixtures, existed=True))
    golden_dir = fixtures / GOLDEN_DIR
    results = []
    reference_normalised: list[str] = []
    for path in paths:
        entry: dict[str, Any] = {"fixture": path.name, "objects": 0,
                                 "checks": {}, "problems": []}
        try:
            raw = load_raw(path)
            objects = adapter.to_cdm(raw)
            dumped = _dump(objects)
            entry["objects"] = len(dumped)
            entry["kinds"] = [o.get("object_kind") for o in dumped]
            entry["checks"]["translate"] = PASS
        except Exception as e:                        # noqa: BLE001 - one fixture must not
            entry["checks"]["translate"] = FAIL       # take the run down; see the docstring
            entry["problems"].append(f"to_cdm raised {type(e).__name__}: {e}")
            entry["traceback"] = traceback.format_exc()
            for check in ("schema", "provenance", "lossless", "roundtrip", "golden"):
                entry["checks"][check] = SKIP
            entry["verdict"] = FAIL
            results.append(entry)
            continue

        schema_problems = _check_schema(dumped, validators)
        entry["checks"]["schema"] = FAIL if schema_problems else PASS
        entry["problems"] += schema_problems

        provenance_problems = _check_provenance(dumped)
        entry["checks"]["provenance"] = FAIL if provenance_problems else PASS
        entry["problems"] += provenance_problems

        raw_for_lossless = raw if isinstance(raw, (dict, list)) else None
        if raw_for_lossless is None:
            # A bytes fixture has no leaf structure to harvest. Reported as SKIP rather than
            # PASS: an unrun check must never read as a passed one.
            entry["checks"]["lossless"] = SKIP
            entry["problems"].append(
                "lossless: SKIPPED — non-JSON fixture has no comparable leaf structure; "
                "an XML/binary adapter should also ship a parsed-form fixture"
            )
        else:
            missing = lossless.value_presence_heuristic(raw_for_lossless, dumped,
                                                        type(adapter).TRANSFORMS)
            entry["checks"]["lossless"] = FAIL if missing else PASS
            entry["problems"] += [
                f"lossless: source value at {path_} = {value!r} appears nowhere in the CDM "
                "output — park it in attributes/payload or declare it in TRANSFORMS"
                for path_, value in sorted(missing.items())
            ]
            # F02: the path-bound ledger, wherever the adapter declares MAPPINGS. Its verdict
            # is folded into the SAME column — a LOST leaf fails `lossless` — and the entry
            # records which basis the verdict rests on. Without MAPPINGS the column is the
            # heuristic alone, and says so; a heuristic PASS is not proof of preservation.
            mappings = getattr(type(adapter), "MAPPINGS", None) or {}
            if mappings:
                book = lossless.ledger(raw_for_lossless, dumped, mappings,
                                       unsupported=_unsupported_paths(adapter))
                entry["preservation"] = book.as_dict(limit=DIAGNOSTIC_LIMIT)
                if book.lost:
                    entry["checks"]["lossless"] = FAIL
                entry["problems"] += [f"lossless: {line}"
                                      for line in book.problem_lines()[:DIAGNOSTIC_LIMIT]]
            else:
                entry["preservation"] = {"basis": "heuristic", "declared_mappings": 0}

        raw_bytes = bytes(raw) if isinstance(raw, (bytes, bytearray)) else None
        entry["checks"]["roundtrip"], roundtrip_problems = _check_roundtrip(
            adapter, objects, raw_for_lossless, raw_bytes)
        entry["problems"] += roundtrip_problems
        if raw_bytes is not None and adapter.direction != "ingest" \
                and adapter.roundtrip_reference(raw_bytes) != raw_bytes:
            reference_normalised.append(path.name)

        golden_path = golden_dir / f"{path.stem}.cdm.json"
        rendered = canonical.serialise(dumped)
        if update_golden:
            golden_dir.mkdir(parents=True, exist_ok=True)
            golden_path.write_text(rendered)
            entry["checks"]["golden"] = "WROTE"
        elif not golden_path.exists():
            entry["checks"]["golden"] = SKIP
            entry["problems"].append(
                f"golden: {golden_path} does not exist — run with --update-golden and REVIEW "
                "the result before committing it"
            )
        else:
            differences = _diff(json.loads(golden_path.read_text()), dumped)
            entry["checks"]["golden"] = FAIL if differences else PASS
            entry["problems"] += [f"golden: {d}" for d in differences]

        entry["verdict"] = FAIL if any(v == FAIL for v in entry["checks"].values()) else PASS
        results.append(entry)

    return {
        "adapter": {"name": adapter.name, "version": adapter.version,
                    "direction": adapter.direction, "system": adapter.system,
                    "class": f"{type(adapter).__module__}.{type(adapter).__qualname__}"},
        "schemas": source_of_schemas,
        "transforms": dict(type(adapter).TRANSFORMS),
        # F02, 2026-09-19: which basis the `lossless` column rests on for this adapter, and the
        # declared mappings, published so a heuristic-only verdict is visible in every report.
        "preservation": {
            "basis": "ledger" if getattr(type(adapter), "MAPPINGS", None) else "heuristic",
            "declared_mappings": len(getattr(type(adapter), "MAPPINGS", None) or {}),
            "mappings": {path: [m.to for m in (v if isinstance(v, (tuple, list)) else (v,))]
                         for path, v in (getattr(type(adapter), "MAPPINGS", None) or {}).items()},
        },
        # 2026-09-16: the round-trip declarations, published for the reason `transforms` is —
        # an exemption the report does not print is an exemption nobody can see. A second
        # ADDED key beside `check_letters`; nothing else in this report moves.
        "roundtrip": {"tolerance": type(adapter).ROUNDTRIP_TOLERANCE,
                      "transforms": dict(type(adapter).ROUNDTRIP_TRANSFORMS),
                      "reference_normalised": reference_normalised},
        "fixtures": str(fixtures),
        "results": results,
        "passed": sum(1 for r in results if r["verdict"] == PASS),
        "failed": sum(1 for r in results if r["verdict"] == FAIL),
        # F2.1, 2026-09-07: the six checks ARE the conformance suite's A-F, and the letters are
        # published BESIDE the existing keys rather than replacing them. Re-keying the report by
        # letter would break every consumer of `cdm-harness --json` in order to save a lookup,
        # and `--json` output is a surface this package has published since 1.0.0. Nothing else
        # in this report moves and the text rendering is untouched.
        "check_letters": dict(CHECK_LETTERS),
    }


def render_roster(adapters: dict[str, type[Adapter]]) -> str:
    """The registered names, with what a caller needs in order to choose one.

    WHY THE ROSTER IS PRINTABLE AT ALL
    ----------------------------------
    Until `--list-adapters` the only way to see it was to get it wrong: `--adapter typo` raises
    `LookupError: unknown adapter 'typo'; registered: …`, and a bare invocation gets argparse's
    usage line, which names the FLAG and not one value it takes. So the answer to "what can I
    run this against?" was reachable only through a failure, and a tool whose inventory is a
    side effect of an error message is a tool that has to be misused before it can be used.

    The version, direction and fixture directory are here because each answers a question the
    name alone leaves open, and the third one especially: `stanag4676` replays `fixtures/nits`,
    and that split was folklore until `Adapter.fixture_dir` made it a declaration. Printing it
    means a reader never has to learn it from a vacuous green run.
    """
    if not adapters:
        # An empty roster is a broken import, not an answer, and it must not print as a tidy
        # empty table. `discover()` populates the registry by import side effect; nothing else
        # empties it, so reaching here means the adapters package did not load.
        return ("no adapters are registered. synapse_cdm.adapters failed to import, because "
                "every adapter this package ships registers itself when its module is imported "
                "— this is a broken installation rather than an empty inventory")
    width = max(len(name) for name in adapters)
    lines = [
        f"{len(adapters)} adapters registered. Replay any of them with "
        f"`--adapter <name>` and no `--fixtures`: the fixtures came with the package.",
        "",
        f"{'name'.ljust(width)}  {'version'.ljust(7)}  {'direction'.ljust(13)}  "
        f"{'fixtures'.ljust(11)}  {'system'.ljust(10)}  binding",
        "-" * (width + 2 + 7 + 2 + 13 + 2 + 11 + 2 + 10 + 2 + 28),
    ]
    for name, cls in adapters.items():
        # F05 (2026-09-20): the wire binding, so `stanag4676`'s `provisional-internal-profile`
        # is read in the same table as its name — a reader choosing an adapter from this listing
        # would otherwise take every row for the standard's own encoding.
        lines.append(f"{name.ljust(width)}  {cls.version.ljust(7)}  "
                     f"{cls.direction.ljust(13)}  "
                     f"{(cls.fixture_dir or cls.name).ljust(11)}  {cls.system.ljust(10)}  "
                     f"{cls.metadata.binding.value}")
    return "\n".join(lines)


_COLUMNS = ("translate", "schema", "provenance", "lossless", "roundtrip", "golden")

#: The suite's letters for the six columns above (ARCHITECTURE.md §8: these are the HARNESS
#: namespace, not the SC-OES tool's dimensions). Derived from `_COLUMNS` so a seventh column
#: cannot acquire a letter by being forgotten here.
CHECK_LETTERS = tuple(zip(_COLUMNS, "ABCDEF"))


def render_report(report: dict) -> str:
    adapter = report["adapter"]
    width = max([len(r["fixture"]) for r in report["results"]] + [7])
    lines = [
        f"adapter   {adapter['name']} {adapter['version']} ({adapter['direction']}) "
        f"-> system {adapter['system']}",
        f"class     {adapter['class']}",
        f"schemas   {report['schemas']}",
        f"fixtures  {report['fixtures']}",
        "",
        f"{'fixture'.ljust(width)}  obj  " + "  ".join(c[:9].ljust(9) for c in _COLUMNS)
        + "  verdict",
        "-" * (width + 2 + 5 + len(_COLUMNS) * 11 + 9),
    ]
    for result in report["results"]:
        cells = "  ".join(result["checks"].get(c, "-").ljust(9) for c in _COLUMNS)
        lines.append(f"{result['fixture'].ljust(width)}  {result['objects']:>3}  {cells}  "
                     f"{result['verdict']}")
    if report["transforms"]:
        lines += ["", "declared transforms (exempt from the lossless HEURISTIC, printed every run "
                      "so the exemption is visible; they exempt nothing from the ledger):"]
        lines += [f"  {path}: {reason}" for path, reason in sorted(report["transforms"].items())]
    preservation = report.get("preservation") or {}
    if preservation.get("basis") == "ledger":
        lines += ["", f"lossless basis: LEDGER — {preservation['declared_mappings']} declared "
                      "mapping(s); every source leaf is bound to a destination and a rule, and a "
                      "LOST leaf fails the column"]
        lines += [f"  {path} -> {', '.join(dests)}"
                  for path, dests in sorted(preservation.get("mappings", {}).items())]
    else:
        lines += ["", "lossless basis: HEURISTIC — the adapter declares no MAPPINGS, so the column "
                      "is value presence only (one surviving value satisfies every field holding "
                      "it) and a PASS here is NOT proof of preservation"]
    roundtrip = report.get("roundtrip")
    if roundtrip and adapter["direction"] != "ingest":
        lines += ["", f"roundtrip tolerance: {roundtrip['tolerance']} (the comparison the "
                      "roundtrip column makes, printed every run so the declaration is visible)"]
        if roundtrip["transforms"]:
            lines += ["  re-stamped on egress (exempt from the roundtrip check):"]
            lines += [f"    {path}: {reason}"
                      for path, reason in sorted(roundtrip["transforms"].items())]
        if roundtrip["reference_normalised"]:
            lines += ["  compared against roundtrip_reference(raw), not raw, for: "
                      + ", ".join(roundtrip["reference_normalised"])]
    problems = [(r["fixture"], p) for r in report["results"] for p in r["problems"]]
    if problems:
        lines += ["", "problems:"]
        lines += [f"  [{fixture}] {problem}" for fixture, problem in problems]
    lines += ["", f"{report['passed']} passed, {report['failed']} failed"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # NOT `required=True` any more: `--list-adapters` is the one invocation that legitimately
    # names no adapter, and argparse would refuse it before main() could answer. The requirement
    # is re-imposed below with `parser.error`, which keeps the exit status and the usage line
    # byte-identical to what a missing `--adapter` produced before.
    parser.add_argument("--adapter", default=None,
                        help="registered name (pntmap) or module:ClassName for an adapter "
                             "outside this package. See --list-adapters")
    parser.add_argument("--list-adapters", action="store_true",
                        help="print the registered adapters and exit, without needing a failed "
                             "lookup to see them. Honours --json")
    parser.add_argument("--fixtures", type=pathlib.Path, default=None,
                        help="directory of payloads to replay. Optional for an adapter this "
                             "package ships — omitted, the fixtures that came with the "
                             "installed package are used, wherever it is installed. Required "
                             "for an adapter given as module:ClassName")
    parser.add_argument("--schemas", type=pathlib.Path, default=None,
                        help="validate against the published schemas in this directory "
                             "instead of regenerating them from the models")
    parser.add_argument("--now", default=None,
                        help="freeze received_at at this RFC 3339 instant "
                             f"(default {times.render(times.FROZEN_NOW)})")
    parser.add_argument("--synthetic", default="true", choices=("true", "false"),
                        help="value stamped into source.synthetic (default true)")
    parser.add_argument("--update-golden", action="store_true",
                        help="overwrite the golden files with this run's output — REVIEW the "
                             "diff before committing, this is how a defect becomes expected")
    parser.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    args = parser.parse_args(argv)

    if args.list_adapters:
        # Answered before anything else and before --adapter is required: a caller who does not
        # know the names cannot be asked for one in order to be told them.
        known = roster()
        if args.json:
            print(json.dumps({name: {"version": cls.version, "direction": cls.direction,
                                     "system": cls.system,
                                     "fixtures": cls.fixture_dir or cls.name,
                                     "binding": cls.metadata.binding.value}
                              for name, cls in known.items()}, indent=2))
        else:
            print(render_roster(known))
        # Exit 0 even for an empty roster: `--list-adapters` answers a question, and "none" is a
        # true answer to it. The broken-installation case is stated in the text rather than in
        # the status, because a caller scripting this reads the list and not the code.
        return 0
    if args.adapter is None:
        # The same refusal argparse gave when the flag was `required=True` — same exit status,
        # same usage line — with the one addition that makes it actionable.
        parser.error("--adapter is required (or --list-adapters to see the registered names)")

    frozen: _dt.datetime = times.parse(args.now) if args.now else times.FROZEN_NOW
    adapter_class = load_adapter(args.adapter)
    adapter = adapter_class(clock=times.frozen_clock(frozen),
                            synthetic=args.synthetic == "true")

    fixtures = args.fixtures
    if fixtures is None:
        # Refused rather than guessed for an adapter from outside this package. `synapse_cdm`
        # ships fixtures for the adapters IT ships; for `module:ClassName` it would be inventing
        # `synapse_cdm/fixtures/<their name>`, which either does not exist — a confusing failure
        # naming a directory the caller never mentioned — or DOES, because the name collides with
        # one of ours, and then a third-party adapter is silently judged against our payloads and
        # every check passes or fails for reasons that have nothing to do with it.
        if not is_shipped(adapter_class):
            print(f"harness: {fixtures_required_message(args.adapter, adapter_class)}",
                  file=sys.stderr)
            return EXIT_NO_FIXTURES
        fixtures = packaged_fixtures(adapter_class)

    try:
        report = run(adapter, fixtures, update_golden=args.update_golden,
                     schema_dir=args.schemas)
    except (NoFixturesFound, NoSchemasFound) as e:
        # Printed to stderr and NOT as a report: --json callers must not receive a well-formed
        # report for a run that did not happen, because the shape of a report is a claim that
        # fixtures were judged.
        print(f"harness: {e}", file=sys.stderr)
        return EXIT_NO_FIXTURES
    print(json.dumps(report, indent=2) if args.json else render_report(report))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
