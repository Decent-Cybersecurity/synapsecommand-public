"""The adapter support matrix — GENERATED from the declarations, never hand-written (F05).

    python -m synapse_cdm.support_matrix --out docs/docs/cdm/support-matrix.mdx          # write
    python -m synapse_cdm.support_matrix --check --out docs/docs/cdm/support-matrix.mdx  # drift

WHY A THIRD GENERATOR BESIDE `manifests.py` AND `schemas.py`
------------------------------------------------------------
The audit (F05) found the support boundary stated in prose at several sites — README, the
coverage document, the manifests, the CLI — with nothing mechanical keeping them in step, and one
of them (STANAG 4676's XML naming) read as a wire-level claim it was not. `manifests/` already
publishes every declaration verbatim, one file per adapter; what a reader choosing an adapter
lacked was the ONE page that lays the declarations side by side: edition, wire binding, directions,
the forms the harness replays, the message families, the exclusions, and which KIND of evidence
backs each (F07's categories). This module renders that page from the same declarations the
manifests are generated from, and `--check` fails while the page and the declarations disagree —
held by `tests/test_cdm_support_matrix.py::test_the_published_page_is_current` in the suite and by
`.remediation/bin/verify.sh full`; no workflow step runs it (recorded 2026-09-20, S10). The same
arrangement `manifests.py` argues for at length.

It STATES NO COUNT. The page lists what ships and lets the reader count; a sentence with a number
in it is the stale-count class `tests/test_cdm_prose_counts.py` exists to catch, and a generated
page that spelled one would be a new site for that gate to guard.

WHAT IT DOES NOT READ. No conformance run, no evidence record, no network: the page is a function
of the adapter classes and the packaged fixture directories, so it renders identically on a clean
checkout and in CI before any evidence step. The evidence-scope columns therefore say which
categories the SUITE produces and which only an outside party can — the reading
`evidence.categories()` makes with the same constants — and never a verdict.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

from synapse_cdm import evidence, harness, manifest
from synapse_cdm.adapter import Adapter, packaged_fixtures
from synapse_cdm.adapter import shipped as _shipped
from synapse_cdm.adapters import stanag4676 as nits
from synapse_cdm.manifest import WireBinding
from synapse_cdm.normative_binding import BLOCKED_STATUS

#: Where the page lives in the documentation tree, relative to the repository root.
DEFAULT_OUT = pathlib.Path("docs/docs/cdm/support-matrix.mdx")

#: The category headings, in `EvidenceCategory`'s order — F07's five, and no sixth.
CATEGORIES = tuple(evidence.EvidenceCategory)


def shipped() -> dict[str, type[Adapter]]:
    """The adapters THIS PACKAGE ships (`adapter.shipped`), not the registry — for the reason
    `manifests.shipped` gives: a test double is not shipped."""
    return _shipped()


def replayed_forms(cls: type[Adapter]) -> list[str]:
    """The file suffixes the harness replays for this adapter, read off its packaged fixture
    directory through the harness's OWN selection (`harness.select_fixtures`, the one definition
    of "a fixture"): `.cat021` and `.parsed.json` for an ASTERIX adapter (the wire block and its
    parsed twin), `.nits.xml` and `.parsed.json` for STANAG 4676, `.json` alone for a JSON API.
    Empty when the directory is not there, which the harness reports on its own."""
    directory = packaged_fixtures(cls)
    if not directory.is_dir():
        return []
    return sorted({"".join(path.suffixes) for path in harness.select_fixtures(directory)})


def evidence_scope(cls: type[Adapter]) -> dict[str, str]:
    """What KIND of evidence each of F07's categories can be for this adapter, from the
    declaration alone. The internal two the suite produces; the external three read ABSENT with
    the basis `evidence.EXTERNAL_ABSENT_BASIS` gives until an exercise report exists — and the
    declaration says whether one could: a `normative-verified` binding or a non-null
    `external_exercise` would be the declaration claiming what only a report can show."""
    meta = cls.metadata
    exercised = set(meta.capabilities.directions_exercised)
    scope = {
        evidence.EvidenceCategory.INTERNAL_FIXTURE.value:
            "internal — the suite's checks A/B/C over the packaged synthetic fixtures",
        evidence.EvidenceCategory.SELF_ROUND_TRIP.value:
            ("internal — check E, this package encoding and decoding on both legs; not "
             "independence" if "egress" in exercised
             else "NOT_APPLICABLE — ingest only, no egress leg to round-trip"),
    }
    for category in evidence.EXTERNAL_CATEGORIES:
        scope[category.value] = "ABSENT — " + evidence.EXTERNAL_ABSENT_BASIS[category]
    if meta.binding is WireBinding.NORMATIVE_VERIFIED:
        scope[evidence.EvidenceCategory.NORMATIVE_SCHEMA.value] = (
            "declared normative-verified — held to an exercise report of this category")
    if meta.maturity.external_exercise is not None:
        scope[evidence.EvidenceCategory.INDEPENDENT_ENDPOINT.value] = (
            f"declared — exercised against {meta.maturity.external_exercise.system}")
    return scope


def rows() -> list[dict]:
    """One row per shipped adapter, in registry order, every value read off the declaration."""
    out = []
    for name, cls in shipped().items():
        meta = cls.metadata
        out.append({
            "id": name,
            "name": meta.name,
            "format": meta.format.name,
            "edition": meta.format.version or "not stated — see the limitations",
            "binding": meta.binding.value,
            "profiles": list(meta.profiles),
            "direction": meta.direction.value,
            "directions_exercised": list(meta.capabilities.directions_exercised),
            "wire": meta.capabilities.wire,
            "forms": replayed_forms(cls),
            "message_types": list(meta.capabilities.message_types),
            "limitations": [manifest.limitation_text(line) for line in meta.limitations],
            "maturity": meta.maturity.level.value,
            "external_exercise": meta.maturity.external_exercise,
            "license_class": meta.license_class.value,
            "evidence_scope": evidence_scope(cls),
        })
    return out


# ------------------------------------------------------------------------------ rendering

_CODE_SPAN = re.compile(r"(`[^`]*`)")


def mdx(text: str) -> str:
    """Text safe inside an MDX table cell or paragraph. Inside a code span nothing is touched;
    outside one, `<`, `{` and `}` — which MDX reads as JSX — become entities, and `|` is escaped
    so a limitation cannot end its own table cell."""
    parts = _CODE_SPAN.split(text)
    for index, part in enumerate(parts):
        if index % 2 == 0:
            part = (part.replace("<", "&lt;").replace(">", "&gt;")
                    .replace("{", "&#123;").replace("}", "&#125;"))
        parts[index] = part.replace("|", "\\|")
    return "".join(parts)


def _table(header: list[str], body: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return lines


def render() -> str:
    """The page, as MDX. Deterministic: registry order, declaration text, no timestamps."""
    data = rows()
    lines = [
        "---",
        "title: Adapter support matrix",
        "sidebar_label: Support matrix",
        "sidebar_position: 8",
        "description: Generated from the adapter declarations — edition, wire binding, "
        "directions, replayed forms, message families, exclusions and evidence scope for every "
        "shipped adapter, and the STANAG 4676 provisional profile beside its normative mode.",
        "---",
        "",
        "{/* GENERATED FILE — DO NOT EDIT.",
        "    Written by `python -m synapse_cdm.support_matrix --out docs/docs/cdm/support-matrix.mdx`",
        "    from the adapters' own `metadata` declarations. Edit the adapter module, regenerate,",
        "    and `--check` fails while the page and the declarations disagree (held by the suite). */}",
        "",
        "# Adapter support matrix",
        "",
        "Every row below is read off one adapter's `metadata` — the same declaration "
        "`manifests/<id>.json` publishes and `python -m synapse_cdm.harness --list-adapters` "
        "prints — so the four cannot say different things about the same adapter. The page is "
        "regenerated by the command in its header, and `tests/test_cdm_support_matrix.py` in the "
        "test suite fails while the page on disk and the declarations disagree (no CI step runs "
        "the generator's `--check`; the suite is what holds it); a sentence in it is not a claim "
        "somebody typed.",
        "",
        "**How to read the binding column.** `standard-encoding` means the bytes this adapter "
        "reads and writes are the cited document's own encoding, checked by this repository's "
        "fixtures and tests — verified by this package's own evidence, not by an independent "
        "implementation or a normative schema (those are the external evidence categories "
        "below). `provisional-internal-profile` means the element names or namespace were chosen "
        "here from the standard's data model because the normative binding resource is not held; "
        "reader and writer agreeing proves the profile is self-consistent and nothing more. "
        "`normative-verified` would mean the wire form was validated against the authorised "
        "normative schema through the adapter's local-resource hook; no shipped adapter declares "
        "it, and the manifests test holds the value to an exercise report.",
        "",
        "## The matrix",
        "",
    ]
    lines += _table(
        ["adapter", "format", "edition", "binding", "direction", "replayed forms", "maturity",
         "licence"],
        [[f"`{r['id']}`", mdx(r["format"]), mdx(r["edition"]), f"`{r['binding']}`",
          f"`{r['direction']}`" + (f" ({', '.join(r['directions_exercised'])})"
                                    if r["directions_exercised"] else ""),
          ", ".join(f"`{f}`" for f in r["forms"]) or "—",
          f"`{r['maturity']}`", f"`{r['license_class']}`"] for r in data])
    lines += [
        "",
        "`direction` is the declared value with the directions the capability block says are "
        "exercised in brackets; the model refuses a disagreement between the two. `replayed "
        "forms` are the file suffixes in the adapter's packaged fixture directory — the wire "
        "form and, for binary and XML adapters, the parsed twin beside it. `maturity` is the "
        "declared rung, which the conformance suite computes independently and the manifests "
        "test holds to the evidence.",
        "",
        "## Evidence scope",
        "",
        "The five evidence categories of `evidence.EvidenceCategory`, per adapter. The first two "
        "the conformance suite produces from this repository's own fixtures; the other three "
        "only an exercise report from outside it can make PRESENT, and until one exists each "
        "reads ABSENT with the reason. A rung's requirement is satisfied by PRESENT only.",
        "",
    ]
    lines += _table(
        ["adapter", *(f"`{c.value}`" for c in CATEGORIES)],
        [[f"`{r['id']}`", *(mdx(r["evidence_scope"][c.value]) for c in CATEGORIES)]
         for r in data])
    lines += ["", "## Per adapter: message families and exclusions", ""]
    for r in data:
        lines += [
            f"### `{r['id']}` — {mdx(r['name'])}",
            "",
            f"**Format.** {mdx(r['format'])}, {mdx(r['edition'])}. **Binding** `{r['binding']}`."
            + (f" **Profiles** {', '.join(f'`{p}`' for p in r['profiles'])}."
               if r["profiles"] else " No profile declared."),
            "",
            "**Message families implemented.**",
            "",
        ]
        lines += [f"- {mdx(m)}" for m in r["message_types"]]
        lines += ["", "**Exclusions and limitations, as declared.**", ""]
        lines += [f"- {mdx(limitation)}" for limitation in r["limitations"]]
        lines.append("")
    nits_row = next(r for r in data if r["id"] == nits.Stanag4676Adapter.name)
    lines += [
        "## STANAG 4676: the provisional profile and the normative mode",
        "",
        f"`{nits_row['id']}` declares `binding: {nits_row['binding']}`. Its XML element names "
        "are AEDP-12's UML attribute names bound through one table (`ELEMENT_NAMES`) in no "
        "namespace, because the normative XSD is distributed through NATO national "
        "representatives (Ed B §B.5) and is not held in this repository or its wheel. Every "
        "fixture, golden and evidence record for this adapter was produced under that profile, "
        "and an emitted document says so in a comment on its first line. The `· provisional` "
        "qualifier on every NITS row of `FORMAT_COVERAGE.md` is the same statement.",
        "",
        f"The verified normative binding is a separate, explicit mode: "
        f"`{nits.BINDING_ENV}={nits.BINDING_NORMATIVE}` in the environment, or "
        f"`binding=\"{nits.BINDING_NORMATIVE}\"` to the constructor. Under it every document "
        "read is validated against the authorised schema before anything interprets it, every "
        "document emitted is validated before it is handed over, and the adapter records what it "
        "validated against (`binding_report`). The mode needs the local-resource hook and FAILS "
        f"`{BLOCKED_STATUS}` without it — at construction, naming the first unmet step — and "
        "it never falls back to the profile. A document whose root is in a namespace is refused "
        "by the profile by name, and an unqualified document is refused by the normative mode by "
        "name, in both directions.",
        "",
        f"**Status (2026-09-20): `{BLOCKED_STATUS}`.** No authorised XSD is available in this "
        "environment, so the normative binding is not verified for any document, and the "
        f"`{evidence.EvidenceCategory.NORMATIVE_SCHEMA.value}` category reads ABSENT above. "
        "The acceptance procedure, in the order the resolver checks it:",
        "",
    ]
    lines += [f"{index}. **`{step}`** — {mdx(text)}"
              for index, (step, text) in enumerate(nits.NORMATIVE_PROCEDURE, 1)]
    lines += [
        "",
        f"The hook is `{nits.XSD_DIR_ENV}`; the record is `{nits.XSD_RECORD_NAME}` beside "
        + " and ".join(f"`{name}`" for name in nits.XSD_FILES)
        + f", recording `{'`, `'.join(nits.XSD_RECORD_FIELDS)}`. Both files stay outside Git "
        "and outside any published package. When the procedure has run, the F07 exercise runner "
        f"records it as a `{evidence.EvidenceCategory.NORMATIVE_SCHEMA.value}` report and only "
        f"then may the manifest say `{WireBinding.NORMATIVE_VERIFIED.value}`.",
        "",
    ]
    return "\n".join(lines)


def write(path: pathlib.Path) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(), encoding="utf-8")
    return path


def check(path: pathlib.Path) -> list[str]:
    """Problems with the page on disk; empty means it is what the declarations render now."""
    if not path.is_file():
        return [f"{path}: missing — run python -m synapse_cdm.support_matrix --out {path}"]
    if path.read_text(encoding="utf-8") != render():
        return [f"{path}: stale — a declaration or the renderer changed; re-export"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=DEFAULT_OUT, type=pathlib.Path)
    parser.add_argument("--check", action="store_true",
                        help="exit non-zero if the page on disk is missing or stale")
    args = parser.parse_args(argv)
    if args.check:
        problems = check(args.out)
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{'STALE' if problems else 'CURRENT'}: {args.out} vs the declarations of "
              f"{len(rows())} shipped adapters")
        return 1 if problems else 0
    print(f"wrote {write(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
