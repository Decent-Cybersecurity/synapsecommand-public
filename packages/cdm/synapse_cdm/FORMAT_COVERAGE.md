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
| `adsb 1.0.0` | implemented by `adapters/adsb.py`, with a fixture and a golden file |
| `adsb 1.0.0 · parked` | implemented, but the value lands in `attributes` because of a named gap below |
| `adsb 1.0.0 · egress` | implemented in the `from_cdm()` direction |
| `models` | provided by the models themselves; no adapter code is involved |
| `not yet` | no adapter implements this row. The mapping is a specification, not a claim |

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
   decision is missing.
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
3. **Track quality scale.** 4676 integer 0–15 → CDM float 0–1 is `value / 15`, a declared
   transform. Note that 4676 quality 0 means "worst", not "unknown", and CDM `None` means
   unknown — so a missing 4676 quality must become `None`, never `0.0`.
4. **Velocity representation.** 4676 carries a 3-vector; the CDM carries speed/course/climb.
   The conversion is exact arithmetic and reversible, so it is a declared transform rather
   than a gap in meaning — but an adapter must declare it or the lossless check will (correctly)
   flag every velocity component.
5. **Feature / FeatureCollection.** Not modelled. `PlanObject` is the CDM's Feature-equivalent
   (geometry + style + label), and a FeatureCollection is a list of PlanObjects. Adding the
   GeoJSON wrappers would give two ways to say one thing.
6. **Vertical accuracy.** CoT `@le` has no canonical home; `Position.accuracy_m` is horizontal
   only. *Proposed: `Position.alt_accuracy_m` in 1.1.0 (MINOR).* Matters for air tracks, where
   a 300 m vertical error decides whether two aircraft are deconflicted. **Now confirmed by a
   shipped adapter**: `air_track_due_north.xml` carries `le="120.0"` on a track at 7 620 m, and
   that 120 m sits in `attributes` where no consumer will look for it.
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
