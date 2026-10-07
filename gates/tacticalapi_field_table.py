"""Print the embedded field table of the package's `adapters/tacticalapi_codec.py`, generated from
protoc's own reading of the pinned contract. A build-time tool; nothing in the package imports it.

    python gates/tacticalapi_field_table.py    # prints the table block to stdout

The block printed is the text between (and including) the codec's `# BEGIN GENERATED FIELD
TABLE` and `# END GENERATED FIELD TABLE` lines. To update the codec, replace that block whole
with this output;
`tests/test_cdm_tacticalapi_codec.py::test_embedded_table_matches_the_pinned_descriptor` holds the
two equal byte for byte. Moved here from the adapter's out-of-tree project on 2026-10-06, when
the adapter landed; the record of the table is `docs/tacticalapi-implementation.md` (the record).

THE ORACLE IS PROTOC, NEVER THE ADAPTER'S DECODER
--------------------------------------------------
1. The pinned directory is located through `synapse_cdm.normative_binding.resolve` — the
   environment variable `SYNAPSE_CDM_TACTICALAPI_PROTO_DIR`, the record `proto_pin.json` — so the
   SHA-256 of every one of the ten files is recomputed and held to the record before protoc reads
   any of them. No validator is built (the factory returns None): protoc is the reader here.
2. protoc compiles the ten files, plus the well-known `google/protobuf/any.proto` the envelope of
   the record's §2.1 needs, into a `FileDescriptorSet` (`--include_imports`).
3. protoc itself prints that set as text (`--decode=google.protobuf.FileDescriptorSet
   google/protobuf/descriptor.proto`), and `gates.protoc_text` reads the text. The descriptor's
   bytes are never decoded by `tacticalapi_codec`, so the table cannot be shaped by the decoder
   it feeds.
4. The closure of the two supported responses (and `Any`) is walked from the descriptor and held
   to the list the record's §3.1 names; a difference stops the tool rather than widening the
   table.
5. The decoder reads the table under proto3's rules: an absent scalar is its type's zero, an enum
   is open, no field is required and none has a default of its own. So the tool also stops when a
   closure message or enum comes from a file whose syntax is not proto3 (a proto2 file, whose
   descriptor states no syntax, or an edition), and when a field is `required` or states a
   default value, rather than print a table the decoder would misread.

No comment text is read: protoc is not asked for source info, so the descriptor holds names,
numbers and types only, and only those are printed. Nothing is written to disk: protoc writes the
descriptor set to its standard output and reads it back on its standard input.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    # Run as `python gates/tacticalapi_field_table.py`, the script's own directory is on the path
    # and the repository root is not; `gates.protoc_text` is imported by its package name either
    # way.
    sys.path.insert(0, str(ROOT))

from synapse_cdm import normative_binding  # noqa: E402

from gates import protoc_text  # noqa: E402

ENV_VAR = "SYNAPSE_CDM_TACTICALAPI_PROTO_DIR"
RECORD = "proto_pin.json"
RECORD_FIELDS = ("binding", "edition", "schema_revision", "files")

#: The ten files of the pin, by the record's own names. All ten are verified and compiled, not
#: only the five the closure reaches, so a pin whose other files no longer compile is noticed.
PINNED_FILES = (
    "rheinmetall/tactical_api/v0/blue_force_tracking_service.proto",
    "rheinmetall/tactical_api/v0/blue_force_types.proto",
    "rheinmetall/tactical_api/v0/own_pose_service.proto",
    "rheinmetall/tactical_api/v0/position_types.proto",
    "rheinmetall/tactical_api/v0/service_types.proto",
    "rheinmetall/tactical_api/v0/situation_object_locations.proto",
    "rheinmetall/tactical_api/v0/situation_object_types.proto",
    "rheinmetall/tactical_api/v0/situation_object_updates.proto",
    "rheinmetall/tactical_api/v0/situation_service.proto",
    "rheinmetall/tactical_api/v0/types.proto",
)
WELL_KNOWN_FILES = ("google/protobuf/any.proto",)

PACKAGE = "rheinmetall.tactical_api.v0"
#: The walk starts here: the two responses of the record's §1 and the envelope of §2.1.
ROOTS = (f"{PACKAGE}.GetBlueForcesResponse", f"{PACKAGE}.SubscribeBlueForceEventsResponse",
         "google.protobuf.Any")

#: The record's §3.1, verbatim as a set. The walk from ROOTS must arrive at exactly this.
EXPECTED_MESSAGES = frozenset({
    f"{PACKAGE}.GetBlueForcesResponse", f"{PACKAGE}.SubscribeBlueForceEventsResponse",
    f"{PACKAGE}.ResponseHeader", f"{PACKAGE}.BlueForce", f"{PACKAGE}.BlueForceType",
    f"{PACKAGE}.Identity", f"{PACKAGE}.SymbolIdentifier", f"{PACKAGE}.NumericIdentifier",
    f"{PACKAGE}.Point", f"{PACKAGE}.GeoPoint",
    "google.protobuf.Any", "google.protobuf.Timestamp", "google.protobuf.StringValue",
    "google.protobuf.DoubleValue",
})
EXPECTED_ENUMS = frozenset({
    f"{PACKAGE}.SymbolCatalog", f"{PACKAGE}.VerticalDistanceReferenceCode",
    f"{PACKAGE}.MeasurementCode",
})

#: descriptor `type` -> the table's kind. Only the kinds the decoder implements are here; any
#: other kind in the closure stops the tool (the decoder would have no reading for it).
KINDS = {
    "TYPE_BOOL": "bool", "TYPE_INT32": "int32", "TYPE_INT64": "int64", "TYPE_DOUBLE": "double",
    "TYPE_STRING": "string", "TYPE_BYTES": "bytes", "TYPE_ENUM": "enum", "TYPE_MESSAGE": "message",
}

#: Where protoc is looked for when it is not on PATH (Homebrew's protoc 36.2, the build the
#: fixture pin records).
PROTOC_FALLBACK = "/opt/homebrew/bin/protoc"

BEGIN = "# BEGIN GENERATED FIELD TABLE"
END = "# END GENERATED FIELD TABLE"


class ProtocUnavailable(RuntimeError):
    """protoc, or the well-known-type includes beside it, is not in this environment. The test
    that needs it reports `BLOCKED_EXTERNAL_EVIDENCE` rather than a pass."""

    status = normative_binding.BLOCKED_STATUS


class ClosureMismatch(RuntimeError):
    """The descriptor does not support the table the record's §3.1 describes."""


