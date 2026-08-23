# CDM schema versioning and migrations

Every serialised object carries `schema_version`. A consumer reading an object off a queue has
no other way to know which shape it is holding, and "we will add versioning when we need it"
means adding it at the moment two incompatible producers are already in the field.

## What each bump means

| Bump | Change | Consumer impact |
|---|---|---|
| **MAJOR** | a field removed or renamed; a type narrowed; an enum member removed; an optional field made required; the `ids.NAMESPACE` changed | breaks readers; needs a migration entry below and a coordinated deployment |
| **MINOR** | an optional field added; an enum member added; a payload model registered; validation relaxed | old readers keep working, old data keeps validating |
| **PATCH** | descriptions, error-message wording, docs | none |

`version.compatible(written_with, read_by)` accepts the same major, **including a minor from
the future** — a 1.0.0 reader accepts a 1.2.0 object, because MINOR additions are optional by
definition and the alternative is a fleet that stops ingesting the moment one adapter is
upgraded. It refuses a different major outright.

Renaming a field is two releases, never one: add the new name in a MINOR, populate both, then
remove the old one in the next MAJOR. One release that renames is an outage for every consumer
that has not been redeployed in the same hour.

## Changing the schema — the procedure

1. Edit the Pydantic model. It is the single source; the files in `/schemas` are a publication.
2. Bump `version.SCHEMA_VERSION` per the table above.
3. Re-export: `python -m synapse_cdm.schemas --out schemas`. `tests/test_cdm_schemas.py` fails
   the build if you forget, and `--check` is the CI form.
4. Add an entry below, naming the reason — not just the change.
5. Re-run every adapter's golden files and **read the diffs**:
   `python -m synapse_cdm.harness --adapter <name> --fixtures <dir> --update-golden`.
   A golden file updated without being read is how a defect becomes the expectation.
6. If a documented gap in `FORMAT_COVERAGE.md` is now closed, close it there too —
   `tests/test_cdm_format_coverage.py::test_the_documented_gaps_are_still_gaps` fails
   deliberately when a gap field appears, so the document cannot silently disagree with the
   code.

## History

### 1.0.0 — initial contract

The four objects (`Entity`, `Event`, `Track`, `PlanObject`), `Position`, `Kinematics`,
`SourceId`, `SourceRef`, `Integrity`, `TrackSample`, and one registered payload model
(`GnssInterferencePayload` for `GNSS_INTERFERENCE`).

Two decisions in this release depart from the original specification, both because building
the reference adapter surfaced the reason:

- **`source_ids` moved from `Entity` to `CDMBase`**, required on every kind. The harness's
  lossless check found the gap on its first run: a PNTMAP alert whose emitter carries its own
  id produced an entity keyed on the emitter and an event keyed on nothing, so the alert's own
  identifier appeared nowhere in the output. A redelivery could not be recognised as a
  duplicate and an auditor holding the event could not get back to the source record.
- **`signal_strength` became `signal_strength_dbm`.** A bare `signal_strength` has been read
  as dBW, dBm and a 0–100 bar by three different consumers; the unit belongs in the name, as
  it already does in `speed_mps`, `alt_m` and `accuracy_m`.

### Adapters that landed with no schema change

Recorded because "no entry" and "nobody wrote an entry" look identical from here, and the first
is worth stating.

- **`adapters/tak.py` 1.0.0 (Cursor-on-Target, bidirectional)** — implements every row of the
  CoT table in `FORMAT_COVERAGE.md` at **schema_version 1.0.0**, with no field added, removed
  or retyped. Two temptations were declined and are listed below as 1.1.0 candidates instead:
  a canonical home for the CoT callsign, and one for `point/@le`. Both would have been MINOR
  and both would have been added in passing, which is the way a canonical model acquires two
  fields that mean nearly the same thing.

  What it needed instead already existed: `attributes` for the unmapped values, `TRANSFORMS`
  for the nine paths whose value legitimately changes, and `UNKNOWN` as an enum member for the
  three CoT affiliation letters the CDM does not carry.

