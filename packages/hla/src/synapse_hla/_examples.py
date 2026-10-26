"""The two example configurations of the handoff, as package data the self-test can read.

`self-test` validates both example configurations (OPS-26), and it must run from an installed
package where the repository's `examples/` directory is not present: the package data directories
hold the bundle's schemas and fixtures and nothing else (CR-L03, D-05). So the two files travel
here as their exact bytes, and `tests/test_hla_cli.py` holds each literal to the file in
`examples/` byte for byte, which `tests/contract/vendored-pins.json` holds to the bundle.
"""

#: `examples/config-demo.json`, byte for byte.
CONFIG_DEMO = (
    b'{\n'
    b'  "profile": "SC-HLA-RPR2-OBS-1",\n'
    b'  "session_id": "example-001",\n'
    b'  "source_system": "synthetic-reference",\n'
    b'  "synthetic": true,\n'
    b'  "mode": "demo",\n'
    b'  "endpoint": "rti://127.0.0.1:14321",\n'
    b'  "allow_remote": false,\n'
    b'  "federation_name": "SC_DEMO_0123456789abcdef",\n'
    b'  "federate_name": "SC_OBSERVER",\n'
    b'  "profile_declaration": "bundled-fom-created",\n'
    b'  "time_policy": {\n'
    b'    "mode": "external_elapsed",\n'
    b'    "epoch": "2026-01-01T00:00:00.000000Z",\n'
    b'    "basis": "Synthetic 1x scenario clock asserted by fixture author"\n'
    b'  },\n'
    b'  "force_map": {\n'
    b'    "1": "FRIENDLY"\n'
    b'  }\n'
    b'}\n'
)

#: `examples/config-existing.json`, byte for byte.
CONFIG_EXISTING = (
    b'{\n'
    b'  "profile": "SC-HLA-RPR2-OBS-1",\n'
    b'  "session_id": "local-observation",\n'
    b'  "source_system": "synthetic-reference",\n'
    b'  "synthetic": true,\n'
    b'  "mode": "existing",\n'
    b'  "endpoint": "rti://127.0.0.1:14321",\n'
    b'  "allow_remote": false,\n'
    b'  "federation_name": "SC_DEMO_0123456789abcdef",\n'
    b'  "federate_name": "SC_OBSERVER",\n'
    b'  "profile_declaration": "external-fom-unverified",\n'
    b'  "time_policy": {\n'
    b'    "mode": "none"\n'
    b'  },\n'
    b'  "force_map": {}\n'
    b'}\n'
)

#: File name -> bytes, in the order self-test runs them.
EXAMPLES = (("config-demo.json", CONFIG_DEMO), ("config-existing.json", CONFIG_EXISTING))
