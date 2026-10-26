"""The session configuration: the strict file loader and `validate_config` (R07-R09, R11).

TWO ENTRY POINTS, ONE RULE SET
------------------------------
`validate_config(mapping)` is the public function of SPEC:32, and a function that receives a
mapping cannot see what R07 says about the file it came from: duplicate keys, invalid UTF-8,
non-finite numbers and the 64 KiB bound are gone or invisible once the bytes are parsed by a
lenient reader. So the file rules live in `load_config_bytes(data)`, which applies them in the
order OPS-06 fixes (size; strict UTF-8, never a replacement decode; no byte order mark; parse
refusing duplicate keys and non-finite numbers) and then calls `validate_config` on what it read.
The strict reader also refuses a carriage return, as it does in a capture line: one written by a
CRLF editor is refused rather than read differently from the same file with LF line ends.

`validate_config` runs the packaged config schema first and the semantic rules second, the rules
the schema cannot express (SPEC:289): numeric IPv4 octets and port range, loopback against
`allow_remote`, force-map keys up to 255, real calendar dates and the epoch's years, the agreement
of `mode` and `profile_declaration`, demo with `synthetic` true, no control in `source_system`,
printable ASCII in `basis`, and no surrogate code point in any string. Within each stage the
error reported is the first in document order (then by rule name), so the same document always
gets the same answer. It returns a deep copy and adds no default (OPS-06): `synthetic`, the time
policy, the endpoint and the force map are whatever the caller wrote, or the configuration is
refused.

Every refusal is `HlaError` with code E_CONFIG and an RFC 6901 pointer into the document as its
path (CR-L01), `""` for the document as a whole. Messages are fixed text and quote no input; a
key taken from the input reaches the pointer only through `errors.safe_text`. A Python value that
is not JSON at all (a set, bytes, a non-str key, a subclass of str or int) is a caller bug, not a
configuration, and raises `TypeError`.

The mapping is copied before the schema sees it, and the copy refuses what the file reader would
already have refused in a file: a non-finite number, nesting deeper than any configuration, and
an integer beyond 2^53 - 1. The last matters beyond agreement between the two entry points: the
schema validator writes `repr` of a failing value into its error text, and Python refuses to
write an integer of more than 4300 digits, so such a value must never reach the schema.

`validated_config(mapping)` gives the same answer kept in a `ValidatedConfig`: a frozen wrapper
that only this module can build, so that the live path validates a session's configuration once
and the projector can trust it afterwards (lead ruling CR-L07).

This module opens no file and reads no clock or environment (D-08): the schema comes through
`_schema`, which reads package data through `_resources`. Pure, then, as a statement about this
module's own source.
"""

from __future__ import annotations

import math
import re
from types import MappingProxyType

from synapse_hla import _schema, _utc, canonical, errors
from synapse_hla.errors import HlaError
from synapse_hla.limits import V1

SCHEMA = "config.schema.json"

EXISTING = "existing"
DEMO = "demo"
#: R11: the declaration each mode must carry.
DECLARATION_FOR_MODE = {EXISTING: "external-fom-unverified", DEMO: "bundled-fom-created"}

TIME_NONE = "none"
TIME_EXTERNAL_ELAPSED = "external_elapsed"

#: OPS-04: dotted-quad IPv4 in canonical decimal (no leading zero, so no octal reading by a C
#: resolver), each octet at most three digits, an explicit port without a leading zero. The
#: ranges (octet <= 255, port <= 65535) are checked on the numbers.
_ENDPOINT = re.compile(r"rti://(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})\.(0|[1-9][0-9]{0,2})"
                       r"\.(0|[1-9][0-9]{0,2}):([1-9][0-9]{0,4})")
_MAX_OCTET = 255
_MAX_PORT = 65535
_MAX_FORCE = 255
_LOOPBACK_FIRST_OCTET = 127
_MULTICAST_FIRST_OCTETS = range(224, 240)

_LOAD_MESSAGES = {
    canonical.INVALID_UTF8: "the configuration is not valid UTF-8",
    canonical.BYTE_ORDER_MARK: "the configuration starts with a byte order mark",
    canonical.CARRIAGE_RETURN: "the configuration holds a carriage return",
    canonical.TOO_DEEP: "the configuration nests deeper than any configuration can",
    canonical.NOT_JSON: "the configuration is not one JSON document",
    canonical.DUPLICATE_KEY: "the configuration repeats a member name",
    canonical.NON_FINITE: "the configuration holds a non-finite number",
    canonical.INTEGER_RANGE: "the configuration holds an integer beyond 2^53 - 1",
}

