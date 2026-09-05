"""MISB ST 0902.8's Motion Imagery Sensor Minimum Metadata Set, transcribed, and read per packet.

**THIS MODULE EMITS AN ADVISORY AND NEVER A REFUSAL.** ST 0902.8 is a *profile* of MISB ST 0601 —
§6: "The MISMMS is a Local Set profile of MISB ST 0601 with all items mandatory unless
conditionally dependent. Thus, it uses the ST 0601 Universal Label." — so a packet that omits a
minimum item is a packet of the same Local Set, decodable by the same codec, and translating it is
not in question. What is in question is whether the STREAM conforms, and that is a different
subject from whether a PACKET decodes. `klv_security_codec`'s element precedent and
`klv_uas_codec.LENGTH_DIVERGENCE_POLICY` both refuse to discard well-formed data over a rule about
what should have accompanied it; this module is the third application of that ruling and the first
where the rule being read is about a whole stream.

THE DOCUMENT ITSELF FORBIDS THE PER-PACKET READING AS A CONFORMANCE VERDICT
--------------------------------------------------------------------------
This is the fact that decides the shape of everything below, and it is stated twice:

* `ST 0902.3-04` — "All metadata items contained in the MISMMS shall be reported no less than once
  every thirty (30) seconds under all circumstances." The obligation is a REPORTING RATE over
  time, not a per-packet content rule.
* Annex A, the Note under the recommendation summary — "It is not mandatory that each metadata
  packet contain every metadata item; Annex B demonstrates the viability of transmitting the
  MISMMS in a bandwidth-constrained environment. Given enough bandwidth other metadata packet
  configurations (e.g. more packets each containing fewer items) are permissible."

So a per-packet absence is **not** a defect and this module never calls it one. What it emits is a
reading: which minimum items this packet carried and which it did not. A consumer aggregating
those readings across thirty seconds of packets can answer the document's actual question; one
reading cannot, and an annotation that implied otherwise would be stating a conformance verdict
the document does not support. `PER_PACKET_IS_NOT_A_VERDICT` says so on every annotation.

THE THREE STATES, AND WHY "ABSENT" AND "NOT DECODED" ARE NOT THE SAME
---------------------------------------------------------------------
A tag can be missing from this adapter's *output* for two unrelated reasons, and collapsing them
would make the annotation a statement about this repository dressed as a statement about the
stream:

* **absent** — the packet's octets carry no such tag. The framing layer walks EVERY triplet of the
  Local Set, including tags no item table here covers (`ST 0107.3-04`, quoted at
  `klv_uas_codec.DecodedPacket`), so this is a true reading about the wire for every tag in the
  minimum set — including the five this adapter cannot decode.
* **present_not_decoded** — the tag IS on the wire, with octets, and `klv_uas_codec` has no block
  for it. `NOT_DECODED_BY_THIS_ADAPTER` names all five. The item was reported; this repository
  cannot say what it says.
* **zero_length** — the tag is on the wire with a length of zero. `ST 0902.8-05`: "No Zero-Length
  items (ZLI) shall be used to meet minimum reporting requirements." A ZLI is the producer saying
  the value is unknown, which the document declines to accept as reporting — so a ZLI is counted
  as NOT reported here while remaining a decoded item everywhere else in this adapter.

`present` is the fourth and it is the ordinary one.
"""

from __future__ import annotations

from typing import NamedTuple

from . import klv_security_codec as security
from . import klv_uas_codec as uas

#: The document this module transcribes, named the way every other pinned document is named here.
SOURCE_ST_0902_8 = (
    "MISB ST 0902.8, Motion Imagery Sensor Minimum Metadata Set, 1 November 2018 — "
    "fixtures/klv/spec/ST0902.8.pdf, pinned at klv_pin.json "
    "delegated_specifications_held.st_0902_8. MISP-2019.1 Appendix B reference [73] reads "
    "'MISB ST 0902.8 Motion Imagery Sensor Minimum Metadata Set, Nov 2018.', and §4.4.4 of the "
    "profile calls the set 'a prerequisite for MISP conformance'"
)

