"""The experimental SC4545-WRITE-NC8-1 writer: one explicit recipe, one 8-bit raster, one fixed
single-image NC layout.

EXPERIMENTAL
------------
This is experimental engineering output. Its files are not independently qualified: no
independent reader has parsed them unchanged and no clause-by-clause check against a normative
profile has been made. The writer's own self-parse accepting its file is necessary and not
sufficient, and it is the only check this module states.

WHAT IT ACCEPTS
---------------
A recipe is one JSON object, read under a size cap with duplicate keys and non-standard
constants refused, and validated in three passes. First, requests for what the writer does not
do are refused as unsupported (E_PROFILE): NSIF01.00, other than 8-bit samples, extra bands or
another representation, a side above 2048, TREs, compression or JPEG tables, transformations,
and sensor models. Second, anything but explicitly unclassified material with no caveat is a
policy refusal (E_POLICY). Third, the schema `contracts/write-nc8-recipe.schema.json` and the
checks it cannot express: printable text that fits its field (overlength is refused, never cut),
valid UTC instants without a leap second, canonical base64 of exactly the raster's samples, and
corners inside their ranges. The capture time is required: an unknown one is an error for this
writer.

WHAT IT WRITES
--------------
`write_nc8` is pure. It lays out one image with no graphic, text, DES, RES or TRE, every
extension length zero, one block, IC NC, INT samples with ABPP and NBPP 8, PJUST R, IMODE B, IREP
MONO or RGB and band descriptors M or R, G, B; every security block is U with the other fields
blank. Lengths are those of the serialised buffers. Optional corners are rounded to the nearest
whole arcsecond, halves away from zero, with the carry inherent in the arithmetic, and the
rounding of each one is recorded. Before anything is returned the octets are parsed back with
the adapter and must give the magic, one native image whose samples equal the input, the stated
length, a declared-unclassified assessment, a usable footprint when corners were given, and an
empty profile validation; any other outcome is a writer defect and nothing is written.
"""

from __future__ import annotations

import base64
import binascii
import datetime
import hashlib
import importlib.resources
import json
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import jsonschema

from synapse_imagery.result import HostError

WRITER = "SC4545-WRITE-NC8-1"
RECIPE_BYTES = 33_554_432
STATUS = "experimental"
QUALIFICATION = (
    "experimental engineering output: not independently parsed, not checked clause by clause "
    "against a normative profile; a self-parse accepting its own file is necessary and "
    "insufficient"
)
RECORD_FORMAT = "sc-imagery-export-record/1"
CORNERS = ("ul", "ur", "lr", "ll")
# The schema's patterns are searched, not matched whole, and its `\d` takes the digits of every
# script, so a final newline or non-ASCII digits pass it: times and corners are matched again
# here, in ASCII and whole, before anything reads a number out of them.
_TIME = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z")
_DECIMAL = re.compile(r"-?[0-9]{1,3}(\.[0-9]{1,12})?")
_HEADER_LENGTH = 404


def _load_schema() -> dict:
    text = (
        importlib.resources.files("synapse_imagery")
        .joinpath("contracts", "write-nc8-recipe.schema.json")
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


SCHEMA = _load_schema()
_VALIDATOR = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())


def _field(path: str, message: str, code: str = "E_FIELD") -> HostError:
    return HostError(code, "export", None, path, message)


# --------------------------------------------------------------------------- reading


