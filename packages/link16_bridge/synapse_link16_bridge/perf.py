"""The measurement harness for the performance gate (REQ161, REQ162; acceptance row F01).

`run(...)` feeds a synthetic report stream through the synthetic provider and its loopback server
into two bridges (two tenants, two channels, two stores, the same track numbers) and records:

- the rig: CPU model, CPU count, platform, Python, SQLite, the synapse-cdm and bridge versions and
  the store's file system;
- the accounting gates (REQ162), which are hard gates at any scale: every input accounted for
  (`fed = accepted + refused + duplicate + dropped_by_capacity`, and every published record fed or
  in the provider's loss accounting), zero cross-tenant identity collisions, zero invented
  coordinates (every published position is its report's), zero unintended sends (the provider's
  send log is empty);
- the measurements: mapping latency (the adapter call), end-to-end durable publication latency
  (from the provider's commit to the bridge's outbox commit), and the peak resident set size.

`evidence_eligible` is true only on Linux x86_64 with at least four CPUs and with the full
parameters of REQ161 (1000 reports per second for 1800 seconds, a burst of 5000 per second for 10
seconds, 100 000 identities); only then are the targets (p99 mapping at most 10 ms, p99
publication at most 100 ms, RSS below 2 GiB) judged. Anywhere else the run checks the accounting
gates and its timings are not evidence of anything: F01 stays NOT_RUN until the maintainer runs
this on the named rig.
"""
from __future__ import annotations

import array
import json
import os
import pathlib
import platform
import random
import sqlite3
import sys
import threading
import time
from typing import Callable

from synapse_cdm import times
from synapse_cdm.version import PACKAGE_VERSION, SCHEMA_VERSION

from synapse_link16_bridge._version import __version__
from synapse_link16_bridge.bridge import Bridge
from synapse_link16_bridge.config import BridgeConfig
from synapse_link16_bridge.gateway.client import GatewayClient
from synapse_link16_bridge.gateway.provider import SyntheticProvider
from synapse_link16_bridge.gateway.server import GatewayServer

FULL = {"rate": 1000, "duration": 1800, "burst": (5000, 10), "identities": 100_000}
TARGETS = {"mapping_p99_ms": 10.0, "publication_p99_ms": 100.0, "rss_bytes": 2 * 1024 ** 3}
TENANTS = ("tenant-a", "tenant-b")
PROFILE = "SYNTHETIC-NO-NATIVE-CODEC"


def _record_id(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012x}"


def _index(record_id: str) -> int:
    return int(record_id.rsplit("-", 1)[1], 16)


def _report(index: int, tenant: str, identities: int, now: str) -> dict:
    number = index % identities
    lat = round(-80 + (number * 7919 % 16000) / 100.0, 2)
    lon = round(-170 + (number * 104729 % 34000) / 100.0, 2)
    return {
        "profile": "sc-link16-gateway/1.0.0", "record_id": _record_id(index),
        "gateway_id": "perf-gateway", "session_id": "00000000-0000-4000-8000-000000000000",
        "sequence": "0", "received_at": now, "effective_at": now, "time_basis": "EXERCISE",
        "time_evidence": "synthetic measurement stream", "tenant": tenant, "realm": "perf",
        "synthetic": True, "origin_scope": "perf-scope", "reporter": "SIMULATED",
        "track_number": f"PERF-{number}", "incarnation": "0", "message_family": "J3.2",
        "native_profile": PROFILE, "domain": "AIR", "entity_kind": "PLATFORM",
        "identity": "UNKNOWN", "identity_code": None,
        "position": {"observed_at": now, "lat_deg": lat, "lon_deg": lon, "method": "SENSOR",
                     "vertical": None},
        "kinematics": None, "quality_code": None, "security_context": "SYNTHETIC-PERF",
        "source_fields": {}, "extensions": {}}


