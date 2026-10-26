# synapse-hla

Profile `SC-HLA-RPR2-OBS-1`, synapse-hla 1.0.0: a receive-only HLA Evolved observer for a
bounded subset of the RPR FOM 2.0 physical-entity attributes. A native worker copies RTI
callbacks into a durable, hash-chained capture; this Python package reduces the capture to
per-object state, projects eligible state to the CDM `Entity` of `synapse-cdm`, and replays a
capture offline. It implements the handoff document SC HLA SPEC 001 v1.0, which is not in this
repository; requirement ids (R01 to R50), acceptance case ids and the ids of the rulings taken on
its open points (for example OPS-02, NAT-01, CR-L04) are cited from it and from the run that
built this package.

**Evidence status.** This release was built and tested on a macOS arm64 development machine
(evidence class `DEV-macOS-arm64`). Its predecessor tree, with the three portability fixes this
release carries applied as patches, was also built and tested on Linux aarch64 with Ubuntu
24.04, GCC 13 and CMake 3.28 (`DEV-linux-aarch64`). Neither is the reference platform the
specification names (Linux x86_64, Ubuntu 24.04, GCC 13, CMake 3.28 to 3.31): every release gate
that needs it, the performance run of R42 among them, reads BLOCKED in the evidence report
(`docs/evidence/`), never PASS. `external_customer_interoperability` is `NOT_TESTED`.

## What it is

`synapse-hla` is a separate distribution beside `synapse-cdm` (R03). It is not a registered CDM
adapter: it has no manifest and no adapter entry point, because a stateful observer with sockets,
files and session state does not belong inside the pure CDM package.

- `sc-hla-federate` (C++14, `src/native/worker/`) is the native worker: the one process that
  talks to the RTI. It joins an existing federation through OpenRTI's rti1516e API, subscribes to
  four attributes and writes every callback, bytes unchanged, as a JSON frame on stdout, with its
  status records on file descriptor 3.
- The host (`synapse_hla.host`, run by `synapse-hla observe`) starts the worker, writes the
  capture with its SHA-256 chain, reduces each frame as it is written, writes the observation and
  diagnostic records, and stops the worker in order.
- The reducer, projector and replay (`reduce_frame`, `project_state`, `replay`) are pure Python:
  the same capture gives the same records, live or offline, on the platform that reduces it.
  Identity across interpreters is shown on macOS arm64 from Python 3.11, 3.12 and 3.14, where
  all three were run; Linux aarch64 ran one interpreter (Python 3.12.3), so it was not observable
  there ("Exact output across platforms", below).
- `sc-hla-publisher` (`tools/publisher/`) is the synthetic publisher of the `demo` command. It is
  not part of the receive-only runtime.

## Profile declaration

Profile `SC-HLA-RPR2-OBS-1`:

- **API and FOM.** HLA Evolved (IEEE 1516-2010) through the C++ rti1516e API of OpenRTI commit
  `814a210978b7faafd65affbe70a2e25679921b23`, with RPR FOM 2.0: the five modules
  `RPR-Foundation_v2.0.xml`, `RPR-Enumerations_v2.0.xml`, `RPR-Base_v2.0.xml`,
  `RPR-Physical_v2.0.xml` and `RPR-Switches_v2.0.xml`, in that order, each checked against its
  SHA-256 in `src/synapse_hla/pins.json`.
- **Subscribed attributes.** Exactly four, of `HLAobjectRoot.BaseEntity.PhysicalEntity`:
  `EntityIdentifier`, `EntityType`, `Spatial` and `ForceIdentifier`. Nothing else is subscribed,
  and an attribute the observer did not subscribe to is captured and diagnosed, never decoded.
- **Services used.** Connect, join an existing federation (without FOM modules of its own),
  resolve the class and attribute handles, subscribe actively without regions, receive
  discoveries, reflections and removals in receive order, ask for the current values of newly
  discovered objects, resign and disconnect.
- **Unsupported services.** Interactions (sending or receiving), publication, registration,
  updates and deletion of objects, creating or destroying a federation, ownership transfer, DDM
  regions, save and restore, time regulation, time-constrained advancement, dead-reckoning
  execution, entity control, commands, firing and detonation, and undoing a retractable update
  (a retractable update or removal is captured and quarantines its object). HLA 1.3, IEEE
  1516-2000, HLA 4, RPR FOM draft 17 and RPR FOM 3.0 are not supported, and an unknown extension
  is never decoded as a standard field.

