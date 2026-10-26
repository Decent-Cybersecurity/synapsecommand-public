"""The policy seam: artefacts, principals, the descriptor, decisions, the default gate field by
field, the registry, tickets and revocation, derivative inheritance, and the fakes' fences."""

from __future__ import annotations

import json

import pytest
from conftest import LOCAL
from helpers import (
    SECURITY_FIELDS,
    build_nsif,
    des,
    image,
    set_field,
    vector,
    with_security_field,
)

from synapse_cdm.adapters.stanag4545 import (
    CORE1_LIMITS,
    assess_security,
    parse_container,
    security_labels,
)
from synapse_imagery.fakes import FakePolicy, InProcessWorker, MemoryAssetStore
from synapse_imagery.policy import (
    EMPTY_REGISTRY,
    Artefact,
    DefaultPolicy,
    ExtensionRegistry,
    PolicyDecision,
    PolicyRequest,
    Principal,
    SecurityDescriptor,
    TicketAuthority,
)
from synapse_imagery.result import HostError, PolicyDenied
from synapse_imagery.worker import Window, WorkerPool

GEO_DMS = vector("geo_dms.ntf")


def descriptor_of(octets: bytes, registry: ExtensionRegistry = EMPTY_REGISTRY):
    return SecurityDescriptor.from_container(parse_container(octets, CORE1_LIMITS), registry)


def request_for(
    descriptor, artefact=Artefact.METADATA, principal=LOCAL, synthetic=True, asset=None
):
    return PolicyRequest(principal, artefact, descriptor, synthetic, None, asset)


# --------------------------------------------------------------------------- names and records


def test_the_seven_artefacts_are_approved_independently_in_this_order():
    assert [artefact.value for artefact in Artefact] == [
        "metadata",
        "original",
        "pixels",
        "thumbnail",
        "tile",
        "text",
        "export",
    ]


@pytest.mark.parametrize("tenant", ["a|b", "", "   ", "é", "x" * 129, "tab\there"])
def test_a_principal_refuses_what_cannot_name_a_tenant(tenant):
    with pytest.raises(ValueError):
        Principal(tenant, "s")
    with pytest.raises(ValueError):
        Principal("t", tenant)


def test_a_principal_takes_exact_strings_only():
    with pytest.raises(TypeError):
        Principal(5, "s")
    assert Principal("x" * 128, "local-operator").tenant == "x" * 128


def test_the_descriptor_carries_the_adapters_records_verbatim():
    container = parse_container(GEO_DMS, CORE1_LIMITS)
    descriptor = SecurityDescriptor.from_container(container, EMPTY_REGISTRY)
    assert descriptor.labels == security_labels(container)
    assert descriptor.assessment == assess_security(container)
    assert descriptor.extensions == []
    assert descriptor.registry_version == "sc4545-core-1-empty"
    assert list(json.loads(descriptor.json_text)) == [
        "labels",
        "assessment",
        "extensions",
        "registry_version",
    ]


def test_two_descriptors_of_the_same_octets_are_equal_and_hash_equal():
    first, second = descriptor_of(GEO_DMS), descriptor_of(bytes(GEO_DMS))
    assert first == second and hash(first) == hash(second)
    # The security facts, not the octets, make the descriptor: mono_nsif101 has the same labels.
    assert first == descriptor_of(vector("mono_nsif101.ntf"))
    assert first != descriptor_of(vector("image_and_text.ntf"))


def test_the_extension_identifiers_are_listed_in_order_by_kind():
    assert descriptor_of(vector("unknown_duplicate_tre.ntf")).extensions == [
        ["tre", "SCZZZZ"],
        ["tre", "SCZZZZ"],
    ]
    with_des = build_nsif(
        [image(icords="G", igeolo="480000N0170000E480000N0180000E470000N0180000E470000N0170000E")],
        des_segments=[des(desid="SCDES")],
    )
    assert descriptor_of(with_des).extensions == [["des", "SCDES"]]


