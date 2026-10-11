"""Static hygiene of the package (the rules the CodeQL security-extended suite judges, the API
surface, and REQ030/REQ151), read from the AST of every module of `synapse_link16_bridge`."""
import ast
import pathlib
import re

import pytest

import synapse_link16_bridge
from synapse_link16_bridge.gateway import server

PACKAGE = pathlib.Path(synapse_link16_bridge.__file__).parent
MODULES = sorted(PACKAGE.rglob("*.py"))
SQL_HOMES = {"store.py", "provider.py"}
SENSITIVE = re.compile(r"password|secret|token|credential", re.IGNORECASE)


def tree(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def calls(path):
    return [node for node in ast.walk(tree(path)) if isinstance(node, ast.Call)]


def name_of(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def enclosing_functions(path):
    """Each call mapped to the name of the function it sits in."""
    out = {}
    for function in ast.walk(tree(path)):
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(function):
                if isinstance(node, ast.Call):
                    out[(node.lineno, node.col_offset)] = function.name
    return out


def test_every_module_parses_at_the_311_floor():
    assert len(MODULES) >= 25
    for path in MODULES:
        ast.parse(path.read_text(encoding="utf-8"), feature_version=(3, 11))


def test_sql_first_arguments_are_module_constants():
    checked = 0
    for path in MODULES:
        functions = enclosing_functions(path)
        for node in calls(path):
            if name_of(node.func) not in ("execute", "executemany", "executescript", "query",
                                          "one") or not isinstance(node.func, ast.Attribute):
                continue
            if not node.args:
                continue
            first = node.args[0]
            where = functions.get((node.lineno, node.col_offset))
            if path.name == "store.py" and where in ("query", "one"):
                assert isinstance(first, ast.Name) and first.id == "sql"
                continue
            assert name_of(first) is not None and name_of(first).startswith("SQL_"), \
                f"{path.name}:{node.lineno}"
            checked += 1
    assert checked > 100


def test_every_sql_constant_is_a_literal_string_in_a_store_module():
    found = 0
    for path in MODULES:
        for node in tree(path).body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
                                                    t.id.startswith("SQL_") for t in node.targets):
                assert path.name in SQL_HOMES, path.name
                assert isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
                found += 1
    assert found > 80
    for path in MODULES:
        for node in ast.walk(tree(path)):
            assert not isinstance(node, ast.JoinedStr) or not any(
                isinstance(v, ast.Constant) and re.search(r"\b(SELECT|INSERT|UPDATE|DELETE)\b",
                                                          str(v.value))
                for v in node.values), f"{path.name}: SQL in an f-string"


@pytest.mark.parametrize("banned", ["subprocess", "pickle", "marshal", "yaml", "shelve",
                                    "socketserver"])
def test_no_dangerous_import(banned):
    for path in MODULES:
        for node in ast.walk(tree(path)):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] != banned for alias in node.names), path.name
            if isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != banned, path.name


def test_no_shell_eval_or_exec():
    for path in MODULES:
        for node in calls(path):
            assert name_of(node.func) not in ("eval", "exec", "system", "popen", "compile") or \
                isinstance(node.func, ast.Attribute) and name_of(node.func) == "compile" and \
                name_of(node.func.value) == "re", f"{path.name}:{node.lineno}"
            for keyword in node.keywords:
                assert not (keyword.arg == "shell" and getattr(keyword.value, "value", False))