def locate_protoc() -> tuple[pathlib.Path, pathlib.Path]:
    """protoc and its include directory (`<prefix>/include`, holding google/protobuf/*.proto)."""
    for candidate in (shutil.which("protoc"), PROTOC_FALLBACK):
        if not candidate:
            continue
        protoc = pathlib.Path(candidate)
        include = protoc.parent.parent / "include"
        if protoc.is_file() and (include / "google/protobuf/descriptor.proto").is_file():
            return protoc, include
    raise ProtocUnavailable("protoc with its google/protobuf includes is not on PATH and not at "
                            f"{PROTOC_FALLBACK}")


def resolve_pin(environ=None) -> normative_binding.LocalSchemaResource:
    """The verified pin directory, or `NormativeBindingBlocked` naming the step that failed."""
    return normative_binding.resolve(env_var=ENV_VAR, record_name=RECORD, files=list(PINNED_FILES),
                                     fields=list(RECORD_FIELDS), environ=environ,
                                     validator_factory=lambda path: None)


def pin_commit(record: dict) -> str:
    """The upstream commit the record pins, read from its `schema_revision`."""
    found = re.findall(r"\b[0-9a-f]{40}\b", str(record.get("schema_revision", "")))
    if len(found) != 1:
        raise ClosureMismatch(f"{RECORD} schema_revision names {len(found)} full commit ids; "
                              "exactly one was expected")
    return found[0]


def descriptor_text(directory: pathlib.Path, protoc: pathlib.Path, include: pathlib.Path) -> str:
    """protoc's text rendering of the FileDescriptorSet of the pinned files and `any.proto`."""
    compiled = subprocess.run(
        [str(protoc), f"-I{directory}", f"-I{include}", "--include_imports",
         "--descriptor_set_out=/dev/stdout", *PINNED_FILES, *WELL_KNOWN_FILES],
        capture_output=True, check=False)
    if compiled.returncode != 0:
        raise RuntimeError(f"protoc could not compile the pinned files: "
                           f"{compiled.stderr.decode('utf-8', 'replace')}")
    printed = subprocess.run(
        [str(protoc), f"-I{include}", "--decode=google.protobuf.FileDescriptorSet",
         "google/protobuf/descriptor.proto"],
        input=compiled.stdout, capture_output=True, check=False)
    if printed.returncode != 0:
        raise RuntimeError(f"protoc could not print the descriptor set: "
                           f"{printed.stderr.decode('utf-8', 'replace')}")
    return printed.stdout.decode("utf-8")


