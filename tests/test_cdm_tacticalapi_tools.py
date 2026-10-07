"""The `tacticalapi` adapter's build-time helpers under `gates/`, tested on their own, because the
other checks build on them: `gates.protoc_text` reads protoc's text output for the fixture tests'
independent readings as well as for the field table, `gates.tacticalapi_field_table` decides what
counts as BLOCKED_EXTERNAL_EVIDENCE, and `gates.tacticalapi_contract_comments` decides what the
comment-literal gate looks for. None of these tests needs protoc or the pinned files. Moved from
the adapter's out-of-tree project (`tools/`) on 2026-10-06, when the adapter landed.
"""
from __future__ import annotations

import json
import pathlib

import pytest
from synapse_cdm.normative_binding import BLOCKED_STATUS, NormativeBindingBlocked

from gates import protoc_text
from gates import tacticalapi_contract_comments as contract_comments
from gates import tacticalapi_field_table as gen_field_table
from gates.protoc_text import Identifier, TextFormatError


def test_the_text_reader_reads_what_protoc_prints():
    text = """
    # a comment
    file {
      name: "a/b.proto"
      message_type {
        name: "M"
        field { name: "x" number: 1 label: LABEL_OPTIONAL type: TYPE_INT64 oneof_index: 0 }
      }
    }
    file < name: 'c.proto' >
    """
    parsed = protoc_text.parse(text)
    files = protoc_text.values(parsed, "file")
    assert len(files) == 2
    assert protoc_text.text(files[0], "name") == "a/b.proto"
    field = protoc_text.single(protoc_text.single(files[0], "message_type"), "field")
    assert field == [("name", b"x"), ("number", 1), ("label", "LABEL_OPTIONAL"),
                     ("type", "TYPE_INT64"), ("oneof_index", 0)]
    assert isinstance(protoc_text.single(field, "label"), Identifier)
    assert protoc_text.text(files[1], "name") == "c.proto"


def test_the_text_reader_reads_decode_output_scalars_and_names():
    """What `protoc --decode` prints for a payload: negative and floating numbers, `inf`/`nan`
    as words, a field the type does not name as its bare number, an expanded Any's bracketed
    name, octal escapes for non-ASCII octets, and adjacent strings joined."""
    text = r"""
    seconds: -62135596800
    latitude_coordinate: 52.52
    big: 1e+30
    hex: 0x1F
    speed: -inf
    course: nan
    15: 7
    99: "abc"
    [type.googleapis.com/x.Y] { value: "EXERCISE \303\244" "!" }
    quoted: "a\"b\\c\n\x41\101"
    """
    parsed = protoc_text.parse(text)
    assert protoc_text.single(parsed, "seconds") == -62135596800
    assert protoc_text.single(parsed, "latitude_coordinate") == 52.52
    assert protoc_text.single(parsed, "big") == 1e30
    assert protoc_text.single(parsed, "hex") == 31
    assert protoc_text.single(parsed, "speed") == "-inf"
    assert protoc_text.single(parsed, "course") == "nan"
    assert protoc_text.single(parsed, "15") == 7
    assert protoc_text.single(parsed, "99") == b"abc"
    expanded = protoc_text.single(parsed, "[type.googleapis.com/x.Y]")
    assert protoc_text.text(expanded, "value") == "EXERCISE ä!"
    assert protoc_text.single(parsed, "quoted") == b'a"b\\c\nAA'


@pytest.mark.parametrize("text", [
    "name: ",                 # no value
    "name {",                 # unclosed
    "name 7",                 # neither ':' nor a body
    "}",                      # a close with nothing open
    'name: "\\q"',            # an unknown escape
    "name: @",                # an unreadable character
])
def test_the_text_reader_refuses_what_it_does_not_read(text):
    with pytest.raises(TextFormatError):
        protoc_text.parse(text)


def test_single_refuses_a_repeated_name():
    with pytest.raises(TextFormatError, match="2 times"):
        protoc_text.single(protoc_text.parse("a: 1 a: 2"), "a")


