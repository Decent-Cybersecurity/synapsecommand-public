"""SC4545-CORE-1: the NSIF 01.01, NSIF 01.00 and NITF 02.10 container parser behind `stanag4545`.

This module reads one still-imagery container into an inventory of immutable records and
refuses everything else with one coded error. The parse interprets no image sample (pixel
assessment only names the cell an image falls in), no TRE payload, no text payload and no DES or
RES payload other than the TRE framing of a TRE_OVERFLOW DES; each image's footprint comes from
its corners alone (`nsif_geometry`). Samples are read only on request, one window of one native
image at a time (`decode_nc_window`). It decodes no compressed or masked image: those cells are
inventoried and disabled. It opens nothing; the input is one `bytes` object, retained once and
addressed by `Slice(offset, length)` everywhere else.

THE ERROR MODEL
---------------
Every refusal is an `NsifError`, a ValueError with `code`, `stage`, `offset`, `path` and
`explanation`, printed `CODE @byte OFFSET PATH: explanation` (`-` for an offset no wire position
has). Explanations are fixed per check and never copy a source byte, field value, tag or length;
paths are built from grammar names and ordinals only. One condition has one code. The two
argument-size and twin-depth refusals are also the SDK's InputTooLarge and InputTooDeep, so the
shared bound tests read them through `to_cdm` as the SDK classes they expect.

THE CHECK ORDER, which is what "the first fatal error" means
-------------------------------------------------------------
Cursor order with named deferred steps, never "lowest offset": the argument (`check_argument`,
`decode_twin`); the file header and directory in wire order, each field checked as it is taken;
the segment walk and the metadata charge; every subheader in file order, its field relations
checked as soon as their operands are read; overflow resolution, which must wait for the DES
subheaders at the end of the file; then the non-fatal inventory (composition, then each image's
footprint in file order). A later phase can therefore report a lower offset than an earlier one,
and that is intended. A window request is checked in its own fixed order, argument by argument,
before any sample is read.

THE SEAMS
---------
`read_layout`, `extension_area` and `image_subheader` are the parse's own code paths exposed as
pure functions over a whole input, one extension area and one image subheader, so each can be
exercised alone; `parse_container` runs the same functions in the order above. `sample_index` is
the one place the four interleave formulas are written, and the decoder takes every index from it.
"""

from __future__ import annotations

import binascii
import datetime
import re
import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from dataclasses import fields as dataclass_fields
from typing import NamedTuple

from synapse_cdm.adapter import InputTooDeep, InputTooLarge
from synapse_cdm.adapters import nsif_geometry

PROFILE = "SC4545-CORE-1"
MAGICS = (b"NSIF01.01", b"NSIF01.00", b"NITF02.10")
CLEVELS = (3, 5, 6, 7, 9)
KINDS = ("image", "graphic", "text", "des", "res")

#: The result schema's stage vocabulary, used by errors and diagnostics alike.
STAGES = (
    "input",
    "header",
    "segment",
    "extension",
    "security",
    "geometry",
    "pixels",
    "cdm",
    "storage",
    "export",
)

#: The specification's section 19 codes, in its table order. The core raises only the first
#: eight and E_ENCRYPTED and E_CODEC; the others name host outcomes.
ERROR_CODES = (
    "E_MAGIC",
    "E_PROFILE",
    "E_DIGITS",
    "E_LENGTH",
    "E_FIELD",
    "E_OVERFLOW",
    "E_LIMIT",
    "E_CONTEXT",
    "E_ENCRYPTED",
    "E_POLICY",
    "E_CODEC",
    "E_GEOMETRY",
    "E_INTEGRITY",
    "E_TIMEOUT",
    "E_BUSY",
    "E_IO",
    "E_INTERNAL",
)

#: The compressed and masked codes the profile names; NC is the one native code.
NAMED_COMPRESSION = ("NM", "C1", "M1", "C3", "M3", "C4", "M4", "C5", "M5", "C8", "M8")

#: The 167-octet security block, in wire order, under the uniform names of every scope.
SECURITY_FIELDS = (
    ("CLAS", 1),
    ("CLSY", 2),
    ("CODE", 11),
    ("CTLH", 2),
    ("REL", 20),
    ("DCTP", 2),
    ("DCDT", 8),
    ("DCXM", 4),
    ("DG", 1),
    ("DGDT", 8),
    ("CLTX", 43),
    ("CAPT", 1),
    ("CAUT", 40),
    ("CRSN", 1),
    ("SRDT", 8),
    ("CTLN", 15),
)
SECURITY_PREFIX = types.MappingProxyType(
    {"file": "FS", "image": "IS", "graphic": "SS", "text": "TS", "des": "DES", "res": "RE"}
)

#: Each extension area's length-field and overflow-number names.
AREA_FIELDS = types.MappingProxyType(
    {
        "UDHD": ("UDHDL", "UDHOFL"),
        "XHD": ("XHDL", "XHDLOFL"),
        "UDID": ("UDIDL", "UDOFL"),
        "IXSHD": ("IXSHDL", "IXSOFL"),
        "SXSHD": ("SXSHDL", "SXSOFL"),
        "TXSHD": ("TXSHDL", "TXSOFL"),
    }
)
_AREA_OWNER = {
    "UDHD": "file",
    "XHD": "file",
    "UDID": "image",
    "IXSHD": "image",
    "SXSHD": "graphic",
    "TXSHD": "text",
}

#: Diagnostic code -> whether `validate_source` lists it as a violation of the profile. The last
#: three occur only on a decoded window or a preview, never in `Container.diagnostics`; they are
#: registered so that one record type carries them. Host codes are not in this registry.
DIAGNOSTIC_CODES = types.MappingProxyType(
    {
        "DATE_UNKNOWN": False,
        "DATE_PARTIAL": False,
        "TIME_UNRESOLVED": False,
        "DATE_MALFORMED": True,
        "TEXT_UNINTERPRETED": False,
        "LOCATION_UNINTERPRETED": False,
        "COMPOSITION_DUPLICATE_LEVEL": True,
        "COMPOSITION_MISSING_PARENT": True,
        "COMPOSITION_CYCLE": True,
        "UNSUPPORTED_SAMPLE_TYPE": False,
        "UNSUPPORTED_SAMPLE_LAYOUT": False,
        "COMPRESSION_NOT_ENABLED": False,
        "UNSUPPORTED_COMPRESSION": False,
        "GEOMETRY_INVALID": True,
        "GEOMETRY_UNRESOLVED": False,
        "GEOMETRY_UNSUPPORTED": False,
        "FILL_BITS_NONZERO": False,
        "FILL_BITS_SIGN_EXTENDED": False,
        "COLOUR_INTERPRETATION_UNRESOLVED": False,
    }
)

_DIAGNOSTIC_CODE_SHAPE = re.compile(r"[A-Z][A-Z0-9_]{1,63}")
_DIRECTORY = (
    ("image", "NUMI", "LISH", 6, "LI", 10),
    ("graphic", "NUMS", "LSSH", 4, "LS", 6),
    (None, "NUMX", None, 0, None, 0),
    ("text", "NUMT", "LTSH", 4, "LT", 5),
    ("des", "NUMDES", "LDSH", 4, "LD", 9),
    ("res", "NUMRES", "LRESH", 4, "LRE", 7),
)


# --------------------------------------------------------------------------- errors


def render(code: str, offset: int | None, path: str, explanation: str) -> str:
    """The one string form of an error and of a diagnostic."""
    return f"{code} @byte {'-' if offset is None else offset} {path}: {explanation}"


def _check_stage_offset_path(stage: object, offset: object, path: object) -> None:
    if type(stage) is not str or stage not in STAGES:
        raise TypeError(f"stage must be one of {STAGES}")
    if offset is not None and (type(offset) is not int or offset < 0):
        raise TypeError("offset must be None or an int >= 0")
    if type(path) is not str or not path.startswith("/"):
        raise TypeError("path must be a str starting with '/'")


class NsifError(ValueError):
    """Every coded refusal of the parser, the twin decoder and the argument screen."""

    def __init__(
        self, code: str, stage: str, offset: int | None, path: str, explanation: str
    ) -> None:
        if type(code) is not str or code not in ERROR_CODES:
            raise TypeError(f"code must be one of the section 19 codes, not {code!r}")
        _check_stage_offset_path(stage, offset, path)
        if type(explanation) is not str:
            raise TypeError("explanation must be a str")
        super().__init__(render(code, offset, path, explanation))
        self.code = code
        self.stage = stage
        self.offset = offset
        self.path = path
        self.explanation = explanation

    def __reduce__(self):
        # The default rebuild calls the class with `args`, the rendered string alone, which the
        # five-argument constructor refuses; pickle and copy must rebuild the same refusal (the
        # host's worker moves it between processes).
        return (type(self), (self.code, self.stage, self.offset, self.path, self.explanation))


class NsifInputTooLarge(NsifError, InputTooLarge):
    """E_LIMIT at stage input: the argument is larger than `Limits.input_bytes`."""

    def __init__(self, path: str, explanation: str) -> None:
        super().__init__("E_LIMIT", "input", None, path, explanation)

    def __reduce__(self):
        return (type(self), (self.path, self.explanation))


