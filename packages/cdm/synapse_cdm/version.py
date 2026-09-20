"""Three version numbers, what each one governs, and why they are not one number.

THE DISTINCTION, STATED ONCE
----------------------------
This package carries three semver strings and they answer different questions.

**THIS FILE OPENED "Two version numbers" UNTIL 2026-09-06, and the sentence moved rather than
being footnoted**, because a third axis arrived and a docstring that still said two would have
been wrong in its first line. What did NOT move is the argument: nothing below is weakened by
there being three, and the reason each is separate is the reason it was already.

``SCHEMA_VERSION`` is the **wire contract's** version. It is carried in EVERY serialised
object as ``schema_version``, because a consumer that reads an object off a queue has no
other way to know which shape it is holding. It is governed by ``MIGRATIONS.md`` — that
document's table decides what a bump means, its History section records every one, and its
procedure is what a schema change has to walk through.

``PACKAGE_VERSION`` is the **distribution's** version — what ``pip install synapse-cdm==…``
resolves and what ``importlib.metadata.version("synapse-cdm")`` returns. It is ordinary
semver over the Python surface: the importable names, the ``Adapter`` contract, the harness
CLI and its exit codes, the fixture set. It follows the general rule and not MIGRATIONS.md.

``SC_OES_VERSION`` is the **SynapseCommand Operational Event Specification's** version — the
wire-semantic contract in ``spec/sc-oes/``, carried by a producer in ``Event.oes.spec_version``
to say which semantics it is claiming. It is a THIRD axis and not a restatement of either
number above: it moves when what ``event_class``, ``confidence``, a relationship predicate or the
effective interval MEAN changes, and it does not move when a field is added to a CDM object or
when an adapter ships. ADR 0003 decision 7 places it here and §46 forbids deriving it from
either of the other two. Three further axes exist and are deliberately NOT Python constants: the
Operational Ontology's version lives in the ontology's own metadata, each profile declares its
own version in its own document, and an event type's semantic major is a segment of the
``type_id`` itself. An axis belongs where the thing it versions is authored, which is the same
rule that keeps the two numbers below apart.

THE NINE AXES, AND WHAT EACH ONE MOVES FOR
------------------------------------------
Six of them are constants in this file; three are authored where the thing they version is
authored, which is the same rule stated one level up. The full set, as of 2026-09-08::

    (This heading read SIX and the split read "three and three" until 2026-09-07, when round P1
    declared ``ADAPTER_API_VERSION`` and ``MANIFEST_SCHEMA_VERSION``. ``VERSIONING.md``'s table
    listed both as rows before either existed — "added by P1", "not yet declared" — so the UNION
    the table states is unmoved at nine and it is this file's own tally that moved.)

    (It read EIGHT until 2026-09-08, when round P4 declared ``EVIDENCE_SCHEMA_VERSION`` — the
    last row ``VERSIONING.md`` carried as owed. This file's tally has now caught the table up:
    the union was nine before this constant existed and is nine after it, because listing an
    owed axis before it exists is exactly what that table is for.)

    Python package        2.2.0   this file, ``PACKAGE_VERSION``. Semver over the importable
                                  surface, the ``Adapter`` contract, the harness CLI, the
                                  fixture set. What ``pip install synapse-cdm==…`` resolves.
    CDM schema            2.1.0   this file, ``SCHEMA_VERSION``. The WIRE CONTRACT, carried in
                                  every serialised object, governed by ``MIGRATIONS.md``.
                                  (2.0.0 -> 2.1.0 on 2026-09-08, round P3: optional primitives
                                  only. The package did not follow it for two days and then did,
                                  on 2026-09-09, at the same number by coincidence — a schema
                                  bump obliges a release and does not perform one. They parted
                                  again on 2026-09-10, at 2.1.1 against 2.1.0, and the schema did
                                  nothing to deserve it: the package took a corrective PATCH for a
                                  release gate that refused its own tag, which is precisely the
                                  kind of event this table exists to keep off the other axes. And
                                  a third time on 2026-09-12, at 2.1.2 against 2.1.0, for the same
                                  class of reason: the tag 2.1.1 named was refused by the release
                                  pipeline's CodeQL gate, so the package took one more corrective
                                  PATCH and the wire contract still had no part in it. And on
                                  2026-09-17, at 2.2.0 against 2.1.0, for the ordinary reason at
                                  last: the audit arc added public names and moved the Adapter
                                  API to 2.1.0, and no wire field, schema or golden moved.)
    SC-OES                0.1.0   this file, ``SC_OES_VERSION``. The wire-SEMANTIC contract in
                                  ``spec/sc-oes/``, claimed by a producer in
                                  ``Event.oes.spec_version``. Still a Draft specification.
    Operational Ontology  0.1.0   the ontology's own metadata in ``ontology/*.ttl``, projected
                                  into ``registry/sc_oes/ontology_terms.json``.
    Profile versions      0.1.0   each profile declares its own, in its own document and in
                                  ``registry/sc_oes/profiles.json``. Seven independent numbers
                                  that happen to be equal.
    Event semantic major  v1      a SEGMENT OF THE IDENTIFIER — ``sc.pnt.gnss_interference.v1``
                                  — so a consumer matching on the string cannot fail to notice
                                  a breaking change to one type's semantics.
    Adapter API           2.1.0   this file, ``ADAPTER_API_VERSION``. The CONTRACT an adapter
                                  class is written against — what ``Adapter`` requires of a
                                  subclass and what it offers it. Frozen by ``ARCHITECTURE.md``
                                  §1 and additive over v1; 2.1.0 added the round-trip tolerance
                                  declarations (2026-09-16) and, like v2, renamed nothing.
    Manifest schema       1.2.0   this file, ``MANIFEST_SCHEMA_VERSION``. The shape of the
                                  published manifest, generated into
                                  ``schemas/manifests/adapter-manifest.schema.json`` and carried
                                  in every file under ``manifests/``. (1.0.0 -> 1.1.0 on
                                  2026-09-08, round P4: ``limitations`` widened to accept a
                                  structured ``Limitation`` beside the sentence it already
                                  accepted. Additive, so a MINOR by this table's own rule.)
    Evidence schema       1.0.0   this file, ``EVIDENCE_SCHEMA_VERSION``. The shape of the
                                  generated evidence record, published into
                                  ``schemas/evidence/evidence.schema.json``. NOT derived from
                                  ``SCHEMA_VERSION``: a record carries the CDM version it
                                  measured in its own ``cdm_version`` field, so binding the
                                  record's shape to the contract it reports on would move this
                                  number every time the measured thing moved.

**Independence is the whole arrangement, and the equalities are coincidences.** Package 2.0.0 and
schema 2.0.0 are two separately argued major changes that landed on one number (see below); a
package 2.0.0 does NOT mean SC-OES 2.0, and SC-OES is at 0.1.0 and Draft. A profile at 0.1.0 says
nothing about the specification's version, and an event type's ``v1`` says nothing about any of
the five above it. Nothing in this package computes one axis from another, ``tests/
test_cdm_packaging.py`` sweeps for an assignment that would, and §46 forbids deriving
``SC_OES_VERSION`` from either number beside it.

WHY THEY MUST BE ALLOWED TO DIVERGE — AND, SINCE 1.1.0, WHY THAT IS NO LONGER AN ARGUMENT
-----------------------------------------------------------------------------------------
**They have diverged, and 1.2.0 widened the gap without anybody arguing about it.**
``PACKAGE_VERSION`` is ``2.2.0`` and ``SCHEMA_VERSION`` is ``2.1.0``, and this paragraph is the
eighth version of itself that does not have to reason about a hypothetical. (Corrected
2026-09-08, round P3. It read "``SCHEMA_VERSION`` is ``2.0.0``" and "third version" for one day:
the schema took a MINOR for the CDM foundation primitives and the package took nothing, so the
paragraph below — written the day the two became equal — is already describing a state that has
passed. It is kept as written; this is the sentence that overtakes it. **Corrected again
2026-09-09, the 2.1.0 release**: the two are LEVEL once more, for the fourth time in this file's
life and for the reason the last paragraph of the packaging sweep's docstring predicted — a
schema MINOR obliges at least a package MINOR, so the day the package pays that debt is a day
the two numbers can land on one value. They are level and neither is computed from the other,
which is the only thing this section has ever claimed. **Corrected a third time 2026-09-10, the
2.1.1 corrective release, and the level lasted one day**: ``v2.1.0`` was tagged and its own
``pip-audit --strict`` release gate refused to publish it, so the package took a PATCH the schema
had no part in and the two numbers parted for the fifth time. Nothing about the wire contract
moved on either day. That is the argument this section makes, arriving from a direction nobody
anticipated: the axis that moved was moved by a workflow's defect. **Corrected a fourth time
2026-09-12, the 2.1.2 corrective release, and the parting is now two PATCHes wide**: ``v2.1.1``
was tagged on ``4409115`` in turn and refused by the release pipeline's CodeQL gate, which asked
for the code-scanning analyses of a tag ref no workflow in this repository can produce, so the
package took a second corrective PATCH the wire contract again had no part in. Two of the five
partings in this file's life are now workflow defects rather than contract decisions, which is
worth stating plainly: this axis records what was RELEASED, and a release is a thing a pipeline
can refuse. **Corrected a fifth time 2026-09-17, the 2.2.0 release, and the parting is now a
MINOR wide for the reason this section was written to describe**: the audit arc since ``v2.1.2``
added importable names — ``adapter.InputTooDeep`` and the depth-bound helpers, the round-trip
tolerance members that moved ``ADAPTER_API_VERSION`` to 2.1.0, ``canonical.py``,
``harness.select_fixtures``, ``SEMVER_RE`` and ``is_semver`` in this file — and removed nothing,
so ``gates/bump_derivation.py`` derived MINOR with nothing unruled; the schema moved by nothing,
because no field, no published schema and no golden changed. The surface grew and the contract
did not, which is what two numbers are FOR.)

**AND ON 2026-09-07 THEY BECAME EQUAL AGAIN, WHICH IS A COINCIDENCE AND NOT A DERIVATION.**
``PACKAGE_VERSION`` moved 1.8.0 -> 2.0.0 by ADR 0005's decision, over its own table: a third
party's adapter or consumer written against 1.8.0 does not work against a distribution whose
canonical objects carry two new keys. The schema moved to 2.0.0 the day before, over
``MIGRATIONS.md``'s table, for a different reason on a different axis. **Two independently
justified major changes that happen to land on the same number**, and the arithmetic that
produced each is written down where that axis is governed. They were also equal at ``1.0.0``,
at first release, for exactly the same kind of reason — and that equality did not survive the
eleventh adapter. Neither will this one: the next adapter is a package MINOR that moves no
contract. Nothing below derives either number from the other, and
``tests/test_cdm_packaging.py`` sweeps the package to keep it that way, with the sweep's own
docstring recording that its teeth return whenever the two are level. **Corrected
2026-09-06:** it read "``SCHEMA_VERSION`` is ``1.0.0``" for eight package releases, and the
SC-OES model round moved the wire contract for the first time. The gap did not close and it did
not merely widen — it reversed direction on one axis, which is worth stating plainly because it
is the first evidence in this file that runs the other way. The schema is now a MAJOR AHEAD of
where a mechanical derivation from the package number would put it, and the package number has
not moved at all: a schema bump obliges a package release, it does not perform one. Every entry in
``MIGRATIONS.md``'s 1.1.0 and 1.2.0 sections says the same two things — an added surface, no
schema touched — so each release moved one number and not the other, which is exactly what two
numbers are FOR.

**1.2.1 moved this number for no surface at all, and that is the PATCH row read literally.**
It ships comments and shipped documents and nothing importable — no adapter, no harness flag,
no fixture set, no dependency — so the MINOR list below does not reach it and the PATCH row
does. The round behind it was large and almost none of that is in the distribution, which is
the distinction this number exists to make: it states what a consumer receives, not how much
work a round did.

**1.2.0 is the release where that arrangement was TESTED rather than merely relied on.** It
ships a new kind of output — a structured defect annotation, which the ``stanag4609`` adapter
writes when a KLV item's octet count contradicts its own standard's Required Length — and
"new output surface"
is exactly the shape that ought to move a schema version. It did not, and the ruling is recorded
in ``MIGRATIONS.md``'s 1.2.0 section with the file and line of the evidence rather than as a
judgement: the annotation lives inside ``Entity.attributes`` and ``Event.payload``, both of which
the published schemas declare ``additionalProperties: true`` while the objects that carry them
are ``additionalProperties: false``. A question that gets asked once and answered from bytes does
not have to be asked again.

Until 1.1.0 they were both ``1.0.0``, and a reader who saw two equal numbers reasonably
concluded one of them was redundant. That was the weakest moment for this file's whole case: the
claim rested on a counterfactual, and any code that derived one number from the other would have
produced the right answer on every run. ``tests/test_cdm_packaging.py`` says so in as many words
and records that 1.1.0 closed the window — a derivation would now be wrong at runtime rather
than right by luck.

The supporting measurement stands and is worth keeping, because it says how far apart they
WOULD already be: ``MIGRATIONS.md`` has a section titled "Adapters that landed with no schema
change" and it holds **thirteen** entries — thirteen adapters, each of which added thousands of
lines of shipped behaviour to this distribution at ``schema_version`` 1.0.0, with no field
added, removed or retyped. That count is derived from the section's own bullets by
``tests/test_cdm_prose_counts.py`` rather than stated here on trust.

Had this package been released before any of them, each would have been a package MINOR and
none of them a schema bump. The two numbers would already be thirteen minors apart. Deriving one
from the other — which is what this file used to do, with the packaging metadata reading
``SCHEMA_VERSION`` directly — would have produced a distribution that could not express "the
same contract, more adapters", and the only ways out are both wrong: bump the contract for a
change no consumer's parser cares about, or ship fourteen different distributions all labelled
1.0.0 — that first release and one per adapter in the section — and let the index refuse the
second one.

The failure the old arrangement was defending against is real and is still defended against,
just not by conflation: the risk was a wheel labelled 1.0.0 shipping objects that say 1.1.0.
That is a DRIFT problem, and drift is what gates are for — ``tests/test_cdm_release.py``
requires every release tag to name the ``PACKAGE_VERSION`` of the tree it points at, and
``tests/test_cdm_schemas.py`` requires the published schemas to carry the ``SCHEMA_VERSION``
the models generate. Neither needs the two strings to be the same string.

WHERE 1.0.0 CAME FROM, FOR THE PACKAGE
---------------------------------------
Ruled at ``1.0.0`` rather than ``0.1.0``. ``0.x`` says "the API may change under you without
notice", and that is not what this is: fourteen adapters are shipped and harness-verified, the
``Adapter`` contract has been stable across all fourteen of them, and the whole point of a
contract layer is that consumers may depend on it. A ``0.x`` first release would be
advertising an instability the tree does not have. The coincidence with ``SCHEMA_VERSION``
1.0.0 is a coincidence of two first releases, and it did not survive the eleventh: `cat062`
and `cat023` both landed at ``schema_version`` 1.0.0 with no field added, removed or
retyped, so the package number is now two adapters ahead of the contract number in the
only sense that matters — what a release of it would have to be.

WHAT EACH BUMP MEANS
--------------------
For ``SCHEMA_VERSION`` — the full policy and the changelog are in ``MIGRATIONS.md``; short form:

    MAJOR  a field is removed or renamed, a type narrows, an enum member is removed, or an
           optional field becomes required. Consumers break. Requires a migration note.
    MINOR  a field is added optional, an enum member is added, a payload model is registered.
           Old readers keep working; old data keeps validating.
    PATCH  documentation, description text, validation message wording. No shape change.

For ``PACKAGE_VERSION`` — semver over the Python surface:

    MAJOR  an importable name is removed or its meaning changes, the ``Adapter`` contract
           changes in a way that breaks a third-party adapter, a harness exit code or flag
           is removed, the Python floor is raised.
    MINOR  an adapter is added, a harness flag or check is added, a fixture set is added,
           a new optional dependency. Existing code keeps working.
    PATCH  a translation fix, a message, a docstring. No surface change.

    A ``SCHEMA_VERSION`` bump is ALWAYS at least a package MINOR, because the objects this
    package emits change shape. The reverse does not hold, and that is the whole point.

    **AT LEAST is the operative phrase and 2.0.0 is where it stops being cheap.** A schema
    MAJOR is not a package MINOR by this rule; the rule states a FLOOR and says so. What the
    package number owes a schema MAJOR is derived from the package table above, on the package
    table's own words — ADR 0005 records that derivation, and the release that types the number
    is the one that writes the ruling. This paragraph fixes no number.

For ``SC_OES_VERSION`` — semver over the wire-semantic contract in ``spec/sc-oes/``:

    MAJOR  a semantic rule changes so that a conformant producer's existing events mean
           something different, or a conformant consumer's existing handling becomes wrong.
    MINOR  an optional concept a consumer may ignore is added.
    PATCH  wording, rationale, a corrected example. No rule changes.

    A breaking change to ONE governed event type's semantics is none of these: it takes a new
    semantic major inside that type's own identifier and leaves this number alone. That is what
    versioning inside the identifier buys — a consumer that knows ``v1`` and meets ``v2`` cannot
    fail to notice, because the string it matches on has changed.

``SCHEMA_VERSION`` is compared with ``compatible()`` rather than by equality, because an
object written by 1.2.0 is readable by a 1.0.0 consumer and refusing it would be a
self-inflicted outage. ``PACKAGE_VERSION`` needs no such helper: ``pip`` resolves it.
"""
import enum
import re
from typing import NamedTuple