def test_the_server_imports_neither_pathlib_nor_http_client():
    source = pathlib.Path(server.__file__)
    imported = set()
    for node in ast.walk(tree(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert "pathlib" not in imported and "http.client" not in imported


def test_logging_takes_fixed_text_and_closed_codes():
    for path in MODULES:
        for node in calls(path):
            receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
            if name_of(receiver) in ("LOG", "logging", "logger") and name_of(node.func) in (
                    "debug", "info", "warning", "error", "exception", "critical", "log"):
                assert path.name == "observe.py", f"{path.name}:{node.lineno}"
                assert isinstance(node.args[0], ast.Constant)
            if name_of(node.func) == "log_event":
                assert isinstance(node.args[0], ast.Constant), f"{path.name}:{node.lineno}"


def test_no_credential_reaches_a_log_the_store_or_a_hash():
    sinks = {"execute", "executemany", "log_event", "info", "warning", "error", "debug",
             "record", "sha256", "sha256_hex", "md5", "new", "canonical"}
    for path in MODULES:
        for node in calls(path):
            if name_of(node.func) not in sinks:
                continue
            for argument in list(node.args) + [k.value for k in node.keywords]:
                for inner in ast.walk(argument):
                    label = name_of(inner)
                    assert not (label and SENSITIVE.search(label)), f"{path.name}:{node.lineno}"


def test_tls_is_never_weakened():
    for path in MODULES:
        text = path.read_text(encoding="utf-8")
        assert "CERT_NONE" not in text and "_create_unverified_context" not in text
        assert not re.search(r"check_hostname\s*=\s*False", text)
        assert not re.search(r"verify_mode\s*=", text)


def test_the_bind_address_is_the_loopback_literal():
    assert server.BIND_ADDRESS == "127.0.0.1"
    text = pathlib.Path(server.__file__).read_text(encoding="utf-8")
    assert "_Server((BIND_ADDRESS, port), _Handler)" in text
    assert '"0.0.0.0"' not in text and "''" not in text.split("_Server((")[1][:40]


def test_the_loopback_check_compares_the_parsed_hostname():
    for path in MODULES:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"startswith\(\s*[\"']https?://", text), path.name
    for name in ("config.py", "gateway/client.py"):
        text = (PACKAGE / name).read_text(encoding="utf-8")
        assert "urlsplit" in text and re.search(r"hostname\s+in\s+LOOPBACK_HOSTS", text)


def test_regexes_have_no_nested_quantifiers():
    patterns = []
    for path in MODULES:
        for node in calls(path):
            if name_of(node.func) == "compile" and name_of(getattr(node.func, "value", None)) \
                    == "re":
                pattern = node.args[0]
                if isinstance(pattern, ast.Constant):
                    patterns.append(pattern.value)
    assert len(patterns) >= 8
    for pattern in patterns:
        assert not re.search(r"[+*}]\)[+*{]", pattern), pattern


def test_the_api_surface_is_the_six_endpoints():
    assert server.ENDPOINTS == (("GET", "/v1/capabilities"), ("GET", "/v1/reports"),
                                ("POST", "/v1/ack"), ("POST", "/v1/transmissions"),
                                ("GET", "/v1/transmissions/{request_id}"), ("GET", "/v1/health"))
    paths = set()
    for node in ast.walk(tree(pathlib.Path(server.__file__))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and \
                node.value.startswith("/v1/"):
            paths.add(node.value)
    assert paths == {"/v1/capabilities", "/v1/reports", "/v1/ack", "/v1/transmissions",
                     "/v1/transmissions/{request_id}", "/v1/health",
                     "/v1/transmissions/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}"
                     "-[0-9a-f]{12})"}


def test_the_server_never_calls_send_error_and_never_answers_with_exception_text():
    source = pathlib.Path(server.__file__)
    for node in calls(source):
        assert name_of(node.func) != "send_error"
        assert name_of(node.func) not in ("repr", "format_exc")
        if name_of(node.func) == "str":
            assert not any(isinstance(a, ast.Name) and a.id in ("error", "e", "exc", "problem")
                           for a in node.args)


def test_cli_evidence_is_the_only_raw_evidence_reader():
    """REQ151: raw evidence access is controlled separately from the ordinary outputs."""
    readers = {}
    for path in MODULES:
        for node in calls(path):
            label = name_of(node.func)
            if label in ("read_raw_evidence", "read_evidence"):
                readers.setdefault(label, set()).add(path.name)
    assert readers == {"read_raw_evidence": {"bridge.py"}, "read_evidence": {"cli.py"}}


def test_no_code_reads_a_label_number_to_fill_a_semantic_field():
    """REQ030: the family is compared for equality with configured families and copied; no
    module parses it."""
    for path in MODULES:
        for node in calls(path):
            if name_of(node.func) in ("int", "float", "split", "match", "fullmatch", "search",
                                      "partition", "findall"):
                for argument in list(node.args) + ([node.func.value] if isinstance(
                        node.func, ast.Attribute) else []):
                    text = ast.unparse(argument)
                    assert "message_family" not in text and "family" != text, \
                        f"{path.name}:{node.lineno}"


def test_every_runtime_import_is_the_standard_library_synapse_cdm_or_the_package():
    """HYGIENE-4 (A2F, 2026-10-11): L-11's runtime dependencies are synapse-cdm and the standard
    library only; every absolute import of every module is one of them or the package itself."""
    import sys
    allowed = set(sys.stdlib_module_names) | {"synapse_cdm", "synapse_link16_bridge"}
    outside, seen = [], 0
    for path in MODULES:
        for node in ast.walk(tree(path)):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module]
            else:
                continue
            for name in names:
                seen += 1
                if name.split(".")[0] not in allowed:
                    outside.append(f"{path.relative_to(PACKAGE)}:{node.lineno} {name}")
    assert seen > 150
    assert outside == []
