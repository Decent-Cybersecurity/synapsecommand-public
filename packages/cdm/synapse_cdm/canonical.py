"""The one serialisation — ARCHITECTURE.md §6.2's form, written once.

WHY THIS IS A MODULE AND NOT A LINE
-----------------------------------
§6.2 fixes the canonical serialisation for comparison, hashing and golden storage as
`json.dumps(obj, sort_keys=True, indent=2)`, UTF-8, trailing newline, "stated here so that no
later round chooses a second one". No later round chose a second one; four of them chose the
same one again. By 2026-09-16 the expression was written at seven sites — the schema exporter,
the manifest writer, the harness's golden comparison, the suite's determinism check (whose
docstring said "written once here"), the evidence record and its two badge writes — and three of
those sites each described their own copy as §6.2's "one serialisation". Seven identical
expressions are one serialisation only until one of them is edited alone, and the edit that
breaks a golden diff is exactly the kind nobody notices in review.

So the expression lives here and the seven sites call it. This module imports the standard
library and nothing else, which is why it can sit under every one of them: `schemas` and
`manifests` are imported by the harness and cannot import it back, so the shared definition has
to be a leaf. Output bytes are unchanged by construction — the seven expressions were
byte-identical — which is why the goldens, the manifests and the evidence digests did not move
when they started calling this.

`sort_keys=True` is what makes two serialisations of one object comparable as strings; `indent=2`
is the goldens' existing form; the trailing newline is what `git diff` and every POSIX text tool
expect at the end of a file.
"""
from __future__ import annotations

import json
from typing import Any


def serialise(payload: Any) -> str:
    """`json.dumps(payload, sort_keys=True, indent=2)` with a trailing newline — §6.2, verbatim."""
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
