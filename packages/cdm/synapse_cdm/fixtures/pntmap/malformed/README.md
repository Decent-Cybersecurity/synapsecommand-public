# Malformed pntmap payloads — every one synthetic, every one refused

These are **not fixtures**. Checks A–F never see them: the harness selects immediate children of
the fixture directory that are files (`harness.py:343`), so a subdirectory is out of its reach by
construction rather than by an exclusion somebody has to remember. They are read by the Synapse
Conformance Suite's check H (§21), and by nothing else:

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

Neither is derived from recorded traffic. Both are built from this directory's own synthetic
payloads by cutting or corrupting them, so they carry no third party's data and no standard's
text.
