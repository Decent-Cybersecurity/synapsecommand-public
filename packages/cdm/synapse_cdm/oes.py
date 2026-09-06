"""SC-OES — the wire-semantic block that rides on the canonical `Event`, and nothing else.

WHAT THIS MODULE IS
-------------------
`OesMetadata` and the five models beneath it are the SynapseCommand Operational Event
Specification's contract, attached to the CDM as one optional declared field. The normative
documents are `spec/sc-oes/`; the decisions are `docs/adr/0001` (attachment), `0003`
(identifiers), `0005` (version impact) and `0008` (extensions). Nothing here is a second event
envelope: `Event` stays the only thing that happens, and an event carrying no block is a valid
CDM event that asserts no SC-OES semantics.

WHY THE BLOCK IS STRICT AND THE BAG IS ONE FIELD
------------------------------------------------
`models.py:8`-`:20` argues the canonical objects' `extra="forbid"`; this is the same argument
one level down. `01-core.md` states it as a rule: "Apart from `extensions`, the block is strict:
an undeclared key MUST be rejected rather than ignored or preserved." A strict block is what
makes a validation failure mean something, and one declared bag is what stops an unknown
producer's data from being smuggled into a core field to survive.

WHY EVERY IDENTIFIER IS A REGEX AND NOTHING IS REPAIRED
-------------------------------------------------------
Four identifier grammars are frozen — ADR 0003 decision 9 for the two event-type families and
the governed ontology term, ADR 0008 decision 3 for the extension key — and all four share one
production, `lower_label = [a-z][a-z0-9_]*`. Two readings from those ADRs are compiled in here
rather than restated:

- **`re.fullmatch`, never `$`.** `$` accepts a single trailing newline in Python, so a validator
  written straight from the `^…$` form of the grammar would admit an identifier with whitespace
  on the end (ADR 0003 decision 9's own note). The patterns below carry no anchors at all,
  because `fullmatch` is the anchor.
- **The character ranges are written out, never `\\w`.** `\\w` matches non-ASCII by default, so a
  grammar spelled with it would silently accept identifiers this one refuses and two
  implementations would differ without either looking wrong.

Nothing is normalised, case-folded, trimmed or otherwise repaired on the producer's behalf
(ADR 0003 decision 10): `ACME`, `radar-quality`, `v01`, `Air` and an identifier with surrounding
whitespace are invalid, not values to be tidied. A validator that repairs input silently makes
the repair the contract.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
-----------------------------------------
**Syntax only.** Whether a well-formed `sc.*` type is in the governed registry, and whether a
well-formed governed ontology term is one the ontology minted, are questions of RECOGNITION and
belong to the conformance dimensions (`13-conformance.md`), not to a model validator. So
`sc.air.imaginary_thing.v1` and `tag:synapsecommand.com,2026-09-06:ontology:air:ImaginaryThing`
both validate here and both fail their dimension. That split is ADR 0003 decision 6, and it is
the reason both grammars can be regexes.

**No network, no filesystem, no RDF.** Nothing here fetches, resolves, dereferences or parses
anything. `EXTERNAL_ARTIFACT.uri` is a string this package never retrieves (§84), `hash` is
descriptive metadata and not an integrity guarantee (`07-provenance-and-evidence.md`), and a
third-party ontology identifier stays opaque.

**No interpretation of an extension.** Nothing in this package reads inside an extension value,
maps it, or promotes it to a core field. That is what makes "an extension may not redefine a
core field" enforceable without refusing the key: a well-formed `x.acme.confidence` is accepted
and preserved precisely because nothing ever consults it (ADR 0008 decision 5).
"""
from __future__ import annotations

import re
import uuid
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Iterable

from pydantic import BaseModel, Field, field_validator, model_validator

from synapse_cdm.models import STRICT, SourceId, Timestamp

if TYPE_CHECKING:                                  # pragma: no cover - annotations only
    from synapse_cdm.models import Event