- **`adapters/ais.py` 1.0.0 (AIS / NMEA 0183 AIVDM, bidirectional)** — message types 1, 2, 3,
  4, 5, 18, 19 and 21, at **schema_version 1.0.0**, with no field added, removed or retyped.

  Three temptations were declined and are listed below as 1.1.0 candidates instead. AIS is the
  format that makes the case for them, because it is the first one where the CDM's silence
  costs something measurable: a vessel's true heading and its course over ground are different
  numbers, and the difference between them is the interesting fact — a vessel making good 095
  while its bow points 070 is being set by wind or current, or is not going where it is
  pointing on purpose. Both land in `attributes` today, under keys only this adapter knows.

  What the CDM had already was enough for everything else, and two existing decisions earned
  their keep here specifically:

  - **`Kinematics`'s docstring was written about AIS's 102.3 sentinel before any AIS adapter
    existed.** Ten of them turned up — position 91/181, speed 102.3, course 360, heading 511,
    rate of turn −128, UTC second 60–63, IMO/ETA/dimension 0, and draught 0.0. The last is the
    one worth naming: it is the only sentinel that is also a plausible reading, so an adapter
    that correctly nulls the other nine can still report that a laden tanker draws nothing.
  - **`source_ids` being a LIST, and living on `CDMBase`.** A type 5 message states an MMSI and
    an IMO number, and they are not alternatives: an MMSI is reassigned when a vessel changes
    flag, an IMO number is fixed for the life of the hull. Both are emitted, under their own
    system names.

  One decision here is worth recording because it looks like a schema gap and is not.
  `Position.accuracy_m` stays null for every AIS fix. AIS states position accuracy as one bit —
  better or worse than 10 m — and writing `10.0` into a 1-sigma metre field would state an
  error nobody measured. The flag is parked. No new field is proposed for it: a threshold and a
  measurement are different kinds of claim, and giving the threshold a numeric home is how it
  would quietly become one.

- **`adapters/adsb.py` 1.0.0 (ADS-B 1090ES, Mode S DF17/DF18, bidirectional)** — type codes
  1-4, 5-8, 0 and 9-18, 19 subtypes 1-4, 20-22, 28 subtype 1 and 31 subtype 0, at
  **schema_version 1.0.0**, with no field added, removed or retyped.

  This is the fourth adapter and the first one whose *silences* cost something structural rather
  than cosmetic, so it adds two gaps to the list below (9, barometric altitude; 10, air-data
  speeds) and sharpens two that were already open. What it did NOT need is worth stating first,
  because three existing decisions carried it:

  - **`Position` requiring both coordinates.** ADS-B states a position as two 17-bit Compact
    Position Reporting values, which are a position *within a zone* and not a position at all.
    Recovering the zone needs either a second frame of the opposite parity or a reference
    position — so a frame this adapter cannot decode has NO position, and the model made that
    unspellable as anything else. A CDM whose Position allowed partial coordinates would have
    invited exactly the guess this format punishes.
  - **`Kinematics` every field optional, absent meaning unknown.** Every ADS-B "not available"
    is a zero in a field that is otherwise offset by one, so the whole family shares one shape
    and the characteristic bug is forgetting the offset — a value one unit wrong and entirely
    plausible. Nine fields carry it, and a vertical rate of 0 meaning "not reported" rather
    than level flight is the one that matters most.
  - **`PositionSource` as a member-bearing enum.** DF18 control fields 2 and 5 are fine-format
    TIS-B: a ground station rebroadcasting a surveillance track it derived by other means.
    ESTIMATED says so; GNSS would promise a fix that survives jamming, which is the dangerous
    direction and the same error as calling an AIS integrated navigation system INERTIAL.

  Two decisions in the adapter itself are recorded here because they look like schema questions
  and are not:

  - **The 24-bit address is filed under system `ICAO24`, not `ADSB`.** It is an ICAO Annex 10
    aircraft address, stable for the airframe and carried identically by Mode S replies, ACAS
    and ASTERIX — so `ids.derive` makes an ADS-B contact and a future radar contact agree on
    one `entity_id` without any coordination, which is the property derived identity exists for.
    `source.system` records the link the copy arrived over. DF18 control fields 1 and 5 state
    that the address is anonymous or self-assigned, and those get `ADSB_NONICAO` instead: a
    wrong join is worse than no join, because it merges two aircraft into one track.
  - **Global CPR even/odd pairing is out of scope, and it is the AIS type 24 argument again.**
    Two frames of opposite parity must be joined on the address across time; an `Adapter` is a
    pure function of one payload, so a global decoder would either emit a half-populated object
    or hold a cache, and a cache in a translator is fusion done where nothing audits it. Type
    24's parts A and B, AIS cross-payload fragment reassembly and CPR pairing are one decision
    made three times. Local decoding IS in scope because its reference position is
    CONFIGURATION — a constructor argument, like the clock — and not state. With no reference
    configured there is no position, so the default is the conservative one.

  Two defects are recorded because the gates that found them are the reason to keep those gates.
  The byte-exact round trip caught a **GNSS altitude being silently dropped** on every frame
  whose CPR could not be decoded: `alt_m` lives on `Position`, `Position` requires a coordinate,
  and an altitude with no horizontal fix therefore had nowhere to go. The adapter now parks the
  figure beside the canonical copy, and the shape of the problem is recorded in the gap 9 note —
  because a Mode C reply states an altitude and no position at all, so the next radar adapter
  meets it immediately.

  The second is the one no gate in this repository could have caught, and it is worth stating for
  that reason. The type code 20-22 altitude field was decoded with the **barometric** arithmetic
  — 25-foot steps behind a Q bit — when it is in fact the plain decimal value of all twelve bits
  in **metres** (mode-s.org, airborne position chapter). Because the fixture was encoded the same
  wrong way, the round trip stayed byte-exact, the goldens agreed with themselves and the lossless
  check passed: the frame simply did not mean what the adapter said, and a real frame carrying
  1039 in that field would have been reported at 24 975 ft instead of 1039 m. Only reading the
  reference found it. The lesson recorded here is the one the airtasking track already states as
  a rule — a field definition is CITED or it is a gap, never inferred from what a magnitude makes
  plausible — and the citation now sits in `FORMAT_COVERAGE.md` beside the row.