_SEMANTIC_MESSAGES = {
    "basis": "time_policy.basis must be printable ASCII (U+0020 to U+007E)",
    "control": "source_system must not hold a control character",
    "declaration": "profile_declaration does not match mode (R11)",
    "endpoint": "endpoint must be rti://, a canonical IPv4 unicast address and a port 1-65535, "
                "and a nonloopback address needs allow_remote true",
    "epoch": "time_policy.epoch must be a real UTC instant in the years 1970-9998",
    "force_key": "a force_map key must be a decimal integer from 0 to 255",
    "surrogate": "a string of the configuration holds a surrogate code point",
    "synthetic": "mode demo requires synthetic true",
}


def load_config_bytes(data: bytes) -> dict:
    """A configuration file's bytes, read by the rules of R07 and validated; see the module text.

    Raises `HlaError` E_CONFIG on any refusal and `TypeError` when `data` is not exactly `bytes`.
    """
    if type(data) is not bytes:
        raise TypeError("load_config_bytes reads bytes")
    if len(data) > V1.config_file_bytes:
        raise HlaError(errors.E_CONFIG, "", "the configuration file is larger than 64 KiB")
    try:
        document = canonical.strict_loads(data, floats=True, surrogates=True)
    except canonical.StrictJsonError as refusal:
        raise HlaError(errors.E_CONFIG, canonical.json_pointer(refusal.tokens),
                       _LOAD_MESSAGES[refusal.reason]) from None
    return validate_config(document)


def _copy(value, tokens: tuple, depth: int):
    """A deep copy of a JSON value, refusing what a configuration document cannot hold."""
    if depth > canonical.MAX_DEPTH:
        raise HlaError(errors.E_CONFIG, "",
                       "the configuration nests deeper than any configuration can")
    kind = type(value)
    if kind is dict:
        out = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("a configuration member name must be a str")
            out[key] = _copy(item, tokens + (key,), depth + 1)
        return out
    if kind is list:
        return [_copy(item, tokens + (i,), depth + 1) for i, item in enumerate(value)]
    if kind is float and not math.isfinite(value):
        raise HlaError(errors.E_CONFIG, canonical.json_pointer(tokens),
                       "the configuration holds a non-finite number")
    if kind is int and not -canonical.MAX_EXACT_INTEGER <= value <= canonical.MAX_EXACT_INTEGER:
        raise HlaError(errors.E_CONFIG, canonical.json_pointer(tokens),
                       _LOAD_MESSAGES[canonical.INTEGER_RANGE])
    if kind in (str, int, float, bool) or value is None:
        return value
    raise TypeError(f"{kind.__name__} is not a JSON value")


def _has_surrogate(text: str) -> bool:
    return any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)


def _surrogate_problems(value, tokens: tuple):
    if type(value) is dict:
        for key, item in value.items():
            if _has_surrogate(key):
                yield tokens + (key,)
            yield from _surrogate_problems(item, tokens + (key,))
    elif type(value) is list:
        for i, item in enumerate(value):
            yield from _surrogate_problems(item, tokens + (i,))
    elif type(value) is str and _has_surrogate(value):
        yield tokens


def endpoint_permitted(endpoint: str, allow_remote: bool) -> bool:
    """OPS-04 and R07: may a worker be pointed at `endpoint`, given `allow_remote`?

    The grammar above; each octet at most 255 and the port 1-65535; never 0.0.0.0, a multicast
    address (224.0.0.0/4) or the limited broadcast 255.255.255.255, whatever `allow_remote` says;
    and an address outside 127.0.0.0/8 only with `allow_remote` true.
    """
    match = _ENDPOINT.fullmatch(endpoint)
    if match is None:
        return False
    octets = [int(group) for group in match.groups()[:4]]
    port = int(match.group(5))
    if any(octet > _MAX_OCTET for octet in octets) or port > _MAX_PORT:
        return False
    if octets == [0, 0, 0, 0] or octets == [_MAX_OCTET] * 4:
        return False
    if octets[0] in _MULTICAST_FIRST_OCTETS:
        return False
    return octets[0] == _LOOPBACK_FIRST_OCTET or allow_remote is True


def _semantic_problems(document: dict):
    """Every semantic rule broken by a schema-valid document, as (pointer tokens, rule name)."""
    for tokens in _surrogate_problems(document, ()):
        yield tokens, "surrogate"
    if any(ord(ch) <= 0x1F or 0x7F <= ord(ch) <= 0x9F for ch in document["source_system"]):
        yield ("source_system",), "control"
    if not endpoint_permitted(document["endpoint"], document["allow_remote"]):
        yield ("endpoint",), "endpoint"
    if document["profile_declaration"] != DECLARATION_FOR_MODE[document["mode"]]:
        yield ("profile_declaration",), "declaration"
    if document["mode"] == DEMO and document["synthetic"] is not True:
        yield ("synthetic",), "synthetic"
    for key in document["force_map"]:
        if int(key) > _MAX_FORCE:
            yield ("force_map", key), "force_key"
    policy = document["time_policy"]
    if policy["mode"] == TIME_EXTERNAL_ELAPSED:
        try:
            _utc.parse_microsecond(policy["epoch"])
        except ValueError:
            yield ("time_policy", "epoch"), "epoch"
        if not all(0x20 <= ord(ch) <= 0x7E for ch in policy["basis"]):
            yield ("time_policy", "basis"), "basis"


