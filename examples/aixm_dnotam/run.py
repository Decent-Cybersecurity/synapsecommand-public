#!/usr/bin/env python3
"""Demonstration 2 — AIXM 5.1.1 baseline plus Digital NOTAM: a runway closure and an airspace
activation, their effective windows at several as-of times, a correction, a cancellation and an
unresolved state.

    python examples/aixm_dnotam/run.py            # run and check; exit 0 only on agreement
    python examples/aixm_dnotam/run.py --update   # rewrite expected/ from this run

One command, self-checking. It reads the packaged synthetic fixtures of `fixtures/aixm511/dnotam/`
through the AIXM 5.1.1 adapter — one canonical Entity per time slice, the Event's own slices with
the `aixm-dnotam/1` block, NOTHING resolved by the adapter — and hands the objects, together with
an instant, to the separate deterministic resolver `synapse_cdm.aixm_resolve`, which applies the
AIXM Temporality Concept 1.1 and the Digital NOTAM Specification 2.0 (DRAFT) coding rules and
reports the view they yield. At every as-of time the script asserts the outcome it expects
(written here, by hand, from the fixture's own stated instants and the published rules) and it
compares the whole report with `expected/aixm_dnotam.report.json` byte for byte.

The five parts, each a synthetic document whose baseline and change are stated slices:

1. `rwy_cls_baseline_and_closure.xml` — RWY.CLS: the runway direction is NORMAL before 06:00Z,
   CLOSED from 06:00:00Z (begin included) to 09:59:59Z, NORMAL again at 10:00:00Z (end excluded).
2. `atsa_act_baseline_and_activation.xml` — ATSA.ACT: the TMA's baseline activation is scheduled
   (typed, not asserted); the TEMPDELTA asserts ACTIVE for its window and replaces the baseline's
   structures in full (ER-04); the baseline schedule stands again after it.
3. `corrections_out_of_order.xml` — a correction received BEFORE the slice it corrects ends the
   closure at 08:00Z; the resolver's valid slice is the highest correction, whatever the order.
4. `cases/cancellation.xml` — a future closure cancelled before effect (§4.4.8): the sequence is
   off the timeline, its record stands, the baseline NORMAL applies; WITHOUT the baseline objects
   the same instant is UNRESOLVED and nothing is asserted.
5. `unresolved_references.xml` — a closure whose Event and baseline are not in what the caller
   passed: the TEMPDELTA's own assertion is known, the feature's state is UNRESOLVED, the binding
   is an unresolved reference kept with its href.

This is PUBLISHED-RULE PROCESSING: what the AIXM temporality rules and the Digital NOTAM coding
rules say about slices a caller hands over. It is not planning, not airspace deconfliction and
not a NOTAM generator, and "unresolved" and "ambiguous" are results it reports, not failures it
hides. Every input is synthetic (fictitious aerodrome ZZSY; UUIDs under a1a40000-).
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from synapse_cdm import aixm_resolve, times
from synapse_cdm.adapter import packaged_fixtures
from synapse_cdm.adapters.aixm511 import Aixm511Adapter, AsOf

HERE = pathlib.Path(__file__).resolve().parent
EXPECTED = HERE / "expected" / "aixm_dnotam.report.json"
RWY_DIR = "a1a40000-00d0-4000-8000-000000000002"
TMA = "a1a40000-00d0-4000-8000-000000000003"
EVENT_1 = "a1a40000-00e0-4000-8000-000000000001"
EVENT_2 = "a1a40000-00e0-4000-8000-000000000002"
#: The instant a cancelling correction (no validTime of its own) is read at; a caller's statement.
CANCELLATION_AS_OF = AsOf("2026-03-25T12:00:00Z",
                          "the synthetic issue instant of the cancellation, stated by the fixture's author")

#: (part, document, feature, as-of instant, expected outcome, expected source, expected status
#:  state, expected asserted status, the note the report carries).
STEPS: list[tuple[str, str, str, str, str, str, str, str | None, str]] = [
    ("1 runway closure", "rwy_cls_baseline_and_closure.xml", RWY_DIR, "2026-03-10T05:59:59Z", "resolved", "BASELINE", "asserted", "NORMAL", "one second before the closure begins: the baseline NORMAL"),
    ("1 runway closure", "rwy_cls_baseline_and_closure.xml", RWY_DIR, "2026-03-10T06:00:00Z", "resolved", "TEMPDELTA", "asserted", "CLOSED", "the begin instant is included (§4.4.1): CLOSED"),
    ("1 runway closure", "rwy_cls_baseline_and_closure.xml", RWY_DIR, "2026-03-10T08:00:00Z", "resolved", "TEMPDELTA", "asserted", "CLOSED", "inside the window; the NORMAL copy beside the CLOSED branch is kept, not ranked"),
    ("1 runway closure", "rwy_cls_baseline_and_closure.xml", RWY_DIR, "2026-03-10T09:59:59Z", "resolved", "TEMPDELTA", "asserted", "CLOSED", "the last second of the window"),
    ("1 runway closure", "rwy_cls_baseline_and_closure.xml", RWY_DIR, "2026-03-10T10:00:00Z", "resolved", "BASELINE", "asserted", "NORMAL", "the end instant is excluded (§4.4.1): expired, the baseline NORMAL"),
    ("2 airspace activation", "atsa_act_baseline_and_activation.xml", TMA, "2026-03-12T04:00:00Z", "resolved", "BASELINE", "scheduled", None, "before the Event: the baseline's scheduled ACTIVE / INACTIVE, typed and not asserted"),
    ("2 airspace activation", "atsa_act_baseline_and_activation.xml", TMA, "2026-03-12T05:00:00Z", "resolved", "TEMPDELTA", "asserted", "ACTIVE", "the activation begins: one unscheduled ACTIVE replaces the baseline's two structures (ER-04)"),
    ("2 airspace activation", "atsa_act_baseline_and_activation.xml", TMA, "2026-03-12T08:59:59Z", "resolved", "TEMPDELTA", "asserted", "ACTIVE", "the last second of the activation"),
    ("2 airspace activation", "atsa_act_baseline_and_activation.xml", TMA, "2026-03-12T09:00:00Z", "resolved", "BASELINE", "scheduled", None, "the activation has expired: the baseline schedule stands again"),
    ("3 correction", "corrections_out_of_order.xml", RWY_DIR, "2026-03-10T07:00:00Z", "resolved", "TEMPDELTA", "asserted", "CLOSED", "correction 1.1 (received first) keeps the begin and moves the end to 08:00Z; CLOSED at 07:00Z"),
    ("3 correction", "corrections_out_of_order.xml", RWY_DIR, "2026-03-10T09:00:00Z", "resolved", "BASELINE", "asserted", "NORMAL", "at 09:00Z the ORIGINAL 1.0 would still be closed; the correction (§3.6) has ended it — NORMAL"),
    ("4 cancellation", "cases/cancellation.xml", RWY_DIR, "2026-06-01T07:00:00Z", "resolved", "BASELINE", "asserted", "NORMAL", "the closure was cancelled before effect (§4.4.8): its record stands, the baseline NORMAL applies"),
    ("5 unresolved", "unresolved_references.xml", RWY_DIR, "2026-03-10T07:00:00Z", "unresolved", "TEMPDELTA", "asserted", "CLOSED", "no baseline was passed: the TEMPDELTA's CLOSED is what the source asserts, the feature is UNRESOLVED"),
    ("5 unresolved", "unresolved_references.xml", RWY_DIR, "2026-03-11T00:00:00Z", "unresolved", "none", "not stated", None, "outside the change, with no baseline: nothing is stated and nothing is invented"),
]


def load(fixtures: pathlib.Path, name: str, **kwargs):
    adapter = Aixm511Adapter(clock=times.frozen_clock(), **kwargs)
    return adapter.to_cdm((fixtures / name).read_bytes())


def summary(resolution: aixm_resolve.Resolution) -> dict:
    return {
        "outcome": resolution.outcome, "source_of_status": resolution.source_of_status,
        "status_state": resolution.status_state, "asserted_status": resolution.asserted_status,
        "statuses": [s.code if not s.nil else None for s in resolution.statuses],
        "operative": [s.code for s in resolution.operative],
        "history": [(h.interpretation, h.sequence_number, h.disposition) for h in resolution.history],
        "findings": resolution.findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--update", action="store_true", help="rewrite expected/ from this run")
    args = parser.parse_args(argv)
    fixtures = packaged_fixtures(Aixm511Adapter) / "dnotam"
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    objects: dict[str, list] = {}
    report: dict = {"demonstration": "AIXM 5.1.1 baseline + Digital NOTAM (RWY.CLS, ATSA.ACT) — published-rule "
                                     "processing with synapse_cdm.aixm_resolve; not planning, not deconfliction",
                    "documents": {}, "steps": [], "events": {}, "cancellation_without_baseline": None}
    for name in sorted({s[1] for s in STEPS}):
        kwargs = {"as_of": CANCELLATION_AS_OF} if name.startswith("cases/") else {}
        objects[name] = load(fixtures, name, **kwargs)
        adapter = Aixm511Adapter(clock=times.frozen_clock(), **kwargs)
        check(f"{name}: the adapter resolves nothing — one Entity per time slice, every slice kept",
              all(o.object_kind == "entity" for o in objects[name])
              and len({o.source_ids[1].external_id for o in objects[name]}) == len(objects[name]))
        report["documents"][name] = {
            "slices": [o.source_ids[1].external_id for o in objects[name]],
            "dnotam": {o.source_ids[1].external_id: {"role": o.attributes["dnotam"]["role"],
                                                    "assertion": o.attributes["dnotam"]["assertion"]["kind"],
                                                    "scenario": o.attributes["dnotam"].get("event_scenario")
                                                    or (o.attributes["dnotam"].get("scenario") or {}).get("value"),
                                                    "rule_findings": o.attributes["dnotam"]["rule_findings"]}
                       for o in objects[name] if "dnotam" in o.attributes},
            "validate_source": [p for p in adapter.validate_source((fixtures / name).read_bytes())
                                if "outside the five pinned families" not in p],
        }

    for part, name, feature, instant, outcome, source, state, asserted, note in STEPS:
        resolution = aixm_resolve.resolve(objects[name], feature, instant)
        got = (resolution.outcome, resolution.source_of_status, resolution.status_state, resolution.asserted_status)
        check(f"{part} @ {instant}: {outcome}/{source}/{state}/{asserted}", got == (outcome, source, state, asserted),
              f"got {'/'.join(str(g) for g in got)}" if got != (outcome, source, state, asserted) else note)
        report["steps"].append({"part": part, "document": name, "feature": feature, "as_of": instant, "note": note,
                                **summary(resolution)})

    # The Event's own state, at instants on both sides of each window.
    for name, event, instants in (("rwy_cls_baseline_and_closure.xml", EVENT_1, ("2026-03-10T05:00:00Z", "2026-03-10T07:00:00Z", "2026-03-10T10:00:00Z")),
                                  ("atsa_act_baseline_and_activation.xml", EVENT_2, ("2026-03-12T04:00:00Z", "2026-03-12T06:00:00Z")),
                                  ("corrections_out_of_order.xml", EVENT_1, ("2026-03-10T07:00:00Z", "2026-03-10T09:00:00Z")),
                                  ("cases/cancellation.xml", EVENT_1, ("2026-06-01T07:00:00Z",))):
        states = []
        for instant in instants:
            e = aixm_resolve.event_state(objects[name], event, instant)
            states.append({"as_of": instant, "state": e.state, "in_force": e.in_force.identity if e.in_force else None,
                           "scenario": e.scenario, "version": e.scenario_version,
                           "history": [(h.sequence_number, h.disposition, h.valid.assertion_kind if h.valid else None) for h in e.history]})
        report["events"][f"{name}#{event}"] = states
    expected_event_states = {
        "rwy_cls_baseline_and_closure.xml#" + EVENT_1: ["future", "active", "ended"],
        "atsa_act_baseline_and_activation.xml#" + EVENT_2: ["future", "active"],
        "corrections_out_of_order.xml#" + EVENT_1: ["active", "ended"],
        "cases/cancellation.xml#" + EVENT_1: ["cancelled"],
    }
    for key, expected in expected_event_states.items():
        got = [s["state"] for s in report["events"][key]]
        check(f"Event {key.split('#')[0]}: {' -> '.join(expected)}", got == expected, f"got {got}" if got != expected else "")
    check("the terminating correction carries a NOTAM C and is typed 'termination'",
          report["events"]["corrections_out_of_order.xml#" + EVENT_1][1]["history"][0][2] == "termination")
    check("the cancelled Event's valid slice is typed 'cancellation' and its 1.0 stays on record",
          report["events"]["cases/cancellation.xml#" + EVENT_1][0]["history"][0] == (1, "cancelled", "cancellation"))

    # The cancellation without its baseline: unresolved, never NORMAL.
    without = [o for o in objects["cases/cancellation.xml"] if o.attributes["aixm"]["time_slice"]["interpretation"] != "BASELINE"
               or o.attributes["aixm"]["feature"]["element"] == "event:Event"]
    stripped = aixm_resolve.resolve(without, RWY_DIR, "2026-06-01T07:00:00Z")
    report["cancellation_without_baseline"] = summary(stripped)
    check("4 cancellation without the baseline objects: UNRESOLVED and nothing asserted",
          (stripped.outcome, stripped.asserted_status, stripped.statuses) == ("unresolved", None, [])
          and [h.disposition for h in stripped.history] == ["cancelled"],
          "a cancellation never turns an unknown baseline into an asserted availability")
    unresolved = objects["unresolved_references.xml"]
    binding = [o for o in unresolved if o.attributes.get("dnotam", {}).get("role") == "affected-feature"][0]
    check("5 unresolved: the binding's theEvent is kept unresolved with its href",
          binding.attributes["dnotam"]["the_event"]["resolved"] is False
          and binding.attributes["dnotam"]["the_event"]["href"] == "urn:uuid:a1a40000-00e0-4000-8000-000000000099")
    check("determinism: the same objects and instants give the same report",
          all(summary(aixm_resolve.resolve(objects[s[1]], s[2], s[3])) == summary(aixm_resolve.resolve(list(reversed(objects[s[1]])), s[2], s[3]))
              for s in STEPS))

    document = (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    if args.update:
        EXPECTED.parent.mkdir(parents=True, exist_ok=True)
        EXPECTED.write_bytes(document)
        check("expected/ rewritten from this run", True, str(EXPECTED.relative_to(HERE.parent.parent)))
    else:
        check("the report equals expected/ byte for byte", EXPECTED.exists() and EXPECTED.read_bytes() == document,
              "run with --update after reviewing a deliberate change")

    print("AIXM 5.1.1 baseline + Digital NOTAM -> CDM -> aixm_resolve (published-rule processing; not planning)")
    width = max(len(name) for name, _, _ in results)
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}".rstrip())
    failed = [name for name, ok, _ in results if not ok]
    print(f"{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