class EventClass(StrEnum):
    """What KIND of assertion an event is — the coarsest semantic distinction SC-OES makes.

    Eight members, and a consumer that understands no event type at all can still act on this
    one. It is asserted by the producer and never inferred: `02-event-classes.md` forbids
    deriving it from `type_id`, from the payload or from the producer's identity, because the
    whole value of the field is that somebody took responsibility for the claim.
    """
    OBSERVATION = "OBSERVATION"
    STATE_CHANGE = "STATE_CHANGE"
    CONSTRAINT = "CONSTRAINT"
    ASSESSMENT = "ASSESSMENT"
    IMPACT = "IMPACT"
    RECOMMENDATION = "RECOMMENDATION"
    DECISION = "DECISION"
    ACTION = "ACTION"


class LifecycleStatus(StrEnum):
    """The lifecycle state of the represented CONDITION — not of the message, not of a workflow.

    Optional, and absence is the ordinary case: most sensor sources report occurrences rather
    than managed conditions. `05-lifecycle.md` forbids defaulting it to `ACTIVE` or to anything
    else, and forbids deriving it from the effective interval — an event whose `effective_to`
    has passed is not thereby `EXPIRED`, because the interval is what the producer said about
    the world and this is what the producer says about the assertion's own standing.
    """
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    RETRACTED = "RETRACTED"
    SUPERSEDED = "SUPERSEDED"


class Verification(StrEnum):
    """How corroborated the assertion is. NOT confidence — `06-verification-and-confidence.md`.

    They vary independently and every combination is meaningful: a single high-grade sensor can
    be highly confident and entirely uncorroborated, and three weak sources can corroborate each
    other and leave the producer unsure. Absence means nothing is asserted about corroboration;
    `UNVERIFIED` is the positive claim that the question was asked and the answer was "no", which
    is a different and more informative fact. `DISPUTED` records that a disagreement exists and
    is not a verdict on it.
    """
    UNVERIFIED = "UNVERIFIED"
    CORROBORATED = "CORROBORATED"
    VALIDATED = "VALIDATED"
    DISPUTED = "DISPUTED"


class EventRelationPredicate(StrEnum):
    """The seven governed relationship predicates. Direction is part of the meaning.

    Five are carried by the LATER event and point at the earlier one; `CONTRADICTS` and
    `CORRELATES_WITH` are conceptually symmetric. An unrecognised predicate is a failure and
    must not be interpreted as a nearby one — `08-event-relationships.md` is explicit, because
    the nearby predicate is always a stronger claim than the one the producer could support.
    """
    DERIVED_FROM = "DERIVED_FROM"
    UPDATES = "UPDATES"
    SUPERSEDES = "SUPERSEDES"
    RESOLVES = "RESOLVES"
    RETRACTS = "RETRACTS"
    CONTRADICTS = "CONTRADICTS"
    CORRELATES_WITH = "CORRELATES_WITH"


class EvidenceKind(StrEnum):
    """What an evidence reference points at: another assertion, a source record, or the outside."""
    EVENT = "EVENT"
    SOURCE_RECORD = "SOURCE_RECORD"
    EXTERNAL_ARTIFACT = "EXTERNAL_ARTIFACT"


#: The SC-OES structural resource-safety bound, and the ONLY universal count this specification
#: fixes. `11-extensions.md` and ADR 0008 decision 7 both insist on what it is not: nesting depth
#: is not operational meaning, so a reader who takes it for a semantic rule will look for the
#: meaning of 16 and find none. Raising it later is compatible; lowering it is potentially
#: breaking, which is why it ships with the block rather than arriving after producers exist.
MAX_EXTENSION_DEPTH = 16

#: The two event-type grammars, ADR 0003 decision 9. Used with `fullmatch` — see the module
#: docstring on why `$` is the wrong anchor here.
GOVERNED_EVENT_TYPE_RE = re.compile(r"sc\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.v[1-9][0-9]*")
THIRD_PARTY_EVENT_TYPE_RE = re.compile(
    r"x\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.v[1-9][0-9]*"
)