@pytest.mark.parametrize(
    "edit",
    [
        lambda doc: doc.pop("registry_version"),
        lambda doc: doc.update(extra=1),
        lambda doc: doc.update(labels=[]),
        lambda doc: doc["labels"][0].pop("uninterpreted"),
        lambda doc: doc["labels"][0]["fields"].update(CLAS=7),
        lambda doc: doc["labels"][0].update(uninterpreted=["CTLN"]),
        lambda doc: doc["assessment"].pop("kind"),
        lambda doc: doc["assessment"].update(scopes=True),
        lambda doc: doc.update(extensions=[["xyz", "A"]]),
        lambda doc: doc.update(registry_version=""),
    ],
)
def test_a_descriptor_of_another_shape_is_refused(edit):
    document = json.loads(descriptor_of(GEO_DMS).json_text)
    edit(document)
    text = json.dumps(document, ensure_ascii=True, separators=(",", ":"))
    with pytest.raises(HostError) as caught:
        SecurityDescriptor.from_json(text)
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_INTERNAL",
        "security",
        "/descriptor",
    )


def test_a_descriptor_in_another_text_form_is_refused():
    pretty = json.dumps(json.loads(descriptor_of(GEO_DMS).json_text), indent=1)
    with pytest.raises(HostError):
        SecurityDescriptor.from_json(pretty)


def test_no_repr_carries_a_label_value():
    octets = with_security_field(GEO_DMS, "image", "CLTX", "SECRETXYZ")
    descriptor = descriptor_of(octets)
    assert "SECRETXYZ" in descriptor.json_text
    request = request_for(descriptor)
    for shown in (repr(descriptor), str(descriptor), repr(request)):
        assert "SECRETXYZ" not in shown
    assert repr(descriptor) == f"SecurityDescriptor({descriptor.sha256[:12]})"


def test_host_errors_have_the_adapters_string_form():
    assert str(HostError("E_LENGTH", "header", 0, "/x", "m")) == "E_LENGTH @byte 0 /x: m"
    assert str(HostError("E_LENGTH", "header", None, "/x", "m")) == "E_LENGTH @byte - /x: m"
    for bad in (
        ("E_NOPE", "header", 0, "/x", "m"),
        ("E_LENGTH", "policy", 0, "/x", "m"),
        ("E_LENGTH", "header", -1, "/x", "m"),
        ("E_LENGTH", "header", True, "/x", "m"),
        ("E_LENGTH", "header", 0, "x", "m"),
    ):
        with pytest.raises(TypeError):
            HostError(*bad)


def test_a_policy_denial_is_always_e_policy_at_security_without_an_offset():
    denied = PolicyDenied(Artefact.PIXELS, "refused")
    assert str(denied).startswith("E_POLICY @byte - /policy/pixels:")
    assert (denied.code, denied.stage, denied.offset, denied.path) == (
        "E_POLICY",
        "security",
        None,
        "/policy/pixels",
    )


def test_a_decision_cannot_allow_an_incomplete_assessment():
    with pytest.raises(ValueError):
        PolicyDecision(True, "X1", "p", "1", "incomplete")
    with pytest.raises(ValueError):
        PolicyDecision(False, "lower", "p", "1", "complete")
    with pytest.raises(ValueError):
        PolicyDecision(False, "X1", "p", "1", "partial")
    assert PolicyDecision(False, "X1", "p", "1", "incomplete").allowed is False


class _Raising:
    policy_id, policy_version = "raising", "1"

    def decide(self, request):
        raise RuntimeError("engine defect")


class _Silent:
    policy_id, policy_version = "silent", "1"

    def decide(self, request):
        return True