class NsifInputTooDeep(NsifError, InputTooDeep):
    """E_LIMIT at stage input: a parsed twin nests deeper than `Limits.twin_depth`."""

    def __init__(self, path: str, explanation: str) -> None:
        super().__init__("E_LIMIT", "input", None, path, explanation)

    def __reduce__(self):
        return (type(self), (self.path, self.explanation))


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A non-fatal finding, in the result schema's diagnostic shape. Its code is registered in
    `DIAGNOSTIC_CODES` and never starts with `E_`: an `E_` code always means a refused operation."""

    code: str
    stage: str
    offset: int | None
    path: str
    message: str

    def __post_init__(self) -> None:
        if (
            type(self.code) is not str
            or not _DIAGNOSTIC_CODE_SHAPE.fullmatch(self.code)
            or self.code not in DIAGNOSTIC_CODES
        ):
            raise TypeError(f"{self.code!r} is not a registered diagnostic code")
        _check_stage_offset_path(self.stage, self.offset, self.path)
        if len(self.path) > 256:
            raise TypeError("a diagnostic path is at most 256 characters")
        if type(self.message) is not str or len(self.message) > 512:
            raise TypeError("a diagnostic message is a str of at most 512 characters")

    def __str__(self) -> str:
        return render(self.code, self.offset, self.path, self.message)


def diagnostic_sort_key(diagnostic: Diagnostic) -> tuple:
    """Offsetless first, then ascending offset, code and path."""
    offset = diagnostic.offset
    return (offset is not None, offset or 0, diagnostic.code, diagnostic.path)


# --------------------------------------------------------------------------- limits


@dataclass(frozen=True, slots=True)
class Limits:
    """The fourteen CORE-1 caps. Each may be lowered (tests inject smaller ones) and never
    raised: a value above the CORE-1 default is refused, because a larger cap belongs to a
    separately qualified deployment, not to a caller of this build.

    Five of them cannot be exceeded by any CORE-1 input, so each is enforced at its check site
    and tested with an injected Limits instead of a wire input:

    * `lut_bytes` is unreachable on the wire at the CORE-1 value; enforced and tested with an
      injected Limits (nine LUTs of 99,999 entries are 899,991 octets);
    * `output_objects` is unreachable on the wire at the CORE-1 value; enforced and tested with an
      injected Limits (66 objects need 65 images, and the image cap refuses the 65th first);
    * `output_bytes` is unreachable on the wire at the CORE-1 value; enforced and tested with an
      injected Limits;
    * `window_bytes` is unreachable on the wire at the CORE-1 value; enforced and tested with an
      injected Limits (a request never exceeds its image's payload, because a band may not be
      requested twice);
    * `twin_depth` is unreachable on the wire at the CORE-1 value; enforced and tested with an
      injected Limits (a valid twin has depth 1 and depths 2 to 4 fail its shape check).

    `metadata_bytes` is reachable through the subheader lengths and the overflow DES payloads;
    only its first branch, HL alone above the cap (HL has six digits), is unreachable on the wire
    at the CORE-1 value; enforced and tested with an injected Limits.
    """

    input_bytes: int = 16_777_216
    twin_depth: int = 4
    twin_chars: int = 22_369_624
    segments: int = 256
    images: int = 64
    bands: int = 256
    blocks: int = 65_536
    dimension: int = 1_000_000
    tre_count: int = 4_096
    metadata_bytes: int = 4_194_304
    lut_bytes: int = 1_048_576
    output_objects: int = 65
    output_bytes: int = 67_108_864
    window_bytes: int = 134_217_728

    def __post_init__(self) -> None:
        for spec in dataclass_fields(self):
            value = getattr(self, spec.name)
            if type(value) is not int or not 0 <= value <= spec.default:
                raise ValueError(f"Limits.{spec.name} must be an int in 0..{spec.default}")


#: Read through this module attribute at call time by every entry point, so that a test which
#: replaces it changes what the adapter enforces.
CORE1_LIMITS = Limits()


# --------------------------------------------------------------------------- records


class Slice(NamedTuple):
    """A half-open `[offset, offset + length)` range of the one retained input."""

    offset: int
    length: int


@dataclass(frozen=True, slots=True)
class DateValue:
    slice: Slice
    status: str
    value: datetime.datetime | None


@dataclass(frozen=True, slots=True)
class Location:
    slice: Slice
    row: int | None
    column: int | None


@dataclass(frozen=True, slots=True)
class SecurityBlock:
    scope: str
    owner_index: int | None
    prefix: str
    slice: Slice
    fields: Mapping[str, Slice]
    clas: str | None


@dataclass(frozen=True, slots=True)
class Extension:
    section: str
    owner_kind: str
    owner_index: int | None
    ordinal: int
    origin: str
    des_index: int | None
    tag: str
    slice: Slice
    data: Slice


@dataclass(frozen=True, slots=True)
class ExtensionArea:
    section: str
    owner_kind: str
    owner_index: int | None
    length_field: Slice
    length: int
    overflow_field: Slice | None
    overflow: int
    local: Slice
    tres: tuple[Extension, ...]


@dataclass(frozen=True, slots=True)
class BandRecord:
    index: int
    irepband: str
    nluts: int
    neluts: int
    lut: Slice | None


@dataclass(frozen=True, slots=True)
class Segment:
    kind: str
    index: int
    file_index: int
    subheader: Slice
    data: Slice


@dataclass(frozen=True, slots=True)
class FileHeader:
    fields: Mapping[str, Slice]
    security: SecurityBlock
    fdt: DateValue
    udhd: ExtensionArea
    xhd: ExtensionArea


@dataclass(frozen=True, slots=True)
class ImageRecord:
    index: int
    segment: Segment
    fields: Mapping[str, Slice]
    security: SecurityBlock
    idatim: DateValue
    nrows: int
    ncols: int
    pvtype: str
    irep: str
    icat: str
    abpp: int
    pjust: str
    icords: str
    igeolo: Slice | None
    nicom: int
    ic: str
    comrat: Slice | None
    band_count: int
    bands: tuple[BandRecord, ...]
    isync: int
    imode: str
    nbpr: int
    nbpc: int
    nppbh: int
    nppbv: int
    block_width: int
    block_height: int
    nbpp: int
    idlvl: int
    ialvl: int
    iloc: Location
    imag: Slice
    udid: ExtensionArea
    ixshd: ExtensionArea
    pixel_status: str
    pixel_reason: str | None
    footprint: nsif_geometry.Footprint
    geometry_status: str
    geometry_reason: str | None


@dataclass(frozen=True, slots=True)
class GraphicRecord:
    index: int
    segment: Segment
    fields: Mapping[str, Slice]
    security: SecurityBlock
    sfmt: str
    sdlvl: int
    salvl: int
    sloc: Location
    sbnd1: Location
    sbnd2: Location
    scolor: str
    sxshd: ExtensionArea


@dataclass(frozen=True, slots=True)
class TextRecord:
    index: int
    segment: Segment
    fields: Mapping[str, Slice]
    security: SecurityBlock
    txtalvl: int
    txtdt: DateValue
    txtfmt: str
    txshd: ExtensionArea


@dataclass(frozen=True, slots=True)
class DesRecord:
    index: int
    segment: Segment
    fields: Mapping[str, Slice]
    security: SecurityBlock
    desid: str
    desoflw: str | None
    desitem: int | None
    user_subheader: Slice


@dataclass(frozen=True, slots=True)
class ResRecord:
    index: int
    segment: Segment
    fields: Mapping[str, Slice]
    security: SecurityBlock
    resid: str
    user_subheader: Slice


@dataclass(frozen=True, slots=True)
class Layout:
    """The container's map before any subheader is read: what `read_layout` returns."""

    file_header: FileHeader
    segments: tuple[Segment, ...]
    metadata_bytes: int
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class Container:
    """One parsed container. `raw` is the caller's object itself, the only copy of any source
    octet; every other record addresses it by Slice."""

    raw: bytes = field(repr=False)
    limits: Limits
    profile: str
    signature: str
    clevel: int
    file_size: int
    header_length: int
    file_header: FileHeader
    segments: tuple[Segment, ...]
    images: tuple[ImageRecord, ...]
    graphics: tuple[GraphicRecord, ...]
    texts: tuple[TextRecord, ...]
    des: tuple[DesRecord, ...]
    res: tuple[ResRecord, ...]
    areas: tuple[ExtensionArea, ...]
    extensions: tuple[Extension, ...]
    metadata_bytes: int
    composition_status: str
    diagnostics: tuple[Diagnostic, ...]


# --------------------------------------------------------------------------- pure helpers


def _printable(raw: bytes, start: int, length: int) -> bool:
    for position in range(start, start + length):
        if not 0x20 <= raw[position] <= 0x7E:
            return False
    return True


def ascii_text(raw: bytes, slice: Slice) -> tuple[str | None, str]:
    """A descriptive or raw field's display value: its text with trailing spaces removed and
    `printable_ascii` when every octet is 0x20-0x7E, else `(None, "uninterpreted")`. The slice is
    the field; nothing is escaped or rewritten here (whoever displays the text escapes it)."""
    if not _printable(raw, slice.offset, slice.length):
        return None, "uninterpreted"
    text = raw[slice.offset : slice.offset + slice.length].decode("ascii")
    return text.rstrip(" "), "printable_ascii"


def text_displayable(txtfmt: str, payload: bytes) -> bool:
    """Whether a text segment may be shown as plain text: TXTFMT `STA` and every payload octet
    printable ASCII. CR and LF are not printable, so a multi-line text is download-only. The core
    never calls this on a payload; the host does, and escapes what it shows."""
    return txtfmt == "STA" and _printable(payload, 0, len(payload))


_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _digits(octets: bytes, start: int, width: int) -> int:
    value = 0
    for position in range(start, start + width):
        value = value * 10 + octets[position] - 0x30
    return value


def classify_date(octets: bytes) -> tuple[str, datetime.datetime | None]:
    """The one date grammar of FDT, IDATIM and TXTDT: `(status, value)` where status is
    `valid`, `unknown`, `partial`, `leap_second`, `malformed` or `impossible`, and value is a UTC
    datetime only for `valid`. Security dates are labels and never come here."""
    if octets in (b" " * 14, b"0" * 14):
        return "unknown", None
    if len(octets) == 14 and all(0x30 <= octet <= 0x39 for octet in octets):
        year = _digits(octets, 0, 4)
        month = _digits(octets, 4, 2)
        day = _digits(octets, 6, 2)
        hour = _digits(octets, 8, 2)
        minute = _digits(octets, 10, 2)
        second = _digits(octets, 12, 2)
        if year == 0 or not 1 <= month <= 12 or hour > 23 or minute > 59 or second > 60:
            return "impossible", None
        leap_year = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        last_day = 29 if month == 2 and leap_year else _MONTH_DAYS[month - 1]
        if not 1 <= day <= last_day:
            return "impossible", None
        if second == 60:
            # A UTC instant cannot hold a leap second; the octets stay, the time is unresolved.
            return "leap_second", None
        utc = datetime.timezone.utc
        return "valid", datetime.datetime(year, month, day, hour, minute, second, tzinfo=utc)
    if b"-" in octets and all(0x30 <= octet <= 0x39 or octet == 0x2D for octet in octets):
        return "partial", None
    return "malformed", None


