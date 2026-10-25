"""Shared support for the three STANAG 4559 translators' test modules: the bundle oracle, the
literal expectations, and the checks every family owes.

A helper, not a test module (the `tests/observation_support.py` precedent). Each of
`tests/test_cdm_stanag4559_catalog_adapter.py`, `..._stream_...` and `..._workflow_...` calls these
for its own family, so a rule is written once and asserted three times; the record-level rules of
`synapse_cdm.isr_record` that do not depend on the family are tested once, in the catalog module.

THE ORACLE, AND WHAT IS NOT ONE
-------------------------------
The expectations here come from outside the code under test:

- the specification bundle's nine records and nine expected Events, carried
  verbatim under `tests/stanag4559_bundle/` (`BUNDLE`): the Events were written by the bundle's
  authors, and the tests compare bytes with them;
- the literal tables below (`BUNDLE_IDENTITY`, `AUTHORED`, `MALFORMED`), each value derived ONCE,
  outside this package, from the bundle's own rules: `object_key` and `revision_key` as the unpadded
  base64url of the compact JSON arrays section 7 names, the ids as `uuid5` in `ids.NAMESPACE` over
  `"<kind>|NSILI|<key>"` (the bundle's `validate_artifacts.py` formula), the semantic digests by the
  bundle's restricted canonicaliser and `shasum`. The bundle identities agree with the manifest,
  and a test holds the two together.

The packaged goldens (`fixtures/stanag4559_<family>/golden/*.cdm.json`) were written by
`harness --update-golden` and are a REGRESSION record, not an oracle: every field a test relies on
is asserted against a literal of `AUTHORED`.
"""

from __future__ import annotations

import copy
import json
import pathlib

import pytest

import synapse_cdm
from synapse_cdm import canonical, isr_record, projection, times
from synapse_cdm.adapter import load_adapter

REPO = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = REPO / "tests" / "stanag4559_bundle"
FIXTURES = pathlib.Path(synapse_cdm.__file__).parent / "fixtures"
FAMILIES = ("catalog", "stream", "workflow")

#: The manifest clock of every bundle record.
BUNDLE_CLOCK = "2026-10-04T12:00:02.000Z"
#: `times.FROZEN_NOW` as the goldens render it.
FROZEN_TEXT = "2026-04-29T06:15:00.000Z"

#: The bundle's cases and the stem each authored payload carries.
CASES = {
    "basic": "basic",
    "missing-source-time": "missing_source_time",
    "unknown-extension": "unknown_extension",
}

