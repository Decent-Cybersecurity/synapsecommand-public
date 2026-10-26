# SC4545-CORE-1 STANAG 4545 imagery adapter: implementation record

Written 2026-10-25, before the landing of the `stanag4545` adapter and the `synapse-imagery`
distribution, as the in-tree record of the SynapseCommand STANAG 4545 engineering kit
SC-4545-ENG-1.0. It carries what the kit's requirements REQ-094 and REQ-100 ask a delivery to hand
over: every requirement with its disposition and evidence (the table is
`docs/stanag4545-acceptance.csv`), the maintainer's and the lead's rulings by id, the deviations
from the kit's specification, the evidence behind each disposition, the residual and security
mapping, the handoff list, the one permitted claim and what is not claimed, and the open items.

Conventions. `pkg/` is `packages/cdm/synapse_cdm/`. "The specification" is the kit's
`specification.txt` (REQ-001 to REQ-100); the kit itself is not in this repository except its 17
synthetic vectors and its generator logic. `C`, `G`, `A`, `RB`, `FZ`, `BM` and `EV` are the core
test modules `tests/test_cdm_nsif_codec.py`, `tests/test_cdm_nsif_geometry.py`,
`tests/test_cdm_stanag4545_adapter.py`, `tests/test_cdm_nsif_robustness.py`,
`tests/test_cdm_nsif_fuzz.py`, `tests/test_cdm_nsif_benchmark.py` and
`tests/test_cdm_stanag4545_evidence.py`; the host's tests are
`packages/imagery/tests/test_imagery_<topic>.py`. Commands are written as they run from the
repository root with the repository's own interpreter. No duration measured anywhere is quoted
here: the specification's performance figures are targets for a reference machine, and a time
taken on another machine is not evidence of them.

## 1. Scope

The landing adds the ingest-only adapter `stanag4545` 1.0.0 to `synapse-cdm` (`pkg/adapters/stanag4545.py`
with its container parser `pkg/adapters/nsif_codec.py` and its footprint module
`pkg/adapters/nsif_geometry.py`, and the packaged vectors, twins and goldens under
`pkg/fixtures/stanag4545/`), and the sibling distribution `synapse-imagery` 1.0.0
(`packages/imagery/`, import `synapse_imagery`, command `sc-imagery`) that holds the host half:
policy, asset store, ingest transaction, isolated worker, preview, replay, the experimental writer,
the command line and the presentation record. The wire grammar is the engineering profile
SC4545-CORE-1, declared with the `provisional-internal-profile` binding, claim PROVISIONAL and
maturity L3, because no standards text is held here. The kit is SC-4545-ENG-1.0; its
`SHA256SUMS` gives `specification.txt` the digest
`ae4d912fcc2cd4164dd9e03832501e64c10f660514612ada80d7d8eba697369a`, cited here and not carried.

## 2. Rulings

The maintainer's rulings (U) govern the lead's (L), which govern the run's decisions and those
accepted from its rounds. All are of 2026-10-04 to 2026-10-25.

**The maintainer.**
- **U-01** The kit's design is carried as written in the sibling distribution: the policy
  interface, the test fake, the default gate that admits only clean unclassified material, and a
  lattice interface that refuses undecidable label combinations; one sentence of
  `docs/docs/sc-oes/boundary.mdx` names it.
- **U-02** The manifest declares PROVISIONAL with the provisional-internal-profile binding.
- **U-03** The kit's 17 synthetic vectors and its generator logic are contributed under Apache-2.0
  and tracked byte-identical.
- **U-04** Linux runs inside an existing local VM, with no network and nothing mounted; timings
  there or on the build machine are never benchmark evidence.
- **U-05** Builders and reviewers are separate sessions; no session but the lead commits.
- **U-06** The standing refused-name rule for the public tree.
- **U-07** The arc is delivered unattended through the release; the lead decides open points and
  records them.

**The lead.**
- **L-01** Done means every requirement ends with code, tests and evidence or an explicit
  `not_claimed`, `gate_open` or `maintainer_action` disposition; REQ-097 stays open by design;
  the writer stays experimental; the only claim wording is REQ-100's sentence.
- **L-02** The arc's ordinal and release number are re-read from `main` before every push.
- **L-03** Every compressed and masked cell is disabled; no codec and no GDAL dependency ships;
  GDAL is a test-time reader of samples and corners only.
- **L-04** Build rounds type no version beyond what the bump gate needs; the release round
  releases.
- **L-05** No CI workflow is added for `packages/imagery`, and it is not uploaded to the package
  index in this release.
- **L-06** Core imports the standard library and what `synapse_cdm` already imports.
- **L-07** Six build rounds, each built, reviewed and fixed until it passes review, then the
  release and a witness round.

