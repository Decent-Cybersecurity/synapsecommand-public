"""The session configuration: `load_config_bytes` and `validate_config` (R07, R08, R09, R11).

The probe table re-derives, row by row and by hand, what the rules say about each mutation of a
bundled example: every keyword of `config.schema.json` (type, const, enum, pattern, minLength,
maxLength, required, additionalProperties, patternProperties, oneOf) and every semantic rule of
SPEC:289, OPS-03, OPS-04 and OPS-07, at the limit and one past it wherever there is a bound. A row
names the JSON Pointer the refusal must carry (CR-L01), or None for a configuration that must be
accepted. Every refusal is `HlaError` E_CONFIG; nothing here reads a product value to decide what
to expect.
"""

import copy
import json
import random
import socket

import pytest

from hla_support import case, example_json
from sockguard import sitecustomize as sockguard
from synapse_hla import HlaError, config, errors, validate_config
from synapse_hla.config import load_config_bytes

R = "\N{REPLACEMENT CHARACTER}"
E_ACUTE = "\N{LATIN SMALL LETTER E WITH ACUTE}"
GRIN = "\N{GRINNING FACE}"

REQUIRED = ("profile", "session_id", "source_system", "synthetic", "mode", "endpoint",
            "allow_remote", "federation_name", "federate_name", "profile_declaration",
            "time_policy", "force_map")


def base(name: str) -> dict:
    return copy.deepcopy(example_json(f"config-{name}.json"))


def mutated(name: str, ops) -> dict:
    document = base(name)
    for op in ops:
        target = document
        for token in op[1][:-1]:
            target = target[token]
        if op[0] == "set":
            target[op[1][-1]] = op[2]
        else:
            del target[op[1][-1]]
    return document


def refusal(call, *args) -> HlaError:
    with pytest.raises(HlaError) as info:
        call(*args)
    error = info.value
    assert type(error) is HlaError and error.code == errors.E_CONFIG
    return error


def outcome(document) -> str | None:
    """The pointer of the refusal through both entry points, which must agree; None if accepted."""
    data = json.dumps(document).encode("utf-8")
    try:
        loaded = load_config_bytes(data)
    except HlaError as error:
        assert error.code == errors.E_CONFIG
        assert refusal(validate_config, document).path == error.path
        return error.path
    assert loaded == document
    assert validate_config(document) == document
    return None


def S(path, value):
    return ("set", path, value)


def D(path):
    return ("del", path)


def endpoint(value, allow_remote=False):
    return [S(("endpoint",), value), S(("allow_remote",), allow_remote)]


def epoch(value):
    return [S(("time_policy", "epoch"), value)]


def basis(value):
    return [S(("time_policy", "basis"), value)]


def force(mapping):
    return [S(("force_map",), mapping)]


EXT = {"mode": "external_elapsed", "epoch": "2026-01-01T00:00:00.000000Z", "basis": "b"}

