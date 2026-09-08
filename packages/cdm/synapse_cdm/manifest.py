"""Adapter metadata: the declaration §3 of ARCHITECTURE.md freezes, as strict models.

WHAT THIS MODULE IS FOR
-----------------------
An adapter has always been able to say its `name`, `version`, `direction` and `system`. Those
four answer "who translated this?" and nothing else. They do not say which edition of which
standard the adapter was written against, whether that standard can be redistributed, how far
the translation has actually been verified, or what the adapter declines to do — and every one
of those is a question somebody asks BEFORE deciding to depend on an adapter, not after.

So `Adapter.metadata` is required at class definition (`adapter.py`), the same enforcement point
`name` and `version` already use, and `manifests.py` publishes a projection of it per adapter.
The models here are the authority; the files under `manifests/` are a publication of them, in
exactly the sense `schemas.py` argues for the JSON Schemas.

WHY THE MODELS ARE STRICT
-------------------------
`extra="forbid"` throughout. A metadata block that accepts unknown keys silently swallows a
misspelling — `licence_class` for `license_class`, `maturity_level` for `maturity` — and the
adapter then publishes a manifest missing the field a consumer filters on, with every gate green.
The whole point of the declaration is that it is checkable, and a checkable declaration cannot
have a slot that means "whatever you like".

WHAT IS *NOT* HERE, AND WHERE IT IS INSTEAD
-------------------------------------------
The obligations that need the CLASS — that `adapter_version` equals the class's `version`, that
`id` equals its `name`, that a declared direction matches which of `to_cdm`/`from_cdm` the class
overrides — are enforced in `adapter.__init_subclass__`, beside the checks that were already
there. They are not duplicated here: two enforcement points for one rule is two chances to
disagree, and `adapter.py:96`'s docstring says the enforcement point must not move.

THE SIX DIRECTIONS, AND WHY ONLY THREE OF THEM CAN BE A CLASS ATTRIBUTE IN PART 1
---------------------------------------------------------------------------------
`Direction` below has the six values ARCHITECTURE.md §2 freezes. `adapter.Direction` still has
the three it has always had, unchanged — the v1 literals are the wire and code spellings of the
first three rows and nothing in Part 1 removes or widens them. So `MODEL`, `TRANSPORT` and
`COMPOSITE` are a vocabulary the manifest schema publishes and the validators below enforce the
obligations of, and an adapter class in this repository cannot yet declare one: `metadata.
direction` must equal the class's own `direction`, which `adapter.py` still restricts to three.
That is stated rather than papered over, because a six-value enum whose extra three are
unreachable would otherwise read as an oversight.
"""
from __future__ import annotations

import enum
import re

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

#: Semver, and nothing looser. An `adapter_version` of "1.0" or "v1.0.0" is a version string a
#: consumer's comparison silently mis-sorts, which is worse than one it refuses.
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class Strict(BaseModel):
    """Every model here forbids unknown keys. See the module docstring for why."""

    model_config = ConfigDict(extra="forbid")


class Direction(str, enum.Enum):
    """ARCHITECTURE.md §2's six, in the lower-case wire spellings that document freezes."""

    INGEST = "ingest"
    EGRESS = "egress"
    BIDIRECTIONAL = "bidirectional"
    MODEL = "model"
    TRANSPORT = "transport"
    COMPOSITE = "composite"


class LicenseClass(str, enum.Enum):
    """§3.2's five. A statement about the SOURCE STANDARD's terms, never about this repository's."""

    OPEN = "OPEN"
    PUBLIC_GOVERNMENT = "PUBLIC_GOVERNMENT"
    LICENSED = "LICENSED"
    CONTROLLED = "CONTROLLED"
    PROPRIETARY_PLUGIN = "PROPRIETARY_PLUGIN"


class MaturityLevel(str, enum.Enum):
    """§3.3's seven rungs. L6 is not awardable from this repository's own evidence (§3.3)."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"
    L6 = "L6"


class ClaimStatus(str, enum.Enum):
    """§3.4's six. A SEPARATE axis from maturity and never derived from it."""

    DOCUMENTED = "DOCUMENTED"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED = "VERIFIED"
    EXERCISED = "EXERCISED"
    INTEGRATED = "INTEGRATED"
    DEPLOYED = "DEPLOYED"


