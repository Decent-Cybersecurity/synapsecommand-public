"""`gates/deploy_record.py`, held to its contract without reaching Cloudflare.

WHY THIS MODULE EXISTS
----------------------
The gate is a protocol act: it shells out to `wrangler` and fetches pages over HTTPS, so it cannot
be a suite member for the reason `PUBLICATION.md` gives — the suite cannot reach Cloudflare and
must not want to. `tests/test_cdm_gate_rosters.py` was written because that arrangement had already
cost this repository once: `gates/wheel_install.py` held three rosters, nothing in the suite read
them, they drifted, and the gate went red on `main` and stayed red because the thing that noticed
was the thing nobody runs.

So the same treatment applies here, and it is the whole of this module's job: **check the part of
the gate that can be wrong while sitting still.** That is more than it sounds, because everything
the gate knows about this repository is parsed out of `PUBLICATION.md` and `wrangler.toml` — the
project name, the custom domain, the recorded deployment ids, the coverage set, the alias holder.
Every one of those is a pattern over prose, and a pattern over prose that stops matching turns a
gate into a green run over nothing.

WHAT IS CHECKED HERE AND WHAT IS NOT
------------------------------------
Checked: that the gate imports without acting; that each of its five parsers finds something in the
record as the record is written today; that the coverage set and the row set are disjoint and
together account for a plausible list; that `reconcile()` refuses both failure directions on
synthetic input; and that the record does not fall back into the shape the gate was written against
— a date range standing in for a set of ids.

Not checked: anything that needs the network. `reconcile()` is exercised against hand-built
`Deployment` values, which is the point — the reconciliation logic is pure, and the only reason it
lived behind a network call was that nobody had separated the two.

The gate is loaded with `exec(compile(...))` and NOT with `spec.loader.exec_module`, for the reason
`tests/test_cdm_gate_rosters.py` records at length: `exec_module` consults and writes
`__pycache__`, a `.pyc` is revalidated on the source's mtime in whole SECONDS plus its size, and
the way you check the assertions below is by mutating this very gate and reverting — which is
exactly the edit pattern a stale `.pyc` defeats.
"""
import pathlib
import sys
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
GATE_PATH = REPO / "gates" / "deploy_record.py"
RECORD = REPO / "PUBLICATION.md"


#: The name the gate module is registered under while it is loaded. It has to be registered, and
#: the reason is worth a comment because the failure is obscure and the fix looks like a hack.
#: The gate declares `from __future__ import annotations`, so every annotation is a STRING at class
#: creation time, and `@dataclasses.dataclass` resolves each one to decide whether it is a
#: `ClassVar` or an `InitVar` — through `sys.modules.get(cls.__module__).__dict__`. A module built
#: with `types.ModuleType` and never registered is not in `sys.modules`, so that lookup returns
#: `None` and the decorator raises `AttributeError: 'NoneType' object has no attribute '__dict__'`
#: from inside the standard library, naming nothing about this repository. Registering it is simply
#: what a real `import` would have done; the gate is importable by name, and this module loads it
#: by path only to keep `__pycache__` out of it.
GATE_MODULE_NAME = "_deploy_record_gate"


@pytest.fixture(scope="module")
def gate():
    """The gate module, from its SOURCE — never from bytecode. See this module's docstring."""
    assert GATE_PATH.exists(), (
        "gates/deploy_record.py is gone. It is the only thing that reconciles this repository's "
        "deployment record against Cloudflare's list; a deleted gate is a silent return to the "
        "habit that let fourteen deployments go unrecorded"
    )
    module = types.ModuleType(GATE_MODULE_NAME)
    module.__file__ = str(GATE_PATH)
    sys.modules[GATE_MODULE_NAME] = module
    try:
        exec(compile(GATE_PATH.read_text(), str(GATE_PATH), "exec"), module.__dict__)
        yield module
    finally:
        sys.modules.pop(GATE_MODULE_NAME, None)


def _deployment(gate, short: str, source: str = "abc12345"):
    """A `Deployment` with a chosen 8-character prefix and a full-length id."""
    return gate.Deployment(id=short + "0" * (36 - len(short)), source=source, status="test")


# ------------------------------------------------------------------------- it does not act


def test_the_gate_imports_with_no_side_effects(gate):
    """Importing it must not run wrangler, fetch a page or write anything — only define.

    `main()` is the only thing that acts. The cost of getting this wrong is specific rather than
    theoretical: a contributor who opens the file with a tool that imports it would spend a
    `npx wrangler` invocation and five HTTPS fetches, and a test collection would do it once per
    worker.
    """
    for name in ("main", "reconcile", "check_alias", "wrangler_deployments", "serving_deployment"):
        assert callable(getattr(gate, name)), f"{name} is not callable on the gate module"


# -------------------------------------------------------- the parsers, against today's record