**The run's own decisions** fixed the round map, the per-round allowed paths, the three parser
fuzz seams (`nsif_codec.read_layout`, `nsif_codec.extension_area`, `nsif_codec.image_subheader`),
the Linux memory-cap contingency, three moves of the arc onto a new `main` while other work
released, and the push ordering with other sessions. **Decisions accepted from rounds** are
filed with each round's review and are not repeated in this record; the ones that change a
ruled shape are the deviations of section 5. The contract-pass rulings that the rounds implement
are filed by area: errors and grammar, pixels and geometry, CDM mapping, the host, and repository
integration with the evidence strategy.

## 3. What landed

- **Core adapter.** `pkg/adapters/stanag4545.py` (the class, the context, the mapping, the security
  labels and assessment), `pkg/adapters/nsif_codec.py` (cursor, error model, limits, header,
  directory, walk, extension areas, TREs, overflow, five subheaders, inventory, window decoder),
  `pkg/adapters/nsif_geometry.py` (footprints from G and D corners).
- **Packaged fixtures.** `pkg/fixtures/stanag4545/`: the 11 translatable kit vectors with twins
  and goldens, `malformed/` (the kit's five negatives), `context/` (header_only and its goldens),
  `vectors/` (47 native vectors), `independent/` (58 recorded GDAL readings and their record),
  `spec/build_fixtures.py` (the builder), README and the `PROVENANCE.json` records.
- **Gates.** `gates/nsif_gdal_reading.py` (the GDAL recorder), `gates/nsif_fuzz.py` (the fuzz
  gate), `gates/nsif_benchmark.py` (the benchmark).
- **Host distribution.** `packages/imagery/`: `policy.py`, `assets.py`, `ingest.py`, `worker.py`,
  `preview.py`, `presentation.py`, `export.py`, `cli.py`, `result.py`, `fakes.py`, the two contract
  schemas, `docs/runbook.md`, LICENSE and NOTICE, and its tests.
- **Records.** This file, `docs/stanag4545-acceptance.csv`, `docs/stanag4545-corpus.json` and
  `manifests/stanag4545.json`; the shared files the registration edits (counts, coverage,
  changelog, support matrix) carry dated notes.

**Work order (REQ-093).** The rounds ran in this order: R0 the parser (bounded cursor, directories,
subheaders, extension inventory, security preservation); R1 the native NC window decoder and the
direct-corner geometry; R2 the CDM mapping, identity, packaging and registration; R3 the host:
policy, store, ingest and the isolated worker process that runs inventory, translation and the
native decode; R4 the disabled codec matrix's operations, preview, replay, the writer, the command
line and the presentation record; R5 the fuzz suite and the evidence. The one difference from the
requirement's sequence: the fuzz suite was written after the worker interface and the writer,
which depend on nothing it provides. No native worker or codec entered core in any round; the
isolated worker lives in `packages/imagery` from its first round.

## 4. Dispositions

`docs/stanag4545-acceptance.csv` holds the kit's header and one row per requirement, REQ-001 to
REQ-100, each with its subject in this repository's words, its status, the implementation paths,
the test ids and the evidence. Its `reviewer` cells are empty: no session signs off, and the
maintainer's review of record is the signed-off commit.

| Status | Rows |
|---|---:|
| `implemented` | 80 |
| `not_claimed` | 8 |
| `maintainer_action` | 8 |
| `gate_open` | 4 |

The rows that are not `implemented`, each with the reason its evidence cell states in full:

| Row | Status | Reason |
|---|---|---|
| REQ-005 | `not_claimed` | unrestricted full-standard rendering is a separate release scope, not offered; every preview is segment-only |
| REQ-008 | `maintainer_action` | closed by the release and witness rounds |
| REQ-032 | `not_claimed` | no TRE semantic plugin and no plugin registry for one; core interprets no payload |
| REQ-036 | `not_claimed` | no compositor ships; the future composer's depth cap has no subject |
| REQ-039 | `not_claimed` | the optional GMTI bridge is not offered; SICD, SIDD, point clouds and GMTI stay opaque |
| REQ-046 | `gate_open` | no pinned, packaged GDAL build with packaged JPEG or JPEG 2000 codecs is held here |
| REQ-047 | `not_claimed` | the codec matrix exists with every cell disabled; compressed and masked decoding are not offered |
| REQ-048 | `not_claimed` | no masked cell is enabled; legacy families are preservation-only |
| REQ-055 | `not_claimed` | no coordinate-system plugin and no RPC plugin exist |
| REQ-075 | `gate_open` | independent writer qualification and Edition 2 profile validation remain release gates |
| REQ-084 | `not_claimed` | no compressed cell is enabled, so the compressed equality rules have no subject |
| REQ-085 | `maintainer_action` | the nightly bounded job and the 24-hour campaign are the maintainer's to schedule |
| REQ-087 | `maintainer_action` | the reference machine is the maintainer's |
| REQ-088 | `maintainer_action` | the timing targets are judged on the reference machine |
| REQ-090 | `maintainer_action` | closed by the release and witness rounds |
| REQ-091 | `maintainer_action` | closed by the release and witness rounds |
| REQ-096 | `gate_open` | the writer gate needs independent NSIF01.01 parsing and a normative profile check |
| REQ-097 | `gate_open` | open by design until the eight items of section 10 are acquired and checked |
| REQ-098 | `maintainer_action` | no normative standard is pinned, so the discrepancy procedure has no subject yet |
| REQ-100 | `maintainer_action` | reference-machine measurements and the 24-hour campaign; no native codec build, so no SBOM for one |

### The core release gate (REQ-094)

Each item of REQ-094, with its evidence:

1. **Every applicable requirement dispositioned**: the acceptance table, held by
   `EV::test_every_disposition_is_the_literal_one` (a disposition changes only by a deliberate
   edit of the test's literal table).
2. **No untriaged parser or security defect**: every defect a review or the fuzz run found is
   listed with its fix in section 10; none is open.
3. **Fixture generation reproducible**: `spec/build_fixtures.py --check` reads CURRENT and the
   builder test reproduces every packaged payload and the kit's 17 digests.
4. **Positive and negative assertions complete**: REQ-079 and REQ-080 are `implemented`; their
   case map is in section 6.
5. **Installed-wheel harness pass**: the wheel gate's `harness` check (section 6).
6. **Byte-retention pass**: `RB::test_invariant_4_exact_byte_retention` and the `MAPPINGS` ledger
   (`A::test_the_ledger_binds_both_twin_leaves`).
7. **Policy-denial pass**: the host's policy and security tests
   (`packages/imagery/tests/test_imagery_policy.py`, `test_imagery_security.py`).
8. **No forbidden imports**: `tests/test_cdm_boundary.py`, `tests/test_cdm_no_network.py` and
   `RB::test_invariant_10_no_network_or_file_access_from_core_imports_or_parser`.
9. **Bounded-output pass**: the object and serialised-output caps
   (`A::test_the_object_bound_admits_sixty_five_and_refuses_one_more_by_injection`,
   `A::test_the_serialised_output_bound_admits_its_size_and_refuses_one_less`).
10. **Documented limitations**: the nine limitations of `manifests/stanag4545.json` and this record.

## 5. Deviations from the specification

- **REQ-006, REQ-090 (test module names).** The kit's `tests/test_nsif_codec.py` and
  `tests/test_nsif_geometry.py` take this repository's prefix: `tests/test_cdm_nsif_codec.py` and
  `tests/test_cdm_nsif_geometry.py`, because the repository's sweeps read `tests/test_cdm_*.py`.
  REQ-090's first command is therefore run with those names (section 11).
- **REQ-008 (numbers).** The specification was written when the CDM schema and adapter API were
  3.0.0; here they are 3.2.0 and 3.1.0 before this arc and stay unmoved by it. The package takes
  the next free minor release that the bump gate derives at the landing.
- **REQ-092 (counts).** The specification counts against a snapshot of the repository that is no
  longer current; every count moved is this repository's own at the landing, derived by its sweeps.
- **The binding.** The wire grammar is declared as a provisional internal profile, not a standard
  encoding, because no standards text is held (U-02).
- **REQ-010.** `decode_nc_window` also takes a keyword-only `storage` flag that returns the
  storage integers for the differential tests; the specified call is unchanged.
- **REQ-019.** A descriptive field that is not printable ASCII is written with `text: null`,
  `encoding_status: uninterpreted` and its `{offset, length}` slice into the octets `wire_b64`
  holds, not with an inline base64 copy, so the source octets appear once (REQ-062, REQ-086).
- **REQ-073.** The specification's list of the writer's inputs calls the true capture time
  optional, and the writer requires it (its recipe schema lists it as required): the
  requirement's own sentence makes an unknown capture time an error for this writer.
- **Derivatives.** A preview's recipe and provenance name the image index, and the store protocol
  gains a listing of a parent's derivatives by id; both are needed to tell a render of one image
  from a render of another and to present them.
- **Kit files.** Apart from its 17 vectors and generator logic, no kit file is tracked, with one
  exception the host requires: `packages/imagery/synapse_imagery/contracts/ingest-result.schema.json`
  is the kit's result contract byte for byte, because the host validates every result against it.

## 6. Evidence

### Corpus manifest

`docs/stanag4545-corpus.json` lists every `.ntf` packaged under `pkg/fixtures/stanag4545/` (the
17 kit vectors and the 47 native vectors) with its origin, authority, redistribution, SHA-256,
size, expected outcome and independent oracles, and four sample classes that are not held: the NGA
NTB test files, the JITC compliance files, official NSIF 01.01 samples and customer samples, which
stay outside this repository unless publication is authorised. `EV` holds every entry to the
packaged octets and to what `parse_container` and `validate_source` answer.

### Differential reading

GDAL 3.13.3 read the storage integers of the 11 image-bearing kit vectors and the 47 native
vectors once, recorded under `pkg/fixtures/stanag4545/independent/` by `gates/nsif_gdal_reading.py`;
`C::test_the_decoder_agrees_with_gdals_recorded_reading` compares the decoder with every reading
without GDAL. The same readings corroborate corner order, axis order and winding on five
axis-aligned rectangles, and six seam-split footprints are compared with GDAL's antimeridian split
as vertex sets and areas. This is independent sample agreement on synthetic NC vectors with
unchanged NSIF01.01, NSIF01.00 and NITF02.10 signatures, from an unpinned GDAL build; it is not a
header, label or NSIF conformance verification.

### Fuzz summary

`python gates/nsif_fuzz.py --mutations 100000 --out <file>` ran the schedule `nsif-fuzz/1` on
CPython 3.12 and 3.11, in child batches of 1,000 inputs; the two reports are equal except for the
interpreter and platform fields:

| Target | Seeds | Mutations | Accepted | Refused | Crash | Hang | Outcome digest |
|---|---:|---:|---:|---:|---:|---:|---|
| `cursor` | 64 | 100000 | 17055 | 82945 | 0 | 0 | `0dadefc2bf089c0195b2db832bd1ae9a399ef85f9446db441218eee2a495d0b9` |
| `extensions` | 7 | 100000 | 4636 | 95364 | 0 | 0 | `d8b9243de8e5956195090c644ecf5d01eb6ad2ff867a0d9ec212d6e4d5b44699` |
| `image_subheader` | 51 | 100000 | 14609 | 85391 | 0 | 0 | `d6c0d6ebaf350230ea3a80725e373a1db1edca2e65cd58eeb15019a9438314b3` |
| `geometry` | 125 | 100000 | 100000 | 0 | 0 | 0 | `3610a2bd871eae278555d019801d39ca9c64143db345893a8fdc0ea021f9f28f` |
| `window_index` | 911 | 100000 | 57094 | 42906 | 0 | 0 | `b8b91bd15880778bc95e79fe257e19e01067acd98f3592ec77d48a08f023a92b` |

0 crashes, 0 hangs; no regression fixture was produced. Every refusal carried a code and a stage
of the error model (the `geometry` target is total and never refuses). These runs are an
engineering gate, not evidence that no malformed file can do harm; the nightly bounded job and the
24-hour campaign of REQ-085 remain the maintainer's (section 10).

### Invariants

`RB` holds one test per REQ-086 invariant, `RB::test_invariant_1_no_read_outside_input` to
`RB::test_invariant_12_no_core_module_evaluates_its_input`, over the 17 kit vectors, the 47 native
vectors and every proper prefix of `mono_nsif101.ntf`. The tenth runs a child interpreter with an
audit hook installed after `synapse_cdm` and the standard library are imported; the three adapter
imports open only module files under the package for reading, and parsing, decoding and
translating every kit vector a second time opens, connects, spawns and changes nothing. The fuzz
gate's own text is held by `FZ::test_the_gate_never_evaluates_what_it_generates`.

### Performance

`gates/nsif_benchmark.py` measures the three workloads of REQ-087 and REQ-088 after one warm-up
and ten runs: the inventory of a 16,777,216-octet container (the input cap), its translation with
canonical serialisation, and the decode of a whole 1024 by 1024 mono 16-bit window. Its verdict
reads no timing: it is PASS when each workload's output equals what it must and the cap holds
(16,777,216 octets parsed, 16,777,217 refused `E_LIMIT` at `/input`). The run on the build machine
(macOS on arm64, not the reference machine) gave PASS; its figures are indicative and are not
kept in the repository.

### Linux runs

On the staged tree, inside a local Linux VM with no network and nothing mounted from the host, the runs gave:
the core modules (`C`, `G`, `A`, `RB`) 1183 passed on linux/arm64 and 1183 passed on linux/amd64;
the host's Linux-only group (the memory cap, the preview under the cap and the installed wheel) 5
passed on arm64 and 5 passed on amd64; the host's platform-neutral group 823 passed on arm64. The
512 MiB worker cap is enforced on Linux and reported as not enforced on macOS. Timings in the VM
are not evidence.

### Installed wheel and conformance

Each round's check built a wheel offline from the staged index, installed it into a scratch
environment and ran `synapse conformance run --adapter stanag4545 --require A,B,C,D,F,G,H,J,K,L,O`
from it; on the tree of this record that read `RESULT: CONFORMANT`, and the harness replayed the
adapter's 22 top-level fixtures with 22 passed and 0 failed. The wheel gate
`python gates/wheel_install.py` last ran on the arc's tree after its last move onto `main`, the
tree of this record: `13 checks, 0 failed`; its `resources` check read 824 fixture files and its
`harness` check 1574 fixture verdicts, 0 failed. The release round runs it again on the landing
tree.

### Retained kit evidence

The kit's SarPy record is retained by citation and not tracked. SarPy commit
`fdcff94e8582fecd680f0b69471f3dc0b4384011`; the kit file `oracle-results.json`, SHA-256
`0557c7c6970058f0aa3cea3555607a4ee1b75e38d6bf3104371f1daaa1fff9e9` in the kit's `SHA256SUMS`.
Method: synthetic fixture integrity and an optional SarPy comparison in which signature surrogates
do not prove NSIF support. The unchanged reader rejected the NSIF 01.01 and NSIF 01.00 vectors
("rejected: Not a NITF file") and accepted the NITF 02.10 vector. The retained failure, quoted
exactly: "not_verified: IMODE is `R` and the image is compressed at image segment index 0". This
is surrogate layout evidence, never NSIF acceptance. The kit's expected outcomes and samples enter
this repository only as test literals and as the corpus manifest's `expected` fields.

### REQ-079 and REQ-080 case map

Positive cases (REQ-079): zero and nonzero extension lengths
(`C::test_every_area_follows_the_same_length_rule`); NBANDS 9 and XBANDS 10 and 256
(`C::test_band_counts`, the `native_nbands9_*`, `native_xbands10_*`, `native_xbands256_*` vectors);
comments 0 and 9 (`C::test_comments_zero_and_nine`); one and several images
(`RB::test_more_than_one_image_translates_with_its_own_footprint_and_count`); every non-image
segment (`C::test_des_and_res_are_parsed_in_order_and_their_payloads_are_opaque`,
`C::test_a_graphic_segment_is_parsed_in_order_and_its_data_is_a_slice`,
`C::test_a_text_segment_is_kept_with_its_format_and_its_payload_unread`); local and overflow TREs
(`C::test_continuation_tres_follow_the_local_ones`); duplicate tags and unknown extensions
(`C::test_the_kits_duplicate_unknown_tres_are_two_ordered_records`,
`C::test_familiar_tags_parse_exactly_like_unknown_ones`); empty TRE data
(`C::test_tags_keep_their_six_octets_and_empty_data_is_allowed`); large raw payload retention
(`RB::test_a_payload_at_the_input_cap_is_retained_exactly`); context fallback
(`A::test_an_unknown_fdt_falls_back_to_as_of_with_its_basis_recorded`); source-tuple revisions
(`packages/imagery/tests/test_imagery_ingest.py::test_another_digest_of_the_same_product_is_a_new_revision`);
signed pixels and both justifications (`C::test_every_interpretation_vector_gives_its_literal_values`);
edge fill (`C::test_edge_fill_is_counted_in_li_and_never_exposed`); the four interleave modes on
grids of at least two by two blocks (`C::test_the_literal_vector_decodes_in_every_mode`,
`C::test_the_edge_and_band_vectors_decode_to_their_stated_content`); zero NPPBH and NPPBV
(`C::test_zero_and_oversized_block_sizes_decode_to_the_stated_content`); the three-table LUT
(`C::test_a_lut_is_metadata_and_the_window_returns_its_indexes`,
`packages/imagery/tests/test_imagery_preview.py::test_the_lookup_table_case_draws_the_three_tables`);
direct D coordinates (`G::test_d_corners_on_the_meridian_and_negative_zero`); valid and unresolved
dates (`C::test_the_one_date_classifier`).

Negative cases (REQ-080), each asserting code and stage: every byte-boundary truncation of
`mono_nsif101.ntf`, with the offset and path of the field each cut lands in
(`RB::test_every_truncation_of_mono_nsif101_is_refused_at_the_field_it_cuts`); decimals with signs,
spaces and other digits (`C::test_decimal_accepts_only_ascii_digits_and_never_strips`); FL, HL and
table-length arithmetic, unknown signature and invalid ENCRYP
(`C::test_every_prefix_rule_refuses_with_its_code_at_its_field`, `C::test_the_directory_rules`);
nonzero NUMX (`C::test_the_directory_rules`); overflowing band and LUT counts
(`C::test_the_band_cap_on_the_wire`, `C::test_the_lut_cap_by_injection`); ABPP above NBPP and a zero
grid count (`C::test_every_image_relation_refuses_at_its_field`); unsupported pixel widths
(`C::test_every_cell_outside_the_native_profile_is_kept_and_refused`); IGEOLO, COMRAT and XBANDS
present or absent against their conditions (`C::test_blank_icords_reads_no_igeolo`,
`C::test_comrat_is_present_exactly_when_ic_is_not_nc_or_nm`, `C::test_band_counts`); dangling,
mismatched and reused overflow (`C::test_every_overflow_association_fault_is_refused`,
`C::test_a_des_named_by_two_areas_is_refused_at_the_later_area`); malformed TRE lengths
(`C::test_tre_framing_refusals`); illegal twin depth
(`C::test_decode_twin_admits_depth_four_shapes_and_refuses_five`); invalid dates
(`C::test_an_impossible_date_is_fatal_in_every_date_field`); invalid corner minutes and
hemispheres (`G::test_every_corner_fault_names_its_corner_and_part`); attachment cycles
(`C::test_composition_faults_leave_the_container_valid`); unsupported encoder requests
(`packages/imagery/tests/test_imagery_export.py::test_a_request_for_what_the_writer_does_not_do_is_unsupported`).

### Evidence record

`python -m synapse_cdm.evidence generate --adapter stanag4545 --out <directory>` writes the
adapter's evidence record (package commit, adapter version, profile, executed fixture hashes,
every failure and skip, resource tests and the preservation ledger), and
`python -m synapse_cdm.evidence verify <directory>/stanag4545/1.0.0/evidence.json` reproduces it.
The record is not tracked (`evidence/` is ignored); the published one is the record the release
pipeline attaches to the GitHub Release of the version that first carries the adapter. Generated on
the tree of this record just before this sentence was added, the record's SHA-256 was
`24edee609963b996d13a1e829c1ff307c429cc91c324a9e23a3482d5bf5f5425`, `verify` printed
REPRODUCED, and its evidence categories read `internal_fixture` PRESENT, `self_round_trip`
NOT_APPLICABLE, and `independent_expected`, `normative_schema` and `independent_endpoint` ABSENT.

## 7. Residual and security mapping

Every source security block (the file's, and one per image, graphic, text, DES and RES segment)
becomes one label record `{scope, index, offset, length, fields, uninterpreted}`; `fields` holds
the sixteen fields below, each the field's text with trailing spaces trimmed, or `null` (and its
name in `uninterpreted`) when it is not printable ASCII. No label is combined, compared by level or
copied as raw octets; each field's octets are recoverable from the label's `offset`.

| Field | Width | Offset in the block | On the product | On each footprint |
|---|---:|---:|---|---|
| CLAS | 1 | 0 | `residual.data.stanag4545.security.labels[k].fields.CLAS` | `residual.data.stanag4545.security.labels[0..1].fields.CLAS` |
| CLSY | 2 | 1 | same path, `CLSY` | same path, `CLSY` |
| CODE | 11 | 3 | same path, `CODE` | same path, `CODE` |
| CTLH | 2 | 14 | same path, `CTLH` | same path, `CTLH` |
| REL | 20 | 16 | same path, `REL` | same path, `REL` |
| DCTP | 2 | 36 | same path, `DCTP` | same path, `DCTP` |
| DCDT | 8 | 38 | same path, `DCDT` | same path, `DCDT` |
| DCXM | 4 | 46 | same path, `DCXM` | same path, `DCXM` |
| DG | 1 | 50 | same path, `DG` | same path, `DG` |
| DGDT | 8 | 51 | same path, `DGDT` | same path, `DGDT` |
| CLTX | 43 | 59 | same path, `CLTX` | same path, `CLTX` |
| CAPT | 1 | 102 | same path, `CAPT` | same path, `CAPT` |
| CAUT | 40 | 103 | same path, `CAUT` | same path, `CAUT` |
| CRSN | 1 | 143 | same path, `CRSN` | same path, `CRSN` |
| SRDT | 8 | 144 | same path, `SRDT` | same path, `SRDT` |
| CTLN | 15 | 152 | same path, `CTLN` | same path, `CTLN` |

The product carries every label; each footprint carries the file label and its own image's label
(`labels[0]` and `labels[1]`, named by `label_scope`) and the product-wide assessment, so a
detached footprint is as restricted as its product.

| Residual path | What it holds |
|---|---|
| product `residual.namespace` | `NSIF/NITF imagery` |
| product `residual.data.stanag4545.wire_b64` | the whole input, once, as canonical base64 |
| product `….file_header` | `offset`, `length`, `fields` (every header field as `{offset, length, text}`), `directory`, `security` |
| product `….segments[i]` | `kind`, `index`, `ordinal`, `subheader` and `data` slices, `fields`, `comments`, `bands` (LUTs as slices), `security` |
| product `….extensions[k]` | each TRE in logical order: area, scope, segment index, ordinal, origin, overflow DES index, tag, offset, length, data slice |
| product `….security` | `labels` (above) and `assessment` (status, reasons, scopes, CLAS values, uniformity, unknown extension counts) |
| product `….parse_profile` | profile, revision, adapter version, capabilities, TRE plugins (none) |
| product `attributes.stanag4545` | profile, wire signature, product key, product time, asset reference, one record per image, security status, diagnostics |
| footprint `residual.data.stanag4545.presentation` | the coverage-overlay role and its type label |
| footprint `….product` | product entity id, product key, profile, system, wire signature, image count |
| footprint `….image` | that image's segment entry (a copy of the product's) |
| footprint `….footprint` | ICORDS, the IGEOLO slice, corners, the derivation flags, `geometry_basis`, `precision`, `accuracy_m: null`, `orthorectified: false` |
| footprint `….label_basis` | what the footprint's label is taken from: `IID1` (the image identifier, trailing spaces trimmed), or `image_ordinal` (`Image <n>`, when IID1 is all spaces or not printable ASCII) |
| footprint `….security` | `labels`, `label_scope`, `assessment` |
| footprint `….diagnostics` | that image's diagnostics |

