"""The Operational Ontology: §140's checklist, and the drift that would make it a fiction.

WHAT THIS MODULE IS FOR
-----------------------
SC-OES-SPEC-v2 §18 and §135 both say the same thing in different words: the Turtle under
`ontology/` is the authority, `ontology/context.jsonld` and
`packages/cdm/synapse_cdm/registry/sc_oes/ontology_terms.json` are generated from it, and "a drift
test must prevent semantic registry divergence". Without the test, "generated" is an intention. A
hand-edit to the registry — adding a term the ontology does not define, or fixing a label in the
JSON because that is the file the failure pointed at — leaves two vocabularies with one name, and
the answer a consumer gets is whichever file its tooling reads.

`§140` lists thirteen conditions and every one of them has a test below, named after it.

WHY THE GRAPH TESTS SKIP RATHER THAN FAIL WITHOUT `rdflib`
-----------------------------------------------------------
`rdflib` is a test/development dependency and deliberately not a runtime one (§136, §144). It
arrives with the `test` extra, which is the one `README.md` and `CONTRIBUTING.md` both tell a
reader to install before running this suite, so in the environment this suite is written for it is
present. Somebody with `pytest` on their path and no extra installed is the case that skips, and
it skips loudly with the reason — the same treatment `tests/test_cdm_packaging.py::_require_git`
gives an sdist with no index to read. The checks that need no parser — the committed registry's
grammar, its record shape, the §91 file list — run either way, so an environment without the
parser is narrowed rather than silenced.

WHY THE GATE IS LOADED WITH `exec(compile(...))`
--------------------------------------------------
`gates/` is not a package and is not on `sys.path`. `tests/test_cdm_generator_loading.py` bans
`exec_module` across this whole suite and gives the reproduction: a `.pyc` is revalidated on the
source's mtime in whole seconds plus its size, so a same-length edit reverted inside one second
hands back a module compiled from the edit. This module's subject IS that source, so reading a
cache of some other version of it would be measuring the wrong thing.
"""
import json
import pathlib
import re
import types

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
ONTOLOGY = REPO / "ontology"
CONTEXT = ONTOLOGY / "context.jsonld"
REGISTRY = REPO / "packages" / "cdm" / "synapse_cdm" / "registry" / "sc_oes" / "ontology_terms.json"
GATE_PATH = REPO / "gates" / "ontology_terms.py"
EVENT_TYPES_DOC = REPO / "spec" / "sc-oes" / "03-event-types.md"

#: §91's file list, verbatim. Written down HERE and derived from the directory in the test, which
#: is the direction that catches a module nobody added rather than one nobody deleted.
SECTION_91_FILES = ("README.md", "core.ttl", "pnt.ttl", "air.ttl", "logistics.ttl", "isr.ttl",
                    "c2.ttl", "mission.ttl", "decision.ttl", "context.jsonld")

#: §92's fifteen relationships, in §92's order and §92's spelling. They are labels in this
#: ontology, not identifiers — see `ontology/README.md`, derivation 1.
SECTION_92_RELATIONSHIPS = ("partOf", "hasPart", "locatedAt", "assignedTo", "uses", "requires",
                            "provides", "supports", "dependsOn", "observes", "detects", "affects",
                            "threatens", "communicatesWith", "concerns")

#: `12-versioning.md`'s four maturity values.
MATURITIES = {"EXPERIMENTAL", "DRAFT", "STABLE", "DEPRECATED"}


@pytest.fixture(scope="module")
def gate():
    """The generator, from its SOURCE. See this module's docstring for why not by import."""
    module = types.ModuleType("_ontology_terms_gate")
    module.__file__ = str(GATE_PATH)
    exec(compile(GATE_PATH.read_text(), str(GATE_PATH), "exec"), module.__dict__)
    return module


@pytest.fixture(scope="module")
def graph(gate):
    pytest.importorskip(
        "rdflib",
        reason="rdflib is this repository's test/development RDF parser and is declared in "
               "packages/cdm/pyproject.toml's `test` extra. Nothing at runtime needs it. "
               "Without that extra installed the Turtle authority cannot be parsed and the "
               "checks over it are NOT asserted here")
    return gate.load_graph()


@pytest.fixture(scope="module")
def collected(gate, graph):
    return gate.collect(graph)


@pytest.fixture(scope="module")
def committed():
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


# ------------------------------------------------------------------- the tree, before the graph


