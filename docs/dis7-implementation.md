# DIS 7 adapter — implementation record

This record is the implementation record for the DIS 7 adapter, kept as the work proceeds rather than written after the fact. The contract is the handoff specification identified as `SC DIS7 SPEC 001 v1.0`; it is a handoff document and is not in this repository, and wherever this record says "spec" or cites a specification section or line, it means that document. The work is done in pipeline runs R02 to R25, whose prompts, logs and reports live in a run directory outside the repository. Decisions D1 to D46 and the Frozen contract section quote the plan this pipeline follows and its rulings file; neither is in this repository. In the quoted text `§4.3`, `§4.4`, `§4.5`, `§4.8`, `§4.10` and `§10`, and anything written `PLAN.md §n`, are sections of the plan this pipeline follows: its §4.3, §4.4, §4.5 and §4.10 are reproduced under Frozen contract (Error model and codes, Validation order and paths, Replay order, Mutation seams), its §5 is the table of D12 to D46, its §4.8 is the command-line interface that run R16 writes, and its §10 is a list of risks. `§4 field order`, `§12`, `§16` and "spec lines" refer to the handoff specification.

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

## Version register

| Item | Value |
| --- | --- |
| IEEE edition | IEEE 1278.1-2012 (DIS 7), Entity State subset; the IEEE text was not consulted, the layout authority is open-dis-python at the pin. |
| OpenDIS commit | `732b6655bb47e34ccc73722eefe0f4706fd0032f`. |
| Repository commit | `c4bba1b6ebfdfe956f6efc2b3a81a04db2b4bb5b`. |
| Package version | 3.1.1. |
| CDM schema version | 3.0.0. |
| Adapter API version | 3.0.0 at the baseline; 3.1.0 from run R05. |
| Adapter version | 1.0.0 (target). |
| Specification id | `SC DIS7 SPEC 001`, version 1.0; bundle `MANIFEST.json` sha256 `3d6c04b4c02f4609625a57c5cfc965aae8d4b5c74ab39e5a0ad0a539e565c5b2`. |

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

| Extension | Why it does not alter the mandatory profile |
| --- | --- |
| `parse_json_text`, a public host loader | Cases N18 and N20 need an API for envelope text and the contract names none (CR-11); it only adds refusals. |
| `Dis7InputTooLarge`, `Dis7InputTooDeep` | Both are `Dis7Error` with `E_INPUT_LIMIT`; the second base class only lets code that catches the SDK's classes see the same refusal. |
| Sentinel defaults for `session` and `synthetic` | Omission still fails, as a coded `Dis7Error` instead of `TypeError` (CR-10); there is no usable default. |
| Optional `--session`, `--synthetic`, `--live` on `replay` | Replay binds both from the stored residual; a flag is only asserted against it (CR-17). |
| `Adapter.fixture_instance`, Adapter API 3.1.0 | Additive; the default is the previous construction; the DIS7 override serves the packaged fixtures only and refuses `synthetic=False` (CR-21, D1). |
| `times.render` four-digit year | Years 1000 to 9999 print as before; smaller years gain zero padding (CR-32, D7). |
| `evidence.digest_bytes` | A new function, existing ones untouched; it keeps hash imports out of the DIS7 adapter modules (D2). |

## Sequencing deviations

The work follows the spec's six work packages (R29) in order, with four sequencing deviations that are logged in the delivery report: vectors and contract files are vendored in WP1, because WP2's independent layout tests seed from them; the vector tests (R25) run in WP4; the SDK hook, the `times.render` fix and Adapter API 3.1.0 land in WP1 as part of the API freeze; and the class sits under `adapters/` from WP4 (F5). R28 is read as the single WP4–WP6 commit and push: nothing DIS7 reaches a pushed ref or a built artefact before WP6's gates pass.

## Progress

### R02 — wp1a-vendor

