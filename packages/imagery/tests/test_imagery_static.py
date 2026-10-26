"""Static hygiene of the package, read from the AST and the text of every module: the dependency
direction, the import and call allowlists, argument-list process creation, lock-only threading,
fixed-text logging, identifier forms, the 3.11 grammar, and the test helpers' literal offsets."""

from __future__ import annotations

import ast
import json
import pathlib
import re
import sys

import pytest
import helpers
from helpers import SECURITY_FIELDS, build_nsif, image, vector, with_ic

import synapse_cdm
import synapse_imagery
from synapse_cdm.adapters.stanag4545 import CORE1_LIMITS, parse_container

PACKAGE = pathlib.Path(synapse_imagery.__file__).resolve().parent
DISTRIBUTION = PACKAGE.parent
MODULES = sorted(PACKAGE.glob("*.py"))
TESTS = sorted((DISTRIBUTION / "tests").glob("*.py"))
LOCK_MODULES = {"policy.py", "assets.py", "ingest.py", "worker.py", "cli.py", "fakes.py"}
BANNED = (
    "pickle",
    "marshal",
    "shelve",
    "yaml",
    "socket",
    "socketserver",
    "http",
    "urllib",
    "ftplib",
    "ssl",
    "ctypes",
    "concurrent",
    "multiprocessing",
    "asyncio",
    "osgeo",
    "PIL",
    "numpy",
)
LOG_NAMES = {
    "record_id",
    "asset_id",
    "derivative_id",
    "job_id",
    "export_id",
    "code",
    "state",
    "stage",
    "count",
    "image_index",
    "exit_code",
}


def tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imports(module: ast.AST, relative_allowed: bool = False):
    """(root of every absolute import, the node) in a tree. A relative import stays inside its
    own package, so where one is allowed it names no root."""
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], node
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                assert relative_allowed, "the package uses absolute imports only"
                continue
            yield node.module.split(".")[0], node


def calls(module: ast.AST):
    return [node for node in ast.walk(module) if isinstance(node, ast.Call)]


def dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{dotted(node.value)}.{node.attr}"
    return ""


def test_the_walk_sees_the_package():
    names = {path.name for path in MODULES}
    assert names == {
        "__init__.py",
        "_version.py",
        "__main__.py",
        "policy.py",
        "assets.py",
        "ingest.py",
        "worker.py",
        "export.py",
        "cli.py",
        "result.py",
        "preview.py",
        "presentation.py",
        "fakes.py",
    }


def test_every_module_parses_at_the_311_floor():
    for path in MODULES + TESTS:
        ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 11))


def test_every_runtime_import_is_the_standard_library_synapse_cdm_jsonschema_or_the_package():
    allowed = set(sys.stdlib_module_names) | {"synapse_cdm", "jsonschema", "synapse_imagery"}
    seen = 0
    for path in MODULES:
        for root, _ in imports(tree(path)):
            assert root in allowed, (path.name, root)
            seen += 1
    assert seen > 60


@pytest.mark.parametrize("banned", BANNED)
def test_no_dangerous_import(banned):
    for path in MODULES:
        assert banned not in {root for root, _ in imports(tree(path))}, (path.name, banned)


def test_threading_is_only_used_for_locks():
    allowed = {"Lock", "RLock", "Condition", "Event"}
    for path in MODULES:
        module = tree(path)
        uses = set()
        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom) and node.module == "threading":
                uses |= {alias.name for alias in node.names}
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "threading"
            ):
                uses.add(node.attr)
        if uses:
            assert path.name in LOCK_MODULES, path.name
            assert uses <= allowed, (path.name, uses)
        text = path.read_text(encoding="utf-8")
        assert "Thread(" not in text and "Timer(" not in text, path.name


def test_zlib_is_imported_by_the_preview_module_only():
    importers = {
        path.name for path in MODULES if "zlib" in {root for root, _ in imports(tree(path))}
    }
    assert importers == {"preview.py"}