## Claims

### What this release claims

It receives and replays the tested RPR FOM 2.0 physical-entity attribute subset through the
pinned OpenRTI baseline and projects externally timed state into CDM. OpenRTI is the tested
reference; neither a customer simulator nor a second RTI implementation was tested. The
release evidence report (`docs/evidence/`) states, case by case, what was tested where.

This release is not a certification. It establishes the named profile and the tested OpenRTI
baseline only, and not compatibility with any specific simulator or installation. The
specification's acceptance targets (the performance target among them) are requirements this
release is measured against, not results; its measurements are those of the evidence report.
Compatibility with a customer's system is a later evidence task.

### What it does not claim

- support for HLA in general, or for the RPR FOM beyond the four attributes above;
- verified integration with any site or installation (the one that motivated the specification
  included), or with SWORD, WASP or Nebula;
- control of a simulator or simulation;
- source-authoritative UTC timing: times are the configured epoch plus the observer's own
  elapsed time, or no time at all (`external_elapsed` or `none`);
- fusion of HLA identities with DIS identities;
- authenticated or encrypted RTI transport: RTI traffic is neither authenticated nor encrypted
  by this adapter, and a remote deployment relies on an externally secured network;
- that OpenRTI's participation is standards certification or a second independent RTI federation
  test: it demonstrates a public reference;
- any external customer interoperability (`external_customer_interoperability` is
  `NOT_TESTED` in every report).

Future extensions need a new profile version, new schemas and new tests; version 1.0 of this
profile is not widened silently.

### Limitations of this baseline

These are facts of the pinned baseline, not defects to work around:

- **Co-publication (NAT-01).** Through the pinned OpenRTI, an object registered by another
  process is discovered only when that process also publishes the four attributes at
  `PhysicalEntity` itself: the RTI forwards a subscription only to federates that publish the
  same class. Objects from other processes whose federate publishes only a subclass of
  `PhysicalEntity` (for example `GroundVehicle`) are not discovered. The synthetic publisher
  therefore publishes at both classes and registers its object at `GroundVehicle`.
- **Orderly RTI exit (NAT-03, NAV-02).** When `rtinode` exits, or the connection ends with an
  orderly close (FIN), OpenRTI reports no connection loss to the observer: it removes every object
  the observer knows, and the session stays open with no objects until it is stopped.
  Last-received values are never kept in that case. A connection reset is reported as
  `E_RTI_CONNECT`, and the host reconnects after 1, 2 and 4 seconds.
- **FOM modules outside the repository (OPV-03).** The five RPR FOM modules and the OpenRTI
  source archive are not in this repository and not in the wheel. They come with the release
  evidence kit; the package finds the modules through `SYNAPSE_HLA_FOM_DIR` and checks each
  against its pin before use.
- **Idle pause (NAT-05).** The worker calls `evokeMultipleCallbacks(0.0, 0.05)` as R12 says;
  those parameters return at once when nothing is pending, so after a call that delivered no
  callback the worker pauses for 5 ms instead of keeping a processor busy.
- **macOS is a development build (NAT-02).** On macOS a C++14 OpenRTI client cannot connect (two
  clocks with different origins inside OpenRTI), so `tools/build_openrti.sh` builds OpenRTI
  alone as C++98 there; the worker and the publisher stay C++14. A macOS build is development
  evidence only.
- **Two evidence levels for the FOM (R11).** `bundled-fom-created` (the demo created the
  federation from the five hashed modules itself) and `external-fom-unverified` (observe joined a
  federation someone else created; the modules it was created from are not known), kept apart in
  every report.
- **The demo's clock.** The demo's main run uses time policy `external_elapsed` under a
  documented synthetic assumption: the scenario clock runs at 1x from the configured epoch, so an
  effective time is the epoch plus the observer's elapsed time. Its second run uses time policy
  `none` and produces snapshots and no Entity.
- **Retractable updates.** A retractable update or removal is captured and quarantines its
  object; nothing in this release can undo one, live or in replay.
