"""GDAL's own reading of the `stanag4545` vectors, recorded as tracked JSON. Run by hand only.

The decoder's mandatory comparison (`tests/test_cdm_nsif_codec.py`) holds the adapter's storage
integers to an independent reader, and GDAL is that reader. GDAL is not a dependency of the
package, of its tests or of CI, so its reading is taken once here, where its command-line tools
exist, and written under `fixtures/stanag4545/independent/`; the test compares with the written
files and needs no GDAL. This is the geopackage precedent (`fixtures/geopackage/independent/`) with
the recorder kept outside `spec/`, which ships only the builder and pin records. Nothing in the
package imports this file and no test runs it.

WHAT IS RECORDED
----------------
For every image-bearing vector (the top-level kit vectors and every `vectors/*.ntf`), one
`<stem>.gdal.json`: the file's path relative to the fixture directory, its length and SHA-256, the
band data type, size `[columns, rows]` and band count `gdalinfo -json` reports, and the samples
`gdallocationinfo -valonly` prints for every pixel, reordered band-major. GDAL returns storage
integers (unshifted, unmasked, signed 16-bit as two's complement), which is why the decoder's
storage view is what they are compared with. Where GDAL reports them, the colour table and the
geotransform with the four pixel-centre corners it implies are recorded as well. One
`gdal_reading.json` states the GDAL version, the three command forms, the environment, the reading
date and what the reading is not: storage integers and corner numbers only, on synthetic vectors,
from an unpinned build, and no oracle for headers, labels, negative vectors or seam splits.

The tools run with an explicit argument list from the fixture directory, never through a shell,
with `GDAL_PAM_ENABLED=NO` so that no `.aux.xml` is written beside a vector.

    python gates/nsif_gdal_reading.py --date YYYY-MM-DD   # take the reading, write the files
    python gates/nsif_gdal_reading.py --check             # re-read and compare, write nothing

`--check` prints `CURRENT` and exits 0 when every reading matches (the date is not compared), prints
`STALE: <names>` and exits 1 when a reading or the command record differs or a file is missing or
left over, and prints `NOTE: <recorded version> recorded, <installed version> installed` (each a
`GDAL x.y.z ...` line) and exits 0 when only the version differs: the build moves under Homebrew,
the storage integers do not. Exit 2: a GDAL tool is missing or failed.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

from synapse_cdm.evidence import digest

REPO = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = REPO / "packages" / "cdm" / "synapse_cdm" / "fixtures" / "stanag4545"
INDEPENDENT = FIXTURES / "independent"
RECORD = "gdal_reading.json"
SUFFIX = ".gdal.json"

ENVIRONMENT = {"GDAL_PAM_ENABLED": "NO"}
COMMANDS = [
    ["gdalinfo", "--version"],
    ["gdalinfo", "-json", "<file>"],
    ["gdallocationinfo", "-valonly", "<file>"],
]
STATEMENT = (
    "storage integers and corner numbers only; synthetic vectors; unpinned Homebrew build; not a "
    "header, label, negative-vector or seam oracle"
)


class ReadingError(RuntimeError):
    """A GDAL tool failed or printed something this recorder does not accept."""


def vectors() -> list[str]:
    """Every image-bearing vector, as its path relative to the fixture directory."""
    top = sorted(p.name for p in FIXTURES.glob("*.ntf"))
    native = sorted(f"vectors/{p.name}" for p in (FIXTURES / "vectors").glob("*.ntf"))
    return top + native


def stem(relative: str) -> str:
    return pathlib.PurePosixPath(relative).name[: -len(".ntf")]


def tools() -> dict[str, str]:
    found = {name: shutil.which(name) for name in ("gdalinfo", "gdallocationinfo")}
    missing = sorted(name for name, path in found.items() if path is None)
    if missing:
        raise ReadingError(f"not on PATH: {', '.join(missing)}")
    return found


def run(argv: list[str], stdin: str | None = None) -> str:
    result = subprocess.run(
        argv,
        input=stdin,
        capture_output=True,
        text=True,
        cwd=FIXTURES,
        env={**os.environ, **ENVIRONMENT},
        check=False,
    )
    if result.returncode != 0:
        raise ReadingError(f"{pathlib.Path(argv[0]).name} exited {result.returncode}")
    return result.stdout


def version(found: dict[str, str]) -> str:
    return run([found["gdalinfo"], "--version"]).strip()


def reading(relative: str, found: dict[str, str]) -> dict:
    """GDAL's reading of one vector, in the recorded field order."""
    info = json.loads(run([found["gdalinfo"], "-json", relative]))
    columns, rows = info["size"]
    bands = info["bands"]
    count = len(bands)
    data_types = {band["type"] for band in bands}
    if len(data_types) != 1:
        raise ReadingError(f"{relative}: bands of more than one data type")
    pairs = "".join(f"{x} {y}\n" for y in range(rows) for x in range(columns))
    tokens = run([found["gdallocationinfo"], "-valonly", relative], pairs).split()
    if len(tokens) != rows * columns * count:
        raise ReadingError(f"{relative}: {len(tokens)} values for {rows * columns * count} samples")
    # One line per band per pixel, pixels in the order given: reorder band-major.
    values = [int(token) for token in tokens]
    band_major = [
        values[(y * columns + x) * count + b]
        for b in range(count)
        for y in range(rows)
        for x in range(columns)
    ]
    sha256, size = digest(FIXTURES / relative)
    record = {
        "file": relative,
        "bytes": size,
        "sha256": sha256,
        "gdal_data_type": data_types.pop(),
        "size": [columns, rows],
        "band_count": count,
        "storage_band_major": band_major,
    }
    table = bands[0].get("colorTable")
    if table is not None:
        record["color_table"] = table["entries"]
    transform = info.get("geoTransform")
    if transform is not None:
        record["geo_transform"] = transform
        # GDAL places IGEOLO's corners at pixel centres; these are the corners its geotransform
        # implies under that convention, UL, UR, LR, LL.
        record["corners"] = [
            [
                transform[0] + px * transform[1] + ln * transform[2],
                transform[3] + px * transform[4] + ln * transform[5],
            ]
            for px, ln in (
                (0.5, 0.5),
                (columns - 0.5, 0.5),
                (columns - 0.5, rows - 0.5),
                (0.5, rows - 0.5),
            )
        ]
    return record