#: The wire contract. Governed by MIGRATIONS.md. Carried in every serialised object.
#: Moved 1.0.0 -> 2.0.0 on 2026-09-06, a MAJOR: `Event` gained `oes` and `Entity` gained
#: `ontology_types`, and the canonical objects are `additionalProperties: false`, so a 1.x
#: strict reader REFUSES an object carrying either key rather than ignoring it. That is
#: MIGRATIONS.md's MAJOR row read by its consequence column — "breaks readers" — and it is why
#: this is not a forward-compatible 1.1. ADR 0005 is the decision.
#: MOVED 2.0.0 -> 2.1.0 on 2026-09-08, a MINOR, by round P3 (SOIF Part 1, R03): the CDM gained
#: the geometry, vertical, temporal-validity, route, area, quality, provenance, status and
#: residual primitives, and EVERY ONE of them is an optional field or a new model reached only
#: through one. Nothing was removed, nothing was renamed, no type was narrowed and no optional
#: field became required, so MIGRATIONS.md's MINOR row is the whole of it: old readers keep
#: working and old data keeps validating. `compatible()` below is what makes that true in
#: practice — a 2.0.0 reader accepts a 2.1.0 object, and the round proves it on a golden file
#: written before the bump.
SCHEMA_VERSION = "2.1.0"

