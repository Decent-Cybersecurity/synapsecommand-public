# Architecture — the contracts a Synapse adapter is written against

This document is **normative**. It uses MUST, MUST NOT, SHOULD, SHOULD NOT and MAY in the sense
those words carry throughout this repository's specifications: a MUST is a condition a gate either
already enforces or is named here as owing enforcement, and a SHOULD is a default that a written
reason may depart from.

It is a **freeze**, not a plan. The contracts below are what every later adapter — in this
repository or outside it — is written against, and the point of stating them before the adapters
exist is that a convention invented per adapter is not a contract. Where a contract is already
enforced in code, this document says where; where it is not yet, it says which round owes the
enforcement and what the interim rule is. A statement here with neither is a defect in this
document.

Two companions carry what does not belong here: [`VERSIONING.md`](VERSIONING.md) carries the
version axes and their relationships, and [`INTEROPERABILITY.md`](INTEROPERABILITY.md) carries what
the framework is, is not, and how an implementer arrives at a conforming adapter.

**What this document does NOT do.** It changes no model, no schema, no adapter and no command. The
only executable thing that landed with it is `tests/test_cdm_architecture_docs.py`, which derives
every figure the three documents state from the tree rather than trusting the prose. That is the
same rule this repository applies to every other count it writes down, and these documents are new
prose with figures in it, which is exactly the thing that goes stale in silence.

---

## 1. Adapter API v2

### 1.1 What v1 is, in the tree, today

The v1 surface is `packages/cdm/synapse_cdm/adapter.py`. It is a class contract enforced at
**class-definition time**:

| element | where | what it is |
|---|---|---|
| `name` | `adapter.py:53` | the registry key; how a `SourceRef` identifies its translator |
| `version` | `adapter.py:54` | the adapter's own semver, stamped into `SourceRef.adapter_version` |
| `direction` | `adapter.py:55` | one of the three wire spellings; see §2 |
| `system` | `adapter.py:58` | the external system the adapter speaks for, into `SourceRef.system` |
| `TRANSFORMS` | `adapter.py:76` | source paths whose value legitimately changes, mapped to the REASON |
| `fixture_dir` | `adapter.py:113` | the fixture directory when it is not the adapter's own name |
| `to_cdm` | `adapter.py:204` | abstract; one source payload in, a list of canonical objects out |
| `from_cdm` | `adapter.py:216` | overridden by an emitting adapter; the base raises the refusal |
| `source_ref` | `adapter.py:176` | the provenance stamp every emitted object carries |
| `now` | `adapter.py:172` | receipt time, from the injected clock and never `datetime.now()` |
| `__init_subclass__` | `adapter.py:115` | the enforcement: the checks below run when the class is defined |

`__init_subclass__` refuses, at import: a missing `name`, `version`, `direction` or `system`; a
`direction` outside the three literals; a declared `egress`/`bidirectional` adapter that does not
override `from_cdm`; an `ingest` adapter that does override it; and a duplicate registry name. An
adapter that cannot honour its own declared direction therefore fails at import — before
deployment, not on the first outbound push.

**This enforcement point MUST NOT move.** A contract checked at call time is a contract discovered
in production, and every v2 addition below is specified so that it can be checked at
class-definition time or by a gate over the manifests, never at first use.

**Dated correction, 2026-09-07 (round P1). Every `adapter.py:N` above moved, and the enforcement
point did not.** P1 added the v2 members `metadata`, `capabilities()`, `detect()`,
`validate_source()`, `decode()` and `encode()` to the same class and three checks to the same
`__init_subclass__`, so each of the eleven cited lines is further down the file than it was — the
citations in the table are the re-derived ones and `tests/test_cdm_architecture_docs.py` compares
every one of them against the file on every run. **Nothing in the eleven rows changed meaning and
no row was added:** this table is the v1 surface, which §1.2's additive rule keeps exactly as it
is, and the v2 members are §1.2's table rather than this one. `adapter.py:3–15`, cited in §4.6, is
unmoved; §4.4's constructor range is re-derived in place for the same reason as these.

### 1.2 What v2 adds

Adapter API v2 is an **ADDITIVE layer over the v1 surface**. Every v1 name above remains, with its
present meaning, for the whole of Part 1 and beyond it:

