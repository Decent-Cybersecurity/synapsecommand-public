"""Write the SYNTHETIC fixtures of one STANAG 4559 translator from the specification bundle's records.

The same script sits in `fixtures/stanag4559_catalog/spec/`, `fixtures/stanag4559_stream/spec/`
and `fixtures/stanag4559_workflow/spec/`, byte for byte (the adapter tests hold the three equal);
the family it writes is read from the name of the directory it sits in.

WHERE THE RECORDS COME FROM
---------------------------
The SynapseCommand STANAG 4559 engineering specification bundle (SC ISR 4559 001, revision 1.0, 4
October 2026) ships nine synthetic internal ISR gateway records, three per family, and the Events
they must become. They are carried VERBATIM, as test data, under `tests/stanag4559_bundle/` of the
repository (that directory's README.md lists them with the SHA-256 digests the bundle's
`SHA256SUMS.json` records). This script reads its family's three records from there, checks each
against its recorded digest, and writes:

- `basic.json`, `missing_source_time.json`, `unknown_extension.json`: the three records, authored
  for this repository. A catalogue or stream record states a footprint at 14 to 15 degrees east,
  50 to 51 degrees north, outside the Baltic rectangle CONTRIBUTING.md puts every fixture position
  in, so its coverage polygon is MOVED seven degrees east and seven degrees north (to 21 to 22
  degrees east, 57 to 58 north, still whole degrees) and `revision.semantic_sha256` is recomputed
  by the bundle's own rule (section 6: the canonical JSON of `family`, `origin`, `change`, `body`
  and `security`; the bundle's `validate_artifacts.py` canonicalises that ASCII and small-integer
  domain with sorted keys and no whitespace, which is RFC 8785 for it). Every other value is the
  bundle's. A workflow record states no position and is copied byte for byte.
- `malformed/`: refused variants, each breaking one rule: the octet-only ones (a duplicate key, a
  NaN literal, a lone surrogate escape, a byte-order mark, nesting one past the declared depth)
  as `.isr` octets, because the harness's loader parses a `.json` file before an adapter sees it;
  the rest as `.json`. One octet past the declared size is not written as a file (it would be a
  16 MiB file per set): the adapter tests feed it in memory.
- `PROVENANCE.json` and `malformed/PROVENANCE.json`.

The digests are computed through `synapse_cdm.evidence.digest_bytes`, the package's one
content-digest site (a fixture builder imports no `hashlib`: `tests/test_cdm_boundary.py`), and
compared with the literals below, which were computed once, outside this repository's code, by
the bundle's rule; a difference is an error, not a rewrite.

    python -I -B fixtures/stanag4559_catalog/spec/build_fixtures.py          # write
    python -I -B fixtures/stanag4559_catalog/spec/build_fixtures.py --check  # compare only

`--check` builds every file in memory, compares the bytes with the files on disk, and also
reports a file in the set's directories that the build does not write; it prints `CURRENT` and
exits 0, or `STALE: <names>` and exits 1, and writes nothing. It needs the repository's
`tests/stanag4559_bundle/`: an installed package does not carry it, and the script says so and
exits 3 rather than guessing. Edit this script and run it; never edit a fixture by hand.
"""

from __future__ import annotations

import copy
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
MALFORMED = ROOT / "malformed"
PACKAGE_PARENT = ROOT.parents[2]  # packages/cdm, which holds synapse_cdm
REPO = ROOT.parents[4]
BUNDLE = REPO / "tests" / "stanag4559_bundle"
FAMILY = ROOT.name.removeprefix("stanag4559_")
ADAPTER = ROOT.name
PIN = f"{ADAPTER}/spec/stanag4559_pin.json"

sys.path.insert(0, str(PACKAGE_PARENT))

from synapse_cdm.adapter import json_nesting_depth  # noqa: E402
from synapse_cdm.adapters.stanag4559_common import MAX_DEPTH  # noqa: E402
from synapse_cdm.evidence import digest_bytes  # noqa: E402

