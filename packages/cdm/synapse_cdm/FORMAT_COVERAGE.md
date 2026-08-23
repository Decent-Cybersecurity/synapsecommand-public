# Format coverage — does the CDM actually carry what these formats need?

The brief asks the model to "map cleanly to Cursor-on-Target, STANAG 4676 track structures and
GeoJSON". This file is that check, done field by field rather than asserted — and it has since
grown the row sets of the formats that actually landed — AIS and ADS-B among them. It is also a
working document for whoever writes the next adapter: the mapping column is the adapter's
specification.

`tests/test_cdm_format_coverage.py` resolves every path in the **CDM field** column against the
actual Pydantic models and fails the build on one that does not exist. That is the only reason
this table can be trusted six months from now — a renamed field breaks the test, not just the
prose.

Paths use `[]` for a list element, e.g. `Track.samples[].observed_at`.

## The status column

`Status` says **who implements the row**, not whether the mapping is believed to be right. The
distinction matters: an unimplemented row is a specification, and a specification nobody has
run is a guess with a table around it.

| Status | Means |
|---|---|
| `tak 1.0.0` | implemented by `adapters/tak.py`, with a fixture and a golden file |
| `tak 1.0.0 · parked` | implemented, but the value lands in `attributes` because of a named gap below |
| `tak 1.0.0 · egress` | implemented in the `from_cdm()` direction |
| `ais 1.0.0` | implemented by `adapters/ais.py`, with a fixture and a golden file |
| `ais 1.0.0 · parked` | implemented, but the value lands in `attributes` because of a named gap below |
| `ais 1.0.0 · egress` | implemented in the `from_cdm()` direction |
| `legion 1.0.0` | implemented by `adapters/legion.py`, with a fixture and a golden file |
| `legion 1.0.0 · parked` | implemented, but the value lands in `attributes` because of a named gap below |
| `adsb 1.0.0` | implemented by `adapters/adsb.py`, with a fixture and a golden file |
| `adsb 1.0.0 · parked` | implemented, but the value lands in `attributes` because of a named gap below |
| `adsb 1.0.0 · egress` | implemented in the `from_cdm()` direction |
| `cat021 1.0.0` | implemented by `adapters/asterix_cat021.py`, with a fixture and a golden file |
| `cat021 1.0.0 · parked` | implemented, but the value lands in `attributes` because of a named gap below |
| `cat021 1.0.0 · egress` | implemented in the `from_cdm()` direction |
| `nits 1.0.0` | implemented by `adapters/stanag4676.py`, with a fixture twin and a golden file |
| `nits 1.0.0 · parked` | implemented, but the value lands in `attributes` because of a named gap below |
| `nits 1.0.0 · egress` | implemented in the `from_cdm()` direction |
| `models` | provided by the models themselves; no adapter code is involved |
| `not yet` | no adapter implements this row. The mapping is a specification, not a claim |

`legion 1.0.0` and `legion 1.0.0 · parked` joined this list when adapter #5 landed. Until it
did, every Legion row said `not yet` — the row set was written and reviewed as a specification
first, and the status column is what recorded the difference.

**The STANAG 4676 row set went through that state too**, and `adapters/stanag4676.py` has now
landed, so `test_the_nits_row_set_claims_its_adapter` is the inverted form: it fails if a row
still says `not yet` while the code implements it.

## Cursor-on-Target (TAK) — ingest and egress

Implemented by `adapters/tak.py` (bidirectional). Ingest translates a CoT **atom** into an
`Entity` + an `Event`; egress turns a `PlanObject` into a `u-d-f` drawing and an `Entity` back
into an atom. A drawing arriving on *ingest* is deliberately not special-cased — see that
module's docstring for why.

| CoT | CDM field | Status | Notes |
|---|---|---|---|
| `event/@uid` | `Entity.source_ids[].external_id` | `tak 1.0.0` | system `TAK`; the UID is what TAK dedupes on |
| `event/@type` | `Entity.affiliation` | `tak 1.0.0` | via `symbology.affiliation_from_cot`; original string parked at `attributes.cot_type` |
| `event/@type` | `Entity.entity_type` | `tak 1.0.0` | battle-dimension letter (`G`/`A`/`S`) → UNIT/PLATFORM/…; `G` + function `I` → FACILITY, because calling a bridge a UNIT is a false statement and CoT says which |
| `event/@time` | `Event.observed_at` | `tak 1.0.0` | re-rendered to fixed milliseconds — a declared transform |
| `event/@start` | `Entity.valid_from` | `tak 1.0.0` | absent in the wild; falls back to `@time` and RECORDS the fallback at `attributes.valid_from_basis` |
| `event/@stale` | `Entity.valid_to` | `tak 1.0.0` | CoT staleness IS an interval end — maps exactly |
| `event/@how` | `Position.position_source` | `tak 1.0.0` | `m-g` machine/GPS → GNSS, `h-e` human entered → MANUAL; an unrecognised `how` → ESTIMATED, which understates rather than overstates the fix |
| `point/@lat` | `Position.lat` | `tak 1.0.0` | `0.0` is a real coordinate, not a "no position" sentinel |
| `point/@lon` | `Position.lon` | `tak 1.0.0` | absent `@lat`/`@lon` → `position: None`, never (0, 0) |
| `point/@hae` | `Position.alt_m` | `tak 1.0.0` | both WGS84 HAE metres — no conversion. CoT's `9999999` sentinel → null |
| `point/@ce` | `Position.accuracy_m` | `tak 1.0.0` | circular error, metres. `9999999` → null |
| `point/@le` | `Entity.attributes` | `tak 1.0.0 · parked` | **gap 6** — no canonical linear (vertical) error field; parked at `attributes.vertical_error_m` |
| `detail/track/@speed` | `Kinematics.speed_mps` | `tak 1.0.0` | CoT speed is m/s — no conversion |
| `detail/track/@course` | `Kinematics.course_deg` | `tak 1.0.0` | degrees true; CoT's `360.0` is reduced to `0.0`, the same bearing and the only one the field admits |
| `detail/contact/@callsign` | `Entity.attributes` | `tak 1.0.0 · parked` | **gap 1** — no canonical name field; parked at `attributes.callsign` |
| `detail/remarks` | `Entity.attributes` | `tak 1.0.0` | free text, no canonical home by design |
| `detail/__group/@name` | `Entity.attributes` | `tak 1.0.0` | colour-based team, not an affiliation |
| drawing `u-d-f` shapes | `PlanObject.geometry` | `tak 1.0.0 · egress` | one `<link point="lat,lon,hae"/>` per vertex — note CoT's lat,lon order is the reverse of GeoJSON's |
| drawing stroke/fill | `PlanObject.style` | `tak 1.0.0 · egress` | hints only — style may never carry meaning. Unmapped style keys ride on `<synapse_style/>` rather than being dropped |
| drawing label | `PlanObject.label` | `tak 1.0.0 · egress` | `<contact callsign="…"/>`; an unlabelled object emits no element at all |
| `event/@stale` (egress) | `PlanObject.expires_at` | `tak 1.0.0 · egress` | omitted rather than emptied when there is no expiry |

### What the TAK adapter fills that CoT does not state

Found by building it. Each of these is a CDM field with no CoT source, so it is derived or
declared — and each one says so in the object itself rather than leaving a consumer to guess.

| CoT | CDM field | Status | Notes |
|---|---|---|---|
| *(derived)* | `Entity.symbol` | `tak 1.0.0` | CoT states a type, not a 2525D SIDC. Derived from affiliation via `symbology.sidc_from_affiliation`, and `attributes.symbol_basis` says so |
| `event/@uid` + `@time` | `Event.event_id` | `tak 1.0.0` | keyed on BOTH: a CoT uid identifies the object and repeats on every report, so uid alone would collapse a thousand reports into one event |
| *(none — CoT has no urgency field)* | `Event.severity` | `tak 1.0.0` | `INFO`, with `payload.severity_basis` recording that this is the format's silence and not a misread severity |
| *(none)* | `Event.event_type` | `tak 1.0.0` | `TRACK_UPDATE`. `DETECTION` would claim a sensor found something new, which one message cannot establish |
| everything unmapped | `Entity.attributes` | `tak 1.0.0` | `attributes.source_extras`, structure intact — `@version`, `contact/@endpoint`, `__group/@role`, `status/@battery` and anything a future CoT extension adds |
| `PlanObject.object_id` (egress) | `PlanObject.object_id` | `tak 1.0.0 · egress` | on `<synapse_plan/>`: the uid carries the TAK identifier, so without this a consumer holding the drawing cannot get back to the CDM object |

## AIS (NMEA 0183 AIVDM/AIVDO) — ingest and egress

Implemented by `adapters/ais.py` (bidirectional). Ingest translates one AIS **message** —
delivered as one or more `!AIVDM`/`!AIVDO` sentences — into an `Entity` + an `Event`; egress
turns an `Entity` or a `Track` back into sentences. The paths in the left column are dotted
paths into the **parsed** form the adapter's own decoder produces (`_parse_nmea()`), which is
what each `.parsed.json` fixture holds and what the never-drop check is measured against.

MMSI is the source id, on every message type, in every direction. It is the only identifier
AIS carries that is stable across reports, and everything else a message states about identity
(the name, the call sign, the IMO number) arrives in a *different* message than the position
does — see the type 24 note under "deliberately out of scope" for why that split is a design
question rather than a coding one.

### The sentence envelope

Present on every payload regardless of message type. Nothing here describes the world, so
nothing here is a canonical field: the envelope describes the *radio* and is parked whole, and
egress rebuilds it from the parked copy.

| AIS | CDM field | Status | Notes |
|---|---|---|---|
| `sentences[].talker` | `Entity.attributes` | `ais 1.0.0` | `AIVDM` (another station) or `AIVDO` (the receiver's own station). Parked at `attributes.ais_talker`, and deliberately NOT read as an affiliation — see the declines table |
| `sentences[].channel` | `Entity.attributes` | `ais 1.0.0` | VHF channel A/B; a link fact, parked at `attributes.source_extras` |
| `sentences[].payload` | `Entity.attributes` | `ais 1.0.0` | the armoured 6-bit payload, verbatim. Parked because it is the evidence an auditor asks for: every decoded field below is a claim ABOUT these characters |
| `sentences[].fragment_count`, `.fragment_number`, `.sequential_id`, `.fill_bits`, `.checksum` | `Entity.attributes` | `ais 1.0.0` | reassembly bookkeeping, parked; egress recomputes the checksum rather than trusting the parked one |
| TAG block `c:` | `Event.received_at` | `ais 1.0.0` | NMEA 0183 v4.10 TAG block UNIX timestamp — the receiver's own delivery instant. Absent, `received_at` comes from the injected clock and the basis says so |
| TAG block `s:`, `g:`, … | `Event.payload` | `ais 1.0.0` | any other TAG parameter, parked with its own key |

### Common to every message type in scope

| AIS | CDM field | Status | Notes |
|---|---|---|---|
| `message.type` | `Event.event_type` | `ais 1.0.0` | position-bearing types → `TRACK_UPDATE`; type 5 → `STATUS_CHANGE`, because calling a static-data broadcast a track update would claim a position it does not carry |
| `message.type` | `Entity.entity_type` | `ais 1.0.0` | 1/2/3/5/18/19 → PLATFORM · 4 → FACILITY · 21 → FACILITY, or OVERLAY_OBJECT when the virtual-aid flag is set. Raw type parked at `attributes.ais_message_type` |
| `message.mmsi` | `Entity.source_ids[].external_id` | `ais 1.0.0` | system `AIS`. The id `entity_id` is derived from, on every type |
| `message.mmsi` | `Entity.attributes` | `ais 1.0.0` | the MMSI's own structure — `attributes.mmsi_category` (ship, coast station, AtoN, SAR aircraft, SART/MOB/EPIRB, craft associated with a parent ship) and `attributes.mmsi_mid`, the three MID digits. Read from the ITU numbering plan, not from a country table |
| `message.repeat_indicator` | `Entity.attributes` | `ais 1.0.0` | how many times a repeater has relayed this; parked |
| `message.lat` | `Position.lat` | `ais 1.0.0` | 1/10000 min → decimal degrees, a declared transform. **91 is the not-available sentinel and becomes an ABSENT position, never a latitude of 91** |
| `message.lon` | `Position.lon` | `ais 1.0.0` | 1/10000 min → decimal degrees. **181 is the not-available sentinel.** `0.0` is a real coordinate and is not treated as absence — the same rule the CoT rows state |
| `message.position_accuracy` | `Entity.attributes` | `ais 1.0.0 · parked` | a one-bit flag: high (DGNSS, better than 10 m) or low. Parked at `attributes.position_accuracy_high` and **not** written to `Position.accuracy_m`, which is a 1-sigma metre figure: turning "better than 10 m" into `10.0` would state an error the source never measured |
| `message.epfd` | `Position.position_source` | `ais 1.0.0` | the EPFD code, where the message carries one (4, 5, 19, 21) |
| `message.utc_second` | `Event.observed_at` | `ais 1.0.0` | AIS states a second-of-minute, never a date — reconciled against the receipt instant, see the fills table |
| `message.utc_second` | `Position.position_source` | `ais 1.0.0` | its out-of-band values are the position-source statement on types 1/2/3/18/19: 61 manual, 62 dead reckoning, 63 positioning system inoperative |
| `message.raim` | `Entity.attributes` | `ais 1.0.0` | receiver autonomous integrity monitoring in use; parked |
| `message.radio_status` | `Entity.attributes` | `ais 1.0.0` | the SOTDMA/ITDMA slot state, as the raw integer. Parked and never interpreted: it describes the radio link, not the vessel |
| `message.spare*`, `message.reserved*` | `Entity.attributes` | `ais 1.0.0` | parked as sent. They carry no meaning today and are the bits a regional authority allocates tomorrow |

### Position reports — types 1, 2, 3 (Class A)

| AIS | CDM field | Status | Notes |
|---|---|---|---|
| `message.navigational_status` | `Event.severity` | `ais 1.0.0` | 14 (AIS-SART / MOB / EPIRB active) → `CRITICAL`; every other value → `INFO`. The line is drawn at what the standard itself defines as an active distress transmission — grading "aground" would be the translator judging operational significance, which belongs to fusion |
| `message.navigational_status` | `Event.event_type` | `ais 1.0.0` | 14 → `ALERT`, otherwise `TRACK_UPDATE` |
| `message.navigational_status` | `Entity.attributes` | `ais 1.0.0 · parked` | the code AND its standard wording, at `attributes.navigational_status` / `attributes.navigational_status_text`. 15 means undefined, which is not the same as 0 "under way using engine" |
| `message.sog_knots` | `Kinematics.speed_mps` | `ais 1.0.0` | knots → m/s, a declared transform. **102.3 is the not-available sentinel and becomes null** — the failure this whole rule set is named after. 102.2 means "102.2 knots or higher" and is a real measurement, kept, with `attributes.sog_at_or_above_maximum` recording the floor |
| `message.cog_deg` | `Kinematics.course_deg` | `ais 1.0.0` | course over ground, 0.1° units → degrees. **360.0 is the not-available sentinel** |
| `message.true_heading_deg` | `Entity.attributes` | `ais 1.0.0 · parked` | **gap 7** — the CDM has no heading field distinct from course. Parked at `attributes.true_heading_deg`. **511 is the not-available sentinel** |
| `message.rate_of_turn_raw` | `Entity.attributes` | `ais 1.0.0 · parked` | **gap 7** — no canonical turn rate. The raw ROT_AIS byte is kept verbatim at `attributes.rate_of_turn_raw` and its degrees-per-minute inverse at `attributes.rate_of_turn_deg_per_min`. −128 is the not-available sentinel; ±127 mean "turning faster than 5° per 30 s", which is a floor and not a rate, so the DERIVED value is null for both while the raw byte survives |
| `message.manoeuvre_indicator` | `Entity.attributes` | `ais 1.0.0` | special manoeuvre in progress; parked |

### Class B — types 18 and 19

Type 18 is the Class B carrier-sense position report; type 19 adds the static fields to it.
Everything type 18 states is in the common table above; the rows below are what 19 adds and
what makes 18 different from a Class A report.

| AIS | CDM field | Status | Notes |
|---|---|---|---|
| *(type 18 carries no navigational status)* | `Event.severity` | `ais 1.0.0` | `INFO`, with `payload.severity_basis` recording that the format is silent rather than that the vessel is calm |
| `message.cs_unit`, `.display_flag`, `.dsc_flag`, `.band_flag`, `.message_22_flag`, `.assigned_mode` | `Entity.attributes` | `ais 1.0.0` | Class B equipment capability flags; parked. They describe the transponder, not the vessel |
| `message.vessel_name` (19) | `Entity.attributes` | `ais 1.0.0 · parked` | **gap 1** — no canonical name field. Parked at `attributes.vessel_name`, trailing `@` padding stripped |
| `message.ship_type` (19) | `Entity.attributes` | `ais 1.0.0 · parked` | code AND wording at `attributes.ship_type` / `attributes.ship_type_text`. It does not change `entity_type`: a tanker, a tug and a pleasure craft are all PLATFORM, and pretending otherwise would put a judgement in a translator |
| `message.dim_to_bow` etc. (19) | `Entity.attributes` | `ais 1.0.0 · parked` | **gap 8** — no canonical extent. Parked as four metre figures plus `attributes.length_m` / `attributes.beam_m`; 0 means not available on each, so an absent dimension is absent and never 0 m |
| `message.epfd` (19) | `Position.position_source` | `ais 1.0.0` | as the common table |

### Static and voyage data — type 5

Carries no position and no time. That is the whole reason it is a separate row set: an adapter
that treated it like a position report would have to invent both.

| AIS | CDM field | Status | Notes |
|---|---|---|---|
| `message.imo_number` | `Entity.source_ids[].external_id` | `ais 1.0.0` | system `IMO` — a SECOND source id, not a replacement. The IMO number is hull-lifetime stable where an MMSI changes with the flag, so both belong. 0 means not available and yields no entry at all |
| `message.call_sign` | `Entity.attributes` | `ais 1.0.0 · parked` | **gap 1** — parked at `attributes.call_sign` |
| `message.vessel_name` | `Entity.attributes` | `ais 1.0.0 · parked` | **gap 1** — parked at `attributes.vessel_name` |
| `message.ship_type` | `Entity.attributes` | `ais 1.0.0 · parked` | as the type 19 row |
| `message.dim_to_bow`, `.dim_to_stern`, `.dim_to_port`, `.dim_to_starboard` | `Entity.attributes` | `ais 1.0.0 · parked` | **gap 8** — as the type 19 row |
| `message.draught_m` | `Entity.attributes` | `ais 1.0.0 · parked` | **gap 8** — maximum present static draught, 0.1 m units. **0 means not available, not a draught of zero**, and it is the sentinel most likely to be forwarded by accident because it is a plausible number |
| `message.destination` | `Entity.attributes` | `ais 1.0.0 · parked` | free text the crew types; parked, never parsed into a place |
| `message.eta_month`, `.eta_day`, `.eta_hour`, `.eta_minute` | `Entity.attributes` | `ais 1.0.0 · parked` | parked as the four stated numbers at `attributes.eta`. **Not assembled into a timestamp**: AIS states no year, so a `Timestamp` would need one invented, and an ETA in the wrong year is worse than four honest numbers |
| `message.ais_version`, `.dte` | `Entity.attributes` | `ais 1.0.0` | equipment facts; parked |
| *(type 5 states no position)* | `Position` | `ais 1.0.0` | `position: None`. Never a Position holding zeros, and never last-known — this adapter has no memory of a previous message |

### Aid to navigation — type 21

| AIS | CDM field | Status | Notes |
|---|---|---|---|
| `message.aid_type` | `Entity.attributes` | `ais 1.0.0 · parked` | code AND wording at `attributes.aid_type` / `attributes.aid_type_text` |
| `message.virtual_aid` | `Entity.entity_type` | `ais 1.0.0` | set → `OVERLAY_OBJECT`, not FACILITY. A virtual AtoN is a chart symbol broadcast where nothing physical floats, and painting it as a structure is a false statement about the sea |
| `message.name` + `.name_extension` | `Entity.attributes` | `ais 1.0.0 · parked` | **gap 1** — joined in that order and parked at `attributes.aid_name`; the extension exists because the base field is 20 characters |
| `message.off_position` | `Entity.attributes` | `ais 1.0.0` | the aid is not on its charted station. Parked, and it does NOT raise severity: it is a station condition, not a distress transmission, and the severity line is drawn at the latter |
| `message.dim_to_bow` etc. | `Entity.attributes` | `ais 1.0.0 · parked` | **gap 8** — for an AtoN these are the extent of the structure |
| `message.epfd` | `Position.position_source` | `ais 1.0.0` | usually 7, surveyed → `MANUAL`, which is exactly right for a charted position |

### Base station report — type 4

| AIS | CDM field | Status | Notes |
|---|---|---|---|
| `message.utc_year` … `.utc_second` | `Event.observed_at` | `ais 1.0.0` | the ONE message in scope that states a full UTC date and time. Used directly, and `payload.observed_at_basis` says so — no reconciliation against the receipt clock is needed or performed |
| `message.epfd` | `Position.position_source` | `ais 1.0.0` | as the common table |
| *(a base station is a shore installation)* | `Entity.entity_type` | `ais 1.0.0` | `FACILITY`. Not SENSOR: an AIS base station transmits as well as receives, and SENSOR would overstate what one report establishes |

### Egress — CDM back to AIVDM

| CDM | AIS | Status | Notes |
|---|---|---|---|
| `Entity.source_ids[].external_id` | `message.mmsi` | `ais 1.0.0 · egress` | the AIS entry, so a re-emitted report updates the same station rather than duplicating it |
| `Position.lat` | `message.lat` | `ais 1.0.0 · egress` | `position: None` emits the 91/181 sentinels — AIS has no way to omit a coordinate, so the format's own "unknown" is the only honest encoding |
| `Kinematics.speed_mps` | `message.sog_knots` | `ais 1.0.0 · egress` | null emits 1023, never 0. The null-to-zero defect running outbound is the same defect |
| `Kinematics.course_deg` | `message.cog_deg` | `ais 1.0.0 · egress` | null emits 3600 |
| `Entity.attributes` | everything parked | `ais 1.0.0 · egress` | the parked fields are read back, which is what makes the round trip byte-exact for a message this adapter ingested |
| `Track.samples[].position.lat` | `message.lat` | `ais 1.0.0 · egress` | one position report per sample, in the track's own order |
| `Track.samples[].observed_at` | `message.utc_second` | `ais 1.0.0 · egress` | each sample's own second-of-minute; the date cannot be carried, which is stated rather than worked around |
| `Track.source_ids[].external_id` | `message.mmsi` | `ais 1.0.0 · egress` | every sentence in the burst carries it |

**AIS has no extension point, and that is a property of the format rather than of this
adapter.** CoT's `<detail>` is an open bag, so the TAK adapter grafts what it could not map
onto a `<synapse_plan/>` element and its egress is lossless. Every bit of every AIS message
type is allocated: there is no spare field, no vendor block, and a bit invented here would be
read by a receiver as the field the standard says lives there. So `entity_id`, `track_id`,
`track_quality`, `schema_version`, the affiliation, the symbol and the whole provenance block
have nowhere to go on the way out. `tests/test_cdm_ais_adapter.py` names each one with its
reason rather than measuring a loss it cannot fix — and measures everything AIS *can* carry,
including the fields inside the armoured payload, which it unpacks rather than exempts.

What egress is NOT lossy for is a message this adapter ingested: the parked fields are read
back, so `to_cdm()` followed by `from_cdm()` reproduces the original sentences byte for byte.
That is asserted over every ingest fixture.

### What the AIS adapter fills that AIS does not state

Each of these is a CDM field with no AIS source, so it is derived or declared — and each says
so in the object itself rather than leaving a consumer to guess.

| AIS | CDM field | Status | Notes |
|---|---|---|---|
| *(none — AIS states no identity)* | `Entity.affiliation` | `ais 1.0.0` | `UNKNOWN`, always, with `attributes.affiliation_basis` recording that the format carries none. AIS is a collision-avoidance broadcast; nothing in it is a military identification |
| *(derived)* | `Entity.symbol` | `ais 1.0.0` | derived from the affiliation via `symbology.sidc_from_affiliation`, so every AIS contact is an UNKNOWN glyph. `attributes.symbol_basis` says so |
| `message.utc_second` + receipt | `Event.observed_at` | `ais 1.0.0` | AIS states a second-of-minute and no date. The instant is the one bearing that second nearest the receipt time, and `payload.observed_at_basis` names both halves. The raw second — including 60–63, which are not seconds at all — is parked at `attributes.utc_second_raw` |
| `message.mmsi` + `observed_at` | `Event.event_id` | `ais 1.0.0` | keyed on BOTH, for the CoT reason: an MMSI identifies the station and repeats on every report, so an id keyed on it alone would collapse a voyage into one event |
| *(none)* | `Entity.confidence` | `ais 1.0.0` | `None`. The position-accuracy flag is not a confidence in the object's identity, and there is nothing else to read |
| *(none)* | `Entity.valid_to` | `ais 1.0.0` | `None`. AIS has no staleness field; the reporting interval implied by a navigational status is a judgement about how long a report stays good, and that belongs to fusion |
| everything unmapped | `Entity.attributes` | `ais 1.0.0` | `attributes.source_extras`, structure intact — the sentence envelope, the spare bits, the radio state, and whatever a regional authority allocates next |
| *(measured)* | `Entity.attributes` | `ais 1.0.0` | `attributes.unavailable_fields`, the sorted list of fields the source explicitly marked not-available with a sentinel. "The vessel said it does not know its heading" and "this adapter had nothing to say" are different facts and only one of them is in the data |

### Deliberately out of scope, and why

An unimplemented message type is a decision, so each one is named. "Not supported" without a
reason is indistinguishable from "nobody thought about it", and the difference is the only
thing a reader of this table actually needs.

| Types | Decision |
|---|---|
| **24** — static data report, parts A and B | **The highest-value omission, and the reason is structural rather than effort.** Parts A and B are two separate transmissions that must be joined on MMSI across time to yield one vessel's static data. An `Adapter` is a pure function of one payload (see `adapter.py`), so a type-24 translator either emits two half-populated entities or holds a cache — and a cache in a translator is fusion done where nothing audits it. Resolving that is a design decision about where the join lives, not a coding task |
| **6, 8, 25, 26** — binary addressed/broadcast, application-specific | The payload is an open-ended blob keyed by DAC/FI application identifiers, defined outside the AIS message itself. Decoding one means adopting a second registry; not decoding one means parking raw bits, which the never-drop rule already gives without a row in this table. First candidate for a V2 ASM pass |
| **7, 13** — binary acknowledgement | Acknowledgements of the above. They address the radio, not the world |
| **9** — SAR aircraft position report | Deferred, not rejected: it is a position report and would cost little. It is out of the initial set because a coverage claim should cover what has a fixture and a golden file, and no SAR-aircraft leg exists in the Baltic scenario package yet |
| **10, 11** — UTC date inquiry and response | Link housekeeping. There is no entity, no event and no position in either |
| **12, 14** — safety-related addressed and broadcast text | Free text between stations. It would translate to an `Event` with a text payload and no geometry, which is defensible — but the CDM has no event type for a safety broadcast, and adding one is a MINOR schema bump this task is not the place to make |
| **15, 16, 20, 22, 23** — interrogation, assignment, data-link management, channel management, group assignment | Network management. A CDM object built from one would be an object about the AIS radio network, which the CDM does not model. These are correctly absent rather than missing |
| **17** — DGNSS broadcast binary message | Differential corrections: a binary payload addressed to receivers, in the same category as the above |
| **27** — long-range AIS position report | In scope conceptually. Out of the initial set because its position is 1/10 min rather than 1/10000 min, and the honest way to carry a coarser fix is to say how coarse it is — which is `Position.accuracy_m`, a figure this message does not state either. It should ship with that question answered rather than parked |
| **Cross-payload fragment reassembly** | Not a message type, but the same decision. The adapter reassembles the fragments present in ONE payload; it does not hold a buffer for a fragment that arrives in the next TCP read. A buffer is state, for the same reason type 24 is deferred, and a feed reader is the right owner of it |

## ADS-B 1090ES Extended Squitter (Mode S DF17/DF18) — ingest and egress

Implemented by `adapters/adsb.py` (bidirectional). Ingest translates one 112-bit extended
squitter **frame** — delivered as a hex string in the AVR text form (`*8D…;`) — into an
`Entity` + an `Event`; egress turns an `Entity` or a `Track` back into DF17 frames. The paths
in the left column are dotted paths into the **parsed** form the adapter's own decoder
produces (`_parse_frames()`), which is what each `.parsed.json` fixture holds and what the
never-drop check is measured against.

The **ICAO 24-bit address** is the source id, on every frame type, in every direction. It is
the only identifier 1090ES carries that is stable across transmissions — a callsign arrives in
a *different* frame than the position does, and a Mode A squawk identifies a flight rather
than an airframe.

Three properties of this format shape every row below, and none of them has an AIS analogue:

1. **A frame carries no time.** Not a second-of-minute, not a date, nothing. The `T` bit says
   only whether the position is synchronised to a 0.2 s UTC epoch. So `observed_at` is the
   receipt instant on every frame, and `payload.observed_at_basis` says so rather than
   implying the aircraft stated it.
2. **A single frame carries no unambiguous position.** The 17-bit CPR fields need either a
   second frame of the opposite parity or a reference position. See the CPR decision below.
3. **Nothing in 1090ES is authenticated.** Every field is self-declared by the transmitter and
   there is no integrity mechanism beyond the CRC, which detects corruption and not forgery.
   That is why `affiliation` is UNKNOWN here for a stronger reason than AIS's silence: AIS
   states no identity, and ADS-B states one that must not be trusted.

### The frame envelope

Present on every frame regardless of type code. Nothing here describes the world, so nothing
here is a canonical field: the envelope describes the *radio*, and egress rebuilds it.

| ADS-B | CDM field | Status | Notes |
|---|---|---|---|
| `frame.hex` | `Entity.attributes` | `adsb 1.0.0` | the 28 hex characters, verbatim. Parked because it is the evidence an auditor asks for: every decoded field below is a claim ABOUT these 112 bits |
| `frame.prefix` | `Entity.attributes` | `adsb 1.0.0` | the AVR marker — `*` for a bare frame, `@` for one carrying a receiver timestamp counter |
| `frame.timestamp_raw` | `Entity.attributes` | `adsb 1.0.0` | the 48-bit 12 MHz receiver counter from the `@` form. **Parked and deliberately NOT read as a time** — it is a free-running counter since receiver start, not a clock, and treating it as a UNIX epoch would date every frame to 1970. This is the row where ADS-B differs from AIS most sharply: the NMEA TAG block IS a wall clock and is read as one |
| `message.parity` | `Event.payload` | `adsb 1.0.0` | the frame's own 24-bit parity field. Verified against the CRC of the first 88 bits on ingest and recomputed on egress; `payload.parity_basis` records the check. A frame whose CRC fails is REFUSED, never best-effort decoded |
| `message.df` | `Entity.attributes` | `adsb 1.0.0` | 17 (transponder) or 18 (non-transponder / TIS-B / ADS-R). Parked at `attributes.adsb_downlink_format` |
| `message.capability` | `Entity.attributes` | `adsb 1.0.0` | the same three bits mean CA (transponder capability) on DF17 and CF (control field) on DF18. Parked raw, and interpreted per `df` — see the DF18 rows |

### Common to every frame type in scope

| ADS-B | CDM field | Status | Notes |
|---|---|---|---|
| `message.icao` | `Entity.source_ids[].external_id` | `adsb 1.0.0` | system `ICAO24`, **not** `ADSB`. The address is an ICAO Annex 10 aircraft address, stable for the airframe and carried identically by Mode S replies, ACAS and ASTERIX — so a fusion layer joining an ADS-B contact to a radar track keys on exactly this string, and `ids.derive` then agrees across both adapters without coordinating. `source.system` records that this copy arrived over ADS-B |
| `message.icao` | `Entity.attributes` | `adsb 1.0.0` | parked at `attributes.icao_address` as well, and the country of registration is deliberately NOT looked up: a state of registry is not an affiliation, and a table mapping one to the other inside a translator is exactly the enrichment adapters may not do |
| `message.type_code` | `Entity.attributes` | `adsb 1.0.0` | the raw type code at `attributes.adsb_type_code`, and the frame kind this adapter resolved it to at `attributes.adsb_frame_kind` |
| `message.type_code` | `Event.event_type` | `adsb 1.0.0` | position and velocity frames → `TRACK_UPDATE`; identification, aircraft status and operational status → `STATUS_CHANGE`, because calling a frame that carries no position a track update would claim one |
| `message.type_code` | `Entity.entity_type` | `adsb 1.0.0` | `PLATFORM`, refined only by the emitter category — see the identification rows. A position frame states no category, so a point obstacle broadcasting its position is a PLATFORM until an identification frame says otherwise; that is a cross-frame join and is named in the declines table rather than guessed |
| *(none)* | `Entity.affiliation` | `adsb 1.0.0` | `UNKNOWN`, always, with `attributes.affiliation_basis` recording *why*: 1090ES is an unauthenticated cooperative broadcast, so its self-declared contents are not an identification. This is a different situation from AIS's silence and the basis string distinguishes them |
| *(derived)* | `Entity.symbol` | `adsb 1.0.0` | from the affiliation via `symbology.sidc_from_affiliation`, so every ADS-B contact is an UNKNOWN glyph. `attributes.symbol_basis` says so |
| `message.icao` + `observed_at` | `Event.event_id` | `adsb 1.0.0` | keyed on BOTH, for the reason the CoT and AIS adapters give: an address identifies the airframe and repeats on every frame, so an id keyed on it alone would collapse a whole flight into one event |
| *(none)* | `Entity.valid_to` | `adsb 1.0.0` | `None`. ADS-B has no staleness field; how long a frame stays good is a judgement about data and belongs to fusion |
| *(none)* | `Entity.confidence` | `adsb 1.0.0` | `None`. NACp and SIL are integrity and accuracy categories in a *different* frame, and neither is a confidence in the object's identity |
| *(measured)* | `Entity.attributes` | `adsb 1.0.0` | `attributes.unavailable_fields`, the sorted list of fields the source explicitly marked not-available — either with a zero sentinel or by clearing the status bit that validates them. "The aircraft said it does not know its ground track" and "this adapter had nothing to say" are different facts |
| *(measured)* | `Entity.attributes` | `adsb 1.0.0` | `attributes.unresolved_raw`, the wire values this adapter read and could not turn into a CDM value — a Gillham altitude, an invalidated ground track or heading, a reserved movement code, a velocity component whose partner is absent. A DIFFERENT fact from the list above and the pair is the point: that one is "the source said it does not know", this one is "the source said something and the translator could not use it, so here are its bits". Both render as an absent field, and the byte-exact round trip is what proved that keeping only the first loses data |
| everything unmapped | `Entity.attributes` | `adsb 1.0.0` | `attributes.source_extras`, structure intact — the reserved fields, the intent-change and IFR-capability flags, the navigation-uncertainty category, and whatever a future DO-260 revision allocates |

### Airborne position — type codes 0, 9–18 (barometric) and 20–22 (GNSS height)

The two type-code ranges share one 56-bit ME layout, and the twelve altitude bits are the same
wire position in both. Everything else about them differs — the measurement, the reference
surface, the **unit** and the **encoding** — and that is the reason two rows below go to
different places. Source for the GNSS side: mode-s.org, *The 1090MHz Riddle*, airborne position
chapter — "the 12-bit altitude field is used for the encoding of the GNSS height … the decimal
value of all 12 bits translates into the height of aircraft in meters"
(<https://mode-s.org/1090mhz/content/ads-b/3-airborne-position.html>). It is cited because
assuming the two ranges shared the barometric arithmetic is a mistake that stays plausible: it
reports an altitude wrong by up to a factor of eight and leaves every other check passing.

| ADS-B | CDM field | Status | Notes |
|---|---|---|---|
| `message.cpr_lat`, `.cpr_lon`, `.cpr_format` | `Position.lat` / `Position.lon` | `adsb 1.0.0` | decoded ONLY against a configured reference position — see the CPR decision. With no reference the position is **absent** and all three fields are parked verbatim, which is the default and the safe direction |
| `message.cpr_lat`, `.cpr_lon`, `.cpr_format` | `Entity.attributes` | `adsb 1.0.0` | parked on every frame whether or not a position was decoded, so a fusion layer holding a global pair can redo the decode properly and is never asked to trust ours |
| *(derived)* | `Position.position_source` | `adsb 1.0.0` | `GNSS` for DF17 and for DF18 CF 0/1/6 — an ADS-B position is the aircraft's own GNSS fix. **`ESTIMATED` for DF18 CF 2/5**, fine-format TIS-B: that is a ground station rebroadcasting a surveillance track it derived by other means, and calling it GNSS would promise a fix that survives jamming. `attributes.position_source_basis` names which case applied |
| `message.altitude_raw` (TC 20–22) | `Position.alt_m` | `adsb 1.0.0` | GNSS height, which is exactly what `alt_m` documents. **The plain decimal value of all 12 bits, in METRES** — no Q bit, no −1000 ft offset, no 25-foot increment — so it reaches `alt_m` with no conversion at all. Two consequences: the field **saturates at 4095 m** (about 13 435 ft), which is why these type codes are little used at cruise, and an altitude above that range is an **encode error** on egress rather than a saturated value, because a cruise level clipped to 4095 m reads as a real low altitude to every consumer. All-zero becomes an absent altitude, never 0 m — but see the next row, because that reading is asserted rather than read |
| `message.altitude_raw` = 0 (TC 20–22) | `Entity.attributes` | `adsb 1.0.0` | the reference documents the all-zero "not available" meaning for the **barometric** field and is **silent** for this one, so treating it as absent is this adapter's decision taken in the safe direction: 0 m would place an airborne aircraft exactly on the ellipsoid, and an absent altitude is recoverable where a false one is not. `attributes.altitude_basis` says which of the two happened, so the decision is auditable rather than a property of the code |
| `message.altitude_raw` (TC 20–22) | `Entity.attributes` | `adsb 1.0.0` | ALSO parked at `attributes.gnss_altitude_m`, symmetrically with the barometric key below, and that is a finding rather than a convenience: `Position` requires a latitude and a longitude, so an altitude with no horizontal fix has nowhere canonical to go — and this format produces exactly that on every position frame whose CPR cannot be decoded. Without the parked key the altitude was silently lost on those frames, which the byte-exact round trip caught. Note the **unit in each key name**: this one counts whole metres and the barometric one counts feet, because the two wire fields do. See the note under gap 9 |
| `message.altitude_raw` (TC 0, 9–18) | `Entity.attributes` | `adsb 1.0.0 · parked` | **gap 9** — barometric altitude has no canonical home. It is a pressure altitude against the 1013.25 hPa datum, NOT a height above the ellipsoid, and the two differ by hundreds of metres in ordinary weather. Writing it into `alt_m` would be the same class of false statement as writing AIS's accuracy threshold into `accuracy_m`. Parked at `attributes.baro_altitude_ft` |
| `message.altitude_raw` (Q bit = 0) | `Entity.attributes` | `adsb 1.0.0 · parked` | the 100-foot **Gillham** (reflected Gray) encoding, used above 50 175 ft. Deliberately NOT decoded — see the declines table. The raw 12 bits are parked at `attributes.unresolved_raw` and the altitude is absent, because a Gillham decode assembled from memory would produce a confident wrong flight level rather than a visible gap. Barometric only: every non-zero GNSS-height value decodes, so there is nothing left unresolved there |
| `message.type_code` | `Entity.attributes` | `adsb 1.0.0 · parked` | the type code encodes a **navigation integrity category**, so it is a claim about accuracy and not only a message selector. Parked, and NOT turned into `Position.accuracy_m`: recovering a containment radius needs the NICa supplement from a type 31 frame, which is a cross-frame join, and a containment radius is an integrity bound rather than the 1-sigma figure that field holds |
| `message.surveillance_status` | `Event.severity` / `Event.event_type` | `adsb 1.0.0` | 1 (permanent alert — an emergency condition) → `CRITICAL` / `ALERT`. 2 (temporary alert, ident code change) and 3 (SPI) → `INFO`: those are procedural conditions, and the severity line is drawn where the standard itself declares an emergency. Code and wording parked |
| `message.nic_supplement_b` | `Entity.attributes` | `adsb 1.0.0` | one bit of the NIC supplement; parked, and meaningless without its partner in a type 31 frame |
| `message.time_sync` | `Entity.attributes` | `adsb 1.0.0` | whether the position is synchronised to a 0.2 s UTC epoch. Parked, and **not** read as a timestamp — it is a flag about time, not a time |
| *(none — the frame states no time)* | `Event.observed_at` | `adsb 1.0.0` | the receipt instant, with `payload.observed_at_basis` stating that 1090ES carries no time field at all |

### Surface position — type codes 5–8

| ADS-B | CDM field | Status | Notes |
|---|---|---|---|
| `message.cpr_lat`, `.cpr_lon`, `.cpr_format` | `Position.lat` / `Position.lon` | `adsb 1.0.0` | as the airborne rows, but the CPR zones span 90° rather than 360°, so a local decode is unambiguous only within ~45 NM of the reference instead of ~180 NM. `attributes.position_decode_basis` states which range applied |
| `message.movement_raw` | `Kinematics.speed_mps` | `adsb 1.0.0` | ground speed, from the standard's non-linear 7-bit bucket table, knots → m/s. **0 means not available and becomes null.** 1 means "stopped, below 0.125 kt", which IS a measurement of stillness and becomes 0.0. 124 means "175 kt or above" — a floor, so it is kept with `attributes.movement_at_or_above_maximum` recording that it is one, exactly as AIS's 102.2 knots is. 125–127 are reserved and become null |
| `message.ground_track_raw` | `Kinematics.course_deg` | `adsb 1.0.0` | 128 steps of 2.8125°, and a track over the ground — which is what `course_deg` means. Valid only when `track_valid` is set; cleared, the course is absent and the field is named in `unavailable_fields` |
| `message.track_valid` | `Entity.attributes` | `adsb 1.0.0` | the status bit that validates the field above. Parked, because "the aircraft cleared the validity bit" and "the field happened to be zero" are different statements — and where it is CLEAR the track's own wire value goes to `attributes.unresolved_raw` rather than being discarded, since a real-looking number the aircraft says not to read is neither a measurement nor something to throw away |
| *(a surface frame states no altitude)* | `Position.alt_m` | `adsb 1.0.0` | `None`. The aircraft is on the ground, and inventing 0.0 would be a measurement nobody made |

### Aircraft identification — type codes 1–4

Carries no position and no time. That is why it is a separate row set: an adapter that treated
it like a position frame would have to invent both.

| ADS-B | CDM field | Status | Notes |
|---|---|---|---|
| `message.callsign` | `Entity.attributes` | `adsb 1.0.0 · parked` | **gap 1** — no canonical name field. Parked at `attributes.callsign`, trailing pad characters stripped. Note that the TAK adapter already parks a CoT callsign under this *same* key: see the gap 1 note, because two adapters agreeing on a private key by coincidence is worse than four disagreeing |
| `message.callsign` | `Entity.attributes` | `adsb 1.0.0` | `attributes.callsign_raw` keeps the eight decoded characters exactly as sent, including `#` for a 6-bit value the ICAO alphabet does not define, so a malformed callsign is visible rather than cleaned away |
| `message.emitter_category` + `.type_code` | `Entity.attributes` | `adsb 1.0.0 · parked` | code AND wording at `attributes.emitter_category` / `attributes.emitter_category_text`. The category SET is selected by the type code (1→D, 2→C, 3→B, 4→A), so neither number means anything alone |
| `message.emitter_category` + `.type_code` | `Entity.entity_type` | `adsb 1.0.0` | it does NOT generally refine the entity type — a light aircraft, a heavy and a rotorcraft are all PLATFORM, and inventing a finer CDM distinction would put a judgement in a translator, exactly as an AIS ship type does not. The ONE exception is category set C 3/4/5, point/cluster/line **obstacle**: those are fixed structures and become `FACILITY`, for the same reason an AIS aid to navigation does |
| `message.emitter_category` = 0 | `Entity.attributes` | `adsb 1.0.0` | "no category information", a stated absence rather than category zero, so it is named in `unavailable_fields` |
| *(the frame states no position)* | `Position` | `adsb 1.0.0` | `position: None`. Never a Position holding zeros, and never last-known — this adapter has no memory of a previous frame |

### Airborne velocity — type code 19

Subtypes 1 and 2 state velocity over the ground; subtypes 3 and 4 state airspeed and heading.
They are two different measurements in one type code, and the rows below are where that split
costs the CDM something.

| ADS-B | CDM field | Status | Notes |
|---|---|---|---|
| `message.subtype` | `Entity.attributes` | `adsb 1.0.0` | 1/2 ground, 3/4 air, and 2/4 are the supersonic variants whose velocity fields are scaled by 4. Parked, with `attributes.velocity_subtype_text` |
| `message.ew_velocity_raw`, `.ns_velocity_raw`, `.ew_sign`, `.ns_sign` | `Kinematics.speed_mps` | `adsb 1.0.0` | the two signed components → a scalar ground speed, knots → m/s, a declared transform. **0 means not available on each component**, and a missing component yields NO speed rather than a speed computed from one axis |
| `message.ew_velocity_raw`, `.ns_velocity_raw` | `Kinematics.course_deg` | `adsb 1.0.0` | track over ground = `atan2(east, north)`, normalised into [0, 360). A course derived from one axis alone would be a bearing of exactly 000/090/180/270, which looks like a measurement, so both components are required |
| `message.airspeed_raw`, `.airspeed_type` | `Entity.attributes` | `adsb 1.0.0 · parked` | **gap 10** — `Kinematics.speed_mps` is a speed over the ground, and this is an indicated or true AIRSPEED. Parked at `attributes.airspeed_kt` / `attributes.airspeed_type`, and `speed_mps` stays null on a subtype 3/4 frame. The difference between the two is the wind, which is the fact an analyst reads |
| `message.heading_raw`, `.heading_valid` | `Entity.attributes` | `adsb 1.0.0 · parked` | **gap 7** — no canonical heading distinct from course. Parked at `attributes.heading_deg`, 1024 steps of 360°. **And this is the row that sharpens gap 7 rather than merely re-reporting it**: an ADS-B heading is referenced to MAGNETIC north unless a type 31 frame's HRD bit says otherwise, while an AIS true heading is referenced to true north. A `Kinematics.heading_deg` with no datum would silently hold two different measurements |
| `message.vertical_rate_raw`, `.vertical_rate_sign` | `Kinematics.climb_mps` | `adsb 1.0.0` | 64 ft/min steps, feet per minute → metres per second, a declared transform. Sign convention matches the CDM's (negative descending). **0 means not available and becomes null, never level flight** |
| `message.vertical_rate_source` | `Entity.attributes` | `adsb 1.0.0` | whether the vertical rate is GNSS-derived or barometric. Parked — and load-bearing for the same reason `position_source` is, since only one of the two survives GNSS denial |
| `message.gnss_baro_diff_raw`, `.gnss_baro_diff_sign` | `Entity.attributes` | `adsb 1.0.0 · parked` | the difference between GNSS height and barometric altitude, 25 ft steps. Parked at `attributes.gnss_baro_difference_ft`; 0 means not available. It is the bridge between gap 9's two altitudes and belongs with whichever field closes it |
| `message.nav_uncertainty_velocity` | `Entity.attributes` | `adsb 1.0.0` | NACv, a velocity accuracy category. Parked and NOT written to any accuracy field — the CDM has no velocity accuracy, and a category is not a metre-per-second figure |

### Aircraft status — type code 28, subtype 1

| ADS-B | CDM field | Status | Notes |
|---|---|---|---|
| `message.emergency_state` | `Event.severity` / `Event.event_type` | `adsb 1.0.0` | 1–6 (general emergency, medical, minimum fuel, no communications, unlawful interference, downed aircraft) → `CRITICAL` / `ALERT`. 0 is no emergency and 7 is reserved, both `INFO`. The line is drawn at the standard's own emergency declaration, exactly where the AIS adapter draws it at navigational status 14 |
| `message.emergency_state` | `Entity.attributes` | `adsb 1.0.0 · parked` | code AND wording at `attributes.emergency_state` / `attributes.emergency_state_text` |
| `message.mode_a_code_raw` | `Entity.attributes` | `adsb 1.0.0 · parked` | the Mode A squawk, as the raw 13 bits AND the four octal digits at `attributes.mode_a_code`. **Deliberately not a `SourceId`**: a squawk is assigned by ATC per flight and reassigned afterwards, so it identifies a flight and not an airframe — and a source id that changes on landing would split one aircraft into many entities |

### Aircraft operational status — type code 31, subtype 0

| ADS-B | CDM field | Status | Notes |
|---|---|---|---|
| `message.version` | `Entity.attributes` | `adsb 1.0.0` | the ADS-B version (0 = DO-260, 1 = DO-260A, 2 = DO-260B). Parked, and it is what says how to read several of the fields above — which is why a frame set from mixed versions cannot be interpreted without it |
| `message.horizontal_reference_direction` | `Entity.attributes` | `adsb 1.0.0` | HRD: whether headings and tracks from this aircraft are referenced to true or magnetic north. Parked at `attributes.heading_reference`, and named in the gap 7 note as the datum a canonical heading field would need |
| `message.nac_position` | `Entity.attributes` | `adsb 1.0.0 · parked` | NACp, a 95 % horizontal accuracy CATEGORY. Parked, and not written to `Position.accuracy_m`: a category bound is not a 1-sigma metre figure, and it arrives in a different frame than the position it would qualify |
| `message.source_integrity_level`, `.sil_supplement`, `.geometric_vertical_accuracy`, `.nic_supplement_a`, `.nic_baro` | `Entity.attributes` | `adsb 1.0.0` | the integrity and accuracy category set; parked as stated. They qualify measurements carried in other frames, and joining them is fusion's to do where it is visible |
| `message.capability_class`, `.operational_mode` | `Entity.attributes` | `adsb 1.0.0` | 16 bits each of equipment capability and operational mode. Parked as raw integers and deliberately not unpacked: their bit meanings change with `version`, and unpacking them against the wrong version would report capabilities the aircraft never claimed |

### DF18 — non-transponder devices, TIS-B and ADS-R

DF18 reuses the DF17 ME layouts and changes what the frame MEANS, which is why it is a row set
rather than a footnote. The control field is the only thing that says so.

| ADS-B | CDM field | Status | Notes |
|---|---|---|---|
| `message.capability` (CF 0) | `Entity.attributes` | `adsb 1.0.0` | ADS-B device with an ICAO24 address. Treated exactly as DF17 |
| `message.capability` (CF 1, 5) | `Entity.source_ids[].system` | `adsb 1.0.0` | **the address is NOT an ICAO24 address** — it is anonymous or self-assigned. The source id system becomes `ADSB_NONICAO` instead, because filing a self-assigned number under `ICAO24` would let fusion join this contact to a real airframe that happens to share the number |
| `message.capability` (CF 2, 5) | `Position.position_source` | `adsb 1.0.0` | fine-format TIS-B: a ground station's rebroadcast of a surveillance track → `ESTIMATED`, never GNSS |
| `message.capability` (CF 6) | `Entity.attributes` | `adsb 1.0.0` | ADS-R rebroadcast. The original fix IS the aircraft's GNSS, so `position_source` stays GNSS, and `attributes.adsb_relay` records that the frame reached us via a rebroadcast rather than directly |
| `message.capability` (CF 3, 4, 7) | — | `adsb 1.0.0` | REFUSED by name — see the declines table |

### Egress — CDM back to DF17 frames

| CDM | ADS-B | Status | Notes |
|---|---|---|---|
| `Entity.source_ids[].external_id` | `message.icao` | `adsb 1.0.0 · egress` | the `ICAO24` entry, so a re-emitted frame updates the same airframe rather than duplicating it. An object with no such entry is REFUSED: deriving an address would put an aircraft on 1090 MHz under a number nobody allocated |
| `Position.lat` / `Position.lon` | `message.cpr_lat`, `.cpr_lon` | `adsb 1.0.0 · egress` | CPR-encoded, which needs no reference position in this direction. `position: None` emits the type code's own no-position form and never the equator |
| `Position.alt_m` | `message.altitude_raw` | `adsb 1.0.0 · egress` | whole metres straight into the 12-bit field, in a GNSS-height frame (type code 20–22) and never in a barometric one — there is no unit conversion in this direction either. A null altitude emits the all-zero not-available encoding, never a flight level of −1000 ft; an altitude above 4095 m is REFUSED rather than clipped |
| `Kinematics.speed_mps` + `.course_deg` | `message.ew_velocity_raw`, `.ns_velocity_raw` | `adsb 1.0.0 · egress` | resolved back into signed components on a type 19 subtype 1 frame. A null speed or course emits 0 on both components, which is the standard's "not available" and not a stationary aircraft |
| `Kinematics.climb_mps` | `message.vertical_rate_raw` | `adsb 1.0.0 · egress` | null emits 0, never level flight |
| `Entity.attributes` | everything parked | `adsb 1.0.0 · egress` | the parked fields are read back, which is what makes the round trip byte-exact for a frame this adapter ingested |
| `Entity.position` + `Entity.kinematics` | TWO frames | `adsb 1.0.0 · egress` | **1090ES has no frame that carries both a position and a velocity.** An airborne position frame states where, a type code 19 frame states how fast, and a real transponder interleaves the two — so an Entity holding both is emitted as two frames rather than one with the velocity dropped. The exception is an Entity that came FROM ADS-B: its parked type code says which frame it was, and exactly that frame is re-emitted, because a surface position frame carries movement and ground track in the same 56 bits and synthesising a second beside it would invent a transmission the aircraft never made |
| *(derived)* | `message.type_code` | `adsb 1.0.0 · egress` | for an object that never came from ADS-B: **18** when no altitude is stated and **22** when one is. Both are the NIC 0 members of their range — the type code is a navigation-integrity claim, so defaulting to type code 9 or 20 would assert a containment radius nobody measured |
| *(computed)* | `message.parity` | `adsb 1.0.0 · egress` | the 24-bit CRC over the emitted 88 bits, computed and never copied. A frame carrying a stale parity field is discarded by every receiver, silently |
| `Track.samples[].position.lat` | `message.cpr_lat` | `adsb 1.0.0 · egress` | one position frame per sample, in the track's own order, **always with the even CPR parity**. Alternating even and odd would invite a receiver to globally pair two samples taken at different times, and a global CPR decode of a non-simultaneous pair yields a position the aircraft was never at |
| `Track.samples[].observed_at` | — | `adsb 1.0.0 · egress` | cannot travel: a frame has no time field. Stated here rather than worked around |
| `Track.samples[].position.alt_m` | `message.altitude_raw` | `adsb 1.0.0 · egress` | carried, in a type code 22 frame — see the `alt_m` row |

**ADS-B has no extension point, for the same reason AIS has none and then some.** All 56 bits
of the ME field are allocated per type code, the 24-bit parity is a CRC over the other 88, and
a bit invented here would either be read as the field the standard says lives there or would
break the CRC and be dropped by every receiver. So `entity_id`, `track_id`, `track_quality`,
`schema_version`, the affiliation, the symbol and the whole provenance block have nowhere to
go on the way out. `tests/test_cdm_adsb_adapter.py` names each one with its reason rather than
measuring a loss it cannot fix — and measures everything ADS-B *can* carry, by unpacking the
emitted frames bit by bit rather than exempting them.

What egress is NOT lossy for is a frame this adapter ingested: the parked fields are read back,
so `to_cdm()` followed by `from_cdm()` reproduces the original frame byte for byte, CRC
included. That is asserted over every ingest fixture.

### The CPR decision: pairing two frames is fusion, not translation

This is the one design question ADS-B forces that AIS did not, and it is settled by the same
argument that keeps AIS message type 24 out of scope.

A 1090ES position frame carries latitude and longitude as 17-bit **Compact Position Reporting**
values, which are a position within a zone and not a position. There are exactly two ways to
recover a coordinate:

1. **Globally**, by pairing an even-parity frame with an odd-parity frame received within about
   ten seconds. No prior knowledge is needed.
2. **Locally**, from one frame plus a reference position already known to be within about
   180 NM (airborne) or 45 NM (surface).

**Global pairing is out of scope, and the reason is structural rather than effort.** Two frames
of opposite parity are two separate transmissions that must be joined on the ICAO address
across time. An `Adapter` is a pure function of one payload (see `adapter.py`), so a
global-decoding translator either emits a half-populated object or holds a cache — and a cache
in a translator is fusion done where nothing audits it. That is word for word the AIS type 24
argument, and applying it consistently is the point: type 24's parts A and B, AIS
cross-payload fragment reassembly, and CPR even/odd pairing are one decision made three times.
It is also why this adapter refuses a payload holding two frames at all: accepting them would
smuggle the pair in through the framing.

**Local decoding IS in scope, and it needs a reference position that is configuration rather
than state.** `AdsbAdapter(reference_position=(lat, lon))` takes the receiver's own surveyed
antenna position — a constant of the deployment, supplied at construction, exactly like the
injected clock and `synthetic`. It is not accumulated from the data stream, it does not change
between frames, and it is recorded in `attributes.position_reference` on every fix it produced,
so no consumer is asked to trust a coordinate without seeing what it was decoded against.

**With no reference configured, there is no position.** That is the default, so the default
behaviour is the safe one: `position` is None, the three CPR fields are parked verbatim, and
`attributes.position_unavailable_reason` says that a single frame does not state a position.
The harness therefore gates the reference-free path; the referenced path is exercised in
`tests/test_cdm_adsb_adapter.py` against coordinates recomputed there from the published CPR
algorithm, and against its own golden files under `fixtures/adsb/local/`.

The residual risk is named rather than hidden: a local decode more than one zone away from the
reference returns a *plausible* coordinate in the wrong zone, and no single frame can reveal
that it did. `attributes.position_decode_basis` states the reference and the range within which
the result is unambiguous, and the raw CPR fields are parked on every frame so a fusion layer
holding a proper even/odd pair can discard our answer and compute its own.

### Deliberately out of scope, and why

An unimplemented frame type is a decision, so each one is named. "Not supported" without a
reason is indistinguishable from "nobody thought about it".

| Frames | Decision |
|---|---|
| **CPR global even/odd pairing** | The highest-value omission, and structural rather than effort — see the CPR decision above. Resolving it is a design decision about where the join lives, not a coding task |
| **Gillham (100 ft) altitude, Q bit = 0** | The encoding used above 50 175 ft. The bit permutation from the 12-bit ADS-B altitude field into the Mode C reflected-Gray layout is the kind of detail that is either exactly right or produces a confident wrong flight level, and no pinned reference for it exists in this repository. So it is LOGGED rather than guessed: the raw 12 bits are parked and the altitude is absent. First candidate for a V2 altitude pass, together with gap 9 |
| **Type code 19 subtypes 0 and 5–7** | Reserved by DO-260B. There is no layout to decode, and inventing one would report the reserved bits as measurements |
| **Type code 23–27, 29, 30** | Type 29 is target state and status (selected altitude, selected heading, autopilot modes) and is the most valuable of these: it states an *intent*, which the CDM has no object for — a selected altitude is not a position. Types 23–27 and 30 are reserved or aircraft-operational-coordination. All deferred rather than rejected |
| **Type code 28 subtype 2** | The ACAS resolution-advisory broadcast. Its 48 bits are an ACAS RA vocabulary defined outside 1090ES, and decoding one means adopting a second standard — the same category as AIS's DAC/FI application identifiers |
| **Type code 31 subtype 1** | Surface operational status. The low bits of the ME field differ from the airborne subtype in ways this adapter would be guessing at, and the airborne subtype is what an air picture needs. Same treatment as Gillham: named, not approximated |
| **DF18 CF 3** | Coarse-format TIS-B. It has a DIFFERENT ME layout — a lower-resolution position with its own field widths — so decoding it with the fine-format layout would produce a plausible wrong position rather than an error. Refused by name |
| **DF18 CF 4** | TIS-B management. Addresses the ground station's link, not the world |
| **DF18 CF 7** | Reserved |
| **DF0, DF4, DF5, DF11, DF16, DF20, DF21 — the rest of Mode S** | Short and long air-air and ground-air surveillance, all-call replies, and the Comm-B BDS registers. Two reasons, not one: their parity field is the CRC **overlaid with the address** rather than a plain CRC, so a frame's address can only be recovered by guessing it from a candidate list, and the BDS registers are a separate register set with their own document. A Mode S adapter is a different adapter |
| **Mode A / Mode C replies** | No ICAO address at all, so nothing to key an entity on. A Mode A squawk is carried where a frame in scope states one |
| **UAT (978 MHz)** | The other ADS-B data link. A different physical layer, a different frame, and no 1090ES type code in common |
| **Cross-payload frame buffering** | Not a frame type, but the same decision as AIS's. This adapter translates ONE frame per payload and holds no buffer for the next TCP read. A buffer is state, for the reason global CPR pairing is out of scope, and a feed reader is the right owner of it |

## Picogrid Legion Platform API v3 — ingest (specification only)

Implemented by `adapters/legion.py` (**ingest only** — see the last section for why there is no
`from_cdm()`). Every row below was written and reviewed as a specification BEFORE any code
existed, with `legion 1.0.0` in the status column; the markers now say `legion 1.0.0` because the
adapter runs them. Four of the rows changed during implementation and each change is noted where
it happened — the harness and the pinned field inventory caught all four.

### The pin, and why this row set has one when the others do not

Every other format in this document is a ratified standard: CoT, NMEA 0183, 1090ES and
STANAG 4676 change on committee timescales and in public. **Legion is a vendor API, and it can
move under us between one deploy and the next.** So this row set is pinned to the exact document
it was read from, retrieval-dated and hashed, the way `airtasking/SOURCES.md` pins its sources:

| | |
|---|---|
| Document | combined OpenAPI 3.1 spec, `GET /v3/openapi.json` |
| Host | `https://api.hopper.west.prod.govcloud.legion.picogrid.com` |
| `info.version` | `3.0.0` |
| Retrieved | 2026-08-22T21:04:41Z |
| Size | 984 135 bytes |
| SHA-256 | `464857b081f1fb47c82e56b23f7585eb44e475c64cec1678629b41a252f6b9e1` |
| `ETag` | `"464857b081f1fb47c82e56b23f7585eb44e475c64cec1678629b41a252f6b9e1"` — the server's own ETag IS the SHA-256 of the body, so a re-fetch can be compared without downloading twice |
| Prose companion | `https://docs.picogrid.com/reference/post_v3-entities-entityid-locations-2.md`, `updatedAt: 2026-05-10T09:22:51.000Z` — the ONLY place the coordinate reference systems are defined |

`info.version` is `3.0.0` and has been since at least the docs snapshot dated 2026-05-21, while
the paths under it demonstrably change (the tasking bulk endpoint is described as a newer
alternative to a legacy URL "kept because deployed clients have this URL baked in"). **So the
version string is not a usable change signal and the hash is.** Whoever revisits this row set
re-fetches and compares the ETag first; a changed hash with an unchanged `info.version` is the
expected case, not an anomaly.

Two facts about the document itself that shape everything below:

- **`components.schemas` is empty.** All 108 paths inline their schemas, so there is no single
  authoritative "Entity schema" object to point a row set at — each resource's field list is
  read off the response body of the endpoint that returns it. Two endpoints returning the same
  resource can therefore disagree, and one pair does; see the declines table.
- **The commercial server 404s on this path.** `servers` lists
  `https://legion-prod.picogrid.com` as "Commercial Production API", and
  `GET /v3/openapi.json` there returns `404 RESOURCE_NOT_FOUND`. The spec is only retrievable
  from the govcloud host, so the pin names that host rather than the API generally.

### What the adapter's input IS — a response payload, not an API client

This is the first adapter whose upstream is a REST API rather than a wire format, and the
boundary is drawn in the same place it was drawn for AIS and ADS-B: **`to_cdm()` takes one
already-fetched JSON document and nothing else.**

The adapter does not own, and must never acquire, an HTTP client, an OAuth token, a retry
policy, a page cursor or a base URL. That is not squeamishness about dependencies — it is the
same rule that keeps a fragment-reassembly buffer out of the AIS adapter. Transport is where
state lives, and an adapter that holds state is a fusion layer that nothing audits. The AIS
adapter translates sentences that a feed reader delivered; the ADS-B adapter translates frames a
receiver delivered; this one translates documents a caller fetched. What the caller had to do to
get them — authenticate, follow `paging.next`, retry a 503 — is the caller's, and stays visible
in the caller's code rather than invisible in ours.

Concretely, the accepted inputs are the parsed bodies of the single-resource and list endpoints
in scope, distinguished by their own shape rather than by a caller-supplied type tag:

| Input document | Becomes |
|---|---|
| one Entity or Track object | `Entity` (+ an `Event` only if the embedded `location_latest` is present, since that is a report of a state at an instant) |
| one Location object (entity or track) | `Event` + the `Entity` it names, from the embedded `entity` block |
| one Event object | `Event` |
| a Locations LIST envelope (`{crs, paging, results[]}`) | ONE `Track`, whose samples are `results[]` in the order given |

### Pagination is framing; correlation across resources is fusion

The type-24 / CPR test, applied to the two things a REST API invites an adapter to do.

**Pagination is framing, and framing belongs to the caller.** A locations list arrives as
`{crs, paging: {has_more, next, previous}, results[]}` with integer page cursors. One page is
one payload and becomes one `Track` — a *partial* history, honestly labelled as one. The adapter
does NOT follow `paging.next`, and it does not stitch page 2 onto page 1, for the reason it does
not buffer AIS fragments across TCP reads: the moment it does, it holds state, and the question
"how much history is in this Track?" stops being answerable from the payload. The `paging` block
is parked, so a consumer can see that more exists.

**Correlation across resources is fusion, and it stays out.** Four joins the API makes
available and this adapter declines:

- **Entity → its locations.** Two requests. A caller wanting a track fetches the list and hands
  it over; the adapter will not fetch it.
- **Event → the entity that produced it.** `Event.source_id` is a uuid and nothing else — no
  embedded entity, no name, no position. Resolving it means a second request, so the CDM `Event`
  gets `related_entities` derived from that id (which is free — `ids.derive` is a pure function
  of the id) and NOTHING else about the entity. A resolved name or position would be a join.
- **Entity → its parent** (`parent_id`). Same shape, and worse: a hierarchy walk is N requests.
- **Location list pages → one complete history.** As above.

The one join the adapter DOES perform is not a join at all: where the payload itself embeds a
related object — `Entity.location_latest`, `Location.entity` — that data arrived in the same
document and translating it is reading, not correlating. This is exactly the line the AIS
adapter draws when it reassembles the fragments *present in one payload* while refusing to
buffer across payloads.

### The round-trip claim, restated for JSON

The other adapters claim a *byte-exact* round trip, which is meaningful because their wire form
is a canonical sequence of bits. A JSON document has no canonical byte form — key order, integer
versus float spelling of `500` and `500.0`, and unicode escaping are all free — so byte equality
would be a claim about a serialiser rather than about a translation.

So for this adapter the claim is **key-for-key equality after canonicalisation**, and
canonicalisation is defined here rather than left to a library's defaults:

1. **Object keys sorted** lexicographically at every depth. Array order is PRESERVED — it is
   meaning, not formatting: `results[]` is a time-ordered history and `coordinates[]` is
   positional.
2. **Numbers compared by value, not spelling.** `500`, `500.0` and `5e2` are one number.
   Integers that arrived as integers are re-emitted as integers, because a `paging.next` of
   `2.0` is a different type to a strict consumer even though it is the same value.
3. **Absent and null are DISTINCT and both preserved.** This is the one that matters, and it is
   the JSON-native form of the sentinel discipline — see the next section.
4. **Timestamp strings re-emitted verbatim**, not re-rendered. The CDM renders timestamps to
   fixed-millisecond UTC (`times.render`), and re-emitting that form would rewrite
   `2024-01-15T11:00:00Z` as `2024-01-15T11:00:00.000Z` — the same instant, a different string,
   and a difference no reader would see. The original string is parked and restored.

### Timestamps: the accepted grammar, and what happens when a document breaks it

No in-scope timestamp carries `format: date-time` (ambiguity 6), so the grammar this adapter
accepts is stated here rather than inherited from an annotation that is not there. It is exactly
what `times.parse` accepts, which is deliberately wider than what the CDM emits:

| Accepted | Example | Treatment |
|---|---|---|
| RFC 3339 with `Z` | `2026-04-29T06:11:20Z` | parsed as UTC |
| RFC 3339 with a numeric offset | `2026-04-29T08:11:20+02:00` | converted to UTC |
| any ISO 8601 form `datetime.fromisoformat` accepts, including fractional seconds of any length | `2026-04-29T06:11:20.123456Z` | parsed, then TRUNCATED to milliseconds on output — never rounded, because rounding `23:59:59.9995` forward moves an event into the next day |
| a naive form with no zone at all | `2026-04-29T06:11:20` | **assumed UTC, and the assumption is DECLARED** in `payload.observed_at_basis` rather than left silent. The alternative — inferring the host's zone — makes one document parse differently on a laptop and in the enclave |

Everything else is a refusal, and the shape of the refusal is the point. **An unparseable
`observed_at` parks the whole document with a written reason and never yields an invented
instant.** `to_cdm()` raises, naming the field, the offending value verbatim and the grammar
above; it does not fall back to the receipt clock, and it does not emit an object with a
plausible time. Two reasons:

- The `Adapter` contract forbids a partial object (see `adapter.py`), and an `Event` whose
  `observed_at` came from our clock while claiming to be the source's observation is precisely
  a partial object with the gap filled in.
- A fabricated instant is unfalsifiable downstream. A refused document is visible in the
  caller's error handling, where somebody can look at the payload; a document silently stamped
  with the wrong minute is a track that drifts for reasons nobody can find.

The narrow exception is a timestamp that is *absent* rather than malformed, which is a different
fact and is handled by the fallback chain in the row set — `recorded_at` absent falls back to
`created_at`, and the basis says so. Absent is the API declining to state; unparseable is the
API stating something that is not a time.

### "Optional" is not "unknown" — the JSON-native sentinel discipline

AIS spelled "not available" as an in-band number and ADS-B as a zero in an offset field. A JSON
API spells it three ways, and they mean different things:

| Form | Means | Goes to |
|---|---|---|
| key **absent** | the API did not say. May be a field this deployment never populates | nothing — and NOT `unavailable_fields`, because nobody claimed not to know |
| key present, value **`null`** | the source states it has no value. `parent_id` is `required` AND nullable, so "this entity has no parent" is an assertion | `attributes.unavailable_fields`, exactly as an AIS sentinel does |
| key present, value **empty** (`""`, `[]`, `{}`) | ambiguous, and the spec never says which. Treated as stated-and-empty, parked verbatim | `attributes.source_extras` |

The distinction is load-bearing here in a way it was not for a wire format, where every field is
always physically present. `required` in OpenAPI constrains the *document*, not the world: a
`required` + nullable field is the API's way of saying "you will always be told, and the answer
may be nothing". Collapsing absent into null would manufacture assertions the API never made.

### Legion Entity — and Legion Track, which is the same resource

`GET /v3/entities/{entityId}` and `GET /v3/tracks/{trackId}` return **byte-identical schemas**
(verified by comparing the two inline schema objects in the pinned document), and
`TrackLocation`'s foreign key is named `entity_id` rather than `track_id`. A Legion "Track" is an
Entity whose `category` is `TRACK`; the `/v3/tracks` paths are a view over one underlying
resource, not a second resource.

**That settles the mapping question, and not in the direction the resource names suggest. A
Legion Track is a CDM `Entity`, NOT a CDM `Track`.** The CDM's `Track` is a position history —
STANAG 4676's shape — and Legion's history lives in its *Locations* collection. So:

| Legion resource | CDM object |
|---|---|
| Entity | `Entity` |
| Track | `Entity`, with `category: TRACK` parked — the same translation, no special case |
| Entity Location / Track Location (one) | `Event` (a state reported at an instant) + `Position` on the Entity |
| Entity Locations / Track Locations (a list) | `Track`, samples in payload order |
| Event | `Event` |

| Legion | CDM field | Status | Notes |
|---|---|---|---|
| `id` | `Entity.source_ids[].external_id` | `legion 1.0.0` | system `LEGION`; `format: uuid`. The id `entity_id` is derived from |
| `organization_id` | `Entity.attributes` | `legion 1.0.0` | the owning org, `format: uuid`. Parked and deliberately NOT read as an affiliation or a classification: a tenant boundary is not a side |
| `parent_id` | `Entity.attributes` | `legion 1.0.0 · parked` | **gap 11** — the CDM has no hierarchy. `required` AND nullable, so `null` is the assertion "no parent" and lands in `unavailable_fields`, while a uuid is parked. Resolving it is a second request and therefore fusion |
| `name` | `Entity.attributes` | `legion 1.0.0 · parked` | **gap 1** — no canonical name, and this is the strongest evidence yet: `name` is `required` on every Legion entity, so EVERY object from this source has an operator-facing string with nowhere canonical to go |
| `type` | `Entity.attributes` | `legion 1.0.0 · parked` | free-form string, example `"Camera"`. No enum, so it is a vendor vocabulary and cannot be mapped to `entity_type` without a table this adapter would be inventing |
| `status` | `Entity.attributes` | `legion 1.0.0 · parked` | free-form string, example `"active"`. Same reasoning; note it is NOT `is_active`, and the spec never relates the two |
| `category` | `Entity.entity_type` | `legion 1.0.0` | the one enum that maps: `SENSOR` → SENSOR · `VEHICLE`, `UXV` → PLATFORM · `ZONE`, `GEOMETRIC` → OVERLAY_OBJECT · `DEVICE` → SENSOR is WRONG, so → UNKNOWN unless `type` says otherwise · `DETECTION`, `ALERT`, `TRACK`, `WEATHER` → UNKNOWN, because they name a *report about* something rather than a thing that exists. Raw value parked |
| `affiliation` | `Entity.affiliation` | `legion 1.0.0` | **gap 2 at its widest: 15 values → 4.** See the affiliation table below — this is the row set's most consequential mapping |
| `affiliation` | `Entity.attributes` | `legion 1.0.0 · parked` | the original string, always. The collapse is recoverable only because it is parked, which the lossless check enforces rather than trusts |
| `top_classification` | `Entity.attributes` | `legion 1.0.0 · parked` | **gap 12** — a classifier's verdict (example `"HUMAN"`) has no canonical home, and it is NOT gap 1's operator-facing name |
| `classification` | `Entity.attributes` | `legion 1.0.0` | **the spec contradicts itself here** — declared `type: object` with the example `"2023-12-15T14:30:00Z"`, which is a string. Parked verbatim, whatever arrives, and NOT parsed as either: see the ambiguity list. Distinct from `top_classification`, and the spec never relates the two |
| `metadata` | `Entity.attributes` | `legion 1.0.0` | **EXPORT-REVIEW RELEVANT** — a bare `type: object` with no declared properties, so its contents are whatever the deployment puts there, and the spec's own example carries `ip_address`, `manufacturer` and `model`. That is infrastructure detail about our own estate rather than an observation of the world: it describes what we field and where it can be reached. Parked whole with its structure intact (the never-drop rule is not negotiable), flagged at `attributes.export_review` naming the key, and it is the field a deployment should review before a CDM object crosses a releasability boundary. This adapter does not filter it — a translator that dropped data on a guess about classification would be making a release decision invisibly, which is the gateway's job and not ours |
| `top_classification_probability` | `Entity.confidence` | `legion 1.0.0` | 0..1 and it is a confidence in the classification, which is what the field means. Absent → `None`, never 0.0: `confidence` 0 is certainty-that-not |
| `created_at` | `Event.received_at` | `legion 1.0.0` | when LEGION stored it — our delivery instant for a document, not the source's observation |
| `updated_at` | `Entity.attributes` | `legion 1.0.0 · parked` | a store-level mutation timestamp. Deliberately not `valid_from`: it says when the record changed, not when the world did |
| `deleted_at` | `Entity.valid_to` | `legion 1.0.0` | a soft-delete instant IS an interval end — maps exactly. Absent → `None` |
| `expires_at` | `Entity.valid_to` | `legion 1.0.0` | the same field, and the two can both be present. `deleted_at` wins when both are set, because a deletion is a fact and an expiry is a schedule; `attributes.valid_to_basis` records which was used |
| `is_active` | `Entity.attributes` | `legion 1.0.0` | `optional` boolean, parked. Not mapped to the `valid_from`/`valid_to` interval: a derived flag and an interval are two representations of one thing and the interval is the canonical one |
| `is_expired` | `Entity.attributes` | `legion 1.0.0` | `required` boolean, parked. Derivable from `expires_at`, so a disagreement between them is the source's to explain and not ours to resolve |
| `location_latest` | `Entity.position` · `Entity.kinematics` | `legion 1.0.0` | the embedded latest location, translated by the Location row set below. Embedded, so reading it is not a join |
| *(none — Legion states no symbol)* | `Entity.symbol` | `legion 1.0.0` | derived from the affiliation via `symbology.sidc_from_affiliation`; `attributes.symbol_basis` says so |
| *(derived)* | `Entity.valid_from` | `legion 1.0.0` | the embedded location's `recorded_at` where there is one, else `created_at`, with `attributes.valid_from_basis` naming which — the same fallback-and-record pattern the CoT adapter uses for `@start` |

#### The affiliation collapse, 15 → 4

Legion carries the full MIL-STD-2525 standard identity **and** an exercise marking in one enum.
The CDM separates the two on purpose, so this is a collapse in one axis and a **split** in the
other — the first source in this document to force both at once.

| Legion | `Entity.affiliation` | Why |
|---|---|---|
| `FRIEND` | FRIENDLY | |
| `HOSTILE` | HOSTILE | |
| `NEUTRAL` | NEUTRAL | |
| `UNKNOWN` | UNKNOWN | |
| `PENDING` | UNKNOWN | not yet judged; PENDING is a fusion state, not a wire fact |
| `ASSUMED_FRIEND` | UNKNOWN | an assumption is not an identification. **Not** FRIENDLY — that is the direction the collapse must not round towards |
| `SUSPECT` | UNKNOWN | suspicion is not identification. **Not** HOSTILE, for the reason the TAK adapter asserts in a test |
| `JOKER`, `FAKER` | HOSTILE | a friendly acting hostile in exercise; both are exercise-only and both are treated hostile, as the CoT letters `j`/`k` are |
| `NONE_SPECIFIED` | UNKNOWN | the source declining to state one |
| `EXERCISE_FRIEND` | FRIENDLY | |
| `EXERCISE_NEUTRAL` | NEUTRAL | |
| `EXERCISE_UNKNOWN` | UNKNOWN | |
| `EXERCISE_PENDING` | UNKNOWN | |
| `EXERCISE_ASSUMED_FRIEND` | UNKNOWN | |

The five `EXERCISE_*` values carry a second, orthogonal fact: this object is an exercise
participant. The CDM already has a home for that idea — the 2525D **context** digit, which
`symbology.sidc_from_affiliation()` takes as `synthetic` — but it does **not** overwrite
`source.synthetic`, and the distinction is deliberate:

- `source.synthetic` describes the FEED: is this an exercise system? It is a deployment
  declaration, set once at construction, and payload content may not rewrite it.
- `attributes.affiliation_exercise` describes the OBJECT: is this contact a simulated
  participant? A live Legion instance can legitimately hold both during a rehearsal.

Letting a payload field flip the feed-level flag would be an adapter making a decision about
provenance, which is exactly what adapters may not do. Both facts are recorded, separately, and
`attributes.affiliation_basis` says which vocabulary produced the UNKNOWN — as it already
distinguishes AIS's silence from CoT's collapse and ADS-B's unauthenticated claim.

### Entity Location and Track Location — one schema, and the CRS is the whole story

`GET /v3/entities/{entityId}/locations/{entityLocationId}` and the track equivalent return
byte-identical schemas.

| Legion | CDM field | Status | Notes |
|---|---|---|---|
| `id` | `Event.source_ids[].external_id` | `legion 1.0.0` | system `LEGION`; the report's own id, which is what makes a redelivered location recognisable |
| `entity_id` | `Event.related_entities[]` | `legion 1.0.0` | via `ids.derive`, a pure function of the id — deriving the CDM id is not a join, resolving the entity would be |
| `position.coordinates` + `crs` | `Position.lat` · `Position.lon` · `Position.alt_m` | `legion 1.0.0` | **the row that decides whether this adapter is correct at all — see the CRS section below** |
| `position.type` | `Event.geometry` | `legion 1.0.0` | `pattern: ^(Point|LineString|Polygon)$`. A `Point` becomes the Position and NO geometry; a LineString or Polygon has no `Position` at all and becomes `Event.geometry` instead, because a Position is a fix and an area is not |
| `crs` | `Entity.attributes` | `legion 1.0.0` | parked verbatim as well as consumed, because it is the evidence that the coordinates were read the right way round |
| `source` | `Entity.attributes` | `legion 1.0.0 · parked` | free-form string, example `"Helios"`. It names the *system* that produced the fix, NOT how the fix was obtained, so it may not become `Position.position_source` |
| *(derived)* | `Position.position_source` | `legion 1.0.0` | `ESTIMATED`, always, with a basis recording that Legion states a source SYSTEM and never a positioning method. Understating is the safe direction for the field a commander uses to tell a fix from a guess under jamming |
| `recorded_at` | `Event.observed_at` | `legion 1.0.0` | when the SOURCE recorded it. `optional`: absent, `created_at` is used and `payload.observed_at_basis` says so rather than implying the source stated it |
| `created_at` | `Event.received_at` | `legion 1.0.0` | when Legion stored it |
| `bearing` | `Kinematics.course_deg` | `legion 1.0.0` | degrees, `minimum: 0`, `maximum: 360`. **360 is reduced to 0** — the same bearing, and the only one `course_deg`'s `[0, 360)` range admits, exactly as the CoT adapter reduces `@course` |
| `speed` | `Kinematics.speed_mps` | `legion 1.0.0 · parked` | **units undocumented — see the ambiguity list. Parked at `attributes.speed_raw` and `speed_mps` left null** until the unit is confirmed. This is the ADS-B altitude lesson applied before the fact rather than after it |
| `velocity` | `Kinematics.speed_mps` · `.course_deg` · `.climb_mps` | `legion 1.0.0 · parked` | **gap 4** — a 3-vector, resolvable into the CDM's scalars by exact arithmetic, but the frame (ECEF or local ENU) and the units are both undocumented, and the answer differs completely between them. Parked whole |
| `acceleration` | `Entity.attributes` | `legion 1.0.0 · parked` | 3-vector; the CDM models no acceleration. Frame and units undocumented |
| `angular_velocity` | `Entity.attributes` | `legion 1.0.0 · parked` | **gap 7** — a turn rate, in the half of that gap AIS opened with its rate-of-turn byte. 3-vector, frame and units undocumented |
| `orientation` | `Entity.attributes` | `legion 1.0.0 · parked` | **gap 7** — a **quaternion** (example `[0.707, 0, 0, 0.707]`, unit norm), which is a heading and more. Component order is undocumented, so even the parked value cannot be interpreted here |
| `covariance` | `Position.accuracy_m` | `legion 1.0.0 · parked` | **gap 6** — a 3×3 matrix (example diagonal `[25, 25, 9]`, so variances in m²). NOT reduced to `accuracy_m`: that field is one horizontal 1-sigma figure, and collapsing a matrix in an undocumented frame into it would state a precision nobody measured |
| `radius` | `Position.accuracy_m` | `legion 1.0.0 · parked` | example `500`. Ambiguous between an uncertainty radius and a geometric extent (**gap 8**) and the spec never says which; parked under both readings' names until it does |
| `entity` | *(the Entity row set)* | `legion 1.0.0` | the embedded owning entity — a SUBSET of the full Entity schema (ambiguity 7), missing five fields the standalone endpoint returns: `classification`, `is_expired`, `location_latest`, `top_classification` and `top_classification_probability`. Note `metadata` is NOT among them — it IS present on the embedded block, and a hand-read of the spec got that wrong until the pinned inventory contradicted it. Translated by the rows above |
| `entity` (the five omitted fields) | `Entity.attributes` | `legion 1.0.0` | **STRUCTURALLY absent, and deliberately NOT in `unavailable_fields`.** That list means "the source stated it does not know"; these fields are missing because *this endpoint's schema does not contain them*, which is a fact about the API's shape and not a claim about the world. Conflating the two would manufacture five assertions of ignorance per document that Legion never made. Recorded instead at `attributes.embedded_entity_basis`, which names the five fields and says that the standalone entity endpoint carries them — so a consumer knows to fetch it rather than concluding the data does not exist |
| *(measured)* | `Entity.attributes` | `legion 1.0.0` | `attributes.unavailable_fields`, the sorted list of keys the API stated as `null` — never the ones it simply omitted |
| everything unmapped | `Entity.attributes` | `legion 1.0.0` | `attributes.source_extras`, structure intact |

#### The CRS, which is where this adapter is most likely to be wrong

`crs` is **optional**, its enum is `EPSG:4978 | EPSG:4326 | EPSG:4979`, and its
`default` — stated in the schema and confirmed in the prose — is **`EPSG:4978`, which is
Earth-Centred Earth-Fixed X/Y/Z in metres from the centre of the Earth.** The schema's own
example is `[4517590.87, 0, 4487348.41]`: a vector of magnitude 6.37 × 10⁶ m, i.e. a point on
the Earth's surface expressed geocentrically.

So **the default coordinate system is not latitude and longitude**, and an adapter that read
`coordinates` as `[lon, lat]` — the reasonable guess, given the GeoJSON-shaped `{type,
coordinates}` object — would place every contact at a nonsensical coordinate while producing
perfectly well-formed CDM objects. This is the single largest hazard in the row set, and it is
why `crs` is consumed AND parked.

**`Position` is therefore a DERIVED, ONE-WAY VIEW of the source coordinates, and the source
coordinates are the record.** `position.coordinates` and `crs` are re-emitted into
`attributes.legion_position` **verbatim** — the same numbers, in the same order, under the same
CRS name — and the geodetic `Position` is computed beside them, never instead of them. Three
reasons, and the third is the one that makes it a rule rather than a preference:

1. A conversion is a claim, and the claim should sit next to its input. A consumer that
   disagrees with our arithmetic, or that wants the geocentric frame for its own geometry, has
   the original rather than a round-tripped approximation of it.
2. The never-drop rule is satisfied by *presence* rather than by a declared exemption, so
   `TRANSFORMS` does not have to carry the coordinate conversion at all. An exemption is a hole
   with a reason attached; a verbatim copy is not a hole.
3. **ECEF → geodetic → ECEF is not the identity in floating point.** Round-tripping through
   latitude, longitude and height loses low-order millimetres, and an adapter whose only copy of
   the position had been through that conversion could never prove it had not moved a contact.

The transform is named rather than implied: **ECEF → geodetic on the WGS84 ellipsoid**
(`a = 6378137.0 m`, `1/f = 298.257223563`), by the closed-form Bowring/Ferrari solution — no
iteration, so the result is a deterministic function of the input and a golden file means
something. `attributes.position_basis` records the CRS that was read, the transform that was
applied and the ellipsoid it was applied on, on every position this adapter produces. An
`EPSG:4326` document states geodetic coordinates already and its basis says "no conversion".

This adapter is **ingest only** — there is no `from_cdm()` — so "one-way" is a property of the
mapping and not merely of this release: nothing in the CDM is ever converted back into a Legion
document, and the row set makes no claim that it could be.

The three cases, and the one that cannot be handled:

| `crs` | Coordinates | Handling |
|---|---|---|
| absent or `EPSG:4978` | `[X, Y, Z]` metres, geocentric | converted to geodetic lat/lon/height on the WGS84 ellipsoid — a declared transform, exact to floating point and reversible |
| `EPSG:4326` | `[longitude, latitude, altitude]` per the prose | used directly; note this is GeoJSON axis order and NOT the EPSG registry's axis order for 4326, which the prose overrides for this API |
| `EPSG:4979` | **undefined** | **REFUSED.** In the enum, defined nowhere. Its registry axis order is (latitude, longitude, height) — the reverse of what this API documents for 4326 — so the two readings differ by a transposition that yields a plausible wrong position rather than an error. Logged, not guessed |

Note also that `{type, coordinates}` plus a `crs` sibling is **GeoJSON-shaped but not GeoJSON**:
RFC 7946 fixes the CRS as WGS84 lon/lat and forbids a `crs` member outright. The CDM's own
`geo.py` is RFC 7946, so a Legion `position` may not be passed into it unconverted.

### Legion Event

Ten fields, no geometry, and no position — which is the whole reason it is a separate row set.

| Legion | CDM field | Status | Notes |
|---|---|---|---|
| `id` | `Event.source_ids[].external_id` | `legion 1.0.0` | system `LEGION` |
| `organization_id` | `Event.payload` | `legion 1.0.0` | parked, as on the Entity |
| `source_id` | `Event.related_entities[]` | `legion 1.0.0` | `required` uuid: the entity the event is about. Derived, never resolved |
| `actor_id` | `Event.payload` | `legion 1.0.0` | who caused it, `optional` uuid. Parked and NOT put in `related_entities`: the actor is not the subject, and merging them would make a user look like a contact |
| `actor_type` | `Event.payload` | `legion 1.0.0` | enum `USER \| ENTITY \| OTHER`. Parked, and the reason the actor stays out of `related_entities` — a `USER` is not a CDM object at all |
| `event_type` | `Event.payload` | `legion 1.0.0 · parked` | enum `HUMAN \| VEHICLE \| VESSEL \| UAV \| FOOTSTEP \| ANIMAL \| GUNSHOT \| OTHER`. **These are detection CLASSES, not event types** — the name collides with `EventType` and means something else entirely, so it is parked and never mapped to it |
| *(derived)* | `Event.event_type` | `legion 1.0.0` | `DETECTION`. Legion's own `event_type` says WHAT was detected, so the CDM's axis — what kind of report this is — has to be supplied, and `DETECTION` is what a classified observation is |
| `event_description` | `Event.payload` | `legion 1.0.0` | free text, `optional`. No canonical home by design |
| `event_timestamp` | `Event.observed_at` | `legion 1.0.0` | when it happened, `required` |
| `created_at` | `Event.received_at` | `legion 1.0.0` | when Legion stored it |
| `metadata` | `Event.payload` | `legion 1.0.0` | a bare `type: object` with no declared properties — free-form, parked whole with its structure intact |
| *(none — Legion states no severity)* | `Event.severity` | `legion 1.0.0` | `INFO`, with `payload.severity_basis` recording that the format is silent. A `GUNSHOT` is not graded here: that is fusion judging operational significance, and the line sits where AIS's does — at the source's own explicit alarm, which Legion has none of |
| *(none)* | `Event.geometry` | `legion 1.0.0` | `None`. A Legion Event carries no position whatsoever, and taking one from the entity it names would be both a join and an invention |

### The list envelope, which becomes a Track

| Legion | CDM field | Status | Notes |
|---|---|---|---|
| `results[]` | `Track.samples[]` | `legion 1.0.0` | in payload order, which the CDM validates as non-decreasing. A page that arrives out of order is refused rather than sorted: sorting would hide a source defect the caller needs to see |
| `results[].position` + envelope `crs` | `Track.samples[].position` | `legion 1.0.0` | the envelope's `crs` applies to every result; the per-item `crs` overrides it where present |
| `results[].recorded_at` | `Track.samples[].observed_at` | `legion 1.0.0` | falling back to `created_at`, as on a single location |
| `crs` | — | `legion 1.0.0` | **there is no `Track.attributes`** — `Track` has no extension bag at all, unlike `Entity` and `Event`. So the envelope's `crs` and `paging` are parked on the **Entity** the track belongs to, which is the object that has one — recorded here because it is a real consequence of the model's shape |
| `paging.has_more` | `Entity.attributes` | `legion 1.0.0` | parked so a consumer can see that the history is partial. `optional`, unlike its two siblings, so its absence is not a claim that there is no more |
| *(computed)* | `Entity.attributes` | `legion 1.0.0` | `attributes.legion_track_completeness` — see the completeness section below. The one place a consumer can machine-read how much of a history it is holding |
| `paging.next` | `Entity.attributes` | `legion 1.0.0` | `required`, integer or `null` — an offset page cursor. `null` means no next page and lands in `unavailable_fields`; the adapter parks it and never follows it |
| `paging.previous` | `Entity.attributes` | `legion 1.0.0` | `required`, integer or `null`, on the same terms |
| `total_count` | `Entity.attributes` | `legion 1.0.0` | `optional` integer, the full size of the collection this page is a window on. Parked, and it is the field that makes a partial Track *measurably* partial: a consumer can compare it against `len(samples)` rather than guessing |
| *(derived)* | `Track.track_id` | `legion 1.0.0` | `ids.derive` over the entity id plus the page's first and last sample instants — NOT the entity id alone, or every page of one entity's history would collapse into one track id |
| *(none)* | `Track.track_quality` | `legion 1.0.0` | `None`. Legion states no track quality; `top_classification_probability` is a classification confidence and a different claim |

### Completeness of a partial history must be machine-visible — and where it can live

A `Track` built from one page is a fragment of a history, and a consumer that cannot tell a
fragment from a whole history will compute a speed across a gap it does not know is there. So the
figures that answer "how much of this is here?" are recorded rather than left implicit:

| Key | From | Meaning |
|---|---|---|
| `total_count` | the envelope, `optional` | how many locations the collection holds in total |
| `carried_samples` | computed — `len(results)` | how many reached this `Track` |
| `complete` | computed | `true` only when `total_count` is stated AND equals `carried_samples` AND `paging.has_more` is not true. Any missing input makes it `null`, never `false`: "we cannot tell" and "we can tell it is partial" are different answers |
| `paging` | the envelope | `has_more`, `next`, `previous`, verbatim |
| `track_id` | computed | the `Track` these figures describe, so the association survives being read from the Entity |

**They are recorded on the `Entity`, not on the `Track`, and that is a limitation rather than a
preference.** `Track` has no extension bag: its fields are `track_id`, `entity_id`, `samples` and
`track_quality`, plus the provenance block every kind carries. There is nowhere on it to put a
count, and the three alternatives were all worse —

- `track_quality` is a 0..1 assessment of how good the track is, not how much of it arrived.
  Writing a completeness ratio there would be a false statement in a field consumers act on.
- Truncating `samples` or refusing a partial page would discard real data to express a caveat.
- Inventing a key on `Track` is impossible: the model is `extra="forbid"`, by design.

So this adapter emits the `Entity` alongside the `Track` in every list translation — which it
must do anyway, since the CDM has no way to state a track without the entity it belongs to — and
the figures ride in `Entity.attributes.legion_track_completeness`, keyed by `track_id`. A
consumer holding both objects can machine-read completeness; a consumer holding **only** the
`Track` cannot, and that is a real limit of the model as it stands rather than something this
adapter can fix. It is the strongest argument yet for a `Track.attributes` bag, and it is
recorded as a 1.1.0 candidate in `MIGRATIONS.md` rather than acted on here, because adding a bag
to a canonical object is a schema change and this adapter ships at `schema_version 1.0.0` with
none.

### Where the pinned spec is ambiguous or contradicts itself

Eight findings, recorded because an adapter author will hit every one of them and because the
ADS-B lesson was that a plausible inference is worse than a logged gap. **Each is a question for
the vendor, not a decision for us**, and the row set above handles each by parking rather than
guessing.

| # | Finding | Consequence for the adapter |
|---|---|---|
| 1 | **`crs` is optional and its default is ECEF.** `EPSG:4978` — geocentric X/Y/Z metres — is the stated default, so a `position` with no `crs` is NOT lat/lon. The object is shaped like GeoJSON (`{type, coordinates}`), which invites exactly the wrong reading | the largest hazard in the row set. `crs` is consumed AND parked; an omitted `crs` means ECEF and is converted, never passed through |
| 2 | **`EPSG:4979` is in the enum and defined nowhere.** The prose companion documents 4978 and 4326 only. The EPSG registry's axis order for 4979 is (lat, lon, h), the reverse of the order this API documents for 4326 | REFUSED by name. A transposition yields a plausible wrong position, which is the failure mode that cannot be detected downstream |
| 3 | **No units on any scalar or vector.** `speed`, `velocity`, `acceleration`, `angular_velocity`, `orientation` and `radius` carry an example and no description, and no page in the documentation states a unit for any of them | `speed` is parked rather than written to `speed_mps`; the vectors are parked whole. This is the ADS-B altitude mistake declined in advance |
| 4 | **`speed` and `velocity` examples contradict each other.** `speed` is `2.236`; `velocity` is `[42.5, -3.1, 0]`, whose magnitude is `42.61`. If `speed` were the magnitude of `velocity` the units would be inferable — they are not, and the two cannot both be right about the same instant | closes the one route to inferring the units. The contradiction is the evidence that inference is unsafe here |
| 5 | **`classification` is declared `type: object` with the example `"2023-12-15T14:30:00Z"`.** An object cannot be that string, and the example is a timestamp unrelated to anything called a classification | parked verbatim whatever arrives, and never parsed as either a timestamp or an object. Its relationship to `top_classification` is also unstated |
| 6 | **No timestamp in any in-scope resource carries `format: date-time`.** The annotation is used 160 times in the document — exclusively on the `timestamp` field of 5xx error envelopes. All 15 timestamps on Entity, Location, Event and TaskStatus are bare `type: string` | timestamps are parsed permissively (`times.parse` already does) and re-emitted verbatim rather than re-rendered, so an unexpected form survives instead of being normalised into a lie |
| 7 | **The embedded `entity` is a subset of the Entity resource.** The `entity` block inside a Location omits `is_expired`, `top_classification`, `top_classification_probability`, `classification`, `metadata` and `location_latest`, which the standalone Entity endpoint returns. Two endpoints, one resource, different shapes — a direct consequence of `components.schemas` being empty and every schema inlined | the absent fields are ABSENT, not null: nothing is invented to fill them, and they do not enter `unavailable_fields` because the API made no claim about them |
| 8 | **`info.version` does not move when the API does.** It has read `3.0.0` across the docs snapshot of 2026-05-21 and this retrieval, while the paths beneath it demonstrably change — the tasking documentation describes a bulk endpoint superseding a legacy URL "kept because deployed clients have this URL baked in" | the SHA-256 is the change signal and the version string is not. `openapi_pin.json` records both, and the ETag makes a re-check cheap |

Two further oddities that are not ambiguities but are worth knowing: the commercial server listed
in `servers` returns `404` for `GET /v3/openapi.json`, so the spec is retrievable from the
govcloud host only; and `Entity.metadata`'s own example carries an IP address, which makes that
field data about our estate rather than about the world — it is parked, and a deployment may
want it filtered before the CDM object leaves the enclave.

### Deliberately out of scope, and why — each named individually

| Resource | Decision |
|---|---|
| **Tasking** (`POST /v3/tasking`, task status, command registration, MQTT topics) | **The highest-value omission, and the reason is structural.** The tentative mapping was Tasking → `PlanObject` egress, and it does not hold: `PlanObject.geometry` is REQUIRED, and a task has no geometry at all — its fields are `entity_id`, `command_name`, `qos` and a free-form `payload`. `PlanObject` is a *drawing*; a task is an *imperative*. Emitting one would mean inventing geometry, which is the exact failure that field's requiredness exists to prevent. And the deeper reason: golden rule 4 keeps a human on the loop for anything that acts, so an adapter that could emit a command is an adapter that can act. If tasking is ever wanted, it needs a CDM object that does not exist yet and an authority model, not a `PlanObject` with a fabricated point |
| **Feed Data** (`/v3/feeds/**`) | Deferred, not rejected — the most likely next addition. A feed data item is `{entity_id, feed_definition_id, payload, recorded_at, received_at, blob_*}` where `payload` is an arbitrary JSON object whose shape is declared by a *separate* Feed Definition resource. Translating one means either parking an opaque blob — which the never-drop rule already achieves without a row set — or fetching and interpreting its definition, which is a cross-resource join and a second registry. Same category as AIS's DAC/FI application identifiers |
| **Feed file data / blob download** | Binary payloads behind a blob key. The CDM models no attachment, and a `blob_key` parked without its bytes is a dangling reference — worse than an absent field, because it looks resolvable |
| **Detection feedback** (`/v3/feeds/data/{id}/detections/{id}/feedback`) | Human adjudication of a detection. It is training-loop data about a *judgement*, not an observation of the world; the CDM has no object for it and inventing one would put an opinion in the entity graph |
| **Video streams, recordings, HLS playlists, signed download URLs** | Media transport. No CDM object, and the signed-URL endpoints mint short-lived capabilities — a credential-adjacent surface an adapter has no business touching |
| **WebRTC connections** (`/v3/me/webrtc/**`) | Session plumbing for the video path. Describes a browser's connection, not the world |
| **Notifications, deliveries, receipts, event subscriptions and channels** | The alerting *mechanism*: who was told, over which channel, and whether they read it. These are objects about the notification system. A CDM object built from one would describe our own message bus, and the CDM does not model that — correctly absent rather than missing |
| **Permissions, authorization, audit trail, templates, trees** | Access control. `POST /v3/authorization/permissions/check` answers a question about a subject's rights; there is no entity, no event and no position in any of it |
| **OAuth, JWKS, token introspection, integration manifests, Keycloak registration** | Auth plumbing. Also the boundary this adapter refuses on principle: transport and credentials stay with the caller |
| **Federation** (`/v3/federation/**`, CA bundles, Nebula certs, enroll/renew/revoke) | Overlay-network identity between Legion instances. It describes the mesh, and it handles certificates — the CDM contains no crypto by an AST-enforced rule (`tests/test_cdm_boundary.py`), so this could not be modelled here even if it were wanted |
| **Users, organizations, invitations, `/v3/me`, Orion settings** | Tenancy and identity. A user is not a thing on a map. `organization_id` is parked where it appears on an in-scope resource, and the org resource itself stays out |
| **Search endpoints** (`POST /v3/*/search`) | Not a resource: a query interface returning the same objects the row sets above cover, wrapped in the same envelope. In scope by their *response*, out of scope as an *operation* — the adapter translates what a search returned and knows nothing about the filter that produced it |
| **`EPSG:4979` coordinates** | Not a resource, but the same decision. In the `crs` enum and defined in no document; its registry axis order contradicts what this API documents for `EPSG:4326`, so a guess yields a plausible wrong position. Refused by name until a source defines it |

## ASTERIX Category 021 — ADS-B Target Reports, ingest and egress

Implemented by `adapters/asterix_cat021.py` (bidirectional). Ingest translates one ASTERIX
**data block** into an `Entity` + an `Event` **per record**; egress turns Entities, or a Track,
back into one data block. The left column names data items as the specification numbers them;
the parsed form the adapter's own parser produces is what each `.parsed.json` fixture holds and
what the never-drop check is measured against.

**Every row below was written and reviewed as a specification BEFORE any code existed**, with
`not yet` in the status column, exactly as the Legion row set was. The markers now read
`cat021 1.0.0` because the adapter runs them, and that difference is the whole reason the status
column exists. Two decisions changed during implementation and both are noted where they
happened: `from_cdm()` had to accept MANY Entities, because a data block holds N records and the
byte-exact claim is about a BLOCK; and the fixtures' System Area Code moved from `0xFE` to
`0x29` when the allocation list was pinned and `0xFE` turned out to be Nicaragua.

The closest relative is `adapters/adsb.py`, and the relationship is worth stating precisely
because it is not "a second ADS-B adapter". **Same underlying data, different wire format, and
one hop of processing in between.** 1090ES is what an aircraft broadcasts; ASTERIX CAT021 is
what a ground station emits after it has received those broadcasts, CPR-decoded the position,
validated it, correlated the type codes into one target report and added its own quality
assessment. So three of the four hard problems in the ADS-B adapter are simply gone here — the
position arrives already decoded, the frame types arrive already merged, and the format states
times — and they are replaced by different ones: a time with no date, a quality vocabulary whose
meaning depends on a version number in another item, and a ground station that has already made
judgements this adapter must carry without repeating or re-deciding.

### The pin

CAT021 is a ratified EUROCONTROL specification, so unlike Legion it does not need a hash to be
trustworthy — a released edition is a fixed document that moves on committee timescales and in
public. The hashes are recorded anyway, for the reason `airtasking/SOURCES.md` records them: an
edition number names a document and a SHA-256 names the **copy that was read**, and those are
different claims.

| | |
|---|---|
| Category | **021** — ADS-B Target Reports |
| Core specification | EUROCONTROL-SPEC-0149-12, ASTERIX Part 12 Category 021, **Edition 2.6**, 21 December 2021, Released |
| SHA-256 (core) | `c30bab5f6b8fc1ef45ae5e5c24d76312ea571e26f32f8ef81ffcc730e0aa87ab` |
| Expansion appendix | EUROCONTROL-SPEC-0149-12-A, Appendix A Reserved Expansion Field, **Edition 1.5**, December 2021, Released |
| SHA-256 (REF) | `5de1f887485d370a9117e5549bdaeeb58a521aa88acc1b0adbb636be9c9fe193` |
| ASTERIX Part 1 | Edition 3.1, November 2021 — the applicable document for the "Element Populated" convention the REF uses |
| ADS-B MOPS covered | Versions 0, 1 and 2 in full; Version 3 (ED-102B / DO-260C) **partially**, and mostly in the REF |

Ed 2.6 states on its own cover that it is **NOT backwards compatible to Edition 2.1 or earlier**,
and Ed 2.2 changed the structure of I021/271 incompatibly. The edition is therefore part of the
mapping and not a footnote: a row set written against Ed 2.1 would decode I021/271 wrongly and
every other check would pass.

### The REF is IN SCOPE for 1.0.0 — decided, not deferred

The question is a real one because the Reserved Expansion Field is optional, is a second
document, and its largest subfield (MES) is military-specific. It is in scope anyway, and the
reason is not completeness — it is that **the core specification relocates two things into the
REF that a CAT021 adapter cannot be correct without.**

1. **A Version 3 aircraft's emergency lives in the REF.** I021/200's Priority Status was
   redefined in ADS-B Version 3, and the core spec's own note says that for Version 3 systems
   "the Priority Status shall be encoded in the Reserved Expansion Field, Item STA, Primary
   Subfield" — i.e. in `STA` first extension `PS3`. An adapter that skipped the REF would
   translate a Version 3 aircraft squawking *unlawful interference* as a record with no
   emergency at all. A silently missing emergency is the worst failure available in this format,
   and it is not hypothetical: it is what happens by default on Version 3 equipment.
2. **A surface target has no ground vector without the REF.** I021/160 is the *Airborne* Ground
   Vector, and its own note says "The Surface Ground Vector format is defined in the Reserved
   Expansion Field in the subfield SGV". So without the REF, every aircraft and vehicle on a
   movement area reports a position and no motion whatsoever — `Kinematics` would be `None` on
   exactly the targets where a metre matters most.

A third reason is smaller but decides the shape of a CDM gap rather than of this adapter:
**CAT021 carries a magnetic heading (I021/152) and a true-north heading (REF `TNH`) as two
separate items.** That is the first source in this document to state a heading *and* its datum
unambiguously, which is precisely what gap 7 grew a requirement for when ADS-B showed that a
bare `heading_deg` would hold two different measurements. Parking the REF would have thrown away
the one piece of evidence that answers the open question.

**What is in scope is the whole REF**: `BPS`, `SelH`, `NAV`, `GAO`, `SGV`, `STA` (primary plus
all five extensions), `TNH` and `MES` (primary plus all six subfields). Nothing is skipped, so
the never-drop rule is satisfied by presence rather than by an exemption. What is *declined* is
one act of interpretation, and it has its own section below: **an authenticated Mode 5 reply is
not read as an affiliation.**

### What the adapter's input IS — one data block, and nothing else

`to_cdm()` takes **one ASTERIX data block**: the octets from the `CAT` byte through the last
record, and nothing else. The boundary is drawn where it was drawn for AIS, ADS-B and Legion.
The adapter does not own, and must never acquire, a socket, a UDP reassembly buffer, a multicast
group, a stream framer or a station configuration it discovered from the data.

The accepted forms are the raw octets, or the already-parsed dict a fixture twin holds — the
same `bytes | dict` shape `adsb.py` accepts, for the same reason: the harness's lossless check
has no leaves to harvest from bytes.

| Input | Becomes |
|---|---|
| a data block holding one record | `Entity` + `Event` |
| a data block holding N records | N × (`Entity` + `Event`), in block order |
| a data block holding zero records | a refusal — see the wire-form rules |

**A data block never becomes a `Track` on ingest.** Several records in one block are several
target reports, not one target's history: they may name different aircraft, and nothing in the
format says otherwise. Building a `Track` from the records that happen to share a Target Address
would be a correlation decision made inside a translator — the type-24 / CPR / pagination test,
applied a fourth time. `Track` appears only in the egress direction, where the caller has already
decided that a history is a history.

### The wire form

#### Data block

    CAT (1 octet, = 21) | LEN (2 octets, big-endian) | FSPEC + items (record 1) | ... | FSPEC + items (record N)

`LEN` is the total length in octets **including CAT and LEN**. Three structural refusals, each
raising with the offending octets quoted and none of them falling back to a best-effort read:

- **`CAT` ≠ 21.** This adapter speaks one category. A CAT062 or CAT048 block decoded against the
  CAT021 UAP yields a plausible wrong aircraft, not an error.
- **`LEN` disagrees with the buffer length.** Reading to the end of the buffer instead would
  translate whatever followed the block as if it were part of it.
- **The last record does not end exactly on `LEN`.** A trailing partial record means the parse
  desynchronised somewhere earlier, so every field already decoded is suspect. Refuse the block,
  never emit the records parsed before the discrepancy — a partial object is forbidden by the
  `Adapter` contract, and so is a partial *set* of objects that looks complete.

#### FSPEC

One or more octets. Bits 8..2 signal the presence of the next seven Field Reference Numbers in
UAP order; bit 1 is `FX`, set when another FSPEC octet follows. Forty-nine FRNs means at most
seven octets. Items then appear **in FRN order**, back to back, with no separators and no
lengths of their own except where the item's own format carries one.

- **FRN 43–47 are "Not Used" in the CAT021 UAP.** A set bit there is a refusal: there is no item
  to decode, so skipping it is impossible and guessing a length would desynchronise every
  following item in the record.
- **A set FSPEC bit with no octets left in the block** is a refusal, quoting the FRN.
- **The FSPEC octets are parked verbatim.** A conforming encoder emits the shortest FSPEC that
  covers its highest set FRN, but the specification does not forbid a longer one, and the round
  trip is only byte-exact if the FSPEC we emit is the FSPEC we read.

#### Item format kinds, all five of which CAT021 uses

| Kind | Shape | Items |
|---|---|---|
| **Fixed** | exactly N octets | most of them — I021/010 (2), I021/080 (3), I021/130 (6), I021/131 (8), I021/140 (2), … |
| **Variable** | one octet, `FX` in bit 1, extending one octet at a time | I021/040, I021/090, I021/271, REF `SGV`, REF `STA` |
| **Repetitive** | one-octet `REP` count, then REP × a fixed block | I021/110 subfield #2 (REP × 15 octets), I021/250 (REP × 8 octets) |
| **Compound** | a primary subfield of presence bits (itself `FX`-extensible), then the present subfields in bit order | I021/110, I021/220, I021/295, REF `MES` |
| **Explicit** | one-octet length **including the length octet itself**, then opaque contents | RE (FRN 48) and SP (FRN 49) |

Two traps worth naming because both are the kind that decode into plausible nonsense rather than
into an error. A **variable** item's extension count is data-dependent, so a decoder that assumed
one octet would read the next item's first octet as an extension and shift everything after it.
And a **compound** item's primary subfield is itself `FX`-extensible — I021/295's is up to four
octets — so the presence map has to be read to its own end before any subfield is consumed.

#### Spare and unused bits are parked verbatim, never normalised

§4.3 says decoders "shall never assume and rely on specific settings of spare or unused Bits" and
that zeroing them is a *recommendation*. So a real encoder may set them to anything, and an
adapter that normalised them to zero would break the byte-exact round trip on exactly the traffic
most worth investigating. Every spare and unused bit is parked as sent, as the AIS adapter parks
its spare and reserved bits — "they carry no meaning today and are the bits a regional authority
allocates tomorrow".

#### Multiple records per data block — and why ADS-B's two-frame refusal does not carry over

`adsb.py` refuses a payload holding two frames outright, because accepting them would smuggle a
CPR even/odd pair in through the framing and let the adapter do a global position decode it has
declared out of scope. **That reasoning does not transfer, and it is worth saying why rather than
appearing to relax a rule.** A CAT021 record carries a fully decoded WGS-84 latitude and
longitude: the ground station did the CPR pairing, upstream, where its own validation flags
(I021/040 `CPR`, `LDPJ`, `IPC`, `RC`) record that it did. There is no join left for two records
to smuggle, so translating all of them is reading, not correlating — the same line the AIS
adapter draws when it reassembles the fragments *present in one payload* while refusing to buffer
across payloads.

### There is no CRC here, and what replaces it

The single strongest gate in the ADS-B adapter is the 24-bit parity: a frame that fails is
refused, never best-effort decoded, because a bit flip in the ME field moves an aircraft rather
than failing to parse. **ASTERIX has no checksum at any level** — no CRC on the data block, none
on a record, none on an item. Whatever integrity the link has belongs to the transport below it.

So the gate is structural instead, and it is deliberately strict for the same reason the CRC one
is: a length or an FSPEC that does not add up is the only evidence available that a record was
corrupted. The block must satisfy `LEN`; the records must tile it exactly; every FSPEC bit must
name a defined FRN; every variable item must terminate on an `FX` of 0 inside the record; every
repetitive item's `REP` must fit; every compound item's subfields must all be present; and the
four items the specification says shall be present in every record — I021/010, I021/040, I021/080
and I021/090 — must be there. A record failing any of those is refused with the offending octets
quoted.

This is weaker than a CRC and the difference is named rather than smoothed over: a single bit
flipped inside a fixed-length field satisfies every structural check and reaches the CDM as a
measurement. `attributes.integrity_basis` therefore records, on every object, that CAT021 carries
no checksum and that the structural gate is what passed — so a consumer comparing a CAT021
contact against a 1090ES one knows which of the two was checked and which was only parsed.

### Time: the format states a time of day and never a date

This is the largest single difference from 1090ES, and it runs the opposite way to the obvious
expectation. ADS-B carries **no time at all**, so `observed_at` is the receipt instant and the
basis says so. CAT021 carries **seven** time items — and not one of them carries a date.

| Item | What it is | Encoding |
|---|---|---|
| I021/071 | Time of Applicability for **Position** | 24 bits, elapsed time since last midnight UTC, LSB 1/128 s |
| I021/072 | Time of Applicability for **Velocity** | 24 bits, since last midnight UTC, LSB 1/128 s |
| I021/073 | Time of Message Reception for **Position** (at the ground station) | 24 bits, since last midnight UTC, LSB 1/128 s |
| I021/074 | TOMRp **high precision** | 32 bits: 2-bit `FSI` whole-second correction to I021/073, then a 30-bit fraction, LSB 2⁻³⁰ s ≈ 0.93 ns |
| I021/075 | Time of Message Reception for **Velocity** | 24 bits, since last midnight UTC, LSB 1/128 s |
| I021/076 | TOMRv **high precision** | as I021/074, against I021/075 |
| I021/077 | Time of **ASTERIX report transmission** | 24 bits, since last midnight UTC, LSB 1/128 s |

`FSI` is not a rounding hint and must not be read as one: `00` means the high-precision whole
seconds equal I021/073's, `01` means they are I021/073's **plus one**, `10` means **minus one**,
and `11` is reserved. Ignoring it puts the fix a whole second out at exactly the moment the
ground station took the trouble to say it was near a second boundary. A `FSI` of `11` is
reserved: the high-precision value is discarded to `unresolved_raw` and the plain I021/073 is
used, because a reserved code has no defined correction and applying one of the other three would
be a guess with a nanosecond's worth of false authority on it.

#### The reference date comes from the injected clock, and the adapter never reads the wall clock

A time of day is not an instant. Something has to supply the date, and there are only two
candidates: the payload, which does not carry one, or us.

So the date is taken from `self.now()` — the injected clock, exactly as `received_at` is, and
never `datetime.now()`. That keeps golden-output tests possible and makes the adapter's behaviour
a pure function of (payload, clock). It is the AIS construction generalised: AIS states a
second-of-minute and no date, and `ais.py` resolves it to "the instant bearing that second
nearest the receipt time", recording both halves in `payload.observed_at_basis`. Here the same
rule resolves a time-of-day against the receipt date.

#### Midnight rollover falls out of "nearest", in both directions

Every one of these counters "is reset to zero at every midnight". The rule is therefore: the
candidate instants are the stated time of day on the receipt date, the day before and the day
after; the one **nearest the receipt instant** wins.

- A report timestamped `23:59:58.500` delivered at `00:00:01.100` on the following day resolves
  to the **previous** day, which is right — picking today's date would date it 24 hours late.
- A report timestamped `00:00:00.900` delivered at `23:59:59.700` resolves to the **next** day,
  which is the same rule run the other way and is what a ground station clock a fraction ahead of
  ours produces.

`payload.observed_at_basis` names the item that supplied the time of day, the date the clock
supplied, and — where the nearest candidate was not the receipt date — that a rollover was
applied. A rollover is a decision about which day a contact was seen on, and a decision nobody
can see afterwards is not a decision.

**A value at or beyond 86 400 s is a refusal, not a modulo.** Twenty-four bits at 1/128 s reach
131 071.99 s, so the field can express times of day that do not exist. The specification says the
counter resets at midnight, so such a value is a corrupt field or a non-conforming encoder;
taking it modulo 86 400 would move a contact by hours and leave every other check passing. The
refusal quotes the item, the raw 24-bit integer and the decoded seconds.

#### Which item becomes `observed_at`, and the one it must never become

`Event.observed_at` is "when the SOURCE saw it", so the chain is, in order, and with the step
that was taken recorded in `payload.observed_at_basis`:

1. **I021/071**, time of applicability of the position — the aircraft's own synchronised
   measurement instant. The best answer the format has.
2. **I021/073** (refined by I021/074 where present), time of message reception of the position at
   the ground station. Not the aircraft's instant, but a stated time about the position rather
   than about the report. The specification guarantees one of 071 or 073 in any record conveying
   position, so a positional record never falls past this step.
3. **I021/072**, then **I021/075** (refined by I021/076), for a record carrying velocity and no
   position.
4. **I021/077**, the ground station's own report transmission time — a source-stated time, but
   about the *report* and not about the observation, which is why it is last.
5. The injected clock, with the basis stating that the record carried no time item at all.

`Event.received_at` is the injected clock, always. It is the one field an adapter invents rather
than reads, and it is never any of the seven items above — I021/073 in particular is a receipt
time *at the ground station*, which is a different party than us and a different instant.

#### One record, two measurement times — and the CDM has one

A record can carry a position applicable at T₁ and a velocity applicable at T₂, and CAT021 states
both. `Entity` carries one `position` and one `kinematics` with no time on either, and `Event`
carries one `observed_at`. **So the CDM cannot express that the two were measured at different
instants**, and this adapter's `observed_at` follows the position, because the fix is the thing
on the map. The velocity times are parked and the offset is computable from them.

I021/295 **Data Ages** makes this worse and is the reason it is recorded as a gap rather than as
a quirk: twenty-three subfields, each stating in units of 0.1 s how old one specific item is —
the geometric height, the ground vector, the target identification, the target status and twenty
more. The format is telling us, per field, exactly how stale each figure is, and there is nowhere
canonical to put any of it. See **gap 13**.

#### The high-precision items do not fit a CDM `Timestamp`, and that is not a defect

`times.render` emits exactly three decimal places, deliberately. I021/074 states 2⁻³⁰ s ≈ 0.93 ns
and even the ordinary items state 1/128 s = 7.8125 ms, which is not a whole number of
milliseconds — so three units of I021/071 is 23.4375 ms and renders as `.023`.

The consequence is a rule and not a caveat: **the raw wire integers are parked, and egress
re-emits from the park rather than recomputing from `observed_at`.** This is the Legion
verbatim-timestamp finding and the Legion ECEF finding wearing one hat — a canonical value
computed from a source value is a derived, one-way view, and the source value is the record.
Recomputing an I021/074 from a millisecond timestamp would silently zero twenty of its thirty
fractional bits and the round trip would report it.

### Position

| | I021/130 | I021/131 |
|---|---|---|
| Length | 6 octets | 8 octets |
| Latitude | 24-bit two's complement, LSB 180/2²³ | 32-bit two's complement, LSB 180/2³⁰ |
| Longitude | 24-bit two's complement, LSB 180/2²³ | 32-bit two's complement, LSB 180/2³⁰ |
| LSB in degrees | ≈ 2.145 767 211 914 06 × 10⁻⁵ | ≈ 1.676 380 634 307 8 × 10⁻⁷ |
| Stated resolution | at least **2.4 m** | at least **2 cm** |
| Range | −90 ≤ lat ≤ 90, −180 ≤ lon < 180 | identical |

Both are **WGS-84 already**, which is the whole reason this is a two-line decision where Legion's
took a section: there is no datum conversion, no ellipsoid to name and no axis-order trap. The
only transform is the scaling by the LSB, and it is exact in binary.

**The source coordinates are the record, and `Position` is a derived, one-way view of them** —
the same rule Legion's `position_basis` establishes, applied here for a different reason. The raw
two's-complement integers, the item they came from and the LSB are re-emitted verbatim into
`attributes.cat021_position`, and `attributes.position_basis` records which item was read, the
LSB applied and that no datum conversion was performed. A consumer that disagrees with our
arithmetic has the integers; and an integer scaled to a float and back is not the identity, so an
adapter whose only copy of the position had been through that conversion could never prove it had
not moved a contact.

**When both items are present, I021/131 wins.** The encoding rule says "either I021/130 or
I021/131 shall be sent", but both sit in the UAP at FRN 6 and 7 and a non-conforming encoder can
set both bits, so the case has to have an answer. The high-resolution item is strictly more
precise, so it is the one read; both are parked; and if the two disagree by more than one
I021/130 LSB — which is more than rounding can explain — the discrepancy is recorded at
`attributes.position_disagreement_deg` rather than quietly resolved. A disagreement between two
statements by one source is the source's to explain, not ours to average.

**A record with neither item has no position.** `position: None`, never a `Position` holding
zeros, and never the last known one — this adapter has no memory of a previous record. And
`0.0, 0.0` is a real coordinate in the Gulf of Guinea, so the absence test is the presence of the
*item*, never the value of the field.

### Identity

**I021/080 Target Address is the stable key** — the ICAO 24-bit aircraft address, three octets.
It is the identifier a fusion layer joins on, and `adsb.py`'s note on `ICAO_SYSTEM` names this
format explicitly: the address is "carried identically by Mode S replies, ACAS and ASTERIX", so
`ids.derive("ICAO24", …)` agrees across the two adapters without either knowing the other exists.
That agreement is the single largest reason this adapter is worth having.

**But the address is only an ICAO24 address when I021/040's `ATP` says so**, and that is a
mandatory item, so the question always has an answer:

| `ATP` | Means | `source_ids[].system` |
|---|---|---|
| 0 | 24-bit ICAO address | **`ICAO24`** — joins with the ADS-B adapter's contacts |
| 1 | Duplicate address | `ADSB_NONICAO` |
| 2 | Surface vehicle address | `ADSB_NONICAO` |
| 3 | Anonymous address | `ADSB_NONICAO` |
| 4–7 | Reserved for future use | `ADSB_NONICAO`, raw value parked |

This is the DF18 `CF` 1/5 decision from `adsb.py`, reached from a different field: filing a
self-assigned or vehicle address under `ICAO24` would let fusion join the contact to a real
airframe that happens to share the number, so it goes in a system namespace that cannot collide
with one.

Two of the rows deserve their reasons stated rather than inherited.

**`ATP` = 1, duplicate address, is a warning and not a category.** The ground station is saying
the address is *not unique on the wire* — two transmitters are using it. Neither available answer
is right: under `ICAO24` the contact merges with the genuine airframe, and under `ADSB_NONICAO`
two different real aircraft still merge with each other. `ADSB_NONICAO` is chosen because it
errs in the recoverable direction, and `attributes.identity_caveat` records in the object that
this entity may conflate two airframes. A consumer can act on that; it cannot act on a silent
merge.

**Reserved `ATP` values are not refused.** `adsb.py` refuses DF18 `CF` 3, 4 and 7 by name, and the
difference is exactly the one that matters: there, the control field changes the **ME layout**, so
decoding with the wrong one yields a plausible wrong position. Here `ATP` changes only what the
address *means*, and every other field decodes identically — so the safe pool is available and a
refusal would discard a good position to express an uncertainty about a name.

**I021/170 Target Identification is label material, and it is gap 1's most awkward case yet.**
Eight characters at six bits each, per ICAO Annex 10 Vol. IV §3.1.2.9.1.2 and Table 3-8 — the
same alphabet `adsb.py` decodes. It is parked at `attributes.target_identification`, with the
eight decoded characters kept verbatim at `attributes.target_identification_raw` including any
six-bit value the alphabet does not define, so a malformed identification is visible rather than
cleaned away.

**It is deliberately NOT parked at `attributes.callsign`**, which is the key the TAK and ADS-B
adapters both already use. Gap 1 records that their convergence on one private key is *worse*
than four keys that visibly disagree, because it reads as a general rule and is not one — and
this item is the proof. The specification defines it as "target identification when flight plan
is available **or the registration marking when no flight plan is available**". One field, two
meanings, no bit anywhere in the record saying which arrived. Filing it under `callsign` would
assert the first meaning half the time.

**The divergence is deliberate, and its cost is visible: one aircraft, two keys.** The same
airframe seen by `adsb.py` and by this adapter carries the **same identification string** under
two different names — `attributes.callsign` from the 1090ES frame and
`attributes.target_identification` from the CAT021 record. A consumer holding both objects sees
one aircraft describe itself twice and has to know both keys to read either.

That is accepted rather than regretted, for a reason about what a translator owes. **Reconciling
two feeds' vocabularies is fusion**, and it is fusion of exactly the kind this document already
declines four times: AIS type 24's cross-message join, CPR even/odd pairing, Legion's pagination,
and correlation across CAT021 data blocks. An adapter is a pure function of one payload — it does
not know the other adapter exists, cannot see its output, and owes it no convergence. **If
convergence is ever wanted it is a consumer decision**, made where both objects are in hand, where
the choice is visible, and where a precedence rule for it can be written down and audited. A
translator reaching for another adapter's key in order to look tidy would be making that decision
invisibly, in the one place nobody looks for it.

**What must not be claimed here is that CAT021's field is the ambiguous one and ADS-B's is not.**
They are the same field. I021/170's coding rules cite ICAO Annex 10 Vol. IV §3.1.2.9.1.2 and
Table 3-8 — the same section and the same table that define the Aircraft Identification carried by
a 1090ES type code 1–4 frame — so "flight identification, or the registration marking when no
flight plan is available" is true of both. One arrives direct from the squitter and one relayed
through a ground station; the ambiguity is identical. The honest statement of the asymmetry is
therefore that **`attributes.callsign` asserts the flight-plan reading on data that does not
support it, and `attributes.target_identification` does not.** This is not two row sets weighing
different evidence and reaching different answers — it is this row set declining to repeat a
choice made before the ambiguity was noticed.

So `adsb.py`'s key is the one that should move, and it is **not moved here**. It is a published
`attributes` key that a shipped adapter, its fixtures and its golden files already carry, so
renaming it is a 1.1.0 question with a migration note behind it, not a side effect of writing a
sixth row set. The cost is counted in gap 1.

**I021/070 Mode 3/A Code is parked, and here converging on ADS-B's key IS right.** Twelve bits,
octal, four digits. It is not a `SourceId` for exactly the reason `adsb.py` gives — a squawk is
assigned by ATC per flight and reassigned afterwards, so an id keyed on it would split one
aircraft into many entities and later merge it with a different one. It lands at
`attributes.mode_a_code` (four octal digits) and `attributes.mode_a_code_raw` (the twelve bits),
the same keys `adsb.py` uses, and the convergence is safe where the callsign one was not: a Mode
3/A code means one thing in both formats, because it is the same transponder answering.

**I021/161 Track Number is parked and is not a `SourceId`.** It is "a unique reference to a track
record within a particular track file" — twelve bits, 0…4095, scoped to one ground station's
track file, and recycled. An entity keyed on it would merge two aircraft tracked by two stations
under one number. A SAC/SIC-scoped composite would be unique across stations and would still
recycle within one, so making it an identifier is a fusion decision about lifetime, not a
translation.

#### Emitter category → `Entity.entity_type`, every code accounted for

I021/020, one octet. The rule is `adsb.py`'s: a category does **not** generally refine the entity
type, because a light aircraft, a heavy and a rotorcraft are all `PLATFORM` and inventing a finer
CDM distinction would put a judgement in a translator. The exception is the same one, reached
through a different vocabulary — an obstacle is a fixed structure.

| Code | Meaning | `Entity.entity_type` | Note |
|---|---|---|---|
| 0 | No ADS-B Emitter Category Information | `PLATFORM` | a **stated absence**, not category zero — named in `attributes.unavailable_fields` |
| 1 | Light aircraft ≤ 15 500 lbs | `PLATFORM` | |
| 2 | Small aircraft, 15 500–75 000 lbs | `PLATFORM` | |
| 3 | Medium aircraft, 75 000–300 000 lbs | `PLATFORM` | |
| 4 | High Vortex Large | `PLATFORM` | Versions 0–2 only; still sent for a Version 3 system, per the item's own note |
| 5 | Heavy aircraft ≥ 300 000 lbs | `PLATFORM` | |
| 6 | Highly manoeuvrable, 5 g and > 400 kt cruise | `PLATFORM` | Versions 0–2 only. **Not read as an affiliation** — a performance class is not a side |
| 7–9 | Reserved | `PLATFORM` | raw parked and named in `attributes.unresolved_raw`: the source said something this adapter cannot use |
| 10 | Rotorcraft | `PLATFORM` | |
| 11 | Glider / sailplane | `PLATFORM` | |
| 12 | Lighter-than-air | `PLATFORM` | |
| 13 | Unmanned aerial vehicle | `PLATFORM` | Versions 0–2 only. Parked as stated; REF `STA` second extension `MUO` is the Version 3 statement of the same fact and the two are kept distinct |
| 14 | Space / transatmospheric vehicle | `PLATFORM` | Versions 0–2 only |
| 15 | Ultralight / hang-glider / paraglider | `PLATFORM` | |
| 16 | Parachutist / skydiver | `PLATFORM` | Versions 0–2 only. The least comfortable row in the table: a person under a canopy is not a platform, and the CDM's nearest alternatives (`UNIT`, `EVACUEE_GROUP`) are both **more** wrong. `PLATFORM` overstates slightly; the others would state something false about who this is |
| 17–19 | Reserved | `PLATFORM` | as 7–9 |
| 20 | Surface emergency vehicle | `PLATFORM` | a vehicle is a platform; "emergency" here describes its role and is **not** read into `Event.severity` |
| 21 | Surface service vehicle | `PLATFORM` | |
| 22 | Fixed ground or tethered obstruction | **`FACILITY`** | the ADS-B exception, reached again |
| 23 | Cluster obstacle | **`FACILITY`** | |
| 24 | Line obstacle | **`FACILITY`** | |
| 25–255 | Undefined | `PLATFORM` | raw parked and named in `unresolved_raw` |

Codes 22, 23 and 24 are the same three objects `adsb.py` maps from category set C values 3, 4 and
5 — point, cluster and line obstacle. Two formats, two vocabularies, one decision, and the two
adapters agree because the reasoning is written down rather than because they were written
together.

The raw code and its standard wording are parked at `attributes.emitter_category` and
`attributes.emitter_category_text` regardless, as AIS parks a ship type: the collapse to
`PLATFORM` is recoverable only because the original survives.

### Affiliation is UNKNOWN, and the Mode 5 case is where that is a decision

`Entity.affiliation` is `UNKNOWN` on every record, with `attributes.affiliation_basis` recording
why. The base reason is `adsb.py`'s and is stronger than AIS's silence: 1090ES is an
unauthenticated cooperative broadcast, so its self-declared contents are not an identification.
CAT021 inherits that — everything in a target report except the ground station's own flags
originated as a self-declared broadcast.

**The REF makes this a real decision rather than an inherited default.** `MES` subfield #1 carries
`ID` = "Authenticated Mode 5 ID reply/report" and `DA` = "Authenticated Mode 5 Data reply or
Report". A Mode 5 Level 2 reply that authenticates is a cryptographic IFF response, and in IFF
doctrine that is what "friend" means. It is the first genuinely *authenticated* identity statement
any source in this document has carried.

**It is still not read as `FRIENDLY`, and the reason is not timidity.** Turning an authenticated
Mode 5 reply into `FRIENDLY` is an identification decision — the exact thing `Affiliation`'s own
docstring puts outside an adapter's remit, and the direction the TAK adapter asserts in a test
that a collapse must not round towards. It is also the dangerous direction: over-claiming
`FRIENDLY` from a translator is a fratricide-adjacent error, and the authority that owns an IFF
verdict is not an integration layer. So the bits are parked in full — `M5`, `ID`, `DA`, `M1`,
`M2`, `M3`, `MC`, `PO` — `attributes.affiliation_basis` states that the record carried an
authenticated IFF indication which this adapter deliberately did not read as an identification,
and the decision is visible in every object rather than absent from the code. See **gap 2**.

### Quality and integrity — every indicator parked, and why each

I021/090 is mandatory in every record and carries up to four octets of them. **Not one becomes a
canonical field.** The rows below say where each goes; the reasons are three, and they compound.

**They are categories and bounds, not measurements.** `Position.accuracy_m` is one horizontal
1-sigma figure in metres. NUCp, NIC, NACp, SIL, SDA and GVA are all *categories*; PIC is an
integrity **containment bound** ("< 0.1 NM", "< 20.0 NM"). A containment bound is the radius
inside which the true position lies with a stated integrity — not a standard deviation, and
converting one into the other states a precision nobody measured. This is `adsb.py`'s NACp row
and `ais.py`'s position-accuracy-flag row, and PIC is the sharpest case yet precisely *because*
the specification hands over a number in nautical miles and it is still the wrong number.

**Their meaning depends on an item that may not be there.** The primary subfield is literally
"NUCr **or** NACv" and "NUCp **or** NIC" — which of each pair is present is decided by the MOPS
version in I021/210, an *optional* item. So a record can carry a quality indicator whose quantity
is undetermined. The raw bits are parked, I021/210's version is parked beside them, and
`attributes.quality_basis` states which reading applied — or that none could be established,
which is the honest answer where I021/210 is absent. This is `adsb.py`'s capability-class row
generalised: unpacking a field against the wrong version reports capabilities the aircraft never
claimed.

**They qualify measurements that arrive from elsewhere.** `Entity.confidence` stays `None`: these
are accuracy and integrity statements about a *position*, not a confidence in the object's
identity, which is what that field means.

The same treatment covers the ground station's own verdicts in I021/040 — `CL` (report valid /
suspect / no information), and the second extension's `LLC` (black-list/white-list lookup), `IPC`
(independent position check failed), `NOGO`, `CPR` (CPR validation failed), `LDPJ` (local
decoding position jump) and `RCF` (range check failed). All parked, none of them touching
`confidence` or `severity`. "Suspect" is a data-quality flag and grading it into a number would
invent the number.

**One of them asks this adapter to filter, and the answer is no.** The specification's own note on
`RCF` says: "For operational users such a target will be suppressed." An adapter may not filter —
that is rule 2 of the `Adapter` contract, and a decision made inside a translator is invisible in
the CDM output and absent from the audit trail. So a range-check-failed target is translated in
full, its flag is parked, and the suppression decision belongs to a consumer where somebody can
see it being made. The specification is describing what a *surveillance system* should do; this
is a translator inside one.

### Row set — the block and record envelope

Nothing here describes the world: it describes the ground station and the framing. All of it is
parked, and egress rebuilds the block from it.

| CAT021 | CDM field | Status | Notes |
|---|---|---|---|
| `block.category` | `Entity.attributes` | `cat021 1.0.0` | the CAT octet, parked as read. A block whose category is not 21 is refused rather than decoded |
| `block.length` | `Entity.attributes` | `cat021 1.0.0` | parked, and **recomputed on egress rather than copied** — a length field that disagrees with the octets is discarded by every ASTERIX decoder, the same reason `adsb.py` recomputes its CRC |
| `block.record_index`, `block.record_count` | `Event.payload` | `cat021 1.0.0` | which record of how many this object came from. Without it, two objects from one block are indistinguishable from two objects from two blocks |
| `record.fspec` | `Entity.attributes` | `cat021 1.0.0` | the FSPEC octets verbatim. Parked because a conforming encoder's FSPEC is the shortest one that covers its highest FRN and the specification does not forbid a longer one — the round trip is byte-exact only if we re-emit what we read |
| `record.spare_bits` | `Entity.attributes` | `cat021 1.0.0` | every spare and unused bit, as sent. §4.3 forbids relying on their settings and only *recommends* zeroing them, so normalising would break the round trip on non-conforming traffic |
| `I021/010` SAC, SIC | `Entity.attributes` | `cat021 1.0.0 · parked` | the ADS-B ground station that produced the report, at `attributes.data_source`. **Not a `SourceId`**: it identifies the sensor, not the target, and filing a station under the object's identifiers is how a fused picture ends up with an entity per receiver. See **gap 14** |
| `I021/400` RID | `Entity.attributes` | `cat021 1.0.0` | Receiver ID — which receiver of a distributed ground system. Parked with the SAC/SIC, same reasoning |
| `I021/015` Service Identification | `Entity.attributes` | `cat021 1.0.0` | which service this record belongs to, allocated by the system. A subscription fact, parked |
| `I021/016` RP | `Entity.attributes` | `cat021 1.0.0` | Report Period, LSB 0.5 s; **0 means data-driven mode**, not a period of zero, and 127.5 means "127.5 s or above". Parked with both readings recorded rather than reduced to a number |
| `RE` (FRN 48) | `Entity.attributes` | `cat021 1.0.0` | the Reserved Expansion Field — parsed in full, see its own row set. Its explicit length octet counts itself |
| `SP` (FRN 49) | `Entity.attributes` | `cat021 1.0.0` | Special Purpose Field, opaque. Parked verbatim as hex and **never written to on egress** — its contents are defined by bilateral agreement between one sender and one receiver, so a byte we invent is a byte some deployment already means something by |

### Row set — common to every record

| CAT021 | CDM field | Status | Notes |
|---|---|---|---|
| `I021/080` Target Address | `Entity.source_ids[].external_id` | `cat021 1.0.0` | the 24-bit address as six hex characters. The id `entity_id` is derived from, on every record |
| `I021/040` ATP | `Entity.source_ids[].system` | `cat021 1.0.0` | `ICAO24` when ATP is 0, `ADSB_NONICAO` otherwise — see the identity section. The choice is recorded at `attributes.address_type` |
| `I021/080` + `observed_at` | `Event.event_id` | `cat021 1.0.0` | keyed on BOTH, for the reason the CoT, AIS and ADS-B adapters give: an address identifies the airframe and repeats on every report, so an id keyed on it alone would collapse a whole flight into one event |
| `I021/020` Emitter Category | `Entity.entity_type` | `cat021 1.0.0` | `PLATFORM`, refined to `FACILITY` only for codes 22, 23 and 24 — see the table above. Every code accounted for |
| `I021/020` Emitter Category | `Entity.attributes` | `cat021 1.0.0` | code AND wording at `attributes.emitter_category` / `attributes.emitter_category_text`. Code 0 is a stated absence and lands in `unavailable_fields` |
| *(none)* | `Entity.affiliation` | `cat021 1.0.0` | `UNKNOWN`, always. `attributes.affiliation_basis` distinguishes the ordinary case (an unauthenticated cooperative broadcast) from the Mode 5 case (an authenticated IFF indication this adapter declines to read as an identification) |
| *(derived)* | `Entity.symbol` | `cat021 1.0.0` | from the affiliation via `symbology.sidc_from_affiliation`, so every CAT021 contact is an UNKNOWN glyph. `attributes.symbol_basis` says so |
| `I021/040` SIM | `Entity.attributes` | `cat021 1.0.0` | Simulated Target. Parked at `attributes.simulated_target` and it **does NOT rewrite `source.synthetic`** — that is a deployment declaration about the feed and a payload field may not flip it. Exactly the Legion `EXERCISE_*` rule, reached from a one-bit flag |
| `I021/040` TST | `Entity.attributes` | `cat021 1.0.0` | Test Target, parked on the same terms |
| `I021/040` RAB | `Entity.attributes` | `cat021 1.0.0` | report from a target transponder or from a **field monitor** (a fixed transponder used to check the station). Parked, and deliberately not turned into `FACILITY`: it says who transmitted, not what kind of thing it is |
| `I021/040` GBS | `Entity.attributes` | `cat021 1.0.0` | Ground Bit set — the aircraft says it is on the surface. Parked, and it is what selects the surface reading of several other fields, so it is load-bearing rather than cosmetic |
| `I021/040` DCR, ARC, RC | `Entity.attributes` | `cat021 1.0.0` | differential correction applied; altitude reporting capability (25 ft, 100 ft, unknown, invalid); range check passed with CPR validation pending. Parked |
| `I021/040` SAA | `Entity.attributes` | `cat021 1.0.0` | Selected Altitude Available — note the **inverted sense**: 0 means the equipment IS capable, 1 means it is not. Parked as sent with the sense recorded, because a consumer reading it the intuitive way gets it backwards |
| `I021/040` CL, LLC, IPC, NOGO, CPR, LDPJ, RCF | `Entity.attributes` | `cat021 1.0.0` | the ground station's own verdicts. All parked, none touching `confidence` or `severity` — and `RCF` is the row where the specification asks for filtering and the `Adapter` contract refuses. See the quality section |
| `I021/040` TBC, MBC | `Entity.attributes` | `cat021 1.0.0` | third and fourth extensions: total and maximum bits corrected by the station's error-correction. Each has an "Element Populated" bit — **not populated is not a count of zero**, and the two are kept distinct |
| `I021/210` VN, VNS, LTT | `Entity.attributes` | `cat021 1.0.0` | MOPS version, version-not-supported, and link technology type (0 other, 1 UAT, 2 1090 ES, 3 VDL 4). Parked, and it is what says how to read I021/090 and I021/200 — which is why a record without it has quality indicators of undetermined meaning |
| `I021/161` Track Number | `Entity.attributes` | `cat021 1.0.0` | parked, **not a `SourceId`** — twelve bits, scoped to one station's track file, and recycled |
| `I021/132` Message Amplitude | `Entity.attributes` | `cat021 1.0.0` | dBm, two's complement, of the latest received squitter. A link measurement, parked and never read as a range or a confidence |
| *(none)* | `Entity.valid_to` | `cat021 1.0.0` | `None`. CAT021 has no staleness field; I021/295 states how old data IS, which is a measurement backwards and not an expiry forwards |
| *(none)* | `Entity.confidence` | `cat021 1.0.0` | `None`. The quality indicators are position accuracy and integrity categories, and `CL` "report suspect" is a data-quality flag — neither is a confidence in the object's identity |
| *(derived)* | `Event.related_entities` | `cat021 1.0.0` | the `entity_id` of the record's own entity, as AIS and ADS-B do |
| *(measured)* | `Entity.attributes` | `cat021 1.0.0` | `attributes.unavailable_fields` — the sorted list of fields the source explicitly marked not-available, by a sentinel or by clearing a validity bit. "The aircraft said it does not know its selected heading" and "this adapter had nothing to say" are different facts |
| *(measured)* | `Entity.attributes` | `cat021 1.0.0` | `attributes.unresolved_raw` — wire values read and not usable: a reserved emitter category, a reserved `FSI`, a geometric height carrying the "greater than" marker, an element whose Element-Populated bit is clear. A DIFFERENT fact from the list above, and the pair is the point |
| everything unmapped | `Entity.attributes` | `cat021 1.0.0` | `attributes.source_extras`, structure intact |

### Row set — time

| CAT021 | CDM field | Status | Notes |
|---|---|---|---|
| `I021/071` Time of Applicability for Position | `Event.observed_at` | `cat021 1.0.0` | first in the chain. Time of day since midnight UTC, LSB 1/128 s; the date comes from the injected clock and `payload.observed_at_basis` names both halves |
| `I021/073` Time of Message Reception for Position | `Event.observed_at` | `cat021 1.0.0` | second in the chain. A receipt time at the **ground station**, which is neither the aircraft's instant nor ours — used only when I021/071 is absent, and the basis says so |
| `I021/074` TOMRp high precision | `Entity.attributes` | `cat021 1.0.0` | refines I021/073's whole seconds through `FSI` and adds a 30-bit fraction at 2⁻³⁰ s. **`FSI` is a whole-second correction, not a rounding hint**; `FSI` = 3 is reserved and sends the value to `unresolved_raw`. Parked raw because a CDM `Timestamp` renders three decimal places and cannot hold it |
| `I021/072` Time of Applicability for Velocity | `Entity.attributes` | `cat021 1.0.0` | parked, and third in the `observed_at` chain for a record with velocity and no position. **This is gap 13**: one record, two measurement instants, one canonical time |
| `I021/075` Time of Message Reception for Velocity | `Entity.attributes` | `cat021 1.0.0` | as I021/073, for velocity |
| `I021/076` TOMRv high precision | `Entity.attributes` | `cat021 1.0.0` | as I021/074, against I021/075 |
| `I021/077` Time of Report Transmission | `Entity.attributes` | `cat021 1.0.0` | when the ground station emitted the ASTERIX record. Parked, and last in the `observed_at` chain: it is a source time about the *report* rather than about the observation |
| all seven, raw | `Entity.attributes` | `cat021 1.0.0` | the raw 24- and 32-bit integers verbatim at `attributes.cat021_times`, because 1/128 s is not a whole number of milliseconds and egress must re-emit from these rather than recompute from `observed_at` |
| *(the injected clock)* | `Event.received_at` | `cat021 1.0.0` | when WE took delivery. Never I021/073, which is the ground station's receipt and a different party |
| `I021/295` Data Ages (23 subfields) | `Entity.attributes` | `cat021 1.0.0` | each item's age in units of 0.1 s, parked under its own key. The maximum, 25.5 s, means "25.5 s **or above**" and is a floor rather than an age, recorded as one — exactly as AIS's 102.2 kt is. **The strongest evidence for gap 13**: the format states per-field staleness and the CDM has nowhere to put any of it |

### Row set — position and altitude

| CAT021 | CDM field | Status | Notes |
|---|---|---|---|
| `I021/130` Latitude, Longitude | `Position.lat` / `Position.lon` | `cat021 1.0.0` | 24-bit two's complement each, LSB 180/2²³ ≈ 2.145 767 × 10⁻⁵ °, at least 2.4 m. WGS-84 already: the only transform is the scaling, and there is no datum conversion |
| `I021/131` Latitude, Longitude | `Position.lat` / `Position.lon` | `cat021 1.0.0` | 32-bit two's complement each, LSB 180/2³⁰ ≈ 1.676 381 × 10⁻⁷ °, at least 2 cm. **Wins when both items are present**, with the disagreement recorded if it exceeds one I021/130 LSB |
| `I021/130`, `I021/131` raw | `Entity.attributes` | `cat021 1.0.0` | the raw integers, the item they came from and the LSB, verbatim at `attributes.cat021_position` — the source coordinates are the record and `Position` is a derived view, the Legion `position_basis` rule applied where the datum happens to be easy |
| *(derived)* | `Position.position_source` | `cat021 1.0.0` | `GNSS`. A CAT021 position originated as the aircraft's own GNSS fix, CPR-decoded by the ground station; `attributes.position_source_basis` records that the decode happened upstream and that this adapter did not perform it |
| *(none)* | `Position.accuracy_m` | `cat021 1.0.0` | `None`, always. Every accuracy statement CAT021 carries is a category or a containment bound — see the quality section. `None` means unknown accuracy, never perfect accuracy |
| `I021/140` Geometric Height | `Position.alt_m` | `cat021 1.0.0` | "minimum height from a plane tangent to the earth's ellipsoid, defined by WGS-84" — which is exactly what `alt_m` documents, so this maps, feet → metres at LSB 6.25 ft, a declared transform. **CAT021 states the reference surface that a 1090ES frame only implies**, which is the half of gap 9's datum problem this format closes |
| `I021/140` = `0111111111111111` | `Entity.attributes` | `cat021 1.0.0` | the "greater than" indication. `alt_m` is **absent** and the raw sixteen bits go to `unresolved_raw`: the marker states that a height exists above some bound the item never names, so it is a statement this adapter cannot use, and not the source saying it does not know |
| `I021/145` Flight Level | `Entity.attributes` | `cat021 1.0.0 · parked` | **gap 9** — a barometric flight level, not QNH corrected, LSB ¼ FL, two's complement, −15 to 1500 FL. Parked at `attributes.flight_level` **in FL, the source's own unit**. Note the collision it exposes rather than resolves: `adsb.py` parks the same concept at `attributes.baro_altitude_ft`, and converging on that key would repeat gap 1's mistake of turning a private convention into a de-facto standard without an owner |
| *(a record can carry both)* | `Position.alt_m` | `cat021 1.0.0` | I021/140 and I021/145 are two different measurements of two different things and both may be present. The geometric one is the only one that reaches `Position`; `attributes.altitude_basis` records which items were present and which was used |
| `I021/146` Selected Altitude | `Entity.attributes` | `cat021 1.0.0 · parked` | **intent, not position** — the MCP/FCU or FMS altitude the crew selected, LSB 25 ft, with a `SAS` availability bit and a 2-bit source. Parked whole. See **gap 15** |
| `I021/148` Final State Selected Altitude | `Entity.attributes` | `cat021 1.0.0` | intent again, with `MV`/`AH`/`AM` mode bits. Kept for backward compatibility and **shall not be used for Version 2 or higher**, so a record carrying it alongside I021/146 is telling us about the transmitter's vintage. Parked, with the version recorded beside it |

### Row set — velocity, heading and attitude

| CAT021 | CDM field | Status | Notes |
|---|---|---|---|
| `I021/160` Ground Speed | `Kinematics.speed_mps` | `cat021 1.0.0` | 15 bits, LSB 2⁻¹⁴ NM/s (≈ 0.22 kt), range 0 ≤ GS < 2 NM/s. NM/s → m/s at exactly 1852 m per NM, a declared transform |
| `I021/160` Track Angle | `Kinematics.course_deg` | `cat021 1.0.0` | 16 bits, LSB 360/2¹⁶ ≈ 0.005 493 °, clockwise from **True North** — a track over the ground, which is what `course_deg` means, and with its datum stated, which is what gap 7 asks for |
| `I021/160` RE | `Entity.attributes` | `cat021 1.0.0` | Range Exceeded: the field holds the maximum the avionics could downlink and the true value is **greater**. A floor, not a measurement — the value is kept with `attributes.ground_speed_at_or_above_maximum`, exactly as AIS's 102.2 kt is |
| `I021/157` Geometric Vertical Rate | `Kinematics.climb_mps` | `cat021 1.0.0` | LSB 6.25 ft/min, two's complement, "with reference to WGS-84" — so it differentiates the same surface `alt_m` is measured against. ft/min → m/s, a declared transform; sign convention matches the CDM's (negative descending) |
| `I021/155` Barometric Vertical Rate | `Kinematics.climb_mps` | `cat021 1.0.0` | the same field when I021/157 is absent, and parked at `attributes.baro_vertical_rate_ft_min` when both are present. `attributes.climb_basis` names which was used. A record can carry both and they are two measurements, exactly as the two altitudes are |
| `I021/155`, `I021/157` RE | `Entity.attributes` | `cat021 1.0.0` | as I021/160's — with one ambiguity named rather than resolved: for a **negative** (descending) rate the specification's "the actual value is greater" does not say whether it means greater in magnitude or greater in signed value. Recorded in the ambiguity list; the figure is kept with the floor flag and never silently re-signed |
| `I021/150` Air Speed | `Entity.attributes` | `cat021 1.0.0 · parked` | **gap 10** — IAS (LSB 2⁻¹⁴ NM/s) or Mach (LSB 0.001), selected by the `IM` bit. Parked at `attributes.airspeed_ias_kt` or `attributes.airspeed_mach` with the flag; `speed_mps` stays null, because an airspeed written into a ground-speed field reads as a ground speed to every consumer |
| `I021/151` True Air Speed | `Entity.attributes` | `cat021 1.0.0 · parked` | **gap 10** — LSB 1 kt, with its own RE floor bit. Parked at `attributes.airspeed_true_kt`. CAT021 is the first source to carry indicated **and** true airspeed as separate items, which is why gap 10 says one `airspeed_mps` would close a third of a question |
| `I021/152` Magnetic Heading | `Entity.attributes` | `cat021 1.0.0 · parked` | **gap 7** — LSB 360/2¹⁶, referenced to **magnetic** north. Parked at `attributes.magnetic_heading_deg` |
| REF `TNH` True North Heading | `Entity.attributes` | `cat021 1.0.0 · parked` | **gap 7, and the row that answers its open question** — the same LSB, referenced to **true** north, as a separate item. CAT021 is the first source in this document to state a heading and its datum without a cross-frame join, which is exactly the requirement ADS-B's magnetic-versus-true problem added to that gap |
| `I021/165` Track Angle Rate | `Entity.attributes` | `cat021 1.0.0 · parked` | **gap 7's turn-rate half** — 10 bits, two's complement, LSB 1/32 °/s, maximum 16 °/s meaning "16 °/s or above", positive right and negative left. Parked at `attributes.track_angle_rate_deg_per_s` — note the **unit collision**: gap 7 proposes `turn_rate_dpm` in degrees per *minute*, AIS states degrees per minute, and this states degrees per second. The item's own note says it is not transmitted for 1090 ES, so a record carrying it came from another link technology and I021/210's `LTT` says which |
| `I021/230` Roll Angle | `Entity.attributes` | `cat021 1.0.0 · parked` | **gap 7's attitude half** — LSB 0.01 °, −180 to 180, negative meaning left wing down. Parked. Legion parked a quaternion here; this is one of its components stated on its own, and the note that 1090 ES resolves it only to 1 degree is parked with it |
| REF `SGV` STP, HTS, HTT, HRD, GSS, HGT | `Kinematics.speed_mps` / `Kinematics.course_deg` | `cat021 1.0.0` | the **Surface** Ground Vector, without which a surface target has no motion at all. `GSS` LSB 0.125 kt → `speed_mps`; `HGT` LSB 2.8125 ° → `course_deg` **only when `HTT` says Ground Track**, since a heading is not a course. `HTS` clear means the heading/track data is not valid, so the course is absent and the field is named in `unavailable_fields` while its wire value goes to `unresolved_raw`. `HRD` states the datum; `STP` means the aircraft has stopped, which is a measurement of stillness and becomes 0.0 m/s and not a null |

### Row set — status, emergency and severity

| CAT021 | CDM field | Status | Notes |
|---|---|---|---|
| `I021/200` PS | `Event.severity` / `Event.event_type` | `cat021 1.0.0` | Priority Status 1–6 (general emergency, lifeguard/medical, minimum fuel, no communications, unlawful interference, downed aircraft) → `CRITICAL` / `ALERT`. 0 is no emergency and reads `INFO`. The line is drawn at the standard's own emergency declaration, exactly where `adsb.py` draws it and where `ais.py` draws it at navigational status 14 |
| `I021/200` SS | `Event.severity` / `Event.event_type` | `cat021 1.0.0` | Surveillance Status 1, Permanent Alert (an emergency condition) → `CRITICAL` / `ALERT`. 2 (temporary alert, a Mode 3/A change) and 3 (SPI) → `INFO`: procedural conditions, not emergencies |
| `I021/200` ME | `Event.severity` / `Event.event_type` | `cat021 1.0.0` | Military Emergency → `CRITICAL` / `ALERT`. No 1090ES frame carries this bit, so it is new here; it is the standard's own emergency declaration and the line is drawn in the same place |
| `I021/200` PS, SS, ME | `Entity.attributes` | `cat021 1.0.0` | code AND wording for each, parked. The three are independent and a record can raise more than one |
| `I021/200` ICF | `Entity.attributes` | `cat021 1.0.0` | Intent Change Flag — new data in BDS registers 40/41/42. **No longer used as of MOPS Version 3 and shall be 0**, so its meaning depends on I021/210 and it is parked with the version beside it |
| `I021/200` LNAV | `Entity.attributes` | `cat021 1.0.0` | LNAV mode. **The logic is REVERSED relative to ED-102/DO-260**, per the item's own note — 0 means engaged. Parked as sent with the inversion recorded, because a consumer reading it the DO-260 way gets it exactly backwards |
| REF `STA` PS3 | `Event.severity` / `Event.event_type` | `cat021 1.0.0` | Priority Status for **Version 3** systems, where I021/200's PS is no longer where an emergency lives. Values 1 and 5–7 (general emergency, unlawful interference, aircraft in distress automatic, aircraft in distress manual) → `CRITICAL` / `ALERT`; 2 is UAS/RPAS lost link and 3 minimum fuel and 4 no communication, all `INFO` under the same line the other rows draw. **This row is why the REF is in scope** |
| REF `STA` PS3 vs `I021/200` PS | `Entity.attributes` | `cat021 1.0.0` | the specification gives an explicit mapping between the two vocabularies, in which Version 3's *aircraft in distress* (6 and 7) both collapse to Version < 3's *general emergency* (1). Both values are parked as stated and the collapse is **never run in reverse** — an adapter inferring 6 or 7 from a 1 would invent a distress activation mode |
| REF `STA` ES, UAT, RCE, RRL | `Entity.attributes` | `cat021 1.0.0` | 1090 ES IN and UAT IN capability; Reduced Capability Equipment (TABS and others); Reply Rate Limiting active. Each `RCE` and `RRL` carries an **Element Populated** bit and "not populated" is not a value of zero — the two are kept distinct and an unpopulated element is named in `unresolved_raw` |
| REF `STA` TPW, TSI, MUO, RWC, DAA, DF17CA, SVH, CATC, TAO | `Entity.attributes` | `cat021 1.0.0` | transmit power; transponder side; **manned or unmanned operation**; Remain Well Clear corrective alert; Detect And Avoid capability; the DF17 CA field as store-and-forward; collision-avoidance sense and CAS type; transponder antenna offset. All parked, all Version 3, all with Element Populated bits. `MUO` is deliberately **not** read into `entity_type`: "unmanned" is a crewing fact, and a UAV and an airliner are both `PLATFORM` for the reason a tanker and a tug both are |
| `I021/008` RA, TC, TS, ARV, CDTI/A, not TCAS, SA | `Entity.attributes` | `cat021 1.0.0` | Aircraft Operational Status while airborne. `RA` says a TCAS/ACAS resolution advisory is **active** — parked, and it does **not** raise severity here: the RA itself arrives in I021/260 and grading an equipment status as an emergency would be the translator judging. Note `not TCAS`'s inverted sense (1 = not operational) and `SA` (1 = single antenna) |
| `I021/271` POA, CDTI/S, B2 low, RAS, IDENT | `Entity.attributes` | `cat021 1.0.0` | surface capabilities. `POA` states whether the transmitted position **is** the ADS-B position reference point — a fact about where on the airframe the fix is, which is gap 8's offset-reference-point problem stated by a source for the first time. `IDENT` is the IDENT switch, parked and not read as an alert |
| `I021/271` first extension, L + W | `Entity.attributes` | `cat021 1.0.0 · parked` | **gap 8** — length and width as a 4-bit bucket index into the specification's own table (L < 15 m and W < 11.5 m, …, L > 85 m or W > 80 m). Parked as the code AND the bucket's bounds, never as a single number: a bucket is a range and collapsing it to a midpoint would state a size nobody measured. Version 2 and higher encode "no data or unknown" as 0 and omit the extension entirely |
| `I021/260` TYP, STYP, ARA, RAC, RAT, MTE, TTI, TID | `Event.payload` | `cat021 1.0.0` | the ACAS Resolution Advisory report, a copy of BDS register 3,0 for message type 28 subtype 2. Parked whole as stated fields plus raw bits. **Not decoded into an advisory vocabulary** — `adsb.py` declines type code 28 subtype 2 for exactly this reason: the ARA bits are an ACAS vocabulary defined outside this specification, and decoding them means adopting a second standard |
| `I021/250` REP, BDSDATA, BDS1, BDS2 | `Entity.attributes` | `cat021 1.0.0` | BDS register data, repetitive: a one-octet count then N × (56-bit register contents + a two-nibble register address). Parked as raw hex per register with its address. The specification's own note says this data "is not encoded in ASTERIX but in the original Squitter format" — so decoding it is a Mode S BDS adapter, which `adsb.py` already names as a different adapter |

### Row set — intent, meteorology and the rest

| CAT021 | CDM field | Status | Notes |
|---|---|---|---|
| `I021/110` TIS: NAV, NVB | `Entity.attributes` | `cat021 1.0.0` | trajectory intent status. Note both bits are **negative-sense**: `NAV` = 1 means intent data is *not* available, `NVB` = 1 means it is *not* valid. Parked as sent with the sense recorded |
| `I021/110` TID: REP × 15-octet trajectory intent points | `Entity.attributes` | `cat021 1.0.0 · parked` | **gap 15** — each point carries an altitude (LSB 10 ft), a WGS-84 latitude and longitude (LSB 180/2²³, the same as I021/130), a point type, turn direction, turn-radius availability, a time over point (LSB 1 s since midnight) and a turn radius (LSB 0.01 NM). Parked whole, structure intact, in payload order |
| `I021/110` TID | `Event.geometry` | `cat021 1.0.0` | **deliberately NOT a geometry.** The points form a 4D path, and a `LineString` in `Event.geometry` would paint an aircraft's declared *future* as something observed. `geometry` stays `None` and the points stay parked — the same reason `adsb.py` defers type code 29 |
| REF `SelH` HRD, Stat, SelH | `Entity.attributes` | `cat021 1.0.0` | Selected Heading, LSB 0.703125 °, with its own datum bit and a validity bit. Intent, so it is parked beside the selected altitudes rather than beside the headings — `Stat` = 0 means unavailable or invalid and the field is named in `unavailable_fields` |
| REF `NAV` AP, VN, AH, AM, MFM | `Entity.attributes` | `cat021 1.0.0` | autopilot, VNAV, altitude hold, approach mode, and the MCP/FCU mode-bits status with its Element Populated bit. Intent again. **`MFM#VAL` = 0 means AP/VN/AH/AM are all forced to 0 and I021/200's LNAV to 1** — so a record with `MFM#VAL` clear states nothing about the autopilot, and reading those zeros as "autopilot off" would be a fabricated fact. `unavailable_fields` records it |
| REF `BPS` | `Entity.attributes` | `cat021 1.0.0` | Barometric Pressure Setting, LSB 0.1 hPa, **and the wire value is the setting minus 800 hPa**. 0 means "800 hPa or less" and 409.5 means "1209.5 hPa or more" — two floors, recorded as floors. It is the offset that would let a consumer relate a flight level to a geometric height, so it belongs with gap 9's bridge alongside ADS-B's GNSS-barometric difference |
| REF `GAO` | `Entity.attributes` | `cat021 1.0.0 · parked` | GPS Antenna Offset, lateral and longitudinal, LSB 2 m, with bit 8 giving the lateral direction (0 left of centreline, 1 right). **gap 8's offset reference point stated numerically for the first time** — this is how far the reported fix is from the airframe's centre, which is what makes a position accurate only to within the aircraft's own size |
| `I021/220` WS, WD, TMP, TRB | `Entity.attributes` | `cat021 1.0.0` | Met Information, compound: wind speed (LSB 1 kt, 0–300), wind direction (LSB 1 °, 1–360), temperature (LSB 0.25 °C, two's complement, −100 to 100) and turbulence (0–15). All parked. **The CDM models weather nowhere**, and this is a measurement of the atmosphere at the aircraft rather than of the aircraft — correctly parked rather than missing. Note wind direction's range starts at **1**, so it has no zero and 360 is north |
| REF `MES` SUM, PNO, EM1, XP, FOM, M2 | `Entity.attributes` | `cat021 1.0.0` | Military Extended Squitter, compound, six subfields: the Mode 5 summary bits, PIN and national origin, extended Mode 1 code in octal, X-pulse presence, figure of merit, and Mode 2 code in octal. Parsed in full and **parked in full** — see the affiliation section for the one interpretation this adapter declines. `FOM` is a position-accuracy figure from a Mode 5 transponder and is parked with the other quality categories, never written to `accuracy_m` |
| REF `MES` SUM PO | `Position.position_source` | `cat021 1.0.0` | the one `MES` bit that is a statement about **how the fix was obtained**: 1 means the position came from a Mode 5 report rather than from ADS-B. It does not change `position_source` — a Mode 5 position is still ultimately a GNSS fix — but `attributes.position_source_basis` records that it arrived by that path, because which link carried a fix is exactly the kind of thing that stops being recoverable later |
| REF `LEN`, Items Indicator | `Entity.attributes` | `cat021 1.0.0` | the REF's own length octet (which counts itself) and its eight presence bits. Parked, and the length is **recomputed on egress** for the reason the block length is |

### Row set — egress, CDM back to a CAT021 data block

| CDM | CAT021 | Status | Notes |
|---|---|---|---|
| `Entity.source_ids[].external_id` | `I021/080` | `cat021 1.0.0 · egress` | the `ICAO24` entry, or the `ADSB_NONICAO` one with the parked `ATP` restored. An object with neither is **REFUSED**: deriving a target address would put an aircraft into a surveillance picture under a number nobody allocated, which is `adsb.py`'s refusal word for word |
| *(configuration)* | `I021/010` SAC, SIC | `cat021 1.0.0 · egress` | mandatory in every record, and it names a **ground station** whose codes EUROCONTROL allocates. For an object this adapter ingested, the parked SAC/SIC is restored. For an object that never came from CAT021, `Cat021Adapter(station=(sac, sic))` supplies it — a constant of the deployment, given at construction exactly like `adsb.py`'s reference position and the injected clock. **With no station configured, such an object is REFUSED**, because a SAC/SIC we invent claims an identity that is centrally issued |
| `Position.lat` / `Position.lon` | `I021/131`, or `I021/130` | `cat021 1.0.0 · egress` | encoded from the parked raw integers for an ingested object, and from the coordinates otherwise — in which case **I021/131** is emitted, because choosing the coarse item would discard resolution the CDM was holding. `position: None` emits **neither item**, which is the format's own way of saying nothing and is available here in a way it was not in AIS |
| `Position.alt_m` | `I021/140` | `cat021 1.0.0 · egress` | metres → feet at LSB 6.25 ft, into the geometric height item and never into I021/145. An altitude outside −1500 ft to 150 000 ft is **REFUSED** rather than clipped or wrapped, the same call `adsb.py` makes at 4095 m: a cruise level clipped to a range bound reads as a real altitude to every consumer |
| `Kinematics.speed_mps` + `.course_deg` | `I021/160` | `cat021 1.0.0 · egress` | m/s → 2⁻¹⁴ NM/s and degrees → 360/2¹⁶ steps. A null speed or course omits the whole item rather than encoding a zero — CAT021 can leave an item out, so "not stated" has an honest encoding and 0 kt due north does not have to double as one |
| `Kinematics.climb_mps` | `I021/157` | `cat021 1.0.0 · egress` | into the **geometric** vertical rate, matching the surface `alt_m` is measured against. Null omits the item |
| `Event.observed_at` | `I021/071` | `cat021 1.0.0 · egress` | the time of day, LSB 1/128 s — **from the parked raw integer for an ingested object**, because 1/128 s is not a whole number of milliseconds and recomputing from a rendered timestamp loses the remainder. The date cannot travel: CAT021 states none |
| `Entity.attributes` | everything parked | `cat021 1.0.0 · egress` | the parked fields are read back, which is what makes the round trip byte-exact for a block this adapter ingested — including the FSPEC octets, the spare bits, the raw time integers and the opaque SP field |
| `Track.samples[]` | N records in **one** data block | `cat021 1.0.0 · egress` | one record per sample, in the track's own order. **This is the shape CAT021 has for a history and ADS-B did not**: a data block holds many records natively, so a `Track` becomes one block rather than a stream of separate frames. A track whose encoded records exceed the 65 535-octet `LEN` field is **REFUSED** with the sample count named, rather than split across blocks — splitting is framing, and framing belongs to the caller |
| `Track.samples[].observed_at` | `I021/071` per record | `cat021 1.0.0 · egress` | each sample's own time of day **does** travel, which is the sharpest single improvement over ADS-B egress, where a frame has no time field at all. The **date** still does not: a receiver dates each record against its own midnight, which is right in normal operation and wrong for a replay of an old track. Stated rather than worked around |
| `Track.track_id`, `Track.track_quality` | — | `cat021 1.0.0 · egress` | nowhere to go. I021/161 is a station's own 12-bit recycled track number, not a place to put a UUID |
| `Entity.entity_id`, `schema_version`, `source`, `affiliation`, `symbol` | — | `cat021 1.0.0 · egress` | nowhere to go. See below |

**CAT021 has an extension point, and it is still not usable for this.** Unlike AIS and 1090ES,
this format has two: the Reserved Expansion Field (FRN 48) and the Special Purpose Field
(FRN 49), and SP exists precisely for content the specification does not define. It is
nevertheless **not written to on egress**, and the reason is the one that governs the whole
document: SP's contents are settled by bilateral agreement between a sender and a receiver, so
octets we invent are octets some deployment already reads as something else. Writing a CDM
`entity_id` there would be indistinguishable, on the wire, from a local field that deployment has
used for years. The RE is worse: its layout **is** defined, by Edition 1.5, so there are no free
bits in it at all.

So `entity_id`, `track_id`, `track_quality`, `schema_version`, the affiliation, the symbol and
the whole provenance block have nowhere to go on the way out, exactly as they have in AIS and
ADS-B — and the round-trip test will name each one with its reason rather than measuring a loss
it cannot fix.

### What egress is NOT lossy for

A block this adapter ingested. The parked fields are read back, so `to_cdm()` followed by
`from_cdm()` reproduces the original data block **byte for byte** — the CAT and LEN octets, every
FSPEC octet, every item in FRN order, every spare bit as sent, the raw time integers at full
resolution, and the opaque SP payload. That is the claim `ais.py` and `adsb.py` make and it is
asserted over every ingest fixture.

**Bidirectionality is therefore in scope for 1.0.0, at the same standard as ADS-B**, and no item
prevents it. Three would have, and each is handled by parking rather than by an exemption:

1. **The high-precision time items** (I021/074, I021/076) state 2⁻³⁰ s and a CDM `Timestamp`
   renders milliseconds. Parked raw, re-emitted from the park.
2. **Every ordinary time item** states 1/128 s, which is not a whole number of milliseconds.
   Same treatment, and it is the reason the rule is stated as a rule rather than as a special
   case for the high-precision pair.
3. **Spare and unused bits** may legitimately be non-zero. Parked as sent.

### What the adapter fills that CAT021 does not state

| CAT021 | CDM field | Status | Notes |
|---|---|---|---|
| *(none — the format states a time of day and no date)* | `Event.observed_at` | `cat021 1.0.0` | the date comes from the injected clock, and the instant is the one bearing the stated time of day **nearest the receipt instant** — which is what makes midnight rollover fall out in both directions. `payload.observed_at_basis` names the item, the date's source and any rollover applied |
| *(none)* | `Event.received_at` | `cat021 1.0.0` | the injected clock. Never I021/073, which is the ground station's receipt instant and a different party |
| *(none — CAT021 states no identity)* | `Entity.affiliation` | `cat021 1.0.0` | `UNKNOWN`, with `attributes.affiliation_basis` distinguishing the ordinary unauthenticated case from the Mode 5 case this adapter declines to read |
| *(derived)* | `Entity.symbol` | `cat021 1.0.0` | from the affiliation via `symbology.sidc_from_affiliation`; `attributes.symbol_basis` says so |
| `I021/071` or `I021/073` | `Entity.valid_from` | `cat021 1.0.0` | the position's own applicability instant where there is one, else whatever the `observed_at` chain resolved; `attributes.valid_from_basis` names which, the same fallback-and-record pattern the CoT adapter uses for `@start` |
| *(none)* | `Entity.valid_to` | `cat021 1.0.0` | `None`. How long a target report stays good is a judgement about data and belongs to fusion — and I021/295's ages measure staleness backwards, not an expiry forwards |
| *(none — CAT021 has no checksum)* | `Entity.attributes` | `cat021 1.0.0` | `attributes.integrity_basis`, recording that this format carries no CRC at any level and that a structural gate is what the record passed. A consumer comparing a CAT021 contact with a 1090ES one should be able to see which of the two was checked |
| *(none)* | `Event.severity` | `cat021 1.0.0` | `INFO` where the record declares no emergency, with `payload.severity_basis` recording that this is the format's silence and not a judgement that the flight is calm |
| *(none)* | `Event.event_type` | `cat021 1.0.0` | `TRACK_UPDATE` for a record carrying position or velocity; `STATUS_CHANGE` for one carrying neither, because calling a record with no position a track update would claim one; `ALERT` where an emergency row above raises it |
| *(measured)* | `Entity.attributes` | `cat021 1.0.0` | `attributes.unavailable_fields` and `attributes.unresolved_raw` — see the common row set. The pair distinguishes "the source said it does not know" from "the source said something and the translator could not use it" |

### Where the specification is ambiguous or contradicts itself

Recorded because an adapter author will hit every one of these, and because the ADS-B lesson was
that a plausible inference is worse than a logged gap. Each is handled by parking or refusing,
never by guessing.

| # | Finding | Consequence for the adapter |
|---|---|---|
| 1 | **The REF's own edition date contradicts itself.** The cover page reads "Edition date: 21 December 2021"; the Document Characteristics table on page ii reads "Edition Date : 22/12/2021" | the pin above records the edition **number** and the SHA-256 as the identifying facts, and names the date discrepancy rather than picking one of the two |
| 2 | **`RE` on a negative rate does not say what "greater" means.** I021/155 and I021/157 are two's complement and their Range Exceeded note says "the actual value is greater than the value contained in the field". For a descending rate, greater in magnitude and greater in signed value are opposite claims | the figure is kept with an at-or-beyond-maximum flag and is never re-signed. The flag records that the bound's direction is unstated |
| 3 | **I021/090's primary subfield holds one of two different quantities and needs another item to say which.** It is "NUCr or NACv" and "NUCp or NIC" by MOPS version — and I021/210, which carries the version, is **optional** | the raw bits are parked with the version beside them and `attributes.quality_basis` states which reading applied, or that none could be established. Never a guess: NUCp and NIC are different scales |
| 4 | **NUCp 6 means two different things and the disambiguator is in a third item.** The PIC conversion table's note says NUCp 6 maps to PIC 10 for airborne messages and PIC 0 for surface ones, and that the air/ground status "is derived from the GBS-bit in I021/040" | the PIC code is parked as sent and never recomputed from NUCp. Deriving it here would mean reading one item's meaning out of another's bit, which is the cross-item join this adapter declines |
| 5 | **`ATP` cannot distinguish a surface vehicle from an anonymous address, and the specification says so.** DF18 `CF` = 1 covers self-assigned, ground-vehicle and surface-obstruction addresses alike, so "how CF=1 is encoded in ATP shall be described in the ICD of the ASTERIX system" — a per-deployment decision, with ED-129B recommending ATP = 3 | both values map to `ADSB_NONICAO`, so the ambiguity costs nothing at the identity level; the raw ATP is parked so a deployment that knows its own ICD can recover the distinction |
| 6 | **I021/140's "greater than" marker names no bound.** `0111111111111111` indicates the aircraft transmits a greater-than indication, and the item's stated range tops out at 150 000 ft — but the note does not say the marker means "above 150 000 ft" | `alt_m` is absent and the raw bits go to `unresolved_raw`. Inventing a floor the specification does not state would be a fabricated measurement, and 204 793.75 ft — the marker read as a value — is not an altitude any aircraft is at |
| 7 | **I021/148 is deprecated but not removed, and a record may carry it with I021/146.** It "shall not be used for Version 2 or higher", where I021/146 carries the same intent | both are parked as stated, with I021/210's version recorded beside them. Neither is preferred and neither is dropped: a record carrying both is telling us about its transmitter, and resolving the contradiction would erase that |
| 8 | **I021/295 gives per-item ages and no age for the position.** Twenty-three subfields cover the height, the ground vector, the identification and twenty more; the position has none, because it has its own applicability time | the ages are parked per item, and gap 13 records that the CDM can hold none of them. The absence of a position age is *correct* in the format and is what makes I021/071 the right head of the `observed_at` chain |
| 9 | **Trajectory intent point size is stated two ways.** The subfield's prose says each point comprises "fifteen octets"; the bit diagram numbers octets 1 through 16 with `REP` as octet 1, i.e. fifteen octets per point after the count | the diagram is authoritative — fifteen octets per point after a one-octet `REP` — and the fixture set carries a two-point trajectory whose total length pins the reading, so a mis-sized point fails a test rather than shifting every field after it |

Two further facts that are not ambiguities but shape the row set: the specification covers ADS-B
Versions 0, 1 and 2 **in full** and Version 3 only **partially**, with most of Version 3 in the
REF — so a Version 3 aircraft is under-described by the core document by design. And the up-to-date
list of SAC codes lives on the EUROCONTROL ASTERIX website rather than in the specification, so
nothing in this repository pins it; that is a live consequence for the fixtures, recorded below.

### Deliberately out of scope, and why

An unimplemented thing is a decision, so each one is named. "Not supported" without a reason is
indistinguishable from "nobody thought about it".

| Out | Decision |
|---|---|
| **Every other ASTERIX category** — 001, 002, 004, 008, 010, 011, 019, 020, 021's siblings, 023, 034, 048, 062, 063, 065, 240, 247 … | Each has its own UAP and its own item catalogue, and a block decoded against the wrong one yields a plausible wrong aircraft rather than an error. **CAT023 is the highest-value neighbour**: it is the ground station's own service status, and I021/015 and I021/016 exist in CAT021 precisely because not every service user receives CAT023. **CAT062** is the system-track category and is where a fused air picture actually lives. Both are deferred, not rejected; a category is an adapter |
| **Interpreting an authenticated Mode 5 reply as an affiliation** | The highest-value omission, and structural rather than effort. REF `MES` carries authenticated Mode 5 ID and Data indications, which in IFF doctrine are what "friend" means — and turning one into `FRIENDLY` is an identification decision that belongs to an IFF authority, not to a translator. Over-claiming `FRIENDLY` is also the dangerous direction. The bits are parked in full and `affiliation_basis` records the decline, so the decision is visible in every object rather than absent from the code |
| **Correlating records across data blocks** | The type-24 / CPR / pagination test, applied a fourth time. Records within one block are translated because they arrived in one payload; records in the next block are a different payload and joining them means holding a cache, which is fusion done where nothing audits it. It is also why a data block never becomes a `Track` on ingest |
| **Building a `Track` from records sharing a Target Address** | The same decision one level down. Several records in a block may name several aircraft, and grouping the ones that agree is a correlation heuristic — a decision, made invisibly, inside a translator |
| **Resolving I021/161 Track Number into an identity** | A station-scoped, recycled 12-bit number. A SAC/SIC-scoped composite would be unique across stations and would still recycle within one, so making it an identifier is a decision about identity lifetime and belongs where it can be audited |
| **Decoding I021/250 BDS register contents** | The specification's own note says the payload "is not encoded in ASTERIX but in the original Squitter format", and the BDS registers are a separate register set with their own document. `adsb.py` names a Mode S BDS adapter as a different adapter for exactly this reason; the registers are parked as raw hex with their addresses, which the never-drop rule already achieves without a row set |
| **Decoding I021/260's ARA / RAC advisory bits** | An ACAS resolution-advisory vocabulary defined outside this specification. Decoding one means adopting a second standard — the same category as AIS's DAC/FI application identifiers and `adsb.py`'s type code 28 subtype 2 |
| **Writing into the SP or RE fields on egress** | SP's contents are defined by bilateral agreement between a sender and a receiver, so an octet invented here is an octet some deployment already reads as something else. The RE's layout is fully defined by Edition 1.5 and has no free bits at all. Both are read on ingest, parked, and restored verbatim |
| **ASTERIX transport — UDP multicast, stream framing, pcap** | A data block is one payload; how it arrived is the caller's. This is the AIS fragment buffer, the ADS-B frame buffer and Legion's HTTP client, refused a fourth time for the same reason: transport is where state lives, and an adapter that holds state is a fusion layer nothing audits |
| **The SAC allocation table** | Not an item, but the same decision. The current list is published on the EUROCONTROL ASTERIX website and this repository pins no retrieved copy, so no claim is made here about which codes are allocated. The fixtures' consequence is named in their own section |

### The fixtures — planned here before they existed, like the row set

**Everything is synthetic.** No recorded ASTERIX traffic, no real ground station, no real
aircraft. Every block is built from field values by `fixtures/cat021/spec/build_fixtures.py`, which
carries the arithmetic in comments — an ASTERIX data block is raw octets and cannot carry one,
and its LEN and FSPEC are functions of its contents, so a hand-edited byte file is a mis-parse
waiting to happen. `fixtures/cat021/README.md` lists the set fixture by fixture.

**Each fixture ships twice**, on the ADS-B pattern. `<name>.cat021` holds the octets;
`<name>.parsed.json` holds exactly what the parser produces from them. The twin exists because
`lossless.unrepresented()` has no leaf structure to harvest from bytes — a byte-only fixture set
would show a green run with the never-drop rule never executed. The twin is also the **reviewable
form**: named fields in the units the specification talks in. Edit the twin, never the octets.

**The worked arithmetic lives in the fixture README**, as it does for ADS-B, because the byte
file cannot hold it. One table per fixture: octet offsets in hex, the field each octet range
carries, the raw integer, the arithmetic and the decoded value — so a reviewer can check
`0x0037 → 55 × 6.25 ft = 343.75 ft` without running anything.

#### The identifiers, and how far each "safe" claim goes

| Identifier | Fixture convention | How strong the claim is |
|---|---|---|
| **Target Address** (I021/080) | `0029xx`, the ADS-B fixture block | Same claim, deliberately: the ICAO allocation table's lowest state block begins at `004000`, so everything below it is in no administration's range. **This repository pins no retrieved copy of that table**, which is why the ADS-B README says the claim is weaker than AIS's MID 299 — and reusing the block keeps the two ADS-B-family sets recognisably one family, which is the point, because one fixture exists to show a CAT021 contact and an ADS-B contact deriving the *same* `entity_id` from the same address |
| **SAC / SIC** (I021/010) | `SAC = 0x29`, `SIC = 0x29` | **Pinned, not asserted** — see the SAC pin below. The retrieved copy of the EUROCONTROL allocation tables lists SAC `0x29` with an explicitly empty country cell in the EUR table and nowhere else, which is the page *positively showing* an unallocated code — the same strength of claim ITU MID 299 gives the AIS fixtures, and stronger than the ADS-B address block's. It echoes MID 299 and the `0029xx` block on purpose. **`SIC` carries no allocation claim at all**: a System Identification Code is assigned by the operator *within* a SAC rather than centrally, so no list exists to pin and its safety is inherited entirely from the SAC's |
| **UUIDs** | the `f1c7…-8…` version-8 convention, where one is needed | CAT021's wire form contains **no UUIDs at all** — its identifiers are a 24-bit address, a SAC/SIC pair, a 12-bit track number and a Mode 3/A code. The UUIDs in the golden files are `entity_id` and `event_id`, which are **derived** uuid5 values and therefore not free to choose. So the convention binds nothing in this set, and that is stated rather than left to look like an omission |
| **Target Identification** (I021/170) | `EXRCS01`, `EXHELO2`, `EXMAST1` | Fictional and marked as exercise traffic, matching the ADS-B set character for character |
| **Mode 3/A** (I021/070) | ordinary codes such as `4271` | 7500, 7600 and 7700 are the hijack, radio-failure and emergency codes and are deliberately absent — an emergency in this set is declared through I021/200 and REF `STA`, which is where CAT021 actually carries one |
| **Positions** | Gulf of Riga, west of Saaremaa, Ventspils, the Riga apron | Baltic-plausible, matching the other four sets, and no vessel's or aircraft's real track |

#### The SAC pin

Phase 1 proposed `0xFE/0xFE` and defended it with an assertion in the test suite. That was wrong
in a way worth recording: **an assertion on an unverified value relocates a guess from somebody's
memory into code without checking it.** It fails loudly when someone edits the constant, and never
fails for the reason that matters — the constant being wrong to begin with. So the list is pinned,
house style (`fixtures/legion/spec/openapi_pin.json`, `airtasking/SOURCES.md`), and the assertion
now sits *on top of* the pin rather than in place of one.

`fixtures/cat021/spec/sac_pin.json` carries the whole thing: the URL, the retrieval timestamp, the
byte count, the SHA-256 of the retrieved page, the full extracted allocation table, and the
evidence for every value the fixtures use or rejected.

| | |
|---|---|
| Document | EUROCONTROL ASTERIX — System Area Code (SAC) allocation tables |
| URL | `https://www.eurocontrol.int/asterix` |
| Form | **an HTML page.** The tables are embedded in it; there is no standalone SAC list and no downloadable artefact to pin. `https://www.eurocontrol.int/services/system-area-code-list`, cited by older ASTERIX specifications, returns **404** |
| Retrieved | 2026-08-23T05:14:49Z |
| Size | 142 913 bytes |
| SHA-256 (page) | `e063503cee9c623befc3b8688846aa33591ec3bc44495dd5fbb3d6eec4e8d931` |
| SHA-256 (extraction) | `094521427194a736214295d97747eb097cfab73e27d0e312e5e62556ab66542d` |
| Rows extracted | 284, across the six regional tables the page presents |

**The page hash is not the change signal, and that is measured rather than assumed.** Two fetches
four minutes apart returned **different bytes and an identical SAC table**: the page is
Drupal-rendered and embeds a fresh `form_build_id` and fresh bootstrap tab element ids on every
render — 76 diff lines, not one of them inside a table. So the **extraction** hash is what a
re-check compares, and the page hash earns its place for a different job: it identifies the copy
that was read, which is a separate claim from "nothing has changed".

That is the exact inverse of the Legion pin, where the server's ETag *is* the SHA-256 of the body
and the document's own `info.version` is the useless signal. Two sources, two pins, and in each
case the obvious identifier is the one that does not work — which is the argument for pinning by
measurement rather than by convention.

**What the pinned copy says about the value Phase 1 proposed:**

| SAC | The pinned copy says | Consequence |
|---|---|---|
| `0xFE` | **Nicaragua** — South America & Caribbean table | rejected. This was the Phase 1 proposal, chosen on no evidence; the pin is what caught it |
| `0xFF` | **Panama** | rejected — the other obvious placeholder, also allocated |
| `0x00` | **LocalAirport** | rejected, and the most dangerous of the three: it is the value an uninitialised field produces |
| `0x29` | listed with an **empty country cell**, in the EUR table and in no other | **adopted** |

The pin also separates two grades of negative evidence, because they are not equally good. A code
the page **lists with a blank country cell** is the page stating that the code has no allocation —
there are twenty, and `0x29` is one. A code **absent from every table** may be unallocated or may
simply be untabulated, so no fixture value rests on one. Only the first grade is used.

#### The fixtures, and what each one is there to catch

| Fixture | What it exercises | The defect it is there to catch |
|---|---|---|
| `airborne_position_time_of_applicability` | The ordinary case: I021/010, /040, /080, /090, /071, /131, /140, /160, /170, /020 | The whole happy path, and the two things that must not happen on it — a geometric height reaching `alt_m` correctly at LSB 6.25 ft, and the high-resolution position decoding at LSB 180/2³⁰ rather than at the coarse item's LSB |
| `airborne_position_coarse_and_high_resolution` | Both I021/130 **and** I021/131 present | The non-conforming case the encoding rule says cannot happen. I021/131 must win, both must be parked, and a disagreement beyond one coarse LSB must be recorded rather than averaged away |
| `position_time_of_message_reception_high_precision` | I021/073 + I021/074 with `FSI` = `01` | The whole-second correction. An adapter that ignored `FSI` would be a full second out here, and the fixture's expected instant is one second *after* what I021/073 alone says — the arithmetic is in the README so the difference is visible |
| `reserved_full_second_indication` | I021/074 with `FSI` = `11` | The reserved code. The high-precision value must go to `unresolved_raw` and the plain I021/073 must be used — declining to decode and losing the data are different outcomes |
| `midnight_rollover_before` | I021/071 = 23:59:58.500, clock frozen at 00:00:01.100 the next day | The rollover, run backwards. The resolved instant must be on the **previous** day, and `observed_at_basis` must say a rollover was applied |
| `midnight_rollover_after` | I021/071 = 00:00:00.900, clock frozen at 23:59:59.700 | The same rule run forwards, which is the direction an adapter that special-cased "subtract a day" would get wrong |
| `time_beyond_one_day` | I021/071 holding 100 000 s | The refusal. A modulo would move the contact by hours and leave every other check passing, so this fixture asserts a raise that quotes the item, the raw integer and the decoded seconds |
| `surface_vehicle_with_ref_ground_vector` | `ATP` = 2, `GBS` set, REF `SGV` with `HTT` = ground track and `STP` clear | The reason the REF is in scope: a surface target's only motion lives there. Also `ADSB_NONICAO`, because a surface vehicle address is not an ICAO24 address |
| `surface_stopped_track_invalid` | REF `SGV` with `STP` set and `HTS` clear over a real-looking `HGT` | Two absences of different kinds in one item. Stopped is a **measurement of stillness** → 0.0 m/s and not null; an invalid heading/track is the source declining → absent course, named in `unavailable_fields`, with its wire value in `unresolved_raw` |
| `emergency_unlawful_interference` | I021/200 `PS` = 5 | `CRITICAL` / `ALERT` at the standard's own emergency declaration, and a temporary alert or an SPI pulse in the same fixture family must **not** do the same |
| `version_three_emergency_in_ref` | I021/210 `VN` = 3, I021/200 `PS` = 0, REF `STA` first extension `PS3` = 7 | **The fixture that justifies the REF decision.** A Version 3 aircraft in distress whose core-item priority status is zero: an adapter that skipped the REF would translate this as an ordinary track update, and the test asserts `ALERT` at `CRITICAL` |
| `quality_indicators_without_mops_version` | I021/090 with all three extensions, I021/210 **absent** | The undetermined reading. `quality_basis` must say that no version could be established, and nothing may reach `Position.accuracy_m` or `Entity.confidence` — the PIC containment bound in nautical miles is the most tempting number in the format and it is still the wrong one |
| `range_check_failed_still_translated` | I021/040 second extension with `RCF` set | The row where the specification asks for filtering. The record must be translated **in full** with the flag parked; a fixture that produced no objects would mean the adapter had started making suppression decisions |
| `duplicate_address` | `ATP` = 1 | The identity caveat. `ADSB_NONICAO`, and `attributes.identity_caveat` recording that this entity may conflate two airframes |
| `obstacle_line` | I021/020 = 24 | The one place an emitter category refines the entity type: `FACILITY`, agreeing with `adsb.py`'s category set C line-obstacle mapping through a different vocabulary |
| `two_records_one_block` | Two records, two different target addresses | Four objects from one payload, in block order, with `record_index` and `record_count` on each — and the assertion that they are two entities and **not** one track |
| `trajectory_intent_two_points` | I021/110 with `REP` = 2 | The repetitive item's stride. Fifteen octets per point after a one-octet count: a mis-sized point shifts every field after it, and the block's total length is what pins the reading |
| `mode_five_authenticated` | REF `MES` subfield #1 with `ID` and `DA` set | The declined interpretation. `affiliation` must be `UNKNOWN` and `affiliation_basis` must say that an authenticated IFF indication was present and deliberately not read — a test that asserts a *refusal to decide* rather than a decision |
| `special_purpose_field_opaque` | An SP field of unknown content | Parked verbatim on ingest, restored verbatim on egress, and never written to for an object that did not arrive with one |
| `spare_bits_nonzero` | A conforming record with spare bits set to 1 | §4.3's recommendation is not a requirement. The byte-exact round trip must survive it, which it only does if the spare bits are parked as sent rather than normalised |

An `egress/` subdirectory holds the CDM-side fixtures — an `Entity` that never came from CAT021
(exercising the station-configuration refusal and its absence), and a `Track` of three samples
that becomes one data block of three records. Reference documents, if any are ever added, go in a
`spec/` subdirectory and not beside the payloads: `harness.run()` replays every **file** in a
fixture directory through `to_cdm()`, so a document sitting next to the blocks is fed to the
adapter and fails as an unrecognised payload.

## STANAG 4676 / AEDP-12 — NATO ISR Tracking Standard (NITS), ingest and egress

Implemented by `adapters/stanag4676.py` (bidirectional). Ingest translates one `NITSRoot` object
into an `Entity` and a `Track` per `TrackData`, plus an `Event` per `Detection`, `MotionEvent`,
`TrackLinkage`, `ProcessedTrack` and retraction-only `TrackSegment`; egress turns them back into
one STANDALONE `NITSRoot` document.

**Every row below was written and reviewed as a specification BEFORE any code existed**, with
`not yet` in the status column, exactly as the Legion and CAT021 row sets were. The markers now
read `nits 1.0.0` because the adapter runs them, and that difference is the whole reason the
status column exists. Three Phase 1 decisions were overturned on review before any code was
written — one Track per `TrackData`, `essence` never touching `source.synthetic`, and `FAKER`
being `FRIENDLY` — and each is a settlement below rather than a footnote.

This is not a 42-item data category. It is a **full UML data model**: 48 classes and 273
attributes, from `NITSRoot` down through `TrackMessage`, `TrackData`, `TrackSegment` and
`TrackPoint`, out through the `Detection`/`Evidence` tree, the identity classes and the common
geometry types. Every class and every attribute has a row, with the cardinality the standard
gives it. Where the standard states no multiplicity the convention is `[1]` — mandatory — and
that convention is the standard's own, stated in its CONVENTIONS section. A class that is
declined appears in the declines table with a reason, and the reasons say
*deferred* where deferred is the truth.

**This section supersedes the placeholder row set that stood here before it.** That table had
sixteen rows against `TrackMessage/trackUUID`, `Track/trackNumber`,
`TrackPoint/trackPointPosition/latitude`, `IdentityIndicator` and `TrackMessage/security` — every
one of which is an **Edition A** name for a class that Edition B does not have. Leaving it beside
this one would have left the document asserting two incompatible models of the same format. Its
two live findings, gap 3's quality scale and gap 4's velocity vector, are carried forward below
and gap 3's premise is corrected: the field it was written about does not exist in Edition B.

### The pin

STANAG 4676 is a ratified NATO standardization agreement, so like CAT021 and unlike Legion it
does not need a hash to be trustworthy. The hashes are recorded anyway, for the same reason: an
edition number names a **document** and a SHA-256 names the **copy that was read**, and those are
two different claims.

| | |
|---|---|
| Ratification wrapper | **STANAG 4676 Edition 2**, 13 October 2021, promulgated by the NATO Standardization Office (NSO(NAFAG)1063(2021)JCGISR/4676). Supersedes STANAG 4676 Edition 1 of 20 May 2014. Names exactly one standard: "AEDP-12, Edition B" |
| SHA-256 (wrapper) | `5c74626102ca0b24735a98c6e0b67191d241afec075f2298c72e51b6223f8a9f`, 255 250 bytes, 5 pages |
| **The target** | **AEDP-12, NATO Intelligence, Surveillance and Reconnaissance Tracking Standard, Edition B Version 2, March 2022**. Every mapped element below cites this document |
| SHA-256 (target) | `c55573231a5882f031862b06589d5a7abaeda9cf7c0b7a55d81843eeb7dc138b`, 6 785 016 bytes, 150 pages |
| Implementation Guide | **AEDP-12.1, NITS Implementation Guide, Standards Related Document (SRD), Edition A Version 1, March 2022** |
| SHA-256 (guide) | `7a4267fced81c760c8a8b487a70b9bb8507b9f765cb32bc4a0a97996b0c4341d`, 6 815 298 bytes, 192 pages |
| Compatibility context only | AEDP-12 **Edition A Version 1**, May 2014 — the Edition 1 model. Read for the delta below and for nothing else |
| SHA-256 (2014) | `a9e88c81369ff4f13a9d4d7e457de55c6cefcc024162efe5a198e395d8898814`, 3 719 388 bytes, 148 pages. **A reseller copy**, per-page watermarked to the licensee, so this hash identifies that copy and not the NATO original — which is one more reason it is context and not a target |
| **The XML schema** | **NOT PINNED, and not obtainable here** — see the encoding settlement |

**The guide is normative only where it says so.** AEDP-12.1 §1.3 states in its own words that
"the information in this guide is informative but not mandatory", and §1.2 that it is "not
'directive' … but is written as 'suggestive' guidance". It then marks eighty-seven passages
with an explicit **AEDP-12 Requirement** callout, and those passages restate obligations from the
standard itself. So the guide is read here for two things and no others: the **AEDP-12
Requirement** passages — ID usage, confidentiality labelling, polygon vertex ordering, the
timestamp calculation, coordinate-frame arithmetic — and its conventions, its compliance-profile
annex and its XSD/EXI guidance. Everywhere else it is background. **Where the guide and Edition B
Version 2 differ, the 2022 standard wins.**

Two places where reading the guide earns something the standard does not state:

- The polygon winding rule gains **"when viewed from above"** (AEDP-12.1 §B.1.10), which the
  standard's own text omits. For a 3-D polygon that is the difference between a determinate rule
  and an undetermined one.
- The XML instantiation **"requires that the raw 128-bit UUID value be encoded as
  `xs:base64Binary`"** (§B.1.4) — 22 characters, not the 36-character canonical form. Nothing in
  Edition B says this, and an adapter that emitted canonical UUIDs would produce documents that
  fail schema validation on every identifier in the file.

### Settlement 1 — Edition B Version 2 is the only target, and Edition 1 is a different adapter

The two editions are not two versions of one format. **The standard says so itself**, in §2.1.1.1:
"STANAG 4676 Ed. 2 is incompatible with STANAG 4676 Ed. 1 … it was determined that the best
course of action … was to **re-architect the data model and XML-based syntax from scratch**."
Three of those re-architectures are load-bearing for this row set:

| | Edition A / STANAG 4676 Ed. 1 (2014) | Edition B v2 / Ed. 2 (2022) |
|---|---|---|
| **Root** | `TrackMessage` → `Track` → `TrackItem`, where `TrackItem` is *abstract* with two specializations, `TrackPoint` and `TrackInformation` | `NITSRoot` → `TrackMessage` → `TrackData` → `TrackSegment` → `TrackPoint`. `NITSRoot` is new, `TrackData` replaces `Track`, `TrackSegment` is new and has no 2014 counterpart, and `TrackItem` is gone entirely |
| **Time** | absolute per item: `TrackItem.trackItemTime`, an ISO 8601 `dateTime` on every point | relative: `TrackMessage.baseTime` (absolute, UTC) plus integer `relTime` steps scaled by `TrackMessage.relTimeIncrement`. A point carries an integer, not a time |
| **Confidentiality** | an **inline `Security` class**, carried on `TrackMessage`, `Track` and `TrackItem` alike, with a `ClassificationLevels` enumeration (`TOP SECRET`, `SECRET`, `CONFIDENTIAL`, `RESTRICTED`, `UNCLASSIFIED`), a `securityPolicyName`, control systems and dissemination controls | **silence.** §2.1.1.6: "The core STANAG 4676 data model is silent on confidentiality metadata", deferring the whole subject to STANAG 4774 / ADatP-4774 on a syntax-by-syntax basis |

Each of the three is a difference an adapter cannot paper over with a mode flag. The root
restructure changes what objects exist and therefore what the CDM's four kinds are built from;
the time model changes whether a point carries an instant or an offset, and therefore whether the
adapter needs a message-scoped time base at all; and the security model changes whether a
classification is a typed field with an enumeration or an opaque XML fragment from another
standard's namespace. A single adapter spanning both would carry two parsers, two time models and
two classification stories behind one name, and every bug in it would be a question about which
half was running.

**So a 2014-edition feed is out of scope for 1.0.0, and it is a separate adapter rather than a
mode.** That is not a deferral of effort; it is the same boundary the ADS-B and CAT021 adapters
draw between 1090ES and ASTERIX — same subject matter, different wire model, two adapters.
Nothing in this row set decodes an Edition 1 document, and an input whose `nitsVersion` reads
`A.1` — or whose root element is `TrackMessage` rather than `NITSRoot` — is **refused with the
version quoted**, never decoded on a best-effort basis. A best-effort decode of Ed 1 against Ed 2
would find a `TrackMessage` at the root, no `baseTime`, and would produce a message full of track
points at the epoch.

### What the adapter's input IS — one NITSRoot object, and nothing else

`to_cdm()` takes **one `NITSRoot` object**: one XML instance document whose root element is
`NITSRoot`, or the already-parsed dict a fixture twin holds — the same `bytes | dict` shape
`adsb.py` and `asterix_cat021.py` accept, for the same reason (the harness's lossless check has
no leaves to harvest from bytes).

The standard makes this boundary unusually easy to draw, because it draws it itself. §2.5.1: "A
conformant instantiation of the model **shall contain one and only one NITSRoot object**", and
concatenating several into one XML document "results in non-conformant XML". §2.1.1.2: "The
method by which STANAG 4676 data are transmitted is out of scope for this standard." So the
adapter does not own, and must never acquire, a socket, a file-server poller, a MIME multipart
splitter, a stream framer or a cache of previously transmitted objects. Splitting a stream into
`NITSRoot` objects is the caller's job, and the standard says as much.

### What one NITSRoot becomes

| NITS | CDM |
|---|---|
| `NITSRoot` | the envelope. Parked on every object the document produces; never an object of its own |
| `TrackMessage` | the time base and the framing. Parked; never an object of its own |
| `TrackData` | one **`Entity`**, from its `TrackedObject`s, and one **`Track`** from all the points of all its segments |
| `TrackSegment` | **not an object.** A temporal and administrative subdivision of the one `Track`; its own attributes are parked against the sample range it covers |
| `TrackPoint` | one **`TrackSample`** inside its `TrackData`'s single `Track` |
| `Detection` | one **`Event`**, `DETECTION` |
| `MotionEvent` | one **`Event`**, `STATUS_CHANGE` |
| `TrackLinkage` | one **`Event`**, `STATUS_CHANGE` — carried, never acted on |
| `ProcessedTrack` | one **`Event`**, `STATUS_CHANGE` — carried, never acted on |
| a retraction-only `TrackSegment` | one **`Event`**, `STATUS_CHANGE`. It contributes no samples, and a retraction is data — so it becomes an object of its own rather than being dropped |

**One `Track` per `TrackData`, and `TrackSegment` is not an identity boundary.** This is the
structural decision the row set turns on, and the standard settles it in the class definition
itself. §2.5.25: a `TrackSegment` "encapsulates zero or more track points **adjacent in time**",
and it exists so that a producer can "later refer to a group of points in order (for example) to
update the confidence of or invalidate the points, without restating … each individual point",
can "report the track status of the included track points", and can "associate different track
source information with just a specific portion of **the track** than specified for the track as
a whole".

Every clause of that is **temporal and administrative subdivision of one track**, not a branch
into competing histories. The standard's own vocabulary says the same thing twice more: a segment
carries source information for "a specific portion of the track", and "if the data producer deems
it unnecessary to break **a track** into multiple track segments, then all track points of the
track can be included is a single `TrackSegment` object". A thing you may or may not break into
pieces at your discretion is not the thing that has the identity — **`TrackData` is**, and a row
set that minted a `track_id` per segment would make the number of tracks a consumer sees depend
on a producer's private choice about how to chunk its output.

So:

- `Track.track_id` is derived from `TrackData.uid`, else its `lid` as the `lidScopeUID` composite,
  else the `TrackedObject` key, with `ids.derive_with_basis` reporting which. It never depends on
  a segment. `ids.derive`'s `kind` argument keeps the track and entity id spaces apart when both
  fall back to the same `TrackData` key.
- **Every point of every segment becomes a sample of the one `Track`, in document order.**
- The segments themselves are parked: `attributes.nits_segments[]` records, per segment and in
  order, its `uid`/`lid`, its `status` and initiation or termination reason, its `confidence`,
  its `comment`, its `segmentSource`, and **the half-open range of sample indices it covers**. A
  consumer that needs to know which points a producer invalidated, or which sensor produced the
  middle third of a history, reads it there.

**Per-segment source information is parked against its sample range, and this is where gap 16
bites hardest.** §2.5.25's whole third purpose is to let a producer say "these points came from
that sensor and those from this one", and the CDM's `TrackSample` has two fields and no extension
bag — so a fact the format attaches to a *range of points* can only be recorded as an index range
in the owning `Entity`'s attributes. That works, it is fragile under any list surgery, and it is
**gap 16**'s argument stated on the one class the format designed for the purpose.

**Points are emitted in document order and a document whose points run backwards is refused, not
sorted — and the rule spans segments as well as sitting inside them.** That
is Legion's rule, verbatim: "sorting would hide a source defect the caller needs to see". The
format promises adjacency in time *within* a segment and promises nothing about the order of
segments, so a producer that emits segments out of order, or that emits segments overlapping in
time, produces a `Track` the CDM refuses. The refusal quotes both instants and both segment
identifiers.

**The case that costs, named rather than buried.** `TrackSegment.confidence`'s own description in
Table 2.5.25-1 offers a multi-hypothesis tracker that "generates 10 hypothesized tracks from a
sequence of low-SNR … motion images", is unsure "which of these hypothesized track segments is
part of the actual track, so it reports all of them" with various confidences. If such a producer
puts all ten under one `TrackData`, their points overlap in time and **this adapter refuses the
document.** That is a deliberate cost and not an oversight: the alternative readings are to
interleave ten incompatible paths into one sample list, which is a physically absurd track, or to
mint ten `track_id`s from a producer's chunking, which is the thing this settlement rejects. A
refusal that names the overlapping segments is the only one of the three that leaves the decision
where it can be made — with the consumer, who can re-request, split by hypothesis, or accept the
highest-confidence segment, none of which a translator may choose on its behalf. Stated once more
because it is the clause an implementer will be tempted to soften: **never reassembly, and never
silent best-hypothesis selection.** The refusal quotes the hypothesis structure — how many
segments overlapped and what confidence each carried — so a consumer can act on it without
re-reading the document.

**An empty `TrackSegment` contributes no samples, and a retraction-only one becomes an `Event`.**
`TrackSegment.tp` is `[0..*]` — zero track points is conformant — so a segment with no points is
not part of the history; it is a *statement about* the history, which is precisely what the format
uses it for (§2.1.1.2.3 c: a segment restated with the same ID and `confidence.valid = FALSE` and
nothing else). It becomes an `Event` carrying the statement verbatim, alongside whatever `Track`
the `TrackData`'s other segments produced. A `TrackData` whose segments hold **no** points between
them yields an `Entity` and no `Track` at all, because `Track.samples` has `min_length=1`.

### Settlement 2 — Time: an absolute base and integer steps, and no rollover to reconstruct

`TrackMessage` carries `baseTime` (`DateTime`, `[1]`) and `relTimeIncrement` (`double`, `[1]`,
"the time, in decimal seconds, equal to 1 relative time increment"). Every `relTime` anywhere
inside that message — on a `TrackPoint`, a `Detection`, a `DynamicSourceInformation`, a
`TrackLinkage`, an `IDSourceInformation`, a `MotionEvent` — is an integer count of those steps.
The standard states the arithmetic in one line, in §2.5.10 and again as an **AEDP-12 Requirement**
in guide §B.3.1:

    t_absolute = TrackMessage.baseTime + relTime × TrackMessage.relTimeIncrement

**Unlike CAT021 there is nothing to reconstruct.** CAT021 states a time of day with no date, so
the adapter has to supply a date and resolve midnight rollover in both directions. Here
`baseTime` is absolute and in UTC, so the date arrives with the data and the injected clock is
not consulted for it at all. That is a strictly easier problem and it should be said plainly
rather than dressed up.

**An omitted `relTime` means zero, and that is the standard's rule, not an assumption.** §2.5.10:
"if a `relTime` attribute is defined for an object … but that individual `relTime` is omitted from
the data stream, then the time associated with that object is equal to the `baseTime`". So an
absent `relTime` is a *stated* instant, and it does **not** land in `unavailable_fields` — the
source has not said it does not know; the format has said the value is zero. **`MotionEvent` is
the one exception and says so in its own words**, and it is handled where it is mapped.

#### The parking rule, which is CAT021's and Legion's reached a third time

`relTimeIncrement` is a `double` in decimal seconds and `relTime` is an integer, so their product
is an arbitrary real number of seconds. A CDM `Timestamp` renders exactly three decimal places
(`times.render`, and deliberately). A `relTimeIncrement` of `1/128` s, or `0.0333667` s for a
29.97 fps motion-imagery frame rate — which is precisely the case the relative time model exists
to serve — produces instants that are not whole milliseconds.

So the rule is the one CAT021 reached for 1/128 s and Legion reached for ECEF: **the raw integers
are the record and the `Timestamp` is a derived, one-way view of them.** `baseTime` as written,
`relTimeIncrement` as written and every `relTime` as written are parked verbatim at
`attributes.nits_times`, and egress **re-emits from the park** rather than recomputing a `relTime`
from a millisecond `Timestamp`. Recomputing would quantise every instant in the message to a
millisecond grid the producer never used, and the round trip would report it.

`attributes.time_basis` records `baseTime`, `relTimeIncrement`, whether the product was a whole
number of milliseconds, and — where it was not — that the CDM instant is a truncation of a value
the park still holds exactly.

#### The `observed_at` chain, stated in full

`Event.observed_at` is "when the SOURCE saw it", and `payload.observed_at_basis` names the step
taken on every object:

1. The object's **own `relTime`**, resolved through the equation above. This is the answer for a
   `Detection`, a `TrackLinkage` and a `TrackPoint`-derived sample.
2. For a `MotionEvent`, **`startRelTime`** — and only that. The class states an end time too and
   it is never used as the observation instant.
3. `TrackMessage.baseTime`, where the class carries no relative time at all. **`ProcessedTrack` is
   the only class in the model in this position**: it has `type`, `uid`, `lid`, `confidence` and
   four reference lists, and no time attribute of any kind. The basis says so rather than
   implying the producer stated an instant.
4. There is no fifth step. Every object this adapter emits an `Event` for sits under a
   `TrackMessage`, and `baseTime` is mandatory there, so the chain cannot fall through.

`Event.received_at` is the injected clock, always — the one field an adapter invents rather than
reads. It is never `NITSRoot.msgCreatedTime`, which is when the *producer* wrote the file, and
never `IDSourceInformation.relTimeExchange`, which is when a *third party* transmitted a
declaration.

#### One `Entity` state out of a history of points, and both halves from the same point

A `TrackData` yields a history — that is the `Track` — and an `Entity`, which is a state at an
instant. Which instant is a decision, and it is made once and applied to both halves:
**`Entity.position` and `Entity.kinematics` both come from the LAST `TrackPoint` in document order
that yields a position**, and `Entity.valid_from` is that point's own instant.

Taking them from different points is the failure worth naming. A position from the newest point
and a velocity from the newest point that happens to *carry* one would put two instants into one
`Entity` with nothing recording the offset — which is precisely the defect CAT021 met in its own
data and recorded as **gap 13**, and it would be manufactured here rather than inherited. So if
the last positioned point states no velocity, `kinematics` is `None`; it is never back-filled from
an earlier point, because §2.5.26 forbids exactly that inference: "if the object's velocity is
omitted from a `TrackPoint`, the data consumer **shall not infer** that the object is travelling
at the same speed as it was at a previous point in time."

`attributes.valid_from_basis` names the point the state came from, and
`attributes.nits_track_first_instant` records the history's own earliest instant separately, so
"when this state began" and "when this track began" stay two different facts. A `TrackData` with
no positioned point at all yields an `Entity` with `position: None`, `kinematics: None` and
`valid_from` = `baseTime`, with the basis saying so. `Entity.valid_to` is `None` — see the
track-status row, where the argument is that a tracker terminating a track is not the object
ceasing to exist.

**Every other point's velocity is parked, per point.** That is **gap 16** again from a second
direction: `Kinematics` hangs off `Entity` and there is exactly one of it, while NITS states a
full state vector at every point in the history.

#### A missing or malformed `baseTime` is a refusal that quotes the value

`baseTime` is `[1]`. A document without it has no time base, and every `relTime` in it is an
integer with no meaning. **The injected clock does not substitute.** The clock supplies
`received_at`, and it supplies `msgCreatedTime` on egress, and it is used nowhere else in this
adapter — writing the receipt instant into a message-wide time base would date every track point
in the file to the moment we happened to read it, and every other check would pass.

Three refusals, each quoting the offending value:

| Case | Why a refusal and not a repair |
|---|---|
| `baseTime` absent | the whole message's time base is missing. Emitting the points at the receipt instant would produce a plausible track at the wrong time |
| `baseTime` carries **no UTC offset** | the standard says the value "**should** be reported in Coordinated Universal Time" — *should*, not *shall* — so a naive value may be local. Assuming UTC moves every point in the message by whole hours. Note this is a **stricter** rule than `times.parse`, whose declared naive-is-UTC assumption is right for a receipt timestamp and wrong for a time base that scales an entire message; the refusal happens before the value reaches it |
| `relTimeIncrement` absent, zero, negative or non-finite | `[1]` and a scale factor. Zero collapses every instant in the message onto `baseTime`, which is a plausible-looking file of simultaneous track points |

An offset-bearing value that is not `Z` is **converted**, not refused: `+02:00` is an exact
statement of an instant and converting it loses nothing. The original string is parked.

### Settlement 3 — Confidentiality: the model is silent, the syntax is not, and neither is optional

Edition B §2.1.1.6 is explicit that "the core STANAG 4676 data model is silent on confidentiality
metadata" and "leaves the issue … to be defined on a syntax-by-syntax basis". That silence is a
statement about the *UML*, and it is routinely misread as a statement about the format. The XML
syntax — the only syntax the standard defines, and therefore the only one an adapter meets — is
not silent at all. Edition B Annex B.2 and guide §D.3 / §E.2, both carrying the **AEDP-12
Requirement** callout, say the same thing:

> The XML syntax instantiation of STANAG 4676 uses, at a minimum, the STANAG 4774 confidentiality
> label elements. The root `NITSRoot` object **must** contain the `originatorConfidentialityLabel`
> element and may also contain the `alternativeConfidentialityLabel` element and the
> `metadataConfidentialityLabel` element.

So a conformant NITS XML document **always carries a confidentiality label**, and any portion of
it that requires its own marking carries one too. The binding is named: namespace
`urn:nato:stanag:4774:confidentialitymetadatalabel:1:0`, schema file
`stanag4774_confidentialitymetadatalabel.xsd`, which must sit in the same directory as the 4676
XSD, with binding guidance in **TN-1491 Edition 2, "Profiles for Binding Metadata to a Data
Object"**. Nation-specific markings ride *inside* those elements — the guide's own §E.3 example
nests US `ism`/`arh` attributes within a `slab:originatorConfidentialityLabel`.

**Where a label goes today: `attributes.confidentiality_label`, verbatim, as the serialised XML
fragment.** Not parsed into `Classification` / `PolicyIdentifier` / `Category` fields, not reduced
to a string like `"NATO SECRET"`, and not normalised. Three reasons:

1. **It is carried, not interpreted.** A confidentiality label is an access-control artefact whose
   meaning is defined by the policy named inside it, and a translator does not hold policy. The
   CDM has no field that can hold one (**gap 12**), so the honest thing is a faithful copy.
2. **Reducing it would destroy the part that matters.** A 4774 label is a structure —
   `PolicyIdentifier`, `Classification`, and any number of `Category` elements typed
   `RESTRICTIVE`, `PERMISSIVE` or `INFORMATIVE`. The RESTRICTIVE categories are the caveats. A
   consumer that received only `SECRET` would have a marking that looks complete and has lost the
   compartment.
3. **Egress has to put it back byte-for-byte.** A re-serialised label that differs from the
   original — a reordered attribute, a dropped `INFORMATIVE` category, a re-emitted
   `CreationDateTime` — is a different label, and whether it is the *same* label is not a question
   a track translator is competent to answer.

Keyed by the element it came from and by the path it was attached to:
`attributes.confidentiality_label.originator`, `.alternative`, `.metadata`, and
`attributes.confidentiality_label.portions[]` for portion markings, each recording the NITS class
and identifier of the element it marked. Nation-specific extensions ride inside the verbatim
fragment because they are inside it on the wire.

**The adapter never invents, downgrades, or strips a label, and on egress there are exactly three
paths.** The root element must carry an `originatorConfidentialityLabel`, so every emitted document
has to get one from somewhere, and "somewhere" is enumerated rather than left to a default:

| Where the label comes from | When | What is recorded |
|---|---|---|
| **the park** | the object round-tripped from a NITS document | the exact fragment that arrived, re-emitted byte-for-byte. `attributes.confidentiality_label_basis` says `round_tripped` and names the source document |
| **configuration** | a CDM-native object — a track from AIS, ADS-B, CAT021, Legion or CoT — for which the deployment has supplied a label as an explicit argument | the supplied label, with the basis saying `configuration_supplied`, naming the configured value and stating that no source stated it. **A deployment declaration, the same category `source.synthetic` is in and the same category settlement B protects** — a fact about the deployment that a payload may not set |
| **nowhere** | neither of the above | **refusal**, naming the object. Emitting would mean writing a marking nobody applied |

A **silent `UNCLASSIFIED` default remains forbidden** and is the reason the third row exists rather
than being folded into the second. There is no safe made-up value: `UNCLASSIFIED` is the dangerous
direction, a label copied from a neighbouring object is a marking its originator never applied to
*this* one, and an empty element is non-conformant. An egress path that could invent a
classification is worse than an egress path that does not exist — but a refusal in the case where
the deployment *has* declared a label would be a refusal with no argument behind it, which is why
the middle row is a path and not an exception.

Note where this sits in the standard. Edition B's **core model is silent** on confidentiality
(§2.1.1.6) and defers the subject **per syntax** to STANAG 4774 / ADatP-4774; the XML syntax is
the one syntax the standard defines, and it is where the label becomes mandatory. So the refusal
is not this row set being strict about a model that says nothing — it is the row set obeying the
only syntax binding the standard has published.

**Gap 12 gets a STANAG 4676 paragraph** below. What NITS adds to it that Legion did not is that
here the label is **mandatory in the syntax** and **structured by another ratified standard** — so
the gap is no longer "one vendor states a `top_classification` string"; it is "a NATO standard
requires a typed label on every document and the CDM has nowhere to put it".

### Settlement 4 — Encoding: plain-text XML in 1.0.0, EXI deferred

The standard defines exactly two conformant encodings and says so twice. Edition B §2.1.1.8, and
guide §B.1.9 under an **AEDP-12 Requirement** callout: "This standard contains an implementation
independent model as well as two options for encoding the model, **plain-text XML and EXI** …
Conformant implementations **shall** exchange data using one of these two encodings … The
Custodial Support Team **recommends the use of EXI** over plain-text encoded XML."

**1.0.0 targets plain-text XML. EXI is deferred, not rejected, and it is in the declines table
with this reason.** Three grounds, in order of weight:

1. **EXI is a codec, not a second mapping.** It is a binary serialisation of the same XML
   infoset. Every row in this document is a statement about the *data model*, and the row set for
   an EXI feed would be character-for-character identical. So deferring EXI defers a transport
   concern, not a mapping; it is the smallest thing that can be deferred here and still be worth
   naming.
2. **Schema-informed EXI needs the XSD, and the XSD cannot be pinned here** — see immediately
   below. An EXI decoder configured for schema-informed mode against a schema we could not obtain
   would be a decoder we could not test against the document that defines it.
3. **EXI has a documented trap that bites this format specifically.** Edition B §B.3 and guide
   Annex F both warn that an EXI encoder treats a namespace prefix inside an *attribute value* as
   an ordinary string, so a decode can rename `xmlns:acme` to `xmlns:a` and silently break every
   `xsi:type` that still says `acme:`. STANAG 4676 expresses **every abstract type** through
   `xsi:type` — §"Data Model" in the CONVENTIONS: "a conformant NITS file must specify the
   concrete type of each of those attributes … using the XML Schema Instance type attribute (e.g.
   `<outline xsi:type="Polygon">`)". So on this format the trap does not corrupt an edge case; it
   makes every `Shape`, every `Ellipsoid` and every `Polygon` unresolvable. The mitigation —
   fidelity options preserving namespace prefixes — is a setting on the **encoder**, which is the
   producer's side and not ours, so an EXI reader here would be depending on a configuration it
   cannot verify.

#### What Phase 2 needs and Phase 1 could not obtain: the XSD

This is the largest known hole in the row set and it is named here rather than discovered later.

**The XML schema is normative for conformance** (Edition B §B.6, guide §D.6: "The XML schema
defined within the standard is normative for conformance only"), and it is **not distributed with
the standard**. Edition B §B.5: the `.xsd` and `.xml` files "are available on the NATO Defense
Investment Web Site (DiWEB) … Request access through your respective NATO JCGISR National
Representative", with the guide adding an APAN mirror. Neither is a public URL and neither can be
hashed into this repository, so **no pin exists for the one document that fixes the syntax**.

What that costs, precisely:

- **Element names are not guaranteed to equal the UML attribute names in the left column below.**
  The standard says so: to fight file size, "many tags have been reduced in size to as little as
  two letters". Several are visible in the model already — `tp` for a track point, `cs` for a
  coordinate system, `sm` for a sensor measurement, `im` for an image, `rs`/`cs` for pixel runs —
  and there is no way to know from the PDF which of the other 273 are shortened.
- **Attributes versus elements.** §2.1.1.7 says the UML's "attributes" are XML *elements* in
  almost every case, with `type` the exception — it is always an XML attribute. "Almost every"
  is not a list, and the UML diagrams mark true XML attributes with a `>` prefix that the
  extracted text of a PDF does not preserve.
- **The `UUID` and `CovarianceMatrix` classes carry a "core class value"** rather than a named
  attribute, i.e. the element's own content. How that content is typed is a schema fact.

**What 1.0.0 ships is a PROVISIONAL binding, and it is a table rather than code.** The adapter
reads and writes XML today by binding UML attribute names to element names through a single
constant, `ELEMENT_NAMES`, which is empty: nothing is renamed because nothing is *known* to be
renamed. Every divergence the XSD turns out to carry is a line in that table, not a change to the
reader. The parsed-dict path is unaffected either way, every fixture ships as a twin — a
`.nits.xml` and a `.parsed.json` — and `test_the_xml_twin_and_the_parsed_twin_produce_identical_
cdm` asserts the two produce byte-identical CDM, which is what makes the provisional binding
*checkable* rather than merely declared. It found two reader defects on its first run.

So the left column below names **data-model attributes**, and the mapping is stated at the layer
the standard itself calls implementation-independent: "This document defines the data type of each
attribute in a way that is agnostic to any specific data encoding." That layer is complete and
reviewable now. The **syntax binding** — element names, attribute-versus-element, the base64
UUID encoding, `xsi:type` placement — is a second layer, and **Phase 2 cannot start until the XSD
is obtained and pinned by SHA-256**. Writing an XML parser against guessed element names would
produce an adapter that passes its own fixtures and fails on the first real document.

### Settlement 5 — Compliance profiles: STANDALONE is read and emitted, DATASTREAM is read and never resolved

`NITSRoot.profile` is `ComplianceProfile [1..*]` with two registered literals, and additional
profiles may be registered with the custodian. The two differ in exactly one respect, and it is
the one that decides this settlement:

| Profile | What it means | Standard |
|---|---|---|
| `STANDALONE` | every reference resolves **inside this NITSRoot object**, with the referent appearing before the reference | §2.1.1.2.2 |
| `DATASTREAM` | a reference may point at an object in a **previously transmitted file**; each file is incomplete on its own and "the entire collection of transmitted files is still complete" | §2.1.1.2.1 |

**The adapter reads both and emits `STANDALONE` only.** Resolving a DATASTREAM reference means
holding objects from earlier payloads and matching them by UID or LID — a cache, keyed across
payloads, inside a translator. That is the AIS multi-fragment buffer, the ADS-B CPR frame pair,
Legion's pagination and CAT021's cross-block correlation, refused a fifth time and for the fifth
time for the same reason: state is where fusion hides.

**A DATASTREAM document is not refused.** Its track points are still track points and its
positions are still positions; refusing it would drop data the payload does carry in order to
protest data it does not. So it is translated on its own terms, and every reference that does not
resolve within the payload is recorded:

- `attributes.unresolved_references` — a sorted list, each entry naming the referring class and
  attribute (`TrackSource.sensorUID`), the raw identifier, and the class it is constrained to
  point at. The standard makes that last part knowable: §2.1.1.2.3 "these reference attributes are
  restricted to only pointing to objects of a specific class … providing the ID of a
  `TrackerInformation` object using the `sensorUID` attribute of the `TrackSource` is
  nonconforming."
- **These do not land in `unavailable_fields`,** and the distinction is Legion's embedded-entity
  finding reached again. `unavailable_fields` means *the source stated it does not know*. A
  DATASTREAM reference is the opposite: the source knows, has said so, and said it in a different
  file. Conflating the two would manufacture an assertion of ignorance the producer never made.
- `attributes.profile_basis` records every literal in `profile`, which ones the adapter
  recognised, and that no reference was followed.

Four further consequences, each because the standard says so:

- **A file may declare both profiles** — the cardinality is `[1..*]` and §2.5.1 notes "a single
  file can be conformant to multiple profiles". A document declaring both is read as STANDALONE
  and its references are expected to resolve; the ones that do not are recorded as above.
- **An absent profile is not a claim.** §2.5.1: "the data consumer shall not infer that a file is
  not conformant with a profile if that profile is not explicitly indicated." So the adapter never
  concludes "this is not STANDALONE" from silence.
- **An unregistered profile literal is parked, not refused.** New profiles are registerable, and
  the XSD expresses every enumeration as a union with `xs:string` (below), so an unknown literal
  is schema-valid.
- **A DATASTREAM document may legitimately contain no `SensorInformation` or `TrackerInformation`
  at all**, because the standard requires only that the *complete set* of files include one. That
  absence is structural, not an assertion of ignorance, and is recorded the same way.

On egress the adapter emits `profile = STANDALONE`, one `NITSRoot`, and every referent inline
before its reference. If a CDM object carries a parked reference the adapter cannot place inside
the document it is emitting, the emit **refuses and names the reference** rather than writing a
dangling UID — a dangling reference in a STANDALONE file is a non-conformance that a consumer
discovers as missing sensor metadata, silently.

### Settlement 6 — Coordinates: six systems, one rule, and three of them do not produce a Position

`CoordinateSystemType` has six literals and they appear on `Dynamics.cs`, `Shape.cs` and
`PositionPoints.cs` — so the question is asked of every position, every outline, every detection
centroid, every tripwire and every field-of-view polygon in the model.

**The Legion settlement generalises, and this is where it becomes a rule rather than a
precedent.** In every case: **`Position` is a derived, one-way view; the source coordinates are
the record.** The array as written, its `cs`, its `dims`, and the `cftUID`/`cftLID` it referenced
are re-emitted verbatim into `attributes.nits_position` (or `attributes.nits_geometry` for a
shape), and the geodetic `Position` is computed *beside* them, never instead of them.
`attributes.position_basis` records, on every position this adapter produces: the
`CoordinateSystemType` read, the dimensionality, the transform applied — or that none was — the
named constants it used, and the CFT it resolved through including that CFT's own `from` system
and whether it was complete.

**Because every source coordinate is present verbatim, `TRANSFORMS` carries no coordinate
exemption at all.** The never-drop rule is satisfied by presence, not by a declared hole. That is
Legion's second reason restated, and it is the reason the verbatim copy is a rule and not a
courtesy.

The named constants, once: the **WGS 84 ellipsoid**, `a = 6378137.0 m`, `1/f = 298.257223563`,
per NIMA TR8350.2 Third Edition, which is the reference the standard itself lists. Cartesian to
geodetic by the **closed-form Bowring/Ferrari solution** — no iteration, so the result is a
deterministic function of the input and a golden file means something. This is the same transform
`adapters/legion.py` performs, and the two agree by construction; unlike Legion, the ellipsoid
here does not have to be inferred, because Edition B names ECEF as "**WGS 84** ECEF coordinates".

#### Per coordinate system

| `cs` | Units and order the standard states | 1.0.0 |
|---|---|---|
| `WGS_84` | latitude [°], longitude [°], ellipsoid height [m]; third axis optional but all-or-nothing across position, velocity and acceleration | **direct** for the position, with **one transform: the axis order.** The velocity splits on the third axis — see the kinematics section. Note the trap below |
| `ECEF` | x, y, z [m], geocentric, WGS 84 | **transformed**, Bowring/Ferrari on the constants above — the Legion precedent, same closed form, same code path |
| `LOCAL_CARTESIAN` | x, y, z [m]; third axis optional, all-or-nothing | **transformed only when a complete CFT is present and its `from` is `ECEF`.** Otherwise attributes-only |
| `LOCAL_SPHERICAL` | radial [m], polar [°], azimuthal [°] | **attributes-only, even with a complete CFT** — the slot labelled *azimuthal* sits in the zenith position of the mandated equations, so a producer's slot convention is unverifiable from the data. See below |
| `ECI_J2K` | x, y, z [m], geocentric, J2000 inertial | **attributes-only** |
| `PIXELS` | x, y [pixels], two axes only | **attributes-only** |

**`WGS_84` is latitude-first, and GeoJSON is not.** The standard orders the array (latitude,
longitude, height); `geo.py` is RFC 7946 and orders it `[lon, lat]`; `Position` is `.lat`/`.lon`
by name and cannot be got wrong. So the only place the trap bites is a `Polygon` or a
`PositionPoints` becoming an `Event.geometry`, and the transposition is a named transform recorded
in the basis. `geo.py`'s latitude validator catches the swap for every coordinate outside the
equatorial band, which is a backstop and not the rule.

**`LOCAL_CARTESIAN` needs the CFT, and "complete" is a checked condition, not a hope.** The
transform is the standard's own, from §2.5.13: local **L** to absolute **A** is
`A = Rᵀ L + T`, valid as a transposition **only when the rotation matrix is a rotation** —
`|det R| = 1`. §2.5.13, and guide §B.3.3.1.1 under an **AEDP-12 Requirement**: "In the event the
rotation matrix contains skew, scale or other components, the true inverse of the rotation matrix
must be used rather than the transposition." So the adapter computes the determinant and takes
the true inverse when it is not unit; a singular matrix is not invertible and is recorded as an
incomplete CFT. A 2-D local coordinate sets `L₃ = 0.0` — also an **AEDP-12 Requirement** — and the
standard then warns that the result may still have a non-zero `A₃`, so the absolute coordinate is
treated as three-dimensional. Complete means: the CFT resolves by `cftUID` or `cftLID` **within
this payload**, `from` is present, `translation` holds exactly three doubles and `rotation`
exactly nine.

**Absent CFT means attributes-only, and no invented `Position`.** The standard contemplates this
case directly: "In cases where the tracker does not know the absolute location or orientation of
the data, data consumers must be able to handle the case where local coordinates cannot be mapped
back to absolute coordinates without combining the STANAG 4676 data file with other data sources."
Combining with other data sources is precisely what this adapter does not do. And under the
DATASTREAM profile a CFT may be defined in a previously transmitted file, so an unresolved
`cftUID` there is an unresolved reference, recorded as one — the same object therefore yields a
`Position` in a STANDALONE document and none in a DATASTREAM one, which is a real property of the
format and is recorded in the basis rather than smoothed over.

**`LOCAL_SPHERICAL` is attributes-only, and the blocker is an unverifiable producer convention
rather than the CFT.** The standard mandates the spherical-to-Cartesian conversion under an
**AEDP-12 Requirement**:

    x = r cosθ sinφ     y = r sinθ sinφ     z = r cosφ

and states "r, θ and φ are the **radial, polar and azimuthal** values, respectively", while
Table 2.5.27-2 gives the array order as "radial [meters], **polar** [degrees], **azimuthal**
[degrees]". Read positionally, the third slot — the one labelled *azimuthal* — is the argument of
`z = r cos φ`. **It sits in the zenith position of the equations.** An azimuth does not determine
a zenith coordinate, so the label and the equation cannot both be describing the same quantity.

The consequence is not that the standard is unreadable; it is that **two conformant producers can
populate the array two different ways and nothing in the data says which one did.** A
label-driven producer writes its elevation-like angle into slot 2 because slot 2 is called
*polar*; an equation-driven producer writes its bearing there because that is what `θ` is used
for. Both are following the document. Feeding either into the mandated equations yields a valid
point on a sphere, so there is no arithmetic failure, no out-of-range value and no error to catch
— the two readings differ by an interchange of bearing and elevation, which puts the object at a
**plausible wrong position on the other side of the sensor**.

So applying the equations is **confidently wrong half the time**, and refusing is **withheld
loudly**: the array is parked verbatim, no `Position` and no `Kinematics` are derived, and
`position_basis` cites both statements and says which slot could not be identified. This is the
Legion `EPSG:4979` refusal reached a second time from a different direction, and it gets the same
answer for the same reason — a transposition that yields a plausible wrong position rather than
an error is the one class of ambiguity a translator must not resolve by preference.

It is a narrowing of the general rule — "transform when the CFT is present and complete" — and the
narrowing is stated here rather than buried, because a CFT-bearing `LOCAL_SPHERICAL` block looks
exactly like a case the rule covers. **And the CFT could not finish the job even if the slots were
unambiguous**: the standard's own note says "the `CoordinateFrameTransformation` class cannot be
used to directly convert to a non-Cartesian coordinate system (e.g., WGS 84)", so the route is
spherical → local Cartesian → absolute Cartesian → geodetic, and the first hop is the one that is
undetermined. What unblocks this is a custodian's clarification or a per-deployment ICD stating
its own convention, not a closer reading of the text — which is why the declines table records it
as deferred.

**`ECI_J2K` is attributes-only because the conversion is not arithmetic on the payload.** Going
from J2000 inertial to Earth-fixed needs the Earth rotation angle at the observation epoch, plus a
precession–nutation model (IAU 2006/2000A) and polar-motion and UT1−UTC values from an Earth
orientation parameter service that is republished daily. That is a second standard and a live
external dependency, in an adapter whose whole contract is to be a pure function of one payload in
an air-gapped node. The standard itself puts these conversions outside its scope: "Those
conversions between well-defined absolute coordinate systems are outside the scope of
STANAG 4676." Parked verbatim; and because `CoordinateFrameTransformation.from` is restricted to
`ECEF` and `ECI_J2K`, **a local frame whose CFT resolves to `ECI_J2K` is attributes-only too**,
for the same reason one hop further out.

**`PIXELS` is attributes-only because the ground is not in the payload.** A pixel coordinate maps
to the Earth only through a sensor model, the frame's exterior orientation and a terrain surface —
none of which NITS carries, and the format acknowledges it by restricting `CFT.from` to the two
absolute Cartesian systems, so there is no mechanism to relate a pixel frame to the ground at all.
Parked with its `DynamicSourceInformation` and `MotionImageryInformation` references intact so a
consumer holding the imagery can do it.

#### Polygons: three transforms, each named, before one can be a `Geometry`

A NITS `Polygon` that does reach `Event.geometry` — which happens only for `WGS_84` and `ECEF`
sources, and only for the classes below that map to an `Event` — needs three separate corrections,
and getting any of them wrong produces a well-formed polygon in the wrong place or with the wrong
interior:

1. **Axis order.** (lat, lon) to `[lon, lat]`, as above.
2. **Winding.** The standard, under two **AEDP-12 Requirement** callouts: an **included** ring is
   ordered **clockwise** when viewed from above, an **excluded** ring **counter-clockwise**.
   RFC 7946 §3.1.6 says the exact opposite — exterior rings counter-clockwise, interior rings
   clockwise. So every ring is reversed, and the exterior ring is moved to the front of the array
   because RFC 7946 requires it first while NITS orders rings arbitrarily.
3. **Ring delimiting and closure.** NITS packs all rings into one flat `DoubleArray` separated by
   a **null point** whose every coordinate is `NaN` (`-1` for `PixelPolygon`) — an **AEDP-12
   Requirement** — and states that "the first point is assumed to also be the last point", so the
   ring is implicitly closed. `geo.py` requires each ring to be an explicit list whose first
   position equals its last, and **refuses to repair an open one**. So the closing position is
   appended during the split, which is the one case where adding a coordinate is correct: it is
   restating a point the format says is already there.

`nRings` is `[0..1]` and "shall not be omitted" when the count is not 1, so it is a checksum on
the split: a `nRings` that disagrees with the number of `NaN`-delimited groups is a refusal
quoting both counts, never a silent preference for one.

A polygon in any of the four attributes-only coordinate systems does not become a `Geometry` at
all. It is parked whole, with its `cs`, `dims` and CFT reference.

### Kinematics: the one place a vector does become the CDM's scalars, and why here

**Gap 4** records that NITS carries a 3-vector and the CDM carries speed, course and climb.
Legion met the same shape and parked it whole, because Legion documented neither the frame nor the
units. **NITS documents both, for every one of its six systems, in Table 2.5.27-2** — so this is
the first source in this document where the conversion is exact arithmetic rather than a guess,
and gap 4 is *answered* for this format instead of re-reported.

`Dynamics.pos` is `[1]`: a `Dynamics` block always states a position, in the same coordinate
system as its velocity, because §2.5.27 requires all four attributes to share one system. So
whenever there is a velocity there is a position to build a local horizon at, and the
decomposition is closed-form:

- **`ECEF`**, and `LOCAL_CARTESIAN` resolved through a complete ECEF CFT: rotate the velocity into
  the local east/north/up frame at the geodetic position — `speed_mps = hypot(vₑ, vₙ)`,
  `course_deg = atan2(vₑ, vₙ)` reduced into `[0, 360)`, `climb_mps = vᵤ`. Exact, no iteration.
- **`WGS_84`, and it splits in two on whether the height axis is present.** The velocity is
  stated in **degrees per second** for latitude and longitude and metres per second for elevation
  — a mixed-unit vector, which is the trap — and the scale factors are the meridional and
  prime-vertical radii of curvature on the same named ellipsoid:
  `vₙ = lat̊/s · (π/180) · (M + h)` and `vₑ = lon̊/s · (π/180) · (N + h) · cos(lat)`.
  - **Third axis present** — so `pos` states an ellipsoid height and, by the all-or-nothing rule,
    `vel` states an elevation speed: **convert.** Both `φ` and `h` are given, `M` and `N` are
    closed forms in `φ` on the named constants, and the result is exact arithmetic on stated
    inputs. `climb_mps` is the elevation speed, already in m/s.
  - **Third axis omitted** — a conformant two-component position and a two-component velocity:
    **park whole**, per Legion. `h` would have to be supplied, `h = 0` is the only available
    guess, and it is a **fabricated input to the conversion** rather than a rounding of a real
    one. The CDM would then carry a speed derived from a height nobody stated, with nothing in the
    output distinguishing it from one derived from a stated height. `attributes.kinematics_basis`
    records that the height axis was absent and that this is why no scalars were derived.
- **`LOCAL_SPHERICAL`, `ECI_J2K`, `PIXELS`, and any local frame with no complete ECEF CFT**:
  parked whole. The same preconditions as the position, for the same reasons, so a `Kinematics`
  never exists without a `Position` derived from the same block.

Note that `LOCAL_CARTESIAN` does **not** split the way `WGS_84` does, and the difference is that
the standard supplies the missing component itself: for a two-dimensional local coordinate it is
an **AEDP-12 Requirement** that "the data consumer shall set `L₃` equal to 0.0". A zero the
standard mandates is a stated input; a zero height we would have to assume is not.

`course_deg` is `[0, 360)` and a course of exactly 360 reduces to 0 — the CoT and Legion rule.
`climb_mps` is "negative = descending" and the NITS up-component is positive-up in every Cartesian
system the standard defines, so the sign carries across unchanged; the basis says so, because a
sign convention nobody wrote down is how a climb becomes a descent.

`Dynamics.acc` has no CDM home in any frame — the model carries no acceleration — so it is parked
whole regardless of coordinate system, exactly as Legion parks its own. And the raw `vel` and
`acc` arrays are re-emitted verbatim beside the derived scalars, so here too `TRANSFORMS` carries
no exemption.

**Several `Dynamics` blocks per `TrackPoint` is normal, not exceptional.** The cardinality is
`[0..*]` and §2.5.27 gives the intended use: "the producer could specify a dynamics block with just
a position in WGS 84, as well as a second dynamics block with position, velocity, acceleration,
and covariance in a local coordinate system". So the adapter picks one to produce the `Position`
and `Kinematics`, in the order `WGS_84` → `ECEF` → `LOCAL_CARTESIAN` with a complete ECEF CFT, and
parks all of them. If two resolvable blocks disagree by more than a stated tolerance the
discrepancy is recorded at `attributes.position_disagreement_m` rather than averaged — the CAT021
I021/130-versus-I021/131 rule, and for the same reason: a disagreement between two statements by
one source is the source's to explain, not ours to split the difference on.

### Settlement 7 — Identity: every class has an ID, and almost none of them is a name

#### UID, LID, and the scope that makes one of them safe to key on

Every addressable class in the model carries `uid` (a `UUID`) and/or `lid` (a `UInt`), and the
standard is precise about what each guarantees — §2.1.1.2.3, restated in the guide under an
**AEDP-12 Requirement**:

- a **`uid`** "must uniquely identify the object not just within a single NITSRoot object, but
  **across all data streams from all data providers**";
- a **`lid`** "must uniquely specify an object **within a single NITSRoot object**", and is
  sharable across objects only when their `NITSRoot.lidScopeUID` values match — "if the
  `lidScopeUID` attributes differ in two NITSRoot objects, the data consumer **must assume that
  the same local ID value can be used to represent different things**".

So the two are not interchangeable, and the rule falls straight out of the text:

| Source of the key | `SourceId.system` | `SourceId.external_id` |
|---|---|---|
| `uid`, no `gidp` | `NITS_UID` | the canonical 36-character UUID |
| `uid` with a `gidp` | `NITS_IC_ID` | the composed IC Identifier `guide://<gidp>/<uuid>` — §2.6.11 defines the guide prefix as part of the identifier, so the bare UUID is a **different** identifier and keying on it would silently merge two |
| `lid` **with** a `lidScopeUID` | `NITS_LID` | the composite `<lidScopeUID>:<lid>` — never the bare integer |
| `lid` with **no** `lidScopeUID` | — | **not an identifier.** Parked at `attributes.nits_lid`. It is unique inside this one document and nowhere else, so a `SourceId` built on it would collide with every other producer's track 7 |

That last row is the I021/170 settlement applied to a number instead of a string: **no key
asserts a semantic the wire data does not carry.** A bare `lid` promoted to a `SourceId` would
tell every downstream consumer "this is a stable identifier for this object", which is exactly
what the standard says it is not. `attributes.identity_basis` records which key was used, and
`ids.derive_with_basis` reports it, so "this document gave us nothing stable" is visible in the
harness report rather than hidden behind a derived UUID.

`Entity.entity_id` is derived from the `TrackedObject`'s key where there is one, falling back to
the `TrackData`'s. The fallback is recorded because it is a weaker claim: a `TrackData` is a
*track*, and a track is a hypothesis about an object, so two tracks of one truck that the producer
later stitches yield two entities. **That is correct here and not a defect** — resolving the
stitch is the fusion this adapter declines, and the linkage that says so is carried verbatim for a
consumer that wants to act on it.

#### The APP-6 code is not a SIDC, and building one from it would draw a symbol nobody stated

`ObjectClass` carries an APP-6(D) `table`, an `entity`/`entityType`/`entitySubtype` triple, two
sector modifiers and a 6-, 8- or 10-digit `code`. APP-6 is MIL-STD-2525's NATO sibling and the
temptation is obvious: `Entity.symbol` wants a 20-digit 2525D SIDC and here is a NATO symbology
code sitting in the payload.

**It does not become `Entity.symbol`.** An APP-6 entity code is the *what-it-is* portion of a
symbol identifier. A 2525D SIDC additionally encodes the standard identity, the symbol set, the
status, the HQ/task-force/dummy indicator, the echelon or mobility, and two amplifier positions —
none of which `ObjectClass` carries. Composing one would mean supplying six fields from nothing,
and the model's `symbol` validator is explicit that a malformed or wrong SIDC is worse than none:
the operator sees a contact whose affiliation is silently wrong rather than visibly absent. So
`symbol` comes from `symbology.sidc_from_affiliation` as it does for every other adapter, with
`attributes.symbol_basis` saying so, and the whole APP-6 block is parked verbatim at
`attributes.app6` — table, code, all four strings and both modifiers — which is strictly more
information than a fabricated SIDC would carry.

`ObjectClass.table` **does** set `Entity.entity_type`, because a table is a coarse domain and the
CDM's entity type is a coarse kind. All fourteen codes are accounted for; the ones that read
`UNKNOWN` are the ones where the CDM has no member rather than the ones nobody thought about:

| Literal | Code | `Entity.entity_type` | Why |
|---|---|---|---|
| `AIR` | 01 | `PLATFORM` | |
| `AIR_MISSILE` | 02 | `PLATFORM` | |
| `SPACE` | 05 | `PLATFORM` | |
| `LAND_UNIT` | 10 | `UNIT` | |
| `LAND_CIVILIAN_UNIT/ORGANIZATION` | 11 | `UNIT` | an organisation is a unit in the CDM's sense; the civilian/military distinction survives in the parked code |
| `LAND_EQUIPMENT` | 15 | `PLATFORM` | |
| `LAND_INSTALLATION` | 20 | `FACILITY` | the same reading CAT021 gives an obstacle emitter category |
| `CONTROL_MEASURE` | 25 | `OVERLAY_OBJECT` | and it is odd on a *tracked* object; the oddity is the format's, and the parked code preserves it |
| `DISMOUNTED_INDIVIDUAL` | 27 | `UNKNOWN` | **the CDM has no member for a person.** `UNIT` would claim an organisation and `EVACUEE_GROUP` would claim a category of person. A new `EntityType` member is a MINOR bump and a candidate — recorded here rather than made in passing, which is gap 1's discipline applied to an enum |
| `SEA_SURFACE` | 30 | `PLATFORM` | |
| `SEA_SUBSURFACE` | 35 | `PLATFORM` | |
| `MINE_WARFARE` | 36 | `UNKNOWN` | a mine is not a platform, a unit or a facility |
| `ACTIVITIES` | 40 | `UNKNOWN` | an activity is not a thing that exists. The CDM separates what exists from what happens, and this table crosses that line |
| `ATMOSPHERIC` | 45 | `UNKNOWN` | weather |

`objectClass` is `[0..*]`. Where several are present and all map to the same type, that type is
used; where they disagree the type is `UNKNOWN` and the basis lists all of them, because choosing
between a producer's own competing classifications is a judgement.

#### Affiliation — 6 into 4, and the amplification that states the identity outright

`ID1241.identity` carries STANAG 1241 Edition 5 standard identities. **This is gap 2's own source**
— the gap was written about 4676 — and Edition B is the occasion to state it exactly:

| `Identity` | `Entity.affiliation` | |
|---|---|---|
| `FRIEND` | `FRIENDLY` | |
| `HOSTILE` | `HOSTILE` | |
| `NEUTRAL` | `NEUTRAL` | |
| `UNKNOWN` | `UNKNOWN` | |
| `ASSUMED_FRIEND` | `UNKNOWN` | **gap 2** — a judgement the CDM does not model. Parked verbatim; understating is the safe direction |
| `SUSPECT` | `UNKNOWN` | **gap 2** — likewise, and this is the one that costs most: "potentially poses a threat" collapsing to "we do not know" |

**Gap 2 says "7 → 4" and Edition B's table has six literals, not seven.** `PENDING` is not in it.
The collapse here is 6 → 4, and two of the three members gap 2 names as lost are the two lost. The
gap's paragraph below carries the correction.

**`IdentityAmplification` is read, and three of its five literals state the affiliation
outright.** Edition B's Table 2.5.34-3 does not describe a role and leave the identity open — it
states the identity in the first word of the definition:

| `IdentityAmplification` | Edition B's definition | `Entity.affiliation` |
|---|---|---|
| `FAKER` | "**Friendly** track, object or entity acting as exercise hostile" | `FRIENDLY` |
| `JOKER` | "**Friendly** track, object or entity acting as exercise suspect" | `FRIENDLY` |
| `KILO` | "**Friendly** high-value object" | `FRIENDLY` |
| `TRAVELER` | "A **suspect** surface track following a recognized surface traffic route" | does not set it — `SUSPECT` has no CDM member, so `identity` governs and **gap 2** applies |
| `ZOMBIE` | "A **suspect** track, object or entity of special interest" | likewise |

So a `FAKER` arriving with `identity = HOSTILE` — which is what an exercise produces — yields
`FRIENDLY`, and the amplification wins because it is the more specific statement and because the
standard has told us in as many words what the object is. **The exercise role is a second fact,
not an ambiguity**, and it is parked verbatim at `attributes.exercise_role` (`FAKER` or `JOKER`)
alongside the overridden `identity` at `attributes.nits_identity`, with
`attributes.affiliation_basis` naming both. A consumer that reads the `FRIENDLY` and ignores
`attributes.exercise_role` has ignored parked data, which is a different failure from being
misinformed by the adapter.

This overturns the Phase 1 reading, which forced `UNKNOWN` on the argument that both answers were
over-claims. They are not symmetric: `HOSTILE` would contradict the standard's own definition, and
`FRIENDLY` restates it. Withholding an identity the source stated plainly is not the conservative
choice — it is a third wrong answer, and the one that loses information. Note the contrast with
the Mode 4 / Mode 5 decline a few paragraphs down, which stands: there the format gives an
*authentication result* and the identity is an inference from it; here the format gives the
identity as a definition. Reading a definition is translation; adjudicating an attestation is not.

`KILO` is included on the same evidence, though it names no exercise: its definition also begins
"Friendly", and mapping `FAKER` to `FRIENDLY` while leaving a plainly friendly high-value object
`UNKNOWN` would be incoherent. It sets no `exercise_role`, because it is not one.

**`TrackEnvironment` does not become `entity_type`.** `LAND`, `SURFACE`, `SUB-SURFACE`, `AIR`,
`SPACE`, `UNKNOWN` name a **domain**, not a kind of thing, and a truck and a dismounted patrol are
both `LAND`. Parked.

**Mode 4 and Mode 5 IFF are not read as an affiliation.** This is the second format to force the
decision and it gets CAT021's answer: an authenticated IFF reply is what "friend" means in IFF
doctrine, and turning one into `FRIENDLY` is an identification decision belonging to an IFF
authority, not a translator. Over-claiming `FRIENDLY` is also the dangerous direction. The codes
are parked in full and `affiliation_basis` records the decline.

**One IFF mode does become an identifier, and it is the one that is the same number in three
formats.** `IFFCode.mode = MODE_S` carries the aircraft's fixed 24-bit address — the same address
`adapters/adsb.py` and `adapters/asterix_cat021.py` key on as `ICAO24`. So a NITS track of an
aircraft and a 1090ES contact derive the **same `entity_id`** without either adapter knowing the
other exists, which is the largest interoperability win available in this row set. The condition
is exact and narrow: **`IFFCode.value` is a `String` with no stated syntax for any mode**, so it
becomes an `ICAO24` `SourceId` only when it parses unambiguously as six hexadecimal digits.
Anything else — decimal, octal, spaced, prefixed — is parked raw with the ambiguity recorded,
because a Mode S value in an unstated radix cannot be keyed on. `MODE3` lands at
`attributes.mode_a_code` on the same terms, converging with the key CAT021 and ADS-B already
share; `MODE_C` is a pressure altitude rather than an identity and never reaches `Position.alt_m`,
for the same radix reason.

**`IDSourceInformation` reaches neither affiliation nor confidence, and its own definition says
why.** §2.5.32: the class "enables an **ID fusion node** to generate an ID category recommendation
on the basis of all relevant ID information", extending the IDCP of STANAG 4162 / AIDPP-01. Being
an ID fusion node is precisely what a translator is not. Every attribute is parked verbatim —
including `idQualityNumber`, which is typed `String` and is therefore not a number the adapter may
compare or rank.

#### The name that is not there

Five formats in this document park an operator-facing name and **gap 1** counts the cost: four
private keys for one concept, and two adapters that converged on `attributes.callsign` for two
different things. NITS is the sixth format and it adds no seventh key, because **it has no
callsign field at all.** There is no name for the tracked contact anywhere in the model.

What it has instead is a set of near-misses, and the discipline is to park each under a key named
for what it is:

| Field | Parked at | Why not a name |
|---|---|---|
| `TrackedObject.description` | `attributes.tracked_object_description` | the closest thing, and explicitly "a string that the data producer can use to **describe** the tracked object in greater detail than is otherwise allowed by the other attributes" — a description, not a label. Promoting it to `attributes.callsign` would assert an operator-assigned name on free text |
| `SensorInformation.name`, `TrackerInformation.name` | `attributes.nits_sensor`, `attributes.nits_tracker` | they name the *sensor* and the *algorithm*, not the contact |
| `ProductIdentification.name`, `.shortName` | `attributes.nits_product` | they name the data product |
| `CollectionInformation.targetID` | `attributes.nits_collection` | "an identifier for the primary **target area** of the collection" — an area, not an object |
| `IDData.stationID` + `nationality` | `attributes.nits_station` | the producing station, per STANAG 4545's OSTAID field. **Gap 14**, not gap 1 |

So NITS's contribution to gap 1 is not a fifth key. It is the demonstration that a format can
carry a full ISR track model, forty-eight classes deep, and never state what a human calls the
thing — which is a fact about what "a name" is worth arguing about, recorded in the gap below.

### Settlement 8 — A translator owes no fusion. Stated once, plainly

**A translator owes no fusion, no track association, and no linkage resolution.** Linkage data is
carried verbatim; acting on it is a consumer decision.

This is the strongest temptation in this document because NITS does not merely permit fusion — it
models it, names it, and its Implementation Guide is largely about it. `ProcessedTrack` has a
`FUSED` type. `TrackLinkage` has `SPLIT`, `MERGE` and `STITCH`. `IDSourceInformation` exists to
feed an ID fusion node. The guide's Annex A opens with figures of decentralized and centralized
fusion architectures and states that ISR track data is "processed, exploited and analyzed to
derive products and reports **through fusion**". None of that changes what an adapter is. **A
tracker fusing tracks is a producer stating a conclusion; an adapter carrying that statement is
translation; an adapter acting on it is fusion.** The line is the same one AIS type 24, ADS-B CPR
pairing, Legion pagination and CAT021 cross-block correlation are on, and this is the fifth time
it is drawn.

Concretely, what "carried verbatim" means for each:

- **`TrackLinkage`** becomes an `Event` whose payload holds the type, the relative time, the
  confidence and the `preUID`/`preLID`/`postUID`/`postLID` lists **as identifiers, exactly as
  written**. The adapter does not merge the tracks, does not rewrite either track's `track_id`,
  and does not emit a combined `Track`.
- **`ProcessedTrack`** becomes an `Event` on the same terms. A `FUSED` processed track says the
  producer re-ran its tracker over several inputs; it does not license us to re-run anything.
- **`Event.related_entities` stays empty for both, and that is deliberate.** The field holds
  `entity_id` values. A linkage names **track** identifiers, and a `Track.track_id` is not an
  `entity_id`. Deriving entity ids from them would assert an entity-level relationship the wire
  never carried — the Legion rule that deriving an id is not a join, but that the id you derive
  has to be the id of the thing that was named. The derived `track_id` values go in the payload,
  where they are what they are. **Gap 19** is the shape this needs and does not have.
- **`MotionEvent.trackUID`/`trackLID`** are handled identically, for the identical reason.

#### The consolidation rule is a cross-payload state merge, and it is refused

This is the sharpest instance, because here the standard **normatively requires** the thing the
adapter will not do. §2.1.1.2.3, restated in the guide under an **AEDP-12 Requirement**:

> the value of the object **shall** be interpreted not as simply the set of values specified in one
> instance of the class of that object in the data stream, but as **the consolidation of all
> instances of that class across all in-scope data streams** where the ID is set to the same value.

That is a consumer obligation to hold every object it has ever seen, keyed by UID or LID, and to
merge each new instance into the accumulated state — and to order the merges by
`NITSRoot.msgCreatedTime`, which §2.6.9 names as the tie-breaker. It is a stateful reducer, and it
is the mechanism behind `Confidence.valid = FALSE`: a producer retracts a previously transmitted
segment by restating its ID with an invalidating confidence and nothing else.

**The adapter does not perform it.** It translates each `NITSRoot` on its own, and it carries the
material a consumer needs to perform it: every `uid` and scoped `lid` verbatim, every `Confidence`
including `valid`, and `NITSRoot.msgCreatedTime` parked as the ordering key. `attributes.
consolidation_basis` records, on every object, that the standard defines a consolidation across
data streams and that this translation is of one document only.

The alternative is worth naming so the decision is not mistaken for laziness. An adapter that
consolidated would need an unbounded store keyed by identifiers whose scope it cannot always
establish (a bare `lid` with no `lidScopeUID`), would produce different output for the same input
depending on what it had seen before — which destroys golden-output testing and, more importantly,
auditability — and would be silently applying retractions inside a component nothing audits. The
standard is describing what a *tracking system* owes its user. This is a translator.

**A retraction is data, and it survives as data.** A `TrackSegment` restated with an invalidating
confidence and no points becomes an `Event` carrying the retracted identifier, the `Confidence`
verbatim including `valid = false`, and a basis recording that the adapter did not apply it. A
consumer that keeps state can; one that does not at least knows a retraction happened, which is
strictly better than the retraction being dropped for having no track points in it.

### How to read the row sets

One table per class, in the order the standard lists them, and **one row per attribute**. The
left column names the attribute as `Class.attribute`; the **Card** column gives the standard's
multiplicity, with `[1]` where the standard states none, per its own CONVENTIONS. Every class in
Annex D's alphabetical entity list has a table, including the three that have no attributes at
all. Nothing is omitted silently: a class the adapter declines appears in the declines table with
a reason.

Two model-wide facts that would otherwise be repeated on a hundred rows:

- **Every class is extensible and the schema says so.** Edition B §2.1.1.5 and Annex B.4: the XSD
  specifies `defaultOpenContent` in interleave mode for the schema as a whole and `xs:anyAttribute`
  on every complex type, so *any* element may carry sub-elements this row set does not name. All
  of them land at `attributes.source_extras` with their structure and their namespace intact. The
  standard requires extensions to live in a vendor or national namespace, so the namespace is the
  provenance and is kept.
- **Every enumeration accepts any string.** Annex B.4 defines each enumerated type as a union of
  the enumeration with `xs:string`, and says outright: "Because any value can be a string, the
  enumerations are not validated. The lack of validation ensures data consumers will not reject
  new registered values." So an unrecognised literal is **conformant**, and the adapter parks it
  at `attributes.unresolved_raw` rather than refusing the document. Refusing would break exactly
  the forward compatibility the union exists to provide.

### Row set — `NITSRoot` and the document header

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `NITSRoot.profile` | `[1..*]` | `Entity.attributes` | `nits 1.0.0` | `ComplianceProfile`. See the profiles settlement — read, never followed; unregistered literals parked |
| `NITSRoot.streamUID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | the DATASTREAM's own `UUID`. Parked; it identifies a stream this adapter does not assemble |
| `NITSRoot.fileUID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | this object's `UUID`. Parked, and it is the document identifier a consumer needs to deduplicate a retransmission |
| `NITSRoot.fileLID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | `UInt`. Parked; scoped by `lidScopeUID` like every other local ID |
| `NITSRoot.lidScopeUID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | **the attribute that decides whether any `lid` in this document may become a `SourceId`.** "Required if local IDs are found in the object" — a document containing local IDs and no scope is non-conforming, and is translated with every `lid` parked rather than keyed |
| `NITSRoot.numFiles` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | how many related files the producer has sent so far, including this one. Parked; the adapter counts nothing and waits for nothing |
| `NITSRoot.msgCreatedTime` | `[1]` | `Entity.attributes` | `nits 1.0.0` | when the producer **wrote the file**. Parked, and deliberately neither `observed_at` nor `received_at`: it is a source time about the document, not about an observation, and it is the ordering key the consolidation rule uses |
| `NITSRoot.nitsVersion` | `[1]` | `Entity.attributes` | `nits 1.0.0` | `"B.2"` for the target edition. **The version gate**: anything reading `A.*` is refused with the value quoted, per the edition settlement |
| `NITSRoot.product` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | one `ProductIdentification`; its own table below |
| `NITSRoot.collection` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | `CollectionInformation`, one per collection; its own table. **Parked, including `essence`** — no payload field sets `source.synthetic` |
| `NITSRoot.sensor` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · parked` | `SensorInformation`, one per sensor; its own table. **Gap 14** |
| `NITSRoot.tracker` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · parked` | `TrackerInformation`, one per tracker; its own table. **Gap 14** |
| `NITSRoot.message` | `[0..*]` | — | `nits 1.0.0` | `TrackMessage`. The container everything below hangs from; not itself parked, because its contents become objects |
| *(the XML syntax, not the model)* | `[1]` | `Entity.attributes` | `nits 1.0.0 · parked` | `originatorConfidentialityLabel` — **mandatory on the root element** per Annex B.2. Parked verbatim at `attributes.confidentiality_label.originator`. **Gap 12** |
| *(the XML syntax)* | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | `alternativeConfidentialityLabel`, verbatim |
| *(the XML syntax)* | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | `metadataConfidentialityLabel`, verbatim |

`ComplianceProfile`: `STANDALONE`, `DATASTREAM`. Both handled; see the settlement.

### Row set — `ProductIdentification`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `ProductIdentification.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | parked; a product is not a CDM object |
| `ProductIdentification.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | parked |
| `ProductIdentification.id` | `[1]` | `Entity.attributes` | `nits 1.0.0` | "a free-form string allowing the data provider to specify the designation (ID) of this STANAG 4676 based product **per that system's ID syntax**" — a per-system syntax, so not a key |
| `ProductIdentification.name` | `[1]` | `Entity.attributes` | `nits 1.0.0` | the product's name, e.g. "System X Motion Imagery Track Product". **Not `attributes.callsign`** — it names the product, not the contact |
| `ProductIdentification.shortName` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | e.g. "XMTP" |
| `ProductIdentification.effectivity` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | the named effectivity the product complies with |

### Row set — `CollectionInformation`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `CollectionInformation.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | referenced by `TrackSource.collectionUID` |
| `CollectionInformation.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | likewise |
| `CollectionInformation.intent` | `[1]` | `Entity.attributes` | `nits 1.0.0` | `CollectionIntentType`. Parked and **does not set `synthetic`**: `EXERCISE` data is frequently real sensor data, and `TEST`, `ENGINEERING` and `INITIALIZATION` say when a collection happened in its programme, not whether it was real |
| `CollectionInformation.essence` | `[1]` | `Entity.attributes` | `nits 1.0.0` | `CollectionEssenceType`. **Parked verbatim and does not set `source.synthetic` either** — see the note below. Where it contradicts the deployment declaration the document is refused, never silently flipped |
| `CollectionInformation.targetID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | "an identifier for the primary **target area**" — an area, not an object, and not a name |

`CollectionIntentType`: `OPERATIONAL`, `EXERCISE`, `TEST`, `ENGINEERING`, `GROUND_TRUTH`,
`INITIALIZATION`, `EXPERIMENTAL`. All parked.
`CollectionEssenceType`: `REAL`, `SIMULATED`, `SYNTHETIC`, `SURROGATE`.

**`essence` does not set `source.synthetic`, and the rule it obeys is a rule and not a default
with exceptions.** The temptation is real and it is worth stating before dismissing it:
`SourceRef.synthetic` is "true for anything not from a real source", and `CollectionEssenceType`
is a statement about whether these data "are derived from real sensor data" or from
digitally-simulated data, a surrogate sensor, or a mixture. It looks like the same claim written
twice.

It is refused anyway, because **`source.synthetic` is a deployment declaration and a payload field
may not rewrite one.** That is the rule the CAT021 row set states for I021/040 `SIM` and the Legion
row set states for its `EXERCISE_*` identities, and a rule that admits an exception whenever the
payload field looks close enough is not a rule — it is a default. The asymmetry that makes it
matter is one-sided: a feed configured as real that receives a document claiming `SIMULATED` has
either been misconfigured or been fed the wrong data, and both are conditions an operator must be
told about rather than have quietly reflected in a boolean.

So `essence` is parked verbatim at `attributes.nits_collection[].essence`, for every collection,
and `source.synthetic` is whatever the deployment declared. Three consequences:

- **A contradiction is a logged refusal, in either direction.** A parked `essence` of `SIMULATED`,
  `SYNTHETIC` or `SURROGATE` against a deployment declaring `synthetic = false` is refused with
  both values quoted; so is a `REAL` essence against a deployment declaring `synthetic = true`.
  Symmetric on purpose — a silent flip is forbidden in the direction that understates realness as
  well as the one that overstates it, because either flip hides the misconfiguration. The case
  most likely to hit the second branch is a replay of genuinely real data through a pipeline
  declared synthetic, and it should surface as a configuration question rather than as a boolean
  nobody looks at.
- **`collection` is `[0..*]`, so collections may disagree with each other.** All essences are
  parked in order and the conflict check runs against the deployment declaration for each; the
  adapter never reduces them to one value.
- **A `NITSRoot` with no `CollectionInformation` at all is conformant.** There is then nothing to
  check against, `synthetic` is the deployment's value, and `attributes.synthetic_basis` records
  that the document stated no essence. The model gives `synthetic` no default precisely so this
  cannot be answered by accident.

### Row set — `SensorInformation` and its three specializations

Everything here is **gap 14**: the format names the producing sensor as a first-class object with
its own identity, and `SourceRef` names the adapter and the system and has nowhere to put it.

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `SensorInformation.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | the target of `TrackSource.sensorUID` and `Detection.sensorUID` |
| `SensorInformation.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | likewise |
| `SensorInformation.sensorID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | an `IDData`; its own table |
| `SensorInformation.name` | `[1]` | `Entity.attributes` | `nits 1.0.0` | names the sensor, not the contact |
| `SensorInformation.description` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | |
| `SensorInformation.modality` | `[1]` | `Entity.attributes` | `nits 1.0.0` | `ModalityType`. **Deliberately does not refine `Position.position_source`** — see the note below |
| `SensorInformation.url` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | a URL for the sensor information data. Parked and **never fetched**: an adapter that dereferences a URL out of a payload is a network client with a payload-controlled target |
| `SensorInformation.collectionMode` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | free string; the standard expects to drop it in a future release |
| `SensorInformation.absTimeUncertainty` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | seconds of uncertainty in the sensor's clock. **Gap 13** — the CDM has no per-measurement time, let alone an uncertainty on one |
| `SensorInformation.relTimeUncertainty` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | seconds of uncertainty between any two of its times. **Gap 13** |
| `SensorInformation.comment` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | free text, and §2.1.1.4 forbids parsing it for embedded data. Parked as the complete string, never split |
| `SensorInformation.esmSensor` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | an `ESMSensor`, which has no attributes |
| `SensorInformation.imagingSensor` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | an `ImagingSensor`; its own table |
| `SensorInformation.radarSensor` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | a `RadarSensor4607`; its own table |

`ModalityType`, all eighteen literals parked verbatim: `DOPPLER_SIGNATURE`, `HRR_SIGNATURE`,
`IMAGE_SIGNATURE`, `HUMINT`, `MASINT`, `ELINT`, `COMINT_EXTERNALS`, `COMINT_INTERNALS`, `OSINT`,
`BIOMETRICS`, `AIS`, `BFT`, `SEISMIC`, `ACOUSTIC`, `ADS-B`, `MIXED`, `OTHER`, `XXXX`.

**Why `modality` does not set `position_source`, even when it says `ADS-B` or `AIS`.** The
temptation is real: an ADS-B or AIS or BFT modality means the position started life as a GNSS fix,
and `PositionSource.GNSS` is the field a commander uses to tell a fix from a guess under jamming.
It is declined for two reasons. First, Legion's: a field that names the *system* that produced a
fix does not state *how the fix was obtained*, and a tracker's output for an ADS-B input is still
the tracker's estimate. Second, and specific to this format: reaching `modality` from a
`TrackPoint` means resolving `TrackSource.sensorUID` to a `SensorInformation`, **and under the
DATASTREAM profile that object may be in a different file** — so the same track point would get
`GNSS` in a STANDALONE document and `ESTIMATED` in a DATASTREAM one. A canonical field whose value
depends on the sender's framing choice is worse than a conservative one. `position_source` is
`ESTIMATED` on every NITS position, and `attributes.position_source_basis` names the modality
where it resolved.

#### `ESMSensor`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| *(no attributes)* | — | `Entity.attributes` | `nits 1.0.0` | §2.5.5: "a placeholder for future additions and does not currently include any attributes". Its **presence** is the datum, so it is parked as a present-and-empty marker; open content may still carry vendor extensions and those land in `source_extras` |

#### `RadarSensor4607`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `RadarSensor4607.platformID` | `[1]` | `Entity.attributes` | `nits 1.0.0 · parked` | STANAG 4607 field P8 — a tail number for an aircraft. **Not a `SourceId` for the tracked object**: it identifies the *collecting platform*. Gap 14 |
| `RadarSensor4607.missionID` | `[1]` | `Entity.attributes` | `nits 1.0.0` | 4607 field P9 |
| `RadarSensor4607.jobID` | `[1]` | `Entity.attributes` | `nits 1.0.0` | 4607 field P10; 0 means no specific request, which is a stated value and not an absence |

#### `ImagingSensor`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `ImagingSensor.motionImageryCoreID` | `[1]` | `Entity.attributes` | `nits 1.0.0` | a `MiisCoreIdType` per **MISB ST 1204.3**. Parked verbatim and **not decoded**: the MIIS Core Identifier is a separate standard, the same category as CAT021's BDS registers. Note the standard's own erratum — the XSD namespace says `nga.gov` where `nga.mil` was meant, and keeps it for backwards compatibility |
| `ImagingSensor.frameHeight` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | focal-plane height in pixels |
| `ImagingSensor.frameWidth` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | focal-plane width in pixels |
| `ImagingSensor.fpaIndex` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | **1-based**, unlike every pixel index in the model, which is 0-based. Parked as sent with the base recorded |
| `ImagingSensor.filter` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | wavelength/transmission pairs in one flat array, microns and fraction. Parked as pairs |
| `ImagingSensor.phenomenology` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | `SymbolicSpectralRange`: `LWIR`, `MWIR`, `SWIR`, `NIR`, `VIS`, `UV`, `MSI`, `HSI`, `DERIVED`, `UNKNOWN` |
| `ImagingSensor.band` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | the imaging system's own band name, e.g. "LWIR-8" |

#### `TrackerInformation`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `TrackerInformation.type` | `[1]` | `Entity.attributes` | `nits 1.0.0` | `TrackerType`: `MANUAL_TRACKER`, `AUTOMATIC_TRACKER`, `SEMIAUTOMATIC_TRACKER`. An XML attribute rather than an element, per §2.1.1.7 |
| `TrackerInformation.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | the target of `TrackSource.trackerUID` |
| `TrackerInformation.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | likewise |
| `TrackerInformation.trackerID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | an `IDData` — the station ID and nationality that "provides unique identification of any given STANAG 4676 capable system". **Gap 14**, and the closest thing in the model to naming who produced the data |
| `TrackerInformation.name` | `[1]` | `Entity.attributes` | `nits 1.0.0` | names the algorithm |
| `TrackerInformation.description` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | |
| `TrackerInformation.version` | `[1]` | `Entity.attributes` | `nits 1.0.0` | the tracker algorithm's version — "useful record in case the tracker algorithm gets updated, or a systematic error is discovered". Parked, and it is the field that makes a stored track re-auditable |
| `TrackerInformation.supplementaryData` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | `SupplementaryData`; its own table |

#### `SupplementaryData`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `SupplementaryData.type` | `[1]` | `Entity.attributes` | `nits 1.0.0` | `SupplementaryDataType`: `GIS_ROAD_NETWORK`, `DIGITAL_ELEVATION_MODEL`, `SHIPPING_LANE`, `AIR_CORRIDOR`, `DIGITAL_TERRAIN_MODEL`, `DIGITAL_SURFACE_MODEL`, `EDGE_DETECTION_SCENE`, `ILLUMINATION/SHADOW_MAP`, `FOUNDATION_FEATURE_DATA`, `AUTOMATIC_SCENE_SEGMENTATION` |
| `SupplementaryData.name` | `[1]` | `Entity.attributes` | `nits 1.0.0` | which DEM, which road network |
| `SupplementaryData.version` | `[1]` | `Entity.attributes` | `nits 1.0.0` | recorded "in case a future update to the supplementary data set requires reassessing the tracks" |
| `SupplementaryData.description` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | |

### Row set — `TrackMessage` and the time base

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `TrackMessage.numDetections` | `[0..1]` | `Event.payload` | `nits 1.0.0` | how many detections the producer says this message holds. Parked, and **checked**: a count that disagrees with the number parsed is recorded at `payload.count_disagreement`, never used to stop parsing. The standard says omitting it "simply means the number is not reported", so absence is not zero |
| `TrackMessage.numTracks` | `[0..1]` | `Event.payload` | `nits 1.0.0` | on the same terms |
| `TrackMessage.baseTime` | `[1]` | `Track.samples[].observed_at` | `nits 1.0.0` | the absolute UTC base every `relTime` in this message scales from. Absent, naive or malformed is a **refusal quoting the value** — see the time settlement |
| `TrackMessage.relTimeIncrement` | `[1]` | `Track.samples[].observed_at` | `nits 1.0.0` | seconds per increment, a `double`. Zero, negative or non-finite is a refusal. Parked verbatim, because egress re-emits from the park rather than recomputing |
| `TrackMessage.dynSrcInfo` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | `DynamicSourceInformation`, one per frame or dwell; its own table |
| `TrackMessage.detection` | `[0..*]` | `Event.payload` | `nits 1.0.0` | `Detection`, each becoming its own `Event`; its own table |
| `TrackMessage.track` | `[0..*]` | `Track.samples[]` | `nits 1.0.0` | `TrackData`, each becoming an `Entity` and one `Track` per segment |
| `TrackMessage.processedTrack` | `[0..*]` | `Event.payload` | `nits 1.0.0` | `ProcessedTrack`, carried verbatim, never acted on |
| `TrackMessage.trackLinkage` | `[0..*]` | `Event.payload` | `nits 1.0.0` | `TrackLinkage`, likewise |
| `TrackMessage.motionEvent` | `[0..*]` | `Event.payload` | `nits 1.0.0` | `MotionEvent`, each becoming its own `Event` |

**`TrackMessage` has no `uid` and no `lid`,** which is worth stating because it is the only
container in the model that cannot be referred to. A `relTime` is therefore meaningful **only
inside the message that carries its base**, and a `NITSRoot` holding several `TrackMessage`
objects holds several independent time bases. The adapter resolves each object against its own
message's base and records which message an object came from at
`attributes.nits_message_index` — without it, two samples from two messages are indistinguishable
from two samples sharing a base.

### Row set — `DynamicSourceInformation` and the coordinate frame

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `DynamicSourceInformation.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | the target of `dynSrcUID` on a `TrackPoint` or a `Detection` |
| `DynamicSourceInformation.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | likewise |
| `DynamicSourceInformation.relTime` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | when this frame or dwell was taken. Parked with its absolute resolution beside it |
| `DynamicSourceInformation.sensorUID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | a reference to `SensorInformation`; "may designate a UID **OR** an LID for the sensor, but not both", and a document setting both is recorded at `attributes.reference_conflict` rather than resolved by preference |
| `DynamicSourceInformation.sensorLID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | the local form of the same reference |
| `DynamicSourceInformation.sensorLocation` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | a `PositionPoints` holding **one** coordinate: where the sensor was. **Gap 14** in its most concrete form — the format states the observer's position and the CDM cannot relate an observation to an observer. Parked, and deliberately **never** used as the target's position |
| `DynamicSourceInformation.groupID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | a program-defined ID for a group of source blocks. Program-defined, so not a key |
| `DynamicSourceInformation.numDetections` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | how many detections were in the field of view |
| `DynamicSourceInformation.numReportedDetections` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | how many of them were reported. The pair is a **completeness measure** and is parked as one, the same job Legion's `total_count` versus `carried_samples` does |
| `DynamicSourceInformation.dynCFT` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | `DynamicCFT`; the transforms every local coordinate in this frame resolves through |
| `DynamicSourceInformation.sourceMI` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | `MotionImageryInformation`; its own table |
| `DynamicSourceInformation.sourceRadar` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | `RadarInformation`; its own table |
| `DynamicSourceInformation.sourceESM` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | `ESMInformation`, which has no attributes |

#### `DynamicCFT`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `DynamicCFT.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | "each instance of a `DynamicCFT` must have either a UID or an LID" — one with neither cannot be referenced and is recorded as such |
| `DynamicCFT.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | likewise |
| `DynamicCFT.cft` | `[1]` | `Position.lat` | `nits 1.0.0` | the `CoordinateFrameTransformation` a local `Dynamics` or `Shape` resolves through. Named as reaching `Position` because when it resolves, it is what makes a local coordinate a geodetic one |

#### `CoordinateFrameTransformation`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `CoordinateFrameTransformation.from` | `[1]` | `Position.lat` | `nits 1.0.0` | `CoordinateSystemType`, "restricted to `ECEF` and `ECI_J2K`". **`ECEF` transforms; `ECI_J2K` does not** — the local frame it anchors is attributes-only, per the coordinate settlement. A `from` naming a local, spherical or geodetic system is non-conforming and the CFT is treated as incomplete |
| `CoordinateFrameTransformation.translation` | `[1]` | `Position.lat` | `nits 1.0.0` | exactly three doubles, `T1 T2 T3`. Any other count makes the CFT incomplete |
| `CoordinateFrameTransformation.rotation` | `[1]` | `Position.lat` | `nits 1.0.0` | exactly nine doubles, `R1..R9` row-major. **The determinant is computed**: `A = Rᵀ L + T` is valid only when `\|det R\| = 1`, and the standard requires the true inverse otherwise. A singular matrix makes the CFT incomplete |

#### `MotionImageryInformation`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `MotionImageryInformation.frameBoundingBox` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | a `Polygon` bounding the field of view. **Not `Event.geometry`**: it describes the sensor's coverage, and emitting it as an event's geometry would paint the footprint as the thing observed |
| `MotionImageryInformation.frameNumber` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | arbitrary, and the standard says so: "the consumer is strongly encouraged to use the time stamps instead of frame number". Parked, never used to order anything |
| `MotionImageryInformation.niirs` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | the producer's NIIRS estimate at image centre, per STANAG 7194. An image-quality rating, and **not** `Entity.confidence` |
| `MotionImageryInformation.vniirs` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | the video equivalent, per MISP-2019.1. Likewise |
| `MotionImageryInformation.sea` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | solar elevation angle in degrees |
| `MotionImageryInformation.tea` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | target elevation angle in degrees |
| `MotionImageryInformation.gsd` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | ground sampling distance in metres, one to three values, where **one value is a geometric mean over all known dimensions** and two or three are per-axis. Parked with the count, because the meaning changes with it |
| `MotionImageryInformation.grd` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | ground resolved distance, same encoding, same reading. **Not `Position.accuracy_m`**: a resolution is not a 1-sigma position error |
| `MotionImageryInformation.useableFOV` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | a `Polygon`, "either pixel or real-world coordinates are permitted" and the `Shape` says which |
| `MotionImageryInformation.processedFOV` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | the portion algorithms actually ran on. Parked, and it is the field that says where a *non*-detection means something |

#### `RadarInformation`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `RadarInformation.revisitIndex` | `[1]` | `Entity.attributes` | `nits 1.0.0` | STANAG 4607 field D2 |
| `RadarInformation.dwellIndex` | `[1]` | `Entity.attributes` | `nits 1.0.0` | 4607 field D3. Both are pointers into the source GMTI data; parked, and **not** resolved — reading the 4607 file is a different adapter |

#### `ESMInformation`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| *(no attributes)* | — | `Entity.attributes` | `nits 1.0.0` | §2.5.16: "a placeholder for future capabilities, and currently does not contain any attributes". Present-and-empty is parked as such |

### Row set — the `Detection` / `Evidence` tree

A `Detection` is "a single instance of sensed information, which if hypothesized to be part of a
tracked object, serves as evidence of the tracked object", and the standard is explicit that
detections "can be reported independent of whether or not they are eventually associated with a
track point". So each becomes an **`Event`** of type `DETECTION` in its own right — the same
reading `adapters/legion.py` gives a Legion Event, reached from a class that says it out loud.

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Detection.uid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0` | system `NITS_UID`. "If the data producer intends to associate detections with track points, they must supply each detection with either a UID or an LID" |
| `Detection.lid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0` | system `NITS_LID`, and **only when `lidScopeUID` is present** — the composite, never the bare integer |
| `Detection.relTime` | `[0..1]` | `Event.observed_at` | `nits 1.0.0` | resolved against the message base. Omitted means zero, which is the standard's rule and not an assumption |
| `Detection.centroid` | `[0..*]` | `Event.geometry` | `nits 1.0.0` | a `PositionPoints` holding one coordinate. **Unbounded so the same centroid can be stated in several coordinate systems**, not so several detections can share a class — the standard says so. A `WGS_84` or transformable `ECEF` centroid becomes a `Point`; the rest are attributes-only |
| `Detection.outline` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · parked` | a `Shape`, unbounded for the same reason. **Gap 8** — the CDM has no extent, so an outline is parked whole even when its coordinate system would allow a polygon |
| `Detection.sensorUID` | `[0..1]` | `Event.payload` | `nits 1.0.0 · parked` | which sensor saw it. **Gap 14** |
| `Detection.sensorLID` | `[0..1]` | `Event.payload` | `nits 1.0.0` | likewise |
| `Detection.dynSrcUID` | `[0..1]` | `Event.payload` | `nits 1.0.0` | which frame or dwell it came from |
| `Detection.dynSrcLID` | `[0..1]` | `Event.payload` | `nits 1.0.0` | likewise |
| `Detection.confidence` | `[0..1]` | `Event.payload` | `nits 1.0.0 · parked` | a `Confidence`. **Gap 18** — parked whole, never reduced to a float |
| `Detection.source` | `[0..1]` | `Event.payload` | `nits 1.0.0` | a `TrackSource` scoped to this one detection |
| `Detection.esm` | `[0..1]` | `Event.payload` | `nits 1.0.0` | an `ESM`, which has no attributes |
| `Detection.im` | `[0..1]` | `Event.payload` | `nits 1.0.0` | an `Image`; its own table |
| `Detection.radar` | `[0..1]` | `Event.payload` | `nits 1.0.0` | a `Radar4607`; its own table |
| `Detection.sm` | `[0..*]` | `Event.payload` | `nits 1.0.0` | `SensorMeasurement`; its own table |
| *(derived)* | — | `Event.event_type` | `nits 1.0.0` | `DETECTION`. The class is one |
| *(derived)* | — | `Event.severity` | `nits 1.0.0` | `INFO`, with `payload.severity_basis` recording that NITS grades nothing. Legion's rule: the line sits at the source's own explicit alarm, and there is none |
| *(none)* | — | `Event.related_entities` | `nits 1.0.0` | **empty.** A detection is evidence *for* a track point, and the association runs the other way — from `Evidence` inside a `TrackPoint`, not from the detection. Filling this would mean walking that reference backwards, which is a join. **Gap 19** |

#### `ESM`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| *(no attributes)* | — | `Event.payload` | `nits 1.0.0` | §2.5.18: a placeholder with no attributes. Parked present-and-empty |

#### `Radar4607`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Radar4607.reportIndex` | `[1]` | `Event.payload` | `nits 1.0.0` | 4607 field D32.1, the MTI report's index within the dwell |
| `Radar4607.hrrType` | `[1]` | `Event.payload` | `nits 1.0.0` | 4607 field H23, an eight-value enumeration in a `byte` with 8–255 reserved. Parked as the integer **and** the wording; a reserved value goes to `unresolved_raw` |

#### `Image`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Image.pixelMask` | `[0..1]` | `Event.payload` | `nits 1.0.0` | a `PixelMask`. Image space; attributes-only, per the coordinate settlement |
| `Image.centroidPixel` | `[0..1]` | `Event.payload` | `nits 1.0.0` | `[row, column]`, **0-based**, and note the order is row-then-column while the `PIXELS` coordinate system is x-then-y. The two orders are opposite and both appear in this model; each is parked under a key naming which |
| `Image.color` | `[0..1]` | `Event.payload` | `nits 1.0.0` | three RGB bytes, the object's dominant colour, per MISB ST 0903.4 Target Color |
| `Image.chip` | `[0..1]` | `Event.payload` | `nits 1.0.0` | an `ImageChip`; its own table |

#### `ImageChip`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `ImageChip.type` | `[1]` | `Event.payload` | `nits 1.0.0` | an IANA image media subtype; MISB ST 0903.4 limits it to `jpeg` and `png`. An XML attribute, not an element |
| `ImageChip.uri` | `[0..1]` | `Event.payload` | `nits 1.0.0` | a URI to a stored image. Parked and **never dereferenced** — the same refusal as `SensorInformation.url` |
| `ImageChip.image` | `[0..1]` | `Event.payload` | `nits 1.0.0` | the image itself, base64 in the XML syntax. **Parked whole**, never re-encoded and never transcoded: the never-drop rule does not have a size exemption, and a chip that is megabytes is a payload the caller chose to send. The standard notes XML "does not lend itself to inclusion of such binary data", which is a hint about `uri` and not a licence to drop `image` |

#### `SensorMeasurement`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `SensorMeasurement.quantity` | `[1]` | `Entity.attributes` | `nits 1.0.0` | `MeasurementType`: `SNR`, `RADIANT_INTENSITY`, `RADIANCE`, `DIRECTIONAL_REFLECTANCE`. The units are fixed by the literal and are recorded with the value, because a bare number in W·sr⁻¹·m⁻² has been read as three things |
| `SensorMeasurement.method` | `[1]` | `Entity.attributes` | `nits 1.0.0` | `MeasurementMethod`: `MEAN`, `MAX`. Parked, and it changes what the value means |
| `SensorMeasurement.value` | `[1]` | `Entity.attributes` | `nits 1.0.0` | the measurement |
| `SensorMeasurement.uncertainty` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | the producer's 1-sigma. **Not `Position.accuracy_m`** — an SNR uncertainty is not a position error, and the class is explicit that it covers sensor quantities and not derived ones like the length of an object |

### Row set — `TrackData`, `TrackSource`, `TrackSegment`, `TrackPoint`

#### `TrackData`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `TrackData.uid` | `[0..1]` | `Track.track_id` | `nits 1.0.0` | **the track's identity**, via `ids.derive` with `kind="track"`, system `NITS_UID`. Also an `Entity.source_ids[].external_id`, and the fallback key for `Entity.entity_id` when no `TrackedObject` carries one — the `kind` argument is what keeps the two id spaces apart |
| `TrackData.lid` | `[0..1]` | `Track.track_id` | `nits 1.0.0` | system `NITS_LID`, **only** as the `lidScopeUID` composite |
| `TrackData.trackSource` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | a `TrackSource` for the track as a whole, overridable per segment; its own table |
| `TrackData.segment` | `[0..*]` | `Track.samples[]` | `nits 1.0.0` | `TrackSegment`. **All of them feed the one `Track`, in document order** — a segment is a subdivision of this track, not a track. `attributes.nits_segments[]` records each segment's own attributes against the half-open range of sample indices it covers |
| `TrackData.object` | `[0..*]` | `Entity.entity_type` | `nits 1.0.0` | `TrackedObject`. **One `Entity` per `TrackData` regardless of how many objects are stated** — `Track.entity_id` is singular. Where several are present the standard says "the data consumer shall interpret the track data as applying to the set of multiple objects **as a group**", so the group is the entity, every instance is parked in full, and `attributes.tracked_object_count` says how many. Merging their attributes would be the consolidation rule, applied inside a document |

#### `TrackSource`

Eight reference lists, no data of its own. Every one of them is **gap 14** and, structurally,
**gap 19**.

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `TrackSource.sensorUID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | which sensors produced the detections behind this track |
| `TrackSource.sensorLID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | the local form |
| `TrackSource.trackerUID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | which trackers |
| `TrackSource.trackerLID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | the local form |
| `TrackSource.collectionUID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | which collections |
| `TrackSource.collectionLID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | the local form |
| `TrackSource.productUID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | which products. The standard warns these **cannot** be resolved from the file at all — "the link … must be made with data external to this NITSRoot" — so they are parked as opaque identifiers by the format's own instruction |
| `TrackSource.productLID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | likewise |

A `TrackSource` inside a `TrackSegment` **overrides** the one on the enclosing `TrackData`, per
§2.5.24 — for that portion of the track and no more. Both are parked: the track-wide one at
`attributes.nits_track_source`, and each segment's at `attributes.nits_segments[].source`
**against the sample index range it governs**, which is the only place the CDM can express "these
points came from that sensor". The override is recorded rather than applied by flattening, because
which one was in force over which points is a fact about the document. This is the concrete cost
of **gap 16**: the format attaches provenance to a range of samples and the CDM's `TrackSample`
has no bag to attach it to.

#### `TrackSegment`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `TrackSegment.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | **not a `Track.track_id`** — a segment is a subdivision of a track and not a track. Parked at `attributes.nits_segments[].uid`. "The producer only needs to specify this value if they want the power to update previously-reported track segment", so its absence means the producer never intends to revise, which is itself worth recording |
| `TrackSegment.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | likewise, as the `lidScopeUID` composite where there is a scope |
| `TrackSegment.segmentSource` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | a `TrackSource` overriding the track's, for this segment's sample range only |
| `TrackSegment.confidence` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | **does not reach `Track.track_quality`** — see the note below. A `Confidence`, parked per segment. **Gap 18** |
| `TrackSegment.comment` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | free text; §2.1.1.4 forbids parsing it |
| `TrackSegment.status` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | `TrackStatus`. **Does not set `Entity.valid_to`** — see the note below. **Gap 16** |
| `TrackSegment.initiationReason` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | `TrackInitiationReason`, used only when the status is `INITIATING` |
| `TrackSegment.terminationReason` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | `TrackTerminationReason`, used only when the status is `TERMINATED` |
| `TrackSegment.tp` | `[0..*]` | `Track.samples[]` | `nits 1.0.0` | `TrackPoint`, appended to the `TrackData`'s single `Track` in document order. **Zero is conformant**, and a segment with no points contributes no samples — a retraction-only one becomes an `Event` |

`TrackStatus`: `INITIATING`, `MAINTAINING`, `SEARCHING`, `TERMINATED`, `GROUND_TRUTH`.
`TrackInitiationReason`: `SENSOR_ON`, `ENTERED_FOV`, `FOUND`, `REINITIATING`, `COLLECTION_START`.
`TrackTerminationReason`: `SENSOR_OFF`, `EXITED_FOV`, `LOST`, `OBSCURED`, `SENSOR_DEFECT`,
`COLLECTION_END`.

**`TERMINATED` does not close `Entity.valid_to`, and the termination reasons are the argument.**
Four of the six — `SENSOR_OFF`, `EXITED_FOV`, `LOST`, `OBSCURED` — say the *sensor* stopped seeing
the object, not that the object stopped existing. A truck that drives under a bridge is still a
truck. `valid_to` means "when this state ceased", and writing the last sample's instant into it
would tell every downstream consumer the contact ended when in fact the coverage did. So
`valid_to` stays `None`, the status and its reason are parked in full, and
`attributes.valid_to_basis` records that the track terminated and the entity did not. This is the
same reading CAT021 gives its own absence of a staleness field, reached here from a field that
exists.

**`GROUND_TRUTH` is a status and not a synthetic flag.** It says the track was not produced by a
tracker; it says nothing about whether the underlying collection was real. `essence` is the
format's answer to that question and **neither of them touches `source.synthetic`**, which is the
deployment's to declare.

**`Track.track_quality` is `None` on every NITS track, and the reason is a consequence of the
`TrackData` identity boundary.** There is no track-level quality in Edition B: `TrackData` has
five attributes and none of them is a confidence. The only confidence anywhere near a history is
`TrackSegment.confidence`, and a segment is a *portion* of the track — so filling `track_quality`
from one would mean either picking a segment, or aggregating across them, and both are judgements.
Worse, the obvious special case is the worst option available: mapping it when a `TrackData`
happens to have exactly one segment would make a canonical field's presence depend on how a
producer chose to chunk its output, which is the same defect the modality-through-`TrackSource`
reading has and is rejected for the same reason.

So every segment confidence is parked at `attributes.nits_segments[].confidence` against the
sample range it covers, and `attributes.track_quality_basis` records that Edition B states no
track-level quality. `TrackedObject.confidence` is a different claim — the producer's confidence
in the *object description* — and it still reaches `Entity.confidence`, on the `PROBABILITY`-only
terms set out there.

**Gap 3's subject does not exist in Edition B, and its anchor moves accordingly.** That gap
records "4676 integer 0–15 → CDM float 0–1" with a conversion of `value / 15`, written against
`Track/trackQuality` — an **Edition A** attribute. The re-architecture removed it and put nothing
track-level in its place, so no row in this row set evidences a quality *scale* problem. What the
`Confidence` class substitutes is a different problem entirely and it has its own number: a value
is uninterpretable without its `type`, which is **gap 18**. The gap below says so in a sentence
rather than being deleted or being propped up with an Edition A name the guard test forbids.

#### `TrackPoint`

Sixteen attributes hang off a track point. **`TrackSample` has two** — `position` and
`observed_at` — and it is `extra="forbid"` with no extension bag. That mismatch is **gap 16**, and
this table is its evidence.

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `TrackPoint.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | **gap 16** — a sample has no identity in the CDM, so the point's own UUID is parked on the owning Entity keyed by sample index |
| `TrackPoint.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | likewise |
| `TrackPoint.relTime` | `[0..1]` | `Track.samples[].observed_at` | `nits 1.0.0` | the integer count. "Required unless the value would be 0", and an omitted value **is** zero. The raw integer is parked so egress re-emits it rather than recomputing from the millisecond `Timestamp` |
| `TrackPoint.dynSrcUID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | which frame this point came from. **Gap 14**, **gap 16** |
| `TrackPoint.dynSrcLID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | likewise |
| `TrackPoint.associatedDetection` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | whether the point has an associated detection. Note it is a **Boolean about association**, distinct from the `Evidence` that names which detection — so `TRUE` with no `Evidence` is a meaningful state and is recorded as one |
| `TrackPoint.processType` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | `ProcessType`: `MANUAL`, `AUTOMATIC`. **Does not set `Position.position_source`** — it says whether a human or an algorithm created the point, not how the position was obtained. `MANUAL` in the CDM means a manually *entered* coordinate, which is a different claim |
| `TrackPoint.confidence` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | the producer's confidence that this point belongs to the segment. **Gap 18**, **gap 16** — parked whole |
| `TrackPoint.comment` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | free text, unparsed |
| `TrackPoint.outline` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | a `Shape` — the object's estimated outline at this instant. **Gap 8** in its strongest form: a per-instant footprint, and the CDM's `Entity` has no geometry at all |
| `TrackPoint.outlineObscured` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | the obscured part of that outline, "a portion of the outline reported in `TrackPoint: outline`". Parked with the relationship recorded; a document carrying it without `outline` is non-conforming and is noted rather than repaired |
| `TrackPoint.nearestConfuser` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | metres to the nearest similarly-shaped object with similar dynamics. **Not `Position.accuracy_m`** — a confuser distance is a statement about ambiguity of *association*, not about the error of a fix, and the two are opposite kinds of number |
| `TrackPoint.nearestConfuserConfidence` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | a `Confidence` on that distance. **Gap 18** |
| `TrackPoint.sm` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · parked` | `SensorMeasurement`, per point. **Gap 16** |
| `TrackPoint.dynamics` | `[0..*]` | `Track.samples[].position` | `nits 1.0.0` | `Dynamics`; its own table. The block that produces the sample's position, chosen by the coordinate-system preference order |
| `TrackPoint.evidence` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · parked` | `Evidence`; its own table. **Gap 19** |

**A `TrackPoint` whose `Dynamics` all sit in an attributes-only coordinate system cannot be a
`TrackSample`,** because `TrackSample.position` is required and `Position` requires a real
latitude and longitude. Those points are parked in full at
`attributes.nits_unpositioned_points[]`, with their instants and their raw coordinates, and they
are **not** silently skipped: a `Track` whose sample count is lower than the segment's point count
is a track with holes in it, and a consumer has to be able to see that. Where *no* point in a
segment yields a position, the segment produces no `Track` at all and its points are parked on the
Entity with a basis saying why.

#### `Dynamics`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Dynamics.cs` | `[1]` | `Position.lat` | `nits 1.0.0` | `CoordinateSystemType`, and the attribute the entire coordinate settlement turns on. An XML attribute, not an element |
| `Dynamics.pos` | `[1]` | `Track.samples[].position.lat` · `Track.samples[].position.lon` · `Track.samples[].position.alt_m` | `nits 1.0.0` | the centroid position, on every point of the history. Mandatory, which is why a velocity always has a position to build a local horizon at. Raw array parked verbatim at `attributes.nits_position` |
| `Dynamics.pos` *(last positioned point)* | `[1]` | `Entity.position` | `nits 1.0.0` | the same value, once more, as the entity's current state — see the state note above. `Track.samples[].position.position_source` and `Entity.position.position_source` are both `ESTIMATED` |
| `Dynamics.vel` | `[0..1]` | `Entity.kinematics` | `nits 1.0.0` | **gap 4, and the first source that answers it** — decomposed into `Kinematics.speed_mps`, `Kinematics.course_deg` and `Kinematics.climb_mps` for `ECEF`, for CFT-resolved `LOCAL_CARTESIAN`, and for `WGS_84` **only when the height axis is present**; parked whole for two-dimensional `WGS_84` and for the other three systems. The raw array is always parked. **And gap 16**: the CDM has one `Kinematics`, on the `Entity`, while NITS states a velocity at every point — so only the last positioned point's reaches it and the rest are parked per point |
| `Dynamics.acc` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | the CDM models no acceleration in any frame, so this is parked whole regardless of coordinate system — as `adapters/legion.py` parks its own |
| `Dynamics.cov` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | a `CovarianceMatrix` over position, or position and velocity, or all three. **Gap 17** — parked whole, and never reduced to `Position.accuracy_m` |
| `Dynamics.cftUID` | `[0..1]` | `Position.lat` | `nits 1.0.0` | the transform a local coordinate resolves through. Unresolvable within the payload makes the block attributes-only |
| `Dynamics.cftLID` | `[0..1]` | `Position.lat` | `nits 1.0.0` | the local form |

`CoordinateSystemType`: `WGS_84`, `ECEF`, `ECI_J2K`, `LOCAL_CARTESIAN`, `LOCAL_SPHERICAL`,
`PIXELS`. Handled individually in the coordinate settlement.

**Note the all-or-nothing third axis.** For `WGS_84` and `LOCAL_CARTESIAN` the standard says the
third component "must either be reported for all three vectors, or not reported for any of the
three". So a two-component `pos` is a **stated** two-dimensional position, `Position.alt_m` is
`None`, and that `None` means the producer reported no height — not that the height is zero and
not that it is unknown-because-we-lost-it. It lands in `attributes.unavailable_fields`, which is
where "the source said it does not know" belongs; the all-or-nothing rule is what makes it safe to
say that.

#### `Evidence`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Evidence.type` | `[1]` | `Entity.attributes` | `nits 1.0.0` | `EvidenceType`: `DIRECT` (the object itself was seen) or `CIRCUMSTANTIAL` (only signs of it). An XML attribute |
| `Evidence.subtype` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | `EvidenceSubtype`: `WAKE`, `DUST_PLUME`, `TIRE_TRACKS`, `SHADOW`, "other values defined by registration" — so an unknown literal is expected and is parked, never refused |
| `Evidence.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | needed only if the producer wants to revise the association later |
| `Evidence.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | likewise |
| `Evidence.detectionUID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · parked` | **the chain**: which detections support this track point. Parked as identifiers and **never resolved into the `Event` objects the detections became** — that is a join, and the CDM has no relation to hold it. **Gap 19** |
| `Evidence.detectionLID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | likewise |
| `Evidence.confidence` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | the producer's confidence in the association itself. **Gap 18** |

**The evidence chain is the clearest thing NITS has that the CDM cannot say.** A track point is
supported by evidence, the evidence names detections, each detection names a sensor and a frame,
the frame names a coordinate transform, and a tracked object names an example detection. Six kinds
of reference, all resolvable inside a STANDALONE document, all reduced here to parked identifiers
because the CDM has one relation and it is `Event.related_entities`, which holds entity ids only.
That is **gap 19**, and this table is why it is opened rather than folded into gap 11 or gap 14.

### Row set — `TrackedObject` and the identity classes

#### `TrackedObject`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `TrackedObject.uid` | `[0..1]` | `Entity.entity_id` | `nits 1.0.0` | **the preferred key**, via `ids.derive`, system `NITS_UID`; also an `Entity.source_ids[].external_id` |
| `TrackedObject.lid` | `[0..1]` | `Entity.entity_id` | `nits 1.0.0` | system `NITS_LID`, as the `lidScopeUID` composite only |
| `TrackedObject.description` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | **the near-miss name.** Parked at `attributes.tracked_object_description` and deliberately not at any name-like key — see the identity settlement. **Gap 1** |
| `TrackedObject.numberOfObjects` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | how many objects the track covers, "if two vehicles are so close to each other that they are indistinguishable". The CDM's `Entity` is one thing with no cardinality, so this is parked and the entity is not multiplied — splitting one indistinguishable pair into two entities would invent two positions from one |
| `TrackedObject.objectColor` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | RGB triples "listed in order from most dominant to least dominant" — the order is data and is preserved |
| `TrackedObject.confidence` | `[0..1]` | `Entity.confidence` | `nits 1.0.0` | a `Confidence`, and the standard is explicit that it "applies to all attributes in this `TrackedObject` instance". Mapped to `Entity.confidence` **only** when `type` is `PROBABILITY` and `valid` is not `false`, on the same terms as `track_quality` above. **Gap 18** |
| `TrackedObject.dims` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | `[length, width, height, covLL, covLW, covLH, covWW, covWH, covHH]`. **Gap 8** — the CDM has no extent — and **gap 17** for the covariance half. Note the sentinels: an unmeasured dimension is `-1` and an inapplicable covariance is `0`, so `-1` is parked as `unavailable_fields` and never as a length |
| `TrackedObject.priority` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | producer-assigned, 1–255, **1 highest**. Parked and **not** mapped to `Event.severity`: a producer's collection priority is not an operational severity, and the inverted scale is exactly the kind of thing that gets read backwards |
| `TrackedObject.iffCode` | `[0..*]` | `Entity.source_ids[].external_id` | `nits 1.0.0` | `IFFCode`; its own table. Only `MODE_S` with a hex-parseable value becomes a `SourceId` |
| `TrackedObject.objectClass` | `[0..*]` | `Entity.entity_type` | `nits 1.0.0` | `ObjectClass`; its own table. Sets the entity type through the APP-6 table only, never the symbol |
| `TrackedObject.idSourceInformation` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | `IDSourceInformation`; its own table. Reaches neither affiliation nor confidence |
| `TrackedObject.id1241` | `[0..1]` | `Entity.affiliation` | `nits 1.0.0` | `ID1241`; its own table. The only path to `affiliation` in the whole model |
| `TrackedObject.exampleDetectionUID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · parked` | a detection that exemplifies the object. Parked as an identifier, never resolved. **Gap 19** |
| `TrackedObject.exampleDetectionLID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0` | likewise |

**Several `TrackedObject` instances with the same ID are not merged.** §2.5.29 and the
consolidation rule together describe a producer splitting one object's attributes across
instances so that different confidences can apply to different attributes — "if the `identity` and
`environment` have different levels of confidence, then two `TrackedObject`s should be reported".
Merging them is the consolidation this adapter refuses; every instance is parked in order, with
its own `Confidence` attached, and `attributes.tracked_object_instances` records how many there
were. A consumer holding all of them can apply the rule. One holding a merged result could not
tell which confidence went with which attribute, which is the whole point of the split.

#### `IFFCode`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `IFFCode.value` | `[1]` | `Entity.source_ids[].external_id` | `nits 1.0.0` | "the code value transmitted by an IFF system", typed `String` with **no stated syntax for any mode** — see the ambiguity table. Becomes an `ICAO24` `SourceId` only for `MODE_S` and only when it parses as six unambiguous hex digits |
| `IFFCode.mode` | `[1]` | `Entity.attributes` | `nits 1.0.0` | `IFFMode`: `MODE1`, `MODE2`, `MODE3`, `MODE4`, `MODE5`, `MODE_C`, `MODE_S`. **`MODE4` and `MODE5` never reach `affiliation`** — the CAT021 decline, second occurrence. `MODE_C` is a pressure altitude and never reaches `Position.alt_m` |

#### `ObjectClass`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `ObjectClass.table` | `[1]` | `Entity.entity_type` | `nits 1.0.0` | `APP-6Table`, fourteen literals, all mapped in the table above |
| `ObjectClass.entity` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | the APP-6 entity string |
| `ObjectClass.entityType` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | "required if the tracked object has a listed entity type" |
| `ObjectClass.entitySubtype` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | likewise for a subtype |
| `ObjectClass.sector1Modifier` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | optional APP-6 modifier |
| `ObjectClass.sector2Modifier` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | optional APP-6 modifier |
| `ObjectClass.code` | `[1]` | `Entity.attributes` | `nits 1.0.0` | the 6-, 8- or 10-digit code, leading zeroes included, parked **as a string**. **Never composed into `Entity.symbol`** — see the identity settlement |

#### `IDSourceInformation`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `IDSourceInformation.idQualityNumber` | `[1]` | `Entity.attributes` | `nits 1.0.0` | "describes the quality of an ID Source Result", and typed **`String`** — so it is not a number the adapter may compare, rank or normalise, whatever it looks like |
| `IDSourceInformation.sourceDeclarationBinary` | `[1]` | `Entity.attributes` | `nits 1.0.0` | whether the source has a positive result, e.g. an IFF match. Parked; it does not reach `affiliation`, for the reason the class's own definition gives |
| `IDSourceInformation.sourceDeclarationExtension` | `[1]` | `Entity.attributes` | `nits 1.0.0` | the precise declaration where the source says more than match/no-match. Encoding defined by AIDPP-01, a document this row set does not adopt |
| `IDSourceInformation.relTimeCreation` | `[1]` | `Entity.attributes` | `nits 1.0.0 · parked` | when the declaration was created. **Gap 13** — two times on one object and the CDM has no per-measurement time at all |
| `IDSourceInformation.relTimeExchange` | `[1]` | `Entity.attributes` | `nits 1.0.0` | when the message sender transmitted it. Deliberately **not** `Event.received_at`: that is a third party's transmission, not our receipt |
| `IDSourceInformation.idSourceNumber` | `[1]` | `Entity.attributes` | `nits 1.0.0` | an `IDSourceNumber`; its own table |

#### `IDSourceNumber`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `IDSourceNumber.sourceType` | `[1]` | `Entity.attributes` | `nits 1.0.0` | the generic grouping of ID sources |
| `IDSourceNumber.sourceSubtype` | `[1]` | `Entity.attributes` | `nits 1.0.0` | the subgroup |
| `IDSourceNumber.sourceDeviceClass` | `[1]` | `Entity.attributes` | `nits 1.0.0` | the precise ID source. All three are `String` and all three are defined by AIDPP-01; parked verbatim |

#### `ID1241`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `ID1241.identity` | `[0..1]` | `Entity.affiliation` | `nits 1.0.0` | `Identity`, STANAG 1241 Ed. 5. **Gap 2** — six literals into four, mapped in the table above |
| `ID1241.identityAmplification` | `[0..1]` | `Entity.affiliation` | `nits 1.0.0` | `IdentityAmplification`: `FAKER`, `JOKER`, `KILO`, `TRAVELER`, `ZOMBIE`. **`FAKER`, `JOKER` and `KILO` yield `FRIENDLY`**, overriding a contradicting `identity`, because Edition B defines all three as friendly in the first word; the exercise role is parked at `attributes.exercise_role`. `TRAVELER` and `ZOMBIE` are `SUSPECT` and set nothing — **gap 2**. See the settlement |
| `ID1241.identitySourceModality` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | a `ModalityType`, "transmitted only if the `identity` is provided". Parked; it says how the identity was reached, and the CDM has no provenance for an affiliation |
| `ID1241.environment` | `[0..1]` | `Entity.attributes` | `nits 1.0.0` | `TrackEnvironment`: `LAND`, `SURFACE`, `SUB-SURFACE`, `AIR`, `SPACE`, `UNKNOWN`. **A domain, not a kind** — does not set `entity_type` |

### Row set — the analysis classes, all carried and none acted on

#### `ProcessedTrack`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `ProcessedTrack.type` | `[1]` | `Event.payload` | `nits 1.0.0` | `ProcessedTrackType`: `FUSED`, `SMOOTHED`. An XML attribute |
| `ProcessedTrack.uid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0` | system `NITS_UID` |
| `ProcessedTrack.lid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0` | system `NITS_LID`, scoped |
| `ProcessedTrack.confidence` | `[0..1]` | `Event.payload` | `nits 1.0.0 · parked` | a `Confidence`, and the mechanism by which a producer **retracts** a processing claim: same ID, `valid = false`. Carried, never applied. **Gap 18** |
| `ProcessedTrack.inputUID` | `[0..*]` | `Event.payload` | `nits 1.0.0` | "two or more input track UUIDs". Parked as identifiers. **Not `related_entities`** — these are track ids |
| `ProcessedTrack.inputLID` | `[0..*]` | `Event.payload` | `nits 1.0.0` | likewise |
| `ProcessedTrack.outputUID` | `[0..1]` | `Event.payload` | `nits 1.0.0` | the output track. Parked; the adapter emits no combined track |
| `ProcessedTrack.outputLID` | `[0..1]` | `Event.payload` | `nits 1.0.0` | likewise |
| *(derived)* | — | `Event.observed_at` | `nits 1.0.0` | **`TrackMessage.baseTime`.** This is the only class in the model with no time attribute of any kind, and `payload.observed_at_basis` says so rather than implying the producer stated an instant |
| *(derived)* | — | `Event.event_type` | `nits 1.0.0` | `STATUS_CHANGE`. Not `TRACK_UPDATE`: nothing about a track's state was updated, a *relationship between* tracks was asserted |

Note the cardinality contradiction the standard carries here: `inputUID` is described as "two or
more input track UUIDs" and then, in the same cell, "all currently-defined `ProcessedTrack`s must
have **a single** input track specified as either a UID or LID". Recorded in the ambiguity table;
the adapter parks whatever count arrives and asserts neither.

#### `TrackLinkage`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `TrackLinkage.type` | `[1]` | `Event.payload` | `nits 1.0.0` | `TrackLinkageType`: `MERGE`, `SPLIT`, `STITCH`. An XML attribute |
| `TrackLinkage.uid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0` | system `NITS_UID` |
| `TrackLinkage.lid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0` | system `NITS_LID`, scoped |
| `TrackLinkage.relTime` | `[0..1]` | `Event.observed_at` | `nits 1.0.0` | "the time when the relationship started". Resolved against the message base; omitted means zero |
| `TrackLinkage.confidence` | `[0..1]` | `Event.payload` | `nits 1.0.0 · parked` | the retraction mechanism again. **Gap 18** |
| `TrackLinkage.preUID` | `[0..*]` | `Event.payload` | `nits 1.0.0` | tracks existing before the relationship. The counts are type-dependent — `SPLIT` `[1]`, `MERGE` `[2..*]`, `STITCH` `[1]` — and are **checked and recorded**, never enforced by dropping the linkage |
| `TrackLinkage.postUID` | `[0..*]` | `Event.payload` | `nits 1.0.0` | tracks existing after — `SPLIT` `[2..*]`, `MERGE` `[1]`, `STITCH` `[1]` |
| `TrackLinkage.preLID` | `[0..*]` | `Event.payload` | `nits 1.0.0` | the local forms, same counts |
| `TrackLinkage.postLID` | `[0..*]` | `Event.payload` | `nits 1.0.0` | likewise |
| *(derived)* | — | `Event.event_type` | `nits 1.0.0` | `STATUS_CHANGE`, and `Event.related_entities` is empty — see the no-fusion settlement |

**A `MERGE` or `SPLIT` may legitimately reuse one identifier on both sides** — a motorcycle riding
into a trailer, or off one — so a `preUID` equal to a `postUID` is conformant and is **not** a
defect to flag. Recorded here because an adapter author's first instinct is to validate it away.

#### `MotionEvent`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `MotionEvent.type` | `[1]` | `Event.payload` | `nits 1.0.0` | `MotionEventType`, seventeen literals. **Parked, not mapped to `EventType`** — see below |
| `MotionEvent.uid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0` | system `NITS_UID` |
| `MotionEvent.lid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0` | system `NITS_LID`, scoped |
| `MotionEvent.trackUID` | `[0..*]` | `Event.payload` | `nits 1.0.0` | the tracks involved. Parked as identifiers; **not** `related_entities`, which holds entity ids |
| `MotionEvent.trackLID` | `[0..*]` | `Event.payload` | `nits 1.0.0` | likewise |
| `MotionEvent.startRelTime` | `[1]` | `Event.observed_at` | `nits 1.0.0` | **the one relTime in the model whose absence does not mean zero** — see below |
| `MotionEvent.endRelTime` | `[0..1]` | `Event.payload` | `nits 1.0.0` | parked. Its absence means "unknown **or** instantaneous", two different facts under one silence, and both are recorded as the one silence rather than one being chosen |
| `MotionEvent.confidence` | `[0..1]` | `Event.payload` | `nits 1.0.0 · parked` | a `Confidence`. **Gap 18** |
| `MotionEvent.region` | `[0..1]` | `Event.geometry` | `nits 1.0.0` | a `Shape` for an ROI-type event. **Becomes a `Polygon` geometry** when its coordinate system is `WGS_84` or transformable `ECEF`, through the three polygon corrections; attributes-only otherwise. This and `tripwire` are the only two places in the model where a NITS shape reaches `Event.geometry` |
| `MotionEvent.tripwire` | `[0..1]` | `Event.geometry` | `nits 1.0.0` | a `PositionPoints` whose vertices "do not form a closed polygon" — so a **`LineString`**, in vertex order, which the standard says "indicates how the tripwire should be drawn" |

`MotionEventType`: `START`, `STOP`, `INTERMITTENT_MOTION`, `LEFT_TURN`, `RIGHT_TURN`,
`LEFT_U-TURN`, `RIGHT_U-TURN`, `ACCELERATION`, `DECELERATION`, `COLLISION`, `MEETING`, `OBSCURED`,
`ENTERING_ROI`, `INSIDE_ROI`, `EXITING_ROI`, `CROSSING_TRIPWIRE`, `CONVOY`.

**The seventeen literals are parked and this is deliberately not a gap.** `EventType` is an axis
about *what kind of report this is* — a detection, a track update, an alert — and a maneuver
vocabulary is about what the subject did. That is the settlement Legion's `event_type` reached
when its eight detection classes collided with the CDM's enum of the same name, and the same
answer applies: `Event.event_type` is `STATUS_CHANGE`, the literal is parked at
`payload.motion_event_type`, and nothing is lost. Not every mismatch between a source vocabulary
and a CDM enum is a gap; this one is a difference of axis.

**Severity stays `INFO` even for `COLLISION`.** Grading a collision or a tripwire crossing as
`WARNING` is a judgement about operational significance, and the standard hands the definition of
every one of these events to the producer — §2.5.37: "the definition of each motion event is
largely left to the data producer (for example, what speed constitutes a `START` or `STOP`
event)". A translator that graded a producer-defined event would be grading something whose
threshold it does not know. The Legion `GUNSHOT` line, in a format that argues the point for us.

**`startRelTime` is the one place the message-wide relTime rule is overridden, and the standard
says so in the attribute's own description**: "Where the `startRelTime` is unknown, it means the
data producer does not know the start time, i.e. **the value does not default to `baseTime`**."
The attribute is nonetheless `[1]`, so a conformant document always carries it and the two
statements cannot both be satisfied — an ambiguity, recorded below. The adapter handles the
non-conformant case rather than failing on it: the `Event` is still emitted, `observed_at` falls
to `baseTime`, `payload.unavailable_fields` names `startRelTime`, and
`payload.observed_at_basis` states that the format defines this absence as *unknown* and that the
instant carried is a substitute the producer did not state. That is the least-bad of three bad
options and it is the one flagged for challenge.

### Row set — COMMON: geometry, uncertainty and identifiers

#### `Shape` — abstract, and never on the wire

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Shape.dims` | `[1]` | `Event.geometry` | `nits 1.0.0` | `Dimensionality`, literals `2` and `3`. Decides how the flat vertex array is split into tuples, so getting it wrong shifts every coordinate after the first |
| `Shape.cs` | `[1]` | `Event.geometry` | `nits 1.0.0` | `CoordinateSystemType` for every vertex or ellipse parameter. The coordinate settlement decides whether a shape can be a geometry at all |
| `Shape.cftUID` | `[0..1]` | `Event.geometry` | `nits 1.0.0` | "if the points are specified in a local coordinate system, then either the `cftLID` or `cftUID` is required" |
| `Shape.cftLID` | `[0..1]` | `Event.geometry` | `nits 1.0.0` | the local form |

`Shape` is **abstract** and, per the CONVENTIONS, "an instance of the abstract class itself will
never be contained within a STANAG 4676 file"; a conformant XML document names the concrete type
with `xsi:type`. So a `Shape`-typed element with **no** `xsi:type` is non-conforming and is a
refusal quoting the element path — guessing between `Polygon` and `Ellipsoid` from the presence of
`vertices` would be inferring a type the document was required to state.

#### `Polygon`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Polygon.nRings` | `[0..1]` | `Event.geometry` | `nits 1.0.0` | "shall not be omitted" when the count is not 1. Used as a **checksum on the `NaN` split**, not as the split itself; a disagreement is a refusal quoting both counts |
| `Polygon.vertices` | `[1]` | `Event.geometry` | `nits 1.0.0` | one flat `DoubleArray` of all rings, tuples of `dims` values, rings separated by an all-`NaN` null point. Becomes a GeoJSON `Polygon` after the three corrections — axis order, winding, explicit closure — only from `WGS_84` or transformable `ECEF` |

#### `Ellipsoid`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Ellipsoid.center` | `[1]` | `Entity.attributes` | `nits 1.0.0` | a **9-element** array: `x y z covXX covXY covXZ covYY covYZ covZZ`, in the units of the `Shape`'s coordinate system. Sentinels matter — a 2-D ellipse sets `z` and `covZZ` to `-1`, and an unknown centre uncertainty sets all three diagonals to `-1`, so `-1` is never read as a coordinate or a variance |
| `Ellipsoid.ellipsoidParameters` | `[1]` | `Entity.attributes` | `nits 1.0.0 · parked` | a `CovarianceMatrix` giving the axis lengths and orientation. **Gap 17** |

**An `Ellipsoid` is never a `Geometry` and never an `accuracy_m`.** It is an uncertainty region,
not a footprint: the class exists to express an error ellipse whose shape *is* a covariance matrix.
Rendering it as a polygon would put a confidence region on the map as though it were an object,
and collapsing it to one horizontal 1-sigma metre figure would state a precision nobody measured —
Legion's covariance refusal, on a class built for the purpose.

#### `PixelMask`, `PixelPolygon`, `PixelRun`

All three are image space. Attributes-only in full, per the coordinate settlement, and parked with
the `DynamicSourceInformation` reference that says which frame they index into.

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `PixelMask.pixelPolygon` | `[0..1]` | `Event.payload` | `nits 1.0.0` | vertices of a polygon in pixel space |
| `PixelMask.pixelRun` | `[0..1]` | `Event.payload` | `nits 1.0.0` | a bit mask as row and column runs |
| `PixelPolygon.nRings` | `[0..1]` | `Event.payload` | `nits 1.0.0` | as `Polygon.nRings`, and the null point here is all **`-1`**, not `NaN` |
| `PixelPolygon.integerArray` | `[1]` | `Event.payload` | `nits 1.0.0` | `[row_1, col_1, row_2, col_2, …]` — **row-then-column, which the standard notes is "the opposite of the order for the `PIXELS` coordinate space"**. Parked with the order named, because two opposite conventions in one model is how a mask lands transposed |
| `PixelRun.rs` | `[0..*]` | `Event.payload` | `nits 1.0.0` | each entry is `(start row, start column, run length across columns)` |
| `PixelRun.cs` | `[0..*]` | `Event.payload` | `nits 1.0.0` | each entry is `(start row, start column, run length across rows)`. Row and column runs may overlap and both are kept |

Pixel indices are **0-based** throughout, per the CONVENTIONS, and the standard warns that
converting from a MISB ST 0903 source requires translating 1-based coordinates. The adapter
translates nothing: it reads NITS, where the base is 0, and records the base in the parked value
so a consumer never has to guess which convention a mask arrived in.

#### `IDData`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `IDData.stationID` | `[1]` | `Entity.attributes` | `nits 1.0.0` | STANAG 4545's OSTAID: "a sequence of 10 alphanumeric characters, **the last 2 of which must be spaces**". Parked with the padding intact — trimming it would produce a string that is not the OSTAID |
| `IDData.nationality` | `[1]` | `Entity.attributes` | `nits 1.0.0 · parked` | a `NationalityTrigraph`, three letters per APP-11(D). "In the case of a fused track, the nationality shall be that of the nation fusing the tracks" — so this names the producer, and the pair `stationID` + `nationality` is what "provides unique identification of any given STANAG 4676-capable system". **Gap 14**, and the single best evidence for it in any format here |

#### `CovarianceMatrix`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `CovarianceMatrix.covarianceType` | `[1]` | `Entity.attributes` | `nits 1.0.0` | `CovarianceType`: `POS3D` (6 elements), `VEL3D` (21), `ACC3D` (45), `POS2D` (3), `VEL2D` (10), `ACC2D` (21). An XML attribute. **The element count is a checksum**: a matrix whose value count disagrees with its type is a refusal quoting both |
| `CovarianceMatrix` *(core class value)* | `[1]` | `Entity.attributes` | `nits 1.0.0 · parked` | the values themselves — "only the diagonal and upper-right triangle elements … reported Left-to-Right, Top-to-Bottom". The class's own content rather than a named attribute, like `UUID`'s. Parked verbatim, ordering intact. **Gap 17** |

#### `Confidence`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Confidence.type` | `[1]` | `Entity.attributes` | `nits 1.0.0 · parked` | `CertaintyStatisticType`: `HUMAN_INSTINCT`, `P-VALUE`, `PROBABILITY`, `T-STATISTIC`. An XML attribute. **The attribute that makes the value uninterpretable without it** — see gap 18 |
| `Confidence.value` | `[1]` | `Entity.confidence` | `nits 1.0.0` | 0–100. Reaches `Entity.confidence` as `value / 100` **only** when `type` is `PROBABILITY` and `valid` is not `false`; otherwise `None` with the whole block parked |
| `Confidence.sourceReliability` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | 0–100, a **separate** measure of the source, and the standard forbids folding it in: "the data producer must not factor in the reliability of the source into its calculation of its confidence in the value". The adapter must not either, and the CDM has one float — **gap 18** |
| `Confidence.valid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked` | the **retraction** flag. `false` means the producer has withdrawn the associated data. Carried verbatim and never applied; a value it invalidates is still parked, because applying a retraction means holding what it retracts. **Gap 18** |

The standard's own analogy is worth carrying: `value` "is intended to be analogous to credibility
(of information) criteria specified in AJP 2.1, whose values range from 1 to 6", and
`sourceReliability` to "reliability (of source) criteria … whose values range from A to F". That
is the classic two-axis intelligence evaluation, and the CDM has one axis.

#### `PositionPoints`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `PositionPoints.dims` | `[1]` | `Event.geometry` | `nits 1.0.0` | `Dimensionality`, 2 or 3; splits the flat array |
| `PositionPoints.cs` | `[1]` | `Event.geometry` | `nits 1.0.0` | `CoordinateSystemType` common to every point |
| `PositionPoints.points` | `[1]` | `Event.geometry` | `nits 1.0.0` | vertices "in the order in which they should be drawn", and **unlike a polygon they do not form a closed shape**. A single point becomes a `Point`, several become a `LineString`, and neither is ever closed |
| `PositionPoints.cftUID` | `[0..1]` | `Event.geometry` | `nits 1.0.0` | required when the points are local |
| `PositionPoints.cftLID` | `[0..1]` | `Event.geometry` | `nits 1.0.0` | the local form |

#### `UUID`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `UUID` *(core class value)* | `[1]` | `Entity.source_ids[].external_id` | `nits 1.0.0` | a 128-bit identifier per ITU-T X.667 / ISO/IEC 9834-8. In the XML syntax it is **`xs:base64Binary`, 22 characters**, not the 36-character canonical form — a guide-only fact, and one an adapter emitting canonical UUIDs would fail schema validation on |
| `UUID.gidp` | `[0..1]` | `Entity.source_ids[].external_id` | `nits 1.0.0` | the IC Identifier guide prefix. When present the identifier is the composed `guide://<gidp>/<value>`, and **the bare UUID is a different identifier** — keying on it would merge two objects that the producer distinguished |

### Row set — egress, CDM back to a NITSRoot document

Bidirectional where the protocol allows, and here the protocol allows a great deal because the
model is richer than the CDM: almost everything egress needs is either a canonical field or a
parked value it wrote itself on the way in.

| CDM | NITS | Status | Notes |
|---|---|---|---|
| `Track.samples[].observed_at` | `TrackPoint.relTime` | `nits 1.0.0 · egress` | **re-emitted from `attributes.nits_times`** for a round trip, never recomputed. For a CDM object of other origin, `relTimeIncrement` is set to `0.001` s so that the CDM's own three-decimal `Timestamp` is exactly representable as an integer count, and `relTime` is whole milliseconds since `baseTime` — exact, with no rounding anywhere |
| `Track.samples[].observed_at` | `TrackMessage.baseTime` | `nits 1.0.0 · egress` | the earliest sample instant in the message, which is what the standard asks for: "this should be the earliest time among all the time stamps in the constituent parts" |
| `Track.samples[].position.lat` · `Track.samples[].position.lon` · `Track.samples[].position.alt_m` | `Dynamics.pos` with `cs = WGS_84` | `nits 1.0.0 · egress` | latitude, longitude, height — **latitude first**, the axis order transposed back. A sample with no `alt_m` emits a two-component position, which is the all-or-nothing rule respected rather than a zero invented |
| `Kinematics.speed_mps` · `Kinematics.course_deg` · `Kinematics.climb_mps` | `Dynamics.vel` | `nits 1.0.0 · egress` | recomposed into the `WGS_84` angular rates using the same two named constants, or re-emitted verbatim from the park where the object came from NITS |
| `Track.track_id` | `TrackData.uid` | `nits 1.0.0 · egress` | from the park where there is one; otherwise a fresh v5 UUID over the CDM id, with `ProductIdentification.id` naming this system as the issuer. **Segmentation is restored from `attributes.nits_segments[]` where the object came from NITS**, and otherwise the whole history is emitted as a single `TrackSegment` — which §2.5.25 permits outright: "if the data producer deems it unnecessary to break a track into multiple track segments, then all track points of the track can be included is a single `TrackSegment` object" |
| `Track.entity_id` | `TrackedObject.uid` | `nits 1.0.0 · egress` | on the same terms |
| `Entity.affiliation` | `ID1241.identity` | `nits 1.0.0 · egress` | `FRIENDLY` → `FRIEND`, `HOSTILE` → `HOSTILE`, `NEUTRAL` → `NEUTRAL`, `UNKNOWN` → `UNKNOWN`. **`ASSUMED_FRIEND` and `SUSPECT` are never emitted** — the CDM cannot hold them, so it cannot state them, and re-widening the collapse would invent a judgement |
| `Entity.entity_type` | `ObjectClass.table` | `nits 1.0.0 · egress` | only where the ingest parked an APP-6 block, which is re-emitted verbatim. **A CDM entity of other origin emits no `ObjectClass` at all**: `code` is `[1]` and there is no honest code to write |
| `Entity.confidence` | `TrackedObject.confidence` | `nits 1.0.0 · egress` | as `value = round(confidence × 100)` with `type = PROBABILITY`, which is the only type the CDM's float can honestly claim |
| `Event.geometry` | `MotionEvent.region` / `.tripwire` | `nits 1.0.0 · egress` | the three polygon corrections run in reverse: rings re-wound to the NITS convention, axis order transposed, the explicit closing position dropped, rings joined by `NaN` null points and `nRings` recomputed |
| `Entity.attributes` | *(everything parked)* | `nits 1.0.0 · egress` | every parked block is restored to the class and attribute it came from. This is what makes the round trip worth claiming at all |
| `Entity.attributes` | `originatorConfidentialityLabel` | `nits 1.0.0 · egress` | verbatim from the park for a round-tripped object; from the deployment's configured label, logged as such, for a CDM-native one; **a refusal when neither exists** — the three paths in the classification settlement. A silent `UNCLASSIFIED` is forbidden |
| *(the injected clock)* | `NITSRoot.msgCreatedTime` | `nits 1.0.0 · egress` | when we wrote the file. The one value egress invents, and it is the same clock `received_at` uses |
| *(constant)* | `NITSRoot.nitsVersion` | `nits 1.0.0 · egress` | `"B.2"` |
| *(constant)* | `NITSRoot.profile` | `nits 1.0.0 · egress` | `STANDALONE`, always — see the profiles settlement |

**The round trip is not byte-exact and cannot be, unlike CAT021's.** XML permits insignificant
whitespace, attribute order and namespace prefix choice, none of which carries information, so
"the same octets" is not a meaningful target. The claim that *is* made is narrower and checkable:
**every value re-emitted equals the value read**, with the raw integers — `relTime`,
`relTimeIncrement`, coordinate arrays, covariance arrays, pixel runs, base64 image chips — taken
from the park rather than recomputed, and the confidentiality label reproduced as the exact
fragment that arrived. Where a value cannot be re-emitted it is a refusal that names it, not a
silent omission.

Three things egress will not do:

- **Emit a `DATASTREAM` document.** It has no earlier files to reference.
- **Emit a document with a dangling reference.** A parked `sensorUID` whose `SensorInformation`
  is not being written into the same file is a refusal naming the reference.
- **Emit an invented confidentiality label.** A configuration-supplied one is not invented — it is
  declared, logged and attributable to the deployment. A defaulted one is invented, and it is
  forbidden. Stated three times in this row set because it is the one failure whose consequence is
  not a wrong pixel on a map.

### What the adapter fills that NITS does not state

| NITS | CDM field | Status | Notes |
|---|---|---|---|
| *(none)* | `Event.received_at` | `nits 1.0.0` | the injected clock. Never `msgCreatedTime`, which is when the producer wrote the file, and never `IDSourceInformation.relTimeExchange`, which is when a third party sent a declaration |
| *(the deployment declaration)* | `Entity.source.synthetic` | `nits 1.0.0` | **no payload field sets this**, and `CollectionInformation.essence` in particular does not — it is parked, and a parked essence contradicting the declaration is a logged refusal rather than a flip in either direction. The CAT021 `SIM` rule and the Legion `EXERCISE_*` rule, held as a rule |
| *(configuration, where the object is CDM-native)* | `Entity.attributes` | `nits 1.0.0` | `attributes.confidentiality_label_basis` — which of the three egress label paths applied. A configured label is declared and logged; a defaulted one is forbidden |
| *(none — NITS states no severity anywhere)* | `Event.severity` | `nits 1.0.0` | `INFO`, with `payload.severity_basis` recording that the format grades nothing, including its own `COLLISION` motion event. `TrackedObject.priority` is a collection priority, not an operational severity, and is parked |
| *(none)* | `Event.event_type` | `nits 1.0.0` | `DETECTION` for a `Detection`; `STATUS_CHANGE` for a `MotionEvent`, a `TrackLinkage`, a `ProcessedTrack` and a retraction-only segment. **Never `TRACK_UPDATE`**, because in this format a track update is a `Track`, not an `Event` |
| *(derived)* | `Entity.symbol` | `nits 1.0.0` | from the affiliation via `symbology.sidc_from_affiliation`; `attributes.symbol_basis` says so, and says that an APP-6 code was present and not composed into a SIDC where one was |
| *(derived)* | `Position.position_source` | `nits 1.0.0` | `ESTIMATED`, always, with `attributes.position_source_basis` naming the sensor modality where it resolved and recording why the modality did not refine the field |
| *(the earliest point instant)* | `Entity.valid_from` | `nits 1.0.0` | else `TrackMessage.baseTime` for a `TrackData` with no points; `attributes.valid_from_basis` names which |
| *(none)* | `Entity.valid_to` | `nits 1.0.0` | `None`, even for a `TERMINATED` segment — four of the six termination reasons say the sensor stopped seeing the object, not that it ceased to exist |
| *(none — NITS carries no checksum of any kind)* | `Entity.attributes` | `nits 1.0.0` | `attributes.integrity_basis`, recording that the document passed schema-shaped structural checks and nothing more. A consumer comparing a NITS contact with a CAT021 one should be able to see which of the two was checked, and neither was |
| *(measured)* | `Entity.attributes` | `nits 1.0.0` | `attributes.unavailable_fields` — fields the source explicitly stated it does not know: a `dims` component of `-1`, a two-component `pos` under the all-or-nothing rule, a `MotionEvent` with no `startRelTime`. **An omitted `relTime` is not in this list**, because the standard defines that absence as zero |
| *(measured)* | `Entity.attributes` | `nits 1.0.0` | `attributes.unresolved_raw` — values read and not usable: an unrecognised enumeration literal, a reserved `hrrType`, a `CovarianceMatrix` whose element count disagrees with its type, a coordinate in an attributes-only system |
| *(measured)* | `Entity.attributes` | `nits 1.0.0` | `attributes.unresolved_references` — references that do not resolve inside this payload, each naming the referring attribute and the class it must point at. **A different fact from both lists above**, and the DATASTREAM profile is why it exists |
| everything unmapped | `Entity.attributes` | `nits 1.0.0` | `attributes.source_extras`, structure and namespace intact — and here that is not a formality: the schema declares open content on every complex type, so extension elements are expected rather than exceptional |

### Where the specification is ambiguous or contradicts itself

Every one of these will be hit by whoever writes the adapter. Each is handled by parking or
refusing, never by guessing.

| # | Finding | Consequence for the adapter |
|---|---|---|
| 1 | **`LOCAL_SPHERICAL`'s slot convention is unverifiable from the data.** Table 2.5.27-2 orders the array "radial, **polar**, azimuthal"; §2.5.13's normative conversion binds those three positionally to `r`, `θ`, `φ` and then puts `φ` — the slot labelled *azimuthal* — in the zenith position, `z = r cos φ`. A label-driven producer and an equation-driven producer therefore place bearing and elevation in swapped slots, both conformantly, and **both produce a valid point on a sphere**, so there is no range violation and no arithmetic failure to detect | `LOCAL_SPHERICAL` is **attributes-only**: no `Position`, no `Kinematics`, the array parked verbatim and both statements cited in the basis. Applying the equations would be confidently wrong half the time; refusing is withheld loudly. The Legion `EPSG:4979` refusal, reached from a different format. Note also that the CFT "cannot be used to directly convert to a non-Cartesian coordinate system (e.g., WGS 84)", so even an unambiguous slot order would leave a three-hop route whose first hop is the undetermined one |
| 2 | **`MotionEvent.startRelTime` is `[1]` and its own description contemplates its absence** — "where the `startRelTime` is unknown, it means the data producer does not know the start time, i.e. the value does not default to `baseTime`". A mandatory attribute cannot be unknown | the `Event` is still emitted, `observed_at` falls to `baseTime`, `payload.unavailable_fields` names the attribute and the basis states that the substitute is ours. The one place the model-wide "omitted `relTime` means zero" rule is overridden, and it is overridden by the standard, not by us |
| 3 | **`ProcessedTrack.inputUID` says two things in one cell**: "two or more input track UUIDs", then "all currently-defined `ProcessedTracks` must have **a single** input track specified as either a UID or LID" | whatever count arrives is parked and neither statement is enforced. A `FUSED` track with one input is conformant under one reading and not the other, and refusing it would drop data over a drafting error |
| 4 | **`IFFCode.value` is a bare `String` with no stated syntax for any of the seven modes.** A Mode 3/A code is octal, a Mode S address is 24 bits usually written hex, a Mode C value is an altitude — and the model gives one untyped string for all of them | only `MODE_S` with an unambiguous six-hex-digit value becomes an `ICAO24` `SourceId`. Everything else is parked raw with the radix recorded as unstated. **This is the single narrowest condition in the row set and it guards the single largest cross-adapter win** |
| 5 | **The XML element names are not knowable from the standard.** §"Naming" says tags were shortened "to as little as two letters" to fight file size, several are visible in the model (`tp`, `cs`, `sm`, `im`, `rs`), and §2.1.1.7 says the UML's attributes are elements "in almost every case" without listing the exceptions | the row set is stated at the **data-model** layer, which the standard itself calls encoding-agnostic. Phase 2 is **blocked** on obtaining and pinning the XSD, and that is recorded in the declines table rather than papered over with guessed names |
| 6 | **`Ellipsoid` describes its parameters two incompatible ways.** §2.6.3 says the ellipsoid is "defined based on a center, the lengths of the axes (**not the semi-axes**), and the orientation", and its own worked example sets the diagonal to "the radius of the circle squared" — 16 for a radius of 4, which is a semi-axis. The two readings differ by a factor of two on every error ellipse | contained by an independent decision: `Ellipsoid` is attributes-only in any coordinate system, so the adapter parks the parameters and interprets neither. Recorded because a future adapter tempted to render an error ellipse would have to resolve it first |
| 7 | **`TrackPoint.relTime` is described against a base that does not exist.** Its text says the count is "since the start time of the **track segment** (`TrackMessage.baseTime`)" — but a `TrackSegment` has no start time attribute, and `baseTime` is scoped to the message. The formula immediately below is correct. `TrackLinkage.relTime`'s description has the matching slip, telling the consumer to multiply "this value (`TrackPoint.relTime`)" | the formula is authoritative and the prose is a copy-paste. Recorded because an implementer reading the prose will look for a per-segment time base and not find one |
| 8 | **The guide sends an implementer to the wrong annex for the XSD.** AEDP-12.1 §B.1.9 says the two encodings are "defined by the XML schema specified in **Annex F**"; Annex F is Binary Encoding and the XSD is Annex D | none, beyond wasted time — recorded so the next reader loses none |
| 9 | **Two opposite pixel orders in one model, and the standard flags it itself.** `PixelPolygon.integerArray` is `[row, col]` and "the order of coordinates for an individual point is the opposite of the order for the `PIXELS` coordinate space", which is `[x, y]`. `Image.centroidPixel` is `[row, column]` again | every pixel value is parked under a key naming its order. Nothing is transposed, because the only correct transposition depends on which of the two conventions a given attribute uses and the model uses both |
| 10 | **`NITSRoot.msgCreatedTime` cites "the ISO 8001 standard".** There is no ISO 8001 relevant here; ISO 8601 is meant, and the W3C note the same sentence references is the timezone note | `times.parse` accepts the value; the citation is noted and nothing turns on it |
| 11 | **`ImagingSensor.motionImageryCoreID` carries an acknowledged wrong namespace.** The standard says "the XML schema incorrectly defines the name space using `nga.gov` instead of `nga.mil`; the XML schema retains the use of `nga.gov` for backwards compatibility" | the wrong namespace is the conformant one and is used as-is. Recorded because it looks exactly like a bug to fix |

### Deliberately out of scope, and why

An unimplemented thing is a decision, so each one is named, and each says whether it is deferred
or rejected.

| Out | Deferred or rejected | Decision |
|---|---|---|
| **EXI encoding** | **deferred** | The second conformant encoding, and the one the Custodial Support Team recommends. It is a codec over the same infoset, so the row set for an EXI feed is this one unchanged; schema-informed EXI needs the XSD that cannot be pinned here; and EXI's documented namespace-prefix hazard breaks `xsi:type`, which is how this format expresses every abstract type. Deferred to a release that can pin the schema and test the decode, not rejected |
| **STANAG 4676 Edition 1 / AEDP-12 Edition A** | **deferred, as a separate adapter** | Different root, different time model, different security model, and the standard's own words: "re-architect the data model and XML-based syntax from scratch". A mode flag would put two parsers behind one name. A document reading `nitsVersion` `A.*` is refused with the value quoted |
| **Emitting a `DATASTREAM` document** | **rejected** | Egress writes one self-contained file. Emitting a stream profile means tracking what has already been sent, which is state |
| **Resolving a `DATASTREAM` reference** | **rejected** | It means caching objects across payloads and matching by identifiers whose scope may be unstatable. The AIS fragment buffer, the ADS-B frame pair, Legion's pagination and CAT021's cross-block correlation, refused a fifth time. Unresolved references are recorded, not followed |
| **Performing the consolidation rule of §2.1.1.2.3** | **rejected** | The standard normatively requires a *consumer* to merge every instance sharing an ID "across all in-scope data streams". That is a stateful reducer with an unbounded store, it destroys determinism and therefore golden-output testing, and it applies retractions where nothing audits them. The material to do it is carried in full; doing it is the consumer's |
| **Resolving `TrackLinkage`, `ProcessedTrack` or `MotionEvent` track references** | **rejected** | Association, merging and stitching are fusion. Carried verbatim; acting on them is a consumer decision |
| **Resolving the `Evidence` → `Detection` chain** | **rejected** | Same decision one level down, and the CDM has no relation to hold the result. **Gap 19** |
| **Interpreting Mode 4 or Mode 5 IFF as an affiliation** | **rejected** | An authenticated IFF reply is what "friend" means in IFF doctrine, and reading one is an identification decision belonging to an IFF authority. Over-claiming `FRIENDLY` is also the dangerous direction. The second format to force this and the second to decline it |
| **Composing a 2525D SIDC from an APP-6 code** | **rejected** | An APP-6 entity code supplies one of the eight things a SIDC encodes. Composing one means inventing six, and a wrong symbol is worse than none — the model's own `symbol` validator says so |
| **`ECI_J2K` → geodetic** | **deferred** | Needs Earth rotation angle at epoch, an IAU precession–nutation model and daily Earth-orientation parameters — a second standard plus a live external feed, in an adapter contracted to be a pure function of one payload. The standard puts these conversions outside its own scope. Deferred against a future release that is willing to carry an EOP dependency |
| **`LOCAL_SPHERICAL` → geodetic** | **deferred** | Blocked by ambiguity 1, not by effort: which slot holds the bearing is a producer convention the data does not record. A custodian's clarification, or a per-deployment ICD declaring its own convention, turns this into a five-line closed form — a document, not a design |
| **`PIXELS` → geodetic** | **rejected** | Needs a sensor model, exterior orientation and a terrain surface, none of which NITS carries — and the format concedes it by restricting `CoordinateFrameTransformation.from` to the two absolute Cartesian systems, so no mechanism exists |
| **Decoding the MIIS Core Identifier (MISB ST 1204.3)** | **deferred** | A separate standard with its own registry, in the same category as CAT021's BDS registers. Parked whole, which the never-drop rule already satisfies |
| **Decoding AIDPP-01 / STANAG 4162 IDCP encodings** | **deferred** | `sourceDeclarationExtension` and the `IDSourceNumber` triple are defined by another publication. Adopting it means becoming an ID fusion node, which is also a rejection on the merits |
| **Reading the STANAG 4607 GMTI data a `Radar4607` points into** | **rejected** | `revisitIndex`, `dwellIndex` and `reportIndex` are pointers into a different file in a different format. A GMTI reader is a different adapter |
| **Dereferencing `SensorInformation.url` or `ImageChip.uri`** | **rejected** | An adapter that fetches a URL out of its payload is a network client with a payload-controlled target, in a component that is supposed to have no network at all |
| **Transport: file servers, MIME multipart streams, sockets, APAN or DiWEB retrieval** | **rejected** | §2.1.1.2 puts transport outside the standard's scope and §2.5.1 makes one file one root object. Splitting a stream is the caller's job, by the standard's own instruction |
| **The XML syntax binding** | **blocked, not declined** | Element names, attribute-versus-element and the base64 UUID form all depend on the XSD, which is distributed through national representatives and cannot be pinned here. Phase 2 starts when it can be |

### The fixtures — planned here, before they exist

**Everything will be synthetic.** No recorded NITS traffic, no real collection, no real track.
Each fixture is a twin: a `.nits.xml` document and a `.parsed.json` holding the parsed form the
never-drop check measures against, the pattern `adsb.py` and `asterix_cat021.py` already use.

Identifiers follow the Legion rule, which is the only one available for a format built on UUIDs:
**RFC 9562 §5.8 version 8**, reserved for custom and experimental use, so a fixture identifier
cannot collide with a real one from a producer emitting v4 or v7, with a fixed prefix asserted by
a test. Local IDs are small integers under a version-8 `lidScopeUID`, which is exactly the
composite the identity settlement requires. `IDData.stationID` and `nationality` will use a
documented non-allocated trigraph rather than a real nation's — and unlike the CAT021 SAC, **no
allocation list is pinned for it**, so that claim will be the weakest in the set and will say so.

The eight cases the set has to catch, chosen because each is a decision above that a golden file
can pin: a minimal STANDALONE track; the same content as DATASTREAM with references pointing
outside the file; a `TrackData` whose three segments are contiguous in time, so the one-Track
rule and the per-segment index ranges are both exercised, and a second whose segments **overlap**,
which must be refused; a `TrackPoint`
carrying `Dynamics` in `WGS_84` **and** `LOCAL_CARTESIAN` with a complete ECEF CFT, so the
preference order and the disagreement check both run; a `LOCAL_SPHERICAL` block that must produce
no `Position`; a complex multi-ring `Polygon` with `NaN` delimiters exercising all three
corrections; a retraction-only `TrackSegment` that must become an `Event` and not a `Track`; and a
`relTimeIncrement` that is not a whole number of milliseconds, so the parking rule is what the
round trip depends on.

## GeoJSON (RFC 7946)

| GeoJSON | CDM field | Status | Notes |
|---|---|---|---|
| `Point` | `Event.geometry` | `models` | `[lon, lat]` order enforced in `geo.py` |
| `LineString` | `PlanObject.geometry` | `models` | routes |
| `Polygon` | `Event.geometry` | `models` | jamming footprints; ring closure enforced |
| `Feature.properties` | `PlanObject.style` | `models` | **gap 5** — Feature/FeatureCollection not modelled |
| `bbox` | — | `not yet` | not carried; derivable from geometry |

## Gaps, and what each one costs

1. **No canonical name.** A CoT callsign and a 4676 track number are the strings an operator
   reads, and today they land in `attributes`. Every consumer that wants to label a contact
   has to know which adapter's key to look under, which is exactly the kind of private
   knowledge the CDM exists to abolish. *Proposed: `Entity.label` in 1.1.0 (MINOR — optional
   field).* Deliberately not added on day one: it needs one owner naming its precedence rules
   across sources, not a field added in passing. **Now confirmed by a shipped adapter** — the
   TAK adapter parks every callsign at `attributes.callsign`, so the private knowledge this
   gap describes already exists in the field. **And now by a second one, which is the
   evidence that changes the argument**: the AIS adapter parks a vessel name at
   `attributes.vessel_name`, a call sign at `attributes.call_sign` and an aid name at
   `attributes.aid_name`. Two adapters, four keys, one concept — a consumer labelling a
   contact must now know which of four private names to look under, and every further
   adapter adds one. The precedence rules this gap waits on are exactly the question
   "vessel name or call sign?", so the second adapter sharpened the open question rather
   than merely re-reporting it. **The third adapter makes it worse in a new way rather than
   by adding a fifth key.** The ADS-B adapter parks an aircraft callsign at
   `attributes.callsign` — the key the TAK adapter already uses for a CoT callsign. Two
   adapters have independently converged on one private name, which reads to a consumer as a
   general rule and is not one: a CoT callsign is an operator-assigned label and an ADS-B
   callsign is a flight identifier the crew types, they follow different precedence rules
   against a vessel name, and nothing anywhere states that the key means the same thing in
   both. A private convention becoming a de-facto standard without an owner is a worse
   position than four keys that visibly disagree, because it removes the signal that a
   decision is missing. **And Legion settles the question of whether this gap is worth
   closing.** Its `name` field is `required` on every Entity and every Track, so every single
   object from that source arrives with an operator-facing string — not sometimes, as with a CoT
   callsign or an AIS vessel name, but always. A fifth adapter parking a sixth key would be
   noise; an adapter whose every object has a name and nowhere to put it is the argument.

   **CAT021 is the first source whose name field cannot be given a precedence rule at all,
   which is a different kind of evidence from a sixth key.** I021/170 Target Identification is
   defined as "target identification when flight plan is available **or the registration
   marking when no flight plan is available**" — one field, two concepts, and no bit anywhere in
   the record saying which one arrived. So the question this gap waits on ("vessel name or call
   sign?") cannot even be *asked* of this source until someone decides whether a registration
   marking is a name. It is also why that row set deliberately does NOT park under
   `attributes.callsign`: converging on the key TAK and ADS-B already share would assert the
   flight-plan reading about half the time, silently.
   **NITS is the sixth format and it adds no key, because it has no name to park.** Forty-eight
   classes deep, a full ISR track model with sensors, trackers, collections, products, detections
   and evidence — and nowhere in it is there a string an operator reads off a contact. The nearest
   thing is `TrackedObject.description`, defined as a field "to **describe** the tracked object in
   greater detail than is otherwise allowed by the other attributes", which is a description and
   not a label; the other candidates (`SensorInformation.name`, `TrackerInformation.name`,
   `ProductIdentification.name`, `CollectionInformation.targetID`, `IDData.stationID`) each name
   something that is not the contact. So the row set parks each under a key named for what it is
   and adds no fifth private name. **The evidence that changes for this gap is negative and it is
   still evidence**: whoever proposes `Entity.label` should know that a ratified NATO tracking
   standard declined to model one at all, which means the precedence rules this gap waits on
   cannot be sourced from the formats — they have to be a decision.
2. **Affiliation collapse, 7 → 4.** PENDING, ASSUMED_FRIEND and SUSPECT have no CDM member
   (see `enums.Affiliation` for why: they are judgements, not wire facts). Recoverable only
   because the adapter parks the original — which the lossless check enforces rather than
   trusts. The TAK adapter parks both the letter (`attributes.cot_affiliation_letter`) and the
   full type string, and a test asserts that SUSPECT becomes UNKNOWN and **not** HOSTILE:
   suspicion is not identification, and that is the direction the collapse must not round
   towards. AIS is the OTHER case and is worth keeping distinct from this one: it states no
   identity at all, so its entities are UNKNOWN because the format is silent and not because
   a wider vocabulary was collapsed. Nothing is parked because nothing was said, and
   `attributes.affiliation_basis` records which of the two situations produced the UNKNOWN.
   **Legion widens this to 15 → 4 and adds a second axis.** Its enum carries the full 2525
   standard identity — PENDING, ASSUMED_FRIEND, SUSPECT, JOKER, FAKER, NONE_SPECIFIED — and
   five `EXERCISE_*` variants on top, so it is both the widest collapse in this document and
   the first source to fold *exercise context* into the identity field. The CDM already
   separates those two ideas, which is why this one is a collapse in one axis and a SPLIT in the
   other: the exercise marking belongs with the 2525D context digit and with
   `SourceRef.synthetic`, not with the affiliation. Note what that split must not do — a payload
   field may not rewrite `source.synthetic`, which is a deployment declaration about the feed
   rather than a fact about one contact. Whoever revisits this gap should read the Legion
   affiliation table before proposing anything: a wider `Affiliation` enum would close the
   collapse and leave the conflation.

   **CAT021 widens it in a third direction, and this one is not about vocabulary size.** Through
   the Reserved Expansion Field's `MES` subfield it carries *authenticated* Mode 5 IFF
   indications — `ID` and `DA`, "authenticated Mode 5 ID reply/report" and "authenticated Mode 5
   Data reply or Report". That is the first cryptographically attested identity statement any
   source in this document carries, and the adapter still emits `UNKNOWN`, because turning an
   attestation into FRIENDLY is an adjudication and over-claiming FRIENDLY from a translator is
   the fratricide-adjacent direction. The consequence for this gap is that the CDM has no way to
   record **"an identity was attested and has not been adjudicated"** — which is neither UNKNOWN
   (that understates what arrived) nor FRIENDLY (that overstates what was decided). Whoever
   revisits this gap should decide whether an attestation belongs beside `affiliation` rather
   than inside it; a wider enum would not touch this case.
   **NITS is the source this gap was originally written about, and Edition B corrects its
   arithmetic.** The gap says 7 → 4. `ID1241.identity` in Edition B carries **six** STANAG 1241
   Edition 5 literals — `UNKNOWN`, `ASSUMED_FRIEND`, `FRIEND`, `NEUTRAL`, `SUSPECT`, `HOSTILE` —
   and `PENDING` is not among them, so the collapse here is 6 → 4 and the two members lost are
   `ASSUMED_FRIEND` and `SUSPECT`, two of the three this gap names.

   **What NITS adds is the exercise-context conflation Legion exposed, arriving in a second field
   and inverting rather than merely colouring the identity.** `ID1241.identityAmplification`
   carries `FAKER` and `JOKER`, defined as a *friendly* track "acting as exercise hostile" and
   "acting as exercise suspect", so an exercise `FAKER` arrives as `identity = HOSTILE` with an
   amplification saying it is really a friend. The row set maps **`FRIENDLY`** and parks the role
   at `attributes.exercise_role`, because the standard states the identity in the definition's
   first word — reading it is translation, not adjudication.

   The consequence for this gap is that **the CDM can carry the identity and cannot carry the
   role**, so a `FAKER` and an ordinary friendly are the same `affiliation` and differ only in a
   parked key. That is Legion's finding restated with the axes separated correctly: Legion folded
   exercise context *into* the identity enum, the CDM already splits the two, and NITS shows that
   the split is right and that the second axis still has nowhere canonical to live. `KILO` is
   mapped on the same evidence and sets no role.

   **`TRAVELER` and `ZOMBIE` are this gap's concrete evidence, and the check was run rather than
   assumed.** Amendment C's logic is symmetric — an amplification whose definition states an
   identity is read — so the question is whether the CDM has a member that honestly carries the
   one they state. It does not: `enums.Affiliation` has exactly four members and its docstring
   names `SUSPECT` as deliberately absent, "a judgement a fusion layer makes, not a fact an
   adapter can read off a wire format". So `TRAVELER` ("a **suspect** surface track following a
   recognized surface traffic route") and `ZOMBIE` ("a **suspect** track, object or entity of
   special interest") set no affiliation, the stated `identity` governs, and both literals are
   parked. That is not the discard amendment C forbids — it is this gap, named at the point it
   costs something, and `test_the_two_suspect_amplifications_never_yield_friendly` fails if
   `Affiliation` ever grows the member that would close it.

   One case is not merely lossy but contradictory, and it is handled rather than left: a
   `ZOMBIE` amplification on a `FRIEND` identity. The producer has said the track is suspect and
   the CDM can express neither the suspicion nor the disagreement, so the affiliation is
   `UNKNOWN` with both fields parked. Presenting a suspect as `FRIENDLY` is an over-claim in
   exactly the direction `symbology`'s own table refuses when it says "suspect — not HOSTILE;
   suspicion is not identification".

   **And a divergence this gap now has to carry.** `symbology.AFFILIATION_FROM_COT` maps CoT's
   `j` and `k` to `HOSTILE` and `legion.AFFILIATION` maps `JOKER` and `FAKER` to `HOSTILE`, while
   `adapters/stanag4676.py` maps the same two words to `FRIENDLY`. The definitions agree across
   all three standards — a friendly acting as an exercise hostile — so this is one concept with
   two answers in one codebase. It is **stated rather than resolved**, on the I021/170 precedent:
   those are published behaviours with shipped adapters, fixtures and golden files behind them,
   and changing one is a 1.1.0 question with a migration note. The argument for the NITS
   direction is that the CDM models exercise context separately (`SourceRef.synthetic`, the 2525D
   context digit), so painting a friendly as `HOSTILE` loses the identity to encode a context the
   model already has a place for; the argument against is that an exercise in which the FAKER
   renders as friendly is an exercise that has stopped working. Whoever settles this gap settles
   that too, and `test_this_adapter_diverges_from_two_shipped_ones_and_the_divergence_is_
   deliberate` pins all three mappings so it cannot be settled by accident.
3. **Track quality scale.** 4676 integer 0–15 → CDM float 0–1 is `value / 15`, a declared
   transform. Note that 4676 quality 0 means "worst", not "unknown", and CDM `None` means
   unknown — so a missing 4676 quality must become `None`, never `0.0`.
   **No row in the STANAG 4676 row set evidences this gap, and that is the honest statement of
   its position.** It was written against `Track/trackQuality`, an **Edition A** attribute;
   Edition B removed it in the re-architecture and put nothing track-level in its place, so
   `Track.track_quality` is `None` on every NITS track and there is no scale to convert. The
   nearest Edition B row is `TrackSegment.confidence`, which parks — it governs a portion of a
   track rather than the track, and it is a `Confidence` rather than a number, which is
   **gap 18**'s problem and not this one. The gap is left standing rather than deleted because
   "closed by the format changing underneath it" is a different fact from "wrong", and an adapter
   meeting an Edition A feed would still need it; it is deliberately **not** re-anchored to an
   Edition A name, which the guard test forbids and which would misrepresent the current row set.
4. **Velocity representation.** 4676 carries a 3-vector; the CDM carries speed/course/climb.
   The conversion is exact arithmetic and reversible, so it is a declared transform rather
   than a gap in meaning — but an adapter must declare it or the lossless check will (correctly)
   flag every velocity component. **Legion carries one too, and shows that the transform is only
   exact when the FRAME is known.** Its `velocity`, `acceleration` and `angular_velocity` are
   3-vectors whose reference frame is documented nowhere — geocentric ECEF and local
   east-north-up give completely different answers for the same three numbers, and its position
   field defaults to ECEF while its `bearing` is plainly a local compass bearing, so neither
   guess is safe. So the declared transform this gap describes needs a stated frame as its
   precondition, exactly as gap 7's heading needs a stated datum and gap 9's altitude needs a
   stated reference surface. The pattern is now three deep: a vector or an angle without its
   frame is not a measurement.
   **NITS answers this gap in part, and the rows that evidence it are `Dynamics.vel` and
   `Dynamics.acc`.** The precondition the Legion entry identified — a stated frame — is met in
   full: `Dynamics.cs` names one of six coordinate systems and Table 2.5.27-2 gives the units of
   the velocity vector for every one of them. So the declared transform is performed rather than
   deferred for `ECEF`, for CFT-resolved `LOCAL_CARTESIAN`, and for `WGS_84` **when its optional
   height axis is present** — with the ellipsoid constants named and the raw vector re-emitted
   beside the scalars.

   Three things worth carrying forward. First, **a stated frame is not the same as an easy one**:
   the `WGS_84` velocity is in *degrees per second* for latitude and longitude and metres per
   second for elevation, so the conversion needs the meridional and prime-vertical radii of
   curvature and is latitude-dependent — a mixed-unit vector that reads like a plain one. Second,
   **a stated frame is not the same as stated inputs**: a two-dimensional `WGS_84` block gives no
   ellipsoid height, `h = 0` would be a fabricated input to that same conversion, and the row
   parks rather than converting. That is a *fourth* precondition this gap now carries, beside a
   frame, a datum and a reference surface — **the conversion's own arguments have to be stated,
   not just its coordinate system.** Third, the transform is still refused entirely for
   `LOCAL_SPHERICAL`, `ECI_J2K` and `PIXELS`. `Dynamics.acc` parks in every case, because the CDM
   models no acceleration at all — which is the half of this gap no format has yet touched.
5. **Feature / FeatureCollection.** Not modelled. `PlanObject` is the CDM's Feature-equivalent
   (geometry + style + label), and a FeatureCollection is a list of PlanObjects. Adding the
   GeoJSON wrappers would give two ways to say one thing.
6. **Vertical accuracy.** CoT `@le` has no canonical home; `Position.accuracy_m` is horizontal
   only. *Proposed: `Position.alt_accuracy_m` in 1.1.0 (MINOR).* Matters for air tracks, where
   a 300 m vertical error decides whether two aircraft are deconflicted. **Now confirmed by a
   shipped adapter**: `air_track_due_north.xml` carries `le="120.0"` on a track at 7 620 m, and
   that 120 m sits in `attributes` where no consumer will look for it.

   **Legion shows the gap is wider than one missing field: the CDM's whole uncertainty model is
   one scalar.** It sends a 3×3 position `covariance` matrix (example diagonal 25, 25, 9 m², so
   σ = 5, 5, 3 m) and, separately, a `radius`. `Position` has `accuracy_m` — one horizontal
   1-sigma number — so a matrix has to be either collapsed or parked, and collapsing it needs
   the frame the matrix is expressed in, which Legion does not state (gap 4's problem again).
   Parking is therefore the only honest option today. This is recorded here rather than as a new
   number because it is the same concept as `alt_accuracy_m`: how precisely do we know where this
   is. Whoever closes gap 6 should decide whether the answer is two scalars or a small covariance
   block, and should not discover the question from a fourth adapter.

   **CAT021 supplies the fourth adapter's answer and it is a third shape.** Its `GVA` is a
   two-bit *Geometric Altitude Accuracy* category — precisely the vertical accuracy this gap
   wants, still not a metre figure — and its `PIC` is an integrity **containment bound** stated
   in nautical miles, from "< 0.004 NM" to "> 20.0 NM". PIC is the sharpest case in the whole
   document because the specification finally hands over a number with a unit on it, **and it is
   still the wrong kind of number**: a containment bound is a radius inside which the truth lies
   with a stated integrity, not a 1-sigma error. So the shape question is now three-way — two
   scalars, a covariance block, or a *bound plus an integrity level*, which is what aviation
   actually publishes and what a downstream deconfliction check would want to read.
   **NITS states vertical accuracy properly and the CDM still cannot hold it, which sharpens the
   gap rather than closing it.** A `CovarianceMatrix` typed `POS3D` carries `covZZ` explicitly —
   a vertical variance, stated, in the coordinate system's own units — and the `Ellipsoid` class
   exists to express a full 3-D error region. So this is the first source where "what is the
   vertical accuracy?" has an unambiguous answer, and `Position.accuracy_m` is still one
   horizontal scalar with nowhere to put it. Note what that implies for the proposal: a
   `Position.alt_accuracy_m` beside `accuracy_m` would hold NITS's `covZZ`, and would still throw
   away the off-diagonal terms that say the horizontal and vertical errors are correlated. That is
   **gap 17**, and the two should be designed together or the CDM acquires a vertical accuracy
   that quietly contradicts the matrix it came from.
7. **Heading and rate of turn.** `Kinematics` carries `course_deg` and nothing else angular, so
   AIS's true heading and rate of turn both land in `attributes`. Course and heading are
   different measurements and the difference is the interesting one: a vessel making 12 knots
   over the ground on course 095 while its bow points 070 is being set 25 degrees by wind or
   current — or is not going where it is pointing on purpose. Collapsing the two, or picking
   one, loses exactly the discrepancy an analyst reads. Rate of turn belongs with it because
   they answer one question between them, "where will this be next", and because a gap opened
   twice for one concept gets closed twice differently. *Proposed: `Kinematics.heading_deg`
   and `Kinematics.turn_rate_dpm` together in 1.1.0 (MINOR — two optional fields, one owner).*
   Note both sentinels for whoever implements it: heading 511 and rate of turn −128 mean not
   available, and ±127 means "faster than 5° per 30 s", which is a floor and not a rate — so a
   `turn_rate_dpm` of 127 would be a fabricated measurement.

   **ADS-B strengthens the case and adds a requirement to it.** A type 19 subtype 3/4 frame
   states a heading, so a third adapter now parks one — but an ADS-B heading is referenced to
   MAGNETIC north unless a type 31 frame's HRD bit says otherwise, while an AIS true heading
   is referenced to true north. A bare `Kinematics.heading_deg` would therefore hold two
   different measurements under one name, and the error is not small: magnetic variation in
   the Baltic is around 8 degrees east and it is a function of place and date, so the
   discrepancy this field exists to expose — bow against track — would be swamped by an
   unstated datum. So the proposal grows a third element: `heading_deg` needs a stated
   reference datum beside it, and ADS-B cannot supply that datum from the same frame as the
   heading (HRD is in type 31, the heading in type 19). Whoever closes this gap inherits that
   cross-frame join as part of the problem, which is exactly the kind of thing a gap is for
   discovering before a field is added in passing.

   **Legion is the fourth source to park an orientation and the second to park a turn rate, and
   it raises the ceiling on both.** Its `orientation` is a unit **quaternion** — an attitude in
   three axes, of which a heading is one component — and its `angular_velocity` is a 3-vector
   turn rate. Neither the quaternion's component order nor either vector's frame is documented,
   so this adapter cannot even interpret what it parks. Two lessons for whoever closes this gap:
   a scalar `heading_deg` is the right shape for the sources seen so far but it is strictly less
   than what a platform actually broadcasts, and every one of these fields is uninterpretable
   without a stated frame or datum.

   **CAT021 answers the datum requirement rather than restating it, and it is the first source
   that can.** It carries a magnetic heading (I021/152) and a true-north heading (REF `TNH`) as
   two **separate data items**, and REF `SGV`'s `HRD` bit states the datum for a surface heading
   or ground track in the same item that carries it. So the cross-frame join ADS-B inflicted on
   this gap — heading in one frame, datum in another — is not inherent to the concept; one real
   source states both together. A `heading_deg` beside a stated reference datum is therefore
   demonstrably encodable, which moves this gap from "needs a design" to "needs a decision".

   It also adds a **unit collision on the turn-rate half** that the proposal has to settle rather
   than inherit: AIS states degrees per minute, the proposal is named `turn_rate_dpm`, and
   CAT021's I021/165 Track Angle Rate is degrees per **second** at LSB 1/32, with 16 °/s meaning
   "16 °/s or above" — a floor and not a rate, exactly as AIS's ±127 is. And it parks a third
   angular quantity beside the other two: I021/230 Roll Angle, which is one component of the
   attitude Legion sent as a quaternion.
   **NITS carries no heading and no turn rate at all, and what it does instead is worth
   recording.** There is no orientation attribute anywhere in the model — not on `TrackedObject`,
   not on `Dynamics`, not on `TrackPoint`. A course is derivable from the velocity vector, and a
   course is not a heading. What the format has instead is **qualitative**: `MotionEventType`
   carries `LEFT_TURN`, `RIGHT_TURN`, `LEFT_U-TURN` and `RIGHT_U-TURN` as *event types*, so a turn
   is something that happened rather than a rate that was measured. That is a fourth shape for
   this gap's subject — AIS states a rate, ADS-B and CAT021 state an angle with a datum, Legion
   states a quaternion, and NITS states an event — and it argues that whatever closes this gap
   should not assume the answer is a number on `Kinematics`. A turn that is only ever reported as
   an event has no home on that model either.
8. **Extent.** An entity has a position and no size. AIS states four dimensions from the
   position reference point — to bow, stern, port and starboard — from which length and beam
   follow, and a type 5 message adds draught. All of it is parked. It matters more than it
   sounds: a 330 m tanker and a 12 m patrol craft render as the same dot, the reference point
   is offset from the hull by up to a ship length so a "position" is only accurate to within
   the vessel's own size, and draught against charted depth is what decides whether a strait
   is passable at all. *Not yet proposed as a field* — unlike gaps 1, 6 and 7, the shape is not
   obvious: a bounding extent, an offset reference point and a draught are three different
   ideas, and STANAG 4676's own object-size fields should be read before any of them is added.
   Recorded here so the next adapter author finds a decision rather than an oversight.
   **Legion adds a case that cannot be filed on either side of it.** Its location `radius` is a
   bare number with an example of `500` and no description, and it is genuinely ambiguous between
   an uncertainty radius (gap 6) and a geometric extent (this gap) — a 500 m *error* and a 500 m
   *object* are different statements about the world and the spec does not say which it means. It
   is parked under both readings' names until a source resolves it, which is the honest handling
   and also the reason this gap should not be closed by guessing a shape.

   **CAT021 states an extent, and its shape is the argument against a scalar.** I021/271's first
   extension carries length and width as a **four-bit bucket index** into the specification's own
   table — 2 means "L < 25 m and W < 28.5 m", 15 means "L > 85 m or W > 80 m". A bucket is a
   range, so an extent field holding a single number would have to pick a midpoint and state a
   size nobody measured; the parked form keeps the code and the bucket's bounds. It also settles
   the second of this gap's three ideas: REF `GAO` states the **GPS antenna offset** in metres,
   lateral and longitudinal, and I021/271's `POA` bit says whether the transmitted position *is*
   the ADS-B position reference point. That is the offset-reference-point problem — the one that
   makes a "position" accurate only to within the vessel's or airframe's own size — stated
   numerically by a source for the first time rather than inferred.
   **NITS is the strongest evidence this gap will get, and it comes in three independent
   shapes.** `TrackedObject.dims` states `[length, width, height]` **with a 6-element covariance
   on them**, so the format gives not only an extent but an uncertainty on the extent.
   `TrackPoint.outline` states a full `Shape` — a polygon or an ellipsoid — **at every instant of
   the history**, plus `outlineObscured` for the part of it hidden, so the extent is
   time-varying and partially occluded. And `Detection.outline` states the same thing for the raw
   sensed region, `[0..*]` so it can be given in several coordinate systems at once. Against that,
   the CDM's `Entity` has a `Position` and **no geometry field of any kind** — only `Event` and
   `PlanObject` have one — so every outline in the format is parked, including the ones whose
   coordinate system would let them be a perfectly good GeoJSON polygon. A dimension triple on
   `Entity` would hold the first shape and none of the other two.
9. **No barometric altitude.** `Position.alt_m` is documented as metres HAE — a height above
   the WGS84 ellipsoid — and that is what an ADS-B type code 20-22 frame states, subject to the
   datum caveat below. The type code
   9-18 frames, which are the overwhelming majority of an air picture, state a *pressure*
   altitude referenced to 1013.25 hPa instead. The two differ by hundreds of metres in ordinary
   weather and by more in a deep low, so writing one into the other's field is the same class
   of false statement as writing AIS's ten-metre accuracy threshold into `accuracy_m`. Today
   every barometric altitude lands at `attributes.baro_altitude_ft`, which means the CDM
   carries no altitude at all for most air tracks. It matters for the same reason gap 6 does
   and more sharply: deconfliction, airspace-boundary checks and any comparison against terrain
   all read an altitude, and two aircraft that are level with each other on the altimeter are
   not necessarily level in space. *Proposed: `Position.baro_alt_m` in 1.1.0 (MINOR — one
   optional field), beside `alt_m` rather than instead of it, because the whole finding is that
   they are two measurements.* Note for whoever implements it that ADS-B carries the bridge
   between them: the type 19 GNSS-barometric difference field, parked today at
   `attributes.gnss_baro_difference_ft`, is exactly the offset relating the two, and it should
   be considered in the same change rather than in a fourth one.

   **A second problem with the same field, recorded here rather than as a gap of its own,
   because it is a consequence of a decision that is right.** `Position` requires a latitude and
   a longitude — that is how the null-never-zero rule is made structural, and it should stay
   that way — so an altitude with no horizontal fix has no canonical home at all. ADS-B produces
   that case constantly: a position frame whose CPR cannot be resolved still states a perfectly
   good altitude, and a Mode C reply states an altitude and no position whatsoever, so the next
   radar adapter meets this immediately. The ADS-B adapter parks the figure at
   `attributes.gnss_altitude_m` / `attributes.baro_altitude_ft` on every position frame, which
   is why nothing is lost; the byte-exact round trip is what found that an earlier version put
   the GNSS figure only inside `Position` and dropped it whenever there was no position to hold
   it. Whoever closes gap 9 should decide deliberately whether the new field hangs off
   `Position` — inheriting the requirement of a coordinate — or off `Entity`, and NOT discover
   the question afterwards. Adding it to `Position` alone would leave this hole open.

   **And a third problem, which is gap 7's problem wearing different clothes: the datum is
   asserted, not carried.** `alt_m` means height above the ellipsoid, and a type code 20-22
   frame does not say which surface its height is measured from. A **DO-260 version 0**
   transmitter broadcasts GNSS height against **mean sea level**; DO-260A and DO-260B broadcast
   it against the **ellipsoid** (per FAA/Airbus altimetry-system-error monitoring material). The
   difference is the geoid separation — tens of metres over the Baltic and over 100 m in places
   — so it is not a rounding matter. The version number that decides which reading applies is in
   a **type code 31 operational-status frame**, not in the position frame, so a single frame
   cannot state its own datum: exactly the shape of gap 7, where an ADS-B heading is magnetic and
   an AIS one is true and neither frame says so. This adapter therefore ASSERTS the DO-260A/B
   reading and names both possibilities in `attributes.altitude_type` rather than silently
   picking one. Whoever closes gap 9 inherits the same requirement gap 7 grew: an altitude field
   needs a stated datum beside it, and a cross-frame join to establish it.

   **CAT021 closes the datum half outright and sharpens the unit half.** Its I021/140 Geometric
   Height is defined in the item itself as the "minimum height from a plane tangent to the
   earth's ellipsoid, defined by WGS-84" — so the reference surface is *stated in the same item
   as the measurement*, and it reaches `alt_m` as a mapping rather than as an assertion. The
   DO-260 version-0 mean-sea-level ambiguity that made the ADS-B row an assertion does not arise:
   the ground station resolved it before emitting.

   The unit half gets worse before it gets better, and whoever closes this gap has to decide it.
   ADS-B parks a pressure altitude at `attributes.baro_altitude_ft`; CAT021 states one as a
   **Flight Level** at LSB ¼ FL and parks it at `attributes.flight_level`. The two are the same
   concept in two units under two keys, and the CAT021 row set deliberately declines to converge
   on the ADS-B key for gap 1's reason — a private convention becoming a de-facto standard
   without an owner removes the signal that a decision is missing. A `Position.baro_alt_m` would
   have to name its unit, and both adapters would have to convert into it.

   And the bridge between the two altitudes now has a second span. ADS-B carries the
   GNSS-barometric difference; CAT021's REF `BPS` carries the **barometric pressure setting**
   itself, as the aircraft's selected value minus 800 hPa at LSB 0.1 hPa. Between them they are
   what relates a flight level to a height above the ellipsoid, and both should be considered in
   the same change rather than in a fifth one.
   **NITS closes the datum half of this gap by never having it open.** There is no barometric
   altitude in the model, and every height it does state names its reference surface: `WGS_84`
   position is "ellipsoid height [meters]", which is exactly what `Position.alt_m` documents, and
   `ECEF`/`ECI_J2K`/`LOCAL_CARTESIAN` are geometric by construction. So the sixth format maps its
   altitude with no ambiguity at all — which is the useful data point for this gap, because it
   shows the problem is not "altitude is hard" but "some formats state a number without its
   surface". The proposal should therefore be about **a reference surface being mandatory**, not
   about adding a second altitude field.
10. **No air-data speeds.** `Kinematics.speed_mps` is a speed over the ground: it is what AIS's
   SOG means, what a CoT track speed means, and what an ADS-B type 19 subtype 1/2 frame states.
   Subtypes 3 and 4 state an indicated or true AIRSPEED instead, which is a different
   measurement — and the difference between airspeed and ground speed is the wind, which is
   the fact worth having. Parked today at `attributes.airspeed_kt` with its IAS/TAS flag, and
   `speed_mps` is left null on those frames rather than being filled with a number that would
   read as a ground speed to every consumer. *Not yet proposed as a field*, for gap 8's reason:
   indicated airspeed, true airspeed and Mach are three related-but-distinct quantities, a
   consumer that wants wind needs a heading (gap 7) and a datum as well, and adding one
   `airspeed_mps` now would be closing a third of a question. Recorded so the next adapter
   author finds a decision rather than an oversight.

   **CAT021 is the evidence that "a third of a question" was the right count.** It carries the
   three quantities as they actually are: I021/150 Air Speed holds **either** an indicated
   airspeed (LSB 2⁻¹⁴ NM/s) **or** a Mach number (LSB 0.001), selected by its own `IM` bit, and
   I021/151 True Air Speed is a **separate data item** at LSB 1 kt with its own range-exceeded
   floor. So one record can state an indicated airspeed and a true airspeed at once, and a field
   named `airspeed_mps` would have to drop one of them. Add the true-north heading this format
   also carries (gap 7) and the ground vector's track angle, and wind becomes computable from a
   single record — the first time that has been true of any source here, and the reason this gap
   is worth closing properly rather than a third at a time.
   **NITS states no air-data speed of any kind**, and the silence is consistent rather than
   incidental: its velocities are state-vector velocities in a declared frame, which is a velocity
   over the ground or an inertial one, never through the air. Sixth format, no new evidence, and
   that is itself the finding — air data has shown up only in the two aviation-surveillance
   formats, which is an argument for keeping it out of `Kinematics` and closer to the sources that
   have it.
11. **No entity hierarchy.** A CDM object has no parent. Legion's `parent_id` is `required` and
   nullable on every Entity and Track — so the source asserts, on every single object, either a
   parent or explicitly none — and the relationships it carries are the ordinary ones in a
   sensor estate: a camera on a mast, a radio on a vehicle, a payload on a UXV. Today the id is
   parked, which means a consumer can see that a parent exists and cannot traverse to it without
   private knowledge of this adapter's key. It matters for more than tidiness: a camera's
   position is its mast's position, so a hierarchy is how a fused picture avoids painting six
   contacts where one installation stands, and destroying a parent destroys its children in a
   way no consumer of a flat list can infer. *Not yet proposed as a field*, for two reasons worth
   stating. A `parent_id` on `Entity` would be a uuid pointing at an object that may not be in
   the same payload — the CDM has no reference-resolution story, and adding a dangling pointer is
   how a model acquires one by accident. And resolving the hierarchy is a per-level request,
   which is fusion by this document's own test. The right shape may be a containment relation
   held by the fusion layer rather than a field on the object, and that decision needs an owner.
   **NITS has no parent pointer either, and it has something that shows why a parent pointer
   would not be the answer.** `TrackData.object` is `[0..*]`, and where several `TrackedObject`s
   are present the standard says the track applies "to the set of multiple objects **as a
   group**"; `TrackedObject.numberOfObjects` states how many objects one track covers when they
   are indistinguishable. That is group membership without a hierarchy — a many-to-one that is not
   a parent — and a `parent_id` would not express it. What would express it, and what would also
   express the six reference kinds this format uses, is a relation.

   **One design question, three gap numbers.** Gaps **11**, **14** and **19** are the same missing
   thing seen from three sides — containment, provenance and reference — and they are on the
   1.1.0 roadmap **as a single item, to be resolved together under whichever number survives**.
   Closing this one alone would give the CDM a parent pointer it cannot resolve while leaving the
   other two open, which is how a model acquires three kinds of dangling pointer instead of one
   relation. Gap numbers are append-only, so the two that are subsumed stay in the list and say
   which number carried the decision.
12. **No classification label.** Legion states `top_classification` (example `"HUMAN"`) with a
   `top_classification_probability` (example `0.95`), and its Event resource has an `event_type`
   enum — `HUMAN`, `VEHICLE`, `VESSEL`, `UAV`, `FOOTSTEP`, `ANIMAL`, `GUNSHOT` — that is the same
   idea again. The probability has a canonical home in `Entity.confidence`; **the label does
   not**. This is deliberately NOT gap 1: a name identifies an individual and a classification
   says what kind of thing it is, they have different precedence rules across sources, and
   collapsing them would make `Entity.label` hold `"Axis IP Camera"` for one source and
   `"HUMAN"` for another. It is also not `entity_type`, which is a closed CDM vocabulary about
   what the object IS to the model rather than a sensor's verdict about what it looks like. So a
   classifier's output currently arrives as a confidence with no subject — the number 0.95 with
   nothing to say what is 95 % likely — which is the worst of the options. *Proposed for 1.1.0
   only once gap 1 is settled*, because the two must be designed together or the CDM ends up with
   two nearly-identical string fields and no rule for choosing between them.
   **NITS raises this from a vendor field to a NATO requirement, and it is the gap's strongest
   evidence by a distance.** Edition B's *model* is silent — §2.1.1.6 says so outright — but its
   *syntax* is not: Annex B.2, and AEDP-12.1 §D.3 and §E.2 under **AEDP-12 Requirement** callouts,
   state that the root object **must** contain an `originatorConfidentialityLabel` element, with
   `alternativeConfidentialityLabel` and `metadataConfidentialityLabel` optional, all four defined
   by STANAG 4774 / ADatP-4774 in namespace
   `urn:nato:stanag:4774:confidentialitymetadatalabel:1:0`, with binding guidance in TN-1491
   Edition 2. Portion marking is supported by attaching the same elements to any element that
   needs one.

   Three things follow for whoever closes this gap. **A classification is not a string**: a 4774
   label is a `PolicyIdentifier`, a `Classification` and any number of `Category` elements typed
   `RESTRICTIVE`, `PERMISSIVE` or `INFORMATIVE`, and the restrictive ones are the caveats — a
   field holding `"SECRET"` would look complete and have lost the compartment. **It is per-object,
   not per-feed**: portion marking means one document can carry several, so a single label on a
   `SourceRef` would be wrong. And **the egress direction is where the gap bites hardest**: the
   row set has exactly three paths and the third is a refusal: a round-tripped object re-emits its
   parked label, a CDM-native object may egress under an explicitly configured and logged
   deployment label, and an object with neither is refused — because there is no safe value to
   invent, `UNCLASSIFIED` being the dangerous direction and a copied label a marking its
   originator never applied. **A CDM that cannot carry a label cannot round-trip through this
   format without the deployment supplying one out of band**, which is the cost of this gap stated
   as an operational fact rather than as a modelling preference.
13. **No per-measurement time.** An `Event` carries one `observed_at`, and `Position` and
   `Kinematics` carry none — so every figure in one object is implicitly of one instant. CAT021
   says otherwise, twice over. A single record carries **I021/071**, the time of applicability of
   the *position*, and **I021/072**, the time of applicability of the *velocity*, and they are
   different instants; the adapter follows the position because the fix is the thing on the map,
   and the velocity's own time is parked where no consumer will look for it. Then **I021/295 Data
   Ages** states, in twenty-three separate subfields at LSB 0.1 s, how old each individual item
   is: the geometric height, the ground vector, the target identification, the target status, the
   roll angle and eighteen more, each to a maximum of 25.5 s that means "or above".

   It matters more than tidiness. An altitude twenty-five seconds older than the position beside
   it is, for an aircraft climbing at 2 000 ft/min, roughly 800 feet wrong — and a deconfliction
   check reading `Position.alt_m` has no way to learn that. The CDM's answer today is that the
   whole object is stamped with the position's instant, which is the most accurate single answer
   available and is still a claim the source did not make about most of the fields.

   *Not yet proposed as a field*, and the shape is genuinely open: a time on `Position` and on
   `Kinematics` would cover the two applicability items and none of the twenty-three ages, while
   an ages map in `attributes` is exactly the private key this document keeps arguing against.
   Whoever closes it should read `airtasking`'s staleness discipline first — a per-field age is a
   freshness statement measured against an `as_of`, which is a problem already solved once in
   this project rather than a new one.
   **NITS states two mandatory times on one identity declaration, which is a shape CAT021 did not
   have.** `IDSourceInformation.relTimeCreation` and `relTimeExchange` are both `[1]` — when the
   declaration was made and when it was transmitted — on a class that hangs off a `TrackedObject`,
   which has no time of its own at all. `SensorInformation` adds `absTimeUncertainty` and
   `relTimeUncertainty`, so the format states not only per-measurement times but the *uncertainty*
   on them. And a `Detection` carries its own `relTime` distinct from the `TrackPoint` whose
   evidence it is, so the sensing instant and the estimated-state instant are two stated,
   different numbers.

   What NITS also shows is that this gap can be **manufactured by an adapter** rather than only
   inherited: the row set takes `Entity.position` and `Entity.kinematics` from the same
   `TrackPoint`, deliberately, because taking them from different points would put two instants
   into one object with nothing recording the offset — CAT021's defect, created by us instead of
   received. Whoever closes this gap should note that the discipline of *not* creating it is
   currently a paragraph in a document rather than anything the models enforce.
14. **No producing sensor.** `SourceRef` records the adapter, its version, the system and whether
   the data is synthetic — and not **which sensor of that system** produced the object. CAT021 is
   the first source to state it in every single record: I021/010 Data Source Identification
   (SAC/SIC) is mandatory and names the ADS-B ground station, and I021/400 Receiver ID names the
   receiver within a distributed ground system. Both are parked at `attributes.data_source`.

   It is not bookkeeping. A multi-station ADS-B ground network reports one aircraft from several
   stations, and which station saw it is what a fused picture needs in order to reason about
   coverage, about a station that has gone quiet, and about a position only one receiver agrees
   with. Parked, a consumer can read it only by knowing this adapter's private key — gap 1's
   problem, one layer up.

   *Not yet proposed as a field*, deliberately: a sensor is arguably an `Entity` of type `SENSOR`,
   and relating an observation to the sensor that made it needs a relation the CDM does not have.
   That is the same missing machinery as gap 11's hierarchy, and the two should be designed
   together or the CDM acquires two different kinds of dangling pointer.
   **NITS models the producing sensor as a first-class object, with its own identity, and that
   makes this gap unarguable.** `SensorInformation` and `TrackerInformation` are top-level classes
   on `NITSRoot`, each with a `uid`, a name, a version and — through `IDData` — a `stationID` and
   a `NationalityTrigraph` that together "provide unique identification of any given STANAG 4676
   capable system". `TrackSource` exists solely to point at them, with eight reference lists
   (`sensorUID`, `sensorLID`, `trackerUID`, `trackerLID`, `collectionUID`, `collectionLID`,
   `productUID`, `productLID`), and it appears both on a track and, overriding it, on a segment —
   so the format expresses "these ten points came from that sensor and those ten from this one".
   `DynamicSourceInformation.sensorLocation` states **where the sensor was** at the moment of
   collection.

   So this is not one field with nowhere to go: it is an entire sub-model of provenance, reduced
   to parked identifiers because `SourceRef` names the adapter and the system and nothing else.
   Note that the gap's own note — that a sensor is arguably an `Entity` of type `SENSOR` and that
   relating an observation to it needs a relation the CDM lacks — is exactly right here, and the
   relation it needs is **gap 19**.

   **One design question, three gap numbers.** Gaps **11**, **14** and **19** are the same missing
   thing seen from three sides — containment, provenance and reference — and they are on the
   1.1.0 roadmap **as a single item, to be resolved together under whichever number survives**. A
   `SourceRef.sensor` field added on its own would answer this gap and leave the evidence chain
   and the group membership unanswerable, and would do it with a pointer nothing can resolve.
15. **No intent.** The four canonical objects are what exists, what happened, where something has
   been, and what we push out. **What a target declares it is going to do is none of them** — and
   `PlanObject` is emphatically not it: that models *our* plan, drawn on somebody else's map.

   ADS-B met this and deferred it, declining type code 29 with the words "it states an *intent*,
   which the CDM has no object for — a selected altitude is not a position". CAT021 does not allow
   the deferral, because intent arrives as ordinary in-scope data items that must be mapped or
   excluded: **I021/146** Selected Altitude and **I021/148** Final State Selected Altitude (the
   MCP/FCU or FMS altitude the crew dialled in), **I021/110** Trajectory Intent (repeated 4D
   trajectory-change points, each with a position, an altitude, a time over the point and a turn
   radius), REF **`SelH`** Selected Heading, and REF **`NAV`** (autopilot, VNAV, altitude hold,
   approach mode). All of it is parked, and I021/110 is deliberately kept out of `Event.geometry`
   — a `LineString` there would paint a declared future as an observation, which is the one
   failure mode a picture cannot survive.

   *Not yet proposed*, and it is a larger question than a field: an intent is a claim about the
   future with its own confidence, its own expiry and its own author, and the honest shapes are a
   fifth canonical object or an `Event` type meaning "a target declared X". Recorded here so that
   whoever meets it next finds a decision rather than an oversight — and so that **two** adapters
   having now hit it counts as evidence rather than as coincidence.
16. **No per-sample extension, and no per-segment one either.** `TrackSample` has exactly two
   fields — `position` and `observed_at` — and it is `extra="forbid"` with no `attributes` bag.
   `Track` above it has no bag either, which the Legion row set already met and worked around by
   parking a page's `crs` and `paging` on the owning `Entity`. STANAG 4676 turns that inconvenience
   into a structural problem, because **a NITS `TrackPoint` carries sixteen attributes** and a NITS
   `TrackSegment` carries nine more: an identity (`uid`/`lid`), a `Confidence`, a comment, an
   `outline` and an `outlineObscured`, a `nearestConfuser` distance with its own confidence, any
   number of `SensorMeasurement`s, any number of `Dynamics` blocks in different coordinate systems,
   any number of `Evidence` links, a `processType`, an `associatedDetection` flag and a dynamic
   source reference — and per segment, a `status` (`INITIATING`, `MAINTAINING`, `SEARCHING`,
   `TERMINATED`, `GROUND_TRUTH`) with an initiation or termination reason.

   All of it is parked on the owning `Entity`, keyed by sample index. That works and it is bad in
   a specific way: **the index is private knowledge and it is fragile.** A consumer reading
   `attributes.nits_point_dynamics[3]` has to know this adapter's convention, and the key stops
   pointing at the right thing the moment anything re-segments, filters or merges the track. It is
   gap 1's problem — private per-adapter keys standing in for canonical structure — one level
   further down, where it also breaks under list surgery.

   **The segment case is the sharpest of these and it is not hypothetical.** One `TrackData`
   becomes one `Track`, so a `TrackSegment` — which the standard designed precisely so a producer
   could attach a status, a confidence and a *different sensor* to one portion of a track — has
   nowhere structural to live. It is parked at `attributes.nits_segments[]` as a half-open range
   of sample indices with its own attributes hung off it. Every fact the format states about a
   *span* of a history is therefore expressed in this adapter's private index arithmetic, which is
   the clearest statement available of what the CDM is missing here.

   The same shape appears for velocity: `Kinematics` hangs off `Entity`, so a history with a
   velocity at every point yields one `Kinematics` and N parked vectors.

   *Not yet proposed as a field*, and the reason is that the obvious proposal is the wrong size.
   An `attributes` bag on `TrackSample` would close the mechanical problem and would put an
   unbounded dict on the CDM's smallest and most-repeated object, which is the one place the
   never-drop escape hatch has a real cost — a thousand-point track would carry a thousand dicts.
   The honest options are a bag on `TrackSample`, a parallel per-sample structure on `Track`, or a
   decision that a rich track point is an `Event` with a position rather than a sample. Whoever
   takes it should decide which, rather than adding the bag because it is the smallest diff.
17. **No state-vector uncertainty.** `Position.accuracy_m` is one number: metres, 1-sigma,
   horizontal. STANAG 4676 states a `CovarianceMatrix` with a declared `CovarianceType` —
   `POS2D` (3 elements), `POS3D` (6), `VEL2D` (10), `VEL3D` (21), `ACC2D` (21), `ACC3D` (45) —
   holding the diagonal and upper triangle of the covariance over position, or position and
   velocity, or all three, **in whichever of the six coordinate systems the parent `Dynamics`
   block declared**. The `Ellipsoid` class carries one as its shape parameters, and
   `TrackedObject.dims` carries a 6-element covariance on the object's length, width and height.

   Three things the CDM cannot say, in increasing order of how much they matter. It cannot say
   what the **vertical** error is (that is **gap 6**). It cannot say that the horizontal and
   vertical errors are **correlated**, which is the off-diagonal terms and is why a
   `alt_accuracy_m` beside `accuracy_m` would be a partial answer that contradicts its own source.
   And it cannot say anything at all about the uncertainty of the **velocity** or the
   **acceleration**, which is 15 of the 21 numbers in a `VEL3D` matrix and is the part a consumer
   needs in order to know whether a predicted position is worth drawing.

   Legion met the first two of these with a 3×3 matrix and this document parked it under gap 6.
   That was right for one vendor field and it is not enough for a ratified standard that types its
   matrices, states their element order, and hands one to every track point.

   *Not yet proposed*, deliberately: a covariance is meaningless without the frame it was
   expressed in, so a `Position.covariance` field would need a frame field beside it, and the CDM
   has spent five row sets establishing that `Position` is always WGS84 geodetic. Expressing a
   covariance in a geodetic frame is possible and is not free — the units are mixed, exactly as
   NITS's own `WGS_84` velocity is. This should be designed with **gap 6** and probably with a
   general "measurement plus uncertainty" shape rather than one field.
18. **No confidence provenance, and no retraction.** `Entity.confidence` and `Track.track_quality`
   are bare floats in `[0, 1]` where `None` means unknown. STANAG 4676's `Confidence` class is
   four attributes, and every one of them is load-bearing:

   - **`type`**, a `CertaintyStatisticType` of `HUMAN_INSTINCT`, `P-VALUE`, `PROBABILITY` or
     `T-STATISTIC`. **The number is uninterpretable without it.** A `PROBABILITY` of 30 means the
     producer thinks there is a 30% chance; a `P-VALUE` of 30 (i.e. 0.30) means the producer failed
     to reject a null hypothesis, which is close to the opposite claim; a `HUMAN_INSTINCT` of 30 is
     an analyst's shrug. Rendered as one confidence bar they are indistinguishable.
   - **`sourceReliability`**, a separate 0–100 measure of the source, which the standard
     explicitly forbids folding into the value: "the data producer **must not** factor in the
     reliability of the source into its calculation of its confidence in the value". The standard
     names the analogy itself — AJP-2.1's credibility-of-information 1–6 and reliability-of-source
     A–F, the classic two-axis intelligence evaluation. The CDM has one axis.
   - **`valid`**, a boolean **retraction**. `false` means the producer has withdrawn the data this
     confidence is attached to, and it is the mechanism by which a multi-hypothesis tracker deletes
     a segment, a fusion node un-fuses a track and a stitch is undone. The CDM has no way to say
     "this earlier statement is withdrawn" about anything.
   - **`value`** itself, which is an integer percentage, so `value / 100` is exact.

   The consequence in the row set is that `Entity.confidence` and `Track.track_quality` are
   populated **only** when `type` is `PROBABILITY` and `valid` is not `false`, and are `None` in
   every other case with the whole block parked. That is the conservative reading and it throws
   away real information: a well-calibrated `T-STATISTIC` becomes "not assessed".

   *Not yet proposed as a field.* The mechanical part — a type enum and a source-reliability float
   beside the value — is easy and is not the interesting part. **Retraction is**, and it is not a
   field: withdrawing a previously emitted object means the CDM has to have a concept of an object
   superseding another, which touches identity, `valid_to`, and whether a consumer is expected to
   hold state at all. Note the interaction with the no-fusion line: the row set carries retractions
   and refuses to apply them, so whatever closes this gap decides where in the pipeline they *are*
   applied. That is a platform decision, not a model one, and it should be made before the field.
19. **No relation object, which is what gaps 11 and 14 have both been describing.** The CDM has
   exactly one link between objects: `Event.related_entities`, a list of `entity_id` values. Every
   other relationship an adapter meets is reduced to an opaque identifier in `attributes`.

   STANAG 4676 is where that stops being survivable, because it uses **six distinct kinds of
   reference** and they are the substance of the format rather than its bookkeeping:

   | Reference | From → to | What is lost |
   |---|---|---|
   | `Evidence.detectionUID` / `.detectionLID` | a track point → the detections supporting it | the entire evidence chain — why the tracker believes the object was there |
   | `TrackSource.sensorUID` / `trackerUID` / `collectionUID` / `productUID` (+ LID forms) | a track or segment → who produced it | **gap 14** |
   | `TrackLinkage.preUID` / `postUID` (+ LID) | a track → the tracks it split from, merged into or stitches to | track lineage |
   | `ProcessedTrack.inputUID` / `outputUID` (+ LID) | tracks → the fused or smoothed track that subsumes them | which tracks a fused picture is made of |
   | `MotionEvent.trackUID` / `trackLID` | an event → the tracks that participated in it | who was in the convoy, who met whom |
   | `Dynamics.cftUID`, `Shape.cftUID`, `dynSrcUID`, `exampleDetectionUID` | an object → the frame, transform or exemplar it depends on | whether a local coordinate can be resolved at all |

   These are not all the same relation and that is the point: a `parent_id` (gap 11) would express
   none of them, and a `SourceRef.sensor` (gap 14) would express one. What they have in common is a
   **typed, directed link between two CDM objects**, which the model does not have.

   The row set parks every one of them as an identifier and resolves none, which is correct under
   the no-fusion line — resolving `Evidence` → `Detection` is a join — but note that the *carrying*
   is also degraded: a parked UID is a string a consumer must know this adapter's key to find, and
   the object it names has an `entity_id` or an `event_id` the consumer cannot get to it from.

   *Not yet proposed*, and it is the largest open question in this document. A relation is a fifth
   thing in a model built on four, and the honest shapes are very different from one another: a
   `relations` list on `CDMBase` with a typed predicate; a fifth canonical object (a `Relation`
   with a subject, a predicate, an object and a confidence, which would also give retraction from
   **gap 18** somewhere to live); or a decision that relations belong in the store and not in the
   interchange model.

   **One design question, three gap numbers.** Gaps **11** (containment), **14** (provenance) and
   **19** (reference) are the same missing thing seen from three sides, and both of the others
   carry this same paragraph pointing here. They are on the 1.1.0 roadmap **as a single item, to
   be resolved together under whichever number survives** — gap numbers are append-only, so 11 and
   14 stay in the list and name the number that carried the decision. Three adapters have now hit
   it — Legion's `parent_id`, CAT021's ground station, and this format's six reference kinds —
   and a fourth will not add information.