No footprint carries base64 or any copy of the source octets.

## 8. Handoff list

REQ-100's twelve items, in its order:

1. **Source code**: `packages/cdm/synapse_cdm/adapters/stanag4545.py`,
   `packages/cdm/synapse_cdm/adapters/nsif_codec.py`, `packages/cdm/synapse_cdm/adapters/nsif_geometry.py`,
   `packages/imagery/synapse_imagery/` — implemented.
2. **Locked optional dependencies**: none exist; `synapse-imagery` depends on `synapse-cdm` by
   range and on `jsonschema`, which `synapse-cdm` already requires, and ships no optional dependency
   or codec backend (`packages/imagery/pyproject.toml`) — implemented as that statement.
3. **Licence notices**: `LICENSE`, `NOTICE`, `packages/imagery/LICENSE`, `packages/imagery/NOTICE`;
   no third-party code is added — implemented.
4. **SBOM for native codec builds**: no native codec build exists — not claimed.
5. **Binary fixture manifest**: `docs/stanag4545-corpus.json` and the `PROVENANCE.json` records under
   `packages/cdm/synapse_cdm/fixtures/stanag4545/` — implemented.
6. **Installed-wheel test output**: section 6, Installed wheel and conformance — implemented with
   the readings named there.
7. **Conformance evidence**: section 6 and the generated evidence record, published by the release
   — implemented at the release.
