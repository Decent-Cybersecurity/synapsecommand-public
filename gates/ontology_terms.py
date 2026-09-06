"""Both derived ontology artefacts, generated from the Turtle authority and diffed against disk.

WHY A GENERATOR AND NOT TWO HAND-WRITTEN FILES
----------------------------------------------
The SC-OES Operational Ontology has one authority — `ontology/*.ttl` — and two derived
publications: `ontology/context.jsonld`, the developer projection, and
`packages/cdm/synapse_cdm/registry/sc_oes/ontology_terms.json`, the artefact the runtime actually
reads. SC-OES-SPEC-v2 §18 rules out the cheap arrangement in as many words: the registry "must be
**generated from the ontology**, not independently hand-maintained", and "a drift test must prove
the generated registry matches the Turtle authority". §135 says the same of both derived files.

The failure that rule is written against is quiet. Two hand-authored files stating one vocabulary
give two answers to "is this term governed?" the first time one of them is edited alone, and the
answer a consumer gets is whichever file their tooling happens to read. This repository has the
same mechanism one layer over — `python -m synapse_cdm.schemas --check` fails the build when the
published schemas differ from the models — and this is that pattern applied to a second generated
publication rather than a new idea.

WHY THE RDF PARSER IS IMPORTED INSIDE A FUNCTION
------------------------------------------------
`rdflib` is a TEST/DEVELOPMENT dependency and nothing else (§136, ADR 0002 decision 6, ADR 0010
decision 5). Nothing in `synapse_cdm` imports it, nothing in the wheel needs it, and the runtime
never parses Turtle — §102 is the binding sentence and §144's dependency budget is the check.
Importing it at module scope here would make this file unimportable without it, and this file is
loaded by the suite to be inspected as well as to be run. So the import sits inside
`load_graph()`: the module imports anywhere, and only the act of parsing Turtle needs the parser.

WHAT THIS GATE VALIDATES, AND WHY IT IS HERE RATHER THAN ONLY IN THE SUITE
--------------------------------------------------------------------------
`verify()` refuses to emit a record it cannot derive honestly — a term with no label, a parent
that resolves to nothing, an identifier the frozen grammar refuses, a local name two modules both
claim. A generator that emitted those and left the suite to notice would be writing a file that
is wrong on disk between the two runs, and `--check` would then be comparing one wrong answer
against another. `tests/test_cdm_ontology.py` re-derives §140's list against the graph
independently; this is the half that must hold before anything is written.
"""
import argparse
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
ONTOLOGY = REPO / "ontology"
CONTEXT = ONTOLOGY / "context.jsonld"
REGISTRY = REPO / "packages" / "cdm" / "synapse_cdm" / "registry" / "sc_oes" / "ontology_terms.json"

#: The governed ontology namespace, frozen by ADR 0003 decision 9 and restated in
#: `spec/sc-oes/09-entity-semantics.md`. The authority date is fixed for the lifetime of the v0.1
#: namespace and is never derived from a clock.
NAMESPACE = "tag:synapsecommand.com,2026-09-06:ontology:"

#: The metadata vocabulary this ontology carries maturity and deprecation in. §88 permits
#: "maturity metadata" and "deprecation metadata" without naming a vocabulary, and no standard one
#: has a maturity property. It is a DIFFERENT namespace from the governed term namespace and
#: provably so: the governed grammar requires the literal segment `ontology:` after the date, and
#: this one is `ontology-metadata:`. So a metadata property can never be mistaken for a term.
METADATA_NS = "tag:synapsecommand.com,2026-09-06:ontology-metadata:"

#: The one production a governed term identifier must match. `re.fullmatch` rather than `$`,
#: because `$` in Python accepts a single trailing newline and would admit an identifier with
#: whitespace on the end — the reading ADR 0003 decision 9 records beside the grammar.
TERM = re.compile(r"tag:synapsecommand\.com,2026-09-06:ontology:[a-z][a-z0-9_]*:[A-Z][A-Za-z0-9]*")

#: The module document IRI: the namespace with the module name and NO term segment. It is not a
#: governed term — it names the file, not a concept — and the closure below is what says so out
#: loud rather than leaving a reader to notice that it does not match `TERM`.
MODULE_IRI = re.compile(r"tag:synapsecommand\.com,2026-09-06:ontology:([a-z][a-z0-9_]*)")

OWL = "http://www.w3.org/2002/07/owl#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
SKOS = "http://www.w3.org/2004/02/skos/core#"


class Failed(Exception):
    """A condition under which no artefact may be written."""


def modules() -> list[str]:
    """The module names, READ from the directory rather than written down here.

    A roster typed into a gate is the defect `gates/wheel_install.py` was caught by twice: two
    adapters shipped, the tuple did not grow, and one of its checks reported a PASS over the
    subset it happened to know about. There is nothing to keep a list here in step with the
    directory, so there is no list.
    """
    return sorted(p.stem for p in ONTOLOGY.glob("*.ttl"))