#: The clause that makes this an advisory rather than a refusal, quoted rather than paraphrased.
PER_PACKET_IS_NOT_A_VERDICT = (
    "A PER-PACKET READING IS NOT A CONFORMANCE VERDICT AND THIS ANNOTATION IS NOT ONE. "
    "ST 0902.3-04 states the obligation as a rate — 'All metadata items contained in the MISMMS "
    "shall be reported no less than once every thirty (30) seconds under all circumstances' — and "
    "ST 0902.8's Annex A states the converse directly: 'It is not mandatory that each metadata "
    "packet contain every metadata item'. So `absent` here means THIS PACKET DID NOT CARRY IT and "
    "never 'the stream does not conform'. The question the document asks is answered by "
    "aggregating these readings over thirty seconds of packets, which is a consumer's arithmetic "
    "and not this adapter's"
)

#: `ST 0902.8-05`, the requirement this edition added, and the reason a ZLI is not `present`.
ZERO_LENGTH_DOES_NOT_REPORT = (
    "ST 0902.8-05: 'No Zero-Length items (ZLI) shall be used to meet minimum reporting "
    "requirements.' A ZLI is ST 0601.14's explicit unknown and this adapter decodes it as one "
    "everywhere else — see klv_uas_codec.ZeroLength — so the item is READ and is not COUNTED. "
    "The requirement is new in this edition: ST 0902.8's Revision History row reads 'Added "
    "Requirement -05'"
)

#: Note 1 on page 3, verbatim, because it is what makes an alternates row satisfiable by any one
#: of its members and it carries its own exception.
INCLUSIVE_OR_NOTE = (
    "Note 1: 'Platform Pitch Angle (Tag 6 | 90), Platform Roll Angle (Tag 7 | 91), Sensor True "
    "Altitude as MSL (Tag 15) | Sensor Ellipsoid Height as HAE (Tag 75) | Sensor Ellipsoid Height "
    "Extended as HAE (Tag 104), Frame Center Elevation as MSL (Tag 25) | Frame Center Height "
    "Above Ellipsoid (Tag 78), and Target Width (Tag 22) | Target Width Extended (Tag 96) are "
    "governed by an “inclusive or” within MISB ST 0601 with one exception.  The use of "
    "Tag 75 and Tag 104 is governed by an “exclusive OR.”' — so a row with alternates is "
    "reported when ANY of its members is, and the 15|75|104 row carries the one place the "
    "document narrows that: 75 and 104 together are the exception, which this module records at "
    "`exclusive_or_violation` and does not refuse"
)

#: The five requirements, contiguous `-01` through `-05` and spelled with TWO edition prefixes.
#: The `st_0107_3` finding a third time: a requirement identifier names the edition that
#: INTRODUCED the requirement, not the edition printing it, so an ID in a 0902.8 document may read
#: `ST 0902.3-`. Four do; only `-05`, added by this edition, reads `ST 0902.8-`.
REQUIREMENTS = {
    "ST 0902.3-01": "All metadata shall be expressed in accordance with MISB ST 0107 [3].",
    "ST 0902.3-02": (
        "DEPRECATED, §7. 'The MISMMS shall use MISB ST 0601 [1] Local Set 16-byte Universal Key "
        "(06.0E.2B.34.02.0B.01.01.0E.01.03.01.01.00.00.00 (CRC 56773)) for its implementation.' "
        "§7 gives the reason: 'Requirement -02 was removed as per recent MISB practices where "
        "Universal Keys are defined within a dictionary and thus not considered requirements.'"),
    "ST 0902.3-03": (
        "The items of the MISMMS as defined in MISB ST 0902 Table 1 shall be populated in "
        "accordance with MISB ST 0601 requirements."),
    "ST 0902.3-04": (
        "All metadata items contained in the MISMMS shall be reported no less than once every "
        "thirty (30) seconds under all circumstances."),
    "ST 0902.8-05": (
        "No Zero-Length items (ZLI) shall be used to meet minimum reporting requirements."),
}

#: The Universal Label §6 states for the set, and it is ST 0601's own — the MISMMS adds no key.
LOCAL_SET_KEY = "06.0E.2B.34.02.0B.01.01.0E.01.03.01.01.00.00.00"
LOCAL_SET_KEY_CRC = 56773