8. **Performance measurements**: `gates/nsif_benchmark.py` and the reference-machine command of
   section 11 — maintainer action.
9. **Fuzz summary**: section 6, Fuzz summary; the 24-hour campaign is open — maintainer action.
10. **Residual and security mapping**: section 7 and the STANAG 4545 section of
    `packages/cdm/synapse_cdm/FORMAT_COVERAGE.md` — implemented.
11. **Deployment runbook**: `packages/imagery/docs/runbook.md` — implemented.
12. **Exact permitted claim text**: section 9 — implemented.

## 9. Permitted claim and what is not claimed

The one permitted claim, REQ-100's sentence:

> Implements the SC4545-CORE-1 NSIF/NITF imagery ingestion profile, with byte-preserving metadata inventory, specified NC sample decoding and direct geographic footprints.

No compression cell is added to it: no cell has passed its gate. Not claimed: certification or
approval by NATO or any authority; coverage of the whole STANAG 4545 family or of every NSIF
feature; accreditation for operational classification handling; compatibility or interoperability
with any named system, product or customer; decoding of any compressed or masked image; the
conformance of the experimental writer; broad STANAG 4545 conformance, whose gate stays open on
the items of section 10; and any reading of the SarPy or GDAL agreement on synthetic vectors as
NSIF acceptance.

