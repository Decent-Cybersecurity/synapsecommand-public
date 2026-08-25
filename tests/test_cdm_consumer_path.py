"""The consumer path — `pip install synapse-cdm`, then a harness command that runs — at every site.

WHY THIS EXISTS
---------------
For as long as `synapse-cdm` was unpublished, every document that stated an installation stated a
*local* one: a wheel filename under `packages/cdm/dist/`, or an editable install of a clone. Both
were correct then and both are the wrong first thing to tell a reader now, and they are wrong in
the way that is hardest to notice — they still work for the maintainer, who has the clone and the
`dist/` directory, and for nobody else. That is the same shape as the three defects
`gates/wheel_install.py` was built for: an instruction that "works" for the one person who never
has to follow it.

The upload closed ledger entry 5 of `PUBLICATION.md`, and closing it turned four sites stale at
once. Nothing in the suite would have noticed. `gates/wheel_install.py::check_no_repo_paths`
sweeps only files INSIDE the wheel, so `README.md`, `docs/docs/intro.mdx` and
`docs/docs/changelog.mdx` — the three documents a stranger actually reads first — were outside
every gate this repository had.

THE DISJUNCTION PROTOCOL, APPLIED TO THREE FACTS
------------------------------------------------
A fact stated at N sites can drift at N−1 of them. The answer used here, as in
`tests/test_cdm_changelog_claim.py` and `tests/test_cdm_prose_counts.py`, is to collect every
site by regex and require the sites to agree — never to check one site and trust the rest. Three
facts are collected:

1. **the installation command** — the index install is what a consumer runs, and where a document
   states both, the index install comes first;
2. **the artefact a reader is pointed at** — never a local file or a `dist/` path, which names a
   version in its own filename and goes stale on the next release;
3. **every documented harness invocation** — a registered adapter name, and no `--fixtures`.

THE TWO EXEMPTIONS TO (3), BOTH RULED RATHER THAN OVERLOOKED
-------------------------------------------------------------
**`module:ClassName` REQUIRES `--fixtures`** and is the one form where passing it is correct. The
harness refuses to guess a directory for an adapter this package does not ship — see
`harness.main`, which would otherwise either miss (naming a directory the caller never mentioned)
or HIT, judging a stranger's adapter against our payloads.

**A Phase 1 fixture directory documents an invocation that FAILS, deliberately.** `fixtures/klv`
and `fixtures/fft` hold `spec/` and nothing else, and their READMEs print the command that proves
it — an unregistered adapter name and a directory with no fixtures in it, failing twice over with
the two exit codes written out in the prose. Rewriting those to a registered name would delete the
demonstration and contradict the `not yet` status the row sets carry. So they are allowlisted BY
PATH, and the allowlist is checked in the direction that matters: each one must still name an
adapter the registry does not have. The day `stanag4609` ships, this module fails and the README
has to be rewritten deliberately — which is the point of allowlisting a site rather than a string.
"""
import pathlib
import re

import pytest

import synapse_cdm
from synapse_cdm import adapter

REPO = pathlib.Path(synapse_cdm.__file__).resolve().parents[3]

#: This module quotes every command it forbids in order to sweep for them, so a sweep that did not
#: exclude it would find the checker and call it a site. The same exclusion
#: `tests/test_cdm_prose_counts.py` and `tests/test_cdm_publication.py` both make.
SELF = "tests/test_cdm_consumer_path.py"

SKIP_PARTS = {".git", ".venv", "node_modules", ".docusaurus", "build", "__pycache__",
              "dist", ".pytest_cache", ".wrangler", "synapse_cdm.egg-info"}


def documents() -> list[pathlib.Path]:
    """Every prose or source file a reader could be following an instruction out of."""
    out = []
    for path in sorted(REPO.rglob("*")):
        if not path.is_file() or path.suffix not in {".md", ".mdx", ".py", ".toml"}:
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if str(path.relative_to(REPO)) == SELF:
            continue
        out.append(path)
    return out


def registered() -> set[str]:
    """The names `--adapter` resolves without a module path, scoped to what this package ships.

    Scoped for the reason `tests/test_cdm_prose_counts.py` gives: `REGISTRY` is a module-level
    global and any `Adapter` subclass defined anywhere lands in it once its module is imported,
    test doubles included. A document may not point a reader at a test double.
    """
    return {name for name, cls in adapter.discover().items()
            if cls.__module__.startswith("synapse_cdm.adapters.")}


