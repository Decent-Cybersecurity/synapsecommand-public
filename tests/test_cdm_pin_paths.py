"""`gates/pin_paths.py` — the resolver, and the fixtures that witness both conventions.

WHAT THIS FILE GUARDS, AND WHY IT IS NOT JUST A HAPPY-PATH TEST
---------------------------------------------------------------
The defect this module retires is **silent**. A `local_path` resolved against the wrong base names
a file that does not exist, and every pin check in this repository treats a non-existent subject as
a `pytest.skip` — correctly, because a fresh clone has the record and not the bytes. So a wrong
base and a fresh clone are indistinguishable from a green run, and a round reported an absence on
exactly that reading.

That property dictates the shape of this file. A test that only resolves a document and finds it
would pass against a resolver hard-wired to the package base, which is the defective resolver. So:

* `test_the_two_conventions_are_disjoint_on_the_tree` witnesses **both** conventions against the
  filesystem, and asserts the other base does NOT hold the file — the half that makes the rule
  falsifiable;
* `test_the_recorded_failures_shape_is_reproduced` reproduces the incident itself, as a fixture:
  a stream's `local_path` under the package base reads absent;
* `test_a_resolver_that_ignored_the_kind_would_fail_this_file` is the mutation — it builds the
  defective resolver and asserts it gets a pin wrong;
* `test_the_control_is_not_vacuous` proves the corpus is non-empty and that the digests are really
  compared, because a control run over zero pins reports the same "0 failed" as a clean one.

SKIPS ARE PER-CONVENTION AND NAMED, on `tests/test_cdm_pins.py`'s rule: a check skips iff its
subject is BYTES and must fail iff its subject is a RECORD. The corpus, the convention rule and the
refusal are records and never skip; the disjointness and digest checks are bytes and skip by
convention, naming which one is absent.
"""
from __future__ import annotations

import hashlib
import pathlib

import pytest

from gates import pin_paths


PINS = pin_paths.discover()
PRESENT = [p for p in PINS if p.resolved.exists()]


def _of_kind(kind: str) -> list[pin_paths.Pin]:
    return [p for p in PRESENT if p.kind == kind]


# --------------------------------------------------------------- the corpus is a RECORD, no skip

def test_the_corpus_is_discovered_and_carries_both_conventions():
    """The pin records name both kinds. A statement about JSON, so it never skips."""
    assert PINS, "no pins discovered at all — discover() found no local_path with a sha256"
    kinds = {p.kind for p in PINS}
    assert "spec" in kinds, f"no spec document is pinned anywhere; kinds are {sorted(kinds)}"
    assert "streams" in kinds, (
        f"no stream artefact is pinned anywhere; kinds are {sorted(kinds)}. This file's whole "
        f"subject is that two conventions exist, and with one kind in the corpus it is vacuous"
    )


def test_every_pin_resolves_without_refusal():
    """No pin in the tree has a `<kind>` the resolver does not know. A record check."""
    for pin in PINS:
        pin_paths.resolve(pin.local_path)  # raises UnknownConvention if the kind is unknown


def test_the_two_bases_are_different_directories():
    """If `PKG` and `REPO` were the same path every other test here would pass vacuously."""
    assert pin_paths.PKG != pin_paths.REPO
    assert pin_paths.PKG.is_relative_to(pin_paths.REPO)


def test_an_unknown_kind_is_refused_and_not_defaulted():
    """The refusal branch. A guess here would restore the silent-absence defect."""
    with pytest.raises(pin_paths.UnknownConvention) as excinfo:
        pin_paths.resolve("fixtures/klv/nowhere/whatever.bin")
    assert "nowhere" in str(excinfo.value)
    for shape in ("fixtures", "fixtures/klv", "spec/thing.pdf", ""):
        with pytest.raises(pin_paths.UnknownConvention):
            pin_paths.resolve(shape)


# ------------------------------------------------------- the conventions, witnessed against BYTES

@pytest.mark.parametrize("kind", ["spec", "streams"])
def test_the_two_conventions_are_disjoint_on_the_tree(kind):
    """The chosen base holds the file and the OTHER base does not. Both halves.

    The second half is the load-bearing one. Without it the rule is unfalsifiable: a resolver that
    returned whichever base happened to work would satisfy the first half and nothing else.
    """
    subjects = _of_kind(kind)
    if not subjects:
        pytest.skip(f"no {kind} pin has its bytes in this working tree; the records are checked "
                    f"unconditionally above")
    for pin in subjects:
        chosen, wrong = pin.resolved, pin_paths.other_base(pin.local_path)
        assert chosen.exists(), f"{pin.local_path} resolves to {chosen}, which does not exist"
        assert not wrong.exists(), (
            f"{pin.local_path} exists under BOTH bases ({chosen} and {wrong}). The convention is "
            f"unfalsifiable while that holds, and one of the two is a stray duplicate"
        )


