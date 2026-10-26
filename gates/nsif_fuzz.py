"""The SC4545-CORE-1 fuzz gate: five pure parser targets, one deterministic mutation schedule, and
an outcome digest per target that a second interpreter must reproduce.

WHY THIS EXISTS
---------------
The STANAG 4545 imagery adapter's requirement REQ-085 asks for the container cursor, the
extension parser, the image subheader parser, the geometry parser and the native window index
calculation to be fuzzed independently, seeded with every fixture, at no fewer than 100,000
generated mutations per target, and for every crash or hang to become a minimised regression with
its expected error. REQ-086 adds that fuzz input is never evaluated as Python or shell code. This
gate is the standard-library harness for that: no fuzzing tool is installed here, so the schedule,
the mutation operators and the bookkeeping are written out below and are part of what the outcome
digests certify.

THE TARGETS
-----------
Each target is a pure function of `synapse_cdm.adapters.nsif_codec` or `nsif_geometry`, called
directly and never through `to_cdm`:

* `cursor`: `nsif_codec.read_layout(raw, limits)` over a whole input (header, directory, the
  file's extension areas, the segment walk and the metadata charge);
* `extensions`: `nsif_codec.extension_area(raw, section, limits, overflow_at)` over one extension
  area, with the payload of the overflow DES it names after `overflow_at`;
* `image_subheader`: `nsif_codec.image_subheader(raw, limits, data_length)` over one subheader;
* `geometry`: `nsif_geometry.footprint(icords, igeolo)`, a one-character str and its octets;
* `window_index`: `nsif_codec.sample_index(...)`, the one place the interleave formulas live.

Seeds are every `.ntf` packaged under `fixtures/stanag4545/` at any depth, kit and authored,
accepted and malformed (`cursor`), and the slices `parse_container` cuts from those that parse:
every extension area with its own octets (and, for an area holding TREs, the same TREs framed as
the payload of overflow DES 1), every image subheader with its LI, every image's ICORDS and
IGEOLO plus every 60-character literal of `tests/test_cdm_nsif_geometry.py` under both corner
codes, and every image's layout crossed with the windows the decoder tests use.

THE SCHEDULE (`nsif-fuzz/1`)
----------------------------
Mutation `i` of target `t` draws from a SplitMix64 generator seeded with `0x4545 ^ t ^ i`: the
seed it starts from, then one to three operators. For octets: flip one bit; set one octet to one
of 00 FF 30 39 20 2D 2B; insert one octet; delete one octet; truncate; duplicate a slice of up to
64 octets elsewhere; overwrite part of a run of ASCII digits with its all-zero, all-nine or
maximum-plus-one spelling (a one followed by as many zeros, one octet longer). For `geometry` the
corner code is also replaced (any of the 256 code points, or G or D), the octets dropped to None,
or changed in place. For `window_index` one or two of the eight integers are moved by +1, -1, x2,
to 0 or to 2**63 - 1. No `random` module, clock, environment value or file time feeds any of it.

OUTCOMES
--------
`accepted` (the call returned and the result keeps its own invariants: every slice inside the
input, an index inside the layout, a footprint in the status vocabulary), `refused` (an
`NsifError`, tallied as `CODE:stage`), `crash` (any other exception, or a broken invariant; the
input's SHA-256 and the exception's type are kept) and `hang`. `footprint` is total, so an
`NsifError` from it is a crash too. The digest of a target is the SHA-256 of its ordered
`index:outcome[:code:stage]` lines; the report carries no time, rate or host name.

The full run executes batches of 1,000 inputs in child interpreters started with an explicit
argument list, `[sys.executable, "-B", <this file>, "--batch", <target>, <start>, <count>]`,
whose `PYTHONPATH` names the directory of the parent's `synapse_cdm` so both judge one tree. A
child rebuilds its inputs from the schedule itself: nothing but four arguments crosses the process
boundary, and no input is ever passed as code or shell text. A batch that outlives its watchdog
(600 s) or dies is re-run one input at a time under a 10-second watchdog, and an input that does
not return is a hang. The watchdogs are limits, never results, and are not written anywhere.

    python gates/nsif_fuzz.py --mutations 100000 --out FILE   # the full run, in child batches
    python gates/nsif_fuzz.py --quick --out FILE              # 1,000 per target, in process

`tests/test_cdm_nsif_fuzz.py` runs the quick schedule twice on every test run and holds the
constants, the operators and the static rules above.
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import hashlib
import json
import os
import pathlib
import platform
import subprocess
import sys

import synapse_cdm
from synapse_cdm.adapters import nsif_codec, nsif_geometry

#: REQ-085's floor for a full run, and the in-process schedule the always-on test runs.
FULL_MUTATIONS = 100000
QUICK_MUTATIONS = 1000
BASE_SEED = 0x4545
SCHEDULE = "nsif-fuzz/1"
SCHEMA = "synapse.nsif-fuzz/v1"
TARGETS = ("cursor", "extensions", "image_subheader", "geometry", "window_index")

#: Inputs per child interpreter, and the two watchdogs (limits only; never recorded).
BATCH_SIZE = 1000
BATCH_WATCHDOG = 600
SINGLE_WATCHDOG = 10

MASK64 = (1 << 64) - 1
#: "Its type maximum" for an index argument: the largest signed 64-bit integer, so the schedule
#: does not depend on the platform's word size.
INT_MAX = (1 << 63) - 1
SET_OCTETS = (0x00, 0xFF, 0x30, 0x39, 0x20, 0x2D, 0x2B)
#: The octets a corner is written with, for the in-place geometry operator.
CORNER_OCTETS = b"NSEW+-.0123456789 "
DUPLICATE_LIMIT = 64
DECIMAL_LIMIT = 12

LIMITS = nsif_codec.CORE1_LIMITS
GATE = str(pathlib.Path(__file__).resolve())
REPO = pathlib.Path(__file__).resolve().parents[1]
GEOMETRY_TESTS = REPO / "tests" / "test_cdm_nsif_geometry.py"

#: The windows the decoder tests request, as (x, y, width, height, bands); `None` is the whole
#: raster with every band.
WINDOWS = (
    None,
    (1, 2, 3, 2, (1, 0)),
    (4, 3, 1, 1, (1, 0)),
    (1, 1, 4, 2, (0,)),
    (1, 1, 3, 3, (0,)),
    (0, 0, 3, 2, (0, 1)),
    (0, 0, 2, 1, (1, 0)),
    (0, 0, 1, 3, (0,)),
)


class InvariantBroken(Exception):
    """A call returned a result that breaks its own contract: counted as a crash."""


# --------------------------------------------------------------------------- the generator


class SplitMix64:
    """Sebastiano Vigna's SplitMix64, the 64-bit generator the schedule draws from."""

    def __init__(self, seed: int) -> None:
        self.state = seed & MASK64

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK64
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return z ^ (z >> 31)

    def below(self, bound: int) -> int:
        """A draw in `range(bound)`, `bound >= 1`."""
        return self.next() % bound