- **`adapters/legion.py` 1.0.0 (Picogrid Legion Platform API v3, ingest)** — Entity, Track,
  Entity/Track Location, Locations list and Event, at **schema_version 1.0.0**, with no field
  added, removed or retyped.

  The first adapter whose upstream is a REST API rather than a wire format, and the boundary is
  drawn in the same place: `to_cdm()` takes one already-fetched JSON document and owns no HTTP,
  no auth, no retries and no pagination. Two decisions carried over from the wire formats and one
  is new.

  - **Pagination is framing; correlation is fusion.** One page becomes one `Track`, and the
    adapter never follows `paging.next` — the AIS fragment-buffer argument and the ADS-B CPR
    argument reaching the same conclusion a third time. Four available joins are declined by
    name; what IS read is data the payload already embeds, which is reading and not correlating.
  - **A Legion Track is a CDM `Entity`, not a CDM `Track`.** `GET /v3/entities/{id}` and
    `GET /v3/tracks/{id}` return byte-identical schemas and a track location's foreign key is
    named `entity_id`. The CDM `Track` comes from a Locations LIST instead, which is where the
    history actually lives.
  - **A vendor API needs a pinned spec, and the pin is load-bearing.** Unlike a ratified
    standard, Legion can change between deploys, and its `info.version` demonstrably does not
    move when it does. So `fixtures/legion/spec/openapi_pin.json` records the document's SHA-256
    (which is also its ETag) and a field-by-field inventory, and a test fails the build on a
    field with no row in `FORMAT_COVERAGE.md`.

  What the CDM already had was enough, and three existing decisions earned their keep:

  - **`Position` requiring both coordinates, and `PositionSource` being a real vocabulary.**
    Legion's `crs` defaults to `EPSG:4978` — geocentric X/Y/Z in metres — while its position
    object is shaped like GeoJSON, so an adapter reading `coordinates` as `[lon, lat]` would
    place every contact somewhere impossible while emitting well-formed objects. And its
    location `source` names the SYSTEM that produced a fix, never the method, so
    `position_source` is ESTIMATED with a basis rather than a borrowed GNSS.
  - **`Affiliation` having four members and `SourceRef.synthetic` being separate from them.**
    Legion's enum is fifteen values wide and folds an exercise marking INTO the identity — so
    this is the widest collapse in the document and also a SPLIT, because the CDM already
    separates identity from context. `source.synthetic` is a declaration about the feed and is
    deliberately not rewritten by payload content.
  - **`attributes` accepting anything.** The four vectors Legion sends (`velocity`,
    `acceleration`, `angular_velocity`, a quaternion `orientation`), its 3×3 `covariance` and its
    `speed` all park, because their units and reference frames are documented nowhere and the
    schema's own `speed` and `velocity` examples contradict each other. That is the ADS-B
    altitude lesson applied BEFORE the fact rather than after it.

  Four corrections happened during implementation and all four came from a gate rather than a
  review, which is the note worth keeping: the never-drop check caught the list path pruning
  every sample's metadata; the pinned inventory caught a hand-read claiming six omitted fields
  where the spec says five; a TRANSFORMS audit caught six exemptions with no subject; and the
  harness caught the spec pin being replayed as a payload.