#: The extension key grammar, ADR 0008 decision 3. Exactly three dot-separated parts.
EXTENSION_KEY_RE = re.compile(r"x\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*")

#: The governed ontology term grammar and the namespace it reserves, ADR 0003 decisions 3 and 5.
#: The authority date is ONE explicit date fixed for the lifetime of the v0.1 ontology namespace
#: — not shortened later, not derived at runtime, and not moved for a later ontology version.
GOVERNED_ONTOLOGY_PREFIX = "tag:synapsecommand.com,2026-09-06:ontology:"
GOVERNED_ONTOLOGY_TERM_RE = re.compile(
    r"tag:synapsecommand\.com,2026-09-06:ontology:[a-z][a-z0-9_]*:[A-Z][A-Za-z0-9]*"
)

#: `<scheme>:` per RFC 3986, used to test that a third-party identifier is ABSOLUTE. A relative
#: reference, a bare word and a local name all fail it, which is what §15's first test asks for.
URI_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:")

#: Semver, the same shape `CDMBase._semver` (`models.py:216`) already enforces on
#: `schema_version`. Reused rather than invented: the repository has exactly one way of spelling
#: a version on the wire, and a second one would be a second thing to keep correct.
SEMVER_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")

#: The reserved extension namespace. Every `sc.*` key fails in v0.1 as "reserved but undefined",
#: and no extension registry is created to represent an empty governed set (§30, ADR 0008).
RESERVED_EXTENSION_PREFIX = "sc."


def is_governed_event_type(type_id: str) -> bool:
    """Does `type_id` match the governed `sc.*` grammar? Syntax only — see the module docstring."""
    return GOVERNED_EVENT_TYPE_RE.fullmatch(type_id) is not None


def is_governed_ontology_term(term_id: str) -> bool:
    """Does `term_id` match the governed ontology-term grammar? Syntax, not recognition.

    A term that satisfies this and is absent from the packaged registry is syntactically valid
    and a dimension E failure (`09-entity-semantics.md`). The two questions are deliberately
    different, and answering the second one here would put registry lookup in a model validator.
    """
    return GOVERNED_ONTOLOGY_TERM_RE.fullmatch(term_id) is not None


def validate_type_id(type_id: str) -> str:
    """Accept a `type_id` under one of the two frozen grammars, or say which rule it broke."""
    if is_governed_event_type(type_id) or THIRD_PARTY_EVENT_TYPE_RE.fullmatch(type_id):
        return type_id
    if type_id.startswith("sc."):
        raise ValueError(
            f"type_id {type_id!r} claims the governed sc. namespace and does not match "
            "sc.<domain>.<event_name>.v<major>, where <domain> and <event_name> are "
            "[a-z][a-z0-9_]* and <major> is [1-9][0-9]* — nothing is case-folded, trimmed or "
            "otherwise repaired on a producer's behalf"
        )
    if type_id.startswith("x."):
        raise ValueError(
            f"type_id {type_id!r} claims the third-party x. namespace and does not match "
            "x.<namespace>.<domain>.<event_name>.v<major>, where each label is [a-z][a-z0-9_]* "
            "and <major> is [1-9][0-9]*"
        )
    raise ValueError(
        f"type_id {type_id!r} is in neither namespace: a governed type is sc.<domain>."
        "<event_name>.v<major> and a third-party type is x.<namespace>.<domain>.<event_name>."
        "v<major>. An unnamespaced identifier cannot be attributed to anybody"
    )


