"""The policy seam: what is decided, by whom, on what, and how a decision is carried to a read.

Seven artefacts are approved independently (metadata, original octets, pixels, thumbnails,
tiles, text and exports); a decision for one never implies a decision for another. An engine sees
a `SecurityDescriptor`, which holds the adapter's own label records and assessment verbatim plus
the identifiers of the container's extensions, never the octets: the host computes no label, no
status and no reason itself, so there is one security predicate, the adapter's.

`DefaultPolicy` is a floor, not an access-control engine: it admits material the adapter assesses
as declared unclassified, with nothing it cannot identify, and refuses everything else. A
`PolicyTicket` carries one approval of one artefact on one asset for one tenant, lives in memory
only, and is checked again at every release point, so revocation takes effect on the next read.
`LabelLattice` is the interface a label combination would go through; the shipped implementation
returns only identical labels and refuses every other combination, so it can never downgrade.
"""

from __future__ import annotations

import copy
import enum
import hashlib
import json
import re
import secrets
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from synapse_imagery.result import HostError, PolicyDenied


class Artefact(str, enum.Enum):
    METADATA = "metadata"
    ORIGINAL = "original"
    PIXELS = "pixels"
    THUMBNAIL = "thumbnail"
    TILE = "tile"
    TEXT = "text"
    EXPORT = "export"


def _printable(value: str) -> bool:
    return all(0x20 <= ord(character) <= 0x7E for character in value)


@dataclass(frozen=True, slots=True)
class Principal:
    """Who asks: a tenant and a subject, each 1-128 printable ASCII characters, not all spaces,
    without `|` (the separator of every identifier the host derives from them)."""

    tenant: str
    subject: str

    def __post_init__(self) -> None:
        for name in ("tenant", "subject"):
            value = getattr(self, name)
            if type(value) is not str:
                raise TypeError(f"{name} must be a str")
            if not 1 <= len(value) <= 128 or not _printable(value):
                raise ValueError(f"{name} must be 1-128 printable ASCII characters")
            if not value.strip(" ") or "|" in value:
                raise ValueError(f"{name} must not be all spaces or contain '|'")


# --------------------------------------------------------------------------- the descriptor

_LABEL_KEYS = ["scope", "index", "offset", "length", "fields", "uninterpreted"]
_LABEL_FIELDS = [
    "CLAS",
    "CLSY",
    "CODE",
    "CTLH",
    "REL",
    "DCTP",
    "DCDT",
    "DCXM",
    "DG",
    "DGDT",
    "CLTX",
    "CAPT",
    "CAUT",
    "CRSN",
    "SRDT",
    "CTLN",
]
_SCOPES = ("file", "image", "graphic", "text", "des", "res")
_ASSESSMENT_KEYS = [
    "status",
    "reasons",
    "scopes",
    "clas_values",
    "uniform_clas",
    "unknown_extensions",
    "combination",
    "kind",
]
_DESCRIPTOR_KEYS = ["labels", "assessment", "extensions", "registry_version"]


def _compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _is_int(value: object) -> bool:
    return type(value) is int


def _label_shape(label: object) -> bool:
    if type(label) is not dict or list(label) != _LABEL_KEYS:
        return False
    scope, index = label["scope"], label["index"]
    if scope not in _SCOPES:
        return False
    if scope == "file":
        if index is not None:
            return False
    elif not _is_int(index) or index < 0:
        return False
    if not _is_int(label["offset"]) or label["offset"] < 0 or label["length"] != 167:
        return False
    fields = label["fields"]
    if type(fields) is not dict or list(fields) != _LABEL_FIELDS:
        return False
    if any(value is not None and type(value) is not str for value in fields.values()):
        return False
    missing = [name for name in _LABEL_FIELDS if fields[name] is None]
    return label["uninterpreted"] == missing


