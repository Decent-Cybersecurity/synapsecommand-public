"""The deployment record, reconciled against Cloudflare's own list — every id, and the alias.

WHY THIS EXISTS, AND IT IS AN INCIDENT RATHER THAN A PRINCIPLE
--------------------------------------------------------------
On 2026-08-27 the deployment-record round measured the project's list for the first time and found
**sixteen deployments of which the tree recorded two**, both in passing. Fourteen had happened and
left no trace outside Cloudflare. One consequence had already landed: `PUBLICATION.md` asserted, in
the PRESENT TENSE, that the live site was byte-identical to deployment `e08d2ea7`, and two
deployments had superseded it — so the sentence had been false for two days and nothing in the
repository could have said so.

That round wrote the record. It did not mechanize the reconciliation, and said so in as many words:
a deploy "gets a row … in the commit that follows it", which is a habit and not a check. The very
next sweep found the habit had already failed in its own file — the round that recorded
`5ed34cd8` left the paragraph above the table naming `57ac1878` as what "the site has served
since", falsified by that round's own upload four hours earlier. **A protocol act nobody can fail
is a protocol act that decays at the speed of somebody's attention.**

WHAT THIS GATE CHECKS, AND THE SECOND HALF IS THE ONE THE INCIDENT ARGUES FOR
-----------------------------------------------------------------------------
1. **Every deployment id is accounted for in the record.** Either it has its own row in ledger
   entry 8's table, or it is named in that entry's explicitly pinned coverage set. Both directions
   fail: a deployment the record cannot name, and an id in the record that Cloudflare does not
   list. The second matters because the first is satisfiable by inventing rows.

2. **The record names the deployment the custom domain actually serves.** This is the fact that
   went false, so it is the fact that gets pinned.

**The alias holder is witnessed by BYTES and not read off the API, deliberately.** Cloudflare
reports an `aliases` array on the deployment record, and that is a settings read — it says which
deployment is *configured* to hold the domain. What the record claims is stronger and is what a
stranger experiences: that fetching `docs.synapsecommand.com` returns what that deployment holds.
So the gate fetches the live pages and the candidate deployment's own `<id>.pages.dev` pages and
compares them byte for byte, newest deployment first, stopping at the first that matches on every
page. That is `PUBLICATION.md`'s own discipline — "a settings page shows what someone intended; a
refusal shows what is enforced" — applied to a deploy.

It also carries the half that makes it a measurement rather than a tautology, which the record's
own flip probe had and a naive check would lose: the winner must be byte-identical on every page
AND the deployment before it must differ on at least one. Identical to the current deployment and
different from the previous one is the only pair that distinguishes "serving what was deployed"
from "serving something".

WHY IT IS A GATE AND NOT A SUITE MEMBER
---------------------------------------
It needs a network and Cloudflare credentials, so it is a protocol act rather than a test, on
`gates/wheel_install.py`'s reasoning: a test that needs a token is a test that fails for every
outsider and turns green only for whoever holds it. `PUBLICATION.md` says the suite "cannot reach
Cloudflare and must not want to", and that stays true — what changes is that the reconciliation is
now a command with a verdict instead of a habit.

**The list comes from `npx wrangler`, not from the REST API with a token this file finds.** The
first draft read wrangler's OAuth token out of its config file and called the API directly; the
token had expired four hours earlier and the API answered `9109 Invalid access token` while
`wrangler` itself worked fine, because wrangler refreshes on use. Shelling out to wrangler means
the gate authenticates the same way the deploy does, which is also the only way it can be wrong
about the same things.

USAGE

    python gates/deploy_record.py                    # reconcile; exit 0 clean, 1 on any finding
    python gates/deploy_record.py --json             # the measurement, for a round to quote
    python gates/deploy_record.py --mutation-check   # prove the gate can fail, both directions

`--mutation-check` is not optional courtesy. It fabricates an unrecorded deployment and requires
this gate to refuse it, then re-runs the real list and requires a pass — a gate nobody has seen
fail is a gate nobody has seen.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.request

REPO = pathlib.Path(__file__).resolve().parents[1]
RECORD = REPO / "PUBLICATION.md"
WRANGLER_TOML = REPO / "wrangler.toml"

#: The ledger entry that holds the deployment table. Anchored to the heading rather than to a line
#: number: the entry moves down the file every time a round adds prose above it.
ENTRY_HEADING = "### 8. The deployment record, reconciled"

#: The paragraph that pins the deployments covered retrospectively rather than row by row. It is a
#: SET of ids and not a date range, and that is the whole point of the marker existing — the first
#: version of this table carried a row reading "eleven earlier | 2026-08-22 → 2026-08-25 | all
#: resolve", which accounts for a deployment by the accident of when it happened. A date heuristic
#: cannot be wrong about an id it never names, so it cannot be checked.
COVERAGE_MARKER = "**The eleven earlier deployments, named rather than dated.**"

#: The sentence that names which deployment the custom domain serves.
ALIAS_MARKER = "**The alias, and which deployment serves it.**"

#: The pages compared byte for byte. Five, as every deploy measurement in the record has used —
#: enough that an asset-hash change shows up somewhere, few enough to be one round of fetches.
#: `/changelog/` and `/cdm/entity/` are here because they are the pages a release actually moves.
PROBE_PAGES = ("/", "/cdm/", "/changelog/", "/writing-an-adapter/", "/cdm/entity/")

#: How many deployments back the alias probe is willing to look before giving up. The answer is
#: expected to be the newest; a deeper match means a deploy did not take the alias, which is a
#: finding and not a reason to keep searching the whole history.
ALIAS_SEARCH_DEPTH = 4


class Finding(Exception):
    """A reconciliation failure. Every one of these is a sentence somebody has to act on."""


@dataclasses.dataclass(frozen=True)
class Deployment:
    """One row of Cloudflare's list, as wrangler reports it."""

    id: str
    source: str
    status: str

    @property
    def short(self) -> str:
        return self.id[:8]

    @property
    def preview(self) -> str:
        return f"https://{self.short}.{project_name()}.pages.dev"