@pytest.mark.parametrize("engine", [_Raising(), _Silent()])
def test_an_engine_that_gives_no_decision_fails_the_ingest_closed(
    services, store, tmp_path, engine
):
    service = services(store, policy=engine, worker=InProcessWorker())
    result = service.ingest(GEO_DMS, principal=LOCAL, dataset_namespace="default", synthetic=True)
    assert result["state"] == "failed"
    assert [entry["code"] for entry in result["diagnostics"]] == ["E_INTERNAL"]
    assert result["asset_id"] is None and result["cdm_ids"] == []
    files = [p.relative_to(tmp_path / "store").as_posix() for p in (tmp_path / "store").rglob("*")]
    assert not [name for name in files if "/records/" in name or "/originals/" in name]
    assert not [name for name in files if "/published/" in name]
    assert service.catalog.list_records(principal=LOCAL) == []


# --------------------------------------------------------------------------- the default gate

_PRINTABLE_ADMITTED = (
    "DCTP",
    "DCDT",
    "DCXM",
    "DG",
    "DGDT",
    "CLTX",
    "CAPT",
    "CAUT",
    "CRSN",
    "SRDT",
    "CTLN",
)


def _gate_rows():
    """Every mutation of HOST-06's table with its literal expectation: allowed exactly where the
    adapter's assessment table makes the labels declared unclassified."""
    rows = []
    for scope in ("file", "image"):
        for clas in ("R", "C", "S", "T", " ", "X", "u"):
            rows.append((f"{scope}-CLAS-{clas!r}", [(scope, "CLAS", clas.encode())], False))
        for name in ("CODE", "CTLH", "REL"):
            rows.append((f"{scope}-{name}-populated", [(scope, name, b"AB")], False))
        rows.append((f"{scope}-CLSY-XN-alone", [(scope, "CLSY", b"XN")], False))
        for name, _, width in SECURITY_FIELDS:
            rows.append(
                (
                    f"{scope}-{name}-printable",
                    [(scope, name, b"Z" * width)],
                    name in _PRINTABLE_ADMITTED,
                )
            )
            rows.append((f"{scope}-{name}-ff", [(scope, name, b"\xff")], False))
    rows.append(("both-CLSY-XN", [("file", "CLSY", b"XN"), ("image", "CLSY", b"XN")], True))
    return rows


@pytest.mark.parametrize(
    "label, edits, admitted", _gate_rows(), ids=[row[0] for row in _gate_rows()]
)
def test_the_default_gate_field_by_field(label, edits, admitted):
    octets = GEO_DMS
    for scope, name, value in edits:
        if value == b"\xff":
            base = {"file": 119, "image": 527}[scope]
            offset = dict((n, o) for n, o, _ in SECURITY_FIELDS)[name]
            octets = set_field(octets, base + offset, b"\xff")
        else:
            octets = with_security_field(octets, scope, name, value)
    descriptor = descriptor_of(octets)
    gate = DefaultPolicy()
    for artefact in Artefact:
        decision = gate.decide(request_for(descriptor, artefact))
        assert decision.allowed is admitted, (label, artefact)
        assert decision.reason == (
            "ADMITTED_DECLARED_UNCLASSIFIED" if admitted else "STATUS_NOT_DECLARED_UNCLASSIFIED"
        )
        assert decision.completeness == "complete"
        assert (decision.policy_id, decision.policy_version) == ("sc-imagery-default-clean-u", "1")


@pytest.mark.parametrize(
    "name",
    [
        "geo_dms.ntf",
        "mono_nsif101.ntf",
        "mono_nsif100.ntf",
        "mono_nitf210.ntf",
        "mode_B.ntf",
        "mode_P.ntf",
        "mode_R.ntf",
        "mode_S.ntf",
        "uint16.ntf",
        "image_and_text.ntf",
        "header_only.ntf",
    ],
)
def test_the_kit_vectors_the_gate_admits_for_every_artefact(name):
    descriptor = descriptor_of(vector(name))
    for artefact in Artefact:
        assert DefaultPolicy().decide(request_for(descriptor, artefact)).allowed is True