class Residual(str, enum.Enum):
    """ARCHITECTURE.md §5: the fourteen keep `legacy` parking through Part 1."""

    LEGACY = "legacy"
    STRUCTURED = "structured"


class UnknownFields(str, enum.Enum):
    """Does this adapter preserve a source field it does not recognise, in its DOCUMENT form?

    Two values and no third, because the conformance suite's check I needs an answer it can act
    on rather than a description it has to interpret. The question is asked of the DOCUMENT form
    the adapter accepts — the dict a caller hands `to_cdm` — and not of every carrier the wire
    format has: `stanag4609` preserves unknown KLV local-set TAGS on the wire
    (`attributes.klv_unknown_items`, `stanag4609.py:1575`) and has no carrier for an unknown key
    in the decoded twin, and those are two true facts that one enum value cannot hold. The
    accompanying `unknown_fields_basis` is where the distinction is stated, in the adapter's own
    words, which is the same arrangement `Limits.absent_because` uses for a bound that does not
    apply.
    """

    PRESERVED = "preserved"
    NONE = "none"


class FormatRef(Strict):
    """The source standard this adapter is written against.

    `version` is `None` when NO document in this tree states which edition the adapter targets.
    That is a reading and not a gap to be filled in: an invented edition number is a claim about
    a publisher's document, and a consumer checking compatibility against it would be checking
    against a guess. A `None` here MUST be accompanied by a limitation saying so, which
    `AdapterMetadata` enforces below.
    """

    name: str
    version: str | None

    @field_validator("name")
    @classmethod
    def _named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("format.name is empty — the source standard has a name or the "
                             "adapter does not know what it is translating")
        return value


#: The five bounds ARCHITECTURE.md §3.5 tabulates, which are §40's five.
LIMIT_FIELDS = ("max_input_bytes", "max_depth", "max_objects",
                "max_decompressed_bytes", "max_parse_seconds")


class LimitKind(str, enum.Enum):
    """Where a declared bound's NUMBER came from — M's F5.4 ruling, 2026-09-07, round P5.

    The ruling's own words are the reason two values are not one: a limit "must NOT be described
    as the format's normative maximum unless the specification actually says so". A consumer
    reading `max_input_bytes: 65535` cannot tell whether it is a fact about ASTERIX or a choice
    this repository made, and the two behave differently — a normative bound is the same in every
    implementation, an implementation cap is ours and may be raised.
    """

    NORMATIVE = "normative"
    IMPLEMENTATION_CAP = "implementation_cap"


class LimitBasis(Strict):
    """The four things F5.4 requires an adapter to record beside a bound it DECLARES.

    "Each adapter records: selected limit; source/rationale; normative vs implementation cap;
    enforcement point; oversized-input test." The selected limit is the field on `Limits`; the
    other four are here, keyed to the field by `Limits.declared_because` — the mirror image of
    `absent_because`, which carries the same weight for a bound that is NOT declared.
    """

    #: Normative maximum, or a cap this repository chose. Never inferred from the number.
    kind: LimitKind
    #: The document or module that states the figure, with the clause or line. Prose, because a
    #: citation is read by a person deciding whether to trust the bound.
    source: str
    #: Where the bound BITES. One place for all fourteen today, and named per adapter anyway: a
    #: declaration that pointed at nothing would be the failure this field exists to make visible.
    enforced_at: str
    #: The test that feeds one octet more than the bound and asserts the refusal.
    test: str

    @field_validator("source", "enforced_at", "test")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a LimitBasis states its source, its enforcement point and its "
                             "oversized-input test; an empty one declares a bound nobody can "
                             "check and nobody can trace")
        return value


