# Counterexamples — well-formed, schema-INVALID, each rejected at a declared layer

Every file here is XML that parses (the guarded parser admits it) and that the pinned AIXM 5.2.0
XSD closure REJECTS. Each is written by `../spec/build_fixtures.py` (2026-09-21) from
`../airspace_baseline_polygon.xml` — the last one from `../airport_runway_navaid.xml` — by one
deliberate breach. The adapter has two layers and the table says which one refuses what: the
NORMATIVE layer is `normative_validation.validate("aixm52", …)` through an actual validator (the
optional `validate` extra and the external schema directory with its catalog;
`BLOCKED_EXTERNAL_EVIDENCE`, never a pass, when either is absent); the ADAPTER layer is
`Aixm52Adapter.to_cdm`'s structural reading, which refuses only what it cannot read at all and
otherwise CARRIES a breach in the residual — `residual: structured`'s promise about an unknown
element — while `validate_source` says what it saw.
`tests/test_cdm_aixm52_adapter.py::test_every_counterexample_is_rejected_at_its_declared_layer`
and `::test_every_counterexample_is_invalid_against_the_pinned_schema` assert both columns.

| File | Breach | normative layer | adapter layer |
|---|---|---|---|
| `unknown_property_in_slice.xml` | `aixm:colour`, a property no AirspaceTimeSlice declares | INVALID (element not expected) | accepted; `aixm:colour` sits in `residual.data` at its position |
| `properties_out_of_order.xml` | `designator` before `type` (the 5.2 sequence is type, designator, localType, …) | INVALID (element not expected) | accepted; order is not a meaning this adapter reads |
| `status_outside_enumeration.xml` | `AirspaceActivation/status` = `SOMETIMES`, outside `CodeStatusAirspaceBaseType` | INVALID (union type) | accepted; the code is carried verbatim as `properties.status.value`; under a Timesheet it is not the Entity's status |
| `foreign_extension_element.xml` | an `aixm:extension` holding an element of an undeclared namespace, before `activation` | INVALID (element not expected) | accepted; the extension sits in `residual.data` in Clark form |
| `missing_interpretation.xml` | no `aixm:interpretation` on the slice | INVALID (interpretation expected) | REFUSED — the interpretation is what every property state is read under, and there is no default |
| `property_removed_in_5_2.xml` | `aixm:fieldElevationAccuracy` on an AirportHeliport — an AIXM 5.1.1 property with no element in 5.2 | INVALID (element not expected) | accepted; it is not a pinned 5.2 property, so it sits in `residual.data` at its position — the version binding is a schema fact, not a namespace string |

The sixth derivation the 5.1.1 set tried — a BASELINE whose `validTime` is a `gml:TimeInstant` —
is schema-VALID under 5.2 as under 5.1.1 (the XSD admits either primitive; only Temporality
Concept rule TS_001 forbids it). It lives in `../cases/baseline_with_time_instant_ts001.xml`,
where the adapter accepts it and `validate_source` names the rule.
