# Versioning — the axes, what moves each, and where each is authored

This document is **normative**. It fixes the version axes this framework carries, the rule that
decides where a new axis belongs, and the relationships between axes — including the relationships
that MUST NOT exist.

It states figures, and every figure it states is derived from the tree by
`tests/test_cdm_architecture_docs.py` rather than trusted here. A version number written into
prose and checked nowhere is the defect this repository has repaired most often.

Its two companions carry the rest of the freeze: [`ARCHITECTURE.md`](ARCHITECTURE.md) is the
adapter contract, and [`INTEROPERABILITY.md`](INTEROPERABILITY.md) is what the framework is, is
not, and how an implementer arrives at a conforming adapter.

---

## 1. The rule that decides where an axis lives

**An axis belongs where the thing it versions is authored.** That is `version.py`'s own rule, in
its own words, and it is the reason three of the axes below are Python constants and the others are
not: a version that lives beside the artefact it describes cannot go stale relative to it, and a
version copied into a Python file so that a Python program can read it conveniently is a second
statement of the same fact.

Two consequences, both normative:

- A new axis MUST be authored where its subject is authored. A profile's version belongs in the
  profile document; the ontology's belongs in the ontology's own metadata; the distribution's
  belongs in the file the packaging reads.
- No axis is DERIVED from another. Nothing in this package computes one axis from another,
  `tests/test_cdm_packaging.py` sweeps for an assignment that would, and the SC-OES specification
  forbids deriving `SC_OES_VERSION` from either number beside it.

---

## 2. The axes

The specification this campaign implements names six axes. The tree already carries six. They
overlap in three, so the union is nine, and all nine are listed — the framework's version model is
the whole set and not the subset one document happened to enumerate.

**Dated correction, 2026-09-07 (round P1, and the sentence above is left standing as written).**
The tree now carries EIGHT: `ADAPTER_API_VERSION` and `MANIFEST_SCHEMA_VERSION` were declared in
`packages/cdm/synapse_cdm/version.py` by P1, so their rows below have stopped reading "added by
P1 / not yet declared" and carry the tree's own name, reading and line. **The union is unmoved at
nine** — both were already rows here, which is what listing an owed axis before it exists is for —
and that is why the sentence above is corrected rather than rewritten: its arithmetic is still
right and only its middle clause has been overtaken. `EVIDENCE_SCHEMA_VERSION` is still owed, by
P4.

**Dated correction, 2026-09-08 (round P4; the two paragraphs above are left standing as written).**
Nothing is owed any more. `EVIDENCE_SCHEMA_VERSION` was declared by P4 at
`packages/cdm/synapse_cdm/version.py:313`, so its row below has stopped reading "added by P4 /
not yet declared" and carries the tree's own name, reading and line — the last of the three rows
this table listed before the constant existed. **The union is unmoved at nine for the third
time**, and the tree's tally is now nine as well, which is the first moment since this table was
written that the two numbers have been equal for a reason rather than by arithmetic.

**Two readings moved in the same round and both are corrections rather than rewrites.**
`MANIFEST_SCHEMA_VERSION` reads `1.1.0`: §34 of the specification needs an "explicit documented
exception" a loss classifier can act on, so `AdapterMetadata.limitations` widened from
`list[str]` to `list[str | Limitation]` and a `Limitation` carries machine-readable
`unsupported_paths`. That is a new optional SHAPE the field accepts, which §3's row below calls a
MINOR, and no existing manifest becomes invalid: all fourteen keep plain sentences and their
`adapter` blocks are byte-identical across the bump. The line citations in the table below moved
too — every one of them, because a new constant was inserted into `version.py` — and they are
re-read here rather than carried over.