- **`adapters/asterix_cat021.py` 1.0.0 (ASTERIX category 021 ADS-B target reports,
  bidirectional)** — all 42 data items plus the RE and SP fields and the whole Reserved
  Expansion Field, at **schema_version 1.0.0**, with no field added, removed or retyped.

  Pinned to EUROCONTROL-SPEC-0149-12 **Edition 2.6** and its Appendix A Reserved Expansion Field
  **Edition 1.5**, both by SHA-256. Ed 2.6 states on its own cover that it is not backwards
  compatible with Ed 2.1 or earlier, so the edition is part of the mapping and not a footnote.

  Three things this format has that no earlier one did, and each is a decision rather than a
  translation:

  - **Seven time items and not one date.** Every CAT021 time is elapsed time since last
    midnight UTC at 1/128 s. The reference date comes from the injected clock and the instant
    chosen is the one bearing the stated time of day NEAREST the receipt instant — one rule that
    handles both midnight-rollover directions with no special case, and the AIS
    second-of-minute construction generalised. A value at or beyond 86 400 s is REFUSED with the
    raw integer quoted, never taken modulo a day.
  - **A quality vocabulary that needs another item to say what it means.** I021/090's primary
    subfield holds "NUCr or NACv" and "NUCp or NIC", decided by the MOPS version in I021/210 —
    which is optional. Where it is absent the reading is recorded as UNDETERMINED rather than
    guessed. Nothing in that item reaches `Position.accuracy_m` or `Entity.confidence` under
    either reading, PIC included: it states a containment bound in nautical miles and a bound is
    still not a 1-sigma error.
  - **A ground station that has already judged.** Range checks, CPR validation, an independent
    position check and a black-list lookup all arrive as flags. They are carried and never
    re-decided — and `RCF`'s own note in the specification says an operational user will
    SUPPRESS such a target, which this adapter does not: filtering is a decision, and a decision
    made inside a translator is invisible in the CDM output.

  What the CDM already had was enough, and two existing decisions earned their keep. The
  **`ICAO24` source-id namespace** means a CAT021 record and a 1090ES frame of one airframe
  derive the same `entity_id` without the two adapters coordinating — asserted by a fixture that
  carries the ADS-B set's own address. And **`attributes` accepting anything** is what lets the
  wire octets of every item be parked verbatim beside the converted values, which is why
  `TRANSFORMS` is **empty**: a declared transform is an exemption from the never-drop check, and
  this adapter needs none. The harness reports `lossless: PASS` on every parsed twin with
  nothing excused.

  Three gaps opened, each evidenced by something this format states and the CDM cannot hold:
  **13** no per-measurement time (two applicability instants in one record, plus twenty-three
  per-item ages in I021/295), **14** no producing sensor (the ground station is named in every
  single record), and **15** no intent (selected altitudes, trajectory intent, navigation mode —
  the deferral `adsb.py` made at type code 29, which this format does not allow).

  One decision changed during implementation and a gate found it: `from_cdm()` originally took a
  single emittable object, which failed the two-record round trip. A data block holds N records
  and the byte-exact claim is about a BLOCK, so it now emits many Entities as many records in
  block order.

- **`adapters/stanag4676.py` 1.0.0 (STANAG 4676 / AEDP-12 Edition B Version 2 NITS tracks,
  bidirectional)** — the full UML model, 48 classes and 273 attributes, at **schema_version
  1.0.0**, with no field added, removed or retyped.

  Pinned to AEDP-12 **Edition B Version 2** (March 2022) by SHA-256, with the AEDP-12.1
  Implementation Guide and the STANAG 4676 Edition 2 ratification wrapper. Edition A is refused
  by name: §2.1.1.1 says the two editions are incompatible and that the model was re-architected
  "from scratch", so a 2014 feed is a separate adapter rather than a mode.

  Four things this format has that no earlier one did:

  - **A relative time model.** `baseTime` is absolute and every instant is an integer count of
    `relTimeIncrement` seconds from it, so unlike CAT021 there is nothing to reconstruct and the
    injected clock supplies no part of an observation time. But `relTimeIncrement` is a double,
    and 1/128 s and 1/29.97 s — the cases the model exists to serve — are not whole
    milliseconds, so the raw integers are parked and egress re-emits from them.
  - **A mandatory confidentiality label that the CORE MODEL does not mention.** Ed B §2.1.1.6 is
    silent on confidentiality and defers per syntax; Annex B.2 then makes a STANAG 4774
    `originatorConfidentialityLabel` mandatory on the root element. It is carried as the exact
    fragment that arrived — never parsed, never re-serialised — and egress has three paths: the
    park, an explicit deployment-supplied label, or a refusal. This is **gap 12**'s strongest
    evidence and the reason it is no longer "one vendor states a string".
  - **Six coordinate systems, three of which cannot produce a position.** `ECI_J2K` needs daily
    Earth-orientation parameters, `PIXELS` needs a sensor model, and `LOCAL_SPHERICAL` is
    refused because the slot the standard labels *azimuthal* is the argument of `z = r cos phi`
    in its own mandated equations — two conformant producers can fill the array two ways and
    nothing in the data says which. Logged, not guessed: the Legion `EPSG:4979` refusal reached
    from a different direction.
  - **A format that models fusion.** `TrackLinkage`, `ProcessedTrack`, `IDSourceInformation` and
    §2.1.1.2.3's normative consolidation across data streams are all carried and none is
    performed. The consolidation rule is the sharpest case, because the standard *requires* a
    consumer to do it — and a stateful reducer inside a translator is exactly what the adapter
    contract forbids.

  What the CDM already had was enough again, and the same two decisions earned their keep. The
  **`ICAO24` namespace** now serves three adapters: a NITS `IFFCode` in `MODE_S` whose value
  parses as six hex digits derives the same `entity_id` as a 1090ES frame and a CAT021 record.
  And **`attributes` accepting anything** is what holds a 273-attribute model verbatim beside
  the converted values, so `TRANSFORMS` is **empty** and the harness reports `lossless: PASS` on
  every parsed twin with nothing excused.

  Four gaps opened in Phase 1 and all four stand: **16** no per-sample extension, **17** no
  state-vector uncertainty, **18** no confidence provenance and no retraction, **19** no relation
  object. Gap 2 gained two things during implementation: `TRAVELER` and `ZOMBIE` as concrete
  evidence, and a **divergence between three adapters** — `symbology.AFFILIATION_FROM_COT` and
  `legion.AFFILIATION` map JOKER and FAKER to HOSTILE while this adapter maps them to FRIENDLY.
  Stated rather than resolved, on the I021/170 precedent; whoever settles gap 2 settles that.

  Note where an amplification stops: it is READ when the CDM has a member for what it states and
  RECORDED when it does not, so `FAKER` sets FRIENDLY and `ZOMBIE` never downgrades a stated
  identity. Ed B makes the two attributes separate with no co-occurrence restriction, and a
  subordinate field rewriting a primary assertion is the move `essence` is forbidden from making
  against `source.synthetic`.

  `FAKER` "overriding" a contradicting identity is not adjudication: its definition is "Friendly
  track, object or entity acting as exercise hostile", so the identity claim is inside the
  amplification literal and reading it is reading a stated fact. `ZOMBIE`'s definition asserts
  suspicion — the judgement `Affiliation` deliberately lacks a member for — so there is nothing
  to read. **The principle self-terminates**: if `Affiliation` ever grows SUSPECT, `ZOMBIE` and
  `TRAVELER` move from recorded to read by the same rule, and
  `test_the_two_suspect_amplifications_never_yield_friendly` is the tripwire that fires when
  that happens.

  `Position.position_source` is the one canonical field this adapter fills from a resolved
  reference chain rather than a constant: `GNSS` where `TrackSource` resolves in-document to an
  `AIS`, `ADS-B` or `BFT` modality, `ESTIMATED` on every other branch including a DATASTREAM
  reference that resolves to a file we do not have.

  One thing is knowingly incomplete and it is not a gap in the CDM. **The XML element binding is
  provisional**: the normative XSD is distributed through NATO national representatives and
  could not be obtained or hashed, so element names bind to UML attribute names through one
  empty table, `ELEMENT_NAMES`. Every fixture ships as an XML/parsed twin and a test asserts the
  two produce byte-identical CDM, which is what makes the binding checkable — it found four
  defects on its first runs, two in the reader and two in the confidentiality label's handling.

