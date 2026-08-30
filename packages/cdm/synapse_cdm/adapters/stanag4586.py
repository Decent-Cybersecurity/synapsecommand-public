"""STANAG 4586 Edition 3 — DLI telemetry ingest. Adapter #15.

INGEST  one DLI datagram — one or more wrapped messages, §3.3.1 — becomes one Entity per air
        vehicle named in it, plus a Track per vehicle whose samples are that datagram's positioned
        observations in wire order.
EGRESS  none. This adapter does not emit DLI and its `direction` is `ingest`, alongside `legion`
        and `pntmap`.

Implements the row set in `FORMAT_COVERAGE.md` under "STANAG 4586 Edition 3 — DLI telemetry",
which was written from the pinned document before this file existed. The wire format lives in
`stanag4586_codec`; this module is the translation and nothing else.

THE SCOPE IS TELEMETRY AND THE NAME IS NOT ALLOWED TO OUTRUN IT
---------------------------------------------------------------
This is *STANAG 4586 telemetry ingest*, never *STANAG 4586 support*. The DLI command uplink —
flight mode commands, waypoint loading, payload steering, link management — is **out of scope
explicitly**, is enumerated under its own heading in the coverage document rather than quietly
left out, and would not become in scope by someone adding a decoder for it. Two reasons, the first
sufficient alone:

* **The CDM has no command or tasking kind.** Its object kinds are entity, event, track and
  plan_object; not one of them is an instruction to an actuator. There is nothing for a Vehicle
  Steering Command to translate INTO, and growing a kind for it is the deferred `ONTOLOGY.md`
  decision — which does not happen as a side effect of an adapter round.
* **Emitting DLI edges toward being a UCS component.** A thing that sends STANAG 4586 command
  messages is a CUCS or a VSM, and whether this repository should ship one is a scope question
  this round was not asked to answer.

THE EDITION IS 3, THE CURRENT EDITION IS 4, AND NOTHING HERE CLAIMS TO READ ONE
-------------------------------------------------------------------------------
Edition 4 (2017-04-05, AEP-84 Edition A) is current and could not be acquired — `nso.nato.int`
refuses every route with HTTP 403, no capture of any 4586 PDF exists in the Internet Archive, and
the commercial distributors that hold Edition 4 serve it paywalled and DRM-wrapped. Edition 3 is
pinned, every row says so, and **no sentence anywhere in this repository asserts that this decoder
reads an Edition 4 feed**. Edition 4 changed the vehicle identifier list and added mission-phase
and autonomy messages, so the question is live and is left open rather than answered hopefully.

WHAT THE ENTITY IS KEYED ON, AND WHY THIS FORMAT CAN DO WHAT STANAG 4609 COULD NOT
-----------------------------------------------------------------------------------
`stanag4609` had to key its platform on the packet, because nothing in its witnessed set
identifies an airframe. **This format states an identity in every wrapper.** §3.3.1.7: the Source
ID "shall be the ID number of UAS element which is originating/transmitting the message, e.g. air
vehicle for downlink messages", formed per §1.7.6 as a 4-byte number whose most significant octet
is the Owning ID. Its stated purpose is "to uniquely identify any entity in an arbitrarily formed
system combining multiple CUCS, air vehicles, and data links".

So `entity_id` derives from the Source ID and is **stable across datagrams without this adapter
remembering anything** — the property `ids.derive` exists for. That is a real gain over #10 and it
is the format's doing, not this adapter's.

NO FUSION, NO JOINS, TWELFTH TIME — AND THE ONE PLACE IT WAS TEMPTING
----------------------------------------------------------------------
The datagram is the unit of delivery and nothing crosses its boundary: no position, no state, no
timestamp. Within one datagram, messages that share a Source ID contribute to that vehicle's
Entity — which is reading one payload, not correlating two.

**The tempting move, refused: picking a position when the datagram carries several.** If a
datagram holds two `#4000` messages for one vehicle at different instants, the Entity takes NO
position at all and records why; the Track carries both as samples. Choosing "the latest" would be
a decision made inside a translator — invisible in the output, absent from the audit trail — and
it is exactly the thing `adapter.py`'s contract forbids. One `#4000` is unambiguous and is used.

POSITION SOURCE IS INERTIAL, AND THIS IS THE MOST SAFETY-LOADED LINE IN THE FILE
--------------------------------------------------------------------------------
`PositionSource` exists so that a commander can tell a fix from a guess: when PNTMAP reports
jamming over an area, every `GNSS` position inside it becomes suspect and every `INERTIAL` one does
not. Writing the wrong member here does not produce a wrong number — it produces a number that is
trusted for the wrong reason.

**The message carrying the position is named `Inertial States`, and the document states no GNSS
source anywhere in it.** There is no field saying how the solution was obtained; a real airframe's
INS is usually GNSS-aided, but that is knowledge about airframes and not something this datagram
says. So the member is `INERTIAL` — read off the message's own name, which is the only evidence
there is, and the safe direction of the two: an inertial fix wrongly trusted in a jammed area is
the error that does not get anyone killed. `attributes.position_source_basis` carries the argument
on every object, because the next person to read this will be tempted by `GNSS`.

WHY AFFILIATION IS UNKNOWN, WHICH LOOKS WRONG UNTIL IT DOESN'T
---------------------------------------------------------------
A DLI link runs between a control station and a vehicle it controls, so `FRIENDLY` is tempting and
would usually be right. **The format states no affiliation field**, and the inference runs from
deployment context rather than from anything on the wire — a relayed, recorded or captured feed
breaks it. Reading a friendly aircraft off the fact that a message arrived is the CAT021
performance-class refusal and the GMTI platform-type refusal in a third costume. `UNKNOWN`, with
the reasoning on the object at `attributes.affiliation_basis`, and a deployment that knows better
sets it in the fusion layer where the decision is visible.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from synapse_cdm import ids, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import stanag4586_codec as dli
from synapse_cdm.enums import Affiliation, EntityType, PositionSource
from synapse_cdm.models import (
    CDMBase, Entity, Kinematics, Position, SourceId, Track, TrackSample,
)
from synapse_cdm.symbology import sidc_from_affiliation

SYSTEM = "STANAG4586"

#: §4.4.3, field 0101.07. Only value 3 is a geodetic height, and even it is ambiguous — see
#: `ALTITUDE_DATUM_AMBIGUITY`. Values 0, 1 and 2 never reach `Position.alt_m`.
ALTITUDE_TYPE_WGS84 = 3

ALTITUDE_DATUM_AMBIGUITY = (
    "STANAG 4586 Ed 3 §4.4.3 field 0101.07 names altitude type 3 'WGS-84 (geoid)', which is two "
    "different surfaces: WGS-84 is an ellipsoid and the geoid is an equipotential surface, and "
    "they differ by roughly -107 m to +85 m over the earth. CDM Position.alt_m is metres HAE. The "
    "value is carried because type 3 is the only one that could be a geodetic height at all, and "
    "the residue is stated here rather than dropped at the seam"
)


class Stanag4586Adapter(Adapter):
    """DLI telemetry in, CDM out. Ingest only, by ruling — see the module docstring."""

    name = "stanag4586"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM
    # No `fixture_dir`: the fixtures live in `fixtures/stanag4586`, which is this adapter's own
    # name, and an override equal to the name is a no-op that reads as an exception. The two
    # adapters that DO override are named for covering documents whose payloads have another
    # name — `stanag4609`'s bytes are KLV and `stanag4676`'s are NITS. This one is named for the
    # standard too, but the standard's own payload name IS its number, so the two coincide.

    TRANSFORMS = {
        "0101.04 / 0101.05 (Latitude / Longitude)": (
            "BAM radians (§1.7.2, §1.7.3) become WGS-84 decimal degrees, which is the CDM's "
            "stated unit for Position. Reversible; the raw integers are parked."
        ),
        "0101.06 (Altitude)": (
            "reaches Position.alt_m ONLY when field 0101.07 Altitude Type is 3, and carries the "
            "ellipsoid/geoid ambiguity with it. Types 0, 1 and 2 park and never become alt_m."
        ),
        "0101.08 / 0101.09 (U_Speed / V_Speed)": (
            "north and east components become one ground speed and a course, which is a change of "
            "basis rather than of information: both components are parked and the pair is "
            "recoverable. Course is undefined at zero speed and is then omitted rather than set."
        ),
        "0101.01 and every other Time Stamp": (
            "a 5-octet count of milliseconds since 2000-01-01 (§1.7.2) becomes a UTC instant. "
            "Whether that count steps at a leap second is NOT stated by the document; see "
            "attributes.time_basis on every object."
        ),
    }

    # ------------------------------------------------------------------ entry point

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One datagram becomes an Entity per air vehicle, plus a Track where it has samples."""
        datagram, frames = self._frames(raw)
        received = self.now()
        order: list[int] = []
        by_vehicle: dict[int, list[dli.Frame]] = {}
        for frame in frames:
            source = frame.wrapper.source_id
            if source not in by_vehicle:
                by_vehicle[source] = []
                order.append(source)
            by_vehicle[source].append(frame)

        out: list[CDMBase] = []
        for source in order:
            out.extend(self._vehicle(source, by_vehicle[source], received, datagram, len(frames)))
        return out

    def _frames(self, raw: bytes | dict) -> tuple[bytes, list[dli.Frame]]:
        """Accepts wire octets, or the `.parsed.json` twin that ships beside each fixture.

        The twin holds the datagram as a hex string under `datagram_hex` and is decoded through
        exactly the same path — it is a READABLE form of the same octets, never a second decoder.
        The arrangement is `stanag4609`'s and it exists so a fixture's intent is greppable.
        """
        if isinstance(raw, dict):
            hexed = raw.get("datagram_hex")
            if not isinstance(hexed, str):
                raise dli.Stanag4586DecodeError(
                    "a parsed STANAG 4586 fixture must carry the datagram as hex under "
                    "'datagram_hex'; this one does not, so there is nothing to decode"
                )
            raw = bytes.fromhex(hexed)
        if not isinstance(raw, (bytes, bytearray)):
            raise dli.Stanag4586DecodeError(
                f"expected DLI octets or a parsed fixture dict, got {type(raw).__name__}"
            )
        octets = bytes(raw)
        return octets, dli.decode_frames(octets)

    # ------------------------------------------------------------------ one air vehicle

    def _vehicle(self, source_id: int, frames: list[dli.Frame],
                 received: dt.datetime, datagram: bytes,
                 frames_in_datagram: int) -> list[CDMBase]:
        decoded: list[tuple[dli.Frame, dli.DecodedMessage | None]] = []
        for frame in frames:
            try:
                decoded.append((frame, dli.decode_message(frame)))
            except KeyError:
                # Not an error. §3.3.1.9's type space is far larger than the decoded set, and a
                # datagram carrying one unknown message among four known ones must still yield the
                # four. `stanag4609` treats an unwitnessed KLV tag the same way, on ST 0107.3-04.
                decoded.append((frame, None))

        # Keyed on the SAME string the SourceId states, not on the raw integer. They diverged in
        # the first draft — the id derived from `117440769` while `source_ids` published
        # `7.0.1.1` — which makes a consumer re-deriving the id from the identifier this object
        # publishes get a different UUID. `Track.track_id` already used the rendered key, so the
        # adapter disagreed with itself across two objects it emits together.
        entity_id = ids.derive(SYSTEM, self._vehicle_key(source_id))
        positioned = [(f, m) for f, m in decoded
                      if m is not None and m.spec.number == dli.INERTIAL_STATES.number
                      and self._point(m) is not None]

        attributes = self._attributes(source_id, decoded, datagram, frames_in_datagram)
        position, kinematics = self._state(positioned, attributes)
        observed = self._observed_at(decoded)

        entity = Entity(
            source=self.source_ref(),
            source_ids=[SourceId(system=SYSTEM, external_id=self._vehicle_key(source_id))],
            entity_id=entity_id,
            entity_type=EntityType.PLATFORM,
            affiliation=Affiliation.UNKNOWN,
            symbol=sidc_from_affiliation(Affiliation.UNKNOWN, synthetic=self._synthetic),
            position=position,
            kinematics=kinematics,
            attributes=attributes,
            valid_from=observed if observed is not None else received,
            valid_to=None,
            confidence=None,
        )
        out: list[CDMBase] = [entity]
        if positioned:
            out.append(Track(
                source=self.source_ref(),
                source_ids=[SourceId(system=SYSTEM, external_id=self._vehicle_key(source_id))],
                track_id=ids.derive(SYSTEM, self._vehicle_key(source_id), kind="track"),
                entity_id=entity_id,
                samples=[TrackSample(position=self._point(m), observed_at=self._stamp(m))
                         for _, m in positioned],
                track_quality=None,
            ))
        return out

    @staticmethod
    def _vehicle_key(source_id: int) -> str:
        """The Source ID as the document writes IDs: four octets, owning octet first.

        Rendered rather than passed as a decimal because §1.7.6 gives the number STRUCTURE — the
        most significant octet is the Owning ID — and a key that hides the structure makes two
        vehicles under different Owning IDs look like unrelated large integers.
        """
        return ".".join(str((source_id >> shift) & 0xFF) for shift in (24, 16, 8, 0))

    # ------------------------------------------------------------------ position and kinematics

    def _state(self, positioned: list[tuple[dli.Frame, dli.DecodedMessage]],
               attributes: dict[str, Any]) -> tuple[Position | None, Kinematics | None]:
        """The Entity's own position — used only when the datagram is unambiguous about it.

        THE REFUSAL IS THE POINT. With two positioned `#4000` messages for one vehicle in one
        datagram there is no non-arbitrary choice, so neither is taken and the reason is recorded.
        The Track still carries both, so nothing is lost — what is refused is putting one of them
        on the Entity as though the format had said which.
        """
        if not positioned:
            attributes["position_basis"] = (
                "no #4000 Inertial States message for this vehicle carried a decodable Latitude "
                "and Longitude in this datagram, so the Entity states no position"
            )
            return None, None
        if len(positioned) > 1:
            attributes["position_basis"] = (
                f"{len(positioned)} #4000 Inertial States messages for this vehicle in one "
                "datagram; the format does not say which is the vehicle's current state and this "
                "adapter does not choose. All of them are samples on the Track"
            )
            return None, None
        _, message = positioned[0]
        attributes["position_basis"] = (
            "#4000 Inertial States fields 0101.04 and 0101.05, BAM radians to WGS-84 degrees"
        )
        return self._point(message), self._kinematics(message, attributes)

    def _point(self, message: dli.DecodedMessage) -> Position | None:
        """A Position, or None when either coordinate is absent from the presence vector.

        Latitude and longitude are separate bits in the vector and either can be absent. Half a
        coordinate pair is not a degraded position, it is no position — building one from a
        present latitude and a missing longitude would put the vehicle on the prime meridian.
        """
        import math

        lat_field = message.get("0101.04")
        lon_field = message.get("0101.05")
        if lat_field is None or lon_field is None:
            return None
        lat = math.degrees(float(lat_field.value))
        lon = math.degrees(float(lon_field.value))
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            return None
        alt = self._altitude(message)
        return Position(lat=lat, lon=lon, alt_m=alt,
                        position_source=PositionSource.INERTIAL, accuracy_m=None)

    def _altitude(self, message: dli.DecodedMessage) -> float | None:
        """Altitude, ONLY under Altitude Type 3, and never otherwise. Ambiguity 3 in the pin."""
        altitude = message.get("0101.06")
        kind = message.get("0101.07")
        if altitude is None or kind is None:
            return None
        if int(kind.raw) != ALTITUDE_TYPE_WGS84:
            return None
        return float(altitude.value)

    def _kinematics(self, message: dli.DecodedMessage,
                    attributes: dict[str, Any]) -> Kinematics | None:
        """Ground speed and course from the north/east components, climb from W_Speed.

        §1.7.2 fixes the frame: "Bearings shall be measured clockwise from true north", and
        U_Speed and V_Speed are "along true north" and "along true east". So course is
        `atan2(east, north)` and not the other way round, which is the error this comment exists
        to make checkable.

        W_Speed is "Inertial vertical speed component pointing down", and `Kinematics.climb_mps`
        is a CLIMB rate, so the sign is inverted. Recorded in TRANSFORMS and asserted in tests.
        """
        import math

        north = message.get("0101.08")
        east = message.get("0101.09")
        down = message.get("0101.10")
        speed = course = climb = None
        if north is not None and east is not None:
            n, e = float(north.value), float(east.value)
            speed = math.hypot(n, e)
            if speed > 0.0:
                course = math.degrees(math.atan2(e, n)) % 360.0
            else:
                attributes["course_basis"] = (
                    "ground speed is exactly zero, so a course would be an invented bearing "
                    "rather than a measured one"
                )
        if down is not None:
            climb = -float(down.value)
        if speed is None and climb is None:
            return None
        return Kinematics(speed_mps=speed, course_deg=course, climb_mps=climb)

    @staticmethod
    def _stamp(message: dli.DecodedMessage) -> dt.datetime:
        """A message's own Time Stamp. Every decoded message has one as field 1."""
        for uid in ("0101.01", "0102.01", "0103.01", "0104.01"):
            field = message.get(uid)
            if field is not None:
                return field.value  # type: ignore[return-value]
        raise dli.Stanag4586DecodeError(
            f"message #{message.spec.number} carries no Time Stamp; field 1 is absent from its "
            "presence vector, and §3.x makes the time stamp the first field of every message"
        )

    # ------------------------------------------------------------------ observed_at

    def _observed_at(self, decoded: list[tuple[dli.Frame, dli.DecodedMessage | None]]
                     ) -> dt.datetime | None:
        """The EARLIEST message time stamp for this vehicle in this datagram, or None.

        Earliest and not latest, and the difference is `valid_from`'s own definition — "When this
        state began". The datagram's messages are statements about a span, and the instant that
        span begins is the first of them. Taking the latest would date the state's beginning to
        the last thing observed about it.

        None when no decoded message carries a stamp, in which case `valid_from` falls back to
        receipt time and `attributes.valid_from_basis` says so — the honest form of "we do not
        know when this began", rather than a receipt time that reads like an observation.
        """
        stamps = []
        for _, message in decoded:
            if message is None:
                continue
            try:
                stamps.append(self._stamp(message))
            except dli.Stanag4586DecodeError:
                continue
        return min(stamps) if stamps else None

    # ------------------------------------------------------------------ attributes

    def _attributes(self, source_id: int,
                    decoded: list[tuple[dli.Frame, dli.DecodedMessage | None]],
                    datagram: bytes, frames_in_datagram: int) -> dict[str, Any]:
        """Everything the wire said, keyed so no two messages can overwrite each other.

        THE KEYING RULE, WHICH IS AMBIGUITY 4 MADE STRUCTURAL. Decoded fields are filed under
        their MESSAGE NUMBER, never merged into one flat namespace. `#4000` and `#3010` both carry
        a roll rate, at scales fifty times apart, and a flat `roll_rate` key would be written by
        whichever message came last with nothing on the object saying which — a number that is
        wrong by a factor of 50 and looks entirely reasonable.
        """
        messages: dict[str, Any] = {}
        unparsed: list[dict[str, Any]] = []
        defects: list[dict[str, Any]] = []
        wrappers: list[dict[str, Any]] = []

        for frame, message in decoded:
            wrapper = frame.wrapper
            # THE WRAPPER IS SOURCE DATA AND IS PARKED WHOLE. `lossless.py` is what made this
            # explicit rather than optional: a value the wire stated and the CDM dropped is a
            # value nobody can get back, and the destination ID, the IDD version and the checksum
            # width are all things an operator investigating a bad feed will want.
            wrappers.append({
                "message_type": wrapper.message_type,
                "message_name": (message.spec.name if message is not None
                                 else "not decoded by this adapter"),
                "source_id": wrapper.source_id,
                "destination_id": wrapper.destination_id,
                "message_length": wrapper.message_length,
                "sequence": wrapper.sequence,
                "properties": wrapper.properties,
                "idd_version": wrapper.idd_version,
                "ack_requested": wrapper.ack_requested,
                "checksum_octets": frame.checksum_octets,
                "checksum_valid": frame.checksum_valid,
                "checksum_stated": frame.checksum_stated,
                "checksum_computed": frame.checksum_computed,
            })
            for defect in frame.defects:
                defects.append({**defect, "message_type": wrapper.message_type})
            if message is None:
                unparsed.append({
                    "message_type": wrapper.message_type,
                    "octets": frame.data.hex(),
                    "detail": (
                        "not one of the four messages this adapter decodes; its wrapper is read, "
                        "its data parked verbatim, and the datagram translates around it"
                    ),
                })
                continue
            entry: dict[str, Any] = {
                "name": message.spec.name,
                "table": message.spec.table,
                "presence_vector": message.presence_vector,
                "absent_fields": list(message.absent_indices),
                "fields": {},
            }
            for index in sorted(message.fields):
                field = message.fields[index]
                value: Any = field.value
                if isinstance(value, dt.datetime):
                    value = times.render(value)
                entry["fields"][field.spec.unique_id] = {
                    "name": field.spec.name,
                    "raw": field.raw,
                    "value": value,
                    "units": field.spec.units,
                    **({"text": field.text} if field.text is not None else {}),
                }
            if message.trailing_octets:
                entry["trailing_octets"] = message.trailing_octets.hex()
            messages[f"#{message.spec.number}"] = entry

        attributes: dict[str, Any] = {
            "s4586_edition": "Edition 3",
            "s4586_source_id": self._vehicle_key(source_id),
            "s4586_owning_id": (source_id >> 24) & 0xFF,
            "s4586_datagram": {
                "octets": len(datagram),
                "hex": datagram.hex(),
                "frames": frames_in_datagram,
            },
            "s4586_frames": wrappers,
            "s4586_messages": messages,
            "affiliation_basis": (
                "STANAG 4586 Edition 3 states no affiliation field. A DLI link runs between a "
                "control station and a vehicle it controls, so FRIENDLY would usually be right — "
                "and it is an inference from deployment context, not from anything on the wire, "
                "which a relayed or recorded feed breaks. UNKNOWN, and a deployment that knows "
                "better decides it in the fusion layer where the decision is visible"
            ),
            "position_source_basis": (
                "INERTIAL, because the message carrying the position is #4000 Inertial States and "
                "the document states no GNSS source for it. Not GNSS: PositionSource is what lets "
                "a jammed-area warning discriminate, so an unstated GNSS claim would be trusted "
                "for a reason the wire never gave"
            ),
            "time_basis": (
                "every Time Stamp is §1.7.2's 5-octet count of milliseconds since 2000-01-01, "
                "which the document calls UTC and about which it says nothing further. Whether "
                "the count steps at a leap second is UNSTATED, so instants near a leap second "
                "carry that ambiguity. The field rolls over in 2034 by the document's own "
                "statement, and this adapter does not unwrap a rollover it cannot detect"
            ),
        }
        if unparsed:
            attributes["s4586_unparsed_messages"] = unparsed
        if defects:
            attributes["s4586_defects"] = defects
        if any("#4000" == key for key in messages):
            entry = messages["#4000"]
            kind = entry["fields"].get("0101.07")
            if kind is not None and int(kind["raw"]) == ALTITUDE_TYPE_WGS84:
                attributes["altitude_datum_ambiguity"] = ALTITUDE_DATUM_AMBIGUITY
            elif kind is not None:
                attributes["altitude_basis"] = (
                    f"Altitude Type is {kind['raw']} ({kind.get('text')}), which is not a "
                    "geodetic height, so Position.alt_m is unset and the value is parked"
                )
        return attributes