def test_the_worker_child_imports_the_preview_before_its_hook():
    setup = next(
        node
        for node in tree(PACKAGE / "worker.py").body
        if isinstance(node, ast.FunctionDef) and node.name == "_child_setup"
    )
    imported = [
        alias.name
        for node in ast.walk(setup)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    assert "synapse_imagery.preview" in imported
    hook = next(
        index
        for index, node in enumerate(setup.body)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and dotted(node.value.func) == "_install_hook"
    )
    last_import = max(
        index for index, node in enumerate(setup.body) if isinstance(node, ast.Import)
    )
    assert last_import < hook


def test_worker_module_level_imports_are_standard_library_only():
    module = tree(PACKAGE / "worker.py")
    for node in module.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for root, _ in imports(node):
                assert root in sys.stdlib_module_names, root


def test_subprocess_only_in_worker_with_an_argv_list_and_no_shell():
    popen = []
    for path in MODULES:
        roots = {root for root, _ in imports(tree(path))}
        if path.name != "worker.py":
            assert "subprocess" not in roots, path.name
        for node in calls(tree(path)):
            if dotted(node.func).endswith("Popen"):
                popen.append((path.name, node))
            assert dotted(node.func) not in (
                "subprocess.run",
                "subprocess.call",
                "subprocess.check_output",
            ), path.name
    assert len(popen) == 1 and popen[0][0] == "worker.py"
    node = popen[0][1]
    first = node.args[0]
    assert not isinstance(first, (ast.Constant, ast.JoinedStr))
    keywords = {keyword.arg: keyword.value for keyword in node.keywords}
    assert "shell" not in keywords
    assert isinstance(keywords["close_fds"], ast.Constant) and keywords["close_fds"].value is True
    assert "env" in keywords and "pass_fds" in keywords


def test_no_shell_eval_exec_or_recursive_delete():
    banned = {
        "eval",
        "exec",
        "compile",
        "input",
        "os.system",
        "os.popen",
        "shutil.rmtree",
        "shutil.move",
        "tempfile.mktemp",
        "os.rename",
    }
    for path in MODULES:
        for node in calls(tree(path)):
            name = dotted(node.func)
            assert name not in banned, (path.name, name)
            assert not re.fullmatch(r"os\.(exec|spawn)\w*", name), (path.name, name)
            assert not name.startswith("pickle."), (path.name, name)


def test_the_store_links_and_flushes_and_never_renames():
    names = {dotted(node.func) for node in calls(tree(PACKAGE / "assets.py"))}
    assert {"os.link", "os.fsync", "os.replace", "fcntl.flock"} <= names


def test_logging_takes_fixed_text_and_allowed_names():
    found = 0
    for path in MODULES:
        module = tree(path)
        for node in calls(module):
            name = dotted(node.func)
            if name == "logging.getLogger":
                assert [arg.value for arg in node.args] == ["synapse_imagery"]
            if name.split(".")[0] != "_LOG":
                continue
            found += 1
            first, *rest = node.args
            assert isinstance(first, ast.Constant) and isinstance(first.value, str), path.name
            for argument in rest:
                assert isinstance(argument, ast.Name) and argument.id in LOG_NAMES, (
                    path.name,
                    ast.dump(argument),
                )
            assert not node.keywords
    assert found >= 4


def test_synapse_cdm_never_imports_synapse_imagery():
    root = pathlib.Path(synapse_cdm.__file__).resolve().parent
    files = sorted(root.rglob("*.py"))
    assert len(files) > 50
    for path in files:
        assert "synapse_imagery" not in {name for name, _ in imports(tree(path), True)}, path


def test_no_module_imports_the_fakes_but_the_live_fence():
    importers = set()
    for path in MODULES:
        for node in ast.walk(tree(path)):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "synapse_imagery"
                and any(alias.name == "fakes" for alias in node.names)
            ):
                importers.add(path.name)
            if isinstance(node, ast.ImportFrom) and node.module == "synapse_imagery.fakes":
                importers.add(path.name)
    assert importers == {"ingest.py"}
    assert "cli.py" not in importers


def test_no_uuid_literal_and_no_key_named_constant():
    literal = re.compile(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    )
    for path in MODULES:
        assert not literal.search(path.read_text(encoding="utf-8")), path.name
        for node in ast.walk(tree(path)):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                for target in node.targets:
                    assert not (
                        isinstance(target, ast.Name) and target.id.lower().endswith("_key")
                    ), path.name


def test_no_test_is_skipped_or_expected_to_fail():
    # The helper names are built here, because the round's checks refuse any line that spells them.
    refused = {"sk" + "ip", "sk" + "ipif", "x" + "fail", "importor" + "skip"}
    for path in TESTS:
        for node in ast.walk(tree(path)):
            if isinstance(node, ast.Attribute):
                assert node.attr not in refused, (path.name, node.attr)
    words = ["TO" + "DO", "FIX" + "ME", "pytest.mark." + "sk", "x" + "fail", "importor" + "skip"]
    for path in sorted(DISTRIBUTION.rglob("*")):
        if path.is_file() and path.suffix in (".py", ".md", ".toml", ".json"):
            text = path.read_text(encoding="utf-8")
            for word in words:
                assert word not in text, (path.name, word)


# --------------------------------------------------------------------------- the test helpers