def validate_ontology_identifier(term_id: str) -> str:
    """Accept a governed term or a valid third-party semantic identifier; refuse impersonation.

    Three tests, §15's, in the order that makes the message useful:

    1. The governed grammar. A match is accepted and nothing further is asked of it.
    2. **Impersonation.** Anything else under the governed prefix is refused, because an
       identifier claiming this project's authority is held to this project's grammar. This is
       the reserved-namespace rule and the third-party rule seen from two sides
       (`09-entity-semantics.md`).
    3. The third-party tests: an absolute identifier with a valid scheme, and no whitespace or
       control character anywhere in it. Nothing more — a third-party identifier is opaque, is
       preserved as written, and is never mapped onto a governed term.
    """
    if GOVERNED_ONTOLOGY_TERM_RE.fullmatch(term_id):
        return term_id
    if term_id.startswith(GOVERNED_ONTOLOGY_PREFIX):
        raise ValueError(
            f"ontology identifier {term_id!r} is in the reserved SynapseCommand namespace "
            f"{GOVERNED_ONTOLOGY_PREFIX!r} and does not match its grammar: <module> is "
            "[a-z][a-z0-9_]* and <Term> is [A-Z][A-Za-z0-9]*. A third party may not mint a term "
            "here, and a governed term is not repaired into shape"
        )
    if any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in term_id):
        raise ValueError(
            f"ontology identifier {term_id!r} contains whitespace or a control character; a "
            "semantic identifier is a single opaque token and is not trimmed on a producer's "
            "behalf"
        )
    match = URI_SCHEME_RE.match(term_id)
    if match is None or match.end() == len(term_id):
        raise ValueError(
            f"ontology identifier {term_id!r} is not an absolute identifier: it must begin with "
            "a scheme, as <scheme>:<rest>. A bare word, a local name and a relative reference "
            "are all refused"
        )
    return term_id


def extension_depth(value: Any) -> int:
    """Nested JSON containers under ONE extension value, counted as SA.1 froze the algorithm.

    A rule is not an algorithm, and two implementations counting differently is the same defect
    as two parsing differently. ADR 0008 decision 7:

        scalar (null, boolean, number, string)   depth 0
        object or array as the extension value   depth 1
        each further nested object or array      +1
        object property names                    contribute nothing
        empty {} or []                           still a container, so still 1

    The depth is the MAXIMUM over the value's container paths, and it is computed per key and
    never once across the bag: `{"x.a.one": {"a": {"b": 1}}, "x.b.two": {"c": {"d": 2}}}` is two
    values of depth 2, not one of depth 3.
    """
    if isinstance(value, dict):
        return 1 + max((extension_depth(v) for v in value.values()), default=0)
    if isinstance(value, (list, tuple)):
        return 1 + max((extension_depth(v) for v in value), default=0)
    return 0


class EventRelation(BaseModel):
    """One typed reference from this event to another event.

    Both halves are required: a predicate with no target says nothing, and a target with no
    predicate is the association `CORRELATES_WITH` exists to spell honestly.
    """
    model_config = STRICT
    predicate: EventRelationPredicate = Field(
        description="One of the seven governed predicates. An unrecognised predicate is refused "
                    "rather than read as a nearby one."
    )
    event_id: uuid.UUID = Field(
        description="The event this relation points at. It need not be locally available — "
                    "rejecting an event because its antecedent has not arrived would make "
                    "delivery order part of the contract."
    )


class EntityRelation(BaseModel):
    """What ROLE an entity already related to this event plays in it.

    `Event.related_entities` remains the single answer to "which entities does this event
    concern"; this adds the role. The membership rule that keeps the two lists agreeing lives on
    `Event` (`models.py`), because it is the only place both lists are visible.
    """
    model_config = STRICT
    entity_id: uuid.UUID = Field(
        description="Must also appear in the event's related_entities — see Event._oes_entities."
    )
    predicate: str = Field(
        min_length=1,
        description="An absolute semantic identifier: a governed ontology term or a valid "
                    "third-party one. A bare word or a local name is refused.",
    )

    @field_validator("predicate")
    @classmethod
    def _predicate(cls, v: str) -> str:
        return validate_ontology_identifier(v)


