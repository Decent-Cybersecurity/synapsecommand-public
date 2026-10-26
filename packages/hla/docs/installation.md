# Installing synapse-hla 1.0.0

The installation guide of profile `SC-HLA-RPR2-OBS-1` (R05, R49). The README of this directory
has the same commands in short, with the files each one creates; this guide adds why each step is
there, where the native part goes, how to check an installation, how to upgrade the CDM it
depends on, and how to remove it.

## What an installation consists of

1. The Python distribution `synapse-hla` (a pure wheel, `py3-none-any`) and its one runtime
   dependency, `synapse-cdm>=3.8.0,<4` (which brings jsonschema and pydantic). `locks/runtime.lock`
   holds the exact versions this release was tested with, each with the SHA-256 of every file the
   package index publishes for it; `locks/test.lock` adds pytest.
2. The native part, built from this directory against the pinned OpenRTI: the worker
   `sc-hla-federate`, the demo's synthetic publisher `sc-hla-publisher`, OpenRTI's `rtinode` and
   the three OpenRTI shared libraries. They are not in the wheel. `cmake --install` puts them
   into `bin/` and `lib/` of the installed package directory, where the command line looks for
   them (never on `PATH`), together with the licence texts of `licences/`.
3. The release evidence kit, which this repository does not contain: the five RPR FOM 2.0
   modules and the OpenRTI source archive `openrti-814a210.tar.gz`, each held to its SHA-256 in
   `src/synapse_hla/pins.json`. The variable `SYNAPSE_HLA_FOM_DIR` names the directory that holds
   them; `validate-config`, `observe`, `demo` and `self-test` check the five modules against
   their pins before anything else.

## Toolchain

Ubuntu 24.04 (the reference distribution; the reference platform is its x86_64 form with GCC 13
and CMake 3.28 to 3.31):

```
sudo apt-get install build-essential g++-13 cmake libexpat1-dev zlib1g-dev python3.12 python3-venv lsof proj-bin
```

At run time the native part needs `libexpat1`, `zlib1g` and `libstdc++6` (OpenRTI links the
system expat and zlib); `lsof` and `proj-bin` are needed by the tests only. On macOS: the Xcode
command line tools and, from Homebrew, `cmake` and `python@3.12` (and `proj` for the reference
tests). CMake 3.28 to 3.31 runs the handoff's OpenRTI build command byte for byte; CMake 4 or
later refuses OpenRTI's own minimum version, so the wrapper adds
`-DCMAKE_POLICY_VERSION_MINIMUM=3.5` there and the build record says so (NAT-12: 3.28 to 3.31
verified; 4.x only with that flag, for development use).

## Steps

`WORK` is a new directory outside the checkout; `SYNAPSE_HLA_FOM_DIR` the kit's directory. From
`packages/hla`:

```
export WORK=/absolute/new/directory SYNAPSE_HLA_FOM_DIR=/absolute/directory/of/the/kit
python3.12 -m venv "$WORK/venv"
"$WORK/venv/bin/python" -m pip install --require-hashes -r locks/test.lock
"$WORK/venv/bin/python" -m pip install --require-hashes -r locks/build.lock
"$WORK/venv/bin/python" -m pip install --no-deps --no-build-isolation .
```

The Python installation, from locked and hashed files only: the runtime and test dependencies,
then the build backend (setuptools, locked in `locks/build.lock`), then this distribution built
with that backend and no other download.

```
bash tools/build_openrti.sh "$SYNAPSE_HLA_FOM_DIR/openrti-814a210.tar.gz" "$WORK/openrti"
```

The pinned OpenRTI (R43): the archive is refused unless its SHA-256 is the pinned one; the
configure, build and install commands are the handoff's, with RTI13 and RTI1516 off, RTI1516E on,
Python bindings off, shared libraries, C++14 and Release, plus a relocatable install whose loader
path is relative (NAT-13) and, on macOS only, OpenRTI built as C++98 (NAT-02). Nothing is
installed outside `$WORK/openrti`, nothing is fetched, nothing needs `sudo`. The build record
`$WORK/openrti/build-record.txt` names the commands, the versions, the archive's digest and the
evidence class of the build: the reference configuration only on Linux x86_64 with Ubuntu 24.04,
GCC 13 and CMake 3.28 to 3.31, otherwise development evidence of the machine.

```
cmake -S src/native -B "$WORK/native" -DOPENRTI_PREFIX="$WORK/openrti/install"
cmake --build "$WORK/native"
ctest --test-dir "$WORK/native"
```

The native part, C++14 with every warning an error, against that OpenRTI install only (nothing
else is searched for). `ctest` runs 100 smoke runs, among them a trial install that checks the
installed layout.

```
PKG=$("$WORK/venv/bin/python" -c 'import os, synapse_hla; print(os.path.dirname(synapse_hla.__file__))')
cmake --install "$WORK/native" --prefix "$PKG"
```

