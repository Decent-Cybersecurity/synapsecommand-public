# SC Link16 Gateway → CDM: implementation record

Written 2026-10-10, when the `link16_gateway` adapter landed with CDM 3.1.0's two new
`PositionSource` members, as the in-tree record of the SynapseCommand JREAP C and Link 16
engineering handoff 1.0.0. It carries what the handoff asks a release to report (its REQ180 to
REQ182): every requirement and every acceptance row with its disposition and evidence, the
maintainer's and the lead's rulings by id, the deviations from the handoff's specification and from
its reference mapper, the measurements behind the figures quoted here, and the open items. No
numerical quality score is given anywhere, by the handoff's REQ180.

Conventions. `pkg/` is `packages/cdm/synapse_cdm/` of this repository. "The specification" is the
handoff's engineering specification (REQ001 to REQ192, 83 requirement ids, and its sections 6 to
21); "the reference mapper" is the handoff's companion projection script, which this repository
does not carry. `AD`, `ID` and `MP` are the adapter's three test modules
`tests/test_cdm_link16_gateway_adapter.py`, `tests/test_cdm_link16_gateway_identity.py` and
`tests/test_cdm_link16_gateway_mapping.py`; `AD::name` is a test in one of them. "The bridge" is
the separate distribution `synapse-link16-bridge` (`packages/link16_bridge/`), which carries the
runtime half of the handoff and lands after the adapter in the same arc; its tests are named in its
own requirement matrix, `packages/link16_bridge/docs/requirements-matrix.md`. Commands are written
as they run from the repository root with the repository's own interpreter.

Disposition words: **PASS** — implemented here, with the evidence named; **NOT_RUN** — not run,
with the reason; **BLOCKED_EXTERNAL_EVIDENCE** — needs evidence from outside this repository, with
the gate that unblocks it; **not-claimed** — deliberately not offered; **maintainer-action** —
needs an act only the maintainer can take. "At this landing" is the state of the commit that lands
the adapter: the runtime rows read NOT_RUN there and are re-dispositioned when the bridge lands.

## 1. Scope

The handoff asks for three things: a pure public translator `link16_gateway`, a runtime service,
and a provider boundary for native JREAP C and Link 16 (REQ003). This record covers the arc that
builds the first two and the boundary of the third:

- the CDM 3.1.0 enum extension the translator needs, `PositionSource.SENSOR` and
  `PositionSource.UNKNOWN` (REQ011), landed with `SCHEMA_VERSION` still `3.0.0` and typed at the
  release commit, in the form of the 3.0.0 landing;
- the adapter `pkg/adapters/link16_gateway.py`, registered as `link16_gateway`, bidirectional,
  ordinal 23 of the adapter series, with its fixtures, goldens, three test modules, generated
  manifest, documentation page `docs/docs/cdm/link16-gateway.mdx` (the contract of export mode) and
  the gateway contract's three schemas published under `schemas/link16_gateway/`;
- the runtime bridge, a sibling distribution with its own tests, outside the adapter registry;
- the release synapse-cdm 3.4.0 with CDM schema 3.1.0.

Native JREAP C and Link 16 interoperability is neither implemented nor claimed: no native frame,
message or J-series word is parsed or produced anywhere in this repository, and the native provider
boundary refuses with `BLOCKED_EXTERNAL_EVIDENCE` until the specification's gates N01 to N09 are
met (section 9).

## 2. Baseline and source pins

| What | Value | How it was read |
|---|---|---|
| Repository base | `6a620be` on `main` (the 3.3.0 documentation deploy, one commit past the tag `v3.3.0` = `e3acf78`); the arc branch `soif/link16-1.0` starts there | `git rev-parse HEAD origin/main v3.3.0^{commit}` |
| The handoff | SynapseCommand JREAP C and Link 16 engineering handoff, implementation contract 1.0.0 of 4 October 2026, written against the older repository base `c4bba1b`; every statement it makes about the repository was read again on `6a620be` | — |
| Handoff integrity | every entry of its `SHA256SUMS.json` recomputed: 27 of 27 equal | SHA-256 of each listed file, compared with the recorded digest (2026-10-10) |
| Handoff files carried here | the six example reports and the six reference projections, byte-identical, under `pkg/fixtures/link16_gateway/` and its `reference/`; the three schemas, byte-identical, under `schemas/link16_gateway/` | `cmp` against the handoff, all identical (the round review of 2026-10-10) |
| Pin record | `pkg/fixtures/link16_gateway/spec/link16_gateway_pin.json`, list form, 16 entries (each carried file, the three schemas, and the specification, which is not carried), each with SHA-256 and size; it states that it is internal gateway evidence and not normative Link 16 evidence (REQ191) | every entry's digest and size recomputed from the handoff: 16 entries, 0 mismatches |

The handoff's reference mapper, its test script and its two proposed schemas are not carried, and
no file of the handoff was copied into the repository except those named above.

## 3. Version register

| Item | At this landing | At the release |
|---|---|---|
| synapse-cdm package | `3.3.0` declared, the tree past it | `3.4.0` |
| CDM schema | `3.0.0` declared; the models hold the two 3.1.0 members | `3.1.0`, frozen under `tests/frozen/cdm/3.1.0/` |
| Adapter API | `3.1.0` (unchanged) | `3.1.0` |
| Manifest schema | `2.1.0` (unchanged) | `2.1.0` |
| Evidence schema | `2.0.0` (unchanged) | `2.0.0` |
| SC Link16 Gateway contract | `1.0.0` (`sc-link16-gateway/1.0.0`) | `1.0.0` |
| `link16_gateway` adapter | `1.0.0` | `1.0.0` |
| `synapse-link16-bridge` | lands after the adapter | `1.0.0`, released on GitHub in the tag and the Release, not uploaded to PyPI (L-11) |

## 4. Rulings

All of 2026-10-10. The maintainer's rulings (U) govern the lead's (L), which govern the run
decisions (D) and those accepted from rounds (C).

**The maintainer.**
- **U-01** Scope "do all": the translator, the gateway API contract, the synthetic provider and the
  runtime bridge are in scope; native interoperability stays blocked on external evidence.
- **U-02** Base: the current `main` (`6a620be`, 3.3.0), not the handoff's `c4bba1b`.
- **U-03** CDM version and sequencing delegated to the lead (L-02).
- **U-04** Export mode is defined by the lead (L-07); the documentation page is its contract.
- **U-05** The arc runs autonomously through the release on GitHub and PyPI, in the same acts as
  the 3.3.0 release; creating a PyPI project for a second distribution is not covered.