#: Which fields each evidence kind may carry, and which one it cannot do without.
#: `description`, `media_type` and `hash` are EXTERNAL_ARTIFACT's alone, because it is the only
#: kind whose referent is outside this system and outside its sources — the only kind that has an
#: outside to describe.
EVIDENCE_FIELDS: dict[EvidenceKind, frozenset[str]] = {
    EvidenceKind.EVENT: frozenset({"event_id"}),
    EvidenceKind.SOURCE_RECORD: frozenset({"source_id"}),
    EvidenceKind.EXTERNAL_ARTIFACT: frozenset({"uri", "description", "media_type", "hash"}),
}

#: The field each kind must carry: the one that says what the reference actually points at.
EVIDENCE_ANCHOR: dict[EvidenceKind, str] = {
    EvidenceKind.EVENT: "event_id",
    EvidenceKind.SOURCE_RECORD: "source_id",
    EvidenceKind.EXTERNAL_ARTIFACT: "uri",
}

#: Every kind-specific field, in one place, so the "belongs to another kind" check cannot fall
#: out of step with the table above by enumerating the names a second time.
EVIDENCE_OPTIONAL: tuple[str, ...] = tuple(sorted(set().union(*EVIDENCE_FIELDS.values())))


class EvidenceRef(BaseModel):
    """What stands behind an assertion. Descriptive: nothing here is fetched or verified.

    One model with a declared `kind` rather than three, because `evidence[]` is a heterogeneous
    list and a discriminated union in the wire form would make a non-Python consumer negotiate a
    discriminator to read a citation. The per-kind field rules are a validator instead, so the
    published schema stays readable and the refusal names the kind and the field.
    """
    model_config = STRICT
    kind: EvidenceKind = Field(description="Which of the three kinds of reference this is.")
    event_id: uuid.UUID | None = Field(
        default=None,
        description="EVENT only. The cited event need not resolve locally, and a consumer that "
                    "cannot find it must not reject the citing event for that reason.",
    )
    source_id: SourceId | None = Field(
        default=None,
        description="SOURCE_RECORD only. The CDM's own source-identifier representation, reused "
                    "rather than re-invented — never the pair flattened into one opaque string.",
    )
    uri: str | None = Field(
        default=None, min_length=1,
        description="EXTERNAL_ARTIFACT only. Never retrieved, at validation time or any other.",
    )
    description: str | None = Field(default=None, min_length=1)
    media_type: str | None = Field(default=None, min_length=1)
    hash: str | None = Field(
        default=None, min_length=1,
        description="DESCRIPTIVE METADATA ONLY. Not an integrity guarantee, not a signature and "
                    "not evidence of authenticity; no conformance dimension asserts anything "
                    "about its value. SC-OES v0.1.0 implements no signing and no verification.",
    )

    @model_validator(mode="after")
    def _kind_shape(self) -> "EvidenceRef":
        """The declared kind decides which fields mean anything; the rest must be absent.

        Absent rather than ignored. A reference that carried a `uri` under `kind: EVENT` would
        read as an external citation to anything scanning the field and as nothing at all to
        anything switching on the kind, and the two readings would disagree silently.
        """
        allowed = EVIDENCE_FIELDS[self.kind]
        required = EVIDENCE_ANCHOR[self.kind]
        if getattr(self, required) is None:
            raise ValueError(
                f"evidence of kind {self.kind.value} requires {required}; a reference that "
                "points at nothing is not a citation"
            )
        present = {name for name in EVIDENCE_OPTIONAL if getattr(self, name) is not None}
        extra = sorted(present - allowed)
        if extra:
            raise ValueError(
                f"evidence of kind {self.kind.value} carries {extra}, which belongs to another "
                f"kind; {self.kind.value} declares {sorted(allowed)}"
            )
        return self