#: (id, base example, mutations, expected pointer or None for acceptance)
PROBES = [
    # --- the bundled examples (OPS-14: validation accepts both modes)
    ("example-demo", "demo", [], None),
    ("example-existing", "existing", [], None),
    # --- required: each member, removed; the pointer names the missing member
    *[(f"missing-{m}", "existing", [D((m,))], f"/{m}") for m in REQUIRED],
    # --- additionalProperties
    ("unknown-member", "existing", [S(("extra",), 1)], "/extra"),
    ("member-name-case", "existing", [S(("Mode",), "existing")], "/Mode"),
    # --- profile: const
    ("profile-other", "existing", [S(("profile",), "SC-HLA-RPR2-OBS-2")], "/profile"),
    ("profile-type", "existing", [S(("profile",), 1)], "/profile"),
    # --- session_id: pattern, 1 to 64 of [A-Za-z0-9._-]
    ("session-64", "existing", [S(("session_id",), "a" * 64)], None),
    ("session-65", "existing", [S(("session_id",), "a" * 65)], "/session_id"),
    ("session-empty", "existing", [S(("session_id",), "")], "/session_id"),
    ("session-space", "existing", [S(("session_id",), "a b")], "/session_id"),
    ("session-lf", "existing", [S(("session_id",), "abc\n")], "/session_id"),
    ("session-non-ascii", "existing", [S(("session_id",), E_ACUTE)], "/session_id"),
    ("session-type", "existing", [S(("session_id",), 7)], "/session_id"),
    ("federation-type", "existing", [S(("federation_name",), ["SC"])], "/federation_name"),
    ("federate-type", "existing", [S(("federate_name",), None)], "/federate_name"),
    ("mode-type", "existing", [S(("mode",), 1)], "/mode"),
    ("declaration-type", "existing", [S(("profile_declaration",), True)], "/profile_declaration"),
    ("basis-type", "demo", [S(("time_policy", "basis"), 1)], "/time_policy/basis"),
    ("force-object-type", "existing", [S(("force_map",), "1")], "/force_map"),
    # OPS-08: the alphabet admits these; nothing derives a path from them.
    ("session-dots", "existing", [S(("session_id",), "..")], None),
    ("session-option-like", "existing", [S(("session_id",), "--help")], None),
    ("session-all-symbols", "existing", [S(("session_id",), "._-")], None),
    # --- source_system: 1 to 128 code points, no Cc control, no surrogate (OPS-07)
    ("source-1", "existing", [S(("source_system",), "a")], None),
    ("source-empty", "existing", [S(("source_system",), "")], "/source_system"),
    ("source-128", "existing", [S(("source_system",), "a" * 128)], None),
    ("source-129", "existing", [S(("source_system",), "a" * 129)], "/source_system"),
    ("source-128-supplementary", "existing", [S(("source_system",), GRIN * 128)], None),
    ("source-129-supplementary", "existing", [S(("source_system",), GRIN * 129)],
     "/source_system"),
    ("source-nul", "existing", [S(("source_system",), "a\x00b")], "/source_system"),
    ("source-tab", "existing", [S(("source_system",), "a\tb")], "/source_system"),
    ("source-us", "existing", [S(("source_system",), "a\x1fb")], "/source_system"),
    ("source-del", "existing", [S(("source_system",), "a\x7fb")], "/source_system"),
    ("source-c1-first", "existing", [S(("source_system",), "a\x80b")], "/source_system"),
    ("source-nel", "existing", [S(("source_system",), "a\x85b")], "/source_system"),
    ("source-c1-last", "existing", [S(("source_system",), "a\x9fb")], "/source_system"),
    ("source-nbsp", "existing", [S(("source_system",), "a\xa0b")], None),
    ("source-space", "existing", [S(("source_system",), " ")], None),
    ("source-line-separator", "existing",
     [S(("source_system",), "a\N{LINE SEPARATOR}b")], None),
    ("source-bidi", "existing", [S(("source_system",), "a\N{RIGHT-TO-LEFT OVERRIDE}b")], None),
    ("source-surrogate", "existing", [S(("source_system",), "a" + chr(0xD800))],
     "/source_system"),
    ("source-type", "existing", [S(("source_system",), None)], "/source_system"),
    # --- synthetic: a boolean, required, no default; demo requires true
    ("synthetic-string", "existing", [S(("synthetic",), "true")], "/synthetic"),
    ("synthetic-int", "existing", [S(("synthetic",), 1)], "/synthetic"),
    ("synthetic-null", "existing", [S(("synthetic",), None)], "/synthetic"),
    ("existing-not-synthetic", "existing", [S(("synthetic",), False)], None),
    ("demo-not-synthetic", "demo", [S(("synthetic",), False)], "/synthetic"),
    # --- mode: enum
    ("mode-case", "existing", [S(("mode",), "Existing")], "/mode"),
    ("mode-other", "existing", [S(("mode",), "observe")], "/mode"),
    # --- profile_declaration: enum, and agreement with mode (R11)
    ("declaration-other", "existing", [S(("profile_declaration",), "unverified")],
     "/profile_declaration"),
    ("existing-with-bundled", "existing",
     [S(("profile_declaration",), "bundled-fom-created")], "/profile_declaration"),
    ("demo-with-unverified", "demo",
     [S(("profile_declaration",), "external-fom-unverified")], "/profile_declaration"),
    # --- endpoint, schema: pattern ^rti://[0-9.]+:[0-9]+$ and maxLength 64
    ("endpoint-hostname", "existing", endpoint("rti://localhost:14321"), "/endpoint"),
    ("endpoint-no-port", "existing", endpoint("rti://127.0.0.1"), "/endpoint"),
    ("endpoint-path", "existing", endpoint("rti://127.0.0.1:14321/fed"), "/endpoint"),
    ("endpoint-ipv6", "existing", endpoint("rti://[::1]:14321"), "/endpoint"),
    ("endpoint-rtic", "existing", endpoint("rtic://127.0.0.1:14321"), "/endpoint"),
    ("endpoint-scheme-case", "existing", endpoint("RTI://127.0.0.1:14321"), "/endpoint"),
    ("endpoint-tcp", "existing", endpoint("tcp://127.0.0.1:14321"), "/endpoint"),
    ("endpoint-credentials", "existing", endpoint("rti://user@127.0.0.1:14321"), "/endpoint"),
    ("endpoint-query", "existing", endpoint("rti://127.0.0.1:14321?x=1"), "/endpoint"),
    ("endpoint-fragment", "existing", endpoint("rti://127.0.0.1:14321#f"), "/endpoint"),
    ("endpoint-lf", "existing", endpoint("rti://127.0.0.1:14321\n"), "/endpoint"),
    ("endpoint-other-digits", "existing",
     endpoint("rti://\N{ARABIC-INDIC DIGIT ONE}27.0.0.1:1"), "/endpoint"),
    # 64 characters pass maxLength and then fail the port rule; 65 fail maxLength.
    ("endpoint-64", "existing", endpoint("rti://1.1.1.1:" + "1" * 50, True), "/endpoint"),
    ("endpoint-65", "existing", endpoint("rti://1.1.1.1:" + "1" * 51, True), "/endpoint"),
    ("endpoint-type", "existing", endpoint(14321), "/endpoint"),
    # --- endpoint, semantic (OPS-04): canonical dotted quad, octets <= 255, port 1-65535
    ("octet-255", "existing", endpoint("rti://127.0.0.255:14321"), None),
    ("octet-256", "existing", endpoint("rti://127.0.0.256:14321"), "/endpoint"),
    ("first-octet-256", "existing", endpoint("rti://256.0.0.1:1", True), "/endpoint"),
    ("three-octets", "existing", endpoint("rti://127.0.1:14321"), "/endpoint"),
    ("two-octets", "existing", endpoint("rti://127.1:14321"), "/endpoint"),
    ("integer-host", "existing", endpoint("rti://2130706433:14321"), "/endpoint"),
    ("five-octets", "existing", endpoint("rti://1.2.3.4.5:1", True), "/endpoint"),
    ("empty-octet", "existing", endpoint("rti://127..0.1:1"), "/endpoint"),
    ("leading-zero-octet", "existing", endpoint("rti://0127.0.0.1:14321"), "/endpoint"),
    ("leading-zero-last-octet", "existing", endpoint("rti://127.0.0.01:14321"), "/endpoint"),
    ("port-0", "existing", endpoint("rti://127.0.0.1:0"), "/endpoint"),
    ("port-1", "existing", endpoint("rti://127.0.0.1:1"), None),
    ("port-65535", "existing", endpoint("rti://127.0.0.1:65535"), None),
    ("port-65536", "existing", endpoint("rti://127.0.0.1:65536"), "/endpoint"),
    ("port-99999", "existing", endpoint("rti://127.0.0.1:99999"), "/endpoint"),
    ("port-leading-zero", "existing", endpoint("rti://127.0.0.1:014321"), "/endpoint"),
    # loopback is 127.0.0.0/8; anything else needs allow_remote (A-REMOTE)
    ("loopback-127-1-2-3", "existing", endpoint("rti://127.1.2.3:14321"), None),
    ("loopback-last", "existing", endpoint("rti://127.255.255.255:1"), None),
    ("below-loopback", "existing", endpoint("rti://126.255.255.255:1"), "/endpoint"),
    ("above-loopback", "existing", endpoint("rti://128.0.0.1:1"), "/endpoint"),
    ("remote-refused", "existing", endpoint("rti://10.0.0.5:14321"), "/endpoint"),
    ("remote-allowed", "existing", endpoint("rti://10.0.0.5:14321", True), None),
    ("remote-max-unicast", "existing", endpoint("rti://223.255.255.255:1", True), None),
    ("remote-class-e", "existing", endpoint("rti://240.0.0.1:1", True), None),
    ("remote-254", "existing", endpoint("rti://255.255.255.254:65535", True), None),
    # never, whatever allow_remote says: 0.0.0.0, 224.0.0.0/4, 255.255.255.255
    ("unspecified", "existing", endpoint("rti://0.0.0.0:14321"), "/endpoint"),
    ("unspecified-allowed", "existing", endpoint("rti://0.0.0.0:14321", True), "/endpoint"),
    ("multicast-first", "existing", endpoint("rti://224.0.0.1:1", True), "/endpoint"),
    ("multicast-last", "existing", endpoint("rti://239.255.255.255:1", True), "/endpoint"),
    ("broadcast", "existing", endpoint("rti://255.255.255.255:1", True), "/endpoint"),
    # --- allow_remote: boolean
    ("allow-remote-string", "existing", [S(("allow_remote",), "false")], "/allow_remote"),
    ("allow-remote-int", "existing", [S(("allow_remote",), 0)], "/allow_remote"),
    # --- federation_name, federate_name: the session_id alphabet, 1 to 64
    ("federation-64", "existing", [S(("federation_name",), "f" * 64)], None),
    ("federation-65", "existing", [S(("federation_name",), "f" * 65)], "/federation_name"),
    ("federation-empty", "existing", [S(("federation_name",), "")], "/federation_name"),
    ("federation-space", "existing", [S(("federation_name",), "SC DEMO")], "/federation_name"),
    ("federation-upper-hex", "existing",
     [S(("federation_name",), "SC_DEMO_0123456789ABCDEF")], None),
    ("federate-64", "existing", [S(("federate_name",), "g" * 64)], None),
    ("federate-65", "existing", [S(("federate_name",), "g" * 65)], "/federate_name"),
    ("federate-slash", "existing", [S(("federate_name",), "a/b")], "/federate_name"),
    # --- time_policy: oneOf of two variants, discriminated by mode
    ("time-policy-string", "existing", [S(("time_policy",), "none")], "/time_policy"),
    ("time-policy-empty", "existing", [S(("time_policy",), {})], "/time_policy/mode"),
    ("time-policy-other-mode", "existing", [S(("time_policy",), {"mode": "sometimes"})],
     "/time_policy/mode"),
    ("time-policy-null-mode", "existing", [S(("time_policy",), {"mode": None})],
     "/time_policy/mode"),
    ("none-for-demo", "demo", [S(("time_policy",), {"mode": "none"})], None),
    ("none-with-epoch", "existing",
     [S(("time_policy",), {"mode": "none", "epoch": EXT["epoch"]})], "/time_policy/epoch"),
    ("none-with-basis", "existing", [S(("time_policy",), {"mode": "none", "basis": "b"})],
     "/time_policy/basis"),
    ("external-for-existing", "existing", [S(("time_policy",), EXT)], None),
    ("external-no-epoch", "demo", [D(("time_policy", "epoch"))], "/time_policy/epoch"),
    ("external-no-basis", "demo", [D(("time_policy", "basis"))], "/time_policy/basis"),
    ("external-nothing", "demo", [S(("time_policy",), {"mode": "external_elapsed"})],
     "/time_policy/basis"),
    ("external-extra", "demo", [S(("time_policy", "zone"), "UTC")], "/time_policy/zone"),
    # --- epoch: pattern (the schema) and a real instant in 1970-9998 (semantic)
    ("epoch-milliseconds", "demo", epoch("2026-01-01T00:00:00.000Z"), "/time_policy/epoch"),
    ("epoch-offset", "demo", epoch("2026-01-01T00:00:00.000000+00:00"), "/time_policy/epoch"),
    ("epoch-space", "demo", epoch("2026-01-01 00:00:00.000000Z"), "/time_policy/epoch"),
    ("epoch-lf", "demo", epoch("2026-01-01T00:00:00.000000Z\n"), "/time_policy/epoch"),
    ("epoch-type", "demo", epoch(0), "/time_policy/epoch"),
    ("epoch-feb-30", "demo", epoch("2026-02-30T00:00:00.000000Z"), "/time_policy/epoch"),
    ("epoch-feb-29-common", "demo", epoch("2026-02-29T00:00:00.000000Z"), "/time_policy/epoch"),
    ("epoch-feb-29-leap", "demo", epoch("2024-02-29T00:00:00.000000Z"), None),
    ("epoch-feb-29-400", "demo", epoch("2000-02-29T00:00:00.000000Z"), None),
    ("epoch-feb-29-100", "demo", epoch("2100-02-29T00:00:00.000000Z"), "/time_policy/epoch"),
    ("epoch-apr-31", "demo", epoch("2026-04-31T00:00:00.000000Z"), "/time_policy/epoch"),
    ("epoch-month-13", "demo", epoch("2026-13-01T00:00:00.000000Z"), "/time_policy/epoch"),
    ("epoch-month-0", "demo", epoch("2026-00-01T00:00:00.000000Z"), "/time_policy/epoch"),
    ("epoch-day-0", "demo", epoch("2026-01-00T00:00:00.000000Z"), "/time_policy/epoch"),
    ("epoch-hour-24", "demo", epoch("2026-01-01T24:00:00.000000Z"), "/time_policy/epoch"),
    ("epoch-hour-25", "demo", epoch("2026-01-01T25:00:00.000000Z"), "/time_policy/epoch"),
    ("epoch-minute-60", "demo", epoch("2026-01-01T23:60:00.000000Z"), "/time_policy/epoch"),
    ("epoch-leap-second", "demo", epoch("2016-12-31T23:59:60.000000Z"), "/time_policy/epoch"),
    ("epoch-last-of-1969", "demo", epoch("1969-12-31T23:59:59.999999Z"), "/time_policy/epoch"),
    ("epoch-first-of-1970", "demo", epoch("1970-01-01T00:00:00.000000Z"), None),
    ("epoch-last-of-9998", "demo", epoch("9998-12-31T23:59:59.999999Z"), None),
    ("epoch-first-of-9999", "demo", epoch("9999-01-01T00:00:00.000000Z"), "/time_policy/epoch"),
    ("epoch-year-0", "demo", epoch("0000-01-01T00:00:00.000000Z"), "/time_policy/epoch"),
    # --- basis: 1 to 512 code points of U+0020..U+007E (OPS-07)
    ("basis-empty", "demo", basis(""), "/time_policy/basis"),
    ("basis-1", "demo", basis("a"), None),
    ("basis-512", "demo", basis("a" * 512), None),
    ("basis-513", "demo", basis("a" * 513), "/time_policy/basis"),
    ("basis-space", "demo", basis(" "), None),
    ("basis-tilde-and-space", "demo", basis(" ~" * 256), None),
    ("basis-del", "demo", basis("a\x7f"), "/time_policy/basis"),
    ("basis-tab", "demo", basis("a\tb"), "/time_policy/basis"),
    ("basis-us", "demo", basis("\x1f"), "/time_policy/basis"),
    ("basis-nbsp", "demo", basis("a\xa0b"), "/time_policy/basis"),
    ("basis-e-acute", "demo", basis(E_ACUTE), "/time_policy/basis"),
    ("basis-supplementary", "demo", basis(GRIN), "/time_policy/basis"),
    ("basis-surrogate", "demo", basis(chr(0xDC00)), "/time_policy/basis"),
    # --- force_map: canonical decimal keys 0-255, the four values
    ("force-type", "existing", force([]), "/force_map"),
    ("force-empty", "existing", force({}), None),
    ("force-0", "existing", force({"0": "FRIENDLY"}), None),
    ("force-255", "existing", force({"255": "HOSTILE"}), None),
    ("force-256", "existing", force({"256": "HOSTILE"}), "/force_map/256"),
    ("force-999", "existing", force({"999": "NEUTRAL"}), "/force_map/999"),
    ("force-1000", "existing", force({"1000": "NEUTRAL"}), "/force_map/1000"),
    ("force-leading-zero", "existing", force({"007": "FRIENDLY"}), "/force_map/007"),
    ("force-negative", "existing", force({"-1": "FRIENDLY"}), "/force_map/-1"),
    ("force-trailing-space", "existing", force({"1 ": "FRIENDLY"}), "/force_map/1 "),
    ("force-empty-key", "existing", force({"": "FRIENDLY"}), "/force_map/"),
    ("force-slash-key", "existing", force({"a/b": "FRIENDLY"}), "/force_map/a~1b"),
    ("force-tilde-key", "existing", force({"~": "FRIENDLY"}), "/force_map/~0"),
    ("force-value-case", "existing", force({"1": "friendly"}), "/force_map/1"),
    ("force-value-null", "existing", force({"1": None}), "/force_map/1"),
    ("force-explicit-unknown", "existing", force({"1": "UNKNOWN"}), None),
    ("force-all-256", "existing", force({str(i): "NEUTRAL" for i in range(256)}), None),
    ("force-first-bad-in-order", "existing",
     force({"1": "FRIENDLY", "300": "HOSTILE", "256": "NEUTRAL"}), "/force_map/300"),
]