- **Exact output across platforms.** Replays are byte-identical across Python 3.11, 3.12 and
  3.14 on macOS arm64, where all three were run against its pin; Linux aarch64's pin was
  recorded from one interpreter (Python 3.12.3), so identity across interpreters was not
  observable there. The packaged capture replays to the same bytes on macOS arm64 and Linux
  aarch64; at extreme heights (tens of thousands of kilometres) the last printed digit of an
  altitude can differ between C libraries (CR-L20).
- **Performance.** R42's run (1000 reflections per second over 1000 objects for 60 seconds on a
  4-vCPU x86_64 machine) has not been made on that machine. On a 4-vCPU aarch64 machine with
  `external_elapsed`, where every reflection is validated as a CDM Entity, the worker's queue
  overflowed in two of three such runs; the gate is at risk (`docs/evidence/`). After an
  overflow, as after any failure the worker reports, the host reads the worker's complete frames
  for at most one second and then stops it: frames the worker had already accepted but the host
  had not read by then are lost, and only the footer's `E_QUEUE_OVERFLOW` marks them (R41).

## The CDM

The handoff fixed the CDM baseline as synapse-cdm 3.1.1 at commit
`c4bba1b6ebfdfe956f6efc2b3a81a04db2b4bb5b` (CDM schema 3.0.0), and the Entity contract this
package validates against is that schema: `src/synapse_hla/schemas/cdm-entity.schema.json`, the
handoff's bytes, unchanged. Every Entity the package emits declares `schema_version` `3.0.0`,
is validated against that file with format checking and the profile assertions, and is
constructed as `synapse_cdm.models.Entity` (R44).

The package was developed and tested against 3.1.1 at that commit, then moved to the
repository's main line at synapse-cdm 3.8.0 (CDM schema 3.2.0), which is the floor it declares
(`synapse-cdm>=3.8.0,<4`), and landed at synapse-cdm 3.9.0 (the same CDM schema), the release
`locks/` pins and the evidence report was tested with. That move was recorded as a migration:

- The installed SDK's generated Entity schema differs from the vendored 3.0.0 one, apart from
  prose, in exactly two places: the `default` of `schema_version` (3.0.0 to 3.2.0, a default and
  not a constraint) and the `PositionSource` enum, which gained `SENSOR` and `UNKNOWN`. Both are
  additive: the same nineteen properties, the same required members, `additionalProperties`
  false in both.
- Re-verification:
  `tests/test_hla_projector.py::test_the_cdm_baseline_and_its_complete_entity_schema` holds the
  declared floor, the installed version, the vendored schema's pinned bytes, the additivity of
  the installed SDK's schema, and that the package's own Entity and the replayed entities
  validate against both schemas; the packaged capture still replays to the packaged expected
  observations byte for byte (SHA-256
  `d55fd510bf633395192f4ead01cab1753216d870a9219d023a8525138ef05125`).

**The upgrade rule (R44).** A later synapse-cdm keeps this package working only if its Entity
schema stays additive over the vendored 3.0.0 contract. An upgrade must keep the packaged
fixtures unchanged, pass that test and the byte-identical replay, and record its migration here:
the differences found and how they were re-verified. Moving the locked set to another
synapse-cdm than the locked 3.9.0 also needs `locks/` regenerated for the set in use
(`locks/tested-set.in`, the three lock files with the command each names in its first lines, and
the SBOM with `python tests/release_sbom.py`) and the evidence report with it. The offline group
and the SBOM tool hold every other installed locked distribution to its locked version, and
synapse-cdm, this repository's sibling distribution, to the declared range at or above its
locked version, since at a release commit a checkout's own `packages/cdm` names a release the
index does not hold yet. So with a later synapse-cdm inside the range installed no test fails by
design, and with an earlier one three do until then: the two that hold the installed set to the
locks and the SBOM, and the one that holds the version the evidence report was tested with to at
most the installed one. The installation guide (`docs/installation.md`) says the same for an
installed system.

## From a clean checkout