def generator(target_index: int, mutation_index: int) -> SplitMix64:
    return SplitMix64(BASE_SEED ^ target_index ^ mutation_index)


# --------------------------------------------------------------------------- octet operators


def flip_bit(data: bytes, position: int, bit: int) -> bytes:
    return data[:position] + bytes((data[position] ^ (1 << bit),)) + data[position + 1 :]


def set_octet(data: bytes, position: int, value: int) -> bytes:
    return data[:position] + bytes((value,)) + data[position + 1 :]


def insert_octet(data: bytes, position: int, value: int) -> bytes:
    return data[:position] + bytes((value,)) + data[position:]


def delete_octet(data: bytes, position: int) -> bytes:
    return data[:position] + data[position + 1 :]


def truncate(data: bytes, length: int) -> bytes:
    return data[:length]


def duplicate_slice(data: bytes, start: int, length: int, at: int) -> bytes:
    return data[:at] + data[start : start + length] + data[at:]


def decimal_runs(data: bytes) -> list[tuple[int, int]]:
    """Every maximal run of ASCII digits as (start, length), in order."""
    runs = []
    start = None
    for position, octet in enumerate(data):
        if 0x30 <= octet <= 0x39:
            if start is None:
                start = position
        elif start is not None:
            runs.append((start, position - start))
            start = None
    if start is not None:
        runs.append((start, len(data) - start))
    return runs


def overwrite_decimal(data: bytes, start: int, width: int, spelling: int) -> bytes:
    """`width` digits at `start` become zeros (0), nines (1) or one past the maximum (2: a one
    and `width` zeros, so the field grows by one octet)."""
    text = (b"0" * width, b"9" * width, b"1" + b"0" * width)[spelling]
    return data[:start] + text + data[start + width :]


