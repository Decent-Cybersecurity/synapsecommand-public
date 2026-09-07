"""Present on purpose, not by accident: it fixes the test modules' identity.

`tests/test_cdm_harness.py` hands the harness a `module:Class` string pointing back at
itself, which is how an adapter the harness has never heard of gets resolved. Without this
file `tests` is a namespace package, so pytest imports the module as `test_cdm_harness`
while the harness imports the same file again as `tests.test_cdm_harness` — two module
objects, two class definitions, and the adapter registry rejects the second name as a
duplicate. One package, one identity.
"""


def probe_metadata(name: str, version: str = "0.1.0", direction: str = "ingest",
                   **overrides):
    """A valid `AdapterMetadata` for a TEST double, in one place rather than in six files.

    Adapter API v2 requires `metadata` on every `Adapter` subclass (M's ruling F1.1), and the
    requirement reaches the doubles this suite defines: `_Minimal`, `_LossyAdapter`,
    `_OutsideAdapter`, `_ProbeAdapter`. Each of them needs a declaration that is VALID —
    the point of the rule is that no framework code invents one — and each of them needs it to
    say the same uninteresting thing, because none of these classes is about metadata.

    So it is built HERE and not repeated. A per-file copy would be six declarations to keep in
    step with the model, and the first time a required field arrived they would go out of step
    one file at a time, which is the drift this repository writes gates against.

    `overrides` is what makes it usable for the refusals too: a test proving that a bad
    combination is refused passes exactly the one field it is making bad.
    """
    from synapse_cdm.manifest import (AdapterMetadata, Capabilities, ClaimStatus, Direction,
                                      Evidence, FormatRef, LicenseClass, Limits, Maturity,
                                      MaturityLevel, Residual)

    exercised = {"ingest": ["ingest"], "egress": ["egress"],
                 "bidirectional": ["ingest", "egress"]}.get(direction, [])
    fields = dict(
        id=name,
        name=f"probe {name}",
        adapter_version=version,
        format=FormatRef(name="a test double's format", version="0"),
        direction=Direction(direction),
        license_class=LicenseClass.OPEN,
        maturity=Maturity(level=MaturityLevel.L0, basis="a test double; no rung is claimed",
                          external_exercise=None),
        claim_status=ClaimStatus.DOCUMENTED,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=exercised,
            message_types=["whatever the test hands it"],
            limits=Limits(max_input_bytes=None, max_depth=None, max_objects=None,
                          max_decompressed_bytes=None, max_parse_seconds=None,
                          absent_because={field: "a test double declares no bounds"
                                          for field in ("max_input_bytes", "max_depth",
                                                        "max_objects", "max_decompressed_bytes",
                                                        "max_parse_seconds")}),
        ),
        limitations=["it is a test double and translates nothing anybody uses"],
        limitations_empty_reason=None,
        residual=Residual.LEGACY,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=False),
    )
    fields.update(overrides)
    return AdapterMetadata(**fields)
