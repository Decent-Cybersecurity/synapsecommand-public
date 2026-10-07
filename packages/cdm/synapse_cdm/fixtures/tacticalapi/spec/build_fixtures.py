#!/usr/bin/env python3
"""Build the TacticalAPI fixture set with protoc. THE SOURCE OF TRUTH FOR EVERY GENERATED FILE HERE.

    python build_fixtures.py            # writes every generated file under fixtures/tacticalapi/
    python build_fixtures.py --check    # regenerates everything in memory and compares it, byte
                                        # for byte, with the tree; exit 1 naming every file that
                                        # differs, is missing or is extra

Both need protoc and the pinned contract: `SYNAPSE_CDM_TACTICALAPI_PROTO_DIR` names the directory
and `synapse_cdm.normative_binding.resolve` holds all ten interface definition files to the
SHA-256 values of their record before protoc reads any of them. Without either the script prints
BLOCKED_EXTERNAL_EVIDENCE and exits 3; it never writes a guess. Edit this file, never a `.binpb`,
a twin, a reading, a provenance record or the pin. `README.md` beside the payloads and this
script are the only hand-written files in the set, and `golden/` is the harness's.

WHAT THIS BUILDS, AND FROM WHAT
-------------------------------
Every case below is a text-format source held here as a literal (`CASES`). The script copies it
to `sources/<case>.txtpb` and hands it to `protoc --encode=google.protobuf.Any`, which writes the
payload: the `Any` envelope the implementation record (`docs/tacticalapi-implementation.md` of the
repository) reads in §2.1, with the response inside it. protoc is the
INDEPENDENT IMPLEMENTATION: it wrote every octet of every payload except the few a case states it
appends, cuts or rewrites (and the lengths re-encoded around them), and the adapter's decoder had
no hand in any of them. protoc is also the
independent READER: `independent/<case>.any.txtpb` is `protoc --decode=google.protobuf.Any` of the
whole payload, and `independent/<case>.value.txtpb` is `protoc --decode` of the envelope's value
as the type its type_url names. Two readings, because protoc's printer does not expand an `Any`.
The `.parsed.json` twin beside each harness and `cases/` payload is the decoder's rendering
(`tacticalapi_codec.decode`); `tests/test_cdm_tacticalapi_fixtures.py` reads every twin against
protoc's readings and against the source literal, so the decoder is never its own oracle.

THE TWO THINGS PROTOC WILL NOT WRITE
------------------------------------
1. A field the type does not define. The text form names fields by name, so an unknown field
   cannot be stated in a source. The three payloads that need one (two in `cases/`, and the
   harness fixture `snapshot_with_unknown_fields`, which is `cases/unknown_field_carried` under a
   name the harness selects) get it as an `Append`:
   hand-encoded octets put at the end of the message a twin path names, every enclosing length
   re-encoded (`within`). Only wire types 0 and 2 are appended: protoc prints an unknown fixed32
   or fixed64 field as hexadecimal, which the tests' text reader reads as a plain number, so the
   wire type could not be read back from protoc's reading. The codec tests carry all four.
2. Malformed data. protoc refuses to encode it, so four of the eight `malformed/` payloads are
   protoc's bytes changed afterwards by one `Surgery` each, a function below named for what it
   breaks and described in the pin and in README.md. The other four are protoc's own encoding of
   a message that is well formed and refused only for what it says.

WHAT PROTOC WRITES DIFFERENTLY FROM WHAT A SOURCE SAYS
------------------------------------------------------
protoc writes no proto3 scalar that holds its default unless it is a oneof member: a source's
`success: false` or `latitude_coordinate: 0` never reaches the wire, and a reader sees the field
as absent, which the contract defines as the default. A message field is written whenever it is
set, so `course { value: 0 }` is a present wrapper whose value is 0, and `int32_identity: 0`, a
oneof member, is written. The sources say what they mean and the comment in each says what the
wire holds.

DETERMINISM
-----------
No clock, host name or absolute path reaches an output: the date below is a literal, the commands
in the pin name their inputs by placeholder, and protoc's output depends on its input alone. The
pin records protoc's version; a protoc build that encodes or prints differently is a new pin, not
a defect, and --check names every file that moved.

EVERYTHING IS SYNTHETIC. Every name carries the word EXERCISE, every UUID is the uuid5 of an
EXERCISE name, every position is invented (a Baltic exercise area off the Courland coast, and one
point on the equator in the Gulf of Guinea where a zero latitude is the point), and nothing
derives from recorded data.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import re
import shutil
import struct
import subprocess
import sys
from typing import Callable, NamedTuple

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE.parent
if str(FIXTURES.parents[2]) not in sys.path:
    # Run as `python build_fixtures.py`, the package is not on the path unless it is installed or
    # the caller put it there; the directory that holds `synapse_cdm` is put first, so the codec
    # this script imports is the one beside these fixtures, by its package name either way.
    sys.path.insert(0, str(FIXTURES.parents[2]))

from synapse_cdm import evidence, normative_binding  # noqa: E402
from synapse_cdm.adapters import tacticalapi_codec as codec  # noqa: E402

PIN = HERE / "tacticalapi_pin.json"
#: The date every file here was first written. A literal, never the clock.
WRITTEN_ON = "2026-10-04"

#: The two files of the set that this script does not write, and the harness's directory.
HAND_WRITTEN = ("README.md", "spec/build_fixtures.py")
GOLDEN = "golden"

# --------------------------------------------------------------------------- the pinned contract

ENV_VAR = "SYNAPSE_CDM_TACTICALAPI_PROTO_DIR"
RECORD = "proto_pin.json"
RECORD_FIELDS = ("binding", "edition", "schema_revision", "files")
#: All ten files of the pin, verified and handed to protoc, as `gates/tacticalapi_field_table.py`
#: does (a test holds the two lists equal). The script stays free of the repository's `gates/`
#: package, which an installed package does not have.
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
#: The envelope's own definition, from the includes that ship with protoc.
WELL_KNOWN_FILES = ("google/protobuf/any.proto",)
#: Where protoc is looked for when it is not on PATH (Homebrew's protoc 36.2, the build recorded in
#: the pin).
PROTOC_FALLBACK = "/opt/homebrew/bin/protoc"
#: The conventional `type_url` prefix; the implementation record's §2.1 carries it verbatim and
#: checks nothing of it.
URL_PREFIX = "type.googleapis.com/"


class ProtocUnavailable(RuntimeError):
    """protoc, or the well-known-type includes beside it, is not in this environment. Reported as
    BLOCKED_EXTERNAL_EVIDENCE, never as a build."""

    status = normative_binding.BLOCKED_STATUS


class BuildError(RuntimeError):
    """protoc refused a source it should accept, or a surgery found octets it did not expect. The
    build stops rather than write around it."""


def resolve_pin(environ=None) -> normative_binding.LocalSchemaResource:
    """The verified contract directory, or `NormativeBindingBlocked` naming the step that failed.
    No validator is built (the factory returns None): protoc is the reader here."""
    return normative_binding.resolve(env_var=ENV_VAR, record_name=RECORD,
                                     files=list(PINNED_FILES), fields=list(RECORD_FIELDS),
                                     environ=environ, validator_factory=lambda path: None)


def pin_commit(record: dict) -> str:
    """The upstream commit the record pins: the one full commit id in its `schema_revision`."""
    found = re.findall(r"\b[0-9a-f]{40}\b", str(record.get("schema_revision", "")))
    if len(found) != 1:
        raise BuildError(f"{RECORD} schema_revision names {len(found)} full commit ids; exactly "
                         "one was expected")
    return found[0]


@dataclasses.dataclass(frozen=True)
class Protoc:
    """One protoc with its includes, reading the verified contract directory."""

    executable: pathlib.Path
    include: pathlib.Path
    contract: pathlib.Path

    @classmethod
    def locate(cls, contract: pathlib.Path) -> "Protoc":
        for candidate in (shutil.which("protoc"), PROTOC_FALLBACK):
            if not candidate:
                continue
            executable = pathlib.Path(candidate)
            include = executable.parent.parent / "include"
            if executable.is_file() and (include / WELL_KNOWN_FILES[0]).is_file():
                return cls(executable, include, contract)
        raise ProtocUnavailable(f"protoc with its google/protobuf includes is not on PATH and not "
                                f"at {PROTOC_FALLBACK}")

    def _run(self, flag: str, octets: bytes) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self.executable), f"-I{self.contract}", f"-I{self.include}", flag,
             *PINNED_FILES, *WELL_KNOWN_FILES],
            input=octets, capture_output=True, check=False)

    def version(self) -> str:
        done = subprocess.run([str(self.executable), "--version"], capture_output=True,
                              check=False)
        if done.returncode != 0:
            raise ProtocUnavailable(f"{self.executable} --version failed")
        return done.stdout.decode("utf-8").strip()

    def encode(self, case: str, source: bytes) -> bytes:
        done = self._run("--encode=google.protobuf.Any", source)
        if done.returncode != 0:
            raise BuildError(f"protoc refused the source of {case}: "
                             f"{done.stderr.decode('utf-8', 'replace').strip()}")
        return done.stdout

    def decode(self, type_name: str, octets: bytes) -> tuple[bytes | None, int]:
        """protoc's text reading of `octets` as `type_name` (None when protoc refuses them) and
        protoc's exit status, which the pin records for a refusal."""
        done = self._run(f"--decode={type_name}", octets)
        return (done.stdout if done.returncode == 0 else None), done.returncode


