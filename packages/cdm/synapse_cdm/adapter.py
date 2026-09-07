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
import importlib.resources
import pathlib
import pkgutil
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Literal

from synapse_cdm import times
from synapse_cdm.manifest import AdapterMetadata
from synapse_cdm.models import CDMBase, SourceRef

#: UNCHANGED, and deliberately. `manifest.Direction` carries ARCHITECTURE.md §2's six values;
#: these three are the v1 wire and code spellings of its first three rows, and §1.2's additive
#: rule forbids v2 from removing or renaming a v1 name. A class in this repository therefore
#: still declares one of these three, and `metadata.direction` is required to agree with it.
Direction = Literal["ingest", "egress", "bidirectional"]

REGISTRY: dict[str, type["Adapter"]] = {}


class Adapter(ABC):
    name: ClassVar[str] = ""
    version: ClassVar[str] = ""
    direction: ClassVar[Direction] = "ingest"

    #: External system this adapter speaks for — goes into SourceRef.system.
    system: ClassVar[str] = ""

    #: THE v2 DECLARATION, and it is REQUIRED — M's ruling F1.1, 2026-09-07.
    #:
    #: Every concrete `Adapter` subclass MUST set this, at class definition, to a valid
    #: `AdapterMetadata`. `None` is the unset marker and `__init_subclass__` refuses it, in the
    #: same breath as a missing `name` or `version` and for the same reason: an adapter whose
    #: maturity, licence class, format edition and limitations are unknown is one nobody can
    #: decide to depend on, and a framework that INVENTED any of them for an undeclared adapter
    #: would be publishing a claim no one made.
    #:
    #: The framework synthesises nothing. There is no derived default, no `maturity: L0`
    #: fallback, no sixth licence class meaning "undeclared" — the specification has five and
    #: F1.1 records that inventing a sixth was the alternative and is refused.
    metadata: ClassVar[AdapterMetadata | None] = None

    #: Source paths whose values legitimately change in translation, mapped to the REASON.
    #: Printed by the harness on every run; see lossless.py for why the escape is loud.
    TRANSFORMS: ClassVar[dict[str, str]] = {}

    #: The directory under `synapse_cdm/fixtures/` holding this adapter's fixtures, when it is
    #: NOT the adapter's own name. Left None means "the same string as `name`", which is true of
    #: twelve of the fourteen shipped adapters — `stanag4676`, whose fixtures are in
    #: `fixtures/nits`, and `stanag4609`, whose fixtures are in `fixtures/klv`, are the two where
    #: the name and the directory differ today, and the split below is the reason rather than an
    #: accident.
    #:
    #: AND A THIRD STANAG-NAMED ADAPTER ARRIVED WITHOUT JOINING THEM, which is the case that
    #: shows what this split is actually about. `stanag4586` is named for a covering document
    #: exactly as the two above are, and it declares NO override: STANAG 4586's payload has no
    #: name of its own beyond the standard's number — its messages are "DLI messages" and its
    #: fixtures are `.s4586` — so the name the bytes want and the name the standard gives are one
    #: string. The rule is "the payload has another name", NOT "the adapter has a STANAG prefix",
    #: and until this adapter the two readings were indistinguishable.
    #:
    #: THE SECOND ONE ARRIVED WITHOUT MOVING THE FIRST HALF OF THIS SENTENCE. `stanag4609` shipped
    #: in 1.2.0 declaring `fixture_dir = "klv"`, which took the divergent set from one adapter to
    #: two while the roster went twelve to thirteen — so "eleven of" stayed arithmetically correct
    #: and "is the only one" went false, in one sentence, with nothing reading either half. Both
    #: halves are derived now: see `test_the_divergent_fixture_dirs_are_what_the_registry_declares`
    #: in `tests/test_cdm_prose_counts.py`, which reads the registry rather than this comment.
    #:
    #: WHY THIS IS DECLARED BY THE ADAPTER AND NOT LOOKED UP BY THE HARNESS
    #: -------------------------------------------------------------------
    #: The relation was folklore, and folklore is how `--adapter stanag4676 --fixtures
    #: fixtures/stanag4676` came to report a green run that replayed nothing: that directory holds
    #: only pinned standards, the fixtures are in `fixtures/nits`, and a nine-adapter gate sweep
    #: reported nine passes with one of them vacuous. `harness.NoFixturesFound` stopped that
    #: reading as a pass; this stops it being typed. The split is not an accident to be tidied
    #: away either — an adapter named after a STANDARD is named for a covering document, and the
    #: directory is named for the bytes it holds, so the two legitimately differ.
    #:
    #: `tests/test_cdm_harness.py` holds the same map written out by hand and requires the two to
    #: agree, which is the pin gate's arrangement: two independent statements of one fact, each
    #: checkable against the other and both against the disk.
    fixture_dir: ClassVar[str | None] = None

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
        # v2, and LAST of the class-definition checks on purpose: every refusal above is about
        # the v1 identity, and a v1 defect has to keep reporting itself in the words it always
        # did rather than being masked by "this adapter declares no metadata".
        _check_metadata(cls)
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

    # ------------------------------------------------------------------ Adapter API v2
    #
    # Four members, added by P1 under `ARCHITECTURE.md` §1.2, which freezes v2 as an ADDITIVE
    # layer: nothing above is removed or renamed, and `to_cdm`/`from_cdm` stay the implemented
    # pair through the whole of Part 1.

    @classmethod
    def capabilities(cls):
        """The machine-readable capability and limits block (§3.5), from the declaration.

        Read from `metadata` rather than assembled here, because §3.5's whole reason for putting
        `limits` inside `capabilities` is that the conformance suite and the parser-safety policy
        must read ONE declaration. A `capabilities()` that built its own block would be a second.
        """
        return cls.metadata.capabilities

    def detect(self, raw: bytes | dict) -> bool | None:
        """Does this adapter claim this payload? `None` means "cannot tell" (§1.2).

        THE DEFAULT IS WEAK AND IS DOCUMENTED AS WEAK. It attempts a translation and answers on
        whether that raised, which costs a full parse and, worse, answers True for any payload
        the adapter can make sense of even partially. A format with a magic number, a header or
        a category octet SHOULD override this with the cheap structural test — that is what the
        method is for, and the ADS-B, ASTERIX and KLV families all have one available.

        It is a default rather than an abstract method because §1.2 adds `detect` to EVERY
        adapter's surface, and an abstract addition would break every subclass outside this
        repository at import — which is precisely the MAJOR that §1.2's additive rule forbids.
        """
        try:
            self.to_cdm(raw)
        except Exception:
            return False
        return True

    def validate_source(self, raw: bytes | dict) -> list[str]:
        """Problems with `raw` as an instance of the SOURCE standard, independent of translation.

        Returns a list of human-readable problems; empty means "nothing this adapter can see".
        The default reports whatever a decode attempt raises, which is a weaker claim than the
        method's name promises: a payload can be a perfectly invalid instance of its standard and
        still decode, and this default will not say so. An adapter with a real structural
        validator overrides it.
        """
        try:
            self.to_cdm(raw)
        except Exception as problem:
            return [f"{type(problem).__name__}: {problem}"]
        return []

    def decode(self, raw: bytes | dict) -> list[CDMBase]:
        """The v2 spelling of `to_cdm`. A thin alias and nothing more (§1.2)."""
        return self.to_cdm(raw)

    def encode(self, objects: list[CDMBase]) -> bytes | dict:
        """The v2 spelling of `from_cdm`. A thin alias and nothing more (§1.2)."""
        return self.from_cdm(objects)


