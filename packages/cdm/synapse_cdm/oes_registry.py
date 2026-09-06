"""The two packaged SC-OES registries, read as data, and the seven helpers over them.

WHAT THIS MODULE IS
-------------------
`synapse_cdm/registry/sc_oes/` holds the machine-readable runtime artefacts ADR 0004 puts there:
`event_types.json`, the governed event contract, hand-authored under
`spec/governance/EVENT-TYPE-PROCESS.md`, and `ontology_terms.json`, generated from the Turtle
authority by `gates/ontology_terms.py` and drift-tested against it. This module loads both,
validates them against their declared shape, and exposes the helper surface ADR 0004 decision 7
names — so a consumer asks a question rather than opening a path.

WHY IT IS NOT CALLED `registry.py`
----------------------------------
`synapse_cdm/registry/` is a DATA directory, and a module of the same name beside it would make
`synapse_cdm.registry` mean two things a reader has to disambiguate by knowing which one wins.
ADR 0004 decision 6 spent a whole decision keeping three meanings of the word "spec" visibly
distinct inside this repository; naming this module after the directory it reads would create the
same collision one word over. `oes_registry` says which registries and whose.

DATA, NEVER CODE (§17, ADR 0004 decision 8)
-------------------------------------------
Both files are parsed as JSON and validated. Nothing in either is imported, evaluated or executed
— in particular `payload_model` is a MODEL NAME checked against `OES_PAYLOAD_MODELS`, which is
declared below in Python, and never an import path the loader resolves. A registry that could name
a module to import would be a registry that could name any module to import.

The files are reached through `importlib.resources.files("synapse_cdm")`, the way
`adapter.fixture_root()` (`adapter.py`) already resolves packaged data: it asks the import system
where this package's data is, so the answer is right from an installed wheel, from a zip and from
a checkout, and §17's "require no repository checkout" holds without a path being written down
anywhere a consumer can see it.

RECOGNITION LIVES HERE; SYNTAX STAYS IN `oes.py`
------------------------------------------------
ADR 0003 decision 6 splits the two questions, and both halves keep their names. `oes.py`'s
`is_governed_event_type` and `is_governed_ontology_term` answer whether an identifier matches a
frozen grammar and read no file; `get_event_type` and `get_ontology_term` here answer whether the
governed set contains it, which is what a registry is for. So
`sc.air.imaginary_thing.v1` is valid syntax (`is_governed_event_type` -> True) and unrecognised
(`get_event_type` -> None), which is exactly the state conformance dimensions C and E report and
a model validator must never decide.

`is_governed_ontology_term` is §126's fifth helper and is the one already exported from `oes.py`.
It is not redefined here: a second function of that name, answering a different question, would
put the ADR 0003 split back into the shape it exists to prevent.
"""
from __future__ import annotations

import functools
import importlib.resources
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from synapse_cdm.enums import EventType
from synapse_cdm.models import GnssInterferencePayload
from synapse_cdm.oes import (
    SEMVER_RE,
    EventClass,
    is_governed_event_type,
    validate_ontology_identifier,
)

#: Where the two artefacts live inside the package. Named once; every reader below goes through
#: `_read()` rather than repeating it, which is the point of ADR 0004 decision 7.
REGISTRY_DIR = ("registry", "sc_oes")
EVENT_TYPES_FILE = "event_types.json"
ONTOLOGY_TERMS_FILE = "ontology_terms.json"

#: The strictness the canonical objects use (`models.py`), for the same reason one level down: a
#: registry that tolerated an undeclared key would let a governed field arrive misspelt and mean
#: nothing, and the registry is the machine authority — there is nothing behind it to catch that.
STRICT = ConfigDict(extra="forbid")