class SecurityMarking(BaseModel):
    """Handling markings, TRANSPORTED. SC-OES does not interpret or enforce them.

    Three propositions `10-security-markings.md` states because each is routinely assumed away:
    presence of a marking is not authorization, absence is not proof of unclassified status, and
    transport is not enforcement. SC-OES is not a cross-domain guard and must not be represented
    as one; nothing in this package could enforce a marking, and a deployment that enforces one
    does so with its own accredited mechanism, which knows the scheme and is answerable for the
    decision.

    Every value here is interpreted ONLY relative to `scheme`, which is why `scheme` is the one
    required field: two markings from different schemes are not comparable, and a classification
    with no scheme beside it is a string somebody will compare anyway.
    """
    model_config = STRICT
    scheme: str = Field(
        min_length=1, description="Which marking system these values belong to. Required."
    )
    classification: str | None = Field(
        default=None, min_length=1, description="As that scheme spells it. Transported verbatim."
    )
    releasability: list[str] = Field(
        default_factory=list, description="As that scheme spells them. Never reordered."
    )
    caveats: list[str] = Field(default_factory=list, description="As that scheme spells them.")
    originator: str | None = Field(
        default=None, min_length=1, description="As that scheme identifies them."
    )
    marking_extras: dict[str, str] = Field(
        default_factory=dict,
        description="Scheme-specific values with no generic counterpart. Strings, because "
                    "dimension B checks that marking values are strings and because the block "
                    "has exactly one generic open bag and it is oes.extensions.",
    )


