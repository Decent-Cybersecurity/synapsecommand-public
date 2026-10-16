# NEXRAD Level II fixtures

**Every one is synthetic.** No volume from the NOAA archive, the Unidata buckets or any reader's
test data — not a file, not a record, not a byte — is in this repository, and no real radar site
is named. Every file here is written by `spec/build_fixtures.py`, an encoder written from the two
ICDs' tables, from literals in that script; edit the script and run it, never an `.ar2v` or a
twin. `python -I -B spec/build_fixtures.py --check` rebuilds the set in memory and prints
`CURRENT` when the tree matches it.

These are the fixtures of `nexrad2` (#25 in the ordinal table, `adapters/nexrad2.py`): one
NEXRAD Level II (Archive II) volume file per payload. The format is ICD 2620010J (Archive
II/User) for the file and ICD 2620002Y (RDA/RPG) for every message, both Build 23.0, pinned by
SHA-256 in `spec/nexrad2_pin.json` and not carried here.

## Why each fixture ships twice

`<name>.ar2v` is the volume as the archive stores it: the 24-octet volume header, then LDM
records, each a signed control word and one bzip2 stream. `<name>.parsed.json` is its twin: the
octets as `wire_hex`, then every field the volume states, raw, under `volume_header`, `site`,
`records` and `sweeps`, and every moment's gate codes as runs of `[code, count]` under `gates`.
The builder writes the twin from the literals it encoded, never by decoding the octets, so the
twin is the decode's expectation; `tests/test_cdm_nexrad2_adapter.py` holds the adapter's decode
of each `.ar2v` to its twin, the twin's own translation to the octets', and the two goldens of
each pair to each other.

## The identifiers and places

The radar sites are **`ZZZZ`** and **`XZZA`**, the synthetic radar-site block of `CONTRIBUTING.md`
("Identifiers and places in observation fixtures"). `ZZZZ` stands at 57.25 N, 22.5 E, 120 m
above mean sea level with a 30 m tower; `XZZA` at 56.75 N, 21.25 E, 5 m below mean sea level with
a 25 m tower — both inside the Baltic rectangle (56.0–58.5 N, 20.0–24.5 E). The day is
2026-04-29 (Modified Julian Date 20573, 1970-01-01 being day 1) and every volume starts at
06:10:00.000. The constants (calibration, transmitter power, noise, Nyquist velocity, VCP 212)
and each moment's gate count, word size, scale and offset are Table XVII-I's and XVII-E to -H's
typical values, chosen so that every Real*4 is exact in single precision except PHI's typical
scale, 2.8361.

Every radial carries all seven moments at their Table XVII-I gate counts, because the adapter
holds Table XVII-A's Radial Length range (9,360 to 14,296 octets) as a rule: a radial of every
moment is 12,440 octets.

## The set

| Fixture | What it exercises |
|---|---|
| `all_moments_one_elevation` | the design record's in-range shape: one elevation of two radials, beginning (3) then end (4) of the volume, every moment with one gate below threshold (0), one range folded (1) and a constant |
| `two_elevations_two_records` | two elevations in two LDM records; an RDA status message (type 2) between two radials; the second record's control word written negative (2620010J 7.3.4: its absolute value is the size); another unambiguous range and Nyquist velocity in elevation 2 |
| `sails_repeated_lowest_angle` | SAILS: elevation 3 rescans elevation 1's 0.5 degrees, so three elevation numbers, three sweeps, two of them at one angle; site `XZZA`, archive version 07, extension 002 |
| `coded_gates_and_bad_radial` | below-threshold and range-folded counts that differ per radial and moment; CFP's own codes 0 to 7; a bad-data radial (status 0x81); spot blanking that varies; a VEL scale that changes between radials; an elevation angle that differs per radial |
| `one_sweep_across_two_records` | one sweep of three radials, two in record 1 and one in record 2 |