def mutate_octets(data: bytes, rng: SplitMix64) -> bytes:
    for _ in range(1 + rng.below(3)):
        data = _one_operator(data, rng)
    return data


def _one_operator(data: bytes, rng: SplitMix64) -> bytes:
    operator = rng.below(7)
    size = len(data)
    if size == 0:
        # Only an insertion applies to nothing.
        return insert_octet(data, 0, rng.below(256))
    if operator == 0:
        return flip_bit(data, rng.below(size), rng.below(8))
    if operator == 1:
        return set_octet(data, rng.below(size), SET_OCTETS[rng.below(len(SET_OCTETS))])
    if operator == 2:
        return insert_octet(data, rng.below(size + 1), rng.below(256))
    if operator == 3:
        return delete_octet(data, rng.below(size))
    if operator == 4:
        return truncate(data, rng.below(size))
    if operator == 5:
        start = rng.below(size)
        length = 1 + rng.below(min(DUPLICATE_LIMIT, size - start))
        return duplicate_slice(data, start, length, rng.below(size + 1))
    runs = decimal_runs(data)
    if not runs:
        return set_octet(data, rng.below(size), 0x30)
    run_start, run_length = runs[rng.below(len(runs))]
    start = run_start + rng.below(run_length)
    width = 1 + rng.below(min(DECIMAL_LIMIT, run_start + run_length - start))
    return overwrite_decimal(data, start, width, rng.below(3))


def _corner_operator(data: bytes, rng: SplitMix64) -> bytes:
    """An in-place change that keeps the 60-octet length the corner grammar needs."""
    size = len(data)
    if size == 0:
        return insert_octet(data, 0, CORNER_OCTETS[rng.below(len(CORNER_OCTETS))])
    operator = rng.below(4)
    if operator == 0:
        return flip_bit(data, rng.below(size), rng.below(8))
    if operator == 1:
        return set_octet(data, rng.below(size), SET_OCTETS[rng.below(len(SET_OCTETS))])
    if operator == 2:
        return set_octet(data, rng.below(size), CORNER_OCTETS[rng.below(len(CORNER_OCTETS))])
    runs = decimal_runs(data)
    if not runs:
        return set_octet(data, rng.below(size), 0x30)
    run_start, run_length = runs[rng.below(len(runs))]
    start = run_start + rng.below(run_length)
    width = 1 + rng.below(min(DECIMAL_LIMIT, run_start + run_length - start))
    return overwrite_decimal(data, start, width, rng.below(2))


def perturb(value: int, operator: int) -> int:
    return (value + 1, value - 1, value * 2, 0, INT_MAX)[operator]


# --------------------------------------------------------------------------- invariants


def _slices(value, found: list) -> None:
    """Every Slice reachable from a parse record, in a stable order."""
    if isinstance(value, nsif_codec.Slice):
        found.append(value)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for spec in dataclasses.fields(value):
            _slices(getattr(value, spec.name), found)
    elif isinstance(value, (tuple, list)):
        for item in value:
            _slices(item, found)
    elif hasattr(value, "values") and hasattr(value, "keys"):
        for key in sorted(value.keys()):
            _slices(value[key], found)


def _inside(result, size: int) -> None:
    found: list = []
    _slices(result, found)
    for part in found:
        if part.offset < 0 or part.length < 0 or part.offset + part.length > size:
            raise InvariantBroken("a slice leaves the input")


# --------------------------------------------------------------------------- seeds


def fixture_root() -> pathlib.Path:
    return pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures" / "stanag4545"


def _vectors() -> list[tuple[str, bytes]]:
    root = fixture_root()
    paths = sorted(root.rglob("*.ntf"), key=lambda path: path.relative_to(root).as_posix())
    return [(path.relative_to(root).as_posix(), path.read_bytes()) for path in paths]


def geometry_literals() -> list[bytes]:
    """Every 60-character string or bytes literal of the geometry test module, read by its
    syntax tree: the module is parsed, never executed."""
    tree = ast.parse(GEOMETRY_TESTS.read_text(encoding="utf-8"), filename=str(GEOMETRY_TESTS))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            if len(node.value) == 60:
                value = node.value
                found.add(value.encode("latin-1") if isinstance(value, str) else value)
    return sorted(found)


