"""The distribution's version, read by setuptools (`[tool.setuptools.dynamic]`) and by the CLI.

`1.0.0` names the implementation of one contract, SC Link16 Gateway 1.0.0, and is independent of
the `synapse-cdm` version it runs on: the two distributions have separate histories.

Moved 1.0.0 -> 1.1.0 on 2026-10-16, a MINOR, with the `synapse-cdm` 3.5.0 release: the bridge gained
`negotiate.dump`, which serialises every `COMPAT_3_0` object through `synapse_cdm.projection`, and
its floor moved to the first `synapse-cdm` that carries that module. The CLI, the configuration and
what a sink receives are unchanged, so it is not a MAJOR; a new function and a moved floor are not
a fix, so it is not a PATCH. It still implements SC Link16 Gateway 1.0.0."""

__version__ = "1.1.0"
