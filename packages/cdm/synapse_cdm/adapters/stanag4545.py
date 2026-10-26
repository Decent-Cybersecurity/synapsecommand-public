"""STANAG 4545 NSIF/NITF still imagery under the SC4545-CORE-1 engineering profile -> CDM.
Adapter #38, ingest only.

INGEST  one NSIF 01.01, NSIF 01.00 or NITF 02.10 still-imagery container, as its octets or as its
        parsed twin `{"profile": "SC4545-CORE-1", "wire_b64": ...}`, becomes one OVERLAY_OBJECT
        product `Entity`, then one ANNOTATION footprint `PlanObject` per image whose IGEOLO G or D
        corners give a footprint, in image order.
EGRESS  none. `from_cdm` is the base class's refusal; replaying the original octets and the
        experimental writer belong to the imagery host distribution and are not egress.

The container grammar, the resource caps, the window decoder and the twin decoder live in
`nsif_codec`, the corner arithmetic in `nsif_geometry`; this module is the mapping and nothing
else. The wire grammar is a provisional internal profile: its field order and widths were
cross-checked against an independent implementation's source, and no standards text is held here,
which is why the claim is PROVISIONAL and the manifest says so in its limitations.

WHAT THE OBJECTS ARE, AND WHAT THEY ARE NOT
-------------------------------------------
The product is an imagery product, not a unit, a sensor or a detection: no position, symbol,
kinematics or confidence, affiliation UNKNOWN, and nothing about targets, intent or accuracy is
read out of TGTID, ISORCE, comments, titles or TREs. A footprint is a coverage overlay, never a
planned objective: ANNOTATION, empty style, no route, area or expiry, and its residual states the
presentation role so a consumer does not have to guess it. Its geometry is the polygon through the
four stated corners, an approximation for display.

IDENTITY AND TIME
-----------------
The product key is the host's `product_key`, or the compact JSON of the source tuple FHDR, FVER,
OSTAID, FDT and every IID1 when all of them are present and printable; without either the call is
refused E_CONTEXT, while `parse_container` and `validate_source` still succeed. `valid_from` is
FDT, else the host's `as_of` with its basis recorded, else E_CONTEXT. No clock is ever read.

SECURITY
--------
Every security block becomes one label record, carried on the product and, with the product-wide
assessment, on every footprint; `security_labels` and `assess_security` are the one predicate,
public so the host can decide before translation exists. Core labels and assesses; it enforces
nothing, and an encrypted container is refused by the parser.

THE OCTETS ONCE
---------------
The product residual holds the whole input once as canonical base64 and every other source
reference as an `{offset, length}` slice into it; no footprint carries base64.
"""

from __future__ import annotations

import base64
import copy
import dataclasses
import functools
import json
import re

from synapse_cdm import ids, lossless, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import nsif_codec, nsif_geometry
from synapse_cdm.adapters.geojson import AsOf
from synapse_cdm.adapters.nsif_codec import (
    CORE1_LIMITS,
    DIAGNOSTIC_CODES,
    MAGICS,
    SECURITY_FIELDS,
    Container,
    Diagnostic,
    Limits,
    NsifError,
    NsifInputTooDeep,
    NsifInputTooLarge,
    SampleWindow,
    Slice,
    check_argument,
    decode_nc_window,
    decode_twin,
    parse_container,
)
from synapse_cdm.enums import Affiliation, EntityType, ObjectType
from synapse_cdm.manifest import (
    AdapterMetadata,
    Capabilities,
    ClaimStatus,
    Direction,
    Evidence,
    FormatRef,
    LicenseClass,
    LimitBasis,
    LimitKind,
    Maturity,
    MaturityLevel,
    Residual,
    UnknownFields,
    WireBinding,
)
from synapse_cdm.manifest import Limits as ManifestLimits
from synapse_cdm.models import (
    CDMBase,
    Entity,
    PlanObject,
    SourceHash,
    SourceId,
    TemporalValidity,
)
from synapse_cdm.models import Residual as ResidualBlock

__all__ = [
    "Stanag4545Adapter",
    "Stanag4545Context",
    "security_labels",
    "assess_security",
    "PROFILE",
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "SYSTEM",
    "PROFILE_REVISION",
    "Container",
    "Limits",
    "CORE1_LIMITS",
    "NsifError",
    "NsifInputTooLarge",
    "NsifInputTooDeep",
    "Diagnostic",
    "DIAGNOSTIC_CODES",
    "parse_container",
    "decode_nc_window",
    "SampleWindow",
]

PROFILE = "SC4545-CORE-1"
FORMAT_NAME = "NSIF/NITF imagery"
FORMAT_VERSION = "SC4545-CORE-1; STANAG 4545 Ed 2 target"
SYSTEM = "STANAG4545"
PROFILE_REVISION = 1

_PIPE = "|"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CLASSIFICATIONS = ("U", "R", "C", "S", "T")
_REASONS = (
    "CLAS_UNRECOGNISED",
    "LABEL_FIELD_UNINTERPRETED",
    "UNKNOWN_EXTENSION",
    "CLAS_NOT_U",
    "RESTRICTIVE_CAVEAT",
    "MIXED_CLASSIFICATION_SYSTEM",
)
# The first three mean core cannot read the labels, which outranks what they say.
_UNRESOLVED = frozenset(_REASONS[:3])