def text(document: dict) -> str:
    return json.dumps(document, indent=1) + "\n"


def command_record(gdal_version: str, date: str) -> dict:
    return {
        "gdal_version": gdal_version,
        "commands": COMMANDS,
        "file_paths": "relative to fixtures/stanag4545/, the directory every command is run in",
        "gdallocationinfo_input": "every `column row` pair of the image on stdin, row by row",
        "environment": ENVIRONMENT,
        "date": date,
        "statement": STATEMENT,
    }


def check(found: dict[str, str]) -> int:
    installed = version(found)
    stale = []
    expected = {}
    for relative in vectors():
        expected[stem(relative) + SUFFIX] = text(reading(relative, found))
    for name, content in sorted(expected.items()):
        path = INDEPENDENT / name
        if not path.is_file() or path.read_text() != content:
            stale.append(name)
    stale += sorted(p.name for p in INDEPENDENT.glob("*" + SUFFIX) if p.name not in expected)
    note = None
    path = INDEPENDENT / RECORD
    if not path.is_file():
        stale.append(RECORD)
    else:
        recorded = json.loads(path.read_text())
        fresh = command_record(installed, recorded.get("date", ""))
        if {k: v for k, v in recorded.items() if k != "gdal_version"} != {
            k: v for k, v in fresh.items() if k != "gdal_version"
        }:
            stale.append(RECORD)
        elif recorded.get("gdal_version") != installed:
            # The version strings begin with "GDAL" themselves.
            note = f"NOTE: {recorded.get('gdal_version')} recorded, {installed} installed"
    if stale:
        print("STALE: " + ", ".join(stale))
        return 1
    print(note or "CURRENT")
    return 0


def write(found: dict[str, str], date: str) -> int:
    INDEPENDENT.mkdir(exist_ok=True)
    written = []
    for relative in vectors():
        name = stem(relative) + SUFFIX
        (INDEPENDENT / name).write_text(text(reading(relative, found)))
        written.append(name)
    for leftover in sorted(INDEPENDENT.glob("*" + SUFFIX)):
        if leftover.name not in written:
            leftover.unlink()
            print(f"removed {leftover.name}: no vector of that name")
    (INDEPENDENT / RECORD).write_text(text(command_record(version(found), date)))
    print(f"wrote {len(written)} readings and {RECORD}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record or check GDAL's reading of the vectors.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="re-read and compare; write nothing")
    group.add_argument("--date", help="the reading date to record, YYYY-MM-DD (writes the files)")
    args = parser.parse_args(argv)
    if args.date is not None:
        try:
            valid = re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date) and datetime.date.fromisoformat(
                args.date
            )
        except ValueError:
            valid = False
        if not valid:
            parser.error("--date takes a calendar date, YYYY-MM-DD")
    try:
        found = tools()
        return check(found) if args.check else write(found, args.date)
    except ReadingError as error:
        print(f"nsif_gdal_reading: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
