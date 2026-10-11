"""The deployment configuration: one strict JSON file, immutable once loaded (SPEC section 15).

Read with `jsonstrict.loads` (no duplicate key, no BOM, no non-finite number), every key checked,
unknown keys refused, no inclusion and no inheritance of any kind: what the file says is the whole
configuration. A configuration that fails validation is never half-applied: `BridgeConfig.load`
raises `ConfigError` and no `Bridge` can be built from it, so transmit permission stays off
(REQ004). A change is a new file with a new `config_revision`, recorded in every audit row.

Secrets are referenced, never embedded (REQ130): `credential_ref` is `env:NAME`, the name of an
environment variable the bridge reads when it connects; any other form is refused, so a literal
credential cannot sit in an exportable configuration.

The defaults are the specification's, with two recorded readings: the "transport allowance" of
`request_deadline_seconds` is its own key, `transport_allowance_seconds` (default 2), so that
`connect_timeout_seconds` keeps REQ061's 5; and `cdm_schema_version` has no default (the
specification's "4.0.0 target" is CDM 3.1.0 in this repository, and a consumer must accept a
version explicitly).

`idle_poll_seconds` (default 1, above 0 and below `lease_ttl_seconds`) is the bridge's own key,
added 2026-10-11 in fix round 1: the wait between two passes when a pass fetched nothing — a
channel that is stopped, awaiting resynchronisation or at a capacity cap, or an empty batch —
so the loop never spins (a backoff wait already taken is not followed by an idle one).

`lease_ttl_seconds` must exceed `request_deadline_seconds` (A2F, 2026-10-11), so a lease renewed
at the start of a pass is not outlived by any one request of it; a lease that is lost all the
same ends the pass `BLOCKED` with `LEASE_LOST`. The `sample_cache` limit is gone with the cache
it sized (A2F, 2026-10-11), and a configuration that names it is refused as an unknown key.
"""
from __future__ import annotations

import dataclasses
import math
import pathlib
import re
import urllib.parse
from typing import Any

from synapse_link16_bridge import jsonstrict
from synapse_link16_bridge.contract import IDENTIFIER

DOMAINS = ("AIR", "SURFACE", "SUBSURFACE", "LAND", "UNKNOWN")
DEFAULT_FRESHNESS = {"AIR": 30.0, "SURFACE": 120.0, "SUBSURFACE": 120.0, "LAND": 120.0,
                     "UNKNOWN": 120.0}
DEFAULT_RECEIVE_FAMILIES = ("J3.2", "J3.3", "J3.4", "J3.5")
LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")
REALM_KINDS = ("live", "exercise", "replay")
MODES = ("ingest", "bidirectional")
#: REQ120-122 and REQ061 defaults, each configurable within the bound beside it.
DEFAULT_LIMITS = {
    "max_identities": 100_000,
    "max_queued_reports": 10_000,
    "max_queued_report_bytes": 64 * 1024 * 1024,
    "max_queued_exports": 4096,
    "max_queued_export_bytes": 16 * 1024 * 1024,
    "max_quarantine_bytes": 1024 * 1024 * 1024,
    "fetch_limit": 100,
    "batch_retry_max": 3,
    "max_body_bytes": jsonstrict.MAX_BODY_BYTES,
}
_LIMIT_BOUNDS = {
    "fetch_limit": (1, 1000),
    "batch_retry_max": (1, 100),
    "max_body_bytes": (1024, jsonstrict.MAX_BODY_BYTES),
}
_ENV_REF = re.compile(r"env:([A-Z_][A-Z0-9_]{0,127})")
_SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")

KEYS = (
    "config_revision", "mode", "gateway_base_url", "gateway_id", "consumer_id", "credential_ref",
    "tenant", "realm", "realm_kind", "synthetic", "security_context", "approved_origin_scopes",
    "native_profile", "cdm_schema_version", "receive_families", "required_families",
    "transmit_families", "export_policy", "number_allocations_ref", "peer_profile",
    "freshness_seconds", "request_deadline_seconds", "long_poll_seconds",
    "connect_timeout_seconds", "transport_allowance_seconds", "outbound_max_age_seconds",
    "limits", "store_path", "lease_ttl_seconds", "idle_poll_seconds",
)
REQUIRED = ("config_revision", "gateway_base_url", "gateway_id", "consumer_id", "credential_ref",
            "tenant", "realm", "realm_kind", "synthetic", "security_context",
            "approved_origin_scopes", "native_profile", "cdm_schema_version", "store_path")
_RULE_KEYS = ("policy_revision", "source", "destination", "families", "forwarding")
_SOURCE_KEYS = ("tenant", "realm", "synthetic", "label_set")
_DEST_KEYS = ("peer_id", "tenant", "realm", "synthetic", "security_context", "vertical_forms",
              "vertical_required")


