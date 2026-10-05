"""Module-level test doubles for `Adapter.fixture_instance` (`tests/test_cdm_fixture_instance.py`).

They live in a module of their own for the reason `tests/synthetic_parsers.py` gives: the
conformance suite's parser worker is a SPAWNED process that receives the adapter as a
`module:ClassName` reference and imports it, and a class defined inside a test function has no
importable name. Always import this module as `from tests import fixture_instance_double`: a
second module identity would define the classes again, and registering a name twice raises.

`RequiresContext` is an adapter whose constructor needs a context no generic caller can know, so
the plain construction refuses it. `ContextDouble` overrides the hook to supply the context its
packaged fixtures were recorded under, and refuses `synthetic=False`. The outer coded guard sits in
front of the SDK's own bound, the shape an adapter with its own error codes takes.
"""

from __future__ import annotations

import functools

from synapse_cdm import ids
from synapse_cdm.adapter import Adapter, InputTooLarge
from synapse_cdm.enums import Affiliation, EntityType
from synapse_cdm.models import Entity

from tests import probe_metadata

#: The four octets every payload this double accepts begins with.
MAGIC = b"FXD1"

#: The declared input bound, enforced by the coded guard and by the SDK's wrapper behind it.
MAX_INPUT_BYTES = 64

#: The context the hook override supplies for the packaged fixtures.
FIXTURE_CONTEXT = "packaged-fixture-context"

_MISSING = object()


class ContextMissing(ValueError):
    """The constructor was called without the context it requires, or the hook refused."""


class CodedRefusal(ValueError):
    """A refusal that carries its own error code."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(f"{code}: {message}")


class CodedInputTooLarge(CodedRefusal, InputTooLarge):
    """The coded guard's size refusal, still an `InputTooLarge` for check O."""


class RequiresContext(Adapter):
    """Needs `context` at construction and does NOT override the hook."""

    name = "fixture-context-required"
    version = "0.1.0"
    direction = "ingest"
    system = "probe"
    metadata = probe_metadata("fixture-context-required", max_input_bytes=MAX_INPUT_BYTES)

    def __init__(self, clock=None, *, context=_MISSING, synthetic=True):
        if context is _MISSING:
            raise ContextMissing(f"{type(self).__name__} needs a context at construction")
        super().__init__(clock=clock, synthetic=synthetic)
        self._context = context

    def to_cdm(self, raw):
        octets = bytes(raw)
        if len(octets) != 8 or octets[:4] != MAGIC:
            raise CodedRefusal("E_PROBE_PAYLOAD", "not a payload this double accepts")
        external = octets[4:].decode("ascii")
        return [Entity(
            entity_id=ids.derive(self.system, external, kind="entity"),
            source_ids=[{"system": self.system, "external_id": external}],
            entity_type=EntityType.UNKNOWN, affiliation=Affiliation.UNKNOWN,
            valid_from=self.now(), source=self.source_ref(),
            attributes={"context": self._context},
        )]


def _coded_guard(inner):
    @functools.wraps(inner)
    def guarded(self, raw, *args, **kwargs):
        if not isinstance(raw, (bytes, bytearray, memoryview)):
            raise CodedRefusal("E_PROBE_TYPE", "octets only")
        size = len(bytes(raw))
        if size > MAX_INPUT_BYTES:
            raise CodedInputTooLarge(
                "E_PROBE_LIMIT", f"{size} octets is over the bound of {MAX_INPUT_BYTES}")
        return inner(self, raw, *args, **kwargs)
    guarded.__input_bounded__ = True
    return guarded


RequiresContext.to_cdm = _coded_guard(RequiresContext.to_cdm)


class ContextDouble(RequiresContext):
    """Overrides the hook with the packaged-fixture context and refuses `synthetic=False`."""

    name = "fixture-context-double"
    metadata = probe_metadata("fixture-context-double", max_input_bytes=MAX_INPUT_BYTES)

    @classmethod
    def fixture_instance(cls, clock=None, *, synthetic=True):
        if synthetic is not True:
            raise ContextMissing("the fixture context is synthetic; synthetic=False is refused")
        return cls(clock=clock, context=FIXTURE_CONTEXT, synthetic=True)


class StaticRefusal(RequiresContext):
    """Overrides the hook as a staticmethod that refuses, not as a classmethod."""

    name = "fixture-context-static"
    metadata = probe_metadata("fixture-context-static", max_input_bytes=MAX_INPUT_BYTES)

    @staticmethod
    def fixture_instance(clock=None, *, synthetic=True):
        raise ContextMissing("the static hook refuses")