@case("G-R07", "G-R08", paragraphs=("SPEC:38", "SPEC:289"))
@pytest.mark.parametrize("name,ops,expected", [p[1:] for p in PROBES], ids=[p[0] for p in PROBES])
@case("G-R37", "G-R40", paragraphs=("SPEC:289",))
def test_the_probe_table(name, ops, expected):
    assert outcome(mutated(name, ops)) == expected


def test_the_probe_table_covers_every_keyword_and_rule():
    """The table is a statement about the schema and the rules; this holds it to both."""
    ids = {p[0] for p in PROBES}
    assert len(ids) == len(PROBES)
    assert len(PROBES) >= 79
    assert {f"missing-{m}" for m in REQUIRED} <= ids
    assert set(json.loads(json.dumps(base("demo")))) == set(REQUIRED)


# =============================================================== file level: load_config_bytes

EXISTING_BYTES = json.dumps(base("existing"), indent=2).encode("utf-8")


def _pad_to(data: bytes, size: int) -> bytes:
    return data.rstrip(b"\n") + b" " * (size - len(data.rstrip(b"\n")))


#: (id, bytes, expected pointer or None)
RAW = [
    ("exactly-64-KiB", _pad_to(EXISTING_BYTES, 65536), None),
    ("64-KiB-plus-1", _pad_to(EXISTING_BYTES, 65537), ""),
    # The strict reader refuses a raw CR in a configuration as in a capture line (brief R2,
    # item 1); JSON alone would read it as whitespace.
    ("crlf-line-ends", EXISTING_BYTES.replace(b"\n", b"\r\n"), ""),
    ("cr-as-whitespace", EXISTING_BYTES.replace(b",", b",\r", 1), ""),
    ("escaped-cr-in-a-string", EXISTING_BYTES.replace(b"synthetic-reference", b"a\\rb"),
     "/source_system"),
    ("byte-order-mark", b"\xef\xbb\xbf" + EXISTING_BYTES, ""),
    ("utf-16", EXISTING_BYTES.decode("utf-8").encode("utf-16"), ""),
    ("empty", b"", ""),
    ("whitespace-only", b"  \n", ""),
    ("array", b"[]", ""),
    ("string", b'"existing"', ""),
    ("null", b"null", ""),
    ("number", b"1", ""),
    ("two-documents", EXISTING_BYTES + b"{}", ""),
    ("truncated", EXISTING_BYTES[:-3], ""),
    ("deep", b'{"x":' + b"[" * 40 + b"]" * 40 + b"}", ""),
    ("duplicate-top", EXISTING_BYTES.replace(b'"profile": "SC', b'"profile": "x", "profile": "SC'),
     "/profile"),
    ("duplicate-force-key", EXISTING_BYTES.replace(
        b'"force_map": {}', b'"force_map": {"1": "FRIENDLY", "1": "HOSTILE"}'), "/force_map/1"),
    ("duplicate-time-policy-member", EXISTING_BYTES.replace(
        b'"mode": "none"', b'"mode": "none", "mode": "none"'), "/time_policy/mode"),
    ("nan", EXISTING_BYTES.replace(b'"force_map": {}', b'"force_map": {}, "x": NaN'), "/x"),
    ("infinity", EXISTING_BYTES.replace(b'"force_map": {}', b'"force_map": {}, "x": Infinity'),
     "/x"),
    ("minus-infinity", EXISTING_BYTES.replace(
        b'"force_map": {}', b'"force_map": {}, "x": -Infinity'), "/x"),
    ("overflowing-number", EXISTING_BYTES.replace(
        b'"force_map": {}', b'"force_map": {}, "x": 1e400'), "/x"),
    ("huge-integer", EXISTING_BYTES.replace(
        b'"force_map": {}', b'"force_map": {}, "x": ' + b"7" * 5000), "/x"),
    ("finite-float-unknown-member", EXISTING_BYTES.replace(
        b'"force_map": {}', b'"force_map": {}, "x": 1.5'), "/x"),
    ("surrogate-escape", EXISTING_BYTES.replace(b"synthetic-reference", b"syn\\ud800"),
     "/source_system"),
    ("surrogate-pair-escape", EXISTING_BYTES.replace(b"synthetic-reference", b"syn\\ud83d\\ude00"),
     None),
]


