"""Startup in REQ140's order, and the outcomes missing evidence produces."""
from helpers import DEST_TUPLE, bidirectional, payload, report, uid
from synapse_cdm.models import Entity
from synapse_link16_bridge.bridge import STEPS, Bridge
from synapse_link16_bridge.store import SQL_LEASE_GET, Store

KEY = '["demo","test-only",true,"exercise-source-1","TEST-0001","0"]'


def test_startup_runs_the_ten_steps_in_order(h):
    events = []

    def store_factory(*args, **kwargs):
        events.append("open_store")
        return Store(*args, **kwargs)

    client = h.client()
    real_capabilities = client.capabilities

    def capabilities():
        lease = bridge.store.query(SQL_LEASE_GET, ("channel",))
        events.append(("query_capabilities", lease[0][:2]))
        return real_capabilities()

    client.capabilities = capabilities

    class Sink:
        @property
        def accepts(self):
            events.append("negotiate_schema")
            return ("3.0.0",)

        def deliver(self, *args):
            pass

    bridge = Bridge(h.config(), sink=Sink(), client=client, clock=h.clock, holder="holder-x",
                    store_factory=store_factory)
    h.bridges.append(bridge)
    h.bridge.close()
    assert bridge.start() == "READY"
    assert tuple(bridge.startup_steps) == STEPS == (
        "parse_configuration", "verify_versions_and_policies", "open_store", "acquire_lease",
        "query_capabilities", "verify_gateway_identity_and_native_profile", "negotiate_schema",
        "restore_state", "start_ingest", "enable_exports")
    assert events == ["open_store", ("query_capabilities", ("holder-x", 2)), "negotiate_schema"]


def test_missing_native_profile_gives_degraded_ingest_only(make_harness):
    h = make_harness(provider_kwargs={"native_profiles": ("ANOTHER-PROFILE",)}, **bidirectional())
    assert (h.bridge.status, h.bridge.exports_enabled) == ("DEGRADED_INGEST_ONLY", False)
    h.publish(report(1))
    assert h.run()["dispositions"] == [(uid(1), "ACCEPTED", None)]
    h.bridge.allocate("peer-1", "dest-realm", KEY, DEST_TUPLE, "allocation record")
    entity = Entity.model_validate(payload(h.sink, f"{uid(1)}:0"))
    assert h.bridge.export(entity, None, peer_id="peer-1")["reason"] == "PROFILE_NOT_READY"
    assert h.provider.sent() == []


def test_an_ingest_only_configuration_is_ready_and_never_exports(h):
    assert (h.bridge.status, h.bridge.exports_enabled) == ("READY", False)


def test_gateway_identity_mismatch_is_blocked(make_harness):
    h = make_harness(provider_kwargs={"gateway_id": "another-gateway"})
    h.publish(report(1))
    assert h.bridge.status == "BLOCKED"
    assert h.bridge.blocked_reasons == ["GATEWAY_IDENTITY_MISMATCH"]
    assert h.bridge.startup_steps[-1] == "verify_gateway_identity_and_native_profile"
    assert h.run() == {"fetched": False, "reason": "BLOCKED"}
    assert h.bridge.health()["ready"] is False


def test_a_live_channel_cannot_enable_exports_without_the_native_boundary(make_harness):
    h = make_harness(synthetic=False, realm_kind="live", provider_kwargs={"synthetic": False},
                     **bidirectional(synthetic=False))
    changes = bidirectional(synthetic=False)
    changes["export_policy"][0]["source"]["synthetic"] = False
    h.bridge.close()
    bridge = h.new_bridge(holder="holder-b", config=h.config(**changes))
    assert (bridge.status, bridge.exports_enabled, bridge.native_status) == (
        "DEGRADED_INGEST_ONLY", False, "BLOCKED_EXTERNAL_EVIDENCE")


def test_a_lease_held_by_another_instance_blocks(h):
    other = h.new_bridge(holder="holder-b")
    assert other.status == "BLOCKED" and other.blocked_reasons == ["LEASE_LOST"]
    assert other.startup_steps[-1] == "acquire_lease"


def test_an_unready_provider_blocks_startup(make_harness):
    h = make_harness(provider_kwargs={"unavailable": True})
    assert (h.bridge.status, h.bridge.provider_ready) == ("BLOCKED", False)
    health = h.bridge.health()
    assert health["ready"] is False and "PROVIDER_UNAVAILABLE" in health["blocked_reasons"]


def test_a_stopped_channel_restarts_only_under_a_new_configuration_revision(h):
    h.publish(report(1, security_context="ESCALATED-LABEL"))
    assert h.run()["reason"] == "SECURITY_CONTEXT_MISMATCH"
    h.bridge.close()
    same = h.new_bridge(holder="holder-b")
    assert same.store.channel()["state"] == "STOPPED"
    same.close()
    renewed = h.new_bridge(holder="holder-c", config=h.config(config_revision="rev-2"))
    assert renewed.store.channel()["state"] == "NORMAL"
    assert renewed.store.query("SELECT kind, code FROM audit ORDER BY seq")[-1] == (
        "channel_restart", "CONFIG_REVISION_RESTART")