#: (object_key, revision_key, record_id, event_id) of each BUNDLE record. object_key, record_id
#: and event_id are the bundle's fixture manifest's values, copied once by hand: the manifest
#: itself is NOT carried in this tree (see `manifest_entries`), so the translators' output is held
#: to these literals by `test_cdm_001_the_bundle_identities_are_the_literals`; revision_key is
#: derived from the record by section 7's rule.
BUNDLE_IDENTITY = {
    "catalog-basic": (
        "WyJ0ZXN0LXRlbmFudCIsInRlc3QtZG9tYWluIiwidGVzdC1vcmlnaW4tYSIsImNhdGFsb2ciLCJjYXRhbG9nLWJhc2ljIl0",
        "WyJXeUowWlhOMExYUmxibUZ1ZENJc0luUmxjM1F0Wkc5dFlXbHVJaXdpZEdWemRDMXZjbWxuYVc0dFlTSXNJbU5oZEdG"
        "c2IyY2lMQ0pqWVhSaGJHOW5MV0poYzJsaklsMCIsIjEiLCI5NGM1MDZhZTBlNjgyZjY1M2RkMWE2OTFkMjkyZjZiOTc5"
        "NzI1Mzg5N2QyNTg0MzkwZmJkMzE0NjkxMjY4NzE4Il0",
        "3dd267d7-b1eb-50ca-afa3-fc59453c23dd",
        "e5280f0f-7c5b-556c-b39d-116e3c9ec8df",
    ),
    "catalog-missing-source-time": (
        "WyJ0ZXN0LXRlbmFudCIsInRlc3QtZG9tYWluIiwidGVzdC1vcmlnaW4tYSIsImNhdGFsb2ciLCJjYXRhbG9nLW1pc3Npbmct"
        "c291cmNlLXRpbWUiXQ",
        "WyJXeUowWlhOMExYUmxibUZ1ZENJc0luUmxjM1F0Wkc5dFlXbHVJaXdpZEdWemRDMXZjbWxuYVc0dFlTSXNJbU5oZEdG"
        "c2IyY2lMQ0pqWVhSaGJHOW5MVzFwYzNOcGJtY3RjMjkxY21ObExYUnBiV1VpWFEiLCIxIiwiZGRhYTBlMzVjZmE3MmE5"
        "NWU3ZGJkODU5Yjc3OWQzMDEwNzI2ZDVjNDhlODAyNzAyNTUyYjk0MzIwNDc0YTk2MSJd",
        "505b1299-ef01-5856-8a5f-2334bd6a5c1e",
        "b49c4969-8ad6-50d7-bea2-12a9b430d3f4",
    ),
    "catalog-unknown-extension": (
        "WyJ0ZXN0LXRlbmFudCIsInRlc3QtZG9tYWluIiwidGVzdC1vcmlnaW4tYSIsImNhdGFsb2ciLCJjYXRhbG9nLXVua25vd24t"
        "ZXh0ZW5zaW9uIl0",
        "WyJXeUowWlhOMExYUmxibUZ1ZENJc0luUmxjM1F0Wkc5dFlXbHVJaXdpZEdWemRDMXZjbWxuYVc0dFlTSXNJbU5oZEdG"
        "c2IyY2lMQ0pqWVhSaGJHOW5MWFZ1YTI1dmQyNHRaWGgwWlc1emFXOXVJbDAiLCIxIiwiMjIxYzMxNGM4YTQwZGI1YTgw"
        "OGU0MzhkYzJiNWIzMGVhZGU4ZWY3Mzc4NjFmY2QxMjdjOGMwMzUwOWU1OTJjZCJd",
        "3dec8982-c535-5a9b-a3c1-8373bfeed8a9",
        "247988e6-ec12-54a9-b379-f622f4d82417",
    ),
    "stream-basic": (
        "WyJ0ZXN0LXRlbmFudCIsInRlc3QtZG9tYWluIiwidGVzdC1vcmlnaW4tYSIsInN0cmVhbSIsInN0cmVhbS1iYXNpYyJd",
        "WyJXeUowWlhOMExYUmxibUZ1ZENJc0luUmxjM1F0Wkc5dFlXbHVJaXdpZEdWemRDMXZjbWxuYVc0dFlTSXNJbk4wY21W"
        "aGJTSXNJbk4wY21WaGJTMWlZWE5wWXlKZCIsIjEiLCJmYjJhYTZjMTljMjk1NjA4ODgzMjA4MzJkMWQwNmFmZjhmNjAz"
        "NDg1YjY3MmRhNWY5NWFjZTdkNmY3MDM3MmM3Il0",
        "feab8467-ad74-5004-b0c7-34a3da3eb004",
        "0ad58e4f-8827-57b1-956a-0febd133d1ed",
    ),
    "stream-missing-source-time": (
        "WyJ0ZXN0LXRlbmFudCIsInRlc3QtZG9tYWluIiwidGVzdC1vcmlnaW4tYSIsInN0cmVhbSIsInN0cmVhbS1taXNzaW5nLXNv"
        "dXJjZS10aW1lIl0",
        "WyJXeUowWlhOMExYUmxibUZ1ZENJc0luUmxjM1F0Wkc5dFlXbHVJaXdpZEdWemRDMXZjbWxuYVc0dFlTSXNJbk4wY21W"
        "aGJTSXNJbk4wY21WaGJTMXRhWE56YVc1bkxYTnZkWEpqWlMxMGFXMWxJbDAiLCIxIiwiOTQxNjI3MTMxNjM0Y2UxNmEx"
        "ZmY0Y2FkYmJmMTkzNzgzMjhkNzM4YTgwM2FkM2M2NTQ0MTI0OWJmOGI4OWMzYiJd",
        "dba3a001-0626-5e55-9047-88c807f09ba0",
        "4a7e3145-8642-551c-920f-e57ac38458ef",
    ),
    "stream-unknown-extension": (
        "WyJ0ZXN0LXRlbmFudCIsInRlc3QtZG9tYWluIiwidGVzdC1vcmlnaW4tYSIsInN0cmVhbSIsInN0cmVhbS11bmtub3duLWV4"
        "dGVuc2lvbiJd",
        "WyJXeUowWlhOMExYUmxibUZ1ZENJc0luUmxjM1F0Wkc5dFlXbHVJaXdpZEdWemRDMXZjbWxuYVc0dFlTSXNJbk4wY21W"
        "aGJTSXNJbk4wY21WaGJTMTFibXR1YjNkdUxXVjRkR1Z1YzJsdmJpSmQiLCIxIiwiMjg2ZTQ4ZTc2YWZjNDc0ZDM0MmY5"
        "N2FmMjcwMWIwMDZhNzMzMTBkNGMyNjNmMjhjMTU1MjFhMDNkZmQ3NTRkMyJd",
        "11dfa316-156b-5427-8cf2-6b435c274e92",
        "5b7f423b-1a51-5593-b84c-88796b101273",
    ),
    "workflow-basic": (
        "WyJ0ZXN0LXRlbmFudCIsInRlc3QtZG9tYWluIiwidGVzdC1vcmlnaW4tYSIsIndvcmtmbG93Iiwid29ya2Zsb3ctYmFzaWMi"
        "XQ",
        "WyJXeUowWlhOMExYUmxibUZ1ZENJc0luUmxjM1F0Wkc5dFlXbHVJaXdpZEdWemRDMXZjbWxuYVc0dFlTSXNJbmR2Y210"
        "bWJHOTNJaXdpZDI5eWEyWnNiM2N0WW1GemFXTWlYUSIsIjEiLCI2NjdlYjQ0MWMzN2NlMzk5MDNkYjY2MjlhYzUwY2Ix"
        "YzhjNmI3OTYyMDIyNzMyOTU1MjUyZGZmNDRkNDU4ZjA4Il0",
        "8c70506b-8561-58ae-86b8-3de2947a10db",
        "7e2bb539-a761-566a-a04d-189df59ac132",
    ),
    "workflow-missing-source-time": (
        "WyJ0ZXN0LXRlbmFudCIsInRlc3QtZG9tYWluIiwidGVzdC1vcmlnaW4tYSIsIndvcmtmbG93Iiwid29ya2Zsb3ctbWlzc2lu"
        "Zy1zb3VyY2UtdGltZSJd",
        "WyJXeUowWlhOMExYUmxibUZ1ZENJc0luUmxjM1F0Wkc5dFlXbHVJaXdpZEdWemRDMXZjbWxuYVc0dFlTSXNJbmR2Y210"
        "bWJHOTNJaXdpZDI5eWEyWnNiM2N0YldsemMybHVaeTF6YjNWeVkyVXRkR2x0WlNKZCIsIjEiLCIzOWMxZWYxZWYzMjJk"
        "ZjE5Y2MyMWUxYWE5YWRjZjYyMWEwOTZhNzMxZWM3MjQ1ZWEwZDRiZGE5ZjJkNGRhMDI3Il0",
        "afd13a22-b3f1-5156-887c-5d6b3bf760dc",
        "ad49e04b-badf-5c20-8e1f-29d5f04f70e0",
    ),
    "workflow-unknown-extension": (
        "WyJ0ZXN0LXRlbmFudCIsInRlc3QtZG9tYWluIiwidGVzdC1vcmlnaW4tYSIsIndvcmtmbG93Iiwid29ya2Zsb3ctdW5rbm93"
        "bi1leHRlbnNpb24iXQ",
        "WyJXeUowWlhOMExYUmxibUZ1ZENJc0luUmxjM1F0Wkc5dFlXbHVJaXdpZEdWemRDMXZjbWxuYVc0dFlTSXNJbmR2Y210"
        "bWJHOTNJaXdpZDI5eWEyWnNiM2N0ZFc1cmJtOTNiaTFsZUhSbGJuTnBiMjRpWFEiLCIxIiwiMmJiYzQ3OGU1OWVkYTBk"
        "NDc5YjJlZmY4YjdmYzA1YTkwMWE2NjA1Mjc0MDQ3NDgwZTBlNzFmNWUxMTYyNDExYSJd",
        "9596150c-49e7-59c2-b661-7728113789da",
        "5cfda2cc-a932-5779-92a1-fb4f00149971",
    ),
}