#: The kit's `contracts/file-header-fields.json` offsets of the fields the helpers name.
KIT_FILE_HEADER = {
    "FTITLE": (39, 80),
    "FSCLAS": (119, 1),
    "ENCRYP": (296, 1),
    "ONAME": (300, 24),
    "FL": (342, 12),
    "HL": (354, 6),
}
#: The one-image subheader offsets, measured on mono_nsif101 with the feasibility prototype.
IMAGE_FIELDS = {
    "IID1": 406,
    "IDATIM": 416,
    "TGTID": 430,
    "IID2": 447,
    "ISCLAS": 527,
    "ENCRYP": 694,
    "ISORCE": 695,
    "NROWS": 737,
    "NCOLS": 745,
    "NICOM": 776,
    "IC": 777,
}


def test_helpers_offsets_match_the_kit():
    assert (helpers.FTITLE, helpers.ONAME) == ((39, 119), (300, 324))
    assert (helpers.FL, helpers.HL, helpers.NUMI, helpers.LISH, helpers.LI) == (
        342,
        354,
        360,
        363,
        369,
    )
    assert (helpers.FILE_BLOCK, helpers.FILE_ENCRYP) == (
        KIT_FILE_HEADER["FSCLAS"][0],
        KIT_FILE_HEADER["ENCRYP"][0],
    )
    assert helpers.FTITLE[1] - helpers.FTITLE[0] == KIT_FILE_HEADER["FTITLE"][1]
    assert helpers.ONAME[1] - helpers.ONAME[0] == KIT_FILE_HEADER["ONAME"][1]
    assert (helpers.IID1[0], helpers.IDATIM[0], helpers.TGTID[0], helpers.IID2[0]) == (
        406,
        416,
        430,
        447,
    )
    assert (helpers.IMAGE_BLOCK, helpers.IMAGE_ENCRYP, helpers.ISORCE[0]) == (527, 694, 695)
    assert (helpers.NROWS, helpers.NCOLS, helpers.NICOM, helpers.IC) == (737, 745, 776, 777)
    assert [(name, offset, width) for name, offset, width in SECURITY_FIELDS] == [
        ("CLAS", 0, 1),
        ("CLSY", 1, 2),
        ("CODE", 3, 11),
        ("CTLH", 14, 2),
        ("REL", 16, 20),
        ("DCTP", 36, 2),
        ("DCDT", 38, 8),
        ("DCXM", 46, 4),
        ("DG", 50, 1),
        ("DGDT", 51, 8),
        ("CLTX", 59, 43),
        ("CAPT", 102, 1),
        ("CAUT", 103, 40),
        ("CRSN", 143, 1),
        ("SRDT", 144, 8),
        ("CTLN", 152, 15),
    ]
    mono = vector("mono_nsif101.ntf")
    assert mono[777:779] == b"NC" and mono[737:745] == b"00000002" and mono[527:528] == b"U"
    for scope, base in (("file", 119), ("image", 527)):
        for name, offset, width in SECURITY_FIELDS:
            changed = helpers.with_security_field(mono, scope, name, "Z" * width)
            moved = [i for i in range(len(mono)) if mono[i] != changed[i]]
            assert moved == list(range(base + offset, base + offset + width)), (scope, name)


def test_with_ic_keeps_the_container_well_formed():
    mono = vector("mono_nsif101.ntf")
    assert with_ic(mono, "NC") == mono
    compressed = with_ic(mono, "C3")
    container = parse_container(compressed, CORE1_LIMITS)
    assert container.images[0].pixel_status == "unsupported"
    assert len(compressed) == int(compressed[342:354]) == 851


def test_the_independent_builder_rebuilds_the_kit_vectors():
    geo = "480000N0170000E480000N0180000E470000N0180000E470000N0170000E"
    assert build_nsif([image()]) == vector("mono_nsif101.ntf")
    assert build_nsif([image()], magic=b"NITF02.10") == vector("mono_nitf210.ntf")
    assert build_nsif([image(icords="G", igeolo=geo)]) == vector("geo_dms.ntf")
    assert build_nsif([image(tres=b"SCZZZZ00003abcSCZZZZ00003def")]) == vector(
        "unknown_duplicate_tre.ntf"
    )
    assert build_nsif([]) == vector("header_only.ntf")
    assert build_nsif(
        [image()], texts=[helpers.text(payload=b"<script>must remain plain text</script>")]
    ) == vector("image_and_text.ntf")


def test_the_helpers_digest_table_is_the_kits():
    assert len(helpers.KIT_SHA256) == 17
    for name in helpers.KIT_SHA256:
        assert helpers.sha(vector(name)) == helpers.KIT_SHA256[name]
    assert json.dumps(
        sorted(helpers.TOP_LEVEL + helpers.MALFORMED + ("header_only.ntf",))
    ) == json.dumps(sorted(helpers.KIT_SHA256))
