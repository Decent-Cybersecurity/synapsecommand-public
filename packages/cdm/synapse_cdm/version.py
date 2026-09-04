"""Two version numbers, what each one governs, and why they are not one number.

THE DISTINCTION, STATED ONCE
----------------------------
This package carries two semver strings and they answer different questions.

``SCHEMA_VERSION`` is the **wire contract's** version. It is carried in EVERY serialised
object as ``schema_version``, because a consumer that reads an object off a queue has no
other way to know which shape it is holding. It is governed by ``MIGRATIONS.md`` — that
document's table decides what a bump means, its History section records every one, and its
procedure is what a schema change has to walk through.

``PACKAGE_VERSION`` is the **distribution's** version — what ``pip install synapse-cdm==…``
resolves and what ``importlib.metadata.version("synapse-cdm")`` returns. It is ordinary
semver over the Python surface: the importable names, the ``Adapter`` contract, the harness
CLI and its exit codes, the fixture set. It follows the general rule and not MIGRATIONS.md.

WHY THEY MUST BE ALLOWED TO DIVERGE — AND, SINCE 1.1.0, WHY THAT IS NO LONGER AN ARGUMENT
-----------------------------------------------------------------------------------------
**They have diverged, and 1.2.0 widened the gap without anybody arguing about it.**
``PACKAGE_VERSION`` is ``1.5.0`` and ``SCHEMA_VERSION`` is ``1.0.0``, and this paragraph is the
third version of itself that does not have to reason about a hypothetical. Every entry in
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

``SCHEMA_VERSION`` is compared with ``compatible()`` rather than by equality, because an
object written by 1.2.0 is readable by a 1.0.0 consumer and refusing it would be a
self-inflicted outage. ``PACKAGE_VERSION`` needs no such helper: ``pip`` resolves it.
"""
#: The wire contract. Governed by MIGRATIONS.md. Carried in every serialised object.
SCHEMA_VERSION = "1.0.0"

#: The distribution. Governed by ordinary semver over the Python surface; read by
#: `pyproject.toml` as the packaging version, and by `tests/test_cdm_release.py` as the
#: number every release tag has to name. NOT the same fact as SCHEMA_VERSION — see above.
PACKAGE_VERSION = "1.5.0"


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