#: The AUTHORED payloads (the packaged fixtures): per family and stem, the recomputed semantic
#: digest, the identity, the copied raw digest, `observed_at` and the time basis. object_key and
#: record_id are the bundle record's (the identity components are unchanged); revision_key and
#: event_id follow the new digest. The workflow payloads are the bundle's records, byte for byte.
_A = "WyJXeUowWlhOMExYUmxibUZ1ZENJc0luUmxjM1F0Wkc5dFlXbHVJaXdpZEdWemRDMXZjbWxuYVc0dFlTSXNJ"
AUTHORED = {
    "catalog": {
        "basic": dict(
            semantic="fa599b1c81963aa8aa64ab812a87be1dd1f987f7d6cc9a9f75c7b96353f133c1",
            revision_key=_A
            + "bU5oZEdGc2IyY2lMQ0pqWVhSaGJHOW5MV0poYzJsaklsMCIsIjEiLCJmYTU5OWIxYzgxOTYzYWE4YWE2"
            "NGFiODEyYTg3YmUxZGQxZjk4N2Y3ZDZjYzlhOWY3NWM3Yjk2MzUzZjEzM2MxIl0",
            event_id="ffa735d7-89e5-5f8d-81b8-e0d9a4171856",
            raw="6b44ab5bb12c5eeb7c3c2fff1b2f8a813b184267f0a02af152b52b73f553f417",
            observed_at="2026-10-04T12:00:00.000Z",
            basis="SOURCE",
        ),
        "missing_source_time": dict(
            semantic="3e35dec0eb3ce3ecf88f49d3b61fb49257a82dc56a7242e23348ad8f3e4a13d3",
            revision_key=_A
            + "bU5oZEdGc2IyY2lMQ0pqWVhSaGJHOW5MVzFwYzNOcGJtY3RjMjkxY21ObExYUnBiV1VpWFEiLCIxIiwi"
            "M2UzNWRlYzBlYjNjZTNlY2Y4OGY0OWQzYjYxZmI0OTI1N2E4MmRjNTZhNzI0MmUyMzM0OGFkOGYzZTRhMTNkMyJd",
            event_id="da3b5c72-52cc-5ec1-b8f2-056d259e73ec",
            raw="836c7a3946a830c38ce368fe48b844f94eb4d3081ef65a7e9fa3ea6e74954660",
            observed_at="2026-10-04T12:00:01.000Z",
            basis="GATEWAY_RECEIPT",
        ),
        "unknown_extension": dict(
            semantic="7f1fd408c43b4c8f9243596fc1d16db2b25bbf863e00ccefcaf5289a44ba88f7",
            revision_key=_A
            + "bU5oZEdGc2IyY2lMQ0pqWVhSaGJHOW5MWFZ1YTI1dmQyNHRaWGgwWlc1emFXOXVJbDAiLCIxIiwiN2Yx"
            "ZmQ0MDhjNDNiNGM4ZjkyNDM1OTZmYzFkMTZkYjJiMjViYmY4NjNlMDBjY2VmY2FmNTI4OWE0NGJhODhmNyJd",
            event_id="14903a84-25bd-5dbe-8597-5408bc22d306",
            raw="45036806c3d12b1dc97403508341d5b9e5abdc618a22375c0772a0e0936ecf6f",
            observed_at="2026-10-04T12:00:00.000Z",
            basis="SOURCE",
        ),
    },
    "stream": {
        "basic": dict(
            semantic="927ce05c01de2defd0133b2b0703bf775a609e3b9beb46d6031b3a67b8d5488b",
            revision_key=_A
            + "bk4wY21WaGJTSXNJbk4wY21WaGJTMWlZWE5wWXlKZCIsIjEiLCI5MjdjZTA1YzAxZGUyZGVmZDAxMzNi"
            "MmIwNzAzYmY3NzVhNjA5ZTNiOWJlYjQ2ZDYwMzFiM2E2N2I4ZDU0ODhiIl0",
            event_id="9072d7eb-cb8b-5dac-91a0-8f7778d9d91e",
            raw="833e9c67f3016064b1357d9997f27eeb2c5d752e7573d8e324ba79eccc149ec5",
            observed_at="2026-10-04T12:00:00.000Z",
            basis="SOURCE",
        ),
        "missing_source_time": dict(
            semantic="7bab24daf19e0495cbf475711a89be823612e82d46e7b2aca1785a9a76771282",
            revision_key=_A
            + "bk4wY21WaGJTSXNJbk4wY21WaGJTMXRhWE56YVc1bkxYTnZkWEpqWlMxMGFXMWxJbDAiLCIxIiwiN2Jh"
            "YjI0ZGFmMTllMDQ5NWNiZjQ3NTcxMWE4OWJlODIzNjEyZTgyZDQ2ZTdiMmFjYTE3ODVhOWE3Njc3MTI4MiJd",
            event_id="b2e641b0-c7eb-5694-8bd2-2ce2618064f2",
            raw="a16e4c35cf7ad4e09d136a1820d055e338bbec3a4c5948af3545f6ad57422443",
            observed_at="2026-10-04T12:00:01.000Z",
            basis="GATEWAY_RECEIPT",
        ),
        "unknown_extension": dict(
            semantic="90f1c2431b0d766ccb919a7a94b14f50721d3e8ef97b6be573d17cce46b69bbd",
            revision_key=_A
            + "bk4wY21WaGJTSXNJbk4wY21WaGJTMTFibXR1YjNkdUxXVjRkR1Z1YzJsdmJpSmQiLCIxIiwiOTBmMWMy"
            "NDMxYjBkNzY2Y2NiOTE5YTdhOTRiMTRmNTA3MjFkM2U4ZWY5N2I2YmU1NzNkMTdjY2U0NmI2OWJiZCJd",
            event_id="d95e47a2-cf75-57ea-91e4-f4ff4b3435e3",
            raw="399ba3b3948e38b686a7d6e14a67ff1cf1e0686ec0a46c6a06c2eded04c90d96",
            observed_at="2026-10-04T12:00:00.000Z",
            basis="SOURCE",
        ),
    },
    "workflow": {
        "basic": dict(
            semantic="667eb441c37ce39903db6629ac50cb1c8c6b7962022732955252dff44d458f08",
            revision_key=BUNDLE_IDENTITY["workflow-basic"][1],
            event_id="7e2bb539-a761-566a-a04d-189df59ac132",
            raw="3747f6bd0521759c8900605859d2d84caa0c2217015ff08af6f6731a5f8767b3",
            observed_at="2026-10-04T12:00:00.000Z",
            basis="SOURCE",
        ),
        "missing_source_time": dict(
            semantic="39c1ef1ef322df19cc21e1aa9adcf621a096a731ec7245ea0d4bda9f2d4da027",
            revision_key=BUNDLE_IDENTITY["workflow-missing-source-time"][1],
            event_id="ad49e04b-badf-5c20-8e1f-29d5f04f70e0",
            raw="69e82f7b9debb6d4549934e68e984265c27cd5687e1be5feb0b1ad3bb2654b08",
            observed_at="2026-10-04T12:00:01.000Z",
            basis="GATEWAY_RECEIPT",
        ),
        "unknown_extension": dict(
            semantic="2bbc478e59eda0d479b2eff8b7fc05a901a6605274047480e0e71f5e1162411a",
            revision_key=BUNDLE_IDENTITY["workflow-unknown-extension"][1],
            event_id="5cfda2cc-a932-5779-92a1-fb4f00149971",
            raw="f272a9ff1e78472246f1350859c0f4d8d52433fc53cf10a5423886c83de4b470",
            observed_at="2026-10-04T12:00:00.000Z",
            basis="SOURCE",
        ),
    },
}

