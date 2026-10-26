"""The error model: the catalogue against SPEC:190-199, severity, exit classes, HlaError.

Every expectation below is written out by hand from the specification's table and from the
rulings it cites (OPS-02, OPS-19, CR-L01), never read back from `synapse_hla.errors`.
"""

import pickle
import re

import pytest

from hla_support import case
from synapse_hla import errors
from synapse_hla.errors import HlaError

#: The table at SPEC:190-199, row by row: the codes in the order the row lists them, and the
#: behaviour the row's second column prescribes.
TABLE = (
    (("E_CONFIG", "E_DEPENDENCY_PIN", "E_OUTPUT_EXISTS"), "fail_before_connection"),
    (("E_FOM_PROFILE", "E_FEDERATE_NAME", "E_RTI_CONNECT", "E_RTI_TIMEOUT"),
     "terminate_attempt"),
    (("E_ATTRIBUTE_LENGTH", "E_NONFINITE", "E_BOOLEAN", "E_SPATIAL_VARIANT",
      "E_UNSUBSCRIBED_ATTRIBUTE"), "reject_reflection"),
    (("E_NULL_ID", "E_ECEF_RANGE", "E_GEODESY", "E_TIME_REGRESSION"), "suppress_projection"),
    (("E_IDENTITY_CHANGED", "E_IDENTITY_COLLISION", "E_RETRACTION_UNSUPPORTED"), "quarantine"),
    (("E_UNKNOWN_OBJECT",), "ignore_mutation"),
    (("E_LIMIT", "E_QUEUE_OVERFLOW", "E_IO"), "stop_session"),
    (("E_CAPTURE_SCHEMA", "E_CAPTURE_HASH", "E_CAPTURE_SEQUENCE", "E_CAPTURE_INCOMPLETE"),
     "refuse_replay"),
    (("W_FOM_UNVERIFIED", "W_TIME_UNRESOLVED", "W_FORCE_UNMAPPED", "W_DUPLICATE_DISCOVERY",
      "W_DUPLICATE_REMOVE"), "preserve_source"),
)

#: The 32 names, in table order.
ALL_CODES = tuple(code for row, _ in TABLE for code in row)

#: OPS-02's class table, transcribed: class -> the codes it names. "All decoder, reducer and
#: projection codes and all E_CAPTURE_*" are the rows of SPEC:193-196 and SPEC:198.
OPS_02 = {
    2: ("E_CONFIG", "E_OUTPUT_EXISTS"),
    3: ("E_ATTRIBUTE_LENGTH", "E_NONFINITE", "E_BOOLEAN", "E_SPATIAL_VARIANT",
        "E_UNSUBSCRIBED_ATTRIBUTE", "E_NULL_ID", "E_ECEF_RANGE", "E_GEODESY", "E_TIME_REGRESSION",
        "E_IDENTITY_CHANGED", "E_IDENTITY_COLLISION", "E_RETRACTION_UNSUPPORTED",
        "E_UNKNOWN_OBJECT", "E_CAPTURE_SCHEMA", "E_CAPTURE_HASH", "E_CAPTURE_SEQUENCE",
        "E_CAPTURE_INCOMPLETE"),
    4: ("E_DEPENDENCY_PIN",),
    5: ("E_FOM_PROFILE", "E_FEDERATE_NAME", "E_RTI_CONNECT", "E_RTI_TIMEOUT"),
    6: ("E_LIMIT", "E_QUEUE_OVERFLOW", "E_IO"),
}


@case("G-R37")
def test_the_catalogue_is_the_table_in_the_tables_order():
    assert len(ALL_CODES) == 32
    assert sum(c.startswith("E_") for c in ALL_CODES) == 27
    assert sum(c.startswith("W_") for c in ALL_CODES) == 5
    assert errors.CODES == ALL_CODES
    assert errors.CODE_SET == frozenset(ALL_CODES)


@pytest.mark.parametrize("code", ALL_CODES)
def test_each_code_is_a_module_constant_whose_value_is_its_name(code):
    assert getattr(errors, code) == code


def test_no_other_module_constant_looks_like_a_code():
    """The set is closed: a constant that looks like a code and is not in the table is refused."""
    looks_like = {n for n in vars(errors) if re.fullmatch(r"[EW]_[A-Z0-9_]+", n)}
    assert looks_like == set(ALL_CODES)


@pytest.mark.parametrize("code", ALL_CODES)
def test_severity_follows_the_prefix(code):
    expected = "ERROR" if code[0] == "E" else "WARNING"
    assert errors.severity(code) == expected


@pytest.mark.parametrize("value", ["E_SOMETHING_NEW", "W_SOMETHING_NEW", "", "e_config",
                                   " E_CONFIG", "E_CONFIG ", "E_CONFIG\n", "ERROR"])