#: The directory's length names per segment kind, in the header's order.
_DIRECTORY_NAMES = (
    ("image", "LISH", "LI"),
    ("graphic", "LSSH", "LS"),
    ("text", "LTSH", "LT"),
    ("des", "LDSH", "LD"),
    ("res", "LRESH", "LRE"),
)
#: Subheader fields whose body is opaque: always a slice, never text.
_OPAQUE_BODIES = frozenset(("DESSHF", "RESSHF"))

_PARSE_PROFILE_CAPABILITIES = {
    "container_inventory": "complete",
    "metadata_preservation": "byte_preserving",
    "cdm_translation": "complete",
    "native_samples": "per_image",
    "compressed_samples": "disabled",
    "geographic_footprint": "per_image",
    "replay": "host_operation",
    "new_export": "not_in_core",
}


# --------------------------------------------------------------------------- the context


def _identifier(name: str, value: object, limit: int, pipe_allowed: bool) -> None:
    if type(value) is not str:
        raise TypeError(f"{name} must be a str")
    if not 1 <= len(value) <= limit:
        raise ValueError(f"{name} must be 1 to {limit} characters")
    if any(not " " <= character <= "~" for character in value):
        raise ValueError(f"{name} must be printable ASCII")
    if not value.strip(" "):
        # An identity made of spaces is one nobody can see or tell apart.
        raise ValueError(f"{name} must hold a character other than a space")
    if not pipe_allowed and _PIPE in value:
        # `ids.derive` joins kind, system and key with the same character.
        raise ValueError(f"{name} must not contain |")


@dataclasses.dataclass(frozen=True, slots=True)
class Stanag4545Context:
    """Trusted host configuration, never read from the source octets.

    `verified_sha256` is the host's assertion that it computed the digest over the exact octets
    passed to the call (for a twin, the decoded octets); it is copied into `source.source_hash`
    and core does not verify it. `asset_ref` is a host-issued opaque reference.
    """

    dataset_namespace: str = "default"
    product_key: str | None = None
    as_of: AsOf | None = None
    asset_ref: str | None = None
    verified_sha256: str | None = None

    def __post_init__(self) -> None:
        _identifier("dataset_namespace", self.dataset_namespace, 128, False)
        if self.product_key is not None:
            _identifier("product_key", self.product_key, 128, False)
        if self.as_of is not None and type(self.as_of) is not AsOf:
            raise TypeError("as_of must be None or an AsOf")
        if self.asset_ref is not None:
            _identifier("asset_ref", self.asset_ref, 256, True)
        if self.verified_sha256 is not None:
            if type(self.verified_sha256) is not str:
                raise TypeError("verified_sha256 must be a str")
            if not _SHA256.fullmatch(self.verified_sha256):
                raise ValueError("verified_sha256 must be 64 lowercase hexadecimal digits")


# --------------------------------------------------------------------------- residual pieces


def _slice(part: Slice) -> dict:
    return {"offset": part.offset, "length": part.length}


def _text(raw: bytes, part: Slice) -> dict:
    text, _ = nsif_codec.ascii_text(raw, part)
    if text is None:
        return {
            "offset": part.offset,
            "length": part.length,
            "text": None,
            "encoding_status": "uninterpreted",
        }
    return {"offset": part.offset, "length": part.length, "text": text}


def _record(container: Container, kind: str, index: int):
    records = {
        "image": container.images,
        "graphic": container.graphics,
        "text": container.texts,
        "des": container.des,
        "res": container.res,
    }
    return records[kind][index]


def _areas(record) -> dict:
    areas = {}
    for key in ("udhd", "xhd", "udid", "ixshd", "sxshd", "txshd"):
        area = getattr(record, key, None)
        if area is not None:
            areas[area.section] = area
    return areas


def _fields(raw: bytes, fields, areas: dict, skip) -> dict:
    """A structure's fields in wire order: text fields, except opaque bodies as slices. An
    extension area that is not empty contributes its overflow number as text and its TRE octets
    as a slice; an empty one has neither."""
    out = {}
    for name, part in fields.items():
        if skip(name):
            continue
        area = areas.get(name)
        if area is not None:
            out[nsif_codec.AREA_FIELDS[name][1]] = _text(raw, area.overflow_field)
            out[name] = _slice(area.local)
        elif name in _OPAQUE_BODIES:
            out[name] = _slice(part)
        else:
            out[name] = _text(raw, part)
    return out


_DIRECTORY_FIELD = re.compile(r"(?:LISH|LI|LSSH|LS|LTSH|LT|LDSH|LD|LRESH|LRE)\[\d+\]")


