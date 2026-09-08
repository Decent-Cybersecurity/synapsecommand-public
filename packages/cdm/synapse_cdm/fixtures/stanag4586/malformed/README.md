# Malformed stanag4586 payloads — every one synthetic, every one refused

These are **not fixtures**. Checks A–F never see them: the harness selects immediate children of
the fixture directory that are files (`harness.py:343`), so a subdirectory is out of its reach by
construction rather than by an exclusion somebody has to remember. They are read by the Synapse
Conformance Suite's check H (§21), and by nothing else:

```bash
synapse conformance run --adapter stanag4586 --require H
```

Each one must be REFUSED — any exception except `SystemExit`, `KeyboardInterrupt`, `MemoryError`
or `RecursionError`, inside the time bound, returning no object — and the exception class is
recorded in the report. A refusal is the pass; a crash and an acceptance are both failures.

| Payload | What is wrong with it |
|---|---|
| `truncated_payload.s4586` | a datagram cut off inside its messages |
| `declared_length_longer_than_the_datagram.s4586` | §21's `invalid length`: the declared message length runs past the end of the datagram |

Neither is derived from recorded traffic. Both are built from this directory's own synthetic
payloads by cutting or corrupting them, so they carry no third party's data and no standard's
text.
