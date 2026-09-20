"""An authorised normative schema held OUTSIDE the repository, verified before anything uses it.

Audit remediation F05 (2026-09-20). Some source formats are bound to a schema this repository may
not hold: STANAG 4676's XSD is distributed through NATO national representatives (AEDP-12 Ed B
§B.5) and belongs in no public Git tree and no published wheel. An adapter that wants to VERIFY a
document against such a schema — rather than read it through a profile chosen here — needs the
schema from somewhere, and "somewhere" has to be explicit, recorded and checked, or a missing
resource turns into a silent pass.

This module is that somewhere. `resolve()` reads ONE environment variable naming a directory, and
holds the directory to a record file beside the schema files: the edition, the schema's own
revision number and date, its provenance and usage rights, and the SHA-256 of every file, each
recomputed. The first thing that does not hold raises `NormativeBindingBlocked` naming the STEP —
the register's `BLOCKED_EXTERNAL_EVIDENCE`, as an exception a program can act on — and the
adapter that asked never receives a resource it could mistake for a verified one.

WHY IT IS NOT INSIDE THE ADAPTER MODULE. `tests/test_cdm_parser_safety.py` derives the set of
adapters that decode JSON payloads by walking each adapter module's AST for `json.load(s)`, and
holds that set to the depth-bound tests. The record here is JSON and is configuration, not a
payload, so the read lives outside `adapters/` where the derivation looks — the alternative was
spelling the decode differently to slip past a gate, which is the thing gates exist to catch.

WHAT IT DOES NOT DO. It fetches nothing: no URL, no network, no default location. It validates
nothing itself: validation is an XSD validator's job, and neither `xmlschema` nor `lxml` is a
dependency of this package — `xsd_validator` imports whichever is present, with entity
resolution, DTD loading and network access switched off, and reports step `validator` BLOCKED
when neither imports. Adding a dependency is the maintainer's decision and is recorded in the
audit register, not made here.
"""
from __future__ import annotations

import dataclasses
import json
import os
import pathlib
from typing import Any, Callable, Mapping, Sequence

from synapse_cdm import evidence

#: The register's word for "the resource this needs is not in this environment".
BLOCKED_STATUS = "BLOCKED_EXTERNAL_EVIDENCE"

#: The steps `resolve()` checks, in order, plus the one the ADAPTER performs with the resource
#: (`validate`). An adapter's procedure text is keyed on exactly these names, and a test holds
#: the two together.
STEPS = ("hook", "directory", "record", "files", "checksum", "validator", "validate")


class NormativeBindingBlocked(ValueError):
    """An explicit request for verified normative support this environment cannot honour.

    `step` is the first entry of `STEPS` that failed; `status` is the register's word. The
    message carries the caller's whole procedure when one is given, so the refusal says what
    would have satisfied it.
    """

    status = BLOCKED_STATUS

    def __init__(self, step: str, reason: str,
                 procedure: Sequence[tuple[str, str]] = ()) -> None:
        if step not in STEPS:
            raise ValueError(f"{step!r} is not one of {list(STEPS)}")
        self.step = step
        self.reason = reason
        text = (f"{BLOCKED_STATUS} at step {step!r}: {reason}. No provisional or fallback "
                f"codec is used in its place — a request for the normative binding is answered "
                f"with the normative binding or with this refusal.")
        if procedure:
            text += " Procedure, in order: " + "; ".join(
                f"[{name}] {what}" for name, what in procedure)
        super().__init__(text)


def sha256_of(path: pathlib.Path) -> str:
    """A content digest, through `evidence.digest` — the ONE module M's ruling of 2026-09-08
    allows `hashlib` in (`tests/test_cdm_boundary.py`, `CRYPTO_ALLOWANCE`): this is a checksum of
    a file the operator holds, the same kind of fact an evidence record's `FileHash` carries, and
    not a signature. Attribute access at call time, because `evidence` imports the adapters and
    the adapters import this module."""
    return evidence.digest(path)[0]


class XmlschemaValidator:
    """`xmlschema`, sandboxed to the resource directory: no fetch, no entity expansion."""

    def __init__(self, schema_path: pathlib.Path) -> None:
        import xmlschema  # not a dependency; imported only under an explicit normative mode
        self.name = f"xmlschema {getattr(xmlschema, '__version__', '?')}"
        self._schema = xmlschema.XMLSchema(str(schema_path), base_url=str(schema_path.parent),
                                           allow="sandbox", defuse="always")

    def validate(self, document: bytes) -> None:
        self._schema.validate(document.decode("utf-8"))


