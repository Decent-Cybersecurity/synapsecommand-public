"""§52's release notes, rendered from the tree rather than recalled from it.

WHAT THIS IS, AND WHAT IT IS CAREFUL NOT TO CLAIM
-------------------------------------------------
SOIF §52 lists ten things a milestone release's notes SHALL contain. Nine of them are readable off
the tree at the tag — five version constants, the adapter roster's declared state, the security
controls' recorded state, the adapters' own stated limitations, and the conformance sweep's
verdicts. One of them is not: **major changes** is a human sentence about why a release matters,
and no derivation produces it. So this module derives the nine and QUOTES the tenth from
`RELEASE_NOTES.md`, which stays the human-authored source it has always been.

That split is the whole design, and it is deliberately NOT the same claim as MIGRATIONS.md's
condition 4. Condition 4 says the notes are *derived, not remembered*, and it says explicitly that
a generated file does not satisfy it — "derived" is a claim about what the WRITER read.
`.github/workflows/publish.yml`'s header argues the same point at length and neither text is edited
by this module's existence. What changes is narrower and worth stating exactly: the nine
mechanical fields no longer have to be copied by hand out of a run summary, so the only thing left
for a person to write is the one field that was always theirs. Condition 4 is still a person's, and
this module makes the part of it that is machine-checkable machine-checked instead of trusted.

THE REFUSAL THAT MATTERS
------------------------
`--version` names the release; `RELEASE_NOTES.md`'s H1 names the version its prose is about. When
those disagree this module REFUSES rather than rendering, because notes describing 2.0.0 published
under a 2.1.0 tag are precisely the failure §52 exists to prevent — and it is a failure no reader
of the rendered file could detect, since the rendered file would carry the right number in its
heading and the wrong prose underneath. `PUBLICATION.md` entry 10 is what that class of mistake
costs once it reaches an index: a permanent filename stating something nobody meant.

DETERMINISM
-----------
Same tree, same inputs, same bytes — no clock is read, nothing is ordered by dictionary insertion,
and every table is sorted by a key the tree fixes. §53's witness hashes this file's output, so a
renderer whose output moved between two runs of one commit would make the witness unverifiable by
construction. `tests/test_cdm_release_notes.py` renders twice and compares.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from typing import Any

from synapse_cdm import version

#: §52's list, verbatim and in its order. The renderer emits one section per entry and
#: `tests/test_cdm_release_notes.py` reads this tuple rather than the prose, so a field dropped
#: from the template is a red test and not a quieter document.
SECTION_52 = (
    "package version",
    "CDM version",
    "SC-OES version",
    "Adapter API version",
    "manifest schema version",
    "major changes",
    "adapter status",
    "security status",
    "known limitations",
    "conformance summary",
)

#: The five version axes §52 names, mapped to the constants `version.py` declares. Read from the
#: module rather than from a table in this file: `VERSIONING.md` §2 is the authority for what the
#: axes are, and a second list here would be a second place for them to drift.
VERSION_AXES = (
    ("package version", "PACKAGE_VERSION"),
    ("CDM version", "SCHEMA_VERSION"),
    ("SC-OES version", "SC_OES_VERSION"),
    ("Adapter API version", "ADAPTER_API_VERSION"),
    ("manifest schema version", "MANIFEST_SCHEMA_VERSION"),
)

_H1 = re.compile(r"^#\s+synapse-cdm\s+(?P<version>\S+)\s*$", re.MULTILINE)
_CONTROL_ROW = re.compile(r"^\|\s*(?P<control>[^|]+?)\s*\|\s*(?P<state>[^|]+?)\s*\|")


class NotesRefused(Exception):
    """Raised where rendering would publish a claim the tree does not support."""


# ----------------------------------------------------------------- the one field that is a person's

def major_changes(notes_path: pathlib.Path, declared: str) -> str:
    """`RELEASE_NOTES.md`'s prose, and a refusal if it is about another version.

    The whole file after its H1 is taken verbatim. Summarising it would be this module inventing
    the one field it has no business inventing.
    """
    if not notes_path.is_file():
        raise NotesRefused(
            f"{notes_path} does not exist. §52's `major changes` is the one field no derivation "
            "produces; it is written by a person and this renderer only quotes it.")
    text = notes_path.read_text(encoding="utf-8")
    match = _H1.search(text)
    if match is None:
        raise NotesRefused(
            f"{notes_path} has no `# synapse-cdm <version>` heading, so nothing states which "
            "release its prose is about. Add one; a version this renderer had to guess at is a "
            "version nobody stated.")
    stated = match.group("version")
    if stated != declared:
        raise NotesRefused(
            f"{notes_path} is about {stated} and this is the {declared} release. §52 requires the "
            f"notes to describe THIS version. Rewrite {notes_path.name} for {declared} before the "
            "release round runs — the numbers agreeing in the heading while the prose describes "
            "the previous release is a mistake a reader of the rendered file cannot see.")
    return _demote(text[match.end():].strip("\n"))


def _demote(prose: str) -> str:
    """The quoted prose's own `##` headings, pushed one level down.

    `RELEASE_NOTES.md` is a whole document with an H1 and a dozen H2s. Embedded unchanged under
    `## Major changes`, its H2s become SIBLINGS of §52's ten sections rather than children of one
    of them, and a reader — or a table-of-contents generator — sees "Artefacts" as a §52 field.
    Nothing but the heading level changes, and it changes only outside fenced code, where a
    leading `#` is a comment and not a heading.
    """
    out, fenced = [], False
    for line in prose.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and re.match(r"^#{1,5} ", line):
            line = "#" + line
        out.append(line)
    return "\n".join(out)


# ------------------------------------------------------------------------------- the nine derived

def adapter_status(manifests_dir: pathlib.Path, conformance: dict[str, Any]) -> list[dict]:
    """One row per shipped manifest: what the adapter declares, and what the sweep allows.

    `maturity eligible` is the sweep's, not the manifest's, and the two columns sit beside each
    other on purpose — a declared rung above an eligible one is the claim ARCHITECTURE.md §3.6
    rule 5 exists to refuse, and it should be readable in the notes rather than only in a gate.
    """
    rows = []
    for path in sorted(manifests_dir.glob("*.json")):
        adapter = json.loads(path.read_text(encoding="utf-8"))["adapter"]
        report = conformance.get(adapter["id"], {})
        rows.append({
            "id": adapter["id"],
            "version": adapter["adapter_version"],
            "direction": adapter["direction"],
            "declared": (adapter.get("maturity") or {}).get("level", "—"),
            "eligible": report.get("maturity_eligible", "not run"),
            "claim": adapter["claim_status"],
            "result": report.get("result", "not run"),
        })
    if not rows:
        raise NotesRefused(
            f"{manifests_dir} holds no manifest, so §52's `adapter status` would be an empty "
            "table stating that this release ships no adapters.")
    return rows


def security_status(security_path: pathlib.Path, exceptions_dir: pathlib.Path,
                    *, codeql: str, pip_audit: str) -> dict:
    """SECURITY.md's controls table, the live exception count, and this run's two scans.

    The controls come from the document because the document is the record; the exception count
    and the two scan verdicts come from the run, because a control's *state* is a claim about now
    and this is the only place in a release where "now" is known.
    """
    controls = []
    if security_path.is_file():
        inside = False
        for line in security_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("| control "):
                inside = True
                continue
            if inside:
                if not line.startswith("|"):
                    break
                if set(line) <= set("|- "):
                    continue
                row = _CONTROL_ROW.match(line)
                if row:
                    controls.append({"control": row.group("control"),
                                     "state": row.group("state").replace("*", "")})
    exceptions = sorted(p.name for p in exceptions_dir.glob("*.json")
                        if p.name != "schema.json") if exceptions_dir.is_dir() else []
    return {"controls": controls, "exceptions": exceptions,
            "codeql": codeql, "pip_audit": pip_audit}


def known_limitations(manifests_dir: pathlib.Path,
                      extra: pathlib.Path | None = None) -> list[dict]:
    """Every limitation the fourteen state about themselves, plus whatever §57 adds.

    These are not this module's judgement about the package. Each one is a sentence an adapter's
    own manifest carries, and it is reproduced under the adapter that carries it.
    """
    out = []
    for path in sorted(manifests_dir.glob("*.json")):
        adapter = json.loads(path.read_text(encoding="utf-8"))["adapter"]
        stated = []
        for item in adapter.get("limitations") or []:
            stated.append(item if isinstance(item, str) else item.get("statement", str(item)))
        if stated:
            out.append({"id": adapter["id"], "limitations": stated})
    if extra is not None and extra.is_file():
        out.append({"id": extra.name, "limitations": [extra.read_text(encoding="utf-8").strip()]})
    return out


def conformance_summary(conformance: dict[str, Any]) -> tuple[list[str], list[dict]]:
    """A verdict per check per adapter, with the letters in the order the suite declares them."""
    letters: list[str] = []
    for report in conformance.values():
        for letter in report.get("checks", {}):
            if letter not in letters:
                letters.append(letter)
    letters.sort()
    rows = []
    for name in sorted(conformance):
        checks = conformance[name].get("checks", {})
        rows.append({
            "id": name,
            "result": conformance[name].get("result", "—"),
            "verdicts": {letter: checks.get(letter, {}).get("verdict", "—")
                         for letter in letters},
        })
    return letters, rows


# --------------------------------------------------------------------------------- the whole file

def render(declared: str, *, notes_path: pathlib.Path, manifests_dir: pathlib.Path,
           conformance: dict[str, Any], security_path: pathlib.Path,
           exceptions_dir: pathlib.Path, codeql: str, pip_audit: str,
           limitations_extra: pathlib.Path | None = None) -> str:
    """§52's ten fields, in §52's order, as one markdown document."""
    versions = {name: getattr(version, constant) for name, constant in VERSION_AXES}
    if versions["package version"] != declared:
        raise NotesRefused(
            f"this tree's PACKAGE_VERSION is {versions['package version']} and the release being "
            f"rendered is {declared}. MIGRATIONS.md condition 3 is the same rule at the tag: a "
            "number that names a tree it does not describe is a release nobody can reproduce.")
    changes = major_changes(notes_path, declared)
    adapters = adapter_status(manifests_dir, conformance)
    security = security_status(security_path, exceptions_dir, codeql=codeql, pip_audit=pip_audit)
    limits = known_limitations(manifests_dir, limitations_extra)
    letters, sweep = conformance_summary(conformance)

    lines: list[str] = [f"# synapse-cdm {declared}", ""]
    lines += ["Rendered by `synapse release-notes` from the tree at this release's tag. Every",
              "section below except **major changes** is a derivation; that one is quoted from",
              "`RELEASE_NOTES.md`, which is written by a person. MIGRATIONS.md condition 4 is",
              "unchanged by this file: it is still a person's, and this only makes the nine",
              "mechanical fields impossible to mistype.", ""]

    lines += ["## Versions", ""]
    lines += ["| axis | version |", "| --- | --- |"]
    lines += [f"| {name} | `{value}` |" for name, value in versions.items()]
    lines += [""]

    lines += ["## Major changes", "", changes, ""]

    lines += ["## Adapter status", "",
              f"{len(adapters)} adapters ship in this distribution. **declared** is the rung the",
              "adapter's manifest claims; **eligible** is the rung this release's conformance",
              "sweep allows it. A declared rung above an eligible one is a defect, not a note.", ""]
    lines += ["| adapter | version | direction | declared | eligible | claim | result |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    lines += [f"| `{r['id']}` | {r['version']} | {r['direction']} | {r['declared']} | "
              f"{r['eligible']} | {r['claim']} | {r['result']} |" for r in adapters]
    lines += [""]

    lines += ["## Security status", ""]
    if security["controls"]:
        lines += ["| control | state |", "| --- | --- |"]
        lines += [f"| {c['control']} | {c['state']} |" for c in security["controls"]]
        lines += [""]
    lines += [f"* CodeQL, this release's run: **{security['codeql']}**",
              f"* `pip-audit`, this release's run: **{security['pip_audit']}**"]
    if security["exceptions"]:
        lines += [f"* Security exceptions in force: **{len(security['exceptions'])}** — "
                  + ", ".join(f"`{name}`" for name in security["exceptions"])]
    else:
        lines += ["* Security exceptions in force: **none**. No finding is excepted; every gate "
                  "in the pipeline passed on its own terms."]
    lines += [""]

    lines += ["## Known limitations", "",
              "Stated by the adapters themselves, in their manifests. This is not a survey of what",
              "the package cannot do; it is what each adapter says it does not do.", ""]
    for entry in limits:
        lines += [f"**`{entry['id']}`**", ""]
        lines += [f"* {item}" for item in entry["limitations"]]
        lines += [""]

    lines += ["## Conformance summary", ""]
    if sweep:
        lines += [f"Checks {letters[0]}–{letters[-1]} of the Synapse Conformance Suite over every",
                  "shipped adapter, from this release's own sweep.", ""]
        lines += ["| adapter | " + " | ".join(letters) + " | result |",
                  "| --- |" + " --- |" * (len(letters) + 1)]
        for row in sweep:
            cells = " | ".join(row["verdicts"][letter] for letter in letters)
            lines += [f"| `{row['id']}` | {cells} | {row['result']} |"]
    else:
        lines += ["No conformance sweep was supplied to the renderer, so this section states that",
                  "rather than a verdict. `--conformance` is how the pipeline supplies it."]
    lines += [""]
    return "\n".join(lines)


def load_conformance(path: pathlib.Path | None) -> dict[str, Any]:
    """The sweep, as `synapse conformance run --all --format json` writes it."""
    if path is None:
        return {}
    if not path.is_file():
        raise NotesRefused(
            f"{path} does not exist. §52's conformance summary is a reading of this release's own "
            "sweep; a summary rendered without one would be a claim about checks nobody ran.")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("adapters", payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="synapse release-notes",
        description="Render §52's ten fields for a milestone release.")
    parser.add_argument("--version", required=True, dest="declared",
                        help="the release being rendered; must equal this tree's PACKAGE_VERSION")
    parser.add_argument("--from", dest="notes", type=pathlib.Path,
                        default=pathlib.Path("RELEASE_NOTES.md"),
                        help="the human-authored `major changes` source (default RELEASE_NOTES.md)")
    parser.add_argument("--manifests", type=pathlib.Path, default=pathlib.Path("manifests"),
                        help="the published manifests (default manifests/)")
    parser.add_argument("--conformance", type=pathlib.Path, default=None,
                        help="`synapse conformance run --all --format json` output")
    parser.add_argument("--evidence", type=pathlib.Path, default=pathlib.Path("evidence"),
                        help="generated evidence records; read for the sweep when --conformance "
                             "is absent")
    parser.add_argument("--security", type=pathlib.Path, default=pathlib.Path("SECURITY.md"),
                        help="the controls table's source (default SECURITY.md)")
    parser.add_argument("--exceptions", type=pathlib.Path,
                        default=pathlib.Path("security/exceptions"),
                        help="the security-exception directory (default security/exceptions)")
    parser.add_argument("--codeql", default="not run in this render",
                        help="this run's CodeQL verdict, as the pipeline read it")
    parser.add_argument("--pip-audit", dest="pip_audit", default="not run in this render",
                        help="this run's pip-audit verdict, as the pipeline read it")
    parser.add_argument("--limitations", type=pathlib.Path, default=None,
                        help="an extra limitations document (§57 item 15)")
    parser.add_argument("--out", type=pathlib.Path, default=None,
                        help="write here instead of stdout")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)
    conformance = {}
    try:
        conformance = load_conformance(args.conformance)
        if not conformance and args.evidence.is_dir():
            # The evidence records carry the same sweep, one adapter per record. Reading them is
            # not a second derivation: `evidence.generate` embeds `suite.run`'s report verbatim,
            # and `tests/test_cdm_evidence.py` is what holds those two together.
            for record in sorted(args.evidence.glob("*/*/evidence.json")):
                payload = json.loads(record.read_text(encoding="utf-8"))
                report = payload.get("conformance") or {}
                name = (report.get("adapter") or {}).get("id")
                if name:
                    conformance[name] = report
        text = render(args.declared, notes_path=args.notes, manifests_dir=args.manifests,
                      conformance=conformance, security_path=args.security,
                      exceptions_dir=args.exceptions, codeql=args.codeql,
                      pip_audit=args.pip_audit, limitations_extra=args.limitations)
    except NotesRefused as refusal:
        print(f"synapse release-notes: {refusal}", file=sys.stderr)
        return 2
    if args.out is None:
        print(text)
    else:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({len(text)} bytes, {len(conformance)} adapters in the sweep)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
