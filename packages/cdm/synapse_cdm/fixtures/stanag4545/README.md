# stanag4545 fixtures

**Every file here is synthetic.** The 17 `.ntf` files outside `vectors/` are the SC4545-CORE-1
engineering vectors of the SC-4545-ENG-1.0 handoff kit, contributed by the maintainer and tracked
byte-identical to the kit; `spec/build_fixtures.py` is a port of the kit's generator and reproduces
each of them byte for byte. The `native_*.ntf` files under `vectors/` were authored for this
repository by the same script. Every security block any of them carries is marked unclassified
(CLAS `U`, every other security field blank), no value names a real place, sensor, platform,
mission or product, and none of them is an official NSIF test file or independent evidence of
anything.

Edit the script and run `python -I -B spec/build_fixtures.py`; `--check` prints `CURRENT` when the
tree matches it and writes nothing. Never edit a fixture by hand.

`stanag4545` is #38 in `FORMAT_COVERAGE.md`'s ordinal table, and these are the fixtures of the
adapter that registers under that name.

## Layout

| Path | What it holds |
|---|---|
| top level | the eleven vectors the adapter translates under its default context, each beside its parsed twin `<stem>.parsed.json`: `mono_nsif101`, `mono_nsif100` and `mono_nitf210` (the three signatures), `geo_dms` (direct DMS corners), `unknown_duplicate_tre` (two TREs with one unknown tag), `mode_B`, `mode_P`, `mode_R` and `mode_S` (the four interleave modes on a 2x2 block grid, three bands), `uint16` (16-bit samples) and `image_and_text` (an image and a text segment) |
| `malformed/` | the five vectors the adapter refuses: `bad_file_length`, `truncated` and `trailing` (FL against the input length), `bad_count` (a letter in NUMI) and `unsupported_stype` (STYPE not `BF01`); no twins |
| `golden/` | `<stem>.cdm.json` and `<stem>.parsed.cdm.json` for each top-level vector: what the adapter writes under its default context and the harness's frozen clock, written only by `--update-golden` and reviewed; a twin's golden is byte-identical to its vector's |
| `context/` | `header_only` and its twin: a valid container with no segment, which translates only with an explicit product key, so it is not replayed under the default context |
| `context/golden/` | the two goldens of `header_only`, written through the exercise-context wrapper below |
| `vectors/` | the native NC vectors the decoder is tested on, `native_<label>.ntf`, one image each: the asymmetric literal vector and edge-block vectors in all four interleave modes, zero and padded block sizes, the fifteen signed, justified and fill-bit cases, nine, ten and 256 bands, a three-table LUT and four axis-aligned rectangles with G and D corners; no twins, and the harness never replays them |
| `independent/` | GDAL's own reading of every image-bearing vector (`<stem>.gdal.json`: the storage integers band-major, and the colour table or geotransform and corners where GDAL reports one) and `gdal_reading.json`, the record of the version, commands and environment it was taken with |
| `spec/` | `build_fixtures.py`, the only thing that writes the `.ntf` and `.parsed.json` files above |

A parsed twin is the closed envelope `{"profile": "SC4545-CORE-1", "wire_b64": ...}` holding the
same octets as canonical base64. It proves that the octets are retained and reach the same parser;
it is a wire envelope, not a decoded form, and it carries nothing the `.ntf` does not.

The kit's `expected.json` outcome `ok` is a parse-level outcome: the container parses and validates
with no violation. Translation additionally needs a product identity: the eleven top-level vectors
carry the source fields the identity falls back to (a nonblank OSTAID, a valid FDT and a nonblank
IID1 for each image), while `header_only` has no image and so needs an explicit product key. The
kit's digests and expected outcomes are
held as literals in `tests/test_cdm_nsif_codec.py` and `tests/test_cdm_stanag4545_adapter.py`, which
also load the builder in memory and require every file it owns to equal the tracked one.

`python -m synapse_cdm.harness --adapter stanag4545` replays the twenty-two top-level files under
the default context, from an installed distribution as from a clone; it never reads `context/`.
The context goldens are replayed from a clone's root through `ExerciseContextAdapter`, an abstract
wrapper in `tests/test_cdm_stanag4545_adapter.py` that overrides only the packaged-fixture hook with
an exercise product key, asset reference and digest: `python -m synapse_cdm.harness --adapter
tests.test_cdm_stanag4545_adapter:ExerciseContextAdapter --fixtures <this directory>/context`, with
`--update-golden` only to regenerate them. Being abstract and outside the package, the wrapper is
never registered and skips the class-definition checks by design; the shipped class keeps the
default hook, so `--fixtures` stays open for it.

`geo_dms.ntf` is the kit's vector, kept byte-identical, and its four corners lie outside the
Baltic rectangle CONTRIBUTING.md asks of new fixtures; every vector this repository authored for
the adapter lies inside it. Footprints at the poles, across the antimeridian or with out-of-range
corners are built in memory by the tests and never written here.

The readings under `independent/` are GDAL's and are not written by the builder: they are re-taken
from a clone where GDAL's command-line tools are installed, with `python gates/nsif_gdal_reading.py
--check` to compare (it writes nothing) and `--date YYYY-MM-DD` to rewrite them. They are storage
integers and corner numbers only, from an unpinned build, and no oracle for headers, security
labels, refused vectors or seam splits. `tests/test_cdm_nsif_codec.py` and
`tests/test_cdm_nsif_geometry.py` compare the decoder and the footprints with them and need no
GDAL.

Each directory's `PROVENANCE.json` lists every file in it as synthetic and `PUBLIC`.
