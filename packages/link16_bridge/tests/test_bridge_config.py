"""The deployment configuration (SPEC section 15, REQ004, REQ040, REQ061, REQ130, REQ132,
REQ133). Every refusal names the key and the rule, never the value."""
import json

import pytest

from helpers import config_dict
from synapse_link16_bridge.bridge import Bridge, MemorySink
from synapse_link16_bridge.config import BridgeConfig, ConfigError


def build(tmp_path, **changes):
    return BridgeConfig.from_dict(config_dict(str(tmp_path / "s.sqlite"), **changes))


def refused(tmp_path, **changes):
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, **changes)
    return caught.value.key, caught.value.rule


def test_default_mode_is_ingest_and_the_specification_defaults_apply(tmp_path):
    config = build(tmp_path)
    assert config.mode == "ingest"
    assert (config.long_poll_seconds, config.request_deadline_seconds,
            config.connect_timeout_seconds, config.transport_allowance_seconds,
            config.outbound_max_age_seconds) == (20.0, 25.0, 5.0, 2.0, 10.0)
    assert config.freshness_seconds == {"AIR": 30.0, "SURFACE": 120.0, "SUBSURFACE": 120.0,
                                        "LAND": 120.0, "UNKNOWN": 120.0}
    assert config.receive_families == ("J3.2", "J3.3", "J3.4", "J3.5")
    assert config.transmit_families == () and config.export_policy == ()
    assert (config.limits["max_identities"], config.limits["max_queued_reports"],
            config.limits["max_queued_report_bytes"], config.limits["max_queued_exports"],
            config.limits["max_queued_export_bytes"], config.limits["max_quarantine_bytes"]) == \
        (100000, 10000, 67108864, 4096, 16777216, 1073741824)
    assert config.credential_env == "SYNAPSE_LINK16_TEST_CREDENTIAL"


def test_deadlines_are_configurable_within_both_rules(tmp_path):
    """REQ061 and section 15: the deadline must EXCEED long poll plus the transport allowance,
    and the connection deadline must be below the request deadline."""
    assert refused(tmp_path, request_deadline_seconds=22) == (
        "request_deadline_seconds", "must exceed long_poll_seconds plus transport_allowance_seconds")
    assert build(tmp_path, request_deadline_seconds=22.001).request_deadline_seconds == 22.001
    assert refused(tmp_path, connect_timeout_seconds=25) == (
        "connect_timeout_seconds", "must be below request_deadline_seconds")
    assert build(tmp_path, long_poll_seconds=0, request_deadline_seconds=3,
                 connect_timeout_seconds=2).long_poll_seconds == 0.0
    assert refused(tmp_path, request_deadline_seconds=0) == ("request_deadline_seconds",
                                                              "out of the deployment bounds")
    assert refused(tmp_path, long_poll_seconds=float("inf")) == (
        "long_poll_seconds", "a finite number of seconds")


@pytest.mark.parametrize("changes, expected", [
    ({"surplus": 1}, ("(file)", "a key the configuration does not define")),
    ({"mode": "transmit"}, ("mode", "ingest or bidirectional")),
    ({"realm_kind": "test"}, ("realm_kind", "live, exercise or replay")),
    ({"synthetic": "true"}, ("synthetic", "a boolean")),
    ({"approved_origin_scopes": []}, ("approved_origin_scopes",
                                      "a non-empty list of identifiers")),
    ({"cdm_schema_version": []}, ("cdm_schema_version", "an explicit non-empty list of versions")),
    ({"cdm_schema_version": ["3.0"]}, ("cdm_schema_version",
                                       "an explicit non-empty list of versions")),
    ({"tenant": "demo\n"}, ("tenant", "an identifier")),
    ({"receive_families": ["J3.2", "J3.2"]}, ("receive_families", "a list of distinct family "
                                                                  "labels of 1 to 32 characters")),
    ({"freshness_seconds": {"SPACE": 1}}, ("freshness_seconds",
                                           "a domain the contract does not define")),
    ({"freshness_seconds": {"AIR": -1}}, ("freshness_seconds.AIR",
                                          "out of the deployment bounds")),
    ({"limits": {"fetch_limit": 1001}}, ("limits.fetch_limit", "an integer within its bounds")),
    ({"limits": {"max_body_bytes": 8 * 1024 * 1024 + 1}}, ("limits.max_body_bytes",
                                                            "an integer within its bounds")),
    ({"peer_profile": "peer"}, ("peer_profile", "null or an object")),
])
def test_invalid_keys_are_refused_by_key_and_rule(tmp_path, changes, expected):
    assert refused(tmp_path, **changes) == expected


