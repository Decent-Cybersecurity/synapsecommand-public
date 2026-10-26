"""The `sc-imagery` command: the five subcommands, the explicit live or synthetic choice, URI and
overwrite refusals, the exit-code table by literal outcome, the fixed stderr lines that carry no
source text, and an interrupt that leaves nothing uncommitted behind. Most cases run the module
in a subprocess, as an operator would; argument errors also run `main` in-process."""

from __future__ import annotations

import base64
import json
import os
import pathlib
import stat
import subprocess
import sys
import zlib

import pytest
from helpers import build_nsif, image, set_field, sha, tre, vector, with_encryp, with_ic

import synapse_imagery
from synapse_imagery import cli
from synapse_imagery.ingest import tenant_directory

DISTRIBUTION = pathlib.Path(synapse_imagery.__file__).resolve().parents[1]
SIGINT_DRIVER = str(pathlib.Path(__file__).with_name("sigint_driver.py"))
GEO = "480000N0170000E480000N0180000E470000N0180000E470000N0170000E"
MEMORY = [] if sys.platform.startswith("linux") else ["sc-imagery: WORKER_MEMORY_NOT_ENFORCED"]
LUT_TABLES = (bytes([0, 85, 170, 255]), bytes([255, 170, 85, 0]), bytes([10, 20, 30, 40]))


def environment() -> dict:
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(DISTRIBUTION),
    }


def sc(cwd, *arguments, driver=None, timeout=120):
    """(exit status, stdout, stderr lines) of one command run as `python -m synapse_imagery`."""
    command = [sys.executable, "-m", "synapse_imagery"]
    if driver is not None:
        command = [sys.executable, SIGINT_DRIVER, driver]
    done = subprocess.run(
        command + [str(argument) for argument in arguments],
        cwd=cwd,
        env=environment(),
        capture_output=True,
        timeout=timeout,
    )
    return done.returncode, done.stdout.decode("utf-8"), done.stderr.decode("utf-8").splitlines()


def write(tmp_path, name, octets) -> pathlib.Path:
    path = tmp_path / name
    path.write_bytes(octets)
    return path


def ingest(tmp_path, name, octets, *extra, store="store"):
    path = write(tmp_path, name, octets)
    return sc(
        tmp_path,
        "ingest",
        path,
        "--store",
        tmp_path / store,
        "--dataset",
        "default",
        "--synthetic",
        "true",
        *extra,
    )


def no_part(directory) -> bool:
    return not [name for name in os.listdir(directory) if name.endswith(".part")]


def recipe(**changes) -> dict:
    out = {
        "recipe": "SC4545-WRITE-NC8-1",
        "producer_id": "SCFIX",
        "product_id": "SCFIX0001",
        "product_time": "2026-10-04T12:00:00Z",
        "capture_time": "2026-10-04T12:00:00Z",
        "source_attribution": "SYNTHETIC",
        "security": {"classification": "U"},
        "raster": {
            "representation": "MONO",
            "width": 2,
            "height": 2,
            "bits": 8,
            "samples_b64": base64.b64encode(bytes([0, 64, 128, 255])).decode("ascii"),
        },
    }
    out.update(changes)
    return out


# --------------------------------------------------------------------------- the surface


def test_the_parser_has_exactly_the_five_subcommands():
    parser = cli.build_parser()
    (commands,) = [action for action in parser._actions if action.dest == "command"]
    assert set(commands.choices) == {"inspect", "ingest", "preview", "replay", "export-nc"}
    assert cli.SUBCOMMANDS == ("inspect", "ingest", "preview", "replay", "export-nc")


def test_the_version_is_the_hosts(capsys):
    assert cli.main(["--version"]) == 0
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("sc-imagery 1.0.0\n", "")


def test_the_export_help_says_experimental_and_not_qualified(capsys):
    assert cli.main(["export-nc", "--help"]) == 0
    text = " ".join(capsys.readouterr().out.split())
    assert "Experimental" in text and "experimental engineering output" in text
    assert "not independently qualified" in text
    for claim in ("conforms", "certified", "compliant"):
        assert claim not in text.lower()


