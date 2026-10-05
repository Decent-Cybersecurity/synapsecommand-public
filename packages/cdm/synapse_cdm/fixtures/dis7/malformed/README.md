# Malformed DIS 7 payloads — every one synthetic, every one refused

These are **not fixtures**. The harness selects files that are immediate children of the fixture
directory (`harness.select_fixtures`), so this subdirectory is out of reach of checks A–F. It is
read by the conformance suite's check H:

```bash
python -m synapse_cdm.suite conformance run --adapter dis7 --require H
```

Each one must be REFUSED with a coded `Dis7Error`, returning no object.

| Payload | What is wrong with it | Refusal |
|---|---|---|
| `wrong_protocol_version.dis` | octet 0 is 6, not 7 (case N01) | `E_HEADER_UNSUPPORTED` at `byte[0]` |
| `pdu_type_67.dis` | octet 2 is 67, not 1 (case N02) | `E_HEADER_UNSUPPORTED` at `byte[2]` |
| `truncated_by_one_byte.dis` | 143 octets, one short of the fixed part (case N06) | `E_LENGTH_MISMATCH` at `byte[143]` |
| `one_trailing_byte.dis` | 145 octets against a header length of 144 (case N07) | `E_LENGTH_MISMATCH` at `byte[8]` |
| `envelope_unknown_key.json` | an envelope with a fourth top-level member | `E_TWIN_SCHEMA` at `$` |

All five are built from `../vectors/equator_eastbound.dis` and its envelope by the one change the
table states; `tests/test_cdm_dis7_adapter.py` rebuilds each and compares. None derives from
recorded traffic. A duplicate-key document is deliberately absent: the fixture loader's plain
JSON load would collapse the duplicate before the adapter saw it.