def _assessment_shape(assessment: object) -> bool:
    if type(assessment) is not dict or list(assessment) != _ASSESSMENT_KEYS:
        return False
    counts = assessment["unknown_extensions"]
    return (
        type(assessment["status"]) is str
        and type(assessment["reasons"]) is list
        and all(type(reason) is str for reason in assessment["reasons"])
        and _is_int(assessment["scopes"])
        and type(assessment["clas_values"]) is list
        and all(type(value) is str for value in assessment["clas_values"])
        and type(assessment["uniform_clas"]) is bool
        and type(counts) is dict
        and list(counts) == ["tre", "des", "res"]
        and all(_is_int(count) and count >= 0 for count in counts.values())
        and type(assessment["combination"]) is str
        and type(assessment["kind"]) is str
    )


def _descriptor_shape(text: object) -> bool:
    if type(text) is not str:
        return False
    try:
        document = json.loads(text)
    except ValueError:
        return False
    if type(document) is not dict or list(document) != _DESCRIPTOR_KEYS:
        return False
    labels = document["labels"]
    extensions = document["extensions"]
    version = document["registry_version"]
    return (
        type(labels) is list
        and len(labels) >= 1
        and all(_label_shape(label) for label in labels)
        and _assessment_shape(document["assessment"])
        and type(extensions) is list
        and all(
            type(pair) is list
            and len(pair) == 2
            and pair[0] in ("tre", "des", "res")
            and (pair[1] is None or type(pair[1]) is str)
            for pair in extensions
        )
        and type(version) is str
        and len(version) >= 1
        and _printable(version)
        # The canonical text only: two descriptors of the same facts are equal as strings.
        and _compact(document) == text
    )


@dataclass(frozen=True, slots=True)
class SecurityDescriptor:
    """One asset's security facts as the adapter states them, in one immutable compact JSON text:
    `{"labels", "assessment", "extensions", "registry_version"}`. Equal facts give equal text,
    so equality and hashing are by the text; `repr` shows a digest prefix and no label value."""

    json_text: str

    def __post_init__(self) -> None:
        if not _descriptor_shape(self.json_text):
            raise HostError(
                "E_INTERNAL",
                "security",
                None,
                "/descriptor",
                "the security descriptor is not in its canonical shape",
            )

    @classmethod
    def from_container(cls, container, registry: ExtensionRegistry) -> SecurityDescriptor:
        """Built from a parsed container with the adapter's own two functions (in the worker)."""
        from synapse_cdm.adapters.stanag4545 import assess_security, security_labels

        if not isinstance(registry, ExtensionRegistry):
            raise TypeError("registry must be an ExtensionRegistry")
        extensions = [["tre", extension.tag] for extension in container.extensions]
        extensions += [["des", _identifier_text(record.desid)] for record in container.des]
        extensions += [["res", _identifier_text(record.resid)] for record in container.res]
        document = {
            "labels": security_labels(container),
            "assessment": assess_security(container),
            "extensions": extensions,
            "registry_version": registry.version,
        }
        return cls(_compact(document))

    @classmethod
    def from_json(cls, text: str) -> SecurityDescriptor:
        """Re-read from a worker answer or the store; the shape is checked again."""
        return cls(text)

    @property
    def labels(self) -> list[dict]:
        return json.loads(self.json_text)["labels"]

    @property
    def assessment(self) -> dict:
        return json.loads(self.json_text)["assessment"]

    @property
    def extensions(self) -> list[list]:
        return json.loads(self.json_text)["extensions"]

    @property
    def registry_version(self) -> str:
        return json.loads(self.json_text)["registry_version"]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.json_text.encode("ascii")).hexdigest()

    def __repr__(self) -> str:
        return f"SecurityDescriptor({self.sha256[:12]})"

    __str__ = __repr__


def _identifier_text(value: str) -> str | None:
    text = value.rstrip(" ")
    return text if _printable(text) else None


# --------------------------------------------------------------------------- requests, decisions