def _area_seeds(container: nsif_codec.Container) -> list[tuple[str, bytes, int | None]]:
    raw = container.raw
    seeds = []
    for area in container.areas:
        start = area.length_field.offset
        own = raw[start : start + 5 + area.length]
        if area.overflow:
            des = container.des[area.overflow - 1].segment.data
            payload = raw[des.offset : des.offset + des.length]
            seeds.append((area.section, own + payload, len(own)))
        else:
            seeds.append((area.section, own, None))
        if area.tres:
            local = raw[area.local.offset : area.local.offset + area.local.length]
            seeds.append((area.section, b"00003001" + local, 8))
    return seeds


def build_seeds() -> dict[str, list]:
    vectors = _vectors()
    cursor = [raw for _, raw in vectors]
    areas, subheaders, corners, layouts = set(), set(), set(), set()
    for _, raw in vectors:
        try:
            container = nsif_codec.parse_container(raw, LIMITS)
        except nsif_codec.NsifError:
            continue
        areas.update(_area_seeds(container))
        for image in container.images:
            sub = image.segment.subheader
            subheaders.add((raw[sub.offset : sub.offset + sub.length], image.segment.data.length))
            igeolo = None
            if image.igeolo is not None:
                igeolo = raw[image.igeolo.offset : image.igeolo.offset + image.igeolo.length]
            corners.add((image.icords, igeolo))
            params = (
                image.imode,
                image.nbpr,
                image.nbpc,
                image.block_width,
                image.block_height,
                image.band_count,
            )
            for window in WINDOWS:
                if window is None:
                    x, y, width, height = 0, 0, image.ncols, image.nrows
                    bands = tuple(range(image.band_count))
                else:
                    x, y, width, height, bands = window
                for px, py in {(x, y), (x + width - 1, y), (x, y + height - 1)}:
                    for band in {bands[0], bands[-1]}:
                        layouts.add((*params, px, py, band))
                layouts.add((*params, x + width - 1, y + height - 1, bands[-1]))
    for octets in geometry_literals():
        corners.add(("G", octets))
        corners.add(("D", octets))
    return {
        "cursor": cursor,
        "extensions": sorted(areas, key=seed_text_of("extensions")),
        "image_subheader": sorted(subheaders, key=seed_text_of("image_subheader")),
        "geometry": sorted(corners, key=seed_text_of("geometry")),
        "window_index": sorted(layouts, key=seed_text_of("window_index")),
    }


def seed_text_of(target: str):
    """A seed's text form: what the seed digest is taken over, and the order seeds are kept in."""

    def text(seed) -> str:
        if target == "cursor":
            return seed.hex()
        if target == "extensions":
            section, data, overflow_at = seed
            return f"{section}:{overflow_at}:{data.hex()}"
        if target == "image_subheader":
            data, data_length = seed
            return f"{data_length}:{data.hex()}"
        if target == "geometry":
            icords, igeolo = seed
            return f"{ord(icords):02x}:{'-' if igeolo is None else igeolo.hex()}"
        return ",".join(str(value) for value in seed)

    return text


def seed_digest(target: str, seeds: list) -> str:
    text = seed_text_of(target)
    lines = "".join(text(seed) + "\n" for seed in seeds)
    return hashlib.sha256(lines.encode("ascii")).hexdigest()


# --------------------------------------------------------------------------- inputs and calls


def make_input(target: str, seeds: list, index: int):
    """Mutation `index` of `target`: a pure function of the schedule and the seed list."""
    rng = generator(TARGETS.index(target), index)
    seed = seeds[rng.below(len(seeds))]
    if target == "cursor":
        return mutate_octets(seed, rng)
    if target == "extensions":
        section, data, overflow_at = seed
        data = mutate_octets(data, rng)
        return section, data, None if overflow_at is None else min(overflow_at, len(data))
    if target == "image_subheader":
        data, data_length = seed
        return mutate_octets(data, rng), data_length
    if target == "geometry":
        icords, igeolo = seed
        for _ in range(1 + rng.below(3)):
            operator = rng.below(8)
            if operator == 0:
                icords = chr(rng.below(256))
            elif operator == 1:
                icords = "GD"[rng.below(2)]
            elif operator == 2:
                igeolo = None
            elif operator == 3:
                igeolo = mutate_octets(igeolo or b"", rng)
            else:
                igeolo = _corner_operator(igeolo or b"", rng)
        return icords, igeolo
    values = list(seed)
    for _ in range(1 + rng.below(2)):
        position = 1 + rng.below(8)
        values[position] = perturb(values[position], rng.below(5))
    return tuple(values)