## 10. Open items for the maintainer

- **The broad conformance gate (REQ-097)** stays open until these are acquired and checked:
  authenticated applicable Edition 2 text and errata; the full NSIF01.01 BIIF profile and accepted
  updates; a selected national or customer profile; the required registered TRE and DES catalogue;
  the required codec and mask specifications; official or accepted independent test files;
  independent results on unchanged NSIF files; a qualified security policy for real deployment
  labels.
- **The 24-hour fuzz campaign and the nightly bounded job (REQ-085)**: the commands are in section
  11; no workflow is added.
- **The reference-machine benchmark (REQ-087, REQ-088's timing targets)**: a recorded Linux x86_64
  machine with four virtual CPUs, at least 8 GiB of memory and a local SSD, with a pinned
  interpreter; the command is in section 11.
- **Codec cells and the writer gate (REQ-046, REQ-075, REQ-096)**: a pinned, packaged backend and
  its per-cell qualification; independent qualification of the writer against a normative profile.
- **Policy accreditation**: the default gate admits only clean unclassified material; a deployment
  that handles real labels supplies and qualifies its own policy engine.
- **`synapse-imagery`** ships as source in the repository and is not uploaded to the package index
  in this release.
- **A later normative discrepancy (REQ-098)**: no normative standard is pinned or held, so the rule
  has no subject yet. When a later profile revision is pinned and contradicts a field
  interpretation: give the profile a new identifier, revise the expected vectors, rerun the
  affected tests, and keep the earlier interpretation as a versioned record (the host already keeps
  interpretation revisions linked to the same original).
- **Release facts**: the tag, the index upload, the publication ledger entry, the CI run ids on the
  landing and release commits and the published evidence record close REQ-008, REQ-090 and REQ-091.

Defects found and fixed during delivery (none is open):

- The store's start-up recovery could disturb a live job while it was being created or ended; the
  store lock now covers a job directory's creation with its lock, its removal and recovery's job
  pass (found in review of the host round).
- A worker answer that named the worker itself with a code of the parser's error model (a cap
  refusal, for one) was catalogued as a rejection of the input, and every repeat then returned
  that rejection; only the host names worker outcomes, so every such answer now ends the attempt
  as an internal failure (found in the same review).