class MismmsRow(NamedTuple):
    """One row of ST 0902.8 Table 1, transcribed cell by cell.

    `tags` is a tuple because five rows name alternatives with a `|` in the Tag cell, and the
    names, types and lengths are tuples of the same arity for exactly those rows. `security_set`
    marks the nine rows whose Tag cell reads `48/n`: those are elements of the ST 0102.12 set
    nested at ST 0601 item 48, not top-level ST 0601 items, and they are looked up in a different
    place.
    """

    tags: tuple[int, ...]
    names: tuple[str, ...]
    range_and_units: str
    klv_types: tuple[str, ...]
    lengths: tuple[str, ...]
    #: Table 2's `Max Length (Bytes)` cell. A `*` in the document marks a length ST 0102 states
    #: as a maximum rather than a fixed size; it is kept as printed.
    max_lengths: tuple[str, ...]
    #: Table 2's `Rec Update Interval` cell — `Fast` or `10 s`. Informative (Annex A is titled
    #: "Informative"), carried because it is the document's own answer to "how often".
    recommended_interval: str
    security_set: bool = False

    @property
    def key(self) -> str:
        """The row's label as the document's Tag cell prints it: `13`, `6|90`, `48/1`."""
        if self.security_set:
            return f"48/{self.tags[0]}"
        return "|".join(str(tag) for tag in self.tags)


def _row(tags, names, range_and_units, types, lengths, max_lengths, interval, *,
         security_set=False) -> MismmsRow:
    return MismmsRow(
        tags=tuple(tags), names=tuple(names), range_and_units=range_and_units,
        klv_types=tuple(types), lengths=tuple(lengths), max_lengths=tuple(max_lengths),
        recommended_interval=interval, security_set=security_set)


