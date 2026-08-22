"""Cursor-on-Target (TAK) — CoT event XML in, CDM out; CDM out to a CoT drawing.

Adapter #2, and the first BIDIRECTIONAL one. It implements the CoT table in
FORMAT_COVERAGE.md row by row; that table is this module's specification, and a test resolves
every CDM path in it against the models so the two cannot drift.

WHAT EACH DIRECTION IS
----------------------
INGEST  one CoT *atom* (`a-.-...`, a contact report) -> one Entity + one Event. Same
        "one payload, two objects" split as the reference adapter: the atom describes a thing
        that EXISTS (a unit, at a place, over an interval) and a thing that HAPPENED (its
        state was reported at an instant).

EGRESS  one CDM object -> one CoT event document. A PlanObject becomes a `u-d-f` free-form
        drawing (the COA-sketch direction the coverage table names); an Entity becomes an
        atom, which is what makes the ingest path round-trippable.

        Entity egress is not an extra: the harness calls `from_cdm()` on whatever `to_cdm()`
        returned for EVERY fixture of a bidirectional adapter, and any exception there is a
        FAIL. An adapter that ingests atoms and can only emit drawings therefore cannot pass
        its own harness, and rightly so — it would be claiming a capability it does not have
        for the objects it actually produces.

WHAT INGEST DELIBERATELY DOES NOT DO
------------------------------------
A `u-d-f` drawing arriving on INGEST is not special-cased. The coverage table marks the
drawing rows as egress, and the CDM's answer to an incoming drawing would be a PlanObject —
an object defined as "what we push OUT". Ingesting one would invert that definition for the
sake of symmetry nothing has asked for. Such a payload still translates losslessly: the type
resolves to UNKNOWN affiliation and UNKNOWN entity type, and every field is parked.

THE XML, AND WHY BOTH FIXTURE FORMS EXIST
-----------------------------------------
`to_cdm()` accepts CoT XML bytes OR the dict that XML parses to. That is not two translators:
`_parse_cot()` produces the dict and everything after it is shared, so the dict form exercises
the same translation minus the parse.

Both forms ship as fixtures because of a real hole in what the harness can check. Given a
non-JSON fixture the harness has no leaf structure to harvest, so `lossless` reports SKIP —
and the never-drop rule is the most important rule in the CDM. An XML-only adapter would show
a green run with its central check never executed. So each ingest fixture ships twice, `.xml`
and `.parsed.json`, the second holding exactly what the first parses to (string-valued
attributes included, because that is what XML attributes are). The two golden files are
byte-identical, and a test asserts it — which is also how the parser and the translator are
kept from disagreeing.

CoT ATTRIBUTES ARE STRINGS, AND ONE OF THEM IS A SENTINEL
---------------------------------------------------------
CoT spells "unknown" for `hae`, `ce` and `le` as **9999999**, exactly as AIS spells unknown
speed as 102.3. Forwarding it would put a contact 9999 km up with 9999 km of error. So it is
TRANSLATED to null and the translation is declared in TRANSFORMS — which is what that
mechanism is for, and which makes the exemption a printed line in every harness report.

Note the direction that is NOT a sentinel: `lat="0" lon="0"`. Some implementations use it to
mean "no position", and this adapter does not, because 0/0 is a real point in the Gulf of
Guinea and discarding it would be the mirror-image of the null-to-zero defect. A CoT event
with no `point` element at all yields `position: None`; a CoT event at 0/0 yields a position
at 0/0.

XML PARSING IS A GUARDED PARSE
------------------------------
This is the first adapter that will be handed bytes off a network. `xml.etree.ElementTree`
does not resolve external entities, but expat does expand INTERNAL ones, which is the
"billion laughs" amplification. A CoT event has no legitimate use for a DTD, so a document
carrying one is refused before the parser sees it. Refusing is right rather than
conservative: the alternative is an adapter that can be made to consume all available memory
by a well-formed-looking message.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

from synapse_cdm import ids, lossless, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    PositionSource,
    Severity,
)
from synapse_cdm.models import CDMBase, Entity, Event, Kinematics, PlanObject, Position
from synapse_cdm.symbology import affiliation_from_cot, sidc_from_affiliation

SYSTEM = "TAK"

# CoT's "value not available" sentinel for the numeric point and track attributes. Compared
# for EQUALITY, not with a threshold: a threshold would be this adapter deciding that some
# large-but-real altitude is unknown, which is a judgement, and 9999999 is the documented
# value rather than an approximate one.
COT_UNKNOWN = 9999999.0

# CoT `type` field 3 — the battle dimension — to what kind of thing the CDM says it is.
# Only the dimensions the coverage table names, plus the ones whose omission would force a
# false statement. Anything else resolves to UNKNOWN, which is a member and therefore an
# honest answer; the full type string is parked either way.
BATTLE_DIMENSION: dict[str, EntityType] = {
    "G": EntityType.UNIT,        # ground
    "F": EntityType.UNIT,        # special operations forces
    "A": EntityType.PLATFORM,    # air
    "S": EntityType.PLATFORM,    # sea surface
    "U": EntityType.PLATFORM,    # subsurface
    "P": EntityType.PLATFORM,    # space
    "X": EntityType.UNKNOWN,     # other
    "Z": EntityType.UNKNOWN,     # unknown
}

# CoT `how` -> how much the position may be trusted. Keyed on the first two fields ("m-g"),
# then on the first letter alone.
#
# An unrecognised `how` resolves to ESTIMATED rather than GNSS, which UNDERSTATES the fix.
# That is the safe direction here: `position_source` is the field a commander uses to tell a
# fix from a guess in a GNSS-denied environment, and a guess promoted to a fix is the error
# that gets acted on. The source's own word is kept at `attributes.cot_how` either way.
HOW: dict[str, PositionSource] = {
    "m-g": PositionSource.GNSS,        # machine, GPS
    "m-i": PositionSource.INERTIAL,    # machine, INS
    "m-e": PositionSource.ESTIMATED,   # machine, estimated
    "m-f": PositionSource.ESTIMATED,   # machine, fused
    "m-c": PositionSource.ESTIMATED,   # machine, configured
    "h-e": PositionSource.MANUAL,      # human, entered
    "h-t": PositionSource.MANUAL,      # human, transcribed
    "h-c": PositionSource.MANUAL,      # human, calculated
}
HOW_BY_ORIGIN: dict[str, PositionSource] = {
    "h": PositionSource.MANUAL,
    "m": PositionSource.ESTIMATED,
}

# Style keys with a conventional CoT drawing element. Everything else in `style` is emitted
# on an extension element rather than dropped — see _style_elements().
STYLE_ELEMENTS = {
    "stroke_color": "strokeColor",
    "stroke_weight": "strokeWeight",
    "fill_color": "fillColor",
}


class TakAdapter(Adapter):
    """CoT atoms in, CDM out; CDM Entity or PlanObject out to a single CoT event document."""

    name = "tak"
    version = "1.0.0"
    direction = "bidirectional"
    system = SYSTEM

    TRANSFORMS = {
        "event.@time": "re-rendered from CoT's second-precision Z form into the CDM's fixed "
                       "three-decimal form (times.render) — same instant, different string",
        "event.@start": "re-rendered into the CDM's fixed three-decimal form (times.render)",
        "event.@stale": "re-rendered into the CDM's fixed three-decimal form (times.render); "
                        "CoT staleness IS an interval end, so it maps to valid_to exactly",
        "event.@how": "mapped to the PositionSource enum; the source's own word is kept "
                      "verbatim at attributes.cot_how",
        "event.point.@hae": "CoT's 9999999 'value unknown' sentinel becomes null rather than "
                           "being forwarded as an altitude — the AIS 102.3 lesson. A REAL "
                           "altitude is carried through unchanged and needs no exemption, so "
                           "this declaration only ever covers the sentinel",
        "event.point.@ce": "CoT's 9999999 sentinel becomes null rather than being forwarded "
                           "as a 9999 km circular error; a real value is carried unchanged",
        "event.point.@le": "CoT's 9999999 sentinel becomes null; a real value is parked at "
                           "attributes.vertical_error_m (gap 6 — the CDM has no canonical "
                           "vertical-accuracy field until Position.alt_accuracy_m in 1.1.0)",
        "event.detail.track.@speed": "CoT's 9999999 sentinel becomes null; a real value is "
                                     "carried unchanged, both in metres per second",
        "event.detail.track.@course": "CoT's 9999999 sentinel becomes null; a real value is "
                                      "reduced modulo 360 so that CoT's 360.0 (due north) "
                                      "becomes the CDM's 0.0, which is the same bearing and "
                                      "the only one Kinematics.course_deg admits",
    }

    # Dotted paths in the PARSED form that this adapter maps to canonical fields. Everything
    # else is collected by lossless.residual() and parked with its structure intact, which is
    # also what lets egress graft it back — see from_cdm().
    #
    # Kept as data rather than buried in the translation below so that "what does this adapter
    # understand?" is answerable by reading one list. Note what is absent on purpose:
    # `event.@version`, `event.detail.contact.@endpoint` and `event.detail.__group.@role` are
    # NOT consumed, so they park automatically — the coverage table does not map them, and an
    # unmapped field parked is the never-drop rule working rather than a gap.
    CONSUMED = (
        "event.@uid",
        "event.@type",
        "event.@time",
        "event.@start",
        "event.@stale",
        "event.@how",
        "event.point.@lat",
        "event.point.@lon",
        "event.point.@hae",
        "event.point.@ce",
        "event.point.@le",
        "event.detail.track.@speed",
        "event.detail.track.@course",
        "event.detail.contact.@callsign",
        "event.detail.remarks",
        "event.detail.__group.@name",
    )

    # ------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One CoT atom -> [Entity, Event]. Raises on a payload it cannot read."""
        parsed = self._as_parsed(raw)
        event_node = parsed.get("event")
        if not isinstance(event_node, dict):
            raise ValueError(
                "CoT payload has no <event> element — refusing to translate; top-level keys: "
                f"{sorted(parsed)}"
            )

        uid = event_node.get("@uid")
        cot_type = event_node.get("@type")
        observed = event_node.get("@time")
        for field, value in (("uid", uid), ("type", cot_type), ("time", observed)):
            if not value:
                raise ValueError(
                    f"CoT event is missing the required @{field} attribute — refusing to "
                    f"translate a partial event; attributes present: "
                    f"{sorted(k for k in event_node if k.startswith('@'))}"
                )

        # `@start` is required by CoT and absent in the wild. Falling back to `@time` is a
        # STATED fallback, not a silent one: the basis is recorded in attributes, the same way
        # the reference adapter records which identifier it keyed an id on. Inventing an
        # interval start and saying nothing is what this avoids.
        start = event_node.get("@start")
        valid_from_basis = "event/@start"
        if not start:
            start, valid_from_basis = observed, "event/@time (event/@start absent)"

        point = event_node.get("point") if isinstance(event_node.get("point"), dict) else {}
        detail = event_node.get("detail") if isinstance(event_node.get("detail"), dict) else {}
        contact = detail.get("contact") if isinstance(detail.get("contact"), dict) else {}
        track = detail.get("track") if isinstance(detail.get("track"), dict) else {}
        group = detail.get("__group") if isinstance(detail.get("__group"), dict) else {}

        affiliation = affiliation_from_cot(cot_type)
        source = self.source_ref()
        entity_id = ids.derive(SYSTEM, uid, kind="entity")

        # The event id is keyed on (uid, time), NOT on uid alone. A CoT uid identifies the
        # OBJECT and is repeated by every position report about it, so an event id derived
        # from uid alone would collapse a thousand reports into one event. Keying on the
        # instant as well makes a redelivery of the same report idempotent — which is what an
        # id is for — while keeping two genuine reports distinct.
        event_id = ids.derive(SYSTEM, f"{uid}@{observed}", kind="event")

        attributes: dict[str, Any] = {
            # The full type string, kept verbatim. This is what makes the 7 -> 4 affiliation
            # collapse (gap 2) RECOVERABLE: a consumer that needs to know the source said
            # "suspect" rather than "unknown" reads it here. The lossless check enforces its
            # presence rather than trusting this comment.
            "cot_type": cot_type,
            "cot_affiliation_letter": _affiliation_letter(cot_type),
            "cot_battle_dimension": _battle_dimension_letter(cot_type),
            "cot_how": event_node.get("@how"),
            "valid_from_basis": valid_from_basis,
            "entity_id_basis": "event/@uid",
            "symbol_basis": "derived from affiliation; CoT states a type, not a 2525D SIDC",
            # gap 1: no canonical name field until Entity.label in 1.1.0.
            "callsign": contact.get("@callsign"),
            "remarks": detail.get("remarks"),
            # A colour-based team, not an affiliation — which is why it lives here and not in
            # `affiliation`. A meaning encoded in a colour is a meaning that can be dropped.
            "group_name": group.get("@name"),
            # gap 6: CoT @le has no canonical home; Position.accuracy_m is horizontal only.
            "vertical_error_m": _number(point.get("@le")),
            "source_extras": lossless.residual(parsed, self.CONSUMED),
        }

        entity = Entity(
            source=source,
            entity_id=entity_id,
            source_ids=[{"system": SYSTEM, "external_id": str(uid)}],
            entity_type=_entity_type(cot_type),
            affiliation=affiliation,
            symbol=sidc_from_affiliation(affiliation, synthetic=self._synthetic),
            position=self._position(point, event_node.get("@how")),
            kinematics=_kinematics(track),
            valid_from=start,
            valid_to=event_node.get("@stale"),
            # CoT carries no confidence figure. None means unknown, which is the truth.
            confidence=None,
            attributes={k: v for k, v in attributes.items() if v is not None},
        )

        event = Event(
            source=source,
            source_ids=[{"system": SYSTEM, "external_id": str(uid)}],
            event_id=event_id,
            # TRACK_UPDATE, not DETECTION. A CoT atom reports the state of an object; it does
            # not claim a sensor found something new, and this adapter cannot know from one
            # message whether it did. DETECTION would be an inference about the feed.
            event_type=EventType.TRACK_UPDATE,
            # CoT has no urgency field at all, so INFO is not a misread severity — it is the
            # honest statement that the format carries none. That is a different case from a
            # source whose severity IS present and unreadable, which is refused.
            severity=Severity.INFO,
            related_entities=[entity_id],
            # No geometry: CoT carries ONE point and it belongs to the object. Copying it onto
            # the event as well would be the adapter inventing a second representation of one
            # measurement.
            geometry=None,
            payload={
                "cot_type": cot_type,
                "cot_how": event_node.get("@how"),
                "event_id_basis": "event/@uid + event/@time",
                "severity_basis": "CoT carries no urgency field; INFO is the format's silence",
            },
            observed_at=observed,
            received_at=self.now(),
        )
        return [entity, event]

    # ------------------------------------------------------------------- egress

    def from_cdm(self, objects: list[CDMBase]) -> bytes:
        """One CDM object -> one CoT event document, as UTF-8 XML bytes.

        Exactly one emittable object, because a CoT event document holds exactly one event.
        Several drawings are several messages, which is how TAK actually carries them; wrapping
        them in a container element would invent a document type no client parses.

        An `Event` in the list is not emittable on its own — CoT has no separate report object,
        the atom IS the report — but it is not ignored either: its `observed_at` becomes the
        atom's `@time`, which is the row the coverage table states.
        """
        emittable = [o for o in objects if isinstance(o, (Entity, PlanObject))]
        if len(emittable) != 1:
            kinds = [getattr(o, "object_kind", type(o).__name__) for o in objects]
            raise ValueError(
                f"from_cdm() emits ONE CoT event document and was given {len(emittable)} "
                f"emittable objects (kinds: {kinds or 'none'}). A CoT event document holds one "
                "event — push several objects as several messages. An Event alone is not "
                "emittable: CoT's atom is both the object and the report about it."
            )

        subject = emittable[0]
        if isinstance(subject, PlanObject):
            root = self._drawing_element(subject)
        else:
            root = self._atom_element(subject, objects)
        ET.indent(root, space="  ")
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    def _atom_element(self, entity: Entity, objects: list[CDMBase]) -> ET.Element:
        """An Entity back out as a CoT atom, restoring what ingest parked."""
        attributes = dict(entity.attributes)
        extras = attributes.get("source_extras") or {}

        # The HELD type wins over a derived one. Reconstructing "a-f-G-U-C" from
        # FRIENDLY + UNIT would produce "a-f-G" and silently drop the function fields the
        # source actually stated — so the parked original is preferred, and derivation is the
        # fallback for an Entity that never came from CoT.
        cot_type = attributes.get("cot_type") or _cot_type_from_cdm(entity)
        observed = _observed_at_for(entity, objects) or entity.valid_from

        root = ET.Element("event", _drop_empty({
            "version": _extras_attribute(extras, "@version", "2.0"),
            "uid": _external_id(entity, default=str(entity.entity_id)),
            "type": cot_type,
            "how": attributes.get("cot_how") or "m-g",
            "time": times.render(observed),
            "start": times.render(entity.valid_from),
            # Omitted when the CDM holds no end. Computing one would invent an expiry the plan
            # never stated; a receiving client applies its own default, which is its decision
            # to make and not ours to fabricate.
            "stale": times.render(entity.valid_to) if entity.valid_to else None,
        }))

        position = entity.position
        # hae/ce/le go out as CoT's own 9999999 sentinel when unknown, which is the mirror of
        # the ingest translation and how CoT spells unknown for those three.
        #
        # lat/lon do NOT. They are OMITTED when there is no position, for two reasons: 9999999
        # is outside [-90, 90] so it is not a latitude a strict consumer would accept, and 0
        # would be the null-to-zero defect running outbound — painting a contact in the Gulf of
        # Guinea instead of admitting we do not know where it is. An absent coordinate is what
        # "position unknown" looks like on the wire, and it is what a degraded CoT client
        # actually sends.
        ET.SubElement(root, "point", _drop_empty({
            "lat": _render_number(position.lat) if position else None,
            "lon": _render_number(position.lon) if position else None,
            "hae": _render_number(position.alt_m if position else None),
            "ce": _render_number(position.accuracy_m if position else None),
            "le": _render_number(attributes.get("vertical_error_m")),
        }))

        detail = ET.SubElement(root, "detail")
        if attributes.get("callsign"):
            ET.SubElement(detail, "contact", {"callsign": str(attributes["callsign"])})
        kinematics = entity.kinematics
        if kinematics and (kinematics.speed_mps is not None or kinematics.course_deg is not None):
            ET.SubElement(detail, "track", {
                "speed": _render_number(kinematics.speed_mps),
                "course": _render_number(kinematics.course_deg),
            })
        if attributes.get("group_name"):
            ET.SubElement(detail, "__group", {"name": str(attributes["group_name"])})
        if attributes.get("remarks"):
            ET.SubElement(detail, "remarks").text = str(attributes["remarks"])

        # Everything ingest could not map, grafted back from the structure `residual()`
        # preserved. This is why residual() being structure-preserving matters twice: it is
        # what keeps a list a list on the way in, and it is what makes the way out lossless
        # without this adapter keeping a second inventory of fields it does not understand.
        _graft_extras(root, extras.get("event") if isinstance(extras, dict) else None)
        return root

    def _drawing_element(self, plan: PlanObject) -> ET.Element:
        """A PlanObject as a `u-d-f` free-form drawing — the COA-sketch direction."""
        vertices = _vertices(plan.geometry)
        if not vertices:
            raise ValueError(
                f"PlanObject {plan.object_id} has geometry type "
                f"{getattr(plan.geometry, 'type', '?')!r} with no positions — a drawing with "
                "no vertices cannot be rendered, and an overlay that silently fails to appear "
                "on a TAK client is worse than one that fails here"
            )

        now = times.render(self.now())
        root = ET.Element("event", _drop_empty({
            "version": "2.0",
            "uid": _external_id(plan, default=str(plan.object_id)),
            "type": "u-d-f",
            # Human-entered: a plan is authored, not sensed. Claiming a machine origin for a
            # commander's sketch would misstate its provenance on the receiving client.
            "how": "h-e",
            # A PlanObject carries no observation time — it was never observed. The emission
            # instant is the honest answer, and it comes from the injected clock so a golden
            # file is stable.
            "time": now,
            "start": now,
            "stale": times.render(plan.expires_at) if plan.expires_at else None,
        }))

        # The FIRST vertex, not a computed centroid. A centroid is a coordinate the plan never
        # stated; the first vertex is one it did. CoT wants an anchor point here and the
        # shape itself is carried by the links below, so nothing depends on which is chosen —
        # which is exactly why it should not be invented.
        lon, lat = vertices[0][0], vertices[0][1]
        ET.SubElement(root, "point", {
            "lat": _render_number(lat),
            "lon": _render_number(lon),
            "hae": _render_number(vertices[0][2] if len(vertices[0]) > 2 else None),
            "ce": _render_number(None),
            "le": _render_number(None),
        })

        detail = ET.SubElement(root, "detail")
        if plan.label:
            ET.SubElement(detail, "contact", {"callsign": plan.label})
        for vertex in vertices:
            altitude = vertex[2] if len(vertex) > 2 else None
            ET.SubElement(detail, "link", {
                "point": f"{_render_number(vertex[1])},{_render_number(vertex[0])},"
                         f"{_render_number(altitude)}",
            })
        for element in _style_elements(plan.style):
            detail.append(element)
        # The CDM facts a CoT drawing has no field for. Written on an extension element rather
        # than dropped, because egress may no more be lossy than ingest — and the round-trip
        # test found all three by measuring rather than by review:
        #
        #   object_id   the uid carries the TAK identifier when the object has one, so without
        #               this a consumer holding the drawing cannot get back to the CDM object.
        #   geometry    `u-d-f` plus links is a shape, but the CDM's own geometry KIND has no
        #               representation in it, and Point/LineString/Polygon are not recoverable
        #               from the link count alone (a two-point line and a two-point ring).
        #   closed      kept alongside `geometry` on purpose: it is the hint a TAK client
        #               reads, where `geometry` is the provenance a CDM consumer reads. Same
        #               fact, two audiences, and neither is served by the other's spelling.
        ET.SubElement(detail, "synapse_plan", {
            "object_id": str(plan.object_id),
            "object_type": str(plan.object_type),
            "geometry": str(getattr(plan.geometry, "type", "")),
            "schema_version": plan.schema_version,
            "closed": "true" if getattr(plan.geometry, "type", "") == "Polygon" else "false",
        })
        return root

    # ------------------------------------------------------------------ helpers

    def _as_parsed(self, raw: bytes | dict) -> dict:
        """XML bytes -> the parsed dict form; a dict passes straight through."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, (bytes, bytearray, str)):
            text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
            stripped = text.lstrip()
            if stripped.startswith("{"):
                # A .json fixture handed over as bytes. Accepted so the parsed form can be
                # replayed either way, and distinguished by inspection rather than by suffix,
                # because the harness does not tell an adapter what it opened.
                return json.loads(text)
            return _parse_cot(text)
        raise TypeError(
            f"TAK adapter takes CoT XML bytes, a JSON string or a parsed dict, got "
            f"{type(raw).__name__}"
        )

    @staticmethod
    def _position(point: dict, how: str | None) -> Position | None:
        """A Position only when CoT actually stated one.

        `lat is None or lon is None` -> None. The check is for ABSENCE: `if not lat` would
        discard a real position on the equator or the Greenwich meridian, and CoT feeds carry
        both. Note also what is NOT treated as absence — lat="0" lon="0" is a real coordinate
        here, not a sentinel, however some implementations abuse it.
        """
        lat, lon = _number(point.get("@lat")), _number(point.get("@lon"))
        if lat is None or lon is None:
            return None
        return Position(
            lat=lat,
            lon=lon,
            alt_m=_number(point.get("@hae")),
            position_source=_position_source(how),
            accuracy_m=_number(point.get("@ce")),
        )


# --------------------------------------------------------------------- parsing


def _parse_cot(text: str) -> dict:
    """CoT XML -> the dict form, xmltodict-style: attributes prefixed `@`, text as the value.

    Repeated sibling elements become a list, so a drawing's many `<link>` elements survive as
    a list rather than the last one winning — silent overwrite in a parser is data loss that
    no later check can see.
    """
    if "<!DOCTYPE" in text.upper():
        raise ValueError(
            "CoT payload carries a DOCTYPE declaration and is refused. A CoT event has no "
            "legitimate use for a DTD, and internal entity expansion is an amplification "
            "attack against any parser that accepts one"
        )
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"CoT payload is not well-formed XML: {e}") from e
    return {root.tag: _element_to_dict(root)}


def _element_to_dict(element: ET.Element) -> Any:
    """One element as a dict of `@attributes` and children, or as its text when it is a leaf."""
    node: dict[str, Any] = {f"@{k}": v for k, v in element.attrib.items()}
    for child in element:
        value = _element_to_dict(child)
        if child.tag in node:
            existing = node[child.tag]
            node[child.tag] = existing + [value] if isinstance(existing, list) else [existing, value]
        else:
            node[child.tag] = value
    text = (element.text or "").strip()
    if not node:
        return text
    if text:
        node["#text"] = text
    return node


# ------------------------------------------------------------------ translation


def _number(value: Any) -> float | None:
    """A CoT numeric attribute as a float, with the 9999999 sentinel translated to None.

    Everything arrives as a string from XML. An unparseable value is None rather than an
    exception: a malformed `ce` must not cost the whole contact report, and None states
    "unknown accuracy" honestly. A malformed REQUIRED attribute is caught in to_cdm(), where
    refusing is the right answer.
    """
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number == COT_UNKNOWN else number


def _affiliation_letter(cot_type: str | None) -> str | None:
    parts = (cot_type or "").split("-")
    return parts[1].lower() if len(parts) >= 2 and parts[1] else None


def _battle_dimension_letter(cot_type: str | None) -> str | None:
    parts = (cot_type or "").split("-")
    return parts[2].upper() if len(parts) >= 3 and parts[2] else None


def _entity_type(cot_type: str | None) -> EntityType:
    """Battle dimension -> EntityType, with one refinement the coverage table's "…" allows.

    `G` means ground, which is a UNIT for a platoon and a FACILITY for a bridge — and CoT says
    which in the next field (`I` for installation). Ignoring it would have this adapter state
    that a bridge is a unit, which is not a coarser truth but a false one. Nothing beyond that
    is inferred from the type hierarchy: the full string is parked for a consumer that wants
    to read it, and interpreting it further would be the translator making judgements.
    """
    parts = (cot_type or "").split("-")
    dimension = _battle_dimension_letter(cot_type)
    if dimension is None:
        return EntityType.UNKNOWN
    if dimension == "G" and len(parts) >= 4 and parts[3].upper() == "I":
        return EntityType.FACILITY
    return BATTLE_DIMENSION.get(dimension, EntityType.UNKNOWN)


def _position_source(how: str | None) -> PositionSource:
    word = (how or "").lower()
    if word in HOW:
        return HOW[word]
    fields = word.split("-")
    if len(fields) >= 2 and f"{fields[0]}-{fields[1]}" in HOW:
        return HOW[f"{fields[0]}-{fields[1]}"]
    return HOW_BY_ORIGIN.get(fields[0] if fields else "", PositionSource.ESTIMATED)


def _kinematics(track: dict) -> Kinematics | None:
    """Motion, or None when CoT stated none. Absent is unknown, never zero."""
    speed = _number(track.get("@speed"))
    course = _number(track.get("@course"))
    if speed is None and course is None:
        return None
    # CoT's 360.0 is due north and so is 0.0; Kinematics.course_deg admits only the second.
    # Reduced rather than rejected, because the two spell one bearing — and declared in
    # TRANSFORMS, because the number on the wire is not the number in the output.
    return Kinematics(speed_mps=speed, course_deg=None if course is None else course % 360.0)


# ---------------------------------------------------------------------- egress


def _drop_empty(attributes: dict[str, str | None]) -> dict[str, str]:
    """Attributes whose value is None are OMITTED, never written as an empty string.

    `stale=""` is not "no expiry" to a receiving client — it is an unparseable timestamp, and
    clients differ on whether that means now, never, or a dropped event.
    """
    return {k: v for k, v in attributes.items() if v is not None}


def _render_number(value: float | None) -> str:
    """A CDM number as a CoT attribute; None becomes CoT's own unknown sentinel."""
    return repr(float(COT_UNKNOWN if value is None else value))


