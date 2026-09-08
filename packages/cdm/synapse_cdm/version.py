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

    Python package        2.0.0   this file, ``PACKAGE_VERSION``. Semver over the importable
                                  surface, the ``Adapter`` contract, the harness CLI, the
                                  fixture set. What ``pip install synapse-cdm==…`` resolves.
    CDM schema            2.1.0   this file, ``SCHEMA_VERSION``. The WIRE CONTRACT, carried in
                                  every serialised object, governed by ``MIGRATIONS.md``.
                                  (2.0.0 -> 2.1.0 on 2026-09-08, round P3: optional primitives
                                  only. The package did NOT follow it and is still 2.0.0.)
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
    Adapter API           2.0.0   this file, ``ADAPTER_API_VERSION``. The CONTRACT an adapter
                                  class is written against — what ``Adapter`` requires of a
                                  subclass and what it offers it. Frozen by ``ARCHITECTURE.md``
                                  §1 and additive over v1: v2 adds ``metadata``, ``detect``,
                                  ``validate_source`` and ``capabilities`` and renames nothing.
    Manifest schema       1.1.0   this file, ``MANIFEST_SCHEMA_VERSION``. The shape of the
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
``PACKAGE_VERSION`` is ``2.0.0`` and ``SCHEMA_VERSION`` is ``2.1.0``, and this paragraph is the
fourth version of itself that does not have to reason about a hypothetical. (Corrected
2026-09-08, round P3. It read "``SCHEMA_VERSION`` is ``2.0.0``" and "third version" for one day:
the schema took a MINOR for the CDM foundation primitives and the package took nothing, so the
paragraph below — written the day the two became equal — is already describing a state that has
passed. It is kept as written; this is the sentence that overtakes it.)

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
PACKAGE_VERSION = "2.0.0"

#: The SC-OES wire-semantic contract's version, and a THIRD axis. Carried by a producer in
#: `Event.oes.spec_version`; read by nothing in this package as a gate, because an event written
#: against a later specification version must stay transportable. NOT derived from either number
#: above, and not equal to them by anything but coincidence — see the docstring.
SC_OES_VERSION = "0.1.0"

#: The Adapter CONTRACT's version, and a FOURTH axis. `2.0.0` because `ARCHITECTURE.md` §1.2
#: freezes v2 as an ADDITIVE layer over v1: `metadata`, `detect()`, `validate_source()` and
#: `capabilities()` are added, `decode`/`encode` arrive as aliases, and no v1 name is removed or
#: renamed. A subclass written against v1 still imports; what it must now also do is DECLARE its
#: metadata, which is why this is a new major rather than a minor — the requirement is on the
#: subclass, and a third party's adapter that does not declare metadata stops being definable.
#: NOT derived from PACKAGE_VERSION and equal to it only by coincidence, exactly as the two
#: numbers above are: `pip install synapse-cdm==2.0.0` resolves a distribution whose Adapter API
#: is v1, because this constant did not exist at that tag.
ADAPTER_API_VERSION = "2.0.0"

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
MANIFEST_SCHEMA_VERSION = "1.1.0"

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
EVIDENCE_SCHEMA_VERSION = "1.0.0"


def parse(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def compatible(written_with: str, read_by: str = SCHEMA_VERSION) -> bool:
    """May a reader at `read_by` accept an object written at `written_with`?

    Same major, and the reader is not asked to understand a version from the future beyond
    its own minor — a 1.0.0 reader accepts 1.0.x and refuses 2.0.0. A minor from the future
    is ACCEPTED (1.0.0 reads 1.2.0): the additions are optional by definition of MINOR, and
    the alternative is a fleet that stops ingesting the moment one adapter is upgraded.

    This is about SCHEMA_VERSION only. Asking it about PACKAGE_VERSION is a category error:
    two distributions are not "compatible", one of them is installed.
    """
    w_major, _, _ = parse(written_with)
    r_major, _, _ = parse(read_by)
    return w_major == r_major
