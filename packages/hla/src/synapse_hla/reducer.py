"""The state reducer of section 7: `reduce_frame(state, frame)` turns one capture frame into the
next state and the ordered output records of that frame.

WHAT THE STATE HOLDS
--------------------
A `ReducerState` is built once from a verified capture header by `initial_state(header,
capture_complete)` (RED-19) and from then on only by `reduce_frame`, which returns a new one and
never changes the one it was given. It holds the session (the header's configuration, validated
once and kept as a frozen `config.ValidatedConfig` that every projection reuses, CR-L07; the
completion flag every record carries: null live, true or false in a replay, SPEC:158), the
position in the capture (the rules of the next line, so that the frame sequence, the hash chain
and the lifecycle framing are the capture's), and the generation state of R21: the open
generation, the object-token map, the identity index (triple -> holder token), the incarnation
counters, the removed-token set, the tokens seen in the generation, the cached-byte budget and
the terminal flag. Each object holds its discovery metadata, its lifecycle (ACTIVE or
QUARANTINED; a REMOVED object leaves the map and its token joins the removed set), its identity
once established (never changed afterwards), its incarnation and entity_id, the four attribute
slots (status ABSENT, VALID or INVALID, decoded value, captured hex, seq, elapsed_ns and external
effective time of the frame that supplied it), the last upsert revision, whether its last
evaluation was eligible, the unmapped force values it has warned about, and the effective time
of its last accepted Spatial value. Everything is immutable or never written after it is built,
so a new state shares whatever did not change with the old one instead of copying it.

WHICH FRAMES ARE ADMITTED
-------------------------
`reduce_frame` judges a frame by the capture's own rules (`capture._LineRules`): what a capture
verified up to this state's position may hold next is admitted, anything else is refused with
the code and the `line:<n>` path verification would report (CR-L01; frame seq n is line n + 1).
One rule is relaxed: elapsed_ns may decrease, because RED-09 keeps a defensive check here that
only such a frame can reach (a verified capture never has one). A frame is the reducer's input
from the wire, so a refusal is `HlaError`; a Python value that is not JSON is a caller bug
(`TypeError`), and so is a state that `initial_state` and `reduce_frame` did not build. A
verified capture never makes the reducer refuse a frame: every source problem it holds becomes
an ordered diagnostic record instead (R06).

WHAT EACH EVENT DOES
--------------------
- generation_start opens the generation, with empty maps and counters (R14: nothing is carried
  over). Under `profile_declaration` external-fom-unverified it emits W_FOM_UNVERIFIED, derived
  here and never captured (RED-01, OPS-19, R11).
- generation_end emits `invalidated` (reason generation_end) for every object still in the map
  that has an entity_id, by numeric token order, whatever was emitted before (SPEC:126,
  RED-V-02), and then nothing of the generation survives.
- A captured diagnostic becomes one diagnostic record at its seq, as it stands (RED-01).
- discover adds the object. Discovering a token again is W_DUPLICATE_DISCOVERY when the name and
  reported class are the same and a fatal capture fault otherwise, as is discovering a removed
  token: E_CAPTURE_SCHEMA, the object unchanged, the terminal flag set (RED-07, RED-13).
- reflect, for a known object, is processed atomically (R22): every supplied attribute is
  decoded before anything changes; one failure (an unknown name is E_UNSUBSCRIBED_ATTRIBUTE)
  rejects the whole reflection, marks every supplied known attribute INVALID with this frame's
  bytes, seq and time, and applies nothing; otherwise only the supplied attributes are
  replaced. Then the identity rules (R24, RED-10), the force warning (RED-17), the defensive
  time check (RED-09), and one snapshot, with the upsert when the state is eligible and the
  reflection supplied a known attribute. An empty reflection changes nothing and emits nothing;
  a retractable one is never decoded or applied: it emits E_RETRACTION_UNSUPPORTED, quarantines
  the object, and still emits the snapshot when it is not empty (RED-11). A reflection for a
  token that is not a discovered, unremoved object, retractable or not, is E_UNKNOWN_OBJECT and
  creates nothing: there is no object to quarantine.
- remove, for a known object, emits `removed` (the entity_id when one was allocated, the last
  revision, no Entity and no valid_to), deletes the cache, releases the identity reservation and
  remembers the token as removed (R25). A removed token again is W_DUPLICATE_REMOVE; an unknown
  one E_UNKNOWN_OBJECT; a retractable remove only quarantines (RED-11).

Identity (R24, RED-10): the first VALID non-null identifier an ACTIVE object applies claims its
triple: the incarnation counter of the triple advances, and the entity_id is R26's
(`_identity`). The null identifier claims nothing. A triple another object holds is a
collision: E_IDENTITY_COLLISION for each object newly quarantined (the claimant always, the
holder unless it already was), the holder keeps its reservation, identity and entity_id, and is
invalidated once in this frame if it was eligible; the claimant gets no identity for life. A
VALID identifier that differs from an established identity is E_IDENTITY_CHANGED every time,
and quarantines once. A quarantined object never claims, keeps applying valid values and never
projects; quarantine ends only with the object.

Eligibility is the projector's answer (R23, round R3) for the snapshot the reducer built, through
`projector._project_from_reducer`, the entry of `project_state` that does not hold this module's
own snapshot and the projector's own provenance block to their schemas again (CR-L17); the
snapshot carries it. With each snapshot come the diagnostics RED-02 places beside it: E_NULL_ID
when NULL_ID is a reason, the geography code when GEOGRAPHY_UNPROJECTABLE is one and no
MISSING_ or INVALID_ reason is, W_TIME_UNRESOLVED when TIME_UNRESOLVED is the only reason. An
object that was eligible and is not any more is invalidated once, with the identity or
retraction reason of the frame, else invalid_required_attribute when an INVALID_ reason holds,
else projection_unavailable (SPEC:285).

Limits (RED-12, OPS-22, through the state's `Limits`): more supplied attributes than a
reflection may carry, a reflection that would take the cached raw bytes of the generation past
their budget, a discover beyond the active objects of a generation, and a token beyond the
distinct (generation, token) pairs of a session each emit E_LIMIT (the token, no attribute),
apply nothing, emit no snapshot and set the terminal flag. The count of supplied attributes is
judged first (NAT-06). A token first named by a reflection or removal of an unknown object
counts as a distinct token too: the worker allocated it (NAT-11). The flag tells the host to
stop; the reducer itself judges every later frame on its own, and the flag ends with the
generation.

THE RECORDS OF ONE FRAME
------------------------
In R33's order: diagnostics by (code, attribute with null first, token by its number with null
first) (RED-03), then `invalidated` by token number, then `removed`, then the changed object's
snapshot, then its upsert; ordinals count from 0 in each frame. Every envelope is
`output.schema.json`'s: the frame's seq and generation, `revision` only on an upsert, and
`entity_id` the one the token holds after the frame (RED-03; null for a token with none, an
unknown or removed token, or a session-level diagnostic), except on a lifecycle record, which
names the entity it ends. `check_records` holds every frame's records to RED-16 and R33 before
they are returned; a breach is a `ReducerDefect`, a defect of this module and never a property
of the data. `output_line` is a record's line in the output files (RED-15).

Nothing here reads a clock, a file or the environment (D-08). Time is the capture's: effective
time is the configured epoch plus the frame's elapsed_ns integer-divided by 1000 (CR-L05).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace

from synapse_hla import _identity, _utc, canonical, capture, codec, config, errors, projector
from synapse_hla.codec import ENTITY_IDENTIFIER, FORCE_IDENTIFIER, NAMES, SPATIAL
from synapse_hla.errors import HlaError
from synapse_hla.limits import V1, Limits

OUTPUT_VERSION = 1

# --- record kinds and lifecycle reasons (output.schema.json) -------------------------------------

DIAGNOSTIC = "diagnostic"
SNAPSHOT = "snapshot"
UPSERT = "upsert"
REMOVED = "removed"
INVALIDATED = "invalidated"
KINDS = (DIAGNOSTIC, SNAPSHOT, UPSERT, REMOVED, INVALIDATED)

REASON_REMOVED = "removed"
GENERATION_END = "generation_end"
INVALID_REQUIRED_ATTRIBUTE = "invalid_required_attribute"
IDENTITY_CHANGED = "identity_changed"
IDENTITY_COLLISION = "identity_collision"
RETRACTION_UNSUPPORTED = "retraction_unsupported"
PROJECTION_UNAVAILABLE = "projection_unavailable"

# --- object vocabulary ---------------------------------------------------------------------------

ACTIVE = "ACTIVE"
QUARANTINED = projector.QUARANTINED
ABSENT = projector.ABSENT
VALID = projector.VALID
INVALID = projector.INVALID
ELIGIBLE = "ELIGIBLE"
SUPPRESSED = "SUPPRESSED"

#: The declaration under which every generation_start emits W_FOM_UNVERIFIED (R11, RED-01).
FOM_UNVERIFIED_DECLARATION = config.DECLARATION_FOR_MODE[config.EXISTING]
_NULL_TRIPLE = (0, 0, 0)
_NANOSECONDS_PER_MICROSECOND = 1000

# --- the messages of the diagnostics this module derives (fixed text: R37, CR-L01) ---------------

_MESSAGES = {
    errors.W_FOM_UNVERIFIED: "the federation's FOM is declared unverified: names were resolved, "
                             "type definitions were not proven",
    errors.W_DUPLICATE_DISCOVERY: "the object was discovered again with the same name and "
                                  "reported class",
    errors.W_DUPLICATE_REMOVE: "the object was already removed in this generation",
    errors.E_UNKNOWN_OBJECT: "the frame names a token that is not a discovered, unremoved object",
    errors.E_RETRACTION_UNSUPPORTED: "a retractable update cannot be undone by replay and is not "
                                     "applied",
    errors.E_IDENTITY_CHANGED: "the object asserted another EntityIdentifier than the identity "
                               "it established",
    errors.E_IDENTITY_COLLISION: "another object of the generation holds this EntityIdentifier",
    errors.E_NULL_ID: "the EntityIdentifier is the null identifier and identifies no entity",
    errors.E_ECEF_RANGE: "the Spatial position lies outside the geographic projection gate",
    errors.E_GEODESY: "the Spatial position does not convert to WGS84 coordinates",
    errors.E_TIME_REGRESSION: "the Spatial effective time is earlier than that of the last "
                              "accepted Spatial value",
    errors.W_TIME_UNRESOLVED: "the state is complete but has no external time context",
    errors.W_FORCE_UNMAPPED: "the ForceIdentifier value is not in the configured force_map",
}
_REDISCOVERED = "the object was discovered again with another name or reported class"
_DISCOVERED_REMOVED = "a removed object's token was discovered again"
_TOO_MANY_ATTRIBUTES = "the reflection supplies more attributes than a reflection may"
_TOO_MANY_BYTES = "the reflection would take the generation's cached attribute bytes past " \
                  "their limit"
_TOO_MANY_OBJECTS = "the generation already holds as many active objects as it may"
_TOO_MANY_TOKENS = "the session already holds as many object tokens as it may"


class ReducerDefect(RuntimeError):
    """Records this module built break RED-16 or R33: a defect here, never a data fault."""


# --- the state ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Slot:
    """One attribute of one object (SPEC:283): ABSENT all null; INVALID no value; VALID all set."""

    status: str
    value: dict | None
    hex: str | None
    seq: int | None
    elapsed_ns: str | None
    effective_at: str | None

    @property
    def raw_bytes(self) -> int:
        """The raw bytes this slot keeps, VALID or INVALID: what the cache budget counts."""
        return 0 if self.hex is None else len(self.hex) // 2


ABSENT_SLOT = Slot(ABSENT, None, None, None, None, None)


@dataclass(frozen=True)
class ObjectState:
    """One discovered, unremoved object of the open generation; see the module text."""

    name: str
    reported_class: str
    lifecycle: str
    identity: tuple[int, int, int] | None
    incarnation: int | None
    entity_id: str | None
    slots: tuple[Slot, Slot, Slot, Slot]
    last_revision: int
    eligible: bool
    warned_forces: frozenset
    spatial_mark: int | None

    def slot(self, name: str) -> Slot:
        return self.slots[NAMES.index(name)]

    @property
    def cached_bytes(self) -> int:
        return sum(slot.raw_bytes for slot in self.slots)


@dataclass(frozen=True)
class ReducerState:
    """The session and generation state between two frames; see the module text.

    Built only by `initial_state` and `reduce_frame`. Its members are read-only: nothing in the
    package writes to them after the state is built, and neither may a caller.
    """

    limits: Limits
    #: The header's configuration, validated once for the session (CR-L07).
    config: config.ValidatedConfig
    capture_complete: bool | None
    rules: capture._LineRules
    generation: int | None
    objects: dict
    removed: frozenset
    seen: frozenset
    index: dict
    incarnations: dict
    cache_bytes: int
    terminal: bool
    tokens_before: int

    @property
    def next_seq(self) -> int:
        """The seq the next frame must carry."""
        return self.rules.next_seq

    @property
    def distinct_tokens(self) -> int:
        """Distinct (generation, token) pairs of the session so far (RED-12, A.2)."""
        return self.tokens_before + len(self.seen)


def _line_bytes(value, number: int) -> bytes:
    """The canonical line of a record handed to the reducer, or the capture's refusal of it."""
    try:
        return canonical.canonical_bytes(value)
    except canonical.StrictJsonError as refusal:
        raise HlaError(errors.E_CAPTURE_SCHEMA, capture._at(number, refusal.tokens),
                       capture._PARSE_REASONS[refusal.reason]) from None


