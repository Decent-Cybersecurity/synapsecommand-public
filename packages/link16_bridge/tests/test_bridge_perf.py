"""The measurement harness at smoke scale (F01, REQ161, REQ162). The accounting gates are hard
gates at any scale; no duration is asserted, and nothing measured here is evidence for REQ161."""
import json
import platform
import sys

from synapse_link16_bridge import perf


def test_harness_accounting_gates_at_smoke_scale_and_never_claims_evidence_here(tmp_path):
    result = perf.run(rate=20, duration=2, burst="5:1", identities=6,
                      store_dir=str(tmp_path / "perf"), sleeper=lambda seconds: None)
    assert result["parameters"] == {"rate": 20, "duration": 2, "burst": "5:1", "identities": 6}
    for tenant in perf.TENANTS:
        accounting = result["accounting"][tenant]
        assert (accounting["published"], accounting["fed"], accounting["accepted"],
                accounting["refused"], accounting["duplicate"],
                accounting["dropped_by_capacity"], accounting["provider_losses"]) == \
            (45, 45, 45, 0, 0, 0, 0)
    assert result["gates"] == {"every_input_accounted_for": "PASS",
                               "zero_cross_tenant_identity_collisions": "PASS",
                               "zero_invented_coordinates": "PASS",
                               "zero_unintended_sends": "PASS"}
    assert (result["cross_tenant_collisions"], result["invented_coordinates"],
            result["unintended_sends"]) == (0, 0, 0)
    assert result["measurements"]["mapping_samples"] == 90
    assert result["evidence_eligible"] is False          # the smoke parameters are never full
    assert result["targets"].startswith("NOT_EVALUATED")
    assert (result["rig"]["system"], result["rig"]["machine"]) == (sys.platform,
                                                                  platform.machine())
    for key in ("cpu_model", "cpu_count", "platform", "python", "sqlite", "synapse_cdm",
                "synapse_link16_bridge", "disk"):
        assert key in result["rig"]
    json.dumps(result)


def test_only_the_named_rig_with_the_full_parameters_is_eligible():
    assert perf.FULL == {"rate": 1000, "duration": 1800, "burst": (5000, 10),
                         "identities": 100_000}
    assert perf.TARGETS == {"mapping_p99_ms": 10.0, "publication_p99_ms": 100.0,
                            "rss_bytes": 2 * 1024 ** 3}