@pytest.mark.parametrize(
    "arguments, typed",
    [
        (["ingest", "x.ntf", "--store", "s", "--dataset", "d"], None),
        (["ingest", "x.ntf", "--store", "s", "--dataset", "d", "--synthetic", "yes"], "yes"),
        (["ingest", "x.ntf", "--store", "s", "--dataset", "d", "--synthetic", "True"], "True"),
        (["ingest", "x.ntf", "--store", "s", "--dataset", "d", "--synth", "true"], "synth"),
        (["preview", "r", "--image", "-1", "--store", "s", "--output", "o.png"], "-1"),
        (["preview", "r", "--image", "one", "--store", "s", "--output", "o.png"], "one"),
        (["shell", "ls"], "shell"),
        ([], None),
        (["--version", "ingest"], None),
    ],
)
def test_a_command_line_the_parser_refuses_is_a_usage_error(
    tmp_path, capsys, monkeypatch, arguments, typed
):
    monkeypatch.chdir(tmp_path)
    assert cli.main(arguments) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == ["sc-imagery: usage error", cli.USAGE]
    if typed is not None:
        assert typed not in captured.err
    assert os.listdir(tmp_path) == []


@pytest.mark.parametrize(
    "extra, option",
    [
        (["--dataset", "a|b"], "--dataset"),
        (["--dataset", "d", "--product-key", "a|b"], "--product-key"),
        (["--dataset", "d", "--as-of", "2026-10-04T12:00:00Z"], "--as-of"),
        (["--dataset", "d", "--as-of-basis", "an operator's statement"], "--as-of"),
        (
            ["--dataset", "d", "--as-of", "yesterday", "--as-of-basis", "an operator's statement"],
            "--as-of",
        ),
    ],
)
def test_refused_context_options_are_usage_errors_and_store_nothing(
    tmp_path, capsys, extra, option
):
    source = write(tmp_path, "geo.ntf", vector("geo_dms.ntf"))
    arguments = ["ingest", str(source), "--store", str(tmp_path / "store"), "--synthetic", "true"]
    assert cli.main(arguments + extra) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    (line,) = captured.err.splitlines()
    assert line.startswith(f"sc-imagery: usage error: {option} ")
    assert "a|b" not in line and "yesterday" not in line
    assert not (tmp_path / "store").exists()


@pytest.mark.parametrize("bands", ["0,0", "0,1", "0,1,2,3", "x", "0,,1"])
def test_a_band_selection_outside_the_rule_is_a_usage_error(tmp_path, capsys, bands):
    arguments = [
        "preview",
        "3c1d7b56-7a0a-5f0e-9d6e-2b8f3a4c5d6e",
        "--image",
        "0",
        "--store",
        str(tmp_path / "store"),
        "--output",
        str(tmp_path / "o.png"),
        "--bands",
        bands,
    ]
    assert cli.main(arguments) == 2
    assert capsys.readouterr().err.splitlines() == [
        "sc-imagery: usage error: --bands is one band or three distinct bands"
    ]


# --------------------------------------------------------------------------- each command once


