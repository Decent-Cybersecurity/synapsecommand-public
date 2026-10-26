# Release evidence: synapse-hla 1.0.0, profile SC-HLA-RPR2-OBS-1

Written by `tests/release_evidence.py` from the runs of one release session (`evidence-report.json` beside this file holds everything below, and more: every test of every case with its outcome in every run). Nothing here is typed by hand.

- **Overall status: BLOCKED.**
- **external_customer_interoperability: NOT_TESTED** (no witnessed report exists).
- Cases: PASS 140, FAIL 0, BLOCKED 7.
- Source: base commit `36086bb5db88e6679812c6548bdbcc503b6e854f`, source commit null (the release commit does not exist when its evidence is generated and is never invented (OPS-10); the tree is identified by source_sha256 over its files), source SHA-256 `ab68ae7e7f640bfcd731a50a25d8bafa576daf27f6c2fc72c6d10f248f0d980a` over 147 files.

## Evidence classes

- `DEV-linux-aarch64`: the Linux reference run's aarch64 machine (Ubuntu 24.04, GCC 13, CMake 3.28): development evidence, not R42's x86_64 machine.
- `DEV-macOS-arm64`: the development Mac (macOS, arm64; OpenRTI built as C++98 there, NAT-02): development evidence, never release evidence.
- `REFERENCE-linux-x86_64`: the reference platform (Linux x86_64, Ubuntu 24.04, GCC 13 (C++14), CMake 3.28 to 3.31): no run of this release was made there.

## Release gates (R48)

