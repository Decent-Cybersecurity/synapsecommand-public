# Malformed pntmap payloads — every one synthetic, every one refused

These are **not fixtures**. Checks A–F never see them: the harness selects immediate children of
the fixture directory that are files (`harness.select_fixtures`, which executes
`harness.FIXTURE_PATTERN`), so a subdirectory is out of its reach by construction rather than by
an exclusion somebody has to remember. They are read by the Synapse Conformance Suite's check H
(§21), and by nothing else:

```bash
synapse conformance run --adapter pntmap --require H
```

Each one must be REFUSED — any exception except `SystemExit`, `KeyboardInterrupt`, `MemoryError`
or `RecursionError`, inside the time bound, returning no object — and the exception class is
recorded in the report. A refusal is the pass; a crash and an acceptance are both failures.

| Payload | What is wrong with it |
|---|---|
| `a_truncated_record.json` | an alert carrying only its first few fields — well-formed JSON that is not a well-formed PNTMAP alert |
| `malformed_json.json` | §21's `malformed JSON`. It is refused by the fixture LOADER rather than by the adapter, because JSON is what the loader parses, and the suite records which layer refused |
| `a_json_list.json` | a well-formed alert wrapped in a JSON array. The loader parses it and the ADAPTER must refuse it, as a `ValueError` naming the shape: added 2026-09-16, when a bare array stopped surfacing as an `AttributeError` from inside the decoder |

None is derived from recorded traffic. All three are built from this directory's own synthetic
payloads by cutting, corrupting or wrapping them, so they carry no third party's data and no
standard's text.