@case("G-R07")
@pytest.mark.parametrize("data,expected", [r[1:] for r in RAW], ids=[r[0] for r in RAW])
def test_the_file_rules_of_r07(data, expected):
    if expected is None:
        assert load_config_bytes(data)["profile"] == "SC-HLA-RPR2-OBS-1"
    else:
        assert refusal(load_config_bytes, data).path == expected


@case("G-R08")
def test_no_date_format_keyword_is_the_only_guard_of_the_epoch():
    """OPS-03: the schema says `format: date-time`, which the product's validator does not check
    (no format checker is attached, and none would be reliable); the schema alone takes
    2026-02-30, and the explicit check refuses it."""
    from synapse_hla import _schema
    document = mutated("demo", epoch("2026-02-30T00:00:00.000000Z"))
    assert _schema.validator("config.schema.json").format_checker is None
    assert _schema.first_problem("config.schema.json", document) is None
    assert refusal(validate_config, document).path == "/time_policy/epoch"


def test_the_padded_rows_are_the_sizes_they_claim():
    assert len(RAW[0][1]) == 65536 and len(RAW[1][1]) == 65537


@case("A-DUPLICATE-KEY", "G-R07")
@pytest.mark.parametrize("data,expected", [
    # The duplicate is the last member, and the document also breaks a schema rule (an unknown
    # member) and a semantic rule (demo without synthetic) earlier on: the duplicate still wins,
    # because it is refused while the bytes are read, before either stage runs.
    (b'{"extra": 1, "profile": "SC-HLA-RPR2-OBS-1", "mode": "demo", "synthetic": false, '
     b'"force_map": {}, "force_map": {}}', "/force_map"),
    (b'{"a": {"b": 1, "b": 1}, "a": 2}', "/a/b"),
    (b'{"a": 1, "a": 1}', "/a"),
    (b'{"force_map": {"1": "FRIENDLY", "1": "FRIENDLY"}}', "/force_map/1"),
])
def test_a_repeated_member_is_refused_before_any_schema_or_semantic_rule(data, expected):
    assert refusal(load_config_bytes, data).path == expected