def project_name() -> str:
    """The Pages project, READ from `wrangler.toml` rather than typed into this file.

    The same discipline `tests/test_cdm_publication.py` applies to the repository owner: the value
    is read from the one place that declares it, so a rename re-points the gate instead of leaving
    a constant somebody has to remember. `wrangler.toml`'s `name` is what the deploy command uses.
    """
    text = WRANGLER_TOML.read_text()
    found = re.search(r'^name\s*=\s*"([^"]+)"', text, re.M)
    if not found:
        raise Finding(
            f"{WRANGLER_TOML.relative_to(REPO)} declares no `name`, so this gate cannot tell which "
            "Pages project to reconcile. That value is also what the deploy command uses; "
            "restore it rather than typing the project name into this gate"
        )
    return found.group(1)


def custom_domain() -> str:
    """The hostname the record claims is served, read out of the record's own alias sentence.

    Not a constant here for the same reason the project name is not: the gate must not be able to
    check a domain the record has stopped talking about.
    """
    section = entry_section()
    start = section.index(ALIAS_MARKER) if ALIAS_MARKER in section else None
    if start is None:
        raise Finding(
            f"{RECORD.name} ledger entry 8 carries no {ALIAS_MARKER!r} paragraph, so there is "
            "nothing stating which deployment serves the custom domain. That is the fact this "
            "gate exists to pin — it went false inside the round that wrote the table"
        )
    paragraph = section[start:].split("\n\n", 1)[0]
    hosts = re.findall(r"`([a-z0-9.-]+\.[a-z]{2,})`", paragraph)
    hosts = [h for h in hosts if not h.endswith(".pages.dev")]
    if not hosts:
        raise Finding(
            f"the {ALIAS_MARKER!r} paragraph names no custom hostname in backticks. It has to say "
            "which domain is being claimed; a paragraph about 'the alias' with no alias in it is "
            "a sentence this gate would check against nothing"
        )
    return hosts[0]


