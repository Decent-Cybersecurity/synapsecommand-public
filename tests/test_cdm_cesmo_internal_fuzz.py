"""The kit's C40 fuzz target for `cesmo_internal`: seeded, deterministic mutations of the five kit
examples, as octets and as dicts.

Every outcome is either a `CesmoError` whose code is one the codec raises and whose message is at
most 512 characters, the same refusal `validate_source` reports, or an accepted Exchange whose
every object carries its record and its envelope verbatim in the residual. Anything else — another
exception class, a hang, a residual that is not the source — fails. The suite runs
`FUZZ_MUTATIONS` of them; the kit's full target of at least 100,000 is the entry point

    python -I -B tests/test_cdm_cesmo_internal_fuzz.py --fuzz 100000 [--seed 34]

which prints the outcome counts and the index of every failing mutation (the preserved seed: the
same seed and index rebuild it), and exits 1 on any failure.

PACKAGE-ONLY: the adapter, its codec and the kit examples under `fixtures/cesmo_internal/`, through
`synapse_cdm.__file__`.
"""

from __future__ import annotations

import collections
import copy
import json
import pathlib
import random
import sys

import synapse_cdm
from synapse_cdm import times
from synapse_cdm.adapters.cesmo_internal import CesmoInternalAdapter
from synapse_cdm.adapters.cesmo_internal_codec import RAISED_CODES, CesmoError

SET = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures" / "cesmo_internal"
KIT = (
    "empty-complete-snapshot.json",
    "observation.json",
    "status.json",
    "upsert.json",
    "withdrawal.json",
)
#: How many mutations the suite runs (DECISIONS C-11: at least 2,000).
FUZZ_MUTATIONS = 2_000
#: The default seed: the adapter's ordinal.
SEED = 34

#: Fragments spliced into the octets: framing, number literals and nesting near every bound.
FRAGMENTS = (
    b"{",
    b"}",
    b"[",
    b"]",
    b",",
    b":",
    b'"',
    b"\\",
    b" ",
    b"\n",
    b"NaN",
    b"Infinity",
    b"-0",
    b"1e400",
    b"1e-400",
    b"4.0",
    b"9" * 310,
    b"9" * 309,
    b'"\\ud800"',
    b"\xff",
    b"\xc0\xaf",
    b"\xef\xbb\xbf",
    b"null",
    b"true",
    b'"$snapshot"',
    b'"TEST-NET\\n"',
    b'"2026-10-04T24:00:00Z"',
    b"[" * 13 + b"]" * 13,
    b"[" * 61 + b"]" * 61,
    b'"x": 1, "x": 2',
    b'"' + b"x" * 4097 + b'"',
)
#: Values put at a node of the parsed document.
VALUES = (
    None,
    True,
    False,
    0,
    -1,
    4.0,
    1.5,
    -0.0,
    2**53,
    2**53 - 1,
    10**400,
    float("nan"),
    float("inf"),
    "",
    "x" * 4097,
    "TEST-NET\n",
    "$snapshot",
    "2026-10-04T24:00:00Z",
    "2026-02-30T00:00:00Z",
    "2026-10-04T12:00:00.123456Z",
    "live",
    "synthetic",
    "eob_upsert",
    "eob_delete",
    "status",
    "observation",
    [],
    {},
    [[[[[[[[[[[[[[]]]]]]]]]]]]]],
    {"k": [1, {"v": None}]},
    "\ud800",
    b"x",
    (1,),
)


def _value(rng: random.Random):
    """A fresh copy, so no mutation shares a container with VALUES or with another mutation."""
    return copy.deepcopy(rng.choice(VALUES))