@case("A-UTF8", "G-R07")
@pytest.mark.parametrize("bad", [
    b"\xff",                  # never a UTF-8 byte
    b"\xc0\xaf",              # overlong encoding of "/"
    b"\xed\xa0\x80",          # an encoded surrogate
    b"\xe2\x82",              # a sequence cut short
    b"\x80",                  # a lone continuation byte
    b"\xf4\x90\x80\x80",      # beyond U+10FFFF
])
def test_invalid_utf8_is_refused_and_never_replacement_decoded(bad):
    """A replacement decode would turn each sequence into U+FFFD, which source_system admits, so
    the decoded document would pass: the refusal shows that no replacement took place."""
    data = EXISTING_BYTES.replace(b"synthetic-reference", b"synthetic" + bad + b"reference")
    assert refusal(load_config_bytes, data).path == ""
    replaced = EXISTING_BYTES.replace(b"synthetic-reference",
                                      ("synthetic" + R + "reference").encode("utf-8"))
    assert load_config_bytes(replaced)["source_system"] == "synthetic" + R + "reference"


@case("A-REMOTE", "G-R07", paragraphs=("SPEC:38",))
@pytest.mark.parametrize("host", ["10.0.0.5", "192.168.1.1", "128.0.0.1", "126.0.0.1",
                                  "8.8.8.8", "172.16.0.1"])