def _file_header(container: Container) -> dict:
    raw = container.raw
    header = container.file_header
    areas = _areas(header)

    def skip(name: str) -> bool:
        return name in ("security", "FBKGC") or bool(_DIRECTORY_FIELD.fullmatch(name))

    fields = {}
    for name, value in _fields(raw, header.fields, areas, skip).items():
        fields[name] = value
        if name == "ENCRYP":
            # FBKGC is three unsigned octets, a colour and never text.
            part = header.fields["FBKGC"]
            octets = raw[part.offset : part.offset + part.length]
            fields["FBKGC"] = {"offset": part.offset, "length": 3, "values": list(octets)}
    directory = {}
    counts = {kind: 0 for kind, _, _ in _DIRECTORY_NAMES}
    for segment in container.segments:
        counts[segment.kind] += 1
    for kind, sub_name, data_name in _DIRECTORY_NAMES:
        directory[kind] = [
            {
                "subheader_length": _text(raw, header.fields[f"{sub_name}[{k}]"]),
                "data_length": _text(raw, header.fields[f"{data_name}[{k}]"]),
            }
            for k in range(counts[kind])
        ]
    return {
        "offset": 0,
        "length": container.header_length,
        "fields": fields,
        "security": _slice(header.security.slice),
        "directory": directory,
    }


def _segment_fields(name: str) -> bool:
    # The security block, the comments and the band records have their own homes.
    return name == "security" or name.startswith(("ICOM[", "band["))


def _segments(container: Container) -> list[dict]:
    raw = container.raw
    out = []
    for segment in container.segments:
        record = _record(container, segment.kind, segment.index)
        entry = {
            "kind": segment.kind,
            "index": segment.index,
            "ordinal": segment.file_index,
            "subheader": _slice(segment.subheader),
            "data": _slice(segment.data),
            "security": _slice(record.security.slice),
            "fields": _fields(raw, record.fields, _areas(record), _segment_fields),
        }
        if segment.kind == "image":
            entry["comments"] = [
                _text(raw, record.fields[f"ICOM[{k}]"]) for k in range(record.nicom)
            ]
            bands = []
            for band in record.bands:
                prefix = f"band[{band.index}]/"
                names = ["IREPBAND", "ISUBCAT", "IFC", "IMFLT", "NLUTS"]
                if band.nluts:
                    names.append("NELUTS")
                luts = []
                if band.lut is not None:
                    luts = [
                        {"offset": band.lut.offset + k * band.neluts, "length": band.neluts}
                        for k in range(band.nluts)
                    ]
                bands.append(
                    {
                        "fields": {
                            name: _text(raw, record.fields[prefix + name]) for name in names
                        },
                        "luts": luts,
                    }
                )
            entry["bands"] = bands
        out.append(entry)
    return out


def _extensions(container: Container) -> list[dict]:
    # `Container.extensions` is already in logical order: the file's areas, then each segment's
    # in file order, and within an area the local records before the overflow ones.
    return [
        {
            "area": tre.section,
            "scope": tre.owner_kind,
            "segment_index": tre.owner_index,
            "ordinal": tre.ordinal,
            "origin": tre.origin,
            "overflow_des_index": tre.des_index,
            "tag": tre.tag,
            "offset": tre.slice.offset,
            "length": tre.slice.length,
            "data": _slice(tre.data),
        }
        for tre in container.extensions
    ]


def _diagnostic(diagnostic: Diagnostic) -> dict:
    return {
        "code": diagnostic.code,
        "stage": diagnostic.stage,
        "offset": diagnostic.offset,
        "path": diagnostic.path,
        "message": diagnostic.message,
    }


# --------------------------------------------------------------------------- security


def _label(raw: bytes, block, index: int | None) -> dict:
    fields = {}
    uninterpreted = []
    for name, _ in SECURITY_FIELDS:
        # A printable value loses nothing to trimming: `value.ljust(width)` is the field again.
        text, _ = nsif_codec.ascii_text(raw, block.fields[name])
        fields[name] = text
        if text is None:
            uninterpreted.append(name)
    return {
        "scope": block.scope,
        "index": index,
        "offset": block.slice.offset,
        "length": block.slice.length,
        "fields": fields,
        "uninterpreted": uninterpreted,
    }


def security_labels(container: Container) -> list[dict]:
    """One label record per security block: the file's, then one per segment in file order.
    Each field is its text with trailing spaces trimmed, or None when not printable ASCII; no
    label is combined, compared by level or copied as raw octets."""
    raw = container.raw
    labels = [_label(raw, container.file_header.security, None)]
    for segment in container.segments:
        record = _record(container, segment.kind, segment.index)
        labels.append(_label(raw, record.security, segment.index))
    return labels