#: The distribution. Governed by ordinary semver over the Python surface; read by
#: `pyproject.toml` as the packaging version, and by `tests/test_cdm_release.py` as the
#: number every release tag has to name. NOT the same fact as SCHEMA_VERSION — see above.
#: Moved 1.8.0 -> 2.0.0 on 2026-09-07, a MAJOR, and the decision is ADR 0005's rather than a
#: derivation from the line above it: `Event.oes` and `Entity.ontology_types` change what this
#: package emits, so a third party's consumer written against 1.8.0 does not work against this
#: distribution. `gates/bump_derivation.py` derives a FLOOR and the floor for this arc is MINOR;
#: the floor is not the answer, and ADR 0005 is where the answer is argued.
#: Moved 2.0.0 -> 2.1.0 on 2026-09-09, a MINOR, and this one IS the derived floor: the SOIF Part 1
#: arc adds an Adapter API v2 surface, a conformance suite, evidence records and the CDM 2.1.0
#: optional primitives, and removes nothing — so the gate's floor and the release's number are the
#: same number, which is the ordinary case and was not the case one release ago.
#: Moved 2.1.0 -> 2.1.1 on 2026-09-10, a PATCH, and it is a CORRECTIVE release rather than new
#: content: `v2.1.0` was tagged on `b69a267` and its own `pip-audit --strict` release gate refused
#: it, because the audited environment holds the version the run had not published yet. The tag
#: stays where it is and 2.1.0 never reached the index. What moved between the two numbers is the
#: gate, not the distribution — `gates/bump_derivation.py`'s floor for the arc v2.1.0 -> v2.1.1 is
#: PATCH with nothing unruled, and this number is that floor. A reader installing 2.1.1 gets
#: everything 2.1.0 was going to carry.
#: Moved 2.1.1 -> 2.1.2 on 2026-09-12, a PATCH, and it is the SECOND corrective in three days: the
#: tag `v2.1.1` on `4409115` was refused by the release pipeline's CodeQL gate at step 16 of 17,
#: which asked for the code-scanning analyses of `${GITHUB_REF}` — `refs/tags/v2.1.1` on a tag
#: push, and no workflow in this repository can produce an analysis on a tag ref. Round PQ made
#: that gate read the analyses of the COMMIT and wrote `gates/release_ref_rehearsal.py`, which
#: replays every ref-dependent step against a tag while it is still local; round PV made that
#: module's own test derive the tag from this constant rather than write it down. Neither 2.1.0
#: nor 2.1.1 reached the index; both tags stay where they are. The floor for the arc
#: v2.1.1 -> v2.1.2 is PATCH with nothing unruled, and this number is that floor.
#: Moved 2.1.2 -> 2.2.0 on 2026-09-17, a MINOR, and this one IS the derived floor again — the first
#: number since 2.1.0 that moved for what the distribution carries rather than for what a workflow
#: refused. The audit arc since `v2.1.2` adds public names and removes nothing: `adapter.InputTooDeep`,
#: `json_nesting_depth`, `container_depth`, `enforce_depth_bound`, `is_shipped` and `shipped`; the
#: `ROUNDTRIP_TOLERANCE`, `ROUNDTRIP_TRANSFORMS` and `roundtrip_reference()` members of `Adapter`,
#: which moved `ADAPTER_API_VERSION` 2.0.0 -> 2.1.0 on its own row; `canonical.py`;
#: `harness.select_fixtures` and `fixtures_required_message`; `SEMVER_RE` and `is_semver` below;
#: six `*_MAX_DEPTH` module constants; and a `[lint]` extra in `pyproject.toml`.
#: `gates/bump_derivation.py` derives MINOR over that arc with nothing unruled once MIGRATIONS.md's
#: eighty-three rulings in the 2.2.0 section are read, so the gate's floor and this number are one
#: number. `SCHEMA_VERSION` stays at 2.1.0: no wire field, no published schema and no golden moved.
PACKAGE_VERSION = "2.2.0"

