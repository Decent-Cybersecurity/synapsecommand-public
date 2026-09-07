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

| axis | spec name | tree name | version today | authored in |
|---|---|---|---|---|
| Python package | `PACKAGE_VERSION` | `PACKAGE_VERSION` | `PACKAGE_VERSION` is `2.0.0` | `packages/cdm/synapse_cdm/version.py:213` |
| CDM schema | `CDM_SCHEMA_VERSION` | `SCHEMA_VERSION` | `SCHEMA_VERSION` is `2.0.0` | `packages/cdm/synapse_cdm/version.py:203` |
| SC-OES specification | `SC_OES_VERSION` | `SC_OES_VERSION` | `SC_OES_VERSION` is `0.1.0` | `packages/cdm/synapse_cdm/version.py:219` |
| Adapter API | `ADAPTER_API_VERSION` | added by P1 | not yet declared | `version.py`, when P1 declares it |
| Manifest schema | `MANIFEST_SCHEMA_VERSION` | added by P1 | not yet declared | `version.py`, when P1 declares it |
| Evidence schema | `EVIDENCE_SCHEMA_VERSION` | added by P4 | not yet declared | `version.py`, when P4 declares it |
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