- A source path that no file can have (one holding a NUL character, or a character the file
  system cannot encode) ended as an internal failure; it now gets the `E_IO` answer a missing
  file gets (found in the same review).
- An 8-bit preview of an image with fewer than eight significant bits failed inside the worker; the
  renderer now maps only the representable range and refuses a window outside it (found in review
  of the worker round).
- A writer recipe time with a final newline, or written in digits of another script, raised instead
  of answering `E_FIELD`; the time and corner checks now match whole ASCII values (found in the same
  review).
- A public manifest string carried an internal ruling reference; it was removed (found in review of
  the registration round).
- The fuzz run of this record found no crash and no hang.

Observations of the final review of the host, none of them a defect; each is the maintainer's to
keep or to change, and each names the rule it rests on:

- **A failed link while storing an original.** When the store cannot link a written original
  into place (another file system mounted inside the store, a full directory), the ingest ends
  `failed` with `E_IO` and the complete staged octets stay behind as an owner-only, read-only
  store temporary until the next recovery removes them. The store commits by write, flush,
  link and unlink, and removing temporaries left under the tenants' directories is the last
  pass of the start-up recovery that every command opening a store runs first (REQ-067).
- **Reuse of an original marked corrupt.** A replay that finds a stored original corrupt marks
  it, and every later open of it is refused `E_INTEGRITY`. A later ingest of the correct octets
  into another dataset of the same tenant reuses the marked object, because the store reuses an
  object it already holds once the recorded digest and length equal the request's (REQ-066's
  write count and digest check); the new record is committed and its replay is refused
  `E_INTEGRITY` as well, until the object is restored as the runbook says.