def test_the_gate_reads_the_project_name_from_wrangler_toml(gate):
    """Derived, not typed. A project rename must re-point the gate rather than break it silently."""
    name = gate.project_name()
    assert name and " " not in name, f"project_name() returned {name!r}"
    assert f'name = "{name}"' in (REPO / "wrangler.toml").read_text(), (
        "project_name() did not come from wrangler.toml's `name`, so the gate and the deploy "
        "command could be pointed at different projects"
    )


def test_the_gate_finds_the_ledger_entry_it_reconciles_against(gate):
    """The section anchor, which is the one thing that makes every other parser non-vacuous."""
    section = gate.entry_section()
    assert len(section) > 500, (
        f"ledger entry 8 parsed to {len(section)} characters. The heading matched but the section "
        "is empty or nearly so, which would make every check below pass over nothing"
    )
    assert "| Deployment |" in section, (
        "the deployment table is no longer inside the section the gate anchors on. Either the table "
        "moved out of entry 8 or the next-heading regex is cutting the section short"
    )


def test_the_record_names_every_deployment_individually_or_in_the_pinned_set(gate):
    """Rows and coverage set: both non-empty, disjoint, and together a plausible list.

    The plausibility floor is deliberately low — this module cannot know how many deployments exist
    without asking Cloudflare, and asking is the gate's job. What it can refuse is the degenerate
    shape: a coverage paragraph that has lost its ids and now names none.
    """
    rows, coverage = gate.recorded_rows(), gate.recorded_coverage()
    assert len(rows) >= 5, (
        f"only {len(rows)} deployment(s) have a row of their own: {sorted(rows)}. The table is the "
        "record; a table that has lost its rows accounts for nothing"
    )
    assert len(coverage) >= 5, (
        f"the pinned coverage set names {len(coverage)} deployment(s): {sorted(coverage)}. It is "
        "the retrospective account of the deployments that predate the record, and it replaced a "
        "date range precisely so that it could be compared to a list"
    )
    # The set is CLOSED, and its size is spelled out in the marker the gate anchors on, so the
    # word and the ids can disagree with nothing noticing. That is a stale count one layer in —
    # the shape `packages/cdm/synapse_cdm/README.md`'s sweep rule 8 exists for — so the two are
    # compared. A deployment that happens from now on gets a ROW; nothing joins this set.
    words = {"eleven": 11, "twelve": 12, "thirteen": 13}
    spelled = [word for word in words if word in gate.COVERAGE_MARKER]
    assert len(spelled) == 1, (
        f"the coverage marker {gate.COVERAGE_MARKER!r} spells {spelled} number words. It must "
        "spell exactly one, because that word is the only statement of the set's size"
    )
    assert words[spelled[0]] == len(coverage), (
        f"the coverage paragraph says {spelled[0]!r} and names {len(coverage)} ids: "
        f"{sorted(coverage)}. The set is closed — a deployment made from now on gets a row of its "
        "own — so a disagreement here is either an id added to a closed set or a word left behind"
    )
    assert not (rows & coverage), (
        f"{sorted(rows & coverage)} are accounted for twice — once as a row and once in the "
        "coverage set. Two accounts of one deployment is two things to keep in agreement"
    )


def test_the_coverage_set_is_a_set_of_ids_and_not_a_date_range(gate):
    """The exact shape the gate was written against, forbidden by substring.

    The table's first version carried `| eleven earlier | 2026-08-22 → 2026-08-25 | all resolve |`.
    That row cannot be wrong about an id it never mentions, so nothing could check it, and a
    deployment landing inside the range would have been covered by it silently. The row was also
    wrong in its own terms — one of the eleven happened ninety-two seconds AFTER the row above it —
    which is recorded in the entry.
    """
    section = gate.entry_section()
    assert "| eleven earlier |" not in section, (
        "ledger entry 8's table has gone back to accounting for deployments by a date range. That "
        "is the shape gates/deploy_record.py cannot check: name the ids in the coverage paragraph"
    )


def test_the_record_names_the_alias_holder_and_the_domain(gate):
    """Both halves of the claim the gate pins, and it is the claim that went false."""
    holder = gate.recorded_alias_holder()
    assert len(holder) == 8 and all(c in "0123456789abcdef" for c in holder), (
        f"the alias paragraph yielded {holder!r}, which is not an 8-character deployment prefix"
    )
    assert holder in gate.recorded_rows(), (
        f"the record says `{holder}` serves the custom domain and gives it no row of its own. The "
        "deployment that is being served is the one that most needs a row"
    )
    domain = gate.custom_domain()
    assert "." in domain and not domain.endswith(".pages.dev"), (
        f"custom_domain() returned {domain!r}. It must be the custom hostname, not a pages.dev "
        "preview URL — comparing a deployment against its own preview URL is a tautology"
    )
    assert domain in RECORD.read_text(), f"{domain!r} does not occur in the record it was read from"


# -------------------------------------------------- the reconciliation, on synthetic input