# ------------------------------------------------------------------ 1. the install command

#: The index install — the command a consumer runs. Both spellings of the name are accepted here
#: on purpose: the point of this pattern is to FIND the site, and whether it spells the
#: distribution correctly is the next assertion's business, not this one's.
INDEX_INSTALL = re.compile(r"pip install\s+(?!-e\b)(?!\./)(?!\.\S)synapse[-_]cdm\b")

#: The contributor install: an editable install of the distribution root inside a clone.
CLONE_INSTALL = re.compile(r"""pip install -e ["']?packages/cdm""")

#: A local artefact: a wheel or sdist by filename, or anything under `dist/`. This is the form
#: that carried `1.0.0` in the command itself.
LOCAL_ARTEFACT = re.compile(
    r"pip install\s+\S*(?:packages/cdm/dist/|synapse_cdm-\d|\.whl\b|\.tar\.gz\b)")

#: Sites that may state the clone install without the index install, each with the ruling that
#: lets it. A dict rather than a set so no exemption can be added without writing down its ground
#: — a bare path in a set is indistinguishable from a site somebody gave up on.
CLONE_ONLY_SITES = {
    "CONTRIBUTING.md":
        "addressed to somebody who by construction has a clone. The first thing it would gain "
        "from an index install is a command its reader must not run",
    "tests/test_cdm_getting_started.py":
        "quotes the clone install as the string it validates. It is the CHECKER for that "
        "command, not a document that instructs anybody — the same standing this module's own "
        "SELF exclusion has",
}


def test_the_index_install_is_stated_before_any_clone_install():
    """Ordering, at every document that states both. The consumer path is the first one read."""
    offenders = []
    for path in documents():
        text = path.read_text()
        rel = str(path.relative_to(REPO))
        clone = CLONE_INSTALL.search(text)
        if not clone or rel in CLONE_ONLY_SITES:
            continue
        index = INDEX_INSTALL.search(text)
        if index is None:
            offenders.append(f"{rel}: states the clone install and never the index install")
        elif index.start() > clone.start():
            offenders.append(f"{rel}: clone install at char {clone.start()} precedes the index "
                             f"install at char {index.start()}")
    assert not offenders, (
        "the contributor path is stated first, or alone, at these sites:\n  "
        + "\n  ".join(offenders) +
        f"\n`pip install synapse-cdm` is the consumer path and is what a reader who is not "
        f"working on this repository needs. Exempt by ruling: {sorted(CLONE_ONLY_SITES)}; "
        "adding to that set means writing down the ground as well as the path"
    )


def test_every_clone_only_exemption_is_still_a_site_that_needs_one():
    """An exemption for a document that no longer states the command is dead weight.

    It reads as a live ruling and covers nothing, so the next site added under it inherits a
    justification that was never examined for it.
    """
    for rel, ground in sorted(CLONE_ONLY_SITES.items()):
        path = REPO / rel
        assert path.exists(), f"{rel} is exempted and does not exist; the exemption is stale"
        assert CLONE_INSTALL.search(path.read_text()), (
            f"{rel} is exempted from the ordering check on the ground that it {ground} — and it "
            "no longer states the clone install at all, so the exemption covers nothing. Drop it"
        )


def test_no_document_points_a_reader_at_a_local_artefact():
    """The pre-publication instruction, which named a version inside the command itself.

    `pip install packages/cdm/dist/synapse_cdm-1.0.0-py3-none-any.whl` was right while there was
    no index to install from. It is wrong twice now: the path exists only in a clone that has just
    run `build`, and the filename pins a version that the next release makes a lie.
    """
    offenders = [f"{path.relative_to(REPO)}: {m.group(0)}"
                 for path in documents()
                 for m in LOCAL_ARTEFACT.finditer(path.read_text())]
    assert not offenders, (
        "these sites install this package from a local file rather than from the index:\n  "
        + "\n  ".join(offenders) +
        "\nUse `pip install synapse-cdm`. Building and installing the wheel is what "
        "`gates/wheel_install.py` does, and it does it in a venv it makes itself"
    )