#: The bundle's cases, by the file stem each becomes here.
CASES = {
    "basic": "basic",
    "missing_source_time": "missing-source-time",
    "unknown_extension": "unknown-extension",
}

#: SHA-256 of each source record as the bundle's SHA256SUMS.json records it.
SOURCE_SHA256 = {
    "catalog-basic.record.json": "b2b5447d80c0614ee7add6640146ecfb0eafa954923451ccb50dff95ffcddab0",
    "catalog-missing-source-time.record.json": (
        "b99e96366993ab86b1d64dda09439ca0baea51e85e2f7ae7cd62e88d089af173"
    ),
    "catalog-unknown-extension.record.json": (
        "8070d74de28fac09fcd3685b83a30abb32fe4b1b4b8981e9d00d0b9e2b3301c0"
    ),
    "stream-basic.record.json": "d3c792b96c936010436fb29011309f7dbf8fa0a377921ac7ffed75355e7e375d",
    "stream-missing-source-time.record.json": (
        "6d84c86e368926e39f5d837bc565cc1291ef615916ca34a254bcbf600fcf340d"
    ),
    "stream-unknown-extension.record.json": (
        "47d4b34080fe725a2b96f4bcfe7b3ad2e562111639dcf3c5be9f2c7b61ad42bf"
    ),
    "workflow-basic.record.json": "9677432fbd0ba53f95fb55b9f04defff0f45d4fef31e8026d7f6e22ae7dbcd6e",
    "workflow-missing-source-time.record.json": (
        "fd77a3b5bec9b64f13e634028551f4905479c73a253055ca04b25a567bbb0d87"
    ),
    "workflow-unknown-extension.record.json": (
        "1d3f032340563c61cfa972ea36e4b8546350de6bfd74f9cc3ac31eb9cfd80271"
    ),
}

#: `revision.semantic_sha256` of each authored record, computed once by the bundle's rule.
#: The workflow records are unchanged, so theirs are the bundle's own.
SEMANTIC_SHA256 = {
    "catalog-basic": "fa599b1c81963aa8aa64ab812a87be1dd1f987f7d6cc9a9f75c7b96353f133c1",
    "catalog-missing-source-time": (
        "3e35dec0eb3ce3ecf88f49d3b61fb49257a82dc56a7242e23348ad8f3e4a13d3"
    ),
    "catalog-unknown-extension": "7f1fd408c43b4c8f9243596fc1d16db2b25bbf863e00ccefcaf5289a44ba88f7",
    "stream-basic": "927ce05c01de2defd0133b2b0703bf775a609e3b9beb46d6031b3a67b8d5488b",
    "stream-missing-source-time": "7bab24daf19e0495cbf475711a89be823612e82d46e7b2aca1785a9a76771282",
    "stream-unknown-extension": "90f1c2431b0d766ccb919a7a94b14f50721d3e8ef97b6be573d17cce46b69bbd",
    "workflow-basic": "667eb441c37ce39903db6629ac50cb1c8c6b7962022732955252dff44d458f08",
    "workflow-missing-source-time": (
        "39c1ef1ef322df19cc21e1aa9adcf621a096a731ec7245ea0d4bda9f2d4da027"
    ),
    "workflow-unknown-extension": "2bbc478e59eda0d479b2eff8b7fc05a901a6605274047480e0e71f5e1162411a",
}

#: The move into the Baltic rectangle, degrees east and north.
SHIFT = (7, 7)

#: The family a mismatched `kind` is borrowed from in `kind_of_another_family.json`.
OTHER_KIND = {"catalog": "stream.record", "stream": "workflow.record", "workflow": "catalog.record"}


class BuildError(Exception):
    """The bundle copies are not what the pin records; nothing is written."""