#: **ST 0902.8 Table 1, "Summary of MISMMS Items", in the document's own row order**, with Table
#: 2's two columns merged onto each row. THE TWO TABLES DRAW THE SAME 33 ROWS in the same order —
#: that is the cross-check `ROW_COUNT`, `TAG_COUNT` and `TABLE_2_TOTAL_MAX_BYTES` exist to make
#: re-derivable, and `tests/test_cdm_mismms.py` re-derives all three from this tuple.
ROWS: tuple[MismmsRow, ...] = (
    _row([1], ["Checksum"], "None", ["uint16"], ["2"], ["2"], "Fast"),
    _row([2], ["Precision Time Stamp"], "Microseconds", ["uint64"], ["8"], ["8"], "Fast"),
    _row([3], ["Mission ID"], "None", ["ISO 646"], ["variable"], ["127"], "10 s"),
    _row([5], ["Platform Heading Angle"], "0-360 Degrees", ["uint16"], ["2"], ["2"], "Fast"),
    _row([6, 90], ["Platform Pitch Angle (Short)", "Platform Pitch Angle (Full)"],
         "+/- 20 Degrees / +/- 90 Degrees", ["int16", "int32"], ["2", "4"], ["2", "4"], "Fast"),
    _row([7, 91], ["Platform Roll Angle (Short)", "Platform Roll Angle (Full)"],
         "+/- 50 Degrees / +/- 90 Degrees", ["int16", "int32"], ["2", "4"], ["2", "4"], "Fast"),
    _row([10], ["Platform Designation"], "None", ["ISO 646"], ["variable"], ["127"], "10 s"),
    _row([11], ["Image Source Sensor"], "None", ["ISO 646"], ["variable"], ["127"], "10 s"),
    _row([12], ["Image Coordinate System"], "None", ["ISO 646"], ["variable"], ["127"], "10 s"),
    _row([13], ["Sensor Latitude"], "+/- 90 Degrees", ["int32"], ["4"], ["4"], "Fast"),
    _row([14], ["Sensor Longitude"], "+/- 180 Degrees", ["int32"], ["4"], ["4"], "Fast"),
    _row([15, 75, 104],
         ["Sensor True Altitude (MSL)", "Sensor Ellipsoid Height (HAE)",
          "Sensor Ellipsoid Height Extended (HAE)"],
         "-900 to 19000m / -900 to 19000m / -900 to 40000m",
         ["uint16", "uint16", "IMAPB"], ["2", "2", "2"], ["2", "2", "2"], "Fast"),
    _row([16], ["Sensor Horizontal FoV"], "0 to 180 Degrees", ["uint16"], ["2"], ["2"], "Fast"),
    _row([17], ["Sensor Vertical FoV"], "0 to 180 Degrees", ["uint16"], ["2"], ["2"], "Fast"),
    _row([18], ["Sensor Relative Azimuth Angle"], "0 to 360 Degrees", ["uint32"], ["4"], ["4"],
         "Fast"),
    _row([19], ["Sensor Relative Elevation Angle"], "+/- 180 Degrees", ["int32"], ["4"], ["4"],
         "Fast"),
    _row([20], ["Sensor Relative Roll Angle"], "0 to 360 Degrees", ["uint32"], ["4"], ["4"],
         "Fast"),
    _row([21], ["Slant Range"], "0 to 5000000 m", ["uint32"], ["4"], ["4"], "Fast"),
    _row([22, 96], ["Target Width", "Target Width Extended"],
         "0 to 10000 m / 0 to 1500000 m", ["uint16", "IMAPB"], ["2", "3"], ["2", "3"], "Fast"),
    _row([23], ["Frame Center Latitude"], "+/- 90 Degrees", ["int32"], ["4"], ["4"], "Fast"),
    _row([24], ["Frame Center Longitude"], "+/- 180 Degrees", ["int32"], ["4"], ["4"], "Fast"),
    _row([25, 78], ["Frame Center Elevation (MSL)", "Frame Center Height Above Ellipsoid (HAE)"],
         "-900 to 19000 m", ["uint16", "uint16"], ["2", "2"], ["2", "2"], "Fast"),
    _row([1], ["Security Classification"], "Look Up Table", ["uint8"], ["1"], ["1"], "10 s",
         security_set=True),
    _row([2], ["Classifying Country & Releasing Instructions Country Coding Method"],
         "Look Up Table", ["uint8"], ["1"], ["1"], "10 s", security_set=True),
    _row([3], ["Classifying Country"], "None", ["ISO 646"], ["variable"], ["6*"], "10 s",
         security_set=True),
    _row([4], ["Security-SCI/SHI Information"], "None", ["ISO 646"], ["variable"], ["40*"],
         "10 s", security_set=True),
    _row([5], ["Caveats"], "None", ["ISO 646"], ["variable"], ["32*"], "10 s", security_set=True),
    _row([6], ["Releasing Instructions"], "None", ["ISO 646"], ["variable"], ["40*"], "10 s",
         security_set=True),
    _row([12], ["Object Country Coding Method"], "Look Up Table", ["uint8"], ["1"], ["1"], "10 s",
         security_set=True),
    _row([13], ["Object Country Codes"], "None", ["UTF-16"], ["variable"], ["40*"], "10 s",
         security_set=True),
    _row([22], ["Security Metadata Version"], "Integer", ["uint16"], ["2"], ["2"], "10 s",
         security_set=True),
    _row([65], ["UAS Local Set Version"], "Integer", ["uint8"], ["1"], ["1"], "Fast"),
    _row([94], ["Motion Imagery Core Identifier"], "None", ["binary"], ["50"], ["50"], "10 s"),
)

#: The three figures the document states about its own tables, held here so the transcription can
#: be checked against them rather than against itself. Table 2's footer row reads
#: **"39 Tags  Total 797"** — 39 tag numbers across 33 rows, and 797 is the sum of the Max Length
#: column. All three are re-derived from `ROWS` in `tests/test_cdm_mismms.py`.
ROW_COUNT = 33
TAG_COUNT = 39
TABLE_2_TOTAL_MAX_BYTES = 797

#: The Annex A recommendation summary, verbatim, because it is the document's own grouping of the
#: 33 rows into two rates and the `recommended_interval` cells are derived from the same sentence.
ANNEX_A_SUMMARY = (
    "'1. Include Tags 3, 10, 11, 12, 48 sub-tags & 94 once every 10 seconds. 2. Include all other "
    "items as often as possible, within the available bandwidth and up to the frame rate.' Annex "
    "A is titled 'Informative' and this module carries it as guidance, never as a rule a packet "
    "can fail"
)