- v2 MUST NOT remove or rename any v1 class attribute or method.
- Removing or renaming one is a STOP under this repository's bump rules, not a MAJOR to be typed.
  The rule is already written, at `packages/cdm/synapse_cdm/MIGRATIONS.md:29–31`:

  > Renaming a field is two releases, never one: add the new name in a MINOR, populate both, then
  > remove the old one in the next MAJOR. One release that renames is an outage for every consumer
  > that has not been redeployed in the same hour.

v2 adds four members, and renames nothing:

| v2 member | added by | contract |
|---|---|---|
| `metadata` | P1 | the inspectable declaration of §3; the manifest is its generated projection |
| `detect()` | P1 | given a candidate payload, does this adapter claim it? MAY return `None` for "cannot tell" |
| `validate_source()` | P1 | is this payload well-formed against the source standard, independent of translation? |
| `capabilities()` | P1 | the machine-readable capability and limits block of §3 |

**`decode` and `encode` are the v2 NAMES of `to_cdm` and `from_cdm`.** Which is canonical, stated
once so no later round has to decide it:

- `to_cdm` and `from_cdm` are the **implemented** methods through the whole of Part 1. They are
  what the harness calls, what every shipped adapter defines, and what the abstract declaration
  and the refusal in `adapter.py` are written on.
- `decode` and `encode` are the **v2 spellings**, added by P1 as thin aliases on the base class
  that delegate to the implemented pair. An adapter MAY define either name; an adapter that
  defines the v2 name MUST NOT also define a divergent v1 name for the same direction.
- NEITHER v1 name is removed in Part 1. The alias direction is one-way and deliberate: a base-class
  alias is a new public name, which is a MINOR, while removing `to_cdm` would break every adapter
  outside this repository.

A manifest's `api.version: "2"` therefore means **"this adapter declares metadata and honours the
v2 contract"**. It does NOT mean "this adapter uses the new method names", and a gate MUST NOT
infer the second from the first.

---

## 2. Direction model

Direction MUST be explicit. There is no default that means "work it out from which methods are
defined": `__init_subclass__` already refuses the two inconsistent combinations, and the reason it
can is that the declaration is separate from the implementation.

**Six values are frozen here.** Three of them exist in the tree today as lower-case literals —
`adapter.py:42`, `Direction = Literal["ingest", "egress", "bidirectional"]` — and those literals
are the **wire and code spellings** of the first three rows. The upper-case forms are the
specification's names for the same three facts; they are not a second enumeration.

| direction | code spelling | meaning | what it MAY leave unimplemented |
|---|---|---|---|
| INGEST | `ingest` | external format → CDM | `from_cdm`; `__init_subclass__` refuses an override |
| EGRESS | `egress` | CDM → external format | nothing; `from_cdm` MUST be overridden |
| BIDIRECTIONAL | `bidirectional` | both directions implemented | nothing; `from_cdm` MUST be overridden |
| MODEL | added by P1 | semantic representation only; not necessarily a wire codec | `detect()`, because a model adapter has no bytes to sniff |
| TRANSPORT | added by P1 | carries information; does not define the operational semantics | the semantics themselves, which it MUST delegate to a named payload adapter |
| COMPOSITE | added by P1 | combines several source adapters into a higher-level mission exchange model | direct parsing, which it MUST delegate to the constituents it names |

The three added values carry obligations rather than exemptions, and each obligation is what keeps
the value from becoming an escape hatch:

- A **MODEL** adapter MUST declare `capabilities.wire: false`. It has no bytes to `detect`, so
  `detect()` MUST return `None` and the conformance checks that read bytes are SKIP for it — never
  PASS (§4.7).
- A **TRANSPORT** adapter MUST name, in its metadata, the payload adapter whose semantics it
  carries. A TRANSPORT adapter that defines its own operational semantics has misdeclared its
  direction.
- A **COMPOSITE** adapter MUST name its constituents in its metadata, and each named constituent
  MUST itself be an adapter this repository or a declared plugin ships. A COMPOSITE that names no
  constituent is an INGEST adapter with a grander word on it.