#: The moved footprint every catalogue and stream payload states, as the Event's geometry renders
#: it (floats) and as the record keeps it (integers).
MOVED_RING = [[21, 57], [22, 57], [22, 58], [21, 58], [21, 57]]
MOVED_GEOMETRY = {"type": "Polygon", "coordinates": [[[float(x), float(y)] for x, y in MOVED_RING]]}

#: Every file of each family's `malformed/` and what refuses it: an `isr_record` code, or the base
#: class's depth bound (`InputTooDeep`). The workflow body has no source interval.
MALFORMED = {
    "byte_order_mark.isr": "byte-order-mark",
    "depth_over_cap.isr": "InputTooDeep",
    "duplicate_key.isr": "duplicate-key",
    "graph_edge_to_no_node.json": "graph-dangling-edge",
    "impossible_date.json": "impossible-instant",
    "kind_of_another_family.json": "kind-family-mismatch",
    "local_library_scope_foreign_authority.json": "local-library-authority",
    "lone_surrogate.isr": "lone-surrogate",
    "missing_captured_at.json": "missing-field",
    "nan_value.isr": "non-finite-number",
    "polygon_latitude_out_of_range.json": "schema-violation",
    "ring_self_intersects.json": "ring-self-intersects",
    "semantic_digest_upper_case.json": "schema-violation",
    "size_bytes_not_an_integer.json": "schema-violation",
    "temporal_start_after_end.json": "interval-reversed",
    "unknown_top_level_key.json": "unknown-key",
}