def _location_half(raw: bytes, start: int) -> int | None:
    # Five digits, or a minus and four digits: the tolerant reading of a field the NITF family
    # may sign, which is why location fields are never validated as structural decimals.
    if all(0x30 <= raw[position] <= 0x39 for position in range(start, start + 5)):
        return _digits(raw, start, 5)
    if raw[start] == 0x2D and all(0x30 <= raw[p] <= 0x39 for p in range(start + 1, start + 5)):
        return -_digits(raw, start + 1, 4)
    return None


# --------------------------------------------------------------------------- the cursor


class Cursor:
    """A bounded read position over the one retained input; it never copies the input.

    Every refusal is raised at the first octet of the field (or of the slice that does not fit)
    with the cursor's path prefix and stage. `fields` records the Slice of every field taken,
    under its grammar name, in wire order.
    """

    __slots__ = ("raw", "pos", "end", "path", "stage", "fields")

    def __init__(self, raw: bytes, pos: int, end: int, path: str, stage: str) -> None:
        self.raw = raw
        self.pos = pos
        self.end = end
        self.path = path
        self.stage = stage
        self.fields: dict[str, Slice] = {}

    def field_path(self, name: str) -> str:
        return f"{self.path}/{name}" if name else self.path

    def fail(self, code: str, offset: int, name: str, explanation: str, stage: str | None = None):
        raise NsifError(code, stage or self.stage, offset, self.field_path(name), explanation)

    def take(self, n: int, name: str, *, stage: str | None = None, code: str = "E_LENGTH") -> int:
        """Claim the next `n` octets as field `name` and return their offset."""
        if type(n) is not int or n < 0:
            raise TypeError("take needs an int length >= 0")
        if n > self.end - self.pos:
            self.fail(code, self.pos, name, "the enclosing structure ends inside this field", stage)
        offset = self.pos
        self.pos = offset + n
        self.fields[name] = Slice(offset, n)
        return offset

    def decimal(
        self,
        n: int,
        name: str,
        *,
        stage: str | None = None,
        length_code: str = "E_LENGTH",
        digit_code: str = "E_DIGITS",
    ) -> int:
        """A structural decimal: octets 0x30-0x39 only, never stripped, signed or coerced."""
        offset = self.take(n, name, stage=stage, code=length_code)
        raw = self.raw
        for position in range(offset, offset + n):
            if not 0x30 <= raw[position] <= 0x39:
                self.fail(digit_code, offset, name, "an octet outside 0x30-0x39", stage)
        return _digits(raw, offset, n)

    def ascii(self, n: int, name: str) -> str:
        """An enumerated or identifier field: printable ASCII, returned with trailing spaces
        removed (the form every comparison uses; the raw slice stays in `fields`)."""
        offset = self.take(n, name)
        if not _printable(self.raw, offset, n):
            self.fail("E_FIELD", offset, name, "an octet outside 0x20-0x7E in an enumerated field")
        return self.raw[offset : offset + n].decode("ascii").rstrip(" ")

    def bounded_subcursor(
        self, n: int, name: str, *, path: str | None = None, stage: str | None = None
    ) -> Cursor:
        """Claim `n` octets as field `name` and return a cursor that can read only them."""
        offset = self.take(n, name, stage=stage)
        return Cursor(
            self.raw, offset, offset + n, self.path if path is None else path, stage or self.stage
        )


# --------------------------------------------------------------------------- parse state


class _AreaDraft:
    """An extension area while its overflow TREs may still be appended (phase 5)."""

    __slots__ = (
        "section",
        "owner_kind",
        "owner_index",
        "owner_path",
        "length_field",
        "length",
        "overflow_field",
        "overflow",
        "local",
        "tres",
        "frozen",
    )

    def __init__(self, section, owner_kind, owner_index, owner_path, length_field, length):
        self.section = section
        self.owner_kind = owner_kind
        self.owner_index = owner_index
        self.owner_path = owner_path
        self.length_field = length_field
        self.length = length
        self.overflow_field = None
        self.overflow = 0
        self.local = Slice(length_field.offset + 5, 0)
        self.tres: list[Extension] = []
        self.frozen: ExtensionArea | None = None

    def freeze(self) -> ExtensionArea:
        if self.frozen is None:
            self.frozen = ExtensionArea(
                self.section,
                self.owner_kind,
                self.owner_index,
                self.length_field,
                self.length,
                self.overflow_field,
                self.overflow,
                self.local,
                tuple(self.tres),
            )
        return self.frozen


class _State:
    __slots__ = ("raw", "limits", "tre_count", "areas", "diagnostics")

    def __init__(self, raw: bytes, limits: Limits) -> None:
        self.raw = raw
        self.limits = limits
        # One counter for the whole file: local areas in parse order, then overflow payloads.
        self.tre_count = 0
        self.areas: list[_AreaDraft] = []
        self.diagnostics: list[Diagnostic] = []

    def note(self, code: str, stage: str, offset: int | None, path: str, message: str) -> None:
        self.diagnostics.append(Diagnostic(code, stage, offset, path, message))


def _begin(raw: object, limits: object) -> _State:
    if type(limits) is not Limits:
        raise TypeError("limits must be a Limits instance")
    if type(raw) is not bytes:
        raise NsifError("E_FIELD", "input", None, "/input", "the container must be a bytes object")
    if len(raw) > limits.input_bytes:
        raise NsifInputTooLarge(
            "/input", f"input is {len(raw)} octets; the limit is {limits.input_bytes}"
        )
    return _State(raw, limits)


def _check_signature(raw: bytes) -> None:
    if len(raw) < 9:
        raise NsifError(
            "E_LENGTH", "header", 0, "/file_header/FHDR", "the input ends inside the signature"
        )
    if raw[:9] not in MAGICS:
        raise NsifError(
            "E_MAGIC",
            "header",
            0,
            "/file_header/FHDR",
            "the signature is not NSIF01.01, NSIF01.00 or NITF02.10",
        )


# --------------------------------------------------------------------------- shared field readers

_DATE_DIAGNOSTICS = {
    "unknown": ("DATE_UNKNOWN", "the date is all spaces or all zeros and is not interpreted"),
    "partial": ("DATE_PARTIAL", "the date is a partial value, preserved and not interpreted"),
    "leap_second": ("TIME_UNRESOLVED", "the time names second 60, which no UTC instant holds"),
    "malformed": ("DATE_MALFORMED", "the date is not fourteen digits of a UTC date and time"),
}


def _date(cursor: Cursor, name: str, state: _State) -> DateValue:
    offset = cursor.take(14, name)
    status, value = classify_date(cursor.raw[offset : offset + 14])
    if status == "impossible":
        cursor.fail("E_FIELD", offset, name, "fourteen digits that form no Gregorian UTC instant")
    if status != "valid":
        code, message = _DATE_DIAGNOSTICS[status]
        state.note(code, cursor.stage, offset, cursor.field_path(name), message)
    return DateValue(Slice(offset, 14), status, value)


def _security(cursor: Cursor, scope: str, owner_index: int | None) -> SecurityBlock:
    # Sliced, never validated: once the 167 octets are present no value in them is an error,
    # and a blank or unknown CLAS stays unresolved rather than defaulting to anything.
    offset = cursor.take(167, "security")
    parts = {}
    position = offset
    for name, width in SECURITY_FIELDS:
        parts[name] = Slice(position, width)
        position += width
    octet = cursor.raw[offset]
    clas = chr(octet) if octet in b"URCST" else None
    return SecurityBlock(
        scope,
        owner_index,
        SECURITY_PREFIX[scope],
        Slice(offset, 167),
        types.MappingProxyType(parts),
        clas,
    )


def _encryp(cursor: Cursor) -> None:
    offset = cursor.take(1, "ENCRYP")
    octet = cursor.raw[offset]
    if octet == 0x31:
        cursor.fail("E_ENCRYPTED", offset, "ENCRYP", "the structure declares encryption")
    if octet != 0x30:
        cursor.fail("E_FIELD", offset, "ENCRYP", "ENCRYP is neither 0 nor 1")


def _positive(cursor: Cursor, n: int, name: str) -> int:
    offset = cursor.pos
    value = cursor.decimal(n, name)
    if value == 0:
        cursor.fail("E_FIELD", offset, name, "a field that must be positive is zero")
    return value


def _location(cursor: Cursor, name: str, state: _State) -> Location:
    offset = cursor.take(10, name)
    row = _location_half(cursor.raw, offset)
    column = _location_half(cursor.raw, offset + 5)
    if row is None or column is None:
        state.note(
            "LOCATION_UNINTERPRETED",
            cursor.stage,
            offset,
            cursor.field_path(name),
            "the location is preserved and not interpreted",
        )
        return Location(Slice(offset, 10), None, None)
    return Location(Slice(offset, 10), row, column)


def _text_note(cursor: Cursor, names: tuple[str, ...], state: _State) -> None:
    # One diagnostic per structure, at its first descriptive field that is not printable.
    for name in names:
        part = cursor.fields[name]
        if not _printable(cursor.raw, part.offset, part.length):
            state.note(
                "TEXT_UNINTERPRETED",
                cursor.stage,
                part.offset,
                cursor.field_path(name),
                "descriptive text holds octets outside printable ASCII and is not interpreted",
            )
            return


def _marker(cursor: Cursor, marker: str) -> None:
    offset = cursor.take(2, marker)
    if cursor.raw[offset : offset + 2] != marker.encode("ascii"):
        cursor.fail(
            "E_FIELD", offset, marker, "the segment marker does not match its directory kind"
        )


def _exact_end(cursor: Cursor) -> None:
    if cursor.pos != cursor.end:
        cursor.fail("E_LENGTH", cursor.pos, "", "octets remain after the structure's grammar")


# --------------------------------------------------------------------------- extensions


