#!/usr/bin/env python3
"""Demonstration 3 — a synthetic GeoPackage into CDM and out through the GeoJSON exchange profile.

    python examples/geopackage_to_geojson/run.py            # run and check; exit 0 on agreement
    python examples/geopackage_to_geojson/run.py --update   # rewrite expected/ from this run

One command, self-checking. It ingests the packaged fixture
`fixtures/geopackage/exercise_facilities_routes_areas.gpkg` (three layers — facilities, routes,
areas — with the primary keys 1, 2, 3 in EVERY layer, NULL attributes, a BLOB attribute and Z on
the facilities), exports the nine objects through `GeojsonAdapter(export="synapsecommand-exchange/1")`,
and compares both stages against expectations established INDEPENDENTLY of both adapters:

* geometry — in the exported document — against GDAL 3.13.3's own reading of the same package
  (`fixtures/geopackage/independent/*.geojson`, `*.ogrinfo.json`, written by
  `spec/build_fixtures.py` with `ogr2ogr -f GeoJSON` and `ogrinfo -json -features`);
* attributes — at the CDM stage, in each object's structured residual (`residual.data.row`),
  joined to its exported feature by `sc:object_id` — against GDAL's export `properties`. The
  GeoJSON adapter is untouched by this demonstration: its exchange profile carries what CDM
  types (geometry, kind, identifiers, provenance, as-of) and NOT another adapter's residual, so
  the document holds no GeoPackage attribute anywhere, promoted or otherwise, and the script
  checks that too;
* identity against a derivation this script performs itself from the namespace, the layer name
  and the primary key (`ids.derive`), and against the arithmetic that nine rows with three
  distinct primary keys must be nine distinct objects;
* provenance against the values the source declares — system, adapter, version, synthetic — and
  against the rule that no GeoPackage attribute may appear as a top-level GeoJSON property;
* the whole document against `expected/exercise_facilities_routes_areas.exchange.geojson`,
  byte for byte, so a change in either adapter's output is a visible diff.

This is CROSS-FORMAT TRANSLATION, not a byte-identical GeoPackage round trip: the GeoPackage
adapter is ingest only and nothing here writes a `.gpkg`. Every input is synthetic.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from synapse_cdm import ids, times
from synapse_cdm.adapter import packaged_fixtures
from synapse_cdm.adapters.geojson import EXPORT_EXCHANGE, GeojsonAdapter
from synapse_cdm.adapters.geopackage import GeopackageAdapter

HERE = pathlib.Path(__file__).resolve().parent
EXPECTED = HERE / "expected" / "exercise_facilities_routes_areas.exchange.geojson"
FIXTURE = "exercise_facilities_routes_areas.gpkg"
DATASET = "exercise-baltic"
LAYERS = ("areas", "facilities", "routes")


def independent(fixtures: pathlib.Path, layer: str) -> tuple[list[dict], list[int]]:
    """GDAL's GeoJSON export of one layer (features, fid as `id`) and its ogrinfo fid list."""
    stem = FIXTURE.removesuffix(".gpkg")
    geojson = json.loads((fixtures / "independent" / f"{stem}.{layer}.geojson").read_text())
    reading = json.loads((fixtures / "independent" / f"{stem}.{layer}.ogrinfo.json")
                         .read_text())
    return geojson["features"], [f["fid"] for f in reading["layers"][0]["features"]]


