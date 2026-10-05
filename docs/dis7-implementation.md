# DIS 7 adapter — implementation record

This record is the implementation record for the DIS 7 adapter, kept as the work proceeds rather than written after the fact. The contract is the handoff specification identified as `SC DIS7 SPEC 001 v1.0`; it is a handoff document and is not in this repository, and wherever this record says "spec" or cites a specification section or line, it means that document. The work is done in pipeline runs R02 to R28, R30 and R31 (R26, R27, R28 and R30 being the sessions of the follow-up unit WP7, which settles the final review's minor findings and then the review of that settlement; R29 is the release gates' check script on the staged tree and has no session; R31 is the one session of WP8, the release preparation on the arc that lands the F-39 fix under the maintainer's approved bump ruling and clears the docs audit), whose prompts, logs and reports live in a run directory outside the repository. Decisions D1 to D46 and the Frozen contract section quote the plan this pipeline follows and its rulings file; neither is in this repository. In the quoted text `§4.3`, `§4.4`, `§4.5`, `§4.8`, `§4.10` and `§10`, and anything written `PLAN.md §n`, are sections of the plan this pipeline follows: its §4.3, §4.4, §4.5 and §4.10 are reproduced under Frozen contract (Error model and codes, Validation order and paths, Replay order, Mutation seams), its §5 is the table of D12 to D46, its §4.8 is the command-line interface that run R16 writes, and its §10 is a list of risks. `§4 field order`, `§12`, `§16` and "spec lines" refer to the handoff specification.

## Scope

One new bidirectional adapter, `dis7` (ordinal 21 in the ordinal table of FORMAT_COVERAGE.md), that turns exactly one DIS 7 Entity State PDU into exactly one CDM `Entity` and replays the original bytes from an unchanged Entity. Around it: a strict codec, a public error model with 18 stable codes, an offline CLI `synapse-dis7` (decode, replay, self-test, `--version`), packaged normative vectors, an independent OpenDIS check, a mutation matrix, a recorded benchmark, and promotion into the `synapse-cdm` wheel through the repository's own generators and gates.

Not claimed at any point: IEEE certification, full DIS 7 support, compatibility with any particular simulator, or L5/L6 maturity.

## Baseline

Branch `soif/dis7-1.0`, created from `main` at commit `c4bba1b6ebfdfe956f6efc2b3a81a04db2b4bb5b`.

| Command | Return code | Result |
| --- | --- | --- |
| `python -m pytest -q -rs -p no:cacheprovider` | 0 | `6679 passed, 182 skipped` |
| `python -m pytest -q -rs -p no:cacheprovider` (with the normative hooks set) | 0 | `6780 passed, 81 skipped` |
| `python -m synapse_cdm.schemas --check --out schemas` | 0 | `CURRENT: schemas vs models at 3.0.0` |
| `python -m synapse_cdm.manifests --check --out manifests` | 0 | `CURRENT` |
| `ruff check --config packages/cdm/pyproject.toml packages/cdm gates tests` | 0 | `All checks passed!` |
| `python gates/bump_derivation.py --json` | 0 | a JSON report ending `}` |
| `python gates/wheel_install.py --mutation-check` | 0 | `mutation caught: [...] refused the fixture-less wheel, so this gate can fail` |
| `cd docs && npm run ci` | 0 | `check-built-admonitions: OK` — 20 directives, 20 admonitions, 0 literal `:::` |

## Source pins

| Source | Identity |
| --- | --- |
| Handoff bundle | `SC DIS7 SPEC 001 v1.0`, dated 2026-10-03, 52 files; `MANIFEST.json` sha256 `3d6c04b4c02f4609625a57c5cfc965aae8d4b5c74ab39e5a0ad0a539e565c5b2` |
| `SPECIFICATION.txt` (MANIFEST row) | sha256 `24e8a7ee0b6907581a76ecce7d43c3e8d1df7cc91aed5b845b544c35ebc3db0a` |
| `acceptance-cases.json` (MANIFEST row) | sha256 `fc894f435ddb7c31fb8f22ecf001a50ebc668b8fc46b5df75305e35807d8881c` |
| `requirements.json` (MANIFEST row) | sha256 `f99821836b1acec262db67e35b75d6bf3e88ddaccf7f551740703a6af2b97cf8`; not tracked (D8) |
| Vendored vectors and contract files | pinned file by file in `fixtures/dis7/spec/dis7_pin.json` |
| OpenDIS | https://github.com/open-dis/open-dis-python at commit `732b6655bb47e34ccc73722eefe0f4706fd0032f`, BSD-2-Clause; a test-time reference, never a runtime dependency, never copied from |

The evidence record generated for `dis7` (`python -m synapse_cdm.evidence generate --all`) hashes every file under `fixtures/dis7/` that `evidence.measured_files` returns: every file except dotfiles, any file named `README.md` or `PROVENANCE.json` in any of its directories, and anything under `spec/`. Its `fixture_hashes` lists 39 files: the six top-level fixtures (three `.dis` payloads and their three `.parsed.json` envelopes), the six goldens, the five malformed payloads, and the 22 vendored files under `vectors/` (16) and `contract/` (6). The evidence record therefore lists the vendored files as fixture files although neither the harness nor the conformance suite reads them; their pins against the bundle MANIFEST live only in `spec/dis7_pin.json`.

## Version register

| Item | Value |
| --- | --- |
| IEEE edition | IEEE 1278.1-2012 (DIS 7), Entity State subset; the IEEE text was not consulted, the layout authority is open-dis-python at the pin. |
| OpenDIS commit | `732b6655bb47e34ccc73722eefe0f4706fd0032f`. |
| Repository commit | `c4bba1b6ebfdfe956f6efc2b3a81a04db2b4bb5b`. |
| Package version | 3.1.1. |
| CDM schema version | 3.0.0. |
| Adapter API version | 3.0.0 at the baseline; 3.1.0 from run R05. |
| Adapter version | 1.0.0. |
| Specification id | `SC DIS7 SPEC 001`, version 1.0; bundle `MANIFEST.json` sha256 `3d6c04b4c02f4609625a57c5cfc965aae8d4b5c74ab39e5a0ad0a539e565c5b2`. |
| Reference reading: Python | 3.14.7 (`tool_versions`, run R17). |
| Reference reading: platform tag | `macosx-26.0-arm64`. |
| Reference reading: git | `git version 2.50.1 (Apple Git-155)`. |
| Reference reading: OpenDIS | `1.1.0a4@732b6655bb47e34ccc73722eefe0f4706fd0032f`. |

## Decisions

Each decision: what, why, alternatives, covering tests. Decisions added by later runs start at D47.

### D1 — F1: How generic SDK construction supplies DIS7's required context

- **What.** Add `Adapter.fixture_instance(clock=None, *, synthetic=True)` (default `cls(clock=clock, synthetic=synthetic)`, placed after `encode()`); route the seven package sites and eleven test sites through it; `Dis7Adapter` overrides it with `session="unnamed"` and the packaged fixtures' `TimeContext` and refuses `synthetic=False`; `harness.main`, `suite.main` and `evidence.main` refuse a caller-supplied `--fixtures` for a shipped adapter that overrides the hook; a refusal raised by an overridden hook is reported as exit 2 (a `ValueError` from any other adapter's constructor propagates as before); `ADAPTER_API_VERSION` 3.0.0 → 3.1.0.
- **Why.** Maintainer ruling, approved in the pipeline's rulings file.
- **Alternatives.** Document-only: keep the directory unrestricted and state the limitation. Lighter, but leaves a default context reachable against R05/R06/R11
- **Covering tests.** Pending; implemented by R03, R04, R05, R12, R13, R15, R17, R22.

### D2 — F2: Where the CLI lives

- **What.** `packages/cdm/synapse_cdm/dis7_host.py` inside the package, hashing through a new bytes-level helper in `evidence.py`. A host source hash is within `evidence.py`'s allowed uses ("deterministic content addressing"), and a separate module satisfies the "separate host CLI" requirement.
- **Why.** Maintainer ruling, approved in the pipeline's rulings file.
- **Alternatives.** (A) Sibling package `packages/cdm/synapse_dis7/` in the same wheel: the most literal reading of R04, but about ten touched files, two new gate-like tests and corrections to three published statements, because five existing gates cannot see a second package and a sixth (`test_cdm_version_floor`) goes red the moment it exists, in WP4. (C) Widen `CRYPTO_ALLOWANCE`: contradicts case A11
- **Covering tests.** Pending; implemented by R03, R05, R11, R16, R20, R22.

### D3 — F3: Declared maturity, claim and licence class

- **What.** L4 + VERIFIED + LICENSED, with the limitations listed in PLAN.md §3 F3. L5/L6, `external_exercise` and `normative-verified` are not declared.
- **Why.** Maintainer ruling, approved in the pipeline's rulings file.
- **Alternatives.** Weakening `tests/test_cdm_manifests.py` to admit L3/IMPLEMENTED
- **Covering tests.** Pending; implemented by R12, R17, R20, R22.

### D4 — F4: Contract resolutions

- **What.** CR-01…CR-35 in PLAN.md §5 are the frozen contract. Bundle schemas ship byte-identical; each resolution is logged as a contract defect in the delivery report.
- **Why.** Maintainer ruling, approved in the pipeline's rulings file.
- **Alternatives.** Amend the bundle (a spec revision; see §10)
- **Covering tests.** Pending; implemented by every run from R03.

### D5 — F5: Execution and commit model

- **What.** Worktree `~/synapsecommand-public-dis7`, branch `soif/dis7-1.0` from `c4bba1b6`. Sessions stage by explicit path and never commit. The maintainer commits WP1a, WP1b, WP2, WP3 with `bash run.sh commit <unit>`; WP4–WP6 land as one commit after the final review. One push at the end.
- **Why.** Maintainer ruling, approved in the pipeline's rulings file.
- **Alternatives.** Keep the adapter class outside the distribution (loaded as `module:ClassName`) until WP6 and commit every WP green. Costs an import-path flip and delays roster-wide behavioural feedback to WP6
- **Covering tests.** Pending; implemented by the driver (run.sh gates); the commit drafts of R03, R06, R08, R10, R22; R12, R20, R21.

### D6 — F6: OpenDIS checkout

- **What.** Clone the pin `732b6655bb47e34ccc73722eefe0f4706fd0032f` to `~/synapsecommand-normative/open-dis-python`, exposed through `SYNAPSE_CDM_OPENDIS_DIR`. CI has no such hook; the live reference test reads BLOCKED there and is reported as unavailable.
- **Why.** Maintainer ruling, approved in the pipeline's rulings file.
- **Alternatives.** `/tmp/open-dis-python`; or a CI clone step
- **Covering tests.** Pending; implemented by preflight, R17, R22, R23, postcommit, R25.

### D7 — F7: SDK defects found on the way

- **What.** (a) Fix `times.render` to format the year as four digits, in this arc. (b) File the `container_depth` cyclic-input hang and the `evidence.generate(fixtures=DIR)` ValueError as separate defects, not fixed here.
- **Why.** Maintainer ruling, approved in the pipeline's rulings file.
- **Alternatives.** (a) Ask the spec owner to narrow the year range. (b) Fix them in this arc
- **Covering tests.** Pending; implemented by R04, R05, R09, R15, R22.

### D8 — F8: Which bundle files are tracked, and how the specification is cited

- **What.** Track the vectors, five schemas and `acceptance-cases.json`. Do not track `SPECIFICATION.*` or `requirements.json`. Tracked files cite case ids and schema names; any other reference says once per file that the specification is a handoff document identified by `SC DIS7 SPEC 001 v1.0` and is not in the repository.
- **Why.** Maintainer ruling, approved in the pipeline's rulings file.
- **Alternatives.** Track the specification under `spec/dis7/`
- **Covering tests.** Pending; implemented by R02, R03, and the text rules of every run.

### D9 — F9: Baseline movement

- **What.** Branch from `c4bba1b6` now. If Dependabot #7/#8 land first, rebase once before the final commit and record the later baseline with its test results.
- **Why.** Maintainer ruling, approved in the pipeline's rulings file.
- **Alternatives.** Land the PRs first and re-pin
- **Covering tests.** Pending; implemented by preflight, R23.

### D10 — F10: Bump rulings

- **What.** The maintainer supplies the `**Bump ruling.**` text. Run R05 writes proposals to `maintainer/bump-wp1b.proposed.md`; the maintainer edits and saves them as `maintainer/bump-wp1b.approved.md`; run R06 pastes them into MIGRATIONS.md verbatim. Any later run that finds an unruled unit stops and writes a proposal the same way.
- **Why.** Maintainer ruling, approved in the pipeline's rulings file.
- **Alternatives.** —
- **Covering tests.** Pending; implemented by R04, R05, R06, R16, R19, R21, R22, R23.

### D11 — F11: Version identity of the handover wheel

- **What.** Hand over an unreleased build from the final commit, reporting package 3.1.1 and saying so. The bump to 3.2.0, the `evidence.available` flip, tag and publish stay in a separate release round.
- **Why.** Maintainer ruling, approved in the pipeline's rulings file.
- **Alternatives.** Rule the bump into WP6
- **Covering tests.** Pending; implemented by R12, R16, R20, R22, R23, R25.

### D12 to D46 — contract resolutions CR-01 to CR-35

| Decision | CR | Issue | Resolution |
| --- | --- | --- | --- |
| D12 | CR-01 | Schema instant regex accepts `:60`, Feb 30, hour 24, year 0000, offset `+24:00` | Prose wins; enforced in `TimeContext`; schema shipped unchanged |
| D13 | CR-02 | Residual schema accepts an unnormalised stored instant | Replay requires the normalised form → `E_REPLAY_PROVENANCE` |
| D14 | CR-03 | Malformed envelope instant/basis: structural or `E_CONTEXT_TIME` | Wrong JSON type or missing key → `E_TWIN_SCHEMA` (stage 2); a string with a bad value → `E_CONTEXT_TIME` (stage 8) |
| D15 | CR-04 | `encode_pdu` code split (table vs case N10) | Keys, types, array sizes, record count, hex width → `E_TWIN_SCHEMA`; header constants → `E_HEADER_UNSUPPORTED`; length vs records → `E_LENGTH_MISMATCH`; NaN/inf → `E_NONFINITE`; integer range, hex characters, float32 representability → `E_VALUE_RANGE` |
| D16 | CR-05 | Envelope twin value classes | Constants, out-of-range integers, hex width or syntax, `wire_hex` outside 288–8448 characters, non-finite numbers → `E_TWIN_SCHEMA` at stage 2 |
| D17 | CR-06 | Integral floats for integer fields (`7.0`) | Accepted in twins and `encode_pdu`, following the schema; booleans refused |
| D18 | CR-07 | Basis `\S` depends on the regex engine | Whitespace defined as an enumerated code-point set; tests for U+001C, U+0085, U+00A0, U+FEFF |
| D19 | CR-08 | Context schema requires `time_context`; constructor makes it optional | Constructor optional (prose); the schema describes vector context files |
| D20 | CR-09 | No code for "final CDM validity" | `E_PROJECTION` at `$` |
| D21 | CR-10 | Omitted keyword-only argument raises `TypeError` | Sentinel defaults raise `Dis7Error` |
| D22 | CR-11 | No API named for envelope text, yet N18 and N20 need one | Public `parse_json_text` (§4.8); unparseable JSON → `E_TWIN_SCHEMA` at `$` |
| D23 | CR-12 | Oversize `str` to `to_cdm` | `E_INPUT_LIMIT` (forced by `tests/test_cdm_resource_envelope.py:121-131`); in-bounds `str` → `E_INPUT_TYPE`. Departs from §12's type-then-bounds order for `str` only |
| D24 | CR-13 | Path strings unspecified beyond two conventions | §4.4, frozen |
| D25 | CR-14 | N15 vs the code table on "time" | `valid_from`/`valid_to` → `E_REPLAY_CHANGED`; `source.observed_at` and stored time context → `E_REPLAY_PROVENANCE` |
| D26 | CR-15 | Non-list replay input; undecodable or edited `wire_hex`/`residual.pdu` | `E_REPLAY_SHAPE` at `$`; `E_REPLAY_CHANGED` |
| D27 | CR-16 | Null vs absent on replay | Unobservable on model instances. At the CLI JSON boundary a non-canonical document (absent member, non-canonical spelling) → `E_REPLAY_SHAPE` |
| D28 | CR-17 | CLI `replay` has no session or classification flags | Bound from the stored residual, so the match is by construction; optional flags, when given, are asserted. Single-copy edits are still caught through `source_ids` and `source.synthetic` |
| D29 | CR-18 | CLI exit classes; CLI output vs null-hash goldens | §4.8. CLI decode always carries a hash, so self-test compares the API's null-hash output |
| D30 | CR-19 | A03 "stated longitudes and heights" appear nowhere normative | Chosen and recorded: (0, 180, 35 786 000), (49, 16, 400), (−45, −179.5, 12 000), (89.999, 34, −100), (−90, 0, 0), plus exact `[0, 0, ±b]` for the pole branch |
| D31 | CR-20 | A09 and A14 cannot be exercised on the named seed | A09 uses `north_pole_stationary`; mutation killers per §4.10 |
| D32 | CR-21 | `fixture_instance` supplies a context without the caller passing it | Contract deviation, restricted per F1, stated as a manifest limitation |
| D33 | CR-22 | Spec lines 219 and 221 order replay checks differently | §4.5 order; multi-defect tests at wire bytes 1, 17 and 88 |
| D34 | CR-23 | "RFC 3339" prose permits lowercase `t`/`z`; the schema refuses them | Refused, with the space separator |
| D35 | CR-24 | `-00:00` offset | Accepted, normalised to `Z` |
| D36 | CR-25 | `residual.namespace` ≠ `DIS`; meaning of "Source namespace" in the code table | `E_REPLAY_SHAPE`; "Source namespace" is the scoped identity system in `source_ids` → `E_REPLAY_PROVENANCE` |
| D37 | CR-26 | How much of the residual schema is the replay shape gate | All of it; CR-15 applies only to schema-valid hex |
| D38 | CR-27 | Duplicate key or unparseable JSON in replay's `entity.json` | `E_REPLAY_SHAPE` |
| D39 | CR-28 | `detect(envelope)` | True only for exactly the three keys and a 7/1/1 header by guarded lookups; False for cyclic, empty, unrelated or over-size input; never raises |
| D40 | CR-29 | Native twin types | `list` and `tuple` for arrays, `dict` only for objects, plain `int`/`float`; `time_context` as `TimeContext` only; `source_hash` as a plain dict; a memoryview of any item size is its underlying octets |
| D41 | CR-30 | The note for position-present with a non-world algorithm appears in no vector | Asserted literally for algorithms 0, 1, 6, 9, 255; all four note shapes tested |
| D42 | CR-31 | `validate_source` format | Exactly one `"CODE at PATH: message"` string; the SDK default's type-name prefix is overridden |
| D43 | CR-32 | Years below 1000 in `valid_from`/`observed_at` | F7(a) |
| D44 | CR-33 | A12's evidence | The wheel gate's clean-venv run, not the in-tree CLI test |
| D45 | CR-34 | Self-test and wheel report package 3.1.1 although the tag has no dis7 | F11 |
| D46 | CR-35 | Is a location written with negative zeros "the exact zero vector"? | Yes, compared by value: position and kinematics null, the zero-vector note, sign bits kept in residual and replay; never `E_POSITION_DOMAIN` |

Bundle schemas ship byte-identical; each resolution is logged as a contract defect in the delivery report (D4).

### D47 — Quoting the `manifests --check` and `bump_derivation.py --json` baseline readings

- **What.** In the Baseline table, the `manifests --check` row quotes only the word `CURRENT`, and the `bump_derivation.py --json` row quotes only the closing `}` of its output, rather than the full result line each command printed.
- **Why.** The full `manifests --check` line ends in a roster-count phrase that trips the roster-count sweep (`tests/test_cdm_prose_counts.py`, `ROSTER_COUNT`) the moment it is quoted whole in a tracked file; `CURRENT` is the word this run's own text rules name as the safe quote for that gate's result. `reports/baseline.md`'s `bump` block shows no summary line, only the tail of a JSON object, so there is nothing else in the block to quote.
- **Alternatives.** Paraphrase the result instead of quoting it; rejected because the run file requires a quote from the block, not a paraphrase.
- **Covering tests.** `tests/test_cdm_prose_counts.py` (`ROSTER_COUNT`) over `docs/dis7-implementation.md`.

### D48 — One refusal rule for a caller-supplied `--fixtures`, read by the three entry points

- **What.** `harness.fixtures_refused_message(reference, adapter_class)` is the one rule and the one text: it returns a refusal only for an adapter this package ships that overrides `Adapter.fixture_instance`, and `None` otherwise. `harness.main`, `suite.main` and `evidence.main` read it when `--fixtures` is given and exit 2 behind their own name; `harness.run`, `suite.run` and `evidence.generate` are not restricted.
- **Why.** F1: an override supplies the context of the packaged fixtures, and replaying a caller's directory under it would stamp that context onto other payloads. An adapter outside the package has no packaged fixtures, so `--fixtures` stays required for it and is never refused. One function keeps the three command lines from drifting apart, on the precedent of `fixtures_required_message`.
- **Alternatives.** A refusal inside `run`/`generate` (rejected: F1 keeps the API unrestricted); three spellings of the rule, one per command line (rejected: three texts to keep in step).
- **Covering tests.** `test_a_cli_refuses_caller_fixtures_for_a_shipped_adapter_that_overrides_the_hook`, `test_the_refusal_is_for_shipped_overriding_adapters_only`, `test_the_api_is_not_restricted_by_the_cli_refusal` in `tests/test_cdm_fixture_instance.py`.

### D49 — A `ValueError` from the hook is a usage error only for a class that overrides it

- **What.** `harness.main`, `suite.main` and `suite._sweep` catch a `ValueError` raised while building the adapter through the hook, and turn it into exit 2 only when `harness.overrides_fixture_instance(adapter_class)` is true; otherwise they re-raise.
- **Why.** The default hook is the plain constructor call, so its `ValueError` is the constructor's own. An existing constructor's error (the `stanag4676` adapter under its normative environment raises `NormativeBindingBlocked`) must leave `main` as a raised exception exactly as at the baseline; only an override refuses on its own account.
- **Alternatives.** Catching every `ValueError` around the hook (rejected: it would change the behaviour `tests/test_cdm_stanag4676_binding.py` relies on).
- **Covering tests.** `test_a_refusal_raised_by_the_hook_is_exit_2`, `test_a_constructor_error_without_an_override_still_propagates` in `tests/test_cdm_fixture_instance.py`.

