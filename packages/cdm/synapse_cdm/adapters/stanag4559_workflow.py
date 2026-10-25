"""`stanag4559_workflow`, #37 in the ordinal table: the STANAG 4559 workflow translator, SC ISR
gateway record -> CDM, ingest only.

WHAT A PAYLOAD IS
-----------------
One workflow record (`family` `workflow`, `kind` `workflow.record`): a workflow entity's
identity at its issuing authority, its revision, its change kind, the source and receipt clocks,
the reference to the raw capture, the two security labels, and the workflow body of section 14
(`service` — organization, requirement, priority, tasking, request or gaoi — `entity_type`,
`native_id`, `native_revision`, `native_state` verbatim, `source_changed_at`, `title`,
`owner_ref`, `references`, `geometry`, the typed `artifact` with its own `raw_ref`,
`source_time_lexical`, `identity_scope`).
The record is this project's internal contract `urn:synapsecommand:isr:record:1` (SC ISR 4559 001,
revision 1.0 of 4 October 2026, section 6), handed over as its UTF-8 octets or as the parsed
object; it is not a NATO wire message.

WHAT ONE RECORD BECOMES
-----------------------
Exactly one `STATUS_CHANGE` `Event`, severity INFO, carrying the record verbatim under
`payload.record` beside `kind`, `record_id`, `revision_key` and `time_basis` (section 9; the rule
is `stanag4559_common.Stanag4559Adapter.translate`, shared by the three translators, and the
record's contract, transport rules, second pass and identity are `synapse_cdm.isr_record`).
`Event.geometry` is the body's `geometry` when the record's service is `gaoi` and null for
every other service (section 9: "workflow GAOI geometry; otherwise null"), the geometry of any
service being validated by section 28's polygon rules and carried in `payload.record` either way.
`native_state` is the source's token, verbatim; no transition, tasking, publication or deletion is
made (section 14's mutations are the gateway's), and an Event is never an authorisation or a
command (section 5).

THE CAPABILITY REPORT
---------------------
Translated: the workflow family of the internal record, under section 14 (AEDP-19 workflow integration) as far as the record
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


class Stanag4559WorkflowAdapter(common.Stanag4559Adapter):
    """One SC ISR gateway record of the workflow family in, one STATUS_CHANGE Event out."""

    name = "stanag4559_workflow"
    version = "1.0.0"
    direction = "ingest"
    system = "NSILI"
    FAMILY = "workflow"

    metadata = common.metadata(
        "stanag4559_workflow",
        "SC ISR gateway record, workflow family (STANAG 4559 translation layer, provisional internal "
        "profile)",
        "workflow",
        "SC ISR gateway record (urn:synapsecommand:isr:record:1), family workflow: one "
        "workflow record, as its UTF-8 octets or the parsed object, becomes one "
        "STATUS_CHANGE Event carrying the record verbatim",
        [
            Limitation(
                id="workflow-geometry-gaoi-only",
                summary="Event.geometry is a workflow record's geometry only when its service is "
                "gaoi (section 9: 'workflow GAOI geometry; otherwise null'); the geometry of any "
                "other service is validated and carried in payload.record only",
            ),
            Limitation(
                id="workflow-read-only",
                summary="native_state is the source's token, verbatim: no transition, tasking, "
                "publication or deletion is made, and an Event is never an authorisation or a "
                "command (sections 5 and 14)",
            ),
        ],
    )

    TRANSFORMS = common.transforms()
    MAPPINGS = common.mappings("workflow")

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        # Defined HERE, not inherited, so the base class's input bounds wrap it.
        return self.translate(raw)