def validate_config(mapping) -> dict:
    """`mapping` checked against R07-R09 and R11, returned as a deep copy; see the module text."""
    document = _copy(mapping, (), 1)
    problem = _schema.first_problem(SCHEMA, document)
    if problem is not None:
        raise HlaError(errors.E_CONFIG, canonical.json_pointer(problem.tokens),
                       f"the configuration does not satisfy its schema ({problem.keyword})")
    found = list(_semantic_problems(document))
    if found:
        tokens, rule = min(found, key=lambda p: (_schema.document_order(document, p[0]), p[1]))
        raise HlaError(errors.E_CONFIG, canonical.json_pointer(tokens), _SEMANTIC_MESSAGES[rule])
    return document


def epoch_microsecond(config) -> int | None:
    """The epoch of a validated configuration in microseconds, or None under time policy none."""
    policy = config["time_policy"]
    if policy["mode"] != TIME_EXTERNAL_ELAPSED:
        return None
    return _utc.parse_microsecond(policy["epoch"])


# --- one validation per session (lead ruling CR-L07) ---------------------------------------------

def _frozen(value):
    # A configuration holds objects, strings and booleans only (its schema has no array and no
    # number), so a read-only view of every object is a complete freeze.
    if type(value) is dict:
        return MappingProxyType({key: _frozen(item) for key, item in value.items()})
    return value


class ValidatedConfig:
    """A session configuration that `validate_config` accepted, frozen, for the live path.

    The reducer projects every eligible snapshot of a session with the same configuration, and
    validating it again for each one cost more than the projection itself (CR-L07). So the
    reducer validates the header's configuration once, keeps it in this wrapper, and hands the
    wrapper to `project_state`, which trusts it without another validation; a plain mapping is
    still validated there as before. Trust needs a guarantee, so the wrapper cannot be built
    from outside this module (`validated_config` is the only way, and it goes through
    `validate_config`), cannot be changed once built (`document` is a read-only view, and no
    attribute can be set), and a copy of it is itself. Two wrappers are equal when their
    configurations have the same canonical bytes.
    """

    __slots__ = ("_document", "_canonical", "_epoch")

    def __init__(self, *_args, **_kwargs) -> None:
        raise TypeError("a ValidatedConfig comes only from config.validated_config")

    @classmethod
    def _of(cls, document: dict) -> "ValidatedConfig":
        made = object.__new__(cls)
        object.__setattr__(made, "_document", _frozen(document))
        object.__setattr__(made, "_canonical", canonical.canonical_bytes(document))
        object.__setattr__(made, "_epoch", epoch_microsecond(document))
        return made

    def __setattr__(self, _name, _value) -> None:
        raise AttributeError("a ValidatedConfig is read-only")

    def __delattr__(self, _name) -> None:
        raise AttributeError("a ValidatedConfig is read-only")

    @property
    def document(self):
        """The configuration as a read-only mapping (nested objects read-only too)."""
        return self._document

    @property
    def canonical(self) -> bytes:
        """The configuration's canonical JSON bytes (sorted keys, ASCII, no line end)."""
        return self._canonical

    @property
    def epoch_microsecond(self) -> int | None:
        """`epoch_microsecond` of the configuration, computed once."""
        return self._epoch

    def __eq__(self, other: object) -> bool:
        if type(other) is not ValidatedConfig:
            return NotImplemented
        return self._canonical == other._canonical

    def __hash__(self) -> int:
        return hash(self._canonical)

    def __copy__(self) -> "ValidatedConfig":
        return self

    def __deepcopy__(self, _memo) -> "ValidatedConfig":
        return self

    def __reduce__(self):
        raise TypeError("a ValidatedConfig is not pickled; validate the configuration again")

    def __repr__(self) -> str:
        return f"ValidatedConfig(<{len(self._canonical)} canonical bytes>)"


def validated_config(mapping) -> ValidatedConfig:
    """`validate_config(mapping)` kept in a `ValidatedConfig` (CR-L07): the same refusals, the
    same `TypeError` for a value that is not JSON."""
    return ValidatedConfig._of(validate_config(mapping))