def _check_metadata(cls: type["Adapter"]) -> None:
    """The v2 half of the class-definition contract. Called from `__init_subclass__` only.

    A FUNCTION RATHER THAN MORE LINES INSIDE `__init_subclass__`, and the reason is this
    repository's own: `ARCHITECTURE.md` §1.1's table cites `adapter.py` line numbers for every v1
    element and a test holds each citation to what it points at, so the enforcement block is kept
    as short as the checks allow. The enforcement POINT does not move — this runs at class
    definition, before the class is registered.
    """
    declared = cls.__dict__.get("metadata", getattr(cls, "metadata", None))
    if declared is None:
        raise TypeError(
            f"{cls.__name__} declares no `metadata`. Adapter API v2 requires an "
            "`AdapterMetadata` on every adapter class: its format and edition, its licence "
            "class, its maturity and the evidence for it, its claim status, and what it does "
            "NOT do. None of those is derivable from the code, so none of them is invented for "
            "an adapter that does not state them — a synthesised maturity or licence class "
            "would be this repository asserting something about a third party's standard that "
            "nobody has checked"
        )
    if not isinstance(declared, AdapterMetadata):
        raise TypeError(
            f"{cls.__name__}.metadata is {type(declared).__name__}, not AdapterMetadata. A "
            "dictionary passes no validator, so the impossible combinations §16 enumerates "
            "would all be declarable"
        )
    wrong = []
    if declared.id != cls.name:
        wrong.append(f"metadata.id is {declared.id!r} and the registry name is {cls.name!r}")
    if declared.adapter_version != cls.version:
        wrong.append(f"metadata.adapter_version is {declared.adapter_version!r} and the class's "
                     f"version is {cls.version!r}")
    if declared.direction.value != cls.direction:
        wrong.append(f"metadata.direction is {declared.direction.value!r} and the class declares "
                     f"{cls.direction!r}")
    if wrong:
        raise TypeError(
            f"{cls.__name__}: the manifest and the implementation disagree — " +
            "; ".join(wrong) + ". §16 fails CI on an adapter version inconsistent with its "
            "implementation metadata, and the same argument reaches the identifier and the "
            "direction: a manifest a consumer filters on has to describe the class that runs"
        )