def test_severity_refuses_a_string_outside_the_catalogue(value):
    with pytest.raises(ValueError):
        errors.severity(value)


@pytest.mark.parametrize("value", [None, b"E_CONFIG", 1, ("E_CONFIG",)])
def test_severity_refuses_a_non_string(value):
    with pytest.raises(ValueError):
        errors.severity(value)


def test_is_code_is_exact_membership():
    assert all(errors.is_code(c) for c in ALL_CODES)
    for value in ("E_SOMETHING_NEW", "e_config", "E_CONFIG ", b"E_CONFIG", None, 7):
        assert errors.is_code(value) is False


class _Str(str):
    pass


def test_is_code_refuses_a_str_subclass():
    # A str subclass can override __eq__ and __hash__; the catalogue compares plain text only.
    assert errors.is_code(_Str("E_CONFIG")) is False


@case("G-R37", paragraphs=("SPEC:190",))
def test_every_code_has_the_behaviour_of_its_table_row():
    expected = {code: behaviour for row, behaviour in TABLE for code in row}
    assert errors.POLICY == expected


@pytest.mark.parametrize("table", ["POLICY", "EXIT_CLASS"])
def test_the_policy_and_exit_class_tables_are_read_only(table):
    """A caller that could edit these would change what a code means for every other caller."""
    mapping = getattr(errors, table)
    before = dict(mapping)
    with pytest.raises(TypeError):
        mapping["E_CONFIG"] = "anything"
    with pytest.raises(TypeError):
        mapping["E_NEW_CODE"] = "anything"
    with pytest.raises(TypeError):
        del mapping["E_CONFIG"]
    assert not hasattr(mapping, "update") and not hasattr(mapping, "pop")
    assert dict(mapping) == before


def test_the_exit_classes_are_ops_02():
    expected = {code: cls for cls, codes in OPS_02.items() for code in codes}
    assert len(expected) == 27
    assert set(expected) == {c for c in ALL_CODES if c.startswith("E_")}
    assert errors.EXIT_CLASS == expected


def test_no_warning_code_has_an_exit_class():
    """W_ codes never change the exit (SPEC:184, OPS-02)."""
    assert not any(c.startswith("W_") for c in errors.EXIT_CLASS)


# ------------------------------------------------------------------------------------- HlaError

def test_hla_error_is_a_value_error_with_three_fields():
    e = HlaError("E_CONFIG", "/time_policy/epoch", "the epoch is not a calendar date")
    assert isinstance(e, ValueError)
    assert (e.code, e.path, e.message) == ("E_CONFIG", "/time_policy/epoch",
                                           "the epoch is not a calendar date")
    assert e.args == ("E_CONFIG", "/time_policy/epoch", "the epoch is not a calendar date")
    assert str(e) == "E_CONFIG at /time_policy/epoch: the epoch is not a calendar date"


def test_an_empty_path_is_shown_as_the_whole_document():
    e = HlaError("E_CONFIG", "", "the document is not an object")
    assert e.path == ""
    assert str(e) == 'E_CONFIG at "": the document is not an object'


def test_hla_error_survives_pickling_with_its_fields():
    e = HlaError("E_CAPTURE_HASH", "line:5", "the frame digest does not match")
    back = pickle.loads(pickle.dumps(e))
    assert type(back) is HlaError
    assert (back.code, back.path, back.message) == (e.code, e.path, e.message)


@pytest.mark.parametrize("code", [c for c in ALL_CODES if c.startswith("E_")])
def test_every_error_code_is_accepted(code):
    assert HlaError(code, "x", "m").code == code


@pytest.mark.parametrize("code", [c for c in ALL_CODES if c.startswith("W_")])
def test_a_warning_code_is_refused(code):
    """CR-new-R0-01: a fatal exception never carries a W_ code."""
    with pytest.raises(ValueError):
        HlaError(code, "x", "m")


@pytest.mark.parametrize("code", ["E_SOMETHING_NEW", "e_config", "", "E_CONFIG ", None,
                                  b"E_CONFIG", _Str("E_CONFIG")])
def test_a_code_outside_the_catalogue_is_refused(code):
    with pytest.raises(ValueError):
        HlaError(code, "x", "m")


@pytest.mark.parametrize("path", [None, b"/a", 3, ["/a"]])
def test_a_non_text_path_is_refused(path):
    with pytest.raises(TypeError):
        HlaError("E_CONFIG", path, "m")


@pytest.mark.parametrize("message", [None, b"bytes", 7])
def test_a_non_text_message_is_refused(message):
    with pytest.raises(TypeError):
        HlaError("E_CONFIG", "", message)


