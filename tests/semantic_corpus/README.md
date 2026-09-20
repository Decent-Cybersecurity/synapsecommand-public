# Semantic-rule corpus

One file per rule of `docs/cdm-semantic-rules.md`, named by the rule's
identifier, plus `STRUCTURAL.json`, which shows the other class for contrast. Every file is
plain JSON and is meant to be replayed by any implementation, not only this package's:

```json
{
  "rule": "SEM-005",
  "cases": [
    {"name": "...", "document": {<one CDM object>},
     "expected": {"structural": "PASS|FAIL", "semantic": "PASS|FAIL", "finding_contains": "..."}}
  ]
}
```

`structural` is the verdict of the published JSON Schema (draft 2020-12, format assertion on)
together with the model's type-level checks; `semantic` is the verdict of the rule set. The two
are reported separately and both must PASS for the object to pass dimension A of the
conformance assessment. `finding_contains` is a substring every implementation's finding for
the failing class must carry — for a semantic case that is the rule identifier.

`tests/test_cdm_semantic_corpus.py` replays every file through `synapse_cdm.conformance.assess`
and holds the identifiers in the specification, in the corpus and in the validators' messages to
one set. Every document here is synthetic.