- **`adapters/gmtif.py` 1.0.0 (STANAG 4607 / AEDP-4607 Edition A Version 1 GMTI, bidirectional)**
  — the packet header, the segment header and all ten defined segments, **212 fields**, at
  **schema_version 1.0.0**, with no field added, removed or retyped.

  Pinned to AEDP-4607 **Edition A Version 1** (February 2024) by SHA-256, with AEDP-4607.1 and
  the STANAG 4607 Edition 4 ratification wrapper. Edition 3 is refused by name with `P1` quoted,
  and the reason is not structure: the packet layout is unchanged and what moved is three
  enumeration tables, so an Edition 3 packet decoded here **misclassifies targets with no
  structural symptom** — every length checks out and the targets are the wrong kind of object.
  One adapter with a version-dispatched table is the right shape and Edition 3's tables are not
  pinned here, so earlier editions are deferred rather than best-effort decoded.

  Landed in four commits, reviewable apart: the row set as a specification with every row saying
  `not yet` (`f4a67ec`), seven amendments to it before any code (`9d57732`), the adapter
  (`3d43871`), and six amendments to that (`519ee71`).

  Five things this format has that no earlier one did:

  - **It is the first non-text wire format**, so the Annex C codec is a layer of its own with its
    own suite: seven numeric encodings, two of them **sign-magnitude** rather than two's
    complement and two of them **binary angles** whose signed and unsigned forms differ in
    *both* signedness and exponent. Every one is a place where a wrong answer is a plausible
    number rather than an exception, so `encode(decode(b)) == b` is asserted over every 16-bit
    and 8-bit pattern by exhaustion, and the two strongest cases are the worked examples the
    standard itself prints — `BA16 0101100100011100` = 125.31006° and −34.876099° = `SA16
    1100111001100110`. No `struct` format anywhere: `int.from_bytes(..., "big")` at every call
    site, because an explicit `>` is one typo from the native order.
  - **An existence mask that governs every subsequent field offset**, so one wrong bit
    desynchronises the rest of the segment. That is what grounds the refuse-versus-record split
    on something the code can verify — whether the byte offsets of everything after the problem
    are still known — rather than on a validation annex whose own references name a 2007 edition.
    A reserved or extension segment type is **skip-and-record**: exact, because §3.2.2 gives its
    length, and never silent, because a packet carrying an Advanced Dwell Segment nobody decodes
    would otherwise be indistinguishable from one carrying nothing.
  - **Targets that are detections rather than tracks.** Nothing in the core segments identifies a
    real target: `D32.1` is scoped "within the dwell" by its own definition and Conditional
    besides, `(D2, D3)` does not identify a Dwell Segment, and `D3` wraps. So each target report
    becomes one `Entity` and one `DETECTION` `Event`, the `entity_id` ends in two **positional**
    ordinals whose fragility is stated on the object, and **no target `Track` is ever emitted** —
    the format's own implementation guide sends the reader to the sensor manufacturer for the
    association rule, so a translator may not invent one. The **platform** is the exception and
    the only identity the format guarantees: §3.1.8 makes each nation responsible for its
    platforms being uniquely identified, so `P3` + `P8` is a real `SourceId` and gets the one
    `Track`.
  - **A reference date on the wire, in a different segment from the times it resolves.** The first
    adapter here for which the injected clock supplies no part of a date — `M5`/`M6`/`M7` do —
    and the first that needs stream context it refuses to hold: §3.3 sends the Mission Segment
    "at least once every two minutes", so the date may be in an earlier packet. Three paths, and
    provenance on **every emitted instant** rather than once per packet: the packet's own Mission
    Segment, an explicit caller argument relaying an earlier packet's date, or a refusal. A
    Mission Segment contradicting the caller's argument is a refusal quoting both — neither
    silently wins, because letting the wire win discards a caller statement that may indicate
    mis-tracked stream state and letting the argument persist lets a stale date override the
    place §3.3 puts the answer. The caller's date is a **stand-in for absent wire context and not
    a deployment declaration**, so it gets no protection against the wire.
  - **Two payload declarations of whether the data are real, one boolean, and neither writes it.**
    `P7` Exercise Indicator is Mandatory on **every** packet and says real, simulated or
    synthesized in as many words; `D32.10`'s upper half says it per target. Neither touches
    `source.synthetic` **in any direction, agreement included** — a rule that let a payload field
    set a deployment declaration whenever the two matched would bind only on disagreement, which
    is a default with a conflict check bolted on. Three branches: pure-simulated against a real
    declaration refuses, pure-real against a synthetic one refuses, and `synthesized` — "a mix of
    real and simulated data", §3.1.7 — contradicts neither pure declaration and **parks visibly
    without a refusal**, because refusing would reject the case §3.1.7 exists to describe. A
    simulated target inside a purely-real packet is a **separate** refusal, payload against
    payload, naming `P7 = 2` as the value the packet needed.

  **The `D32.10` mapping is a lookup and never arithmetic, and `FACILITY` appears nowhere.**
  Eighteen of the forty-three named classifications map, every one of them to `PLATFORM`; the
  rest park as `UNKNOWN` with the standard's wording. `128 + n` mirrors `n` for n = 0…13 and for
  no other n — 144–148 mirror 14–18 at an offset of **+130**, so an arithmetic decoder reads
  Clutter-Simulated as Ground-Rotator-Live. The rotator classes park rather than becoming
  `FACILITY`: they name a Doppler signature class, and reading an installation off a motion
  characteristic is the inference this adapter already refuses for `M3` Platform Type. The
  **tagging-device exemption is keyed on the LABEL** and not on a value, because the label has
  been carried by 140, then 143, then 142 across three editions.

  What the CDM already had was enough again, and one thing it did not have is now written down.
  **`attributes` accepting anything** is what holds the whole decoded packet verbatim beside the
  converted values, so `TRANSFORMS` is **empty** and the harness reports `lossless: PASS` on every
  parsed twin with nothing excused — and it is also what makes the **byte-exact round trip**
  structural rather than hopeful, because egress re-encodes from the park. Sixteen binary twins,
  32 files, 32 goldens; `roundtrip` reports SKIP on both halves of every twin because `from_cdm()`
  returns binary and the harness compares structures, so the byte-exact claim is the adapter's own
  test and is a stronger claim than the harness could make.

  **Four gaps opened, 20 to 23**, and each has its assertion in the gap test:

  - **20 — no detection-versus-track distinction.** An `Entity` says *this exists* and a `Track`
    says *where it has been*; neither says *a radar returned energy from this point at this
    instant and nothing before or after is claimed*. It is why `Entity.valid_to` has no honest
    value here, why the key ends in positional ordinals, and why twenty-five of `D32.10`'s
    classifications have no honest `EntityType` — `Clutter` and `Phantom` being *explicit denials
    that anything is there*. The gap now also carries **two stated divergences**: a person maps
    `UNKNOWN` here and `PLATFORM` in the shipped CAT021 adapter, and a detection's fix lives in
    `Event.geometry` here and in `stanag4676.py` while `asterix_cat021.py` and `adsb.py` leave it
    `None`. Both are 1.1.0 questions with both arguments written down, on the I021/170 precedent.
  - **21 — no home for a radar measurable**, and specifically no way to state **one component** of
    a velocity. `D32.7` is the radial component and the tangential part is physically
    unobservable to a single-look MTI radar, so a target's `Kinematics` is `None` and the radial
    value is not a speed. Explicitly **not** gap 4: a component is a projection, not a vector with
    elements missing. Plus SNR, RCS, classification probability, MDV and electrical length.
  - **22 — no negative information.** Stated by the format's own guide — "the fact that the radar
    has looked at a particular area and found no targets can be just as important as receiving
    targets in an area" — and built into the standard, which requires a Dwell Segment "even if no
    targets are observed". The CDM renders "not looked at", "looked at and empty", "looked at with
    an MDV of 3 m/s" and "targets found and then filtered out" identically, as empty space.
  - **23 — no way to carry an observation whose source states no time.** Three GMTIF segments have
    no time field in their layout at all — Free Text, Processing History, and an HRR segment whose
    `H2`/`H3` name a dwell in another packet — and `Event.observed_at` is required and documented
    "Never receipt time". The adapter substitutes the receipt instant and labels it in
    `payload.observed_at_basis`, which is the least bad of three bad answers and **still a
    violation of the field's documented meaning on three object kinds**. Two 1.1.0 proposals: make
    `observed_at` optional so an absence can be an absence, or add a typed, mandatory basis field
    beside it. **The `models.Event.observed_at` docstring amendment rides the same release**,
    because its wording is part of the v1.0.0 contract.

  **Three ambiguities were found by implementing rather than by reading**, which is the split
  worth noticing — a contradiction in a byte-range column and a contradiction between two "shall"
  statements are both invisible until something has to obey both. **15**: `H15`'s value range
  restates `B16`'s maximum for a `B32` field and its stated minimum is 2⁻²² where the encoding's
  LSB is 2⁻²³, so Annex C-4.5 is followed and the range column is not enforced. **16**: §3.1.10
  requires `P10 = 0` with no dwell data and §3.7.1 gives `J1` a floor of 1, so a literal
  `J1 == P10` cross-check makes a Job-Definition-only packet — which the guide's own Figure 2-1
  draws — impossible to represent; the row set's rule was narrowed to §3.1.10's own condition
  rather than the packet refused. **17**: §3.5.6 and §3.5.7 both end "Either H6 or H7 or both must
  be reported", so a sparse chip may carry both with the two disagreeing about how many scatterer
  records follow, and nothing says which governs — which is the written justification for bounding
  the array by `S2` and parking it whole rather than adjudicating between two "must be reported"
  fields on a conformant packet.

  One defect is on the record because a review asked the right question of it. `codec.snap`, which
  quantises a CDM-native position to a field's own resolution on egress, originally **masked** the
  encoded integer to the field's width — so `snap("SA32", 95.0)` returned **−85.0**, a latitude on
  the other side of the equator, and `snap("B16", 300.0)` returned −44.0. Clamping to the boundary
  would have been less bad and still silent. Quantising inside a field's range is the format's
  stated resolution being applied; moving a value **into** range is not, and an out-of-range value
  is now a refusal quoting the value and the range.