def test_the_message_length_bound_is_256_characters_inclusive():
    assert HlaError("E_CONFIG", "", "m" * 256).message == "m" * 256
    # Characters, not bytes: 256 two-byte characters are still 256.
    assert HlaError("E_CONFIG", "", "\u00e9" * 256).message == "\u00e9" * 256
    with pytest.raises(ValueError):
        HlaError("E_CONFIG", "", "m" * 257)
    with pytest.raises(ValueError):
        HlaError("E_CONFIG", "", "")


#: (code point, accepted?) at both edges of every refused range, written out by hand. U+061C
#: ARABIC LETTER MARK is the one member of the Unicode Bidi_Control set outside U+200E-U+2069
#: (review finding R0-r1-F1); its neighbours U+061B and U+061D are ordinary.
EDGES = (
    (0x0000, False), (0x0009, False), (0x000A, False), (0x000D, False), (0x001B, False),
    (0x001F, False), (0x0020, True), (0x007E, True), (0x007F, False), (0x0085, False),
    (0x009F, False), (0x00A0, True), (0x061B, True), (0x061C, False), (0x061D, True),
    (0x200D, True), (0x200E, False), (0x200F, False),
    (0x2010, True), (0x2027, True), (0x2028, False), (0x2029, False), (0x202A, False),
    (0x202E, False), (0x202F, True), (0x2065, True), (0x2066, False), (0x2069, False),
    (0x206A, True), (0xD7FF, True), (0xD800, False), (0xDFFF, False), (0xE000, True),
    (0x1F600, True),
)


@pytest.mark.parametrize("point,accepted", EDGES, ids=[f"U+{p:04X}" for p, _ in EDGES])
def test_the_message_refuses_line_breaks_controls_bidi_controls_and_surrogates(point, accepted):
    message = f"before {chr(point)} after"
    if accepted:
        assert HlaError("E_CONFIG", "", message).message == message
    else:
        with pytest.raises(ValueError):
            HlaError("E_CONFIG", "", message)


def test_a_subclass_is_held_to_the_same_rules():
    """CR-L01 allows subclasses; the constructor's checks are inherited, not optional."""

    class Narrower(HlaError):
        pass

    assert isinstance(Narrower("E_IO", "--out", "m"), HlaError)
    with pytest.raises(ValueError):
        Narrower("E_IO", "--out", "two\nlines")


# ------------------------------------------------------------------------------------ safe_text

R = "\ufffd"

#: (input, what safe_text must return), each written out by hand: every refused code point
#: becomes U+FFFD one for one, everything else is kept, and the result is at most 64 characters.
SAFE_TEXT = (
    ("", ""),
    ("Spatial", "Spatial"),
    ("a\nb", f"a{R}b"),
    ("\x00\x1f\x7f\x85\x9f", R * 5),
    ("\x1b[31mred\x1b[0m", f"{R}[31mred{R}[0m"),
    ("\u202eSpatial", f"{R}Spatial"),
    ("\u061bx\u061cy\u061d", f"\u061bx{R}y\u061d"),
    ("\u200e\u200f\u2028\u2029\u202a\u202e\u2066\u2069", R * 8),
    ("\u200d\u2010\u202f\u206a", "\u200d\u2010\u202f\u206a"),
    ("lone \ud800 and \udfff", f"lone {R} and {R}"),
    ("x" * 64, "x" * 64),
    ("x" * 65, "x" * 64),
    ("x" * 10_000, "x" * 64),
    ("\n" * 100, R * 64),
    ("\u00e9" * 70, "\u00e9" * 64),
    ("\U0001f600" * 65, "\U0001f600" * 64),
    ("y" * 63 + "\n" + "z" * 10, "y" * 63 + R),
    ("y" * 64 + "\n", "y" * 64),
)


@pytest.mark.parametrize("text,expected", SAFE_TEXT, ids=[f"case{i}" for i in range(len(SAFE_TEXT))])
def test_safe_text_replaces_each_refused_code_point_and_cuts_to_64_characters(text, expected):
    got = errors.safe_text(text)
    assert type(got) is str and got == expected
    # The result is always fit for a path and, with fixed text around it, for a message.
    assert HlaError("E_CONFIG", got, f"refused: {got}").path == got


@pytest.mark.parametrize("point,accepted", EDGES, ids=[f"U+{p:04X}" for p, _ in EDGES])
def test_safe_text_refuses_exactly_what_the_message_rule_refuses(point, accepted):
    assert errors.safe_text(chr(point)) == (chr(point) if accepted else "\ufffd")


@pytest.mark.parametrize("value", [None, b"Spatial", 7, ["x"]])
def test_safe_text_takes_only_text(value):
    with pytest.raises(TypeError):
        errors.safe_text(value)


def test_safe_text_bounds_quoted_input_at_the_cr_l01_figure():
    """64 is CR-L01's 'never carrying input beyond 64 characters', read from the one limits object."""
    from synapse_hla.limits import V1
    assert V1.error_message_input_chars == 64
    assert len(errors.safe_text("q" * 1000)) == 64
