"""`--list-adapters`: the roster, without having to get something wrong to see it.

WHY THIS EXISTS
---------------
The registry decided what `--adapter` accepts and there was no way to ask it. A caller who did
not already know the ten names had two routes to them, and both were failures:

* `--adapter typo` — `LookupError: unknown adapter 'typo'; registered: adsb, ais, …`. The roster
  was a clause inside an error message, so the inventory was a side effect of misuse;
* a bare invocation — argparse's usage line, which names the FLAG and not one value it takes.

A verification tool whose whole job is to be the gate an adapter passes should be able to say
which adapters it knows. `--list-adapters` prints the name, version, direction, fixture directory
and system, and exits `0`.

THE FIXTURE DIRECTORY IS IN THE TABLE ON PURPOSE
------------------------------------------------
`stanag4676` replays `fixtures/nits`, and that relation was folklore until `Adapter.fixture_dir`
made it a declaration — folklore that produced a nine-adapter gate sweep reporting nine greens
with one of them vacuous. A reader who can see the mapping never has to learn it the way that
sweep did.

WHAT THIS MODULE CHECKS, AND THE ONE CHECK IT IS FOR
-----------------------------------------------------
A listing is a restatement of the registry, and a restatement can drift from the thing it
restates. The failure to fear is not a listing that crashes — it is a listing that is *written
down*: a tuple of ten names in `harness.py` that stays right until the eleventh adapter ships,
and then reads as authoritative while being wrong. So the load-bearing test here is a mutation:
the registry is changed under the code, and the OUTPUT has to change with it. A listing that
survives its registry being altered is a literal with a table around it.

The second is the disjunction. Two things now state the roster — the listing and the refusal in
`load_adapter` — and a fact stated twice can drift at one site. Both read `adapter.roster()`, and
this module additionally requires the two rendered OUTPUTS to name the same set, which is the
check that survives someone re-deriving one of them from `REGISTRY` directly.
"""
import json
import re

import pytest

from synapse_cdm import adapter, harness
from synapse_cdm.adapter import Adapter
from synapse_cdm.models import CDMBase

#: The names in the rendered table: every line after the rule, first column.
ROW = re.compile(r"^(?P<name>\S+)\s+(?P<version>\S+)\s+(?P<direction>\S+)\s+"
                 r"(?P<fixtures>\S+)\s+(?P<system>\S+)$")

#: The roster as `load_adapter` states it when a lookup fails.
REFUSAL = re.compile(r"registered: (?P<names>[^.]+)\.")


def listed(text: str) -> dict[str, dict]:
    """Parse the rendered table back into a mapping, so the assertion is about content."""
    out = {}
    body = text.split("-" * 10, 1)
    assert len(body) == 2, f"the listing has no rule line, so it has no table:\n{text}"
    for line in body[1].splitlines():
        match = ROW.match(line.strip())
        if match:
            out[match.group("name")] = match.groupdict()
    return out


def render() -> str:
    return harness.render_roster(adapter.roster())


# ------------------------------------------------------------------- the listing itself


def test_the_listing_names_every_registered_adapter_and_nothing_else():
    rendered = listed(render())
    assert set(rendered) == set(adapter.roster()), (
        f"the listing names {sorted(rendered)} and the registry holds "
        f"{sorted(adapter.roster())}. A roster that is not the registry is a second opinion "
        "about what `--adapter` accepts"
    )
    assert len(rendered) >= 10, (
        f"the listing has {len(rendered)} rows, which is fewer than the adapters this package "
        "ships — the row parser has probably stopped matching, and every check here would then "
        "be passing on an empty table"
    )


def test_every_row_states_the_adapter_s_own_declarations():
    """The columns, against the classes. A table can be right about names and wrong about rows."""
    rendered = listed(render())
    for name, cls in adapter.roster().items():
        row = rendered[name]
        assert row["version"] == cls.version, f"{name}: listed {row['version']}, is {cls.version}"
        assert row["direction"] == cls.direction, (
            f"{name}: listed {row['direction']}, declares {cls.direction}")
        assert row["system"] == cls.system, f"{name}: listed {row['system']}, is {cls.system}"
        assert row["fixtures"] == (cls.fixture_dir or cls.name), (
            f"{name}: listed fixture directory {row['fixtures']}, declares "
            f"{cls.fixture_dir or cls.name}. This column exists because that relation was "
            "folklore once, and folklore is what made a vacuous run look green"
        )


def test_the_listing_states_that_fixtures_do_not_have_to_be_passed():
    """The listing is where a reader learns the command, so it must state the whole command.

    A roster that shows names and leaves the caller to guess at `--fixtures` sends them back to
    the instruction that was wrong for every installed reader for as long as it existed.
    """
    text = render()
    assert "--adapter <name>" in text and "--fixtures" in text, (
        "the listing no longer tells the reader how to use a name once they have it"
    )


# ------------------------------------------------------------------ THE MUTATION CHECK
#
# The one this module is for. Everything above passes just as well against a hardcoded tuple of
# ten names; only these two can tell the difference.