_REASON = re.compile(r"[A-Z][A-Z0-9_]{1,63}")


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    principal: Principal
    artefact: Artefact
    descriptor: SecurityDescriptor
    synthetic: bool
    record_id: str | None
    asset_id: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.principal, Principal):
            raise TypeError("principal must be a Principal")
        if not isinstance(self.artefact, Artefact):
            raise TypeError("artefact must be an Artefact")
        if not isinstance(self.descriptor, SecurityDescriptor):
            raise TypeError("descriptor must be a SecurityDescriptor")
        if type(self.synthetic) is not bool:
            raise TypeError("synthetic must be a bool")
        for name in ("record_id", "asset_id"):
            value = getattr(self, name)
            if value is not None and type(value) is not str:
                raise TypeError(f"{name} must be None or a str")


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str
    policy_id: str
    policy_version: str
    completeness: str

    def __post_init__(self) -> None:
        if type(self.allowed) is not bool:
            raise TypeError("allowed must be a bool")
        if type(self.reason) is not str or not _REASON.fullmatch(self.reason):
            raise ValueError("reason must be an upper-case token")
        for name in ("policy_id", "policy_version"):
            value = getattr(self, name)
            if type(value) is not str or not value or not _printable(value):
                raise ValueError(f"{name} must be a non-empty printable ASCII str")
        if self.completeness not in ("complete", "incomplete"):
            raise ValueError("completeness must be complete or incomplete")
        if self.allowed and self.completeness == "incomplete":
            # An assessment that could not be completed blocks release: no engine may allow it.
            raise ValueError("an incomplete assessment cannot be allowed")


class PolicyEngine(Protocol):
    """Pure and deterministic: no I/O, no clock, no randomness; equal requests, equal decisions."""

    policy_id: str
    policy_version: str

    def decide(self, request: PolicyRequest) -> PolicyDecision: ...


def decide(engine: PolicyEngine, request: PolicyRequest) -> PolicyDecision:
    """Ask an engine, failing closed on anything that is not a decision."""
    decision = engine.decide(request)
    if not isinstance(decision, PolicyDecision):
        raise HostError(
            "E_INTERNAL", "security", None, "/policy", "the policy engine gave no decision"
        )
    return decision


# --------------------------------------------------------------------------- the registry


@dataclass(frozen=True, slots=True)
class ExtensionRegistry:
    """The versioned list of (kind, identifier) extensions a deployment has identified as
    security-neutral. The shipped registry is empty: nothing is identified."""

    version: str
    security_neutral: frozenset

    def __post_init__(self) -> None:
        if type(self.version) is not str or not 1 <= len(self.version) <= 64:
            raise ValueError("a registry version is 1-64 printable ASCII characters")
        if not _printable(self.version):
            raise ValueError("a registry version is 1-64 printable ASCII characters")
        if type(self.security_neutral) is not frozenset:
            raise TypeError("security_neutral must be a frozenset of (kind, identifier)")
        for entry in self.security_neutral:
            if type(entry) is not tuple or len(entry) != 2 or entry[0] not in ("tre", "des", "res"):
                raise ValueError("a registry entry is (kind, identifier) with kind tre, des or res")
            identifier = entry[1]
            if type(identifier) is not str or not 1 <= len(identifier) <= 25:
                raise ValueError("a registry identifier is 1-25 printable ASCII characters")
            if not _printable(identifier):
                raise ValueError("a registry identifier is 1-25 printable ASCII characters")

    def wire(self) -> dict:
        return {
            "version": self.version,
            "security_neutral": sorted(map(list, self.security_neutral)),
        }


EMPTY_REGISTRY = ExtensionRegistry(version="sc4545-core-1-empty", security_neutral=frozenset())


def unidentified(descriptor: SecurityDescriptor, registry: ExtensionRegistry) -> int:
    """How many of the descriptor's extensions the registry does not identify as neutral."""
    return sum(
        1
        for kind, identifier in descriptor.extensions
        if identifier is None or (kind, identifier) not in registry.security_neutral
    )


def completeness(descriptor: SecurityDescriptor, registry: ExtensionRegistry) -> str:
    return "complete" if unidentified(descriptor, registry) == 0 else "incomplete"


# --------------------------------------------------------------------------- the default gate


