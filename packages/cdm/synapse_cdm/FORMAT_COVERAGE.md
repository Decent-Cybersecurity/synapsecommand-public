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
| `nits 1.0.0 · provisional` | implemented by `adapters/stanag4676.py`, with a fixture twin and a golden file — and **the XML element name it binds to is provisional**, see below |
| `nits 1.0.0 · parked · provisional` | implemented, the value lands in `attributes` because of a named gap below, and the element name is provisional |
| `nits 1.0.0 · egress · provisional` | implemented in the `from_cdm()` direction, element name provisional |
| `gmti 1.0.0` | implemented by `adapters/gmtif.py` on the codec in `adapters/gmtif_codec.py`, with a binary fixture twin and a golden file |
| `gmti 1.0.0 · parked` | implemented, but the value lands in `attributes`/`payload` because of a named gap below |
| `gmti 1.0.0 · egress` | implemented in the `from_cdm()` direction |
| `cat048 1.0.0` | implemented by `adapters/asterix_cat048.py` on the codec in `adapters/cat048_codec.py`, with a binary fixture twin and a golden file |
| `cat048 1.0.0 · parked` | implemented, but the value lands in `attributes`/`payload` because of a named gap below |
| `cat048 1.0.0 · egress` | implemented in the `from_cdm()` direction |

**What `· provisional` qualifies, precisely.** It is a statement about the **XML element name**,
not about the mapping. The normative XSD is distributed through NATO national representatives
(Ed B §B.5) and could not be obtained or hashed here, and the standard says tags were shortened
"to as little as two letters" — so the reader and writer bind UML attribute names to element
names through one table, `ELEMENT_NAMES`, which is empty because nothing is *known* to be
renamed. The **data-model mapping in these rows is not provisional** and neither is the
parsed-dict path: a caller holding a parsed document gets the same CDM either way, and a twin
test asserts it. The qualifier sits in the status column rather than in a paragraph because a
reader deciding whether to point a real feed at this adapter reads the status column, and the
exit condition has its own row in the declines-and-blockers table below.
| `models` | provided by the models themselves; no adapter code is involved |
| `not yet` | no adapter implements this row. The mapping is a specification, not a claim |

`legion 1.0.0` and `legion 1.0.0 · parked` joined this list when adapter #5 landed. Until it
did, every Legion row said `not yet` — the row set was written and reviewed as a specification
first, and the status column is what recorded the difference.

**The STANAG 4676 row set went through that state too**, and `adapters/stanag4676.py` has now
landed, so `test_the_nits_row_set_claims_its_adapter` is the inverted form: it fails if a row
still says `not yet` while the code implements it.

**The STANAG 4607 / AEDP-4607 row set went through that state too**, and `adapters/gmtif.py` has
now landed, so `test_the_row_set_claims_this_adapter` is the inverted form: it fails if a row still
says `not yet` while the code implements it. Note what `gmti 1.0.0` does **not** carry: unlike the
NITS markers there is no `· provisional` qualifier, because a binary format's field layout is fixed
by the standard's own byte tables rather than by a schema distributed through national
representatives — every offset in this row set is checkable against a table in the pinned document,
and `test_every_segment_layout_sums_to_the_standards_own_byte_count` checks it.

**The ASTERIX Category 048 row set went through that state too**, and
`adapters/asterix_cat048.py` has now landed, so `test_the_row_set_claims_this_adapter` is the
inverted form: it fails if a row still says `not yet` while the code implements it. Two things
about it are deliberately unlike the CAT021 rows it sits beside, and both are settlements rather
than omissions: the **Reserved Expansion Field is parked** rather than in scope, and the reason is
procedural rather than textual — the appendix that defines it is public and simply was not pinned
here; and **geometry is derived only when a `sensor_position` is injected at construction**,
because the format states range and azimuth from a station whose location it never carries, and
the caller owns that value the way it already owns the clock. Note what `cat048 1.0.0` does not
carry: no `· provisional` qualifier, because every offset in this row set is checkable against a
table in the pinned document — and `test_the_item_layouts_sum_to_the_standards_own_byte_counts`
checks it. What it carries instead is the admission in **gap 24**: the *geodesy* is not in the
pinned document at all, and the inversion audit is what stands in for the document's blessing.

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
| SHA-256 (wrapper) | `5c74626102ca0b24735a98c6e0b67191d241afec075f2298c72e51b6223f8a9f`, 255 250 bytes, 5 pages, `fixtures/stanag4676/spec/nato-stanag-4676-edition-2.pdf` |
| **The target** | **AEDP-12, NATO Intelligence, Surveillance and Reconnaissance Tracking Standard, Edition B Version 2, March 2022**. Every mapped element below cites this document. **Version 2 is not a reading of "Edition B" — it is printed on the title page and on the footer of all 150 pages.** The document carries **no NATO Letter of Promulgation**: page I reads "RESERVED FOR NATIONAL LETTER OF PROMULGATION", so no promulgation date is stated anywhere inside it and the pin does not claim one — see ambiguity 12 |
| SHA-256 (target) | `c55573231a5882f031862b06589d5a7abaeda9cf7c0b7a55d81843eeb7dc138b`, 6 785 016 bytes, 150 pages, `fixtures/stanag4676/spec/nato-aedp-12-edition-b-v2.pdf` |
| Implementation Guide | **AEDP-12.1, NITS Implementation Guide, Standards Related Document (SRD), Edition A Version 1, March 2022**. Also carries no NATO Letter of Promulgation. Annex D is the XSD annex and Annex J the Configuration Management Plan; the guide's own Annex F is Binary Encoding, which is what ambiguity 8 is about |
| SHA-256 (guide) | `7a4267fced81c760c8a8b487a70b9bb8507b9f765cb32bc4a0a97996b0c4341d`, 6 815 298 bytes, 192 pages, `fixtures/stanag4676/spec/nato-aedp-12-1-edition-a-v1.pdf` |
| Historical context only, and **never a basis** | AEDP-12 **Edition A Version 1**, May 2014 — the STANAG 4676 Edition 1 generation, which Edition B's §2.1.1.1 declares incompatible with Edition 2 in as many words. Read for the delta below and for nothing else. Edition B v2's own reference list dates it "May 2014" and marks it "(covered by STANAG 4676)", and the STANAG 4676 Edition 2 cover supersedes "STANAG 4676, Edition 1, dated 20 May 2014" — so the wrapper and the AEDP agree on the generation this document belongs to. **The incompatibility statement is §2.1.1.1, not the foreword**: Edition B v2's FOREWORD (page VII) is about interoperability aims, the CST and the Custodian's address, and says nothing about Edition 1 |
| SHA-256 (2014) | `a9e88c81369ff4f13a9d4d7e457de55c6cefcc024162efe5a198e395d8898814`, 3 719 388 bytes, 148 pages. **A reseller copy**, per-page watermarked to the licensee, so this hash identifies that copy and not the NATO original — which is one more reason it is context and not a target. **Not present in `fixtures/stanag4676/spec/` and therefore NOT re-verified on 2026-08-23**: this hash stands on the reading that recorded it, and it is the one line in this pin table that the re-verification below could not check. That is a premise, and it is the right premise to carry — a watermarked reseller copy is not a document a later reader can be expected to reproduce |
| **The XML schema** | **NOT PINNED, and not obtainable here** — see the encoding settlement, whose reason was corrected on 2026-08-23. The park does not rest on the file being unobtainable: it rests on guide §D.1.1, which versions the XSD on its own axis with its own revision number and revision date inside the file, so the AEDP edition does not name one schema |

**Pin re-verification, 2026-08-23 — three of the four copies are on disk, and they are the copies
the row set was written from.** Each SHA-256 was recomputed from the file in
`fixtures/stanag4676/spec/`, each byte count and page count re-measured, each title page re-read.
All three match:

| Filename | Title-page identity, as printed | Bytes | Pages |
|---|---|---|---|
| `nato-stanag-4676-edition-2.pdf` | "STANDARDIZATION AGREEMENT / STANAG 4676 / NATO INTELLIGENCE, SURVEILLANCE AND RECONNAISSANCE TRACKING STANDARD / EDITION/ÉDITION 2 / 13 October/octobre 2021" | 255 250 | 5 |
| `nato-aedp-12-edition-b-v2.pdf` | "NATO STANDARD / AEDP-12 / NATO INTELLIGENCE, SURVEILLANCE AND RECONNAISSANCE TRACKING STANDARD / Edition B, Version 2 / MARCH 2022" | 6 785 016 | 150 |
| `nato-aedp-12-1-edition-a-v1.pdf` | "STANDARDS RELATED DOCUMENT / AEDP-12.1 / NATO INTELLIGENCE, SURVEILLANCE AND RECONNAISSANCE TRACKING STANDARD IMPLEMENTATION GUIDE / EDITION A VERSION 1 / MARCH 2022" | 6 815 298 | 192 |

**Version 2 is resolved explicitly, and the resolution is the AEDP's, not the wrapper's.** The
STANAG 4676 Edition 2 cover names its standard **without a version** — "STANDARD / AEDP-12,
Edition B" — and unlike the STANAG 4607 cover it names no version anywhere else either, so the
ratification wrapper alone cannot tell a reader which Edition B this row set is against. The pinned
AEDP settles it from its own side: **Edition B, Version 2** on the title page and in the footer of
every one of its 150 pages. This section's target row now says Version 2 for that reason rather
than by inference, and ambiguity 12 records what the wrapper leaves open.

**The pinned Version 2 text is the text the adapter was built against, and these are the clauses
that were compared** — each one load-bearing for a settlement, an ambiguity or a row, matched
verbatim in the pinned copy: §2.1.1.1's "STANAG 4676 Ed. 2 is incompatible with STANAG 4676 Ed. 1 …
re-architect the data model and XML-based syntax from scratch" (settlement 1); §2.1.1.6's "The core
STANAG 4676 data model is silent on confidentiality metadata" (settlement 3); §2.1.1.7's attributes
that "should be interpreted as 'elements'" with `type` the exception (settlement 4 and ambiguity 5);
§2.1.1.8's "two options for encoding the model, plain-text XML and EXI … The Custodial Support Team
recommends the use EXI over plain-text encoded XML" (settlement 4); the CONVENTIONS clause on
`xsi:type`, "`<outline xsi:type="Polygon">…</outline>`", and the naming clause's tags "reduced in
size to as little as two letters"; §2.5.13's `z = r cosϕ` against Table 2.5.27-2's "radial, polar
and azimuthal values, respectively" (ambiguity 1, still live and still unresolvable from the data);
§2.6.3's ellipsoid "defined based on a center, the lengths of the axes (**not the semi-axes**)"
against its own worked example squaring a radius (ambiguity 6, still live); `MotionEvent.startRelTime`'s
"i.e. the value does not default to baseTime" (ambiguity 2); `ProcessedTrack.inputUID`'s "must have
a single input track specified as either a UID or LID" beside its own "two or more" (ambiguity 3);
`NITSRoot.msgCreatedTime`'s citation of "the ISO 8001 standard" (ambiguity 10); and the
`motionImageryCoreID` note that "the XML schema incorrectly defines the name space using nga.gov
instead of nga.mil" (ambiguity 11). Nothing was re-based and no row moved: every ambiguity checked
is present in the promulgated Version 2 text, which is what makes them the standard's rather than
an artefact of the copy that was read.

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
time, produces a `Track` the CDM refuses.

**The two conditions are checked independently and every violated one is quoted.** They overlap
in practice — segments that overlap in time are usually also out of order — so first-match-wins
would mean a producer only ever hears about whichever check happened to run first, and a refusal
that names the wrong cause is a guess wearing a refusal's clothes. One refusal, every violation
listed, each prefixed `OUT OF ORDER` or `OVERLAPPING SEGMENTS`.

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

**The XML schema is normative for conformance**, and the two documents say it in the same two
sentences. **Edition B §B.6**, printed page B-4 (PDF page 144), and **guide §D.6**, printed page D-2
(PDF page 157), each read in full: "The XML schema defined within the standard is normative for
conformance only. Implementations may use any method to write the XML formatted data as long as that
resulting data conforms to the schema." Both sections are two sentences long and neither carries a
third, so the attribution is to both and not to §B.6 alone. Checked on 2026-08-23 against a reported
alternative wording for §D.6 — one making the XSD "the normative reference for conformance" and
placing it in a "STANAG 4676 library": **neither phrase occurs anywhere in the pinned guide.**
`normative reference` has no hits in its 192 pages and `normative` has exactly two, this sentence
and §G.2's "STANAG 4676 defines the normative XML schema using XML Schema 1.1" on PDF page 167. Recorded because
that wording would have moved the park's attribution, and the absence of a phrase is the one thing a
section number cannot show.

And the schema is **not distributed with the standard** — neither AEDP contains it, and the
standard's Annex B and the guide's Annex D are prose *about* the schema rather than the schema.

**The two documents name two different, unlinked distribution channels, and this row set said
"mirror" where the text says no such thing** — corrected on the 2026-08-23 re-verification, because
the difference is the difference between one artefact and two. **Edition B §B.5**, printed page B-4
(PDF page 144): "The .xsd and .xml electronic files are available on the NATO Defense Investment Web
Site (DiWEB) under the JCGISR link in the STANAG 4676 section: https://diweb.hq.nato.int. Request
access through your respective NATO JCGISR National Representative." **Guide §D.1**, printed page
D-1 (PDF page 156): "The .xsd and .xml electronic files are available on the All Partners Network
Access (APAN) site under the 4676 Community: https://wss.apan.org/csa/4676_CST/SitePages/Home.aspx",
followed by "To request access to the APAN and the 4676 Community site:" and five numbered steps, the
second of which is "Select 'Create An Account'". **Neither document mentions the other's channel** —
`DiWEB` and `Defense Investment` appear **nowhere** in the 192-page guide, and `APAN` appears nowhere
in the 150-page standard — and nothing in either says the two hold the same file. Both are
access-controlled and neither is a public URL, so no pin exists for the one document that fixes the
syntax; but the reason is now two unreconciled sources rather than one unreachable one.

**And the ground that actually carries this park is not procurement at all — it is configuration
management, which was missing from the reason recorded here before.** **Guide §D.1.1**, printed page
D-1 (PDF page 156), in full: "For configuration management purposes, the 4676 XSD schema is
maintained by the Custodian. As new versions or editions of the 4676 standard are ratified, the
latest version of the XSD schema will be copied to the All Partners Network Access (APAN) site under
the 4676 Community: https://wss.apan.org/csa/4676_CST/SitePages/Home.aspx. **The XSD file contains
the schema revision number, revision date, and change log.** This provides the mechanism to identify
the latest version and manage updates to the schema." So the schema is versioned **on its own axis**,
inside its own file, by the Custodian, and the AEDP edition does not fix it: "the XSD for Edition B
Version 2" does not name one artefact, and two files with different hashes can both be it. That is
why this is a park and not an errand. Obtaining the file through a national representative — which a
reader with the right phone number could do tomorrow — would dissolve the *procurement* reason and
leave this one standing untouched, which is the test of whether a reason was the real one.

**§D.1.1 is not §C.1.1, and confusing the two is the one live way to get this park wrong** — so the
distinction is recorded rather than left to be re-derived. The guide configuration-manages **two
different artefacts in two different annexes, with different metadata**, and the weaker one comes
first in the document. **§C.1.1**, "Configuration Management of the 4676 Data Model", printed page
C-1 (PDF page 147), in full: "For configuration management purposes, the data model files are
maintained by the Custodian. The files contain revision number and date. This provides the mechanism
to identify the latest version and manage updates to the data model." That is the **data model**
files, and it gives **revision number and date only — no change log**. §D.1.1 nine pages later is
the **XSD**, and it is the one that adds the change log. A reader who finds §C.1.1 first and stops
there will conclude that this row set quoted a section that says something else, which is exactly
what an independent read of the pinned guide reported on 2026-08-23; the resolution is that both
sections exist, both are quoted above, and the exit condition cites §D.1.1 because the XSD is what
it is about. Nothing in the argument depends on the change log — "revision number and date" alone
already means an edition does not name a revision — but the quote is §D.1.1's and it is reproduced
in full so the next reader compares sentences instead of section numbers.

**What the guide says about the root element is the part that costs nothing and is worth having.**
Edition B §B.1 and guide §D.2, the latter under an explicit **AEDP-12 Requirement** callout, carry
the same sentence: "The root element of a STANAG 4676 object in XML format must be the NITSRoot
element of type NITSRoot." Settlement 1 refuses a document whose root is `TrackMessage`, and that
refusal now rests on a normative callout in the pinned guide rather than on the edition delta alone.
It is also the single syntax fact the XSD *cannot* move, so it is the one element name below that is
not provisional in substance — the qualifier stays on the row anyway, because a status column that
carries exceptions is a status column nobody can read.

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
| `TRAVELER` | "A **suspect** surface track following a recognized surface traffic route" | does not set it, **and does not downgrade it either** — `SUSPECT` has no CDM member, `identity` governs whatever it says, and **gap 2** records the loss |
| `ZOMBIE` | "A **suspect** track, object or entity of special interest" | likewise, including over a `FRIEND` identity: two separate attributes with no stated co-occurrence restriction, so a subordinate field does not rewrite a primary assertion |

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
| `NITSRoot.profile` | `[1..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `ComplianceProfile`. See the profiles settlement — read, never followed; unregistered literals parked |
| `NITSRoot.streamUID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the DATASTREAM's own `UUID`. Parked; it identifies a stream this adapter does not assemble |
| `NITSRoot.fileUID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | this object's `UUID`. Parked, and it is the document identifier a consumer needs to deduplicate a retransmission |
| `NITSRoot.fileLID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `UInt`. Parked; scoped by `lidScopeUID` like every other local ID |
| `NITSRoot.lidScopeUID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | **the attribute that decides whether any `lid` in this document may become a `SourceId`.** "Required if local IDs are found in the object" — a document containing local IDs and no scope is non-conforming, and is translated with every `lid` parked rather than keyed |
| `NITSRoot.numFiles` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | how many related files the producer has sent so far, including this one. Parked; the adapter counts nothing and waits for nothing |
| `NITSRoot.msgCreatedTime` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | when the producer **wrote the file**. Parked, and deliberately neither `observed_at` nor `received_at`: it is a source time about the document, not about an observation, and it is the ordering key the consolidation rule uses |
| `NITSRoot.nitsVersion` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `"B.2"` for the target edition. **The version gate**: anything reading `A.*` is refused with the value quoted, per the edition settlement |
| `NITSRoot.product` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | one `ProductIdentification`; its own table below |
| `NITSRoot.collection` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `CollectionInformation`, one per collection; its own table. **Parked, including `essence`** — no payload field sets `source.synthetic` |
| `NITSRoot.sensor` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | `SensorInformation`, one per sensor; its own table. **Gap 14** |
| `NITSRoot.tracker` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | `TrackerInformation`, one per tracker; its own table. **Gap 14** |
| `NITSRoot.message` | `[0..*]` | — | `nits 1.0.0 · provisional` | `TrackMessage`. The container everything below hangs from; not itself parked, because its contents become objects |
| *(the XML syntax, not the model)* | `[1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | `originatorConfidentialityLabel` — **mandatory on the root element** per Annex B.2. Parked verbatim at `attributes.confidentiality_label.originator`. **Gap 12** |
| *(the XML syntax)* | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `alternativeConfidentialityLabel`, verbatim |
| *(the XML syntax)* | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `metadataConfidentialityLabel`, verbatim |

`ComplianceProfile`: `STANDALONE`, `DATASTREAM`. Both handled; see the settlement.

### Row set — `ProductIdentification`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `ProductIdentification.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | parked; a product is not a CDM object |
| `ProductIdentification.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | parked |
| `ProductIdentification.id` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | "a free-form string allowing the data provider to specify the designation (ID) of this STANAG 4676 based product **per that system's ID syntax**" — a per-system syntax, so not a key |
| `ProductIdentification.name` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the product's name, e.g. "System X Motion Imagery Track Product". **Not `attributes.callsign`** — it names the product, not the contact |
| `ProductIdentification.shortName` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | e.g. "XMTP" |
| `ProductIdentification.effectivity` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the named effectivity the product complies with |

### Row set — `CollectionInformation`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `CollectionInformation.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | referenced by `TrackSource.collectionUID` |
| `CollectionInformation.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | likewise |
| `CollectionInformation.intent` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `CollectionIntentType`. Parked and **does not set `synthetic`**: `EXERCISE` data is frequently real sensor data, and `TEST`, `ENGINEERING` and `INITIALIZATION` say when a collection happened in its programme, not whether it was real |
| `CollectionInformation.essence` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `CollectionEssenceType`. **Parked verbatim and does not set `source.synthetic` either** — see the note below. Where it contradicts the deployment declaration the document is refused, never silently flipped |
| `CollectionInformation.targetID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | "an identifier for the primary **target area**" — an area, not an object, and not a name |

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
| `SensorInformation.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the target of `TrackSource.sensorUID` and `Detection.sensorUID` |
| `SensorInformation.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | likewise |
| `SensorInformation.sensorID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | an `IDData`; its own table |
| `SensorInformation.name` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | names the sensor, not the contact |
| `SensorInformation.description` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | |
| `SensorInformation.modality` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `ModalityType`. **Deliberately does not refine `Position.position_source`** — see the note below |
| `SensorInformation.url` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | a URL for the sensor information data. Parked and **never fetched**: an adapter that dereferences a URL out of a payload is a network client with a payload-controlled target |
| `SensorInformation.collectionMode` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | free string; the standard expects to drop it in a future release |
| `SensorInformation.absTimeUncertainty` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | seconds of uncertainty in the sensor's clock. **Gap 13** — the CDM has no per-measurement time, let alone an uncertainty on one |
| `SensorInformation.relTimeUncertainty` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | seconds of uncertainty between any two of its times. **Gap 13** |
| `SensorInformation.comment` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | free text, and §2.1.1.4 forbids parsing it for embedded data. Parked as the complete string, never split |
| `SensorInformation.esmSensor` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | an `ESMSensor`, which has no attributes |
| `SensorInformation.imagingSensor` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | an `ImagingSensor`; its own table |
| `SensorInformation.radarSensor` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | a `RadarSensor4607`; its own table |

`ModalityType`, all eighteen literals parked verbatim: `DOPPLER_SIGNATURE`, `HRR_SIGNATURE`,
`IMAGE_SIGNATURE`, `HUMINT`, `MASINT`, `ELINT`, `COMINT_EXTERNALS`, `COMINT_INTERNALS`, `OSINT`,
`BIOMETRICS`, `AIS`, `BFT`, `SEISMIC`, `ACOUSTIC`, `ADS-B`, `MIXED`, `OTHER`, `XXXX`.

**`modality` sets `position_source` on one branch and not the other, and both are in the row.**
Ed B defines modality as the "category of the sensor according to the type of signal it **can
detect**", and for `AIS`, `ADS-B` and `BFT` the signal detected *is* a GNSS-derived position the
object broadcast about itself. That is a fact the sensor read, not an inference — and it is the
same reading `adapters/ais.py` and `adapters/adsb.py` give their own positions, so declining it
here would make one airframe's fix `GNSS` through 1090ES and `ESTIMATED` through a NITS track of
the same broadcast.

| Branch | `Position.position_source` |
|---|---|
| the `TrackSource` reference chain resolves **within this document** to a sensor whose modality is `AIS`, `ADS-B` or `BFT` | **`GNSS`**, with the basis naming the modality and which compliance profile applied |
| the reference **dangles** — it points at a `SensorInformation` in a previously transmitted DATASTREAM file, which this adapter does not fetch | `ESTIMATED` |
| the modality is `MIXED`, `OTHER` or `XXXX` | `ESTIMATED` — those name no signal in particular, so they refine nothing |
| any other modality, or no sensor referenced at all | `ESTIMATED` — a NITS track point is a tracker's estimate unless something says otherwise |

Three things worth stating about the split. **The conservative branch is deliberately the wider
one**: a mix of cooperative and non-cooperative sensors on one `TrackSource` gives `ESTIMATED`,
because understating is the direction that survives being wrong. **The chain is resolved per
segment, not per track**, because §2.5.24 scopes a `TrackSegment.segmentSource` to "a specific
portion of the track" — so two segments of one history can legitimately differ, and
`attributes.nits_segments[].position_source` records which each took. And **the dangling case is
not a refusal**: STANDALONE guarantees at least one sensor block in the document, DATASTREAM does
not, and a reference that resolves to a file we do not have means the modality is unknown here —
which is what `ESTIMATED` says.

**The per-frame route is deliberately not read.** `TrackPoint.dynSrcUID` →
`DynamicSourceInformation.sensorUID` is a second chain to a modality, and it can disagree with the
`TrackSource` one. Reading both would need a precedence rule for the disagreement and nobody has
written one, so this row set names `TrackSource` and a test pins that it is the only chain
consulted.

#### `ESMSensor`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| *(no attributes)* | — | `Entity.attributes` | `nits 1.0.0 · provisional` | §2.5.5: "a placeholder for future additions and does not currently include any attributes". Its **presence** is the datum, so it is parked as a present-and-empty marker; open content may still carry vendor extensions and those land in `source_extras` |

#### `RadarSensor4607`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `RadarSensor4607.platformID` | `[1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | STANAG 4607 field P8 — a tail number for an aircraft. **Not a `SourceId` for the tracked object**: it identifies the *collecting platform*. Gap 14 |
| `RadarSensor4607.missionID` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | 4607 field P9 |
| `RadarSensor4607.jobID` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | 4607 field P10; 0 means no specific request, which is a stated value and not an absence |

#### `ImagingSensor`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `ImagingSensor.motionImageryCoreID` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | a `MiisCoreIdType` per **MISB ST 1204.3**. Parked verbatim and **not decoded**: the MIIS Core Identifier is a separate standard, the same category as CAT021's BDS registers. Note the standard's own erratum — the XSD namespace says `nga.gov` where `nga.mil` was meant, and keeps it for backwards compatibility |
| `ImagingSensor.frameHeight` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | focal-plane height in pixels |
| `ImagingSensor.frameWidth` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | focal-plane width in pixels |
| `ImagingSensor.fpaIndex` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | **1-based**, unlike every pixel index in the model, which is 0-based. Parked as sent with the base recorded |
| `ImagingSensor.filter` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | wavelength/transmission pairs in one flat array, microns and fraction. Parked as pairs |
| `ImagingSensor.phenomenology` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `SymbolicSpectralRange`: `LWIR`, `MWIR`, `SWIR`, `NIR`, `VIS`, `UV`, `MSI`, `HSI`, `DERIVED`, `UNKNOWN` |
| `ImagingSensor.band` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the imaging system's own band name, e.g. "LWIR-8" |

#### `TrackerInformation`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `TrackerInformation.type` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `TrackerType`: `MANUAL_TRACKER`, `AUTOMATIC_TRACKER`, `SEMIAUTOMATIC_TRACKER`. An XML attribute rather than an element, per §2.1.1.7 |
| `TrackerInformation.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the target of `TrackSource.trackerUID` |
| `TrackerInformation.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | likewise |
| `TrackerInformation.trackerID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | an `IDData` — the station ID and nationality that "provides unique identification of any given STANAG 4676 capable system". **Gap 14**, and the closest thing in the model to naming who produced the data |
| `TrackerInformation.name` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | names the algorithm |
| `TrackerInformation.description` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | |
| `TrackerInformation.version` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the tracker algorithm's version — "useful record in case the tracker algorithm gets updated, or a systematic error is discovered". Parked, and it is the field that makes a stored track re-auditable |
| `TrackerInformation.supplementaryData` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `SupplementaryData`; its own table |

#### `SupplementaryData`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `SupplementaryData.type` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `SupplementaryDataType`: `GIS_ROAD_NETWORK`, `DIGITAL_ELEVATION_MODEL`, `SHIPPING_LANE`, `AIR_CORRIDOR`, `DIGITAL_TERRAIN_MODEL`, `DIGITAL_SURFACE_MODEL`, `EDGE_DETECTION_SCENE`, `ILLUMINATION/SHADOW_MAP`, `FOUNDATION_FEATURE_DATA`, `AUTOMATIC_SCENE_SEGMENTATION` |
| `SupplementaryData.name` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | which DEM, which road network |
| `SupplementaryData.version` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | recorded "in case a future update to the supplementary data set requires reassessing the tracks" |
| `SupplementaryData.description` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | |

### Row set — `TrackMessage` and the time base

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `TrackMessage.numDetections` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | how many detections the producer says this message holds. Parked, and **checked**: a count that disagrees with the number parsed is recorded at `payload.count_disagreement`, never used to stop parsing. The standard says omitting it "simply means the number is not reported", so absence is not zero |
| `TrackMessage.numTracks` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | on the same terms |
| `TrackMessage.baseTime` | `[1]` | `Track.samples[].observed_at` | `nits 1.0.0 · provisional` | the absolute UTC base every `relTime` in this message scales from. Absent, naive or malformed is a **refusal quoting the value** — see the time settlement |
| `TrackMessage.relTimeIncrement` | `[1]` | `Track.samples[].observed_at` | `nits 1.0.0 · provisional` | seconds per increment, a `double`. Zero, negative or non-finite is a refusal. Parked verbatim, because egress re-emits from the park rather than recomputing |
| `TrackMessage.dynSrcInfo` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `DynamicSourceInformation`, one per frame or dwell; its own table |
| `TrackMessage.detection` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | `Detection`, each becoming its own `Event`; its own table |
| `TrackMessage.track` | `[0..*]` | `Track.samples[]` | `nits 1.0.0 · provisional` | `TrackData`, each becoming an `Entity` and one `Track` per segment |
| `TrackMessage.processedTrack` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | `ProcessedTrack`, carried verbatim, never acted on |
| `TrackMessage.trackLinkage` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | `TrackLinkage`, likewise |
| `TrackMessage.motionEvent` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | `MotionEvent`, each becoming its own `Event` |

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
| `DynamicSourceInformation.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the target of `dynSrcUID` on a `TrackPoint` or a `Detection` |
| `DynamicSourceInformation.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | likewise |
| `DynamicSourceInformation.relTime` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | when this frame or dwell was taken. Parked with its absolute resolution beside it |
| `DynamicSourceInformation.sensorUID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | a reference to `SensorInformation`; "may designate a UID **OR** an LID for the sensor, but not both", and a document setting both is recorded at `attributes.reference_conflict` rather than resolved by preference |
| `DynamicSourceInformation.sensorLID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the local form of the same reference |
| `DynamicSourceInformation.sensorLocation` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | a `PositionPoints` holding **one** coordinate: where the sensor was. **Gap 14** in its most concrete form — the format states the observer's position and the CDM cannot relate an observation to an observer. Parked, and deliberately **never** used as the target's position |
| `DynamicSourceInformation.groupID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | a program-defined ID for a group of source blocks. Program-defined, so not a key |
| `DynamicSourceInformation.numDetections` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | how many detections were in the field of view |
| `DynamicSourceInformation.numReportedDetections` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | how many of them were reported. The pair is a **completeness measure** and is parked as one, the same job Legion's `total_count` versus `carried_samples` does |
| `DynamicSourceInformation.dynCFT` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `DynamicCFT`; the transforms every local coordinate in this frame resolves through |
| `DynamicSourceInformation.sourceMI` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `MotionImageryInformation`; its own table |
| `DynamicSourceInformation.sourceRadar` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `RadarInformation`; its own table |
| `DynamicSourceInformation.sourceESM` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `ESMInformation`, which has no attributes |

#### `DynamicCFT`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `DynamicCFT.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | "each instance of a `DynamicCFT` must have either a UID or an LID" — one with neither cannot be referenced and is recorded as such |
| `DynamicCFT.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | likewise |
| `DynamicCFT.cft` | `[1]` | `Position.lat` | `nits 1.0.0 · provisional` | the `CoordinateFrameTransformation` a local `Dynamics` or `Shape` resolves through. Named as reaching `Position` because when it resolves, it is what makes a local coordinate a geodetic one |

#### `CoordinateFrameTransformation`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `CoordinateFrameTransformation.from` | `[1]` | `Position.lat` | `nits 1.0.0 · provisional` | `CoordinateSystemType`, "restricted to `ECEF` and `ECI_J2K`". **`ECEF` transforms; `ECI_J2K` does not** — the local frame it anchors is attributes-only, per the coordinate settlement. A `from` naming a local, spherical or geodetic system is non-conforming and the CFT is treated as incomplete |
| `CoordinateFrameTransformation.translation` | `[1]` | `Position.lat` | `nits 1.0.0 · provisional` | exactly three doubles, `T1 T2 T3`. Any other count makes the CFT incomplete |
| `CoordinateFrameTransformation.rotation` | `[1]` | `Position.lat` | `nits 1.0.0 · provisional` | exactly nine doubles, `R1..R9` row-major. **The determinant is computed**: `A = Rᵀ L + T` is valid only when `\|det R\| = 1`, and the standard requires the true inverse otherwise. A singular matrix makes the CFT incomplete |

#### `MotionImageryInformation`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `MotionImageryInformation.frameBoundingBox` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | a `Polygon` bounding the field of view. **Not `Event.geometry`**: it describes the sensor's coverage, and emitting it as an event's geometry would paint the footprint as the thing observed |
| `MotionImageryInformation.frameNumber` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | arbitrary, and the standard says so: "the consumer is strongly encouraged to use the time stamps instead of frame number". Parked, never used to order anything |
| `MotionImageryInformation.niirs` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the producer's NIIRS estimate at image centre, per STANAG 7194. An image-quality rating, and **not** `Entity.confidence` |
| `MotionImageryInformation.vniirs` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the video equivalent, per MISP-2019.1. Likewise |
| `MotionImageryInformation.sea` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | solar elevation angle in degrees |
| `MotionImageryInformation.tea` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | target elevation angle in degrees |
| `MotionImageryInformation.gsd` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | ground sampling distance in metres, one to three values, where **one value is a geometric mean over all known dimensions** and two or three are per-axis. Parked with the count, because the meaning changes with it |
| `MotionImageryInformation.grd` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | ground resolved distance, same encoding, same reading. **Not `Position.accuracy_m`**: a resolution is not a 1-sigma position error |
| `MotionImageryInformation.useableFOV` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | a `Polygon`, "either pixel or real-world coordinates are permitted" and the `Shape` says which |
| `MotionImageryInformation.processedFOV` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the portion algorithms actually ran on. Parked, and it is the field that says where a *non*-detection means something |

#### `RadarInformation`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `RadarInformation.revisitIndex` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | STANAG 4607 field D2 |
| `RadarInformation.dwellIndex` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | 4607 field D3. Both are pointers into the source GMTI data; parked, and **not** resolved — reading the 4607 file is a different adapter |

#### `ESMInformation`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| *(no attributes)* | — | `Entity.attributes` | `nits 1.0.0 · provisional` | §2.5.16: "a placeholder for future capabilities, and currently does not contain any attributes". Present-and-empty is parked as such |

### Row set — the `Detection` / `Evidence` tree

A `Detection` is "a single instance of sensed information, which if hypothesized to be part of a
tracked object, serves as evidence of the tracked object", and the standard is explicit that
detections "can be reported independent of whether or not they are eventually associated with a
track point". So each becomes an **`Event`** of type `DETECTION` in its own right — the same
reading `adapters/legion.py` gives a Legion Event, reached from a class that says it out loud.

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Detection.uid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0 · provisional` | system `NITS_UID`. "If the data producer intends to associate detections with track points, they must supply each detection with either a UID or an LID" |
| `Detection.lid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0 · provisional` | system `NITS_LID`, and **only when `lidScopeUID` is present** — the composite, never the bare integer |
| `Detection.relTime` | `[0..1]` | `Event.observed_at` | `nits 1.0.0 · provisional` | resolved against the message base. Omitted means zero, which is the standard's rule and not an assumption |
| `Detection.centroid` | `[0..*]` | `Event.geometry` | `nits 1.0.0 · provisional` | a `PositionPoints` holding one coordinate. **Unbounded so the same centroid can be stated in several coordinate systems**, not so several detections can share a class — the standard says so. A `WGS_84` or transformable `ECEF` centroid becomes a `Point`; the rest are attributes-only |
| `Detection.outline` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | a `Shape`, unbounded for the same reason. **Gap 8** — the CDM has no extent, so an outline is parked whole even when its coordinate system would allow a polygon |
| `Detection.sensorUID` | `[0..1]` | `Event.payload` | `nits 1.0.0 · parked · provisional` | which sensor saw it. **Gap 14** |
| `Detection.sensorLID` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | likewise |
| `Detection.dynSrcUID` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | which frame or dwell it came from |
| `Detection.dynSrcLID` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | likewise |
| `Detection.confidence` | `[0..1]` | `Event.payload` | `nits 1.0.0 · parked · provisional` | a `Confidence`. **Gap 18** — parked whole, never reduced to a float |
| `Detection.source` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | a `TrackSource` scoped to this one detection |
| `Detection.esm` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | an `ESM`, which has no attributes |
| `Detection.im` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | an `Image`; its own table |
| `Detection.radar` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | a `Radar4607`; its own table |
| `Detection.sm` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | `SensorMeasurement`; its own table |
| *(derived)* | — | `Event.event_type` | `nits 1.0.0 · provisional` | `DETECTION`. The class is one |
| *(derived)* | — | `Event.severity` | `nits 1.0.0 · provisional` | `INFO`, with `payload.severity_basis` recording that NITS grades nothing. Legion's rule: the line sits at the source's own explicit alarm, and there is none |
| *(none)* | — | `Event.related_entities` | `nits 1.0.0 · provisional` | **empty.** A detection is evidence *for* a track point, and the association runs the other way — from `Evidence` inside a `TrackPoint`, not from the detection. Filling this would mean walking that reference backwards, which is a join. **Gap 19** |

#### `ESM`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| *(no attributes)* | — | `Event.payload` | `nits 1.0.0 · provisional` | §2.5.18: a placeholder with no attributes. Parked present-and-empty |

#### `Radar4607`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Radar4607.reportIndex` | `[1]` | `Event.payload` | `nits 1.0.0 · provisional` | 4607 field D32.1, the MTI report's index within the dwell |
| `Radar4607.hrrType` | `[1]` | `Event.payload` | `nits 1.0.0 · provisional` | 4607 field H23, an eight-value enumeration in a `byte` with 8–255 reserved. Parked as the integer **and** the wording; a reserved value goes to `unresolved_raw` |

#### `Image`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Image.pixelMask` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | a `PixelMask`. Image space; attributes-only, per the coordinate settlement |
| `Image.centroidPixel` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | `[row, column]`, **0-based**, and note the order is row-then-column while the `PIXELS` coordinate system is x-then-y. The two orders are opposite and both appear in this model; each is parked under a key naming which |
| `Image.color` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | three RGB bytes, the object's dominant colour, per MISB ST 0903.4 Target Color |
| `Image.chip` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | an `ImageChip`; its own table |

#### `ImageChip`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `ImageChip.type` | `[1]` | `Event.payload` | `nits 1.0.0 · provisional` | an IANA image media subtype; MISB ST 0903.4 limits it to `jpeg` and `png`. An XML attribute, not an element |
| `ImageChip.uri` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | a URI to a stored image. Parked and **never dereferenced** — the same refusal as `SensorInformation.url` |
| `ImageChip.image` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | the image itself, base64 in the XML syntax. **Parked whole**, never re-encoded and never transcoded: the never-drop rule does not have a size exemption, and a chip that is megabytes is a payload the caller chose to send. The standard notes XML "does not lend itself to inclusion of such binary data", which is a hint about `uri` and not a licence to drop `image` |

#### `SensorMeasurement`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `SensorMeasurement.quantity` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `MeasurementType`: `SNR`, `RADIANT_INTENSITY`, `RADIANCE`, `DIRECTIONAL_REFLECTANCE`. The units are fixed by the literal and are recorded with the value, because a bare number in W·sr⁻¹·m⁻² has been read as three things |
| `SensorMeasurement.method` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `MeasurementMethod`: `MEAN`, `MAX`. Parked, and it changes what the value means |
| `SensorMeasurement.value` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the measurement |
| `SensorMeasurement.uncertainty` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the producer's 1-sigma. **Not `Position.accuracy_m`** — an SNR uncertainty is not a position error, and the class is explicit that it covers sensor quantities and not derived ones like the length of an object |

### Row set — `TrackData`, `TrackSource`, `TrackSegment`, `TrackPoint`

#### `TrackData`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `TrackData.uid` | `[0..1]` | `Track.track_id` | `nits 1.0.0 · provisional` | **the track's identity**, via `ids.derive` with `kind="track"`, system `NITS_UID`. Also an `Entity.source_ids[].external_id`, and the fallback key for `Entity.entity_id` when no `TrackedObject` carries one — the `kind` argument is what keeps the two id spaces apart |
| `TrackData.lid` | `[0..1]` | `Track.track_id` | `nits 1.0.0 · provisional` | system `NITS_LID`, **only** as the `lidScopeUID` composite |
| `TrackData.trackSource` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | a `TrackSource` for the track as a whole, overridable per segment; its own table |
| `TrackData.segment` | `[0..*]` | `Track.samples[]` | `nits 1.0.0 · provisional` | `TrackSegment`. **All of them feed the one `Track`, in document order** — a segment is a subdivision of this track, not a track. `attributes.nits_segments[]` records each segment's own attributes against the half-open range of sample indices it covers |
| `TrackData.object` | `[0..*]` | `Entity.entity_type` | `nits 1.0.0 · provisional` | `TrackedObject`. **One `Entity` per `TrackData` regardless of how many objects are stated** — `Track.entity_id` is singular. Where several are present the standard says "the data consumer shall interpret the track data as applying to the set of multiple objects **as a group**", so the group is the entity, every instance is parked in full, and `attributes.tracked_object_count` says how many. Merging their attributes would be the consolidation rule, applied inside a document |

#### `TrackSource`

Eight reference lists, no data of its own. Every one of them is **gap 14** and, structurally,
**gap 19**.

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `TrackSource.sensorUID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | which sensors produced the detections behind this track |
| `TrackSource.sensorLID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the local form |
| `TrackSource.trackerUID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | which trackers |
| `TrackSource.trackerLID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the local form |
| `TrackSource.collectionUID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | which collections |
| `TrackSource.collectionLID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the local form |
| `TrackSource.productUID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | which products. The standard warns these **cannot** be resolved from the file at all — "the link … must be made with data external to this NITSRoot" — so they are parked as opaque identifiers by the format's own instruction |
| `TrackSource.productLID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | likewise |

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
| `TrackSegment.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | **not a `Track.track_id`** — a segment is a subdivision of a track and not a track. Parked at `attributes.nits_segments[].uid`. "The producer only needs to specify this value if they want the power to update previously-reported track segment", so its absence means the producer never intends to revise, which is itself worth recording |
| `TrackSegment.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | likewise, as the `lidScopeUID` composite where there is a scope |
| `TrackSegment.segmentSource` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | a `TrackSource` overriding the track's, for this segment's sample range only |
| `TrackSegment.confidence` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | **does not reach `Track.track_quality`** — see the note below. A `Confidence`, parked per segment. **Gap 18** |
| `TrackSegment.comment` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | free text; §2.1.1.4 forbids parsing it |
| `TrackSegment.status` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | `TrackStatus`. **Does not set `Entity.valid_to`** — see the note below. **Gap 16** |
| `TrackSegment.initiationReason` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `TrackInitiationReason`, used only when the status is `INITIATING` |
| `TrackSegment.terminationReason` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `TrackTerminationReason`, used only when the status is `TERMINATED` |
| `TrackSegment.tp` | `[0..*]` | `Track.samples[]` | `nits 1.0.0 · provisional` | `TrackPoint`, appended to the `TrackData`'s single `Track` in document order. **Zero is conformant**, and a segment with no points contributes no samples — a retraction-only one becomes an `Event` |

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
| `TrackPoint.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | **gap 16** — a sample has no identity in the CDM, so the point's own UUID is parked on the owning Entity keyed by sample index |
| `TrackPoint.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | likewise |
| `TrackPoint.relTime` | `[0..1]` | `Track.samples[].observed_at` | `nits 1.0.0 · provisional` | the integer count. "Required unless the value would be 0", and an omitted value **is** zero. The raw integer is parked so egress re-emits it rather than recomputing from the millisecond `Timestamp` |
| `TrackPoint.dynSrcUID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | which frame this point came from. **Gap 14**, **gap 16** |
| `TrackPoint.dynSrcLID` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | likewise |
| `TrackPoint.associatedDetection` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | whether the point has an associated detection. Note it is a **Boolean about association**, distinct from the `Evidence` that names which detection — so `TRUE` with no `Evidence` is a meaningful state and is recorded as one |
| `TrackPoint.processType` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `ProcessType`: `MANUAL`, `AUTOMATIC`. **Does not set `Position.position_source`** — it says whether a human or an algorithm created the point, not how the position was obtained. `MANUAL` in the CDM means a manually *entered* coordinate, which is a different claim |
| `TrackPoint.confidence` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | the producer's confidence that this point belongs to the segment. **Gap 18**, **gap 16** — parked whole |
| `TrackPoint.comment` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | free text, unparsed |
| `TrackPoint.outline` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | a `Shape` — the object's estimated outline at this instant. **Gap 8** in its strongest form: a per-instant footprint, and the CDM's `Entity` has no geometry at all |
| `TrackPoint.outlineObscured` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the obscured part of that outline, "a portion of the outline reported in `TrackPoint: outline`". Parked with the relationship recorded; a document carrying it without `outline` is non-conforming and is noted rather than repaired |
| `TrackPoint.nearestConfuser` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | metres to the nearest similarly-shaped object with similar dynamics. **Not `Position.accuracy_m`** — a confuser distance is a statement about ambiguity of *association*, not about the error of a fix, and the two are opposite kinds of number |
| `TrackPoint.nearestConfuserConfidence` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | a `Confidence` on that distance. **Gap 18** |
| `TrackPoint.sm` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | `SensorMeasurement`, per point. **Gap 16** |
| `TrackPoint.dynamics` | `[0..*]` | `Track.samples[].position` | `nits 1.0.0 · provisional` | `Dynamics`; its own table. The block that produces the sample's position, chosen by the coordinate-system preference order |
| `TrackPoint.evidence` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | `Evidence`; its own table. **Gap 19** |

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
| `Dynamics.cs` | `[1]` | `Position.lat` | `nits 1.0.0 · provisional` | `CoordinateSystemType`, and the attribute the entire coordinate settlement turns on. An XML attribute, not an element |
| `Dynamics.pos` | `[1]` | `Track.samples[].position.lat` · `Track.samples[].position.lon` · `Track.samples[].position.alt_m` | `nits 1.0.0 · provisional` | the centroid position, on every point of the history. Mandatory, which is why a velocity always has a position to build a local horizon at. Raw array parked verbatim at `attributes.nits_position` |
| `Dynamics.pos` *(last positioned point)* | `[1]` | `Entity.position` | `nits 1.0.0 · provisional` | the same value, once more, as the entity's current state — see the state note above. `Track.samples[].position.position_source` and `Entity.position.position_source` are both `ESTIMATED` |
| `Dynamics.vel` | `[0..1]` | `Entity.kinematics` | `nits 1.0.0 · provisional` | **gap 4, and the first source that answers it** — decomposed into `Kinematics.speed_mps`, `Kinematics.course_deg` and `Kinematics.climb_mps` for `ECEF`, for CFT-resolved `LOCAL_CARTESIAN`, and for `WGS_84` **only when the height axis is present**; parked whole for two-dimensional `WGS_84` and for the other three systems. The raw array is always parked. **And gap 16**: the CDM has one `Kinematics`, on the `Entity`, while NITS states a velocity at every point — so only the last positioned point's reaches it and the rest are parked per point |
| `Dynamics.acc` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the CDM models no acceleration in any frame, so this is parked whole regardless of coordinate system — as `adapters/legion.py` parks its own |
| `Dynamics.cov` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | a `CovarianceMatrix` over position, or position and velocity, or all three. **Gap 17** — parked whole, and never reduced to `Position.accuracy_m` |
| `Dynamics.cftUID` | `[0..1]` | `Position.lat` | `nits 1.0.0 · provisional` | the transform a local coordinate resolves through. Unresolvable within the payload makes the block attributes-only |
| `Dynamics.cftLID` | `[0..1]` | `Position.lat` | `nits 1.0.0 · provisional` | the local form |

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
| `Evidence.type` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `EvidenceType`: `DIRECT` (the object itself was seen) or `CIRCUMSTANTIAL` (only signs of it). An XML attribute |
| `Evidence.subtype` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `EvidenceSubtype`: `WAKE`, `DUST_PLUME`, `TIRE_TRACKS`, `SHADOW`, "other values defined by registration" — so an unknown literal is expected and is parked, never refused |
| `Evidence.uid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | needed only if the producer wants to revise the association later |
| `Evidence.lid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | likewise |
| `Evidence.detectionUID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | **the chain**: which detections support this track point. Parked as identifiers and **never resolved into the `Event` objects the detections became** — that is a join, and the CDM has no relation to hold it. **Gap 19** |
| `Evidence.detectionLID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | likewise |
| `Evidence.confidence` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | the producer's confidence in the association itself. **Gap 18** |

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
| `TrackedObject.uid` | `[0..1]` | `Entity.entity_id` | `nits 1.0.0 · provisional` | **the preferred key**, via `ids.derive`, system `NITS_UID`; also an `Entity.source_ids[].external_id` |
| `TrackedObject.lid` | `[0..1]` | `Entity.entity_id` | `nits 1.0.0 · provisional` | system `NITS_LID`, as the `lidScopeUID` composite only |
| `TrackedObject.description` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | **the near-miss name.** Parked at `attributes.tracked_object_description` and deliberately not at any name-like key — see the identity settlement. **Gap 1** |
| `TrackedObject.numberOfObjects` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | how many objects the track covers, "if two vehicles are so close to each other that they are indistinguishable". The CDM's `Entity` is one thing with no cardinality, so this is parked and the entity is not multiplied — splitting one indistinguishable pair into two entities would invent two positions from one |
| `TrackedObject.objectColor` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | RGB triples "listed in order from most dominant to least dominant" — the order is data and is preserved |
| `TrackedObject.confidence` | `[0..1]` | `Entity.confidence` | `nits 1.0.0 · provisional` | a `Confidence`, and the standard is explicit that it "applies to all attributes in this `TrackedObject` instance". Mapped to `Entity.confidence` **only** when `type` is `PROBABILITY` and `valid` is not `false`, on the same terms as `track_quality` above. **Gap 18** |
| `TrackedObject.dims` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | `[length, width, height, covLL, covLW, covLH, covWW, covWH, covHH]`. **Gap 8** — the CDM has no extent — and **gap 17** for the covariance half. Note the sentinels: an unmeasured dimension is `-1` and an inapplicable covariance is `0`, so `-1` is parked as `unavailable_fields` and never as a length |
| `TrackedObject.priority` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | producer-assigned, 1–255, **1 highest**. Parked and **not** mapped to `Event.severity`: a producer's collection priority is not an operational severity, and the inverted scale is exactly the kind of thing that gets read backwards |
| `TrackedObject.iffCode` | `[0..*]` | `Entity.source_ids[].external_id` | `nits 1.0.0 · provisional` | `IFFCode`; its own table. Only `MODE_S` with a hex-parseable value becomes a `SourceId` |
| `TrackedObject.objectClass` | `[0..*]` | `Entity.entity_type` | `nits 1.0.0 · provisional` | `ObjectClass`; its own table. Sets the entity type through the APP-6 table only, never the symbol |
| `TrackedObject.idSourceInformation` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `IDSourceInformation`; its own table. Reaches neither affiliation nor confidence |
| `TrackedObject.id1241` | `[0..1]` | `Entity.affiliation` | `nits 1.0.0 · provisional` | `ID1241`; its own table. The only path to `affiliation` in the whole model |
| `TrackedObject.exampleDetectionUID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | a detection that exemplifies the object. Parked as an identifier, never resolved. **Gap 19** |
| `TrackedObject.exampleDetectionLID` | `[0..*]` | `Entity.attributes` | `nits 1.0.0 · provisional` | likewise |

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
| `IFFCode.value` | `[1]` | `Entity.source_ids[].external_id` | `nits 1.0.0 · provisional` | "the code value transmitted by an IFF system", typed `String` with **no stated syntax for any mode** — see the ambiguity table. Becomes an `ICAO24` `SourceId` only for `MODE_S` and only when it parses as six unambiguous hex digits |
| `IFFCode.mode` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `IFFMode`: `MODE1`, `MODE2`, `MODE3`, `MODE4`, `MODE5`, `MODE_C`, `MODE_S`. **`MODE4` and `MODE5` never reach `affiliation`** — the CAT021 decline, second occurrence. `MODE_C` is a pressure altitude and never reaches `Position.alt_m` |

#### `ObjectClass`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `ObjectClass.table` | `[1]` | `Entity.entity_type` | `nits 1.0.0 · provisional` | `APP-6Table`, fourteen literals, all mapped in the table above |
| `ObjectClass.entity` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the APP-6 entity string |
| `ObjectClass.entityType` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | "required if the tracked object has a listed entity type" |
| `ObjectClass.entitySubtype` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | likewise for a subtype |
| `ObjectClass.sector1Modifier` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | optional APP-6 modifier |
| `ObjectClass.sector2Modifier` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | optional APP-6 modifier |
| `ObjectClass.code` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the 6-, 8- or 10-digit code, leading zeroes included, parked **as a string**. **Never composed into `Entity.symbol`** — see the identity settlement |

#### `IDSourceInformation`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `IDSourceInformation.idQualityNumber` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | "describes the quality of an ID Source Result", and typed **`String`** — so it is not a number the adapter may compare, rank or normalise, whatever it looks like |
| `IDSourceInformation.sourceDeclarationBinary` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | whether the source has a positive result, e.g. an IFF match. Parked; it does not reach `affiliation`, for the reason the class's own definition gives |
| `IDSourceInformation.sourceDeclarationExtension` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the precise declaration where the source says more than match/no-match. Encoding defined by AIDPP-01, a document this row set does not adopt |
| `IDSourceInformation.relTimeCreation` | `[1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | when the declaration was created. **Gap 13** — two times on one object and the CDM has no per-measurement time at all |
| `IDSourceInformation.relTimeExchange` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | when the message sender transmitted it. Deliberately **not** `Event.received_at`: that is a third party's transmission, not our receipt |
| `IDSourceInformation.idSourceNumber` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | an `IDSourceNumber`; its own table |

#### `IDSourceNumber`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `IDSourceNumber.sourceType` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the generic grouping of ID sources |
| `IDSourceNumber.sourceSubtype` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the subgroup |
| `IDSourceNumber.sourceDeviceClass` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | the precise ID source. All three are `String` and all three are defined by AIDPP-01; parked verbatim |

#### `ID1241`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `ID1241.identity` | `[0..1]` | `Entity.affiliation` | `nits 1.0.0 · provisional` | `Identity`, STANAG 1241 Ed. 5. **Gap 2** — six literals into four, mapped in the table above |
| `ID1241.identityAmplification` | `[0..1]` | `Entity.affiliation` | `nits 1.0.0 · provisional` | `IdentityAmplification`: `FAKER`, `JOKER`, `KILO`, `TRAVELER`, `ZOMBIE`. **`FAKER`, `JOKER` and `KILO` yield `FRIENDLY`**, overriding a contradicting `identity`, because Edition B defines all three as friendly in the first word; the exercise role is parked at `attributes.exercise_role`. `TRAVELER` and `ZOMBIE` are `SUSPECT` and set nothing — **gap 2**. See the settlement |
| `ID1241.identitySourceModality` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | a `ModalityType`, "transmitted only if the `identity` is provided". Parked; it says how the identity was reached, and the CDM has no provenance for an affiliation |
| `ID1241.environment` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `TrackEnvironment`: `LAND`, `SURFACE`, `SUB-SURFACE`, `AIR`, `SPACE`, `UNKNOWN`. **A domain, not a kind** — does not set `entity_type` |

### Row set — the analysis classes, all carried and none acted on

#### `ProcessedTrack`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `ProcessedTrack.type` | `[1]` | `Event.payload` | `nits 1.0.0 · provisional` | `ProcessedTrackType`: `FUSED`, `SMOOTHED`. An XML attribute |
| `ProcessedTrack.uid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0 · provisional` | system `NITS_UID` |
| `ProcessedTrack.lid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0 · provisional` | system `NITS_LID`, scoped |
| `ProcessedTrack.confidence` | `[0..1]` | `Event.payload` | `nits 1.0.0 · parked · provisional` | a `Confidence`, and the mechanism by which a producer **retracts** a processing claim: same ID, `valid = false`. Carried, never applied. **Gap 18** |
| `ProcessedTrack.inputUID` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | "two or more input track UUIDs". Parked as identifiers. **Not `related_entities`** — these are track ids |
| `ProcessedTrack.inputLID` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | likewise |
| `ProcessedTrack.outputUID` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | the output track. Parked; the adapter emits no combined track |
| `ProcessedTrack.outputLID` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | likewise |
| *(derived)* | — | `Event.observed_at` | `nits 1.0.0 · provisional` | **`TrackMessage.baseTime`.** This is the only class in the model with no time attribute of any kind, and `payload.observed_at_basis` says so rather than implying the producer stated an instant |
| *(derived)* | — | `Event.event_type` | `nits 1.0.0 · provisional` | `STATUS_CHANGE`. Not `TRACK_UPDATE`: nothing about a track's state was updated, a *relationship between* tracks was asserted |

Note the cardinality contradiction the standard carries here: `inputUID` is described as "two or
more input track UUIDs" and then, in the same cell, "all currently-defined `ProcessedTrack`s must
have **a single** input track specified as either a UID or LID". Recorded in the ambiguity table;
the adapter parks whatever count arrives and asserts neither.

#### `TrackLinkage`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `TrackLinkage.type` | `[1]` | `Event.payload` | `nits 1.0.0 · provisional` | `TrackLinkageType`: `MERGE`, `SPLIT`, `STITCH`. An XML attribute |
| `TrackLinkage.uid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0 · provisional` | system `NITS_UID` |
| `TrackLinkage.lid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0 · provisional` | system `NITS_LID`, scoped |
| `TrackLinkage.relTime` | `[0..1]` | `Event.observed_at` | `nits 1.0.0 · provisional` | "the time when the relationship started". Resolved against the message base; omitted means zero |
| `TrackLinkage.confidence` | `[0..1]` | `Event.payload` | `nits 1.0.0 · parked · provisional` | the retraction mechanism again. **Gap 18** |
| `TrackLinkage.preUID` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | tracks existing before the relationship. The counts are type-dependent — `SPLIT` `[1]`, `MERGE` `[2..*]`, `STITCH` `[1]` — and are **checked and recorded**, never enforced by dropping the linkage |
| `TrackLinkage.postUID` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | tracks existing after — `SPLIT` `[2..*]`, `MERGE` `[1]`, `STITCH` `[1]` |
| `TrackLinkage.preLID` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | the local forms, same counts |
| `TrackLinkage.postLID` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | likewise |
| *(derived)* | — | `Event.event_type` | `nits 1.0.0 · provisional` | `STATUS_CHANGE`, and `Event.related_entities` is empty — see the no-fusion settlement |

**A `MERGE` or `SPLIT` may legitimately reuse one identifier on both sides** — a motorcycle riding
into a trailer, or off one — so a `preUID` equal to a `postUID` is conformant and is **not** a
defect to flag. Recorded here because an adapter author's first instinct is to validate it away.

#### `MotionEvent`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `MotionEvent.type` | `[1]` | `Event.payload` | `nits 1.0.0 · provisional` | `MotionEventType`, seventeen literals. **Parked, not mapped to `EventType`** — see below |
| `MotionEvent.uid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0 · provisional` | system `NITS_UID` |
| `MotionEvent.lid` | `[0..1]` | `Event.source_ids[].external_id` | `nits 1.0.0 · provisional` | system `NITS_LID`, scoped |
| `MotionEvent.trackUID` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | the tracks involved. Parked as identifiers; **not** `related_entities`, which holds entity ids |
| `MotionEvent.trackLID` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | likewise |
| `MotionEvent.startRelTime` | `[1]` | `Event.observed_at` | `nits 1.0.0 · provisional` | **the one relTime in the model whose absence does not mean zero** — see below |
| `MotionEvent.endRelTime` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | parked. Its absence means "unknown **or** instantaneous", two different facts under one silence, and both are recorded as the one silence rather than one being chosen |
| `MotionEvent.confidence` | `[0..1]` | `Event.payload` | `nits 1.0.0 · parked · provisional` | a `Confidence`. **Gap 18** |
| `MotionEvent.region` | `[0..1]` | `Event.geometry` | `nits 1.0.0 · provisional` | a `Shape` for an ROI-type event. **Becomes a `Polygon` geometry** when its coordinate system is `WGS_84` or transformable `ECEF`, through the three polygon corrections; attributes-only otherwise. This and `tripwire` are the only two places in the model where a NITS shape reaches `Event.geometry` |
| `MotionEvent.tripwire` | `[0..1]` | `Event.geometry` | `nits 1.0.0 · provisional` | a `PositionPoints` whose vertices "do not form a closed polygon" — so a **`LineString`**, in vertex order, which the standard says "indicates how the tripwire should be drawn" |

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
| `Shape.dims` | `[1]` | `Event.geometry` | `nits 1.0.0 · provisional` | `Dimensionality`, literals `2` and `3`. Decides how the flat vertex array is split into tuples, so getting it wrong shifts every coordinate after the first |
| `Shape.cs` | `[1]` | `Event.geometry` | `nits 1.0.0 · provisional` | `CoordinateSystemType` for every vertex or ellipse parameter. The coordinate settlement decides whether a shape can be a geometry at all |
| `Shape.cftUID` | `[0..1]` | `Event.geometry` | `nits 1.0.0 · provisional` | "if the points are specified in a local coordinate system, then either the `cftLID` or `cftUID` is required" |
| `Shape.cftLID` | `[0..1]` | `Event.geometry` | `nits 1.0.0 · provisional` | the local form |

`Shape` is **abstract** and, per the CONVENTIONS, "an instance of the abstract class itself will
never be contained within a STANAG 4676 file"; a conformant XML document names the concrete type
with `xsi:type`. So a `Shape`-typed element with **no** `xsi:type` is non-conforming and is a
refusal quoting the element path — guessing between `Polygon` and `Ellipsoid` from the presence of
`vertices` would be inferring a type the document was required to state.

#### `Polygon`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Polygon.nRings` | `[0..1]` | `Event.geometry` | `nits 1.0.0 · provisional` | "shall not be omitted" when the count is not 1. Used as a **checksum on the `NaN` split**, not as the split itself; a disagreement is a refusal quoting both counts |
| `Polygon.vertices` | `[1]` | `Event.geometry` | `nits 1.0.0 · provisional` | one flat `DoubleArray` of all rings, tuples of `dims` values, rings separated by an all-`NaN` null point. Becomes a GeoJSON `Polygon` after the three corrections — axis order, winding, explicit closure — only from `WGS_84` or transformable `ECEF` |

#### `Ellipsoid`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Ellipsoid.center` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | a **9-element** array: `x y z covXX covXY covXZ covYY covYZ covZZ`, in the units of the `Shape`'s coordinate system. Sentinels matter — a 2-D ellipse sets `z` and `covZZ` to `-1`, and an unknown centre uncertainty sets all three diagonals to `-1`, so `-1` is never read as a coordinate or a variance |
| `Ellipsoid.ellipsoidParameters` | `[1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | a `CovarianceMatrix` giving the axis lengths and orientation. **Gap 17** |

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
| `PixelMask.pixelPolygon` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | vertices of a polygon in pixel space |
| `PixelMask.pixelRun` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | a bit mask as row and column runs |
| `PixelPolygon.nRings` | `[0..1]` | `Event.payload` | `nits 1.0.0 · provisional` | as `Polygon.nRings`, and the null point here is all **`-1`**, not `NaN` |
| `PixelPolygon.integerArray` | `[1]` | `Event.payload` | `nits 1.0.0 · provisional` | `[row_1, col_1, row_2, col_2, …]` — **row-then-column, which the standard notes is "the opposite of the order for the `PIXELS` coordinate space"**. Parked with the order named, because two opposite conventions in one model is how a mask lands transposed |
| `PixelRun.rs` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | each entry is `(start row, start column, run length across columns)` |
| `PixelRun.cs` | `[0..*]` | `Event.payload` | `nits 1.0.0 · provisional` | each entry is `(start row, start column, run length across rows)`. Row and column runs may overlap and both are kept |

Pixel indices are **0-based** throughout, per the CONVENTIONS, and the standard warns that
converting from a MISB ST 0903 source requires translating 1-based coordinates. The adapter
translates nothing: it reads NITS, where the base is 0, and records the base in the parked value
so a consumer never has to guess which convention a mask arrived in.

#### `IDData`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `IDData.stationID` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | STANAG 4545's OSTAID: "a sequence of 10 alphanumeric characters, **the last 2 of which must be spaces**". Parked with the padding intact — trimming it would produce a string that is not the OSTAID |
| `IDData.nationality` | `[1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | a `NationalityTrigraph`, three letters per APP-11(D). "In the case of a fused track, the nationality shall be that of the nation fusing the tracks" — so this names the producer, and the pair `stationID` + `nationality` is what "provides unique identification of any given STANAG 4676-capable system". **Gap 14**, and the single best evidence for it in any format here |

#### `CovarianceMatrix`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `CovarianceMatrix.covarianceType` | `[1]` | `Entity.attributes` | `nits 1.0.0 · provisional` | `CovarianceType`: `POS3D` (6 elements), `VEL3D` (21), `ACC3D` (45), `POS2D` (3), `VEL2D` (10), `ACC2D` (21). An XML attribute. **The element count is a checksum**: a matrix whose value count disagrees with its type is a refusal quoting both |
| `CovarianceMatrix` *(core class value)* | `[1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | the values themselves — "only the diagonal and upper-right triangle elements … reported Left-to-Right, Top-to-Bottom". The class's own content rather than a named attribute, like `UUID`'s. Parked verbatim, ordering intact. **Gap 17** |

#### `Confidence`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `Confidence.type` | `[1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | `CertaintyStatisticType`: `HUMAN_INSTINCT`, `P-VALUE`, `PROBABILITY`, `T-STATISTIC`. An XML attribute. **The attribute that makes the value uninterpretable without it** — see gap 18 |
| `Confidence.value` | `[1]` | `Entity.confidence` | `nits 1.0.0 · provisional` | 0–100. Reaches `Entity.confidence` as `value / 100` **only** when `type` is `PROBABILITY` and `valid` is not `false`; otherwise `None` with the whole block parked |
| `Confidence.sourceReliability` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | 0–100, a **separate** measure of the source, and the standard forbids folding it in: "the data producer must not factor in the reliability of the source into its calculation of its confidence in the value". The adapter must not either, and the CDM has one float — **gap 18** |
| `Confidence.valid` | `[0..1]` | `Entity.attributes` | `nits 1.0.0 · parked · provisional` | the **retraction** flag. `false` means the producer has withdrawn the associated data. Carried verbatim and never applied; a value it invalidates is still parked, because applying a retraction means holding what it retracts. **Gap 18** |

The standard's own analogy is worth carrying: `value` "is intended to be analogous to credibility
(of information) criteria specified in AJP 2.1, whose values range from 1 to 6", and
`sourceReliability` to "reliability (of source) criteria … whose values range from A to F". That
is the classic two-axis intelligence evaluation, and the CDM has one axis.

#### `PositionPoints`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `PositionPoints.dims` | `[1]` | `Event.geometry` | `nits 1.0.0 · provisional` | `Dimensionality`, 2 or 3; splits the flat array |
| `PositionPoints.cs` | `[1]` | `Event.geometry` | `nits 1.0.0 · provisional` | `CoordinateSystemType` common to every point |
| `PositionPoints.points` | `[1]` | `Event.geometry` | `nits 1.0.0 · provisional` | vertices "in the order in which they should be drawn", and **unlike a polygon they do not form a closed shape**. A single point becomes a `Point`, several become a `LineString`, and neither is ever closed |
| `PositionPoints.cftUID` | `[0..1]` | `Event.geometry` | `nits 1.0.0 · provisional` | required when the points are local |
| `PositionPoints.cftLID` | `[0..1]` | `Event.geometry` | `nits 1.0.0 · provisional` | the local form |

#### `UUID`

| NITS | Card | CDM field | Status | Notes |
|---|---|---|---|---|
| `UUID` *(core class value)* | `[1]` | `Entity.source_ids[].external_id` | `nits 1.0.0 · provisional` | a 128-bit identifier per ITU-T X.667 / ISO/IEC 9834-8. In the XML syntax it is **`xs:base64Binary`, 22 characters**, not the 36-character canonical form — a guide-only fact, and one an adapter emitting canonical UUIDs would fail schema validation on |
| `UUID.gidp` | `[0..1]` | `Entity.source_ids[].external_id` | `nits 1.0.0 · provisional` | the IC Identifier guide prefix. When present the identifier is the composed `guide://<gidp>/<value>`, and **the bare UUID is a different identifier** — keying on it would merge two objects that the producer distinguished |

### Row set — egress, CDM back to a NITSRoot document

Bidirectional where the protocol allows, and here the protocol allows a great deal because the
model is richer than the CDM: almost everything egress needs is either a canonical field or a
parked value it wrote itself on the way in.

| CDM | NITS | Status | Notes |
|---|---|---|---|
| `Track.samples[].observed_at` | `TrackPoint.relTime` | `nits 1.0.0 · egress · provisional` | **re-emitted from `attributes.nits_times`** for a round trip, never recomputed. For a CDM object of other origin, `relTimeIncrement` is set to `0.001` s so that the CDM's own three-decimal `Timestamp` is exactly representable as an integer count, and `relTime` is whole milliseconds since `baseTime` — exact, with no rounding anywhere |
| `Track.samples[].observed_at` | `TrackMessage.baseTime` | `nits 1.0.0 · egress · provisional` | the earliest sample instant in the message, which is what the standard asks for: "this should be the earliest time among all the time stamps in the constituent parts" |
| `Track.samples[].position.lat` · `Track.samples[].position.lon` · `Track.samples[].position.alt_m` | `Dynamics.pos` with `cs = WGS_84` | `nits 1.0.0 · egress · provisional` | latitude, longitude, height — **latitude first**, the axis order transposed back. A sample with no `alt_m` emits a two-component position, which is the all-or-nothing rule respected rather than a zero invented |
| `Kinematics.speed_mps` · `Kinematics.course_deg` · `Kinematics.climb_mps` | `Dynamics.vel` | `nits 1.0.0 · egress · provisional` | recomposed into the `WGS_84` angular rates using the same two named constants, or re-emitted verbatim from the park where the object came from NITS |
| `Track.track_id` | `TrackData.uid` | `nits 1.0.0 · egress · provisional` | from the park where there is one; otherwise a fresh v5 UUID over the CDM id, with `ProductIdentification.id` naming this system as the issuer. **Segmentation is restored from `attributes.nits_segments[]` where the object came from NITS**, and otherwise the whole history is emitted as a single `TrackSegment` — which §2.5.25 permits outright: "if the data producer deems it unnecessary to break a track into multiple track segments, then all track points of the track can be included is a single `TrackSegment` object" |
| `Track.entity_id` | `TrackedObject.uid` | `nits 1.0.0 · egress · provisional` | on the same terms |
| `Entity.affiliation` | `ID1241.identity` | `nits 1.0.0 · egress · provisional` | `FRIENDLY` → `FRIEND`, `HOSTILE` → `HOSTILE`, `NEUTRAL` → `NEUTRAL`, `UNKNOWN` → `UNKNOWN`. **`ASSUMED_FRIEND` and `SUSPECT` are never emitted** — the CDM cannot hold them, so it cannot state them, and re-widening the collapse would invent a judgement |
| `Entity.entity_type` | `ObjectClass.table` | `nits 1.0.0 · egress · provisional` | only where the ingest parked an APP-6 block, which is re-emitted verbatim. **A CDM entity of other origin emits no `ObjectClass` at all**: `code` is `[1]` and there is no honest code to write |
| `Entity.confidence` | `TrackedObject.confidence` | `nits 1.0.0 · egress · provisional` | as `value = round(confidence × 100)` with `type = PROBABILITY`, which is the only type the CDM's float can honestly claim |
| `Event.geometry` | `MotionEvent.region` / `.tripwire` | `nits 1.0.0 · egress · provisional` | the three polygon corrections run in reverse: rings re-wound to the NITS convention, axis order transposed, the explicit closing position dropped, rings joined by `NaN` null points and `nRings` recomputed |
| `Entity.attributes` | *(everything parked)* | `nits 1.0.0 · egress · provisional` | every parked block is restored to the class and attribute it came from. This is what makes the round trip worth claiming at all |
| `Entity.attributes` | `originatorConfidentialityLabel` | `nits 1.0.0 · egress · provisional` | verbatim from the park for a round-tripped object; from the deployment's configured label, logged as such, for a CDM-native one; **a refusal when neither exists** — the three paths in the classification settlement. A silent `UNCLASSIFIED` is forbidden |
| *(the injected clock)* | `NITSRoot.msgCreatedTime` | `nits 1.0.0 · egress · provisional` | when we wrote the file. The one value egress invents, and it is the same clock `received_at` uses |
| *(constant)* | `NITSRoot.nitsVersion` | `nits 1.0.0 · egress · provisional` | `"B.2"` |
| *(constant)* | `NITSRoot.profile` | `nits 1.0.0 · egress · provisional` | `STANDALONE`, always — see the profiles settlement |

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
- **Merge two parked NITSRoot contexts under one root.** A refusal, and a NARROW one. §2.1.1.2.3
  says that when two objects' `lidScopeUID` values differ "the same local ID value can be used to
  represent different things", so a verbatim round trip of two documents into one would make
  identifiers from two scopes collide silently — and re-scoping them would destroy the cross-file
  correlation those identifiers exist to provide. **It does not refuse a consolidated picture.**
  CDM-native egress from any number of sources mints fresh identifiers: the native path keys on
  the CDM's own UUIDs and emits no local ID at all, so `lidScopeUID` — "required if local IDs are
  found in the object" — is not needed and no collision is possible. That is a mint, not a merge,
  and it is the path the refusal points a caller at.
- **Emit an invented confidentiality label.** A configuration-supplied one is not invented — it is
  declared, logged and attributable to the deployment. A defaulted one is invented, and it is
  forbidden. Stated three times in this row set because it is the one failure whose consequence is
  not a wrong pixel on a map.

### What the adapter fills that NITS does not state

| NITS | CDM field | Status | Notes |
|---|---|---|---|
| *(none)* | `Event.received_at` | `nits 1.0.0 · provisional` | the injected clock. Never `msgCreatedTime`, which is when the producer wrote the file, and never `IDSourceInformation.relTimeExchange`, which is when a third party sent a declaration |
| *(the deployment declaration)* | `Entity.source.synthetic` | `nits 1.0.0 · provisional` | **no payload field sets this**, and `CollectionInformation.essence` in particular does not — it is parked, and a parked essence contradicting the declaration is a logged refusal rather than a flip in either direction. The CAT021 `SIM` rule and the Legion `EXERCISE_*` rule, held as a rule |
| *(configuration, where the object is CDM-native)* | `Entity.attributes` | `nits 1.0.0 · provisional` | `attributes.confidentiality_label_basis` — which of the three egress label paths applied. A configured label is declared and logged; a defaulted one is forbidden |
| *(none — NITS states no severity anywhere)* | `Event.severity` | `nits 1.0.0 · provisional` | `INFO`, with `payload.severity_basis` recording that the format grades nothing, including its own `COLLISION` motion event. `TrackedObject.priority` is a collection priority, not an operational severity, and is parked |
| *(none)* | `Event.event_type` | `nits 1.0.0 · provisional` | `DETECTION` for a `Detection`; `STATUS_CHANGE` for a `MotionEvent`, a `TrackLinkage`, a `ProcessedTrack` and a retraction-only segment. **Never `TRACK_UPDATE`**, because in this format a track update is a `Track`, not an `Event` |
| *(derived)* | `Entity.symbol` | `nits 1.0.0 · provisional` | from the affiliation via `symbology.sidc_from_affiliation`; `attributes.symbol_basis` says so, and says that an APP-6 code was present and not composed into a SIDC where one was |
| *(derived)* | `Position.position_source` | `nits 1.0.0 · provisional` | `ESTIMATED`, always, with `attributes.position_source_basis` naming the sensor modality where it resolved and recording why the modality did not refine the field |
| *(the earliest point instant)* | `Entity.valid_from` | `nits 1.0.0 · provisional` | else `TrackMessage.baseTime` for a `TrackData` with no points; `attributes.valid_from_basis` names which |
| *(none)* | `Entity.valid_to` | `nits 1.0.0 · provisional` | `None`, even for a `TERMINATED` segment — four of the six termination reasons say the sensor stopped seeing the object, not that it ceased to exist |
| *(none — NITS carries no checksum of any kind)* | `Entity.attributes` | `nits 1.0.0 · provisional` | `attributes.integrity_basis`, recording that the document passed schema-shaped structural checks and nothing more. A consumer comparing a NITS contact with a CAT021 one should be able to see which of the two was checked, and neither was |
| *(measured)* | `Entity.attributes` | `nits 1.0.0 · provisional` | `attributes.unavailable_fields` — fields the source explicitly stated it does not know: a `dims` component of `-1`, a two-component `pos` under the all-or-nothing rule, a `MotionEvent` with no `startRelTime`. **An omitted `relTime` is not in this list**, because the standard defines that absence as zero |
| *(measured)* | `Entity.attributes` | `nits 1.0.0 · provisional` | `attributes.unresolved_raw` — values read and not usable: an unrecognised enumeration literal, a reserved `hrrType`, a `CovarianceMatrix` whose element count disagrees with its type, a coordinate in an attributes-only system |
| *(measured)* | `Entity.attributes` | `nits 1.0.0 · provisional` | `attributes.unresolved_references` — references that do not resolve inside this payload, each naming the referring attribute and the class it must point at. **A different fact from both lists above**, and the DATASTREAM profile is why it exists |
| everything unmapped | `Entity.attributes` | `nits 1.0.0 · provisional` | `attributes.source_extras`, structure and namespace intact — and here that is not a formality: the schema declares open content on every complex type, so extension elements are expected rather than exceptional |

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
| 12 | **The ratification wrapper names no version, and it predates the version this row set is against by five months.** STANAG 4676 Edition 2 was promulgated **13 October 2021** and its STANDARD line reads "AEDP-12, Edition B" with no version, in both the English and the French column. The pinned AEDP is **Edition B, Version 2, MARCH 2022**. Neither AEDP in the pinned set carries a NATO Letter of Promulgation — both reserve that page for a *national* letter — so **no promulgation date for Edition B Version 2 is stated in any pinned document**, only the month on its title page. Contrast STANAG 4607, whose cover names "Edition A, version 1" explicitly and whose AEDPs both carry a NATO Letter of Promulgation dated 16 February 2024 | none for the parse, and it is why this section's target row now states Version 2 on the AEDP's own authority rather than the wrapper's. The consequence is for *citation*: a claim that this row set is against "the ratified Edition B" would be a claim the wrapper cannot support past October 2021, and any Version 2 promulgation date is a premise from outside the pinned set. Recorded, and the prose is left as the documents have it |
| 13 | **The guide describes the XSD's status two incompatible ways, one page apart.** §D.1, printed page D-1 (PDF page 156): "The schema is provided as a guide and may not be suitable for all programs. It is used for conformance testing." §D.6, printed page D-2 (PDF page 157), and Edition B §B.6, printed page B-4 (PDF page 144), identically: "The XML schema defined within the standard is **normative for conformance only**. Implementations may use any method to write the XML formatted data as long as that resulting data conforms to the schema." A schema that is normative for conformance and a schema that is "provided as a guide" are two different objects, and the second sentence is the one that appears in the standard as well | none, and the park survives either reading — which is the point of recording it rather than choosing. Under §D.6 the schema is what conformance means and nothing here can claim it; under §D.1 the schema is advisory and *still* the only thing that fixes the element names, so the provisional binding is unaffected. A park that needs only one of two contradictory sentences to be true is the kind worth keeping. Found on the 2026-08-23 re-verification, in the same pass that corrected the encoding settlement's recorded reason. **Neither pole of this contradiction is a claim that some *third* artefact is normative**: the guide nowhere says the data model, or anything else, is "the normative reference" — the phrase does not occur in it — so the ambiguity is about the XSD's status and not about which document wins |
| 14 | **§2.1.1.1 names the wrong edition in its own second sentence.** The clause settlement 1 quotes reads "Upon analysis of the new features needed for STANAG 4676 **Ed. 1**, along with implementation concerns related to the large size of STANAG 4676 Ed. 1 data, it was determined that the best course of action to ensure that STANAG 4676 Ed. 2 met all of the functional and data size requirements was to re-architect …". The features being analysed are Edition 2's; Edition 1 is the thing whose *size* was the concern. So of the sentence's two references to Ed. 1 the first is wrong and the second is right, which is why it reads as prose — a reader who notices one of them notices the wrong one half the time | none — the operative sentence is the one before it, "STANAG 4676 Ed. 2 is incompatible with STANAG 4676 Ed. 1", which is unambiguous and is what settlement 1 rests on. Recorded because settlement 1 quotes this passage with an ellipsis, and a reader who opens §2.1.1.1 to check the quote will hit the slip and wonder whether the ellipsis hid it |

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
| **The XML syntax binding** | **blocked, not declined** | Element names, attribute-versus-element and the base64 UUID form all depend on the XSD, which the pinned edition does not fix: guide §D.1.1 has the Custodian re-issuing it on its own revision axis, with its revision number and date inside the file, so "the schema for Edition B Version 2" names no single artefact — and it is distributed through access-controlled channels besides. Re-based on §D.1.1 on 2026-08-23; the previous reason named only the distribution. 1.0.0 ships a **provisional** binding through one table, `ELEMENT_NAMES`, and every row above carries `· provisional` so the status column says so on its own |
| **XSD validation of an emitted document** | **blocked, with a stated exit condition** | The schema "is normative for conformance" (Ed B §B.6), so nothing here can claim a document it emits is conformant — only that every value it re-emits equals the value it read. **Exit condition, in order** — revised 2026-08-23, because a SHA-256 alone under-identifies a document that versions itself: obtain `stanag4676.xsd` and `stanag4774_confidentialitymetadatalabel.xsd`, from **either** DiWEB through a NATO JCGISR national representative (Ed B §B.5) **or** the APAN 4676 Community (guide §D.1) — and if both, hash both, because neither document says the two channels hold the same file; pin them as `fixtures/nits/spec/xsd_pin.json` the way `sac_pin.json` pins the ASTERIX allocation list, recording **the schema's own revision number and revision date from inside the file** — the two fields the text guarantees — alongside the SHA-256 and the change log §D.1.1 also names, since the Custodian re-issues the XSD independently of the AEDP edition and a hash with no revision number cannot say which revision it is. The citation is **guide §D.1.1, printed page D-1 (PDF page 156)**, which is about the **XSD**; §C.1.1 on printed page C-1 is the parallel section about the **data model files** and gives revision number and date without a change log, so a pin built from §C.1.1 would record the wrong artefact's metadata; fill `ELEMENT_NAMES` from the schema and re-run the twin test, which fails on every name that moved; add a validation step to the fixture build so each `.nits.xml` is checked against the schema; and drop `· provisional` from the status column in the same commit. Until all five are done the qualifier stays, and `test_every_nits_row_carries_the_provisional_qualifier` fails the build if one is removed early |

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

## STANAG 4607 / AEDP-4607 — NATO Ground Moving Target Indicator Format (GMTIF), ingest

Implemented by `adapters/gmtif.py` (bidirectional), on the Annex C wire codec in
`adapters/gmtif_codec.py`. Ingest translates one GMTI packet into an `Entity` and a `Track` for the
platform, an `Entity` and a `DETECTION` `Event` per target report, and a `STATUS_CHANGE` `Event`
per Free Text, Test and Status or Processing History Segment; egress turns them back into one
packet, byte for byte.

**Every row below was written and reviewed as a specification BEFORE any code existed**, with
`not yet` in the status column, exactly as the Legion, CAT021 and STANAG 4676 row sets were. The
markers now read `gmti 1.0.0` because the adapter runs them, and that difference is the whole
reason the status column exists. Nothing in the mapping moved when the code landed; what the code
found were two contradictions in the standard, recorded as ambiguities 15 and 16 below, and one
place where a row's own rule had to be narrowed to keep a packet the guide draws representable.

**Seven amendments were applied on review, before any code, and each is stated where it applies
rather than as a footnote — and every one of them is now executed and pinned by a test.** Two overturned a Phase 1 reading — the rotator classes no
longer map to `FACILITY` (1), and `P7` no longer writes `source.synthetic` even when it agrees with
the deployment declaration (2). Three tightened one that stood: the platform `Track` now parks a
time basis per sample and rests on the standard's field definitions rather than a guide annex (3),
the caller-supplied reference date carries per-instant provenance and is refused rather than
preferred when the wire contradicts it (4), and reserved segments are skip-**and-record** on
§3.2.1 and §3.2.2 rather than on a stale validation annex (5). One re-based the grounds of a
decline after running a discrepancy to its source (6). One recorded a divergence from a shipped
adapter rather than resolving it (7). The two overturned readings are visible in the rows they
changed, because a reversal nobody can see in the document is a reversal nobody can review.

This is a **binary, byte-aligned, message-oriented wire format**, not a UML model and not an XML
syntax. It has a packet header, a segment header, ten defined segment types and two nested record
arrays, and every field of every one of them has a row here, with the standard's own
Mandatory/Conditional/Optional marking and its own units. 212 field rows across 13 tables, plus a
table accounting for every reserved segment type code. Nothing is omitted silently: the CAT021
rule.

**It is also the first format in this document whose targets are detections rather than tracks**,
and that is the settlement the row set turns on. A GMTI target report is one radar return with a
position, a radial velocity component and a classification. There is no track number, no report
continuity across dwells, and no identifier for a real target anywhere in the core segments. So
this adapter emits **no `Track` for any target, ever** — see settlement 5.

### The pin

STANAG 4607 is a ratified NATO standardization agreement, so like CAT021 and STANAG 4676 and
unlike Legion it does not need a hash to be trustworthy. The hashes are recorded anyway, for the
same reason: an edition number names a **document** and a SHA-256 names the **copy that was
read**.

| | |
|---|---|
| Ratification wrapper | **STANAG 4607 Edition 4**, 16 February 2024, promulgated by the NATO Standardization Office (NSO(NAFAG)0232(2024)JCGISR/4607). Supersedes STANAG 4607 Edition 3 of 14 September 2010. Names exactly one standard: "AEDP-4607, Edition A" |
| SHA-256 (wrapper) | `e102f47c51e74d26f61f02947df1228330e0ab6176b4b55c28447cf74574751b`, 558 866 bytes, 6 pages, `fixtures/gmti/spec/nato-stanag-4607-edition-4.pdf` |
| **The target** | **AEDP-4607, NATO Ground Moving Target Indicator Format (GMTIF), Edition A Version 1, February 2024**. Every mapped field below cites this document. Carries its own **NATO Letter of Promulgation, 16 February 2024** — the wrapper's date exactly — which closes the covering chain from the AEDP's side: "AEDP-4607, Edition A, Version 1 … is promulgated herewith. The agreement of nations to use this publication is recorded in STANAG 4607" |
| SHA-256 (target) | `13f054c2bced1444aac9b5e85682b0b14b82f1d83988bf183f9324095c11a5d9`, 1 724 707 bytes, 104 pages, `fixtures/gmti/spec/nato-aedp-4607-edition-a-v1.pdf` |
| Implementation Guide and validation | **AEDP-4607.1, NATO GMTIF Implementation Guide, Standards Related Document (SRD), Edition A Version 1**, 212 pages. Carries the test and validation procedures (Annex G), the coordinate and position-recovery arithmetic (Annex E), the Registry of Controlled Extensions (Annex L) and the change history (Annexes M and N). Its own **NATO Letter of Promulgation is also 16 February 2024**, "approved in conjunction with AEDP-4607", and it "supersedes AEDP-07, Edition 2, which shall be destroyed" — see ambiguity 19 |
| SHA-256 (guide) | `877f9b6f1bbcd1ac76cddca751a7222deb5bcf8c8061e6530657eb68f655ed94`, 3 010 604 bytes, 212 pages, `fixtures/gmti/spec/nato-aedp-4607-1-edition-a-v1.pdf` |
| **The Controlled Extension field definitions** | **NOT PINNED, and not obtainable here.** Annex L.3.1 registers five *approved* extension segment types — 128 Advanced Dwell, 129 Advanced Job Definition, 130 Advanced Platform Location, 131 Target Centroid, 132 Releasability — and §L.4, the section that gives their field tables, reads **"(TO BE PROVIDED)"**. **Re-read in the promulgated Edition A Version 1 copy on 2026-08-23: unchanged.** See the blocker row in the declines table |
| Superseded, and deliberately not read | AEDP-7 Edition 2, the previous implementation guide, which AEDP-4607.1 replaces. Unlike the STANAG 4676 row set, which pinned the 2014 edition as compatibility context and read it for the edition delta, **nothing here was read from AEDP-7**: the delta that matters is recorded inside the pinned guide itself, in Annexes M and N |

**Pin re-verification, 2026-08-23 — the three copies in `fixtures/gmti/spec/` are the copies the row
set was written from.** Each SHA-256 above was recomputed from the file on disk, each byte count and
page count re-measured, and each title page re-read for its printed identity. All three match, so
nothing below is re-based:

| Filename | Title-page identity, as printed | Bytes | Pages |
|---|---|---|---|
| `nato-stanag-4607-edition-4.pdf` | "STANDARDIZATION AGREEMENT / STANAG 4607 / NATO GROUND MOVING TARGET INDICATOR FORMAT (GMTIF) / EDITION/ÉDITION 4 / 16 February/février 2024" | 558 866 | 6 |
| `nato-aedp-4607-edition-a-v1.pdf` | "NATO STANDARD / AEDP-4607 / NATO GROUND MOVING TARGET INDICATOR FORMAT (GMTIF) / Edition A, Version 1 / FEBRUARY 2024" | 1 724 707 | 104 |
| `nato-aedp-4607-1-edition-a-v1.pdf` | "STANDARDS RELATED DOCUMENT / AEDP-4607.1 / NATO GROUND MOVING TARGET INDICATION FORMAT (GMTIF) - IMPLEMENTATION GUIDE / Edition A, Version 1 / FEBRUARY 2024" | 3 010 604 | 212 |

**The basis is confirmed, and the confirmation is a clause comparison rather than an edition
string.** What the pin records as the governing text is, verbatim, "**AEDP-4607, NATO Ground Moving
Target Indicator Format (GMTIF), Edition A Version 1, February 2024**. Every mapped field below
cites this document" — and the pinned copy *is* that document, not a successor to it. The covering
chain is stated by both ends independently, which is what makes it a chain and not an assumption:
the STANAG's AGREEMENT/STANDARD line reads "AEDP-4607, Edition A" and its INTEROPERABILITY
REQUIREMENTS paragraph names the version — "The data format described in the associated AEDP-4607,
Edition A, version 1" — while the AEDP's own Letter of Promulgation points back, "The agreement of
nations to use this publication is recorded in STANAG 4607". So the wrapper's version-less STANDARD
line is not an ambiguity here: the same cover names Version 1 two paragraphs earlier.

**No substantive divergence was found, and these are the clauses that were compared** — every one a
clause a settlement or a row set rests on, read in the pinned copy and matched to what this section
already asserts about it: §2.2's "no provision or need within AEDP-4607 for Start- or End-of Message
characters"; §3.1.7's "synthesized (a mix of real and simulated data)"; §3.1.8's "uniquely
identified within the set of platforms it owns"; §3.1.10's "then the Job ID in the Packet Header
shall be 0 (hex 0x00)"; §3.2.1's "values 4, 7, 8, 9, 11, 14-100, and 103-255 are reserved for
future use" against Table 3-6's split of `103-127` from `128-255 = Reserved for Extensions`
(ambiguity 4, still live); §3.2.2's "the number of bytes in this header and the data segment which
follows this header"; Table 3-4's NATO releasability codewords, `0x0002 EUFOR` and `0x0100 THE
PUBLIC` among them, against guide Annex G's US-flavoured list (ambiguity 1, still live); §3.4.6's
"the temporal center of the dwell" against §3.15.1's "the time the report is prepared" (settlement
5's two kinds of instant); §3.4.10's deferral of the latitude scale factor to the "Implementation
Guidance Document for this standard"; Table 3-11's `140 = Large Multiple-Return, Simulated Land
Target` / `142 = Tagging Device` / `143 = Reserved` against §3.4.32.16's and §3.4.32.17's prose
citing `140` (ambiguity 3, still live, and the value in the pinned table is 142 exactly as recorded);
and both truth tags' condition, "sent only if the MTI Target in the Report is simulated or a tagging
device is detected". Ambiguities 1, 3 and 4 are re-confirmed as present in the promulgated text
rather than closed — they are the standard's, not a stale reading of it.

**Three documents, and the third is not decorative.** The standard defers two things to the guide
in as many words — the choice of the latitude and longitude scale factors ("shall be chosen in
accordance with the guidance given in the Implementation Guidance Document", §3.4.10) and the
tutorial coordinate systems — and the guide supplies four things that the standard does not state
at all and that this row set depends on:

- **The delta-position reconstruction is integer arithmetic, and longitude wraps.** Guide §E.7
  gives the recovery in the *encoded* domain with the operators subscripted `S32` and `I32`, and
  requires that "the ANSI Standard C conventions for unsigned integer arithmetic be adhered to …
  that overflow from addition or underflow from subtraction yield a result that is congruent
  mod 2^n". Nothing in the standard says this, and an adapter that reconstructed in degrees would
  get the prime-meridian case wrong. Settlement 6.
- **The provenance of the truth-tag "140".** Guide Annex M is a change record, and it is where the
  standard's most consequential stale cross-reference becomes traceable rather than merely wrong:
  M-9 shows `Tagging Device` being *added to the classification table at value 140*, and the very
  next item, M-10, is the errata that *introduced* the battery-strength prose citing 140 and
  widened `D32.16`'s condition to "simulated **or a tagging device is detected**". The two were
  written as one coherent pair. Ambiguity 3 below follows the trail from there.
- **Annex G is read for one thing only: as evidence against itself.** Amendment 5 struck every
  citation of Annex G as *authority*. Its own reference list cites "STANAG 4607, Edition 2,
  2 August 2007" and AEDP-7 Edition 1, so it was carried forward without being re-based on Edition
  A — which is how it comes to publish a `P6` codeword table contradicting the standard's
  (ambiguity 1). A row set cannot discredit an annex in one settlement and lean on it in another,
  so nothing here rests on it. **The rest of the guide is used where it is not stale** — §E.7,
  §D.2, §E.8, Annex L, Annexes M and N and the FAQ — and each use is cited to its own section.
- **Negative information is the point of the format, in its own words.** Guide §D.2: "the fact
  that the radar has looked at a particular area and found no targets can be just as important as
  receiving targets in an area." That sentence is **gap 22**.

**Where the guide and the standard disagree, the standard wins** — and they do disagree, in one
place that matters enough to have its own settlement. Guide Annex G's Table G-1 gives a
**completely different codeword list for P6** from the standard's Table 3-4: same sixteen bit
values, US-flavoured caveats (`NOCONTRACT`, `ORCON`, `PROPIN`, `WNINTEL`, `REL 4-EYES`) against
the standard's NATO releasability set (`EU`, `EUFOR`, `ISAF`, `KFOR`, `PFP`, `THE PUBLIC`). The
cause is visible in the same annex: Annex G's own reference list cites "STANAG 4607, Edition 2,
2 August 2007" and "AEDP-7, Edition 1, April 2008", so the validation annex was carried forward
without being re-based on Edition A. The consequence is settlement 3.

### Settlement 1 — Edition A Version 1 is the only target, and P1 is the gate

`P1` Version ID is two alphanumeric characters, `"mn"`, where `m` is the edition as a number
(edition A = 4, B = 5) and `n` is the version. **`"41"` is Edition A Version 1 and is the only
value this row set decodes.** `"30"` is STANAG 4607 Edition 3, whose detail was published inside
the STANAG rather than in an AEDP; anything else is a later edition nobody has read.

**A non-`41` packet is refused with the value quoted, and the reason is enumeration drift rather
than structure.** Guide Annex M.2 lists what changed from Edition 3 to Edition A, and the
load-bearing item is #28, Table 3-11, Target Classification:

| | Edition 3 | Edition A Version 1 |
|---|---|---|
| 14–18 | `14–125 = Reserved` | `14 = Clutter, Live` · `15 = Phantom Live` · `16 = Ground Rotator Live` · `17 = Small Vehicle, Live` · `18 = Low-slow Flyer, Live` |
| Tagging Device | **143** | **142** |
| 144–148 | `143–253 = Reserved` | `144 = Clutter, Simulated` · `145 = Phantom Simulated` · `146 = Ground Rotator Simulated` · `147 = Small Vehicle, Simulated` · `148 = Low-slow Flyer, Simulated` |

An Edition 3 packet decoded against Edition A therefore reads a tagging device as `Reserved` and
five live-target classes as five different things. That is a **silent misclassification with no
structural symptom** — every length checks out, every mask is satisfied, and the targets are
simply the wrong kind of object.

**So Edition 3 is deferred, not a separate adapter — and that is a deliberate departure from the
STANAG 4676 settlement.** There, Edition 1 became a separate adapter because the standard had
"re-architect[ed] the data model and XML-based syntax from scratch": different root, different
time model, different security model, two parsers behind one name. Here the packet header, the
segment header, the existence masks and the field layouts are the same; what moved is the contents
of three enumeration tables. That is **one adapter with a version-dispatched enumeration table**,
not two adapters, and building it means transcribing Edition 3's tables from a document this
repository has not pinned. Deferred on the pin, not on the design.

### What the adapter's input IS — one packet, and nothing else

`to_cdm()` takes **one GMTIF packet**: a `bytes` object beginning with a 32-byte Packet Header
whose `P2` Packet Size equals its length, or the already-parsed dict a fixture twin holds — the
same `bytes | dict` shape `adsb.py`, `asterix_cat021.py` and `stanag4676.py` accept, and for the
same reason (the harness's lossless check has no leaves to harvest from raw bytes).

The standard draws this boundary itself, twice. §2.2: "The format does not specify error
detection/correction, encryption, or the physical transmission of the data. The format requires
these functions to be accomplished by the lower layers of the communications media", and "There is
no provision or need within AEDP-4607 for Start- or End-of Message characters to be transmitted."
Guide §D.4 puts packet sequence numbering, loss detection and channelisation in a "mux/demux"
layer explicitly *outside* the format. So the adapter does not own, and must never acquire, a
socket, a datalink, a reassembly buffer, a sequence-number window or a cache of previous packets.
**Splitting a stream into packets is the caller's job, by the standard's own instruction.**

Two consequences that are easy to miss and are settled here rather than in the code:

- **A packet is not a dwell, and a dwell is not a packet.** §3.4.32: "Targets detected within a
  dwell may be split among multiple Dwell Segments", and guide §D.2 conclusion 3: "Multiple dwell
  segments may be sent with the same Dwell Index, indicating that the dwell has been split into
  multiple segments." Guide §D.5 then describes splitting one logical dwell across multiple
  *packets*, with the Dwell Segment header fields repeated in each. **Reassembling a split dwell
  is refused** — it is the AIS fragment buffer, the ADS-B frame pair, Legion's pagination,
  CAT021's cross-block correlation and NITS's DATASTREAM resolution, refused a sixth time. Each
  Dwell Segment translates as what it is: a report of the target reports it actually carries.
- **`D5` Target Report Count is a count of what is in *this* segment**, not of the dwell — §3.4.5:
  "A count of the total number of targets reported during this dwell **and sent in this Dwell
  Segment**." A `D5` that disagrees with the number of reports the segment's `S2` size can hold is
  a packet with an error, and that is a refusal quoting both numbers.

### What one packet becomes

| GMTIF | CDM |
|---|---|
| the packet | the envelope. Parked on every object the packet produces; never an object of its own |
| Packet Header | the platform, mission and job identity, the security label and the simulation declaration. Parked; never an object of its own |
| Segment Header | framing. Parked as the type and size of each segment, in order |
| Mission Segment | **not an object.** The mission's reference date and the platform's type and configuration. Parked — and it is the packet's *date source*, which no other adapter in this document has on the wire |
| Job Definition Segment | **not an object.** The job's tasking, geometry, radar mode and nominal sensor performance. Parked on the platform `Entity` |
| Dwell Segment (D1–D31) | one **`Entity`** for the *platform*, updated from the sensor position and velocity, and one **`TrackSample`** of the platform's single `Track` |
| one Target Report (D32.x) | one **`Entity`**, the detected object, and one **`Event`**, `DETECTION`. **Never a `Track` and never a `TrackSample`** |
| Platform Location Segment | one **`TrackSample`** of the platform's single `Track`, and the platform `Entity`'s state where it is the latest |
| HRR Segment | one **`Event`**, `DETECTION`, per HRR segment, carrying the segment's parameters. The scatterer records are parked, never mapped |
| Free Text Segment | one **`Event`**, `STATUS_CHANGE`. A message is data, so it becomes an object rather than being dropped |
| Test and Status Segment | one **`Event`**, `STATUS_CHANGE`, about the *platform* |
| Processing History Segment | one **`Event`**, `STATUS_CHANGE`. Carried verbatim, resolved never — **gap 14** and **gap 19** |
| Job Request Segment | **nothing.** Parked whole; see the declines table |
| Job Acknowledge Segment | **nothing.** Parked whole; see the declines table |
| a reserved or extension segment type | **nothing.** Skip-and-record: the skip is exact because `S2` gives its length, the type code and size are always logged, the bytes are parked by default, and the rest of the packet translates. Never a silent skip |

**The platform `Entity` is one per packet, and every target `Entity` is one per target report.** A
packet carrying a Mission Segment, a Job Definition Segment and four Dwell Segments holding 300
target reports between them yields **one** platform `Entity`, **one** platform `Track` with four
samples, **300** target `Entity` objects and **300** `DETECTION` `Event` objects. Nothing about
that count depends on how the producer chose to chunk its output, which is the STANAG 4676
one-`Track`-per-`TrackData` argument reaching a format that has no track at all.

### Settlement 2 — Time: the reference date is ON THE WIRE, and the injected clock is not the date source

**This is the first adapter in this document for which the injected clock does not supply the
date, and the difference is worth stating against the precedent it breaks.** CAT021 states a time
of day and never a date, so `asterix_cat021.py` takes the date from the injected clock and
resolves midnight rollover in both directions by nearest-instant. STANAG 4676 states an absolute
`baseTime`, so the date arrives with the data and the clock is not consulted. GMTIF is a third
case and the awkward one: the date **is** on the wire, in `M5`/`M6`/`M7` of the **Mission
Segment** — a *different segment* from the one carrying the time of day.

    observed_at = midnight UTC at the beginning of (M5, M6, M7)  +  D6 milliseconds

with `T4` (Test and Status) and `L1` (Platform Location) substituting for `D6` in their own
segments. Every one of the three is `I32`, in milliseconds, and the arithmetic is exact: integer
milliseconds added to a midnight instant, which a CDM `Timestamp` renders at exactly the three
decimal places it has (`times.render`). **There is nothing to park and no truncation to record** —
unlike NITS, whose `relTimeIncrement` is a `double` in decimal seconds and whose products are
therefore not whole milliseconds. GMTIF's time model is the easiest of the three and it should be
said plainly rather than dressed up.

#### A dwell past midnight is stated, not silent — so the rule is addition, and NOT a modulo

**The brief for this row set stated a fallback for this case: refuse, quoting the raw integer, if
the text was silent. The text is not silent, so the fallback does not apply and the departure is
recorded here.** AEDP-4607 addresses multi-day dwell times in three separate places:

- §3.4.6, D6's own definition: "In this manner, the Dwell Time corresponds to the day's UTC time
  converted to milliseconds, **with the possible addition of multiples of 86400000 for multi-day
  missions**."
- §3.3.7, under the Reference Time fields: "The maximum value of field D6 is equivalent to
  49 days. Therefore, to prevent the time stamp in field D6 from being repeated, a new mission day
  must be provided every 49 days or more frequently."
- Annex C-3, with a worked example: reference date 2002/08/24, a dwell centred on 08:45:35.2 UTC
  **of the next day** gives `D6 = 117,935,200`, "since 117,935,200 = 35.2\*1000 + 45\*60\*1000 +
  8\*60\*60\*1000 + **1\*24\*60\*60\*1000**".

So a `D6` of 117,935,200 is not an out-of-range value to be refused and not a value to be reduced
mod 86,400,000; it is a conformant statement that the dwell happened on the day after the mission
reference date. **The rule is exact addition with no wrapping of any kind**, and `L1` says the
same thing in the same words (§3.15.1). A modulo would silently move a multi-day mission's every
dwell back onto day one, and a refusal would reject the case the format was designed for.

`attributes.observed_at_basis` records the reference date, the raw millisecond count, and the
whole number of days the count exceeds one day by — so a consumer can see that an instant 41 days
after the reference date was computed rather than guessed.

**One genuine range contradiction survives, and it is handled by converting and recording.**
Table 3-9 gives `D6`'s value range as "0 to 4 x (10^9)" milliseconds, which is 46 days 7 hours.
§3.3.7 and Annex C-3 both say the field accommodates "49 days" and "49 days and 17 hours", which
is the full `I32` range, 4 294 967 295 ms. A `D6` between 4 000 000 001 and 4 294 967 295 is
therefore outside the table's stated maximum and inside the prose's. The arithmetic is unambiguous
either way, so the value is **converted**, the raw integer is parked, and
`attributes.unresolved_raw` records that it exceeded the table's declared range — a refusal here
would reject a value two of the standard's three statements permit.

#### The Mission Segment may be in a different packet, and there are exactly three date paths

The standard is explicit that the reference date does not have to be in the packet that needs it.
§3.3: the Mission Segment "shall be sent periodically at least once every two minutes", and "the
Dwell Time (field D6) specified in any associated Dwell Segments is referenced to the Reference
Time (fields M5-M7) in the Mission Segment, and **will not be resolved as to the day of the
mission until the Mission Segment is received from the transmitting platform**." Guide §A.1.3 adds
that it is "preferable that it be sent more often (e.g., every thirty seconds), and ideally within
each STANAG 4607 packet".

**So mission context does carry across packets in a stream — the specification says so — and
carrying it is the caller's job, because this adapter holds no state between payloads.** That is
the same boundary every other settlement here draws, and it produces three paths and no fourth:

| Where the reference date comes from | When | What is recorded |
|---|---|---|
| **the packet's own Mission Segment** | the normal case, and the one the guide calls ideal | `M5`/`M6`/`M7` as read. Basis `in_packet` |
| **the caller, as an explicit argument** | the packet has a Dwell, Test and Status or Platform Location Segment and no Mission Segment, and the caller — who owns the stream and has seen an earlier packet's Mission Segment — supplies the date | the supplied date, basis `caller_supplied_stream_context`, naming the value and stating that this packet did not carry it |
| **nowhere** | neither of the above | **refusal**, naming the segments that carried a time and had no date to resolve it against |

**Amendment 4 attached two conditions to the middle path, and the first of them corrects a
mis-classification in the Phase 1 text.**

**(a) The path that supplied the date is recorded on every emitted instant, not once per packet.**
A basis field on the owning `Entity` is not enough: an `Event`'s `observed_at`, a `TrackSample`'s
`observed_at` and an `Entity`'s `valid_from` are each an absolute instant computed from the
reference date, and a consumer holding one object does not necessarily hold the `Entity` whose
`attributes` explained it. So `payload.reference_date_basis` is set on every `Event`,
`attributes.platform_track_points[].reference_date_basis` on every platform sample, and
`attributes.reference_date_basis` on the `Entity` — each naming the path, and for the caller path
naming the supplied value. **An instant computed from a date the wire did not carry must be
distinguishable from one computed from a date it did, on the object that carries the instant.**

**(b) A Mission Segment contradicting the caller's argument is a refusal quoting both. Neither
silently wins.** If a packet carries a Mission Segment *and* the caller supplied a date, and the
two differ, the adapter refuses with both values quoted and both origins named. The two failure
modes it forbids are symmetric and both are silent: letting the wire win discards a caller
statement that may be the correct one and may indicate the caller has mis-tracked the stream;
letting the argument persist over an in-packet Mission Segment means a stale caller-held date
overrides the wire, which is the worse of the two because the wire is where §3.3 puts the answer.
A contradiction here means the caller's stream tracking and the producer disagree about what day it
is, and that is an operator's problem, not a precedence rule's. (Identical values are not a
contradiction: the caller has simply confirmed what the packet says, the `in_packet` path is used,
and the basis records that the argument agreed.)

**The caller's argument is a stand-in for absent wire context, and it is NOT a deployment
declaration.** The Phase 1 text called it one and likened it to the STANAG 4676 confidentiality
label's configured path; that was wrong, and the difference has teeth. A deployment declaration —
`source.synthetic`, a configured confidentiality label — states a fact about the *deployment* that
no payload is competent to contradict, which is why amendment B protects it *against* the wire. A
reference date is a fact about the *mission*, the wire is its designated home (§3.3 names the
Mission Segment), and the caller is only relaying what an earlier packet in the same stream said.
So it gets no amendment-B protection: where the wire speaks, the wire is not overridden, and where
the two disagree neither is preferred — which is condition (b). A configured confidentiality label
beats silence and is never contradicted by a payload; a caller-supplied date beats silence and is
refused when a payload contradicts it. Two different categories, and the row set now says which is
which.

**The injected clock is never the third path.** It supplies `Event.received_at` and nothing else in
this adapter. Writing the receipt instant's date into the mission reference would date every dwell
in the packet to the day we happened to read it, every other check would pass, and a mission
flying across midnight UTC would produce a picture 24 hours wrong with no symptom. That is
strictly worse than CAT021's clock-derived date, because there the clock is resolving a *time of
day the format genuinely omits*; here it would be overriding a value the format states in a
segment we happen not to have.

A packet with **no** time-bearing segment at all — a Mission Segment alone, a Free Text Segment
alone, a Job Definition Segment alone — needs no reference date and is translated without one, with
the basis saying so. `Event.observed_at` for those objects falls to the rule below.

#### The `observed_at` chain, stated in full

`Event.observed_at` is "when the SOURCE saw it", and `payload.observed_at_basis` names the step
taken:

1. The segment's **own millisecond count**, resolved through the equation above: `D6` for a
   `DETECTION` from a target report and for the platform's dwell-derived sample, `T4` for a Test
   and Status `Event`, `L1` for a Platform Location sample.
2. **The owning Dwell Segment's `D6`, for an HRR `Event`** — the HRR Segment carries `H2` Revisit
   Index and `H3` Dwell Index and **no time of its own**. Where the referenced dwell is in the
   same packet its `D6` is used and the basis says so; where it is not, there is no instant, and
   see the next item.
3. **`Event.received_at`, and only with the basis saying that the format stated no source time** —
   for a Free Text Segment, a Processing History Segment, and an HRR Segment whose dwell is not in
   this packet. None of the three carries any time field. This is the one place this adapter puts
   a receipt instant in an `observed_at`, it is forced by a mandatory schema field meeting a
   segment that states no time, and the basis makes it visible on every such object rather than
   leaving a plausible instant unexplained.

   **This violates `Event.observed_at`'s own documented meaning — "When the SOURCE saw it. Never
   receipt time" — on three object kinds, and that is a CDM gap rather than an adapter footnote.**
   It is **gap 23**: the model has no way to express "the source stated no instant", because
   `observed_at` is required with no default and no canonical field for saying where it came from,
   so the three available answers are to discard the data, to invent an instant, or to substitute
   one and label the substitution in an untyped dict. The third is the least bad and it is still a
   violation; the gap carries the two 1.1.0 proposals and the reason the docstring amendment has to
   ride the same release.
4. There is no fourth step.

**`Event.received_at` is the injected clock, always** — the one field an adapter invents rather
than reads. GMTIF carries no producer-side creation time anywhere, so unlike NITS there is not
even a wrong candidate to warn against.

#### The dwell instant is the *temporal centre* of the dwell, and that is a stated approximation

§3.4.6: `D6` is the elapsed time "to the temporal center of the dwell", and `D7`–`D9`, `D15`–`D17`
and `D21`–`D23` are all "at the temporal center of the dwell". A dwell has duration — Annex C-1.3
defines it as a sequence of coherent processing intervals — so every target report in a Dwell
Segment shares one instant that is the *midpoint* of the interval in which its return was actually
received, and the format states no per-report time and no dwell duration. `D27` Dwell Angle Half
Extent is an angular half-extent, not a temporal one, and turning it into a duration would need
the scan rate, which the format does not carry.

So every target report in a Dwell Segment gets the same `observed_at`, the basis says it is a
dwell centre rather than a detection instant, and the residual is unstated. That is **gap 13** —
no per-measurement time — arriving from a fourth format and in its sharpest form yet: CAT021 states
two applicability times in one record, and GMTIF states one time for up to 65 535 reports.

### Settlement 3 — Confidentiality: three fields park verbatim, and the digraph is what makes them mean anything

The Packet Header carries the classification on **every packet**, in three mandatory fields:

- **`P4` Security Classification and/or Marking**, `E8`: `1 = TOP SECRET`, `2 = SECRET`,
  `3 = CONFIDENTIAL`, `4 = RESTRICTED`, `5 = UNCLASSIFIED`.
- **`P5` Classification System**, a two-character digraph naming "the national or multinational
  security system to which the security classification and/or marking in field P4 conforms" — with
  `XN` for the NATO system, a list of national examples, "Additional codes as registered with the
  Custodian", and all-BCS-spaces meaning no system applies.
- **`P6` Code**, a 16-bit flag field of "additional control and/or handling instructions", where
  each set bit names a codeword and `0x0000` is the no-statement value.

**All three park verbatim at `attributes.confidentiality_label`, as a triple and never as a
string.** The STANAG 4676 amendment-F discipline reached a second time, and here the argument is
not an analogy — it is a demonstrated contradiction in the pinned documents:

1. **`P6`'s bits mean different things in two of the three pinned documents.** Standard Table 3-4
   assigns `0x0001 = EU (Releasable To European Commission)`, `0x0002 = EUFOR`, `0x0004 = ISAF`,
   `0x0008 = KFOR`, `0x0010 = NATO RESPONSE FORCE`, `0x0020 = NMI`, `0x0040 = PFP`,
   `0x0080 = RESOLUTE SUPPORT`, `0x0100 = THE PUBLIC`, and `0x0200`–`0x8000` undefined. Guide
   Annex G Table G-1 assigns the same sixteen bits `NOCONTRACT`, `ORCON`, `PROPIN`, `WNINTEL`,
   `NATIONAL ONLY`, `LIMDIS`, `FOUO`, `EFTO`, `LIM OFF USE (UNCLAS)`, `NONCOMPARTMENT`,
   `SPECIAL CONTROL`, `SPECIAL INTEL`, a warning notice, `REL NATO`, `REL 4-EYES`, `REL 9-EYES`.
   An adapter that rendered `0x0001` as a caveat would be picking one of two published meanings.
2. **The standard says the codewords are not the standard's to define.** Table 3-4's own note:
   "This table is representative, based on NATO security handling codes for Packet Classification
   System **XN**, and is not an exhaustive list of all allowable codes. **Each nation shall be
   responsible for developing and publishing their own packet security handling codes** as
   required." So `P6`'s meaning is a function of `P5`, and there is no registry of national code
   sets in any pinned document.
3. **`P4`'s integer is national too.** `4 = RESTRICTED` is a level several national systems do not
   have and others define differently, and the digraph is the only thing that says which system's
   RESTRICTED it is. A `P4` reduced to the string `"RESTRICTED"` is a marking with its policy
   removed — which is exactly what the 4774 settlement refuses for NITS.

**So the digraph travels with the label, structurally.** `attributes.confidentiality_label` is
`{system: P5, classification: P4, classification_text: the standard's wording, codes: P6, code_bits: [...]}`,
and the `codes` value is the **raw 16-bit integer plus the list of set bit positions**, never a
list of codeword names. `attributes.confidentiality_label_basis` records that both published
codeword tables were consulted and that neither was applied. A label whose `system` is
BCS-spaces records that the packet declared no system, which is a *stated* absence and lands in
`unavailable_fields`, not a reason to reach for `XN`.

**Egress has exactly three paths and a silent `UNCLASSIFIED` default is forbidden.** `P4`, `P5`
and `P6` are Mandatory on every packet, so every emitted packet must get them from somewhere, and
"somewhere" is enumerated rather than defaulted — the STANAG 4676 table, restated because the
fields are different and the discipline is the same:

| Where the label comes from | When | What is recorded |
|---|---|---|
| **the park** | the object round-tripped from a GMTIF packet | the exact triple that arrived, re-emitted byte-for-byte, including the raw `P6` integer. The basis says `round_tripped` |
| **configuration** | a CDM-native object — from AIS, ADS-B, CAT021, Legion, CoT or NITS — for which the deployment has supplied a `P4`, a `P5` and a `P6` as explicit arguments | the supplied triple, basis `configuration_supplied`, naming the values and stating that no source stated them |
| **nowhere** | neither of the above | **refusal**, naming the object. Emitting would mean writing a marking nobody applied |

`P4 = 5` (UNCLASSIFIED) is a real classification a producer can state and is therefore a perfectly
good *round-tripped* or *configured* value. What is forbidden is reaching for it because nothing
else was available: a defaulted `5` is a downgrade decision taken by a translator, and the
absence of a mandatory field is a fact about the packet, not a fact about the data's sensitivity.
Note that a partial label — a configured `P4` with no `P5` — is also a refusal rather than a
`P5` of spaces, because per the argument above a classification with no system is a marking whose
policy has been removed.

**Gap 12 gets a GMTIF paragraph.** What this format adds to it is that the classification is
**mandatory on every packet** and **structured as three interdependent fields**, so the gap is no
longer "one vendor states a `top_classification` string" or even "a NATO standard requires a typed
XML label"; it is "a binary format stamps a system-scoped classification and a bitfield of
national caveats on every single packet, and the CDM has nowhere to put any of it."

### Settlement 4 — Simulation: two payload declarations, one boolean, and neither sets it

GMTIF states whether its data are real **twice**, at two levels, and one of the two is mandatory
on every packet. Under STANAG 4676 amendment B — `SourceRef.synthetic` is a **deployment
declaration** and a payload field may not rewrite one — both park. The rule is a rule, not a
default with exceptions, and this is the third format to test it.

#### `P7` Exercise Indicator is the mandatory one, and it carries two facts

`P7` is `E8`, Mandatory, on every packet:

| Value | Meaning | Fact 1 — programme | Fact 2 — provenance |
|---|---|---|---|
| 0 | Operation, Real Data | operation | real |
| 1 | Operation, Simulated Data | operation | simulated |
| 2 | Operation, Synthesized Data | operation | synthesized, "a mix of real and simulated data" |
| 3–127 | Reserved | — | — |
| 128 | Exercise, Real Data | exercise | real |
| 129 | Exercise, Simulated Data | exercise | simulated |
| 130 | Exercise, Synthesized Data | exercise | synthesized |
| 131–255 | Reserved | — | — |

**Both facts park and neither sets `synthetic`.** The programme axis parks for NITS's
`CollectionIntentType` reason, which the standard states in its own words here too: an exercise
"originates from live-fly or other non-simulated operational sources" just as often as not, so
`Exercise, Real Data` is real sensor data collected during an exercise and calling it synthetic
would be false. The provenance axis parks under amendment B.

**`P7` NEVER WRITES `source.synthetic`, IN EITHER DIRECTION — INCLUDING AGREEMENT.** Amendment 2
reversed a reading that had `synthesized` "agreeing with" a `synthetic = true` declaration, and the
correction is not a detail. The rule that shipped twice — in CAT021's I021/040 `SIM` row and in
STANAG 4676 amendment B — is that **a payload field may not touch a deployment declaration**, and
writing a value that happens to match is still writing it. A row set that let a payload field set
the boolean whenever the two agreed would have a rule that only bound on disagreement, which is a
default with a conflict check bolted on. `synthetic` comes from the deployment declaration alone,
whatever `P7` says, and `attributes.synthetic_basis` records that the packet stated a provenance
and that the declaration is what was used.

**What `P7` does instead is participate in a conflict check, and it has three branches:**

| `P7` provenance | deployment `synthetic = false` (real) | deployment `synthetic = true` (synthetic) |
|---|---|---|
| **pure real** (0, 128) | consistent — parked, no refusal | **conflict — logged refusal, both values quoted** |
| **pure simulated** (1, 129) | **conflict — logged refusal, both values quoted** | consistent — parked, no refusal |
| **synthesized** (2, 130) | **parked visibly, NO refusal** | **parked visibly, NO refusal** |

The third row is the one that changed, and the reasoning is the standard's rather than the
boolean's. `P7 = 2` means "a mix of real and simulated data" in §3.1.7's own words, so it does not
contradict a declaration of *pure* real or a declaration of *pure* synthetic — it is a third
statement, and a mixture is exactly what neither pure declaration describes. The previous reading
resolved it onto `true` by reading `SourceRef.synthetic`'s docstring, which was the field's
definition being used to adjudicate a payload value: the same move amendment B forbids, arrived at
one step further back. So a synthesized packet translates under whatever the deployment declared,
and `attributes.synthetic_basis` says in as many words that the packet declared a mixture, that the
CDM's boolean cannot hold one, and which declaration was used — visibly, on every object, rather
than as a refusal that would reject the case §3.1.7 exists to describe.

The two conflict branches keep their asymmetry and it is the right way round: a feed configured as
operational that receives a packet declaring its data *purely* simulated has either been
misconfigured or been fed the wrong data, and so has the reverse, and both are conditions an
operator must be told about rather than have quietly reflected in a boolean.

A **reserved** `P7` value (3–127, 131–255) states neither fact. It parks in
`attributes.unresolved_raw`, no conflict check runs, and `attributes.synthetic_basis` records that
the packet's provenance declaration was unreadable — which is *not* the same as the packet not
making one, and the basis distinguishes them.

#### `D32.10`'s simulated half does not set `synthetic` either — and it is not a clean 128 boundary

Target Classification's 256 values are two halves, live below 128 and simulated at and above it,
and the classification's *type* statement is read while its *provenance* statement is only
recorded — the FAKER/ZOMBIE read-vs-record principle, reached in a format where the two claims
share one octet. The full accounting is in the `D32.10` table below. Three things about the
boundary are settled here because each is a trap:

1. **`128 + n` is a lookup, never arithmetic.** The halves mirror each other for `n = 0..13` and
   then diverge: `142` is `Tagging Device` with no live counterpart, `143` is Reserved, and
   `144`–`148` mirror `14`–`18` at an offset of **+130, not +128**. An adapter computing
   `live = code - 128` would read `144` (Clutter, Simulated) as `16` (Ground Rotator Live) and
   `142` (Tagging Device) as `14` (Clutter, Live). Two of the three edition-A additions land
   inside exactly that gap, which is why item #28 of the change list is where this trap came from.
2. **The `Tagging Device` label and `Reserved` are the two entries in the upper half the table does
   not mark "Simulated", and the format proves the first of them.** `D32.16` is "sent only if the
   MTI Target in this report **is simulated OR a tagging device is detected**" (§3.4.32.16) — a
   disjunction, which is only meaningful if a tagging device is not simulated. So a
   `Tagging Device` report is a **real** detection of a real emitter that happens to sit in the
   numeric range above 127, and no simulation inference attaches to it. **The exemption is written
   against the label, not the number** (amendment 6): the label has been carried by `140`, `143`
   and now `142` across three editions, so under Ed A the exempt values are `142` and `143`
   (`Reserved`, exempt because the table does not mark it Simulated either) and a future
   renumbering moves the exemption with the label rather than stranding it.
3. **A simulated target report inside a packet declaring real data is an intra-payload
   contradiction, and it is a separate refusal from the deployment conflict.** `P7 = 0` says
   "Operation, Real Data" about the whole packet; a `D32.10` of 129 says this target came from a
   target simulator. `P7 = 2`, "Synthesized Data … a mix of real and simulated data", is precisely
   the value the format provides for that packet, so the producer has stated two incompatible
   things about its own data. **Refusal, quoting `P7`, the offending `D32.10` values and the count
   of reports carrying them, and naming `P7 = 2` as the value the packet needed.** Codes `142`
   and `143` are exempt, per item 2.

That is two distinct refusals with two distinct causes — payload-versus-deployment and
payload-versus-payload — and they are checked and reported independently, for the reason the
STANAG 4676 segment-ordering rule gives: a refusal that names the wrong cause is a guess wearing a
refusal's clothes.

#### The truth tags are a simulation artefact and a real-tag identifier in one pair of fields

`D32.16` Truth Tag – Application and `D32.17` Truth Tag – Entity are, per §3.4.32.16–17, the
Application and Entity fields of the **DIS Entity State PDU** that generated a simulated MTI
target — "for simulated data, the truth tag relates targets back to the truth data" — *or*, when a
tagging device was detected, the tag's battery strength and "the tag identification number
transmitted by a tagging device".

Both park, raw, always, and neither becomes a `SourceId`. **Amendment 6 re-based the grounds for
that, because running down the `140`/`142` discrepancy changed the strongest reason and the row set
says so rather than leaving a weakened argument standing.**

The Phase 1 reason was that "the condition that distinguishes a DIS application field from a
battery percentage is unstatable from the pinned text". It is not unstatable. Ambiguity 3 traces
the value through the pinned documents — `Tagging Device` was **140** when this prose was written
(guide Annex M.1, pages M-9 and M-10, added the table value and the prose in adjacent items of one
errata), then **143** in STANAG 4607 Ed 3, then **142** in Ed A — so the prose plainly means *the
class labelled Tagging Device* and the standard simply never re-based the number. The condition is
therefore **statable, and only by an editorial correction to a normative document.** That is a
different objection and a narrower one, and it is the first of the three below.

- **Applying it means re-basing a normative cross-reference, which is a custodian's act and not a
  translator's.** Reading the prose against `142` requires *us* to decide that the standard meant a
  number it does not say — and this document declines that move elsewhere on weaker provocation:
  the STANAG 4676 row set uses the acknowledged-wrong `nga.gov` namespace because the wrong one is
  the conformant one. The alternative is worse rather than safer: applying the prose literally to
  `140` would read a battery percentage off a `Large Multiple-Return, Simulated Land Target`, which
  is nonsense the standard cannot have meant. **Neither reading is safe, both are now understood,
  and the understanding is what is recorded.**
- **A DIS entity identifier is ground truth from a simulation**, and keying a CDM `Entity` on it
  would make the adapter a simulation harness: it would give simulated targets the cross-dwell
  identity continuity that real targets provably do not have, so the same pipeline would produce
  tracked objects in exercise and unassociated hits in operations. That is the worst possible
  place for a behavioural difference, and it is untouched by the provenance finding.
- **The tag identification number is genuinely a persistent real-world identifier**, and it is the
  one candidate in the whole format with a case for `SourceId`. What it now waits on is smaller
  than it was: a custodian's erratum re-basing `140` to `142` in §3.4.32.16 and §3.4.32.17 turns
  this into a five-line change and a `SourceId` with `system = "GMTIF-TAG"`, keyed on the label
  rather than the number so the next renumbering costs nothing. Recorded in the declines table as
  deferred, blocked on the erratum — and the ambiguity row now carries the exact page references an
  erratum request would have to cite.

**The exemption from the intra-payload simulation conflict check does not depend on any of that**,
and amendment 6 leaves it standing. It rests on the conditionals themselves: `D32.16` and `D32.17`
are each "sent only if the MTI Target in this report is simulated **or** a tagging device is
detected", and a disjunction is only meaningful if its two branches are different — so **the
standard itself treats a tagging device as distinct from simulation**, whatever value carries the
label. The exemption is written against the label and covers whichever value or values carry it,
which under Ed A is `142`.

### Settlement 5 — Identity: a detection is not a track, and no target `Track` is ever emitted

#### What the format actually identifies, and what it does not

| Thing | Identified by | Scope of that identifier | Verdict |
|---|---|---|---|
| the **platform** | `P3` Nationality digraph + `P8` Platform ID | **globally unique, by the standard's own guarantee.** §3.1.8: "the platform ID is determined by the nation owning the platform, whose responsibility it is to ensure that all its platforms are uniquely identified within the set of platforms it owns" | a real, persistent `Entity` with a real `SourceId` |
| the **mission** | `P9` Mission ID | "assigned by the platform identified in Field P8 that uniquely identifies the mission for the platform" — scoped to the platform | a composite key component, never a key |
| the **job** | `P10` / `J1` Job ID | "shall be unique within a mission", and §3.7.14 adds that "the Job ID must be associated with exactly one radar operating mode" | a composite key component |
| the **dwell** | `D2` Revisit Index + `D3` Dwell Index | scoped to the job, **and not unique**: guide §D.2 says "Multiple dwell segments may be sent with the same Dwell Index", and §3.4.3 says dwell counts "are allowed to wrap" | ordering information, not identity |
| a **target report** | `D32.1` MTI Report Index | "The sequential count of this MTI report **within the dwell**" — and Conditional, sent only when an HRR report exists for the dwell | **within the dwell**, by its own definition. No cross-dwell semantics anywhere |
| a **simulated target** | `D32.16` + `D32.17` truth tags | a DIS Entity State PDU in another system — or a physical tag's ID, and the format cannot say which | parked, never keyed on. Settlement 4 |
| a **real target** | *nothing* | — | there is no identifier |

**The brief for this row set said to quote and rule from the text if any field carried a
track or report index with stated cross-dwell semantics. None does.** `D32.1` states its scope in
its own definition and it is the only per-report index in the format. `H5` MTI Report Index in the
HRR Segment points at a `D32.1` in the *same* revisit and dwell (`H2`/`H3`), which is a
within-dwell reference, not a continuity claim. So each target report stands alone, and the row set
says so on every row that would otherwise be tempting.

#### An `Entity` is one target report, and the reason is that the alternatives lose more

A GMTI target report states that at one instant, energy consistent with a mover was returned from
one geodetic position, with a radial velocity component, a classification and a signal-to-noise
ratio. "Something was there" is an `Entity` claim; "we detected it" is an `Event` claim. Both are
made, so both objects are emitted, and the `Event`'s `related_entities` names the `Entity`.

The two alternatives were considered and are worse:

- **Event-only, with the report in `Event.payload` and a `Point` in `Event.geometry`.** Mechanically
  sufficient — `Event` has both — and it discards the two canonical fields the format genuinely
  fills: `Entity.entity_type`, which `D32.10`'s live half states directly, and `Entity.position`,
  which is the field every consumer draws from. A row set that put a stated position somewhere
  other than `Position` to avoid an uncomfortable `Entity` would be hiding the discomfort rather
  than recording it.
- **One `Entity` per dwell, the target reports parked on it.** This is the shape that keys on the
  producer's chunking, which is the thing the STANAG 4676 one-`Track`-per-`TrackData` settlement
  rejects — and here it is worse, because a dwell is explicitly splittable across segments and
  packets, so the number of `Entity` objects a consumer sees would depend on the transmission
  media's MTU.

**So each target report yields one `Entity`, and its `entity_id` is derived, via
`ids.derive_with_basis`, from the composite the format actually guarantees:**
`P3` + `P8` + `P9` + `P10` + `D2` + `D3` + the Dwell Segment's ordinal position in the packet + the
report's ordinal position in the segment. The last two components are there because of the
non-uniqueness above: `(revisit, dwell)` does not identify a Dwell Segment, and `D32.1` is
Conditional and often absent, so a positional index is the only thing left. `attributes.entity_key_basis`
records every component and states that the last two are **positional and therefore not stable
under any re-segmentation of the packet** — the same fragility the STANAG 4676 per-segment sample
ranges have, recorded rather than hidden.

**`Entity.valid_from` is the dwell instant. `Entity.valid_to` is `None`, and that is the least
satisfactory statement in this row set.** A detection asserts existence at one instant and asserts
nothing whatever afterwards. `valid_to = valid_from` would say the object ceased to exist
immediately, which is false. `None` means "no end stated", which a consumer holding state may read
as "still current", which overstates by however long ago the dwell was. There is no third option
in the model, so `None` is chosen, `attributes.valid_to_basis` says in as many words that a GMTI
detection makes no persistence claim, and the honest fix is a model change — **gap 20**.

#### The platform gets one `Entity` and one `Track`, and the standard's own field definitions are what license it

The platform is the one thing in this format with a stated, globally unique, cross-packet identity,
and the format reports its position and velocity in two segments — each with **its own instant, and
the two instants do not mean the same thing**:

| Segment | Position | Velocity | Instant | What the instant IS |
|---|---|---|---|---|
| Dwell Segment | `D7`/`D8`/`D9` | `D15`/`D16`/`D17` | `D6` | §3.4.6 / §3.4.7: "the **temporal center of the dwell**" — the midpoint of the collection interval |
| Platform Location Segment | `L2`/`L3`/`L4` | `L5`/`L6`/`L7` | `L1` | §3.15.1 / §3.15.2: "the time the **report is prepared**" — a producer-side authoring instant |

**Amendment 3 moved the argument off the guide and onto those two definitions.** The Phase 1 text
rested the platform `Track` on guide §E.8's sentence that the two positions "are assumed to be the
same" — and that sentence cannot carry it, for two reasons. It is a statement about *positions* and
is entirely silent about the *instants*, which is the half that decides whether two samples belong
in one ordered list. And it lives in the same guide whose Annex G this row set discredits two
settlements later over its `P6` table, so leaning on an unverifiable guide sentence for a
structural decision is exactly the move ambiguity 1 exists to warn against. §E.8 is recorded below
as corroborating the position coincidence and nothing more.

**What actually licenses one `Track` is on the wire, in the standard, twice over.** Each of `D7`–`D9`
and `L2`–`L4` states the position *of the platform carrying the sensor* at an instant the same
segment states, and both segments sit under one Packet Header whose `P3` + `P8` identifies that
platform uniquely (§3.1.8). So the subject is stated, the instant is stated, and no association
step is performed or possible — every sample in the packet belongs to the platform named in the
packet header by construction. The two segments are complementary by design, which the standard
also says itself: §3.15 sends the Platform Location Segment "during periods when the sensor is not
collecting data", so they interleave rather than compete.

So one `Entity` per packet for the platform, keyed on `P3` + `P8` with `SourceId(system="GMTIF-PLATFORM", external_id="XN/AB12345678")`,
and **one `Track` whose samples are every platform position the packet states, in document order**.

**Every sample parks its own time basis, and that is the amendment's substance rather than its
bookkeeping.** `attributes.platform_track_points[]` records, per sample and in order:

| Key | Value | Why it has to be there |
|---|---|---|
| `time_basis` | `dwell_center` for a `D6`-sourced sample, `report_prepared` for an `L1`-sourced one | the two are not the same kind of instant. A dwell centre is the midpoint of an interval whose duration the format never states; a preparation time is when a producer wrote a record. **A consumer interpolating or averaging across a mixed run would be mixing an observation midpoint with an authoring timestamp, and nothing in the CDM would show it** |
| `source_segment` | `dwell` or `platform_location`, with the segment's ordinal position in the packet | so the sample can be traced back to the bytes it came from without re-parsing |
| `sample_index` | the index into `Track.samples` | because `TrackSample` has two fields and no bag — **gap 16**, keyed by index for the fourth time |

`attributes.platform_track_basis` states the same thing once for the whole track: how many samples
came from each basis, and whether the track is mixed. A single-basis track is the common case and
says so; a mixed one is flagged, because a mixed track is the one a consumer must not smooth.

Three further rules on that `Track`, each borrowed and each stated:

- **Document order, and a packet whose platform positions run backwards in time is refused, not
  sorted.** Legion's rule verbatim: "sorting would hide a source defect the caller needs to see."
  The format promises no ordering of segments within a packet, so a producer that emits them out of
  order produces a `Track` this row set refuses, with every violation listed and the instants
  quoted.
- **`Track.track_quality` is `None`.** GMTIF states no track quality because it states no track.
  `J25` Nominal Detection Probability is a probability that *an unobscured ten square-metre target
  will be detected* — a sensor performance figure, not a quality of this history — and writing it
  there would state a number about the wrong thing.
- **A packet with one platform position yields a one-sample `Track`** (`Track.samples` has
  `min_length=1`), and a packet with none — a Mission Segment or Free Text Segment alone — yields
  no `Track` and an `Entity` with `position: None`.

**Where guide §E.8 does and does not help, stated once so nobody re-derives it.** It says the Dwell
Segment's sensor position and the Platform Location Segment's platform position "are assumed to be
the same", which corroborates that the samples describe one point and settles a question the
standard leaves implicit — the sensor is mounted somewhere on the platform, and the offset is not
carried anywhere in the format. It is recorded for that. It says **nothing** about `D6` versus
`L1`, so it cannot license putting the two into one ordered list, and the per-sample `time_basis`
above is what stands in for the sentence the guide does not contain.

#### No target `Track`, and this is the fusion line for this format

Associating target reports across dwells is what a GMTI tracker does, and it is the entire
substance of a separate discipline: guide FAQ Q10 says the revisit concept "allows ground movers to
be tracked, and for identifying features to be accrued as evidence to the identity of the ground
mover", and then declines to specify how — "the way in which to do so is best recommended by the
sensor manufacturer as it may depend on the sensor's particular design purpose and mission."

A format whose own implementation guide sends the reader to the sensor vendor for the association
rule is not a format from which a translator may invent one. **So no target `Track` is emitted from
any packet, under any conditions**, and this is the first row set in this document that produces no
`Track` for its subject matter. The material for a tracker is carried in full — position, radial
velocity, wrap velocity for un-aliasing, SNR, RCS, classification, and the revisit and dwell
indices that order the dwells — and doing the association is the consumer's.

Note the symmetry with the STANAG 4676 declines: that row set carries `TrackLinkage` and
`ProcessedTrack` and refuses to act on them, because a tracker's *output* is data and a tracker's
*decision* is not the translator's. Here there is no tracker output at all, so the refusal moves
one step earlier and is correspondingly easier to state.

#### Affiliation is `UNKNOWN` on every object, and here it is not even a decision

`Entity.affiliation` is `UNKNOWN` on every `Entity` this adapter produces, target and platform
alike, with `attributes.affiliation_basis` recording why. **GMTIF states no affiliation, no IFF, no
identity and no allegiance anywhere in any segment** — it is a radar detection format, and a
Doppler return carries no allegiance. Unlike CAT021, where declining to read an authenticated
Mode 5 reply as `FRIENDLY` was a real decision with a real cost, there is nothing here to decline.
The platform's own `P3` Nationality digraph is the closest thing in the format, and reading a
platform's nationality as an affiliation would be inventing a coalition membership from a country
code: `attributes.platform_nationality` holds it and `affiliation` stays `UNKNOWN`.

`Entity.symbol` is `None` on every object, for the same reason and via the same route: the
`symbology.sidc_from_affiliation` path needs an affiliation, and composing a symbol from a target
classification alone would draw a symbol with an invented standard identity —
the 2525D-from-APP-6 refusal reached from a format that does not even carry an APP-6 code.

### Settlement 6 — Positions: exact binary angles, integer-domain delta recovery, and two unit traps

#### Coordinates are WGS 84 geodetic, and there is one system and no transforms

Annex C-2: "The fundamental earth reference system for the GMTI Format is the World Geodetic
System 1984 (WGS-84)", with the ellipsoid stated (a = 6 378 137 m, 1/f = 298.257223563), and "The
convention adopted for AEDP-4607 is to report sensor, platform, and target locations in the
Geodetic Coordinate System." The guide's Annex E tutorial on ECEF, topocentric, sensor-centred,
conical and flat-earth systems is explicitly tutorial: **no GMTIF field is ever expressed in any
of them.** So unlike STANAG 4676's six coordinate systems, three of which produce no `Position`,
GMTIF has exactly one and every position field converts. There is no coordinate settlement to
make, which is worth stating because it is the only place this format is simpler than the last one.

#### Binary angles convert exactly, and the precision is worth writing down

Annex C-4.6 and C-4.7 give the two encodings and the exact scale factors:

| Form | Encoding | Angle | LSB | Ground distance at the equator |
|---|---|---|---|---|
| `BA16` | unsigned 16-bit | value × 360/2^16 | 0.0054931640625° | ≈ 611 m |
| `BA32` | unsigned 32-bit | value × 360/2^32 | ≈ 8.3819 × 10^-8 ° | ≈ 9.3 mm |
| `SA16` | two's-complement 16-bit | value × 180/2^16 | 0.00274658203125° | ≈ 306 m |
| `SA32` | two's-complement 32-bit | value × 180/2^32 | ≈ 4.1909 × 10^-8 ° | ≈ 4.7 mm |

**These conversions are exact in IEEE-754 double precision and the row set claims so
deliberately.** The scale factor is `45/2^(n-3)` for `BA` and `45/2^(n-2)` for `SA` — the
standard's own "more care to precision" form, `value × 1.40625 × 2^-(n-8)`, where 1.40625 = 45/32 —
so the product of a ≤32-bit integer and 45 needs at most 38 significand bits and a `float64` has
53. No rounding is introduced by the conversion itself, and `attributes.position_basis` says so
rather than hedging. `BA16` and `SA16` are a different matter: a 611-metre longitude LSB is
*coarse*, but it is coarse **in the source**, and reporting it as an accuracy would be
manufacturing a figure — see below.

**Longitude arrives in [0, 360) East and the CDM requires [-180, 180].** Every `BA16`/`BA32`
longitude and heading field in the format is unsigned East-from-Greenwich: `D8` is "0 to
+359.999999916", `D25`, `J7`/`J9`/`J11`/`J13`, `L3`, `R5`/`R7`/`R9`/`R11`, `A8`/`A10`/`A12`/`A14`
the same. The reduction is `lon - 360 if lon > 180 else lon`, which is exact in both directions,
and it is applied to **longitudes only** — `D15`, `D21`, `D27`, `D28`, `L5` and `J22` are bearings
and half-extents in [0, 360) and stay there, because `Kinematics.course_deg` is documented as
"[0, 360)" and a heading of 350° is not -10°.

#### Delta positions recover in the integer domain, and longitude wraps while latitude does not

The reduced-bandwidth target report sends two-byte offsets from the dwell centre:

    Latitude  = (D32.4 × D10) + D24
    Longitude = (D32.5 × D11) + D25

with `D10` an `SA32` latitude scale, `D11` a `BA32` longitude scale, `D24`/`D25` the `SA32`/`BA32`
dwell-area centre, and `D32.4`/`D32.5` signed 16-bit counts. **Guide §E.7 requires that this be
computed on the encoded integers, not on degrees**, and gives the two cases separately:

- **Latitude**: `lat_S32 = lat_ref +_S32 (S16_to_S32(Δlat) ×_S32 scale_lat)`, in **signed** 32-bit
  arithmetic. Signed overflow is not defined as wrapping and a latitude cannot wrap — ±90° is a
  pole, not a seam — so a reconstruction that leaves the `SA32` range, or that yields |lat| > 90°,
  is a **refusal** quoting `D32.4`, `D10`, `D24` and the result.
- **Longitude**: the same shape in **unsigned** 32-bit arithmetic, with the sign of `Δlong` tested
  and the magnitude added or subtracted, and the guide is explicit that overflow and underflow are
  intended: "it is essential that the ANSI Standard C conventions for unsigned integer arithmetic
  be adhered to … that overflow from addition or underflow from subtraction yield a result that is
  congruent mod 2^n". A `BA32` wrapping mod 2^32 **is** the 360°/0° seam, so a dwell straddling
  the prime meridian recovers correctly and no special case is needed. The guide names this as the
  first of "two interrelated difficulties that require care", and an implementation that worked in
  degrees would produce longitudes near ±180 wrong by 360°.

So: **one binary-angle conversion, applied to the reconstructed integer, and never two conversions
with arithmetic in between.** `attributes.position_basis` records `hi_res` or `delta_recovered` and,
for the latter, the four inputs.

**A delta report whose Dwell Segment does not carry the scale factors is a refusal, not a guess.**
§3.4.10 and §3.4.11: `D10` "is always sent with field D11. They are sent **if and only if** the
optional difference fields Delta Latitude (D32.4) and Delta Longitude (D32.5) are sent in the
Target Report", and §3.4.32.4 states the converse — "If fields D32.4, D32.5, D10, and D11 are
sent, then fields D32.2 and D32.3 are not sent." So the mask combination "`D32.4`/`D32.5` present,
`D10`/`D11` absent" is non-conformant, the offsets are uninterpretable, and there is nothing to
default to: the scale is chosen per dwell from the dwell's own extent (guide §E.7, "Choosing the
Scale Factors"), so no fixed value exists to fall back on. **Refusal, quoting the eight relevant
existence-mask bits.** The mirror combination — both position pairs present, or neither — is
refused the same way and quoted the same way.

`D24`/`D25` are Mandatory with mask bits fixed at 1, so the reference point is always available;
a Dwell Segment whose mask clears either of them is a mask violation under settlement 7 before it
is a position problem.

#### Heights: three fields, two units, and the trap named before anyone hits it

| Field | Quantity | Unit **in the format** | To `Position.alt_m` |
|---|---|---|---|
| `D9` | Sensor Position – Altitude | **centimetres**, `S32`, -50 000 to +2 billion | ÷ 100 |
| `L4` | Platform Position – Altitude | **centimetres**, `S32` | ÷ 100 |
| `D32.6` | Target Location – Geodetic Height | **metres**, `S16`, -1 000 to +32 767 | × 1 |

Two altitudes in centimetres and one height in metres, in the same packet, describing the same
axis. A single conversion factor applied to all three puts the target 100× too high or the
platform 100× too low, and neither error has a structural symptom. It is written down here because
"the classic error" is not a figure of speech — the other unit splits in the format are the same
shape and are listed on their rows: `D12`/`D13`/`D14` sensor position uncertainties in
**centimetres** against `J16`/`J17`/`J18` nominal ones in **decimetres**; `D16` sensor speed in
**millimetres/s** against `D17` vertical velocity in **decimetres/s**; `D32.12` slant-range
uncertainty in **centimetres** against `D32.13` cross-range in **decimetres** and `D32.14` height
in **metres**.

**Whether these are heights above the ellipsoid is a contradiction between the standard and the
guide, and the standard wins.** §3.4.9, §3.15.4 and §3.4.32.6 all say "referenced to its position
above the WGS 84 ellipsoid" without qualification, which is exactly `Position.alt_m`'s documented
"Metres HAE". Guide §E.8 says heights are measured "either from the reference ellipsoid, **or from
mean sea level if a geoid model is being used**", and `J28` Geoid Model Used states `EGM96`,
`GEO96` or `Flat Earth`. Those two readings differ by the geoid undulation — up to about 105 m —
so under the guide's reading `alt_m` would sometimes be orthometric. The standard's unconditional
statement is taken, `J27` and `J28` are parked on the platform `Entity`, and
`attributes.alt_datum_basis` records the guide's contradicting sentence and the geoid model the
packet declared, so a consumer that needs to resolve it has both halves. This is **gap 9**'s
neighbourhood — no barometric altitude, and more generally no altitude datum field — reached by a
format that states a datum and then has its own guide disagree.

#### `Position.accuracy_m` is `None` on every object this adapter produces

GMTIF is the most uncertainty-rich format in this document. It states, per dwell, three sensor
position standard deviations (`D12` along-track, `D13` cross-track, `D14` altitude), three sensor
velocity ones (`D18`/`D19`/`D20`), per target report four measurement ones (`D32.12` slant range,
`D32.13` cross range, `D32.14` height, `D32.15` radial velocity), and per job five nominal ones
(`J16`–`J20`) plus four nominal sensor values (`J21`–`J24`). **Not one of them becomes
`accuracy_m`,** and the reason is the field's own definition: one number, metres, 1-sigma,
horizontal.

- **A slant-range standard deviation is not a horizontal error.** `D32.12` is along the sensor's
  line of sight, which is a slant; converting it to a ground-range error needs the grazing angle,
  which the format does not state and which cannot be derived without the terrain height the
  target report may not carry.
- **Two orthogonal components are not one scalar.** `D12` and `D13` are both horizontal, both in
  centimetres, and orthogonal — the most reducible pair in any format here — and reducing them
  still means choosing a convention (RSS? the semi-major axis? a DRMS?) that the source did not.
  This is Legion's 3×3 covariance refusal with the excuse removed, and it is the sharpest available
  statement of **gap 17**: an `accuracy_m` that carried an along/cross pair would express `D12` and
  `D13` exactly, and the CDM's single scalar cannot.
- **The nominal fields are a fallback the standard mandates and the CDM cannot receive.** §3.7.16's
  note: the nominal fields "are to be used when values are not received from the sensor. More
  precise values … may be reported in the appropriate fields in either the Dwell Segment or the
  Target Report Sub-Segment." That is a stated precedence chain, and it terminates in the same
  place: `J22` Cross Range Standard Deviation is an **angle** in degrees, and converting it to
  metres needs a range.

So `accuracy_m` is `None` everywhere, every figure is parked under a key naming its axis and its
unit, and `attributes.accuracy_basis` states the precedence chain the standard mandates and that
the CDM has one field where the format has twelve. CAT021 also reports `None` always, for the
opposite reason — everything it carries is a category or a containment bound — and the two row sets
reaching the same value from opposite premises is worth noting rather than eliding.

`Position.position_source` is `ESTIMATED` on every object, with `attributes.position_source_basis`
recording the two different reasons: a target position is a radar geolocation through a terrain and
geoid model (`J27`/`J28`, and processing code `0x2000` "Target Coordinate Conversion" says so
explicitly), and a platform position is stated by the platform's own navigation system, which the
format never names. **Never `GNSS`** — the format does not say, and in a PNT-denied environment
`GNSS` is the one value whose wrongness costs something.

#### Velocity: the platform converts, the target does not

`Kinematics` maps cleanly for the **platform** and not at all for the **target**, and the
difference is a genuine limit of the CDM rather than an ambiguity in the format.

| Source | `Kinematics.course_deg` | `Kinematics.speed_mps` | `Kinematics.climb_mps` |
|---|---|---|---|
| Dwell Segment | `D15` Sensor Track, `BA16`, degrees CW from True North | `D16` Sensor Speed, mm/s ÷ 1000 | `D17` Sensor Vertical Velocity, dm/s ÷ 10 |
| Platform Location Segment | `L5` Platform Track | `L6` Platform Speed, mm/s ÷ 1000 | `L7` Platform Vertical Velocity, dm/s ÷ 10 |
| Target Report | — | — | — |

The platform's are a ground track and a ground speed, which is exactly what `course_deg` and
`speed_mps` are documented to hold, and vertical velocity is `climb_mps` with the sign convention
matching (`S8`, negative = descending).

**A target's `Kinematics` is `None`, always.** `D32.7` Target Velocity Line-of-Sight Component is
"the component of velocity … along the line of sight between the sensor and the reported
detection, where the positive direction is away from the sensor" — **one component of a vector**,
and the tangential component is physically unobservable to a single-look MTI radar. So the target's
speed is unknown (the radial component is a lower bound, and writing a lower bound into
`speed_mps` would state a measurement nobody made) and its course is unknown (the *direction* of
the line of sight is computable from `D7`/`D8` and the target position, but the direction of the
velocity is not). `D32.7` and `D32.8` Target Wrap Velocity park in full, and
`attributes.kinematics_basis` states that the format measured one component of a two-dimensional
quantity. That is **gap 21**, and it is a different gap from **gap 4** — that one is about
representing a velocity a source stated in full, and this one is about a velocity no single-look
radar can state in full.

`D32.8`'s own note deserves a line, because it is the one place the format invites a computation
and this row set declines it: "the tracker may consider adding multiples of twice the target wrap
velocity to field D32.7" to un-alias a Doppler-wrapped velocity. Choosing the multiple is a
tracker's decision, informed by the target's expected speed, and the standard addresses it to "the
tracker" rather than to the reader. Both values park; nothing is un-wrapped.

### Settlement 7 — The existence mask is the schema, and a skip is only safe when a length is stated

#### Mandatory, Conditional, Optional — and "No Statement", which is a fourth thing

§2.4 defines the three types: Mandatory fields "are essential to the format and must always be
sent"; Conditional fields "are dependent on the presence or absence or the value of certain other
fields"; Optional fields "are not required but may be transmitted". The Dwell and HRR Segments
carry that structure on the wire as an **existence mask** — `D1`, eight bytes, one bit per field
`D2`–`D32.18`; `H1`, five bytes, one bit per field `H2`–`H32.4` — and the mask's own tables
(Figures 3-1 and 3-4) fix the Mandatory bits at 1.

**But §2.4 also creates a fourth category that the mask cannot express**: "For Mandatory Fields for
which no information is being provided, a **'No Statement' value** may be transmitted, where the No
Statement value is defined in the Value Range column of the corresponding Segment Layout Table."
So a Mandatory field is always *present* and may still say nothing, and the sentinel is
per-field: `65535` for `J16`–`J21` and `J23`, `255` for `J19`, `J24`–`J26` and `J2`/`R24`, `180.0`
for `J22`, `0` for `H11`/`H12`/`H17`/`H18`/`H19` and `P6`, all-zeros for `D32.16`/`D32.17`, the
string `"None"` for `R25`, and BCS spaces for `P5`, `M1`, `M2` and `M4`.

Every one of those lands in `attributes.unavailable_fields`, and **not** as a value. This is the
AIS sentinel lesson in a format that documents its sentinels: a `J24` of 255 is not an MDV of
25.5 m/s, a `J22` of 180.0 is not a cross-range standard deviation of half a circle, and a `P6` of
0 is "no codes apply" rather than a codeword. The distinction the basis has to preserve is between
**a field the mask says is absent** (the source chose not to send it) and **a field present with a
No Statement value** (the source sent it and said it does not know) — two different facts, and
`attributes.unavailable_fields` records which of the two applied for every one.

#### The four mask rules, and the one exception the standard states itself

1. **A Mandatory bit cleared is a refusal, quoting the mask.** Figures 3-1 and 3-4 give the value
   `1` for every Mandatory bit, so a cleared one is a packet with an error, and the fields after it
   cannot be located: the segment is a sequence of variable-length fields whose offsets depend on
   the mask, so one wrong bit desynchronises everything downstream. The refusal quotes the eight or
   five mask bytes in hex, the bit position, and the field it belongs to.
2. **A Conditional field present without its governing condition, or absent with it, is a
   refusal.** The standard states the conditions as co-presence groups, in the fields' own text,
   and they are checked as groups: `{D10, D11}` iff `{D32.4, D32.5}`; `{D32.2, D32.3}` xor
   `{D32.4, D32.5}`; `{D12, D13, D14}` together; `{D15, D16, D17}` together; `{D18, D19, D20}`
   together; `{D21, D22, D23}` together; `{D32.12, D32.13, D32.14, D32.15}` only if
   `{D12, D13, D14}` were sent, with `D32.14` additionally requiring `D32.6` and `D32.15`
   additionally requiring `D32.7`; `{D32.7, D32.8}` together; `{D32.16, D32.17}` together;
   `{H6, H7}` at least one of the two; `H5` present iff `H23` ∈ {1,2,3,4}; `H15` required unless
   `H23` ∈ {1,3}; `{H21, H22}` required if `H23` ∈ {4,6}; `H32.2` populated iff `H26` ≠ 0;
   `{H32.3, H32.4}` required when the range-Doppler matrix is sparse. **Every violated group is
   listed in one refusal**, prefixed by its group name — the STANAG 4676 rule that first-match-wins
   means a producer only ever hears about whichever check ran first.
3. **An Optional field's absence is simply an absence**, and is not in `unavailable_fields`: the
   source has not said it does not know, it has said nothing, which is what Optional means.
   `D28`/`D29`/`D30` are the exception the standard writes itself — "If at least one of fields D28,
   D29, or D30 is present, then any omitted field shall represent an angle of **zero** degrees" —
   so a partial sensor-orientation triple has two stated values and one stated zero, and the zero
   goes in as a value with the basis naming the rule. This is NITS's "an omitted `relTime` means
   zero" reached in a different format: a *stated* default is not an unknown.
4. **`D5 = 0` overrides the mask for the target report bits, and the standard says so.** §3.4.1:
   "As an exception to the normal rules for existence masks, if field D5=0 (i.e. no targets
   present) then it shall be assumed that the target report fields (D32.1-D32.18) are **not
   present even if the existence mask indicates they are**. This allows producers to implement
   constant values in the existence mask for these fields regardless of whether targets are
   reported." So a Dwell Segment with `D5 = 0` and target-report bits set is **conformant**, not a
   rule-2 violation, and reading those bits would consume bytes belonging to the next segment. The
   exception is checked first, and `attributes.mask_basis` records that it fired.

#### Unsupported is not the same as erroneous, and the difference is whether the parse can continue deterministically

**Amendment 5 struck the authority the Phase 1 text cited here.** That text grounded this split on
guide Annex G Subtest 18's two bullets — "alert the user … and provide an option to either abort
the process or continue" versus "alert the user and abort the process" — and it cannot: Subtest 18
sits in the annex this row set discredits two settlements earlier over its `P6` table, and an annex
whose own references name STANAG 4607 Edition 2 of 2007 is not authority for behaviour under
Edition A. §3.2.1 is **silent** on receiver behaviour, so there is no normative statement of the
split anywhere in the pinned set.

**So the split stands on something the adapter can verify for itself: whether the byte offsets of
everything after the problem are still known.**

- A **reserved or extension segment type** costs nothing to skip and the skip is *exact*, because
  `S2` "specif[ies] the number of bytes in this header and the data segment which follows this
  header" (§3.2.2). §3.2.1 reserves those codes for future use, so the adapter knows it does not
  know the contents, and it knows precisely where they end. The parse continues with no guessing.
- A **mask violation, a broken conditional group or a size mismatch** destroys exactly that. A
  Dwell Segment is a sequence of variable-length fields whose offsets are a function of `D1`, so
  one wrong bit desynchronises everything after it, and continuing means reading values from the
  wrong bytes. There is nothing to continue *from*.

Skipping is available where the format hands over a length and withheld where it does not. That is
a stronger footing than a stale annex's preference, and it is checkable against §3.2.1 and §3.2.2.

| Case | Behaviour | Where it is recorded |
|---|---|---|
| a **reserved or extension segment type** (4, 7, 8, 9, 11, 14–100, 103–127, 128–255) | its `S2` size is used to skip it exactly; **skip-and-record, never a silent skip**; **the rest of the packet translates** | `attributes.source_extras.unsupported_segments[]` with the type code, the size and the raw bytes — or, where a deployment caps the parked volume, the type code, the size and a count with the omission stated — plus `attributes.unresolved_raw` |
| an **unrecognised enumeration value** in a defined field — a reserved `P7`, `M3`, `J2`, `J14`, `J27`, `J28`, `H16`, `H17`, `H18`, `H23`, `A18` or `D32.10` | the value is parked, the object is still produced. The field's *length* is known, so the parse never loses its place | `attributes.unresolved_raw` |
| a **mask violation, a broken conditional group, a size mismatch, a wrong `P1`, a missing or contradicted reference date, a `synthetic` conflict** | **refusal** | the refusal message, quoting the offending values |

**A silent skip is forbidden, and that is the amendment's operative half.** A consumer holding the
output of this adapter must be able to tell that the packet contained material the adapter did not
read — otherwise a document carrying a Controlled Extension it cannot decode is indistinguishable
from one that carried nothing, and the Advanced Dwell Segment (`S1 = 128`) is precisely a segment
whose *absence from the output would look like an empty dwell*. So every skipped segment is logged
and recorded: at minimum its type code, its size and a count, and by default its bytes verbatim.
The floor is the count, never nothing.

**There is no checksum, and the format says whose problem that is.** §2.2: "The data format
described herein allows for loss of packets but assumes that the packets received are error-free
… The format requires these functions to be accomplished by the lower layers of the communications
media." So `attributes.integrity_basis` records that the packet passed structural checks — `P2`
against the byte count, each `S2` against the segment boundaries, each mask against its field
sequence — and **nothing more**, and that the format carries no cryptographic or checksum
protection of any kind. That is the third format in this document with nothing to verify, and a
consumer comparing a GMTIF contact with a CAT021 one should be able to see that neither was
checked.

### Settlement 8 — A translator owes no fusion. Stated once, and for the sixth time

Every cross-payload and cross-object join this format invites is refused, and they are named
individually rather than covered by a principle:

- **Associating target reports across dwells** into tracks. Settlement 5.
- **Reassembling a dwell split across Dwell Segments or packets.** §3.4.32 and guide §D.2/§D.5.
- **Resolving an HRR Segment's `H2`/`H3`/`H5` to a target report** outside this packet. Within the
  packet the reference is followed only to borrow the dwell's `D6` as the HRR `Event`'s
  `observed_at`, which is reading a time from the same payload, not joining two objects.
- **Resolving a Processing History Segment's `<DataSetID>` chain** — `C2`–`C5` naming the original
  radar job and `C6.2`–`C6.5` naming each modifying system — to the packets those jobs produced.
  **Gap 14** and **gap 19**.
- **Resolving a truth tag to a DIS Entity State PDU.** Settlement 4.
- **Matching a Job Acknowledge Segment to the Job Request Segment it answers** via `R2`/`A3`
  Requestor Task ID. Both are parked whole and neither is an object.
- **Applying the un-aliasing arithmetic `D32.8` suggests.** Settlement 6.
- **Ordering dwells by `D2`/`D3` across packets** to build a revisit history. `D3` wraps and `D2`
  resets, both by §3.4.2 and §3.4.3, so the sequence is only interpretable with state the adapter
  does not hold.

The material for every one of these is carried in full. Doing them is the consumer's.

### How to read the row sets

One table per header or segment, in the order the standard lists them, and **one row per field**.
The left column names the field by the standard's own identifier and name (`D32.10 Target
Classification`); the **M/C/O** column gives the standard's own Mandatory/Conditional/Optional
marking; the **Form** column gives the standard's data type and, where it matters, the unit.
Nothing is omitted silently: a field the adapter declines appears with its reason in the Notes
column and, where a whole segment is declined, in the declines table below.

Two format-wide facts that would otherwise be repeated on two hundred rows:

- **Alphanumeric fields are BCS, left-justified, space-padded.** §2.3 and Annex A: valid codes are
  `0x20`–`0x7E` plus LF, FF and CR, "the use of ECS characters in this standard shall be restricted
  to the BCS Subset", and "alphanumeric fields shall be left-justified, with unused bytes filled
  with the ISO Basic Character Set (BCS) space character (hexadecimal 0x20)". Trailing spaces are
  stripped on ingest and restored on egress; an all-spaces field is a stated absence and lands in
  `unavailable_fields`; a byte outside the BCS is a packet with an error and a refusal, because
  §2.3's restriction is a "shall".
- **Everything is big-endian and byte-aligned.** Annex C-4.1: "All data will be passed in a
  'Big-Endian' manner, with the most-significant byte passed first", and §2.3: "All fields and
  subfields shall be defined at the byte boundaries (i.e., there are no half-bytes included in the
  structure)." `B16`, `B32` and `H32` are **sign-magnitude**, not two's complement — Annex C-4.5,
  "The numbers are expressed in sign magnitude" — while `S8`–`S64` and `SA16`/`SA32` are two's
  complement. Reading a `B16` as two's complement gets every negative value wrong, and the fields
  that use it are `D26`, `H11`, `H12`, `H15`, `H19`, `H30` and `H31`.

### Row set — Packet Header

Ten fields, all Mandatory, 32 bytes, on every packet. Nothing here is an object; all of it is
parked on every object the packet produces, because every one of them is a fact about all of it.

| GMTIF | M/C/O | Form | CDM field | Status | Notes |
|---|---|---|---|---|---|
| `P1 Version ID` | M | 2 A | `Entity.attributes` | `gmti 1.0.0` | `"41"` = Edition A Version 1. **The version gate**: any other value is refused with the value quoted, per settlement 1. Parked so a consumer can see what it was decoded as |
| `P2 Packet Size` | M | 4 I32, bytes | `Entity.attributes` | `gmti 1.0.0` | 32 to 4 294 967 295. Checked against the actual byte count and against the sum of the segment sizes; a mismatch is a refusal. Parked because a consumer deduplicating a retransmission needs it |
| `P3 Nationality` | M | 2 A | `Entity.source_ids` | `gmti 1.0.0` | digraph; `XN` for NATO platforms. **Half of the one real identity in the format** — see `P8`. Also parked at `attributes.platform_nationality` and explicitly **not** read as an affiliation |
| `P4 Packet Security – Classification` | M | 1 E8 | `Entity.attributes` | `gmti 1.0.0 · parked` | `1` TOP SECRET, `2` SECRET, `3` CONFIDENTIAL, `4` RESTRICTED, `5` UNCLASSIFIED. Parked verbatim as part of the label triple. **Gap 12**; settlement 3 |
| `P5 Packet Security – Classification System` | M | 2 A | `Entity.attributes` | `gmti 1.0.0` | the digraph that says whose RESTRICTED `P4` means and whose codewords `P6` uses. All-BCS-spaces = no system applies, a **stated** absence. **It travels with `P4` and `P6` structurally** |
| `P6 Packet Security – Code` | M | 2 FL | `Entity.attributes` | `gmti 1.0.0` | 16 caveat bits. Parked as **the raw integer plus the set bit positions**, never as codeword names: the standard and the guide publish two different meanings for the same sixteen bits, and the standard says each nation defines its own. `0x0000` = no codes, a stated absence |
| `P7 Exercise Indicator` | M | 1 E8 | `Entity.attributes` | `gmti 1.0.0` | operation/exercise × real/simulated/synthesized. **Parked, and does not set `source.synthetic`** — settlement 4. A contradiction with the deployment declaration is a logged refusal; a reserved value parks in `unresolved_raw` |
| `P8 Platform ID` | M | 10 A | `Entity.source_ids` | `gmti 1.0.0` | tail number for aircraft, satellite name plus designator for spaceborne. **Nation-guaranteed unique within the owning nation's fleet** (§3.1.8), so `P3` + `P8` is a globally unique key and the platform `Entity`'s `SourceId.external_id`. **Not `attributes.callsign`** — it names the platform, not a contact — but it is the string an operator reads, which is **gap 1** |
| `P9 Mission ID` | M | 4 I32 | `Entity.attributes` | `gmti 1.0.0` | "assigned by the platform … uniquely identifies the mission for the platform" — platform-scoped, so a key component and never a key. Part of the target `entity_id` composite |
| `P10 Job ID` | M | 4 I32 | `Entity.attributes` | `gmti 1.0.0` | 0 if the packet carries no Dwell, HRR or Range-Doppler segment; the segments' non-zero Job ID otherwise (§3.1.10). **Both directions are checked and they resolve differently.** A Dwell Segment under `P10 = 0` is a **refusal**, because §3.4 says a Dwell Segment "may be sent only if the Job ID in the associated Packet Header is not equal to zero" and a zero leaves the dwell belonging to no job a consumer can name. A non-zero `P10` with no dwell data is **recorded, not refused**: it violates §3.1.10's "shall" and nothing downstream is ambiguous, because there is no dwell data for the header's Job ID to apply to |

### Row set — Segment Header

| GMTIF | M/C/O | Form | CDM field | Status | Notes |
|---|---|---|---|---|---|
| `S1 Segment Type` | M | 1 E8 | `Entity.attributes` | `gmti 1.0.0` | the enumeration below. Parked as the ordered list of segment types the packet carried, which is the only record of the packet's shape once its contents have become objects |
| `S2 Segment Size` | M | 4 I32, bytes | `Entity.attributes` | `gmti 1.0.0` | "the number of bytes in this header and the data segment which follows", so it **includes** the 5-byte header. Checked against `P2` minus the packet header, and against the segment's actual field consumption; a mismatch is a refusal. **It is also what makes skipping an unsupported segment exact** rather than a guess |

### Row set — the reserved and extension segment type codes

Every value of `S1` is accounted for. The defined ten have their own row sets below; these are the
rest, and each one states what happens on encounter.

**None of them is a refusal, and none of them is a silent skip either.** The behaviour is
**skip-and-record**, and it stands on two clauses of the standard and nothing else (amendment 5
struck the guide citation that used to appear here): §3.2.1 reserves these codes "for future use",
so the adapter knows it cannot decode them, and §3.2.2 makes `S2` "the number of bytes in this
header and the data segment which follows", so the skip is exact rather than a resynchronisation
guess. Refusing the packet instead would discard the Dwell Segments beside the undecodable one,
which is a larger loss than not decoding a segment nobody has defined — but skipping *silently*
would be worse than either, because the output would then be indistinguishable from a packet that
carried nothing. Every row below therefore reads **skip by `S2`, park, log and record**, and the
record names the type code and the size even where a deployment caps the parked bytes.

| `S1` | Standard's name | On encounter | Notes |
|---|---|---|---|
| 4 | **Reserved** (the Range-Doppler Segment) | skip by `S2`, park the bytes, log and record in `unresolved_raw` — never a silent skip | Table 2-1 lists a Range-Doppler Segment and §3 says "A preliminary description of the Range-Doppler Segment is provided in the associated guidance for this standard (AEDP-4607.1)". **Preliminary is not normative**, and §3.6 in the standard itself is the single word "RESERVED". Deferred in the declines table |
| 7 | Low Reflectivity Index (LRI) Segment | skip by `S2`, park, log and record — never a silent skip | §3.9: "[THIS PARAGRAPH IS RESERVED FOR FUTURE DEFINITION]" |
| 8 | Group Segment | skip by `S2`, park, log and record — never a silent skip | §3.10, same |
| 9 | Attached Target Segment | skip by `S2`, park, log and record — never a silent skip | §3.11, same |
| 11 | System-Specific Segment | skip by `S2`, park, log and record — never a silent skip | §3.13, same |
| 14–100 | Reserved for new Segments | skip by `S2`, park, log and record — never a silent skip | Table 3-6 |
| 103–127 | Reserved for future use | skip by `S2`, park, log and record — never a silent skip | Table 3-6 |
| 128–255 | **Reserved for Extensions** | skip by `S2`, park, log and record — never a silent skip, and the record names the registered extension where the code has one | Five are registered and approved in guide Annex L.3.1: **128** Advanced Dwell, **129** Advanced Job Definition, **130** Advanced Platform Location, **131** Target Centroid, **132** Releasability. **Their field definitions do not exist in any pinned document** — §L.4 reads "(TO BE PROVIDED)" — so this is a blocker, not a decline. `132 Releasability` is the one that will matter most, being a security extension over the fields of settlement 3 |

**§3.2.1 and Table 3-6 disagree about this table and the disagreement is recorded rather than
resolved.** §3.2.1's prose says values "4, 7, 8, 9, 11, 14-100, and **103-255** are reserved for
future use", folding the extension range into the undefined one; Table 3-6 splits `103-127`
(future use) from `128-255` (Reserved for Extensions), and Annex L has actively assigned five of
them since 2008. The table and the registry agree with each other and against the prose, so they
are followed — but the behaviour is identical either way, which is why this costs nothing.

### Row set — Mission Segment

Sent "at least once every two minutes" (§3.3), and guide §A.1.3 recommends once per packet.
**This is the packet's date source** — settlement 2 — and it is otherwise entirely parked.

| GMTIF | M/C/O | Form | CDM field | Status | Notes |
|---|---|---|---|---|---|
| `M1 Mission Plan` | M | 12 A | `Entity.attributes` | `gmti 1.0.0` | the ATO Mission Number, or `yymmddhhnn` for spaceborne. "shall be unique for all the missions defined for that platform" — platform-scoped. All-spaces = no mission plan to send, a stated absence |
| `M2 Flight Plan` | M | 12 A | `Entity.attributes` | `gmti 1.0.0` | "provides a unique identification of the flight plan". All-spaces = a stated absence |
| `M3 Platform Type` | M | 1 E8 | `Entity.attributes` | `gmti 1.0.0` | Table 3-8, 57 assigned values `0`–`56` plus `255 = Other`, with `57–254` available for future use. **Every value parks and none maps**: the enumeration is a fleet inventory — `E-8C (Joint STARS)`, `Sentinel`, `MQ-9 Reaper`, `Stryker` — and the platform `Entity` is `PLATFORM` for all of them, so refining `entity_type` from it is impossible and refining anything else would be inventing a capability model. `0 = Unidentified` is a stated unknown; a value in `57–254` parks in `unresolved_raw`. **Not read as an affiliation**, though the list is overwhelmingly NATO hardware — that is an inference from an inventory, which is the CAT021 performance-class refusal in a new costume |
| `M4 Platform Configuration` | M | 10 A | `Entity.attributes` | `gmti 1.0.0` | the variant: model number, software release, "or identification of the platform as a test article". **A test-article marking does not set `source.synthetic`** — settlement 4's rule reaching a third field. All-spaces = a stated absence |
| `M5 Reference Time – Year` | M | 2 I16 | `Entity.attributes` | `gmti 1.0.0` | takeoff year for airborne, an epoch for spaceborne, "a time reference suitable for collection" for ground-based. **The date source, with `M6` and `M7`.** Parked as read, and the derived date is parked beside it |
| `M6 Reference Time – Month` | M | 1 I8, 1–12 | `Entity.attributes` | `gmti 1.0.0` | as `M5`. A value outside 1–12 is a refusal: there is no month 13 to record and every instant in the packet depends on it |
| `M7 Reference Time – Day` | M | 1 I8, 1–31 | `Entity.attributes` | `gmti 1.0.0` | as `M5`, and stated as UTC in its own text where `M5` and `M6` are not. A value outside 1–31, or a date that does not exist (31 February), is a refusal quoting all three fields |

### Row set — Dwell Segment, D1–D31

The dwell's own fields: the mask, the sequencing, the instant, the platform's state and the dwell
area. **This is where the platform `Entity` and its `Track` sample come from.**

| GMTIF | M/C/O | Form | CDM field | Status | Notes |
|---|---|---|---|---|---|
| `D1 Existence Mask` | M | 8 FL64 | `Entity.attributes` | `gmti 1.0.0` | **the segment's schema.** Parked verbatim as eight hex bytes, because every refusal in settlement 7 quotes it and a consumer auditing one needs the value that produced it. Figure 3-1 maps bit to field; Mandatory bits are fixed at 1; `D5 = 0` overrides the `D32.*` bits per §3.4.1 |
| `D2 Revisit Index` | M | 2 I16 | `Entity.attributes` | `gmti 1.0.0` | "the sequential count of a revisit of the bounding area in the last sent Job Definition Segment", reset to 0 when the sensor is not revisiting. Parked; part of the target `entity_id` composite. **Never used to order across packets** — settlement 8 |
| `D3 Dwell Index` | M | 2 I16 | `Entity.attributes` | `gmti 1.0.0` | "temporally sequential count of a dwell within the revisit", and "dwell counts are allowed to wrap". Parked; a key component, not a key — guide §D.2 says multiple segments may share it |
| `D4 Last Dwell of Revisit` | M | 1 FL8 | `Entity.attributes` | `gmti 1.0.0` | a completeness flag: `1` means no more dwells in this revisit. Parked and **never acted on** — waiting for the rest of a revisit is state. §3.4.4's note that `D3 = 0` with `D4 = 1` means "first and only dwell" is recorded in the basis, because it is how a non-dwelling radar expresses itself in a dwell format |
| `D5 Target Report Count` | M | 2 I16 | `Entity.attributes` | `gmti 1.0.0 · parked` | the count **in this segment**, not in the dwell (§3.4.5). Checked against the reports actually present; a mismatch is a refusal. `0` is conformant and mandatory to send — §3.4 requires a Dwell Segment "even if no targets are observed" — and that is **gap 22** |
| `D6 Dwell Time` | M | 4 I32, ms | `Event.observed_at`, `Track.samples[].observed_at` | `gmti 1.0.0` | milliseconds from midnight UTC of the `M5`/`M6`/`M7` date to the **temporal centre** of the dwell, "with the possible addition of multiples of 86400000 for multi-day missions". Exact addition, no modulo — settlement 2. Every target report in the segment shares it, which is **gap 13**. **Amendment 3**: the platform sample this field times parks `time_basis = dwell_center`, because a dwell midpoint and `L1`'s report-preparation instant are different kinds of instant in one sample list |
| `D7 Sensor Position – Latitude` | M | 4 SA32, deg | `Position.lat` | `gmti 1.0.0` | the platform's latitude at the dwell centre. Exact `SA32` conversion, LSB ≈ 4.7 mm |
| `D8 Sensor Position – Longitude` | M | 4 BA32, deg | `Position.lon` | `gmti 1.0.0` | 0–360 East, reduced to [-180, 180]. Exact, LSB ≈ 9.3 mm |
| `D9 Sensor Position – Altitude` | M | 4 S32, **cm** | `Position.alt_m` | `gmti 1.0.0` | HAE per §3.4.9, ÷ 100. **Centimetres**, against `D32.6`'s metres — settlement 6's unit table |
| `D10 Scale Factor – Latitude Scale` | C | 4 SA32, deg | `Position.lat` | `gmti 1.0.0` | multiplies `D32.4`. Sent **iff** `D32.4`/`D32.5` are; the pair `{D10, D11}` is checked as a group and a violation is a refusal. Applied in the **integer domain** per guide §E.7 |
| `D11 Scale Factor – Longitude Scale` | C | 4 BA32, deg | `Position.lon` | `gmti 1.0.0` | multiplies `D32.5`. As `D10`, and its arithmetic **wraps mod 2^32** by the guide's explicit requirement, which is the prime-meridian case |
| `D12 Sensor Position Uncertainty – Along Track` | O | 4 I32, cm | `Entity.attributes` | `gmti 1.0.0 · parked` | 1-sigma along `D15`. **Parked, never `Position.accuracy_m`** — one of two orthogonal horizontal components, and reducing them to one scalar is a convention the source did not state. **Gap 17.** Group `{D12, D13, D14}` |
| `D13 Sensor Position Uncertainty – Cross Track` | O | 4 I32, cm | `Entity.attributes` | `gmti 1.0.0` | 1-sigma orthogonal to `D15`. As `D12` |
| `D14 Sensor Position Uncertainty – Altitude` | O | 2 I16, cm | `Entity.attributes` | `gmti 1.0.0 · parked` | 1-sigma on `D9`. **Gap 6** — there is no vertical accuracy field to put it in |
| `D15 Sensor Track` | C | 2 BA16, deg | `Kinematics.course_deg` | `gmti 1.0.0` | the platform's ground track, CW from True North, [0, 360). Converts exactly; LSB 0.0055° ≈ 611 m over a 6 km leg, coarse **in the source** and not reported as an accuracy. Group `{D15, D16, D17}` |
| `D16 Sensor Speed` | C | 4 I32, mm/s | `Kinematics.speed_mps` | `gmti 1.0.0` | ground speed ÷ 1000. Group `{D15, D16, D17}` |
| `D17 Sensor Vertical Velocity` | C | 1 S8, dm/s | `Kinematics.climb_mps` | `gmti 1.0.0` | ÷ 10, negative = descending, matching the field's own sign convention. Group `{D15, D16, D17}` |
| `D18 Sensor Track Uncertainty` | O | 1 I8, deg | `Entity.attributes` | `gmti 1.0.0 · parked` | 1-sigma on `D15`. Parked — `Kinematics` carries no uncertainty at all. **Gap 17** |
| `D19 Sensor Speed Uncertainty` | O | 2 I16, mm/s | `Entity.attributes` | `gmti 1.0.0 · parked` | 1-sigma on `D16`. Parked. **Gap 17**. Group `{D18, D19, D20}` |
| `D20 Sensor Vertical Velocity Uncertainty` | O | 2 I16, cm/s | `Entity.attributes` | `gmti 1.0.0` | 1-sigma on `D17`. Note the unit: cm/s where `D17` is dm/s. Group `{D18, D19, D20}` |
| `D21 Platform Orientation – Heading` | C | 2 BA16, deg | `Entity.attributes` | `gmti 1.0.0 · parked` | the platform's **attitude**, not its track: the angle from True North to the roll axis. **Not `course_deg`** — a heading and a ground track differ by drift, and this format states both, which is the strongest available argument for **gap 7**. Rotation order is heading, then pitch, then roll, and is recorded. Group `{D21, D22, D23}` |
| `D22 Platform Orientation – Pitch` | C | 2 SA16, deg | `Entity.attributes` | `gmti 1.0.0 · parked` | positive = nose up. Parked; **gap 7** has no attitude field either. Group `{D21, D22, D23}` |
| `D23 Platform Orientation – Roll` | C | 2 SA16, deg | `Entity.attributes` | `gmti 1.0.0` | positive = clockwise from the rear; "Platform Bank Angle" is synonymous. Group `{D21, D22, D23}` |
| `D24 Dwell Area – Center Latitude` | M | 4 SA32, deg | `Entity.attributes` | `gmti 1.0.0 · parked` | **the reference point for `D32.4`.** Also parked in its own right as the dwell area's centre, which is a fact about where the radar looked — **gap 22** |
| `D25 Dwell Area – Center Longitude` | M | 4 BA32, deg | `Entity.attributes` | `gmti 1.0.0` | the reference point for `D32.5`; as `D24` |
| `D26 Dwell Area – Range Half Extent` | M | 2 **B16**, km | `Entity.attributes` | `gmti 1.0.0 · parked` | "from the near edge to the center of the dwell area". **Sign-magnitude**, not two's complement. Parked and **not made a `Geometry`**: the dwell area is a sector defined relative to the sensor position (Figure C-4), and constructing a polygon from a centre, a range half-extent and an angular half-extent is a geodesic construction plus an interpretation of a figure. **Gap 22** |
| `D27 Dwell Area – Dwell Angle Half Extent` | M | 2 BA16, deg | `Entity.attributes` | `gmti 1.0.0` | half the 3 dB beamwidth for a dwelling radar; for a non-dwelling one, "the angle between the beginning of the dwell to the center of the dwell". **Two different quantities in one field**, distinguishable only from the radar's design, so it parks with both readings named. **Never a duration** — settlement 2 |
| `D28 Sensor Orientation – Heading` | O | 2 BA16, deg | `Entity.attributes` | `gmti 1.0.0` | the sensor's or the ESA beam's rotation about the platform's local vertical, first of three. Parked. **The stated-zero rule**: if any of `D28`/`D29`/`D30` is present, an omitted one is zero degrees, and the zero is a value with the basis naming §3.4.28 |
| `D29 Sensor Orientation – Pitch` | O | 2 SA16, deg | `Entity.attributes` | `gmti 1.0.0` | second of three, above the horizontal positive. Stated-zero rule |
| `D30 Sensor Orientation – Roll` | O | 2 SA16, deg | `Entity.attributes` | `gmti 1.0.0` | third of three, clockwise from behind the face. Stated-zero rule |
| `D31 Minimum Detectable Velocity (MDV)` | O | 1 I8, dm/s | `Entity.attributes` | `gmti 1.0.0 · parked` | "the minimum velocity component, along the line of sight, which can be detected by the sensor". Parked — and this is the field that makes **gap 22** concrete: an MDV of 30 dm/s means a target moving at 2 m/s radially was *not detectable*, so the absence of a report in this dwell means something specific, and the CDM has nowhere to say it |
| `D32 < Target Reports >` | — | — | — | `gmti 1.0.0` | the container. `D5` reports of the layout below; each becomes an `Entity` and a `DETECTION` `Event`. Not itself parked, because its contents become objects |

### Row set — Dwell Segment target reports, D32.1–D32.18

One row of this table is one target report, and one target report is **one `Entity` plus one
`DETECTION` `Event`** — settlement 5.

| GMTIF | M/C/O | Form | CDM field | Status | Notes |
|---|---|---|---|---|---|
| `D32.1 MTI Report Index` | C | 2 I16 | `Entity.attributes` | `gmti 1.0.0` | "the sequential count of this MTI report **within the dwell**", sent only "if an HRR report is provided for targets in this dwell". Parked and **not the entity key**: it is dwell-scoped by its own definition and Conditional besides, so the key falls back to a positional index — settlement 5 |
| `D32.2 Target Location – Hi-Res Latitude` | C | 4 SA32, deg | `Position.lat` | `gmti 1.0.0` | exact `SA32`, LSB ≈ 4.7 mm. Group: `{D32.2, D32.3}` together, and **exclusive** with `{D32.4, D32.5}` |
| `D32.3 Target Location – Hi-Res Longitude` | C | 4 BA32, deg | `Position.lon` | `gmti 1.0.0` | 0–360 East reduced to [-180, 180]; exact, LSB ≈ 9.3 mm |
| `D32.4 Target Location – Delta Latitude` | C | 2 S16 | `Position.lat` | `gmti 1.0.0` | `(D32.4 × D10) + D24`, computed in **signed 32-bit integer** arithmetic per guide §E.7 and converted once at the end. Signed overflow, or a result outside ±90°, is a **refusal** — a latitude has no seam to wrap at |
| `D32.5 Target Location – Delta Longitude` | C | 2 S16 | `Position.lon` | `gmti 1.0.0` | `(D32.5 × D11) + D25` in **unsigned 32-bit** arithmetic, and the guide requires it to wrap mod 2^32, which is exactly the prime-meridian case. Sign of the delta selects add or subtract, per §E.7's two branches |
| `D32.6 Target Location – Geodetic Height` | O | 2 S16, **m** | `Position.alt_m` | `gmti 1.0.0` | HAE per §3.4.32.6, × 1. **Metres**, against `D9`'s centimetres. If absent, "the target height shall be interpreted as being on the earth model described in the Job Definition Segment, fields J27 and J28" — a *stated* reference to a model the packet names but does not carry, so `alt_m` is `None` and `attributes.alt_basis` records `J27`/`J28`. **Never zero**, and never a DTED lookup: fetching terrain data is a network dependency in a pure function |
| `D32.7 Target Velocity Line-of-Sight Component` | O | 2 S16, cm/s | `Entity.attributes` | `gmti 1.0.0 · parked` | radial velocity, positive away from the sensor. **Parked, never `Kinematics.speed_mps`** — it is one component of a vector whose tangential part is unobservable, so the target's speed and course are both unknown. **Gap 21.** Group `{D32.7, D32.8}` |
| `D32.8 Target Wrap Velocity` | O | 2 I16, cm/s | `Entity.attributes` | `gmti 1.0.0` | half the velocity aliasing period, so a consumer can un-wrap `D32.7`. Parked, and **the un-wrapping is not performed**: the standard addresses it to "the tracker" and the multiple depends on an expected speed nobody stated. Group `{D32.7, D32.8}` |
| `D32.9 Target SNR` | O | 1 S8, dB | `Entity.attributes` | `gmti 1.0.0 · parked` | estimated signal-to-noise ratio of the return. Parked, and **never `Entity.confidence`** — an SNR is a measurement of a signal, not a probability that the object is there. **Gap 21** |
| `D32.10 Target Classification` | O | 1 E8 | `Entity.entity_type` | `gmti 1.0.0` | the enumeration below, every value accounted for. The **type** half is read; the **live/simulated** half is recorded and does not set `source.synthetic` — settlement 4. The raw code and the standard's wording park at `attributes.target_classification` and `.target_classification_text` regardless, as AIS parks a ship type |
| `D32.11 Target Classification Probability` | O | 1 I8, % | `Entity.attributes` | `gmti 1.0.0 · parked` | "the estimated probability that the target classification appearing in field D32.10 is correctly classified". **Parked, never `Entity.confidence`**: it is a confidence about the *classification*, and `confidence` is a bare float with no stated subject, so writing 70 there would say "we are 70 % sure this object exists" about a source that said "we are 70 % sure it is a wheeled vehicle". **Gap 18** — confidence with no provenance and no subject |
| `D32.12 Target Measurement Uncertainty – Slant Range` | C | 2 I16, cm | `Entity.attributes` | `gmti 1.0.0` | 1-sigma along the line of sight. **Parked, never `accuracy_m`**: a slant is not a horizontal error and the grazing angle needed to project it is not stated. Group: sent only if `{D12, D13, D14}` were, and with `{D32.13, D32.14, D32.15}` where available |
| `D32.13 Target Measurement Uncertainty – Cross Range` | C | 2 I16, **dm** | `Entity.attributes` | `gmti 1.0.0 · parked` | 1-sigma in cross-range. Note the unit against `D32.12`'s centimetres. Parked; **gap 17** |
| `D32.14 Target Measurement Uncertainty – Height` | C | 1 I8, **m** | `Entity.attributes` | `gmti 1.0.0 · parked` | 1-sigma on `D32.6`, and conditional on `D32.6` being present. Parked; **gap 6**. Its own text mislabels the field "D34.14", which is recorded in the ambiguities table |
| `D32.15 Target Measurement Uncertainty – Target Radial Velocity` | C | 2 I16, cm/s | `Entity.attributes` | `gmti 1.0.0 · parked` | 1-sigma on `D32.7`, conditional on `D32.7` being present. Parked — `Kinematics` has no uncertainty field. **Gap 17** |
| `D32.16 Truth Tag – Application` | C | 1 I8 | `Entity.attributes` | `gmti 1.0.0` | the DIS Entity State PDU Application field, truncated to 8 bits — **or** a tagging device's battery percentage, and the condition that distinguishes them names a classification code that means something else. Parked raw under both readings' names, interpreted as neither. Settlement 4. All-zeros = a stated absence. Group `{D32.16, D32.17}` |
| `D32.17 Truth Tag – Entity` | C | 4 I32 | `Entity.attributes` | `gmti 1.0.0` | the DIS Entity field — **or** "the tag identification number transmitted by a tagging device", which is the one genuine persistent real-world identifier in the format and the one this row set cannot safely key on. **Never a `SourceId`**; deferred on a custodian's erratum. All-zeros = a stated absence |
| `D32.18 Target Radar Cross Section` | O | 1 S8, dB/2 | `Entity.attributes` | `gmti 1.0.0 · parked` | RCS in square metres expressed in half-decibels, so the decibel value is `D32.18 / 2` dBsm and the area is `10^(D32.18/20)` m². Parked as the raw half-decibel integer **and** the dBsm value, and never as square metres: the exponentiation turns a quantised estimate into a precise-looking area, and an RCS is a property of the return rather than of the object. **Gap 21** |

#### `D32.10` Target Classification — every one of the 256 values accounted for

The `entity_type` collapse is the CAT021 rule: a classification does not generally refine the CDM's
type, because a tracked vehicle, a wheeled vehicle and a small vehicle are all `PLATFORM`, and
inventing a finer CDM distinction would put a judgement in a translator. **There are no
exceptions here** — every value either maps to `PLATFORM` or parks as `UNKNOWN` — and the large
abstention is argued value by value rather than asserted.

**Amendment 1 removed the one exception this table used to claim.** Codes 5 and 16 mapped to
`FACILITY` on the reasoning that a rotating antenna that does not move is a fixed structure, which
read as the ADS-B/CAT021 obstacle exception reached through a third vocabulary. It is not that
exception and the difference is the whole point: ADS-B's category set C says *obstacle* and
CAT021's codes 22–24 say *fixed ground or tethered obstruction* — both name the thing. `Stationary
Rotator` and `Ground Rotator` name a **Doppler signature class**: a return whose spectrum is
consistent with a rotating scatterer. Inferring an installation from a motion characteristic is
precisely the inference this row set refuses for `M3` Platform Type, where an inventory of NATO
hardware is not read as an affiliation, and refusing it there while making it here would be the
rule admitting an exception whenever the label sounded architectural. Both map `UNKNOWN` with the
raw value and the standard's wording parked.

| Code | Standard's wording | `Entity.entity_type` | Note |
|---|---|---|---|
| 0 | No Information, Live Target | `UNKNOWN` | a **stated absence** of classification, named in `attributes.unavailable_fields`. Not `PLATFORM`: unlike ADS-B, where every contact is an aircraft, this format has no class-wide default |
| 1 | Tracked Vehicle, Live | `PLATFORM` | |
| 2 | Wheeled Vehicle, Live | `PLATFORM` | |
| 3 | Rotary Wing Aircraft, Live | `PLATFORM` | |
| 4 | Fixed Wing Aircraft, Live | `PLATFORM` | |
| 5 | Stationary Rotator, Live | `UNKNOWN` | **amendment 1 reversed this from `FACILITY`.** A rotator class is a statement about the *return's* spectrum, not about a structure — the format never says the scatterer is installed, mounted, permanent or man-made. `FACILITY` asserts an installation from a motion characteristic; `SENSOR` additionally asserts a function. Raw value and wording parked |
| 6 | Maritime, Live | `PLATFORM` | a vessel |
| 7 | Beacon, Live | `UNKNOWN` | a cooperative emitter, which may be on a vehicle, on a structure or on the ground. Every CDM member would state a host the source did not |
| 8 | Amphibious, Live | `PLATFORM` | |
| 9 | Person, Live | `UNKNOWN` | **the most uncomfortable row, and it diverges from the shipped CAT021 adapter deliberately.** There, `PLATFORM` is the class-wide default and a parachutist is an oddity inside it; here there is no default, and `UNIT` names a military formation while `EVACUEE_GROUP` names a humanitarian role — both state something specific and false. `UNKNOWN` with the wording parked loses nothing that the raw does not carry. **The divergence is recorded with both arguments in gap 20 and marked a 1.1.0 resolution question** (amendment 7); the CAT021 adapter is not touched |
| 10 | Vehicle, Live | `PLATFORM` | |
| 11 | Animal, Live | `UNKNOWN` | no member, and none of them is close |
| 12 | Large Multiple-Return, Live Land Target | `UNKNOWN` | **an unresolved group of objects**, not one object. `EVACUEE_GROUP` is the CDM's only plural member and it names a specific humanitarian category. The count is unstated, so even `Entity` is a slight overstatement — one object standing for several |
| 13 | Large Multiple-Return, Live Maritime Target | `UNKNOWN` | as 12 |
| 14 | Clutter, Live | `UNKNOWN` | **an explicit statement that this is not an object.** The CDM has no way to emit a detection while denying that anything is there, so the `Entity` is emitted with `UNKNOWN` and `attributes.target_classification_text` carries the denial. New in Edition A — settlement 1 |
| 15 | Phantom Live | `UNKNOWN` | as 14: a phantom is a false detection, stated as such. New in Edition A |
| 16 | Ground Rotator Live | `UNKNOWN` | as 5, and reversed with it. "Ground" locates the return, it does not make the scatterer a structure. New in Edition A |
| 17 | Small Vehicle, Live | `PLATFORM` | New in Edition A |
| 18 | Low-slow Flyer, Live | `PLATFORM` | New in Edition A. §1.1 says the format's scope includes "targets flying at low speeds close to the surface of the earth", so this is in scope rather than an anomaly |
| 19–125 | Reserved | `UNKNOWN` | parked in `unresolved_raw`: the source said something this adapter cannot use. **In Edition 3 this range began at 14** |
| 126 | Other, Live | `UNKNOWN` | a stated "none of the above", which is different from 0 and from 127 and the basis says which |
| 127 | Unknown, Live | `UNKNOWN` | a **stated unknown** — §3.4.32.10: "If a target cannot be classified, it shall be marked as 'unknown'" — so unlike 0 it is not in `unavailable_fields` |
| 128–141 | the same fourteen classes, Simulated | as 0–13 above | **the type half is read and the simulated half is only recorded.** `128 + n` maps to `n` for `n = 0..13` and **for no other n**. Includes `133` Stationary Rotator, Simulated, which parks as `UNKNOWN` with its live twin under amendment 1 |
| 142 | **Tagging Device** | `UNKNOWN` | **the value that breaks the halves.** No live counterpart, no "Simulated" in its name, and §3.4.32.16's condition — "if the MTI Target in this report is simulated **or** a tagging device is detected" — is a disjunction, so the standard itself treats a tagging device as distinct from simulation. **Exempt from the intra-payload simulation conflict check, and the exemption is keyed on the LABEL rather than on 142** (amendment 6): the value has been `140`, then `143` in Edition 3, then `142` here, so a rule written against the number would silently change behaviour on the next renumbering. Ambiguity 3 has the trail |
| 143 | Reserved | `UNKNOWN` | parked in `unresolved_raw`. Also exempt from the conflict check, and for a *weaker* reason than the `Tagging Device` label's: the table does not mark it Simulated, but no clause of the standard says what it is either — so the exemption here is withholding an inference rather than reading a stated distinction, and the basis says which. It carried `Tagging Device` in Edition 3 |
| 144 | Clutter, Simulated Target | `UNKNOWN` | mirrors **14** at an offset of +130. `144 - 128 = 16` is Ground Rotator Live, which is what an arithmetic decoder would say |
| 145 | Phantom Simulated | `UNKNOWN` | mirrors 15 |
| 146 | Ground Rotator Simulated | `UNKNOWN` | mirrors 16, and reversed with it |
| 147 | Small Vehicle, Simulated | `PLATFORM` | mirrors 17 |
| 148 | Low-slow Flyer, Simulated | `PLATFORM` | mirrors 18 |
| 149–253 | Reserved | `UNKNOWN` | `unresolved_raw`. In Edition 3 this range began at 143 |
| 254 | Other, Simulated | `UNKNOWN` | mirrors 126 |
| 255 | Unknown, Simulated | `UNKNOWN` | mirrors 127; a stated unknown |

**So: eighteen of the forty-three named values map to a CDM member that carries their meaning** —
1, 2, 3, 4, 6, 8, 10, 17, 18 and their simulated twins 129, 130, 131, 132, 134, 136, 138, 147, 148,
all to `PLATFORM` — and **the other twenty-five park.** `FACILITY` appears nowhere in this table
after amendment 1, so the mapping is now uniform: a vehicle, a vessel or an aircraft is a
`PLATFORM` and everything else is `UNKNOWN` with its wording preserved.

The abstentions are not a shortage of effort. `Person`, `Animal`, `Beacon`, `Stationary Rotator`,
`Ground Rotator`, `Large Multiple-Return`, `Clutter` and `Phantom` are eight statements a ground
surveillance radar makes routinely, and `EntityType`'s eight members were designed for a different
question. That is a pressure on the enum rather than a gap of its own, and it is recorded in
**gap 20** — which amendment 1 makes four values worse.

### Row set — HRR Segment, H1–H31

High Range Resolution and Range-Doppler data for a target, or a Range-Doppler Map for an area.
**Every field parks and the segment becomes one `DETECTION` `Event` carrying its parameters** — see
the declines table for the argument. The row set is complete anyway, because a field with no row is
a field nobody decided about.

| GMTIF | M/C/O | Form | CDM field | Status | Notes |
|---|---|---|---|---|---|
| `H1 Existence Mask` | M | 5 FL40 | `Event.payload` | `gmti 1.0.0` | the segment's schema, Figure 3-4, covering `H2`–`H32.4`. Parked as five hex bytes; every HRR refusal quotes it. §3.5.1 defers the rules to §3.4.1, so the `D1` discipline applies unchanged **except** that there is no `D5`-style override here |
| `H2 Revisit Index` | M | 2 I16 | `Event.payload` | `gmti 1.0.0` | as `D2`, for the dwell this HRR data belongs to |
| `H3 Dwell Index` | M | 2 I16 | `Event.payload` | `gmti 1.0.0` | as `D3`. **With `H2`, this is how the segment borrows an instant**: if the named Dwell Segment is in this packet its `D6` becomes `observed_at`; otherwise the receipt instant does, with the basis saying so — settlement 2 |
| `H4 Last Dwell of Revisit` | M | 1 FL8 | `Event.payload` | `gmti 1.0.0` | as `D4`; parked, never acted on |
| `H5 MTI Report Index` | C | 2 I16 | `Event.payload` | `gmti 1.0.0 · parked` | points at a `D32.1` in the same dwell. Required for `H23` types 1–4, omitted for an RDM with no corresponding detection (§3.5, §3.5.5). Parked; **resolving it to a target report is a join even within the packet**, so the `Event`'s `related_entities` is populated only when the referenced report is in this packet and its `Entity` therefore has an id — otherwise the reference lands in `attributes.unresolved_references`. **Gap 19** |
| `H6 Number of Target Scatterers` | C | 2 I16 | `Event.payload` | `gmti 1.0.0` | pixels exceeding the scatterer threshold. "Either H6 or H7 or both must be reported" — checked as an at-least-one group |
| `H7 Number of Range Samples / Total Scatterers` | C | 2 I16 | `Event.payload` | `gmti 1.0.0` | range bins, or the total scatterer-record count for a sparse chip. **One field, two meanings, selected by `H23`** — parked under both names |
| `H8 Number of Doppler Samples / Pulses` | M | 2 I16 | `Event.payload` | `gmti 1.0.0` | Doppler bins in the chip. With `H7`, this is what makes the scatterer array's length predictable |
| `H9 Mean Clutter Power Relative to Peak Scatterer` | C | 1 I8, dB/4 | `Event.payload` | `gmti 1.0.0` | quarter-decibels, "uncalibrated", required for `H23 = 3`. Parked as the raw integer and the decibel value |
| `H10 Detection Threshold Relative to Peak Scatterer` | M | 1 I8, **-dB/4** | `Event.payload` | `gmti 1.0.0` | **negative** quarter-decibels: the sign is removed before encoding, so the decibel value is `-H10/4`. A sign convention stated only in the units column, and reading it as `+H10/4` inverts the threshold |
| `H11 Range Resolution` | M | 2 B16, cm | `Event.payload` | `gmti 1.0.0` | 3 dB range impulse response. **Sign-magnitude.** `0` = No Statement, so it lands in `unavailable_fields` and never as a resolution of zero |
| `H12 Range Bin Spacing` | M | 2 B16, cm | `Event.payload` | `gmti 1.0.0` | post-oversampling pixel spacing. `0` = No Statement |
| `H13 Doppler Resolution` | M | 4 H32, Hz | `Event.payload` | `gmti 1.0.0` | **`H32` is sign-magnitude with a 15-bit integer and a 16-bit fraction** — a form defined only in a footnote to Table 3-12 and added to Annex C-4.5 by guide Annex M. Decoding it as `B32` shifts every value by 2^15 |
| `H14 Doppler Bin Spacing / PRF` | M | 4 H32, Hz | `Event.payload` | `gmti 1.0.0` | as `H13`. **One field, two meanings** — a bin spacing and a pulse repetition frequency — parked under both names |
| `H15 Center Frequency` | C | 4 B32, GHz | `Event.payload` | `gmti 1.0.0` | required for every `H23` except types 1 and 3, optional for those. Parked; the CDM has no emitter-frequency field and this is not `GnssInterferencePayload.frequency_band`, which names a GNSS band |
| `H16 Compression Flag` | M | 1 E8 | `Event.payload` | `gmti 1.0.0` | `0` No Compression, `1` Threshold Decomposition (×10), `2–255` Reserved. Parked; **the compression is never undone** — decoding a threshold-decomposition scatterer array is signal processing |
| `H17 Range Weighting Function Type` | M | 1 E8 | `Event.payload` | `gmti 1.0.0` | `0` No Statement, `1` Taylor Weighting, `2` Other, `3–255` Reserved. `0` lands in `unavailable_fields` |
| `H18 Doppler Weighting Function Type` | M | 1 E8 | `Event.payload` | `gmti 1.0.0` | as `H17` |
| `H19 Maximum Pixel Power` | M | 2 B16, dB | `Event.payload` | `gmti 1.0.0` | peak scatterer's initial power. `0` = No Statement, which is awkward — 0 dB is a real power ratio — and the standard's own value range says so, so the sentinel is honoured and recorded as a sentinel |
| `H20 Maximum RCS` | O | 1 S8, dB/2 | `Event.payload` | `gmti 1.0.0 · parked` | the peak scatterer's RCS, same encoding as `D32.18` and the same refusal to exponentiate. **Gap 21** |
| `H21 Range of Origin` | C | 2 S16, m | `Event.payload` | `gmti 1.0.0` | offset from dwell centre of the first scatterer record, positive away from the sensor. Required for `H23` 4 and 6. **Not a `Position`**: it is an offset along an unstated bearing in a sensor-relative frame, which is the `LOCAL_SPHERICAL` refusal's shape without even the slot ambiguity |
| `H22 Doppler of Origin` | C | 4 H32, Hz | `Event.payload` | `gmti 1.0.0` | Doppler of the first scatterer record. Required for `H23` 4 and 6 |
| `H23 Type of HRR/RDM` | M | 1 E8 | `Event.payload` | `gmti 1.0.0` | `0` Other, `1` 1-D HRR Profile, `2` 2-D HRR Chip, `3` Sparse HRR Chip, `4` Oversized HRR Chip, `5` Full RDM, `6` Partial RDM, `7` Full Range-Pulse Data, `8–255` Reserved. **The field that governs five conditionals** (`H5`, `H15`, `H21`, `H22`, `H29`), so a reserved value makes those conditions unevaluable: the value parks in `unresolved_raw` and the conditional group checks that depend on it are **skipped with the skip recorded**, rather than being failed against a condition nobody can evaluate. Table 3-6's enumeration names `1` "1-D HRR Chip" and §3.5.23 names it "1-D HRR Profile"; both are recorded |
| `H24 Processing Mask` | M | 1 FL8 | `Event.payload` | `gmti 1.0.0` | bit 7 Clutter Cancellation, 6 Single-Ambiguity Keystoning, 5 Multi-Ambiguity Keystoning, 4–1 Spare, **0 Unknown**. Parked as the raw byte and the named bits. A mask whose only set bit is `Unknown` is a stated absence; a mask of all zeros claims that none of the three techniques was applied, which §3.5.24 qualifies — "it is generally assumed that range processing and motion compensation have been applied when necessary" — so the zero is recorded as stated rather than as "no processing" |
| `H25 Number of Bytes – Magnitude` | M | 1 I8 | `Event.payload` | `gmti 1.0.0` | 1 or 2, and **it sizes `H32.1`**. A value other than 1 or 2 is a refusal: the scatterer array's length becomes indeterminate and every byte after it is misread |
| `H26 Number of Bytes – Phase` | M | 1 I8 | `Event.payload` | `gmti 1.0.0` | 0, 1 or 2, sizing `H32.2`; `0` means "no phase data is present and H32.2 is not populated". As `H25`, any other value is a refusal |
| `H27 Range Extent in Pixels` | O | 1 I8, px | `Event.payload` | `gmti 1.0.0` | pixels in the chip's range dimension |
| `H28 Range to Nearest Edge in Chip` | O | 4 I32, cm | `Event.payload` | `gmti 1.0.0` | distance from range bin to the closest edge |
| `H29 Index of Zero Velocity Bin` | O | 1 I8 | `Event.payload` | `gmti 1.0.0` | "relative velocity to skin line", and "shall be masked out if field H23 is set to a value of 1". A present `H29` with `H23 = 1` is a conditional-group violation and a refusal |
| `H30 Target Radial Electrical Length` | O | 4 B32, m | `Event.payload` | `gmti 1.0.0 · parked` | object length computed from the HRR profile, "set to a value of 0 if HRR is not performed". Parked and **not an extent** — **gap 8**, and the sentinel means the zero is never a length |
| `H31 Electrical Length Uncertainty` | O | 4 B32, m | `Event.payload` | `gmti 1.0.0 · parked` | 1-sigma on `H30`. Parked; **gap 17** |
| `H32 <HRR Scatterer Records>` | — | — | — | `gmti 1.0.0` | the container. `H6`/`H7` records of the layout below, ordered "in range order … starting at near range" with Doppler "sequentially from negative to positive" |

### Row set — HRR scatterer records, H32.1–H32.4

| GMTIF | M/C/O | Form | CDM field | Status | Notes |
|---|---|---|---|---|---|
| `H32.1 Scatterer Magnitude` | M | 1 or 2 (per `H25`), I8/I16, **-dB/4** | `Event.payload` | `gmti 1.0.0` | power normalised to the peak scatterer. Parked **as an array**, never as a canonical field: this is signature data, not track state. The units column says `-dB/4` while §3.5.32.1 describes an unsigned quarter-decibel conversion with no sign removal, so both readings are recorded |
| `H32.2 Scatterer Phase` | C | 1 or 2 (per `H26`) | `Event.payload` | `gmti 1.0.0` | complex phase as a quantised rotation in units of 2π/256 or 2π/65536. Populated iff `H26 ≠ 0` |
| `H32.3 Range Index` | C | 2 I16, bins | `Event.payload` | `gmti 1.0.0` | range index within the chip; "must be used when the Range-Doppler matrix is sparsely populated". Table 3-13's Bytes column says `1` and its Form column says `I16`, which cannot both be true — recorded in the ambiguities table, and `I16` is followed because a 16-bit range 0–65 535 needs two bytes |
| `H32.4 Doppler Index` | C | 2 I16, bins | `Event.payload` | `gmti 1.0.0` | Doppler index within the chip; as `H32.3`, including the same Bytes/Form contradiction |

### Row set — Job Definition Segment

Sent before the first visit of a job and "periodically at least once every 30 seconds thereafter"
(§3.7). Entirely parked on the platform `Entity`: it defines the *job*, and the CDM has no object
for a sensor tasking.

| GMTIF | M/C/O | Form | CDM field | Status | Notes |
|---|---|---|---|---|---|
| `J1 Job ID` | M | 4 I32 | `Entity.attributes` | `gmti 1.0.0` | 1 to 4 294 967 295 — **never 0 here**, unlike `P10`. Cross-checked against `P10` **only where §3.1.10 makes the two equal**, which is when the packet also carries a Dwell, HRR or Range-Doppler segment; there a mismatch is a refusal. Phase 1 stated the check unconditionally and Phase 2 found that this makes a Job-Definition-only packet unrepresentable — §3.1.10 requires `P10 = 0` with no dwell data and §3.7.1 gives `J1` a floor of 1, so the two could never agree, and the guide's own Figure 2-1 draws exactly such a packet. **Ambiguity 16**, and the narrowing is what keeps that figure conformant |
| `J2 Sensor ID – Type` | M | 1 E8 | `Entity.attributes` | `gmti 1.0.0 · parked` | Table 3-15, 36 assigned values `0`–`35` plus `255 = No Statement` and `36–254` available. **Every value parks**: it names a radar model (`APY-7`, `AN/ZPY-2 (MP-RTIP)`, `SeaSpray`) and the CDM has no field for the producing sensor at all. **Gap 14.** `255` is a stated absence; `0 = Unidentified` and `1 = Other` are distinct stated values and the basis keeps them apart |
| `J3 Sensor ID – Model` | M | 6 A | `Entity.attributes` | `gmti 1.0.0 · parked` | the variant. **Gap 14** |
| `J4 Target Filtering Flag` | M | 1 FL8 | `Entity.attributes` | `gmti 1.0.0 · parked` | bit 0 area filtering within the dwell∩bounding intersection, bit 1 Area Blanking, bit 2 Sector Blanking, bits 3–7 reserved. Parked, and it is **the completeness statement for the target reports**: bits 1 and 2 say targets were removed and, in the standard's own words, "the format does not currently specify the area over which blanking has been applied". So a consumer cannot know what is missing. **Gap 22** |
| `J5 Priority (Radar Priority)` | M | 1 I8 | `Entity.attributes` | `gmti 1.0.0` | 1 (highest) to 99, and **`255` means the job has ended** — a state change hidden in a priority field. Parked, and the end-of-job value is recorded in `attributes.job_ended` rather than acted on: acting on it means holding job state |
| `J6 Bounding Area – Point A Latitude` | M | 4 SA32, deg | `Entity.attributes` | `gmti 1.0.0 · parked` | the tasked or actually-scanned area. Four corners, "given in clockwise order (Points A, B, C, and D) and must form a convex quadrilateral" — checked, and a non-convex or non-clockwise quadrilateral is a refusal, because the standard says "must". Converted to degrees and parked as a ring; **not `Event.geometry`** and **not `PlanObject.geometry`** — `PlanObject` models *our* plan drawn on somebody else's map, and a sensor's tasked area is neither an observation nor our plan. **Gap 22** |
| `J7 Bounding Area – Point A Longitude` | M | 4 BA32, deg | `Entity.attributes` | `gmti 1.0.0` | 0–360 East reduced to [-180, 180]; as `J6` |
| `J8 Bounding Area – Point B Latitude` | M | 4 SA32, deg | `Entity.attributes` | `gmti 1.0.0` | as `J6` |
| `J9 Bounding Area – Point B Longitude` | M | 4 BA32, deg | `Entity.attributes` | `gmti 1.0.0` | as `J7` |
| `J10 Bounding Area – Point C Latitude` | M | 4 SA32, deg | `Entity.attributes` | `gmti 1.0.0` | as `J6` |
| `J11 Bounding Area – Point C Longitude` | M | 4 BA32, deg | `Entity.attributes` | `gmti 1.0.0` | as `J7` |
| `J12 Bounding Area – Point D Latitude` | M | 4 SA32, deg | `Entity.attributes` | `gmti 1.0.0` | as `J6` |
| `J13 Bounding Area – Point D Longitude` | M | 4 BA32, deg | `Entity.attributes` | `gmti 1.0.0` | as `J7` |
| `J14 Radar Mode` | M | 1 E8 | `Entity.attributes` | `gmti 1.0.0` | Table 3-16, 0–5 generic (`Unspecified`, `MTI`, `HRR`, `UHRR`, `HUR`, `FTI`) and 11–144 platform-specific, with ten available-for-future-use ranges interleaved. **Every value parks**: a mode is a sensor configuration, and the closest CDM field is nothing at all. `100 = Test/Status Mode` is notable and **does not set `source.synthetic`** — settlement 4's rule reaching a fourth field |
| `J15 Nominal Revisit Interval` | M | 2 I16, deciseconds | `Entity.attributes` | `gmti 1.0.0` | reset to 0 "if the sensor is not revisiting the previous area", so `0` is a stated fact and not an absence |
| `J16 Nominal Sensor Position Uncertainty – Along Track` | M | 2 I16, **dm** | `Entity.attributes` | `gmti 1.0.0 · parked` | `65535` = No Statement. **Decimetres**, where `D12` is centimetres. Parked; §3.7.16's note states the precedence — nominals "are to be used when values are not received from the sensor" — and `Position.accuracy_m` receives neither. **Gap 17** |
| `J17 Nominal Sensor Position Uncertainty – Cross Track` | M | 2 I16, dm | `Entity.attributes` | `gmti 1.0.0` | `65535` = No Statement. As `J16` |
| `J18 Nominal Sensor Position Uncertainty – Altitude` | M | 2 I16, dm | `Entity.attributes` | `gmti 1.0.0 · parked` | `65535` = No Statement. Its text cites "field D11", which is the Longitude Scale factor; `D9` is meant. Recorded in the ambiguities table. **Gap 6** |
| `J19 Nominal Sensor Position Uncertainty – Track Heading` | M | 1 I8, deg | `Entity.attributes` | `gmti 1.0.0` | 0–45, `255` = No Statement. Parked |
| `J20 Nominal Sensor Position Uncertainty – Sensor Speed` | M | 2 I16, mm/s | `Entity.attributes` | `gmti 1.0.0` | `65535` = No Statement. Parked |
| `J21 Nominal Sensor Value – Slant Range Standard Deviation` | M | 2 I16, cm | `Entity.attributes` | `gmti 1.0.0` | `65535` = No Statement. Parked, never `accuracy_m` — a slant is not horizontal |
| `J22 Nominal Sensor Value – Cross Range Standard Deviation` | M | 2 BA16, **deg** | `Entity.attributes` | `gmti 1.0.0` | `180.0` = No Statement. **An angle, not a distance** — turning it into metres needs a range, which is why the nominal precedence chain terminates in a park |
| `J23 Nominal Sensor Value – Target Velocity LOS Component Std Dev` | M | 2 I16, cm/s | `Entity.attributes` | `gmti 1.0.0` | `65535` = No Statement. The nominal counterpart of `D32.15` |
| `J24 Nominal Sensor Value – Minimum Detectable Velocity` | M | 1 I8, dm/s | `Entity.attributes` | `gmti 1.0.0 · parked` | `255` = No Statement. The job-level `D31`. **Gap 22** |
| `J25 Nominal Sensor Value – Detection Probability` | M | 1 I8, % | `Entity.attributes` | `gmti 1.0.0 · parked` | `255` = No Statement. "Nominal probability that an unobscured ten square-meter target will be detected within the given area of surveillance, assuming the Swerling model appropriate for the particular radar target." **Never `Track.track_quality` and never `Entity.confidence`** — it is a sensor performance figure about a hypothetical target, not a confidence in anything this packet reports. **Gap 22** |
| `J26 Nominal Sensor Value – False Alarm Density` | M | 1 I8, negative dB | `Entity.attributes` | `gmti 1.0.0 · parked` | `255` = No Statement. `-10·log10(d)` where d is false alarms per m², so 60 means 1 FA/km². Parked as the raw integer **and** the FA/m² value, since the transform is exact and stated. The other half of **gap 22**: a false alarm density says how many of the reports in this packet are expected to be nothing |
| `J27 Terrain Elevation Model Used` | M | 1 E8 | `Entity.attributes` | `gmti 1.0.0` | Table 3-17: `0` None Specified, `1`–`6` DTED 0–5, `7`/`8` SRTM 1/2, `9` DGM50, `10` DGM250, `11` ITHD, `12` STHD, `13` SEDRIS, `14–255` Reserved. Parked, and it is **half of what `D32.6`'s absence refers to** — see that row. Never dereferenced: fetching DTED is a network dependency |
| `J28 Geoid Model Used` | M | 1 E8 | `Entity.attributes` | `gmti 1.0.0` | Table 3-18: `0` None Specified, `1` EGM96, `2` GEO96, `3` Flat Earth, `4–255` Reserved. Parked, and recorded in `attributes.alt_datum_basis` because guide §E.8 says heights may be orthometric when a geoid model is in use while the standard says HAE unconditionally — settlement 6. §3.7.28's note that no DTED model is specified in `J27` when `J28` is Flat Earth is checked and a violation is recorded, not refused: it is a "will" statement, not a "shall" |

### Row set — Free Text Segment

| GMTIF | M/C/O | Form | CDM field | Status | Notes |
|---|---|---|---|---|---|
| `F1 Originator ID` | M | 10 A | `Event.payload` | `gmti 1.0.0` | **Explicitly not meaningful**: the segment's own note says "fields F1 and F2 … do not have any formal significance in this standard" and sends the reader to guide Annex H. So it is parked and **never a `SourceId`** — the standard has disclaimed it |
| `F2 Recipient ID` | M | 10 A | `Event.payload` | `gmti 1.0.0` | as `F1`, and **never `related_entities`**: an addressee is not an entity reference |
| `F3 Free Text` | M | 1–65 515 A | `Event.payload` | `gmti 1.0.0` | BCS only, so a byte outside `0x20`–`0x7E` plus LF/FF/CR is a refusal per §2.3's "shall". Becomes one `STATUS_CHANGE` `Event` with `severity` `INFO` and `observed_at` = the receipt instant, because the segment states no time. **The text is never parsed** — an operator's message is not a structured field, and searching it for coordinates or callsigns would be inventing data |

### Row set — Test and Status Segment

| GMTIF | M/C/O | Form | CDM field | Status | Notes |
|---|---|---|---|---|---|
| `T1 Job ID` | M | 4 I32 | `Event.payload` | `gmti 1.0.0` | 0 to 4 294 967 295 — **`0` is permitted here** where `J1` requires non-zero, so the `P10` cross-check does not apply. Parked |
| `T2 Revisit Index` | M | 2 I16 | `Event.payload` | `gmti 1.0.0` | **range `1` to 65 535**, where `D2` and `H2` start at `0`. An off-by-one against its own siblings, recorded in the ambiguities table and neither corrected nor refused |
| `T3 Dwell Index` | M | 2 I16 | `Event.payload` | `gmti 1.0.0` | as `T2`, range `1` to 65 535 against `D3`'s `0` |
| `T4 Dwell Time` | M | 4 I32, ms | `Event.observed_at` | `gmti 1.0.0` | the same arithmetic as `D6`, against the same `M5`/`M6`/`M7` date, including the multi-day addition (§3.12.4). **So a Test and Status Segment needs the reference date and is subject to settlement 2's three paths** |
| `T5 Hardware Status` | M | 1 FL | `Event.payload` | `gmti 1.0.0` | one bit each for Antenna, RF Electronics, Processor, Datalink and Calibration Mode, **where 1 = FAIL**. Parked as the raw byte and the named failures. **`Event.severity` is not raised from it** — see the fills table: grading a datalink failure is an operational judgement, and the format grades nothing |
| `T6 Mode Status` | M | 1 FL | `Event.payload` | `gmti 1.0.0` | one bit each for Range, Azimuth, Elevation and Temperature limits, **where 1 = outside the operational limit**. As `T5` |

### Row set — Processing History Segment

Transmitted every three minutes when processing has been applied, and omitted entirely when it has
not (guide FAQ Q11: "If processing is not applied to the original radar job, then the Processing
History Segment is not transmitted"). **Its absence therefore means the data are unmodified**,
which is a fact worth recording and is recorded in `attributes.processing_history_absent`.

| GMTIF | M/C/O | Form | CDM field | Status | Notes |
|---|---|---|---|---|---|
| `C1 Processing History Count` | M | 1 I8 | `Event.payload` | `gmti 1.0.0` | 1 to 255 records. Checked against the records present; a mismatch is a refusal. Guide FAQ Q11's own worked example shows `C1 = 3` beside a single first record, contradicting its text — recorded in the ambiguities table |
| `C2 Based on Nationality ID` | M | 2 A | `Event.payload` | `gmti 1.0.0 · parked` | the **original** radar job's `P3`. With `C3`–`C5` this is the `<DataSetID>` of the data this packet is derived from — a typed, directed reference to another packet, resolved never. **Gap 19** |
| `C3 Based on Platform ID` | M | 10 A | `Event.payload` | `gmti 1.0.0 · parked` | the original job's `P8`. **Gap 14** and **gap 19** |
| `C4 Based on Mission ID` | M | 4 I32 | `Event.payload` | `gmti 1.0.0` | the original job's `P9` |
| `C5 Based on Job ID` | M | 4 I32 | `Event.payload` | `gmti 1.0.0` | the original job's `P10`, 1 to 4 294 967 295 |
| `C6 <Processing Records>` | M | — | — | `gmti 1.0.0` | the container; `C1` records of the layout below |
| `C6.1 Processing History Sequence Number` | M | 1 I8 | `Event.payload` | `gmti 1.0.0` | the record's position in the chain, 1 to 255. **The chain order is preserved and the chain is not walked** |
| `C6.2 Nationality ID of Modifying System` | M | 2 A | `Event.payload` | `gmti 1.0.0 · parked` | the modifying system's `<DataSetID>`, with `C6.3`–`C6.5`. **Gap 14** — this is a producing system named as a first-class fact, and `SourceRef` names the adapter |
| `C6.3 Platform ID of Modifying System` | M | 10 A | `Event.payload` | `gmti 1.0.0` | as `C6.2` |
| `C6.4 Mission ID of Modifying System` | M | 4 I32 | `Event.payload` | `gmti 1.0.0` | as `C6.2` |
| `C6.5 Job ID of Modifying System` | M | 4 I32 | `Event.payload` | `gmti 1.0.0` | as `C6.2` |
| `C6.6 Processing Performed` | M | 2 FL | `Event.payload` | `gmti 1.0.0 · parked` | Table 3-23's sixteen bits: Area Filtering, Target Classification Filtering, LOS Velocity Filtering, SNR Filtering, De-clutter Filtering, Bandwidth Filtering, Revisit Filtering, Location Adjustment, Geoid Adjustment, Location Registration, Time Filtering, Security Filtering, Data Augmentation, Target Coordinate Conversion, and two reserved. Parked as the raw integer and the named operations. **Eight of the fourteen are eliminations** — filtering — so this field is the closest the format comes to saying what is missing, and it says only *that* something was removed and never *what*. **Gap 22.** `0x0800 Security Filtering`, "the elimination of certain fields to lower the classification level", interacts with settlement 3 and is recorded beside the label |

### Row set — Platform Location Segment

Sent "during periods in which the sensor is not collecting data" (§3.15). **Every field maps** —
this is the only segment in the format with no parked field at all, and guide §E.8 is why the
samples join the same `Track` as the Dwell Segment's sensor positions.

| GMTIF | M/C/O | Form | CDM field | Status | Notes |
|---|---|---|---|---|---|
| `L1 Location Time` | M | 4 I32, ms | `Track.samples[].observed_at` | `gmti 1.0.0` | milliseconds from midnight of the `M5`/`M6`/`M7` date "to the time the report is prepared", with the same multi-day addition as `D6`. **Note that it times the report's preparation, not an observation** — the nearest thing to a source-side creation time in the format, and it is used as the sample instant because it is the only instant the segment has. **Amendment 3**: the sample parks `time_basis = report_prepared` at `attributes.platform_track_points[]`, so it is never averaged against a `D6`-sourced dwell-centre sample unknowingly |
| `L2 Platform Position – Latitude` | M | 4 SA32, deg | `Track.samples[].position.lat` | `gmti 1.0.0` | exact `SA32` |
| `L3 Platform Position – Longitude` | M | 4 BA32, deg | `Track.samples[].position.lon` | `gmti 1.0.0` | 0–360 East reduced to [-180, 180] |
| `L4 Platform Position – Altitude` | M | 4 S32, **cm** | `Track.samples[].position.alt_m` | `gmti 1.0.0` | HAE, ÷ 100. **Centimetres**, matching `D9` and not `D32.6` |
| `L5 Platform Track` | M | 2 BA16, deg | `Kinematics.course_deg` | `gmti 1.0.0` | ground track CW from True North. Reaches the platform `Entity`'s `Kinematics` only when this is the latest platform position in the packet — otherwise parked per sample, which is **gap 16** |
| `L6 Platform Speed` | M | 4 I32, mm/s | `Kinematics.speed_mps` | `gmti 1.0.0` | ÷ 1000. As `L5` |
| `L7 Platform Vertical Velocity` | M | 1 S8, dm/s | `Kinematics.climb_mps` | `gmti 1.0.0` | ÷ 10, negative = descending. As `L5` |

**`Kinematics` hangs off `Entity` and there is exactly one of it, while this segment can appear
many times in one packet.** So a packet with four Platform Location Segments yields a four-sample
`Track`, one `Kinematics` from the last of them, and three parked velocity triples keyed by sample
index. That is **gap 16** — no per-sample extension — arriving from a fourth format, and here it
bites on the platform's own state rather than on a target's.

### Row set — Job Request Segment

"Recommended … and not mandatory for this format" (§3, §4). **Every field parks and nothing becomes
an object** — see the declines table for why tasking is out of CDM scope. The rows exist because a
segment with no rows is a segment nobody decided about, and because a future release that grows a
tasking object will need them.

| GMTIF | M/C/O | Form | CDM field | Status | Notes |
|---|---|---|---|---|---|
| `R1 Requestor ID` | M | 10 A | — | `gmti 1.0.0` | who is asking. Parked whole with the segment; **not a `SourceId`** — the requestor is not the subject of any object here |
| `R2 Requestor Task ID` | M | 10 A | — | `gmti 1.0.0` | "an identifier for the tasking message". Matched to `A3` by a consumer, never here — settlement 8 |
| `R3 Priority (Requestor Priority)` | M | 1 I8 | — | `gmti 1.0.0` | 1 highest to 99 lowest, `0` = default priority. **Not `Event.severity`**: a requestor's priority orders its own requests |
| `R4 Bounding Area – Point A Latitude` | M | 4 SA32, deg | — | `gmti 1.0.0` | the requested area, four corners clockwise and convex as `J6` |
| `R5 Bounding Area – Point A Longitude` | M | 4 BA32, deg | — | `gmti 1.0.0` | |
| `R6 Bounding Area – Point B Latitude` | M | 4 SA32, deg | — | `gmti 1.0.0` | |
| `R7 Bounding Area – Point B Longitude` | M | 4 BA32, deg | — | `gmti 1.0.0` | |
| `R8 Bounding Area – Point C Latitude` | M | 4 SA32, deg | — | `gmti 1.0.0` | its paragraph is numbered `4.1.1`, duplicating the Requestor ID's — a numbering slip recorded in the ambiguities table |
| `R9 Bounding Area – Point C Longitude` | M | 4 BA32, deg | — | `gmti 1.0.0` | |
| `R10 Bounding Area – Point D Latitude` | M | 4 SA32, deg | — | `gmti 1.0.0` | |
| `R11 Bounding Area – Point D Longitude` | M | 4 BA32, deg | — | `gmti 1.0.0` | |
| `R12 Radar Mode` | M | 1 E8 | — | `gmti 1.0.0` | Table 3-16, as `J14`. §4.1.11 cites "Table 4-16", which does not exist |
| `R13 Radar Resolution – Range` | M | 2 I16, cm | — | `gmti 1.0.0` | `0` = Don't Care, a stated indifference rather than a stated absence, and the basis keeps them apart |
| `R14 Radar Resolution – Cross-Range` | M | 2 I16, **dm** | — | `gmti 1.0.0` | `0` = Don't Care. Decimetres against `R13`'s centimetres |
| `R15 Earliest Start Time – Year` | M | 2 I16 | — | `gmti 1.0.0` | **2000 to 2099** — the one place the format bounds a year, and it makes the request segment unusable after 2099. Recorded, not policed: a value outside the range parks in `unresolved_raw` |
| `R16 Earliest Start Time – Month` | M | 1 I8, 1–12 | — | `gmti 1.0.0` | **This is an absolute wall-clock time, unlike every instant in the data segments** — the request states its own date rather than referencing the Mission Segment, so a Job Request Segment needs no reference date |
| `R17 Earliest Start Time – Day` | M | 1 I8, 1–31 | — | `gmti 1.0.0` | |
| `R18 Earliest Start Time – Hour` | M | 1 I8, 0–23 | — | `gmti 1.0.0` | |
| `R19 Earliest Start Time – Minutes` | M | 1 I8, 0–59 | — | `gmti 1.0.0` | |
| `R20 Earliest Start Time – Seconds` | M | 1 I8, 0–**60** | — | `gmti 1.0.0` | "The upper bound of 60 is used in the case of needing to reference a leap second according to UTC convention." A second 60 is a real instant that `datetime` cannot hold, so the seven fields are parked as read and **never assembled into a `Timestamp`** — which costs nothing here, since nothing in this segment becomes an object |
| `R21 Earliest Start Time – Allowed Delay` | M | 2 I16, s | — | `gmti 1.0.0` | after which the request is abandoned |
| `R22 Duration` | M | 2 I16, s | — | `gmti 1.0.0` | `0` = continuous |
| `R23 Revisit Interval` | M | 2 I16, deciseconds | — | `gmti 1.0.0` | `0` = default interval |
| `R24 Sensor ID – Type` | M | 1 E8 | — | `gmti 1.0.0` | Table 3-15, `255` = No Statement |
| `R25 Sensor ID – Model` | M | 6 A | — | `gmti 1.0.0` | the literal string `"None"` = No Statement — the only string sentinel in the format |
| `R26 Request Type` | M | 1 FL | — | `gmti 1.0.0 · parked` | `0` initial request, `1` cancel the job. A **cancellation** is the closest thing in the format to a retraction, and it is out of scope with the rest of the segment; **gap 18**'s retraction half |

### Row set — Job Acknowledge Segment

"Sent once to acknowledge the status of a particular job request" (§4.2). Parked whole, with the
Job Request Segment and for the same reason.

| GMTIF | M/C/O | Form | CDM field | Status | Notes |
|---|---|---|---|---|---|
| `A1 Job ID` | M | 4 I32 | — | `gmti 1.0.0` | "the specific Job ID created in response to the request", 1 to 4 294 967 295 |
| `A2 Requestor ID` | M | 10 A | — | `gmti 1.0.0` | echoes `R1` |
| `A3 Requestor Task ID` | M | 10 A | — | `gmti 1.0.0` | echoes `R2`. Its text says it "Correlates with the Job ID defined in paragraph 4.2.1", which describes `A1`, not this field — recorded in the ambiguities table |
| `A4 Sensor ID – Type` | M | 1 E8 | — | `gmti 1.0.0` | Table 3-15. Unlike `R24` and `J2`, its value range column states no No-Statement value |
| `A5 Sensor ID – Model` | M | 6 A | — | `gmti 1.0.0` | and unlike `R25`, no `"None"` sentinel is stated |
| `A6 Priority (Radar Priority)` | M | 1 I8 | — | `gmti 1.0.0` | 1 to 99. **No `255` end-of-job value here**, unlike `J5` |
| `A7 Bounding Area – Point A Latitude` | M | 4 SA32, deg | — | `gmti 1.0.0` | the area that will actually be serviced, four corners clockwise and convex |
| `A8 Bounding Area – Point A Longitude` | M | 4 BA32, deg | — | `gmti 1.0.0` | |
| `A9 Bounding Area – Point B Latitude` | M | 4 SA32, deg | — | `gmti 1.0.0` | |
| `A10 Bounding Area – Point B Longitude` | M | 4 BA32, deg | — | `gmti 1.0.0` | |
| `A11 Bounding Area – Point C Latitude` | M | 4 SA32, deg | — | `gmti 1.0.0` | |
| `A12 Bounding Area – Point C Longitude` | M | 4 BA32, deg | — | `gmti 1.0.0` | |
| `A13 Bounding Area – Point D Latitude` | M | 4 SA32, deg | — | `gmti 1.0.0` | |
| `A14 Bounding Area – Point D Longitude` | M | 4 BA32, deg | — | `gmti 1.0.0` | |
| `A15 Radar Mode` | M | 1 E8 | — | `gmti 1.0.0` | Table 3-16, as `J14` |
| `A16 Duration` | M | 2 I16, s | — | `gmti 1.0.0` | `0` = continuous |
| `A17 Revisit Interval` | M | 2 I16, deciseconds | — | `gmti 1.0.0` | `0` = default interval |
| `A18 Request Status` | M | 1 E8 | — | `gmti 1.0.0` | `0` Request, `1` Approved, `2` Approved with Modification, `3`–`10` Denied for Line of Sight / Timeline / Orbit / Priority / Area of Interest / Illegal Request / Function Inoperative / Other. **`0 = "Request"` in an acknowledge segment is a value with no stated meaning** — recorded in the ambiguities table. §4.2.18 puts the burden of finding the modifications on the requestor, which is a consumer's job by the standard's own instruction |
| `A19 Radar Job Start Time – Year` | M | 2 I16, 2000–2099 | — | `gmti 1.0.0` | as `R15`, including the 2099 bound |
| `A20 Radar Job Start Time – Month` | M | 1 I8, 1–12 | — | `gmti 1.0.0` | an absolute wall-clock time, as `R16` |
| `A21 Radar Job Start Time – Day` | M | 1 I8, 1–31 | — | `gmti 1.0.0` | |
| `A22 Radar Job Start Time – Hour` | M | 1 I8, 0–23 | — | `gmti 1.0.0` | |
| `A23 Radar Job Start Time – Minutes` | M | 1 I8, 0–59 | — | `gmti 1.0.0` | |
| `A24 Radar Job Start Time – Seconds` | M | 1 I8, 0–60 | — | `gmti 1.0.0` | the leap-second bound, as `R20` |
| `A25 Requestor Nationality ID` | M | 2 A | — | `gmti 1.0.0` | digraph, `XN` for NATO requestors. The `P3` of the requesting station rather than of the platform, which is the one field in this segment a fusion layer would genuinely want |

### Row set — egress, CDM back to a GMTI packet

**Phase 1 deferred this and Phase 2 shipped it, so the declines table's egress row is now a
description rather than a deferral.** What the Phase 1 row set predicted held: egress here is not a
symmetry problem but an **authorship** problem, because seven of a Dwell Segment's Mandatory fields
state where a sensor was and what area it swept, and no CDM object states any of them. So there are
two paths and a refusal, and the refusal is the decision that row asked for.

| CDM field | GMTIF | Status | Notes |
|---|---|---|---|
| `Entity.attributes` | the whole packet | `gmti 1.0.0 · egress` | **path 1, round-tripped.** `attributes.gmti_packet` and `attributes.gmti_segments` hold every decoded field, so egress re-encodes and the result is **byte-identical** to what arrived. `P2` and every `S2` are recomputed and then checked against the parked values: recomputing without checking would let a decoder bug and an encoder bug cancel out invisibly, which is exactly what a round trip is supposed to catch |
| `Entity.position` · `Entity.kinematics` · `Entity.valid_from` | `L1`–`L7` in a Platform Location Segment, under a Mission Segment | `gmti 1.0.0 · egress` | **path 2, CDM-native platform state.** `P10 = 0`, which is the packet shape §3.1.10 provides for outright — "if the Packet contains no Dwell, HRR, or Range-Doppler segments, then the Job ID in the Packet Header shall be 0" — so nothing has to be invented to satisfy it. Requires a configured `platform_identity` and `mission_reference_date`; requires all three of `course_deg`, `speed_mps` and `climb_mps`, because `L5`/`L6`/`L7` are Mandatory and none has a No-Statement value |
| `Track.samples[].position.lat` · `Track.samples[].position.lon` | *(nothing, for more than one sample)* | `gmti 1.0.0 · egress` | **a CDM-native `Track` with two or more samples is refused, and the refusal names the exit.** `L5` Platform Track and `L6` Platform Speed are Mandatory in every Platform Location Segment and are each defined "at the time the report is prepared" (§3.15.5, §3.15.6), with `L7` taking the same instant from `L1`; the CDM holds ONE `Kinematics` per `Entity`. So emitting N segments would repeat the latest velocity onto N−1 earlier instants, which **fabricates a Mandatory measurement N−1 times** — **gap 16** on the egress side. **The exit is the caller's and the message says so**: the last sample is the one instant where every Mandatory field has an honest value, because it is the instant the `Entity`'s own position and kinematics were taken from, so a single-sample `Track` — or the `Entity` alone, which needs no `Track` — emits a valid packet. Truncating a history has a cost, so it is a decision the caller takes visibly rather than one this adapter takes silently |
| *(anything else)* | — | `gmti 1.0.0 · egress` | **path 3, refusal.** A CDM-native object that is not a platform would have to become a Dwell Segment target report, and `D7`/`D8`/`D9` (where the sensor was) and `D24`–`D27` (what area it swept) are Mandatory and unstated. **A configured value for them is not a deployment declaration — it is an invented measurement**, and a GMTI packet claiming a radar saw something it did not is the silent-`UNCLASSIFIED` failure in a different field |
| `Entity.attributes` | `P4` · `P5` · `P6` | `gmti 1.0.0 · egress` | the three label paths, unchanged from settlement 3: the parked triple, an explicitly configured one, or a refusal. A **partial** configured triple is also refused — a classification with no system digraph is a marking whose policy has been removed |
| `Entity.source` | `P7` | `gmti 1.0.0 · egress` | a CDM-native packet has no source `P7` to re-emit, and amendment 2 run backwards would be just as wrong: the deployment's `synthetic` declaration is the only honest source for it, and it is emitted as a **configured** value rather than as a reading of anything. A round-tripped packet re-emits the `P7` that arrived |

**Two things this egress is not.** It is not a Dwell Segment writer, per the refusal above. And it
performs **no context merge**: two objects carrying different parked packet headers are refused
rather than combined, because one emitted packet has one Packet Header — one nationality, one
platform, one mission, one job and one classification — and merging two would attribute one
producer's data to another's platform. An object from another system passed alongside a
round-tripped packet is refused for the same reason: nothing from another format's parked context
may cross into an emitted packet. That is `stanag4676.py`'s consolidation refusal reached in a
format with no local IDs at all.

**Quantisation on the native path is the FORMAT'S stated resolution, not a translator's loss — and
amendment 4 records it here as a property of the format rather than as an apology.** Phase 1's
position rule was already "convert, stating precision"; these are the precisions, every one of them
the standard's own arithmetic (Annex C-4.6's 360/2ⁿ, C-4.7's 180/2ⁿ, C-4.5's magnitude over
2^fraction), and `codec._bounds` computes them rather than restating them:

| Form | Range | LSB | What the LSB is worth |
|---|---|---|---|
| `SA32` | −90 … +89.99999996 | 4.1910 × 10⁻⁸ ° | ≈ **4.7 mm** of latitude. `D7`, `D24`, `D32.2`, `J6`, `L2` |
| `BA32` | 0 … 359.99999992 | 8.3819 × 10⁻⁸ ° | ≈ **9.3 mm** of longitude at the equator. `D8`, `D25`, `D32.3`, `J7`, `L3` |
| `SA16` | −90 … +89.9972534 | 0.00274658203125 ° | pitch and roll — `D22`, `D23`, `D29`, `D30` — where it is 2.7 hundredths of a degree of attitude rather than a distance |
| `BA16` | 0 … 359.9945068 | 0.0054931640625 ° | ≈ **611 m** of longitude, and **the one visible loss on the native egress path**: `L5` Platform Track is a `BA16`, so a course quantises to within 2.7 millidegrees |
| `B16` | ±255.9921875 | 1/128 | `D26` Dwell Area Range Half Extent, so **7.8 m** on a kilometre-scale extent |
| `B32` | ±255.99999988 | 2⁻²³ | `H15`, `H30`, `H31` |
| `H32` | ±32767.99998474 | 2⁻¹⁶ | `H13`, `H14`, `H22` |
| `D9` · `L4` | ±2 × 10⁹ cm | 1 cm | height |
| `D16` · `L6` | 0 … 8 × 10⁶ mm/s | 1 mm/s | ground speed |
| `D17` · `L7` | −128 … +127 dm/s | 0.1 m/s | vertical velocity, and the coarsest scalar in the format |

**Quantising is legitimate; clamping and wrapping are not.** A value outside a field's range is a
**refusal quoting the value and the range** — `codec.snap` does not mask the encoded integer to the
field's width and does not clamp to the boundary. Amendment 4 is where that was fixed, and the
defect it fixed was the worse of the two available: the first implementation **masked**, so a
latitude of 95° came back as **−85°**, on the other side of the equator, and a `B16` of 300 came
back as −44. Clamping would have been less bad and still silent. **The round-trip path never
quantises anything at all**, because it re-encodes the integers that arrived.

### What the adapter fills that GMTIF does not state

| GMTIF | CDM field | Status | Notes |
|---|---|---|---|
| *(none)* | `Event.received_at` | `gmti 1.0.0` | the injected clock. GMTIF carries no producer-side creation time anywhere, so unlike NITS there is not even a wrong candidate to warn against — and unlike CAT021 the clock is **not** consulted for the date, which settlement 2 states against that precedent |
| *(none — three segments state no time at all)* | `Event.observed_at` | `gmti 1.0.0 · parked` | the receipt instant on a Free Text, Processing History or dwell-less HRR `Event`, with `payload.observed_at_basis` recording that the format stated no source time. **This contradicts the field's own docstring** and is the least bad of three bad answers — see the `observed_at` chain and **gap 23**, which is the model change that would let an absence be an absence |
| *(the deployment declaration)* | `SourceRef.synthetic` | `gmti 1.0.0` | **no payload field sets this, and agreement is not an exception** — amendment 2. `P7` Exercise Indicator, `D32.10`'s simulated half, `M4`'s test-article marking and `J14 = 100` Test/Status Mode all park; a pure-real-versus-synthetic or pure-simulated-versus-real contradiction is a logged refusal; a `P7` of *synthesized* contradicts neither pure declaration and parks visibly without one. Amendment B held as a rule for the third format, and the first one where the payload's declaration is Mandatory on every packet |
| *(none — GMTIF states no affiliation anywhere)* | `Entity.affiliation` | `gmti 1.0.0` | `UNKNOWN` on every object, with `attributes.affiliation_basis` recording that the format carries no identity, no IFF and no allegiance, and that `P3` Nationality is the platform's country and not the contact's side |
| *(none)* | `Entity.symbol` | `gmti 1.0.0` | `None` on every object. `symbology.sidc_from_affiliation` needs an affiliation, and composing a symbol from `D32.10` alone would draw one with an invented standard identity |
| *(none — GMTIF grades nothing)* | `Event.severity` | `gmti 1.0.0` | `INFO` on every `Event`, with `payload.severity_basis` recording that the format grades nothing — **including `T5` Hardware Status, where a failed datalink bit is the most gradeable thing in the format**. Grading it is an operational judgement about a platform this adapter knows nothing else about. `J5` and `R3` are tasking priorities, not severities, and are parked |
| *(none)* | `Event.event_type` | `gmti 1.0.0` | `DETECTION` for a target report and for an HRR segment; `STATUS_CHANGE` for a Free Text, Test and Status or Processing History segment. **Never `TRACK_UPDATE`** — settlement 5 |
| *(derived)* | `Position.position_source` | `gmti 1.0.0` | `ESTIMATED`, always, with `attributes.position_source_basis` recording two different reasons: a target position is a radar geolocation through `J27`/`J28`, and a platform position comes from a navigation system the format never names. **Never `GNSS`** |
| *(none)* | `Position.accuracy_m` | `gmti 1.0.0` | `None`, always, on every object. Twelve uncertainty fields, not one of them a single horizontal 1-sigma metre figure — settlement 6. `None` means unknown accuracy, never perfect accuracy |
| *(none)* | `Entity.confidence` | `gmti 1.0.0` | `None`, always. `D32.11` is a confidence in a *classification* and `J25` is a sensor performance figure; the CDM's bare float has no stated subject, so neither can be written to it. **Gap 18** |
| *(none)* | `Track.track_quality` | `gmti 1.0.0` | `None`, always — GMTIF states no track quality because it states no track |
| *(none)* | `Entity.valid_to` | `gmti 1.0.0` | `None`, always, including on target `Entity` objects whose existence claim covers one instant. The least satisfactory statement in this row set, and **gap 20** is the honest fix |
| *(the composite key)* | `Entity.attributes` | `gmti 1.0.0` | `attributes.entity_key_basis` — every component of the derived `entity_id`, and the statement that the last two are **positional** and therefore unstable under any re-segmentation of the packet |
| *(measured, per platform track sample)* | `Entity.attributes` | `gmti 1.0.0 · parked` | `attributes.platform_track_points[]` — per sample, its `time_basis` (`dwell_center` from `D6`, or `report_prepared` from `L1`), its source segment type and ordinal, and its `Track.samples` index; plus `attributes.platform_track_basis` stating the per-basis counts and whether the track is mixed. **Amendment 3**, and it exists so that no consumer averages a dwell-centre position against a report-preparation position unknowingly. **Gap 16** and **gap 13** together |
| *(the date's provenance)* | `Entity.attributes` | `gmti 1.0.0` | `attributes.reference_date_basis`, `payload.reference_date_basis` and `attributes.platform_track_points[].reference_date_basis` — `in_packet` or `caller_supplied_stream_context`, **on every emitted instant** rather than once per packet (amendment 4a). A caller-supplied date is named and logged; a clock-derived one is forbidden; a caller date contradicting an in-packet Mission Segment is a refusal quoting both (amendment 4b) |
| *(none — GMTIF carries no checksum of any kind)* | `Entity.integrity` | `gmti 1.0.0` | `None`, with `attributes.integrity_basis` recording that the packet passed structural checks — `P2` against the byte count, each `S2` against the segment boundaries, each existence mask against its field sequence — and nothing more, because §2.2 puts error detection in the transmission layer |
| *(measured)* | `Entity.attributes` | `gmti 1.0.0` | `attributes.unavailable_fields` — and here it holds **two distinguishable kinds** of fact: a field the existence mask says is absent, and a Mandatory field present with its own documented No-Statement value. Settlement 7 keeps them apart, because "the source did not send it" and "the source sent it and said it does not know" are different statements |
| *(measured)* | `Entity.attributes` | `gmti 1.0.0` | `attributes.unresolved_raw` — values read and not usable: a reserved enumeration literal, a `D6` beyond Table 3-9's stated maximum, an unsupported segment's bytes, a `J14` in a reserved range |
| *(measured)* | `Entity.attributes` | `gmti 1.0.0 · parked` | `attributes.unresolved_references` — an `H5` pointing at a target report not in this packet, and a Processing History `<DataSetID>` naming a job this packet is not. **Gap 19** |
| everything unmapped | `Entity.attributes` | `gmti 1.0.0` | `attributes.source_extras`, including `source_extras.unsupported_segments[]` with each skipped segment's type code, size and raw bytes. Unlike NITS, whose schema declares open content on every type, GMTIF has **no extension mechanism inside a defined segment** — the extension point is a whole segment type, which is why the unsupported-segment park is a named key rather than a formality |
| *(the whole packet, verbatim)* | `Entity.attributes` | `gmti 1.0.0` | `attributes.gmti_packet` — the ten Packet Header fields as decoded — and `attributes.gmti_segments`, the ordered list of every segment with its type, its size, its existence mask where it has one, and every field it carried. **This is what makes `TRANSFORMS` empty**: every source value is present verbatim as well as converted, so the never-drop rule is satisfied by presence rather than by a declared exemption. It is also what makes the byte-exact round trip structural rather than hopeful, because egress re-encodes from it |
| *(per target report)* | `Entity.attributes` | `gmti 1.0.0` | `attributes.gmti_target_report`, and `payload.gmti_dwell` on the matching `DETECTION` `Event` — so an object holding one detection can be read without the platform `Entity` beside it |
| *(measured)* | `Entity.attributes` | `gmti 1.0.0` | `attributes.target_classification_conflict_basis` — the result of the intra-payload simulation check, on every platform `Entity`, whether or not it found anything. A check that only reports when it fires is a check nobody can tell ran |
| `D32.2`/`D32.3`, or the recovered delta | `Event.geometry` | `gmti 1.0.0` | **a `Point` in `[lon, lat]` order on every `DETECTION` `Event` from a target report** — amendment 1 reversed the Phase 2 reading, which was `None` everywhere. A GMTI target report **is** a position measurement: the detection's location is the payload's primary content, and `Event.geometry` is the CDM's field for where an event happened, so `None` put the one thing the report is about somewhere a consumer holding the `Event` alone cannot reach. **Two elements and never three** — `D32.6` is Optional, a two-element `Point` is the honest shape when the source stated no height, and a `Point` that sometimes has a third element makes every consumer branch; `Position.alt_m` on the `Entity` carries the height. This follows `stanag4676.py` and diverges from `asterix_cat021.py` and `adsb.py`, which is recorded in **gap 20** rather than resolved here |
| *(none)* | `Event.geometry` | `gmti 1.0.0` | `None` on an HRR `Event` and on the three `STATUS_CHANGE` kinds, with `payload.geometry_basis` saying why in each: an HRR segment states range-Doppler indices in a sensor-relative space rather than a position, and a Free Text, Test and Status or Processing History segment states no location at all |

### Where the specification is ambiguous or contradicts itself

Every one of these will be hit by whoever writes the adapter. Each is handled by parking, by
following the more authoritative statement, or by refusing — never by guessing.

| # | Finding | Consequence for the adapter |
|---|---|---|
| 1 | **`P6`'s sixteen caveat bits mean two different things in two pinned documents.** Standard Table 3-4 assigns NATO releasability codewords (`EU`, `EUFOR`, `ISAF`, `KFOR`, `NRF`, `NMI`, `PFP`, `RS`, `THE PUBLIC`); guide Annex G Table G-1 assigns the same bits US-flavoured caveats (`NOCONTRACT`, `ORCON`, `PROPIN`, `WNINTEL`, `REL 4-EYES`, `REL 9-EYES`). Annex G's own reference list cites STANAG 4607 **Edition 2, 2 August 2007** and AEDP-7 Edition 1, so the validation annex was carried forward without being re-based. The standard's own note then says the table is "representative … not an exhaustive list" and that "each nation shall be responsible for developing and publishing their own packet security handling codes" | `P4`/`P5`/`P6` park verbatim as a triple, `P6` as the raw integer plus set bit positions and **never as codeword names**, and `P5`'s digraph is what a consumer resolves them with. Settlement 3. This is the single strongest argument in this row set for parking rather than interpreting, and it is a demonstrated contradiction rather than an analogy |
| 2 | **`D6`'s value range and its stated capacity disagree.** Table 3-9 gives "0 to 4 x (10^9)" ms — 46 days 7 h — while §3.3.7 says "the maximum value of field D6 is equivalent to 49 days" and Annex C-3 says "up to 49 days and 17 hours", which is the full `I32` range. The same disagreement applies to `T4` and `L1` | the arithmetic is unambiguous either way, so the value is **converted**, the raw integer is parked, and `unresolved_raw` records that it exceeded the table's declared maximum. A refusal would reject a value two of three statements permit |
| 3 | **The truth tags guard on classification value `140` and the table puts `Tagging Device` at `142` — and the disagreement is a stale cross-reference whose whole history is inside the pinned set.** Checked against the PDFs' raw content streams rather than a text extraction. **Locus A**, AEDP-4607 Ed A V1 Table 3-11, page 25 (PDF page 45): `140 = Large Multiple-Return, Simulated Land Target`, `142 = Tagging Device`, `143 = Reserved`. **Locus B**, §3.4.32.16 and §3.4.32.17, page 27 (PDF page 47): "If the target classification field is classified as **140** then the truth tag application field will indicate the battery strength of the tagging device" and "If the target classification field is **140** then the truth tag entity field will be the tag identification number transmitted by a tagging device". **Locus C**, guide Annex M.1 (Errata Sheet No. 3, STANAG 4607 Ed 2 → Ed 3), page M-9: the change record for "Page A-30, Table 2-4.2 Target Classification" **adds `Tagging Device` at value 140**, and the immediately following item on page M-10, "Page A-31 Paragraph 2.4.32.16", is the errata that *introduced* the battery-strength prose citing 140 and widened the condition to "simulated **or a tagging device is detected**". **Locus D**, guide Annex M.2 item 28, page M-31: Ed 3's table is quoted with `143 = Tagging Device`, replaced by `142` for Ed A. So the value moved **140 → 143 → 142** across three editions and the prose was never re-based; it was correct when written and refers to the class, not to the number | **the ambiguity is keyed on the LABEL, `Tagging Device`, not on a value**, and every rule that depends on it is written against the label so that a future edition moving the number again does not silently change behaviour. Under Ed A the label is carried by `142`, so `142` is the value the tagging-device exemption covers. Both truth tags still park raw under both readings' names and neither is interpreted — see the settlement for the re-based grounds, which are no longer "the condition is unstatable" |
| 4 | **§3.2.1's prose and Table 3-6 disagree about the extension range.** The prose reserves "103-255 … for future use"; the table splits `103–127` from `128–255` "Reserved for Extensions", and guide Annex L has assigned five of the latter since 2008 | none, because the behaviour is identical: skip by `S2`, park, record. The table and the registry are followed, and the disagreement is recorded so the next reader does not have to re-derive it |
| 5 | **The guide says heights may be orthometric; the standard says they are ellipsoidal, unconditionally.** §3.4.9, §3.15.4 and §3.4.32.6 all say "above the WGS 84 ellipsoid"; guide §E.8 says heights are "either from the reference ellipsoid, or from mean sea level if a geoid model is being used", and `J28` names one. The two readings differ by the geoid undulation, up to about 105 m | the standard wins: `alt_m` is HAE. `J27`/`J28` park and `attributes.alt_datum_basis` records the guide's contradicting sentence and the declared model, so a consumer that needs to resolve it has both halves. **Gap 9**'s neighbourhood |
| 6 | **Table 3-13 gives `H32.3` and `H32.4` a Bytes value of `1` and a Form of `I16`**, which cannot both be true | `I16` is followed — the stated value range is 0 to 65 535, which needs two bytes — and the contradiction is recorded. An adapter that believed the Bytes column would desynchronise the whole scatterer array |
| 7 | **`H10`'s and `H32.1`'s sign conventions are stated only in a units column and are described inconsistently in prose.** `H10`'s unit is `-dB/4` and §3.5.10 explicitly says "removing the negative sign"; `H32.1`'s unit is `-dB/4` but §3.5.32.1 describes the conversion with no sign removal | both readings are recorded in the park and neither value reaches a canonical field, so the ambiguity costs nothing beyond a note. Recorded because an adapter tempted to render a signature would have to resolve it |
| 8 | **`J18`'s text cites "field D11"** — the Longitude Scale factor — where it means `D9`, Sensor Position Altitude | none; recorded so the next reader loses no time |
| 9 | **Four numbering and cross-reference slips.** §3.14.6.6 Processing Performed is numbered `3.1.1.1`; §4.1.4's Point C Latitude paragraph is numbered `4.1.1`, duplicating Requestor ID's; §4.1.11 cites "Table 4-16", which does not exist (Table 3-16 is meant); §3.1.6 says the codewords are "in Table 3-5", which is the Exercise Indicator table, when they are in Table 3-4 itself; and `D32.14`'s own text calls the field "D34.14" | none beyond wasted time. Recorded together because an implementer working from the paragraph numbering will hit all five |
| 10 | **`A18 = 0` means "Request" in a segment whose purpose is to acknowledge one.** No paragraph explains what an acknowledge segment carrying "Request" is acknowledging | the value parks with the rest of the segment; nothing turns on it because nothing in the Job Acknowledge Segment becomes an object. Recorded because a future release that grew a tasking object would have to decide |
| 11 | **`T2` and `T3` are ranged `1` to 65 535 where their `D2`/`D3` and `H2`/`H3` counterparts start at `0`** — and §3.4.2 defines a Revisit Index of "0" as the first revisit | parked as read, neither corrected nor refused. An off-by-one against its own siblings means a Test and Status Segment reporting the *first* dwell of the *first* revisit cannot state it, and no adapter behaviour can fix that |
| 12 | **Guide FAQ Q11's worked example contradicts its own text**, showing `C1 = 3` beside the first and only Processing Record where the text says `C1` "is set to 1" for the first processing | `C1` is checked against the records actually present and a mismatch is a refusal, per the standard's own definition of the field. The guide's example is informative and does not override it |
| 13 | **`D27` Dwell Angle Half Extent is two different quantities in one field**, selected by whether the radar dwells: half the 3 dB beamwidth, or "the angle between the beginning of the dwell to the center of the dwell" | parked with both readings named, and never used to derive a dwell duration or a dwell-area polygon. The format states nothing that says which kind of radar produced the packet |
| 14 | **`H7` and `H14` are each two quantities in one field**, selected by `H23` and by nothing respectively: `H7` is a range-sample count or a total scatterer count, `H14` is a Doppler bin spacing or a PRF | parked under both names. `H14` is the worse of the two because nothing selects between them — and `H7`'s dual meaning is what creates the collision **row 17** records, so the two are read together |
| 15 | **`H15`'s value range restates `B16`'s maximum for a `B32` field, and its minimum is off by a bit.** Table 3-12 gives `H15` Center Frequency a range of "2.384e-7 to 255.9921875" GHz. Annex C-4.5 makes `B32` one sign bit, eight integer bits and **23** fraction bits, so its maximum is 255.999999881 and its LSB is 2^-23 = 1.192e-7 — while 255.9921875 is exactly `B16`'s maximum (256 − 1/128) and 2.384e-7 is exactly 2^-22. So the value-range column appears to have been carried over from a 16-bit field and then had its low end halved once too few times. `H30` and `H31` are `B32` too and their stated range, "0 to 100", says nothing either way | found while implementing, and it costs nothing: Annex C-4.5 defines the ENCODING and Table 3-12 only annotates it, so the field is decoded per C-4.5 and the range column is not enforced. Recorded because an implementer who validated `H15` against the table would reject conformant values between 255.9921875 and 255.999999881, and would accept nothing below 2.384e-7 that the field can in fact carry |
| 16 | **§3.1.10 and §3.7.1 together make a Job-Definition-only packet unrepresentable under a literal `J1`/`P10` cross-check.** §3.1.10: "if the Packet contains no Dwell, HRR, or Range-Doppler segments, then the Job ID in the Packet Header shall be 0". §3.7.1 and Table 3-14 give `J1` a range of 1 to 4 294 967 295. So a packet carrying a Job Definition Segment and no dwell data must have `P10 = 0` and `J1 ≥ 1`, and the two can never be equal — yet guide Figure 2-1 draws exactly that packet ("Packet Header / Segment Header / Segment No. 1 (Job Definition Segment)") | found while implementing, and the Phase 1 row set had to be narrowed rather than the packet refused. The `J1`/`P10` equality is required **only under §3.1.10's own condition** — that the packet does carry a Dwell, HRR or Range-Doppler segment — and outside it `J1` is the job being *defined* rather than the job the header's data belongs to. Both "shall" statements are kept and Figure 2-1 stays conformant; the fixture `tasking_segments_parked_with_job_id_zero` is what pins the narrowing |
| 17 | **`H6` and `H7` may both be reported and the standard never says which bounds the scatterer array.** §3.5.6 makes `H6` the "number of Range Doppler pixels that exceed target scatterer threshold and **are reported in this segment**" — a count of records present. §3.5.7 makes `H7` the "number of Range Bins/Samples in a Range Doppler Chip", and then: "**when used with a Sparse HRR chip this field shall define the total number of scatterer records**" — so `H7` is a *dimension* for a contiguous chip and a *record count* for a sparse one, selected by `H23`. Both paragraphs end with the same sentence: "**Either H6 or H7 or both must be reported**." So the unresolved case is explicit in the text rather than hypothetical: a **sparse** chip (`H23 = 3`) carrying **both**, where `H6` states one number of records and `H7` states another. Nothing in §3.5.32 or anywhere else says which governs, and the two readings produce arrays of different lengths — so both produce a *valid-looking* parse of a different number of bytes | **this row is the written justification for the hex-blob parking, and it is why the array is bounded by `S2` instead.** The declines table rejects mapping HRR signature data at all, so the adapter never needs the count: the array is the remainder of the segment, whose end §3.2.2's `S2` gives exactly, and the question is left where the standard left it. Adjudicating `H6` against `H7` would be a translator choosing between two "must be reported" fields on a conformant packet, which is a custodian's act. `H25` and `H26` are still validated (1-or-2 and 0-1-or-2), because they size a record and any other value makes the array indeterminate under *every* reading. **A Phase 3 author who decodes the array has to resolve this first**, and the resolution is an erratum or a per-deployment ICD, not a preference. Row 14 records `H7`'s dual meaning; this row records the collision it creates |
| 18 | **The implementation guide's document number is spelled four ways across the three pinned documents.** Its own title page and Letter of Promulgation say **`AEDP-4607.1`**; the standard's §3.2 says **`AEDP-4607.01`**; the STANAG cover's English column says `SRD AEDP-4607.1` and its French column says `AEDP-4607.01`. The superseded guide is `AEDP-7` in the standard's body and **`AEDP-07`** in the guide's own Letter of Promulgation. Found on the 2026-08-23 pin re-verification, in documents promulgated on the same day by the same signature | none for the parse — no field carries a document number. It matters for *citation*: this row set writes `AEDP-4607.1` throughout, which is the form the document uses about itself, and a reader grepping the standard for that string will not find it. Recorded rather than harmonised, because picking one spelling for a NATO publication number is a custodian's act |
| 19 | **The standard sends the reader to a guide that its own co-promulgated guide orders destroyed.** §3.2, in the pinned Edition A Version 1: "AEDP-7 will be replaced by AEDP-4607.01 and as such, AEDP-7 should be treated as the current version of the implementation guidance **until AEDP-4607.01 is published**." AEDP-4607.1 was published on **16 February 2024** — the same Letter of Promulgation date as AEDP-4607 itself, signed by the same Director — and it states that it "supersedes AEDP-07, Edition 2, which shall be destroyed in accordance with the local procedure for the destruction of documents". So the sentence's own condition was satisfied on the day the sentence was promulgated | none, and it is the one ambiguity in this register that *confirms* a decision instead of constraining one: the pin's line "**nothing here was read from AEDP-7**" is what §3.2 would have argued against on a literal reading, and the guide's promulgation letter settles it. The stale sentence is left alone — re-basing normative prose is the act ambiguity 3 declines for the same reason |

### Deliberately out of scope, and why

An unimplemented thing is a decision, so each one is named, and each says whether it is deferred,
rejected, or blocked.

| Out | Deferred, rejected or blocked | Decision |
|---|---|---|
| **Emitting a CDM-native Dwell Segment target report** | **rejected** | The decision Phase 1's deferred egress row asked to be made, made. `D7`/`D8`/`D9` state where the sensor was and `D24`–`D27` state what area it swept; all seven are Mandatory and no CDM object states any of them. A configured value for them would not be a deployment declaration — it would be an **invented observation footprint**, and a packet claiming a radar saw something it did not is worse than a packet that does not exist. See the egress row set: a CDM-native platform state emits a Platform Location Segment under `P10 = 0` instead, which is a shape the standard provides for and which needs nothing invented |
| **Emitting a multi-sample CDM-native platform history** | **rejected, with the exit named** | `L5`/`L6`/`L7` are Mandatory in every Platform Location Segment and the CDM holds one `Kinematics` per `Entity`, so N segments would repeat one velocity onto N−1 instants it was not measured at. **Gap 16** on the egress side, refused rather than fabricated — and the refusal tells the caller that a single-sample `Track` holding the latest sample emits a valid packet, so the truncation is theirs to choose rather than ours to perform |
| **STANAG 4607 Edition 3 and earlier** | **deferred** | Same packet structure, same masks, **different enumeration tables** — guide Annex M item 28 moves `Tagging Device` from 143 to 142 and adds ten target classifications. So this is one adapter with a version-dispatched enumeration table, not a second adapter, which is a deliberate departure from the STANAG 4676 Edition 1 decline. Building it needs Edition 3's tables from a document this repository has not pinned. A packet whose `P1` is not `"41"` is refused with the value quoted |
| **The Range-Doppler Segment (`S1 = 4`)** | **deferred** | §3.6 in the standard is the single word "RESERVED", and §3 says "A preliminary description of the Range-Doppler Segment is provided in the associated guidance". **Preliminary is not normative**, and the guide is not normative for the format. Skipped by `S2`, parked, logged and recorded, on §3.2.1 and §3.2.2 |
| **LRI (7), Group (8), Attached Target (9) and System-Specific (11) Segments** | **rejected as unimplementable** | Four paragraphs reading "[THIS PARAGRAPH IS RESERVED FOR FUTURE DEFINITION]". There is nothing to defer to. Skipped and parked |
| **Controlled Extension Segments 128–132** | **blocked, with a stated exit condition. Re-checked 2026-08-23; the condition is UNMET** | Guide Annex L.3.1 registers five *approved and validated* extensions — Advanced Dwell, Advanced Job Definition, Advanced Platform Location, Target Centroid, Releasability — and **§L.4, which is supposed to hold their field tables, reads "(TO BE PROVIDED)"**. So a conformant producer may emit segment types a pinned document names and no pinned document defines. **The reopen condition was checked against the promulgated Edition A Version 1 text on 2026-08-23 and remains unmet, and the annex now promises the tables in two places and delivers them in neither.** §L.2: "Section L.4 of this Annex provides the tables, descriptions, and rules of use for each Controlled Extension." §L.4, in full: "Descriptions of Controlled Extensions — This section provides tables and descriptions of Controlled Extensions for use with the core set of Headers and Segments identified in Chapter 3 of the standard. **(TO BE PROVIDED)**". §L.3.1's Table L-1 is the half that *is* populated, and its five rows carry submission and approval dates from 2006–2010 with named submitters and approvers (S.C. Bygren and D.T. Bagley, approved by L.A. Moore, 17 Jun 2008 / 17 Mar 2010 / 17 Apr 2010) — so these are extensions approved fourteen to sixteen years before the pinned edition and still undescribed in it, followed by six blank rows numbered `L.4.6` through `L.4.11` for the ones that have not been submitted. **A populated record sheet is not a populated registry**, and the distinction is the whole blocker: the segment type codes are knowable and their field layouts are not. **Exit condition, in order:** obtain the five field tables from the STANAG 4607 Custodian or a revision of AEDP-4607.1 that fills §L.4; pin them by SHA-256 the way `sac_pin.json` pins the ASTERIX allocation list; write the row sets; and implement `132 Releasability` **first**, because it extends the fields of settlement 3 and a security extension nobody decodes is the one park with a real cost. Until then all five are skipped and parked |
| **Job Request and Job Acknowledge Segments** | **rejected** | They are tasking: a request for sensor service and its acknowledgement. The CDM's four kinds are what exists, what happened, where something has been, and what *we* push out — and a request addressed to somebody else's sensor is none of them. `PlanObject` is emphatically not it, for the reason the CAT021 intent gap states: it models our plan drawn on somebody else's map, and this is somebody else's plan drawn on ours. The standard itself calls both segments "recommendations only and … not required for this format". Parked whole, every field with a row, so that a release which grows a tasking object finds a decision rather than an omission. **Gap 15** is the neighbouring open question |
| **HRR and Range-Doppler signature data** | **rejected** | `H32.1`–`H32.4` are a scatterer array: magnitudes, phases and bin indices in a sensor-relative range-Doppler space. **A signature is not track state.** Turning one into anything canonical means a target-recognition model, which is a different discipline with its own standards, and the array's *only* geolocatable content is the target report it points at, which is already an object. The segment becomes one `DETECTION` `Event` carrying its parameters and the array parked whole, which is what the never-drop rule requires and the most that can honestly be claimed |
| **Undoing `H16` threshold decomposition, or applying `H24`'s processing mask** | **rejected** | Signal processing on parked signature data, in an adapter contracted to be a pure function of one payload |
| **Un-wrapping `D32.7` using `D32.8`** | **rejected** | §3.4.32.8 addresses the arithmetic to "the tracker" and makes the multiple depend on "the target's expected line-of-sight velocity", which is a tracker's prior. Both values park |
| **Test and Status Segment → a graded alert** | **rejected as a grading, carried as data** | The segment becomes a `STATUS_CHANGE` `Event` with every `T5` and `T6` bit named, and `severity` stays `INFO`. Deciding that a failed datalink is `CRITICAL` and a temperature limit is `WARNING` is an operational judgement about a platform this adapter knows nothing else about, and the format grades nothing |
| **Processing History Segment → resolving the `<DataSetID>` chain** | **rejected** | `C2`–`C5` name the original radar job and `C6.2`–`C6.5` name each modifying system, so the chain is a provenance graph across packets this adapter will never see. Carried in full, in order; resolved never. **Gap 14**, **gap 19** |
| **Reassembling a dwell split across segments or packets** | **rejected** | §3.4.32 permits the split, guide §D.2 and §D.5 describe it, and doing it means holding state across payloads. The AIS fragment buffer, the ADS-B frame pair, Legion's pagination, CAT021's cross-block correlation and NITS's DATASTREAM resolution, refused a sixth time |
| **Associating target reports across dwells into tracks** | **rejected** | It is what a GMTI tracker does, and the format's own implementation guide sends the reader to the sensor manufacturer for the rule (FAQ Q10). Settlement 5 |
| **Building a dwell-area or bounding-area `Geometry`** | **deferred** | The bounding area is four explicit corners and would be a `Polygon` with no inference at all — but there is no CDM object for "the area a sensor was tasked to search", and putting it in `Event.geometry` would paint a tasking as an observation. The dwell area additionally needs a geodesic sector construction from a centre, a range half-extent and `D27`'s two-meanings angle. Deferred against **gap 22**, which is the object this needs |
| **Dereferencing `J27`/`J28` terrain or geoid models** | **rejected** | §3.4.32.6 offers "DTED Level 0 terrain elevation data, which is available over the Internet" as a way to supply a missing target height. An adapter that fetched terrain data out of its payload's declared model name is a network client with a payload-controlled target, in a component that is supposed to have no network at all. `D32.6` absent means `alt_m` is `None` |
| **Decoding DIS Entity State PDU truth tags** | **deferred** | A separate standard with its own identifier semantics, and the guard condition that selects between its two readings names the wrong classification code (ambiguity 3). Parked whole, which the never-drop rule already satisfies |
| **Embedding: NSIF/STANAG 4545 DES, NITF, STANAG 7023, STANAG 4559 libraries** | **rejected** | Guide Annex B describes GMTIF carried inside three imagery formats and retrieved from an ISR library. Extracting a GMTIF packet from an NSIF Data Extension Segment is an NSIF reader's job, and the boundary is the same one §2.1 draws: this adapter's input is one packet, and getting one is the caller's problem |
| **Transport: datalinks, packet sequence numbers, loss detection, channelisation, error correction** | **rejected** | §2.2 puts all of it in "the lower layers of the communications media" and guide §D.4 puts it in a mux/demux layer explicitly outside the format. By the standard's own instruction |
| **Claiming conformance for anything this adapter emits or reads** | **blocked, and it always will be** | Two reasons and the second is amendment 5's. Guide Annex G's compliance testing is a *program* — test events, a registration authority, a certificate — not a document one can execute. And Annex G is **stale**: its own reference list cites STANAG 4607 Edition 2 of 2007, which is how it comes to publish a `P6` codeword table contradicting the standard's (ambiguity 1), so passing its subtests would not establish conformance to Edition A even if one could run them. Nothing here can claim a packet it reads is conformant or that one it emits would pass; only that every value it re-emits equals the value it read. Recorded so that "validated against AEDP-4607.1" is never written down about this adapter |

### The fixtures — planned here before they existed, and now sixteen twins

**Everything is synthetic.** No recorded GMTI traffic, no real mission, no real platform, no real
detection. Each fixture is a twin: a `.gmti` packet of raw bytes and a `.parsed.json` holding the
decoded form the never-drop check measures against — the pattern `adsb.py`, `asterix_cat021.py` and
`stanag4676.py` already use, and the only one available for a binary format, since the harness's
lossless check has no leaves to harvest from bytes.

**Sixteen twins, 32 files, 32 goldens**, built by `fixtures/gmti/spec/build_fixtures.py`, which is
this set's reviewable form for the reason the CAT021 generator is that set's: a GMTI packet cannot
carry a comment and cannot be rebuilt from its own twin by hand, because `P2`, every `S2`, every
existence mask and every target-report width are functions of the contents. Harness result:
**32 passed, 0 failed** — `lossless` PASS on every `.parsed.json` half with `TRANSFORMS` empty and
SKIP on every `.gmti` half (a bytes fixture has no leaves), `roundtrip` SKIP on both halves because
`from_cdm()` returns binary and the harness compares structures.

**The round trip is therefore this adapter's own claim, and it is stronger than the harness's would
be.** `test_every_fixture_round_trips_byte_for_byte` asserts `from_cdm(to_cdm(bytes)) == bytes` on
all sixteen packets, and `test_decode_encode_is_the_identity_on_every_fixture` asserts the same one
level lower, so a failure can be attributed to the codec or to the parking rather than to "the
round trip".

**One fixture is verified BY HAND against Annex C, and that is not ceremony.** Every binary here is
produced by the same module the adapter decodes with, so a symmetric error — a swapped byte order,
a radix point off by one, a field in the wrong place — would round-trip perfectly and show up
nowhere. `test_the_hand_verified_fixture_matches_the_annex_c_byte_layout` writes out the first 76
bytes of `mission_dwell_hi_res_targets` field by field from Tables 3-1, 3-6 and 3-7, with every
value's hexadecimal spelled out in the test, and asserts them against the committed file. Beneath
it, `tests/test_cdm_gmtif_codec.py` checks each of the seven encodings against hand-computed
patterns — including **the two worked examples the standard itself prints**, `BA16`
`0101100100011100` = 125.31006° and −34.876099° = `SA16` `1100111001100110`, which between them fix
the sign convention, the exponent and the scale factor in one shot.

Identifiers follow the rule each field's own registry allows, and where no registry is pinned the
claim says so:

- **`P3` Nationality and `A25` Requestor Nationality**: a documented non-allocated digraph, never a
  real nation's and never `XN`. Table 3-3 is explicitly a list of "National Examples" plus
  "Additional codes as registered with the Custodian", so **no allocation list is pinned for it** —
  unlike the CAT021 SAC, where `sac_pin.json` pins the ASTERIX allocation table and the fixture's
  unallocated value is asserted against it. It is the weakest identifier claim in the fixture set,
  the fixture README says so in those words, and `test_every_fixture_identifier_is_non_allocated_
  and_says_how_strong_that_claim_is` asserts that it does.
- **`P8` Platform ID**: a tail number in a range no nation issues, asserted by a test. The standard
  makes each nation responsible for uniqueness "within the set of platforms it owns", so a
  non-allocated `P3` is what makes the `P8` safe, and the two claims are coupled.
- **`M3` Platform Type and `J2` Sensor ID – Type**: values from the **Available for Future Use**
  ranges (57–254 and 36–254), so no fixture ever claims to be an E-8C carrying an APY-7. This also
  exercises the `unresolved_raw` path on every fixture for free.
- **`J14` Radar Mode**: `1` (generic MTI) where a working mode is needed, and a reserved value
  where the reserved path is under test.
- **`D32.16`/`D32.17` truth tags**: all-zeros — the standard's own no-information value — except in
  the one fixture that tests the truth-tag park.

The **nine** cases the set has to catch, each chosen because it pins a decision above that a
golden file can hold still:

1. **A minimal packet**: Packet Header, Mission Segment, Job Definition Segment, one Dwell Segment
   with three hi-res target reports. The base case for the platform `Entity`, the platform `Track`,
   three target `Entity` objects and three `DETECTION` `Event` objects.
2. **A Dwell Segment with `D5 = 0`** and the `D32.*` existence-mask bits **set**, which §3.4.1 makes
   conformant. Must produce the platform sample and no target objects, and must not read a single
   byte past the segment — the fixture puts a Free Text Segment immediately after it so that
   reading one byte too many corrupts a value a golden file checks.
3. **A reduced-bandwidth Dwell Segment** whose dwell area straddles the **prime meridian**, with
   delta reports on both sides of it. This is the fixture the integer-domain reconstruction exists
   for: a float-degrees implementation puts half the targets 360° away, and the golden file catches
   it. A companion report has a delta that overflows the latitude reconstruction and must be
   refused.
4. **A delta report with `D10`/`D11` masked out**, which must be refused with the mask quoted — the
   conditional-group discipline, in the one place where guessing would silently work most of the
   time (a scale factor of zero puts every target at the dwell centre, which looks plausible).
5. **A multi-day mission**: reference date on day one, `D6` values of 117 935 200 (the standard's
   own Annex C-3 worked example, reproduced exactly so the fixture and the specification agree
   arithmetically) and one beyond Table 3-9's stated maximum but within `I32`, which must convert
   and record.
6. **A packet with a Dwell Segment and no Mission Segment**, tested three ways against settlement
   2's three paths: refused with no caller-supplied date, translated with one, and asserted never to
   consult the injected clock for the date in either case. The `received_at` in the golden file
   comes from `times.frozen_clock`, so a clock leak into `observed_at` is visible as a matching
   instant.
7. **A `P7`/`D32.10` simulation conflict matrix**: `P7 = 0` with a `D32.10` of 129 (refused, the
   intra-payload check), `P7 = 0` with a `D32.10` of 142 (translated, because a tagging device is
   not simulated), and `P7 = 1` against a deployment declaring `synthetic = false` (refused, the
   deployment check). Three refusals and one translation from four nearly identical packets, which
   is what makes settlement 4's two checks provably independent.
8. **An HRR Segment whose `H2`/`H3` name a dwell in the same packet, and a second whose do not**,
   so both branches of the HRR `observed_at` chain run and the second lands in
   `unresolved_references`. With `H25 = 2` and `H26 = 1`, so the scatterer array's byte sizing is
   exercised rather than assumed.
9. **A packet carrying an unsupported segment between two supported ones** — type `132`
   (Releasability, registered and undefined) with a valid `S2` — which must be skipped exactly,
   parked with its bytes, recorded, and must leave the segment after it decoded correctly. This is
   the skip-and-record rule as a golden file — the golden asserts the type code, the size and the
   parked bytes are all present, so a silent skip fails it — and it is the fixture that proves the
   Controlled Extension blocker is contained rather than merely named.

A tenth is worth naming as **deliberately absent**: there is no fixture for a target `Track`,
because settlement 5 says no target `Track` is ever produced, and the test that enforces that is a
negative assertion over every fixture rather than a fixture of its own.

## ASTERIX Category 048 — Monoradar Target Reports, ingest and egress

**Every row below was a SPECIFICATION before it was a claim.** The row set was written and
reviewed with `not yet` in every status column and no code, exactly as the Legion rows were
before adapter #5 and the NITS and GMTIF rows before #9 and #10; `adapters/asterix_cat048.py`
then implemented it and the markers became `cat048 1.0.0`. The difference between those two
states is the whole reason the status column exists — and three rulings reversed in between,
each noted where it happened.

CAT048 is the **sensor-side complement of CAT021**, and the relationship is worth stating
precisely because it is not "a second ASTERIX adapter". §1.1: this document "describes the
message structure for the transmission of monoradar target reports from a radar station
(conventional Secondary Surveillance Radar (SSR), monopulse, Mode S, conventional primary radar
or primary radar using Moving Target Detection (MTD) processing), to one or more Surveillance
Data Processing (SDP) Systems." So where CAT021 is what a ground station emits after it has
received cooperative broadcasts and decoded them, CAT048 is what **one radar** emits about what
**it** detected — and that inverts three of CAT021's four easy problems:

- CAT021 arrives with a fully decoded WGS-84 latitude and longitude. **CAT048 arrives as slant
  range and azimuth from a station whose position the format never states.** This is the largest
  difference and it is not a units problem; see settlement 3.
- CAT021 carries seven time items. **CAT048 carries one**, and §4.2.1 requires it to be
  "consistent with the reported plot position", so gap 13's one-record-two-instants problem does
  not arise here at all.
- CAT021's target is cooperative and self-reporting. **A CAT048 target may not be an object.**
  The format has codes for a reflection, a sidelobe reply, a split plot, an angel, a phantom
  plot, a bird, a flock of birds and a wind turbine, because a primary radar return is an echo
  before it is anything else.

And it adds a problem neither has: the record can announce that a track has **ended**, which is
the first terminal declaration any source in this document makes.

The **no-fusion rule applies with a sharper edge than usual.** CAT048 carries the radar's own
local track number (I048/161) and its own track status (I048/170), and ingesting those is
translation of the source's claims — the station said "my track 199 is confirmed, SSR-maintained
and manoeuvring", and repeating that is reading. What is forbidden is the join: **no CAT048
report is ever correlated with anything**, including a CAT021 record sharing an aircraft address
in I048/220. Deriving the same `entity_id` from the same 24-bit address is not that join — it is
the same pure function `adsb.py` and `asterix_cat021.py` already apply, and it is what lets a
fusion layer *elsewhere* do the joining with an audit trail. The distinction is settlement 11.

### The pin

CAT048 is a ratified EUROCONTROL specification, so like CAT021 and unlike Legion it does not
need a hash to be trustworthy. The hash is recorded anyway, for the reason the CAT021 pin gives:
an edition number names a **document** and a SHA-256 names the **copy that was read**.

`fixtures/cat048/spec/cat048_pin.json` carries the whole thing — the bundle URL, the member
filename, the byte count, the hash, and every extracted value cited below with its locus.

| | |
|---|---|
| Category | **048** — Monoradar Target Reports |
| Core specification | EUROCONTROL-SPEC-0149-4, ASTERIX Part 4 Category 048, **Edition 1.32**, Released Issue |
| Edition date | **01/07/2024** — the document's own claim, on the cover and in the page-ii Document Characteristics table. The publication page lists the same file as "2 July 2024"; the pin records both and picks neither, because the identifying facts are the edition number and the hash |
| SHA-256 | `8f9c51ff18b0a4cb6b6c1ae752622ffe9b0dbecef721f0ee123bd352000c996e`, 725 626 bytes, 64 pages |
| Retrieved | 2026-08-23, from the "Download all" bundle at `https://www.eurocontrol.int/archive_download/all/node/11127`, member `eurocontrol-cat048-part4-edition-1-32.pdf` |
| Corroboration | The publication page states 708.62 KB for its Edition 1.32 entry. 725 626 / 1024 = 708.619 KB, so the pinned copy is the page's file and not some other Edition 1.32 |
| ASTERIX Part 1 | Edition 3.1, Released Issue, **28 October 2021** — §2.2 reference 1. See the next section |
| **Reserved Expansion Field** | **NOT PINNED — obtainable, and simply not obtained.** Defined in a separate publication (Appendix A, SPEC-0149-4A) that this document does not even list among its references. A download, not an unobtainable artefact; see settlement 1 for the reopen condition |
| CAT034 | §2.2 reference 5 pins Part 2b Category 034 Monoradar Service Messages, Edition 1.30. **Out of scope**, and settlement 2 states what that costs |
| Editions NOT read | 1.31 and earlier. The I048/030 code table has grown in nearly every edition since 1.17 and the table below is transcribed from 1.32's own text; an earlier edition would enumerate it short |

**Edition 1.32 removed the item roster.** The Document Change Record (page vi) lists `Table
"Standard Data Items" removed` against §5.1, and §5.1 in this edition is one sentence of prose:
"The standardised Data Items which shall be used for the transmission of monoradar target
reports from a Mode S station are described in the following pages." So **§5.3.1's Table 2, the
UAP, is the sole item roster**, and the coverage table below is keyed on it — all 28 FRNs
including the SP and RE slots. The Table of Contents still carries the heading "5.1 Standard
Data Items" at page 13, so the heading outlived the table.

### Part 1 — the mechanics this category does not state, and why nothing was diffed

§2.2 reference 1 pins ASTERIX Part 1 (SUR.ET1.ST05.2000-STD-01-01) at **Edition 3.1, Released
Issue, 28 October 2021**. FORMAT_COVERAGE.md's CAT021 pin row already carries `ASTERIX Part 1 |
Edition 3.1, November 2021`. **The editions match, so the existing basis is cited and no second
document was obtained** — and three things about that are recorded rather than smoothed over.

**The date disagrees and is not reconciled here.** CAT048 §2.2 says 28 October 2021; the CAT021
row says November 2021. One is a publication date and the other an edition date, or one is
simply wrong. Neither document was retrieved by anyone in this repository, so the discrepancy is
a finding (ambiguity 12) and the CAT021 prose is left alone rather than edited on a guess.

**CAT021's structural machinery was never Part 1-derived here, so there was nothing to inherit.**
`adapters/asterix_cat021.py` contains no reference to Part 1 at all — `grep` finds none — and its
FSPEC handling is implemented directly from the CAT021 document's own layout. The CAT021 pin row
cites Part 1 for exactly one thing: "the applicable document for the 'Element Populated'
convention the REF uses". So the honest answer to "does cat021's structural machinery transfer"
is that it was re-derived from CAT048's own text, below, and not transferred.

**And the mechanics are checkable against CAT048's own normative table**, which is the difference
between an inherited assumption and a verified one. Table 2 lists 28 numbered FRNs and
interleaves four explicit rows reading `FX | n.a. | Field Extension Indicator | n.a.` — after
FRN 7, after FRN 14, after FRN 21 and after FRN 28. Four groups of seven plus four FX bits is
exactly 32 bits. **So the UAP itself fixes both the stride (seven FRNs per octet) and the
maximum FSPEC length (four octets) without Part 1 being opened.**

What CAT048 genuinely does *not* state, and therefore still inherits:

| Inherited from Part 1 | What CAT048 says instead |
|---|---|
| The octet-level FSPEC encoding | §4.6.2 says only "FSPEC is the Field Specification". §4.7 says items are "assembled in the order defined by the Field Reference Number (FRN) in the associated UAP" and "Transmitted items shall always be in a Record with the corresponding FSPEC bits set to one". Corroborated by Table 2 above, stated by Part 1 |
| The explicit-length form of the SP and RE fields | **Nothing.** Neither field has a §5.2 description anywhere in the document. They appear only as FRN 27 and FRN 28 of Table 2, with a length notation `1+1+` that the UAP's own legend does not define — the legend explains a stand-alone figure and `1+`, and stops |
| The "Element Populated" convention | Used without being named, throughout I048/020's extensions 2 to 5. This is the one place the Part 1 dependency is *substantive* rather than structural, and it is the same convention the CAT021 REF needed: **`#EP` clear is not a value of zero** |

**"The editions agree" is a weaker claim than "the FSPEC/FX/UAP mechanics were compared", and
this repository cannot make the stronger one for either category.** That is stated plainly
because a matching edition number is easy to mistake for a diff.

### Settlement 1 — the RE field is PARKED for this phase, and the reason is PROCEDURAL, not textual

CAT021 put its whole Reserved Expansion Field **in scope** and argued for it at length. Here the
RE field is **parked verbatim and never decoded**, and the honest statement of why is short and
unflattering: **the defining document is public, was identified in the same session as the core
specification, and simply was not acquired or pinned.** Nothing in the pinned text forces this
park, and this row set does not pretend otherwise.

Two facts are true and only one of them is a reason. The true-but-not-a-reason fact is that **this
document defines no part of the Reserved Expansion Field** — FRN 28 has no §5.2 entry, and the RE's
contents are named only by path from inside other items' notes, so decoding it *from the pinned
text alone* would mean inventing a structure. The reason is that the appendix which does define it
was not pinned. Those are different claims, and conflating them would dress a procedural gap as a
textual one.

**This is a weaker park than either precedent it resembles**, and the difference is worth naming
rather than blurring. GMTIF's Controlled Extension blocker rests on §L.4 of a pinned document
reading "(TO BE PROVIDED)" — the field tables do not exist to be obtained. The NITS XSD row rests
on a schema "distributed through NATO national representatives" that could not be had. **CAT048's
Appendix A is neither: it is a download.** So this park is not "not obtainable here" but "not
obtained here", and it carries a correspondingly cheap exit condition.

**The document depends on the appendix and does not cite it.** §2.2 lists exactly five
references — Part 1, ED-73F/DO-181F, ED-275/DO-386, EMS Edition 4.0, and Part 2b CAT034 — and
the Reserved Expansion Field appendix is not among them, while eight passages in §5.2 make
normative statements about its contents:

| REF item named | Locus | What the pinned text says about it |
|---|---|---|
| `M4E` | §5.2.2, NOTE to FOE/FRI | IFF interrogators with three-level Mode 4 classification "shall encode the detailed response information in data item M4E of the Reserved Expansion Field of category 048. In this case the value for FOE/FRI in I048/020 shall be set to '00'" |
| `ERR` / "Extended Range Report" | §5.2.4 NOTE 4 and §5.2.2 NOTE to bit 7 | "The ERR data item shall only be sent if the value of RHO is equal to or greater than 256NM" and "in this case — and this case only — the ERR Data Item in the Reserved Expansion Field shall provide the range value of the Measured Position in Polar Coordinates" |
| `I048/REF/GEN48/ALTM2` | §5.2.6 NOTE | an alternative Mode-2 value for radars interrogating in Mode S *and* Mode 5 |
| `I048/REF/GEN48/ALTM3` | §5.2.10 NOTE 3 | the same for Mode-3/A |
| `I048/REF/GEN48/ALTFL` | §5.2.12 NOTE 5 | the same for Flight Level |
| `MD5` / `M5N` subfield #1 | §5.2.6, §5.2.10, §5.2.12 | the bits that say a Mode-2, Mode-3/A or Flight Level value "has been derived from a Mode 5 Reply/Report" |
| `MD5` / `M5N` subfield #5 | §5.2.7 NOTE | I048/055's V, G, L, A4, A2, A1, B2, B1 "shall be identical to the values of the corresponding bits in subfield #5" |
| "the Mode 5 items in the REF" | §5.2.3, Code 37 | the code's entire definition is a pointer: "Duplicate Mode 5 PIN (refer to the Mode 5 items in the REF)" |

**What parking it actually loses**, named individually rather than waved at:

1. **A target beyond 256 NM has no range.** §5.2.4 NOTE 4 recommends that RHO be set to its
   maximum — "bits 32/17 all set to 1" — when the ERR item is used. So the parked RHO of such a
   target is a **floor and not a range**, and it is recorded as one, the AIS 102.2 kt discipline.
   The `ERR` bit in I048/020's first extension *is* decoded, so the floor is machine-visible
   rather than looking like a 255.996 NM measurement.
2. **A Mode 4 interrogation that happened is indistinguishable from one that did not.** The M4E
   note forces FOE/FRI to `00` — which reads "No Mode 4 interrogation" — whenever the real
   three-level result is in the REF. The only case the note preserves in the core item is "No
   reply". This is the most consequential loss and it is a *silent* one.
3. **A Mode 5-derived value looks conventionally interrogated.** Nothing in the core items says
   a Mode-2, Mode-3/A or Flight Level came from a Mode 5 reply.
4. **Code 37 is uninterpretable by construction.**

**Nothing is exempted from the lossless gate.** The RE field is an explicit-length field, its
octets are parked verbatim as hex, and egress restores them byte-for-byte. The never-drop rule
is satisfied by *presence*, not by a waiver — the same terms on which CAT021 parks its SP field
and `adsb.py` parks a register payload.

**The exit condition, named as a blocker rather than a wish.** The publication page for
"CAT048 … Part 4 Category 48 (Appendix A)" lists **Edition 1.13, 4 December 2024** as current
and **Edition 1.12, 2 July 2024** as the edition contemporaneous with the pinned core. Phase 2
inherits a decision it must not take by default: pinning "the latest" pairs a July core with a
December appendix, and pinning "the contemporaneous one" pins a superseded appendix. Either way
the pairing is a claim and belongs in the pin. That listing was read off the page on 2026-08-23
and **no copy was retrieved, sized or hashed** — so it is a named exit condition and explicitly
not a pin.

### Settlement 2 — CAT034 is out of scope, and this is what declining it costs

§2.2 reference 5 pins Part 2b, Category 034 Monoradar Service Messages, Edition 1.30. Real
CAT048 streams interleave with CAT034 North-marker and sector-crossing messages. **CAT034 is
out of scope for adapter #11**, and the row states the loss rather than only the decision.

The document puts service messages outside itself, in §4.1: "The transmission of monoradar
information shall require the transmission of two types of messages: • data messages of radar
target reports; • radar service messages used to signal status information of the radar station
to the user systems **(not covered by this document)**."

**What is lost:**

| Lost | Consequence |
|---|---|
| **Antenna rotation timing context** | CAT034's North-marker and sector-crossing messages are what relate a target report's time of day to the antenna's azimuth sweep and to the scan period. CAT048 carries no scan period and no antenna position, so nothing downstream can compute the expected update rate of a track or say how overdue an un-updated one is. `Entity.valid_to` stays `None` on every record except an End of Track Message for exactly this reason: the format gives no staleness horizon and CAT034 is where one would come from |
| **The area in which an IC Conflict is detectable** | §5.2.3 NOTE 6 is explicit: "Together with Codes 35 and 36 the possibility to communicate the area within which the detection of an IC Conflict is possible was implemented in the Category 034 Specification Ref. [5] by means of Message Type 008." So I048/030 codes 35 and 36 arrive as a bare assertion that a potential Interrogator Code conflict exists or is detectable, with the *where* unreadable |
| **Radar station status** | Which RDP chain is live, and whether the station is degraded. I048/020's `RDP` bit says "Report from RDP Chain 1" or "Chain 2" and CAT034 is what makes that more than a label |

**And the reason is structural, not effort.** CAT034's value is almost entirely *context
accumulated across messages* — the last North marker, the current sector, the standing station
status. A translator holding any of it is holding stream state, which is the transport refusal
every adapter here has already made: AIS's fragment buffer, ADS-B's frame buffer, Legion's HTTP
client, CAT021's UDP reassembly. A different UAP and a different item catalogue make CAT034 a
different *adapter*; needing accumulated state to be useful at all makes it a different *kind of
thing*. Deferred, not rejected — and if it lands, it lands as adapter #12 with its own pin.

### Settlement 3 — Position: derived from an INJECTED sensor position, or parked, and never silently either

**Reversed from this row set's first draft**, which refused to derive geometry at all. The
distinction the first draft missed is the one that matters, and it is the injected-clock
precedent: **I048/140 carries no date and this adapter supplies one from `self.now()`; I048/040
carries no site and the site is the same class of deployment configuration.** What
`asterix_cat021.py` refuses is "a station configuration it **discovered from the data**" — an
adapter inferring its own parameters from the payload it is translating. A `sensor_position`
handed to the constructor is not that act. It is the same shape as the injected clock: a value
the caller owns, stated once, outside the payload, and visible in every golden file.

So the rule has two branches and no third:

| | `sensor_position` injected | not injected |
|---|---|---|
| `Entity.position` | a `Position`, derived — **when a height is also available**, see below | `None` |
| `attributes.cat048_measured_position` | `RHO` and `THETA` carried losslessly | identical |
| `attributes.position_basis` | that the position is **derived**, from which site value, which height item, which earth model and which arithmetic | that no site was injected, so nothing was derived |

**The polar measurement is carried losslessly in both branches.** That is not a courtesy: the
raw `RHO` and `THETA` integers are what egress re-emits, and a `Position` computed from them is a
derived, one-way view — the Legion `position_basis` rule and CAT021's `cat021_position` rule,
applied where the derivation is finally ours rather than the source's.

#### The conversion, owned in full

Nothing here may be implicit, because **the pinned document contains none of this arithmetic**
(see the counter-argument below). Four declarations, all recorded in `attributes.position_basis`:

1. **Earth model: WGS-84**, and the document does name it — §4.3.2.2 describes the radar's own
   tangential plane as "a plane tangential to the **WGS-84 Ellipsoid** at the location of the
   radar head". So the ellipsoid is the specification's, even though the geodesic solution is not.
2. **Azimuth reference: local geographical north**, per §4.3.1 — "The reference for the azimuth
   shall be local geographical north." `THETA` is therefore a **true** bearing and needs no
   magnetic declination. Stated by the text, not assumed.
3. **Slant-range treatment: stated, never skipped.** `RHO` is a slant range, so the ground range
   is `sqrt(RHO² − Δh²)` with `Δh` the target's height above the site, and the geodetic position
   is the geodesic direct solution from the site at that distance on bearing `THETA`.
4. **The height comes from inside the same record**, which is not a join: combining items within
   one record is reading, and it is what the *radar itself* does — §4.3.2.2 says its own 3-D to
   2-D conversion uses "either the measured height or an assumed target height". Precedence, with
   the step taken recorded:

   | Order | Item | What it costs |
   |---|---|---|
   | 1 | **I048/110**, height measured by a 3D radar, LSB 25 ft, **mean sea level** zero reference | Nothing beyond its own quantisation, *provided* the injected site altitude is also MSL-referenced. A height **difference** is far less geoid-sensitive than an absolute height, which is why `Δh` is usable here while `alt_m` still is not — see the altitude row set |
   | 2 | **I048/090**, flight level, LSB ¼ FL | A pressure altitude used as a geometric height. Recorded as an approximation, because the two differ by hundreds of metres in ordinary weather, and the basis names which item supplied `Δh` |
   | 3 | **I048/100** | **Never.** Settlement 5 declines to decode it, and a height this row set refuses to read cannot become a height it silently uses |

**The no-height case yields no `Position`, and that is a documented outcome rather than a silent
one.** With a site injected but no usable height item, `Entity.position` is `None`, the polar
values are parked as in the non-injected branch, and `position_basis` names the missing height as
the reason. The record itself is **not** refused — it is translatable and suppressing it would be
filtering.

The alternative — assume `Δh = 0` and treat the slant range as a ground range — is rejected with
a number, because the intuition that it is a small correction is wrong in exactly the geometry a
monoradar sees most: the error is worst at **short** range and high altitude, not at long range.
A target at FL350 is 5.76 NM above the site. Directly overhead it has `RHO ≈ 5.76` NM and a
ground range near zero, so a zero-height assumption paints it **10.7 km from the antenna**; at
`RHO` = 10 NM the ground range is 8.17 NM and the error is still 1.83 NM. At `RHO` = 200 NM the
same target's error is 0.08 NM, which is where the intuition comes from and where it does not
matter.

#### What is still not derived

- **`Position.alt_m` stays `None`.** I048/110 is mean-sea-level referenced and `alt_m` is metres
  above the WGS-84 ellipsoid; the geoid separation is tens of metres and needs a geoid model
  nothing here carries. The height **difference** used for the slant correction is a different
  quantity from an absolute height, and the geoid largely cancels across a sensor-to-target
  baseline — so using `Δh` and declining `alt_m` is one consistent position, not two.
- **`Position.accuracy_m` stays `None`.** I048/210 gives per-axis standard deviations "within the
  local grid system"; collapsing σ(X) and σ(Y) into one horizontal figure is a modelling choice
  (RMS? CEP? which axis convention?), and the derivation adds error of its own that nothing in the
  record bounds. **Gap 17.**
- **`Position.position_source` is `ESTIMATED`**, and the enum is the reason rather than the
  physics. `PositionSource` offers `GNSS`, `INERTIAL`, `MANUAL` and `ESTIMATED`, and **none of
  them names a sensor measurement.** `ESTIMATED` is chosen because it is the only one that is not
  an outright false statement, and because it answers correctly the question the enum's own
  docstring says the field exists for — "the field that lets a commander tell a fix from a guess"
  in a GNSS-denied environment: a radar position is emphatically **not** `GNSS`, so it survives
  jamming that a GNSS fix does not. It is also not a lie in the narrow sense: what reaches
  `Position` is a *computed* product of a measurement, an injected site and possibly a pressure
  altitude. `attributes.position_source_basis` records all of that, and the missing enum member
  is a 1.1.0 candidate rather than a schema change.
- **I048/042 is still parked, and the reason survives the reversal.** Its origin "coincides with
  the radar head position", so a site would in principle place it too — but **which of two
  transforms produced it is signalled in a different item**, `TCC` in I048/170, and the projection
  is named only as "e.g. a stereographical projection". Deriving from it would mean reading one
  item's meaning out of another's bit *and* guessing an unnamed projection. I048/040 is the single
  source of derived geometry, which also means there is exactly one owner of the arithmetic.
- **`Event.geometry` stays `None`.** The position lives on the `Entity`, as it does for every
  other point-target adapter here; `Event.geometry` is for footprints.

#### The counter-argument, recorded because it is a real one

**None of the arithmetic above is in the pinned text.** §4.3.2.1 gives only the radar-plane
identities `X = RHO * SIN(THETA)` and `Y = RHO * COS(THETA)` — no slant correction, no geodetic
step. §4.3.2.2 names the WGS-84 ellipsoid and then defers the projection to "a suitable
projection technique … (e.g. a stereographical projection)". There is no geodesic direct solution
anywhere in the document, and no stated slant-range formula.

So this is the first geometry in this repository that a **binary** adapter computes from
arithmetic the pinned standard does not supply — GMTIF's positions are exact binary angles the
standard tabulates, CAT021's arrive already decoded. The consequence is stated rather than
softened: the derived latitude and longitude are **this adapter's arithmetic**, not the
specification's, and the defence is not that the document authorises it but that (a) every input
is either on the wire or injected by the caller, (b) the earth model and the azimuth datum are
the document's own, and (c) the result is checkable — the derived position must invert back to
`RHO` and `THETA` within the item's own least significant bits, 1/256 NM and 360/2¹⁶ °, and a
test asserts it. That round-trip is what keeps the arithmetic honest without the document
blessing it. It is recorded in **gap 24**.

### Settlement 4 — Time: one item, a stated range, and a permitted absence

CAT048 has exactly one time item, and §4.2.1 ties it to the position: "The target time stamp
shall be consistent with the reported plot position." §4.2.2 adds that "every individual target
report shall have its own individual timestamp" and that UTC "as specified in ICAO Annex 5 shall
be used".

| | I048/140 Time of Day |
|---|---|
| Definition | "Absolute time stamping expressed as Co-ordinated Universal Time (UTC)." |
| Format | 3 octets |
| LSB | "= 2⁻⁷ seconds = 1/128 seconds" |
| Stated range | "Acceptable Range of values: 0<= Time-of-Day<=24 hrs" |
| Encoding rule | "This data item shall be present in every ASTERIX record, **except in case of failure of all sources of time-stamping**. The time information, coded in three octets, shall reflect the exact time of an event, expressed as a number of 1/128 s elapsed since last midnight." |
| Note 1 | "The time of day value is reset to 0 each day at midnight." |

**The date comes from the injected clock**, `self.now()`, never `datetime.now()` — the AIS
construction generalised, exactly as CAT021 does it, so the adapter stays a pure function of
(payload, clock) and golden tests remain possible.

**The rollover ruling transfers, and three things around it do not.** CAT021's rule is: the
candidate instants are the stated time of day on the receipt date, the day before and the day
after, and the one **nearest the receipt instant** wins, with `payload.observed_at_basis`
recording that a rollover was applied. That rule is unchanged here — Note 1's reset is the same
sentence CAT021's items carry, and the LSB is the same 1/128 s, so the CAT048 fixtures can echo
CAT021's `midnight_rollover_before` / `midnight_rollover_after` values deliberately. What CAT048's
text forces to differ:

1. **The refusal above 24 hours is textual here, not inferred.** CAT021's refusal of a value at
   or beyond 86 400 s was derived from "the counter resets at midnight". CAT048 *states* the
   bound: "Acceptable Range of values: 0<= Time-of-Day<=24 hrs". Twenty-four bits at 1/128 s
   reach 131 071.992 187 5 s, so the field can express times of day that the item's own range
   excludes. A value above the bound is a refusal quoting the item, the raw 24-bit integer and
   the decoded seconds. **Never a modulo** — taking 100 000 s mod 86 400 moves a contact by
   hours and leaves every other check passing.
2. **The boundary value is a genuine ambiguity, and CAT021 did not have one.** The stated range
   is `<= 24 hrs`, so exactly 86 400.000 s (raw 11 059 200) is *inside* it — while Note 1 says
   the counter resets to 0 at midnight, which makes 86 400 unreachable. Two sentences of the same
   section disagree about whether one value can occur. Ruled: **the single value 86 400.000 s is
   accepted**, on the range's own inequality, and resolved as 00:00:00.000 of the following day,
   with the reading recorded in `observed_at_basis`. Refusing a value the document lists as
   acceptable would be this adapter overruling the text; accepting anything above it would be
   ignoring the text. Ambiguity 1.
3. **A record with no time at all is permitted, and CAT021's was not.** "except in case of
   failure of all sources of time-stamping" is an explicit licence to omit the item. CAT021 could
   lean on a guarantee that a positional record carries 071 or 073; there is no such guarantee
   here. So the chain has two steps and the second is not an error path: I048/140 if present,
   otherwise **the injected clock**, with `observed_at_basis` recording that the record carried
   no time item and that the specification permits it. That is a *stated* absence — it goes to
   `attributes.unavailable_fields`, not to `unresolved_raw`.

`Event.received_at` is the injected clock, always. **The raw 24-bit integer is parked and egress
re-emits from the park** rather than recomputing from `observed_at`: 1/128 s is 7.8125 ms, not a
whole number of milliseconds, and `times.render` emits three decimal places, so a round trip
through the canonical timestamp would not be the identity. Same rule, same reason, as CAT021.

### Settlement 5 — Three altitude items, three different quantities, and no arbitration

I048/090, I048/100 and I048/110 can all appear in one record. They are **not three measurements
of one quantity**, which is the fact the row set exists to preserve.

| | I048/090 | I048/100 | I048/110 |
|---|---|---|---|
| Name | Flight Level in Binary Representation | Mode-C Code and Code Confidence Indicator | Height Measured by a 3D Radar |
| Locus | §5.2.12 | §5.2.13 | §5.2.14 |
| Length | 2 octets | 4 octets | 2 octets |
| Quantity | a **pressure** altitude — a flight level | the **raw Gray-coded reply**, plus per-pulse confidence | a **geometric** height |
| Datum | the 1013.25 hPa flight-level datum | none — it is an uninterpreted reply | "The height shall use **mean sea level** as the zero reference level" |
| Value field | bits 14/1, "LSB= 1/4 FL **in two's complement form**" | bits 28/17 "Mode-C reply in Gray notation"; bits 12/1 pulse quality | bits 14/1, "3D height, in binary notation. Negative values are expressed in two's complement. LSB = 25 ft" |
| Sent when | "Mode C code or Mode S altitude code is present **and decodable**" | "only … when a **not validated or undecodable** Mode C code has been received" | "This data item is optional." |

**Edition 1.32's own change to I048/090, quoted current.** The Document Change Record lists
`Clarification "in two's complement form" and Note added to I048/090` against §5.2.12. The
current wording of the value field is exactly: **"bits-14/1 (Flight Level) LSB= 1/4 FL in two's
complement form"**. Its five Notes now read:

> 1. When Mode C code / Mode S altitude code is present but not decodable, the "Undecodable Mode
>    C code / Mode S altitude code" Warning/Error should be sent in I048/030.
> 2. When local tracking is applied and the received Mode C code / Mode S altitude code
>    corresponds to an abnormal value (the variation with the previous plot is estimated too
>    important by the tracker), the "Mode C code / Mode S altitude code abnormal value compared
>    to the track" Warning/Error should be sent in I048/030.
> 3. The value shall be within the range described by ICAO Annex 10
> 4. For Mode S, bit 15 (G) is set to one when an error correction has been attempted.
> 5. For radar systems interrogating with various technologies (such as military radars
>    interrogating in Mode S and Mode 5), element I048/REF/GEN48/ALTFL provides the possibility
>    to transmit an alternative Flight Level value. If this Data Item carries a Flight Level
>    value that has been derived from a Mode 5 Reply/Report, then bit-2 in I048/REF/MD5/SF#1 or
>    bit-2 in I048/REF/M5N/SF#1 shall be set to 1.

**Which Note 1.32 added is not determinable from the pinned copy**, and is recorded as an
inference rather than a finding: Note 3 is the only one whose subject matter is not traceable to
an earlier change-record entry, so it is the likely insertion, but establishing it needs Edition
1.31, which nothing here pins. **Note 3 is also load-bearing and unresolvable**: it bounds the
field by reference to ICAO Annex 10, a document §2.2 does not list and this repository does not
pin. So the enforceable range is the field's own — 14 bits of two's complement at ¼ FL, i.e.
−2048.00 to +2047.75 FL — and `attributes.flight_level_range_basis` records that the narrower
ICAO bound the item defers to was not readable.

**None of the three populates a CDM altitude.** `Position.alt_m` is documented as metres above
the WGS-84 ellipsoid, and each of these three is a different quantity against a different datum.
Settlement 3 does use a height — as a **difference**, for the slant-range correction — and that is
a separate act from writing one into `alt_m`, which fails on datum alone:

- **I048/090 is a pressure altitude.** This is **gap 9**, and the ruling is CAT021's verbatim:
  parked at `attributes.flight_level` **in FL, the source's own unit**. Note the same collision
  CAT021 named rather than resolved — `adsb.py` parks the concept at `attributes.baro_altitude_ft`
  and CAT021 at `attributes.flight_level`; converging on one key here would repeat gap 1's
  mistake of turning a private convention into a de-facto standard with no owner.
- **I048/110 is a geometric height above mean sea level.** MSL is not the ellipsoid; the geoid
  separation is tens of metres and varies by place. Parked in feet at
  `attributes.height_3d_ft` with the datum recorded. **This is a third datum**, alongside HAE and
  the pressure datum, and it sharpens gap 9's existing note that "the datum has to be carried
  rather than assumed" rather than opening a new gap.
- **I048/100 is not decoded at all**, and that is the sharpest of the three rulings. The item's
  encoding rule says it is sent "only … when a **not validated or undecodable** Mode C code has
  been received". **The item exists to report that the altitude could not be established.**
  Gray-decoding it would manufacture precisely the value the item says is unavailable. No Gray
  table appears anywhere in this document either. So the 12 reply bits and the 12 confidence bits
  are parked verbatim, and `unresolved_raw` records that a Mode-C reply arrived and was
  deliberately not interpreted.

**Disagreement is recorded, never adjudicated.** When I048/090 and I048/110 are both present the
difference is computed and written to `attributes.cat048_altitude_disagreement` — as a *statement
about the record*, with both source units, both datums and an explicit note that **the two are
not the same quantity, so a bare numeric comparison is itself a defect**. Nothing is preferred,
averaged or dropped. A disagreement between two statements by one source is the source's to
explain.

**And the format has its own vocabulary for the disagreement**, which is the genuinely
interesting fact here and the reason this is not merely a parking decision. I048/090's Notes 1
and 2 route the two failure cases into I048/030 by name: an undecodable code should raise
**code 18**, and a value the tracker judges abnormal should raise **code 12**. So a conforming
station tells us, in a third item, that its own altitudes disagree. Those codes are parked with
the rest of I048/030 and `attributes.altitude_basis` names them when present — the source's
verdict is carried as the source's, and this adapter adds none of its own.

### Settlement 6 — I048/120 is a scalar along the line of sight, and even its sign is implementation-defined

I048/120 Radial Doppler Speed **parks. It reaches no `Kinematics` field.**

§5.2.15 defines it as "Information on the Doppler Speed of the target report", a compound item
with a one-octet primary subfield and two possible secondary subfields:

| Subfield | Shape | Fields |
|---|---|---|
| **#1** Calculated Doppler Speed | 2 octets | bit 16 `D` — "= 0 Doppler speed is valid; = 1 Doppler speed is doubtful"; bits 15/11 spare fixed to zero; bits 10/1 `CAL` — "Calculated Doppler Speed, coded in two's complement. LSB= 1 m/sec" |
| **#2** Raw Doppler Speed | 7 octets | bits 56/49 `REP` repetition factor; bits 48/33 `DOP` Doppler Speed LSB 1 m/s; bits 32/17 `AMB` Ambiguity Range LSB 1 m/s; bits 16/1 `FRQ` Transmitter Frequency LSB 1 MHz |

**A radial Doppler speed is not a speed.** It is the projection of a velocity onto the radar's
line of sight, so a target flying tangentially across the beam has a radial speed of zero and a
ground speed of three hundred knots. `Kinematics.speed_mps` is a speed over the ground — that is
what AIS's SOG means, what an ADS-B type 19 subtype 1/2 frame states, and what gap 10 is
explicitly about. Writing a line-of-sight component into it would not be imprecise; it would be
a different quantity under the wrong name, and it would read as a ground speed to every consumer.

**And the sign is not even defined by the standard**, which by itself forecloses any canonical
mapping. §5.2.15's Note on subfield #1, quoted whole:

> Although the meaning of a positive or negative value is implementation dependent and shall be
> described in the ICD of the system generating the ASTERIX record, it is recommended to transmit
> a positive value for targets moving away from the radar.

A field whose sign convention is a per-deployment ICD matter, with a *recommendation* rather than
a rule as the fallback, cannot be normalised into a canonical model without inventing the
convention. So `CAL` is parked with its raw two's-complement integer, its decoded m/s, the `D`
doubtful bit, and `attributes.radial_speed_sign_basis` recording that the direction of positive
is unstated and that the recommendation was **not** applied as an assumption. `REP`, `DOP`, `AMB`
and `FRQ` park likewise — `AMB` is a Doppler ambiguity interval and `FRQ` is a transmitter
frequency, neither of which is a property of the target at all.

This opens **gap 25**, which is gap 24's other half: a radial speed is measured along the same
line of sight a polar position is measured on, so both are missing the same thing — a **sensor
frame**. They are recorded as two gaps and flagged to be designed as one.

**Two structural details worth naming**, both of which decode into plausible nonsense rather than
into an error. The primary subfield's bits 6/2 are documented as "(Spare) Subfields #3/7: Spare —
= 0 Absence of Subfield; = 1 Presence of Subfield" — presence bits for subfields that do not
exist. **A set bit there is a refusal**, on CAT021's Not-Used-FRN reasoning: there is nothing to
decode, so skipping is impossible and guessing a length desynchronises everything after it. And
the encoding rule says "When used, **only one** secondary subfield shall be present", yet both
`CAL` and `RDS` bits exist — a record setting both is non-conforming but perfectly decodable,
since both subfields are fixed-length. Ruled: **both are parsed and parked, the non-conformance
is recorded, and the record is not refused.** Refusing a decodable record over a redundancy rule
would discard a real target report. Ambiguity 5.

### Settlement 7 — I048/030 is a SET, and here is Edition 1.32's table in full

§5.2.3's format is "Variable length Data Item comprising a first part of one-octet, followed by
one-octet extents as necessary", with **bits 8/2 carrying a 7-bit Code** and bit 1 the `FX`,
annotated "Extension into first extent **(next W/E condition value)**". Note 1 removes all doubt:
"It has to be stressed that **a series of one or more codes can be reported per target report**."

**So this is the only item in the category whose FX extensions each carry an independent value
rather than more fields of one value**, and the CDM has to carry a sequence.

**How the CDM carries the set.** `attributes.cat048_warning_error_codes` is an **ordered list**
of `{code, text}` objects in **wire order**, plus the raw octets alongside. Three properties, each
load-bearing:

- **Ordered, not a set.** The wire order is data, and egress is only byte-exact if the codes go
  back out in the order they came in.
- **Duplicates preserved.** Nothing in §5.2.3 forbids repeating a code, so collapsing them would
  be a normalisation that breaks the round trip.
- **Never sorted.** Same reason.

**The table, transcribed from Edition 1.32's own text** — not from any earlier edition, and
including the "see Note" annotations that are part of the entries. Dash spacing is normalised for
legibility here (the document writes code 34 as `…report wrong) –see Note 5 below`);
`fixtures/cat048/spec/cat048_pin.json` holds all 38 strings byte-for-byte as the document sets
them, and that copy is the one to quote from:

| Code | Description | Code | Description |
|---|---|---|---|
| 0 | Not defined; never used. | 19 | Birds |
| 1 | Multipath Reply (Reflection) | 20 | Flock of Birds |
| 2 | Reply due to sidelobe interrogation/reception | 21 | Mode-1 was present in original reply |
| 3 | Split plot | 22 | Mode-2 was present in original reply |
| 4 | Second time around reply | 23 | Plot potentially caused by Wind Turbine |
| 5 | Angel | 24 | Helicopter |
| 6 | Slow moving target correlated with road infrastructure (terrestrial vehicle) | 25 | Maximum number of re-interrogations reached (surveillance information) |
| 7 | Fixed PSR plot | 26 | Maximum number of re-interrogations reached (BDS Extractions) |
| 8 | Slow PSR target | 27 | BDS Overlay Incoherence |
| 9 | Low quality PSR plot | 28 | Potential BDS Swap Detected |
| 10 | Phantom SSR plot | 29 | Track Update in the Zenithal Gap |
| 11 | Non-Matching Mode-3/A Code | 30 | Mode S Track re-acquired |
| 12 | Mode C code / Mode S altitude code abnormal value compared to the track | 31 | Duplicated Mode 5 Pair NO/PIN detected |
| 13 | Target in Clutter Area | 32 | Wrong DF reply format detected |
| 14 | Maximum Doppler Response in Zero Filter | 33 | Transponder anomaly (MS XPD replies with Mode A/C to Mode A/C-only all-call) — see Note 5 below |
| 15 | Transponder anomaly detected — see Note 4 below | 34 | Transponder anomaly (SI capability report wrong) — see Note 5 below |
| 16 | Duplicated or Illegal Mode S Aircraft Address | 35 | Potential IC Conflict |
| 17 | Mode S error correction applied | 36 | IC Conflict detection possible — no conflict currently detected |
| 18 | Undecodable Mode C code / Mode S altitude code | 37 | Duplicate Mode 5 PIN (refer to the Mode 5 items in the REF) |

**Code 37 is Edition 1.32's own addition** — the change record's 1.32 row reads `Value 37 added
to I048/030`. **Code 36 carries the flagged NOTE** the change record points at: its 1.31 row
reads `Values 35 & 36 added to I048/030 (Check NOTE on Code = 36); Note 3 deleted`, and the note
in question is inside Note 5's bullet for code 36: "Code 36 indicates that a plot is in a
configuration that it would be possible to detect an IC Conflict with another interrogator.
Currently no potential IC Conflict has been detected. **NOTE: Although implementation dependent,
the use of this code should be limited to the target acquisition phase.**" That nested NOTE is
recorded because it makes code 36 a *phase-dependent* assertion — the same code outside target
acquisition means something the standard declines to define. And **Note 3 now reads, in full,
"Note outdated and deleted."** — the deletion left a numbered stub rather than renumbering, so a
reader looking for Note 3's content finds a tombstone.

**Four encoding-rule consequences, each ruled rather than left to an implementer:**

| Situation | Ruling |
|---|---|
| **Code 0 present.** The rule says the item "shall be transmitted only if different from zero. The zero value for this field means no warning neither error conditions and that the target classification is unknown" | **Accepted, not refused.** Code 0 has a stated meaning, so the record is translated, the code is recorded, "target classification unknown" lands in `attributes.unavailable_fields`, and the non-conformance (the item should not have been sent) is noted. Refusing a whole target report over one redundant octet would be this adapter filtering |
| **Codes 33 or 34 without code 15.** "If Codes 33 or 34 are sent, also Code 15 shall be sent — see Notes below" | Recorded as a non-conformance in `attributes`, **not a refusal**. It is a redundancy requirement whose violation costs nothing structurally — and Note 4 explains why the redundancy exists at all: "Code 15 is kept for backwards compatibility … ASTERIX Encoders implementing Category 048 in line with Edition 1.27 or earlier of this specification cannot indicate specific Transponder Anomalies" |
| **A code in 64–127.** "Values 0-63 are allocated by the AMG, values 64 to 127 are available for allocation by manufacturers and shall be described in the corresponding ICD" | The code number is carried with **no text**, in `attributes.unresolved_raw`. No ICD is pinned here, so a manufacturer code is a number this adapter can transport and cannot read — and that is a different fact from a code it has never heard of |
| **A code in 38–63.** Allocated to the AMG and not yet assigned | Carried with no text in `unresolved_raw`, distinguished in the basis from the manufacturer range: an unassigned AMG code is a *future* standard value, a manufacturer code is a *private* one |

**Nothing in this item derives `Entity.entity_type`**, and Note 7 is why: "The use of this Data
Item is implementation specific and shall be described in the ICD of the system generating the
Category 048 target reports." Reading `Birds`, `Helicopter` or `Wind Turbine` into a canonical
entity type would be reading a per-deployment convention as a classification. Note 2 says the
same thing more gently — "Data conveyed in this item are of secondary importance". See settlement
9 for where `entity_type` actually comes from.

### Settlement 8 — The End of Track Message, and the four items Edition 1.30 relaxed

A report announcing a track's termination is a distinct message shape, and Edition 1.30 rewrote
four encoding rules for it. **The trigger is one bit**: I048/170 First Extension bit 8, `TRE` —
"Signal for End_of_Track; = 0 Track still alive; = 1 End of track lifetime (last report for this
track)". Each of I048/220, /230, /240 and /250 names it identically: *"except for an 'End of
Track Message' (i.e. I048/170, First Extension, Bit 8 is set to '1') in which this Data Item is
optional."*

**What it becomes in the CDM: an event and a carried status. It does NOT close the entity.**

| CDM | Value on a TRE record | Why |
|---|---|---|
| `Event.event_type` | `STATUS_CHANGE`, overriding whatever the record would otherwise be | The reportable fact is the end of a track's lifetime. Calling it a `DETECTION` would claim a sensor found something; calling it a `TRACK_UPDATE` would claim the track continues. This is the same line `ais.py` draws putting a static-data broadcast at `STATUS_CHANGE` |
| `Event.severity` | `INFO` | A track ending is normal. The severity line in this document sits at the standard's own emergency declaration and a track-end is not one |
| `Entity.valid_to` | **`None`, as on every other CAT048 record** | See below. A test pins that a TRE record does not close the entity |
| `Entity.attributes` | `attributes.track_end` records the bit, beside the rest of the I048/170 status | The bit is carried as what it is: a claim about the station's track record |

**Reversed from this row set's first draft, which set `valid_to` to the record's `observed_at`.**
The overturning argument is the text's own scoping of the two nouns. `TRE` says "End of track
lifetime (**last report for this track**)", and I048/161 defines the thing being tracked as "a
unique reference to a **track record within a particular track file**". So what ends is **one
radar's track record**, not the aircraft, and not the entity the `entity_id` names — which, when
I048/220 is present, is keyed on a 24-bit airframe address that outlives any station's track file.

`Entity.valid_to` is documented "When it ceased. None = still current / open-ended", and it sits
on an object identified by that airframe address. Writing the track-end instant there tells every
consumer that does not read a basis key that **the aircraft's state ceased**, which is a false
statement; the first draft's defence was a basis string, and a basis string is a convention in an
untyped bag rather than a contract. The failure modes are not symmetric: over-closing an entity is
a false statement, and leaving a real terminal declaration in `attributes` is a truncation. This
document refuses false statements and names truncations.

**So the truncation is named.** CAT048 makes the only explicit terminal declaration of any source
in this document, and the CDM has nowhere to put it: there is no "track terminated" representation
on `Track`, no relation object, and `Entity.valid_to` is the wrong field for the reason above.
That is **gap 26**, and it lands in `MIGRATIONS.md` as a 1.1.0 candidate in gap 15 / gap 19
territory rather than as a reinterpretation of an existing field.

**How the four items' conditional encoding is honoured, in both directions.** The relaxation is
permissive on ingest and must not become licence on egress.

| Item | Ingest, `TRE` clear | Ingest, `TRE` set | Egress |
|---|---|---|---|
| `I048/220` Aircraft Address | "shall be present in every ASTERIX record conveying data related to a Mode S target". Mode S is observable — I048/020 `TYP` ∈ {100, 101, 110, 111} — so **absence is a refusal**, quoting `TYP` and the FSPEC | absence is a **permitted absence**: `unavailable_fields`, with the encoding rule quoted. Never a refusal, never `unresolved_raw` | emitted **only if the park holds it.** Never synthesised — an invented aircraft address is the worst byte this adapter could write |
| `I048/230` Comms/ACAS Capability and Flight Status | same rule, same refusal | same permitted absence | same |
| `I048/240` Aircraft Identification | "**After the first extraction** of aircraft identification, this item shall be present…" — a condition about the *station's history*, which a stateless translator cannot observe. So **absence is never a refusal**, whatever `TRE` says | permitted absence | same |
| `I048/250` BDS Register Data | "…**provided BDS Register Data has been extracted in the last scan**" — also unobservable. Absence is never a refusal | permitted absence | same |

Two consequences fall out and both are worth stating. **Only two of the four are gateable**, and
the reason is not the relaxation — it is that /240 and /250 were always conditioned on facts
about the station rather than about the record. And **the recommendation is honoured by fidelity,
not by policy**: all four notes say "it is recommended that systems sending [the item] in an 'End
of Track Message' continue to do so", and a byte-exact round trip does that automatically — what
was on the wire goes back on the wire. What egress must never do is *add* an item to a TRE record
that arrived without one, in the name of the recommendation.

**And the specification uses two names for this message and defines neither.** I048/170, /220,
/230, /240 and /250 say "End of Track Message". I048/040 Note 1 says "except for a **track
cancellation message**", and I048/200's encoding rule says "except for a **track cancellation
message**". Nothing in the document defines either term or says they are the same thing.
Ambiguity 2, and it has a real consequence: whether a TRE record may carry I048/040 and I048/200
depends on which name means which.

### Settlement 9 — Identity: two steps, because a PSR plot has no address

CAT021 could treat I021/080 as "the stable key … on every record". **CAT048 cannot**: I048/220 is
present only for Mode S targets, and a primary-radar plot has no address, no identification and
possibly no track number. `source_ids` is required with `min_length=1` on every kind, so the
chain has to bottom out somewhere real.

| Step | When | `system` | `external_id` | What it claims |
|---|---|---|---|---|
| 1 | I048/220 present | `ICAO24` | the 24-bit address as six hex characters | A persistent airframe identity. **The same `ids.derive("ICAO24", …)` call `adsb.py` and `asterix_cat021.py` make**, so the three agree without any of them knowing the others exist |
| 2 | absent | a report-scoped derived id, via `ids.derive_with_basis` | keyed on SAC, SIC, the time of day, `RHO`, `THETA` and the record index | "This observation." A report with no stated airframe identity **is** a one-shot observation, and an id that says so is more honest than one that implies continuity |

**The first draft had a middle step and it is reversed.** It made I048/161 a `SourceId` under a
`SAC:SIC:track` composite whenever no address was present, with the recycling hazard carried in
`attributes.identity_caveat`. CAT021's declines table already rejected exactly that — "Resolving
I021/161 Track Number into an identity … a station-scoped, recycled 12-bit number" — and the
citation was in the first draft's own text, arguing against itself.

**The failure modes are not symmetric, which is what settles it.** A recycled 12-bit number is
reused within one station's track file, so keying `entity_id` on it merges two different airframes
hours apart into **one entity** — a false statement, asserted in the field the CDM guarantees is
"stable across updates", and a caveat in an untyped bag does not unmake it. Declining to key on it
loses the continuity the radar genuinely states across scans — a **truncation**, and one nothing
downstream mistakes for a fact. This document refuses false statements and names truncations, so
the truncation is named:

**What the truncation costs.** For a PSR-tracked target with no Mode S address, consecutive scans
of the same radar track now produce **different `entity_id` values**, so the one case where CAT048
does state continuity is the one case the CDM cannot express. The station's claim is not lost — the
track number, its SAC/SIC scope and I048/170's `CNF`/`RAD`/`DOU` all ride in `attributes` — but it
is a claim a consumer must reassemble, which is fusion's job and is exactly where it belongs. It is
recorded in **gap 27**, beside gap 26's terminal declaration: both are cases where the radar states
something about the *life of a track* and the CDM has no vocabulary for a track's life at all.

**`Entity.entity_type` comes from I048/020 `TYP`, not from I048/030.** `TYP` is in a mandatory
item — §5.2.2's encoding rule is "This Data Item shall be present in every target record" — and
it is not implementation-specific, which I048/030's Note 7 says its own codes are.

| `TYP` | Meaning | `entity_type` | Why |
|---|---|---|---|
| `001` | Single PSR detection | `UNKNOWN` | A primary return is an **echo**. The format's own code list — reflection, sidelobe, split plot, angel, bird, wind turbine — exists because it may not be an object at all |
| `010`, `011` | Single SSR / SSR + PSR detection | `PLATFORM` | A transponder replied, so something carrying a transponder is there |
| `100`, `101`, `110`, `111` | Mode S All-Call / Roll-Call, ± PSR | `PLATFORM` | Same, with an address |
| `000` | No detection | `UNKNOWN` | §5.2.4 Note 1: "No detection is signalled by the TYP field set to zero". The record is a track report with no plot behind it |

The known infelicity is stated rather than hidden: a **flock of birds detected by an SSR-equipped
station** would still read `PLATFORM`. Refining it would mean reading I048/030, whose own Note 7
makes it an ICD matter — so the classification codes ride in `attributes` in full, and
`attributes.entity_type_basis` records the reason the refinement was declined.

**`Entity.affiliation` is `UNKNOWN`, always — and CAT048 makes that decline harder than CAT021
did.** I048/020's first extension carries `FOE/FRI` with the literal values "= 01 Friendly
target", "= 10 Unknown target", "= 11 No reply", plus `MI` "Military identification" and `ME`
"Military emergency". A field whose value is spelled *Friendly* is more tempting than CAT021's
Mode 5 authentication bits, and the answer is the same: **turning an IFF interrogation result
into `FRIENDLY` is an identification decision belonging to an IFF authority, not to a
translator**, and over-claiming `FRIENDLY` is the dangerous direction. Two further reasons are
specific to this format and both are in the text:

- **The field is not even reliable when the REF is in use.** §5.2.2's note: interrogators with
  three-level classification "shall encode the detailed response information in data item M4E …
  In this case the value for FOE/FRI in I048/020 shall be set to '00'." So `00` means either "no
  interrogation" or "the answer is somewhere this adapter cannot read".
- **`10` is spelled "Unknown target", not "not interrogated".** A vocabulary that distinguishes
  *unknown* from *no interrogation* from *no reply* is making three different claims, and
  collapsing any of them into an affiliation loses the distinction the vocabulary exists for.

All the bits are parked in full and `attributes.affiliation_basis` records the decline on every
object, so it is visible in the data rather than only in the code. `Entity.symbol` follows from
the affiliation through `symbology.sidc_from_affiliation`, so every CAT048 contact is an UNKNOWN
glyph, with `attributes.symbol_basis` saying why.

**`Entity.confidence` and `Track.track_quality` are both `None`.** CAT048 is dense with quality
statements and not one of them is a 0..1 assessment: I048/060, /065, /080 and /100 give per-pulse
reply confidence; I048/210 gives "a vector of standard deviations" in NM, NM/s and degrees;
I048/170 `DOU` signals "Low confidence in **plot to track association**", which is a
data-association verdict rather than a claim about identity; I048/030 code 9 is "Low quality PSR
plot". All parked. A standard deviation in nautical miles is not a probability, and mapping one
onto a 0..1 field would fabricate a scale.

**`Event.severity` is raised by exactly one bit.** I048/020 first extension `ME`, "Military
emergency", → `CRITICAL` / `ALERT`. That is the standard's own emergency declaration, and the
line sits precisely where `ais.py` puts navigational status 14, where `adsb.py` puts emergency
state 1–6, and where CAT021 puts I021/200 `ME`. Three things deliberately do **not** raise it:

- **I048/230 `STAT` values 2, 3 and 4** ("Alert, no SPI, aircraft airborne" and so on). A Mode S
  flight-status alert fires on a Mode 3/A code change as well as on an emergency, so it is a
  procedural condition — the same reading CAT021 gives I021/200 `SS` = 2 and `adsb.py` gives
  surveillance status 2.
- **I048/020 `SPI`** — Special Position Identification, an ident pulse a controller asked for.
- **I048/260's presence.** Its encoding rule is "This item shall be present when a Resolution
  Advisory (RA) has been generated in the last scan", so presence *is* the source asserting an
  active RA. It still does not raise severity, and the reason is consistency with a decision
  already taken: CAT021's row for I021/008 `RA` says an active advisory is "parked, and it does
  **not** raise severity here: the RA itself arrives in I021/260 and grading an equipment status
  as an emergency would be the translator judging". An ACAS advisory is an equipment output, its
  content is undecodable from this document (settlement 10), and RAs include benign resolutions.
  `attributes.severity_basis` records that an active RA was present and deliberately not graded.

### Settlement 10 — Opaque register payloads: parked in full, never exempted

The AIS precedent applies to both of these: **unpack or park, and never silently exempt from the
lossless gate.** Both are parked, in full, with their structure preserved — so the never-drop
rule is satisfied by *presence*, not by a waiver.

**I048/250 BDS Register Data** (§5.2.25). "Repetitive Data Item starting with a one-octet Field
Repetition Indicator (REP) followed by at least one BDS Register comprising one seven octet BDS
Register Data and one octet BDS Register code." Each register is parked as its 56 bits of hex
plus its `BDS1`/`BDS2` address. Not decoded, for CAT021's reason at I021/250 — the registers are
a separate register set with their own document, [Ref. 2] ED-73F/DO-181F, which nothing here
pins, and `adsb.py` already names a Mode S BDS adapter as a *different* adapter. Three traps in
the notes, each a row:

| Trap | The text | Consequence |
|---|---|---|
| **`BDS1 = BDS2 = 0` is not register 0,0** | Note 3: "In case of data extracted via Comm-B broadcast, all bits of fields BDS1 and BDS2 are set to 0; in case of data extracted via GICB requests, the fields BDS1 and BDS2 correspond to the GICB register number" | An adapter treating `0,0` as an address would mislabel **every broadcast-extracted register**. The address is parked with its extraction mode recorded, and `0,0` means "Comm-B broadcast, register unidentified" |
| **The register set is split across three items** | Note 1: "For the transmission of BDS Register 2,0, Data Item I048/240 is used." Note 2: "For the transmission of BDS Register 3,0, Data Item I048/260 is used. In case of ACAS Xu … BDS Register 3,1 will be transmitted using Data Item I048/250" | Nothing may assume I048/250 holds all extracted registers. 2,0 is in /240, 3,0 is in /260, and 3,1 comes back into /250 for ACAS Xu |
| **Length is stated twice** | The prose says "one seven octet BDS Register Data and one octet BDS Register code" — eight octets per register. The bit diagram numbers octets 2 to 9, i.e. eight after the one-octet `REP`. The UAP says `1+8*n` | All three agree at eight, which is worth checking rather than assuming: a mis-sized stride in a repetitive item shifts every register after the first |

**I048/260 ACAS Resolution Advisory Report** (§5.2.26). Seven octets, "bits-56/1 (ACASRA)
Currently active ACAS Resolution Advisory (RA)". **Not decoded, and the reason is quotable and
decisive**: the only decode authority the item cites is Note 1 — "**Refer to ICAO Draft SARPs for
ACAS** for detailed explanations." A *draft*, unnamed by edition, absent from §2.2's reference
list, and there is no field breakdown of the 56 bits anywhere in the document. Parked as 56 bits
of hex in `Event.payload` with the decline recorded. Note 2 is carried too, because it changes
what the item *is* on newer equipment: "In case of ACAS Xu, the Resolution Advisory consists of
two parts (BDS30 and BDS31). BDS31 will be transmitted using item 250" — so on ACAS Xu the
advisory is **split across two items**, and either half alone is incomplete.

### Settlement 11 — A translator owes no fusion. Stated once, and for the seventh time

CAT048 tempts three joins that no previous format did, so the rule is restated with the specific
temptations named:

1. **A CAT048 report and a CAT021 record sharing an aircraft address.** Forbidden. Both derive
   the same `entity_id` from `ids.derive("ICAO24", …)`, which is a pure function of the address
   and not a correlation — and that agreement is what lets a fusion layer join them *where the
   join is audited*. The adapter never looks for a counterpart, holds no cache and reads no other
   feed. A fixture exists specifically to assert that two such objects are produced and **not**
   merged.
2. **Records in one block sharing a track number.** Forbidden, and it is the CAT021
   `two_records_one_block` decision one level down: several records in one block are several
   target reports. **A data block never becomes a `Track` on ingest.**
3. **A plot and a track in the same block.** Forbidden, and this one is CAT048-specific. §4.6.2
   says "A single User Application Profile (UAP) is defined and shall be used whether plot or
   track information is provided by the radar", and §4.6.1 says a track "is a superset of a
   plot". So one block can hold a plot and a track for the same target, and associating them is
   precisely the plot-to-track association the *radar* performs and reports its confidence in
   through I048/170 `DOU`. Doing it again here would be redoing the source's work, invisibly,
   with less information than the source had.

### What the adapter's input IS — one data block, and nothing else

`to_cdm()` takes **one ASTERIX data block**: the octets from the `CAT` byte through the last
record, and nothing else. The boundary is where it was drawn for AIS, ADS-B, Legion, CAT021 and
GMTIF. The adapter does not own, and must never acquire, a socket, a UDP reassembly buffer, a
multicast group, a stream framer, or a CAT034 sector context.

**The constructor takes two injected values, and the second is new to this adapter family.** The
clock, as every adapter does; and an optional `sensor_position` — the radar site — which
settlement 3 uses to derive geometry. Both are the same kind of thing: a value the *caller* owns,
supplied once, outside the payload, and visible in every golden file. What remains forbidden is
the adapter **obtaining** either one for itself: reading a site out of the payload, or resolving a
SAC/SIC through a lookup table it carries. That is "a station configuration it discovered from the
data", and it is a different act from accepting an argument.

Accepted forms are the raw octets or the already-parsed dict a fixture twin holds — the
`bytes | dict` shape, for the same reason: `lossless.unrepresented()` has no leaves to harvest
from bytes.

| Input | Becomes |
|---|---|
| a block holding one record | `Entity` + `Event` |
| a block holding N records | N × (`Entity` + `Event`), in block order |
| a block holding zero records | a refusal — see the structural gate |

### The wire form

#### Data block

    CAT (1 octet, = 48) | LEN (2 octets, big-endian) | FSPEC + items (record 1) | ... | FSPEC + items (record N)

§4.6.2: "Data Category (CAT) = 048, is a one-octet field indicating that the Data Block contains
radar target reports"; "Length Indicator (LEN) is a two-octet field indicating the total length
in octets of the Data Block, **including the CAT and LEN fields**".

#### FSPEC — four octets at most, and no "Not Used" FRNs

Bits 8..2 signal the presence of the next seven FRNs in UAP order; bit 1 is `FX`. **28 FRNs and
four FX bits is exactly 32 bits**, so four octets is the maximum and Table 2 says so itself.
Items then appear **in FRN order**, back to back, with no separators and no lengths of their own
except where the item's format carries one.

**The refusal case differs from CAT021's, and the difference matters.** CAT021's UAP marks FRNs
43–47 "Not Used", so a set bit there is a refusal. **CAT048 has no Not-Used FRN at all** — every
one of its 28 names a defined item. The analogous refusal here is **the trailing `FX` of the
fourth octet**: Table 2 lists it, but no FRN 29 exists, so a record that sets it names nothing
that can be decoded and nothing whose length can be guessed. Refused, quoting the octet.

**The FSPEC octets are parked verbatim.** A conforming encoder emits the shortest FSPEC covering
its highest set FRN, but the specification does not forbid a longer one, and the round trip is
byte-exact only if the FSPEC emitted is the FSPEC read.

#### Item format kinds — all five, as CAT021 uses all five

| Kind | Shape | CAT048 items |
|---|---|---|
| **Fixed** | exactly N octets | I048/010 (2), /140 (3), /040 (4), /070 (2), /090 (2), /220 (3), /240 (6), /161 (2), /042 (4), /200 (4), /210 (4), /080 (2), /100 (4), /110 (2), /230 (2), /260 (7), /055 (1), /050 (2), /065 (1), /060 (2) |
| **Variable** | one octet, `FX` in bit 1, extending one octet at a time | I048/020 (five defined extensions), I048/030, I048/170 (one defined extent) |
| **Repetitive** | one-octet `REP`, then REP × a fixed block | I048/250 (REP × 8 octets) |
| **Compound** | a presence-bit primary subfield, itself `FX`-extensible, then the present subfields in bit order | I048/120, I048/130 |
| **Explicit** | one-octet length **including the length octet itself**, then opaque contents | SP (FRN 27) and RE (FRN 28) — and neither has a §5.2 description here, so the form is Part 1's |

**Three traps, all of which decode into plausible nonsense rather than into an error:**

- **A variable item's extension count is data-dependent.** A decoder assuming one octet for
  I048/020 would read the next item's first octet as an extension and shift everything after it.
  I048/020 has *five* defined extensions, which is the deepest in the category.
- **A compound item's primary subfield is itself `FX`-extensible.** I048/130's says so
  explicitly: "bit-1 (FX) = 0 End of Primary Subfield; = 1 Extension of Primary Subfield into
  next octet". Only seven subfields are defined, so a *second* primary octet has no defined
  subfields — refused, on the same grounds as the trailing FSPEC `FX`.
- **`FX` is documented as leading somewhere that does not exist, THREE times.** Phase 1 recorded
  two and the adapter found the third. I048/170's first extent says "= 1 Extension into second
  extent" and §5.2.19 defines no second extent; **I048/020's FIFTH extension says "= 1 Extension
  into next extension" and §5.2.2 defines no sixth**; and Table 2's fourth `FX` follows FRN 28
  where no FRN 29 exists. All three are refusals, and all three look like ordinary extension
  bits. The third was found by writing the length rules rather than by reading, which is the
  argument for a per-item octet cap: without one the FX chain still refuses — it runs off the end
  of the record — but the message names the wrong cause, and a refusal that misidentifies itself
  is one nobody can act on. `refusals/descriptor_sixth_extension.cat048` pins it.

#### Spare and unused bits are parked verbatim, never normalised

§4.4: "Decoders of ASTERIX data shall never assume and rely on specific settings of spare or
unused bits. However in order to improve the readability of binary dumps of ASTERIX records, it
is **recommended** to set all spare bits to zero." Same wording and same consequence as CAT021
§4.3: zeroing is a recommendation, so a conforming encoder may set them to anything and
normalising would break the byte-exact round trip on exactly the traffic most worth
investigating.

#### There is no checksum here either

**Neither §4.6.2 nor §4.7 nor any §5.2 item defines a CRC, checksum or parity field** at block,
record or item level. So the gate is structural, and deliberately strict for the reason the ADS-B
parity gate is strict:

- `CAT` ≠ 48 → refusal. A CAT021 or CAT062 block decoded against the CAT048 UAP yields a
  plausible wrong aircraft, not an error.
- `LEN` disagrees with the buffer → refusal.
- The records do not tile `LEN` exactly → refusal, and **no records are emitted**, not even those
  parsed before the discrepancy. A partial *set* of objects that looks complete is forbidden by
  the `Adapter` contract exactly as a partial object is.
- A set FSPEC bit with no octets left → refusal, quoting the FRN.
- The trailing `FX` of octet 4 set, or a second primary-subfield octet in I048/130, or a set
  spare presence bit in I048/120's primary subfield → refusal.
- A variable item not terminating on `FX` = 0 inside the record → refusal.
- I048/250's `REP` not fitting the remaining octets → refusal.
- **The mandatory items must be there**: I048/010 ("shall be present in every ASTERIX record"),
  I048/020 ("shall be present in every target record"), and I048/140 unless the record is
  claiming the time-stamping failure §5.2.17 permits.

`attributes.integrity_basis` records on every object that CAT048 carries no checksum at any level
and that the structural gate is what passed — so a consumer comparing a CAT048 contact against a
1090ES one knows which was checked and which was only parsed.

**Codec discipline, on GMTIF's terms.** CAT048 is FSPEC-gated binary, so the arithmetic layer
follows `adapters/gmtif_codec.py`: every bound is computed from the standard's own arithmetic,
every out-of-range value is a `CodecError` naming the value and the range, and **nothing is
clamped, masked to the field width, or wrapped**. The bounds this row set derives, each from a
stated LSB and width:

| Field | Width | LSB | Range | Source of the arithmetic |
|---|---|---|---|---|
| `RHO` | 16 | 1/256 NM | 0 .. 255.996 093 75 NM | §5.2.4 states "Max. range = 256-(1/256) NM" — so the derivation is checkable against the document |
| `THETA` | 16 | 360/2¹⁶ ° | 0 .. 359.994 506 8 ° | §5.2.4 |
| I048/042 `X`, `Y` | 16 each, two's complement | 1/128 NM | −256 .. 255.992 187 5 NM | §5.2.5 states "Max. range = 256 NM" |
| I048/090 Flight Level | 14, two's complement | ¼ FL | −2048.00 .. +2047.75 FL | §5.2.12; the ICAO Annex 10 bound Note 3 defers to is not readable here |
| I048/110 3D-Height | 14, two's complement | 25 ft | −204 800 .. +204 775 ft | §5.2.14 |
| I048/120 `CAL` | 10, two's complement | 1 m/s | −512 .. +511 m/s | §5.2.15 |
| I048/140 Time of Day | 24 | 1/128 s | 0 .. 86 400 s **accepted**; above → `CodecError` | §5.2.17's stated range, not the field width. The field reaches 131 071.992 187 5 s |
| I048/161 Track Number | 12 | 1 | 0 .. 4095 | §5.2.18 states "(0..4095)" |
| I048/200 groundspeed | 16 | 2⁻¹⁴ NM/s | 0 .. 3.999 938 96 NM/s | §5.2.20 labels the field "max. 2 NM/s", which the width exceeds — ambiguity 6 |
| I048/210 σ(X), σ(Y) | 8 | 1/128 NM | 0 .. 1.992 187 5 NM | §5.2.21 states "0<= Sigma(X)<2 NM" |

`I048/200`'s groundspeed conversion is **exact in float64** and the row set claims so rather than
hedging: 2⁻¹⁴ NM/s × 1852 m = 0.113 037 109 375 m/s, a dyadic rational times an integer needing
11 significand bits.

### How to read the row sets

Left column names data items as §5.2 numbers them, with the subfield or bit where one matters.
The parsed form the adapter's own parser produces is what each `.parsed.json` twin will hold and
what the never-drop check is measured against. `Status` reads `cat048 1.0.0` on every row now,
so **the mapping is a claim and `tests/test_cdm_asterix_cat048_adapter.py` is what makes it
one** — including `test_the_row_set_claims_this_adapter`, which fails if a row slips back to
`not yet` while the code implements it.

### Row set — the block and record envelope

Nothing here describes the world; it describes the radar and the framing. All of it is parked and
egress rebuilds the block from it.

| CAT048 | CDM field | Status | Notes |
|---|---|---|---|
| `block.category` | `Entity.attributes` | `cat048 1.0.0 · parked` | the CAT octet as read. A block whose category is not 48 is refused rather than decoded |
| `block.length` | `Entity.attributes` | `cat048 1.0.0 · parked` | parked, and **recomputed on egress rather than copied** — a length that disagrees with the octets is discarded by every ASTERIX decoder, the reason `adsb.py` recomputes its CRC |
| `block.record_index`, `block.record_count` | `Event.payload` | `cat048 1.0.0 · parked` | which record of how many. Without it, two objects from one block are indistinguishable from two objects from two blocks |
| `record.fspec` | `Entity.attributes` | `cat048 1.0.0 · parked` | the FSPEC octets verbatim. The shortest covering FSPEC is conventional, not required, so the round trip is byte-exact only if we re-emit what we read |
| `record.spare_bits` | `Entity.attributes` | `cat048 1.0.0 · parked` | every spare and unused bit as sent, per §4.4. Normalising would break the round trip on non-conforming traffic |
| *(measured)* | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.integrity_basis` — that CAT048 defines no checksum at any level and the structural gate is what passed |
| *(measured)* | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.unavailable_fields` — fields the source explicitly marked absent: a validity bit cleared, an item the encoding rules permit to be missing, I048/030 code 0's "target classification is unknown" |
| *(measured)* | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.unresolved_raw` — wire values read and not usable: an I048/030 code in 38–127, a `RAD` of `11` (Invalid), a Gray-coded Mode-C reply, an ACAS advisory, a `CDM` of `11` (Unknown). A **different fact** from the list above, and the pair is the point |
| everything unmapped | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.source_extras`, structure intact |

### Row set — I048/010 Data Source Identifier, and the sensor that everything is relative to

| CAT048 | CDM field | Status | Notes |
|---|---|---|---|
| `I048/010` SAC, SIC | `Entity.attributes` | `cat048 1.0.0 · parked` | §5.2.1's Definition is "Identification of the radar station **from which the data is received**" and its Encoding Rule is "This Item shall be present in every ASTERIX record" — mandatory, and it names the RECEIVER rather than the target. Parked at `attributes.data_source`. **Not a `SourceId`**: it identifies the sensor, not the target, and filing a station under the object's identifiers is how a fused picture ends up with an entity per receiver. **Sharper here than in CAT021** — every measurement in the record is relative to this station, so the SAC/SIC is the key a consumer would need to resolve the geometry at all, and there is nowhere canonical to put it. See **gap 14** and **gap 24** |
| `I048/010` NOTE | *(no field)* | `cat048 1.0.0` | "The up-to-date list of SACs is published on the EUROCONTROL Web Site (http://www.eurocontrol.int/asterix)" — the URL `fixtures/cat021/spec/sac_pin.json` pinned, which is why the fixtures' SAC evidence transfers by citation rather than by analogy |

### Row set — I048/020 Type and Properties of the Target Report and Target Capabilities

Mandatory in every target record, five defined extensions, and the source of `entity_type` and of
the only severity this format raises.

| CAT048 | CDM field | Status | Notes |
|---|---|---|---|
| `I048/020` TYP | `Entity.entity_type` | `cat048 1.0.0` | `UNKNOWN` for `000` (No detection) and `001` (Single PSR detection); `PLATFORM` for the six SSR and Mode S values. A primary return is an echo before it is an object — settlement 9 |
| `I048/020` TYP | `Entity.attributes` | `cat048 1.0.0 · parked` | code and wording at `attributes.report_type`, all eight values accounted for |
| `I048/020` TYP | `Event.event_type` | `cat048 1.0.0` | `DETECTION` when TYP ≠ `000`; `TRACK_UPDATE` when TYP = `000`, because §5.2.4 Note 1 says a zero TYP signals no detection and calling it a detection would claim one the item denies. Overridden to `STATUS_CHANGE` by I048/170 `TRE` — settlement 8. **First adapter here whose ordinary case is `DETECTION`**: AIS, ADS-B and CAT021 receive self-reports, a radar detects |
| `I048/020` SIM | `Entity.attributes` | `cat048 1.0.0 · parked` | Simulated target report. Parked at `attributes.simulated_target`, and it **does not rewrite `Entity.source.synthetic`** — that is a deployment declaration about the feed and a payload bit may not flip it. The Legion `EXERCISE_*` rule and CAT021's SIM row, reached from one bit |
| `I048/020` TST | `Entity.attributes` | `cat048 1.0.0 · parked` | Test target report, parked on the same terms |
| `I048/020` RDP | `Entity.attributes` | `cat048 1.0.0 · parked` | Report from RDP Chain 1 or 2. A station-internal routing fact; **what makes it interpretable is CAT034**, which is out of scope — settlement 2 |
| `I048/020` SPI | `Entity.attributes` | `cat048 1.0.0 · parked` | Special Position Identification. Parked, **not a severity** — an ident pulse is a procedural request. The item's own note adds "For Mode S aircraft, the SPI information is also contained in I048/230", so the same fact can arrive twice; both are parked and neither is preferred |
| `I048/020` RAB | `Entity.attributes` | `cat048 1.0.0 · parked` | Report from aircraft transponder, or from a **field monitor (fixed transponder)**. Parked, and deliberately **not** turned into `FACILITY` — CAT021's identical decision: it says who transmitted, not what kind of thing it is |
| `I048/020` ERR | `Entity.attributes` | `cat048 1.0.0 · parked` | Extended Range present. **Decoded and load-bearing**: it is what says the parked `RHO` is a floor rather than a range, since §5.2.4 NOTE 4 recommends RHO be set to all-ones when the REF's ERR item carries the real value. Settlement 1 |
| `I048/020` XPP | `Entity.attributes` | `cat048 1.0.0 · parked` | X-Pulse present. Parked with its note quoted — "This bit shall always be set when the X-pulse has been extracted, independent from the Mode it was extracted with" — so it says nothing about *which* mode |
| `I048/020` ME | `Event.severity` / `Event.event_type` | `cat048 1.0.0` | Military emergency → `CRITICAL` / `ALERT`. **The only bit in CAT048 that raises severity**, and the line sits exactly where CAT021 puts I021/200 `ME`, `adsb.py` puts emergency state 1–6 and `ais.py` puts navigational status 14 |
| `I048/020` MI | `Entity.attributes` | `cat048 1.0.0 · parked` | Military identification. Parked, **never an affiliation** — settlement 9 |
| `I048/020` FOE/FRI | `Entity.attributes` | `cat048 1.0.0 · parked` | the four Mode 4 values including "Friendly target", parked in full at `attributes.mode_4_foe_fri`, with the M4E note recorded: when the REF carries the three-level result this field "shall be set to '00'", so `00` is ambiguous between "not interrogated" and "unreadable here" |
| *(none)* | `Entity.affiliation` | `cat048 1.0.0` | `UNKNOWN`, always. `attributes.affiliation_basis` distinguishes the ordinary case from the IFF case this adapter declines to read |
| *(derived)* | `Entity.symbol` | `cat048 1.0.0` | from the affiliation via `symbology.sidc_from_affiliation`, so every CAT048 contact is an UNKNOWN glyph. `attributes.symbol_basis` says so |
| `I048/020` ext 2 ADSB, SCN, PAI | `Entity.attributes` | `cat048 1.0.0 · parked` | On-Site ADS-B, Surveillance Cluster Network and Passive Acquisition Interface availability, each with an **`#EP` Element Populated bit**. `#EP` clear is **not** a value of "not available" — the two are kept distinct and the unpopulated case lands in `unresolved_raw`. This is the Part 1 convention CAT021's REF needed |
| `I048/020` ext 3 ACASXV, POXPR | `Entity.attributes` | `cat048 1.0.0 · parked` | ACAS Extended Version (0 Non-Extended, 1 ACAS Xa V1, 2 ACAS Xu V1, "3 – 15 Reserved for future versions" → `unresolved_raw`) and Phase Overlay transponder capability. **ACASXV is load-bearing for I048/260**: on ACAS Xu the advisory is split across /260 and /250 |
| `I048/020` ext 4 POACT, DTFXPR, DTFACT | `Entity.attributes` | `cat048 1.0.0 · parked` | Phase Overlay active, and Basic Dataflash capability and activity, each with its `#EP` bit |
| `I048/020` ext 5 IRMXPR, IRMACT | `Entity.attributes` | `cat048 1.0.0 · parked` | Interrogation/Reply Monitoring capability and activity, each with its `#EP` bit |
| `I048/020` exts 3–5 notes | `Entity.attributes` | `cat048 1.0.0 · parked` | the MOPS note is parked as provenance: these functionalities are defined by ED-73F/DO-181F [Ref. 2], and "To populate bits in these extensions, Mode S radars will have to decode/analyse the content of BDS register 1,0 (bits 15, 42 and 44)" — so these bits are the *station's* reading of a register, not the register |

### Row set — I048/030 Warning/Error Conditions and Target Classification

| CAT048 | CDM field | Status | Notes |
|---|---|---|---|
| `I048/030` code sequence | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.cat048_warning_error_codes` — an **ordered list** of `{code, text}` in wire order, duplicates preserved, never sorted and never deduplicated. Settlement 7 |
| `I048/030` raw octets | `Entity.attributes` | `cat048 1.0.0 · parked` | the octets verbatim, because egress re-emits from them |
| `I048/030` code 0 | `Entity.attributes` | `cat048 1.0.0 · parked` | accepted despite the "transmitted only if different from zero" rule; "the target classification is unknown" lands in `unavailable_fields` and the non-conformance is recorded |
| `I048/030` codes 38–63 | `Entity.attributes` | `cat048 1.0.0 · parked` | AMG range, unassigned. Code number with no text, in `unresolved_raw` |
| `I048/030` codes 64–127 | `Entity.attributes` | `cat048 1.0.0 · parked` | manufacturer range — "shall be described in the corresponding ICD", and no ICD is pinned. Code number with no text, in `unresolved_raw`, distinguished from the AMG range |
| `I048/030` codes 12, 18 | `Entity.attributes` | `cat048 1.0.0 · parked` | the source's **own** statement that its altitudes disagree or are undecodable, routed here by I048/090's Notes 1 and 2. Named in `attributes.altitude_basis` when present — settlement 5 |
| `I048/030` codes 35, 36 | `Entity.attributes` | `cat048 1.0.0 · parked` | Potential IC Conflict, and IC-Conflict-detection-possible. Parked with code 36's nested NOTE ("the use of this code should be limited to the target acquisition phase") and with the record that **the area lives in CAT034 Message Type 008**, out of scope — settlement 2 |
| `I048/030` codes 1–5, 7, 10, 19, 20, 23 | `Entity.attributes` | `cat048 1.0.0 · parked` | reflection, sidelobe, split plot, second-time-around, angel, fixed PSR plot, phantom SSR plot, birds, flock, wind turbine — the codes saying the return may not be an object. Parked and **not read into `entity_type`**, per Note 7 |
| `I048/030` code 16 | `Entity.attributes` | `cat048 1.0.0 · parked` | "Duplicated or Illegal Mode S Aircraft Address" → `attributes.identity_caveat`, because it is the source telling us the key in I048/220 may not be unique |
| `I048/030` code 37 | `Entity.attributes` | `cat048 1.0.0 · parked` | parked as a code with its text, and `unresolved_raw` records that its meaning is a pointer into the un-pinned REF |

### Row set — position: derived when a sensor position is injected, parked otherwise

| CAT048 | CDM field | Status | Notes |
|---|---|---|---|
| `I048/040` + injected site + a height | `Entity.position` | `cat048 1.0.0` | a `Position`, **derived**. Requires all three: `sensor_position` at construction, `RHO`/`THETA` on the wire, and a height from I048/110 or I048/090. Settlement 3 |
| `I048/040` + injected site + a height | `Position.lat` / `Position.lon` | `cat048 1.0.0` | the geodesic direct solution from the site, distance `sqrt(RHO² − Δh²)`, bearing `THETA` on WGS-84. Asserted to invert back to `RHO` and `THETA` within the item's own LSBs — 1/256 NM and 360/2¹⁶ ° |
| no injected site | `Entity.position` | `cat048 1.0.0` | `None`, and the polar values parked. `attributes.position_basis` says no site was injected — the first draft's behaviour, retained as the default rather than as the rule |
| injected site, **no usable height** | `Entity.position` | `cat048 1.0.0` | `None`, with the missing height named in the basis. **The record is not refused** — it is translatable, and a `Δh = 0` assumption misplaces a target at FL350 overhead by 10.7 km. Settlement 3 |
| *(derived)* | `Position.position_source` | `cat048 1.0.0` | `ESTIMATED`. **`PositionSource` has no member for a sensor measurement** — `GNSS`, `INERTIAL`, `MANUAL`, `ESTIMATED` — and `ESTIMATED` is the only one that is not an outright false statement about a computed product of a measurement, an injected site and possibly a pressure altitude. It also answers the enum's own purpose correctly: a radar fix is not `GNSS` and survives jamming. `attributes.position_source_basis` records it; the missing member is a 1.1.0 candidate, not a schema change here |
| *(none)* | `Position.alt_m` | `cat048 1.0.0` | `None` even when a `Position` exists. I048/110 is **mean-sea-level** referenced and `alt_m` is metres above the WGS-84 ellipsoid; the geoid separation needs a model nothing here carries. The height **difference** used for the slant correction is a different quantity, and the geoid largely cancels across a sensor-to-target baseline |
| *(none)* | `Position.accuracy_m` | `cat048 1.0.0` | `None`. I048/210's per-axis σ are "within the local grid system", collapsing them into one horizontal figure is a modelling choice, and the derivation adds unbounded error of its own. **Gap 17** |
| *(none)* | `Event.geometry` | `cat048 1.0.0` | `None`. The position lives on the `Entity`, as for every other point-target adapter here; `Event.geometry` is for footprints |
| `I048/040` RHO, THETA | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.cat048_measured_position` — raw integers, LSBs (1/256 NM and 360/2¹⁶ °), decoded NM and degrees, the azimuth reference ("local geographical north", §4.3.1) and the SAC/SIC the angles are measured from. **Carried losslessly in both branches**, because egress re-emits from these and a derived `Position` is a one-way view |
| `I048/040` RHO at maximum with `ERR` set | `Entity.attributes` | `cat048 1.0.0 · parked` | a **floor, not a range**: §5.2.4 NOTE 4 recommends all-ones when the REF's ERR item holds the value. Recorded as at-or-beyond-maximum, the AIS 102.2 kt discipline — and **no `Position` is derived from a floor**, because a bound is not a measurement |
| `I048/040` absent with TYP ≠ 0 | `Entity.attributes` | `cat048 1.0.0 · parked` | non-conformance recorded against "This item shall be sent when there is a detection", **not a refusal** — the record is otherwise complete and suppressing it would be filtering |
| `I048/040` Note 1 | `Entity.attributes` | `cat048 1.0.0 · parked` | "In case of no detection, the extrapolated position expressed in slant polar co-ordinates may be sent" — so a TYP = `000` record's polar values are an **extrapolation**, not a measurement. Recorded in the basis, and a `Position` derived from one says so |
| `I048/040` Note 3 | `Entity.attributes` | `cat048 1.0.0 · parked` | "In case of combined detection by a PSR and an SSR, then the SSR position is sent" — parked as provenance, since it says which sensor the numbers came from and nothing else in the record does |
| `I048/042` X, Y | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.cat048_calculated_position` — raw two's-complement integers, LSB 1/128 NM, origin "coincides with the radar head position". **Still never a `Position`**, even with a site injected: settlement 3 |
| `I048/042` + `I048/170` TCC | `Entity.attributes` | `cat048 1.0.0 · parked` | **which transform produced I048/042 is signalled in another item**, and the projection is named only as "e.g. a stereographical projection". Both parked, the pair recorded, the cross-item join declined — CAT021 ambiguity 4's rule, and the reason I048/040 is the single source of derived geometry |
| *(measured)* | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.position_basis` — which branch was taken; and when derived, the injected site value, the height item that supplied `Δh`, the WGS-84 earth model, the slant treatment, and that **the arithmetic is this adapter's and not the specification's**. **Gap 24** |

### Row set — altitude and height

| CAT048 | CDM field | Status | Notes |
|---|---|---|---|
| `I048/090` Flight Level | `Entity.attributes` | `cat048 1.0.0 · parked` | **gap 9.** `attributes.flight_level` in **FL, the source's own unit**, LSB ¼ FL, "in two's complement form" per Edition 1.32's clarification. A pressure altitude is not `Position.alt_m`'s metres-above-ellipsoid, and there is no `Position` anyway |
| `I048/090` V, G | `Entity.attributes` | `cat048 1.0.0 · parked` | code-validated and garbled flags. `G` set means "an error correction has been attempted" for Mode S (Note 4) — a statement about the *station's* processing |
| `I048/090` Note 3 | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.flight_level_range_basis` — the item defers its range to ICAO Annex 10, which §2.2 does not list and nothing here pins, so the enforced range is the field's own −2048.00 .. +2047.75 FL |
| `I048/100` Mode-C Gray bits | `Entity.attributes` | `cat048 1.0.0 · parked` | **not decoded.** The item is sent "only … when a not validated or undecodable Mode C code has been received", so decoding it would manufacture the value it exists to say is unavailable. Twelve reply bits parked verbatim; `unresolved_raw` records the deliberate decline. No Gray table appears in this document |
| `I048/100` QXi pulse quality | `Entity.attributes` | `cat048 1.0.0 · parked` | twelve per-pulse confidence bits. Note the Mode S case: "all pulse quality bits will be set to high (zero)" when the item is sent for an undecodable Mode S altitude reply — so all-zero does **not** mean twelve good pulses |
| `I048/100` D1/Q + `I048/230` ARC | `Entity.attributes` | `cat048 1.0.0 · parked` | "For Mode S, D1 is also designated as Q, and is used to denote either 25ft or 100ft reporting" — and the capability is in a *different item*. Both parked, the dependency recorded, the join declined |
| `I048/110` 3D-Height | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.height_3d_ft` in feet, LSB 25 ft, two's complement, **mean sea level zero reference**. A third datum alongside HAE and the pressure datum — sharpens **gap 9**'s datum note rather than opening a new gap |
| `I048/090` + `I048/110` both present | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.cat048_altitude_disagreement` — both values in both units with both datums, and an explicit note that they are **not the same quantity**. Recorded, never adjudicated. Settlement 5 |
| *(none)* | `Position.alt_m` | `cat048 1.0.0` | never written, even when settlement 3 derives a `Position`. None of the three items is metres-above-ellipsoid: I048/090 is a pressure altitude, I048/110 is mean-sea-level referenced and needs a geoid model, and I048/100 is deliberately undecoded. **A height difference and an absolute height are different claims** — the first is what the slant correction consumes, the second is what `alt_m` would assert |

### Row set — the Mode codes and their confidence indicators

| CAT048 | CDM field | Status | Notes |
|---|---|---|---|
| `I048/070` Mode-3/A code | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.mode_3a_code` in octal, the source's own representation. **Not a `SourceId`** — a squawk is assigned per flight, reassigned, and duplicated across regions |
| `I048/070` V, G, L | `Entity.attributes` | `cat048 1.0.0 · parked` | **`L` means something different here than in I048/050 and /055.** In /070 it is "Mode-3/A code **not extracted during the last scan**"; in /050 and /055 it is "Smoothed … code as provided by a local tracker". Same letter, same relative position, different claim — parked per item with the per-item wording, never through one shared decoder |
| `I048/070` Note 2 | `Entity.attributes` | `cat048 1.0.0 · parked` | "For Mode S, bit 16 is normally set to zero, but can exceptionally be set to one to indicate a non-validated Mode-3/A code (e.g. alert condition detected, but new Mode-3/A code not successfully extracted)" — parked, and it is why a `V` set on a Mode S record is not the same event as on a Mode A/C one |
| `I048/070` encoding rule | `Entity.attributes` | `cat048 1.0.0 · parked` | "For Mode S, once a Mode-3/A code is seen, that code shall be sent every scan" — so a repeated code is not fresh extraction. Recorded, because a consumer counting code changes would otherwise read continuity as re-confirmation |
| `I048/050` Mode-2 code | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.mode_2_code` in octal, with V, G, L. A military interrogation mode; the 1.32 NOTE routing an alternative value to `I048/REF/GEN48/ALTM2` is parked as an un-pinned pointer |
| `I048/055` Mode-1 code | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.mode_1_code`, 5 bits, with V, G, L. Its NOTE ties V, G, L, A4, A2, A1, B2, B1 to "subfield #5 of data item 'MD5 – Mode 5 Reports'" in the REF — recorded, unreadable here |
| `I048/060`, `I048/065`, `I048/080` | `Entity.attributes` | `cat048 1.0.0 · parked` | per-pulse confidence for Mode-2, Mode-1 and Mode-3/A. Each is sent "only when at least one pulse is of low quality", so **the item's presence is itself the signal** and its absence is not a claim of perfect quality. Parked bit by bit; none reaches `Entity.confidence` |
| `I048/240` Aircraft Identification | `Entity.attributes` | `cat048 1.0.0 · parked` | **gap 1**, the EIGHTH private key for one concept — see the corrected tally there. Eight characters at 6 bits each, decoded with the table `adsb.py` uses, raw 48 bits parked. `attributes.aircraft_identification_basis` records that **this document states no character table** — §5.2.25 Note 1 points to BDS Register 2,0, whose coding is in [Ref. 2] ED-73F/DO-181F, which nothing here pins |
| `I048/240` semantics | `Entity.attributes` | `cat048 1.0.0 · parked` | "aircraft identification when flight plan is available **or the registration marking when no flight plan is available**" — two different kinds of string in one field, with nothing saying which. Recorded rather than guessed |

### Row set — time

| CAT048 | CDM field | Status | Notes |
|---|---|---|---|
| `I048/140` Time of Day | `Event.observed_at` | `cat048 1.0.0` | 24 bits, 1/128 s since last midnight UTC. The date comes from the injected clock, nearest of (previous day, receipt date, next day). Settlement 4 |
| `I048/140` raw integer | `Entity.attributes` | `cat048 1.0.0 · parked` | parked, and **egress re-emits from it** rather than recomputing from `observed_at` — 1/128 s is 7.8125 ms and `times.render` emits three decimals |
| `I048/140` > 86 400 s | *(refusal)* | `cat048 1.0.0` | a `CodecError` quoting the item, the raw 24-bit integer and the decoded seconds. Never a modulo. The bound is **stated** by §5.2.17, not inferred |
| `I048/140` = 86 400.000 s exactly | `Event.observed_at` | `cat048 1.0.0` | **accepted**, on the range's own `<=`, and resolved as midnight of the following day with the reading recorded. §5.2.17's range and its Note 1 disagree about whether the value can occur — ambiguity 1 |
| `I048/140` absent | `Event.observed_at` | `cat048 1.0.0` | the injected clock, with `payload.observed_at_basis` recording that the record carried no time item and that "failure of all sources of time-stamping" is a case the encoding rule **permits**. A stated absence → `unavailable_fields`, not `unresolved_raw` |
| *(the injected clock)* | `Event.received_at` | `cat048 1.0.0` | when WE took delivery. Never the radar's time of day, which is a different party and a different instant |
| *(derived)* | `Entity.valid_from` | `cat048 1.0.0` | the resolved `observed_at`. The state this record describes begins when the radar saw it |
| *(none)* | `Entity.valid_to` | `cat048 1.0.0` | `None`, **on every record including an End of Track Message** — settlement 8. CAT048 has no staleness field and no scan period (the scan period is in CAT034), and `TRE` ends a station's track record rather than the entity. **Gap 26** |
| §4.2.1 | `Entity.attributes` | `cat048 1.0.0 · parked` | "The target time stamp shall be consistent with the reported plot position" — parked as the reason gap 13 does not bite here: one time, one position, one instant, unlike CAT021's seven items |

### Row set — track number, track status, and the end of a track

| CAT048 | CDM field | Status | Notes |
|---|---|---|---|
| `I048/161` Track Number | `Entity.attributes` | `cat048 1.0.0 · parked` | **a carried claim, never an identity key.** `attributes.track_number` on every record, with the SAC/SIC it is scoped to. Reversed from this row set's first draft, which made it a `SourceId` at step 2 of the identity chain — settlement 9 |
| `I048/161` Track Number | `Entity.attributes` | `cat048 1.0.0 · parked` | it cannot ride on a `Track` either: `Track` has `track_id`, `entity_id`, `samples` and `track_quality` and **no extension bag**, which is the existing `Track.attributes` 1.1.0 candidate. So the station's own track number rides on the `Entity` even when the object it describes is a history |
| `I048/170` CNF | `Entity.attributes` | `cat048 1.0.0 · parked` | Confirmed vs Tentative Track. Parked, and **not read into `Entity.confidence`** — a tracker's promotion state is not a probability |
| `I048/170` RAD | `Entity.attributes` | `cat048 1.0.0 · parked` | which sensor maintains the track: Combined, PSR, SSR/Mode S, or `11` **Invalid** → `unresolved_raw`. Its note is parked too: "RAD can change after a number of non-matching with TYP in item 020", so RAD and TYP may legitimately disagree within one record |
| `I048/170` DOU | `Entity.attributes` | `cat048 1.0.0 · parked` | "Low confidence in plot to track association" — a **data-association** verdict, not a confidence in the object. Parked; `Entity.confidence` stays `None` |
| `I048/170` MAH | `Entity.attributes` | `cat048 1.0.0 · parked` | horizontal manoeuvre sensed. Parked; it is a tracker judgement, not a kinematic quantity |
| `I048/170` CDM | `Entity.attributes` | `cat048 1.0.0 · parked` | Climbing / Descending Mode: Maintaining, Climbing, Descending, `11` Unknown → `unresolved_raw`. **A 2-bit category, not a rate** — it never reaches `Kinematics.climb_mps`, which is metres per second. CAT048 states no vertical rate anywhere |
| `I048/170` TRE | `Event.event_type` | `cat048 1.0.0` | End_of_Track → `STATUS_CHANGE`. **The only terminal declaration any source in this document makes, and the CDM cannot hold it**: `valid_to` stays `None`, because `TRE` ends "this track" — a "track record within a particular track file" per I048/161 — and not the airframe the `entity_id` names. Carried at `attributes.track_end`. Settlement 8, **gap 26** |
| `I048/170` GHO | `Entity.attributes` | `cat048 1.0.0 · parked` | "Ghost target track". Parked, and the object is still emitted in full — the source's verdict is carried, and suppressing or downgrading the record would be the filtering the `Adapter` contract refuses. CAT021's `RCF` row, one format later |
| `I048/170` SUP | `Entity.attributes` | `cat048 1.0.0 · parked` | track maintained with information from a neighbouring node on the cluster or network. A **station-topology** fact; it says another sensor contributed and names neither it nor how, so nothing about it is actionable here |
| `I048/170` TCC | `Entity.attributes` | `cat048 1.0.0 · parked` | which coordinate transformation produced I048/042 — radar plane, or slant-range-corrected and projected. Load-bearing for that item and parked with it |
| `I048/170` first extent FX = 1 | *(refusal)* | `cat048 1.0.0` | documented as "Extension into second extent", and §5.2.19 defines no second extent. Nothing to decode and no length to guess |

### Row set — velocity and track quality

| CAT048 | CDM field | Status | Notes |
|---|---|---|---|
| `I048/200` CALCULATED GROUNDSPEED | `Kinematics.speed_mps` | `cat048 1.0.0` | LSB 2⁻¹⁴ NM/s × 1852 m = 0.113 037 109 375 m/s, **exact in float64**. A ground speed in the CDM's own sense, and the one kinematic quantity CAT048 states cleanly |
| `I048/200` angular component | `Kinematics.course_deg` | `cat048 1.0.0` | Mapped on §5.2.20's **Definition** — "Calculated track velocity expressed in polar co-ordinates" — because the angular component of a velocity vector is a course by construction, and on its **Note**, which pins the datum: "The calculated heading is related to the geographical North at the aircraft position". LSB 360/2¹⁶ °. **Gap 7's magnetic-versus-true hazard is absent BY THE TEXT here**, not by inference: geographical north is stated, so unlike an ADS-B heading there is no datum living in another frame. The field *label* reads "CALCULATED HEADING" and does not govern — ambiguity 3 |
| `I048/200` raw integers | `Entity.attributes` | `cat048 1.0.0 · parked` | parked; egress re-emits from them rather than from the converted floats |
| *(none)* | `Kinematics.climb_mps` | `cat048 1.0.0` | `None`, always. CAT048 states no vertical rate — I048/170 `CDM` is a four-value category and I048/120 is a line-of-sight scalar |
| `I048/120` primary CAL, RDS | `Entity.attributes` | `cat048 1.0.0 · parked` | which secondary subfield is present. "When used, only one … shall be present" — both set is non-conforming, parsed, parked, recorded, **not refused**. Ambiguity 5 |
| `I048/120` primary bits 6/2 set | *(refusal)* | `cat048 1.0.0` | presence bits for "Subfields #3/7: Spare", which do not exist. CAT021's Not-Used-FRN reasoning |
| `I048/120` #1 CAL, D | `Entity.attributes` | `cat048 1.0.0 · parked` | Calculated Doppler Speed, 10 bits two's complement, LSB 1 m/s, plus the doubtful bit. **Parks — reaches no `Kinematics` field.** A line-of-sight component is not a ground speed, and the item's own note makes the sign "implementation dependent". Settlement 6, **gap 25** |
| `I048/120` #2 REP, DOP, AMB, FRQ | `Entity.attributes` | `cat048 1.0.0 · parked` | Raw Doppler Speed: repetition factor, Doppler speed and ambiguity range at 1 m/s, transmitter frequency at 1 MHz. `AMB` is a Doppler ambiguity interval and `FRQ` is a radar parameter — **neither is a property of the target at all** |
| `I048/210` σ(X), σ(Y), σ(V), σ(H) | `Entity.attributes` | `cat048 1.0.0 · parked` | "a vector of standard deviations" in the **local grid system** — 1/128 NM, 1/128 NM, 2⁻¹⁴ NM/s, 360/2¹² °. Parked in the source's units. Local-grid axes are the same unresolvable frame as I048/042's, so σ(X) and σ(Y) cannot become `Position.accuracy_m` even if a `Position` existed. **Gap 17** and **gap 24** |
| *(none)* | `Position.accuracy_m` | `cat048 1.0.0` | never written, even when a `Position` is derived. A per-axis standard deviation "within the local grid system" is not a 1-sigma horizontal metre figure, collapsing σ(X) and σ(Y) into one is a modelling choice, and the derivation in settlement 3 adds error that nothing in the record bounds |
| *(none)* | `Entity.confidence` / `Track.track_quality` | `cat048 1.0.0` | both `None`. Every quality statement CAT048 carries is a pulse-level flag, a per-axis standard deviation or an association verdict; none is a 0..1 assessment. Settlement 9 |

### Row set — I048/130 Radar Plot Characteristics

A compound item of seven one-octet subfields, all parked. It is the radar's own account of the
*quality of the detection*, which is a different thing from the quality of the track.

| CAT048 | CDM field | Status | Notes |
|---|---|---|---|
| `I048/130` #1 SRL | `Entity.attributes` | `cat048 1.0.0 · parked` | SSR plot runlength, LSB 360/2¹³ ° ≈ 0.044 °, unsigned; its note gives the span, "from 0 to 11.21 dg" |
| `I048/130` #2 SRR | `Entity.attributes` | `cat048 1.0.0 · parked` | number of received replies for (M)SSR, LSB 1 |
| `I048/130` #3 SAM | `Entity.attributes` | `cat048 1.0.0 · parked` | amplitude of the (M)SSR reply, LSB 1 dBm, **two's complement per its own note**. A link measurement, never a range or a confidence — `adsb.py`'s message-amplitude rule |
| `I048/130` #4 PRL | `Entity.attributes` | `cat048 1.0.0 · parked` | primary plot runlength, LSB 360/2¹³ °, unsigned, same 11.21 ° span |
| `I048/130` #5 PAM | `Entity.attributes` | `cat048 1.0.0 · parked` | amplitude of the primary plot, LSB 1 dBm, two's complement |
| `I048/130` #6 RPD | `Entity.attributes` | `cat048 1.0.0 · parked` | PSR−SSR range difference, LSB 1/256 NM, two's complement, span ±0.5 NM. **"Sending the maximum value means that the difference in range is equal or greater than the maximum value"** — a floor, recorded as one |
| `I048/130` #7 APD | `Entity.attributes` | `cat048 1.0.0 · parked` | PSR−SSR azimuth difference, LSB 360/2¹⁴ °, two's complement, span "+/-360/2⁷ = +/-2.8125 dg". Its maximum is a floor on the same terms — and its note says "the difference in **range**", which is a copy-paste from #6. Ambiguity 4 |
| `I048/130` recommendation | `Entity.attributes` | `cat048 1.0.0 · parked` | "For a combined target report, subfields RPD and APD of primary subfield should be present" — a *should*, so absence is recorded and never a refusal |
| `I048/130` second primary octet | *(refusal)* | `cat048 1.0.0` | the primary subfield is `FX`-extensible but only seven subfields are defined |

### Row set — I048/230, I048/250, I048/260

| CAT048 | CDM field | Status | Notes |
|---|---|---|---|
| `I048/230` COM | `Entity.attributes` | `cat048 1.0.0 · parked` | transponder communications capability, 0–4 defined and "5 to 7 Not assigned" → `unresolved_raw`. Its encoding rule adds "If the datalink capability has not been extracted yet, bits 16/14 shall be set to zero" — so **`0` is ambiguous between "surveillance only" and "not yet extracted"**, and both readings are recorded |
| `I048/230` STAT | `Entity.attributes` | `cat048 1.0.0 · parked` | flight status: the alert / SPI / airborne-or-on-ground vocabulary, 0–5 plus "6 Not assigned" → `unresolved_raw` and "7 Unknown" → `unavailable_fields`. **Alert values do not raise severity** — settlement 9. The airborne/on-ground half is CAT048's only ground indication and it is parked, not read into `entity_type` |
| `I048/230` SI | `Entity.attributes` | `cat048 1.0.0 · parked` | SI/II transponder capability. Added in Edition 1.16, so a record from an older encoder carries a spare bit here instead |
| `I048/230` MSSC, ARC, AIC | `Entity.attributes` | `cat048 1.0.0 · parked` | Mode-S specific service capability, altitude reporting resolution (100 ft or 25 ft), aircraft identification capability. `ARC` is what I048/100's D1/Q bit needs and the join is declined |
| `I048/230` B1A, B1B | `Entity.attributes` | `cat048 1.0.0 · parked` | "BDS 1,0 bit 16" and "BDS 1,0 bits 37/40" — five bits lifted out of a register whose other 51 bits are not here. Parked as the register fragments they are, never as a decoded capability |
| `I048/250` REP + registers | `Event.payload` | `cat048 1.0.0 · parked` | each register as 56 bits of hex plus its `BDS1`/`BDS2` address and extraction mode. **Parked, not exempted** — settlement 10 |
| `I048/250` BDS1 = BDS2 = 0 | `Event.payload` | `cat048 1.0.0 · parked` | "Comm-B broadcast, register unidentified" — **not register 0,0**. Note 3 |
| `I048/260` ACASRA | `Event.payload` | `cat048 1.0.0 · parked` | 56 bits of hex. **Not decoded**: the only cited authority is "ICAO Draft SARPs for ACAS", a draft, unnamed by edition and absent from §2.2. `unresolved_raw` records the decline |
| `I048/260` presence | `Entity.attributes` | `cat048 1.0.0 · parked` | **The item's two sentences assert different things and the row carries both.** The Definition says "Currently active Resolution Advisory (RA), if any, generated by the ACAS associated with the transponder transmitting the report and threat identity data"; the Encoding Rule says "This item shall be present when a Resolution Advisory (RA) has been **generated in the last scan**". An RA generated last scan need not still be active, so **presence asserts less than the Definition's word "currently"** — and since the 56 bits are undecodable here, this adapter cannot tell which of the two it is holding. Parked at `attributes.acas_ra_active` with both sentences quoted, and severity stays a **consumer's act**. Note the divergence from CAT021 explicitly: that row declines on the grounds that "grading an equipment status as an emergency would be the translator judging", which is a judgement argument; **this row declines on a weaker and more specific ground — the text does not establish that an advisory is active at all** |
| `I048/260` + `I048/250` on ACAS Xu | `Event.payload` | `cat048 1.0.0 · parked` | "the Resolution Advisory consists of two parts (BDS30 and BDS31). BDS31 will be transmitted using item 250" — the advisory is **split across two items** and either half alone is incomplete. Recorded, and I048/020 ext 3 `ACASXV` is what says whether this applies |

### Row set — SP and RE

| CAT048 | CDM field | Status | Notes |
|---|---|---|---|
| `SP` (FRN 27) | `Entity.attributes` | `cat048 1.0.0 · parked` | Special Purpose Field, opaque. Parked verbatim as hex and **never written to on egress** — its contents are defined by bilateral agreement between one sender and one receiver, so a byte invented here is a byte some deployment already means something by. No §5.2 description exists for it in this document |
| `RE` (FRN 28) | `Entity.attributes` | `cat048 1.0.0 · parked` | Reserved Expansion Field. Parked verbatim as hex, restored byte-for-byte, **never decoded and never written to**. Settlement 1. The explicit length octet counts itself, per Part 1 |
| `RE` present | `Entity.attributes` | `cat048 1.0.0 · parked` | `attributes.reserved_expansion_basis` — that the RE field arrived, that its layout is in an appendix this repository does not pin, and which of the four losses in settlement 1 the record is exposed to (`ERR` set? `FOE/FRI` = `00`? code 37 present?) |

### Row set — egress, CDM back to a CAT048 data block

**Egress is byte-exact for a block that came from CAT048, and a refusal for anything else.** That
asymmetry is a real departure from CAT021, which can build a block from a `Track`, and it follows
directly from settlement 3.

| CDM | CAT048 | Status | Notes |
|---|---|---|---|
| `Entity.attributes` (the park) | the whole record | `cat048 1.0.0 · egress` | every item re-encoded from the **raw wire integers** parked on ingest, in FRN order, under the FSPEC as read. A float that had been through a conversion could not prove it had not moved a contact |
| `Entity.attributes` | `LEN` | `cat048 1.0.0 · egress` | recomputed from the octets, never copied |
| `Entity.source_ids[].system` | *(nothing)* | `cat048 1.0.0 · egress` | read to confirm the object came from CAT048; never written into a record |
| `Entity.attributes` `track_end` | `I048/170` TRE | `cat048 1.0.0 · egress` | re-emitted from the park. **Never inferred from `Entity.valid_to`**, which CAT048 never sets — an entity whose interval was closed by something else must not acquire a track-end bit |
| a `Track` | *(refusal)* | `cat048 1.0.0 · egress` | **A CDM `Track` cannot become a CAT048 block, and settlement 3 narrows the reason rather than removing it.** With a `sensor_position` injected the geometry *is* invertible — geodetic to `RHO`/`THETA` is the same arithmetic run backwards — so the refusal no longer rests on the transform. It rests on what the CDM does not carry: **I048/010 "shall be present in every ASTERIX record"** and there is no SAC/SIC anywhere in a `Track`; there is no FSPEC, no I048/020 `TYP`, and no height item, so the inverse slant correction has no `Δh` either. The refusal names each missing input |
| an `Entity` that never came from CAT048 | *(refusal)* | `cat048 1.0.0 · egress` | same list. Note what is **not** on it any more: the site position, which a caller may now supply. Inventing a SAC/SIC would be a station identity, which is a different and larger act than accepting a site coordinate — the first names a system, the second locates one |
| `Entity.attributes` SP, RE | `SP`, `RE` | `cat048 1.0.0 · egress` | restored verbatim, and **never created** for an object that did not arrive with one |

#### What egress is NOT lossy for

A block that came in goes back out identically — FSPEC octets, spare bits, item order, `RHO` and
`THETA` integers, the I048/030 code sequence in wire order, the SP and RE octets, and the raw time
of day. Everything derived — `observed_at`, `entity_type`, the `Kinematics` floats and **the
`Position` settlement 3 computes** — is a one-way view and is **not** the source of any emitted
byte. That last one matters more here than in any previous adapter: re-encoding `RHO` from a
derived latitude would run the imported arithmetic in both directions and hide any error in it,
whereas re-emitting the parked integers means a conversion defect can only ever affect the CDM
view and never the wire.

### What the adapter fills that CAT048 does not state

| CDM field | Filled with | Why the format cannot say |
|---|---|---|
| `Event.received_at` | the injected clock | The radar states when it saw the target, never when we took delivery |
| the date half of `observed_at` | the injected clock | I048/140 is a time of day. Settlement 4 |
| `Entity.affiliation` | `UNKNOWN` | An IFF result is not an affiliation. Settlement 9 |
| `Entity.symbol` | derived from the affiliation | CAT048 carries no symbology of any kind |
| `Entity.entity_type` | from I048/020 `TYP` | The format has no emitter category; `TYP` says what kind of *detection* it was, which is the closest thing to a kind of object it states |
| `Entity.source.synthetic` | the deployment's declaration | `SIM` and `TST` are payload bits and may not flip it |
| `Event.event_id` | keyed on the identity **and** `observed_at` | An address or a track number repeats on every scan, so an id keyed on it alone would collapse a whole flight into one event |
| `Entity.source_ids` at step 2 | a report-scoped derived id | A report with no aircraft address states no identity at all, and `source_ids` is required |
| `Position.lat` / `Position.lon` | the geodesic solution from an **injected** site | The format states range and bearing and never the origin. Settlement 3 — and the arithmetic is this adapter's, which is the one place in this row set where that is true |
| `Position.position_source` | `ESTIMATED` | `PositionSource` has no member for a sensor measurement |

### Where the specification is ambiguous or contradicts itself

Recorded because an adapter author will hit every one of these. Each is handled by parking or
refusing, never by guessing.

| # | Finding | Consequence for the adapter |
|---|---|---|
| 1 | **I048/140's stated range and its Note 1 disagree about one value.** §5.2.17's normative structure block prints "Acceptable Range of values: 0<= Time-of-Day<=24 hrs" — **inclusive at the top**; Note 1 says "The time of day value is reset to 0 each day at midnight", which makes 86 400 unreachable | 86 400.000 s exactly is **accepted** on the stated range's own inequality and resolved as midnight of the following day, with the reading recorded. **Note prose cannot narrow a range the normative block states.** Anything above it is a `CodecError`. Two boundary fixtures pin it: raw 11 059 200 (= 86 400.000 s) accepted, raw 11 059 201 (= 86 400 + 1/128 s) refused |
| 2 | **Two undefined names for the same message shape, or for two different ones.** I048/170, /220, /230, /240 and /250 say "End of Track Message"; I048/040 Note 1 and I048/200's encoding rule say "track cancellation message". Neither term is defined anywhere | `TRE` is the only observable trigger, so it is the one used, and `attributes.track_end_basis` records that whether I048/040 and I048/200 may appear in such a record depends on an equivalence the document never states |
| 3 | **I048/200's field label says "heading" where its Definition says velocity.** The Definition is "Calculated track velocity expressed in polar co-ordinates"; the bit diagram labels the angular component "CALCULATED HEADING" | The **Definition and the Note govern, and the label does not.** The angular component of a velocity vector is a course by construction, and the Note pins the datum — "The calculated heading is related to the geographical North at the aircraft position". So the mapping to `Kinematics.course_deg` cites §5.2.20's Definition and Note, never the label. An encoder that puts a bow heading in that field contradicts its own item's Definition: **that is the encoder's nonconformance, not a reading this row set has to accommodate.** The label is recorded so the mismatch is discoverable |
| 4 | **I048/130 subfield #7's third note is a copy-paste from subfield #6.** APD is an azimuth difference, and its note reads "Sending the maximum value means that the difference in **range** is equal or greater than the maximum value" | Read as azimuth, since the subfield carries nothing else, and the wording is recorded. The at-or-beyond-maximum flag is set on APD's own terms |
| 5 | **I048/120's encoding rule forbids what its structure permits.** "When used, only one secondary subfield shall be present", yet `CAL` and `RDS` are independent presence bits | Both parsed, both parked, the non-conformance recorded, the record **not** refused: both subfields are fixed-length so nothing desynchronises. Refusing a decodable target report over a redundancy rule would be filtering |
| 6 | **I048/200's groundspeed field is wider than its stated maximum.** The field is labelled "CALCULATED GROUNDSPEED (max. 2 NM/s)" and the LSB is 2⁻¹⁴ NM/s over 16 bits, which reaches 3.999 938 96 NM/s | The **field's** range is enforced, and a value above 2 NM/s is carried with an over-stated-maximum flag rather than refused: 2 NM/s is 7 200 kt, so the label is a design envelope and not an encoding limit, and refusing would discard a decodable value |
| 7 | **The UAP's length notation is undefined for three of its own rows.** The legend explains a stand-alone figure and `1+`. FRN 7 reads `1+1+`, FRN 10 reads `1+8*n`, and FRNs 27 and 28 read `1+1+` | Lengths are taken from each item's §5.2 structure, and from Part 1 for SP and RE, which have no §5.2 structure at all. The notation is recorded as uninterpretable rather than reverse-engineered |
| 8 | **The UAP and §5.2 disagree about seven item names**, most consequentially FRN 10: Table 2 says "Mode S MB Data" and §5.2.25's heading says "BDS Register Data". The change record shows the rename happened in Edition 1.29 — three editions before this one | §5.2's headings are authoritative and Table 2's names are recorded beside them, because the FRN is what the FSPEC addresses and the name is what a reader searches for. The other six are Time-of-Day, Slant Polar, Polar Representation, Warning/Error Conditions/Target Classification, Mode-C Code and Confidence Indicator, and Height Measured by 3D Radar |
| 9 | **I048/230 `COM` = 0 means two things.** "No communications capability (surveillance only)", and — per the item's own encoding rule — "If the datalink capability has not been extracted yet, bits 16/14 shall be set to zero" | Both readings recorded, neither chosen. A transponder with no datalink and a transponder not yet interrogated are different facts, and the field cannot distinguish them |
| 10 | **I048/030's Note 3 is a tombstone.** It reads, in full, "Note outdated and deleted." The deletion left the numbering intact rather than renumbering Notes 4 to 7 | Nothing to implement, and it is recorded because a reader following a "see Note 3" reference from an older edition lands on nothing. Notes 4 and 5 are the ones codes 15, 33 and 34 point at |
| 11 | **§5.1's heading outlived its table.** Edition 1.32 removed the "Standard Data Items" table; the Table of Contents still lists "5.1 Standard Data Items" at page 13, and §5.1 is one sentence of prose | The **UAP is the sole item roster** and this coverage table is keyed on it. Recorded because a reader looking for the roster at §5.1 finds a heading and no list |
| 12 | **This repository states two different dates for one Part 1 edition.** CAT048 §2.2 says "Edition 3.1, Released Issue, 28 October 2021"; FORMAT_COVERAGE.md's CAT021 pin row says "Edition 3.1, November 2021" | The **edition** is what the dependency rests on and the editions agree, so the existing basis is cited. The date discrepancy is recorded and neither row is edited on a guess, because no copy of Part 1 has ever been retrieved here |
| 13 | **Which Note Edition 1.32 added to I048/090 is not determinable from the pinned copy.** The change record says one was added to §5.2.12; the section carries five | All five are quoted verbatim in settlement 5 and in the pin. Note 3 is identified as the *likely* insertion and labelled an inference, since establishing it needs Edition 1.31 |
| 14 | **This repository will refuse and accept the same wire value in two adapters, and the bases differ.** CAT048 accepts exactly 86 400.000 s (ambiguity 1). `asterix_cat021.py` refuses it: the guard is `if seconds >= SECONDS_PER_DAY`, so 86 400.000 s raises, and its stated reason is inference from reset prose — "the counter resets at every midnight, so it cannot reach 86400" — with **no acceptable-range line cited** | **Recorded as a cross-adapter finding, not harmonised.** The two rest on *different recorded bases*: CAT048 §5.2.17 prints an inclusive range in its normative block, and the CAT021 row set quotes only "is reset to zero at every midnight". Whether the CAT021 *document* also prints a range is **not establishable here** — no CAT021 copy is pinned with an extracted text layer, only hashes in prose. So one of two things is true and this repository cannot say which: the documents genuinely differ, or one was read more closely than the other. Harmonising the boundary silently would erase the question; the exit condition is pinning CAT021's text the way CAT048's is now pinned |

### Deliberately out of scope, and why — each named individually

An unimplemented thing is a decision. "Not supported" without a reason is indistinguishable from
"nobody thought about it".

| Out | Decision |
|---|---|
| **The Reserved Expansion Field's contents** | Settlement 1. **Not blocked on anything but the act of pinning.** The layout is in Appendix A (SPEC-0149-4A), listed at Edition 1.13 of 4 December 2024 with Edition 1.12 contemporaneous with the pinned core; it is a public download and no copy was retrieved here. The octets are parked verbatim so no *data* is lost; four *interpretations* are, the sharpest being that **a Mode 4 interrogation that happened is indistinguishable from one that did not** — the M4E note forces `FOE/FRI` to `00`, which reads "No Mode 4 interrogation". **Reopen condition: acquire and pin Appendix A** — hash it, record which core edition it is paired with and why (1.12 is contemporaneous, 1.13 is current), and write the subfield row sets. Unlike GMTIF's §L.4 blocker there is nothing to wait for |
| **Category 034 Monoradar Service Messages** | Settlement 2. Deferred, not rejected, and the loss is stated: antenna rotation timing, the IC-Conflict area for codes 35 and 36, and station status. The structural reason is that CAT034 is only useful as context accumulated across messages, which is stream state |
| **Deriving a geodetic position with no injected site** | Settlement 3, and it is a **default rather than a decline**: with a `sensor_position` injected the geometry IS derived. What stays out of scope is the adapter *obtaining* the site itself — inferring it from the payload, or resolving it through a SAC/SIC lookup table it owns. Both are "a station configuration it discovered from the data", which is the act `asterix_cat021.py` refuses by name; a constructor argument is not that act |
| **Deriving a geodetic position from I048/042** | Settlement 3, and this one is a genuine decline even with a site. Which of two transforms produced it is signalled by `TCC` in I048/170, and the projection is named only as "e.g. a stereographical projection" — so a derivation would need a cross-item join *and* an unnamed projection. I048/040 is the single source of derived geometry, so the arithmetic has one owner |
| **Every other ASTERIX category** — 001, 002, 004, 008, 010, 011, 019, 020, 023, 034, 062, 063, 065, 240, 247 … | Each has its own UAP and item catalogue, and a block decoded against the wrong one yields a plausible wrong aircraft rather than an error. **CAT034 is the highest-value neighbour here**, for the reason CAT023 was for CAT021: it is the station's own status. **CAT062** remains where a fused air picture actually lives. A category is an adapter |
| **Interpreting `FOE/FRI`, `MI` or an authenticated Mode 5 indication as an affiliation** | Settlement 9. The highest-value omission and structural rather than effort: an IFF result belongs to an IFF authority, over-claiming `FRIENDLY` is the dangerous direction, and the M4E note makes `00` ambiguous anyway. The bits are parked in full and `affiliation_basis` records the decline on every object |
| **Decoding I048/250's register contents** | Settlement 10. A separate register set with its own document, [Ref. 2], unpinned. `adsb.py` already names a Mode S BDS adapter as a different adapter |
| **Decoding I048/260's advisory bits** | Settlement 10. The only cited authority is "ICAO Draft SARPs for ACAS" — a draft, unnamed by edition, not in §2.2, with no field breakdown anywhere in the document. Decoding would mean adopting a standard this repository cannot identify |
| **Gray-decoding I048/100** | Settlement 5. The item is sent *because* the Mode-C code was not validated or not decodable, so decoding it would manufacture the value it exists to deny. No Gray table is given here either |
| **Reading I048/030's classification codes into `entity_type`** | Settlement 7. Note 7: "The use of this Data Item is implementation specific and shall be described in the ICD of the system generating the Category 048 target reports." A per-deployment convention is not a canonical classification |
| **Suppressing a ghost, a phantom, an angel or a bird** | Every one of these is a code the source sets, and the record is translated in full with the code parked. The `Adapter` contract refuses filtering, and CAT021's `range_check_failed_still_translated` fixture is the precedent: a translator that starts suppressing is making operational decisions invisibly |
| **Correlating records across data blocks, or with any other feed** | Settlement 11, for the seventh time. Records within one block are translated because they arrived in one payload; joining across payloads means holding a cache, which is fusion done where nothing audits it |
| **Building a `Track` from records sharing a track number or an address** | Settlement 11. Several records in one block are several target reports, and grouping the ones that agree is a correlation heuristic made invisibly inside a translator |
| **Associating a plot with a track in the same block** | Settlement 11, and CAT048-specific: one UAP serves both, a track "is a superset of a plot", and the association is what the *radar* does and reports its confidence in through `DOU` |
| **Writing into the SP or RE fields on egress** | SP is bilateral by definition. RE's layout is unpinned, so a byte written there would be a guess about a structure nobody here has read. Both are read, parked and restored verbatim |
| **ASTERIX transport — UDP multicast, stream framing, pcap** | A data block is one payload; how it arrived is the caller's. The AIS fragment buffer, the ADS-B frame buffer, Legion's HTTP client and CAT021's reassembly, refused a fifth time |
| **The SAC allocation table** | Not an item, but the same shape of decision. §5.2.1's note points at the EUROCONTROL website, and `fixtures/cat021/spec/sac_pin.json` pins a retrieved copy — so unlike CAT021's Phase 1 there *is* a pin here, and the fixtures' consequence is in `fixtures/cat048/README.md`. What is still unpinned is the ICAO 24-bit address allocation table, so the address-block claim stays the weaker of the two |
| **ICAO Annex 10's flight-level range** | I048/090 Note 3 defers to it and §2.2 does not list it. The field's own range is enforced and `flight_level_range_basis` records that the narrower bound was not readable |

### The fixtures — planned here before they existed, and now fifty-two

Nothing existed at Phase 1; now there are **forty-one translatable blocks and eleven refusals**, all built by
`fixtures/cat048/spec/build_fixtures.py` from field values rather than hand-edited — a record's
FSPEC and its block's LEN are both functions of the contents. Each ships as `<name>.cat048` plus
a `<name>.parsed.json` twin, because `lossless.unrepresented()` has no leaf structure to harvest
from bytes and a blocks-only set would show a green run with the never-drop rule never executed.
**The twins are what make the claim real here**: the lossless check *passes* on all 41 of them
rather than skipping, so nothing in this row set is excused.

The set grew past the thirty-four translatable fixtures Phase 1 planned, and the additions are
named rather than slipped in: `psr_track_two_scans_same_track_number` (gap 27's truncation needs
two records to be visible at all), `ic_conflict_codes`, `mode_s_alert_is_not_an_emergency`,
`track_quality_vector`, `mode_1_and_mode_2_with_confidence`, `reserved_expansion_field_carried`,
`fspec_longer_than_necessary`, `helicopter_classification_not_read_as_a_type`,
`field_monitor_report`, and the five geometry fixtures settlement 3's reversal required. Five
refusals were added for the same reason: `descriptor_sixth_extension` (the third FX-to-nowhere),
`missing_mandatory_data_source`, `plot_characteristics_second_primary_octet`, `wrong_category`
and `length_disagrees_with_buffer`.

`check_layouts()` in the generator asserts that every encoder emits exactly the octet count §5.2
states for its item, and `test_the_item_layouts_sum_to_the_standards_own_byte_counts` runs it
from the suite so it cannot be skipped.

| Fixture | What it exercises | The defect it is there to catch |
|---|---|---|
| `mode_s_roll_call_track` | The ordinary case: I048/010, /140, /020 with TYP=`101`, /040, /070, /090, /220, /240, /161, /170, /200 | The whole happy path, replayed **twice** — once with no `sensor_position` and once with one — so the same octets are asserted to yield `position: None` and a derived `Position` from one fixture. Also that the groundspeed reaches `Kinematics.speed_mps` at exactly 0.113 037 109 375 m/s per unit |
| `derived_position_inverts_to_the_polar_values` | A site injected, I048/110 present, `RHO`/`THETA` at awkward values | **The check that keeps settlement 3's imported arithmetic honest.** The derived latitude and longitude must invert to `RHO` and `THETA` within the item's own LSBs — 1/256 NM and 360/2¹⁶ ° — because the pinned document supplies none of the conversion and the round trip is the only available audit |
| `injected_site_no_height_item` | A site injected, no I048/090 and no I048/110 | The documented no-geometry outcome. `position: None`, the reason named in the basis, and **the record still translated** — a `Δh = 0` assumption would paint a target at FL350 overhead 10.7 km from the antenna |
| `injected_site_pressure_height_only` | A site injected, I048/090 only | The degraded branch: a pressure altitude used as a geometric height, with the approximation named in the basis and the height item that supplied `Δh` recorded |
| `injected_site_range_at_maximum` | A site injected, `ERR` set, `RHO` all-ones | **No `Position` is derived from a floor.** The at-or-beyond-maximum flag must suppress the derivation, because a bound is not a measurement |
| `psr_only_plot_no_identity` | TYP = `001`, no /220, no /240, no /161 | Step 3 of the identity chain, and `entity_type` = `UNKNOWN`. An adapter that required an address would refuse this, and one that invented a track number would fabricate continuity |
| `psr_plot_with_track_number_only` | TYP = `001`, /161 present, no /220 | **That the track number is NOT an identity.** Two records one scan apart with the same track number and different measurements must produce **two different `entity_id` values**, and the track number must appear in `attributes` on both. This is the fixture that pins settlement 9's reversal, and it asserts a truncation on purpose — gap 27 |
| `no_detection_track_only` | TYP = `000`, /040 carrying an extrapolated position | `TRACK_UPDATE`, not `DETECTION` — §5.2.4 Note 1's zero-TYP signal, and the position still parked and still not a `Position` |
| `end_of_track_full_items` | `TRE` set with /220, /230, /240 and /250 all present | The recommendation honoured by fidelity: `STATUS_CHANGE`, all four items round-tripping unchanged, and — pinned as an assertion because a first draft got it wrong — **`valid_to` is `None`**. A TRE record does not close the entity: settlement 8, gap 26 |
| `end_of_track_items_omitted` | `TRE` set with all four items absent | The relaxation. A **permitted absence** in `unavailable_fields` and not a refusal — and egress must **not** add them back |
| `mode_s_target_missing_address` | TYP = `101`, `TRE` clear, no /220 | The refusal the relaxation does not cover. Quotes `TYP` and the FSPEC |
| `time_of_day_beyond_one_day` | I048/140 holding 100 000 s | The `CodecError`. A modulo would move the contact by hours with every other check passing |
| `time_of_day_exactly_86400` | I048/140 = 11 059 200 raw | Ambiguity 1's lower boundary. **Accepted**, on §5.2.17's inclusive stated range, and resolved to the next day's midnight |
| `time_of_day_one_lsb_past_86400` | I048/140 = 11 059 201 raw | Ambiguity 1's upper boundary, one LSB away. **Refused**, so the two fixtures together pin the edge rather than the direction. Ambiguity 14 records that `asterix_cat021.py` refuses the value the fixture above accepts |
| `midnight_rollover_before` | 23:59:58.500, clock frozen at 00:00:01.100 the next day | The rollover backwards, echoing CAT021's value on purpose so the shared rule is visible. **The clock is injected in the test, not by the harness**: the harness's shared 06:15 clock resolves both of these to the receipt date and exercises nothing, which is a property of one frozen clock per fixture directory rather than of the rule |
| `midnight_rollover_after` | 00:00:00.900, clock frozen at 23:59:59.700 | The same rule forwards — the direction an adapter that special-cased "subtract a day" gets wrong. Same note about the clock |
| `no_time_item_at_all` | I048/140 absent | The stated absence §5.2.17 permits. `observed_at` from the clock, the basis saying so, and **no refusal** |
| `three_altitudes_disagreeing` | /090, /100 and /110 in one record, with I048/030 codes 12 and 18 | Settlement 5 end to end: three quantities, three datums, no arbitration, the disagreement recorded, the Gray bits undecoded, and the source's own codes named in the basis |
| `flight_level_negative` | /090 holding a negative flight level | Edition 1.32's "in two's complement form" clarification. An unsigned read puts the aircraft at FL 4000 |
| `warning_error_code_series` | /030 with six codes including 0, 15, 33 and a code in the manufacturer range | The set: wire order preserved, duplicates kept, code 0's stated meaning honoured, the 33-without-15 non-conformance recorded, and the manufacturer code carried with no text |
| `warning_error_code_37` | /030 with code 37 | The 1.32 addition, and a code whose meaning is a pointer into the un-pinned REF |
| `radial_doppler_calculated` | /120 subfield #1 with a negative `CAL` and `D` set | Settlement 6: nothing reaches `Kinematics`, and the basis records that the sign convention is the encoder's ICD to define |
| `radial_doppler_both_subfields` | /120 with `CAL` and `RDS` both set | Ambiguity 5. Both parsed and parked, non-conformance recorded, **not** refused |
| `radial_doppler_spare_presence_bit` | /120 primary with a bit in 6/2 set | The refusal. No subfield to decode and no length to guess |
| `extended_range_target` | /020 `ERR` set, `RHO` all-ones, RE field present | Settlement 1's first loss. `RHO` recorded as a **floor**, and the RE octets parked and restored without being read |
| `mode_4_result_in_ref` | /020 ext 1 `FOE/FRI` = `00` with an RE field present | Settlement 1's second and worst loss: an interrogation that happened, reported as `00`. The basis must say the value is ambiguous |
| `military_emergency` | /020 ext 1 `ME` set | `CRITICAL` / `ALERT` at CAT048's only emergency declaration — and a sibling fixture with I048/230 `STAT`=2 and an active /260 must **not** do the same |
| `acas_ra_active_undecoded` | /260 present, /020 ext 3 `ACASXV` = 2 (ACAS Xu), /250 carrying BDS 3,1 | The advisory split across two items, both parked, neither decoded, severity **not** raised — and the test asserts a refusal to interpret rather than an interpretation. The basis must carry the item's own tension: the Definition says "currently active", the Encoding Rule says "generated in the last scan", and this adapter cannot tell which it holds |
| `bds_registers_comm_b_broadcast` | /250 with two registers, one at `BDS1=BDS2=0` | Note 3's trap: `0,0` is "broadcast, unidentified" and not register 0,0 |
| `ghost_target_still_translated` | /170 `GHO` set | The row where the source says the track is not real. Translated **in full** with the flag parked; a fixture producing no objects would mean the adapter had started filtering |
| `radial_ambiguity_rad_invalid` | /170 `RAD` = `11` (Invalid), `CDM` = `11` (Unknown) | Two reserved-or-unknown codes in one item, landing in different bags: `Invalid` is `unresolved_raw`, `Unknown` is a stated absence |
| `trailing_fspec_fx_set` | FSPEC octet 4 with `FX` = 1 | CAT048's counterpart to CAT021's Not-Used-FRN refusal. There is no FRN 29 |
| `track_status_second_extent` | /170 first extent with `FX` = 1 | The other FX-to-nowhere. §5.2.19 defines no second extent |
| `plot_and_track_one_block` | Two records for one target, one a plot and one a track | Settlement 11's third temptation: two entities, **not** one track, and no association performed |
| `icao24_shared_with_cat021` | An address also used by a CAT021 fixture | The no-fusion assertion. The same derived `entity_id`, two objects, **no join** — and the two records carry different SAC/SICs, per §4.5.4 |
| `two_stations_one_block` | Two records with SAC/SIC `0x25/0x25` and `0x25/0x26` | §4.5.4's addressing rule. Two Radar Systems in one payload, and neither record's geometry resolvable from the other's |
| `spare_bits_nonzero` | A conforming record with spare bits set to 1 | §4.4's recommendation is not a requirement. The byte-exact round trip only survives if spare bits are parked as sent |
| `special_purpose_field_opaque` | An SP field of unknown content | Parked verbatim on ingest, restored verbatim on egress, never written for an object that arrived without one |
| `plot_characteristics_all_subfields` | /130 with all seven subfields, `RPD` and `APD` at maximum | Two's complement on five of the seven, and the at-or-beyond-maximum floors on the two difference subfields |
| `records_do_not_tile_len` | A block whose last record overruns `LEN` | The structural gate, and the assertion that **no** records are emitted — not even the ones parsed before the discrepancy |

An `egress/` subdirectory will hold the CDM-side fixtures: an `Entity` that never came from
CAT048 and a `Track`, both exercising the **refusal** in the egress row set, which is the shape
CAT021's egress set does not have. `refusals/` holds the payloads meant to raise, and `spec/`
holds the pin and the generator — neither beside the payloads, because `harness.run()` replays
every file in a fixture directory through `to_cdm()`.

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

   **STANAG 4607 adds a fifth key and, unusually, a defensible one.** `P8` Platform ID is a tail
   number, a satellite name or "an appropriate unique designator", and §3.1.8 makes the owning
   nation responsible for its uniqueness — so `P3` + `P8` is both the string an operator reads *and*
   a globally unique identifier, which no earlier adapter's name field was. It becomes a
   `SourceId` for that reason and still parks at `attributes.platform_id` as a name, because a
   `SourceId` is a provenance mapping and not a label. It demonstrates the missing distinction
   rather than merely widening it: an identifier and a name are different things, and the CDM has
   a field for one of them.

   **CAT048 adds an eighth key, and the roster sweep found the tally had been wrong before it.**
   `attributes.aircraft_identification` — I048/240, eight characters at six bits, "aircraft
   identification when flight plan is available **or the registration marking when no flight plan
   is available**", so the field holds two different kinds of string with nothing saying which.
   Counting properly, because the count is the argument:

   | Key | Adapter(s) |
   |---|---|
   | `attributes.callsign` | `tak` (a CoT operator label) **and** `adsb` (a flight identifier the crew types) — one key, two adapters, two precedence rules, which is the convergence this gap calls worse than disagreement |
   | `attributes.vessel_name` | `ais` |
   | `attributes.call_sign` | `ais` |
   | `attributes.aid_name` | `ais` |
   | `name` | `legion` — a required field rather than an attributes key, which is the evidence that closing this gap is worth it |
   | `attributes.target_identification` | `cat021` |
   | `attributes.platform_id` | `gmti` |
   | `attributes.aircraft_identification` | `cat048` |

   **Seven adapters, eight private keys.** The previous tally read "five adapters and six private
   keys" and omitted `cat021`'s `target_identification` — which that row set calls "gap 1's most
   awkward case yet" and explicitly says is "counted in gap 1". So the gap had been undercounting
   itself by one adapter and one key since adapter #6, which is a small demonstration of why a
   count in prose needs a sweep: the number is the whole argument here, and nothing failed a build
   when it drifted.
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

   **A `ZOMBIE` on a `FRIEND` identity stays `FRIENDLY`, and Ed B's structure is what decides
   it.** Table 2.5.34-1 makes these two separate attributes — `identity` is "the estimated
   identity/status … in accordance with STANAG 1241" and `identityAmplification` is "additional
   identity/status information (amplification)" — and the standard states no co-occurrence
   restriction between them. So `FRIEND` + `ZOMBIE` is the designated identity field plus an
   amplifier the standard permits beside it, not a contradiction a translator may adjudicate.
   Downgrading a primary assertion because of a subordinate field is precisely the move
   `CollectionInformation.essence` is forbidden from making against `source.synthetic`, and
   deciding which of the two to believe is the fusion-layer judgement `enums.Affiliation`'s own
   docstring says an adapter does not make. The identity governs; the amplification parks.

   **Note the asymmetry with `FAKER`, because it is a principle and not an inconsistency.** A
   friendly-defined amplification *does* override a contradicting identity and a suspect-defined
   one does not, and the line between them is whether the CDM has a member for what the
   amplification states. `FAKER` says "friendly" and `FRIENDLY` exists, so reading it is
   translation. `ZOMBIE` says "suspect" and no member exists, so acting on it could only mean
   choosing some *other* value to stand in for it — which is a judgement, and the judgement this
   gap exists to record rather than make.

   **`FAKER` "overriding" the identity is not adjudication**, and that is worth saying plainly
   because "override" is the word that makes it sound like one. Its Edition B definition is
   "Friendly track, object or entity acting as exercise hostile" — **the identity claim sits
   inside the amplification literal itself**, so reading `FAKER` is reading a fact the standard
   states, not weighing two fields against each other and picking a winner. `ZOMBIE`'s definition
   asserts *suspicion*, which is precisely the judgement `enums.Affiliation` deliberately has no
   member for, so there is nothing there to read and it can only be recorded.

   **The principle self-terminates, and this gap is what it terminates on.** If `Affiliation`
   ever grows `SUSPECT`, `ZOMBIE` and `TRAVELER` move from recorded to read by the same rule,
   with no new rule needed — closing this gap closes them.
   `test_the_two_suspect_amplifications_never_yield_friendly` is the tripwire: it asserts the
   member's absence, so it fails the build the moment someone adds it, and whoever does will be
   sent here.

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

   **STANAG 4607 adds a case this gap cannot absorb, and it is filed as gap 21 rather than here.**
   `D32.7` is one *component* of a target's velocity — the radial one — and the tangential
   component is physically unobservable to a single-look MTI radar. A component is not a vector
   with elements missing; it is a projection, so there is no conversion to declare and nothing to
   round. This gap is about *representing* a velocity the source stated in full; **gap 21** is
   about a velocity no source can state in full.
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

   **STANAG 4607 states three vertical 1-sigma figures in three different units** and none of them
   has a home: `D14` Sensor Position Uncertainty – Altitude in centimetres, `D32.14` Target
   Measurement Uncertainty – Height in metres, and `J18` the nominal version in decimetres. The
   first two are simple metre figures once divided — no matrix, no frame, no correlation argument —
   so this is the gap in its plainest form: three fields the CDM would take verbatim if the field
   existed.
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

   **STANAG 4607 states a heading and a ground track in the same segment, four bytes apart**, which
   is the clearest evidence this gap will get: `D21` Platform Orientation – Heading is the angle
   from True North to the platform's roll axis, and `D15` Sensor Track is its ground track. They
   differ by drift, both are Conditional and often both present, and `Kinematics` has one field —
   so `course_deg` takes `D15` and `D21` parks beside `D22` Pitch and `D23` Roll, which have no
   home either. A format that reports attitude and track separately is a format that considers them
   different facts.
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

   **STANAG 4607 contributes a fourth shape and a sentinel worth noting.** `H30` Target Radial
   Electrical Length is a *computed object length* from an HRR profile, in metres, with `H31`'s
   1-sigma beside it — one dimension of an extent, derived rather than measured, and "set to a
   value of 0 if HRR is not performed", so the zero is a sentinel and not a zero-length object.
   Parked, like the rest.
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

   **STANAG 4607 is the case where the format states its surface and its own guide contradicts
   it**, which is the strongest possible argument for that framing. §3.4.9, §3.15.4 and §3.4.32.6
   each say "above the WGS 84 ellipsoid" without qualification; guide §E.8 says heights are
   measured "either from the reference ellipsoid, or from mean sea level if a geoid model is being
   used", and `J28` Geoid Model Used names `EGM96`, `GEO96` or `Flat Earth` on every job. The two
   readings differ by the geoid undulation, up to about 105 m. The row set takes the standard's
   unconditional statement and records the contradiction — and a mandatory reference-surface field
   would have made the contradiction impossible to write.
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

   **STANAG 4607 raises the floor again**: `P4`, `P5` and `P6` are **Mandatory on every packet**, so
   unlike NITS — where the label is mandatory in the XML syntax and absent from the core model —
   here a classification, a classification *system* digraph and a sixteen-bit caveat field arrive
   with every single message and nothing can be read without meeting them. It also supplies the
   argument against any reduction to a string: the standard and its own guide publish **two
   different codeword tables for the same sixteen bits of `P6`**, and the standard says each nation
   defines its own besides — so the label is only interpretable together with the digraph that
   scopes it, which is precisely the structure a single `classification: str` would destroy.
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

   **STANAG 4607 states the extreme case of this gap**: `D6` Dwell Time is the instant of the
   *temporal centre* of a dwell (§3.4.6), and a single Dwell Segment may carry up to 65 535 target
   reports that all share it. So one `observed_at` covers up to 65 535 detections whose returns
   arrived at different moments inside an interval whose duration the format never states — `D27` is
   an angular half-extent, not a temporal one. CAT021 states two applicability times in one record;
   GMTIF states one time for a whole segment, and the residual is not merely unrecorded but
   unknowable from the payload.
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

   **STANAG 4607 is the fourth format to hit this and the first to state a full provenance
   *chain*.** `J2` Sensor ID – Type and `J3` Sensor ID – Model name the producing radar (`APY-7`,
   `AN/ZPY-2 (MP-RTIP)`) on every job, and the Processing History Segment then names every system
   that has touched the data since: `C2`–`C5` identify the original radar job by nationality,
   platform, mission and job, and each `C6.2`–`C6.5` record identifies one modifying system the
   same way, with `C6.6` saying what it did. `SourceRef` names this adapter. So the format states a
   directed graph of producers and the CDM records the translator — and the chain is also **gap
   19**, which is why both entries point at each other rather than either one growing a field.
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

   **STANAG 4607 reaches the same problem from the platform's own side.** A packet may carry several
   Platform Location Segments and several Dwell Segments, each stating the platform's position
   *and* its ground track, ground speed and vertical velocity (`L5`–`L7`, `D15`–`D17`). Every
   position becomes a `TrackSample`; `Kinematics` hangs off `Entity` and there is one of it. So a
   four-sample platform history yields one `Kinematics` and three parked velocity triples keyed by
   sample index — the NITS per-point velocity case, on the object doing the observing rather than
   on the object observed, and reached in a format with no per-point extension point to hope for.
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

   **STANAG 4607 removes the last excuse for a scalar.** It states twelve uncertainty figures, and
   the pair that matters is `D12` Sensor Position Uncertainty – Along Track and `D13` Cross Track:
   **both horizontal, both 1-sigma, both in centimetres, and orthogonal to each other.** That is
   the most reducible uncertainty statement in any format in this document and it is still not one
   number — reducing it means choosing an RSS, a semi-major axis or a DRMS that the source did not
   state. Beside them, `D32.12` is a *slant*-range standard deviation, which is not a horizontal
   error at all without a grazing angle the format never gives; and `J22`, the nominal cross-range
   figure the standard mandates as a fallback, is an **angle in degrees**, so the fallback chain
   terminates in a quantity that is not even in metres. `Position.accuracy_m` is therefore `None`
   on every object the GMTIF row set produces. An `accuracy_m` that carried an along/cross pair
   would express `D12` and `D13` exactly, which is the smallest concrete thing this gap could
   grow.
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

   **STANAG 4607 sharpens the *subject* half rather than the retraction half.** `D32.11` Target
   Classification Probability is "the estimated probability that the target classification
   appearing in field D32.10 is correctly classified" — a percentage, so `value / 100` is exact,
   and exactly the shape `Entity.confidence` wants. It still cannot be written there, because
   `confidence` is a bare float with **no stated subject**: writing 70 would say "we are 70 % sure
   this object exists" about a source that said "we are 70 % sure it is a wheeled vehicle". NITS
   showed that a confidence is uninterpretable without its `type`; GMTIF shows it is
   uninterpretable without knowing what it is a confidence *in*, and those are two different
   missing halves of one field.
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

   **A fourth has now hit it, and the prediction held.** STANAG 4607 contributes a seventh reference
   kind — the Processing History Segment's `<DataSetID>` chain, where `C2`–`C5` name the radar job
   the data are derived from and each `C6.2`–`C6.5` record names one modifying system — plus
   `H5`'s HRR-to-target-report pointer and `D32.17`'s pointer into a DIS simulation. All three are
   the same missing thing: a typed, directed link between two objects. **They are recorded here and
   they do not change the design question**, which is what "a fourth will not add information"
   meant, and leaving the sentence standing beside the fourth adapter's evidence is the point.
20. **No detection, only tracked objects — the CDM cannot say that a state claim is one
   unassociated observation.** An `Entity` says *this exists, here, now*; a `Track` says *this is
   where it has been*. Neither can say *at 12:00:00.123 a radar received a return consistent with a
   mover at this point, and nothing before or after that instant is claimed*.

   STANAG 4607 is where this stops being a nuance, because **that is the only kind of statement the
   format makes**. A GMTI target report has no identifier, no continuity, no predecessor and no
   successor: §3.4.32.1's MTI Report Index is scoped "within the dwell" by its own definition, and
   the format's own implementation guide sends the reader to the sensor manufacturer for the
   association rule (FAQ Q10). So the row set emits one `Entity` and one `DETECTION` `Event` per
   report and **no `Track` for any target, ever** — and a consumer receiving one of those `Entity`
   objects beside a STANAG 4676 one cannot tell them apart. One is a tracked object with a
   producer-asserted identity, a history, a confidence and a segment status; the other is a hit.

   Four consequences, in increasing order of how much they cost:

   - **`Entity.valid_to` has no honest value.** `None` reads as "still current" to anything holding
     state; `valid_from` would say the object ceased to exist immediately. The row set chooses
     `None` and records the problem in a basis field, which is the best available and is not good.
   - **`entity_id` is derived from a positional index**, because the format guarantees no
     identifier below the job: `(P3, P8, P9, P10, D2, D3, segment ordinal, report ordinal)`. The
     last two are not stable under any re-segmentation of the packet, and the format explicitly
     permits re-segmentation (§3.4.32, guide §D.2). So the same physical detection re-transmitted
     in a differently-split packet gets a different `entity_id`. **This is gap 1 and gap 16's
     problem — private index arithmetic standing in for canonical structure — arriving at the level
     of object identity itself.**
   - **`EntityType`'s eight members were designed for a different question**, and **twenty-five** of
     `D32.10`'s forty-three named classifications have no honest home in them: `Person`, `Animal`,
     `Beacon`, `Stationary Rotator` and `Ground Rotator` (Doppler signature classes, not
     structures — see amendment 1), `Large Multiple-Return` (an unresolved group of unstated size),
     `Clutter` and `Phantom` — the last two being *explicit denials that anything is there*, which
     the CDM cannot express while still emitting an object. A detection type is not an entity type,
     and amendment 1 raised the count from twenty-one by declining to read a motion characteristic
     as an installation.

   **A divergence this gap now has to carry, and it is a person.** `D32.10` code 9 is
   `Person, Live Target` and this row set maps it to `UNKNOWN`. CAT021's I021/020 emitter category
   16 is `Parachutist / skydiver` and the **shipped** `asterix_cat021.py` maps it to `PLATFORM`,
   with its row admitting in as many words that "a person under a canopy is not a platform" and
   that `PLATFORM` "overstates slightly". So one concept — a human being detected by a sensor —
   has two answers in one codebase, and it is **stated rather than resolved**, on the I021/170
   precedent that gap 2 uses for FAKER: the CAT021 behaviour is published, with an adapter, a
   fixture and a golden file behind it, and changing it is a 1.1.0 question with a migration note
   rather than a side effect of an eighth adapter.

   Both arguments, because whoever settles this has to weigh them rather than inherit a preference:

   - **For `PLATFORM` (the CAT021 answer).** ADS-B and CAT021 carry aircraft and nothing else, so
     `PLATFORM` is the class-wide default and a skydiver is an oddity *inside* a population that is
     otherwise entirely platforms. Mapping the oddity to `UNKNOWN` would put a hole in an otherwise
     uniform column, and a consumer filtering for `PLATFORM` to get "air traffic" would silently
     lose the one contact under a canopy — which is a contact that matters.
   - **For `UNKNOWN` (the GMTIF answer).** A ground surveillance radar reports vehicles, vessels,
     aircraft, animals, groups, clutter and dismounts in one stream, so there is **no class-wide
     default to be an oddity inside**. `PLATFORM` here is not a slight overstatement of a
     surrounding norm; it is a positive claim that a walking human is a platform, made about a
     population where "vehicle" and "person" are adjacent enumeration values the source
     deliberately distinguished. And the raw wording is parked either way, so `UNKNOWN` loses
     nothing a consumer cannot recover.

   The honest resolution is probably neither: the shape both answers are working around is that
   `EntityType` has no member for a person, which is this gap's argument and not a mapping choice.
   `test_the_person_divergence_from_cat021_is_deliberate_and_pinned` fixes both mappings so the
   question cannot be closed by accident in either direction, and it fails the build if
   `EntityType` grows the member that would close it properly.

   **A second divergence this gap carries, and it is the same question about the same objects:
   WHERE A DETECTION'S POSITION LIVES.** Four shipped adapters emit an `Entity` plus a `DETECTION`
   `Event` for one target report, and they disagree about `Event.geometry`:

   | Adapter | `Event.geometry` on a detection |
   |---|---|
   | `adapters/stanag4676.py` | a `Point`, from the `Detection`'s `centroid` |
   | `adapters/gmtif.py` | a `Point`, from the target report's recovered position (amendment 1; it was `None` in the Phase 2 commit) |
   | `adapters/asterix_cat021.py` | `None` |
   | `adapters/adsb.py` | `None` |

   Both arguments, because whoever settles this has to weigh them rather than inherit a majority:

   - **For a `Point` (the NITS and GMTIF answer).** `Event.geometry` is documented as GeoJSON in
     WGS84 and is the CDM's only field for *where an event happened*. A detection's whole content
     is a location at an instant, so leaving it `None` puts the one thing the event is about
     somewhere a consumer holding the `Event` alone cannot reach — and `related_entities` is a list
     of ids, not a join a consumer can perform without the `Entity` in hand. **Gap 19** is exactly
     the observation that a bare id is not a resolvable reference.
   - **For `None` (the CAT021 and ADS-B answer).** The fix is a *state* of the object, which is
     what `Entity.position` is for, and writing one measurement into two objects gives it two
     places to be edited and two places to drift. It also duplicates bytes in every store and
     every wire format the CDM is serialised into, on the most numerous object kind there is.

   **Stated rather than resolved, on the I021/170 precedent**, and note the asymmetry with the
   person divergence above: there the shipped adapter is the one that would have to change, and
   here the shipped adapters are two of four. Neither is touched.
   `test_where_a_detections_position_lives_diverges_across_four_adapters` pins all four so the
   question cannot be closed by accident, and it is a **1.1.0** question — the honest fix is a
   documented rule for the whole model (a detection's fix belongs in one named place, and every
   adapter follows it) with a migration note, not a fifth adapter voting.
   - **A consumer that fuses would have to undo this first.** The honest input to a tracker is a
     stream of detections; what it receives is a stream of `Entity` objects each claiming to be a
     thing that exists.

   *Not yet proposed, and the shape is the question.* The candidates are genuinely different: a
   `DETECTION`-flavoured `Event` carrying a `Position` and no `Entity` at all (which loses
   `entity_type` and the position field every consumer draws from); an `Entity` field stating
   observation kind and duration-of-claim; or a fifth canonical object for an observation, which is
   the same "fifth thing in a model built on four" question that **gap 15** (intent) and **gap 19**
   (relation) both reach from their own directions. Whoever takes it should note that all three of
   those gaps are asking the model to hold something that is *not* one of the four kinds, and that
   deciding the four kinds are complete is also an answer.
21. **No home for a radar measurable — and in particular no way to state one component of a
   velocity.** `Kinematics` is `speed_mps`, `course_deg`, `climb_mps`: a full ground velocity, or
   nothing.

   A single-look MTI radar measures exactly one component of a target's horizontal velocity — the
   radial one — and cannot observe the tangential component at all. STANAG 4607 states it in
   `D32.7`, "the component of velocity … along the line of sight between the sensor and the
   reported detection, where the positive direction is away from the sensor", with `D32.8` Target
   Wrap Velocity beside it so a consumer can un-alias it and `D32.15` giving its 1-sigma. **All
   three park, and `Kinematics` is `None` on every target `Entity` in the format**, because the
   radial component is a lower bound on the speed and writing a lower bound into `speed_mps` states
   a measurement nobody made.

   That is the sharp half. The blunt half is everything else the format measures and the CDM has
   nowhere to put: `D32.9` Target SNR in decibels, `D32.18` and `H20` Radar Cross Section in half
   decibels, `D32.11` Target Classification Probability as a percentage, `D31` and `J24` Minimum
   Detectable Velocity, `H30` Target Radial Electrical Length with `H31`'s uncertainty. Six
   quantities that a GMTI consumer uses to decide whether a hit is worth looking at, and every one
   of them lands in `attributes` under a key only this adapter knows — **gap 1**'s private-key
   problem, on the numbers rather than on the names.

   Note the two interactions, because they are what makes this more than a wish for more fields.
   **With gap 4** (velocity representation): that gap records that the CDM carries scalars where
   4676 carries a 3-vector, and its answer is a conversion. Here there is no conversion, because
   the information genuinely is not there — a component is not a vector with two elements missing,
   it is a projection. **With gap 18** (confidence provenance): `D32.11` is a confidence *about a
   classification*, and `Entity.confidence` is a bare float with no stated subject, so the field
   cannot receive it even though the number is exactly the right shape.

   *Not yet proposed*, and the smallest honest proposal is not more fields but a decision about
   what `Kinematics` is for. A `radial_speed_mps` beside `speed_mps` would need the bearing it was
   measured along to mean anything, which is a second field and a frame; an SNR and an RCS belong
   to the *return* rather than to the object, which argues they are `Event` payload and not
   `Entity` state at all. That argument is **gap 20**'s argument again, which is why the two should
   be read together.
22. **No negative information: the CDM cannot say that an area was searched and nothing was
   found.** Every object in the model is a positive claim. There is no way to record that a sensor
   looked somewhere, at some time, with some sensitivity, and reported nothing — and no way to
   record that what it did report had things deliberately removed from it.

   **STANAG 4607's own implementation guide states the requirement in one sentence** (§D.2): "It is
   necessary that the receiver of the Target Reports knows the area that is being reported on. This
   is because the fact that the radar has looked at a particular area and found no targets can be
   just as important as receiving targets in an area." The standard then builds the format around
   it — §3.4: "A Dwell Segment shall be transmitted **even if no targets are observed**" — so a
   `D5` of zero is not an empty message, it is the format's primary product for an empty area.
   Today such a Dwell Segment produces one platform `Track` sample and nothing else, and the
   statement it was sent to make is gone.

   The material the CDM cannot hold is not one field. It is a coherent set, and the format states
   all of it:

   | What the format states | Fields |
   |---|---|
   | **where** the sensor looked | `D24`/`D25` dwell centre with `D26`/`D27` extents; `J6`–`J13`, the tasked or actually-scanned bounding quadrilateral |
   | **when**, and for how long | `D6`, and `J15` Nominal Revisit Interval |
   | **what it could have seen** | `D31`/`J24` Minimum Detectable Velocity, `J25` Detection Probability for a ten-square-metre target, `J26` False Alarm Density |
   | **what was taken out** | `J4` Target Filtering Flag — area filtering, Area Blanking, Sector Blanking, and the standard's own admission that "the format does not currently specify the area over which blanking has been applied"; and `C6.6` Processing Performed, eight of whose fourteen operations are eliminations |
   | **that nothing was there** | `D5 = 0` |

   The consequence compounds with the gap above. A commander looking at a map cannot distinguish
   "no contacts reported here" from "not looked at", from "looked at and nothing moving faster than
   3 m/s would have been seen", from "looked at, targets found, and then filtered out by a
   downstream system that recorded only *that* it filtered". Those are four different operational
   pictures and the CDM renders them identically — as empty space.

   *Not yet proposed, and it is the second-largest open question in this document after gap 19.*
   The honest shapes are very different: a `PlanObject`-like coverage object with a validity window
   (which puts a fact about somebody else's sensor into the kind reserved for our own plans); an
   `Event` type meaning "this area was surveilled" with the sensitivity in its payload (cheapest,
   and it makes a non-observation an occurrence, which is at least defensible); or an acceptance
   that negative information belongs to a coverage service rather than to an interchange model.
   Note the interaction with **gap 14**: a coverage statement is worthless without saying which
   sensor made it, and `SourceRef` cannot. Recorded here so that whoever meets it next — and
   anything with a footprint will, since this is the first sensor format in this document whose
   coverage is stated rather than implied — finds a decision rather than an oversight.

23. **No way to carry an observation whose source states no time.** `Event.observed_at` is
   documented as "When the SOURCE saw it. Never receipt time." It is also **required**, with no
   default and no companion field for saying where it came from — so an adapter meeting a payload
   that states an observation and no instant has three options, and all three break something the
   model says.

   **STANAG 4607 is where that stops being hypothetical, because three of its segments state no
   time of any kind.** Not "an optional time that happened to be absent" — no time field exists in
   the layout at all:

   | Segment | What it states | Why it has no instant |
   |---|---|---|
   | Free Text (§3.8) | `F1`, `F2`, `F3` — an operator's message | three fields, none of them temporal |
   | Processing History (§3.14) | the `<DataSetID>` chain of every system that modified the data | five fields plus N records, none of them temporal, and §3.14's own "shall be transmitted every 3 minutes" is a *cadence* rather than a stamp |
   | HRR (§3.5) whose `H2`/`H3` name a dwell **not in this packet** | a range-Doppler signature | the segment borrows its instant from the Dwell Segment those two fields point at, and resolving the pointer across packets is a join the fusion line refuses |

   The three options, and why the chosen one is still a violation:

   - **Refuse the object.** It is data, and the never-drop rule says data is not discarded because
     a field the CDM requires is absent from the source. This would delete an operator's message
     for having no timestamp.
   - **Invent an instant** — the epoch, the packet's other times, the enclosing dwell's `D6`. Every
     one of these produces a plausible instant nobody stated, which is the failure mode every time
     settlement in this document exists to prevent.
   - **Use the receipt instant and say so** — what `adapters/gmtif.py` does, with
     `payload.observed_at_basis` recording that the format stated no source time. **This violates
     the field's own documented meaning on three object kinds**, and the basis string is a
     convention rather than a contract: it is a key in an untyped `payload` dict, so nothing
     validates it, nothing requires it, and a consumer that does not know to look sees a normal
     `observed_at` and takes it for a source time.

   *Proposed for 1.1.0, and it is two changes rather than one.* Make `observed_at` **optional**
   (MINOR — a nullable field), so "the source stated no instant" is expressible as an absence
   rather than as a substitution; **or** add a canonical basis field beside it so the substitution
   is at least typed and mandatory. The first is cleaner and pushes the problem onto consumers that
   currently assume a value; the second is smaller and leaves the wrong value in place with a label.
   **The docstring amendment rides the same release**, because `models.Event.observed_at`'s "Never
   receipt time" is part of the CDM v1.0.0 contract and editing it in a patch release would change
   what shipped objects claim about themselves.

   Note which gap this is NOT. **Gap 13** is that a CDM object carries one instant where a source
   states several — a *resolution* problem. This is that a source states **none**, and no number of
   per-measurement times fixes it. And note the interaction with **gap 20**: a detection with no
   instant is even less like a tracked object than one with an instant, so whatever closes 20 has
   to decide whether an observation kind implies a time.

24. **No sensor frame — so a sensor-relative measurement can only be carried by converting it.**
   Every position in this document so far has been geodetic or convertible to it by arithmetic the
   standard itself supplies: CoT and AIS state latitude and longitude, Legion states them or an
   ECEF triple with a named CRS, CAT021 states them already CPR-decoded, GMTIF states them as exact
   binary angles its own tables define. **ASTERIX CAT048 states a slant range and an azimuth from a
   station whose position the format never carries** — §4.3.1 names "the radar site location" as
   the origin and no data item holds it.

   Settlement 3 resolves the *practical* problem by taking the site as a constructor argument, on
   the injected-clock precedent. It does not close this gap, and the residue is precise:

   - **The CDM can only hold the converted product, never the measurement.** `Position` requires
     `lat` and `lon`, so a range and a bearing have to become a geodetic fix or park in
     `attributes`. There is no way to say "1 234 units of 1/256 NM on bearing 0x3F00 from sensor
     X" in a canonical field, which is what the record actually asserts.
   - **The conversion arithmetic is nowhere in the pinned text.** §4.3.2.1 gives only the
     radar-plane identities `X = RHO * SIN(THETA)` / `Y = RHO * COS(THETA)`; §4.3.2.2 names the
     WGS-84 ellipsoid and then defers to "a suitable projection technique … (e.g. a stereographical
     projection)". There is no geodesic direct solution and no slant-range formula anywhere in the
     document. So the derived latitude and longitude are **the adapter's arithmetic, not the
     specification's** — a first for a binary format in this repository — and the only thing
     keeping that honest is the inversion test: the derived position must return `RHO` and `THETA`
     within the item's own LSBs, 1/256 NM and 360/2¹⁶ °.
   - **Without a site there is no fix at all**, so the same wire record yields a positioned entity
     or an unpositioned one depending on a constructor argument. That is correct behaviour and it
     is also a gap: nothing in the object model distinguishes "no position stated" from "position
     stated relative to something we were not told about".
   - **`PositionSource` has no member for a sensor measurement.** `GNSS`, `INERTIAL`, `MANUAL`,
     `ESTIMATED`. Settlement 3 writes `ESTIMATED` because it is the only one that is not an
     outright false statement, but a radar return is a measurement and the enum cannot say so.
   - **I048/042 and I048/210 stay in `attributes` regardless.** The Cartesian components and the
     per-axis standard deviations are expressed "within the local grid system", and which grid is
     signalled by `TCC` in a different item — so even with a site injected they are uncarryable.

   *Not proposed as a field yet, and the dependency is the reason rather than an excuse.* A
   sensor-relative position is meaningless without a machine-readable identity for the sensor it is
   relative to, and that is **gap 14** — `SourceRef` names the adapter and the system and cannot
   name the producing sensor. So the honest shape is one change with three halves: somewhere
   canonical for "which sensor", somewhere canonical for "where, relative to it", and a
   `PositionSource` member that does not call a measurement an estimate. Adding the geometry alone
   would produce a range and a bearing from an unnamed origin, which is worse than parking them,
   because it *looks* like a position. **Gap 17** overlaps: a covariance in a local grid is
   uncarryable for exactly the reason the position in that grid is.

25. **No line-of-sight velocity component.** `Kinematics` carries `speed_mps` (over the ground),
   `course_deg` and `climb_mps`. CAT048's I048/120 states a **radial Doppler speed**: the
   projection of the target's velocity onto the radar's line of sight, at 1 m/s, with a validity
   bit. A target crossing the beam has a radial speed of zero and a ground speed of three hundred
   knots, so the quantity cannot go into `speed_mps` — that is not a precision loss, it is a
   different measurement under a name every consumer reads as ground speed. It is parked, and
   `speed_mps` is left null on a plot that carries no I048/200, exactly as **gap 10** leaves it
   null on an ADS-B airspeed frame.

   **This is gap 24's other half and they should be closed together.** A radial speed is measured
   along the same line of sight a polar position is measured on; both are missing the same thing,
   which is a frame. Recorded as two gaps because they are two fields, and flagged as one concept
   so that whoever implements either does not invent a private frame for it.

   Whoever takes it inherits a sentinel-shaped problem that is not a sentinel: **the sign is
   undefined by the standard.** §5.2.15's note says the meaning of a positive or negative value
   "is implementation dependent and shall be described in the ICD of the system generating the
   ASTERIX record", with a *recommendation* that positive mean moving away. So a canonical
   `radial_speed_mps` would need a stated sign convention and a per-source declaration of which
   way the source runs — gap 7's magnetic-versus-true problem again, in a third axis. Two more
   quantities arrive with it and neither is about the target: I048/120 subfield #2's `AMB` is a
   Doppler ambiguity interval and `FRQ` is the transmitter frequency, both properties of the
   radar.

26. **No way to say a track has ended.** ASTERIX CAT048 makes the **only explicit terminal
   declaration of any source in this document**: I048/170 First Extension bit 8, `TRE`, "End of
   track lifetime (last report for this track)". The CDM has nowhere to put it.

   The tempting field is wrong, and settlement 8 reverses a first draft that used it.
   `Entity.valid_to` is "When it ceased" on an object whose `entity_id` is derived from a 24-bit
   airframe address; `TRE` ends "this track", which I048/161 scopes as "a track record within a
   particular track file". Writing the track-end instant into `valid_to` therefore tells every
   consumer that does not read a basis key that **the aircraft's state ceased** — a false
   statement about a longer-lived thing than the one that actually ended. `Track` has no
   extension bag to hold it either (that is the existing `Track.attributes` candidate), and
   `Event.event_type = STATUS_CHANGE` records that *something* changed without saying what.

   *Not proposed as a field on `Entity`.* This is **gap 15 / gap 19 territory** — a lifecycle
   statement about a track, which is either a typed relation or a fifth object kind, and both of
   those are already open questions with owners. What belongs in the same change is gap 27 below:
   a vocabulary for a track's life needs to cover its start and its identity as well as its end,
   and closing only the end would leave the CDM able to say a track stopped and unable to say
   which track it was. Until then the bit rides in `attributes.track_end` and the loss is that a
   consumer must know that key exists.

27. **No way to carry a source-stated track continuity that is not an identity.** Settlement 9
   reverses a first draft that made I048/161 a `SourceId`, because a station-scoped, recycled
   12-bit number keyed into `entity_id` merges two different airframes into one entity — and
   `entity_id` is the field the CDM guarantees is "stable across updates". The cost of declining
   is real and is named here rather than left implicit: **for a PSR-tracked target with no Mode S
   address, consecutive scans of the same radar track produce different `entity_id` values.** The
   one case where CAT048 states continuity is the one case the CDM cannot express.

   The claim is not lost — the track number, its SAC/SIC scope, and I048/170's `CNF` (confirmed
   versus tentative), `RAD` (which sensor maintains it) and `DOU` (confidence in the plot-to-track
   association) all ride in `attributes`. What is lost is the ability to say "these two objects are
   the same track according to the sensor" **without** asserting they are the same airframe
   according to us. Those are different claims and the CDM currently has one field for both.

   *Not proposed separately.* It is gap 26's other half and gap 19's shape: a scoped, non-identity
   correlation claim between two objects is a relation, and a relation is the thing gap 19 says the
   CDM lacks. Whoever opens gap 19 should read this row and gap 26 together, because a radar track
   is the smallest complete example available — it has a start, an identity scoped to one station,
   a confidence, and an explicit end, and the CDM can hold exactly none of the four as such.

28. **No way to say a measurement is geometrically impossible.** CAT048's slant-range correction
   needs the target's height above the site: the ground range is `sqrt(RHO² − Δh²)`, so `|Δh|`
   larger than `RHO` has no real solution. That is not a hypothetical. It happens whenever a
   **pressure altitude stands in for a geometric height** — settlement 3's second height source,
   I048/090, which is used exactly when the measured I048/110 is absent. A flight level and a
   geometric height differ by hundreds of metres in ordinary weather, and at short range that is
   more than enough to make `|Δh| > RHO`.

   **This was shipped as a call-site comment in `cat048_codec.ground_range_m` and that was the
   wrong home for it**, because a decision nobody can find later is not a decision — which is the
   principle the whole `*_basis` discipline exists to serve. The three candidate behaviours, with
   the two rejected ones named:

   | Behaviour | Verdict |
   |---|---|
   | **Refuse the record** | Rejected. The record is otherwise complete and translatable — it has an identity, a time, Mode codes, a track status. Refusing it because one derived view cannot be computed is the adapter filtering, which the `Adapter` contract forbids in as many words |
   | **Clamp the ground range to zero** | Rejected, and it is the dangerous one. It puts the contact **at the antenna** — a plausible position, structurally valid, and wrong by up to the target's own altitude. The same failure mode as reading a floor as a value |
   | **Derive no position and record why** | **Shipped.** `Entity.position` is `None`, the polar values are parked as in every other non-derived branch, and `attributes.position_basis.reason` names the impossibility with both figures in it. The record translates in full |

   *Not proposed as a field, and the reason is that the CDM has nowhere for a NEGATIVE result
   about a measurement.* `unavailable_fields` says the source declined to state something;
   `unresolved_raw` says a stated value could not be used. This is a third thing: two stated
   values that cannot both be true of one geometry. It is closest to **gap 18**'s confidence
   provenance — a machine-readable statement about why a derived value is absent — and whoever
   opens that should decide whether "the source contradicted itself" is a case of it or a fourth
   bag. Until then the basis string carries it, and `test_the_impossible_geometry_is_a_named_gap`
   asserts that this row and the call site still agree.
