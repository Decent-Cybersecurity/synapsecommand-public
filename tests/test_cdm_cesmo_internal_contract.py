"""`adapters/cesmo_internal_codec.py`: the SC CESMO Internal Exchange 1.0 contract's refusal table.

Every case is one fault in an otherwise valid kit example, asserted as its whole diagnostic
(`"<CODE> <path> <detail>"`), its code, its path and its record index, on the dict path and again
on the octet path wherever a dict can carry the fault — so the verdict is the same on both and,
the module running unchanged on Python 3.11, 3.12 and 3.14, on every interpreter (the cases where
the kit's `validate_contract.py` 1.0 differs by interpreter or from its own specification, hour
24, a trailing newline in a token, a non-ASCII digit, are here: DECISIONS C-06 and C-15). The
expectations are written from the kit's §8-§10, §14 and §19 and the rulings, never read back from
the codec.

PACKAGE-ONLY: the codec and the kit examples under `fixtures/cesmo_internal/`, through
`synapse_cdm.__file__`.
"""

from __future__ import annotations

import copy
import decimal
import enum
import json
import pathlib

import pytest
import synapse_cdm
from synapse_cdm.adapters import cesmo_internal_codec as codec
from synapse_cdm.adapters.cesmo_internal_codec import CesmoError

SET = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures" / "cesmo_internal"


def kit(name: str = "upsert.json") -> dict:
    return json.loads((SET / name).read_bytes())


def refusal(source, *, synthetic: bool | None = True) -> CesmoError:
    with pytest.raises(CesmoError) as raised:
        codec.validate(source, synthetic=synthetic)
    return raised.value


def rec(d: dict, i: int = 0) -> dict:
    return d["records"][i]


def eleven(d: dict) -> None:
    """Eleven upserts with distinct identifiers (for the numeric path order)."""
    d["records"] = [
        {**copy.deepcopy(rec(d)), "record_id": f"EOB-{i}", "object_id": f"EMITTER-{i}"}
        for i in range(11)
    ]


