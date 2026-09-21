"""The AIXM temporality resolver: explicit prior state + an as-of instant -> the resolved view
of a feature's availability / activation under the PUBLISHED temporality rules, for the three
Digital NOTAM scenario families `adapters/aixm511.py` pins (runway closure, airspace
activation, navaid outage). Adapter expansion phase 5 (2026-09-21).

This module is published-rule processing. It is not planning, not deconfliction and not a
NOTAM generator: it applies the AIXM Temporality Concept 1.1 and the Digital NOTAM
Specification 2.0 (DRAFT) coding rules to slices a caller hands it, and reports what those
rules yield — including "unresolved" and "ambiguous", which are results, not failures.

THE CONTRACT
------------
`resolve(objects, feature, as_of)` takes the canonical objects the AIXM 5.1.1 adapter produced
(one Entity per time slice, `attributes["aixm"]` the typed slice, `attributes["dnotam"]` where
the Event extension binds it) — from ANY number of documents: the baseline data set and the
Digital NOTAM messages — the feature's `gml:identifier` and an instant, and returns a
`Resolution`. The caller supplies every slice it wants considered; the resolver holds NOTHING
between calls (no cache, no store), so the same objects and the same instant always give the
same answer, and a slice the caller did not pass does not exist for it. The adapter stays
stateless; this is the separate deterministic resolver master §7 asks for.

THE RULES, BY IDENTIFIER
------------------------
* **The valid slice of a sequence** is the one with the highest correction number
  (Temporality Concept 1.1 §3.6, §4.4.4); a missing correction number counts as 0 (TS_007 /
  TS_008). Document order and arrival order play no part, so a correction received before the
  slice it corrects resolves the same way. Two slices with the same (interpretation, sequence,
  correction) are a conflict (TS_005): the sequence is AMBIGUOUS and nothing of it is applied.
* **A cancellation** — the valid correction has an empty `gml:validTime` with a nilReason
  (§4.4.8, "abandoned changes"; guidance page "Event update or cancellation", inactive Event) —
  takes the sequence off the timeline. It is kept in `history` as `cancelled`, with every
  earlier correction: the record is never erased. A correction with a higher number after the
  cancelling one is TS_019's forbidden reinstatement and is reported. A cancelled temporary
  change leaves the BASELINE state in force, whatever that is — if the baseline states no
  availability, the result is `not stated` / UNRESOLVED, never "available".
* **The BASELINE at as-of** is the valid BASELINE whose validity period contains the instant
  (begin included, end excluded — §4.4.1; an `indeterminatePosition="unknown"` end is open —
  §4.4.2). None: the feature's state is UNRESOLVED (the caller did not pass the baseline, or
  the feature does not exist at that instant) and NO feature is invented. Two: TS_009 is broken
  and the result is AMBIGUOUS.
* **The TEMPDELTAs at as-of** are the valid TEMPDELTAs whose period contains the instant. A
  TEMPDELTA REPLACES the baseline's whole multi-occurring property during its validity (§4.4.6.3;
  guidance ER-04, NAV.UNS.08, RWY.CLS.03 — "completely replaces all the BASELINE … information"),
  so the resolved availability / activation is the TEMPDELTA's list of structures, not a merge.
  A TEMPDELTA that states the property nil (`xsi:nil`, §4.4.6.3 "all occurrences removed") is
  a WITHDRAWAL: the resolved list is empty and the status `withdrawn`. A TEMPDELTA that does not
  state the property leaves the baseline's in force (§4.4.6: a delta carries only what changes).
* **Overlapping temporary changes.** Two valid TEMPDELTAs whose periods both contain the
  instant and that both state the SAME property break TS_011 ("shall not have overlapping or
  intersecting validTime periods and modify the same property"). The documented rule is that
  the value cannot be determined — the resolver reports AMBIGUOUS, names both slices, and
  applies NEITHER; it does not pick the later sequence, the later correction or the shorter
  period. Two overlapping TEMPDELTAs that modify DIFFERENT properties are not a conflict.
* **Correction of an active slice** may change only the end of validity (TS_017). A valid
  correction whose begin differs from the correction before it is reported (the correction still
  wins — §3.6 is the rule for which slice is valid; TS_017 is a finding about the provider).
* **Expiry** is the end of validity: at or after `effective_to` a slice no longer applies (end
  excluded); `estimated_end` on the source assertion marks an end the source called an estimate.
  A slice whose begin is after the instant is FUTURE: recorded, not applied.
* **The operative structure.** The guidance codes a closure as a SEPARATE branch beside a copy
  of the baseline's `NORMAL` availability (RWY.CLS.03; page "Usage limitation and closure
  scenarios": the copy keeps the baseline usage limitations, and a `.CLS` closure admits no
  exception), so on a `ManoeuvringAreaAvailability` / `AirportHeliportAvailability` list a
  `CLOSED` structure is operative over the `NORMAL` / `LIMITED` branches beside it, which are
  kept and listed. A `NavaidOperationalStatus` list with one structure per `signalType`
  (NAV.UNS.02 / .03, the TACAN coding) is one status PER SIGNAL, not a conflict. An
  `AirspaceActivation` list has no such rule: its structures are read as stated.
* **Schedules stay typed.** A status structure with Timesheets is `scheduled`; the resolver
  does not evaluate a Timesheet's day / time rules against the instant (the guidance itself calls
  their interpretation a human operator's task), so an `asserted_status` is set only when the
  operative structures are exactly one with a code and no timeInterval — the same rule the
  adapter applies to `Entity.status` (D48). Anything else is `scheduled` with the structures
  listed, `asserted-per-signal` with `asserted_by_signal`, or `ambiguous` when more than one
  unscheduled structure states a code and no published rule ranks them.

Nothing here reads a file, a socket or a clock.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Iterable, Literal

from synapse_cdm import times
from synapse_cdm.adapters.aixm_codec import Contract

#: The status structure each feature class states its availability / activation in, and the
#: block field the adapter types it at (the three scenario families, D43/D48). A feature outside
#: these classes (a NavaidEquipment specialisation under NAV.UNS) carries `availability` at the
#: same field (the carrying rule, D41), read here from the verbatim source.
STATUS_FIELD: dict[str, tuple[str, str, str]] = {
    "aixm:RunwayDirection": ("availability", "aixm:ManoeuvringAreaAvailability", "operationalStatus"),
    "aixm:Airspace": ("activation", "aixm:AirspaceActivation", "status"),
    "aixm:Navaid": ("availability", "aixm:NavaidOperationalStatus", "operationalStatus"),
    "aixm:AirportHeliport": ("availability", "aixm:AirportHeliportAvailability", "operationalStatus"),
}
NAVAID_EQUIPMENT_STATUS = ("availability", "aixm:NavaidOperationalStatus", "operationalStatus")

RULES = {
    "§3.6": "Temporality Concept 1.1 §3.6 / §4.4.4 — the highest correction number is the valid slice; a missing correction number reads as 0 (TS_007, TS_008)",
    "§4.4.1": "Temporality Concept 1.1 §4.4.1 — begin included, end excluded",
    "§4.4.2": "Temporality Concept 1.1 §4.4.2 — an indeterminate 'unknown' end is an open BASELINE",
    "§4.4.6.3": "Temporality Concept 1.1 §4.4.6.3 — a delta's multi-occurring property replaces the baseline's in full; one nil occurrence withdraws all",
    "§4.4.8": "Temporality Concept 1.1 §4.4.8 — an empty validTime with nilReason takes the sequence off the timeline; the record stands",
    "TS_005": "TS_005 — two slices with the same interpretation, sequence and correction conflict",
    "TS_009": "TS_009 — valid BASELINE slices do not overlap",
    "TS_011": "TS_011 — valid TEMPDELTA slices modifying the same property do not overlap; the value is undetermined when they do",
    "TS_017": "TS_017 — an active slice is corrected only in its end of validity",
    "TS_019": "TS_019 — an abandoned sequence is not reinstated by a higher correction",
    "ER-04": "Digital NOTAM Specification 2.0 (DRAFT) ATSA.ACT ER-04 / SAA.ACT ER-06 / NAV.UNS.08 / RWY.CLS.03 — the TEMPDELTA's structures replace the BASELINE's during its validity",
    "CLS": "Digital NOTAM Specification 2.0 (DRAFT) 'Usage limitation and closure scenarios' / RWY.CLS.03 — the CLOSED branch is operative over the NORMAL / LIMITED branches copied from the baseline; a .CLS closure admits no exception",
    "SIGNAL": "Digital NOTAM Specification 2.0 (DRAFT) NAV.UNS.02 / NAV.UNS.03 — a TACAN states one NavaidOperationalStatus per signalType; each is that signal's status",
}

Outcome = Literal["resolved", "unresolved", "ambiguous"]
StatusState = Literal["asserted", "asserted-per-signal", "scheduled", "withdrawn", "not stated", "unknown", "ambiguous"]
Disposition = Literal["applied", "in force", "cancelled", "expired", "future", "superseded", "conflict", "not applicable"]


class SliceRef(Contract):
    """One time slice as the resolver saw it."""

    identity: str
    gml_id: str | None = None
    interpretation: str
    sequence_number: int | None = None
    correction_number: int | None = None
    valid_time_form: str
    effective_from: str | None = None
    effective_to: str | None = None
    end_open: bool = False
    #: The Digital NOTAM binding, when the adapter typed one on the slice.
    assertion_kind: str | None = None
    event: str | None = None
    scenario: str | None = None
    #: Position of the object in the caller's list — the tie-breaker that never decides anything
    #: (it is reported, never used to prefer a slice).
    index: int


class HistoryEntry(Contract):
    """One sequence of one interpretation: its valid slice and how it stands at the instant."""

    interpretation: str
    sequence_number: int | None
    valid: SliceRef | None
    superseded: list[SliceRef] = []
    disposition: Disposition
    reason: str


class ResolvedStatus(Contract):
    """One availability / activation structure of the effective source."""

    element: str | None = None
    gml_id: str | None = None
    nil: bool = False
    code: str | None = None
    code_state: Literal["stated", "nil", "absent"] = "absent"
    scheduled: bool = False
    timesheets: int = 0
    other_properties: dict[str, str | None] = {}


class Resolution(Contract):
    """The resolved view of ONE feature at ONE instant."""

    contract: Literal["aixm-resolution/1"] = "aixm-resolution/1"
    feature: str
    feature_element: str | None = None
    as_of: str
    outcome: Outcome
    baseline: SliceRef | None = None
    applied: list[SliceRef] = []
    source_of_status: Literal["TEMPDELTA", "BASELINE", "none"] = "none"
    status_property: str | None = None
    statuses: list[ResolvedStatus] = []
    #: The structures the published rules make operative among `statuses` (all of them unless a
    #: rule ranks them: the CLOSED branch, the per-signal set).
    operative: list[ResolvedStatus] = []
    status_state: StatusState = "unknown"
    asserted_status: str | None = None
    asserted_by_signal: dict[str, str] = {}
    reasons: list[str] = []
    findings: list[str] = []
    history: list[HistoryEntry] = []
    rules_applied: list[str] = []


class EventResolution(Contract):
    """The Event feature's own state at the instant: which of its BASELINE sequences is in
    force, and whether it is active, not yet, ended or cancelled."""

    contract: Literal["aixm-event-resolution/1"] = "aixm-event-resolution/1"
    event: str
    as_of: str
    scenario: str | None = None
    scenario_version: str | None = None
    state: Literal["active", "future", "ended", "cancelled", "unresolved", "ambiguous"]
    in_force: SliceRef | None = None
    reasons: list[str] = []
    findings: list[str] = []
    history: list[HistoryEntry] = []


class ResolverError(ValueError):
    """The caller's input cannot be resolved as asked (no slice of the feature, a malformed
    object): a typed failure, never a guess."""


# ------------------------------------------------------------------------------ the reading

def _attributes(obj: Any) -> dict:
    if isinstance(obj, dict):
        attributes = obj.get("attributes")
    else:
        attributes = getattr(obj, "attributes", None)
    if not isinstance(attributes, dict) or "aixm" not in attributes:
        raise ResolverError("every object handed to the resolver is an AIXM 5.1.1 Entity carrying "
                            "attributes['aixm'] (the aixm-timeslice/1 block)")
    return attributes


def _instant(text: str | None) -> _dt.datetime | None:
    return times.parse(text) if text else None


def _as_of(value: _dt.datetime | str) -> _dt.datetime:
    try:
        instant = times.parse(value) if isinstance(value, str) else value
    except (TypeError, ValueError) as e:
        raise ResolverError(f"as_of {value!r} is not an RFC 3339 instant: {e}") from e
    if not isinstance(instant, _dt.datetime) or instant.tzinfo is None:
        raise ResolverError("as_of is an RFC 3339 instant, or an aware datetime")
    return instant


class _Slice:
    """One slice's reading, from the adapter's blocks; nothing re-parsed."""

    def __init__(self, index: int, obj: Any) -> None:
        attributes = _attributes(obj)
        self.aixm: dict = attributes["aixm"]
        self.dnotam: dict | None = attributes.get("dnotam")
        self.index = index
        ts = self.aixm["time_slice"]
        self.identifier: str = (self.aixm["feature"]["identifier"] or "").lower()
        self.element: str = self.aixm["feature"]["element"]
        self.interpretation: str = ts["interpretation"]
        self.sequence: int | None = ts["sequence_number"]
        self.correction: int | None = ts["correction_number"]
        self.valid_time: dict = ts["valid_time"]
        self.form: str = self.valid_time["form"]
        self.begin = self.end = None
        self.end_open = False
        if self.form == "period":
            self.begin = _instant((self.valid_time.get("begin") or {}).get("instant"))
            end = self.valid_time.get("end") or {}
            self.end = _instant(end.get("instant"))
            self.end_open = self.end is None and end.get("indeterminate") is not None
        elif self.form == "instant":
            self.begin = _instant((self.valid_time.get("time") or {}).get("instant"))

    @property
    def correction_rank(self) -> int:
        return self.correction if self.correction is not None else 0

    @property
    def cancelled(self) -> bool:
        return self.form in ("nil", "absent")

    def covers(self, instant: _dt.datetime) -> bool:
        if self.begin is None:
            return False
        if instant < self.begin:
            return False
        return self.end is None or instant < self.end

    def ref(self) -> SliceRef:
        d = self.dnotam or {}
        assertion = d.get("assertion") or {}
        event = None
        if d.get("role") == "affected-feature":
            reference = d.get("the_event") or {}
            event = reference.get("key") or reference.get("href")
        elif d.get("role") == "event":
            event = self.identifier
        return SliceRef(identity=f"{self.identifier}/{self.interpretation}/"
                                 f"{'-' if self.sequence is None else self.sequence}/"
                                 f"{'-' if self.correction is None else self.correction}",
                        gml_id=self.aixm["time_slice"].get("gml_id"), interpretation=self.interpretation,
                        sequence_number=self.sequence, correction_number=self.correction,
                        valid_time_form=self.form,
                        effective_from=times.render(self.begin) if self.begin else None,
                        effective_to=times.render(self.end) if self.end else None, end_open=self.end_open,
                        assertion_kind=assertion.get("kind"), event=event,
                        scenario=d.get("event_scenario") or ((d.get("scenario") or {}).get("value")),
                        index=self.index)

    def statuses(self, field: str, element: str, code_property: str) -> tuple[bool, list[ResolvedStatus]]:
        """(stated, structures): whether the slice states the property at all, and its
        structures. A slice whose list is exactly one nil item states the property WITHDRAWN
        (stated=True, structures=[] with the nil entry kept)."""
        items = self.aixm.get(field) or []
        if not items:
            return False, []
        out: list[ResolvedStatus] = []
        for item in items:
            if item.get("nil"):
                out.append(ResolvedStatus(nil=True))
                continue
            properties = item.get("properties") or {}
            code = properties.get(code_property)
            if code is None:
                # A carried structure (a NavaidEquipment's availability): read the code off the
                # verbatim source, as stated; nothing else of it is inferred.
                source = item.get("source") or {}
                raw = source.get("aixm:" + code_property)
                if isinstance(raw, dict):
                    code = {"state": "nil" if raw.get("@xsi:nil") in ("true", "1") else ("stated" if raw.get("#text") else "absent"),
                            "value": raw.get("#text")}
                elif isinstance(raw, str):
                    code = {"state": "stated", "value": raw}
                else:
                    code = {"state": "absent", "value": None}
            others = {k: (v or {}).get("value") for k, v in properties.items() if k != code_property}
            if not properties:
                source = item.get("source") or {}
                for extra in ("signalType", "warning", "activity"):
                    raw = source.get("aixm:" + extra)
                    if isinstance(raw, str):
                        others[extra] = raw
                    elif isinstance(raw, dict) and raw.get("#text"):
                        others[extra] = raw["#text"]
            out.append(ResolvedStatus(element=item.get("element") or element, gml_id=item.get("gml_id"),
                                      code=code.get("value"), code_state=code.get("state", "absent"),
                                      scheduled=bool(item.get("time_interval")),
                                      timesheets=len(item.get("time_interval") or []), other_properties=others))
        return True, out


def _slices_of(objects: Iterable[Any], identifier: str) -> list[_Slice]:
    key = identifier.strip().lower()
    out = [_Slice(i, o) for i, o in enumerate(objects)]
    return [s for s in out if s.identifier == key]


def _sequences(slices: list[_Slice], interpretation: str, findings: list[str]) -> list[tuple[_Slice | None, list[_Slice], str]]:
    """Per sequence of one interpretation: (the valid slice or None on conflict, the superseded
    corrections, a note). §3.6, TS_005, TS_019."""
    by_sequence: dict[int | None, list[_Slice]] = {}
    for s in slices:
        if s.interpretation == interpretation:
            by_sequence.setdefault(s.sequence, []).append(s)
    out = []
    for sequence in sorted(by_sequence, key=lambda k: (k is None, k or 0)):
        group = sorted(by_sequence[sequence], key=lambda s: (s.correction_rank, s.index))
        top = group[-1]
        twins = [s for s in group if s.correction_rank == top.correction_rank]
        if len(twins) > 1:
            findings.append(f"{RULES['TS_005']}: {interpretation} sequence {sequence} has {len(twins)} slices at "
                            f"correction {top.correction_rank} (objects {[s.index for s in twins]}); the sequence "
                            "is not applied")
            out.append((None, group, "conflict"))
            continue
        superseded = group[:-1]
        cancelling = [s for s in superseded if s.cancelled]
        if cancelling:
            findings.append(f"{RULES['TS_019']}: {interpretation} sequence {sequence} was taken off the timeline "
                            f"at correction {cancelling[0].correction_rank} and correction {top.correction_rank} "
                            "follows it; the later correction is still the valid slice under §3.6 and this is "
                            "reported")
        if superseded and not top.cancelled and superseded[-1].begin is not None and top.begin != superseded[-1].begin:
            findings.append(f"{RULES['TS_017']}: {interpretation} sequence {sequence} correction {top.correction_rank} "
                            f"moves the begin from {times.render(superseded[-1].begin)} to "
                            f"{times.render(top.begin) if top.begin else None}; only the end of an active slice "
                            "may be corrected")
        out.append((top, superseded, "valid"))
    return out


def _history(sequences, instant: _dt.datetime, applied: set[int]) -> list[HistoryEntry]:
    out = []
    for valid, superseded, note in sequences:
        refs = [s.ref() for s in superseded]
        if valid is None:
            first = superseded[0]
            out.append(HistoryEntry(interpretation=first.interpretation, sequence_number=first.sequence, valid=None,
                                    superseded=refs, disposition="conflict",
                                    reason="two slices claim the same correction number (TS_005)"))
            continue
        if valid.cancelled:
            disposition, reason = "cancelled", (f"the valid correction has an empty gml:validTime "
                                                f"(nilReason={valid.valid_time.get('nil_reason')!r}) — §4.4.8; "
                                                "the sequence is off the timeline and its record stands")
        elif valid.begin is None:
            disposition, reason = "not applicable", "the valid slice states no begin instant"
        elif instant < valid.begin:
            disposition, reason = "future", f"begins at {times.render(valid.begin)}, after the instant"
        elif valid.end is not None and instant >= valid.end:
            disposition, reason = "expired", f"ended at {times.render(valid.end)} (end excluded, §4.4.1)"
        elif valid.index in applied:
            disposition, reason = "applied", "covers the instant and is the effective source"
        else:
            disposition, reason = "in force", "covers the instant"
        out.append(HistoryEntry(interpretation=valid.interpretation, sequence_number=valid.sequence,
                                valid=valid.ref(), superseded=refs, disposition=disposition, reason=reason))
    return out


# ------------------------------------------------------------------------------ resolution

def resolve(objects: Iterable[Any], feature: str, as_of: _dt.datetime | str) -> Resolution:
    """The resolved availability / activation view of `feature` (its `gml:identifier`) at
    `as_of`, from the slices in `objects` and nothing else. See the module docstring for the
    rules; every one applied is named in `rules_applied`, every departure in `findings`."""
    instant = _as_of(as_of)
    objects = list(objects)
    slices = _slices_of(objects, feature)
    if not slices:
        raise ResolverError(f"no slice of feature {feature} is among the {len(objects)} object(s) handed to "
                            "the resolver; nothing is invented for a feature the caller did not pass")
    element = slices[0].element
    if element == "event:Event":
        raise ResolverError(f"{feature} is an event:Event; resolve its state with event_state(), and its "
                            "affected features with resolve()")
    field, status_element, code_property = STATUS_FIELD.get(element, NAVAID_EQUIPMENT_STATUS)
    findings: list[str] = []
    reasons: list[str] = []
    rules = ["§3.6", "§4.4.1", "§4.4.2", "§4.4.8"]
    baselines = _sequences(slices, "BASELINE", findings)
    tempdeltas = _sequences(slices, "TEMPDELTA", findings)
    permdeltas = _sequences(slices, "PERMDELTA", findings)

    covering_baselines = [v for v, _, _ in baselines if v is not None and not v.cancelled and v.covers(instant)]
    applied: set[int] = set()
    outcome: Outcome = "resolved"
    baseline: _Slice | None = None
    if len(covering_baselines) > 1:
        outcome = "ambiguous"
        rules.append("TS_009")
        findings.append(f"{RULES['TS_009']}: {len(covering_baselines)} valid BASELINE slices cover "
                        f"{times.render(instant)} ({[b.ref().identity for b in covering_baselines]})")
        reasons.append("the baseline state cannot be determined; no temporary change is applied over an "
                       "undetermined baseline")
    elif not covering_baselines:
        outcome = "unresolved"
        reasons.append(f"no valid BASELINE slice of {feature} covers {times.render(instant)}: the caller passed "
                       f"{len([b for b in baselines if b[0] is not None])} BASELINE sequence(s) of this feature "
                       "and none is in force at the instant, so the feature's state is unknown here and "
                       "nothing is invented")
    else:
        baseline = covering_baselines[0]
        applied.add(baseline.index)

    covering_deltas = [v for v, _, _ in tempdeltas if v is not None and not v.cancelled and v.covers(instant)]
    stating = [(d, *d.statuses(field, status_element, code_property)) for d in covering_deltas]
    modifying = [(d, structures) for d, stated, structures in stating if stated]
    source: Literal["TEMPDELTA", "BASELINE", "none"] = "none"
    statuses: list[ResolvedStatus] = []
    state: StatusState = "unknown"
    if outcome != "ambiguous" and len(modifying) > 1:
        outcome = "ambiguous"
        rules.append("TS_011")
        findings.append(f"{RULES['TS_011']}: {len(modifying)} valid TEMPDELTA slices cover {times.render(instant)} "
                        f"and each states {field} ({[d.ref().identity for d, _ in modifying]}); neither is applied")
        reasons.append("overlapping temporary changes to the same property: the documented rule (TS_011) "
                       "forbids them and gives no precedence, so the resolver picks none")
        state = "ambiguous"
    elif outcome == "ambiguous":
        state = "ambiguous"
    elif len(modifying) == 1:
        delta, statuses = modifying[0]
        applied.add(delta.index)
        source = "TEMPDELTA"
        rules += ["§4.4.6.3", "ER-04"]
        reasons.append(f"TEMPDELTA {delta.ref().identity} covers the instant and states {field}: its structures "
                       "replace the baseline's in full for its validity")
        if outcome == "unresolved":
            # The temporary change is known and the baseline is not: the temporary structures are
            # what the source asserts for the instant, but the feature itself is unresolved.
            reasons.append("the TEMPDELTA is applied over an UNRESOLVED baseline: what it states is known, "
                           "what it does not state is not")
    elif baseline is not None:
        stated, statuses = baseline.statuses(field, status_element, code_property)
        source = "BASELINE" if stated else "none"
        if covering_deltas:
            reasons.append(f"{len(covering_deltas)} TEMPDELTA slice(s) cover the instant and none states {field}; "
                           "the baseline's stands (§4.4.6: a delta carries only what changes)")
        if not stated:
            reasons.append(f"the BASELINE {baseline.ref().identity} states no {field}; the status is NOT STATED, "
                           "not 'available'")
    else:
        reasons.append(f"no source states {field} at the instant")

    operative: list[ResolvedStatus] = []
    asserted = None
    by_signal: dict[str, str] = {}
    if state != "ambiguous":
        state, asserted, operative, by_signal, notes = _operative(statuses, source, status_element)
        for rule, note in notes:
            rules.append(rule)
            reasons.append(note)
    history = _history(baselines, instant, applied) + _history(permdeltas, instant, applied) + _history(tempdeltas, instant, applied)
    for d, stated, _ in stating:
        if not stated and d.dnotam:
            reasons.append(f"TEMPDELTA {d.ref().identity} is bound to an Event and states no {field}; it changes "
                           "nothing the resolver reads")
    return Resolution(feature=feature.strip().lower(), feature_element=element, as_of=times.render(instant),
                      outcome=outcome, baseline=baseline.ref() if baseline else None,
                      applied=[s.ref() for s in sorted(slices, key=lambda s: s.index) if s.index in applied],
                      source_of_status=source, status_property=f"{status_element}.{code_property}",
                      statuses=statuses, operative=operative, status_state=state, asserted_status=asserted,
                      asserted_by_signal=by_signal, reasons=reasons,
                      findings=findings, history=history, rules_applied=[RULES[r] for r in dict.fromkeys(rules)])


def _operative(statuses: list[ResolvedStatus], source: str, status_element: str
               ) -> tuple[StatusState, str | None, list[ResolvedStatus], dict[str, str], list[tuple[str, str]]]:
    """(state, asserted code, operative structures, per-signal codes, (rule, note) pairs)."""
    notes: list[tuple[str, str]] = []
    if source == "none":
        return ("not stated" if statuses == [] else "unknown"), None, [], {}, notes
    stated = [s for s in statuses if not s.nil]
    if not stated:
        return ("withdrawn" if statuses else "not stated"), None, [], {}, notes
    operative = stated
    if status_element in ("aixm:ManoeuvringAreaAvailability", "aixm:AirportHeliportAvailability"):
        closed = [s for s in stated if s.code == "CLOSED"]
        if closed and len(closed) < len(stated):
            operative = closed
            notes.append(("CLS", f"the CLOSED branch is operative; the {len(stated) - len(closed)} other "
                                 f"structure(s) ({sorted({s.code or '?' for s in stated if s.code != 'CLOSED'})}) are "
                                 "the baseline limitations copied beside it and are kept, not ranked"))
    if status_element == "aixm:NavaidOperationalStatus" and len(stated) > 1:
        signals = [s.other_properties.get("signalType") for s in stated]
        if all(signals) and len(set(signals)) == len(signals):
            notes.append(("SIGNAL", "one NavaidOperationalStatus per signalType: each is that signal's status"))
            if any(s.scheduled for s in stated):
                return "scheduled", None, stated, {}, notes
            by_signal = {str(s.other_properties["signalType"]): s.code or "" for s in stated if s.code_state == "stated"}
            return "asserted-per-signal", None, stated, by_signal, notes
    if any(s.scheduled for s in operative):
        return "scheduled", None, operative, {}, notes
    coded = [s for s in operative if s.code_state == "stated"]
    if len(operative) == 1 and len(coded) == 1:
        return "asserted", coded[0].code, operative, {}, notes
    if not coded:
        state: StatusState = "not stated" if all(s.code_state == "absent" for s in operative) else "withdrawn"
        return state, None, operative, {}, notes
    return "ambiguous", None, operative, {}, notes + [("TS_011", f"{len(coded)} unscheduled structures state a "
                                                                 "code and no published rule ranks them; nothing is asserted")]


def event_state(objects: Iterable[Any], event: str, as_of: _dt.datetime | str) -> EventResolution:
    """The Event feature's own state at the instant (its BASELINE sequences under §3.6 and §4.4.8;
    the one whose period covers the instant is in force)."""
    instant = _as_of(as_of)
    slices = _slices_of(list(objects), event)
    if not slices:
        raise ResolverError(f"no slice of Event {event} is among the objects handed to the resolver")
    if slices[0].element != "event:Event":
        raise ResolverError(f"{event} is a <{slices[0].element}>, not an event:Event")
    findings: list[str] = []
    reasons: list[str] = []
    sequences = _sequences(slices, "BASELINE", findings)
    valid = [v for v, _, _ in sequences if v is not None]
    covering = [v for v in valid if not v.cancelled and v.covers(instant)]
    scenario = version = None
    for s in slices:
        d = s.dnotam or {}
        if scenario is None and (d.get("scenario") or {}).get("value"):
            scenario, version = d["scenario"]["value"], (d.get("scenario_version") or {}).get("value")
    if len(covering) > 1:
        state: str = "ambiguous"
        findings.append(f"{RULES['TS_009']}: {len(covering)} valid Event BASELINE slices cover the instant")
        in_force = None
    elif covering:
        state, in_force = "active", covering[0]
        reasons.append(f"Event BASELINE {in_force.ref().identity} covers {times.render(instant)}")
    else:
        in_force = None
        live = [v for v in valid if not v.cancelled and v.begin is not None]
        if not valid:
            state = "unresolved"
            reasons.append("the Event has no valid BASELINE slice")
        elif not live:
            state = "cancelled"
            reasons.append("every valid Event BASELINE is off the timeline (§4.4.8)")
        elif all(instant < v.begin for v in live):
            state = "future"
            reasons.append(f"the Event begins at {times.render(min(v.begin for v in live))}")
        elif all(v.end is not None and instant >= v.end for v in live):
            state = "ended"
            reasons.append(f"the Event ended at {times.render(max(v.end for v in live))} (end excluded)")
        else:
            state = "future"
            reasons.append("the instant falls between the Event's BASELINE sequences")
    applied = {in_force.index} if in_force else set()
    return EventResolution(event=event.strip().lower(), as_of=times.render(instant), scenario=scenario,
                           scenario_version=version, state=state,  # type: ignore[arg-type]
                           in_force=in_force.ref() if in_force else None, reasons=reasons, findings=findings,
                           history=_history(sequences, instant, applied))


def features_of(objects: Iterable[Any]) -> dict[str, str]:
    """Every feature identifier among the objects with its element, Events included, in first
    appearance order — what a caller iterates to resolve a whole data set."""
    out: dict[str, str] = {}
    for obj in objects:
        attributes = _attributes(obj)
        identifier = (attributes["aixm"]["feature"]["identifier"] or "").lower()
        out.setdefault(identifier, attributes["aixm"]["feature"]["element"])
    return out


__all__ = ["EventResolution", "HistoryEntry", "NAVAID_EQUIPMENT_STATUS", "RULES", "ResolvedStatus",
           "Resolution", "ResolverError", "STATUS_FIELD", "SliceRef", "event_state", "features_of", "resolve"]