def initial_state(header, capture_complete, *, limits: Limits = V1) -> ReducerState:
    """The state before the first frame of a capture whose header is `header` (RED-19).

    `capture_complete` is what every record will carry: None in a live session, True or False
    in a replay. The header is held to the capture's rules for line 1 (its schema, its audit
    time, the full semantic validation of its configuration: RED-V-01); a refusal is the
    `HlaError` verification would report. Its pins are replay's to compare (RED-V-03), not this
    function's. `limits` is the OPS-21 seam; only tests pass another.
    """
    if capture_complete is not None and type(capture_complete) is not bool:
        raise TypeError("capture_complete is True, False or None")
    rules = capture._LineRules(limits, elapsed_may_decrease=True)
    fault, record = rules.check(1, _line_bytes(header, 1))
    if fault is not None:
        raise HlaError(fault.code, fault.path, fault.message)
    return ReducerState(limits=limits, config=rules.session, capture_complete=capture_complete,
                        rules=rules, generation=None, objects={}, removed=frozenset(),
                        seen=frozenset(), index={}, incarnations={}, cache_bytes=0,
                        terminal=False, tokens_before=0)


def reduce_frame(state, frame) -> tuple[ReducerState, list[dict]]:
    """The state after `frame` and the frame's output records, in order; see the module text.

    Neither argument is changed, and the records share no object with either or with the new
    state.
    """
    if type(state) is not ReducerState:
        raise TypeError("reduce_frame takes a ReducerState built by initial_state or reduce_frame")
    number = state.rules.lines + 1
    raw = _line_bytes(frame, number)
    rules = copy.copy(state.rules)
    fault, record = rules.check(number, raw)
    if fault is not None:
        raise HlaError(fault.code, fault.path, fault.message)
    if record["type"] != capture.FRAME:
        raise HlaError(errors.E_CAPTURE_SCHEMA, capture._at(number, ("type",)),
                       "reduce_frame reduces frames; the footer produces no observations")
    step = _Step(state, rules, record)
    step.run()
    return step.result()