def test_a_required_key_missing_is_refused(tmp_path):
    document = config_dict(str(tmp_path / "s.sqlite"))
    del document["cdm_schema_version"]
    with pytest.raises(ConfigError) as caught:
        BridgeConfig.from_dict(document)
    assert (caught.value.key, caught.value.rule) == ("cdm_schema_version", "required")


def test_the_file_is_read_strictly(tmp_path):
    good = json.dumps(config_dict(str(tmp_path / "s.sqlite"))).encode()
    assert BridgeConfig.from_octets(good).config_revision == "rev-1"
    with pytest.raises(ConfigError) as caught:
        BridgeConfig.from_octets(good[:-1] + b',"tenant":"demo"}')
    assert (caught.value.key, caught.value.rule) == ("(file)",
                                                     "not strict JSON (duplicate object key)")
    with pytest.raises(ConfigError) as caught:
        BridgeConfig.from_octets(b"\xef\xbb\xbf" + good)
    assert caught.value.rule == "not strict JSON (byte order mark)"
    with pytest.raises(ConfigError) as caught:
        BridgeConfig.load(tmp_path / "absent.json")
    assert (caught.value.key, caught.value.rule) == ("(file)", "not readable")


def test_credentials_are_referenced_never_embedded(tmp_path):
    """REQ130 and section 15: only `env:NAME`; a literal is refused and never echoed."""
    literal = "literal-" + "q" * 12
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, credential_ref=literal)
    assert (caught.value.key, caught.value.rule) == ("credential_ref",
                                                     "env:NAME, a reference and never a value")
    assert literal not in str(caught.value)
    for wrong in ("env:lower_case", "env:", "ENV:NAME", "env:NAME\n", "file:/x"):
        assert refused(tmp_path, credential_ref=wrong)[0] == "credential_ref"


@pytest.mark.parametrize("url, accepted", [
    ("https://gateway.example:8443/base", True),
    ("http://127.0.0.1:8080", True),
    ("http://[::1]:8080", True),
    ("http://localhost", True),
    ("http://10.0.0.1:8080", False),
    ("http://127.0.0.1.example.net", False),
    ("http://localhost.example.net", False),
    ("ftp://127.0.0.1", False),
    ("https://user:pw@gateway.example", False),
    ("https://gateway.example/?x=1", False),
    ("https://gateway.example:99999", False),
    ("gateway.example", False),
])
def test_the_gateway_url_is_explicit_and_http_is_loopback_only(tmp_path, url, accepted):
    if accepted:
        assert build(tmp_path, gateway_base_url=url).gateway_base_url == url
    else:
        assert refused(tmp_path, gateway_base_url=url)[0] == "gateway_base_url"


def test_bidirectional_requires_a_transmit_policy(tmp_path):
    assert refused(tmp_path, mode="bidirectional") == (
        "export_policy", "bidirectional mode requires a transmit policy")


def test_a_forwarding_rule_is_refused(tmp_path):
    from helpers import bidirectional
    changes = bidirectional()
    changes["export_policy"][0]["forwarding"] = True
    assert refused(tmp_path, **changes) == ("export_policy[0].forwarding",
                                            "false: no forwarding profile is implemented (REQ133)")


@pytest.mark.parametrize("changes, expected", [
    ({"synthetic": False}, ("synthetic", "a replay realm is synthetic (REQ132)")),
    ({"transmit_families": ["J3.2"]}, ("transmit_families", "empty in a replay realm (REQ132)")),
    ({"peer_profile": {"addresses": []}}, ("peer_profile", "null in a replay realm (REQ132)")),
])
def test_replay_config_cannot_enable_egress_or_native(tmp_path, changes, expected):
    assert refused(tmp_path, realm_kind="replay", **changes) == expected
    from helpers import bidirectional
    assert refused(tmp_path, realm_kind="replay", **bidirectional()) == (
        "mode", "a replay realm never exports (REQ132)")


