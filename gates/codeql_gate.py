"""The CodeQL gate: a SARIF file read against `security/exceptions/`, identically in CI and here.

WHY THIS IS A FILE UNDER `gates/` AND NOT THREE LINES OF `jq` IN A WORKFLOW
--------------------------------------------------------------------------
SOIF Part 1 §44 says "high-confidence critical findings SHALL fail the relevant security gate",
and the obvious implementation is a `jq` expression in `codeql.yml`. Three things make that the
wrong shape here, and each of them is a failure this repository has already had somewhere else:

1. **A gate nobody can run is a gate nobody reads.** `github/codeql-action/analyze` uploads the
   SARIF to the code-scanning API and the run's alerts become a web page. A maintainer holding a
   downloaded SARIF has to reason about the threshold rather than apply it. This module IS the
   threshold, so `python gates/codeql_gate.py results.sarif` answers the same question the CI step
   answers, with the same code and the same exceptions directory.
2. **A threshold inside a workflow is a threshold with no test over it.** `gates/wheel_install.py`
   carried the roster nothing read, and it drifted (see `tests/test_cdm_gate_rosters.py`'s own
   docstring for what that cost). `tests/test_cdm_codeql_gate.py` builds synthetic SARIF — one
   result above the threshold, one below it, one excepted — and proves each branch.
3. **The allowlist must be derived from ONE place.** §45's exception directory is the source, and
   the pip-audit step reads it through `--emit-pip-audit-ignores` below rather than through a
   second list typed into `ci.yml`. Two lists diverge in the silent direction: a finding still
   suppressed by a workflow line whose exception expired months ago.

WHAT BLOCKS, AND THE RULING THAT SET IT
---------------------------------------
The round's brief pre-ruled `security-severity >= 9.0` and precision high/very-high. M amended it
on 2026-09-07T21:53:40Z, verbatim: "HIGH and CRITICAL findings block release. A numeric CVSS
threshold of 9.0 may be used for CRITICAL, but it MUST NOT mean that HIGH findings between 7.0 and
8.9 are ignored when the security source classifies them as HIGH."

So the blocking test is `security-severity >= 7.0`, which is CVSS's own HIGH floor, and the
`CRITICAL` band at 9.0 is reported as a band rather than used as the cut. **Precision is printed
for every finding and is NOT part of the blocking test**, because the amended ruling states the
rule without it and a precision-gated cut would let a `medium`-precision CVSS 9.8 result through
while claiming to block CRITICAL findings. §44's "high-confidence" is satisfied on the other side:
`security-extended` is the query suite, and a finding whose query is genuinely imprecise is a query
problem to be fixed or suppressed at the source — `security/exceptions/README.md` says so, and an
exception is deliberately not the tool for it.

WHAT DOES *NOT* BLOCK, WHICH IS THE PART A READER WILL WANT SPELLED OUT
----------------------------------------------------------------------
* A result whose rule carries a `security-severity` below 7.0. Reported under `reported`, counted,
  and P8's §57 item 9 is where the list is meant to land.
* A result whose rule carries **no** `security-severity` at all. CodeQL sets that property on
  security queries only, and `security-extended` also runs maintainability and correctness
  queries whose `problem.severity` is `error`; blocking on those would red every run and the
  predictable response is that the gate gets deleted. They are counted separately as
  `unclassified` and PRINTED, never silently dropped — an unclassifiable security result is
  exactly the hole this paragraph exists to keep visible.
* Anything a valid, unexpired `security/exceptions/<rule id>.json` names.

An EXPIRED exception does not except. It is not an error here either — the suite is what fails on
it, unconditionally, on the day it expires (`tests/test_cdm_security_exceptions.py`), so a gate run
in the window between the expiry and somebody noticing reports the finding as blocking and says the
exception expired. Both halves fire; neither depends on the other having run.

READING SARIF WITHOUT A SARIF LIBRARY
-------------------------------------
`runs[].tool.driver.rules[]` and `runs[].tool.extensions[].rules[]` are both consulted, because
CodeQL puts the query pack's rules in the extensions and only the driver's own in `driver.rules` —
a gate that read one of the two would resolve a fraction of the rule ids and report the rest as
`unclassified`, which is a green with a hole in it. A result names its rule by `ruleId`, or by
`rule.id`, or by `rule.index` into the extension that declared it; all three spellings are handled
because all three occur in the wild and the failure mode of missing one is, again, `unclassified`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from typing import Any, Iterable, NamedTuple

REPO = pathlib.Path(__file__).resolve().parents[1]
EXCEPTIONS = REPO / "security" / "exceptions"

#: CVSS v3's own band floors. `HIGH` is the cut (M's ruling above); `CRITICAL` is reported as a
#: band so that a run's output distinguishes the two without a second threshold to keep in step.
HIGH = 7.0
CRITICAL = 9.0

#: Files in `security/exceptions/` that are not exceptions. `schema.json` is the schema the
#: exceptions validate against and `README.md` is prose; a gate that treated the schema as an
#: exception would except a rule called `Security exception`.
NOT_AN_EXCEPTION = {"schema.json"}


class Failed(Exception):
    """A reading could not be taken. Distinct from a finding, which is a result, not an error."""


def _shown(path: pathlib.Path) -> str:
    """A path as a message should name it: repo-relative when it is in the repository.

    `relative_to` RAISES for a path outside `REPO`, and every refusal message below names a path
    — so the first draft of this gate turned a refusal about a malformed exception file into a
    `ValueError` about pathlib whenever the directory was not inside the tree. Found by
    `tests/test_cdm_codeql_gate.py`, which calls `load_exceptions()` on a `tmp_path`, and it is
    the same shape a maintainer hits pointing the gate at a directory outside this checkout.
    """
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


class Exemption(NamedTuple):
    identifier: str
    expiry: dt.date
    owner: str
    path: pathlib.Path

    def valid_on(self, day: dt.date) -> bool:
        """Valid up to and including `expiry`.

        Inclusive deliberately: an `expiry` of 2026-12-31 means the exception covers that day.
        The suite's own check uses the same comparison, so the day the gate stops honouring an
        exception is the day the suite starts failing on it — one boundary, not two.
        """
        return day <= self.expiry


class Finding(NamedTuple):
    rule: str
    severity: float | None
    precision: str
    message: str
    location: str
    excepted_by: Exemption | None

    @property
    def band(self) -> str:
        if self.severity is None:
            return "unclassified"
        if self.severity >= CRITICAL:
            return "critical"
        if self.severity >= HIGH:
            return "high"
        return "below"

    @property
    def blocking(self) -> bool:
        return self.band in ("critical", "high") and self.excepted_by is None


def load_exceptions(directory: pathlib.Path | None = None) -> list[Exemption]:
    """Every exception file, parsed. A missing directory is an empty list, not an error.

    An absent `security/exceptions/` is the state a fresh checkout of any commit before round P6
    is in, and refusing to run there would make this gate unusable for exactly the audit — "what
    did the gate say at that commit" — it exists to make possible.

    `None` resolves to the module-level `EXCEPTIONS` **at call time** rather than through a
    default argument, which would bind the path once at import and leave the two callers below
    reading a different directory from the one a caller had set.
    """
    directory = EXCEPTIONS if directory is None else directory
    if not directory.is_dir():
        return []
    out: list[Exemption] = []
    for path in sorted(directory.glob("*.json")):
        if path.name in NOT_AN_EXCEPTION:
            continue
        try:
            body = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise Failed(f"{_shown(path)} is not JSON: {exc}") from exc
        for field in ("identifier", "expiry", "owner"):
            if not body.get(field):
                raise Failed(f"{_shown(path)} declares no {field}; the schema requires "
                             f"it and tests/test_cdm_security_exceptions.py is what says so at "
                             f"length. This gate refuses rather than treating it as no exception, "
                             f"because a malformed exception is ambiguous between 'excepted' and "
                             f"'not excepted' and both readings are wrong")
        try:
            expiry = dt.date.fromisoformat(body["expiry"])
        except ValueError as exc:
            raise Failed(f"{_shown(path)}'s expiry {body['expiry']!r} is not an ISO "
                         f"date: {exc}") from exc
        out.append(Exemption(str(body["identifier"]), expiry, str(body["owner"]), path))
    return out


def _rules(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every rule this run declares, from the driver AND from every extension.

    Keyed by rule id, and additionally by `<extension index>/<rule index>` so that a result naming
    its rule positionally resolves too. CodeQL emits the positional form for pack rules.
    """
    tool = run.get("tool") or {}
    out: dict[str, dict[str, Any]] = {}
    for rule in (tool.get("driver") or {}).get("rules") or []:
        if rule.get("id"):
            out[str(rule["id"])] = rule
    for index, extension in enumerate(tool.get("extensions") or []):
        for position, rule in enumerate(extension.get("rules") or []):
            if rule.get("id"):
                out[str(rule["id"])] = rule
            out[f"{index}/{position}"] = rule
    return out