def test_a_nonloopback_endpoint_without_allow_remote_is_refused_before_any_socket(
        host, monkeypatch):
    """A-REMOTE: E_CONFIG at /endpoint, and no socket call of any kind was attempted. The
    offline guard would turn one into a SocketGuardError; recording the calls makes it explicit.
    The same endpoint with allow_remote true is accepted, so the refusal is the R07 rule."""
    attempts = []
    for name in sockguard.GUARDED:
        monkeypatch.setattr(socket, name, lambda *a, _n=name, **k: attempts.append(_n))
    document = mutated("existing", endpoint(f"rti://{host}:14321"))
    data = json.dumps(document).encode("utf-8")
    assert refusal(load_config_bytes, data).path == "/endpoint"
    assert refusal(validate_config, document).path == "/endpoint"
    document["allow_remote"] = True
    assert validate_config(document)["endpoint"] == f"rti://{host}:14321"
    assert attempts == []


# =========================================================================== order of refusals

@case("G-R07")
def test_the_first_error_is_chosen_by_stage_then_document_order():
    """OPS-06: file rules, then the schema, then the semantic rules; inside a stage the error
    earliest in document order. A missing member has no place in the document and counts after
    every present one."""
    # Schema before semantic: the demo document lacks synthetic=true (semantic, earlier) and has
    # a lower-case force value (schema, later).
    doc = mutated("demo", [S(("synthetic",), False), S(("force_map",), {"1": "friendly"})])
    assert outcome(doc) == "/force_map/1"
    # Document order inside the schema stage, both ways round.
    doc = mutated("existing", [S(("session_id",), "a b"), S(("endpoint",), "rti://x:1")])
    assert outcome(doc) == "/session_id"
    reordered = {"endpoint": doc.pop("endpoint"), **doc}
    assert outcome(reordered) == "/endpoint"
    # Document order inside the semantic stage, both ways round.
    doc = mutated("demo", [S(("synthetic",), False), S(("endpoint",), "rti://10.0.0.5:1")])
    assert outcome(doc) == "/synthetic"
    reordered = {"endpoint": doc.pop("endpoint"), **doc}
    assert outcome(reordered) == "/endpoint"
    # A present error before a missing member.
    doc = mutated("existing", [D(("synthetic",)), S(("force_map",), {"1": "friendly"})])
    assert outcome(doc) == "/force_map/1"
    # Two missing members: by name.
    doc = mutated("existing", [D(("synthetic",)), D(("mode",))])
    assert outcome(doc) == "/mode"


# ================================================================================ hostile input

#: (member name, the path it must give): each refused code point replaced by U+FFFD and the
#: name cut to 64 characters before the pointer escapes "~" and "/" (CR-R0-04, CR-R1-04).
HOSTILE_NAMES = [
    ("\x1b[2J", f"/{R}[2J"),
    ("\x00", f"/{R}"),
    ("a\nb", f"/a{R}b"),
    ("\N{RIGHT-TO-LEFT OVERRIDE}x", f"/{R}x"),
    ("\N{ARABIC LETTER MARK}", f"/{R}"),
    ("\N{LEFT-TO-RIGHT ISOLATE}x\N{POP DIRECTIONAL ISOLATE}", f"/{R}x{R}"),
    ("\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}", f"/{R}{R}"),
    ("\x7f\x85\x9f", f"/{R}{R}{R}"),
    ("k" * 10_000, "/" + "k" * 64),
    ("\N{RIGHT-TO-LEFT OVERRIDE}" * 10_000, "/" + R * 64),
    ("a/b~", "/a~1b~0"),
]


@case("G-R07")
@pytest.mark.parametrize("name,path", HOSTILE_NAMES,
                         ids=[f"h{i}" for i in range(len(HOSTILE_NAMES))])
def test_a_hostile_member_name_reaches_every_refusal_path_only_as_safe_text(name, path):
    # schema stage: an unknown member
    doc = base("existing")
    doc[name] = 1
    assert refusal(validate_config, doc).path == path
    assert refusal(load_config_bytes, json.dumps(doc).encode("utf-8")).path == path
    # load stage: the same name twice, and a non-finite number under that name. Written as
    # JSON a name of 10,000 escaped characters makes the file larger than 64 KiB, and the size
    # rule comes first (OPS-06), with the whole document as its path.
    member = json.dumps(name).encode("ascii")
    for data in (b"{" + member + b":1," + member + b":2}", b"{" + member + b":NaN}"):
        expected = path if len(data) <= 65536 else ""
        assert refusal(load_config_bytes, data).path == expected
    # schema stage inside force_map
    doc = base("existing")
    doc["force_map"] = {name: "FRIENDLY"}
    assert refusal(validate_config, doc).path == "/force_map" + path
    # copy stage: an integer beyond 2^53 - 1 under that name, and one Python cannot print
    for value in (2 ** 53, -10 ** 5000):
        doc = base("existing")
        doc[name] = value
        assert refusal(validate_config, doc).path == path


def test_a_lone_surrogate_member_name_is_refused_with_a_safe_path():
    data = b'{"\\ud800": 1}'
    assert refusal(load_config_bytes, data).path == f"/{R}"


# ======================================================================== what comes back, types

@case("G-R07", "G-R08")
def test_the_result_is_a_deep_copy_with_no_default_added():
    """OPS-06: no default enters the result: not for synthetic (R07: an explicit boolean with no
    default), not an epoch (R08: no default epoch, no wall-clock substitution), not an endpoint.
    The source system comes back as written: nothing is inferred from it."""
    for name in ("demo", "existing"):
        original = base(name)
        original["source_system"] = "external-sim-A"
        snapshot = copy.deepcopy(original)
        result = validate_config(original)
        assert result == snapshot and original == snapshot
        assert result is not original
        assert result["time_policy"] is not original["time_policy"]
        assert result["force_map"] is not original["force_map"]
        result["time_policy"]["mode"] = "changed"
        assert original == snapshot
        assert list(result) == list(snapshot)
    # The loader's result too: exactly the members of the file.
    assert set(load_config_bytes(EXISTING_BYTES)) == set(REQUIRED)


