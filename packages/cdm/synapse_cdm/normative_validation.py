"""Offline normative validation: an XML document against an XSD closure held OUTSIDE the tree.

Adapter expansion phase 1 (2026-09-20). `normative_binding.resolve()` already does the first
half — one environment variable names a directory, a record beside the schema files states the
edition and the SHA-256 of every file, and the first thing that does not hold raises
`NormativeBindingBlocked` naming the step. What it leaves to the caller is the second half, and
the C2SIM, AIXM 5.1.1 / 5.2 and Digital NOTAM closures make that half non-trivial: an AIXM
message schema imports GML, ISO 19139 and xlink by `schemaLocation`s that spell the publishers'
HTTP URLs, and a validator that followed them would either fetch from the network or fail with a
message that reads like a broken schema.

THREE OUTCOMES, KEPT APART BECAUSE THEY SEND A READER TO THREE DIFFERENT PLACES
--------------------------------------------------------------------------------
* `VALID`       — the resource was resolved and verified, the closure compiled from local files
                  only, and the document validates.
* `INVALID`     — the same, and the document does not validate; `problems` carries the
                  validator's own messages. A finding about the DOCUMENT.
* `UNAVAILABLE` — the judgement could not be made: the hook is unset, the directory or record is
                  missing, a checksum does not match, `lxml` is not installed, or the closure
                  needed a resource the local resolver refused. `step` names which of
                  `normative_binding.STEPS` failed. A finding about the ENVIRONMENT, and the one a
                  test records as BLOCKED rather than as a pass (`tests/normative_support.py`).

`validate()` never raises for either of the last two; it returns the verdict, so a caller cannot
mistake "could not check" for "checked and fine" by catching the wrong exception.

THE LOCAL RESOLVER
------------------
lxml consults a Python `Resolver` for every schema import and include (read empirically on
2026-09-20: the resolver is called with the entry file's own path, then with each
`schemaLocation` as written). `LocalResolver` answers three ways and no fourth:

1. a relative or local path under the binding's directory — left to libxml2, which reads the
   file (no network is involved in reading a file);
2. a remote URL the binding's OASIS XML catalog rewrites (`rewriteURI`, `uri`, `system`,
   `rewriteSystem`) to a file under the directory — resolved to that file, and recorded;
3. anything else — a remote URL with no catalog entry, an absolute path outside the directory —
   REFUSED: recorded, and answered with an empty document so the compile fails rather than
   proceeds. The parser is additionally created with `no_network=True`, so a refusal this class
   somehow missed would meet libxml2's own.

The catalog is read by this module (through `secure_xml`, which is what every catalog file in the
normative directory is small enough for) rather than through libxml2's `XML_CATALOG_FILES`, so
the resolution does not depend on a process-global environment variable being exported before
the first parse, and the record of what was resolved is this module's own.

WHAT THIS IS NOT
----------------
Not a runtime dependency: `lxml` is the optional `validate` extra
(`pip install "synapse-cdm[validate]"`), imported inside the validator's constructor and nowhere
at module level, so the package imports and every adapter discovers without it. Not the
adapters' structural check either — an adapter parses with `secure_xml` and the standard
library; this is the normative judgement, made on request, with the resource the record names.
"""
from __future__ import annotations

import dataclasses
import enum
import json
import os
import pathlib
from typing import Any, Mapping, Sequence

from synapse_cdm import normative_binding, secure_xml
from synapse_cdm.normative_binding import BLOCKED_STATUS, NormativeBindingBlocked

#: The OASIS XML Catalogs namespace.
CATALOG_NAMESPACE = "urn:oasis:names:tc:entity:xmlns:xml:catalog"

#: A catalog file is small; these bounds are generous for one and refuse a catalog that is not.
CATALOG_LIMITS = secure_xml.XmlLimits(max_bytes=1_048_576, max_depth=16, max_elements=10_000)

#: URL schemes that name something on a network. Everything else is a path.
REMOTE_SCHEMES = frozenset({"http", "https", "ftp", "ftps", "sftp", "data"})


def url_scheme(url: str) -> str:
    """The scheme of `url`, lower-cased, or `""` for a bare path — RFC 3986 §3.1's grammar
    (`ALPHA *( ALPHA / DIGIT / "+" / "-" / "." ) ":"`), read here rather than through
    `urllib`, which `tests/test_cdm_no_network.py` keeps out of every module of this package: a
    URL is only ever CLASSIFIED here, never fetched. A Windows drive letter (`C:`) is one
    character and is not a scheme."""
    head, sep, _ = url.partition(":")
    if not sep or len(head) < 2 or not head[0].isalpha():
        return ""
    if not all(c.isalnum() or c in "+-." for c in head):
        return ""
    return head.lower()


