# AIS fixtures

**Every one is synthetic.** No real AIS traffic, and no MMSI of a live vessel, is in this
repository. The fixtures were written as field values and encoded by `adapters/ais.py`; the
generator's field tables are the reviewable form of what each one says, and this file is the
prose version of the same thing — necessary here in a way it was not for the CoT fixtures,
because an armoured AIS payload is not readable and a `.nmea` file cannot carry a comment.

## The MMSIs, and why not `999xxxxxx`

The obvious choice for synthetic AIS is the `999xxxxxx` test range, and it is the wrong one
here for a reason worth writing down: **`99` is the ITU prefix for an aid to navigation.** An
MMSI of `999123456` reads, by the standard's own numbering plan, as the AtoN `99|912|3456` —
so a vessel fixture using one would contradict itself, and `_mmsi_category()` would classify
it as a buoy. A fixture that lies about its own subject is worse than no fixture.

So the MMSIs use **MID 299**, which is in the European `2xx` block and is not allocated to any
administration. That keeps the numbering-plan structure meaningful — a coast station really is
`00|299|0001` and an aid to navigation really is `99|299|0010` — while every number is plainly
fictional. `970299001` is an AIS-SART under the `970` prefix, for the same reason.

Positions are Baltic-plausible: the Gulf of Riga, Ventspils, Liepāja and the water west of
them. Nothing is a real vessel's real track.

## Why each fixture ships twice

Each `<name>.nmea` has a `<name>.parsed.json` twin holding exactly what the parser produces
from it. The harness cannot run its **lossless** check on a non-JSON fixture — there is no
leaf structure to harvest from bytes — so an AIS-only fixture set would show a green run with
the never-drop rule never executed. The twin gives the check something to measure, and
`tests/test_cdm_ais_adapter.py` asserts both that the twin is what the `.nmea` parses to and
that the two golden files are byte-identical. Hand-maintained, they would drift, and the drift
would be invisible because each would still pass its own golden check.

## Editing or adding one

Edit the **`.parsed.json`**, never the `.nmea`. The twin is the reviewable form — named fields
in the units the standard talks in — and the sentences are produced from it:

```python
from synapse_cdm.adapters import ais
parsed = ais._parse_nmea(open("class_a_underway_gulf_of_riga.nmea", "rb").read())
lines = ais._render_sentences(parsed["message"], parsed["sentences"][0])
```

Then re-run the harness with `--update-golden` and read the diff. A TAG block, if the fixture
has one, is prepended by hand: it is the receiver's annotation and the emitter does not write
one, which is the same reason it does not survive a round trip.

## The ingest fixtures

| Fixture | Type | What it is there to catch |
|---|---|---|
| `class_a_underway_gulf_of_riga` | 1 | The fully-populated ordinary case: a cargo vessel under way, every field a routine report carries, plus an NMEA TAG block so `received_at` is read from the feed rather than the clock — and `observed_at` reconciled from a second-of-minute against it |
| `class_a_sentinels_no_position` | 3 | **Every sentinel at once.** Latitude 91, longitude 181, speed 102.3, course 360, heading 511, rate of turn −128, second 63. All must become absent CDM fields; not one may reach the output as a number. Also the case where `utc_second` 63 makes `position_source` ESTIMATED rather than GNSS |
| `static_voyage_two_fragments` | 5 | Multi-fragment reassembly, and the static/voyage block: name, call sign, IMO number as a *second* source id, dimensions, destination, ETA as four numbers rather than a fabricated timestamp — and **draught 0.0**, the one sentinel that is also a plausible reading. No position and no time field at all, so `observed_at` falls back to receipt and says so |
| `class_b_own_station_ventspils` | 18 | Class B, and an **AIVDO** talker — the receiver's own station. Deliberately NOT read as an affiliation. Also a real report carrying one sentinel among live values (heading 511, which Class B units routinely omit) |
| `class_b_extended_named` | 19 | Class B extended: the same position fields plus name, ship type and dimensions in one message |
| `aid_to_navigation_virtual` | 21 | A **virtual** aid — `OVERLAY_OBJECT`, not FACILITY, because nothing physical floats there. Also the name extension, which exists because the base name field is 20 characters, and EPFD 7 (surveyed) → MANUAL |
| `aid_to_navigation_off_position` | 21 | A real light buoy reporting itself **off station**. Severity stays INFO: an off-position flag is a station condition, not a distress transmission, and that is where the severity line is drawn |
| `base_station_liepaja` | 4 | The one message type in scope that states a full UTC date and time. Used directly, with nothing reconciled — and the observed time is five minutes before the receipt time, which a reconciliation would have destroyed |
| `sart_active_distress` | 1 | Navigational status 14 → `ALERT` at `CRITICAL`. Also the mirror of the sentinel fixture: speed **0.0** and course **0.0** are real measurements here — a life raft, stationary, and 0 is not an absence |
| `equator_zero_meridian` | 1 | Latitude 0, longitude 0 is a real position in the Gulf of Guinea and is translated as one. The same rule the CoT fixture of the same name states, and the mirror of the sentinel rule: nulling a real zero is the same defect as forwarding a sentinel |

## The egress fixtures

`egress/` holds CDM objects and the AIVDM each one becomes. **Not** run by the harness:
`run()` replays every fixture through `to_cdm()`, so a CDM payload placed beside the ingest
fixtures would be fed to the NMEA parser and fail. They live in a subdirectory because the
harness iterates files and skips directories, so pointing it at `fixtures/ais` still works.

They are exercised by `tests/test_cdm_ais_adapter.py`, which is where the round-trip check for
this adapter has to live anyway: the harness's `roundtrip` column reports SKIP for an adapter
that emits something it cannot parse structurally.

| Fixture | What it is there to catch |
|---|---|
| `track_patrol_three_samples` | A `Track` becomes one position report per sample, in the track's own order. What a Track does NOT carry — speed, course, the date — goes out as the standard's not-available values and **never as zeros** |
| `entity_fused_elsewhere` | An Entity that never came from AIS: no parked source fields, so every unmapped bit comes from the not-available table. It still carries an MMSI, because an AIS message with no MMSI addresses nobody |
| `entity_static_voyage_no_position` | The type 5 egress path from a hand-authored object rather than from a re-ingest: name, call sign, destination, dimensions, draught, ETA and an IMO number taken from `source_ids` all have to reach the wire, across two fragments |

Goldens are the emitted sentences under the frozen clock (`times.FROZEN_NOW`), so the fields a
CDM object does not state — which for AIS means the minute and the date — are stable.
