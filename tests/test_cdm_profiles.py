"""The seven profile documents, against the registry they describe and the examples they cite.

`spec/sc-oes/profiles/` is the normative profile tree. None of it ships in the wheel, so this
module is REPOSITORY-BOUND (`gates/wheel_install.py`); its subject is the DOCUMENTS, where
`tests/test_cdm_conformance_spec.py`'s subject is the conformance implementation those documents
fix. The two overlap on exactly one sentence — the one that keeps dimension D honest — and that
sentence is asserted there, not here, so there is one gate for it and not two.

WHAT A PROFILE MAY AND MAY NOT SAY
----------------------------------
The packaged event registry is the machine authority for a governed type's class, maturity,
ontology class, payload model and legacy mapping (`spec/sc-oes/03-event-types.md`), and
`../03-event-types.md` is the human index that pairs a type with its class. A profile that
repeated either would be a third copy of one fact, and the third copy is the one nobody updates.
So a profile names identifiers and says which classes its types span AS A SET, and the checks
below are written to catch the copy: every type the registry files under a profile appears in that
profile's document, no type another profile owns appears in it, and no line of a profile pairs a
governed identifier with a class or a maturity value.

WHY THE COUNTS ARE DERIVED AND NOT WRITTEN DOWN
-----------------------------------------------
`get_profile_event_types` is asked on every run. A fourteenth governed type filed under Air would
arrive here as a document that does not mention it, which is the failure that gets the document
fixed — rather than as a passing test over the three that were already there.
"""
import pathlib
import re

import pytest

import synapse_cdm
from synapse_cdm import adapter
from synapse_cdm.oes import EventClass
from synapse_cdm.oes_registry import (
    PROFILES,
    Maturity,
    get_profile,
    get_profile_event_types,
)
from synapse_cdm.version import SC_OES_VERSION

REPO = pathlib.Path(synapse_cdm.__file__).resolve().parents[3]
PROFILE_DIR = REPO / "spec" / "sc-oes" / "profiles"
DOCS = {name: PROFILE_DIR / f"{name.lower()}.md" for name in PROFILES}

#: The sixteen headings a profile must carry, in the order the specification lists them (§113),
#: plus the one this repository adds. `Conformance` is last because it is the section that reports
#: what the other sixteen amount to; a reader who stops before it has still read the profile.
REQUIRED_HEADINGS = (
    "Scope", "Version", "Maturity", "Ontology concepts", "Event types in scope", "EventClass",
    "Payload semantics", "Required fields", "Optional fields", "Temporality", "Entity relations",
    "Extensions", "Security considerations", "Examples", "Non-goals", "Implementation status",
    "Conformance",
)

#: §114's two statuses, verbatim enough to be found and specific enough to mean something.
PRODUCER_BACKED = "**Reference producer-backed.**"
SPECIFICATION_ONLY = "**Specification-only in v0.1.0.**"

#: The one profile §114 names as producer-backed. Not written down as a bare string: it is checked
#: against the adapter that actually emits the block, in
#: `test_the_producer_backed_profile_is_the_one_with_a_producer_behind_it`.
PRODUCER_BACKED_PROFILE = "PNT"

#: The one profile with executable dimension D rules (§12), and the six without. Both derived
#: from the packaged registry: a second profile acquiring rules moves these sets rather than
#: leaving a parametrisation that no longer covers what it claims to.
EXECUTABLE_PROFILE = "PNT"
SPECIFICATION_ONLY_PROFILES = tuple(p for p in PROFILES if p != EXECUTABLE_PROFILE)

GOVERNED_ID = re.compile(r"sc\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.v[1-9][0-9]*")


def _text(profile: str) -> str:
    return DOCS[profile].read_text()


def _headings(profile: str) -> list[str]:
    return [line[3:].strip() for line in _text(profile).splitlines() if line.startswith("## ")]


def _section(profile: str, heading: str) -> str:
    text = _text(profile)
    start = text.index(f"\n## {heading}\n") + len(heading) + 5
    rest = text[start:]
    nxt = rest.find("\n## ")
    return rest if nxt < 0 else rest[:nxt]


# ------------------------------------------------------------------------ 1. the tree itself


def test_the_documents_this_module_judges_are_all_present():
    """A prose gate whose files have moved passes vacuously; this is what stops that."""
    assert len(DOCS) == 7
    for profile, path in DOCS.items():
        assert path.is_file(), path
    on_disk = {p.stem for p in PROFILE_DIR.glob("*.md")}
    assert on_disk == {name.lower() for name in PROFILES}