def test_an_absent_protoc_is_blocked_external_evidence(monkeypatch):
    # A path that does not exist (nothing is created): PATH finds nothing and neither does this.
    absent = pathlib.Path(__file__).parent / "no-such-directory" / "bin" / "protoc"
    assert not absent.exists()
    monkeypatch.setattr(gen_field_table.shutil, "which", lambda name: None)
    monkeypatch.setattr(gen_field_table, "PROTOC_FALLBACK", str(absent))
    with pytest.raises(gen_field_table.ProtocUnavailable) as blocked:
        gen_field_table.locate_protoc()
    assert blocked.value.status == BLOCKED_STATUS


@pytest.mark.parametrize("name", ["a b", 'x"', "1abc", "a..b", "", "a.", "#"])
def test_a_printed_name_is_an_identifier_or_a_dotted_path(name):
    with pytest.raises(gen_field_table.ClosureMismatch):
        gen_field_table.literal(name)


def test_printed_names_are_double_quoted():
    assert gen_field_table.literal("rheinmetall.tactical_api.v0.Point") == \
        '"rheinmetall.tactical_api.v0.Point"'
    assert gen_field_table.literal(None) == "None"


def test_the_pin_commit_is_the_one_full_commit_id_in_schema_revision():
    commit = "0123456789abcdef0123456789abcdef01234567"
    assert gen_field_table.pin_commit({"schema_revision": f"repo commit {commit} (main)"}) == commit
    with pytest.raises(gen_field_table.ClosureMismatch):
        gen_field_table.pin_commit({"schema_revision": "commit 58661c9"})


#: A synthetic descriptor set as protoc prints one: a proto2 file (protoc states no syntax for
#: it), a proto3 file with a nested message and enum, and an editions file.
SYNTAX_DESCRIPTOR = """
file { name: "two.proto" package: "x" message_type { name: "Two" } }
file {
  name: "three.proto" package: "x" syntax: "proto3"
  message_type { name: "Three" nested_type { name: "Inner" }
                 enum_type { name: "E" value { name: "E_0" number: 0 } } }
}
file {
  name: "edition.proto" package: "x" syntax: "editions" edition: EDITION_2023
  enum_type { name: "Ed" value { name: "ED_0" number: 0 } }
}
"""


def test_the_generator_refuses_a_closure_file_whose_syntax_is_not_proto3():
    """The decoder reads proto3 only (the record's §3.1, `docs/tacticalapi-implementation.md`), so a closure message or enum from a
    proto2 or editions file stops the tool, whatever its names (added 2026-10-04, final
    verification)."""
    messages, enums, syntax = gen_field_table.index(protoc_text.parse(SYNTAX_DESCRIPTOR))
    assert set(messages) == {"x.Two", "x.Three", "x.Three.Inner"}
    assert set(enums) == {"x.Three.E", "x.Ed"}
    assert syntax == {"x.Two": "", "x.Three": "proto3", "x.Three.Inner": "proto3",
                      "x.Three.E": "proto3", "x.Ed": "editions"}
    gen_field_table.proto3_only(["x.Three", "x.Three.Inner", "x.Three.E"], syntax)
    with pytest.raises(gen_field_table.ClosureMismatch, match="no syntax stated, which is proto2"):
        gen_field_table.proto3_only(["x.Three", "x.Two"], syntax)
    with pytest.raises(gen_field_table.ClosureMismatch, match=r"x\.Ed \(editions\)"):
        gen_field_table.proto3_only(["x.Ed", "x.Three.E"], syntax)


def one_field(text: str) -> list:
    """A synthetic message `M` holding one field, as protoc prints a DescriptorProto."""
    return protoc_text.parse(f'name: "M" field {{ name: "a" number: 1 {text} }}')


def test_the_generator_reads_a_proto3_singular_field():
    assert gen_field_table.field_rows("x.M", one_field("label: LABEL_OPTIONAL type: TYPE_INT32")) \
        == [(1, '        1: Field("a", "int32", None, False, None),')]


def test_the_generator_refuses_a_required_field():
    with pytest.raises(gen_field_table.ClosureMismatch, match="x.M.a is a required field"):
        gen_field_table.field_rows("x.M", one_field("label: LABEL_REQUIRED type: TYPE_INT32"))


def test_the_generator_refuses_a_field_with_a_default_value():
    with pytest.raises(gen_field_table.ClosureMismatch, match="x.M.a states a default value"):
        gen_field_table.field_rows("x.M", one_field(
            'label: LABEL_OPTIONAL type: TYPE_INT32 default_value: "7"'))


# ------------------------------------------------------- gates.tacticalapi_contract_comments

