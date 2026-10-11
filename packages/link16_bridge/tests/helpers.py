"""Shared test helpers: the packaged fixtures, report and notice builders, and `Harness`, which
wires a synthetic provider, its loopback server, a client, a sink and a bridge on a manual clock.

The reports are the `link16_gateway` adapter's packaged fixtures, read through the installed
`synapse_cdm` (never from a bundle path), with variants derived in memory. Every credential is a
readable low-entropy string built at run time.
"""
from __future__ import annotations

import copy
import datetime as _dt
import importlib.resources
import json
import pathlib
import random
from typing import Any

from synapse_link16_bridge.bridge import Bridge, MemorySink
from synapse_link16_bridge.clock import ManualClock, RecordingSleeper
from synapse_link16_bridge.config import BridgeConfig
from synapse_link16_bridge.gateway.client import GatewayClient
from synapse_link16_bridge.gateway.provider import SyntheticProvider
from synapse_link16_bridge.gateway.server import GatewayServer

FIXTURES = importlib.resources.files("synapse_cdm") / "fixtures" / "link16_gateway"
#: The repository root when the tests run inside a checkout, else None.
REPO = next((p for p in pathlib.Path(__file__).resolve().parents
             if (p / "schemas" / "link16_gateway").is_dir() and (p / "packages").is_dir()), None)
CHANNEL = "c1"
CONSUMER = "consumer-1"
CREDENTIAL = "synthetic-bearer-" + "a" * 16
OTHER_CREDENTIAL = "synthetic-bearer-" + "b" * 16
T0 = _dt.datetime(2026, 10, 4, 12, 0, 0, tzinfo=_dt.timezone.utc)


def uid(n: int) -> str:
    """A canonical lowercase UUID numbered `n`."""
    return f"00000000-0000-4000-8000-{n:012x}"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def stamp(offset_ms: int = 0) -> str:
    moment = T0 + _dt.timedelta(milliseconds=offset_ms)
    return f"{moment:%Y-%m-%dT%H:%M:%S}.{moment.microsecond // 1000:03d}Z"


def report(n: int = 1, *, base: str = "air_hae_metres_friendly.json", at_ms: int = 0, **changes: Any) -> dict:
    """A report numbered `n`: the fixture `base` with its own record id, every time at T0 +
    `at_ms`, then `changes` applied (a key set to a value replaces it)."""
    body = fixture(base)
    body["record_id"] = uid(n)
    body["received_at"] = stamp(at_ms)
    body["effective_at"] = stamp(at_ms)
    if body["position"] is not None:
        body["position"]["observed_at"] = stamp(at_ms)
    if body["kinematics"] is not None:
        body["kinematics"]["observed_at"] = stamp(at_ms)
    for key, value in changes.items():
        body[key] = copy.deepcopy(value)
    return body


def notice(n: int, operation: str, *, at_ms: int = 0, track_number: str | None = "TEST-0001",
           incarnation: str | None = "0", **changes: Any) -> dict:
    body = {"record_id": uid(n), "session_id": uid(0), "sequence": "0",
            "received_at": stamp(at_ms), "effective_at": stamp(at_ms), "tenant": "demo",
            "realm": "test-only", "synthetic": True, "origin_scope": "exercise-source-1",
            "security_context": "SYNTHETIC-UNCLASSIFIED", "track_number": track_number,
            "incarnation": incarnation, "operation": operation,
            "reason": "synthetic lifecycle test"}
    body.update(changes)
    return body


def tuple_of(body: dict) -> dict:
    return {k: body[k] for k in ("tenant", "realm", "synthetic", "origin_scope", "track_number",
                                 "incarnation")}


def config_dict(store_path: str, base_url: str = "http://127.0.0.1:9", **changes: Any) -> dict:
    document = {
        "config_revision": "rev-1", "gateway_base_url": base_url,
        "gateway_id": "synthetic-gateway-1", "consumer_id": CONSUMER,
        "credential_ref": "env:SYNAPSE_LINK16_TEST_CREDENTIAL", "tenant": "demo",
        "realm": "test-only", "realm_kind": "exercise", "synthetic": True,
        "security_context": "SYNTHETIC-UNCLASSIFIED",
        "approved_origin_scopes": ["exercise-source-1"],
        "native_profile": "SYNTHETIC-NO-NATIVE-CODEC", "cdm_schema_version": ["3.0.0"],
        "store_path": store_path,
    }
    document.update(changes)
    return document


