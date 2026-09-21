#!/usr/bin/env python3
"""Writes the synthetic Digital NOTAM fixtures of `fixtures/aixm511/dnotam/` — every positive
document with its parsed twin (the harness set), the `cases/` document that needs the as-of
context, and the two counterexample classes — from the templates below, so each file is
reproducible byte for byte and its provenance is this script.

    python build_fixtures.py            # write, from the directory this file is in
    python build_fixtures.py --check    # compare with the committed files, write nothing

`--check` rebuilds in memory and reports whether the committed files are what the script
writes (exit 0 CURRENT, 1 STALE). The twins are the codec's own `twin_of` reading of each XML
(`tests/test_cdm_aixm511_dnotam.py` re-derives them with the standard library alone). The
goldens under `golden/` are NOT written here: `python -m synapse_cdm.harness --adapter aixm511
--fixtures <this directory> --update-golden` writes them, and the harness judges them.

Everything is SYNTHETIC: designators start with `SYN`, every UUID sits under `a1a40000-00d0-`
(features) or `a1a40000-00e0-` (Events), the aerodrome `ZZSY` and every instant are fictitious,
and no file derives from any published aeronautical data set. The coding follows the Digital
NOTAM Specification 2.0 (DRAFT) scenario pages RWY.CLS (220791360), ATSA.ACT (220791511), SAA.ACT
(220791162) and NAV.UNS (220791463) and the page "Event update or cancellation" (220791154),
and the AIXM Temporality Concept 1.1; the counterexamples break one layer each, on purpose.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent

NS = ('xmlns:message="http://www.aixm.aero/schema/5.1.1/message"\n'
      '    xmlns:aixm="http://www.aixm.aero/schema/5.1.1" xmlns:event="http://www.aixm.aero/schema/5.1.1/event"\n'
      '    xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:xlink="http://www.w3.org/1999/xlink"\n'
      '    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')

# Identifiers. Features under 00d0, Events under 00e0; the last group numbers them.
AIRPORT = "a1a40000-00d0-4000-8000-000000000001"
RWY_DIR = "a1a40000-00d0-4000-8000-000000000002"
TMA = "a1a40000-00d0-4000-8000-000000000003"
TSA = "a1a40000-00d0-4000-8000-000000000004"
NAVAID = "a1a40000-00d0-4000-8000-000000000005"
VOR = "a1a40000-00d0-4000-8000-000000000006"
FIR = "a1a40000-00d0-4000-8000-000000000007"
EVENTS = {n: f"a1a40000-00e0-4000-8000-{n:012d}" for n in range(1, 10)}
NOF = "a1a40000-00d0-4000-8000-000000000008"


def document(gml_id: str, comment: str, members: list[str]) -> str:
    body = "\n".join(f"  <message:hasMember>\n{m}\n  </message:hasMember>" for m in members)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<!-- SYNTHETIC. {comment} -->\n'
            f'<message:AIXMBasicMessage {NS}\n    gml:id="{gml_id}">\n{body}\n</message:AIXMBasicMessage>\n')


def period(gml_id: str, begin: str, end: str | None) -> str:
    end_xml = (f'<gml:endPosition>{end}</gml:endPosition>' if end
               else '<gml:endPosition indeterminatePosition="unknown"/>')
    return (f'<gml:TimePeriod gml:id="{gml_id}">\n              <gml:beginPosition>{begin}</gml:beginPosition>\n'
            f'              {end_xml}\n            </gml:TimePeriod>')


def slice_head(gml_id: str, interpretation: str, sequence: int, correction: int, begin: str | None,
               end: str | None, *, lifetime: tuple[str, str | None] | None = None, cancelled: bool = False) -> str:
    if cancelled:
        valid = '          <gml:validTime nilReason="inapplicable"/>'
    else:
        valid = f'          <gml:validTime>\n            {period(gml_id + "_VT", begin or "", end)}\n          </gml:validTime>'
    out = (f'{valid}\n          <aixm:interpretation>{interpretation}</aixm:interpretation>\n'
           f'          <aixm:sequenceNumber>{sequence}</aixm:sequenceNumber>\n'
           f'          <aixm:correctionNumber>{correction}</aixm:correctionNumber>')
    if cancelled and lifetime is not None:
        out += '\n          <aixm:featureLifetime nilReason="inapplicable"/>'
    elif lifetime is not None:
        out += (f'\n          <aixm:featureLifetime>\n            {period(gml_id + "_LT", lifetime[0], lifetime[1])}'
                '\n          </aixm:featureLifetime>')
    return out


def feature(element: str, uuid: str, slices: list[str], *, slice_element: str | None = None) -> str:
    prefix = element.split(":")[0]
    ts = slice_element or (element + "TimeSlice")
    inner = "\n".join(f'      <{prefix}:timeSlice>\n        <{ts} gml:id="{g}">\n{body}\n        </{ts}>\n      </{prefix}:timeSlice>'
                      for g, body in slices)
    return (f'    <{element} gml:id="uuid.{uuid}">\n      <gml:identifier codeSpace="urn:uuid:">{uuid}</gml:identifier>\n'
            f'{inner}\n    </{element}>')


def notam(gml_id: str, kind: str, number: int, issued: str, start: str, end: str, text: str,
          *, referred: int | None = None, estimated: bool = False) -> str:
    referred_xml = ""
    if referred is not None:
        referred_xml = (f'\n              <event:referredSeries>S</event:referredSeries>\n'
                        f'              <event:referredNumber>{referred}</event:referredNumber>\n'
                        f'              <event:referredYear>2026</event:referredYear>')
    return (f'          <event:notification>\n            <event:NOTAM gml:id="{gml_id}">\n'
            f'              <event:series>S</event:series>\n              <event:number>{number}</event:number>\n'
            f'              <event:year>2026</event:year>\n              <event:issued>{issued}</event:issued>\n'
            f'              <event:publisher xlink:href="urn:uuid:{NOF}" xlink:title="SYNTHETIC NOTAM OFFICE"/>\n'
            f'              <event:type>{kind}</event:type>{referred_xml}\n'
            f'              <event:affectedFIR>ZZSY</event:affectedFIR>\n'
            f'              <event:location>ZZSY</event:location>\n'
            f'              <event:effectiveStart>{start}</event:effectiveStart>\n'
            f'              <event:effectiveEnd>{end}</event:effectiveEnd>\n'
            f'              <event:estimatedEnd>{"YES" if estimated else "NO"}</event:estimatedEnd>\n'
            f'              <event:permanent>NO</event:permanent>\n'
            f'              <event:text lang="ENG">{text}</event:text>\n'
            f'            </event:NOTAM>\n          </event:notification>')


def event_slice(gml_id: str, sequence: int, correction: int, begin: str | None, end: str | None, *,
                scenario: str, name: str, notams: list[str], cancelled: bool = False,
                estimated_validity: str | None = None, concerned_airspace: str | None = FIR,
                concerned_airport: str | None = AIRPORT, version: str = "2.0",
                activity_nil: bool = False) -> tuple[str, str]:
    head = slice_head(gml_id, "BASELINE", sequence, correction, begin, end,
                      lifetime=(begin or "", end) if (begin or cancelled) else None, cancelled=cancelled)
    props = [f'          <event:name>{name}</event:name>',
             '          <event:designator>DNOTAM</event:designator>',
             f'          <event:scenario>{scenario}</event:scenario>',
             f'          <event:version>{version}</event:version>']
    if estimated_validity == "nil":
        props.append('          <event:estimatedValidity xsi:nil="true"/>')
    elif estimated_validity:
        props.append(f'          <event:estimatedValidity>{estimated_validity}</event:estimatedValidity>')
    if activity_nil:
        props.append('          <event:activity xsi:nil="true" nilReason="unknown"/>')
    if concerned_airspace:
        props.append(f'          <event:concernedAirspace xlink:href="urn:uuid:{concerned_airspace}" xlink:title="ZZSY FIR"/>')
    if concerned_airport:
        props.append(f'          <event:concernedAirportHeliport xlink:href="urn:uuid:{concerned_airport}" xlink:title="ZZSY"/>')
    return gml_id, head + "\n" + "\n".join(props) + ("\n" + "\n".join(notams) if notams else "")


def extension(gml_id: str, element: str, event_uuid: str, title: str) -> str:
    return (f'          <aixm:extension>\n            <event:{element} gml:id="{gml_id}">\n'
            f'              <event:theEvent xlink:href="urn:uuid:{event_uuid}" xlink:title="{title}"/>\n'
            f'            </event:{element}>\n          </aixm:extension>')


def availability(gml_id: str, status: str, *, timesheet: tuple[str, str] | None = None,
                 note: str | None = None, element: str = "ManoeuvringAreaAvailability",
                 status_property: str = "operationalStatus", extra: str = "") -> str:
    ts = ""
    if timesheet:
        ts = (f'\n              <aixm:timeInterval>\n                <aixm:Timesheet gml:id="{gml_id}_TS">\n'
              f'                  <aixm:timeReference>UTC</aixm:timeReference>\n                  <aixm:day>ANY</aixm:day>\n'
              f'                  <aixm:dayTil>ANY</aixm:dayTil>\n                  <aixm:startTime>{timesheet[0]}</aixm:startTime>\n'
              f'                  <aixm:endTime>{timesheet[1]}</aixm:endTime>\n                </aixm:Timesheet>\n'
              f'              </aixm:timeInterval>')
    note_xml = ""
    if note:
        note_xml = (f'\n              <aixm:annotation>\n                <aixm:Note gml:id="{gml_id}_N">\n'
                    f'                  <aixm:propertyName>{status_property}</aixm:propertyName>\n'
                    f'                  <aixm:purpose>REMARK</aixm:purpose>\n'
                    f'                  <aixm:translatedNote>\n                    <aixm:LinguisticNote gml:id="{gml_id}_LN">\n'
                    f'                      <aixm:note lang="ENG">{note}</aixm:note>\n                    </aixm:LinguisticNote>\n'
                    f'                  </aixm:translatedNote>\n                </aixm:Note>\n              </aixm:annotation>')
    prop = "activation" if element == "AirspaceActivation" else "availability"
    return (f'          <aixm:{prop}>\n            <aixm:{element} gml:id="{gml_id}">{ts}{note_xml}\n'
            f'              <aixm:{status_property}>{status}</aixm:{status_property}>{extra}\n'
            f'            </aixm:{element}>\n          </aixm:{prop}>')


LEVELS = ('\n              <aixm:levels>\n                <aixm:AirspaceLayer gml:id="{id}_L">\n'
          '                  <aixm:upperLimit>CEILING</aixm:upperLimit>\n'
          '                  <aixm:lowerLimit>FLOOR</aixm:lowerLimit>\n'
          '                </aixm:AirspaceLayer>\n              </aixm:levels>')

BASELINE_BEGIN = "2026-01-01T00:00:00Z"


def airport_baseline() -> str:
    g = "AHP_ZZSY_BL_1_0"
    return feature("aixm:AirportHeliport", AIRPORT, [(g, slice_head(g, "BASELINE", 1, 0, BASELINE_BEGIN, None) +
                                                     '\n          <aixm:designator>ZZSY</aixm:designator>'
                                                     '\n          <aixm:name>SYNTHETIC AERODROME</aixm:name>'
                                                     '\n          <aixm:locationIndicatorICAO>ZZSY</aixm:locationIndicatorICAO>')])


def fir_baseline() -> str:
    g = "ASE_FIR_BL_1_0"
    return feature("aixm:Airspace", FIR, [(g, slice_head(g, "BASELINE", 1, 0, BASELINE_BEGIN, None) +
                                          '\n          <aixm:type>FIR</aixm:type>\n          <aixm:designator>ZZSY</aixm:designator>'
                                          '\n          <aixm:name>SYNTHETIC FIR</aixm:name>')])


def rwy_dir_baseline() -> tuple[str, str]:
    g = "RDN_ZZSY_09_BL_1_0"
    return (g, slice_head(g, "BASELINE", 1, 0, BASELINE_BEGIN, None) +
            '\n          <aixm:designator>09</aixm:designator>'
            '\n          <aixm:trueBearing>87.2</aixm:trueBearing>\n' + availability(g + "_AV1", "NORMAL"))


def rwy_dir(*deltas: tuple[str, str], baseline: bool = True) -> str:
    """The runway direction feature: its BASELINE slice (unless `baseline=False`) and the deltas,
    in that order, in ONE member — a feature's slices share its gml:id."""
    return feature("aixm:RunwayDirection", RWY_DIR, ([rwy_dir_baseline()] if baseline else []) + list(deltas))


