"""The current-contracts page's generated block: derived from the package, never typed.

WHY THIS EXISTS
---------------
`docs/docs/current-contracts.mdx` is the one page a new implementer reads first: the version
axes in force, the frozen contracts the compatibility verdicts rest on, the conformance worker's
deadlines and outcome codes, the five declared bounds, the evidence categories and what each
maturity rung needs. Every one of those is a figure, and a figure typed into a page is the defect
this repository has repaired most often — a count that was right when it was written, a line
citation that survived the code moving under it (`VERSIONING.md`'s axis table cited `version.py`
line numbers and had to be re-pointed at every release; audit remediation F09, 2026-09-20,
replaced them with the constant's name and this block).

So the page STATES nothing of its own inside the markers below. The block between
`{/* BEGIN GENERATED … */}` and `{/* END GENERATED */}` is rendered from `synapse_cdm.version`,
`synapse_cdm.suite`, `synapse_cdm.harness`, `synapse_cdm.manifest` and `synapse_cdm.evidence` —
read from the installed package, exactly as `python -m synapse_cdm.support_matrix` renders the
support matrix — and `--check` fails when the page's block is not what the package renders today.
Nothing in the block depends on the platform it was rendered on: the platform-conditional table
(what `setrlimit` enforces where) lives on the deployment-envelope page and is asserted by
`tests/test_cdm_resource_envelope.py`, so a block rendered on macOS and one rendered on Linux CI
compare equal.

    python gates/current_contracts.py --check    # exit 0 current; 1 missing, stale or markerless
    python gates/current_contracts.py --write    # re-render the block in place

The prose outside the markers is hand-written and this gate does not touch it. The markers are
MDX comments (`{/* … */}`), because an HTML comment is not MDX and would fail the site build.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

from synapse_cdm import evidence, harness, manifest, suite, version

REPO = pathlib.Path(__file__).resolve().parents[1]
PAGE = REPO / "docs" / "docs" / "current-contracts.mdx"
BEGIN = "{/* BEGIN GENERATED — rendered by gates/current_contracts.py; edit nothing until END */}"
END = "{/* END GENERATED */}"

#: The six version axes `version.py` declares as constants, in `VERSIONING.md` §2's order, with the
#: specification's name where it differs from the tree's. Read by name, so a renamed constant
#: fails here rather than going stale.
AXES = (
    ("Python package", "PACKAGE_VERSION"),
    ("CDM schema (the specification's `CDM_SCHEMA_VERSION`)", "SCHEMA_VERSION"),
    ("SC-OES specification", "SC_OES_VERSION"),
    ("Adapter API", "ADAPTER_API_VERSION"),
    ("Manifest schema", "MANIFEST_SCHEMA_VERSION"),
    ("Evidence schema", "EVIDENCE_SCHEMA_VERSION"),
)

#: The suite's worker figures, each the constant it is read from.
WORKER_FIGURES = (
    ("per-case parser deadline", "DEFAULT_TIMEOUT_S", "seconds"),
    ("worker start-up deadline", "DEFAULT_STARTUP_TIMEOUT_S", "seconds"),
    ("grace between `terminate()` and `kill()`", "KILL_GRACE_S", "seconds"),
    ("worker restarts per check before the rest is `cases_not_run`",
     "DEFAULT_MAX_WORKER_RESTARTS", "restarts"),
    ("largest answer a worker may send", "OUTPUT_CAP_BYTES", "octets"),
)


def _code(value: object) -> str:
    return f"`{value}`"


def _table(header: tuple[str, ...], rows: list[tuple[str, ...]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out.extend("| " + " | ".join(row) + " |" for row in rows)
    return out


def _mdx(text: str) -> str:
    """Braces and angle brackets outside code spans are MDX expressions and JSX, and a bar is a
    table cell boundary anywhere; escape them so a sentence read off the code cannot break the
    page."""
    parts = text.split("`")
    for index in range(0, len(parts), 2):
        parts[index] = (parts[index].replace("{", "&#123;").replace("}", "&#125;")
                        .replace("<", "&lt;"))
    return "`".join(parts).replace("|", "\\|")


def render() -> str:
    """The block, markers included, derived from the package on this interpreter."""
    lines = [BEGIN, ""]

    lines.append("### Version axes in force")
    lines.append("")
    lines.append("Read off `synapse_cdm.version` by constant name; the reading beside each is the "
                 "one the installed package answers with today.")
    lines.append("")
    axis_rows = [(axis, _code(const), _code(getattr(version, const))) for axis, const in AXES]
    lines.extend(_table(("axis", "constant", "reading"), axis_rows))
    lines.append("")
    frozen = ", ".join(_code(v) for v in version.KNOWN_CONTRACTS)
    lines.append(f"Frozen CDM contracts the compatibility verdicts rest on (`KNOWN_CONTRACTS`): "
                 f"{frozen}. A minor of the current major outside this set is `UNKNOWN`, which "
                 f"`compatible()` reads as `False`.")
    lines.append("")

    lines.append("### Compatibility verdicts over the frozen contracts")
    lines.append("")
    lines.append("Every pair `version.assess(written_with, read_by)` answers for, as it answers "
                 "today. The basis names the frozen-schema matrix test or the "
                 "`additionalProperties: false` rule the verdict rests on.")
    lines.append("")
    verdict_rows = []
    for writer in version.KNOWN_CONTRACTS:
        for reader in version.KNOWN_CONTRACTS:
            reading = version.assess(writer, reader)
            verdict_rows.append((_code(writer), _code(reader), _code(reading.verdict.name),
                                 _code(reading.direction.name), _mdx(reading.basis)))
    lines.extend(_table(("written with", "read by", "verdict", "direction", "basis"),
                        verdict_rows))
    lines.append("")

    lines.append("### The conformance worker")
    lines.append("")
    lines.append("Checks H (malformed input) and N (parser robustness) run every adversarial "
                 "case in a spawned worker process; the figures are `synapse_cdm.suite`'s "
                 "defaults, each overridable on the command line.")
    lines.append("")
    worker_rows = [(what, _code(const), f"{getattr(suite, const)} {unit}")
                   for what, const, unit in WORKER_FIGURES]
    lines.extend(_table(("figure", "constant", "default"), worker_rows))
    lines.append("")
    codes = ", ".join(_code(c) for c in sorted(suite.OUTCOME_CODES))
    failing = ", ".join(_code(c) for c in sorted(suite.FAILING_OUTCOMES))
    lines.append(f"Per-case outcome codes: {codes}. Every code but `{suite.PARSER_REJECTED}` "
                 f"FAILS the check: {failing}. A deadline that fires is reported as the code, "
                 f"never as a duration.")
    lines.append("")
    exit_rows = [(_code(name), str(getattr(suite, name))) for name in
                 ("EXIT_OK", "EXIT_FAILED", "EXIT_USAGE", "EXIT_INTERNAL")]
    lines.extend(_table(("exit code", "value"), exit_rows))
    lines.append("")

    lines.append("### Bounds on what a fixture loader and an adapter accept")
    lines.append("")
    loader_bytes = ("unset — the hosting application's figure, passed as `max_bytes`; `0` "
                    "switches the guard off" if harness.LOADER_MAX_BYTES is None
                    else f"{harness.LOADER_MAX_BYTES} octets")
    loader_rows = [
        ("harness fixture loader, nesting", "`LOADER_MAX_DEPTH`", f"{harness.LOADER_MAX_DEPTH}"),
        ("harness fixture loader, size", "`LOADER_MAX_BYTES`", loader_bytes),
        ("preservation diagnostics per fixture entry", "`DIAGNOSTIC_LIMIT`",
         f"{harness.DIAGNOSTIC_LIMIT}"),
    ]
    lines.extend(_table(("bound", "constant", "reading"), loader_rows))
    lines.append("")
    declared = [name for name in manifest.Limits.model_fields
                if name not in ("absent_because", "declared_because")]
    lines.append("Every adapter declares each of these `capabilities.limits` fields, as a number "
                 "with its basis in `declared_because` or as absent with its reason in "
                 "`absent_because`: " + ", ".join(_code(n) for n in declared) + ".")
    lines.append("")
    bindings = ", ".join(_code(b.value) for b in manifest.WireBinding)
    lines.append(f"Wire binding, required on every manifest and never defaulted: {bindings}.")
    lines.append("")

    lines.append("### Streaming")
    lines.append("")
    lines.extend(_table(("aspect", "status"),
                        [(_code(k), _mdx(v)) for k, v in suite.STREAMING_STATUS.items()]))
    lines.append("")

    lines.append("### Evidence categories and what each maturity rung needs")
    lines.append("")
    cats = ", ".join(_code(c.value) for c in evidence.EvidenceCategory)
    lines.append(f"The five kinds of evidence a record reads (`evidence_categories`, each "
                 f"`PRESENT`, `ABSENT` or `NOT_APPLICABLE`): {cats}. The first two this "
                 f"repository produces itself; the last three only an exercise report from an "
                 f"outside party can make `PRESENT`.")
    lines.append("")
    rung_rows = [(_code(rung), ", ".join(_code(c.value) for c in needs) or "—")
                 for rung, needs in evidence.RUNG_CATEGORIES.items()]
    lines.extend(_table(("rung", "categories that must be `PRESENT` (or `NOT_APPLICABLE`)"),
                        rung_rows))
    lines.append("")
    lines.append(END)
    return "\n".join(lines) + "\n"


def split(text: str) -> tuple[str, str, str] | None:
    """(before, block, after) around the markers, or None when the page has no block."""
    start = text.find(BEGIN)
    stop = text.find(END)
    if start == -1 or stop == -1 or stop < start:
        return None
    stop += len(END) + 1
    return text[:start], text[start:stop], text[stop:]


def check(page: pathlib.Path = PAGE) -> list[str]:
    """Reasons the page is not current — empty when it is."""
    if not page.exists():
        return [f"{page} is missing"]
    parts = split(page.read_text(encoding="utf-8"))
    if parts is None:
        return [f"{page} carries no generated block between the markers"]
    if parts[1] != render():
        return [f"{page}'s generated block is not what the package renders today; "
                f"run `python gates/current_contracts.py --write`"]
    return []


def write(page: pathlib.Path = PAGE) -> None:
    """Re-render the block in place; the prose outside the markers is not touched."""
    parts = split(page.read_text(encoding="utf-8"))
    if parts is None:
        raise SystemExit(f"{page} carries no generated block to replace; add the markers first")
    page.write_text(parts[0] + render() + parts[2], encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true", help="fail when the block is stale")
    action.add_argument("--write", action="store_true", help="re-render the block in place")
    parser.add_argument("--page", type=pathlib.Path, default=PAGE)
    args = parser.parse_args(argv)
    if args.write:
        write(args.page)
        print(f"rendered {args.page.relative_to(REPO) if args.page.is_relative_to(REPO) else args.page}")
        return 0
    problems = check(args.page)
    for problem in problems:
        print(problem, file=sys.stderr)
    if not problems:
        print("current-contracts: CURRENT")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