#: The SC-OES wire-semantic contract's version, and a THIRD axis. Carried by a producer in
#: `Event.oes.spec_version`; read by nothing in this package as a gate, because an event written
#: against a later specification version must stay transportable. NOT derived from either number
#: above, and not equal to them by anything but coincidence — see the docstring.
SC_OES_VERSION = "0.1.0"

#: The Adapter CONTRACT's version, and a FOURTH axis. Major 2 because `ARCHITECTURE.md` §1.2
#: freezes v2 as an ADDITIVE layer over v1 — `metadata`, `detect()`, `validate_source()` and
#: `capabilities()` added, `decode`/`encode` as aliases, no v1 name removed — while requiring a
#: subclass to DECLARE its metadata, a new demand on the subclass and so a major. 2.0.0 -> 2.1.0
#: on 2026-09-16: `ROUNDTRIP_TOLERANCE`, `ROUNDTRIP_TRANSFORMS` and `roundtrip_reference()`
#: added to the base class so the harness can compare egress octets under a declared tolerance;
#: every default is the old behaviour, so a MINOR by VERSIONING.md §3's own row. NOT derived from
#: PACKAGE_VERSION: `pip install synapse-cdm==2.0.0` resolves a distribution whose Adapter API is
#: v1, because this constant did not exist at that tag, and 2.1.x ships this 2.1.0 contract.
#: 2.1.0 -> 3.0.0 on 2026-09-20, the audit remediation's S10 ruling: `AdapterMetadata.binding`
#: (F05) is REQUIRED and has no default — a default would be the framework making a wire-level
#: claim the author did not, which is the reason F05 refused one — so every subclass written
#: against 2.1.0 fails to construct its metadata until it declares one of the three
#: `manifest.WireBinding` values. A new demand on the subclass is what made v2 a major and it is
#: what makes this one; `Adapter.MAPPINGS` (F02) is additive beside it and would have been a
#: MINOR on its own. The migration is one line per adapter class — `binding="standard-encoding"`
#: where the wire form is the cited document's own encoding, or
#: `binding="provisional-internal-profile"` with a limitation that contains the word
#: "provisional" — and MIGRATIONS.md's S10 record under Unreleased carries the full note.
ADAPTER_API_VERSION = "3.0.0"