**Dated correction, 2026-09-08 (round P5; every paragraph above is left standing as written).**
`MANIFEST_SCHEMA_VERSION` reads `1.2.0`. §40 requires input bounds and M's F5.4 ruling requires a
DECLARED bound to record where its number came from, so `Limits` gained `declared_because` — the
mirror of `absent_because`, keyed by the same five field names, carrying the kind (normative
maximum or implementation cap), the source, the enforcement point and the test. MINOR on §3's row
below: the field defaults to `{}`, so a manifest written against `1.1.0` still validates and no
existing field changed shape. This time all fourteen manifests move in their `adapter` block as
well as their envelope, because all fourteen now DECLARE `max_input_bytes` and so lose an
`absent_because` entry and gain a basis. The evidence row's line citation moved with it — nine
comment lines were added above `MANIFEST_SCHEMA_VERSION` — and both are re-read here.

| axis | spec name | tree name | version today | authored in |
|---|---|---|---|---|
| Python package | `PACKAGE_VERSION` | `PACKAGE_VERSION` | `PACKAGE_VERSION` is `2.1.1` | `packages/cdm/synapse_cdm/version.py:283` |
| CDM schema | `CDM_SCHEMA_VERSION` | `SCHEMA_VERSION` | `SCHEMA_VERSION` is `2.1.0` | `packages/cdm/synapse_cdm/version.py:262` |
| SC-OES specification | `SC_OES_VERSION` | `SC_OES_VERSION` | `SC_OES_VERSION` is `0.1.0` | `packages/cdm/synapse_cdm/version.py:289` |
| Adapter API | `ADAPTER_API_VERSION` | `ADAPTER_API_VERSION` | `2.0.0` | `packages/cdm/synapse_cdm/version.py:300` |
| Manifest schema | `MANIFEST_SCHEMA_VERSION` | `MANIFEST_SCHEMA_VERSION` | `1.2.0` | `packages/cdm/synapse_cdm/version.py:335` |
| Evidence schema | `EVIDENCE_SCHEMA_VERSION` | `EVIDENCE_SCHEMA_VERSION` | `1.0.0` | `packages/cdm/synapse_cdm/version.py:349` |
| Operational Ontology | — | — | declared in its own metadata | `ontology/*.ttl`, projected into `registry/sc_oes/ontology_terms.json` |
| Profile versions | — | — | one per profile, declared per document | each profile document, and `registry/sc_oes/profiles.json` |
| Event semantic major | — | — | a segment of the identifier | the `type_id` itself, e.g. `sc.pnt.gnss_interference.v1` |

**The spec's example figures are illustrative and this table's are readings.** The specification's
version model section carries an example in which the CDM sits at `1.1.0`; the tree governs, and
the tree's readings are the three cells above with a `version.py` line number beside them.

### 2.1 The one name that differs, and why it is not renamed

The specification calls the CDM schema's axis `CDM_SCHEMA_VERSION`. The tree calls it
`SCHEMA_VERSION`, and has since first release. **The name is not changed and this table is the
mapping.**

Renaming it would be renaming a public name in the distribution's surface, which under this
repository's bump rules is not a MINOR to be typed but a two-release procedure; and adding
`CDM_SCHEMA_VERSION` as an alias constant would put two names on one fact, which is the arrangement
`version.py` argues against for the whole length of its docstring. A reader arriving from the
specification needs one sentence of mapping, and this is that sentence.

### 2.2 The three axes that do not become Python constants

The Operational Ontology's version, each profile's version and an event type's semantic major are
axes of this framework and are listed above as such. They are NOT Python constants, on §1's rule:

- the **ontology** is authored in Turtle, and Turtle is the authority — the registry projection is
  derived from it;
- each **profile** is authored in its own document, and seven independent numbers that happen to be
  equal today are still seven numbers;
- an event type's **semantic major** is a SEGMENT OF THE IDENTIFIER rather than a field beside it,
  so a consumer matching on the string cannot fail to notice a breaking change to that type's
  semantics.

Listing them here as framework axes rather than as internal details of one specification is
deliberate: an implementer negotiating compatibility needs to know that nine things can move
independently, and finding out about three of them later is finding out from an incident.