def load_graph():
    """Every module parsed into one graph. The parser is imported here and nowhere else."""
    try:
        import rdflib                                        # noqa: PLC0415 — see the docstring
    except ImportError as exc:                               # pragma: no cover - environment
        raise Failed(
            "rdflib is not importable. It is this repository's test/development RDF parser and is "
            "declared in packages/cdm/pyproject.toml's `test` extra; nothing at runtime needs it. "
            "Install that extra and run this again"
        ) from exc
    graph = rdflib.Graph()
    found = sorted(ONTOLOGY.glob("*.ttl"))
    if not found:
        raise Failed(f"no Turtle module under {ONTOLOGY.relative_to(REPO)}; nothing to generate "
                     "from, and a generator that writes an empty registry from an empty directory "
                     "would report success over a deleted ontology")
    for path in found:
        graph.parse(path, format="turtle")
    return graph


def _one(graph, subject, predicate):
    values = list(graph.objects(subject, predicate))
    return str(values[0]) if len(values) == 1 else None


def _split(identifier: str) -> tuple[str, str]:
    """`(module, local)` of a governed term identifier. Assumes it already matched `TERM`."""
    module, local = identifier[len(NAMESPACE):].split(":", 1)
    return module, local


def collect(graph) -> tuple[list[dict], list[str]]:
    """Every governed term as a §102 record, and every reason a record could not be trusted.

    Both halves come back together on purpose. A collector that raised on the first problem would
    report one defect per run over an ontology with six, and the person fixing them would learn
    about them one commit at a time.
    """
    import rdflib                                            # noqa: PLC0415 — see the docstring

    problems: list[str] = []
    records: list[dict] = []
    declared: set[str] = set()

    kinds = {rdflib.URIRef(OWL + "Class"): "class",
             rdflib.URIRef(OWL + "ObjectProperty"): "property"}
    label_p = rdflib.URIRef(RDFS + "label")
    definition_p = rdflib.URIRef(SKOS + "definition")
    version_p = rdflib.URIRef(OWL + "versionInfo")
    maturity_p = rdflib.URIRef(METADATA_NS + "maturity")
    deprecated_p = rdflib.URIRef(OWL + "deprecated")
    replaced_p = rdflib.URIRef(METADATA_NS + "replacedBy")
    subclass_p = rdflib.URIRef(RDFS + "subClassOf")
    subproperty_p = rdflib.URIRef(RDFS + "subPropertyOf")

    typed: dict[str, str] = {}
    for rdf_type, kind in kinds.items():
        for subject in graph.subjects(rdflib.RDF.type, rdf_type):
            identifier = str(subject)
            if identifier in typed:
                problems.append(f"{identifier} is declared both a class and an object property")
            typed[identifier] = kind
            declared.add(identifier)

    # THE CLOSURE OVER THE NAMESPACE, and it is the half that catches a typo rather than a
    # deletion. Every subject that opens with the governed namespace is either a module document
    # IRI or a declared term; a fifth colon-separated segment that is lowercase, or a term nobody
    # gave a type to, lands here instead of quietly vanishing from the registry.
    known_modules = set(modules())
    for subject in set(graph.subjects()):
        identifier = str(subject)
        if not identifier.startswith(NAMESPACE):
            continue
        if identifier in typed:
            if not TERM.fullmatch(identifier):
                problems.append(f"{identifier} is a declared term and does not match the governed "
                                "grammar (ADR 0003 decision 9)")
            continue
        module_match = MODULE_IRI.fullmatch(identifier)
        if module_match and module_match.group(1) in known_modules:
            continue
        problems.append(f"{identifier} is in the governed namespace and is neither a declared "
                        "class or object property nor a module document IRI")

    for identifier, kind in sorted(typed.items()):
        subject = rdflib.URIRef(identifier)
        if not TERM.fullmatch(identifier):
            continue                                   # already reported by the closure above
        module, _local = _split(identifier)
        if module not in known_modules:
            problems.append(f"{identifier} names module '{module}', and the modules on disk are "
                            f"{sorted(known_modules)}")
        label = _one(graph, subject, label_p)
        definition = _one(graph, subject, definition_p)
        maturity = _one(graph, subject, maturity_p)
        version = _one(graph, subject, version_p)
        for name, value in (("rdfs:label", label), ("skos:definition", definition),
                            ("maturity", maturity), ("owl:versionInfo", version)):
            if value is None:
                problems.append(f"{identifier} carries no single {name}")
        parents = [str(o) for o in graph.objects(
            subject, subclass_p if kind == "class" else subproperty_p)]
        if len(parents) > 1:
            problems.append(f"{identifier} declares {len(parents)} parents: {sorted(parents)}. "
                            "The §102 record carries one, and choosing between them here would be "
                            "this generator inventing a hierarchy")
        deprecated_raw = list(graph.objects(subject, deprecated_p))
        replacement = _one(graph, subject, replaced_p)
        deprecated = bool(deprecated_raw and str(deprecated_raw[0]).lower() == "true")
        if replacement and not deprecated:
            problems.append(f"{identifier} names a replacement and is not deprecated")
        records.append({
            "id": identifier,
            "label": label,
            "module": module,
            "kind": kind,
            "parent": parents[0] if len(parents) == 1 else None,
            "maturity": maturity,
            "deprecated": deprecated,
            "replacement": replacement,
        })

    for record in records:
        parent = record["parent"]
        if parent is not None and parent not in declared:
            problems.append(f"{record['id']} has parent {parent}, which no module declares")

    # Every `rdfs:domain`, `rdfs:range` and `owl:inverseOf` object must be a term this ontology
    # declares. A dangling one is not a cosmetic defect: a consumer reading the Turtle would treat
    # the missing identifier as a class it has never heard of rather than as a typo.
    for predicate_name, predicate in (("rdfs:domain", rdflib.URIRef(RDFS + "domain")),
                                      ("rdfs:range", rdflib.URIRef(RDFS + "range")),
                                      ("owl:inverseOf", rdflib.URIRef(OWL + "inverseOf"))):
        for subject, obj in graph.subject_objects(predicate):
            if str(obj) not in declared:
                problems.append(f"{subject} declares {predicate_name} {obj}, which no module "
                                "declares")

    # §87: "Do not include real operational instances." An individual is how one would arrive.
    for subject in graph.subjects(rdflib.RDF.type, rdflib.URIRef(OWL + "NamedIndividual")):
        problems.append(f"{subject} is an owl:NamedIndividual. The ontology is terminological "
                        "(§87) and commits no instances")

    seen: dict[str, str] = {}
    for record in sorted(records, key=lambda r: r["id"]):
        _module, local = _split(record["id"])
        if local in seen:
            problems.append(f"the local name '{local}' is claimed by both {seen[local]} and "
                            f"{record['id']}; the JSON-LD context maps local names and one of "
                            "them would silently win")
        seen[local] = record["id"]

    records.sort(key=lambda r: r["id"])
    return records, sorted(set(problems))