- **U-06** The standing refused-name rule for the public tree.
- **U-07** The model and checkpoint setup of the agents that built the arc (process only).

**The lead.**
- **L-01** Done means every requirement and acceptance row ends with evidence or an explicit
  disposition; no score; the release stages of REQ182 are reported separately.
- **L-02** CDM 3.1.0 (a MINOR) and package 3.4.0, one release, in the 3.0.0 landing form; REQ012's
  4.0.0 not followed; no shipped adapter re-labelled.
- **L-03** Registry, module and fixture names `link16_gateway`; the ordinals test's two name
  patterns widened to admit `_`, dated, with a mutation reading.
- **L-04** `source.system` = `SC_LINK16_GATEWAY`, one token; `format_name` stays
  `SC Link16 Gateway`.
- **L-05** Manifest: binding `provisional-internal-profile`, claim `PROVISIONAL`, licence `OPEN`,
  bidirectional, structured residual, L4; the handoff's schemas, examples and goldens contributed
  under Apache-2.0; NOTICE unchanged.
- **L-06** Limits: manifest 1 048 576 octets and depth 64; the contract's depth 32 and 10 000 nodes
  inside; `InputTooLarge`/`InputTooDeep` past the manifest's bounds; every other refusal
  `Link16GatewayRefusal` with a code and a message that never echoes a payload value.
- **L-07** Modes: mirror by default, exact equality; export under an immutable `ExportContext`,
  with refusals and a structured loss report; neither transmits.
- **L-08** MAPPINGS: canonical declarations, the whole report as a structured residual, and three
  residual-only projections asserted by the tests.
- **L-09** Vertical: HAE feet become metres in `vertical` and `alt_m`; the tension with the
  description of `Position.vertical` stated.
- **L-10** Strictness where the reference mapper is lenient (section 8).
- **L-11** The bridge as a sibling distribution with standard-library runtime dependencies besides
  synapse-cdm; on GitHub only in this release.
- **L-12** The native boundary refuses `BLOCKED_EXTERNAL_EVIDENCE` and never falls back.
- **L-13** Performance (REQ161, F01): the rig is Linux x86_64 with four dedicated cores; NOT_RUN
  here, the harness ships.
- **L-14** Fixtures and goldens (section 10).
- **L-15** The three test modules with the repository's `test_cdm_` prefix; the report schema as a
  module literal; the three schemas published under `schemas/link16_gateway/`.
- **L-16** This record and the documentation page.
- **L-17** Commits: the adapter landing, the bridge landing, the release commit, then the tag and
  the pipeline, each with one sign-off.
- **L-18** Arcs in flight on older bases re-pin and re-stamp against 3.4.0 / CDM 3.1.0 when they
  land; nothing of theirs is touched.