@pytest.mark.parametrize("profile", PROFILES)
def test_every_profile_carries_every_required_heading_in_order(profile):
    """§113's list, and the order is checked because a profile is read top to bottom."""
    assert _headings(profile) == list(REQUIRED_HEADINGS), (
        f"{DOCS[profile].name} has {_headings(profile)}")


@pytest.mark.parametrize("profile", PROFILES)
def test_no_required_section_is_left_empty(profile):
    """A heading with nothing under it is the shape a stub takes when it is called complete."""
    thin = [h for h in REQUIRED_HEADINGS if len(_section(profile, h).split()) < 25]
    assert not thin, f"{DOCS[profile].name}: {thin} say almost nothing"


@pytest.mark.parametrize("profile", PROFILES)
def test_every_profile_declares_its_own_version_and_the_specifications(profile):
    """§48: each profile declares 0.1.0 independently, and the SC-OES version beside it."""
    block = _section(profile, "Version")
    assert f"profile:         {profile}" in block
    assert "profile_version: 0.1.0" in block
    assert f"sc_oes_version:  {SC_OES_VERSION}" in block


@pytest.mark.parametrize("profile", PROFILES)
def test_every_profile_states_a_maturity_the_vocabulary_knows(profile):
    stated = _section(profile, "Maturity").split("```text")[1].split("```")[0].strip()
    assert stated in {m.value for m in Maturity}, f"{DOCS[profile].name}: {stated!r}"


# ------------------------------------------------- 2. the profile and the registry, not a copy


@pytest.mark.parametrize("profile", PROFILES)
def test_the_types_in_scope_are_exactly_the_types_the_registry_files_under_the_profile(profile):
    listed = set(GOVERNED_ID.findall(_section(profile, "Event types in scope")))
    governed = {entry.id for entry in get_profile_event_types(profile)}
    assert listed == governed, (
        f"{DOCS[profile].name} lists {sorted(listed)}; the registry files {sorted(governed)} "
        f"under {profile}")


@pytest.mark.parametrize("profile", PROFILES)
def test_no_profile_names_a_governed_type_another_profile_owns(profile):
    """A profile that referred to another's type would be the second copy in a slower form."""
    mine = {entry.id for entry in get_profile_event_types(profile)}
    named = set(GOVERNED_ID.findall(_text(profile)))
    assert named <= mine, f"{DOCS[profile].name} names {sorted(named - mine)}"


@pytest.mark.parametrize("profile", PROFILES)
def test_the_event_class_section_names_exactly_the_classes_its_types_span(profile):
    spanned = {entry.event_class.value for entry in get_profile_event_types(profile)}
    section = _section(profile, "EventClass")
    stated = {c.value for c in EventClass if f"`{c.value}`" in section.split("\n\n")[0]}
    assert stated == spanned, (
        f"{DOCS[profile].name}'s EventClass sentence states {sorted(stated)}; its types span "
        f"{sorted(spanned)}")


@pytest.mark.parametrize("profile", PROFILES)
def test_no_line_pairs_a_governed_type_with_a_class_or_a_maturity(profile):
    """THE COPY CHECK. See this module's docstring.

    Line-scoped rather than document-scoped, and that is the whole design: every profile
    legitimately names classes in one section and identifiers in another, so a document-wide check
    would flag all seven. What must not happen is the two arriving TOGETHER — a table row, a
    bullet, a sentence — because that is a per-type restatement of a fact the registry owns.
    """
    vocabulary = [c.value for c in EventClass] + [m.value for m in Maturity]
    offenders = [f"{number}: {line.strip()[:90]}"
                 for number, line in enumerate(_text(profile).splitlines(), 1)
                 if GOVERNED_ID.search(line) and any(word in line for word in vocabulary)]
    assert not offenders, (
        f"{DOCS[profile].name} pairs a governed identifier with a class or maturity value at "
        f"{offenders}. Those belong to the registry and to ../03-event-types.md's index; a third "
        "copy is the one that goes stale")


@pytest.mark.parametrize("profile", PROFILES)
def test_every_profile_points_at_the_registry_as_the_authority(profile):
    assert "synapse_cdm/registry/sc_oes/event_types.json" in _text(profile)
    assert "second hand-authored copy" in _text(profile)


