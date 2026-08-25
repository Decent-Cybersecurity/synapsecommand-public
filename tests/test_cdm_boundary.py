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
#: The repository root, for the prose sites the ruling below pins the gate against.
REPO = PACKAGE.parents[2]

#: The top-level packages of the private product repository this one was lifted out of. An import
#: of any of them here would end the independence `README.md` advertises.
#:
#: THE NAMES ARE REAL, AND THEY STAY. RULED, so the pre-publication finding does not reopen.
#:
#: This is the only place in a public repository where the private core's directory structure is
#: written down, and a publication audit is right to stop on it. Three things decide it:
#:
#: 1. **The names are LOAD-BEARING.** This is a negative test — "no module imports any of these" —
#:    so it is satisfied vacuously by any name the core does not actually use. Sanitising them to
#:    `PRIVATE_A`, `PRIVATE_B` would leave a gate that passes forever while enforcing nothing, and
#:    the README's independence claim would then rest on a test that cannot fail. **A gate that
#:    cannot fail is a worse exposure than the topology it was hiding**, because the thing it was
#:    protecting stops being protected and nobody can tell.
#: 2. **Names reveal STRUCTURE, not CONTENT.** Five top-level directory names and one file path
#:    (`synapse-data/contracts/track.schema.json`, cited in `synapse_cdm/__init__.py` as the
#:    contract this model is deliberately NOT). No endpoint, no credential, no hostname, no
#:    business logic, no schema body. What a reader learns is that a product repository has an
#:    agents directory — which the word "agents" in this project's public description already says.
#: 3. **Every reference is survivable without access.** All of them are NEGATIVE statements —
#:    "nothing here comes from there", "this is not that contract" — so a reader who cannot open
#:    the core loses nothing by reading them. There is no link to follow and no presupposition of
#:    access anywhere in the tree.
#:
#: The other sites naming these roots are `synapse_cdm/__init__.py`, `synapse_cdm/README.md` and
#: `MIGRATIONS.md`, and all four were reviewed together at the audit. If the core is ever
#: restructured, the repair is to update these names — not to remove them, which would silently
#: retire the gate.
FORBIDDEN_ROOTS = {"agents", "core", "platform", "synapse_data", "synapse-data", "airtasking",
                   "verification", "scripts"}
#: The sites that also name these roots, in prose. The gate and the prose are the SAME FACT
#: stated four times, and the test below requires them to agree — which is what makes the ruling
#: above enforceable rather than advisory. A MUTATION established that it needed to be: replacing
#: FORBIDDEN_ROOTS with `{"PRIVATE_A", "PRIVATE_B"}` passed the entire suite, so the exact failure
#: the ruling describes — a sanitised gate that can no longer fail — was itself ungated. The
#: comment was right and unenforced, which is the shape this repository treats as a defect.
PROSE_SITES = ("packages/cdm/synapse_cdm/__init__.py",
               "packages/cdm/synapse_cdm/README.md")

#: The roots those sites name, as a backticked directory list. A SUBSET check, not equality: the
#: gate legitimately guards more than the prose names — `synapse_data` is the importable spelling
#: of `synapse-data`, and `verification` and `scripts` are guarded without being advertised.
PROSE_ROOTS = ("agents", "core", "platform", "synapse-data", "airtasking")

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


def test_the_forbidden_roots_are_the_real_ones_and_every_site_agrees():
    """THE RULING, MADE ENFORCEABLE — see the block above FORBIDDEN_ROOTS for why the names stay.

    This gate is a NEGATIVE test: "no module imports any of these". Any name the core does not use
    satisfies it forever, so sanitising the list would leave a check that passes while enforcing
    nothing, and the independence `README.md` advertises would rest on a test that cannot fail.
    A mutation proved the risk was live: `{"PRIVATE_A", "PRIVATE_B"}` passed the whole suite.

    So the names are pinned against the two prose sites that also carry them. Sanitise the gate
    and the sites disagree; sanitise all three and the disagreement moves to a place a reader
    of the README will meet. That is the disjunction treatment, applied to a fact that had been
    stated four times and checked at none of them.
    """
    for rel in PROSE_SITES:
        text = (REPO / rel).read_text()
        missing = [r for r in PROSE_ROOTS if f"`{r}/`" not in text]
        assert not missing, (
            f"{rel} no longer names {missing} as part of the product repository. Those names are "
            "what FORBIDDEN_ROOTS enforces against; if the core was restructured, update both "
            "the prose and the gate — do not drop either"
        )
    missing = [r for r in PROSE_ROOTS if r not in FORBIDDEN_ROOTS]
    assert not missing, (
        f"FORBIDDEN_ROOTS does not guard {missing}, which the prose sites name as top-level "
        "packages of the product repository. A root advertised as forbidden and not in this set "
        "is an import nothing stops"
    )
    # AND THE ABSENCE THE MUTATION FOUND: the set must not have been replaced by placeholders.
    assert not any(r.upper() == r and "_" in r for r in FORBIDDEN_ROOTS), (
        f"FORBIDDEN_ROOTS contains what looks like a placeholder: {sorted(FORBIDDEN_ROOTS)}. "
        "Sanitised names make this gate unfailable, which is a worse exposure than the five "
        "directory names it was hiding — the ruling above is explicit about that trade"
    )