#: (id, the kit example, the one fault, code, path, detail). Every case runs on both paths.
CASES = [
    # -- tokens (kit L104): ECMA anchors, so a trailing newline is outside the alphabet
    (
        "token-network-newline",
        "upsert.json",
        lambda d: d["source"].update(network_id="TEST-NET\n"),
        "E_SCHEMA",
        "source/network_id",
        "pattern",
    ),
    (
        "token-originator-newline",
        "upsert.json",
        lambda d: d["source"].update(originator_id="TEST-SOURCE-A\n"),
        "E_SCHEMA",
        "source/originator_id",
        "pattern",
    ),
    (
        "token-epoch-newline",
        "upsert.json",
        lambda d: d["source"].update(identity_epoch="EXERCISE-1\n"),
        "E_SCHEMA",
        "source/identity_epoch",
        "pattern",
    ),
    (
        "token-message-newline",
        "upsert.json",
        lambda d: d.update(message_id="MSG-2\n"),
        "E_SCHEMA",
        "message_id",
        "pattern",
    ),
    (
        "token-record-newline",
        "upsert.json",
        lambda d: rec(d).update(record_id="EOB-1\n"),
        "E_SCHEMA",
        "records/0/record_id",
        "pattern",
    ),
    (
        "token-object-newline",
        "upsert.json",
        lambda d: rec(d).update(object_id="EMITTER-1\n"),
        "E_SCHEMA",
        "records/0/object_id",
        "pattern",
    ),
    (
        "token-sensor-newline",
        "observation.json",
        lambda d: rec(d)["signal"].update(sensor_id="SENSOR-1\n"),
        "E_SCHEMA",
        "records/0/signal/sensor_id",
        "pattern",
    ),
    (
        "token-snapshot-newline",
        "empty-complete-snapshot.json",
        lambda d: d["snapshot"].update(snapshot_id="SNAP-1\n"),
        "E_SCHEMA",
        "snapshot/snapshot_id",
        "pattern",
    ),
    (
        "token-65",
        "upsert.json",
        lambda d: d.update(message_id="M" * 65),
        "E_SCHEMA",
        "message_id",
        "pattern",
    ),
    (
        "token-empty",
        "upsert.json",
        lambda d: d.update(message_id=""),
        "E_SCHEMA",
        "message_id",
        "pattern",
    ),
    (
        "token-bar",
        "upsert.json",
        lambda d: d["source"].update(originator_id="a|b"),
        "E_SCHEMA",
        "source/originator_id",
        "pattern",
    ),
    (
        "token-non-ascii-letter",
        "upsert.json",
        lambda d: rec(d).update(object_id="EMITTER-é"),
        "E_SCHEMA",
        "records/0/object_id",
        "pattern",
    ),
    (
        "snapshot-as-record-id",
        "upsert.json",
        lambda d: rec(d).update(record_id="$snapshot"),
        "E_SCHEMA",
        "records/0/record_id",
        "pattern",
    ),
    (
        "snapshot-as-object-id",
        "upsert.json",
        lambda d: rec(d).update(object_id="$snapshot"),
        "E_SCHEMA",
        "records/0/object_id",
        "pattern",
    ),
    (
        "snapshot-as-message-id",
        "upsert.json",
        lambda d: d.update(message_id="$snapshot"),
        "E_SCHEMA",
        "message_id",
        "pattern",
    ),
    # -- timestamps (kit L108; DECISIONS C-06 b): the codec's own grammar and calendar
    (
        "hour-24-envelope",
        "upsert.json",
        lambda d: d.update(observed_at="2026-10-04T24:00:00Z"),
        "E_SCHEMA",
        "observed_at",
        "date-time",
    ),
    (
        "hour-24-record",
        "upsert.json",
        lambda d: rec(d).update(observed_at="2026-12-31T24:00:00Z"),
        "E_SCHEMA",
        "records/0/observed_at",
        "date-time",
    ),
    (
        "february-30",
        "upsert.json",
        lambda d: d.update(observed_at="2026-02-30T12:00:00Z"),
        "E_SCHEMA",
        "observed_at",
        "date-time",
    ),
    (
        "february-29-common-year",
        "upsert.json",
        lambda d: d.update(observed_at="2026-02-29T12:00:00Z"),
        "E_SCHEMA",
        "observed_at",
        "date-time",
    ),
    (
        "month-13",
        "upsert.json",
        lambda d: d.update(observed_at="2026-13-01T12:00:00Z"),
        "E_SCHEMA",
        "observed_at",
        "date-time",
    ),
    (
        "minute-60",
        "upsert.json",
        lambda d: d.update(observed_at="2026-10-04T12:60:00Z"),
        "E_SCHEMA",
        "observed_at",
        "date-time",
    ),
    (
        "second-60",
        "upsert.json",
        lambda d: rec(d).update(observed_at="2026-10-04T12:00:60Z"),
        "E_SCHEMA",
        "records/0/observed_at",
        "date-time",
    ),
    (
        "year-1969",
        "upsert.json",
        lambda d: d.update(observed_at="1969-12-31T23:59:59Z"),
        "E_SCHEMA",
        "observed_at",
        "date-time",
    ),
    (
        "seven-fraction-digits",
        "upsert.json",
        lambda d: d.update(observed_at="2026-10-04T12:00:00.1234567Z"),
        "E_SCHEMA",
        "observed_at",
        "date-time",
    ),
    (
        "lower-case-z",
        "upsert.json",
        lambda d: d.update(observed_at="2026-10-04T12:00:00z"),
        "E_SCHEMA",
        "observed_at",
        "date-time",
    ),
    (
        "offset",
        "upsert.json",
        lambda d: d.update(observed_at="2026-10-04T12:00:00+00:00"),
        "E_SCHEMA",
        "observed_at",
        "date-time",
    ),
    (
        "trailing-newline-time",
        "upsert.json",
        lambda d: d.update(observed_at="2026-10-04T12:00:00Z\n"),
        "E_SCHEMA",
        "observed_at",
        "date-time",
    ),
    (
        "arabic-indic-digit",
        "upsert.json",
        lambda d: d.update(observed_at="2026-10-0٤T12:00:00Z"),
        "E_SCHEMA",
        "observed_at",
        "date-time",
    ),
    (
        "fullwidth-digit",
        "upsert.json",
        lambda d: rec(d).update(observed_at="２026-10-04T12:00:00Z"),
        "E_SCHEMA",
        "records/0/observed_at",
        "date-time",
    ),
    (
        "time-not-a-string",
        "upsert.json",
        lambda d: d.update(observed_at=1759579200),
        "E_SCHEMA",
        "observed_at",
        "type",
    ),
    # -- the envelope and the discriminator (kit L102-L104; DECISIONS C-06 h)
    (
        "unknown-contract",
        "upsert.json",
        lambda d: d.update(contract="sc.cesmo.internal/2.0"),
        "E_UNSUPPORTED_MESSAGE",
        "contract",
        "not sc.cesmo.internal/1.0",
    ),
    (
        "contract-not-a-string",
        "upsert.json",
        lambda d: d.update(contract=1),
        "E_SCHEMA",
        "contract",
        "const",
    ),
    ("mode-upper-case", "upsert.json", lambda d: d.update(mode="LIVE"), "E_SCHEMA", "mode", "enum"),
    (
        "unknown-top-level-key",
        "upsert.json",
        lambda d: d.update(pretend_header=1),
        "E_SCHEMA",
        "",
        "additionalProperties",
    ),
    (
        "unknown-source-key",
        "upsert.json",
        lambda d: d["source"].update(relay="R-1"),
        "E_SCHEMA",
        "source",
        "additionalProperties",
    ),
    (
        "unknown-record-key",
        "upsert.json",
        lambda d: rec(d).update(operation="upsert"),
        "E_SCHEMA",
        "records/0",
        "additionalProperties",
    ),
    (
        "unknown-position-key",
        "upsert.json",
        lambda d: rec(d)["position"].update(msl_m=3),
        "E_SCHEMA",
        "records/0/position",
        "additionalProperties",
    ),
    (
        "unknown-signal-key",
        "upsert.json",
        lambda d: rec(d)["signal"].update(mode_s=3),
        "E_SCHEMA",
        "records/0/signal",
        "additionalProperties",
    ),
    (
        "unknown-ellipse-key",
        "upsert.json",
        lambda d: rec(d)["uncertainty"].update(covariance=[1]),
        "E_SCHEMA",
        "records/0/uncertainty",
        "additionalProperties",
    ),
    (
        "unknown-snapshot-key",
        "empty-complete-snapshot.json",
        lambda d: d["snapshot"].update(chunk=1),
        "E_SCHEMA",
        "snapshot",
        "additionalProperties",
    ),
    (
        "missing-contract",
        "upsert.json",
        lambda d: d.pop("contract"),
        "E_SCHEMA",
        "contract",
        "required",
    ),
    ("missing-mode", "upsert.json", lambda d: d.pop("mode"), "E_SCHEMA", "mode", "required"),
    ("missing-source", "upsert.json", lambda d: d.pop("source"), "E_SCHEMA", "source", "required"),
    (
        "missing-message-id",
        "upsert.json",
        lambda d: d.pop("message_id"),
        "E_SCHEMA",
        "message_id",
        "required",
    ),
    (
        "missing-observed-at",
        "upsert.json",
        lambda d: d.pop("observed_at"),
        "E_SCHEMA",
        "observed_at",
        "required",
    ),
    (
        "missing-records",
        "upsert.json",
        lambda d: d.pop("records"),
        "E_SCHEMA",
        "records",
        "required",
    ),
    (
        "missing-epoch",
        "upsert.json",
        lambda d: d["source"].pop("identity_epoch"),
        "E_SCHEMA",
        "source/identity_epoch",
        "required",
    ),
    (
        "missing-record-id",
        "upsert.json",
        lambda d: rec(d).pop("record_id"),
        "E_SCHEMA",
        "records/0/record_id",
        "required",
    ),
    (
        "missing-kind",
        "upsert.json",
        lambda d: rec(d).pop("kind"),
        "E_SCHEMA",
        "records/0/kind",
        "required",
    ),
    (
        "missing-revision",
        "upsert.json",
        lambda d: rec(d).pop("revision"),
        "E_SCHEMA",
        "records/0/revision",
        "required",
    ),
    (
        "missing-record-time",
        "upsert.json",
        lambda d: rec(d).pop("observed_at"),
        "E_SCHEMA",
        "records/0/observed_at",
        "required",
    ),
    (
        "missing-method",
        "upsert.json",
        lambda d: rec(d)["position"].pop("method"),
        "E_SCHEMA",
        "records/0/position/method",
        "required",
    ),
    (
        "missing-frame",
        "upsert.json",
        lambda d: rec(d)["uncertainty"].pop("frame"),
        "E_SCHEMA",
        "records/0/uncertainty/frame",
        "required",
    ),
    (
        "missing-snapshot-revision",
        "empty-complete-snapshot.json",
        lambda d: d["snapshot"].pop("revision"),
        "E_SCHEMA",
        "snapshot/revision",
        "required",
    ),
    (
        "records-not-a-list",
        "upsert.json",
        lambda d: d.update(records={}),
        "E_SCHEMA",
        "records",
        "type",
    ),
    (
        "record-not-an-object",
        "upsert.json",
        lambda d: d.update(records=[1]),
        "E_SCHEMA",
        "records/0",
        "type",
    ),
    # -- ranges and types (kit §9-§10, §8 L110; DECISIONS C-06 c, g)
    (
        "revision-float",
        "upsert.json",
        lambda d: rec(d).update(revision=4.0),
        "E_SCHEMA",
        "records/0/revision",
        "type",
    ),
    (
        "revision-boolean",
        "upsert.json",
        lambda d: rec(d).update(revision=True),
        "E_SCHEMA",
        "records/0/revision",
        "type",
    ),
    (
        "revision-negative",
        "upsert.json",
        lambda d: rec(d).update(revision=-1),
        "E_SCHEMA",
        "records/0/revision",
        "minimum",
    ),
    (
        "revision-2-to-the-53",
        "upsert.json",
        lambda d: rec(d).update(revision=2**53),
        "E_SCHEMA",
        "records/0/revision",
        "maximum",
    ),
    (
        "revision-as-text",
        "upsert.json",
        lambda d: rec(d).update(revision="4"),
        "E_SCHEMA",
        "records/0/revision",
        "type",
    ),
    (
        "snapshot-revision-float",
        "empty-complete-snapshot.json",
        lambda d: d["snapshot"].update(revision=6.0),
        "E_SCHEMA",
        "snapshot/revision",
        "type",
    ),
    (
        "complete-not-boolean",
        "empty-complete-snapshot.json",
        lambda d: d["snapshot"].update(complete=1),
        "E_SCHEMA",
        "snapshot/complete",
        "type",
    ),
    (
        "confidence-above-1",
        "upsert.json",
        lambda d: rec(d).update(confidence=1.1),
        "E_SCHEMA",
        "records/0/confidence",
        "maximum",
    ),
    (
        "confidence-below-0",
        "upsert.json",
        lambda d: rec(d).update(confidence=-0.1),
        "E_SCHEMA",
        "records/0/confidence",
        "minimum",
    ),
    (
        "confidence-boolean",
        "upsert.json",
        lambda d: rec(d).update(confidence=False),
        "E_SCHEMA",
        "records/0/confidence",
        "type",
    ),
    (
        "latitude-91",
        "upsert.json",
        lambda d: rec(d)["position"].update(latitude_deg=91),
        "E_SCHEMA",
        "records/0/position/latitude_deg",
        "maximum",
    ),
    (
        "latitude-minus-91",
        "upsert.json",
        lambda d: rec(d)["position"].update(latitude_deg=-91),
        "E_SCHEMA",
        "records/0/position/latitude_deg",
        "minimum",
    ),
    (
        "longitude-past-180",
        "upsert.json",
        lambda d: rec(d)["position"].update(longitude_deg=180.5),
        "E_SCHEMA",
        "records/0/position/longitude_deg",
        "maximum",
    ),
    (
        "longitude-minus-181",
        "upsert.json",
        lambda d: rec(d)["position"].update(longitude_deg=-181),
        "E_SCHEMA",
        "records/0/position/longitude_deg",
        "minimum",
    ),
    (
        "hae-as-text",
        "upsert.json",
        lambda d: rec(d)["position"].update(hae_m="250"),
        "E_SCHEMA",
        "records/0/position/hae_m",
        "type",
    ),
    (
        "method-unknown",
        "upsert.json",
        lambda d: rec(d)["position"].update(method="rtk"),
        "E_SCHEMA",
        "records/0/position/method",
        "enum",
    ),
    (
        "bearing-360",
        "observation.json",
        lambda d: rec(d)["signal"].update(bearing_deg_true=360),
        "E_SCHEMA",
        "records/0/signal/bearing_deg_true",
        "exclusiveMaximum",
    ),
    (
        "bearing-negative",
        "observation.json",
        lambda d: rec(d)["signal"].update(bearing_deg_true=-1),
        "E_SCHEMA",
        "records/0/signal/bearing_deg_true",
        "minimum",
    ),
    (
        "frequency-negative",
        "observation.json",
        lambda d: rec(d)["signal"].update(frequency_hz=-1),
        "E_SCHEMA",
        "records/0/signal/frequency_hz",
        "minimum",
    ),
    (
        "pulse-width-zero",
        "observation.json",
        lambda d: rec(d)["signal"].update(pulse_width_s=0),
        "E_SCHEMA",
        "records/0/signal/pulse_width_s",
        "exclusiveMinimum",
    ),
    (
        "pri-zero",
        "observation.json",
        lambda d: rec(d)["signal"].update(pri_s=0),
        "E_SCHEMA",
        "records/0/signal/pri_s",
        "exclusiveMinimum",
    ),
    (
        "signal-empty",
        "observation.json",
        lambda d: rec(d).update(signal={}),
        "E_SCHEMA",
        "records/0/signal",
        "minProperties",
    ),
    (
        "orientation-180",
        "upsert.json",
        lambda d: rec(d)["uncertainty"].update(orientation_deg=180),
        "E_SCHEMA",
        "records/0/uncertainty/orientation_deg",
        "exclusiveMaximum",
    ),
    (
        "probability-zero",
        "upsert.json",
        lambda d: rec(d)["uncertainty"].update(probability=0),
        "E_SCHEMA",
        "records/0/uncertainty/probability",
        "exclusiveMinimum",
    ),
    (
        "probability-above-1",
        "upsert.json",
        lambda d: rec(d)["uncertainty"].update(probability=1.01),
        "E_SCHEMA",
        "records/0/uncertainty/probability",
        "maximum",
    ),
    (
        "semi-major-zero",
        "upsert.json",
        lambda d: rec(d)["uncertainty"].update(semi_major_m=0),
        "E_SCHEMA",
        "records/0/uncertainty/semi_major_m",
        "exclusiveMinimum",
    ),
    (
        "frame-other",
        "upsert.json",
        lambda d: rec(d)["uncertainty"].update(frame="ENU_MAGNETIC"),
        "E_SCHEMA",
        "records/0/uncertainty/frame",
        "const",
    ),
    (
        "affiliation-finer",
        "upsert.json",
        lambda d: rec(d).update(affiliation="SUSPECT"),
        "E_SCHEMA",
        "records/0/affiliation",
        "enum",
    ),
    (
        "kind-unknown",
        "upsert.json",
        lambda d: rec(d).update(kind="task"),
        "E_SCHEMA",
        "records/0/kind",
        "enum",
    ),
    (
        "extensions-not-an-object",
        "upsert.json",
        lambda d: rec(d).update(extensions=[]),
        "E_SCHEMA",
        "records/0/extensions",
        "type",
    ),
    # -- the rules the schema cannot state (kit L106-L112, L139, L187; DECISIONS C-06 d)
    (
        "live-under-synthetic",
        "upsert.json",
        lambda d: d.update(mode="live"),
        "E_MODE_MISMATCH",
        "mode",
        "mode differs from the constructor's",
    ),
    (
        "repeated-record-id",
        "upsert.json",
        lambda d: d["records"].append({**copy.deepcopy(rec(d)), "object_id": "EMITTER-9"}),
        "E_SEMANTIC",
        "records/1/record_id",
        "repeated record_id",
    ),
    (
        "empty-records-no-snapshot",
        "upsert.json",
        lambda d: d.update(records=[]),
        "E_SEMANTIC",
        "records",
        "empty records without a snapshot",
    ),
    (
        "snapshot-repeats-object",
        "upsert.json",
        lambda d: (
            d.update(snapshot={"snapshot_id": "S", "complete": True, "revision": 4}),
            d["records"].append({**copy.deepcopy(rec(d)), "record_id": "EOB-2"}),
        ),
        "E_SEMANTIC",
        "records/1/object_id",
        "object_id repeated in a snapshot",
    ),
    (
        "upsert-without-object",
        "upsert.json",
        lambda d: rec(d).pop("object_id"),
        "E_SEMANTIC",
        "records/0/object_id",
        "object_id required",
    ),
    (
        "delete-without-object",
        "withdrawal.json",
        lambda d: rec(d).pop("object_id"),
        "E_SEMANTIC",
        "records/0/object_id",
        "object_id required",
    ),
    (
        "status-with-object",
        "status.json",
        lambda d: rec(d).update(object_id="EMITTER-1"),
        "E_SEMANTIC",
        "records/0/object_id",
        "status carries no emitter field",
    ),
    (
        "status-with-confidence",
        "status.json",
        lambda d: rec(d).update(confidence=0.5),
        "E_SEMANTIC",
        "records/0/confidence",
        "status carries no emitter field",
    ),
    (
        "status-with-signal-and-affiliation",
        "status.json",
        lambda d: rec(d).update(affiliation="HOSTILE", signal={"frequency_hz": 1}),
        "E_SEMANTIC",
        "records/0/signal",
        "status carries no emitter field",
    ),
    (
        "delete-with-position",
        "withdrawal.json",
        lambda d: rec(d).update(
            position={"latitude_deg": 57, "longitude_deg": 22, "method": "gnss"}
        ),
        "E_SEMANTIC",
        "records/0/position",
        "withdrawal carries no measurement",
    ),
    (
        "delete-with-affiliation",
        "withdrawal.json",
        lambda d: rec(d).update(affiliation="NEUTRAL"),
        "E_SEMANTIC",
        "records/0/affiliation",
        "withdrawal carries no measurement",
    ),
    (
        "ellipse-without-position",
        "upsert.json",
        lambda d: rec(d).pop("position"),
        "E_SEMANTIC",
        "records/0/uncertainty",
        "ellipse requires a position",
    ),
    (
        "ellipse-axes-reversed",
        "upsert.json",
        lambda d: rec(d)["uncertainty"].update(semi_major_m=99.5),
        "E_SEMANTIC",
        "records/0/uncertainty/semi_minor_m",
        "semi_minor_m above semi_major_m",
    ),
    (
        "snapshot-with-observation",
        "observation.json",
        lambda d: d.update(snapshot={"snapshot_id": "S", "complete": True, "revision": 1}),
        "E_SEMANTIC",
        "records/0/kind",
        "a snapshot holds eob_upsert only",
    ),
    (
        "snapshot-with-delete",
        "withdrawal.json",
        lambda d: d.update(snapshot={"snapshot_id": "S", "complete": False, "revision": 5}),
        "E_SEMANTIC",
        "records/0/kind",
        "a snapshot holds eob_upsert only",
    ),
    (
        "snapshot-revision-mismatch",
        "upsert.json",
        lambda d: d.update(snapshot={"snapshot_id": "S", "complete": True, "revision": 5}),
        "E_SEMANTIC",
        "records/0/revision",
        "revision differs from the snapshot's",
    ),
    (
        "partial-snapshot-revision-mismatch",
        "upsert.json",
        lambda d: d.update(snapshot={"snapshot_id": "S", "complete": False, "revision": 3}),
        "E_SEMANTIC",
        "records/0/revision",
        "revision differs from the snapshot's",
    ),
    # -- the first failure (DECISIONS C-06 i)
    (
        "numeric-path-order",
        "upsert.json",
        lambda d: (eleven(d), d["records"][10].update(kind="x"), d["records"][2].update(kind="y")),
        "E_SCHEMA",
        "records/2/kind",
        "enum",
    ),
    (
        "schema-before-semantic",
        "upsert.json",
        lambda d: (d["records"].append({**copy.deepcopy(rec(d)), "revision": -1}),),
        "E_SCHEMA",
        "records/1/revision",
        "minimum",
    ),
    (
        "mode-before-semantic",
        "upsert.json",
        lambda d: (d.update(mode="live"), rec(d).pop("object_id")),
        "E_MODE_MISMATCH",
        "mode",
        "mode differs from the constructor's",
    ),
    (
        "contract-before-schema",
        "upsert.json",
        lambda d: (d.update(contract="other/1", extra=1), d.pop("mode")),
        "E_UNSUPPORTED_MESSAGE",
        "contract",
        "not sc.cesmo.internal/1.0",
    ),
    (
        "root-before-children",
        "upsert.json",
        lambda d: (d.update(extra=1), rec(d).update(kind="x")),
        "E_SCHEMA",
        "",
        "additionalProperties",
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("form", ["dict", "bytes"])
def test_every_contract_fault_is_refused_with_its_code_path_and_detail(case, form):
    """C10, C12, C14, C15 and the C-06 refusal list: the whole message, the code, the path, the
    record index, on the dict path and on the octets of the same document."""
    _id, base, fault, code, path, detail = case
    document = kit(base)
    fault(document)
    source = document if form == "dict" else json.dumps(document).encode()
    error = refusal(source)
    assert str(error) == f"{code} {path or '(root)'} {detail}"
    assert (error.code, error.path, error.detail) == (code, path, detail)
    parts = path.split("/")
    assert error.record_index == (
        int(parts[1]) if parts[0] == "records" and len(parts) > 1 else None
    )


def test_the_first_failure_never_depends_on_dict_order():
    """The same two faults, the document built with every object's keys reversed."""

    def reverse(node):
        if isinstance(node, dict):
            return {k: reverse(node[k]) for k in reversed(list(node))}
        if isinstance(node, list):
            return [reverse(v) for v in node]
        return node

    document = kit()
    document["source"]["relay"] = "R"
    rec(document)["revision"] = 4.0
    assert (
        str(refusal(document))
        == str(refusal(reverse(document)))
        == "E_SCHEMA records/0/revision type"
    )
    assert (
        codec.diagnostics(document)
        == codec.diagnostics(reverse(document))
        == [
            "E_SCHEMA records/0/revision type",
            "E_SCHEMA source additionalProperties",
        ]
    )


def without(select, *keys):
    """The fault that deletes `keys` from the object `select` picks out of the document."""

    def fault(d: dict) -> None:
        target = select(d)
        for key in keys:
            del target[key]

    return fault


#: (id, the kit example, the faults, the whole diagnostics list). Several required keys missing at
#: one place: each missing key is a finding of its own, named as the last component of its own
#: path, and the findings sort as every schema finding does (keys compared as text, the codec
#: docstring's stage 4), so the first is the refusal `validate` raises. Written from the schema's
#: `required` lists, never read back from the codec.
MISSING = [
    (
        "envelope-every-key",
        "upsert.json",
        lambda d: d.clear(),
        [
            "E_SCHEMA contract required",
            "E_SCHEMA message_id required",
            "E_SCHEMA mode required",
            "E_SCHEMA observed_at required",
            "E_SCHEMA records required",
            "E_SCHEMA source required",
        ],
    ),
    (
        "envelope-two-keys",
        "upsert.json",
        without(lambda d: d, "observed_at", "message_id"),
        ["E_SCHEMA message_id required", "E_SCHEMA observed_at required"],
    ),
    (
        "source-two-keys",
        "upsert.json",
        without(lambda d: d["source"], "network_id", "identity_epoch"),
        ["E_SCHEMA source/identity_epoch required", "E_SCHEMA source/network_id required"],
    ),
    (
        "record-three-keys",
        "upsert.json",
        without(rec, "record_id", "kind", "revision"),
        [
            "E_SCHEMA records/0/kind required",
            "E_SCHEMA records/0/record_id required",
            "E_SCHEMA records/0/revision required",
        ],
    ),
    (
        "position-two-keys",
        "upsert.json",
        without(lambda d: rec(d)["position"], "longitude_deg", "method"),
        [
            "E_SCHEMA records/0/position/longitude_deg required",
            "E_SCHEMA records/0/position/method required",
        ],
    ),
    (
        "ellipse-every-key",
        "upsert.json",
        lambda d: rec(d)["uncertainty"].clear(),
        [
            "E_SCHEMA records/0/uncertainty/frame required",
            "E_SCHEMA records/0/uncertainty/orientation_deg required",
            "E_SCHEMA records/0/uncertainty/probability required",
            "E_SCHEMA records/0/uncertainty/semi_major_m required",
            "E_SCHEMA records/0/uncertainty/semi_minor_m required",
        ],
    ),
    (
        "snapshot-every-key",
        "empty-complete-snapshot.json",
        lambda d: d["snapshot"].clear(),
        [
            "E_SCHEMA snapshot/complete required",
            "E_SCHEMA snapshot/revision required",
            "E_SCHEMA snapshot/snapshot_id required",
        ],
    ),
    (
        "missing-keys-among-other-faults",
        "upsert.json",
        lambda d: (
            without(rec, "record_id", "kind")(d),
            rec(d).update(revision=4.0),
            without(lambda d: d["source"], "originator_id")(d),
        ),
        [
            "E_SCHEMA records/0/kind required",
            "E_SCHEMA records/0/record_id required",
            "E_SCHEMA records/0/revision type",
            "E_SCHEMA source/originator_id required",
        ],
    ),
]


@pytest.mark.parametrize("case", MISSING, ids=[c[0] for c in MISSING])
@pytest.mark.parametrize("form", ["dict", "bytes"])
def test_every_missing_key_is_named_once_by_its_own_path(case, form):
    """C-06(i), review R1-F1: a document missing several required keys at one place lists each of
    them once, by its own path, in the stated order; the refusal is the first of them."""
    _id, base, fault, expected = case
    document = kit(base)
    fault(document)
    source = document if form == "dict" else json.dumps(document).encode()
    assert codec.diagnostics(source) == expected
    assert codec.diagnostics(source, synthetic=True) == expected
    error = refusal(source)
    assert str(error) == expected[0]
    first_path = expected[0].split(" ")[1]
    assert (error.code, error.path, error.detail) == ("E_SCHEMA", first_path, "required")
    parts = first_path.split("/")
    assert error.record_index == (int(parts[1]) if parts[0] == "records" else None)


ACCEPTED = [
    ("hour-23-second-59", lambda d: d.update(observed_at="2026-10-04T23:59:59Z")),
    ("leap-day", lambda d: d.update(observed_at="2028-02-29T00:00:00Z")),
    ("year-1970", lambda d: d.update(observed_at="1970-01-01T00:00:00Z")),
    ("year-9999-six-digits", lambda d: rec(d).update(observed_at="9999-12-31T23:59:59.999999Z")),
    ("one-fraction-digit", lambda d: rec(d).update(observed_at="2026-10-04T12:00:00.5Z")),
    ("revision-2-to-the-53-less-1", lambda d: rec(d).update(revision=2**53 - 1)),
    ("revision-0", lambda d: rec(d).update(revision=0)),
    ("token-64", lambda d: d.update(message_id="M" * 64)),
    ("token-dots-and-underscores", lambda d: rec(d).update(object_id="EMITTER_1.a-b")),
    (
        "latitude-90-longitude-minus-180",
        lambda d: rec(d)["position"].update(latitude_deg=90, longitude_deg=-180),
    ),
    (
        "latitude-minus-90-longitude-180",
        lambda d: rec(d)["position"].update(latitude_deg=-90, longitude_deg=180),
    ),
    ("confidence-1", lambda d: rec(d).update(confidence=1)),
    (
        "probability-1-orientation-0",
        lambda d: rec(d)["uncertainty"].update(probability=1, orientation_deg=0),
    ),
    ("circular-ellipse", lambda d: rec(d)["uncertainty"].update(semi_major_m=100)),
    ("negative-zero", lambda d: rec(d)["position"].update(hae_m=-0.0)),
    (
        "nested-extensions",
        lambda d: rec(d)["extensions"].update(a={"b": [1, {"c": None}]}, z=""),
    ),
    (
        "status-without-extensions",
        lambda d: d.update(
            records=[
                {
                    "record_id": "S-1",
                    "kind": "status",
                    "revision": 0,
                    "observed_at": "2026-10-04T12:00:00Z",
                }
            ]
        ),
    ),
    (
        "partial-snapshot-without-records",
        lambda d: d.update(
            records=[], snapshot={"snapshot_id": "S", "complete": False, "revision": 0}
        ),
    ),
    ("record-time-after-envelope", lambda d: rec(d).update(observed_at="2026-10-04T12:00:05Z")),
]


@pytest.mark.parametrize("case", ACCEPTED, ids=[c[0] for c in ACCEPTED])
@pytest.mark.parametrize("form", ["dict", "bytes"])
def test_the_edges_the_contract_admits(case, form):
    document = kit()
    case[1](document)
    source = document if form == "dict" else json.dumps(document).encode()
    assert codec.validate(source, synthetic=True) == document
    assert codec.diagnostics(source, synthetic=True) == []


def test_binary64_is_the_comparison_and_the_parse_keeps_what_binary64_holds():
    """DECISIONS C-06 c: a latitude literal that binary64 reads as 90.0 is 90.0 and admitted; one
    past 90 in binary64 is refused; a subnormal is a number, not an underflow."""
    text = (SET / "upsert.json").read_text("utf-8")
    edge = text.replace('"latitude_deg": 0', '"latitude_deg": 90.000000000000001')
    assert codec.validate(edge.encode())["records"][0]["position"]["latitude_deg"] == 90.0
    past = text.replace('"latitude_deg": 0', '"latitude_deg": 90.00000000000002')
    assert str(refusal(past.encode())) == "E_SCHEMA records/0/position/latitude_deg maximum"
    tiny = text.replace('"frequency_hz": 1000000000', '"frequency_hz": 1e-310')
    assert codec.validate(tiny.encode())["records"][0]["signal"]["frequency_hz"] == 1e-310
    zero = text.replace('"frequency_hz": 1000000000', '"frequency_hz": 0.0e5')
    assert codec.validate(zero.encode())["records"][0]["signal"]["frequency_hz"] == 0.0


UPSERT = (SET / "upsert.json").read_bytes()


def swap(old: bytes, new: bytes) -> bytes:
    assert UPSERT.count(old) == 1
    return UPSERT.replace(old, new)


#: (id, octets, detail): faults only octets can carry, all E_SCHEMA at the root (kit L102).
OCTET_CASES = [
    (
        "duplicate-top-level-key",
        swap(b'"mode": "synthetic",', b'"mode": "live", "mode": "synthetic",'),
        "duplicate object key",
    ),
    (
        "duplicate-record-key",
        swap(b'"kind": "eob_upsert",', b'"kind": "eob_upsert", "kind": "status",'),
        "duplicate object key",
    ),
    (
        "duplicate-extension-key",
        swap(b'"source_category": "synthetic-emitter",', b'"a": 1, "a": 1,'),
        "duplicate object key",
    ),
    ("nan", swap(b'"confidence": 0', b'"confidence": NaN'), "non-finite number literal"),
    (
        "infinity",
        swap(b'"frequency_hz": 1000000000', b'"frequency_hz": Infinity'),
        "non-finite number literal",
    ),
    (
        "minus-infinity",
        swap(b'"frequency_hz": 1000000000', b'"frequency_hz": -Infinity'),
        "non-finite number literal",
    ),
    (
        "overflow",
        swap(b'"frequency_hz": 1000000000', b'"frequency_hz": 1e400'),
        "number outside binary64",
    ),
    (
        "negative-overflow",
        swap(b'"latitude_deg": 0', b'"latitude_deg": -1e400'),
        "number outside binary64",
    ),
    (
        "underflow",
        swap(b'"frequency_hz": 1000000000', b'"frequency_hz": 1e-400'),
        "number underflows binary64 to zero",
    ),
    (
        "integer-310-digits",
        swap(b'"revision": 4', b'"revision": 1' + b"0" * 309),
        "integer outside binary64",
    ),
    ("byte-order-mark", b"\xef\xbb\xbf" + UPSERT, "byte order mark"),
    ("invalid-byte", swap(b'"notice": "Zero', b'"notice": "\xffZero'), "not UTF-8"),
    ("overlong-encoding", swap(b'"notice": "Zero', b'"notice": "\xc0\xafZero'), "not UTF-8"),
    ("lone-continuation-byte", swap(b'"notice": "Zero', b'"notice": "\x80Zero'), "not UTF-8"),
    ("utf-16", UPSERT.decode().encode("utf-16"), "not UTF-8"),
    ("lone-surrogate-value", swap(b'"notice": "Zero', b'"notice": "\\ud800Zero'), "lone surrogate"),
    ("lone-surrogate-key", swap(b'"notice":', b'"\\udfffnotice":'), "lone surrogate"),
    ("truncated", UPSERT[:-30], "not one JSON text"),
    ("trailing-document", UPSERT + b"{}", "not one JSON text"),
    ("trailing-garbage", UPSERT + b"x", "not one JSON text"),
    ("comment", b"// c\n" + UPSERT, "not one JSON text"),
    ("empty", b"", "not one JSON text"),
    ("whitespace-only", b"  \n", "not one JSON text"),
    ("numeric-string-coercion-is-not-done", swap(b'"revision": 4', b'"revision": "4"'), None),
    ("top-level-array", b"[" + UPSERT + b"]", "not a JSON object"),
    ("top-level-string", b'"sc.cesmo.internal/1.0"', "not a JSON object"),
    ("top-level-null", b"null", "not a JSON object"),
]


@pytest.mark.parametrize("case", OCTET_CASES, ids=[c[0] for c in OCTET_CASES])
def test_octet_only_faults(case):
    """C14: duplicate keys, NaN, bad UTF-8, a BOM, truncation and trailing content are E_SCHEMA
    before any object exists; a numeric string is not coerced (it is a schema `type` error)."""
    _id, octets, detail = case
    error = refusal(octets)
    if detail is None:
        assert str(error) == "E_SCHEMA records/0/revision type"
    else:
        assert str(error) == f"E_SCHEMA (root) {detail}"
        assert (error.code, error.path, error.record_index) == ("E_SCHEMA", "", None)


def test_whitespace_around_the_document_and_a_309_digit_integer_are_admitted():
    assert codec.validate(b"\n  " + UPSERT + b"  \n") == kit()
    big = swap(b'"source_category": "synthetic-emitter"', b'"source_category": 1' + b"0" * 308)
    assert codec.validate(big)["records"][0]["extensions"]["source_category"] == 10**308


class _Str(str):
    pass


class _Float(float):
    pass


class _Rev(enum.IntEnum):
    FOUR = 4


#: (id, the value put at records[0].extensions.x, detail): types a dict can carry that JSON has not.
DICT_TYPES = [
    ("decimal", decimal.Decimal("0.5"), "not a JSON value"),
    ("bytes", b"x", "not a JSON value"),
    ("set", {1}, "not a JSON value"),
    ("tuple", (1,), "not a JSON value"),
    ("str-subclass", _Str("x"), "not a JSON value"),
    ("float-subclass", _Float(0.5), "not a JSON value"),
    ("int-enum", _Rev.FOUR, "not a JSON value"),
    ("nan", float("nan"), "non-finite number"),
    ("infinity", float("inf"), "non-finite number"),
    ("int-past-binary64", 10**400, "integer outside binary64"),
    ("lone-surrogate", "\ud800", "lone surrogate"),
    ("non-string-key", {1: "x"}, "object key is not a string"),
]


@pytest.mark.parametrize("case", DICT_TYPES, ids=[c[0] for c in DICT_TYPES])
def test_dict_path_values_json_cannot_hold(case):
    """DECISIONS C-06 f: a dict holding what no JSON text parses to is E_SCHEMA at the root."""
    _id, value, detail = case
    document = kit()
    rec(document)["extensions"]["x"] = value
    assert str(refusal(document)) == f"E_SCHEMA (root) {detail}"


def test_only_octets_or_a_dict_are_read():
    for value in ("{}", UPSERT.decode(), [kit()], None, 7, kit().items()):
        assert str(refusal(value)) == "E_SCHEMA (root) expected JSON octets or a dict"
    assert codec.validate(bytearray(UPSERT)) == codec.validate(memoryview(UPSERT)) == kit()


def _count(node) -> int:
    """JSON values, containers included (kit §19), counted here independently of the codec."""
    if isinstance(node, dict):
        return 1 + sum(_count(v) for v in node.values())
    if isinstance(node, list):
        return 1 + sum(_count(v) for v in node)
    return 1


@pytest.mark.parametrize("form", ["dict", "bytes"])
def test_the_value_text_and_depth_caps_at_and_past_their_bounds(form):
    """C16: 100,000 JSON values, a 4,096-code-point text or key (an astral character counted
    once) and 16 containers are admitted and kept; one past each is E_LIMIT at the root."""

    def run(document):
        return document if form == "dict" else json.dumps(document, ensure_ascii=False).encode()

    def with_pad(total: int) -> dict:
        document = kit()
        rec(document)["extensions"]["pad"] = []
        rec(document)["extensions"]["pad"] = [0] * (total - _count(document))
        assert _count(document) == total
        return document

    assert codec.validate(run(with_pad(100_000))) == with_pad(100_000)
    assert str(refusal(run(with_pad(100_001)))) == "E_LIMIT (root) more than 100000 JSON values"
    for text in ("x" * 4096, "\U0001f4e1" * 4096):
        document = kit()
        rec(document)["extensions"]["t"] = text
        rec(document)["extensions"][text] = 1
        assert codec.validate(run(document)) == document
    for where in ("value", "key"):
        document = kit()
        if where == "value":
            rec(document)["extensions"]["t"] = "x" * 4097
        else:
            rec(document)["extensions"]["x" * 4097] = 1
        assert str(refusal(run(document))) == "E_LIMIT (root) text longer than 4096 code points"
    deep = kit()
    node: list = []
    for _ in range(11):
        node = [node]
    rec(deep)["extensions"]["n"] = node  # root, records, record, extensions and 12 lists
    assert codec.validate(run(deep)) == deep
    rec(deep)["extensions"]["n"] = [node]
    assert str(refusal(run(deep))) == "E_LIMIT (root) nesting deeper than 16 containers"


def test_the_caps_come_before_the_schema_and_in_a_fixed_order():
    """Resource limits terminate first (kit L267): values, then depth, then text, then the
    tree's type findings, whatever else is wrong."""
    document = kit()
    document["unknown"] = 1
    node: list = []
    for _ in range(13):
        node = [node]
    rec(document)["extensions"]["n"] = node
    rec(document)["extensions"]["t"] = "x" * 5000
    rec(document)["extensions"]["pad"] = [0] * 100_001
    rec(document)["extensions"][1] = "non-string key"
    assert str(refusal(document)) == "E_LIMIT (root) more than 100000 JSON values"
    rec(document)["extensions"].pop("pad")
    assert str(refusal(document)) == "E_LIMIT (root) nesting deeper than 16 containers"
    rec(document)["extensions"].pop("n")
    assert str(refusal(document)) == "E_LIMIT (root) text longer than 4096 code points"
    rec(document)["extensions"].pop("t")
    assert str(refusal(document)) == "E_SCHEMA (root) object key is not a string"


def test_a_cyclic_or_exponentially_shared_dict_is_refused_at_the_value_cap():
    """A dict is not JSON text: it can contain itself, or share one subtree so often that a walk
    of every path is exponential. The walk stops at the 100,001st value."""
    cyclic = kit()
    rec(cyclic)["extensions"]["self"] = cyclic
    shared: dict = {}
    for _ in range(40):
        shared = {"a": shared, "b": shared, "c": shared}
    wide = kit()
    rec(wide)["extensions"]["shared"] = shared
    for document in (cyclic, wide):
        assert str(refusal(document)) == "E_LIMIT (root) more than 100000 JSON values"
        assert codec.diagnostics(document) == ["E_LIMIT (root) more than 100000 JSON values"]
        with pytest.raises(CesmoError) as raised:
            codec.count_values(document)
        assert raised.value.code == "E_LIMIT"


def test_octets_past_the_manifest_depth_are_refused_before_the_decoder():
    """A direct caller of the codec gets the bound the SDK applies in `to_cdm`, before
    `json.loads` (which recurses) sees the text."""
    for depth in (65, 5000, 200_000):
        text = b"[" * depth + b"]" * depth
        error = refusal(text)
        assert isinstance(error, codec.CesmoInputTooDeep) and error.code == "E_LIMIT"
        assert str(error) == f"E_LIMIT (root) nesting {depth} containers deep, past the bound of 64"
    assert str(refusal(b"[" * 64 + b"]" * 64)) == "E_LIMIT (root) nesting deeper than 16 containers"


def test_a_diagnostic_is_bounded_and_never_quotes_the_payload():
    marker = "PAYLOAD-MARKER-" * 300
    cases = []
    for build in (
        lambda d: d.update({marker: 1}),
        lambda d: d.update(message_id=marker),
        lambda d: rec(d).update(record_id=marker[:64] + "\n"),
        lambda d: rec(d)["extensions"].update({marker: marker}),
        lambda d: d.update(contract=marker),
        lambda d: d.update(observed_at=marker),
    ):
        document = kit()
        build(document)
        cases.append(document)
    for document in cases:
        for message in [str(refusal(document))] + codec.diagnostics(document):
            assert "MARKER" not in message and len(message) <= 512


def test_the_codes_are_the_section_19_table_and_five_are_raised():
    assert codec.CODES == (
        "E_BINDING_BLOCKED",
        "E_EDITION",
        "E_FRAMING",
        "E_SCHEMA",
        "E_SEMANTIC",
        "E_TIME_UNRESOLVED",
        "E_MODE_MISMATCH",
        "E_LIMIT",
        "E_UNSUPPORTED_MESSAGE",
        "E_UNKNOWN_CRITICAL",
        "E_ID_CONFLICT",
        "E_REVISION_CONFLICT",
        "E_LABEL_UNRESOLVED",
        "E_POLICY_DENIED",
        "E_STALE_REPLAY",
        "E_EGRESS_UNREPRESENTABLE",
    )
    assert codec.RAISED_CODES == (
        "E_SCHEMA",
        "E_SEMANTIC",
        "E_MODE_MISMATCH",
        "E_LIMIT",
        "E_UNSUPPORTED_MESSAGE",
    )
    for code in set(codec.CODES) - set(codec.RAISED_CODES):
        with pytest.raises(ValueError, match="a refusal code this module does not raise"):
            CesmoError(code, "", "x")
        assert code in codec.__doc__
    assert issubclass(CesmoError, ValueError)


def test_the_timestamp_grammar_directly():
    assert codec.instant("2026-10-04T12:00:00Z")[1] is False
    assert codec.instant("2026-10-04T12:00:00.000999Z")[1] is True
    assert codec.instant("2026-10-04T12:00:00.999000Z")[1] is False
    stamp, dropped = codec.instant("2026-10-04T12:00:00.123456Z")
    assert (stamp.microsecond, dropped, str(stamp.tzinfo)) == (123456, True, "UTC")
    for bad in (
        "2026-10-04T24:00:00Z",
        "2026-10-04T12:00:00",
        "2026-10-04 12:00:00Z",
        None,
        1,
        "10000-01-01T00:00:00Z",
        "2026-1-04T12:00:00Z",
    ):
        assert codec.instant(bad) is None


def test_the_validator_never_relies_on_a_format_checker():
    """`format: date-time` is the codec's own keyword: `jsonschema.FormatChecker` registers a
    date-time checker only when an optional package is importable (A-04)."""
    assert codec.VALIDATOR.format_checker is None
    assert codec.VALIDATOR.VALIDATORS["format"] is codec._date_time
    assert codec.VALIDATOR.VALIDATORS["pattern"] is codec._ecma_pattern