def _no_duplicates(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("a key is repeated")
    return dict(pairs)


def _no_constant(name):
    raise ValueError("a non-standard constant")


def read_recipe(data: bytes) -> dict:
    """The recipe in `data`, validated by the three passes; the parent record is the caller's
    check, because it needs the store."""
    if type(data) is not bytes:
        raise TypeError("a recipe is read from bytes")
    if len(data) > RECIPE_BYTES:
        raise _field("/recipe", f"the recipe is larger than {RECIPE_BYTES} octets")
    try:
        recipe = json.loads(
            data.decode("utf-8"),
            parse_float=Decimal,
            parse_constant=_no_constant,
            object_pairs_hook=_no_duplicates,
        )
    except (UnicodeDecodeError, ValueError, RecursionError):
        # Deep nesting ends in RecursionError or a decode error depending on the interpreter.
        raise _field("/recipe", "the recipe is not one UTF-8 JSON document") from None
    if type(recipe) is not dict:
        raise _field("/recipe", "the recipe is not a JSON object")
    _refuse_unsupported(recipe)
    _refuse_security(recipe)
    _check_schema(recipe)
    _check_semantics(recipe)
    return recipe


def _refuse_unsupported(recipe: dict) -> None:
    def unsupported(path: str, message: str):
        return _field(path, message, "E_PROFILE")

    raster = recipe.get("raster")
    raster = raster if type(raster) is dict else {}
    if recipe.get("magic") == "NSIF01.00":
        raise unsupported("/recipe/magic", "NSIF01.00 is never emitted")
    bits = raster.get("bits")
    if "bits" in raster and type(bits) in (int, Decimal) and bits != 8:
        raise unsupported("/recipe/raster/bits", "the writer writes 8-bit samples only")
    if "bands" in raster or (
        "representation" in raster and raster["representation"] not in ("MONO", "RGB")
    ):
        raise unsupported(
            "/recipe/raster/representation", "the writer writes one MONO or three RGB bands only"
        )
    for axis in ("width", "height"):
        value = raster.get(axis)
        if type(value) is int and value > 2048:
            raise unsupported(f"/recipe/raster/{axis}", "a raster side is at most 2048 pixels")
    if "tres" in recipe or "copy_tres" in recipe:
        raise unsupported("/recipe/tres", "the writer adds and copies no TRE")
    if "jpeg_tables" in recipe or "compression" in recipe:
        raise unsupported("/recipe/compression", "the writer writes uncompressed NC samples only")
    if recipe.get("transformations") or "crop" in recipe or "resample" in recipe:
        raise unsupported(
            "/recipe/transformations",
            "a transformation would need a fresh sensor model; the writer applies none",
        )
    if any(name in recipe for name in ("rpc", "ichipb", "blocka", "sensor_model")):
        raise unsupported("/recipe/sensor_model", "the writer reuses and writes no sensor model")


def _refuse_security(recipe: dict) -> None:
    if "security" in recipe and recipe["security"] != {"classification": "U"}:
        raise _field(
            "/recipe/security",
            "the writer accepts only explicitly unclassified material with no caveats",
            "E_POLICY",
        )


def _pointer(parts) -> str:
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _check_schema(recipe: dict) -> None:
    errors = sorted(
        _VALIDATOR.iter_errors(recipe),
        key=lambda error: (tuple(str(part) for part in error.absolute_path), error.validator),
    )
    if not errors:
        return
    first = errors[0]
    path = "/recipe" + _pointer(first.absolute_path)
    if first.validator == "required":
        missing = [name for name in first.validator_value if name not in first.instance]
        path += _pointer(missing[:1])
    raise _field(path, f"the recipe does not satisfy its schema ({first.validator})")


def _printable(text: str) -> bool:
    return all(0x20 <= ord(character) <= 0x7E for character in text) and not text.startswith(" ")


def _instant(text: str) -> datetime.datetime | None:
    match = _TIME.fullmatch(text)
    if match is None:
        return None
    year, month, day, hour, minute, second = map(int, match.groups())
    try:
        return datetime.datetime(year, month, day, hour, minute, second)
    except ValueError:
        # Includes second 60: a UTC instant cannot hold a leap second.
        return None


def _check_semantics(recipe: dict) -> None:
    for name in ("producer_id", "product_id", "source_attribution"):
        if not _printable(recipe[name]):
            raise _field(f"/recipe/{name}", "text is printable ASCII and does not start blank")
    for name in ("product_time", "capture_time"):
        if _instant(recipe[name]) is None:
            raise _field(f"/recipe/{name}", "the time is not a valid UTC instant")
    raster = recipe["raster"]
    if type(raster["bits"]) is not int:
        raise _field("/recipe/raster/bits", "bits is the integer 8")
    samples = samples_of(raster)
    expected = raster["width"] * raster["height"] * (1 if raster["representation"] == "MONO" else 3)
    if len(samples) != expected:
        raise _field(
            "/recipe/raster/samples_b64",
            "the samples are not width times height times bands octets",
            "E_LENGTH",
        )
    for corner in CORNERS if "corners" in recipe else ():
        for axis, bound in (("lat", 90), ("lon", 180)):
            text = recipe["corners"][corner][axis]
            if _DECIMAL.fullmatch(text) is None:
                raise _field(f"/recipe/corners/{corner}/{axis}", "the corner is not a decimal")
            if not -bound <= Decimal(text) <= bound:
                raise _field(f"/recipe/corners/{corner}/{axis}", "the corner is outside its range")


def samples_of(raster: dict) -> bytes:
    """The decoded samples: canonical base64 only (the strict decoder accepts non-zero pad bits,
    so the text must also be exactly the encoding of what it decodes to)."""
    text = raster["samples_b64"]
    path = "/recipe/raster/samples_b64"
    if len(text) % 4:
        raise _field(path, "the samples are not canonical base64")
    try:
        decoded = binascii.a2b_base64(text.encode("ascii"), strict_mode=True)
    except (binascii.Error, ValueError):
        raise _field(path, "the samples are not canonical base64") from None
    if base64.b64encode(decoded).decode("ascii") != text:
        raise _field(path, "the samples are not canonical base64")
    return decoded


def canonical(value: object) -> str:
    """The recipe's canonical JSON: keys sorted, compact, ASCII; the same recipe written in
    another key order or spacing is the same recipe."""
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------- writing


@dataclass(frozen=True, slots=True)
class WriteResult:
    octets: bytes
    provenance: dict


def _a(text: str, width: int) -> bytes:
    data = text.encode("ascii")
    if len(data) > width:
        raise ValueError("a field is longer than its width")
    return data.ljust(width, b" ")


def _d(value: int, width: int) -> bytes:
    text = f"{value:0{width}d}".encode("ascii")
    if len(text) != width:
        raise ValueError("a number is wider than its field")
    return text


def _wire_time(text: str) -> str:
    # Only ever called on a time `_check_semantics` accepted.
    return "".join(_TIME.fullmatch(text).groups())


def _corner(value: str, degree_digits: int, positive: str, negative: str):
    """One coordinate in whole arcseconds, halves away from zero: (text, delta, whole seconds)."""
    number = Decimal(value)
    seconds = (abs(number) * 3600).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    whole = int(seconds)
    degrees, rest = divmod(whole, 3600)
    minutes, second = divmod(rest, 60)
    hemisphere = positive if number >= 0 or whole == 0 else negative
    signed = whole if hemisphere == positive else -whole
    delta = Decimal(signed) - 3600 * number
    text = f"{degrees:0{degree_digits}d}{minutes:02d}{second:02d}{hemisphere}"
    return text, format(delta.normalize(), "+f"), whole


def _igeolo(corners: dict) -> tuple[str, list[dict]]:
    text, rounding = "", []
    for name in CORNERS:
        corner = corners[name]
        lat, lat_delta, lat_seconds = _corner(corner["lat"], 2, "N", "S")
        lon, lon_delta, lon_seconds = _corner(corner["lon"], 3, "E", "W")
        if lat_seconds > 90 * 3600:
            raise _field(f"/recipe/corners/{name}/lat", "the corner is outside its range")
        if lon_seconds > 180 * 3600:
            raise _field(f"/recipe/corners/{name}/lon", "the corner is outside its range")
        text += lat + lon
        rounding.append(
            {
                "corner": name,
                "lat": corner["lat"],
                "lon": corner["lon"],
                "emitted": lat + lon,
                "lat_delta_arcseconds": lat_delta,
                "lon_delta_arcseconds": lon_delta,
            }
        )
    return text, rounding


_UNCLASSIFIED = b"U" + b" " * 166


def _image_subheader(recipe: dict, igeolo: str | None) -> bytes:
    raster = recipe["raster"]
    rgb = raster["representation"] == "RGB"
    out = b"IM" + _a(recipe["product_id"], 10) + _wire_time(recipe["capture_time"]).encode()
    out += b" " * 17 + b" " * 80 + _UNCLASSIFIED + b"0" + _a(recipe["source_attribution"], 42)
    out += _d(raster["height"], 8) + _d(raster["width"], 8) + b"INT"
    out += _a(raster["representation"], 8) + _a("VIS", 8) + b"08" + b"R"
    out += b" " if igeolo is None else b"G" + igeolo.encode("ascii")
    out += b"0" + b"NC" + (b"3" if rgb else b"1")
    for descriptor in (b"R ", b"G ", b"B ") if rgb else (b"M ",):
        out += descriptor + b" " * 6 + b"N" + b" " * 3 + b"0"
    out += b"0" + b"B" + b"0001" + b"0001" + _d(raster["width"], 4) + _d(raster["height"], 4)
    out += b"08" + b"001" + b"000" + b"0000000000" + b"1.0 " + b"00000" + b"00000"
    return out


def _serialise(recipe: dict, igeolo: str | None, samples: bytes) -> bytes:
    """The whole file: lengths are those of the serialised buffers, decimals zero-padded."""
    subheader = _image_subheader(recipe, igeolo)
    head = _a(recipe.get("magic", "NSIF01.01"), 9) + b"03" + b"BF01"
    head += _a(recipe["producer_id"], 8) + b"  " + _wire_time(recipe["product_time"]).encode()
    head += _a(recipe["product_id"], 80) + _UNCLASSIFIED + b"00000" + b"00000" + b"0"
    head += bytes(3) + b" " * 24 + b" " * 18
    directory = b"001" + _d(len(subheader), 6) + _d(len(samples), 10)
    directory += b"000" * 5 + b"00000" + b"00000"
    header_length = len(head) + 12 + 6 + len(directory)
    if header_length != _HEADER_LENGTH:
        raise ValueError("the header has its fixed length")
    total = header_length + len(subheader) + len(samples)
    return head + _d(total, 12) + _d(header_length, 6) + directory + subheader + samples


def _defect(name: str, message: str) -> HostError:
    return HostError("E_INTERNAL", "export", None, f"/self_check/{name}", message)


def _self_check(octets: bytes, recipe: dict, samples: bytes) -> dict:
    """The writer's own file parsed back with the adapter: every property must hold, or the
    writer is defective and nothing is written."""
    from synapse_cdm.adapters import nsif_codec
    from synapse_cdm.adapters.stanag4545 import (
        CORE1_LIMITS,
        Stanag4545Adapter,
        assess_security,
        parse_container,
    )

    raster = recipe["raster"]
    bands = 1 if raster["representation"] == "MONO" else 3
    try:
        container = parse_container(octets, CORE1_LIMITS)
    except nsif_codec.NsifError:
        raise _defect("parse", "the writer's file does not parse") from None
    if container.signature != recipe.get("magic", "NSIF01.01"):
        raise _defect("signature", "the writer's file has another magic")
    images = container.images
    if len(images) != 1 or images[0].pixel_status != "native_supported":
        raise _defect("image", "the writer's file is not one native image")
    window = nsif_codec.decode_nc_window(
        container, 0, 0, 0, raster["width"], raster["height"], tuple(range(bands))
    )
    if window.data != samples:
        raise _defect("samples", "the writer's samples do not read back equal")
    if len(octets) != int(octets[342:354]):
        raise _defect("length", "the writer's file differs from its stated length")
    status = assess_security(container)["status"]
    if status != "declared_unclassified":
        raise _defect("security", "the writer's labels are not assessed as declared unclassified")
    if "corners" in recipe and images[0].geometry_status != "available":
        raise _field("/recipe/corners", "the corners do not form a footprint the adapter accepts")
    found = Stanag4545Adapter().validate_source(octets)
    if found != []:
        raise _defect("validate_source", "the writer's file does not validate")
    return {
        "parse": "ok",
        "samples_equal": True,
        "length_equal": True,
        "security_status": status,
        "validate_source": found,
    }


def write_nc8(recipe: dict) -> WriteResult:
    """The octets of a validated recipe and the writer's part of the export provenance."""
    samples = samples_of(recipe["raster"])
    igeolo, rounding = (None, [])
    if "corners" in recipe:
        igeolo, rounding = _igeolo(recipe["corners"])
    octets = _serialise(recipe, igeolo, samples)
    check = _self_check(octets, recipe, samples)
    provenance = {
        "output": {
            "sha256": hashlib.sha256(octets).hexdigest(),
            "bytes": len(octets),
            "magic": recipe.get("magic", "NSIF01.01"),
        },
        "corner_rounding": rounding,
        "self_check": check,
    }
    return WriteResult(octets, provenance)


def stored_recipe(recipe: dict) -> dict:
    """The recipe as the export record keeps it: the samples by digest and length only."""
    kept = json.loads(canonical(recipe))
    samples = samples_of(recipe["raster"])
    raster = kept["raster"]
    del raster["samples_b64"]
    raster["samples_sha256"] = hashlib.sha256(samples).hexdigest()
    raster["samples_bytes"] = len(samples)
    return kept


def export_record(recipe: dict, written: WriteResult, parent: dict | None, software: dict) -> dict:
    """The provenance an export commits before its output is delivered."""
    from synapse_imagery._version import __version__

    return {
        "format": RECORD_FORMAT,
        "writer": WRITER,
        "writer_version": __version__,
        "status": STATUS,
        "qualification": QUALIFICATION,
        "recipe": stored_recipe(recipe),
        "recipe_sha256": hashlib.sha256(canonical(recipe).encode("ascii")).hexdigest(),
        "parent": parent,
        "output": written.provenance["output"],
        "lossy_transformations": [],
        "samples": "preserved_exactly",
        "container": "newly_authored",
        "corner_rounding": written.provenance["corner_rounding"],
        "self_check": written.provenance["self_check"],
        "software": software,
    }