def _external_id(obj: CDMBase, *, default: str) -> str:
    """This object's TAK identifier if it has one, so a round trip keeps the same uid."""
    for source_id in obj.source_ids:
        if source_id.system == SYSTEM:
            return source_id.external_id
    return default


def _observed_at_for(entity: Entity, objects: list[CDMBase]):
    """The `observed_at` of an Event about this entity — CoT's `@time` row in the table."""
    for candidate in objects:
        if isinstance(candidate, Event) and entity.entity_id in candidate.related_entities:
            return candidate.observed_at
    return None


def _cot_type_from_cdm(entity: Entity) -> str:
    """A minimal CoT type for an Entity that never came from CoT.

    Three fields only — `a-<affiliation>-<dimension>`. The function fields are left off rather
    than guessed: a type that LOOKS specific and was invented renders a wrong glyph on a
    client, and a wrong symbol is worse than a generic one for exactly the reason
    `Entity.symbol` is validated at all.
    """
    from synapse_cdm.symbology import COT_FROM_AFFILIATION

    letter = COT_FROM_AFFILIATION.get(Affiliation(entity.affiliation), "u")
    dimension = next(
        (d for d, kind in BATTLE_DIMENSION.items() if kind == entity.entity_type and d in "GA"),
        "Z",
    )
    return f"a-{letter}-{dimension}"