class Maturity(StrEnum):
    """What this specification commits to for a governed type — §51, and it is registry-owned.

    §50 is explicit that maturity does not belong in `Event.oes`: it is a property of the TYPE,
    not of an occurrence of it, so a producer never asserts it and a consumer reads it here. That
    is why this vocabulary lands with the registry rather than with the wire block in `oes.py`.
    """
    EXPERIMENTAL = "EXPERIMENTAL"
    DRAFT = "DRAFT"
    STABLE = "STABLE"
    DEPRECATED = "DEPRECATED"


#: The seven profiles of §113, each declared at 0.1.0 in its own document under
#: `spec/sc-oes/profiles/`. Held as a closed tuple because "profile exists" is one of §139's
#: registry checks and a check against an open set is not a check.
PROFILES: tuple[str, ...] = ("PNT", "Air", "Logistics", "ISR", "C2", "Mission", "Decision")

#: `type_id` -> the model a conformant producer's payload is checked against (§111). Exactly one
#: entry in v0.1.0, and it REUSES `GnssInterferencePayload` (`models.py`) rather than declaring a
#: second GNSS payload — §112: "Reuse the existing `GnssInterferencePayload`. Do not duplicate
#: it." The other twelve governed types keep free-form payloads until their semantics are stable
#: enough to freeze, which is a decision §112 takes deliberately and not a gap.
#:
#: Validation against these is a CHECK and never a transformation: nothing here rewrites,
#: coerces, reorders or drops payload content, and extra source-specific fields survive because
#: the model itself is `extra="allow"`.
OES_PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "sc.pnt.gnss_interference.v1": GnssInterferencePayload,
}