def input_octets(target: str, item) -> bytes:
    """The octets an input's SHA-256 is taken over (a crash or hang record names it by this)."""
    if target == "cursor":
        return item
    if target == "extensions":
        section, data, overflow_at = item
        return f"{section}:{overflow_at}:".encode("ascii") + data
    if target == "image_subheader":
        data, data_length = item
        return f"{data_length}:".encode("ascii") + data
    if target == "geometry":
        icords, igeolo = item
        tail = b"-" if igeolo is None else igeolo
        return icords.encode("utf-8") + b":" + tail
    return ",".join(str(value) for value in item).encode("ascii")


def call(target: str, item) -> None:
    """Run one input; return normally when accepted, raise otherwise."""
    if target == "cursor":
        _inside(nsif_codec.read_layout(item, LIMITS), len(item))
    elif target == "extensions":
        section, data, overflow_at = item
        _inside(nsif_codec.extension_area(data, section, LIMITS, overflow_at), len(data))
    elif target == "image_subheader":
        data, data_length = item
        record, diagnostics = nsif_codec.image_subheader(data, LIMITS, data_length)
        _inside((record, diagnostics), len(data) + data_length)
    elif target == "geometry":
        found = nsif_geometry.footprint(*item)
        if found.status not in nsif_geometry.STATUSES:
            raise InvariantBroken("a footprint status outside the vocabulary")
        if (found.geometry is None) == (found.status == "available"):
            raise InvariantBroken("a footprint geometry that disagrees with its status")
    else:
        index = nsif_codec.sample_index(*item)
        _, nbpr, nbpc, width, height, bands = item[:6]
        if not 0 <= index < nbpr * nbpc * width * height * bands:
            raise InvariantBroken("a sample index outside the layout")


def classify(target: str, item) -> tuple:
    """(`accepted`,), (`refused`, code, stage) or (`crash`, exception type name)."""
    try:
        call(target, item)
    except nsif_codec.NsifError as error:
        if target == "geometry":
            return ("crash", type(error).__name__)
        return ("refused", error.code, error.stage)
    except Exception as error:
        # Every other exception is the defect the run looks for, recorded rather than raised.
        return ("crash", type(error).__name__)
    return ("accepted",)


def line(index: int, outcome: tuple) -> str:
    if outcome[0] == "refused":
        return f"{index}:refused:{outcome[1]}:{outcome[2]}"
    return f"{index}:{outcome[0]}"


# --------------------------------------------------------------------------- running


def run_batch(target: str, seeds: list, start: int, count: int) -> list[list]:
    """Inputs `start` .. `start + count - 1`, in process: one row per input."""
    rows = []
    for index in range(start, start + count):
        item = make_input(target, seeds, index)
        outcome = classify(target, item)
        row = [index, *outcome]
        if outcome[0] == "crash":
            row.append(hashlib.sha256(input_octets(target, item)).hexdigest())
        rows.append(row)
    return rows


def _child_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(pathlib.Path(synapse_cdm.__file__).resolve().parent.parent)
    return environment