def assess_security(container: Container) -> dict:
    """This package's assessment of the source labels, never an authorisation.

    `unresolved` when core cannot read the labels or something on the wire could carry security
    semantics it does not know (an unrecognised CLAS, an uninterpreted field, any TRE, DES or
    RES: no extension is registered as security-neutral); else `labelled` when the labels say
    more than plain unclassified (CLAS other than U, a CODE, CTLH or REL, differing CLSY); else
    `declared_unclassified`. The host's default gate admits only the last.
    """
    labels = security_labels(container)
    clas = [label["fields"]["CLAS"] for label in labels]
    holds = {
        "CLAS_UNRECOGNISED": any(value not in _CLASSIFICATIONS for value in clas),
        "LABEL_FIELD_UNINTERPRETED": any(label["uninterpreted"] for label in labels),
        "UNKNOWN_EXTENSION": bool(container.extensions or container.des or container.res),
        "CLAS_NOT_U": any(value in _CLASSIFICATIONS[1:] for value in clas),
        "RESTRICTIVE_CAVEAT": any(
            label["fields"][name] != "" for label in labels for name in ("CODE", "CTLH", "REL")
        ),
        "MIXED_CLASSIFICATION_SYSTEM": len({label["fields"]["CLSY"] for label in labels}) > 1,
    }
    reasons = [reason for reason in _REASONS if holds[reason]]
    if _UNRESOLVED.intersection(reasons):
        status = "unresolved"
    elif reasons:
        status = "labelled"
    else:
        status = "declared_unclassified"
    return {
        "status": status,
        "reasons": reasons,
        "scopes": len(labels),
        "clas_values": sorted({value for value in clas if value is not None}),
        "uniform_clas": len(set(clas)) == 1,
        "unknown_extensions": {
            "tre": len(container.extensions),
            "des": len(container.des),
            "res": len(container.res),
        },
        "combination": "not_performed",
        "kind": "core_assessment",
    }


# --------------------------------------------------------------------------- identity and time


def _compact(value) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _visible(raw: bytes, part: Slice) -> str | None:
    """The field's octets as text when printable ASCII and not all spaces, untrimmed."""
    octets = raw[part.offset : part.offset + part.length]
    if not all(0x20 <= octet <= 0x7E for octet in octets) or not octets.strip(b" "):
        return None
    return octets.decode("ascii")


def _context_error(path: str, explanation: str) -> NsifError:
    return NsifError("E_CONTEXT", "cdm", None, path, explanation)


def _source_tuple(container: Container) -> str | None:
    raw = container.raw
    header = container.file_header
    if header.fdt.status != "valid" or not container.images:
        return None
    ostaid = _visible(raw, header.fields["OSTAID"])
    iid1s = [_visible(raw, image.fields["IID1"]) for image in container.images]
    if ostaid is None or None in iid1s:
        return None
    fdt = raw[header.fdt.slice.offset : header.fdt.slice.offset + 14].decode("ascii")
    return _compact([raw[0:4].decode("ascii"), raw[4:9].decode("ascii"), ostaid, fdt, iid1s])


def _iid1(raw: bytes, image) -> str | None:
    text = _visible(raw, image.fields["IID1"])
    return None if text is None else text.rstrip(" ")


# --------------------------------------------------------------------------- the adapter

_MAX_INPUT_BYTES = Limits().input_bytes
_MAX_DEPTH = Limits().twin_depth
_MAX_OBJECTS = Limits().output_objects


