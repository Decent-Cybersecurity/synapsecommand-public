"""PNTMAP GNSS interference alert -> one Entity (the emitter) + one Event (the interference).

THE REFERENCE ADAPTER. It is worth reading before writing adapter #2 because every rule the
CDM cares about shows up here at least once:

- ONE payload, TWO objects. The alert describes a thing that exists (an interference source,
  at a place, over an interval) and a thing that happened (interference, observed, over an
  area). Those are different canonical kinds and forcing them into one would lose whichever
  half the container was not shaped for.
- NO BUSINESS LOGIC, demonstrated where it is most tempting. A jamming emitter is almost
  certainly hostile, and this adapter still writes `affiliation: UNKNOWN` unless the payload
  states an attribution. Inferring HOSTILE would be an intelligence judgement made inside a
  translator, invisible to the audit trail, and unattributable — and it would be wrong the
  first time the "jammer" turns out to be a friendly EW exercise. The source's own words are
  kept in `attributes`; the judgement is the fusion layer's to make, on the record.
- UNKNOWN POSITION STAYS NULL. An alert with no geolocated emitter produces an entity with
  `position: None`, never (0, 0) — see fixtures/spoofing_no_geolocation.json.
- NEVER DROP. Everything not mapped to a canonical field is parked by `lossless.residual()`
  under `attributes.source_extras` / `payload.source_extras`, so a field this adapter has
  never seen still arrives intact.
- THE DECLARED TRANSFORM. `alert_time` is re-rendered into the CDM's fixed-millisecond form,
  so its string changes and the lossless check would flag it. It is declared in TRANSFORMS
  with a reason, and the harness prints that reason on every run.
- DERIVED IDENTITY WITH A STATED BASIS. `entity_id` is uuid5 over the emitter's own id when
  the payload has one, and over the alert id when it does not — and the basis is recorded in
  `attributes`, because an id keyed on a per-alert field is NOT stable across alerts and a
  consumer accumulating a track needs to know that.

PAYLOAD SHAPE (synthetic, representative — no real PNTMAP data in this repository)
---------------------------------------------------------------------------------
    {
      "alert_id": "PNTMAP-2026-04-29-0117",
      "alert_time": "2026-04-29T06:12:44Z",
      "valid_until": "2026-04-29T07:00:00Z",          optional
      "severity": "critical",                          info | advisory | warning | critical
      "interference": {"type": "jamming",              jamming | spoofing | unknown
                       "band": "L1",
                       "signal_strength_dbm": -71.5,
                       "confidence": 0.87},
      "emitter": {"emitter_id": "EMT-4471",            optional - see identity basis above
                  "lat": 57.512, "lon": 21.884,        optional - absent means unknown
                  "geolocation_method": "tdoa",
                  "accuracy_m": 2500,
                  "attribution": "hostile"},           optional - the ONLY thing that may set
                                                       affiliation
      "affected_area": {GeoJSON Polygon},              optional
      ...anything else rides through into source_extras
    }
"""
from __future__ import annotations

import json
from typing import Any

from synapse_cdm import ids, lossless
from synapse_cdm.adapter import Adapter
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    InterferenceType,
    PositionSource,
    Severity,
)
from synapse_cdm.models import CDMBase, Entity, Event, Position
from synapse_cdm.symbology import sidc_from_affiliation

SYSTEM = "PNTMAP"

# The source's vocabulary -> ours. A value absent from a table is NOT silently defaulted: it
# raises for severity (an alert whose urgency we cannot read must not arrive labelled INFO)
# and resolves to UNKNOWN for interference type and affiliation (both have a member that
# means exactly "not known", so using it states the truth rather than guessing).
SEVERITY = {
    "info": Severity.INFO,
    "advisory": Severity.ADVISORY,
    "warning": Severity.WARNING,
    "critical": Severity.CRITICAL,
}
INTERFERENCE = {
    "jamming": InterferenceType.JAMMING,
    "spoofing": InterferenceType.SPOOFING,
    "unknown": InterferenceType.UNKNOWN,
}
ATTRIBUTION = {
    "hostile": Affiliation.HOSTILE,
    "friendly": Affiliation.FRIENDLY,
    "neutral": Affiliation.NEUTRAL,
    "unknown": Affiliation.UNKNOWN,
}
# How PNTMAP says it geolocated the emitter -> what that means for trusting the position.
# Everything here is ESTIMATED or better-stated; `tdoa` and `aoa` are inferred fixes, not
# reported ones, and calling them GNSS would be absurd for an alert about GNSS being denied.
GEOLOCATION = {
    "tdoa": PositionSource.ESTIMATED,
    "aoa": PositionSource.ESTIMATED,
    "reported": PositionSource.MANUAL,
    "surveyed": PositionSource.MANUAL,
}