def rig(store_dir: str) -> dict:
    model = platform.processor() or "unknown"
    cpuinfo = pathlib.Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(errors="replace").splitlines():
            if line.startswith("model name"):
                model = line.split(":", 1)[1].strip()
                break
    disk = {"filesystem": "unknown"}
    mounts = pathlib.Path("/proc/mounts")
    target = os.path.realpath(store_dir)
    if mounts.is_file():
        best = ""
        for line in mounts.read_text(errors="replace").splitlines():
            parts = line.split()
            if len(parts) > 2 and target.startswith(parts[1]) and len(parts[1]) > len(best):
                best, disk = parts[1], {"filesystem": parts[2], "mount": parts[1]}
    stats = os.statvfs(store_dir)
    disk["free_bytes"] = stats.f_bavail * stats.f_frsize
    return {"cpu_model": model, "cpu_count": os.cpu_count(), "machine": platform.machine(),
            "system": sys.platform, "platform": platform.platform(),
            "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
            "synapse_cdm": PACKAGE_VERSION, "synapse_link16_bridge": __version__, "disk": disk}


def _p99(values) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(0.99 * len(ordered)))] * 1000.0


def _rss_bytes() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


class _CheckingSink:
    """Counts deliveries and checks each published position against its own report."""

    def __init__(self, accepts: tuple[str, ...]) -> None:
        self.accepts = accepts
        self.delivered = 0
        self.invented = 0
        self.entity_ids: set[str] = set()

    def deliver(self, event_key: str, kind: str, payload: bytes, flags: tuple[str, ...]) -> None:
        self.delivered += 1
        if kind != "cdm":
            return
        document = json.loads(payload)
        if document.get("object_kind") == "entity":
            self.entity_ids.add(document["entity_id"])
            report = document["residual"]["data"]["report"]
            position = document.get("position")
            if position is not None and (position["lat"] != report["position"]["lat_deg"] or
                                         position["lon"] != report["position"]["lon_deg"]):
                self.invented += 1
            if position is None and report["position"] is not None and \
                    "POSITION_NOT_PROJECTED_CDM3" not in flags:
                self.invented += 1