This distinction is what later formats need and is why it is frozen before they arrive: a TAXII
adapter carries STIX and does not define it, a JREAP adapter carries Link 16 J-series content and
does not define it, and an AEW&C exchange model composes several sources into one mission picture.

---

## 3. Capability and metadata model

### 3.1 Metadata fields

Every adapter SHALL expose metadata equivalent to the following, and it MUST be inspectable
programmatically — from the class, without parsing a document and without instantiating the adapter
against a payload:

| field | required | what it carries |
|---|---|---|
| `id` | MUST | the stable machine identifier; equal to the registry `name` for a shipped adapter |
| `name` | MUST | the human-readable name |
| `adapter_version` | MUST | the adapter's own semver — the tree's `version`, not the package's |
| `format.name` | MUST | the source standard's name, as its publisher writes it |
| `format.version` | MUST | the edition or version of that standard this adapter is written against |
| `direction` | MUST | one of §2's six values |
| `licence_class` | MUST | one of §3.2's five classes |
| `maturity` | MUST | one of §3.3's seven levels |
| `claim` | MUST | one of §3.4's six statuses |
| `profiles` | MAY | the SC-OES profiles this adapter claims to produce for |
| `capabilities` | MUST | §3.5, including `limits` |
| `limitations` | MUST | what this adapter does NOT do, stated positively and not as an empty list by default |

`limitations` is required and MUST NOT be defaulted to empty. Every adapter in this repository has
limitations — a format edition it does not implement, a message type it declines, a field with no
canonical home — and an adapter declaring none is an adapter nobody has audited.

### 3.2 Licence classes

Five classes are frozen, and the class is a statement about the SOURCE STANDARD's terms and about
what this repository may redistribute, never about the adapter's own licence (which is the
repository's, Apache 2.0):

| class | what it means |
|---|---|
| OPEN | the source standard is publicly available under terms permitting free implementation |
| PUBLIC_GOVERNMENT | published by a government or an alliance body and publicly retrievable, under that body's own terms |
| LICENSED | available for a fee or under a signed agreement; retrievable but not redistributable |
| CONTROLLED | distribution is restricted by classification, export control or a controlling authority |
| PROPRIETARY_PLUGIN | the format is a vendor's private property; any adapter for it lives outside this repository |

A CONTROLLED or LICENSED classification MUST NOT be read as blocking an adapter. It governs what
this repository may hold: a pinned document's own terms are already recorded per document, and the
pin records under `fixtures/*/spec/` exist precisely because the standards are not redistributable.

### 3.3 Maturity model — seven levels

| level | name | what it asserts |
|---|---|---|
| L0 | DOCUMENTED | the relationship to the source standard is documented |
| L1 | DECODED | the source representation can be parsed |
| L2 | CANONICAL | the source can be translated into the CDM |
| L3 | PROVENANCE VERIFIED | the required provenance survives translation |
| L4 | ROUNDTRIP VERIFIED | applicable information survives source → CDM → source within declared tolerances |
| L5 | PUBLIC CONFORMANCE VERIFIED | every applicable public conformance gate passes |
| L6 | EXTERNALLY EXERCISED | verified against an independent real implementation or system |

**L6 MUST NOT be awarded solely by Decent Cybersecurity using synthetic fixtures.** Every fixture in
this repository is synthetic, so no adapter in this repository can reach L6 on the evidence this
repository is able to generate. That is a property of the evidence and not a defect in the adapter,
and stating it here is what stops the top rung from being awarded by the party that also writes the
gate.

### 3.4 Claim status — six statuses

Claim status is a **separate axis from maturity** and MUST NOT be derived from it:

| status | what it asserts |
|---|---|
| DOCUMENTED | the mapping is written down |
| IMPLEMENTED | code exists that performs the mapping |
| VERIFIED | the mapping passes this repository's public gates |
| EXERCISED | it has been run against an independent implementation |
| INTEGRATED | integration with a NAMED external system has actually occurred |
| DEPLOYED | it is running in a named operational or exercise deployment |

An adapter at `maturity: L5` MAY claim `VERIFIED`. It MUST NOT claim `INTEGRATED` unless
integration with the named external system has actually occurred, and the name of that system is
part of the claim. The two axes are separate because one is about how thoroughly this repository
has checked the translation and the other is about what has happened in the world, and the second
cannot be earned by running a test.