def test_every_command_succeeds_on_the_kit_vector(tmp_path):
    octets = vector("geo_dms.ntf")
    status, out, err = ingest(tmp_path, "geo.ntf", octets)
    result = json.loads(out)
    assert (status, result["state"], len(result["cdm_ids"])) == (0, "committed", 2)
    assert err == MEMORY + [f"sc-imagery: ingest committed {result['record_id']}"]
    record_id = result["record_id"]
    store = tmp_path / "store"

    status, out, err = sc(tmp_path, "inspect", tmp_path / "geo.ntf", "--json", tmp_path / "i.json")
    assert (status, out) == (0, "")
    assert err == MEMORY + ["sc-imagery: inspect ok"]
    document = json.loads((tmp_path / "i.json").read_text())
    assert (document["valid"], document["sha256"]) == (True, sha(octets))

    status, out, err = sc(
        tmp_path, "preview", record_id, "--image", "0", "--store", store, "--output", "p.png"
    )
    receipt = json.loads(out)
    assert status == 0 and receipt["size"] == [2, 2]
    assert err == MEMORY + [f"sc-imagery: preview ok {receipt['derivative_id']}"]
    assert (tmp_path / "p.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    status, out, err = sc(tmp_path, "replay", record_id, "--store", store, "--output", "r.ntf")
    assert (status, err) == (0, [f"sc-imagery: replay ok {record_id}"])
    assert json.loads(out)["wire_signature"] == "NSIF01.01"
    assert (tmp_path / "r.ntf").read_bytes() == octets

    (tmp_path / "recipe.json").write_text(json.dumps(recipe()))
    status, out, err = sc(
        tmp_path, "export-nc", "recipe.json", "--store", store, "--output", "e.ntf"
    )
    receipt = json.loads(out)
    assert (status, receipt["status"], receipt["writer"]) == (
        0,
        "experimental",
        "SC4545-WRITE-NC8-1",
    )
    assert err == [f"sc-imagery: export-nc ok {receipt['export_id']}"]
    assert sha((tmp_path / "e.ntf").read_bytes()) == receipt["output_sha256"]

    for name in ("i.json", "p.png", "r.ntf", "e.ntf"):
        assert stat.S_IMODE(os.stat(tmp_path / name).st_mode) == 0o600
    assert no_part(tmp_path)


def test_inspect_to_stdout_prints_the_document_and_its_stderr_by_platform(tmp_path):
    source = write(tmp_path, "geo.ntf", vector("geo_dms.ntf"))
    status, out, err = sc(tmp_path, "inspect", source, "--json", "-")
    assert status == 0
    document = json.loads(out)
    assert document["schema"] == "sc-imagery-inspect/1" and document["valid"] is True
    expected = ["sc-imagery: inspect ok"]
    if sys.platform == "darwin":
        expected = ["sc-imagery: WORKER_MEMORY_NOT_ENFORCED"] + expected
    assert err == expected
    assert sorted(os.listdir(tmp_path)) == ["geo.ntf"]


def test_inspect_of_a_file_the_adapter_refuses_exits_by_its_code(tmp_path):
    source = write(tmp_path, "t.ntf", vector("truncated.ntf"))
    status, out, err = sc(tmp_path, "inspect", source, "--json", "-")
    document = json.loads(out)
    assert (status, document["valid"]) == (3, False)
    assert [entry["code"] for entry in document["diagnostics"]] == ["E_LENGTH"]
    assert err == MEMORY + ["sc-imagery: inspect E_LENGTH"]


def test_a_header_only_file_needs_a_product_key_from_the_command_line(tmp_path):
    octets = vector("header_only.ntf")
    status, out, err = ingest(tmp_path, "h.ntf", octets)
    result = json.loads(out)
    assert (status, result["state"]) == (2, "rejected")
    assert [entry["code"] for entry in result["diagnostics"]] == ["E_CONTEXT"]
    tenant = tmp_path / "store" / "tenants" / tenant_directory("local")
    assert [path for path in tenant.rglob("*") if path.is_file()] == []
    status, out, _ = ingest(tmp_path, "h.ntf", octets, "--product-key", "EXERCISE-HEADER-ONLY-0001")
    result = json.loads(out)
    assert (status, result["state"], result["images"]) == (0, "committed", [])


# --------------------------------------------------------------------------- the exit-code table


@pytest.mark.parametrize(
    "name, octets, status, code",
    [
        ("geo.ntf", vector("geo_dms.ntf"), 0, None),
        ("tre.ntf", vector("unknown_duplicate_tre.ntf"), 5, "E_POLICY"),
        ("count.ntf", vector("bad_count.ntf"), 3, "E_DIGITS"),
        ("short.ntf", vector("truncated.ntf"), 3, "E_LENGTH"),
        ("long.ntf", vector("trailing.ntf"), 3, "E_LENGTH"),
        ("length.ntf", vector("bad_file_length.ntf"), 3, "E_LENGTH"),
        ("stype.ntf", vector("unsupported_stype.ntf"), 3, "E_PROFILE"),
        ("header.ntf", vector("header_only.ntf"), 2, "E_CONTEXT"),
        ("crypt.ntf", with_encryp(vector("mono_nsif101.ntf"), "file"), 4, "E_ENCRYPTED"),
        ("big.ntf", b"N" * 16_777_217, 6, "E_LIMIT"),
        ("c8.ntf", with_ic(vector("mono_nsif101.ntf"), "C8"), 0, None),
    ],
)
def test_an_ingest_exits_by_its_outcome(tmp_path, name, octets, status, code):
    got, out, err = ingest(tmp_path, name, octets)
    result = json.loads(out)
    assert got == status
    assert err[-1] == f"sc-imagery: ingest {result['state']} {result['record_id']}"
    if code is not None:
        assert code in [entry["code"] for entry in result["diagnostics"]]
    worker_ran = name != "big.ntf"
    assert err[:-1] == (MEMORY if worker_ran else [])


def committed_record(tmp_path, octets, name="v.ntf") -> str:
    status, out, _ = ingest(tmp_path, name, octets)
    assert status == 0, out
    return json.loads(out)["record_id"]


def test_a_preview_of_a_compressed_image_is_an_unsupported_operation(tmp_path):
    record_id = committed_record(tmp_path, with_ic(vector("mono_nsif101.ntf"), "C8"))
    status, out, err = sc(
        tmp_path, "preview", record_id, "--image", "0", "--store", "store", "--output", "p.png"
    )
    assert (status, out) == (4, "")
    assert err == MEMORY + ["sc-imagery: preview E_CODEC"]
    assert not (tmp_path / "p.png").exists()


def test_a_preview_of_an_eight_bit_image_with_four_significant_bits_succeeds(tmp_path):
    # Signed, four significant bits, PJUST R: -8, -1, 0, 7 stored as 0x08, 0x0F, 0x00, 0x07 and
    # shown over the range -8..7 as 0, 119, 136, 255 (span 15: 0, 1785/15, 2040/15, 3825/15).
    octets = build_nsif([image(abpp=4, pvtype="SI", data=bytes([0x08, 0x0F, 0x00, 0x07]))])
    record_id = committed_record(tmp_path, octets)
    status, out, err = sc(
        tmp_path, "preview", record_id, "--image", "0", "--store", "store", "--output", "p.png"
    )
    receipt = json.loads(out)
    assert (status, receipt["size"], receipt["channels"]) == (0, [2, 2], 1)
    assert err == MEMORY + [f"sc-imagery: preview ok {receipt['derivative_id']}"]
    png = (tmp_path / "p.png").read_bytes()
    # The ruled layout: signature, IHDR (25 octets), then IDAT holding filter 0 and each row.
    length = int.from_bytes(png[33:37], "big")
    assert png[37:41] == b"IDAT"
    assert zlib.decompress(png[41 : 41 + length]) == bytes([0, 0, 119, 0, 136, 255])


def test_a_preview_of_an_image_the_record_does_not_have_is_a_command_error(tmp_path):
    record_id = committed_record(tmp_path, vector("mono_nsif101.ntf"))
    status, _, err = sc(
        tmp_path, "preview", record_id, "--image", "1", "--store", "store", "--output", "p.png"
    )
    assert (status, err) == (2, MEMORY + ["sc-imagery: preview E_FIELD"])


def test_a_lookup_index_past_its_table_is_malformed_input(tmp_path):
    octets = build_nsif(
        [image(irep="RGB/LUT", irepband=b"LU", luts=LUT_TABLES, data=bytes([0, 1, 2, 4]))]
    )
    record_id = committed_record(tmp_path, octets)
    status, _, err = sc(
        tmp_path, "preview", record_id, "--image", "0", "--store", "store", "--output", "p.png"
    )
    assert (status, err) == (3, MEMORY + ["sc-imagery: preview E_FIELD"])
    assert not (tmp_path / "p.png").exists()


def test_an_unknown_or_malformed_record_id_is_a_command_error(tmp_path):
    committed_record(tmp_path, vector("mono_nsif101.ntf"))
    for record_id in ("3c1d7b56-7a0a-5f0e-9d6e-2b8f3a4c5d6e", "../../x", "%2e%2e"):
        status, out, err = sc(
            tmp_path, "replay", record_id, "--store", "store", "--output", "r.ntf"
        )
        assert (status, out, err) == (2, "", ["sc-imagery: replay E_FIELD"])
    assert not (tmp_path / "r.ntf").exists()


def test_a_replay_of_a_corrupted_original_is_an_integrity_failure(tmp_path):
    octets = vector("geo_dms.ntf")
    record_id = committed_record(tmp_path, octets)
    (path,) = (tmp_path / "store" / "tenants").glob("*/originals/*")
    os.chmod(path, 0o600)
    path.write_bytes(set_field(octets, 500, b"Z"))
    os.chmod(path, 0o400)
    status, out, err = sc(tmp_path, "replay", record_id, "--store", "store", "--output", "r.ntf")
    assert (status, out, err) == (7, "", ["sc-imagery: replay E_INTEGRITY"])
    assert not (tmp_path / "r.ntf").exists() and no_part(tmp_path)


@pytest.mark.parametrize(
    "document, status, code",
    [
        (recipe(raster={**recipe()["raster"], "bits": 16}), 4, "E_PROFILE"),
        (recipe(security={"classification": "R"}), 5, "E_POLICY"),
        ({key: value for key, value in recipe().items() if key != "capture_time"}, 3, "E_FIELD"),
        (recipe(raster={**recipe()["raster"], "samples_b64": "AAAA"}), 3, "E_LENGTH"),
        # A final newline and digits of another script pass the schema's searched patterns and
        # are refused as malformed recipe times (U+0662 U+0660 U+0662 U+0666: Arabic-Indic 2026).
        (recipe(product_time="2026-10-04T12:00:00Z\n"), 3, "E_FIELD"),
        (recipe(capture_time="\u0662\u0660\u0662\u0666-10-04T12:00:00Z"), 3, "E_FIELD"),
    ],
)
def test_an_export_exits_by_its_outcome(tmp_path, document, status, code):
    (tmp_path / "recipe.json").write_text(json.dumps(document))
    got, out, err = sc(
        tmp_path, "export-nc", "recipe.json", "--store", "store", "--output", "e.ntf"
    )
    assert (got, out, err) == (status, "", [f"sc-imagery: export-nc {code}"])
    assert not (tmp_path / "e.ntf").exists()


def test_rejected_and_refused_inputs_leak_no_source_text_on_stderr(tmp_path):
    planted = build_nsif(
        [
            image(
                iid1="SECRETXYZ",
                iid2="SECRETXYZ",
                isorce="SECRETXYZ",
                icords="G",
                igeolo=GEO,
                tres=tre("SCZZZZ", b"SECRETXYZ"),
            )
        ],
        ftitle="SECRETXYZ",
        oname="SECRETXYZ",
    )
    runs = [
        ingest(tmp_path, "planted.ntf", planted),
        ingest(tmp_path, "cut.ntf", planted[:-1]),
        ingest(tmp_path, "geocut.ntf", vector("geo_dms.ntf")[:-1]),
        sc(tmp_path, "inspect", tmp_path / "planted.ntf", "--json", "-"),
        sc(tmp_path, "inspect", tmp_path / "cut.ntf", "--json", "-"),
    ]
    assert [status for status, _, _ in runs] == [5, 3, 3, 0, 3]
    for _, _, err in runs:
        text = "\n".join(err)
        for needle in ("SECRETXYZ", "480000N0170000E", "480000N", "SCZZZZ"):
            assert needle not in text
    # Inspect prints structure only: no title, identifier, source or corner text.
    for _, out, _ in runs[3:]:
        assert "SECRETXYZ" not in out and "480000N" not in out


# --------------------------------------------------------------------------- paths


URIS = ["file:///tmp/x.ntf", "http://127.0.0.1/x", "s3://b/k", "C:x", "/vsicurl/x", ""]


@pytest.mark.parametrize("uri", URIS)
def test_a_uri_is_never_read_as_a_path(tmp_path, capsys, monkeypatch, uri):
    monkeypatch.chdir(tmp_path)
    cases = [
        (["inspect", uri, "--json", "-"], "INPUT"),
        (["inspect", "x.ntf", "--json", uri], "--json"),
        (["ingest", uri, "--store", "s", "--dataset", "d", "--synthetic", "true"], "INPUT"),
        (["ingest", "x.ntf", "--store", uri, "--dataset", "d", "--synthetic", "true"], "--store"),
        (["export-nc", uri, "--store", "s", "--output", "o.ntf"], "RECIPE.json"),
        (["export-nc", "r.json", "--store", "s", "--output", uri], "--output"),
        (
            [
                "preview",
                "3c1d7b56-7a0a-5f0e-9d6e-2b8f3a4c5d6e",
                "--image",
                "0",
                "--store",
                "s",
                "--output",
                uri,
            ],
            "--output",
        ),
        (
            ["replay", "3c1d7b56-7a0a-5f0e-9d6e-2b8f3a4c5d6e", "--store", "s", "--output", uri],
            "--output",
        ),
    ]
    for arguments, option in cases:
        assert cli.main(arguments) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.splitlines() == [f"sc-imagery: usage error: {option} names a URI"]
        if uri:
            assert uri not in captured.err
    assert os.listdir(tmp_path) == []


def test_a_local_name_with_a_colon_is_read_through_a_relative_path(tmp_path):
    write(tmp_path, "a:b.ntf", vector("geo_dms.ntf"))
    status, out, _ = sc(tmp_path, "inspect", "./a:b.ntf", "--json", "-")
    assert (status, json.loads(out)["valid"]) == (0, True)


def test_an_existing_output_is_replaced_only_on_request(tmp_path):
    source = write(tmp_path, "geo.ntf", vector("geo_dms.ntf"))
    (tmp_path / "i.json").write_bytes(b"keep")
    status, out, err = sc(tmp_path, "inspect", source, "--json", "i.json")
    assert (status, out) == (2, "")
    assert err == ["sc-imagery: usage error: --json exists; it is replaced only with --replace"]
    assert (tmp_path / "i.json").read_bytes() == b"keep"
    status, _, _ = sc(tmp_path, "inspect", source, "--json", "i.json", "--replace")
    assert status == 0 and json.loads((tmp_path / "i.json").read_text())["valid"] is True
    (tmp_path / "d").mkdir()
    status, _, err = sc(tmp_path, "inspect", source, "--json", "d", "--replace")
    assert (status, err) == (2, ["sc-imagery: usage error: --json is not a file"])
    assert no_part(tmp_path)


def test_an_output_without_its_directory_is_a_command_error(tmp_path):
    source = write(tmp_path, "geo.ntf", vector("geo_dms.ntf"))
    status, _, err = sc(tmp_path, "inspect", source, "--json", tmp_path / "missing" / "i.json")
    assert (status, err) == (2, ["sc-imagery: usage error: --json names no directory"])
    assert not (tmp_path / "missing").exists()


def test_an_existing_replay_output_is_kept_before_any_work(tmp_path):
    record_id = committed_record(tmp_path, vector("mono_nsif101.ntf"))
    (tmp_path / "r.ntf").write_bytes(b"keep")
    status, _, err = sc(tmp_path, "replay", record_id, "--store", "store", "--output", "r.ntf")
    assert (status, err) == (
        2,
        ["sc-imagery: usage error: --output exists; it is replaced only with --replace"],
    )
    assert (tmp_path / "r.ntf").read_bytes() == b"keep"
    status, _, _ = sc(
        tmp_path, "replay", record_id, "--store", "store", "--output", "r.ntf", "--replace"
    )
    assert status == 0 and (tmp_path / "r.ntf").read_bytes() == vector("mono_nsif101.ntf")


@pytest.mark.parametrize("kind", ["fifo", "directory", "absent"])
def test_an_input_that_is_not_a_regular_file_is_an_io_failure(tmp_path, kind):
    path = tmp_path / "input"
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    status, out, err = sc(tmp_path, "inspect", path, "--json", "-", timeout=60)
    assert (status, out, err) == (7, "", ["sc-imagery: inspect E_IO"])
    status, out, err = sc(
        tmp_path,
        "ingest",
        path,
        "--store",
        "store",
        "--dataset",
        "default",
        "--synthetic",
        "false",
        timeout=60,
    )
    result = json.loads(out)
    assert (status, result["state"]) == (7, "failed")
    assert [(e["code"], e["path"]) for e in result["diagnostics"]] == [("E_IO", "/input")]


def test_a_directory_that_is_not_a_store_is_a_command_error(tmp_path):
    source = write(tmp_path, "geo.ntf", vector("geo_dms.ntf"))
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "file").write_text("x")
    status, out, err = sc(
        tmp_path, "ingest", source, "--store", "other", "--dataset", "d", "--synthetic", "true"
    )
    assert (status, out, err) == (2, "", ["sc-imagery: usage error: --store is not a store"])
    assert os.listdir(tmp_path / "other") == ["file"]