class EventTypeRecord(BaseModel):
    """One governed event type, with the fourteen fields §110 lists and not a fifteenth.

    Every key is present on every record, including `legacy_event_type` when it is null: §110
    requires it, and `03-event-types.md` says why in one line — "A missing key and an explicit
    null are different facts: the first says nobody considered the mapping, the second says
    somebody considered it and there is none."
    """
    model_config = STRICT

    id: str = Field(description="The governed `sc.` type identifier, the registry's key.")
    title: str = Field(min_length=1, description="A human title; not an identifier.")
    description: str = Field(min_length=1, description="What the type asserts, in prose.")
    domain: str = Field(min_length=1, description="The `<domain>` segment of `id`.")
    profile: str = Field(description="The owning profile, one of PROFILES.")
    profile_version: str = Field(description="The owning profile's own version (§48).")
    event_class: EventClass
    maturity: Maturity
    ontology_class: str = Field(description="The governed ontology class this type instantiates.")
    payload_model: str | None = Field(
        description="The name of the model in OES_PAYLOAD_MODELS, or null for a free-form payload."
    )
    legacy_event_type: EventType | None = Field(
        description="The broad legacy CDM EventType a conformant producer sets, or null where no "
                    "meaningful legacy category is governed (§27, ADR 0007). Never absent."
    )
    introduced_in: str = Field(description="The SC-OES version that introduced the type.")
    deprecated: bool
    replacement: str | None = Field(
        description="The governed type that replaces a deprecated one; null otherwise."
    )

    @field_validator("id")
    @classmethod
    def _governed_id(cls, v: str) -> str:
        """The registry may only carry `sc.*` types, and only well-formed ones.

        An `x.*` type is a third party's governed contract and is not this repository's to
        govern (`03-event-types.md`); a malformed `sc.*` identifier is refused rather than
        repaired, the same way the model validators refuse one on the wire.
        """
        if not is_governed_event_type(v):
            raise ValueError(
                f"registry id {v!r} is not a governed type identifier: the grammar is "
                "sc.<domain>.<event_name>.v<major> and only the sc. namespace is governed here"
            )
        return v

    @field_validator("profile")
    @classmethod
    def _known_profile(cls, v: str) -> str:
        if v not in PROFILES:
            raise ValueError(
                f"profile {v!r} is not one of the seven declared profiles {PROFILES}; a registry "
                "entry may not name a profile that has no document"
            )
        return v

    @field_validator("profile_version", "introduced_in")
    @classmethod
    def _semver(cls, v: str) -> str:
        if SEMVER_RE.fullmatch(v) is None:
            raise ValueError(f"{v!r} is not a semantic version, and a version segment is required")
        return v

    @field_validator("ontology_class")
    @classmethod
    def _ontology_class(cls, v: str) -> str:
        """Syntax here; whether the ontology minted it is checked against the term registry.

        `validate_ontology_identifier` refuses an impersonated identifier under the governed
        prefix, which is the half that must hold even where a term registry is unavailable.
        """
        return validate_ontology_identifier(v)

    @model_validator(mode="after")
    def _domain_matches_id(self) -> "EventTypeRecord":
        """`domain` restates the identifier's second segment, and disagreeing is a defect.

        The field exists because a consumer filtering by domain should not have to parse an
        identifier; it is not a second, independent classification.
        """
        segment = self.id.split(".")[1]
        if self.domain != segment:
            raise ValueError(
                f"entry {self.id!r} declares domain {self.domain!r} while its identifier's "
                f"domain segment is {segment!r} — the two are one fact"
            )
        return self

    @model_validator(mode="after")
    def _payload_model_resolves(self) -> "EventTypeRecord":
        """A declared payload model must be one this package actually carries (§139).

        The check is by NAME against `OES_PAYLOAD_MODELS` — the registry never names something
        to import. A declared name that resolves to nothing would be a contract a producer could
        not satisfy and a consumer could not check.
        """
        if self.payload_model is None:
            if self.id in OES_PAYLOAD_MODELS:
                raise ValueError(
                    f"entry {self.id!r} declares no payload model while OES_PAYLOAD_MODELS "
                    "registers one for it — the registry is the machine authority and the two "
                    "may not disagree"
                )
            return self
        model = OES_PAYLOAD_MODELS.get(self.id)
        if model is None or model.__name__ != self.payload_model:
            raise ValueError(
                f"entry {self.id!r} declares payload model {self.payload_model!r}, which "
                "OES_PAYLOAD_MODELS does not register for that type"
            )
        return self

    @model_validator(mode="after")
    def _deprecation_carries_its_migration(self) -> "EventTypeRecord":
        """A deprecated entry says what to move to; a live one does not name a replacement.

        §139's last registry check. A deprecation with no migration information is the shape that
        leaves a producer with nowhere to go, and `spec/governance/DEPRECATION-POLICY.md` is what
        this enforces the machine half of.
        """
        if self.deprecated and self.replacement is None and self.maturity != Maturity.DEPRECATED:
            raise ValueError(
                f"entry {self.id!r} is deprecated and names neither a replacement nor DEPRECATED "
                "maturity — a deprecation without migration information is a dead end"
            )
        if not self.deprecated and self.replacement is not None:
            raise ValueError(
                f"entry {self.id!r} is not deprecated and names a replacement {self.replacement!r}"
            )
        return self


class EventTypeRegistry(BaseModel):
    """The `event_types.json` document: its own provenance header, and the governed entries."""
    model_config = STRICT

    artefact: str
    artefact_version: str
    sc_oes_version: str
    namespace: str
    authored: str
    authority: str
    event_types: list[EventTypeRecord]

    @model_validator(mode="after")
    def _unique_ids(self) -> "EventTypeRegistry":
        seen: set[str] = set()
        for entry in self.event_types:
            if entry.id in seen:
                raise ValueError(
                    f"duplicate registry id {entry.id!r}: an identifier is the key of exactly one "
                    "governed contract"
                )
            seen.add(entry.id)
        return self


class OntologyTermRecord(BaseModel):
    """One governed ontology term, as `gates/ontology_terms.py` generates it from the Turtle.

    The shape is §102's, and the drift test that proves this file agrees with `ontology/*.ttl`
    is `tests/test_cdm_ontology.py` — repository-bound, because the Turtle authority does not
    ship. What ships is this projection of it, which is what runtime recognition reads (§102:
    "Runtime must not parse Turtle").
    """
    model_config = STRICT

    id: str
    label: str
    module: str
    kind: str
    parent: str | None
    maturity: Maturity
    deprecated: bool
    replacement: str | None