### 3.5 Capabilities, and why `limits` lives here

`capabilities()` returns the machine-readable block: which directions are exercised, which message
types or subsets are implemented, whether the adapter is a wire codec, which SC-OES profiles it
produces for, and `limits`.

`limits` is part of `capabilities` and not a separate concept, so that the conformance suite's
resource-limits check and the parser-safety policy read ONE declaration:

| limit | what it bounds |
|---|---|
| `max_input_bytes` | the largest single payload the adapter will accept |
| `max_depth` | nesting depth, where the source format nests |
| `max_objects` | the object or record count a single payload may yield |
| `max_decompressed_bytes` | the expansion an archived or compressed payload may reach |
| `max_parse_seconds` | the wall-clock bound on one parse, where one is practical |

A limit that does not apply to a format MUST be declared absent with a reason, not silently
omitted: "this format does not nest" is a fact about the format and belongs in the declaration.

### 3.6 The MATURITY-ELIGIBILITY algorithm

A maturity level is a **claim about evidence**, so eligibility is computed from check results and
never typed. The algorithm, frozen here and implemented by P1 and P2:

1. Collect the conformance result for every check the suite defines, for this adapter.
2. Each level names the checks it requires (L1 the translate check; L2 translate and schema; L3
   provenance; L4 roundtrip; L5 every check APPLICABLE to this adapter). L0 requires no check — it
   requires a document.
3. A required check that is **PASS** satisfies its requirement.
4. A required check that is **SKIP FROM A DECLARED INAPPLICABILITY** does not block the rung. The
   roundtrip check on an ingest-only adapter is the standing example: there is no egress direction
   to lose information in, so the absence of a roundtrip result is not the absence of evidence.
5. A SKIP is **NEVER printed or recorded as PASS**, at any level, for any reason. The report says
   SKIP and says which declaration made it inapplicable, and the eligibility computation is a
   separate layer that reads that pair.
6. A required check that is **FAIL**, or **SKIP with no declared inapplicability**, blocks the rung
   and every rung above it.
7. L6 is never computed from this repository's own evidence (§3.3).

Rule 4 and rule 5 together are the whole delicacy of this model. Collapsing them — printing PASS
because the rung was not blocked — would make the report say the adapter round-trips when nothing
round-tripped it. Keeping them apart means the report is readable as evidence and the eligibility
is derivable from the report.

---

## 4. Core rules 1–6

These six rules are normative. Each is stated, then mapped to where the tree ALREADY enforces it,
then to the gap a later round closes. The package's own README states seven rules and is not
superseded by this section: those are the CDM's authoring rules for a fixture-level reader, and
these are the six the framework's contract is written on.

### 4.1 Rule 1 — no silent data loss

Unsupported source information MUST be retained when technically and legally possible, in an
explicit residual structure. Unknown source attributes MUST NOT be silently discarded.

**Enforced today.** `lossless.unrepresented()` (`lossless.py:99`) harvests every scalar leaf of the
source payload, harvests every scalar in the CDM output, and reports source values appearing
nowhere; the harness FAILS an adapter on a non-empty report. `lossless.residual()`
(`lossless.py:124`) returns everything the adapter did not consume, with structure preserved, for
the adapter to park. Values that legitimately change are declared in `TRANSFORMS` with a reason and
are PRINTED on every run — an exemption is a visible line in the report, not a silent skip. The
harness's fourth check (`lossless`) is where an adapter meets this rule.

**The gap.** The residual today is parked in `Entity.attributes` or `Event.payload`, which is a
free-form dictionary; the source-identifying container of §5 is P3's addition.

**LANDED 2026-09-08, round P3.** `models.Residual{namespace, data}` and
`lossless.residual_block(adapter, raw, consumed)` exist. What has NOT changed is §5's Part 1
stance: the fourteen adapters shipped here keep the `attributes` / `payload` parking and keep
declaring `residual: legacy`, so no golden moved for residual placement. The container is there
for Part 2, and `tests/test_cdm_lossless.py` carries the rule that a `structured` adapter may not
also use the legacy bag.

### 4.2 Rule 2 — do not invent values