def test_reconcile_passes_when_every_listed_deployment_is_recorded(gate):
    """The baseline. Built from the record's own ids, so it passes for the right reason."""
    known = gate.recorded_rows() | gate.recorded_coverage()
    result = gate.reconcile([_deployment(gate, short) for short in sorted(known)])
    assert result["listed"] == len(known), result
    assert result["rows"] + result["coverage"] == len(known), (
        f"reconcile() accounted for {result['rows']} + {result['coverage']} of {len(known)}"
    )


def test_reconcile_refuses_a_deployment_the_record_cannot_name(gate):
    """Direction one: the defect the gate exists for.

    Sixteen deployments, two recorded. A gate that cannot fail on this is not a gate.
    """
    known = sorted(gate.recorded_rows() | gate.recorded_coverage())
    listed = [_deployment(gate, s) for s in known] + [_deployment(gate, "deadbeef")]
    with pytest.raises(gate.Finding) as raised:
        gate.reconcile(listed)
    assert "deadbeef" in str(raised.value), (
        f"the refusal does not name the offending deployment:\n{raised.value}"
    )
    assert "cannot name" in str(raised.value)


def test_reconcile_refuses_an_id_the_project_does_not_list(gate):
    """Direction two, and it is the one that stops the gate being satisfiable by typing rows.

    A record that may add ids freely can always be made to pass. An id in the table that Cloudflare
    has never held is either a typo — in which case the row accounts for nothing — or a deleted
    deployment, which is a fact the entry should state rather than leave as a row that no longer
    resolves.
    """
    known = sorted(gate.recorded_rows() | gate.recorded_coverage())
    with pytest.raises(gate.Finding) as raised:
        gate.reconcile([_deployment(gate, s) for s in known[1:]])
    assert known[0] in str(raised.value), (
        f"the refusal does not name the id that failed to resolve:\n{raised.value}"
    )
    assert "does not list" in str(raised.value)


def test_reconcile_refuses_a_deployment_accounted_for_twice(gate):
    """A row AND a coverage entry for one deployment is two things to keep in agreement.

    This is not pedantry about tidiness: the coverage set exists to say "these were never written
    down individually", so a deployment in both is a contradiction about its own history.
    """
    duplicated = sorted(gate.recorded_rows())[0]
    section = gate.entry_section()
    marker = gate.COVERAGE_MARKER
    paragraph = section[section.index(marker):].split("\n\n", 1)[0]
    assert duplicated not in paragraph, (
        f"`{duplicated}` has a row AND appears in the coverage paragraph. The gate's own overlap "
        "check will refuse this; it is asserted here so the failure arrives from pytest"
    )


def test_the_alias_probe_is_not_a_tautology(gate):
    """`serving_deployment` must require a DIFFERENCE from the previous deployment, not just a match.

    Asserted against the source rather than by running it, because running it needs the network.
    The property: a check that only compared the live site to one deployment would pass if every
    deployment served identical bytes — which is exactly the state a project has before its second
    deploy, and exactly when the claim means least. `PUBLICATION.md`'s flip measurement had this
    half and said why; the gate must not lose it.
    """
    source = GATE_PATH.read_text()
    for fragment in ("differing_from_previous", "previous.preview", "byte-identical to BOTH"):
        assert fragment in source, (
            f"gates/deploy_record.py no longer carries {fragment!r}, so the alias probe may have "
            "lost the half that makes it a measurement: identical to the current deployment AND "
            "different from the one before it"
        )


def test_the_gate_does_not_read_a_credential_out_of_a_config_file(gate):
    """It shells out to wrangler, and that decision is load-bearing rather than stylistic.

    The first draft read wrangler's OAuth token from its config file and called the REST API. The
    token had expired four hours earlier; the API answered `9109 Invalid access token` while
    `wrangler` itself worked, because wrangler refreshes on use. A gate that manages credentials
    reports an authentication failure as a deployment finding.
    """
    source = GATE_PATH.read_text()
    for forbidden in ("oauth_token", "CLOUDFLARE_API_TOKEN", "api.cloudflare.com"):
        assert forbidden not in source, (
            f"gates/deploy_record.py mentions {forbidden!r}. The list comes from `npx wrangler`, "
            "which refreshes its own token; a gate that reaches for the credential directly fails "
            "with an auth error dressed up as a reconciliation finding"
        )
    assert '"npx", "wrangler"' in source, (
        "the gate no longer invokes wrangler, so it is getting the deployment list from somewhere "
        "that is not the tool the deploy itself uses"
    )


def test_the_gate_is_not_a_suite_member_and_says_so(gate):
    """A protocol act nobody can run is a protocol act nobody runs.

    The same assertion `tests/test_cdm_commit_message.py` makes about its own gate: the usage block
    has to be in the file, because re-running a protocol act should be copying and not designing.
    """
    doc = gate.__doc__ or ""
    assert "python gates/deploy_record.py" in doc, (
        "the gate's docstring no longer shows how to run it. `PUBLICATION.md` calls re-witnessing a "
        "protocol act on the grounds that the probes are written out in full"
    )
    assert "--mutation-check" in doc, (
        "the gate no longer documents its mutation check. A gate nobody has seen fail is a gate "
        "nobody has seen"
    )
