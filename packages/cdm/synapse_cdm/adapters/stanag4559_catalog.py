"""`stanag4559_catalog`, #35 in the ordinal table: the STANAG 4559 catalogue translator, SC ISR
gateway record -> CDM, ingest only.

WHAT A PAYLOAD IS
-----------------
One catalogue record (`family` `catalog`, `kind` `catalog.record`): a product's identity at
its issuing library, its revision, its change kind, the source and receipt clocks, the reference
to the raw capture, the metadata and content security labels, and the catalogue body of section 8
(`product_type`, `title`, `description`, `created_at`, `modified_at`, `temporal_start`,
`temporal_end`, `coverage`, `files`, `associations`, the typed `graph`, `source_time_lexical`,
`identity_scope`).
The record is this project's internal contract `urn:synapsecommand:isr:record:1` (SC ISR 4559 001,
revision 1.0 of 4 October 2026, section 6), handed over as its UTF-8 octets or as the parsed
object; it is not a NATO wire message.

WHAT ONE RECORD BECOMES
-----------------------
Exactly one `STATUS_CHANGE` `Event`, severity INFO, carrying the record verbatim under
`payload.record` beside `kind`, `record_id`, `revision_key` and `time_basis` (section 9; the rule
is `stanag4559_common.Stanag4559Adapter.translate`, shared by the three translators, and the
record's contract, transport rules, second pass and identity are `synapse_cdm.isr_record`).
`Event.geometry` is the body's `coverage` (a WGS84 Polygon or MultiPolygon, or null),
validated by section 28's polygon rules; a footprint is coverage only, never an Entity and never a
point at its centre (acceptance case CDM-007). The product, its thumbnail and its related files
are references in `body.files`; none is fetched (section 12 is the gateway's).

THE CAPABILITY REPORT
---------------------
Translated: the catalog family of the internal record, under section 8 (catalogue metadata and graph preservation) as far as the record
contract states it, and sections 6, 7, 9 and 28. NOT implemented, and not part of this
distribution: the stateful ISR gateway; every wire profile of section 3 (C17, S18, W19) is
UNIMPLEMENTED; no STANAG 4559 or AEDP-17/18/19 wire message is read, no NATO binding package is
held, no peer was exercised, and no NATO wire interoperability is claimed
(`nato_wire_compatibility_verified: false`). Binding `provisional-internal-profile`, claim
PROVISIONAL. The deviations from the specification — PROVISIONAL from the start, the capture
representation kept at `payload.record.raw_ref.representation` rather than in `source_hash`,
`time_basis` SOURCE taken from the goldens, no gateway or peer — are stated, with the rest of the
report, in `stanag4559_common`'s docstring.
"""

from __future__ import annotations

from synapse_cdm.adapters import stanag4559_common as common
from synapse_cdm.manifest import Limitation
from synapse_cdm.models import CDMBase


class Stanag4559CatalogAdapter(common.Stanag4559Adapter):
    """One SC ISR gateway record of the catalog family in, one STATUS_CHANGE Event out."""

    name = "stanag4559_catalog"
    version = "1.0.0"
    direction = "ingest"
    system = "NSILI"
    FAMILY = "catalog"

    metadata = common.metadata(
        "stanag4559_catalog",
        "SC ISR gateway record, catalog family (STANAG 4559 translation layer, provisional internal "
        "profile)",
        "catalog",
        "SC ISR gateway record (urn:synapsecommand:isr:record:1), family catalog: one "
        "catalogue record, as its UTF-8 octets or the parsed object, becomes one "
        "STATUS_CHANGE Event carrying the record verbatim",
        [
            Limitation(
                id="products-not-fetched",
                summary="body.files are references: no product, thumbnail or related file is "
                "fetched or opened, and no product transfer is made (section 12 is the gateway's)",
            ),
        ],
    )

    TRANSFORMS = common.transforms()
    MAPPINGS = common.mappings("catalog")

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        # Defined HERE, not inherited, so the base class's input bounds wrap it.
        return self.translate(raw)