class Limits(Strict):
    """§3.5's five bounds, the reason for each one that does not apply, and the basis of each
    one that does.

    "A limit that does not apply to a format MUST be declared absent with a reason, not silently
    omitted" — §3.5. So `None` is legal and bare `None` is not: `absent_because` has to carry the
    reason, keyed by the field. "This format does not nest" is a fact about the format, and a
    reader who cannot find it has to go and work it out again.

    `declared_because` is the same rule pointed the other way, added by round P5 under M's F5.4:
    a bound that IS declared carries where its number came from, what kind of bound it is, where
    it is enforced and which test proves the refusal. A number on its own is exactly as opaque as
    a `None` on its own, and the round that introduced real bounds is the round where that stopped
    being hypothetical.
    """

    max_input_bytes: int | None
    max_depth: int | None
    max_objects: int | None
    max_decompressed_bytes: int | None
    max_parse_seconds: float | None
    absent_because: dict[str, str]
    declared_because: dict[str, LimitBasis] = {}

    @model_validator(mode="after")
    def _every_absent_limit_has_a_reason(self) -> "Limits":
        missing = [name for name in LIMIT_FIELDS
                   if getattr(self, name) is None and not self.absent_because.get(name, "").strip()]
        if missing:
            raise ValueError(
                f"these limits are absent with no reason: {missing}. §3.5 requires a limit that "
                "does not apply to be declared absent WITH a reason — silence reads as an "
                "oversight and a reason reads as a fact about the format"
            )
        stray = sorted(set(self.absent_because) - set(LIMIT_FIELDS))
        if stray:
            raise ValueError(f"absent_because names {stray}, which are not limits. The five are "
                             f"{list(LIMIT_FIELDS)}")
        contradicted = sorted(name for name in LIMIT_FIELDS
                              if getattr(self, name) is not None and name in self.absent_because)
        if contradicted:
            raise ValueError(
                f"these limits are both declared and explained as absent: {contradicted}. One of "
                "the two is wrong and a reader cannot tell which"
            )
        unbased = [name for name in LIMIT_FIELDS
                   if getattr(self, name) is not None and name not in self.declared_because]
        if unbased:
            raise ValueError(
                f"these limits are declared with no basis: {unbased}. M's F5.4 ruling (round P5) "
                "requires a declared bound to record its source, whether it is the format's "
                "normative maximum or an implementation cap, where it is enforced and which test "
                "proves the refusal — a bare number is a bound a reader cannot audit"
            )
        astray = sorted(set(self.declared_because) - set(LIMIT_FIELDS))
        if astray:
            raise ValueError(f"declared_because names {astray}, which are not limits. The five "
                             f"are {list(LIMIT_FIELDS)}")
        phantom = sorted(name for name in LIMIT_FIELDS
                         if getattr(self, name) is None and name in self.declared_because)
        if phantom:
            raise ValueError(
                f"these limits are absent and carry a basis anyway: {phantom}. A basis describes "
                "where a NUMBER came from, and there is no number here — the reason belongs in "
                "absent_because"
            )
        return self


class Capabilities(Strict):
    """§3.5's machine-readable block. `limits` lives HERE and not beside it, deliberately.

    The reason is §3.5's own: the conformance suite's resource-limits check and the parser-safety
    policy must read ONE declaration, and two declarations of one bound is the arrangement where a
    parser is hardened against a number the report does not print.
    """

    wire: bool
    directions_exercised: list[str]
    message_types: list[str]
    limits: Limits
    #: Check I's declaration (P2). It is READ and never inferred: a probe that injects an unknown
    #: field and finds nothing in the output has found either a format with no carrier for one or
    #: an adapter that drops what it carries, and those are opposite verdicts about the same
    #: evidence. Only the adapter can say which.
    unknown_fields: UnknownFields
    #: Why, in the adapter's own words. Required for BOTH values, not just `none`: "preserved"
    #: without a basis is a claim nobody has to justify, and this model's whole habit is that a
    #: declaration carries its reason (§3.5, `Limits.absent_because`).
    unknown_fields_basis: str

    @field_validator("unknown_fields_basis")
    @classmethod
    def _the_declaration_carries_its_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("unknown_fields_basis is empty. Whether unknown source fields "
                             "survive is a fact about the format AND about this adapter, and a "
                             "bare enum value leaves a reader unable to tell which one they are "
                             "being told")
        return value

    @field_validator("directions_exercised")
    @classmethod
    def _only_the_two_that_move_bytes(cls, value: list[str]) -> list[str]:
        stray = sorted(set(value) - {"ingest", "egress"})
        if stray:
            raise ValueError(f"directions_exercised may only name 'ingest' and 'egress'; got "
                             f"{stray}. `bidirectional` is BOTH of them and is spelled as both")
        return value


