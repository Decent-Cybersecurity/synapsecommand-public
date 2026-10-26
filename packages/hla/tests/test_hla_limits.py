"""The fixed v1 limits against the table at SPEC:217-231 and the paragraphs that add bounds.

The expected numbers are written as literals with the arithmetic beside them; nothing is read
back from `synapse_hla.limits` except the object under test.
"""

import ast
import dataclasses
import pathlib

import pytest

from hla_support import case
from synapse_hla import limits
from synapse_hla.limits import V1, Limits

#: field -> (value, where the specification fixes it). Binary multiples: 1 KiB = 1024 bytes,
#: 1 MiB = 1024 * 1024 = 1048576 bytes, 1 GiB = 1024 * 1048576 = 1073741824 bytes.
EXPECTED = (
    ("active_objects_per_generation", 10000, "SPEC:218"),
    ("object_tokens_per_session", 100000, "SPEC:219"),
    ("attributes_per_reflection", 4, "SPEC:220"),
    ("attribute_value_bytes", 4096, "SPEC:221"),
    ("user_tag_bytes", 4096, "SPEC:222"),
    ("object_name_utf8_bytes", 1024, "SPEC:223"),
    ("class_name_utf8_bytes", 1024, "SPEC:224"),
    ("logical_time_bytes", 256, "SPEC:225"),
    ("line_bytes", 65536, "SPEC:226"),
    ("queue_frames", 4096, "SPEC:227"),
    ("queue_bytes", 16777216, "SPEC:227, 16 MiB"),
    ("cached_attribute_bytes_per_generation", 33554432, "SPEC:228, 32 MiB"),
    ("capture_file_bytes", 1073741824, "SPEC:229, 1 GiB"),
    ("frames_per_session", 10000000, "SPEC:230"),
    ("dependency_xml_bytes", 2097152, "SPEC:231, 2 MiB"),
    ("dependency_xml_depth", 64, "SPEC:231"),
    ("config_file_bytes", 65536, "R07 (SPEC:36), 64 KiB"),
    ("capture_reserve_bytes", 65536, "SPEC:293"),
    ("diagnostic_message_utf8_bytes", 1024, "R37 (SPEC:188)"),
    ("worker_rss_bytes", 536870912, "R41 (SPEC:233), 512 MiB"),
    ("host_rss_bytes", 536870912, "R41 (SPEC:233), 512 MiB"),
    ("error_message_chars", 256, "CR-L01"),
    ("error_message_input_chars", 64, "CR-L01"),
)


def test_the_fields_are_exactly_the_expected_ones_in_order():
    assert [f.name for f in dataclasses.fields(Limits)] == [name for name, _, _ in EXPECTED]


@pytest.mark.parametrize("name,value,source", EXPECTED, ids=[n for n, _, _ in EXPECTED])
@case("G-R40", paragraphs=("SPEC:217",))
def test_each_v1_value_is_the_specifications(name, value, source):
    got = getattr(V1, name)
    assert type(got) is int
    assert got == value, f"{name} is fixed by {source}"


def test_v1_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        V1.line_bytes = 1


@pytest.mark.parametrize("bad", [0, -1, True, 1.0, "4096", None])
def test_a_variant_with_a_non_positive_or_non_int_limit_is_refused(bad):
    with pytest.raises(ValueError):
        dataclasses.replace(V1, attribute_value_bytes=bad)


def test_a_test_variant_can_lower_one_limit_and_keeps_the_rest():
    small = dataclasses.replace(V1, active_objects_per_generation=2)
    assert small.active_objects_per_generation == 2
    assert small.line_bytes == 65536 and V1.active_objects_per_generation == 10000


#: The limit values large and distinctive enough that a literal of one elsewhere in the package
#: is almost certainly a second definition of a limit. 4, 64 and 256 are left out: they are also
#: a count of attributes, the length of a hex digest and a byte range.
DISTINCTIVE = {10000, 100000, 4096, 1024, 65536, 16777216, 33554432, 1073741824, 10000000,
               2097152, 536870912}

SRC = pathlib.Path(limits.__file__).resolve().parent


def test_no_other_module_of_the_package_writes_a_limit_number():
    """No other module defines a limit number (limits.py says why); held here mechanically."""
    found = []
    for path in sorted(SRC.rglob("*.py")):
        if path.name == "limits.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Constant) and type(node.value) is int
                    and node.value in DISTINCTIVE):
                found.append(f"{path.name}:{node.lineno}: {node.value}")
    assert not found, found
