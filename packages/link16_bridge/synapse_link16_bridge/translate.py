"""One record's way to the CDM: the channel check, scope and family, then the adapter (REQ060,
REQ065, REQ071, REQ081, REQ115, SPEC section 16).

The adapter is built once per channel with the configuration's EXPLICIT `synthetic` (REQ081: the
runtime never relies on the SDK's default) and the negotiated `cdm_schema`. Before a report is
translated, its `gateway_id`, `tenant`, `realm`, `synthetic` and `security_context` must equal the
configured channel's exactly: a different `synthetic` is `SYNTHETIC_MISMATCH` and any other
difference `SECURITY_CONTEXT_MISMATCH`, and both stop the channel — an in-band label never grants
access (REQ060, REQ131). An `origin_scope` the configuration has not approved is
`IDENTITY_SCOPE_UNRESOLVED` and the record is quarantined (REQ071); a `message_family` outside both
the configured and the gateway's receive families is `UNSUPPORTED_MESSAGE`, kept opaque and never
projected (REQ002, REQ115).

Then the report's canonical octets go to the adapter (`to_cdm`), which judges the contract on them:
a body over 1 MiB or 64 levels is the base class's `InputTooLarge` / `InputTooDeep`, both
`LIMIT_EXCEEDED`; every other refusal carries its contract code. Dispositions follow SPEC section
16: `SCHEMA_INVALID`, `JSON_INVALID` and `LIMIT_EXCEEDED` quarantine the record; `TIME_UNRESOLVED`
keeps it as opaque evidence with no canonical track. Under the compatibility projection a report
whose position was not projected is flagged `POSITION_NOT_PROJECTED_CDM3`.
"""
from __future__ import annotations

import dataclasses

from synapse_cdm.adapter import InputTooDeep, InputTooLarge
from synapse_cdm.adapters.link16_gateway import T_COMPAT, Link16GatewayAdapter, \
    Link16GatewayRefusal

from synapse_link16_bridge import jsonstrict
from synapse_link16_bridge.config import BridgeConfig
from synapse_link16_bridge.negotiate import Projection, adapter_schema

ACCEPT, QUARANTINE, OPAQUE, STOP = "ACCEPT", "QUARANTINE", "OPAQUE", "STOP"
COMPAT_FLAG = "POSITION_NOT_PROJECTED_CDM3"
_REPORT_CHANNEL = ("gateway_id", "tenant", "realm", "synthetic", "security_context")
_NOTICE_CHANNEL = ("tenant", "realm", "synthetic", "security_context")


@dataclasses.dataclass(frozen=True)
class Verdict:
    action: str
    code: str | None = None
    path: str | None = None
    rule: str | None = None
    objects: tuple = ()
    flags: tuple[str, ...] = ()
    transformations: tuple[str, ...] = ()


class Translator:
    def __init__(self, config: BridgeConfig, projection: Projection, clock,
                 gateway_receive_families: tuple[str, ...]) -> None:
        self.config = config
        self.projection = projection
        self.adapter = Link16GatewayAdapter(clock, synthetic=config.synthetic,
                                            cdm_schema=adapter_schema(projection))
        self.families = frozenset(config.receive_families) & frozenset(gateway_receive_families)
        self.calls = 0

    def channel_check(self, kind: str, body: dict) -> Verdict | None:
        """A stop verdict when a channel field is present, well-typed and different."""
        expected = {"gateway_id": self.config.gateway_id, "tenant": self.config.tenant,
                    "realm": self.config.realm, "synthetic": self.config.synthetic,
                    "security_context": self.config.security_context}
        keys = _REPORT_CHANNEL if kind == "report" else _NOTICE_CHANNEL
        if "synthetic" in body and type(body["synthetic"]) is bool and \
                body["synthetic"] is not self.config.synthetic:
            return Verdict(STOP, "SYNTHETIC_MISMATCH", "synthetic", "differs from the channel")
        for key in keys:
            if key == "synthetic" or key not in body:
                continue
            if type(body[key]) is str and body[key] != expected[key]:
                return Verdict(STOP, "SECURITY_CONTEXT_MISMATCH", key, "differs from the channel")
        return None

    def scope_check(self, body: dict) -> Verdict | None:
        scope = body.get("origin_scope")
        if type(scope) is str and scope not in self.config.approved_origin_scopes:
            return Verdict(QUARANTINE, "IDENTITY_SCOPE_UNRESOLVED", "origin_scope",
                           "scope not approved for this channel")
        return None

    def family_check(self, body: dict) -> Verdict | None:
        family = body.get("message_family")
        if type(family) is str and family not in self.families:
            return Verdict(OPAQUE, "UNSUPPORTED_MESSAGE", "message_family",
                           "family not supported on this channel")
        return None

    def translate(self, body: dict) -> Verdict:
        self.calls += 1
        try:
            objects = self.adapter.to_cdm(jsonstrict.canonical(body))
        except Link16GatewayRefusal as refusal:
            if refusal.code == "TIME_UNRESOLVED":
                return Verdict(OPAQUE, refusal.code, refusal.path, refusal.rule)
            if refusal.code == "SYNTHETIC_MISMATCH":
                return Verdict(STOP, refusal.code, refusal.path, refusal.rule)
            return Verdict(QUARANTINE, refusal.code, refusal.path, refusal.rule)
        except (InputTooLarge, InputTooDeep):
            return Verdict(QUARANTINE, "LIMIT_EXCEEDED", "", "above the contract's bounds")
        transformations = tuple(objects[0].source.transformations)
        flags = (COMPAT_FLAG,) if T_COMPAT in transformations else ()
        return Verdict(ACCEPT, objects=tuple(objects), flags=flags,
                       transformations=transformations)