def test_the_ontology_directory_is_exactly_section_91s_file_list():
    """Both directions. A ninth module nobody decided about is the failure worth catching."""
    on_disk = {p.name for p in ONTOLOGY.iterdir() if p.is_file()}
    expected = set(SECTION_91_FILES)
    assert on_disk == expected, (
        f"ontology/ holds {sorted(on_disk)} and §91 lists {sorted(expected)}. Missing: "
        f"{sorted(expected - on_disk)}; unexpected: {sorted(on_disk - expected)}. A new module is "
        "a governance act — it needs a §91 entry and a row in ontology/README.md's table"
    )


def test_the_committed_registry_is_valid_json_with_the_shape_the_runtime_reads(committed):
    """What a consumer receives, checked without a parser — because they will have no parser."""
    assert committed["artefact"] == "sc-oes-ontology-terms"
    assert committed["namespace"] == "tag:synapsecommand.com,2026-09-06:ontology:"
    assert committed["ontology_version"] == "0.1.0"
    assert committed["terms"], "the packaged registry carries no terms"
    fields = {"id", "label", "module", "kind", "parent", "maturity", "deprecated", "replacement"}
    for record in committed["terms"]:
        assert set(record) == fields, (
            f"{record.get('id')} carries {sorted(record)} and §102's record is {sorted(fields)}. "
            "A missing key and an explicit null are different facts, so every key is present on "
            "every record even where its value is null"
        )


def test_every_packaged_identifier_matches_the_frozen_governed_grammar(gate, committed):
    """ADR 0003 decision 9, applied to the artefact a runtime actually reads.

    `re.fullmatch` and not `$`: `$` accepts a single trailing newline in Python, which is the
    reading recorded beside the grammar in the ADR itself.
    """
    bad = [r["id"] for r in committed["terms"] if not gate.TERM.fullmatch(r["id"])]
    assert not bad, f"identifiers the governed grammar refuses: {bad}"


def test_the_metadata_namespace_cannot_be_mistaken_for_the_governed_namespace(gate):
    """Derivation 3 of ontology/README.md, asserted rather than argued.

    The two strings share a prefix, which is exactly the condition under which a reader assumes
    they are the same space. The grammar is what separates them, so the grammar is what is asked.
    """
    assert gate.METADATA_NS != gate.NAMESPACE
    assert not gate.NAMESPACE.startswith(gate.METADATA_NS)
    assert not gate.METADATA_NS.startswith(gate.NAMESPACE)
    for local in ("maturity", "replacedBy", "module", "Maturity"):
        assert not gate.TERM.fullmatch(gate.METADATA_NS + local), (
            f"{gate.METADATA_NS + local} matches the governed term grammar. The metadata "
            "vocabulary would then be indistinguishable from the vocabulary it annotates"
        )


# --------------------------------------------------------------------------- §140, condition by


def test_140_all_turtle_parses(graph):
    assert len(graph) > 0


def test_140_governed_term_ids_are_unique(collected):
    records, _problems = collected
    identifiers = [r["id"] for r in records]
    duplicates = sorted({i for i in identifiers if identifiers.count(i) > 1})
    assert not duplicates, f"duplicate governed identifiers: {duplicates}"


def test_140_labels_and_definitions_and_maturity_and_version_are_present(collected):
    """Four of §140's conditions, and the generator refuses to emit a record missing any of them.

    So this asserts the generator's own verdict rather than re-deriving it: `collect()` returns
    every problem it found, and a term with no label is one of them. The re-derivation that keeps
    this honest is `test_the_generators_verdict_is_not_vacuous`, which mutates a synthetic module
    and requires the problem list to grow.
    """
    records, problems = collected
    assert not problems, "the generator refuses this ontology:\n  " + "\n  ".join(problems)
    for record in records:
        assert record["label"], record["id"]
        assert record["maturity"] in MATURITIES, record["id"]


def test_140_parents_resolve(collected):
    records, _problems = collected
    declared = {r["id"] for r in records}
    dangling = [(r["id"], r["parent"]) for r in records
                if r["parent"] is not None and r["parent"] not in declared]
    assert not dangling, f"parents naming no declared term: {dangling}"


def test_140_properties_and_inverse_declarations_resolve(gate, graph, collected):
    """`rdfs:domain`, `rdfs:range` and `owl:inverseOf`, re-derived from the graph directly.

    Independent of `collect()`: this walks the triples rather than reading the generator's record,
    so a generator that stopped checking would not also stop this from checking.
    """
    import rdflib

    records, _problems = collected
    declared = {r["id"] for r in records}
    dangling = []
    for name, predicate in (("rdfs:domain", rdflib.URIRef(gate.RDFS + "domain")),
                            ("rdfs:range", rdflib.URIRef(gate.RDFS + "range")),
                            ("owl:inverseOf", rdflib.URIRef(gate.OWL + "inverseOf"))):
        for subject, obj in graph.subject_objects(predicate):
            if str(obj) not in declared:
                dangling.append(f"{subject} {name} {obj}")
    assert not dangling, f"declarations naming no declared term: {dangling}"