class ConfigError(ValueError):
    """A configuration refused: names the key and the rule, never the value."""

    def __init__(self, key: str, rule: str) -> None:
        self.key, self.rule = key, rule
        super().__init__(f"CONFIG_INVALID: {key} — {rule}")


@dataclasses.dataclass(frozen=True)
class Destination:
    peer_id: str
    tenant: str
    realm: str
    synthetic: bool
    security_context: str
    vertical_forms: tuple[tuple[str, str], ...]
    vertical_required: bool


@dataclasses.dataclass(frozen=True)
class PolicyRule:
    """One export rule: exactly this source label set, to exactly this destination, for these
    families. Matching is set equality on labels and string equality on every other field."""

    policy_revision: str
    source_tenant: str
    source_realm: str
    source_synthetic: bool
    label_set: frozenset[str]
    destination: Destination
    families: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class BridgeConfig:
    config_revision: str
    mode: str
    gateway_base_url: str
    gateway_id: str
    consumer_id: str
    credential_ref: str
    tenant: str
    realm: str
    realm_kind: str
    synthetic: bool
    security_context: str
    approved_origin_scopes: frozenset[str]
    native_profile: str
    cdm_schema_version: tuple[str, ...]
    receive_families: tuple[str, ...]
    required_families: tuple[str, ...]
    transmit_families: tuple[str, ...]
    export_policy: tuple[PolicyRule, ...]
    number_allocations_ref: str | None
    peer_profile: Any
    freshness_seconds: dict
    request_deadline_seconds: float
    long_poll_seconds: float
    connect_timeout_seconds: float
    transport_allowance_seconds: float
    outbound_max_age_seconds: float
    limits: dict
    store_path: str
    lease_ttl_seconds: float
    idle_poll_seconds: float

    @property
    def credential_env(self) -> str:
        """The environment variable `credential_ref` names."""
        return _ENV_REF.fullmatch(self.credential_ref).group(1)

    @staticmethod
    def load(path: str | pathlib.Path) -> "BridgeConfig":
        try:
            octets = pathlib.Path(path).read_bytes()
        except OSError:
            raise ConfigError("(file)", "not readable") from None
        return BridgeConfig.from_octets(octets)

    @staticmethod
    def from_octets(octets: bytes) -> "BridgeConfig":
        try:
            document = jsonstrict.loads(octets)
        except jsonstrict.ContractError as error:
            raise ConfigError("(file)", f"not strict JSON ({error.rule})") from None
        return BridgeConfig.from_dict(document)

    @staticmethod
    def from_dict(document: Any) -> "BridgeConfig":
        return _build(document)


def _text(doc: dict, key: str, low: int = 1, high: int = 128) -> str:
    value = doc[key]
    if type(value) is not str or not low <= len(value) <= high:
        raise ConfigError(key, f"a string of {low} to {high} characters")
    return value


def _ident(value: Any, key: str) -> str:
    if type(value) is not str or IDENTIFIER.fullmatch(value) is None:
        raise ConfigError(key, "an identifier")
    return value


def _bool(value: Any, key: str) -> bool:
    if type(value) is not bool:
        raise ConfigError(key, "a boolean")
    return value


def _seconds(value: Any, key: str, low: float, high: float, *, low_open: bool) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ConfigError(key, "a finite number of seconds")
    if (value <= low if low_open else value < low) or value > high:
        raise ConfigError(key, "out of the deployment bounds")
    return float(value)


def _families(value: Any, key: str) -> tuple[str, ...]:
    if type(value) is not list or len(value) > 256 or \
            any(type(f) is not str or not 1 <= len(f) <= 32 for f in value) or \
            len(set(value)) != len(value):
        raise ConfigError(key, "a list of distinct family labels of 1 to 32 characters")
    return tuple(value)


def _url(value: Any) -> str:
    key = "gateway_base_url"
    if type(value) is not str or not 1 <= len(value) <= 2048:
        raise ConfigError(key, "an explicit URL")
    try:
        parts = urllib.parse.urlsplit(value)
        hostname = parts.hostname
        _ = parts.port  # a malformed port raises here
    except ValueError:
        raise ConfigError(key, "an explicit URL") from None
    if parts.query or parts.fragment or parts.username is not None or \
            parts.password is not None or not hostname:
        raise ConfigError(key, "scheme, host, optional port and path only")
    if parts.scheme == "https":
        return value
    if parts.scheme == "http" and hostname in LOOPBACK_HOSTS:
        return value
    raise ConfigError(key, "https, or http to a loopback host only")


