"""§40's input bounds: declared on all fourteen, enforced once, and proved to refuse.

WHAT THIS MODULE IS FOR
-----------------------
Round P5 declared `capabilities.limits.max_input_bytes` on every shipped adapter and put its
enforcement in `Adapter.__init_subclass__`, which wraps each subclass's own `to_cdm` at
class-definition time. Two things follow that a manifest alone cannot say, and both are here:

1. **The number is real.** One octet more than the bound is refused, for every adapter, before
   any decoder in the adapter's own module runs. A declared bound nothing exercised would be a
   number in a JSON file.
2. **The declaration is auditable.** M's F5.4 ruling requires each adapter to record where the
   figure came from, whether it is the format's NORMATIVE maximum or an IMPLEMENTATION CAP, where
   it is enforced and which test proves the refusal. The last of those is this module, and the
   tests below check that every adapter's basis names it — a citation that pointed at nothing
   would be the failure the field exists to prevent.

WHY THE BOUND IS ABOUT OCTETS AND NOT ABOUT THE PARSED TWIN
------------------------------------------------------------
`to_cdm` also accepts the `.parsed.json` twin that ships beside a byte fixture, and a twin is a
much larger representation of the same message: ADS-B's 14 wire octets serialise to over 400 as a
decoded document. `wire_size` returns `None` for anything that is not bytes or text, so the bound
does not apply there, and the reason is not squeamishness — a caller holding a parsed dict has
already done the parse the bound exists to prevent. `test_the_bound_does_not_apply_to_a_parsed_
twin` pins that decision so it cannot be quietly reversed into a rule that refuses legal fixtures.
"""
import pytest

from synapse_cdm import harness
from synapse_cdm.adapter import (Adapter, InputTooLarge, discover, enforce_input_bound,
                                 packaged_fixtures, roster, wire_size)
from synapse_cdm.manifest import LimitKind

from tests import probe_metadata


def shipped() -> dict:
    """The adapters this PACKAGE ships, not everything the registry holds.

    `roster()` is `REGISTRY`, and every `Adapter` subclass registers itself — including the
    doubles this module and four others define. A sweep parametrised on `roster()` would grow or
    shrink with pytest's import order, and a bound sweep that depended on import order would
    report a different set of adapters in a full run than in a single-module one. Written the
    same way `test_cdm_suite.py` writes it, and for the same reason.
    """
    discover()
    return {name: cls for name, cls in roster().items()
            if cls.__module__.startswith("synapse_cdm.adapters.")}


ADAPTERS = sorted(shipped())

#: The test the fourteen manifests name as the proof of their bound. Written once here and
#: compared against every declaration, so the citation cannot rot in fourteen places at a time.
THIS_TEST = ("tests/test_cdm_input_bounds.py::"
             "test_every_adapter_refuses_one_octet_over_its_declared_bound")


def _cls(name):
    return shipped()[name]


def _seed(name):
    """A byte payload this adapter would accept, from its own fixtures where it ships one."""
    cls = _cls(name)
    for path in sorted(packaged_fixtures(cls).iterdir()):
        if not path.is_file() or path.name.startswith(".") or \
                path.name in ("README.md", harness.PROVENANCE_FILE):
            continue
        raw = harness.load_raw(path)
        if isinstance(raw, (bytes, bytearray)):
            return bytes(raw)
    return b"{}"


def test_the_roster_is_not_empty():
    """A parametrised sweep over an empty roster passes and checks nothing."""
    assert len(ADAPTERS) >= 14, ADAPTERS


@pytest.mark.parametrize("name", ADAPTERS)
def test_every_adapter_declares_a_bound_with_a_basis(name):
    limits = _cls(name).metadata.capabilities.limits
    assert limits.max_input_bytes is not None, \
        f"{name} declares no max_input_bytes; §40 and M's F5.4 require one on all fourteen"
    assert "max_input_bytes" not in limits.absent_because
    basis = limits.declared_because["max_input_bytes"]
    assert basis.kind in (LimitKind.NORMATIVE, LimitKind.IMPLEMENTATION_CAP)
    assert basis.test == THIS_TEST, \
        f"{name}'s basis names {basis.test!r}, which is not the test that proves the refusal"
    assert "class-definition" in basis.enforced_at, basis.enforced_at
    assert len(basis.source) > 80, \
        f"{name}'s basis states {basis.source!r}, which cites nothing a reader could check"


@pytest.mark.parametrize("name", ADAPTERS)
def test_a_normative_bound_is_only_claimed_where_a_clause_is_quoted(name):
    """M's F5.4, in its own words: a limit "must NOT be described as the format's normative
    maximum unless the specification actually says so". Every adapter that claims NORMATIVE is an
    ASTERIX one, whose LEN field is two octets — the one bound in this repository that a published
    clause fixes exactly. Every other adapter says IMPLEMENTATION_CAP and says so in
    the basis text too, so a reader skimming the prose reaches the same conclusion as a consumer
    reading the enum."""
    basis = _cls(name).metadata.capabilities.limits.declared_because["max_input_bytes"]
    if basis.kind is LimitKind.NORMATIVE:
        assert "NORMATIVE" in basis.source and "§" in basis.source
        assert _cls(name).metadata.capabilities.limits.max_input_bytes == 0xFFFF
    else:
        assert "IMPLEMENTATION CAP" in basis.source
        assert "is NOT the format's normative maximum" in basis.source


