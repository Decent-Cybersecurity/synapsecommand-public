"""The canonical writer, the strict reader and the explicit UTC parser.

SPEC:68 fixes the canonical spelling to the byte, so the writer is held to hand-written byte
literals; RED-04 and OPS-06 list what the strict reader refuses that Python's `json` lets through,
so each refusal has a row with the pointer of where it sits. The UTC parser is the authority for
every date the product reads (OPS-03, CR-L05): it is held to hand-derived day counts and, over
the whole range of years, to the standard library's independent proleptic Gregorian calendar.
"""

import datetime

import pytest

from hla_support import case, fixture_capture_records
from synapse_hla import _utc, canonical
from synapse_hla.canonical import StrictJsonError

R = "\N{REPLACEMENT CHARACTER}"
SURROGATE_HIGH = chr(0xD800)
SURROGATE_LOW = chr(0xDFFF)


# ================================================================================ canonical bytes

#: (value, its canonical bytes), written out by hand from SPEC:68: sorted keys, "," and ":" with
#: no space, every non-ASCII character as a lowercase \u escape (U+1F600 as the surrogate pair
#: d83d de00), "/" not escaped, the JSON short escapes for quote, backslash, newline and tab,
#: and the other characters outside U+0020-U+007E (C0 controls and DEL) as \u00XX: SPEC:68
#: names json.dumps with ensure_ascii, whose encoder escapes everything outside printable ASCII.
CANONICAL = [
    ({"b": 1, "a": [True, False, None]}, b'{"a":[true,false,null],"b":1}'),
    ({"s": "\N{LATIN SMALL LETTER E WITH ACUTE}/\N{GRINNING FACE}"},
     b'{"s":"\\u00e9/\\ud83d\\ude00"}'),
    ({"s": "q\"b\\n\nt\tc\x1f"}, b'{"s":"q\\"b\\\\n\\nt\\tc\\u001f"}'),
    ("\x7f", b'"\\u007f"'),
    ({"Z": 0, "a": 0, "_": 0, "\N{LATIN SMALL LETTER E WITH ACUTE}": 0},
     b'{"Z":0,"_":0,"a":0,"\\u00e9":0}'),
    ({"n": 9007199254740991, "m": -9007199254740991},
     b'{"m":-9007199254740991,"n":9007199254740991}'),
    ([], b"[]"),
    ({}, b"{}"),
    ({"x": {"y": {"z": []}}}, b'{"x":{"y":{"z":[]}}}'),
]


@case("G-R15", paragraphs=("SPEC:68",))
@pytest.mark.parametrize("value,expected", CANONICAL, ids=[f"c{i}" for i in range(len(CANONICAL))])
def test_canonical_bytes_are_the_one_spelling_spec_68_describes(value, expected):
    assert canonical.canonical_bytes(value) == expected


@case("G-R15", paragraphs=("SPEC:68",))
def test_a_capture_value_holds_no_float_and_no_integer_beyond_2_to_the_53():
    for value, reason, tokens in [
        ({"a": 1.0}, canonical.FLOAT, ("a",)),
        ({"a": [0, -0.0]}, canonical.FLOAT, ("a", 1)),
        ({"a": 9007199254740992}, canonical.INTEGER_RANGE, ("a",)),
        ([-9007199254740992], canonical.INTEGER_RANGE, (0,)),
    ]:
        with pytest.raises(StrictJsonError) as info:
            canonical.canonical_bytes(value)
        assert (info.value.reason, info.value.tokens) == (reason, tokens)


def test_the_output_form_admits_finite_floats_in_python_repr_and_nothing_non_finite():
    """RED-15: output lines may hold floats, written as Python's shortest repr."""
    assert canonical.canonical_bytes({"v": [1.0, -0.0, 0.1, 1e300]}, floats=True) == (
        b'{"v":[1.0,-0.0,0.1,1e+300]}')
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(StrictJsonError) as info:
            canonical.canonical_bytes({"v": bad}, floats=True)
        assert (info.value.reason, info.value.tokens) == (canonical.NON_FINITE, ("v",))