# ------------------------------------------------------------- 3. §114 — implementation status


@pytest.mark.parametrize("profile", PROFILES)
def test_every_profile_states_its_implementation_status_explicitly(profile):
    """§114: "State this explicitly." One of exactly two statuses, and never both."""
    section = _section(profile, "Implementation status")
    stated = [s for s in (PRODUCER_BACKED, SPECIFICATION_ONLY) if s in section]
    assert len(stated) == 1, f"{DOCS[profile].name}: {stated}"
    expected = PRODUCER_BACKED if profile == PRODUCER_BACKED_PROFILE else SPECIFICATION_ONLY
    assert stated[0] == expected


def test_exactly_one_profile_is_producer_backed():
    backed = [p for p in PROFILES if PRODUCER_BACKED in _section(p, "Implementation status")]
    assert backed == [PRODUCER_BACKED_PROFILE]


def test_the_producer_backed_profile_is_the_one_with_a_producer_behind_it():
    """§114 read off the CODE, not off the document that claims it.

    The adapter that emits the block is found the way `tests/test_cdm_pntmap_adapter.py` finds it
    — by looking for the construction in the registered adapters' sources — and the profile the
    registry files that adapter's governed type under is the profile that may say
    "producer-backed". A second emitting adapter, or a producer whose type moved to another
    profile, lands here rather than in a document that has quietly become an overclaim.
    """
    import inspect

    emitting = [name for name, cls in adapter.roster().items()
                if "OesMetadata(" in pathlib.Path(inspect.getfile(cls)).read_text()]
    assert emitting == ["pntmap"], emitting
    source = pathlib.Path(inspect.getfile(adapter.roster()["pntmap"])).read_text()
    emitted = set(GOVERNED_ID.findall(source))
    profiles = {entry.profile for profile in PROFILES
                for entry in get_profile_event_types(profile) if entry.id in emitted}
    assert profiles == {PRODUCER_BACKED_PROFILE}, (
        f"the one SC-OES producer emits types in {sorted(profiles)}, and {PRODUCER_BACKED_PROFILE} "
        "is the profile documented as producer-backed")


@pytest.mark.parametrize("profile",
                         [p for p in PROFILES if p != PRODUCER_BACKED_PROFILE])
def test_a_specification_only_profile_does_not_imply_an_adapter(profile):
    """§114's second clause: "Do not imply an operational adapter implementation exists."""
    # Whitespace-normalised: prose here is hard-wrapped at 100 columns, so a literal that
    # depends on where a line break falls is a test that fails on a reflow rather than on a
    # change of meaning. The same treatment `tests/test_cdm_conformance_spec.py` gives the
    # aggregate-score ban.
    section = " ".join(_section(profile, "Implementation status").split())
    assert "No adapter in this repository emits this profile's event types." in section
    assert "remains CDM Conformant without being an SC-OES semantic producer" in section
    assert "operational adapter implementation exists" in section


# --------------------------------------------------------- 4. the examples a profile cites


@pytest.mark.parametrize("profile", PROFILES)
def test_every_example_a_profile_cites_exists(profile):
    """§113 requires an "examples" section, and a citation nothing backs is the rot §141 bans."""
    cited = re.findall(r"examples/sc-oes/individual/(\S+?\.json)", _text(profile))
    assert cited, f"{DOCS[profile].name} cites no example file"
    for name in cited:
        assert (REPO / "examples" / "sc-oes" / "individual" / name).is_file(), name


@pytest.mark.parametrize("profile", PROFILES)
def test_a_profile_cites_an_example_for_each_of_its_governed_types(profile):
    cited = set(re.findall(r"examples/sc-oes/individual/(\S+?)\.json", _text(profile)))
    governed = {entry.id for entry in get_profile_event_types(profile)}
    assert cited == governed, (
        f"{DOCS[profile].name} cites {sorted(cited)} and owns {sorted(governed)}")


# ---------------------------------------------------- 5. what a profile does NOT yet declare