def _rule_of(result: dict[str, Any], rules: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    """The rule a result names, by whichever of the three spellings it used."""
    named = result.get("ruleId") or (result.get("rule") or {}).get("id")
    if named:
        return str(named), rules.get(str(named), {})
    rule_ref = result.get("rule") or {}
    if "index" in rule_ref:
        key = f"{rule_ref.get('toolComponent', {}).get('index', 0)}/{rule_ref['index']}"
        found = rules.get(key, {})
        return str(found.get("id") or key), found
    return "<unnamed>", {}


def _severity(rule: dict[str, Any]) -> float | None:
    raw = (rule.get("properties") or {}).get("security-severity")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        # A `security-severity` that is not a number is worse than an absent one: it looks
        # classified and cannot be compared. Reported as unclassified, which prints it.
        return None


def _location(result: dict[str, Any]) -> str:
    for location in result.get("locations") or []:
        physical = (location.get("physicalLocation") or {})
        uri = (physical.get("artifactLocation") or {}).get("uri")
        line = (physical.get("region") or {}).get("startLine")
        if uri:
            return f"{uri}:{line}" if line else str(uri)
    return "<no location>"


def findings(sarif: dict[str, Any], exemptions: Iterable[Exemption],
             day: dt.date) -> list[Finding]:
    """Every result in every run, classified."""
    valid = {e.identifier: e for e in exemptions if e.valid_on(day)}
    out: list[Finding] = []
    for run in sarif.get("runs") or []:
        rules = _rules(run)
        for result in run.get("results") or []:
            rule_id, rule = _rule_of(result, rules)
            out.append(Finding(
                rule=rule_id,
                severity=_severity(rule),
                precision=str((rule.get("properties") or {}).get("precision") or "unstated"),
                message=str((result.get("message") or {}).get("text") or "").strip(),
                location=_location(result),
                excepted_by=valid.get(rule_id),
            ))
    return out


def read_sarif(path: pathlib.Path) -> dict[str, Any]:
    try:
        body = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise Failed(f"{path} does not exist. A gate that treated a missing SARIF as an empty "
                     f"one would print a green for an analysis that never ran, which is the "
                     f"whole defect it is here to prevent") from exc
    except json.JSONDecodeError as exc:
        raise Failed(f"{path} is not JSON: {exc}") from exc
    if not isinstance(body, dict) or "runs" not in body:
        raise Failed(f"{path} has no `runs` key, so it is not a SARIF log. Refusing rather than "
                     f"reporting zero findings")
    return body


def _report(all_findings: list[Finding], expired: list[Exemption], day: dt.date) -> int:
    blocking = [f for f in all_findings if f.blocking]
    excepted = [f for f in all_findings if f.excepted_by is not None]
    reported = [f for f in all_findings if f.band == "below"]
    unclassified = [f for f in all_findings if f.band == "unclassified"]

    print(f"day           {day.isoformat()}")
    print(f"results       {len(all_findings)}")
    print(f"blocking      {len(blocking)}  (security-severity >= {HIGH}, not excepted)")
    print(f"excepted      {len(excepted)}")
    print(f"reported       {len(reported)}  (below {HIGH}; not blocking, and not ignored either)")
    print(f"unclassified  {len(unclassified)}  (the rule carries no security-severity)")

    for finding in unclassified:
        print(f"  unclassified  {finding.rule}  {finding.location}  precision={finding.precision}")
    for finding in reported:
        print(f"  reported      {finding.rule}  {finding.severity}  {finding.location}")
    for finding in excepted:
        assert finding.excepted_by is not None
        print(f"  excepted      {finding.rule}  {finding.severity}  {finding.location}  "
              f"by {finding.excepted_by.path.name} (owner {finding.excepted_by.owner}, "
              f"expires {finding.excepted_by.expiry.isoformat()})")
    for finding in blocking:
        print(f"  BLOCKING      {finding.rule}  {finding.severity}  {finding.band}  "
              f"precision={finding.precision}  {finding.location}")
        if finding.message:
            print(f"                {finding.message.splitlines()[0]}")

    for exemption in expired:
        print(f"  EXPIRED       {exemption.path.name} expired {exemption.expiry.isoformat()} "
              f"(owner {exemption.owner}) and no longer excepts anything")

    if blocking:
        print(f"{len(blocking)} blocking finding(s). SOIF Part 1 §44, and M's ruling of "
              f"2026-09-07: HIGH and CRITICAL findings block. Fix the finding, or write a "
              f"documented, time-bounded exception under security/exceptions/ — the schema and "
              f"the rules are in that directory's README.")
        return 1
    print(f"{len(all_findings)} result(s), 0 blocking")
    return 0


def emit_pip_audit_ignores(day: dt.date) -> int:
    """The `--ignore-vuln` flags pip-audit should run with, derived and never typed.

    Printed on ONE line, shell-word-safe: an identifier is constrained by `schema.json`'s pattern
    to `[A-Za-z0-9._/-]`, so no entry can carry a space, a quote or a shell metacharacter, and the
    `$(...)` substitution in `ci.yml` is therefore safe without quoting gymnastics. An empty
    directory prints an empty line, which is a pip-audit invocation with no ignores — the correct
    behaviour, and the reason this is not implemented as "if the file exists".
    """
    words: list[str] = []
    for exemption in load_exceptions():
        if not exemption.valid_on(day):
            print(f"# {exemption.path.name} expired {exemption.expiry.isoformat()}; not ignored",
                  file=sys.stderr)
            continue
        words += ["--ignore-vuln", exemption.identifier]
    print(" ".join(words))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sarif", nargs="*", type=pathlib.Path,
                    help="SARIF log(s) to gate; every run in every file is read")
    ap.add_argument("--emit-pip-audit-ignores", action="store_true",
                    help="print the --ignore-vuln flags derived from security/exceptions/ and "
                         "exit; the pip-audit step in ci.yml is the caller")
    ap.add_argument("--today", default=None, metavar="YYYY-MM-DD",
                    help="the day to judge expiry against (default: today, UTC)")
    args = ap.parse_args(argv)

    day = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()

    try:
        if args.emit_pip_audit_ignores:
            return emit_pip_audit_ignores(day)
        if not args.sarif:
            ap.error("no SARIF file given. Pass the log(s) to gate, or "
                     "--emit-pip-audit-ignores to derive pip-audit's allowlist")
        exemptions = load_exceptions()
        expired = [e for e in exemptions if not e.valid_on(day)]
        found: list[Finding] = []
        for path in args.sarif:
            found += findings(read_sarif(path), exemptions, day)
        return _report(found, expired, day)
    except Failed as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