# ------------------------------------------------------------------- the wire, for surgery only
#
# Enough of the encoding to find a length-delimited field in octets protoc wrote and re-frame the
# messages around a change to it. It is not the decoder and decides nothing about validity: what it
# does not expect stops the build.


def varint(value: int) -> bytes:
    """Base-128, least significant group first. Nothing written here is negative."""
    if value < 0:
        raise BuildError(f"varint({value}): the surgery writes no negative number")
    out = bytearray()
    while value > 0x7F:
        out.append(value & 0x7F | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _read_varint(octets: bytes, at: int) -> tuple[int, int]:
    value, shift = 0, 0
    while True:
        if at >= len(octets):
            raise BuildError("a varint runs past the octets protoc wrote")
        octet = octets[at]
        value |= (octet & 0x7F) << shift
        shift += 7
        at += 1
        if not octet & 0x80:
            return value, at


class Span(NamedTuple):
    """One field of a message: its tag's first octet, its value's first octet (after the length
    prefix for wire type 2) and the octet after it."""

    number: int
    wire_type: int
    start: int
    value: int
    end: int


def spans(octets: bytes) -> list[Span]:
    """The fields of one message protoc wrote, in wire order."""
    found = []
    at = 0
    while at < len(octets):
        start = at
        tag, at = _read_varint(octets, at)
        number, wire_type = tag >> 3, tag & 7
        if wire_type == 0:
            value, (_, end) = at, _read_varint(octets, at)
        elif wire_type == 2:
            length, value = _read_varint(octets, at)
            end = value + length
        elif wire_type in (1, 5):
            value, end = at, at + (8 if wire_type == 1 else 4)
        else:
            raise BuildError(f"wire type {wire_type} at octet {start}: protoc writes none")
        if end > len(octets):
            raise BuildError(f"field {number} at octet {start} runs past its message")
        found.append(Span(number, wire_type, start, value, end))
        at = end
    return found


def wire_steps(type_name: str, path: str) -> list[tuple[int, int]]:
    """From the `Any` to the message a twin path names, as (field number, occurrence) steps. The
    path is spelled as `codec.unknown_fields` spells it: "" is the response, then names joined by
    dots, a repeated field with its index (`blue_forces[1].point_location.geo_point`). A surgery
    may end the path at a well-known type (a `Timestamp` is a message on the wire); an append
    there would be refused by the decoder when it renders the twin, and the build would stop."""
    steps = [(2, 0)]                    # google.protobuf.Any field 2, `value`: the response
    current = type_name
    for part in filter(None, path.split(".")):
        name, _, index = part.partition("[")
        number, field = codec.FIELDS_BY_NAME[current][name]
        if field.kind != "message":
            raise BuildError(f"{path}: {name} is not a message field")
        steps.append((number, int(index.rstrip("]")) if index else 0))
        current = field.type
    return steps


def within(octets: bytes, steps: list[tuple[int, int]], change: Callable[[bytes], bytes]) -> bytes:
    """`octets` (one message) with `change` applied to the message `steps` lead to, and every
    length on the way re-encoded, so the result is framed as protoc would frame it."""
    if not steps:
        return change(octets)
    (number, occurrence), rest = steps[0], steps[1:]
    matching = [span for span in spans(octets) if span.number == number]
    if occurrence >= len(matching) or matching[occurrence].wire_type != 2:
        raise BuildError(f"no length-delimited occurrence {occurrence} of field {number}")
    span = matching[occurrence]
    inner = within(octets[span.value:span.end], rest, change)
    return (octets[:span.start] + varint(number << 3 | 2) + varint(len(inner)) + inner
            + octets[span.end:])


def any_value(payload: bytes) -> bytes:
    """The octets of the envelope's field 2 (`value`), which protoc then reads as the response."""
    values = [span for span in spans(payload) if span.number == 2 and span.wire_type == 2]
    if len(values) != 1:
        raise BuildError(f"the envelope holds {len(values)} values; one was expected")
    return payload[values[0].value:values[0].end]


# ------------------------------------------------------------------------- appends and surgery


@dataclasses.dataclass(frozen=True)
class Append:
    """A field this contract revision does not define, hand-encoded and appended to the end of the
    message `at` names (a twin path; "" is the response). `value` is the value's octets — for wire
    type 2 without the length prefix — which is exactly what the twin's `hex` states."""

    at: str
    number: int
    wire_type: int
    value: bytes

    def __post_init__(self) -> None:
        if self.wire_type == 0:
            read, after = _read_varint(self.value, 0)
            if after != len(self.value) or varint(read) != self.value:
                raise BuildError(f"{self}: a wire type 0 value is one canonical varint")
        elif self.wire_type != 2:
            raise BuildError(f"{self}: only wire types 0 and 2 are appended (module docstring)")

    def octets(self) -> bytes:
        if self.wire_type == 0:
            return varint(self.number << 3) + self.value
        return varint(self.number << 3 | 2) + varint(len(self.value)) + self.value

    def entry(self) -> dict:
        return {"at": self.at, "number": self.number, "wire_type": self.wire_type,
                "hex": self.value.hex()}


@dataclasses.dataclass(frozen=True)
class Surgery:
    """One change to protoc's bytes that makes them malformed. `says` is the record of it."""

    change: Callable[[bytes, str], bytes]
    says: str


def _cut_inside_a_varint(payload: bytes, type_name: str) -> bytes:
    """truncated_varint: drop the last octet of the element's `last_contact_time` (the final
    octet of its `seconds` varint, the one without the continuation bit) and re-frame."""
    def drop_last(timestamp: bytes) -> bytes:
        if timestamp[:1] != b"\x08" or timestamp[-1] & 0x80 or not timestamp[-2] & 0x80:
            raise BuildError("the Timestamp does not end in a multi-octet seconds varint")
        return timestamp[:-1]
    return within(payload, wire_steps(type_name, "blue_forces[0].last_contact_time"), drop_last)


def _cut_the_last_eight_octets(payload: bytes, type_name: str) -> bytes:
    """length_past_end: the capture loses its last eight octets (the longitude's double)."""
    if payload[-9] != 0x11:
        raise BuildError("the payload does not end in the longitude (field 2, fixed64)")
    return payload[:-8]


def _latitude_as_a_float(payload: bytes, type_name: str) -> bytes:
    """wire_type_mismatch: the latitude written as a 32-bit float (wire type 5) where the
    contract has a double (wire type 1), and the enclosing lengths re-framed."""
    def as_float(geo_point: bytes) -> bytes:
        first = spans(geo_point)[0]
        if (first.number, first.wire_type) != (1, 1):
            raise BuildError("the geo_point does not begin with its latitude as a double")
        latitude = struct.unpack("<d", geo_point[first.value:first.end])[0]
        if struct.unpack("<f", struct.pack("<f", latitude))[0] != latitude:
            raise BuildError(f"{latitude} is not exact as a float; the case wants the same value")
        return b"\x0d" + struct.pack("<f", latitude) + geo_point[first.end:]
    return within(payload, wire_steps(type_name, "blue_forces[0].point_location.geo_point"),
                  as_float)


def _second_oneof_member(payload: bytes, type_name: str) -> bytes:
    """two_oneof_members: an `int32_identity` (field 3, varint 407) appended to an identity that
    already holds a `string_identity`, and the enclosing lengths re-framed."""
    def add_member(identity: bytes) -> bytes:
        if [span.number for span in spans(identity)] != [2]:
            raise BuildError("the identity does not hold exactly its string_identity")
        return identity + varint(3 << 3) + varint(407)
    return within(payload, wire_steps(type_name, "blue_forces[0].identity"), add_member)


# --------------------------------------------------------------------------------- the cases


@dataclasses.dataclass(frozen=True)
class Case:
    """One payload: its name, its directory ("" for the harness's own, "cases" or "malformed"),
    its text source, what it exercises, and what was done to protoc's bytes, if anything."""

    name: str
    home: str
    source: str
    exercises: str
    appends: tuple[Append, ...] = ()
    surgery: Surgery | None = None
    refused_with: str | None = None
    refused_by: str | None = None

    @property
    def type_name(self) -> str:
        """The message type the source wraps, from its expanded `Any` line."""
        found = re.findall(r"^\[" + re.escape(URL_PREFIX) + r"([A-Za-z0-9_.]+)\] \{$",
                           self.source, flags=re.MULTILINE)
        if len(found) != 1:
            raise BuildError(f"{self.name}: the source names {len(found)} wrapped types")
        return found[0]

    def path(self, suffix: str) -> str:
        return f"{self.home}/{self.name}{suffix}" if self.home else f"{self.name}{suffix}"


SNAPSHOT_THREE_FORCES = r"""# A snapshot (GetBlueForces) of three blue forces in a Baltic exercise area, keyed by three of the
# four identity kinds (a uuid, a string, an int32). The first carries a MIL-STD-2525D numeric symbol
# and a height on the WGS 84 ellipsoid; the second a 2525C string symbol, a height at mean sea
# level and a non-ASCII callsign; the third is unmanned, mounted on the second, with no height.
# Fractional seconds in 3 and 9 digits.
[type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse] {
  header {
    success: true
  }
  blue_forces {
    identity {
      uuid_identity: "7e0789f0-8823-5bcb-b121-3278650b625b"
    }
    last_contact_time {
      seconds: 1790661600
    }
    callsign {
      value: "EXERCISE COBRA 6"
    }
    symbol {
      symbol_catalog: SYMBOL_CATALOG_MIL2525_D
      numeric_identifier {
        first_ten_digits: 1013100015
        second_ten_digits: 1211000000
      }
    }
    blue_force_type {
      is_leader: true
    }
    own_blue_force: true
    point_location {
      name {
        value: "EXERCISE COBRA CP"
      }
      location_time {
        seconds: 1790661595
        nanos: 250000000
      }
      geo_point {
        latitude_coordinate: 57.2154
        longitude_coordinate: 20.8732
        vertical_distance {
          value: 31.5
        }
        vertical_distance_reference_code: VERTICAL_DISTANCE_REFERENCE_CODE_WGS84_REFERENCE_ELLIPSOID
        measurement_code: MEASUREMENT_CODE_GPS
      }
    }
    associated_organization_unit_identity {
      string_identity: "EXERCISE-BN-3"
    }
  }
  blue_forces {
    identity {
      string_identity: "EXERCISE-VEH-201"
    }
    last_contact_time {
      seconds: 1790661602
      nanos: 123456789
    }
    callsign {
      value: "EXERCISE G\303\204DDA 2"
    }
    symbol {
      symbol_catalog: SYMBOL_CATALOG_MIL2525_C
      string_identifier: "SFGPEVC--------"
    }
    blue_force_type {
      is_vehicle: true
    }
    point_location {
      location_time {
        seconds: 1790661601
        nanos: 987654321
      }
      geo_point {
        latitude_coordinate: 57.1987
        longitude_coordinate: 20.9415
        vertical_distance {
          value: 4.25
        }
        vertical_distance_reference_code: VERTICAL_DISTANCE_REFERENCE_CODE_MEAN_SEA_LEVEL
        measurement_code: MEASUREMENT_CODE_INS
      }
      course {
        value: 247.5
      }
      speed {
        value: 8.75
      }
    }
  }
  blue_forces {
    identity {
      int32_identity: 30517
    }
    last_contact_time {
      seconds: 1790661560
      nanos: 500000000
    }
    blue_force_type {
      is_unmanned: true
    }
    point_location {
      location_time {
        seconds: 1790661559
      }
      geo_point {
        latitude_coordinate: 57.2402
        longitude_coordinate: 20.8019
        measurement_code: MEASUREMENT_CODE_ESTIMATE
      }
    }
    mount_host {
      string_identity: "EXERCISE-VEH-201"
    }
  }
}
"""

DELTA_WITH_DELETION = r"""# A streamed update (SubscribeBlueForceEvents). The first blue force moved; its key is the fourth
# identity kind, an int64 one past 2^53, which a JSON number cannot hold exactly. The second is
# the snapshot's EXERCISE-VEH-201, deleted. Fractional seconds in 6 digits; a height against QNH.
[type.googleapis.com/rheinmetall.tactical_api.v0.SubscribeBlueForceEventsResponse] {
  header {
    success: true
  }
  updated_blue_forces {
    identity {
      int64_identity: 9007199254740993
    }
    last_contact_time {
      seconds: 1790662500
    }
    callsign {
      value: "EXERCISE VIPER 3"
    }
    blue_force_type {
      is_vehicle: true
      is_unmanned: true
    }
    point_location {
      location_time {
        seconds: 1790662499
        nanos: 1000
      }
      geo_point {
        latitude_coordinate: 57.3011
        longitude_coordinate: 21.0544
        vertical_distance {
          value: 120
        }
        vertical_distance_reference_code: VERTICAL_DISTANCE_REFERENCE_CODE_PRESSURE_DATUM_QNH
        measurement_code: MEASUREMENT_CODE_GPS
      }
      course {
        value: 12.5
      }
      speed {
        value: 22.5
      }
    }
  }
  updated_blue_forces {
    identity {
      string_identity: "EXERCISE-VEH-201"
    }
    last_contact_time {
      seconds: 1790662470
    }
    is_deleted: true
  }
}
"""

AWKWARD_ZEROS = r"""# Zeros that are values. Every one below is on the wire except the latitude: protoc writes no
# proto3 scalar holding its default, so `latitude_coordinate: 0` never reaches the wire and a
# reader sees the longitude alone. The wrappers (error_message, callsign, vertical_distance,
# course, speed) and blue_force_type are messages, so each is written present and empty;
# int32_identity is a oneof member, so its 0 is written too. Fractional seconds in 9 digits.
# The second blue force's location_time is a present, empty Timestamp: seconds 0 and nanos 0,
# what a default-constructed Timestamp serialises to, which is not read as a source time. Its
# course is 360, the full turn: the first's course 0 is a course the CDM holds, and 360 is not
# (course_deg holds 0 up to but not including 360), so it is not mapped and nothing turns it to 0.
[type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse] {
  header {
    success: true
    error_message {
      value: ""
    }
  }
  blue_forces {
    identity {
      int32_identity: 0
    }
    last_contact_time {
      seconds: 1790663400
    }
    callsign {
      value: ""
    }
    blue_force_type {
      is_vehicle: false
    }
    point_location {
      location_time {
        seconds: 1790663399
        nanos: 1
      }
      geo_point {
        latitude_coordinate: 0
        longitude_coordinate: 9.25
        vertical_distance {
          value: 0
        }
        vertical_distance_reference_code: VERTICAL_DISTANCE_REFERENCE_CODE_TOPOGRAPHIC_SURFACE
        measurement_code: MEASUREMENT_CODE_GPS
      }
      course {
        value: 0
      }
      speed {
        value: 0
      }
    }
  }
  blue_forces {
    identity {
      string_identity: "EXERCISE-VEH-341"
    }
    last_contact_time {
      seconds: 1790663460
    }
    point_location {
      location_time {
      }
      geo_point {
        latitude_coordinate: 57.1333
        longitude_coordinate: 20.9222
        measurement_code: MEASUREMENT_CODE_GPS
      }
      course {
        value: 360
      }
    }
  }
}
"""

AWKWARD_SYMBOLS_AND_CODES = r"""# Symbols and codes no converter is written for: a 2525C string one character short of fifteen with
# a vertical reference code and a measurement code the contract does not name; the vendor's own
# catalog with a laser-ranged position; and a 2525D numeric code whose standard-identity digit is
# 2 (assumed friend), not the friend digit 3.
[type.googleapis.com/rheinmetall.tactical_api.v0.SubscribeBlueForceEventsResponse] {
  header {
    success: true
  }
  updated_blue_forces {
    identity {
      uuid_identity: "11819efc-c7e5-50b0-8aa4-ad2c6f420c17"
    }
    last_contact_time {
      seconds: 1790664300
    }
    symbol {
      symbol_catalog: SYMBOL_CATALOG_MIL2525_C
      string_identifier: "SFGPUCR-------"
    }
    point_location {
      location_time {
        seconds: 1790664299
        nanos: 750000000
      }
      geo_point {
        latitude_coordinate: 57.412
        longitude_coordinate: 21.1876
        vertical_distance {
          value: 15
        }
        vertical_distance_reference_code: 12
        measurement_code: 7
      }
    }
  }
  updated_blue_forces {
    identity {
      string_identity: "EXERCISE-RME-12"
    }
    callsign {
      value: "EXERCISE KESTREL 5"
    }
    symbol {
      symbol_catalog: SYMBOL_CATALOG_RME
      string_identifier: "EXERCISE-RME-SYMBOL-77"
    }
    point_location {
      location_time {
        seconds: 1790664303
      }
      geo_point {
        latitude_coordinate: 57.3855
        longitude_coordinate: 21.221
        measurement_code: MEASUREMENT_CODE_LRS
      }
    }
  }
  updated_blue_forces {
    identity {
      int64_identity: 4400000000017
    }
    last_contact_time {
      seconds: 1790664290
    }
    symbol {
      symbol_catalog: SYMBOL_CATALOG_MIL2525_D
      numeric_identifier {
        first_ten_digits: 1012100015
        second_ten_digits: 1211000000
      }
    }
  }
}
"""

UNKNOWN_FIELD_CARRIED = r"""# Two blue forces. After protoc wrote them, four fields this contract revision does not define were
# appended by hand (spec/build_fixtures.py, UNKNOWN_FIELD_CARRIED_APPENDS): one on the response,
# one on the header, one on the first blue force, one on the second's geo_point.
[type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse] {
  header {
    success: true
  }
  blue_forces {
    identity {
      string_identity: "EXERCISE-VEH-310"
    }
    last_contact_time {
      seconds: 1790665200
    }
    point_location {
      location_time {
        seconds: 1790665199
      }
      geo_point {
        latitude_coordinate: 57.1502
        longitude_coordinate: 20.7655
        measurement_code: MEASUREMENT_CODE_GPS
      }
    }
  }
  blue_forces {
    identity {
      int32_identity: 311
    }
    point_location {
      location_time {
        seconds: 1790665201
        nanos: 5000000
      }
      geo_point {
        latitude_coordinate: 57.1611
        longitude_coordinate: 20.7701
        measurement_code: MEASUREMENT_CODE_GPS
      }
    }
  }
}
"""

UNKNOWN_FIELD_CARRIED_APPENDS = (
    # Field 3 of the response, a string: the next free number after `blue_forces`.
    Append("", 3, 2, b"EXERCISE NOTE ALPHA"),
    # Field 3 of the header, a varint: the next free number after `error_message`.
    Append("header", 3, 0, varint(2)),
    # Field 11 of a blue force, a varint: the next free number after `is_deleted`.
    Append("blue_forces[0]", 11, 0, varint(1)),
    # Field 6 of a geo_point, a varint: the next free number after `measurement_code`.
    Append("blue_forces[1].point_location.geo_point", 6, 0, varint(3)),
)

EMPTY_GEO_POINT = r"""# A geo_point that is present and empty: neither coordinate is on the wire, so there is no position.
[type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse] {
  header {
    success: true
  }
  blue_forces {
    identity {
      string_identity: "EXERCISE-VEH-320"
    }
    last_contact_time {
      seconds: 1790665260
    }
    point_location {
      location_time {
        seconds: 1790665258
      }
      geo_point {
      }
    }
  }
}
"""

EMPTY_SUCCESSFUL_RESPONSE = r"""# A successful snapshot with no blue force in it.
[type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse] {
  header {
    success: true
  }
}
"""

DELETED_WITHOUT_TIMESTAMPS = r"""# A deletion that states the identity and nothing else: no time of any kind.
[type.googleapis.com/rheinmetall.tactical_api.v0.SubscribeBlueForceEventsResponse] {
  header {
    success: true
  }
  updated_blue_forces {
    identity {
      uuid_identity: "af3012b2-9c6e-5748-961b-48f15a82528b"
    }
    is_deleted: true
  }
}
"""

DUPLICATE_IDENTITY = r"""# One identity twice in one message, ten seconds and a few metres apart.
[type.googleapis.com/rheinmetall.tactical_api.v0.SubscribeBlueForceEventsResponse] {
  header {
    success: true
  }
  updated_blue_forces {
    identity {
      string_identity: "EXERCISE-VEH-305"
    }
    point_location {
      location_time {
        seconds: 1790665500
      }
      geo_point {
        latitude_coordinate: 57.205
        longitude_coordinate: 20.9001
        measurement_code: MEASUREMENT_CODE_GPS
      }
    }
  }
  updated_blue_forces {
    identity {
      string_identity: "EXERCISE-VEH-305"
    }
    point_location {
      location_time {
        seconds: 1790665510
      }
      geo_point {
        latitude_coordinate: 57.2071
        longitude_coordinate: 20.9033
        measurement_code: MEASUREMENT_CODE_GPS
      }
    }
  }
}
"""

D_CODE_SECOND_SET_ZERO = r"""# A 2525D numeric code whose second set of ten digits is all zeros: protoc writes no int64 holding
# 0, so `second_ten_digits` is absent from the wire, and an absent set reads 0.
[type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse] {
  header {
    success: true
  }
  blue_forces {
    identity {
      int32_identity: 330
    }
    last_contact_time {
      seconds: 1790665620
    }
    symbol {
      symbol_catalog: SYMBOL_CATALOG_MIL2525_D
      numeric_identifier {
        first_ten_digits: 1013100015
        second_ten_digits: 0
      }
    }
    point_location {
      location_time {
        seconds: 1790665619
      }
      geo_point {
        latitude_coordinate: 57.1777
        longitude_coordinate: 20.8888
        measurement_code: MEASUREMENT_CODE_GPS
      }
    }
  }
}
"""

UNKNOWN_FIELDS_WITHOUT_CARRIER = r"""# A successful response with no blue force. After protoc wrote it, two fields this contract revision
# does not define were appended by hand (UNKNOWN_FIELDS_WITHOUT_CARRIER_APPENDS): one on the
# response, one on the header. No element exists to carry them.
[type.googleapis.com/rheinmetall.tactical_api.v0.SubscribeBlueForceEventsResponse] {
  header {
    success: true
  }
}
"""

UNKNOWN_FIELDS_WITHOUT_CARRIER_APPENDS = (
    Append("", 3, 2, b"EXERCISE NOTE BRAVO"),
    Append("header", 3, 0, varint(1)),
)

ERROR_MESSAGE_WITHOUT_CARRIER = r"""# A successful snapshot with no blue force whose header states an error message: no element
# exists to carry the text, so the adapter refuses the message rather than drop it.
[type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse] {
  header {
    success: true
    error_message {
      value: "EXERCISE partial: 3 units unreachable"
    }
  }
}
"""

TRUNCATED_VARINT = r"""# Before surgery: one blue force whose last field is its last_contact_time.
[type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse] {
  header {
    success: true
  }
  blue_forces {
    identity {
      string_identity: "EXERCISE-VEH-401"
    }
    last_contact_time {
      seconds: 1790665800
    }
  }
}
"""

LENGTH_PAST_END = r"""# Before surgery: one blue force whose last field is the longitude of its geo_point.
[type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse] {
  header {
    success: true
  }
  blue_forces {
    identity {
      string_identity: "EXERCISE-VEH-402"
    }
    point_location {
      geo_point {
        latitude_coordinate: 57.255
        longitude_coordinate: 20.991
      }
    }
  }
}
"""

WIRE_TYPE_MISMATCH = r"""# Before surgery: one blue force with a latitude that a 32-bit float holds exactly.
[type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse] {
  header {
    success: true
  }
  blue_forces {
    identity {
      string_identity: "EXERCISE-VEH-403"
    }
    point_location {
      geo_point {
        latitude_coordinate: 57.5
        longitude_coordinate: 21
      }
    }
  }
}
"""

UNSUPPORTED_MESSAGE_TYPE = r"""# The write side's response, which has the same header: a type outside the two the adapter reads.
[type.googleapis.com/rheinmetall.tactical_api.v0.AddOrUpdateBlueForcesResponse] {
  header {
    success: true
  }
}
"""

SUCCESS_FALSE = r"""# An unsuccessful response that still lists a blue force. protoc writes no bool holding false, so
# `success` is absent from the wire, which the contract defines as false; the message stays.
[type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse] {
  header {
    success: false
    error_message {
      value: "EXERCISE feed unavailable"
    }
  }
  blue_forces {
    identity {
      string_identity: "EXERCISE-VEH-405"
    }
    last_contact_time {
      seconds: 1790665900
    }
  }
}
"""

BLUE_FORCE_WITHOUT_IDENTITY = r"""# A blue force with a callsign and a position and no identity.
[type.googleapis.com/rheinmetall.tactical_api.v0.SubscribeBlueForceEventsResponse] {
  header {
    success: true
  }
  updated_blue_forces {
    callsign {
      value: "EXERCISE NOMAD 6"
    }
    point_location {
      location_time {
        seconds: 1790665960
      }
      geo_point {
        latitude_coordinate: 57.2333
        longitude_coordinate: 20.9555
        measurement_code: MEASUREMENT_CODE_GPS
      }
    }
  }
}
"""

TWO_ONEOF_MEMBERS = r"""# Before surgery: one blue force whose identity holds a string_identity and nothing else.
[type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse] {
  header {
    success: true
  }
  blue_forces {
    identity {
      string_identity: "EXERCISE-VEH-407"
    }
  }
}
"""

LATITUDE_91 = r"""# A latitude one degree past the pole.
[type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse] {
  header {
    success: true
  }
  blue_forces {
    identity {
      string_identity: "EXERCISE-VEH-408"
    }
    point_location {
      location_time {
        seconds: 1790666020
      }
      geo_point {
        latitude_coordinate: 91
        longitude_coordinate: 20.95
        measurement_code: MEASUREMENT_CODE_GPS
      }
    }
  }
}
"""

CASES = (
    # ---- the harness fixtures (the implementation record's §7, top level)
    Case("snapshot_three_forces", "", SNAPSHOT_THREE_FORCES,
         "three identity kinds, a 2525D numeric symbol, a 2525C string symbol, heights on the "
         "ellipsoid and at mean sea level"),
    Case("delta_with_deletion", "", DELTA_WITH_DELETION,
         "a streamed update with one deleted blue force; an int64 identity past 2^53"),
    Case("awkward_zeros", "", AWKWARD_ZEROS,
         "wrapper-present zeros (course 0, speed 0, height 0, empty callsign and error message), "
         "an int32 identity of 0, latitude 0 (absent from the wire) with a non-zero longitude, "
         "and a present zero location_time beside a real last_contact_time and a course of 360, "
         "outside the range course_deg holds"),
    Case("awkward_symbols_and_codes", "", AWKWARD_SYMBOLS_AND_CODES,
         "a 14-character symbol string, an unnamed measurement code and vertical reference code, "
         "the vendor catalog, a 2525D identity digit that is not friend"),
    Case("snapshot_with_unknown_fields", "", UNKNOWN_FIELD_CARRIED,
         "cases/unknown_field_carried under a name the harness selects: four unknown fields, on "
         "the response, the header, a blue force and a geo_point",
         appends=UNKNOWN_FIELD_CARRIED_APPENDS),
    # ---- accepted counterexamples, read by name in the tests
    Case("unknown_field_carried", "cases", UNKNOWN_FIELD_CARRIED,
         "four unknown fields, on the response, the header, a blue force and a geo_point",
         appends=UNKNOWN_FIELD_CARRIED_APPENDS),
    Case("empty_geo_point", "cases", EMPTY_GEO_POINT, "a present, empty geo_point"),
    Case("empty_successful_response", "cases", EMPTY_SUCCESSFUL_RESPONSE,
         "a successful snapshot with no blue force"),
    Case("deleted_without_timestamps", "cases", DELETED_WITHOUT_TIMESTAMPS,
         "a deleted blue force with no time of any kind"),
    Case("duplicate_identity", "cases", DUPLICATE_IDENTITY, "one identity twice in one message"),
    Case("d_code_second_set_zero", "cases", D_CODE_SECOND_SET_ZERO,
         "a 2525D code whose second set is all zeros (absent from the wire)"),
    Case("unknown_fields_without_carrier", "cases", UNKNOWN_FIELDS_WITHOUT_CARRIER,
         "unknown fields on a response with no blue force to carry them",
         appends=UNKNOWN_FIELDS_WITHOUT_CARRIER_APPENDS),
    Case("error_message_without_carrier", "cases", ERROR_MESSAGE_WITHOUT_CARRIER,
         "a header error_message on a successful response with no blue force to carry it"),
    # ---- refusals (check H)
    Case("truncated_varint", "malformed", TRUNCATED_VARINT, "a varint that ends early",
         surgery=Surgery(_cut_inside_a_varint,
                         "the last octet of the blue force's last_contact_time, the final octet "
                         "of its seconds varint, removed, and the three enclosing lengths (the "
                         "Timestamp, the blue force, the Any's value) re-encoded one shorter, so "
                         "every length is honest and the varint alone runs out"),
         refused_with="truncated-varint", refused_by="decoder"),
    Case("length_past_end", "malformed", LENGTH_PAST_END,
         "a declared length the remaining octets cannot hold",
         surgery=Surgery(_cut_the_last_eight_octets,
                         "the last eight octets (the longitude's double) cut off, as a capture "
                         "cut short; the Any's value still declares them"),
         refused_with="length-exceeds-input", refused_by="decoder"),
    Case("wire_type_mismatch", "malformed", WIRE_TYPE_MISMATCH,
         "a named field arriving with another wire type",
         surgery=Surgery(_latitude_as_a_float,
                         "the geo_point's latitude (field 1, a double, wire type 1) rewritten as "
                         "the 32-bit float of the same value (tag 0x0d, wire type 5, four octets), "
                         "and the three enclosing lengths re-encoded four shorter"),
         refused_with="wire-type-mismatch", refused_by="decoder"),
    Case("unsupported_message_type", "malformed", UNSUPPORTED_MESSAGE_TYPE,
         "a type outside the two supported", refused_with="unsupported-message-type",
         refused_by="decoder"),
    Case("success_false", "malformed", SUCCESS_FALSE,
         "an unsuccessful response (success absent from the wire, which reads false)",
         refused_with="response-not-successful", refused_by="adapter"),
    Case("blue_force_without_identity", "malformed", BLUE_FORCE_WITHOUT_IDENTITY,
         "a blue force with no identity", refused_with="blue-force-without-identity",
         refused_by="adapter"),
    Case("two_oneof_members", "malformed", TWO_ONEOF_MEMBERS,
         "two members of the identity oneof in one message",
         surgery=Surgery(_second_oneof_member,
                         "an int32_identity (field 3, varint 407) appended to the identity after "
                         "its string_identity, and the three enclosing lengths (the identity, the "
                         "blue force, the Any's value) re-encoded"),
         refused_with="multiple-oneof-members", refused_by="decoder"),
    Case("latitude_91", "malformed", LATITUDE_91, "a latitude of 91 degrees",
         refused_with="coordinate-out-of-range", refused_by="adapter"),
)

# ------------------------------------------------------------------------------ the generated set


class _Generated:
    """Octets built in memory, offered to `synapse_cdm.evidence.digest`, the one place this
    adapter's code hashes. `digest` reads its argument with `read_bytes()` and nothing else; a
    generated file has no path to give it, because --check never writes.
    `tests/test_cdm_tacticalapi_fixtures.py` holds every hash taken this way to `digest` of the
    file on disk."""

    def __init__(self, octets: bytes) -> None:
        self._octets = octets

    def read_bytes(self) -> bytes:
        return self._octets


def file_digest(name: str, octets: bytes) -> dict:
    sha256, size = evidence.digest(_Generated(octets))
    return {"file": name, "sha256": sha256, "bytes": size}


def twin_text(payload: bytes) -> bytes:
    """The decoder's twin of a payload as the `.parsed.json` file holds it. Key order is the twin's
    own (the implementation record's §2.2), never sorted; non-ASCII is escaped so the file reads the same under
    any locale the harness's `read_text()` might use."""
    return (json.dumps(codec.decode(payload), indent=2, ensure_ascii=True) + "\n").encode("ascii")


def json_bytes(document: dict) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("ascii")


@dataclasses.dataclass
class Built:
    """One case's outputs: the payload, and what protoc made of it."""

    case: Case
    payload: bytes
    any_reading: bytes | None
    value_reading: bytes | None
    refusal_status: int | None = None

    def protoc_verdict(self) -> str:
        if self.any_reading is None:
            return (f"protoc --decode=google.protobuf.Any refuses the payload (exit status "
                    f"{self.refusal_status})")
        if self.value_reading is None:
            return (f"protoc reads the envelope (independent/{self.case.name}.any.txtpb) and "
                    f"refuses the value as {self.case.type_name} (exit status "
                    f"{self.refusal_status})")
        return (f"protoc reads both: independent/{self.case.name}.any.txtpb and "
                f"independent/{self.case.name}.value.txtpb")


def build_case(case: Case, protoc: Protoc) -> Built:
    source = case.source.encode("ascii")    # non-ASCII text is written as octal escapes
    payload = protoc.encode(case.name, source)
    for append in case.appends:
        payload = within(payload, wire_steps(case.type_name, append.at),
                         lambda message, extra=append.octets(): message + extra)
    if case.surgery is not None:
        payload = case.surgery.change(payload, case.type_name)
    any_reading, status = protoc.decode("google.protobuf.Any", payload)
    value_reading = None
    if any_reading is not None:
        value_reading, status = protoc.decode(case.type_name, any_value(payload))
    if case.home != "malformed" and (any_reading is None or value_reading is None):
        raise BuildError(f"protoc cannot read back {case.name}, which is meant to be well formed")
    return Built(case, payload, any_reading, value_reading,
                 refusal_status=status if value_reading is None else None)


#: Each directory's provenance sentence (§33 of the host package: `origin` is prose for a human
#: auditor; the machine-readable claims are the booleans and the classification).
ORIGINS = {
    "": (f"Synthetic TacticalAPI response payloads written on {WRITTEN_ON} by "
         "`spec/build_fixtures.py`: protoc encoded each, wrapped in google.protobuf.Any, from a "
         "text source the script holds as its own literal (copied to `sources/`), one has "
         "fields appended by hand that protoc's text form cannot state (fields this contract "
         "revision does not define, listed in `spec/tacticalapi_pin.json`), and the "
         "package's decoder rendered the `.parsed.json` twin beside each. Every name carries the "
         "word EXERCISE, every UUID is the uuid5 of an EXERCISE name, every position is invented, "
         "and nothing derives from recorded data; hashes and the protoc commands are in "
         "`spec/tacticalapi_pin.json`, and protoc's own reading of every payload is under "
         "`independent/`, against which `tests/test_cdm_tacticalapi_fixtures.py` holds every "
         "twin."),
    "cases": (f"Synthetic accepted counterexamples written on {WRITTEN_ON} by "
              "`spec/build_fixtures.py`, read by name in the tests and never selected by the "
              "harness: protoc encoded each from the script's own text literal, two have fields "
              "appended by hand that protoc's text form cannot state (fields this contract "
              "revision does not define, listed in `spec/tacticalapi_pin.json`), and the "
              "package's decoder rendered each twin. Every name carries EXERCISE and nothing "
              "derives from recorded data."),
    "malformed": (f"Synthetic refusal payloads built on {WRITTEN_ON} by `spec/build_fixtures.py`: "
                  "four are protoc's own encoding of a message the adapter refuses for what it "
                  "says, and four are protoc's bytes changed by one described byte surgery, since "
                  "protoc will not write malformed data. The surgery, the reason code and protoc's "
                  "own verdict on each are in `spec/tacticalapi_pin.json` and README.md. Nothing "
                  "derives from recorded data and none is claimed as independent evidence."),
    "sources": (f"The text-format sources protoc encoded into every payload of this set, written on "
                f"{WRITTEN_ON} by `spec/build_fixtures.py` from its own literals. Each names its "
                "message type in the expanded Any form and holds invented values only: names "
                "with EXERCISE, UUIDs that are uuid5 of EXERCISE names, positions in a Baltic "
                "exercise area or on the equator."),
    "independent": (f"protoc's own reading of the written payloads, taken on {WRITTEN_ON} by "
                    "`spec/build_fixtures.py`: `<case>.any.txtpb` is "
                    "`protoc --decode=google.protobuf.Any` of the whole payload and "
                    "`<case>.value.txtpb` is `protoc --decode` of the envelope's value as the type "
                    "its type_url names. `tests/test_cdm_tacticalapi_fixtures.py` reads every twin "
                    "against them, so the decoder is not its own oracle. Everything read is "
                    "synthetic."),
}


def provenance(directory: str, names: list[str]) -> bytes:
    record = {
        "schema_id": evidence.PROVENANCE_SCHEMA_ID,
        "directory": f"tacticalapi/{directory}" if directory else "tacticalapi",
        "fixtures": [{"file": name, "synthetic": True, "classification": "PUBLIC",
                      "operational_data": False, "personal_data": False,
                      "origin": ORIGINS[directory]} for name in sorted(names)],
    }
    return json_bytes(record)


#: How each output was made, with placeholders for every path that depends on the host.
COMMANDS = (
    'protoc -I"$SYNAPSE_CDM_TACTICALAPI_PROTO_DIR" -I<protoc include> '
    "--encode=google.protobuf.Any <the ten pinned files> google/protobuf/any.proto "
    "< sources/<case>.txtpb > <payload, before any append or surgery>",
    'protoc -I"$SYNAPSE_CDM_TACTICALAPI_PROTO_DIR" -I<protoc include> '
    "--decode=google.protobuf.Any <the ten pinned files> google/protobuf/any.proto "
    "< <payload> > independent/<case>.any.txtpb",
    'protoc -I"$SYNAPSE_CDM_TACTICALAPI_PROTO_DIR" -I<protoc include> '
    "--decode=<the type the type_url names> <the ten pinned files> google/protobuf/any.proto "
    "< <the octets of the Any's value> > independent/<case>.value.txtpb",
)


def pin_record(built: list[Built], files: dict[str, bytes], record: dict, version: str) -> dict:
    def listed(prefix: str, suffixes: tuple[str, ...]) -> list[dict]:
        return [file_digest(name, files[name]) for name in sorted(files)
                if name.startswith(prefix) and "/" not in name[len(prefix):]
                and name.endswith(suffixes)]

    def case_entry(item: Built, suffix: str) -> dict:
        return file_digest(item.case.path(suffix), files[item.case.path(suffix)])

    fixtures = []
    cases = []
    malformed = []
    for item in built:
        if item.case.home in ("", "cases"):
            for suffix in (".binpb", ".parsed.json"):
                entry = case_entry(item, suffix)
                if suffix == ".binpb" and item.case.appends:
                    entry["appended_by_hand"] = [append.entry() for append in item.case.appends]
                (fixtures if item.case.home == "" else cases).append(entry)
        elif item.case.home == "malformed":
            entry = case_entry(item, ".binpb")
            entry["made_by"] = (item.case.surgery.says if item.case.surgery is not None
                                else "protoc's own encoding of the source, unchanged")
            entry["refused_with"] = item.case.refused_with
            entry["refused_by"] = item.case.refused_by
            entry["protoc_reading"] = item.protoc_verdict()
            malformed.append(entry)
    return {
        "what_this_is": (
            "The provenance record for every TacticalAPI payload under fixtures/tacticalapi/: the "
            "contract the payloads are written to, the INDEPENDENT IMPLEMENTATION that wrote them "
            "(protoc), how each file was produced, its SHA-256 and byte count, and where protoc's "
            "own readings live, so the decoder's twin is never the only oracle for what a payload "
            "holds. House style follows fixtures/c2sim/spec/c2sim_pin.json of this package. No "
            "node here pairs a local path with a hash, deliberately: this record pins fixtures, "
            "which are the repository's own files, and the contract is not carried here."),
        "adapter": {"name": "tacticalapi", "ordinal": 22, "direction": "ingest",
                    "fixture_directory": "tacticalapi",
                    "message_types": list(codec.SUPPORTED_TYPES)},
        "contract": {
            "package": codec.PACKAGE,
            "edition": (f"upstream commit {pin_commit(record)}; the upstream repository has no "
                        "tag and no release, so the edition is the commit"),
            "files": list(PINNED_FILES),
            "terms": ("The file headers offer two licences, the Eclipse Public License 2.0 or a "
                      "BSD-style licence, and the upstream repository's licence file holds the "
                      "Eclipse Public License 2.0 alone. The maintainer ruled on 2026-10-06 that "
                      "the Eclipse Public License 2.0 governs the files, as that licence file "
                      "states, and the headers' BSD-style alternative is not taken "
                      "(docs/tacticalapi-implementation.md of the repository, R8). The upstream README also reserves the publisher's names; the "
                      "maintainer ruled on 2026-10-06 to keep the interface name without seeking "
                      "written consent, accepting the risk that reservation names (R9). The "
                      "upstream README notes that export-control law may apply to using the "
                      "files; the maintainer ruled on 2026-10-06 that this adapter, which holds "
                      "field names, numbers and enum values of the publicly published interface "
                      "and no upstream software or interface definition text, is not a "
                      "controlled item, and nothing here is classified (R10). Nothing of the "
                      "files is copied here: payloads hold invented values, and the adapter "
                      "holds the contract's names and numbers only."),
            "carried_here": False,
            "why_not_carried": (
                "The files are held outside every repository under the "
                "SYNAPSE_CDM_TACTICALAPI_PROTO_DIR hook, with their record proto_pin.json, and "
                "synapse_cdm.normative_binding.resolve verifies each one's SHA-256 against that "
                "record before protoc reads any of them. The payloads need no file of the "
                "contract to be read: the decoder embeds the field table, and the tests that need "
                "protoc report BLOCKED_EXTERNAL_EVIDENCE without it."),
        },
        "independent_implementation": {
            "tool": "protoc, with the google/protobuf well-known types that ship with it",
            "version": version,
            "taken_on": WRITTEN_ON,
            "commands": list(COMMANDS),
            "what_it_shows": (
                "protoc wrote every octet of every payload except those a case appends, cuts or "
                "rewrites, and the lengths re-encoded around them (listed below per file). "
                "independent/ holds protoc's reading of every payload it "
                "can read: the envelope (type_url and the value's octets) and the value decoded as "
                "the type the type_url names. tests/test_cdm_tacticalapi_fixtures.py reads each "
                "twin against those readings and against the source literal, convention by "
                "convention of section 2.2 of docs/tacticalapi-implementation.md."),
        },
        "fixtures_are_synthetic": (
            f"Every source is a literal in spec/build_fixtures.py, written on {WRITTEN_ON}. Every "
            "name carries the word EXERCISE, every UUID is the uuid5 of an EXERCISE name, every "
            "position is an invented point in a Baltic exercise area off the Courland coast or, "
            "where a zero latitude is the point, on the equator in the Gulf of Guinea, and no file "
            "derives from any recorded message."),
        "regenerate": (
            "python spec/build_fixtures.py, run beside this record with protoc and the pinned "
            "contract present; --check regenerates everything in memory and names every file that "
            "differs, is missing or is extra. golden/ is the harness's and is not compared. "
            "tests/test_cdm_tacticalapi_fixtures.py re-derives every hash below from the files "
            "on disk on every run, without protoc."),
        "fixtures": sorted(fixtures, key=lambda entry: entry["file"]),
        "cases": {
            "what": ("accepted counterexamples the harness never selects, each read by name in the "
                     "tests"),
            "files": cases,
        },
        "malformed": {
            "what": ("refusal payloads for the conformance suite's check H; the reason code each "
                     "is refused with, and whether the decoder or the adapter refuses it, is "
                     "tested in tests/test_cdm_tacticalapi_fixtures.py against README.md"),
            "files": malformed,
        },
        "sources": listed("sources/", (".txtpb",)),
        "independent": listed("independent/", (".txtpb",)),
    }


def generate(environ=None) -> dict[str, bytes]:
    """Every generated file, by its path under fixtures/tacticalapi/, built in memory. Raises
    `NormativeBindingBlocked` when the pin does not verify and `ProtocUnavailable` when protoc is
    absent: both are BLOCKED_EXTERNAL_EVIDENCE, never a fixture set."""
    resource = resolve_pin(environ)
    protoc = Protoc.locate(resource.directory)
    version = protoc.version()
    built = [build_case(case, protoc) for case in CASES]
    files: dict[str, bytes] = {}
    for item in built:
        case = item.case
        files[f"sources/{case.name}.txtpb"] = case.source.encode("ascii")
        files[case.path(".binpb")] = item.payload
        if case.home != "malformed":
            files[case.path(".parsed.json")] = twin_text(item.payload)
        if item.any_reading is not None:
            files[f"independent/{case.name}.any.txtpb"] = item.any_reading
        if item.value_reading is not None:
            files[f"independent/{case.name}.value.txtpb"] = item.value_reading
    for directory in ORIGINS:
        prefix = f"{directory}/" if directory else ""
        members = [name[len(prefix):] for name in files
                   if name.startswith(prefix) and "/" not in name[len(prefix):]]
        files[f"{prefix}PROVENANCE.json"] = provenance(directory, members)
    files["spec/tacticalapi_pin.json"] = json_bytes(pin_record(built, files, resource.record,
                                                               version))
    return files


def not_generated(relative: str) -> bool:
    """The files of the tree this script neither writes nor compares: the two hand-written ones,
    the harness's golden/, and what an editor or an interpreter leaves behind (dotfiles,
    `__pycache__`), which the harness ignores too."""
    parts = pathlib.PurePosixPath(relative).parts
    return (relative in HAND_WRITTEN or parts[0] == GOLDEN or "__pycache__" in parts
            or any(part.startswith(".") for part in parts))


def differences(files: dict[str, bytes], root: pathlib.Path = FIXTURES) -> list[str]:
    """Each generated file that differs from the tree's or is missing from it, then each file of
    the tree that is not generated and not exempt (`not_generated`). Empty means equal."""
    found = []
    for relative in sorted(files):
        path = root / relative
        if not path.is_file():
            found.append(f"{relative}: missing from the tree")
        elif path.read_bytes() != files[relative]:
            found.append(f"{relative}: differs from what this script generates")
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative not in files and not not_generated(relative):
            found.append(f"{relative}: in the tree and not generated by this script")
    return found


def main(argv: list[str] | None = None, environ=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true",
                        help="regenerate in memory and compare with the tree, byte for byte")
    args = parser.parse_args(argv)
    try:
        files = generate(environ)
    except normative_binding.NormativeBindingBlocked as blocked:
        print(str(blocked), file=sys.stderr)
        return 3
    except ProtocUnavailable as blocked:
        print(f"{normative_binding.BLOCKED_STATUS} at step 'protoc': {blocked}", file=sys.stderr)
        return 3
    if not args.check:
        for relative, octets in sorted(files.items()):
            target = FIXTURES / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(octets)
        print(f"wrote {len(files)} files under fixtures/tacticalapi/")
    found = differences(files)
    for line in found:
        print(line)
    if args.check:
        print(f"{len(files)} generated files compared with the tree: {len(found)} differ, are "
              "missing or are extra")
    elif found:
        print("the tree holds files this script does not generate; remove them or generate them")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