class OesMetadata(BaseModel):
    """The wire-semantic block. §52's thirteen fields, and `maturity` is not among them.

    Maturity is a property of a governed semantic DEFINITION, not of an occurrence: it lives in
    the event registry, in ontology-term metadata and in profile documents. Putting it on the
    wire would duplicate registry governance metadata on every message and give it a second
    authority, which would then go stale (`12-versioning.md`).

    Three states are distinguished throughout and are not collapsed (`01-core.md`): a field
    present with a value is ASSERTED, an absent field or a null `confidence` is UNKNOWN, and a
    value whose meaning is "none" is ASSERTED-ABSENT. An unknown value is never represented as a
    zero, an empty string or a default enumeration member — which is why every optional field
    here defaults to `None` and none of the enumerations carries an UNKNOWN member the way the
    CDM's own vocabularies do (`enums.py:3`). The CDM's rule is right for a closed structural
    classification a map has to render; SC-OES's optional fields are assertions a producer either
    made or did not, and "not asserted" is exactly what absence already says.
    """
    model_config = STRICT

    spec_version: str = Field(
        description="The SC-OES version whose semantics the producer is claiming. Semver, on the "
                    "same rule CDMBase applies to schema_version; NOT derived from SCHEMA_VERSION "
                    "or PACKAGE_VERSION, and not required to equal this package's SC_OES_VERSION "
                    "— a producer at a later spec version stays transportable."
    )
    event_class: EventClass = Field(
        description="Asserted by the producer. Never inferred from type_id or from the payload."
    )
    type_id: str = Field(
        description="The governed or third-party semantic type identifier, under one of the two "
                    "frozen grammars. Syntax here; recognition is dimension C's."
    )
    status: LifecycleStatus | None = Field(
        default=None, description="None = the source says nothing about lifecycle."
    )
    verification: Verification | None = Field(
        default=None, description="None = nothing is asserted about corroboration."
    )
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="0..1 on the producer's own scale. None = unknown, never 0.0, and this "
                    "specification defines no universal confidence algorithm.",
    )
    effective_from: Timestamp | None = Field(
        default=None,
        description="When the represented condition begins. NEVER defaulted to observed_at, "
                    "received_at or the time of validation.",
    )
    effective_to: Timestamp | None = Field(
        default=None,
        description="When it ceases. None = the producer did not state an end; it does not mean "
                    "the condition is permanent and it does not mean it is still in force.",
    )
    event_relations: list[EventRelation] = Field(
        default_factory=list, description="Empty or absent asserts nothing. No universal cap."
    )
    entity_relations: list[EntityRelation] = Field(
        default_factory=list, description="Roles for entities already in related_entities."
    )
    evidence: list[EvidenceRef] = Field(
        default_factory=list, description="What stands behind the assertion. No universal cap."
    )
    security: SecurityMarking | None = Field(
        default=None,
        description="Transported markings. Absence is never a conformance failure and is never "
                    "proof of unclassified status.",
    )
    extensions: dict[str, Any] = Field(
        default_factory=dict,
        description="The one declared open bag. Keys are x.<namespace>.<name>; sc.* is reserved "
                    "and rejected in v0.1; values are preserved and never interpreted.",
    )

    @field_validator("spec_version")
    @classmethod
    def _spec_version(cls, v: str) -> str:
        """Semver, and nothing stronger.

        The conservative reading, and it is worth saying which of two it is. This could have
        required equality with the package's own `SC_OES_VERSION`, and that would refuse an event
        written against a later specification version — which `12-versioning.md` requires stay
        transportable, and which is the case the field exists to make visible. So the shape is
        checked and the value is not, on the same rule `CDMBase._semver` applies one level up.
        """
        if SEMVER_RE.fullmatch(v) is None:
            raise ValueError(
                f"spec_version must be semver MAJOR.MINOR.PATCH with no leading zeroes, got {v!r}"
            )
        return v

    @field_validator("type_id")
    @classmethod
    def _type_id(cls, v: str) -> str:
        return validate_type_id(v)

    @model_validator(mode="after")
    def _effective_interval(self) -> "OesMetadata":
        """`effective_to >= effective_from` when both exist. Nothing else about ordering.

        The only ordering rule that fails, deliberately. A source may report a condition that
        began before anybody observed it, and clock skew between a source and the canonical
        system is a fact of life — so `observed_at` after `received_at`, and `effective_from`
        before `observed_at`, are both ordinary and are both accepted. An interval that ends
        before it starts is a defect in the assertion itself.
        """
        if (self.effective_from is not None and self.effective_to is not None
                and self.effective_to < self.effective_from):
            raise ValueError(
                f"effective_to {self.effective_to.isoformat()} precedes effective_from "
                f"{self.effective_from.isoformat()} — an interval that runs backwards is a "
                "translation defect, not data"
            )
        return self

    @model_validator(mode="after")
    def _relations(self) -> "OesMetadata":
        """Duplicate identical relationships are refused; self-reference is `Event`'s to catch.

        The two halves of §80's rule live one level apart because that is where each is visible.
        A duplicate is the same predicate to the same target twice and needs only this list; a
        self-reference needs the citing event's own `event_id`, which this block does not carry.
        """
        seen: set[tuple[str, uuid.UUID]] = set()
        for relation in self.event_relations:
            key = (relation.predicate.value, relation.event_id)
            if key in seen:
                raise ValueError(
                    f"duplicate event relation {relation.predicate.value} -> {relation.event_id}: "
                    "the same predicate to the same target twice asserts nothing the first one "
                    "did not"
                )
            seen.add(key)
        return self

    @model_validator(mode="after")
    def _entity_relation_duplicates(self) -> "OesMetadata":
        """The same role to the same entity, twice, is the same defect one list over."""
        seen: set[tuple[uuid.UUID, str]] = set()
        for relation in self.entity_relations:
            key = (relation.entity_id, relation.predicate)
            if key in seen:
                raise ValueError(
                    f"duplicate entity relation {relation.predicate} -> {relation.entity_id}"
                )
            seen.add(key)
        return self

    @model_validator(mode="after")
    def _extensions(self) -> "OesMetadata":
        """Key grammar, the `sc.*` reservation, and the depth bound — per key, in that order.

        The refusal names the key, the calculated depth and the maximum accepted depth, and
        carries no stack trace and no internal implementation detail: a producer reading it has
        to be able to fix its own data from the message alone.
        """
        for key, value in self.extensions.items():
            if key.startswith(RESERVED_EXTENSION_PREFIX):
                raise ValueError(
                    f"extension key {key!r} is in the reserved sc. namespace: reserved but "
                    "undefined. No governed sc.* extension is defined in SC-OES v0.1.0, so "
                    "there is nothing for this key to mean"
                )
            if EXTENSION_KEY_RE.fullmatch(key) is None:
                raise ValueError(
                    f"extension key {key!r} does not match x.<namespace>.<name>, exactly three "
                    "dot-separated parts with each label [a-z][a-z0-9_]*. An unnamespaced key is "
                    "the one shape that cannot be attributed to anybody, and nothing is "
                    "case-folded, trimmed or otherwise repaired"
                )
            depth = extension_depth(value)
            if depth > MAX_EXTENSION_DEPTH:
                raise ValueError(
                    f"extension {key} has nesting depth {depth}; maximum permitted depth is "
                    f"{MAX_EXTENSION_DEPTH}"
                )
        return self