- `.gitattributes`: appended the DIS 7 block (blank line, 4-line comment, `*.dis -text -diff`, `packages/cdm/synapse_cdm/fixtures/dis7/vectors/** -text`, `packages/cdm/synapse_cdm/fixtures/dis7/contract/** -text`) verbatim per Deliverable 1, before any vendored file was staged.
- `pkg/fixtures/dis7/vectors/`: the 16 bundle files (`index.json` plus 5 files each for `equator_eastbound`, `north_pole_stationary`, `unprojectable_with_extensions`) copied with `cp`, `cmp`-identical to `/Users/admin/Documents/cc/dis7-run/bundle/vectors`.
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
- Exit check `bash /Users/admin/Documents/cc/dis7-run/checks/R02.sh` ends `EXIT-CHECK: PASS`, 0 blocked steps (see `logs/R02.exit.log`).
- `docs/dis7-implementation.md` does not exist yet (it is introduced in R03 per the run file's Paths section), so step 3 of "How to finish this run" does not apply this run.

### R03 — wp1a-freeze

- Wrote this record, assembled from `PLAN.md` and `rulings.md` with a throwaway script kept outside the worktree: the thirteen `## ` headings in order, F1 to F11 as D1 to D11, CR-01 to CR-35 as D12 to D46, the five Frozen contract subsections and the 18 codes, the Baseline table read from `reports/baseline.md`, and one decision of this run's own, D47.
- Wrote `pkg/adapters/dis7_codec.py`: the complete error model only — `Dis7Error`, `Dis7InputTooLarge`, `Dis7InputTooDeep` and the 18 code constants plus `CODES`; no stub of any later function.
- Wrote `tests/test_cdm_dis7_codec.py` (10 tests): the code table, the two input-limit subclasses' MROs, the `str()` form, and survival of copy and pickle — the evidence for requirement R21.
- Wrote `tests/test_cdm_dis7_trace.py` (10 tests): the two-way ratchet (`scan_source`, `scan_tree`, `evidence_problems`, `bound_ids`, `ratchet_problems`) over the contract's 38 cases and R01 to R30; `PENDING` holds the 67 ids this run does not bind, and `R_EVIDENCE` binds R21 to the six tests above. No id came back already bound, so none was removed from `PENDING`.
- Bookkeeping: the `CLONE_ONLY_SITES` row for this record in `tests/test_cdm_consumer_path.py`; `test_cdm_dis7_codec.py` added to `PACKAGE_ONLY_TESTS` and `test_cdm_dis7_trace.py` to `REPO_BOUND_TESTS` in `gates/wheel_install.py`; `pkg/MIGRATIONS.md`'s `### Unreleased` raised to 28 files with `dis7_codec.py` named.
- All seven files staged by explicit path; `git diff --name-only v3.1.1 -- packages/cdm | wc -l` prints 28.
- Exit check `bash /Users/admin/Documents/cc/dis7-run/checks/R03.sh` and its result are reported in `reports/R03-runner.md`.

### R04 — wp1b-hook

- Added `Adapter.fixture_instance(clock=None, *, synthetic=True)` directly after `encode()`; its default is `cls(clock=clock, synthetic=synthetic)`, the clock passed by keyword. `load_adapter` moved from line 654 to 671; `SECURITY.md` and `tests/test_cdm_security_policy.py` re-pinned to 671.
- Routed the seven package sites (`harness.main`; `suite._fresh`, `suite._worker_main` twice, `suite._sweep`, `suite.main`; `evidence.generate`) and the eleven test sites through the hook.
- Added `harness.overrides_fixture_instance` and `harness.fixtures_refused_message`, the `--fixtures` refusal in the three entry points, the exit-2 handling of a hook refusal in `harness.main`, `suite.main` and `suite._sweep` (D48 to D50), and the packaged-fixture paragraph of `suite.run`'s docstring.
- Wrote the helper `tests/fixture_instance_double.py` (`RequiresContext`, `ContextDouble`, a coded outer guard) and `tests/test_cdm_fixture_instance.py`, eighteen test functions, added to `PACKAGE_ONLY_TESTS`.
- `pkg/MIGRATIONS.md`'s `### Unreleased` raised to 32 files with `adapter.py`, `harness.py`, `suite.py` and `evidence.py` named. No bump ruling (R06), no `ADAPTER_API_VERSION` change (R05).
- Exit check `bash /Users/admin/Documents/cc/dis7-run/checks/R04.sh` and its result are reported in `reports/R04-runner.md`.

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

Not started.

### R08 — wp2-encode

Not started.

### R09 — wp3-time

Not started.

### R10 — wp3-geodesy

Not started.

### R11 — wp4-loader

Not started.

### R12 — wp4-adapter

Not started.

### R13 — wp4-fixtures

Not started.

### R14 — wp4-replay-tests

Not started.

### R15 — wp4-acceptance

Not started.

### R16 — wp5-cli

Not started.

### R17 — wp5-reference

Not started.

### R18 — wp5-mutation

Not started.

### R19 — wp5-bench-trace

Not started.

### R20 — wp6-roster

Not started.

### R21 — wp6-prose

Not started.

### R22 — wp6-docs

Not started.

### R23 — wp6-gates

Not started.

### R24 — final-fix

Not started.

### R25 — handover

Not started.

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

## Verification

Every run is judged by a mechanical exit check and by an independent verifier session; both write to the pipeline's run directory, outside the repository. Run R22 completes this section.

## Remaining gaps

- Runs R04 to R25 are not started.
- Every unbound case and requirement is listed in `PENDING` in `tests/test_cdm_dis7_trace.py`.
- The OpenDIS reference run stays open until run R17 and case A12's wheel-gate evidence (CR-33) until run R20.

## Handoff

Written by run R22.