def test_unknown_extensions_are_denied_and_incomplete_for_every_artefact():
    descriptor = descriptor_of(vector("unknown_duplicate_tre.ntf"))
    for artefact in Artefact:
        decision = DefaultPolicy().decide(request_for(descriptor, artefact))
        assert (decision.allowed, decision.reason, decision.completeness) == (
            False,
            "STATUS_NOT_DECLARED_UNCLASSIFIED",
            "incomplete",
        )


def _edited(octets: bytes, **assessment) -> SecurityDescriptor:
    document = json.loads(descriptor_of(octets).json_text)
    document["assessment"].update(assessment)
    return SecurityDescriptor(json.dumps(document, ensure_ascii=True, separators=(",", ":")))


def test_the_gate_reads_the_assessment_and_cross_checks_it_against_itself():
    gate = DefaultPolicy()
    forged = _edited(vector("unknown_duplicate_tre.ntf"), status="declared_unclassified")
    assert gate.decide(request_for(forged)).reason == "STATUS_NOT_DECLARED_UNCLASSIFIED"
    assert gate.decide(request_for(_edited(GEO_DMS, clas_values=["R"]))).reason == (
        "ASSESSMENT_INCONSISTENT"
    )
    assert gate.decide(request_for(_edited(GEO_DMS, scopes=3))).reason == "ASSESSMENT_INCONSISTENT"
    assert gate.decide(request_for(_edited(GEO_DMS, uniform_clas=False))).reason == (
        "ASSESSMENT_INCONSISTENT"
    )
    assert gate.decide(request_for(_edited(GEO_DMS, kind="host_assessment"))).reason == (
        "ASSESSMENT_MALFORMED"
    )
    assert gate.decide(request_for(_edited(GEO_DMS, combination="performed"))).reason == (
        "ASSESSMENT_MALFORMED"
    )


def test_a_registry_can_complete_an_assessment_and_the_gate_still_denies_unknown_extensions():
    tre_free = _edited(
        vector("unknown_duplicate_tre.ntf"), status="declared_unclassified", reasons=[]
    )
    neutral = ExtensionRegistry("test-neutral-1", frozenset({("tre", "SCZZZZ")}))
    assert DefaultPolicy().decide(request_for(tre_free)).reason == "ASSESSMENT_INCONSISTENT"
    decision = DefaultPolicy(neutral).decide(
        request_for(descriptor_of(vector("unknown_duplicate_tre.ntf"), neutral))
    )
    assert (decision.allowed, decision.reason, decision.completeness) == (
        False,
        "STATUS_NOT_DECLARED_UNCLASSIFIED",
        "complete",
    )


def test_security_dates_are_labels_and_never_downgrade():
    past = with_security_field(GEO_DMS, "file", "DG", "D")
    past = with_security_field(past, "file", "DGDT", "20000101")
    assert DefaultPolicy().decide(request_for(descriptor_of(past))).allowed is True
    restricted = with_security_field(past, "file", "CLAS", "R")
    decision = DefaultPolicy().decide(request_for(descriptor_of(restricted)))
    assert (decision.allowed, decision.reason) == (False, "STATUS_NOT_DECLARED_UNCLASSIFIED")


def test_the_gate_takes_no_other_input():
    gate = DefaultPolicy()
    descriptor = descriptor_of(GEO_DMS)
    other = Principal("tenant-two", "someone-else")
    answers = {
        (
            gate.decide(request_for(descriptor, a, p, s)).allowed,
            gate.decide(request_for(descriptor, a, p, s)).reason,
        )
        for a in Artefact
        for p in (LOCAL, other)
        for s in (True, False)
    }
    assert answers == {(True, "ADMITTED_DECLARED_UNCLASSIFIED")}


# --------------------------------------------------------------------------- the registry


def test_the_shipped_registry_is_empty_and_versioned():
    assert EMPTY_REGISTRY.version == "sc4545-core-1-empty"
    assert len(EMPTY_REGISTRY.security_neutral) == 0