def test_invalid_config_leaves_transmit_disabled(tmp_path):
    """REQ004: a Bridge exists only for a parsed configuration; a refused one builds nothing."""
    with pytest.raises(ConfigError):
        build(tmp_path, mode="bidirectional")
    with pytest.raises(TypeError):
        Bridge(config_dict(str(tmp_path / "s.sqlite"), mode="bidirectional"), sink=MemorySink())


def test_the_configuration_is_immutable(tmp_path):
    config = build(tmp_path)
    with pytest.raises(AttributeError):
        config.mode = "bidirectional"


def test_missing_required_family_fails_release_readiness(make_harness):
    """REQ040: the gateway lacks J3.4 and the configuration requires it: the internal stage is
    NOT_READY while ingest of the other families continues."""
    from helpers import report
    h = make_harness(provider_kwargs={"receive_families": ("J3.2", "J3.3", "J3.5")},
                     required_families=["J3.4"])
    assert h.bridge.status == "READY"
    stages = h.bridge.status_report()["release_stages"]
    assert stages["internal_gateway_translation"] == "NOT_READY"
    assert stages["native_codec"] == "BLOCKED_EXTERNAL_EVIDENCE"
    h.publish(report(1))
    h.publish(report(2, base="subsurface_unknown_method.json", track_number="SUB-1"))
    result = h.run()
    assert [d[1:] for d in result["dispositions"]] == [("ACCEPTED", None),
                                                        ("OPAQUE", "UNSUPPORTED_MESSAGE")]


def test_the_idle_interval_is_positive_and_below_the_lease_lifetime(tmp_path):
    """Fix round 1 (2026-10-11, R4-F6): `idle_poll_seconds` defaults to 1, is above 0, and is
    below `lease_ttl_seconds` so an idle loop renews the lease in time."""
    assert build(tmp_path).idle_poll_seconds == 1.0
    assert build(tmp_path, idle_poll_seconds=29.5).idle_poll_seconds == 29.5
    assert refused(tmp_path, idle_poll_seconds=0) == ("idle_poll_seconds",
                                                       "out of the deployment bounds")
    assert refused(tmp_path, idle_poll_seconds=30) == ("idle_poll_seconds",
                                                        "must be below lease_ttl_seconds")
    assert refused(tmp_path, idle_poll_seconds="1") == ("idle_poll_seconds",
                                                         "a finite number of seconds")


def test_the_lease_outlives_the_request_deadline(tmp_path):
    """RUNTIME-3 (A2F, 2026-10-11): `lease_ttl_seconds` must exceed `request_deadline_seconds`,
    so no single request of a pass outlasts the lease renewed at its start."""
    config = build(tmp_path)
    assert (config.lease_ttl_seconds, config.request_deadline_seconds) == (30.0, 25.0)
    assert refused(tmp_path, lease_ttl_seconds=25) == ("lease_ttl_seconds",
                                                        "must exceed request_deadline_seconds")
    assert refused(tmp_path, lease_ttl_seconds=10, idle_poll_seconds=1) == (
        "lease_ttl_seconds", "must exceed request_deadline_seconds")
    assert build(tmp_path, lease_ttl_seconds=25.001).lease_ttl_seconds == 25.001
    assert build(tmp_path, lease_ttl_seconds=2, request_deadline_seconds=1.5, long_poll_seconds=0,
                 transport_allowance_seconds=0.5, connect_timeout_seconds=1
                 ).lease_ttl_seconds == 2.0


def test_the_sample_cache_limit_is_gone_with_the_cache(tmp_path):
    """HYGIENE-1 (A2F, 2026-10-11): the unread in-memory sample cache was removed, and with it
    the limit that sized it; a configuration naming it is refused as an unknown key."""
    from synapse_link16_bridge.config import DEFAULT_LIMITS
    assert sorted(DEFAULT_LIMITS) == ["batch_retry_max", "fetch_limit", "max_body_bytes",
                                      "max_identities", "max_quarantine_bytes",
                                      "max_queued_export_bytes", "max_queued_exports",
                                      "max_queued_report_bytes", "max_queued_reports"]
    assert refused(tmp_path, limits={"sample_cache": 100}) == (
        "limits", "a key the configuration does not define")