class DefaultPolicy:
    """Admits an artefact only when the adapter's assessment is well formed, declared
    unclassified with no reason, consistent with its own labels, and complete under the registry.
    It reads the assessment and recomputes nothing; it compares no security date with any clock;
    principal, subject and the synthetic flag do not change its answer."""

    policy_id = "sc-imagery-default-clean-u"
    policy_version = "1"

    def __init__(self, registry: ExtensionRegistry = EMPTY_REGISTRY) -> None:
        if not isinstance(registry, ExtensionRegistry):
            raise TypeError("registry must be an ExtensionRegistry")
        self.registry = registry

    def decide(self, request: PolicyRequest) -> PolicyDecision:
        descriptor = request.descriptor
        assessment = descriptor.assessment
        labels = descriptor.labels
        state = completeness(descriptor, self.registry)
        if (
            list(assessment) != _ASSESSMENT_KEYS
            or assessment["kind"] != "core_assessment"
            or assessment["combination"] != "not_performed"
        ):
            reason = "ASSESSMENT_MALFORMED"
        elif assessment["status"] != "declared_unclassified" or assessment["reasons"] != []:
            reason = "STATUS_NOT_DECLARED_UNCLASSIFIED"
        elif (
            assessment["clas_values"] != ["U"]
            or assessment["uniform_clas"] is not True
            or assessment["unknown_extensions"] != {"tre": 0, "des": 0, "res": 0}
            or not assessment["scopes"] == len(labels) >= 1
        ):
            reason = "ASSESSMENT_INCONSISTENT"
        elif state != "complete":
            reason = "ASSESSMENT_INCOMPLETE"
        else:
            return PolicyDecision(
                True, "ADMITTED_DECLARED_UNCLASSIFIED", self.policy_id, self.policy_version, state
            )
        return PolicyDecision(False, reason, self.policy_id, self.policy_version, state)


# --------------------------------------------------------------------------- tickets


@dataclass(frozen=True, slots=True)
class PolicyTicket:
    """One approval of one artefact on one asset for one tenant. The id never reaches a repr or
    a log; the issuing authority travels with the ticket so that a store can check it without
    holding the authority itself."""

    ticket_id: str = field(repr=False)
    tenant: str
    subject: str
    artefact: Artefact
    asset_id: str
    record_id: str | None
    policy_id: str
    policy_version: str
    epoch: int
    _authority: TicketAuthority = field(repr=False, compare=False)

    def verify(self, *, artefact: Artefact, asset_id: str, tenant: str) -> None:
        self._authority.check(self, artefact=artefact, asset_id=asset_id, tenant=tenant)


class TicketAuthority:
    """Issues and checks tickets in memory, in one process; nothing is persisted, so a crash
    resurrects no authority. Thread-safe."""

    def __init__(self, policy: PolicyEngine) -> None:
        self._policy = policy
        self._lock = threading.Lock()
        self._epoch = 0
        self._outstanding: dict[str, PolicyTicket] = {}

    @property
    def policy(self) -> PolicyEngine:
        return self._policy

    def issue(self, request: PolicyRequest) -> PolicyTicket:
        if not isinstance(request, PolicyRequest):
            raise TypeError("request must be a PolicyRequest")
        if type(request.asset_id) is not str:
            raise TypeError("a ticket names an asset: asset_id must be a str")
        decision = decide(self._policy, request)
        if not decision.allowed:
            raise PolicyDenied(
                request.artefact,
                f"refused by policy {decision.policy_id}/{decision.policy_version}: "
                f"{decision.reason}",
            )
        with self._lock:
            ticket = PolicyTicket(
                secrets.token_hex(16),
                request.principal.tenant,
                request.principal.subject,
                request.artefact,
                request.asset_id,
                request.record_id,
                decision.policy_id,
                decision.policy_version,
                self._epoch,
                self,
            )
            self._outstanding[ticket.ticket_id] = ticket
        return ticket

    def check(self, ticket: object, *, artefact: Artefact, asset_id: str, tenant: str) -> None:
        if not isinstance(artefact, Artefact):
            raise TypeError("artefact must be an Artefact")
        with self._lock:
            valid = (
                isinstance(ticket, PolicyTicket)
                and self._outstanding.get(ticket.ticket_id) is ticket
                and ticket.epoch == self._epoch
                and ticket.artefact is artefact
                and ticket.asset_id == asset_id
                and ticket.tenant == tenant
            )
        if not valid:
            raise PolicyDenied(artefact, "the ticket does not authorise this read")

    def revoke(self, ticket: PolicyTicket) -> None:
        with self._lock:
            if self._outstanding.get(getattr(ticket, "ticket_id", None)) is ticket:
                del self._outstanding[ticket.ticket_id]

    def revoke_asset(self, asset_id: str) -> int:
        return self._revoke_where(lambda ticket: ticket.asset_id == asset_id)

    def revoke_subject(self, tenant: str, subject: str) -> int:
        return self._revoke_where(
            lambda ticket: (ticket.tenant, ticket.subject) == (tenant, subject)
        )

    def advance_epoch(self) -> None:
        """Revoke every outstanding ticket: called whenever the engine or registry is replaced."""
        with self._lock:
            self._epoch += 1
            self._outstanding.clear()

    def _revoke_where(self, predicate) -> int:
        with self._lock:
            gone = [key for key, ticket in self._outstanding.items() if predicate(ticket)]
            for key in gone:
                del self._outstanding[key]
        return len(gone)