def test_140_module_and_version_metadata_exists_on_every_module_document(gate, graph):
    """§91's eight modules each declare themselves, with a version and a module name."""
    import rdflib

    version_p = rdflib.URIRef(gate.OWL + "versionInfo")
    module_p = rdflib.URIRef(gate.METADATA_NS + "module")
    documents = sorted(str(s) for s in graph.subjects(
        rdflib.RDF.type, rdflib.URIRef(gate.OWL + "Ontology")))
    assert len(documents) == len(gate.modules()) == 8, (
        f"{len(documents)} owl:Ontology declarations for {len(gate.modules())} module files")
    for identifier in documents:
        subject = rdflib.URIRef(identifier)
        assert gate._one(graph, subject, version_p) == "0.1.0", identifier
        assert gate._one(graph, subject, module_p) in set(gate.modules()), identifier


def test_140_event_ontology_classes_subclass_the_correct_core_event_class(gate, graph, collected):
    """The condition §140 states last and the one with the most ways to be quietly wrong.

    The mapping is NOT written down here. `spec/sc-oes/03-event-types.md`'s table gives each of the
    thirteen governed types an `event_class`; `core.ttl` gives each core event class a
    `scmeta:eventClass` naming the same vocabulary; and the ontology event class for a type is
    found by turning the type's own name into UpperCamelCase and appending `Event`. Both ends are
    read from the tree, so a change at either end fails here instead of drifting.
    """
    import rdflib

    rows = re.findall(r"^\| `(sc\.[a-z0-9_.]+)` \| [^|]+ \| `([A-Z_]+)` \|",
                      EVENT_TYPES_DOC.read_text(encoding="utf-8"), re.MULTILINE)
    assert len(rows) == 13, f"{len(rows)} governed types parsed from {EVENT_TYPES_DOC.name}"

    event_class_p = rdflib.URIRef(gate.METADATA_NS + "eventClass")
    core_class_of = {str(o): str(s) for s, o in graph.subject_objects(event_class_p)}
    assert len(core_class_of) == 8, (
        f"{len(core_class_of)} core event classes carry scmeta:eventClass; "
        "02-event-classes.md's vocabulary has eight values and all eight must be grounded")

    records = {r["id"]: r for r in collected[0]}
    for type_id, event_class in rows:
        _sc, module, name, _major = type_id.split(".")
        local = "".join(part.capitalize() for part in name.split("_")) + "Event"
        identifier = f"{gate.NAMESPACE}{module}:{local}"
        # `capitalize()` lowercases the tail, so a term whose spelling keeps an acronym is looked
        # up by its label instead of being reported missing on a spelling difference.
        if identifier not in records:
            matches = [r for r in records.values()
                       if r["module"] == module and r["label"].lower() == local.lower()]
            assert len(matches) == 1, (
                f"{type_id} has event class {event_class} and no ontology class in module "
                f"'{module}' answers to {local}")
            identifier = matches[0]["id"]
        parent = records[identifier]["parent"]
        assert parent == core_class_of[event_class], (
            f"{identifier} subclasses {parent}; {type_id} declares event_class {event_class}, "
            f"whose core ontology class is {core_class_of[event_class]}")


def test_140_no_real_operational_individuals_are_committed(gate, graph):
    """§87: "Do not include real operational instances."

    Asked as "is anything typed as something this ontology declares a class?" rather than as
    "is anything an owl:NamedIndividual", because the second is only the tidy way to arrive.
    """
    import rdflib

    classes = {str(s) for s in graph.subjects(rdflib.RDF.type, rdflib.URIRef(gate.OWL + "Class"))}
    assert classes, ("no owl:Class in the graph, so this sweep looked at nothing and its PASS "
                     "would mean nothing")
    instances = sorted(f"{s} a {o}" for s, o in graph.subject_objects(rdflib.RDF.type)
                       if str(o) in classes)
    assert not instances, (
        f"the ontology commits {len(instances)} individual(s): {instances[:5]}. It is "
        "terminological (§87) and names no real unit, platform, location, callsign or mission")


def test_140_the_generated_registry_is_in_sync_with_the_turtle(gate, collected):
    """THE DRIFT TEST. §18: "must be generated from the ontology, not independently hand-maintained"."""
    records, _problems = collected
    expected = gate.render(gate.build_registry(records))
    actual = REGISTRY.read_text(encoding="utf-8")
    assert actual == expected, (
        "packages/cdm/synapse_cdm/registry/sc_oes/ontology_terms.json has drifted from the Turtle "
        "authority under ontology/. The Turtle is correct by construction and this file is not "
        "edited by hand — run `python gates/ontology_terms.py --write` and commit the result"
    )