def render(document: dict) -> str:
    """The bundle's own rendering: two-space indent, sorted keys, a final newline."""
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def restricted_jcs(value) -> bytes:
    """The bundle's canonicaliser for its fixtures (`validate_artifacts.py`): ASCII strings and
    integers within 2**53-1 only, sorted keys, no whitespace. RFC 8785 for exactly that domain;
    anything outside it is refused rather than approximated."""

    def check(node) -> None:
        if node is None or isinstance(node, bool):
            return
        if isinstance(node, str):
            node.encode("ascii")
            return
        if isinstance(node, int) and abs(node) <= 9007199254740991:
            return
        if isinstance(node, list):
            for item in node:
                check(item)
            return
        if isinstance(node, dict):
            for key, item in node.items():
                check(key)
                check(item)
            return
        raise BuildError("a value outside the restricted canonicalisation domain")

    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def semantic_sha256(record: dict) -> str:
    covered = copy.deepcopy(
        {key: record[key] for key in ("family", "origin", "change", "body", "security")}
    )
    if record["family"] == "workflow":
        del covered["body"]["artifact"]["raw_ref"]
    return digest_bytes(restricted_jcs(covered))[0]


def source(case: str) -> dict:
    name = f"{FAMILY}-{case}.record.json"
    path = BUNDLE / name
    data = path.read_bytes()
    if digest_bytes(data)[0] != SOURCE_SHA256[name]:
        raise BuildError(f"tests/stanag4559_bundle/{name} is not the bundle's file")
    return json.loads(data)


def authored(case: str) -> dict:
    record = source(case)
    if FAMILY != "workflow":
        coverage = record["body"]["coverage"]
        coverage["coordinates"] = [
            [[lon + SHIFT[0], lat + SHIFT[1]] for lon, lat in ring]
            for ring in coverage["coordinates"]
        ]
        record["revision"]["semantic_sha256"] = semantic_sha256(record)
    digest = semantic_sha256(record)
    if (
        digest != SEMANTIC_SHA256[f"{FAMILY}-{case}"]
        or digest != record["revision"]["semantic_sha256"]
    ):
        raise BuildError(f"the semantic digest of {FAMILY}-{case} is not the recorded literal")
    return record


# -- malformed: one broken rule each ----------------------------------------------------------


def _octets_with(text: str, old: str, new: str) -> bytes:
    if text.count(old) != 1:
        raise BuildError(f"the edit point {old!r} is not unique in the record text")
    return text.replace(old, new).encode("utf-8")


def _nested(depth: int) -> dict:
    node: dict = {}
    for _ in range(depth - 1):
        node = {"n": node}
    return node


def malformed_octets(basic: dict, extension: dict) -> dict[str, bytes]:
    text = render(basic)
    over_depth = copy.deepcopy(extension)
    graph = (
        over_depth["body"]["artifact"]["graph"]
        if FAMILY == "workflow"
        else over_depth["body"]["graph"]
    )
    attribute = graph["nodes"][0]["attributes"][0]
    attribute["value"] = {}
    depth_with_one = json_nesting_depth(render(over_depth))
    attribute["value"] = _nested(MAX_DEPTH + 1 - (depth_with_one - 1))
    deep = render(over_depth)
    if json_nesting_depth(deep) != MAX_DEPTH + 1:
        raise BuildError("the over-depth record does not nest exactly one past the bound")
    sized = text.encode("utf-8")
    object_id = basic["origin"]["object_id"]
    return {
        "duplicate_key.isr": _octets_with(
            text,
            '"tenant_id": "test-tenant"\n',
            '"tenant_id": "test-tenant",\n  "tenant_id": "test-tenant-b"\n',
        ),
        "nan_value.isr": _octets_with(text, '"ordinal": 1,', '"ordinal": NaN,'),
        "lone_surrogate.isr": _octets_with(
            text, f'"object_id": "{object_id}"', f'"object_id": "{object_id}\\ud800"'
        ),
        "byte_order_mark.isr": b"\xef\xbb\xbf" + sized,
        "depth_over_cap.isr": deep.encode("utf-8"),
    }