def bidirectional(**destination: Any) -> dict:
    """The configuration changes that enable export to peer `peer-1` in realm `dest-realm`."""
    dest = {"peer_id": "peer-1", "tenant": "demo", "realm": "dest-realm", "synthetic": True,
            "security_context": "SYNTHETIC-DEST", "vertical_forms": [["m", "HAE"], ["ft", "HAE"]],
            "vertical_required": False}
    dest.update(destination)
    return {"mode": "bidirectional", "transmit_families": ["J3.2", "J3.3", "J3.4", "J3.5"],
            "export_policy": [{
                "policy_revision": "policy-1",
                "source": {"tenant": "demo", "realm": "test-only", "synthetic": True,
                           "label_set": ["SYNTHETIC-UNCLASSIFIED"]},
                "destination": dest, "families": ["J3.2", "J3.3"], "forwarding": False}]}


DEST_TUPLE = {"tenant": "demo", "realm": "dest-realm", "synthetic": True,
              "origin_scope": "dest-scope", "track_number": "DEST-0001", "incarnation": "0"}


class Harness:
    """A provider, its server, a client, a sink and a bridge, all closed by `close()`."""

    def __init__(self, tmp_path: pathlib.Path, *, accepts: tuple[str, ...] = ("3.0.0",),
                 provider_kwargs: dict | None = None, deadline: float = 5.0,
                 long_poll: float = 0.0, faults=None, **config_changes: Any) -> None:
        self.tmp_path = tmp_path
        self.clock = ManualClock(T0)
        self.provider = SyntheticProvider(self.clock, **(provider_kwargs or {}))
        self.provider.add_channel(CHANNEL)
        self.provider.add_channel("c2")
        self.server = GatewayServer(self.provider, {CREDENTIAL: (CONSUMER, CHANNEL),
                                                    OTHER_CREDENTIAL: ("consumer-2", "c2")},
                                    long_poll_seconds=long_poll).start()
        self.accepts = accepts
        self.deadline = deadline
        self.config_changes = config_changes
        self.store_path = str(tmp_path / "bridge.sqlite")
        self.sink = MemorySink(accepts)
        self.sleeper = RecordingSleeper()
        self.faults = faults
        self.bridges: list[Bridge] = []
        self.bridge = self.new_bridge(faults=faults)

    def config(self, **changes: Any) -> BridgeConfig:
        merged = dict(self.config_changes)
        merged.update(changes)
        return BridgeConfig.from_dict(config_dict(self.store_path, self.server.base_url,
                                                  **merged))

    def client(self, credential: str = CREDENTIAL, deadline: float | None = None) -> GatewayClient:
        return GatewayClient(self.server.base_url, credential, connect_timeout=2,
                             request_deadline=deadline or self.deadline)

    def new_bridge(self, *, faults=None, holder: str = "holder-a", start: bool = True,
                   config: BridgeConfig | None = None, sink=None, **kwargs: Any) -> Bridge:
        from synapse_link16_bridge import faults as _faults
        bridge = Bridge(config or self.config(), sink=sink or self.sink, client=self.client(),
                        clock=self.clock, sleeper=self.sleeper, rng=random.Random(5),
                        faults=faults or _faults.NO_FAULTS, holder=holder, **kwargs)
        self.bridges.append(bridge)
        if start:
            bridge.start()
        return bridge

    def publish(self, body: dict, *, channel: str = CHANNEL, stamp_delivery: bool = True) -> int:
        return self.provider.publish(channel, "report", body, stamp=stamp_delivery)

    def publish_notice(self, body: dict, *, channel: str = CHANNEL) -> int:
        return self.provider.publish(channel, "notice", body)

    def run(self, bridge: Bridge | None = None) -> dict:
        return (bridge or self.bridge).run_once()

    def rows(self, sql: str, params: tuple = (), bridge: Bridge | None = None) -> list:
        return (bridge or self.bridge).store.query(sql, params)

    def counters(self, bridge: Bridge | None = None) -> dict:
        return (bridge or self.bridge).store.counters()

    def close(self) -> None:
        for bridge in self.bridges:
            try:
                bridge.close()
            except Exception:                           # noqa: BLE001 - teardown
                pass
        self.server.stop()
        self.provider.close()


def assert_accounting(counters: dict) -> None:
    """REQ162: every fed input is accepted, refused, a duplicate or dropped by capacity."""
    assert counters.get("fed", 0) == (counters.get("accepted", 0) + counters.get("refused", 0) +
                                      counters.get("duplicate", 0) +
                                      counters.get("dropped_by_capacity", 0)), counters


def payload(sink: MemorySink, key: str) -> dict:
    return json.loads(sink.events[key][1])