@pytest.mark.parametrize("name", ADAPTERS)
def test_every_adapter_refuses_one_octet_over_its_declared_bound(name):
    """THE PROOF. One octet over is refused; the bound itself is not refused here.

    The oversized payload is built by repeating a real fixture, so it is not merely large — it is
    large and otherwise plausible, which is the case a bound has to catch. The assertion is on the
    exception CLASS and on the message naming both numbers: a refusal that said only "invalid"
    would leave an operator unable to tell a bound from a parse error.
    """
    cls = _cls(name)
    bound = cls.metadata.capabilities.limits.max_input_bytes
    seed = _seed(name)
    oversized = (seed * (bound // max(1, len(seed)) + 2))[:bound + 1]
    assert len(oversized) == bound + 1

    with pytest.raises(InputTooLarge) as raised:
        cls().to_cdm(oversized)
    assert str(bound) in str(raised.value) and str(bound + 1) in str(raised.value)


@pytest.mark.parametrize("name", ADAPTERS)
def test_the_bound_is_checked_before_the_adapter_s_own_decoder_runs(name):
    """§40's "before decode", as a fact about the call and not about the wording.

    The oversized payload is nothing any of the fourteen decoders can read — it is a fixture
    repeated past its own framing — so a decoder that saw it would raise its OWN error. Getting
    `InputTooLarge` and not `Cat048ParseError`, `GmtifError` or `ParseError` is what says the
    bound ran first.
    """
    cls = _cls(name)
    bound = cls.metadata.capabilities.limits.max_input_bytes
    payload = b"\xff" * (bound + 1)
    with pytest.raises(InputTooLarge):
        cls().to_cdm(payload)


@pytest.mark.parametrize("name", ADAPTERS)
def test_no_shipped_fixture_is_refused_by_its_own_adapter_s_bound(name):
    """A bound that refused the repository's own fixtures would be a bound chosen carelessly."""
    cls = _cls(name)
    bound = cls.metadata.capabilities.limits.max_input_bytes
    over = []
    for path in sorted(packaged_fixtures(cls).iterdir()):
        if not path.is_file() or path.name.startswith(".") or \
                path.name in ("README.md", harness.PROVENANCE_FILE):
            continue
        size = wire_size(harness.load_raw(path))
        if size is not None and size > bound:
            over.append((path.name, size))
    assert not over, f"{name} declares {bound} and ships {over}"


def test_the_bound_does_not_apply_to_a_parsed_twin():
    """`wire_size` answers `None` for a dict, and `enforce_input_bound` lets it through.

    Pinned because the opposite reading is the tempting one and it breaks the repository: ADS-B
    declares 64 octets, and every one of its sixteen `.parsed.json` twins serialises to more than
    that. A bound applied to twins would refuse fixtures whose wire form is 14 octets long.
    """
    assert wire_size({"a": 1}) is None
    assert wire_size([1, 2, 3]) is None
    assert wire_size(b"abcd") == 4
    assert wire_size("abcd") == 4
    assert wire_size("é") == 2

    adsb = _cls("adsb")
    assert adsb.metadata.capabilities.limits.max_input_bytes == 64
    enforce_input_bound(adsb, {"padding": "x" * 10_000})


def test_an_adapter_that_declares_no_bound_is_refused_nothing():
    """Absence stays absence. Inventing a default here would be the package choosing a number."""

    class _Unbounded(Adapter):
        name = "test-unbounded-input"
        version = "0.1.0"
        direction = "ingest"
        system = "TEST"
        metadata = probe_metadata("test-unbounded-input")

        def to_cdm(self, raw):
            return []

    assert _Unbounded.metadata.capabilities.limits.max_input_bytes is None
    assert _Unbounded().to_cdm(b"\x00" * 10_000) == []


def test_the_guard_is_installed_on_the_class_that_defines_the_decoder_and_not_twice():
    """One wrapper, on the class whose `to_cdm` it guards; a subclass inherits it unwrapped again.

    Double wrapping would measure the payload twice and report one refusal from two places, and
    the symptom would be a message naming the wrong class.
    """
    class _Parent(Adapter):
        name = "test-bound-parent"
        version = "0.1.0"
        direction = "ingest"
        system = "TEST"
        metadata = probe_metadata("test-bound-parent")

        def to_cdm(self, raw):
            return []

    class _Child(_Parent):
        name = "test-bound-child"
        metadata = probe_metadata("test-bound-child", max_input_bytes=4)

    assert "to_cdm" not in _Child.__dict__
    assert _Parent.to_cdm.__input_bounded__ is True
    assert _Parent().to_cdm(b"\x00" * 99) == []          # the parent declares no bound
    with pytest.raises(InputTooLarge, match="test-bound-child"):
        _Child().to_cdm(b"\x00" * 5)                     # the CHILD's declaration is what bites