## Proposed for 1.1.0 (MINOR — not yet implemented)

Both come from `FORMAT_COVERAGE.md`'s gap list, and both are deliberately deferred rather than
added in passing. **Both are now confirmed by a shipped adapter** rather than anticipated — the
TAK adapter parks a real value for each of them on every fixture it translates, which is the
evidence that was missing when they were first written down:

- **`Entity.label`** — a canonical human-readable name. A CoT callsign and a STANAG 4676 track
  number are the strings an operator reads, and today they land in `attributes`, so every
  consumer that wants to label a contact needs private knowledge of which adapter's key to
  look under. Deferred because it needs one owner naming its precedence rules across sources.
- **`Position.alt_accuracy_m`** — vertical accuracy. `accuracy_m` is horizontal only, so CoT's
  `@le` has no home. It matters for air tracks, where a 300 m vertical error decides whether
  two aircraft are deconflicted — and the TAK adapter's `air_track_due_north` fixture is
  exactly that case: `le="120.0"` on a track at 7 620 m, parked at `attributes.vertical_error_m`
  where no consumer will look for it.

- **`Kinematics.heading_deg` and `Kinematics.turn_rate_dpm`**, together and with one owner —
  `FORMAT_COVERAGE.md` gap 7. AIS carries course over ground, true heading and rate of turn as
  three separate measurements; the CDM carries the first and parks the other two. They are
  proposed as a pair because they answer one question between them — where will this be next —
  and a gap opened twice for one concept gets closed twice differently. Whoever implements it
  inherits two sentinels: heading 511 means not available, and rate of turn ±127 means "faster
  than 5° per 30 s", which is a floor, so a `turn_rate_dpm` of 127 would be a fabricated
  measurement rather than a large one.

  **ADS-B is the third adapter to park a heading, and it changes the proposal rather than
  merely confirming it.** An ADS-B heading is referenced to MAGNETIC north unless a type code 31
  frame's HRD bit says otherwise; an AIS true heading is referenced to true north. A bare
  `heading_deg` would hold two different measurements under one name, and magnetic variation in
  the Baltic is around 8° east and a function of place and date — enough to swamp the bow-against-
  track discrepancy the field exists to expose. So the pair becomes a pair plus a datum, and
  whoever implements it inherits a cross-frame join as well: ADS-B cannot state the datum in the
  same frame as the heading.

