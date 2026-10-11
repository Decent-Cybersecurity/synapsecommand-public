"""The synthetic provider wrapper: complete snapshot reports from synthetic semantic updates.

The specification gives the provider wrapper the semantic duties of snapshot assembly (REQ031,
REQ033): every report is a complete snapshot, never a delta; null means explicitly unavailable in
the current snapshot; latitude and longitude are both known or there is no canonical fix (a
partial coordinate stays in `source_fields`); each component keeps its own observation time, and
an update that changes only identity fields does not redate an inherited position; a component
without a resolvable observation time is not projected.

This wrapper applies those rules to SYNTHETIC semantic updates only, so the runtime half of the
acceptance row P02 and of REQ031/REQ033 has something to run against. It reads no J-series code
and no native field — `message_family` is a provenance label it copies — and it makes no claim
about native behaviour: the native wrapper, which would apply an edition's word assembly and
source ownership rules, is BLOCKED_EXTERNAL_EVIDENCE (gates N04 and N05).
"""
from __future__ import annotations

import copy
from typing import Any

from synapse_link16_bridge.contract import PROFILE

ENVELOPE_KEYS = ("gateway_id", "tenant", "realm", "synthetic", "origin_scope", "reporter",
                 "track_number", "incarnation", "message_family", "native_profile", "domain",
                 "entity_kind", "security_context", "time_basis", "time_evidence")
UPDATE_KEYS = ("effective_at", "identity", "identity_code", "quality_code", "entity_kind",
               "position", "kinematics", "source_fields")
_POSITION_KEYS = ("observed_at", "lat_deg", "lon_deg", "method", "vertical")
_MOTION_KEYS = ("observed_at", "speed_mps", "course_deg", "climb_mps")


class SyntheticWrapper:
    """Assemble complete reports for one synthetic track from its semantic updates."""

    def __init__(self, envelope: dict) -> None:
        missing = [key for key in ENVELOPE_KEYS if key not in envelope]
        if missing or any(key not in ENVELOPE_KEYS for key in envelope):
            raise ValueError("the envelope holds exactly the wrapper's envelope keys")
        if envelope["synthetic"] is not True:
            raise ValueError("the synthetic wrapper assembles synthetic reports only")
        self.envelope = dict(envelope)
        self.position: dict | None = None
        self.kinematics: dict | None = None
        self.identity = "UNKNOWN"
        self.identity_code: str | None = None
        self.quality_code: str | None = None
        self.source_fields: dict = {}

    def snapshot(self, update: dict, *, record_id: str, session_id: str, sequence: str,
                 received_at: str) -> dict:
        if any(key not in UPDATE_KEYS for key in update) or "effective_at" not in update:
            raise ValueError("an update holds effective_at and the wrapper's update keys only")
        fields = dict(self.source_fields)
        fields.pop("partial_position", None)
        if "source_fields" in update:
            fields.update(copy.deepcopy(update["source_fields"]))
        if "position" in update:
            self.position = self._position(update["position"], fields)
        if "kinematics" in update:
            motion = update["kinematics"]
            self.kinematics = None if motion is None or not motion.get("observed_at") else \
                {key: motion.get(key) for key in _MOTION_KEYS}
        for key in ("identity", "identity_code", "quality_code"):
            if key in update:
                setattr(self, key, update[key])
        self.source_fields = fields
        report = {"profile": PROFILE, "record_id": record_id, "session_id": session_id,
                  "sequence": sequence, "received_at": received_at,
                  "effective_at": update["effective_at"]}
        if "entity_kind" in update:
            self.envelope["entity_kind"] = update["entity_kind"]
        report.update(self.envelope)
        report.update({"identity": self.identity, "identity_code": self.identity_code,
                       "position": copy.deepcopy(self.position),
                       "kinematics": copy.deepcopy(self.kinematics),
                       "quality_code": self.quality_code,
                       "source_fields": copy.deepcopy(fields), "extensions": {}})
        return report

    @staticmethod
    def _position(given: Any, fields: dict) -> dict | None:
        """Both coordinates and a time, or no canonical fix (the partial value kept aside)."""
        if given is None:
            return None
        has_lat, has_lon = "lat_deg" in given, "lon_deg" in given
        if has_lat != has_lon:
            fields["partial_position"] = {key: given[key] for key in ("lat_deg", "lon_deg")
                                          if key in given}
            return None
        if not has_lat or not given.get("observed_at"):
            return None
        return {"observed_at": given["observed_at"], "lat_deg": given["lat_deg"],
                "lon_deg": given["lon_deg"], "method": given.get("method", "UNKNOWN"),
                "vertical": given.get("vertical")}
