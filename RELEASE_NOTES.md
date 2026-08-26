# synapse-cdm 1.1.0

Two ASTERIX adapters, a roster you can ask for, and the first release of this distribution that
nobody uploaded by hand.

**Package version 1.1.0 · CDM `schema_version` 1.0.0.** The two numbers have parted for the first
time, which is what two numbers are for: every change in this release added a surface and touched
no field of the wire contract. `synapse_cdm/version.py` argues the distinction and, as of this
release, no longer has to do it from a hypothetical.

Everything below is read off the tree at this tag rather than written from memory — condition 4 of
the release procedure in `packages/cdm/synapse_cdm/MIGRATIONS.md`. The commands that produced each
number are named beside it.

For what 1.0.0 was and how it reached PyPI, see
[the 1.0.0 release](https://github.com/Decent-Cybersecurity/synapsecommand-public/releases/tag/v1.0.0)
and `PUBLICATION.md` ledger entry 5. This document does not restate them.

## Twelve adapters, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --json`, run over the roster:

| Adapter | Direction | Fixture verdicts |
|---|---|---|
| `adsb` | bidirectional | 32 |
| `ais` | bidirectional | 22 |
| `cat021` | bidirectional | 40 |
| **`cat023`** | bidirectional | **34** |
| `cat034` | bidirectional | 34 |
| `cat048` | bidirectional | 82 |
| **`cat062`** | bidirectional | **56** |
| `gmti` | bidirectional | 32 |
| `legion` | ingest | 6 |
| `pntmap` | ingest | 4 |
| `stanag4676` | bidirectional | 34 |
| `tak` | bidirectional | 12 |

**388 fixture verdicts, 0 failed**, against the published schemas. 1.0.0 shipped ten adapters and
298 verdicts; the two new ones are the difference.

### The two new adapters

- **`cat062` — ASTERIX Category 062, SDPS track messages, bidirectional.** 27 data items, six
  compound items, a six-extent FX chain, and the Reserved Expansion Field decoded in full. The
  byte-for-byte round trip holds on all 28 fixtures. CAT062 carries **fused** output from a
  multi-sensor tracker, and the adapter translates it and fuses nothing of its own — the per-sensor
  ages, amalgamation and coasting flags and contributing-sensor lists are the upstream system's
  statements and are carried or parked as such.
- **`cat023` — ASTERIX Category 023, CNS/ATM ground station and service status, bidirectional.**
  Nine data items and a three-column presence matrix. The byte-for-byte round trip holds on all 17
  fixtures. It is the first adapter here that emits **two `Entity` objects from one record**: report
  types 002 and 003 describe a service rather than the station, and §4.5.1.2 requires the two to be
  independent, so a service is keyed on `(SAC/SIC, Service Identification)`. Both ids ride on one
  `Event`; both are pure functions of fields in the same record, so it is not a join.

Neither adapter added, removed or retyped a field. `MIGRATIONS.md`'s "Adapters that landed with no
schema change" section now holds eleven entries — eleven of the twelve, `pntmap` having arrived with
the schema itself.

## The roster is now discoverable

Before this release the set of names `--adapter` accepts was reachable only by getting something
wrong: a `LookupError` from a bad name, or argparse's usage line, which names the flag and not one
value it takes.

```bash
python -m synapse_cdm.harness --list-adapters          # name, version, direction, fixtures, system
python -m synapse_cdm.harness --list-adapters --json   # the same set, machine-readable
```

```python
from synapse_cdm.adapter import roster
roster()          # {name: Adapter subclass}, the single source both the listing and the refusal read
```

`adapter.roster()` is one function rather than two `sorted(REGISTRY)` calls, because two
independent derivations of one fact drift the moment either grows a filter. The listing and
`load_adapter`'s refusal read the same function, and a test requires their two rendered outputs to
name the same set.

## Six JSON Schemas, generated on demand

```bash
python -m synapse_cdm.schemas --out ./schemas    # cdm_object, entity, event, plan_object, track,
                                                 # payload_gnss_interference
```

Identifiers are `urn:synapsecommand:cdm:1.0.0:<name>` — the `schema_version`, not the package
version. The wheel deliberately carries no copy of them: a third copy of a generated artefact is a
third thing that can go stale.

## How this release was published

**By `.github/workflows/publish.yml`, over OIDC, with no credential involved.** PyPI mints nothing
long-lived for this repository: GitHub issues a short-lived token naming this repository, this
workflow file and the `pypi` environment, and PyPI trades it for an upload good for one run. There
is no API token in the workflow, in this repository's secrets, or anywhere it could be copied from.

The upload waited on a required reviewer on the `pypi` environment. A PyPI upload cannot be undone —
a yank hides a release but never frees its filename — so it is the one irreversible step in a
release and the one that gets a human in front of it.

**The artefacts uploaded are the artefacts the gates passed.** Not an equivalent rebuild: the
workflow's `gates/wheel_install.py --mutation-check --export-dist dist` runs 13 checks against a
wheel it builds, installs it into a clean virtualenv with no part of the repository on the path,
replays all twelve adapters from the packaged fixtures, then hands those exact files to the publish
job. This matters because two builds of one tree are **not** the same bytes — the payloads are
identical but the build-generated metadata carries timestamps at a two-second resolution — so
building twice and gating one of them checks a file nobody installs.

`PUBLICATION.md` ledger entry 6 records what had to be configured on pypi.org for any of this to
work, and what remains open.

## Artefacts

An sdist and a wheel, built once by the workflow, gated as that build, and uploaded as those same
files. Their **SHA-256 digests are recorded in `PUBLICATION.md` ledger entry 6** together with the
workflow run that produced them, and they are repeated at the foot of this release — the same place
entry 5 records 1.0.0's.

They are deliberately not committed to `RELEASE_NOTES.md` in the repository. A digest is a property
of one build rather than of the tree: two builds of one tree have identical payloads but differ in
their generated metadata, so a digest written here before the tag would not be the digest of the
file PyPI serves, and one written after the tag could never be inside the tree the tag names.
Everything else in this document is readable off that tree, which is what condition 4 asks for.

```bash
pip install synapse-cdm==1.1.0
python -m synapse_cdm.harness --list-adapters
```