Unknown is not zero. An unknown position is not `0,0`; an unknown altitude, confidence, velocity or
accuracy is not `0`. Missing data SHALL remain missing or be explicitly marked unknown.

**Enforced today, structurally.** `Position` requires `lat` and `lon`, so an unknown position
cannot be spelled as zeros — it is spelled by the absence of a `Position`. The optional scalars
carry the convention in their own field descriptions: `models.py:159`, `alt_m` — "Metres HAE.
None = unknown"; `models.py:163`, `accuracy_m` — "Metres, 1-sigma. None = unknown, never 0". The
mirror-image defect is equally a defect: `0.0` IS a real coordinate, so a truth test on a
coordinate is as wrong as a null-to-zero substitution.

**The gap.** None in the model. What P2 adds is the check that catches a violation in an adapter
rather than in the model.

### 4.3 Rule 3 — deterministic identity

Repeated observations of the same source identity SHALL derive the same canonical identity under
the same configuration. Random identifier generation MUST NOT be used where a stable source
identity exists.

**Enforced today.** `ids.derive()` (`ids.py:33`) is `uuid5` under a namespace fixed for the
lifetime of the CDM major (`ids.py:28`), keyed on `kind|system|external_id`.
`ids.derive_with_basis()` (`ids.py:44`) takes candidate keys in order of preference and reports
WHICH one was used, so an identity keyed on a per-report field is reportable rather than a
footnote. An adapter reaching for a random identifier fails the golden check on its second run.

**The gap.** None in the derivation. P2's identity-stability check is what makes the property
machine-verifiable per adapter rather than a consequence of the golden files.

### 4.4 Rule 4 — deterministic canonical representation

For identical input, adapter version, schema version and configuration, the canonical output MUST
be deterministic.

**Enforced today.** The clock is INJECTED, never read: `adapter.py:161–174` takes a `Clock` in the
constructor and `now()` is the only receipt-time source; `times.py:39` fixes the frozen instant the
harness uses and `times.py:46` builds the frozen clock. The golden check compares byte for byte
under that frozen clock. Serialisation is the goldens' own form (§6).

**The gap.** Determinism is currently a CONSEQUENCE of the golden files: a non-deterministic
adapter fails the golden check on its second run, which is a detection and not a measurement. P2's
determinism check parses one fixture repeatedly, canonicalises, serialises, hashes and compares.

### 4.5 Rule 5 — provenance survives translation

A canonical object SHALL expose enough to determine: source format; format version; source system
if known; adapter; adapter version; original identifier; transformation chain; source hash where
appropriate; source observation time; and ingest time where relevant.

**What the tree carries today.** `SourceRef` (`models.py:103`) carries `system`, `adapter`,
`adapter_version` and a REQUIRED `synthetic` with no default. `SourceId` (`models.py:77`) carries
one external system's own identifier, as a list on `CDMBase` and required with `min_length=1` on
every kind — the reason is in `CDMBase`'s docstring (`models.py:185`) and it is a defect found by
running the harness: an alert's own identifier appeared nowhere in the output, silently, with every
other check passing. `Event.observed_at` (`models.py:376`) is when the SOURCE saw it and
`Event.received_at` (`models.py:377`) is when WE took delivery, and the field descriptions say
"Never receipt time" and "Never source time" because that is the confusion they exist to prevent.

**The gap, named as P3's.** Five of Rule 5's items have no canonical home yet: **source format
name**, **format version**, **original identifier as a first-class provenance field** (as opposed
to one entry of `source_ids`), **transformation chain**, **source hash** and **record index within
the source payload**. Until P3 lands them, an adapter needing any of them MUST park it in the
residual with a documented key, and MUST NOT invent a top-level field.

**CLOSED 2026-09-08, round P3, and the sentence above is kept because it is what the gap was.**
All six now have a canonical home on `SourceRef`: `format_name`, `format_version`, `original_id`,
`source_hash`, `record_index` and `transformations`, every one of them OPTIONAL, plus an
`observed_at` for the record's own instant. `Adapter.source_ref()` fills the first two from the
adapter's own `metadata.format`, so the stamp and the manifest cannot disagree; the other five are
facts about ONE SOURCE RECORD and are set per object by an adapter that has them. The instruction
to park in the residual has therefore expired for these six items and still holds for anything
else.

