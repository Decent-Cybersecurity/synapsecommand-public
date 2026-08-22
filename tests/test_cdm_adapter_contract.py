"""The adapter contract is enforced at class-definition time, so these tests define classes.

Every failure here is one that would otherwise surface in production: an adapter with no
version stamping unattributable provenance, an "egress" adapter that raises on the first
outbound push, two adapters quietly sharing a name so the harness validates the wrong one.
"""
import datetime as _dt
import uuid

import pytest

from synapse_cdm import times
from synapse_cdm.adapter import REGISTRY, Adapter, discover, load_adapter
from synapse_cdm.enums import EntityType, Affiliation
from synapse_cdm.models import Entity


class _Minimal(Adapter):
    name = "test_minimal"
    version = "0.1.0"
    direction = "ingest"
    system = "TEST"

    def to_cdm(self, raw):
        return [Entity(source=self.source_ref(),
                       source_ids=[{"system": "TEST", "external_id": "E-1"}],
                       entity_id=uuid.uuid4(), entity_type=EntityType.UNKNOWN,
                       affiliation=Affiliation.UNKNOWN, valid_from=self.now())]


def test_an_adapter_without_identity_fails_at_import_time():
    with pytest.raises(TypeError, match="version"):
        class _NoVersion(Adapter):
            name = "test_no_version"
            direction = "ingest"
            system = "TEST"

            def to_cdm(self, raw):
                return []


def test_an_egress_adapter_that_cannot_emit_is_refused():
    """The failure belongs at import, not at 03:00 on the first outbound push."""
    with pytest.raises(TypeError, match="does not override from_cdm"):
        class _FakeEgress(Adapter):
            name = "test_fake_egress"
            version = "0.1.0"
            direction = "bidirectional"
            system = "TEST"

            def to_cdm(self, raw):
                return []


def test_an_ingest_adapter_that_can_emit_must_say_so():
    """Otherwise a real capability is invisible in the registry, which is how it goes unused."""
    with pytest.raises(TypeError, match="declare 'bidirectional'"):
        class _UndeclaredEgress(Adapter):
            name = "test_undeclared_egress"
            version = "0.1.0"
            direction = "ingest"
            system = "TEST"

            def to_cdm(self, raw):
                return []

            def from_cdm(self, objects):
                return {}


def test_a_duplicate_name_is_refused():
    with pytest.raises(TypeError, match="already registered"):
        class _Clash(Adapter):
            name = "test_minimal"
            version = "9.9.9"
            direction = "ingest"
            system = "TEST"

            def to_cdm(self, raw):
                return []


def test_a_bad_direction_is_refused():
    with pytest.raises(TypeError, match="ingest, egress or bidirectional"):
        class _BadDirection(Adapter):
            name = "test_bad_direction"
            version = "0.1.0"
            direction = "outbound"
            system = "TEST"

            def to_cdm(self, raw):
                return []


def test_abstract_intermediates_are_exempt():
    """A shared base between adapters is legitimate and must not have to fake a name."""
    class _SharedBase(Adapter):
        abstract = True

        def helper(self):
            return 1

    assert "" not in REGISTRY


def test_ingest_only_from_cdm_refuses_clearly():
    with pytest.raises(NotImplementedError, match="does not emit"):
        _Minimal().from_cdm([])


def test_the_clock_is_injected_and_adapter_code_never_calls_now_itself():
    frozen = _dt.datetime(2026, 1, 2, 3, 4, 5, tzinfo=_dt.timezone.utc)
    entity = _Minimal(clock=times.frozen_clock(frozen)).to_cdm({})[0]
    assert times.render(entity.valid_from) == "2026-01-02T03:04:05.000Z"
    # ... and the default clock is real time, not the frozen one.
    assert _Minimal().to_cdm({})[0].valid_from > frozen


def test_synthetic_defaults_true_and_is_overridable():
    assert _Minimal().source_ref().synthetic is True
    assert _Minimal(synthetic=False).source_ref().synthetic is False


def test_the_registry_resolves_by_name_and_by_module_path():
    assert load_adapter("test_minimal") is _Minimal
    assert load_adapter("synapse_cdm.adapters.pntmap:PntmapAdapter").name == "pntmap"
    with pytest.raises(LookupError, match="unknown adapter"):
        load_adapter("no_such_adapter")
    with pytest.raises(LookupError, match="not an Adapter subclass"):
        load_adapter("synapse_cdm.models:Entity")


def test_discovery_finds_the_shipped_adapters():
    assert "pntmap" in discover()


def test_the_abstract_escape_is_not_inherited():
    """A real adapter under a shared abstract base must still face every gate.

    With `getattr(cls, "abstract", False)` this passed silently: the concrete subclass
    inherited abstract=True and skipped validation entirely, which turns the gates off for
    precisely the adapters organised well enough to share a base class.
    """
    class _Base(Adapter):
        abstract = True

        def to_cdm(self, raw):
            return []

    with pytest.raises(TypeError, match="version"):
        class _Concrete(_Base):
            name = "test_inherits_abstract"
            direction = "ingest"
            system = "TEST"