@pytest.mark.parametrize("profile", SPECIFICATION_ONLY_PROFILES)
def test_every_specification_only_profile_says_it_declares_no_rules_of_its_own(profile):
    """The positive half of the sentence `tests/test_cdm_conformance_spec.py` guards.

    That module asserts the profile still says a D assessment has no rules to check. This one
    asserts the profile says WHY — that it declares no conformance rules of its own, and that its
    SHOULDs are conventions rather than rules. The two together are what make the `SKIP` an
    argued position instead of an unfinished one: a profile that acquired a rule would have to
    delete this sentence, and deleting it fails here.
    """
    section = _section(profile, "Conformance")
    assert "declares no conformance rules of its own in v0.1.0" in section
    assert "convention marked SHOULD" in section
    assert "writes the rules and the check that" in section


def test_the_executable_profile_states_the_rule_the_registry_declares_for_it():
    """§17's first clause, over the document rather than over the registry pair.

    The rule count is DERIVED from the packaged registry, so a second rule added there with no
    sentence written here fails on the count rather than on somebody noticing.
    """
    section = _section(EXECUTABLE_PROFILE, "Conformance")
    rules = get_profile(EXECUTABLE_PROFILE).rules
    assert len(rules) == 1, rules
    assert "declares one executable conformance rule of its own" in section
    assert "**Event membership.**" in section
    assert "declares no conformance rules of its own in v0.1.0" not in section
    assert "synapse_cdm/registry/sc_oes/profiles.json" in section


@pytest.mark.parametrize("profile", PROFILES)
def test_no_profile_uses_a_normative_must_for_a_rule_it_does_not_check(profile):
    """A profile may spell an obligation in the reserved word only for a rule the tool checks.

    Two exemptions and both are checked rather than assumed. The ban on becoming a second copy
    of the registry is a rule about the DOCUMENT and not about an event, and every profile
    carries it. The executable profile additionally states its own rule, which is the one case
    where `MUST` is what the word is for — and `test_cdm_conformance_spec.py` is what stops that
    sentence existing without a check behind it.
    """
    allowed = ("second hand-authored copy", "registry is right")
    if get_profile(profile).rules:
        allowed += ("MUST carry an `oes.type_id`",)
    lines = [line.strip() for line in _text(profile).splitlines() if re.search(r"\bMUST\b", line)]
    assert all(any(phrase in line for phrase in allowed) for line in lines), (
        f"{DOCS[profile].name} states a MUST outside its checked rules: {lines}")


# ------------------------------------------- 6. §17 — the document and the packaged metadata
#
# The two may not silently disagree on profile ID, version, maturity, implementation status or
# governed event-type membership. Membership is already one fact in both directions — the
# registry refuses a projection that disagrees with `event_types.json`, and
# `test_the_types_in_scope_are_exactly_the_types_the_registry_files_under_the_profile` above
# reads the document against the same authority — so what is added here is the other four.


@pytest.mark.parametrize("profile", PROFILES)
def test_the_document_and_the_packaged_record_agree_on_identity_and_state(profile):
    record = get_profile(profile)
    version_block = _section(profile, "Version")
    assert f"profile:         {record.id}" in version_block
    assert f"profile_version: {record.version}" in version_block
    stated_maturity = _section(profile, "Maturity").split("```text")[1].split("```")[0].strip()
    assert stated_maturity == record.maturity.value
    status_block = _section(profile, "Implementation status")
    spelled = {"PRODUCER_BACKED": "producer-backed",
               "SPECIFICATION_ONLY": "specification-only"}[record.implementation_status.value]
    assert f"Implementation status:        {spelled}" in status_block, (
        f"{DOCS[profile].name} does not state implementation status {spelled}, which is what "
        f"synapse_cdm/registry/sc_oes/profiles.json carries for it")
    marker = PRODUCER_BACKED if spelled == "producer-backed" else SPECIFICATION_ONLY
    assert marker in status_block


@pytest.mark.parametrize("profile", PROFILES)
def test_the_document_and_the_packaged_record_agree_on_whether_rules_exist(profile):
    record = get_profile(profile)
    status_block = _section(profile, "Implementation status")
    expected = "available" if record.rules else "not defined in 0.1.0"
    assert f"Executable Dimension D rules: {expected}" in status_block, (
        f"{DOCS[profile].name} does not state that its executable dimension D rules are "
        f"{expected!r}, which is what the packaged registry says")


@pytest.mark.parametrize("profile", PROFILES)
def test_the_document_and_the_packaged_record_agree_on_membership(profile):
    """§17's last clause. There is ONE list of event types and this reads the document against it."""
    listed = set(GOVERNED_ID.findall(_section(profile, "Event types in scope")))
    assert listed == set(get_profile(profile).event_types)