### 4.6 Rule 6 — adapters do not make operational decisions

An adapter MAY parse, validate, canonicalise, normalise units, translate and preserve provenance.
An adapter MUST NOT rank threats, infer hostile intent without source evidence, recommend targets,
choose courses of action, assign weapons, or make command decisions.

**Promoted to normative here.** The rule is stated at `adapter.py:3–15` under "WHAT AN ADAPTER MAY
NOT DO", with the reason that matters: a decision made inside a translator is invisible in the CDM
output, absent from the audit trail, and discovered only when somebody asks why a contact never
appeared. Decisions belong to the layer where they are visible and attributable, which is not this
repository. The boundary is enforced over the package sources by `tests/test_cdm_boundary.py` — no
import of private code, no reasoner, no graph database, no message broker, no model SDK, no crypto
in the contract layer.

### 4.7 SKIP, once, for all six

A check that does not apply to an adapter reports **SKIP**, never PASS, and the report states which
declaration made it inapplicable. This is stated once here because it is the rule the maturity
algorithm (§3.6), the conformance suite and the evidence records all read, and three
implementations of it would be three chances to print PASS.

---

## 5. Residual-field policy

Residual information MUST identify its origin, and MUST NOT be treated as semantically trusted
merely because it survived translation. A residual is a **preservation** mechanism: it says "the
source said this and the CDM has no home for it", which is a fact about the source record and not
an assertion about the world.

The container P3 adds is origin-identifying: it names the source format the leftovers came from and
holds their structure beneath that name, so a reader meeting an unfamiliar key can find out which
standard's vocabulary it belongs to. A consumer MUST NOT promote a residual value into a canonical
field, and a later adapter MUST NOT read another adapter's residual as an input.

**The Part 1 stance for the adapters already shipped, ruled and stated rather than left to a later
round to discover.** The fourteen adapters in this repository park their leftovers today in
`Entity.attributes` / `Event.payload` via `lossless.residual()`, under `source_extras`. They KEEP
that placement through Part 1 and declare it in their manifests as `residual: legacy`. Every Part 2
adapter uses the structured container. The goldens are therefore NOT rewritten for residual
placement in Part 1, on the specification's own instruction not to introduce a breaking change for
stylistic cleanliness: the information is already preserved, the placement is what changes, and
paying for that with every golden file and every downstream consumer buys nothing a reader can use.

**Added 2026-09-08, round P3.** The four policies this section and §4 state normatively — geometry
and CRS, units, time, and residual — are also written for a reader rather than for an implementer
at `docs/docs/cdm/policies.mdx`, which names the line that enforces each one. This document stays
the normative text; that page is its projection and adds no rule.

---

## 6. Deterministic behaviour

### 6.1 What "identical configuration" includes

Determinism is asserted over a tuple, and the tuple is enumerated so that "same configuration" is
not a matter of opinion:

- the **input bytes** (or the parsed source object, where the adapter is given one);
- the **adapter version**;
- the **CDM schema version**;
- the **clock** — the injected `Clock`, frozen for any comparison;
- the **`synthetic` flag**, which is required and has no default and therefore always part of the
  configuration;
- every other constructor argument the adapter declares.

Change any member and the output MAY differ. Change none and it MUST NOT.

### 6.2 Serialisation and hash

The canonical serialisation for comparison, hashing and golden storage is the goldens' existing
form, stated here so that no later round chooses a second one:

```text
json.dumps(obj, sort_keys=True, indent=2)   UTF-8, trailing newline
sha256 over those UTF-8 bytes
```

`sort_keys=True` is what makes two serialisations of one object comparable as strings, and the
existing golden files are already written this way. A hash quoted anywhere in this framework —
evidence records, witness entries, conformance output — is sha256 over the UTF-8 bytes of that
form unless the quoting site names another algorithm explicitly.

Time has one serialised form throughout: RFC 3339 UTC, exactly three decimals, always `Z`. Two
timestamps meaning the same instant MUST compare equal as strings, because that is what golden
diffs and chain hashes compare.

---

## 7. CI layout