def build_registry(records: list[dict]) -> dict:
    """§102's record set, plus the provenance a reader of the JSON alone would otherwise lack."""
    return {
        "artefact": "sc-oes-ontology-terms",
        "artefact_version": "1",
        "ontology_version": "0.1.0",
        "namespace": NAMESPACE,
        "generated_by": "gates/ontology_terms.py",
        "source_modules": modules(),
        "generated": "derived from the Turtle ontology; do not hand-edit",
        "terms": records,
    }


def build_context(records: list[dict]) -> dict:
    """The developer projection: prefixes, then every term by its local name.

    §19 fixes what this file is and is not — a developer convenience, "not required for ordinary
    CDM/SC-OES JSON validation", and runtime validation "must not require parsing it". Object
    properties are typed `@id` so that a value written against this context is read as an
    identifier rather than as a string, which is the one thing a context can get wrong here.
    """
    context: dict[str, object] = {name: f"{NAMESPACE}{name}:" for name in modules()}
    for record in records:
        _module, local = _split(record["id"])
        if record["kind"] == "property":
            context[local] = {"@id": record["id"], "@type": "@id"}
        else:
            context[local] = record["id"]
    return {"@context": context}


def render(document: dict) -> str:
    """One serialisation, used for writing AND for comparing, so `--check` cannot be fooled."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def generate() -> tuple[dict, dict, list[dict], list[str]]:
    graph = load_graph()
    records, problems = collect(graph)
    return build_registry(records), build_context(records), records, problems


def _write(path: pathlib.Path, text: str) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else None
    if existing == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="regenerate in memory and fail if either file on disk differs")
    parser.add_argument("--write", action="store_true",
                        help="write both derived artefacts")
    parser.add_argument("--json", action="store_true",
                        help="print the generated registry to stdout and exit")
    args = parser.parse_args(argv)

    try:
        registry, context, records, problems = generate()
    except Failed as exc:
        print(f"ontology_terms: {exc}")
        return 1

    if problems:
        print(f"ontology_terms: {len(problems)} problem(s); nothing written")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    if args.json:
        print(render(registry), end="")
        return 0

    wanted = {REGISTRY: render(registry), CONTEXT: render(context)}
    if args.write:
        changed = [p for p, text in wanted.items() if _write(p, text)]
        print(f"ontology_terms: {len(records)} terms, {len(modules())} modules, "
              f"{len(changed)} file(s) written, 0 failed")
        return 0

    stale = [p for p, text in wanted.items()
             if not p.exists() or p.read_text(encoding="utf-8") != text]
    if stale:
        print(f"ontology_terms: {len(stale)} derived artefact(s) differ from the ontology: "
              + ", ".join(str(p.relative_to(REPO)) for p in stale)
              + "\n  The Turtle under ontology/ is the authority. Run "
                "`python gates/ontology_terms.py --write` and commit the result")
        return 1
    print(f"ontology_terms: {len(records)} terms, {len(modules())} modules, "
          f"{len(wanted)} derived artefacts in sync, 0 failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