class _Name(str):
    pass


@pytest.mark.parametrize("mapping", [
    {1: "x"},
    {"profile": {1, 2}},
    {"force_map": ("1",)},
    {"source_system": b"x"},
    {"source_system": _Name("x")},
    {"time_policy": object()},
])
def test_a_python_value_that_is_not_json_is_a_caller_bug(mapping):
    with pytest.raises(TypeError):
        validate_config(mapping)


@pytest.mark.parametrize("mapping,path", [
    ([], ""), ("text", ""), (None, ""), (1, ""), (True, ""),
    ({"x": float("nan")}, "/x"), ({"x": [float("-inf")]}, "/x/0"),
])
def test_a_json_value_that_is_not_a_configuration_is_e_config(mapping, path):
    assert refusal(validate_config, mapping).path == path


def test_a_self_containing_mapping_is_refused_not_followed_forever():
    doc = base("existing")
    doc["force_map"] = doc
    assert refusal(validate_config, doc).path == ""


# ===================================================================== integers beyond 2^53 - 1

#: Every place a value can stand: each member of R07, the time policy and its three members, the
#: force map and one of its values, a member the schema does not know, and an array element.
INTEGER_PLACES = [
    ("profile",), ("session_id",), ("source_system",), ("synthetic",), ("mode",), ("endpoint",),
    ("allow_remote",), ("federation_name",), ("federate_name",), ("profile_declaration",),
    ("time_policy",), ("time_policy", "mode"), ("time_policy", "epoch"), ("time_policy", "basis"),
    ("force_map",), ("force_map", "1"), ("unknown",), ("unknown", 1),
]
#: 10^4300 has 4301 digits, one more than Python will write as text by default; 10^5000 and its
#: negative are far past it; 2^53 and -2^53 are the first integers past the reader's bound.
BIG_INTEGERS = [10 ** 4300, 10 ** 5000, -10 ** 5000, 2 ** 53, -(2 ** 53)]


def _place(document: dict, place: tuple, value) -> str:
    """Put `value` at `place` in the external_elapsed example and return the pointer to it."""
    if place == ("unknown", 1):
        document["unknown"] = ["first", value]
    else:
        target = document
        for token in place[:-1]:
            target = target[token]
        target[place[-1]] = value
    return "".join(f"/{token}" for token in place)


@case("G-R07")
@pytest.mark.parametrize("value", BIG_INTEGERS, ids=["1e4300", "1e5000", "-1e5000", "2^53",
                                                     "-2^53"])
@pytest.mark.parametrize("place", INTEGER_PLACES, ids=["/".join(map(str, p)) for p in
                                                       INTEGER_PLACES])
def test_an_integer_beyond_2_53_is_refused_at_its_member_by_the_mapping_entry_point(place, value):
    """SPEC:32 and CR-L01: a fatal input error of validate_config is HlaError. A mapping can hold
    an integer no JSON reader of the profile would have produced (CR-new-R2-12 refuses it in the
    file); it is refused at its own pointer before the schema, whose error text would otherwise
    need the integer's decimal form, which Python refuses to write past 4300 digits."""
    document = base("demo")
    pointer = _place(document, place, value)
    assert refusal(validate_config, document).path == pointer


@case("G-R07")
@pytest.mark.parametrize("value,expected", [
    (2 ** 53, "/x"), (-(2 ** 53), "/x"),
    # 2^53 - 1 is the reader's last integer: the member is then only an unknown member, and the
    # schema error earlier in the document (a space in session_id) is the first one.
    (2 ** 53 - 1, "/session_id"), (-(2 ** 53 - 1), "/session_id"),
])
def test_the_integer_bound_is_the_readers_and_comes_before_the_schema(value, expected):
    """Both entry points refuse an integer past 2^53 - 1 before any schema rule, so a schema
    error earlier in the document does not hide it, and they agree on the pointer (`outcome`
    asserts the agreement)."""
    document = mutated("existing", [S(("session_id",), "a b")])
    document["x"] = value
    assert outcome(document) == expected


#: Values a Python caller can hand over that are JSON types but no configuration holds.
_HOSTILE_VALUES = [
    10 ** 5000, -10 ** 5000, 10 ** 4300, 2 ** 53, -(2 ** 53), 2 ** 53 - 1, 0, -1, 1.5, -0.0,
    1e308, float("nan"), float("inf"), float("-inf"), True, False, None, "", "x" * 70_000,
    chr(0xD800), "a" + chr(0xDFFF), "\x00", "\N{RIGHT-TO-LEFT OVERRIDE}", [], {}, [[[[]]]],
    [10 ** 5000], {"k": {"k": -10 ** 5000}}, {"1": 10 ** 5000}, ["FRIENDLY", 2 ** 60],
]


def _deep(levels: int):
    value = []
    for _ in range(levels):
        value = [value]
    return value


def test_hostile_values_anywhere_give_e_config_or_acceptance_and_nothing_else():
    """A deterministic fuzz of the mapping entry point (seeded; 3000 documents): one to three
    hostile values put at existing or new places of both examples, sometimes a member removed,
    sometimes nesting past 32. Each outcome is HlaError E_CONFIG with a pointer, or acceptance
    with a deep copy equal to the input; never any other exception (R2-F1)."""
    rng = random.Random(20261010)
    for _ in range(3000):
        document = base(rng.choice(["demo", "existing"]))
        for _ in range(rng.randint(1, 3)):
            # An earlier mutation may have removed or replaced either nested object.
            containers = [document] + [document[k] for k in ("time_policy", "force_map")
                                       if type(document.get(k)) is dict]
            target = rng.choice(containers)
            roll = rng.random()
            if roll < 0.1 and target:
                del target[rng.choice(sorted(target))]
                continue
            key = rng.choice(sorted(target) + ["1", "256", "x", chr(0xD800), "a/b~"])
            if roll < 0.15:
                target[key] = _deep(rng.choice([31, 32, 33, 40]))
            else:
                target[key] = copy.deepcopy(rng.choice(_HOSTILE_VALUES))
        snapshot = copy.deepcopy(document)
        try:
            result = validate_config(document)
        except HlaError as error:
            assert type(error) is HlaError and error.code == errors.E_CONFIG
            assert error.path == "" or error.path.startswith("/")
        else:
            assert result == snapshot
        assert document == snapshot


