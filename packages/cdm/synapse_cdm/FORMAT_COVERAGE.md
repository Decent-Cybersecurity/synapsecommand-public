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
| `models` | provided by the models themselves; no adapter code is involved |
| `not yet` | no adapter implements this row. The mapping is a specification, not a claim |

`legion 1.0.0` and `legion 1.0.0 · parked` joined this list when adapter #5 landed. Until it
did, every Legion row said `not yet` — the row set was written and reviewed as a specification
first, and the status column is what recorded the difference.

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

## STANAG 4676 — track ingest

No adapter yet. Every row below is a specification for whoever writes it.

| STANAG 4676 | CDM field | Status | Notes |
|---|---|---|---|
| `TrackMessage/trackUUID` | `Track.track_id` | `not yet` | derive with `ids.derive` when absent |
| `Track/trackNumber` | `Track.source_ids[].external_id` | `not yet` | the operator-facing track number |
| `TrackPoint/trackPointPosition/latitude` | `Track.samples[].position.lat` | `not yet` | |
| `TrackPoint/trackPointPosition/longitude` | `Track.samples[].position.lon` | `not yet` | |
| `TrackPoint/trackPointPosition/hae` | `Track.samples[].position.alt_m` | `not yet` | |
| `TrackPoint/trackPointTime` | `Track.samples[].observed_at` | `not yet` | ordering is validated by `Track` |
| `TrackPoint/trackPointSource` | `Track.samples[].position.position_source` | `not yet` | |
| `TrackPoint/trackPointObjectMass` etc. | `Entity.attributes` | `not yet` | source-specific, parked |
| `TrackPoint/trackPointVelocity` (u,v,w) | `Kinematics.speed_mps` | `not yet` | **gap 4** — vector → scalar+course, a declared transform |
| `TrackPoint/trackPointVelocity` (w) | `Kinematics.climb_mps` | `not yet` | sign convention differs; declare it |
| `Track/trackQuality` | `Track.track_quality` | `not yet` | **gap 3** — 4676 is integer 0–15, CDM is float 0–1 |
| `Track/objectClassification` | `Entity.entity_type` | `not yet` | plus original in `attributes` |
| `Track/classificationConfidence` | `Entity.confidence` | `not yet` | |
| `IdentityIndicator` | `Entity.affiliation` | `not yet` | **gap 2** — 7 values collapse to 4 |
| `exerciseIndicator` | `Entity.source.synthetic` | `not yet` | maps exactly — and this is why `synthetic` has no default |
| `TrackMessage/security/…` | `Entity.attributes` | `not yet` | classification marking lives at the platform gateway, not here |

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
3. **Track quality scale.** 4676 integer 0–15 → CDM float 0–1 is `value / 15`, a declared
   transform. Note that 4676 quality 0 means "worst", not "unknown", and CDM `None` means
   unknown — so a missing 4676 quality must become `None`, never `0.0`.
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