def test_the_recorded_failures_shape_is_reproduced():
    """THE INCIDENT, as a fixture: a stream read as absent because the package base was assumed.

    This is the failure a round actually recorded. It is reproduced rather than described, so that
    a future change making the two bases coincide fails here loudly instead of making the module
    pointless quietly.
    """
    streams = _of_kind("streams")
    if not streams:
        pytest.skip("no stream artefact in this working tree — .gitignore excludes "
                    "fixtures/klv/streams/ by a directory rule, so a fresh clone has neither")
    pin = streams[0]
    naive = pin_paths.PKG / pin.local_path          # `_full()`'s rule, applied to a stream
    assert not naive.exists(), (
        "the package base now holds a stream artefact, so the incident this module exists for can "
        "no longer be reproduced and the module's premise needs re-deriving"
    )
    assert pin.resolved.exists(), "the resolver must find what the naive base misses"
    assert pin.resolved != naive


def test_a_resolver_that_ignored_the_kind_would_fail_this_file():
    """THE MUTATION. Build the defective resolver and prove it gets the tree wrong.

    Two mutants, one per base, and each must be wrong about at least one pin whose bytes are here.
    If neither is wrong, the two conventions have collapsed into one and this whole module is
    unnecessary — which is a thing to be told rather than to pass through.
    """
    if not PRESENT:
        pytest.skip("no pinned bytes in this working tree to mutate against")
    for base, name in ((pin_paths.PKG, "always the package"), (pin_paths.REPO, "always the root")):
        wrong = [p for p in PRESENT if not (base / p.local_path).exists()]
        assert wrong, (
            f"a resolver that used {name} base resolves every present pin correctly, so nothing "
            f"here distinguishes it from the real one"
        )


# ------------------------------------------------------------------------ the control, and vacuity

def test_the_control_is_not_vacuous():
    """A control over zero pins reports "0 failed" exactly as a clean one does.

    So the count is asserted, and one digest is recomputed independently of `control()` — a
    comparison nobody performs and a comparison that passes look identical from the outside.
    """
    readings = pin_paths.control()
    assert len(readings) == len(PINS) > 0
    checked = [r for r in readings if r.present]
    if not checked:
        pytest.skip("no pinned bytes in this working tree; the readings are all absences")
    r = checked[0]
    assert hashlib.sha256(r.pin.resolved.read_bytes()).hexdigest() == r.digest
    assert r.matched is (r.digest == r.pin.sha256)


def test_the_control_reports_a_mismatch_rather_than_ignoring_it(tmp_path):
    """Feed the control a pin whose sha256 is wrong and require it to say so.

    Synthetic, on `test_cdm_pins.py`'s precedent for the cited class: a checker that CANNOT report
    a mismatch and one with nothing to report look the same from a green run.
    """
    if not PRESENT:
        pytest.skip("no pinned bytes in this working tree to build a synthetic mismatch from")
    good = PRESENT[0]
    bad = pin_paths.Pin(good.pin_file, good.local_path, "0" * 64, good.bytes_)
    (reading,) = pin_paths.control([bad])
    assert reading.present is True
    assert reading.matched is False, "a wrong sha256 was not reported as a mismatch"

    missing = pin_paths.Pin(good.pin_file, "fixtures/klv/streams/not-a-real-file.klv",
                            "0" * 64, None)
    (absent,) = pin_paths.control([missing])
    assert absent.present is False and absent.matched is None, (
        "an absent subject must be reported as absent and NOT as a mismatch — conflating the two "
        "is what let a wrong base read as a fresh clone"
    )


def test_the_convention_check_finds_nothing_to_complain_about():
    """`verify_convention` over the real tree. Its own vacuity is covered by the disjointness test."""
    assert pin_paths.verify_convention() == []


def test_the_byte_counts_the_pins_state_are_the_bytes_on_disk():
    """Where a pin states `bytes`, the resolved file is that long. A second axis on the resolution.

    A path that resolved to some *other* real file would still hash-mismatch, but a size check
    fails faster and names the shape of the error more plainly.
    """
    sized = [p for p in PRESENT if p.bytes_ is not None]
    if not sized:
        pytest.skip("no present pin states a byte count")
    for pin in sized:
        assert pin.resolved.stat().st_size == pin.bytes_, (
            f"{pin.local_path} resolves to {pin.resolved}, which is "
            f"{pin.resolved.stat().st_size} bytes; the pin says {pin.bytes_}"
        )


# --------------------------------------------------------- the mapping has exactly one home

def test_no_second_site_resolves_a_pin_path_by_hand():
    """The rule this module exists to enforce: one resolver, and the old sites now call it.

    Read from the sources rather than remembered. The three reproductions named in the module
    docstring are the subjects; each must now reach a base through `pin_paths` rather than by
    joining one itself.
    """
    subjects = ["test_cdm_pins.py", "test_cdm_format_coverage.py", "test_cdm_stanag4609_adapter.py"]
    here = pathlib.Path(__file__).parent
    for name in subjects:
        source = (here / name).read_text()
        assert "pin_paths" in source, (
            f"{name} was one of the three sites that resolved a pin path by hand and it no longer "
            f"references gates.pin_paths — either the refactor was reverted or a fourth spelling "
            f"of a base has appeared"
        )