def _nodes(node, path=()):
    yield path, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _nodes(value, path + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _nodes(value, path + (index,))


def _octets(rng: random.Random, octets: bytes) -> bytes:
    data = bytearray(octets)
    for _ in range(rng.randint(1, 3)):
        op = rng.randrange(6)
        at = rng.randrange(len(data) + 1)
        if op == 0 and data:
            data[min(at, len(data) - 1)] = rng.randrange(256)
        elif op == 1:
            data[at:at] = rng.choice(FRAGMENTS)
        elif op == 2:
            del data[at : at + rng.randint(1, 16)]
        elif op == 3:
            del data[at:]
        elif op == 4 and data:
            start = rng.randrange(len(data))
            data[at:at] = data[start : start + rng.randint(1, 64)]
        else:
            data[at:at] = str(rng.choice((0, -1, 2**53, 10**20, 7.25))).encode()
    return bytes(data)


def _document(rng: random.Random, document: dict) -> dict:
    document = copy.deepcopy(document)
    for _ in range(rng.randint(1, 3)):
        nodes = list(_nodes(document))
        path, _node = rng.choice(nodes)
        op = rng.randrange(6)
        parent = document
        for token in path[:-1]:
            parent = parent[token]
        if not path:
            if op == 0:
                document[rng.choice(("unknown", "snapshot", "records"))] = _value(rng)
            continue
        key = path[-1]
        if op in (0, 1):
            parent[key] = _value(rng)
        elif op == 2 and isinstance(parent, dict):
            del parent[key]
        elif op == 3 and isinstance(parent, list):
            parent.insert(key, copy.deepcopy(parent[key]))
        elif op == 4 and isinstance(parent[key], dict):
            parent[key]["unknown_" + str(rng.randrange(3))] = _value(rng)
        else:
            nested = parent[key]
            for _ in range(rng.choice((1, 12, 13, 60, 61))):
                nested = [nested]
            parent[key] = nested
    return document


def mutation(seed: int, index: int, sources: dict[str, bytes]) -> tuple[str, bytes | dict]:
    """The `index`-th mutation of a seed: rebuilt from the two numbers alone."""
    rng = random.Random(seed * 1_000_003 + index)
    name = KIT[rng.randrange(len(KIT))]
    if rng.randrange(2) == 0:
        return f"{name}/octets", _octets(rng, sources[name])
    return f"{name}/dict", _document(rng, json.loads(sources[name]))


def outcome(adapter: CesmoInternalAdapter, payload) -> str:
    """The code a refusal carries, or ACCEPTED; raises AssertionError on a broken invariant and
    lets any unexpected exception propagate (it is a failure)."""
    try:
        objects = adapter.to_cdm(payload)
    except CesmoError as refusal:
        assert refusal.code in RAISED_CODES, refusal.code
        assert len(str(refusal)) <= 512
        assert adapter.validate_source(payload)[0] == str(refusal)
        return refusal.code
    document = json.loads(payload) if isinstance(payload, bytes) else payload
    envelope = {k: v for k, v in document.items() if k != "records"}
    assert adapter.validate_source(payload) == []
    for obj in objects:
        index = obj.source.record_index
        if index is None:
            assert obj.residual.data == {"envelope": envelope}
        else:
            assert obj.residual.data == {"envelope": envelope, "record": document["records"][index]}
    return "ACCEPTED"


def run(count: int, seed: int = SEED) -> tuple[collections.Counter, list[tuple[int, str, str]]]:
    sources = {name: (SET / name).read_bytes() for name in KIT}
    adapter = CesmoInternalAdapter(times.frozen_clock())
    seen: collections.Counter = collections.Counter()
    failures = []
    for index in range(count):
        label, payload = mutation(seed, index, sources)
        try:
            seen[outcome(adapter, payload)] += 1
        except Exception as problem:  # noqa: BLE001 - every unexpected outcome is recorded, then fails
            failures.append((index, label, f"{type(problem).__name__}"))
    return seen, failures


def test_the_seeded_mutations_end_in_a_listed_refusal_or_a_faithful_residual():
    """C40: no crash, no hang, no unexpected exception class, on 2,000 mutations of the five kit
    examples, as octets and as dicts; both outcomes occur."""
    seen, failures = run(FUZZ_MUTATIONS)
    assert failures == []
    assert sum(seen.values()) == FUZZ_MUTATIONS
    assert (
        seen["ACCEPTED"] > 0
        and seen["E_SCHEMA"] > 0
        and set(seen) <= set(RAISED_CODES) | {"ACCEPTED"}
    )


def test_the_mutations_are_deterministic():
    sources = {name: (SET / name).read_bytes() for name in KIT}
    first = [mutation(SEED, i, sources) for i in range(200)]
    again = [mutation(SEED, i, sources) for i in range(200)]
    assert repr(first) == repr(again)
    assert len({repr(m) for m in first}) > 150


def main(argv: list[str]) -> int:
    count = int(argv[argv.index("--fuzz") + 1]) if "--fuzz" in argv else FUZZ_MUTATIONS
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else SEED
    seen, failures = run(count, seed)
    print(f"cesmo_internal fuzz: {count} mutations, seed {seed}, python {sys.version.split()[0]}")
    for key in sorted(seen):
        print(f"  {key}: {seen[key]}")
    print(f"  unexpected outcomes: {len(failures)}")
    for index, label, what in failures[:50]:
        print(f"    index {index} ({label}): {what}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