@pytest.mark.parametrize(
    "version, entries, error",
    [
        ("", frozenset(), ValueError),
        ("x" * 65, frozenset(), ValueError),
        ("vé", frozenset(), ValueError),
        ("v1", frozenset({("xyz", "A")}), ValueError),
        ("v1", frozenset({("tre", "")}), ValueError),
        ("v1", frozenset({("tre", "x" * 26)}), ValueError),
        ("v1", {("tre", "A")}, TypeError),
    ],
)
def test_a_registry_validates_its_version_and_entries(version, entries, error):
    with pytest.raises(error):
        ExtensionRegistry(version, entries)


def test_unknown_extensions_are_quarantined_with_an_incomplete_assessment(
    services, store, tmp_path
):
    service = services(store)
    result = service.ingest(
        vector("unknown_duplicate_tre.ntf"),
        principal=LOCAL,
        dataset_namespace="default",
        synthetic=True,
    )
    assert result["state"] == "policy_blocked" and result["cdm_ids"] == []
    assert result["asset_id"] is not None
    tenant = tmp_path / "store" / "tenants" / store_tenant()
    assert (tenant / "quarantine" / "originals" / result["asset_id"]).is_file()
    assert [entry["code"] for entry in result["diagnostics"]] == [
        "E_POLICY",
        "POLICY_ASSESSMENT_INCOMPLETE",
    ]
    assert result["diagnostics"][1]["message"] == (
        "2 extension record(s) not identified as security-neutral by registry sc4545-core-1-empty"
    )


def store_tenant() -> str:
    from helpers import ruled_tenant_dir

    return ruled_tenant_dir("local")


def test_a_neutral_registry_completes_the_assessment_and_the_default_gate_still_blocks(
    services, store
):
    neutral = ExtensionRegistry("test-neutral-1", frozenset({("tre", "SCZZZZ")}))
    service = services(store, registry=neutral)
    result = service.ingest(
        vector("unknown_duplicate_tre.ntf"),
        principal=LOCAL,
        dataset_namespace="default",
        synthetic=True,
    )
    assert result["state"] == "policy_blocked"
    assert [entry["code"] for entry in result["diagnostics"]] == ["E_POLICY"]
    record = service.catalog.read_quarantined(result["record_id"], principal=LOCAL)
    assert record["decision"]["completeness"] == "complete"
    assert json.loads(record["descriptor"])["registry_version"] == "test-neutral-1"


def test_a_text_segment_is_no_extension_and_a_des_is(services, store):
    service = services(store, worker=InProcessWorker())
    text = service.ingest(
        vector("image_and_text.ntf"), principal=LOCAL, dataset_namespace="default", synthetic=True
    )
    assert text["state"] == "committed"
    with_des = build_nsif(
        [image(icords="G", igeolo="480000N0170000E480000N0180000E470000N0180000E470000N0170000E")],
        des_segments=[des(desid="ANY DESID")],
    )
    blocked = service.ingest(with_des, principal=LOCAL, dataset_namespace="default", synthetic=True)
    assert blocked["state"] == "policy_blocked"
    assert [entry["code"] for entry in blocked["diagnostics"]] == [
        "E_POLICY",
        "POLICY_ASSESSMENT_INCOMPLETE",
    ]


# --------------------------------------------------------------------------- tickets

_SCRIPT = {
    Artefact.METADATA: True,
    Artefact.ORIGINAL: True,
    Artefact.PIXELS: False,
    Artefact.THUMBNAIL: True,
    Artefact.EXPORT: False,
}


def _committed(services, store, octets, policy=None):
    service = services(store, policy=policy, worker=InProcessWorker())
    result = service.ingest(octets, principal=LOCAL, dataset_namespace="default", synthetic=True)
    assert result["state"] == "committed"
    return service, result


def test_each_artefact_is_decided_on_its_own(services, store):
    service, result = _committed(services, store, GEO_DMS, FakePolicy(_SCRIPT))
    with pytest.raises(PolicyDenied) as caught:
        service.decode_window(result["record_id"], 0, Window(0, 0, 2, 2), (0,), principal=LOCAL)
    assert caught.value.path == "/policy/pixels"
    assert "FAKE_SCRIPTED_DENY" in caught.value.message
    assert len(service.catalog.objects(result["record_id"], principal=LOCAL)) == 2


