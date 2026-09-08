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

from tests import probe_metadata


class _Minimal(Adapter):
    name = "test_minimal"
    version = "0.1.0"
    direction = "ingest"
    system = "TEST"
    metadata = probe_metadata("test_minimal")

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
            metadata = probe_metadata("test_no_version")

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
            metadata = probe_metadata("test_fake_egress", direction="bidirectional")

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
            metadata = probe_metadata("test_undeclared_egress")

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
            metadata = probe_metadata("test_minimal", version="9.9.9")

            def to_cdm(self, raw):
                return []


def test_a_bad_direction_is_refused():
    with pytest.raises(TypeError, match="ingest, egress or bidirectional"):
        class _BadDirection(Adapter):
            name = "test_bad_direction"
            version = "0.1.0"
            direction = "outbound"
            system = "TEST"
            metadata = probe_metadata("test_bad_direction")

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
            metadata = probe_metadata("test_inherits_abstract")


# ============================================================== Adapter API v2 (round P1)
#
# Every refusal below was run RED before the check existed and is green now — the same
# discipline the v1 refusals above were written under. What they guard is M's ruling F1.1: an
# adapter must DECLARE its metadata and the framework must synthesise none of it.


def test_an_adapter_without_metadata_fails_at_import_time():
    """The v2 counterpart of the missing-version refusal, and the reason is the same shape.

    A missing `version` makes provenance unattributable. A missing `metadata` makes an adapter
    undecidable: nothing says which edition of which standard it implements, whether that
    standard can be redistributed, or how far the translation has actually been checked. The
    framework does not fill any of that in — a synthesised maturity or licence class is this
    repository asserting something about somebody else's document that nobody verified.
    """
    with pytest.raises(TypeError, match="declares no `metadata`"):
        class _NoMetadata(Adapter):
            name = "test_no_metadata"
            version = "0.1.0"
            direction = "ingest"
            system = "TEST"

            def to_cdm(self, raw):
                return []


def test_metadata_that_is_not_an_adapter_metadata_is_refused():
    """A dict passes no validator, so every §16 combination would become declarable again."""
    with pytest.raises(TypeError, match="not AdapterMetadata"):
        class _DictMetadata(Adapter):
            name = "test_dict_metadata"
            version = "0.1.0"
            direction = "ingest"
            system = "TEST"
            metadata = {"id": "test_dict_metadata"}

            def to_cdm(self, raw):
                return []


def test_a_manifest_naming_a_different_version_from_the_implementation_is_refused():
    """§16's last CI clause: "adapter version inconsistent with implementation metadata"."""
    with pytest.raises(TypeError, match="metadata.adapter_version is '2.0.0'"):
        class _VersionSkew(Adapter):
            name = "test_version_skew"
            version = "0.1.0"
            direction = "ingest"
            system = "TEST"
            metadata = probe_metadata("test_version_skew", version="2.0.0")

            def to_cdm(self, raw):
                return []


def test_a_manifest_naming_a_different_id_from_the_registry_name_is_refused():
    """The same argument one field along: a manifest a consumer filters on names its own class."""
    with pytest.raises(TypeError, match="metadata.id is 'somebody_else'"):
        class _IdSkew(Adapter):
            name = "test_id_skew"
            version = "0.1.0"
            direction = "ingest"
            system = "TEST"
            metadata = probe_metadata("somebody_else")

            def to_cdm(self, raw):
                return []


def test_a_manifest_declaring_a_direction_the_class_does_not_is_refused():
    """§16's "impossible direction declared", in the form the class can see.

    The manifest says bidirectional and the class says ingest. Both statements are internally
    fine; together they are a published claim that this adapter emits, made by a class that
    `__init_subclass__` has already refused an egress path to.
    """
    with pytest.raises(TypeError, match="metadata.direction is 'bidirectional'"):
        class _DirectionSkew(Adapter):
            name = "test_direction_skew"
            version = "0.1.0"
            direction = "ingest"
            system = "TEST"
            metadata = probe_metadata("test_direction_skew", direction="bidirectional")

            def to_cdm(self, raw):
                return []


