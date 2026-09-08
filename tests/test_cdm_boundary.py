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
import re

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

#: THE ONE ALLOWANCE, AND IT IS A MODULE NAME AND A MODULE NAME ONLY — M's ruling, 2026-09-08.
#:
#: `synapse_cdm/evidence.py` computes SHA-256 over fixture files and build artefacts so that an
#: evidence record can say WHICH bytes a conformance run read. M ruled: "`hashlib` is permitted
#: only inside the evidence-generation module for non-cryptographic-security uses such as
#: deterministic SHA-256 content digests. Allowed uses: fixture hashes; artifact hashes;
#: evidence-record integrity identifiers; deterministic content addressing. Forbidden uses remain
#: unchanged: encryption; key derivation; authentication; signatures; MACs; password hashing;
#: random/token generation; any security protocol primitive."
#:
#: THE RULE ABOVE IS NOT WEAKENED, AND THIS IS WHY. The reason `FORBIDDEN_CRYPTO` exists is in
#: this module's own docstring and it is about SIGNING — "an import of `cryptography` or
#: `hashlib` here would mean somebody had started signing objects inside the translation layer,
#: where the key material has no business being and where nothing audits it". A content digest
#: carries no key, authenticates nobody and asserts nothing about who produced the bytes. It
#: answers "did this file change?", which is a question about identity and not about trust.
#:
#: SCOPED TO ONE NAME AND NOT TO A PATTERN, deliberately. `{"evidence.py"}` is a set of one; a
#: prefix rule (`evidence*`) or a marker comment would let the next module opt itself in, and an
#: allowance that a module can grant itself is not an allowance, it is the absence of a rule.
#: `test_the_crypto_allowance_is_one_named_module` below pins the size of this set, and the
#: parametrised test still fails for every other module in the package — proved by a mutation in
#: the round that added it: the same `import hashlib` in a second module reds this file.
#:
#: `hmac`, `cryptography`, `secrets`, `ssl`, `nacl` and `oqs` remain forbidden EVERYWHERE,
#: including in the allowed module: the allowance is one name on each side, not a door.
CRYPTO_ALLOWANCE: dict[str, set[str]] = {"evidence.py": {"hashlib"}}

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
    allowed = CRYPTO_ALLOWANCE.get(path.name, set())
    offending = _imported_roots(path) & FORBIDDEN_CRYPTO - allowed
    assert not offending, (
        f"{path.relative_to(ROOT)} imports {sorted(offending)} — the `integrity` field is "
        "designed, not implemented (models.Integrity). Signing belongs to the ledger, which "
        "holds the keys and is audited; a signature computed inside a translator is neither. "
        f"The one allowance is {sorted(CRYPTO_ALLOWANCE)}, for CONTENT DIGESTS and nothing "
        "else (see CRYPTO_ALLOWANCE above); widening it needs a ruling, not an edit"
    )


def test_the_crypto_allowance_is_one_named_module_and_one_named_import():
    """The allowance's SIZE is the gate, because a set is one edit away from being a hole.

    A parametrised test cannot notice that its own exemption list grew — it would simply stop
    failing — so the shape of `CRYPTO_ALLOWANCE` is asserted here rather than left to review.
    Adding a module or an import to it fails this test, which is where the ruling gets read.
    """
    assert set(CRYPTO_ALLOWANCE) == {"evidence.py"}, (
        f"the crypto allowance now covers {sorted(CRYPTO_ALLOWANCE)}. M's ruling of 2026-09-08 "
        "names ONE module — the evidence generator — and every widening is a security decision "
        "that belongs to a person"
    )
    assert CRYPTO_ALLOWANCE["evidence.py"] == {"hashlib"}, (
        f"evidence.py is allowed {sorted(CRYPTO_ALLOWANCE['evidence.py'])}. The ruling permits "
        "SHA-256 content digests; `hmac`, `cryptography`, `secrets` and `ssl` are what the "
        "forbidden uses are made of and none of them is allowed anywhere"
    )
    allowed_module = PACKAGE / "evidence.py"
    assert allowed_module.is_file(), (
        "the allowance names a module that does not exist. An exemption for a file nobody "
        "ships is an exemption nothing constrains"
    )
    assert "hashlib" in _imported_roots(allowed_module), (
        "evidence.py no longer imports hashlib, so the allowance guards nothing and should be "
        "removed rather than left as a standing exception"
    )