def test_no_document_says_the_distribution_is_unpublished():
    """The claim four sites carried, gone from all of them, and required to stay gone.

    Windowed rather than line-scoped, for the reason `tests/test_cdm_changelog_claim.py` gives:
    this prose is hard-wrapped, so a line-scoped check finds the repair and reports it as the
    offence.
    """
    offenders = []
    for path in documents():
        low = path.read_text().lower()
        for m in re.finditer(r"not on pypi|not yet on pypi|unpublished", low):
            window = low[max(0, m.start() - 200):m.end() + 200]
            if "synapse" in window or "distribution" in window or "package" in window:
                line = low.count("\n", 0, m.start()) + 1
                offenders.append(f"{path.relative_to(REPO)}:{line}: {m.group(0)!r}")
    assert not offenders, (
        f"these sites still say the distribution is unpublished: {offenders}. `synapse-cdm` "
        "1.0.0 is on PyPI — see ledger entry 5 of PUBLICATION.md, which records the upload, the "
        "hash comparison against the built artefacts and the verification from a clean venv"
    )


def test_the_install_patterns_can_see_the_commands_they_forbid():
    """Three patterns that matched nothing would report every site correct.

    Each is tested against the exact string that shipped, because that is the string the gate
    exists to refuse and a pattern that no longer recognises it is a green check on nothing.
    """
    assert LOCAL_ARTEFACT.search(
        "pip install packages/cdm/dist/synapse_cdm-1.0.0-py3-none-any.whl"), \
        "the local-artefact pattern no longer recognises the command README.md carried"
    assert LOCAL_ARTEFACT.search("pip install ./synapse_cdm-1.0.0-py3-none-any.whl"), \
        "the local-artefact pattern no longer recognises the command intro.mdx carried"
    assert not LOCAL_ARTEFACT.search("pip install synapse-cdm"), \
        "the local-artefact pattern now flags the index install, which is the correct command"
    assert INDEX_INSTALL.search("pip install synapse-cdm"), \
        "the index-install pattern no longer recognises the command every site now states"
    assert not INDEX_INSTALL.search('pip install -e "packages/cdm[test]"'), \
        "the index-install pattern matches the clone install, so the ordering check is vacuous"
    assert CLONE_INSTALL.search('pip install -e "packages/cdm[test]"'), \
        "the clone-install pattern no longer recognises the contributor command"


def test_the_index_install_is_actually_stated_somewhere():
    """The whole gate is about a command; if no document states it, everything above is vacuous."""
    sites = sorted(str(p.relative_to(REPO)) for p in documents()
                   if INDEX_INSTALL.search(p.read_text()))
    assert len(sites) >= 3, (
        f"only {len(sites)} site(s) state `pip install synapse-cdm`: {sites}. The consumer path "
        "is supposed to be stated wherever installation is stated"
    )


# --------------------------------------------------------------- 2. the harness invocations

#: One documented command line. Anchored on the module form because that is how every document
#: spells it; the console script is named in prose but never invoked with arguments.
INVOCATION = re.compile(r"python -m synapse_cdm\.harness[^\n`]*")

#: The value of `--adapter` in one of those.
ADAPTER_ARG = re.compile(r"--adapter\s+(\S+)")

#: Fixture directories at Phase 1, whose READMEs document a command that FAILS on purpose — an
#: unregistered adapter name against a directory holding only `spec/`. See this module's header.
DELIBERATE_FAILURE_SITES = {
    "packages/cdm/synapse_cdm/fixtures/klv/README.md",
    "packages/cdm/synapse_cdm/fixtures/fft/README.md",
    "packages/cdm/synapse_cdm/FORMAT_COVERAGE.md",
}


def invocations() -> list[tuple[str, int, str]]:
    """Every documented `python -m synapse_cdm.harness …` line, as (path, line number, command)."""
    out = []
    for path in documents():
        rel = str(path.relative_to(REPO))
        for number, line in enumerate(path.read_text().splitlines(), 1):
            for m in INVOCATION.finditer(line):
                # The trailing comment is stripped before the command is judged. Half of these
                # lines end in `# no --fixtures: they came with the package`, and a check that
                # read the comment as an argument would report the sentence explaining the rule
                # as a violation of it.
                out.append((rel, number, m.group(0).split("#")[0].strip()))
    return out


def test_the_invocation_sweep_finds_the_commands_it_is_meant_to_judge():
    """A sweep that matched nothing would pass every check below."""
    found = invocations()
    assert len(found) >= 12, (
        f"the harness-invocation sweep matched {len(found)} command(s), which is fewer than the "
        "documents that certainly state one. Re-anchor the pattern deliberately"
    )
    paths = {rel for rel, _, _ in found}
    for required in ("README.md", "docs/docs/intro.mdx",
                     "packages/cdm/synapse_cdm/README.md"):
        assert required in paths, (
            f"{required} states a harness invocation and the sweep did not find it"
        )


