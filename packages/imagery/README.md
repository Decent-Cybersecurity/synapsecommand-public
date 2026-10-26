# synapse-imagery

The host of the `stanag4545` adapter of `synapse-cdm`: staged ingest of STANAG 4545 (NSIF/NITF)
still-imagery containers under the SC4545-CORE-1 engineering profile, a local asset store, a
policy seam, an isolated worker, previews, original-byte replay, an experimental writer and the
`sc-imagery` command. Version 1.0.0, Apache-2.0, written 2026-10-25.

## What it is

- An ingest transaction: the octets are received into private staging under the 16 MiB cap and
  hashed; a repeat of the deduplication key `(tenant, dataset_namespace, synthetic, sha256,
  profile_revision)` returns the stored result; the adapter's inventory runs in a fresh isolated
  child process; the policy decides on the adapter's own security assessment; the immutable
  original is stored (in quarantine when policy blocks it); the translation runs in the worker with
  a context that carries the asset id and the digest the host computed; the record is committed by
  linking it into place, and only then published.
- Interfaces for storage (`AssetStore`) and policy (`PolicyEngine`, `LabelLattice`), each
  artefact (metadata, original octets, pixels, thumbnails, tiles, text, exports) approved
  independently through in-memory tickets that are checked again at every read and can be revoked.
- A runnable local filesystem store (`LocalAssetStore`): restrictive permissions, generated
  temporary names, atomic links on one filesystem, digest and length checks before every commit,
  quarantine, a retention choice for refused octets, revisions selected explicitly, and crash
  recovery.
- A default policy gate that admits only material the adapter assesses as declared unclassified,
  an extension registry that is empty in this release, a lattice that returns only identical
  labels, and test fakes of the policy, store, worker and lattice interfaces, fenced to synthetic
  material.
- Native windows and previews: the worker decodes windows of the uncompressed NC cell for an
  approved caller, and draws 8-bit PNG previews (at most 1024 pixels on the longer side, linear
  over the significant-bit range, nearest-neighbour, segment-only) as derivatives that carry their
  parent's labels and never replace the analytic samples.
- Original-byte replay: the stored octets relayed unchanged after the policy is asked again and
  their digest and length recomputed, with a receipt naming the wire signature and the content
  that was retained without being interpreted.
- The host result of the engineering kit's `ingest-result.schema.json`, validated with its schema
  and the cross-field rules the schema cannot express, and a presentation record of the
  user-visible imagery detail for a consumer's interface to render.

## What it is not

It is not a codec: only the native uncompressed NC cell decodes, and every compressed or masked
cell is disabled, so no JPEG, JPEG 2000 or other compression is decoded. It is not an HTTP
service, a tile service or a URL signer, and it opens no socket. Its policy code is an interface,
a test fake, a default gate and a lattice interface that refuses every combination it cannot
decide: it is not a classification-policy engine and not a cross-domain guard. Replay is not a
newly authored file and not a translation from the CDM. The writer is experimental and its output
is not independently qualified. It makes no claim of conformance, certification or compatibility
with any named system; the adapter it hosts is a provisional internal profile.

## Install

The host needs `synapse-cdm` 3.10.0 or later (and below 4), the first release that carries the
`stanag4545` adapter, and `jsonschema`. Install `synapse-cdm` from the package index first, then
this distribution from the repository's release tag; it is source in the tag and is not uploaded
to the package index:

```bash
pip install synapse-cdm
pip install "synapse-imagery @ git+https://github.com/Decent-Cybersecurity/synapsecommand-public@v3.10.0#subdirectory=packages/imagery"
```

## The command line

```
sc-imagery inspect INPUT --json OUTPUT [--replace]
sc-imagery ingest INPUT --store STORE --dataset NAME --synthetic true|false [--product-key KEY] [--as-of INSTANT --as-of-basis TEXT]
sc-imagery preview RECORD_ID --image N --store STORE --output OUTPUT.png [--bands B[,B,B]] [--replace]
sc-imagery replay RECORD_ID --store STORE --output OUTPUT.ntf [--replace]
sc-imagery export-nc RECIPE.json --store STORE --output OUTPUT.ntf [--replace]
sc-imagery --version
```