@case("G-R15", paragraphs=("SPEC:289",))
def test_canonical_json_rejects_lone_surrogates_in_strings_and_keys():
    """SPEC:289. Python's json.dumps would write them as escapes without complaint."""
    for value, tokens in [
        ({"a": "x" + SURROGATE_HIGH}, ("a",)),
        ({"a": [SURROGATE_LOW]}, ("a", 0)),
        ({SURROGATE_HIGH: 1}, (SURROGATE_HIGH,)),
    ]:
        with pytest.raises(StrictJsonError) as info:
            canonical.canonical_bytes(value)
        assert (info.value.reason, info.value.tokens) == (canonical.LONE_SURROGATE, tokens)
    # A pair escape is one supplementary character, not a lone surrogate.
    assert canonical.canonical_bytes("\N{GRINNING FACE}") == b'"\\ud83d\\ude00"'


class _Text(str):
    pass


class _Number(int):
    pass


@pytest.mark.parametrize("value", [b"x", (1,), {1}, object(), _Text("x"), _Number(1), {1: "a"},
                                   {"a": bytearray(b"x")}])
def test_a_python_value_that_is_not_json_is_a_caller_bug(value):
    with pytest.raises(TypeError):
        canonical.canonical_bytes(value)


def test_nesting_is_bounded_on_writing():
    deep = []
    for _ in range(canonical.MAX_DEPTH - 1):
        deep = [deep]
    assert canonical.canonical_bytes(deep) == b"[" * 32 + b"]" * 32
    with pytest.raises(StrictJsonError) as info:
        canonical.canonical_bytes([deep])
    assert info.value.reason == canonical.TOO_DEEP