def malformed_names(family: str) -> list[str]:
    return sorted(
        n for n in MALFORMED if family != "workflow" or n != "temporal_start_after_end.json"
    )


def placeholder_problems(record: dict) -> list[str]:
    """CONTRIBUTING.md's rule for SC ISR gateway record fixtures: the bundle's `test-` identifiers
    and `TEST_ONLY` labels under `SYNTHETIC_TEST`, nothing that could name a real deployment."""
    problems = []
    for path in (
        ("tenant_id",),
        ("security_domain",),
        ("connector_id",),
        ("library_id",),
        ("origin", "authority"),
    ):
        value = record[path[0]] if len(path) == 1 else record[path[0]][path[1]]
        if not value.startswith("test-"):
            problems.append(f"/{'/'.join(path)} is not a test- placeholder")
    for which in ("metadata", "content"):
        label = record["security"][which]
        if (label["classification"], label["scheme"]) != ("TEST_ONLY", "SYNTHETIC_TEST"):
            problems.append(f"/security/{which} is not the TEST_ONLY / SYNTHETIC_TEST label")
    return problems


# -- reading --------------------------------------------------------------------------------------


#: SHA-256 of the bundle's `examples/fixture-manifest.json`, as its `SHA256SUMS.json` records it.
#: The file is NOT carried under `tests/stanag4559_bundle/`: its nine `object_key` values are
#: base64url strings beside a field named `key`, which the repository's secret scanner (gitleaks,
#: rule `generic-api-key`) flags, and `.gitleaks.toml` admits no allowlist by policy. Its content is
#: the literals of this module (`BUNDLE_CLOCK`, `BUNDLE_IDENTITY`) and `manifest_entries` below.
BUNDLE_MANIFEST_SHA256 = "3d2a0666e7a396cc01c2059e2f0e309dadb225d33503a9e766a97e6b181a21a2"


