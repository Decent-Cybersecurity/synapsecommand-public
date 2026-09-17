# Malformed nits payloads — every one synthetic, every one refused

These are **not fixtures**. Checks A–F never see them: the harness selects immediate children of
the fixture directory that are files (`harness.select_fixtures`, which executes
`harness.FIXTURE_PATTERN`), so a subdirectory is out of its reach by construction rather than by
an exclusion somebody has to remember. They are read by the Synapse Conformance Suite's check H
(§21), and by nothing else:

```bash
synapse conformance run --adapter stanag4676 --require H
```

Each one must be REFUSED — any exception except `SystemExit`, `KeyboardInterrupt`, `MemoryError`
or `RecursionError`, inside the time bound, returning no object — and the exception class is
recorded in the report. A refusal is the pass; a crash and an acceptance are both failures.

| Payload | What is wrong with it |
|---|---|
| `truncated_payload.nits.xml` | a document cut off mid-element |
| `not_well_formed_xml.nits.xml` | §21's `invalid XML`: a stray `<` where an element name belongs |
| `deeply_nested.nits.xml` | the `standalone_basic_track` fixture with one unmodelled element nested one thousand deep — under 30 KB, far inside `max_input_bytes`, and past the declared `max_depth` of 64. Added 2026-09-16 with the bound: before it, this document made the adapter raise `RecursionError` out of `ET.tostring`, which is a crash class and not a refusal |

None is derived from recorded traffic. All three are built from this directory's own synthetic
payloads by cutting, corrupting or nesting them, so they carry no third party's data and no
standard's text.