# --------------------------------------------------------------------- what Cloudflare says


def wrangler_deployments() -> list[Deployment]:
    """Cloudflare's list, via `npx wrangler`, newest first.

    Through wrangler and not through the REST API with a token this file goes looking for. See the
    module docstring: the token in wrangler's own config expires, wrangler refreshes it on use, and
    a gate that reads the file directly reports an authentication error as a deployment finding.
    """
    proc = subprocess.run(
        ["npx", "wrangler", "pages", "deployment", "list",
         "--project-name", project_name(), "--json"],
        cwd=REPO, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise Finding(
            "`wrangler pages deployment list` failed, so nothing was reconciled. This is NOT a "
            "clean run and must not be reported as one.\n"
            f"  exit {proc.returncode}\n  {proc.stderr.strip()[:400]}\n"
            "  If it is an authentication error, run `npx wrangler whoami` — the OAuth token "
            "refreshes on use and this gate deliberately does not manage credentials."
        )
    # wrangler prints a banner before the JSON on some versions; take from the first bracket.
    out = proc.stdout
    if "[" not in out:
        raise Finding(f"wrangler printed no JSON array:\n{out[:400]}")
    rows = json.loads(out[out.index("["):])
    deployments = [Deployment(id=r["Id"], source=r.get("Source", ""), status=r.get("Status", ""))
                   for r in rows]
    if not deployments:
        raise Finding(
            f"the {project_name()} project lists no deployments at all. The record describes a "
            "served site, so an empty list is a finding about this gate's target and not a clean "
            "reconciliation"
        )
    shorts = [d.short for d in deployments]
    if len(set(shorts)) != len(shorts):
        clash = sorted({s for s in shorts if shorts.count(s) > 1})
        raise Finding(
            f"two deployments share an 8-character prefix: {clash}. The record names deployments by "
            "that prefix, so the abbreviation has stopped being an identifier. Widen the record's "
            "ids and this gate's pattern together"
        )
    return deployments


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "synapsecommand-deploy-record"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        raise Finding(f"GET {url} returned HTTP {error.code}") from error
    except OSError as error:
        raise Finding(f"GET {url} failed: {error}") from error


def page_digests(base: str) -> dict[str, str]:
    return {page: hashlib.sha256(fetch(base.rstrip("/") + page)).hexdigest()
            for page in PROBE_PAGES}


def serving_deployment(deployments: list[Deployment]) -> tuple[Deployment, dict]:
    """Which deployment the custom domain actually serves, witnessed by bytes.

    Newest first, stopping at the first deployment byte-identical to the live site on every probe
    page. The one after it must DIFFER on at least one page, which is the half that makes this a
    measurement: a check that only asserted "the live site matches deployment X" would also pass if
    every deployment served identical bytes, and then it would be pinning nothing.
    """
    host = custom_domain()
    live = page_digests(f"https://{host}")
    for index, candidate in enumerate(deployments[:ALIAS_SEARCH_DEPTH]):
        if page_digests(candidate.preview) != live:
            continue
        previous = deployments[index + 1] if index + 1 < len(deployments) else None
        if previous is None:
            raise Finding(
                f"{host} matches {candidate.short}, which is the only deployment in the list, so "
                "there is nothing to differ from and the match proves only that a server answered"
            )
        prior = page_digests(previous.preview)
        differing = [page for page in PROBE_PAGES if prior[page] != live[page]]
        if not differing:
            raise Finding(
                f"{host} is byte-identical to BOTH {candidate.short} and the deployment before it, "
                f"{previous.short}, on all {len(PROBE_PAGES)} probe pages. The comparison cannot "
                "distinguish which one is being served, so it establishes nothing about the alias. "
                "Widen PROBE_PAGES to a page the two deployments differ on"
            )
        return candidate, {
            "host": host,
            "serving": candidate.short,
            "previous": previous.short,
            "pages": len(PROBE_PAGES),
            "identical_to_serving": len(PROBE_PAGES),
            "differing_from_previous": len(differing),
        }
    searched = [d.short for d in deployments[:ALIAS_SEARCH_DEPTH]]
    raise Finding(
        f"{host} is not byte-identical to any of the {len(searched)} newest deployments "
        f"{searched} on all {len(PROBE_PAGES)} probe pages. Either the domain is served by "
        "something older — which means a deploy did not take the alias and is a finding — or it is "
        "not served by this project at all"
    )


# ------------------------------------------------------------------------ what the record says


def entry_section() -> str:
    """Ledger entry 8, by its heading. A missing heading is a re-anchoring job, not a pass."""
    text = RECORD.read_text()
    if ENTRY_HEADING not in text:
        raise Finding(
            f"{RECORD.name} no longer contains a heading starting {ENTRY_HEADING!r}. The "
            "deployment record is what this gate reconciles against; find where the entry went and "
            "update this constant deliberately rather than letting the gate pass over nothing"
        )
    start = text.index(ENTRY_HEADING)
    rest = text[start + len(ENTRY_HEADING):]
    nxt = re.search(r"\n#{2,3} ", rest)
    return rest[:nxt.start()] if nxt else rest


def recorded_rows() -> set[str]:
    """Ids with a row of their own: the first backticked 8-hex cell of a table line."""
    return set(re.findall(r"^\|\s*`([0-9a-f]{8})`\s*\|", entry_section(), re.M))


def recorded_coverage() -> set[str]:
    """Ids named by the retrospective coverage paragraph — an explicit set, never a date range."""
    section = entry_section()
    if COVERAGE_MARKER not in section:
        raise Finding(
            f"{RECORD.name} ledger entry 8 carries no {COVERAGE_MARKER!r} paragraph. The "
            "deployments not given a row of their own have to be NAMED: the table's first version "
            "covered them with a row reading 'eleven earlier | 2026-08-22 → 2026-08-25', and a "
            "date range cannot be wrong about an id it never mentions"
        )
    start = section.index(COVERAGE_MARKER)
    paragraph = section[start:].split("\n\n", 1)[0]
    return set(re.findall(r"`([0-9a-f]{8})`", paragraph))


def recorded_alias_holder() -> str:
    """The deployment the record says serves the custom domain."""
    section = entry_section()
    if ALIAS_MARKER not in section:
        raise Finding(
            f"{RECORD.name} ledger entry 8 carries no {ALIAS_MARKER!r} paragraph, so nothing in "
            "the record states which deployment serves the domain"
        )
    start = section.index(ALIAS_MARKER)
    paragraph = section[start:].split("\n\n", 1)[0]
    found = re.findall(r"`([0-9a-f]{8})`", paragraph)
    if not found:
        raise Finding(
            f"the {ALIAS_MARKER!r} paragraph names no deployment id. It has to say WHICH "
            "deployment, in backticks: this is the claim that was false for four hours inside the "
            "round that wrote the table, and a paragraph about the alias that names no deployment "
            "is the shape that let it happen"
        )
    return found[0]


# ------------------------------------------------------------------------------ the verdicts


def reconcile(deployments: list[Deployment]) -> dict:
    """The id reconciliation, both directions. Returns the measurement; raises on any finding."""
    listed = {d.short: d for d in deployments}
    rows, coverage = recorded_rows(), recorded_coverage()
    overlap = rows & coverage
    if overlap:
        raise Finding(
            f"{sorted(overlap)} appear BOTH as a row and in the retrospective coverage set. Each "
            "deployment is accounted for once, by one mechanism; two accounts of one deployment is "
            "two places to keep in agreement and the reason entry 8 exists is that nobody kept one"
        )
    accounted = rows | coverage
    unrecorded = sorted(set(listed) - accounted)
    if unrecorded:
        lines = [f"    {listed[s].short}  {listed[s].status:<16} source {listed[s].source}"
                 for s in unrecorded]
        raise Finding(
            f"{len(unrecorded)} deployment(s) that {RECORD.name} cannot name:\n"
            + "\n".join(lines) + "\n"
            f"  Give each one a row in ledger entry 8's table, or add it to the "
            f"{COVERAGE_MARKER!r} set if it is being covered retrospectively.\n"
            "  This is the class the entry was written for: sixteen deployments of which the tree "
            "recorded two, and a present-tense claim about the live site that outlived the state it "
            "described by two days."
        )
    invented = sorted(accounted - set(listed))
    if invented:
        raise Finding(
            f"{RECORD.name} names {len(invented)} deployment(s) Cloudflare does not list: "
            f"{invented}.\n"
            "  This direction is checked because the other one is satisfiable by writing rows. An "
            "id in the record that the project has never held is either a typo — which makes the "
            "row account for nothing — or a deployment that was deleted, which is a fact the entry "
            "should state rather than leave as a row that no longer resolves."
        )
    return {"listed": len(listed), "rows": len(rows), "coverage": len(coverage)}


def check_alias(deployments: list[Deployment]) -> dict:
    """The record's alias claim against the bytes the domain actually serves."""
    serving, measurement = serving_deployment(deployments)
    claimed = recorded_alias_holder()
    if claimed != serving.short:
        raise Finding(
            f"{RECORD.name} says `{claimed}` serves {measurement['host']}; the bytes say "
            f"`{serving.short}`.\n"
            f"  {measurement['identical_to_serving']}/{measurement['pages']} probe pages are "
            f"byte-identical to {serving.short} and "
            f"{measurement['differing_from_previous']}/{measurement['pages']} differ from "
            f"{measurement['previous']}, so the measurement is not a tautology.\n"
            "  THIS IS THE EXACT DEFECT THIS GATE WAS WRITTEN FOR. The round that recorded "
            "`5ed34cd8` left the paragraph above its own table naming `57ac1878` as what the site "
            "'has served since' — falsified four hours earlier by that round's own upload."
        )
    return measurement


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the measurement as JSON")
    parser.add_argument("--mutation-check", action="store_true",
                        help="prove the gate refuses a fabricated deployment, then that it passes")
    args = parser.parse_args(argv)

    try:
        deployments = wrangler_deployments()
        ids = reconcile(deployments)
        alias = measurement = check_alias(deployments)
    except Finding as finding:
        print(f"FAIL  {finding}", file=sys.stderr)
        return 1

    if args.mutation_check:
        fake = Deployment(id="deadbeef" + "0" * 28, source="cafef00d", status="fabricated")
        try:
            reconcile([fake, *deployments])
        except Finding:
            print("mutation  a fabricated unrecorded deployment is REFUSED  ok")
        else:
            print("FAIL  the gate accepted a fabricated deployment the record cannot name; the "
                  "reconciliation above proves nothing", file=sys.stderr)
            return 1
        try:
            reconcile(deployments)
        except Finding as finding:
            print(f"FAIL  the real list stopped passing: {finding}", file=sys.stderr)
            return 1
        print("mutation  the real list PASSES                             ok")

    if args.json:
        print(json.dumps({"ids": ids, "alias": alias}, indent=2))
        return 0

    print(f"deployments   {ids['listed']} listed; {ids['rows']} with a row, "
          f"{ids['coverage']} covered retrospectively; 0 unaccounted for")
    print(f"alias         {measurement['host']} is served by `{measurement['serving']}` — "
          f"{measurement['identical_to_serving']}/{measurement['pages']} pages identical to it, "
          f"{measurement['differing_from_previous']}/{measurement['pages']} differing from "
          f"`{measurement['previous']}`")
    print("2 checks, 0 failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