def reduce_admitted(state, record: dict) -> tuple[ReducerState, list[dict]]:
    """`reduce_frame` for a frame that the caller's own capture rules have just admitted at
    exactly this state's position; the caller gives `record` up (CR-L07).

    Replay reads every line through a verified `capture.CaptureReader`, and the live host writes
    every frame through a `capture.CaptureChain`; both judge each line by the same
    `capture._LineRules` the reducer holds (stricter only in that elapsed_ns may not decrease
    there), fed the same lines from the same header. A frame they admitted would pass every rule
    here again, so judging it a second time is work without a verdict, and it was a fifth of the
    cost of an eligible reflection. What is still checked is that the frame is the one for this
    position: a frame record whose `seq` is the next one and whose `prev_sha256` is the chain
    head, which through the hash chain ties the caller's verified history to the one this state
    holds. Anything else is a caller bug (`ValueError`), and the state is left as it was.
    """
    if type(state) is not ReducerState:
        raise TypeError("reduce_admitted takes a ReducerState built by initial_state or "
                        "reduce_frame")
    rules = state.rules
    if type(record) is not dict or record.get("type") != capture.FRAME \
            or type(record.get("seq")) is not int or record["seq"] != rules.next_seq \
            or record.get("prev_sha256") != rules.last_sha256 \
            or type(record.get("sha256")) is not str:
        raise ValueError("reduce_admitted takes the next frame of this state's capture, as the "
                         "caller's capture rules admitted it")
    rules = copy.copy(rules)
    rules._take(rules.lines + 1, None, record, None)
    step = _Step(state, rules, record)
    step.run()
    return step.result()