### D50 — A hook refusal under `--all` leaves that adapter out and the sweep exits 2

- **What.** In `suite._sweep` a refusal raised by an overriding hook is printed as `synapse conformance: <name>: <message>`, the adapter gets no entry in the document, the remaining adapters are still run and printed, and the sweep returns `EXIT_USAGE` (2) instead of the worst verdict.
- **Why.** F1: "an `--all` sweep continues". A refused adapter has no report, so the document cannot carry one for it, and exit 2 keeps the invocation error from reading as a verdict.
- **Alternatives.** Aborting the sweep at the first refusal, as it does for `NoFixturesFound` (rejected: F1 asks it to continue); recording a FAIL row for the refused adapter (rejected: no checks ran, so a row would claim a judgement that did not happen).
- **Covering tests.** `test_a_hook_refusal_fails_one_row_and_the_sweep_continues` in `tests/test_cdm_fixture_instance.py`.

### D51 — digest_bytes takes bytes only

- **What.** `evidence.digest_bytes` accepts `bytes` only and raises `TypeError` otherwise.
- **Why.** A `memoryview` of wider items would report a length that is not its octet count.
- **Alternatives.** Accept any bytes-like object.
- **Covering tests.** `tests/test_cdm_evidence_categories.py::test_digest_bytes_refuses_anything_that_is_not_bytes`.

### D52 — `decode_pdu` refuses text of any length as a type error

- **What.** `decode_pdu` given a `str`, whatever its length, raises `E_INPUT_TYPE` at `$`. The oversize-text rule of CR-12 (`E_INPUT_LIMIT` for a `str` over the bound) is applied by the coded guard of the adapter class before the codec is called, not by the codec.
- **Why.** The codec reads octets only and has no text bound of its own; CR-12 is a rule about what `to_cdm` accepts, so it lives where `to_cdm` is guarded, and the codec keeps one plain type-then-bounds order.
- **Alternatives.** Measuring a `str` by its UTF-8 length inside the codec (rejected: it would put a second copy of the guard's text rule in the codec and make the codec's order depart from the contract order for one type).
- **Covering tests.** `test_non_bytes_input_is_e_input_type_at_the_root` (ids `short_text` and `long_text`) in `tests/test_cdm_dis7_codec.py`.

### D53 — The header predicate has no upper size bound

- **What.** `looks_like_entity_state` returns True for any byte sequence of at least 12 octets whose octets 0, 2 and 3 are 7, 1 and 1, whatever its length; the over-size rule of CR-28 is added by `detect`.
- **Why.** The predicate judges the header triplet alone, neither the length nor the record count, so `detect` can combine it with its own bounds and so it never raises.
- **Alternatives.** Folding the 4224-octet bound into the predicate (rejected: `detect` owns CR-28, and a second bound here would be a second place to keep in step).
- **Covering tests.** `test_r07_header_predicate_matrix` (id `triplet_5000`) in `tests/test_cdm_dis7_codec.py`.

### D54 — A released memoryview is a type error at the root

- **What.** `decode_pdu` given a released `memoryview` raises `E_INPUT_TYPE` at `$`: the size read through `memoryview(raw).nbytes` and the one `bytes(raw)` conversion after it each run inside a handler for any `Exception`, which re-raises a `Dis7Error` (the handler was narrower until R26, D93). `looks_like_entity_state` returns False for it.
- **Why.** The view is bytes-like by type but no octets can be read from it, so no later stage applies; a plain `ValueError` would leak a foreign exception.
- **Alternatives.** Letting the `ValueError` through (rejected: nothing but a `Dis7Error` may leave `decode_pdu`); `E_LENGTH_MISMATCH` at `byte[0]` (rejected: the input was never measured).
- **Covering tests.** `test_released_memoryview_is_e_input_type_at_the_root` and `test_r07_header_predicate_matrix` (id `released_memoryview`) in `tests/test_cdm_dis7_codec.py`.

### D55 — The paths `encode_pdu` reports

- **What.** `encode_pdu` reports `$` for an argument that is not a dict and for an unknown top-level member, the member's own path for a missing member (`force_id`, `header.length`), `header` for an unknown header member, the field name for a wrong container (`entity_id`, `variable_parameters_hex`) and `<field>[i]` for an element (`velocity_mps[1]`, `variable_parameters_hex[0]`). At the root and in `header` a missing member is reported before an unknown one, and the message of an unknown-member refusal never repeats the foreign key.
- **Why.** Bare field paths are the frozen form for the encoder; reporting the parent for an unknown member keeps a caller-supplied key out of the diagnostic, and judging a container before its elements gives one path per defect.
- **Alternatives.** Naming the unknown key in the path (rejected: a diagnostic must not echo arbitrary source strings); `pdu.`-prefixed paths as in the envelope (rejected: that is the adapter's stage 2, not the codec's).
- **Covering tests.** `test_encode_structure_defects_are_twin_schema_at_the_member`, `test_t03_n10_256_records_are_refused_as_twin_schema` and `test_encode_reports_defects_in_the_frozen_stage_order` in `tests/test_cdm_dis7_codec.py`.

### D56 — The types `encode_pdu` accepts

- **What.** An integer field takes a plain `int` or a finite integral `float` (`7.0`); a boolean, a string, `None` or `7.5` is `E_TWIN_SCHEMA`. A vector component takes a plain `int` or `float`; a non-finite float is `E_NONFINITE` and a value that does not survive a pack and unpack at its wire width is `E_VALUE_RANGE`. `header.protocol_version = 256` is `E_HEADER_UNSUPPORTED` and `header.length = 65536` is `E_LENGTH_MISMATCH`, because stages 2 and 3 come before the range stage. Every type test uses `type(v) is ...`, never `isinstance`, so a `bool` is never an integer.
- **Why.** CR-06 accepts integral floats as the schema does and refuses booleans; CR-04 fixes the stage of each class of defect, and the constants and the length are judged by their own stages before any range is.
- **Alternatives.** Refusing integral floats (rejected: CR-06); reporting `header.protocol_version = 256` as a range defect (rejected: the constant stage comes first under CR-04).
- **Covering tests.** `test_t04_integral_floats_are_accepted_for_integer_fields`, `test_t04_booleans_are_refused_for_integers_and_vector_components`, `test_encode_header_constants_are_header_unsupported`, `test_encode_length_must_equal_144_plus_16_per_record` and `test_t04_out_of_range_integers_are_refused_per_field_width` in `tests/test_cdm_dis7_codec.py`.

### D57 — CR-07: the enumerated whitespace set

- **What.** `BASIS_WHITESPACE`, a public constant of `pkg/adapters/dis7.py`, is the frozenset of these 30 code points: U+0009, U+000A, U+000B, U+000C, U+000D, U+001C, U+001D, U+001E, U+001F, U+0020, U+0085, U+00A0, U+1680, U+2000, U+2001, U+2002, U+2003, U+2004, U+2005, U+2006, U+2007, U+2008, U+2009, U+200A, U+2028, U+2029, U+202F, U+205F, U+3000 and U+FEFF. A basis made only of them is `E_CONTEXT_TIME` at `time_context.basis`; U+200B, U+180E and U+001B are not in the set. The code points are written out as `chr(0x...)`, never derived from the interpreter.
- **Why.** It is the whitespace of `str.isspace()` on CPython 3.11 to 3.14 plus U+FEFF, so a basis that passes satisfies the schemas' non-whitespace pattern under Python and under ECMA-262 alike; deriving it from `str.isspace`, a strip or a regex class would make the verdict depend on the interpreter.
- **Alternatives.** The Unicode White_Space property (25 code points; rejected: it would accept a basis made only of U+001C to U+001F or of U+FEFF, which the ECMA-262 pattern refuses); `str.isspace()` at run time (rejected: interpreter-dependent).
- **Covering tests.** `test_t09_basis_whitespace_is_the_enumerated_set` in `tests/test_cdm_dis7_time_identity.py`.

### D58 — The three-layer geodesy oracle

- **What.** `ecef_to_geodetic` is held to three always-on layers in `tests/test_cdm_dis7_geodesy.py`: analytical literals (height p - a on the equatorial plane, abs(z) - b on the axis), the forward equations of `tests/dis7_support.py` (`geodetic_to_ecef`, written with its own literals) over a 448-point grid of latitudes, longitudes and heights, and Heikkinen's closed-form inverse, which exists only in the test file, over that grid and eight raw ECEF points. Tolerances are 1e-9 degrees (longitude compared circularly) and 0.001 m; no layer takes a value or a constant from the module under test.
- **Why.** The function cannot be validated against itself, and a fixture is only as right as the conversion that made it. The grid covers the equator, both poles, mid-latitudes, the antimeridian, below the ellipsoid and high altitude inside the cap, the locations an independent check must cover; the closed form is a different method, so a shared mistake in the iteration and the forward equations still shows.
- **Alternatives.** The repository's existing single-step closed form in the legion and STANAG 4676 modules as the reference (rejected: it is 0.3 to 0.4 m off at depth and at the cap, and it is what the oracle must catch); an optional external geodesy library (rejected: no new dependency, and an optional layer would skip).
- **Covering tests.** `test_t16_oracle_analytical_literals`, `test_t16_oracle_forward_equations_over_the_grid` and `test_t16_oracle_closed_form_inverse`.

### D59 — Non-finite kinematics are `E_PROJECTION`; the algorithm byte is the caller's

- **What.** When `velocity_to_kinematics` computes a speed or a climb that is not finite it raises `E_PROJECTION` at `byte[48]`. The function takes only the velocity, the latitude and the longitude: it never reads the dead-reckoning algorithm, and the caller decides with `algorithm in dis7_codec.WORLD_ALGORITHMS` whether to call it.
- **Why.** All kinematics outputs must be finite, and stage 9 of the validation order has the one wire path `byte[48]` with the codes `E_POSITION_DOMAIN` and `E_PROJECTION`; the projection code is the one that describes a derived value that cannot be represented. Keeping the algorithm decision out of the helper leaves `WORLD_ALGORITHMS` a single mutation seam.
- **Alternatives.** `E_NONFINITE` at the velocity's octets (rejected: stage 6 already guarantees finite octets, so the overflow is a property of the projection, not of the wire); returning `None` kinematics (rejected: a silent drop of a refusal); passing the algorithm in (rejected: two places would then decide the same question).
- **Covering tests.** `test_t07_a05_non_finite_output_is_refused` and `test_t07_a05_kinematics_take_only_velocity_and_position`.

### D60 — NaN or infinity reaching `ecef_to_geodetic` is `E_POSITION_DOMAIN`