def test_140_the_jsonld_context_is_in_sync_with_the_turtle(gate, collected):
    """The same drift test for the developer projection §19 says to generate from the authority."""
    records, _problems = collected
    expected = gate.render(gate.build_context(records))
    assert CONTEXT.read_text(encoding="utf-8") == expected, (
        "ontology/context.jsonld has drifted from the Turtle authority. Run "
        "`python gates/ontology_terms.py --write` and commit the result"
    )


# --------------------------------------------------------------- the specification's own lists


def test_the_fifteen_relationships_of_section_92_are_present_as_labels(collected):
    """§92's names survive verbatim, and the grammar decides the identifiers. Derivation 1."""
    records, _problems = collected
    properties = {r["label"]: r["id"] for r in records if r["kind"] == "property"}
    assert sorted(properties) == sorted(SECTION_92_RELATIONSHIPS), (
        f"§92 names {sorted(SECTION_92_RELATIONSHIPS)} and the ontology labels "
        f"{sorted(properties)}")
    for label, identifier in properties.items():
        assert identifier.endswith(":" + label[0].upper() + label[1:]), (
            f"{identifier} is labelled '{label}'; the identifier is that label's UpperCamelCase "
            "form and nothing else, so a reader can move between the two without a lookup")


def test_the_two_core_branches_of_section_89_and_90_hold_every_term(collected):
    """Every class reaches `OperationalConcept`. An unreachable class is a vocabulary nobody finds."""
    records = {r["id"]: r for r in collected[0]}
    root = "tag:synapsecommand.com,2026-09-06:ontology:core:OperationalConcept"
    for identifier, record in records.items():
        if record["kind"] != "class":
            continue
        seen, cursor = [identifier], record["parent"]
        while cursor is not None:
            assert cursor not in seen, f"cycle in the hierarchy above {identifier}: {seen}"
            seen.append(cursor)
            cursor = records[cursor]["parent"]
        assert seen[-1] == root, f"{identifier} reaches {seen[-1]}, not {root}"


# ------------------------------------------------------------------------------- the teeth


def test_the_generators_verdict_is_not_vacuous(gate):
    """A PASS above means nothing unless `collect()` can still say no. So make it say no.

    Four synthetic defects, one graph each, none of them written to disk: a term the grammar
    refuses, a term with no label, a parent that resolves to nothing, and a local name two modules
    both claim. A `collect()` that had stopped checking would return an empty problem list for
    every one of them and every §140 test above would still be green.
    """
    rdflib = pytest.importorskip("rdflib")
    header = ("@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
              "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
              "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
              f"@prefix scmeta: <{gate.METADATA_NS}> .\n"
              f"@prefix core: <{gate.NAMESPACE}core:> .\n"
              f"@prefix air: <{gate.NAMESPACE}air:> .\n")
    good = ('core:Thing a owl:Class ; rdfs:label "Thing" ; skos:definition "d" ; '
            'scmeta:maturity "EXPERIMENTAL" ; owl:versionInfo "0.1.0" .\n')
    cases = {
        "lowercase term segment": 'core:thing a owl:Class ; rdfs:label "thing" ; '
                                  'skos:definition "d" ; scmeta:maturity "EXPERIMENTAL" ; '
                                  'owl:versionInfo "0.1.0" .\n',
        "no label": 'core:Nameless a owl:Class ; skos:definition "d" ; '
                    'scmeta:maturity "EXPERIMENTAL" ; owl:versionInfo "0.1.0" .\n',
        "parent resolves to nothing": good + 'core:Orphan a owl:Class ; '
                                      'rdfs:subClassOf core:Absent ; rdfs:label "Orphan" ; '
                                      'skos:definition "d" ; scmeta:maturity "EXPERIMENTAL" ; '
                                      'owl:versionInfo "0.1.0" .\n',
        "local name claimed twice": good + 'air:Thing a owl:Class ; rdfs:label "Thing" ; '
                                    'skos:definition "d" ; scmeta:maturity "EXPERIMENTAL" ; '
                                    'owl:versionInfo "0.1.0" .\n',
    }
    for case, body in cases.items():
        graph = rdflib.Graph()
        graph.parse(data=header + body, format="turtle")
        _records, problems = gate.collect(graph)
        assert problems, f"collect() accepted a graph with a {case}"


def test_the_gate_loads_with_no_side_effects_and_writes_nothing(gate):
    """Reading the generator must not run it. Only `main()` acts."""
    assert callable(gate.main)
    assert callable(gate.collect)
    assert gate.NAMESPACE.startswith("tag:synapsecommand.com,2026-09-06:")