class OntologyTermRegistry(BaseModel):
    """The `ontology_terms.json` document, header included."""
    model_config = STRICT

    artefact: str
    artefact_version: str
    ontology_version: str
    namespace: str
    generated_by: str
    source_modules: list[str]
    generated: str
    terms: list[OntologyTermRecord]


def _read(name: str) -> Any:
    """Read one packaged registry as JSON, from wherever this package is installed."""
    root = importlib.resources.files("synapse_cdm")
    for part in REGISTRY_DIR:
        root = root / part
    return json.loads((root / name).read_text(encoding="utf-8"))


@functools.lru_cache(maxsize=1)
def _event_registry() -> EventTypeRegistry:
    return EventTypeRegistry.model_validate(_read(EVENT_TYPES_FILE))


@functools.lru_cache(maxsize=1)
def _term_registry() -> OntologyTermRegistry:
    return OntologyTermRegistry.model_validate(_read(ONTOLOGY_TERMS_FILE))


def list_event_types() -> tuple[EventTypeRecord, ...]:
    """Every governed event type, in the registry's own order (§103-§109's, by domain)."""
    return tuple(_event_registry().event_types)


def get_event_type(type_id: str) -> EventTypeRecord | None:
    """The governed entry for `type_id`, or `None` if the registry does not carry it.

    `None` is RECOGNITION failing, not syntax: a well-formed `sc.*` identifier that no entry
    declares is a dimension C failure and a valid `x.*` identifier is a third party's contract
    this registry never claims. Neither is an error here (ADR 0003 decision 6).
    """
    for entry in _event_registry().event_types:
        if entry.id == type_id:
            return entry
    return None


def get_profile_event_types(profile: str) -> tuple[EventTypeRecord, ...]:
    """Every governed type owned by `profile`, which must be one of the seven (§113).

    An unknown profile RAISES rather than returning empty: an empty tuple would read as "that
    profile governs nothing yet", which is true of no profile and would hide a typo.
    """
    if profile not in PROFILES:
        raise KeyError(
            f"{profile!r} is not one of the seven SC-OES profiles {PROFILES}"
        )
    return tuple(e for e in _event_registry().event_types if e.profile == profile)


def get_legacy_event_type(type_id: str) -> EventType | None:
    """The broad legacy `EventType` a conformant producer sets, or `None` where none is governed.

    `None` means §27's null exactly — "no meaningful legacy category is governed for this
    semantic type. It does not mean unfinished" — and it is returned for the six entries ADR 0007
    rules null. An UNGOVERNED `type_id` raises instead, because answering it with `None` would
    collapse the two facts into one value and a caller could not tell "no mapping is governed"
    from "this type is not governed at all".
    """
    entry = get_event_type(type_id)
    if entry is None:
        raise KeyError(
            f"{type_id!r} is not a governed event type; get_event_type() answers recognition and "
            "returns None for it"
        )
    return entry.legacy_event_type


def list_ontology_terms() -> tuple[OntologyTermRecord, ...]:
    """Every governed ontology term the packaged registry carries."""
    return tuple(_term_registry().terms)


def get_ontology_term(term_id: str) -> OntologyTermRecord | None:
    """The governed term record for `term_id`, or `None` if the ontology never minted it.

    This is the recognition half of `oes.is_governed_ontology_term`, which answers the grammar.
    A syntactically valid governed term that is absent here is a dimension E failure
    (`09-entity-semantics.md`), and a third-party identifier is opaque and is never mapped onto a
    governed term — so it, too, is simply absent.
    """
    for term in _term_registry().terms:
        if term.id == term_id:
            return term
    return None