def rwy_dir_tempdelta(gml_id: str, sequence: int, correction: int, begin: str | None, end: str | None,
                      event_uuid: str, *, cancelled: bool = False, status: str = "CLOSED",
                      closed_timesheet: tuple[str, str] | None = None, copy_normal: bool = True) -> tuple[str, str]:
    body = slice_head(gml_id, "TEMPDELTA", sequence, correction, begin, end, cancelled=cancelled)
    if not cancelled:
        if copy_normal:
            body += "\n" + availability(gml_id + "_AV1", "NORMAL", note="Baseline data copy. Not included in the NOTAM text generation")
        body += "\n" + availability(gml_id + "_AV2", status, timesheet=closed_timesheet, note="Surface maintenance")
    body += "\n" + extension(gml_id + "_EXT", "RunwayDirectionExtension", event_uuid, "ZZSY 09 DNOTAM RWY.CLS")
    return gml_id, body


def rwy_cls_event(n: int, gml: str, sequence: int, correction: int, begin: str | None, end: str | None, *,
                  notams: list[str], cancelled: bool = False, estimated_validity: str | None = None,
                  activity_nil: bool = False, scenario: str = "RWY.CLS", version: str = "2.0",
                  concerned_airspace: str | None = FIR) -> tuple[str, str]:
    return event_slice(gml, sequence, correction, begin, end, scenario=scenario, name="ZZSY 09", notams=notams,
                       cancelled=cancelled, estimated_validity=estimated_validity, activity_nil=activity_nil,
                       version=version, concerned_airspace=concerned_airspace)