def manifest_entries(family: str) -> list[dict]:
    """The bundle manifest's entries of one family, in the manifest's own shape and order, built
    from the literals above (the manifest file is not carried; `BUNDLE_MANIFEST_SHA256`)."""
    entries = []
    for case in CASES:
        name = f"{family}-{case}"
        object_key, _, record_id, event_id = BUNDLE_IDENTITY[name]
        entries.append(
            {
                "name": name,
                "input": f"{name}.record.json",
                "expected": f"{name}.expected-cdm.json",
                "clock": BUNDLE_CLOCK,
                "object_key": object_key,
                "record_id": record_id,
                "event_id": event_id,
                "native_wire_validated": False,
                "synthetic": True,
            }
        )
    return entries


def bundle_record(family: str, case: str) -> dict:
    return json.loads((BUNDLE / f"{family}-{case}.record.json").read_text(encoding="utf-8"))


def fixture_dir(family: str) -> pathlib.Path:
    return FIXTURES / f"stanag4559_{family}"


def authored_record(family: str, stem: str) -> dict:
    return json.loads((fixture_dir(family) / f"{stem}.json").read_text(encoding="utf-8"))


def adapter(family: str, clock: str = BUNDLE_CLOCK, synthetic: bool = True):
    cls = load_adapter(f"stanag4559_{family}")
    return cls(clock=times.frozen_clock(times.parse(clock)), synthetic=synthetic)


