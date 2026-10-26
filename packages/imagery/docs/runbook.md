# synapse-imagery: deployment runbook

Written 2026-10-25 with the host's first version, 1.0.0. This page is what an operator needs to
run the host of the `stanag4545` adapter: what runs, how it is installed, where it keeps what,
the commands and their exit codes, the policy seam, the worker's limits, what happens on a
failure, what replay, previews and the writer do, what is not claimed, and the one claim that is.

## 1. What this runs

Two processes per job. The host process stages the octets, keeps the store and asks the policy;
a fresh worker child, started for every job, is the only process that parses an untrusted octet.
An ingest runs in this order, each step journalled before the next:

1. the octets are copied into private staging under the 16 MiB input cap and hashed (SHA-256);
2. a repeat of the deduplication key returns the stored result and nothing else runs;
3. the worker inventories the staged octets and builds the adapter's security descriptor;
4. the policy decides on that descriptor (no ticket: nothing is released here);
5. the immutable original is stored, in quarantine when the policy refused it;
6. the worker translates the octets with a context naming the asset id and the host's digest;
7. the record is written, committed by linking it into place, and only then published.

Previews, windows, replays and exports read a committed record and need a policy ticket of their
own artefact on that record's descriptor.

## 2. Install and the dependency floor

Python 3.11 to 3.14 on a POSIX system (Linux or macOS: the store uses `fcntl` locks and the worker
`resource` limits). The host depends on `synapse-cdm>=3.10.0,<4` and `jsonschema>=4.0` and on
nothing else. It is source in the repository's release tag and is not uploaded to the package
index; install `synapse-cdm` first, then the host from the tag:

```bash
pip install synapse-cdm
pip install "synapse-imagery @ git+https://github.com/Decent-Cybersecurity/synapsecommand-public@v3.10.0#subdirectory=packages/imagery"
```

## 3. The store

`LocalAssetStore(root)` keeps everything under one directory it marks with
`sc-imagery-store.json`; it refuses a non-empty directory without that marker. Every directory is
0o700 and every file 0o600; every immutable object is 0o400 once linked and is never rewritten.

| Path under the root | What it holds | Mode |
|---|---|---|
| `sc-imagery-store.json`, `lock` | the marker; the store lock (`flock`) | 0o400, 0o600 |
| `staging/<job_id>/` | one live job: its lock, its journal, its temporaries | 0o700 |
| `tenants/<tenant_dir>/originals/<asset_id>` | admitted originals | 0o400 |
| `tenants/<tenant_dir>/quarantine/originals/`, `quarantine/records/` | originals and records the policy blocked | 0o400 |
| `tenants/<tenant_dir>/rejected/originals/`, `rejected/records/` | refused octets (only under a retaining policy) and their records | 0o400 |
| `tenants/<tenant_dir>/records/<record_id>.json`, `published/<record_id>` | committed records; publication markers | 0o400, 0o600 |
| `tenants/<tenant_dir>/assets/`, `descriptors/` | digest and length of each original; the security descriptors stored for it | 0o400 |
| `tenants/<tenant_dir>/dedup/`, `products/` | the deduplication slots; each product's revisions | 0o600 |
| `tenants/<tenant_dir>/derivatives/<derivative_id>.png`, `.json` | previews and their records | 0o400 |
| `tenants/<tenant_dir>/exports/<export_id>.json` | export provenance | 0o400 |
| `tenants/<tenant_dir>/integrity-failed/<asset_id>` | the mark of an original that failed its integrity check | 0o400 |

Every commit and index update holds the store lock, and so do the creation of a staging
directory together with taking its own lock, the last removal of a staging directory, and the
job pass of `recover()`; the lock is never held across a worker run or a policy call. The lock
serialises processes and threads that use the store through its own interface: the store is not
a boundary against its own in-process caller, which can read or write the directory as any code
of that process can, so the host process itself must be trusted.

Back the store up by copying the whole root while no job runs. Never edit it by hand: names are
identifiers, and a changed record breaks its digest and its immutability. Never mount another
filesystem inside the root: commits are links, which are atomic only on one filesystem (a link
across two fails with `E_IO`). The process ceiling (a container or cgroup limit), the disk quota
and the number of host processes running at once are the deployment's to set.

## 4. The five commands