- **`Track.attributes`** — an extension bag on `Track`, the one canonical object without one.
  `Entity` has `attributes` and `Event` has `payload`; `Track` has `track_id`, `entity_id`,
  `samples` and `track_quality` and nowhere to park anything. The Legion adapter is what makes
  this concrete: a `Track` built from one page of a paginated history is a FRAGMENT, and how much
  of the history it holds — `total_count` against the carried sample count — has to be
  machine-readable or a consumer will compute a speed across a gap it does not know is there.
  Today those figures ride on the `Entity` the track belongs to, keyed by `track_id`, so a
  consumer holding both objects can read them and one holding only the `Track` cannot. The three
  alternatives were all worse: `track_quality` is a 0..1 assessment of how good a track is rather
  than how complete it is, truncating `samples` would discard real data to express a caveat, and
  the model is `extra="forbid"` by design. Whoever adds it should decide at the same time whether
  a *typed* completeness block is better than a free bag, since "how much of this is here" is a
  question every paginated source will ask.
- **`Position.baro_alt_m`** (or `Entity.baro_alt_m` — the choice is part of the work) —
  `FORMAT_COVERAGE.md` gap 9, and the strongest-evidenced of these. `Position.alt_m` is
  documented as metres above the WGS84 ellipsoid, which is what an ADS-B type code 20-22 frame
  states. Type codes 9-18 — the overwhelming majority of an air picture — state a *pressure*
  altitude against the 1013.25 hPa datum instead, and the two differ by hundreds of metres in
  ordinary weather. Every one of them is parked today, so the CDM carries no altitude at all for
  most air tracks, and deconfliction, airspace checks and any comparison against terrain all
  read one. Three things belong in the same change: ADS-B's GNSS-barometric difference field is
  exactly the offset relating the two altitudes; the decision about WHERE the field hangs is
  load-bearing — on `Position` it inherits the requirement of a coordinate, which leaves an
  altitude with no horizontal fix homeless, and this format produces that case constantly; and
  **the datum has to be carried rather than assumed**. `alt_m` says "above the ellipsoid", but a
  DO-260 version 0 transmitter broadcasts GNSS height against mean sea level and DO-260A/B
  against the ellipsoid, with the version living in a different frame. That is gap 7's
  magnetic-versus-true problem in the vertical, and the geoid separation is tens of metres, so it
  is not a rounding matter. The ADS-B adapter asserts the DO-260A/B reading and names both in
  `attributes.altitude_type`; a canonical field would have to do better than assert.

