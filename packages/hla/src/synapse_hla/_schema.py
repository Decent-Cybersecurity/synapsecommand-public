"""Schema validation with one deterministic first error and a precise JSON Pointer for it.

A refusal has to name one error, the same one on every run and every interpreter (OPS-06: "the
first error chosen deterministically (document order of the pointer, then schema keyword)").
jsonschema reports every error it finds, some of them at a place that is not where the input is
wrong, so three of them are made precise before the choice:

- `required` is reported at the object that lacks the member; here it points at the missing
  member itself (`/synthetic`), which is the place the input has to change.
- `additionalProperties` is reported at the object too; here it points at the first member, in
  the object's order, that is not allowed (`/extra`).
- `oneOf` over branches that each fix one member with `const` (the two time policies, the six
  event types) is reported as "no branch matched" with every branch's complaints inside it. The
  branch the input chose by that member is the one it meant, so its complaints are the ones
  reported (`/time_policy/basis` rather than `/time_policy`); with no branch chosen, the
  discriminating member itself is the error (`/time_policy/mode`, `/event/type`).

Then the earliest pointer in document order wins: members in the order the document has them,
a parent before its children, a missing member after every present one (by name), and the schema
keyword's name breaks a tie.

No format checker is attached to the validators that refuse input. `format: date-time` is a
no-op in the installed jsonschema and would become a check if another package were installed;
the profile's dates are checked by explicit code (`_utc`) instead, so a refusal never depends on
what else is installed (OPS-03).

The product's own output is a different matter. R44 asks for every Entity to be validated
against the CDM schema WITH format checking, and the provenance block is held to its schema the
same way: `checked_validator` and `entity_validator` attach the format checker (which asserts
`uuid`, the one format those documents carry that the installed jsonschema checks). They never
judge input; a failure there is a defect of the producer. The Entity schema is the SDK's
publication, written with ECMA-262 anchors (`^...$`, where Python's `$` also matches before a
final newline), so it is validated the way the SDK validates its published schemas,
through `synapse_cdm.schemas.validator_for`.

What "integer" means. Draft 2020-12 counts a number with a zero fraction as an integer, and so
does jsonschema: 5.0 passes `"type": "integer"`. The canonical writer keeps it a float and spells
it `5.0`. A capture line never holds a float (the strict reader refuses the token) and the
configuration has no integer member, so the validators that judge those keep the draft's
reading. Values built in memory are another matter: the projector's arguments are Python values,
and a 5.0 among them would reach the output as `5.0` where the same state with 5 writes `5`, two
byte streams for one state (R35). So `first_problem(..., exact_integers=True)`, which the
projector uses on its snapshot, and `checked_validator`, which holds the product's own output,
read "integer" as exactly a Python int (a bool is no more an integer than the draft says).
"""

from __future__ import annotations

import functools
import re
from typing import NamedTuple

from jsonschema import Draft202012Validator, FormatChecker, validators
from referencing import Registry, Resource
from synapse_cdm.schemas import validator_for

from synapse_hla import _resources

#: The packaged copy of the CDM Entity schema 3.0.0 (R44), from the handoff's baseline
#: synapse-cdm 3.1.1: history, kept as the contract; the package's floor is 3.8.0 (D-28).
ENTITY_SCHEMA = "cdm-entity.schema.json"


class SchemaProblem(NamedTuple):
    """One schema error: pointer tokens from the root, and the keyword that failed."""

    tokens: tuple
    keyword: str


@functools.lru_cache(maxsize=None)
def _registry_and_schemas() -> tuple[Registry, dict]:
    registry = Registry()
    found = {}
    for directory in (_resources.SCHEMA_DIR, _resources.LOCAL_SCHEMA_DIR):
        for name in _resources.schema_names(directory):
            schema = _resources.package_json(directory, name)
            resource = Resource.from_contents(schema)
            registry = registry.with_resource(name, resource)
            registry = registry.with_resource(schema["$id"], resource)
            found[name] = schema
    return registry, found