def test_the_v2_aliases_delegate_and_do_not_reimplement():
    """`decode`/`encode` are the v2 spellings and nothing more (ARCHITECTURE.md §1.2)."""
    adapter = _Minimal()
    assert adapter.decode({})[0].source.adapter == "test_minimal"
    with pytest.raises(NotImplementedError, match="does not emit"):
        adapter.encode([])


def test_capabilities_reads_the_declaration_rather_than_assembling_a_second_one():
    """§3.5's whole reason for putting `limits` inside `capabilities` is that there is ONE block."""
    assert _Minimal.capabilities() is _Minimal.metadata.capabilities


def test_detect_answers_on_a_translation_attempt_and_is_documented_as_weak():
    """The default is a full parse and it says so in its own docstring, which is the honest form.

    Asserted here rather than left to the docstring alone: a weak default that stops SAYING it is
    weak is a default somebody will trust for dispatch.
    """
    assert _Minimal().detect({}) is True
    assert "weak" in Adapter.detect.__doc__.lower()

    class _NeverTranslates(Adapter):
        name = "test_never_translates"
        version = "0.1.0"
        direction = "ingest"
        system = "TEST"
        metadata = probe_metadata("test_never_translates")

        def to_cdm(self, raw):
            raise ValueError("not mine")

    assert _NeverTranslates().detect(b"anything") is False
    assert _NeverTranslates().validate_source(b"anything") == ["ValueError: not mine"]
    assert _Minimal().validate_source({}) == []


# --- P3: Rule 5, and the projection that fills it (F3.3) ---------------------------------------


def test_the_provenance_stamp_carries_the_format_the_adapter_declares():
    """`source_ref()` READS `metadata.format`; it is not passed in and it is not guessed.

    That is what let all fourteen shipped adapters gain `source.format_name` and
    `source.format_version` in round P3 without one per-adapter edit — and it is what makes a
    disagreement between an object's stamp and its manifest impossible rather than merely
    unlikely: there is one declaration and this is a projection of it.
    """
    for name, cls in sorted(discover().items()):
        if not cls.__module__.startswith("synapse_cdm.adapters"):
            continue                              # test doubles defined by this suite
        ref = cls(synthetic=True).source_ref()
        assert ref.format_name == cls.metadata.format.name, name
        assert ref.format_version == cls.metadata.format.version, name


def test_a_null_format_version_on_the_stamp_is_a_reading_a_limitation_states():
    """A null edition is never a field nobody filled in — `AdapterMetadata` already refuses that.

    So the stamp inherits the guarantee: wherever `source.format_version` is null in a golden
    file, some limitation of that adapter says in words that no document in this tree states
    which edition it targets.
    """
    unstated = []
    for name, cls in sorted(discover().items()):
        if not cls.__module__.startswith("synapse_cdm.adapters"):
            continue
        if cls(synthetic=True).source_ref().format_version is None:
            said_so = any("format version" in line.lower() or "edition" in line.lower()
                          for line in cls.metadata.limitations)
            unstated.append(name) if not said_so else None
    assert unstated == [], (
        f"{unstated} stamp a null format_version with no limitation saying why")


def test_the_five_record_level_provenance_fields_are_not_filled_by_the_stamp():
    """`source_ref()` is called once per translation and has no source RECORD in front of it.

    `original_id`, `source_hash`, `record_index`, `observed_at` and `transformations` are facts
    about one record, so filling them here would put the first record's values on every object of
    the payload. An adapter that has them sets them per object.
    """
    ref = _Minimal(synthetic=True).source_ref()
    assert ref.original_id is None and ref.source_hash is None
    assert ref.record_index is None and ref.observed_at is None
    assert ref.transformations == []