The native part beside the installed package: `bin/sc-hla-federate`, `bin/sc-hla-publisher`,
`bin/rtinode`, `lib/` with the OpenRTI libraries (found by the executables through the relative
loader path `../lib`), and `licences/`. These are the fixed places the host and the demo use
when no variable names an executable. Nothing test-only is installed.

Instead of installing the native part, each executable can be named by an absolute path:
`SYNAPSE_HLA_WORKER`, `SYNAPSE_HLA_PUBLISHER` and `SYNAPSE_HLA_RTINODE`. A relative path in one
of them is refused; no executable is ever looked for on `PATH`.

## Checking the installation

From any directory outside the checkout:

```
"$WORK/venv/bin/synapse-hla" --version          # exit 0, prints the version line
"$WORK/venv/bin/synapse-hla" self-test --out st # exit 0: every packaged fixture, offline
"$WORK/venv/bin/synapse-hla" demo --out demo    # exit 0: the synthetic reference run
```

`self-test` exits 4 when `SYNAPSE_HLA_FOM_DIR` is not set: its FOM pin check is then BLOCKED and
the rest still runs. `demo` exits 4 (a BLOCKED `demo.json`) when the worker, the publisher or
`rtinode` is missing; 0 when every semantic checkpoint passed in both of its runs and everything
it started was stopped. The demo starts its own `rtinode` on 127.0.0.1, its publisher creates a
federation `SC_DEMO_<16 hexadecimal digits>` from the five pinned modules, and the observer joins
it twice: once with time policy `external_elapsed` under the documented synthetic assumption that
the scenario clock runs at 1x from the configured epoch, once with time policy `none` (snapshots,
no Entity). OpenRTI is the tested reference; no customer simulator and no second RTI
implementation is tested.

## What the commands keep and what they never do

- `observe` joins an existing federation and writes `capture.jsonl` (the hash-chained capture),
  `observations.jsonl`, `diagnostics.jsonl` and `run.json` into a new directory. It publishes
  nothing, creates and destroys no federation, and never controls a simulation.
- `replay` verifies a capture from its first byte to its last and reduces it again into a new
  directory; a capture that is not complete is replayed only as a prefix on request
  (`--allow-prefix`), and every record of a prefix says so.
- `export-capture` copies a verified original capture byte for byte. It is not an HLA
  re-export: it does not edit or re-encode HLA data, constructs no HLA packets and replays no
  traffic into an RTI.
- A retractable update or removal is captured and quarantines its object. Nothing in this
  release can undo a retractable update, live or in replay.
- When `rtinode` exits, or the RTI connection ends with an orderly close, OpenRTI gives the
  observer no connection loss but a removal of every object it knows; last-received values are
  not kept. Objects whose publishing federate publishes only a subclass of `PhysicalEntity` are
  not discovered through the pinned OpenRTI (both are limitations of the baseline; the README
  lists them all).
- `external_customer_interoperability` is `NOT_TESTED` in every report this release writes.

## Upgrading synapse-cdm (R44)

The package validates every Entity against the CDM schema 3.0.0 it carries
(`src/synapse_hla/schemas/cdm-entity.schema.json`, the handoff's bytes) and constructs it as
the installed SDK's `synapse_cdm.models.Entity`. It declares `synapse-cdm>=3.8.0,<4`, whose floor
is the release it was moved to the repository's main line on, and it is locked and tested with
synapse-cdm 3.9.0, the release it landed at. Before any other synapse-cdm is used with it:

1. keep the packaged fixtures unchanged (`src/synapse_hla/fixtures/`, pinned in
   `tests/contract/vendored-pins.json`);
2. run `tests/test_hla_projector.py::test_the_cdm_baseline_and_its_complete_entity_schema` and
   the offline group: the new SDK's Entity schema must be additive over the 3.0.0 one (the same
   properties, required members, `additionalProperties` and definitions, each identical or
   differing only by the `schema_version` default or by an enum that keeps every value), and the
   packaged capture must still replay to the packaged expected observations byte for byte (every
   other test must pass too: with a later SDK inside the declared range none fails by design,
   and with an earlier one than the locked 3.9.0 three fail by design until step 4 is done: the
   two that hold the installed set to the locks and the SBOM, and the one that holds the version
   the evidence report was tested with to at most the installed one);
3. record the migration in the README's section "The CDM": the differences found and how they
   were re-verified;
4. regenerate `locks/` for the set in use (`locks/tested-set.in`, the three lock files with the
   command each names in its first lines, and the SBOM with `python tests/release_sbom.py`) and
   the evidence report with it: the offline group and the SBOM tool hold every other installed
   locked distribution to its locked version, and synapse-cdm, this repository's sibling
   distribution, to the declared range at or above its locked version.

An SDK whose Entity changed in any other way fails step 2, naming the place; that is where a
migration starts, and a new profile version is needed if the change is not additive.

## Removing an installation

`pip uninstall synapse-hla` removes the Python distribution but not the native part, which pip
did not install: remove `bin/`, `lib/` and `licences/` of the package directory as well, or the
whole virtual environment. The build directories under `$WORK` are independent of both.