#: The MISMMS top-level tags `klv_uas_codec` has no block for. DERIVED at import from the codec's
#: own two tables rather than typed, so it cannot go stale when a tag is wired: `ITEMS` is the 26
#: the pinned stream attests and `DOCUMENT_WITNESSED_TAGS` the 18 a printed example does, 44
#: together. Item 48 is a nested set and item 94 a delegated pack, each decoded by its own module,
#: so both are decodable and neither is in either table.
_DECODABLE_TOP_LEVEL = (
    set(uas.ITEMS) | set(uas.DOCUMENT_WITNESSED_TAGS)
    | set(uas.NESTED_SETS) | {uas.CORE_IDENTIFIER_TAG})
NOT_DECODED_BY_THIS_ADAPTER = tuple(sorted(
    tag for row in ROWS if not row.security_set
    for tag in row.tags if tag not in _DECODABLE_TOP_LEVEL))

NOT_DECODED_BASIS = (
    "The minimum set names five ST 0601 items this adapter's tag tables do not cover — 3 Mission "
    "ID, 10 Platform Designation, 78 Frame Center Height Above Ellipsoid, 90 Platform Pitch Angle "
    "(Full) and 91 Platform Roll Angle (Full). THIS IS A FACT ABOUT THIS REPOSITORY AND NOT ABOUT "
    "THE STREAM, which is why `present_not_decoded` is a state of its own: the framing layer walks "
    "every triplet in the Local Set under ST 0107.3-04, so whether the tag was on the wire is "
    "always readable and only its VALUE is out of reach. Reporting either state as the other "
    "would let a gap in this repository read as a gap in a producer's stream"
)

#: What a member carries when `klv_uas_codec`'s length policy skipped it. WITNESSED ON THE ONLY
#: STREAM HELD: `day_flight.klv`'s tag 22 arrives at four octets where §8.22 requires two, so all
#: six packets skip it as a `required_length` divergence — and row `22|96` still reads `reported`,
#: because the producer DID report Target Width and the question ST 0902.3-04 asks is whether it
#: was reported. Whether it was reported CORRECTLY is ST 0902.3-03's question — "The items of the
#: MISMMS as defined in MISB ST 0902 Table 1 shall be populated in accordance with MISB ST 0601
#: requirements" — and this module records the divergence beside the presence rather than letting
#: one verdict stand for both.
LENGTH_POLICY_NOTE = (
    "this item is on the wire and klv_uas_codec's length policy skipped it, so it is REPORTED for "
    "ST 0902.3-04's purposes and its VALUE was not decoded. ST 0902.3-03 asks the second question "
    "— whether the item is populated per ST 0601 — and this annotation records the divergence "
    "rather than answering it. See klv_uas_codec.LENGTH_DIVERGENCE_POLICY"
)

#: The two states a reader must not conflate, named so a consumer can key on them.
STATE_PRESENT = "present"
STATE_PRESENT_NOT_DECODED = "present_not_decoded"
STATE_ZERO_LENGTH = "zero_length"
STATE_ABSENT = "absent"

#: A row is `reported` when any of its members is `present` or `present_not_decoded` — Note 1's
#: inclusive or. `not_reported` covers every other case and names why.
ROW_REPORTED = "reported"
ROW_NOT_REPORTED = "not_reported"


def _tag_state(tag: int, octets: str | None, *, security_set: bool) -> str:
    """One member's state. `security_set` is not a convenience — it is the whole of the lookup.

    **THE TWO TAG NUMBER SPACES COLLIDE AND ONE OF THE COLLISIONS IS LIVE.** `NOT_DECODED_BY_THIS_
    ADAPTER` numbers ST 0601 items and `48/3` numbers an ST 0102.12 element, so an unqualified
    membership test reads MISMMS row `48/3` Classifying Country — which `klv_security_codec`
    decodes, and which every complete fixture here carries — as ST 0601 tag 3 Mission ID, which it
    does not. Caught on the full-minimum-set fixture, where `48/3` reported `present_not_decoded`
    beside a decoded value. Every one of the nine security rows is inside `ELEMENTS`, so a member
    of the nested set is never `present_not_decoded`.
    """
    if octets is None:
        return STATE_ABSENT
    if len(octets) == 0:
        return STATE_ZERO_LENGTH
    if not security_set and tag in NOT_DECODED_BY_THIS_ADAPTER:
        return STATE_PRESENT_NOT_DECODED
    return STATE_PRESENT