def output_line(record: dict) -> bytes:
    """A record's line in observations.jsonl and diagnostics.jsonl: canonical JSON with finite
    floats in Python's shortest repr, then LF (RED-15)."""
    return canonical.canonical_bytes(record, floats=True) + b"\n"


# --- one frame ------------------------------------------------------------------------------------

def _token_number(token: str | None) -> int:
    # Tokens are "o" and a positive decimal (event.schema.json): ordered by that number, so o2
    # comes before o10 (RED-03); null, for a session-level diagnostic, before every token.
    return -1 if token is None else int(token[1:])


def _diagnostic_key(item: tuple) -> tuple:
    code, attribute, token, _ = item
    return (code, attribute is not None, attribute or "", _token_number(token))


def _json_copy(value):
    if type(value) is dict:
        return {key: _json_copy(item) for key, item in value.items()}
    if type(value) is list:
        return [_json_copy(item) for item in value]
    return value


def _identity_value(triple: tuple[int, int, int] | None) -> dict | None:
    if triple is None:
        return None
    site, application, entity = triple
    return {"site": site, "application": application, "entity": entity}


def _slot_value(slot: Slot) -> dict:
    return {"status": slot.status, "value": _json_copy(slot.value), "hex": slot.hex,
            "seq": slot.seq, "elapsed_ns": slot.elapsed_ns, "effective_at": slot.effective_at}