- **What.** `ecef_to_geodetic` refuses a radius that is not finite, as well as one below b/2 or above 1e9 metres, with `E_POSITION_DOMAIN` at `byte[48]`; a NaN or infinite coordinate, and a vector whose `math.hypot` overflows, therefore take this code.
- **Why.** NaN compares false against both bounds, so without the explicit finiteness test a NaN coordinate would pass the domain check and reach the iteration. The adapter's stage 6 refuses non-finite octets earlier with `E_NONFINITE`; only helper-level calls reach this branch, and the domain rule already names a non-finite radius.
- **Alternatives.** `E_NONFINITE` inside the helper (rejected: that code's paths are the component octets, which the helper does not know); `E_PROJECTION` (rejected: the domain rule names a non-finite radius explicitly).
- **Covering tests.** `test_t05_n11_refused_positions` (the NaN, infinity and overflow rows).

### D61 — Non-bytes input to the text loader is `E_INPUT_TYPE` at `$`

- **What.** `parse_json_text` refuses anything that is not `bytes` — a `str`, a `bytearray`, a `memoryview`, `None`, a dict — with `E_INPUT_TYPE` at `$`, before any other check.
- **Why.** The loader's job is to own the decoding of octets; a `str` has already been decoded by someone else, under rules the loader cannot see, and a mutable buffer can change between the checks and the decode.
- **Alternatives.** Accept `str` and skip the UTF-8 step (rejected: the byte-order mark and NUL rules would then depend on who decoded it); accept any buffer by copying it (rejected: the plan says the loader takes bytes, and a copy hides the caller's type error).
- **Covering tests.** `test_t12_text_argument_must_be_bytes`.

### D62 — Duplicate-key paths and the foreign-key rule

- **What.** A repeated key reports `E_TWIN_SCHEMA` at the path of the object that repeats it: `$` at the root, `k` and `P.k` for members, `[i]` and `P[i]` for array items. The first such object in document order wins, an outer object before the objects inside it. A key is written into a path only when it fullmatches `[a-z][a-z0-9_]{0,31}`; below any other key every container reports the nearest ancestor reached through such keys.
- **Why.** The error model reports an unknown or duplicate key at its parent path and never echoes a foreign key; the decoder's pairs hook replaces an object with a repeated key by one private marker, so an outer duplicate swallows any inner one and an iterative walk in document order finds the first marker.
- **Alternatives.** Report the duplicated key itself (rejected: it is input text); report always `$` (rejected: the frozen paths name `pdu.header` and `[0].residual.data`); escape foreign keys into the path (rejected: still echoes them).
- **Covering tests.** `test_t12_n18_text_duplicate_key_in_an_envelope`, `test_t12_n18_text_duplicate_key_in_an_entity_document`, `test_t12_n18_text_duplicate_key_order_and_foreign_keys`.

### D63 — The loader's size and depth refusals are the two input-limit subclasses

- **What.** Over 65536 bytes raises `Dis7InputTooLarge("$", ...)` with a message naming the length and the bound; text nested deeper than 16 containers raises `Dis7InputTooDeep("$", ...)`. Both carry `E_INPUT_LIMIT` and are raised before anything else looks at the content (size) and before the decoder (depth).
- **Why.** A host catching the SDK's `InputTooLarge`/`InputTooDeep` sees the loader's refusals the same way as the adapter's guard; the size check first keeps a hostile payload's cost bounded, and the lexical depth scan first keeps the decoder from raising `RecursionError` on CPython 3.11 and 3.12.
- **Alternatives.** A plain `Dis7Error(E_INPUT_LIMIT, ...)` (rejected: hosts that catch the SDK classes would miss it); measuring depth on the decoded document (rejected: the decoder can recurse past the interpreter limit first).
- **Covering tests.** `test_t03_n20_text_65536_bytes_accepted_and_65537_refused`, `test_t03_n20_text_size_is_checked_before_everything_else`, `test_t03_n20_text_depth_16_accepted_and_17_refused`, `test_t03_n20_text_very_deep_text_raises_no_recursion_error`, `test_t03_n20_text_depth_is_checked_before_the_decoder`.

### D64 — Integer literals over 4300 characters are refused by the loader itself

- **What.** The decoder's integer hook refuses a literal longer than 4300 characters (a private constant) with `ValueError`, which the loader maps to `E_TWIN_SCHEMA` at `$`.
- **Why.** 4300 is CPython's default integer-string limit; holding it in the module makes the refusal independent of the interpreter's `sys.set_int_max_str_digits` setting, so every supported interpreter refuses the same text.
- **Alternatives.** Rely on `int()`'s own limit (rejected: it is process-wide and can be raised or disabled by a host); a smaller bound (rejected: no case asks for one, and the wire fields are all far shorter).
- **Covering tests.** `test_t12_text_oversized_integer_literal`, `test_t12_text_oversized_integer_literal_does_not_depend_on_the_interpreter_limit`.

### D65 — A released buffer and a lone-surrogate text are type errors at the root of the guard

- **What.** The adapter's coded guard measures bytes-like input through `memoryview(raw).nbytes` and then converts it once with `bytes(raw)`, each inside a handler for any `Exception` (narrower until R26, D93), so a released `memoryview` is `E_INPUT_TYPE` at `$` before the SDK wrapper or the codec runs; text is measured with `surrogatepass`, so a `str` holding a lone surrogate is measured without a `UnicodeEncodeError` and then refused as `E_INPUT_TYPE` at `$` (over the bound it is `E_INPUT_LIMIT` first). D54 covers the codec alone; this extends the same rule to `to_cdm`, `validate_source` and `detect`, which answers False for a released view.
- **Why.** PLAN.md §4.3 to §4.5 leave it open.
- **Alternatives.** Letting the guard's `bytes(raw)` raise `ValueError` (rejected: only a `Dis7Error` may leave `to_cdm`); a strict UTF-8 measurement (rejected: it raises on a lone surrogate before the size can be judged).
- **Covering tests.** `test_guard_measures_text_before_it_types_it` in `tests/test_cdm_dis7_adapter.py`.

### D66 — `detect` is False over 4224 octets

- **What.** For bytes-like input `detect` measures the size first (`nbytes` for a `memoryview`, `len` otherwise) and answers False above `MAX_PDU_BYTES` without consulting the header predicate, whose missing upper bound (D53) is closed here; for a dict it requires exactly the three envelope keys, a passing depth and cycle walk, and a 7/1/1 header of integers. The whole body sits inside one handler, so `detect` never raises.
- **Why.** PLAN.md §4.3 to §4.5 leave it open.
- **Alternatives.** Leaving the size to `to_cdm` (rejected: CR-28 asks `detect` to be False for over-size input, and the predicate alone answers True for a valid header followed by any number of octets).
- **Covering tests.** `test_t03_n09_guard_refuses_4225_octets_in_every_octet_form` and `test_t03_n20_guard_refuses_a_cycle`; the full matrix is in the tests of R14 and R15.

### D67 — The order of the structure checks at one object

- **What.** At every object of an envelope (`E_TWIN_SCHEMA`) or a stored residual (`E_REPLAY_SHAPE`): not a dict is refused at the object's own path; then a key that is not a `str` of the allowed set at the object's own path, never naming the key; then each required member, absent, at the member's path in schema order; then each member's value in schema order. An array's type or length is reported at the array, an element at `[i]`, lowest index first. The walk follows the schema's order, never the caller's.
- **Why.** PLAN.md §4.3 to §4.5 leave it open.
- **Alternatives.** Missing before unknown, as `encode_pdu` does (rejected for the envelope: D-13 of the shared decisions orders unknown first); the caller's member order (rejected: diagnostics would depend on it).
- **Covering tests.** `test_t03_n20_guard_refuses_seventeen_levels_and_admits_sixteen` (an unknown key at `$`); the per-member matrix is in the tests of R14 and R15.

### D68 — The stage 7 and stage 8 paths

- **What.** Stage 7 compares the checked twin with the decoded wire, the eight header members first and then the other twelve members in schema order, and refuses `E_TWIN_WIRE_MISMATCH` at `pdu.header.<name>`, `pdu.<field>`, `pdu.<array>` when the lengths differ, or `pdu.<array>[i]`; Python values are compared, so `7.0` equals `7` and the two zeros are equal. Stage 8 builds `TimeContext` from the envelope's strings (its `E_CONTEXT_TIME` at `time_context.instant` or `time_context.basis` passes through), then, when the adapter has a context, refuses `E_CONTEXT_CONFLICT` at `time_context.instant` for differing normalised instants and then at `time_context.basis` for differing bases compared verbatim. Octets with no adapter context are `E_CONTEXT_TIME` at `time_context`.
- **Why.** PLAN.md §4.3 to §4.5 leave it open.
- **Alternatives.** Comparing serialised JSON (rejected: it separates `25` from `25.0`); preferring the adapter's context on disagreement (rejected: a silent choice between two caller statements).
- **Covering tests.** tests of R14 and R15.

### D69 — The replay paths and the replay classification

- **What.** `from_cdm` raises only the three replay codes, also when a caller-supplied container of the residual raises as it is read (R30, D112), in six steps: `E_REPLAY_SHAPE` at `$` (not a list of exactly one Entity), at `[0].residual` (no residual block or a namespace other than `DIS`) and at `[0].residual.data` or a member path below it (the residual schema, with the replay-only rows); `E_REPLAY_PROVENANCE` for the stored context, at `[0].residual.data.session`, `.synthetic`, `.time_context.instant`, `.time_context.basis`, `.source_hash`, with a `TimeContext` refusal re-coded at the path it names and an unnormalised stored instant at `.time_context.instant`; `E_REPLAY_CHANGED` at `[0].residual.data.wire_hex` when the stored wire fails the codec or no longer maps to an Entity, and at `[0].residual.data.pdu.<difference>`; `E_REPLAY_PROVENANCE` at `[0].source.<name>` in the frozen field order and then `[0].source_ids`; `E_REPLAY_CHANGED` at `[0].<field>` in `Entity.model_fields` order. A codec or mapping refusal inside replay is re-coded, never passed through. The residual block is also refused at `[0].residual` when it is not the model's residual type, which a model with assignment validation cannot normally hold. Three forms of an Entity built without validation (`model_copy(update=...)`, `model_construct`) are refused as `E_REPLAY_SHAPE` before the attribute concerned is read: at `[0].<field>` for a model field absent from it (in `Entity.model_fields` order), at `[0].residual` for a residual without its namespace or data, and, after the residual checks, at `[0].source` for provenance that is not a complete `SourceRef`; any other unvalidated value goes through the same steps as a validated one (a `position` given as a dict, for example, is `E_REPLAY_CHANGED` at `[0].position`). A comparison of steps 5 and 6 that raises counts as a difference: `E_REPLAY_PROVENANCE` at `[0].source.<name>` or `[0].source_ids`, and `E_REPLAY_CHANGED` at `[0].<field>` (R26).
- **Why.** PLAN.md §4.3 to §4.5 leave it open.
- **Alternatives.** Passing the codec's code through (rejected: CR-15 classifies an undecodable wire as a changed record); a generic dump-and-compare (rejected: §4.5 forbids it, and it hides sub-millisecond edits).
- **Covering tests.** `test_replay_smoke_refuses_count_edit_and_foreign_session`; the full matrix is in the tests of R14 and R15, and R24 added `test_t11_n17_unvalidated_entity_is_refused` (instances built without validation) and the `entity-subclass` row of `test_t11_n17_wrong_shape_is_refused`. R26 added `test_t11_replay_comparison_that_raises_is_a_coded_refusal`, and R30 `test_t11_residual_container_whose_read_raises_is_shape`.

### D70 — The signatures of the five seams

- **What.** Five top-level functions, each called by its bare name from the adapter's methods and never bound as a default, a class attribute or an alias: `_assemble_position(lat_deg, lon_deg, hae_m)` returns an ESTIMATED `Position`; `_affiliation(force_id)` returns `UNKNOWN`; `_state_instant(adapter, context)` slices the normalised instant into a UTC-aware `datetime` and reads no clock; `_replay_bytes(wire_hex)` returns `bytes.fromhex(wire_hex)`; `_canonical_equal(provided, expected)` is true when the types are identical and the values equal. `from_cdm` calls `_canonical_equal` by its bare name through `_unchanged`, which counts a comparison that raises as a difference, so a replacement at run time is still seen (R26).
- **Why.** PLAN.md §4.3 to §4.5 leave it open.
- **Alternatives.** Methods on the class (rejected: a mutation harness replacing a module attribute must reach every caller); bound defaults (rejected: they freeze the original at definition time).
- **Covering tests.** `test_t01_a01_vector_bytes_equal_expected` (the north-pole vector kills a swapped `_assemble_position`) and `test_replay_smoke_refuses_count_edit_and_foreign_session` (kills an always-true `_canonical_equal`).

### D71 — How the holding-state sentences of `### Unreleased` were put into the past tense

- **What.** Besides the four places the run file names, the paragraph on `dis7_host.py` (R11) also said that nothing is registered; it now says nothing was registered at that step. In the codec paragraph the clause after the colon reads "there was no adapter class for `dis7`", and in the paragraph on `adapters/dis7.py` the words naming `Dis7Adapter` joined the sentence saying what the module holds, while the closing sentence reads "There was no adapter class in the module at that step."
- **Why.** The section may say nowhere that nothing is registered, and a sentence in the present tense saying there is no adapter class would be false once the class landed.
- **Alternatives.** Changing only the words `nothing is registered` (rejected: it leaves a false present-tense clause beside them); deleting the sentences (rejected: they record what each step did).
- **Covering tests.** The `### Unreleased` step of the exit check; `tests/test_cdm_release.py` for the count clause.

### D72 — The host-side shape paths of `replay`

- **What.** Before anything is bound, the `replay` command refuses as `E_REPLAY_SHAPE`: more or fewer than one Entity at `$`; no residual or a namespace other than `DIS` at `[0].residual`; a stored session that is not a string or that `validate_session` refuses at `[0].residual.data.session`; a stored classification that is not a boolean at `[0].residual.data.synthetic`. A loader `E_TWIN_SCHEMA` is re-coded as `E_REPLAY_SHAPE` with its own path and message, a pydantic validation failure or a document that differs from the models' own dump is `E_REPLAY_SHAPE` at `$` with one fixed message.
- **Why.** The command binds session and classification from the stored residual, so it has to read them before `from_cdm` can check them; the four paths are the ones `from_cdm` uses for the same defects (DECISIONS D-16), so a caller sees one path per defect whichever layer finds it.
- **Alternatives.** Binding from whatever is stored and letting `from_cdm` refuse it (rejected: a non-string session would reach the constructor and be refused as `E_CONTEXT_SESSION`, a constructor code for a data defect); new host-only paths (rejected: two paths for one defect).
- **Covering tests.** `test_t15_a12_replay_refusals_exit_3` (`residual null`, `residual namespace HLA`) and `test_t15_a12_replay_refuses_each_absent_null_member`.

### D73 — `_same_json` lets a boolean equal only a boolean

- **What.** The host's equality of parsed JSON values treats `true` and `false` as equal only to a boolean; integers and floats compare by value; objects need equal key sets and arrays equal lengths; anything else needs the same type and value.
- **Why.** Python's `True == 1` would let a document spelling `source.synthetic` as `1` pass the canonical-form check after pydantic coerced it, and the self-test would accept a file whose flag changed type.
- **Alternatives.** `==` on the parsed values (rejected: the coercion above); comparing serialised text (rejected: it depends on member order and number spelling the canonical form does not fix in the input).
- **Covering tests.** `test_t15_a12_replay_refusals_exit_3` (`synthetic as 1`) and `test_t15_a12_self_test_passes`.

### D74 — The two `synapse-dis7:` diagnostics

- **What.** The two I/O refusals, both exit 4, are one stderr line each: `synapse-dis7: cannot read --input: <reason>` and `synapse-dis7: cannot write output: <reason>`, where the reason is the operating system's `strerror` or, for a file that is not regular, the words `not a regular file`. Every data and context refusal is instead the `Dis7Error`'s own `CODE at PATH: message` line.
- **Why.** An I/O failure carries no error code of the contract, and the command's name as a prefix separates it from a coded refusal for a caller who reads stderr; the path the caller gave is not repeated, so nothing from the input is echoed.
- **Alternatives.** Coding them as `E_INPUT_TYPE` (rejected: the contract's codes describe data, and exit 4 is a different class); a traceback (rejected: a closed pipe would end in exit 120).
- **Covering tests.** `test_t15_a12_unreadable_input_exits_4` and `test_t15_a12_broken_pipe_exits_4`; R26 added `test_t15_a12_failed_stderr_keeps_exit_class`, `test_t15_a12_failed_stdout_and_failed_stderr_exit_4` and `test_t15_a12_help_into_a_broken_pipe_exits_4`.

### D75 — The `--version` format

- **What.** Exactly three lines: `adapter dis7 1.0.0` from `Dis7Adapter.name` and `Dis7Adapter.version`, `package synapse-cdm <PACKAGE_VERSION>` from `synapse_cdm.version`, and `specification SC DIS7 SPEC 001 1.0` from the module constants `SPECIFICATION_ID` and `SPECIFICATION_VERSION`.
- **Why.** The contract asks for adapter, package and specification identifiers; one `kind name version` line each is readable and splits on spaces except for the specification id, which is the last line. The package version is imported, never typed and never read from installed metadata, which an editable install can leave stale (F11, CR-34).
- **Alternatives.** One line (rejected: harder to read and to parse); a JSON object (rejected: `--version` output is text by convention).
- **Covering tests.** `test_t15_a12_version` and `test_t15_a12_broken_pipe_exits_4` (`version`).

### D76 — The pin block is inserted as text, and the record keeps its row layout

- **What.** `independent_reading_tool` is appended to `spec/dis7_pin.json` as text before its closing brace, indented two spaces like the other blocks; the one-line `file`/`sha256`/`bytes` rows and the one-line `adapter` object stay as they were.
- **Why.** The run allows one new key and no change to an existing row; re-serialising the whole record with `json.dumps(indent=2)` would have rewritten every row onto five lines, a 129-line diff for a 13-line change, although the parsed value is the same.
- **Alternatives.** Re-serialising the record (rejected: it moves every row in the diff); a second record file (rejected: `spec/` may hold only the generator and the `*_pin.json` and `*_terms.json` records, and the run names this record).
- **Covering tests.** `test_t16_a13_pin_record_states_the_independent_reading`, `test_t16_a13_packaged_vectors_are_the_recorded_opendis_bytes` (the rows still carry their digests) and the pin tests of `tests/test_cdm_dis7_schema.py`.

### D77 — How `resolve` words each step, and one child answers a batch

- **What.** `tests/dis7_reference_support.resolve` raises `Blocked` with: `hook` — `SYNAPSE_CDM_OPENDIS_DIR is not set`; `directory` — the directory is missing, or holds no `opendis/dis7.py`; `record` — no `.git`, or `git rev-parse HEAD` cannot run or exits non-zero; `checksum` — HEAD is another commit, or `git status --porcelain` prints anything. A wrong commit and a dirty tree are both `checksum`, the step `normative_binding` uses for a resource whose content differs from the pin. `run_opendis` answers a list of requests in one child, so `write_exercise` starts one interpreter for its six requests.
- **Why.** The wording follows `normative_binding.resolve` (`<hook>=<value> is not a directory`); one child per batch keeps OpenDIS out of the test process without an interpreter start per comparison.
- **Alternatives.** A separate step name for a dirty tree (rejected: every step name must be a member of `normative_binding.STEPS`); one child per request in `write_exercise` (rejected: six starts for one specification).
- **Covering tests.** `test_t16_a13_blocked_reasons` (`hook`, `directory`, `record`), the live tests through `support.checkout()`, and `test_t16_a13_exercise_files_agree`.

### D78 — The generator's per-PDU line reports the built length and the packaged digest

- **What.** Each line of `build_fixtures.py` reads `<stem>.dis: <n> bytes, sha256 <hex>: equal` (or `DIFFERENT`), where `<n>` is the length of the PDU OpenDIS built and `<hex>` is `evidence.digest` of the packaged file.
- **Why.** The digest names the file the comparison is against, which is the pinned fact; the built length is what shows a missed length or record at a glance when the two differ.
- **Alternatives.** The packaged length (rejected: equal to the pin row and silent about what was built); the digest of the built bytes (rejected: the generator imports no digest module and the run names `evidence.digest(path)`).
- **Covering tests.** `test_t16_a13_generator_script_reproduces_the_packaged_vectors`; the verifier's scratch-copy run with `25.0` changed to `26.0` (exit 1, `DIFFERENT`).

### D79 — The restamp mutant patches the call site of `_replay_bytes`

- **What.** The `restamp_timestamp` row of `gates/dis7_mutation.py` replaces the one line `return _replay_bytes(stored_wire)` in `from_cdm` with a return of the same bytes whose octets 4 to 7 are the DIS encoding of the stored instant's position in its hour, `(int(s * 2**31 / 3600) << 1) | 1` big-endian, read from `context.instant` (minutes, seconds, milliseconds).
- **Why.** `_replay_bytes(wire_hex)` cannot see the instant, and the call site is the one place where the stored instant is in scope; the encoding of the real instant is the fault the case names, and on every vector it equals the octets already there, so the mutant is blind exactly where the plan says naive killers are.
- **Alternatives.** Restamping with the fixed octets `40000001` inside `_replay_bytes` (rejected: allowed only if the call site could not be patched, and it is a weaker model of the fault).
- **Covering tests.** `test_acceptance_sweep[t09_a07]` and `test_t09_a07_years_0001_and_0999_are_dumped_with_four_digits` caught it; `test_t16_a14_every_fault_is_detected_and_the_control_is_green` holds the row to DETECTED.

### D80 — The receipt-time and stale-PDU mutants still call the original seam

- **What.** The two `receipt_time_*` rows and `stale_pdu_after_edit` wrap their seam like the others: the mutated function calls `<name>_original(...)`, discards its result and returns the adapter clock's `now()`, the wall clock in UTC, or `True`.
- **Why.** The wrap form keeps every row the same shape (the `def` line as the anchor, the original renamed below it) and keeps whatever the original checks on its arguments, so the only change a row makes is the fault it names.
- **Alternatives.** Replacing the body (rejected: the run asks for wraps, never body edits); not calling the original (rejected: it leaves the original as dead code with a different behaviour on bad arguments).
- **Covering tests.** `test_t16_a14_every_patch_anchor_occurs_exactly_once` and the slow test of `tests/test_cdm_dis7_mutation.py`.

### D81 — The benchmark's retained-growth allowance and reduced workload

- **What.** `gates/dis7_benchmark.py` judges retained growth against `RETAINED_ALLOWANCE_BYTES = 65536` traced bytes between the end of a first and of a second identical pass, after `gc.collect()`; `--quick` runs 2000 calls after 200 warm-up calls, the workload the always-on test runs.
- **Why.** Requirement R23 makes the absence of unbounded retained state mandatory but names no figure; 64 KiB is far below what a per-call leak of even one small object leaves over 2000 calls (2000 × 64 payload bytes is already 128000), yet absorbs interpreter-level one-off allocations such as a cache filled on the second pass. The reduced workload keeps the test well under a few seconds while still exercising both inputs and the traced passes.
- **Alternatives.** A zero allowance (rejected: one-off interpreter allocations would make the verdict flaky); a figure relative to the call count (rejected: a constant is what the verdict and the test can both state); running the full workload in the test (rejected: minutes on every test run).
- **Covering tests.** `test_r23_workload_sizes_are_the_required_ones`, `test_r23_retained_growth_sees_a_leak`, `test_r23_quick_run_has_no_retained_growth`, `test_r23_verdict_ignores_timings`.

### D82 — The benchmark finds the seed through the imported package

- **What.** `seed_pdu()` reads `fixtures/dis7/vectors/equator_eastbound.dis` next to `sys.modules["synapse_cdm"].__file__`, the package that `from synapse_cdm import version` has already imported, so the gate's imports stay the two named package imports and the standard library.
- **Why.** The seed must be the bytes of the package under test, wherever it is installed; the module object is present once any submodule is imported.
- **Alternatives.** A separate `import synapse_cdm` (rejected: the run lists the gate's imports exactly); a path relative to the gate file (rejected: it would read the source tree even when another installation is under test).
- **Covering tests.** `test_r23_quick_run_has_no_retained_growth` (fixture sizes and record counts) and `test_r23_maximal_pdu_is_case_a02`.

No retained state was found in the DIS7 modules: the full and the reduced workloads both reported no retained growth, so no code was changed for it.

### D83 — The `synapse-dis7` check reports stderr only, and locates its inputs in text mode

- **What.** `check_dis7_script` raises `Failed` through one local helper that names the step, the exit code and at most the last 800 characters of stderr decoded with `errors="replace"`; it never quotes stdout. Locating the packaged vectors and reading `PACKAGE_VERSION` go through the text-mode `run` and `must`, as `check_console_scripts` locates its golden.
- **Why.** The script's stdout is JSON or PDU octets; a report that quotes it would carry undecodable bytes. The two locating calls print one line of text each, so the existing helpers fit them.
- **Alternatives.** Quoting a hex digest of stdout on failure (rejected: the run file forbids stdout in the message); `run_bytes` for the locating calls too (rejected: the run file asks for the same route as the existing golden lookup).
- **Covering tests.** `test_t15_a12_the_dis7_script_check_passes_against_this_environment`, `test_t15_a12_the_gate_reads_a_scripts_output_as_bytes`.

### D84 — The coverage paragraph carries the profile sentence in lower case

- **What.** The DIS section's first sentence continues with ", and the profile is the Entity State subset only (…)" rather than opening a new sentence with "The profile".
- **Why.** The run file requires those exact words, and a capitalised "The" would not be them; the order it asks for (residual stance, then profile) is kept.
- **Alternatives.** A separate sentence beginning "The profile" (rejected: not the exact words).
- **Covering tests.** `tests/test_cdm_format_coverage.py` (paths of the CDM column) and the run's exit check, which greps the section.

### D85 — The release-notes roster paragraph keeps the replaced sentences unwrapped

- **What.** The replacement text in `RELEASE_NOTES.md` sits on one line inside the paragraph instead of being re-wrapped to the file's width.
- **Why.** Tests and exit checks read that file's raw text for whole sentences (the test name, the `adapters registered` sentence, the **post-3.1.1** sentence); a line break inside one would hide it.
- **Alternatives.** Re-wrapping to the file's column (rejected for that reason).
- **Covering tests.** `tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry`.

### D86 — The declarations-table clause for `dis7` names the codec constant

- **What.** The `dis7` row of the declarations table in `parser-safety.mdx` reads "one Entity State PDU of this subset is 144 octets plus at most 255 variable parameter records of 16 octets (`dis7_codec.MAX_PDU_BYTES`)".
- **Why.** It is the manifest's `max_input_bytes` source, shortened to one clause, and the neighbouring rows cite the module constant that holds the figure in the same form.
- **Alternatives.** Quoting the manifest's whole source sentence (rejected: the table holds one clause per row).
- **Covering tests.** `tests/test_cdm_prose_counts.py` (the implementation-cap count of that page) and `tests/test_cdm_input_bounds.py`.

### D87 — One ledger quotation is a shortened contiguous part of the printed text

- **What.** The `TREE_EXEMPT` row for the ledger's second `CONFORMANT from the installed wheel` reading quotes the text from "and read" on, dropping the run's time-of-day range that the sweep printed before it.
- **Why.** The pipeline forbids a time of day in any tracked file; the run file allows a contiguous part of the printed text that still holds the whole count phrase.
- **Alternatives.** Pasting the printed text byte for byte (rejected: it carries a time of day).
- **Covering tests.** `tests/test_cdm_prose_counts.py::test_every_tree_exemption_still_points_at_prose_that_is_there` and `test_no_tracked_file_states_an_adapter_count_that_is_neither_the_roster_nor_ruled`.

### D88 — D85's quotation of a release-notes sentence names it without its count

- **What.** D85's "Why" names the `adapters registered` sentence instead of quoting it with its number.
- **Why.** This record is live and states no roster count; the sentence it names is the released version's, and quoting its number here was a stray of the tree-wide sweep.
- **Alternatives.** A `TREE_EXEMPT` row for this file (rejected: a live file is never exempted).
- **Covering tests.** `tests/test_cdm_prose_counts.py::test_no_tracked_file_states_an_adapter_count_that_is_neither_the_roster_nor_ruled`.

### D89 — The terms record is a reading by a tool that does not expose the HTTP status

- **What.** `fixtures/dis7/spec/dis7_terms.json` is written in the reading form, from one WebFetch of the IEEE page for IEEE 1278.1-2012: `http_status` is null and `notes` says the tool did not expose it, `quoted` carries only the words the tool returned (title, status, inactivation date, `Purchase`, `Access via Subscription`), and the maintainer confirmation read PENDING. On 2026-10-05 the maintainer confirmed the reading and the class `LICENSED`; run R28 replaced the two PENDING sentences of `mapping_rule_applied` and `what_this_is` with the confirmation and changed no other member.
- **Why.** The run allowed exactly one fetch, and the result named the standard, so it counts as a reading; the earlier curl attempt from this machine met a challenge page, which the tool did not.
- **Alternatives.** The no-reading form (rejected: a page was read); a second fetch by curl to obtain a status (rejected: one fetch only).
- **Covering tests.** `tests/test_cdm_packaging.py` (the record ships as package data). Run R22's exit check held the record to the PENDING form and refuses the confirmed record by design; since R28 the exit check of run R28 reads the confirmation sentence.

### D90 — The completion checks treat a docstring-only function as empty

- **What.** `empty_function_bodies` flags a function whose body after a leading docstring is empty, only `pass` or `...`, and any `raise NotImplementedError`; classes are never flagged. The claims guard splits on `.`, `;`, `|` and blank lines and accepts a negation word anywhere before the phrase in the same sentence.
- **Why.** The run's rule, stated as functions of source text so the checks are witnessed refusing before they judge the tree.
- **Alternatives.** Flagging only `pass` (rejected: a docstring-only function is as unfinished).
- **Covering tests.** `tests/test_cdm_dis7_trace.py::test_completion_checks_can_fail`, `tests/test_cdm_dis7_trace.py::test_completion_claims_guard_can_fail`.

### D91 — A str subclass is refused for the session, the instant and the basis

- **What.** `validate_session`, the instant check and the basis check of `TimeContext` require the exact type `str` (`type(value) is not str`), so an `enum.StrEnum` member, a `(str, Enum)` member or any other subclass of `str` is refused with the code and path a non-string gets (`E_CONTEXT_SESSION` at `session`; `E_CONTEXT_TIME` at `time_context.instant` or `time_context.basis`). `validate_session` still returns the very object it was given (D-08).
- **Why.** The identity is derived from the characters, and a subclass can format differently (`Sess.ALPHA`) or lie about its length and encoding; the replay gate already requires the exact type, so an accepted subclass gave an Entity the same adapter could not replay (final review F-01).
- **Alternatives.** Converting the value with `str(value)` (rejected: D-08 requires `validate_session` to return the object it was given, and `str()` of a `(str, Enum)` member is its class and member name (`Sess.ALPHA`), not its value).
- **Covering tests.** `tests/test_cdm_dis7_time_identity.py::test_t09_session_refuses_str_subclasses`, `::test_t09_time_context_refuses_str_subclasses`; the three `session_str_*` rows of `test_constructor_refuses_each_context_defect`.

### D92 — The constructor checks a time context again and keeps its own copy

- **What.** `Dis7Adapter(...)` given a `TimeContext` builds a new `TimeContext(instant, basis)` from the attributes it reads once (absent attributes read as `None`), so an instance whose fields bypassed `__post_init__` (a subclass with an empty `__post_init__`, `TimeContext.__new__(TimeContext)`, `object.__setattr__` on the frozen instance) is refused as `E_CONTEXT_TIME` at `time_context.instant` or `time_context.basis`; a valid instant that is not in its normalised form is refused at `time_context.instant`. The adapter stores the new plain instance, so `time_context` compares equal to a plain `TimeContext` the caller passed (a subclass instance is replaced by a plain one and no longer compares equal), and a later `object.__setattr__` on the caller's object does not reach it (final review F-09).
- **Why.** R21 requires a coded constructor refusal, and PLAN.md §4.2 says the instance holds only immutable context; before, the first `to_cdm` raised an uncoded `ValueError` or `AttributeError` and `validate_source` raised instead of returning one string.
- **Alternatives.** Keeping the caller's object after the check (rejected: a later in-place write would reach the adapter).
- **Covering tests.** `test_constructor_revalidates_a_time_context_that_bypassed_validation` (five forms) and `test_constructor_keeps_its_own_copy_of_the_time_context` in `tests/test_cdm_dis7_adapter.py`; since R30 also `test_constructor_refuses_a_time_context_whose_read_raises` (D112).

### D93 — A bytes-like subclass that raises is a type error, never a foreign exception

- **What.** `decode_pdu` and the adapter's coded guard catch any `Exception` around `memoryview(raw).nbytes` and `bytes(raw)` and refuse it as `E_INPUT_TYPE` at `$`; a conversion that returns anything but the exact type `bytes` (a subclass `__bytes__` returning itself) is refused the same way. `looks_like_entity_state` catches any `Exception` while it reads the first 12 octets and answers False, also when what it read is not the exact type `bytes`. `parse_json_text` requires the exact type `bytes` (D-10), so a subclass is `E_INPUT_TYPE` at `$`. A plain subclass that overrides nothing still decodes like `bytes` (final review F-15).
- **Why.** R21: no foreign exception may leave the public interface, and the predicate is documented never to raise; a subclass can override `__bytes__`, `__len__` or `__getitem__`.
- **Alternatives.** Refusing every subclass by type in the codec (rejected: `isinstance` admission of buffers is the contract's, and a plain subclass carries ordinary octets).
- **Covering tests.** `test_bytes_subclasses_that_raise_are_refused_as_input_type` in `tests/test_cdm_dis7_codec.py`, `test_guard_refuses_a_bytes_subclass_that_raises_as_input_type` in `tests/test_cdm_dis7_adapter.py`, `test_t12_text_bytes_subclass_is_refused` in `tests/test_cdm_dis7_replay.py`.

### D94 — The header predicate reads a multi-dimensional or 0-dimensional view as flat octets

- **What.** `looks_like_entity_state` given a C-contiguous `memoryview` whose `ndim` is not 1 reads `raw.cast("B")[:12]`, so a 0-dimensional view (a `ctypes.Structure`) answers as `decode_pdu` reads it and a multi-dimensional view is not sliced by rows; every other input keeps `bytes(raw[:12])` (final review F-16).
- **Why.** CR-29: a memoryview is its underlying octets; before, a 0-dimensional view answered False for a buffer `decode_pdu` accepts, and a `[16, 2^24]` view copied 12 rows.
- **Alternatives.** `raw.tobytes()` for non-contiguous views (rejected: it copies the whole view; the slice of the first dimension is already a C-order prefix).
- **Covering tests.** `test_header_predicate_reads_a_zero_dimensional_view_as_its_octets` in `tests/test_cdm_dis7_codec.py`.

### D95 — The PDU bound is measured before the buffer is copied

- **What.** `decode_pdu` and the coded guard read `memoryview(raw).nbytes` first and raise `Dis7InputTooLarge` over 4224 octets before `bytes(raw)` runs; the copy is then measured again, as PLAN.md §4.3 step 1 says, which also catches a `bytearray` resized between the two statements. The message names both numbers as before (final review F-17).
- **Why.** R22 asks for the limits to be enforced before expensive allocation; before, a 16 MiB `bytearray` or `memoryview` was duplicated in memory before it was refused.
- **Alternatives.** Measuring only the copy (rejected: that is the allocation R22 forbids before the check).
- **Covering tests.** `test_oversize_buffer_is_refused_before_it_is_copied` in `tests/test_cdm_dis7_codec.py` and `test_guard_refuses_an_oversize_buffer_before_it_is_copied` in `tests/test_cdm_dis7_adapter.py` (traced peak below 1 MiB; memory only, never a duration).

### D96 — Envelope and residual members are read once, and only the checked values are used

- **What.** The structure checks return what they checked: each array helper takes `list(value)` after the width check on the original and checks the items on that copy; `_check_pdu` returns a plain twin built from the values it read once; `_check_time_context` returns `(instant, basis)`; `_check_hash` returns `None` or the digest; `_check_envelope` returns `(twin, wire_hex, instant, basis)` and `_check_residual` the seven checked values. `to_cdm` and `from_cdm` use only those values and never index the caller's mapping again. Check order and diagnostics are unchanged (final review F-19).
- **Why.** PLAN.md §4.2 says `to_cdm` copies what it keeps once the guard has bounded it, and R21 forbids a foreign exception; a mapping whose second read of a key differed (a dict subclass, or a dict another thread writes) leaked `TypeError` or `ValueError`.
- **Alternatives.** Copying the whole envelope first (rejected: the widths must be checked before anything is expanded, R13).
- **Covering tests.** `test_envelope_member_read_twice_differently_is_read_once`, `test_envelope_pdu_member_read_twice_differently_is_read_once`, `test_residual_member_read_twice_differently_is_read_once` and `test_residual_data_read_twice_differently_is_read_once` in `tests/test_cdm_dis7_replay.py`.

### D97 — A failed stderr keeps the exit class

- **What.** `_diagnose` writes and flushes `sys.stderr`; on an `OSError`, `ValueError` or `AttributeError` it sets `sys.stderr` to `None`, and it returns at once when `sys.stderr` is `None`. A refused file or refused data with stderr on a broken pipe therefore exits 4 or 3, not 120 (final review F-20). Since R30 a usage error keeps exit 2 the same way: `main` flushes `sys.stderr` before it re-raises argparse's non-zero `SystemExit` and sets it to `None` on an `OSError` or `ValueError`, and with stderr closed the parser's `error` writes nothing and exits 2, where argparse would write the usage to stdout (adjudication S-03).
- **Why.** R24 and PLAN.md §4.8 fix the exit classes; the interpreter's exit-time flush of a line left in a failed stderr exits 120.
- **Alternatives.** Leaving the line buffered (rejected: that is the exit-time flush that fails).
- **Covering tests.** `test_t15_a12_failed_stderr_keeps_exit_class` (closed and broken stderr, exit 4 and exit 3, and since R30 exit 2 for `bogus`, `decode` without its arguments and no command) and `test_t15_a12_failed_stdout_and_failed_stderr_exit_4` in `tests/test_cdm_dis7_cli.py`.

### D98 — Help output is flushed inside the output handler

- **What.** `main` catches the `SystemExit(0)` argparse raises after `--help`, flushes `sys.stdout`, and on an `OSError` or `ValueError` sets `sys.stdout` to `None`, writes `synapse-dis7: cannot write output: <reason>` and returns 4; a non-zero `SystemExit` is re-raised unchanged. No second `os.open` is added (final review F-21). Since R30, under PLAN.md §4.8 (an output failure is exit 4), `--help` with stdout closed, at the top level and for each command, writes no help text: the parser class `_Parser`, which the sub-parsers take from their parent, overrides `print_help` to write nothing when `sys.stdout` is `None`, and `main` writes `synapse-dis7: cannot write output: stdout is closed` and returns 4. Before, argparse wrote the help to stderr and the command exited 0 (adjudication S-03).
- **Why.** PLAN.md §4.8: all stdout is flushed inside the handler that maps an I/O failure to exit 4; argparse wrote the help outside `_emit`, and a broken pipe ended in exit 120 with `Exception ignored`.
- **Alternatives.** Adding the help cases to `BROKEN_PIPE_CASES` (rejected: the closed-stdout tests share that table, and with stdout closed argparse printed the help to stderr and exited 0, a behaviour R26 did not change; R30 changed it, above).
- **Covering tests.** `test_t15_a12_help_into_a_broken_pipe_exits_4` (`--help`, `decode --help`) and, since R30, `test_t15_a12_help_with_closed_stdout_exits_4` (the same two, exit 4 and nothing on stderr but the one line) in `tests/test_cdm_dis7_cli.py`.

### D99 — The bounded read checks the descriptor it reads and asks for no more than the bound

- **What.** `_read_bounded` keeps the type check on the path, so a FIFO or a device is not opened, then opens the path with `O_RDONLY` and, where the platform has them, `O_NONBLOCK`, `O_NOCTTY` and `O_BINARY`; it refuses a descriptor that `os.fstat` does not report as a regular file with `OSError("not a regular file")`, and reads with `os.read` in a loop that asks for no more than the octets still wanted, `limit + 1` in all (final review F-22 and F-23).
- **Why.** PLAN.md §4.8: a non-regular `--input` is exit 4 without blocking, also when a FIFO is renamed onto the path between the check and the open; R24 says read at most 4225 bytes, and the buffered reader read 128 KiB on 3.14.
- **Alternatives.** An unbuffered `open(path, "rb", buffering=0)` (rejected: it still opens a swapped-in FIFO with a blocking open).
- **Covering tests.** `test_t15_a12_fifo_swapped_in_after_the_type_check_is_refused`, `test_t15_a12_read_bounded_reads_no_more_than_the_bound`, `test_t15_a12_decode_oversize_read_is_bounded` and `test_t15_a12_replay_oversize_read_is_bounded` in `tests/test_cdm_dis7_cli.py`; `test_t15_a12_host_module_import_rules` now expects the two `os.open` calls, in `_emit` and `_read_bounded`.

### D100 — `replay` names the size of an oversize file as a floor

- **What.** `replay` refuses a read of more than 65536 octets itself, before the loader, with `E_INPUT_LIMIT at $: input is at least 65537 octets; the limit is 65536` and exit 3, as `decode` already words its own bound (final review F-24).
- **Why.** D-01 requires a size refusal to name both numbers; the bounded read stops one octet past the bound, so the loader's `input is 65537 octets` was false for any larger file.
- **Alternatives.** Measuring the file with `os.fstat` (rejected: the size can change between the measurement and the read).
- **Covering tests.** `test_t15_a12_replay_input_bound` (the 65537 row asserts the whole line) and `test_t15_a12_replay_of_a_much_larger_file_names_the_floor` in `tests/test_cdm_dis7_cli.py`.

### D101 — A hook overridden as a staticmethod or a plain function is an override

- **What.** `harness.overrides_fixture_instance` compares `getattr(hook, "__func__", hook)` with the default hook's function, so an override that is not a classmethod is recognised and its `ValueError` is exit 2 with the hook's own message, as D-30 says, instead of an `AttributeError` about `__func__` (final review F-42). The bump gate classifies the function as new in this arc, so no ruling is needed.
- **Why.** D-30 catches the hook's refusal only for an overriding class; the helper raised for any override that has no `__func__`.
- **Alternatives.** Requiring the hook to be a classmethod (rejected: the base class does not enforce it).
- **Covering tests.** `test_a_staticmethod_hook_is_an_override_and_its_refusal_is_exit_2` in `tests/test_cdm_fixture_instance.py`, with the double `StaticRefusal` in `tests/fixture_instance_double.py`.

### D102 — The stdout redirect closes its descriptor when it cannot be made

- **What.** `_emit`'s failure branch reads `sys.stdout.fileno()` before it opens the null device, and closes the opened descriptor in a `finally`, so a stdout whose `fileno()` or `dup2` fails leaves no descriptor open (final review F-56).
- **Why.** Each in-process call with a Python-closed `sys.stdout` leaked one descriptor.
- **Alternatives.** None that keeps exactly one `os.open` in `_emit`.
- **Covering tests.** `test_t15_emit_closes_the_redirect_descriptor` in `tests/test_cdm_dis7_cli.py`.

### D103 — The trace ratchet binds only tests pytest collects

- **What.** `scan_source` walks the module body only: a module-level `test_t<gg>_<case>_` function binds, a method binds only inside a module-level class whose name starts with `Test`, and the `SWEEP_BUILDERS` dict literal binds as before; a nested function or a method of any other class binds nothing. `evidence_problems` resolves a `tests/<file>::<function>` entry against module-level functions only (final review F-26). Since R30 a `Test*` class that defines `__init__` binds nothing either, since pytest does not collect it, and an entry of `R_EVIDENCE` or `R_SUPPLEMENT` must name a function whose name starts with `test`; every `R_EVIDENCE` entry of that form already did (adjudication S-08, S-10).
- **Why.** `pytest.ini` sets no `python_classes`, so only `Test*` classes are collected; a binding by a test pytest never runs kept the ratchet green with no test behind it.
- **Alternatives.** Collect with pytest itself (rejected: the binder is a function of source text so that its refusals can be witnessed on literal sources).
- **Covering tests.** `test_the_binder_reads_function_names_methods_and_the_sweep_table` and `test_pending_is_exactly_the_set_of_unbound_ids` in `tests/test_cdm_dis7_trace.py`; since R30 also `test_the_evidence_check_refuses_what_does_not_resolve` (a nested and a helper entry) and `test_the_supplement_check_refuses_what_does_not_resolve` (a helper entry).

### D104 — Supplementary requirement evidence, the wheel-gate half of A12 and the resolution tags are checked

- **What.** `R_SUPPLEMENT` attaches the `test_r12_`, `test_r17_` and `test_r22_` tests to the cited requirements R12, R17 and R22 without binding anything; `supplement_problems` refuses an uncited key, an empty tuple, a `RUN:` entry and an entry that does not resolve, and a completeness test requires every module-level `test_r<nn>_` test of a cited requirement to be listed (F-04). `a12_wheel_gate_problems` requires the three `test_t15_a12_` tests of `tests/test_cdm_gate_rosters.py` (CR-33, F-27) while `bound_ids` and `R_EVIDENCE` stay unchanged. `tagged_resolutions` reads a `# CR-nn` comment directly above a test or its first decorator, and every resolution CR-01 to CR-35 must be tagged so (D-28, F-12). Since R30 the tag counts only at column 0 on the line above a module-level function whose name starts with `test_`, or above its first decorator, read from the parsed module, so a tag above a fixture or a nested function counts not (adjudication S-09).
- **Why.** A requirement cited by one case was evidenced only by that case's tests, the wheel gate that CR-33 names was outside the ratchet, and seven resolutions had no tag, so each gap could reopen without a red test.
- **Alternatives.** A `CASE_EVIDENCE` dict folded into `bound_ids` (rejected by the review's own check: the handover reads `bound_ids` and `evidence_problems` as they are); the tags without a check (rejected: nothing would keep them).
- **Covering tests.** `test_the_supplement_names_only_cited_requirements_and_every_entry_resolves`, `test_the_supplement_check_refuses_what_does_not_resolve`, `test_every_named_requirement_test_of_a_cited_requirement_is_in_the_supplement`, `test_cr33_case_a12_is_bound_to_the_wheel_gate_as_well_as_the_cli`, `test_cr33_the_wheel_gate_check_can_fail`, `test_every_contract_resolution_is_tagged_above_a_test` and `test_the_resolution_tag_check_can_fail` in `tests/test_cdm_dis7_trace.py`.

### D105 — The envelope range rows are the union of both corrections

- **What.** `_RANGE_ROWS` in `tests/test_cdm_dis7_replay.py` gains eighteen rows: the review's eleven, the per-index upper bounds of both independent checks (`entity_id[1]`, `entity_id[2]`, `entity_type[1]`, `[3]`, `[4]`, `[5]`, `alternative_entity_type[4]`), with the two padding rows that F-30 also asks for written once. The same table drives the new stored-residual range test, so every row is judged as `E_TWIN_SCHEMA` on the envelope and as `E_REPLAY_SHAPE` on a stored residual (F-30, F-32). R30 added five rows: the upper bounds of `alternative_entity_type[1]`, `[2]`, `[3]` and `[5]`, and a negative timestamp (adjudication S-07).
- **Why.** The two checks of F-32 each proposed rows the other lacked; every row passes on the tree and kills a bound no other row kills.
- **Alternatives.** Either correction alone (rejected: it leaves per-index tops unkilled); a separate residual table (rejected: the finding asks to reuse the envelope tables).
- **Covering tests.** `test_t12_n18_range_constant_and_non_finite` and `test_t11_residual_range_constant_and_non_finite_is_shape` in `tests/test_cdm_dis7_replay.py`.

### D106 — The error classes' constructors and the size-refusal texts

- **What.** Kit decision D-01: `Dis7Error(code, path, message)`, `Dis7InputTooLarge(path, message)` and `Dis7InputTooDeep(path, message)`; the two subclasses set `E_INPUT_LIMIT` themselves. A size refusal reads `input is {n} octets; the limit is {limit}` in the codec, in the adapter's guard (octets and text) and in the text loader, and the loader's depth refusal reads `the text nests deeper than 16 containers`. The host command reads at most one octet past its bound, so it words an oversize file as a floor: `input is at least {n} octets; the limit is 4224` for `decode` and `input is at least {n} octets; the limit is 65536` for `replay` (D100). Every other refusal message is printed unchanged.
- **Why.** PLAN.md §4.3 names the classes and the code but not their constructors or their wording; the kit fixed both once for every run.
- **Alternatives.** Subclasses that take the code as an argument (rejected: an input-limit class could then carry another code).
- **Covering tests.** `tests/test_cdm_dis7_codec.py::test_r21_too_large_carries_the_limit_code_and_both_base_classes`, `::test_r21_too_deep_carries_the_limit_code_and_both_base_classes`, `::test_r21_errors_survive_copy_and_pickle`, `tests/test_cdm_dis7_adapter.py::test_t03_n09_guard_refuses_4225_octets_in_every_octet_form` and `tests/test_cdm_dis7_replay.py::test_t03_n20_text_65536_bytes_accepted_and_65537_refused`, which assert both numbers rather than the literal wording; `tests/test_cdm_dis7_cli.py::test_t15_a12_replay_input_bound`, `::test_t15_a12_replay_of_a_much_larger_file_names_the_floor` and `::test_t15_a12_decode_oversize_read_is_bounded` assert the command's whole line.

### D107 — TimeContext checks the instant before the basis

- **What.** Kit decision D-08: `TimeContext(instant, basis)` checks the instant first, then the basis; a value that is not a `str` is `E_CONTEXT_TIME` at its own path. `.instant` is always the 24-character form `YYYY-MM-DDTHH:MM:SS.mmmZ`. In an envelope twin, a missing or non-string instant or basis is `E_TWIN_SCHEMA` (stage 2) and a string with a bad value is `E_CONTEXT_TIME` (CR-03). `validate_session` returns the very object it was given or raises `E_CONTEXT_SESSION` at `session`. `TimeContext` equality and hash are the dataclass-generated ones over the normalised instant and the verbatim basis.
- **Why.** PLAN.md §4.2 and §4.6 fix what `TimeContext` stores, not the order of its checks or its equality.
- **Alternatives.** Checking the basis first; a hand-written `__eq__`.
- **Covering tests.** `tests/test_cdm_dis7_time_identity.py::test_t09_n13_instant_is_checked_before_basis`, `::test_t09_n13_refused_instant` (non-string instants), `::test_t09_basis_bounds_in_code_points` (non-string bases), `::test_t09_a07_equivalent_spellings_normalise_to_one_instant` (hash), `::test_t09_time_context_is_frozen_and_equal_by_value` and `::test_t09_session_bounds_and_alphabet`.

### D108 — The malformed set

- **What.** Kit decision D-19: five payloads, all built from the equator vector: `wrong_protocol_version.dis` (`E_HEADER_UNSUPPORTED` at `byte[0]`), `pdu_type_67.dis` (`E_HEADER_UNSUPPORTED` at `byte[2]`), `truncated_by_one_byte.dis` (`E_LENGTH_MISMATCH` at `byte[143]`), `one_trailing_byte.dis` (`E_LENGTH_MISMATCH` at `byte[8]`) and `envelope_unknown_key.json` (`E_TWIN_SCHEMA` at `$`). `fixtures/dis7/malformed/README.md` tables them.
- **Why.** PLAN.md §4.7 asks for at least two payloads; the codes and paths follow the validation order of PLAN.md §4.4 and cases N01, N02, N06 and N07.
- **Alternatives.** A duplicate-key document (rejected: the fixture loader would collapse the repeated key before the adapter saw it).
- **Covering tests.** `tests/test_cdm_dis7_adapter.py::test_the_malformed_set_is_exactly_the_five_stated_payloads`, `::test_t02_n01_malformed_wrong_protocol_version_is_refused`, `::test_t02_n02_malformed_pdu_type_67_is_refused`, `::test_t02_n06_malformed_truncated_by_one_byte_is_refused`, `::test_t02_n07_malformed_one_trailing_byte_is_refused` and `::test_malformed_envelope_with_an_unknown_member_is_refused`.

### D109 — What the host module may import and open

- **What.** Kit decision D-29, as the module stands after R26: `dis7_host.py` never imports `hashlib`, `hmac`, `secrets`, `ssl`, `socket`, `signal`, `resource`, `platform`, `subprocess` or `importlib.metadata`, and has no module-level import of `synapse_cdm.evidence`, `suite` or `harness`, so importing it loads none of them. It calls the builtin `open` nowhere: it reads its input through one read-only, non-blocking `os.open` in `_read_bounded` (D99) and opens `os.devnull` for writing in `_emit` only to stop a failed stdout from being flushed again (D102). It never calls `write_text` or `write_bytes`.
- **Why.** PLAN.md §4.1 forbids `signal`, `resource` and `platform` and requires attribute access to `evidence`; the `hashlib` ban is the package-wide boundary gate; the module is the only DIS 7 file reader and writes no file.
- **Alternatives.** None.
- **Covering tests.** `tests/test_cdm_dis7_replay.py::test_t12_text_host_module_surface_and_imports` (the import list and the modules a plain import loads) and `tests/test_cdm_dis7_cli.py::test_t15_a12_host_module_import_rules` (the import roots, the `evidence` import, the `open` modes and the two `os.open` sites). No test checks `importlib.metadata`, `write_text` or `write_bytes`; that part is held by inspection.

### D110 — Three findings on one paragraph of `### Unreleased` are applied as one wording

- **What.** F-43, F-45 and F-52 each rewrote the count paragraph of `### Unreleased` and the two step sentences of the projection helpers and the host loader. The paragraph takes F-52's corrected wording (the `FORMAT_COVERAGE.md`, `dis7_codec.py`, `adapters/dis7.py` and `README.md` descriptions and 48 new files under `fixtures/dis7/`), the two step sentences take F-45's corrected wording (`At that step nothing called …`), and the count clause stays at 64 files.
- **Why.** The three replacements overlap on the same strings, so only one can be applied; F-52's is the superset, and F-45's step sentences keep the record's past tense for a step (D71).
- **Alternatives.** F-43's parentheses (rejected: they leave the README and `FORMAT_COVERAGE.md` descriptions short of what moved).
- **Covering tests.** `tests/test_cdm_release.py` (the Unreleased file list and its count clause) and `tests/test_cdm_prose_counts.py`.

### D111 — What run R28 left to a later unit

- **What.** Two parts of the text findings are not applied: the availability assertion that F-44 proposes for `tests/test_cdm_dis7_trace.py` (a new test, which this run may not add), and the argparse description of `synapse-dis7` in `dis7_host.py`, which still says the command reads one file (F-60; help text is output, and this run changes no behaviour of the package). Run R30 applied both (adjudication S-18): the description now says that `decode` and `replay` read the one `--input` file and `self-test` the packaged vectors, and the availability sentence is asserted.
- **Why.** Run R28 changes texts and records only; a new assertion belongs to a test run and a help string to a behaviour run.
- **Alternatives.** Applying both here (rejected: each would break the run's scope).
- **Covering tests.** Since R30, `tests/test_cdm_dis7_cli.py::test_t15_a12_help_description_names_what_each_command_reads` and `tests/test_cdm_dis7_trace.py::test_completion_availability_is_stated`.

### D112 — A caller-supplied container whose read raises is refused with the stage's code

- **What.** Each read of a caller-supplied container in the structure checks (a member by key, the key list, an array's length and its items) goes through `_read`: an `Exception` other than `Dis7Error` raised by the read becomes `E_TWIN_SCHEMA` on the way in and `E_REPLAY_SHAPE` on the way back, at the member's path, with the message `the member cannot be read`; `KeyboardInterrupt` and other classes outside `Exception` pass through. The constructor reads the `instant` and `basis` of a caller's `TimeContext` the same way and refuses a raising read as `E_CONTEXT_TIME` at `time_context.instant` or `time_context.basis`. The depth guard treats a container whose members cannot be listed as having no children, so the structure check reads it and refuses it at its path. `_check_object` lists the keys once and judges presence on that list. Nothing else is wrapped, so an error of the adapter's own code stays visible as what it is (adjudication S-05).
- **Why.** R21: no foreign exception may leave the public interface; a dict or list subclass passes the `isinstance` admission and could raise from `to_cdm`, `validate_source`, `from_cdm` and `encode`, and a `TimeContext` subclass from the constructor. R26 made a bytes-like subclass that raises a coded refusal the same way (D93).
- **Alternatives.** Admitting only the exact `dict`, `list` and `tuple` (rejected: it changes what the contract admits); wrapping a whole stage in `except Exception` (rejected: it would also re-code a defect of the adapter); refusing in the depth guard at `$` (rejected: the member's path is known only to the structure check).
- **Covering tests.** `test_t12_envelope_container_whose_read_raises_is_twin_schema` (`to_cdm` and `validate_source`) and `test_t11_residual_container_whose_read_raises_is_shape` (`from_cdm` and `encode`) in `tests/test_cdm_dis7_replay.py`, and `test_constructor_refuses_a_time_context_whose_read_raises` in `tests/test_cdm_dis7_adapter.py`.

### D113 — Check O builds the adapter before it feeds the oversized payload (F-39)

- **What.** `suite.check_resource_limits` builds the adapter through `fixture_instance` in a `try` of its own before it feeds the oversized payload. A crash class raised while building is FAIL (`building the adapter through fixture_instance raised a crash class: <name>`), any other exception while building is FAIL (`the adapter could not be built through fixture_instance, so the declared bound was not exercised: <module>.<class>`), and the feed's two `except` clauses and its final FAIL are unchanged. The maintainer's approved bump ruling for `synapse_cdm/suite.py:check_resource_limits` (PATCH) stands under `### Unreleased` of MIGRATIONS.md between the rulings for `suite.py:_worker_main` and `suite.py:main`, the order of the units, and the bump gate reads MINOR with nothing unruled.
- **Why.** Final review F-39: a refusal raised by an overriding hook was read as the adapter refusing the bound, a PASS without the payload ever reaching `to_cdm`. The maintainer approved the ruling and asked for the fix before a release commit is drafted (answer 2 of 2026-10-05).
- **Alternatives.** Shipping F-39 as a stated limitation (the maintainer chose the fix); reading a construction refusal as SKIP (rejected: the proposal the maintainer approved says FAIL, and a SKIP of a required check would read as a declared inapplicability, which it is not).
- **Covering tests.** `tests/test_cdm_fixture_instance.py::test_a_hook_refusal_is_not_read_as_the_bound_refusing`, which fails on the tree as R31 found it and passes now; the existing assertion that the hook-built double reads `refusal == Q + "CodedInputTooLarge"` is unchanged and passes.

### D114 — The docs audit is cleared on the arc, by three overrides and one time-bounded exception

- **What.** The CI job "npm audit over docs/" named five unexcepted high advisories over the committed lock. Three `overrides` entries in `docs/package.json` (`brace-expansion ^1.1.20`, `http-cache-semantics ^4.3.0`, `joi ^17.13.7`), each at the lowest version that clears its advisories, clear four of them; the lock refresh moved exactly those three packages. The fifth, `braces` GHSA-vfj7-8cjw-p6xm, has no fixed version and is excepted by `security/exceptions/GHSA-vfj7-8cjw-p6xm.json`, owner the maintainer, created 2026-10-05, expiry 2026-12-04. `SECURITY.md`, the supply-chain page, `security/README.md`, `security/exceptions/README.md` and `### Unreleased` of MIGRATIONS.md state the ten overrides and the one exception, with dated corrections where a sentence said none.
- **Why.** The maintainer's ruling of 2026-09-07 makes high and critical findings block a release, and answer 3 of 2026-10-05 decided the fix on this branch and never as a separate change to `main`, which moves only once, at the release.
- **Alternatives.** A floor at `^1.1.21` for `brace-expansion`, which READINESS.md suggested (rejected: the run asks for the lowest version that clears each named advisory, and the caret resolves to 1.1.21 anyway); `npm audit fix` (rejected: the repository's own record shows it downgrading `qs` into its vulnerable range); a written ruling that the advisories do not block (not chosen by the maintainer); the owner as the security mailbox, as the two `image-size` exceptions had it (rejected: the ruling names the maintainer as owner, and the schema asks for a handle or an address of the person who answers for it).
- **Covering tests.** `tests/test_cdm_security_policy.py::test_every_floor_the_docs_manifest_pins_is_named_in_the_policy_and_counted_on_the_page` and the module `tests/test_cdm_security_exceptions.py`, which validates the new file against the schema and fails the suite the day after its expiry; the job's own decision step, re-run over the new lock, reads `OK`.

## Frozen contract

### Public API

```python
decode_pdu(raw) -> dict                 # one decoded PDU or Dis7Error
encode_pdu(pdu) -> bytes                # lossless; all fields required
TimeContext(instant, basis)             # frozen; stores the normalised instant, verbatim basis
Dis7Adapter(clock=None, *, session, synthetic, time_context=None, source_hash=None)
    .to_cdm(raw) -> [Entity]            # bytes-like PDU, or dict envelope {pdu, wire_hex, time_context}
    .from_cdm(objects) -> bytes         # list of exactly one unchanged Entity -> original bytes
    .detect(raw) -> bool                # cheap; bounded; never raises
    .validate_source(raw) -> list[str]  # [] or ["CODE at PATH: message"]
    .decode / .encode                   # SDK aliases
parse_json_text(data: bytes) -> object  # host loader (dis7_host)
```

- `session` and `synthetic` use private sentinels as signature defaults so omission raises `Dis7Error`, not `TypeError`. There is no usable default. `synthetic` is checked with `type(x) is bool`; `session` by `fullmatch`.
- Constructor checks run session → synthetic → time_context → source_hash, then `super().__init__(clock=clock, synthetic=synthetic)`.
- `to_cdm` accepts `bytes`, `bytearray`, `memoryview` (always a PDU) and `dict` (always an envelope). `from_cdm` accepts a list of `Entity` instances.
- `to_cdm` copies what it keeps from an envelope once the guard has bounded it; outputs never alias inputs; the instance holds only immutable context.

### Error model and codes

`class Dis7Error(ValueError)` exposes `code`, `path`, `message`; `str()` is `"CODE at PATH: message"`. `Dis7InputTooLarge(Dis7Error, InputTooLarge)` and `Dis7InputTooDeep(Dis7Error, InputTooDeep)` carry `E_INPUT_LIMIT` and satisfy the SDK's roster tests by inheritance. Both are defined in `dis7_codec.py`; `decode_pdu` raises `Dis7InputTooLarge` above 4224.

After the class statement `Dis7Adapter.to_cdm` is wrapped once more by a coded guard that runs before the SDK's wrapper, in this order:

1. Size: bytes-like input is converted once with `bytes(raw)` and that copy is measured and decoded, so a memoryview of any item size counts as its octets; `str` by UTF-8 length. Over 4224 → `Dis7InputTooLarge` naming both numbers (4224 itself is accepted).
2. Type: anything that is not bytes-like or `dict`, including an in-bounds `str` → `E_INPUT_TYPE`.
3. For a `dict`: an iterative depth walk with an on-stack set for cycles and a per-object memo, so each distinct container is visited once. Depth over 16 or a cycle → `Dis7InputTooDeep`. Shared non-cyclic references are accepted.

The manifest declares `max_input_bytes = 4224` and **`max_depth` absent with a reason** ("octets are one PDU and never JSON text; the envelope is held to 16 levels and acyclicity by the adapter's coded guard"), following the shipped binary adapters that have parsed twins (cat021, cat048, gmti, stanag4586 and others). That keeps the SDK's text-scanning depth guard from ever running on PDU bytes.

Messages never echo payload bytes, foreign keys or source strings; an unknown or duplicate key reports its parent path. Stage-2 traversal follows the schema's field order so diagnostics are identical under shuffled member order.

The 18 codes, in this order:

`E_INPUT_TYPE`, `E_INPUT_LIMIT`, `E_CONTEXT_SESSION`, `E_CONTEXT_SYNTHETIC`, `E_CONTEXT_TIME`, `E_CONTEXT_CONFLICT`, `E_CONTEXT_HASH`, `E_HEADER_UNSUPPORTED`, `E_LENGTH_MISMATCH`, `E_NONFINITE`, `E_TWIN_SCHEMA`, `E_TWIN_WIRE_MISMATCH`, `E_VALUE_RANGE`, `E_POSITION_DOMAIN`, `E_PROJECTION`, `E_REPLAY_SHAPE`, `E_REPLAY_PROVENANCE`, `E_REPLAY_CHANGED`.

### Validation order and paths

| Stage | Check | Code | Path |
|---|---|---|---|
| 0 | Constructor: session, synthetic, time_context, source_hash | `E_CONTEXT_SESSION` / `_SYNTHETIC` / `_TIME` / `_HASH` | `session`, `synthetic`, `time_context[.instant\|.basis]`, `source_hash[.algorithm\|.value]` |
| 1 | Size, type, depth, cycle (§4.3) | `E_INPUT_LIMIT`, `E_INPUT_TYPE` | `$` |
| 2 | Envelope structure: exact keys, JSON types, ranges, array and hex widths, hex syntax | `E_TWIN_SCHEMA` | member path; parent path for unknown keys |
| 3 | Wire length ≥ 144 | `E_LENGTH_MISMATCH` | `byte[<len>]` |
| 4 | Octets 0, 2, 3 equal 7, 1, 1, compared in that order | `E_HEADER_UNSUPPORTED` | `byte[0]`, `byte[2]`, `byte[3]` |
| 5 | `len == header.length`, then `header.length == 144 + 16·count` | `E_LENGTH_MISMATCH` | `byte[8]`, then `byte[19]` |
| 6 | Velocity, position, orientation finite, ascending offset | `E_NONFINITE` | `byte[36+4i]`, `byte[48+8i]`, `byte[72+4i]` |
| 7 | Twin equals decoded wire (±0 equal), §4 field order | `E_TWIN_WIRE_MISMATCH` | `pdu.<field>[i]` |
| 8 | Time context present and valid; constructor vs envelope agreement | `E_CONTEXT_TIME`, `E_CONTEXT_CONFLICT` | `time_context[.instant\|.basis]` |
| 9 | Radial domain; convergence; finite in-range outputs | `E_POSITION_DOMAIN`, `E_PROJECTION` | `byte[48]` |
| 10 | Final CDM validity | `E_PROJECTION` | `$` |

Other frozen paths: `encode_pdu` uses bare field paths (`variable_parameters_hex`, `velocity_mps[i]`, `header.length`); the text loader uses `$` or the parent path of a duplicate key; replay paths are rooted at the list (`$`, `[0].residual`, `[0].residual.data.<key>`, `[0].source.<field>`, `[0].<field>`).

Text loader codes: over 65536 bytes or lexical depth over 16 → `E_INPUT_LIMIT` at `$`; invalid UTF-8, a byte-order mark, a wide encoding, unparseable text, `NaN`/`Infinity` tokens, overflowing or oversized numbers → `E_TWIN_SCHEMA` at `$`; a duplicate key → `E_TWIN_SCHEMA` at the parent path. The replay command re-codes a loader `E_TWIN_SCHEMA` as `E_REPLAY_SHAPE` with the same path. A standalone `TimeContext(...)` failure reports `time_context.instant` or `time_context.basis`.

### Replay order

Order, resolving a disagreement between spec lines 219 and 221 (CR-22):

1. Constructor context (stage 0).
2. **Shape** → `E_REPLAY_SHAPE`: not a list of exactly one, wrong kind, residual missing, namespace not `DIS`, `residual.data` failing the residual schema's shape.
3. **Stored context**, needing no wire → `E_REPLAY_PROVENANCE`: adapter session and synthetic vs stored; egress time context and hash vs stored; stored instant not normalised.
4. **Residual consistency** → `E_REPLAY_CHANGED`: `wire_hex` fails stages 3–6, `residual.pdu` ≠ decoded wire (±0 equal), or reconstruction from the stored wire and context refuses at stage 9 or 10.
5. **Source vs reconstruction** → `E_REPLAY_PROVENANCE`: `source.*` in spec order, then `source_ids`.
6. **Remaining canonical fields** → `E_REPLAY_CHANGED`.

Comparison is on Python values, field by field: datetimes exact to the microsecond (a serialised dump would hide sub-millisecond edits), floats exact with ±0 equal, residual data by a bounded structure-directed comparison. On success the bytes returned are decoded from `wire_hex`, never rebuilt.

`from_cdm` raises only stage-0 context codes and the three replay codes. It never deep-copies, dumps or schema-validates its argument generically: step 2 walks only the residual schema's known keys and refuses anything else at its parent path, and the comparison iterates `Entity.model_fields` with `getattr`. It leaves its argument unchanged.

The profile overlay `dis7-entity.schema.json` is a test oracle, not a shape gate: as a gate it would turn cases N15 and N16 into `E_REPLAY_SHAPE`.

### Mutation seams

| Fault (spec §16) | Seam | WP | Killed by |
|---|---|---|---|
| Swap latitude and longitude | `dis7._assemble_position` | 4 | adapter-level A03 (49° N, 16° E); north-pole vector |
| Body velocity treated as world | `dis7_codec.WORLD_ALGORITHMS` | 3 | adapter-level A04, codes 6–9 at the equator seed |
| Drop an opaque record | `dis7_codec._decode_records` | 2 | A02 (255 records), A08, vector 3 — asserting the decoded view, not only replay |
| Affiliation from force ID | `dis7._affiliation` | 4 | A08, vectors |
| Receipt time (two variants: `self.now()`, `datetime.now()`) | `dis7._state_instant` | 4 | adapter-level A07 and A10 |
| Change the UUID namespace | `ids.NAMESPACE` | — | A01, A06 with literal UUIDs |
| Restamp the DIS timestamp | `dis7._replay_bytes` | 4 | adapter-level A07 replay |
| Stale PDU after a canonical edit | `dis7._canonical_equal` | 4 | N15, N16 |

Two traps make naive killers blind, so the killer tests must avoid them: every vector's DIS timestamp `0x40000001` is exactly the DIS encoding of the fixture instant's minutes, and the fixture instant equals the SDK's `FROZEN_NOW`. Killer tests therefore use a state instant different from `FROZEN_NOW` and not at hh:15:00, a clock fixed at a different instant from the context, and, for the restamp fault, a seed whose bytes 4–7 differ from the encoding of the instant.

## Optional-extension register

| Extension | Why it does not alter the mandatory profile | State |
| --- | --- | --- |
| `parse_json_text`, a public host loader | Cases N18 and N20 need an API for envelope text and the contract names none (CR-11); it only adds refusals. | delivered |
| `Dis7InputTooLarge`, `Dis7InputTooDeep` | Both are `Dis7Error` with `E_INPUT_LIMIT`; the second base class only lets code that catches the SDK's classes see the same refusal. | delivered |
| Sentinel defaults for `session` and `synthetic` | Omission still fails, as a coded `Dis7Error` instead of `TypeError` (CR-10); there is no usable default. | delivered |
| Optional `--session`, `--synthetic`, `--live` on `replay` | Replay binds both from the stored residual; a flag is only asserted against it (CR-17). | delivered |
| `Adapter.fixture_instance`, Adapter API 3.1.0 | Additive; the default is the previous construction; the DIS7 override serves the packaged fixtures only and refuses `synthetic=False` (CR-21, D1). | delivered |
| `times.render` four-digit year | Years 1000 to 9999 print as before; smaller years gain zero padding (CR-32, D7). | delivered |
| `evidence.digest_bytes` | A new function, existing ones untouched; it keeps hash imports out of the DIS7 adapter modules (D2). | delivered |
| An implementation in another language | No second implementation is part of this delivery; Python is the only one. | not delivered |
| `detect` reading an envelope's header | A dict is judged by its PDU header alone, so `detect` stays cheap, bounded and never raises (CR-28). | delivered |
| A network listener | The adapter and `synapse-dis7` read bytes the caller supplies and open no socket. | not delivered |
| An adapted command spelling | The command is spelled `synapse-dis7` with the four commands of the contract and no alias. | not delivered |

## Sequencing deviations

The work follows the spec's six work packages (R29) in order, with four sequencing deviations that are logged in the delivery report: vectors and contract files are vendored in WP1, because WP2's independent layout tests seed from them; the vector tests (R25) run in WP4; the SDK hook, the `times.render` fix and Adapter API 3.1.0 land in WP1 as part of the API freeze; and the class sits under `adapters/` from WP4 (F5). R28 is read as the single WP4–WP6 commit and push: nothing DIS7 reaches a pushed ref or a built artefact before WP6's gates pass.

## Progress

### R02 — wp1a-vendor

- `.gitattributes`: appended the DIS 7 block (blank line, 4-line comment, `*.dis -text -diff`, `packages/cdm/synapse_cdm/fixtures/dis7/vectors/** -text`, `packages/cdm/synapse_cdm/fixtures/dis7/contract/** -text`) verbatim per Deliverable 1, before any vendored file was staged.
- `pkg/fixtures/dis7/vectors/`: the 16 bundle files (`index.json` plus 5 files each for `equator_eastbound`, `north_pole_stationary`, `unprojectable_with_extensions`) copied with `cp`, `cmp`-identical to `RUN/bundle/vectors`.
- `pkg/fixtures/dis7/contract/`: `acceptance-cases.json` and the five `dis7-*.schema.json` files, `cmp`-identical to the bundle; `cdm-entity.schema.json` deliberately not vendored (confirmed absent).
- `PROVENANCE.json` written in both `vectors/` and `contract/`: `synapse.fixture-provenance/v1`, 16 and 6 rows respectively, each `synthetic: true` / `classification: PUBLIC`, `origin` text copied verbatim from the run file, `standard_ref` `dis7/spec/dis7_pin.json`, rows sorted by `file`.
- `pkg/fixtures/dis7/spec/dis7_pin.json`: built to the given structure; `manifest_sha256` confirmed against `shasum -a 256 bundle/MANIFEST.json`; all 22 `vectors.files`/`contract.files` rows carry the bundle's `sha256`/`bytes`; no node anywhere carries a `local_path` key.
- `pkg/fixtures/dis7/` holds exactly `spec/`, `vectors/`, `contract/` and the 25 files — no top-level file, no `golden/`, no `malformed/`.
- Two `TREE_EXEMPT` rows added to `tests/test_cdm_prose_counts.py` directly after the second `schemas/entity.schema.json` row, middle strings copied character-for-character (including the literal `\n\n` and `—` escapes), third string identical and written in full in both rows.
- `pkg/FORMAT_COVERAGE.md`: row `| 21 | \`dis7\` | specification, Phase 1 | ...` inserted directly after row 20 (`aixm52`); the five-line paragraph under the table replaced with the two-paragraph "TWO rows are at Phase 1" / "`dis7` at #21" text verbatim; no DIS section added; the "Row sets written as specifications, with no adapter code yet" list left untouched (still two entries).
- `tests/test_cdm_harness.py`: `PLANNED_FIXTURE_DIRS` extended to `{"stanag5527": "fft", "dis7": "dis7"}` with the given comment; `SHIPPED_FIXTURE_DIRS` untouched.
- `tests/dis7_support.py` written: `FIXTURES`/`VECTORS`/`CONTRACT` resolved off `synapse_cdm.__file__`, `STEMS`, `vector_bytes`, `vector_json` (raises `ValueError` on bad `stem`/`kind`), `seed`, `patch` (raises `ValueError` on out-of-range offset/data, leaves the input unmutated). No `test_` function in this module.
- `tests/test_cdm_dis7_schema.py` written with the 13 named tests (none named `test_t<digit>`), the two module-level helpers `_schema(name)` and `_errors(schema, instance)`, the `BUNDLE_MANIFEST` and `CDM_ENTITY_SHA256` literals copied from the bundle manifest (never computed from the vendored files), and the module docstring naming `SC DIS7 SPEC 001 v1.0` as a handoff document not in this repository. 48 tests collected (13 functions, several parametrised over 22 files / 5 schemas / 3 stems), all passing on 3.14, 3.11 and 3.12.
- `gates/wheel_install.py`: `"test_cdm_dis7_schema.py"` appended to `PACKAGE_ONLY_TESTS` with the given comment, after `"test_cdm_mismms.py"`.
- `pkg/MIGRATIONS.md` `### Unreleased`: the `**What moved inside the distribution: ...**` paragraph replaced with the two given paragraphs (27-file count, the "THE DIS 7 CONTRACT IS VENDORED AHEAD OF THE ADAPTER" paragraph), keeping "no release" and "3.1.1"; `git diff --name-only v3.1.1 -- packages/cdm | wc -l` prints 27.
- No edit to `tests/test_cdm_ordinals.py`; no ordinal-claim phrase naming this adapter's number was written anywhere (`git grep` confirms empty); no roster-count phrase was introduced.
- All 33 files staged by explicit path; `git diff --quiet` true; `git ls-files --others --exclude-standard` empty; HEAD unchanged at `c4bba1b6ebfdfe956f6efc2b3a81a04db2b4bb5b`.
- Exit check `bash RUN/checks/R02.sh` ends `EXIT-CHECK: PASS`, 0 blocked steps (see `logs/R02.exit.log`).
- `docs/dis7-implementation.md` does not exist yet (it is introduced in R03 per the run file's Paths section), so step 3 of "How to finish this run" does not apply this run.

### R03 — wp1a-freeze

- Wrote this record, assembled from `PLAN.md` and `rulings.md` with a throwaway script kept outside the worktree: the thirteen `## ` headings in order, F1 to F11 as D1 to D11, CR-01 to CR-35 as D12 to D46, the five Frozen contract subsections and the 18 codes, the Baseline table read from `reports/baseline.md`, and one decision of this run's own, D47.
- Wrote `pkg/adapters/dis7_codec.py`: the complete error model only — `Dis7Error`, `Dis7InputTooLarge`, `Dis7InputTooDeep` and the 18 code constants plus `CODES`; no stub of any later function.
- Wrote `tests/test_cdm_dis7_codec.py` (10 tests): the code table, the two input-limit subclasses' MROs, the `str()` form, and survival of copy and pickle — the evidence for requirement R21.
- Wrote `tests/test_cdm_dis7_trace.py` (10 tests): the two-way ratchet (`scan_source`, `scan_tree`, `evidence_problems`, `bound_ids`, `ratchet_problems`) over the contract's 38 cases and R01 to R30; `PENDING` holds the 67 ids this run does not bind, and `R_EVIDENCE` binds R21 to the six tests above. No id came back already bound, so none was removed from `PENDING`.
- Bookkeeping: the `CLONE_ONLY_SITES` row for this record in `tests/test_cdm_consumer_path.py`; `test_cdm_dis7_codec.py` added to `PACKAGE_ONLY_TESTS` and `test_cdm_dis7_trace.py` to `REPO_BOUND_TESTS` in `gates/wheel_install.py`; `pkg/MIGRATIONS.md`'s `### Unreleased` raised to 28 files with `dis7_codec.py` named.
- All seven files staged by explicit path; `git diff --name-only v3.1.1 -- packages/cdm | wc -l` prints 28.
- Exit check `bash RUN/checks/R03.sh` and its result are reported in `reports/R03-runner.md`.

### R04 — wp1b-hook

- Added `Adapter.fixture_instance(clock=None, *, synthetic=True)` directly after `encode()`; its default is `cls(clock=clock, synthetic=synthetic)`, the clock passed by keyword. `load_adapter` moved from line 654 to 671; `SECURITY.md` and `tests/test_cdm_security_policy.py` re-pinned to 671.
- Routed the seven package sites (`harness.main`; `suite._fresh`, `suite._worker_main` twice, `suite._sweep`, `suite.main`; `evidence.generate`) and the eleven test sites through the hook.
- Added `harness.overrides_fixture_instance` and `harness.fixtures_refused_message`, the `--fixtures` refusal in the three entry points, the exit-2 handling of a hook refusal in `harness.main`, `suite.main` and `suite._sweep` (D48 to D50), and the packaged-fixture paragraph of `suite.run`'s docstring.
- Wrote the helper `tests/fixture_instance_double.py` (`RequiresContext`, `ContextDouble`, a coded outer guard) and `tests/test_cdm_fixture_instance.py`, eighteen test functions, added to `PACKAGE_ONLY_TESTS`.
- `pkg/MIGRATIONS.md`'s `### Unreleased` raised to 32 files with `adapter.py`, `harness.py`, `suite.py` and `evidence.py` named. No bump ruling (R06), no `ADAPTER_API_VERSION` change (R05).
- Exit check `bash RUN/checks/R04.sh` and its result are reported in `reports/R04-runner.md`.

### R05 — wp1b-sdk

- WP1 step 9: `evidence.digest_bytes(data)`, the SHA-256 and size of octets the caller holds, added below `digest`; `digest`, the imports and the module docstring are unchanged, and `hashlib` is still imported by `evidence.py` alone (D51).
- WP1 step 10: `times.render` writes the year as four digits itself, not through `strftime`'s year directive; output for years 1000 to 9999 is byte-identical. Tests in `tests/test_cdm_adapter_contract.py` (values for years 1 and 999, four-digit years, and an AST check that no string constant of `render` holds the directive) pass on 3.14, 3.11 and 3.12.
- WP1 step 11: `ADAPTER_API_VERSION` reads 3.1.0 in `version.py` (constant, `#:` block, docstring row), `VERSIONING.md` §2, `ARCHITECTURE.md` §1.2 (a `fixture_instance()` row) and the generated block of `docs/docs/current-contracts.mdx` (`current-contracts: CURRENT`).
- `pkg/MIGRATIONS.md`'s `### Unreleased` raised to 34 files with `times.py` and `version.py` named, and the paragraph that begins `DIS 7 UNIT 1B, SDK HELPERS` added. No bump ruling is in the repository.
- Open, WP1 step 12: the bump-ruling proposals are written to the pipeline's `maintainer/bump-wp1b.proposed.md`, one per unit the bump gate lists as unruled; they wait for the maintainer's rulings, which run R06 pastes.

### R06 — wp1b-rulings

- WP1 step 12 complete: the bump rulings are the maintainer's, pasted verbatim from the approved file into `pkg/MIGRATIONS.md`'s `### Unreleased`, ten paragraphs, directly after the paragraph that begins `DIS 7 UNIT 1B, SDK HELPERS`; the file list and its count clause are unchanged. `gates/bump_derivation.py --json` reads the pending arc as MINOR, 3.2.0, with nothing unruled.
- Unit 1b exit passed: the full suite reads 6813 passed, 182 skipped on the staged tree, CPython 3.14.
- The commit is the maintainer's; the message is drafted outside the worktree.

### R07 — wp2-decode

- `pkg/adapters/dis7_codec.py` gained the wire constants (`MIN_PDU_BYTES`, `MAX_PDU_BYTES`, `RECORD_BYTES`, `MAX_RECORDS`), `decode_pdu`, the record seam `_decode_records` and the header predicate `looks_like_entity_state`. Checks run in contract order (type, size bound, minimum length, octets 0, 2, 3, declared length, record count, the nine vector components in ascending offset) and every refusal carries its frozen code and path; a memoryview of any item size is read as its octets (CR-29). Decisions D52 to D54.
- `tests/dis7_support.py` gained `walking_pdu()`, a 176-octet PDU built from `struct` and literals.
- `tests/test_cdm_dis7_codec.py` binds A01 (T01), N01 to N08 (T02), N09 and A02 (T03), N36, N48 and N72 (T04), with the refused-category, bracket, defect-order, predicate, input-type and no-foreign-exception tests. `tests/test_cdm_dis7_schema.py` validates five decoded PDUs against `dis7-pdu.schema.json`, with a control that can fail.
- The trace table's `PENDING` lost the eighteen ids the ratchet named stale: A01, A02, N01 to N09, N36, N48, N72, R08, R09, R14 and R22; R21's evidence gained the fuzz test.
- The DIS 7 test modules pass on CPython 3.14, 3.11 and 3.12. No file under `packages/cdm` was added, so `### Unreleased` is unchanged.
- Left for R08: `encode_pdu`, round-trip assertions, N10, counts 0, 1, 254 and 255, the multi-octet memoryview tests, the encoder fuzz, the `### Unreleased` sentence and the WP2 commit draft.

### R08 — wp2-encode

- `pkg/adapters/dis7_codec.py` gained `encode_pdu`, the lossless inverse of `decode_pdu`. It validates in the five CR-04 stages, each finished over every member in decode order before the next begins: structure (`E_TWIN_SCHEMA`), header constants (`E_HEADER_UNSUPPORTED`), declared length against the record count (`E_LENGTH_MISMATCH`), finite vector components (`E_NONFINITE`), then integer ranges, pack-then-unpack representability and hex characters (`E_VALUE_RANGE`). Every refusal is a plain `Dis7Error` with a bare field path; the only handler is the one around `struct.pack`. The module docstring says the module also encodes. Decisions D55 and D56.
- `tests/test_cdm_dis7_codec.py` binds N10 (T03) and adds the round trips of the three twins and the walking pattern, record counts 0, 1, 254 and 255, the maximal PDU, the stage-1 paths, booleans, header constants, length, the non-finite components, wire-width refusals, exact encodings and signed zero, integer widths, integral floats, hex characters, the stage-order pairs, tuples without mutation (CR-29), the two multi-octet memoryview cases and the encoder fuzz; the decoder fuzz now asserts `encode_pdu(decode_pdu(raw)) == raw`.
- The trace table's `PENDING` lost N10; R21's evidence gained the encoder fuzz test.
- `### Unreleased` gained the paragraph on the codec; its file list and count clause are unchanged. The WP2 commit draft for the maintainer is written outside the worktree.
- The DIS 7 test modules pass on CPython 3.14, 3.11 and 3.12.

### R09 — wp3-time

- `pkg/adapters/dis7.py` is new and holds no adapter class: `TimeContext` (a frozen dataclass whose instant is checked by an anchored ASCII-digit pattern and explicit range checks, normalised to UTC as `YYYY-MM-DDTHH:MM:SS.mmmZ`, and whose basis is kept verbatim), `BASIS_WHITESPACE`, `validate_session`, and the identity helpers `external_id`, `identity_system` and `entity_uuid`, the last through `ids.derive`. It re-exports the error model of `dis7_codec.py`. Decision D57.
- `tests/test_cdm_dis7_time_identity.py` binds A06 (T08), N13 and A07 (T09) at helper level against literal UUIDs and literal normalised instants, with the basis, frozen-context and session tests; it is listed in `PACKAGE_ONLY_TESTS`.
- The trace table's `PENDING` lost A06, N13, A07 and R11; R10 stays pending until N12 is bound.
- `### Unreleased` names `adapters/dis7.py` in its file list, its count clause moved by one, and it gained the paragraph on the module.
- The DIS 7 test modules pass on CPython 3.14, 3.11 and 3.12.
- Left for R15: the adapter-level halves of A06, A07 and N13.

### R10 — wp3-geodesy

- `pkg/adapters/dis7_codec.py` gains the WGS84 constants, `PROJECTION_MAX_ITERATIONS` (the iteration-cap seam), `WORLD_ALGORITHMS` (a mutation seam), `ecef_to_geodetic` (the origin returns `None` by value, CR-35; the radial domain; the pole branch; the reference iteration with an explicit convergence flag; finite in-range outputs; negative zero normalised) and `velocity_to_kinematics` (horizontal speed, course and climb; no course at zero speed or exactly at a pole; a computed 360 emitted as 0; negative zero normalised). Nothing calls them yet. Decisions D58, D59 and D60.
- `tests/dis7_support.py` gains `geodetic_to_ecef`, the forward conversion with its own literals.
- `tests/test_cdm_dis7_geodesy.py` binds A03 and N11 (T05), A04 (T06) and A05 (T07) at helper level, with the iteration-cap seam and the three-layer oracle (T16); it is listed in `PACKAGE_ONLY_TESTS`.
- The trace table's `PENDING` lost A03, N11, A04, A05, R15, R16 and R17; A13 and A14 stay pending.
- `### Unreleased` gained the paragraph on the helpers; its file list and count clause are unchanged.
- The DIS 7 test modules pass on CPython 3.14, 3.11 and 3.12.
- Left for R12 and R15: calling the helpers from the adapter and the adapter-level halves of A03, N11, A04 and A05.

### R11 — wp4-loader

- `pkg/dis7_host.py` is new: the host boundary's strict JSON text loader `parse_json_text` with `MAX_JSON_BYTES` and `MAX_JSON_DEPTH`, checking type, size, NUL, strict UTF-8, byte-order mark and lexical depth before the decoder, which is handed the decoded text with four hooks, then walking the document for a repeated key. No command line, no file access. Decisions D61 to D64.
- `tests/test_cdm_dis7_replay.py` is new with the frozen helpers and eighteen loader tests: the duplicate-key tests bind N18 (T12) and the bound tests bind N20 (T03); the token, encoding, number and surface tests are named `test_t12_text_` and bind nothing. It is listed in `PACKAGE_ONLY_TESTS`.
- The trace table's `PENDING` lost N18, N20 and R12. The table has no notion of half a case: the dict half of N18 and further native N20 tests arrive in R12 and R14 under the same case ids.
- `### Unreleased` names `dis7_host.py` in its file list, its count clause moved by one, and it gained the paragraph on the loader.
- The DIS 7 test modules pass on CPython 3.14, 3.11 and 3.12.
- Left for R16: the command line, file reads, hashing and the replay command's re-coding of a loader `E_TWIN_SCHEMA` (CR-27).

### R12 — wp4-adapter

- `pkg/adapters/dis7.py` now holds `Dis7Adapter`, registered as `dis7`: the registry holds twenty. It adds `FIXTURE_SESSION`, `FIXTURE_TIME_CONTEXT`, `MAX_ENVELOPE_DEPTH`, the five seams, the envelope and residual structure checks, `_twin_difference`, the coded guard installed outside the SDK wrapper, the constructor with its context checks, `fixture_instance`, `to_cdm` for octets and envelopes, the canonical mapping with stage 10, `from_cdm` in six steps, `detect` and `validate_source`. The declarations follow PLAN.md §4.9. Decisions D65 to D70.
- `tests/dis7_support.py` gains `fixture_adapter`.
- `tests/test_cdm_dis7_adapter.py` is new with the smoke tests (vectors on both paths, byte-exact replay, constructor defects and order, `fixture_instance`, the guard, the declarations); its case labels are A01, N09 and N20 only. It is listed in `PACKAGE_ONLY_TESTS`.
- The trace table and `### Unreleased` are unchanged: no new case is bound and no file under `packages/cdm` is added.
- The DIS 7 test modules pass on CPython 3.14, 3.11 and 3.12.
- Left for R13: the packaged fixtures, goldens, the malformed set and the ordinal flip, so the harness, ordinal and roster-bookkeeping tests stay red until then. Left for R14 and R15: the replay, envelope, `detect` and `validate_source` matrices and the stage 10 test.

### R13 — wp4-fixtures

- `fixtures/dis7/` gains its top level: the six harness fixtures (`<stem>.dis` and `<stem>.parsed.json` for the three stems, `cp` copies of `vectors/<stem>.dis` and `vectors/<stem>.envelope.json`), `README.md` and `PROVENANCE.json`; `golden/` with the six goldens the harness wrote with `--update-golden`, each equal to `vectors/<stem>.expected.json` as sorted JSON text; and `malformed/` with five refusal payloads (`wrong_protocol_version.dis`, `pdu_type_67.dis`, `truncated_by_one_byte.dis`, `one_trailing_byte.dis`, `envelope_unknown_key.json`), its `README.md` and `PROVENANCE.json`. No adapter or codec repair was needed: every harness column read as planned on the first run and every payload was refused with the planned code and path.
- `FORMAT_COVERAGE.md`: the `dis7` ordinal row reads `shipped`; the paragraph under the table is the baseline text again, with two lines saying the second Phase 1 row has closed.
- `tests/test_cdm_harness.py`: `dis7` moved from `PLANNED_FIXTURE_DIRS` to `SHIPPED_FIXTURE_DIRS`, and the comment above the planned map says so. `tests/test_cdm_ordinals.py`: `SWEPT` lists the fixture README. No earlier DIS 7 test asserted the holding state, so no existing assertion changed.
- `tests/test_cdm_dis7_schema.py` gains four tests (byte identity of the top-level fixtures, the directory layout, the nesting bound, the two provenance records); `tests/test_cdm_dis7_adapter.py` gains the golden test, the harness test under two clocks, the malformed-set test and one test per payload, with the `REFUSALS` table. The cases bound are A01, N01, N02, N06 and N07; the trace table is unchanged.
- `.gitattributes` holds the top-level envelope twins and the malformed JSON out of line-ending conversion.
- `### Unreleased` names the new files, its count clause moved by the new files, and the holding-state sentences of earlier steps are now past tense and name `Dis7Adapter` (D71).
- The harness reads `6 passed, 0 failed` under the default clock and under `--now 2031-01-02T03:04:05Z`; the conformance run with `--require A,B,C,D,E,F,G,H,J,K,L,N,O` exits 0. The DIS 7 test modules pass on CPython 3.14, 3.11 and 3.12. The registry holds twenty.
- Left for R14 to R22: the replay and envelope matrices, the acceptance sweep, the CLI and the roster bookkeeping (manifest, support matrix, count prose) that stays allowlisted debt until WP6.

### R14 — wp4-replay-tests

- `tests/test_cdm_dis7_replay.py` gains forty tests and their helpers. T11 replays through `Dis7Adapter.from_cdm`: byte-exact replay of the three vectors on both paths, one refusal per canonical field (N15), per `source` field, per scoped identity edit and per stored or constructor context member (N16), the wrong-shape inputs (N17), the residual shape gate, cyclic and very deep residuals, single-view edits, the three wire and view pairs at octets 1, 17 and 88 (CR-22), the check order under two defects and an unchanged argument. T12 drives the envelope structure through `to_cdm(dict)`: unknown, missing, short, long, wrongly typed, boolean, out-of-range and non-finite members (the dict half of N18) and a twin that disagrees with the wire at every member (N19). T03 holds the native half of N20: seventeen levels of each container kind, cycles and shared references measured at their deepest use.
- No defect was exposed: every new test passed against `adapters/dis7.py` and `adapters/dis7_codec.py` as R12 left them, so neither module changed.
- The module's existing `_depth` helper now also counts a `tuple` as a container, which the native depth rows need; the loader tests read the same depths, as JSON text never yields a tuple.
- The trace table's `PENDING` lost N15, N16, N17 and N19; no requirement followed.
- `### Unreleased` and the wheel-gate lists are unchanged: no file under `packages/cdm` moved and no test module was added.
- The DIS 7 test modules pass on CPython 3.14, 3.11 and 3.12.
- Left for R15: the acceptance sweep, emitted-output schema validation and the remaining T09, T10 and T13 to T15 tests.

### R15 — wp4-acceptance

- `tests/test_cdm_dis7_adapter.py` gains the acceptance sweep: three item kinds (`Accept`, `Refuse`, `RefuseConstruct`), one runner and the builder table `SWEEP_BUILDERS` with its count table `SWEEP_COUNTS`, 28 keys, one per case whose operation reaches the adapter (A01 to A11, N01 to N09, N11 to N14, N21, N36, N48, N72). Every accepted item also validates against `dis7-entity.schema.json`, replays byte-exact and reads `[]` from `validate_source`; every refusal asserts code and path, that nothing was returned and the one `validate_source` string.
- The same module gains the named tests: the index walk (R25), T09 (N12, N14), T10 (A08 over every force ID and entity kind, the opaque-field rule of R17), T13 (A10: no socket, no clock, an unchanged harness report under another `--now`, three hash seeds in child processes, member order, eight parallel instances, no mutation or aliasing, the import and call scan) with the three R22 tests, T14 (A11 and N21, the SDK CLI refusals, the four note shapes, a 1024-character basis, years 0001 and 0999, explicit nulls), and T15's SDK half with the `validate_source` and `detect` matrices, the stage 10 test (CR-09) and the bracket-leading and refused-format samples.
- `tests/test_cdm_dis7_schema.py` gains four tests: emitted Entities against the profile and the published Entity schema, emitted residuals and the envelopes rebuilt from them, the oracles' red half, and the stage 2 differential over 106 envelopes, whose only divergences are the classes of CR-03 and CR-05.
- The trace table's `PENDING` lost N12, N14, A08, A09, A10, A11, N21 and R04, R05, R06, R10, R13, R18, R19, R20 to the new tests, and R02, R03, R07, R25, R30 to new `R_EVIDENCE` entries.
- No defect was exposed: every new test passed against `adapters/dis7.py` and `adapters/dis7_codec.py` as earlier runs left them, so neither module, no golden, `### Unreleased` and the wheel-gate lists changed.
- The DIS 7 test modules pass on CPython 3.14, 3.11 and 3.12; the harness reads six passed and none failed; the WP4 exit's full suite fails only on allowlisted ids.
- Left for R16 to R19: the CLI (A12), the OpenDIS reference test (A13), the mutation gate (A14), the benchmark and the last pending rows.

### R16 — wp5-cli

- `dis7_host.py` gains the offline host command `synapse-dis7` beside `parse_json_text`: `decode`, `replay`, `self-test` and `--version`, the exit constants 0, 2, 3 and 4, the two specification constants, and the helpers `_read_bounded`, `_emit`, `_diagnose`, `_fixture_dir` and `_same_json`. Importing the module does not load `synapse_cdm.evidence`; `decode` imports it inside the handler for the SHA-256 of the file bytes.
- `pyproject.toml` declares `synapse-dis7 = "synapse_cdm.dis7_host:main"` with its dated comment, and the comment above `synapse` now says it was the one entry not spelled `cdm-*` until then. The package was reinstalled editable in the three interpreters.
- `tests/test_cdm_dis7_cli.py` runs the command as a child process with byte comparisons only: 91 passed (the count as of R30). It is listed in `PACKAGE_ONLY_TESTS`. The trace table's `PENDING` lost A12, R24 and R28.
- `### Unreleased` names `pyproject.toml` and the host command; the count clause moved to the new total.
- `self-test` reports 16 checks over the packaged vectors and four refusals.
- Not done here: the wheel gate's console-script check (R20), the CLI reference page (R22).

### R17 — wp5-reference

- `spec/build_fixtures.py` (shipped, never imported by the package) rebuilds the three packaged PDUs from literal scenarios through open-dis-python at `732b6655bb47e34ccc73722eefe0f4706fd0032f`, compares them with `vectors/` and writes nothing: with the pinned checkout it prints the all-equal line and exits 0.
- `tests/dis7_reference_support.py` resolves `SYNAPSE_CDM_OPENDIS_DIR`, verifies the commit and a clean tree, and drives OpenDIS in a child interpreter (`child_env()`); `tests/test_cdm_dis7_reference.py` binds A13 (and so R26): eleven always-on test cases and eighteen live ones under the `reference` marker, registered in `pytest.ini` beside `normative`. The module is in `REPO_BOUND_TESTS`; `PENDING` lost A13 and R26.
- Live half, with the checkout: `-m reference` passes with nothing skipped on 3.14 and 3.11. OpenDIS generates each packaged PDU byte for byte, its parse equals `decode_pdu` field by field (the canonical text too, so the sign of −0.0 agrees), the adapter ingests OpenDIS bytes and replays them exactly, OpenDIS reparses and reserialises each replay unchanged, a 255-record PDU agrees in both directions, and OpenDIS's type-67 and default zero-length PDUs are refused with `E_HEADER_UNSUPPORTED` at `byte[2]` and `E_LENGTH_MISMATCH` at `byte[8]`. No disagreement between OpenDIS and the codec was found.
- `spec/dis7_pin.json` gained `independent_reading_tool`, status `TAKEN`, with the tool versions of the reading; no existing row changed.
- The exercise report `opendis-732b6655.json`, under the pipeline directory's `exercise/` (category `independent_expected`, six of six directions AGREE), is provisional: the tree is uncommitted, and the post-commit gates re-run it on the final commit. No report is tracked.
- `### Unreleased` names `build_fixtures.py` and the count clause moved to the new total.
- Not done here: the mutation gate (R18), the benchmark (R19), `spec/dis7_terms.json` and the regeneration command's documentation (R22).

### R18 — wp5-mutation

- `gates/dis7_mutation.py` copies `packages/cdm` to a temporary directory outside the repository, runs the DIS7 test modules (all but the mutation and reference modules) against the copy with `-o pythonpath=<copy>` and `PYTHONPATH=<copy>`, plants a probe proving the package, `ids` and the two DIS7 modules were imported from the copy in process and in a child, and then applies each of the nine `MUTANTS` rows for the eight faults of case A14 in turn, restoring and byte-comparing the patched file after each run. No worktree file is patched.
- Command: `python gates/dis7_mutation.py --out <dir>/mutation-matrix.json`. The matrix `mutation-matrix.json`, under the pipeline directory's `reports/`, is the evidence for case A14 and requirement R27: control `GREEN` with `imported_from_copy` true, nine rows `DETECTED`, result `PASS`. No report is tracked.
- Every row was DETECTED on the first full run, so no killer test was strengthened. Every child Python of the DIS7 test modules already passed `PYTHONPATH` in the D-21 form and took the repository root from its own `__file__`, so no `env=` was changed.
- `tests/test_cdm_dis7_mutation.py` binds A14 (and so R27) with seven test functions, the last running the whole gate; it is in `REPO_BOUND_TESTS`. `PENDING` lost A14 and R27.
- T, the wall time of one unpatched run of the gate's modules, was about 16 seconds here; one gate run is ten such runs.
- No file under `packages/cdm` changed, so `### Unreleased` is unchanged.
- Not done here: the benchmark and the remaining trace rows (R19), the gate's documentation (R22).

### R19 — wp5-bench-trace

- `gates/dis7_benchmark.py` records requirement R23's measurements: a 1000-call warm-up and 100000 timed calls of `to_cdm` for the 144-byte equator vector and for case A02's 4224-byte PDU (built in-process from the seed, never written to disk), the machine and runtime versions, elapsed time, throughput, nearest-rank p50/p95 latency, peak process memory, and the traced memory retained by a second identical pass. Its verdict is `PASS` only if the bound holds (4224 octets accepted, 4225 refused with `E_INPUT_LIMIT` at `$`, case N09) and no input retains more than the allowance (D81); it reads no timing field, as no numeric SLA applies.
- `tests/test_cdm_dis7_benchmark.py` (7 tests, green on 3.14, 3.11 and 3.12) loads the gate from its source and runs the reduced workload on every test run; it asserts bound enforcement and the absence of retained growth, never a timing. It is in `REPO_BOUND_TESTS`.
- The trace table is complete: `PENDING` is empty, and `R_EVIDENCE` gained R01 (the trace meta-test), R23 (the reduced benchmark test and the benchmark report) and R29 (the verifier report of each unit's exit run).
- No file under `packages/cdm` changed, so `### Unreleased` is unchanged.
- Evidence artefacts in the pipeline's run directory (outside the repository):
  - requirement R23 → `reports/benchmark.json`, regenerated by `python gates/dis7_benchmark.py --out <file>`; measured on this run's staged tree (the WP5 snapshot) and not re-run after promotion or on the final commit. Its figures are recorded measurements, not a commitment;
  - requirement R27 (case A14) → `reports/mutation-matrix.json`, regenerated by `python gates/dis7_mutation.py --out <file>`;
  - requirement R26 (case A13) → the exercise report `opendis-732b6655.json` under `exercise/`, provisional until it is re-run on the final commit.
- Not done here: the manifest, the support matrix, the roster literals and A12's wheel-gate evidence (R20), the prose counts (R21), the benchmark's documentation (R22).

### R20 — wp6-roster

- Generated: `manifests/dis7.json` (the only manifest that moved), `docs/docs/cdm/support-matrix.mdx`; `docs/docs/current-contracts.mdx` was already current and did not change. `manifests --check`, `support_matrix --check`, `current_contracts.py --check` and `schemas --check` each read `CURRENT`. The manifest carries the values of PLAN.md §4.9 and F3 (`L4`, `VERIFIED`, `LICENSED`, `structured`, `max_input_bytes` 4224); the metadata block of the `dis7` adapter did not need a change.
- Roster literals: the twenty-name assertions in `tests/test_cdm_no_network.py`, `tests/test_cdm_lossless.py` (with `dis7` as the sixth `structured` adapter) and `tests/test_cdm_evidence.py`; the harness's selected-fixture total is 586, derived from the test's own message, of which the `dis7` directory gives 6.
- `RELEASE_NOTES.md`: the roster heading and paragraph say what `v3.1.1` registered, and a `dis7` row marked **post-3.1.1** carries this tree's harness reading of 6 verdicts.
- `pkg/FORMAT_COVERAGE.md`: three `dis7` status rows and the section `DIS 7 Entity State PDU (IEEE 1278.1-2012 subset) — ingest and egress`, one paragraph and one table.
- `gates/wheel_install.py`: `run_bytes` (bytes-mode helper) and `check_dis7_script` (version, self-test, decode, byte-exact replay, exit classes 0, 2, 3 and 4), called last in `check_console_scripts`; the gate keeps thirteen checks. Three tests appended to `tests/test_cdm_gate_rosters.py`; the gate itself is not run here (run R23). Decisions D83 to D85.
- Not done here: the adapter-count prose (R21), the documentation page and the final `### Unreleased` (R22), the wheel gate's clean-venv run (R23).

### R21 — wp6-prose

- Live counts moved to the registry's: the roster sentences, pair arithmetic (190 and 380), the double-count opinions sentence, the legacy census beside the roster, the egress count in the package README (fourteen), the `fixture_dir` note in `adapter.py` (eighteen), the implementation-cap and absent-bound counts in `parser-safety.mdx`, and the package README's byte-tolerance codec count (ten); every number read off `adapter.discover()` before it was written. Comment and docstring lines in `.py` files and `pyproject.toml` replaced one for one.
- `dis7` joined the roster enumerations of `README.md`, `docs/docs/intro.mdx`, `pkg/__init__.py` and the package README, the package README's "Shipped so far" table and the declarations table of `parser-safety.mdx`.
- Dated sites in the adapter expansion's implementation record, the publication ledger, the readiness report, the release notes and the dated history sections of `MIGRATIONS.md` are exempted by appended `TREE_EXEMPT` rows, never edited. `tests/test_cdm_prose_counts.py` and `tests/test_cdm_architecture_docs.py` are green. Decisions D86 to D88.
- Not done here: the documentation page, the CLI reference, the audit-table row for the host JSON loader and the final `### Unreleased` wording (R22); the release gates (R23).

### R22 — wp6-docs

- The package README gained the section on the `dis7` adapter before `## Layout`: the bounded-subset paragraph, the explicit-context Python example (run once on the packaged equator vector), the `synapse-dis7` commands and exit codes, the availability sentence and the docs address.
- `docs/docs/cdm/dis7.mdx` is new, with the nine sections the run names; its flags and bounds were taken from `synapse-dis7 --help`, each sub-command's help and the module constants, and its code list was printed from `CODES`. The parser-safety page gained the subsection on the DIS 7 codec and host loader.
- `fixtures/dis7/spec/dis7_terms.json` is a reading of the publisher's page with the confirmation PENDING (D89; confirmed on 2026-10-05, see R28); the migration notes' Unreleased section names it and its count clause moved by one.
- This record gained the contract-defect log, the SHOULD-deviation log, the dependency and licence inventory and installation, and its version register, optional-extension register, validation, verification, remaining gaps, handoff and the R24 and R25 entries were filled.
- `tests/test_cdm_dis7_trace.py` carries the completion checks (D90), and `R_EVIDENCE["R30"]` names the two prototype guards. No covering test was missing from the contract-defect log.
- Not done here: the release gates, the wheel gate and the full suite (R23); the handover directory (R25).

### R23 — wp6-gates

- The pre-commit release-gate sequence ran once on the staged tree as R22 left it and every step read `PASS`, none `FAIL` and none `BLOCKED`: the git state, the adapter text rules, no bytecode under `fixtures/dis7`, the editable install, the registry count, both full suites (hooks unset: 8423 passed, 200 skipped; normative hooks and OpenDIS set: 8542 passed, 81 skipped; no failing test id in either junit report), the DIS7 modules on 3.14, 3.11 and 3.12, the four generated-file checks (`CURRENT`), ruff (`clean`), the `dis7` harness and conformance runs, the roster conformance loop, the bump gate (`MINOR`, `3.2.0`, nothing unruled), the pin, parks and provenance gates, evidence generate, verify and badges, the live OpenDIS reference test on 3.14 and 3.11, the mutation matrix (every mutant `DETECTED`, control `GREEN`), the wheel gate with its mutation check, the docs gate (`npm ci` and `npm run ci`), gitleaks over the staged diff and the drafted commit message.
- No failure, so no owner run's file was changed and no fix was made; the only change of this run is this entry. The commit message draft still describes the staged tree and passes `gates/commit_message.py`.
- Second pass, after R24's fixes: the whole sequence ran again on the staged tree as R24 left it and every step read `PASS` again, none `FAIL` and none `BLOCKED` (hooks unset: 8443 passed, 200 skipped; normative hooks and OpenDIS set: 8562 passed, 81 skipped; no failing test id in either junit report; every mutant `DETECTED`, control `GREEN`). No fix was made; the only change of this pass is this bullet.
- Not done here: the commit, the post-commit gates and the push (the maintainer); the handover directory (R25).

### R24 — final-fix

- The final review ended in HOLD with three major findings; all three are fixed, each with a regression test that fails on the reviewed tree and passes now.
- F-01: `validate_session`, the instant check and the basis check in `adapters/dis7.py` require the exact type `str`, so a str subclass (an `enum.StrEnum` member, a `(str, Enum)` member, a plain subclass) is refused with the existing codes and paths (D91). Tests: `test_t09_session_refuses_str_subclasses`, `test_t09_time_context_refuses_str_subclasses` and three `session_str_*` rows of `test_constructor_refuses_each_context_defect`.
- F-02: `from_cdm` refuses three forms of an Entity built without validation as `E_REPLAY_SHAPE` instead of raising `AttributeError`, at `[0].<field>`, `[0].residual` or `[0].source` (D69). Test: `test_t11_n17_unvalidated_entity_is_refused`, through `from_cdm` and `encode`.
- F-03: `dis7_host._emit` answers a closed stdout with exit 4 and `synapse-dis7: cannot write output: stdout is closed`, and `_diagnose` no longer raises when stderr is closed. Tests: `test_t15_a12_closed_stdout_exits_4`, `test_t15_a12_closed_stdout_and_stderr_exits_4`.
- Minor findings applied: F-08 (readable test ids for the N13 inputs), F-18 (`from_cdm` refuses an Entity subclass at `$`; row `entity-subclass` of `test_t11_n17_wrong_shape_is_refused`), F-48 (the codec's module docstring), F-49 (no local absolute path in this record or the schema test), F-53 (the Verification table carries R22 and R23).
- Not done here: the other minor findings, listed with their reasons in the run's report; F-40 and F-10 wait for the maintainer.

### R25 — handover

Runs after the final commit and changes nothing in the repository; its output is the handover directory in the pipeline's run directory.

### R26 — settle-behaviour

- WP7, first of the four sessions of the unit (R26, R27, R28, R30): the sixteen behaviour findings of the final review that this run owns. Each FIXED finding except F-59, a text correction, has a regression test that fails on the tree as R26 found it (or, for F-25, on a copy with an unbounded read) and passes now.
- F-09 FIXED: the constructor checks a time context again and keeps its own copy (D92).
- F-15 FIXED: a bytes-like subclass that raises is `E_INPUT_TYPE` at `$` in `decode_pdu`, the coded guard and `parse_json_text`, and False in the header predicate (D93).
- F-16 FIXED: the header predicate reads a 0-dimensional or multi-dimensional view as flat octets (D94).
- F-17 FIXED: the PDU bound is measured through `nbytes` before the copy, in the codec and the guard (D95, D54, D65).
- F-19 FIXED: envelope and residual members are read once and only the checked values are used (D96).
- F-20 FIXED: a failed stderr keeps exit 3 and exit 4 (D97, D74).
- F-21 FIXED: `--help` is flushed inside the output handler, so a broken pipe is exit 4 (D98).
- F-22 and F-23 FIXED: `_read_bounded` checks the descriptor it reads, opened without blocking, and asks for no more than `limit + 1` octets (D99); `test_t15_a12_host_module_import_rules` now expects the second `os.open`.
- F-24 FIXED: `replay` names an oversize file's size as a floor (D100).
- F-25 FIXED: two in-process tests bound the traced allocation of an oversize decode and replay; the CLI module read 81 passed as R26 left it.
- F-39 BLOCKED: the fix to check O makes the bump gate report `synapse_cdm/suite.py:check_resource_limits` unruled; the change and its test were taken out again, and the proposed ruling waits for the maintainer. Corrected in R31: the maintainer approved the ruling on 2026-10-05, and R31 applied the change and its test (D113).
- F-42 FIXED: an override of the hook that is not a classmethod is recognised (D101).
- F-56 FIXED: `_emit` closes the redirect descriptor when the redirect cannot be made (D102).
- F-57 FIXED: a comparison of replay steps 5 and 6 that raises counts as a difference (D69, D70); the seam lines are unchanged.
- F-59 FIXED: the three sentences of D69 and D91, and the R24 entry's F-02 bullet, say what the code does.
- No golden, manifest or schema changed; the output of `synapse-dis7` for the packaged vectors is byte-identical; the bump gate still reads MINOR, 3.2.0, nothing unruled; the mutation gate still detects every fault.
- Not done here: F-39 (blocked, above; fixed in R31, D113); the findings of R27 and R28.

### R27 — settle-tests

- WP7, second of the four sessions of the unit: the nineteen test findings of the final review that this run owns. Each FIXED finding's test passes on the tree and fails against the finding's mutant in a scratch copy of the package, or, for the trace-module findings F-04, F-12, F-26 and F-27, against a mutant of the tests in a scratch copy of `tests/`; no file under the package changed.
- F-04 FIXED: `R_SUPPLEMENT` with its resolution check and completeness test (D104); the handover generator's half is a kit change.
- F-05 FIXED: `test_sweep_items_agree_with_the_contract_expected_and_operation` ties each sweep entry to the case's `expected` codes and machine-readable `operation`.
- F-06 FIXED: a negative-zero position item in the A03 sweep and a negative-zero climb item in the A05 sweep.
- F-07 FIXED: an antimeridian envelope whose twin spells +0 where the wire has -0 in the A09 sweep.
- F-11 FIXED: `test_t15_a12_replay_binds_session_and_classification_from_the_document` (CR-17).
- F-12 FIXED: `# CR-nn` tags above the tests of CR-13, CR-16, CR-17, CR-18, CR-27, CR-33 and CR-34, kept by `test_every_contract_resolution_is_tagged_above_a_test` (D104).
- F-26 FIXED: the binder reads collectable tests only (D103).
- F-27 FIXED: the wheel-gate half of A12 is checked (D104).
- F-28 FIXED: three rotated-velocity items in the A05 sweep at latitude and longitude away from zero.
- F-29 FIXED: `test_t09_n14_envelope_instant_in_another_spelling_is_normalised` (six cases).
- F-30 FIXED: a four-digit stored instant row and five stored-residual tests over the range, width, wrong-type, hex and source-hash tables (D105).
- F-31 FIXED: `test_t12_time_context_is_judged_before_the_projection` (four cases).
- F-32 FIXED: eighteen `_RANGE_ROWS` rows (D105).
- F-33 FIXED: cyclic, ring and over-deep three-key envelopes in `test_r07_detect_matrix`.
- F-34 FIXED: `test_r21_hash_and_twin_messages_echo_nothing`.
- F-35 FIXED: three order rows in `test_t12_member_order_does_not_change_the_diagnostic` and the instant-before-basis conflict in the N14 test.
- F-36 FIXED: `test_t11_type_only_edits_are_refused`.
- F-37 FIXED: `test_cr29_subclass_instances_are_not_the_plain_types` and `test_encode_refuses_int_and_float_subclasses`.
- F-38 FIXED: `test_t12_text_oversized_integer_literal_does_not_depend_on_the_interpreter_limit`, added to D64's covering tests.
- The trace table's `PENDING` stays empty and `R_EVIDENCE` is unchanged; the CR-17 and CR-26 rows of the contract-resolution table name the new tests; the CLI module read 82 passed as R27 left it.
- Not done here: the findings of R26 and R28.

### R28 — settle-texts

- WP7, third of the four sessions of the unit: the fifteen text findings of the final review that this run owns, and the maintainer's three answers of 2026-10-05. No behaviour of the package changed.
- F-10 FIXED: a paragraph under `## Source pins` states what the generated `dis7` evidence record hashes, as observed on a record generated into a scratch directory: 39 files, `README.md` and `PROVENANCE.json` being left out in every directory, not only at the top.
- F-13 FIXED: the contract-defect log names the tests that fail when CR-03, CR-04, CR-25, CR-29, CR-32 and CR-34 are reversed; the CR-17 row already named R27's test.
- F-14 FIXED: D106 to D109 record the kit decisions D-01, D-08, D-19 and D-29 (the numbers D91 to D94 that the review proposed were taken by then).
- F-40 FIXED: the approved clause in the ruling of `synapse_cdm/evidence.py:main`, and the module docstring of `tests/test_cdm_fixture_instance.py`.
- F-41 FIXED: the package README and the adapter-writer page state the `--fixtures` refusal for an overriding adapter, and the package README's exit-code paragraph names the two further causes of harness exit 2.
- F-43, F-45 and F-52 FIXED: the count paragraph of `### Unreleased` and two step sentences (D110).
- F-44 FIXED: the availability sentence in the root README, the docs introduction and the `dis7` page; the proposed test assertion is not added (D111; R30 added it).
- F-46 FIXED: the residual paragraph of the CDM index page accounts for `dis7`.
- F-47 FIXED: the parser-safety heading no longer places the codec outside `adapters/`; the kit check that quotes the old heading is a kit change.
- F-50 FIXED: the `dis7` page cites open-dis-python by URL, licence and commit.
- F-51 FIXED: the `residual_block` docstring of `lossless.py` names which structured adapters call it.
- F-54 FIXED: the fix-round bullet under `## SHOULD-deviation log` and the sentence under `## Verification`, whose table gained the rows R24 to R27.
- F-60 FIXED in the tree's texts (package README, `dis7` page, `pyproject.toml` comment, the host-command paragraph of `### Unreleased`); the argparse description is left (D111; R30 changed it).
- Terms record: the confirmation sentence and the confirmed clause replace the two PENDING sentences; D89, the R22 entry and `### Unreleased` say so, and the row under `## Remaining gaps` is closed. No pin, provenance record or test hashes the file.
- Not done here: the findings of R26 and R27; F-39 stays blocked on a bump ruling. Corrected in R31: F-39 is fixed under the approved ruling (D113).

### R30 — settle-final

- WP7, fourth of the four sessions of the unit: the eighteen items of the lead's adjudication of the unit's own review (S-01 to S-18) and the two parts R28 left (D111). Each behaviour change has a regression test that fails on the tree as R30 found it and passes now; each test-only change fails against a named mutant in a scratch copy of the package or of `tests/`.
- S-01 FIXED: the commit draft's tests paragraph separates the regression tests of a behaviour change from the gap tests, with numbers counted against the WP4-6 commit.
- S-02 FIXED: the commit draft says that the header predicate answers False for a raising bytes-like subclass.
- S-03 FIXED: a usage error keeps exit 2 with stderr closed or broken, and `--help` with stdout closed exits 4 with the one diagnostic line (D97, D98).
- S-04 FIXED: D92 says that a subclass instance no longer compares equal.
- S-05 FIXED: a caller-supplied container whose read raises is a coded refusal from `to_cdm`, `validate_source`, `from_cdm`, `encode` and the constructor (D112, D69).
- S-06 FIXED: F-29's two mutants re-expressed for the tree, each defining every name it uses, both killed by the N14 spelling test; the proof is in the run's report.
- S-07 FIXED: five `_RANGE_ROWS` rows (D105).
- S-08 FIXED: the evidence check is pinned for a nested function, and a `Test*` class with `__init__` binds nothing (D103).
- S-09 FIXED: a resolution tag counts only above a module-level test (D104).
- S-10 FIXED: an `R_SUPPLEMENT` or `R_EVIDENCE` entry must name a test function (D103).
- S-11 FIXED: the commit draft's texts paragraph names the four texts that say what `decode`, `replay` and `self-test` read.
- S-12, S-13 and S-14 FIXED: the framing bullets of the R26 and R27 entries and the F-41 bullet of the R28 entry.
- S-15 FIXED: D89's covering tests.
- S-16 FIXED: the opening paragraph names the runs of the follow-up unit, and `## Handoff` says how the unit is committed and pushed.
- S-17 FIXED: `## Remaining gaps` carries the F-39 row; the D111 items are closed, so they have no row. Corrected in R31: the F-39 row is closed too, so it has no row (D113).
- S-18 FIXED: the argparse description of `synapse-dis7` and its test, and the availability test (D111).
- F-39 stays BLOCKED: no approved ruling exists for `synapse_cdm/suite.py:check_resource_limits`, so `suite.py` is as at the WP4-6 commit. Corrected in R31: the maintainer approved the ruling on 2026-10-05, R31 applied the change and its test, and the `## Remaining gaps` row is closed (D113).
- No fixture, golden, manifest or schema changed; the bump gate still reads MINOR, 3.2.0, nothing unruled; the mutation gate still detects every fault; the CLI module reads 91 passed.

### R31 — arc-release-prep

- WP8, the one session of the unit: the two changes the maintainer decided on 2026-10-05 must land on `soif/dis7-1.0` before a release commit is drafted, on this branch because `main` moves once, at the release.
- F-39 FIXED: check O builds the adapter in a step of its own and reports a refusal raised while building as FAIL (D113); the approved ruling is under `### Unreleased`; the new test fails on the tree as R31 found it and passes now; the bump gate reads a pending MINOR with nothing unruled; every shipped adapter still reads CONFORMANT under the CI job's required sets.
- AUDIT FIXED: three `overrides` entries and a lock refresh that moved those three packages only, and the exception for `braces` (D114); the job's decision step reads `OK` with the exception derived, the two security test modules pass, and `npm --prefix docs run ci` exits 0.
- The R26, R28 and R30 entries carry a correction sentence for F-39, and its `## Remaining gaps` row is closed.
- No fixture, golden, manifest or schema changed; `### Unreleased` still counts 64 files inside the distribution, since every new path of this run is outside it.
- Not done here: the release itself (the version, the roll of `### Unreleased`, the release notes, the evidence flag of `dis7`), which the maintainer's answers leave to the release round.

## Validation

Commands a developer runs from a clean checkout of the branch:

```bash
python -m pip install -e "packages/cdm[test,lint,validate]"
python -m pytest -q -rs -p no:cacheprovider
python -m synapse_cdm.schemas --check --out schemas
python -m synapse_cdm.manifests --check --out manifests
python -m synapse_cdm.support_matrix --check
python gates/current_contracts.py --check
python -m synapse_cdm.evidence provenance
ruff check --config packages/cdm/pyproject.toml packages/cdm gates tests
```

Results are in each run's Progress entry.

The exit check of run R22, as read at the end of that run:

| Command | RC | Result |
| --- | --- | --- |
| git state: index equals working tree, nothing untracked, HEAD unchanged | 0 | PASS |
| adapter text rules over `adapters/dis7.py` and `adapters/dis7_codec.py` | 0 | PASS |
| added text rules over every added line | 0 | PASS |
| no bytecode under `fixtures/dis7` | 0 | PASS |
| `adapter.discover()` | 0 | PASS |
| `ruff check --config packages/cdm/pyproject.toml packages/cdm gates tests` | 0 | `All checks passed!` |
| the registry holds twenty | 0 | PASS |
| `schemas --check`, `manifests --check`, `support_matrix --check`, `current_contracts.py --check` | 0 | `CURRENT` |
| `python gates/bump_derivation.py --json` | 0 | pending `MINOR`, `3.2.0`, unruled `[]` |
| the DIS 7 test modules under Python 3.14, 3.11 and 3.12 | 0 | PASS; the live OpenDIS half skips as `BLOCKED_EXTERNAL_EVIDENCE` with the hook unset |
| sentinels | 0 | PASS |
| prose, path and policy gates (`test_cdm_prose_counts.py` and nine further modules) | 0 | PASS |
| `python -m pytest -q -p no:cacheprovider tests/test_cdm_dis7_trace.py -k test_completion_` | 0 | PASS |
| `R_EVIDENCE["R30"]` names the two prototype guards | 0 | PASS |
| files this run delivers | 0 | PASS |
| README section, docs page, parser-safety subsection | 0 | PASS |
| terms record | 0 | PASS, form A |
| implementation record: closing sections | 0 | PASS |
| commit message draft through `gates/commit_message.py` | 0 | `clean` |
| `cd docs && npm run ci` | 0 | PASS |

## Verification

Every run is judged by a mechanical exit check and by an independent verifier session; both write to the pipeline's run directory, outside the repository. Its commands and verdicts:

A verifier re-runs, from the branch with the staged tree:

```bash
bash RUN/checks/<run id>.sh
python -m pytest -q -p no:cacheprovider tests/test_cdm_dis7_trace.py
python gates/bump_derivation.py --json
python -m synapse_cdm.manifests --check --out manifests
python -m synapse_cdm.harness --adapter dis7 --schemas schemas
python -m synapse_cdm.suite conformance run --adapter dis7 --require A,B,C,D,E,F,G,H,J,K,L,N,O
```

The last line of each verifier report, `RUN/reports/<run id>-verify.md`, that existed when this table was last edited; the report of a run that edits this record afterwards is in `RUN/reports/` only:

| Run | Verdict |
| --- | --- |
| R01 | `VERDICT: PASS` |
| R02 | `VERDICT: PASS` |
| R03 | `VERDICT: PASS` |
| R04 | `VERDICT: PASS` |
| R05 | `VERDICT: PASS` |
| R06 | `VERDICT: PASS` |
| R07 | `VERDICT: PASS` |
| R08 | `VERDICT: PASS` |
| R09 | `VERDICT: PASS` |
| R10 | `VERDICT: PASS` |
| R11 | `VERDICT: PASS` |
| R12 | `VERDICT: PASS` |
| R13 | `VERDICT: PASS` |
| R14 | `VERDICT: PASS` |
| R15 | `VERDICT: PASS` |
| R16 | `VERDICT: PASS` |
| R17 | `VERDICT: PASS` |
| R18 | `VERDICT: PASS` |
| R19 | `VERDICT: PASS` |
| R20 | `VERDICT: PASS` |
| R21 | `VERDICT: PASS` |
| R22 | `VERDICT: PASS` |
| R23 | `VERDICT: PASS` |
| R24 | `VERDICT: PASS` |
| R25 | `VERDICT: PASS` |
| R26 | `VERDICT: PASS` |
| R27 | `VERDICT: PASS` |

The table gives each report's final verdict. Runs R02, R03 and R09 first received `VERDICT: FAIL` from their verifier, and runs R01, R03 and R15 first failed their exit check; see the fix-round bullet under `## SHOULD-deviation log`.


## Remaining gaps

| Gap | Affected claim | Reproduction |
| --- | --- | --- |
| The live OpenDIS reference tests (case A13, requirement R26) need the pinned checkout named by `SYNAPSE_CDM_OPENDIS_DIR`; CI has none, so there they read `BLOCKED_EXTERNAL_EVIDENCE` [F6] | A13 and R26 verified locally only, unavailable in CI; the exercise report names the commit it was re-run on | `SYNAPSE_CDM_OPENDIS_DIR=<checkout at the pin> python -m pytest -q -rs -m reference tests/test_cdm_dis7_reference.py` |
| Case A12's evidence is the wheel gate's clean-environment run of `gates/wheel_install.py::check_dis7_script` (written in run R20, run by the wheel gate in run R23), not the in-tree CLI test [CR-33] | A12: the installed `synapse-dis7` command behaves as specified | `python gates/wheel_install.py --mutation-check` |
| Two SDK defects are filed separately and not fixed here [F7(b)]: `adapter.container_depth` never returns on a cyclic dict, and `evidence.generate(name, fixtures=DIR)` raises `ValueError` for a directory outside the packaged root | none of this adapter's claims; the `dis7` adapter holds a parsed envelope to acyclicity itself | `adapter.container_depth` on a dict that contains itself; `evidence.generate` with a fixture directory outside the package |
| `Evidence(available=False)` until the release round flips it [F11] | no published evidence badge for the `dis7` adapter | `grep -n '"available"' manifests/dis7.json` |

## Contract-defect log

For the specification owner: every contract resolution CR-01 to CR-35 the plan froze, with the issue found in the handoff specification, the resolution this implementation follows, and the test that covers it. Issue and Resolution are the plan's own cells, quoted in `## Decisions` as D12 to D46. The handoff specification is identified by `SC DIS7 SPEC 001 v1.0` and is not in this repository.

| CR | Issue | Resolution | Covering test |
| --- | --- | --- | --- |
| CR-01 | Schema instant regex accepts `:60`, Feb 30, hour 24, year 0000, offset `+24:00` | Prose wins; enforced in `TimeContext`; schema shipped unchanged | `tests/test_cdm_dis7_time_identity.py::test_t09_n13_refused_instant`, `tests/test_cdm_dis7_time_identity.py::test_t09_n13_refused_instants_that_cannot_be_test_ids` |
| CR-02 | Residual schema accepts an unnormalised stored instant | Replay requires the normalised form → `E_REPLAY_PROVENANCE` | `tests/test_cdm_dis7_replay.py::test_t11_n16_stored_context_edit_is_refused` |
| CR-03 | Malformed envelope instant/basis: structural or `E_CONTEXT_TIME` | Wrong JSON type or missing key → `E_TWIN_SCHEMA` (stage 2); a string with a bad value → `E_CONTEXT_TIME` (stage 8) | `tests/test_cdm_dis7_replay.py::test_t12_n18_wrong_type_or_boolean`, `tests/test_cdm_dis7_schema.py::test_r12_stage2_verdict_equals_the_envelope_schema_except_enumerated_divergences` |
| CR-04 | `encode_pdu` code split (table vs case N10) | Keys, types, array sizes, record count, hex width → `E_TWIN_SCHEMA`; header constants → `E_HEADER_UNSUPPORTED`; length vs records → `E_LENGTH_MISMATCH`; NaN/inf → `E_NONFINITE`; integer range, hex characters, float32 representability → `E_VALUE_RANGE` | `tests/test_cdm_dis7_codec.py::test_encode_reports_defects_in_the_frozen_stage_order`, `tests/test_cdm_dis7_codec.py::test_t03_n10_256_records_are_refused_as_twin_schema` |
| CR-05 | Envelope twin value classes | Constants, out-of-range integers, hex width or syntax, `wire_hex` outside 288–8448 characters, non-finite numbers → `E_TWIN_SCHEMA` at stage 2 | `tests/test_cdm_dis7_replay.py::test_t12_n18_range_constant_and_non_finite` |
| CR-06 | Integral floats for integer fields (`7.0`) | Accepted in twins and `encode_pdu`, following the schema; booleans refused | `tests/test_cdm_dis7_replay.py::test_t12_n18_integral_floats_and_integer_components_are_accepted` |
| CR-07 | Basis `\S` depends on the regex engine | Whitespace defined as an enumerated code-point set; tests for U+001C, U+0085, U+00A0, U+FEFF | `tests/test_cdm_dis7_time_identity.py::test_t09_basis_whitespace_is_the_enumerated_set` |
| CR-08 | Context schema requires `time_context`; constructor makes it optional | Constructor optional (prose); the schema describes vector context files | `tests/test_cdm_dis7_adapter.py::test_t01_a01_vector_envelope_equals_expected` |
| CR-09 | No code for "final CDM validity" | `E_PROJECTION` at `$` | `tests/test_cdm_dis7_adapter.py::test_cr09_final_cdm_validity_failure_is_e_projection_at_the_root` |
| CR-10 | Omitted keyword-only argument raises `TypeError` | Sentinel defaults raise `Dis7Error` | `tests/test_cdm_dis7_adapter.py::test_constructor_refuses_each_context_defect` |
| CR-11 | No API named for envelope text, yet N18 and N20 need one | Public `parse_json_text` (§4.8); unparseable JSON → `E_TWIN_SCHEMA` at `$` | `tests/test_cdm_dis7_replay.py::test_t12_text_unparseable` |
| CR-12 | Oversize `str` to `to_cdm` | `E_INPUT_LIMIT` (forced by `tests/test_cdm_resource_envelope.py:121-131`); in-bounds `str` → `E_INPUT_TYPE`. Departs from §12's type-then-bounds order for `str` only | `tests/test_cdm_dis7_adapter.py::test_guard_measures_text_before_it_types_it` |
| CR-13 | Path strings unspecified beyond two conventions | §4.4, frozen | `tests/test_cdm_dis7_adapter.py::test_acceptance_sweep` |
| CR-14 | N15 vs the code table on "time" | `valid_from`/`valid_to` → `E_REPLAY_CHANGED`; `source.observed_at` and stored time context → `E_REPLAY_PROVENANCE` | `tests/test_cdm_dis7_replay.py::test_t11_n15_canonical_edit_is_refused` |
| CR-15 | Non-list replay input; undecodable or edited `wire_hex`/`residual.pdu` | `E_REPLAY_SHAPE` at `$`; `E_REPLAY_CHANGED` | `tests/test_cdm_dis7_replay.py::test_t11_single_view_edit_is_refused` |
| CR-16 | Null vs absent on replay | Unobservable on model instances. At the CLI JSON boundary a non-canonical document (absent member, non-canonical spelling) → `E_REPLAY_SHAPE` | `tests/test_cdm_dis7_cli.py::test_t15_a12_replay_refuses_each_absent_null_member` |
| CR-17 | CLI `replay` has no session or classification flags | Bound from the stored residual, so the match is by construction; optional flags, when given, are asserted. Single-copy edits are still caught through `source_ids` and `source.synthetic` | `tests/test_cdm_dis7_cli.py::test_t15_a12_live_sets_synthetic_false_and_replay_asserts_flags`, `tests/test_cdm_dis7_cli.py::test_t15_a12_replay_binds_session_and_classification_from_the_document` |
| CR-18 | CLI exit classes; CLI output vs null-hash goldens | §4.8. CLI decode always carries a hash, so self-test compares the API's null-hash output | `tests/test_cdm_dis7_cli.py::test_t15_a12_self_test_passes` |
| CR-19 | A03 "stated longitudes and heights" appear nowhere normative | Chosen and recorded: (0, 180, 35 786 000), (49, 16, 400), (−45, −179.5, 12 000), (89.999, 34, −100), (−90, 0, 0), plus exact `[0, 0, ±b]` for the pole branch | `tests/test_cdm_dis7_geodesy.py::test_t05_a03_analytical_positions` |
| CR-20 | A09 and A14 cannot be exercised on the named seed | A09 uses `north_pole_stationary`; mutation killers per §4.10 | `tests/test_cdm_dis7_adapter.py::test_acceptance_sweep` (its item `t10_a09`) |
| CR-21 | `fixture_instance` supplies a context without the caller passing it | Contract deviation, restricted per F1, stated as a manifest limitation | `tests/test_cdm_dis7_adapter.py::test_t14_n21_sdk_clis_refuse_live_and_a_caller_supplied_fixture_directory` |
| CR-22 | Spec lines 219 and 221 order replay checks differently | §4.5 order; multi-defect tests at wire bytes 1, 17 and 88 | `tests/test_cdm_dis7_replay.py::test_t11_consistent_wire_and_view_edit_is_provenance` |
| CR-23 | "RFC 3339" prose permits lowercase `t`/`z`; the schema refuses them | Refused, with the space separator | `tests/test_cdm_dis7_time_identity.py::test_t09_n13_refused_instant`, `tests/test_cdm_dis7_time_identity.py::test_t09_n13_refused_instants_that_cannot_be_test_ids` |
| CR-24 | `-00:00` offset | Accepted, normalised to `Z` | `tests/test_cdm_dis7_time_identity.py::test_t09_a07_equivalent_spellings_normalise_to_one_instant` |
| CR-25 | `residual.namespace` ≠ `DIS`; meaning of "Source namespace" in the code table | `E_REPLAY_SHAPE`; "Source namespace" is the scoped identity system in `source_ids` → `E_REPLAY_PROVENANCE` | `tests/test_cdm_dis7_replay.py::test_t11_n16_source_ids_edit_is_refused`, `tests/test_cdm_dis7_replay.py::test_t11_residual_shape_defect_is_refused` |
| CR-26 | How much of the residual schema is the replay shape gate | All of it; CR-15 applies only to schema-valid hex | `tests/test_cdm_dis7_replay.py::test_t11_residual_shape_defect_is_refused`, `tests/test_cdm_dis7_replay.py::test_t11_residual_range_constant_and_non_finite_is_shape`, `tests/test_cdm_dis7_replay.py::test_t11_residual_width_one_short_or_one_long_is_shape`, `tests/test_cdm_dis7_replay.py::test_t11_residual_wrong_type_or_boolean_is_shape`, `tests/test_cdm_dis7_replay.py::test_t11_residual_hex_syntax_and_wire_hex_length_is_shape`, `tests/test_cdm_dis7_replay.py::test_t11_residual_source_hash_shape_defect_is_refused` |
| CR-27 | Duplicate key or unparseable JSON in replay's `entity.json` | `E_REPLAY_SHAPE` | `tests/test_cdm_dis7_cli.py::test_t15_a12_replay_refusals_exit_3` |
| CR-28 | `detect(envelope)` | True only for exactly the three keys and a 7/1/1 header by guarded lookups; False for cyclic, empty, unrelated or over-size input; never raises | `tests/test_cdm_dis7_adapter.py::test_r07_detect_matrix` |
| CR-29 | Native twin types | `list` and `tuple` for arrays, `dict` only for objects, plain `int`/`float`; `time_context` as `TimeContext` only; `source_hash` as a plain dict; a memoryview of any item size is its underlying octets | `tests/test_cdm_dis7_codec.py::test_t04_a_memoryview_of_72_two_octet_items_decodes_as_its_144_octets`, `tests/test_cdm_dis7_replay.py::test_t12_n18_integral_floats_and_integer_components_are_accepted`, `tests/test_cdm_dis7_adapter.py::test_constructor_refuses_each_context_defect` |
| CR-30 | The note for position-present with a non-world algorithm appears in no vector | Asserted literally for algorithms 0, 1, 6, 9, 255; all four note shapes tested | `tests/test_cdm_dis7_adapter.py::test_t14_a11_note_sequences_for_all_four_shapes` |
| CR-31 | `validate_source` format | Exactly one `"CODE at PATH: message"` string; the SDK default's type-name prefix is overridden | `tests/test_cdm_dis7_adapter.py::test_r07_validate_source_matrix` |
| CR-32 | Years below 1000 in `valid_from`/`observed_at` | F7(a) | `tests/test_cdm_adapter_contract.py::test_render_pads_the_year_to_four_digits_for_years_1_and_999`, `tests/test_cdm_adapter_contract.py::test_render_holds_no_strftime_year_directive` |
| CR-33 | A12's evidence | The wheel gate's clean-venv run, not the in-tree CLI test | `tests/test_cdm_gate_rosters.py::test_t15_a12_the_dis7_script_check_passes_against_this_environment` |
| CR-34 | Self-test and wheel report package 3.1.1 although the tag has no dis7 | F11 | `tests/test_cdm_dis7_cli.py::test_t15_a12_version`, `tests/test_cdm_packaging.py::test_the_two_versions_are_independent_and_nothing_derives_one_from_the_other` |
| CR-35 | Is a location written with negative zeros "the exact zero vector"? | Yes, compared by value: position and kinematics null, the zero-vector note, sign bits kept in residual and replay; never `E_POSITION_DOMAIN` | `tests/test_cdm_dis7_geodesy.py::test_t05_n11_origin_and_negative_zero_origin_have_no_projection` |

## SHOULD-deviation log

The handoff specification contains no SHOULD statement beyond its definition of the word, so no requirement-level SHOULD was deviated from. The process deviations, each logged for the delivery report:

- The four sequencing deviations, recorded under `## Sequencing deviations`.
- Three of the plan's gate commands run in CI's stricter form: `pytest -q -rs` with a junit report, `gates/wheel_install.py --mutation-check` with `--export-dist`, and `npm ci` in place of `npm install`, which can rewrite the tracked lock file.
- CR-12: the input guard measures text before it types it, so an oversize `str` is `E_INPUT_LIMIT` rather than `E_INPUT_TYPE`; see D23.
- CR-21: the conformance verdict is defined for the packaged fixtures only, because the generic tools build the adapter with the fixtures' context through `Adapter.fixture_instance` and refuse a caller-supplied fixture directory for it; see D32.
- The maturity tension [F3]: the handoff specification allows an initial L3 with implemented claim status, while `tests/test_cdm_manifests.py` forces L4 and VERIFIED for a bidirectional `standard-encoding` adapter with `MAPPINGS` and a passing round trip. L4, VERIFIED and LICENSED are declared; L5, L6, `external_exercise` and `normative-verified` are not.
- The conformance applicability [WP6]: checks I and M are declared inapplicable, and the gate requires `A,B,C,D,E,F,G,H,J,K,L,N,O`.
- Fix rounds [PLAN sections 6.1 and 10]: the plan allows at most one fix round per work package and stops the work when it fails; the pipeline's driver allowed two per run (`MAX_FIX_ROUNDS` in the run kit). In run R01 the first fix round did not pass the exit check and a second one did. In run R03 the first fix round passed the exit check but not its verifier, because the WP1a commit draft quoted a suite duration that the next run of the suite changed; a second fix round failed on the same line, the driver stopped, the maintainer removed the duration from the draft, and the re-check passed. Runs R02 and R09 each passed after one fix round. In run R15 both fix rounds ended at once on the account's session limit; the driver stopped and the runner was started again.

## Dependency and licence inventory

| Component | Role | Licence | Carried |
| --- | --- | --- | --- |
| `pydantic` | runtime dependency, unchanged | MIT | installed from the package index, not vendored |
| `jsonschema` | runtime dependency, unchanged | MIT | installed from the package index, not vendored |
| open-dis-python at `732b6655bb47e34ccc73722eefe0f4706fd0032f` (https://github.com/open-dis/open-dis-python) | development reference: the layout authority and the reference tests' oracle | BSD-2-Clause | not vendored and not a dependency; nothing is copied from it |
| IEEE 1278.1-2012 | the standard the Entity State subset is written against | licensed by its publisher | not carried in this repository or in the wheel, and its text was not consulted; see `fixtures/dis7/spec/dis7_terms.json` |
| this implementation | the `dis7` adapter, its codec, the host module and the tests | Apache-2.0 | this repository |

The two runtime licences are what `importlib.metadata.metadata(name)["License-Expression"]` prints.

## Installation

From a clone of the branch:

```bash
python -m pip install -e "packages/cdm[test,lint]"
synapse-dis7 --version
synapse-dis7 self-test
```

The wheel is built and installed into a clean environment, and the `synapse-dis7` command is exercised there, by `python gates/wheel_install.py --mutation-check`. A wheel built from this tree is an unreleased build: it reports package 3.1.1.

## Handoff

The final steps, run by the maintainer from the pipeline's run directory:

```bash
bash RUN/run.sh final
bash RUN/run.sh approve final-review
bash RUN/run.sh commit wp4-6
bash RUN/run.sh postcommit
bash RUN/run.sh
git push -u origin soif/dis7-1.0
```

The final review's minor findings were then settled in a follow-up unit, WP7: the sessions R26, R27, R28 and R30 and the release gates' check script R29 on the staged tree. The unit is committed on top of the WP4-6 commit, and the branch is pushed again once that commit has passed the post-commit gates. The release preparation follows as WP8, the session R31: the F-39 fix under the maintainer's approved ruling and the docs audit cleared, committed on top of WP7 on this branch, so that the release commit is drafted from a reviewed tip and `main` moves once, at the release.

On HOLD the final review is followed by `bash RUN/run.sh fix-final` before it is run again.

The handover artefacts are untracked, are assembled under `RUN/handover/` and indexed there by `INDEX.json` with their SHA-256 and the commit, and this record cannot carry the SHA of the commit that contains it.

| Artefact kind | Regenerated by |
| --- | --- |
| wheel and sdist, with their SHA-256 | `python gates/wheel_install.py --mutation-check --export-dist DIR` |
| filled requirements file, trace matrix, skip ledger, geodesy oracle results and index | `python RUN/handover/tools/build_handover.py` (written by run R25) |
| mutation matrix | `python gates/dis7_mutation.py --out FILE` |
| benchmark report | `python gates/dis7_benchmark.py --out FILE` |
| OpenDIS exercise report | `python -m tests.dis7_reference_support --exercise-out DIR`, with `SYNAPSE_CDM_OPENDIS_DIR` naming the pinned checkout, then `python -m synapse_cdm.evidence exercise --adapter dis7 --spec DIR/opendis.json --slug opendis-732b6655 --out DIR` |
| gate logs and junit reports | `bash RUN/run.sh postcommit` |

The release round is described here and not run in this arc: the version number is the one `python gates/bump_derivation.py --json` derives, `evidence.available` flips to true for the `dis7` adapter in the release commit, the tag is pushed, and the publish pipeline builds and publishes the distribution. Until then the package still reads 3.1.1.