def test_every_other_module_is_still_refused_the_same_import():
    """The mutation, run as a test: `import hashlib` in a module that is not the allowed one.

    Written because the allowance above is the exact shape of change that silently disables a
    negative gate. This constructs the offending module in memory, runs the gate's own predicate
    over it, and requires the refusal — so the narrowing is proved to be a narrowing rather than
    a removal, on every run and not once in a round report.
    """
    other = next(p for p in SOURCES if p.name not in CRYPTO_ALLOWANCE and p.name != "__init__.py")
    allowed = CRYPTO_ALLOWANCE.get(other.name, set())
    mutated = _imported_roots(other) | {"hashlib"}
    assert mutated & FORBIDDEN_CRYPTO - allowed == {"hashlib"}, (
        f"a `import hashlib` added to {other.name} would not be caught. The allowance has "
        "stopped being scoped to one module"
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


# ==================================================================== §143 and §144
#
# THE SECOND HALF OF THE BOUNDARY, AND WHY IT ARRIVED THREE ROUNDS AFTER THE FIRST
# -------------------------------------------------------------------------------
# The two gates above are about the product this package was lifted out of, and about crypto.
# SC-OES added a semantic layer with its own gravity: an ontology invites an RDF reasoner, a
# governed registry invites a network client to fetch it, a conformance verdict invites a model
# to explain itself, and a "knowledge graph" invites a graph database. None of those would be an
# absurd thing for a developer to reach for; each of them would move the line this repository is
# drawn around, because each is a piece of the reasoning that is deliberately NOT published.
#
# `tests/test_cdm_conformance.py` already guards the conformance module's own import closure
# against the same names — it is the tool a consumer runs against content it did not write, so it
# earns a second, narrower gate. What was missing is the WIDE one: the same classes over every
# module in the package. The closure test at the bottom of this section keeps the two in step,
# because a fact stated in two places and compared in none is this repository's standard defect.
#
# The names are real for the reason FORBIDDEN_ROOTS's names are real: a negative test is satisfied
# vacuously by any name nobody would import, so a sanitised list is a gate that cannot fail.

#: §143's classes, by the reason each one would mean the line had moved. Beyond the private roots
#: and the crypto set above, which are the same section's first two classes.
FORBIDDEN_BY_CLASS: dict[str, frozenset[str]] = {
    "LLM frameworks and model SDKs": frozenset({
        "openai", "anthropic", "langchain", "langchain_core", "llama_index", "transformers",
        "torch", "tensorflow", "cohere", "mistralai", "ollama", "huggingface_hub"}),
    "graph databases": frozenset({
        "neo4j", "py2neo", "neomodel", "gremlin_python", "arango", "networkx"}),
    "message brokers": frozenset({
        "kafka", "confluent_kafka", "pika", "redis", "nats", "zmq", "celery", "paho"}),
    "RDF parsers and reasoners": frozenset({"rdflib", "owlrl", "pyshacl"}),
}

FORBIDDEN_RUNTIME = frozenset().union(*FORBIDDEN_BY_CLASS.values())


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_reasoning_infrastructure_in_the_contract_layer(path):
    """§143, over every module in the package rather than over the conformance closure alone."""
    reached = _imported_roots(path)
    for label, roots in sorted(FORBIDDEN_BY_CLASS.items()):
        offending = reached & roots
        assert not offending, (
            f"{path.relative_to(ROOT)} imports {sorted(offending)} — {label} belong to the "
            "SynapseCommand runtime and not to the contract layer. The ontology is "
            "TERMINOLOGICAL: it carries classes, labels and definitions, and the reasoning it "
            "would be written over is not published here"
        )


def test_the_ontology_is_read_by_the_runtime_as_data_and_never_parsed_as_turtle():
    """The concrete case the RDF row exists for, asserted on the artefact rather than the class.

    `rdflib` is a TEST dependency: the ontology's own tests read `ontology/*.ttl` with it. What
    the installed package reads is the GENERATED `registry/sc_oes/ontology_terms.json`, with
    `importlib.resources` — no network, no checkout, no RDF library. An import of `rdflib` under
    `synapse_cdm/` would mean the runtime had started parsing the authority, which is the one
    thing the derived artefact exists to make unnecessary.
    """
    importers = [p.relative_to(ROOT) for p in SOURCES if "rdflib" in _imported_roots(p)]
    assert not importers, f"{importers} import rdflib; the runtime reads the generated registry"


def test_the_wide_gate_guards_everything_the_conformance_closure_guards():
    """The two statements of one fact, compared — see the block at the top of this section.

    `test_cdm_conformance.py` guards the conformance module's closure against §125's network
    roots AND §143's classes. The network roots are that gate's own business; the §143 classes are
    this one's, and every one of them must be guarded here too. Otherwise a name could be dropped
    from the wide gate and the narrow one would keep passing, which is how a boundary shrinks
    without anybody deciding to shrink it.
    """
    from tests.test_cdm_conformance import FORBIDDEN_ROOTS as NARROW

    guarded = FORBIDDEN_RUNTIME | FORBIDDEN_CRYPTO | FORBIDDEN_ROOTS
    #: §125's network roots are the narrow gate's alone: reaching a network is a property of the
    #: TOOL a consumer runs, and the package legitimately holds none of these either way.
    network = {"socket", "ssl", "http", "urllib", "urllib2", "urllib3", "requests", "httpx",
               "aiohttp", "ftplib", "smtplib", "telnetlib", "webbrowser", "xmlrpc", "asyncio"}
    missing = sorted((NARROW - network) - guarded)
    assert not missing, (
        f"the conformance closure guards {missing} and this gate does not. The narrow gate covers "
        "one module; this one covers the package, so a name in the first and not the second is a "
        "class of import the rest of the package is free to make"
    )


def test_every_class_the_boundary_page_names_is_a_class_this_module_guards():
    """The rendered documentation and the gate, compared. The page makes the claim; this is it.

    `docs/docs/sc-oes/boundary.mdx` tabulates the classes and says the build fails on each. A page
    that claims a gate exists is exactly as good as the comparison between the two — this
    repository has repaired that shape often enough to write the check first.
    """
    page = (REPO / "docs" / "docs" / "sc-oes" / "boundary.mdx").read_text()
    assert page, "the boundary page is missing; this module's site list is stale"
    for phrase in ("private SynapseCommand code", "LLM frameworks and model SDKs",
                   "graph databases", "message brokers", "RDF reasoners",
                   "crypto implementations"):
        assert phrase in page, f"{phrase!r} is guarded here and the boundary page no longer names it"


# --------------------------------------------------------------- §144, the dependency budget


#: §144's list, spelled the way a `dependencies` entry would spell it. A runtime dependency on any
#: of them would make the public contract heavier than the thing it is a contract for.
BUDGET_FORBIDDEN = ("kafka", "confluent-kafka", "redis", "neo4j", "rdflib", "owlrl", "pyshacl",
                    "openai", "anthropic", "langchain", "transformers", "torch", "cryptography",
                    "pynacl", "requests", "httpx", "aiohttp")


def _pyproject() -> dict:
    import tomllib
    return tomllib.loads((REPO / "packages" / "cdm" / "pyproject.toml").read_text())


def test_the_runtime_dependencies_are_the_two_the_documents_promise():
    """`README.md`, the package README and the rendered site all say two. Here they are counted."""
    declared = _pyproject()["project"]["dependencies"]
    names = sorted(re.split(r"[<>=!~\[ ]", entry, maxsplit=1)[0].lower() for entry in declared)
    assert names == ["jsonschema", "pydantic"], (
        f"the distribution now declares {names} as RUNTIME dependencies. Two is a promise made in "
        "`README.md`, in the package README and on the documentation site; a third is a decision "
        "those three documents have to be told about"
    )


def test_no_forbidden_runtime_dependency_is_declared():
    """§144, read off the declaration rather than off the import graph.

    The import gates above catch a module that reaches for one of these. This catches the other
    order — a dependency declared and not yet imported — which is what an abandoned experiment
    looks like in a `pyproject.toml`, and which a `pip install` still pays for.
    """
    declared = " ".join(_pyproject()["project"]["dependencies"]).lower()
    offending = [name for name in BUDGET_FORBIDDEN if name in declared]
    assert not offending, f"the distribution declares {offending} at RUNTIME; §144 forbids each"


def test_the_rdf_parser_is_declared_in_the_test_extra_and_only_there():
    """The one place `rdflib` is allowed to be, stated as a positive so it cannot drift upward."""
    project = _pyproject()["project"]
    extras = project["optional-dependencies"]
    assert sorted(extras) == ["test"], f"unexpected extras: {sorted(extras)}"
    test_extra = " ".join(extras["test"]).lower()
    assert "rdflib" in test_extra, "rdflib left the test extra; the ontology's graph tests need it"
    assert "rdflib" not in " ".join(project["dependencies"]).lower()


def test_the_import_walk_sees_third_party_imports_at_all():
    """A negative test that cannot fail is worse than none, so this one proves the walk works."""
    assert "pydantic" in _imported_roots(PACKAGE / "models.py")
    assert FORBIDDEN_RUNTIME & {"rdflib"}