```
sc-imagery inspect INPUT --json OUTPUT [--replace]
sc-imagery ingest INPUT --store STORE --dataset NAME --synthetic true|false [--product-key KEY] [--as-of INSTANT --as-of-basis TEXT]
sc-imagery preview RECORD_ID --image N --store STORE --output OUTPUT.png [--bands B[,B,B]] [--replace]
sc-imagery replay RECORD_ID --store STORE --output OUTPUT.ntf [--replace]
sc-imagery export-nc RECIPE.json --store STORE --output OUTPUT.ntf [--replace]
```

Every command runs as the local principal (tenant `local`, subject `local-operator`) under the
default policy and the isolated worker and, with `--store`, after a recovery pass over the store.
`--synthetic` has no default. The optional `--product-key` and `--as-of` with `--as-of-basis`
supply the context a file without a usable product identity or date needs; without them such a file is refused with
`E_CONTEXT` and nothing is stored. A path that names a URI is refused before anything is opened;
inputs must be regular files; an existing output is replaced only with `--replace`.

| Exit | Outcome |
|---|---|
| 0 | success |
| 2 | command or configuration error, an unknown record id, `E_CONTEXT`, a window or band outside the image |
| 3 | malformed input or recipe |
| 4 | an operation this deployment does not perform (`E_CODEC`, `E_ENCRYPTED`, an unsupported writer feature) |
| 5 | policy denial, or an ingest that ended `policy_blocked` |
| 6 | `E_LIMIT`, `E_TIMEOUT`, `E_BUSY` |
| 7 | `E_IO`, `E_INTEGRITY`, `E_INTERNAL` |
| 130 | interrupted: children killed, temporaries and uncommitted staging removed |

Stderr carries fixed lines only: `sc-imagery: WORKER_MEMORY_NOT_ENFORCED` when the worker could
not apply its memory cap, then `sc-imagery: <command> ok <id>`, `sc-imagery: ingest <state>
<record_id>`, `sc-imagery: <command> <code>`, a usage line, or `sc-imagery: interrupted`. No line
carries a path, a title, a label value, a coordinate or source text.

## 5. Policy

The shipped gate, `DefaultPolicy`, is a floor and not an access-control engine. It reads the
adapter's assessment of the labels and recomputes nothing; it admits an artefact only when all of
these hold, for the file's label and every segment's:

| Field or fact | Admitted when |
|---|---|
| CLAS | exactly `U` |
| CODE, CTLH, REL | blank |
| CLSY | identical across every label (blank or not) |
| DCTP, DCDT, DCXM, DG, DGDT, CLTX, CAPT, CAUT, CRSN, SRDT, CTLN | printable ASCII, any value; security dates are never compared with a clock |
| TRE, DES, RES | none, unless the deployment's extension registry names each one security-neutral (the shipped registry names none) |
| the assessment record | well formed, `declared_unclassified` with no reason, consistent with its own labels |

Anything else is refused, and the material is kept in quarantine. A deployment supplies its own
decisions through the Python API, never through the command line:

```python
from synapse_imagery.assets import LocalAssetStore
from synapse_imagery.ingest import IngestService
from synapse_imagery.policy import Artefact, DefaultPolicy, ExtensionRegistry, PolicyDecision


class NoOriginals:
    """The default floor, except that original octets are never released."""

    policy_id, policy_version = "site-no-originals", "1"

    def __init__(self, registry):
        self._floor = DefaultPolicy(registry)

    def decide(self, request):
        floor = self._floor.decide(request)
        allowed = floor.allowed and request.artefact is not Artefact.ORIGINAL
        reason = floor.reason if allowed or not floor.allowed else "SITE_ORIGINALS_WITHHELD"
        return PolicyDecision(
            allowed, reason, self.policy_id, self.policy_version, floor.completeness
        )


registry = ExtensionRegistry(version="site-2026-10", security_neutral=frozenset())
service = IngestService(
    LocalAssetStore("/srv/imagery/store"), policy=NoOriginals(registry), registry=registry
)
```

A `PolicyEngine` is pure and deterministic and decides each of the seven artefacts (metadata,
original octets, pixels, thumbnails, tiles, text, exports) on its own. `LabelLattice` is the
interface a label combination would go through; the shipped `IdenticalOnlyLattice` returns only
identical labels and refuses everything else. `AssetStore` is the interface a store other than
the local one implements. `FakePolicy`, `MemoryAssetStore`, `InProcessWorker` and
`FakeSchemeLattice` in `synapse_imagery.fakes` are test fakes: they serve synthetic material only,
and a live ingest refuses them. Tickets live in memory, are checked again at every read and are
revoked by ticket, by asset, by subject, or all at once when the engine or registry changes
(`TicketAuthority.advance_epoch`). The repository's boundary page says what this code is: an
interface, a test fake, a default gate and a lattice interface, which is neither a
classification-policy engine nor a cross-domain guard.