def index(descriptor_set: list) -> tuple[dict[str, list], dict[str, list], dict[str, str]]:
    """Every message and enum of the set by full name (no leading dot), nested ones included,
    and the syntax of the file that defines each: the file's `syntax` as protoc prints it, or ""
    when it prints none, which is how a proto2 file's descriptor reads."""
    messages: dict[str, list] = {}
    enums: dict[str, list] = {}
    syntax: dict[str, str] = {}

    def walk_message(prefix: str, message: list, file_syntax: str) -> None:
        name = f"{prefix}.{protoc_text.text(message, 'name')}"
        if name in messages:
            raise ClosureMismatch(f"message {name} is defined twice in the descriptor set")
        messages[name] = message
        syntax[name] = file_syntax
        for nested in protoc_text.values(message, "nested_type"):
            walk_message(name, nested, file_syntax)
        for nested in protoc_text.values(message, "enum_type"):
            enums[f"{name}.{protoc_text.text(nested, 'name')}"] = nested
            syntax[f"{name}.{protoc_text.text(nested, 'name')}"] = file_syntax

    for file in protoc_text.values(descriptor_set, "file"):
        package = protoc_text.text(file, "package", "")
        file_syntax = protoc_text.text(file, "syntax", "")
        for message in protoc_text.values(file, "message_type"):
            walk_message(package, message, file_syntax)
        for enum in protoc_text.values(file, "enum_type"):
            enums[f"{package}.{protoc_text.text(enum, 'name')}"] = enum
            syntax[f"{package}.{protoc_text.text(enum, 'name')}"] = file_syntax
    return messages, enums, syntax


def proto3_only(names: list[str], syntax: dict[str, str]) -> None:
    """Stop unless every one of `names` comes from a proto3 file. Under proto2 an absent scalar
    has a presence of its own and may have a default, and under an edition the features decide
    both; the decoder reads neither, so a table it would read under the wrong rules is not
    printed."""
    other = [f"{name} ({syntax[name] or 'no syntax stated, which is proto2'})"
             for name in sorted(names) if syntax[name] != "proto3"]
    if other:
        raise ClosureMismatch(f"the decoder reads proto3 only, and these come from a file of "
                              f"another syntax: {other}")


def closure(messages: dict[str, list]) -> tuple[list[str], list[str]]:
    """The messages and enums reachable from ROOTS through message- and enum-typed fields."""
    seen_messages: set[str] = set()
    seen_enums: set[str] = set()
    pending = list(ROOTS)
    while pending:
        name = pending.pop()
        if name in seen_messages:
            continue
        if name not in messages:
            raise ClosureMismatch(f"{name} is referenced and not defined in the descriptor set")
        seen_messages.add(name)
        for field in protoc_text.values(messages[name], "field"):
            target = protoc_text.text(field, "type_name")
            kind = protoc_text.single(field, "type")
            if kind == "TYPE_MESSAGE":
                pending.append(target.lstrip("."))
            elif kind == "TYPE_ENUM":
                seen_enums.add(target.lstrip("."))
    return sorted(seen_messages), sorted(seen_enums)


#: What a name printed into the table may look like. A descriptor name is an identifier, a dotted
#: path of identifiers, or nothing; holding every printed name to this pattern is what keeps the
#: block to names and numbers (no quote, no space, no sentence can pass it).
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


def literal(name: str | None) -> str:
    """A name as a double-quoted Python literal (the package's quoting), or `None`."""
    if name is None:
        return "None"
    if not _NAME.fullmatch(name):
        raise ClosureMismatch(f"{name!r} is not an identifier or a dotted path of identifiers")
    return f'"{name}"'