def _file_url_path(url: str) -> pathlib.Path:
    """`file:///a/b%20c.xsd` -> `/a/b c.xsd`: the path part with percent-escapes decoded."""
    rest = url.partition(":")[2]
    if rest.startswith("//"):
        rest = rest[2:]
        slash = rest.find("/")
        rest = rest[slash:] if slash >= 0 else ""
    out, i = [], 0
    while i < len(rest):
        pair = rest[i + 1:i + 3]
        if rest[i] == "%" and len(pair) == 2 and all(c in "0123456789abcdefABCDEF" for c in pair):
            out.append(chr(int(pair, 16)))
            i += 3
        else:
            out.append(rest[i])
            i += 1
    return pathlib.Path("".join(out))

#: The record fields every binding's `xsd_pin.json` must fill — `stanag4676`'s set, which the
#: four phase-0 records were written to.
RECORD_FIELDS: tuple[str, ...] = ("edition", "schema_revision", "schema_revision_date",
                                  "target_namespace", "provenance", "usage_rights", "obtained_on",
                                  "files")


class Outcome(str, enum.Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


@dataclasses.dataclass(frozen=True)
class Verdict:
    """What `validate()` returns. `step` is set only when `outcome` is UNAVAILABLE."""

    outcome: Outcome
    validator: str | None
    problems: tuple[str, ...]
    step: str | None = None
    resolved: tuple[str, ...] = ()
    refused: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        return self.outcome is Outcome.UNAVAILABLE

    def describe(self) -> str:
        if self.outcome is Outcome.UNAVAILABLE:
            return f"{BLOCKED_STATUS} at step {self.step!r}: " + "; ".join(self.problems)
        head = f"{self.outcome.value} by {self.validator}"
        return head if not self.problems else head + ": " + "; ".join(self.problems)


@dataclasses.dataclass(frozen=True)
class Binding:
    """One normative resource hook: the environment variable and the record that describes it."""

    name: str
    env_var: str
    record_name: str = "xsd_pin.json"
    fields: tuple[str, ...] = RECORD_FIELDS


#: The four hooks phase 0 provisioned (`docs/adapter-expansion-implementation.md`, Source pins).
BINDINGS: dict[str, Binding] = {
    "c2sim": Binding("c2sim", "SYNAPSE_CDM_C2SIM_XSD_DIR"),
    "aixm511": Binding("aixm511", "SYNAPSE_CDM_AIXM511_XSD_DIR"),
    "aixm52": Binding("aixm52", "SYNAPSE_CDM_AIXM52_XSD_DIR"),
    "dnotam": Binding("dnotam", "SYNAPSE_CDM_DNOTAM_XSD_DIR"),
}


# ------------------------------------------------------------------------------ the catalog


@dataclasses.dataclass(frozen=True)
class CatalogRule:
    kind: str          # "rewrite" (prefix) or "exact"
    match: str
    target: str


def read_catalog(path: pathlib.Path) -> tuple[CatalogRule, ...]:
    """The `rewriteURI` / `rewriteSystem` (prefix) and `uri` / `system` (exact) entries of an
    OASIS catalog, relative targets resolved against the catalog's own directory. Parsed through
    `secure_xml`, so a catalog carrying a DTD or an XInclude is refused like any other document."""
    parsed = secure_xml.parse(path.read_bytes(), CATALOG_LIMITS)
    base = path.parent
    rules: list[CatalogRule] = []
    for element in parsed.root.iter():
        tag = element.tag
        local = tag.split("}", 1)[1] if tag.startswith("{" + CATALOG_NAMESPACE + "}") else tag
        if local in ("rewriteURI", "rewriteSystem"):
            start = element.get("uriStartString") if local == "rewriteURI" \
                else element.get("systemIdStartString")
            prefix = element.get("rewritePrefix")
            if start and prefix is not None:
                # `os.path.join`, not `pathlib`: a `rewritePrefix` ends in the slash the rewritten
                # URL's remainder is appended after, and pathlib would strip it (read 2026-09-20
                # against the AIXM 5.1.1 catalog, whose `gml/3.2.1/` became `gml/3.2.1gml.xsd`).
                rules.append(CatalogRule("rewrite", start, os.path.join(str(base), prefix)))
        elif local in ("uri", "system"):
            name = element.get("name") if local == "uri" else element.get("systemId")
            target = element.get("uri")
            if name and target:
                rules.append(CatalogRule("exact", name, os.path.join(str(base), target)))
    return tuple(rules)


def apply_catalog(rules: Sequence[CatalogRule], url: str) -> pathlib.Path | None:
    """The local file a URL rewrites to, or None. Exact entries win; among prefix entries the
    longest match wins (OASIS XML Catalogs 1.1 §7.1.2)."""
    for rule in rules:
        if rule.kind == "exact" and rule.match == url:
            return pathlib.Path(rule.target)
    best: CatalogRule | None = None
    for rule in rules:
        if rule.kind == "rewrite" and url.startswith(rule.match):
            if best is None or len(rule.match) > len(best.match):
                best = rule
    if best is None:
        return None
    return pathlib.Path(best.target + url[len(best.match):])


# ----------------------------------------------------------------------------- the validator


def _make_resolver_class():
    """The resolver, built once `lxml` is known to import. Defined inside a function because the
    base class is lxml's, and this module must import without lxml."""
    from lxml import etree

    class LocalResolver(etree.Resolver):
        """Files under the directory, catalog rewrites to files under the directory, and nothing
        else — see the module docstring."""

        def __init__(self, directory: pathlib.Path, rules: Sequence[CatalogRule]) -> None:
            super().__init__()
            self.directory = directory.resolve()
            self.rules = tuple(rules)
            self.resolved: list[str] = []
            self.refused: list[str] = []

        def _inside(self, path: pathlib.Path) -> bool:
            try:
                path.resolve().relative_to(self.directory)
            except ValueError:
                return False
            return True

        def resolve(self, url, pubid, context):  # noqa: D401 - lxml's signature
            scheme = url_scheme(url)
            if scheme in REMOTE_SCHEMES:
                local = apply_catalog(self.rules, url)
                if local is not None and local.is_file() and self._inside(local):
                    self.resolved.append(f"{url} -> {local}")
                    return self.resolve_filename(str(local), context)
                self.refused.append(url)
                return self.resolve_string("", context)
            path = _file_url_path(url) if scheme == "file" else pathlib.Path(url)
            if path.is_absolute() and not self._inside(path):
                self.refused.append(url)
                return self.resolve_string("", context)
            return None

    return LocalResolver


class LocalLxmlValidator:
    """`lxml`, compiled from the entry schema through `LocalResolver`, network off.

    Exposes `name` and `validate(bytes)` — the shape `normative_binding.LocalSchemaResource`
    expects — plus `resolved` and `refused`, the resolver's two records. A constructor that
    cannot compile raises `NormativeBindingBlocked` at step `validator`, naming every remote
    resource the closure asked for and was refused.
    """

    def __init__(self, entry: pathlib.Path, *, directory: pathlib.Path,
                 rules: Sequence[CatalogRule] = ()) -> None:
        try:
            from lxml import etree
        except ImportError as e:
            raise NormativeBindingBlocked(
                "validator", f"lxml does not import ({e}); it is the optional `validate` extra: "
                             "pip install \"synapse-cdm[validate]\"") from e
        self._etree = etree
        self.name = f"lxml {etree.LXML_VERSION[0]}.{etree.LXML_VERSION[1]}"
        self._parser = etree.XMLParser(no_network=True, resolve_entities=False, load_dtd=False,
                                       huge_tree=False)
        self._resolver = _make_resolver_class()(directory, rules)
        self._parser.resolvers.add(self._resolver)
        try:
            self._schema = etree.XMLSchema(etree.parse(str(entry), self._parser))
        except (etree.XMLSchemaParseError, etree.XMLSyntaxError, OSError) as e:
            refused = ", ".join(self._resolver.refused) or "none"
            raise NormativeBindingBlocked(
                "validator", f"the closure rooted at {entry.name} did not compile offline: {e}. "
                             f"Remote resources refused by the local resolver: {refused}") from e

    @property
    def resolved(self) -> tuple[str, ...]:
        return tuple(self._resolver.resolved)

    @property
    def refused(self) -> tuple[str, ...]:
        return tuple(self._resolver.refused)

    def validate(self, document: bytes) -> None:
        """Raise `lxml.etree.DocumentInvalid` (or `XMLSyntaxError`) on a document that does not
        validate; return None on one that does."""
        self._schema.assertValid(self._etree.fromstring(document, self._parser))


# ------------------------------------------------------------------------------ resolution


def _read_record(binding: Binding, environ: Mapping[str, str] | None) -> tuple[pathlib.Path, dict]:
    """The directory and the record, or `NormativeBindingBlocked` at hook / directory / record —
    the same three steps `resolve()` checks first, taken here because the file list `resolve()`
    needs is inside the record."""
    env = os.environ if environ is None else environ
    where = (env.get(binding.env_var) or "").strip()
    if not where:
        raise NormativeBindingBlocked("hook", f"{binding.env_var} is not set")
    directory = pathlib.Path(where)
    if not directory.is_dir():
        raise NormativeBindingBlocked("directory", f"{binding.env_var}={where!r} is not a directory")
    record_path = directory / binding.record_name
    if not record_path.is_file():
        raise NormativeBindingBlocked("record", f"{binding.record_name} is not in the directory")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise NormativeBindingBlocked("record", f"{binding.record_name} is not JSON: {e}") from e
    if not isinstance(record, dict):
        raise NormativeBindingBlocked("record", f"{binding.record_name} is not a JSON object")
    return directory, record


def build(binding: Binding, *, environ: Mapping[str, str] | None = None
          ) -> normative_binding.LocalSchemaResource:
    """Resolve and verify the binding and compile its closure, or raise `NormativeBindingBlocked`.

    The record's `entry_file` names the schema the closure is rooted at and its `files` map names
    every file that must be present and hash-verified; `catalog`, when present, names the OASIS
    catalog that maps the closure's remote `schemaLocation`s to local copies.
    """
    directory, record = _read_record(binding, environ)
    entry = record.get("entry_file")
    files_map = record.get("files")
    if not isinstance(entry, str) or not entry:
        raise NormativeBindingBlocked("record", f"{binding.record_name} names no `entry_file`")
    if not isinstance(files_map, dict) or entry not in files_map:
        raise NormativeBindingBlocked("record", f"{binding.record_name}'s `files` map does not "
                                                f"name the entry file {entry!r}")
    files = [entry] + sorted(name for name in files_map if name != entry)
    rules: tuple[CatalogRule, ...] = ()
    catalog = record.get("catalog")
    if isinstance(catalog, str) and catalog:
        catalog_path = directory / catalog
        if not catalog_path.is_file():
            raise NormativeBindingBlocked("files", f"the record names catalog {catalog!r}, which is "
                                                   "not beside it")
        rules = read_catalog(catalog_path)

    def factory(entry_path: pathlib.Path) -> LocalLxmlValidator:
        return LocalLxmlValidator(entry_path, directory=directory, rules=rules)

    return normative_binding.resolve(env_var=binding.env_var, record_name=binding.record_name,
                                     files=files, fields=binding.fields, environ=environ,
                                     validator_factory=factory)


def validate(binding: Binding | str, document: bytes | str, *,
             environ: Mapping[str, str] | None = None,
             limits: secure_xml.XmlLimits | None = None) -> Verdict:
    """The verdict on `document` under `binding` — VALID, INVALID or UNAVAILABLE, never raised.

    `limits`, when given, holds the document to `secure_xml.parse` first, so a document carrying
    a DTD, an entity, an XInclude or more than the bounds is INVALID with that diagnostic before
    the validator sees it.
    """
    if isinstance(binding, str):
        if binding not in BINDINGS:
            raise KeyError(f"no binding named {binding!r}; known: {sorted(BINDINGS)}")
        binding = BINDINGS[binding]
    octets = document.encode("utf-8") if isinstance(document, str) else bytes(document)
    try:
        resource = build(binding, environ=environ)
    except NormativeBindingBlocked as e:
        return Verdict(Outcome.UNAVAILABLE, None, (e.reason,), step=e.step)
    validator: Any = resource.validator
    resolved = tuple(getattr(validator, "resolved", ()))
    refused = tuple(getattr(validator, "refused", ()))
    if limits is not None:
        try:
            secure_xml.parse(octets, limits)
        except secure_xml.XmlRefused as e:
            return Verdict(Outcome.INVALID, validator.name, (str(e),), resolved=resolved,
                           refused=refused)
    try:
        validator.validate(octets)
    except Exception as e:                                # noqa: BLE001 - the validator's own
        problems = _problems(validator, e)                # classes, read by name below
        return Verdict(Outcome.INVALID, validator.name, problems, resolved=resolved,
                       refused=refused)
    return Verdict(Outcome.VALID, validator.name, (), resolved=resolved, refused=refused)


def _problems(validator: Any, error: Exception) -> tuple[str, ...]:
    """The validator's messages, one per line, from lxml's error log where there is one."""
    log = getattr(getattr(validator, "_schema", None), "error_log", None)
    lines = [str(entry) for entry in log] if log is not None else []
    if not lines:
        lines = [f"{type(error).__name__}: {error}"]
    return tuple(lines)