def _child(target: str, start: int, count: int, watchdog: int, expected_seeds: str):
    """One child batch: its rows, or None when it did not return a well-formed answer in time."""
    # An explicit argument list, so no shell ever sees the four arguments.
    try:
        completed = subprocess.run(
            [sys.executable, "-B", GATE, "--batch", target, str(start), str(count)],
            capture_output=True,
            text=True,
            timeout=watchdog,
            env=_child_environment(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    if completed.returncode != 0:
        return None
    try:
        answer = json.loads(completed.stdout)
    except ValueError:
        return None
    if answer.get("seed_sha256") != expected_seeds:
        raise RuntimeError(f"{target}: a child built different seeds; the trees differ")
    return answer["rows"]


def run_isolated(target: str, seeds: list, mutations: int) -> list[list]:
    """The full run's batches, each in a fresh child under the watchdogs."""
    digest = seed_digest(target, seeds)
    rows = []
    for start in range(0, mutations, BATCH_SIZE):
        count = min(BATCH_SIZE, mutations - start)
        batch = _child(target, start, count, BATCH_WATCHDOG, digest)
        if batch is None:
            batch = []
            for index in range(start, start + count):
                single = _child(target, index, 1, SINGLE_WATCHDOG, digest)
                if single is None:
                    item = make_input(target, seeds, index)
                    octets = hashlib.sha256(input_octets(target, item)).hexdigest()
                    batch.append([index, "hang", octets])
                else:
                    batch.extend(single)
        rows.extend(batch)
    return rows


def summarise(target: str, seeds: list, mutations: int, rows: list[list]) -> dict:
    refused: dict[str, int] = {}
    accepted = 0
    crash, hang, lines = [], [], []
    for row in rows:
        index, kind = row[0], row[1]
        if kind == "accepted":
            accepted += 1
            lines.append(line(index, ("accepted",)))
        elif kind == "refused":
            key = f"{row[2]}:{row[3]}"
            refused[key] = refused.get(key, 0) + 1
            lines.append(line(index, ("refused", row[2], row[3])))
        elif kind == "crash":
            crash.append({"index": index, "exception": row[2], "input_sha256": row[3]})
            lines.append(line(index, ("crash",)))
        else:
            hang.append({"index": index, "input_sha256": row[2]})
            lines.append(line(index, ("hang",)))
    text = "".join(entry + "\n" for entry in lines)
    return {
        "target": target,
        "schedule": SCHEDULE,
        "seeds": len(seeds),
        "seed_sha256": seed_digest(target, seeds),
        "mutations": mutations,
        "accepted": accepted,
        "refused": dict(sorted(refused.items())),
        "crash": crash,
        "hang": hang,
        "outcome_sha256": hashlib.sha256(text.encode("ascii")).hexdigest(),
    }


def run(mutations: int, isolated: bool) -> dict:
    seeds = build_seeds()
    results = []
    for target in TARGETS:
        if isolated:
            rows = run_isolated(target, seeds[target], mutations)
        else:
            rows = run_batch(target, seeds[target], 0, mutations)
        results.append(summarise(target, seeds[target], mutations, rows))
    return {
        "schema": SCHEMA,
        "schedule": SCHEDULE,
        "mode": "isolated" if isolated else "in_process",
        "mutations": mutations,
        "interpreter": f"{platform.python_implementation()} {platform.python_version()}",
        "platform": platform.platform(),
        "targets": results,
    }


def _batch_main(target: str, start: str, count: str) -> int:
    if target not in TARGETS or not start.isdigit() or not count.isdigit():
        print("nsif_fuzz: --batch takes a target name and two counts", file=sys.stderr)
        return 2
    seeds = build_seeds()[target]
    rows = run_batch(target, seeds, int(start), int(count))
    print(json.dumps({"seed_sha256": seed_digest(target, seeds), "rows": rows}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nsif_fuzz",
        description="Fuzz the five SC4545-CORE-1 parser targets on a deterministic schedule.",
    )
    parser.add_argument("--out", type=pathlib.Path, help="the JSON report to write")
    parser.add_argument(
        "--mutations",
        type=int,
        default=FULL_MUTATIONS,
        help=f"mutations per target in child batches (default {FULL_MUTATIONS})",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help=f"{QUICK_MUTATIONS} mutations per target, in this process",
    )
    parser.add_argument(
        "--batch",
        nargs=3,
        metavar=("TARGET", "START", "COUNT"),
        help="the child side of a full run (prints one JSON answer)",
    )
    args = parser.parse_args(argv)
    if args.batch:
        return _batch_main(*args.batch)
    if args.out is None:
        parser.error("--out is required")
    if args.mutations < 1:
        parser.error("--mutations must be at least 1")
    if args.quick:
        report = run(QUICK_MUTATIONS, isolated=False)
    else:
        report = run(args.mutations, isolated=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    failed = 0
    for result in report["targets"]:
        refused = sum(result["refused"].values())
        failed += len(result["crash"]) + len(result["hang"])
        print(
            f"{result['target']}: {result['seeds']} seeds, {result['mutations']} mutations, "
            f"{result['accepted']} accepted, {refused} refused, {len(result['crash'])} crash, "
            f"{len(result['hang'])} hang, outcome {result['outcome_sha256']}"
        )
    print(f"schedule {SCHEDULE}; {failed} crash or hang")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
