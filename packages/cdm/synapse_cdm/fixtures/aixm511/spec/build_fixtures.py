"""Build the aixm511 INDEPENDENT fixtures from the EUROCONTROL/FAA Donlon fictitious data set.

The Donlon data set (github.com/aixm/Donlon_2025, BSD-2-Clause; every file carries a BSD-style
notice and the words "THIS FICTITIOUS DATA SET") is independently authored AIXM 5.1.1: nothing
in it was written by or for this adapter, which is what makes it an `independent_expected`
input (ARCHITECTURE.md §3.4). It is also large — `Donlon_Airspace.xml` alone is 569 KB — so this
script writes a BOUNDED extract: the members named in `SELECTION`, copied element for element
from the source files into one `message:AIXMBasicMessage` each, with the source's copyright
notice kept at the top, plus `expected.json`, a reading of the SAME members made with the
standard library's ElementTree over the SOURCE files (never through the adapter or its codec),
which `tests/test_cdm_aixm511_adapter.py::test_the_adapter_agrees_with_the_independent_donlon_reading`
compares the adapter's output against.

Run it with the six Donlon files in one directory:

    python build_fixtures.py --donlon <dir>            # from the directory this file is in
    python build_fixtures.py --donlon <dir> --check

`--check` rebuilds in memory and reports whether the committed files are what the script
writes. The SHA-256 of every source file this extract was cut from is in
`independent/PROVENANCE.json`; the script refuses a source whose digest differs, so an extract
is never silently cut from a different revision of the data set.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent / "independent"

AIXM = "http://www.aixm.aero/schema/5.1.1"
MESSAGE = "http://www.aixm.aero/schema/5.1.1/message"
GML = "http://www.opengis.net/gml/3.2"
XLINK = "http://www.w3.org/1999/xlink"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
NS = {"aixm": AIXM, "message": MESSAGE, "gml": GML, "xlink": XLINK, "xsi": XSI}

#: Source file -> its SHA-256 as retrieved on 2026-09-21 from
#: raw.githubusercontent.com/aixm/Donlon_2025/main/Donlon/DONLON original files/...
SOURCES: dict[str, str] = {
    "Donlon_EADD_AirportHeliport.xml": "34266d4fa6935b8e2f605109ef405d83eed8a14487549a1925974594e50e0331",
    "Donlon_EADD_Runway.xml": "1196dfa5643333da3b422882461c0d59be42b4e00b6e355008a6642c68fdd196",
    "Donlon_EADD_RunwayDirection.xml": "323c6a97bddf2b01c05a5377f8e58b382b7985afca0e9ccc4ec60ab6fb2010de",
    "Donlon_Navaid.xml": "25d9593e435726be144dc106c80360cb374f1b7c33fef1c627637e1b03ffede3",
    "Donlon_Airspace.xml": "6570598acba9da6b70223a58059ac7bd95b01d627aa487b1e142eb6fdf54f4f1",
    "Donlon_VerticalStructure.xml": "f7c36910d8e85345b748e2770338f01ba3e51b6b508afb21e21245346a0d9c11",
}

#: Output file -> [(source file, gml:identifier), ...] in the order the members are written.
SELECTION: dict[str, list[tuple[str, str]]] = {
    "donlon_extract.xml": [
        ("Donlon_EADD_AirportHeliport.xml", "1b54b2d6-a5ff-4e57-94c2-f4047a381c64"),
        ("Donlon_EADD_Runway.xml", "9e51668f-bf8a-4f5b-ba6e-27087972b9b8"),
        ("Donlon_EADD_Runway.xml", "4428d037-1cdf-433a-9bfa-d0857aaf448a"),
        ("Donlon_EADD_Runway.xml", "b4744933-6271-4534-874c-380596a4d3d8"),
        ("Donlon_EADD_RunwayDirection.xml", "425f1f4b-ef0f-4d7b-8706-aee197f124ed"),
        ("Donlon_EADD_RunwayDirection.xml", "c6fd6993-78ea-4815-9089-6a711bf58a2c"),
        ("Donlon_Navaid.xml", "e0aaf66e-82dd-4c79-b333-d99efe04b99b"),
        ("Donlon_Navaid.xml", "e10319da-34de-404f-a5e1-0ebfd3d07e34"),
        ("Donlon_Airspace.xml", "ecf4941f-21c8-4a47-af12-a333d1744e54"),
        ("Donlon_Airspace.xml", "d1806917-9ca1-4213-83b5-9fac67e4f508"),
        ("Donlon_VerticalStructure.xml", "1371b29a-2ba6-44c8-8da3-711e5488fdb7"),
        ("Donlon_VerticalStructure.xml", "56ef6d9c-4951-4a0b-83d8-95e4836c63c8"),
    ],
    # One prohibited area whose boundary is drawn with gml:ArcByCenterPoint / CircleByCenterPoint:
    # the refusal path on independently authored data.
    "donlon_extract_arc_airspace.xml": [
        ("Donlon_Airspace.xml", "21a13c9f-a8ff-4fdd-9aaa-5dbfd91514b8"),
    ],
}

NOTICE = """ Copyright (c) 2025, EUROCONTROL

  All rights reserved.

  Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:

  Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
  Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
  Neither the names of EUROCONTROL or FAA nor the names of their contributors may be used to endorse or promote products derived from this specification without specific prior written permission.

  THIS FICTITIOUS DATA SET IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
  INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
  CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
  OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR
  TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS DATA SET, EVEN IF ADVISED OF THE
  POSSIBILITY OF SUCH DAMAGE.

  Extract: members selected from the Donlon_2025 data set (github.com/aixm/Donlon_2025) by
  synapse_cdm/fixtures/aixm511/spec/build_fixtures.py on 2026-09-21; each member is copied element
  for element from the source file named in independent/PROVENANCE.json. Fictitious data — never
  operational. """


def _sha256(path: pathlib.Path) -> str:
    """Through `evidence.digest`, the package's one content-digest site (no `hashlib` in a
    fixture generator: `tests/test_cdm_boundary.py::test_no_crypto_in_the_contract_layer`)."""
    from synapse_cdm.evidence import digest
    return digest(path)[0]


def _members(source_dir: pathlib.Path, verified: dict[str, ET.Element]) -> dict[tuple[str, str], ET.Element]:
    found: dict[tuple[str, str], ET.Element] = {}
    for name in SOURCES:
        if name not in verified:
            path = source_dir / name
            if not path.is_file():
                raise SystemExit(f"{path} is missing; the six Donlon files are named in SOURCES")
            digest = _sha256(path)
            if digest != SOURCES[name]:
                raise SystemExit(f"{path} has SHA-256 {digest}, not the {SOURCES[name]} this extract was "
                                 "cut from; an extract from another revision would be a different fixture")
            verified[name] = ET.parse(path).getroot()
        for member in verified[name].findall("message:hasMember", NS):
            identifier = member[0].findtext("gml:identifier", namespaces=NS)
            if identifier:
                found[(name, identifier.strip().lower())] = member
    return found


def build(source_dir: pathlib.Path) -> tuple[dict[str, bytes], dict]:
    for prefix, uri in NS.items():
        ET.register_namespace(prefix, uri)
    verified: dict[str, ET.Element] = {}
    members = _members(source_dir, verified)
    files: dict[str, bytes] = {}
    expected: dict[str, dict] = {}
    for out_name, selection in SELECTION.items():
        root = ET.Element(f"{{{MESSAGE}}}AIXMBasicMessage",
                          {f"{{{GML}}}id": "DONLON_EXTRACT_" + out_name.removesuffix(".xml").upper()})
        for source, identifier in selection:
            member = members.get((source, identifier))
            if member is None:
                raise SystemExit(f"{source} carries no member with gml:identifier {identifier}")
            root.append(member)
            expected[identifier] = _independent_reading(member[0], source)
        ET.indent(root, space="  ")
        body = ET.tostring(root, encoding="unicode")
        files[out_name] = (f'<?xml version="1.0" encoding="UTF-8"?>\n<!--{NOTICE}-->\n' + body + "\n").encode("utf-8")
    return files, expected


def _text(element: ET.Element | None) -> str | None:
    return None if element is None or element.text is None else element.text.strip()


def _attr(element: ET.Element | None, name: str) -> str | None:
    return None if element is None else element.get(name)


def _first(parent: ET.Element, *paths: str) -> ET.Element | None:
    for path in paths:
        found = parent.find(path, NS)
        if found is not None:
            return found
    return None


def _independent_reading(feature: ET.Element, source: str) -> dict:
    """What the adapter must agree with, read with ElementTree and XPath over the source
    element — no codec, no adapter, no schema table."""
    family = feature.tag.split("}", 1)[1]
    slices = feature.findall("aixm:timeSlice/*", NS)
    reading: dict = {"source_file": source, "family": family,
                     "gml_id": feature.get(f"{{{GML}}}id"), "slices": []}
    for ts in slices:
        entry: dict = {
            "gml_id": ts.get(f"{{{GML}}}id"),
            "interpretation": _text(ts.find("aixm:interpretation", NS)),
            "sequence_number": _text(ts.find("aixm:sequenceNumber", NS)),
            "correction_number": _text(ts.find("aixm:correctionNumber", NS)),
            "begin_position": _text(ts.find("gml:validTime/gml:TimePeriod/gml:beginPosition", NS)),
            "end_indeterminate": _attr(ts.find("gml:validTime/gml:TimePeriod/gml:endPosition", NS),
                                       "indeterminatePosition"),
            "designator": _text(ts.find("aixm:designator", NS)),
            "type": _text(ts.find("aixm:type", NS)),
            "name": _text(ts.find("aixm:name", NS)),
        }
        point = _first(ts, "aixm:ARP/aixm:ElevatedPoint", "aixm:location/aixm:ElevatedPoint",
                       "aixm:part/aixm:VerticalStructurePart/aixm:horizontalProjection_location/aixm:ElevatedPoint")
        if point is not None:
            pos = _text(point.find("gml:pos", NS))
            entry["point"] = {"srs_name": point.get("srsName"), "pos": pos,
                              "elevation": _text(point.find("aixm:elevation", NS)),
                              "elevation_uom": _attr(point.find("aixm:elevation", NS), "uom")}
        volume = ts.find("aixm:geometryComponent/aixm:AirspaceGeometryComponent/aixm:theAirspaceVolume/aixm:AirspaceVolume", NS)
        if volume is not None:
            upper, lower = volume.find("aixm:upperLimit", NS), volume.find("aixm:lowerLimit", NS)
            entry["volume"] = {
                "upper_limit": _text(upper), "upper_uom": None if upper is None else upper.get("uom"),
                "upper_reference": _text(volume.find("aixm:upperLimitReference", NS)),
                "lower_limit": _text(lower), "lower_uom": None if lower is None else lower.get("uom"),
                "lower_reference": _text(volume.find("aixm:lowerLimitReference", NS)),
                "srs_name": _attr(volume.find("aixm:horizontalProjection/aixm:Surface", NS), "srsName"),
                "segment_elements": sorted({e.tag.split("}", 1)[1] for e in volume.findall(".//gml:segments/*", NS)}),
                "pos_list_numbers": sum(len((e.text or "").split()) for e in volume.findall(".//gml:posList", NS)),
            }
        entry["operations"] = [_text(e) for e in ts.findall("aixm:geometryComponent/aixm:AirspaceGeometryComponent/aixm:operation", NS)]
        entry["hrefs"] = sorted(e.get(f"{{{XLINK}}}href") for e in ts.iter() if e.get(f"{{{XLINK}}}href"))
        statuses = ts.findall("aixm:availability/*/aixm:operationalStatus", NS) + ts.findall("aixm:activation/*/aixm:status", NS)
        entry["status_codes"] = [_text(s) for s in statuses]
        entry["timesheets"] = (len(ts.findall("aixm:availability/*/aixm:timeInterval/aixm:Timesheet", NS))
                               + len(ts.findall("aixm:activation/*/aixm:timeInterval/aixm:Timesheet", NS)))
        entry["parts"] = len(ts.findall("aixm:part/aixm:VerticalStructurePart", NS))
        reading["slices"].append(entry)
    return reading


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--donlon", required=True, type=pathlib.Path,
                        help="directory holding the six Donlon source files named in SOURCES")
    parser.add_argument("--check", action="store_true", help="compare with the committed files, write nothing")
    args = parser.parse_args(argv)
    files, expected = build(args.donlon)
    rendered = json.dumps(expected, indent=2, sort_keys=True) + "\n"
    if args.check:
        differences = [name for name, octets in files.items() if (OUT / name).read_bytes() != octets]
        if (OUT / "expected.json").read_text() != rendered:
            differences.append("expected.json")
        print("CURRENT" if not differences else "STALE: " + ", ".join(differences))
        return 0 if not differences else 1
    OUT.mkdir(parents=True, exist_ok=True)
    for name, octets in files.items():
        (OUT / name).write_bytes(octets)
        print(f"wrote {OUT / name} ({len(octets)} octets)")
    (OUT / "expected.json").write_text(rendered)
    print(f"wrote {OUT / 'expected.json'} ({len(expected)} features)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
