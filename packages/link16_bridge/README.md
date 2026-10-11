# synapse-link16-bridge

The runtime bridge between an **SC Link16 Gateway 1.0.0** API and the SynapseCommand Canonical
Data Model. Version 1.0.0, Apache-2.0, written 2026-10-11 as the runtime half of the
SynapseCommand JREAP C and Link 16 engineering handoff 1.0.0.

## What it is

- A client of the gateway API (`GET /v1/capabilities`, `GET /v1/reports`, `POST /v1/ack`,
  `POST /v1/transmissions`, `GET /v1/transmissions/{request_id}`, `GET /v1/health`) that reads
  report batches over `https://`, or over `http://` to a loopback host only, with a bearer
  credential it reads from the environment variable its configuration names.
- Durable ingest into one SQLite file per channel: every record checked against the configured
  channel before translation, translated by the `link16_gateway` adapter of `synapse-cdm`,
  deduplicated, given a durable disposition, kept in history with current state, freshness,
  lifecycle (drop, rekey, gap, scope reset), quarantine and an audit trail, and delivered to a
  sink at least once under stable event keys.
- Export of a CDM Entity, and its one-sample Track, to a gateway only when the deployment
  configuration permits it, after exact-match policy, freshness, allocation, family and profile
  checks, with idempotent requests and no blind re-send.
- A synthetic provider with a loopback HTTP server, so every path above can run without a
  native gateway, and a measurement harness for the performance gate.

## What it is not

It is not JREAP C and not Link 16. It parses no native frame, message or J-series word, opens no
native socket, and makes no claim of native interoperability, radio participation, encryption,
anti-jam behaviour, spectrum authorisation, national accreditation or certification of any kind.
The native provider is a boundary that refuses activation with `BLOCKED_EXTERNAL_EVIDENCE` until a
normative profile, independent byte vectors and a witnessed peer test exist, and it never falls
back to the synthetic provider. Its policy is configuration matching — exact channel, label-set
and export rules its deployment configuration names — and not a classification-policy engine or
a cross-domain guard. It makes no weapons, engagement or command decision. Release acceptance
has four stages, reported separately: the internal gateway translation (implemented), a native
codec (blocked on external evidence), interoperability with a named peer (not run) and
deployment in a named authorised environment (not claimed). No numerical quality score is given.

## Install

The bridge needs `synapse-cdm` 3.4.0 or later (and below 4), which carries the `link16_gateway`
adapter and the CDM 3.1.0 position methods. Install it from the package index first, then the
bridge from the repository's release tag:

```bash
pip install synapse-cdm
pip install "synapse-link16-bridge @ git+https://github.com/Decent-Cybersecurity/synapsecommand-public@v3.4.0#subdirectory=packages/link16_bridge"
```

The bridge's runtime dependencies are `synapse-cdm` and the Python standard library.

## The command line

```text
synapse-link16-bridge check-config CONFIG
synapse-link16-bridge serve-gateway --reports DIR --port N [--channel C] [--consumer ID]
synapse-link16-bridge run CONFIG --sink-dir DIR [--once]
synapse-link16-bridge health CONFIG
synapse-link16-bridge status CONFIG REQUEST_ID
synapse-link16-bridge export CONFIG --entity FILE [--track FILE] --peer ID
synapse-link16-bridge reconcile CONFIG
synapse-link16-bridge recover CONFIG --evidence TEXT
synapse-link16-bridge resync CONFIG --accept-earliest [--lost-count N] --evidence TEXT
synapse-link16-bridge resync-identities CONFIG --decision keep|advance --evidence TEXT
synapse-link16-bridge resolve-reuse CONFIG --identity KEY --decision continue|reject --evidence TEXT
synapse-link16-bridge resolve-send CONFIG REQUEST_ID --decision abandon --evidence TEXT
synapse-link16-bridge allocate CONFIG --peer ID --realm R --identity KEY --dest-tuple JSON --evidence TEXT
synapse-link16-bridge evidence CONFIG --raw-ref SHA256 --out FILE --evidence TEXT
synapse-link16-bridge native-status CONFIG
synapse-link16-bridge schema api|notice
synapse-link16-bridge perf --store DIR [--rate N --duration S --burst N:S --identities N --out FILE]
```

Exit codes: 0 done, 2 a usage error or a refused configuration, 3 blocked, 4 an operation
refused. `serve-gateway` reads its accepted credential from `SYNAPSE_LINK16_GATEWAY_CREDENTIAL`
(or the variable `--credential-env` names) and binds `127.0.0.1` only. The configuration keys,
the limits, the recovery procedures and the codes are in `docs/operations.md`; every requirement
and acceptance row of the handoff, with its disposition and its test, is in
`docs/requirements-matrix.md`.

## Tests

From a clone of the repository, with `synapse-cdm` installed from the same tree, the commands
the workflow `.github/workflows/gateway-bridge.yml` runs:

```bash
python -m pip install -e "packages/cdm[test,lint]"
python -m pip install --no-deps -e packages/link16_bridge
python -m pip install "setuptools>=77"
ruff check --config packages/link16_bridge/pyproject.toml packages/link16_bridge
cd packages/link16_bridge && python -m pytest
```

The `native` tests skip with `BLOCKED_EXTERNAL_EVIDENCE` and name the gate that unblocks each;
the `wheel` test builds and installs this distribution and skips where the interpreter has no
`pip` and `setuptools`; the `process` tests kill a bridge process at a crash point. No test
asserts a duration, and no timing taken anywhere but on the rig the performance requirement
names is evidence for it.
