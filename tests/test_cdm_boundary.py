"""The CDM is the contract layer, so it may not depend on a consumer of the contract.

Same enforcement as agent isolation and the airtasking boundary: AST over the source, not a
convention in a docstring. A contract package that imports `core` or `platform` cannot be
lifted into another service, cannot be published to a non-Python consumer, and turns every
change in a consumer into a possible change in the contract.

The second test is the one that matters for the `integrity` field: the CDM must contain NO
crypto. The field is designed and unpopulated on purpose (see models.Integrity), and an import
of `cryptography` or `hashlib` here would mean somebody had started signing objects inside the
translation layer — where the key material has no business being and where nothing audits it.
"""
import ast
import pathlib

import pytest

import synapse_cdm

# The package lives under packages/cdm/ while this suite sits at the repo root, so its
# internal files are located through the import system rather than by walking up from
# this file: a relative hop between the two breaks the moment either one moves, and this
# way the files checked are the ones belonging to the package that is actually importable.
PACKAGE = pathlib.Path(synapse_cdm.__file__).resolve().parent
ROOT = PACKAGE.parent

FORBIDDEN_ROOTS = {"agents", "core", "platform", "synapse_data", "synapse-data", "airtasking",
                   "verification", "scripts"}
FORBIDDEN_CRYPTO = {"cryptography", "hashlib", "hmac", "nacl", "oqs", "secrets", "ssl"}

SOURCES = sorted(PACKAGE.rglob("*.py"))


def _imported_roots(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_the_package_has_sources_to_check():
    """A boundary test that silently checks nothing is worse than no boundary test."""
    assert len(SOURCES) >= 10, f"expected the CDM package, found {len(SOURCES)} modules"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_import_from_a_consumer(path):
    offending = _imported_roots(path) & FORBIDDEN_ROOTS
    assert not offending, (
        f"{path.relative_to(ROOT)} imports {sorted(offending)} — synapse_cdm is the contract "
        "layer and must not depend on anything that consumes it"
    )


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_crypto_in_the_contract_layer(path):
    offending = _imported_roots(path) & FORBIDDEN_CRYPTO
    assert not offending, (
        f"{path.relative_to(ROOT)} imports {sorted(offending)} — the `integrity` field is "
        "designed, not implemented (models.Integrity). Signing belongs to the ledger, which "
        "holds the keys and is audited; a signature computed inside a translator is neither"
    )