def _valid_tag(raw: bytes, offset: int) -> bool:
    nonspace = False
    for position in range(offset, offset + 6):
        octet = raw[position]
        if octet == 0x20:
            continue
        if not (0x41 <= octet <= 0x5A or 0x30 <= octet <= 0x39):
            return False
        nonspace = True
    return nonspace


def _frame_tres(
    state: _State,
    area: _AreaDraft,
    start: int,
    end: int,
    path: str,
    origin: str,
    des_index: int | None,
) -> None:
    raw = state.raw
    limit = state.limits.tre_count
    if origin == "overflow":
        # Inside a TRE_OVERFLOW payload every framing fault is the overflow's own (E_OVERFLOW);
        # the TRE-count cap keeps its code.
        length_code = digit_code = tag_code = "E_OVERFLOW"
    else:
        length_code, digit_code, tag_code = "E_LENGTH", "E_DIGITS", "E_FIELD"
    position = start
    k = 0
    while position < end:
        tre_path = f"{path}/tre[{k}]"
        if state.tre_count >= limit:
            raise NsifError(
                "E_LIMIT",
                "extension",
                position,
                tre_path,
                f"the file holds more than {limit} TREs",
            )
        cursor = Cursor(raw, position, end, tre_path, "extension")
        tag_offset = cursor.take(6, "CETAG", code=length_code)
        if not _valid_tag(raw, tag_offset):
            cursor.fail(
                tag_code,
                tag_offset,
                "CETAG",
                "a tag is six octets of A-Z, 0-9 or space with one that is not a space",
            )
        cel = cursor.decimal(5, "CEL", length_code=length_code, digit_code=digit_code)
        data_offset = cursor.take(cel, "CEDATA", code=length_code)
        state.tre_count += 1
        area.tres.append(
            Extension(
                area.section,
                area.owner_kind,
                area.owner_index,
                len(area.tres),
                origin,
                des_index,
                raw[tag_offset : tag_offset + 6].decode("ascii"),
                Slice(tag_offset, 11 + cel),
                Slice(data_offset, cel),
            )
        )
        position = cursor.pos
        k += 1


def _read_area(cursor: Cursor, section: str, owner_index: int | None, state: _State) -> _AreaDraft:
    length_name, overflow_name = AREA_FIELDS[section]
    length_offset = cursor.pos
    length = cursor.decimal(5, length_name, stage="extension")
    area = _AreaDraft(
        section,
        _AREA_OWNER[section],
        owner_index,
        cursor.path,
        Slice(length_offset, 5),
        length,
    )
    state.areas.append(area)
    if length == 0:
        return area
    content = cursor.bounded_subcursor(length, section, stage="extension")
    start = content.pos
    # The three-octet overflow number is counted in L, so an L of 1 or 2 cannot hold it.
    area.overflow = content.decimal(3, overflow_name)
    area.overflow_field = Slice(start, 3)
    area.local = Slice(start + 3, length - 3)
    _frame_tres(state, area, start + 3, start + length, f"{cursor.path}/{section}", "local", None)
    return area


# --------------------------------------------------------------------------- file header


class _HeaderDraft:
    __slots__ = ("fields", "security", "fdt", "udhd", "xhd", "clevel", "fl", "hl", "tables")


def _read_header(state: _State) -> _HeaderDraft:
    raw = state.raw
    limits = state.limits
    _check_signature(raw)
    cursor = Cursor(raw, 0, len(raw), "/file_header", "header")
    cursor.take(4, "FHDR")
    cursor.take(5, "FVER")
    clevel_offset = cursor.pos
    clevel = cursor.decimal(2, "CLEVEL")
    if clevel not in CLEVELS:
        cursor.fail("E_PROFILE", clevel_offset, "CLEVEL", "CLEVEL is not 03, 05, 06, 07 or 09")
    stype = cursor.take(4, "STYPE")
    if raw[stype : stype + 4] != b"BF01":
        cursor.fail("E_PROFILE", stype, "STYPE", "STYPE is not BF01")
    cursor.take(10, "OSTAID")
    fdt = _date(cursor, "FDT", state)
    cursor.take(80, "FTITLE")
    security = _security(cursor, "file", None)
    cursor.take(5, "FSCOP")
    cursor.take(5, "FSCPYS")
    _encryp(cursor)
    cursor.take(3, "FBKGC")
    cursor.take(24, "ONAME")
    cursor.take(18, "OPHONE")
    fl_offset = cursor.pos
    fl = cursor.decimal(12, "FL")
    if fl != len(raw):
        # Sentinel and streaming lengths, concatenated files and trailing octets all land here.
        cursor.fail("E_LENGTH", fl_offset, "FL", "FL differs from the input length")
    hl_offset = cursor.pos
    hl = cursor.decimal(6, "HL")
    if not 388 <= hl <= fl:
        cursor.fail("E_LENGTH", hl_offset, "HL", "HL is outside 388..FL")
    # From the directory on the header ends at HL, so a directory that overruns HL fails at the
    # first field that crosses it rather than somewhere later in the walk.
    cursor.end = hl
    tables: dict[str, list[tuple[int, int]]] = {}
    total = 0
    for kind, count_name, sub_name, sub_width, data_name, data_width in _DIRECTORY:
        count_offset = cursor.pos
        count = cursor.decimal(3, count_name)
        if kind is None:
            if count != 0:
                cursor.fail("E_PROFILE", count_offset, count_name, "NUMX is not 000")
            continue
        if kind == "image" and count > limits.images:
            cursor.fail(
                "E_LIMIT", count_offset, count_name, f"more than {limits.images} image segments"
            )
        total += count
        if total > limits.segments:
            cursor.fail(
                "E_LIMIT", count_offset, count_name, f"more than {limits.segments} segments"
            )
        entries = []
        for k in range(count):
            sub_length = cursor.decimal(sub_width, f"{sub_name}[{k}]")
            data_length = cursor.decimal(data_width, f"{data_name}[{k}]")
            entries.append((sub_length, data_length))
        tables[kind] = entries
    udhd = _read_area(cursor, "UDHD", None, state)
    xhd = _read_area(cursor, "XHD", None, state)
    if cursor.pos != hl:
        cursor.fail("E_LENGTH", cursor.pos, "", "the header octets do not end at HL")
    _text_note(cursor, ("OSTAID", "FTITLE", "ONAME", "OPHONE"), state)
    header = _HeaderDraft()
    header.fields = cursor.fields
    header.security = security
    header.fdt = fdt
    header.udhd = udhd
    header.xhd = xhd
    header.clevel = clevel
    header.fl = fl
    header.hl = hl
    header.tables = tables
    return header


def _freeze_header(header: _HeaderDraft) -> FileHeader:
    return FileHeader(
        types.MappingProxyType(dict(header.fields)),
        header.security,
        header.fdt,
        header.udhd.freeze(),
        header.xhd.freeze(),
    )


def _walk(state: _State, header: _HeaderDraft) -> tuple[tuple[Segment, ...], int]:
    """Locate every segment from the validated lengths alone; nothing is searched for."""
    fl = header.fl
    position = header.hl
    segments = []
    file_index = 0
    for kind in KINDS:
        for index, (sub_length, data_length) in enumerate(header.tables[kind]):
            base = f"/segments/{kind}[{index}]"
            if position + sub_length > fl:
                raise NsifError(
                    "E_LENGTH",
                    "segment",
                    position,
                    base + "/subheader",
                    "the subheader ends past FL",
                )
            data_offset = position + sub_length
            if data_offset + data_length > fl:
                raise NsifError(
                    "E_LENGTH", "segment", data_offset, base + "/data", "the data ends past FL"
                )
            segments.append(
                Segment(
                    kind,
                    index,
                    file_index,
                    Slice(position, sub_length),
                    Slice(data_offset, data_length),
                )
            )
            position = data_offset + data_length
            file_index += 1
    if position != fl:
        raise NsifError("E_LENGTH", "segment", position, "/segments", "the segments end before FL")
    # The metadata charge: HL, then every subheader once. Image, graphic and text data and the
    # payloads of DES and RES the core never parses are preserved slices and are not charged.
    cap = state.limits.metadata_bytes
    metadata = header.hl
    if metadata > cap:
        raise NsifError(
            "E_LIMIT",
            "segment",
            header.fields["HL"].offset,
            "/file_header/HL",
            f"parsed metadata exceeds {cap} octets",
        )
    for segment in segments:
        metadata += segment.subheader.length
        if metadata > cap:
            raise NsifError(
                "E_LIMIT",
                "segment",
                segment.subheader.offset,
                f"/segments/{segment.kind}[{segment.index}]/subheader",
                f"parsed metadata exceeds {cap} octets",
            )
    return tuple(segments), metadata


# --------------------------------------------------------------------------- subheaders