class LxmlValidator:
    """`lxml`, with network access, entity resolution and DTD loading switched off."""

    def __init__(self, schema_path: pathlib.Path) -> None:
        from lxml import etree  # not a dependency; imported only under an explicit normative mode
        self.name = f"lxml {etree.LXML_VERSION[0]}.{etree.LXML_VERSION[1]}"
        self._parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False)
        self._schema = etree.XMLSchema(etree.parse(str(schema_path), self._parser))
        self._etree = etree

    def validate(self, document: bytes) -> None:
        self._schema.assertValid(self._etree.fromstring(document, self._parser))


#: The validators tried, in order. Each is a class taking the schema path and exposing `name`
#: and `validate(bytes)`; a constructor raising `ImportError` means "not installed here".
VALIDATORS: tuple[type, ...] = (XmlschemaValidator, LxmlValidator)


def xsd_validator(schema_path: pathlib.Path, procedure: Sequence[tuple[str, str]] = ()) -> Any:
    """The first validator that imports, or `NormativeBindingBlocked` at step `validator`."""
    absent = []
    for factory in VALIDATORS:
        try:
            return factory(schema_path)
        except ImportError as e:
            absent.append(f"{factory.__name__}: {e}")
    raise NormativeBindingBlocked(
        "validator",
        "no XSD validator imports in this environment (" + "; ".join(absent) + "); `xmlschema` "
        "(MIT) or `lxml` (BSD-3-Clause) would, and neither is a dependency of this package",
        procedure)


@dataclasses.dataclass(frozen=True)
class LocalSchemaResource:
    """A verified local resource: where it is, what its record says, what each file hashes to,
    and the validator built from its first file. Constructed by `resolve()` only."""

    directory: pathlib.Path
    record: dict
    checksums: dict[str, str]
    validator: Any


def resolve(*, env_var: str, record_name: str, files: Sequence[str], fields: Sequence[str],
            environ: Mapping[str, str] | None = None,
            validator_factory: Callable[[pathlib.Path], Any] | None = None,
            procedure: Sequence[tuple[str, str]] = ()) -> LocalSchemaResource:
    """Resolve the hook, verify the record and every checksum, build the validator — or raise
    `NormativeBindingBlocked` at the first of `STEPS` that does not hold.

    `env_var` names the directory; `record_name` is the JSON record inside it; `files` are the
    schema files that must sit beside the record and be named in its `files` map (name ->
    lowercase hex SHA-256); `fields` are the record's required non-empty keys, `files` among
    them. `environ` and `validator_factory` are test seams: the defaults are `os.environ` and
    `xsd_validator`, and nothing else is read.
    """
    env = os.environ if environ is None else environ
    where = (env.get(env_var) or "").strip()
    if not where:
        raise NormativeBindingBlocked("hook", f"{env_var} is not set", procedure)
    directory = pathlib.Path(where)
    if not directory.is_dir():
        raise NormativeBindingBlocked("directory", f"{env_var}={where!r} is not a directory",
                                      procedure)
    record_path = directory / record_name
    if not record_path.is_file():
        raise NormativeBindingBlocked("record", f"{record_name} is not in the directory",
                                      procedure)
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise NormativeBindingBlocked("record", f"{record_name} is not JSON: {e}",
                                      procedure) from e
    if not isinstance(record, dict):
        raise NormativeBindingBlocked("record", f"{record_name} is not a JSON object", procedure)
    empty = [field for field in fields if not record.get(field)]
    if empty:
        raise NormativeBindingBlocked("record", f"{record_name} leaves {empty} empty", procedure)
    recorded = record.get("files")
    if not isinstance(recorded, dict):
        raise NormativeBindingBlocked("record", "`files` is not an object of name -> sha256",
                                      procedure)
    unnamed = [name for name in files if name not in recorded]
    if unnamed:
        raise NormativeBindingBlocked("files", f"the record names no checksum for {unnamed}",
                                      procedure)
    missing = [name for name in files if not (directory / name).is_file()]
    if missing:
        raise NormativeBindingBlocked("files", f"{missing} not present beside the record",
                                      procedure)
    checksums = {}
    for name in files:
        actual = sha256_of(directory / name)
        expected = str(recorded[name]).strip().lower()
        if actual != expected:
            raise NormativeBindingBlocked(
                "checksum", f"{name} hashes to {actual} and the record says {expected}", procedure)
        checksums[name] = actual
    if validator_factory is None:
        validator = xsd_validator(directory / files[0], procedure)
    else:
        validator = validator_factory(directory / files[0])
    return LocalSchemaResource(directory=directory, record=record, checksums=checksums,
                               validator=validator)
