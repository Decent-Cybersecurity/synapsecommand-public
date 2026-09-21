# Counterexamples — well-formed, schema-INVALID, each rejected at a declared layer

Every file here is XML that parses (the guarded parser admits it) and that the pinned AIXM 5.1.1
XSD closure REJECTS. Each was derived on 2026-09-21 from `../airspace_baseline_polygon.xml` by one
deliberate breach. The adapter has two layers and the table says which one refuses what: the
NORMATIVE layer is `normative_validation.validate("aixm511", …)` through an actual validator (the
optional `validate` extra and the external schema directory; `BLOCKED_EXTERNAL_EVIDENCE`, never a
pass, when either is absent); the ADAPTER layer is `Aixm511Adapter.to_cdm`'s structural reading,
which refuses only what it cannot read at all and otherwise CARRIES a breach in the residual —
`residual: structured`'s promise about an unknown element — while `validate_source` says what it
saw. `tests/test_cdm_aixm511_adapter.py::test_every_counterexample_is_rejected_at_its_declared_layer`
and `::test_every_counterexample_is_invalid_against_the_pinned_schema` assert both columns.

| File | Breach | normative layer | adapter layer |
|---|---|---|---|
| `unknown_property_in_slice.xml` | `aixm:colour`, a property no AirspaceTimeSlice declares | INVALID (element not expected) | accepted; `aixm:colour` sits in `residual.data` at its position |
| `properties_out_of_order.xml` | `designator` before `type` (the schema's sequence is type, designator, …) | INVALID (element not expected) | accepted; order is not a meaning this adapter reads |
| `status_outside_enumeration.xml` | `AirspaceActivation/status` = `OPEN`, outside `CodeStatusAirspaceBaseType` | INVALID (union type) | accepted; the code is carried verbatim as `properties.status.value` and, being unconditional, as the Entity's `status.state` in the AIXM namespace |
| `foreign_extension_element.xml` | an `aixm:extension` holding an element of an undeclared namespace | INVALID (element not expected) | accepted; the extension sits in `residual.data` in Clark form |
| `missing_interpretation.xml` | no `aixm:interpretation` on the slice | INVALID (interpretation expected) | REFUSED — the interpretation is what every property state is read under, and there is no default |

A sixth derivation, a BASELINE whose `validTime` is a `gml:TimeInstant`, turned out to be
schema-VALID: the XSD admits either primitive on any slice and only the Temporality Concept's
coding rule TS_001 forbids it. It lives in `../cases/baseline_with_time_instant_ts001.xml`, where
the adapter accepts it and `validate_source` names the rule.
