"""The export policy: exact matching of what the deployment configuration names (REQ131-133).

A source resolves to a destination only when one rule of `export_policy` names exactly that
source label set (set equality: no subset, superset, ordering or lattice), that tenant, realm and
synthetic layer, that destination peer, and the family. No rule means deny. The label set of a
source identity on a channel is the channel's configured `security_context` — the one label
every accepted report on it carries — so it is a singleton here. A rule with `forwarding: true`
is refused when the configuration is read (no forwarding profile is implemented, REQ133), and a
destination realm equal to the ingress realm is denied as `REALM_LOOP` (no re-export to the
ingress realm). This is configuration matching: not a classification-policy engine and not a
cross-domain guard.
"""
from __future__ import annotations

import dataclasses

from synapse_link16_bridge.config import BridgeConfig, PolicyRule


@dataclasses.dataclass(frozen=True)
class Match:
    rule: PolicyRule | None
    reason: str | None


def source_labels(config: BridgeConfig) -> frozenset[str]:
    return frozenset({config.security_context})


def resolve(config: BridgeConfig, peer_id: str, source_synthetic: bool) -> Match:
    """The rule an export to `peer_id` resolves to, or the reason it does not.

    `SYNTHETIC_MISMATCH` when every rule naming this peer for this source has a destination of
    another synthetic layer than the source; `POLICY_DENIED` when no rule names exactly this
    source and this peer; `REALM_LOOP` when the one that does sends back to the ingress realm."""
    labels = source_labels(config)
    candidates = [rule for rule in config.export_policy
                  if rule.destination.peer_id == peer_id
                  and rule.source_tenant == config.tenant and rule.source_realm == config.realm
                  and rule.source_synthetic == source_synthetic and rule.label_set == labels]
    if not candidates:
        return Match(None, "POLICY_DENIED")
    same_layer = [rule for rule in candidates if rule.destination.synthetic == source_synthetic]
    if not same_layer:
        return Match(None, "SYNTHETIC_MISMATCH")
    rule = same_layer[0]
    if rule.destination.realm == config.realm:
        return Match(None, "REALM_LOOP")
    return Match(rule, None)


def family(rule: PolicyRule, config: BridgeConfig, gateway_transmit: tuple[str, ...]) -> str | None:
    """The family the runtime chooses (REQ093): the rule's first family that the configuration
    and the gateway's capabilities both allow, or None."""
    for name in rule.families:
        if name in config.transmit_families and name in gateway_transmit:
            return name
    return None