**What exists today.** `.github/workflows/` holds exactly one workflow, `publish.yml`, and its
triggers are `push:` on tags matching `v*` and `workflow_dispatch` (`publish.yml:119–125`). The
dispatch trigger exists so the build-and-gate half is runnable against any branch without
publishing anything; the publish job is guarded on the ref being a tag.

**What that means, and it is a design constraint rather than a complaint.** A push to a branch
starts no workflow. Every "CI MUST fail if …" clause in this campaign — a missing or invalid
manifest, an impossible direction, an unknown maturity value, a conformance regression, a fixture
without provenance — therefore has nothing to fail on until a second workflow exists.

**`ci.yml`, designed here and created by P1.** One workflow, on `push` to `main` and to `soif/**`
and on `pull_request`:

| job | added by | what it runs |
|---|---|---|
| `suite` | P1 | the repository's own test suite from a clean checkout |
| `gates` | P1 | the checks under `gates/` that do not need the network |
| `manifests` | P1 | manifest presence, schema validity and consistency with the implementation |
| `conformance` | P2 | Conformance Suite v2 over every shipped adapter, JSON output retained |
| `evidence` | P4 | evidence generation and verification, and fixture provenance |
| `secrets` | P5 | the secret-scanning gate |
| `supply-chain` | P6 | dependency review, dependency audit and the static-analysis gate |

`publish.yml` keeps its present shape and its present triggers. The two files have separate jobs: a
release pipeline that also runs pull-request checks becomes a release pipeline nobody may restructure.

---

## 8. Conformance namespaces

**There are two letterings, and they are two namespaces.** Confusing them would be easy and the
confusion would be silent, so the rule is stated before either grows:

| namespace | letters | authority | in the tree |
|---|---|---|---|
| harness checks | A–F today, A–O after P2 | this document and the conformance suite | `harness.py:473`, `_COLUMNS` |
| SC-OES dimensions | A–E | `spec/sc-oes/` and its own conformance document | `conformance.py:139`, `DIMENSIONS` |

The harness's six checks are the framework's A–F, in this order and with these code names:
`translate`, `schema`, `provenance`, `lossless`, `roundtrip`, `golden` (`harness.py:473`). P2 adds
G through O: deterministic, malformed-input, unknown-field-preservation, temporal correctness,
identity stability, version compatibility, streaming, parser robustness, resource limits.

The SC-OES tool's five dimensions are A "CDM Conformance", B "SC-OES Core Syntax Conformance", C
"SC-OES Semantic Type Conformance", D "SC-OES Profile Conformance" and E "Ontology Conformance"
(`conformance.py:139–145`), with its own exit codes (`conformance.py:151–157`). **Its letters are
NOT renamed.** They are part of a published specification's consumer-visible surface, and renaming
them to free up the alphabet would be a breaking change to a document in order to tidy a document.

Two rules follow, and both are testable:

1. **Prose says which namespace it means.** "Harness check G", "SC-OES dimension D" — never a bare
   letter. A bare letter in a document that discusses both is ambiguous in exactly the way a reader
   cannot detect.
2. **The JSON keys are distinct.** The conformance suite's machine output keys harness checks under
   a key of its own, and the SC-OES tool keys its dimensions under `dimensions` as it does today. A
   consumer merging two reports MUST NOT find one letter meaning two things.

---

## 9. What this document froze, and what it did not

Frozen here: the v2 surface and the additive rule; the six directions and the obligations of the
three new ones; the metadata fields, five licence classes, seven maturity levels and six claim
statuses; the position of `limits` inside `capabilities`; the maturity-eligibility algorithm and
the SKIP rule; the six core rules with their present enforcement and their named gaps; the residual
policy and Part 1's stance for the adapters already shipped; the determinism tuple, the
serialisation form and the hash; the CI layout; and the two conformance namespaces.

Not frozen here, and owed by a named round: the manifest schema and the maturity and claim values
of each shipped adapter (P1); checks G–O, the SKIP semantics in code and the JSON output shape
(P2); the CDM primitives and the structured residual container (P3); the evidence record and its
schema (P4); the parser-safety policy's concrete bounds (P5); the supply-chain gates (P6); and the
release pipeline's restructured shape (P7).