#: The published manifest's shape, and a FIFTH axis. It moves when the MANIFEST's shape moves — a
#: required field added, a field's meaning changed — and not when an adapter's metadata VALUES
#: move, which is the distinction that keeps a consumer's schema check from failing on somebody
#: else's maturity. `schemas/manifests/adapter-manifest.schema.json` is generated from
#: `manifest.AdapterManifest` and every file under `manifests/` declares this number in its own
#: `manifest_schema_version`.
#:
#: `1.0.0` was the first manifest schema there had ever been. **`1.1.0` on 2026-09-08, round P4,
#: on M's ruling of that date**: `AdapterMetadata.limitations` widened from `list[str]` to
#: `list[str | Limitation]` so that §34's "explicit documented exception" can carry
#: MACHINE-READABLE `unsupported_paths` instead of prose a loss classifier would have to guess at.
#: A new optional shape a field ACCEPTS is additive — `VERSIONING.md`'s own row says "A new
#: optional field is a MINOR; a newly required field is a MAJOR, because every existing manifest
#: becomes invalid" — and no existing manifest becomes invalid: every one of the fourteen keeps
#: plain sentences and `manifest.py`'s validators read either form.
#:
#: THE FOURTEEN FILES UNDER `manifests/` MOVE BY EXACTLY ONE LINE EACH, and that is arithmetic
#: rather than a decision: `manifests.py:50` writes this constant into every manifest's envelope
#: as `manifest_schema_version`, so bumping it here makes all fourteen stale by
#: `python -m synapse_cdm.manifests --check`. Their `adapter` blocks — the declarations
#: themselves — are byte-identical, which is what M's ruling means by not regenerating them to
#: convert strings into objects. MIGRATIONS.md's P2 note that this constant "does NOT move:
#: `1.0.0` has never been published" is what made 1.0.0 free to be the first published number
#: rather than a deprecated one; it is still unpublished at 1.1.0, and this round's record says so.
#:
#: **1.1.0 -> 1.2.0, round P5, 2026-09-08.** `Limits` gains `declared_because` — the mirror of
#: `absent_because` — because M's F5.4 ruling requires a bound that IS declared to record where
#: its number came from, whether it is the format's normative maximum or an implementation cap,
#: where it is enforced and which test proves the refusal. MINOR on `VERSIONING.md`'s own row: the
#: field carries a default of `{}`, so a manifest written against 1.1.0 still validates, and no
#: existing field changed shape or meaning. All fourteen manifests move, and this time they move
#: in their `adapter` block as well as their envelope: every one of the fourteen now declares
#: `max_input_bytes`, so every one loses an `absent_because` entry and gains a basis.
#:
#: **1.2.0 -> 2.0.0, audit remediation S10, 2026-09-20.** `AdapterMetadata.binding` (F05) is a
#: newly REQUIRED field with no default, and `VERSIONING.md`'s row is the whole ruling: "a newly
#: required field is a MAJOR, because every existing manifest becomes invalid". Both directions
#: refuse: a 1.2.0 manifest lacks `binding` under the 2.0.0 schema, and a 2.0.0 manifest carries
#: a key the 1.2.0 schema's `additionalProperties: false` does not know. No default was ruled —
#: F05's reason stands, a default is a wire-level claim the author did not make. All fourteen
#: manifests move in their envelope (this constant) and moved already in their `adapter` block
#: (the declaration each adapter now carries).
MANIFEST_SCHEMA_VERSION = "2.0.0"