class Limitation(Strict):
    """A limitation stated so that a MACHINE can act on it — M's ruling, 2026-09-08, round P4.

    WHY THIS EXISTS BESIDE THE SENTENCE AND DOES NOT REPLACE IT
    -----------------------------------------------------------
    `limitations` has always been `list[str]`, and a sentence is the right shape for most of what
    an adapter has to admit: "no document in this tree states which edition this targets" is prose
    and stays prose. §34 asks for one thing a sentence cannot give. The loss report classifies a
    source path as UNSUPPORTED when it is "an explicit documented exception", and a classifier
    that had to decide that by reading English would be a classifier that guessed. So the
    exception becomes data: `unsupported_paths` holds the SOURCE paths, in the dotted spelling
    `lossless.leaves()` produces, and the classifier does a set membership test.

    `limitations` is therefore `list[str | Limitation]` and not `list[Limitation]`. The union is
    the whole ruling: existing string entries stay valid unchanged, all fourteen shipped adapters
    keep the sentences they already declare, and only an adapter that needs the mechanism emits
    the structured form. A field that FORCED the structure would have converted twenty-eight
    prose statements into objects with an empty `unsupported_paths`, which is a schema migration
    performed to satisfy a shape rather than to say anything.

    `severity` is optional and its vocabulary is NOT frozen here: ARCHITECTURE.md defines no
    severity scale for limitations and inventing one in a model would be freezing a contract in
    the wrong document. It is a free string when it is given at all.
    """

    #: Stable within one adapter, so a consumer can track one limitation across releases. Not
    #: globally unique and not a registry key — two adapters may both call one `format-version`.
    id: str
    #: The sentence a `str` entry would have been. The structured form does not get to be less
    #: readable than the shape it replaces.
    summary: str
    #: SOURCE paths, dotted, in `lossless.leaves()`'s spelling. The one field a classifier reads.
    unsupported_paths: list[str] = []
    #: Free text. Optional, and unfrozen — see the docstring.
    severity: str | None = None
    #: Why, where the summary is not the whole answer.
    notes: str | None = None

    @field_validator("id", "summary")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a Limitation's `id` and `summary` are both required and non-empty; "
                             "a structured limitation with no summary is less legible than the "
                             "sentence it replaced")
        return value

    @field_validator("unsupported_paths")
    @classmethod
    def _paths_are_paths(cls, value: list[str]) -> list[str]:
        """§34, and M's ruling: "must be machine-readable and contain canonical source/CDM paths,
        not prose descriptions". A path with a space in it is a sentence that got into the wrong
        field, and the loss classifier would silently never match it."""
        prose = sorted(p for p in value if not p.strip() or " " in p.strip())
        if prose:
            raise ValueError(
                f"unsupported_paths holds {prose}, which are prose and not paths. This field is "
                "read by `lossless.classify` as a set of dotted SOURCE paths "
                "(`vendor.firmware`, `items[0].code`); a description here classifies nothing"
            )
        return value


def limitation_text(entry: "str | Limitation") -> str:
    """The prose of a limitation, whichever of the two shapes it arrived in.

    Written once, because four validators below and `AdapterMetadata` read a limitation AS PROSE
    (the blank check, the format-version-is-null check) and four places each unpacking a union is
    four places one of them gets wrong.
    """
    return entry if isinstance(entry, str) else entry.summary


def unsupported_paths(limitations: "list[str | Limitation]") -> tuple[str, ...]:
    """Every source path any structured limitation declares unsupported, sorted and deduplicated.

    `lossless.classify` reads this and nothing else for its UNSUPPORTED category. A string entry
    contributes nothing — deliberately: a sentence is not an exception a classifier may act on,
    which is the entire reason the structured form exists.
    """
    paths = {path for entry in limitations if isinstance(entry, Limitation)
             for path in entry.unsupported_paths}
    return tuple(sorted(paths))