# --------------------------------------------------------------------------- interrupts


def staging(tmp_path) -> list[str]:
    return os.listdir(tmp_path / "store" / "staging")


def test_an_interrupted_ingest_leaves_nothing(tmp_path):
    source = write(tmp_path, "geo.ntf", vector("geo_dms.ntf"))
    status, out, err = sc(
        tmp_path,
        "ingest",
        source,
        "--store",
        "store",
        "--dataset",
        "default",
        "--synthetic",
        "true",
        driver="staged",
    )
    assert (status, out) == (130, "")
    assert err[-1] == "sc-imagery: interrupted"
    assert staging(tmp_path) == []
    tenants = tmp_path / "store" / "tenants"
    assert [path for path in tenants.rglob("*") if path.is_file()] == []


@pytest.mark.parametrize(
    "point, arguments",
    [
        ("derivative_temp_written", ["preview", "{id}", "--image", "0", "--output", "o.png"]),
        ("replay_part_written", ["replay", "{id}", "--output", "o.ntf"]),
        ("export_temp_written", ["export-nc", "recipe.json", "--output", "o.ntf"]),
    ],
)
def test_an_interrupted_command_leaves_no_output_and_no_staging(tmp_path, point, arguments):
    record_id = committed_record(tmp_path, vector("geo_dms.ntf"))
    (tmp_path / "recipe.json").write_text(json.dumps(recipe()))
    command = [argument.replace("{id}", record_id) for argument in arguments]
    status, out, err = sc(tmp_path, *command, "--store", "store", driver=point)
    assert (status, out) == (130, "")
    assert err[-1] == "sc-imagery: interrupted"
    assert not (tmp_path / "o.png").exists() and not (tmp_path / "o.ntf").exists()
    assert no_part(tmp_path) and staging(tmp_path) == []
    tenant = tmp_path / "store" / "tenants" / tenant_directory("local")
    assert not list(tenant.glob("derivatives/*")) and not list(tenant.glob("exports/*"))


