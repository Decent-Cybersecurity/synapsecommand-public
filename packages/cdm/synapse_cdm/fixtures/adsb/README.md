# ADS-B fixtures

**Every one is synthetic.** No real 1090ES traffic, and no ICAO address of a live aircraft, is
in this repository. The fixtures were written as field values and encoded by `adapters/adsb.py`;
the generator's field tables are the reviewable form of what each one says, and this file is the
prose version of the same thing — necessary here for the reason it was necessary for AIS, and
more so: a 28-character hex frame is not readable and a `.adsb` file cannot carry a comment.

## The addresses, and how far the "safe" claim actually goes

The ICAO 24-bit aircraft address has no test range the way the AIS numbering plan has no test
MMSI, and the obvious cheat is worse here than it was there. `FFFFFF` and `000000` are not
neutral placeholders: an all-zero address is invalid, and the top of the space is where ICAO
keeps its own temporary and special-use allocations. A fixture using one would be making a
claim about a real allocation rather than avoiding one.

So every fixture address is in **`0029xx`**, and the reasoning is:

- The ICAO allocation table assigns addresses to states in contiguous blocks, and its **lowest
  block begins at `004000`**. Everything below that is in no administration's range, so an
  address there cannot collide with a real airframe's.
- `0029xx` is structurally an ordinary address — 24 bits, decodes normally, passes the CRC —
  so the fixtures exercise the same code path a real frame does. That is the property MID 299
  bought the AIS fixtures, and it is the one that matters: a fixture that is invalid in a way
  the format notices tests the refusal path instead of the translation.
- `29` echoes the AIS fixtures' MID 299 on purpose, so a reader who has met one set recognises
  the other.

**What this claim rests on, stated plainly because it is weaker than the AIS one.** MID 299 is
documented as unallocated in the ITU numbering plan. Here the evidence is that the allocation
table's lowest state block starts at `004000` — which is true of every published copy of that
table, but this repository pins no retrieved copy of it the way `airtasking/SOURCES.md` pins a
source. If ICAO ever allocates below `004000`, these fixtures must move. That is why
`tests/test_cdm_adsb_adapter.py` asserts the constraint rather than leaving it to this file:
the test names the block, so the assumption is discoverable from a failure instead of from
somebody's memory.

Callsigns are fictional and marked as exercise traffic (`EXRCS01`, `EXHELO2`, `EXMAST1`).
Positions are Baltic-plausible — the Gulf of Riga, west of Saaremaa, Ventspils, and the apron
and taxiways at Riga. Nothing is a real aircraft's real track.

## Why each fixture ships twice

Each `<name>.adsb` has a `<name>.parsed.json` twin holding exactly what the parser produces from
it. The harness cannot run its **lossless** check on a non-JSON fixture — there is no leaf
structure to harvest from bytes — so an ADS-B-only fixture set would show a green run with the
never-drop rule never executed. The twin gives the check something to measure, and
`tests/test_cdm_adsb_adapter.py` asserts both that the twin is what the `.adsb` parses to and
that the two golden files are byte-identical. Hand-maintained, they would drift, and the drift
would be invisible because each would still pass its own golden check.

## Editing or adding one

Edit the **`.parsed.json`**, never the `.adsb`. The twin is the reviewable form — named fields
in the units the standard talks in — and the frame is produced from it:

```python
from synapse_cdm.adapters import adsb
parsed = adsb._parse_frames(open("airborne_position_baro_gulf_of_riga.adsb", "rb").read())
line = adsb._render_frame(parsed["message"], parsed["frame"])
```

The parity field does not need editing and cannot be edited usefully: `_render_frame` recomputes
the CRC over whatever the other 88 bits end up being, which is also why a hand-edited `.adsb`
file is refused rather than mis-decoded. Then re-run the harness with `--update-golden` and read
the diff.

## The ingest fixtures