def _exact_integer(_checker, instance) -> bool:
    return type(instance) is int


#: Draft 2020-12 with "integer" read as exactly a Python int (see the module text).
ExactIntegerValidator = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine("integer", _exact_integer))


@functools.lru_cache(maxsize=None)
def validator(name: str, *, exact_integers: bool = False):
    """The Draft 2020-12 validator of one packaged schema, its `$ref`s resolved in the package;
    with `exact_integers`, an integral float is not an integer (see the module text)."""
    registry, found = _registry_and_schemas()
    kind = ExactIntegerValidator if exact_integers else Draft202012Validator
    return kind(found[name], registry=registry)


@functools.lru_cache(maxsize=None)
def checked_validator(name: str):
    """The validator of one packaged schema with the format checker on and integers exact, for
    the product's own output (see the module text); never for a refusal."""
    registry, found = _registry_and_schemas()
    return ExactIntegerValidator(found[name], registry=registry, format_checker=FormatChecker())


@functools.lru_cache(maxsize=None)
def entity_validator():
    """The packaged CDM Entity schema as the SDK validates its published schemas: Draft 2020-12,
    ECMA-262 `pattern` anchors and `format` asserted."""
    _, found = _registry_and_schemas()
    return validator_for(found[ENTITY_SCHEMA])


def _same(a, b) -> bool:
    return type(a) is type(b) and a == b


def _refined(error):
    tokens = tuple(error.absolute_path)
    keyword = error.validator
    instance = error.instance
    if keyword == "required" and type(instance) is dict:
        for name in error.validator_value:
            if name not in instance:
                yield SchemaProblem(tokens + (name,), keyword)
        return
    if keyword == "additionalProperties" and error.validator_value is False \
            and type(instance) is dict:
        declared = error.schema.get("properties", {})
        patterns = error.schema.get("patternProperties", {})
        # Only the first member not allowed, in the object's own order: it is the earliest in
        # document order, and a hostile object with thousands of members costs one pointer.
        for name in instance:
            if name not in declared and not any(re.search(p, name) for p in patterns):
                yield SchemaProblem(tokens + (name,), keyword)
                return
        return
    if keyword == "oneOf" and type(instance) is dict:
        chosen = None
        discriminators = []
        for index, branch in enumerate(error.validator_value):
            for member, rule in branch.get("properties", {}).items():
                if isinstance(rule, dict) and "const" in rule:
                    discriminators.append(member)
                    if member in instance and _same(instance[member], rule["const"]):
                        chosen = index
        if chosen is not None:
            inner = [e for e in error.context if e.relative_schema_path[0] == chosen]
            if inner:
                for sub in inner:
                    yield from _refined(sub)
                return
        elif discriminators:
            yield SchemaProblem(tokens + (discriminators[0],), keyword)
            return
    yield SchemaProblem(tokens, keyword)


def document_order(instance, tokens) -> tuple:
    """A sort key that orders pointers as their targets appear in `instance` (see module text)."""
    key = []
    node = instance
    for token in tokens:
        if type(node) is dict and type(token) is str and token in node:
            key.append((0, list(node).index(token), ""))
            node = node[token]
        elif type(node) is list and type(token) is int and 0 <= token < len(node):
            key.append((0, token, ""))
            node = node[token]
        else:
            key.append((1, 0, str(token)))
            node = None
    return tuple(key)


def first_problem(name: str, instance, *, exact_integers: bool = False) -> SchemaProblem | None:
    """The first error of `instance` against packaged schema `name`, or None when it is valid;
    `exact_integers` as for `validator`."""
    problems = set()
    for error in validator(name, exact_integers=exact_integers).iter_errors(instance):
        problems.update(_refined(error))
    if not problems:
        return None
    return min(problems, key=lambda p: (document_order(instance, p.tokens), p.keyword))