def _vertices(geometry: Any) -> list[list[float]]:
    """The drawing's positions as `[lon, lat, alt?]`, in GeoJSON order and geometry order."""
    kind = getattr(geometry, "type", None)
    coordinates = getattr(geometry, "coordinates", None)
    if kind == "Point":
        return [list(coordinates)]
    if kind == "LineString":
        return [list(p) for p in coordinates]
    if kind == "Polygon":
        # The OUTER ring only. Interior rings (holes) have no `u-d-f` representation, and
        # emitting them as more links would draw the hole as part of the outline — a shape
        # that means something different from the one the plan stated.
        return [list(p) for p in coordinates[0]]
    return []


def _style_elements(style: dict[str, Any]) -> list[ET.Element]:
    """Style as CoT drawing elements; anything unrecognised rides on an extension element.

    `<detail>` is an open bag by design in CoT, and an unknown child element is ignored by a
    client rather than rejected — so parking the rest there is using the documented extension
    point, not inventing a construct. Dropping them instead would make egress lossy in exactly
    the way the ingest direction is forbidden to be.
    """
    elements = []
    remainder = {}
    for key, value in sorted(style.items()):
        if key in STYLE_ELEMENTS:
            elements.append(ET.Element(STYLE_ELEMENTS[key], {"value": str(value)}))
        else:
            remainder[key] = value
    if remainder:
        elements.append(ET.Element("synapse_style", {k: str(v) for k, v in remainder.items()}))
    return elements


def _graft_extras(parent: ET.Element, extras: Any) -> None:
    """Rebuild parked source structure as XML under `parent`, without overwriting anything.

    Canonical fields win: an attribute or element this adapter already wrote is left alone.
    There should be no collision at all — `residual()` removed every consumed path — so a
    collision means the consumed list and the writer disagree, and silently preferring one
    would hide that. Preferring the canonical value keeps the OUTPUT correct while the
    disagreement stays visible in the parked bag.
    """
    if not isinstance(extras, dict):
        return
    for key, value in extras.items():
        if key.startswith("@"):
            parent.attrib.setdefault(key[1:], str(value))
        elif key == "#text":
            if not (parent.text or "").strip():
                parent.text = str(value)
        else:
            for item in value if isinstance(value, list) else [value]:
                existing = parent.find(key)
                target = existing if existing is not None else ET.SubElement(parent, key)
                if isinstance(item, dict):
                    _graft_extras(target, item)
                elif item != "":
                    target.text = str(item)


def _extras_attribute(extras: Any, key: str, default: str) -> str:
    """One parked attribute of the `<event>` element, or a default."""
    if isinstance(extras, dict):
        event = extras.get("event")
        if isinstance(event, dict) and event.get(key):
            return str(event[key])
    return default