@pytest.mark.parametrize("site", sorted(DELIBERATE_FAILURE_SITES))
def test_each_deliberate_failure_site_still_names_an_unregistered_adapter(site):
    """The allowlist, checked in the direction that makes it expire.

    These sites are exempt because the command they print is a demonstration of a failure. That
    justification holds only while the name really does not resolve. When the adapter ships, this
    fails and somebody has to rewrite the prose around it rather than inheriting an exemption that
    has quietly become a wrong command.
    """
    path = REPO / site
    assert path.exists(), f"{site} does not exist; the allowlist is stale"
    names = {ADAPTER_ARG.search(cmd).group(1)
             for rel, _, cmd in invocations() if rel == site and ADAPTER_ARG.search(cmd)}
    assert names, f"{site} is allowlisted as a deliberate-failure site and states no invocation"
    live = names & registered()
    assert not live, (
        f"{site} is allowlisted because the command it prints cannot run, and {sorted(live)} "
        "now resolves. The demonstration has become a wrong instruction: rewrite that section "
        "for a shipped adapter and take the site off the allowlist"
    )


def test_every_documented_invocation_names_an_adapter_the_registry_has():
    """A command a reader can run. Placeholders and the module form are the two other legal cases."""
    known = registered()
    offenders = []
    for rel, number, cmd in invocations():
        if rel in DELIBERATE_FAILURE_SITES:
            continue
        match = ADAPTER_ARG.search(cmd)
        if match is None:
            continue                      # prose naming the command without invoking it
        name = match.group(1)
        if name.startswith("<") or ":" in name:
            continue                      # a placeholder, or the module:ClassName form
        if name not in known:
            offenders.append(f"{rel}:{number}: --adapter {name} — registered: {sorted(known)}")
    assert not offenders, (
        "these documented commands name an adapter the registry does not have, so they exit 1 "
        "with `LookupError` for anybody who runs them:\n  " + "\n  ".join(offenders)
    )


def test_no_documented_invocation_passes_fixtures_for_a_shipped_adapter():
    """`--fixtures` is what made the harness unrunnable for anyone who had installed the package.

    Every document used to fill it in with a path inside a clone. The flag is still correct — and
    still required — for `module:ClassName`, which is why this is scoped to the shipped case
    rather than banning the flag.
    """
    known = registered()
    offenders = []
    for rel, number, cmd in invocations():
        if rel in DELIBERATE_FAILURE_SITES or "--fixtures" not in cmd:
            continue
        match = ADAPTER_ARG.search(cmd)
        if match is None:
            continue
        name = match.group(1)
        if ":" in name:
            continue                      # the module form, where the flag is mandatory
        if name in known or name.startswith("<"):
            offenders.append(f"{rel}:{number}: {cmd}")
    assert not offenders, (
        "these documented commands pass `--fixtures` for an adapter the package ships:\n  "
        + "\n  ".join(offenders) +
        "\nOmit it. The adapter declares its own directory (`Adapter.fixture_dir`) and the "
        "harness resolves it through `importlib.resources`, so the command is identical from a "
        "clone and from a `pip install` — which is the property that made the harness runnable "
        "by the people it gates"
    )


def test_the_module_form_still_requires_fixtures_wherever_it_is_documented():
    """The other direction, so the check above cannot be satisfied by deleting the flag entirely.

    A document that showed `--adapter my_package:MyAdapter` with no `--fixtures` would be printing
    a command that exits `2`, and the reader's diagnosis would be about their adapter rather than
    about the flag they were never told to pass.
    """
    seen, offenders = 0, []
    for rel, number, cmd in invocations():
        match = ADAPTER_ARG.search(cmd)
        if match is None or ":" not in match.group(1):
            continue
        seen += 1
        if "--fixtures" not in cmd:
            offenders.append(f"{rel}:{number}: {cmd}")
    assert seen >= 2, (
        f"only {seen} documented command(s) use the `module:ClassName` form. That form is how an "
        "outside adapter is validated at all, and a check that sees none of it proves nothing"
    )
    assert not offenders, (
        "these documented commands use `module:ClassName` and omit `--fixtures`, which the "
        f"harness refuses with exit code {2}:\n  " + "\n  ".join(offenders)
    )