class _Step:
    """The work of one frame: the state's maps copied when first written, the records gathered."""

    def __init__(self, state: ReducerState, rules: capture._LineRules, frame: dict) -> None:
        self.state = state
        self.rules = rules
        self.frame = frame
        self.event = frame["event"]
        self.seq = frame["seq"]
        self.limits = state.limits
        # A read-only view of the configuration validated once for the session (CR-L07); the
        # wrapper itself goes into each projection context, so the projector does not validate
        # it again.
        self.validated = state.config
        self.session = state.config.document
        self.epoch = state.config.epoch_microsecond
        self.generation = state.generation
        self.objects = state.objects
        self.removed = state.removed
        self.seen = state.seen
        self.index = state.index
        self.incarnations = state.incarnations
        self.cache_bytes = state.cache_bytes
        self.terminal = state.terminal
        self.tokens_before = state.tokens_before
        self._copied: set[str] = set()
        # (code, attribute, token, message); (token, reason, entity_id, last_revision)
        self.diagnostics: list[tuple] = []
        self.invalidations: list[tuple] = []
        self.removals: list[tuple] = []
        self.snapshot: tuple | None = None
        self.upsert: tuple | None = None

    # -- copy on write

    def _writable(self, name: str) -> dict:
        if name not in self._copied:
            setattr(self, name, dict(getattr(self, name)))
            self._copied.add(name)
        return getattr(self, name)

    def _put(self, token: str, obj: ObjectState) -> None:
        self._writable("objects")[token] = obj

    def _see(self, token: str) -> None:
        if token not in self.seen:
            self.seen = self.seen | {token}

    def _clear_generation(self, generation: int | None) -> None:
        self.tokens_before += len(self.seen)
        self.generation = generation
        self.objects, self.removed, self.seen = {}, frozenset(), frozenset()
        self.index, self.incarnations = {}, {}
        self.cache_bytes = 0
        self.terminal = False
        self._copied = {"objects", "index", "incarnations"}

    # -- diagnostics and limits

    def _diagnose(self, code: str, attribute: str | None, token: str | None,
                  message: str | None = None) -> None:
        self.diagnostics.append((code, attribute, token,
                                 _MESSAGES[code] if message is None else message))

    def _limit(self, token: str, message: str) -> None:
        self._diagnose(errors.E_LIMIT, None, token, message)
        self.terminal = True

    def _token_admitted(self, token: str) -> bool:
        """False, with E_LIMIT, when `token` would be one distinct token too many (RED-12)."""
        if token in self.seen:
            return True
        if self.tokens_before + len(self.seen) + 1 > self.limits.object_tokens_per_session:
            self._limit(token, _TOO_MANY_TOKENS)
            return False
        return True

    # -- the events

    def run(self) -> None:
        kind = self.event["type"]
        if kind == capture.GENERATION_START:
            self._clear_generation(self.frame["generation"])
            if self.session["profile_declaration"] == FOM_UNVERIFIED_DECLARATION:
                self._diagnose(errors.W_FOM_UNVERIFIED, None, None)
        elif kind == capture.GENERATION_END:
            for token, obj in self.objects.items():
                if obj.entity_id is not None:
                    self.invalidations.append((token, GENERATION_END, obj.entity_id,
                                               obj.last_revision))
            self._clear_generation(None)
        elif kind == capture.DIAGNOSTIC:
            captured = self.event["diagnostic"]
            self._diagnose(captured["code"], captured["attribute"], self.event["object_token"],
                           captured["message"])
        elif kind == capture.DISCOVER:
            self._discover()
        elif kind == capture.REFLECT:
            self._reflect()
        else:
            self._remove()

    def _discover(self) -> None:
        token = self.event["object_token"]
        name, reported_class = self.event["name"], self.event["reported_class"]
        known = self.objects.get(token)
        if known is not None:
            if known.name == name and known.reported_class == reported_class:
                self._diagnose(errors.W_DUPLICATE_DISCOVERY, None, token)
            else:
                self._diagnose(errors.E_CAPTURE_SCHEMA, None, token, _REDISCOVERED)
                self.terminal = True
            return
        if token in self.removed:
            self._diagnose(errors.E_CAPTURE_SCHEMA, None, token, _DISCOVERED_REMOVED)
            self.terminal = True
            return
        if not self._token_admitted(token):
            return
        if len(self.objects) + 1 > self.limits.active_objects_per_generation:
            self._limit(token, _TOO_MANY_OBJECTS)
            return
        self._see(token)
        self._put(token, ObjectState(name=name, reported_class=reported_class, lifecycle=ACTIVE,
                                     identity=None, incarnation=None, entity_id=None,
                                     slots=(ABSENT_SLOT,) * len(NAMES), last_revision=0,
                                     eligible=False, warned_forces=frozenset(),
                                     spatial_mark=None))

    def _unknown(self, token: str) -> None:
        if self._token_admitted(token):
            self._see(token)
            self._diagnose(errors.E_UNKNOWN_OBJECT, None, token)

    def _remove(self) -> None:
        token = self.event["object_token"]
        obj = self.objects.get(token)
        if obj is None:
            if token in self.removed:
                self._diagnose(errors.W_DUPLICATE_REMOVE, None, token)
            else:
                self._unknown(token)
            return
        if self.event["retractable"]:
            self._diagnose(errors.E_RETRACTION_UNSUPPORTED, None, token)
            if obj.eligible:
                self.invalidations.append((token, RETRACTION_UNSUPPORTED, obj.entity_id,
                                           obj.last_revision))
            self._put(token, replace(obj, lifecycle=QUARANTINED, eligible=False))
            return
        self.removals.append((token, obj.entity_id, obj.last_revision))
        if obj.identity is not None and self.index.get(obj.identity) == token:
            del self._writable("index")[obj.identity]
        self.cache_bytes -= obj.cached_bytes
        del self._writable("objects")[token]
        self.removed = self.removed | {token}

    def _reflect(self) -> None:
        token = self.event["object_token"]
        attributes = self.event["attributes"]
        if len(attributes) > self.limits.attributes_per_reflection:
            self._limit(token, _TOO_MANY_ATTRIBUTES)
            return
        obj = self.objects.get(token)
        if obj is None:
            self._unknown(token)
            return
        known = [(a["name"], a["hex"]) for a in attributes if a["name"] in NAMES]
        changed = [name for name, _ in known]
        if self.event["retractable"]:
            self._diagnose(errors.E_RETRACTION_UNSUPPORTED, None, token)
            quarantined = replace(obj, lifecycle=QUARANTINED)
            if attributes:
                self._put(token, quarantined)
                self._evaluate(token, obj.eligible, changed, False, RETRACTION_UNSUPPORTED)
            else:
                if obj.eligible:
                    self.invalidations.append((token, RETRACTION_UNSUPPORTED, obj.entity_id,
                                               obj.last_revision))
                self._put(token, replace(quarantined, eligible=False))
            return
        if not attributes:
            return
        budget = self.cache_bytes + sum(len(raw) // 2 - obj.slot(name).raw_bytes
                                        for name, raw in known)
        if budget > self.limits.cached_attribute_bytes_per_generation:
            self._limit(token, _TOO_MANY_BYTES)
            return
        self.cache_bytes = budget
        self._apply(token, obj, attributes, known, changed)

    def _apply(self, token: str, obj: ObjectState, attributes: list, known: list,
               changed: list) -> None:
        decoded, failures = {}, []
        for attribute in attributes:
            name = attribute["name"]
            try:
                decoded[name] = codec.decode_attribute(name, bytes.fromhex(attribute["hex"]))
            except HlaError as error:
                # The diagnostic names the attribute as the frame did, never error.path
                # (CR-R1-04); the decoder's message quotes no input.
                failures.append((error.code, name, error.message))
        elapsed = self.frame["elapsed_ns"]
        effective = None if self.epoch is None else \
            self.epoch + int(elapsed) // _NANOSECONDS_PER_MICROSECOND
        effective_at = None if effective is None else _utc.format_microsecond(effective)
        slots = list(obj.slots)
        if failures:
            for code, name, message in failures:
                self._diagnose(code, name, token, message)
            for name, raw in known:
                slots[NAMES.index(name)] = Slot(INVALID, None, raw, self.seq, elapsed,
                                                effective_at)
            self._put(token, replace(obj, slots=tuple(slots)))
            self._evaluate(token, obj.eligible, changed, False, None)
            return
        for name, raw in known:
            slots[NAMES.index(name)] = Slot(VALID, decoded[name]["value"], raw, self.seq, elapsed,
                                            effective_at)
        updated = {}
        if SPATIAL in decoded and effective is not None:
            if obj.spatial_mark is not None and effective < obj.spatial_mark:
                # RED-09: the regressed value is kept as rejected source; the other supplied
                # attributes still apply, so this is not an atomic rejection.
                index = NAMES.index(SPATIAL)
                slots[index] = replace(slots[index], status=INVALID, value=None)
                self._diagnose(errors.E_TIME_REGRESSION, SPATIAL, token)
            else:
                updated["spatial_mark"] = effective
        updated["slots"] = tuple(slots)
        reason = None
        if ENTITY_IDENTIFIER in decoded:
            reason = self._identify(token, obj, decoded[ENTITY_IDENTIFIER]["value"], updated)
        if FORCE_IDENTIFIER in decoded:
            value = decoded[FORCE_IDENTIFIER]["value"]["value"]
            if str(value) not in self.session["force_map"] and value not in obj.warned_forces:
                updated["warned_forces"] = obj.warned_forces | {value}
                self._diagnose(errors.W_FORCE_UNMAPPED, FORCE_IDENTIFIER, token)
        self._put(token, replace(obj, **updated))
        self._evaluate(token, obj.eligible, changed, True, reason)

    def _identify(self, token: str, obj: ObjectState, value: dict, updated: dict) -> str | None:
        """R24 and RED-10 for one applied VALID identifier; the transition reason, if any."""
        triple = (value["site"], value["application"], value["entity"])
        if obj.identity is not None:
            if triple == obj.identity:
                return None
            self._diagnose(errors.E_IDENTITY_CHANGED, ENTITY_IDENTIFIER, token)
            if obj.lifecycle == QUARANTINED:
                return None
            updated["lifecycle"] = QUARANTINED
            return IDENTITY_CHANGED
        if obj.lifecycle == QUARANTINED or triple == _NULL_TRIPLE:
            return None
        holder = self.index.get(triple)
        if holder is not None:
            updated["lifecycle"] = QUARANTINED
            self._diagnose(errors.E_IDENTITY_COLLISION, ENTITY_IDENTIFIER, token)
            held = self.objects[holder]
            if held.lifecycle != QUARANTINED:
                self._diagnose(errors.E_IDENTITY_COLLISION, ENTITY_IDENTIFIER, holder)
            if held.eligible:
                self.invalidations.append((holder, IDENTITY_COLLISION, held.entity_id,
                                           held.last_revision))
            self._put(holder, replace(held, lifecycle=QUARANTINED, eligible=False))
            return IDENTITY_COLLISION
        incarnation = self.incarnations.get(triple, 0) + 1
        self._writable("incarnations")[triple] = incarnation
        self._writable("index")[triple] = token
        external = _identity.external_id(self.session["session_id"], self.generation, value,
                                         incarnation)
        updated.update(identity=triple, incarnation=incarnation,
                       entity_id=_identity.entity_id(external))
        return None

    def _evaluate(self, token: str, was_eligible: bool, changed: list, supplied: bool,
                  reason: str | None) -> None:
        """The snapshot of `token` after this frame, its RED-02 diagnostics, the transition
        invalidation, and the upsert when the state is eligible and `supplied` holds."""
        obj = self.objects[token]
        payload = {
            "name": obj.name, "reported_class": obj.reported_class, "lifecycle": obj.lifecycle,
            "identity": _identity_value(obj.identity), "incarnation": obj.incarnation,
            "attributes": {name: _slot_value(slot) for name, slot in zip(NAMES, obj.slots)},
            "changed_attributes": list(changed), "projection_status": SUPPRESSED,
            "suppression_reasons": [], "last_revision": obj.last_revision,
        }
        context = {"config": self.validated, "generation": self.generation, "object_token": token,
                   "identity": _identity_value(obj.identity), "incarnation": obj.incarnation,
                   "seq": self.seq, "sha256": self.frame["sha256"],
                   "capture_complete": self.state.capture_complete}
        result = projector._project_from_reducer(payload, context)
        eligible = type(result) is not projector.Suppression
        reasons = [] if eligible else list(result.reasons)
        if projector.NULL_ID in reasons:
            self._diagnose(errors.E_NULL_ID, ENTITY_IDENTIFIER, token)
        if projector.GEOGRAPHY_UNPROJECTABLE in reasons and not any(
                r.startswith(("MISSING_", "INVALID_")) for r in reasons):
            self._diagnose(result.geography_code, SPATIAL, token)
        if reasons == [projector.TIME_UNRESOLVED]:
            self._diagnose(errors.W_TIME_UNRESOLVED, None, token)
        if was_eligible and not eligible:
            if reason is None:
                reason = INVALID_REQUIRED_ATTRIBUTE if any(
                    r.startswith("INVALID_") for r in reasons) else PROJECTION_UNAVAILABLE
            self.invalidations.append((token, reason, obj.entity_id, obj.last_revision))
        payload["projection_status"] = ELIGIBLE if eligible else SUPPRESSED
        payload["suppression_reasons"] = reasons
        self.snapshot = (token, payload)
        revision = obj.last_revision
        if eligible and supplied:
            revision += 1
            self.upsert = (token, obj.entity_id, revision, projector.entity_payload(result))
        self._put(token, replace(obj, eligible=eligible, last_revision=revision))

    # -- the result

    def _entity_id_after(self, token: str | None) -> str | None:
        obj = None if token is None else self.objects.get(token)
        return None if obj is None else obj.entity_id

    def result(self) -> tuple[ReducerState, list[dict]]:
        generation = self.frame["generation"]
        session_id = self.session["session_id"]
        complete = self.state.capture_complete
        records = []

        def emit(kind, token, entity_id, revision, payload):
            records.append({"output_version": OUTPUT_VERSION, "session_id": session_id,
                            "seq": self.seq, "ordinal": len(records), "generation": generation,
                            "kind": kind, "object_token": token, "entity_id": entity_id,
                            "revision": revision, "capture_complete": complete,
                            "payload": payload})

        for code, attribute, token, message in sorted(self.diagnostics, key=_diagnostic_key):
            emit(DIAGNOSTIC, token, self._entity_id_after(token), None,
                 {"severity": errors.severity(code), "code": code, "message": message,
                  "seq": self.seq, "generation": generation, "object_token": token,
                  "attribute": attribute})
        for token, reason, entity_id, last_revision in sorted(
                self.invalidations, key=lambda item: _token_number(item[0])):
            emit(INVALIDATED, token, entity_id, None,
                 {"reason": reason, "last_revision": last_revision})
        for token, entity_id, last_revision in self.removals:
            emit(REMOVED, token, entity_id, None,
                 {"reason": REASON_REMOVED, "last_revision": last_revision})
        if self.snapshot is not None:
            token, payload = self.snapshot
            emit(SNAPSHOT, token, self._entity_id_after(token), None, payload)
        if self.upsert is not None:
            token, entity_id, revision, payload = self.upsert
            emit(UPSERT, token, entity_id, revision, payload)
        check_records(self.frame, records)
        state = ReducerState(
            limits=self.limits, config=self.validated, capture_complete=complete, rules=self.rules,
            generation=self.generation, objects=self.objects, removed=self.removed,
            seen=self.seen, index=self.index, incarnations=self.incarnations,
            cache_bytes=self.cache_bytes, terminal=self.terminal,
            tokens_before=self.tokens_before)
        return state, records