def build() -> dict[str, str]:
    out: dict[str, str] = {}
    E = EVENTS

    # 1. RWY.CLS: baseline + closure --------------------------------------------------------
    b, e = "2026-03-10T06:00:00Z", "2026-03-10T10:00:00Z"
    out["rwy_cls_baseline_and_closure.xml"] = document(
        "M_DN_RWY_CLS", "Digital NOTAM RWY.CLS 2.0 (DRAFT guidance page 220791360): the RunwayDirection\n"
        "     BASELINE (availability NORMAL, open-ended) and the Event BASELINE 1.0 with its NOTAMN, plus the\n"
        "     RunwayDirection TEMPDELTA 1.0 for the closure window carrying the NORMAL copy (RWY.CLS.03, first\n"
        "     sentence) beside the CLOSED branch (second sentence) and the event:theEvent binding (RWY.CLS.02).\n"
        "     The aerodrome and FIR BASELINEs are here so concernedAirportHeliport / concernedAirspace resolve\n"
        "     (RWY.CLS.05, .06). Authored 2026-09-21 by dnotam/spec/build_fixtures.py.",
        [airport_baseline(), fir_baseline(),
         feature("event:Event", E[1], [rwy_cls_event(1, "EVT_1_BL_1_0", 1, 0, b, e, notams=[
             notam("EVT_1_BL_1_0_N", "N", 101, "2026-03-09T12:00:00Z", "2603100600", "2603101000",
                   "RWY 09 CLOSED DUE TO SURFACE MAINTENANCE.")])], slice_element="event:EventTimeSlice"),
         rwy_dir(rwy_dir_tempdelta("RDN_ZZSY_09_TD_1_0", 1, 0, b, e, E[1]))])

    # 2. ATSA.ACT: baseline (scheduled activation) + activation ----------------------------
    b, e = "2026-03-12T05:00:00Z", "2026-03-12T09:00:00Z"
    g = "ASE_TMA_BL_1_0"
    tma_baseline = (g, slice_head(g, "BASELINE", 1, 0, BASELINE_BEGIN, None) +
                    '\n          <aixm:type>TMA</aixm:type>\n          <aixm:designator>SYNTMA</aixm:designator>'
                    '\n          <aixm:name>SYNTHETIC TMA</aixm:name>\n' +
                    availability(g + "_ACT1", "ACTIVE", element="AirspaceActivation", status_property="status", timesheet=("07:00", "21:00")) + "\n" +
                    availability(g + "_ACT2", "INACTIVE", element="AirspaceActivation", status_property="status", timesheet=("21:00", "07:00")))
    g = "ASE_TMA_TD_1_0"
    out["atsa_act_baseline_and_activation.xml"] = document(
        "M_DN_ATSA_ACT", "Digital NOTAM ATSA.ACT 2.0 (DRAFT guidance page 220791511): a TMA BASELINE whose activation\n"
        "     is scheduled (ACTIVE 07:00-21:00, INACTIVE otherwise — typed, never asserted), the Event BASELINE\n"
        "     1.0, and the Airspace TEMPDELTA 1.0 activating the whole TMA (one AirspaceActivation ACTIVE, layer\n"
        "     FLOOR/CEILING per ER-02, no schedule) bound by event:theEvent (ER-01). Authored 2026-09-21 by\n"
        "     dnotam/spec/build_fixtures.py.",
        [fir_baseline(),
         feature("event:Event", E[2], [event_slice("EVT_2_BL_1_0", 1, 0, b, e, scenario="ATSA.ACT", name="SYNTMA", notams=[
             notam("EVT_2_BL_1_0_N", "N", 102, "2026-03-11T12:00:00Z", "2603120500", "2603120900", "SYNTHETIC TMA ACTIVE.")],
             concerned_airport=None)], slice_element="event:EventTimeSlice"),
         feature("aixm:Airspace", TMA, [tma_baseline, (g, slice_head(g, "TEMPDELTA", 1, 0, b, e) + "\n" +
                                        availability(g + "_ACT1", "ACTIVE", element="AirspaceActivation", status_property="status", extra=LEVELS.format(id=g + "_ACT1")) + "\n" +
                                        extension(g + "_EXT", "AirspaceExtension", E[2], "SYNTMA DNOTAM ATSA.ACT"))])])

    # 3. SAA.ACT: activation with a schedule ------------------------------------------------
    b, e = "2026-03-16T00:00:00Z", "2026-03-20T00:00:00Z"
    g = "ASE_TSA_BL_1_0"
    tsa_baseline = (g, slice_head(g, "BASELINE", 1, 0, BASELINE_BEGIN, None) +
                    '\n          <aixm:type>TSA</aixm:type>\n          <aixm:designator>SYNTSA</aixm:designator>'
                    '\n          <aixm:name>SYNTHETIC TSA</aixm:name>\n' +
                    availability(g + "_ACT1", "INACTIVE", element="AirspaceActivation", status_property="status"))
    g = "ASE_TSA_TD_1_0"
    out["saa_act_activation_with_schedule.xml"] = document(
        "M_DN_SAA_ACT", "Digital NOTAM SAA.ACT 2.0 (DRAFT guidance page 220791162): a TSA BASELINE (INACTIVE,\n"
        "     unconditional), the Event BASELINE 1.0, and the Airspace TEMPDELTA 1.0 with TWO AirspaceActivation\n"
        "     structures — ACTIVE under a Timesheet 08:00-16:00 (ER-05) and the INACTIVE baseline copy for the\n"
        "     other hours (ER-06, with the prescribed REMARK) — so the resolved view is SCHEDULED, not asserted.\n"
        "     Authored 2026-09-21 by dnotam/spec/build_fixtures.py.",
        [fir_baseline(),
         feature("event:Event", E[3], [event_slice("EVT_3_BL_1_0", 1, 0, b, e, scenario="SAA.ACT", name="SYNTSA", notams=[
             notam("EVT_3_BL_1_0_N", "N", 103, "2026-03-15T12:00:00Z", "2603160800", "2603191600", "SYNTHETIC TSA ACTIVE DAILY 0800-1600.")],
             concerned_airport=None)], slice_element="event:EventTimeSlice"),
         feature("aixm:Airspace", TSA, [tsa_baseline, (g, slice_head(g, "TEMPDELTA", 1, 0, b, e) + "\n" +
                                        availability(g + "_ACT1", "ACTIVE", element="AirspaceActivation", status_property="status", timesheet=("08:00", "16:00"), extra=LEVELS.format(id=g + "_ACT1")) + "\n" +
                                        availability(g + "_ACT2", "INACTIVE", element="AirspaceActivation", status_property="status", timesheet=("16:00", "08:00"), note="Baseline data copy. Not included in the NOTAM text generation") + "\n" +
                                        extension(g + "_EXT", "AirspaceExtension", E[3], "SYNTSA DNOTAM SAA.ACT"))])])

    # 4. NAV.UNS: baseline + outage of one component ---------------------------------------
    b, e = "2026-03-14T08:00:00Z", "2026-03-14T12:00:00Z"
    g = "NAV_SYN_BL_1_0"
    nav_baseline = (g, slice_head(g, "BASELINE", 1, 0, BASELINE_BEGIN, None) +
                                                   '\n          <aixm:type>VOR_DME</aixm:type>\n          <aixm:designator>SYN</aixm:designator>'
                                                   '\n          <aixm:name>SYNTHETIC VOR DME</aixm:name>'
                                                   '\n          <aixm:navaidEquipment>\n            <aixm:NavaidComponent gml:id="NAV_SYN_NC_1">'
                                                   '\n              <aixm:collocationGroup>1</aixm:collocationGroup>'
                                                   f'\n              <aixm:theNavaidEquipment xlink:href="urn:uuid:{VOR}" xlink:title="SYN VOR"/>'
                                                   '\n            </aixm:NavaidComponent>\n          </aixm:navaidEquipment>\n' +
                                                   availability(g + "_OPS1", "OPERATIONAL", element="NavaidOperationalStatus"))
    g = "VOR_SYN_BL_1_0"
    # VORTimeSliceType: the NavaidEquipment properties (designator, name, …, availability) precede
    # the VOR's own (type, frequency, …).
    vor_baseline = (g, slice_head(g, "BASELINE", 1, 0, BASELINE_BEGIN, None) +
                    '\n          <aixm:designator>SYN</aixm:designator>\n          <aixm:name>SYNTHETIC VOR</aixm:name>\n' +
                    availability(g + "_OPS1", "OPERATIONAL", element="NavaidOperationalStatus") +
                    '\n          <aixm:type>VOR</aixm:type>')
    g1, g2 = "NAV_SYN_TD_1_0", "VOR_SYN_TD_1_0"
    out["nav_uns_baseline_and_outage.xml"] = document(
        "M_DN_NAV_UNS", "Digital NOTAM NAV.UNS 2.0 (DRAFT guidance page 220791463): a VOR/DME Navaid BASELINE\n"
        "     (OPERATIONAL) and its VOR component (a NavaidEquipment feature outside the five families, read\n"
        "     generically with its availability carried), the Event BASELINE 1.0, the VOR TEMPDELTA 1.0\n"
        "     UNSERVICEABLE (NAV.UNS.02) and the Navaid TEMPDELTA 1.0 with type DME and status PARTIAL\n"
        "     (NAV.UNS.05, NAV.UNS.06: the VOR component of a VOR_DME is out, the service is temporarily a\n"
        "     DME). Authored 2026-09-21 by dnotam/spec/build_fixtures.py.",
        [airport_baseline(), fir_baseline(),
         feature("event:Event", E[4], [event_slice("EVT_4_BL_1_0", 1, 0, b, e, scenario="NAV.UNS", name="SYN VOR/DME", notams=[
             notam("EVT_4_BL_1_0_N", "N", 104, "2026-03-13T12:00:00Z", "2603140800", "2603141200", "SYN VOR U/S. DME OPERATIONAL.")])],
                 slice_element="event:EventTimeSlice"),
         feature("aixm:Navaid", NAVAID, [nav_baseline, (g1, slice_head(g1, "TEMPDELTA", 1, 0, b, e) +
                                         '\n          <aixm:type>DME</aixm:type>\n' +
                                         availability(g1 + "_OPS1", "PARTIAL", element="NavaidOperationalStatus") + "\n" +
                                         extension(g1 + "_EXT", "NavaidExtension", E[4], "SYN VOR/DME DNOTAM NAV.UNS"))]),
         feature("aixm:VOR", VOR, [vor_baseline, (g2, slice_head(g2, "TEMPDELTA", 1, 0, b, e) + "\n" +
                                   availability(g2 + "_OPS1", "UNSERVICEABLE", element="NavaidOperationalStatus") + "\n" +
                                   extension(g2 + "_EXT", "VORExtension", E[4], "SYN VOR/DME DNOTAM NAV.UNS"))])])

    # 5. A future-effective change ----------------------------------------------------------
    b, e = "2026-06-01T06:00:00Z", "2026-06-01T10:00:00Z"
    out["future_effective_change.xml"] = document(
        "M_DN_FUTURE", "A RWY.CLS Event and TEMPDELTA whose window (2026-06-01 06:00-10:00Z) lies after the\n"
        "     instants the tests resolve at: the baseline NORMAL stands until the begin (§4.4.1 begin included),\n"
        "     the change is recorded as FUTURE and applied from 06:00:00Z exactly. Authored 2026-09-21 by\n"
        "     dnotam/spec/build_fixtures.py.",
        [feature("event:Event", E[5], [rwy_cls_event(5, "EVT_5_BL_1_0", 1, 0, b, e, notams=[
             notam("EVT_5_BL_1_0_N", "N", 105, "2026-03-20T12:00:00Z", "2606010600", "2606011000", "RWY 09 CLOSED.")],
             concerned_airspace=None)], slice_element="event:EventTimeSlice"),
         rwy_dir(rwy_dir_tempdelta("RDN_ZZSY_09_TD_1_0", 1, 0, b, e, E[5]))])

    # 6. Overlapping temporary changes (TS_011) --------------------------------------------
    out["overlapping_tempdeltas.xml"] = document(
        "M_DN_OVERLAP", "Two RWY.CLS Events on the SAME runway direction whose TEMPDELTAs overlap: sequence 1\n"
        "     06:00-10:00Z and sequence 2 08:00-12:00Z, both stating availability. Temporality Concept 1.1 TS_011\n"
        "     forbids this; between 08:00 and 10:00 the resolver reports AMBIGUOUS and applies neither, before\n"
        "     08:00 sequence 1 alone, from 10:00 sequence 2 alone. Authored 2026-09-21 by\n"
        "     dnotam/spec/build_fixtures.py.",
        [feature("event:Event", E[6], [rwy_cls_event(6, "EVT_6_BL_1_0", 1, 0, "2026-03-10T06:00:00Z", "2026-03-10T10:00:00Z", notams=[
             notam("EVT_6_BL_1_0_N", "N", 106, "2026-03-09T12:00:00Z", "2603100600", "2603101000", "RWY 09 CLOSED.")],
             concerned_airspace=None)], slice_element="event:EventTimeSlice"),
         feature("event:Event", E[7], [rwy_cls_event(7, "EVT_7_BL_1_0", 1, 0, "2026-03-10T08:00:00Z", "2026-03-10T12:00:00Z", notams=[
             notam("EVT_7_BL_1_0_N", "N", 107, "2026-03-09T18:00:00Z", "2603100800", "2603101200", "RWY 09 CLOSED.")],
             concerned_airspace=None)], slice_element="event:EventTimeSlice"),
         rwy_dir(rwy_dir_tempdelta("RDN_ZZSY_09_TD_1_0", 1, 0, "2026-03-10T06:00:00Z", "2026-03-10T10:00:00Z", E[6]),
                 rwy_dir_tempdelta("RDN_ZZSY_09_TD_2_0", 2, 0, "2026-03-10T08:00:00Z", "2026-03-10T12:00:00Z", E[7]))])

    # 7. Explicit nil values ----------------------------------------------------------------
    b, e = "2026-03-14T08:00:00Z", "2026-03-14T12:00:00Z"
    g = "NAV_SYN_TD_1_0"
    out["explicit_nil_values.xml"] = document(
        "M_DN_NIL", "Explicit nils on both sides of the binding: the Event states estimatedValidity xsi:nil\n"
        "     (nil, not absent) and activity nil with nilReason='unknown'; the Navaid TEMPDELTA states its\n"
        "     availability as ONE nil occurrence (Temporality Concept 1.1 §4.4.6.3, 'all occurrences are\n"
        "     removed'), so the resolved availability is WITHDRAWN — the baseline OPERATIONAL is not carried\n"
        "     through and nothing is asserted. Authored 2026-09-21 by dnotam/spec/build_fixtures.py.",
        [feature("event:Event", E[8], [event_slice("EVT_8_BL_1_0", 1, 0, b, e, scenario="NAV.UNS", name="SYN VOR/DME", notams=[
             notam("EVT_8_BL_1_0_N", "N", 108, "2026-03-13T12:00:00Z", "2603140800", "2603141200", "SYN VOR/DME STATUS WITHDRAWN.")],
             estimated_validity="nil", activity_nil=True, concerned_airspace=None, concerned_airport=None)],
                 slice_element="event:EventTimeSlice"),
         feature("aixm:Navaid", NAVAID, [nav_baseline, (g, slice_head(g, "TEMPDELTA", 1, 0, b, e) +
                                         '\n          <aixm:availability xsi:nil="true" nilReason="unknown"/>\n' +
                                         extension(g + "_EXT", "NavaidExtension", E[8], "SYN VOR/DME DNOTAM NAV.UNS"))])])

    # 8. Unresolved references ---------------------------------------------------------------
    b, e = "2026-03-10T06:00:00Z", "2026-03-10T10:00:00Z"
    missing_event = "a1a40000-00e0-4000-8000-000000000099"
    out["unresolved_references.xml"] = document(
        "M_DN_UNRESOLVED", "The binding and the Event's references point outside the document: the\n"
        "     RunwayDirection TEMPDELTA's event:theEvent names an Event that is not here, the Event's\n"
        "     concernedAirspace and concernedAirportHeliport name features that are not here, and no\n"
        "     RunwayDirection BASELINE is here. Every reference is kept with its href and form and listed as\n"
        "     unresolved; the resolved view is UNRESOLVED. Authored 2026-09-21 by dnotam/spec/build_fixtures.py.",
        [feature("event:Event", E[1], [rwy_cls_event(1, "EVT_1_BL_1_0", 1, 0, b, e, notams=[
             notam("EVT_1_BL_1_0_N", "N", 101, "2026-03-09T12:00:00Z", "2603100600", "2603101000", "RWY 09 CLOSED.")])],
                 slice_element="event:EventTimeSlice"),
         rwy_dir(rwy_dir_tempdelta("RDN_ZZSY_09_TD_1_0", 1, 0, b, e, missing_event), baseline=False)])

    # 9. Corrections received out of order ---------------------------------------------------
    b, e, e2 = "2026-03-10T06:00:00Z", "2026-03-10T10:00:00Z", "2026-03-10T08:00:00Z"
    out["corrections_out_of_order.xml"] = document(
        "M_DN_OUT_OF_ORDER", "Immediate Event termination (guidance page 220791154) with the corrections\n"
        "     placed BEFORE the slices they correct: the Event BASELINE 1.1 (end and end of life moved to 08:00Z,\n"
        "     NOTAMC) precedes BASELINE 1.0 (NOTAMN, end 10:00Z), and the RunwayDirection TEMPDELTA 1.1 (end\n"
        "     08:00Z) precedes TEMPDELTA 1.0. The adapter keeps both in document order; the resolver's valid\n"
        "     slice is the highest correction whatever the order (§3.6). Authored 2026-09-21 by\n"
        "     dnotam/spec/build_fixtures.py.",
        [feature("event:Event", E[1], [
             rwy_cls_event(1, "EVT_1_BL_1_1", 1, 1, b, e2, notams=[
                 notam("EVT_1_BL_1_1_N", "N", 101, "2026-03-09T12:00:00Z", "2603100600", "2603101000", "RWY 09 CLOSED."),
                 notam("EVT_1_BL_1_1_C", "C", 109, "2026-03-10T08:00:00Z", "2603100800", "2603100800", "RWY 09 CLOSURE CANCELLED.", referred=101)],
                 concerned_airspace=None),
             rwy_cls_event(1, "EVT_1_BL_1_0", 1, 0, b, e, notams=[
                 notam("EVT_1_BL_1_0_N", "N", 101, "2026-03-09T12:00:00Z", "2603100600", "2603101000", "RWY 09 CLOSED.")],
                 concerned_airspace=None)], slice_element="event:EventTimeSlice"),
         rwy_dir(rwy_dir_tempdelta("RDN_ZZSY_09_TD_1_1", 1, 1, b, e2, E[1]),
                 rwy_dir_tempdelta("RDN_ZZSY_09_TD_1_0", 1, 0, b, e, E[1]))])

    # 10. A cancellation before effect --------------------------------------------------------
    b, e = "2026-06-01T06:00:00Z", "2026-06-01T10:00:00Z"
    out["cases/cancellation.xml"] = document(
        "M_DN_CANCELLATION", "An inactive (future) Event cancelled before its start (guidance page 220791154,\n"
        "     'Inactive Event … cancellation'; Temporality Concept 1.1 §4.4.8): the Event BASELINE 1.1 has an\n"
        "     empty gml:validTime and featureLifetime with nilReason='inapplicable' and carries the NOTAMC; the\n"
        "     RunwayDirection TEMPDELTA 1.1 has the empty validTime. Sequence 1 is off the timeline, its 1.0\n"
        "     slices stay on record, and the baseline NORMAL applies at every instant. Authored 2026-09-21 by\n"
        "     dnotam/spec/build_fixtures.py.",
        [feature("event:Event", E[1], [
             rwy_cls_event(1, "EVT_1_BL_1_0", 1, 0, b, e, notams=[
                 notam("EVT_1_BL_1_0_N", "N", 101, "2026-03-20T12:00:00Z", "2606010600", "2606011000", "RWY 09 CLOSED.")],
                 concerned_airspace=None),
             rwy_cls_event(1, "EVT_1_BL_1_1", 1, 1, None, None, cancelled=True, notams=[
                 notam("EVT_1_BL_1_1_C", "C", 110, "2026-03-25T12:00:00Z", "2603251200", "2603251200", "RWY 09 CLOSURE CANCELLED.", referred=101)],
                 concerned_airspace=None)], slice_element="event:EventTimeSlice"),
         rwy_dir(rwy_dir_tempdelta("RDN_ZZSY_09_TD_1_0", 1, 0, b, e, E[1]),
                 rwy_dir_tempdelta("RDN_ZZSY_09_TD_1_1", 1, 1, None, None, E[1], cancelled=True))])

    # 11. Expiry, with an estimated end ------------------------------------------------------
    b, e = "2026-03-10T06:00:00Z", "2026-03-10T10:00:00Z"
    out["expiry.xml"] = document(
        "M_DN_EXPIRY", "A RWY.CLS Event whose end is an ESTIMATE (event:estimatedValidity stated and the\n"
        "     NOTAM's estimatedEnd YES) and whose TEMPDELTA ends at 10:00Z: at 09:59:59Z the closure applies,\n"
        "     at 10:00:00Z it has EXPIRED (end excluded, §4.4.1) and the baseline NORMAL stands; the source\n"
        "     assertion carries estimated_end. Authored 2026-09-21 by dnotam/spec/build_fixtures.py.",
        [feature("event:Event", E[1], [rwy_cls_event(1, "EVT_1_BL_1_0", 1, 0, b, e, notams=[
             notam("EVT_1_BL_1_0_N", "N", 101, "2026-03-09T12:00:00Z", "2603100600", "2603101000 EST", "RWY 09 CLOSED.", estimated=True)],
             estimated_validity=e, concerned_airspace=None)], slice_element="event:EventTimeSlice"),
         rwy_dir(rwy_dir_tempdelta("RDN_ZZSY_09_TD_1_0", 1, 0, b, e, E[1]))])

    # Counterexamples ---------------------------------------------------------------------------
    b, e = "2026-03-10T06:00:00Z", "2026-03-10T10:00:00Z"
    gml, body = rwy_cls_event(1, "EVT_1_BL_1_0", 1, 0, b, e, notams=[], concerned_airspace=None)
    body = body.replace("          <event:version>2.0</event:version>",
                        "          <event:version>2.0</event:version>\n          <event:closureReason>maintenance</event:closureReason>")
    out["counterexamples/schema_invalid_unknown_event_property.xml"] = document(
        "CE_DN_UNKNOWN_PROPERTY", "COUNTEREXAMPLE, class 1: well-formed and SCHEMA-INVALID. The EventTimeSlice carries\n"
        "     an element the Event schema does not declare (event:closureReason). The normative validator\n"
        "     rejects it (element not expected); the adapter reads the document and carries the element in the\n"
        "     residual. Authored 2026-09-21 by dnotam/spec/build_fixtures.py.",
        [feature("event:Event", E[1], [(gml, body)], slice_element="event:EventTimeSlice"),
         rwy_dir(rwy_dir_tempdelta("RDN_ZZSY_09_TD_1_0", 1, 0, b, e, E[1]))])

    gml, body = rwy_cls_event(1, "EVT_1_BL_1_0", 1, 0, b, e, notams=[], concerned_airspace=None)
    old_event = feature("event:Event", E[1], [(gml, body)], slice_element="event:EventTimeSlice")
    old_event = old_event.replace("<event:Event gml:id", '<event:Event xmlns:event="http://www.aixm.aero/schema/5.1/event" gml:id')
    out["counterexamples/schema_invalid_event_schema_1_0_namespace.xml"] = document(
        "CE_DN_OLD_NAMESPACE", "COUNTEREXAMPLE, class 1: well-formed and SCHEMA-INVALID. The Event is in the Event\n"
        "     Schema 1.0 namespace (http://www.aixm.aero/schema/5.1/event, AIXM 5.1), which the pinned 2.0.m\n"
        "     closure does not declare: the validator rejects the member, and the adapter — which reads the\n"
        "     5.1.1 event namespace only — sees a member that is not an AIXM feature and carries it whole in\n"
        "     the residual; the TEMPDELTA's binding is then an unresolved reference. Authored 2026-09-21 by\n"
        "     dnotam/spec/build_fixtures.py.",
        [old_event, rwy_dir(rwy_dir_tempdelta("RDN_ZZSY_09_TD_1_0", 1, 0, b, e, E[1]))])

    g = "ASE_TMA_TD_1_0"
    out["counterexamples/rule_invalid_rwy_cls_on_an_airspace.xml"] = document(
        "CE_DN_WRONG_FEATURE", "COUNTEREXAMPLE, class 2: SCHEMA-VALID and invalid under a scenario RULE. The Event\n"
        "     states scenario RWY.CLS, and the slice bound to it is an Airspace TEMPDELTA with an\n"
        "     AirspaceActivation — RWY.CLS.02 puts the TEMPDELTA on each affected RunwayDirection. The schema\n"
        "     has no objection; the adapter's scenario rule layer names the rule. Authored 2026-09-21 by\n"
        "     dnotam/spec/build_fixtures.py.",
        [feature("event:Event", E[1], [rwy_cls_event(1, "EVT_1_BL_1_0", 1, 0, b, e, notams=[], concerned_airspace=None)],
                 slice_element="event:EventTimeSlice"),
         feature("aixm:Airspace", TMA, [tma_baseline, (g, slice_head(g, "TEMPDELTA", 1, 0, b, e) + "\n" +
                                        availability(g + "_ACT1", "ACTIVE", element="AirspaceActivation", status_property="status") + "\n" +
                                        extension(g + "_EXT", "AirspaceExtension", E[1], "ZZSY 09 DNOTAM RWY.CLS"))])])

    out["counterexamples/rule_invalid_rwy_cls_without_closed_status.xml"] = document(
        "CE_DN_NO_CLOSED", "COUNTEREXAMPLE, class 2: SCHEMA-VALID and invalid under a scenario RULE. The\n"
        "     RunwayDirection TEMPDELTA bound to a RWY.CLS Event states operationalStatus LIMITED and no CLOSED\n"
        "     structure — RWY.CLS.03 requires the CLOSED branch (a limitation is the RWY.LIM scenario). LIMITED is\n"
        "     in the schema's enumeration, so only the rule layer catches it. Authored 2026-09-21 by\n"
        "     dnotam/spec/build_fixtures.py.",
        [feature("event:Event", E[1], [rwy_cls_event(1, "EVT_1_BL_1_0", 1, 0, b, e, notams=[], concerned_airspace=None)],
                 slice_element="event:EventTimeSlice"),
         rwy_dir(rwy_dir_tempdelta("RDN_ZZSY_09_TD_1_0", 1, 0, b, e, E[1], status="LIMITED"))])
    return out


def twin_json(xml: str) -> str:
    from synapse_cdm import secure_xml
    from synapse_cdm.adapters import aixm511, aixm_codec
    twin = aixm_codec.twin_of(secure_xml.parse(xml.encode("utf-8"), aixm511.XML_LIMITS).root, aixm_codec.VERSION_511)
    return json.dumps(twin, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="compare with the committed files, write nothing")
    args = parser.parse_args(argv)
    files = build()
    for name in [n for n in files if "/" not in n]:
        files[name.removesuffix(".xml") + ".parsed.json"] = twin_json(files[name])
    stale = []
    for rel, content in sorted(files.items()):
        path = ROOT / rel
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                stale.append(rel)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if args.check:
        print("CURRENT" if not stale else "STALE: " + ", ".join(stale))
        return 1 if stale else 0
    print(f"wrote {len(files)} files under {ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
