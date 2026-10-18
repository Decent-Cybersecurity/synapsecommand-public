# Malformed cog payloads — every one synthetic, every one refused

These are **not fixtures**. Checks A–F never see them: the harness selects the immediate files of
`fixtures/cog/`, so a subdirectory is out of its reach by construction. They are read by the
conformance suite's check H, and by `tests/test_cdm_cog_adapter.py`, which holds each one to the
exact refusal below:

```bash
synapse conformance run --adapter cog --require H
```

Every one is built by `../spec/build_fixtures.py` — the TIFFs by the script's own small TIFF writer
from literal tags and blocks, the two VRTs from the script's `local_sources_index` with one thing
changed — with the one thing named below wrong with it. Each is refused with `CogRefused`, a
`ValueError` whose text begins with the code in the second column and names the structure, never a
value from the payload.

| Payload | Code | What is wrong with it |
|---|---|---|
| `bigtiff_header.tif` | `bigtiff` | the header's version is 43: a BigTIFF, which is not read |
| `truncated_ifd.tif` | `ifd-past-the-end` | a 2 x 2 image's file cut after the fifth of its twelve directory entries |
| `tile_offset_past_the_end.tif` | `block-past-the-end` | a 16 x 16 tiled image whose one tile offset is 1 MiB, past the end of the file |
| `jpeg_compression.tif` | `unsupported-compression` | Compression 7 (JPEG), refused by name |
| `unsupported_crs.tif` | `unsupported-crs` | ProjectedCRSGeoKey 3035 (ETRS89 / LAEA Europe), outside the closed set |
| `tile_inflates_past_its_size.tif` | `block-inflates-past-its-size` | one 512 x 512 Float32 tile, exactly the 1 MiB `max_decompressed_bytes`, whose 13 KB Deflate stream would inflate to 2 MiB of zeros; refused at the first octet past the tile |
| `tile_past_the_decompression_bound.tif` | `block-past-the-decompression-bound` | a 1024 x 1024 Float32 tile, 4 MiB decoded, past the 1 MiB bound; refused before anything is inflated |
| `ifd_loop.tif` | `ifd-loop` | the directory's next-directory offset points back at itself |
| `vsicurl_source.vrt` | `remote-source` | the second source is a `/vsicurl/` path to an `example.invalid` URL |
| `entity_declaration.vrt` | `vrt-dtd` | the index opens with a DOCTYPE that declares an entity; the XML guard refuses it before anything is read |