def test_exit_status_rows_by_code_stage_and_path():
    cases = [
        (("E_FIELD", "storage", "/record_id"), 2),
        (("E_FIELD", "pixels", "/window/bands"), 2),
        (("E_FIELD", "pixels", "/segments/image[0]/band[0]/LUTD"), 3),
        (("E_FIELD", "export", "/recipe/parent/record_id"), 3),
        (("E_LENGTH", "export", "/recipe/raster/samples_b64"), 3),
        (("E_PROFILE", "header", "/file_header/STYPE"), 3),
        (("E_PROFILE", "pixels", "/segments/image[0]/NBPP"), 4),
        (("E_PROFILE", "export", "/recipe/magic"), 4),
        (("E_CODEC", "pixels", "/segments/image[0]/IC"), 4),
        (("E_ENCRYPTED", "header", "/file_header/ENCRYP"), 4),
        (("E_POLICY", "export", "/replay/mutations"), 5),
        (("E_LIMIT", "input", "/input"), 6),
        (("E_TIMEOUT", "pixels", "/worker"), 6),
        (("E_BUSY", "input", "/worker"), 6),
        (("E_IO", "input", "/input"), 7),
        (("E_INTEGRITY", "storage", "/asset"), 7),
        (("E_INTERNAL", "pixels", "/worker"), 7),
        (("E_GEOMETRY", "geometry", "/segments/image[0]/IGEOLO"), 7),
        (("E_CONTEXT", "cdm", "/context/product_key"), 2),
    ]
    assert [cli.exit_status(*case) for case, _ in cases] == [status for _, status in cases]