@pytest.mark.parametrize("data", ["{}", bytearray(b"{}"), memoryview(b"{}"), None])
def test_the_loader_reads_bytes_only(data):
    with pytest.raises(TypeError):
        load_config_bytes(data)


def test_the_endpoint_rule_agrees_with_the_standard_library_on_the_address_classes():
    """OPS-04 defines loopback as ipaddress.is_loopback (127.0.0.0/8); the rule is written with
    octets, so it is held here to the standard library on the class boundaries."""
    import ipaddress
    for text in ("126.255.255.255", "127.0.0.0", "127.255.255.255", "128.0.0.0",
                 "223.255.255.255", "224.0.0.0", "239.255.255.255", "240.0.0.0",
                 "0.0.0.0", "0.0.0.1", "255.255.255.255", "255.255.255.254"):
        address = ipaddress.IPv4Address(text)
        never = address.is_unspecified or address.is_multicast or text == "255.255.255.255"
        assert config.endpoint_permitted(f"rti://{text}:1", False) == (
            address.is_loopback and not never), text
        assert config.endpoint_permitted(f"rti://{text}:1", True) == (not never), text


# ============================================================ one validation per session (CR-L07)

def test_a_validated_config_comes_only_from_validated_config():
    """CR-L07: the wrapper the projector trusts is built by `validated_config` and nothing else:
    its constructor refuses every call, and `validated_config` gives the document
    `validate_config` gives, read-only, with the canonical bytes (sorted keys, compact, ASCII)
    and the epoch written out by hand here."""
    for args in ((), (base("demo"),), ({},)):
        with pytest.raises(TypeError):
            config.ValidatedConfig(*args)
    made = config.validated_config(base("demo"))
    assert type(made) is config.ValidatedConfig
    assert dict(made.document["time_policy"]) == {
        "mode": "external_elapsed", "epoch": "2026-01-01T00:00:00.000000Z",
        "basis": "Synthetic 1x scenario clock asserted by fixture author"}
    assert dict(made.document["force_map"]) == {"1": "FRIENDLY"}
    assert {k: v for k, v in made.document.items() if k not in ("time_policy", "force_map")} == {
        k: v for k, v in validate_config(base("demo")).items()
        if k not in ("time_policy", "force_map")}
    assert made.canonical == json.dumps(base("demo"), sort_keys=True, separators=(",", ":"),
                                        ensure_ascii=True).encode("ascii")
    # 2026-01-01T00:00:00Z: 20454 days after 1970-01-01 (56 years, 14 of them leap years).
    assert made.epoch_microsecond == 20_454 * 86_400 * 1_000_000
    assert config.validated_config(base("existing")).epoch_microsecond is None


@case("G-R07")
@pytest.mark.parametrize("ops,pointer", [
    ((("set", ("endpoint",), "rti://0127.0.0.1:14321"),), "/endpoint"),
    ((("del", ("synthetic",)),), "/synthetic"),
    ((("set", ("time_policy", "epoch"), "2026-02-30T00:00:00.000000Z"),), "/time_policy/epoch"),
    ((("set", ("source_system",), "a\x07b"),), "/source_system"),
])
def test_validated_config_refuses_what_validate_config_refuses(ops, pointer):
    document = mutated("demo", ops)
    assert refusal(validate_config, document).path == pointer
    assert refusal(config.validated_config, document).path == pointer


def test_validated_config_refuses_a_value_that_is_not_json_as_validate_config_does():
    document = base("demo")
    document["force_map"] = {1: "FRIENDLY"}
    with pytest.raises(TypeError):
        config.validated_config(document)


def test_a_validated_config_cannot_be_changed():
    """Nothing can change what the projector trusts: no attribute can be set or deleted, the
    document and its nested objects refuse assignment, and a later change to the mapping it was
    made from does not reach it."""
    source = base("demo")
    made = config.validated_config(source)
    before = made.canonical
    for name in ("_document", "_canonical", "_epoch", "document", "anything"):
        with pytest.raises(AttributeError):
            setattr(made, name, None)
        with pytest.raises(AttributeError):
            delattr(made, name)
    with pytest.raises(TypeError):
        made.document["session_id"] = "other"
    with pytest.raises(TypeError):
        made.document["force_map"]["2"] = "HOSTILE"
    with pytest.raises(TypeError):
        made.document["time_policy"]["epoch"] = "1970-01-01T00:00:00.000000Z"
    source["force_map"]["2"] = "HOSTILE"
    source["time_policy"]["epoch"] = "1970-01-01T00:00:00.000000Z"
    assert made.canonical == before and "2" not in made.document["force_map"]
    assert made.epoch_microsecond == 20_454 * 86_400 * 1_000_000


def test_a_validated_config_copies_as_itself_compares_by_content_and_is_not_pickled():
    import pickle
    made = config.validated_config(base("demo"))
    assert copy.copy(made) is made and copy.deepcopy(made) is made
    again = config.validated_config(base("demo"))
    assert again is not made and again == made and hash(again) == hash(made)
    assert made != config.validated_config(base("existing"))
    assert (made == base("demo")) is False
    with pytest.raises(TypeError):
        pickle.dumps(made)
