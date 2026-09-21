# Independent input — a bounded extract of the Donlon fictitious data set

`donlon_extract.xml` (twelve members: the EADD aerodrome, its three runways, two runway
directions, two navaids, two airspaces, two vertical structures) and
`donlon_extract_arc_airspace.xml` (one prohibited area bounded by arcs and circles) are cut from
the EUROCONTROL/FAA **Donlon** AIXM 5.1.1 data set — `github.com/aixm/Donlon_2025`, BSD-2-Clause,
each source file carrying a BSD-style notice and the words "THIS FICTITIOUS DATA SET … shall NEVER
BE USED AS OPERATIONAL DATA" — by `../spec/build_fixtures.py` on 2026-09-21, member by member,
element for element, with the notice kept at the top of each file. The script pins the SHA-256 of
the six source files it cuts from and refuses any other revision; `PROVENANCE.json` repeats the
digests.

Nothing here was written by or for this adapter, which is what makes it an `independent_expected`
input (ARCHITECTURE.md §3.4). `expected.json` is a reading of the SAME members made with the
standard library's ElementTree and XPath over the SOURCE files — identifiers, slice ids,
interpretations and numbers, begin positions, designators, types, names, the `gml:pos` text and
elevation of every ARP / navaid location / obstacle location, every volume's limit texts, units
and references, the segment element names and the count of posList numbers, every `xlink:href`,
every status code, the Timesheet and part counts — never through the adapter or its codec.
`tests/test_cdm_aixm511_adapter.py::test_the_adapter_agrees_with_the_independent_donlon_reading`
compares the adapter's output against it feature by feature and slice by slice.

Two readings the extract shows on independently authored data: `EAD21A` (a danger area drawn
with GeodesicStrings) becomes a CONTROL_MEASURE PlanObject with its Area; the `EADD` CTA is a
composition (`BASE` with a contributor plus `UNION`) and is typed component by component with no
Area drawn. The arc-bounded `EAP2` is refused under the default constructor and typed as
unsupported under `Aixm511Adapter(unsupported_geometry="report")`.

To rebuild: `python build_fixtures.py --donlon <directory holding the six source files>` from
`../spec/`; `--check` compares without writing.