#: The generated EVIDENCE RECORD's shape, and a SIXTH axis — the last one `VERSIONING.md` carried
#: as owed. `1.0.0` because `schemas/evidence/evidence.schema.json` is the first evidence schema
#: there has ever been and no release has carried one.
#:
#: NOT DERIVED FROM `SCHEMA_VERSION`, AND THE INDEPENDENCE IS THE POINT. An evidence record is a
#: measurement OF a tree: it carries `cdm_version`, `package_version`, `adapter_api_version`,
#: `manifest_version` and `sc_oes_version` as DATA, because the whole value of the record is that
#: a third party can read which versions were in force when the run happened. If the record's own
#: shape were pinned to `SCHEMA_VERSION`, then every CDM minor would move the evidence schema
#: without one field of the record changing, and a consumer's schema check would break on a
#: number that describes somebody else's contract. It moves when the RECORD's fields move, on
#: `VERSIONING.md`'s "Same rule as the manifest".
#:
#: **1.0.0 -> 2.0.0, audit remediation S10, 2026-09-20.** The record gained three REQUIRED fields
#: under F07 — `snapshot`, `evidence_categories`, `maturity_support` — and a second schema file,
#: `schemas/evidence/exercise.schema.json`, joined the axis. A 1.0.0 record no longer validates
#: against the regenerated schema and a 2.0.0 record carries keys a 1.0.0 validator refuses, so
#: the manifest's own rule applies unchanged: a newly required field is a MAJOR. Records are
#: regenerated, never migrated by hand: `python -m synapse_cdm.evidence generate --all --out
#: evidence` writes every one under this number.
EVIDENCE_SCHEMA_VERSION = "2.0.0"