def _policy(value: Any) -> tuple[PolicyRule, ...]:
    key = "export_policy"
    if type(value) is not list or len(value) > 1024:
        raise ConfigError(key, "a list of rules")
    rules = []
    for index, rule in enumerate(value):
        where = f"{key}[{index}]"
        if type(rule) is not dict or sorted(rule) != sorted(_RULE_KEYS):
            raise ConfigError(where, "exactly the rule keys")
        if rule["forwarding"] is not False:
            raise ConfigError(f"{where}.forwarding",
                              "false: no forwarding profile is implemented (REQ133)")
        revision = rule["policy_revision"]
        if type(revision) is not str or not 1 <= len(revision) <= 128:
            raise ConfigError(f"{where}.policy_revision", "a string of 1 to 128 characters")
        source, dest = rule["source"], rule["destination"]
        if type(source) is not dict or sorted(source) != sorted(_SOURCE_KEYS):
            raise ConfigError(f"{where}.source", "exactly tenant, realm, synthetic, label_set")
        labels = source["label_set"]
        if type(labels) is not list or not labels:
            raise ConfigError(f"{where}.source.label_set", "a non-empty list of labels")
        for label in labels:
            _ident(label, f"{where}.source.label_set")
        if type(dest) is not dict or sorted(dest) != sorted(_DEST_KEYS):
            raise ConfigError(f"{where}.destination", "exactly the destination keys")
        forms = dest["vertical_forms"]
        if type(forms) is not list or any(
                type(p) is not list or len(p) != 2 or any(type(x) is not str for x in p)
                for p in forms):
            raise ConfigError(f"{where}.destination.vertical_forms",
                              "a list of [unit, reference] pairs")
        families = _families(rule["families"], f"{where}.families")
        if not families:
            raise ConfigError(f"{where}.families", "at least one family")
        rules.append(PolicyRule(
            policy_revision=revision,
            source_tenant=_ident(source["tenant"], f"{where}.source.tenant"),
            source_realm=_ident(source["realm"], f"{where}.source.realm"),
            source_synthetic=_bool(source["synthetic"], f"{where}.source.synthetic"),
            label_set=frozenset(labels),
            destination=Destination(
                peer_id=_ident(dest["peer_id"], f"{where}.destination.peer_id"),
                tenant=_ident(dest["tenant"], f"{where}.destination.tenant"),
                realm=_ident(dest["realm"], f"{where}.destination.realm"),
                synthetic=_bool(dest["synthetic"], f"{where}.destination.synthetic"),
                security_context=_ident(dest["security_context"],
                                        f"{where}.destination.security_context"),
                vertical_forms=tuple((u, r) for u, r in forms),
                vertical_required=_bool(dest["vertical_required"],
                                        f"{where}.destination.vertical_required")),
            families=families))
    return tuple(rules)


def _limits(value: Any) -> dict:
    if type(value) is not dict:
        raise ConfigError("limits", "an object")
    out = dict(DEFAULT_LIMITS)
    for name, given in value.items():
        if name not in DEFAULT_LIMITS:
            raise ConfigError("limits", "a key the configuration does not define")
        low, high = _LIMIT_BOUNDS.get(name, (1, 2 ** 62))
        if type(given) is not int or not low <= given <= high:
            raise ConfigError(f"limits.{name}", "an integer within its bounds")
        out[name] = given
    return out


def _freshness(value: Any) -> dict:
    if type(value) is not dict:
        raise ConfigError("freshness_seconds", "an object of domain -> seconds")
    out = dict(DEFAULT_FRESHNESS)
    for domain, seconds in value.items():
        if domain not in DOMAINS:
            raise ConfigError("freshness_seconds", "a domain the contract does not define")
        out[domain] = _seconds(seconds, f"freshness_seconds.{domain}", 0.0, 86_400.0,
                               low_open=False)
    return out