def test_the_comment_splitter_keeps_strings_in_the_code():
    # `//` inside a string is code; a line comment ends at its newline, which stays in the code;
    # a block comment leaves one space, so `a/*x*/b` is two literals, not `ab`; an escaped quote
    # does not close a string.
    assert contract_comments.split('a = "x // y"; // z\n/* w */b') == \
        ('a = "x // y"; \n b', " z\n w ")
    assert contract_comments.split("a/*x*/b") == ("a b", "x")
    assert contract_comments.split("o = 'p\\'q'; // r") == ("o = 'p\\'q'; ", " r")
    assert contract_comments.split('s = "a\\"b" // c') == ('s = "a\\"b" ', " c")


@pytest.mark.parametrize("source", ["/* never closed", 'a = "never closed', 'a = "line\nbreak"'])
def test_the_comment_splitter_refuses_what_it_cannot_tell_apart(source):
    with pytest.raises(contract_comments.UnreadableSource):
        contract_comments.split(source)


def test_a_distinctive_literal_has_eight_characters_and_a_digit():
    assert contract_comments.MIN_LENGTH == 8
    assert contract_comments.distinctive("exercis1")
    assert not contract_comments.distinctive("exerci1")
    assert not contract_comments.distinctive("exercise")
    assert contract_comments.literals("A-1.b:c/D_2 e--f x. Y") == \
        {"a-1.b:c/d_2", "e", "f", "x", "y"}


def test_the_digests_file_is_the_commit_and_sorted_unique_fingerprints():
    commit = "0123456789abcdef0123456789abcdef01234567"
    text = contract_comments.render(commit, ["exercise-0002", "EXERCISE-0001", "exercise-0001"])
    record = json.loads(text)
    assert list(record) == ["commit", "sha256"] and record["commit"] == commit
    assert record["sha256"] == sorted({contract_comments.fingerprint("exercise-0001"),
                                       contract_comments.fingerprint("exercise-0002")})
    assert text == json.dumps(record, indent=2) + "\n"


def test_a_fingerprint_is_the_sha256_evidence_digest_gives():
    """The fingerprint goes through `synapse_cdm.evidence.digest` (no file of the adapter imports
    `hashlib`, which the package keeps to `synapse_cdm/evidence.py`); the
    expected values are the published SHA-256 test vectors, so the route changes no digest."""
    assert contract_comments.fingerprint("") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    assert contract_comments.fingerprint("ABC") == contract_comments.fingerprint("abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_the_comment_tool_refuses_an_unset_pin_rather_than_reading_anything():
    with pytest.raises(NormativeBindingBlocked) as blocked:
        contract_comments.generate(environ={})
    assert blocked.value.step == "hook"


def test_the_scans_read_the_adapters_own_files_and_never_the_whole_repository():
    """Re-scoped on 2026-10-06, when the tool moved into the repository: out of tree it read every
    file of the project; here `arc_files` reads the files `ARC_FILES` names and nothing else, so
    the prose check and the literal scan judge the adapter's own files, and the repository's other
    files, which were never compared with the contract's comments, are not walked."""
    root = pathlib.Path(__file__).resolve().parents[1]
    found = {path.relative_to(root).as_posix() for path in contract_comments.arc_files(root)}
    for expected in ("packages/cdm/synapse_cdm/adapters/tacticalapi.py",
                     "packages/cdm/synapse_cdm/adapters/tacticalapi_codec.py",
                     "packages/cdm/synapse_cdm/fixtures/tacticalapi/README.md",
                     "packages/cdm/synapse_cdm/fixtures/tacticalapi/spec/build_fixtures.py",
                     "gates/protoc_text.py", "gates/tacticalapi_field_table.py",
                     "gates/tacticalapi_contract_comments.py", "tests/tacticalapi_protowire.py",
                     "tests/test_cdm_tacticalapi_tools.py", "NOTICE", "packages/cdm/NOTICE"):
        assert expected in found, expected
    for outside in ("README.md", "packages/cdm/synapse_cdm/adapters/dis7.py",
                    "packages/cdm/synapse_cdm/fixtures/dis7/README.md", "gates/wheel_install.py",
                    "tests/test_cdm_lossless.py"):
        assert outside not in found, outside
    assert not [name for name in found if "__pycache__" in name or name.endswith(".pyc")]