def parse(version: str) -> tuple[int, int, int]:
    """`MAJOR.MINOR.PATCH` as three integers, or `ValueError`.

    Held to `SEMVER_RE` under `fullmatch` BEFORE the split, since 2026-09-19 (audit F01). The
    split-and-`int()` this replaced took "2.1.0\n", " 2.1.0", "01.0.0" and "-1.0.0" as versions
    — `int()` strips whitespace, tolerates a leading zero and reads a sign — so a string the
    wire field refuses was a version the compatibility question answered.
    """
    if not isinstance(version, str) or SEMVER_RE.fullmatch(version) is None:
        raise ValueError(f"not a CDM version: {version!r} is not MAJOR.MINOR.PATCH with no "
                         f"prefix, suffix, sign, leading zero, whitespace or trailing newline")
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


class Verdict(enum.Enum):
    """What the evidence says about one writer-by-reader relationship."""
    SUPPORTED = "SUPPORTED"   #: documents of the writer's shape were accepted by the reader's contract
    REFUSED = "REFUSED"       #: the reader's contract rejects documents of the writer's shape
    UNKNOWN = "UNKNOWN"       #: no frozen contract on one side — nothing has been demonstrated


class Direction(enum.Enum):
    """Which side is older. The question is asymmetric and the answer has to say which way."""
    SAME = "SAME"                    #: same MAJOR.MINOR; a PATCH moves descriptions only
    READER_NEWER = "READER_NEWER"    #: new reader, old writer — the additive direction
    WRITER_NEWER = "WRITER_NEWER"    #: old reader, new writer — where strict readers refuse


class Compatibility(NamedTuple):
    """The answer `assess()` gives, with the direction and the evidence it rests on."""
    written_with: str
    read_by: str
    verdict: Verdict
    direction: Direction
    basis: str    #: where the evidence for this verdict lives, or why there is none
    reason: str   #: one sentence for a CLI or a conformance finding

    def __bool__(self) -> bool:
        return self.verdict is Verdict.SUPPORTED

    def __str__(self) -> str:
        return (f"{self.verdict.value}: written with {self.written_with}, read by "
                f"{self.read_by} ({self.direction.value}) — {self.reason}")


#: The CDM contracts of the current major that have been PUBLISHED and FROZEN — every minor a
#: reader can hold evidence about. `tests/frozen/cdm/MANIFEST.json` carries each one's schemas
#: as the release tag shipped them (tag, commit, sha256), and `tests/test_cdm_version_matrix.py`
#: holds this tuple equal to that manifest's keys: a contract may not be claimed here before it
#: is frozen there, and a frozen one may not be forgotten here. A minor of this major that is
#: not in this tuple is UNKNOWN to `assess()` — never presumed safe by arithmetic.
KNOWN_CONTRACTS: tuple[str, ...] = ("2.0.0", "2.1.0")

_MATRIX = "tests/test_cdm_version_matrix.py"
_FROZEN = "tests/frozen/cdm/MANIFEST.json"