def _read_image(cursor: Cursor, segment: Segment, state: _State) -> dict:
    limits = state.limits
    raw = cursor.raw
    index = segment.index
    _marker(cursor, "IM")
    cursor.take(10, "IID1")
    idatim = _date(cursor, "IDATIM", state)
    cursor.take(17, "TGTID")
    cursor.take(80, "IID2")
    security = _security(cursor, "image", index)
    _encryp(cursor)
    cursor.take(42, "ISORCE")
    dimensions = []
    for name in ("NROWS", "NCOLS"):
        offset = cursor.pos
        value = _positive(cursor, 8, name)
        if value > limits.dimension:
            cursor.fail("E_LIMIT", offset, name, f"a dimension above {limits.dimension}")
        dimensions.append(value)
    nrows, ncols = dimensions
    pvtype = cursor.ascii(3, "PVTYPE")
    irep = cursor.ascii(8, "IREP")
    icat = cursor.ascii(8, "ICAT")
    abpp = _positive(cursor, 2, "ABPP")
    offset = cursor.take(1, "PJUST")
    pjust = chr(raw[offset])
    if pjust not in ("L", "R"):
        cursor.fail("E_FIELD", offset, "PJUST", "PJUST is neither L nor R")
    offset = cursor.pos
    cursor.ascii(1, "ICORDS")
    icords = chr(raw[offset])
    # A non-blank ICORDS dictates the 60 octets whatever its value means.
    igeolo = Slice(cursor.take(60, "IGEOLO"), 60) if icords != " " else None
    nicom = cursor.decimal(1, "NICOM")
    for k in range(nicom):
        cursor.take(80, f"ICOM[{k}]")
    offset = cursor.take(2, "IC")
    if not all(0x41 <= o <= 0x5A or 0x30 <= o <= 0x39 for o in raw[offset : offset + 2]):
        cursor.fail("E_FIELD", offset, "IC", "IC is not two octets of A-Z or 0-9")
    ic = raw[offset : offset + 2].decode("ascii")
    comrat = Slice(cursor.take(4, "COMRAT"), 4) if ic not in ("NC", "NM") else None
    offset = cursor.pos
    band_count = cursor.decimal(1, "NBANDS")
    band_field = "NBANDS"
    if band_count == 0:
        offset = cursor.pos
        band_count = _positive(cursor, 5, "XBANDS")
        band_field = "XBANDS"
    if band_count > limits.bands:
        cursor.fail("E_LIMIT", offset, band_field, f"more than {limits.bands} bands")
    bands = []
    for b in range(band_count):
        prefix = f"band[{b}]/"
        irepband = cursor.ascii(2, prefix + "IREPBAND")
        cursor.take(6, prefix + "ISUBCAT")
        cursor.take(1, prefix + "IFC")
        cursor.take(3, prefix + "IMFLT")
        nluts = cursor.decimal(1, prefix + "NLUTS")
        neluts = 0
        lut = None
        if nluts > 0:
            offset = cursor.pos
            neluts = cursor.decimal(5, prefix + "NELUTS")
            # Checked before the LUT octets are claimed: the product is the allocation a decoder
            # would make.
            if nluts * neluts > limits.lut_bytes:
                cursor.fail(
                    "E_LIMIT", offset, prefix + "NELUTS", f"a LUT above {limits.lut_bytes} octets"
                )
            lut = Slice(cursor.take(nluts * neluts, prefix + "LUTD"), nluts * neluts)
        bands.append(BandRecord(b, irepband, nluts, neluts, lut))
    isync = cursor.decimal(1, "ISYNC")
    offset = cursor.take(1, "IMODE")
    imode = chr(raw[offset])
    if imode not in ("B", "P", "R", "S"):
        cursor.fail("E_FIELD", offset, "IMODE", "IMODE is not B, P, R or S")
    nbpr = _positive(cursor, 4, "NBPR")
    nbpc = _positive(cursor, 4, "NBPC")
    nppbh = cursor.decimal(4, "NPPBH")
    nppbv = cursor.decimal(4, "NPPBV")
    fields = cursor.fields

    def relation(code: str, name: str, explanation: str) -> None:
        cursor.fail(code, fields[name].offset, name, explanation)

    # The grid relations run here, as soon as their last operand is read, so that a later fault
    # in the same subheader cannot mask them.
    if nppbh == 0 and nbpr != 1:
        relation("E_FIELD", "NPPBH", "NPPBH of zero needs NBPR of one")
    if nppbv == 0 and nbpc != 1:
        relation("E_FIELD", "NPPBV", "NPPBV of zero needs NBPC of one")
    width = ncols if nppbh == 0 else nppbh
    height = nrows if nppbv == 0 else nppbv
    if nbpr * nbpc > limits.blocks:
        relation("E_LIMIT", "NBPR", f"more than {limits.blocks} blocks")
    if nbpr * width < ncols:
        relation("E_FIELD", "NBPR", "the block grid does not cover NCOLS")
    if nbpc * height < nrows:
        relation("E_FIELD", "NBPC", "the block grid does not cover NROWS")
    if (nbpr - 1) * width >= ncols:
        relation("E_PROFILE", "NBPR", "the block grid is not minimally covering")
    if (nbpc - 1) * height >= nrows:
        relation("E_PROFILE", "NBPC", "the block grid is not minimally covering")
    nbpp = _positive(cursor, 2, "NBPP")
    if abpp > nbpp:
        relation("E_FIELD", "ABPP", "ABPP exceeds NBPP")
    idlvl = _positive(cursor, 3, "IDLVL")
    ialvl = cursor.decimal(3, "IALVL")
    iloc = _location(cursor, "ILOC", state)
    imag = Slice(cursor.take(4, "IMAG"), 4)
    udid = _read_area(cursor, "UDID", index, state)
    ixshd = _read_area(cursor, "IXSHD", index, state)
    _exact_end(cursor)
    comments = tuple(f"ICOM[{k}]" for k in range(nicom))
    _text_note(cursor, ("IID1", "TGTID", "IID2", "ISORCE") + comments, state)
    pixel_status, pixel_reason = _assess_pixels(
        cursor, segment, state, ic, pvtype, nbpp, imode, band_count, nbpr, nbpc, width, height
    )
    return {
        "index": index,
        "segment": segment,
        "fields": types.MappingProxyType(dict(fields)),
        "security": security,
        "idatim": idatim,
        "nrows": nrows,
        "ncols": ncols,
        "pvtype": pvtype,
        "irep": irep,
        "icat": icat,
        "abpp": abpp,
        "pjust": pjust,
        "icords": icords,
        "igeolo": igeolo,
        "nicom": nicom,
        "ic": ic,
        "comrat": comrat,
        "band_count": band_count,
        "bands": tuple(bands),
        "isync": isync,
        "imode": imode,
        "nbpr": nbpr,
        "nbpc": nbpc,
        "nppbh": nppbh,
        "nppbv": nppbv,
        "block_width": width,
        "block_height": height,
        "nbpp": nbpp,
        "idlvl": idlvl,
        "ialvl": ialvl,
        "iloc": iloc,
        "imag": imag,
        "udid": udid,
        "ixshd": ixshd,
        "pixel_status": pixel_status,
        "pixel_reason": pixel_reason,
    }


def _pixel_cell(
    ic: str, pvtype: str, nbpp: int, imode: str, band_count: int, nbpr: int, nbpc: int
) -> tuple[str, str | None, str | None, str | None, str | None]:
    """The one pixel-cell table, first matching row: `(status, reason, code, deciding field,
    message)`, the last four None for the native cell. The inventory records it and a window
    request refuses by it, so the two can never disagree."""
    if ic in NAMED_COMPRESSION:
        return (
            "unsupported",
            "compression_not_enabled",
            "COMPRESSION_NOT_ENABLED",
            "IC",
            "no pixel path is enabled for this compression code in this deployment",
        )
    if ic != "NC":
        return (
            "unsupported",
            "unsupported_compression",
            "UNSUPPORTED_COMPRESSION",
            "IC",
            "compression code is not one this profile names",
        )
    for field_name, native in (("PVTYPE", pvtype in ("INT", "SI")), ("NBPP", nbpp in (8, 16))):
        if not native:
            return (
                "unsupported",
                "unsupported_sample_type",
                "UNSUPPORTED_SAMPLE_TYPE",
                field_name,
                "no native sample path for this sample type",
            )
    if imode == "S" and (band_count < 2 or nbpr * nbpc < 2):
        return (
            "unsupported",
            "unsupported_sample_layout",
            "UNSUPPORTED_SAMPLE_LAYOUT",
            "IMODE",
            "IMODE S needs at least two bands and two blocks in this profile",
        )
    return "native_supported", None, None, None, None


