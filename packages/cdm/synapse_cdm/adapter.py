"""The Adapter contract: external format in, CDM out, and nothing else.

WHAT AN ADAPTER MAY NOT DO
--------------------------
Adapters are pure translation. No filtering ("we only forward hostile contacts"), no
enrichment ("we look up the vessel's flag"), no business logic ("below 0.3 confidence we drop
it"). Each of those is a DECISION, and a decision made inside a translator is a decision
nobody can find later: it is invisible in the CDM output, absent from the audit trail, and
discovered only when a commander asks why a contact never appeared. Decisions belong to the
agents and the fusion layer, where they are visible and attributable.

The contract is enforced at CLASS-DEFINITION time rather than at call time. `__init_subclass__`
refuses an adapter that leaves `name`/`version`/`direction` unset, or that declares itself
egress-capable without overriding `from_cdm`. An adapter that cannot honour its own declared
direction fails at import — before deployment, not on the first outbound push at 03:00.

REGISTRY, AND WHY THE HARNESS DOES NOT IMPORT ADAPTERS BY HAND
--------------------------------------------------------------
Subclasses register themselves by name. The harness resolves `--adapter pntmap` through this
registry, and also accepts `module:ClassName` for an adapter that lives outside this package —
which is the case that matters for the adapter factory, whose generated adapters will not be
in our tree and must still be validatable without editing the harness.

THE CLOCK
---------
`received_at` is the one field an adapter invents rather than reads: the instant WE took
delivery. It comes from the injected clock so that golden-output tests are possible at all
(see times.py). Adapter code calls `self.now()` and never `datetime.now()`.
"""
from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Literal

from synapse_cdm import times
from synapse_cdm.models import CDMBase, SourceRef

Direction = Literal["ingest", "egress", "bidirectional"]

REGISTRY: dict[str, type["Adapter"]] = {}


class Adapter(ABC):
    name: ClassVar[str] = ""
    version: ClassVar[str] = ""
    direction: ClassVar[Direction] = "ingest"

    #: External system this adapter speaks for — goes into SourceRef.system.
    system: ClassVar[str] = ""

    #: Source paths whose values legitimately change in translation, mapped to the REASON.
    #: Printed by the harness on every run; see lossless.py for why the escape is loud.
    TRANSFORMS: ClassVar[dict[str, str]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # `cls.__dict__`, NOT getattr: `abstract` must apply to the class that declares it and
        # NOT to its descendants. With getattr, a real adapter inheriting from a shared
        # abstract base inherits abstract=True and skips every check below — the gates would
        # then be silently off for exactly the adapters most likely to have a shared base.
        if cls.__dict__.get("abstract", False):
            return
        missing = [field for field in ("name", "version", "direction", "system")
                   if not getattr(cls, field, "")]
        if missing:
            raise TypeError(
                f"{cls.__name__} must set {', '.join(missing)} — an adapter with no name or "
                "version cannot be identified in a SourceRef, and provenance that cannot "
                "name its translator is not provenance"
            )
        if cls.direction not in ("ingest", "egress", "bidirectional"):
            raise TypeError(
                f"{cls.__name__}.direction must be ingest, egress or bidirectional, "
                f"got {cls.direction!r}"
            )
        if cls.direction in ("egress", "bidirectional") and \
                cls.from_cdm is Adapter.from_cdm:
            raise TypeError(
                f"{cls.__name__} declares direction {cls.direction!r} but does not override "
                "from_cdm(). An adapter that cannot emit must not claim it can: the failure "
                "would otherwise surface as a NotImplementedError on the first outbound push"
            )
        if cls.direction == "ingest" and cls.from_cdm is not Adapter.from_cdm:
            raise TypeError(
                f"{cls.__name__} overrides from_cdm() but declares direction 'ingest' — "
                "declare 'bidirectional' so the capability is discoverable in the registry"
            )
        existing = REGISTRY.get(cls.name)
        if existing is not None and existing is not cls:
            raise TypeError(
                f"adapter name {cls.name!r} is already registered by "
                f"{existing.__module__}.{existing.__qualname__} — names are how the harness "
                "and every SourceRef identify a translator, so they must be unique"
            )
        REGISTRY[cls.name] = cls

    def __init__(self, clock: times.Clock | None = None, *, synthetic: bool = True) -> None:
        """`synthetic` defaults to True — the safe direction for a repository of fixtures.

        Mislabelling exercise data as live is the dangerous error (it can reach an operational
        picture); mislabelling live data as exercise is visible and recoverable. A live
        deployment passes synthetic=False explicitly, which is a line of configuration someone
        has to write and review.
        """
        self._clock = clock or times.utc_now
        self._synthetic = synthetic

    def now(self):
        """Receipt time. Always through here — never datetime.now() in adapter code."""
        return self._clock()

    def source_ref(self) -> SourceRef:
        """The provenance stamp for every object this adapter emits."""
        return SourceRef(system=self.system, adapter=self.name,
                         adapter_version=self.version, synthetic=self._synthetic)

    @abstractmethod
    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """Translate one source payload into canonical objects.

        Returns a list because one payload legitimately produces several objects — a PNTMAP
        alert is an INTERFERENCE_SOURCE entity AND a GNSS_INTERFERENCE event, and forcing that
        into one object would mean inventing a container the rest of the platform does not use.

        Raises on a payload it cannot translate. It must not return a partial object and it
        must not return an empty list to signal failure: an empty list means "this payload
        legitimately carries nothing", and the two cases have to be distinguishable.
        """

    def from_cdm(self, objects: list[CDMBase]) -> bytes | dict:
        """Egress adapters override this. Ingest-only adapters inherit the refusal."""
        raise NotImplementedError(
            f"{type(self).__name__} is {self.direction}-only and does not emit"
        )


def load_adapter(reference: str) -> type[Adapter]:
    """Resolve 'pntmap' from the registry, or 'package.module:ClassName' by import.

    The second form is what makes the harness usable on an adapter it has never heard of —
    a generated one, or one being developed in a branch — without a code change here.
    """
    if ":" in reference:
        module_name, _, class_name = reference.partition(":")
        module = importlib.import_module(module_name)
        candidate = getattr(module, class_name, None)
        if candidate is None or not (isinstance(candidate, type) and issubclass(candidate, Adapter)):
            raise LookupError(f"{reference} is not an Adapter subclass")
        return candidate
    discover()
    if reference not in REGISTRY:
        known = ", ".join(sorted(REGISTRY)) or "none"
        raise LookupError(f"unknown adapter {reference!r}; registered: {known}")
    return REGISTRY[reference]


def discover() -> dict[str, type[Adapter]]:
    """Import every module under synapse_cdm.adapters so subclasses register themselves."""
    from synapse_cdm import adapters as package

    for info in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package.__name__}.{info.name}")
    return dict(REGISTRY)
