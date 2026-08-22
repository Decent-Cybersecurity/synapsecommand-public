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