#: The two predicates that assert a strict ordering, and therefore the two whose cycles are
#: incoherent rather than merely unusual: one assertion replaces an earlier one, one assertion
#: was produced from an earlier one.
ACYCLIC_PREDICATES = (EventRelationPredicate.SUPERSEDES, EventRelationPredicate.DERIVED_FROM)


def find_relation_cycles(events: Iterable["Event"]) -> list[list[uuid.UUID]]:
    """`SUPERSEDES` and `DERIVED_FROM` cycles inside ONE supplied bundle, as a list of paths.

    The check is bounded by what the caller supplied and by nothing else. It does not fetch,
    query or accumulate history, and it introduces no graph database, triple store or persistent
    event graph — `08-event-relationships.md` forbids all three by name, and the plain
    depth-first walk below is what "bounded by the bundle" costs.

    Deliberately conditional, which reads at first like a weak rule and is the only honest one: a
    producer emitting a single event cannot know whether its supersession chain closes, and a
    specification demanding the global answer would either require every consumer to hold the
    whole graph or be quietly unenforced. What is enforceable is that a validator handed a bundle
    notices a cycle inside it — which catches the realistic mistake, a producer emitting a
    mutually superseding pair.

    Returns one path per cycle found, each beginning and ending at the same event id, so that a
    caller can name the cycle rather than only report that one exists. An empty list means the
    bundle is acyclic in both predicates, NOT that the wider history is.
    """
    edges: dict[uuid.UUID, set[uuid.UUID]] = {}
    for event in events:
        block = getattr(event, "oes", None)
        if block is None:
            continue
        for relation in block.event_relations:
            if relation.predicate in ACYCLIC_PREDICATES:
                edges.setdefault(event.event_id, set()).add(relation.event_id)

    cycles: list[list[uuid.UUID]] = []
    seen: set[uuid.UUID] = set()

    def walk(node: uuid.UUID, path: list[uuid.UUID], on_path: set[uuid.UUID]) -> None:
        for target in sorted(edges.get(node, ()), key=str):
            if target in on_path:
                cycles.append(path[path.index(target):] + [target])
                continue
            walk(target, path + [target], on_path | {target})

    for start in sorted(edges, key=str):
        if start in seen:
            continue
        seen.add(start)
        walk(start, [start], {start})
    return cycles


def validate_event_bundle(events: Iterable["Event"]) -> None:
    """Raise if the supplied bundle contains a detectable `SUPERSEDES`/`DERIVED_FROM` cycle.

    The imperative form of `find_relation_cycles`, for a caller whose contract is "reject". Kept
    separate from the models because a single event cannot see a bundle, and a validator that
    pretended otherwise would be asserting something about history it was never given.
    """
    cycles = find_relation_cycles(events)
    if cycles:
        drawn = "; ".join(" -> ".join(str(node) for node in cycle) for cycle in cycles)
        raise ValueError(
            f"the supplied bundle contains {len(cycles)} SUPERSEDES/DERIVED_FROM cycle(s): "
            f"{drawn}. Both predicates assert a strict ordering, so a cycle in either is "
            "incoherent rather than unusual"
        )