def flat(node) -> list[float]:
    out: list[float] = []
    pending = [node]
    while pending:
        current = pending.pop(0)
        if isinstance(current, list) and current and isinstance(current[0], list):
            pending = list(current) + pending
        else:
            out.extend(float(v) for v in current)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--update", action="store_true", help="rewrite expected/ from this run")
    args = parser.parse_args(argv)

    fixtures = packaged_fixtures(GeopackageAdapter)
    octets = (fixtures / FIXTURE).read_bytes()
    objects = GeopackageAdapter(clock=times.frozen_clock(), dataset=DATASET).to_cdm(octets)
    document = GeojsonAdapter(clock=times.frozen_clock(), export=EXPORT_EXCHANGE).from_cdm(objects)
    exported = json.loads(document)

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    features = exported["features"]
    check("document is a FeatureCollection under the exchange profile",
          exported.get("type") == "FeatureCollection" and exported.get("sc:profile") == EXPORT_EXCHANGE)
    check("nine features for nine rows", len(features) == 9, f"{len(features)} features")

    # The join between the two stages: each CDM object's residual (where the row's attributes
    # live) meets its exported feature on `sc:object_id`, the identity both stages carry.
    residuals = {str(obj.object_id): obj.residual for obj in objects}
    check("every exported feature is one CDM object, joined on sc:object_id",
          sorted(f["properties"]["sc:object_id"] for f in features) == sorted(residuals)
          and all(r is not None and r.namespace == "GeoPackage" for r in residuals.values()))
    check("the document carries no GeoPackage residual: the GeoJSON adapter emits only what CDM types",
          not any(k == "sc:residual" or k.startswith("sc:residual") for f in features
                  for k in f["properties"]))

    def row_of(feature: dict) -> dict:
        return residuals[feature["properties"]["sc:object_id"]].data["row"]

    by_layer: dict[str, list[dict]] = {layer: [] for layer in LAYERS}
    for feature in features:
        by_layer[row_of(feature)["layer"]].append(feature)

    geometry_agreements = attribute_agreements = 0
    for layer in LAYERS:
        gdal_features, gdal_fids = independent(fixtures, layer)
        mine = by_layer[layer]
        check(f"{layer}: GDAL and the export agree on the row count",
              len(mine) == len(gdal_features) == len(gdal_fids), f"{len(mine)} vs {len(gdal_features)}")
        for feature, gdal in zip(mine, gdal_features):
            row = row_of(feature)
            same_geometry = (feature["geometry"]["type"] == gdal["geometry"]["type"]
                             and flat(feature["geometry"]["coordinates"])
                             == flat(gdal["geometry"]["coordinates"]))
            geometry_agreements += same_geometry
            attributes = {k: (v["hex"] if isinstance(v, dict) and v.get("encoding") == "hex" else v)
                          for k, v in row["attributes"].items()}
            same_attributes = attributes == gdal["properties"]
            attribute_agreements += same_attributes
            check(f"{layer}/{row['pk']}: geometry equals GDAL's ({gdal['geometry']['type']})",
                  same_geometry)
            check(f"{layer}/{row['pk']}: CDM residual attributes equal GDAL's (NULLs kept, BLOB as hex)",
                  same_attributes, json.dumps(attributes, sort_keys=True))
            check(f"{layer}/{row['pk']}: the primary key is GDAL's fid and the exported external id",
                  row["pk"] == gdal["id"]
                  and feature["properties"]["sc:source_ids"][0]["external_id"] == f"{layer}/{gdal['id']}")
            check(f"{layer}/{row['pk']}: no attribute is promoted to a top-level property",
                  all(k.startswith("sc:") for k in feature["properties"]))
            props = feature["properties"]
            check(f"{layer}/{row['pk']}: identity derives from namespace, layer and primary key",
                  props["sc:object_id"] == str(ids.derive(f"GeoPackage:{DATASET}",
                                                          json.dumps([layer, row["pk"]]),
                                                          kind="feature"))
                  and props["sc:source_ids"] == [{"system": f"GeoPackage:{DATASET}",
                                                  "external_id": f"{layer}/{row['pk']}"}])
            check(f"{layer}/{row['pk']}: provenance names the source system, adapter and synthetic",
                  props["sc:source_system"] == "GeoPackage" and props["sc:source_adapter"] == "geopackage"
                  and props["sc:synthetic"] is True and props["sc:object_kind"] == "plan_object")

    object_ids = {f["properties"]["sc:object_id"] for f in features}
    primary_keys = {row_of(f)["pk"] for f in features}
    check("nine distinct identities from three distinct primary keys",
          len(object_ids) == 9 and primary_keys == {1, 2, 3}, f"{len(object_ids)} ids, keys {sorted(primary_keys)}")
    check("every CDM object carries the package inventory naming all three layers as included",
          all(r.data["package"]["inventory"]["included"] == list(LAYERS) for r in residuals.values()))
    check("the Z ordinate of every facility is carried as the third coordinate",
          all(len(f["geometry"]["coordinates"]) == 3 for f in by_layer["facilities"]))

    if args.update:
        EXPECTED.parent.mkdir(parents=True, exist_ok=True)
        EXPECTED.write_bytes(document)
        check("expected/ rewritten from this run", True, str(EXPECTED.relative_to(HERE.parent.parent)))
    else:
        check("the document equals expected/ byte for byte",
              EXPECTED.exists() and EXPECTED.read_bytes() == document,
              "run with --update after reviewing a deliberate change")

    failed = [c for c in checks if not c[1]]
    width = max(len(c[0]) for c in checks)
    print(f"GeoPackage -> CDM -> GeoJSON ({EXPORT_EXCHANGE}) — {FIXTURE}, dataset {DATASET!r}")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}".rstrip())
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks agree; geometry agreed on "
          f"{geometry_agreements}/9 rows, attributes on {attribute_agreements}/9 rows")
    print("RESULT: " + ("AGREES with the independent expectations" if not failed
                        else f"{len(failed)} DISAGREEMENT(S)"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