def _assess_pixels(
    cursor: Cursor,
    segment: Segment,
    state: _State,
    ic: str,
    pvtype: str,
    nbpp: int,
    imode: str,
    band_count: int,
    nbpr: int,
    nbpc: int,
    width: int,
    height: int,
) -> tuple[str, str | None]:
    """The image's pixel cell, decided once: native, or unsupported with one diagnostic. No
    sample octet is read; only a native cell's data length is compared with its formula."""
    status, reason, code, name, message = _pixel_cell(
        ic, pvtype, nbpp, imode, band_count, nbpr, nbpc
    )
    if code is not None:
        offset = cursor.fields[name].offset
        state.note(code, "pixels", offset, cursor.field_path(name), message)
        return status, reason
    # Pad pixels of partial edge blocks are counted: LI covers whole physical blocks.
    expected = nbpr * nbpc * width * height * band_count * (nbpp // 8)
    if expected != segment.data.length:
        raise NsifError(
            "E_LENGTH",
            "segment",
            segment.data.offset,
            cursor.field_path("data"),
            "the data length differs from the native sample length",
        )
    return status, reason


def _read_graphic(cursor: Cursor, segment: Segment, state: _State) -> dict:
    index = segment.index
    _marker(cursor, "SY")
    cursor.take(10, "SID")
    cursor.take(20, "SNAME")
    security = _security(cursor, "graphic", index)
    _encryp(cursor)
    sfmt = cursor.ascii(1, "SFMT")
    cursor.take(13, "SSTRUCT")
    sdlvl = _positive(cursor, 3, "SDLVL")
    salvl = cursor.decimal(3, "SALVL")
    sloc = _location(cursor, "SLOC", state)
    sbnd1 = _location(cursor, "SBND1", state)
    scolor = cursor.ascii(1, "SCOLOR")
    sbnd2 = _location(cursor, "SBND2", state)
    cursor.take(2, "SRES2")
    sxshd = _read_area(cursor, "SXSHD", index, state)
    _exact_end(cursor)
    _text_note(cursor, ("SID", "SNAME"), state)
    return {
        "index": index,
        "segment": segment,
        "fields": types.MappingProxyType(dict(cursor.fields)),
        "security": security,
        "sfmt": sfmt,
        "sdlvl": sdlvl,
        "salvl": salvl,
        "sloc": sloc,
        "sbnd1": sbnd1,
        "sbnd2": sbnd2,
        "scolor": scolor,
        "sxshd": sxshd,
    }


def _read_text(cursor: Cursor, segment: Segment, state: _State) -> dict:
    index = segment.index
    _marker(cursor, "TE")
    cursor.take(7, "TEXTID")
    txtalvl = cursor.decimal(3, "TXTALVL")
    txtdt = _date(cursor, "TXTDT", state)
    cursor.take(80, "TXTITL")
    security = _security(cursor, "text", index)
    _encryp(cursor)
    txtfmt = cursor.ascii(3, "TXTFMT")
    txshd = _read_area(cursor, "TXSHD", index, state)
    _exact_end(cursor)
    _text_note(cursor, ("TEXTID", "TXTITL"), state)
    return {
        "index": index,
        "segment": segment,
        "fields": types.MappingProxyType(dict(cursor.fields)),
        "security": security,
        "txtalvl": txtalvl,
        "txtdt": txtdt,
        "txtfmt": txtfmt,
        "txshd": txshd,
    }


def _read_des(cursor: Cursor, segment: Segment, state: _State) -> dict:
    index = segment.index
    _marker(cursor, "DE")
    desid = cursor.ascii(25, "DESID")
    cursor.take(2, "DESVER")
    security = _security(cursor, "des", index)
    desoflw = None
    desitem = None
    # Exactly TRE_OVERFLOW after trailing-space removal; every other DES payload stays opaque,
    # XML_DATA_CONTENT and embedded containers included.
    if desid == "TRE_OVERFLOW":
        desoflw = cursor.ascii(6, "DESOFLW")
        desitem = cursor.decimal(3, "DESITEM")
    user_length = cursor.decimal(4, "DESSHL")
    user = Slice(cursor.take(user_length, "DESSHF"), user_length)
    _exact_end(cursor)
    return {
        "index": index,
        "segment": segment,
        "fields": types.MappingProxyType(dict(cursor.fields)),
        "security": security,
        "desid": desid,
        "desoflw": desoflw,
        "desitem": desitem,
        "user_subheader": user,
    }


def _read_res(cursor: Cursor, segment: Segment, state: _State) -> dict:
    index = segment.index
    _marker(cursor, "RE")
    resid = cursor.ascii(25, "RESID")
    cursor.take(2, "RESVER")
    security = _security(cursor, "res", index)
    user_length = cursor.decimal(4, "RESSHL")
    user = Slice(cursor.take(user_length, "RESSHF"), user_length)
    _exact_end(cursor)
    return {
        "index": index,
        "segment": segment,
        "fields": types.MappingProxyType(dict(cursor.fields)),
        "security": security,
        "resid": resid,
        "user_subheader": user,
    }


_READERS = {
    "image": _read_image,
    "graphic": _read_graphic,
    "text": _read_text,
    "des": _read_des,
    "res": _read_res,
}
_RECORDS = {
    "image": ImageRecord,
    "graphic": GraphicRecord,
    "text": TextRecord,
    "des": DesRecord,
    "res": ResRecord,
}
_AREA_KEYS = ("udid", "ixshd", "sxshd", "txshd")


def _subheader_cursor(raw: bytes, segment: Segment) -> Cursor:
    start = segment.subheader.offset
    return Cursor(
        raw,
        start,
        start + segment.subheader.length,
        f"/segments/{segment.kind}[{segment.index}]",
        "segment",
    )


def _freeze_record(kind: str, values: dict):
    frozen = dict(values)
    for key in _AREA_KEYS:
        if key in frozen:
            frozen[key] = frozen[key].freeze()
    return _RECORDS[kind](**frozen)


# --------------------------------------------------------------------------- overflow


def _resolve_overflow(state: _State, des: list[dict], metadata: int) -> int:
    """Phase 5: every area that names an overflow DES, in parse order; then the orphans."""
    raw = state.raw
    cap = state.limits.metadata_bytes
    used: set[int] = set()
    for area in state.areas:
        number = area.overflow
        if number == 0:
            continue
        offset = area.overflow_field.offset
        path = f"{area.owner_path}/{AREA_FIELDS[area.section][1]}"

        def refuse(explanation: str) -> None:
            raise NsifError("E_OVERFLOW", "extension", offset, path, explanation)

        if number > len(des):
            refuse("the overflow number names no DES segment")
        record = des[number - 1]
        if record["desid"] != "TRE_OVERFLOW":
            refuse("the named DES is not a TRE_OVERFLOW DES")
        named = record["fields"]["DESOFLW"]
        if raw[named.offset : named.offset + 6] != area.section.ljust(6).encode("ascii"):
            refuse("DESOFLW does not name the referring area")
        owner = 0 if area.owner_kind == "file" else area.owner_index + 1
        if record["desitem"] != owner:
            refuse("DESITEM does not name the owning segment")
        if number in used:
            refuse("the overflow DES is already referenced by an earlier area")
        used.add(number)
        data = record["segment"].data
        metadata += data.length
        if metadata > cap:
            raise NsifError(
                "E_LIMIT", "extension", offset, path, f"parsed metadata exceeds {cap} octets"
            )
        _frame_tres(
            state,
            area,
            data.offset,
            data.offset + data.length,
            f"/segments/des[{number - 1}]/data",
            "overflow",
            number - 1,
        )
    for index, record in enumerate(des):
        if record["desid"] == "TRE_OVERFLOW" and index + 1 not in used:
            raise NsifError(
                "E_OVERFLOW",
                "extension",
                record["segment"].subheader.offset,
                f"/segments/des[{index}]",
                "a TRE_OVERFLOW DES is referenced by no extension area",
            )
    return metadata


# --------------------------------------------------------------------------- inventory


def _composition(images: list[dict], graphics: list[dict], state: _State) -> str:
    """Display levels and attachment of images and graphics; never fatal. Text segments are
    not displayable items."""
    items = []
    for kind, records, level_name, parent_name in (
        ("image", images, "IDLVL", "IALVL"),
        ("graphic", graphics, "SDLVL", "SALVL"),
    ):
        level_key = level_name.lower()
        parent_key = parent_name.lower()
        for record in records:
            base = f"/segments/{kind}[{record['index']}]"
            items.append(
                (
                    record[level_key],
                    record[parent_key],
                    record["fields"][level_name].offset,
                    f"{base}/{level_name}",
                    record["fields"][parent_name].offset,
                    f"{base}/{parent_name}",
                )
            )
    found = False
    owners: dict[int, tuple] = {}
    order: dict[int, int] = {}
    for item in items:
        level = item[0]
        if level in owners:
            found = True
            state.note(
                "COMPOSITION_DUPLICATE_LEVEL",
                "segment",
                item[2],
                item[3],
                "the display level is already used by an earlier image or graphic",
            )
        else:
            owners[level] = item
            order[level] = len(order)
    for item in items:
        if item[1] != 0 and item[1] not in owners:
            found = True
            state.note(
                "COMPOSITION_MISSING_PARENT",
                "segment",
                item[4],
                item[5],
                "the attachment level names no display level in this file",
            )
    reported: set[int] = set()
    for start in owners:
        chain: list[int] = []
        visited: set[int] = set()
        level = start
        while level != 0 and level in owners and level not in visited:
            chain.append(level)
            visited.add(level)
            level = owners[level][1]
        if level in visited:
            cycle = chain[chain.index(level) :]
            if reported.isdisjoint(cycle):
                reported.update(cycle)
                found = True
                first = owners[min(cycle, key=order.__getitem__)]
                state.note(
                    "COMPOSITION_CYCLE",
                    "segment",
                    first[4],
                    first[5],
                    "the attachment levels form a cycle",
                )
    return "unavailable" if found else "segment_only"


#: A footprint finding -> its diagnostic code, the field it is reported at and its fixed message.
#: Only the four source defects are GEOMETRY_INVALID (a violation of the profile); a corner set
#: outside this profile's assumptions stays unresolved, and a coordinate system it does not
#: project is preserved, so neither is a violation.
_GEOMETRY_DIAGNOSTICS = types.MappingProxyType(
    {
        "icords_unsupported": (
            "GEOMETRY_UNSUPPORTED",
            "ICORDS",
            "ICORDS names a coordinate system this profile preserves but does not project",
        ),
        "corner_syntax": (
            "GEOMETRY_INVALID",
            "IGEOLO",
            "corner text does not match the ICORDS grammar",
        ),
        "corner_range": ("GEOMETRY_INVALID", "IGEOLO", "corner value is outside its valid range"),
        "pole_corner": ("GEOMETRY_UNRESOLVED", "IGEOLO", "a corner lies exactly on a pole"),
        "ambiguous_edge": (
            "GEOMETRY_UNRESOLVED",
            "IGEOLO",
            "two consecutive corners are exactly 180 degrees of longitude apart",
        ),
        "span": (
            "GEOMETRY_UNRESOLVED",
            "IGEOLO",
            "the footprint spans 180 degrees of longitude or more",
        ),
        "degenerate": (
            "GEOMETRY_INVALID",
            "IGEOLO",
            "the corners do not enclose a nonzero area",
        ),
        "self_intersection": ("GEOMETRY_INVALID", "IGEOLO", "the corner ring intersects itself"),
        "seam_fragment": (
            "GEOMETRY_UNRESOLVED",
            "IGEOLO",
            "clipping at the antimeridian does not give simple parts",
        ),
    }
)


def _geometry(image: dict, raw: bytes, state: _State) -> None:
    """Phase 6 for one image draft: its footprint, whatever its pixel cell, and at most one
    diagnostic. The geometry module returns a record for every input, so nothing here raises."""
    igeolo = image["igeolo"]
    octets = None if igeolo is None else raw[igeolo.offset : igeolo.offset + igeolo.length]
    found = nsif_geometry.footprint(image["icords"], octets)
    image["footprint"] = found
    image["geometry_status"] = found.status
    image["geometry_reason"] = found.reason
    if found.reason is not None:
        code, name, message = _GEOMETRY_DIAGNOSTICS[found.reason]
        offset = image["fields"][name].offset
        state.note(code, "geometry", offset, f"/segments/image[{image['index']}]/{name}", message)


# --------------------------------------------------------------------------- entry points


def parse_container(raw: bytes, limits: Limits) -> Container:
    """One container, parsed in the fixed check order, or the first fatal NsifError."""
    state = _begin(raw, limits)
    header = _read_header(state)
    segments, metadata = _walk(state, header)
    drafts: dict[str, list[dict]] = {kind: [] for kind in KINDS}
    for segment in segments:
        reader = _READERS[segment.kind]
        drafts[segment.kind].append(reader(_subheader_cursor(raw, segment), segment, state))
    metadata = _resolve_overflow(state, drafts["des"], metadata)
    composition_status = _composition(drafts["image"], drafts["graphic"], state)
    for image in drafts["image"]:
        _geometry(image, raw, state)
    records = {
        kind: tuple(_freeze_record(kind, values) for values in drafts[kind]) for kind in KINDS
    }
    areas = tuple(area.freeze() for area in state.areas)
    return Container(
        raw=raw,
        limits=limits,
        profile=PROFILE,
        signature=raw[:9].decode("ascii"),
        clevel=header.clevel,
        file_size=header.fl,
        header_length=header.hl,
        file_header=_freeze_header(header),
        segments=segments,
        images=records["image"],
        graphics=records["graphic"],
        texts=records["text"],
        des=records["des"],
        res=records["res"],
        areas=areas,
        extensions=tuple(tre for area in areas for tre in area.tres),
        metadata_bytes=metadata,
        composition_status=composition_status,
        diagnostics=tuple(sorted(state.diagnostics, key=diagnostic_sort_key)),
    )


def read_layout(raw: bytes, limits: Limits) -> Layout:
    """Fuzz seam `cursor`: the file header, the directory, the file's own extension areas (local
    TREs only), the segment walk and the metadata charge over a whole input, exactly as
    `parse_container` runs them, without reading any subheader."""
    state = _begin(raw, limits)
    header = _read_header(state)
    segments, metadata = _walk(state, header)
    return Layout(
        _freeze_header(header),
        segments,
        metadata,
        tuple(sorted(state.diagnostics, key=diagnostic_sort_key)),
    )


def extension_area(
    raw: bytes, section: str, limits: Limits, overflow_at: int | None = None
) -> ExtensionArea:
    """Fuzz seam `extensions`: one extension area of kind `section`, its five-digit length field
    first, read from `raw[:overflow_at]` (all of `raw` when `overflow_at` is None) as its
    enclosing structure, which it must fill exactly; its local TREs framed as the parser frames
    them. With `overflow_at`, `raw[overflow_at:]` is the payload of the TRE_OVERFLOW DES the
    area's overflow number names, framed as phase 5 frames it (continuation TREs, overflow
    codes); the association checks against a DES table belong to `parse_container`. Slices are
    offsets into `raw`; segment areas belong to segment 0 of their kind."""
    if type(section) is not str or section not in AREA_FIELDS:
        raise TypeError(f"section must be one of {tuple(AREA_FIELDS)}")
    state = _begin(raw, limits)
    if overflow_at is not None and (
        type(overflow_at) is not int or not 0 <= overflow_at <= len(raw)
    ):
        raise TypeError("overflow_at must be None or an int in 0..len(raw)")
    end = len(raw) if overflow_at is None else overflow_at
    owner_kind = _AREA_OWNER[section]
    owner_index = None if owner_kind == "file" else 0
    path = "/file_header" if owner_kind == "file" else f"/segments/{owner_kind}[0]"
    cursor = Cursor(raw, 0, end, path, "extension")
    area = _read_area(cursor, section, owner_index, state)
    if cursor.pos != end:
        cursor.fail("E_LENGTH", cursor.pos, "", "octets remain after the extension area")
    if overflow_at is not None:
        if area.overflow == 0:
            raise NsifError(
                "E_OVERFLOW",
                "extension",
                overflow_at,
                "/segments/des[0]",
                "an overflow payload that no extension area names",
            )
        des_index = area.overflow - 1
        _frame_tres(
            state,
            area,
            overflow_at,
            len(raw),
            f"/segments/des[{des_index}]/data",
            "overflow",
            des_index,
        )
    return area.freeze()


def image_subheader(
    raw: bytes, limits: Limits, data_length: int = 0
) -> tuple[ImageRecord, tuple[Diagnostic, ...]]:
    """Fuzz seam `image_subheader`: `raw` read whole as the subheader of image 0, by the
    parser's own image grammar, with `data_length` standing in for LI in the native length check;
    returns the record (its areas with their local TREs only, its footprint as the inventory
    computes it) and its diagnostics, sorted. The record's data slice starts where `raw` ends, as
    it would in a container."""
    if type(data_length) is not int or data_length < 0:
        raise TypeError("data_length must be an int >= 0")
    state = _begin(raw, limits)
    segment = Segment("image", 0, 0, Slice(0, len(raw)), Slice(len(raw), data_length))
    values = _read_image(_subheader_cursor(raw, segment), segment, state)
    _geometry(values, raw, state)
    return (
        _freeze_record("image", values),
        tuple(sorted(state.diagnostics, key=diagnostic_sort_key)),
    )


# --------------------------------------------------------------------------- the window decoder

#: The returned element type, decided by (PVTYPE, NBPP) alone: ABPP and PJUST never narrow it, so
#: a 12-bit sample in 16 is a 16-bit element. A storage window is unsigned by NBPP.
_DTYPES = types.MappingProxyType(
    {("INT", 8): "uint8", ("INT", 16): "uint16", ("SI", 8): "int8", ("SI", 16): "int16"}
)
_IMODES = ("B", "P", "R", "S")


@dataclass(frozen=True, slots=True)
class SampleWindow:
    """One decoded window: `data` holds `[band][row][column]` elements in request band order, rows
    top to bottom, no row padding, each element 1 or 2 octets big-endian (two's complement for the
    signed types), so no host byte order or array type is involved. `kind` is `interpreted` (the
    ABPP-bit values) or `storage` (the unsigned integers on the wire); only an interpreted window
    counts discarded bits, over the samples it returns."""

    image_index: int
    x: int
    y: int
    width: int
    height: int
    bands: tuple[int, ...]
    kind: str
    dtype: str
    data: bytes
    fill_bits_nonzero: int
    fill_bits_sign_extended: int
    diagnostics: tuple[Diagnostic, ...]

    @property
    def shape(self) -> tuple[int, int, int]:
        return (len(self.bands), self.height, self.width)

    @property
    def itemsize(self) -> int:
        return 2 if self.dtype in ("uint16", "int16") else 1

    def values(self) -> tuple[int, ...]:
        """The elements as Python ints, band-major."""
        size = self.itemsize
        signed = self.dtype in ("int8", "int16")
        data = self.data
        return tuple(
            int.from_bytes(data[at : at + size], "big", signed=signed)
            for at in range(0, len(data), size)
        )


def _sample_index(
    imode: str,
    nbpr: int,
    nbpc: int,
    block_width: int,
    block_height: int,
    bands: int,
    x: int,
    y: int,
    band: int,
) -> int:
    bc, ix = divmod(x, block_width)
    br, iy = divmod(y, block_height)
    q = br * nbpr + bc
    if imode == "B":
        return ((q * bands + band) * block_height + iy) * block_width + ix
    if imode == "P":
        return ((q * block_height + iy) * block_width + ix) * bands + band
    if imode == "R":
        return ((q * block_height + iy) * bands + band) * block_width + ix
    return ((band * (nbpr * nbpc) + q) * block_height + iy) * block_width + ix


def sample_index(
    imode: str,
    nbpr: int,
    nbpc: int,
    block_width: int,
    block_height: int,
    bands: int,
    x: int,
    y: int,
    band: int,
) -> int:
    """The sample index j (before multiplying by octets per sample) of physical position (x, y)
    in `band`, by the interleave mode's formula. The only place the four formulas are written.

    The physical grid is addressable, pad positions included (a window request refuses them
    first). Inside its domain the map from (x, y, band) to j is a bijection onto
    `range(nbpr * nbpc * block_width * block_height * bands)`, so no index leaves the data
    segment; outside it the arguments are refused."""
    integers = (nbpr, nbpc, block_width, block_height, bands, x, y, band)
    if (
        type(imode) is not str
        or imode not in _IMODES
        or any(type(value) is not int for value in integers)
        or min(nbpr, nbpc, block_width, block_height, bands) < 1
        or not 0 <= x < nbpr * block_width
        or not 0 <= y < nbpc * block_height
        or not 0 <= band < bands
    ):
        raise NsifError(
            "E_FIELD", "pixels", None, "/window", "sample index argument outside the native layout"
        )
    return _sample_index(imode, nbpr, nbpc, block_width, block_height, bands, x, y, band)


def decode_nc_window(
    container: Container,
    image_index: int,
    x: int,
    y: int,
    width: int,
    height: int,
    bands: tuple[int, ...],
    *,
    storage: bool = False,
) -> SampleWindow:
    """The samples of one window of one native image: interpreted (PJUST and SI applied, never
    scaled, looked up or converted to colour) or, with `storage=True`, the unsigned integers on
    the wire for comparison with an independent reader. Pure; the cap comes from the Limits the
    container was parsed with.

    The request is checked in a fixed order and the first failure refuses it with stage `pixels`:
    the container, the image index, the storage flag, the image's pixel cell, the four coordinates'
    types, their signs, the raster bounds (pad pixels are never addressable), the band tuple, the
    output size against the window cap, and a recheck of the data length. Only then is the output
    allocated, once, and every sample read directly from its indexed position."""

    def refuse(code: str, path: str, explanation: str, offset: int | None = None):
        raise NsifError(code, "pixels", offset, path, explanation)

    if not isinstance(container, Container):
        refuse("E_FIELD", "/window/container", "the container is not a parsed Container")
    if type(image_index) is not int:
        refuse("E_FIELD", "/window/image_index", "image_index is not an int")
    if not 0 <= image_index < len(container.images):
        refuse("E_FIELD", "/window/image_index", "no such image")
    if type(storage) is not bool:
        refuse("E_FIELD", "/window/storage", "storage is not a bool")
    image = container.images[image_index]
    base = f"/segments/image[{image_index}]"
    # The pixel cell before the coordinates: bounds mean nothing for an image no path can decode.
    _, _, code, name, message = _pixel_cell(
        image.ic, image.pvtype, image.nbpp, image.imode, image.band_count, image.nbpr, image.nbpc
    )
    if code is not None:
        refusal = "E_CODEC" if image.ic != "NC" else "E_PROFILE"
        refuse(refusal, f"{base}/{name}", message, image.fields[name].offset)
    for argument, value in (("x", x), ("y", y), ("width", width), ("height", height)):
        if type(value) is not int:
            refuse("E_FIELD", f"/window/{argument}", f"{argument} is not an int")
    if x < 0:
        refuse("E_FIELD", "/window/x", "x is negative")
    if y < 0:
        refuse("E_FIELD", "/window/y", "y is negative")
    if width < 1:
        refuse("E_FIELD", "/window/width", "width is not positive")
    if height < 1:
        refuse("E_FIELD", "/window/height", "height is not positive")
    if x + width > image.ncols:
        refuse("E_FIELD", "/window/width", "the window extends past NCOLS")
    if y + height > image.nrows:
        refuse("E_FIELD", "/window/height", "the window extends past NROWS")
    if type(bands) is not tuple:
        refuse("E_FIELD", "/window/bands", "bands must be a tuple")
    if not bands:
        refuse("E_FIELD", "/window/bands", "no band requested")
    # Refused before the elements are iterated, so a long tuple costs nothing.
    if len(bands) > image.band_count:
        refuse("E_FIELD", "/window/bands", "more band indexes than the image has bands")
    seen: set[int] = set()
    for band in bands:
        if type(band) is not int:
            refuse("E_FIELD", "/window/bands", "band index is not an int")
        if not 0 <= band < image.band_count:
            refuse("E_FIELD", "/window/bands", "no such band")
        if band in seen:
            refuse("E_FIELD", "/window/bands", "duplicate band index")
        seen.add(band)
    octets = image.nbpp // 8
    size = len(bands) * height * width * octets
    if size > container.limits.window_bytes:
        refuse("E_LIMIT", "/window", "the window is larger than the native window cap")
    # The parser already holds LI to this length; rechecking it next to the reads makes "no read
    # outside the input" a local fact of this function rather than a property of another one.
    data = image.segment.data
    expected = (
        image.nbpr * image.nbpc * image.block_width * image.block_height * image.band_count * octets
    )
    if expected != data.length or data.offset + data.length > len(container.raw):
        refuse(
            "E_LENGTH",
            f"{base}/data",
            "the data length differs from the native sample length",
            data.offset,
        )

    raw = container.raw
    start = data.offset
    layout = (
        image.imode,
        image.nbpr,
        image.nbpc,
        image.block_width,
        image.block_height,
        image.band_count,
    )
    nbpp = image.nbpp
    abpp = image.abpp
    discarded = nbpp - abpp
    discarded_mask = (1 << discarded) - 1
    value_mask = (1 << abpp) - 1
    sign_bit = 1 << (abpp - 1)
    element_mask = (1 << nbpp) - 1
    signed = image.pvtype == "SI"
    left = image.pjust == "L"
    out = bytearray(size)
    nonzero = sign_extended = 0
    first_nonzero = first_sign_extended = None
    at = 0
    for band in bands:
        for row in range(y, y + height):
            for column in range(x, x + width):
                source = start + _sample_index(*layout, column, row, band) * octets
                u = raw[source] if octets == 1 else (raw[source] << 8) | raw[source + 1]
                if storage:
                    v = u
                else:
                    if left:
                        v = u >> discarded
                        high = 0
                        if u & discarded_mask:
                            nonzero += 1
                            if first_nonzero is None or source < first_nonzero:
                                first_nonzero = source
                    else:
                        v = u & value_mask
                        high = u >> abpp
                    if signed and v >= sign_bit:
                        v -= 1 << abpp
                    if high:
                        # Conventional sign extension of a negative right-justified value is
                        # still a discarded nonzero bit, but it is counted apart so that it does
                        # not read as corruption.
                        if signed and v < 0 and high == discarded_mask:
                            sign_extended += 1
                            if first_sign_extended is None or source < first_sign_extended:
                                first_sign_extended = source
                        else:
                            nonzero += 1
                            if first_nonzero is None or source < first_nonzero:
                                first_nonzero = source
                    v &= element_mask
                if octets == 1:
                    out[at] = v
                else:
                    out[at] = v >> 8
                    out[at + 1] = v & 0xFF
                at += octets
    found = []
    if nonzero:
        found.append(
            Diagnostic(
                "FILL_BITS_NONZERO",
                "pixels",
                first_nonzero,
                f"{base}/data",
                "some samples in this window have nonzero bits outside ABPP",
            )
        )
    if sign_extended:
        found.append(
            Diagnostic(
                "FILL_BITS_SIGN_EXTENDED",
                "pixels",
                first_sign_extended,
                f"{base}/data",
                "some samples in this window carry sign-extension bits outside ABPP",
            )
        )
    if storage:
        dtype = "uint8" if octets == 1 else "uint16"
    else:
        dtype = _DTYPES[(image.pvtype, nbpp)]
    return SampleWindow(
        image_index,
        x,
        y,
        width,
        height,
        bands,
        "storage" if storage else "interpreted",
        dtype,
        bytes(out),
        nonzero,
        sign_extended,
        tuple(found),
    )


# --------------------------------------------------------------------------- the argument screen


def _measured_size(raw: object) -> int | None:
    """The octets an argument is, for the size cap, read without copying the argument and
    through the base class, so no subclass method runs; None for a type that is not octets or
    text. A released memoryview has no size and is refused."""
    kind = type(raw)
    if issubclass(kind, bytes):
        return bytes.__len__(raw)
    if issubclass(kind, bytearray):
        return bytearray.__len__(raw)
    if kind is memoryview:
        try:
            return raw.nbytes
        except ValueError:
            raise NsifError(
                "E_FIELD", "input", None, "/input", "the buffer cannot be read"
            ) from None
    if issubclass(kind, str):
        return len(str.encode(raw, "utf-8", "surrogatepass"))
    return None


def _too_deep(document: object, limit: int) -> bool:
    """Whether `document` nests more than `limit` containers. Iterative, and each
    (container, depth) pair is expanded once, so a self-referential or widely shared structure
    is refused at once instead of being walked without end."""
    pending = [(document, 1)]
    seen: set[tuple[int, int]] = set()
    while pending:
        node, depth = pending.pop()
        kind = type(node)
        if issubclass(kind, dict):
            children = dict.values(node)
        elif issubclass(kind, list):
            children = list.__iter__(node)
        else:
            continue
        key = (id(node), depth)
        if key in seen:
            continue
        seen.add(key)
        if depth > limit:
            return True
        pending.extend((child, depth + 1) for child in children)
    return False


def _refuse_depth(raw: dict, limits: Limits) -> None:
    if _too_deep(raw, limits.twin_depth):
        raise NsifInputTooDeep("/twin", f"twin nests deeper than {limits.twin_depth} containers")


def check_argument(raw: object, limits: Limits) -> None:
    """The first screen of every entry point: the size cap, the two accepted types, a twin's
    depth, and for bytes the nine-octet signature. Nothing is coerced."""
    if type(limits) is not Limits:
        raise TypeError("limits must be a Limits instance")
    size = _measured_size(raw)
    if size is not None and size > limits.input_bytes:
        raise NsifInputTooLarge(
            "/input", f"input is {size} octets; the limit is {limits.input_bytes}"
        )
    if type(raw) is dict:
        _refuse_depth(raw, limits)
        return
    if type(raw) is not bytes:
        raise NsifError("E_FIELD", "input", None, "/input", "the input is neither bytes nor a twin")
    _check_signature(raw)


_BASE64_VALUES = {
    character: value
    for value, character in enumerate(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    )
}
_TWIN_KEYS = frozenset(("profile", "wire_b64"))


def decode_twin(raw: dict, limits: Limits) -> bytes:
    """A parsed twin's octets: exactly `{"profile": "SC4545-CORE-1", "wire_b64": <text>}`, the
    text canonical RFC 4648 base64. Every size is checked before anything is decoded, and the
    octets then go through `parse_container` like any other input."""
    if type(limits) is not Limits:
        raise TypeError("limits must be a Limits instance")

    def refuse(code: str, path: str, explanation: str) -> None:
        raise NsifError(code, "input", None, path, explanation)

    if type(raw) is not dict:
        refuse("E_FIELD", "/input", "the input is not a parsed twin")
    _refuse_depth(raw, limits)
    keys = list(dict.keys(raw))
    if len(keys) != 2 or not all(type(key) is str for key in keys) or set(keys) != _TWIN_KEYS:
        refuse("E_FIELD", "/twin", "the twin's members are not exactly profile and wire_b64")
    profile = dict.__getitem__(raw, "profile")
    if type(profile) is not str:
        refuse("E_FIELD", "/twin/profile", "profile is not a string")
    if profile != PROFILE:
        refuse("E_PROFILE", "/twin/profile", "profile is not SC4545-CORE-1")
    text = dict.__getitem__(raw, "wire_b64")
    if type(text) is not str:
        refuse("E_FIELD", "/twin/wire_b64", "wire_b64 is not a string")
    n = len(text)
    if n > limits.twin_chars:
        refuse(
            "E_LIMIT", "/twin/wire_b64", f"wire_b64 is longer than {limits.twin_chars} characters"
        )
    if not text.isascii() or n % 4:
        refuse("E_FIELD", "/twin/wire_b64", "wire_b64 is not canonical RFC 4648 base64")
    pad = 2 if text.endswith("==") else 1 if text.endswith("=") else 0
    if n // 4 * 3 - pad > limits.input_bytes:
        refuse(
            "E_LIMIT",
            "/twin/wire_b64",
            f"wire_b64 decodes to more than {limits.input_bytes} octets",
        )
    if pad:
        # The decoder accepts non-zero pad bits; canonical form (RFC 4648 section 3.5) does not.
        value = _BASE64_VALUES.get(text[n - 1 - pad])
        if value is None or value & (0x0F if pad == 2 else 0x03):
            refuse("E_FIELD", "/twin/wire_b64", "wire_b64 is not canonical RFC 4648 base64")
    try:
        return binascii.a2b_base64(text.encode("ascii"), strict_mode=True)
    except binascii.Error:
        # Characters outside the alphabet, misplaced padding, data after padding.
        pass
    refuse("E_FIELD", "/twin/wire_b64", "wire_b64 is not canonical RFC 4648 base64")
