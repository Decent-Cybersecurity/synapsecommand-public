# CDM semantic validation rules

**Status: normative for CDM 2.1.0. Introduced 2026-09-19 (audit finding F04).**

The CDM contract is validated at two levels, and this document is the second one.

**Structural validation** is what the published JSON Schema (`schemas/*.schema.json`, draft
2020-12) states: object shape, required keys, no unknown keys (`additionalProperties: false`),
enumerations, numeric bounds, string patterns, and the one `format` (`uuid`) — which a validator
must be told to assert. The Python models state the same constraints through their types and
`Field` keywords, and the two are held to the same answers on the same bytes by
`tests/test_cdm_schema_alignment.py`. Every portable constraint lives in the schema: since this
document was introduced, `adapter_version` and `schema_version` carry the semver `pattern`
(`version.SEMVER_PATTERN`), `symbol` carries the twenty-digit pattern, `ontology_types` carries
`uniqueItems`, and every timestamp carries the RFC 3339 pattern with exactly three decimals and `Z`.

**Semantic validation** is the rule set below: the constraints JSON Schema cannot express
(cross-field relations, content of a coordinate, the shape of a payload that depends on another
field) or cannot express without a contract change this edition does not make (SEM-001). Each rule
has a stable identifier, and an implementation's finding for a rule carries that identifier.

A claim of CDM conformance for an object requires **both** levels to pass. The reference
assessment (`python -m synapse_cdm.conformance`, dimension A) reports the two classes separately
— `structural` and `semantic` lists beside the combined `findings` — and its detail line counts
each. A finding is never moved from one class to the other to make a level pass.

## Rules

| ID | Applies to | Rule | Why it is not in the JSON Schema |
|----|------------|------|----------------------------------|
| SEM-001 | any `geometry`, `Area.geometry` | The geometry object carries its GeoJSON `type` tag (`Point`, `LineString`, `Polygon`, `MultiPoint`, `MultiLineString`, `MultiPolygon`). | The schema publishes the union as `oneOf` plus an OpenAPI `discriminator`, which JSON Schema validators ignore. A type-less object that fits exactly one branch passes the schema. Requiring `type` grows a `required` list on a published object, which `MIGRATIONS.md` classes as MAJOR; the option is recorded for the next major. |
| SEM-002 | `Polygon`, `MultiPolygon` | Every linear ring has at least four positions and its first position equals its last (RFC 7946 §3.1.6); every MultiPolygon part has at least one ring. | Equality between two array elements is not expressible. |
| SEM-003 | every position | A position is `[lon, lat]` or `[lon, lat, alt]` with longitude in [-180, 180] and latitude in [-90, 90]; every LineString and every MultiLineString part has at least two positions (RFC 7946 §3.1.4). | The nesting depth of `coordinates` differs per geometry type; per-position bounds at each depth are not stated by the published schema this edition. |
| SEM-004 | `Position` | When `vertical` is metres above the WGS84 ellipsoid (`unit` m, `reference` HAE), `alt_m`, if present, equals `vertical.value`; for any other unit or reference `alt_m` is absent. | Cross-field. |
| SEM-005 | `Period` | `end`, when present, is not before `start`. | Cross-field comparison of timestamps. |
| SEM-006 | `TemporalValidity` | `valid_to`, when present, is not before `valid_from`, when present. | Cross-field comparison of timestamps. |
| SEM-007 | `Entity` | `valid_to`, when present, is not before `valid_from`. | Cross-field comparison of timestamps. |
| SEM-008 | `RouteLeg` | `from_seq` differs from `to_seq`. | Cross-field. |
| SEM-009 | `Route` | No two waypoints share a `sequence`; every leg's `from_seq` and `to_seq` is the `sequence` of a waypoint in the same route. | Cross-element uniqueness of a nested key and a reference between two arrays. |
| SEM-010 | `Entity.ontology_types` | Every entry is a valid identifier — a governed SynapseCommand term matching the governed grammar, or an absolute third-party identifier with a valid scheme and no whitespace or control character — and no entry repeats. | The identifier grammar is a decision procedure over two namespaces (`spec/sc-oes/09-entity-semantics.md`). Uniqueness IS in the schema (`uniqueItems`); the grammar is not. |
| SEM-011 | `Event.payload` | When `event_type` has a registered payload model (`GNSS_INTERFERENCE` → `GnssInterferencePayload`), the payload validates against it; keys the model does not declare are preserved. | The payload's shape depends on a sibling field. |
| SEM-012 | `Track.samples` | Samples are in non-decreasing `observed_at` order. | Ordering across array elements. |
| SEM-013 | `PlanObject` | When both `expires_at` and `validity.valid_to` are present they are equal. | Cross-field. |

Rules carried by the SC-OES layer (an event's `oes` block: self-relations, membership of
`entity_relations` subjects in `related_entities`) are the SC-OES specification's, are assessed by
conformance dimension B, and are not numbered here.

## Corpus

`tests/semantic_corpus/SEM-nnn.json` holds, per rule, at least one document that passes both
levels and one that passes the structural level and fails the rule, with the expected verdict of
each class and the substring (the rule identifier) the finding must carry. `STRUCTURAL.json` holds
the contrast: documents the schema alone refuses. Every document is synthetic. The corpus is plain
JSON so another implementation can replay it; `tests/test_cdm_semantic_corpus.py` is this
package's replay, and it also holds this table, the corpus and the validators' messages to one
identifier set.

## Changing a rule

Adding a rule appends the next identifier and a corpus file; it is a MINOR of the package when it
refuses documents that passed before, by `MIGRATIONS.md`'s table (an accepted input language
narrowed). Removing or relaxing a rule keeps the identifier in this table with the word
*withdrawn* and the date. Identifiers are never reused.
