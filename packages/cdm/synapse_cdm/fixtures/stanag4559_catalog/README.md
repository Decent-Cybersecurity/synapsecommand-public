# stanag4559_catalog fixtures

**Every one is synthetic.** The three payloads are the catalog records of the SynapseCommand STANAG
4559 engineering specification bundle (SC ISR 4559 001, revision 1.0, 4 October 2026), which says
of its own examples that they are "Nine synthetic internal records": every identifier is a `test-`
placeholder, every security label is `TEST_ONLY` under the scheme `SYNTHETIC_TEST`, and nothing is
recorded data. The bundle's records are carried verbatim, as test data, under
`tests/stanag4559_bundle/` (with their SHA-256 digests in its README.md); the files here are written
from them by `spec/build_fixtures.py`, and `--check` prints `CURRENT` when the files match it and
writes nothing. Do not edit a fixture by hand.

The bundle's catalogue records state a coverage polygon at 14 to 15 degrees east, 50 to 51 degrees north. CONTRIBUTING.md puts every fixture position inside the Baltic rectangle (56.0 to 58.5 N, 20.0 to 24.5 E), so the polygon is **moved seven degrees east and seven degrees north**, to 21 to 22 E and 57 to 58 N (whole degrees, as in the bundle), and `revision.semantic_sha256` is recomputed by the bundle's rule. Every other value is the bundle's.

Each payload is one internal ISR gateway record, `urn:synapsecommand:isr:record:1`, as JSON (the
harness's loader parses it, so the adapter is handed the parsed object; the octet path is exercised
by the `.isr` files under `malformed/` and by `tests/test_cdm_stanag4559_catalog_adapter.py`, which
translates every payload in both forms). It is this project's internal record contract, not a NATO
wire message.

## The set

| Fixture | What it exercises |
|---|---|
| `basic` | A catalogue product with a Polygon footprint, a source time and an empty graph: `observed_at` is `source_time`, `time_basis` SOURCE, `geometry` the footprint and nothing else (no Entity, no centre point). |
| `missing_source_time` | `source_time` is null: the Event is the gateway's receipt observation, `observed_at` = `captured_at`, `source.observed_at` null and `time_basis` GATEWAY_RECEIPT; `modified_at` is never promoted. |
| `unknown_extension` | **The awkward one.** A vendor graph node carries the attribute `urn:synthetic:vendor:largeCounter` with `source_type` unsignedLong and the value 18446744073709551615 as a string, beyond 2**53-1: it survives verbatim, `lexical` and `value` both, and is never turned into a number. |

`golden/` holds the Event of each payload, written by `harness --update-golden` under the
repository clock and read before it was kept; `tests/test_cdm_stanag4559_catalog_adapter.py` asserts
the fields that matter as literals (event id, record id, object and revision keys, time basis,
`observed_at`, geometry) and replays the bundle's own records against the bundle's own expected
Events byte for byte (acceptance case CDM-001).

`malformed/` holds records the adapter must refuse (the conformance suite's check H and the test
module read it), each breaking one rule. Octets, as `.isr` because a `.json` file is parsed by the
harness's loader before an adapter sees it: a duplicate key, a NaN literal, a lone surrogate
escape, a byte-order mark and nesting one container past the declared `max_depth` (one octet past
the declared `max_input_bytes` is fed in memory by the test module, not shipped as a 16 MiB file).
JSON: an unknown top-level key, a `kind` of another family, a missing `captured_at`, an upper-case
semantic digest, a `size_bytes` that is not an integer, a vertex at latitude 91, an impossible date, a
self-intersecting ring, a graph edge to no node, temporal_start_after_end, and `identity_scope` LOCAL_LIBRARY beside a
foreign origin authority.

`spec/stanag4559_pin.json` cites the specification (not carried), lists the bundle files the set
and the acceptance test derive from with their digests, and records the derivation; the builder
reads its inputs only after checking them against those digests.