def test_a_ticket_names_one_artefact_one_asset_and_one_tenant(services, store):
    _, first = _committed(services, store, GEO_DMS)
    _, second = _committed(services, store, vector("mono_nsif101.ntf"))
    authority = TicketAuthority(FakePolicy({artefact: True for artefact in Artefact}))
    descriptor = descriptor_of(GEO_DMS)
    ticket = authority.issue(request_for(descriptor, Artefact.ORIGINAL, asset=first["asset_id"]))
    authority.check(ticket, artefact=Artefact.ORIGINAL, asset_id=first["asset_id"], tenant="local")
    for artefact, asset, tenant in (
        (Artefact.ORIGINAL, second["asset_id"], "local"),
        (Artefact.ORIGINAL, first["asset_id"], "tenant-two"),
        (Artefact.PIXELS, first["asset_id"], "local"),
    ):
        with pytest.raises(PolicyDenied):
            authority.check(ticket, artefact=artefact, asset_id=asset, tenant=tenant)
    assert ticket.ticket_id not in repr(ticket)
    assert len(ticket.ticket_id) == 32


def test_revocation_stops_a_reader_on_its_next_read(services, store):
    _, result = _committed(services, store, GEO_DMS)
    authority = TicketAuthority(FakePolicy({artefact: True for artefact in Artefact}))
    ticket = authority.issue(
        request_for(descriptor_of(GEO_DMS), Artefact.ORIGINAL, asset=result["asset_id"])
    )
    reader = store.open_original(result["asset_id"], ticket)
    assert reader.read(100) == GEO_DMS[:100]
    assert authority.revoke_asset(result["asset_id"]) == 1
    with pytest.raises(HostError) as caught:
        reader.read(100)
    assert caught.value.code == "E_POLICY"
    reader.close()


def test_a_new_epoch_revokes_every_earlier_ticket_of_its_own_authority_only(services, store):
    _, result = _committed(services, store, GEO_DMS)
    asset = result["asset_id"]
    everything = FakePolicy({artefact: True for artefact in Artefact})
    mine, other = TicketAuthority(everything), TicketAuthority(everything)
    ticket = mine.issue(request_for(descriptor_of(GEO_DMS), Artefact.ORIGINAL, asset=asset))
    other.advance_epoch()
    store.open_original(asset, ticket).close()
    mine.advance_epoch()
    with pytest.raises(HostError) as caught:
        store.open_original(asset, ticket)
    assert str(caught.value) == "E_POLICY @byte - /asset: no such asset for this ticket"


def test_revoking_a_subject_revokes_its_tickets_only():
    authority = TicketAuthority(FakePolicy({artefact: True for artefact in Artefact}))
    descriptor = descriptor_of(GEO_DMS)
    other = Principal("local", "someone-else")
    mine = authority.issue(request_for(descriptor, Artefact.ORIGINAL, asset="a"))
    theirs = authority.issue(request_for(descriptor, Artefact.ORIGINAL, principal=other, asset="a"))
    assert authority.revoke_subject("local", "someone-else") == 1
    authority.check(mine, artefact=Artefact.ORIGINAL, asset_id="a", tenant="local")
    with pytest.raises(PolicyDenied):
        authority.check(theirs, artefact=Artefact.ORIGINAL, asset_id="a", tenant="local")


def test_a_denied_artefact_issues_no_ticket():
    authority = TicketAuthority(DefaultPolicy())
    descriptor = descriptor_of(vector("unknown_duplicate_tre.ntf"))
    with pytest.raises(PolicyDenied) as caught:
        authority.issue(request_for(descriptor, Artefact.ORIGINAL, asset="a"))
    assert caught.value.path == "/policy/original"
    assert caught.value.message == (
        "refused by policy sc-imagery-default-clean-u/1: STATUS_NOT_DECLARED_UNCLASSIFIED"
    )


