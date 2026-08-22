"""The schema version, and what a change to it means.

Semver, carried in EVERY serialised object as `schema_version`, because a consumer that
reads an object off a queue has no other way to know which shape it is holding. The full
policy and the changelog live in synapse_cdm/MIGRATIONS.md; the short form:

    MAJOR  a field is removed or renamed, a type narrows, an enum member is removed, or an
           optional field becomes required. Consumers break. Requires a migration note.
    MINOR  a field is added optional, an enum member is added, a payload model is registered.
           Old readers keep working; old data keeps validating.
    PATCH  documentation, description text, validation message wording. No shape change.

`SCHEMA_VERSION` is compared with `compatible()` rather than by equality, because an object
written by 1.2.0 is readable by a 1.0.0 consumer and refusing it would be a self-inflicted
outage.
"""
SCHEMA_VERSION = "1.0.0"


def parse(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(part) for part in version.split("."))
    return major, minor, patch


def compatible(written_with: str, read_by: str = SCHEMA_VERSION) -> bool:
    """May a reader at `read_by` accept an object written at `written_with`?

    Same major, and the reader is not asked to understand a version from the future beyond
    its own minor — a 1.0.0 reader accepts 1.0.x and refuses 2.0.0. A minor from the future
    is ACCEPTED (1.0.0 reads 1.2.0): the additions are optional by definition of MINOR, and
    the alternative is a fleet that stops ingesting the moment one adapter is upgraded.
    """
    w_major, _, _ = parse(written_with)
    r_major, _, _ = parse(read_by)
    return w_major == r_major
