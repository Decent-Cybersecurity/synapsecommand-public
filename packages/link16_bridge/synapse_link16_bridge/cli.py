"""`synapse-link16-bridge`: the command line.

Exit codes: 0 done; 2 a usage error or a configuration refused; 3 blocked (the native boundary,
the lease, the gateway, the negotiation); 4 an operation refused (an operator record that does
not apply, an export denied). Every state-changing operator command writes an audit row holding
the operator's `--evidence` text (at most 1024 characters). A credential is never a command-line
argument: the configuration's `credential_ref` names the environment variable the bridge reads,
and `serve-gateway` reads the variable `--credential-env` names.

Subcommands: `check-config`, `serve-gateway`, `run`, `health`, `status`, `export`, `reconcile`,
`recover`, `resync`, `resync-identities`, `resolve-reuse`, `resolve-send`, `allocate`, `evidence`
(the separately controlled reader of raw batch evidence, REQ151), `native-status`, `schema` and
`perf`.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Sequence

from synapse_cdm import times
from synapse_cdm.models import Entity, Track

from synapse_link16_bridge import contract, jsonstrict, native, perf
from synapse_link16_bridge._version import __version__
from synapse_link16_bridge.bridge import BLOCKED, Bridge, JsonlSink, MemorySink, OperatorRefusal
from synapse_link16_bridge.config import BridgeConfig, ConfigError
from synapse_link16_bridge.gateway.client import (GatewayClient, GatewayError,
                                                  GatewayProtocolError, TransportError)
from synapse_link16_bridge.gateway.provider import SyntheticProvider
from synapse_link16_bridge.gateway.server import GatewayServer
from synapse_link16_bridge.store import SQL_JOB_GET, Store

OK, USAGE, BLOCKED_EXIT, REFUSED = 0, 2, 3, 4
DEFAULT_CREDENTIAL_ENV = "SYNAPSE_LINK16_GATEWAY_CREDENTIAL"


def _print(document) -> None:
    print(json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False))


def _config(path: str) -> BridgeConfig:
    return BridgeConfig.load(path)


def _credential(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise OperatorRefusal(f"the environment variable {name} is not set")
    return value


def _client(config: BridgeConfig) -> GatewayClient:
    return GatewayClient(config.gateway_base_url, _credential(config.credential_env),
                         connect_timeout=config.connect_timeout_seconds,
                         request_deadline=config.request_deadline_seconds,
                         max_body_bytes=config.limits["max_body_bytes"])


def _bridge(config: BridgeConfig, sink_dir: str | None = None, client=None) -> Bridge:
    sink = JsonlSink(sink_dir, config.cdm_schema_version) if sink_dir else \
        MemorySink(config.cdm_schema_version)
    return Bridge(config, sink=sink, client=client)


def _started(config: BridgeConfig, sink_dir: str | None = None) -> Bridge:
    bridge = _bridge(config, sink_dir, _client(config))
    if bridge.start() == BLOCKED:
        _print({"status": BLOCKED, "blocked_reasons": bridge.blocked_reasons})
        bridge.close()
        raise _Blocked()
    return bridge


class _Blocked(Exception):
    pass


def _operator(config: BridgeConfig) -> Bridge:
    bridge = _bridge(config)
    bridge.open_for_operator()
    return bridge


def cmd_check_config(args) -> int:
    config = _config(args.config)
    _print({"config": "VALID", "config_revision": config.config_revision, "mode": config.mode})
    return OK


def cmd_serve_gateway(args) -> int:
    credential = _credential(args.credential_env)
    provider = SyntheticProvider(times.utc_now, gateway_id=args.gateway_id)
    provider.add_channel(args.channel)
    for path in sorted(pathlib.Path(args.reports).glob("*.json")):
        provider.publish(args.channel, "report", jsonstrict.loads(path.read_bytes()))
    server = GatewayServer(provider, {credential: (args.consumer, args.channel)}, port=args.port,
                           long_poll_seconds=args.long_poll)
    print(f"serving on {server.base_url}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return OK


def cmd_run(args) -> int:
    config = _config(args.config)
    bridge = _started(config, args.sink_dir)
    try:
        bridge.run(once=args.once)
        _print(bridge.status_report())
        blocked = bridge.status == BLOCKED      # e.g. the lease lost mid-run: exit 3
    finally:
        bridge.close()
    return BLOCKED_EXIT if blocked else OK


def _existing_store(config: BridgeConfig) -> Store:
    if not pathlib.Path(config.store_path).is_file():
        raise OperatorRefusal("the store does not exist yet; run the bridge first")
    return Store(config.store_path, times.utc_now)


def cmd_health(args) -> int:
    config = _config(args.config)
    store = _existing_store(config)
    try:
        channel = store.channel()
    finally:
        store.close()
    provider_ready = True
    try:
        _client(config).capabilities()
    except (GatewayError, TransportError, GatewayProtocolError):
        provider_ready = False
    reasons = [] if provider_ready else ["PROVIDER_UNAVAILABLE"]
    if channel["state"] == "INCOMPLETE" or channel["incomplete"] is not None:
        reasons.append("CHANNEL_INCOMPLETE")        # a gap not yet recovered, in any state
    reasons += {"RESYNC_REQUIRED": ["RESYNC_REQUIRED"],
                "STOPPED": ["CHANNEL_STOPPED"]}.get(channel["state"], [])
    _print({"ready": not reasons, "provider_ready": provider_ready, "blocked_reasons": reasons,
            "channel_state": channel["state"]})
    return OK if not reasons else BLOCKED_EXIT


def cmd_status(args) -> int:
    config = _config(args.config)
    store = _existing_store(config)
    try:
        row = store.db.execute(SQL_JOB_GET, (args.request_id,)).fetchone()
    finally:
        store.close()
    if row is None:
        _print({"request_id": args.request_id, "state": None})
        return REFUSED
    _print({"request_id": row[0], "state": row[7], "reason": row[8]})
    return OK


def cmd_export(args) -> int:
    config = _config(args.config)
    entity = Entity.model_validate_json(pathlib.Path(args.entity).read_bytes())
    track = None if args.track is None else \
        Track.model_validate_json(pathlib.Path(args.track).read_bytes())
    bridge = _started(config)
    try:
        result = bridge.export(entity, track, peer_id=args.peer)
    finally:
        bridge.close()
    _print(dict(result))
    return OK if result["state"] in ("ACCEPTED", "ENCODED", "SENT") else REFUSED


def cmd_reconcile(args) -> int:
    bridge = _started(_config(args.config))
    try:
        changes = bridge.reconcile()
    finally:
        bridge.close()
    _print({"reconciled": [{"request_id": r, "state": s} for r, s in changes]})
    return OK


def _with_operator(args, action) -> int:
    bridge = _operator(_config(args.config))
    try:
        result = action(bridge)
    finally:
        bridge.close()
    _print({"done": args.command, "result": result})
    return OK


def cmd_recover(args) -> int:
    return _with_operator(args, lambda b: b.recover(args.evidence))


def cmd_resync(args) -> int:
    if not args.accept_earliest:
        raise OperatorRefusal("resync requires --accept-earliest")
    return _with_operator(args, lambda b: b.resync(args.evidence, args.lost_count))


def cmd_resync_identities(args) -> int:
    return _with_operator(args, lambda b: b.resync_identities(args.decision, args.evidence))


def cmd_resolve_reuse(args) -> int:
    return _with_operator(args, lambda b: b.resolve_reuse(args.identity, args.decision,
                                                          args.evidence))


def cmd_resolve_send(args) -> int:
    return _with_operator(args, lambda b: b.resolve_send(args.request_id, args.decision,
                                                         args.evidence))


def cmd_allocate(args) -> int:
    dest = jsonstrict.loads(args.dest_tuple.encode("utf-8"))
    return _with_operator(args, lambda b: b.allocate(args.peer, args.realm, args.identity, dest,
                                                     args.evidence))


def cmd_evidence(args) -> int:
    bridge = _operator(_config(args.config))
    try:
        octets = bridge.read_evidence(args.raw_ref, args.evidence)
    finally:
        bridge.close()
    if octets is None:
        _print({"raw_ref": args.raw_ref, "kept": False})
        return REFUSED
    pathlib.Path(args.out).write_bytes(bytes(octets))
    _print({"raw_ref": args.raw_ref, "kept": True, "bytes": len(octets)})
    return OK


def cmd_native_status(args) -> int:
    config = _config(args.config)
    status, what = native.native_status(None, config.native_profile)
    _print({"native_profile": config.native_profile, "status": status, "detail": what,
            "release_stages": native.release_stages(False)})
    return OK if status == "ACTIVE" else BLOCKED_EXIT


def cmd_schema(args) -> int:
    _print(contract.API_SCHEMA if args.which == "api" else contract.NOTICE_SCHEMA)
    return OK


def cmd_perf(args) -> int:
    result = perf.run(rate=args.rate, duration=args.duration, burst=args.burst,
                      identities=args.identities, store_dir=args.store)
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        pathlib.Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return OK


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        prog="synapse-link16-bridge",
        description="The runtime bridge between an SC Link16 Gateway 1.0.0 API and the CDM. "
                    "Synthetic provider included; no native JREAP C or Link 16 codec.")
    top.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = top.add_subparsers(dest="command", required=True)

    def command(name, handler, help_text, *, config=True):
        p = sub.add_parser(name, help=help_text)
        if config:
            p.add_argument("config", help="the deployment configuration file (JSON)")
        p.set_defaults(handler=handler)
        return p

    command("check-config", cmd_check_config, "parse and validate a configuration")
    p = command("serve-gateway", cmd_serve_gateway,
                "serve the synthetic provider on 127.0.0.1 with the reports of a directory",
                config=False)
    p.add_argument("--reports", required=True, help="a directory of report files (*.json)")
    p.add_argument("--port", type=int, default=0, help="the port (0 picks a free one)")
    p.add_argument("--gateway-id", default="synthetic-gateway-1")
    p.add_argument("--channel", default="default")
    p.add_argument("--consumer", default="consumer-1")
    p.add_argument("--credential-env", default=DEFAULT_CREDENTIAL_ENV,
                   help="the environment variable holding the accepted bearer credential")
    p.add_argument("--long-poll", type=float, default=0.0)
    p = command("run", cmd_run, "ingest from the gateway into the sink")
    p.add_argument("--once", action="store_true", help="one pass, then exit")
    p.add_argument("--sink-dir", required=True, help="the directory sink's directory")
    command("health", cmd_health, "readiness, from the store and the gateway")
    p = command("status", cmd_status, "an export job's state")
    p.add_argument("request_id")
    p = command("export", cmd_export, "export one CDM Entity (and its Track) to a peer")
    p.add_argument("--entity", required=True)
    p.add_argument("--track")
    p.add_argument("--peer", required=True)
    command("reconcile", cmd_reconcile, "adopt the gateway's state of open export jobs")
    p = command("recover", cmd_recover, "record recovery of an INCOMPLETE channel")
    p.add_argument("--evidence", required=True)
    p = command("resync", cmd_resync, "accept the earliest cursor after CURSOR_EXPIRED")
    p.add_argument("--accept-earliest", action="store_true")
    p.add_argument("--lost-count", type=int, default=None,
                   help="the gateway's loss accounting for the expired range, when known")
    p.add_argument("--evidence", required=True)
    p = command("resync-identities", cmd_resync_identities,
                "record the identity decision after RESET_SCOPE")
    p.add_argument("--decision", required=True, choices=("keep", "advance"))
    p.add_argument("--evidence", required=True)
    p = command("resolve-reuse", cmd_resolve_reuse, "release or reject a quarantined reuse")
    p.add_argument("--identity", required=True)
    p.add_argument("--decision", required=True, choices=("continue", "reject"))
    p.add_argument("--evidence", required=True)
    p = command("resolve-send", cmd_resolve_send, "close an UNKNOWN export job")
    p.add_argument("request_id")
    p.add_argument("--decision", required=True, choices=("abandon",))
    p.add_argument("--evidence", required=True)
    p = command("allocate", cmd_allocate, "record a provider's destination number allocation")
    p.add_argument("--peer", required=True)
    p.add_argument("--realm", required=True)
    p.add_argument("--identity", required=True)
    p.add_argument("--dest-tuple", required=True, help="the destination identity tuple (JSON)")
    p.add_argument("--evidence", required=True)
    p = command("evidence", cmd_evidence, "read one raw batch kept as evidence (audited)")
    p.add_argument("--raw-ref", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--evidence", required=True, help="why the raw evidence is read")
    command("native-status", cmd_native_status, "the native provider boundary's state")
    p = command("schema", cmd_schema, "print the API or the notice schema", config=False)
    p.add_argument("which", choices=("api", "notice"))
    p = command("perf", cmd_perf, "the measurement harness (evidence only on the named rig)",
                config=False)
    p.add_argument("--rate", type=int, default=1000)
    p.add_argument("--duration", type=int, default=1800)
    p.add_argument("--burst", default="5000:10")
    p.add_argument("--identities", type=int, default=100_000)
    p.add_argument("--store", required=True)
    p.add_argument("--out")
    return top


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return args.handler(args)
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        return USAGE
    except _Blocked:
        return BLOCKED_EXIT
    except OperatorRefusal as refusal:
        print(f"REFUSED: {refusal}", file=sys.stderr)
        return REFUSED