---

## 3. What moves each axis

| axis | moves when |
|---|---|
| Python package | the importable surface, the `Adapter` contract, the harness CLI and its exit codes, or the fixture set changes. Ordinary semver; governed by the bump rules, not by the schema's table |
| CDM schema | the WIRE CONTRACT changes. Governed by `packages/cdm/synapse_cdm/MIGRATIONS.md`'s table, whose rows decide what a bump means |
| SC-OES specification | what `event_class`, `confidence`, a relationship predicate or the effective interval MEAN changes |
| Adapter API | the v2 contract of `ARCHITECTURE.md` §1 changes. An ADDITION is a MINOR; a removal or rename is the two-release procedure |
| Manifest schema | the manifest format changes. A new optional field is a MINOR; a newly required field is a MAJOR, because every existing manifest becomes invalid |
| Evidence schema | the evidence record's shape changes. Same rule as the manifest |
| Operational Ontology | a governed term is added, deprecated or re-defined |
| Profile version | that profile's own document changes what it requires |
| Event semantic major | one governed type's semantics break. It moves for that type and for nothing else |

### 3.1 Independence, and the equalities that are coincidences

`PACKAGE_VERSION` and `SCHEMA_VERSION` read the same number today. They are two separately argued
changes that landed on one number, and the equality is a coincidence rather than a rule: a package
at 2.0.0 does NOT mean SC-OES is at 2.0, SC-OES is at 0.1.0 and Draft, a profile's number says
nothing about the specification's, and an event type's `v1` says nothing about any axis above it.

**CORRECTED 2026-09-08, round P3 (SOIF Part 1, R03), and the correction is the section's own point
arriving.** The two numbers no longer read the same: `SCHEMA_VERSION` moved 2.0.0 -> 2.1.0 with the
CDM foundation primitives and `PACKAGE_VERSION` did not move at all, because a package release is
P8's and PR's business and not this round's. The paragraph above is kept exactly as written — it
argued that the equality was a coincidence and not a rule, and an axis diverging is what that
sentence was for. The table above carries the two numbers as they now stand.

**They MUST NOT automatically share a number.** Anything that made one axis follow another would
turn every one of the coincidences above into a false statement the moment the axes diverged, and
the axes exist in order to be able to diverge.

### 3.2 Adding an adapter MUST NOT force a CDM major

This is a rule the tree already holds, and this section states it where an implementer will look
for it. The wire contract's own document opens on the distinction, at
`packages/cdm/synapse_cdm/MIGRATIONS.md:7`:

> **`schema_version` is not the package's version.**

Its bump table, at `packages/cdm/synapse_cdm/MIGRATIONS.md:16–24`, is what makes the rule derivable
rather than a promise. The MAJOR row is a field removed or renamed, a type narrowed, an enum member
removed, an optional field made required, or the identifier namespace changed — and shipping an
adapter is none of those things. That document's own section recording the adapters that landed
with no schema change at all is the evidence, entry by entry.

An adapter that appears to need a CDM MAJOR has almost certainly found a modelling gap rather than
a versioning one, and the gap is what gets fixed.

---

## 4. What this campaign expects to land, and why it is a floor and not a promise

The distribution's next number is expected to be `2.1.0`, representing the framework's foundation
and assurance work. It does NOT claim a new adapter portfolio exists, because Part 1 adds no source
format.

That number is a **derivation to be taken at the release, not a figure to be typed now**:

- `gates/bump_derivation.py` derives a FLOOR from the arc's own diff, per unit and per shape. The
  floor is what the diff proves; it is not the answer, and a number stronger than the floor needs a
  ruling recorded in `MIGRATIONS.md` in the form that gate reads.
- The release round types the number the gate accepts at that commit. If the gate's floor comes out
  stronger than MINOR, the number moves and this paragraph is what gets corrected — the derivation
  is never adjusted to match the sentence.