def test_sha256_is_lowercase_hexadecimal():
    # The digest of the empty string, FIPS 180-4's well-known value.
    assert canonical.sha256_hex(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")


@case("G-R15", paragraphs=("SPEC:68",))
def test_the_record_digest_is_over_the_record_without_its_sha256():
    """RED-20 and SPEC:68: the bundled capture's own digests, as the fixture records them."""
    records = fixture_capture_records()
    assert canonical.record_sha256(records[1]) == (
        "e092c98d642c20d0772d24ee86885c9468fbe70ffdf2b0a3eee7124e28d0fb04")
    assert canonical.record_sha256(records[-1]) == (
        "6a89145f412a43c7197fe5735a1addfa16e6452b8466be859be1612527027eb8")
    for record in records[1:]:
        assert canonical.record_sha256(record) == record["sha256"]


# ================================================================================== JSON pointers

@pytest.mark.parametrize("tokens,expected", [
    ((), ""),
    (("a",), "/a"),
    (("a/b", "~", 0, ""), "/a~1b/~0/0/"),
    (("\x1b[2J",), f"/{R}[2J"),
    (("x" * 100,), "/" + "x" * 64),
    (("\N{RIGHT-TO-LEFT OVERRIDE}/",), f"/{R}~1"),
    ((SURROGATE_HIGH,), f"/{R}"),
])
def test_a_pointer_escapes_rfc_6901_after_making_each_key_safe(tokens, expected):
    assert canonical.json_pointer(tokens) == expected


# ================================================================================== strict reader

def _nested(levels: int) -> list:
    value: list = []
    for _ in range(levels - 1):
        value = [value]
    return value


#: Thirty-two nested lists, the deepest the reader admits.
NESTED_32 = _nested(32)

#: (input bytes, floats, surrogates, expected): a value, or (reason, pointer tokens).
READS = [
    (b'{"a":1}', False, False, {"a": 1}),
    (b'  {"a" : [1, "x", null, true]}\n', False, False, {"a": [1, "x", None, True]}),
    (b'{"a":-0}', False, False, {"a": 0}),
    (b'{"a":1,"a":2}', False, False, (canonical.DUPLICATE_KEY, ("a",))),
    # Document order, not the parser's inner-first order: x's duplicate comes before y's NaN...
    (b'{"x":{"a":1,"a":2},"y":NaN}', True, True, (canonical.DUPLICATE_KEY, ("x", "a"))),
    # ...and here y's NaN comes before x's duplicate.
    (b'{"y":NaN,"x":{"a":1,"a":2}}', True, True, (canonical.NON_FINITE, ("y",))),
    (b'[1,NaN]', True, True, (canonical.NON_FINITE, (1,))),
    (b'{"a":Infinity}', True, True, (canonical.NON_FINITE, ("a",))),
    (b'{"a":-Infinity}', True, True, (canonical.NON_FINITE, ("a",))),
    (b'{"a":1e400}', True, True, (canonical.NON_FINITE, ("a",))),
    (b'{"a":-1E999}', True, True, (canonical.NON_FINITE, ("a",))),
    (b'{"a":1e400}', False, False, (canonical.FLOAT, ("a",))),
    (b'{"a":1.0}', False, False, (canonical.FLOAT, ("a",))),
    (b'{"a":1e2}', False, False, (canonical.FLOAT, ("a",))),
    (b'{"a":[2,-0.0]}', False, False, (canonical.FLOAT, ("a", 1))),
    (b'{"a":1.5}', True, False, {"a": 1.5}),
    (b'{"a":9007199254740991}', False, False, {"a": 9007199254740991}),
    (b'{"a":9007199254740992}', False, False, (canonical.INTEGER_RANGE, ("a",))),
    (b'{"a":-9007199254740992}', False, False, (canonical.INTEGER_RANGE, ("a",))),
    # Far beyond the interpreter's own 4300-digit conversion limit: still this refusal.
    (b'{"a":' + b"9" * 5000 + b"}", True, True, (canonical.INTEGER_RANGE, ("a",))),
    (b'"\\ud800"', False, False, (canonical.LONE_SURROGATE, ())),
    (b'"\\ud800"', True, True, SURROGATE_HIGH),
    (b'{"\\udfff":1}', False, False, (canonical.LONE_SURROGATE, (SURROGATE_LOW,))),
    (b'["ok","x\\udbff"]', False, False, (canonical.LONE_SURROGATE, (1,))),
    (b'"\\ud83d\\ude00"', False, False, "\N{GRINNING FACE}"),
    (b'"\\u00E9"', False, False, "\N{LATIN SMALL LETTER E WITH ACUTE}"),
    (b'\xef\xbb\xbf{}', True, True, (canonical.BYTE_ORDER_MARK, ())),
    (b'{"a":1}\r', True, True, (canonical.CARRIAGE_RETURN, ())),
    (b'{\r\n"a":1}', True, True, (canonical.CARRIAGE_RETURN, ())),
    (b'{"a":"\\r"}', True, True, {"a": "\r"}),
    (b'{"a":"\xff"}', True, True, (canonical.INVALID_UTF8, ())),
    (b'"\xed\xa0\x80"', True, True, (canonical.INVALID_UTF8, ())),
    (b'"\xc0\xaf"', True, True, (canonical.INVALID_UTF8, ())),
    (b'"\xe2\x82"', True, True, (canonical.INVALID_UTF8, ())),
    (b"", True, True, (canonical.NOT_JSON, ())),
    (b"{}{}", True, True, (canonical.NOT_JSON, ())),
    (b'{"a":}', True, True, (canonical.NOT_JSON, ())),
    (b"[", True, True, (canonical.NOT_JSON, ())),
    (b"nul", True, True, (canonical.NOT_JSON, ())),
    (b"[" * 32 + b"]" * 32, False, False, NESTED_32),
    (b"[" * 33 + b"]" * 33, False, False, (canonical.TOO_DEEP, ())),
    (b"[" * 100000, False, False, (canonical.TOO_DEEP, ())),
    # Brackets inside a string do not nest.
    (b'"' + b"[" * 40 + b'"', False, False, "[" * 40),
    (b'["\\"' + b"[" * 40 + b'"]', False, False, ['"' + "[" * 40]),
]


@pytest.mark.parametrize("data,floats,surrogates,expected", READS,
                         ids=[f"r{i}" for i in range(len(READS))])
def test_the_strict_reader(data, floats, surrogates, expected):
    if isinstance(expected, tuple):
        with pytest.raises(StrictJsonError) as info:
            canonical.strict_loads(data, floats=floats, surrogates=surrogates)
        assert (info.value.reason, info.value.tokens) == expected
    else:
        assert canonical.strict_loads(data, floats=floats, surrogates=surrogates) == expected


#: (input, the first problem by document order, the first by stage): a configuration reports
#: the first in document order (OPS-06); a capture line every duplicate key before any value
#: problem (RED-06: "JSON/duplicate keys, float/surrogate").
ORDERS = [
    (b'{"a":NaN,"b":1,"b":2}', (canonical.NON_FINITE, ("a",)),
     (canonical.DUPLICATE_KEY, ("b",))),
    (b'{"a":"\\ud800","b":{"c":1,"c":1}}', (canonical.LONE_SURROGATE, ("a",)),
     (canonical.DUPLICATE_KEY, ("b", "c"))),
    (b'{"a":[9007199254740992],"b":1,"b":1}', (canonical.INTEGER_RANGE, ("a", 0)),
     (canonical.DUPLICATE_KEY, ("b",))),
    (b'{"\\udc00":1,"b":1,"b":1}', (canonical.LONE_SURROGATE, ("\udc00",)),
     (canonical.DUPLICATE_KEY, ("b",))),
    (b'{"b":1,"b":1,"a":NaN}', (canonical.DUPLICATE_KEY, ("b",)),
     (canonical.DUPLICATE_KEY, ("b",))),
    (b'{"a":1.0,"b":"\\ud800"}', (canonical.FLOAT, ("a",)), (canonical.FLOAT, ("a",))),
]


@pytest.mark.parametrize("data,by_document,by_stage", ORDERS,
                         ids=[f"o{i}" for i in range(len(ORDERS))])
def test_document_order_and_stage_order(data, by_document, by_stage):
    for staged, expected in ((False, by_document), (True, by_stage)):
        with pytest.raises(StrictJsonError) as info:
            canonical.strict_loads(data, floats=False, surrogates=False, staged=staged)
        assert (info.value.reason, info.value.tokens) == expected


@pytest.mark.parametrize("data", ["{}", bytearray(b"{}"), memoryview(b"{}")])
def test_the_strict_reader_reads_bytes_only(data):
    with pytest.raises(TypeError):
        canonical.strict_loads(data, floats=True, surrogates=True)


def test_the_strict_reader_keeps_ints_and_floats_apart():
    value = canonical.strict_loads(b'{"i":1,"f":1.0}', floats=True, surrogates=True)
    assert type(value["i"]) is int and type(value["f"]) is float


# ========================================================================================= UTC

#: (timestamp, microseconds since 1970-01-01T00:00:00Z), derived by hand:
#: 2026-01-01 is day 56 * 365 + 14 = 20454 (56 years, the 14 leap years 1972 ... 2024), and
#: 20454 * 86400 = 1767225600 s, the Unix time of that midnight;
#: 2024-01-01 is day 54 * 365 + 13 = 19723 (1704067200 s); 2024-02-29 is 59 days later, day
#: 19782 (1709164800 s), and 12:34:56 adds 45296 s;
#: 2000-01-01 is day 30 * 365 + 7 = 10957; 2000-02-29 is day 11016 (951782400 s);
#: 9999-01-01 is day 8029 * 365 + 1947 = 2932532 (8029 years 1970-9998 with 2007 - 80 + 20 = 1947
#: leap years), 253370764800 s; the last microsecond before it is 9998-12-31T23:59:59.999999Z.
UTC_VALUES = [
    ("1970-01-01T00:00:00.000000Z", 0),
    ("1970-01-01T00:00:00.000001Z", 1),
    ("2026-01-01T00:00:00.000000Z", 1767225600000000),
    ("2026-01-01T00:00:01.000000Z", 1767225601000000),
    ("2024-02-29T12:34:56.789012Z", 1709210096789012),
    ("2000-02-29T00:00:00.000000Z", 951782400000000),
    ("9998-12-31T23:59:59.999999Z", 253370764799999999),
]


@case("G-R08")
@pytest.mark.parametrize("text,micro", UTC_VALUES)
def test_a_timestamp_is_parsed_to_integer_microseconds(text, micro):
    assert _utc.parse_microsecond(text) == micro
    assert _utc.format_microsecond(micro) == text


def test_the_range_ends_are_1970_and_the_last_microsecond_of_9998():
    assert _utc.MIN_MICROSECOND == 0
    assert _utc.MAX_MICROSECOND == 253370764799999999


#: Each refused for its own reason: calendar, range, form (OPS-03, CR-L05, R08).
UTC_REFUSED = [
    "2026-02-30T00:00:00.000000Z",          # February has no 30th
    "2026-02-29T00:00:00.000000Z",          # 2026 is not a leap year
    "2100-02-29T00:00:00.000000Z",          # a century year not divisible by 400
    "2026-04-31T00:00:00.000000Z",          # April has 30 days
    "2026-13-01T00:00:00.000000Z",
    "2026-00-01T00:00:00.000000Z",
    "2026-01-00T00:00:00.000000Z",
    "2026-01-32T00:00:00.000000Z",
    "2026-01-01T24:00:00.000000Z",
    "2026-01-01T25:00:00.000000Z",
    "2026-01-01T23:60:00.000000Z",
    "2016-12-31T23:59:60.000000Z",          # no leap second
    "1969-12-31T23:59:59.999999Z",
    "9999-01-01T00:00:00.000000Z",
    "0000-01-01T00:00:00.000000Z",
    "2026-01-01T00:00:00.00000Z",
    "2026-01-01T00:00:00.0000000Z",
    "2026-01-01T00:00:00.000Z",
    "2026-01-01T00:00:00Z",
    "2026-01-01T00:00:00.000000+00:00",
    "2026-01-01T00:00:00.000000z",
    "2026-01-01t00:00:00.000000Z",
    "2026-01-01 00:00:00.000000Z",
    "2026-01-01T00:00:00.000000Z\n",
    " 2026-01-01T00:00:00.000000Z",
    "\N{FULLWIDTH DIGIT TWO}026-01-01T00:00:00.000000Z",
    "\N{ARABIC-INDIC DIGIT TWO}026-01-01T00:00:00.000000Z",
    "",
]


@case("G-R08")
@pytest.mark.parametrize("text", UTC_REFUSED, ids=[f"u{i}" for i in range(len(UTC_REFUSED))])
def test_a_timestamp_that_is_not_a_real_instant_of_the_profile_is_refused(text):
    with pytest.raises(ValueError):
        _utc.parse_microsecond(text)


def test_a_timestamp_must_be_text():
    with pytest.raises(TypeError):
        _utc.parse_microsecond(b"2026-01-01T00:00:00.000000Z")


def test_formatting_truncates_to_milliseconds_and_refuses_the_outside():
    assert _utc.format_millisecond(1767225601999999) == "2026-01-01T00:00:01.999Z"
    assert _utc.format_millisecond(0) == "1970-01-01T00:00:00.000Z"
    for bad in (-1, 253370764800000000):
        with pytest.raises(ValueError):
            _utc.format_microsecond(bad)
    with pytest.raises(TypeError):
        _utc.format_microsecond(1.0)


@pytest.mark.parametrize("date,days", [
    ((1970, 1, 1), 0), ((1969, 12, 31), -1), ((2026, 1, 1), 20454), ((2000, 3, 1), 11017),
    ((2024, 2, 29), 19782), ((9999, 1, 1), 2932532), ((1600, 1, 1), -135140),
])
def test_day_counts_by_hand(date, days):
    # 1600-01-01: 370 years back, 90 leap years among 1600-1969 (93 - 4 + 1), 370 * 365 + 90.
    assert _utc.days_from_civil(*date) == days
    assert _utc.civil_from_days(days) == date


def test_the_calendar_agrees_with_the_standard_librarys_on_every_37th_day_of_the_range():
    """An independent proleptic Gregorian calendar: datetime.date's ordinal."""
    origin = datetime.date(1970, 1, 1).toordinal()
    last = _utc.days_from_civil(9998, 12, 31)
    for days in list(range(0, last + 1, 37)) + [last]:
        day = datetime.date.fromordinal(origin + days)
        assert _utc.days_from_civil(day.year, day.month, day.day) == days
        assert _utc.civil_from_days(days) == (day.year, day.month, day.day)
        assert _utc.days_in_month(day.year, day.month) == (
            (datetime.date(day.year + day.month // 12, day.month % 12 + 1, 1)
             - datetime.date(day.year, day.month, 1)).days)