def roster() -> dict[str, type[Adapter]]:
    """Every name `--adapter` resolves without a module path, in one place.

    WHY THIS IS A FUNCTION AND NOT TWO SORTED LISTS
    -----------------------------------------------
    The roster is stated twice: once by `harness --list-adapters`, which a reader asks for, and
    once by `load_adapter`'s refusal, which a reader meets by accident. Two independent
    `sorted(REGISTRY)` calls would be two statements of one fact and could drift the moment one
    of them grew a filter — "only the ones with fixtures", "only the bidirectional ones" — which
    is the shape every stale count in this repository started as. So the refusal message and the
    listing read the same function, and `tests/test_cdm_list_adapters.py` requires the two
    OUTPUTS to name the same set as well, which is the check that survives someone re-deriving
    one of them.

    `discover()` first, because the registry is populated by import side effect: without it a
    fresh process reports an empty roster and the refusal reads "registered: none".
    """
    discover()
    return dict(sorted(REGISTRY.items()))


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
    known = roster()
    if reference not in known:
        raise LookupError(
            f"unknown adapter {reference!r}; registered: {', '.join(known) or 'none'}. "
            "`--list-adapters` prints the same set with each one's version, direction and "
            "fixture directory, and does not require a failed lookup to do it"
        )
    return known[reference]


def discover() -> dict[str, type[Adapter]]:
    """Import every module under synapse_cdm.adapters so subclasses register themselves."""
    from synapse_cdm import adapters as package

    for info in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"{package.__name__}.{info.name}")
    return dict(REGISTRY)


def fixture_root() -> pathlib.Path:
    """The packaged fixtures directory, found through package RESOURCES and not through the repo.

    THE DEFECT THIS EXISTS FOR
    --------------------------
    Every documented harness invocation used to spell `--fixtures` out as a path inside a CLONE
    of the repository this package is developed in — a directory that exists there and nowhere
    else. The package's own README told an installed reader to `pip install synapse_cdm` and then
    handed them that path on the next line. So the harness, whose entire purpose is to be the gate
    an adapter passes, could not be run by anyone who had installed the thing it gates.

    `importlib.resources.files()` asks the IMPORT SYSTEM where this package's data is, which
    answers correctly for a site-packages install, an editable install, a virtualenv, a checkout
    on `PYTHONPATH`, and a working directory anywhere at all.

    THE LIMIT, NAMED RATHER THAN HIDDEN
    -----------------------------------
    The harness reads a fixture directory with `iterdir()` and writes goldens into it, so it needs
    a real filesystem. A package imported from inside a zip has no such path and `files()` returns
    a Traversable that is not a `Path`. That is refused HERE with a message that says what is
    wrong, rather than surfacing as an `AttributeError` in the middle of a replay — and refused
    rather than worked around with a temporary extraction, because `--update-golden` writing into
    an extracted copy would report WROTE for files that vanish.
    """
    root = importlib.resources.files("synapse_cdm") / "fixtures"
    if not isinstance(root, pathlib.Path):
        raise RuntimeError(
            "synapse_cdm's fixtures are not on a real filesystem — this package looks to be "
            f"imported from an archive ({type(root).__name__}). The harness reads a fixture "
            "directory and can write golden files back into it, so it needs a directory it can "
            "walk. Install the wheel normally (pip does not zip-import) or pass --fixtures with "
            "an extracted path"
        )
    return pathlib.Path(root)


def packaged_fixtures(adapter: type[Adapter] | Adapter) -> pathlib.Path:
    """Where THIS adapter's fixtures live inside the installed package.

    Returns the directory whether or not it exists. A missing one is not this function's failure
    to report: `harness.run` already refuses a directory holding no fixtures, with a message that
    names the adapter, the path and the rule that matched nothing, and duplicating that judgement
    here would give the same condition two different error messages.
    """
    cls = adapter if isinstance(adapter, type) else type(adapter)
    return fixture_root() / (cls.fixture_dir or cls.name)
