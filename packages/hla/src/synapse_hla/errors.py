"""The error model of synapse-hla: one exception type and the closed catalogue of diagnostic codes.

ONE TYPE, THREE FIELDS
----------------------
Every fatal input error the public API raises is `HlaError`, a `ValueError`, carrying `code`,
`path` and `message` (lead ruling CR-L01). A caller that catches `HlaError` has caught every
refusal this package makes on purpose; anything else that escapes is a defect, and is meant to
look like one. `code` is the stable part and the only part a test compares together with
`path`. `message` is for a human, varies freely between implementations and is never contract.

What `path` holds depends on where the input came from, and the forms are fixed by CR-L01:
an RFC 6901 JSON Pointer into a configuration document (`""` is the whole document); the
attribute name, or `<name>/<byte offset>` for E_BOOLEAN and E_NONFINITE, for a decode;
`line:<n>` or `line:<n>#<JSON Pointer>` for a capture (the header is line 1); the argument name
for the command line and its files; the pinned file's name for a dependency. The producer of each
form owns its test; this module only requires that `path` is text.

THE MESSAGE IS BOUNDED HERE, NOT AT EACH CALL SITE
--------------------------------------------------
A message is one non-empty line of at most 256 characters, with no control character, line
separator, bidirectional-text control or lone surrogate in it. Those are checked in the
constructor rather than trusted, because the failure they prevent is quiet: a
message built from an object name that happens to hold a newline or an escape sequence would
otherwise reach a terminal or a JSON log intact (R40 says capture strings are data, never
terminal escape sequences). A violating message is a programming defect, so the constructor
raises `TypeError` or `ValueError` instead of producing an `HlaError`: the bad call surfaces as
the wrong exception type in the first test that reaches it. The other half of the rule — a
message never quotes more than 64 characters of input and never an interpreter's exception text
— cannot be checked here, because the constructor cannot tell input from prose; each producer
holds it. `safe_text` is how a producer holds it: input text that is to stand in a message or in
a `path` goes through it first, so that a hostile object or attribute name turns into a clean
refusal instead of a constructor `ValueError` (CR-R0-04).

`HlaError` takes only E_ codes. A W_ code is a limitation that is reported and then lived with
(SPEC:199; W_ codes never change an exit class), so a fatal exception carrying one would be a
contradiction in terms. That reading is stricter than the letter of CR-L01, which says only "one
of the 32 catalogue codes", and is proposed as CR-new-R0-01.

THE CATALOGUE
-------------
The 32 codes of the table at SPEC:190-199, each a module constant whose value is its own name,
in the table's order. The set is closed: no schema of the handoff closes it (the diagnostic code
is free text there), so the closure lives here (OPS-19). Severity follows the prefix and nothing
else: E_ is ERROR, W_ is WARNING. Each E_ code carries the exit class of OPS-02 and each code the
failure policy of its table row, both as data; choosing an exit from them is the command line's
job, not this module's.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from synapse_hla.limits import V1

# --- the catalogue, in the order of the table at SPEC:190-199 ---------------------------------

E_CONFIG = "E_CONFIG"
E_DEPENDENCY_PIN = "E_DEPENDENCY_PIN"
E_OUTPUT_EXISTS = "E_OUTPUT_EXISTS"
E_FOM_PROFILE = "E_FOM_PROFILE"
E_FEDERATE_NAME = "E_FEDERATE_NAME"
E_RTI_CONNECT = "E_RTI_CONNECT"
E_RTI_TIMEOUT = "E_RTI_TIMEOUT"
E_ATTRIBUTE_LENGTH = "E_ATTRIBUTE_LENGTH"
E_NONFINITE = "E_NONFINITE"
E_BOOLEAN = "E_BOOLEAN"
E_SPATIAL_VARIANT = "E_SPATIAL_VARIANT"
E_UNSUBSCRIBED_ATTRIBUTE = "E_UNSUBSCRIBED_ATTRIBUTE"
E_NULL_ID = "E_NULL_ID"
E_ECEF_RANGE = "E_ECEF_RANGE"
E_GEODESY = "E_GEODESY"
E_TIME_REGRESSION = "E_TIME_REGRESSION"
E_IDENTITY_CHANGED = "E_IDENTITY_CHANGED"
E_IDENTITY_COLLISION = "E_IDENTITY_COLLISION"
E_RETRACTION_UNSUPPORTED = "E_RETRACTION_UNSUPPORTED"
E_UNKNOWN_OBJECT = "E_UNKNOWN_OBJECT"
E_LIMIT = "E_LIMIT"
E_QUEUE_OVERFLOW = "E_QUEUE_OVERFLOW"
E_IO = "E_IO"
E_CAPTURE_SCHEMA = "E_CAPTURE_SCHEMA"
E_CAPTURE_HASH = "E_CAPTURE_HASH"
E_CAPTURE_SEQUENCE = "E_CAPTURE_SEQUENCE"
E_CAPTURE_INCOMPLETE = "E_CAPTURE_INCOMPLETE"
W_FOM_UNVERIFIED = "W_FOM_UNVERIFIED"
W_TIME_UNRESOLVED = "W_TIME_UNRESOLVED"
W_FORCE_UNMAPPED = "W_FORCE_UNMAPPED"
W_DUPLICATE_DISCOVERY = "W_DUPLICATE_DISCOVERY"
W_DUPLICATE_REMOVE = "W_DUPLICATE_REMOVE"

#: Every code, in table order. A tuple and not a set so that anything rendering the catalogue
#: renders it in one order on every interpreter (D-19: nothing here may depend on hash order).
CODES: tuple[str, ...] = (
    E_CONFIG, E_DEPENDENCY_PIN, E_OUTPUT_EXISTS,
    E_FOM_PROFILE, E_FEDERATE_NAME, E_RTI_CONNECT, E_RTI_TIMEOUT,
    E_ATTRIBUTE_LENGTH, E_NONFINITE, E_BOOLEAN, E_SPATIAL_VARIANT, E_UNSUBSCRIBED_ATTRIBUTE,
    E_NULL_ID, E_ECEF_RANGE, E_GEODESY, E_TIME_REGRESSION,
    E_IDENTITY_CHANGED, E_IDENTITY_COLLISION, E_RETRACTION_UNSUPPORTED,
    E_UNKNOWN_OBJECT,
    E_LIMIT, E_QUEUE_OVERFLOW, E_IO,
    E_CAPTURE_SCHEMA, E_CAPTURE_HASH, E_CAPTURE_SEQUENCE, E_CAPTURE_INCOMPLETE,
    W_FOM_UNVERIFIED, W_TIME_UNRESOLVED, W_FORCE_UNMAPPED, W_DUPLICATE_DISCOVERY,
    W_DUPLICATE_REMOVE,
)

#: The closed set, for membership tests.
CODE_SET: frozenset[str] = frozenset(CODES)

ERROR = "ERROR"
WARNING = "WARNING"

# --- failure policy: the "Behavior" column of the same table -----------------------------------

FAIL_BEFORE_CONNECTION = "fail_before_connection"
TERMINATE_ATTEMPT = "terminate_attempt"
REJECT_REFLECTION = "reject_reflection"
SUPPRESS_PROJECTION = "suppress_projection"
QUARANTINE = "quarantine"
IGNORE_MUTATION = "ignore_mutation"
STOP_SESSION = "stop_session"
REFUSE_REPLAY = "refuse_replay"
PRESERVE_SOURCE = "preserve_source"

#: Code -> the behaviour its table row prescribes. Held as data so that the reducer, the host and
#: the verifier can be tested against the row their code belongs to rather than against prose.
#: Read-only: a caller that could edit the table could change what a code means for every other
#: caller in the process.
POLICY: Mapping[str, str] = MappingProxyType({
    E_CONFIG: FAIL_BEFORE_CONNECTION,
    E_DEPENDENCY_PIN: FAIL_BEFORE_CONNECTION,
    E_OUTPUT_EXISTS: FAIL_BEFORE_CONNECTION,
    E_FOM_PROFILE: TERMINATE_ATTEMPT,
    E_FEDERATE_NAME: TERMINATE_ATTEMPT,
    E_RTI_CONNECT: TERMINATE_ATTEMPT,
    E_RTI_TIMEOUT: TERMINATE_ATTEMPT,
    E_ATTRIBUTE_LENGTH: REJECT_REFLECTION,
    E_NONFINITE: REJECT_REFLECTION,
    E_BOOLEAN: REJECT_REFLECTION,
    E_SPATIAL_VARIANT: REJECT_REFLECTION,
    E_UNSUBSCRIBED_ATTRIBUTE: REJECT_REFLECTION,
    E_NULL_ID: SUPPRESS_PROJECTION,
    E_ECEF_RANGE: SUPPRESS_PROJECTION,
    E_GEODESY: SUPPRESS_PROJECTION,
    E_TIME_REGRESSION: SUPPRESS_PROJECTION,
    E_IDENTITY_CHANGED: QUARANTINE,
    E_IDENTITY_COLLISION: QUARANTINE,
    E_RETRACTION_UNSUPPORTED: QUARANTINE,
    E_UNKNOWN_OBJECT: IGNORE_MUTATION,
    E_LIMIT: STOP_SESSION,
    E_QUEUE_OVERFLOW: STOP_SESSION,
    E_IO: STOP_SESSION,
    E_CAPTURE_SCHEMA: REFUSE_REPLAY,
    E_CAPTURE_HASH: REFUSE_REPLAY,
    E_CAPTURE_SEQUENCE: REFUSE_REPLAY,
    E_CAPTURE_INCOMPLETE: REFUSE_REPLAY,
    W_FOM_UNVERIFIED: PRESERVE_SOURCE,
    W_TIME_UNRESOLVED: PRESERVE_SOURCE,
    W_FORCE_UNMAPPED: PRESERVE_SOURCE,
    W_DUPLICATE_DISCOVERY: PRESERVE_SOURCE,
    W_DUPLICATE_REMOVE: PRESERVE_SOURCE,
})

#: E_ code -> exit class, OPS-02. Class 2 is invocation and configuration, 3 invalid data
#: (every decoder, reducer and projection code and every E_CAPTURE_*), 4 a missing or mismatched
#: dependency, 5 the RTI, 6 resources and I/O. W_ codes have no class: they never change an exit.
#: Read-only for the reason POLICY is.
EXIT_CLASS: Mapping[str, int] = MappingProxyType({
    E_CONFIG: 2,
    E_OUTPUT_EXISTS: 2,
    E_DEPENDENCY_PIN: 4,
    E_FOM_PROFILE: 5,
    E_FEDERATE_NAME: 5,
    E_RTI_CONNECT: 5,
    E_RTI_TIMEOUT: 5,
    E_ATTRIBUTE_LENGTH: 3,
    E_NONFINITE: 3,
    E_BOOLEAN: 3,
    E_SPATIAL_VARIANT: 3,
    E_UNSUBSCRIBED_ATTRIBUTE: 3,
    E_NULL_ID: 3,
    E_ECEF_RANGE: 3,
    E_GEODESY: 3,
    E_TIME_REGRESSION: 3,
    E_IDENTITY_CHANGED: 3,
    E_IDENTITY_COLLISION: 3,
    E_RETRACTION_UNSUPPORTED: 3,
    E_UNKNOWN_OBJECT: 3,
    E_CAPTURE_SCHEMA: 3,
    E_CAPTURE_HASH: 3,
    E_CAPTURE_SEQUENCE: 3,
    E_CAPTURE_INCOMPLETE: 3,
    E_LIMIT: 6,
    E_QUEUE_OVERFLOW: 6,
    E_IO: 6,
})


def is_code(value: object) -> bool:
    """True when `value` is one of the 32 catalogue codes, compared exactly."""
    return type(value) is str and value in CODE_SET


def severity(code: str) -> str:
    """ERROR for an E_ code and WARNING for a W_ code; anything outside the catalogue raises.

    The prefix is the whole rule (OPS-19), but the catalogue is checked first, so that a string
    which merely looks like a code — `E_SOMETHING_NEW` — is refused rather than given a severity.
    """
    if not is_code(code):
        raise ValueError("not a catalogue code")
    return ERROR if code.startswith("E_") else WARNING


#: Code points a message may not hold, as closed ranges. The C0 controls, DEL and the C1 controls
#: are what a terminal acts on; U+2028 and U+2029 end a line for `str.splitlines()`; the
#: bidirectional-text controls (the whole Bidi_Control set: the Arabic letter mark U+061C, the
#: left-to-right and right-to-left marks, and the embedding, override and isolate controls)
#: reorder what a reader sees; a lone surrogate cannot be written as UTF-8 at all. Listed by
#: number rather than by Unicode category so that the rule is the same on every interpreter,
#: whatever version of the character database it carries (D-19).
_REFUSED_IN_MESSAGE: tuple[tuple[int, int], ...] = (
    (0x0000, 0x001F),
    (0x007F, 0x009F),
    (0x061C, 0x061C),
    (0x200E, 0x200F),
    (0x2028, 0x202E),
    (0x2066, 0x2069),
    (0xD800, 0xDFFF),
)

#: What `safe_text` puts in place of each refused code point: U+FFFD REPLACEMENT CHARACTER, the
#: character Unicode reserves for "something was here that cannot be shown".
REPLACEMENT = "�"


def _refused(point: int) -> bool:
    return any(lo <= point <= hi for lo, hi in _REFUSED_IN_MESSAGE)


def _message_problem(message: object) -> str | None:
    if type(message) is not str:
        return "type"
    if not message or len(message) > V1.error_message_chars:
        return "length"
    for ch in message:
        if _refused(ord(ch)):
            return "character"
    return None


def safe_text(text: str) -> str:
    """`text` made fit to stand in an `HlaError` message or path: CR-R0-04's one helper.

    Each refused code point (the list above) becomes U+FFFD, one for one, and the result is cut
    to the first 64 characters (`V1.error_message_input_chars`, CR-L01's bound on quoted input).
    Cutting before replacing gives the same result because the replacement is one character for
    one, and it keeps the work bounded however long the input is. Characters are counted, not
    UTF-8 bytes, as CR-L01 counts them. A non-str is a caller bug and raises `TypeError`: input
    that is not text has no business in a message.
    """
    if type(text) is not str:
        raise TypeError("safe_text takes a str")
    head = text[:V1.error_message_input_chars]
    return "".join(REPLACEMENT if _refused(ord(ch)) else ch for ch in head)


class HlaError(ValueError):
    """A fatal input error of the public API: a catalogue E_ code, a path and a one-line message.

    Positional order is `(code, path, message)`, and `args` is that triple, so the exception
    pickles and compares by its fields. `str()` gives `"<code> at <path>: <message>"`, where an
    empty path is shown as `""` so that "the whole document" is still visible.
    """

    def __init__(self, code: str, path: str, message: str) -> None:
        if not is_code(code) or not code.startswith("E_"):
            raise ValueError("HlaError takes an E_ catalogue code")
        if type(path) is not str:
            raise TypeError("HlaError path must be str")
        problem = _message_problem(message)
        if problem == "type":
            raise TypeError("HlaError message must be str")
        if problem is not None:
            raise ValueError("HlaError message must be one line of 1 to 256 printable characters")
        super().__init__(code, path, message)
        self.code = code
        self.path = path
        self.message = message

    def __str__(self) -> str:
        shown = self.path if self.path else '""'
        return f"{self.code} at {shown}: {self.message}"
