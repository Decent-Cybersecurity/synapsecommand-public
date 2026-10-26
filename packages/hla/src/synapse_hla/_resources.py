"""Read-only access to the package's own data files: the schemas and the pin list.

The pure modules may not open files (D-08), yet `config` validates against the packaged config
schema and `_fom` compares against the packaged `pins.json`. This helper is the one place that
reads them, through `importlib.resources` so that it works from a wheel, a zip or a source tree
alike. It reads nothing but package data: never the environment, never a path a caller names.

Bytes are cached, documents are not: every caller gets a freshly parsed document, so no caller
can change what the next one reads.
"""

from __future__ import annotations

import functools
import importlib.resources

from synapse_hla import canonical

#: The bundle's thirteen schemas, byte-identical to the handoff (CR-L03).
SCHEMA_DIR = "schemas"
#: The schemas the product defines for its own outputs (CR-L03).
LOCAL_SCHEMA_DIR = "local_schemas"
SCHEMA_SUFFIX = ".schema.json"
PINS = "pins.json"


@functools.lru_cache(maxsize=None)
def package_bytes(directory: str, name: str) -> bytes:
    """The bytes of one data file of the package; `directory` "" for the package root."""
    node = importlib.resources.files("synapse_hla")
    if directory:
        node = node.joinpath(directory)
    return node.joinpath(name).read_bytes()


@functools.lru_cache(maxsize=None)
def schema_names(directory: str) -> tuple[str, ...]:
    """The schema file names of one schema directory, sorted."""
    node = importlib.resources.files("synapse_hla").joinpath(directory)
    return tuple(sorted(entry.name for entry in node.iterdir()
                        if entry.is_file() and entry.name.endswith(SCHEMA_SUFFIX)))


def package_json(directory: str, name: str):
    """One data file of the package, parsed by the strict reader into a fresh document."""
    return canonical.strict_loads(package_bytes(directory, name), floats=True, surrogates=False)
