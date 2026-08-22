"""Concrete adapters. One module per external system, each a thin translator and nothing more.

Modules here are imported by `synapse_cdm.adapter.discover()` so that subclasses register
themselves by name. An adapter that lives outside this package is equally valid and equally
testable — the harness takes `module:ClassName` — which is the case the adapter factory will
be in.
"""
