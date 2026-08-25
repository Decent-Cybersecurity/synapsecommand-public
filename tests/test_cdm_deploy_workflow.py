"""How the documentation site is deployed, stated twice and required to agree.

WHY THIS EXISTS, AND IT IS THE ONLY FACT HERE NOTHING COULD CHECK
-----------------------------------------------------------------
Every other multi-site fact in this repository has a collector behind it: the adapter count, the
ordinals, the pin rows, the edition lineage. The DEPLOY MECHANISM had none, and it drifted the
way an unchecked fact drifts — into a commit message, as a claim that a push to `main` deploys
the site. It does not. `wrangler pages project list` reports `Git Provider: No`: Cloudflare never
clones this repository and never runs a build, and every deployment in the project's history is a
direct upload of an already-built `docs/build`.

**The claim survived a round because it was made in the one window where nothing could falsify
it.** Five commits stood between the claim and its correction and NOT ONE of them touched a file
under `docs/` — so there was nothing a deploy would have changed, and a site that was already
correct went on being correct. A wrong belief about deployment is invisible until a rendered page
changes, which is exactly the property that makes it worth a gate rather than a habit.

WHAT THIS MODULE CAN AND CANNOT CHECK
-------------------------------------
It cannot reach Cloudflare, and it does not pretend to: there is no assertion here that the live
site is current, because that needs credentials the suite does not have and must not want. What
it checks is the half that is decidable from the tree —

* the mechanism is stated at both sites, in the same terms, naming the same output directory;
* neither site claims a push deploys;
* the closure: a file that states the mechanism and is not on the list FAILS, in both directions.

CLOSURE, BOTH DIRECTIONS — THE PIN GATE'S PROPERTY, APPLIED TO PROSE
---------------------------------------------------------------------
`SITES` is not trusted. A repo-wide sweep looks for the two strings that appear only where this
mechanism is described, and any file carrying one that `SITES` does not name is a failure. That is
what makes dropping a site from the list a build failure rather than a silent narrowing — the
mutation `tests/test_cdm_pins.py` is built around, reached here from the other side.
"""
import pathlib
import re
import tomllib

import pytest

import synapse_cdm

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
REPO = PKG.parents[2]

#: The two files that state the deploy mechanism. Both are checked, and the sweep below
#: re-derives this list rather than trusting it.
SITES = ("wrangler.toml", "docs/README.md")

#: This module quotes the mechanism in order to check it, so sweeping it would flag the checker
#: as a site. The same exclusion `tests/test_cdm_ordinals.py` makes, for the same reason.
SELF = "tests/test_cdm_deploy_workflow.py"

#: Strings that occur only where this mechanism is described. Deliberately narrow: `deploy` alone
#: appears in the changelog and in MIGRATIONS.md in the unrelated sense of a CONSUMER being
#: redeployed after a schema bump, and a marker that matched those would need an exemption list
#: longer than the thing it checks.
MARKERS = ("pages deploy", "Git Provider")

#: The directory the CLI uploads. Read from `wrangler.toml` as DATA rather than as a substring,
#: because a substring check is satisfied by the prose around the value as well as by the value.
EXPECTED_OUTPUT_DIR = "docs/build"


def _read(rel: str) -> str:
    path = REPO / rel
    assert path.exists(), f"{rel} does not exist; the site list is stale"
    return path.read_text()


def _flat(text: str) -> str:
    return " ".join(text.split())


# ------------------------------------------------------------------ the mechanism itself


def test_wrangler_toml_parses_and_declares_the_output_directory_as_data():
    """The one field this file actually governs, read as TOML rather than grepped."""
    config = tomllib.loads(_read("wrangler.toml"))
    assert config.get("pages_build_output_dir") == EXPECTED_OUTPUT_DIR, (
        f"wrangler.toml declares {config.get('pages_build_output_dir')!r} as the Pages build "
        f"output directory, expected {EXPECTED_OUTPUT_DIR!r}. This is the value a no-argument "
        "`wrangler pages deploy` uses, so it is the one thing in that file with an effect"
    )
    assert config.get("name") == "synapsecommand-docs", (
        "the Pages project name moved; every deploy command in the tree names it explicitly"
    )


def test_both_sites_state_that_the_project_has_no_git_integration():
    """The load-bearing half of the mechanism, and the half that was asserted backwards.

    Anchored to `Git Provider: No` — the exact string `wrangler pages project list` prints — so
    the sites record a MEASUREMENT rather than a belief about how Pages projects usually work.
    """
    for site in SITES:
        flat = _flat(_read(site))
        assert "Git Provider: No" in flat or "`Git Provider: No`" in flat, (
            f"{site} no longer records that the Pages project has no Git integration. That is "
            "the fact the whole workflow rests on: without it, 'a push does not deploy' reads as "
            "a preference rather than as a consequence"
        )


@pytest.mark.parametrize("site", SITES)
def test_every_site_states_the_deploy_is_an_explicit_direct_upload(site):
    """A pattern that stops matching is a FAILURE, not a pass — the standing rule."""
    flat = _flat(_read(site))
    assert re.search(r"wrangler pages deploy", flat), (
        f"{site} no longer shows the deploy command. Re-anchor it deliberately if the command "
        "changed; do not delete the row"
    )
    assert EXPECTED_OUTPUT_DIR in flat, (
        f"{site} no longer names {EXPECTED_OUTPUT_DIR!r}, so the two sites can no longer be "
        "checked against each other on the one value that has an effect"
    )
    assert "direct upload" in flat.lower(), (
        f"{site} no longer says the deployment is a direct upload. 'Deployed to Cloudflare "
        "Pages' is true of both mechanisms and distinguishes neither"
    )