- The CDM schema moves to a MINOR **if and only if** the CDM round adds optional fields, which is
  what the schema's own table says an optional addition is. If that round lands nothing additive,
  the schema does not move, and a package MINOR with an unmoved schema is the ordinary case rather
  than an anomaly.

**CORRECTED 2026-09-10, and the second bullet above is what corrected it.** The campaign's number
came out as `2.1.1` and not `2.1.0`. `v2.1.0` was tagged on `b69a267` on 2026-09-09 and its own
`pip-audit --strict` release gate refused to publish it — the audit resolves every installed
distribution against the index, and the one distribution it could not resolve was the release
candidate itself. The tag stays where it is, permanently, and names a commit that never reached
PyPI; the corrective release carries the same content one PATCH higher. The paragraph above is
kept as written because it said this would happen: the number is taken at the release, and the
sentence is what gets corrected. What it did not anticipate is the direction — the floor was never
in question, and the number moved because a workflow refused a tag rather than because a diff
proved anything.

---

## 5. Main advancement

`origin/main` is unchanged by ordinary campaign rounds. Work happens on the campaign branch, is
reviewed, and is pushed to the campaign branch's remote only after the review says so.

A release round is the only round that advances `main`, and it advances it by **fast-forward**:

```text
verified campaign branch → release review → fast-forward main → tag → push → publish
```

**If a fast-forward is impossible, the release round MUST STOP.** It MUST NOT merge and MUST NOT
rewrite history to make the fast-forward possible. A non-fast-forward means `main` moved
independently of the reviewed branch, and the reviewed thing is then not the thing that would be
released — which is precisely the condition a release must not paper over. A previously accepted
and pushed commit is never amended, rebased away, squashed or force-pushed.

Tags are created by release rounds alone, and the tag names the version the tree it points at
declares. That correspondence is gated, not conventional.

### 5.1 The commands, added 2026-09-08 (SOIF Part 1 round P7)

The rule above was written by round P0 and says what MUST happen. This says how, because a rule
whose execution is left to memory is executed differently each time — and the one step where that
matters is the one that cannot be undone.

```bash
git fetch origin
git switch main
git merge --ff-only soif/1.0        # STOP here if it refuses. Do not merge. Do not rebase.
git tag -a v2.1.1 -m "…"            # annotated; the workflow refuses a lightweight tag
git push origin main --follow-tags
```

**`--ff-only` is the whole of it.** Without the flag `git merge` produces a merge commit and
succeeds, which is not a refusal to fast-forward — it is a fast-forward being silently replaced by
something else. The tree that then gets tagged is a tree no review ever saw: a merge commit's
content is `soif/1.0`'s, but the commit is new, and every reading a review took is about a commit
that is now the second parent of something else.

**What a refusal means, and what it does not.** `git merge --ff-only` refuses when `main` holds a
commit the reviewed branch does not. That is not a merge conflict and is not fixed by resolving
one: it means `main` moved independently of the reviewed branch, so the reviewed thing is not the
thing that would be released. The release round STOPS, and what follows is a new round that
reviews the combined history — never a rebase of the branch, and never a force-push. A previously
accepted and pushed commit is never amended, rebased away or squashed (§54; `RUNNER.md`'s hard
limits say the same thing for the loop).

**The order is not interchangeable.** The tag is created on `main`'s new tip AFTER the
fast-forward, because `.github/workflows/publish.yml`'s condition 3 compares the tag's ref against
the tree's `PACKAGE_VERSION` and the release pipeline runs on the tag push. A tag created on the
branch before the fast-forward names the same commit today and stops naming a commit on `main` the
moment anything else lands.

`packages/cdm/synapse_cdm/MIGRATIONS.md`, "Releasing the package", carries the same sequence beside
the five conditions it has to satisfy; that file is the authority on the conditions and this one is
the authority on the axes.