| Gate | Status | Evidence class | Blocked on |
|---|---|---|---|
| contract and dependency hashes verified | PASS | DEV-macOS-arm64 | - |
| all offline tests PASS | PASS | DEV-macOS-arm64 | - |
| reference encoding and geodesy checks PASS | BLOCKED | DEV-macOS-arm64 | the reference tools built and run on the reference platform (GCC 13) |
| local OpenRTI lifecycle exercise PASS | BLOCKED | DEV-macOS-arm64 | the local OpenRTI lifecycle exercise on the reference platform (CR-L04): the demo PASSes on the development platforms only |
| overload and failure tests PASS | PASS | DEV-macOS-arm64 | - |
| performance test PASS | BLOCKED | DEV-macOS-arm64 | R42's recorded 4-vCPU x86_64 machine with 8 GiB on the reference platform |
| no unresolved severity-high defects | BLOCKED | - | the records of the independent reviews of this release tree (the packaging round's two reviews, the final review and the review of the fix pass that followed it), which are kept in the release run's kit outside this tree: a gate reads PASS only from evidence the tree carries (A-EVIDENCE, CR-L25) |
| reproducible build and licence review completed | BLOCKED | DEV-macOS-arm64 | the reference build (Linux x86_64, Ubuntu 24.04, GCC 13 (C++14), CMake 3.28 to 3.31) and the SHA-256 of the distribution packages of its toolchain |
| claims matching the tested scope | PASS | DEV-macOS-arm64 | - |

## Runs of this session

| Run | Group | Python | Platform | Class | Counts | Command |
|---|---|---|---|---|---|---|
| offline-py311 | offline | 3.11.15 | Darwin arm64 | DEV-macOS-arm64 | passed 3181 | `cd packages/hla && SYNAPSE_HLA_FOM_DIR=<kit> python -m pytest -p no:cacheprovider -m "not rti and not perf and not reference"` |
| offline-py312 | offline | 3.12.13 | Darwin arm64 | DEV-macOS-arm64 | passed 3181 | `cd packages/hla && SYNAPSE_HLA_FOM_DIR=<kit> python -m pytest -p no:cacheprovider -m "not rti and not perf and not reference"` |
| offline-py314 | offline | 3.14.7 | Darwin arm64 | DEV-macOS-arm64 | passed 3181 | `cd packages/hla && SYNAPSE_HLA_FOM_DIR=<kit> python -m pytest -p no:cacheprovider -m "not rti and not perf and not reference"` |
| rti-py312 | rti | 3.12.13 | Darwin arm64 | DEV-macOS-arm64 | passed 213 | `cd packages/hla && SYNAPSE_HLA_FOM_DIR=<kit> SYNAPSE_HLA_WORKER=<native>/bin/sc-hla-federate SYNAPSE_HLA_HARNESS=<native>/bin/sc-hla-harness SYNAPSE_HLA_PUBLISHER=<native>/bin/sc-hla-publisher SYNAPSE_HLA_RTINODE=<openrti>/bin/rtinode python -m pytest -p no:cacheprovider -m "rti"` |
| perf-py312 | perf | 3.12.13 | Darwin arm64 | DEV-macOS-arm64 | passed 3, skipped 1 | `cd packages/hla && SYNAPSE_HLA_FOM_DIR=<kit> SYNAPSE_HLA_WORKER=<native>/bin/sc-hla-federate SYNAPSE_HLA_HARNESS=<native>/bin/sc-hla-harness SYNAPSE_HLA_PUBLISHER=<native>/bin/sc-hla-publisher SYNAPSE_HLA_RTINODE=<openrti>/bin/rtinode python -m pytest -p no:cacheprovider -m "perf"` |
| reference-py312 | reference | 3.12.13 | Darwin arm64 | DEV-macOS-arm64 | passed 1 | `cd packages/hla && SYNAPSE_HLA_FOM_DIR=<kit> SYNAPSE_HLA_WORKER=<native>/bin/sc-hla-federate SYNAPSE_HLA_HARNESS=<native>/bin/sc-hla-harness SYNAPSE_HLA_PUBLISHER=<native>/bin/sc-hla-publisher SYNAPSE_HLA_RTINODE=<openrti>/bin/rtinode python -m pytest -p no:cacheprovider -m "reference"` |

## Cases

| Case | Requirement | Result | Class | Tests | Passed/failed/skipped/not run | Blocked on |
|---|---|---|---|---|---|---|
| G-R01 | R01 | PASS | DEV-macOS-arm64 | 42 | 126/0/0/0 | - |
| G-R02 | R02 | BLOCKED | DEV-macOS-arm64 | 48 | 132/0/0/0 | the reference platform (Linux x86_64, Ubuntu 24.04, GCC 13 (C++14), CMake 3.28 to 3.31) for SPEC:20's native build and rti group: no run there; the development runs are DEV evidence |
| G-R03 | R03 | PASS | DEV-macOS-arm64 | 28 | 84/0/0/0 | - |
| G-R04 | R04 | PASS | DEV-macOS-arm64 | 5 | 15/0/0/0 | - |
| G-R05 | R05 | PASS | DEV-macOS-arm64 | 14 | 40/0/0/0 | - |
| G-R06 | R06 | PASS | DEV-macOS-arm64 | 120 | 120/0/0/0 | - |
| G-R07 | R07 | PASS | DEV-macOS-arm64 | 366 | 1082/0/0/0 | - |
| G-R08 | R08 | PASS | DEV-macOS-arm64 | 298 | 894/0/0/0 | - |
| G-R09 | R09 | PASS | DEV-macOS-arm64 | 13 | 39/0/0/0 | - |
| G-R10 | R10 | PASS | DEV-macOS-arm64 | 46 | 72/0/0/0 | - |
| G-R11 | R11 | PASS | DEV-macOS-arm64 | 11 | 29/0/0/0 | - |
| G-R12 | R12 | PASS | DEV-macOS-arm64 | 60 | 62/0/0/0 | - |
| G-R13 | R13 | PASS | DEV-macOS-arm64 | 23 | 49/0/0/0 | - |
| G-R14 | R14 | PASS | DEV-macOS-arm64 | 161 | 401/0/0/0 | - |
| G-R15 | R15 | PASS | DEV-macOS-arm64 | 180 | 532/0/0/0 | - |
| G-R16 | R16 | PASS | DEV-macOS-arm64 | 154 | 388/0/0/0 | - |
| G-R17 | R17 | PASS | DEV-macOS-arm64 | 110 | 330/0/0/0 | - |
| G-R18 | R18 | PASS | DEV-macOS-arm64 | 259 | 771/0/0/0 | - |
| G-R19 | R19 | PASS | DEV-macOS-arm64 | 46 | 138/0/0/0 | - |
| G-R20 | R20 | PASS | DEV-macOS-arm64 | 33 | 99/0/0/0 | - |
| G-R21 | R21 | PASS | DEV-macOS-arm64 | 48 | 144/0/0/0 | - |
| G-R22 | R22 | PASS | DEV-macOS-arm64 | 54 | 162/0/0/0 | - |
| G-R23 | R23 | PASS | DEV-macOS-arm64 | 32 | 96/0/0/0 | - |
| G-R24 | R24 | PASS | DEV-macOS-arm64 | 25 | 75/0/0/0 | - |
| G-R25 | R25 | PASS | DEV-macOS-arm64 | 30 | 86/0/0/0 | - |
| G-R26 | R26 | PASS | DEV-macOS-arm64 | 58 | 174/0/0/0 | - |
| G-R27 | R27 | PASS | DEV-macOS-arm64 | 11 | 33/0/0/0 | - |
| G-R28 | R28 | PASS | DEV-macOS-arm64 | 20 | 60/0/0/0 | - |
| G-R29 | R29 | PASS | DEV-macOS-arm64 | 43 | 127/0/0/0 | - |
| G-R30 | R30 | PASS | DEV-macOS-arm64 | 41 | 123/0/0/0 | - |
| G-R31 | R31 | PASS | DEV-macOS-arm64 | 10 | 30/0/0/0 | - |
| G-R32 | R32 | PASS | DEV-macOS-arm64 | 15 | 45/0/0/0 | - |
| G-R33 | R33 | PASS | DEV-macOS-arm64 | 42 | 126/0/0/0 | - |
| G-R34 | R34 | PASS | DEV-macOS-arm64 | 72 | 216/0/0/0 | - |
| G-R35 | R35 | PASS | DEV-macOS-arm64 | 77 | 231/0/0/0 | - |
| G-R36 | R36 | PASS | DEV-macOS-arm64 | 198 | 572/0/0/0 | - |
| G-R37 | R37 | PASS | DEV-macOS-arm64 | 201 | 603/0/0/0 | - |
| G-R38 | R38 | BLOCKED | DEV-macOS-arm64 | 28 | 40/0/0/0 | the demo built and run on the reference platform (Linux x86_64, Ubuntu 24.04, GCC 13 (C++14), CMake 3.28 to 3.31) |
| G-R39 | R39 | PASS | DEV-macOS-arm64 | 52 | 104/0/0/0 | - |
| G-R40 | R40 | PASS | DEV-macOS-arm64 | 281 | 843/0/0/0 | - |
| G-R41 | R41 | PASS | DEV-macOS-arm64 | 105 | 115/0/0/0 | - |
| G-R42 | R42 | BLOCKED | DEV-macOS-arm64 | 4 | 7/0/1/0 | R42's recorded 4-vCPU x86_64 machine with 8 GiB on the reference platform |
| G-R43 | R43 | BLOCKED | DEV-macOS-arm64 | 40 | 118/0/0/0 | the reference build (Linux x86_64, Ubuntu 24.04, GCC 13 (C++14), CMake 3.28 to 3.31) and the SHA-256 of the distribution packages of its toolchain |
| G-R44 | R44 | PASS | DEV-macOS-arm64 | 85 | 255/0/0/0 | - |
| G-R45 | R45 | PASS | DEV-macOS-arm64 | 41 | 123/0/0/0 | - |
| G-R46 | R46 | PASS | DEV-macOS-arm64 | 32 | 96/0/0/0 | - |
| G-R47 | R47 | BLOCKED | DEV-macOS-arm64 | 7 | 15/0/0/0 | the reference tools built and run on the reference platform (GCC 13) |
| G-R48 | R48 | BLOCKED | DEV-macOS-arm64 | 3 | 9/0/0/0 | the release gates 'local OpenRTI lifecycle exercise' and 'performance test' on the reference platform |
| G-R49 | R49 | PASS | DEV-macOS-arm64 | 11 | 31/0/0/0 | - |
| G-R50 | R50 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| V-SPATIAL-1 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| V-SPATIAL-2 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| V-SPATIAL-3 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| V-SPATIAL-4 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| V-SPATIAL-5 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| V-SPATIAL-6 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| V-SPATIAL-7 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| V-SPATIAL-8 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| V-SPATIAL-9 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| V-ID-123 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| V-TYPE-PLATFORM | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| V-FORCE-1 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| V-FORCE-255 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| V-SPATIAL-PADDING | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRUNC-1 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRAIL-1 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRUNC-2 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRAIL-2 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRUNC-3 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRAIL-3 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRUNC-4 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRAIL-4 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRUNC-5 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRAIL-5 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRUNC-6 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRAIL-6 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRUNC-7 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRAIL-7 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRUNC-8 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRAIL-8 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRUNC-9 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-TRAIL-9 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-ALG-0 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-ALG-10 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-ALG-255 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-NONFINITE-8 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-NONFINITE-36 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-NONFINITE-48 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-NONFINITE-60 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-NONFINITE-72 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-BOOL-2 | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-LENGTH-EntityIdentifier | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-LENGTH-EntityType | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| N-LENGTH-ForceIdentifier | R18 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-PARTIAL-ORDER | R22 | PASS | DEV-macOS-arm64 | 24 | 72/0/0/0 | - |
| A-ATOMIC | R22 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-REPAIR | R22 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-FORCE-ABSENT | R23 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-FORCE-INVALID | R23 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-FORCE-UNMAPPED | R09 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-NULL-ID | R19 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-COLLISION | R24 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-ID-CHANGE | R24 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-REINCARNATE | R25 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-RECONNECT | R14 | PASS | DEV-macOS-arm64 | 5 | 15/0/0/0 | - |
| A-NO-TIME | R08 | PASS | DEV-macOS-arm64 | 2 | 6/0/0/0 | - |
| A-TIME-CONTEXT | R32 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-BODY | R30 | PASS | DEV-macOS-arm64 | 8 | 24/0/0/0 | - |
| A-STATIC | R30 | PASS | DEV-macOS-arm64 | 2 | 6/0/0/0 | - |
| A-ATTITUDE | R31 | PASS | DEV-macOS-arm64 | 2 | 6/0/0/0 | - |
| A-POLE | R30 | PASS | DEV-macOS-arm64 | 2 | 6/0/0/0 | - |
| A-EMPTY | R22 | PASS | DEV-macOS-arm64 | 2 | 4/0/0/0 | - |
| A-REPEATED | R22 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-UNKNOWN | R22 | PASS | DEV-macOS-arm64 | 2 | 6/0/0/0 | - |
| A-UNSUBSCRIBED | R12 | PASS | DEV-macOS-arm64 | 4 | 6/0/0/0 | - |
| A-REMOVE | R25 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-END | R25 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-RETRACT | R13 | PASS | DEV-macOS-arm64 | 6 | 14/0/0/0 | - |
| A-DUPLICATE-KEY | R07 | PASS | DEV-macOS-arm64 | 4 | 12/0/0/0 | - |
| A-UTF8 | R07 | PASS | DEV-macOS-arm64 | 6 | 18/0/0/0 | - |
| A-HASH | R15 | PASS | DEV-macOS-arm64 | 16 | 48/0/0/0 | - |
| A-TRUNCATED | R17 | PASS | DEV-macOS-arm64 | 4 | 12/0/0/0 | - |
| A-SEQ-GAP | R15 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-CANONICAL | R15 | PASS | DEV-macOS-arm64 | 13 | 39/0/0/0 | - |
| A-REPLAY | R35 | PASS | DEV-macOS-arm64 | 3 | 9/0/0/0 | - |
| A-PREFIX | R17 | PASS | DEV-macOS-arm64 | 4 | 12/0/0/0 | - |
| A-OUTPUT-IDEMPOTENCE | R33 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-NO-PUBLISH | R39 | PASS | DEV-macOS-arm64 | 1 | 1/0/0/0 | - |
| A-NO-CREATE | R10 | PASS | DEV-macOS-arm64 | 2 | 2/0/0/0 | - |
| A-MISSING-FOM | R10 | PASS | DEV-macOS-arm64 | 1 | 1/0/0/0 | - |
| A-CLASS | R10 | PASS | DEV-macOS-arm64 | 2 | 2/0/0/0 | - |
| A-NAME-CONFLICT | R14 | PASS | DEV-macOS-arm64 | 1 | 1/0/0/0 | - |
| A-TIMEOUT | R14 | PASS | DEV-macOS-arm64 | 8 | 22/0/0/0 | - |
| A-OVERFLOW | R41 | PASS | DEV-macOS-arm64 | 15 | 15/0/0/0 | - |
| A-OBJECT-LIMIT | R40 | PASS | DEV-macOS-arm64 | 1 | 3/0/0/0 | - |
| A-ATTRIBUTE-LIMIT | R40 | PASS | DEV-macOS-arm64 | 1 | 1/0/0/0 | - |
| A-TAG-LIMIT | R40 | PASS | DEV-macOS-arm64 | 2 | 2/0/0/0 | - |
| A-FILE-LIMIT | R40 | PASS | DEV-macOS-arm64 | 3 | 9/0/0/0 | - |
| A-DISK | R34 | PASS | DEV-macOS-arm64 | 10 | 30/0/0/0 | - |
| A-SIGNAL | R36 | PASS | DEV-macOS-arm64 | 16 | 42/0/0/0 | - |
| A-REMOTE | R07 | PASS | DEV-macOS-arm64 | 6 | 18/0/0/0 | - |
| A-DEPENDENCY | R04 | PASS | DEV-macOS-arm64 | 14 | 42/0/0/0 | - |
| A-XML | R40 | PASS | DEV-macOS-arm64 | 60 | 180/0/0/0 | - |
| A-DEMO | R38 | PASS | DEV-macOS-arm64 | 23 | 67/0/0/0 | - |
| A-ENCODING | R47 | PASS | DEV-macOS-arm64 | 1 | 1/0/0/0 | - |
| A-PERFORMANCE | R42 | BLOCKED | DEV-macOS-arm64 | 2 | 3/0/1/0 | R42's recorded 4-vCPU x86_64 machine with 8 GiB on the reference platform |
| A-EVIDENCE | R48 | PASS | DEV-macOS-arm64 | 4 | 12/0/0/0 | - |

## Performance (R42, A-PERFORMANCE)

Status: BLOCKED (R42's recorded 4-vCPU x86_64 machine with 8 GiB on the reference platform). R42's 1000 reflections per second with every reflection projected and validated as a CDM Entity (R44) is AT RISK on a 4-vCPU machine: in R42's shape with that configuration the worker's queue overflowed in 2 of the 3 Linux aarch64 runs (reference_run); this session's development run lost no load reflection (60000 of 60000 output), with a p95 callback-to-output delay of 875 ms against R42's 250 ms (observation below) (CR-L17, CR-R8-12).

- perf-py312, `tests/test_hla_rti.py::test_r42_load_on_the_reference_machine_without_loss_within_the_p95_target`: {"capture_status": "COMPLETE", "frames": 63932, "load_captured": 60000, "load_expected": 60000, "load_with_output": 60000, "machine": {"cpus": 18, "distribution": null, "evidence_class": "DEV-macOS-arm64", "filesystem": {"device": "/dev/disk3s5", "mount_point": "/System/Volumes/Data", "type": "apfs"}, "load_average_1m": "1.08", "machine": "arm64", "memory_bytes": 137438953472, "python": "3.12.13", "release": "25.5.0", "system": "Darwin", "worker_sha256": "377c145fc3f73ed10376449a560129610aface8e034df88340c2d28a9d6e7234"}, "overflow": false, "p50_ms": 480, "p95_ms": 875, "p95_ns": 875982000, "p99_ms": 1120, "session_status": "COMPLETE", "shape": "perf:1000:1:60", "terminal_codes": [], "throughput_per_s": 1001}

## The CDM (R44)

- Contract: CDM schema 3.0.0, `src/synapse_hla/schemas/cdm-entity.schema.json` (SHA-256 `310d04623b4647e0f92abd384a48683df783495ec9e1ffd1bedf85ee18bf092a`).
- Handoff baseline: synapse-cdm 3.1.1 at `c4bba1b6ebfdfe956f6efc2b3a81a04db2b4bb5b`: the source of the vendored cdm-entity schema and of the fixtures; the package was developed and tested against it before landing.
- Floor: `synapse-cdm>=3.8.0,<4` (synapse-cdm 3.8.0, schema 3.2.0, at `0d4cf0e00f9636752c87fe47b50726aa0015b460`); tested with 3.9.0.
- Migration: the installed SDK's Entity schema differs from the vendored 3.0.0 one only by the schema_version default and the PositionSource enum (+SENSOR, +UNKNOWN), both additive; re-verified by the additivity test and the byte-identical replay of the packaged capture.
- Upgrade rule: a later synapse-cdm must keep the packaged fixtures, stay additive over the vendored 3.0.0 Entity schema, pass the additivity test and the byte-identical replay, and record its migration (README, "The CDM"); moving the locked set (synapse-cdm 3.9.0) also needs locks/ (the lock files and the SBOM) and this report regenerated for the set in use, because the offline group holds every other installed locked distribution to its locked version and synapse-cdm, the repository's sibling distribution, to the declared range at or above its locked version (CR-L22).
- R44's baseline 3.1.1 is history, not the supported floor: a recorded deviation on the owner list (CR-L18).

## Cross-interpreter pins and geodesy

Platforms with a pin: `darwin-arm64` (Python 3.11.15, 3.12.13, 3.14.7 in this session's runs; agreement across interpreters shown), `linux-aarch64` (Python 3.12.3 in reference run ref-1 of 2026-10-25; agreement across interpreters not observable: one interpreter); linux-x86_64 has no pin: the 10,000-point test fails there with its computed digest until a run there records one (CR-R1-06).

The packaged capture replays byte for byte on darwin-arm64 and linux-aarch64 (its observations' SHA-256 d55fd510bf633395192f4ead01cab1753216d870a9219d023a8525138ef05125). Of the 10,000-point grid, 674 inputs differ by one or two units in the last place of position_ecef_m between the C libraries (612 coordinate values by 1 ulp, 79 by 2 ulp; the test's own generator uses math.cos and math.sin); of the 9,326 identical inputs, 5 outputs differ by one unit in the sixth decimal of alt_m (1e-6 m) at altitudes of 27,451 to 89,704 km, latitude, longitude and kinematics agreeing. Byte identity across platforms is therefore not guaranteed at extreme heights. Identity across interpreters on one platform (what CR-R1-06 pins) is shown on darwin-arm64 (3.11, 3.12, 3.14: Python 3.11.15, 3.12.13 and 3.14.7 in this session's runs) and not observable on linux-aarch64, whose pin was recorded from one interpreter (Python 3.12.3, reference run ref-1 of 2026-10-25) (CR-L20).

PROJ as each run of the reference group measured it (CDV-02):

- reference-py312 (DEV-macOS-arm64): `$HOMEBREW_PREFIX/bin/cs2cs` stated `Rel. 9.9.0, September 15th, 2026`; read from the observation the reference-group test recorded in this run.
- ref-1 (DEV-linux-aarch64): `/usr/bin/cs2cs` stated `Rel. 9.4.0, March 1st, 2024`; read from the reference run's files (reference_run.proj).

## Integration report

- allowed_claim: Receives and replays the tested RPR FOM 2.0 physical-entity attribute subset through the pinned OpenRTI baseline and projects externally timed state into CDM.
- co_publication: Through the pinned OpenRTI, objects from other processes whose federate publishes only a subclass of PhysicalEntity are not discovered; the synthetic publisher publishes at PhysicalEntity and at GroundVehicle.
- demo_clock: The demo uses external_elapsed only under the documented synthetic 1x scenario-clock assumption (the scenario clock runs at 1x from the configured epoch); its second run uses time policy none and fabricates no Entity.
- excluded_claims: all-HLA support; full RPR FOM support; verified integration with any site or installation, the one that motivated the specification included; verified SWORD, WASP or Nebula integration; automatic simulator control; source-authoritative UTC timing; DIS/HLA identity fusion; authenticated RTI transport.
- fom_outside: The five RPR FOM modules and the OpenRTI source archive are not in the repository: the release evidence kit supplies them, held to their pins (a recorded deviation from R05, OPV-03).
- orderly_exit: When rtinode exits or the connection ends with FIN, the observer gets no connectionLost but a removal of every object it knows; last-received values are never kept.
- public_reference: OpenRTI's participation demonstrates a public reference, not standards certification or a second independent RTI federation test.
- retractable: A retractable update is captured and quarantines its object; no claim is made that replay can undo a retractable update.
- tested_reference: OpenRTI 814a210978b7faafd65affbe70a2e25679921b23 is the tested reference; neither a customer simulator nor a second RTI implementation was tested.
- transport: RTI traffic is neither authenticated nor encrypted by this adapter; a remote deployment relies on an externally secured network.

## The Linux reference run (DEV-linux-aarch64)

- Run: `ref-1`, ended 2026-10-25, Python 3.12.3; PROJ `Rel. 9.4.0, March 1st, 2024` (`/usr/bin/cs2cs`).
- Tree: the accepted tree before this release, with this release's three portability fixes applied as patches where a step needed them.
- Build record: platform Linux aarch64, cmake version 3.28.3, c++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0, policy flag no, C++ standard 14.
- The record's evidence line as written: "the reference configuration when run on Linux x86_64, Ubuntu 24.04, GCC 13"; corrected: DEV-linux-aarch64: the record's evidence line was written by the wrapper whatever the machine; this release's wrapper names a non-reference machine as development evidence (CR-L21).
- ctest: 100% tests passed, 0 tests failed out of 100; offline group: 1 failed, 3084 passed, 213 deselected; rti group unpatched: 3 failed, 207 passed, 3088 deselected, patched: 210 passed, 3088 deselected; reference group: 1 passed, 3297 deselected; perf group: 2 passed, 3296 deselected.
- self-test: PASS {'BLOCKED': 0, 'FAIL': 0, 'PASS': 85}.
- Demos: PASS (manifest class as written `DEV-Linux-aarch64`, refresh seqs [[4], []]); PASS (manifest class as written `DEV-Linux-aarch64`, refresh seqs [[4], [4]]).
- Demo timing: In some Linux demo sessions the publisher answered the observer's request for values after step 1 with a refresh reflection; the Mac's demos have shown the same answer, less often. A difference of frequency, not of kind, allowed by R38; every checkpoint passed.
- Labels: This report spells the classes as CR-L04 does (DEV-macOS-arm64, DEV-linux-aarch64); a demo manifest writes the platform's own spelling, quoted here as written.
- Tree manifest: taken in the container before the first step and after the last; equal.
- R42-shaped runs: r42-main-1 perf:1000:1:60 main: 60000 of 60000 load reflections, footer COMPLETE; r42-main-2 perf:1000:1:60 main: 51650 of 60000 load reflections, footer FAILED E_QUEUE_OVERFLOW; r42-main-3 perf:1000:1:60 main: 12587 of 60000 load reflections, footer FAILED E_QUEUE_OVERFLOW; r42-none-1 perf:1000:1:60 no-time: 60000 of 60000 load reflections, footer COMPLETE; r42-none-2 perf:1000:1:60 no-time: 60000 of 60000 load reflections, footer COMPLETE; r42-overflow-1 perf:1000:5:20 main: 1000 of 100000 load reflections, footer FAILED E_QUEUE_OVERFLOW.

## Session observations

- clean_checkout: {"demo_files": ["demo.json", "main-replay/capture.jsonl", "main-replay/diagnostics.jsonl", "main-replay/observations.jsonl", "main-replay/run.json", "main/capture.jsonl", "main/diagnostics.jsonl", "main/observations.jsonl", "main/run.json", "no-time-replay/capture.jsonl", "no-time-replay/diagnostics.jsonl", "no-time-replay/observations.jsonl", "no-time-replay/run.json", "no-time/capture.jsonl", "no-time/diagnostics.jsonl", "no-time/observations.jsonl", "no-time/run.json"], "demo_status": "PASS", "in_tree_build_output": ["build/", "src/synapse_hla.egg-info/"], "offline_tests": {"command": "SYNAPSE_HLA_FOM_DIR=... \"$WORK/venv/bin/python\" -m pytest -m \"not rti and not perf and not reference\"", "exit": 0, "summary": "3181 passed, 218 deselected"}, "openrti_record": {"cmake": "cmake version 4.4.2", "compiler": "Apple clang version 21.0.0 (clang-2100.1.1.101)", "cxx_standard_in_cache": "98", "evidence": "development evidence only (macOS: OpenRTI configured as C++98, NAT-02)", "platform": "Darwin arm64", "policy_version_minimum_added": "yes"}, "replay_files": ["capture.jsonl", "diagnostics.jsonl", "observations.jsonl", "run.json"], "results": [{"exit": 0, "line": "export WORK=/absolute/new/directory SYNAPSE_HLA_FOM_DIR=/absolute/directory/of/the/kit", "tail": "(environment)"}, {"exit": 0, "expected": "0", "line": "python3.12 -m venv \"$WORK/venv\"", "tail": ""}, {"exit": 0, "expected": "0", "line": "\"$WORK/venv/bin/python\" -m pip install --require-hashes -r locks/test.lock", "tail": "Successfully installed annotated-types-0.8.0 attrs-26.1.0 iniconfig-2.3.1 jsonschema-4.26.0 jsonschema-specifications-2025.9.1 packaging-26.3 pluggy-1.7.0 pydantic-2.14.1 pydantic-core-2.50.1 pygments-2.21.0 pytest-9.1.1 referencing-0.37.0 rpds-py-2026.9.1 synapse-cdm-3.9.0 typing-extensions-4.16.0 typing-inspection-0.4.4"}, {"exit": 0, "expected": "0", "line": "\"$WORK/venv/bin/python\" -m pip install --require-hashes -r locks/build.lock", "tail": "Successfully installed setuptools-84.2.1"}, {"exit": 0, "expected": "0", "line": "\"$WORK/venv/bin/python\" -m pip install --no-deps --no-build-isolation .", "tail": "Successfully installed synapse-hla-1.0.0"}, {"exit": 0, "expected": "0", "line": "bash tools/build_openrti.sh \"$SYNAPSE_HLA_FOM_DIR/openrti-814a210.tar.gz\" \"$WORK/openrti\"", "tail": "Evidence: development evidence only (macOS: OpenRTI configured as C++98, NAT-02)"}, {"exit": 0, "expected": "0", "line": "cmake -S src/native -B \"$WORK/native\" -DOPENRTI_PREFIX=\"$WORK/openrti/install\"", "tail": "-- Build files have been written to: <clean>/work/native"}, {"exit": 0, "expected": "0", "line": "cmake --build \"$WORK/native\"", "tail": "[100%] Built target sc-hla-test-federate"}, {"exit": 0, "expected": "0", "line": "ctest --test-dir \"$WORK/native\"", "tail": "100% tests passed out of 100"}, {"exit": 0, "expected": null, "line": "PKG=$(\"$WORK/venv/bin/python\" -c 'import os, synapse_hla; print(os.path.dirname(synapse_hla.__file__))')", "tail": ""}, {"exit": 0, "expected": "0", "line": "cmake --install \"$WORK/native\" --prefix \"$PKG\"", "tail": "-- Installing: <clean>/work/venv/lib/python3.12/site-packages/synapse_hla/licences/openrti/mpl-2.0"}, {"exit": 0, "line": "cd \"$WORK\"", "tail": "(environment)"}, {"exit": 0, "expected": "0", "line": "venv/bin/synapse-hla --version", "tail": "{\"name\":\"synapse-hla\",\"version\":\"1.0.0\",\"profile\":\"SC-HLA-RPR2-OBS-1\"}"}, {"exit": 0, "expected": "0", "line": "venv/bin/synapse-hla self-test --out selftest", "tail": "{\"cli_summary_version\":1,\"command\":\"self-test\",\"exit_code\":0,\"codes\":[],\"result\":{\"result\":\"PASS\",\"cases\":85,\"passed\":85,\"failed\":0,\"blocked\":0,\"failed_ids\":[],\"blocked_ids\":[]}}"}, {"exit": 0, "expected": "0", "line": "venv/bin/synapse-hla demo --out demo", "tail": "{\"cli_summary_version\":1,\"command\":\"demo\",\"exit_code\":0,\"codes\":[\"W_TIME_UNRESOLVED\"],\"result\":{\"status\":\"PASS\",\"runs\":[{\"name\":\"main\",\"result\":\"PASS\",\"failed_checkpoints\":[]},{\"name\":\"no-time\",\"result\":\"PASS\",\"failed_checkpoints\":[]}],\"failures\":[],\"cleanup\":\"PASS\"}}"}, {"exit": 0, "expected": "0", "line": "venv/bin/synapse-hla inspect --capture demo/main/capture.jsonl", "tail": "{\"cli_summary_version\":1,\"command\":\"inspect\",\"exit_code\":0,\"codes\":[],\"result\":{\"verification\":{\"verify_report_version\":1,\"status\":\"COMPLETE\",\"code\":null,\"path\":null,\"message\":null,\"verified_seq\":9,\"verified_bytes\":5097,\"frames\":8,\"header_sha256\":\"088b3005d32c8d3d79b4a4e7e57fd9a1c3b696dcc9158420d374800bc01f152e\",\"last_sha256\":\"677d08d18fcf684595317ec24cfa48c294ee4c7ddcd55970c56e94d5362207a0\",\"capt"}, {"exit": 0, "expected": "0", "line": "venv/bin/synapse-hla verify --capture demo/main/capture.jsonl", "tail": "{\"cli_summary_version\":1,\"command\":\"verify\",\"exit_code\":0,\"codes\":[],\"result\":{\"verification\":{\"verify_report_version\":1,\"status\":\"COMPLETE\",\"code\":null,\"path\":null,\"message\":null,\"verified_seq\":9,\"verified_bytes\":5097,\"frames\":8,\"header_sha256\":\"088b3005d32c8d3d79b4a4e7e57fd9a1c3b696dcc9158420d374800bc01f152e\",\"last_sha256\":\"677d08d18fcf684595317ec24cfa48c294ee4c7ddcd55970c56e94d5362207a0\",\"captu"}, {"exit": 0, "expected": "0", "line": "venv/bin/synapse-hla replay --capture demo/main/capture.jsonl --out replay", "tail": "{\"cli_summary_version\":1,\"command\":\"replay\",\"exit_code\":0,\"codes\":[],\"result\":{\"verification\":{\"verify_report_version\":1,\"status\":\"COMPLETE\",\"code\":null,\"path\":null,\"message\":null,\"verified_seq\":9,\"verified_bytes\":5097,\"frames\":8,\"header_sha256\":\"088b3005d32c8d3d79b4a4e7e57fd9a1c3b696dcc9158420d374800bc01f152e\",\"last_sha256\":\"677d08d18fcf684595317ec24cfa48c294ee4c7ddcd55970c56e94d5362207a0\",\"captu"}, {"exit": 0, "expected": "0", "line": "cmp demo/main-replay/observations.jsonl replay/observations.jsonl", "tail": ""}], "rti_tests": {"command": "SYNAPSE_HLA_FOM_DIR=... SYNAPSE_HLA_WORKER=\"$WORK/native/bin/sc-hla-federate\" SYNAPSE_HLA_HARNESS=\"$WORK/native/bin/sc-hla-harness\" SYNAPSE_HLA_PUBLISHER=\"$WORK/native/bin/sc-hla-publisher\" SYNAPSE_HLA_RTINODE=\"$WORK/openrti/install/bin/rtinode\" \"$WORK/venv/bin/python\" -m pytest -m rti", "exit": 0, "summary": "213 passed, 3186 deselected"}, "selftest_files": ["fixture-replay/capture.jsonl", "fixture-replay/diagnostics.jsonl", "fixture-replay/observations.jsonl", "fixture-replay/run.json", "self-test.json"]}
- installed_wheel: {"fixture_replay_sha256": "d55fd510bf633395192f4ead01cab1753216d870a9219d023a8525138ef05125", "fom_modules_or_archives": [], "imported_from": "lib/python3.12/site-packages/synapse_hla/__init__.py", "install_runtime_lock_exit": 0, "install_wheel_exit": 0, "members": 64, "outside_any_checkout": true, "self_test": {"exit": 0, "result": {"blocked": 0, "blocked_ids": [], "cases": 85, "failed": 0, "failed_ids": [], "passed": 85, "result": "PASS"}}, "self_test_without_fom_dir": {"exit": 4, "result": "BLOCKED"}, "txt_files": ["synapse_hla-1.0.0.dist-info/entry_points.txt", "synapse_hla-1.0.0.dist-info/top_level.txt"], "txt_outside_dist_info": [], "uv_build_exit": 0, "venv_exit": 0, "version": {"exit": 0, "stdout": "{\"name\":\"synapse-hla\",\"version\":\"1.0.0\",\"profile\":\"SC-HLA-RPR2-OBS-1\"}"}, "wheel": "synapse_hla-1.0.0-py3-none-any.whl", "wheel_sha256": "6fc6db0012f2b4e334394c29c21c8beda4f60ff608ef4cc213a32f12c6382eb8"}

## Specification points for the owner

The rulings this run took where the specification is open or contradicts itself (the CR-L06 list and its extensions). The owner may overrule any of them.

- **OPV-03** (CR-L06). R05 asks for packaged FOM modules; the repository's rules refuse the five RPR XML modules and the OpenRTI archive anywhere in the tree. Ruling: Recorded deviation: the modules and the archive are never in the repository or the wheel; the release evidence kit supplies them, SYNAPSE_HLA_FOM_DIR names their directory and every module is checked against pins.json before use. Bound by `tests/test_hla_packaging.py::test_the_package_directory_is_what_the_wheel_carries_and_nothing_else`, `tests/test_hla_cli.py::test_observe_without_its_dependencies_is_exit_4_before_the_run_directory`.
- **NAT-05** (CR-L06). R12's literal evokeMultipleCallbacks(0.0, 0.05) returns at once when nothing is pending and keeps a processor busy. Ruling: The literal parameters are kept; after a call that delivered no callback the worker pauses 5 ms. Changing R12's parameters is the owner's call. Bound by `tests/test_hla_native.py::test_an_idle_worker_does_not_keep_a_processor_busy`.
- **NAT-01** (CR-L06). Through the pinned OpenRTI a subscription at PhysicalEntity reaches only federates that publish PhysicalEntity itself; a publisher at GroundVehicle alone is never discovered, so the demo as written yields no observation. Ruling: The synthetic publisher publishes the four attributes at PhysicalEntity and at GroundVehicle and registers at GroundVehicle; the observer is unchanged. README, installation guide and evidence report state the limitation. Bound by `tests/test_hla_demo.py::test_the_demo_object_is_reported_at_physical_entity_though_registered_at_ground_vehicle`, `tests/test_hla_rti.py::test_an_existing_mode_session_reports_physical_entity_for_a_ground_vehicle`, `tests/test_hla_release.py::test_the_documents_state_the_baseline_limitations`.
- **NAT-02** (CR-L06). On macOS a C++14 OpenRTI client cannot connect (two clocks with different origins inside OpenRTI). Ruling: Linux keeps R43 exactly; on macOS OpenRTI alone is built as C++98 and the worker and publisher stay C++14; macOS results are development evidence only. Bound by `tests/test_hla_native_sources.py::test_the_openrti_wrapper_runs_the_bundles_commands_with_only_the_ruled_additions`.
- **NAT-03, NAV-02** (CR-L06). An orderly RTI exit (rtinode ends, or FIN) gives no connectionLost; OpenRTI removes every known object instead. Ruling: Both are handled: a reset is E_RTI_CONNECT with the 1/2/4 s retry; an orderly close gives one removal per known object and the generation stays open. Last-received values are never claimed to be kept. Bound by `tests/test_hla_rti.py::test_a_tcp_reset_is_connection_lost_then_a_rejoin_under_the_same_name`, `tests/test_hla_rti.py::test_an_orderly_close_is_no_connection_lost_but_one_removal_per_known_object`.
- **OPS-01** (CR-L06). The interoperability field has three spellings in the handoff. Ruling: external_customer_interoperability everywhere (run.json, demo.json, the evidence report), NOT_TESTED unless a witnessed report exists. Bound by `tests/test_hla_cli.py::test_replay_of_the_bundled_capture_writes_four_files_and_exits_0`, `tests/test_hla_release.py::test_the_evidence_report_never_hides_not_tested_or_blocked_behind_a_pass`.
- **OPS-02** (CR-L06). No E_ code is mapped to an exit class; the exit of a COMPLETE capture with a recovered error is undetermined. Ruling: Codes mapped to classes 2 to 6; the exit is the highest class of the terminal failures, else 3 for any E_ diagnostic, else 0; usage errors are a structured E_CONFIG with exit 2. Bound by `tests/test_hla_cli.py::test_every_e_code_has_the_exit_class_ops_02_gives_it`.
- **OPS-04** (CR-L06). The endpoint pattern admits non-canonical hosts. Ruling: Semantic validation: a canonical dotted quad with octets up to 255 and a port 1 to 65535. Bound by `tests/test_hla_config.py::test_the_endpoint_rule_agrees_with_the_standard_library_on_the_address_classes`.
- **OPS-05, NAT-07** (CR-L06). A-UNSUBSCRIBED, A-RETRACT and A-EMPTY cannot be produced through the pinned RTI. Ruling: A test harness drives the worker's own callback code inside an OpenRTI federation of its own process; those cases are bound to its scenarios. Bound by `tests/test_hla_native.py::test_an_unsubscribed_attribute_is_captured_under_its_name_and_rejects_the_reflection`, `tests/test_hla_native.py::test_both_retraction_handle_overloads_are_captured_retractable_and_quarantine`, `tests/test_hla_native.py::test_an_empty_map_is_a_captured_empty_reflection_with_no_state_output`.
- **OPS-21** (CR-L06). The fixed limits are unreachable at their real values in a test. Ruling: A test-only seam lowers one limit while keeping the rest; no option, key or variable reaches a limit; the real values are held to the table. Bound by `tests/test_hla_limits.py::test_a_test_variant_can_lower_one_limit_and_keeps_the_rest`, `tests/test_hla_cli.py::test_no_limit_or_timing_value_is_reachable_from_an_option_a_key_or_a_variable`.
- **RED-09, COD-12** (CR-L06). E_TIME_REGRESSION and E_GEODESY cannot arise from valid data. Ruling: Both are reached through direct calls and crafted inputs and keep their table behaviour. Bound by `tests/test_hla_reducer.py::test_e_time_regression_through_a_direct_reduce_frame_call`, `tests/test_hla_geodesy.py::test_convergence_on_the_last_allowed_step_counts_and_one_fewer_is_e_geodesy`.
- **OPS-27** (CR-L06). requirements.json and the gates carry only the first paragraph of each requirement. Ruling: A paragraph map assigns every continuation paragraph and table to its requirements; a gate is bound only when its tests name every paragraph mapped to it. Bound by `tests/test_hla_trace.py::test_the_paragraph_map_records_ops_27`, `tests/test_hla_trace.py::test_the_tree_satisfies_the_ratchet`.
- **NAT-12** (CR-L06). SPEC:20 says CMake 3.28 or later; CMake 4 refuses OpenRTI's minimum version. Ruling: The handoff's command byte for byte on 3.28 to 3.31; -DCMAKE_POLICY_VERSION_MINIMUM=3.5 only on 4.x, recorded in the build record; 4.x is development use. Bound by `tests/test_hla_native_sources.py::test_the_openrti_wrapper_runs_the_bundles_commands_with_only_the_ruled_additions`.
- **NAT-14** (CR-L06). The handoff's licence note says LGPL-2.1-or-later and points to COPYING files the archive does not have; the archive offers LGPL-2.1, LGPL-3.0 or MPL-2.0. Ruling: The release carries the archive's LICENSE and the three licence texts verbatim and elects LGPL-2.1-or-later, dynamically linked, with the pinned archive shipped alongside; the SBOM records the system expat and zlib. Bound by `tests/test_hla_packaging.py::test_the_openrti_licence_texts_are_the_archives_own_bytes_and_the_election_is_stated`, `tests/test_hla_packaging.py::test_the_sbom_is_what_the_locks_give_and_enumerates_what_r43_names`.
- **CDV-02** (CR-L06). The handoff's geodesy tool prints a fixed PROJ version string whatever ran. Ruling: Evidence records the PROJ version cs2cs states at run time, never a copied string. Bound by `tests/test_hla_rti.py::test_the_product_inverse_agrees_with_proj_forward_on_the_175_point_grid`.
- **CDV-01, COD-08** (CR-L06). The supplied vectors leave whole classes of decoder and geodesy mistakes undetected. Ruling: Hand-derived vectors were added for every slot of every variant, every interpreted offset and non-trivial latitudes and longitudes. Bound by `tests/test_hla_geodesy.py::test_the_cdv01_worked_point_exactly`, `tests/test_hla_codec.py::test_every_slot_of_every_variant_lands_where_the_table_puts_it`.
- **COD-01** (C.5). Rounding of emitted floats is not specified to the bit. Ruling: CPython's round of the binary64 value, ties to even. Bound by `tests/test_hla_projector.py::test_rounding_is_half_even_and_a_rounded_plus_180_is_written_minus_180`.
- **COD-03** (C.5). What the kinematics object holds below the course threshold. Ruling: Kinematics is kept below the 1e-6 m/s threshold with course_deg null, and the ENU step is listed. Bound by `tests/test_hla_geodesy.py::test_the_course_threshold_compares_the_unrounded_speed`, `tests/test_hla_projector.py::test_course_threshold_rounding_and_360`.
- **COD-10** (C.5). Longitude +180 and the ENU basis at the antimeridian. Ruling: A literal +180 is written -180; ENU uses the unwrapped atan2. Bound by `tests/test_hla_geodesy.py::test_longitude_is_atan2_and_plus_180_is_written_minus_180`, `tests/test_hla_projector.py::test_enu_at_plus_180_uses_the_unnormalised_atan2`.
- **COD-13** (C.5). The iteration's converged latitude and its last step. Ruling: The converged latitude is the last next value; convergence on the 32nd step counts; N is recomputed at the final latitude. Bound by `tests/test_hla_geodesy.py::test_convergence_on_the_last_allowed_step_counts_and_one_fewer_is_e_geodesy`.
- **RED-18, COD-15** (C.5). Negative zero in decoded and projected values. Ruling: -0.0 is kept in attributes.hla.spatial and normalised only in position and kinematics. Bound by `tests/test_hla_projector.py::test_negative_zero_is_kept_in_the_provenance_and_normalised_in_position_and_motion`.
- **CR-R3-06** (C.5). The order of suppression reasons. Ruling: Reasons are unique and sorted in code-point order. Bound by `tests/test_hla_projector.py::test_reasons_are_complete_sorted_and_unique`.
- **CR-L09** (C.5). A generation_start whose federation_name differs from the configuration's. Ruling: Refused by verify, the reader and the chain as E_CAPTURE_SCHEMA at line:<n>#/event/federation_name. Bound by `tests/test_hla_capture.py::test_a_generation_of_another_federation_is_refused_by_verify_and_the_reader`.
- **CR-L10** (C.5). What a prefix replay's capture.jsonl holds. Ruling: The whole input file, unverified tail included, with its SHA-256; the summary's verification member says how far verification read. Bound by `tests/test_hla_replay.py::test_a_truncated_capture_is_refused_and_replays_as_a_prefix_on_request`.
- **CR-L11** (C.5). A quarantined token that keeps asserting an identity. Ruling: No diagnostic and no claim (the catalogue is closed); the snapshot shows the quarantine. Bound by `tests/test_hla_reducer.py::test_removal_releases_the_triple_but_never_unquarantines_a_survivor`.
- **CR-L12** (C.5). Which objects generation_end invalidates. Ruling: Every non-removed object with an allocated entity_id, whether or not it ever produced an Entity. Bound by `tests/test_hla_reducer.py::test_generation_end_invalidates_every_identified_object_in_token_number_order`.
- **CR-L13** (C.5). How often a geography error is emitted. Ruling: E_ECEF_RANGE or E_GEODESY on every snapshot that lists GEOGRAPHY_UNPROJECTABLE and no MISSING_ or INVALID_ reason, under time policy none too. Bound by `tests/test_hla_reducer.py::test_e_ecef_range_suppresses_with_its_diagnostic_once_the_state_is_otherwise_complete`.
- **CR-L14** (C.5). A vertical ECEF velocity at longitude +-180 or +-90 gains a horizontal component from roundoff. Ruling: SPEC:146 as written, no clipping threshold (R31 forbids one); a course appears above about 1e10 m/s. Bound by `tests/test_hla_projector.py::test_enu_at_plus_180_uses_the_unnormalised_atan2`.
- **CR-R2-06** (C.2). Bytes after a verified footer. Ruling: E_CAPTURE_SCHEMA, never INCOMPLETE: such a file has no prefix replay (stricter than RED-06's text). Bound by `tests/test_hla_capture.py::test_nothing_may_follow_the_footer`.
- **CR-R4-05** (C.5). Replay of a FAILED capture without allow_prefix. Ruling: Refused as E_CAPTURE_INCOMPLETE at line:<footer>#/status; an INCOMPLETE capture whose header did not verify is refused even with allow_prefix. Bound by `tests/test_hla_replay.py::test_a_failed_capture_is_refused_unless_replayed_as_a_prefix`.
- **RED-V-01, CR-R2-01, CR-R2-10** (C.5). A header configuration that fails a semantic rule. Ruling: The capture is INVALID (verify reports, replay raises); schema faults of the header's config are E_CAPTURE_SCHEMA, semantic faults E_CONFIG; captures recorded before a later tightening of the configuration rules become unreplayable. Bound by `tests/test_hla_capture.py::test_the_headers_configuration_is_validated_in_full`.
- **CR-R2-13** (C.2). A carriage return in a configuration file. Ruling: A raw CR is refused (E_CONFIG with a line path), so a CRLF-saved configuration is refused. Bound by `tests/test_hla_config.py::test_the_file_rules_of_r07`.
- **SPEC:68 key order** (C.5). "Sorted ASCII property names" when a key is not ASCII. Ruling: Python's code-point key order of the named json.dumps call; only header pin keys can be non-ASCII. Bound by `tests/test_hla_canonical.py::test_canonical_bytes_are_the_one_spelling_spec_68_describes`.
- **CR-R2-22** (C.2). The encoding of a FOM module. Ruling: Strict UTF-8, no NUL, an XML declaration naming UTF-8 or none; expat is created with UTF-8 so the codec registry is never consulted. Bound by `tests/test_hla_fom.py::test_no_encoding_name_but_utf_8_is_read_whatever_the_codec_registry_knows`.
- **CR-R4-08** (C.4). R15: the audit time never affects the output; but the hash chain covers the header's record_created_at. Ruling: Held as: identical state, identity, values and diagnostics, observations differing only in source_hash. Bound by `tests/test_hla_replay.py::test_the_audit_time_of_the_header_reaches_the_output_only_through_the_cited_digests`.
- **CR-R4-09** (C.4). Retractable callbacks on unknown or removed tokens. Ruling: Only E_UNKNOWN_OBJECT or W_DUPLICATE_REMOVE (there is no object to quarantine); adding E_RETRACTION_UNSUPPORTED is a possible other reading. Bound by `tests/test_hla_reducer.py::test_retractable_callbacks_for_a_token_that_is_not_an_object_quarantine_nothing`.
- **CR-R5-01** (C.6). The retraction footer: NAT-08's table says FAILED, RED-08 says COMPLETE. Ruling: RED-08 wins: E_RETRACTION_UNSUPPORTED, generation_end retraction, footer COMPLETE with reason_code null, exit 3. Bound by `tests/test_hla_host.py::test_request_retraction_ends_the_generation_and_the_session_complete`, `tests/test_hla_native.py::test_request_retraction_ends_the_generation_with_reason_retraction`.
- **CR-R5-20** (C.6). A worker that cannot be started again in mid-session (RED-01 does not list it). Ruling: A captured generation-0 E_DEPENDENCY_PIN, never retried, footer FAILED E_DEPENDENCY_PIN, exit class 4. Bound by `tests/test_hla_host.py::test_a_worker_that_cannot_be_started_again_is_a_dependency_failure`.
- **CR-R5-21** (C.6). A never-retried failure that competes with a first condition. Ruling: It still ends the session with its own diagnostic frame; generation_end and the footer name the same code. Bound by `tests/test_hla_host.py::test_a_never_retried_failure_that_competes_with_a_lost_connection_ends_the_session`.
- **Terminal code of two pending pipes** (C.12). When a frame and a status record are pending at one poll, which is read first decides the first terminal code. Ruling: Logged as observed behaviour; the test row is deterministic. Bound by `tests/test_hla_host.py::test_a_never_retried_failure_that_competes_with_a_lost_connection_ends_the_session`.
- **CR-R6-01** (C.8). What validate-config's dependency check covers. Ruling: The configuration and the five FOM modules against their pins and the XML scan; the worker is not probed there (observe's pre-flight does); the higher class wins. Bound by `tests/test_hla_cli.py::test_validate_config_with_a_changed_or_absent_fom_module_is_exit_4`.
- **CR-R6-03** (C.8). Exit of verify, inspect and export-capture for a faulty capture. Ruling: 3 for every verdict other than COMPLETE whatever the fault's class (E_LIMIT and E_CONFIG faults included), 6 for an unreadable file; replay keeps its code's class. Bound by `tests/test_hla_cli.py::test_verify_of_any_other_capture_exits_3_with_the_fault_on_stderr`.
- **CR-R6-05** (C.8). An offline command stopped by a signal. Ruling: It stops at its next safe point, removes what it created and exits 130 or 143 with nothing printed; observe stops its session in order once one exists, and a stop during its own configuration and FOM pre-flight exits 130 or 143 like the other commands. Bound by `tests/test_hla_cli.py::test_an_interrupted_command_takes_back_what_it_made`.
- **CR-R6-07** (C.8). What stderr carries. Ruling: Refusals and terminal failures only; diagnostics that are records of the output are in diagnostics.jsonl and the summary, not repeated on stderr. Bound by `tests/test_hla_cli.py::test_a_complete_capture_whose_records_hold_an_e_code_replays_with_exit_3`.
- **CR-R6-F2** (C.8). A host whose parent has gone. Ruling: Treated as an orderly stop request: the session ends in order and run.json is absent, which is the visible mark. Bound by `tests/test_hla_host.py::test_a_parent_that_has_gone_stops_the_session_in_order`, `tests/test_hla_cli.py::test_a_command_killed_from_outside_leaves_a_session_stopped_in_order_without_run_json`.
- **CR-R6F-04** (C.9). SPEC:184 says forced termination cannot produce COMPLETE. Ruling: Read as the command: a command killed from outside leaves a session the host ends in order (COMPLETE when the worker exited by itself) and no run.json; a parent gone before the first worker is FAILED E_RTI_CONNECT. Bound by `tests/test_hla_host.py::test_a_parent_gone_before_the_first_worker_ends_the_session_before_it_starts`.
- **CR-R7-03** (C.11). The worker's parent dies. Ruling: getppid() differing from the recorded parent, checked once per idle pause: resign NO_ACTION, disconnect, drain, exit 72, no report. Bound by `tests/test_hla_native.py::test_a_worker_whose_parent_has_gone_resigns_disconnects_and_exits`.
- **CR-R7-04** (C.11). The worker's diagnostic frames. Ruling: object_token and attribute null, the failure record's text, enqueued when the queue has room, never for E_QUEUE_OVERFLOW. Bound by `tests/test_hla_native.py::test_a_terminal_condition_is_one_failure_record_then_resign_and_disconnect`.
- **CR-R7-05** (C.11). What the worker's queue bound counts. Ruling: One bound of 4096 frames and 16 MiB of copied bytes covers the batch, the queue and the record being written; the refused record is the newest. Bound by `tests/test_hla_native.py::test_a_batch_beyond_the_queue_bound_overflows_keeping_everything_accepted`.
- **CR-R7-06** (C.11). Which code wins when a callback breaks several rules. Ruling: Count, sizes (E_LIMIT), metadata validity (E_CAPTURE_SCHEMA), token budget, queue, in that order. Bound by `tests/test_hla_native.py::test_a_callback_refused_on_a_full_queue_reports_its_own_fault_first`.
- **CR-R7-09** (C.11). A reflection or removal of a handle never discovered. Ruling: It takes the next token, mapped as not active (E_UNKNOWN_OBJECT or W_DUPLICATE_REMOVE downstream); a later discovery is a new object with a new token. Bound by `tests/test_hla_native.py::test_a_handle_keeps_its_token_after_removal_and_a_new_discovery_is_a_new_object`.
- **CR-R7-10** (C.11). RTI exceptions without a code of their own. Ruling: Mapped per service (connect, join, resolve, evoke, request, getAttributeName, resign, disconnect) to E_RTI_CONNECT, E_FEDERATE_NAME, E_FOM_PROFILE or E_CAPTURE_SCHEMA. Bound by `tests/test_hla_native.py::test_each_rti_exception_maps_to_its_code_and_the_worker_ends_in_order`.
- **CR-R7-22** (C.11). When a failing resign or disconnect is reported. Ruling: Immediately after the running record of that stage; the session ends FAILED E_RTI_CONNECT, no retry after a stop. Bound by `tests/test_hla_native.py::test_each_rti_exception_maps_to_its_code_and_the_worker_ends_in_order`.
- **CR-R8-14** (C.12). What the demo accepts from the publisher. Ruling: Twelve event kinds with exactly their members, printable ASCII lines of at most 768 bytes, R38's order; anything else fails the run with a fixed reason. Bound by `tests/test_hla_demo.py::test_publisher_events_out_of_their_order_end_the_run`, `tests/test_hla_demo.py::test_hostile_publisher_events_end_the_run_cleanly_and_never_reach_the_record`.
- **CR-R8-15** (C.12). An rtinode start ended by an exception. Ruling: rtinode is ended by its PID before the exception leaves the start. Bound by `tests/test_hla_demo.py::test_a_stop_while_rtinode_starts_ends_it_by_its_pid_and_its_port_refuses`.
- **CR-R8-16** (C.12). Which class the publisher registered at. Ruling: Read back from the RTI and named by the handle it equals; any class but GroundVehicle fails the run. Bound by `tests/test_hla_demo.py::test_the_demo_object_is_reported_at_physical_entity_though_registered_at_ground_vehicle`.
- **CR-R8-17** (C.12). Draining a child's pipes after it ended. Ruling: One more R14 deadline at most, then closed; a process the child left behind is not the demo's. Bound by `tests/test_hla_demo.py::test_the_end_of_a_child_never_waits_on_a_pipe_another_process_holds`.
- **CR-R8-18** (C.12). The couplings of demo.json. Ruling: Held by demo.schema.json where JSON Schema can express them (now also the seven steps by position) and by code and tests otherwise. Bound by `tests/test_hla_demo.py::test_the_demo_schema_refuses_each_broken_rule`.
- **CR-L17, CR-R8-12** (C.8, C.12, C.14). R42's 1000 reflections per second against R44's per-upsert validation in pure Python. Ruling: Per-upsert CDM validation with format checking stays; with external_elapsed the worker's queue overflowed on a 4-vCPU aarch64 machine in two of three R42-shaped runs and on the development Mac under load; the gate is BLOCKED (no x86_64 run) and at risk. What the live path no longer checks, made concrete: an EntityType whose kind is outside uint8 is refused by the public project_state (the snapshot schema) and projected by the reducer's entry, which the decoder never hands such a value. Bound by `tests/test_hla_rti.py::test_r42_load_on_the_reference_machine_without_loss_within_the_p95_target`, `tests/test_hla_rti.py::test_the_perf_load_shape_runs_under_the_host_without_loss`.
- **CR-L18** (D). R44 names synapse-cdm 3.1.1 as the baseline; the package landed on 3.8.0 (schema 3.2.0). Ruling: Recorded deviation: the dependency is synapse-cdm>=3.8.0,<4; the vendored 3.0.0 Entity schema stays the contract; the installed SDK's schema must be additive over it; the migration is recorded in the README. Bound by `tests/test_hla_projector.py::test_the_cdm_baseline_and_its_complete_entity_schema`, `tests/test_hla_release.py::test_the_cdm_history_and_the_upgrade_rule_are_recorded`.
- **CR-L20** (C.14). Byte identity across platforms: the specification's 1e-6 threshold is the unit of the difference seen between C libraries. Ruling: Pins are per platform: darwin-arm64, recorded where Python 3.11, 3.12 and 3.14 agreed, and linux-aarch64, recorded from one interpreter (Python 3.12.3, reference run ref-1 of 2026-10-25), so identity across interpreters on one platform, what each pin holds, is shown on darwin-arm64 and not observable on linux-aarch64; across platforms 674 of the 10,000 inputs differ in the last place of position_ecef_m (612 coordinate values by 1 ulp, 79 by 2 ulp) and 5 altitudes at 27,451 to 89,704 km differ by 1e-6 m. Bound by `tests/test_hla_geodesy.py::test_ten_thousand_projected_points_are_identical_on_every_interpreter`.
- **CR-new-R9-03** (R9). R05 asks for the source commit in every report; a report cannot name the commit that will contain it, and OPS-10 forbids fabricating one. Ruling: Reports carry source_commit null; the evidence report names the base commit and the SHA-256 of the package's files, which identifies the tree. Bound by `tests/test_hla_release.py::test_the_evidence_report_identifies_its_build_and_lists_every_case`.
- **F-native-03** (C.16). A SIGTERM in the milliseconds between the worker's spawn and the installation of its handler ends it by the signal, before its orderly stop exists (SPEC:277). Ruling: No change: the host never spawns once a stop is requested, and a stop that lands in that window gives E_RTI_CONNECT with a FAILED footer, exit class 5, the outcome OPS-15 rules for a stop before the first join; closing the window needs native work (the spawn's signal mask). Bound by `tests/test_hla_host.py::test_a_stop_before_any_join_is_failed`, `tests/test_hla_native.py::test_sigterm_during_connect_is_honoured_once_connect_returns`.
- **F-native-04** (C.16). On macOS the OpenRTI build record spells its evidence line 'development evidence only (macOS: OpenRTI configured as C++98, NAT-02)', not CR-L04's label DEV-macOS-arm64. Ruling: Kept as CR-R9-06 accepted it; the evidence report labels the native build DEV-macOS-arm64. Bound by `tests/test_hla_native_sources.py::test_the_openrti_wrapper_runs_the_bundles_commands_with_only_the_ruled_additions`.
- **F-release-03** (C.16). The SBOM names the distribution pkg:pypi/synapse-hla@1.0.0 while it is released in the tag's tree and the release archives, not uploaded to the index (D-30). Ruling: Kept: a pkg:pypi package URL names the ecosystem of a Python distribution, not an upload. Bound by `tests/test_hla_packaging.py::test_the_sbom_is_what_the_locks_give_and_enumerates_what_r43_names`.
- **CR-L26** (D.2). OPS-11 refuses a failing worker pre-flight or a missing rtinode before the output directory exists; OPS-18 has the demo without rtinode write DIR/demo.json with status BLOCKED and exit 4. Ruling: OPS-18 governs the demo: a missing or wrong rtinode, worker or publisher after the FOM check gives DIR/demo.json BLOCKED and exit 4 (CR-L16's reading for the publisher applies to all three); OPS-11's 'before the output directory exists' governs validate-config and observe; the FOM pin check precedes the directory for all three commands. Bound by `tests/test_hla_cli.py::test_demo_without_its_dependencies_is_blocked_with_exit_4`, `tests/test_hla_cli.py::test_observe_without_its_dependencies_is_exit_4_before_the_run_directory`.
- **F-trace-03** (C.16). A FOM module given as a symbolic link to the pinned bytes is accepted. Ruling: The bytes decide (OPV-03, OPS-11): the pin is checked over the bytes read through the link. Bound by `tests/test_hla_fom.py::test_a_module_reached_through_a_symlink_is_judged_by_its_bytes`.
- **F-host-05** (C.16). A SIGINT or SIGTERM before the program has installed its handlers (the interpreter's start-up) ends any command by the signal, with nothing started and nothing written. Ruling: No change: before the handlers exist there is nothing of the product to stop; CR-R6-05's exit 130 or 143 applies from their installation on. Bound by `tests/test_hla_cli.py::test_an_interrupted_command_takes_back_what_it_made`.
- **F-host-03** (C.16). The pre-flight 'sc-hla-federate --version' probe runs with the command's stderr: an executable named by SYNAPSE_HLA_WORKER that writes to stderr is heard there. Ruling: Kept as CR-R5-04 rules (the worker's stderr is the host's): a misconfigured SYNAPSE_HLA_WORKER can put lines that are not JSON on stderr beside the E_DEPENDENCY_PIN diagnostic. Bound by `tests/test_hla_host.py::test_the_pre_flight_refuses_before_the_run_directory_exists`, `tests/test_hla_host.py::test_the_worker_gets_its_arguments_environment_and_descriptors`.