def translate(record, family: str | None = None, **kw) -> dict:
    """The one Event's JSON dump; asserts the translation yields exactly one Event."""
    family = family or record["family"]
    objects = adapter(family, **kw).to_cdm(record)
    assert len(objects) == 1 and objects[0].object_kind == "event", objects
    return objects[0].model_dump(mode="json")


def render_as_bundle(event) -> bytes:
    """An Event of this package in the bundle's form: projected to the frozen CDM 3.0.0 contract
    the bundle was written against (`projection.dump_for`, which removes the 3.2.0 `validity`
    member when it is null and refuses it when it is not) and stamped 3.0.0, the stamp section 9
    gives as "Repository SCHEMA_VERSION, initially 3.0.0"; then rendered as the harness renders."""
    assert event.schema_version == "3.2.0", event.schema_version
    dumped = projection.dump_for(event, "3.0.0")
    dumped["schema_version"] = "3.0.0"
    return canonical.serialise([dumped]).encode("utf-8")


def refusal(call, *args) -> str:
    """The code (or bound class name) that refuses `call(*args)`; fails if nothing does."""
    try:
        call(*args)
    except isr_record.IsrRecordRefused as refused:
        return refused.code
    except ValueError as refused:
        return type(refused).__name__
    pytest.fail(f"{call} accepted what it must refuse")


def refuse_record(record, family: str | None = None) -> str:
    family = family or (record.get("family") if isinstance(record, dict) else None) or "catalog"
    return refusal(adapter(family).to_cdm, record)


def mutated(record: dict, mutate) -> dict:
    out = copy.deepcopy(record)
    mutate(out)
    return out


def graph_of(record: dict) -> dict:
    body = record["body"]
    return body["artifact"]["graph"] if record["family"] == "workflow" else body["graph"]


