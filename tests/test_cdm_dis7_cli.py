"""Acceptance case A12: the `synapse-dis7` host command, run as a child process.

Every comparison of child output is on bytes: PDU octets are not UTF-8, so no `subprocess` call
here decodes its output. The child imports the package the parent imported, through
`PYTHONPATH`, so these tests judge the worktree, an installed wheel or a scratch copy alike.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

import synapse_cdm
from synapse_cdm import dis7_host
from synapse_cdm.version import PACKAGE_VERSION
from tests.dis7_support import STEMS, VECTORS, patch, seed, vector_bytes, vector_json

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
ENV = {**os.environ, "PYTHONPATH": str(PKG.parent), "PYTHONDONTWRITEBYTECODE": "1"}
EQUATOR = "equator_eastbound"


def _cli(*args, cwd=None):
    return subprocess.run([sys.executable, "-m", "synapse_cdm.dis7_host", *args],
                          capture_output=True, timeout=60, cwd=cwd, env=ENV)


def _context_flags(stem, classification="--synthetic"):
    context = vector_json(stem, "context")
    return ["--at", context["time_context"]["instant"], "--basis",
            context["time_context"]["basis"], "--session", context["session"], classification]


def _refused(result, status, prefix):
    assert result.returncode == status, result.stderr
    assert result.stdout == b""
    lines = result.stderr.split(b"\n")
    assert len(lines) == 2 and lines[1] == b"", result.stderr
    assert lines[0].startswith(prefix.encode("utf-8")), result.stderr


def _accepted(result):
    assert result.returncode == 0, result.stderr
    assert result.stderr == b""
    return result.stdout


def _a02():
    """The 4224-octet PDU of case A02: the seed declaring 255 records, with 255 zero records."""
    raw = patch(patch(seed(), 19, bytes([255])), 8, (4224).to_bytes(2, "big"))
    return raw + bytes(255 * 16)


def _write(path, data):
    path.write_bytes(data)
    return str(path)


def _decode(tmp_path, raw, stem=EQUATOR, *flags):
    return _cli("decode", "--input", _write(tmp_path / "input.dis", raw),
                *(flags or _context_flags(stem)))


def _replay_doc(tmp_path, doc, *flags):
    data = doc if isinstance(doc, bytes) else json.dumps(doc).encode("utf-8")
    return _cli("replay", "--input", _write(tmp_path / "entity.json", data), *flags)


# -- accepting --------------------------------------------------------------------------------


@pytest.mark.parametrize("stem", STEMS)
def test_t15_a12_replay_of_each_expected_document_is_byte_exact(stem):
    result = _cli("replay", "--input", str(VECTORS / f"{stem}.expected.json"))
    assert _accepted(result) == vector_bytes(stem)


@pytest.mark.parametrize("stem", STEMS)
def test_t15_a12_decode_then_replay_round_trips(stem, tmp_path):
    result = _cli("decode", "--input", str(VECTORS / f"{stem}.dis"), *_context_flags(stem),
                  cwd=tmp_path)
    stdout = _accepted(result)
    doc = json.loads(stdout)
    expected = vector_json(stem, "expected")
    digest = {"algorithm": "sha256", "value": hashlib.sha256(vector_bytes(stem)).hexdigest()}
    expected[0]["source"]["source_hash"] = digest
    expected[0]["residual"]["data"]["source_hash"] = digest
    assert doc == expected
    assert stdout == (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode()
    (tmp_path / "entity.json").write_bytes(stdout)
    replayed = _cli("replay", "--input", str(tmp_path / "entity.json"), cwd=tmp_path)
    assert _accepted(replayed) == vector_bytes(stem)
    assert sorted(os.listdir(tmp_path)) == ["entity.json"]


def test_t15_a12_source_hash_is_the_sha256_of_the_file_bytes(tmp_path):
    raw = patch(seed(), 129, b"X")
    doc = json.loads(_accepted(_decode(tmp_path, raw)))
    digest = {"algorithm": "sha256", "value": hashlib.sha256(raw).hexdigest()}
    assert doc[0]["source"]["source_hash"] == digest
    assert doc[0]["residual"]["data"]["source_hash"] == digest


def test_t15_a12_live_sets_synthetic_false_and_replay_asserts_flags(tmp_path):
    stdout = _accepted(_decode(tmp_path, seed(), EQUATOR, *_context_flags(EQUATOR, "--live")))
    doc = json.loads(stdout)
    assert doc[0]["source"]["synthetic"] is False
    assert doc[0]["residual"]["data"]["synthetic"] is False
    assert _accepted(_replay_doc(tmp_path, stdout)) == seed()
    assert _accepted(_replay_doc(tmp_path, stdout, "--live")) == seed()
    _refused(_replay_doc(tmp_path, stdout, "--synthetic"), 3,
             "E_REPLAY_PROVENANCE at [0].residual.data.synthetic: ")
    _refused(_replay_doc(tmp_path, stdout, "--session", "other"), 3,
             "E_REPLAY_PROVENANCE at [0].residual.data.session: ")


def test_t15_a12_maximal_pdu_round_trips(tmp_path):
    raw = _a02()
    assert len(raw) == 4224
    stdout = _accepted(_decode(tmp_path, raw))
    doc = json.loads(stdout)
    assert len(doc[0]["residual"]["data"]["pdu"]["variable_parameters_hex"]) == 255
    assert _accepted(_replay_doc(tmp_path, stdout)) == raw


def test_t15_a12_leading_dash_basis(tmp_path):
    flags = _context_flags(EQUATOR)
    at, session = flags[1], flags[5]
    raw_path = _write(tmp_path / "input.dis", seed())
    result = _cli("decode", "--input", raw_path, "--at", at, "--basis=-x", "--session", session,
                  "--synthetic")
    doc = json.loads(_accepted(result))
    assert doc[0]["residual"]["data"]["time_context"]["basis"] == "-x"
    split = _cli("decode", "--input", raw_path, "--at", at, "--basis", "-x", "--session", session,
                 "--synthetic")
    assert split.returncode == 2
    assert split.stdout == b""


def test_t15_a12_non_ascii_basis_round_trips(tmp_path):
    basis = "Základ: čas záznamu – 測試"
    flags = _context_flags(EQUATOR)
    flags[3] = basis
    stdout = _accepted(_decode(tmp_path, seed(), EQUATOR, *flags))
    assert stdout.isascii()
    doc = json.loads(stdout)
    assert doc[0]["residual"]["data"]["time_context"]["basis"] == basis
    assert doc[0]["source"]["transformations"][0].endswith(basis)
    assert _accepted(_replay_doc(tmp_path, stdout)) == seed()


def test_t15_a12_self_test_passes():
    lines = _accepted(_cli("self-test")).decode("utf-8").splitlines()
    assert lines[-1] == "self-test: 16 checks, 0 failed"
    assert sum(line.startswith("PASS ") for line in lines) == 16


def test_t15_a12_self_test_fails_on_a_changed_vector(tmp_path, capsysbinary, monkeypatch):
    root = tmp_path / "dis7"
    shutil.copytree(VECTORS, root / "vectors")
    wire = root / "vectors" / f"{EQUATOR}.dis"
    wire.write_bytes(patch(wire.read_bytes(), 129, b"X"))
    monkeypatch.setattr(dis7_host, "_fixture_dir", lambda: root)
    assert dis7_host.main(["self-test"]) == 3
    out = capsysbinary.readouterr().out
    lines = out.split(b"\n")
    assert b"FAIL decode equator_eastbound: mismatch" in lines
    assert b"FAIL envelope equator_eastbound: mismatch" in lines
    assert out.endswith(b"self-test: 16 checks, 2 failed\n")


def test_t15_a12_version():
    expected = (f"adapter dis7 1.0.0\npackage synapse-cdm {PACKAGE_VERSION}\n"
                "specification SC DIS7 SPEC 001 1.0\n").encode("utf-8")
    assert _accepted(_cli("--version")) == expected


# -- usage, exit 2 ----------------------------------------------------------------------------


def _decode_args(omit=None, classification=("--synthetic",)):
    flags = _context_flags(EQUATOR)[:6]
    pairs = {"--input": str(VECTORS / f"{EQUATOR}.dis"), flags[0]: flags[1], flags[2]: flags[3],
             flags[4]: flags[5]}
    args = ["decode"]
    for name, value in pairs.items():
        if name != omit:
            args += [name, value]
    return [*args, *classification]


USAGE_CASES = {
    "no command": [],
    "unknown command": ["frobnicate"],
    "decode without --input": _decode_args(omit="--input"),
    "decode without --at": _decode_args(omit="--at"),
    "decode without --basis": _decode_args(omit="--basis"),
    "decode without --session": _decode_args(omit="--session"),
    "decode without a classification": _decode_args(classification=()),
    "decode with both classifications": _decode_args(classification=("--synthetic", "--live")),
    "replay with both classifications": ["replay", "--input",
                                         str(VECTORS / f"{EQUATOR}.expected.json"),
                                         "--synthetic", "--live"],
}


@pytest.mark.parametrize("case", sorted(USAGE_CASES))
def test_t15_a12_usage_errors_exit_2(case):
    result = _cli(*USAGE_CASES[case])
    assert result.returncode == 2
    assert result.stdout == b""
    assert result.stderr != b""


def _with(args, name, value):
    args = list(args)
    args[args.index(name) + 1] = value
    return args


FLAG_CASES = {
    "decode bad --at": (_with(_decode_args(), "--at", "2026-04-29T06:15:60.000Z"),
                        "E_CONTEXT_TIME at time_context.instant: "),
    "decode blank --basis": (_with(_decode_args(), "--basis", " "),
                             "E_CONTEXT_TIME at time_context.basis: "),
    "decode bad --session": (_with(_decode_args(), "--session", "bad session"),
                             "E_CONTEXT_SESSION at session: "),
    "replay bad --session": (["replay", "--input", str(VECTORS / f"{EQUATOR}.expected.json"),
                              "--session", "bad session"], "E_CONTEXT_SESSION at session: "),
    "decode bad --at and a missing input": (
        _with(_with(_decode_args(), "--at", "2026-04-29T06:15:60.000Z"), "--input",
              str(VECTORS / "no-such-file.dis")),
        "E_CONTEXT_TIME at time_context.instant: "),
}


@pytest.mark.parametrize("case", sorted(FLAG_CASES))
def test_t15_a12_flag_context_errors_exit_2(case):
    args, prefix = FLAG_CASES[case]
    _refused(_cli(*args), 2, prefix)


# -- rejected, exit 3 -------------------------------------------------------------------------

DECODE_REFUSALS = {
    "header": (lambda: patch(seed(), 0, b"\x06"), "E_HEADER_UNSUPPORTED at byte[0]: "),
    "truncated": (lambda: seed()[:143], "E_LENGTH_MISMATCH at byte[143]: "),
    "oversize": (lambda: _a02() + b"\x00", "E_INPUT_LIMIT at $: "),
}


@pytest.mark.parametrize("case", sorted(DECODE_REFUSALS))
def test_t15_a12_decode_refusals_exit_3(case, tmp_path):
    make, prefix = DECODE_REFUSALS[case]
    _refused(_decode(tmp_path, make()), 3, prefix)


@pytest.mark.parametrize("size", [65536, 65537])
def test_t15_a12_replay_input_bound(size, tmp_path):
    data = (VECTORS / f"{EQUATOR}.expected.json").read_bytes()
    padded = data + b" " * (size - len(data))
    assert len(padded) == size
    result = _replay_doc(tmp_path, padded)
    if size == 65536:
        assert _accepted(result) == vector_bytes(EQUATOR)
    else:
        _refused(result, 3, "E_INPUT_LIMIT at $: ")


def _null_members(node, prefix=""):
    found = []
    for key, value in node.items():
        path = f"{prefix}{key}"
        if value is None:
            found.append(path)
        elif isinstance(value, dict):
            found += _null_members(value, path + ".")
    return found


def _without(doc, path):
    doc = json.loads(json.dumps(doc))
    node = doc[0]
    *parents, last = path.split(".")
    for key in parents:
        node = node[key]
    del node[last]
    return doc


@pytest.mark.parametrize("stem", STEMS)
def test_t15_a12_replay_refuses_each_absent_null_member(stem, tmp_path):
    doc = vector_json(stem, "expected")
    members = _null_members(doc[0])
    if stem == EQUATOR:
        assert sorted(members) == [
            "confidence", "integrity", "position.accuracy_m", "position.vertical", "quality",
            "residual.data.source_hash", "source.source_hash", "status", "symbol", "valid_to"]
    assert members
    for path in members:
        prefix = ("E_REPLAY_SHAPE at [0].residual.data" if path.startswith("residual.data.")
                  else "E_REPLAY_SHAPE at $: ")
        _refused(_replay_doc(tmp_path, _without(doc, path)), 3, prefix)


def _edited(edit):
    doc = vector_json(EQUATOR, "expected")
    edit(doc)
    return doc


def _set(path, value):
    def edit(doc):
        node = doc[0]
        *parents, last = path.split(".")
        for key in parents:
            node = node[key]
        node[last] = value
    return edit


def _duplicate_key():
    text = (VECTORS / f"{EQUATOR}.expected.json").read_bytes()
    data = text.replace(b'"valid_to": null', b'"valid_to": null, "valid_to": null', 1)
    assert data != text
    return data


REPLAY_REFUSALS = {
    "duplicate key": (_duplicate_key, None),
    "unparseable": (lambda: b"[{", "E_REPLAY_SHAPE at $: "),
    "bare object": (lambda: vector_json(EQUATOR, "expected")[0], "E_REPLAY_SHAPE at $: "),
    "empty array": (lambda: [], "E_REPLAY_SHAPE at $: "),
    "two elements": (lambda: vector_json(EQUATOR, "expected") * 2, "E_REPLAY_SHAPE at $: "),
    "entity_id upper-cased": (
        lambda: _edited(lambda doc: doc[0].update(entity_id=doc[0]["entity_id"].upper())),
        "E_REPLAY_SHAPE at $: "),
    "synthetic as 1": (lambda: _edited(_set("source.synthetic", 1)), "E_REPLAY_SHAPE at $: "),
    "valid_from respelled": (lambda: _edited(_set("valid_from", "2026-04-29T06:15:00Z")),
                             "E_REPLAY_SHAPE at $: "),
    "added member": (lambda: _edited(lambda doc: doc[0].update(zzz_probe="PAYLOAD-ECHO")),
                     "E_REPLAY_SHAPE at $: "),
    "residual null": (lambda: _edited(_set("residual", None)), "E_REPLAY_SHAPE at [0].residual: "),
    "residual namespace HLA": (lambda: _edited(_set("residual.namespace", "HLA")),
                               "E_REPLAY_SHAPE at [0].residual: "),
    "position changed": (lambda: _edited(_set("position.lat", 1.0)),
                         "E_REPLAY_CHANGED at [0].position: "),
}


@pytest.mark.parametrize("case", sorted(REPLAY_REFUSALS))
def test_t15_a12_replay_refusals_exit_3(case, tmp_path):
    make, prefix = REPLAY_REFUSALS[case]
    document = make()
    result = _replay_doc(tmp_path, document)
    if case == "duplicate key":
        with pytest.raises(dis7_host.Dis7Error) as caught:
            dis7_host.parse_json_text(document)
        error = caught.value
        assert (error.code, error.path) == ("E_TWIN_SCHEMA", "[0]")
        assert result.returncode == 3
        assert result.stdout == b""
        assert result.stderr == f"E_REPLAY_SHAPE at {error.path}: {error.message}\n".encode()
        return
    _refused(result, 3, prefix)
    if case == "added member":
        assert b"zzz_probe" not in result.stderr
        assert b"PAYLOAD-ECHO" not in result.stderr


# -- I/O, exit 4 ------------------------------------------------------------------------------


def _unreadable(kind, tmp_path):
    if kind == "missing":
        return str(tmp_path / "absent")
    if kind == "directory":
        return str(tmp_path)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    return str(fifo)


@pytest.mark.parametrize("kind", ["missing", "directory", "fifo"])
@pytest.mark.parametrize("command", ["decode", "replay"])
def test_t15_a12_unreadable_input_exits_4(command, kind, tmp_path):
    path = _unreadable(kind, tmp_path)
    args = [command, "--input", path]
    if command == "decode":
        args += _context_flags(EQUATOR)
    result = subprocess.run([sys.executable, "-m", "synapse_cdm.dis7_host", *args],
                            capture_output=True, timeout=30, env=ENV)
    _refused(result, 4, "synapse-dis7: cannot read --input: ")


BROKEN_PIPE_CASES = {
    "version": ["--version"],
    "self-test": ["self-test"],
    "replay": ["replay", "--input", str(VECTORS / f"{EQUATOR}.expected.json")],
    "decode": ["decode", "--input", str(VECTORS / f"{EQUATOR}.dis"), *_context_flags(EQUATOR)],
}


@pytest.mark.parametrize("case", sorted(BROKEN_PIPE_CASES))
def test_t15_a12_broken_pipe_exits_4(case):
    r, w = os.pipe()
    os.close(r)
    try:
        child = subprocess.Popen(
            [sys.executable, "-m", "synapse_cdm.dis7_host", *BROKEN_PIPE_CASES[case]],
            stdout=w, stderr=subprocess.PIPE, env=ENV)
    finally:
        os.close(w)
    _, err = child.communicate(timeout=60)
    assert child.returncode == 4, err
    lines = err.split(b"\n")
    assert len(lines) == 2 and lines[1] == b"", err
    assert lines[0].startswith(b"synapse-dis7: cannot write output: ")
    assert b"Exception ignored" not in err
    assert b"Traceback" not in err


@pytest.mark.parametrize("case", sorted(BROKEN_PIPE_CASES))
def test_t15_a12_closed_stdout_exits_4(case):
    result = subprocess.run(
        [sys.executable, "-m", "synapse_cdm.dis7_host", *BROKEN_PIPE_CASES[case]],
        stdout=None, stderr=subprocess.PIPE, timeout=60, env=ENV,
        preexec_fn=lambda: os.close(1))
    assert result.returncode == 4, result.stderr
    assert result.stderr == b"synapse-dis7: cannot write output: stdout is closed\n"


@pytest.mark.parametrize("case", sorted(BROKEN_PIPE_CASES))
def test_t15_a12_closed_stdout_and_stderr_exits_4(case):
    result = subprocess.run(
        [sys.executable, "-m", "synapse_cdm.dis7_host", *BROKEN_PIPE_CASES[case]],
        stdout=None, stderr=None, timeout=60, env=ENV,
        preexec_fn=lambda: (os.close(1), os.close(2)))
    assert result.returncode == 4


# -- structure --------------------------------------------------------------------------------

FORBIDDEN_ROOTS = {"hashlib", "signal", "resource", "platform", "socket", "subprocess"}


def test_t15_a12_host_module_import_rules():
    tree = ast.parse(pathlib.Path(dis7_host.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots = {(node.module or "").split(".")[0]}
        else:
            continue
        assert not roots & FORBIDDEN_ROOTS, ast.dump(node)
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert all("evidence" not in alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert "evidence" not in (node.module or "")
            assert all(alias.name != "evidence" for alias in node.names)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "open":
            modes = [*node.args[1:2], *(k.value for k in node.keywords if k.arg == "mode")]
            assert len(modes) == 1 and isinstance(modes[0], ast.Constant) \
                and modes[0].value == "rb", ast.dump(node)
    os_opens = []
    for function in tree.body:
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr == "open" and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id == "os":
                os_opens.append((function.name, node))
    assert len(os_opens) == 1
    assert sum(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
               and node.func.attr == "open" and isinstance(node.func.value, ast.Name)
               and node.func.value.id == "os" for node in ast.walk(tree)) == 1
    name, call = os_opens[0]
    assert name == "_emit"
    first = call.args[0]
    assert isinstance(first, ast.Attribute) and first.attr == "devnull" \
        and isinstance(first.value, ast.Name) and first.value.id == "os"
    child = subprocess.run(
        [sys.executable, "-c",
         "import sys, synapse_cdm.dis7_host; print('synapse_cdm.evidence' in sys.modules)"],
        capture_output=True, timeout=60, env=ENV)
    assert child.stdout.strip() == b"False", child.stderr
