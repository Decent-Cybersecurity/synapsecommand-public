"""Identity of an observed object: its `external_id` and its CDM `entity_id` (R26).

WHAT AN IDENTITY IS MADE OF, AND WHAT IT IS NOT
-----------------------------------------------
The identity of an Entity is the capture's own account of the object, and nothing else:

    external_id = canonical JSON of [session_id, generation, site, application, entity,
                                     incarnation], all six as strings, no spaces
    entity_id   = UUIDv5(6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50, UTF-8 of
                         "entity|hla-rpr2|" + external_id), lowercase canonical form

The namespace is the public CDM namespace, and the name is exactly what
`synapse_cdm.ids.derive("hla-rpr2", external_id)` hashes, so the SDK and this module agree
without either calling the other (a test holds the agreement). The session and the generation
are in it so that two sessions, or two connections of one session, never merge their objects;
the incarnation is in it so that a triple reused after a removal is a new entity. The RTI's
handles and object tokens, the object name, the reported class, the position and the force
identifier are NOT in it: they are runtime artefacts or observations, and an identity built from
them would change when they do. Nor does anything here correlate an HLA object with a DIS
entity that happens to carry the same triple: the name is scoped to `hla-rpr2`, and
cross-protocol identity is outside this profile.

An `entity_id` is a correlation aid, not an authenticated identity (R28): anyone who knows the
six values can compute it, so it proves nothing about who published the object.

WHO MAY CALL
------------
The reducer (round R4) when an identifier is claimed, and the projector. Both pass values the
capture and the reducer have already validated, so anything outside the contract here is a bug
in the caller: a value of the wrong Python type raises `TypeError`, a value out of range (a
session id the configuration would refuse, a generation of 0, the null triple 0.0.0, which
R19 says can never be an identity) raises `ValueError`. Nothing here raises `HlaError`, because
no input of this module comes from the wire.
"""

from __future__ import annotations

import re
import uuid

from synapse_hla import canonical
from synapse_hla.canonical import MAX_EXACT_INTEGER

#: The public CDM UUID namespace of R26 (the value of `synapse_cdm.ids.NAMESPACE`).
NAMESPACE = uuid.UUID("6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50")
#: The issuing system: the UUID name's middle part, and the `system` of the Entity's SourceId.
SYSTEM = "hla-rpr2"
#: The CDM id space of an entity, the UUID name's first part (`synapse_cdm.ids.derive`'s kind).
KIND = "entity"
#: The members of an identifier, in the order external_id lists them.
IDENTIFIER_FIELDS = ("site", "application", "entity")
#: The largest value of one identifier member (an RPRunsignedInteger16BE).
MAX_IDENTIFIER_FIELD = 65535

# The configuration's session_id alphabet (R07), matched whole.
_SESSION_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")
# What `external_id` writes: a session id and five canonical decimals, each a JSON string.
_EXTERNAL_ID = re.compile(r'\["[A-Za-z0-9._-]{1,64}"(?:,"(?:0|[1-9][0-9]{0,15})"){5}\]')


def _counter(value, what: str) -> int:
    if type(value) is not int:
        raise TypeError(f"the {what} must be an int")
    if not 1 <= value <= MAX_EXACT_INTEGER:
        raise ValueError(f"the {what} must be between 1 and 2^53 - 1")
    return value


def identifier_fields(identifier) -> tuple[int, int, int]:
    """`(site, application, entity)` of a decoded EntityIdentifier that may be an identity.

    The identifier is the decoded shape `{site, application, entity}`, nothing more; each member
    an int of 0-65535; and not the null triple 0.0.0 (R19, SPEC:281: it allocates no identity).
    """
    if type(identifier) is not dict:
        raise TypeError("an identifier is a dict")
    if set(identifier) != set(IDENTIFIER_FIELDS):
        raise ValueError("an identifier has exactly the members site, application and entity")
    values = tuple(identifier[name] for name in IDENTIFIER_FIELDS)
    for value in values:
        if type(value) is not int:
            raise TypeError("an identifier member must be an int")
        if not 0 <= value <= MAX_IDENTIFIER_FIELD:
            raise ValueError("an identifier member must be between 0 and 65535")
    if values == (0, 0, 0):
        raise ValueError("the null identifier 0.0.0 is never an identity")
    return values


def external_id(session_id: str, generation: int, identifier: dict, incarnation: int) -> str:
    """R26's external_id: the six values as a canonical JSON array of ASCII strings."""
    if type(session_id) is not str:
        raise TypeError("the session id must be a str")
    if _SESSION_ID.fullmatch(session_id) is None:
        raise ValueError("the session id is not 1 to 64 ASCII letters, digits, '.', '_' or '-'")
    _counter(generation, "generation")
    site, application, entity = identifier_fields(identifier)
    _counter(incarnation, "incarnation")
    parts = [session_id, str(generation), str(site), str(application), str(entity),
             str(incarnation)]
    return canonical.canonical_bytes(parts).decode("ascii")


def parts(external: str) -> tuple[str, int, int, int, int, int]:
    """The six values of an external_id this module writes: session id, generation, site,
    application, entity, incarnation."""
    if type(external) is not str:
        raise TypeError("an external_id is a str")
    if _EXTERNAL_ID.fullmatch(external) is None:
        raise ValueError("not an external_id of this profile")
    session_id, *numbers = external[2:-2].split('","')
    generation, site, application, entity, incarnation = (int(n) for n in numbers)
    return session_id, generation, site, application, entity, incarnation


def entity_id(external: str) -> str:
    """R26's entity_id of an external_id this module writes: UUIDv5, lowercase canonical form."""
    if type(external) is not str:
        raise TypeError("an external_id is a str")
    if _EXTERNAL_ID.fullmatch(external) is None:
        raise ValueError("not an external_id of this profile")
    return str(uuid.uuid5(NAMESPACE, f"{KIND}|{SYSTEM}|{external}"))
