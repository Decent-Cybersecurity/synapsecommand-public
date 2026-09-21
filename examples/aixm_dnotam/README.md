# Demonstration 2 — AIXM 5.1.1 baseline plus Digital NOTAM: effective windows, a correction, a cancellation, an unresolved state

```
python examples/aixm_dnotam/run.py            # offline; one command; exit 0 only when every check agrees
python examples/aixm_dnotam/run.py --update   # rewrite expected/aixm_dnotam.report.json after a reviewed change
```

`run.py` reads five synthetic documents the package ships under `fixtures/aixm511/dnotam/` —
AIXM 5.1.1 (April 2016) with the Digital NOTAM Event Schema 2.0.m — through `adapters/aixm511.py`,
which produces one canonical Entity per time slice (the baseline slice, the Event's slices with
their `aixm-dnotam/1` block, the bound TEMPDELTA with its own source assertion) and **resolves
nothing**. It then hands those objects and an instant to the separate deterministic resolver
`synapse_cdm.aixm_resolve`, and checks twenty-nine expectations it states itself, at every as-of
time, from the fixtures' stated instants and the published rules:

1. **Runway closure** (`RWY.CLS`): NORMAL at 05:59:59Z, CLOSED from 06:00:00Z (begin included,
   Temporality Concept 1.1 §4.4.1) through 09:59:59Z, NORMAL again at 10:00:00Z (end excluded);
   the `NORMAL` copy the coding rule puts beside the `CLOSED` branch (RWY.CLS.03) is kept and
   listed, and the `CLOSED` branch is operative.
2. **Airspace activation** (`ATSA.ACT`): the TMA's baseline activation is a schedule (typed,
   never asserted); the TEMPDELTA's one unscheduled `ACTIVE` replaces the baseline's structures in
   full for its window (ER-04); the schedule stands again after it.
3. **Correction**, received before the slice it corrects: the valid slice is the highest
   correction number (§3.6) whatever the document order, so the closure ends at 08:00Z and the
   Event is `ended` with a `termination` assertion (its NOTAM C).
4. **Cancellation** before effect (§4.4.8): the sequence is off the timeline, its 1.0 slice stays
   on record, the baseline NORMAL applies — and with the baseline objects withheld the same
   instant is UNRESOLVED with nothing asserted: a cancellation never turns an unknown baseline
   into an availability.
5. **Unresolved state**: a closure whose Event and baseline the caller did not pass — the
   TEMPDELTA's own CLOSED is what the source asserts, the feature is UNRESOLVED, the binding is
   an unresolved reference kept with its href, and outside the window nothing is stated and
   nothing is invented.

The whole report (every step's outcome, source, status state, operative structures, per-sequence
history and findings; the Events' states; the documents' slices and `validate_source` findings) is
committed under `expected/aixm_dnotam.report.json` and compared byte for byte.

**What this is, and is not.** This is published-rule processing: the AIXM Temporality Concept 1.1
(the valid correction, begin-included / end-excluded validity, the abandoned change, TS_005 /
TS_009 / TS_011 / TS_017 / TS_019) and the Digital NOTAM Specification 2.0 coding rules (a
**DRAFT**, never described here as an approved final standard) applied to slices a caller hands
over, with "unresolved" and "ambiguous" reported as results. It is not planning, not airspace
deconfliction and not a NOTAM generator; the resolver evaluates no Timesheet against the instant
(a scheduled status stays `scheduled`), holds no state between calls and reads no file, socket or
clock. The script claims no schema validity: the normative validation of every fixture against the
pinned AIXM 5.1.1 + Event 2.0.m closure is `tests/test_cdm_aixm511_dnotam.py`'s (BLOCKED, never
PASS, without the external resource and the `validate` extra).

Every input is synthetic — the fictitious aerodrome `ZZSY`, designators `SYN*`, UUIDs under
`a1a40000-` — and written by `fixtures/aixm511/dnotam/spec/build_fixtures.py`.