class Stanag4545Adapter(Adapter):
    """NSIF/NITF still imagery in, one product Entity and its footprints out. Ingest only."""

    name = "stanag4545"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    #: Licence class PUBLIC_GOVERNMENT: STANAG 4545 is a NATO standardization agreement, the
    #: same class as the other STANAG-named adapters.
    metadata = AdapterMetadata(
        id="stanag4545",
        name="STANAG 4545 NSIF/NITF imagery",
        adapter_version="1.0.0",
        format=FormatRef(name=FORMAT_NAME, version=FORMAT_VERSION),
        binding=WireBinding.PROVISIONAL_INTERNAL_PROFILE,
        direction=Direction.INGEST,
        license_class=LicenseClass.PUBLIC_GOVERNMENT,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis=(
                "L3 PROVENANCE VERIFIED, from evidence that runs today. The harness's "
                "`translate`, `schema` and `provenance` checks are PASS on every fixture of this "
                "adapter (L1 to L3). Its `lossless` column rests on the PATH-BOUND LEDGER: "
                "`MAPPINGS` binds both leaves of the parsed twin — `wire_b64` to the product "
                "Entity's `residual.data.stanag4545.wire_b64` and `profile` to its "
                "`attributes.stanag4545.profile`, each by identity — so a PASS proves the source "
                "octets are retained, not that any field is interpreted correctly; field "
                "interpretation is held by tests/test_cdm_stanag4545_adapter.py. This adapter is "
                "INGEST ONLY: `from_cdm` is the base class's refusal, the harness's `roundtrip` "
                "column is a declared SKIP, and `synapse conformance run --adapter stanag4545` "
                "computes E as a declared inapplicability. A rung passed vacuously is not a rung "
                "declared (ARCHITECTURE.md §3.6, rule 4): L4 is NOT declared. The wire grammar is "
                "a provisional internal profile, SC4545-CORE-1, which is why the claim is "
                "PROVISIONAL and not VERIFIED."
            ),
            external_exercise=None,
        ),
        claim_status=ClaimStatus.PROVISIONAL,
        claim_external_system=None,
        profiles=[PROFILE],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[
                "NSIF 01.01, NSIF 01.00 and NITF 02.10 still-imagery containers read under the "
                "SC4545-CORE-1 engineering profile (the octets) — one OVERLAY_OBJECT product "
                "Entity, then one ANNOTATION footprint PlanObject per image with valid IGEOLO G "
                "or D corners, in image order",
                'the parsed twin `{"profile": "SC4545-CORE-1", "wire_b64": …}` — the same '
                "objects through the same parser",
            ],
            limits=ManifestLimits(
                max_input_bytes=_MAX_INPUT_BYTES,
                max_depth=_MAX_DEPTH,
                max_objects=_MAX_OBJECTS,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_decompressed_bytes": (
                        "to_cdm decompresses nothing: image data whose IC is not NC is "
                        "inventoried and preserved as a slice, never decoded in this package; "
                        "the compressed worker's decode limits are published by the imagery "
                        "host distribution"
                    ),
                    "max_parse_seconds": (
                        "no wall-clock bound is enforced in this package: SC4545-CORE-1's "
                        "5-second core parsing deadline is the host's isolated-worker timeout "
                        "(the imagery host distribution kills the worker), not a claim this "
                        "module makes about itself"
                    ),
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "SC4545-CORE-1 (the engineering profile's resource table, "
                            "`CORE1_LIMITS` in `adapters/nsif_codec.py`) admits a binary "
                            "container of at most 16,777,216 octets; files above it are the "
                            "host's to stage separately. This is an IMPLEMENTATION CAP and is "
                            "NOT the format's normative maximum."
                        ),
                        enforced_at=(
                            "the adapter's coded guard, installed on `to_cdm` after the class "
                            "statement, measures the argument first and refuses with E_LIMIT "
                            "(`NsifInputTooLarge`, also an `InputTooLarge`); behind it "
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the payload is measured and refused before "
                            "any decoder in this module runs; `parse_container` and "
                            "`validate_source` refuse the same size again with E_LIMIT"
                        ),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "SC4545-CORE-1 caps the parsed twin's JSON depth at 4 before base64 "
                            'decoding. The only twin the profile accepts, `{"profile", '
                            '"wire_b64"}`, nests one container, so a dict two to four deep '
                            "reaches the adapter's own shape check and is refused there. This "
                            "is an IMPLEMENTATION CAP and is NOT the format's normative maximum."
                        ),
                        enforced_at=(
                            "the adapter's coded guard measures a parsed twin's containers "
                            "first, before any key is read, and refuses past 4 with E_LIMIT "
                            "(`NsifInputTooDeep`, also an `InputTooDeep`); behind it "
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_depth_bound` beside `enforce_input_bound` at "
                            "class-definition time (`adapter.py`, `_bind_input_bound`), and "
                            "`decode_twin` refuses the same depth again; octets are never read "
                            "as JSON, and the guard keeps every payload that does not begin "
                            "with a supported magic away from the wrapper's text decode"
                        ),
                        test="tests/test_cdm_stanag4545_adapter.py::test_the_twin_depth_bound_admits_depth_four_shapes_and_refuses_five",
                    ),
                    "max_objects": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "SC4545-CORE-1 emits one product Entity and at most one footprint "
                            "PlanObject per image segment, and caps image segments at 64, so a "
                            "translation yields at most 65 objects. This is an IMPLEMENTATION "
                            "CAP and is NOT the format's normative maximum. Caps the manifest "
                            "schema has no field for are declared beside it as module "
                            "constants: 256 segments, 64 image segments, 256 bands, 65,536 "
                            "blocks, 1,000,000 per dimension, 4,096 TREs, 4,194,304 octets of "
                            "parsed metadata, 1,048,576 octets per LUT, 22,369,624 twin "
                            "characters, 67,108,864 octets of serialised output and "
                            "134,217,728 octets per native sample window."
                        ),
                        enforced_at=(
                            "`Stanag4545Adapter.to_cdm` counts the objects it will emit before "
                            "it builds any and raises NsifError E_LIMIT; at the production "
                            "values the image-segment cap in `parse_container` refuses a 65th "
                            "image first, so the test lowers the cap to reach the refusal"
                        ),
                        test="tests/test_cdm_stanag4545_adapter.py::test_the_object_bound_admits_sixty_five_and_refuses_one_more_by_injection",
                    ),
                },
            ),
            unknown_fields=UnknownFields.NONE,
            unknown_fields_basis=(
                "the parsed twin is a closed two-key wire envelope (`profile`, `wire_b64`) and "
                "any other key is refused, so an unknown field in the document form has no "
                "carrier; unknown TREs, DES and RES on the wire are a different thing and are "
                "preserved as ordered records and slices in the structured residual"
            ),
        ),
        limitations=[
            "the wire grammar this adapter reads is a PROVISIONAL internal profile (`binding: "
            "provisional-internal-profile`): SC4545-CORE-1, an engineering profile whose field "
            "order and widths were cross-checked against an independent implementation's source "
            "because the NSIF 01.01 BIIF profile, its errata and the Edition 2 normative text are "
            "not held here. Passing this repository's gates shows the profile is self-consistent "
            "and nothing more; the broad STANAG 4545 conformance gate stays open",
            "ingest only: `from_cdm` is the base class's refusal (`NotImplementedError`) and no "
            "NSIF/NITF file is written by this adapter; original-byte replay and the experimental "
            "SC4545-WRITE-NC8-1 writer belong to the imagery host distribution and are not egress",
            "`validate_source` checks the SC4545-CORE-1 engineering profile's structure, local "
            "semantics and resource caps; an empty list is not full STANAG 4545 validation",
            "no pixel is decompressed or decoded in `to_cdm`: native NC samples are read only by "
            "`decode_nc_window` on request, and every compressed or masked image (IC other than "
            "NC) is inventoried, preserved and answered E_CODEC; per-image `pixel_status` and "
            "`geometry_status` say when pixels or a footprint are unavailable",
            "`security_status` is this package's assessment of the source labels, never an "
            "authorisation: labels are preserved verbatim on the product and on every footprint, "
            "no TRE, DES or RES is known to be security-neutral so any one makes the status "
            "`unresolved`, and no access decision is enforced here",
            "footprints come from IGEOLO G and D corners only and are approximate coverage "
            "overlays: UTM, MGRS, other ICORDS codes and sensor models are preserved and not "
            "projected",
            "the parsed twin is a closed wire envelope (`profile`, `wire_b64`), so the `MAPPINGS` "
            "ledger proves byte retention and not the interpretation of any field",
            "the evidence RECORD for this adapter is not IN the distribution: `evidence/` is "
            "untracked and unpackaged. `evidence.available` is false because no published "
            "Release carries this adapter yet; the release round that attaches its records "
            "flips it",
            "of §3.5's five resource limits this adapter enforces THREE — `max_input_bytes` and "
            "`max_depth` by its coded guard and, behind it, the base class before decode, and "
            "`max_objects` in this module — plus the SC4545-CORE-1 caps the manifest schema has "
            "no field for. The other two are absent with their reasons in "
            "`capabilities.limits.absent_because`",
        ],
        limitations_empty_reason=None,
        residual=Residual.STRUCTURED,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=False),
    )

    #: Descriptive keys: the twin's only leaves are `profile` and `wire_b64`, which `MAPPINGS`
    #: binds, so no key here may equal or prefix either. The geometry texts are the geometry
    #: module's own objects, so the wording exists once.
    TRANSFORMS = {
        "ASCII display trimming": (
            "trailing ASCII spaces of a fixed-width text field are trimmed for its display value "
            "(attributes, the footprint label, residual `text`); the padded bytes stay "
            "addressable by the field's offset and length in the preserved container"
        ),
        "UTC reformatting": (
            "a valid 14-digit YYYYMMDDhhmmss field (FDT, IDATIM) is rendered as RFC 3339 UTC "
            "with three decimals; the 14 source bytes stay addressable by offset and length"
        ),
        "date fallback": (
            "valid_from is the caller's context.as_of instant because FDT is unknown or not "
            "representable; the clock, the epoch and IDATIM are never substituted"
        ),
        "integer conversion": (
            "decimal ASCII count, dimension and bit-depth fields are carried as integers in "
            "attributes and FBKGC as three unsigned integers; the source bytes stay addressable"
        ),
        "IGEOLO corner coordinates": nsif_geometry.REASON_COORDINATES,
        "IGEOLO ring orientation": nsif_geometry.REASON_ORIENTATION,
        "IGEOLO antimeridian splitting": nsif_geometry.REASON_SPLITTING,
    }

    #: The twin's two leaves, each by identity. This proves the octets are retained; whether any
    #: field is interpreted correctly is the adapter's own tests' business.
    MAPPINGS = {
        "profile": lossless.Mapping("entity:attributes.stanag4545.profile"),
        "wire_b64": lossless.Mapping("entity:residual.data.stanag4545.wire_b64"),
    }

    def __init__(
        self,
        clock: times.Clock | None = None,
        *,
        synthetic: bool = True,
        context: Stanag4545Context | None = None,
    ) -> None:
        if type(synthetic) is not bool:
            # A truthy string such as "false" must not become a live-data claim.
            raise TypeError("synthetic must be True or False")
        super().__init__(clock, synthetic=synthetic)
        if context is None:
            context = Stanag4545Context()
        elif type(context) is not Stanag4545Context:
            raise TypeError("context must be a Stanag4545Context")
        self._context = context

    @property
    def context(self) -> Stanag4545Context:
        return self._context

    @property
    def namespace(self) -> str:
        return "STANAG4545:" + self._context.dataset_namespace

    # ------------------------------------------------------------------------ v2 surface

    def detect(self, raw: bytes | dict) -> bool | None:
        """True for the three supported signatures, False for another complete one, None when
        it cannot tell. Reads at most nine octets, or the first twelve base64 characters of a
        well-formed twin; never raises and checks no size cap."""
        if type(raw) is bytes:
            if len(raw) < 9:
                return None
            return raw[:9] in MAGICS
        if type(raw) is not dict or len(raw) != 2:
            return None
        if not all(type(key) is str for key in raw) or set(raw) != {"profile", "wire_b64"}:
            return None
        profile = raw["profile"]
        text = raw["wire_b64"]
        if type(profile) is not str or profile != PROFILE or type(text) is not str:
            return None
        head = text[:12]
        # Twelve characters of the alphabet are nine octets; a padded head encodes fewer.
        if len(head) < 12 or not all(character in _BASE64_ALPHABET for character in head):
            return None
        return base64.b64decode(head) in MAGICS

    def validate_source(self, raw: bytes | dict) -> list[str]:
        """Engineering-profile validation of SC4545-CORE-1, not full STANAG 4545 validation.

        One string for the first fatal error, else the violations of the profile the parse
        found (malformed dates, display-level faults, invalid corners) in the container's sort
        order. Statuses and limitations of the profile (unsupported pixels, unresolved
        footprints, unknown TREs) are not violations. Needs no context and decodes no sample.
        """
        limits = nsif_codec.CORE1_LIMITS
        try:
            check_argument(raw, limits)
            octets = decode_twin(raw, limits) if type(raw) is dict else raw
            container = parse_container(octets, limits)
        except NsifError as error:
            return [str(error)]
        return [str(found) for found in container.diagnostics if DIAGNOSTIC_CODES[found.code]]

    # ------------------------------------------------------------------------ translation

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """The product Entity, then one footprint per image with an available footprint.

        Stops at the first fatal error, in this order: the argument, the container, the product
        key, `valid_from`, the object count, and after building the serialised size. Every
        refusal is an NsifError; no clock is read and no state is kept between calls.
        """
        # Looked up at call time so that a test lowering a cap changes what is enforced.
        limits = nsif_codec.CORE1_LIMITS
        octets = decode_twin(raw, limits) if type(raw) is dict else raw
        container = parse_container(octets, limits)
        context = self._context
        key = context.product_key
        if key is None:
            key = _source_tuple(container)
            if key is None:
                raise _context_error(
                    "/context/product_key",
                    "no product key was supplied and the source tuple is not complete",
                )
        fdt = container.file_header.fdt
        fallback = None
        if fdt.status == "valid":
            valid_from = fdt.value
        elif context.as_of is not None:
            valid_from = context.as_of.instant
            fallback = context.as_of.basis
        else:
            raise _context_error(
                "/context/as_of", "FDT is not a valid instant and no as_of was supplied"
            )
        labels = security_labels(container)
        assessment = assess_security(container)
        footprinted = [image for image in container.images if image.geometry_status == "available"]
        if 1 + len(footprinted) > container.limits.output_objects:
            raise NsifError(
                "E_LIMIT",
                "cdm",
                None,
                "/cdm/objects",
                f"the translation would emit more than {container.limits.output_objects} objects",
            )
        namespace = self.namespace
        source = self.source_ref()
        source_hash = None
        if context.verified_sha256 is not None:
            source_hash = SourceHash(algorithm="sha256", value=context.verified_sha256)
        raw_octets = container.raw
        segments = _segments(container)
        image_entries = {entry["index"]: entry for entry in segments if entry["kind"] == "image"}
        diagnostics = [_diagnostic(found) for found in container.diagnostics]
        images = []
        captures = {}
        for image in container.images:
            captured = image.idatim.value if image.idatim.status == "valid" else None
            captures[image.index] = captured
            images.append(
                {
                    "index": image.index,
                    "iid1": _iid1(raw_octets, image),
                    "capture_time": None if captured is None else times.render(captured),
                    "rows": image.nrows,
                    "columns": image.ncols,
                    "bands": image.band_count,
                    "pvtype": image.pvtype,
                    "abpp": image.abpp,
                    "nbpp": image.nbpp,
                    "compression": image.ic,
                    "mode": image.imode,
                    "pixel_status": image.pixel_status,
                    "geometry_status": image.geometry_status,
                    "composition_status": container.composition_status,
                }
            )
        product_time = times.render(valid_from) if fallback is None else None
        notes = [self.TRANSFORMS["ASCII display trimming"]]
        if product_time is not None or any(value is not None for value in captures.values()):
            notes.append(self.TRANSFORMS["UTC reformatting"])
        if fallback is not None:
            notes.append(self.TRANSFORMS["date fallback"] + " Basis: " + fallback)
        notes.append(self.TRANSFORMS["integer conversion"])
        entity_id = ids.derive(namespace, key, kind="imagery-product")
        product = Entity(
            source=source.model_copy(
                update={
                    "original_id": key,
                    "record_index": 0,
                    "observed_at": None,
                    "source_hash": source_hash,
                    "transformations": notes,
                }
            ),
            source_ids=[SourceId(system=namespace, external_id=key)],
            quality=None,
            status=None,
            residual=ResidualBlock(
                namespace=FORMAT_NAME,
                data={
                    "stanag4545": {
                        "wire_b64": base64.b64encode(raw_octets).decode("ascii"),
                        "file_header": _file_header(container),
                        "segments": segments,
                        "extensions": _extensions(container),
                        "security": {"labels": labels, "assessment": assessment},
                        "parse_profile": {
                            "profile": PROFILE,
                            "profile_revision": PROFILE_REVISION,
                            "adapter_version": self.version,
                            "tre_plugins": [],
                            "capabilities": dict(_PARSE_PROFILE_CAPABILITIES),
                        },
                    }
                },
            ),
            entity_id=entity_id,
            entity_type=EntityType.OVERLAY_OBJECT,
            affiliation=Affiliation.UNKNOWN,
            symbol=None,
            position=None,
            kinematics=None,
            attributes={
                "stanag4545": {
                    "profile": PROFILE,
                    "wire_signature": container.signature,
                    "product_key": key,
                    "product_time": product_time,
                    "asset_ref": context.asset_ref,
                    "images": images,
                    "security_status": assessment["status"],
                    "diagnostics": diagnostics,
                }
            },
            ontology_types=[],
            valid_from=valid_from,
            valid_to=None,
            confidence=None,
        )
        objects: list[CDMBase] = [product]
        file_label = labels[0]
        for image in footprinted:
            objects.append(
                self._footprint(
                    container,
                    image,
                    key,
                    entity_id,
                    source,
                    source_hash,
                    image_entries[image.index],
                    file_label,
                    labels,
                    assessment,
                    diagnostics,
                    captures[image.index],
                )
            )
        # The compact JSON array of what is returned, base64 and escaping included.
        size = 2 + sum(len(item.model_dump_json().encode("utf-8")) for item in objects)
        size += len(objects) - 1
        if size > container.limits.output_bytes:
            raise NsifError(
                "E_LIMIT",
                "cdm",
                None,
                "/cdm/serialized",
                f"the serialised output would exceed {container.limits.output_bytes} octets",
            )
        return objects

    def _footprint(
        self,
        container: Container,
        image,
        key: str,
        entity_id,
        source,
        source_hash,
        entry: dict,
        file_label: dict,
        labels: list[dict],
        assessment: dict,
        diagnostics: list[dict],
        captured,
    ) -> PlanObject:
        namespace = self.namespace
        index = image.index
        found = image.footprint
        label = _iid1(container.raw, image)
        notes = []
        if label is not None:
            notes.append(self.TRANSFORMS["ASCII display trimming"])
        if captured is not None:
            notes.append(self.TRANSFORMS["UTC reformatting"])
        notes.extend(found.transformations)
        image_label = next(
            item for item in labels[1:] if item["scope"] == "image" and item["index"] == index
        )
        prefix = f"/segments/image[{index}]"
        external = _compact([key, index])
        return PlanObject(
            source=source.model_copy(
                update={
                    "original_id": key,
                    "record_index": index,
                    "observed_at": captured,
                    "source_hash": source_hash,
                    "transformations": notes,
                }
            ),
            source_ids=[SourceId(system=namespace, external_id=external)],
            quality=None,
            status=None,
            residual=ResidualBlock(
                namespace=FORMAT_NAME,
                data={
                    "stanag4545": {
                        "presentation": {
                            "role": "coverage_overlay",
                            "type_label": "imagery footprint",
                        },
                        "product": {
                            "product_entity_id": str(entity_id),
                            "system": namespace,
                            "product_key": key,
                            "profile": PROFILE,
                            "wire_signature": container.signature,
                            "image_count": len(container.images),
                        },
                        "image": copy.deepcopy(entry),
                        "footprint": {
                            "geometry_basis": "IGEOLO",
                            "precision": "source_corner_encoding",
                            "accuracy_m": None,
                            "orthorectified": False,
                            "icords": image.icords,
                            "igeolo": _text(container.raw, image.igeolo),
                            "corners": [[lon, lat] for lon, lat in found.corners],
                            "reversed": found.reversed,
                            "split": found.split,
                            "seam_corner": found.seam_corner,
                            "duplicates_removed": found.duplicates_removed,
                        },
                        "label_basis": "image_ordinal" if label is None else "IID1",
                        "security": {
                            "label_scope": [
                                {"scope": "file", "index": None},
                                {"scope": "image", "index": index},
                            ],
                            "labels": [copy.deepcopy(file_label), copy.deepcopy(image_label)],
                            "assessment": copy.deepcopy(assessment),
                        },
                        "diagnostics": [
                            dict(item)
                            for item in diagnostics
                            if item["path"] == prefix or item["path"].startswith(prefix + "/")
                        ],
                    }
                },
            ),
            object_id=ids.derive(namespace, external, kind="imagery-footprint"),
            object_type=ObjectType.ANNOTATION,
            label=f"Image {index + 1}" if label is None else label,
            # The geometry module builds this dict afresh per call; it is copied so the object
            # never shares it with the record.
            geometry=copy.deepcopy(found.geometry),
            style={},
            expires_at=None,
            validity=None if captured is None else TemporalValidity(observed_at=captured),
            route=None,
            area=None,
        )


_BASE64_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")

# The coded guard stands in front of the SDK wrapper: every refusal through `to_cdm` is then an
# NsifError, and the two cap refusals are also the SDK's InputTooLarge and InputTooDeep. The
# wrapper stays behind it, reachable as `__wrapped__`, and repeats its checks on what the guard
# admitted.
_sdk_to_cdm = Stanag4545Adapter.to_cdm


@functools.wraps(_sdk_to_cdm)
def _guarded_to_cdm(self, raw):
    check_argument(raw, nsif_codec.CORE1_LIMITS)
    return _sdk_to_cdm(self, raw)


Stanag4545Adapter.to_cdm = _guarded_to_cdm