What a fresh engineer runs, on Ubuntu 24.04 or macOS, without access to any private network;
for this release the commands were run as written on the development Mac (the evidence report
says what each printed). They start in `packages/hla` of a checkout. `WORK` names a new
directory outside the checkout and `SYNAPSE_HLA_FOM_DIR` the directory of the release evidence
kit that holds the five RPR FOM modules and `openrti-814a210.tar.gz`; both are absolute paths you
choose. Installing the toolchain and the Python packages are the only steps that use the network
(the distribution's package archive and the public Python package index).

### 1. Toolchain

- Ubuntu 24.04: `build-essential`, `g++-13`, `cmake`, `libexpat1-dev`, `zlib1g-dev`,
  `python3.12`, `python3-venv`; for the tests also `lsof` and `proj-bin` (`cs2cs`, the reference
  group). The runtime packages the native part needs are `libexpat1`, `zlib1g` and `libstdc++6`.
- macOS: the Xcode command line tools, CMake and Python 3.12 (Homebrew); for the reference group
  `proj` (Homebrew).
- For the `rti` group on either system: `uv`, in `~/.local/bin` (where Astral's installer puts
  it), in `/usr/local/bin` or in Homebrew's `bin` on macOS, the places the tests look; its cache
  must hold the build backend `locks/build.lock` pins (see "Running the tests").
- Python 3.11 or 3.12 (3.14 was also exercised and passes).

```
sudo apt-get install build-essential g++-13 cmake libexpat1-dev zlib1g-dev python3.12 python3-venv lsof proj-bin
```

### 2. Commands, expected exit codes and the files they create

```
export WORK=/absolute/new/directory SYNAPSE_HLA_FOM_DIR=/absolute/directory/of/the/kit
python3.12 -m venv "$WORK/venv"                                                 # exit 0
"$WORK/venv/bin/python" -m pip install --require-hashes -r locks/test.lock      # exit 0
"$WORK/venv/bin/python" -m pip install --require-hashes -r locks/build.lock     # exit 0
"$WORK/venv/bin/python" -m pip install --no-deps --no-build-isolation .         # exit 0
bash tools/build_openrti.sh "$SYNAPSE_HLA_FOM_DIR/openrti-814a210.tar.gz" "$WORK/openrti"  # exit 0
cmake -S src/native -B "$WORK/native" -DOPENRTI_PREFIX="$WORK/openrti/install"  # exit 0
cmake --build "$WORK/native"                                                    # exit 0
ctest --test-dir "$WORK/native"                                                 # exit 0
PKG=$("$WORK/venv/bin/python" -c 'import os, synapse_hla; print(os.path.dirname(synapse_hla.__file__))')
cmake --install "$WORK/native" --prefix "$PKG"                                  # exit 0
cd "$WORK"
venv/bin/synapse-hla --version                                                  # exit 0
venv/bin/synapse-hla self-test --out selftest                                   # exit 0
venv/bin/synapse-hla demo --out demo                                            # exit 0
venv/bin/synapse-hla inspect --capture demo/main/capture.jsonl                  # exit 0
venv/bin/synapse-hla verify --capture demo/main/capture.jsonl                   # exit 0
venv/bin/synapse-hla replay --capture demo/main/capture.jsonl --out replay      # exit 0
cmp demo/main-replay/observations.jsonl replay/observations.jsonl               # exit 0
```

What each step leaves behind:

| Step | Files and directories it creates |
|---|---|
| `venv`, the three `pip install` | `$WORK/venv/`; the in-tree build of the last one writes `build/` and `src/synapse_hla.egg-info/` into the checkout (both ignored by git) |
| `tools/build_openrti.sh` | `$WORK/openrti/source/` (the unpacked archive), `build/`, `install/` (`bin/rtinode`, the `libOpenRTI`, `librti1516e` and `libfedtime1516e` shared libraries, `include/rti1516e/`, `share/OpenRTI/`) and `build-record.txt` (the exact commands, the CMake and compiler versions, the archive's SHA-256, the variant and the evidence class of the build) |
| `cmake -S`, `cmake --build` | `$WORK/native/`: `bin/` with `sc-hla-federate`, `sc-hla-publisher`, and the test-only `sc-hla-harness`, `sc-hla-test-federate`, `sc-hla-reference-encode` and `sc-hla-reference-fom-check`; `lib/` with copies of the OpenRTI libraries |
| `ctest` | `$WORK/native/smoke/` (one directory per smoke run, and `installed/`, a trial install) |
| `cmake --install` | in the installed package directory: `bin/sc-hla-federate`, `bin/sc-hla-publisher`, `bin/rtinode`, `lib/` (the OpenRTI libraries) and `licences/` (this directory's `licences/`) |
| `--version` | nothing; prints `{"name":"synapse-hla","version":"1.0.0","profile":"SC-HLA-RPR2-OBS-1"}` |
| `self-test` | `selftest/self-test.json` and `selftest/fixture-replay/` with `capture.jsonl`, `observations.jsonl`, `diagnostics.jsonl` and `run.json` |
| `demo` | `demo/demo.json`, and `main/`, `main-replay/`, `no-time/`, `no-time-replay/`, each with `capture.jsonl`, `observations.jsonl`, `diagnostics.jsonl` and `run.json` |
| `inspect`, `verify` | nothing; one JSON summary on stdout |
| `replay` | `replay/` with `capture.jsonl` (a byte copy), `observations.jsonl`, `diagnostics.jsonl` and `run.json` |
| `observe` (below) | its `--out` directory with `capture.jsonl`, `observations.jsonl`, `diagnostics.jsonl` and `run.json` |
| `export-capture` | the file named by `--out` |

`self-test` exits 4 when `SYNAPSE_HLA_FOM_DIR` is not set (its FOM pin check is then BLOCKED).
It runs, offline and without pytest, the packaged attribute vectors, the geodesy points, the
identity example and both example configurations, checks that every packaged schema is a valid
schema and every fixture has its recorded digest, checks the FOM pins, and replays the packaged
capture against its expected observations; it does not run the demo's checkpoints and does not
test how strict the schemas are.
`demo` exits 4 with a BLOCKED `demo.json` when the worker, the publisher or `rtinode` is
missing. Instead of `cmake --install`, the three executables can be named by
`SYNAPSE_HLA_WORKER`, `SYNAPSE_HLA_PUBLISHER` and `SYNAPSE_HLA_RTINODE` (absolute paths, for
example into `$WORK/native/bin` and `$WORK/openrti/install/bin`). `docs/installation.md` gives
the same steps with their reasons, the upgrade rule and how to remove an installation.

To observe a federation someone else runs, copy `examples/config-existing.json`, set its
`endpoint` (`rti://<IPv4 address>:<port>`), `federation_name` and the other members as
`src/synapse_hla/schemas/config.schema.json` describes, then:

```
venv/bin/synapse-hla validate-config --config my-config.json                    # exit 0
venv/bin/synapse-hla observe --config my-config.json --out session --duration-seconds 60
```

## The command line

`synapse-hla` has eight commands: `validate-config`, `observe`, `replay`, `verify`, `inspect`,
`export-capture`, `demo` and `self-test`, each with `--help` and `--version`. Every command
prints one JSON summary on stdout (`export-capture` prints nothing) and JSON diagnostics on
stderr, one per line; rendered text escapes control characters. `export-capture` copies only a
verified original capture, byte for byte: it does not edit, re-encode or re-export HLA data, it
constructs no HLA packets and replays no traffic into an RTI.

| Exit | Meaning (OPS-02) |
|---|---|
| 0 | the command's operation completed with no `E_` diagnostic (`W_` diagnostics allowed) |
| 2 | invocation or configuration error: `E_CONFIG`, `E_OUTPUT_EXISTS`, a usage error |
| 3 | invalid data, or a completed capture or replay with `E_` diagnostics: every decoder, reducer and projection code and every `E_CAPTURE_*` code |
| 4 | missing dependency or unavailable reference evidence: `E_DEPENDENCY_PIN` |
| 5 | RTI connection, profile or runtime error: `E_FOM_PROFILE`, `E_FEDERATE_NAME`, `E_RTI_CONNECT`, `E_RTI_TIMEOUT` |
| 6 | resource or I/O failure: `E_LIMIT`, `E_QUEUE_OVERFLOW`, `E_IO` |
| 130, 143 | stopped by SIGINT or SIGTERM before the command had its result; `observe` stops its session in order once one exists, and a stop before that (during its own configuration and FOM pre-flight) exits 130 or 143 like the other commands |
| 1 | a defect of this program (a traceback on stderr) |

Among competing terminal failures the highest class wins (6, 5, 4, 3, 2). A live run directory
without `run.json` marks a session whose command did not see its end: a command killed from
outside, a host that ended without a result or was stopped for its memory, or a `run.json` that
could not be written.

The native worker `sc-hla-federate` has exit statuses of its own (CR-R7-01). The host reads only
0 and not 0 (0 after its orderly stop); the distinct values are for a person reading a log:

| Worker exit | Meaning |
|---|---|
| 0 | the orderly stop completed, or `--version` |
| 1 | a terminal condition was reported on file descriptor 3 |
| 64 | the argument vector is neither `--version` nor the three tokens of OPS-08 |
| 70 | file descriptor 3 is not open, or not a pipe (NAT-09) |
| 71 | stdout or file descriptor 3 broke (EPIPE): nobody is left to report to |
| 72 | the host that started the worker has gone |

A capture's hash chain detects accidental modification of the recorded evidence. It is not
authentication and not a digital signature: anyone who can write the file can recompute every
digest. An Entity's `entity_id` and `source.source_hash` correlate it with the capture it came
from; they are not authenticated identities, and the Entity's `integrity` is never set.

## Running the tests

From `packages/hla`, with the venv of the steps above (or any interpreter holding
`locks/test.lock`):

```
SYNAPSE_HLA_FOM_DIR=... "$WORK/venv/bin/python" -m pytest -m "not rti and not perf and not reference"
```

That is the offline group: it opens no socket and starts no RTI (an autouse guard refuses
sockets in it, and child interpreters get the same guard), and needs only the FOM directory.
The `rti` group needs the native build and runs the worker, the publisher, `rtinode` and the
demo on 127.0.0.1:

```
SYNAPSE_HLA_FOM_DIR=... SYNAPSE_HLA_WORKER="$WORK/native/bin/sc-hla-federate" \
  SYNAPSE_HLA_HARNESS="$WORK/native/bin/sc-hla-harness" \
  SYNAPSE_HLA_PUBLISHER="$WORK/native/bin/sc-hla-publisher" \
  SYNAPSE_HLA_RTINODE="$WORK/openrti/install/bin/rtinode" "$WORK/venv/bin/python" -m pytest -m rti
```

`SYNAPSE_HLA_HARNESS` is a test-only variable: the harness drives the worker's own callback code
inside an OpenRTI federation of its own process, to produce the callbacks a running RTI does not
deliver. The `rti` group also builds a wheel with `uv` and installs it with the native part. That
build runs offline, with its build backend held to `locks/build.lock` by hash, so uv's cache must
already hold that backend (setuptools 84.2.1); once per machine, with network access to the
public Python package index, run from `packages/hla`:

```
uv build --wheel --out-dir "$WORK/dist" --build-constraints locks/build.lock --require-hashes
```

Without it the installed-form test reports `BLOCKED` and names the missing backend. The
`perf` group (`-m perf`, the load runs of R42) and the `reference` group (`-m reference`, PROJ's
`cs2cs`) run only when asked for. A test whose external resource is absent reports itself
`BLOCKED: <resource>` (a skip with that reason, the only skip there is); the performance test
reports BLOCKED on any machine but the reference platform, after recording its measurement.

## Layout of this directory

- `src/synapse_hla/` the Python package: the public API of R06 (`validate_config`,
  `decode_attribute`, `reduce_frame`, `project_state`, `replay`, `verify_capture`, `HlaError`,
  `__version__`, `PROFILE`), the host, the command line, the 13 contract schemas and the 8
  fixtures of the handoff byte for byte with `pins.json`, and the product's own schemas
  (`local_schemas/`).
- `src/native/` the worker and its test programs (one CMake project); `tools/` the OpenRTI build
  wrapper, the synthetic publisher and the handoff's two reference tools.
- `examples/` the two example configurations of the handoff, byte for byte.
- `tests/` the test suite; `tests/contract/` the acceptance-case index, the trace ratchet and the
  vendored-file pins; `tests/release_sbom.py` and `tests/release_evidence.py` write the SBOM and
  the evidence report.
- `locks/` the hashed lock files (`runtime.lock`, `test.lock`, `build.lock`), the native
  toolchain record and the CycloneDX SBOM (`sbom.cdx.json`).
- `docs/` the installation guide and the release evidence report.
- `licences/` the OpenRTI licence texts and the licence this release elects.

## Licences

synapse-hla is licensed under Apache-2.0 (`LICENSE`, `NOTICE`). The native part links OpenRTI,
which this release uses under LGPL-2.1-or-later, dynamically and unmodified;
`licences/README.md` states the election and the attributions the IEEE API headers and the SISO
FOM modules require, and `licences/openrti/` holds OpenRTI's licence texts, verbatim from the
pinned archive (without the `.txt` suffix the repository's ignore rules exclude).
