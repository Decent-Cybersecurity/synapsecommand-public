# ASTERIX Category 023 / CNS/ATM Ground Station and Service Status Reports fixtures

**Twenty-seven of them: seventeen translatable, ten refusals.** Adapter `cat023` is at Phase 2 —
`adapters/asterix_cat023.py` on the codec in `adapters/cat023_codec.py`, bidirectional, and every
row of the row set in `../../FORMAT_COVERAGE.md` now reads `cat023 1.0.0`. Phase 1 wrote and
reviewed that row set as a specification with no code behind it; this directory is what shipped
against it, **with no row changed**.

```bash
python -m synapse_cdm.harness --adapter cat023
# 34 passed, 0 failed — seventeen payloads, each replayed twice
```

**Thirty-four, not seventeen, and the doubling is the point.** Each fixture ships as
`<name>.cat023` for the octets and `<name>.parsed.json` for exactly what the parser produces,
because `lossless.unrepresented()` has no leaf structure to harvest from bytes: a blocks-only set
would show a green run with the never-drop rule never executed. The binary twin gets `SKIP` on the
lossless check and says so; the parsed twin gets the check at full strength.

The ten refusals live in `refusals/` and are **not** replayed by the harness, because the refusal is
the expected output. `../../../../../tests/test_cdm_asterix_cat023_adapter.py` runs them through
`to_cdm` and asserts the message names what was wrong. **Nine refuse in `parse_block` and one
refuses in translation** — `reporting_period_zero`, whose `GSSP` of 0 is a value the item's own
range excludes rather than a byte pattern that cannot be read — and the test covers both through
one entry point, because a caller does not care which layer said no.

## `cat023` is adapter #14, and the first here that emits TWO Entities from one record

This is the **CAT034 analogue**: the station is the object, `entity_type` is `SENSOR`,
`affiliation` is `UNKNOWN`, there is no `Kinematics` anywhere, and a report-type item drives a
per-type presence matrix. What Part 16 adds is that two of its three report types are about a
**service**, and §4.5.1.2 requires the independence: "Each ground station may provide several
services, and the status of each shall be reported independently in each service status report." So
a type 002 or 003 record emits a station Entity, a service Entity, and one Event carrying both ids
in `related_entities` with the station first.

**That is not a join.** Both ids are pure functions of fields in the same record, and the service's
is the pair `(SAC/SIC, Service Identification)` because §5.2.3's NOTE 1 says the SID is "allocated
by the system" — four bits, unique within a station and meaningless across stations.
`FORMAT_COVERAGE.md` settlement 2 argues it.

The series is tabulated once, in "The adapter ordinals, and the reserved-ordinal rule" near the top
of `../../FORMAT_COVERAGE.md`.

## What each fixture is for

The plan is in `../../FORMAT_COVERAGE.md` under "The fixtures". Five are worth naming here because
they exist to catch a specific way of being wrong:

| Fixture | The mistake it catches |
|---|---|
| `ground_station_status_minimal` | one FSPEC octet and four items in **FRN order**. A parser walking item-number order reads `I023/000` where `I023/010` is — and the real trap is `I023/200`, which sits between `I023/101` and `I023/110` in wire order, three items out of numeric sequence, so the wrong order loses its place **with no length error anywhere** |
| `all_three_service_types` | three records, one block, two different service identifications. One station Entity per record and **two distinct service Entities**, and nothing merged — settlement 7's first refusal made visible |
| `data_driven_report_period` | `RP` = 0 is "Data driven mode", not a period of zero seconds. The AIS sentinel lesson in a new format: `seconds` is `None` and never `0.0` |
| `service_status_unknown` | two paths to `ADVISORY` that the object has to keep apart. `STAT` = 0 is a value the document **defines** as "Unknown"; `STAT` = 6 is a value it does not define at all, and only the second produces an `unresolved_raw` entry |
| `spare_bits_nonzero` | every reachable spare bit set to `1` — `I023/101` octet 2 bits 5/2, `I023/110` bits 8/5, and `I023/120`'s seven spare bits per block. §4.3 is normative, and the CAT034 round found that a set with all-zero spares tests nothing |

**Two fixtures changed shape during Phase 2, and the generator is what caught it.** The plan gave
`service_status_degraded` and `service_status_unknown` an `I023/110` and no `I023/101`, and Table 2
makes **both** mandatory for report type 002. `spec/build_fixtures.py` runs `parse_block` over every
fixture as it writes it, so the mandatory-item gate refused them at build time rather than at review
time. A hand-written byte file would have shipped two records the adapter must reject, in the
translatable set, and the harness would have reported two failures with no indication that the
fixtures were wrong rather than the code.

## Everything here is synthetic, and there are no coordinates to be synthetic about

`SAC = 0x29` is listed with an explicitly empty country cell in the EUROCONTROL allocation tables
pinned at `../cat021/spec/sac_pin.json` and in no other regional table — the evidence transfers to
Part 16 **by citation**, because §5.2.2's NOTE points at the same published list the CAT021 row
does, at the same URL under a different scheme. `SIC` carries no allocation claim. The clock is
injected.

**Part 16 carries no position of any kind** — nine items and not one coordinate — so unlike every
other fixture set here this one has nowhere to put a synthetic one. `I023/200` is an operational
range with no centre, `Entity.position` is `None` on every object, and `Event.geometry` is `None`
permanently rather than pending.

## Editing these

**Edit `spec/build_fixtures.py`, never the octets and never the twins.** A record's FSPEC and its
block's `LEN` are both functions of the contents. The generator also runs `check_layouts()`, which
asserts every encoder emits exactly the octet count §5.2 states — and the one to check hardest is
`I023/101`, whose first part is **two** octets with the `FX` in the second and whose extension is
one. That is the only `2+` shape in any ASTERIX category this repository pins, and a length rule
copied from `I023/100`'s would be off by one on every record.

`spec/` also holds `cat023_pin.json`. **The document itself is not in git and never will be**: it is
EUROCONTROL's, under their own terms, and this edition — unlike Part 9 Edition 1.21 — carries no
copyright notice anywhere, because its back cover is an unfinished template. So there is no stated
permission to rely on, which makes carrying it a worse idea rather than a better one.
