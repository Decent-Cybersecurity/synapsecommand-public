# barentswatch_hais fixtures

**Every file here is synthetic**, written by `spec/build_fixtures.py` from literal documents in that
script. The MMSIs are under **MID 299**, the European block no administration holds, for the reason
`fixtures/ais/README.md` gives against the `999xxxxxx` range (a `99` prefix reads as an aid to
navigation): a ship station is `299xxxxxx` and the one aid to navigation is `99|299|0010`. Names
begin `EX`, every position lies inside CONTRIBUTING.md's Baltic rectangle (56.0 to 58.5 N, 20.0 to
24.5 E), and the day is 2026-10-19 UTC. No value is copied from a real BarentsWatch response, no
real vessel is named, and no receiver is identified.

Edit the script and run `python -I -B spec/build_fixtures.py`; `--check` prints `CURRENT` when the
tree matches it and writes nothing. Never edit a fixture by hand.

## The pairs

Each valid fixture is written twice: `<name>.hais`, the response's octets as the API sends them
(compact UTF-8 JSON, one array), and `<name>.parsed.json`, the same document parsed, which is what
the harness's `lossless` column reads (the column skips on octets). The adapter takes either form,
and `tests/test_cdm_barentswatch_hais_adapter.py` holds the two translations and the two goldens of
every pair equal.

| Fixture | What it exercises |
|---|---|
| `underway_newest_first` | the API's newest-first order reversed into ascending samples; six reports of one ship station, a PLATFORM |
| `nulls_and_sentinels` | null heading / ROT / COG / SOG, the AIS sentinels (102.3 kn, 360 deg, 511, -128, 91 / 181), the 102.2 kn floor, null latitude, zeros as measurements, a newest element with no kinematics |
| `single_point` | a one-sample track of the aid to navigation `992990010`, which the `ais` adapter's MMSI rule types FACILITY |
| `unknown_extra_key` | keys outside the observed twelve (a scalar and a nested object), an element with only the four required keys, a `sat` stream |
| `duplicate_instants_unordered` | unordered input, an identical duplicate pair, a conflicting pair, a `+02:00` offset with sub-millisecond digits |

`malformed/` holds payloads the adapter must refuse (read by the conformance suite's check H and by
the test module): eleven structural cases as `.json` and four octet-level cases as `.hais` (a
duplicate key, `NaN`, a truncated document, octets that are not UTF-8). `golden/` is written by the
harness's `--update-golden` and was read before it was kept.

`spec/barentswatch_hais_pin.json` cites the API documentation the format is read from (by URL,
never carried) and `spec/barentswatch_hais_terms.json` records the publisher's licence statement
behind the adapter's `PUBLIC_GOVERNMENT` class.