Every command runs as one local principal under the default policy and the isolated worker; a
deployment that needs another policy, store or registry uses the Python API. `--synthetic` has no
default. `--product-key` and `--as-of` with `--as-of-basis` give the context a file without a
usable product identity or date needs. `inspect` prints structural data only, to the output it is
given (`-` is stdout), with a `POLICY_UNRESOLVED` warning when the default policy would not admit
the file; it never prints a label value, title, comment, identifier or coordinate. An RGB preview
needs colour band descriptors in the file or an explicit `--bands` selection, which is recorded.

A path argument that names a URI (any scheme, a drive letter, a `/vsi` path) is refused before
anything is opened; give a local name with a colon as `./name`. Inputs must be regular files. An
existing output is replaced only with `--replace`, and every output is written under a temporary
name beside it and linked into place. Stdout carries only the command's JSON document; stderr
carries fixed lines with identifiers and codes only.

| Exit | Meaning |
|---|---|
| 0 | success (an ingest that committed; an inspect of a file that parses, whatever its policy warning) |
| 2 | command or configuration error: usage, a refused option value, a URI path, an existing output without `--replace`, an output without its directory, a store that is not a store, an unknown record id, missing context (`E_CONTEXT`), a window or band outside the image |
| 3 | malformed input: `E_MAGIC`, `E_DIGITS`, `E_LENGTH`, `E_OVERFLOW`, a field or profile refusal of the container, a source sample outside its lookup table, a malformed recipe |
| 4 | an operation this deployment does not perform: `E_CODEC`, `E_ENCRYPTED`, a pixel cell outside the native one, a writer feature it does not offer |
| 5 | policy denial: `E_POLICY`, an ingest that ended `policy_blocked` |
| 6 | a resource cap, a timeout or a full queue: `E_LIMIT`, `E_TIMEOUT`, `E_BUSY` |
| 7 | I/O or internal failure: `E_IO`, `E_INTEGRITY`, `E_INTERNAL` |
| 130 | interrupted (SIGINT): live children are killed and nothing uncommitted is left |

## The experimental writer

`sc-imagery export-nc` runs SC4545-WRITE-NC8-1, an experimental writer: from one explicit recipe
(`synapse_imagery/contracts/write-nc8-recipe.schema.json`) it writes one new single-image file
with one uncompressed 8-bit raster, one MONO band or three RGB bands of 1 to 2048 pixels a side,
NSIF01.01 by default or NITF02.10 when the recipe asks, every security block U with nothing else,
no extension, and optional corners rounded to the nearest whole arcsecond. A capture time is
required. It refuses NSIF01.00, other bit depths, extra bands, TREs, compression and JPEG tables,
transformations and sensor models, and any classification or caveat but plain U. It parses its
own file back before anything is written and commits the export's provenance (parent, recipe,
output digest, corner rounding, no lossy transformation) before the output exists. Its output is
experimental engineering output and is not independently qualified: a self-parse accepting its
own file is necessary and insufficient.

## Limits

Every job runs in a fresh child process with a scrubbed environment, a private empty directory,
one thread and an audit hook that refuses network, process creation and file access outside the
interpreter and the adapter. Parsing jobs have a 5 s and pixel jobs a 30 s wall-clock deadline;
a job killed at its deadline is retried once in a fresh child and then fails `E_TIMEOUT`. Two
jobs run at a time with 32 waiting, and a full queue answers `E_BUSY` at once. Each of these
limits can be lowered and none raised.

On macOS the worker's 512 MiB address-space cap is not enforced: the kernel refuses `RLIMIT_AS` at that value. Records and inspect output say `memory_enforcement: not_enforced` there; the deadlines, the single-threaded worker and the core caps still apply. On Linux the cap is set with `RLIMIT_AS` and enforced by the kernel.

The deployment's own process ceiling (a container or cgroup limit) and the number of host processes
running at once stay the deployment's to set. The deployment runbook is `docs/runbook.md`.

## Tests

```bash
cd packages/imagery && python -m pytest -q -rs
cd packages/imagery && python -m pytest -q -m linux
cd packages/imagery && python -m pytest -q -m "not linux" --ignore=tests/test_imagery_repo.py
ruff check --config packages/imagery/pyproject.toml packages/imagery
```

The first is the mandatory group; tests that need a Linux kernel carry the `linux` marker, are
deselected there and run with the second. No test is skipped and no test asserts a duration.
