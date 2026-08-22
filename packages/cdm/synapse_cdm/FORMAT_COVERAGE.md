# Format coverage — does the CDM actually carry what these formats need?

The brief asks the model to "map cleanly to Cursor-on-Target, STANAG 4676 track structures and
GeoJSON". This file is that check, done field by field rather than asserted — and it has since
grown the row sets of the formats that actually landed, AIS among them. It is also a
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
   than merely re-reporting it.
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