def run(*, rate: int, duration: int, burst: str = "0:0", identities: int, store_dir: str,
        sleeper: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.perf_counter) -> dict:
    burst_rate, burst_seconds = (int(part) for part in burst.split(":"))
    pathlib.Path(store_dir).mkdir(parents=True, exist_ok=True)
    clock = times.utc_now
    provider = SyntheticProvider(clock, gateway_id="perf-gateway", native_profiles=(PROFILE,))
    published_at = {tenant: array.array("d") for tenant in TENANTS}
    bindings = {}
    for tenant in TENANTS:
        provider.add_channel(tenant)
        bindings["perf-" + tenant + "-" + "x" * 8] = ("perf-consumer", tenant)
    server = GatewayServer(provider, bindings).start()
    bridges, sinks, mapping = {}, {}, array.array("d")
    publication = array.array("d")
    try:
        for tenant in TENANTS:
            config = BridgeConfig.from_dict({
                "config_revision": "perf-1", "gateway_base_url": server.base_url,
                "gateway_id": "perf-gateway", "consumer_id": "perf-consumer",
                "credential_ref": "env:SYNAPSE_LINK16_PERF_CREDENTIAL", "tenant": tenant,
                "realm": "perf", "realm_kind": "exercise", "synthetic": True,
                "security_context": "SYNTHETIC-PERF", "approved_origin_scopes": ["perf-scope"],
                "native_profile": PROFILE, "cdm_schema_version": [SCHEMA_VERSION],
                "store_path": str(pathlib.Path(store_dir) / f"{tenant}.sqlite"),
                "limits": {"fetch_limit": 1000, "max_identities": max(identities, 1)}})
            credential = "perf-" + tenant + "-" + "x" * 8
            client = GatewayClient(server.base_url, credential, connect_timeout=5,
                                   request_deadline=25)
            sinks[tenant] = _CheckingSink((SCHEMA_VERSION,))
            bridge = Bridge(config, sink=sinks[tenant], client=client, rng=random.Random(0),
                            sleeper=sleeper, monotonic=monotonic)
            if bridge.start() != "READY":
                raise RuntimeError("a measurement bridge did not start")
            translator = bridge.ingestor.translator
            original = translator.translate

            def timed(body, _original=original):
                started = monotonic()
                try:
                    return _original(body)
                finally:
                    mapping.append(monotonic() - started)

            translator.translate = timed
            bridges[tenant] = bridge
        total = {"count": 0}
        done = threading.Event()

        def feed() -> None:
            index = 0
            started = monotonic()
            for second in range(duration):
                count = rate + (burst_rate if second < burst_seconds else 0)
                now = times.render(clock())
                for _ in range(count):
                    for tenant in TENANTS:
                        provider.publish(tenant, "report", _report(index, tenant, identities,
                                                                   now))
                        published_at[tenant].append(monotonic())
                    index += 1
                total["count"] = index
                sleeper(max(0.0, second + 1 - (monotonic() - started)))
            done.set()

        feeder = threading.Thread(target=feed, daemon=True)
        feeder.start()
        quiet = 0
        while True:
            idle = True
            for tenant, bridge in bridges.items():
                result = bridge.run_once()
                committed = monotonic()
                for record_key, disposition, _code in result.get("dispositions", []):
                    if disposition == "ACCEPTED" and record_key.startswith("00000000-"):
                        publication.append(committed - published_at[tenant][_index(record_key)])
                if result.get("fetched") and result.get("dispositions"):
                    idle = False
            if not done.is_set():
                continue
            quiet = quiet + 1 if idle else 0
            drained = all(b.store.counters().get("fed", 0) +
                          sum(loss["count"] for loss in provider.losses(t)) >= total["count"]
                          for t, b in bridges.items())
            if (idle and drained) or quiet >= 100:
                break
        feeder.join()
        accounting = {}
        for tenant, bridge in bridges.items():
            counters = bridge.store.counters()
            fed = counters.get("fed", 0)
            accounting[tenant] = {
                "published": total["count"], "fed": fed,
                "accepted": counters.get("accepted", 0), "refused": counters.get("refused", 0),
                "duplicate": counters.get("duplicate", 0),
                "dropped_by_capacity": counters.get("dropped_by_capacity", 0),
                "provider_losses": sum(loss["count"] for loss in provider.losses(tenant))}
        collisions = len(sinks[TENANTS[0]].entity_ids & sinks[TENANTS[1]].entity_ids)
        invented = sum(sink.invented for sink in sinks.values())
        sends = len(provider.sent())
        gates = {
            "every_input_accounted_for": all(
                a["fed"] == a["accepted"] + a["refused"] + a["duplicate"] +
                a["dropped_by_capacity"] and a["published"] == a["fed"] + a["provider_losses"]
                for a in accounting.values()),
            "zero_cross_tenant_identity_collisions": collisions == 0,
            "zero_invented_coordinates": invented == 0,
            "zero_unintended_sends": sends == 0,
        }
    finally:
        for bridge in bridges.values():
            bridge.close()
        server.stop()
        provider.close()
    rig_record = rig(store_dir)
    full = rate >= FULL["rate"] and duration >= FULL["duration"] and \
        (burst_rate, burst_seconds) >= FULL["burst"] and identities >= FULL["identities"]
    eligible = rig_record["system"].startswith("linux") and rig_record["machine"] == "x86_64" \
        and (rig_record["cpu_count"] or 0) >= 4 and full
    measurements = {"mapping_p99_ms": _p99(mapping), "publication_p99_ms": _p99(publication),
                    "rss_bytes": _rss_bytes(), "mapping_samples": len(mapping),
                    "publication_samples": len(publication)}
    targets = "NOT_EVALUATED: not the named rig with the full parameters (REQ161)"
    if eligible:
        targets = {name: "PASS" if measurements[name] is not None and
                   measurements[name] <= bound and (name != "rss_bytes" or
                                                     measurements[name] < bound) else "FAIL"
                   for name, bound in TARGETS.items()}
    return {"rig": rig_record,
            "parameters": {"rate": rate, "duration": duration, "burst": burst,
                           "identities": identities},
            "evidence_eligible": eligible,
            "accounting": accounting,
            "cross_tenant_collisions": collisions, "invented_coordinates": invented,
            "unintended_sends": sends,
            "gates": {name: "PASS" if held else "FAIL" for name, held in gates.items()},
            "measurements": measurements, "targets": targets}