def malformed_documents(basic: dict, extension: dict) -> dict[str, dict]:
    def variant(mutate, start: dict = basic) -> dict:
        document = copy.deepcopy(start)
        mutate(document)
        return document

    def polygon(*points) -> dict:
        return {"type": "Polygon", "coordinates": [[list(p) for p in points]]}

    geometry = "geometry" if FAMILY == "workflow" else "coverage"

    def edge_to_no_node(d):
        graph = d["body"]["artifact"]["graph"] if FAMILY == "workflow" else d["body"]["graph"]
        graph["edges"].append({"relation": "synthetic-related", "source": "n1", "target": "n9"})

    documents = {
        "unknown_top_level_key.json": variant(lambda d: d.update({"unexpected": 1})),
        "kind_of_another_family.json": variant(lambda d: d.update({"kind": OTHER_KIND[FAMILY]})),
        "missing_captured_at.json": variant(lambda d: d.pop("captured_at")),
        "semantic_digest_upper_case.json": variant(
            lambda d: d["revision"].update(
                {"semantic_sha256": d["revision"]["semantic_sha256"].upper()}
            )
        ),
        "size_bytes_not_an_integer.json": variant(
            lambda d: d["raw_ref"].update({"size_bytes": "88.5"})
        ),
        "polygon_latitude_out_of_range.json": variant(
            lambda d: d["body"].update(
                {geometry: polygon((21, 57), (22, 57), (22, 91), (21, 58), (21, 57))}
            )
        ),
        "impossible_date.json": variant(
            lambda d: d.update({"source_time": "2026-02-30T12:00:00.000Z"})
        ),
        "ring_self_intersects.json": variant(
            lambda d: d["body"].update(
                {geometry: polygon((21, 57), (24, 58), (24, 56), (21, 58), (21, 57))}
            )
        ),
        "graph_edge_to_no_node.json": variant(edge_to_no_node, extension),
        "local_library_scope_foreign_authority.json": variant(
            lambda d: d["body"].update({"identity_scope": "LOCAL_LIBRARY"})
        ),
    }
    if FAMILY != "workflow":
        # The workflow body states no source interval (section 14), so it has no such case.
        documents["temporal_start_after_end.json"] = variant(
            lambda d: d["body"].update(
                {
                    "temporal_start": "2026-10-04T11:30:00.000Z",
                    "temporal_end": "2026-10-04T11:00:00.000Z",
                }
            )
        )
    return documents


# -- provenance ---------------------------------------------------------------------------------


def _origin(case: str, what: str) -> str:
    name = f"{FAMILY}-{CASES[case]}.record.json"
    return (
        f"Synthetic SC ISR gateway record (urn:synapsecommand:isr:record:1) of the {FAMILY} family, "
        f"written for the {ADAPTER} adapter by fixtures/{ADAPTER}/spec/build_fixtures.py from "
        f"{name} of the SynapseCommand STANAG 4559 specification bundle (SC ISR 4559 001 revision "
        f"1.0, examples/, SHA-256 {SOURCE_SHA256[name]} as the bundle's SHA256SUMS.json records "
        f"it), carried verbatim under tests/stanag4559_bundle/; {what}. Every identifier is a test "
        "placeholder and nothing is recorded data."
    )


def _authored_what() -> str:
    if FAMILY == "workflow":
        return "copied byte for byte, since a workflow record of the bundle states no position"
    return (
        "the coverage polygon moved seven degrees east and seven degrees north into the Baltic "
        "rectangle and revision.semantic_sha256 recomputed by the bundle's rule, every other value "
        "kept"
    )