def read_packet(packet: uas.DecodedPacket) -> dict:
    """One packet read against ST 0902.8 Table 1. **A reading, never a verdict.**

    Presence is taken from the packet's raw octet map rather than from its decoded items, for the
    reason `NOT_DECODED_BASIS` gives: `klv_uas_codec` parks the octets of every triplet it walks,
    including the five minimum-set tags it has no block for, so the wire question is answerable
    for all 39 tags while the value question is answerable for 34.
    """
    top = packet.raw_items
    elements = packet.security.raw_elements if packet.security is not None else None
    # Tags the length policy SKIPPED. They are on the wire and they are not in `packet.items`, so
    # a reading taken from the octets calls them reported and a reading taken from the decoded
    # items would call them absent. BOTH FACTS ARE CARRIED AND NEITHER IS FOLDED INTO THE OTHER,
    # for `NOT_DECODED_BASIS`'s reason: presence is what ST 0902.3-04 asks about and is what the
    # row state answers, while whether the item was populated per ST 0601 is ST 0902.3-03's
    # separate question, which this module records and does not adjudicate.
    skipped = {defect.tag: defect.divergence_class for defect in packet.defects}

    rows: dict[str, dict] = {}
    reported = 0
    for row in ROWS:
        members = {}
        for index, tag in enumerate(row.tags):
            if row.security_set:
                octets = None if elements is None else elements.get(tag)
            else:
                octets = top.get(tag)
            member = {
                "name": row.names[index],
                "state": _tag_state(tag, octets, security_set=row.security_set),
                "octet_length": None if octets is None else len(octets) // 2,
            }
            if not row.security_set and tag in skipped:
                member["length_policy_skipped"] = skipped[tag]
                member["length_policy_note"] = LENGTH_POLICY_NOTE
            members[str(tag)] = member
        states = {member["state"] for member in members.values()}
        row_reported = bool(states & {STATE_PRESENT, STATE_PRESENT_NOT_DECODED})
        reported += row_reported
        entry = {
            "state": ROW_REPORTED if row_reported else ROW_NOT_REPORTED,
            "tags": members,
            "recommended_interval": row.recommended_interval,
        }
        if not row_reported and STATE_ZERO_LENGTH in states:
            entry["not_reported_because"] = ZERO_LENGTH_DOES_NOT_REPORT
        if row.security_set and elements is None:
            entry["not_reported_because"] = security.ABSENCE_OF_SETS
        if len(row.tags) > 1:
            entry["alternates_basis"] = INCLUSIVE_OR_NOTE
        rows[row.key] = entry

    # The one narrowing Note 1 makes on its own rule, recorded and NOT refused: 75 and 104 are an
    # exclusive OR, so a packet carrying both has broken a rule of ST 0601 that this document
    # restates. It is carried as a named observation on the row for a consumer to act on.
    both_hae = {tag for tag in (75, 104) if top.get(tag)}
    exclusive_or_violation = sorted(both_hae) if len(both_hae) == 2 else None

    return {
        "profile": "MISB ST 0902.8 Motion Imagery Sensor Minimum Metadata Set (MISMMS)",
        "source": SOURCE_ST_0902_8,
        "advisory_and_never_a_refusal": PER_PACKET_IS_NOT_A_VERDICT,
        "stated_on_every_object": (
            "the reading rides on every object this packet produced and not only on the packets "
            "that fell short, because a consumer needs to know that a complete packet is complete "
            "UNDER A RULE and not merely unflagged — klv_uas_codec.LENGTH_DIVERGENCE_POLICY's "
            "precedent, applied to a second rule"),
        "rows_total": ROW_COUNT,
        "rows_reported": reported,
        "rows_not_reported": ROW_COUNT - reported,
        "tags_total": TAG_COUNT,
        "requirement": REQUIREMENTS["ST 0902.3-04"],
        "zero_length_rule": ZERO_LENGTH_DOES_NOT_REPORT,
        "not_decoded_by_this_adapter": list(NOT_DECODED_BY_THIS_ADAPTER),
        "not_decoded_basis": NOT_DECODED_BASIS,
        "exclusive_or_violation": exclusive_or_violation,
        "rows": rows,
    }