class ExternalExercise(Strict):
    """What L6 requires, and what this repository cannot produce for its own adapters (§3.3)."""

    system: str
    date: str
    record: str


class Maturity(Strict):
    """A rung and the evidence it rests on.

    `basis` is required and is prose, because the rung is a CLAIM ABOUT EVIDENCE (§3.6) and a
    rung with no statement of what verified it is the thing the eligibility algorithm exists to
    stop being typed.
    """

    level: MaturityLevel
    basis: str
    external_exercise: ExternalExercise | None

    @model_validator(mode="after")
    def _l6_names_the_independent_system(self) -> "Maturity":
        if self.level is MaturityLevel.L6 and self.external_exercise is None:
            raise ValueError(
                "maturity L6 with no `external_exercise`. §3.3: L6 is EXTERNALLY EXERCISED and "
                "MUST NOT be awarded solely by Decent Cybersecurity using synthetic fixtures, so "
                "the rung names the system, the date and the record or it is not that rung"
            )
        if self.level is not MaturityLevel.L6 and self.external_exercise is not None:
            raise ValueError(
                f"maturity {self.level.value} carries an `external_exercise`, which only L6 "
                "means. An exercise record on a lower rung reads as a claim the level denies"
            )
        if not self.basis.strip():
            raise ValueError("maturity.basis is empty — a rung is a claim about evidence (§3.6) "
                             "and this one names none")
        return self


class Evidence(Strict):
    """§13's `evidence.available`. P4 is what makes it mean a generated record."""

    available: bool


