# STANAG 4559 translators: the specification bundle's examples, verbatim

These eighteen files are TEST DATA, copied byte for byte from the `examples/` directory of the
SynapseCommand STANAG 4559 engineering specification bundle, `SynapseCommand_STANAG4559`
(specification SC ISR 4559 001, revision 1.0, 4 October 2026). They are the acceptance oracle of
the three ingest-only translators `stanag4559_catalog`, `stanag4559_stream` and
`stanag4559_workflow`: the bundle's authors wrote the expected Events independently of any
adapter ("No gateway adapter was executed to generate these expected outputs"), so the tests read
them as the expectation and never write them.

- `<family>-<case>.record.json`: nine internal ISR gateway records
  (`urn:synapsecommand:isr:record:1`), three per family: `basic`, `missing-source-time` (no
  source time, so the Event is the gateway's receipt observation) and `unknown-extension` (a
  vendor attribute carrying the wide integer 18446744073709551615 as a string);
- `<family>-<case>.expected-cdm.json`: the Event each record must become, rendered with
  `synapse_cdm.canonical.serialise` under the CDM 3.0.0 the bundle pinned (synapse-cdm 3.1.1) and
  the clock below;

The bundle's `fixture-manifest.json` (per record, the clock `2026-10-04T12:00:02.000Z`, the expected
`object_key`, `record_id` and `event_id`, and `synthetic: true`) is NOT carried here. Its nine
`object_key` values are base64url strings beside a field named `key`, which the repository's secret
scanner (gitleaks, rule `generic-api-key`) flags, and `.gitleaks.toml` admits no allowlist by policy.
Its SHA-256 is recorded below and in each `spec/stanag4559_pin.json` (`carried_here: false`), and its
content is the literals of `tests/stanag4559_support.py`: `BUNDLE_CLOCK`, `BUNDLE_IDENTITY` and
`manifest_entries`, against which the translators' output is held.

Every record is synthetic: the bundle says so ("Nine synthetic internal records and expected CDM
events"), every identifier is a `test-` placeholder and every label is `TEST_ONLY`. They are not
payload fixtures of the package: CONTRIBUTING.md's place rule puts every payload position inside
the Baltic rectangle, and the catalogue and stream records state a footprint at 14 to 15 degrees
east, 50 to 51 degrees north. The packaged fixtures under
`packages/cdm/synapse_cdm/fixtures/stanag4559_*/` are written from these files by
`spec/build_fixtures.py`, with the footprint moved by seven degrees east and seven degrees north
and the semantic digest recomputed; that builder reads this directory and checks every file
against the digests below before it derives anything.

`tests/test_cdm_stanag4559_catalog_adapter.py`, `..._stream_...` and `..._workflow_...` replay
their family's three records, as octets and as parsed objects, under the manifest clock and
compare the rendered Event with the expected file byte for byte (acceptance case CDM-001), and
assert the manifest's identities as literals. The expected files are CDM 3.0.0 documents and this
package writes CDM 3.2.0, which adds one optional Event member (`validity`, null here) and stamps
`schema_version` with its own version (specification section 9: "Repository SCHEMA_VERSION,
initially 3.0.0"); the tests project the Event to the frozen 3.0.0 contract with
`synapse_cdm.projection.dump_for` and state the stamp before they compare, and say so.

SHA-256 of each file, as the bundle's `SHA256SUMS.json` records it (`shasum -a 256` reproduces
each):

| File | SHA-256 |
|---|---|
| `catalog-basic.record.json` | `b2b5447d80c0614ee7add6640146ecfb0eafa954923451ccb50dff95ffcddab0` |
| `catalog-missing-source-time.record.json` | `b99e96366993ab86b1d64dda09439ca0baea51e85e2f7ae7cd62e88d089af173` |
| `catalog-unknown-extension.record.json` | `8070d74de28fac09fcd3685b83a30abb32fe4b1b4b8981e9d00d0b9e2b3301c0` |
| `stream-basic.record.json` | `d3c792b96c936010436fb29011309f7dbf8fa0a377921ac7ffed75355e7e375d` |
| `stream-missing-source-time.record.json` | `6d84c86e368926e39f5d837bc565cc1291ef615916ca34a254bcbf600fcf340d` |
| `stream-unknown-extension.record.json` | `47d4b34080fe725a2b96f4bcfe7b3ad2e562111639dcf3c5be9f2c7b61ad42bf` |
| `workflow-basic.record.json` | `9677432fbd0ba53f95fb55b9f04defff0f45d4fef31e8026d7f6e22ae7dbcd6e` |
| `workflow-missing-source-time.record.json` | `fd77a3b5bec9b64f13e634028551f4905479c73a253055ca04b25a567bbb0d87` |
| `workflow-unknown-extension.record.json` | `1d3f032340563c61cfa972ea36e4b8546350de6bfd74f9cc3ac31eb9cfd80271` |
| `catalog-basic.expected-cdm.json` | `d3352ba1079da45e0f0a0c12a07a982c4d485f6ec76d68f43636d23e6f21d8ef` |
| `catalog-missing-source-time.expected-cdm.json` | `e6d8b0c94f269fc267e131d46b9ff79e030ce7b65717129b934593549071c46d` |
| `catalog-unknown-extension.expected-cdm.json` | `55a7b05754c5b7c432519747e21a2b041c4a56d98dc1c14fce74ce7eca18408b` |
| `stream-basic.expected-cdm.json` | `ae0e9a5830cec5eee910f36d25b02fc67bcb239b53f41996a4b61542ec95775a` |
| `stream-missing-source-time.expected-cdm.json` | `934ea644779d93a4e6e61d163cd91ceaf1e5c8cd05796643cb8ed9e8f35719f7` |
| `stream-unknown-extension.expected-cdm.json` | `18ef258aafc105fd46cd77068565d7767f39c0915643dea22fa636b817a28eeb` |
| `workflow-basic.expected-cdm.json` | `90236528b6e9ca52e1123383b6f50f934a287e7f2c4656e2464169f8260b39d7` |
| `workflow-missing-source-time.expected-cdm.json` | `296bceee6a4f61a1d62281f98f1d5f734833510aeee2adb4131ea5853a3e4e37` |
| `workflow-unknown-extension.expected-cdm.json` | `2e046ef909759e7f91db7abede8cd119435ee9d6cea1857f62b9bb70a6d933d3` |
| `fixture-manifest.json` (not carried, see above) | `3d2a0666e7a396cc01c2059e2f0e309dadb225d33503a9e766a97e6b181a21a2` |

The record contract itself, `contracts/isr-record.schema.json` of the same bundle
(`881f9cbfd8c564a1d4e6b7d820d3b1a27a8bcfdc9676825a10e105d2dc17d621`), ships as package data at
`packages/cdm/synapse_cdm/registry/isr/isr-record.schema.json`. The bundle's `examples/raw/`
markers are not copied: the records reference them by `raw_ref`, and a translator never opens one.