# -- values the schema has not judged yet -------------------------------------------------------

#: JSON values that are not strings, two of them unhashable containers: what `family` or `kind`
#: can hold when the steps that run before the schema pass read them (the review of 2026-10-24
#: found a list or an object `family` escaping the translators as `TypeError`).
UNJUDGED = ([], {}, [1], {"a": 1})

#: One value of every JSON shape, and three of the shapes the contract itself uses (a timestamp and
#: the two geometries): the table each single-field substitution draws from.
SUBSTITUTES = (
    None,
    [],
    {},
    0,
    -1,
    "",
    "x",
    True,
    1.5,
    [[]],
    {"a": 1},
    [None],
    [1],
    10**30,
    "2026-10-04T12:00:00.000Z",
    {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
    {"type": "MultiPolygon", "coordinates": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]]},
)
_DELETE = object()


def _paths(value, where: tuple = ()):
    yield where
    if type(value) is dict:
        for key, sub in value.items():
            yield from _paths(sub, (*where, key))
    elif type(value) is list:
        for index, sub in enumerate(value):
            yield from _paths(sub, (*where, index))


def single_field_substitutions(record: dict):
    """Every record that differs from `record` at exactly one path: the member there replaced by
    each of `SUBSTITUTES`, or, for an object member, deleted. Yields `(label, record)`."""
    for where in _paths(record):
        if not where:
            continue
        pointer = "/" + "/".join(str(part) for part in where)
        for value in (*SUBSTITUTES, _DELETE):
            out = copy.deepcopy(record)
            parent = out
            for key in where[:-1]:
                parent = parent[key]
            if value is _DELETE:
                if type(parent) is not dict:
                    continue
                del parent[where[-1]]
                yield f"{pointer} deleted", out
            else:
                parent[where[-1]] = copy.deepcopy(value)
                yield f"{pointer} = {json.dumps(value)}", out


def untyped_outcomes(family: str, record: dict) -> tuple[int, list[str]]:
    """Each single-field substitution of `record`, as a parsed object and as octets, through the
    family's translator. Returns how many inputs were tried and the labels of those that neither
    translated to exactly one Event nor were refused with `isr_record.IsrRecordRefused`."""
    translator = adapter(family)
    tried, problems = 0, []
    for label, mutant in single_field_substitutions(record):
        for form, raw in (("object", mutant), ("octets", json.dumps(mutant).encode("utf-8"))):
            tried += 1
            try:
                objects = translator.to_cdm(raw)
            except isr_record.IsrRecordRefused:
                continue
            except Exception as error:  # what this helper exists to find, reported by class
                problems.append(f"{label} ({form}): {type(error).__name__}")
                continue
            if len(objects) != 1 or objects[0].object_kind != "event":
                problems.append(f"{label} ({form}): {len(objects)} objects")
    return tried, problems


# -- RFC 8785, written from the RFC's sentences and from nothing else ------------------------------


def jcs_string(text: str) -> str:
    """RFC 8785 section 3.2.2.2: the two-character escapes for backspace, tab, line feed, form
    feed, carriage return, quote and backslash; `\\u` and four lower-case hex digits for the other
    controls below U+0020; every other code point as itself. A lone surrogate is an error."""
    out = ['"']
    for ch in text:
        cp = ord(ch)
        if 0xD800 <= cp <= 0xDFFF:
            raise ValueError("lone surrogate")
        named = {
            0x08: "\\b",
            0x09: "\\t",
            0x0A: "\\n",
            0x0C: "\\f",
            0x0D: "\\r",
            0x22: '\\"',
            0x5C: "\\\\",
        }
        if cp in named:
            out.append(named[cp])
        elif cp < 0x20:
            out.append("\\u%04x" % cp)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def jcs_array(items) -> str:
    return "[" + ",".join("null" if item is None else jcs_string(item) for item in items) + "]"