#: What each malformed file breaks, for its provenance entry, and which authored case it starts
#: from.
MALFORMED_WHAT = {
    "duplicate_key.isr": ("basic", "refused variant: the top-level key tenant_id stated twice"),
    "nan_value.isr": ("basic", "refused variant: revision.ordinal written as the NaN literal"),
    "lone_surrogate.isr": (
        "basic",
        "refused variant: origin.object_id ends in a lone surrogate escape",
    ),
    "byte_order_mark.isr": (
        "basic",
        "refused variant: the octets begin with a UTF-8 byte-order mark",
    ),
    "depth_over_cap.isr": (
        "unknown_extension",
        "refused variant: one graph attribute value nests the document one container past the "
        "adapter's declared max_depth",
    ),
    "unknown_top_level_key.json": (
        "basic",
        "refused variant: a top-level key the contract does not define",
    ),
    "kind_of_another_family.json": (
        "basic",
        "refused variant: kind names another family's record kind",
    ),
    "missing_captured_at.json": ("basic", "refused variant: the required captured_at removed"),
    "semantic_digest_upper_case.json": (
        "basic",
        "refused variant: revision.semantic_sha256 in upper-case hex, which the contract's pattern refuses",
    ),
    "size_bytes_not_an_integer.json": (
        "basic",
        "refused variant: raw_ref.size_bytes is not an integer lexeme",
    ),
    "polygon_latitude_out_of_range.json": (
        "basic",
        "refused variant: a polygon vertex at latitude 91, outside the contract's range",
    ),
    "impossible_date.json": ("basic", "refused variant: source_time on 30 February"),
    "ring_self_intersects.json": ("basic", "refused variant: a polygon whose ring crosses itself"),
    "graph_edge_to_no_node.json": (
        "unknown_extension",
        "refused variant: a graph edge to a node the graph does not hold",
    ),
    "local_library_scope_foreign_authority.json": (
        "basic",
        "refused variant: identity_scope LOCAL_LIBRARY beside an origin authority that is not the library",
    ),
    "temporal_start_after_end.json": (
        "basic",
        "refused variant: temporal_start after temporal_end",
    ),
}


def provenance(directory: str, entries: dict[str, str]) -> bytes:
    record = {
        "schema_id": "synapse.fixture-provenance/v1",
        "directory": directory,
        "fixtures": [
            {
                "classification": "PUBLIC",
                "file": name,
                "operational_data": False,
                "origin": entries[name],
                "personal_data": False,
                "standard_ref": PIN,
                "synthetic": True,
            }
            for name in sorted(entries)
        ],
    }
    return (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")


def planned() -> dict[pathlib.Path, bytes]:
    records = {stem: authored(case) for stem, case in CASES.items()}
    files: dict[pathlib.Path, bytes] = {
        ROOT / f"{stem}.json": render(record).encode("utf-8") for stem, record in records.items()
    }
    files[ROOT / "PROVENANCE.json"] = provenance(
        ADAPTER, {f"{stem}.json": _origin(stem, _authored_what()) for stem in CASES}
    )
    broken: dict[str, bytes] = dict(
        malformed_octets(records["basic"], records["unknown_extension"])
    )
    for name, document in malformed_documents(
        records["basic"], records["unknown_extension"]
    ).items():
        broken[name] = render(document).encode("utf-8")
    for name, data in broken.items():
        files[MALFORMED / name] = data
    files[MALFORMED / "PROVENANCE.json"] = provenance(
        f"{ADAPTER}/malformed",
        {name: _origin(MALFORMED_WHAT[name][0], MALFORMED_WHAT[name][1]) for name in broken},
    )
    return files


def unplanned(files: dict[pathlib.Path, bytes]) -> list[pathlib.Path]:
    """Files in the set's two directories the build does not write (README.md is written by hand)."""
    present = [p for p in ROOT.iterdir() if p.is_file() and p.name != "README.md"]
    if MALFORMED.is_dir():
        present += [p for p in MALFORMED.iterdir() if p.is_file()]
    return sorted(p for p in present if p not in files)


def main(argv: list[str]) -> int:
    if not BUNDLE.is_dir():
        print(
            "BLOCKED: tests/stanag4559_bundle/ is not beside this package (an installed wheel does "
            "not carry the repository's tests/); run this from a clone"
        )
        return 3
    try:
        files = planned()
    except BuildError as problem:
        print(f"ERROR: {problem}")
        return 2
    if "--check" in argv:
        stale = [p for p, data in files.items() if not p.exists() or p.read_bytes() != data]
        stale += unplanned(files)
        print(
            "CURRENT"
            if not stale
            else "STALE: " + ", ".join(p.relative_to(ROOT).as_posix() for p in stale)
        )
        return 0 if not stale else 1
    MALFORMED.mkdir(parents=True, exist_ok=True)
    for path, data in files.items():
        path.write_bytes(data)
    print(f"wrote {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