# --------------------------------------------------------------------------- footprints


def test_a_decision_on_a_footprint_equals_the_decision_on_its_product(services, store):
    service, result = _committed(services, store, GEO_DMS)
    product, footprint = service.catalog.objects(result["record_id"], principal=LOCAL)
    on_product = product["residual"]["data"]["stanag4545"]["security"]
    on_footprint = footprint["residual"]["data"]["stanag4545"]["security"]
    assert on_footprint["assessment"] == on_product["assessment"]
    stored = json.loads(
        store.read_record("local", result["record_id"], area="records")["descriptor"]
    )
    # The record is canonical JSON (sorted keys); the descriptor keeps the adapter's key order.
    label_keys = ["scope", "index", "offset", "length", "fields", "uninterpreted"]
    names = [name for name, _, _ in SECURITY_FIELDS]
    labels = [
        {
            **{key: label[key] for key in label_keys},
            "fields": {n: label["fields"][n] for n in names},
        }
        for label in on_footprint["labels"]
    ]
    assessment_keys = list(descriptor_of(GEO_DMS).assessment)
    counts = on_footprint["assessment"]["unknown_extensions"]
    on_footprint["assessment"]["unknown_extensions"] = {k: counts[k] for k in ("tre", "des", "res")}
    assembled = SecurityDescriptor(
        json.dumps(
            {
                "labels": labels,
                "assessment": {key: on_footprint["assessment"][key] for key in assessment_keys},
                "extensions": [],
                "registry_version": stored["registry_version"],
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
    )
    gate = DefaultPolicy()
    assert gate.decide(request_for(assembled)) == gate.decide(request_for(descriptor_of(GEO_DMS)))


def test_a_blocked_product_leaves_no_cdm_object_anywhere(services, store, tmp_path):
    service = services(store)
    service.ingest(
        vector("unknown_duplicate_tre.ntf"),
        principal=LOCAL,
        dataset_namespace="default",
        synthetic=True,
    )
    restricted = with_security_field(GEO_DMS, "image", "CLAS", "R")
    blocked = service.ingest(
        restricted, principal=LOCAL, dataset_namespace="default", synthetic=True
    )
    assert blocked["state"] == "policy_blocked"
    for path in (tmp_path / "store").rglob("*.json"):
        if path.name.endswith(".json") and "records" in path.parts:
            assert json.loads(path.read_text())["objects"] == []
    for path in (tmp_path / "store").rglob("*"):
        if path.is_file():
            assert (
                b"PlanObject" not in path.read_bytes()
                and b"OVERLAY_OBJECT" not in path.read_bytes()
            )


# --------------------------------------------------------------------------- the fakes' fences


def test_the_fake_policy_refuses_live_material_whatever_its_table():
    fake = FakePolicy({artefact: True for artefact in Artefact})
    decision = fake.decide(request_for(descriptor_of(GEO_DMS), synthetic=False))
    assert (decision.allowed, decision.reason, decision.completeness) == (
        False,
        "FAKE_LIVE_REFUSED",
        "complete",
    )
    assert fake.decide(request_for(descriptor_of(GEO_DMS))).reason == "FAKE_SCRIPTED_ALLOW"
    assert FakePolicy({}).decide(request_for(descriptor_of(GEO_DMS))).reason == "FAKE_SCRIPTED_DENY"


def test_a_live_ingest_refuses_every_fake(services, store):
    cases = [
        services(store, worker=InProcessWorker()),
        services(store, policy=FakePolicy({Artefact.METADATA: True}), worker=WorkerPool()),
        services(MemoryAssetStore(), worker=WorkerPool()),
    ]
    for service in cases:
        with pytest.raises(ValueError):
            service.ingest(GEO_DMS, principal=LOCAL, dataset_namespace="default", synthetic=False)
    cases[2]._store.close()