class PntmapAdapter(Adapter):
    name = "pntmap"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    TRANSFORMS = {
        "alert_time": "re-rendered from the source's second-precision Z form into the CDM's "
                      "fixed three-decimal form (times.render) — same instant, different "
                      "string",
        "valid_until": "re-rendered into the CDM's fixed three-decimal form (times.render)",
        "emitter.geolocation_method": "mapped to the PositionSource enum; the source's own "
                                      "word is kept at attributes.source_extras."
                                      "geolocation_method",
    }

    # Dotted paths this adapter maps to canonical fields. Everything else is collected by
    # lossless.residual() and parked. Kept as data rather than buried in the code below so
    # that "what does this adapter understand?" is answerable by reading one list.
    CONSUMED_TOP = ("alert_id", "alert_time", "valid_until", "severity")
    CONSUMED_INTERFERENCE = ("interference.type", "interference.band",
                             "interference.signal_strength_dbm", "interference.confidence")
    CONSUMED_EMITTER = ("emitter.emitter_id", "emitter.lat", "emitter.lon",
                        "emitter.geolocation_method", "emitter.accuracy_m",
                        "emitter.attribution")

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        alert = self._as_dict(raw)
        for required in ("alert_id", "alert_time", "interference"):
            if not alert.get(required):
                raise ValueError(
                    f"PNTMAP alert is missing {required!r} — refusing to translate a partial "
                    f"alert; keys present: {sorted(alert)}"
                )

        interference = alert["interference"] or {}
        emitter = alert.get("emitter") or {}
        source = self.source_ref()

        severity_word = str(alert.get("severity", "")).lower()
        if severity_word not in SEVERITY:
            raise ValueError(
                f"unknown PNTMAP severity {alert.get('severity')!r}; known: "
                f"{', '.join(SEVERITY)}. Refused rather than defaulted — an alert that "
                "arrives labelled INFO because its severity was unreadable is worse than one "
                "that fails loudly"
            )

        affiliation = ATTRIBUTION.get(str(emitter.get("attribution", "")).lower(),
                                      Affiliation.UNKNOWN)

        entity_id, id_basis = ids.derive_with_basis(
            SYSTEM,
            {"emitter.emitter_id": emitter.get("emitter_id"),
             "alert_id": alert.get("alert_id")},
            kind="entity",
        )
        event_id = ids.derive(SYSTEM, alert["alert_id"], kind="event")

        # The entity keeps the ALERT-level leftovers and the emitter's own leftovers. The
        # `interference` subtree is consumed WHOLE here — it is the event's subject, and
        # parking its leftovers on both objects would duplicate them, which is not loss but
        # is noise, and noise in an extension bag is where real fields go to hide.
        entity_extras = lossless.residual(
            alert,
            (*self.CONSUMED_TOP, *self.CONSUMED_EMITTER, "interference", "affected_area"),
        )
        # The emitter's consumed-but-remapped words, kept verbatim under their original key
        # so the source's structure is recoverable. `geolocation_method` is declared in
        # TRANSFORMS *and* kept here: the declaration explains the change, this keeps the
        # original readable.
        for key in ("geolocation_method", "attribution"):
            if emitter.get(key) is not None:
                entity_extras.setdefault("emitter", {})[key] = emitter[key]

        entity = Entity(
            source=source,
            entity_id=entity_id,
            source_ids=[{"system": SYSTEM, "external_id": str(
                emitter.get("emitter_id") or alert["alert_id"])}],
            entity_type=EntityType.INTERFERENCE_SOURCE,
            affiliation=affiliation,
            symbol=sidc_from_affiliation(affiliation, synthetic=self._synthetic),
            position=self._position(emitter),
            valid_from=alert["alert_time"],
            valid_to=alert.get("valid_until"),
            confidence=interference.get("confidence"),
            attributes={
                # Stated, not implied: a consumer accumulating this emitter across alerts has
                # to know whether the id it is keying on is stable.
                "entity_id_basis": id_basis,
                "symbol_basis": "derived from affiliation; the source states no SIDC",
                "interference_type": str(interference.get("type", "")).lower() or None,
                "source_extras": entity_extras,
            },
        )

        payload: dict[str, Any] = {
            "frequency_band": interference.get("band") or "UNKNOWN",
            "interference_type": INTERFERENCE.get(
                str(interference.get("type", "")).lower(), InterferenceType.UNKNOWN).value,
            "signal_strength_dbm": interference.get("signal_strength_dbm"),
            "source_extras": lossless.residual(
                {"interference": interference},
                self.CONSUMED_INTERFERENCE,
            ).get("interference", {}),
        }

        event = Event(
            source=source,
            # The alert's OWN identifier, not the emitter's: this is what PNTMAP deduplicates
            # on and what an auditor holding this event will search for in the source system.
            source_ids=[{"system": SYSTEM, "external_id": alert["alert_id"]}],
            event_id=event_id,
            event_type=EventType.GNSS_INTERFERENCE,
            severity=SEVERITY[severity_word],
            related_entities=[entity_id],
            geometry=alert.get("affected_area"),
            payload=payload,
            observed_at=alert["alert_time"],
            received_at=self.now(),
        )
        return [entity, event]

    @staticmethod
    def _as_dict(raw: bytes | dict) -> dict:
        if isinstance(raw, (bytes, bytearray, str)):
            return json.loads(raw)
        if isinstance(raw, dict):
            return raw
        raise TypeError(f"PNTMAP adapter takes JSON bytes or a dict, got {type(raw).__name__}")

    @staticmethod
    def _position(emitter: dict) -> Position | None:
        """A Position only when the source actually geolocated the emitter.

        `lat is None or lon is None` -> None, and that is the whole null-never-zero rule at the
        one place it can be broken. Note that `0.0` is a legitimate coordinate and passes this
        test: the check is for ABSENCE, not for falsiness — `if not lat` would have silently
        discarded a real position on the Greenwich meridian or the equator.
        """
        lat, lon = emitter.get("lat"), emitter.get("lon")
        if lat is None or lon is None:
            return None
        method = str(emitter.get("geolocation_method", "")).lower()
        return Position(
            lat=float(lat),
            lon=float(lon),
            position_source=GEOLOCATION.get(method, PositionSource.ESTIMATED),
            accuracy_m=emitter.get("accuracy_m"),
        )