def test_a_file_without_a_usable_date_is_ingested_with_an_explicit_as_of(tmp_path):
    octets = set_field(vector("mono_nsif101.ntf"), 25, b" " * 14)
    status, out, _ = ingest(tmp_path, "undated.ntf", octets)
    assert (status, [entry["code"] for entry in json.loads(out)["diagnostics"]]) == (
        2,
        ["E_CONTEXT"],
    )
    status, out, _ = ingest(
        tmp_path,
        "undated.ntf",
        octets,
        "--product-key",
        "EXERCISE-UNDATED-0001",
        "--as-of",
        "2026-10-04T12:00:00Z",
        "--as-of-basis",
        "the operator's stated snapshot instant",
    )
    result = json.loads(out)
    assert (status, result["state"]) == (0, "committed")
    (path,) = (tmp_path / "store" / "tenants").glob(f"*/records/{result['record_id']}.json")
    product = json.loads(path.read_text())["objects"][0]
    assert product["valid_from"] == "2026-10-04T12:00:00.000Z"
    assert product["attributes"]["stanag4545"]["images"][0]["capture_time"] == (
        "2026-10-04T12:00:00.000Z"
    )


def test_an_output_the_system_refuses_to_write_is_an_io_failure(tmp_path, capsys, monkeypatch):
    from synapse_imagery import ingest as ingest_module

    def refuse(*arguments, **options):
        raise PermissionError("refused")

    monkeypatch.setattr(ingest_module, "_deliver", refuse)
    source = write(tmp_path, "geo.ntf", vector("geo_dms.ntf"))
    assert cli.main(["inspect", str(source), "--json", str(tmp_path / "i.json")]) == 7
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.splitlines() == MEMORY + ["sc-imagery: inspect E_IO"]
    assert not (tmp_path / "i.json").exists()