| Fixture | Type code | What it is there to catch |
|---|---|---|
| `airborne_position_baro_gulf_of_riga` | 11 | The ordinary case: an airborne position with a barometric altitude, which must land in `attributes.baro_altitude_ft` and **not** in `Position.alt_m` — the whole of gap 9. Also the AVR `@` form, whose 48-bit timestamp is a free-running receiver counter and must be parked rather than read as a clock |
| `airborne_position_gnss_height_odd` | 22 | The one altitude in this format that maps, and the one with its **own encoding**: the 12 bits are a plain decimal value in **metres**, no Q bit and no 25-foot step, so 3200 m is literally 3200. The field saturates at 4095 m, which is why this is a climbing regional aircraft rather than a cruise level. Also **odd** CPR parity, and the fixture that caught two real defects — an earlier version read this field with the barometric arithmetic (reporting an altitude up to 8× too high while the round trip stayed byte-exact), and before that dropped the altitude entirely whenever no reference position made a `Position` to hold it |
| `airborne_position_gillham_above_50175` | 11 | The **Q bit clear**: the 100-foot Gillham encoding this adapter deliberately does not decode. The altitude must be absent and the raw twelve bits must survive in `attributes.unresolved_raw` — declining to decode and losing the data are different outcomes |
| `airborne_position_no_position_information` | 0 | The frame that says outright it has no position. Its CPR fields are **zero**, and zero CPR values are the absence of a position and not a position on the equator — so this one stays position-less even with a reference configured, which is the mirror of the rule that a real 0/0 coordinate must survive |
| `airborne_position_permanent_alert` | 11 | Surveillance status 1, the standard's own alert indication → `ALERT` at `CRITICAL`. A temporary alert or an SPI pulse must not do the same |
| `surface_position_riga_taxiway` | 6 | Surface position: the 90-degree CPR span, the non-linear movement bucket table, and a ground track that is a track over the ground and therefore a real `course_deg` |
| `surface_position_stopped_no_track` | 5 | **Movement 1 is "stopped"** — a measurement of stillness, so 0.0 m/s and not an absent speed, the mirror of AIS's stationary life raft. And the track validity bit is CLEAR over a real-looking value: the second absence mechanism, which the byte-exact round trip caught being discarded |
| `identification_light_aircraft` | 4 | A callsign, which has no canonical home (gap 1) and lands under the key the TAK adapter already uses. Carries no position and no time, so `STATUS_CHANGE` and not `TRACK_UPDATE` |
| `identification_point_obstacle` | 2 | Category set C code 3: a point obstacle is a fixed structure, so `FACILITY`. The ONE case where the emitter category refines the entity type — a light aircraft and a heavy are both PLATFORM |
| `airborne_velocity_ground_speed` | 19 ST 1 | Velocity over ground: two signed components into one speed and one course, a vertical rate, and the GNSS-barometric difference that is the bridge between gap 9's two altitudes |
| `airborne_velocity_airspeed_and_heading` | 19 ST 3 | The subtype that costs the CDM two fields. An airspeed is not a ground speed, so `speed_mps` stays null (gap 10); a heading is not a course, so it parks (gap 7). The vertical rate still travels, because it is the same measurement on both subtypes |
| `airborne_velocity_all_unavailable` | 19 ST 1 | **Every zero sentinel in the velocity frame at once.** Not one may reach the output as a measurement, and `kinematics` must be absent entirely rather than a zero vector |
| `aircraft_status_unlawful_interference` | 28 ST 1 | Emergency state 5 → `ALERT` at `CRITICAL`, and the Mode A squawk 7500, decoded from three non-adjacent bits per digit. Parked and deliberately **not** a `SourceId`: a squawk identifies a flight, not an airframe |
| `operational_status_magnetic_heading` | 31 ST 0 | The HRD bit: this airframe's headings are referenced to **magnetic** north. It is in a different frame from the heading it qualifies, which is the cross-frame join gap 7 inherits |
| `tisb_fine_format_relayed_track` | 11, DF18 CF 2 | Fine-format TIS-B: a ground station's rebroadcast of a surveillance track, so `position_source` must be `ESTIMATED` and never `GNSS`. Calling it GNSS would promise a fix that survives jamming |
| `nonicao_anonymous_address` | 11, DF18 CF 1 | The address is **not** an ICAO allocation, so the source id system must be `ADSB_NONICAO`. Filing it under `ICAO24` would let fusion join this contact to a real airframe sharing the number |

## `local/` — the same frames, decoded against a reference position

`local/` holds the CDM output for the referenced path: the same `.adsb` fixtures translated by
an adapter constructed with `reference_position=(56.9236, 23.9711)`, a receiver at Riga. Only
the eight position-bearing fixtures appear there, because those are the only ones a reference
changes — and `tests/test_cdm_adsb_adapter.py` asserts BOTH halves of that: the eight against
these goldens, and the other eight as byte-identical to their reference-free output. A reference
position must change positions and nothing else.

**Not run by the harness**, and not because of a directory-skipping trick: the harness constructs
the adapter itself and has no adapter-specific flags to pass a reference through, which is
exactly the property that makes it usable on an adapter it has never seen. So the harness gates
the reference-free path — the default, and the safe one — and the test suite gates the other.

## The egress fixtures

`egress/` holds CDM objects and the frames each one becomes. **Not** run by the harness either:
`run()` replays every fixture through `to_cdm()`, so a CDM payload beside the ingest fixtures
would be fed to the frame parser and fail. They live in a subdirectory because the harness
iterates files and skips directories, so pointing it at `fixtures/adsb` still works.

| Fixture | What it is there to catch |
|---|---|
| `track_air_patrol_three_samples` | A `Track` becomes one position frame per sample, in the track's own order, at **type code 22** because the samples state `alt_m` and that is a GNSS height — so the altitudes are 2750 / 3050 / 3350 m, inside the 12-bit metre field rather than at a cruise level it cannot hold. The CPR parity is always EVEN: alternating it would invite a receiver to globally pair two samples taken minutes apart and produce a position the aircraft was never at |
| `entity_fused_elsewhere` | An Entity that never came from ADS-B, holding a position AND a velocity — which **no single 1090ES frame can carry**, so it emits two: a type code 18 position frame and a type code 19 velocity frame. Type code 18 rather than 9 or 11 because the type code encodes a navigation integrity category, and a default of 9 would assert a containment radius nobody measured |
| `entity_identification_no_position` | The identification path from a hand-authored object: a callsign and an emitter category reaching the wire with no position at all, under a type code the object itself states |

Goldens are the emitted frames under the frozen clock (`times.FROZEN_NOW`) — which for this
format changes nothing, since no frame has a time field. That is itself worth knowing: the
clock is load-bearing for `observed_at` and `received_at` in the CDM output and reaches the wire
nowhere.