# -- RED-16 and R33 on every frame's records -------------------------------------------------------

_RANK = {DIAGNOSTIC: 0, INVALIDATED: 1, REMOVED: 2, SNAPSHOT: 3, UPSERT: 4}
_ENVELOPE = ("output_version", "session_id", "seq", "ordinal", "generation", "kind",
             "object_token", "entity_id", "revision", "capture_complete", "payload")


def _sorted_unique(values: list) -> bool:
    return values == sorted(set(values))


def _record_problems(frame: dict, records: list):
    kind_of_event = frame["event"]["type"]
    ranks = []
    for ordinal, record in enumerate(records):
        if type(record) is not dict or tuple(sorted(record)) != tuple(sorted(_ENVELOPE)):
            yield "an envelope does not carry exactly output.schema.json's members"
            return
        kind, payload = record["kind"], record["payload"]
        if kind not in _RANK:
            yield "a record kind outside the five"
            return
        ranks.append(_RANK[kind])
        if record["output_version"] != OUTPUT_VERSION or record["ordinal"] != ordinal \
                or record["seq"] != frame["seq"] or record["generation"] != frame["generation"]:
            yield "the envelope's version, ordinal, seq or generation is not the frame's"
        if (record["revision"] is not None) != (kind == UPSERT):
            yield "a revision on a record other than an upsert, or an upsert without one"
        if kind == REMOVED and (payload["reason"] != REASON_REMOVED
                                or kind_of_event != capture.REMOVE):
            yield "a removed record whose reason is not removed or whose frame is not a remove"
        ends = kind_of_event == capture.GENERATION_END
        if kind == INVALIDATED and (payload["reason"] == REASON_REMOVED
                                    or (payload["reason"] == GENERATION_END) != ends):
            yield "an invalidated record with reason removed, or generation_end out of place"
        if kind == UPSERT and record["entity_id"] != payload["entity_id"]:
            yield "an upsert whose envelope entity_id is not its Entity's"
        if kind == DIAGNOSTIC and (not errors.is_code(payload["code"])
                                   or payload["severity"] != errors.severity(payload["code"])
                                   or payload["object_token"] != record["object_token"]):
            yield "a diagnostic whose code, severity or token contradicts the contract"
        if kind == SNAPSHOT:
            reasons = payload["suppression_reasons"]
            if not _sorted_unique(reasons) or not set(reasons) <= set(projector.REASONS) \
                    or (payload["projection_status"] == ELIGIBLE) != (not reasons) \
                    or not _sorted_unique(payload["changed_attributes"]):
                yield "a snapshot's reasons or changed attributes are not sorted, unique and " \
                      "of the vocabulary, or its status contradicts them"
    if ranks != sorted(ranks):
        yield "the records are not in R33's order"
    kinds = [record["kind"] for record in records]
    if kinds.count(SNAPSHOT) > 1 or kinds.count(UPSERT) > 1:
        yield "more than one snapshot or upsert in one frame"
    if UPSERT in kinds and (SNAPSHOT not in kinds
                            or records[-1]["object_token"] != records[-2]["object_token"]):
        yield "an upsert that does not follow its object's snapshot"
    if kind_of_event == capture.GENERATION_END and set(kinds) - {INVALIDATED}:
        yield "a generation_end frame emits something other than invalidated records"


def check_records(frame: dict, records: list) -> None:
    """RED-16 and R33 on the records of one frame: raises `ReducerDefect` naming the first breach.

    The schemas let through a removed record with another reason, a revision on a snapshot, an
    upsert whose envelope names another entity, unsorted or repeated reasons and records out of
    order (RED-16); the product holds its own output to the prose instead.
    """
    for problem in _record_problems(frame, records):
        raise ReducerDefect(problem)