# --------------------------------------------------------------------------- the lattice

LATTICE_REFUSALS = (
    "EMPTY_INPUT",
    "UNINTERPRETED_FIELD",
    "UNRECOGNISED_LEVEL",
    "DIFFERENT_SYSTEM",
    "DIFFERENT_LEVEL",
    "DIFFERENT_CAVEATS",
    "EMPTY_RELEASABILITY",
    "NO_COMMON_RECIPIENT",
    "FIELD_OVERFLOW",
)


class LabelCombinationRefused(ValueError):
    """A combination the lattice cannot decide; `reason` is one of `LATTICE_REFUSALS`."""

    def __init__(self, reason: str) -> None:
        if reason not in LATTICE_REFUSALS:
            raise TypeError("reason must be one of the lattice refusal tokens")
        super().__init__(reason)
        self.reason = reason


class LabelLattice(Protocol):
    """Combines label records into one record of the same shape (scope `combined`, no index,
    offset or length), or refuses. Every implementation: never returns a level below any input's
    in its own ordering, never returns an empty releasability when an input's is non-empty, never
    reads an empty releasability as "every recipient", and refuses what it cannot decide."""

    lattice_id: str

    def combine(self, labels: Sequence[Mapping[str, object]]) -> dict: ...


_LEVELS = ("U", "R", "C", "S", "T")


def combined(fields: Mapping[str, object]) -> dict:
    """A combined record: the label shape with the combined scope and the given fields."""
    return {
        "scope": "combined",
        "index": None,
        "offset": None,
        "length": None,
        "fields": dict(fields),
        "uninterpreted": [],
    }


def screen(labels: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """The refusals every lattice shares: no input, or an input with a field nobody can read."""
    labels = list(labels)
    if not labels:
        raise LabelCombinationRefused("EMPTY_INPUT")
    if any(label["uninterpreted"] for label in labels):
        raise LabelCombinationRefused("UNINTERPRETED_FIELD")
    return labels


class IdenticalOnlyLattice:
    """Holds no scheme, so it orders nothing: it returns the common label when every input
    carries the same fields and refuses every other combination with the first difference."""

    lattice_id = "sc-imagery-identical-only/1"

    def combine(self, labels: Sequence[Mapping[str, object]]) -> dict:
        labels = screen(labels)
        if any(label["fields"]["CLAS"] not in _LEVELS for label in labels):
            raise LabelCombinationRefused("UNRECOGNISED_LEVEL")
        first = labels[0]["fields"]
        if all(label["fields"] == first for label in labels):
            return combined(copy.deepcopy(dict(first)))
        if len({label["fields"]["CLSY"] for label in labels}) > 1:
            raise LabelCombinationRefused("DIFFERENT_SYSTEM")
        if len({label["fields"]["CLAS"] for label in labels}) > 1:
            raise LabelCombinationRefused("DIFFERENT_LEVEL")
        raise LabelCombinationRefused("DIFFERENT_CAVEATS")
