# STANAG 4609 / MISP-2019.1 KLV fixtures

**There are none yet, and that is the state this directory is in rather than a step somebody
forgot.** Adapter `stanag4609` is at Phase 1: the row set in `../../FORMAT_COVERAGE.md` is written
with `not yet` in every status column and there is no adapter code, no codec and no payload. This
directory holds `spec/` and nothing else.

```bash
# Today this FAILS, deliberately, and it fails TWICE over — which is worth knowing before you
# debug it. The adapter name does not resolve yet, so `--adapter stanag4609` raises
# `LookupError: unknown adapter 'stanag4609'` and exits 1. Substitute any registered adapter and
# it fails again, this time on the directory: exit code 2, `NoFixturesFound`, because the only
# thing in here is spec/ and a run that exercises nothing must not report a green.
PYTHONPATH=packages/cdm python -m synapse_cdm.harness --adapter stanag4609 \
    --fixtures packages/cdm/synapse_cdm/fixtures/klv
```

**The directory is `klv` and the adapter is `stanag4609`, and the two names differ on purpose.**
The adapter takes the STANAG's number because STANAG 4609 is, in MISP-2019.1 §C.1.2's own words,
"a covering document rather than a standalone document, which points directly to a version of the
U.S. Motion Imagery Standards Profile (MISP)" — five pages, one of which is a Letter of
Promulgation — so there is no NATO document whose *content* could name the adapter. The directory
takes the content's name because a directory holds payloads and a payload is not a standard, which
is the same split that puts adapter `stanag4676`'s fixtures in `fixtures/nits`. The reasoning, and
the three rejected alternatives (`misp`, `misb`, `fmv`), are in `spec/klv_pin.json` and in the
`FORMAT_COVERAGE.md` section.

What is here:

- **`spec/klv_pin.json`** — the pinned identity of both documents and every value extracted from
  them that a ruling cites, each with its locus. Written first, for the reason the Legion, CAT021
  and CAT048 pins were: a quotation with no pin behind it is a recollection.
- **`spec/nato-stanag-4609-edition-5.pdf`** and **`spec/misb-misp-2019-1.pdf`** — in the working
  tree because they had to be read, and **not committed**, matching every other adapter here.
  `git ls-files | grep -c '\.pdf$'` is 0 across the whole repository.

| Document | SHA-256 | Bytes | Pages |
|---|---|---|---|
| `spec/nato-stanag-4609-edition-5.pdf` | `f2f9ae1a5a74528664a8751c3c105161f4597b1041928b7cedba1a57b2dbf8d8` | 273 801 | 5 |
| `spec/misb-misp-2019-1.pdf` | `3167362ace20746ed13e85522130c2e9f3fc9ecf62a112bd75bdced7b102d5ea` | 1 372 771 | 73 |

Those two rows are also stated in `spec/klv_pin.json` and in `../../FORMAT_COVERAGE.md`, and
`tests/test_cdm_format_coverage.py` checks **every** occurrence rather than any one of them — the
80b38d1 finding, which was that an `in` check is satisfied by one site while a fact stated at three
sites can drift at two.

## Why no fixture can be written yet

Not scheduling. A `.klv` payload is a sequence of key/length/value triplets, and **this phase does
not hold the document that says how a key or a length is written**: `MISP-2015.1-07` delegates the
encoding to SMPTE ST 336:2017, which is behind a paywall, and `MISP-2015.1-08` delegates the
formatting to MISB ST 0107.3, which is a public download that was not obtained. Writing bytes
anyway would produce a file that *looks* like KLV, a golden file recording what our own guess
decodes to, and a green harness run asserting that the two agree — the round-trip trap
`../../README.md` names under "Three things the harness cannot check for you": self-consistency
without an external anchor.

The twelve planned fixtures and the park that gates each one are tabulated in
`../../FORMAT_COVERAGE.md` under "The fixtures — planned here, before they exist". When the parks
close, each will ship as a twin — a `.klv` payload and a `.parsed.json` holding the parsed form the
never-drop check measures against — on the pattern `adsb`, `cat021` and `cat048` already use, and a
`spec/build_fixtures.py` will be their single source of truth.
