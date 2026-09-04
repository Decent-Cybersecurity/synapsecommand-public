"""STANAG 4609 / MISP-2019.1 — the UAS Datalink Local Set. KLV packets in, CDM out, and back.

Adapter #10, whose ordinal was reserved before this file existed and is now made good — see
FORMAT_COVERAGE.md, "The adapter ordinals, and the reserved-ordinal rule".

INGEST  one KLV metadata payload — one or more UAS Datalink LS packets, each `UL | BER length |
        items` — becomes an Entity + an Event per packet, in wire order. The Entity is the UAS
        platform.
EGRESS  Entities that CAME FROM this adapter become one payload, byte-exactly, including any
        length-divergent item's original octets.

Implements the row set in `FORMAT_COVERAGE.md` under "STANAG 4609 / MISP-2019.1", which was
written and reviewed as a specification across five earlier rounds before this file existed.

THE SCOPE IS THE WITNESSED SET, AND THAT IS THE WHOLE SHAPE OF THIS ADAPTER
---------------------------------------------------------------------------
`klv_uas_codec` decodes **26 items and no others**: the distinct tags the pinned stream
`fixtures/klv/streams/day_flight.klv` — SHA-256 `a810e4b6…e51`, 977 octets — actually carries. The
other 115 rows of ST 0601.14a's Table 1 still read `not yet`, and the reason is stated as a rule
rather than as a to-do: an item this repository has never met on a wire is an item whose decoder
could only ever be checked against a fixture written from the same reading of the same table.

A tag outside the 26 is **not** an error. `ST 0107.3-04` requires a decoder to "skip unknown Local
Set values so as to not impact the decoding of known Local Set items within the same Local Set
instance", so an unwitnessed tag's octets are parked at `attributes.klv_unknown_items` and its tag
number at `attributes.klv_unknown_tags`, and the packet translates.

WHAT THE PLATFORM ENTITY IS KEYED ON, WHICH IS THE HARDEST CALL IN THIS FILE
----------------------------------------------------------------------------
**Nothing in the witnessed set identifies anything.** ST 0601 carries four items that could key an
airframe — tag 3 Mission ID, tag 4 Platform Tail Number, tag 10 Platform Designation and tag 59
Platform Call Sign — plus the MIIS Core Identifier at tag 94, and the pinned stream carries **none
of the five**. The one witnessed item that looks like a name is tag 11, Image Source Sensor, and it
is disqualified BY THE BYTES rather than by argument: across the six packets its value is `'EON'`
five times and `'IR'` once, so an `entity_id` keyed on it would split one aircraft into two
entities halfway through a 3-minute clip.

So the id is **packet-scoped**, keyed on the Precision Time Stamp and the packet's index in its
payload, and it claims exactly what it can support: *this observation*. That is CAT048 settlement
9's step 2, reached a second time by a different format for the same reason — "a report with no
stated airframe identity IS a one-shot observation, and an id that says so is more honest than one
that implies continuity". **What it costs is named rather than hidden**: consecutive packets from
one aircraft get different `entity_id` values, so the continuity a real feed obviously has is a
continuity the CDM cannot express from this format. Park 11 — MISB ST 1204.1, the MIIS Core
Identifier — is what would fix it, and this round's contribution to that park is to have turned a
prediction into a measurement.

TIME: THE EPOCH IS IN A HELD DOCUMENT AND THE TIMESCALE'S NAME IS STILL PARK 3'S
--------------------------------------------------------------------------------
Tag 2 is mandatory in every packet (§6.4, §8.2, `ST 0601.14-32`) and ST 0601.14a states its epoch
on its own account, which is why `observed_at` is not blocked: §8.2.1, "This item represents time
as the number of microseconds elapsed since January 1, 1970 (1970-01-01T00:00:00Z) using an
unsigned eight (8) byte integer."

**Two things about that are carried into every object rather than smoothed over.**

* §8.2.1 also says "The Precision Time Stamp does not include leap seconds and therefore the
  Precision Time Stamp does not represent UTC", and the CDM's `Timestamp` is UTC. A count of
  seconds since 1970 that excludes leap seconds is POSIX time — which edition 1 says outright, in
  its own Table 1 note: "Derived from the POSIX IEEE 1003.1 standard" — and converting POSIX to a
  UTC calendar instant by the POSIX rule is what this adapter does, because it is the only
  conversion either document describes and `Event.observed_at` is required. The residue is a
  leap-second-boundary ambiguity, and **park 3 (MISB ST 0603.5) still owns the normative
  definition of the scale**. `attributes.time_basis` says all of this on every object.
* The stamp has **microsecond** resolution and `times.render` emits **milliseconds**, so the
  serialised timestamp is the instant truncated to a millisecond. The exact integer is parked at
  `attributes.precision_time_stamp_us`, which is the CAT021 treatment of its own high-precision
  items: "The high-precision items do not fit a CDM `Timestamp`, and that is not a defect."

`received_at` comes from the injected clock and this adapter never reads the wall clock — the seam
FORMAT_COVERAGE.md called "NAMED AND NOT BUILT" for two rounds, because "closing park 4 did not
create an adapter to hang a seam on". This is the adapter.

WHAT NEVER HAPPENS HERE: NO FUSION, NO JOINS, ELEVENTH TIME
-----------------------------------------------------------
A payload of six packets is six statements, not one platform's history. No state crosses a packet
boundary: not a position, not a sensor name, not the `ST 0601.14-34` zero-length-item ordering
rule, which is a constraint on a producer across packets and is recorded per packet instead of
policed. And nothing crosses a PAYLOAD boundary either. Tags 40/41/42 (Target Location) and
23/24/25 (Frame Center) are carried side by side and never reconciled, even where — as in the
pinned stream — they are byte-identical at every site.

THE CHECKSUM IS REAL, WHICH MAKES THIS THE FIRST BINARY ADAPTER HERE WITH AN ACTUAL INTEGRITY GATE
--------------------------------------------------------------------------------------------------
CAT021, CAT048, CAT034 and CAT023 all had to write "there is no CRC here either". ST 0601.14a §8.1
defines one, `ST 0601.14-32` makes it mandatory in every packet, and §6.6 states its range and
prints the C. `attributes.integrity_basis` records the verdict per packet, and a packet whose
checksum does not validate is **translated and flagged, not refused** — for the same reason the
length policy skips an item rather than a packet: the stored checksum is one item among 26, and
discarding 25 verified-looking items because a 16-bit sum disagrees would be destroying the
evidence a consumer needs to decide what happened.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from synapse_cdm import ids, lossless, symbology, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import klv_codec as framing
from synapse_cdm.adapters import klv_security_codec as security
from synapse_cdm.adapters import klv_uas_codec as uas
from synapse_cdm.enums import Affiliation, EntityType, EventType, PositionSource, Severity
from synapse_cdm.models import (
    CDMBase,
    Entity,
    Event,
    Kinematics,
    Position,
    SourceId,
)
from synapse_cdm.geo import Point

#: `SourceRef.system` — the covering standard, which is what this adapter is named for.
SYSTEM = "STANAG4609"

#: The `SourceId.system` for a packet-scoped identity. Deliberately NOT `SYSTEM`: a reader seeing
#: `STANAG4609` on an identifier would reasonably take it for an identifier the standard defines,
#: and this one is the adapter's own construction over items that identify nothing. The name says
#: what it is.
OBSERVATION_SYSTEM = "UAS-LS-PACKET"

#: §8.2.1: "the number of microseconds elapsed since January 1, 1970 (1970-01-01T00:00:00Z)".
EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)


class Stanag4609ParseError(ValueError):
    """A payload this adapter refuses, with the section that decides it quoted."""


# ------------------------------------------------------------------------------- the parsed twin


def parse_payload(raw: bytes) -> dict:
    """One KLV payload to its parsed form — the dict a `.parsed.json` fixture holds.

    Why the twin exists at all: the harness's lossless check harvests every leaf of a JSON fixture
    and requires each to appear somewhere in the CDM output, and a `bytes` fixture has no leaves to
    harvest, so it is reported SKIP. A binary adapter that ships only binary fixtures therefore
    ships an unrun check. Every fixture here is a pair, and `tests/test_cdm_stanag4609_adapter.py`
    asserts the two produce the same CDM.
    """
    packets = uas.decode_stream(raw)
    return {
        "payload": {"octets": len(raw), "packet_count": len(packets)},
        "packets": [_parsed_packet(index, packet, raw) for index, packet in enumerate(packets)],
    }


def _parsed_packet(index: int, packet: uas.DecodedPacket, raw: bytes) -> dict:
    return {
        "index": index,
        "at": packet.at,
        "universal_label": raw[packet.at:packet.at + framing.KEY_LENGTH].hex(),
        "value_length": packet.value_length,
        "value_length_octets": raw[packet.at + framing.KEY_LENGTH:packet.value_offset].hex(),
        "tag_order": list(packet.order),
        "item_octets": {str(tag): octets for tag, octets in sorted(packet.raw_items.items())},
        "checksum": {
            "stored": packet.checksum_stored,
            "computed": packet.checksum_computed,
            "valid": packet.checksum_valid,
        },
        "defects": [_defect_dict(defect) for defect in packet.defects],
        "advisories": [dict(advisory) for advisory in packet.advisories],
        "unknown_tags": list(packet.unknown_tags),
        "security": _security_dict(packet.security),
    }


def _security_dict(decoded) -> dict | None:
    """The ST 0102.12 set as a fixture twin states it, or None where the packet carried no item 48.

    **`None` here is the §6.5 shape and is not a value.** "The absence of Security Metadata does
    not signify Motion Imagery Data as Unclassified", so a twin for an unlabelled packet carries
    no security block at all rather than a block saying `classification: null` — which a reader
    could take for a marking that had been read and found empty.
    """
    if decoded is None:
        return None
    return {
        "element_order": list(decoded.order),
        "element_octets": {str(tag): octets
                           for tag, octets in sorted(decoded.raw_elements.items())},
        "required_present": list(decoded.required_present),
        "required_absent": list(decoded.required_absent),
        "partial": decoded.is_partial,
        "refusals": [_refusal_dict(refusal) for refusal in decoded.refusals],
        "advisories": [dict(advisory) for advisory in decoded.advisories],
        "unlisted_tags": list(decoded.unlisted_tags),
    }


def _refusal_dict(refusal: security.RefusedElement) -> dict:
    return {
        "tag": refusal.tag,
        "name": refusal.name,
        "class": refusal.refusal_class,
        "observed_length": refusal.observed_length,
        "stated_length": refusal.stated_length,
        "presence": refusal.presence,
        "octets": refusal.octets,
        "tag_offset": refusal.tag_offset,
        "value_offset": refusal.value_offset,
        "section": refusal.section,
        "clause": refusal.clause,
    }


def _defect_dict(defect: uas.LengthDivergence) -> dict:
    return {
        "tag": defect.tag,
        "name": defect.name,
        "class": defect.divergence_class,
        "observed_length": defect.observed_length,
        "required_length": defect.required_length,
        "max_length": defect.max_length,
        "tag_offset": defect.tag_offset,
        "value_offset": defect.value_offset,
        "octets": defect.octets,
        "section": f"ST 0601.14a §{defect.section}",
        "policy": defect.policy,
        "factual_basis": defect.factual_basis,
        "normative_basis": defect.normative_basis,
    }


def _rendered(value: Any) -> Any:
    """A decoded item value in a form JSON and the golden files can hold."""
    if isinstance(value, uas.SpecialValue):
        return {"special_value": value.label, "klv_integer": value.integer,
                "basis": ("ST 0601.14a states this integer in the item's own Special Values "
                          "cell, so it is a signal and not a measurement — running the item's "
                          "affine map over it would produce a plausible-looking number")}
    if isinstance(value, uas.ZeroLength):
        return {"zero_length_item": True, "basis": value.basis}
    return value


def _measured(value: Any) -> float | int | None:
    """The value when it is a number this adapter may put in a canonical field, else None.

    A `SpecialValue` and a `ZeroLength` both return None, which is what keeps a "Reserved"
    latitude out of `Position.lat` and a zero-length ground speed out of `Kinematics.speed_mps`.
    """
    if isinstance(value, (uas.SpecialValue, uas.ZeroLength)):
        return None
    if isinstance(value, str):
        return None
    return value


def _octets_from_parsed(packet: dict) -> bytes:
    """Rebuild one packet's exact octets from its parsed form.

    THE PARSED PATH AND THE BYTES PATH ARE THE SAME PATH, BY CONSTRUCTION. The alternative was to
    translate a parsed dict field by field, which is a second implementation of the same mapping
    and the place `stanag4676.py` had to add a twin test to catch drift. Here the parsed form
    carries the Universal Label, the BER length octets and every item's Value octets verbatim, so
    the honest thing is to reassemble the packet and hand it to the same decoder — which makes the
    twin equality a theorem rather than an assertion.

    It also makes the parsed form CHECKABLE: the reassembled packet's own declared Value length has
    to agree with the `value_length` the fixture states, and a hand-edited fixture that says
    otherwise fails here rather than translating into a plausible object.
    """
    label = bytes.fromhex(packet["universal_label"])
    if label != framing.UAS_LOCAL_SET_KEY:
        raise Stanag4609ParseError(
            f"parsed packet {packet.get('index')} states a Universal Label of {label.hex()} and "
            f"ST 0601.14a §6.2 registers {framing.UAS_LOCAL_SET_KEY.hex()}"
        )
    octets = {int(tag): bytes.fromhex(value)
              for tag, value in (packet.get("item_octets") or {}).items()}
    order = [int(tag) for tag in packet.get("tag_order") or sorted(octets)]
    missing = [tag for tag in order if tag not in octets]
    if missing:
        raise Stanag4609ParseError(
            f"parsed packet {packet.get('index')} lists tag(s) {missing} in tag_order and gives no "
            "item_octets for them — the parsed form has to carry every item's Value verbatim, "
            "because that is what makes it the same payload as the binary twin"
        )
    body = b"".join(framing.encode_ber_oid(tag) + framing.encode_ber_length(len(octets[tag]))
                    + octets[tag] for tag in order)
    stated = packet.get("value_length")
    if stated is not None and stated != len(body):
        raise Stanag4609ParseError(
            f"parsed packet {packet.get('index')} declares a Value length of {stated} and its own "
            f"items occupy {len(body)} octets"
        )
    return framing.UAS_LOCAL_SET_KEY + framing.encode_ber_length(len(body)) + body


class Stanag4609Adapter(Adapter):
    """UAS Datalink LS payloads in, CDM out; CDM back out to a payload, byte-exactly."""

    name = "stanag4609"
    version = "1.0.0"
    direction = "bidirectional"
    system = SYSTEM

    #: `fixtures/klv`, not `fixtures/stanag4609`. The `stanag4676` → `nits` split reached a second
    #: time and in the same direction: an adapter named after a STANDARD is named for a covering
    #: document, and the fixture directory is named for the bytes it holds. `klv_pin.json` recorded
    #: both names five rounds before this file existed and neither moved.
    fixture_dir = "klv"

    #: EMPTY, the claim four sibling adapters already make. A declared transform is an EXEMPTION
    #: from the never-drop check and this adapter needs none: every item's Value octets are parked
    #: verbatim at `attributes.klv_item_octets` as well as decoded, the raw KLV integer rides beside
    #: every converted figure in `payload.items`, and the whole parsed packet lands at
    #: `attributes.source_extras`. So `lossless.unrepresented()` runs at full strength with nothing
    #: excused — including over the length-divergent item, whose octets are the only thing this
    #: adapter has for it.
    TRANSFORMS: dict[str, str] = {}

    #: Dotted paths in a parsed PACKET this adapter re-emits under a name of its own. Short by
    #: design: the decoded values are parked wholesale and the canonical fields are additions on
    #: top, so consuming a mapped path would DELETE the evidence rather than move it.
    CONSUMED = ("index", "universal_label", "value_length_octets", "tag_order", "item_octets")

    # ------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One payload -> [Entity, Event] per packet, in wire order.

        Several packets in one payload are several STATEMENTS about a platform at several instants,
        not one accumulated state. Assembling that state is the accumulation this adapter refuses,
        and the CDM makes it expressible for a consumer rather than performing it here — the CAT034
        ruling, reached by a format whose records really are consecutive samples of one thing.
        """
        packets, parsed, payload = self._packets(raw)
        received_at = self.now()
        source = self.source_ref()
        objects: list[CDMBase] = []
        for index, (packet, parsed_packet) in enumerate(zip(packets, parsed)):
            entity, event = self._translate(index, packet, parsed_packet, payload,
                                            received_at, source)
            objects.extend((entity, event))
        return objects

    def _packets(self, raw: bytes | dict
                 ) -> tuple[list[uas.DecodedPacket], list[dict], dict]:
        if isinstance(raw, (bytes, bytearray)):
            buf = bytes(raw)
            packets = uas.decode_stream(buf)
            return (packets, [_parsed_packet(i, p, buf) for i, p in enumerate(packets)],
                    {"octets": len(buf), "packet_count": len(packets)})
        if isinstance(raw, dict):
            entries = raw.get("packets")
            if not isinstance(entries, list) or not entries:
                raise Stanag4609ParseError(
                    "a parsed STANAG 4609 payload holds a non-empty 'packets' list; top-level "
                    f"keys: {sorted(raw)}"
                )
            buf = b"".join(_octets_from_parsed(entry) for entry in entries)
            packets = uas.decode_stream(buf)
            for entry, packet in zip(entries, packets):
                self._agree(entry, packet)
            stated = raw.get("payload") or {}
            if stated.get("octets") not in (None, len(buf)):
                raise Stanag4609ParseError(
                    f"the parsed payload declares {stated['octets']} octets and its own packets "
                    f"reassemble to {len(buf)}"
                )
            if stated.get("packet_count") not in (None, len(packets)):
                raise Stanag4609ParseError(
                    f"the parsed payload declares {stated['packet_count']} packet(s) and carries "
                    f"{len(packets)}"
                )
            return (packets, [_parsed_packet(i, p, buf) for i, p in enumerate(packets)],
                    {"octets": len(buf), "packet_count": len(packets)})
        raise Stanag4609ParseError(
            "a STANAG 4609 payload is a KLV byte string or its parsed twin (dict), got "
            f"{type(raw).__name__}"
        )

    def _agree(self, entry: dict, packet: uas.DecodedPacket) -> None:
        """The parsed form states the checksum and the defects; the decoder re-derives both.

        Two independent statements of one fact, each checkable against the other — the pin gate's
        arrangement, applied to a fixture. A fixture whose stated verdict disagrees with what its
        own octets produce is a fixture that would otherwise teach a golden file a falsehood.
        """
        stated = entry.get("checksum") or {}
        if "computed" in stated and stated["computed"] != packet.checksum_computed:
            raise Stanag4609ParseError(
                f"parsed packet {entry.get('index')} states a computed checksum of "
                f"{stated['computed']} and its own octets sum to {packet.checksum_computed} by "
                "ST 0601.14a §6.6"
            )
        stated_defects = sorted((d["tag"], d["class"]) for d in entry.get("defects") or [])
        derived = sorted((d.tag, d.divergence_class) for d in packet.defects)
        if stated_defects != derived:
            raise Stanag4609ParseError(
                f"parsed packet {entry.get('index')} states length defects {stated_defects} and "
                f"the length policy derives {derived} from its own octets"
            )
        # THE SAME ARRANGEMENT FOR THE NESTED SET, AND THE ABSENCE IS PART OF THE CLAIM. A twin
        # stating a security block for a packet with no item 48 — or omitting one for a packet
        # that carries it — is a twin that would teach a golden file that a marking was or was not
        # there. §6.5 makes that the one error in this format nobody may make quietly.
        stated_security = entry.get("security")
        if (stated_security is None) != (packet.security is None):
            raise Stanag4609ParseError(
                f"parsed packet {entry.get('index')} "
                f"{'states' if stated_security is not None else 'states no'} ST 0102.12 security "
                f"metadata and its own octets "
                f"{'carry' if packet.security is not None else 'carry no'} ST 0601 item 48. "
                "MISB ST 0102.12 §6.5: 'The absence of Security Metadata does not signify Motion "
                "Imagery Data as Unclassified' — so which of the two it is, is a claim"
            )
        if stated_security is not None:
            stated_order = list(stated_security.get("element_order") or [])
            derived_order = list(packet.security.order)
            if stated_order != derived_order:
                raise Stanag4609ParseError(
                    f"parsed packet {entry.get('index')} states ST 0102.12 elements "
                    f"{stated_order} and its own item 48 octets carry {derived_order}"
                )

    # ------------------------------------------------------------------ translation

    def _translate(self, index: int, packet: uas.DecodedPacket, parsed: dict, payload: dict,
                   received_at: _dt.datetime, source: Any) -> tuple[Entity, Event]:
        items = packet.items
        unavailable: list[str] = []

        observed_at, stamp_us, time_basis = self._observed_at(index, items)
        external_id = f"{stamp_us}|{index}"
        entity_id = ids.derive(OBSERVATION_SYSTEM, external_id, kind="entity")
        source_ids = [SourceId(system=OBSERVATION_SYSTEM, external_id=external_id)]

        position, position_basis = self._position(items, unavailable)
        kinematics, kinematics_basis = self._kinematics(items, unavailable)
        geometry, geometry_basis = self._frame_centre(items)

        attributes = self._attributes(index, packet, parsed, payload, external_id, time_basis,
                                      position_basis, kinematics_basis, unavailable)
        entity = Entity(
            source=source,
            source_ids=source_ids,
            entity_id=entity_id,
            # PLATFORM, from the standard's own subject rather than from any item — the CAT034
            # ruling in a second format. §1: "MISB ST 0601 defines the Unmanned Air System (UAS)
            # Datalink Local Set (LS) for UAS platforms. The UAS Datalink LS is typically produced
            # on-board a UAS airborne platform". Tag 10 Platform Designation is the item that would
            # say WHAT platform and it is not in the witnessed set, so the type is the format's and
            # the model is nobody's.
            entity_type=EntityType.PLATFORM,
            # UNKNOWN, always. Nothing in the witnessed set states an allegiance, and ST 0601
            # carries no item that does — the standard describes one's own aircraft to one's own
            # ground station, which is a context in which the question does not arise on the wire.
            affiliation=Affiliation.UNKNOWN,
            symbol=symbology.sidc_from_affiliation(Affiliation.UNKNOWN,
                                                   synthetic=self._synthetic),
            position=position,
            kinematics=kinematics,
            attributes=attributes,
            valid_from=observed_at,
            # None on every packet. A UAS LS packet states an instant and never an interval, and
            # `ST 0601.13-26` — "Metadata items which have not been updated within a thirty (30)
            # second period shall be considered Unknown" — is a rule about ITEM staleness for a
            # consumer holding a sequence, not an expiry the emitter declares for this state. Using
            # it as `valid_to` would put a horizon on the wire that the wire does not carry.
            valid_to=None,
            # None. ST 0601.14a carries error estimates at tags 45 and 46 and a full standard-
            # deviation pack at tag 102, and not one of them is a 0..1 assessment of identity —
            # and none of the three is in the witnessed set anyway.
            confidence=None,
        )
        event = Event(
            source=source,
            source_ids=source_ids,
            event_id=ids.derive(OBSERVATION_SYSTEM, external_id, kind="event"),
            # STATUS_CHANGE. The witnessed set is a periodic report of a platform and its sensor's
            # own state, which is the CAT034 shape: the object of the report is the reporting thing.
            # DETECTION is deliberately NOT used — nothing in these 26 items detects anything, and
            # the item that would (tag 74, the VMTI Local Set) is park 6.
            event_type=EventType.STATUS_CHANGE,
            # INFO on every packet. Nothing in the witnessed set is an emergency or an alert
            # declaration. Tag 47 Generic Flag Data carries the standard's own condition bits and
            # is not witnessed; when it lands, it is what would raise this.
            severity=Severity.INFO,
            related_entities=[entity_id],
            geometry=geometry,
            payload=self._payload(index, packet, payload, geometry_basis, time_basis),
            observed_at=observed_at,
            received_at=received_at,
        )
        return entity, event

    # ------------------------------------------------------------------ time

    def _observed_at(self, index: int,
                     items: dict[int, uas.DecodedItem]) -> tuple[_dt.datetime, int, dict]:
        """Tag 2 to an instant. A packet without a usable one is REFUSED, quoting the value."""
        entry = items.get(2)
        value = _measured(entry.value) if entry is not None else None
        if value is None:
            raise Stanag4609ParseError(
                f"packet {index} carries no usable Precision Time Stamp (tag 2): "
                + ("the item is absent" if entry is None else f"its value is {entry.value!r}")
                + ". ST 0601.14a §6.4: 'Every UAS Datalink LS packet is required to include a "
                "Precision Time Stamp representing absolute time as defined in MISB ST 0603', and "
                "ST 0601.14-32 forbids a Zero-Length Item for it. Event.observed_at is required "
                "and there is nothing else in the Local Set to read it from — the NITS baseTime "
                "refusal reached a second time"
            )
        stamp_us = int(value)
        observed_at = EPOCH + _dt.timedelta(microseconds=stamp_us)
        basis = {
            "item": "tag 2 Precision Time Stamp",
            "raw_microseconds": stamp_us,
            "epoch": (
                "1970-01-01T00:00:00Z, read from ST 0601.14a §8.2.1: 'This item represents time as "
                "the number of microseconds elapsed since January 1, 1970 (1970-01-01T00:00:00Z) "
                "using an unsigned eight (8) byte integer.' The epoch is in a HELD document, which "
                "is why this field is filled at all — the profile MISP-2019.1 states none"),
            "timescale": (
                "NOT UTC, on the document's own statement: §8.2.1, 'The Precision Time Stamp does "
                "not include leap seconds and therefore the Precision Time Stamp does not "
                "represent UTC.' A count of seconds since 1970 that excludes leap seconds is POSIX "
                "time, which is what EDITION 1 calls it in its own Table 1 note — 'Derived from "
                "the POSIX IEEE 1003.1 standard' — and this adapter converts by the POSIX rule "
                "because it is the only conversion either held document describes and "
                "Event.observed_at is required. The residue is an ambiguity at a leap-second "
                "boundary and it is NOT resolved here: park 3, MISB ST 0603.5, owns the normative "
                "definition of the MISP Time System and of what to CALL this scale"),
            "precision": (
                "the stamp is microseconds and times.render emits milliseconds, so the serialised "
                "timestamp is this instant truncated to a millisecond. The exact integer is at "
                "attributes.precision_time_stamp_us — the CAT021 treatment of its own "
                "high-precision items, where the mismatch is named as a mismatch and not as a "
                "defect"),
            "received_at": (
                "the injected clock, never the wall clock. FORMAT_COVERAGE.md called this seam "
                "'NAMED AND NOT BUILT' for two rounds because closing park 4 created no adapter "
                "to hang it on"),
        }
        return observed_at, stamp_us, basis

    # ------------------------------------------------------------------ position

    def _position(self, items: dict[int, uas.DecodedItem],
                  unavailable: list[str]) -> tuple[Position | None, dict]:
        """Tags 13 and 14, both or neither. `alt_m` is None on every object and tag 15 is why."""
        lat = _measured(items[13].value) if 13 in items else None
        lon = _measured(items[14].value) if 14 in items else None
        basis: dict[str, Any] = {
            "lat_item": "tag 13 Sensor Latitude" if lat is not None else None,
            "lon_item": "tag 14 Sensor Longitude" if lon is not None else None,
            "datum": (
                "WGS 84, and the packet says so about itself: tag 12 Image Coordinate System "
                "carries the name of the datum every geographic angle in the Local Set is "
                "expressed in — §8.12.1 lists the items it governs, 13 and 14 among them — and "
                "§8.13's own bullet says 'Based on WGS84 ellipsoid'. Two statements, one datum, "
                "and the CDM's Position is WGS 84 as well, so there is no transform here at all"),
            "what_this_position_IS": (
                "the SENSOR's location, on an entity whose type is PLATFORM, and the document is "
                "what licenses the join: §8.13.1, 'In a realized system, this item accounts for "
                "the lever arm distance between a platform's GPS antenna (or known central "
                "platform position) to a sensor's general location (like the center of a gimbaled "
                "sensor).' So it is the platform's position adjusted by a lever arm on the same "
                "airframe, not a second object's fix. Tag 67 Alternate Platform Latitude is the "
                "item that would state a platform position separately and it is NOT in the "
                "witnessed set — so this is named rather than smoothed over: to within one "
                "airframe's dimensions, this IS where the platform is, and the residue is a "
                "distance the document declines to state"),
            "alt_m": (
                "None on EVERY object, and this is a decline rather than an absence. Tag 15 Sensor "
                "True Altitude is witnessed and is measured 'from Mean Sea Level (MSL)' (§8.15), "
                "while Position.alt_m is documented as 'Metres HAE' — so the one altitude in the "
                "witnessed set cannot fill the one altitude field. §8.15 itself points at the "
                "twin: 'For improved modeling accuracy use Sensor Ellipsoid Height (Tag 75) or "
                "Sensor Ellipsoid Height Extended (Tag 104)', and `ST 0601.8-17` settles the "
                "collision in the same direction — a decoder that understands HAE 'shall use the "
                "HAE representation and ignore the Mean Sea Level (MSL) representation when both "
                "exist'. Neither 75 nor 104 is witnessed. The MSL figure is parked at "
                "attributes.sensor_true_altitude_msl_m, converting nothing: a geoid separation is "
                "a model this repository does not hold"),
            "accuracy_m": (
                "None on every object. ST 0601.14a carries CE90/LE90 error estimates at tags 45 "
                "and 46 and a Standard Deviation Cross Correlation pack at tag 102, and none of "
                "the three is in the witnessed set. The item's stated Resolution — '~42 nano "
                "degrees' for tag 13 — is a QUANTISATION STEP and not an accuracy, and writing it "
                "here would claim the platform knows where it is to within millimetres. The "
                "CAT034 quantisation note, reached a second time"),
        }
        if lat is None or lon is None:
            unavailable.append(
                "Position (tag 13 and/or tag 14 absent or reserved — an absent Position is the "
                "honest statement, never a Position holding zeros)")
            basis["reason"] = (
                "no Position is emitted: a Position needs both angles and this packet does not "
                "carry both as measurements. A Position holding a zero for the missing half is a "
                "real point in the Gulf of Guinea")
            return None, basis
        basis["position_source"] = (
            "GNSS, and the enum has no member that says what the document says. §8.13.1: "
            "'Generated from GPS/INS information and based on the WGS84 coordinate system.' "
            "PositionSource offers GNSS, INERTIAL, MANUAL and ESTIMATED, and a GPS/INS blend is "
            "none of them exactly — GNSS is the member naming the source the document names "
            "first, and ESTIMATED would understate a fix that really is a satellite solution. "
            "The blend is recorded here rather than resolved")
        return Position(
            lat=lat, lon=lon, alt_m=None,
            position_source=PositionSource.GNSS,
            accuracy_m=None,
        ), basis

    # ------------------------------------------------------------------ kinematics

    def _kinematics(self, items: dict[int, uas.DecodedItem],
                    unavailable: list[str]) -> tuple[Kinematics | None, dict]:
        """Tag 56 fills `speed_mps`. Tag 5 is a HEADING and fills nothing."""
        speed = _measured(items[56].value) if 56 in items else None
        basis: dict[str, Any] = {
            "speed_item": "tag 56 Platform Ground Speed" if speed is not None else None,
            "speed_basis": (
                "§8.56, 'Speed projected to the ground of an airborne platform passing "
                "overhead', Units Meters/Second, KLV format uint8 over 0..255 with the "
                "Software format also uint8 — so the document's own formula is the identity "
                "`KLV = Soft` and there is no conversion to get wrong. A speed over GROUND, "
                "which is what Kinematics.speed_mps documents itself as, so this is the one "
                "kinematic figure in the witnessed set that lands without an argument"),
            "course_deg": (
                "None on EVERY object, and tag 5 is the temptation. Tag 5 is the Platform HEADING "
                "Angle — §8.5, 'the angle between longitudinal axis (line made by the fuselage) "
                "and true north' — and Kinematics.course_deg is documented as a COURSE, which is "
                "the direction of travel. On an aircraft in wind those differ by the drift angle, "
                "and the standard itself keeps them apart: tag 112 is the Platform Course Angle "
                "and it is NOT in the witnessed set. So the heading parks at "
                "attributes.platform_heading_deg and course_deg stays None. The AIS heading/course "
                "distinction, reached by an airborne format"),
            "climb_mps": (
                "None on every object. Tag 51 Platform Vertical Speed is the item and it is not "
                "in the witnessed set; deriving a climb rate from two packets' altitudes would be "
                "differentiating across records, which is the accumulation this adapter refuses"),
        }
        if speed is None:
            unavailable.append("Kinematics (tag 56 absent or zero-length)")
            return None, basis
        return Kinematics(speed_mps=float(speed), course_deg=None, climb_mps=None), basis

    # ------------------------------------------------------------------ geometry

    def _frame_centre(self, items: dict[int, uas.DecodedItem]) -> tuple[Point | None, dict]:
        """`Event.geometry` is the frame centre, and never the target location."""
        lat = _measured(items[23].value) if 23 in items else None
        lon = _measured(items[24].value) if 24 in items else None
        basis: dict[str, Any] = {
            "items": ["tag 23 Frame Center Latitude", "tag 24 Frame Center Longitude"],
            "why_frame_centre_and_not_target_location": (
                "tags 40 and 41 carry the Target Location and §8.40 makes them CONDITIONAL on "
                "their own face — 'This is the crosshair location if different from frame "
                "center' — while the frame centre is stated unconditionally as the geometric "
                "centre of the imagery this packet's metadata describes. Choosing between them "
                "per packet, on whether they happen to differ, would be this adapter deciding "
                "which point the operator meant. So the frame centre is the geometry and the "
                "target location is carried in the payload beside it, both verbatim, neither "
                "reconciled. In the pinned stream they are BYTE-IDENTICAL at all six sites, "
                "which is the emitter reporting them as not different — and is exactly the case "
                "where a merge would look free and would still be a merge"),
            "elevation": (
                "2-D, [lon, lat], and the third element is deliberately absent. Tag 25 Frame "
                "Center Elevation is witnessed and is 'Terrain elevation at frame center relative "
                "to Mean Sea Level (MSL)' — the same MSL-against-HAE decline Position.alt_m "
                "carries, in a field that would not even be labelled. Parked at "
                "payload.frame_centre.elevation_msl_m"),
        }
        if lat is None or lon is None:
            basis["reason"] = (
                "no geometry: tag 23 and/or 24 is absent or carries the '0x80000000 = \"N/A "
                "(Off-Earth)\"' signal §8.23 declares, which is the document saying the frame "
                "centre is not on the earth's surface. A Point built over that signal would be a "
                "position at the south pole")
            return None, basis
        return Point(coordinates=[lon, lat]), basis

    # ------------------------------------------------------------------ attributes

    def _attributes(self, index: int, packet: uas.DecodedPacket, parsed: dict, payload: dict,
                    external_id: str, time_basis: dict, position_basis: dict,
                    kinematics_basis: dict, unavailable: list[str]) -> dict:
        items = packet.items
        attributes: dict[str, Any] = {}

        attributes["klv_payload"] = dict(payload)
        attributes["klv_packet"] = {
            "index": index,
            "offset": packet.at,
            "value_length": packet.value_length,
            "value_length_octets": parsed.get("value_length_octets"),
            "item_count": len(packet.order),
            "universal_label": framing.UAS_LOCAL_SET_KEY.hex(),
            "universal_label_crc": framing.UAS_LOCAL_SET_KEY_CRC,
        }
        attributes["klv_item_octets"] = {str(tag): octets
                                         for tag, octets in sorted(packet.raw_items.items())}
        attributes["klv_tag_order"] = list(packet.order)
        attributes["klv_unknown_tags"] = list(packet.unknown_tags)
        attributes["klv_unknown_items"] = {
            str(tag): packet.raw_items[tag] for tag in packet.unknown_tags}
        if packet.unknown_tags:
            attributes["klv_unknown_basis"] = (
                "tags outside the 26 the pinned stream attests. NOT an error and not dropped: "
                "`ST 0107.3-04` requires a decoder to 'skip unknown Local Set values so as to not "
                "impact the decoding of known Local Set items within the same Local Set instance', "
                "and the octets are above. What this adapter declines is to say what they MEAN, "
                "because a decoder for an item nobody here has seen on a wire could only be "
                "checked against a fixture written from the same reading of the same table")

        attributes["identity_basis"] = (
            f"uuid5 over ({OBSERVATION_SYSTEM}, {external_id!r}) — the Precision Time Stamp and "
            "the packet's index in its payload. PACKET-SCOPED, and it claims exactly that: THIS "
            "OBSERVATION. Nothing in the witnessed set identifies anything — tag 3 Mission ID, tag "
            "4 Platform Tail Number, tag 10 Platform Designation, tag 59 Platform Call Sign and "
            "tag 94's MIIS Core Identifier are the five items that would, and the pinned stream "
            "carries none of them. Tag 11 Image Source Sensor is the one witnessed item that looks "
            "like a name and it is disqualified BY THE BYTES: it reads 'EON' in five of the six "
            "packets and 'IR' in the sixth, so keying on it would split one aircraft into two "
            "entities inside a three-minute clip. WHAT THIS COSTS, stated rather than hidden: "
            "consecutive packets from one platform get DIFFERENT entity_id values, so the "
            "continuity a real feed has is continuity the CDM cannot express from this format. "
            "Park 11 — MISB ST 1204.1, the MIIS Core Identifier — is what closes it, and reading "
            "the stream turned that park from a prediction into a measurement")
        attributes["entity_type_basis"] = (
            "PLATFORM, from the standard's own subject rather than from any item. §1: 'MISB ST "
            "0601 defines the Unmanned Air System (UAS) Datalink Local Set (LS) for UAS platforms. "
            "The UAS Datalink LS is typically produced on-board a UAS airborne platform'. Tag 10 "
            "Platform Designation is the item that would say WHICH platform and it is not in the "
            "witnessed set, so the type is the format's and the model is nobody's — the CAT034 "
            "reading, where the object's type is a property of the format")
        attributes["affiliation_basis"] = (
            "UNKNOWN, always, and here it is barely a decision: ST 0601.14a carries no item "
            "stating an allegiance at all. A UAS Datalink LS describes one's own aircraft to one's "
            "own ground station, which is a context in which the question does not arise on the "
            "wire — and inferring FRIENDLY from that context would be this adapter reasoning about "
            "who deployed the sensor")
        attributes["symbol_basis"] = (
            "derived from the affiliation through symbology.sidc_from_affiliation, so every "
            "STANAG 4609 platform is an UNKNOWN glyph. ST 0601.14a carries no symbology of any "
            "kind; tag 63 Sensor Field of View Name is the nearest thing to a rendering hint and "
            "it names a lens, not an icon")
        attributes["integrity_basis"] = self._integrity_basis(packet)
        attributes["time_basis"] = time_basis
        attributes["precision_time_stamp_us"] = time_basis["raw_microseconds"]
        attributes["position_basis"] = position_basis
        attributes["kinematics_basis"] = kinematics_basis

        attributes["security_metadata_basis"] = self._security_basis(packet)
        if packet.security is not None:
            attributes["security_metadata"] = self._security_metadata(packet.security)

        attributes["length_divergence_policy"] = {
            "policy": uas.LENGTH_DIVERGENCE_POLICY,
            "stated_on_every_object": (
                "the policy rides on every object and not only on the ones that tripped it, "
                "because a consumer needs to know that a clean object is clean UNDER A RULE and "
                "not merely unflagged"),
            "defects": [_defect_dict(defect) for defect in packet.defects],
            "advisories": [dict(advisory) for advisory in packet.advisories],
        }

        parked = {}
        for tag, entry in sorted(items.items()):
            spec = uas.ITEMS[tag]
            parked[str(tag)] = {
                "name": spec.name,
                "value": _rendered(entry.value),
                "units": spec.units,
                "klv_format": spec.klv_format,
                "octets": entry.raw.hex(),
                "section": f"ST 0601.14a §{spec.section}",
            }
        attributes["klv_items"] = parked

        if 15 in items:
            attributes["sensor_true_altitude_msl_m"] = _rendered(items[15].value)
        if 5 in items:
            attributes["platform_heading_deg"] = _rendered(items[5].value)
        if 65 in items:
            attributes["uas_ls_version_number"] = {
                "value": _rendered(items[65].value),
                "basis": (
                    "§8.65: '1..255 corresponds to document revisions MISB ST 0601.1 thru MISB ST "
                    "0601.255'. Carried and NOT trusted as provenance, and register entry KLV 15 "
                    "is why: there is no MISB ST 0601.1 — edition 1 was published as MISB EG "
                    "0601.1, an Engineering Guideline, and the standard has renamed its own "
                    "history. Edition 1's own §7.65.1 adds that the item 'is not required in every "
                    "packet of metadata', so at the edition a value of 1 declares, the stamp was "
                    "OPTIONAL; `ST 0601.8-12` made it mandatory"),
            }
        attributes["unavailable_fields"] = sorted(unavailable)
        attributes["source_extras"] = lossless.residual(parsed, self.CONSUMED)
        return attributes

    # ------------------------------------------------ ST 0102.12 security metadata, item 48

    def _security_basis(self, packet: uas.DecodedPacket) -> dict:
        """What this object says about its own security marking, in every case including absence.

        **THE STANDING CONFIDENTIALITY RULING, WHICH IS WHY THIS METHOD IS SHAPED THE WAY IT IS.**
        A classification is CARRIED AND NEVER INVENTED — the NITS precedent, reached here by a
        second format. So there are exactly two things this adapter can say about a packet's
        classification: what the packet's own item 48 stated, or that the packet stated nothing.
        There is no third branch and in particular no default.

        **§6.5 IS WHAT MAKES THE ABSENT CASE A STATEMENT RATHER THAN A GAP.** "The absence of
        Security Metadata does not signify Motion Imagery Data as Unclassified." A packet with no
        item 48 is UNLABELLED. Unlabelled is not a value of a field, so no classification field is
        emitted for it — and the document's own sentence is, so that a consumer reading the object
        meets ST 0102.12's statement of what the absence does not mean instead of supplying one.
        """
        basis: dict[str, Any] = {
            "carried_in": "ST 0601 item 48, Security Local Set",
            "carrier_basis": uas.NESTED_SET_BASIS,
            "element_layer": security.SOURCE_ST_0102_12,
            "confidentiality_ruling": (
                "CARRIED AND NEVER INVENTED. Every value below is an octet the packet sent, "
                "decoded by a rule this repository can cite in a held document, or it is absent. "
                "No marking is defaulted, inferred from context, completed from a partial set, or "
                "converted to a nearest listed value. Where the CDM has no field for a security "
                "element it goes into Entity.attributes AS THE DOCUMENT NAMES IT — which is why "
                "the keys below are ST 0102.12's element names and not a CDM vocabulary"),
            "external_code_lists": security.EXTERNAL_CODE_LISTS_NOT_HELD,
            "st_336_conformance": security.ST_336_CONFORMANCE,
            "repetition_rate": security.REPETITION_RATE,
        }
        if packet.security is None:
            basis["state"] = "UNLABELLED — this packet carried no ST 0601 item 48"
            basis["absence"] = security.ABSENCE_OF_SETS
            basis["what_is_NOT_emitted"] = (
                "no classification, no country code, no coding method, no version. NOT 'null "
                "meaning unclassified' and not an empty security_metadata object: attributes "
                "carries NO security_metadata key at all for this packet, because a key present "
                "with empty contents is a reader's invitation to treat emptiness as a value. "
                "§6.3 is the contrast that makes this precise — an unclassified packet is a "
                "MARKED packet whose Security Classification octet is 0x01, so 'unclassified' and "
                "'unlabelled' are two different states and this is the second one")
            basis["what_the_document_asks_of_a_consumer"] = (
                "§6.5: 'Bit stream originators and system developers are responsible to "
                "incorporate continual checks for Security Metadata in their applications.' This "
                "adapter performs that check per packet and reports its result; deciding what to "
                "do about an unlabelled packet is the consumer's, and it is a decision this "
                "object gives them the evidence to make rather than one made here")
            return basis
        decoded = packet.security
        basis["state"] = (
            "PARTIAL — the set is present and does not carry every element §6.7 marks Required"
            if decoded.is_partial else
            "COMPLETE-ON-REQUIRED — the set carries all six elements §6.7 marks Required")
        basis["partial_sets"] = security.PARTIAL_SETS
        basis["required_present"] = list(decoded.required_present)
        basis["required_absent"] = list(decoded.required_absent)
        basis["absence_clause_still_applies"] = (
            "§6.5 governs the ELEMENTS this set does not carry as well as the sets a packet does "
            "not carry: an absent Security Classification inside a present set is unlabelled and "
            "not unclassified, for the same reason and by the same sentence")
        basis["element_refusal_policy"] = security.ELEMENT_REFUSAL_POLICY
        basis["refusals"] = [_refusal_dict(refusal) for refusal in decoded.refusals]
        basis["advisories"] = [dict(advisory) for advisory in decoded.advisories]
        if decoded.unlisted_tags:
            basis["unlisted_tags"] = list(decoded.unlisted_tags)
            basis["unlisted_tags_basis"] = security.ABSENT_TAGS_BASIS
        return basis

    def _security_metadata(self, decoded: security.DecodedSecuritySet) -> dict:
        """The decoded elements, keyed by ST 0102.12's own element names.

        **KEYED AS THE DOCUMENT NAMES THEM.** The standing ruling puts a security element the CDM
        has no field for into `Entity.attributes` "as the document names it", so the keys here are
        §6.7's Name column lower-cased with spaces and slashes turned to underscores and nothing
        else — no CDM vocabulary, no shortening, no renaming of the two long Version Date
        elements. A reader with Table 2 open can find every key in it.

        The three `uint8` elements carry BOTH the integer the packet sent and the string §6.8
        converts it to, under two keys, because they are two different claims: the integer is what
        arrived and the label is what a held clause says it means. A label is absent where the
        integer is not one the element's own enumeration lists.
        """
        out: dict[str, Any] = {}
        for tag in decoded.order:
            entry = decoded.elements.get(tag)
            if entry is None:
                continue                       # refused or unlisted; it is in the basis, not here
            key = _element_key(entry.name)
            out[key] = {
                "tag": tag,
                "value": entry.value,
                "octets": entry.raw.hex(),
                "presence": entry.presence,
                "section": entry.section,
                "length_octets": entry.length,
            }
            if entry.label is not None:
                out[key]["label"] = entry.label
                out[key]["label_basis"] = security.CONVERSION_BETWEEN_SET_FORMS
            if tag == 13:
                out[key]["value_is_octets_not_text"] = (
                    security.DECODING_RULES["carried_octets"])
        out["_element_order"] = list(decoded.order)
        out["_local_set_key"] = security.LOCAL_SET_KEY.hex()
        out["_local_set_key_crc"] = security.LOCAL_SET_KEY_CRC
        out["_local_set_key_basis"] = (
            "§6.7's registered key, stated here as the set's IDENTITY. It is NOT an octet this "
            "packet carried: inside ST 0601 item 48 the key is not on the wire, because §8.48 "
            "makes the item's own length 'the size of all MISB ST 0102 metadata items'. ST "
            "0601.14a §8.48 prints the same sixteen octets and the same CRC 40980, which is the "
            "two-document agreement item 48's reading rests on")
        return out

    def _integrity_basis(self, packet: uas.DecodedPacket) -> dict:
        """The first REAL integrity gate in a binary adapter here, and it is worth saying so."""
        return {
            "checksum_item": "tag 1 Checksum",
            "stored": packet.checksum_stored,
            "computed": packet.checksum_computed,
            "valid": packet.checksum_valid,
            "range": (
                "ST 0601.14a §6.6 and §8.1: 'Performed on entire LS packet, including 16-byte US "
                "key and 1-byte checksum length' — so the summation runs from the first octet of "
                "the Universal Label up to and including tag 1's own length octet, and the two "
                "octets of the stored value are outside it. Computed by klv_codec.bcc_16, which is "
                "a transcription of the C the document prints in §8.1.1.1 and is checked against "
                "the eight-octet worked vector in §8.1.1.2"),
            "why_a_failure_is_not_a_refusal": (
                "a packet whose checksum does not validate is TRANSLATED and flagged. The stored "
                "checksum is one item among 26, and discarding 25 items that each satisfied their "
                "own Required Length because a 16-bit sum disagrees would destroy the evidence a "
                "consumer needs to decide what happened — the same reasoning that makes the length "
                "policy skip an ITEM rather than a packet. `valid: false` on an object is a "
                "statement, and a missing object is not"),
            "what_this_is_NOT": (
                "the four sibling ASTERIX adapters and the GMTIF one all had to record that their "
                "format defines no checksum at any level. This one does, `ST 0601.14-32` makes it "
                "mandatory in every packet, and a validating 16-bit summation over the whole "
                "packet is a materially stronger gate than a structural parse — it is what ruled "
                "out corruption as an explanation for the length divergence at tag 22"),
        }

    # ------------------------------------------------------------------ payload

    def _payload(self, index: int, packet: uas.DecodedPacket, envelope: dict,
                 geometry_basis: dict, time_basis: dict) -> dict:
        items = packet.items
        payload: dict[str, Any] = {
            "packet_index": index,
            "packet_count": envelope.get("packet_count"),
            "payload_octets": envelope.get("octets"),
            "klv_item_count": len(packet.order),
            "geometry_basis": geometry_basis,
            "time_basis": time_basis,
        }

        def number(tag: int) -> Any:
            return _rendered(items[tag].value) if tag in items else None

        payload["sensor"] = {
            "active_sensor_name": number(11),
            "image_coordinate_system": number(12),
            "horizontal_field_of_view_deg": number(16),
            "vertical_field_of_view_deg": number(17),
            "relative_azimuth_deg": number(18),
            "relative_elevation_deg": number(19),
            "relative_roll_deg": number(20),
            "slant_range_m": number(21),
            "ground_range_m": number(57),
            "true_altitude_msl_m": number(15),
            "basis": (
                "the sensor half of the witnessed set, parked whole. The three relative angles are "
                "the gimbal's orientation with respect to the airframe and the CDM has no field "
                "for a sensor's pointing at all; deriving where the sensor is LOOKING from them "
                "plus the platform attitude at tags 5/6/7 would be a photogrammetric computation "
                "the standard itself delegates — §8.13.1 recommends 'the use of Photogrammetric "
                "metadata sets (i.e. MISB ST 0801)' for exactly this, and ST 0801.6 is not held"),
        }
        payload["platform_attitude"] = {
            "heading_deg": number(5),
            "pitch_deg": number(6),
            "roll_deg": number(7),
            "ground_speed_mps": number(56),
            "basis": (
                "the platform half. Heading is NOT course — see attributes.kinematics_basis — and "
                "pitch and roll reach no CDM field because the CDM models a contact's motion and "
                "not an airframe's attitude. All three carry the '~610 micro degrees' class of "
                "stated resolution and all three are within their items' stated Min/Max"),
        }
        payload["frame_centre"] = {
            "lat": number(23),
            "lon": number(24),
            "elevation_msl_m": number(25),
            "basis": ("the point Event.geometry is built from, carried in full because the "
                      "geometry is 2-D and the elevation is MSL"),
        }
        payload["target_location"] = {
            "lat": number(40),
            "lon": number(41),
            "elevation_msl_m": number(42),
            "basis": (
                "§8.40/§8.41/§8.42, 'This is the crosshair location if different from frame "
                "center'. Carried beside the frame centre and NEVER reconciled with it, not even "
                "where the two are byte-identical — which they are at all six sites of the pinned "
                "stream. Choosing between two stated points is a decision, and a decision made "
                "inside a translator is one nobody can find later"),
        }
        payload["target_width_m"] = {
            "value": number(22),
            "basis": (
                "tag 22 Target Width. In the PINNED stream this item is the length-divergence "
                "defect and this field is therefore null there, with the octets at "
                "attributes.klv_item_octets['22'] and the ruling at "
                "attributes.length_divergence_policy — see FORMAT_COVERAGE.md, 'Park 13 "
                "adjudicated and CLOSED'. In a conformant packet it is a width in metres"),
        }
        payload["klv_defects"] = [_defect_dict(defect) for defect in packet.defects]
        payload["klv_advisories"] = [dict(advisory) for advisory in packet.advisories]
        payload["integrity"] = {
            "checksum_valid": packet.checksum_valid,
            "checksum_stored": packet.checksum_stored,
            "checksum_computed": packet.checksum_computed,
        }
        return payload

    # ------------------------------------------------------------------ egress

    def from_cdm(self, objects: list[CDMBase]) -> bytes:
        """Entities that came from THIS adapter back to one KLV payload, byte-exactly.

        WHY THIS RE-EMITS OCTETS RATHER THAN RE-ENCODING VALUES. Every item's Value octets are
        parked at `attributes.klv_item_octets` on ingest, and egress replays them in the order
        `attributes.klv_tag_order` records. The alternative — re-encoding each decoded Software
        Value through `uas.encode_value` — would be lossy in a way the document itself predicts:
        §7's Programmer's Notes say the printed examples run 'beyond a tag's resolution', so a
        value that arrived quantised comes back rounded to its item's Resolution and the octets
        differ in their low bits. Replaying the octets is exact, and exactness is what makes the
        round-trip test able to fail.

        AND IT IS THE ONLY WAY THE DEFECT SURVIVES. The length-divergent item has no Software
        Value — the policy refused to invent one — so there is nothing to re-encode. Re-emitting it
        at the conformant length would be this adapter silently correcting a stream it was asked to
        translate, which is a change no consumer requested and which the source's own checksum
        would then disagree with.

        AND THE CHECKSUM IS REPLAYED TOO, which the first draft got backwards. It recomputed §6.6's
        sum on the reasoning that a self-consistent packet is the better artefact — and that
        reasoning silently REPAIRED a packet whose stored checksum did not validate, which is a
        change no consumer asked for and which made egress non-byte-exact for exactly the input
        where fidelity matters most. The fixture
        `a_checksum_that_does_not_validate_is_flagged_not_refused` failed its round-trip test and
        said so. The invalid sum is the emitter's own statement, `attributes.integrity_basis`
        records on the object that it does not validate, and computing a correct one is the
        consumer's decision rather than this adapter's.
        """
        entities = [obj for obj in objects if isinstance(obj, Entity)]
        if not entities:
            raise Stanag4609ParseError(
                "from_cdm needs at least one Entity; got "
                f"{[type(o).__name__ for o in objects]}. A STANAG 4609 payload is a sequence of "
                "UAS Datalink LS packets and each packet is one Entity's worth of state"
            )
        out = bytearray()
        for entity in sorted(entities, key=_packet_index):
            out += self._packet_from_entity(entity)
        return bytes(out)

    def _packet_from_entity(self, entity: Entity) -> bytes:
        octets = entity.attributes.get("klv_item_octets")
        order = entity.attributes.get("klv_tag_order")
        if not isinstance(octets, dict) or not isinstance(order, list):
            raise Stanag4609ParseError(
                f"entity {entity.entity_id} carries no attributes.klv_item_octets / "
                "attributes.klv_tag_order, so it did not come from this adapter. Egress here "
                "re-emits the octets ingest parked; it does not synthesise a packet from "
                "canonical fields, because the canonical fields are a lossy projection of the "
                "Local Set by construction — 26 items reach four CDM fields"
            )
        by_tag = {int(tag): bytes.fromhex(value) for tag, value in octets.items()}
        wanted = [int(tag) for tag in order]
        missing = [tag for tag in wanted if tag not in by_tag]
        if missing:
            raise Stanag4609ParseError(
                f"entity {entity.entity_id} lists tag(s) {missing} in attributes.klv_tag_order "
                "and carries no octets for them"
            )
        return uas.encode_packet({}, order=tuple(wanted),
                                 raw_overrides={tag: by_tag[tag] for tag in wanted})


def _element_key(name: str) -> str:
    """§6.7's Name column to an attribute key: lower-cased, spaces and slashes to underscores.

    Deliberately mechanical and deliberately not shortened. `Security-SCI/SHI information` becomes
    `security_sci_shi_information` and the two Version Date elements keep their full names, so a
    reader holding Table 2 can find every key in it and this adapter names no security element
    anything the document does not.
    """
    out = []
    for char in name:
        out.append(char.lower() if char.isalnum() else "_")
    key = "".join(out)
    while "__" in key:
        key = key.replace("__", "_")
    return key.strip("_")


def _packet_index(entity: Entity) -> int:
    """Wire order, from the packet index ingest recorded. Never the entity_id's ordering."""
    packet = entity.attributes.get("klv_packet") or {}
    index = packet.get("index")
    return index if isinstance(index, int) else 0
