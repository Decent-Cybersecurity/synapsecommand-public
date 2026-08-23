"""The validation harness: replay recorded payloads through an adapter, judge the output.

    python -m synapse_cdm.harness --adapter pntmap --fixtures packages/cdm/synapse_cdm/fixtures/pntmap

WHAT IT IS FOR
--------------
Today: the gate an adapter has to pass before it ships. Tomorrow: the gate GENERATED adapters
have to pass, which is why nothing in this file knows anything about any particular adapter.
It resolves the adapter by name or by `module:ClassName`, reads whatever fixtures it is
pointed at, and applies the same five checks to all of them. An adapter the harness has never
heard of is validated by the same code as the reference one, and that property is the whole
design constraint.

THE FIVE CHECKS, AND WHY EACH ONE EARNS ITS PLACE
-------------------------------------------------
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
4. lossless    no source value vanished. See lossless.py. Declared transforms are printed.
5. golden      the output matches the recorded expectation byte for byte, under a FROZEN
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

import jsonschema

from synapse_cdm import lossless, schemas, times
from synapse_cdm.adapter import Adapter, load_adapter
from synapse_cdm.models import CDMBase

GOLDEN_DIR = "golden"
PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

#: The rule that selects a fixture, written down so a run that selects NOTHING can quote it.
#: It is not a glob — it is three predicates over the directory's immediate children — and the
#: message says so rather than printing a `*` that would suggest a pattern the code never uses.
FIXTURE_PATTERN = ("immediate children of the directory that are files, "
                   "excluding dotfiles and README.md")

#: Exit status for a run that exercised no fixture. Distinct from 1, which means fixtures ran
#: and some failed: this one means the INVOCATION was wrong, and conflating the two would tell a
#: caller to debug an adapter when the thing to fix is the path they passed.
EXIT_NO_FIXTURES = 2


class NoFixturesFound(RuntimeError):
    """A harness run that matched zero fixtures. Raised, never reported as a pass.

    THE FAILURE THIS EXISTS FOR
    ---------------------------
    `--adapter stanag4676 --fixtures fixtures/stanag4676` used to print "0 passed, 0 failed" and
    exit 0. That directory holds only a `spec/` subdirectory of pinned standards; the adapter's
    fixtures are in `fixtures/nits`. So a gate sweep over all nine adapters reported nine greens
    while one of them had replayed nothing, and the run that proves the least looks exactly like
    the run that proves the most.

    It is the same failure `test_cdm_prose_counts.py` guards in prose — "a regex that silently
    matches nothing is worse than no test at all, it reads as a passing check on a site nobody is
    checking any more" — reached from the other direction. A verification tool's worst output is
    not a false failure; it is a true-looking pass over an empty set.
    """


def _load_raw(path: pathlib.Path) -> Any:
    """Fixtures are JSON on disk; adapters may take bytes or dict.

    A `.bin`/`.txt`/`.xml` fixture is handed over as raw bytes untouched — a STANAG or CoT XML
    adapter must be replayable from the bytes it will really receive, and pre-parsing it here
    would test a parser the adapter does not use in production.
    """
    if path.suffix.lower() == ".json":
        return json.loads(path.read_text())
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


def _check_roundtrip(adapter: Adapter, objects: list[CDMBase],
                     raw: Any) -> tuple[str, list[str]]:
    """For an adapter that also emits: does raw -> CDM -> raw lose anything?

    The brief asks for round-trip tests on bidirectional adapters, and the first of those
    (TAK / CoT) is the next one to be written — so the check exists before it is needed rather
    than being retrofitted around whatever the first egress adapter happens to do.

    Equality is measured with the same value-presence comparison as the lossless check, NOT
    with `==` on the two payloads. A byte-equal round trip is not achievable and not the point:
    key order changes, a source that omitted an optional field gets it back explicitly, XML
    attribute order is arbitrary. What must hold is that no VALUE from the original went
    missing on the way out, which is the property an operator on the receiving TAK client
    actually depends on.

    Reported as SKIP — never PASS — for an ingest-only adapter. An unrun check that reads as
    passed is how a capability nobody tested acquires a green tick.
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
            return SKIP, [
                "roundtrip: SKIPPED — from_cdm returned non-JSON bytes (XML, USMTF), which "
                "this check cannot compare structurally; the adapter must ship its own "
                "round-trip test in tests/"
            ]
    if raw is None or not isinstance(emitted, (dict, list)):
        return SKIP, ["roundtrip: SKIPPED — no comparable structure on one side"]

    missing = lossless.unrepresented(raw, [emitted], type(adapter).TRANSFORMS)
    return (FAIL if missing else PASS), [
        f"roundtrip: value at {path_} = {value!r} was in the source payload but is absent "
        "from what from_cdm() emitted"
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
        source_of_schemas = str(schema_dir)
    else:
        published = schemas.generate()
        source_of_schemas = "generated in-process from the models"
    validators = {
        kind: jsonschema.Draft202012Validator(published[kind])
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
    paths = sorted(p for p in fixtures.iterdir()
                   if p.is_file() and not p.name.startswith(".")
                   and p.name != "README.md" and p.parent.name != GOLDEN_DIR)
    if not paths:
        raise NoFixturesFound(_no_fixtures_message(adapter, fixtures, existed=True))
    golden_dir = fixtures / GOLDEN_DIR
    results = []
    for path in paths:
        entry: dict[str, Any] = {"fixture": path.name, "objects": 0,
                                 "checks": {}, "problems": []}
        try:
            raw = _load_raw(path)
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
            missing = lossless.unrepresented(raw_for_lossless, dumped,
                                             type(adapter).TRANSFORMS)
            entry["checks"]["lossless"] = FAIL if missing else PASS
            entry["problems"] += [
                f"lossless: source value at {path_} = {value!r} appears nowhere in the CDM "
                "output — park it in attributes/payload or declare it in TRANSFORMS"
                for path_, value in sorted(missing.items())
            ]

        entry["checks"]["roundtrip"], roundtrip_problems = _check_roundtrip(
            adapter, objects, raw_for_lossless)
        entry["problems"] += roundtrip_problems

        golden_path = golden_dir / f"{path.stem}.cdm.json"
        rendered = json.dumps(dumped, indent=2, sort_keys=True) + "\n"
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
        "fixtures": str(fixtures),
        "results": results,
        "passed": sum(1 for r in results if r["verdict"] == PASS),
        "failed": sum(1 for r in results if r["verdict"] == FAIL),
    }


_COLUMNS = ("translate", "schema", "provenance", "lossless", "roundtrip", "golden")


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
        lines += ["", "declared transforms (exempt from the lossless check, printed every run "
                      "so the exemption is visible):"]
        lines += [f"  {path}: {reason}" for path, reason in sorted(report["transforms"].items())]
    problems = [(r["fixture"], p) for r in report["results"] for p in r["problems"]]
    if problems:
        lines += ["", "problems:"]
        lines += [f"  [{fixture}] {problem}" for fixture, problem in problems]
    lines += ["", f"{report['passed']} passed, {report['failed']} failed"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--adapter", required=True,
                        help="registered name (pntmap) or module:ClassName for an adapter "
                             "outside this package")
    parser.add_argument("--fixtures", required=True, type=pathlib.Path)
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

    frozen: _dt.datetime = times.parse(args.now) if args.now else times.FROZEN_NOW
    adapter_class = load_adapter(args.adapter)
    adapter = adapter_class(clock=times.frozen_clock(frozen),
                            synthetic=args.synthetic == "true")
    try:
        report = run(adapter, args.fixtures, update_golden=args.update_golden,
                     schema_dir=args.schemas)
    except NoFixturesFound as e:
        # Printed to stderr and NOT as a report: --json callers must not receive a well-formed
        # report for a run that did not happen, because the shape of a report is a claim that
        # fixtures were judged.
        print(f"harness: {e}", file=sys.stderr)
        return EXIT_NO_FIXTURES
    print(json.dumps(report, indent=2) if args.json else render_report(report))
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
