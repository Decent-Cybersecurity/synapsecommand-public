# TAK egress fixtures

CDM `PlanObject`s and the CoT drawing each one becomes. **Not** run by the harness: `run()`
replays every fixture through `to_cdm()`, so an egress payload placed beside the ingest
fixtures would be fed to the CoT parser and fail. They live in this subdirectory because the
harness iterates files and skips directories, so pointing it at `fixtures/tak` still works.

They are exercised by `tests/test_cdm_tak_adapter.py`, which is where the round-trip check for
this adapter has to live anyway: the harness's `roundtrip` column reports SKIP for an adapter
that emits XML, because it cannot compare a structure it cannot parse.

Goldens are the emitted CoT under the frozen clock (`times.FROZEN_NOW`), so `@time` and
`@start` on a drawing — which a plan does not carry and which are therefore the emission
instant — are stable.