def _build(doc: Any) -> BridgeConfig:
    if type(doc) is not dict:
        raise ConfigError("(file)", "a JSON object")
    for key in doc:
        if key not in KEYS:
            raise ConfigError("(file)", "a key the configuration does not define")
    for key in REQUIRED:
        if key not in doc:
            raise ConfigError(key, "required")
    mode = doc.get("mode", "ingest")
    if mode not in MODES or type(mode) is not str:
        raise ConfigError("mode", "ingest or bidirectional")
    credential = doc["credential_ref"]
    if type(credential) is not str or _ENV_REF.fullmatch(credential) is None:
        raise ConfigError("credential_ref", "env:NAME, a reference and never a value")
    realm_kind = doc["realm_kind"]
    if realm_kind not in REALM_KINDS or type(realm_kind) is not str:
        raise ConfigError("realm_kind", "live, exercise or replay")
    scopes = doc["approved_origin_scopes"]
    if type(scopes) is not list or not scopes:
        raise ConfigError("approved_origin_scopes", "a non-empty list of identifiers")
    for scope in scopes:
        _ident(scope, "approved_origin_scopes")
    versions = doc["cdm_schema_version"]
    if type(versions) is not list or not versions or \
            any(type(v) is not str or _SEMVER.fullmatch(v) is None for v in versions):
        raise ConfigError("cdm_schema_version", "an explicit non-empty list of versions")
    peer = doc.get("peer_profile")
    if peer is not None and type(peer) is not dict:
        raise ConfigError("peer_profile", "null or an object")
    allocations = doc.get("number_allocations_ref")
    if allocations is not None:
        _ident(allocations, "number_allocations_ref")
    config = BridgeConfig(
        config_revision=_text(doc, "config_revision"),
        mode=mode,
        gateway_base_url=_url(doc["gateway_base_url"]),
        gateway_id=_ident(doc["gateway_id"], "gateway_id"),
        consumer_id=_ident(doc["consumer_id"], "consumer_id"),
        credential_ref=credential,
        tenant=_ident(doc["tenant"], "tenant"),
        realm=_ident(doc["realm"], "realm"),
        realm_kind=realm_kind,
        synthetic=_bool(doc["synthetic"], "synthetic"),
        security_context=_ident(doc["security_context"], "security_context"),
        approved_origin_scopes=frozenset(scopes),
        native_profile=_text(doc, "native_profile"),
        cdm_schema_version=tuple(versions),
        receive_families=_families(doc.get("receive_families",
                                           list(DEFAULT_RECEIVE_FAMILIES)), "receive_families"),
        required_families=_families(doc.get("required_families", []), "required_families"),
        transmit_families=_families(doc.get("transmit_families", []), "transmit_families"),
        export_policy=_policy(doc.get("export_policy", [])),
        number_allocations_ref=allocations,
        peer_profile=peer,
        freshness_seconds=_freshness(doc.get("freshness_seconds", {})),
        request_deadline_seconds=_seconds(doc.get("request_deadline_seconds", 25),
                                          "request_deadline_seconds", 0.0, 3600.0,
                                          low_open=True),
        long_poll_seconds=_seconds(doc.get("long_poll_seconds", 20), "long_poll_seconds",
                                   0.0, 300.0, low_open=False),
        connect_timeout_seconds=_seconds(doc.get("connect_timeout_seconds", 5),
                                         "connect_timeout_seconds", 0.0, 300.0, low_open=True),
        transport_allowance_seconds=_seconds(doc.get("transport_allowance_seconds", 2),
                                             "transport_allowance_seconds", 0.0, 300.0,
                                             low_open=True),
        outbound_max_age_seconds=_seconds(doc.get("outbound_max_age_seconds", 10),
                                          "outbound_max_age_seconds", 0.0, 3600.0,
                                          low_open=True),
        limits=_limits(doc.get("limits", {})),
        store_path=_text(doc, "store_path", 1, 4096),
        lease_ttl_seconds=_seconds(doc.get("lease_ttl_seconds", 30), "lease_ttl_seconds",
                                   0.0, 3600.0, low_open=True),
        idle_poll_seconds=_seconds(doc.get("idle_poll_seconds", 1), "idle_poll_seconds",
                                   0.0, 300.0, low_open=True),
    )
    _cross_rules(config)
    return config


def _cross_rules(config: BridgeConfig) -> None:
    if config.request_deadline_seconds <= \
            config.long_poll_seconds + config.transport_allowance_seconds:
        raise ConfigError("request_deadline_seconds",
                          "must exceed long_poll_seconds plus transport_allowance_seconds")
    if config.connect_timeout_seconds >= config.request_deadline_seconds:
        raise ConfigError("connect_timeout_seconds", "must be below request_deadline_seconds")
    if config.idle_poll_seconds >= config.lease_ttl_seconds:
        raise ConfigError("idle_poll_seconds", "must be below lease_ttl_seconds")
    if config.lease_ttl_seconds <= config.request_deadline_seconds:
        raise ConfigError("lease_ttl_seconds", "must exceed request_deadline_seconds")
    if config.mode == "bidirectional" and not config.export_policy:
        raise ConfigError("export_policy", "bidirectional mode requires a transmit policy")
    if config.realm_kind == "replay":
        if not config.synthetic:
            raise ConfigError("synthetic", "a replay realm is synthetic (REQ132)")
        if config.mode != "ingest":
            raise ConfigError("mode", "a replay realm never exports (REQ132)")
        if config.transmit_families:
            raise ConfigError("transmit_families", "empty in a replay realm (REQ132)")
        if config.peer_profile is not None:
            raise ConfigError("peer_profile", "null in a replay realm (REQ132)")