def test_no_site_anywhere_claims_that_a_push_deploys():
    """THE ABSENCE, and it is the sentence that was actually wrong.

    Scoped to the CLAIM rather than to the words: 'push' and 'deploy' both occur innocently and
    often. What is banned is the pairing asserting one causes the other, and the two sites are
    permitted to state the negation — which is why the check is for an affirmative form.
    """
    banned = re.compile(
        r"(?:push(?:ing)?[^.]{0,40}(?:is|triggers?|starts?|causes?)[^.]{0,20}(?:the )?deploy)"
        r"|(?:deploys? on push)"
        r"|(?:push[- ]triggered deploy)",
        re.I)
    offenders = []
    for path in sorted(REPO.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".mdx", ".toml", ".py", ".ts"}:
            continue
        if any(part in {".git", "node_modules", ".docusaurus", "build", ".venv"}
               for part in path.parts):
            continue
        rel = str(path.relative_to(REPO))
        if rel == SELF:
            continue                      # this module quotes the retired claim, on purpose
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for match in banned.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{rel}:{line} — {_flat(match.group(0))[:80]}")
    assert not offenders, (
        "these sites claim a push deploys the documentation site:\n  " + "\n  ".join(offenders) +
        "\nIt does not. The Pages project reports `Git Provider: No`, so Cloudflare never clones "
        "this repository; the deploy is an explicit `wrangler pages deploy` of a built "
        f"{EXPECTED_OUTPUT_DIR}."
    )


def test_the_workflow_order_is_written_down_and_says_why_the_order_matters():
    """Commit first, deploy second — and the REASON, because an order with no reason decays.

    Wrangler stamps a deployment with the commit SHA it reads from git at upload time, so
    deploying before committing records a SHA that is not what was uploaded. That is a fact about
    the tool and it is the only thing making the order more than a convention.
    """
    # SCOPED to the workflow section, and the scoping is the lesson rather than a detail. The
    # first version of this test read the whole file, and a mutation that gutted the reason from
    # the workflow paragraph SURVIVED — because "commit SHA" also appears two sections up, where
    # the mechanism is described. A check on a fact stated in one paragraph must read that
    # paragraph; anything wider is a disjunction over the document.
    text = _read("docs/README.md")
    start = text.index("### The workflow, written down for the first time")
    end = text.find("\n## ", start)
    flat = _flat(text[start:end if end != -1 else len(text)])
    assert "Commit first; deploy second" in flat, (
        "docs/README.md no longer states the workflow order. It was written down for the first "
        "time in the round that found the mechanism claim was wrong — before that it existed only "
        "in commit messages, which is where the wrong version got in"
    )
    assert "commit SHA" in flat, (
        "the workflow no longer says WHY the order matters. Wrangler stamps the deployment with "
        "the SHA it reads from git, so the order is a property of the tool rather than a habit"
    )
    assert "only when a rendered page changed" in flat.lower(), (
        "the condition is gone. It is also the reason the wrong claim survived a round: a commit "
        "touching nothing under docs/ needs no deploy, and five in a row make the belief "
        "unfalsifiable"
    )


# --------------------------------------------------------------------------- the closure


def _files_stating_the_mechanism() -> list[str]:
    found = []
    for path in sorted(REPO.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".mdx", ".toml", ".py", ".ts",
                                                     ".json"}:
            continue
        if any(part in {".git", "node_modules", ".docusaurus", "build", ".venv"}
               for part in path.parts):
            continue
        rel = str(path.relative_to(REPO))
        if rel == SELF:
            continue
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if any(marker in text for marker in MARKERS):
            found.append(rel)
    return found


def test_the_site_list_is_exactly_the_files_that_state_the_mechanism():
    """CLOSURE, BOTH DIRECTIONS, and neither is redundant.

    A site on the list and not in the tree is a stale list. A file stating the mechanism and not
    on the list is a site nothing checks — which is the state the mechanism was in entirely until
    this module existed, and is the direction that catches the real mistake.
    """
    swept = set(_files_stating_the_mechanism())
    listed = set(SITES)
    assert swept == listed, (
        f"the deploy-mechanism site list and the tree disagree.\n"
        f"  only in the list: {sorted(listed - swept)}\n"
        f"  only in the tree: {sorted(swept - listed)}\n"
        "A new file describing the deploy has to join SITES and pass the checks above; a site "
        "that stops describing it has to leave deliberately."
    )
    assert len(listed) >= 2, (
        "fewer than two sites state the mechanism, so there is no disjunction left to check and "
        "the agreement assertions above are checking one file against itself"
    )


def test_the_marker_sweep_is_not_vacuous():
    """A collector that finds nothing agrees with every list, including a wrong one.

    Asserted positively against each marker, because the two are load-bearing in different ways:
    `pages deploy` is the command and `Git Provider` is the measurement, and a site could state
    one without the other.
    """
    for marker in MARKERS:
        carriers = [rel for rel in SITES if marker in _read(rel)]
        assert carriers, (
            f"no site contains the marker {marker!r}, so the closure sweep cannot see this "
            "mechanism at all and would pass against an empty site list"
        )


def test_the_built_site_is_not_committed_so_a_deploy_is_the_only_way_it_ships():
    """`docs/build` is ignored, which is what makes the deploy a separate act rather than a diff.

    Stated because the alternative design is real and was not chosen: committing the built site
    would make a push carry the rendered pages, and the mechanism above would be a different one.
    """
    import subprocess
    tracked = subprocess.run(["git", "ls-files", "docs/build"], cwd=REPO,
                             capture_output=True, text=True).stdout.strip()
    assert tracked == "", (
        f"docs/build is tracked ({len(tracked.splitlines())} files). The built site is generated "
        "and deployed, never committed — `npm run check:schemas` is what gates the SOURCE pages "
        "against drift, and a committed build would be a second copy of the rendered contract"
    )