## 6. The worker and its limits

| Limit | Default | When it is reached |
|---|---|---|
| parse deadline (inventory, translation, capability) | 5 s, wall clock | the child is killed and the job runs once more in a fresh child; a second expiry is `E_TIMEOUT` |
| codec deadline (window, preview) | 30 s, wall clock | the same; a killed preview leaves no output |
| workers running | 2 | further jobs wait in the queue |
| queue | 32 | the next job is refused `E_BUSY` at once; retry with backoff |
| answer size | 65 MiB | `E_LIMIT` at `/worker` |
| address space | 512 MiB | see below |

`E_TIMEOUT` has had its one supervised retry; do not loop on it. `E_BUSY` is retryable after a
pause. Every limit can be lowered through `WorkerLimits` and none raised. A crashed child is an
`E_INTERNAL` without retry and is replaced by the next job's fresh child.

| Platform | Memory cap | What records and inspect output say |
|---|---|---|
| Linux | `RLIMIT_AS` at 512 MiB, set before the adapter is imported; an allocation past it ends the child with `E_LIMIT` | `memory_enforcement: rlimit_as` |
| macOS | not enforced | `memory_enforcement: not_enforced`, and the command line prints `WORKER_MEMORY_NOT_ENFORCED` |

On macOS the worker's 512 MiB address-space cap is not enforced: the kernel refuses `RLIMIT_AS` at that value. Records and inspect output say `memory_enforcement: not_enforced` there; the deadlines, the single-threaded worker and the core caps still apply. On Linux the cap is set with `RLIMIT_AS` and enforced by the kernel.

A deployment that must have the guarantee constructs `WorkerPool(WorkerLimits(
require_memory_enforcement=True))`, which refuses to start on a platform that cannot give it.

## 7. Failure and recovery

An ingest ends in one of four states: `committed` (published, with CDM object ids), `policy_blocked`
(the original in quarantine, nothing published), `rejected` (the adapter refused the octets; they
are kept only under a retaining policy) or `failed` (an I/O or host failure; nothing published,
one diagnostic). The link of the record is the commit point: before it a failure rolls everything
back, after it the next repeat or `recover()` completes the publication. `recover()` runs at every
command's start and in four passes: dead jobs (rolled back or forward by their journal), record
and index repair with publication, orphan originals and derivative images, and stray
temporaries. A job whose lock is held is live and left alone. An interrupted command leaves no
output, no temporary name and no uncommitted staging behind.

`E_INTEGRITY` on a replay means the stored original no longer matches its recorded digest or
length. The object is marked, kept in place for investigation and never relayed again; restore it
from a backup copy of the store and investigate the storage. A quarantined product is released
only by `IngestService.reassess` under a policy or registry that now admits it, which commits a new
record naming the quarantined one; nothing in quarantine is ever relayed or previewed.

## 8. Replay, preview and the writer

Replay relays the stored original octets exactly, after the policy is asked again for the
original and the digest and length are recomputed; it never edits a label, a pixel or a field,
and any requested change is refused. It is not a newly authored file, not a translation from the
CDM and not proof that an unrecognised extension was interpreted: the receipt names the wire
signature and every retained feature that was not interpreted.

A preview is an 8-bit PNG derivative of one image segment, at most 1024 pixels on its longer
side, linear over the significant-bit range with nearest-neighbour sampling, never composed with
graphics (`segment_only`). It carries its parent's descriptor, is read only with a thumbnail
ticket, and never replaces the analytic samples, which only a window decode returns.

The SC4545-WRITE-NC8-1 writer (`export-nc`) is experimental. It writes one new single-image
uncompressed 8-bit file from one explicit recipe, parses it back before anything is written, and
commits its provenance before the output exists; every export record states its qualification as
"experimental engineering output: not independently parsed, not checked clause by clause against a normative profile; a self-parse accepting its own file is necessary and insufficient".

## 9. What is not claimed

No codec: only the native uncompressed NC cell decodes, and every compressed or masked cell is
disabled. No HTTP service, tile service or URL signer: the host opens no socket. The policy code
is not a classification-policy engine and not a cross-domain guard. The writer's output is not
independently qualified. No certification or accreditation of any kind is held or implied, and
no compatibility with a named system is stated.

## 10. The permitted claim text

> Implements the SC4545-CORE-1 NSIF/NITF imagery ingestion profile, with byte-preserving metadata inventory, specified NC sample decoding and direct geographic footprints.