def field_rows(name: str, message: list) -> list[tuple[int, str]]:
    """`(number, source line)` for every field of one message, refusing what the decoder cannot
    read: a kind outside KINDS, a repeated non-message field, a proto3 `optional` field, a
    `required` field and a field with a default value (neither exists in proto3, and the decoder
    reads an absent scalar as its type's zero, never as a stated default)."""
    oneofs = [protoc_text.text(decl, "name") for decl in protoc_text.values(message, "oneof_decl")]
    rows = []
    for field in protoc_text.values(message, "field"):
        field_name = protoc_text.text(field, "name")
        number = protoc_text.single(field, "number")
        kind_word = str(protoc_text.single(field, "type"))
        label = str(protoc_text.single(field, "label"))
        if kind_word not in KINDS:
            raise ClosureMismatch(f"{name}.{field_name} is {kind_word}; the decoder implements "
                                  f"{sorted(KINDS)} only")
        if protoc_text.single(field, "proto3_optional") is not None:
            raise ClosureMismatch(f"{name}.{field_name} is a proto3 `optional` field; its "
                                  "synthetic oneof is not modelled by the decoder")
        if label == "LABEL_REQUIRED":
            raise ClosureMismatch(f"{name}.{field_name} is a required field; the decoder reads "
                                  "proto3, where no field is required and none is refused for "
                                  "being absent")
        if protoc_text.single(field, "default_value") is not None:
            raise ClosureMismatch(f"{name}.{field_name} states a default value; the decoder "
                                  "reads an absent scalar as its type's zero, as proto3 does")
        kind = KINDS[kind_word]
        repeated = label == "LABEL_REPEATED"
        if repeated and kind != "message":
            raise ClosureMismatch(f"{name}.{field_name} is a repeated {kind}; the decoder reads "
                                  "repeated message fields only (no packed scalars occur in the "
                                  "closure)")
        target = protoc_text.text(field, "type_name")
        type_name = target.lstrip(".") if target else None
        oneof_index = protoc_text.single(field, "oneof_index")
        oneof = oneofs[oneof_index] if oneof_index is not None else None
        rows.append((number, f"        {number}: Field({literal(field_name)}, {literal(kind)}, "
                             f"{literal(type_name)}, {repeated!r}, {literal(oneof)}),"))
    numbers = [number for number, _ in rows]
    if len(set(numbers)) != len(numbers):
        raise ClosureMismatch(f"{name} defines a field number twice")
    return sorted(rows)


def enum_rows(name: str, enum: list) -> list[tuple[int, str]]:
    """`(number, source line)` for every value of one enum; an alias (two names, one number)
    stops the tool, since the twin names a number by exactly one name."""
    rows = {}
    for value in protoc_text.values(enum, "value"):
        number = protoc_text.single(value, "number")
        if number in rows:
            raise ClosureMismatch(f"{name} gives {number} two names; the twin needs one")
        rows[number] = f"        {number}: {literal(protoc_text.text(value, 'name'))},"
    return sorted(rows.items())


def render(commit: str, message_names: list[str], enum_names: list[str],
           messages: dict[str, list], enums: dict[str, list]) -> str:
    """The table block, deterministic: messages and enums by full name, rows by number."""
    lines = [
        BEGIN,
        "# Generated by gates/tacticalapi_field_table.py from protoc's descriptor of the pinned "
        "contract,",
        f"# upstream commit {commit}. Not edited by hand: regenerate it",
        "# and replace this block whole. Names and numbers only.",
        "MESSAGES: dict[str, dict[int, Field]] = {",
    ]
    for name in message_names:
        lines.append(f"    {literal(name)}: {{")
        lines.extend(line for _, line in field_rows(name, messages[name]))
        lines.append("    },")
    lines.append("}")
    lines.append("ENUMS: dict[str, dict[int, str]] = {")
    for name in enum_names:
        lines.append(f"    {literal(name)}: {{")
        lines.extend(line for _, line in enum_rows(name, enums[name]))
        lines.append("    },")
    lines.append("}")
    lines.append(END)
    return "\n".join(lines) + "\n"


def generate(environ=None) -> str:
    """The table block for the pin `environ` (default `os.environ`) names. Raises
    `NormativeBindingBlocked` when the pin does not verify and `ProtocUnavailable` when protoc is
    absent; both are BLOCKED_EXTERNAL_EVIDENCE, never a table."""
    resource = resolve_pin(environ)
    protoc, include = locate_protoc()
    commit = pin_commit(resource.record)
    descriptor_set = protoc_text.parse(descriptor_text(resource.directory, protoc, include))
    messages, enums, syntax = index(descriptor_set)
    message_names, enum_names = closure(messages)
    if set(message_names) != EXPECTED_MESSAGES or set(enum_names) != EXPECTED_ENUMS:
        raise ClosureMismatch(
            "the closure of the two responses is not the one §3.1 of "
            "docs/tacticalapi-implementation.md names: "
            f"messages extra {sorted(set(message_names) - EXPECTED_MESSAGES)}, "
            f"missing {sorted(EXPECTED_MESSAGES - set(message_names))}; "
            f"enums extra {sorted(set(enum_names) - EXPECTED_ENUMS)}, "
            f"missing {sorted(EXPECTED_ENUMS - set(enum_names))}")
    proto3_only(message_names + enum_names, syntax)
    return render(commit, message_names, enum_names, messages, enums)


def main() -> int:
    try:
        block = generate(os.environ)
    except (normative_binding.NormativeBindingBlocked, ProtocUnavailable) as blocked:
        print(f"{normative_binding.BLOCKED_STATUS}: {blocked}", file=sys.stderr)
        return 3
    sys.stdout.write(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