Two gaps are recorded in `FORMAT_COVERAGE.md` and deliberately NOT proposed as fields here.
A gap with no proposal is a decision too, and in both cases the decision is "not yet understood
well enough to name a field for":

- **Gap 8, extent.** AIS states four dimensions from the position reference point plus a
  draught, and all of it is parked; but a bounding extent, an offset reference point and a
  draught are three different ideas, and STANAG 4676's own object-size fields should be read
  before any of them is added.
- **Gap 10, air-data speeds.** `Kinematics.speed_mps` is a speed over the ground — what AIS's
  SOG means and what an ADS-B type 19 subtype 1/2 frame states. Subtypes 3 and 4 state an
  indicated or true airspeed instead, and the difference between airspeed and ground speed is
  the wind, which is the fact worth having. It is parked and `speed_mps` is left null on those
  frames rather than filled with a number every consumer would read as a ground speed. Not
  proposed because indicated airspeed, true airspeed and Mach are three related-but-distinct
  quantities and a consumer that wants wind needs gap 7 and its datum as well: adding one
  `airspeed_mps` now would close a third of a question.

None of these is a blocker for an adapter, and that is the point of writing them down rather
than adding them: `attributes` keeps the value, so the cost of the delay is private knowledge in
consumers rather than lost data. When one lands, `tests/test_cdm_format_coverage.py::
test_the_documented_gaps_are_still_gaps` fails deliberately until the document is closed with
it — the gap cannot be fixed in code and left open in the prose.