class AdapterMetadata(Strict):
    """§3.1's fields, with §16's impossible combinations refused by construction.

    The field names are the specification's (§8) rather than ARCHITECTURE.md §3.1's table
    headings, which spell two of them `licence_class` and `claim`. §3.1's own opening clause is
    what permits it — ":142, Every adapter SHALL expose metadata EQUIVALENT to the following" —
    so the table fixes the SEMANTICS and not a spelling, and the specification's spelling is the
    one a manifest consumer reading §8 will look for.
    """

    id: str
    name: str
    adapter_version: str
    format: FormatRef
    direction: Direction
    license_class: LicenseClass
    maturity: Maturity
    claim_status: ClaimStatus
    claim_external_system: str | None
    profiles: list[str]
    capabilities: Capabilities
    limitations: list[str | Limitation]
    limitations_empty_reason: str | None
    residual: Residual
    payload_adapter: str | None
    constituents: list[str]
    evidence: Evidence

    @field_validator("adapter_version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not _SEMVER.match(value):
            raise ValueError(f"adapter_version {value!r} is not `major.minor.patch`. A version a "
                             "consumer cannot order is not a version")
        return value

    @model_validator(mode="after")
    def _the_combinations_sixteen_calls_impossible(self) -> "AdapterMetadata":
        # §16, "required limitation field missing". §3.1: `limitations` "is required and MUST NOT
        # be defaulted to empty … an adapter declaring none is an adapter nobody has audited".
        # An empty list is therefore admissible only as a stated finding.
        if not self.limitations and not (self.limitations_empty_reason or "").strip():
            raise ValueError(
                "limitations is empty and no reason is given. §3.1 forbids defaulting it to "
                "empty; an adapter that genuinely has none has to SAY that it was audited and "
                "none were found, which is a different statement from silence"
            )
        if self.limitations and self.limitations_empty_reason:
            raise ValueError("limitations_empty_reason is set on an adapter that declares "
                             "limitations — the reason explains an empty list and this one is not")
        if any(not limitation_text(line).strip() for line in self.limitations):
            raise ValueError("a limitation is blank; a limitation is a sentence or it is nothing")

        # §15: the two statuses that are about the world rather than about this repository's gates.
        if self.claim_status in (ClaimStatus.INTEGRATED, ClaimStatus.DEPLOYED) and \
                not (self.claim_external_system or "").strip():
            raise ValueError(
                f"claim_status {self.claim_status.value} with no `claim_external_system`. §15: "
                "it MUST NOT be claimed unless integration with the NAMED external system has "
                "actually occurred, and the name of that system is part of the claim"
            )
        if self.claim_external_system and self.claim_status not in (
                ClaimStatus.EXERCISED, ClaimStatus.INTEGRATED, ClaimStatus.DEPLOYED):
            raise ValueError(
                f"claim_status {self.claim_status.value} names an external system. Naming one on "
                "a status that is about this repository's own gates reads as a claim about the "
                "world that the status does not make"
            )

        # §16, "impossible direction declared" — the three values whose obligations §2 states.
        if self.direction is Direction.MODEL and self.capabilities.wire:
            raise ValueError(
                "direction MODEL with capabilities.wire true. §2: a MODEL adapter MUST declare "
                "`capabilities.wire: false` — it is a semantic representation and has no bytes "
                "to sniff"
            )
        if self.direction is Direction.TRANSPORT and not (self.payload_adapter or "").strip():
            raise ValueError(
                "direction TRANSPORT names no payload adapter. §2: a TRANSPORT adapter MUST name, "
                "in its metadata, the payload adapter whose semantics it carries; one that "
                "defines its own has misdeclared its direction"
            )
        if self.direction is Direction.COMPOSITE and not self.constituents:
            raise ValueError(
                "direction COMPOSITE names no constituents. §2: a COMPOSITE that names no "
                "constituent is an INGEST adapter with a grander word on it"
            )
        if self.payload_adapter and self.direction is not Direction.TRANSPORT:
            raise ValueError(f"direction {self.direction.value} names a payload adapter, which "
                             "only TRANSPORT delegates to")
        if self.constituents and self.direction is not Direction.COMPOSITE:
            raise ValueError(f"direction {self.direction.value} names constituents, which only "
                             "COMPOSITE composes")

        # The declared direction and the directions the capability block says are exercised are
        # two statements of one fact, so they are compared rather than left to agree by habit.
        exercised = set(self.capabilities.directions_exercised)
        expected = {
            Direction.INGEST: {"ingest"},
            Direction.EGRESS: {"egress"},
            Direction.BIDIRECTIONAL: {"ingest", "egress"},
        }.get(self.direction)
        if expected is not None and exercised != expected:
            raise ValueError(
                f"direction {self.direction.value} and capabilities.directions_exercised "
                f"{sorted(exercised)} disagree; {self.direction.value} means {sorted(expected)}"
            )

        # A format version nobody can read from a document is `None` WITH a limitation saying so,
        # never a guess. This is the half of that rule a model can enforce.
        if self.format.version is None and not any(
                "format version" in limitation_text(line).lower()
                or "edition" in limitation_text(line).lower()
                for line in self.limitations):
            raise ValueError(
                "format.version is null and no limitation says so. A null edition is a reading — "
                "no document in this tree states which edition the adapter targets — and a "
                "reading a consumer cannot find is indistinguishable from a field somebody forgot"
            )
        return self


class ApiRef(Strict):
    """`api.version` is the ADAPTER API major, and §1.2 says what it does NOT mean.

    "A manifest's `api.version: "2"` therefore means 'this adapter declares metadata and honours
    the v2 contract'. It does NOT mean 'this adapter uses the new method names', and a gate MUST
    NOT infer the second from the first."
    """

    version: str


class CdmRef(Strict):
    """Which CDM a consumer of this manifest is being told the adapter emits."""

    supported: str
    schema_version: str


class AdapterManifest(Strict):
    """The published document: §13's semantics in this repository's canonical JSON (F1.3).

    The envelope is separate from `AdapterMetadata` because the two are different facts. The
    metadata is what the ADAPTER declares and is inspectable from the class; the envelope is what
    the PUBLICATION declares — which manifest schema it was written to, which Adapter API it
    claims, which CDM it emits — and none of those belong to one adapter.
    """

    schema_id: str
    manifest_schema_version: str
    api: ApiRef
    cdm: CdmRef
    adapter: AdapterMetadata