**Run decisions** (the plan's D-01 to D-47 accepted as proposed, with these as amended or noted):
D-00 the round mapping: the CDM 3.1.0 members first; then the adapter with its fixtures, goldens,
tests and every bookkeeping row in one round, because the roster sweeps cannot pass with either half
alone; then the documentation page, this record and the migration notes, the three rounds forming
one landing commit; then the bridge in a second commit and the release in a third, each commit
after a final review; D-01 the ordinals widening only, no alias entry; D-02 reversed: the support
matrix's binding legend gains one dated clause, with a PATCH ruling; D-03 the provisional-set test
renamed; D-04 two
permanent count exemptions for the 3.3.0 history; D-05 byte-level refusals as `.bin`; D-06 the
three schemas published, module literals for the wheel; D-07 the wording rule that keeps the egress
mode's name away from the migration notes' file name; D-08 the DIS 7 entity pin re-pointed to the
frozen 3.0.0 copy now, its profile re-derived at the release; D-09 the landing names the
version-pending facts, and no test is red by construction; D-10 the pinned phrase count kept;
D-11 hand-written 3.0.0 documents left at 3.0.0 by choice or because pinned; D-12 the release's
`KNOWN_CONTRACTS` (MINOR) and `assess` (PATCH) rulings; D-13 the enum docstring fixed before the
freeze; D-14 no re-labelling, the REQ011 tension named; D-15 the changelog's fixed phrase; D-16 the
3.1.0 `SELF` provenance resolved before any next package bump; D-17 a timestamp's shape error is
`TIME_UNRESOLVED`; D-18 the number rule narrowed to overflow, non-zero underflow and inexact
integers; D-19 the compatibility projection outside the ledger; D-20 the feet transformation only
when a converted height is emitted; D-21 `max_objects` absent with a reason; D-22 the handoff's
goldens under `reference/`, never re-stamped; D-23 the loss carrier and the `TRUNCATED` loss for a
sub-millisecond time; D-24 a missing `origin_scope` is `SCHEMA_INVALID` at the adapter; D-25 no
format checker; D-26 one module and the `cdm_schema` keyword; D-27 to D-37 the bridge's design
(workflow name, version and dependency, GitHub-only release, local codes, open terms, batch stop
codes, synthetic wrapper, authentication, ARCHITECTURE §7, boundary sentence, notice deduplication),
D-31 with `connect_timeout_seconds` kept at 5 and a separate `transport_allowance_seconds`; D-38 the
release-notes rendering repair, with a PATCH ruling; D-39 every landing commit fully green; D-40
one sign-off and no other trailer; D-41 the tag message; D-42 handoff bytes only in throwaway
clones; D-43 the host's `times.parse` hour-24 finding recorded, not changed (section 11); D-44
ordinal 23 re-checked before the push; D-45 the bridge's REQ134 test reads the forbidden list at run
time; D-46 the runtime's name (section 7); D-47 history export not offered by the runtime; D-48
the wording rules for every file the arc writes; D-49 the bump gate's roster-move attribution made
per module, with regression tests.

**Accepted from rounds.** C-R1-01 the `PositionSource` docstring paragraph is the wire-published
wording; C-R1-02 one count clause for everything moved since `v3.3.0`; C-R1-03 the DIS 7 pin's
dated note; C-R1-04 the REQ011 tension in FORMAT_COVERAGE; C-R2-01 the schema-error choice for an
`anyOf` and the refusal paths; C-R2-02 `ExportContext`'s two objects stored as compact JSON text,
the duplicate-identifier and missing-position-time refusals, the loss order; C-R2-03 each written
fixture's own `record_id`; C-R2-04 the release procedure's harness count and the resource-envelope
roster; C-R2-05 the bump gate's per-module attribution.

## 5. Acceptance rows

The handoff's `acceptance.csv` has 45 rows (38 `implementation`, 7 `native external`), every one
`NOT_RUN` in the handoff.

| Row | Expected | Evidence | At this landing |
|---|---|---|---|
| C01 | four domains: Entity first, Track iff position | `MP::test_entity_first_track_iff_position`; `AD::test_every_packaged_fixture_translates_and_validates_against_the_generated_schemas`; harness and suite over the 15 fixtures (section 10); the bridge's ingest of the four domains | PASS (translator); runtime half NOT_RUN until the bridge lands |
| C02 | missing key, unknown key, wrong type: `SCHEMA_INVALID`, no partial output | `AD::test_malformed_fixtures_are_refused_with_their_expected_codes` (`missing_required_key`, `unknown_top_level_key`, `unknown_nested_key`, `number_as_string`, `top_level_array`); `AD::test_schema_refusals_name_path_and_keyword_and_never_a_value`; `to_cdm` raises before any object exists | PASS |
| C03 | duplicate keys, NaN, Infinity, invalid UTF-8, surrogate: `JSON_INVALID`, bounded refusal | `AD::test_octet_only_refusals`, `AD::test_dict_path_refusals`, `AD::test_a_byte_order_mark_and_utf16_are_refused_and_trailing_whitespace_is_not`, the nine `JSON_INVALID` files of `malformed/`; `AD::test_seeded_mutation_fuzz_refuses_only_with_the_contract_vocabulary`; the bridge's per-report quarantine | PASS (translator: the message names code, path and rule, never a value); runtime half NOT_RUN until the bridge lands |
| C04 | above 1 MiB, depth 32, 10 000 nodes: `LIMIT_EXCEEDED` before conversion | `AD::test_depth_32_is_limit_free_33_is_limit_exceeded_65_is_input_too_deep`, `AD::test_nodes_10000_admitted_10001_refused`, `AD::test_one_octet_over_1_mib_is_input_too_large_and_a_dict_over_1_mib_is_limit_exceeded`; `depth_33.bin`, `nodes_10001.bin` | PASS; above 1 MiB of octets and above depth 64 the code is realised as `InputTooLarge` / `InputTooDeep` (L-06) |
| P01 | zeros, poles, longitude 180 preserved | `MP::test_zero_poles_antimeridian_preserved` | PASS |
| P02 | partial or out-of-range position refused; wrapper null for an unavailable fix | `partial_coordinates.json`, `latitude_out_of_range.json` via `AD::test_malformed_fixtures_are_refused_with_their_expected_codes`; the bridge's synthetic wrapper | PASS (translator); synthetic wrapper NOT_RUN until the bridge lands; native wrapper BLOCKED_EXTERNAL_EVIDENCE (N04, N05) |
| P03 | SENSOR or UNKNOWN under the new schema, no false GNSS | `MP::test_sensor_and_unknown_methods_project_under_cdm_3_1` against the schemas the models generate; against the frozen 3.1.0 contract from the release commit | PASS (the handoff's "schema4" is CDM 3.1.0, L-02) |
| P04 | SENSOR or UNKNOWN under 3.0.0: position null, no Track, compatibility transform | `MP::test_compatibility_projection_validates_against_frozen_3_0_0`, `MP::test_compatibility_projection_omits_unrepresentable_positions`, `MP::test_compatibility_projection_keeps_representable_positions_with_a_track`; the bridge's negotiation | PASS (translator); negotiation NOT_RUN until the bridge lands |
| V01 | 10000 ft HAE → 3048 m in `vertical` and `alt_m`, feet kept | `MP::test_hae_feet_becomes_metres_in_vertical_and_alt_m_and_feet_stay_in_residual` | PASS (L-09 tension stated) |
| V02 | MSL, BARO, AGL, FL keep the source vertical, `alt_m` null | `MP::test_other_datums_keep_source_vertical_and_null_alt_m` | PASS |
| V03 | subsurface depth never a negative `alt_m` | `MP::test_subsurface_depth_is_never_a_negative_alt_m` | PASS |
| I01 | reconnect or changed reporter keep both ids | `ID::test_reconnect_and_changed_reporter_keep_ids`, `ID::test_all_provenance_changed_at_once_keeps_ids`; the bridge's identity tests | PASS (translator); runtime half NOT_RUN until the bridge lands |
| I02 | each tuple member changes both ids | `ID::test_each_tuple_member_changes_both_ids`, `ID::test_the_synthetic_layer_is_a_tuple_member` | PASS |
| I03 | ambiguous reuse quarantined until resolved | the bridge's identity tests | NOT_RUN until the bridge lands (planned: the quarantine branch; the operator release is a recorded deviation, section 7) |
| I04 | REKEY relation, nothing merged | the bridge's identity tests | NOT_RUN until the bridge lands |
| A01 | finer tokens → `UNKNOWN`, token kept | `MP::test_affiliation_projects_to_four_and_keeps_the_token` | PASS (the Affiliation docstring tension stated) |
| T01 | rollover or unknown day: resolve only with evidence, else `TIME_UNRESOLVED` | the `TIME_UNRESOLVED` files of `malformed/`; `AD::test_strict_calendar_refuses_second_60_hour_24_and_february_30`; `AD::test_component_time_after_effective_is_time_unresolved_and_earlier_is_kept`; the bridge's time tests | PASS for the refusal branch (translator); runtime half NOT_RUN until the bridge lands; the resolve-with-evidence branch not-claimed: it needs an authenticated native time anchor (BLOCKED_EXTERNAL_EVIDENCE, N03, N04) |
| T02 | leap second refused; future beyond 5 s `TIME_SKEW`, egress denied | `AD::test_strict_calendar_refuses_second_60_hour_24_and_february_30` (second 60), `second_60_effective_at.json`, `second_60_component.json`; the bridge's skew tests | PASS (leap second); skew NOT_RUN until the bridge lands |
| T03 | late history kept, current never backward | the bridge's state tests | NOT_RUN until the bridge lands |
| T04 | equal-time conflict explicit | the bridge's state tests | NOT_RUN until the bridge lands |
| N01 | native frame split at every byte | — | BLOCKED_EXTERNAL_EVIDENCE (gates N01, N03, N07) |
| N02 | several native frames in one read | — | BLOCKED_EXTERNAL_EVIDENCE (N01, N02, N03, N07) |
| N03 | bad frame length or impossible word combination | — | BLOCKED_EXTERNAL_EVIDENCE (N03, N04, N07) |
| N04 | UDP sender mismatch, loss, duplicate, reorder | — | BLOCKED_EXTERNAL_EVIDENCE (N02, N03, N07) |
| N05 | unknown legal J-series family kept opaque | — | BLOCKED_EXTERNAL_EVIDENCE (N04, N05, N07) |
| N06 | every required word form and numeric edge code | — | BLOCKED_EXTERNAL_EVIDENCE (N04, N07) |
| L01 | disconnect, heartbeat loss, stale, expiry drop nothing | the bridge's lifecycle tests | NOT_RUN until the bridge lands |
| L02 | authorised drop closes the exact incarnation | the bridge's lifecycle tests | NOT_RUN until the bridge lands; the reporting-authority half of REQ105 not-claimed (notices carry no reporter) |
| L03 | cursor expiry or gap: INCOMPLETE, egress blocked | the bridge's lifecycle tests | NOT_RUN until the bridge lands; REQ106's snapshot request not-claimed (the API has none) |
| E01 | export denied or synthetic mismatch: zero sends | `AD::test_export_synthetic_mismatch_three_ways`; the bridge's egress policy tests | PASS (translator half); runtime half NOT_RUN until the bridge lands |
| E02 | wrong edition, unallocated number, expired request | the bridge's egress tests | NOT_RUN until the bridge lands (planned against the synthetic profile) |
| E03 | unsupported datum or out-of-range field: refusal, or permitted unknown with a loss report | `AD::test_export_altitude_datum_unsupported_refused_or_omitted_with_loss`, `AD::test_export_value_not_representable_cases`, `AD::test_a_track_quality_is_an_omitted_loss`, `AD::test_export_refuses_a_non_finite_number_at_its_path`, `AD::test_export_refuses_a_grade_quality_code_cannot_hold`; the bridge's egress tests | PASS for both branches at gateway level (refused, or omitted with a loss when the height is optional); the native unknown-code choice BLOCKED_EXTERNAL_EVIDENCE (N04) |
| E04 | same `request_id`, different body: 409, one send | the bridge's gateway API tests | NOT_RUN until the bridge lands |
| E05 | timeout after a possible send: UNKNOWN, reconcile | the bridge's egress tests | NOT_RUN until the bridge lands |
| E06 | conflicting Entity and Track: `CDM_SOURCE_CONFLICT` | `AD::test_mirror_refuses_every_deviation_as_cdm_source_conflict`, `AD::test_a_mirror_refusal_never_echoes_a_key_from_the_residual_or_attributes`, `AD::test_export_list_rules_are_cdm_source_conflict` | PASS |
| R01 | crash after commit before ACK | the bridge's resilience tests | NOT_RUN until the bridge lands |
| R02 | crash before commit | the bridge's resilience tests | NOT_RUN until the bridge lands |
| R03 | lease loss while export queued | the bridge's resilience tests | NOT_RUN until the bridge lands |
| S01 | in-band security label escalation | the bridge's security tests | NOT_RUN until the bridge lands |
| S02 | replay data reaching a live realm | the bridge's security tests | NOT_RUN until the bridge lands |
| F01 | 1000 reports per second for 30 minutes and a burst | — | NOT_RUN: the rig is Linux x86_64 with four dedicated cores, 8 GiB and a local durable store (REQ161); this arc's machines are arm64 and aarch64, and no timing from them is evidence (L-13); the bridge ships the measurement harness for the maintainer |
| F02 | queue and quarantine limits | the bridge's limits tests | NOT_RUN until the bridge lands |
| G01 | installed wheel outside the repository | `gates/wheel_install.py` with `AD` and `ID` in its package-only list and `MP` in its repository-bound list; the bridge's wheel test | NOT_RUN at this landing: the wheel gate builds and installs a wheel and is run before the release (the release procedure) |
| G02 | missing normative resource: `BLOCKED_EXTERNAL_EVIDENCE` | the bridge's native-boundary tests | NOT_RUN until the bridge lands (planned: the refusal is the evidence) |
| G03 | independent peer bidirectional trial | — | BLOCKED_EXTERNAL_EVIDENCE (gate N08, a witnessed peer trial) |

## 6. The specification's section 17 test groups

| Group | Closed by | At this landing |
|---|---|---|
| Contract | C01 to C04; the Unicode fixture and its octet twin | PASS (translator) |
| Position | P01 to P04 | PASS (translator) |
| Vertical | V01 to V03; the HAE-metres, BARO, AGL, FL and depth fixtures | PASS |
| Identity | I01 to I04 | PASS for I01 and I02; I03 and I04 NOT_RUN until the bridge lands |
| Affiliation | A01; `identity_code` kept in the residual | PASS |
| Time | T01 to T04 | PASS for the translator's refusals; ordering, conflict and skew NOT_RUN until the bridge lands; rollover and missing-date resolution BLOCKED_EXTERNAL_EVIDENCE (native time anchor) |
| Native framing | N01 to N04 | BLOCKED_EXTERNAL_EVIDENCE |
| Lifecycle | L01 to L03, I03 | NOT_RUN until the bridge lands |
| Egress | E01 to E03 and the bridge's loop-prevention test | PASS for the translator's refusals and losses; runtime NOT_RUN until the bridge lands; native rounding edges BLOCKED_EXTERNAL_EVIDENCE |
| Crash recovery | R01 to R03, E05 | NOT_RUN until the bridge lands |
| Packaging | G01; manifests and schemas `--check`; the refused-name scan and the positioning sweep | generated files CURRENT at this landing; the wheel gate NOT_RUN until the release procedure |
| Robustness | C04, F02, the adapter's edge payloads and seeded fuzz | PASS for the parser (`AD::test_edge_payloads_are_accepted_schema_valid_and_mirrored`, `AD::test_seeded_mutation_fuzz_refuses_only_with_the_contract_vocabulary`); overload NOT_RUN until the bridge lands; native frame fuzz BLOCKED_EXTERNAL_EVIDENCE; sustained load NOT_RUN (F01) |

## 7. Requirement dispositions

One row per requirement id, 83 in all. "Bridge" means the runtime half, NOT_RUN at this landing and
judged by the bridge's tests when it lands.

| REQ | Subject | Evidence | At this landing |
|---|---|---|---|
| 001 | receive, and export when separately enabled | C01; export mode; the bridge's export gating | PASS (translator); bridge; PPLI not-claimed |
| 002 | no weapons, engagement or key management | nothing of the kind anywhere; the documentation page's scope | PASS (translator); bridge |
| 003 | translator, runtime service, provider boundary | the adapter; the bridge; the native boundary | PASS (translator); bridge; native provider BLOCKED_EXTERNAL_EVIDENCE; runtime name deviation (section 7.1) |
| 004 | ingest only by default at the runtime | the bridge's configuration tests | bridge; the translator's bidirectional declaration grants no transmit permission |
| 005 | native TCP client and server roles | — | BLOCKED_EXTERNAL_EVIDENCE (N02, N03) |
| 006 | transport variant and standard edition kept apart | the bridge's native pin record | bridge (field split); native transport BLOCKED_EXTERNAL_EVIDENCE |
| 010 | the files the specification names | the adapter, `pkg/fixtures/link16_gateway/`, the three test modules, the documentation page | PASS with deviation (test module names, section 7.1) |
| 011 | `PositionSource.SENSOR` and `UNKNOWN` | `pkg/enums.py`; P03 | PASS; no shipped adapter re-labelled (D-14) |
| 012 | publish the extension as a new major | schemas re-exported from the models; 3.0.0 family frozen; 3.1.0 frozen at the release | PASS with deviation: CDM 3.1.0, a MINOR, not 4.0.0 (L-02) |
| 013 | negotiate the output schema | P04; the bridge's negotiation | PASS (translator); bridge; the full-projection end-to-end path runs from the release commit |
| 014 | Adapter API preserved, one report per call | `AD::test_input_types`; no SDK change | PASS |
| 020 | native profile pins its documents | the bridge's G02 refusal | bridge (refusal); pin content BLOCKED_EXTERNAL_EVIDENCE (N01) |
| 021 | verified native definitions | the bridge's `NATIVE_PROFILE_INCOMPLETE` gate | bridge (gate); definitions BLOCKED_EXTERNAL_EVIDENCE (N03, N04) |
| 022 | missing definitions fail activation | G02 | bridge |
| 030 | only the wrapper interprets J-series codes | the translator reads explicit report fields only | PASS (translator); bridge; native wrapper BLOCKED_EXTERNAL_EVIDENCE |
| 031 | complete snapshots | P02 runtime half | bridge (synthetic); native assembly BLOCKED_EXTERNAL_EVIDENCE |
| 032 | assembly separate from deduplication | the bridge's ingest tests | bridge; native word assembly BLOCKED_EXTERNAL_EVIDENCE |
| 033 | component timestamps kept, at or before `effective_at` | `AD::test_component_time_after_effective_is_time_unresolved_and_earlier_is_kept`; `MP::test_track_sample_time_is_position_observed_at`; the bridge's state tests | PASS (translator); bridge |
| 040 | receive and encode coverage per family | the bridge's configuration tests | bridge; native coverage BLOCKED_EXTERNAL_EVIDENCE |
| 041 | no automatic hostility | A01; the bridge's ingest tests | PASS (translator); bridge |
| 050 | null and unknown survive | `MP::test_kinematics_copied_with_nulls_and_time_in_residual_only`, `MP::test_quality_code_is_source_quality_only`; the bridge's ingest tests | PASS (translator); bridge; native unavailable codes BLOCKED_EXTERNAL_EVIDENCE |
| 051 | `record_id` and `sequence` | `AD::test_uint64_bounds_inclusive`; the bridge's gateway API tests | PASS (translator); bridge |
| 052 | timestamp form and rollover | `AD::test_strict_calendar_refuses_second_60_hour_24_and_february_30`, `AD::test_ecma_digit_reading_refuses_non_ascii_digits`; T01 | PASS (refusal); anchor-based resolution not-claimed (native) |
| 060 | authentication and authorisation | the bridge's gateway API tests | bridge |
| 061 | body and report limits, deadlines | C04 (report limits); the bridge's gateway API tests | PASS (report limits); bridge |
| 062 | status codes and error bodies | the bridge's gateway API tests | bridge |
| 063 | retention | the bridge's tests | bridge |
| 064 | records, reports and notices | the bridge's contract tests; a notice is refused by the translator | bridge |
| 065 | malformed report quarantined, the rest continue | the bridge's ingest tests | bridge |
| 070 | identities kept distinct | I01; `ID::test_entity_and_track_ids_differ_and_track_points_to_entity` | PASS (translator); bridge |
| 071 | `origin_scope` defined; missing scope | `MP::test_missing_origin_scope_is_schema_invalid`; the bridge's scope tests | PASS with deviation (D-24); bridge |
| 072 | incarnation advances only on established reuse | I03 | bridge |
| 073 | REKEY never merges | I04 | bridge |
| 074 | two sources stay separate | `ID::test_identical_track_numbers_in_two_realms_or_layers_never_collide`; E02 | PASS (translator); bridge |
| 080 | Entity first, Track iff position | C01 | PASS |
| 081 | `SourceRef` fields; synthetic equality | `MP::test_source_ref_fields`; `AD::test_synthetic_mismatch_both_ways` | PASS with deviation: `source.system` = `SC_LINK16_GATEWAY` (L-04) |
| 082 | transformations in order, only when applied | `MP::test_transformations_exact_strings_and_order` | PASS with deviation (D-20, section 8) |
| 083 | no symbol, confidence or `valid_to`; no attributes schema | `MP::test_symbol_confidence_valid_to_attributes_stay_empty` | PASS (the Affiliation docstring tension stated) |
| 084 | HAE feet become metres in both | V01 | PASS; the tension with `Position.vertical`'s description stated (L-09) |
| 085 | MAPPINGS cover every leaf | `MP::test_mappings_ledger_has_no_lost_leaf_on_every_fixture`, `MP::test_the_ledger_catches_a_wrong_projection`, `MP::test_residual_only_projections_are_asserted_here`; the suite's ledger (section 10) | PASS with deviation (L-08); the compatibility projection outside the ledger (D-19) |
| 090 | mirror mode | `AD::test_mirror_reproduces_every_packaged_report`, `AD::test_mirror_refuses_every_deviation_as_cdm_source_conflict` | PASS |
| 091 | export under an immutable `ExportContext` | `AD::test_export_context_is_frozen_and_validated`, `AD::test_export_context_objects_are_bounded_where_they_land_and_together_at_export`, `AD::test_export_builds_a_valid_report_from_entity_and_track` | PASS; the documentation page is the export contract (U-04) |
| 092 | export list rules | `AD::test_export_list_rules_are_cdm_source_conflict` | PASS (translator); history export not offered by the runtime: not-claimed (D-47) |
| 093 | identity tokens in export; audit | `AD::test_export_builds_a_valid_report_from_entity_and_track`, `AD::test_export_writes_quality_code_from_source_quality` (no confidence becomes a grade); the bridge's egress audit | PASS (translator); bridge |
| 094 | altitude only in a supported datum | E03 | PASS (translator); bridge; an external geoid transformation not-claimed |
| 095 | loss report for every unrepresentable field | `AD::test_export_value_not_representable_cases`, `AD::test_sub_millisecond_valid_from_gives_a_truncated_loss`, `AD::test_a_track_quality_is_an_omitted_loss`, `AD::test_export_refuses_a_non_finite_number_at_its_path`, `AD::test_a_non_finite_number_keeps_the_losses_before_it_and_one_never_written_is_no_refusal`, `AD::test_export_refuses_a_grade_quality_code_cannot_hold`, `AD::test_a_track_grade_is_carried_only_when_it_is_the_entity_s` | PASS (loss report); native quantisation BLOCKED_EXTERNAL_EVIDENCE |
| 096 | transmission checks and states | E01, E02 | bridge |
| 097 | idempotent requests, no blind retry | E04, E05 | bridge |
| 100 | transactional ingest | R01, R02 | bridge |
| 101 | deduplication | R01 | bridge |
| 102 | history and current state | T03, T04 | bridge |
| 103 | freshness defaults | T02 | bridge |
| 104 | stale and expired never delete | L01 | bridge |
| 105 | drop closes the exact source | L02 | bridge (exact tuple); reporting-authority half not-claimed |
| 106 | scope reset | L03 | bridge; snapshot request not-claimed |
| 110 | provider interface | the bridge's synthetic provider | bridge (protocol); native BLOCKED_EXTERNAL_EVIDENCE |
| 111 | TCP stream framing | — | BLOCKED_EXTERNAL_EVIDENCE (N03) |
| 112 | UDP datagram framing | — | BLOCKED_EXTERNAL_EVIDENCE (N02, N03) |
| 113 | native management messages | — | BLOCKED_EXTERNAL_EVIDENCE (N03) |
| 114 | session isolation and backoff | the bridge's backoff tests | bridge (application backoff); native session rules BLOCKED_EXTERNAL_EVIDENCE |
| 115 | unknown messages kept opaque | the bridge's ingest tests | bridge (gateway level); native framing refusals BLOCKED_EXTERNAL_EVIDENCE |
| 120 | runtime limits | F02 | bridge |
| 121 | backpressure | F02 | bridge (gateway API mode); UDP mode BLOCKED_EXTERNAL_EVIDENCE |
| 122 | durable history, bounded cache | F02 | bridge |
| 130 | no credentials or crypto in the translator | `AD::test_imports_stay_inside_the_allowed_roots`; the host's boundary tests; the bridge's credential tests | PASS (translator); bridge |
| 131 | context bound to authentication | S01, E01 | bridge |
| 132 | replay separated | S02 | bridge |
| 133 | loop prevention | the bridge's egress tests | bridge |
| 134 | no native, radio, crypto or accreditation claim | the manifest's limitations; the documentation page; the positioning sweep | PASS (translator); bridge |
| 140 | startup order | the bridge's startup tests | bridge |
| 141 | fencing lease | R03 | bridge |
| 150 | metrics | the bridge's observability tests | bridge |
| 151 | audit and readiness | the bridge's observability tests | bridge |
| 160 | gateway tests are not native wire tests | this record; the bridge's requirement matrix | PASS (statement); native wire tests BLOCKED_EXTERNAL_EVIDENCE (N07) |
| 161 | performance gate on the named rig | F01 | NOT_RUN (L-13) |
| 162 | accounting of every input | the bridge's accounting tests | bridge (accounting); throughput NOT_RUN |
| 170 | native conformance matrix | — | BLOCKED_EXTERNAL_EVIDENCE: the matrix needs native evidence |
| 180 | no score; manifest declarations | `AD::test_metadata_values_field_by_field`; the generated manifest | PASS with deviation: `IMPLEMENTED` is not admitted beside a provisional binding by `tests/test_cdm_manifests.py`, so the claim is `PROVISIONAL` (L-05) |
| 181 | no transport registry migration | no SDK change; the bridge outside the registry | PASS |
| 182 | release stages reported apart | the documentation page; this record; the release notes | PASS: only the first stage, internal gateway translation, is claimed |
| 190 | no gate weakened | the only widening is L-03's, recorded with its mutation reading (section 10) | PASS |
| 191 | everything moved together; installed-package check; pin record wording | versions, schemas, manifests, the migration notes, FORMAT_COVERAGE, documentation, pins and registry at this landing; the wheel gate and evidence at the release | PASS for this landing's part; the wheel gate NOT_RUN until the release procedure |
| 192 | reference mapper as oracle only | schemas generated from the models; the reference mapper not vendored; the proposed schemas unused; `MP::test_projection_matches_the_bundle_reference_goldens` | PASS |

### 7.1 Deviations from the specification

- **REQ003, the runtime's name.** The runtime is the distribution `synapse-link16-bridge`, imported
  as `synapse_link16_bridge`, not `sc_link16_bridge` (L-11, D-46): this repository's distributions
  are named `synapse-*`.
- **REQ010, the test module names.** `tests/test_cdm_link16_gateway_identity.py` and
  `tests/test_cdm_link16_gateway_mapping.py` carry the repository's `test_cdm_` prefix (L-15).
- **REQ012, the version.** CDM 3.1.0, a MINOR, not 4.0.0 (L-02): the migration notes' rule table
  and VERSIONING.md §3.2 class an added enum member as a MINOR, and a 3.0.0-only consumer is served
  by the compatibility projection.
- **REQ071, missing scope.** A missing `origin_scope` is `SCHEMA_INVALID` at the adapter, where the
  schema requires the key; `IDENTITY_SCOPE_UNRESOLVED` is the runtime's code for a scope it has not
  approved (D-24).
- **REQ081, `source.system`.** The one token `SC_LINK16_GATEWAY`, because `--list-adapters` prints
  whitespace-separated columns (L-04); `format_name` keeps `SC Link16 Gateway`.
- **REQ082 and D-20, the feet transformation.** Recorded only when a converted height reached an
  emitted position; the reference mapper records it under the compatibility projection's omission
  too.
- **REQ084 against `Position.vertical`.** The specification is followed, and the description of
  `Position.vertical` ("never converted") is contradicted for HAE in feet; stated on the
  documentation page and in the manifest's limitation `hae-feet-converted` (L-09).
- **REQ085, the wording.** Every leaf is covered, but three projections the ledger grammar cannot
  state are asserted by the tests instead of declared (L-08), and the compatibility projection is
  outside the ledger (D-19).
- **The reference mapper's leniency.** Section 8.
- **I03, the operator release.** Besides a provider report at a higher incarnation, an audited
  operator command releases a quarantined reuse; the specification says "await provider
  resolution" (D-31). Realised in the bridge.
- **REQ105, the reporting-authority half.** Notices carry no reporter, so the authority half of a
  drop cannot be checked: not-claimed (D-31). Realised in the bridge.
- **The cursor's "inclusive contents after".** Read as strictly after the committed cursor (D-31).
  Realised in the bridge.
- **The configuration's `cdm_schema_version` default.** The specification's 4.0.0 target is 3.1.0
  here, and the list is explicit (L-02). Realised in the bridge.

## 8. Where the adapter is stricter than the reference mapper

Each with a negative fixture under `pkg/fixtures/link16_gateway/malformed/` and a test (L-10, D-17,
D-18, D-20, D-24):

| Point | Reference mapper | Adapter | Fixture |
|---|---|---|---|
| component timestamps | compared as text after the pattern; a leap second or hour 24 passes | every timestamp built on a strict calendar | `second_60_component.json`, `hour_24_component.json` |
| envelope timestamps | parsed with a calendar that admits second 60 and 61 | strict calendar | `second_60_effective_at.json`, `february_30.json` |
| `\d` in the schema's patterns | any Unicode decimal digit | ECMA-262's `[0-9]` | `non_ascii_digit_timestamp.json` |
| a timestamp's wrong shape | `SCHEMA_INVALID` | `TIME_UNRESOLVED` (D-17) | `timestamp_without_milliseconds.json` |
| `$` in identifier patterns | admits a final newline | ECMA-262's end anchor | `identifier_trailing_newline.json` |
| UUID case | upper case accepted | canonical lowercase only | `uppercase_record_id.json` |
| numbers | an inexact integer and a non-zero underflow pass | `JSON_INVALID` (D-18) | `integer_not_double_exact.bin`, `number_underflow.bin`, `number_overflow.bin` |
| the feet transformation | recorded under the compatibility omission | only when emitted (D-20) | `MP::test_transformations_exact_strings_and_order` |
| missing `origin_scope` | the code of the specification's prose | `SCHEMA_INVALID` (D-24) | `missing_origin_scope.json` |

## 9. The native boundary and its unblock procedure

The native rows (N01 to N06, G03) and every native half of a requirement are
BLOCKED_EXTERNAL_EVIDENCE. The specification's section 18 is the unblock procedure; each gate has
an owner and a concrete output, and none can be met from this repository:

| Gate | Owner | Output it requires |
|---|---|---|
| N01 standards access | standards owner | the authorised editions of the selected standards, with their change sets and digests |
| N02 peer agreement | integration lead | addresses, ports, roles, modes, participant identities, transport options, network scope and message coverage |
| N03 transport binding | codec engineer | clause-referenced frame and session tables with every counter, timer and error rule |
| N04 payload binding | codec engineer | clause-referenced field and word tables for every selected form, unavailable codes included |
| N05 mapping | data model owner | a reviewed dictionary from native fields to the gateway's semantics |
| N06 forwarding | gateway owner | the forwarding rules, or an explicit no-forwarding boundary and authority statement |
| N07 test oracle | verification lead | independent authorised byte vectors with decoded values and negative cases |
| N08 interoperability | verification lead and peer operator | a witnessed bidirectional track exchange log with exact profiles and families |
| N09 release evidence | release owner | the provider's digests, tests, limits, unresolved deviations and approved wording |

The bridge's native boundary refuses activation with `BLOCKED_EXTERNAL_EVIDENCE` when no provider
is set and with `NATIVE_PROFILE_INCOMPLETE` when a pin record is incomplete, and never falls back
(L-12).

## 10. Fixtures and measurements

**Fixtures** (L-14): 15 harness fixtures — the handoff's six reports byte-identical, seven synthetic
reports written for the adapter (HAE metres, HAE feet on GNSS, BARO, AGL, a reference of UNKNOWN,
the Unicode and uint64 report, the south pole on the antimeridian), and two octet twins — with 15
goldens, the handoff's six reference projections under `reference/`, 32 refused reports under
`malformed/` (20 `.json`, 12 `.bin`), three `PROVENANCE.json` records, the fixture README and the
pin record: 73 files. Over 1 MiB and deeper than 64 are generated by the tests and the suite, never
committed.

**Measurements**, counts only, each read with the command named on the landing's tree (the arc's
A1 tree, after its final review's fix round), 2026-10-10; every figure below was re-read there:

| Reading | Command | Result |
|---|---|---|
| harness | `python -m synapse_cdm.harness --adapter link16_gateway --schemas schemas` | `15 passed, 0 failed` |
| conformance suite | `python -m synapse_cdm.suite conformance run --adapter link16_gateway --schemas schemas --format json` | `CONFORMANT`, eligible L5 (L4 declared); A, B, C, F 15 of 15; D and E 13 pass and 2 skip (the octet twins); G 15 compared; H 32 of 32 refused by the adapter; I and M declared inapplicable; J 115 timestamps; K 43 identifiers; L 29 objects; N 2 byte fixtures, 2657 offsets, 0 crashed; O 1 048 577 octets fed, `InputTooLarge` |
| preservation ledger | the same run's ledger | 18 declared mappings over 13 JSON fixtures: MAPPED 174, RESIDUAL 319, DECLARED_LIMITATION 0, LOST 0 |
| the roster row | `python -m synapse_cdm.harness --list-adapters` | `link16_gateway  1.0.0    bidirectional  link16_gateway  SC_LINK16_GATEWAY  provisional-internal-profile` |
| the adapter's tests | `python -m pytest -q tests/test_cdm_link16_gateway_adapter.py` | `198 passed` |
| identity tests | `python -m pytest -q tests/test_cdm_link16_gateway_identity.py` | `35 passed` |
| mapping tests | `python -m pytest -q tests/test_cdm_link16_gateway_mapping.py` | `90 passed` |
| the bump gate | `python gates/bump_derivation.py --json` | pending `MINOR`, `3.4.0`, unruled `[]` |
| the ordinals widening (L-03) | `tests/test_cdm_ordinals.py` in a throwaway copy of the A1 tree, one mutation at a time | baseline `109 passed, 1 skipped` (one more case than the adapter round's 108: the bound site that the migration notes' landing paragraph adds for row 23); a stale pairing at #22 in FORMAT_COVERAGE.md or RELEASE_NOTES.md fails the bound-site test; a duplicate row fails `test_the_table_is_a_bijection`; a renamed row fails `test_the_shipped_rows_are_exactly_the_registered_adapters`; a hyphenated name is a collection error; a repeated ordinal number is not caught, before the widening as after it |
| the DIS 7 entity pin | one byte of `tests/frozen/cdm/3.0.0/entity.schema.json` changed in a scratch copy | the renamed pin test fails, and two digest tests of `tests/test_cdm_version_matrix.py` fail independently |
| secrets scan | gitleaks 8.30.1 with the repository's configuration over the fixture directory, `schemas/link16_gateway/`, the adapter module and its test module | `no leaks found` |

## 11. Open items

- **Version-pending facts (D-09).** Until the release commit types 3.1.0: the files under
  `schemas/` say 3.0.0 while holding the two members; the adapter's default projection stamps
  `3.0.0` on SENSOR and UNKNOWN objects, which the frozen 3.0.0 contract refuses; and
  `cdm_schema=SCHEMA_VERSION` selects the compatibility projection. The branch is not fast-forwarded
  to `main` before the release commit.
- **D-43, a host finding.** `times.parse` and `times.parse_wire` accept hour 24 on Python 3.14 and
  refuse it on 3.12, because `datetime.fromisoformat` changed. The adapter does not use them for
  its strict calendar. Not changed in this arc; reported to the maintainer as a separate task.
- **Amendment 6, an ordinals gap.** `tests/test_cdm_ordinals.py` does not catch a repeated ordinal
  number, before L-03's widening as after it. Offered to the maintainer as a separate decision.
- **The native rows.** BLOCKED_EXTERNAL_EVIDENCE until gates N01 to N09 (section 9).
- **F01.** NOT_RUN until the maintainer runs the bridge's measurement harness on the named rig.
- **REQ180's `IMPLEMENTED`.** Not available to a registered adapter beside a provisional binding;
  `PROVISIONAL` is declared (L-05).
- **The runtime rows.** NOT_RUN at this landing; dispositioned in the bridge's requirement matrix
  and in this record when the bridge lands.
- **A host open item, the cyclic dict (verified 2026-10-10).** The host's
  `synapse_cdm.adapter.container_depth` walks a dict with a stack and keeps no record of what it
  has visited, so on a dict that contains itself it never returns. Probed under a three-second
  alarm: `container_depth` itself, this adapter's `to_cdm` and the GeoJSON adapter's `to_cdm`
  (both stop in the base class's depth guard, which calls it), and an `ExportContext` built with a
  cyclic `provenance` or `source_fields` (stopped at the same call) each ran until the alarm. Only
  an in-process caller can build such a dict, since octets and JSON text cannot form a cycle, and
  every adapter that takes a parsed dict shares the behaviour. Not changed in this arc; reported to
  the maintainer as a host open item.

## 12. Changes

- **2026-10-10, the adapter landing.** Written with the adapter, its fixtures and tests, the CDM
  3.1.0 members, the documentation page and the migration notes' landing paragraphs. Three review
  findings on the adapter were fixed before the landing: `ExportContext.provenance` is bounded at
  depth 29 and `source_fields` at depth 31, where each lands in an emitted report, each object alone
  at most 10 000 nodes and 1 048 576 octets, with the two together still checked by the export's
  self-check
  (`AD::test_export_context_objects_are_bounded_where_they_land_and_together_at_export`); a Track's
  `track_quality` is shown to give an `OMITTED` loss (`AD::test_a_track_quality_is_an_omitted_loss`,
  so named since the fix round below); and `detect` is shown to refuse octets of a JSON object
  without the profile (`AD::test_detect_and_validate_source`).
- **2026-10-10, the landing's final review, fixed before the landing.** One major and eight minor
  findings were closed. Two change export: `quality_code` is now written from the Entity's
  `Quality.source_quality`, the specification's section 9 row read backwards, where it had been
  null with a loss whose rule ("the contract has no field for it") was untrue — null when the
  Entity states no grade, `VALUE_NOT_REPRESENTABLE` with a loss record when the grade is not 1 to
  128 characters of Unicode scalar values, and a Track's differing grade an `OMITTED` loss
  (`AD::test_export_writes_quality_code_from_source_quality`,
  `AD::test_export_refuses_a_grade_quality_code_cannot_hold`,
  `AD::test_a_track_grade_is_carried_only_when_it_is_the_entity_s`); and a non-finite number the
  export would write is refused as `VALUE_NOT_REPRESENTABLE` at its own path with a loss record,
  where it had reached the self-check as `JSON_INVALID` with an empty loss record
  (`AD::test_export_refuses_a_non_finite_number_at_its_path`). Each of those tests failed on the
  tree before the fix. `AD::test_export_never_reads_a_residual_or_a_clock` now plants all 28 report
  fields in the residual, each with a value the Entity and the export context do not hold, and
  asserts that no emitted field equals its plant, so a residual read of any field fails it,
  `identity_code` (which it could not see before) and, since the review of that fix on
  2026-10-11, the profile constant and the five fields the context supplies (`profile`, `tenant`,
  `incarnation`, `native_profile`, `domain`, `synthetic`) among them. The rest are wording: the package README's export clause, the
  `max_depth` basis (64 is the figure most JSON-reading adapters declare; `geojson` declares 128),
  the documentation page's list of deviations, and the measurements of section 10, re-read on the
  landing's tree.