- **An export rerun after an upgrade.** An export's identity is its recipe and its output
  digest, so that rerunning the same recipe is idempotent; its record also names the writer's
  and the packages' versions (REQ-076). A rerun of the same recipe into the same store after
  either package's version changes builds the same identity with a record of other content, and
  the immutable store answers `E_INTEGRITY` and writes no output, although the octets are the
  same. A derivative's identity, by contrast, includes the software versions (REQ-066).
- **The explanation text of a worker refusal.** The host holds every field of a worker child's
  refusal to the error model (its code, stage, offset and path) except the content of its
  explanation, which it copies into the result. The child's explanation is the parser's own
  text and never a source value, so only a compromised or replaced child could carry source
  text there (REQ-045: the worker answers, the host re-checks).
- **The deduplication key.** The key is REQ-065's `(tenant, dataset_namespace, synthetic, sha256,
  profile_revision)`; it has no part for an explicit context, so the same octets ingested again
  with another product key or `as_of` are answered by the first committed record.
- **Symbolic links inside the store.** Store reads refuse a symbolic link as the file they open
  but do not check each directory on the way to it, as the host's design has the store do for
  every directory it enters: a link planted in place of a store subdirectory, which needs write
  access to the owner-only store root, is followed by catalogue reads, while an ingest into that
  tenant refuses it with `E_IO`.
- **An output inside the store.** `--output` may name a path inside `--store`; with `--replace`
  an operator can overwrite a store file, the store marker included, after which commands refuse
  the store. The output rule refuses a URI and an overwrite without `--replace` (REQ-069); it
  does not refuse a path under the store.
- **A preview job's journal.** A preview job journals only its start, where the host's design has
  it journal its commit as well, so a crash after both of a derivative's files are linked and
  before the job's staging directory is removed is counted by recovery as a rolled-back job while
  the derivative stays; only the count is affected.

## 11. Commands

```
python -m pytest tests/test_cdm_stanag4545_adapter.py tests/test_cdm_nsif_codec.py tests/test_cdm_nsif_geometry.py
python -m pytest tests/test_cdm_boundary.py tests/test_cdm_resource_envelope.py tests/test_cdm_input_bounds.py
python -m pytest tests/test_cdm_nsif_robustness.py tests/test_cdm_nsif_fuzz.py tests/test_cdm_nsif_benchmark.py tests/test_cdm_stanag4545_evidence.py
python -m synapse_cdm.manifests --out manifests
python -m synapse_cdm.manifests --check --out manifests
synapse conformance run --adapter stanag4545
python -m synapse_cdm.harness --adapter stanag4545 --schemas schemas
python packages/cdm/synapse_cdm/fixtures/stanag4545/spec/build_fixtures.py --check
python gates/nsif_gdal_reading.py --check
python gates/nsif_fuzz.py --quick --out fuzz-quick.json
python gates/nsif_fuzz.py --mutations 100000 --out nightly.json
python gates/nsif_fuzz.py --mutations <N> --out campaign.json
python gates/nsif_benchmark.py --machine "<description>" --out benchmark-linux-x86_64.json
python -m synapse_cdm.evidence generate --adapter stanag4545 --out <directory>
python -m synapse_cdm.evidence verify <directory>/stanag4545/1.0.0/evidence.json
python gates/wheel_install.py
cd packages/imagery && python -m pytest -q -rs
```

The fuzz campaign's `<N>` is sized by the maintainer for 24 hours on the machine that runs it. The
GDAL check needs GDAL's command-line tools and is run by hand where they exist.