def test_removing_an_adapter_from_the_registry_removes_it_from_the_listing(monkeypatch):
    """Break the registry; the listing must change."""
    before = listed(render())
    victim = "pntmap"
    assert victim in before, f"{victim} is not listed, so this mutation removes nothing"
    shrunk = {k: v for k, v in adapter.REGISTRY.items() if k != victim}
    monkeypatch.setattr(adapter, "REGISTRY", shrunk)
    after = listed(render())
    assert victim not in after, (
        f"{victim} was removed from the registry and the listing still names it. The roster is "
        "not being read from the registry — it is written down somewhere, and it will stay right "
        "until the next adapter ships and then be authoritatively wrong"
    )
    assert set(after) == set(before) - {victim}, (
        f"removing one adapter changed the listing by {set(before) ^ set(after)}"
    )


def test_adding_an_adapter_to_the_registry_adds_it_to_the_listing(monkeypatch):
    """The other direction, which is the one an eleventh adapter will exercise for real."""
    monkeypatch.setattr(adapter, "REGISTRY", dict(adapter.REGISTRY))

    class _ProbeAdapter(Adapter):
        name = "_probe_listing"
        version = "9.9.9"
        direction = "ingest"
        system = "PROBE"
        fixture_dir = "somewhere_else"

        def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
            raise NotImplementedError

    after = listed(render())
    assert "_probe_listing" in after, (
        "an adapter that registered itself does not appear in the listing, so a new adapter "
        "would have to be added to the roster by hand — which is the stale-list failure this "
        "check exists to make impossible"
    )
    row = after["_probe_listing"]
    assert row["version"] == "9.9.9" and row["direction"] == "ingest", row
    assert row["fixtures"] == "somewhere_else", (
        f"the fixture column shows {row['fixtures']!r} for an adapter declaring "
        "`fixture_dir = 'somewhere_else'`, so that column is derived from the name rather than "
        "from the declaration and would be wrong for exactly the adapter it exists for"
    )
    assert _ProbeAdapter.name in adapter.REGISTRY, "the probe never registered"


# ------------------------------------------------------- the disjunction: two sites, one set


def test_the_listing_and_the_refusal_name_the_same_set():
    """The roster is stated twice. The two statements are compared, not just their source."""
    with pytest.raises(LookupError) as caught:
        adapter.load_adapter("no_such_adapter")
    match = REFUSAL.search(str(caught.value))
    assert match, (
        f"the refusal no longer states the roster in the form this sweep reads:\n"
        f"  {caught.value}\nRe-anchor deliberately — a pattern that stops matching would leave "
        "the two sites unchecked while reading as a passing test"
    )
    from_refusal = {n.strip() for n in match.group("names").split(",")}
    from_listing = set(listed(render()))
    assert from_refusal == from_listing, (
        f"the refusal names {sorted(from_refusal)} and the listing names {sorted(from_listing)}. "
        "These are the only two places the roster is stated and they disagree"
    )


def test_the_refusal_points_at_the_flag_that_answers_it():
    """The error a reader meets by accident should name the thing they wanted."""
    with pytest.raises(LookupError) as caught:
        adapter.load_adapter("no_such_adapter")
    assert "--list-adapters" in str(caught.value), (
        "the unknown-adapter refusal does not mention `--list-adapters`. That message is where a "
        "caller who does not know the names actually ends up, so it is where the flag has to be "
        "advertised"
    )


# --------------------------------------------------------------------- the CLI behaviour


def test_the_flag_exits_zero_and_needs_no_adapter(capsys):
    """A caller who does not know a name must not be asked for one in order to be told them."""
    assert harness.main(["--list-adapters"]) == 0
    out = capsys.readouterr().out
    assert set(listed(out)) == set(adapter.roster()), (
        "the CLI's listing is not the roster; it renders something else"
    )


def test_the_json_form_carries_the_same_set(capsys):
    """`--json` is honoured, because a roster is exactly the thing something else will parse."""
    assert harness.main(["--list-adapters", "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert set(parsed) == set(adapter.roster())
    for name, cls in adapter.roster().items():
        assert parsed[name] == {"version": cls.version, "direction": cls.direction,
                                "system": cls.system,
                                "fixtures": cls.fixture_dir or cls.name}, parsed[name]


def test_a_bare_invocation_still_refuses_and_now_says_where_to_look(capsys):
    """`--adapter` stopped being argparse-required, so the requirement has to be re-imposed.

    Same exit status as before — argparse's `2` for a usage error — because a caller scripting
    against the old behaviour must not silently start getting a run.
    """
    with pytest.raises(SystemExit) as caught:
        harness.main([])
    assert caught.value.code == 2, (
        f"a bare invocation exited {caught.value.code}. It exited 2 when `--adapter` was "
        "`required=True`, and changing that is a change to every caller's error handling"
    )
    assert "--list-adapters" in capsys.readouterr().err


def test_an_empty_roster_is_reported_as_broken_rather_than_as_an_empty_table(monkeypatch):
    """The vacuous-pass shape, one more time: nothing must render as a tidy answer of none.

    `NoFixturesFound` exists because "0 passed, 0 failed" looked like a result. An empty roster
    is the same picture — a well-formed table with no rows reads as "this package ships no
    adapters", which is never true and always an import failure.
    """
    monkeypatch.setattr(adapter, "REGISTRY", {})
    monkeypatch.setattr(adapter, "discover", lambda: {})
    text = harness.render_roster(adapter.roster())
    assert "broken installation" in text, (
        f"an empty roster renders as:\n{text}\nIt has to say that this is a broken install, not "
        "print an empty inventory"
    )