def assess(written_with: str, read_by: str = SCHEMA_VERSION) -> Compatibility:
    """May a reader at `read_by` accept an object written at `written_with`? Answered by
    direction and by evidence, never by major-number arithmetic alone.

    The rules, in the order they apply:

    * either string outside `SEMVER_RE` under `fullmatch` — `ValueError`, from `parse()`;
    * different MAJOR — REFUSED both ways. MIGRATIONS.md's table: a MAJOR removes, renames or
      narrows, and no reader of one major has been shown to accept the other;
    * same MAJOR.MINOR — SUPPORTED, in either direction. A PATCH moves descriptions and error
      wording only, so the two contracts have one shape;
    * READER_NEWER, both contracts in `KNOWN_CONTRACTS` — SUPPORTED. The frozen older
      documents validate under the newer models and schema; the matrix test is the evidence,
      re-run on every suite;
    * WRITER_NEWER, both contracts known — REFUSED. Every published CDM schema carries
      `additionalProperties: false`, so a document carrying a property the older contract does
      not know — populated OR explicitly null — is rejected by it. The old helper promised the
      opposite ("a 1.0.0 reader accepts a 1.2.0 object") and the frozen 2.0.0 schemas refute it;
    * a MINOR of this major that is not in `KNOWN_CONTRACTS`, on either side — UNKNOWN. Nothing
      has been frozen, nothing has been demonstrated, and `compatible()` reads it as False.

    A SUPPORTED verdict is version ELIGIBILITY: documents of that contract's shape have been
    shown to pass. It says nothing about the document in hand, which is validated on its own —
    `conformance.py` does both and reports both. No verdict rewrites `schema_version`, discards
    a field or invents a downgrade; a REFUSED document stays exactly what it is.

    This is about SCHEMA_VERSION only. Asking it about PACKAGE_VERSION is a category error:
    two distributions are not "compatible", one of them is installed.
    """
    w_major, w_minor, _ = parse(written_with)
    r_major, r_minor, _ = parse(read_by)

    if w_major != r_major:
        return Compatibility(
            written_with, read_by, Verdict.REFUSED,
            Direction.WRITER_NEWER if (w_major, w_minor) > (r_major, r_minor)
            else Direction.READER_NEWER,
            basis="different major: MIGRATIONS.md's table makes a MAJOR a removal, rename or "
                  "narrowing, and no reader has been shown to accept the other major",
            reason=f"{written_with} and {read_by} are a major apart; MIGRATIONS.md states what "
                   f"a reader must do about it")
    if w_minor == r_minor:
        return Compatibility(
            written_with, read_by, Verdict.SUPPORTED, Direction.SAME,
            basis="same MAJOR.MINOR: a PATCH moves descriptions and error wording only "
                  "(MIGRATIONS.md, 'What each bump means')",
            reason=f"{written_with} and {read_by} share one contract shape")

    direction = Direction.WRITER_NEWER if w_minor > r_minor else Direction.READER_NEWER
    w_contract, r_contract = f"{w_major}.{w_minor}.0", f"{r_major}.{r_minor}.0"
    unknown = [c for c in (w_contract, r_contract) if c not in KNOWN_CONTRACTS]
    if unknown:
        return Compatibility(
            written_with, read_by, Verdict.UNKNOWN, direction,
            basis=f"no frozen contract for {', '.join(unknown)} in {_FROZEN}; nothing has "
                  f"been demonstrated for this relationship",
            reason=f"{written_with} read by {read_by} is an unpublished minor of this major: "
                   f"not presumed safe")
    if direction is Direction.READER_NEWER:
        return Compatibility(
            written_with, read_by, Verdict.SUPPORTED, direction,
            basis=f"{_MATRIX}: frozen {w_contract} documents of every kind validate under the "
                  f"{r_contract} models and schema",
            reason=f"a {read_by} reader accepts {written_with} documents: the additions since "
                   f"{w_contract} are optional and the frozen matrix shows it")
    return Compatibility(
        written_with, read_by, Verdict.REFUSED, direction,
        basis=f"{_MATRIX}: the frozen {r_contract} schemas carry additionalProperties: false "
              f"and reject the properties {w_contract} introduced, populated or null",
        reason=f"a {read_by} reader refuses {written_with} documents that carry any property "
               f"introduced since {r_contract}; the document is not rewritten or downgraded")


def compatible(written_with: str, read_by: str = SCHEMA_VERSION) -> bool:
    """`assess(written_with, read_by).verdict is Verdict.SUPPORTED`, as a plain bool.

    The name and signature are the ones every caller and document has used since 1.0.0; what
    changed on 2026-09-19 (audit F01) is the answer. It was `major == major`, which said True
    for a 2.0.0 reader handed a 2.1.0 object (the frozen 2.0.0 schema refuses it), for a minor
    nobody has published, and for "2.1.0\n". It is now False for all three: an UNKNOWN verdict
    is not a safe one, and a malformed string is a `ValueError` rather than an answer. A caller
    that needs the direction or the evidence reads `assess()`; this is the yes/no view of it.
    """
    return assess(written_with, read_by).verdict is Verdict.SUPPORTED


#: Semver as it is spelled on the wire — `MAJOR.MINOR.PATCH`, no leading zeroes, no prefix, no
#: suffix — applied with `re.fullmatch` and never `$`, which admits a trailing newline. One
#: pattern since 2026-09-16, where there were three: `manifest.py` had `^\d+\.\d+\.\d+$` under
#: `.match` and `models.CDMBase._semver` split on dots and called `int()`, so "01.0.0" and
#: "1.0.0\n" were a version to an adapter manifest and to `schema_version` while `spec_version`
#: refused them, and `SourceRef.adapter_version` had no shape check at all. This file is the
#: home because it is the leaf of the package's import graph: every module that validates a
#: version already imports it, and it imports nothing of theirs. `oes.py`, which had this
#: pattern, re-exports it under the same name for `oes_registry`.
SEMVER_RE = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")

#: The same grammar as a JSON Schema `pattern`, since 2026-09-19 (audit F04). One string feeds
#: both sides of the contract: `models.py` passes it to `Field(pattern=...)` on
#: `SourceRef.adapter_version` and `CDMBase.schema_version`, so the published schema carries it,
#: and pydantic holds the same fields to it before the `_semver` validators run. Anchored with
#: `^`/`$` here and matched with `fullmatch` above, because `$` means different things in
#: different engines: ECMA-262 (what JSON Schema specifies) and pydantic-core's Rust engine end
#: the input there; Python's `re` also matches before a trailing newline, and the Python
#: `jsonschema` package uses `re.search` — so `"1.2.3\n"` is a version to a vanilla Python
#: schema validator and to nothing else. `schemas.validator_for()` is this package's answer
#: (it reads `$` as ECMA does), and `tests/test_cdm_schema_alignment.py` runs every engine on
#: the same bytes.
SEMVER_PATTERN = f"^{SEMVER_RE.pattern}$"


def is_semver(value: str) -> bool:
    """Does `value` spell a version the way every version field of this package requires?"""
    return SEMVER_RE.fullmatch(value) is not None
