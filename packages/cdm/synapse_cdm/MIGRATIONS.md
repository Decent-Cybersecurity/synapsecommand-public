# CDM schema versioning and migrations

Every serialised object carries `schema_version`. A consumer reading an object off a queue has
no other way to know which shape it is holding, and "we will add versioning when we need it"
means adding it at the moment two incompatible producers are already in the field.

**`schema_version` is not the package's version.** This document governs the first: the wire
contract, carried in every object, bumped by the table below. The distribution on PyPI carries
the second — ordinary semver over the Python surface — and the two are allowed to diverge,
because the section "Adapters that landed with no schema change" is twelve entries long and
every one of them would have been a package release. Both are declared in `version.py`, which is the
one place the distinction is argued; nothing here restates it. They were both `1.0.0` at first
release, by coincidence of two first releases, and they parted at the 1.1.0 release below:
`PACKAGE_VERSION` is `1.2.1` and `SCHEMA_VERSION` is `1.0.0`.

## What each bump means

| Bump | Change | Consumer impact |
|---|---|---|
| **MAJOR** | a field removed or renamed; a type narrowed; an enum member removed; an optional field made required; the `ids.NAMESPACE` changed | breaks readers; needs a migration entry below and a coordinated deployment |
| **MINOR** | an optional field added; an enum member added; a payload model registered; validation relaxed | old readers keep working, old data keeps validating |
| **PATCH** | descriptions, error-message wording, docs | none |

`version.compatible(written_with, read_by)` accepts the same major, **including a minor from
the future** — a 1.0.0 reader accepts a 1.2.0 object, because MINOR additions are optional by
definition and the alternative is a fleet that stops ingesting the moment one adapter is
upgraded. It refuses a different major outright.

Renaming a field is two releases, never one: add the new name in a MINOR, populate both, then
remove the old one in the next MAJOR. One release that renames is an outage for every consumer
that has not been redeployed in the same hour.

## Changing the schema — the procedure

1. Edit the Pydantic model. It is the single source; the files in `/schemas` are a publication.
2. Bump `version.SCHEMA_VERSION` per the table above.
3. Re-export: `python -m synapse_cdm.schemas --out schemas`. `tests/test_cdm_schemas.py` fails
   the build if you forget, and `--check` is the CI form.
4. Add an entry below, naming the reason — not just the change.
5. Re-run every adapter's golden files and **read the diffs**:
   `python -m synapse_cdm.harness --adapter <name> --update-golden`, once per shipped adapter.
   A golden file updated without being read is how a defect becomes the expectation.
6. If a documented gap in `FORMAT_COVERAGE.md` is now closed, close it there too —
   `tests/test_cdm_format_coverage.py::test_the_documented_gaps_are_still_gaps` fails
   deliberately when a gap field appears, so the document cannot silently disagree with the
   code.

## Releasing the package — the procedure

A release is a **tag plus an artefact**, and this section exists so that the second release
follows a written procedure rather than the first one's memory. It governs `PACKAGE_VERSION`.
A `schema_version` bump is always at least a package MINOR and therefore always a release; the
reverse does not hold, and most releases will change no schema at all.

### What a release requires

Five conditions, none of them satisfiable by assertion. The **Actor** column is who or what checks
each one. Four of the five now have a machine in it, and the one that does not says so rather than
pretending otherwise.

**Condition 5 was added after the release that needed it.** The 1.2.1 round was specified as
**1.3.0** and renumbered itself from the diff — the ruling is `PUBLICATION.md` entry 10 — and the
four conditions above were all satisfied by 1.3.0. Each of them checks that a number is stated
*consistently*: the tag names the tree's `PACKAGE_VERSION`, the notes describe that version, the
package source that moved is written down. None of them asks whether the number is the RIGHT one.
A version number is the one claim in a release that can never be corrected — a PyPI filename is
permanent — and until this condition existed it was the only claim in a release with no machine
behind it.

| # | Condition | Actor |
| --- | --- | --- |
| 1 | the suite is green | the workflow, on every dispatch and every tag |
| 2 | the harnesses are green, one against the installed wheel | the workflow |
| 3 | the tag names its tree's `PACKAGE_VERSION` | the workflow, and it knows the tag |
| 4 | the notes are derived, not remembered | **a person.** The workflow prints the derivations |
| 5 | the number is derived from the packaged diff | `gates/bump_derivation.py`, in the suite |

1. **The suite is green**, from the repository root, with the count recorded in the commit.
   `.github/workflows/publish.yml` runs it. Note that a CI green is not identical to a
   maintainer's: the pinned specification documents are gitignored, so a fresh clone skips the
   tests that read them, and the workflow prints the skip list with `-rs` rather than reporting
   one number.

   **CONDITION 1'S LOCAL PRE-CHECK IS A FRESH-CLONE SUITE RUN**, added 2026-09-04 after the
   release that needed it. The sentence above already knew that a CI green and a maintainer's are
   different runs, and it stopped one step short of what follows from that: **a maintainer green
   is not evidence for this condition, because this condition is read by a clone.** So the
   pre-check is a clone, and it stands beside condition 5's `--mutation-check` in the block below
   — the two things this repository can check locally before a tag exists.

   1.5.0's first tag is the case that put it here. `tests/test_cdm_pins.py` carried a guard
   asserting the pin corpus was on disk, which is right on the tree that wrote it and is the
   ORDINARY state of a clone, where `.gitignore` keeps every pinned document out of the index.
   Run 33875771133 failed condition 1 on that one test at the tag, from a commit whose own suite
   was green — the re-tag round in the 1.5.0 section carries it. The gitignored corpus is the
   WHOLE of the difference between the two trees, so a clone is the only tree that can see a
   defect of that class, and nothing in this procedure had ever asked anybody to make one. It
   stays a PRE-CHECK and does not become a sixth condition: the workflow checks condition 1
   already, and what a clone changes is only whether the finding arrives before the tag or after
   it.
2. **All fourteen harnesses are green**, and at least one of them run against the INSTALLED
   wheel rather than the source tree — `gates/wheel_install.py` does both halves and is the gate
   this condition means. The workflow runs it with `--mutation-check`, so the release build also
   proves the gate can still fail. Neither the count nor the roster is written down anywhere that a
   fifteenth adapter would not update: the gate derives it, after a written-down ten replayed ten
   of twelve adapters and reported the ten as a pass. **THE PREDICTION IN THIS SENTENCE CAME TRUE
   AND THE SENTENCE STILL NEEDED EDITING**: it said a fourteenth adapter would update the count
   wherever it was written down, `stanag4586` is the fourteenth, and the number in this very
   condition is one of the places — updated by the stale-count sweep, which is the mechanism the
   sentence was describing rather than an exception to it.
3. **The tag names the package version of the tree it points at.** `v1.0.0` on a tree whose
   `PACKAGE_VERSION` is `1.0.1` is a release nobody can reproduce, and
   `tests/test_cdm_release.py` re-derives this for every tag in history rather than for the one
   being made. The workflow checks the tag being made, which is the one case history cannot cover,
   and it is stricter there than a person is: it reads the ref it was triggered by instead of
   trusting what was typed.
4. **The notes are derived, not remembered.** Every claim in a release's notes has to be
   readable off the tree at the tag: the adapter roster from `adapter.discover()`, the fixture
   count from the harness, the schema list from `python -m synapse_cdm.schemas`. Notes written
   from memory are how a release claims a capability that slipped. **This one stays a person's**,
   and the workflow cannot take it: "derived" is a claim about what the writer read, and a
   generated file does not satisfy it. What the workflow does is print all three derivations into
   the run summary, so the notes are copied off a run rather than recalled.
5. **The number is derived from the packaged diff, not from the brief.**
   `gates/bump_derivation.py` classifies the diff over the distribution's own contents between the
   previous tag and the tree being released, against `version.py`'s `PACKAGE_VERSION` table, and
   refuses a number that **exceeds** or **undershoots** what the diff proves. It is a suite member
   as well as a command — it needs git and nothing else, no network and no credential — so unlike
   conditions 1 through 3 it does not wait for a tag. Run it before typing a number, beside
   condition 1's fresh-clone pre-check, which is the other check that does not wait for one:

   ```bash
   python gates/bump_derivation.py --mutation-check              # condition 5, this one
   git clone --no-local . /tmp/precheck && \
     (cd /tmp/precheck && pytest -q -rs)                         # condition 1, on the tree CI reads
   ```

   **Where the table needs judgment the gate refuses rather than guessing.** Its PATCH row ("a
   translation fix, a message, a docstring. No surface change") and its MAJOR row ("an importable
   name is removed or its **meaning** changes") both reach a function whose body moved and whose
   name did not, and no diff separates them — "the meaning changed" is a claim about intent. The
   gate names the unit and stops. A person then rules it, in this file, in the section describing
   the arc, as `**Bump ruling.** ` followed by the unit in backticks, a dash, and the category:

   ```
   **Bump ruling.** `synapse_cdm/harness.py:main` — PATCH: the wording of a refusal message.
   ```

   The gate reads those and refuses a ruling that outlives its case, so the mechanism cannot decay
   into a list of exemptions nobody re-derives. **Retroactively, it derives the number every one of
   this package's releases actually shipped** — 1.1.0 and 1.2.0 as MINOR, 1.2.1 as PATCH — having
   been told none of them; `tests/test_cdm_bump_derivation.py` asserts that over the tags.

### The sequence

```bash
git tag -a v1.5.0 -m "..."                           # annotated, never lightweight
git push origin main --follow-tags                   # this is the whole of it
```

The tag is the release. `.github/workflows/publish.yml` takes it from there: conditions 1, 2 and 3,
`twine check --strict`, then a wait for a reviewer on the `pypi` environment, then an upload over
OIDC with no token anywhere in the process. Condition 4's derivations are in the run summary; the
GitHub release itself is still made by a person, with `gh release create`, from those.

The tag is **annotated** because a release is a statement by a person: an annotated tag carries a
tagger, a date and a message, and `git describe` prefers it. A lightweight tag is a branch name
that does not move, and it records nobody — and the workflow now refuses one outright rather than
leaving that to whoever reads this paragraph.

### The manual fallback — NOT the procedure

For the case where the workflow itself is broken. It is written down because an undocumented
fallback gets improvised under pressure, which is worse; it is marked because the previous version
of this document presented it as *the* procedure and it is not one any more.

```bash
pytest -q                                            # condition 1
python gates/wheel_install.py --mutation-check       # condition 2 and the artefact
python -m synapse_cdm.schemas --check --out schemas  # CURRENT
python -m twine check --strict packages/cdm/dist/*
python -m twine upload packages/cdm/dist/*           # needs a token this repository has retired
```

Two things are lost by taking this path, and both are the reason it is a fallback:

* **there is no record.** No Actions run, no artefact, no log of which gate output preceded the
  upload. `PUBLICATION.md` entry 5 is what that looks like a month later — it is the record of the
  1.0.0 upload done this way, and of the step in its own sequence that nobody noticed had been
  skipped until a stranger looked the package up on TestPyPI and got a 404;
* **the credential it needs does not exist.** The API token used for 1.0.0 was **revoked** on
  2026-08-26 — by revocation rather than by disuse, because an unused token is one that still
  works. `PUBLICATION.md` entry 6 records it. So this path cannot simply be taken: it requires
  issuing a NEW token first, and issuing a token to work around a broken workflow is how the
  workflow stays broken. Fix the workflow. That the fallback now costs something is deliberate —
  it is written down so nobody improvises it, not so it stays convenient.

### What the workflow does, and what it still cannot

Publishing to PyPI is automated. `.github/workflows/publish.yml` runs on a pushed tag matching
`v*`: it builds the sdist and wheel, runs conditions 1, 2 and 3 above against what it built, and
then — only after those pass, only for a tag, and only once a required reviewer approves the `pypi`
environment — uploads over OIDC with no token, password or secret anywhere in the file. It first
did so for 1.1.0 on 2026-08-26, and the long-lived API token used for 1.0.0 was revoked the same
day, so **OIDC is now the only way to upload to this project.** `PUBLICATION.md` entry 6 carries
the run, the artefact digests, and the four values registered on pypi.org that the upload is matched
against — if any of them stops matching the upload is refused, and there is deliberately no
credential to fall back to.

Until this round the section said the opposite, on the grounds that automating an upload before
there was anything to run it on would be inventing a mechanism. There is something to run it on
now, so the claim is retired rather than qualified — and it is not quoted back here, because the
test that holds this prose to the tree forbids the old wording as a *substring* and cannot tell an
assertion from a quotation of a retired one. That is the right way round: a gate that accepted the
false sentence inside quotation marks would accept it anywhere. The superseded text is in git and
in `PUBLICATION.md` entry 5, which is where a record of what was believed when belongs.

Three things are still deliberately a person's:

* **the tag.** Nothing creates it. The workflow is triggered by one and refuses a lightweight tag
  outright, on the grounds this document already gives — a lightweight tag records nobody;
* **the approval.** The `pypi` environment carries required reviewers, so the upload waits for a
  human. A PyPI upload cannot be undone and its filename can never be reused, which makes it the
  only irreversible step in a release; the ruling, and the case against it, are in ledger entry 6;
* **condition 4, the notes.** A workflow cannot satisfy "derived, not remembered" by generating a
  document — the condition is about what the person writing the notes read. What the workflow does
  instead is print the derivations into its run summary, so the notes can be copied off a run.

`PUBLICATION.md` ledger entry 5 carries the sequence that was followed for 1.0.0 by hand, what was
measured off the index afterwards, and which step of it did not run.

## History

### 1.5.0 — 2026-09-04 — the ST 0102.12 security row set ships, and the first pinned document that is not a PDF

**This section carried the pending-arc heading and this release absorbed it** — the token itself is elided here, as it has been at every roll since the third one recreated the carrier defect, because prose that spells it leaves the file answering four release gates in the affirmative with no such section present.

**What moved inside the distribution: 92 files.** The largest arc this record has carried, and
the shape is three rounds': **park 2 closed by writing the row set MISB ST 0102.12 supports**,
which took a new module, two modified ones, seven new fixture payloads with their twins and
goldens, and every existing KLV golden re-generated because two attribute keys now ride on every
object this adapter emits. The count and the set are `gates/bump_derivation.py`'s, re-derived
**after** this record was written rather than before it — the fixed point the 1.4.0 arc's own
repair note insists on, and the reason the number above is not a quotation of a derivation that
has since moved. **IT READ 91 AT `3b5a5dd` AND READS 92 HERE**, `version.py` having joined the
arc it closes: it is a distribution file, so the bump that ends an arc is part of the arc. That is a
property of every release this file records and the 1.3.0 section states it once for all of them.

**AND TWO TRUE FILE COUNTS SIT ONE APART AT A RELEASE COMMIT, WHICH IS WORTH A SENTENCE BECAUSE THE
1.4.1 RECORD STATED ONLY ONE OF THEM.** The number above is the release gate's moved set — the
package files that differ from the previous tag, committed or in the working tree — and it is
**92**. `gates/bump_derivation.py`'s own SIGNAL set spans **91** of them, and the missing one is
`version.py`: the gate skips `version.py:PACKAGE_VERSION` by name as *the declaration under
judgement*, because a gate that read the number it is judging as evidence for that number would be
arguing in a circle. So the file moved and produced no signal. The same off-by-one is in the 1.4.1
arc — twelve moved files, fourteen signals over eleven — and was recorded there as one figure.

**THAT FIGURE READ 66 UNTIL 2026-09-04 AND THE PARAGRAPH ABOVE STILL DESCRIBES THE PARK 2 ROUND**,
which is deliberate: the sentence names the shape of the arc's largest round and the arc has since
gained two more. The surface round moved the count by nothing and the text-pins round moved it by
twenty-five, each recorded in its own paragraph below rather than by editing this one.

**THE SURFACE ROUND OF 2026-09-04 IS THE ARC'S SECOND ROUND AND IT MOVES THE COUNT BY NOTHING.**
It touched eight distribution files and **all eight were already in the 66** — the two shipped
documents, the fixture README, `klv_pin.json`, `build_fixtures.py` and three modules — plus the
34 goldens the park 2 round had already re-generated. **So the set is unchanged and the number
is unchanged**, re-derived after this record was written for the same reason the paragraph above
gives. What the round changes is not WHICH files moved but **what the objects say**: see *The
surface round* below, which is the section the 1.5.0 notes have to be derived from, because a
consumer's `security_metadata_basis` goes from six kilobytes of prose to a token and six
pointers.

**THE TEXT-PINS ROUND OF 2026-09-04 IS THE ARC'S THIRD ROUND AND IT MOVES THE COUNT FROM 66 TO
91.** Twenty-five files it touched were NOT already in the 66: `packages/cdm/pyproject.toml`, and
twenty-four fixture files — six new payloads with their parsed twins and their two goldens each.
The number and the set are `gates/bump_derivation.py`'s, re-derived **after** this record was
written, which is the fixed point the 1.4.0 arc's repair note insists on and the third round in
this arc to honour it.

**WHAT THE ROUND ADDED TO THE DISTRIBUTION, NAMED:**

- `security_object_country_codes_big_endian_bom_is_honoured_and_stripped.klv` + `security_object_country_codes_big_endian_bom_is_honoured_and_stripped.parsed.json`, with goldens `security_object_country_codes_big_endian_bom_is_honoured_and_stripped.cdm.json` and `security_object_country_codes_big_endian_bom_is_honoured_and_stripped.parsed.cdm.json`
- `security_object_country_codes_little_endian_bom_is_honoured_with_an_advisory.klv` + `security_object_country_codes_little_endian_bom_is_honoured_with_an_advisory.parsed.json`, with goldens `security_object_country_codes_little_endian_bom_is_honoured_with_an_advisory.cdm.json` and `security_object_country_codes_little_endian_bom_is_honoured_with_an_advisory.parsed.cdm.json`
- `security_object_country_codes_with_no_bom_are_big_endian_by_two_documents.klv` + `security_object_country_codes_with_no_bom_are_big_endian_by_two_documents.parsed.json`, with goldens `security_object_country_codes_with_no_bom_are_big_endian_by_two_documents.cdm.json` and `security_object_country_codes_with_no_bom_are_big_endian_by_two_documents.parsed.cdm.json`
- `security_object_country_codes_multiple_are_split_on_the_semicolon.klv` + `security_object_country_codes_multiple_are_split_on_the_semicolon.parsed.json`, with goldens `security_object_country_codes_multiple_are_split_on_the_semicolon.cdm.json` and `security_object_country_codes_multiple_are_split_on_the_semicolon.parsed.cdm.json`
- `security_object_country_codes_at_an_odd_octet_count_is_refused.klv` + `security_object_country_codes_at_an_odd_octet_count_is_refused.parsed.json`, with goldens `security_object_country_codes_at_an_odd_octet_count_is_refused.cdm.json` and `security_object_country_codes_at_an_odd_octet_count_is_refused.parsed.cdm.json`
- `security_object_country_codes_with_a_lone_surrogate_is_refused.klv` + `security_object_country_codes_with_a_lone_surrogate_is_refused.parsed.json`, with goldens `security_object_country_codes_with_a_lone_surrogate_is_refused.cdm.json` and `security_object_country_codes_with_a_lone_surrogate_is_refused.parsed.cdm.json`

`pyproject.toml` is the twenty-fifth, and it is the one worth a sentence: its
`exclude-package-data` globs named `.pdf` and nothing else, so the newly pinned
`fixtures/klv/spec/rfc2781.txt` — a document this repository never redistributes — matched
`fixtures/**/*` and **would have shipped inside the wheel**, invisible to every check that reads
`git ls-files` because `.gitignore` keeps it out of the index. `tests/test_cdm_packaging.py`
caught it by name on the first run after the file landed, because that test asks what the globs
SELECT rather than what they say. See *The text-pins round* below.

**THREE shipped documents** — `MIGRATIONS.md`, `FORMAT_COVERAGE.md` and `fixtures/klv/README.md`.
**ONE pin record**, `klv_pin.json`, which gained `tag_table_st_0102_12` and
`parks.the_ones_that_closed.park_2`. **FOUR modules**, of which **one is new**:

`build_fixtures.py`, `klv_security_codec.py`, `klv_uas_codec.py`, `stanag4609.py`

`klv_security_codec.py` is the new one — the MISB ST 0102.12 element layer — and it is what makes
this arc **MINOR**; `build_fixtures.py` gained the seven fixture specs; `klv_uas_codec.py` gained a
nested-set table and one field on `DecodedPacket`; `stanag4609.py` carries the decoded elements into
`Entity.attributes`.

**SEVEN new fixture payloads:**

`no_security_local_set_is_unlabelled_not_unclassified.klv`,
`security_classification_outside_the_enumeration_carries_no_label.klv`,
`security_local_set_complete_from_the_element_rules.klv`,
`security_local_set_minimal_required_only.klv`,
`security_local_set_partial_is_carried_as_partial.klv`,
`security_required_element_at_a_forbidden_length_is_refused.klv`,
`security_uint16_that_the_format_cannot_carry_is_refused.klv`

**SEVENTEEN parsed twins** — the seven new ones and the ten existing ones, every one of which
gained a `security` key stating whether its packets carry item 48, because §6.5 makes that a claim
rather than a silence:

`a_checksum_that_does_not_validate_is_flagged_not_refused.parsed.json`,
`an_unwitnessed_tag_is_skipped_and_the_packet_translates.parsed.json`,
`length_divergence_at_a_required_length.parsed.json`, `mandatory_items_only.parsed.json`,
`no_security_local_set_is_unlabelled_not_unclassified.parsed.json`,
`over_recommended_max_length_is_an_advisory.parsed.json`,
`security_classification_outside_the_enumeration_carries_no_label.parsed.json`,
`security_local_set_complete_from_the_element_rules.parsed.json`,
`security_local_set_minimal_required_only.parsed.json`,
`security_local_set_partial_is_carried_as_partial.parsed.json`,
`security_required_element_at_a_forbidden_length_is_refused.parsed.json`,
`security_uint16_that_the_format_cannot_carry_is_refused.parsed.json`,
`special_values_are_signals_and_not_measurements.parsed.json`,
`two_packets_one_payload_are_two_statements.parsed.json`,
`witnessed_set_from_the_documents_own_examples.parsed.json`,
`zero_length_item_is_an_explicit_unknown.parsed.json`,
`zero_length_item_on_a_required_item_is_a_defect.parsed.json`

**THIRTY-FOUR goldens**, fourteen new and twenty regenerated:

`a_checksum_that_does_not_validate_is_flagged_not_refused.cdm.json`,
`a_checksum_that_does_not_validate_is_flagged_not_refused.parsed.cdm.json`,
`an_unwitnessed_tag_is_skipped_and_the_packet_translates.cdm.json`,
`an_unwitnessed_tag_is_skipped_and_the_packet_translates.parsed.cdm.json`,
`length_divergence_at_a_required_length.cdm.json`,
`length_divergence_at_a_required_length.parsed.cdm.json`, `mandatory_items_only.cdm.json`,
`mandatory_items_only.parsed.cdm.json`,
`no_security_local_set_is_unlabelled_not_unclassified.cdm.json`,
`no_security_local_set_is_unlabelled_not_unclassified.parsed.cdm.json`,
`over_recommended_max_length_is_an_advisory.cdm.json`,
`over_recommended_max_length_is_an_advisory.parsed.cdm.json`,
`security_classification_outside_the_enumeration_carries_no_label.cdm.json`,
`security_classification_outside_the_enumeration_carries_no_label.parsed.cdm.json`,
`security_local_set_complete_from_the_element_rules.cdm.json`,
`security_local_set_complete_from_the_element_rules.parsed.cdm.json`,
`security_local_set_minimal_required_only.cdm.json`,
`security_local_set_minimal_required_only.parsed.cdm.json`,
`security_local_set_partial_is_carried_as_partial.cdm.json`,
`security_local_set_partial_is_carried_as_partial.parsed.cdm.json`,
`security_required_element_at_a_forbidden_length_is_refused.cdm.json`,
`security_required_element_at_a_forbidden_length_is_refused.parsed.cdm.json`,
`security_uint16_that_the_format_cannot_carry_is_refused.cdm.json`,
`security_uint16_that_the_format_cannot_carry_is_refused.parsed.cdm.json`,
`special_values_are_signals_and_not_measurements.cdm.json`,
`special_values_are_signals_and_not_measurements.parsed.cdm.json`,
`two_packets_one_payload_are_two_statements.cdm.json`,
`two_packets_one_payload_are_two_statements.parsed.cdm.json`,
`witnessed_set_from_the_documents_own_examples.cdm.json`,
`witnessed_set_from_the_documents_own_examples.parsed.cdm.json`,
`zero_length_item_is_an_explicit_unknown.cdm.json`,
`zero_length_item_is_an_explicit_unknown.parsed.cdm.json`,
`zero_length_item_on_a_required_item_is_a_defect.cdm.json`,
`zero_length_item_on_a_required_item_is_a_defect.parsed.cdm.json`

**The twenty regenerated goldens are the arc's own evidence and not noise.** Every object this
adapter emits now carries `attributes.security_metadata_basis`, including the objects of packets
that carry no item 48 — which is exactly what MISB ST 0102.12 §6.5 requires the output to say, so a
golden that did NOT move would mean the §6.5 clause had not reached it.

**The arc derives MINOR, so the floor is 1.5.0**, and `gates/bump_derivation.py` derived it with no
human ruling required for the decision itself: `klv_security_codec.py` is a new importable module
and `fixtures/klv/`'s seven payloads extend a fixture set, both on `version.py`'s MINOR list. That
is park 5's shape rather than park 11's — the gate derives the kind by itself when the artefact has
a public name. **`SCHEMA_VERSION` is unmoved at 1.0.0** and had to be: `Entity.attributes` is
`additionalProperties: true`, so carrying seventeen security elements into it adds no field to any
schema, and `python -m synapse_cdm.schemas --check --out schemas` reports CURRENT against an empty
`schemas/` diff. **THIS SECTION IS 1.5.0**, and the sentences that stood here while it was pending said the opposite:
nothing in it was in any release and the version a reader who ran `pip install synapse-cdm`
actually had was 1.4.1. The release round below is what changed that — `PACKAGE_VERSION` moved to
**1.5.0**, the tag names it, and a reader who installs the package receives everything described
above.

**EIGHT units the gate REFUSED to classify, and all eight are modifications in place.** The gate
names them rather than defaulting them to PATCH, which is the refusal that keeps its other two
honest. Each is ruled below.

**Bump ruling.** `synapse_cdm/adapters/klv_uas_codec.py:DecodedPacket` — MINOR: a `NamedTuple`
gained a trailing field, `security`, with a default of `None`. Existing code keeps working, which
is the MINOR row's own governing clause: the field is appended last so every positional unpack and
every index is unchanged, and a caller that never mentions it sees the tuple it always saw. It is
an ADDITION to a declared surface and not a modification of one — the modification is in the
statement that fills it, ruled next.

**Bump ruling.** `synapse_cdm/adapters/klv_uas_codec.py:decode_packet` — MINOR: the function now
decodes ST 0601 item 48 through `klv_security_codec` where it previously appended 48 to
`unknown_tags` and carried its octets. **PATCH is refused** on its own row's terms — "a translation
fix, a message, a docstring" — because nothing this function emitted was WRONG: parking an
undecoded item's octets is what `ST 0107.3-04` requires of a decoder that does not know a tag, and
the octets were carried losslessly. The change makes the function assert something it never
asserted, which is new emitted content and not a corrected value. **MAJOR is refused** because no
importable name is removed and no signature moves. This is the shape park 11's drafted ruling
argues at length and the same conclusion, reached by a different item.

**Bump ruling.** `synapse_cdm/adapters/stanag4609.py:Stanag4609Adapter` — MINOR: the adapter emits
`attributes.security_metadata_basis` on every object and `attributes.security_metadata` on objects
whose packet carried item 48, and `_agree` gained a cross-check that a fixture's stated security
block matches what its own octets produce. Existing code keeps working — no import breaks, no
signature moves, every object still validates at `SCHEMA_VERSION` 1.0.0 — and what moves is what
the objects SAY. 1.2.0 is the precedent: a structured annotation added to shipped output was ruled
"a new kind of output" rather than a fix.

**Bump ruling.** `synapse_cdm/adapters/stanag4609.py:_parsed_packet` — MINOR: the parsed twin
gained a `security` key. A private name by the leading underscore, which would ordinarily make it
PATCH by the gate's own private-name rule — but this function's return value is written to disk as
a `.parsed.json` fixture and read back by the harness, so its shape is a published artefact whatever
its name's visibility. Ruled on what it produces rather than on how it is spelled.

**FOUR RULINGS ON ONE INSERTION, AND SAYING SO IS THE POINT.** The four below name
`<statement 6>` through `<statement 9>` of `synapse_cdm/adapters/stanag4609.py`. **They are four
`from ... import ...` statements, and none of them changed.** What happened is that this round
inserted one import — `klv_security_codec as security` — at index 6, and the gate names an
unnamed top-level statement by its POSITION, so the four imports after it were renamed and read as
modified. **One addition reported as four modifications.** That is a property of positional unit
naming and not a defect in this arc: the gate refuses rather than guesses, and refusing four times
for one cause is the cost of a naming scheme that cannot be fooled into silence. It is recorded
here so the next round that inserts a module-level statement meets the explanation before the
refusals.

**Bump ruling.** `synapse_cdm/adapters/stanag4609.py:<statement 6>` — PATCH: an `import` statement,
renamed by position when one import was inserted above it. No importable name of this module is
added, removed or changed in meaning by an import's index.

**Bump ruling.** `synapse_cdm/adapters/stanag4609.py:<statement 7>` — PATCH: the same, one position
further down.

**Bump ruling.** `synapse_cdm/adapters/stanag4609.py:<statement 8>` — PATCH: the same.

**Bump ruling.** `synapse_cdm/adapters/stanag4609.py:<statement 9>` — PATCH: the same.

**The parks arithmetic after this round: SIX closed and SEVEN open.** `gates/parks_table.py` reads
thirteen rows, six closed — parks 1, 2, 4, 8, 9 and 13 — and seven open: parks 3, 5, 6, 7, 10, 11
and 12. **Park 2 is the first park here closed without acquiring anything**: its document had been
held since 2026-08-26 and what was missing was the artefact, which is the state park 2 was this
table's own precedent FOR. The delegation count does not move either — fourteen delegations in
scope and **nine** held, unchanged, because this round fetched nothing.

#### The re-tag round, 2026-09-04 — the tag moved to a fix a clone could see and the maintainer tree could not, and no artefact was ever at risk

**THE TAG MOVED. IT WAS NOT SUPERSEDED, AND THE DIFFERENCE IS THE WHOLE RULING.** `v1.5.0` was
pushed at `bf95b77` and run **33875771133** failed **condition 1** — one test, on a tree that was
green when the commit was made. The standing rule that a remote tag is never deleted was set
aside for this case only, on two conditions taken as readings rather than assumed, and both were
re-taken at the top of this round:

* **PyPI does not serve 1.5.0.** `GET https://pypi.org/pypi/synapse-cdm/1.5.0/json` → **404** at
  `2026-09-04T15:00:45Z`; `/pypi/synapse-cdm/json` lists 1.0.0 through 1.4.1 and stops. The
  publish job never ran — the build job failed at its fifth step and the publish job is reported
  `skipped` — so the one irreversible step in a release was never reached;
* **no GitHub Release exists for `v1.5.0`.** `gh release view v1.5.0` → *release not found* at
  `2026-09-04T15:00:50Z`; the newest Release is `v1.4.1`.

The procedure says which steps are revocable and which are not, in *What the workflow does*: the
tag is a person's and nothing creates it, the approval is a person's, **and a PyPI upload cannot
be undone and its filename can never be reused**. A tag moves. A Release deletes. An upload does
neither, and there was no upload. **So this round is a re-tag and not a 1.5.1**: the number is
still the gate's, over the same arc, and the fix is outside the distribution.

**WHAT FAILED, AND WHY A GREEN MAINTAINER TREE COULD NOT SEE IT.**
`tests/test_cdm_pins.py::test_a_stream_or_a_provenance_capture_under_a_pin_path_is_still_refused`
opened with `assert disk, "the disk half is empty, so every assertion below is vacuous"`. On a
maintainer tree that guard is exactly right: the pin corpus is held, so an empty set can only mean
the glob broke. On a fresh clone the empty set is the ORDINARY state, because `.gitignore:42` and
its `*.txt` sibling keep every pinned document out of the index — which is the fresh-clone
boundary this module's own docstring states and the sibling at `test_every_pin_is_present_intact_
and_untracked` obeys with a `pytest.skip`. **The test was right about the tree it was written on
and wrong about the tree condition 1 is read by.** CI: `1 failed, 3468 passed, 71 skipped`. The
same tree at `bf95b77`, with the documents present: `3532 passed, 8 skipped`.

`git log -S` names one commit for that test — **`3b5a5dd`**, the text-pins round — so the release
commit did not touch it and the defect shipped one round before the release that found it.

**THE FIX, AND ITS SCOPE.** The strays check becomes conditional on a non-empty disk set and skips
in the wording its sibling in that file already uses; parts 2, 3 and 4 — the `PINS` read and the
two `CITED_PATH` predicates — are untouched, so every tooth the text-pins round required is still
there on a maintainer tree, where it is measuring something. The maintainer count does not move:
**3532 passed, 8 skipped** before and after, so the fix costs the maintainer tree nothing and buys
the clone a skip in place of a failure.

**THE SWEEP FOR SIBLINGS OF THE SAME CLASS FOUND NONE**, and the enumeration is the point rather
than the result. Every site in `tests/` that builds a set from files `.gitignore` excludes was
read: `spec_pin_files_on_disk()` has exactly two callers — `tests/test_cdm_pins.py:619`, whose
`DISK` is guarded by the skip at `tests/test_cdm_pins.py:694`, and the failing test. Of the rest,
`tests/test_cdm_pins.py:1409`, `:1446`, `:1498`, `:1664`, `:1820` and `:1835` already skip on
absence; `:768` and `:1583` assert a NEGATIVE, which an empty set satisfies; `:1235` floors itself
on the tracked pin records and says so in its own message — *"it is keyed on the record precisely
so that a fresh clone checks fifteen paths instead of none"*; `:1617` feeds a printed line whose
assertions are over `PINS`; `tests/test_cdm_format_coverage.py:2768` compares two disk readings
against each other and asserts only the tracked `spec/` directory exists. Every other non-emptiness
assertion over a glob — `.klv`, `.klvframe`, `.cat0*`, `.s4586`, `.nmea`, `.gmti`, `.xml`, `.adsb`
— is over a TRACKED fixture and a clone has all of them. **The empirical half agrees with the
enumeration**: a clone of the fixed tree runs the whole suite with **0 failed**.

**THE CLONE IS NOW THE PROCEDURE'S**, which is this round's return and not a note. Condition 1
gains a local pre-check — a fresh-clone suite run, with the command, beside condition 5's
`--mutation-check` in the block that does not wait for a tag. The reading it is grounded on is the
one this failure proves was missing: *a maintainer green is not evidence for condition 1, because
condition 1 is read by a clone.* Condition 1's paragraph had known since it was written that the
two trees run different suites; what it never said is what follows from that.

**THE READINGS.** Tree clean, `HEAD` and `origin/main` both `bf95b77`, one `Signed-off-by`
identity on that commit. **EIGHT tags**; `v1.5.0` annotated, tagger Matej Michalko,
2026-09-04 13:59:43 +0100, at `bf95b77` locally and on `origin`. `PACKAGE_VERSION` `1.5.0`,
`SCHEMA_VERSION` `1.0.0`. Repository ruleset **21205830** targets `~DEFAULT_BRANCH` with `deletion`
and `non_fast_forward` and **no tag target** — read rather than assumed, because a tag rule would
have made the deletion a person's decision and stopped this round there; it is the only ruleset on
the repository. The clone reproduced the failure at the `assert disk` guard before the fix and ran
`0 failed` after it, both against the same interpreter.

**THE DERIVATION IS UNCHANGED AND IS RE-RUN RATHER THAN RECALLED**, after this record was written,
which is the fixed point the arc's own preamble insists on:

```
declared      1.5.0 — a MINOR over v1.4.1
derived       MINOR, from the diff over the distribution between v1.4.1 and v1.5.0
              ... 173 signals over 91 distribution files, elided ...
ruled         8 unit(s) ruled by a person: [...]
pending       the arc since 1.5.0 derives PATCH, so the next release is at least 1.5.1
1 check, 0 failed
```

**173 signals over 91 files, MINOR, zero unruled — the same three figures the release commit
recorded**, taken from the git index of this commit rather than from that message. The `pending`
line is the one reading that is about this round rather than about the arc, and it is quoted
because it is the alternative that was NOT taken: with the tag still at `bf95b77` the fix is an
unreleased PATCH and the gate correctly says the next release is 1.5.1. **Moving the tag is what
empties that arc**, and it is legitimate here for the reason at the top of this section and for no
other — the number is not being reused, because 1.5.0 was never issued.

**So the 1.5.0 derivation, its nine `Bump ruling` paragraphs — eight ruled units and one stated
absence — and the arc's notes all stand.** The fix is a test and this record is a document; neither
is code a consumer imports, and the classification of the arc does not move because a `.md` and a
`tests/` file cannot raise a floor that is already MINOR. **The record gets a dated note and not a
rewrite**: nothing above this heading was edited to make the first tag disappear, because a record
that erases a failed run is a record that cannot be checked against the runs.

**What this round did not do**, each because it is somebody else's: it did not approve the `pypi`
environment, did not create the GitHub release, and did not write `PUBLICATION.md` entry 14 — and
entry 14 now has two more things to carry than it did this morning, the failed run and the tag
move. No park, pin or ledger row moved: `version.py`, `RELEASE_NOTES.md`, `klv_pin.json`,
`FORMAT_COVERAGE.md` and `PUBLICATION.md` are byte-identical to `bf95b77`, verified by SHA-256
before and after. `MIGRATIONS.md` and `tests/test_cdm_pins.py` are the only two files that moved.

#### The release round, 2026-09-04 — the number was the gate's over the largest arc this file records, and one Act 0 premise had no reading behind it

**Act 0, and every figure was measured rather than inherited.** Tree clean. `HEAD` and `origin/main`
both at `3b5a5dd`, so nothing was owed to the remote before this round began, and the single
`Signed-off-by` trailer on that commit names the one identity this history uses. **SEVEN tags**,
newest `v1.4.1` at `10d0956` and annotated. `PACKAGE_VERSION` `1.4.1`, `SCHEMA_VERSION` `1.0.0`,
the docstring stating both. Suite **3537 passed, 3 skipped**. `RELEASE_NOTES.md` opened
`# synapse-cdm 1.4.1` with its mechanism heading naming the five prior OIDC releases, exactly one
`## Artefacts` section, and **zero** occurrences of the pinned phrase. The pending section was
first under `## History`, opened on its 91-file count, carried the three round headings, and said
in its own words that nothing in it was in a release. `gh` authenticated; `publish.yml` triggers on
a pushed `v*` tag and on dispatch, with the publish job on the `pypi` environment.
`gates/commit_message.py --rev HEAD` clean. **The untouchables hold, each by its own command**: the
pinned phrase derives to **35** over the git index across 26 files, `scripted_edit`'s contract is
green at **9** while a bare `-k` collects **11** (the recorded trap), `git ls-files` matches **no**
PDF and **no** zip, `fixtures/*/spec/` tracks **nine `.json` and nine `.py` and nothing else**,
`klv_pin.json` still reads fourteen delegations in scope, and the three untouchable files were
digested before anything moved.

**ONE ACT 0 PREMISE HAD NO READING BEHIND IT, AND THAT IS THE SECOND HALF OF 0.10 RATHER THAN THE
FIRST.** The brief paired the suite figure — which matched to the test — with `harness 46 passed`.
**No reading of this tree yields 46.** `tests/test_cdm_harness.py` collects and passes **36**;
`pytest -k harness` collects **64** across eleven modules; the module has held 36 at `v1.4.0`,
at `v1.4.1` and here, so nothing regressed and nothing was removed. It was reported and ruled a
miscount rather than absorbed, on the same standing rule the 1.4.1 record applied to a tag count
that was five in the brief and six in the repository — **and this is the third consecutive round in
which a brief bookkeeping figure is the only Act 0 reading that fails.** It moves no condition: the
harness is green in the suite, and condition 2's actual actor is `gates/wheel_install.py`, run
below.

**The bump gate decided the number, and it needed no human ruling for the KIND.** The arc since
`v1.4.1` derives **MINOR**, floor **1.5.0**, over **173 signals** spanning **91 distribution
files**, with **zero** unruled units — the same three figures at Act 0 and at this commit, because
`version.py`'s move is a change to the declaration the gate is judging and it emits no signal for
it. The release gate's moved set is **92** and the section above states why the two differ.
`klv_security_codec.py` is a new importable module and `fixtures/klv/` gains seven payloads, both
on `version.py`'s MINOR list, so the gate reached the floor by itself: park 5's shape rather than
park 11's. **The eight `Bump ruling` paragraphs are what make the arc reportable rather than what
decides it**, and the gate read all eight and refused none as outliving its case.
`--mutation-check` exercised five synthetic arcs: UNDERSHOOT, EXCEED and UNRULED all refused, and
both PASS cases classified.

**NINE PARAGRAPHS BEGIN `Bump ruling` IN THIS SECTION AND THE GATE PARSES EIGHT, WHICH IS THE
PARSER BEING RIGHT.** The ninth is the surface round's, and it names no unit — it is a paragraph
recording that no ruling was *required*, written so the absence of one would not read as an
oversight. `rulings()` keys on a backticked unit followed by a category, so a paragraph with no
unit contributes nothing, and the arithmetic is nine written against eight parsed with no
discrepancy anywhere. Recorded because a brief counting the paragraphs and a gate counting the
units will disagree by one for as long as that paragraph stands.

**Condition 2 was run locally before any version string moved**, which is the point of running it
here as well as at the tag: `gates/wheel_install.py --mutation-check` reported **13 checks, 0
failed** — 14 adapters against 2 schema modes for **916 fixture verdicts, 0 failed**, a manifest of
**1163 files equal to git in both directions**, 62 shipped prose files, six schemas regenerated
byte-identical from outside the repository, and the package slice at **2439 passed, 1 skipped** —
and the mutant wheel with `package-data` emptied was refused by **five** checks, so the gate can
still fail.

**AND THE TEXT-PINS ROUND'S `pyproject.toml` FINDING WAS RE-CHECKED AGAINST THE BUILT ARCHIVES
RATHER THAN AGAINST THE GLOBS.** That round found `exclude-package-data` naming `.pdf` and nothing
else, so a newly pinned `.txt` would have shipped inside the wheel, invisible to every check that
reads `git ls-files`. The exported wheel and sdist were opened and enumerated here: **eighteen
entries under `fixtures/*/spec/` in each, nine `.json` and nine `.py`, zero offenders**; **zero
`.pdf` anywhere in either archive**; and the only `.txt` in either is packaging metadata generated
by the build — `dist-info/entry_points.txt` and `top_level.txt` in the wheel, five `egg-info` files
in the sdist. `rfc2781.txt` is on disk, gitignored by the global `*.txt` rule, and **in neither
archive**. A glob that stopped matching would have been caught by the result and not by reading the
pattern.

**Condition 4's three derivations were read off the tree and copied into the notes from the
output.** `adapter.discover()` returns **14** and `adapter.roster()` returns **14**, the same
fourteen names in the same two directions — **the roster did not move this arc**, derived rather
than carried over from the 1.4.1 notes. The harness over the registry sums **458 fixture verdicts,
0 failed**; the whole of the increase is `stanag4609`'s, twenty to **forty-six**, and every other
adapter's total is unchanged. `python -m synapse_cdm.schemas --check --out schemas` reports
`CURRENT: schemas vs models at 1.0.0` over six schemas.

**`SCHEMA_VERSION` was checked and not assumed.** `git diff v1.4.1..HEAD -- schemas/` is empty, and
it had to be: `entity.schema.json` declares `attributes` `additionalProperties: true` while the
object around it is `additionalProperties: false`, so carrying seventeen decoded security elements
into it adds no field to any schema. That is the 1.2.0 ruling reached a second time by a different
payload. It stays **1.0.0** and the release is a package MINOR with no wire movement.

**THE SUITE AT THE RELEASE COMMIT, AND THE 1.4.1 RECORD'S FINDING HELD IN A CLEANER FORM.** That
round moved five checks, then rolled the section and turned three more red. Here the five version
sites were moved first and re-run green — the changelog claim, the packaging assertion, the
notes-describe-this-version check and the documented tag command all pass at 1.5.0 — so the roll's
consequence stands alone: **exactly FOUR red, all in `tests/test_cdm_bump_derivation.py`, all one
cause.** `measure()` resolves rulings under the heading `declared if released else Unreleased`, and
with no `v1.5.0` tag it looks in a section this commit no longer has, so the arc reads UNRULED with
all eight units named. **Proven rather than argued, at the commit and before the tag**:
`rulings("1.5.0")` returns all eight units with their categories and `rulings("Unreleased")`
returns zero, so the gate resolves them the instant a tag names the declared version. Every other
test in the suite is green, which is the STOP condition this round was given and did not meet. All
four went green the moment the tag existed, as predicted.

**AND A SECOND CHECK WENT RED ONLY ONCE THE TAG EXISTED, WHICH IS THE HALF A PRE-TAG SUITE CANNOT
REACH.** With `v1.5.0` present, all four of those went green and
`test_every_released_arc_derives_the_number_it_shipped` went red: it walks every consecutive pair
of tags and compares each arc's unruled units against `UNRULED_HISTORICAL_ARCS`, a NAMED set rather
than a count. `v1.4.1 → v1.5.0` was not in it. **The row was added and the tag was remade** — the
one point in the procedure where a tag may be moved, because nothing had been pushed. It is the
third entry and it arrives by the second's route rather than the first's: `v1.0.0 → v1.1.0` is an
arc nobody ruled, because this gate did not exist when it shipped, while this one **was** ruled and
belongs in the set anyway, because that check derives the arc RAW — it calls `derive()` and never
`apply_rulings()`, so what it witnesses is the classifier's own reading of history rather than the
classifier plus a document.

**IT IS ALSO THE LARGEST ENTRY THE SET HOLDS, AT EIGHT UNITS, AND SIX OF THE EIGHT ARE ONE CAUSE
READ SIX WAYS.** Four of them are the `<statement 6>` through `<statement 9>` imports that did not
change, renamed by the position of an insertion above them. **They are left in at full width
deliberately.** Collapsing four refusals with one cause into one entry would make this set a
summary of causes rather than a record of units the table cannot decide — and a set that
summarises is a set that can be argued smaller, which is the file-of-exemptions the whole ruling
mechanism refuses to become. The comment beside the row says so, so a later round meets the
reasoning before the temptation.

**The roll, and the grep that no gate can replace was run anyway.** The pending section became
`### 1.5.0` and its opening sentence describes the heading it absorbed rather than spelling it. The
literal occurs **zero** times in this file, confirmed by grep after the roll and independently by
the carrier gate — the sixth roll to do this, on a defect three consecutive rolls recreated. The
two other tracked files that spell it, `FORMAT_COVERAGE.md` and `klv_pin.json`, are outside that
gate's scope, which reads this file only; both were checked against the section-reference gate as
well, and neither cites a heading by the double-quoted form that gate sweeps.

**The fixed point was respected.** Writing this record moves `MIGRATIONS.md`, which is a shipped
document and already in the arc, so the moved set stays at **92** and the classification stays
**MINOR** — verified by re-running the derivation after this file was written, not before it.

**DATED NOTE, 2026-09-04 — THE TAG THIS ROUND PUSHED HAS MOVED, and this section is annotated
rather than rewritten.** `v1.5.0` first pointed at `bf95b77`, the commit this round made. Run
**33875771133** failed **condition 1** on one test —
`tests/test_cdm_pins.py::test_a_stream_or_a_provenance_capture_under_a_pin_path_is_still_refused`,
at its `assert disk` guard, a guard that holds on a maintainer tree and cannot hold on a clone.
`1 failed, 3468 passed, 71 skipped`. Nothing reached the publish job, no artefact was uploaded and
no Release was made, so the release's one irreversible step was never taken. The tag was moved to
the fix commit the same day; see *The re-tag round* above. **Nothing in this section is wrong** —
the suite was green on the tree it was run on, the count recorded below is that tree's, and the
defect was in a test the round did not touch and could not have seen. That is the finding, and it
is why condition 1 now carries a fresh-clone pre-check.

**What this round did not do**, each because it is somebody else's: it did not approve the `pypi`
environment, did not create the GitHub release, did not write `PUBLICATION.md` entry 14, and did
not deploy the documentation site — all of which are the witness round's once PyPI serves 1.5.0 and
the workflow's digests exist. No park, pin or ledger row moved: `klv_pin.json`,
`FORMAT_COVERAGE.md` and `PUBLICATION.md` are byte-identical to `3b5a5dd`, verified by SHA-256
before and after.

#### The text-pins round, 2026-09-04 — a pin may be text, and tag 13 is read from three documents

**DATED NOTE, 2026-09-04 — ONE TEST THIS ROUND SHIPPED WAS RIGHT ON A MAINTAINER TREE AND WRONG ON
A CLONE, and the release it landed on is what found it.** `test_a_stream_or_a_provenance_capture_
under_a_pin_path_is_still_refused` opened by asserting the pin corpus was on disk. That is the
correct guard on the tree that wrote it and it cannot hold on a fresh clone, where `.gitignore`
keeps every pinned document out of the index — including the `*.txt` rule this very round added.
It failed condition 1 on the tag for 1.5.0, run 33875771133, four commits later; the guard is now
a skip and condition 1 has a fresh-clone pre-check. See *The re-tag round* above. The round's
substantive work is untouched by it.

**WHAT A CONSUMER RECEIVES CHANGES AT EXACTLY ONE KEY, AND THIS IS THE PARAGRAPH THE 1.5.0 NOTES
HAVE TO BE DERIVED FROM.** `Entity.attributes.security_metadata.object_country_codes` stops
carrying hex and starts carrying text. Before this round:

    "value":      "0043005a0045003b005a005a005a"
    "value_form": "carried_octets"

After it:

    "value":              "CZE;ZZZ"
    "codes":              ["CZE", "ZZZ"]
    "byte_order":         "big"
    "byte_order_mark":    null
    "byte_order_clause":  "The byte order is read under RFC 2781 §4.3, …"
    "value_form":         "utf16_country_codes"

`octets`, `length_octets`, `tag`, `presence` and `section` are unchanged, and **the input bytes did
not move**: they were UTF-16BE from the day the fixture was written. What moved is that this
repository can now say so from a document it holds.

**THE STRUCTURAL DIFF IS ONE KEY WIDE, MEASURED RATHER THAN CLAIMED.** All 22 pre-existing goldens
were parsed before and after and compared leaf by leaf: **every differing leaf path lies under
`attributes/security_metadata/object_country_codes`** — its `value`, `value_form`, and the four
keys added beside them. Nothing else in any object changed, which is what the round required and
what a whole-file diff of eleven regenerated goldens cannot tell you.

##### The blocker was a schema question, and the surface round is what turned it into one

The section below records Act 2 of the surface round stopping at its own stop rule: RFC 2781 is
free, stable, erratum-free and served over a route that answered 200 on the first ask, **and the
RFC Editor issues no PDF for it**, while every pin gate here recognised a pin by `.pdf`. It named
four sites and said *any one of those is a ruling; four of them together are a round*. This is that
round, and the acquisition it unblocked was one `GET`.

**TWO RULINGS, recorded in full at `fixtures/klv/spec/klv_pin.json`'s `text_pin_ruling`:**

**A PIN MAY BE TEXT WHERE THE PUBLISHER ISSUES NO PDF.** The copy that is read is the publisher's
`.txt` as served. A text pin's node keeps `pages` and gains `format` (`"text/plain"`; **a node
without the field is a PDF**, which is what let one document be admitted without rewriting twelve
records to describe bytes that did not move) and `lines`. `pages` comes from a **second ruled
method** with three terms that must agree — form feeds, `[Page N]` footers, and the highest footer
number — and RFC 2781 gives 14, 14 and 14. `lines` is **defined** as the count of `\n` bytes, which
is `wc -l` semantics, and is 787; `str.splitlines()` gives **801**, because Python treats the form
feed as a line terminator, so the two differ by exactly the page count with no error anywhere.
Both figures are recorded wherever one is.

**NOT COMMITTED, UNIFORMLY WITH EVERY PIN — AND THE GROUND IS NOT LICENCE.** RFC 2781's own Full
Copyright Statement permits copying it "without restriction of any kind" provided the notice
travels along, so committing it would have been *allowed* — unlike STANAG 4609 Edition 5, whose
prohibition is what `not_committed.why` quotes. It is kept out anyway: a tree that vendored what it
may and pinned what it may not would hold documents two ways, and a reader could not tell from a
pin record which way governed a row. `.gitignore` gained a global `*.txt` beside its `*.pdf`,
commented so nobody reads the rule backwards into a restriction the Internet Society did not
impose.

##### The pin

**IETF RFC 2781, UTF-16, an encoding of ISO 10646, February 2000**
(`e3fed703…ae75b502`, 29 870 bytes, 14 pages) at `fixtures/klv/spec/rfc2781.txt`, 787 lines,
`format` `"text/plain"`, retrieved
2026-09-04T11:36:15Z from `https://www.rfc-editor.org/rfc/rfc2781.txt` — the route read off the
publisher's own info page, whose Formats block names exactly `TXT` and `HTML`. Neither obsoleted
nor updated nor erratum-bearing, read off the publisher's pages rather than assumed. Magic-checked
before it was treated as text: 0 NUL bytes and 0 octets above 0x7F. **It is a held document and not
a delegation** — the encoding reference of ONE element of ONE held delegation — so the delegation
tally is unchanged at fourteen in scope and nine held, while the held-document count moves to
thirteen.

##### Tag 13, and the third document is the round's finding

**THE ROUND EXPECTED A TWO-DOCUMENT COMPOSITION AND THE TREE HAS THREE.**

- **ST 0102.12 supplies none of the byte order**, and that is a measurement. §6.1.13 states
  presence, the semi-colon separator, concatenation and the frame-centre rule. Across all eighteen
  pages `UTF` occurs once and `10646` once, both inside reference [26]'s title; `BOM`, `byte
  order`, `endian`, `Unicode` and `little` occur **zero** times in the document's own voice. The
  encoding reaches the element only through §6.7's Data Type cell reading `RFC 2781 [26] [27]`.
- **RFC 2781 supplies the rule.** §4.3 for the unlabelled `UTF-16` charset — `0xFEFF` means
  big-endian, `0xFFFE` means little-endian, neither means big-endian, and an application `MUST
  NOT` assume the serialization without reading the first two octets. §3.2 for what a leading
  `0xFEFF` is and what one anywhere else is not. §2.2 for the decode and its two error cases.
- **MISB ST 0107.3 supplies the agreement, and it was already held.** ST 0102.12's own reference
  [9] is *MISB ST 0107.2 Bit and Byte Order for Metadata in Motion Imagery Files and Streams* — a
  document pinned here since 2026-08-26, because it closed park 4 — whose `ST 0107.2-02` reads
  "Byte order shall be big-endian or MSB", scoped by §1 to apply "retroactively to all documents
  approved by the Motion Imagery Standards Board". **So §4.3's no-BOM default and the MISB
  baseline agree by two independent held statements**, and the ordinary case is not a `SHOULD` this
  layer chose to follow.

`ST 0102.10-24` and `-25` are now **applied**: the element is one entry and its codes are split on
the semi-colon. `-26` stays a producer's rule — nothing here computes a country from a geometry.
Codes are **carried and never validated**, on the standing coding-method ruling: GEC, ISO 3166,
STANAG 1059 and GENC are registers this repository does not hold.

**WHERE THE TWO DOCUMENTS PULL APART, AND WHAT HAPPENS THEN.** A little-endian BOM. §4.3 makes the
text little-endian and forbids assuming otherwise; `ST 0107.2-02` says big-endian. The value
**decodes** under §4.3 and an advisory of class `byte_order_contradicts_st_0107_2_02` records that
the producer broke the MISB baseline — the `ST 0102.10-57` precedent at tag 22, where a clause is
recorded and not applied. Refusing would discard a value the packet carried because its producer
broke a rule; big-endian-decoding it would turn `CZE` into two ideographs and call them country
codes.

**TWO REFUSAL CLASSES, kept separate because the repairs differ.**
`utf16_cannot_carry_an_odd_octet_count` is a framing fault upstream — and note that §6.7's Length
cell for this element reads `Variable`, so unlike tags 1 and 22 there is no stated length to
disagree with and the refusal comes from the encoding itself. `utf16_sequence_is_in_error` is a
content fault: a surrogate without its partner, which §2.2 calls an error and declines to specify
recovery for, so none is invented.

**Tag 13's row moves off `not yet` and the ST 0102.12 row set reads SEVENTEEN of seventeen**, dated
2026-09-04. `DECODING_RULES["carried_octets"]` is **retired and kept** as the rule that was, because
it is what four goldens said and what every release up to 1.4.1 delivered.

##### Outside the distribution, and stated so a reader of this section does not go looking

`gates/`, `tests/`, `.gitignore`, `CONTRIBUTING.md` and `PUBLICATION.md` all moved and **none of
them ships**. What changed there: three `.pdf`-shaped recognition sites in `tests/test_cdm_pins.py`
widened to a declared `PIN_SUFFIXES` vocabulary rather than to a dropped extension check — the
filter was keeping nineteen fetched provenance files and two transport-stream artefacts out of a
corpus resolved against the package base, and **nine of those provenance files are `.txt`**;
`gates/pdf_text.py` gained `text_pages`, because RFC pagination breaks a sentence exactly the way
PDF extraction does and then inserts four lines of furniture into the break; and
`gates/commit_message.py` gained a sign-off requirement for the `41d3d2d` incident, with the
history-wide calibration that refuted its first specification. `gates/parks_table.py` needed **no
change** — its `held_series()` globs `*.pdf`, so `2781` never enters `FILE_SERIES` and cannot be
mistaken for a MISB four-digit series.

#### The surface round, 2026-09-04 — the wire carries facts and pointers, and one document that is free but not holdable

**WHAT A CONSUMER RECEIVES CHANGES, AND THIS PARAGRAPH IS WHY THE 1.5.0 NOTES HAVE TO SAY SO.**
`Entity.attributes.security_metadata_basis` goes from **prose to tokens**. Until this round it
carried every ruling in `klv_security_codec` — the carrier basis, the confidentiality ruling argued
in full, the external code lists ruling, `ST 0102.12-65`/`-66` on ST 336, §6.2's repetition rate,
§6.5 and §6.4 quoted, the element refusal policy — on **every object**, whether or not the packet
carried a security set. It now carries a state token from a closed set, the ruling's NAME as a
token, what carried the set, the copy that decoded it, the clause pointers that govern this case,
and **one** pointer to where the argument lives. A consumer that read a sentence out of this key now
reads a pointer; a consumer that compared a state now compares a token instead of an em-dashed
sentence.

**THE MEASUREMENT.** Compact UTF-8 JSON across all 34 goldens, 36 occurrences: **229 864 bytes
before, 25 294 after — 204 570 removed, 89%**. Per occurrence, 6 385 to 703. The absent case, which
is the one that rides on a packet carrying no security metadata at all, goes from **6 146 to 486**.
The precedent is `length_divergence_policy`, the 1.2.0 annotation that also rides on every object:
**299 bytes clean**, and measured in the same goldens on the same day it is 299 clean, 818 with one
advisory, 1 622 with one defect. The reshaped basis is **486, 1 106, 1 773** — the same three
scales, which is this round's scope ruling stated as a measurement.

**NOTHING WAS DELETED.** Sixteen prose values came off the wire and every one landed in
`klv_pin.json`'s new **`security_basis_ruling`** node **under the key it was emitted as**, with its
byte count and the module constant it was generated from, lifted out of the acb6295 goldens by a
script rather than retyped. That node also states the replacing shape: every key, its type, its
condition, the closed token set `UNLABELLED` / `PARTIAL` / `COMPLETE-ON-REQUIRED`, and the three
pointer forms. **The codec constants all remain in code** and are simply no longer emitted.

**THE STANDING CONFIDENTIALITY RULING IS UNCHANGED IN EVERY TERM** — carried and never invented, no
default, no nearest match, no marking on an unlabelled packet, no `security_metadata` key at all for
a packet that carried no item 48. Only where its text lives moved.

**AND NO CONSUMER EVER RECEIVED THE SHAPE THIS REPLACES**, which is why this is not a migration and
why it was done now. `klv_security_codec.py` and `security_metadata_basis` do not exist at tag
v1.4.1 — both landed in the park 2 round four commits earlier the same day, in this same pending
section (the heading token itself is elided here, because `tests/test_cdm_release.py` reads the
literal as evidence that a pending section EXISTS and a sentence spelling it would answer for one
that a release had absorbed). A consumer of 1.5.0 meets the token shape as the **first** shape
this key ever had.

**THE CHECK THAT MADE IT SAFE, AND THE GUARD THAT WAS MISSING.** All 34 goldens were parsed before
and after, `security_metadata_basis` and the six relocated prose keys deleted from both, and the
remainder compared: **byte-identical on all 34**, so not one decoded value, octet string, offset,
refusal fact or advisory fact moved. And `grep -rn security_metadata_basis tests/` returned
**nothing** before this round — the goldens were the only guard, and a golden guards a VALUE.
`tests/test_cdm_stanag4609_adapter.py` gained **seven tests** that guard the SHAPE: the token is
drawn from the codec's own closed set, the key set is checked per case, no basis key may carry more
than 160 bytes of string, the clause pointers must be the codec's own, `UNLABELLED` and the absence
of a `security_metadata` key must agree, and **the record must name every key the wire stopped
carrying**.

**Inside `security_metadata` the element VALUES are untouched and only the prose beside them moved.**
`label_basis` — §6.8 quoted, the same 890 bytes under all three labelled elements — became
`label_clause`, the ONE subsection that governs that element, which is strictly more than the
paragraph said. `_local_set_key_basis` became `_local_set_key_clauses`. Tag 13's
`value_is_octets_not_text` became `value_form`.

**Bump ruling.** Not required, and this states why rather than leaving the absence to be read as an
oversight. `gates/bump_derivation.py --json` reports `pending.unruled` as **empty** after this
round's files were staged: every unit it classified, it classified, so the arc still derives
**MINOR** with a floor of **1.5.0** on `klv_security_codec.py` being a new module — unchanged by
this round, which adds no importable name and removes none. The eight **Bump ruling** paragraphs the
park 2 round wrote are untouched and still stand.

**ACT 2 STOPPED, AND THE STOP IS THE FINDING.** The round was also sent to acquire **IETF RFC
2781**, pin it, read UTF-16's byte-order rule off it and move ST 0102.12's tag 13 row off `not yet`.
**The document is free, reachable, and was read; it is not pinned.** The RFC Editor's info page
answered 200 at 2026-09-04T10:01:19Z and its `Details` block names **two** formats, `TXT` and
`HTML` — the string `pdf` does not occur anywhere in its 177 626 bytes, and the expected
`/rfc/pdfrfc/rfc2781.txt.pdf` answers **404**. Every pin gate here is PDF-shaped, so pinning a
text-only document needs a schema ruling this round was not given, and the round stopped at its own
stop rule rather than inventing one. The text was read and hashed as a **reading and not a pin**:
29 870 bytes, SHA-256 `e3fed703…ae75b502`, no obsoleting or updating RFC, **zero errata**.
`gates/pin_paths.py` still counts **23**, `delegated_specifications_held` still holds **fourteen**
pins, fourteen delegations are still in scope, and **tag 13 stays `not yet`** — but its blocker
narrowed from *an unheld document* to *a document this tree cannot yet hold*, which is smaller and
more tractable, and the tag 13 row, the codec's TAG 13 ONLY note and
`klv_pin.json`'s `surface_round_2026_09_04` all now say so with the routes and the digest recorded.
**No park moved**: tag 13 is a row.

#### The park 2 round, 2026-09-04 — the row set MISB ST 0102.12 supports, and a park that closed by writing rather than by obtaining

**WHAT CLOSED, AND ON WHAT.** Park 2 closed on **both halves of `shared_exit_condition`**. The
first half was discharged on 2026-08-26 and did not move: ST 0102.12 pinned by SHA-256
`20d40b52…85eca267`, 514 842 bytes, 18 pages, title-page identity read — re-digested from the copy
on disk at the start of this round and matching in both terms. **The second half is what this round
wrote**: §6.7's Table 2 transcribed in full, **seventeen elements**, at `klv_pin.json`'s
`tag_table_st_0102_12` and in `FORMAT_COVERAGE.md`'s *The ST 0102.12 Security Metadata Local Set —
the row set nested under item 48*.

**IT IS THE FIRST PARK HERE CLOSED WITHOUT ACQUIRING ANYTHING.** Parks 1, 4, 9, 13 and 8 each
closed on bytes that arrived that day; this one closed on bytes that had been on disk for nine
days. The park stood entirely on its unwritten artefact — which is precisely the state park 2 was
this table's **precedent for**, cited as such by the delegated-documents row, the parks preamble,
parks 5 and 11's rows and the *Why neither is CLOSED* row. **Closing it does not weaken the
precedent**: it is the precedent being discharged the way it said it would be. Every citation now
reads in the wrong tense and every one was given a **dated note rather than a rewrite**, because a
citation rewritten to the past destroys the evidence that the state it names was real from
2026-08-26 to 2026-09-04.

**THE TRANSCRIPTION, AND WHAT MAKES IT CHECKABLE.** Seventeen rows — tags 1–14, then 22, 23 and 24
— six `Required`, eight `Context`, three `Optional`, and the two splits are over different columns
and agree at 17. **§6.1 carries seventeen subsections, §6.1.1 through §6.1.17, one per element and
in the same order**; §6.8 has exactly three conversion subsections and they are exactly the three
rows whose Data Type is `uint8`; and Table 1's Universal Set lists the same seventeen elements
under 16-byte keys. Four statements of one table, all agreeing — which is park 1's arrangement
reached by a second document.

**AND WHAT CANNOT BE CHECKED, SAID PLAINLY.** `check_against_the_documents_own_examples` runs
`klv_uas_codec`'s decoder over ST 0601.14a's own 26 printed Software Values and is the strongest
check in this repository. **It has no analogue here and none was simulated.** ST 0102.12 prints no
worked example of an element or a set anywhere in its eighteen pages — derived rather than assumed:
every run of four or more hex pairs in the document was extracted and every one is a 16-byte
Universal Label. Its only examples are two country codes (§6.1.2, §6.1.3) and one Tag 2 value
(§6.9). **And ST 0601.14a §8.48's own Example KLV Item row reads `30`, `-`, `N/A`**, so neither of
the two documents behind this row set supplies one. The transcription is checked four ways and not
one decoded VALUE is checked against a document. That is weaker than park 1's arrangement and the
record says so at four sites rather than leaving a reader to notice.

**THE CONFIDENTIALITY RULING, IN THE OUTPUT.** A classification is **CARRIED AND NEVER INVENTED** —
the NITS precedent, reached a second time. Three consequences a reader can check in a golden file:
an integer outside §6.7's five listed Security Classification values is carried **with no label**
and an advisory names the clause, because a nearest match would be inventing a marking; a malformed
element is refused with its octets parked while the other sixteen decode; and **a packet with no
item 48 emits no marking at all** — no `security_metadata` key, not a null classification, not an
empty object a reader could take for an empty marking.

**§6.5 IS WHAT DECIDED THE OUTPUT SHAPE, AND IT WAS READ BEFORE THE SHAPE WAS CHOSEN.** *"The
absence of Security Metadata does not signify Motion Imagery Data as Unclassified."* So a packet
without item 48 is **UNLABELLED**, unlabelled is not a value of a field, and what the object
carries instead is §6.5's own sentence at `attributes.security_metadata_basis` — so a consumer
meets the document's statement of what the absence does not mean rather than supplying one. **DATED
NOTE, 2026-09-04, ADDED BY THE SURFACE ROUND AND NOT A REWRITE OF THE SENTENCE ABOVE:** the
object now carries §6.5's *pointer* rather than §6.5's sentence — `state` reads `UNLABELLED`,
`clauses` names `MISB ST 0102.12 §6.5`, and the sentence itself is at `klv_pin.json`'s
`security_basis_ruling.relocated_from_the_wire.absence`. **The reasoning above is untouched and
so is the behaviour it decides**; what moved is whether the consumer meets the document's
statement inline or one dereference away, and the paragraph is left in its own tense because it
records what the park 2 round chose on the day it chose it. **§6.3
is the contrast that makes it precise**: `ST 0102.10-51` puts a VALUE on the wire for unclassified
data, so *unclassified* and *unlabelled* are two different states.

**THE TRAP THIS DOCUMENT SETS, AND IT IS THE FINDING WORTH CARRYING FORWARD.** Tags 2 and 12 are
both a `uint8` "Country Coding Method" and **their enumerations disagree at seven of sixteen
positions** — `0x03` is *FIPS 10-4 Two Letter* under tag 2 and *ISO-3166 Numeric* under tag 12,
`0x0A`–`0x0C` are the three *Mixed* methods against *Omitted Value*, and the sixteenth value is
`0x10 GENC Mixed` against `0x40 GENC AdminSub`. **The prose corroborates the tables
independently** — §6.1.2 says GENC administrative subdivisions "are not applicable" to tag 2's
method and §6.1.12 says tag 12's allows them — so it is a finding rather than an extraction
artefact. A decoder sharing one enumeration would report a coding method the packet did not send,
for seven of sixteen legal values, with no error and no clue: the plausible-looking lie this
repository's ellipsoid audit exists for, in a new place.

**WHERE THE ITEM LAYER WENT, AND THE ARGUMENT IS MECHANICAL.** Its own module,
`adapters/klv_security_codec.py`, beside `klv_uas_codec` rather than inside it, on that module's
own stated precedent — one item layer per document. **Every one of ST 0102.12's seventeen tags
collides with a tag of ST 0601.14a's 141**: tag 1 is Checksum against Security Classification, tag
2 Precision Time Stamp against the Country Coding Method, tag 22 Target Width against Version. Two
tables cannot share one `dict[int, ...]`, and a module holding two dicts keyed on the same integers
is one where a lookup's meaning depends on which document the reader thought they were in.

**THE SCOPE CONTRACT WAS CROSSED, ONCE, WITH A GROUND.** `klv_uas_codec` covers the 26 items the
pinned stream attests "and nothing else", because an unwitnessed item's decoder "could only ever be
checked against a fixture written from the same reading of the same table". **Item 48 is not in the
pinned stream.** What admits it is that its decoder is checked against a **second document**: ST
0601.14a §8.48 prints `KLV Key 06.0E.2B.34.02.03.01.01.0E.01.03.03.02.00.00.00 (CRC 40980)` and ST
0102.12 §6.7 registers the Security Metadata Local Set under the same sixteen octets and the same
CRC — two documents, obtained on different days by different routes, in agreement. **No other
unwitnessed ST 0601 item has a second document behind it**, so the admission is one tag wide and
cannot grow without another one arriving. `WITNESSED_TAGS` is unchanged at 26; the crossing lives in
a separate `NESTED_SETS` table so that it has to be declared to be counted, and the suite's
tag-by-tag partition guard rules it explicitly rather than being widened.

**KLV 7 IS NARROWED, STAYS REGISTERED, AND IS NOW SHOWN TO BE INERT.** The register entry is that
MISP-2019.1 §4.4.2.9 says "Motion Imagery Data" where `MISP-2015.1-73` says "Motion Imagery", and
Appendix E defines the two differently. **ST 0102.12 settles what the delegated document means**:
its §1 Scope, its §3 definition and every live marking requirement in it — `-55`, `-03`, `-04`,
`-05`, `-23`, `-54` — take the wider term, and the one requirement that named a narrower carrier
(`-01`, MPEG-2 transport streams) is deprecated by this edition. **It does not settle the register
entry**, because the question is about two sentences of MISP-2019.1 and a third document cannot
adjudicate them — that would be the move KLV 11 refused when a majority of reference lists named
one ST 336 edition. **What is new is that the question is INERT for the output**: §6.5 makes this
adapter's behaviour identical under both readings, so KLV 7 bounds a conformance claim about
somebody else's producer and bounds nothing this repository emits. That is why park 2 could close
over it.

**ONE ROW OF THE SEVENTEEN IS `not yet`, AND THE REASON IS A DOCUMENT.** Tag 13 Object Country
Codes declares Data Type `RFC 2781 [26] [27]` — UTF-16, where every other text element here is
ISO/IEC 646. **RFC 2781 is not held.** Decoding UTF-16 needs a byte order and guessing one would be
a rule read off a reference rather than off a document, so the octets are carried verbatim and no
string is produced. The same ruling covers GENC, the GEC register, ISO 3166 and STANAG 1059: **the
codec carries a code as the element's Data Type cell says and does not validate it against a list
it cannot read** — the shape of `klv_codec`'s refusal to enforce X.690's 126-octet ceiling from an
informative annex.

**THE FIXTURES ARE BUILT FROM CLAUSES AND CARRY NO REAL-WORLD MARKING.** Seven of them, each citing
the clause it exercises: a complete set of all seventeen elements, a minimal set of the six
`Required` ones, a partial set (§6.4), a packet with no item 48 (§6.5), a classification outside the
enumeration, and two refusals — a `Required` element at a forbidden length and a `uint16` one octet
short. Two kinds of value appear and are kept apart: **codes the held document itself prints**
(`0x01` UNCLASSIFIED//, `0x0C` STANAG 1059 Mixed from §6.9's own worked Tag 2 value, `//CZE` and
`//GB` from §6.1.3, `0x000C` for this document's own version) and **clearly synthetic strings**,
every one beginning `SYNTHETIC`, with `ZZZ` where a second country code is needed. **Not one caveat,
compartment, handling instruction or releasability marking used in the real world appears in any
fixture.** The `uint16` refusal fixture uses `0x0C` deliberately: zero-extending it would produce
`0x000C`, the RIGHT version for this document, from octets that do not state it — the most
dangerous near-miss available, and the one worth a fixture.

**A DATED CORRECTION, AND THE ORIGINAL WORDS ARE KEPT.**
`reconciliation_ruling.ruling_st_0102.and_it_cannot_be_written_alone_anyway` said of parks 4, 5 and
8 that "None of those three is held". **Parks 4 and 8 are held and closed** — 2026-08-26 and
2026-09-03 — and **park 5's documents are held too**, so the sentence was false of all three by the
time it was read this round. **And park 5 was never on this document's path at all**: not one of ST
0102.12's seventeen elements is a scaled numeric value, and `IMAPB` does not occur in the document.
The correction sits **immediately after the field it qualifies** rather than at the end of the node,
because a reader reaches the end of a node and a `grep` does not. What the clause got right is kept:
"real progress on identity and not yet progress on capability" was exactly true for nine days, and
it stopped being true by the route it named — parks 4 and 8 closed first, and the security set
became readable the moment its framing was.

**AND A STALE COUNT MOVED WITH ITS DATE.** `FORMAT_COVERAGE.md` read **Eight** of the fourteen
delegated documents obtained; `klv_pin.json` has read **NINE** since 2026-09-03, when park 8's
`delegation_table` entry moved from `held: false` to `held: true`. The two sites disagreed by one
for a day and the pin was right. The derived figure — fourteen in scope, five unobtained on parks 3,
6, 7, 10 and 12, leaving nine — is now at both. **The scope figure does not move and never did:
acquiring a document changes whether a delegation is HELD, never how many the profile makes.**

**WHAT THIS ROUND DID NOT DO.** No acquisition of any kind: no fetch, no CDX query, no control
re-fetch, no DNS probe. **No pin added** — `gates/pin_paths.py` reads 23 copies, unchanged. **No
schema change**: `SCHEMA_VERSION` is unmoved at 1.0.0 and `python -m synapse_cdm.schemas --check`
reports CURRENT against an empty `schemas/` diff, because `Entity.attributes` is
`additionalProperties: true`. **No release**: `version.py`, `RELEASE_NOTES.md` and `PUBLICATION.md`
are byte-identical and no tag was created. **No other park moved** and no other row: 114 of the 141
ST 0601 rows still read `not yet`, and item 48 is the only one that left that set.

### 1.4.1 — 2026-09-04 — one refusal gains a document, and the park that priced itself as a purchase closes

**This section carried the pending-arc heading and this release absorbed it** — the token itself is elided here, as it has been at every roll since the third one recreated the carrier defect, because prose that spells it leaves the file answering four release gates in the affirmative with no such section present.

**What moved inside the distribution: twelve files.** Five shipped documents —
`MIGRATIONS.md`, `FORMAT_COVERAGE.md`, `README.md`, `fixtures/klv/README.md` and
`fixtures/klv/spec/build_fixtures.py` — three pin records — `fft_pin.json`, `klv_pin.json` and
`stanag4586_pin.json` — one fixture payload, `fixtures/klv/framing/`
`length_indefinite_first_octet.parsed.json`, and **three modules**, `adapters/klv_codec.py`,
`adapters/stanag4586_codec.py` and `version.py`. The count and the set are
`gates/bump_derivation.py`'s, re-derived AFTER this record was written rather than before it — the
fixed point the 1.4.0 arc's own repair note insists on, and the reason the sentence above is not a
quotation of a derivation that has since moved. **The set grew from six to eleven when the publisher
round closed park 8, and to twelve when this release closed the arc**: `version.py` is a
distribution file, so the bump that ends an arc joins the arc it ends. That is a property of every
release this file records and the 1.3.0 section states it once for all of them.

**The interesting part of the growth is that code moved, for the first time in this arc.**
`klv_codec.py` changed which exception one first-octet value raises and `stanag4586_codec.py`
corrected a docstring analogy, and both units the gate could not classify carry a **Bump ruling**
below.

**The arc derives PATCH over 14 signals, so this release is 1.4.1**, and the two rulings are why the
gate could reach a floor at all: an exception class swapped between two refusals the function
already raised, and a module-private message string. No adapter gained or lost a capability, no
model, no schema and no harness flag moved, and **`SCHEMA_VERSION` is unmoved at 1.0.0** — checked,
not assumed, by an empty `git diff v1.4.0..HEAD -- schemas/`.

**What a consumer of this release receives, stated here as it is in the notes**, because it is the
one thing in this arc that is not internal: a KLV length whose first octet is `0x80` now raises
`KLVFramingError`, a `ValueError`, where it raised `UnderivableFromPinnedCopy`, a
`NotImplementedError`. They share no base but `Exception`, so a caller catching the latter for
indefinite lengths must catch the former. Nothing else about `decode_ber_length` moved.

#### The release round, 2026-09-04 — the number was the gate's, and the suite cannot be green at the release commit by construction

**Act 0, and every figure was measured rather than inherited.** Tree clean. `HEAD` at `23f6f2d`,
`origin/main` at `08e4c0c` — one commit ahead and unpushed, which the push at the end carries. Suite
**3470 passed, 3 skipped**. `PACKAGE_VERSION` `1.4.0`, `SCHEMA_VERSION` `1.0.0`. `RELEASE_NOTES.md`
opened `# synapse-cdm 1.4.0` with its mechanism heading naming the four prior OIDC releases, one
`## Artefacts` section, and **zero** occurrences of the pinned phrase. The pending section was first
under `## History` and said in its own words that nothing in it was in a release. `gh` authenticated;
`publish.yml` triggers on a pushed `v*` tag and on dispatch, with the publish job on the `pypi`
environment. **The untouchables hold, each by its own command**: the pinned phrase derives to **35**
over the git index, `scripted_edit`'s contract is green at **9** (`pytest -k scripted_edit` collects
**11**, the recorded trap), `git ls-files` matches **no** PDF and **no** zip, and `klv_pin.json`'s
delegation tally still reads fourteen.

**ONE ACT 0 READING DIVERGED FROM THE BRIEF AND IT WAS THE BRIEF THAT WAS WRONG.** The brief
enumerated **five** tags; the repository has **six**. `v1.0.0` is the missing one — the hand-uploaded
first release the procedure's own fallback section describes and `PUBLICATION.md` entry 5 records.
It is annotated, already on `origin`, and names its tree's `PACKAGE_VERSION`, so the tag tests that
re-derive over *every* tag in history were already green across it and `--follow-tags` had nothing to
push for it. The divergence was reported and ruled a miscount rather than absorbed silently, on the
standing rule that a premise stated wrongly is stopped on even when stopping is inconvenient — this
is the second consecutive round in which a brief's own bookkeeping figure was the only thing that
failed Act 0.

**The bump gate decided the number, and the two rulings are what let it reach a floor at all.** The
arc since `v1.4.0` derives **PATCH** over **14 signals**, floor **1.4.1**, with **zero** unruled
units — the gate reads both `**Bump ruling.**` paragraphs in this section and accepts them, neither
being stale. `--mutation-check` exercised five synthetic arcs: UNDERSHOOT, EXCEED and UNRULED all
refused, and both PASS cases classified. **The moved set was eleven files at Act 0 and is twelve
here**, `version.py` having joined the arc it closes.

**Condition 2 was run locally before any version string moved**, which is the point of running it
here as well as at the tag: `gates/wheel_install.py --mutation-check` reported **13 checks, 0
failed** — 14 adapters against 2 schema modes for **864 fixture verdicts, 0 failed**, the wheel
installed into a venv with no part of this repository on its path, six schemas regenerated
byte-identical from outside the repo — and the mutant wheel with `package-data` emptied was refused
by **five** checks, so the gate can still fail. A failing build found here is a failing build no tag
points at.

**Condition 4's three derivations were read off the tree and copied into the notes from the output.**
`adapter.discover()` returns **14** and `adapter.roster()` returns **14**, the same fourteen names —
**the roster did not move this arc**, and that is derived rather than carried over from the 1.4.0
notes. The harness over the registry sums **432 fixture verdicts, 0 failed**, which is 1.4.0's total
unchanged because this release adds no fixture and removes none. `python -m synapse_cdm.schemas
--check --out schemas` reports `CURRENT: schemas vs models at 1.0.0` over six schemas.

**`SCHEMA_VERSION` was checked and not assumed.** `git diff v1.4.0..HEAD -- schemas/` is empty. It
stays **1.0.0** and the release is a package PATCH with no wire movement.

**THE FINDING OF THIS ROUND: THE SUITE CANNOT BE GREEN AT A RELEASE COMMIT, AND THAT IS THE GATE
WORKING RATHER THAN FAILING.** Bumping `PACKAGE_VERSION` alone turned five checks red — the
changelog claim, the packaging assertion, the notes-describe-this-version check, the documented tag
command, and `test_the_json_measurement_is_what_a_round_would_quote`. Four were moved to 1.4.1 and
re-run green; the fifth is the one the 1.4.0 round also left red, and it is red **by construction
until the tag**. Rolling the pending section then turned three more red, all of them the bump gate
refusing the arc as UNRULED — and the reason is written in the gate's own docstring:
`rulings()` reads the section describing the arc, which is the pending one *while the arc ends in
the working tree* and `### <version>` *once a release has absorbed it*. So between the roll and the
tag the rulings are in a section the gate is not yet looking at. **This is unreachable in the other
direction**: the roll has to happen in the release commit, the release gates forbid a pending
section once the tag exists, and a ruling duplicated into both sections would be refused as stale in
one of them. **Condition 1 is a check at the tag** — the procedure says so in its Actor column, "the
workflow, on every dispatch and every tag" — and the workflow runs the suite on the tagged tree.
Verified rather than argued: `rulings("1.4.1")` returns both units from this section, so the gate
resolves them the moment a tag names the declared version, and the suite was re-run with the tag
present before anything was pushed.

**AND A SECOND CHECK WENT RED ONLY ONCE THE TAG EXISTED, WHICH IS THE HALF A PRE-TAG SUITE CANNOT
REACH.** With `v1.4.1` present, three of the four pre-tag failures went green and
`test_every_released_arc_derives_the_number_it_shipped` went red: it walks every consecutive pair of
tags and compares each arc's unruled units against `UNRULED_HISTORICAL_ARCS`, a NAMED set rather
than a count. `v1.4.0 → v1.4.1` was not in it. **The row was added and the tag was remade** — the
one point in the procedure where a tag may be moved, because nothing had been pushed.

**The entry is a different kind of thing from the one already there, and the comment beside it says
so.** `v1.0.0 → v1.1.0` is an arc nobody ruled, because this gate did not exist when it shipped.
`v1.4.0 → v1.4.1` **was** ruled, by the two `**Bump ruling.**` paragraphs above — and it belongs in
the set anyway, because that check derives the arc RAW: it calls `derive()` and never
`apply_rulings()`, so what it witnesses is the classifier's own reading of history rather than the
classifier plus a document. The rulings are what make the arc *reportable*; the ambiguity they
resolve is still a true fact about the diff. **The set records diffs the table cannot decide, not
diffs nobody has decided**, and conflating those two would have made the ruling mechanism look like
a way to shrink this set — which is exactly the file-of-exemptions the gate refuses to become.

**The roll, and the grep that no gate can replace was run anyway.** The pending section became
`### 1.4.1` and its opening sentence describes the heading it absorbed rather than spelling it. The
literal occurs **zero** times in this file as a heading, confirmed by grep after the roll and
independently by the carrier gate — the fifth roll to do this, on a defect three consecutive rolls
recreated.

**The fixed point was respected.** Writing this record moves `MIGRATIONS.md`, which is a shipped
document and already in the arc, so the moved set stays at **twelve** and the classification stays
**PATCH** — verified by re-running the derivation after this file was written, not before it.

**What this round did not do**, each because it is somebody else's: it did not approve the `pypi`
environment, did not create the GitHub release, and did not write `PUBLICATION.md` entry 13, which is
the witness round's once PyPI serves 1.4.1 and the workflow's digests exist. No park moved:
`klv_pin.json` and `FORMAT_COVERAGE.md` are byte-identical to `23f6f2d`, and so is `PUBLICATION.md`.

#### The publisher round, 2026-09-03 — park 8 closed on a document that was never for sale, and the register entry it was blocking is resolved

**THE ROUND TOOK THE FORK THE MAINTENANCE ROUND PUT UP AND DID NOT WIDEN IT.** That round asked
`pub.smpte.org` with `HEAD`, moved zero body bytes, refuted park 8's premise and stopped, because
acquisition is not a round's own call here. The ruling was **ACQUIRE**. Both editions of SMPTE
ST 336 were obtained from the publisher's own library, **park 8 CLOSED**, and register entries
**KLV 11** and **KLV 13** both closed with it — the first round here to close two.

**What was acquired, with the instants (rule 12).** `pub.smpte.org/doc/st336/` listed both
publications and both artefact routes answered **200**. `st0336-2017.pdf` — **457 808 bytes**,
**36 pages**, SHA-256 `d6658f63…f37dc294` — was fetched at **2026-09-03T21:14:22Z**;
`st0336-2007.pdf` — **300 320 bytes**, **41 pages**, SHA-256 `e05e5415…4ea92522` — at
**21:14:23Z**. Both were fetched a second time in a pass beginning **21:14:33Z** and both came back
byte-identical, and the received lengths match the `Content-Length` this repository read by `HEAD`
at three separate hours across two rounds. **The transport was a zip and the pin is the PDF**: each
zip holds exactly one file, the SHA-256 that identifies *the copy that was read* is the PDF's, and
each zip's own digest is recorded as transport at `retrieved_inside` rather than as a second
`local_path`+`sha256` pair — which would have been demanded by `gates/pin_paths.py`, whose
resolver has no extension filter, and skipped by `tests/test_cdm_pins.py`, which filters to `.pdf`.
The zips were unpacked in scratch **outside** the repository and never placed under `spec/`.

**THE DOWNLOAD DID NOT CLOSE THE PARK. READING §5.3 DID**, and the two residual absences were ruled
apart rather than together — which is the round's actual content.

* **`0x80` as a first length octet — STATED**, at ST 336:2017 **§5.3**, in the normative body:
  the Length field *"shall be set to [0x80] which shall indicate a non-deterministic length of the
  Value field. Any application document which allows the length of the Value field to be undefined
  shall define an alternative method of locating the end of the Value field."* **The second sentence
  decides it**: no held MISB document defines such a method, and `ST 0107.3-05`'s
  fewest-possible-bytes rule makes every conforming length determinate — so a MISB local set
  carrying `0x80` has no conforming way to end. `klv_codec.decode_ber_length` now raises
  `KLVFramingError` where it raised `UnderivableFromPinnedCopy`, with the refusal fixture
  reclassified from the generator's `ber_length_park` kind, which is **gone rather than left empty**.
  Note the scope, stated at the codec and the pin: **ST 336 permits `0x80`** — the refusal is the
  profile's, not the framing standard's.
* **Any ceiling on the count of length octets — DELEGATED ONWARD**, and ST 336 says so in its own
  voice. §5.3 NOTE 1: *"While there are no restrictions in this standard on the maximum number of
  bytes in the Length field…"*, with the body inviting application documents to impose one — an
  invitation ST 0107.3 declined. **So this was never a silence in two documents**: it is one
  delegating and the other not exercising the delegation. `BER_LENGTH_OF_LENGTH_MAX` stays **127**
  and the encoder's refusal stays `UnderivableFromPinnedCopy` **for a new reason** — ISO/IEC 8825-1
  §8.1.3.5(c) forbids an initial `0xFF` and would cap the count at **126**, that text is reproduced
  verbatim in ST 336's **Informative** Annex I, and X.690 itself is not held. **Recorded, not
  enforced**, because a refusal taken from an informative annex quoting an unheld standard is a rule
  read off a reference rather than off a document.

**KLV 11, resolved as shape (a) and NOT by majority.** The four-against-three divergence is a
reference-list fact with no octet behind it: `ST 0102.12-65`/`-66`, `ST 1204.1` ref [10] and
`ST 1301.2` ref [2] are governed by text that reads the same in both editions. The clauses were read
against each other and then checked mechanically — every `0xNN` literal in each normative body
counted and the multisets compared, every "byte N" statement extracted and the lists diffed.
**Exactly two differences reach a key form, a length octet or a UL structure, and neither reaches an
octet a conforming stream can carry**: 2007 §6.6 forbids byte 6 = `0x06` where 2017's Table 3 marks
it *Reserved* — and 2017 §2 defines *reserved* as "shall not be used" plus *may be defined in
future*, so the prohibition on emitting is identical and only the future differs; and 2017 adds a
`0x06`–`0x7E` **Reserved** row for byte 5 where 2007 said nothing, which names a previously unstated
range rather than changing a stated one. The BER annexes are **word-for-word identical**. ST 336:2017
§1 states *"This revision is intended to yield identical encodings to previous revisions of ST 336
given identical dictionaries"* — quoted as corroboration and **not relied on**, because it is a
statement of intent and the clause-by-clause read is the evidence.

**An identity finding that explains the register's own derivation note.** The 2007 document does not
call itself ST 336:2007. Its cover reads **`SMPTE 336M-2007`**, "Revision of SMPTE 336M-2001", its
running header says the same on all 41 pages, and the string "ST 336" **does not occur in it**. All
three citing documents are back-forming the newer naming style onto the older document, which is why
they disagree about the punctuation and why the register's first sweep — keyed on `ST 336:` — missed
`ST 1301.2`'s hyphen.

**KLV 13, closed, and its reasoning was right at every step.** ST 336:2017's own Normative References
read *"ISO/IEC 8825-1:2008 |ITU-T X.690:2008 … BER Paragraphs 8.1.3.4 and 8.1.3.5 for Length, 8.19
for Object Identifier Coding"*, so X.690 is the document and the `ST 0107.3` pointer at X.680 is the
slip the entry suspected. **What it got wrong is not the citation: it priced the wrong thing.** It
reasoned about reaching a free ITU document to get around SMPTE's paywall, and the premise in its own
first clause — that ST 336 costs money — was false when it was written. The cheap route was never a
substitute document; **the source itself was already free**.

**The parks arithmetic, re-derived rather than incremented.** `gates/parks_table.py` reads **13
rows — 8 open, five closed** \[1, 4, 8, 9, 13], **6 set-claims, 0 failed**. Park 12's three
set-claims naming park 8 fired **CLOSED MEMBER** the moment the row's title cell gained its date, and
were rewritten: the partition's seven named parks are now four open and three closed, and "reading a
stream wants parks 5 and 8" becomes **park 5 alone**. **This is the second time that partition has
decayed by exactly this mechanism**, and the difference is that nothing had to notice — the gate
failed the build.

**A contrast was retired rather than re-pointed, and that is the honest form of this count moving.**
`parks.how_many`, `parks.honest_strength` and the table's own preamble all ended on the same clause:
eight of the nine open parks are public downloads *and one is not*. **The one was park 8.** All eight
still open are downloads, so the sentence has no second side and is retired as a comparison instead
of restated with a different pair of numbers. What survives is weaker and truer, and is what the four
earlier closures were already evidence for: every open row is obtainable by one person with a browser.

**THE FINDING THIS ROUND WOULD CARRY OUT OF ITSELF, and it is about the guard rather than the row.**
`tests/test_cdm_format_coverage.py` **required** park 8's row to keep saying *a purchase decision,
not a download*, and was green for eleven days over a claim that was false the whole time — green
**because** it was doing its job. Its subject, whether a publisher sells a document, lives at
`pub.smpte.org`, and no test here can reach it: a **protocol-gated** fact wearing a **suite-gated**
label cannot fail, because the only thing that could falsify it is a request nobody makes. The guard
now asserts the closure, whose evidence is two PDFs on disk with digests, page counts and title-page
identities. **That is an improvement in tier and not in kind** — it is still the tree agreeing with
itself, and the difference is that the tree now contains the bytes the claim is about. The general
form, recorded at `publisher_round_2026_09_03.the_finding_worth_carrying_out`: **before writing a
guard, ask where its subject lives.** If the answer is a host, a registry or a price, the guard can
pin the record's *wording* and cannot pin the *fact*, and saying so at the guard is the only honest
arrangement.

**The sweep was classified, not scrubbed.** `git grep -Il -e paywall -e 'purchase decision' -e 'not
a download'` returned **27 lines across 9 files** before the round. Each was classified as a **live
claim** or a **dated record**; the dated ones stand, and the four that would redirect a reader —
this file's acquisition-round analogy, `FORMAT_COVERAGE.md`'s STANAG 4586 section, `fft_pin.json`'s
`honest_strength` and `stanag4586_pin.json`'s park-8 class note — got an **adjacent dated
correction** rather than an edit, on rule 9's placement discipline. **The count does not go to zero
and must not be made to**: the refutation and this closure both spell the word in order to retire it,
and are thereafter sites of it. `parks.the_one_that_is_not_a_download` **keeps its now-false key**
and carries the correction beside it, on the precedent
`these_two_counts_were_STALE_and_the_closure_makes_them_RIGHT_AGAIN` set.

**Nothing about meaning moved.** All **141** rows of the ST 0601 row set still read `not yet` and
none was eligible — the third round running to predict that and record it, for the same reason: a
framing rule says where an item begins and never what it means. No other park closed, no park opened,
no park renumbered, and `SCHEMA_VERSION` is unmoved at **1.0.0**.

**Free access is not redistribution and nothing here redistributes.** `.gitignore` carries `*.pdf`
and `*.zip`; both new files report `.gitignore:42:*.pdf` under `git check-ignore -v`;
`tests/test_cdm_pins.py` asserts `git ls-files` matches no PDF anywhere; and the commit names its
paths rather than using `git add -A`. The policy behind the 200 is recorded with the instant it was
read: `www.smpte.org/setting-the-standards-free` answered **200** at **2026-09-03T21:25:43Z**,
headlined *"SMPTE Makes Its Standards Freely Accessible, Opening Standards Library to the Global
Media Technology Community"*. **It was re-read rather than carried from the brief**, which is what
rule 12 was installed for.

**Bump ruling.** `synapse_cdm/adapters/klv_codec.py:decode_ber_length` — PATCH: the refusal for a
single first-octet value changes EXCEPTION CLASS, from `UnderivableFromPinnedCopy` to
`KLVFramingError`. Both are raised, both are documented, and both were already reachable from this
function on other inputs — so the set of inputs it accepts is unchanged, every length it decodes
decodes to the same value, and no caller that handled the function's refusals handles fewer of them
now. What moved is which of two refusals one octet gets and the sentence it carries, which is the
PATCH row's "a translation fix, a message". **It is not MINOR**: the MINOR row is about a surface
gaining or losing something a caller can reach, and a caller catching `UnderivableFromPinnedCopy`
alone for `0x80` was catching a park that no longer exists — the park's disappearance is the
shipped-evidence change the PATCH row governs, not a new capability.

**Bump ruling.** `synapse_cdm/adapters/klv_codec.py:_CEILING_RESIDUE` — PATCH: a module-private
message string. It is not exported, not reachable by name from outside the module, and its only use
is the text of an exception whose class and trigger condition are both unchanged. The sentence now
cites SMPTE ST 336:2017 §5.3 NOTE 1 and ISO/IEC 8825-1 §8.1.3.5(c) where it used to cite park 8;
`BER_LENGTH_OF_LENGTH_MAX` is unmoved at 127 and the encoder refuses exactly the same values.

**THE ROUND'S OWN HISTORY, WHICH IS NOT A WAIVER.** The brief's first issue **stopped at Act 0 on
two of its own bookkeeping figures** — an untracked input directory in the working root, and a sweep
count carried over from a single-pattern grep — and was corrected and re-issued with the tree
untouched between the runs. The second issue's Act 0 was re-taken from scratch rather than carried,
and **one of the two corrections had not actually landed**: the input directory was still in the
working root, so `git status --porcelain | wc -l` read **1** and not the **0** the brief asserted.
It was moved out before Act 1 and the reading was re-taken at **0**. Recorded because a round that
stops on a premise and then proceeds on that premise's second statement should say which.

#### The maintenance round, 2026-09-03 — two standing rules installed, and the sweep that installed the first one refuted a park

**THE ROUND'S CENTRAL FINDING IS NOT ONE OF THE TWO RULES IT WAS SENT TO INSTALL.** It is what the
first rule's sweep turned up on its first run: **park 8's reopen condition priced its document as a
purchase, and the publisher serves it for nothing.** That claim had a suite guard on it and the
guard was green throughout, because what a guard like that checks is that the record keeps saying
the thing. The route to finding it was mechanical rather than clever — an undated field had to be
dated, dating it meant asking the route, and asking the route refuted it.

**Act 0 — the audit, and every figure in it was measured.** Tree clean, `HEAD` equal to
`origin/main` at `e48f3ee`, the tip the brief named. Suite **3460 passed, 8 skipped** at the start,
total **3468**, which is the four-way reconciliation's maintainer-tree row exactly and therefore no
drift. The four untouchables hold, each by its own command: the pinned phrase derives to **35** over
the git index; `scripted_edit`'s contract is green at **9**, with `pytest -k scripted_edit`
collecting **11** because two `version_floor` parametrizations match the name — the recorded trap,
reproduced; `git ls-files` matches **no** PDF; and `RELEASE_NOTES.md` opens **1.4.0**. The bump gate
derived **NONE** over the arc since `v1.4.0` with the floor at **1.4.0**, which is the state the
brief described, measured rather than taken on trust. Pin-as-control through the resolver: **21
copies present, 21 matched, 0 failed**, the Edition 3 pin among them, with its one-byte divergence
recorded at its own site and not re-derived here. Decomposition derived — **22** stated
`local_path`+`sha256` pairs resolving to **21** distinct copies, **19** under the spec base and
**2** under the streams base.

**The `nga.mil` series is extended by one reading, resolution only, AND THE SERIES' CONSTANT IS NO
LONGER CONSTANT.** At **2026-09-03 10:24:57Z** the apex, `gwg` and `nsgreg` all answered `NOERROR`.
No route was asked for bytes. **But the resolver is `127.175.81.17` and every prior reading in this
series was from `192.168.0.1`** — a loopback-range address, so a local proxy rather than the gateway
this environment used to ask through. That is recorded rather than smoothed, because the whole value
of a resolution series is that one variable moves at a time: this reading extends the series only
under the caveat that it came down a different DNS path, and it is not evidence about the path the
earlier readings measured. The hour is 10:24Z, which is outside the single `SERVFAIL` episode's
~14:00–15:00Z window either way.

#### Act 1 — the two rules, and one of them is mechanized further than the brief asked

**Rule 12, dating an external-state reading at the point of reading, is installed in `README.md`
with its witness cited rather than restated.** The witness is ledger entry 12, which had already
adjudicated the case: readings a brief called stale were true when taken, and what made them
misleading was a three-day carry that dropped their timestamps. The rule states what counts as
dated, so the sweep does not churn every round record, and it names the relative-date forms it
refuses.

**The sweep the rule owes was run once, and each finding is repaired at its own site by RE-READING
rather than by dating a recollection.** A date attached to an inherited reading is a second claim
nobody checked. What it found:

* **`PUBLICATION.md`'s visibility probe** stated an anonymous `200`, a `private` flag and a
  successful clone in the present tense with no instant on either half — in the section that opens
  by promising each entry names its probe. It named them and said nothing about when. Both halves
  re-read **2026-09-03 at 10:28:40Z and 10:31:06Z**, and the clone's `HEAD` matched the pushed tip
  at that second reading.
* **The platform bullet** stating an SBOM `404` and two disabled features carried no date while
  sitting between two neighbours that each carry theirs. Re-read **10:28:43Z**, unchanged.
* **The deployment section's Pages reading**, and this was the sharpest of them, for where it sits:
  it asserted a Cloudflare setting in the present tense inside **the section whose entire recorded
  lesson is an undated present-tense claim about Cloudflare state going false while nothing
  noticed**, with the diagnosis three paragraphs below. Re-read **10:28:56Z**, unchanged.
* **`stanag4586_pin.json` dated the copy it fetched and not the refusals that made the fetch
  necessary**, so this park's whole evidence base was undated while reading as current. Act 2's
  probe is that repair.
* **`FORMAT_COVERAGE.md`'s round headings carry no date at all**, where `MIGRATIONS.md`'s carry one
  and its own sub-round headings carry one to the minute. So rule 12's own exemption — a round
  record's heading dates the readings inside it — did not hold for one of the three long records,
  which left readings like a re-checked `403` undated at their site. All three were dated from git
  rather than from memory.

**A REPAIR TO ONE OF THOSE WAS REFUSED BY A BUILD, AND THE REFUSAL IS THE RULE 9 CARRIER TRAP
SPRINGING ON A RULE 12 FIX.** The Pages note quoted the listing's own column heading in order to
report what the column said — one of the two strings `test_cdm_publication.py` forbids this file —
so a note about an undated reading briefly made the record a site of the deploy mechanism. Caught by
a gate rather than by care, which is the only reason it is a footnote instead of a finding.

**AND RULE 12 IS MECHANIZED FOR THE ONE CLASS WHERE A PRECEDENT ALREADY EXISTED.** The existence
check came first and found one: `test_the_annex_l_reopen_condition_records_the_date_it_was_checked`
requires exactly this of the GMTIF Controlled Extension blocker, on exactly this reasoning, and it
had been the only reopen condition in the tree with a machine behind it. `tests/test_cdm_pins.py`
now generalises it — the conditions are **discovered** from the pin records rather than listed, on
this module's own founding lesson, and each must carry an ISO day in its field or in the key path
that reaches it. Of the **five** it discovers across four pin records, two were dated and three were
not. All five are dated now, and the check is proved non-vacuous against the real tree in both
directions: stripping park 8's date makes it red, and a bare year, a relative date and an undated
condition are all refused.

**Rule 13, distrusting a completion notice, is installed AS PROCEDURE, and that is an existence
check rather than a preference.** A background notice reported a long-running command finished, exit
zero, while the run it named was still going; the process table was asked and the process was still
in it. Mechanizing it was tried first, because the precedent is real — a prose sweep became a gate
with no skip state once its token turned out to be enumerable in advance — and it does not reach: the
notice is not a string in a tracked file and not a fact about the tree, it arrives on a channel no
suite member can observe, and this tree carries no hook configuration for one to be attached to. The
consequence is partly checked in one place and the hole in that net is named in the rule.

**AND THE BRIEF'S ORDINAL FOR IT DOES NOT SURVIVE THE RECORD. THE BRIEF LOSES.** It called this the
second incident of the lying-monitor class. The reading it took for the first is the one ledger entry
12 adjudicated the other way, at its own site and in as many words: that watcher was not wrong. A
monitor reporting a state that changes afterwards is not a monitor that lied — it is the ordinary
condition of every observation — and collapsing the two gives back the whole of rule 12's
distinction. **One recorded incident, this one.** The divergence is recorded and the ordinal is not
carried.

#### Act 2 — the Edition 4 re-probe, and every reading carries the instant it was taken

**EDITION 4 / AEP-84 EDITION A REMAINS CURRENT AND UNHELD, WHICH IS THE EXPECTED RESULT AND A FINE
ONE.** Nothing was acquired: no document byte was fetched, no park moved, and the readings are
resolution and status only. They are in `stanag4586_pin.json` at
`the_reopen_condition_re_probed_2026_09_03` rather than restated here. **What is worth naming here
is that two of the four route families could not be asked at all**, and recording that as
"unchanged" would have been the comfortable error: the Internet Archive's CDX answered **429** to
all four queries and the distributors answered **403** to an automated read, so the pin's archive
claim and its purchase-and-DRM claim are **un-re-derivable at this hour** rather than
re-confirmed. Only the publisher's registry (403 on six paths, both with and without a browser
User-Agent) and the mirror's index (200, still exactly the two 4586 entries, editions 2 and 3) both
answered and answered the question.

**ONE LEAD IS RECORDED AND STOPPED FOR A RULING.** A route no earlier round here used — the
archive's availability API — answered 200 and reported a capture of the publisher's own Edition 4
page. **The pin's claim is not refuted**: it says no capture of any STANAG 4586 *PDF* exists, and a
captured HTML details page is not a PDF; the four CDX queries could not have found it, because that
URL carries the document's registry id and not its number. What is unverified is everything that
would matter, because replaying the capture needs the host that answered 429 in the same minute. So
it is a lead with a dated first reading and no content behind it, and acquisition is not this
round's to decide.

#### Act 3 — the standing sweeps, and the parks sweep is where the round earned its keep

**THE DISJUNCTION SWEEP FOUND NOTHING, over twelve twice-stateable facts, with the `v1.4.0` Release
body and ledger entry 12 in scope for the first time.** Read from the API at **2026-09-03
10:42:00Z**: the Release is not a draft, is what the `releases/latest` endpoint returns, was created
by the tag at 10:45:15Z on 2026-08-30 and published at 17:22:06Z — all four as entry 12 states them.
Both artefact digests, the run id, CI's passed and skipped figures, the tag-tree total, the approval
instant and the verdict count each agree at every site that states them. **AND THE SWEEP'S OWN FIRST
PASS PRODUCED TWO FALSE DISAGREEMENTS**, which is the more useful half: its patterns alternated two
*spellings* of one figure — a table cell against a sentence, and an instant with and without its
trailing `Z` — so it compared spellings and called the difference a divergence. Re-run with one
canonical capture per fact it reports zero. **A disjunction sweep whose regex alternates is a
sweep that can disagree with itself**, and the near-false finding is recorded because the
comfortable move was to write up two disagreements that were not there.

**The stale-count sweep holds at every named subject.** Roster **14** derived from the registry,
pair arithmetic **91** and **182**, ordinal **15** — different derivations over different sources,
and the ordinals module is green. **432** fixture verdicts, summed from the release notes' own
fourteen-row table and tied to the registry by its gate. The **166 / 27 / 48** message figures and
**1.4.0** unmoved. The pending-heading token gate passes with **no skip state**, verified by running
it rather than by reading about it, and the Edition 4 compatibility presence gate passes with its
scope still correct — no sentence in this repository asserts that an Edition 3 decoder reads an
Edition 4 feed.

**The rule 11 parks sweep, at table scope through the repaired regex.** The gate reports **13 rows,
9 open, 4 closed**, **7** set-claims across two rows all resolving, **3** self-membership claims
which are an observation and not a problem, and no `CLOSED MEMBER` or `PHANTOM MEMBER`. Park 12's
partition re-derived against current membership: the five it names are all still open. The
MISB-series blockers were re-checked for existence by the gate. **The two rows the gate hands to a
human are where the round's finding is**, and it printed them as its own uncovered surface, which is
the split working rather than failing:

* **Park 10 holds and was verified rather than inherited.** Its document is the Motion Imagery
  Handbook and it is not held — the `misp-2019-1` file under `spec/` is the **profile**, which the
  pin's own target field settles, and the pin states in as many words that the delegation table does
  not carry the Handbook. Its two stated routes re-read **2026-09-03**: the registry answers 200 at
  10:43:06Z, which this record already establishes is an interstitial and not a serving route, and
  the public host answers **403** at 10:43:24Z over `https`. **A 000 over `http` is a scheme
  artefact and not a new state**, recorded so the next round does not read it as one.
* **Park 8's premise is refuted, dated, and stopped for a ruling.** The findings are in the row and
  in `klv_pin.json` and are not re-derived here. **The sharper half is about the guard rather than
  the row**: the suite requires that row to keep saying the document is a purchase and pins how many
  rows say otherwise, so **it asserts a fact that lives at the publisher's host and cannot reach
  it** — green forever, because the tree agrees with itself. That is the record's own tier confusion
  one class over, a claim wearing the suite-gated label whose truth is protocol-gated. The wording
  and the guards are left standing deliberately, because editing them presumes the ruling. **The
  park's residual absences are unchanged in every term; only the price of answering them moved.**

#### Act 4 — the suite, and the difference from Act 0 is named rather than averaged

**3462 passed, 5 skipped, 4 failed at the moment this section was owed and unwritten, total 3471**,
against Act 0's **3460 / 8 / 3468**. Every part of that difference is accounted for. **The total
moved by +3** and they are this round's three new tests, the reopen-condition discovery, its date
check and its mutation check. **The four failures were the four release gates that demand this
section**, and they are what this section discharges. **The skips fell from 8 to 5, and the three
that left are the three release gates conditional on the moved set** — two that skip while the
package tree is identical to the tag, and one that skips while there is no live count to mutate.
They did not disappear; they woke up, because this round moved shipped documents. **A skip that
becomes a live test is the opposite of decay**, and reporting 8→5 without saying which three is how
a conditional gate's activation gets filed as a loss.

**AND THE FINAL READING IS 3468 PASSED, 3 SKIPPED, EXIT 0 — total 3471.** Writing this section
woke the last two, the pair that skip while there is nothing unreleased, and turned the four
failures into passes. So the round's skip arc is **8 → 5 → 3** and not one number: eight while the
tree matched the tag, five once shipped documents had moved, three once the section they were
waiting for existed. Only the **3** is a property of the tree at this commit; the other two are
readings of intermediate states and are dated as such.

**The suite was run in the foreground and its exit status read directly**, which is rule 13's own
prescription applied to the round that wrote it rather than left as advice for the next one. The
floor was re-derived AFTER this record was written, not before: **six** shipped documents, arc
**PATCH**, floor **1.4.1**, which is the same set and the same classification the section above
states — the fixed point holding, because editing an already-moved file moves neither.

### 1.4.0 — 2026-08-30 — STANAG 4586 telemetry ingest ships, and the parks regex is scoped to the table it owns

**This section carried the pending heading and a release absorbed it**, which is what that heading
is for — the token itself is elided here, because prose that spells it leaves the file carrying the
literal with no such section, and two release gates key on it. **Since 2026-08-29 a third gate
refuses the carrier outright**, `test_the_pending_heading_is_never_spelled_except_as_that_heading`,
and it has NO skip state; this round verified it exists rather than rebuilding it, and witnessed it
red against a reconstructed carrier before the roll. It is the arc since `v1.3.0`.

**What moved inside the distribution: 60 files.** The count and the set are
`gates/bump_derivation.py`'s, re-derived AFTER this record was written rather than before it — the
fixed point the repair note below insists on. The gate derives the arc as **MINOR** over **46
signals** — 41 public top-level names in `adapters/stanag4586_codec.py`, 4 in
`adapters/stanag4586.py`, and the `fixtures/stanag4586` fixture set — on the row that covers a
public top-level name appearing, so the floor was **1.4.0**. **This release is that floor taken
up**, and the number was not chosen: the gate derived it and the round adopted what it derived.

**THE TRANSITION WAS WITNESSED AND NOT ASSERTED, AND THE FIRST TWO READINGS DISAGREED FOR A REASON
WORTH KEEPING.** The brief predicted a new public top-level name would move the gate from
PATCH/1.3.1 to MINOR/1.4.0. Run at the audit, before any of this existed, it reported **PATCH**,
floor **1.3.1** — the state the brief described, measured rather than taken on trust. Run again with
both adapter modules written, it *still* reported PATCH: the files were **untracked**, and the gate
reads the distribution through `git`, so a module on disk that `git` has never seen is a module the
gate cannot classify. Only after `git add` did it report **MINOR**, floor **1.4.0**, with `unruled`
empty. **A gate that measures the index and a round that measures the working tree will disagree
silently, and the disagreement looks exactly like "the prediction was wrong".** It is recorded
because the wrong conclusion was available and cheap: PATCH twice in a row reads as a settled
answer.

The twelve modules, documents and records:
  `FORMAT_COVERAGE.md`, `MIGRATIONS.md`,
  `README.md`, `__init__.py`,
  `adapter.py`, `build_fixtures.py`,
  `pyproject.toml`, `stanag4586.py`,
  `stanag4586_codec.py`, `stanag4586_pin.json`,
  `symbology.py`, `version.py`

The twelve synthetic datagrams ship as octets:
  `a_checksum_that_does_not_validate_is_flagged.s4586`, `altitude_type_baro_never_reaches_alt_m.s4586`,
  `an_idd_version_that_is_not_edition_3.s4586`, `an_undecoded_message_type_is_parked.s4586`,
  `four_decoded_messages_one_vehicle.s4586`, `four_octet_checksum.s4586`,
  `inertial_states_wgs84_altitude.s4586`, `longitude_absent_from_the_presence_vector.s4586`,
  `no_checksum_is_not_a_failing_checksum.s4586`, `two_inertial_states_leave_the_entity_unpositioned.s4586`,
  `two_vehicles_are_two_entities.s4586`, `zero_ground_speed_yields_no_course.s4586`

each with the readable twin the adapter decodes through the same path:
  `a_checksum_that_does_not_validate_is_flagged.parsed.json`, `altitude_type_baro_never_reaches_alt_m.parsed.json`,
  `an_idd_version_that_is_not_edition_3.parsed.json`, `an_undecoded_message_type_is_parked.parsed.json`,
  `four_decoded_messages_one_vehicle.parsed.json`, `four_octet_checksum.parsed.json`,
  `inertial_states_wgs84_altitude.parsed.json`, `longitude_absent_from_the_presence_vector.parsed.json`,
  `no_checksum_is_not_a_failing_checksum.parsed.json`, `two_inertial_states_leave_the_entity_unpositioned.parsed.json`,
  `two_vehicles_are_two_entities.parsed.json`, `zero_ground_speed_yields_no_course.parsed.json`

and all twelve translate, each carrying a golden per replayed form, octets and twin, which is why
the goldens number twenty-four and not twelve:
  `a_checksum_that_does_not_validate_is_flagged.cdm.json`, `a_checksum_that_does_not_validate_is_flagged.parsed.cdm.json`,
  `altitude_type_baro_never_reaches_alt_m.cdm.json`, `altitude_type_baro_never_reaches_alt_m.parsed.cdm.json`,
  `an_idd_version_that_is_not_edition_3.cdm.json`, `an_idd_version_that_is_not_edition_3.parsed.cdm.json`,
  `an_undecoded_message_type_is_parked.cdm.json`, `an_undecoded_message_type_is_parked.parsed.cdm.json`,
  `four_decoded_messages_one_vehicle.cdm.json`, `four_decoded_messages_one_vehicle.parsed.cdm.json`,
  `four_octet_checksum.cdm.json`, `four_octet_checksum.parsed.cdm.json`,
  `inertial_states_wgs84_altitude.cdm.json`, `inertial_states_wgs84_altitude.parsed.cdm.json`,
  `longitude_absent_from_the_presence_vector.cdm.json`, `longitude_absent_from_the_presence_vector.parsed.cdm.json`,
  `no_checksum_is_not_a_failing_checksum.cdm.json`, `no_checksum_is_not_a_failing_checksum.parsed.cdm.json`,
  `two_inertial_states_leave_the_entity_unpositioned.cdm.json`, `two_inertial_states_leave_the_entity_unpositioned.parsed.cdm.json`,
  `two_vehicles_are_two_entities.cdm.json`, `two_vehicles_are_two_entities.parsed.cdm.json`,
  `zero_ground_speed_yields_no_course.cdm.json`, `zero_ground_speed_yields_no_course.parsed.cdm.json`

**THIS SENTENCE WAS WRONG IN THE COMMIT THAT WROTE IT, and it is the arc-mis-stating-the-arc class
one turn tighter than this file has caught it before.** It read *"derives **NONE**, so the floor
stays at **1.3.0** and no release is pending"*, and that was the gate's true answer **at the moment
the gate was run** — before this record existed. Writing the record moved `MIGRATIONS.md`, which is
a shipped document, which moved the arc from NONE to PATCH; so the prose was falsified by the very
commit that carried it, in the interval between running the derivation and committing the sentence
quoting it. **The count half was right throughout** — one file, and the gate agrees — which is why
every Unreleased gate passed over a section that was already wrong: they check the spelled count
against the derived set and nothing checks a quoted *kind* or *floor*. Every previous instance of
this class in this file went stale over commits or days; this one went stale over minutes inside a
single commit, and the lesson is narrower than "re-derive each round": **a derivation quoted in a
file the derivation reads must be re-run after the file is written, not before.** Repaired
2026-08-29 in the commit below; the repair is a fixed point, because editing an already-moved file
changes neither the set nor its classification.

#### The acquisition round — STANAG 4586 telemetry ingest, built on an edition that is not the current one

**THE ROUND'S CENTRAL FACT IS THAT ITS FIRST BLOCKER COULD NOT BE DISCHARGED THE WAY THE BRIEF
IMAGINED, AND THE FORK WAS PUT UP RATHER THAN TAKEN.** The brief opened the edition question
explicitly — "Edition 4 is believed current — verify, don't inherit this brief's belief" — and the
belief **held**: Edition 4 is current, dated 2017-04-05, promulgated as AEP-84 Edition A. What the
brief did not anticipate is that the current edition is **not obtainable**. Every route was tried
and each refusal is recorded with its shape: `nso.nato.int` answers HTTP 403 on six distinct paths
with and without a browser User-Agent; the Internet Archive holds **no capture of any STANAG 4586
PDF at any URL**, checked by four CDX queries; the one mirror carrying this family lists exactly
two editions, 2 and 3; and the commercial distributors that hold Edition 4 serve it paywalled and
**DRM-wrapped**. That is park 8's class — procurement, not procedure.

**† SUPERSEDED 2026-09-03 BY THE PUBLISHER ROUND, AND THE SENTENCE ABOVE STANDS.** Park 8 was not
park 8's class. SMPTE ST 336 is served free from `pub.smpte.org/doc/st336/`, both editions were
obtained at no cost on 2026-09-03, and the park **closed**. The correction is placed here rather
than in the sentence because this is a round record and the sentence is a true statement about what
the acquisition round believed — **and because this is the site the classification sweep lands on**,
which is the whole of README rule 9's placement discipline. **Nothing about the Edition 4 ruling
moves**: `nso.nato.int` still answers 403, the Archive still holds no capture, and the commercial
distributors really do serve Edition 4 paywalled and DRM-wrapped. What is gone is the *comparison* —
there is no longer another park in this repository whose reason is procurement, so Edition 4 is the
only instance of the class rather than the second one.

**The round stopped there rather than choosing.** Two branches were live and materially different:
park on Edition 4 and ship nothing (Acts 2 and 3 skipped, adapter count staying 13 everywhere), or
pin the obtainable Edition 3 and build against a superseded document. The ruling — **pin Edition 3
and build, with the edition named at every site** — was given to the round, not made by it, and it
is recorded at `fixtures/stanag4586/spec/stanag4586_pin.json`'s `edition_ruling` with the
alternative named, because a later reader who finds an adapter built on a superseded standard is
owed both the reasoning and the fact that the other branch existed.

**WHAT THE RULING DOES NOT LICENSE, and it is asserted by a test rather than promised.** No sentence
anywhere claims an Edition 3 decoder reads an Edition 4 feed. Edition 4 changed the vehicle
identifier list and added mission-phase and autonomy messages — changes landing on exactly the
tables the row set tabulates — so the compatibility question is left **open**.
`test_both_modules_carry_the_disclaimer_rather_than_merely_not_claiming_edition_4` requires both
shipped modules to say Edition 4 is current, is not held, and is not what they decode; **silence is
the failure**, because a module mentioning neither edition would pass any absence check ever
written. That test is itself a repair: its first draft swept for phrases like "reads an Edition 4
feed" and required their absence, and **failed against a correct tree** — the adapter's docstring
carries that exact phrase inside its own negation. A substring sweep cannot tell a claim from its
denial, which is sweep rule 9's lesson arriving in a test instead of in prose.

**Act 0, and the audit's own figures.** Tree clean, `HEAD` equal to `origin/main` at `d463edd` — a
descendant of the `7895083` the brief named, which is what the brief allowed for. Suite **3394
passed, 3 skipped** at the start. The untouchables hold, each by its own command: the pinned phrase
derives to **35** over the git index, `scripted_edit`'s contract is green at **9**,
`RELEASE_NOTES.md` opens **1.3.0**, and `git ls-files` matches **no** PDF. The bump gate derived
**PATCH** with the floor at **1.3.1**, which is the state the brief described, measured rather than
taken on trust. `nga.mil` resolved `NOERROR` for the apex, `gwg` and `nsgreg` alike at
**2026-08-30 08:58Z**, resolution only, no route asked for bytes. Pin-as-control through the
resolver: **20 copies present, 20 matched, 0 failed** before any new byte was trusted.

**The new sweep subject was verified and joined the surface.** The GitHub Release at `v1.3.0`
states two artefact digests. Both were matched against run `33247697980`'s own log — the gate's
`--export-dist` output, the publish job's pre-upload hashes and the in-toto DSSE statements all
carry `5cb8e3fc…9343a` for the wheel and `55a1e9f2…24fc5` for the sdist, and the release body's
figures equal them. **The release body's other figures are dated and must NOT move with the tree**:
its "13 adapters" describes the 1.3.0 artefact, and this round's adapter does not change what that
release contains.

**Act 1 — the pin, and a second party that disagreed by one byte.** STANAG 4586 Edition 3 is pinned
at `fixtures/stanag4586/spec/STANAG_4586_Ed3.pdf`, SHA-256 `a4fa6e54…c15da`, **3 852 365 octets**,
**509 pages** by the ruled `/Pages` walk, by pypdf's independent walker and by the `/Count` the page
tree declares — three statements agreeing. The digest was recomputed at the landed path and
`.gitignore:42`'s extension rule covered it with **no new rule needed**, which is that rule's own
note making good on itself.

**THE IDENTITY WAS ATTESTED BY TWO PARTIES AND THE SECOND ONE DID NOT MATCH.** A 2019-11-20
Internet Archive capture of the same URL was fetched and verified against the archive's own CDX
digest, then compared. The two copies are **one byte apart** — 3 852 365 against 3 852 364, with
completely different SHA-256s — and a round that stopped at the sizes would have called them the
same file or called them different documents, and both would have been wrong. The divergence begins
at byte offset 3 675 201, **inside PDF object 2389, which is the mirror's own download stamp**,
declared `/Length 205` in one copy and `204` in the other and drawn at a different x-offset. Text
was then extracted from all 509 pages of **both**, the stamp stripped and whitespace normalised, and
the two digest **identically** with **zero** pages differing. The standard's content is the same
across seven years; the only thing that moved is where the mirror paints its own name. This is the
1.3.0 release's "a size is not an identity" lesson inverted — there, two *different* wheels shared
one size; here, one document has two sizes.

**The document dates itself nowhere, and that is a positive reading rather than a failed
extraction.** Its front matter carries no date and no `NSA/` promulgation reference — pages 1–20
swept for both, returning zero — and its RECORD OF AMENDMENTS is **present and empty**, where
Edition 2's copy carries one row. So the "09 NOV 2012" identifying the edition is the distributor's
catalogue metadata and is **external to the pinned bytes**, recorded as such. That is STANAG 4676's
situation reached by a different route.

**Act 1 also produced the round's one refused instruction, and the refusal is a category error the
brief could not have seen.** It asked for a new **parks-table row**. `FORMAT_COVERAGE.md`'s parks
table is not a general blocker register: its column header reads "Reason, grounded in the delegation
table", all thirteen rows are MISB documents **MISP-2019.1 delegates to**, and its preamble derives
counts over that set. STANAG 4586 is delegated by nothing here, so a row would be an entry no reason
cell could ground and would falsify three counts in the paragraph above it. **And it would have
broken a gate invisibly**: `gates/parks_table.py`'s row pattern is applied to the WHOLE FILE — 13
lines match it and the gate reports 13 parks — so a second bold-numbered table anywhere in the
document would be absorbed into the parks set and cross-referenced against park closures as though
its rows were parks. The two blockers are recorded instead in the 4586 section's own **lettered**
table, which that pattern cannot match, and the gate still reports **13 rows, 9 open, 4 closed, 7
set-claims, 0 failed** with the new table present. **Both blockers are discharged**, so nothing is
parked and the only survivor is Edition 4's reopen condition.

**Act 2 — the coverage, derived rather than remembered.** The section enumerates **all 166 message
field tables** the document defines, numbered 1 to 51000, across **27 functional groups**, with
**none unclassified** — derived by walking every `Table B1-N: Message #M:` caption in the body with
the List of Tables excluded so its dotted leaders are not read as captions. Three transcription
traps were met and each cost a wrong count before it was fixed: the payload tables carry an extra
`Payload Type` column that defeats a fixed-column row regex; the System ID group's messages are
numbered 1, 2 and 3, which a `\d{4,5}` pattern silently drops; and two messages are named "Fuel,
Oil & Hydraulic", which a name character class without `&` silently drops. **The first count was
163 and the derived answer is 166**, and the difference is entirely those two classes.

**The 48 command messages are enumerated under an OUT OF SCOPE heading rather than omitted**, by
group and by number range, with the ruling's two reasons stated — the CDM has no command or tasking
kind for them to translate into, and emitting DLI edges toward being a UCS component. The
consequences are structural rather than declared: the shipped codec has **no encoder at all** (the
frame builder lives in the generator, which `gates/bump_derivation.py:295` correctly excludes from
public surface), the adapter's direction is `ingest` which `adapter.py` enforces at
class-definition time, and a test names eleven command message numbers and requires each to be
absent from the decoded set. **The seven mixed groups are named as mixed** rather than counted
either way, with a note that the message-by-message split has not been drawn because none of them
is decoded.

**Act 3 — the adapter, and the two calls that are load-bearing.** `stanag4586 1.0.0`, ingest, on a
decode-only layer. Four messages are decoded field by field — `#4000` Inertial States, `#3002`
Vehicle Operating States, `#3009` Air and Ground Relative States, `#3010` Body-Relative Sensed
States — and every other message has its wrapper read and its data parked verbatim, which is
`stanag4609`'s ST 0107.3-04 treatment of an unwitnessed tag.

* **`PositionSource` is `INERTIAL` and not `GNSS`, and this is the most safety-loaded line in the
  file.** That field exists so a jammed-area warning can discriminate a fix from a guess. The
  message carrying the position is named **Inertial States** and the document states no GNSS source
  anywhere in it; a real airframe's INS is usually GNSS-aided, but that is knowledge about airframes
  and not something the datagram says. Read off the message's own name — the only evidence there is
  — and it is the safe direction of the two.
* **Where a datagram carries two positioned `#4000` for one vehicle, the `Entity` takes NO position
  and says why**, while the `Track` carries both as samples. Picking "the latest" would be a
  decision made inside a translator, which `adapter.py`'s contract forbids in as many words.

**This format can do what `stanag4609` could not, and the gain is the format's rather than the
adapter's.** Every wrapper carries a Source ID whose stated purpose is to "uniquely identify any
entity in an arbitrarily formed system", so `entity_id` derives from the wire's own identifier and
is **stable across datagrams with the adapter remembering nothing**. A first-draft defect is worth
recording: the id was derived from the raw integer while `SourceId.external_id` published the dotted
`7.0.1.1` form, so a consumer re-deriving the id from the identifier the object publishes would have
got a different UUID — and `Track.track_id` already used the dotted form, so the adapter disagreed
with itself across two objects it emits together. Caught by a test asserting both halves.

**Five ambiguities are registered and none is resolved by guessing.** The sharpest is the third:
Altitude Type value 3 reads **"WGS-84 (geoid)"**, which names an ellipsoid and an equipotential
surface in four words — they differ by roughly −107 m to +85 m — and it is the *only* one of four
values that could ever populate `Position.alt_m`, documented "Metres HAE". The value is carried and
every object built from one states the ambiguity; types 0, 1 and 2 park and never reach `alt_m`.
What is refused is treating type 3 as ellipsoidal because the CDM wants HAE and "WGS-84" is the
nearest word. The first is an **extraction limit rather than a defect in the standard**: Figure
B1-8's bit-number row extracts scrambled, so where the two-bit Checksum Length subfield sits inside
bits 7:0 is unrecoverable from this copy's text layer — the codec therefore **derives the checksum
width from the frame arithmetic**, reads the subfield as a second statement, and records a
disagreement rather than resolving one.

**THE BUMP GATE'S TRANSITION WAS WITNESSED, AND THE FIRST TWO READINGS DISAGREED FOR A REASON WORTH
KEEPING.** Before the adapter existed it derived **PATCH**, floor **1.3.1**. With both modules
written it *still* reported PATCH — the files were **untracked**, and the gate reads the
distribution through `git`, so a module on disk that `git` has never seen is one the gate cannot
classify. Only after `git add` did it report **MINOR**, floor **1.4.0**, `unruled` empty. A gate
measuring the index and a round measuring the working tree disagree silently, and the disagreement
looks exactly like "the prediction was wrong" — PATCH twice running reads as a settled answer.

**Act 4 — the sweeps, and three figures that were wrong before they were derived.** The stale-count
sweep moved the roster from 13 to 14 across every live site and left the dated ones alone: nine
prose sites, the pair arithmetic from seventy-eight to **ninety-one** (and 156 against 78 to **182
against 91**), `adapter.py`'s `fixture_dir` note from "eleven of the thirteen" to "twelve of the
fourteen", the release procedure's "all thirteen harnesses", the package README's roster table, the
release notes' table, and both `pyproject.toml` voices. Nine sites went to `TREE_EXEMPT` with their
grounds — dated round records, past deployment readings and three release-verification blocks, each
a separate row because a single row quoting the common prefix would exempt a future stale one.

Three findings came out of deriving rather than asserting:

1. **The ordinal is 15 and the roster count is 14, and the brief conflated them.** Ordinals 1–14
   were already assigned because #9 is `stanag5527`'s Phase 1 specification with no adapter, so
   thirteen shipped adapters occupied fourteen ordinals. A round predicting the ordinal from the
   roster count collides with `cat023`, and this one did before the ordinals gate caught it.
2. **The egress-capable count did NOT move** and stays at eleven, because the new adapter is
   ingest — sweep rule 6's "know which counts are not drift". What moved beside it is the
   ingest-only count, two to **three**.
3. **"the eleven that translate" was wrong and all twelve do.** The figure came from assuming that
   the fixture yielding an `Entity` with no position and no `Track` was a refusal. It is not: an
   `Entity` stating no position **is** a translation, and that distinction is the one the fixture
   exists to draw. Repaired at both sites, and 12 × 2 = 24 goldens is now arithmetic rather than
   recollection.

**A disjunction guard was added rather than a third statement tolerated.** The pinned digest, byte
count and page count are stated in three files — the pin, the codec's docstring and the coverage
section — and collapsing to one site is not available, because a codec whose docstring does not name
the bytes it was written from is what the pin discipline exists to prevent. So they are gated, with
the abbreviated digest checked as a prefix-and-suffix of the full hash rather than as a substring.

**Untouchables re-verified at the close, each by its own command:** the pinned phrase derives to
**35** over the git index — **re-derived and unmoved**, which is why that guard exists, since sixty
new files could have carried the phrase — `scripted_edit`'s contract is green at **9**,
`RELEASE_NOTES.md` opens **1.3.0**, and `git ls-files` matches **no** PDF. Pin-as-control after the
new pin: **21 copies, 21 matched, 0 failed**, 22 pairs across 7 of 9 pin files.

**WHAT THIS ROUND DID NOT DO.** **Nothing outward**: no tag, no release, no PyPI upload, no
deployment. `PACKAGE_VERSION` is unmoved at **1.3.0** and `SCHEMA_VERSION` at **1.0.0** — the gate
moved the *floor* to 1.4.0 and a floor is not a release. *(Annotated 2026-08-30: the release round
below took that floor up, so `PACKAGE_VERSION` now reads 1.4.0. This paragraph is left as the
acquisition round wrote it — it is a dated reading of that round's tree, and editing it would make
the record assert a state nobody measured. `SCHEMA_VERSION` is still 1.0.0 and that half needed no
annotation.)* **No command message was decoded and no
encoder was written.** No park was closed and none was opened. No document was fetched for any other
format, and the `nga.mil` reading is resolution only.

#### The maintenance round — the carrier grep becomes a gate, and two briefed facts do not survive reconstruction

**THE ROUND'S RETURN IS THAT BOTH THINGS IT WAS SENT TO MECHANIZE WERE MIS-DESCRIBED IN THE BRIEF,
AND THE TREE SAYS SO IN BOTH DIRECTIONS.** The defect is real and the gate is written; the account
of *why no gate caught it* is wrong, and correcting it moved the gate's design. A hand-carried
tally that no command reproduces turned out to have drifted in both directions. Neither was
findable by re-reading — both needed the state rebuilt and the derivation re-run.

##### Act 0 — the audit, and a tally that had drifted in both directions

Tree clean, `HEAD` equal to `origin/main` at `7895083`. Suite **3392 passed, 3 skipped** before
anything moved. The untouchables hold, each by its own command: the pinned phrase derives to **35**
over the git index, `scripted_edit`'s contract is green at **9**, `RELEASE_NOTES.md` opens
**1.3.0**, and `git ls-files` matches **no** PDF. **The bump gate was run and not copied**: it
derives the arc since `v1.3.0` as **PATCH** with the floor at **1.3.1**, which is what the section
above already says — the previous commit's repair is a fixed point and this run is the check of it,
not a restatement. `--mutation-check` passes all five fixtures. **Pin-as-control through the
resolver, decomposition derived:** **21** `local_path`+`sha256` pairs stated by **six of the eight**
pin files, resolving to **20** distinct copies — 18 spec and 2 streams, twelve of the spec copies
under `fixtures/klv/spec` — **20 present, 20 matched, 0 failed**. Identical in every part to the
three runs before it. **Fresh clone at `v1.3.0`: 3331 passed, 64 skipped**, reconciling with the
working tree's **3392 + 3** at the same **3395** total, which confirms the figure the round below
recorded rather than carrying it.

**The `nga.mil` series is extended by one reading, resolution only.** At **2026-08-29 15:16Z** the
apex, `gwg` and `nsgreg` all answered `NOERROR`, from `192.168.0.1` as every prior reading. No
route was asked for bytes. **The hour is the reason this one is worth its line**: the single
SERVFAIL episode is a ~14:00–15:00Z observation, and this reading is the closest to that window
since the 14:08Z probe that first retested it. It does not fail either.

**AND THE TALLY IT WAS SUPPOSED TO CARRY IS NOT MONOTONIC, WHICH IS A FINDING.** The round above
records *eleven* successes at **10:10Z**. The round before it records *fifteen* at **09:21Z** — an
earlier reading with a higher count. A series that only ever grows cannot do that, so at least one
of the two is wrong and re-reading either sentence cannot say which. **Derived instead of carried**,
using the counting unit the record itself states — one timestamped probe of all three names — the
readings are: 2026-08-27 20:20Z and 21:03Z; 2026-08-28 10:56Z, 11:49Z, 13:44Z, 14:08Z, 18:23Z,
19:47Z, 20:17Z and 21:14Z; 2026-08-29 07:59Z, 08:49Z, 09:21Z and 10:10Z. **Fourteen, so this
round's is the FIFTEENTH**, against the one SERVFAIL episode. The stated series drifted in both
directions: it was **two too high** at 09:21Z and **three too low** at 10:10Z, and the step from
*four* at 11:49Z to *eight* at 14:08Z adds four for two probes.

**Class: an underived figure doing exactly what an underived figure does, at the one site that had
already said so.** The 07:59Z reading records that the tally *"is the one figure in this record that
no command reproduces"* — the defect and its own diagnosis were written in the same sentence, one
round apart. **The dated tallies are NOT rewritten.** Each was a round's reading of its own moment
and a dated round narrative is a historical artefact; the correction belongs beside the claim and
not on top of it, which is the ruling this file already applied to the retired `Entity.source_ids`
phrase. What changes is that the count above is derived from the timestamps and shows its work, so
the next round has something to check rather than something to increment.

##### Act 1 — the carrier gate, and the blindness it was briefed to close is not the blindness that exists

**The defect, which is not in dispute.** Four checks in `tests/test_cdm_release.py` key on the
literal pending-arc heading, and every one asks the same question of the same file: is that string
IN `MIGRATIONS.md`? **None asks whether the occurrence it found is a heading.** So a sentence of
prose that spells the heading — to quote a gate's refusal message, or to say the section has just
been absorbed — answers all four in the affirmative on behalf of a section that may not exist.
Three consecutive rolls recreated it: `96f5920`, the same shape again while that repair was being
written, and `148e7a6`, where the rolled section's opening sentence named the heading it had just
absorbed. The third was caught by a human following the previous repair's written instruction to
grep after rolling. **A defect caught three times by an instruction, while the gates that key on the
string stay green, is past the mechanization threshold** — that part of the brief holds and the gate
is written to it.

**THE BRIEF'S ACCOUNT OF WHY THE GATES MISSED IT DOES NOT SURVIVE REBUILDING THE STATE.** The brief
and `4f1932f` both record that on the third occurrence *"both watching gates were structurally
blind, skipping because the bumped version had no tag yet"*. Rebuilt — `148e7a6` in an isolated
clone, `v1.3.0` removed there and nowhere else, the elided sentence restored to the form the repair
describes — **that is not what happens.**
`test_the_unreleased_section_is_the_first_thing_under_history` **STOPS** skipping, because the
carrier is precisely what makes the presence test true; it then reads the real headings, finds the
released one first, and goes **RED**. Three tag-conditional checks skip, and
`..._states_that_it_is_in_no_release` passes **green while reading a paragraph of prose as the
section body**. So the tag blinded three checks that were never watching for this, one check would
have refused the tree, and one answered a question about a sentence.

**THE FULLY BLIND STATE IS THE OTHER ONE, AND IT IS THE FIRST OCCURRENCE'S SHAPE.** Rebuilt at
`4f1932f` with a carrier added beside a genuine heading, **every check passes or skips and nothing
in the tree objects.** That is the state `96f5920` was actually in — the literal three times, one of
them a heading — and it is the state that **survived a release**. It is legal to every gate and it
is wrong, and it is what the new check is aimed at. **Had the gate been written to the brief's
account it would have been built around the tag condition, which is not the mechanism.**

**The gate: `test_the_pending_heading_is_never_spelled_except_as_that_heading`.** It splits every
occurrence in `MIGRATIONS.md` into genuine headings and carriers and requires the carrier list to be
empty, plus at most one heading, because the checks it protects resolve the section with `index`
and silently ignore the rest. A heading inside a code fence is a carrier however it is indented — it
reads as a section to every presence test. The subtitle form is a heading and not a carrier, so the
gate is not stricter than the checks it exists to protect. **NO SKIP STATE, and that is the design
point rather than a convenience**: not on git, not on a tag, not on the token being absent. A check
whose subject is *an occurrence that should not exist* cannot be conditioned on occurrences
existing, which is the circularity that let the first occurrence live through a release. It reads
one file that ships inside the wheel, so it holds on a clone and in an unpacked sdist.

**WITNESSED RED THREE TIMES, ONCE ON BYTES NOBODY RECONSTRUCTED.** On `96f5920`'s **real committed
`MIGRATIONS.md`, unmodified** — two carriers, one heading, the quoted refusal message at lines 2164
and 2165. On the third occurrence rebuilt — one carrier, no heading. On a carrier beside a genuine
heading — one carrier, one heading, the state every existing check passes. And **green on
`6c0615a`, `b7a5474`, `feca9dd`, `e79f81a` and `7895083`**, so it discriminates rather than
objecting to everything. Its non-vacuity witness is hermetic text rather than a checkout, because
the third occurrence was repaired before it was committed and there is no tree to check out — a
witness that needed git would have to skip without one, which is the property being retired.
Verified to run with `.git` removed entirely.

##### Act 2 — the size collision, verified in place rather than placed again

**Existence check first, and it is a verification note.** Both conditions the brief set are already
met. The incident sits at the rule's own site — `PUBLICATION.md` entry 11 — where the published
wheel's **3 960 762 bytes** and the local rebuild's **identical 3 960 762** are stated with their
two different digests, immediately above the sentence the rule is: the served-versus-built check
compares the **workflow's** digests and never a rebuild's. The local rebuild's digest occurs
**exactly once in the tree**, at that site, so rule 9's "cited once, at the rule's own site" holds
as written. The round record above cites entry 11 for the verification instead of restating the
digests. **Nothing was placed and nothing was moved.**

**A near-false finding, caught before it was reported.** A first pass looked for the standing claim
in each release's notes and found it at 1.1.0, 1.2.1 and 1.3.0 but **not at 1.2.0**, which would
have made the brief's *"claimed since 1.1.0"* false and the claim's continuity broken by a release.
It is there: at 1.2.0 the sentence is **line-wrapped** between "two builds of" and "one tree", and a
`grep -c` for the phrase cannot cross the newline. The claim is continuous from 1.1.0. **Fifth time
the record has been right against a crude derivation, and the second whose cause is a wrapped
line.**

##### Act 3 — the sweeps at the new values

**The disjunction and stale-count sweep over the version figures is a NON-FIND, and it is stated
rather than reported as clean by silence.** Every `1.2.1` still in the tree was read and classed:
55 in `MIGRATIONS.md`, 32 in `PUBLICATION.md`, 9 in `gates/bump_derivation.py`, 8 in
`tests/test_cdm_bump_derivation.py`, 7 in `klv_pin.json`, 6 in `RELEASE_NOTES.md`, 4 each in
`tests/test_cdm_release.py` and `FORMAT_COVERAGE.md`, 2 in `tests/test_cdm_deploy_record.py` and 1
in `version.py`. **Not one asserts 1.2.1 as the current distribution.** They are dated release
records, ledger entry 10, the bump gate's founding incident, test fixture strings, and — in
`RELEASE_NOTES.md` and `version.py` — correct live statements *about the arc from* `v1.2.1`, which
is what a release's notes are for. The live current-version claims agree with each other and with
the tree: `docs/docs/changelog.mdx` reads **1.3.0**, `version.py` reads **1.3.0** in both its
constant and its prose, the witness table's index row reads 1.3.0 and the 1.2.1 row is struck and
superseded. `README.md`'s single occurrence is its documented annotated-tag command, whose version
its own gate holds to `PACKAGE_VERSION`. **The command form is described here and not reproduced**,
and that elision is a repair made during the 1.4.0 round rather than a style choice: spelled out,
this dated record reads to `test_every_documented_tag_command_names_this_trees_package_version`
as a live instruction naming a superseded version, and it went red on it. It is the pending-heading
carrier class on a second gate — a record that quotes a command becomes a command.

**Rule 11's parks sweep at table scope, by the gate:** **13 rows — 9 open [2, 3, 5, 6, 7, 8, 10, 11,
12] and 4 closed [1, 4, 9, 13]**, 7 set-claims across 2 rows, 3 self-members, blockers re-derived by
series number, **0 failed**. Unchanged in every part from the round above.

**Park 5's row was checked against the tag, and the brief mis-states what it claims.** The brief has
it claiming *"1.3.0 shipped the codec"*. The row does not say that: it says `adapters/imapb_codec.py`
landed in `431b0c5` and that the bump gate **moved the floor to 1.3.0 by itself**. Both are true of
this tree and they are different claims — a floor is not a release, which is the distinction the
section above this one exists to keep. Verified against the tag rather than read: `431b0c5` adds the
file at **309 lines**, exactly as the row says; the codec **is** in the `v1.3.0` tree and **absent**
from `v1.2.1`, so the codec did ship in 1.3.0 and `431b0c5` is inside that arc. The row's live
negative holds too — `imapb` occurs **four** times in `FORMAT_COVERAGE.md`, all of them as a file
path, **none** in the adapter name-and-version form that `stanag4609` carries 38 times. **No repair;
the row is right and the brief's paraphrase is what was wrong.**

**Rule 10 over the index the release round touched.** The witness table's four new entry-11 rows are
dated 2026-08-29, each names a probe that exists, and the section each cites — `### 1.3.0` — is a
heading `MIGRATIONS.md` actually has, which the citation gate re-derives. The superseded index rows
are struck rather than deleted and carry what superseded them.

**Finding 3's lesson applied as a check and not as a sentence.** The derivation this record quotes
is the bump gate's, and the gate reads `MIGRATIONS.md`, which this record moves — the exact
configuration that falsified the sentence one commit above. So it was re-run **after** this section
was written, and the figures here are that second run's.

**WHAT THIS ROUND DID NOT DO.** No document was fetched and no route was asked for bytes — the DNS
reading is resolution only. No pin was added and no digest changed. **Nothing new was written under
`packages/` except this record**: the only code this round adds is in `tests/`, which does not ship,
so the moved set inside the distribution is one file and the count above is unchanged. No adapter,
model or fixture moved, `SCHEMA_VERSION` is unmoved at 1.0.0 and `PACKAGE_VERSION` at 1.3.0. **No
park was closed, no bump ruling was installed, no release was made, and nothing went outward.**

#### The reversal round — 1.3.0 shipped, and both rulings stand

**THE RULING FIRST.** The maintainer refused this release on **2026-08-28**. The operator
**reversed** that refusal on **2026-08-29**, and 1.3.0 published the same day. Both are in the
record: the refusal as a dated reading with the step it failed, the reversal as the decision that
outranks it. **No history was rewritten** — the unwind arc at `86cbf9e` stands as committed and
this release re-derived forward from the tip rather than restoring anything.

**The step the refusal turned on does not exist, and this round corrected its own brief before
acting on it.** The 2026-08-28 brief conditioned the release on *"the release protocol's step C"*
and a dated PyPI token witness; the procedure states five numbered conditions and no lettered
steps, and the only lettered steps in the tree are `PUBLICATION.md` entry 6's, whose step C closed
**2026-08-26**. That was refuted last round at its own site and nothing this round waited on it.
**The carrier sweep for it is a non-find**: every site naming *step C* or a token witness is either
entry 6's genuine closed step or one of the refutation's own paragraphs. No site asserts the
withdrawn obligation, so nothing was repaired and the sweep's result is that there was nothing to
repair.

#### Act 0 — the audit, and its figures

Tree clean, `HEAD` equal to `origin/main` at `feca9dd`, a descendant of `86cbf9e`. Suite **3392
passed, 3 skipped**. The untouchables hold, each by its own command: the pinned phrase derives to
**35** over the git index, `scripted_edit`'s contract is green at **9**, `RELEASE_NOTES.md` opened
**1.2.1** on the index, and `git ls-files` matched **no** PDF. The bump gate was **run and not
copied**: declared 1.2.1 a PATCH over `v1.2.0`, with the pending arc deriving **MINOR** and the
floor at **1.3.0**, which is the derivation that decided the number rather than the brief.

**The `nga.mil` series is extended by one reading, resolution only.** At **2026-08-29T10:10Z** all
three names answered `NOERROR`. That is **eleven** successes against the single SERVFAIL episode,
and it is a reading — one timestamped probe of all three names — which is the counting unit every
increment in this record uses.

**Pin-as-control ran through the resolver and its decomposition is derived, not recalled.**
`gates/pin_paths.py`: **21** `local_path`+`sha256` pairs stated by **six of the eight** pin files,
resolving to **20** distinct copies — 18 spec and 2 streams, twelve of the spec copies under
`fixtures/klv/spec` — with **20 present and 20 matched, 0 failed**.

#### Act 1 — the release, re-derived forward

Every mechanic was re-run from scratch and **nothing was cherry-picked from the refused attempt**,
which contributed no bytes. The gate derived **MINOR over `v1.2.1`** on thirteen public top-level
names in `adapters/imapb_codec.py`, with no ambiguity and so no bump ruling. `SCHEMA_VERSION` moved
only if its own categories said so and they did not: the diff over `schemas/` since `v1.2.1` is
empty and no model changed.

**The four guards were watched failing before they were repaired**, which is the part a green suite
cannot show. Three move by editing — the two-version literal pin, the notes' opening line, and the
documented `git tag -a` commands — and the fourth,
`test_the_json_measurement_is_what_a_round_would_quote`, is red **by construction** between the
bump and the tag and went green on the tag rather than on an edit, exactly as this file records.

**THE PROSE-CARRIER INCIDENT REPEATED ITSELF INSIDE THE COMMIT THAT ROLLS THE SECTION, and that is
the strongest result the last round's repair could have produced.** The rolled section's own
opening sentence spelled the pending heading in order to say it had been absorbed — leaving the
file carrying the literal token with no such section, which is precisely the defect repaired on
2026-08-29 one commit earlier. It was found by grepping the token after the roll, as that repair's
record instructs, and not by a gate: both gates that key on the string were skipping, because the
version had no tag yet. **A repair whose own record tells the next round how to catch the repeat is
worth more than a gate here**, and the token is elided with the sentence saying why.

**A NEAR-FALSE FINDING OF THIS ROUND'S OWN, caught by re-deriving rather than by reporting.** A
first pass concluded that **none** of the fourteen IMAPB rows reads `not yet` — which would have
contradicted the release notes being written beside it. The cause is this record's own counting
trap one turn further on: the row regex `^\| `\d+` \| ` matches **two different tables** keyed by
the same tag numbers, the ST 0601 tag table and the IMAPB worked-example table, and collapsing them
into one map by tag let the second overwrite the first. Scoped by column count the answer is
**141 tag-table rows, 115 reading `not yet`** — the record's own 115, reproduced — with all
fourteen IMAPB rows among them. **The disagreement was the reader's and the record was right**,
which is the fourth time that sentence has had to be written and the first time about a table
collision rather than a wrapped line.

**Park 5's row is repaired and its own note is the citation.** The row asserted `PACKAGE_VERSION`
*stays* 1.2.1 inside a realised forecast; the refused round left it standing, recorded that the
refusal made it true again, and wrote that *"the next release will falsify it"*. This is that
release. The clause now states what happened, what held — `SCHEMA_VERSION` at 1.0.0 — and that the
floor's own reading survives, the gate's MINOR and the decision to ship having been six days apart.

#### Act 2 — published, and verified against the bytes

Run **33247697980**, triggered by the `v1.3.0` tag: build green on every step, then the `pypi`
environment held the upload for twenty-one minutes until a required reviewer approved at
**10:47:24Z**. **The approval was the operator's alone.** Before pushing, the environment's
`required_reviewers` protection was verified rather than assumed — a tag pushed at a workflow with
no reviewer on its environment would publish unattended, and that is the one thing the plan rested
on.

**Six readings of each digest agree**, and the served bytes were fetched and re-hashed rather than
trusted, with the body read before the status was believed. **The size trap is demonstrated instead
of asserted**: this round's local build, made for `twine check --strict`, produced a wheel of
**exactly the published wheel's size** and a different digest. A size comparison would have called
two different files identical, which is why the check compares the workflow's digests and never a
rebuild's. `PUBLICATION.md` entry 11 carries the whole verification.

#### Act 3 — the sweeps, and what they found

**The version-figure sweep moved two sites and no others.** Both are index claims —
`docs/docs/changelog.mdx`'s live sentence and the witness table's row — and both moved only after
the artefact was actually on the index, on the rule the 1.2.1 release followed. Every remaining
1.2.1 is a dated round reading exempt under sweep rule 6 or a historical reference to a released
tag. **The parks sweep ran at rule 11's table scope**: 13 rows, four closed and nine open, 7
set-claims across 2 rows, no `CLOSED MEMBER` and no `PHANTOM MEMBER`, 0 failed.

**The ledger count gate's word map stopped at ten, and an eleventh entry is what found it.** It
derives the count from the headings and requires two prose sites to state it in words; the map had
no entry for eleven, so the gate refused with its own instruction to extend it. Extended to
fifteen rather than to eleven, because a bound that is met again next round is the same defect.

**Untouchables re-verified at the close, each by its own command:** the pinned phrase derives to
**35** over the git index, `scripted_edit`'s contract is green at **9**, `RELEASE_NOTES.md` opens
**1.3.0**, and `git ls-files` matches **no** PDF. **Exactly one of the four cites the version** and
it moved with the release under its own guard, which reads `PACKAGE_VERSION` rather than a literal.
The bump gate re-derives the arc since `v1.3.0` as **NONE** with the floor at **1.3.0**. Fresh
clone at the tag **3331 passed, 64 skipped**, reconciling with the working tree at the same
**3395** total.


#### The release round, 2026-08-30 — the number was derived, one pre-check was already built, the other was not, and the first witness of the one that was not proved nothing

**Act 0, and the audit's own figures.** Tree clean, `HEAD` equal to `origin/main` at `d6f9ef3`.
Suite **3459 passed, 3 skipped** at the start. **The untouchables hold, each by its own command**:
the pinned phrase derives to **35** over the git index, `scripted_edit`'s contract is green at **9**
(`pytest -k scripted_edit` collects **11**, which is the recorded trap and not a disagreement),
`RELEASE_NOTES.md` opened **1.3.0** on the index, and `git ls-files` matches **no** PDF. Of the
four, exactly one cites a version and therefore moves this round — the notes — and its before-state
is recorded here as `# synapse-cdm 1.3.0`. The other three are version-free and are unchanged at the
close.

**The bump gate was run fresh from the tracked index and its derivation decided the number.** The
arc since `v1.3.0` derives **MINOR**, floor **1.4.0**, over **46 signals**. The brief predicted
MINOR and floor 1.4.0 and the prediction held, but the round adopted the gate's answer rather than
the brief's: the two agreeing is a fact worth recording precisely because it is not what makes the
number right.

**`SCHEMA_VERSION` was checked and not assumed.** `git diff v1.3.0..HEAD -- schemas/` is empty, and
no path matching `schema` appears in the arc's name list at all. It stays **1.0.0**, and the release
is a package MINOR with no wire movement — the arrangement `version.py` argues two numbers exist
for.

**The `nga.mil` resolution series is extended by one observation.** `NOERROR` for the apex, `gwg`
and `nsgreg` alike at **2026-08-30 10:26Z**, resolution only, no route asked for bytes, from
`192.168.0.1` as every prior reading.

**Pin-as-control through the resolver, and the decomposition derived rather than stated.** **22
`local_path`+`sha256` pairs stated by 7 of 9 pin files** — `cat021/spec/sac_pin.json` and
`legion/spec/openapi_pin.json` state none — resolving to **21 distinct copies, all present, all
matched, 0 failed**. By location: 19 under `spec` bases and 2 under `fixtures/klv/streams`. The
Edition 3 pin is among them and matched, and the **one-byte** mirror-stamp divergence is recorded at
its own site in `stanag4586_pin.json` rather than here — live copy 3 852 365 octets, archived copy
3 852 364, wholly different digests, and every one of 509 pages textually identical.

#### Act 1 — the two pre-checks, and they came out opposite ways

**PRE-CHECK 1: THE PROSE-CARRIER GATE ALREADY EXISTS, so this round verified it instead of building
a second one.** It is `test_the_pending_heading_is_never_spelled_except_as_that_heading`, and it was
built in `c73ea45` during the maintenance round — the acquisition round did not detour past it. Its
skip conditions were checked against the third incident as the brief asked, and there are none: the
module states in as many words that a check whose subject is "an occurrence that should not exist"
cannot be conditioned on occurrences existing. It runs tag-or-no-tag, on a file that ships inside
the wheel, so it holds on a clone and in an unpacked sdist. Its companion reconstructs occurrences 1
and 3 as text and asserts both are caught. **It was additionally witnessed red live**: a quoted
refusal message was appended to this file, the gate named the carrier by line and failed, and the
file was restored.

**AND THE GATE'S OWN RECONSTRUCTION REFUTES WHAT THE 1.3.0 RECORD SAYS ABOUT THE THIRD INCIDENT** —
already recorded at the gate, repeated here because it is the kind of correction that gets
re-inherited. `4f1932f` recorded that on the third occurrence "neither gate that keys on the string
could see it — both were skipping". Rebuilt at `148e7a6` with the un-elided sentence restored and no
tag, `test_the_unreleased_section_is_the_first_thing_under_history` **stops** skipping and goes red.
The tag was never what blinded them. **The fully blind state is occurrence 1's** — a carrier beside a
genuine heading — and that is the state the gate closes.

**PRE-CHECK 2: THE PARKS REGEX WAS NOT SCOPED. Found last round, worked around, not repaired — the
brief was right, and it is repaired here.** `gates/parks_table.py`'s `ROW` pattern ran over the whole
of `FORMAT_COVERAGE.md`, thirteen thousand lines, and reported thirteen parks because the file
happens to hold one bold-numbered table. The workaround was a convention — spell other tables with
lettered rows — that lives in a round record and in nothing executable. `_rows` now scans only the
span `_table_span` resolves, anchored on the parks table's own column header (`Reason, grounded in
the delegation table`, the cell that makes it this table and not another), and **refuses rather than
falls back** when that anchor does not resolve exactly once: zero headers means the table moved, two
means a coin toss, and a scope that silently reverts to the whole file on a renamed column
reintroduces the defect at the moment nobody is watching.

**FINDING 1 — THE FIRST NON-VACUITY WITNESS WAS ITSELF VACUOUS, TWICE OVER, AND BOTH FAILURES ARE
THIS REPOSITORY'S OWN RECORDED CLASSES.** The repair was witnessed by appending a synthetic second
bold-numbered table and asserting the scoped parser did not absorb it. It passed. It also passed
against the **unrepaired** parser, which is a witness measuring nothing.

*The first cause was mechanical:* the edit that was supposed to un-repair the parser silently matched
nothing and the file was never modified, so the "red" run was a green run of the repaired code. It
carried no assertion that its pattern had matched. **A mutation with an empty domain is a case that
passes without running** — `gates/pin_paths.py` records that lesson and this round re-committed it
one layer up, in the scaffolding rather than in the gate. Every subsequent un-repair asserts its
pattern is present before writing.

*The second cause was substantive and is the more useful half:* with the parser genuinely unscoped,
the witness **still** passed, because `_cells` requires **five** cells and the synthetic table had
three. **So the original defect is narrower than it was recorded as being.** A second bold-numbered
table with fewer than five columns was never absorbed — the cell-count guard already dropped it —
and the exposure is second tables with **five or more** columns only. Measured directly: over the
real document plus a three-column second table the unscoped scan yields the same 13 rows; plus a
five-column one it yields **14**, and the scoped scan yields 13. **Class: a repair whose witness
tested a shape the defect never had, hiding both that the witness was inert and that the defect's
domain had never been measured.** The witness is rebuilt at five columns, is red against the
unscoped parser and green against the scoped one, and the three-column case is kept as its own test
so the five columns cannot be "simplified" back out.

**What the scope is worth, stated rather than implied.** A phantom row inflates `rows`, and with it
`open_parks`, `closed_parks` and the membership every set-claim is derived against — so
`check_set_claims` would go on passing while measuring the wrong set, and `check_stated`'s MISSING
branch would demand a group for a park that is not a park. That is the shape `gates/pin_paths.py` is
named for: a guard whose subject is a set, checking the wrong set, in silence.

#### Act 2 — the release, derived end to end

**Every guard the bump turns red was witnessed red before it was moved.** Bumping `PACKAGE_VERSION`
alone and running the suite produced exactly four failures and no others:
`test_the_json_measurement_is_what_a_round_would_quote` (**red by construction until the tag** — it
requires `pending.kind` to be a classification and `measure()` leaves it `None` while no tag names
the declared version, so it goes green on the tag and not on an edit),
`test_the_two_versions_are_independent_and_nothing_derives_one_from_the_other`,
`test_the_release_notes_describe_this_version`, and
`test_every_documented_tag_command_names_this_trees_package_version`. The first is left red until
the tag; the other three were moved to 1.4.0 and re-run green. Skips went 3 to 7 as the
tag-conditional release checks stood down, which is the same construction.

**FINDING 2 — THE TAG-COMMAND GATE HAS A PROSE-CARRIER CLASS OF ITS OWN, and this round is the first
to hit it.** `test_every_documented_tag_command_names_this_trees_package_version` went red on a site
that is not a command: a **dated round record** in this file, describing what `README.md` said during
the 1.3.0 round, which reproduced the annotated-tag command verbatim in order to describe it. The
gate reads it as a live instruction naming a superseded version. It is the pending-heading carrier
class on a second gate — **a record that quotes a command becomes a command** — and the repair is the
same one: the command form is described and not reproduced, with the elision marked as a repair so a
later round does not restore it for fidelity. The number in the record was **not** updated, because
the sentence is a dated reading and moving its figure would make it assert a measurement nobody took.

**FINDING 3 — A TREE EXEMPTION OUTLIVED THE PROSE IT EXEMPTED, and the guard caught it within
seconds.** `TREE_EXEMPT` carried a row for `RELEASE_NOTES.md`'s "across the thirteen adapters 1.3.0
shipped", a named subset that needed exempting because the 1.3.0 notes described an artefact smaller
than the tree. The 1.4.0 notes describe an artefact that **is** the tree, so the sentence is gone and
needs no licence; `test_every_tree_exemption_still_points_at_prose_that_is_there` went red on the
leftover row the moment the notes were rewritten. The row is retired with its reasoning kept as a
comment. **An exemption outliving its prose is a licence nobody is using**, and the next stale figure
to land on those bytes would inherit it.

**And retiring it cost one, which is rule 9 closing on itself and is worth knowing terminates.** The
paragraph above quotes the retired bytes in order to say what was retired, which made this file a
site of the figure and turned the adapter-count sweep red. A row was added for the quotation. The
loop is finite: a record of *that* exemption need not quote it, and the ground recorded on the row
says so. The alternative — eliding the figure from the quotation, as the two carrier repairs above
do — was available and was not taken, because here the quoted bytes exist nowhere else in the tree
any more and a description of them could not be checked against anything.

**The notes were re-read off the tree, and the acquisition round's figures were re-derived from
their own sources rather than copied from its report.** All four came out as the brief predicted and
none was taken from it:

* **14 adapters** from `roster()`, and **15 ordinals** from the ordinal table's own parser. **These
  are two derivations over two sources and they are not the same number** — `#9` is `stanag5527`, a
  Phase 1 row set with no adapter — so `stanag4586` is the fourteenth shipped adapter at ordinal
  **15**. The brief's standing lesson from the last release is exactly this, and it is why neither
  figure was obtained from the other.
* **432 fixture verdicts, 0 failed**, summed from the harness over the registry. 1.3.0's 408 plus
  `stanag4586`'s 24 is the same number, and the notes say so — but the 432 in them was summed, not
  added, and the agreement of two independent routes is the check.
* **166 messages in 27 functional groups, 48 of them out of scope across 9 groups**, all three
  re-derived by parsing the inventory table. **The parts were summed as well as the total**: 48 out
  of scope + 57 mixed + 61 in scope = 166 over 27 rows, and the nine section numbers the
  out-of-scope prose names are exactly the nine the table marks. That is the guard the last
  decomposition failure asked for — a right total with wrong parts is what `pin_paths.check_parts`
  exists for, and a figure re-derived without its partition would not have caught it.

**The roll, and the grep that no gate can replace was run anyway.** The pending section became
`### 1.4.0` and its opening sentence describes the heading it absorbed rather than spelling it. The
literal now occurs **zero** times in this file, confirmed by grep after the roll and independently by
the carrier gate — belt and suspenders on a defect that three consecutive rolls recreated, and this
was the fourth roll.

**The fixed point was respected.** Writing this record moves `MIGRATIONS.md`, which is a shipped
document and already in the arc, so the moved set stays at **60** and the classification stays
**MINOR** — verified by re-running the derivation after this file was written, not before it. That
is the 1.3.0 round's own falsified-sentence lesson applied as a procedure rather than remembered as
a warning.

### 1.3.0 — 2026-08-29 — the IMAPB codec ships, and a refused release re-derived forward

**This section carried the pending heading and a release absorbed it**, which is what that
heading is for — the token itself is elided here, because prose that spells it leaves the file
carrying it with no such section and two release gates key on the literal string. It is the arc since `v1.2.1`, and every paragraph below it was written while the work
landed rather than assembled at the tag — condition 4's "derived, not remembered" read as a
rule about *when* prose is written and not only about what it cites.

**THIS RELEASE WAS DERIVED, VERIFIED AND REFUSED ONCE BEFORE IT SHIPPED.** The refusal is dated
2026-08-28 and is recorded below in full, with the finding that accompanied it; the operator
**reversed** it on 2026-08-29 and this release is that reversal carried out. Both rulings stand:
the refusal as a dated reading, the reversal as the decision that outranks it. **Nothing was
cherry-picked from the refused attempt.** That attempt's bump, rolled section and rewritten notes
were unwound before it closed, and every release mechanic here was re-run from scratch against the
tip — the number re-derived by the gate, the notes re-read off the tree, the guards re-witnessed
red and then green. The refused attempt exists as history and as this paragraph, and contributed
no bytes.

**What moved inside the distribution: 67 files, and this arc now carries CODE.** The count is
`gates/bump_derivation.py`'s and the enumeration below is derived from it rather than typed —
4 shipped documents, 1 pin record, 2 modules of source and 60 fixture files. **It was 66 for the
whole of the arc's life and the release itself is what made it 67**: `version.py` is a
distribution file, so the bump that closes an arc joins the arc it closes. That is a property of
every release this file will ever record and it is stated here once.

* **Documents (4):** `FORMAT_COVERAGE.md`, `MIGRATIONS.md`, `README.md`, `fixtures/klv/README.md` — the last two both carrying the
  basename `README.md`.
* **Pin record (1):** `fixtures/klv/spec/klv_pin.json`.
* **Source (2):** `adapters/imapb_codec.py`, the IMAPB codec — MISB ST 1201.3's mapping,
  both directions, park 5's artefact — and `version.py`, carrying the bump to 1.3.0.
* **Fixtures (60):** a new set at `fixtures/klv/imapb/`, 30 payloads each with its parsed
  record:

```
  item_103_document_worked_example.imapb
  item_103_document_worked_example.parsed.json
  item_104_document_worked_example.imapb
  item_104_document_worked_example.parsed.json
  item_105_document_worked_example.imapb
  item_105_document_worked_example.parsed.json
  item_109_document_worked_example.imapb
  item_109_document_worked_example.parsed.json
  item_112_document_worked_example.imapb
  item_112_document_worked_example.parsed.json
  item_113_document_worked_example.imapb
  item_113_document_worked_example.parsed.json
  item_114_document_worked_example.imapb
  item_114_document_worked_example.parsed.json
  item_117_document_worked_example.imapb
  item_117_document_worked_example.parsed.json
  item_118_document_worked_example.imapb
  item_118_document_worked_example.parsed.json
  item_119_document_worked_example.imapb
  item_119_document_worked_example.parsed.json
  item_120_document_worked_example.imapb
  item_120_document_worked_example.parsed.json
  item_132_document_worked_example.imapb
  item_132_document_worked_example.parsed.json
  item_134_document_worked_example.imapb
  item_134_document_worked_example.parsed.json
  item_96_document_worked_example.imapb
  item_96_document_worked_example.parsed.json
  length_from_the_wire_tag112_2_octets.imapb
  length_from_the_wire_tag112_2_octets.parsed.json
  length_from_the_wire_tag112_3_octets.imapb
  length_from_the_wire_tag112_3_octets.parsed.json
  length_from_the_wire_tag112_4_octets.imapb
  length_from_the_wire_tag112_4_octets.parsed.json
  msb_high_is_a_normal_value_when_the_range_is_a_power_of_two.imapb
  msb_high_is_a_normal_value_when_the_range_is_a_power_of_two.parsed.json
  special_minus_inf.imapb
  special_minus_inf.parsed.json
  special_minus_qnan.imapb
  special_minus_qnan.parsed.json
  special_minus_snan.imapb
  special_minus_snan.parsed.json
  special_plus_inf.imapb
  special_plus_inf.parsed.json
  special_plus_qnan.imapb
  special_plus_qnan.parsed.json
  special_plus_snan_with_payload.imapb
  special_plus_snan_with_payload.parsed.json
  special_reserved.imapb
  special_reserved.parsed.json
  special_userdefined_with_payload.imapb
  special_userdefined_with_payload.parsed.json
  st1201_example_3_altitude.imapb
  st1201_example_3_altitude.parsed.json
  st1201_example_4_small_range.imapb
  st1201_example_4_small_range.parsed.json
  zero_offset_applies_when_the_range_spans_zero.imapb
  zero_offset_applies_when_the_range_spans_zero.parsed.json
  zero_offset_is_not_applied_to_an_all_positive_range.imapb
  zero_offset_is_not_applied_to_an_all_positive_range.parsed.json
```

**THE BUMP MOVED FROM PATCH TO MINOR THIS ROUND, AND THE GATE DERIVED IT RATHER THAN BEING TOLD.**
Before the codec landed the arc derived **PATCH** with the floor at **1.2.2**, which is what every
round since `v1.2.1` had recorded. `adapters/imapb_codec.py` introduces public top-level names and
`fixtures/klv/imapb/` is a new fixture set, and `version.py`'s MINOR row covers both — "an optional
field added; an enum member added; a payload model registered" in the schema's terms, and the
gate's own table in the package's: *a public top-level name appears → MINOR*, *a fixture set
appears → MINOR*. So the arc since `v1.2.1` now derives **MINOR** and the next release is at least
**1.3.0**. **No release is forced by this.** `SCHEMA_VERSION` is unmoved at 1.0.0 — nothing about
the wire contract changed, no field was added to any model, and a consumer reading CDM objects is
unaffected. What moved is the Python surface, which is what a package MINOR states and all it
states.

**WHAT THE NEW CODE DOES NOT BUY, because a MINOR that reads as a park closure would be worse than
no note at all.** **Park 5 is not closed.** Its exit condition is the document plus the artefact
that document makes writable; both documents have been held since 2026-08-27 and the artefact now
exists, and what remains is that **none of the fourteen rows the codec reaches is witnessed by any
held octet** — the pinned stream's 26 items stop at tag 65 and the lowest IMAPB item is tag 96. All
fourteen rows still read `not yet`. In particular `Kinematics.course_deg` is still `None` on every
object this package emits from the pinned stream, because tag 112 is not in it. The codec is
checked against ST 0601.14a's fourteen worked examples and ST 1201.3's two, and against nothing on
a wire.

**THIS SENTENCE WENT STALE A SECOND TIME, AND THE PARAGRAPH BELOW IS ABOUT IT GOING STALE THE
FIRST TIME.** It read "three shipped documents" and named three, while the arc had moved five:
`synapse_cdm/README.md` joined at `2cc0643`'s predecessor when sweep rule 1 gained the
synthetic-fixture case, and `fixtures/klv/README.md` at the off-peak round. **Found by the pins
round's stale-count sweep, not by a gate**, and the reason no gate caught it is the one the
paragraph below already names: the guard requires every moved path to be named **by basename**, and
`README.md` occurs throughout this section for unrelated reasons, so both files were counted as
named while the sentence that is supposed to name them said *three*. **The guard's one-directional
design is doing exactly what it was documented to do** — it asserts that no moved file is unnamed,
not that the prose's own arithmetic is right — so this is a gap in coverage rather than a gate
failing. Recorded rather than quietly re-synced, because a sentence that has now drifted twice in
one arc is evidence about the sentence and not about either round: **the count is the part no
machine reads, and `gates/bump_derivation.py` prints the true set on every run.**

**AND NOW A MACHINE READS IT. 2026-08-27.** The gap the paragraph above records is closed, and it is
closed at the count rather than at the naming, which is the part worth stating. The tempting repair
was to make *named* mean something narrower — only a basename inside the listing sentence, only one
in backticks — and every version of that is a heuristic about which mentions are claims about the
arc, which is the reading this file's own guard already refuses to make in the reverse direction.
The count needs no heuristic: the sentence asserts a number, `git` derives a number, and they are
equal or they are not. So
`tests/test_cdm_release.py::test_the_unreleased_sections_spelled_count_agrees_with_the_derived_moved_set`
compares the spelled count against the **derived set**, never against what the section names — a
file named here for unrelated reasons cannot satisfy it, because it never looks at what is named.
The naming gate is unchanged and still runs beside it; the two now assert different things.

**The refusal path is a recorded outcome and not a hole.** Parsing prose to a number is safe only
where the prose is unambiguous, so the parser requires exactly one `What moved inside the
distribution:` anchor in the section and exactly one count-bearing token in the clause it opens.
Zero, or two, and the gate **fails with the ambiguity named** and the count stays a manual step. It
is not resolved by preferring the first number: a sentence reading "FIVE shipped documents and TWO
code files" has two candidate arc sizes and choosing between them is a reading. This is the
treatment the four refuted reverse-sweep formulations got, applied to a live gate rather than to a
dead end — the difference being that here the refusal fires on the sentence, so it cannot be dodged
by writing prose the parser gives up on.

**Three refusal directions are witnessed by fixtures and the live gate was mutation-tested against
this tree.** The fixtures cover count high, count low, and the one that is the whole point: a
section naming **every** basename of a five-file arc while its sentence says three. The naming gate
accepts that section and the count gate refuses it, which is the gap between the two predicates
written down as an assertion rather than as a claim. Against the real tree, moving the count word by
one in either direction breaks the comparison, and a two-number sentence produces the named refusal
— run before this paragraph was written, not after.

**This round's own sentence is the first thing the tightened gate rules, and the count did not
move.** The arc since `v1.2.1` moved five shipped files before this round and moves the same five
now: `FORMAT_COVERAGE.md` gained a dated register note beside **KLV 5**, `MIGRATIONS.md` is the file
you are reading, `fixtures/klv/spec/klv_pin.json` gained the round's node, and both `README.md`
files were already in the arc and did not move again. **FIVE is now derived rather than remembered**
— which is the non-vacuity witness worth recording, because a gate whose first live subject already
satisfied it is a gate nobody has watched decide anything.

**What the register note found, recorded here because it is a negative result about a framing this
file will otherwise inherit.** The note was to be filed as *the profile's second citation defect*,
beside **KLV 18**. It is not a second anything: all **116** bracketed citations in MISP-2019.1's
body, over **53** distinct documents, are unsuffixed, so unsuffixed-in-the-body is the profile's
convention and ST 1301 is an instance of it. The full derivation, and the reason this sharpens
**KLV 5** rather than weakening it, is in `FORMAT_COVERAGE.md` beside the entry. **No register entry
was added or edited** — the note is filed adjacent, because its subject is the pinned profile and
not any claim the register makes.

**THAT SENTENCE NAMED ONLY THIS DOCUMENT AND WAS FALSE WHEN IT WAS READ, three commits after it
was written.** It was true at `e825e96`, whose only shipped file was this one. `6475615` then moved
`FORMAT_COVERAGE.md` and `klv_pin.json`, and `2d2c320` moved all three — and neither round came
back to the sentence, because nothing asked it to. It is the arc's own contents mis-stated by the
section whose subject *is* the arc, which is a worse site for the defect than any prose count this
record has swept: `gates/bump_derivation.py` derives the true set on every run and prints it, so
the correct answer was one command away at every moment the sentence was wrong.

**Now guarded** —
`tests/test_cdm_release.py::test_the_unreleased_section_names_every_distribution_file_the_arc_moved`
requires this section to name, by basename, every shipped path the arc has moved, derived from git
rather than read out of the prose. Only that direction is asserted: the reverse — that the section
names no file the arc did *not* move — is not derivable, because the section legitimately cites
`gates/bump_derivation.py`, `pyproject.toml` and `version.py` while none of them moved or ships.

**THE GUARD'S FIRST DRAFT HAD A HOLE, AND THE PARAGRAPH ANNOUNCING IT DUG THE HOLE.** The draft
accepted this document referring to itself the way prose naturally does, instead of requiring the
basename. That phrase recurs through the section for unrelated reasons, so `MIGRATIONS.md` was in
practice always counted as named — and the announcement above originally *quoted* the defective
sentence, which carried the phrase, so the guard would have stayed green with the naming sentence
deleted. **It is the quoting trap closed in `FORMAT_COVERAGE.md` this same round, met a second
time inside the round that closed it**, which is the argument for closing it. The rule is now
uniform: every path is required by basename, this document included, and no self-reference is
accepted anywhere.

**A fifth release condition exists, and the thing that enforces it ships nothing.**
`gates/bump_derivation.py` classifies the diff over the distribution's contents between the
previous tag and the tree being released against this document's `PACKAGE_VERSION` table, and
refuses a number that exceeds or undershoots it. The gate is repository infrastructure —
`pyproject.toml`'s "DOES NOT SHIP" list names `gates/` in as many words — so a consumer installing
the next release receives none of it. It is recorded here because condition 5 is now part of the
procedure a release follows, which is a fact about this document rather than about the wheel.

**THE ROUND THAT BUILT THE GATE EXPECTED IT TO RULE ITSELF A MINOR, AND THE TABLE DOES NOT AGREE.**
The expectation was that "a new gate is a MINOR per the table", on the MINOR row's "a harness flag
or **check** is added". It is not: the harness is `synapse_cdm/harness.py`, the shipped `cdm-harness`
CLI, and its checks are the six `_check_*` functions inside it — all of which a consumer runs.
`gates/bump_derivation.py` is none of those things and is not in the sdist or the wheel.
`PACKAGE_VERSION` is defined in `version.py` as "ordinary semver over the Python surface: the
importable names, the `Adapter` contract, the harness CLI and its exit codes, the fixture set", and
this round moves no member of that list. **So the expectation is refuted by the table it appealed
to, and the derived answer is PATCH.** It is recorded here, with its derivation, because the round
that built the gate asked for its expectation to be written down so the next release round could
check the gate against it — and what the next round will find is that the gate refuses the
expectation rather than confirming it. Run
`python gates/bump_derivation.py` to see the same verdict off the tree.

**And the arc would have been NONE without this file, as at the round that wrote this.** The only
distribution member THAT round touched was `MIGRATIONS.md` itself, so the PATCH floor rested
entirely on a shipped document moving. **Dated rather than carried forward**, on sweep rule 6: it is
a true statement about one round and it was written in the bare present tense, and four later rounds
have since moved four more shipped documents into the same arc. Had the
round written its record only in `PUBLICATION.md` — which does not ship — the gate would have
derived **NONE**, and the correct next release would have been no release at all. That is the
distinction `PACKAGE_VERSION` exists to make and it is worth seeing it land on a round this large.

**The KLV register moved, and two sentences of the `1.2.1` section below are superseded rather than
edited.** That section is a closed release record, and entry 5's ruling is that a closed record which
quietly updates its own history is a record nobody can date. So both supersessions are stated here:

* it says the `13 December` row of EG 0601.1's §3 is "untouched and undecidable from anything held".
  **It is now narrowed from held bytes.** §3's list is chronological — its first row is the initial
  release — and the two candidate years are not symmetric under that: ST 0601.4's `13 December 2006`
  leaves the three rows in order, while edition 1's own `13 December 2007` would place it *after* the
  `15 May 2007` row below it and run the list backwards. One reading makes the section consistent and
  the other makes it wrong twice. Evidence, not proof — a list can be misordered — but the row is no
  longer undecided on nothing.
* it reports KLV 14 as "refuted in part" and states the corrected finding. **What that round's
  refutation pointed at was the middle clause of a three-clause conclusion**, under a heading reading
  "THAT LAST CLAUSE", so the conclusion itself — that the entry is "a park list rather than a defect
  in the standard" — was never adjudicated. It is ruled now, and it is false in that exclusive form:
  ST 0601.4's §3 exists to log revisions and omits four of the eight additions it should log, which is
  a defect in the document and not an absence of one. **The entry is both**, and "rather than" is the
  word that fails.

**KLV 16's cover date is corroborated a third time, from the file rather than the page.** EG 0601.1's
PDF document-information dictionary carries `/CreationDate D:20080515125829` with `/ModDate` identical
to it, and a `/Title` naming the source document `EG0601.1_UAS_Local_Data_Set_20080515.doc`. The field
was calibrated against the lineage before being quoted: it equals the cover date exactly for three of
the four held 0601 documents and post-dates it by four days for the initial release. Reading (a) — a
one-digit typo — is now preferred on a wider margin, because reading (b) needs **two** documents to
fail to log the same re-issue. It is still not a proof and the entry still elects neither.

**Park 9 was retried once and stays parked**, and the retry withdrew a claim about the two official
routes rather than the throttled one: `web.archive.org` still answers HTTP 429, and `gwg.nga.mil` and
`nsgreg.nga.mil` were never reached at all, because the whole `nga.mil` zone does not resolve from
this environment. The blocker is one throttled route, not three refusing hosts.

**RETRIED A SECOND TIME, 2026-08-27T14:51Z, and the answer is the same in every term.** The CDX
index query and playback of the byte-exact archived `ST0601.4.pdf` URL both answered **HTTP 429**,
`Server: nginx`, `X-RL: 1`, `Content-Type: text/html`, 162 bytes. **The park's premise was not
contradicted, because no bytes arrived to contradict it** — the pin's digest was never reached, so
nothing was compared and nothing is claimed. The 429 body was read and deliberately not hashed, on
the same discipline as the previous retry. **No mirror was improvised**, per the standing rule.

**`X-RL` has now been sampled three times — `0`, `1`, `1` — and it still does not predict the
answer.** Recorded as an observation and not as a trend: three samples of a counter that moves
while the refusal does not say only that the counter moves.

**And the environment bound was re-derived before the network was trusted, not after.** The whole
`nga.mil` zone still answers `SERVFAIL` from the only reachable resolver — `gwg.nga.mil`,
`nsgreg.nga.mil` and the apex — while `web.archive.org` resolves normally. So this round could ask
exactly one of the three routes, which is the same one route the previous retry could ask, and the
two official routes remain a question this environment cannot put.

**A quoting trap was closed in `FORMAT_COVERAGE.md`, and it was a carrier rather than a defect.**
The parks-round audit corrected a bare-present-tense claim about which release `RELEASE_NOTES.md`
opens with, and it did so by **quoting the phrase it was correcting**. The correction is right and
the quotation is the trap: `tests/test_cdm_publication.py` documents the pattern for the deploy
markers — "a checker that spells the forbidden string is itself a carrier of it" — and the same
holds for a record. The sentence now describes the phrase instead of reproducing it, and says why.
**Nothing swept the string before the edit and nothing does after**: it occurred exactly once in
the tracked tree, in the correction itself, and occurs zero times now. So this closes a trap that
had not yet sprung, which is the only time closing one is cheap.

**A NAMED AMBIGUITY, LEFT AS A MANUAL SWEEP RATHER THAN GUESSED AT.** The round was briefed to
mechanize the reverse direction of the record's commit accounting — every commit that lands under
`gates/` or `tests/` should be answerable from an entry — after a hand sweep found `7544880`
unaccounted for. **It is not mechanizable in that form from this tree, and four candidate rules
were tested rather than one:**

* *every commit touching `gates/` or `tests/` has its short SHA in a tracked `.md`* — fails at
  **53 of the 81** such commits in the history. Most rounds are recorded by their commit message
  and by prose that names no SHA, which is the documented convention and not a defect.
* *every file under `gates/` is named by a tracked `.md`* — **holds, 5 of 5**, and would not have
  found `7544880`: that commit named both files it added, in the same diff.
* *every file under `tests/` is named by a tracked `.md`* — fails at **eleven** modules. A test
  module is not owed a prose citation and nothing in the record says it is.
* *every commit adding a `gates/` or `tests/` file names it in its own message* — fails at
  **16** commits, and again does not reach `7544880`, whose message names both.

**So the rule cannot be stated without deciding what "answerable from an entry" means, and that
decision is a reading of prose rather than a derivation from the tree.** The briefing's own stop
rule applies — a guard that guesses is worse than none — and the sweep stays manual. What is
recorded here is the **four refuted formulations**, so the next round attempting it starts from
what has already been ruled out rather than from the idea.

**What the round mechanized instead is the direction that IS derivable, and it caught a live
defect** — this section's own account of the arc, above. That is the same family of check aimed at
the place where the tree, and not a reading, settles the answer.

**No adapter, no codec and no fixture changed**, so none of the above touches an octet. The register
is a record of what the standards say about themselves, and this round read six PDFs and promoted no
tag row.


**THE OFF-PEAK ROUND: PARK 9 IS CLOSED, and what moved was the hour rather than the argument.**
2026-08-27T20:20Z. Three attempts had asked `web.archive.org` for park 9's document and met HTTP 429
— the parks round, a retry at ~14:05Z and a second at ~14:51Z — and each recorded the refusal
faithfully. **All three asked at the same hour of the day.** This round asked at 20:20Z, roughly six
hours off that mark, and the archive answered `X-RL: 0` and HTTP 200. The park arithmetic therefore
moves in every term: thirteen parks, **four closed** — 1, 4, 13 and now 9 — and of **the nine still
open**, eight are public downloads and one is SMPTE's purchase.

**The environment bound was re-derived before the network was trusted, and it had MOVED.** The two
previous retries recorded that the whole `nga.mil` zone answers `SERVFAIL` here and correctly bounded
their claims to this environment's DNS path. That bound is gone: `gwg.nga.mil`, `nsgreg.nga.mil` and
the apex all resolve now, stable across three consecutive queries on the same resolver that refused
them before. **So the two official routes were asked for the first time in this record** — the
question the earlier rounds recorded as one this environment could not put. `gwg.nga.mil` answered
**HTTP 403** with an S3 `AccessDenied` body, where earlier rounds met CloudFront's 403; `nsgreg.nga.mil`
answered **HTTP 200 whose body is the F5 JavaScript interstitial**. **A 200 carrying a challenge page
is not a document**, and that is recorded because the status line alone would have supported "the
registry now serves" — finding 4 in its purest form, a probe reporting its own transport as its
target's behaviour. The status was checked, then the body was read, and only then was the route ruled
out.

**The pin was TESTED, which is the half the two previous retries could never reach.** Their plan was
to digest fetched bytes against the pin *before* reading anything, and no bytes ever arrived. This
round ran it as a **control first**: the byte-exact archived `ST0601.4.pdf` URL served 1 268 558 bytes
digesting to the value this record already pins, equal in both terms. The route was shown to serve
**the recorded bytes** before it was trusted with unrecorded ones, and only then was ST 1402.2
fetched. Had it disagreed the round would have stopped for adjudication and closed nothing.

**What park 9 bought.** MISB ST 1402.2, 27 October 2016, thirteen pages, pinned at
`52a3b32a…773100e0` / 1 112 404 bytes. Its artefact half was prose from the beginning, which is why
the parks round ranked it most closable of the three, and the row set is now written: **26
requirements, four deprecated and 22 live**. Two findings came with it. **The requirement identifiers
are unsuffixed** — 25 of the 26 read `ST 1402-NN`, so an identifier does not say which edition states
it, which is the same defect one layer in that this record already logs about the profile's own
citations; the 26th reads `ST 1402.1-26`, suffixed with the *previous* edition inside the edition-2
document, and that is recorded and **not** adjudicated because no other edition of ST 1402 is held.
**And the four deprecated requirements are still needed**: they carry the `stream_type` and
`stream_id` values for both multiplex methods, deprecated as re-specifications of ISO/IEC 13818-1
rather than withdrawn as facts, and a reader who read "deprecated" as "not applicable" would lose
exactly the ability to locate a KLV stream that park 9 existed to buy.

**Parks 5 and 11 did NOT close, and their blocker is now down to the one that needs a ruling.** Their
documents were checked for obtainability from the index only, with nothing fetched and nothing
landed: **ST 1201.3, ST 1303.1, ST 1204.1 and ST 1301.2 are all present as `application/pdf` 200
captures at the exact revisions those parks pin.** So the acquisition half is discharged in principle
by the same route that just worked, and each park now stands on its **second** blocker alone — an
artefact half that is *source* under `packages/`, an `IMAPB` codec for park 5 and populating
`Entity.source_ids` for park 11. That is held behind a standing rule, so this round **framed the
question and did not act on it**; the framing is in `FORMAT_COVERAGE.md`, marked as awaiting a
ruling, so the next round can act on an answer without re-deriving the context.

**THE MANUAL REVERSE SWEEP WAS RUN, and it found one gap in nine commits.** The four refuted
formulations above stand untouched — this sweep is evidence about the *manual* reading's cost, which
is the datum a future mechanization attempt needs. Over `v1.2.1..HEAD`, **eight of nine commits are
accounted for** by prose in a tracked `.md`. The ninth is **`90f65f7`**, and the gap is real: its
repair reworded synthetic fixtures inside `gates/bump_derivation.py` and
`tests/test_cdm_bump_derivation.py` that had spelled an adapter count, and **sweep rule 1's own file
set is `*.md`, `*.mdx` and `*.py`** — so a test fixture spelling a count is a *live carrier* of it,
indistinguishable to the sweep from a real claim. No rule recorded that case. It is the same shape as
the quoting trap closed one commit later, one layer over: there a correction became a carrier by
quoting, here a fixture becomes one by illustrating. **Repaired in place** in the package README's
rule 1 rather than left as a finding.

**A GUARD WAS GENERALISED AND CAUGHT A DEFECT IN THE SAME ROUND THAT WROTE IT — the defect its
own comment had warned about, recurring for the third time.**
`test_the_pinned_copy_is_the_same_copy_at_every_site_that_names_one` checks that an abbreviated
digest expands to the pinned one, because eight characters at each end look right for any hash
sharing them. Its comment read "generalised rather than duplicated, because the framing round's
version hard-coded ONE digest and a second document would have slipped past it" — and it then
hard-coded **two**, skipping every other abbreviation as "another document's pin, checked by its
own gate" when no such gate existed. **ST 1402.2 slipped past exactly that way.** The subjects are
now DERIVED from `delegated_specifications_held`, so a document cannot be held without being
swept, and the sweep refuses to run vacuously. **It failed on its first run, correctly:** this
round had written the new digest's abbreviation with a NINE-character tail, which reads as a
digest at a glance and is not one. Generalising a list is not generalising — the list is the
thing that goes stale — and the lesson is cheap only because the guard was widened before the
commit rather than after it.

**WHAT MOVED IN THE DISTRIBUTION, named file by file** — condition 4, and the guard that reads
this section wants the names rather than a count. Five files under `packages/`:
`FORMAT_COVERAGE.md` (the round record, the ST 1402.2 row set, the parks 5/11 framing, the pin
row and the park-table closure); `MIGRATIONS.md`, this entry; `synapse_cdm/README.md`, where
**sweep rule 1 gained the synthetic-fixture case** the manual sweep found; 
`fixtures/klv/README.md`, which gains the ninth round and moves its delegated-document tally
from four to five; and `fixtures/klv/spec/klv_pin.json`, which gains the ST 1402.2 pin, the
park 9 closure entry and the round's own node. **Every one of them is a shipped document and
none is executable**, so the arc still derives PATCH and the floor stays **1.2.2** — which the
bump gate is asked rather than asserted here.

**What the sweep cost, recorded because that is the number a mechanization attempt needs.** Nine
commits, and judgement was required at exactly **two** of them — `90f65f7` and `9b62e9b` — where the
question was whether prose about a mechanism accounts for a *repair within* that mechanism. Seven
were unambiguous in both directions. So the manual reading is cheap at this arc length and the
expensive part is not the reading: it is that the two hard cases turn on a distinction — mechanism
versus repair-within-mechanism — that none of the four refuted formulations can express.

**THE PINS ROUND: FOUR DOCUMENTS PINNED, NO SOURCE WRITTEN, AND NEITHER PARK CLOSED.**
2026-08-27 evening. The off-peak round ended by recommending an intermediate for parks 5 and 11 —
*obtain and pin all four documents, write no source* — and that ruling was given and executed here.
**MISB ST 1201.3** (`c5d8cb2d…bff4a07e`, 617 525 bytes, 20 pages), **ST 1303.1**
(`e30487b0…a3627895`, 1 084 929 bytes, 14 pages), **ST 1204.1** (`2503960a…61d9f1c5`, 1 078 045
bytes, 36 pages) and **ST 1301.2** (`3d08d35d…e509f9a6`, 590 094 bytes, 4 pages) are held, pinned and
read. **The delegated-document tally moves from four to eight of fourteen** — it had not moved at all
between the day it was written and this morning, and it has now moved twice in one day.
*(CORRECTED 2026-08-28 by the repair round. This sentence read "from five to nine" as written and
both figures were one too high, for the reason the decay sweep's finding 3 names: the tally counts
delegations the profile makes, and the held copy of ST 0601.19 is not one. The acquisition this
entry records is unaffected — four documents were obtained and all four are delegations; what was
wrong is the base the increment started from.)*

**THE ACQUISITION WINDOW WAS SPENT BEFORE THE AUDIT WAS FINISHED, deliberately.** The quota is
hour-windowed by the previous round's finding and a window that is open now has closed without
warning before, so Act 0 was abbreviated in its favour: environment bound re-derived at **21:03Z**,
control fetch at **21:04Z**, all four documents in hand by **21:05:40Z**, prose afterwards. The
window held throughout — every response carried `X-RL: 0`, HTTP 200 and an `application/pdf` body.

**THE PIN-AS-CONTROL STEP IS NOW THE STANDARD METHOD RATHER THAN ONE ROUND'S IDEA, AND IT PASSED.**
The byte-exact archived `ST0601.4.pdf` URL was re-fetched in full first and served 1 268 558 bytes
digesting to this record's pinned value, equal in both terms. **The route was shown to serve the
RECORDED bytes before it was asked for unrecorded ones.** Had it disagreed the round would have
stopped and pinned nothing.

**Both official routes were asked first and the BODY was read, not the status.** `gwg.nga.mil`
answered **403** with an S3 `AccessDenied` body; `nsgreg.nga.mil` answered **200 whose body is the F5
JavaScript interstitial**, 43 652 bytes of `text/html` carrying the `bobcmn` marker. A 200 with a
challenge page in it is the most expensive wrong answer this environment offers, which is why the
check is run every round rather than recalled. **And the environment bound had to be re-derived
again**: the whole `nga.mil` zone answered `SERVFAIL` on the afternoon of 2026-08-27 and `NOERROR`
that evening and again now, so the honest reading is an **intermittency** and not a recovery.

**THE STOP RULE WAS NEVER REACHED.** Each document was to be halted for adjudication if its fetched
bytes disagreed with what the index-only check had recorded of that revision. All four served at the
exact CDX timestamps that check read, all four returned `application/pdf` 200, and all four bodies
are real PDFs whose page counts two independent walkers agree on — 20, 14, 36 and 4. **A second party
corroborates every one:** each capture's CDX digest is the base32 SHA-1 of its payload, and all four
were recomputed on the fetched bytes and matched.

**THE DISJUNCTION SWEEP RAN ON ALL FOUR COVERS AND ALL FOUR ARE CLEAN** — cover, running footer and
changes table agreeing in each, and each agreeing with MISP-2019.1's Appendix B read first-hand. The
cover-versus-changelog hazard was looked for in four documents and found in none, which is worth
stating because it was found in three of the documents where it was looked for before.

**PARKS 5 AND 11 ARE NARROWED TO ONE BLOCKER EACH AND NEITHER IS CLOSED.** The acquisition half is
discharged; the artefact half — an `IMAPB` codec for park 5, populating `Entity.source_ids` for park
11 — is source under `packages/` and is now marked **blocked on a per-change ruling**. The standing
rule is unchanged, and any concrete proposal goes to the maintainer with the bump gate's own
derivation attached. **Park 2 is the exact precedent** for the intermediate state: document held, row
set unwritten, park open. **The park arithmetic is unchanged in every term** — thirteen parks, four
closed, nine open. The off-peak round's framing table is **amended in place** rather than left beside
its own answer, so the record carries one state of that question and not two.

**TWO REGISTER ENTRIES, FROM A DOCUMENT THAT WAS ALREADY HELD.** KLV 18 and KLV 19 are both about
**ST 1402.2**, pinned hours earlier, and both were **re-derived from the pinned bytes at writing
time** rather than copied from the closing round's report. KLV 18: twenty-five of its twenty-six
requirement identifiers carry no revision suffix and the twenty-sixth carries the *previous*
edition's — deliberately not adjudicated, because KLV 12 rules the converse shape in ST 0107.3 as
provenance and there the suffixed form is the majority. KLV 19: the four deprecated requirements are
withdrawn as **re-specifications of ISO/IEC 13818-1 and not as facts**, so the `stream_type` and
`stream_id` values they carry still apply — and the entry states that distinction because a reader
taking "deprecated" in its ordinary sense loses exactly the ability to locate a KLV stream, which is
what park 9 existed to buy.

**TWO STALE COUNTS WERE SWEPT OUT OF `FORMAT_COVERAGE.md`, BOTH HALF A DAY OLD.** The parks preamble
said *three closed, ten open* and the download-count paragraph said *moved four times*, while park 9's
own row three rows below already read `CLOSED 2026-08-27`. **The file contradicted itself about its
own table.** Both repaired and both recorded. **This is the first full round under the widened sweep
rule 1** — the one that gained the synthetic-fixture case a commit earlier — and what it caught was
not a fixture but ordinary narrative arithmetic that no gate reads.

**A METHOD GOT WEAKER AND IS NARROWED RATHER THAN LEFT TO BE TRUSTED.** The PDF
document-information dictionary entered this record as a date corroborator, calibrated on the 0601
set where it equalled the cover exactly three times in four. These four post-date their covers by
**462, 63, 47 and 288 days**, so across nine samples the lag runs 0 to 462 and the field corroborates
only that a file was produced **no earlier than** its cover — at 462 days, not even the year. The
narrowing is written in `klv_pin.json` under its own key and **not** edited into ST 1402.2's node,
whose 47-day claim is true of that document. The four new timestamps are declared in
`MULTIPLIED_FACTS` beside the row whose calibration they retire.

**A NEAR-MISS RECORDED BECAUSE IT WOULD HAVE READ AS A FINDING.** A first pass at MISP-2019.1's
Appendix B reported ST 1301 as carrying no dated citation where the other three had one — a real
asymmetry, had it been real. It was a line break: reference [56]'s title wraps between `Local` and
`Set`, so a single-line regex missed it. Re-derived against the unwrapped text before anything was
written down.

**WHAT MOVED IN THE DISTRIBUTION, named file by file** — condition 4, and the guard that reads this
section wants names rather than a count. Four files under `packages/`: `FORMAT_COVERAGE.md` (the pin
table's four rows and the tally, the parks 5/11 section amended in place, both parks-table rows, two
stale counts, register entries KLV 18 and KLV 19, and this round's own record); `MIGRATIONS.md`, this
entry; `fixtures/klv/README.md`, which gains the tenth round and moves its delegated-document tally
from four to eight (*written as "five to nine" and corrected 2026-08-28 — see above*); and `fixtures/klv/spec/klv_pin.json`, which gains four pin nodes, the parks
narrowing, the two register entries, the document-info narrowing and the round's own node. **Every
one of them is a shipped document and none is executable.** Two files under `tests/` moved as well
and are not in the distribution. **So the arc still derives PATCH and the floor stays 1.2.2** — which
the bump gate is asked rather than told.

**WHAT THIS ROUND DID NOT DO.** No park closed. No tag row moved — all 115 `not yet` rows still read
`not yet`, and no row set was written for any of the four documents. **No source under `packages/`**:
no `IMAPB` codec, no Core Identifier decoder, no adapter, no model, no fixture, no schema, and
`SCHEMA_VERSION` is unmoved at `1.0.0`. No mirror was improvised. No new park. **No deploy, no tag,
no rendered page.**

**THE NAMING ROUND, 2026-08-28 — the carrier pattern is a class with a rule, and the decay sweep
found four claims that stop unrepaired.** Two acts, no acquisition, nothing executable under
`packages/`.

**The carrier pattern is named once and centrally, as sweep rule 9 in `synapse_cdm/README.md`.**
It had been met four times and ruled on four times, each ruling local to where it was met: the
phrase rule 8 pins, the deploy markers, the paragraph announcing a guard, and the KLV 2 correction
note. Rule 9 states the class — a record that discusses a token becomes a site of it, and a note
that corrects a figure becomes a carrier of the figure — cites each instance at its own record
rather than restating it, and states the rule the four already share: describe rather than quote,
every path by basename with no self-reference, and each live figure exactly once with its basis.
**It is rule 9 and not a fifth entry under the heading above it**, deliberately: that heading
states a count, two files quote it, and renaming it once already stranded both quotations.

**The mechanization question was answered by measuring, and it split in two.** The briefed form —
a check that refuses re-quotation *inside correction notes* — is **refused, with the refusal
recorded** on the treatment the four reverse-sweep formulations got. Two formulations were tested
against the tracked record rather than argued about: *a repair-marked paragraph states no digits*
refuses the correct form of a correction note far more often than the defective one, and *a number
occurring only inside a repair-marked paragraph is a superseded figure* returns tag numbers,
reference numbers and status codes and cannot do better in principle — where the discipline holds,
a superseded figure is absent by construction. **And the deciding argument is not either
measurement:** what KLV 2's note superseded was a figure paired with the wrong basis, both of whose
numbers are live today, so recognising one requires knowing which basis is right, which is a
reading.

**What was mechanized instead is the consequence, which the tree settles.** A carrier's effect is
that a guard loses the ability to fail, and that is countable. KLV 2's live figures are now asserted
to occur **exactly once** in their section rather than merely to be present, so a second copy fails
the build with nothing having had to recognise a correction note, and
`test_the_klv_2_figure_guard_is_not_vacuous_in_either_direction` mutates the real section both ways
— figure dropped, figure re-quoted — to prove the guard can fail in each. **The mutation check
earned itself immediately**: the first draft of that test asserted the wrong count for the
re-quoted direction and failed on the real section, which is the check working on the round that
wrote it.

**THE DECAY SWEEP: FOUR FINDINGS, AND ALL FOUR STOP FOR ADJUDICATION UNREPAIRED.** The sweep
repairs nothing, on the standing rule. Classes named, and each re-derived from held bytes or from
the tree rather than from a round report:

1. **The CAT062 `TYP` authorship split in `FORMAT_COVERAGE.md` contradicts the adapter and every
   golden fixture — BORN-FALSE.** The item's NOTE splits fourteen defined values by whether the
   name says *Predicted*. `asterix_cat062.py`'s table defines fourteen and exactly **three** carry
   that word — values 4, 9 and 12 — so eleven are the flight plan's, which is what the adapter and
   all five golden fixtures state. The document's row states a split two higher on the prediction
   side. Introduced at `dd99acd`, the specification-before-code commit, and the document has never
   said three; the adapter was written afterwards from the same table and has never said anything
   else. **The figures are described and not re-quoted here**, per rule 9.
2. **`klv_pin.json`'s root `what_this_is` is STALE.** Its convention is an append-only log of dated
   `UPDATED … BY THE … ROUND` clauses, and it stops at 2026-08-26, so its opening sentence still
   describes the file in the bare present tense as pinning seven documents obtained from four
   delegations. Two rounds on 2026-08-27 added five pins and appended nothing. The file today
   carries fifteen pinned identities, every one of which matched its bytes this round.
3. **`FORMAT_COVERAGE.md`'s tally of delegated documents obtained is one too high — BORN-FALSE, and
   it has been carried through both increments.** Derived here from the record's own two tables:
   the delegation table and the parks table give **fourteen** delegated documents, of which six are
   unobtained — the ones parks 3, 6, 7, 8, 10 and 12 stand on — leaving **eight** obtained, not the
   nine the row states. The ninth in that tally is the copy of ST 0601.19, which the same row
   declares is *not* an edition the profile pins and is retained as context only. The error entered
   when the count was first stated on 2026-08-26, because the four documents retrieved that day
   included that copy, and each re-dating preserved it.
4. **The document-info calibration is correctly scoped and materially incomplete — NOT false, and
   recorded as a narrowing rather than a defect.** All nine sampled lags were re-derived from the
   held bytes this round and **all nine match the record exactly**, as did all fifteen digests, all
   fifteen byte counts and all fifteen page counts. But the sample is nine of the thirteen PDFs
   held. Two of the four unsampled are excluded for cause — they are the KLV 9 and KLV 10 copies,
   whose covers are known not to describe their contents. **The other two are clean and were simply
   never sampled, and one of them is the sharpest case in the set**: ST 0102.12, whose cover date
   the record says three independent statements agree on and which has a single revision-history
   row, lags its cover by more than the recorded maximum. The method's conclusion is unaffected in
   direction and strengthened in degree — the field is a lower bound and nothing more.

**THE OPEN LEDGER'S TWO WITNESSED ENTRIES WERE RE-DERIVED, one confirmed and one marked
UNREACHABLE-TODAY.** Entry 2's unsigned set derives from the history to exactly the three commits
it names, over the 128 the branch now carries — the set, not a ratio, which is the point that entry
makes about itself. Entry 3's substance is confirmed from the bytes: none of the five documents it
names yields a distribution statement anywhere in its extractable text, and the two the sweep found
carrying `NATO UNCLASSIFIED` and `RELEASABLE` markings are carrying classification markings, which
are a different object from a distribution statement and do not touch the entry's claim. **What did
not reproduce is that entry's one precise figure** — the character count it gives for AEDP-12
Ed. B v2's eight front pages. This round's extractor yields a count one higher by per-page
normalization and seven higher by the joined normalization `gates/pdf_text.py` performs, and eight
methods were tried without landing on the recorded number. **That is not a finding of falsity and
is not recorded as one:** `extract_text()` output moves between extractor versions, the gap is
inside that range, and the round that wrote the figure predates the counting rule this arc
mechanized. It is marked unreachable-today with both of this round's derivations written down, so
the next round starts from two numbers and a method rather than from the bytes. **The entry's
conclusion is untouched** — either figure is a few hundred characters across eight pages of a
150-page document, which is what an image-only front matter looks like from the text layer.

**Act 0 in full, because a claim about the tree is a claim.** Tree clean, `origin/main` at the
commit this round started from, suite **3255 passed, 3 skipped** before the round and green after.
*(CORRECTED 2026-08-28 by the repair round's stale-count sweep: this read **3254 passed, 3
skipped**, which is one low and was refuted three ways — the tree at `91ef1df` collects 3258
tests, so 3254 and 3 skipped do not sum to it; re-running that tree gives 3255 and 3; and THIS
ROUND'S OWN COMMIT TRAILER says `Suite: 3255 passed, 3 skipped`, as do the two commits either
side of it. The prose disagreed with the trailer of the commit that carried it.)*
The untouchables hold: the pinned phrase derives to **35** over the git index by the command the
guard shares, `gates/scripted_edit.py`'s contract is intact and green, `RELEASE_NOTES.md` opens the
release then on the index, and `git ls-files` matches no PDF. The bump gate derives PATCH over the
arc and the floor stays **1.2.2**. **Pin-as-control was run at the widened scope before any held
byte was trusted** — every pinned digest recomputed against the file it names, with the
edition-history set checked at the `home` the pin declares rather than where a first pass assumed
it, which is why that pass reported three absences that were the reader's error and not the
record's.

**The `nga.mil` resolution series is extended by one observation and still cannot carry a window
reading.** `NOERROR` for the apex, `gwg` and `nsgreg` alike at **2026-08-28 10:56Z**, a morning
hour from the same resolver — one SERVFAIL now against three successes over three hours. **It is
not the archive quota's finding and must not be read as one:** that reading was earned by
re-testing the failing hour and getting a different answer, and nothing has ever re-tested this
one's. One failure is an intermittency until something separates the hour from the moment.

**WHAT THIS ROUND DID NOT DO.** No document was fetched and no pin was added — the PDF library it
used to re-derive the calibration was installed out-of-tree and `.venv` is unchanged. No park moved.
No tag row moved. **No source under `packages/`**, no adapter, no codec, no fixture, no schema, and
`SCHEMA_VERSION` is unmoved at `1.0.0`. **No finding was repaired**, which is the point of the stop
rule. No deploy, no tag, no rendered page.

**THE REPAIR ROUND, 2026-08-28. The four adjudicated findings are repaired, the guard-shaped one
is a guard, and the sweep's second half is done.** Each repair is its own commit and each was
made from the authority the finding named rather than from the round report that carried it.

**Act 0, and one of its own claims did not hold.** Tree clean, `origin/main` at `4ac1df3`, the
untouchables intact — the pinned phrase derives to **35** over the git index, `scripted_edit`'s
contract is green at 9, `RELEASE_NOTES.md` still opens 1.2.1 and `git ls-files` matches no PDF —
and the bump gate derives PATCH with the floor at **1.2.2**. **The brief's expected suite figure
was wrong and so was the record's:** both said 3254 passed, and the tree has said **3255 passed, 3
skipped** since `91ef1df`. It is repaired in this arc's stale-count sweep below, where the third
refutation is that the commit carrying the sentence has the trailer `Suite: 3255 passed, 3
skipped`.

**Pin-as-control at the widened scope, and the widened scope is FIFTEEN.** Every pinned digest in
`klv_pin.json` recomputed against the file it names before any held byte was read: the wrapper,
the target profile, the ten entries under `delegated_specifications_held` and the three lineage
editions under `history/`. All fifteen match in both terms. The CAT062 pins were tested the same
way before that repair was attempted, both files matching digest, byte count and page count.

**The `nga.mil` series gains one observation and STILL cannot carry a window reading.** `NOERROR`
for the apex, `gwg` and `nsgreg` alike at **2026-08-28 11:49Z**, a second morning hour from the
same resolver — one SERVFAIL now against four successes. **This round did not land in the failing
hour**: it ran from ~11:48Z and the recorded SERVFAIL is a ~14:00-15:00Z observation, so the one
reading that would settle the question was again not taken. That is stated rather than left as a
gap, because four successes outside the failing hour add nothing to the question the series is
actually about.

**Act 1(a) — the CAT062 `TYP` split, repaired to three and eleven.** Re-derived from the pinned
specification, which is the authority the finding named, and NOT from the adapter that disagreed
with the document. SS 5.2.25 Subfield #12 defines fourteen values and exactly three carry the word
*Predicted*, so the document's *five and nine* was wrong and the code was right throughout. **The
table and the NOTE that splits it are on opposite sides of a page break**, so the derivation ran
through `gates/pdf_text.py`'s joined normalization; a reader who stopped at the table's own page
would not have seen the NOTE at all. Born false at `dd99acd` and never true. One figure in the
finding did not survive its own repair and is corrected: the fixtures carrying the note are
**three**, each in an emitted and a re-parsed form, so six files rather than the five fixtures the
finding named.

**Act 1(b) — the obtained tally is EIGHT, and the dropped reason is what is restored.** Derived
from the record's own two tables: fourteen delegated documents, six unobtained and standing on
parks 3, 6, 7, 8, 10 and 12. The off-by-one was never a counting slip. Four documents were
retrieved on 2026-08-26 and only three are delegations, because the fourth is the ST 0601.19 copy
the same row declares is *not* an edition the profile pins. That distinction was stated when the
count was first written and dropped once the count became arithmetic. **The sentence was carried
at four sites and all four are repaired**, the two dated round records marked as corrected rather
than renumbered.

**Act 1(c) — the header log is appended to, five pins late, and nothing is backfilled.** Two
clauses carrying the true 2026-08-27 dates of the off-peak and pins rounds, and a third naming
**this** round as the appender and saying plainly that the two above were not written on the days
they name. One wrong figure in the opening sentence is deliberately left standing and annotated:
it reads "the four delegated documents this repository has obtained" where three is right for that
date. Editing it would be the backfill the clause exists to refuse. The counts now form a ladder —
ten of which seven, eleven of which eight, fifteen of which twelve.

**Act 1(d) — the calibration states its sample, and the sharpest case was the one left out.** All
nine sampled lags re-derived from the bytes and all nine match. **The sample is nine of THIRTEEN,
and the thirteen are now defined rather than asserted**: the held MISB documents carrying a
day-precision cover date. Fifteen PDFs are held and two are outside that set for two different
reasons — the NATO wrapper is not a MISB document, and MISP-2019.1's cover states a month with no
day. Of the four unsampled, ST 0601.19 (853 days) and ST 0601.14a (595) are excluded for cause as
the KLV 9 and KLV 10 copies; **ST 0107.3 (63) and ST 0102.12 (567) are clean and were simply never
sampled**. ST 0102.12 is the sharpest document in the set — three independent statements agree on
its cover and it has one revision-history row — so **the widest lag over cleanly-dated copies is
567 and not 462**, and 617 if the wrapper is admitted. The conclusion is unchanged in direction and
stronger in degree.

**Act 2 — `tests/test_cdm_pin_header.py`, and the failure it guards is not the shape people guard
against.** The header did not become malformed; it stayed internally consistent, well-formed and
pleasant to read while describing a repository that had stopped existing. A log whose convention is
"append when you change something" cannot notice the append that did not happen. Both sides of the
equality live in the same file and **the module counts pin NODES and never looks at the disk**,
which is why it is a real check in a fresh clone and in the wheel, where none of the fifteen PDFs
it counts is present. **Its first live subject was Act 1(c)'s own commit and it ruled it**: against
the record at `646b306` it fails with "header states 10 documents of which 7 are pins; the record
carries 15 and 12", and against the repaired record it passes. Mutation-tested on the real artefact
over four cases with the file restored byte-identically after each, the vacuity attack among them.
**Its limit is asserted rather than implied** — editing the last clause satisfies the equality
exactly as appending does, and a test says so; what refuses the edit is the failure message and the
reviewer. One regression is recorded because it happened here: the dated-clause pattern's character
class carries a hyphen, and the first draft's `[A-Z0-9 ]+` dropped the OFF-PEAK ROUND clause
entirely rather than truncating it, so the clause was present and the pattern reported one fewer
with no error anywhere.

**Act 3 — the sweep's second half, and it is COMPLETE over the named debt.** Ledger entries 1 and
4-10, `CONTRIBUTING.md`, `RELEASE_NOTES.md` and `fixtures/klv/README.md`, claim by claim, in the
first half's form. **The platform route was reachable today**, which is what made most of it
derivable rather than parked. Confirmed from outside the tree: `main-protection` carries exactly
`deletion` and `non_fast_forward` and no `required_status_checks`; `f916ba2` still returns
`total_count: 0` check runs; the contributor list is one login with two contributions; **exactly
two commits are `verified: true` with `reason: valid`** and both are PGP-signed web-UI commits; the
SBOM endpoint is 404 and secret scanning and Dependabot are disabled; Community Standards is 50%;
the `pypi` environment carries `decentcybersecurity` as required reviewer, tag policy `v*` and
`prevent_self_review: false`, created at the recorded `2026-08-26T06:46:16Z`; the repository holds
**zero Actions secrets**; runs `32944124955` and `33061413447` are the v1.1.0 and v1.2.1 publishes;
every 1.0.0 and 1.2.1 digest and byte count matches the index, and the 1.0.0 pair also matches the
two artefacts still sitting in the repository root — a third reading nobody asked for. The harness
reproduces `RELEASE_NOTES.md`'s table adapter by adapter and **408 verdicts, 0 failed**. Entry 8's
arithmetic re-derives exactly: the `docs/` diff is 5 files, 71 insertions, 22 deletions, and
`ccfa7476` is 92 seconds after `e4a1c33d`.

**One reading of this round's own was wrong and is corrected here rather than carried.** A first
pass read the legacy per-file `provenance` field as null across every release and was about to
record entry 10's attestations claim as unwitnessed. **The simple index carries the provenance URL
and the legacy JSON API does not**, and fetching it returns an in-toto subject naming the same
wheel digest and a publisher block reading exactly `GitHub` / `Decent-Cybersecurity/`
`synapsecommand-public` / `publish.yml` / `pypi`. That is **entry 6 step A witnessed from PyPI's
own side**, which entry 6 could only assert, and it arrived because the first reading was checked
rather than reported.

**TWO SWEEP FINDINGS, BOTH STOPPING FOR ADJUDICATION UNREPAIRED, on the standing rule.**

1. **Ledger entry 8's "Sixteen deployments" is one low — DECAY, and inside the entry whose own
   subject is this failure.** The entry enumerates **seventeen** distinct deployment ids, six in
   its table and eleven named below it, and `gates/deploy_record.py` run today reports "17 listed;
   6 with a row, 11 covered retrospectively; 0 unaccounted for". Two were recorded before that
   round, so the unrecorded remainder is **fifteen and not the fourteen** the entry states. The
   mechanism is visible in the table: `222a55be` was deployed by the 1.2.1 release at
   `2026-08-27 12:37:06` and its row **was** added — the three prose figures around it were not
   moved with it. **The gate does not catch this and is not failing:** it asserts that no
   deployment is unaccounted for, never that the prose's own arithmetic equals the list length. So
   this is a count no machine reads, which is precisely what entry 8 was written to say about
   deployments.

2. **Ledger entry 9's "exactly anti-correlated" is stronger than its own measurement — OVERSTATED.**
   Over the 134 commits the branch now carries the four cells are: signed-off and verified **0**;
   signed-off and not verified **131**; not signed-off and verified **2**, being `d7986017` and
   `2a51871f`; **not signed-off and not verified 1**, being `965e939d`. The two senses of "signed"
   are therefore **disjoint** — nothing is both — but **not complementary**, and "exactly
   anti-correlated across its history" requires the fourth cell to be empty. Everything measured in
   that entry is right, and the sentence beside it explaining the web-UI mechanism is exactly true
   of the two commits it describes. Entry 2 is precise where entry 9 is not: it says "The first two
   were made in the GitHub web UI".

**What the sweep covered and what it did not, so the bound is stated rather than implied.** It
swept the **witnessed and numeric** claims — every assertion carrying an id, a digest, a count, a
date or an API reading — and it is complete over those for the named debt. **It is not a read of
every prose sentence in those four files**, and no claim is made that the remainder is clean. The
residue is named that way rather than by file, because a file-shaped residue would read as though
the files not listed had been finished.

**Act 4 — the stale-count sweep found two more, both refuted by the thing carrying them.** The
suite figure above, and `klv_pin.json`'s pin-as-control node reading "the nine delegated
specifications" inside a sentence whose own total of fifteen requires ten. A third candidate is
recorded and **not** repaired: `delegated_specifications_held`'s header says "THREE are here"
against ten entries, but that sentence says *field dictionaries* and this record explicitly rules
ST 0107.3 is not one, so repairing the number would settle a question about the documents by
arithmetic. **No disjunction sweep ran, and it had no subject** — that sweep is over a newly
obtained document's identity field and this round obtained nothing.

**WHAT THIS ROUND DID NOT DO.** No document was fetched and no pin was added; the PDF library was
installed out-of-tree and `.venv` is unchanged. No park moved and no park closed. No tag row moved.
**No source under `packages/` that executes**, no adapter, no codec, no fixture, no schema, and
`SCHEMA_VERSION` is unmoved at `1.0.0`. The one executable file this round wrote is a test module
under `tests/`, which the wheel does not carry, and the one line it changed in `gates/` is a
roster entry. **Neither sweep finding was repaired**, which is the point of the stop rule. No
deploy, no tag, no rendered page, and the floor stays **1.2.2**.

**THE RULED ROUND, 2026-08-28 — the two stopped findings are repaired, the third is settled by
definition rather than arithmetic, and the sweep table's own excuse for missing the first is the
root cause.** The repair round stopped two sweep findings unrepaired on the standing rule and
recorded a third as unrepairable by counting. All three are now closed, each in its ruled form.

**Entry 8's deployment count, amended and then MECHANIZED.** The entry said sixteen where its own
table enumerates seventeen — six rows and eleven named ids, which is what
[`gates/deploy_record.py`](../../gates/deploy_record.py) reports. Amended in the KLV 11 form: the
original stands date-scoped to the set it was true under, with the falsifying act named — commit
`1fc35e8` appended the `222a55be` row for the 1.2.1 deploy and left the prose where the previous
round had it. **Only the total is restated live**, and the reason is stated in the entry: the gate
derives rows and coverage and derives nothing about which deploys earlier rounds had written down,
so restating that pair would add a figure no command recomputes — the failure being amended, one
figure over.

**The guard, and it rules the amendment that occasioned it.**
`tests/test_cdm_deploy_record.py` now requires the entry's spelled count and both its parts to equal
what the gate's two sets derive, each figure with its basis and each exactly once — sweep rule 9's
carrier rule, because the entry is dense with spelled numbers that are other claims. Both failure
directions are mutation-tested against the real entry, and a third fixture replays the incident's
actual shape: a deployment added to the enumeration with the prose untouched, which must go red. It
does. **The date-scoped original is deliberately unconstrained**, and the limit is written into the
module: constraining it would forbid the amendment form, and telling two spellings apart is a
reading of prose — the check rule 9 already specced, measured and refused.

**AND THE ROOT CAUSE WAS NOT THE DECAY.** The "gated and witnessed" table carried a cell saying the
list's length was derived by the gate and appeared in no prose. Commit `07214f9` wrote that clause,
and entry 8 spelled the figure three times in the same file at the same commit. **So the file's own
index of what is checkable told every later reader there was nothing there to check**, about the one
figure that then went stale. That is why two rounds whose declared subject was claim decay walked
past it. Corrected in the cell, describing the wrong claim rather than reproducing it.

**Entry 9's "exactly anti-correlated", corrected with its fourth cell named.** The two senses of
signed are **disjoint** — nothing is both — and not complementary. `965e939d` is signed in neither:
no `Signed-off-by` trailer, and GitHub reports it `verified: false`. **Entry 2 has named it since it
was written**, under a heading saying three commits carry no sign-off, so the sentence cites entry 2
for a set of two where entry 2 states three. **Both measurements were right and witnessed**; the
error is the word joining them, which is why a sweep that checks claims one at a time could not see
it. The web-UI mechanism survives and was re-derived rather than recalled: both verified commits
carry `committer: GitHub`, and `965e939d` carries a human one, putting it outside the mechanism's
scope rather than against it. The cells are named as sets and never as a ratio, on entry 2's rule —
a count of the remainder would have moved on the commit that recorded the correction.

**The field-dictionary question, settled by the record's own ruling.** The repair round refused to
move `delegated_specifications_held`'s "THREE are here" because the sentence says *field
dictionaries* and this record rules ST 0107.3 is not one, so moving the number alone would settle a
question about the documents by arithmetic. **That stop was right, and the other route was open the
whole time: the term had already been ruled, twice, and neither ruling reached this sentence.** The
length round recorded ST 0107.3 as the first held document that is not a field dictionary and
changed *dictionaries* to *documents* in the top-level header; `FORMAT_COVERAGE.md`'s tally row says
the same in its own words. With the term settled the number follows without judgment: **eight of the
fourteen delegations are held**, the figure `FORMAT_COVERAGE.md` re-derived from the delegation and
parks tables, and the node holds **ten documents**, the extra two being ST 0601.19 as context only
and EG 0601.1 as a park's deciding document.

**THREE was never a delegation count**, which is the part worth keeping. Written over a node holding
ST 0601.14, ST 0102.12 and ST 0601.19, it was right as a count of what was there and already one too
high as a count of delegations — the same off-by-one annotated in the top-level header and repaired
in `FORMAT_COVERAGE.md`. **This is its third site and the first where the figure and the term were
wrong together.** The sentence then passed through a point where it was accidentally right as a
delegation count while wrong as a held count, which is what kept it alive through both increments.
**One clause of it was checked and found NOT stale:** fourteen is the right total — eight
stream-governing, five mandatory-and-parked, and the Motion Imagery Handbook at park 10 — but
`delegation_table` names thirteen, because the Handbook is named by the wrapper. The figure was
right and its locus was wrong.

**The brief's own claims, checked rather than taken.** The standing rule caught one again. The brief
named an untouchable as "35 via the derivation"; nothing the derivation reports is 35 — its signals
are seven, the pending arc is five, its module has 22 tests — and the divergence is recorded rather
than reconciled to a number that would fit. Its other figures held: seventeen deployments,
`965e939d` as the fourth cell, the scripted-edit contract at nine, `RELEASE_NOTES.md` opening 1.2.1,
zero tracked PDFs.

**WITHDRAWN 2026-08-28 BY THE PROVENANCE ROUND: the finding above is itself false, and it is a
category error rather than a miscount.** "35 via the derivation" is exactly what the pinned-phrase
derivation reports. The command the record states at every site — `git ls-files -z | xargs -0 grep
-Ioh '1\.1\.0 candidate' | wc -l` — answers **35** today, `occurrences_over_tracked_files()` sums
to the same over the tracked tree, and `tests/test_cdm_prose_counts.py` holds the two equal, so the
figure is gated rather than unsourced. The three figures the paragraph above measured it against
belong to a **different untouchable**: signals and the pending arc are
`gates/bump_derivation.py`'s and the Unreleased count guard's, and the module holding 22 tests is
that gate's. Two derivations, one of them not the one
the brief named. **The refutation was already in this file, twice, in the two round records above
that state the pinned phrase's reading together with its command** — so nothing had to be measured
to find it. The standing rule did not catch a fifth brief error here; it produced one, and the next
brief inherited it as a premise. Classed **born-false**; the trace, and what it did not change, is
in the provenance round below.

**A sweep-class finding of this round's own was ALSO checked before it was
believed and did not survive:** `delegation_table` looked one short of the fourteen its sentence
claims, and the fourteenth turned out to be the Handbook rather than the missing document a first
reading suggested — a stray `ST 0605.9` inside a quoted deprecation note makes the node's raw
document-token count fourteen by coincidence, which is exactly the false finding the rule exists to
stop.

**The environment bound, re-derived twice, and the second reading is the one the series wanted.**
2026-08-28 at 13:44Z and again at **14:08Z**, resolution only, no route asked for bytes; gwg.nga.mil,
nsgreg.nga.mil and the apex all NOERROR at both, from the same resolver as every prior reading.
**14:08Z is inside the ~14:00–15:00Z hour the series had never retested**, three minutes past the
clock position of the earlier SERVFAIL probe. So the afternoon window is directly retested and does
not reproduce. One SERVFAIL episode against eight NOERRORs, and the honest summary is unchanged
except that "the afternoon is the bad window" is now a reading the sample actively disfavours rather
than one it merely could not carry. **Pin-as-control at the widened scope before anything was
trusted:** fifteen documents re-digested against their recorded pins — wrapper, target, the ten
delegated and the three lineage editions — all fifteen matching.

**WHAT THIS ROUND DID NOT DO.** No document was fetched, no CDX query was made, and no pin was
added. **Nothing executable under `packages/`** — no adapter, no codec, no model, no fixture, no
schema, and `SCHEMA_VERSION` unmoved. No park moved and no park closed. No tag row moved. No
register entry was added. The only files touched under `packages/` are `MIGRATIONS.md` and
`klv_pin.json`, both prose and both already among the **FIVE** the arc had moved, so the Unreleased
count does not move and the floor stays **1.2.2**. No deploy, no tag, no rendered page.

**THE PROVENANCE ROUND, 2026-08-28 — the figure the last round called unsourced is the one its
own derivation reports, the residue that round left dissolves on reading, and sweeping the record's
index of what is checkable found a false row of a shape no previous sweep had a name for.** Three
acts. The first reverses a finding instead of closing one, the second closes nothing because there
was nothing there, and the third is the only one that repaired anything.

**THE 35 TRACE FOUND NEITHER DECAY NOR A BIRTH DEFECT, which is the one outcome the brief did not
allow for.** The brief was written on the premise that the figure stands unsourced and instructed
this round to re-anchor the untouchable away from any number. Run first, as the audit: the command
answers **35**, `occurrences_over_tracked_files()` sums to 35 across the tracked tree, and the two
are held equal by a guard that calls the same function the human command mirrors. The trace by
history is short. `8e020eb` (2026-08-26) introduced sweep rule 8 and `PINNED_PHRASE_OCCURRENCES` in
one commit, so the figure and its derivation were born together and correct together; the last
commit that could have moved the count is `1b0316b` (2026-08-24), two days earlier, and nothing has
touched the phrase since. **Every round's commit message from `487a421` onward states the figure
together with the command**, which is a re-derivation and not a carrier. So the figure was correct
at birth, has not drifted, and is gated. The withdrawal is recorded at the false finding's own site
above.

**WHAT ACTUALLY RODE BRIEF TO BRIEF WAS THE REFUTATION, NOT THE FIGURE — and that is rule 9's
class, one layer up and pointed the other way.** The brief asked honestly whether the figure was
rule 9's fifth instance. It was not: a number re-derived by command in every round is the opposite
of a carrier. What travelled unre-derived was the *negative* claim about it — "nothing the
derivation reports is 35" — which was written into three sites in one round and then carried into
the next round's premises, where it cost this round's first act. **A carrier of a refutation is
worse than a carrier of a figure**, because a figure has a derivation somebody may re-run out of
habit while a refutation reads as the work already having been done. Nothing here is mechanized and
the honest reason is that the check is free: the paragraph that made the claim sat two paragraphs
below two paragraphs stating the correct fact with its command.

**THE RE-ANCHORING IS DECLINED, ON THE BRIEF'S OWN STOP RULE.** The ruling the brief carried as
already-made — state the command and never a number, record any current figure as a dated reading
— was ordered against a defect that does not exist. The record already states the command at every
site that states the figure, the figure is what the command reports, and a guard fails if they
part. Stripping it would remove a gated number on a false premise and leave the untouchable weaker
than it is. **The brief loses and the divergence is recorded**: the untouchable stays anchored to
both, because that is what "pin the derivation, not just the number" asked for and got.

**THE ENTRY 2 RESIDUE DISSOLVES, AND A DISSOLVED RESIDUE IS A FINDING.** `PUBLICATION.md`'s entry 2
is headed for a set of three, enumerates three rows, says three in its prose, and the tree derives
exactly those three commits as carrying no `Signed-off-by` trailer — `965e939d`, `2a51871f` and
`d7986017`, with a guard recomputing the set from the history and a second guard proving that
reader is not vacuous. Nothing in entry 2 is stale. The tension the last round left was between
entry 2 and a *pre-correction* sentence in entry 9 that cites it for a set of two, and that round's
own amendment already names it in those words. There was no arithmetic to repair, and the reason it
looked like a stale count from outside is worth keeping: **a citation can be wrong about the source
it cites without either the citation or the source containing a wrong number.**

**SWEEP RULE 10 — an index of what is checkable is itself a claim, and it gets swept like one.**
Written into `synapse_cdm/README.md` beside rule 9 from the last round's root cause, which was a
cell asserting that a figure lived in no prose while the entry above it spelled that figure three
times in the same file. The generalisation is what makes it a rule rather than an incident: a
summary of what is checkable is the fastest thing in a long record to trust and the slowest to
check, and a false one does not merely mislead — it redirects the sweeps, and keeps redirecting
them.

**APPLIED ONCE, AND IT FOUND TWO, IN THE TABLE THAT SUPPLIED THE RULE.** Both stopped for
adjudication before anything was written, on the standing rule.

* **A treatment cell named a gate and misdescribed what the gate enforces — BORN-FALSE.** It said
  `tests/test_cdm_release.py` forbids an `Unreleased` section once the release tag exists. The gate
  requires that section while shipped files have moved past the tag and forbids it only when the
  tree is identical to the tag, so a tag and an `Unreleased` section coexist legally. They coexist
  in this repository right now, on a green suite, and have since `e825e96` — written about an hour
  after the cell, at the moment the arc moved its first file. **The cell was consistent with the
  tree in the hour it was written and false about the mechanism from the start**, which is rule 8's
  substitution — a state read off the tree standing in for the derivation that produces it —
  applied to a gate's contract instead of to a count. Corrected in the cell, dated.
* **One label carried two disjoint senses and the table defined one — BORN-FALSE in the
  definition, not in the rows that use it.** The table explains a gated claim as one that cannot go
  stale because a test fails. Four of its rows apply the label to claims whose truth lives at
  Cloudflare: the deployment list's two, and the two naming which deployment serves the custom
  domain. The suite cannot reach Cloudflare and must not want to — `tests/test_cdm_deploy_record.py`
  says so while checking the part of the gate that can be wrong sitting still — so what refuses a
  stale one is `gates/deploy_record.py`, an act a person performs. **The proof they are not one
  sense is two rows of the same table**: one custom-domain claim went false inside the round that
  wrote it and another was superseded a day later, each caught by somebody running the gate and
  neither by a build going red. Both senses are kept and both are now named; relabelling the rows
  would have thrown away the weaker one, which is the honest description of four of them.

**The rest of the table holds, and the sweep is published rather than counted.** Checked one cell
at a time against the tree: the top row's two gated examples both have suite tests, and one of them
has a non-vacuity witness; the deploy mechanism is stated at two paths and its gate reads exactly
those two; the retroactive bump claim is a test that classifies every released arc from the trees
alone; the tree half of the 1.2.1 prose corrections is pinned in `tests/test_cdm_prose_counts.py` at
each of the paths the entry names; the entry 8 cell the last round corrected now names a figure its
own guard derives; release condition 5 exists and is the derivation the prose says it is. Five
cells claim a fact is *already dated* elsewhere in the file and all five resolve — the flip-day byte
identity to a timestamped paragraph, the ruleset's version history to a table dated per row, the
check-runs measurement to its own commit, and the two index readings — 1.0.0's, and 1.1.0's
with 1.2.0's — to their entries. The two
cells that record a claim as undatable or half-witnessable both resolve to the paragraph below the
table that explains why.

**The environment bound, extended into an hour the series had never sampled.** 2026-08-28 at
**18:23Z**, resolution only, no route asked for bytes: gwg.nga.mil, nsgreg.nga.mil and the apex all
NOERROR, same resolver as every prior reading. That is a new hour between the retested afternoon and
the evening window, and it does not fail. **One SERVFAIL episode against nine NOERRORs**, so the
series continues as intermittency bookkeeping and the reading it disfavours — that the failure is a
property of an hour — is disfavoured a little further. **Pin-as-control at the widened scope before
anything was trusted:** the fifteen held documents re-digested from their bytes, every digest
matching one recorded in the pin, none unmatched.

**WHAT THIS ROUND DID NOT DO.** No document was fetched, no CDX query was made, no pin was added.
**Nothing executable under `packages/`** — no adapter, no codec, no model, no fixture, no schema,
and `SCHEMA_VERSION` unmoved. No park moved and no park closed. No tag row moved. No register entry
was added. No number in the record was reconciled to a nearby number, and the one figure this round
was told to unanchor stays anchored, with the reason recorded. The files touched under `packages/`
are `MIGRATIONS.md`, `synapse_cdm/README.md` and `klv_pin.json`, all prose and all already among
the **FIVE** the arc had moved, so the Unreleased count does not move and the floor stays **1.2.2**.
No deploy, no tag, no rendered page.

**THE WITHDRAWAL-SITE ROUND, 2026-08-28 — one of the two carried findings was already repaired,
the other was half repaired, and the withdrawal check found a carrier where it expected none.**
Three of the brief's four acts turned on something the brief asserted being wrong about the tree,
which is what the standing rule is for. The rule now reads in its widened form — figures, citation
paths and RULINGS alike are claims to verify — and this round is the first where it was the
*rulings* that failed rather than the figures.

**ACT 1 WAS ALREADY DONE, AND THE BRIEF DID NOT KNOW IT.** The brief instructed a repair of the
treatment cell that misdescribed `tests/test_cdm_release.py`, as though the cell still carried the
false sentence. It does not: the ruled round's successor repaired it, dated it and classed it, and
the repair is correct. Verified from the source rather than from the cell — the gate's predicate
re-derived at `tests/test_cdm_release.py`'s
`test_package_source_that_has_moved_past_its_released_tag_is_recorded_as_unreleased`, which
requires the section while the moved set is non-empty and forbids it only when the set is empty;
the coexistence re-established from the history, with the section absent at `1fc35e8`'s parent and
present from `e825e96`, the tag an ancestor of both and the suite green over the whole span. The
birth commit the record names also holds: `1fc35e8` at 13:49 carried the false sentence and
`e825e96` at 15:05 refuted it, an hour and a quarter later, which is the "about an hour" the record
claims. **Nothing was written for act 1**, because a correct repair rewritten by the next round is
how a record acquires two accounts of one defect.

**ACT 2 WAS HALF DONE, AND THE HALF LEFT UNDONE WAS THE HALF THAT MATTERED.** The finding round
named the two senses — **suite-gated**, a claim a suite test reads, and **protocol-gated**, a claim
whose truth lives at Cloudflare — and then left every row of the sweep table under the collapsed
label, recording the split in a paragraph beneath the table. Its stated reason was that relabelling
"would have thrown away the weaker one, which is the honest description of four of them", and that
reason inverts: labelling those four rows protocol-gated is what APPLIES the weaker sense. The
un-relabelled table is what discarded it. So the rows are relabelled, both terms are defined once
each in the kinds table where the table's terms live, and the reversal is recorded in
`PUBLICATION.md` beside the original decision rather than replacing it.

**WHICH ROWS MOVED WAS RE-DERIVED AND NOT COUNTED TO FOUR.** Each cell was read against what
actually refuses its claim. Four name `gates/deploy_record.py`, which shells out to `wrangler` and
which `tests/test_cdm_deploy_record.py` asserts in as many words is not a suite member — those are
protocol-gated. Two name suite tests that read only the tree, `test_cdm_deploy_workflow.py` and
`test_cdm_prose_counts.py`, and stay suite-gated. One keeps its **at one remove** qualifier and
fits the suite-refuses class on inspection rather than by its label: the suite test it names gates
a proxy — a tag matching its tree's `PACKAGE_VERSION` — and nothing in the suite reads the index
itself. **No row fitted neither class**, so nothing stopped here. The derived split is four
protocol-gated, three suite-gated of which one at one remove, and zero rows under the retired word.

**THE TIER ROSTER WAS GATED ALL ALONG, WHICH IS WHY THE RENAME COULD NOT BE HALF-DONE, AND THE
GUARD WAS VACUOUS IN THE DIRECTION THAT MATTERED.**
`tests/test_cdm_publication.py::test_the_record_states_what_it_cannot_check` pins the tier
vocabulary, so the rename turned it red immediately and the roster was amended to the four tiers.
Its membership test was then mutated and **survived renaming the `Protocol-gated` row**, because
all four tier names also occur in the prose below the table, so a test for the bare token was
satisfied by the paragraph that DISCUSSES a tier while the tier itself was gone. It now matches the
table row. That is the round's own instance of the finding it was repairing: a check on an index
that reads the commentary beside the index. Three mutations refuse it now — the retired label
restored on a row, and either of two tier rows renamed — and a fourth assertion refuses the
collapsed label as a row label outright, so the split cannot be silently reverted while the roster
still names both senses.

**ACT 3 — THE WITHDRAWAL CHECK, AND IT FOUND A CARRIER WHERE THE BRIEF EXPECTED NONE.** The brief
predicted zero carriers beyond the already-classed site and instructed that the result be recorded
either way. It is not zero. Every tracked site mentioning the withdrawn refutation was enumerated
by walking the record and every pin as data rather than by reading prose: three sites, all in this
file and in `klv_pin.json`. Two state the withdrawal. The third — the ruled round's own node in
`klv_pin.json`, at the field recording what the standing rule caught in that round's brief — still
asserted the refutation unqualified, with no withdrawal anywhere in the node. **It was the last
carrier, and it is exactly the shape act 3 was sent to look for**: the refutation that reached a
later brief as a premise, still sitting where it was written, in a file a round reads for its pins
rather than for its history. The two memory-file echoes the brief raised as candidates do not
exist; `synapse_cdm/README.md`'s rule 8 states the figure live with its derivation and never the
negative claim about it.

**THE CARRIER IS ANNOTATED AND NOT EDITED, AND THE WITHDRAWAL IS PLACED WHERE A SWEEP LANDS.** The
node's text is not rewritten, backfilled or re-dated, on the convention `klv_pin.json`'s own
`what_this_is` follows. A dated withdrawal clause was appended to the node instead, and then MOVED
to sit immediately after the field that carries the refutation — one line below it in the
serialised file, with the withdrawal in the key's own name. The first placement put it at the end
of the node, which is a node-level withdrawal a reader gets to and a `grep` does not. The clause
describes the withdrawn claim rather than re-quoting it and does not restate the figure, which is
stated once with its basis at rule 8: a second copy inside a withdrawal note is the carrier shape
rule 9 names, and writing one here while repairing a carrier would have been the round's second
instance of its own finding. **The superseded tally goes with it** — the count of brief errors the
standing rule had caught was four in five rounds, not five.

**A CLEAN CHECK WOULD HAVE BEEN A DATED READING; THIS ONE IS A REPAIR, AND THE DIFFERENCE IS THE
BRIEF'S THIRD LOSS.** Act 1's premise was stale, act 3's expectation was false, and act 2's
inherited reasoning was unsound. None of the three was detectable from the brief — each needed the
tree — which is the whole content of the widened rule. **What the brief got right** was checked one
at a time and held: tree clean, remote at `b56bc57`, suite green, the scripted-edit contract at
nine, `RELEASE_NOTES.md` opening 1.2.1, zero tracked PDFs, the bump gate green deriving PATCH with
the floor at **1.2.2**, the Unreleased count at **FIVE**, the pinned-phrase derivation answering
what `README.md` rule 8 says it answers, and the expected four rows moving — that last one derived
rather than accepted, and it is the one expectation of the four that survived being re-derived.

**ONE CARRIER IS OPENED DELIBERATELY AND NAMED.** `PUBLICATION.md`'s reversal paragraph is now the
only place in that file spelling the retired collapsed label, so a sweep for it arrives at the
explanation instead of a surviving row. It cannot be made unspellable the way rule 9's three
mechanized instances were — a retired label has to be named to be retired — so it is named, twice,
inside the sentence that retires it, and the table it describes carries none.

**The environment bound, extended into an hour the series had never sampled.** 2026-08-28 at
**19:47Z**, resolution only, no route asked for bytes: gwg.nga.mil, nsgreg.nga.mil and the apex all
NOERROR, same resolver as every prior reading. That is the evening hour after the 18:23Z reading
and it does not fail. Intermittency bookkeeping only: **one SERVFAIL episode against ten NOERRORs**.

**Pin-as-control at the widened scope, run before anything was trusted, and its decomposition is
stated rather than inherited.** Every `local_path` paired with a `sha256` in all eight pin files was
re-digested from the bytes on disk: **TWENTY** distinct pinned copies, of which **EIGHTEEN** are
documents under a `spec/` directory — all eighteen present, all eighteen matching, none unmatched —
and two are the walk round's transport-stream artefacts under `fixtures/klv/streams/`, both absent
from disk, which is what a held-but-never-committed stream looks like after the round that held it.
*(CORRECTED 2026-08-28 by the blocker round's stale-count sweep: they are NOT absent. Both sit at
the REPOSITORY ROOT — `local_path` is package-relative for the `spec/` documents and
root-relative for the streams — with mtimes of 2026-08-26, two days before this round, and both
digest to their pinned values. So the widened scope is twenty present and twenty matching, not
eighteen of twenty. The absence was a path-resolution error of exactly the class the round before
this one had already recorded.)*
**That is a different decomposition from the "fifteen documents" the last two rounds recorded, and
it is not a disagreement**: fifteen counts the documents the KLV directory holds, of which twelve
are pins, while eighteen counts pinned copies across every fixture directory. Both are derived and
they measure different sets, which is the distinction the pin's own header keeps between a document
and the copy that was read.

**WHAT THIS ROUND DID NOT DO.** No document was fetched, no CDX query was made, no pin was added,
no acquisition of any kind. **Nothing executable under `packages/`** — no adapter, no codec, no
model, no fixture, no schema, and `SCHEMA_VERSION` unmoved. No park moved and no park closed. No
tag row moved. No register entry was added. **Act 1 wrote nothing**, and no correct repair was
rewritten. No number was reconciled to a nearby number: the one figure this round derived against
an expectation, the four moved rows, was derived first and agreed afterwards. The files touched
under `packages/` are `MIGRATIONS.md`, `synapse_cdm/README.md` and `klv_pin.json`, all prose and
all already among the **FIVE** the arc had moved, so the Unreleased count does not move and the
floor stays **1.2.2**. `PUBLICATION.md` and `tests/test_cdm_publication.py` are outside the
distribution and move nothing a release ships. No deploy, no tag, no rendered page.

**THE BLOCKER ROUND, 2026-08-28. Parks 5 and 11 are put to the ruling they wait on, and the two
rows turn out to want ONE ruling at the first step and TWO at the second.**

**Act 0, and the audit's own figures.** Tree clean, `origin/main` at `a40bd02` and `HEAD` equal to
it. Suite **3271 passed, 3 skipped**. The untouchables hold, each by its own command: the pinned
phrase derives to **35** over the git index, `scripted_edit`'s contract is green at **9**,
`RELEASE_NOTES.md` opens **1.2.1** on the index, and `git ls-files` matches **no** PDF. The bump
gate derives **PATCH** over the arc with the floor at **1.2.2**, and `--mutation-check` proves both
refusal directions and the unruled case on its five fixtures. **One reading needed care and is not
a finding:** `pytest -k scripted_edit` collects **11**, not 9 — the extra two are
`test_cdm_version_floor.py`'s parametrisations, which carry the module's name and are not its
contract. The contract file is `tests/test_cdm_scripted_edits.py` and it holds **9**.

**The `nga.mil` resolution series is extended by one observation.** `NOERROR` for the apex, `gwg`
and `nsgreg` alike at **2026-08-28 20:17Z**, resolution only, no route asked for bytes, from
`192.168.0.1` as every prior reading. That is the evening hour after the 19:47Z reading and it does
not fail. Intermittency bookkeeping only: **one SERVFAIL episode against eleven NOERRORs**.

**Pin-as-control at the widened scope, decomposed from the files rather than inherited.** Every
`local_path` paired with a `sha256` across all eight pin files was re-digested from the bytes on
disk: **21** such pairs resolving to **TWENTY distinct copies** — `day_flight.klv` is pinned twice,
which is the whole of the difference — of which **EIGHTEEN are documents under a `spec/`
directory**, three of them under `spec/history/`, and **two are the transport-stream artefacts**.
**All twenty are present and all twenty match; none is unmatched and none is absent.** That last
clause is where this round's derivation parts company with the one it inherited, and the divergence
is Act 0's finding rather than a decomposition dispute — see the sweep below. The choice between
"fifteen documents" and "eighteen pinned copies" is settled the same way the last round settled it
and for the same reason: they measure different sets, fifteen counting the documents the KLV
directory holds and eighteen counting pinned copies across every fixture directory. This round
states **twenty**, because the two stream copies are pinned copies that were re-digested like the
rest.

#### Act 1 — Park 5, the decision memo

**The existence check first, because the protocol now requires it of every commanded repair.** No
`IMAPB` codec exists. `grep -i imapb` over `packages/` returns **two** hits, both prose in
`adapters/klv_codec.py`'s module docstring naming this park; `klv_uas_codec.py` and
`stanag4609.py` return none. The artefact is unwritten, so this is a memo and not a verification
note.

**The blocker, in one sentence.** *Park 5 waits on permission to write new source under
`packages/` — an `IMAPB` codec — and on nothing else, both its documents being held, pinned and
re-digested clean this round.*

**The minimal change that would unblock it.** A new importable module carrying ST 1201.3's
forward map and its inverse for egress, plus the tag rows that consume it. **New importable name,
new fixtures, new tests.** ST 1303.1 is not on the critical path and the record already says why:
`1303` occurs **zero** times in ST 0601.14a's 218 pages, so the governing document delegates
nothing to it and the delegation is MISP-2019.1's alone.

**The cost, and which guard rules it.** `gates/bump_derivation.py`'s `_classify_module` reads a
module that APPEARS as every unit added, and a public unit among them fires *"a public top-level
name appears"* — **MINOR**, derived by the gate with no human ruling required. So the **1.2.2 floor
does not hold** and the next release is **1.3.0**. The gate's own mutation fixture confirms the
shape: *"a MINOR arc numbered MINOR — an adapter added and the number moved by one minor"*.

**What closing park 5 would claim, and what it would not.** It would claim that the mapping
mechanism is written and that the rows delegating to it can be read. **It would not claim a single
held octet is newly understood.** Re-derived from the bytes this round rather than carried:
**fourteen** of the 141 Table 1 rows have a Format column reading `IMAPB` — tags 96, 103, 104, 105,
109, 112, 113, 114, 117, 118, 119, 120, 132 and 134, which is the row's own enumeration reproduced
exactly — and the sections reach **sixteen**, adding 128 and 130 whose `vlp` packs map members with
IMAPB. **Not one of the sixteen is in the pinned stream**, whose 26 witnessed items stop at tag 65,
verified this round by walking `day_flight.klv` rather than by citation. **The row that bites is
tag 112**, Platform Course Angle: the shipped adapter emits `kinematics.course_deg=None` on all six
packets, measured, and 112 is what would fill it.

#### Act 2 — Park 11, derived independently, and its plan cell does not hold

**The existence check, and it is the finding.** `Entity.source_ids` is **not** empty today.
`adapters/stanag4609.py:369` sets `source_ids=[SourceId(system=OBSERVATION_SYSTEM,
external_id=f"{stamp_us}|{index}")]`, and running the shipped adapter over the pinned stream emits
`[('UAS-LS-PACKET', '1245257585099653|0')]` on every packet. `OBSERVATION_SYSTEM` is documented in
that module as *"the adapter's own construction over items that identify nothing"*.

**So the plan's bump cell rests on a premise its own tree refutes.** The cell reads: the PATCH row
*"does not describe an `Entity` that gains a `source_ids` it did not carry"*. **One phrase doing two
jobs** — true read as *gains a source id it did not carry*, false read as *gains the field* — and
**the bump argument rides on the false reading**, because "the field appears" is a surface change
and "an existing field carries a second, better-sourced entry" is not. It was false when written:
adapter #10 shipped 2026-08-26 emitting this `source_ids`, and the cell was written on the evening
of 2026-08-27. **Finding first, memo second**, per the brief.

**The blocker, in one sentence.** *Park 11 waits on permission to write source under `packages/` —
decoding item 94's MIIS Core Identifier into `Entity.source_ids` — and, separately, on a written
bump ruling that the gate will refuse to derive for it.*

**The minimal change that would unblock it.** A MIIS decoder in `klv_uas_codec`, and a call site in
`stanag4609.py`'s `_translate` that appends the decoded identity beside the packet key rather than
replacing it — the packet key is what makes an `Entity` addressable when item 94 is absent, which
is every packet of the only stream held.

**The cost, and which guard rules it — re-derived, and it is not what the plan says.**
`functional_units` keys a module by its **top-level** statements, so a change inside `_translate`
is a change to the public unit `Stanag4609Adapter`, which exists at both ends of the arc. With no
name added or removed in `stanag4609.py` there is no roster move to explain it, and
`_classify_module`'s last branch files it as an **Ambiguity**: *"changed on functional lines with
NO name added or removed and no roster behind it"*, and the branch's remedy clause sends the reader
to this file's arc section to rule the unit by hand. The gate's own
mutation fixture names this exact case — *"UNRULED — an unruled arc — a function body moved with no
name added, removed or rostered"*. **So the gate REFUSES park 11's change rather than classifying
it**, printing `synapse_cdm/adapters/stanag4609.py:Stanag4609Adapter`, and a
`**Bump ruling.**` paragraph naming that unit verbatim is required before the arc measures. The
plan's *"MINOR at least"* is not wrong about the direction; it is wrong that the gate supplies it.

**What closing park 11 would claim, and what it would not.** It would claim that the only identity
the format guarantees can key an `Entity`. **It would not claim that any held octet was decoded:**
item 94 is **absent from the pinned stream**, verified this round by walking the bytes, so the
decoder would ship against no witness — the sharper form of park 5's risk, and the reason the
appending call site above matters rather than a replacing one.

**ARE THE TWO PARKS THE SAME RULING WEARING TWO ROWS? At the first step yes, at the second no, and
the difference is the whole answer.** Both parks' first blocker is one ruling: the standing rule on
source under `packages/`, and a single answer to *"may source be written for the KLV adapter"*
unblocks both. **They diverge at the second step.** Park 5's bump is derived by the gate
automatically and costs the 1.2.2 floor. Park 11's bump is **refused** by the gate and costs a
second, separately written human ruling that park 5 does not need. **So one ruling is being
requested for both, and park 11 additionally requests a second.** A round that asked for "a ruling
on parks 5 and 11" as one item would get park 11 half-unblocked.

#### Act 3 — the parks table swept, and four of the nine open rows have decayed

**The sweep repairs nothing.** Each row was asked the two questions the brief sets — does its
stated blocker still match what its plan needs today, and does it cite anything the last seventeen
rounds have obtained or refuted — and every answer is derived from the tree or from held bytes
rather than from the row beside it. **Nine parks are open: 2, 3, 5, 6, 7, 8, 10, 11 and 12.**

**Park 2 — DECAYED, and the record refutes it in its own prose.** The row's Reopen cell reads
*"Public download. Blocks the confidentiality ruling … so until it lands, nothing this adapter
emits can be claimed conformant"*. **ST 0102.12 landed on 2026-08-26**; it is pinned in
`klv_pin.json` and was re-digested clean in this round's pin-as-control. The record says so itself
two sections above the table — *"Park 2 is the precedent: ST 0102.12 held since 2026-08-26, row set
unwritten, park open"* — and the delegated-documents row counts park 2 among the obtained, listing
only parks 3, 6, 7, 8, 10 and 12 as standing on unobtained documents. **Class: the acquisition half
is discharged and the row was never given the update parks 5 and 11 received.** Park 2 is in
exactly the state those two rows describe at length and its own row still describes step one as
pending.

**Park 3 — DECAYED, and the refutation is the shipped adapter.** The row reads *"Blocks
`Event.observed_at` — the one CDM field this format's own users would consider mandatory"*. Running
adapter #10 over the pinned stream emits `observed_at = 2009-06-17 16:53:05.099653+00:00` on every
packet. The record already contains the narrowing: the tag 2 row says **"Promoted"**, reads the
epoch out of ST 0601.14 §6.4 and §8.2, and states twice that *"park 3 is not closed by this: ST
0603.5 still owns what to call a scale of SI seconds since 1970 that is not UTC"*. **Class: the
blocker was narrowed elsewhere in the record and the row was not re-derived.** What park 3 owns
today is the timescale's NAME, not the field.

**Park 6 — DECAYED, mildly, and only in its second half.** The row reads *"what would make this
adapter emit `Event`s of type `DETECTION` rather than only parked bytes"*. The `DETECTION` half
stands. **"Only parked bytes" does not:** the adapter emits six `Entity`/`Event` pairs with a GNSS
position, `speed_mps=46.0` and `STATUS_CHANGE`, measured this round. **Class: a comparison written
against an adapter that had not shipped yet.**

**Park 11's plan cell — DECAYED, and it is Act 2's finding above rather than the sweep's.** Named
here so the table sweep and the memo agree on the count: **four decayed rows, and this is the
fourth.**

**Park 7 — CLEAN.** Four cells, a document unobtained, one section citation, and nothing that any
round has since obtained or refuted.

**Park 10 — CLEAN, and a near-false finding is declined.** `spec/misb-misp-2019-1.pdf` is held and
matched, which read at a glance as park 10's document arriving without its row moving. **It is not
that document.** The held copy is `klv_pin.json`'s `target` — the 73-page MISP-2019.1 profile, the
thing being profiled. Park 10 is the **Motion Imagery Handbook**, a companion volume, and the
record already carries the distinction verbatim: *"Named by the wrapper and NOT held"*. **The row
stands unchanged**, and this is recorded because the near-miss is the interesting part: two
documents whose short names differ by nothing a filename shows.

**Park 12 — FLAGGED, at lower confidence, and not called decay.** The row prices itself on a
partition: *"parks 4, 5 and 8 are enough to READ a stream at all, and parks 1, 3, 11 and 12 are
enough to TRANSLATE a conformant one"*. Read as **sufficiency** it is untested and nothing here
touches it. Read as **necessity** the tree refutes both halves: the pinned stream is read today —
six packets, 26 items, walked end to end — with parks 5 and 8 open, and it is translated today into
positions, kinematics and instants with parks 3, 11 and 12 open. **Class: a partition written
before adapter #10 shipped and not re-derived since.** Named rather than repaired, and flagged
rather than ruled, because the sentence is ambiguous between a claim the tree refutes and one it
does not reach.

**Park 8 — UNTOUCHABLE, verified unchanged rather than assumed.** Its row is line 9777 of
`FORMAT_COVERAGE.md` and its SHA-256 opens `f16f602d7473`, taken at the start of this round and
re-taken at the end. `FORMAT_COVERAGE.md` is not modified by this round at all, so the row is
unchanged by the stronger fact that the file is.

#### Act 0's finding, repaired here as a stale-count sweep item

**The last round reported an absence that was the reader's error, and it is the same error the
round before it warned about.** Its pin-as-control recorded the two transport-stream artefacts as
*"both absent from disk"*. **They are present.** `fixtures/klv/streams/day_flight.klv` and
`day_flight.mpg` sit at the **repository root**, mtimes **2026-08-26**, two days before that round
ran, and both digest to their pinned values exactly. The cause is path resolution: `local_path` is
package-relative for the `spec/` documents and repository-root-relative for the streams, and a
single base applied to both makes the streams vanish. **The round before last had already written
the warning** — its own first pass *"reported three absences that were the reader's error and not
the record's"* — and the next round reproduced the class in the same step. **This round's first
pass reproduced it a third time** and caught it only by looking for the files rather than trusting
the resolver, which is why it is recorded as a property of the method and not of a round.

The correction is made in place beside the claim rather than appended, so a reader arriving at the
sentence meets its refutation there. **The last round's commit message carries the same
formulation** and is not rewritten; a message is a historical artefact and the record is the thing
that has to be right.

**THE REFUSED-RELEASE ROUND, 2026-08-29 — 1.3.0 was derived, built, verified and REFUSED. The round
closes at 1.2.1 with one scope repair and THREE gate defects, every one of them found by taking the
release far enough to trip it. The brief's own release gate turns out not to exist in the tree, and
the release was refused anyway.**

**What this round did NOT do, first, because it is the headline.** No tag exists. Nothing was
pushed to any index. `PACKAGE_VERSION` is **1.2.1** and `SCHEMA_VERSION` is **1.0.0**, both
unmoved. The distribution on the index is unchanged. The version bump, the rolled release section
and the rewritten notes were all written, verified and then **unwound**, and this record is what
survives them.

#### Act 0 — the audit, and its figures

Tree clean, `HEAD` equal to `origin/main` at `86cbf9e`. Suite **3391 passed, 3 skipped**. The
untouchables hold, each by its own command: the pinned phrase derives to **35** over the git index,
`scripted_edit`'s contract is green at **9**, `RELEASE_NOTES.md` opens **1.2.1** on the index, and
`git ls-files` matches **no** PDF. **Exactly one of the four cites the version**, the
`RELEASE_NOTES.md` opening — and its guard reads `PACKAGE_VERSION` rather than a literal, so it
would have moved without an edit. All four are unchanged at the close, because nothing shipped.

The bump gate was **run and not copied**: declared **1.2.1**, a PATCH over `v1.2.0`, with the
pending arc since 1.2.1 deriving **MINOR** and the floor at **1.3.0**. `--mutation-check` witnessed
both refusal directions and the unruled case on its five fixtures. **Re-run at the close and
identical**, which is the point of recording it twice in a round that moved the number and put it
back.

**Pin-as-control, third live run through the resolver:** 21 `local_path`+`sha256` pairs stated by
**six of the eight** pin files, resolving to **20 distinct copies** — 18 spec and 2 stream, twelve
of the spec copies under `fixtures/klv/spec` — all twenty present, all twenty matched, the
decomposition derived by `decompose()` rather than narrated. Identical in every part to the two runs
before it.

**The `nga.mil` resolution series is extended by one observation.** `NOERROR` for the apex, `gwg`
and `nsgreg` alike at **2026-08-29 09:21Z**, resolution only, no route asked for bytes, from
`192.168.0.1` as every prior reading. Bookkeeping only, and the tally is carried rather than
derived, on the ground earlier rounds stated: **fifteen NOERROR readings against one SERVFAIL
episode**.

#### Act 1 — sweep rule 11's scope, and the existence check had a subject

**The shipped text did not say table-scope, so the repair was written.** Rule 11's per-round sweep
was three bullets under a preamble stating no scope at all, and its first bullet reads *each open
row's blocker* — correct for a blocker and, being the only scope word in the list, read as the
list's. Meanwhile the rule's own fourth instance had been found in a **closed** row, and the
paragraph recording it says in as many words that a sweep scoped to open rows would not have opened
it. **The spec had never caught up with its own witness.**

The scope is now stated above the list; the witness is cited at its own record site rather than
restated, because a second copy of its two figures is the carrier shape rule 9 names; and the one
open-scoped bullet says which it is and why its subject makes it so. **The mechanized half already
agreed** and was checked rather than assumed: `check_set_claims()` walks every row, and
`blocker_existence()` is open-scoped and says so in its own docstring — an unheld document is what
an open row waits on, and a closed row waits on nothing.

#### Act 2 — the release gate the brief specified, which the tree does not have

**THE BRIEF LOSES ON ITS OWN ACT 2, and the release was refused notwithstanding.** Both halves of
that sentence are the finding, and they point opposite ways, so both are recorded.

The brief conditioned the whole release on a step it named *"the release protocol's step C"*,
requiring a dated PyPI token witness and instructing refusal if the witness were absent. Checked
before any release mechanic ran, in three parts:

* **There is no step C in the release protocol.** "Releasing the package — the procedure", above,
  states **five numbered conditions**; none is lettered and none mentions a token, a witness or a
  date. Verified by reading the section and by sweeping every `*.md` at the repository root and in
  this package for a lettered step. The only lettered steps in the tree are `PUBLICATION.md` ledger
  entry 6's, which is a **one-time trusted-publishing migration** rather than a per-release gate.
* **That step C is closed, not pending.** It is *retire the 1.0.0 API token*, recorded **done
  2026-08-26** under a heading that says so. Its own "Where this stands" table once read `NOT DONE`
  four paragraphs above that heading, and that is already a recorded ledger defect — entry 9 —
  struck as never true.
* **The brief is right that one claim in the record carries no date, and wrong about what that
  means.** The witness table's row for *the token is revoked; OIDC is the only way in* reads
  **UNDATABLE from held evidence**, because PyPI publishes no token state. The record's own
  treatment says an invented "verified as of" on a fact nothing can check is the failure the whole
  file exists against.

**So the brief's gate is not a gate that can ever open.** Its condition is unobtainable by
construction, which makes *"no token witness, no release"* a permanent refusal rather than a
protocol step, refusing on a requirement the release procedure does not contain. That is the shape
of the ruling the blocker round declined: an instruction ordered against a defect that does not
exist. The finding is recorded rather than reconciled.

**AND THE RELEASE WAS REFUSED ANYWAY, BY THE MAINTAINER, WHICH IS A DECISION AND NOT A
DERIVATION — and the distinction is the whole reason this paragraph exists.** The round put the
finding above and the completed, verified release side by side and asked; the ruling came back to
refuse and close at 1.2.1. **Nothing in this repository refused it.** The five conditions were
satisfiable, the artefact passed every check below, and no gate went red on the release itself. So
the refusal is recorded here as **a dated reading with the step it failed** — *2026-08-29, refused
for want of a dated PyPI token witness* — and immediately beside it, because a record that stated
only the first half would assert a gate the tree does not have: **that step is the brief's and not
the release procedure's**, and a later round re-deriving it will not find it. **A version number is
the one claim in a release that can never be corrected**, and a PyPI filename is permanent; on an
irreversible act, a refusal that costs a round is cheaper than a publication that cannot be undone.
**This is the house's oldest form working as intended** — a small round that stops honestly — with
the one qualification that it stopped on a decision and says so.

#### Act 3 and Act 4, which ran in full and were then unwound

Recorded because the work is the evidence for the refusal being cheap rather than forced, and
because two of this round's three findings only exist because the release went this far.

**The number was derived and it was MINOR.** With the bump applied, `gates/bump_derivation.py`
reported `declared_kind == derived_kind == MINOR` over `v1.2.1 → the working tree`, from
`adapters/imapb_codec.py`'s public top-level names and the new fixture set at `fixtures/klv/imapb/`
— two entries in `version.py`'s MINOR list, read verbatim. **1.3.0 was the right number**, and
condition 5 would have had its first live release.

**Every guard citing the old version was witnessed RED before any was touched**, which the brief
required. The bump landed alone and the suite named four: the two-version pin in
`tests/test_cdm_packaging.py`, the release-notes heading, the documented tag commands at their two
sites, and the bump gate's JSON measurement. Three moved by an edit under their own stated rules.
**The fourth cannot be moved by an edit at all**, and it is the interesting one: the gate reports a
null pending arc until a tag exists for the declared number, so it goes green on the **tag** and is
red by construction in the commit that bumps. Both states were witnessed.

**`SCHEMA_VERSION` was verified rather than assumed to hold.** The diff over `schemas/` since
`v1.2.1` is empty, `models.py`, `enums.py` and `schemas.py` are untouched across the whole arc, and
the generated schemas report CURRENT at 1.0.0. No row of the schema table is reached.

**The artefact was built and verified before anything left, and nothing left.**
`gates/wheel_install.py` reported **13 checks, 0 failed** on the tagged tree, with
`--mutation-check` still refusing the fixture-less wheel on five of them. Read off the exported
artefacts directly rather than from the gate's summary: the wheel's manifest **equal to `git` in
both directions**; **42** `.py` files under the package against the same 42 `git` tracks, with no
`.so`, `.dylib`, `.exe`, `.sh` or `.pyc` in either artefact; and **zero PDFs** in the wheel, zero in
the sdist, zero tracked. `twine check --strict` passed both files. `twine` was installed out of
tree, never into `.venv`, which the suite judges.

**The unwind, and what it means for the numbers above.** The bump, the rolled release section, the
rewritten notes and the moved guards were reverted; the tag was deleted before it was ever pushed;
`RELEASE_NOTES.md` opens 1.2.1 again and the two-version pin is back at 1.2.1 and 1.0.0. The bump
gate re-derives the pending arc as **MINOR with the floor still at 1.3.0**, which is exactly where
Act 0 found it — **a refused release leaves the floor, not a gap**. The three repairs below are all
that survive under `packages/`, plus this record.

#### The three gate defects, which are the round's return

Each was found by taking the release to the point where the gate actually runs, and none of them
would have been found by a green suite on a tree nobody tried to release.

**ONE — a prose carrier had defeated two release gates.** Both key on the literal heading of the
pending-arc section and both are conditional on the file containing it: one skips when it is
absent, the other **requires** it to be absent once the package tree is identical to its tag. A
round record quoting the bump gate's own refusal message spelled that heading in full. Today that
is harmless, because the real heading appears earlier in the file. It stops being harmless at
exactly one moment — when a release absorbs the section and the heading goes with it — and **this
round watched both gates fail on it**: the first stopped skipping and read the quoted message as
the section, and the second would have refused the tagged tree outright. The tag could not be made
until the quotation changed. **Rule 9's carrier pattern landing on a gate's own precondition rather
than on a reader**, which is a first. Repaired by eliding the heading, and the paragraph now says
the elision *is* the repair, so a later round does not restore the full quote for fidelity.

**TWO — condition 2's gate was red on `main` before this round touched anything.**
`gates/wheel_install.py` refuses a distribution whose shipped prose names the package's own
contents by the repository's layout — a directory an installed reader HAS under another name, so
the instruction looks correct, resolves, and fails on a path they never chose. The 2026-08-28 build
round's own record of the two-base pin defect spelled that layout while explaining it, and shipped.
**The gate has refused the built artefact ever since — one line, red on `main` for a day, with a
green suite over it the whole time.** The reason nothing noticed is structural: condition 2's actor
is the release workflow, the workflow runs on a tag, so **the only gate that reads the built
artefact is also the only one nothing exercises between releases**. Repaired at the sentence, which
now states both bases without spelling either as a path and points at `gates/pin_paths.py`'s
`BASES`. **Mechanized as well as repaired**, because this round is the proof that waiting for a tag
does not work: `tests/test_cdm_packaging.py` runs the same needle over the tracked distribution — no
wheel, no venv, no network — and was witnessed refusing the **real** incident at `86cbf9e` rather
than a fixture. The wheel gate stays authoritative over the built artefact, which sees what
`package-data` sweeps in that `git` does not track.

**THREE — the Unreleased count gate's own non-vacuity witness mutated the wrong sentence.** The
witness proves the parser reads the anchor rather than agreeing with it by luck: change the count,
require the parser to notice. **The substitution ran over the whole section with `count=1`**, so it
replaced the first lookalike token instead of the one the parser reads. Witnessed on the two-file
arc the release produced, whose section said *"the two documents that moved"* above the anchor: the
opening paragraph was mutated, the anchor kept saying `2`, the parser returned the unchanged count,
and the witness reported that **the gate** was not reading its own sentence. **The gate was right
and its witness was wrong** — worse than a stale figure, because a witness that accuses the
mechanism it defends invites repairing the mechanism. It is `gates/scripted_edit.py`'s founding
incident inside the suite that cites it: a non-unique anchor is a bug and not a coin flip. Repaired
twice over — the mutation now applies to the clause a **shared** helper returns, so the vehicle and
the gate cannot address different bytes by construction; and both spellings are tried rather than
one chosen, retiring the bare `next()` that had already raised `StopIteration` once when an arc
exceeded twelve files. **Proven on both arcs**: on the two-file arc the old vehicle leaves the
parser reading 2 where it wanted 3 and the new one gets 3, and on this tree's live 66-file arc the
clause the parser reads is ` 66 files, and this arc now carries CODE` with the digit as the only
spelling tried.

#### Act 5 — the sweeps, at rule 11's repaired scope

**The parks sweep ran at table scope**, which is Act 1's repair applied in the round that wrote it.
`gates/parks_table.py`: 13 rows, **four closed and nine open**, 7 set-claims across 2 rows, no
`CLOSED MEMBER` and no `PHANTOM MEMBER`, 0 failed; three self-members printed as the observation the
gate refuses to fail on.

**And table scope earned itself on a version figure, which is the sweep's most interesting non-find
this round.** Park 5's row asserts `PACKAGE_VERSION` **stays** 1.2.1, inside a forecast the same
cell records as realised — a *closed forecast in an open row*, which is the class rule 11 was
widened to reach. The clause was identified as the sweep's live subject **while the bump was
applied**, at which moment it was false. **The refusal is what makes it true again**, and it is left
exactly as it stands rather than rewritten: it is correct at 1.2.1, and a claim repaired against a
release that did not happen would be the worse defect. **Recorded because the next release will
falsify it**, and a sweep that found a claim, watched it go false and then watched it come back owes
the next round that sentence.

**The disjunction sweep** checked the parks arithmetic at every site that states it: thirteen parks,
four closed and nine open, agreeing everywhere, with the two sites reading *three closed, ten open*
already dated and exempt under sweep rule 6 with the live figure stated beside them.

**The stale-count sweep** re-derived every figure this round's prose introduced rather than carrying
any: the 30 IMAPB payloads and their 30 parsed records, the 14 ST 0601 item worked examples against
`IMAPB_ITEMS`'s own length, the five bump-gate mutation fixtures, and the 42 shipped modules. The
13 adapters and 408 fixture verdicts were derived off `adapter.discover()` and the harness for the
notes that were then unwound; they are stated here only as the reading they were.

**Version figures moved at no site at all, and that is the derived outcome rather than an omission.**
The sweep's subject was every occurrence of the old number, classified: two **live tree-fact** sites
(this file's statement of the two numbers, and park 5's cell) which moved with the bump and moved
back with the unwind; the **dated round readings** — the per-round untouchable records and the pin
file's round nodes — which rule 6 exempts; and the **index claims** in `docs/docs/changelog.mdx` and
`PUBLICATION.md`'s witness-table row, which were deliberately left at 1.2.1 throughout, because
moving them before the artefact is served is the bare-claim class this record spent two rounds
mechanizing against. **The 1.2.1 release held its own deploy for that reason** and this round would
have done the same. All of them are correct at the close, unchanged, and they are unchanged because
the release did not happen rather than because nobody looked.

#### What this round did not do

**No acquisition of any kind** — no fetch, no CDX query, no control re-fetch, and the DNS probe
asked for no bytes. **No tag, no push to any index, no deploy and no rendered page.** **Nothing new
under `packages/` beyond three prose repairs**: no adapter, no model, no fixture, no pin, no schema,
`SCHEMA_VERSION` unmoved at 1.0.0 and `PACKAGE_VERSION` unmoved at 1.2.1. The only new executable
code is one test in `tests/test_cdm_packaging.py` and one helper in `tests/test_cdm_release.py`,
neither of which a wheel carries. **No park was closed and no bump ruling was installed.** The
Unreleased arc is the same **66** files it was at Act 0.

### 1.2.1 — 2026-08-27 — no surface moved, three gates, and a record that refuted itself twice

**A package PATCH, and the first release here to move `PACKAGE_VERSION` for no executable change
at all.** Everything below was written into the Unreleased section as it landed — condition 4 of
"What a release requires", notes derived rather than remembered — and the release absorbed the
section rather than restating it. `PACKAGE_VERSION` moves `1.2.0` → `1.2.1`; `SCHEMA_VERSION`
stays `1.0.0`, and this time that needed no ruling of the kind the 1.2.0 section argues: the diff
over `schemas/` since `v1.2.0` is **empty**, and no model, adapter or fixture changed either.

**WHY PATCH AND NOT MINOR, RULED FROM THE DIFF RATHER THAN FROM THE ROUND'S SIZE.** The arc behind
this release is about 2 800 lines and almost none of it is in the distribution. Every file that
changed under `packages/` is a comment or a shipped document: `pyproject.toml` and `adapter.py`
changed **comment lines only** — filtering both diffs to functional lines yields nothing — and the
rest are `MIGRATIONS.md`, `FORMAT_COVERAGE.md`, the two READMEs and `klv_pin.json`. No importable
name, no `Adapter` contract change, no harness flag or exit code, no fixture set and no dependency
moved, which is `version.py`'s MINOR list in full and none of it occurred; its PATCH row — "a
translation fix, a message, a docstring. No surface change" — is this release read literally. The
work that was large is in `gates/`, `tests/` and `PUBLICATION.md`, none of which a wheel carries.
**A release number states what a consumer receives, not how much a round did**, and the first
draft of this round proposed 1.3.0 on the second reading before the diff was consulted.

**The adapter count disagreed with itself at seven sites, and the guards did not see it.** The
1.2.0 round repaired this count in the package README and in `PUBLICATION.md` and guarded both;
the root `README.md` shipped that same round saying "Thirteen integration adapters are shipped" in
its intro and "the twelve shipped adapters" under Using it. Six more sites were in the same state.
**The finding is not any one of those numbers — it is that last round's guards covered the sites
that had FAILED, not the fact.** `SITES` is a list of places a count once went wrong, and a fact is
not a list of places.

Repaired: `README.md`, `docs/docs/intro.mdx`, `pyproject.toml` twice, this file's release
condition 2 ("all twelve harnesses", and the "thirteenth adapter" it hangs on, both one roster
behind), `adapter.py`'s `fixture_dir` note, and — a roster along — `tests/test_cdm_pins.py`'s
floor, where "pinned standards for six adapters" became seven when `stanag4609` shipped into
`fixtures/klv/spec/`. `tests/test_cdm_ordinals.py`'s "a thirteenth adapter cannot arrive" is now
"a fifteenth", the series having reached fourteen.

**One of those was stale in a way no count guard could see.** `adapter.py` said `fixture_dir` is
left unset by "eleven of the twelve shipped adapters — `stanag4676` … is the only one where the
two differ". `stanag4609` shipped declaring `fixture_dir = "klv"`, which moved the roster twelve to
thirteen AND the divergent set one to two — so "eleven of" stayed arithmetically correct while "is
the only one" went false, in the same sentence. The half that broke was a claim of UNIQUENESS,
which has no number in it. Both halves are derived now, the set as a set.

**The guard is no longer an allowlist.** `tests/test_cdm_prose_counts.py` gains the tree-wide
discovery sweep it has carried as recorded debt since 1.1.0: the roster is derived ONCE, `git
ls-files` is swept, and every collected site is ruled by comparison. A sentence stating the roster
needs no row and cannot go stale silently. Only a NON-roster count needs one, so the exemption list
is bounded by how many of those exist rather than by how many adapter counts exist.

**The harness register gained a fourth entry**, from verifying the published 1.2.0 rather than from
mutating an adapter: a wheel-only consumer cannot run any round-trip proof for an adapter with a
non-JSON egress, because the SKIP text points at `tests/`, which the wheel does not carry. It
affects eleven of the thirteen adapters, it is pre-existing across every version, and it is not a
1.2.0 defect. Renaming that heading "Three things" → "Four things" left two files quoting the old
one, this module's own header among them; that is guarded now too.

**What the published 1.2.0 carries, and what 1.2.1 replaces.** Four of the repaired sentences were
inside the artefacts on the index, and this paragraph was written when the round that repaired
them was not going to be released on its own account. `PUBLICATION.md`'s ledger records which
four, with the digests of the artefacts carrying them. They are prose in comments and in a
packaged document and nothing executable reads them, which is why 1.2.0 was not withdrawn and is
not yanked now. **1.2.1 is the release in which the repaired text reaches a consumer**, and it is
very nearly the whole of what this release changes for anybody who installs it.

**The third mechanized protocol act landed in this arc too, and nothing recorded its arrival:
`gates/commit_message.py`.** It came from a commit that acquired two `Signed-off-by` trailers, one
of them prose in the body — a sign-off that was not one — and it reads a commit message's trailers
rather than trusting that whoever wrote it meant what the hook accepted.
`tests/test_cdm_commit_message.py` holds its parsers and both refusal directions on every suite
run, for the reason the paragraph below gives about the fourth. **This entry is written by the
release round rather than by the round that landed it**, and derived from `git log`: the paragraph
below names the tool while listing the habits already mechanized, so the record said it existed
and never said it was new. The release audit found it by checking the arc against this section in
both directions — every entry to a commit, and every commit to an entry.

**The fourth mechanized protocol act: `gates/deploy_record.py`.** Three habits in this repository
have been turned into things that fail — the pinned count *derivation*, so a number and the command
behind it cannot disagree; `gates/scripted_edit.py`, after a scripted rewrite deleted ~5 000 lines
on a non-unique anchor; and `gates/commit_message.py`, after a commit acquired two `Signed-off-by`
trailers, one of them prose. This is the fourth, and it comes from the same shape: the deployment
round wrote "a deploy gets a row in the commit that follows it" and called it a protocol act rather
than a gate, on the correct ground that the suite cannot reach Cloudflare.

**The habit failed inside the round that wrote it.** That round deployed `5ed34cd8` and recorded it,
and left the paragraph three above its own table saying `57ac1878` "is what the site has served
since" — present tense, undated, false four hours before it was typed. The gate reconciles
Cloudflare's list against ledger entry 8 in both directions, and pins which deployment the custom
domain serves. Two properties are worth naming: the entry's retrospective coverage is now an
explicit **set of ids** rather than a date range, because a range cannot be wrong about an id it
never mentions; and the alias is witnessed **by bytes** rather than read off the API's `aliases`
field, since that field says which deployment is configured to hold the domain and the record claims
the stronger thing a stranger experiences. `tests/test_cdm_deploy_record.py` holds the pure half —
the parsers and both refusal directions — on every suite run, because a gate outside the suite is a
gate whose rosters nothing reads, which is the lesson `tests/test_cdm_gate_rosters.py` was written
for.

**The fifth: every witnessed claim about external state now carries a date or names a gate.** The
same defect twice in two rounds is a class, and the class is a **bare present-tense assertion about
something outside this tree**. `PUBLICATION.md` gains the sweep's full collection, with
the sites it judged already correct shown beside the ones it repaired, because a sweep reported as a
count is a sweep whose misses are invisible — and for the same reason this sentence states no
total: the table is the claim, and a number beside it is one more thing to keep in agreement. It found two claims that were **never** true, which
its own premise did not predict, and they are ledger entry 9. One claim is recorded as **undatable**
rather than given a date: whether the retired PyPI token is revoked is observable by nobody but the
maintainer, and an invented "verified as of" is the failure the whole exercise is against.

**One existing gate got more precise as a side effect, and this paragraph cannot quote it.**
`tests/test_cdm_deploy_workflow.py` sweeps the tree for files that state the deploy mechanism, and
one of its two markers was a plain substring that turned out to be a **prefix of a longer, unrelated
wrangler subcommand** — the one that merely enumerates deployments and describes no mechanism at
all. The new gate runs that subcommand, so it was collected as a site that would then have had to
agree about wrangler forever. The marker now carries a negative lookahead and is asserted in both
directions, against a string it must match and one it must not.

The markers are named in that module and deliberately **not** repeated here: a sweep for a string
collects any file containing it, so a document that spelled the marker in order to discuss it would
become a site by discussing it — which is what the first draft of this paragraph did, and the sweep
caught it on the next run.

**THE BUILD ROUND, 2026-08-28 — the four decayed rows are repaired, a warning is retired by
mechanization, park 5's artefact is written under Ruling 1, and the gate moves the floor by itself.
Two of the brief's own assertions are refuted by the tree and both are recorded as losses.**

**Act 0, and the audit's own figures.** Tree clean, `HEAD` equal to `origin/main` at `26d3305`.
Suite **3271 passed, 3 skipped** at the start. The untouchables hold, each by its own command: the
pinned phrase derives to **35** over the git index, `scripted_edit`'s contract is green at **9**,
`RELEASE_NOTES.md` opens **1.2.1** on the index, and `git ls-files` matches **no** PDF. **The bump
gate was recorded twice on purpose, because this round moves it:** before the codec it derived
**PATCH** with the floor at **1.2.2**, and `--mutation-check` proved both refusal directions and the
unruled case on its five fixtures.

**The `nga.mil` resolution series is extended by one observation.** `NOERROR` for the apex, `gwg`
and `nsgreg` alike at **2026-08-28 21:14Z**, resolution only, no route asked for bytes, from
`192.168.0.1` as every prior reading. Bookkeeping only: **one SERVFAIL episode against twelve
NOERRORs**.

**Pin-as-control, and the decomposition parts from the one it inherited in a way that is a
FINDING.** Every `local_path` paired with a `sha256` across the eight pin files was re-digested:
**21 such pairs resolving to TWENTY distinct copies** — `day_flight.klv` is pinned twice, which is
the whole of the difference — of which **EIGHTEEN are documents under a `spec/` directory** and
**two are the transport-stream artefacts**. All twenty present, all twenty matched, none absent and
none mismatched. **Where this parts company with the last round: that round's decomposition added
"three of them under `spec/history/`", and no pinned copy is under `spec/history/` at all.**
`klv_pin.json`'s `edition_history` node says so in its own first words — *"THE 0601 LINEAGE, NOT
PINS"* — and carries no `local_path`/`sha256` pair anywhere beneath it; the three lineage editions
are held and deliberately unpinned. **The arithmetic also refutes it from the other side**: the
eighteen are twelve under `fixtures/klv/spec/` plus one each for cat023, cat034, cat048 and fft and
two for cat062, which is eighteen with no room for three more. **Class: a sub-clause added to a
correct total.** The total was right, the parts were not, and nothing checked the parts because the
total is what the gate reads.

#### Act 1 — the four decayed rows, each repaired per its form and each checked for existence first

All four exist and all four were located before anything was written. **Park 2's row** now records
that the acquisition half is discharged — ST 0102.12 landed 2026-08-26, `20d40b52…85eca267`,
514 842 bytes, 18 pages — and that what remains is item 48's unwritten row set; the row had gone on
describing step one as pending while being cited elsewhere in the same file as *the precedent* for
the state it was actually in. **Park 3's row** now says what it owns: not `Event.observed_at`, which
is filled on all six packets, but the **name** of a scale of SI seconds since 1970 that is not UTC.
**Park 6's row** keeps its `DETECTION` half and loses *"only parked bytes"*.

**Park 6's repair is the one where the brief's method mattered, and the instruction earned itself.**
The brief said to re-derive the emissions rather than copy last round's examples, and re-deriving
changed the answer. Last round refuted *"only parked bytes"* with `speed_mps=46.0` — one figure.
Running the adapter this round over the pinned stream gives **six** `Entity`/`Event` pairs, twelve
objects, every entity a `PLATFORM` with a **GNSS position**, and `speed_mps` filled on all six at
**46.0, 44.0, 43.0, 43.0, 43.0 and 47.0**. The single figure was packet 0's. **A park priced on
"only parked bytes" is not corrected by one example any more than it is established by none**, and
the repaired cell carries all six.

**Park 11's plan cell — repaired, and the repair is that its artefact was described as filling a
field that is already full.** Verified at its source rather than from the table: `models.py`'s
`CDMBase` declares `source_ids` with **`min_length=1` on every kind**, so an adapter that populated
nothing would not validate, and `adapters/stanag4609.py` line 369 fills it with a **packet-scoped**
key — the Precision Time Stamp and the packet's index — with `attributes.identity_basis` stating on
every object that it claims *this observation* and nothing more. **So the artefact is a REPLACEMENT,
not an addition**, and what the park costs while open is not an empty field but an inexpressive one:
consecutive packets from one aircraft get different `entity_id` values. **The UNRULED branch, stated
as the reason the bump ruling waits:** the change moves `_translate`'s body and adds, removes and
rosters no name — no subclass name, no harness flag, no `_check_*`, no exit code, no fixture set, no
public top-level name, no optional dependency, no console entry point, `SCHEMA_VERSION` unmoved — so
the gate reads it as a modification in place of something whose meaning is the question and
**REFUSES the classification** rather than defaulting it to PATCH. **No hand-ruling is written**, per
Ruling 2.

#### Act 2 — the `local_path` resolver, and the warning is retired by mechanization

**Three reproductions, and a fourth was found while retiring them.** Every pin states its subject as
a `local_path` beginning `fixtures/`, and **two directories answer to that prefix**: specification
documents resolve against the package directory — the one you are reading this inside — and the
stream artefacts resolve against the repository root, because `.gitignore` excludes
`fixtures/klv/streams/` by a directory rule. `gates/pin_paths.py`'s `BASES` states both, and is
where they are read from rather than retyped; **this sentence deliberately spells neither as a
path**, because the package's own layout written the repository's way is a directory an installed
reader has under another name — see the refused-release round's record above. The two are
**disjoint** — neither path exists under the other's base — and they share their first two segments,
`fixtures/klv/`, so nothing a reader sees distinguishes them.

**Why it is a method defect and not a warning: the failure is silent.** A stream's `local_path`
under the package base names a file that does not exist, and every pin check here treats an absent
subject as a `pytest.skip` — correctly, because a fresh clone has the record and not the bytes. **So
a wrong base is indistinguishable from a fresh clone**, and the check goes green while measuring
nothing. That is the absence a round reported and the round after it corrected.

`gates/pin_paths.py` is now the only site that maps a `local_path` to a file. The base is chosen
from the `<kind>` segment — `spec` to the package, `streams` and `provenance` to the root — and an
unknown kind is **REFUSED** rather than defaulted, on `bump_derivation.py`'s UNRULED precedent and
for the same reason: a guess here would be a silent one. `verify_convention()` checks the rule
against the tree on every run, including that the *other* base does **not** hold the file, which is
the half that makes the rule falsifiable rather than restated. The three by-hand sites now call it,
and `tests/test_cdm_pin_paths.py` asserts that they do.

**THE FOURTH SITE WAS `_repo_rel`, and it had the same bug pointed the other way.**
`tests/test_cdm_pins.py` carried `_full = PKG / recorded` under a comment asserting that
package-relative *"is the form every one of those documents uses"*. It is the form every **document**
uses. The module was correct anyway — but by luck: `discover_pins` filters its corpus to `.pdf`, so
no stream path had ever reached it, and **an extension filter was doing load-bearing work while
reading as a preference.** `_repo_rel` joined the same prefix to produce a git-relative path and
would have been wrong for a stream in the same way. Both now defer to the resolver.

**Its first live subject is this round's own pin-as-control**, and it reproduces the hand derivation
exactly: 21 pairs, 20 distinct copies, 18 spec documents and 2 stream artefacts, 20 present and 20
matched. `--mutation-check` proves both directions — a document under the wrong base reads absent, a
stream under the wrong base reads absent — and the refusal.

#### Act 3 — the IMAPB codec, spec first, and the row set is written before the code

**The order was the protocol's and it paid.** All 141 of ST 0601.14a's Table 1 rows were located in
the pinned copy and **fourteen carry a Format column reading `IMAPB`: tags 96, 103, 104, 105, 109,
112, 113, 114, 117, 118, 119, 120, 132 and 134.** That is park 5's enumeration member for member —
**no spec-versus-memo divergence, so the stop rule did not fire.**

**THE FIRST RE-DERIVATION RETURNED THIRTEEN AND WOULD HAVE BEEN REPORTED AS A FINDING.** Tag 105's
Name wraps mid-phrase in Table 1, so a row parser matching line by line sees no Format column on
that row and drops it. Re-run over text joined across pages and whitespace-collapsed first — the
rule `gates/pdf_text.py` states — all 141 rows parse and the count is fourteen. **This is that
module's third reproduction and the first outside a count**: the two it records are tallies, this
one is a structured read of a table, so the rule's reach is wider than the incidents that produced
it. The naive figure was short in the direction that looks like a real finding, which is the whole
danger of the method.

**Every parameter is checked against its own section's worked example, and all fourteen reproduce**
— along with ST 1201.3 §10's two full examples including their intermediate constants. **One
divergence inside the document's own row is recorded as register entry KLV 20**: §8.132's Units cell
says MHz and its example says *2.4 GHz*, and only 2 400 reproduces the octets the same row prints.
A codec calibrated on the example at face value would be wrong by a thousand, and `00 00 59` is a
perfectly well-formed three-octet value — the failure with no shape.

**A SECOND FINDING CAME OUT OF A TEST THIS ROUND WROTE AND THEN HAD TO CORRECT.** A test asserted
that reverse-mapping a Table 2 signal yields a *plausible* number. **It does not**, and the reason
is structural: a special pattern sets the top two bits, so it always reverse-maps above `b`, while
the largest normal value is about half that. The claim was written from park 5's stated risk rather
than measured, and the test failed on its own assertion. **Where the risk actually bites is one step
later**: reverse-mapping a signal raises nothing, and ST 1201.3 requires no range check of a
decoder, so a decoder skipping §7.2.2 step 1 hands its caller 800.0 as a course angle. Recorded as
the correction it is.

**PARK 5 IS NOT CLOSED, AND THE BRIEF'S TAG-112 VERIFICATION IS REFUSED BY THE TREE.** The brief
asked that tag 112's fill of `Kinematics.course_deg` be verified against the six packets. **It
cannot be: tag 112 is absent from all six.** The pinned stream's 26 items were re-enumerated this
round and stop at **tag 65**; the lowest IMAPB item is 96. So `course_deg` is `None` on all six
objects before this codec and `None` after it, exactly as item 5's row already predicted, and the
codec is checked against §8.112's own worked example instead — 125° at two octets is `1F40`. **The
brief loses and the divergence is recorded.** All fourteen rows still read `not yet`, because the
exit condition each states is a witness and this round produced none.

**THE GATE RULED THE BUMP AND NOTHING TOLD IT.** After the codec landed, `gates/bump_derivation.py`
reports *"the arc since 1.2.1 derives **MINOR**, so the next release is at least **1.3.0**"*, where
before it reported PATCH and 1.2.2. Both readings are recorded above. **No release is forced**:
`PACKAGE_VERSION` stays **1.2.1** and `SCHEMA_VERSION` stays **1.0.0** — no field moved, no model
changed, and a consumer reading CDM objects is unaffected. The park 5 / park 11 comparison table's
*"What the bump gate would derive"* cell is the one place a bump was forecast before the change
existed, and it now records the forecast as realised in every clause.

**WHAT THIS ROUND DID NOT DO.** No document was fetched, no CDX query was made, no pin was added, no
acquisition of any kind — the PDF reader was installed outside `.venv` per the standing rule and
read only held bytes. **No park closed and no park moved state**: parks 2, 3, 6 and 11 have repaired
rows and the same standing. **No tag row moved** — all 141 still read `not yet`. **No hand-ruling on
park 11**, per Ruling 2. **Nothing under `packages/` moved outside the granted scope**: the files
added are `adapters/imapb_codec.py` and `fixtures/klv/imapb/`, and the files edited are
`FORMAT_COVERAGE.md` and this one. `gates/`, `tests/` and the resolver are outside the distribution.
**Two of the brief's assertions were refuted and both are recorded as losses rather than absorbed**:
the tag-112 verification, and — from the round before it — the `spec/history/` sub-clause.

**THE PARKS ROUND: no park closed, three register entries narrowed, and the record refuted itself
twice.** Parks 5, 9 and 11 and register entries KLV 14–17 were re-opened after five rounds of record
discipline. **No park closed, and the reason is acquisition rather than judgement.** All three routes
the parks table names refused on 2026-08-27: `gwg.nga.mil` answered nothing, `nsgreg.nga.mil`
answered nothing, and `web.archive.org` answered **HTTP 429 with `X-RL: 0`** — on the CDX API and on
playback alike, **including the byte-exact archived URL the pin records as having served
`ST0601.4.pdf` the day before.** It needs no credentials and no account: it is a quota, so the route
is named as throttled rather than as closed, and the round refused to substitute an unnamed mirror to
close a park — `upload.wikimedia.org` is already the weakest provenance in this record, and a pin
weaker than the park it lifts is not a lift.

**Everything that moved came off documents already on disk.** The six ST 0601 editions in `spec/` and
`spec/history/` had never been read against each other item by item.

**KLV 17: narrowed from twelve revisions to five, and the middle step is not an encoding change.**
The entry was written from the two *endpoints* of the span. The lineage holds two documents inside
it: **ST 0601.4 still states items 11 and 12 as `String 1..127 ISO7`** — unchanged at edition 4 — and
**ST 0601.8 states them as `String 1..127 ISO 646`**, a third spelling, while adding the reference
`ISO7` had denoted for eight editions without citing: **[16] ISO/IEC 646:1991**. So the column moved
twice and only the second move is an encoding change, and the gap shrinks from `.2`–`.13` to
**`.9`–`.13`**. ST 0601.14a carries **no ISO 646 reference at all**, so the edition that adopted
`utf8` dropped the old normative reference rather than superseding it in place.

**KLV 16: the cover date is corroborated from inside edition 1, by a route nobody had tried.** EG
0601.1's §2.3 cites "MISB **RP** 0102.5 … **15 May 2008**", and a document cannot cite a reference
published a year after itself — so **the held bytes cannot be the 15 May 2007 issue**, and the pin's
edition-date field is now positively corroborated rather than merely elected by the provenance
ruling. **What it does not prove is why §3 reads 2007**, and the entry keeps both surviving readings
rather than rounding up: a one-digit typo, or a real 2007 issue re-issued in 2008 without §3 gaining
a row. The typo is the better reading and is not a proof. **Under either, ST 0601.4 restates 2007
and so does not repair that row**, which corrects the entry's "makes the sequence coherent". The
"13 December" row — 2007 against 2006 — is untouched and undecidable from anything held.

**KLV 14: refuted in part, by documents that were on disk when the refuted sentence was written.**
The park-13 closure concluded "the editions state their own deltas perfectly well". They do not. An
edition's item **set** is readable from its own subsection headers with no changelog at all, and six
editions are held: **39, 72, 80, 95, 141, 143** items, contiguous, no gaps. Edition 1's changelog
balances exactly — "Added metadata items 40 through 72", and 39 + 33 = 72. **Editions 2 through 4 do
not:** eight items separate edition 1 from edition 4, and ST 0601.4's §3 accounts for four of them.
**Items 77, 78, 79 and 80 are named in no §3 row** — "operational" and "velocity" occur nowhere in
that section. So the surviving changelog is **incomplete where it exists**, and obtaining an edition
buys its table but not reliably its delta.

**And a truncation, which is the defect the guards could not see.** `FORMAT_COVERAGE.md`'s KLV 16
entry ended mid-clause — "the pin states one date and the document contains" — with no blank line
before `**KLV 17 — `, running two register entries together. **`klv_pin.json` held the complete
sentence**, so the repair is a restoration and is recorded as one. The register-numbering guard
requires each `**KLV n — ` to be *present*, which it was; a truncated sentence carries no count.

**The three parks are narrowed without being lifted, and ranked.** **Park 9 carries ONE blocker** —
acquisition — because the transport-stream input is *declined* rather than deferred to a codec, so
what ST 1402.2 makes writable is prose. **Parks 5 and 11 each carry a second blocker:** their
artefact half is source under `packages/`, which this round had no call for. Park 5's `IMAPB` reach
was re-derived and **the two counts in this file and that one are now reconciled rather than left to
collide**: sixteen §8.x sections name IMAPB and **fourteen** Table 1 rows have `IMAPB` in the Format
column, the difference being tags **128 and 130**, `vlp` packs whose *members* are IMAPB-mapped.
Park 11's ST 1204.1 is now pinned as "Oct 2013" by **two** held editions eight revisions apart. Item
94 has been on the wire since edition 8 and is **absent from the pinned stream**, whose 26 items stop
at 65 — so parks 5 and 11 each block rows and no held octet. `1303`, `1402` and `1301` each occur
**zero** times in ST 0601.14a, so three of the five documents these parks need are delegated by
MISP-2019.1 alone.

**One gate amended, and it is the gate working.** Quoting "MISB RP 0102.5" put a second revision of
the `0102` family in the section where the profile pins ST 0102.12, and
`test_the_delegation_table_states_the_exact_version_the_profile_pins` refused the edit. The gate's
family is the bare number, so it read a revision of the *RP* as a revision of the *ST* — which is
KLV 15's phenomenon one series over, the 0102 series having converted Recommended Practice to
Standard exactly as 0601 converted Engineering Guideline to Standard. Admitted in
`KLV_HELD_NOT_PINNED` as a **fifth kind** — a revision of a different series designation, quoted from
a held document's reference list and used as a **date witness** — with its own admitting phrase, per
that table's one-phrase-per-revision rule. **No new gate was added.**

**Six held claims were re-derived rather than inherited, and all six hold.** The round needed a PDF
text reader it did not have, so it built one and spent its first output reproducing answers this
record already states: the four 0601 page counts **98, 116, 155, 59** under a second independent
page-tree walker; **141** tag rows; the pinned stream's **6 packets, 26 items each, 156 items, 977
octets, 0 left over**; item 22 at `uint16` Len **2** at all six held editions; EG 0601.1 §7.65's
range verbatim; and **98** undated running headers. **A tool whose first job is to reproduce known
answers is a tool whose later answers mean something.**

**What did NOT move, as at that round.** No park closed and no document was fetched, so the
download count stood at **9 of 10** and the park arithmetic was unchanged in every term —
thirteen parks, three closed, ten open. **Dated rather than carried forward**, on sweep rule 6:
this is a past-tense narrative about a specific run and it stays true of that run, but it was
written in the bare present tense and the off-peak round falsified it hours later by closing
park 9. The live arithmetic is four closed and nine open, stated in that round's entry above.
**All 115 tag rows that read `not yet` still read `not yet`**: this round read six editions and
promoted nothing, because every finding is about the standard's history rather than about what an
octet means. **KLV 15 stands untouched**, its evidence re-derived verbatim. No new park and no new
register entry — **ST 1010.3** was checked as a candidate and is already carried in the §4.4.2.5 row.
No adapter, model or fixture changed, `SCHEMA_VERSION` is unmoved, and there was no deploy.
**That last sentence used to read "nothing under `packages/` changed", which was never true and
is corrected here rather than promoted:** the parks round wrote `FORMAT_COVERAGE.md`,
`fixtures/klv/README.md` and `klv_pin.json`, all three of them under `packages/` and all three
shipped, which is exactly why there is a 1.2.1 to put them in. What was meant is that no *code*
moved, and that is what it now says. `PACKAGE_VERSION` was unmoved by the round and is moved by
the release absorbing it.

**THE SWEEP-SURFACE ROUND, 2026-08-29 — park 12's partition is re-derived to current
membership, the parks table joins the per-round sweep list as sweep rule 11 with the derivable half
mechanized, and the new gate's FIRST LIVE RUN found a fourth decay in a row nobody was sweeping
because it is closed. One of the brief's figures is confirmed by derivation, one specced check is
refused by the table, and one of this round's own claims was found to be checking itself.**

**Act 0, and the audit's own figures.** Tree clean, `HEAD` equal to `origin/main` at `36cd947`.
Suite **3377 passed, 3 skipped** at the start. The untouchables hold, each by its own command: the
pinned phrase derives to **35** over the git index, `scripted_edit`'s contract is green at **9**,
`RELEASE_NOTES.md` opens **1.2.1** on the index, and `git ls-files` matches **no** PDF. The bump
gate is green and reads exactly as the brief predicted — declared **1.2.1**, a PATCH over v1.2.0,
the pending arc since 1.2.1 deriving **MINOR** with the floor at **1.3.0** — verified by running it
rather than by copying the figure. **Pin-as-control's second live run through the resolver**: 21
`local_path`+`sha256` pairs stated by **six of the eight** pin files, resolving to **20 distinct
copies**, 18 spec and 2 stream, twelve of them under `fixtures/klv/spec` — all twenty present, all
twenty matched, the decomposition derived by `decompose()` and not narrated. Identical in every
part to the run that mechanized it, which is what a second run is for.

**The `nga.mil` resolution series is extended by one observation.** `NOERROR` for the apex, `gwg`
and `nsgreg` alike at **2026-08-29 08:49Z**, resolution only, no route asked for bytes, from
`192.168.0.1` as every prior reading. Bookkeeping only, and the tally is carried rather than
derived, on the ground the last round stated: **fourteen NOERROR readings against one SERVFAIL
episode**.

#### Act 1 — park 12's partition, re-derived rather than restated

**The blocker was re-verified and not inherited, which the brief required and the tree confirms.**
**MISB ST 0902.8 is not held**: no file under `fixtures/klv/spec/` carries the `0902` series, now
checked by `gates/parks_table.py`'s own existence test rather than by eye. **And the Reason cell's
quotation was re-read from the bytes**, because re-verifying that the bytes still say it is part of
the existence check. Extracting MISP-2019.1's 73 pages and normalising whitespace first — the rule
`gates/pdf_text.py` exists for — the profile reads *"MISMMS is defined in MISB ST 0902 [73], and is
a prerequisite for MISP conformance. Requirement MISP-2015.1-75 Motion Imagery shall contain Motion
Imagery Sensor Minimum Metadata in accordance with MISB ST 0902 [73]"*, and the enclosing heading
derived by walking back from that offset is **§4.4.4 Airborne Collection**. So `MISP-2015.1-75` and
§4.4.4 both hold. **One thing was found that the last round's record states slightly wrong** and it
is left standing as a dated narrative under sweep rule 6: that record quotes the following heading
as *"4.4.4.1 Airborne UAS Collection"* and the bytes read `4.4.4.1 Airborne - UAS Collection`, with
a hyphen. It changes nothing the round concluded. **A second corroboration was found and not looked
for:** Appendix B's reference [73] reads *"MISB ST 0902.8 Motion Imagery Sensor Minimum Metadata
Set, Nov 2018"*, so the row's Version cell is pinned by the governing document and not by the
delegation table alone.

**THE PARTITION IS DERIVED FROM THE TABLE AT READING TIME, AND THE BRIEF'S FIGURE IS CONFIRMED
RATHER THAN COPIED.** Parsing the parks table and cross-referencing every member: the claim names
**seven** parks, of which **five are open — 3, 5, 8, 11 and 12** — and **two are closed, 1 and 4**,
both on **2026-08-26**, park 1 in `642280b` at 12:08 and park 4 in `77210e1` at 14:04. The brief
expected five of seven and it is right; it is recorded as confirmed-by-derivation because a figure
that arrives as a premise and leaves as a conclusion has not been checked. The row now states the
groups as they stand — reading a stream wants parks 5 and 8, translating a conformant one wants
parks 3, 11 and 12 — and **names the class: a set-claim decays silently when its members move.**

**The one derived sentence the brief asked for, and it produced no finding.** Each of the five open
members was checked at its source for a live blocker. Parks 3, 8 and 12 are **unacquired** — no
`0603`, no ST 336 and no `0902` under `spec/`. Parks 5 and 11 **hold every document their version
cells name** and are blocked on the artefact half: park 5 on the sixteen rows that would consume
its codec, park 11 on the source change under `packages/`. **No open member is blocker-free**, so
nothing stopped for adjudication under that rule.

#### Act 2 — the parks table becomes a standing sweep surface, and the gate catches a fourth decay

**Sweep rule 11 is written where the sweep rules live**, numbered per the house convention, with
the three instances cited at their own record sites and verified there: park 5's row denying its
own artefact for a day after `431b0c5`; four of the nine open rows decaying in one pass; park 12's
partition outliving two closures. **The third is a different shape from the first two and it is why
the rule exists** — the first two are claims that went stale about their own row's subject, which
re-reading the row finds, while a set-claim goes stale when a DIFFERENT row changes, so re-reading
its row cannot find it at all.

**The derivable half is a gate, in `decompose()`'s form, because the brief was right that it
fits.** `gates/parks_table.py` derives the table's rows, their open/closed state and their closing
dates, then walks every set-claim: **CLOSED MEMBER** for a named park that has since closed,
**PHANTOM MEMBER** for one the table does not have, with `check_stated()` adding **MISSING** and
**OVERLAP** for a partition somebody writes down. `blocker_existence()` answers, per open row,
whether the MISB series its title names is held on disk. Ten tests in
`tests/test_cdm_parks_table.py`, five mutations in `--mutation-check`, and the module is rostered
REPO-bound in `gates/wheel_install.py` because it judges the repository and does not ship.

**FINDING — A FOURTH DECAY, ON THE GATE'S FIRST LIVE RUN, IN A ROW NOBODY WAS SWEEPING.** Park 1's
Reopen cell listed **park 4** among the parks still owning how an item is found in the octets. Park
1 closed at **12:08** and park 4 at **14:04 the same day** — 116 minutes — and the clause stood for
three days. It is instance 3's shape exactly, and it is the argument for the whole rule: **a sweep
scoped to OPEN rows would never have opened this one**, because park 1 is closed and reads as
finished. Repaired, with the class named in the cell.

**A SECOND FINDING, AND THIS ONE IS THIS ROUND'S OWN SUBJECT TURNED ON ITSELF.** Park 5's row
argued that not one of its sixteen rows had moved by asserting that the codec's `name version`
citation token *appears nowhere in this file* — **and that sentence was the file's only occurrence
of the token.** So the claim was true only because of the sentence making it, and a future round
running the obvious `grep` gets a hit and concludes a row has moved. That is **sweep rule 9's
carrier pattern** — a record that discusses a token becomes a site of it — met for the sixth time
and the first time inside the parks table. Repaired per rule 9's own treatment, describe and do not
quote: the cell now names the citation form without spelling it, says why, and the token's
occurrence count in `FORMAT_COVERAGE.md` is back to **zero**, which re-arms the check.

**ONE SPECCED CHECK WAS MEASURED AGAINST THE TABLE AND REFUSED.** *A set-claim naming its own row
is a defect* — plausible, and false here. Park 12's partition names park 12, and always did: a row
that prices its own park by saying which parks together suffice has its own membership as the
claim's subject. The rule fired **three times on the one row it was written to protect**. Demoted
to an observation the gate prints and does not fail on, and recorded as refused so the next round
starts from what has been ruled out. **Two calibration defects in the gate were caught by its own
mutation check before it was trusted**: a `\b` anchor that never matches inside `ST0102.12.pdf` and
reported every held document as absent, and a series pattern loose enough to read `2017` out of
`ST 336:2017` as a document. Park 8 and park 10 are now reported **NOT DERIVABLE from a filename**
rather than guessed at, which is `pin_paths`'s refusal discipline in a second module.

**WHAT THE GATE DOES NOT CHECK IS PRINTED ON EVERY RUN**, and that is rule 10 applied to this
rule's own gate: a Reason cell's quotation against the pinned bytes, a plan cell against what its
plan needs, and whether a row's argument still follows. Checking that a cell names a test that
exists is nearly free and nearly worthless; the expensive half stays a human's, and the exit code
says so rather than letting a green read as a clean bill.

**A THIRD FINDING, AND THE FRESH-CLONE VERIFICATION IS WHAT FOUND IT — IN THIS ROUND'S OWN
PUSHED GATE.** `blocker_existence()`'s first pushed version printed `ST 0102 NOT held` on a clone,
beside a row whose own cell says *held*, because every pinned PDF is untracked by design and a
clone has the records and not the documents. **An absence there measures the checkout and reads as
a fact about the park** — it would invite the next reader to "repair" a correct row from their own
empty `spec/`. That is `gates/pin_paths.py`'s named failure on a second axis, and it is the mirror
of what the round before this one had to fix in that module: a check whose bytes half must say when
it cannot speak. With no pinned PDF present at all the state is now **`UNVERIFIABLE HERE`**, and
the set-claim half — which needs no bytes and is the half rule 11 turns on — runs everywhere. Two
tests pin both directions. **The verification step earned its place this round rather than
confirming a green.**

#### Act 3 — park 11's row states the question that is actually left

**Checked for existence first, and most of what the brief asked for was already written — in the
other table.** The plan table's bump row and its remaining-blocker cell both carry the shape
question in full, ruled and repaired last round. **The parks-table row did not**: it said the
ruling was DRAFTED and MINOR and named three steps to closure, without saying that MINOR is ruled
for **one shape of the artefact and not the other**. Only the delta is written. The row now states
that MINOR holds where the artefact **appends** the decoded identity beside the packet key; that
the shape which **drops** the packet key is **unruled**, because it removes from shipped output an
identifier a consumer may key on and no MINOR row here covers that; and that the shape decision is
therefore itself a step — **four now, not three**: the shape, the artefact, the ruling moved into
the arc that carries it, then the rows. The draft discharges none of them.

#### Act 4 — the sweeps, and what this round did not do

**The parks sweep ran live as its own first subject**, which is where both findings above came
from. **The disjunction sweep** checked the parks arithmetic across every site that states it:
thirteen parks, **four closed and nine open**, agreeing everywhere, with the one site reading
*three closed, ten open* already dated and exempt under sweep rule 6 with the live figure beside
it. **The stale-count sweep** found two counts this round's own new prose had introduced into
`synapse_cdm/README.md` — the guard caught them, and both were **deleted rather than re-synced**,
on sweep rule 7: a restated count re-drifts and a rephrasing cannot.

**WHAT THIS ROUND DID NOT DO.** No document was fetched and no route was asked for bytes — the DNS
reading is resolution only. No pin was added and no digest changed. **Nothing new was written under
`packages/`**: the only executable code added is `gates/parks_table.py` and its test module,
neither of which ships. No adapter, model or fixture moved, `SCHEMA_VERSION` is unmoved at 1.0.0,
`PACKAGE_VERSION` at 1.2.1, and no release is forced — the floor stays at 1.3.0 where the gate put
it. **No park was closed, and no bump ruling was installed.**

**THE RULING ROUND, 2026-08-29 — park 11's bump ruling is derived and DRAFTED rather than written,
because the gate refuses a ruling that precedes its case; the pin-as-control decomposition is
mechanized; and park 12 decays on a test that does not need its ambiguity resolved. Three of the
brief's assertions are refuted by the tree and all three are recorded as losses.**

**Act 0, and the audit's own figures.** Tree clean, `HEAD` equal to `origin/main` at `9fcfbad`.
Suite **3368 passed, 3 skipped** at the start. The untouchables hold, each by its own command: the
pinned phrase derives to **35** over the git index, `scripted_edit`'s contract is green at **9**,
`RELEASE_NOTES.md` opens **1.2.1** on the index, and `git ls-files` matches **no** PDF. The bump
gate is green and its arc reads as the brief predicted — declared **1.2.1**, a PATCH over v1.2.0,
and the pending arc since 1.2.1 deriving **MINOR** with the floor at **1.3.0** — verified by running
it rather than by copying the figure, and `--mutation-check` passes all five fixtures.

**The `nga.mil` resolution series is extended by one observation.** `NOERROR` for the apex, `gwg`
and `nsgreg` alike at **2026-08-29 07:59Z**, resolution only, no route asked for bytes, from
`192.168.0.1` as every prior reading. Bookkeeping only, and the tally is carried rather than
derived: the prose series is distributed across rounds in words no sweep collects, so **thirteen
NOERROR readings against one SERVFAIL episode** is the previous round's derivation plus this one,
and it is the one figure in this record that no command reproduces.

#### Act 1 — park 11's ruling, derived, and the two things the brief did not know about it

**The stop rule did not fire, and it was checked before anything was written.** The brief conditions
the ruling on the repaired plan cell matching what the decay sweep reported. It does, clause for
clause: `min_length=1` on every kind, the packet-scoped key at line 369, `identity_basis` claiming
this observation and nothing more, the UNRULED branch with the same enumeration of names not moved.
**All three of its source claims were re-verified at their sources rather than from the table** —
`models.py`'s `CDMBase` declares `source_ids: list[SourceId]` with `min_length=1` and says so in its
docstring; `adapters/stanag4609.py:369` is `source_ids = [SourceId(system=OBSERVATION_SYSTEM,
external_id=external_id)]` with `OBSERVATION_SYSTEM = "UAS-LS-PACKET"` at line 120; and `CDMBase` is
the base of `Entity`, `Event`, `Track` and `PlanObject`, so "every kind" is the whole of them.

**FINDING 1 — THE PLAN HAS TWO CELLS ABOUT PARK 11'S BUMP AND THE SWEEP REPAIRED THE OTHER ONE.**
The brief says the ruling is to be written "against the repaired plan". The repaired cell is the
*remaining-blocker* cell. The cell that actually states the bump — the plan table's **"What the bump
gate would derive"** row, park 11's column — was never touched, and it still read *"MINOR at least.
The gate's PATCH row ... does not describe an `Entity` that gains a `source_ids` it did not carry"*.
**That is verbatim the phrase the 2026-08-28 round named as doing two jobs** and identified as the
premise the bump argument rode on. Park 5's column of the same row was rewritten by the codec round;
park 11's was not. **Class: a repair applied to the cell that stated the premise and not to the cell
that used it.** Repaired here, and the ruling below is rebuilt without the phrase.

**FINDING 2 — THE ARTEFACT'S SHAPE IS UNSETTLED, AND THE BUMP KIND DEPENDS ON IT.** Three sites
describe what park 11 would change and they do not agree. The repaired cell says the artefact
**swaps** a synthetic observation key for the identity the format guarantees. The round that
proposed the artefact specified the opposite in as many words: a call site that **appends the
decoded identity beside the packet key rather than replacing it**, because the packet key is what
makes an `Entity` addressable when item 94 is absent — which is every packet of the only stream
held. And the plan's own remaining-blocker row says the adapter *"emits something it did not"*,
which is the appending shape again. **The repair established that the field is never empty; it did
not establish that the packet key goes away**, and the cell took one step past its own evidence.
Both cells are corrected.

**THE RULING, derived from `version.py`'s rows rather than adopted from the brief.** **PATCH is
refused**: its row is "a translation fix, a message, a docstring — no surface change", and all three
examples leave the meaning of the output where it was, whereas nothing this adapter emits today is
wrong and the change makes it assert a cross-packet identity it has never asserted. That is new
emitted content, which 1.2.0 already ruled on in the shape of the structured defect annotation — "a
new kind of output", where the only open question was the schema's. **MAJOR is refused**: every
MAJOR row here is about the importable surface, and the change moves a function body, adds and
removes no name and breaks no third-party adapter; reading "its meaning changes" to cover a
translation's VALUES would make every translation fix a MAJOR, which the PATCH row forbids in the
same breath. **So MINOR, on the MINOR row's own governing clause, "Existing code keeps working"** —
no import breaks, no signature moves, every object still validates at `SCHEMA_VERSION` 1.0.0.

**THE BRIEF LOSES ON THE RULING'S PREMISE, AND THE NARROW READING IS RULED ANYWAY.** The brief
expected *"a replacement of a populated public field's contents is a behavioral change to shipped
output and rules MINOR"*. **That is the one pairing the record cannot support.** MINOR holds for an
artefact that APPENDS; an artefact that DROPS the packet key removes from shipped output an
identifier a consumer may key on, and that is not MINOR and needs its own ruling. The brief takes
the dropping premise and the appending conclusion. The ruling states the shape it rules.

**FINDING 3 — THE RULING CANNOT BE INSTALLED, AND THIS IS PROVEN RATHER THAN ARGUED.** The brief
says to draft it "in the form the gate's hand-ruling slot expects". Written into that slot today it
**fails the gate**. `apply_rulings()` refuses as stale any ruling naming a unit the arc does not
find ambiguous, and park 11's change does not exist, so `Stanag4609Adapter` is not an `Ambiguity` of
the pending arc. A probe inserted the ruling into the section describing the pending arc, ran the
gate, and got *"MIGRATIONS.md's `### …` section carries 1 bump ruling(s) for unit(s) this arc does
not find ambiguous"*; the probe was reverted and the gate re-run green. **The heading is elided from
that quotation on purpose and the elision is the repair, not a style choice** — spelled in full it
is the token two release gates key on, and this paragraph was carrying it. See the refused-release
round's record above. **So the gate refuses a ruling
that PRECEDES its case exactly as it refuses one that OUTLIVES it, and for the same reason** — the
refusal message says a ruling is dated by the entry it sits in, and an entry for a change nobody has
made dates nothing. The ruling is therefore drafted in `FORMAT_COVERAGE.md`, which the gate does not
read, in the exact form the slot parses — the `RULING_MARKER` string, then the unit as ONE backticked
span, then an em dash, then the kind — and it moves into the arc that carries the artefact. **The
scope is narrow by construction and not by choice**: the slot keys a ruling by unit and refuses a
stale one, so no class can be ruled through it.

**What park 11's row now states between ruling and closure.** The artefact, then the ruling moved
into the arc that carries it, then the rows. The ruling alone closes nothing, and drafting it does
not shorten that list.

#### Act 2 — the decomposition, derived by the gate instead of narrated by a round

**The subject is last round's finding: a right total with wrong parts, and nothing checked the
parts.** That round's decomposition added *"three of them under `spec/history/`"* to a correct
eighteen, and no pinned copy is under `spec/history/` at all. **The shape matters and the fixture
now reproduces it exactly: it was a SUB-CLAUSE and not an addend**, so the total went on adding up.
A guard that summed the parts would have passed it.

`gates/pin_paths.py` now derives the decomposition rather than leaving it to prose. `decompose()`
returns pairs per pin file, the pin files that state **no** pair, distinct copies per location and
per kind by the resolver's own classification; `check_parts()` is the arithmetic half; and
`check_stated()` is the guard proper, comparing a decomposition somebody STATED against the derived
one and complaining in three ways — **PHANTOM** for a location the corpus does not have, **MISSING**
for one it has and the statement omits, **COUNT** for a disagreement. The report prints all of it,
so the parts are no longer something a round has to get right by hand.

**This round's own control run is the first live subject, and it settles a latent disjunction.**
**21 `local_path`+`sha256` pairs, stated by SIX of the EIGHT pin files** — `cat021/spec/sac_pin.json`
and `legion/spec/openapi_pin.json` state none — **resolving to TWENTY distinct copies**, `day_flight.klv`
being pinned twice; **eighteen documents and two stream artefacts**; all twenty present, all twenty
matched. The last round wrote "across the eight pin files" and the tool printed six. **Both were
true of different things and neither said which**, so the report now names the silent files instead
of choosing a number. By location: twelve under `fixtures/klv/spec`, two under `fixtures/klv/streams`
after resolution from three pairs, two for cat062 and one each for cat023, cat034, cat048 and fft.

**The non-vacuity witness is the interesting half, and its mutation's domain is checked against its
subject.** The mutation re-attributes three copies from `fixtures/klv/spec` to
`fixtures/klv/spec/history` — the recorded failure, reproduced — and asserts before applying it both
that the phantom location is *not* a location of this corpus and that the donor holds at least three,
because a mutation with an empty domain is a case that passes without running, which is the
`StopIteration` lesson from the round before. The mutated statement **sums to 20, which is the
correct total**, so a sum-only guard passes it and `check_stated()` does not. Nine tests, and
breaking the PHANTOM branch was confirmed to fail two of them.

**And the fresh-clone run caught this module committing its own defect.** The decomposition
mutations were placed inside `_mutation_check()`'s early return for *no pinned bytes in this
working tree* — so on a clone, where `.gitignore` keeps every pinned byte out and the untouchable
`git ls-files` matches no PDF, the whole block was skipped. **The decomposition is a property of the
pin RECORDS and needs no bytes at all**, so gating it on bytes was a check going green while
measuring nothing, which is the exact failure this module exists to retire. The bytes half still
skips and says so; the record half now runs everywhere, verified against a fresh clone.

#### Act 3 — park 12, and the flag decays on a test that does not need the ambiguity resolved

**What was re-derived, not carried.** The blocker is real: **MISB ST 0902.8 is not held** — absent
from `fixtures/klv/spec/`, and `klv_pin.json`'s own filesystem sweep records "no ... 0902" over 1940
PDFs examined. The Reason cell is sound and was checked against the held profile's own bytes rather
than cited: MISP-2019.1 reads *"MISMMS is defined in MISB ST 0902 [73] and is a prerequisite for
MISP conformance"* followed by *"Requirement MISP-2015.1-75: Motion Imagery shall contain Motion
Imagery Sensor Minimum Metadata in accordance with MISB ST 0902 [73]"*, immediately before the
heading "4.4.4.1 Airborne UAS Collection" — so the row's `MISP-2015.1-75` and its §4.4.4 both hold,
and ref [73] matches the pin record. Park 12 has no plan cell, so there is none to match.

**THE FLAG DECAYS, AND THE FINDING IS THAT ITS AMBIGUITY WAS NEVER THE ONLY DEFECT.** The row prices
park 12 on a partition: *"parks 4, 5 and 8 are enough to READ a stream at all, and parks 1, 3, 11
and 12 are enough to TRANSLATE a conformant one"*. Two rounds ago that was flagged and deliberately
not called decay, because the sentence is ambiguous between a sufficiency claim the tree does not
reach and a necessity claim it refutes. **Re-derived now, a test applies that does not need the
reading resolved: the partition names SEVEN parks as prerequisites and TWO OF THEM ARE CLOSED** —
park 1 and park 4, both closed 2026-08-26. A statement of what is still needed that lists two
things no longer needed is stale on its face, whichever way its verb is read. The necessity reading
is refuted more strongly than when it was flagged, too: the pinned stream is read and translated
today with parks 3, 5, 8, 11 and 12 all open, and the codec round added an `IMAPB` codec without
closing any of them. **Class: a prerequisite partition that outlived the closure of two of its own
members** — the flag's own class, "written before adapter #10 shipped and not re-derived since",
sharpened by naming what specifically decayed. **The row is NOT repaired here.** Park 12 findings
stop for adjudication under the brief's own stop rule, and this one stops.

#### Act 4 — the sweeps, and a second disjunction the codec round left behind

**The disjunction sweep found park 5's row denying its own artefact.** `adapters/imapb_codec.py`
landed in `431b0c5` on 2026-08-28 — 309 lines — and the parks table's park 5 row went on saying the
artefact was *"blocked on a per-change ruling"* and citing park 2 for *"document held, artefact
unwritten"*, while the plan table's park 5 column had already recorded the landing. **Two sites, one
fact, a day apart.** Repaired, and the repair is not "park 5 is closed": it is not. Its artefact is
a codec **plus the tag rows that consume it**, and **`imapb 1.0.0` appears nowhere in
`FORMAT_COVERAGE.md`** — not one of the sixteen rows has moved, because none of the sixteen is
witnessed and the scope contract blocks them independently of this park. That is a state park 2 is
not the precedent for, and the row now says so.

**The retired phrase was swept for and found at one more live site.** *"Populating
`Entity.source_ids`"* survived in park 11's parks-table row a day after the plan cell was repaired
of it; corrected there to "decoding item 94 into", with the reason stated once. The occurrence in
the round record of 2026-08-27 is left standing: a dated round narrative is a historical artefact
and the correction belongs beside the claim, not on top of it.

**WHAT THIS ROUND DID NOT DO.** No document was fetched and no route was asked for bytes — the DNS
reading is resolution only. No pin was added, no digest changed, and nothing new was written under
`packages/`: the only executable code this round adds is in `gates/` and `tests/`, which do not
ship. No adapter, model or fixture moved, `SCHEMA_VERSION` is unmoved at 1.0.0, `PACKAGE_VERSION` at
1.2.1, and no release is forced — the floor stays where the gate put it. **No park was closed, and
no bump ruling was installed.**

### 1.2.0 — adapter #10, a codec ruling, and a schema version that did not move

**A package MINOR, and the release where the two-number arrangement was tested rather than
relied on.** Everything below was written into the Unreleased section as it landed — condition 4 of
"What a release requires", notes derived rather than remembered — and the release absorbed the
section rather than restating it. `PACKAGE_VERSION` moves `1.1.0` → `1.2.0`; `SCHEMA_VERSION`
stays `1.0.0`, and the paragraph beginning **THE SCHEMA QUESTION** below is why, with the file
and line of each piece of evidence.

- **Adapter #10 SHIPPED — `stanag4609`, STANAG 4609 / MISP-2019.1, the UAS Datalink Local Set,
  bidirectional and byte-exact — against 26 of its row set's 141 rows.** The witnessed-set round of
  2026-08-26, and the seventh round on this format. **No field added, removed or retyped, and no
  schema touched**, which is the entry: `SCHEMA_VERSION` stays `1.0.0` and this is a package
  **MINOR** when released.

  **What "26 of 141" means, because a partial promotion is new in this repository.** The pinned
  stream `fixtures/klv/streams/day_flight.klv` — SHA-256 `a810e4b6…e51`, 977 octets, re-verified —
  carries six packets of 26 items each, the same 26 tags in the same order every time: 1, 2, 5, 6,
  7, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 40, 41, 42, 56, 57 and 65. Those
  26 rows moved. **The other 115 still read `not yet`**, and the blocker on almost all of them is
  neither a park nor a schedule but a rule: *an item nobody here has met on a wire is an item whose
  decoder could only ever be checked against a fixture written from the same reading of the same
  table.* `klv_uas_codec.WITNESSED_TAGS` is that scope contract as data, and
  `test_the_st_0601_tag_table_agrees_between_the_pin_record_and_the_document` now asserts the
  partition tag by tag in both directions — a row promoted without a decoder fails, and a decoder
  without its row promoted fails too.

  **Two codecs, not one, and the split is the property being protected.** `adapters/klv_codec.py`
  stays the framing layer and stays **tag-blind** — that is how `ST 0107.3-04`'s "skip unknown Local
  Set values" is satisfied structurally rather than by a skip list — and
  `adapters/klv_uas_codec.py` is new and holds the tag table. A test asserts the framing layer does
  not import the tag table, because a table imported there would destroy the claim silently: the
  walk would still work.

  **Every number in the item table is the document's, and the check is the document's too.** Each
  §8.x block in ST 0601.14a states eleven facts in three drawn tables and prints one Software Value
  beside the KLV octets that encode it, and §7's Programmer's Notes say why: "the 'Example Value'
  for a tag is shown in full precision, beyond a tag's resolution, so programmers can verify they
  are using the right formulas." So `check_against_the_documents_own_examples()` runs all 26 on
  every suite run — **26 of 26 agree** — and `check_against_edition_1s_examples()` runs the 23 that
  **MISB EG 0601.1** independently prints, which all decode under the same maps. That is what makes
  the anchor external: a transcription checked against a fixture written from the same reading proves
  only that the reading is self-consistent.

  **A codec ruling: the length-divergence policy.** Park 13 ruled item 22's four octets a stream
  defect and said explicitly that the flag was "owed by the value-decoding layer, which does not
  exist". It exists now, so the rule is written: **the ITEM is skipped and a structured defect
  annotation is recorded** — never the packet rejected (candidate a), never the octets reinterpreted
  (candidate c). Rejecting the packet would discard 25 conformant items whose checksum validates and
  would contradict `ST 0107.3-04`; reinterpreting them requires choosing between three truncation
  rules no held document states, which agree on this stream and disagree the moment a top octet is
  non-zero. **The class has four branches and the document draws three of them**: `ST 0601.13-29`'s
  `shall` for a Required Length, §7's word "**recommended**" for a Max Length (so an over-long
  variable item is decoded and carries an advisory), and `ST 0601.14-33`'s "consumers shall interpret
  the value of the item as 'unknown'" for a length of zero — except on the three items
  `ST 0601.14-32` forbids a Zero-Length Item for, where a zero IS a defect. `ST 0601.14-34`'s
  ordering rule is read and deliberately **not enforced**: it constrains a producer across packets,
  and checking it would carry state across a packet boundary.

  **Park 5 is NARROWED and not lifted, by enumeration.** `MISP-2015.1-09` says every scaled value is
  mapped by ST 1201.3 and that is the profile's claim; **not one of the 26 witnessed items' §8.x
  sections names IMAPB**, because each states its own affine map twice over. The 16 that do are tags
  96, 103, 104, 105, 109, 112, 113, 114, 117, 118, 119, 120, 128, 130, 132 and 134. Recording that a
  blocker shrank is not recording that it lifted. **Park 11 changed standing without anything being
  fetched**: it has said since Phase 1 that it "blocks keying an `Entity` on anything the stream
  states", which was a forecast and is now a measurement — the stream carries none of the five items
  that could identify an airframe, and item 11, the only witnessed item that looks like a name, reads
  `'EON'` in five packets and `'IR'` in the sixth. So the `entity_id` is **packet-scoped** on the
  CAT048 settlement-9 precedent, and the cost is **gap 30**.

  **The register gains one entry — KLV 17**, the `ISO7`-against-`utf8` divergence on items 11 and 12,
  which is the only column of the only two of the 26 items where edition 1 and the pinned edition
  differ at all. It costs nothing on any octet either edition admits.

  **Ten synthetic payload fixtures and their ten parsed twins**, in `fixtures/klv/` where the harness
  finds them, built only by `fixtures/klv/spec/build_fixtures.py`, plus goldens. **Not one contains a
  run from the pinned stream**: the value-carrying fixture uses each item's own §8.x Example KLV
  Value, and the defect fixture reproduces the *class* — four octets under a Required Length of 2 —
  with a value the stream does not carry. Two of them earned their place by failing on the first run:
  `special_values_are_signals_and_not_measurements` caught the sentinel being compared against the
  *signed* reading of its own octets, which made `0x80000000` decode to a latitude of
  −90.00000004190952; and `a_checksum_that_does_not_validate_is_flagged_not_refused` caught egress
  **recomputing** the checksum instead of replaying it, which silently repaired a packet it had been
  asked to carry.

  **The clock seam is built.** `FORMAT_COVERAGE.md` called it "NAMED AND NOT BUILT" for two rounds
  because "closing park 4 did not create an adapter to hang a seam on". `received_at` comes from the
  injected clock and `observed_at` from item 2, whose epoch §8.2.1 states on its own account — so
  that field was never blocked on park 3. What park 3 still owns is the **name** of a timescale
  §8.2.1 says "does not represent UTC", and `attributes.time_basis` carries the caveat on every
  object rather than resolving it.

  **Why this is NOT yet in "Adapters that landed with no schema change", and it is a precedent
  rather than an oversight.** That section's heading says *landed*, every one of its eleven entries
  shipped in a release, and the nine sites that state its count all say eleven — including
  `RELEASE_NOTES.md`'s "eleven of the twelve", which is 1.1.0's own sentence and true of 1.1.0.
  `stanag4609` has landed on `main` and in no release, so it joins that section and moves that count
  **in the commit that releases it**, which is the first time this file has had to distinguish the
  two. Recorded here because "no entry" and "nobody wrote an entry" look identical from the section
  itself, which is the reason the section exists.

  **What did NOT move.** No park closed. Parks 8 and 9 are untouched and were unreachable — a value
  decoder fetches no transport standard and none of the held documents is SMPTE ST 336 — so the
  download count stays at **9 of 10**. No specification was fetched and none pinned; both
  transcriptions were read from copies already held. KLV 14, 15 and 16 stay open as scoped. And
  `klv_uas_codec` reads **no nested set at all** — items 48, 73, 74, 100 and 101 carry Local Sets
  inside their Values, none is witnessed, and "the codec handles 26 items" and "the codec handles one
  level of structure" are different claims of which only the first is true.


  **THE SCHEMA QUESTION, ASKED BECAUSE THE ANSWER WAS NOT OBVIOUS, AND ANSWERED FROM BYTES.** The
  length-divergence annotation is **new output surface**: objects from adapter #10 carry keys no
  object in 1.1.0 carried. "New output surface" is the shape that ought to move `SCHEMA_VERSION`,
  so the question was put before the version moved, and the answer is **no — `SCHEMA_VERSION`
  stays `1.0.0`** — on four pieces of evidence rather than on judgement:

  | Evidence | Where | What it shows |
  |---|---|---|
  | `"additionalProperties": false` | `schemas/entity.schema.json:29`, `schemas/event.schema.json:17` | The OBJECTS are closed. A new top-level field would have to be declared, and would be a schema change |
  | `"additionalProperties": true` | `schemas/entity.schema.json:248`, `schemas/event.schema.json:267` | The two never-drop bags — `attributes` and `payload` — are open by declaration. A key inside one is already valid against the published schema |
  | `attributes.length_divergence_policy`, `payload.klv_defects`, `payload.klv_advisories` | `fixtures/klv/golden/length_divergence_at_a_required_length.cdm.json:86, 220, 219` | Every part of the annotation is INSIDE those bags. Neither object gained a top-level key: the entity's fifteen and the event's thirteen are exactly the schemas' |
  | `git diff c5cf212..8e020eb -- schemas/` is **empty**, and all six schemas regenerate byte-identical from the models | `tests/test_cdm_schemas.py`, and the wheel gate's `schemas` check | The adapter that produced the annotation changed no schema file at all |

  **And the general form, which is why this is a ruling and not a one-off.** 361 distinct
  adapter-private keys already live inside `attributes` and `payload` across the thirteen adapters'
  golden files — 65 from `cat048`, 58 from `gmti`, 36 from this one. **If a new key in a never-drop
  bag moved `SCHEMA_VERSION`, every adapter this repository has ever shipped would have moved it**,
  and the bag would not be a bag. `attributes` is documented as "the never-drop bag: park data here
  rather than discarding it"; parking is what it is for.

  **Measured against "What each bump means" at the top of this file rather than against intuition.**
  A schema MINOR is "an optional field added; an enum member added; a payload model registered;
  validation relaxed". The annotation is none of the four: no field was added to any model, no enum
  member exists that did not, `PAYLOAD_MODELS` gained no registration, and nothing was relaxed —
  the bags were already open. **The consumer migration story is therefore empty, and that is the
  claim being made**: a 1.0.0 reader validates a 1.2.0 object from adapter #10 unchanged, because
  the bytes it does not recognise are in the place the contract has always said it may ignore.
  Nothing to migrate is a stronger statement than a migration nobody needs, and it is recorded here
  so the question is not re-opened at the next release that adds an annotation.

  **Package MINOR** — an added adapter and two added modules, nothing removed, no schema touched.

- **Two corrections to this file's own prose, made true by an act that happened after 1.1.0
  shipped.** `PUBLICATION.md` ledger entry 6 closed on 2026-08-26 when the 1.0.0 API token was
  revoked, and closing it falsified two sentences here. "What the workflow does" said the upload
  would be refused *until* a trusted publisher was registered on pypi.org — it is registered, and
  1.1.0 went through it. "The manual fallback" said the credential that path needs was *meant to
  be* gone; it is gone. Both now read in the past tense, and the fallback section says plainly that
  taking it would require issuing a new token first.

  Recorded rather than folded in silently because this file ships inside the wheel: a reader who
  installs 1.1.0 gets the earlier wording, which was accurate on the day that artefact was built.

  **Package PATCH when released** — shipped documentation corrected, no code, no schema touched.

### 1.1.0 — two adapters, a discoverable roster, and the first release nobody uploaded

**A package MINOR, and the release where the two version numbers part company for the first
time.** Every entry below says the same two things — an added surface, nothing removed, no schema
touched — so `PACKAGE_VERSION` is `1.1.0` and `SCHEMA_VERSION` stays `1.0.0`. `version.py` has
argued since before publication that the two are independent numbers rather than one number
written twice; until this release that argument rested on a counterfactual, because the two were
equal and a reader could reasonably think one redundant. It no longer does.

**This is also the first release this repository did not upload.** `.github/workflows/publish.yml`
built the artefacts, ran the gates against what it built, and published over OIDC with no
credential in the process. `PUBLICATION.md` ledger entries 5 and 6 carry the two halves of that
story — what a release by hand looked like, and what had to be true for one to stop being.

Everything below was written while it landed, entry by entry, on the argument that condition 4 of
"What a release requires" — notes derived rather than remembered — is not satisfiable in arrears.
The v1.1.0 release notes are read off this section.

- **`harness --list-adapters`** — prints the registered adapters (name, version, direction,
  fixture directory, system) and exits `0`, with `--json` honoured. The roster used to be
  reachable only through a failure: inside `load_adapter`'s `LookupError`, or not at all, since
  a bare invocation gets argparse's usage line naming `--adapter` and not one value it takes.
  `--adapter` is no longer `required=True` — the requirement is re-imposed with `parser.error`,
  so a bare invocation still exits `2` with the same usage line and one added sentence.
  `adapter.roster()` is now the single source both the listing and the refusal read.
  **Package MINOR when released** — an added CLI surface, nothing removed, no schema touched.

- **ASTERIX Category 062 and Category 023 — the specification pass, `cat062` and `cat023` at
  Phase 1.** Two row sets in `FORMAT_COVERAGE.md`, written and reviewed as specifications with
  `not yet` in every status cell and no code behind them, plus two pin records and three pinned
  documents: Part 9 Edition 1.21, its Appendix A (Reserved Expansion Field) Edition 1.3, and
  Part 16 Edition 1.3. **No adapter ships in this entry** — the ordinals #13 and #14 are recorded
  as Phase 1 and the roster is unchanged at ten.

  Two rulings the pass had to make explicitly, both in the row sets and both carried in the pin
  records:

  - **CAT062 carries FUSED content**, being the output of a multi-sensor tracker, and the adapter
    will TRANSLATE that output and fuse nothing of its own. The items describing the fusion — the
    per-technology update ages, the per-DAP ages, the amalgamation and coasting flags, the
    contributing-sensor lists in the REF, the estimated accuracies, the measured-versus-calculated
    split — are the upstream system's statements and park or map as such. Settlement 1 of the
    CAT062 section states the six things the adapter therefore does not do.
  - **`entity_id` basis.** The Mode S address in `I062/380` SF#1 is the identity basis where a
    record states one, filed under `ICAO24` as three adapters already do; the system track number
    in `I062/040` is **never** the basis and parks, because sixteen bits allocated by the emitting
    system and recycled would merge two airframes into one entity. Where no address is stated the
    id is record-scoped and says so. `asterix_cat048.py`'s sibling-category enumeration is
    **not** copied forward — it omits `cat034` and would go stale again on the next category — and
    the CAT062/CAT023 modules will state the property instead of a list.

  **Package MINOR when released** — two documented row sets, no schema touched, no adapter added.

- **Three gate repairs found by writing the two row sets**, each recorded because each was a gate
  that would have gone on reporting clean:
  - `tests/test_cdm_format_coverage.py`'s egress-table collector knew seven format names and now
    knows nine. Both new egress tables are written at Phase 1, so their CDM paths would have been
    resolved against the models **never** — the state five of the first seven tables were in until
    the header ruling.
  - `tests/test_cdm_format_coverage.py`'s Branch R sweep excluded no virtualenv at all and had
    been failing on a clean tree since the consumer-path round installed this package into `.venv`
    inside the clone: it found four extra "sites" that were site-packages copies of the four it
    already reads. `tests/test_cdm_prose_counts.py`'s check-count sweep excluded the literal name
    `.venv` and so was clean here and red for anyone whose environment is called anything else.
    Both now import `is_virtualenv` from `tests/test_cdm_version_floor.py`, which identifies an
    environment by PEP 405's `pyvenv.cfg` rather than by its name — the fourth and last sweep to
    adopt the property.
  - `tests/test_cdm_pins.py`'s pin floor moved 11 → 14 and its home floor 6 → 8, and its
    page-count-method roster gained the two new records. The round is the first to add three pins
    and two homes at once and the first to pin an **appendix** alongside the specification it
    belongs to; the two new records are also the first whose measurements make the page-count
    ruling look obvious rather than merely correct — the retired raw-object scan reports 423 pages
    for a 146-page document and 60 for a 31-page one, where the largest disagreement on record was
    41 against 43.

- **`cat062` — ASTERIX Category 062 SDPS Track Messages, bidirectional.** Adapter #13, shipped
  against the row set the specification pass wrote. `adapters/asterix_cat062.py` on a codec in
  `adapters/cat062_codec.py`; 27 data items, six compound items, a six-extent FX chain, and the
  Reserved Expansion Field decoded in full. **Every row of the CAT062 row set now reads
  `cat062 1.0.0`**, the roster is eleven, and `Position.accuracy_m` is set from a source for the
  first time in this repository.

  **The byte-for-byte round trip holds on all 28 fixtures.** Phase 1 promised to rule and record if
  an item defeated it and named two candidates in advance; neither did, because both derived values
  are one-way views re-emitted from parked raw fields. Verified independently of the harness, which
  skips `roundtrip` for a binary format — that skip is a pointer at `tests/`, not a waiver.

  **One row changed and it is on the record.** The row set predicted a declared `TRANSFORMS` entry
  for the `I062/500` Subfield #3 combination, reasoning that two angular components becoming one
  metric scalar leaves the degrees unrepresented. Both halves are true and the conclusion does not
  follow: the never-drop check compares source LEAF values, the leaves are the two raw integers, and
  those are parked. Measured rather than argued — the check was re-run over all 28 fixtures with
  `TRANSFORMS` emptied and reported zero losses either way. `cat062` declares none, like its three
  ASTERIX siblings.

  **Package MINOR when released** — an added adapter, nothing removed, no schema touched.

- **Two gates were stating a count nothing computed, and now derive it.**
  `tests/test_cdm_harness.py`'s `test_the_packaged_fixtures_resolve_through_import_resources_not_a_
  repo_path` asserted the bare literal `10`; it now reads the length off `SHIPPED_FIXTURE_DIRS`,
  which the same module already asserts equal to the registry. That is
  `tests/test_cdm_prose_counts.py`'s defect one layer in — a count in a place nothing computes it —
  and the ICAO24 sharer count went from four to five in the same round, which is the second time
  that sentence has gone stale by an adapter landing.

- **`cat023` — ASTERIX Category 023 CNS/ATM Ground Station and Service Status Reports,
  bidirectional.** Adapter #14, shipped against the row set the specification pass wrote, **with no
  row changed**. `adapters/asterix_cat023.py` on a codec in `adapters/cat023_codec.py`; nine data
  items, a three-column Table 2 presence matrix, and three items whose `FX` names an extension the
  document never defines. Every row of the CAT023 row set now reads `cat023 1.0.0` and **the roster
  is twelve**.

  **The first adapter here that emits TWO Entities from one record.** Report types 002 and 003 are
  about a SERVICE rather than about the station, and §4.5.1.2 requires the two to be independent, so
  a service is a second `Entity` keyed on the pair `(SAC/SIC, Service Identification)` — never the
  SID alone, which §5.2.3's NOTE 1 says is "allocated by the system". Both ids ride on one `Event`
  in `related_entities`, station first, which is not a join: both are pure functions of fields in
  the same record. `from_cdm()` re-assembles from the STATION object and refuses a call that passes
  only the service one.

  **The byte-for-byte round trip holds on all 17 fixtures**, and this category is the easiest case
  in the family: not one scaled value becomes a canonical numeric field, so there is no arithmetic
  to invert anywhere. Verified independently of the harness, which skips `roundtrip` for a binary
  format.

  **`Entity.position` is `None` on every object and `Event.geometry` is `None` permanently.** Nine
  items and not one coordinate: `I023/200` is an operational range with no centre, and §4.4.1
  asserts a SAC/SIC is unambiguous per station without saying where any station is. Reading a
  position out of a CAT034 record to locate a CAT023 station is cross-payload state — the refusal
  `asterix_cat034.py`'s settlement 2 already made in the other direction.

  **Package MINOR when released** — an added adapter, nothing removed, no schema touched.

- **`tests/test_cdm_version_floor.py` caught a real 3.11 incompatibility in new code**, which is
  the first time that gate has fired on something written after it existed rather than on something
  it was written to find. An f-string in `asterix_cat023.py`'s refusal message had a replacement
  field reusing the string's own quote and containing a backslash — legal from 3.12 under PEP 701
  and a `SyntaxError` at the declared `requires-python = ">=3.11"` floor. The expression is hoisted
  to a local above the f-string, as the gate's own message suggests.

- **The roster, the gates and the disjunction sweep, after adapters #13 and #14.** No behaviour
  changed; what changed is every site that stated a fact the two adapters moved.

  **`--list-adapters` shows both, and its mutation check is now parameterised over the whole
  roster.** It named `pntmap` alone, which proves the listing is derived FOR THAT ONE and does not
  prove a new adapter is reachable by it — a hand-written roster containing eleven of twelve names
  passes a one-victim mutation eleven times out of twelve. The parameter list is read from
  `adapter.roster()`, so an adapter that lands without being listed fails there.

  **The published roadmap emptied, because both of its members landed.** `README.md`,
  `docs/docs/intro.mdx` and `synapse_cdm/__init__.py` no longer promise "the other ASTERIX
  categories (062 system tracks, 023 service status)", and `tests/test_cdm_landing_next.py` was
  INVERTED rather than deleted: the three clause patterns are kept verbatim and must now match ZERO
  times, so a promise coming back without a roster behind it fails a build. A second half was added
  in the other direction — a category with a shipped adapter may not still read as "deferred, not
  rejected" in a declines table, which is the same staleness pointing backwards. The three declines
  tables that deferred 023 and 062 now record them as landed.

  **The stale-count sweep found six live counts, one disjunction and one thing it was not looking
  for.** Six sites said ten or nine adapters and now say twelve: `README.md`, `docs/docs/intro.mdx`,
  `docs/docs/changelog.mdx`, `gates/wheel_install.py`, `pyproject.toml` twice, and `adapter.py`'s
  "nine of the ten shipped adapters" (now eleven of twelve). The disjunction was three PIN RECORDS
  stating ONE PRACTICE as three different numbers — "the other eleven adapter efforts", "the other
  nine", "all ten" — every one of them stale and no two agreeing; all three now state the practice
  and no count, because the practice is universal and derivable and the count was neither.

  **Two sites were left alone deliberately and say why.** `PUBLICATION.md`'s "Ten adapters, 298
  fixture verdicts" measures the PUBLISHED 1.0.0 from the index, so it names its subset rather than
  moving — updating it would falsify the record. `synapse_cdm/README.md`'s and `harness.py`'s
  "nine adapters" are descriptions of things that happened.

  **And a gap tally moved.** `FORMAT_COVERAGE.md`'s gap 1 counts the private keys adapters invent
  because the CDM has no canonical name: seven adapters and eight keys became **eight and eleven**,
  because `cat062` alone carries THREE name-shaped strings that the specification itself says are
  alternatives and that no adapter may arbitrate between. Gap 7's detection-geometry table was
  checked and neither new adapter joins it; the check is recorded, because a target-report category
  absent from that table should be a finding rather than a hole in the sweep.

- **A defect this round introduced and repaired.** A scripted edit for the count sweep corrupted one
  sentence in `version.py` — "one of them is redundant" became "one ofeleven adapters is redundant"
  — and it was committed. It was found by the sweep that follows the edits rather than by the edits,
  which is the argument for running the sweep as a separate act: a script that rewrites prose in
  eight files is exactly the thing whose own output nobody re-reads. The sentence is restored, the
  whole round's diff was re-scanned for the same signature, and no other site was affected.

- **`tests/test_cdm_asterix_cat062_adapter.py` and `tests/test_cdm_asterix_cat023_adapter.py`.**
  183 and 124 tests. Each ships **the round trip the harness skips** — `_check_roundtrip` reports
  SKIP for an adapter whose `from_cdm` returns non-JSON bytes and says in as many words that the
  adapter must ship its own, and both of these assert BYTE EQUALITY on every fixture rather than
  the harness's value-presence comparison.

  **Every assertion is scoped to a NAMED table, settlement or fixture.** The CAT062 section is over
  a thousand lines and `Entity.attributes` appears in fourteen of its seventeen mapping tables, so a
  section-wide substring check would pass by luck.

  **Eleven mutations, zero survivors, and each caught by the test that names the property.** The
  ones worth listing because they would otherwise pass every check in the harness: `atan2(Vx, Vy)`
  → `atan2(Vy, Vx)` (a course reflected about 45°, plausible everywhere); `alt_m` sourced from
  `I062/135` instead of `I062/130` (a pressure altitude in a field documented as an ellipsoidal
  height); the record-scoped `entity_id` key reduced to `(SAC/SIC, track number)` (two updates
  becoming one entity, which is settlement 3's whole subject); `I062/290` Subfield #5 read as one
  octet instead of two; the FSPEC ceiling lowered to Part 4's four; `I062/110`'s coordinate quantum
  swapped for `I062/105`'s; the CAT023 service keyed on its four-bit SID alone; `RP = 0` reaching a
  consumer as `0.0` seconds; a service status severity softened; `GSSP`'s low bound moved to zero;
  and a spare bit dropped by a decoder.

- **The mutation harness reproduced this repository's own documented stale-bytecode failure, on its
  first run, and it is worth recording because the prediction was exact.**
  `tests/test_cdm_generator_loading.py`'s docstring says a `.pyc` is revalidated on the source's
  mtime **in whole seconds** and its size, that an edit reverted inside one second therefore leaves
  a cache validating against a file it was not compiled from, and that "a mutation harness only
  makes it routine". It did: eleven mutations applied and reverted in under a second each left nine
  tests failing against a **restored** tree, and the failures pointed at the wrong properties
  entirely. That module's own fix compiles the fixture generators in memory, which is why the
  generators were unaffected; the ADAPTER modules are imported normally and are not covered by it,
  and should not be — `import` caching is correct behaviour. What was wrong was a harness that
  edits source and re-runs without clearing `__pycache__`. Recorded rather than dropped because the
  first mutation run's output was wrong in the direction that looks like a finding: seven "MISSED"
  verdicts, every one of them false.

- **The release procedure in this file changed, and this file ships.** Everything else in this
  entry is code or fixtures; this one is prose a consumer receives, which is why it is recorded
  rather than treated as repository housekeeping. "Releasing the package" no longer describes a
  sequence a person runs: conditions 1, 2 and 3 gained an actor column naming the workflow,
  condition 4 kept a person and says why a workflow cannot take it, and the manual `twine` path is
  now written down under "The manual fallback — NOT the procedure" with what it costs. A reader who
  installs 1.1.0 and opens the packaged `MIGRATIONS.md` gets that text; a reader of 1.0.0's gets
  the earlier version, which denied that any automation existed and was right when it shipped. The
  denial is not quoted here — the gate over this prose forbids the old wording as a substring and
  cannot tell an assertion from a quotation of one, which is the correct way round.

  Two gates moved with it, in the direction that keeps prose checkable rather than the direction
  that stops checking. `tests/test_cdm_release.py`'s mechanism test was **inverted** — it asserted
  the ABSENCE of `.github/workflows` and carried its own instruction for the day that stopped being
  true, so it now requires the workflow the prose names to exist and forbids the retired claim.
  And the two documented procedures are collected: a `twine upload` in any document must be marked
  a fallback, and any document describing publishing must name `publish.yml`.

  **Package MINOR when released** — shipped documentation changed, no code, no schema touched.

### 1.0.0 — initial contract

The four objects (`Entity`, `Event`, `Track`, `PlanObject`), `Position`, `Kinematics`,
`SourceId`, `SourceRef`, `Integrity`, `TrackSample`, and one registered payload model
(`GnssInterferencePayload` for `GNSS_INTERFERENCE`).

Two decisions in this release depart from the original specification, both because building
the reference adapter surfaced the reason:

- **`source_ids` moved from `Entity` to `CDMBase`**, required on every kind. The harness's
  lossless check found the gap on its first run: a PNTMAP alert whose emitter carries its own
  id produced an entity keyed on the emitter and an event keyed on nothing, so the alert's own
  identifier appeared nowhere in the output. A redelivery could not be recognised as a
  duplicate and an auditor holding the event could not get back to the source record.
- **`signal_strength` became `signal_strength_dbm`.** A bare `signal_strength` has been read
  as dBW, dBm and a 0–100 bar by three different consumers; the unit belongs in the name, as
  it already does in `speed_mps`, `alt_m` and `accuracy_m`.

**And one identifier was corrected before first publication, which is why it is recorded here and
not as a version event.** The published schemas' `$id` was
`https://synapsecommand.local/cdm/1.0.0/<name>.schema.json` and is now
`urn:synapsecommand:cdm:1.0.0:<name>`. The old value was not merely unresolvable: RFC 6762
reserves `.local` for multicast DNS, so an `https://` URI under it asserts a link-local scope,
which is a false thing for a published contract to say about itself. The pre-publication audit
found it.

**A URN rather than a served URL, ruled from what a consumer does with an `$id`** — the reasoning
is at `synapse_cdm/schemas.py`'s `BASE_ID` and the short form is that every `$ref` in these six
schemas is internal, so nothing needs the identifier to resolve; what an `https://` identifier
would add is an invitation to fetch something this repository does not serve and will not promise
to serve.

**No version bump, and that is a decision rather than an omission.** A `$id` is consumer-visible
and moving one after consumers exist breaks every registration keyed on it — which is exactly the
argument for doing it NOW: the repository is unpublished, `SCHEMA_VERSION` is still 1.0.0, and
there is no consumer to protect. A bump exists to protect consumers; publishing a wrong identifier
in order to deprecate it later protects nobody. If this repository were already public the same
change would be a MAJOR event, and the entry would read very differently.

### Adapters that landed with no schema change

Recorded because "no entry" and "nobody wrote an entry" look identical from here, and the first
is worth stating.

- **`adapters/tak.py` 1.0.0 (Cursor-on-Target, bidirectional)** — implements every row of the
  CoT table in `FORMAT_COVERAGE.md` at **schema_version 1.0.0**, with no field added, removed
  or retyped. Two temptations were declined and are listed below as 1.1.0 candidates instead:
  a canonical home for the CoT callsign, and one for `point/@le`. Both would have been MINOR
  and both would have been added in passing, which is the way a canonical model acquires two
  fields that mean nearly the same thing.

  What it needed instead already existed: `attributes` for the unmapped values, `TRANSFORMS`
  for the nine paths whose value legitimately changes, and `UNKNOWN` as an enum member for the
  three CoT affiliation letters the CDM does not carry.

- **`adapters/ais.py` 1.0.0 (AIS / NMEA 0183 AIVDM, bidirectional)** — message types 1, 2, 3,
  4, 5, 18, 19 and 21, at **schema_version 1.0.0**, with no field added, removed or retyped.

  Three temptations were declined and are listed below as 1.1.0 candidates instead. AIS is the
  format that makes the case for them, because it is the first one where the CDM's silence
  costs something measurable: a vessel's true heading and its course over ground are different
  numbers, and the difference between them is the interesting fact — a vessel making good 095
  while its bow points 070 is being set by wind or current, or is not going where it is
  pointing on purpose. Both land in `attributes` today, under keys only this adapter knows.

  What the CDM had already was enough for everything else, and two existing decisions earned
  their keep here specifically:

  - **`Kinematics`'s docstring was written about AIS's 102.3 sentinel before any AIS adapter
    existed.** Ten of them turned up — position 91/181, speed 102.3, course 360, heading 511,
    rate of turn −128, UTC second 60–63, IMO/ETA/dimension 0, and draught 0.0. The last is the
    one worth naming: it is the only sentinel that is also a plausible reading, so an adapter
    that correctly nulls the other nine can still report that a laden tanker draws nothing.
  - **`source_ids` being a LIST, and living on `CDMBase`.** A type 5 message states an MMSI and
    an IMO number, and they are not alternatives: an MMSI is reassigned when a vessel changes
    flag, an IMO number is fixed for the life of the hull. Both are emitted, under their own
    system names.

  One decision here is worth recording because it looks like a schema gap and is not.
  `Position.accuracy_m` stays null for every AIS fix. AIS states position accuracy as one bit —
  better or worse than 10 m — and writing `10.0` into a 1-sigma metre field would state an
  error nobody measured. The flag is parked. No new field is proposed for it: a threshold and a
  measurement are different kinds of claim, and giving the threshold a numeric home is how it
  would quietly become one.

- **`adapters/adsb.py` 1.0.0 (ADS-B 1090ES, Mode S DF17/DF18, bidirectional)** — type codes
  1-4, 5-8, 0 and 9-18, 19 subtypes 1-4, 20-22, 28 subtype 1 and 31 subtype 0, at
  **schema_version 1.0.0**, with no field added, removed or retyped.

  This is the fourth adapter and the first one whose *silences* cost something structural rather
  than cosmetic, so it adds two gaps to the list below (9, barometric altitude; 10, air-data
  speeds) and sharpens two that were already open. What it did NOT need is worth stating first,
  because three existing decisions carried it:

  - **`Position` requiring both coordinates.** ADS-B states a position as two 17-bit Compact
    Position Reporting values, which are a position *within a zone* and not a position at all.
    Recovering the zone needs either a second frame of the opposite parity or a reference
    position — so a frame this adapter cannot decode has NO position, and the model made that
    unspellable as anything else. A CDM whose Position allowed partial coordinates would have
    invited exactly the guess this format punishes.
  - **`Kinematics` every field optional, absent meaning unknown.** Every ADS-B "not available"
    is a zero in a field that is otherwise offset by one, so the whole family shares one shape
    and the characteristic bug is forgetting the offset — a value one unit wrong and entirely
    plausible. Nine fields carry it, and a vertical rate of 0 meaning "not reported" rather
    than level flight is the one that matters most.
  - **`PositionSource` as a member-bearing enum.** DF18 control fields 2 and 5 are fine-format
    TIS-B: a ground station rebroadcasting a surveillance track it derived by other means.
    ESTIMATED says so; GNSS would promise a fix that survives jamming, which is the dangerous
    direction and the same error as calling an AIS integrated navigation system INERTIAL.

  Two decisions in the adapter itself are recorded here because they look like schema questions
  and are not:

  - **The 24-bit address is filed under system `ICAO24`, not `ADSB`.** It is an ICAO Annex 10
    aircraft address, stable for the airframe and carried identically by Mode S replies, ACAS
    and ASTERIX — so `ids.derive` makes an ADS-B contact and a future radar contact agree on
    one `entity_id` without any coordination, which is the property derived identity exists for.
    `source.system` records the link the copy arrived over. DF18 control fields 1 and 5 state
    that the address is anonymous or self-assigned, and those get `ADSB_NONICAO` instead: a
    wrong join is worse than no join, because it merges two aircraft into one track.
  - **Global CPR even/odd pairing is out of scope, and it is the AIS type 24 argument again.**
    Two frames of opposite parity must be joined on the address across time; an `Adapter` is a
    pure function of one payload, so a global decoder would either emit a half-populated object
    or hold a cache, and a cache in a translator is fusion done where nothing audits it. Type
    24's parts A and B, AIS cross-payload fragment reassembly and CPR pairing are one decision
    made three times. Local decoding IS in scope because its reference position is
    CONFIGURATION — a constructor argument, like the clock — and not state. With no reference
    configured there is no position, so the default is the conservative one.

  Two defects are recorded because the gates that found them are the reason to keep those gates.
  The byte-exact round trip caught a **GNSS altitude being silently dropped** on every frame
  whose CPR could not be decoded: `alt_m` lives on `Position`, `Position` requires a coordinate,
  and an altitude with no horizontal fix therefore had nowhere to go. The adapter now parks the
  figure beside the canonical copy, and the shape of the problem is recorded in the gap 9 note —
  because a Mode C reply states an altitude and no position at all, so the next radar adapter
  meets it immediately.

  The second is the one no gate in this repository could have caught, and it is worth stating for
  that reason. The type code 20-22 altitude field was decoded with the **barometric** arithmetic
  — 25-foot steps behind a Q bit — when it is in fact the plain decimal value of all twelve bits
  in **metres** (mode-s.org, airborne position chapter). Because the fixture was encoded the same
  wrong way, the round trip stayed byte-exact, the goldens agreed with themselves and the lossless
  check passed: the frame simply did not mean what the adapter said, and a real frame carrying
  1039 in that field would have been reported at 24 975 ft instead of 1039 m. Only reading the
  reference found it. The lesson recorded here is the one the airtasking track already states as
  a rule — a field definition is CITED or it is a gap, never inferred from what a magnitude makes
  plausible — and the citation now sits in `FORMAT_COVERAGE.md` beside the row.

- **`adapters/legion.py` 1.0.0 (Picogrid Legion Platform API v3, ingest)** — Entity, Track,
  Entity/Track Location, Locations list and Event, at **schema_version 1.0.0**, with no field
  added, removed or retyped.

  The first adapter whose upstream is a REST API rather than a wire format, and the boundary is
  drawn in the same place: `to_cdm()` takes one already-fetched JSON document and owns no HTTP,
  no auth, no retries and no pagination. Two decisions carried over from the wire formats and one
  is new.

  - **Pagination is framing; correlation is fusion.** One page becomes one `Track`, and the
    adapter never follows `paging.next` — the AIS fragment-buffer argument and the ADS-B CPR
    argument reaching the same conclusion a third time. Four available joins are declined by
    name; what IS read is data the payload already embeds, which is reading and not correlating.
  - **A Legion Track is a CDM `Entity`, not a CDM `Track`.** `GET /v3/entities/{id}` and
    `GET /v3/tracks/{id}` return byte-identical schemas and a track location's foreign key is
    named `entity_id`. The CDM `Track` comes from a Locations LIST instead, which is where the
    history actually lives.
  - **A vendor API needs a pinned spec, and the pin is load-bearing.** Unlike a ratified
    standard, Legion can change between deploys, and its `info.version` demonstrably does not
    move when it does. So `fixtures/legion/spec/openapi_pin.json` records the document's SHA-256
    (which is also its ETag) and a field-by-field inventory, and a test fails the build on a
    field with no row in `FORMAT_COVERAGE.md`.

  What the CDM already had was enough, and three existing decisions earned their keep:

  - **`Position` requiring both coordinates, and `PositionSource` being a real vocabulary.**
    Legion's `crs` defaults to `EPSG:4978` — geocentric X/Y/Z in metres — while its position
    object is shaped like GeoJSON, so an adapter reading `coordinates` as `[lon, lat]` would
    place every contact somewhere impossible while emitting well-formed objects. And its
    location `source` names the SYSTEM that produced a fix, never the method, so
    `position_source` is ESTIMATED with a basis rather than a borrowed GNSS.
  - **`Affiliation` having four members and `SourceRef.synthetic` being separate from them.**
    Legion's enum is fifteen values wide and folds an exercise marking INTO the identity — so
    this is the widest collapse in the document and also a SPLIT, because the CDM already
    separates identity from context. `source.synthetic` is a declaration about the feed and is
    deliberately not rewritten by payload content.
  - **`attributes` accepting anything.** The four vectors Legion sends (`velocity`,
    `acceleration`, `angular_velocity`, a quaternion `orientation`), its 3×3 `covariance` and its
    `speed` all park, because their units and reference frames are documented nowhere and the
    schema's own `speed` and `velocity` examples contradict each other. That is the ADS-B
    altitude lesson applied BEFORE the fact rather than after it.

  Four corrections happened during implementation and all four came from a gate rather than a
  review, which is the note worth keeping: the never-drop check caught the list path pruning
  every sample's metadata; the pinned inventory caught a hand-read claiming six omitted fields
  where the spec says five; a TRANSFORMS audit caught six exemptions with no subject; and the
  harness caught the spec pin being replayed as a payload.

- **`adapters/asterix_cat021.py` 1.0.0 (ASTERIX category 021 ADS-B target reports,
  bidirectional)** — all 42 data items plus the RE and SP fields and the whole Reserved
  Expansion Field, at **schema_version 1.0.0**, with no field added, removed or retyped.

  Pinned to EUROCONTROL-SPEC-0149-12 **Edition 2.6** and its Appendix A Reserved Expansion Field
  **Edition 1.5**, both by SHA-256. Ed 2.6 states on its own cover that it is not backwards
  compatible with Ed 2.1 or earlier, so the edition is part of the mapping and not a footnote.

  Three things this format has that no earlier one did, and each is a decision rather than a
  translation:

  - **Seven time items and not one date.** Every CAT021 time is elapsed time since last
    midnight UTC at 1/128 s. The reference date comes from the injected clock and the instant
    chosen is the one bearing the stated time of day NEAREST the receipt instant — one rule that
    handles both midnight-rollover directions with no special case, and the AIS
    second-of-minute construction generalised. A value at or beyond 86 400 s is REFUSED with the
    raw integer quoted, never taken modulo a day.
  - **A quality vocabulary that needs another item to say what it means.** I021/090's primary
    subfield holds "NUCr or NACv" and "NUCp or NIC", decided by the MOPS version in I021/210 —
    which is optional. Where it is absent the reading is recorded as UNDETERMINED rather than
    guessed. Nothing in that item reaches `Position.accuracy_m` or `Entity.confidence` under
    either reading, PIC included: it states a containment bound in nautical miles and a bound is
    still not a 1-sigma error.
  - **A ground station that has already judged.** Range checks, CPR validation, an independent
    position check and a black-list lookup all arrive as flags. They are carried and never
    re-decided — and `RCF`'s own note in the specification says an operational user will
    SUPPRESS such a target, which this adapter does not: filtering is a decision, and a decision
    made inside a translator is invisible in the CDM output.

  What the CDM already had was enough, and two existing decisions earned their keep. The
  **`ICAO24` source-id namespace** means a CAT021 record and a 1090ES frame of one airframe
  derive the same `entity_id` without the two adapters coordinating — asserted by a fixture that
  carries the ADS-B set's own address. And **`attributes` accepting anything** is what lets the
  wire octets of every item be parked verbatim beside the converted values, which is why
  `TRANSFORMS` is **empty**: a declared transform is an exemption from the never-drop check, and
  this adapter needs none. The harness reports `lossless: PASS` on every parsed twin with
  nothing excused.

  Three gaps opened, each evidenced by something this format states and the CDM cannot hold:
  **13** no per-measurement time (two applicability instants in one record, plus twenty-three
  per-item ages in I021/295), **14** no producing sensor (the ground station is named in every
  single record), and **15** no intent (selected altitudes, trajectory intent, navigation mode —
  the deferral `adsb.py` made at type code 29, which this format does not allow).

  One decision changed during implementation and a gate found it: `from_cdm()` originally took a
  single emittable object, which failed the two-record round trip. A data block holds N records
  and the byte-exact claim is about a BLOCK, so it now emits many Entities as many records in
  block order.

- **`adapters/stanag4676.py` 1.0.0 (STANAG 4676 / AEDP-12 Edition B Version 2 NITS tracks,
  bidirectional)** — the full UML model, 48 classes and 273 attributes, at **schema_version
  1.0.0**, with no field added, removed or retyped.

  Pinned to AEDP-12 **Edition B Version 2** (March 2022) by SHA-256, with the AEDP-12.1
  Implementation Guide and the STANAG 4676 Edition 2 ratification wrapper. Edition A is refused
  by name: §2.1.1.1 says the two editions are incompatible and that the model was re-architected
  "from scratch", so a 2014 feed is a separate adapter rather than a mode.

  Four things this format has that no earlier one did:

  - **A relative time model.** `baseTime` is absolute and every instant is an integer count of
    `relTimeIncrement` seconds from it, so unlike CAT021 there is nothing to reconstruct and the
    injected clock supplies no part of an observation time. But `relTimeIncrement` is a double,
    and 1/128 s and 1/29.97 s — the cases the model exists to serve — are not whole
    milliseconds, so the raw integers are parked and egress re-emits from them.
  - **A mandatory confidentiality label that the CORE MODEL does not mention.** Ed B §2.1.1.6 is
    silent on confidentiality and defers per syntax; Annex B.2 then makes a STANAG 4774
    `originatorConfidentialityLabel` mandatory on the root element. It is carried as the exact
    fragment that arrived — never parsed, never re-serialised — and egress has three paths: the
    park, an explicit deployment-supplied label, or a refusal. This is **gap 12**'s strongest
    evidence and the reason it is no longer "one vendor states a string".
  - **Six coordinate systems, three of which cannot produce a position.** `ECI_J2K` needs daily
    Earth-orientation parameters, `PIXELS` needs a sensor model, and `LOCAL_SPHERICAL` is
    refused because the slot the standard labels *azimuthal* is the argument of `z = r cos phi`
    in its own mandated equations — two conformant producers can fill the array two ways and
    nothing in the data says which. Logged, not guessed: the Legion `EPSG:4979` refusal reached
    from a different direction.
  - **A format that models fusion.** `TrackLinkage`, `ProcessedTrack`, `IDSourceInformation` and
    §2.1.1.2.3's normative consolidation across data streams are all carried and none is
    performed. The consolidation rule is the sharpest case, because the standard *requires* a
    consumer to do it — and a stateful reducer inside a translator is exactly what the adapter
    contract forbids.

  What the CDM already had was enough again, and the same two decisions earned their keep. The
  **`ICAO24` namespace** now serves three adapters: a NITS `IFFCode` in `MODE_S` whose value
  parses as six hex digits derives the same `entity_id` as a 1090ES frame and a CAT021 record.
  And **`attributes` accepting anything** is what holds a 273-attribute model verbatim beside
  the converted values, so `TRANSFORMS` is **empty** and the harness reports `lossless: PASS` on
  every parsed twin with nothing excused.

  Four gaps opened in Phase 1 and all four stand: **16** no per-sample extension, **17** no
  state-vector uncertainty, **18** no confidence provenance and no retraction, **19** no relation
  object. Gap 2 gained two things during implementation: `TRAVELER` and `ZOMBIE` as concrete
  evidence, and a **divergence between three adapters** — `symbology.AFFILIATION_FROM_COT` and
  `legion.AFFILIATION` map JOKER and FAKER to HOSTILE while this adapter maps them to FRIENDLY.
  Stated rather than resolved, on the I021/170 precedent; whoever settles gap 2 settles that.

  Note where an amplification stops: it is READ when the CDM has a member for what it states and
  RECORDED when it does not, so `FAKER` sets FRIENDLY and `ZOMBIE` never downgrades a stated
  identity. Ed B makes the two attributes separate with no co-occurrence restriction, and a
  subordinate field rewriting a primary assertion is the move `essence` is forbidden from making
  against `source.synthetic`.

  `FAKER` "overriding" a contradicting identity is not adjudication: its definition is "Friendly
  track, object or entity acting as exercise hostile", so the identity claim is inside the
  amplification literal and reading it is reading a stated fact. `ZOMBIE`'s definition asserts
  suspicion — the judgement `Affiliation` deliberately lacks a member for — so there is nothing
  to read. **The principle self-terminates**: if `Affiliation` ever grows SUSPECT, `ZOMBIE` and
  `TRAVELER` move from recorded to read by the same rule, and
  `test_the_two_suspect_amplifications_never_yield_friendly` is the tripwire that fires when
  that happens.

  `Position.position_source` is the one canonical field this adapter fills from a resolved
  reference chain rather than a constant: `GNSS` where `TrackSource` resolves in-document to an
  `AIS`, `ADS-B` or `BFT` modality, `ESTIMATED` on every other branch including a DATASTREAM
  reference that resolves to a file we do not have.

  One thing is knowingly incomplete and it is not a gap in the CDM. **The XML element binding is
  provisional**: the normative XSD is distributed through NATO national representatives and
  could not be obtained or hashed, so element names bind to UML attribute names through one
  empty table, `ELEMENT_NAMES`. Every fixture ships as an XML/parsed twin and a test asserts the
  two produce byte-identical CDM, which is what makes the binding checkable — it found four
  defects on its first runs, two in the reader and two in the confidentiality label's handling.

- **`adapters/gmtif.py` 1.0.0 (STANAG 4607 / AEDP-4607 Edition A Version 1 GMTI, bidirectional)**
  — the packet header, the segment header and all ten defined segments, **212 fields**, at
  **schema_version 1.0.0**, with no field added, removed or retyped.

  Pinned to AEDP-4607 **Edition A Version 1** (February 2024) by SHA-256, with AEDP-4607.1 and
  the STANAG 4607 Edition 4 ratification wrapper. Edition 3 is refused by name with `P1` quoted,
  and the reason is not structure: the packet layout is unchanged and what moved is three
  enumeration tables, so an Edition 3 packet decoded here **misclassifies targets with no
  structural symptom** — every length checks out and the targets are the wrong kind of object.
  One adapter with a version-dispatched table is the right shape and Edition 3's tables are not
  pinned here, so earlier editions are deferred rather than best-effort decoded.

  Landed in four commits, reviewable apart: the row set as a specification with every row saying
  `not yet` (`f4a67ec`), seven amendments to it before any code (`9d57732`), the adapter
  (`3d43871`), and six amendments to that (`519ee71`).

  Five things this format has that no earlier one did:

  - **It is the first non-text wire format**, so the Annex C codec is a layer of its own with its
    own suite: seven numeric encodings, two of them **sign-magnitude** rather than two's
    complement and two of them **binary angles** whose signed and unsigned forms differ in
    *both* signedness and exponent. Every one is a place where a wrong answer is a plausible
    number rather than an exception, so `encode(decode(b)) == b` is asserted over every 16-bit
    and 8-bit pattern by exhaustion, and the two strongest cases are the worked examples the
    standard itself prints — `BA16 0101100100011100` = 125.31006° and −34.876099° = `SA16
    1100111001100110`. No `struct` format anywhere: `int.from_bytes(..., "big")` at every call
    site, because an explicit `>` is one typo from the native order.
  - **An existence mask that governs every subsequent field offset**, so one wrong bit
    desynchronises the rest of the segment. That is what grounds the refuse-versus-record split
    on something the code can verify — whether the byte offsets of everything after the problem
    are still known — rather than on a validation annex whose own references name a 2007 edition.
    A reserved or extension segment type is **skip-and-record**: exact, because §3.2.2 gives its
    length, and never silent, because a packet carrying an Advanced Dwell Segment nobody decodes
    would otherwise be indistinguishable from one carrying nothing.
  - **Targets that are detections rather than tracks.** Nothing in the core segments identifies a
    real target: `D32.1` is scoped "within the dwell" by its own definition and Conditional
    besides, `(D2, D3)` does not identify a Dwell Segment, and `D3` wraps. So each target report
    becomes one `Entity` and one `DETECTION` `Event`, the `entity_id` ends in two **positional**
    ordinals whose fragility is stated on the object, and **no target `Track` is ever emitted** —
    the format's own implementation guide sends the reader to the sensor manufacturer for the
    association rule, so a translator may not invent one. The **platform** is the exception and
    the only identity the format guarantees: §3.1.8 makes each nation responsible for its
    platforms being uniquely identified, so `P3` + `P8` is a real `SourceId` and gets the one
    `Track`.
  - **A reference date on the wire, in a different segment from the times it resolves.** The first
    adapter here for which the injected clock supplies no part of a date — `M5`/`M6`/`M7` do —
    and the first that needs stream context it refuses to hold: §3.3 sends the Mission Segment
    "at least once every two minutes", so the date may be in an earlier packet. Three paths, and
    provenance on **every emitted instant** rather than once per packet: the packet's own Mission
    Segment, an explicit caller argument relaying an earlier packet's date, or a refusal. A
    Mission Segment contradicting the caller's argument is a refusal quoting both — neither
    silently wins, because letting the wire win discards a caller statement that may indicate
    mis-tracked stream state and letting the argument persist lets a stale date override the
    place §3.3 puts the answer. The caller's date is a **stand-in for absent wire context and not
    a deployment declaration**, so it gets no protection against the wire.
  - **Two payload declarations of whether the data are real, one boolean, and neither writes it.**
    `P7` Exercise Indicator is Mandatory on **every** packet and says real, simulated or
    synthesized in as many words; `D32.10`'s upper half says it per target. Neither touches
    `source.synthetic` **in any direction, agreement included** — a rule that let a payload field
    set a deployment declaration whenever the two matched would bind only on disagreement, which
    is a default with a conflict check bolted on. Three branches: pure-simulated against a real
    declaration refuses, pure-real against a synthetic one refuses, and `synthesized` — "a mix of
    real and simulated data", §3.1.7 — contradicts neither pure declaration and **parks visibly
    without a refusal**, because refusing would reject the case §3.1.7 exists to describe. A
    simulated target inside a purely-real packet is a **separate** refusal, payload against
    payload, naming `P7 = 2` as the value the packet needed.

  **The `D32.10` mapping is a lookup and never arithmetic, and `FACILITY` appears nowhere.**
  Eighteen of the forty-three named classifications map, every one of them to `PLATFORM`; the
  rest park as `UNKNOWN` with the standard's wording. `128 + n` mirrors `n` for n = 0…13 and for
  no other n — 144–148 mirror 14–18 at an offset of **+130**, so an arithmetic decoder reads
  Clutter-Simulated as Ground-Rotator-Live. The rotator classes park rather than becoming
  `FACILITY`: they name a Doppler signature class, and reading an installation off a motion
  characteristic is the inference this adapter already refuses for `M3` Platform Type. The
  **tagging-device exemption is keyed on the LABEL** and not on a value, because the label has
  been carried by 140, then 143, then 142 across three editions.

  What the CDM already had was enough again, and one thing it did not have is now written down.
  **`attributes` accepting anything** is what holds the whole decoded packet verbatim beside the
  converted values, so `TRANSFORMS` is **empty** and the harness reports `lossless: PASS` on every
  parsed twin with nothing excused — and it is also what makes the **byte-exact round trip**
  structural rather than hopeful, because egress re-encodes from the park. Sixteen binary twins,
  32 files, 32 goldens; `roundtrip` reports SKIP on both halves of every twin because `from_cdm()`
  returns binary and the harness compares structures, so the byte-exact claim is the adapter's own
  test and is a stronger claim than the harness could make.

  **Four gaps opened, 20 to 23**, and each has its assertion in the gap test:

  - **20 — no detection-versus-track distinction.** An `Entity` says *this exists* and a `Track`
    says *where it has been*; neither says *a radar returned energy from this point at this
    instant and nothing before or after is claimed*. It is why `Entity.valid_to` has no honest
    value here, why the key ends in positional ordinals, and why twenty-five of `D32.10`'s
    classifications have no honest `EntityType` — `Clutter` and `Phantom` being *explicit denials
    that anything is there*. The gap now also carries **two stated divergences**: a person maps
    `UNKNOWN` here and `PLATFORM` in the shipped CAT021 adapter, and a detection's fix lives in
    `Event.geometry` here and in `stanag4676.py` while `asterix_cat021.py` and `adsb.py` leave it
    `None`. Both are 1.1.0 questions with both arguments written down, on the I021/170 precedent.
  - **21 — no home for a radar measurable**, and specifically no way to state **one component** of
    a velocity. `D32.7` is the radial component and the tangential part is physically
    unobservable to a single-look MTI radar, so a target's `Kinematics` is `None` and the radial
    value is not a speed. Explicitly **not** gap 4: a component is a projection, not a vector with
    elements missing. Plus SNR, RCS, classification probability, MDV and electrical length.
  - **22 — no negative information.** Stated by the format's own guide — "the fact that the radar
    has looked at a particular area and found no targets can be just as important as receiving
    targets in an area" — and built into the standard, which requires a Dwell Segment "even if no
    targets are observed". The CDM renders "not looked at", "looked at and empty", "looked at with
    an MDV of 3 m/s" and "targets found and then filtered out" identically, as empty space.
  - **23 — no way to carry an observation whose source states no time.** Three GMTIF segments have
    no time field in their layout at all — Free Text, Processing History, and an HRR segment whose
    `H2`/`H3` name a dwell in another packet — and `Event.observed_at` is required and documented
    "Never receipt time". The adapter substitutes the receipt instant and labels it in
    `payload.observed_at_basis`, which is the least bad of three bad answers and **still a
    violation of the field's documented meaning on three object kinds**. Two 1.1.0 proposals: make
    `observed_at` optional so an absence can be an absence, or add a typed, mandatory basis field
    beside it. **The `models.Event.observed_at` docstring amendment rides the same release**,
    because its wording is part of the v1.0.0 contract.

  **Three ambiguities were found by implementing rather than by reading**, which is the split
  worth noticing — a contradiction in a byte-range column and a contradiction between two "shall"
  statements are both invisible until something has to obey both. **15**: `H15`'s value range
  restates `B16`'s maximum for a `B32` field and its stated minimum is 2⁻²² where the encoding's
  LSB is 2⁻²³, so Annex C-4.5 is followed and the range column is not enforced. **16**: §3.1.10
  requires `P10 = 0` with no dwell data and §3.7.1 gives `J1` a floor of 1, so a literal
  `J1 == P10` cross-check makes a Job-Definition-only packet — which the guide's own Figure 2-1
  draws — impossible to represent; the row set's rule was narrowed to §3.1.10's own condition
  rather than the packet refused. **17**: §3.5.6 and §3.5.7 both end "Either H6 or H7 or both must
  be reported", so a sparse chip may carry both with the two disagreeing about how many scatterer
  records follow, and nothing says which governs — which is the written justification for bounding
  the array by `S2` and parking it whole rather than adjudicating between two "must be reported"
  fields on a conformant packet.

  One defect is on the record because a review asked the right question of it. `codec.snap`, which
  quantises a CDM-native position to a field's own resolution on egress, originally **masked** the
  encoded integer to the field's width — so `snap("SA32", 95.0)` returned **−85.0**, a latitude on
  the other side of the equator, and `snap("B16", 300.0)` returned −44.0. Clamping to the boundary
  would have been less bad and still silent. Quantising inside a field's range is the format's
  stated resolution being applied; moving a value **into** range is not, and an out-of-range value
  is now a refusal quoting the value and the range.

- **`adapters/asterix_cat048.py` 1.0.0 (ASTERIX Category 048, Monoradar Target Reports,
  bidirectional)** — all 28 UAP FRNs of EUROCONTROL-SPEC-0149-4 Edition 1.32, at
  **schema_version 1.0.0**, with no field added, removed or retyped.

  This is the eleventh adapter and the first **sensor-side** one: its reports are genuine
  detections rather than self-reports, which is why `Event.event_type` is `DETECTION` in the
  ordinary case where AIS, ADS-B and CAT021 all use `TRACK_UPDATE`. Two of its rulings reversed
  during review and both reversals were away from using an existing field, which is worth
  recording because the pressure runs the other way:

  - **`Entity.valid_to` was NOT used for the track-end bit.** I048/170's `TRE` is the only
    explicit terminal declaration any source in `FORMAT_COVERAGE.md` makes, and a first draft
    wrote it into `valid_to`. It ends "a track record within a particular track file"
    (§5.2.18), not the airframe the `entity_id` names — so `valid_to` would have told every
    consumer that did not read a basis key that the aircraft's state ceased. **Gap 26.**
  - **I048/161 was NOT made a `SourceId`.** A station-scoped, recycled 12-bit number keyed into
    `entity_id` merges two airframes into one entity. Declining it loses the continuity the
    radar states across scans — a truncation, named in **gap 27** — and the alternative was a
    false statement in the field the CDM guarantees is stable across updates.

  What the CDM had was otherwise enough, and one existing decision earned its keep in a way no
  previous adapter tested: **`Position` requiring both coordinates**. CAT048 states range and
  azimuth from a station whose location the format never carries, so a caller that injects no
  `sensor_position` gets `position: None` on every object — and because the model makes a
  partial coordinate unspellable, there is no way to express that as a half-position. The
  injected site is the injected clock's precedent applied to geometry, and the arithmetic it
  enables is declared in `attributes.position_basis` because **the pinned specification supplies
  none of it** (gap 24).

  One gap it opens is a schema question rather than a parking key, and it is the entry above:
  `PositionSource` has no member for a sensor measurement, so a derived radar fix is written
  `ESTIMATED`.

  **Three commits, and the row set came first.** `70b8c07` wrote the row set as a specification
  with `not yet` in every status column and no code; `7e13f27` amended it under review, reversing
  three of its own rulings; `6cb283e` shipped the adapter against the amended rulings and flipped
  all 136 rows. The reversals are the reason the order matters — each one was away from using an
  existing CDM field, and each was easier to make while the row set was still prose.

- **`adapters/asterix_cat034.py` 1.0.0 (ASTERIX Category 034, Monoradar Service Messages,
  bidirectional)** — all 14 UAP FRNs and all 12 data items of EUROCONTROL-SPEC-0149-2b Edition
  1.29, at **schema_version 1.0.0**, with no field added, removed or retyped.

  This is the twelfth adapter and **the first whose primary object is the sensor itself.** Every
  record in Part 2b describes the radar station, not a target, which inverts three things every
  previous adapter took for granted: `Entity.entity_type` is `SENSOR` from the *category* rather
  than read off any item, `I034/010`'s SAC/SIC is a `SourceId` here where the identical two octets
  are parked at `attributes.data_source` in `adapters/asterix_cat048.py`, and `Kinematics` is
  `None` on every object because a station does not move. The one bearing the category carries,
  `I034/020`'s sector number, is the **antenna's** — writing it into `Kinematics.course_deg` would
  state that the radar head is travelling on that heading.

  Pinned to one document by SHA-256: **EUROCONTROL-SPEC-0149-2b, ASTERIX Part 2b Category 034,
  Edition 1.29, 15/03/2021** (`32925e6a…cfcae101`, 639 615 bytes, 41 pages). The PDF is not
  committed. Three further editions — **1.26, 1.27 and 1.28** — sit in
  `fixtures/cat034/spec/history/` as the lineage and are explicitly **not pins**.

  **Two rulings Phase 1 deferred were made here, and both are decided by the document rather than
  by preference** — which is the reason the row set was written first:

  - **No `Geometry` is ever derived from `I034/100`.** Phase 1 asked whether using `I034/120` from
    the *same record* to turn a polar window into a polygon is a derivation or a state merge.
    Table 2 answers it: `I034/120` is permitted on message type 001 alone and `I034/100` is
    forbidden on that one, so **there is no message type for which both are permitted**. The
    station's position could only ever come from a different record, which is the cross-payload
    state this repository refuses. `Event.geometry` is `None` on every object.
  - **A record whose message type this edition does not define is translated, not refused**, at
    `STATUS_CHANGE` / **`ADVISORY`**. `INFO` would say the message is understood and ordinary;
    `WARNING` would invent an alarm out of an unknown. `ADVISORY` is the CDM's own middle value and
    the only one that leaves the record visible to a severity filter while claiming nothing.

  **The gap Phase 1 opened is the gap that shipped, and no field was proposed for it.**
  `EventType.GNSS_INTERFERENCE` is paired with `GnssInterferencePayload` — `frequency_band`,
  `interference_type`, `signal_strength_dbm` — and exists for PNTMAP. Three of this category's
  seven message types are radar jamming strobes, and none of them sets it: they become `ALERT` at
  `WARNING` with the strobe geometry parked. That is **gap 29**, and it stays a gap rather than
  becoming a 1.1.0 proposal, because one format wanting a shape is a gap and two are a proposal.

  **And one finding is recorded because it changes nothing, which is the point.** `I034/120`
  carries the 3D position of the data source in WGS 84 — the value `FORMAT_COVERAGE.md`'s CAT048
  settlement 3 requires the caller to *inject*, and whose geodesy **gap 24** records as absent from
  the CAT048 document. The adapter translates it into a `Position` on the object that carries it
  and hands it to nobody. Gap 24 does not close, deliberately: it is about what the CAT048 document
  contains. Phase 2 made that **assertable** rather than merely recorded — every such object carries
  `attributes.position_basis.gap_24` saying so, and a test reads both that key and the gap's own
  entry in `FORMAT_COVERAGE.md`.

  **What the CDM had was otherwise enough, and one existing decision earned its keep in a new way:
  `Position` requiring `position_source`.** A surveyed radar head is none of `GNSS`, `INERTIAL` or
  `ESTIMATED`; `MANUAL` is recorded as the least-wrong of four rather than as a fit, and §5.2.12's
  "accuracy of at least 2.3844 metres" is parked as a quantisation step rather than written into
  `accuracy_m`, because reporting a resolution as an accuracy claims the station knows where it is
  to 2.4 m when the document says only that it cannot say so more finely.

  **Two commits, and the row set came first.** `840e92c` wrote the pin, the ruling and the row set
  as a specification with `not yet` in every status column and no code; this one shipped the
  adapter, the codec, twenty fixtures and the test module against those rows, and flipped all of
  them. Five Phase 1 rows changed in the same commit and each is listed in `FORMAT_COVERAGE.md`
  under "What Phase 2 changed in the Phase 1 row set" — including two that matter for this file's
  own discipline. The fixture plan's prose said twenty fixtures and four refusals while its table
  had nineteen rows and three, because the totals had been counted off a sub-heading rather than
  off the cells under it. And a **mutation** asked for a twentieth the plan did not have:
  `spare_bits_nonzero`, because zeroing a spare bit inside the decoder passed every test when every
  fixture's spare bits were already zero, and §4.4 says a decoder "shall never assume and rely on"
  their setting.

  **The Edition 1.30 record was corrected, and it is the one correction here that is not about
  code.** Phase 1 wrote that Edition 1.29 "is not the newest published" and that Edition 1.30 "is
  the current edition", from a citation and without a check. This round checked EUROCONTROL's
  Category 034 publication page on **2026-08-24**: the newest file it offers is Edition 1.29, the
  pin. So the fact is two-part — **cited-but-unpublished**. Two independent sibling specifications
  name Edition 1.30 (CAT048 Edition 1.32 §2.2 reference 5, already quoted in `cat048_pin.json`, and
  CAT007 Edition 1.12 of July 2024 §2.2), and no page offers it. The Message Type 008 content
  stands exactly where it stood, **as an inference**: a page that does not offer a document says
  nothing about what the document contains. The check date is recorded because "was not published"
  and "was not checked" are indistinguishable a year later.

- **`adapters/asterix_cat062.py` 1.0.0 (ASTERIX Category 062 SDPS Track Messages,
  bidirectional)** — adapter #13, at **schema_version 1.0.0**, with no field added, removed or
  retyped. The largest ASTERIX category this repository has translated: 27 data items, six compound
  items, a six-extent FX chain and a Reserved Expansion Field decoded in full, landed against a row
  set written first with `not yet` in every status column. One Phase 1 row changed and it is listed
  in `FORMAT_COVERAGE.md` under "What Phase 2 changed in the Phase 1 row set".

  **What it cost the model: nothing, and it is the source that most nearly did.** It is the third
  to state a vertical accuracy the CDM has no field for (**gap 6**) and the fourth to state a
  heading with a datum and a turn rate (**gap 7**), and it is the FIRST to state a positional
  standard deviation in the CDM's own terms — which `Position.accuracy_m` already had a home for,
  so that one closed rather than reopened. A category whose input is itself a fused product
  absorbed into the contract without a field is the strongest evidence this section carries.

- **`adapters/asterix_cat023.py` 1.0.0 (ASTERIX Category 023 CNS/ATM Ground Station and Service
  Status Reports, bidirectional)** — adapter #14, at **schema_version 1.0.0**, with no field added,
  removed or retyped, and **no Phase 1 row changed at all**. Nine data items on 21 printed pages.

  **The first adapter here that emits TWO Entities from one record**, and it needed nothing of the
  model to do it: a service is an `Entity` with `entity_type` `SENSOR` — recorded as the least-wrong
  of eight rather than as a fit — keyed on the pair `(SAC/SIC, Service Identification)`, and the
  relationship rides on the `Event`'s existing `related_entities`. An `EntityType` member for a
  service, or a parent field on `Entity`, were both available and both declined: the first would
  widen a closed vocabulary for one source, and the second would put a relationship in the model
  that the CDM deliberately leaves to a fusion layer.

- **`adapters/stanag4609.py` 1.0.0 (STANAG 4609 / MISP-2019.1 UAS Datalink Local Set, bidirectional,
  byte-exact)** — adapter #10, at **schema_version 1.0.0**, with no field added, removed or retyped.
  26 of ST 0601.14a's 141 items, which is the witnessed set the one pinned KLV stream attests; the
  other 115 rows still read `not yet`.

  **The entry that made this section's rule an argument rather than a formality.** Every bullet above
  adds a source whose values land in fields the CDM already had; this one adds a new KIND of output —
  a structured defect annotation, written when an item's octet count contradicts its own standard's
  Required Length — and "new output surface" is the shape that ought to move `SCHEMA_VERSION`. It did
  not, and the ruling is in the 1.2.0 section above with the file and line of every piece of evidence:
  the annotation lives inside `Entity.attributes` and `Event.payload`, which the published schemas
  declare `additionalProperties: true` while the objects carrying them are `additionalProperties:
  false`. **361 adapter-private keys already live in those two bags across the thirteen adapters'
  goldens**; a new one is what the bag is for.

  Two model members were available and both declined, on this section's usual grounds. `Integrity`
  was the obvious home for a checksum verdict — this is the first adapter here whose format defines
  one — and it is designed for a PQC signature block, so a 16-bit summation would have widened a
  field for one source; the verdict rides at `attributes.integrity_basis` instead. And
  `EventType.DETECTION` was available for a motion-imagery packet and is not used, because nothing in
  the witnessed set detects anything: the item that would is ST 0601's VMTI Local Set, which is a
  park.

### Row sets written as specifications, with no adapter code yet

A new heading, and it needs one sentence of justification because this document dislikes
conventions adopted in passing. The section above records adapters that **landed** without a schema
change, "because 'no entry' and 'nobody wrote an entry' look identical from here". A row set that
has landed as a *specification* and has no adapter yet makes no schema claim at all, so it has
never had a home here: the Legion, NITS and GMTIF Phase 1 commits wrote nothing in this file, and
CAT048's wrote only its 1.1.0 candidates. That is the same indistinguishability one level up — a
Phase 1 that proposes no field and a Phase 1 that nobody thought about look identical from here
too — so the first is now stated.

- **`stanag4609` — STANAG 4609 / MISP-2019.1, the KLV metadata stream. Phase 1: row set only, no
  adapter code, no codec, no fixtures.** `stanag4609` is adapter #10, under the reserved-ordinal
  rule `FORMAT_COVERAGE.md`'s ordinal table states: `stanag5527` has #9, `gmti`
  has #8, and the next free number is therefore this adapter's. `cat048` keeps #11. Every
  mapping row in `FORMAT_COVERAGE.md`
  says `not yet`, and **no gap is opened and no field proposed** — which is the entry.

  Pinned to five documents by SHA-256: **STANAG 4609 Edition 5, 30 July 2020**
  (`f2f9ae1a…b2dbf8d8`, 273 801 bytes, 5 pages) and the profile its AGREEMENT clause names,
  **MISP-2019.1, title page November 2018** (`3167362a…b102d5ea`, 1 372 771 bytes, 73 pages), plus
  three of the delegated field dictionaries obtained on 2026-08-26 — **MISB ST 0601.14, served as
  `ST0601.14a.pdf`, cover dated 1 May 2020** (`3d5f1ca1…ab212ce4`, 3 969 201 bytes, 218 pages),
  **MISB ST 0102.12, 22 June 2017** (`20d40b52…85eca267`, 514 842 bytes, 18 pages) and **MISB ST
  0601.19, cover dated 02 March 2023** (`e53c1e7b…0cfb92b1`, 4 700 978 bytes, 226 pages). **The
  first two are the editions the profile pins** — Appendix B ref [53] pins 0601.14 and ref [55]
  pins 0102.12 — and **the third is not**, being five major revisions later; it is retained as
  **context only** and is never a source of tag semantics. `spec/klv_pin.json`'s
  `reconciliation_ruling` carries every citation verbatim and the ruling on each. No PDF is
  committed.

  **The round that obtained ST 0601.14 transcribed its Table 1 in full — 141 items, tags 1 through
  141, every row `not yet` — and closed park 1**, the largest of the thirteen. It did not otherwise
  advance: parks 4 and 8 (ST 0107.3 and SMPTE ST 336:2017) own how a key and a length are written,
  and holding the dictionary does not make the octets readable. **Still no gap opened and no field
  proposed.** Two
  findings are worth carrying here rather than leaving in the pin. First, ST 0601.14 §6.4 and §8.2
  **state the Precision Time Stamp's epoch** — SI seconds since `1970-01-01T00:00:00Z`, in
  microseconds, leap seconds excluded and therefore not UTC — which corrects the *reach* of this
  entry's own epoch note below without touching its finding: the profile still states none, and the
  rule was always "do not write one from memory" rather than "do not write one". Park 3 stays open
  because ST 0603.5 remains the normative definition. Second, item 65 is **mandatory in every
  packet and declares which revision of ST 0601 the producer encoded against**, so park 1's
  wrong-edition hazard is detectable on the wire — but it is a `uint8` and cannot express the
  minor-version letter, which is the same blind spot the citation has. Register entries **KLV 9**
  **A later round the same day asked how much of the framing the pinned copy settles by itself, and
  the answer was two rules of three.** ST 0601.14a **states** the 16-byte Universal Label (§6.2), the
  packet shape (§6.3 and Figure 1), the BER-OID tag form and its 127/128 width transition (§7.1),
  the two-octet bit pattern and its 14-bit ceiling (Figure 67, PDF page 212), the checksum algorithm
  with a worked vector (§6.6, §8.1.1.1–2) and the Zero-Length Item (§6.5). It **delegates** the BER
  length grammar entirely: `ST 0601.8-07` states the constraint and is **(Deprecated)**, the live
  route `ST 0601.8-03` sends it to ST 0107.3, and no worked example in 218 pages carries a length
  octet above `0x24`. So `adapters/klv_codec.py` and thirteen fixtures in `fixtures/klv/framing/`
  exist — a **codec and not an adapter**, no registry entry and no ordinal — and its
  `decode_ber_length`, `encode_ber_length` and `walk_local_set` exist, are importable and **raise**,
  naming the park. **Parks 4 and 8 both stay OPEN**: no document was obtained, so no park state
  moved, and all 141 rows stay `not yet` because a framing rule says where an item begins and never
  what it means. What did move is the size of park 8, which owned "key forms, the 16-byte Universal
  Label, the length forms" and now owns the length grammar and the third BER-OID octet. Register
  entry **KLV 11** records a new divergence found in passing: ST 0601.14a's reference [2] and
  MISP-2019.1's ref [13] both pin **ST 336:2017** while ST 0102.12's reference [3] pins
  **ST 336:2007**, so two delegated documents this repository holds disagree about which edition of
  the encoding standard governs.

  **A third round the same day followed `ST 0601.8-03` where it points, and it points at six
  pages.** "All UAS Datalink LS metadata shall be expressed in accordance with MISB ST 0107 [5]" —
  so **MISB ST 0107.3, KLV Metadata in Motion Imagery** was obtained from NSG Registry document
  4738, pinned at `fixtures/klv/spec/ST0107.3.pdf` (SHA-256 `500d6752…98b69794`, 656 949 bytes, **6
  pages**), and read in full. **PARK 4 IS CLOSED** — the second park to close and the cheapest in
  the table — and `klv_codec` now walks a UAS Datalink LS packet end to end.

  What ST 0107.3 states, each with its section: the **short form** (§6.3.2, "the short form
  one-byte (0x02) length"); the **long form and its length-of-length octet**, derived from the four
  encodings §6.3.2 prints — `0x02`→2, `0x8102`→2, `0x8180`→128, `0x8300 0080`→128 — where `0x81`
  introduces one following octet and `0x83` introduces three, so the first octet's low seven bits
  are a **count**, big-endian by `ST 0107.2-02`; **minimality as a live requirement**,
  `ST 0107.3-05`, "shall be BER Short form or BER Long form encoded using the fewest possible
  bytes", which is `ST 0601.8-07` with the onward delegation *removed* and the scope *widened*; a
  **zero length** as legal with the Value "not a part of the item" (§6.3); the **BER-OID chain rule
  for any width** (§6.3.1), which is the "(or more)" §7.1 never defined; and the **`0x80`
  prohibition on tags** (§6.3.1, "ASN.1 forbids the use of 0x80 in the first byte of a BER-OID
  value"), which promotes a refusal that had rested on the deprecated `ST 0601.8-06` to live
  authority without changing its behaviour.

  **`ST 0107.3-05` is what decided the shape of the API.** Because minimality is required rather
  than optional, every length has exactly one conforming encoding — so `encode_ber_length` takes no
  `form=` parameter and the ruling is enforced by the signature. That was the question park 4 was
  sent to answer, and "not free choice" is the answer.

  **PARK 8 STAYS OPEN and is narrower again**, and both things it still owns are **absences** rather
  than delegations. ST 0107.3 never mentions `0x80` as a first *length* octet — a long form declaring
  zero following octets, BER's indefinite length — and it states **no ceiling** on the count of
  length octets, its only maxima (§6.3.3, `ST 0107.3-07`) governing a Value's size. Neither is
  reachable from a conforming stream, which is why the length codec is complete and total with the
  park open; both raise `UnderivableFromPinnedCopy` carrying park 8 and `ST 0107.3-03`. The codec's
  bound of 127 length octets is the first octet's seven bits — **structural, not cited** — and says so.

  **All 141 rows still say `not yet`**, for the third round running and for the same reason: a
  framing rule says where an item begins and never what it means. This adapter went from *can name
  every field and read none* to *can find every item and decode no value*. The three functions that
  raised — `decode_ber_length`, `encode_ber_length`, `walk_local_set` — stopped raising; `LocalSetItem`
  is new; `fixtures/klv/framing/` grew from thirteen fixtures to **twenty-six**, discharging all three
  classes the framing round had named as omitted, with four of the nine new length fixtures being the
  document's **own octets**. `BER_OID_MAX_OCTETS` was **deleted** — a cap beside a codec that no longer
  honours it is a constant nothing reads — while `BER_OID_MAX` is kept at 16383 and re-documented as a
  waypoint rather than a limit.

  Three register entries. **KLV 11** is updated: ST 0107.3's reference [1] pins **ST 336:2017**, so
  the divergence is now three held documents against ST 0102.12's one — a stronger majority and no
  resolution, because ST 0102.12 is the document whose own items are *required* to conform to its
  edition. **KLV 12** is new: two of ST 0107.3's thirteen requirements are prefixed **`ST 0107.2`**,
  not `ST 0107.3`, because MISB stamps a requirement with the edition that introduced it — and one of
  them is the sole octet-order rule in the entire delegation chain, so it is load-bearing and easy to
  miscite. **KLV 13** is new and bounds park 8's cost: §6.3.3.1 names *ASN.1* rather than ST 336 as
  the source of the BER length rules and pins ITU Rec **X.680**, which specifies notation — BER is
  **X.690**. ITU recommendations are free, so part of the one park that costs money may be a
  download. Registered rather than acted on: the reference needs adjudicating and neither ITU
  document is held, and rewriting a park's reopen route on a reference list read in passing is the
  roster change the park 1 round refused to make.

  **A fourth round the same day pointed the codec at a real stream, and it ended in a PARK rather
  than a ruling.** The three rounds above read documents; this one read octets nobody here wrote —
  an MPEG-2 transport stream (SHA-256 `a491ceff…260e`, **102 004 664 bytes**) and the **977-octet**
  KLV extraction taken from it (`a810e4b6…2e51`) with
  `ffmpeg -i day_flight.mpg -map 0:1 -c copy -f data day_flight.klv`, **ffmpeg 9.0.1**, a command
  **re-run rather than recalled** and reproducing those octets byte for byte. **Neither file is
  tracked**, on a *directory* rule (`fixtures/klv/streams/`) rather than the extension rule the
  PDFs use, because a stream has no extension discipline to derive one from. `walk_local_set` reads
  it end to end: **6 packets, 26 items each, 156 items, 0 octets left over, every one of the 162
  length fields minimal, and all 6 checksums validate** — which is what rules out corruption for
  the one thing that does not fit.

  **What does not fit is item 22, Target Width: four octets at all six sites where §8.22 states a
  Required Length of 2**, with the top two octets `0x0000` every time. The round could not classify
  it, and the reason is a finding in its own right. Item 65 declares edition **1**, and the test for
  whether that stamp is trustworthy — does the stream use any item that *postdates* edition 1? —
  **could not be run against anything held**: ST 0601.14a's revision history begins at edition 14
  and ST 0601.19's at edition 19, no item section in either carries an introduction annotation,
  Table 1 has no edition column, and the one dating device the series carries is the
  requirement-identifier prefix, whose **33** instances in ST 0601.14a span editions 8, 9, 10, 13
  and 14 and reach editions 1 through 7 in none of them. So the stamp stands **UNREFUTED**, the
  classification parks with **three** live candidates — a stream defect against `ST 0601.13-29`,
  an edition skew against ST 0601.1's own item-22 entry, or an unknown tag under the declared
  edition — and the deciding fact is one page: **ST 0601.1's tag table**. That is **PARK 13**, the
  first park in this section a *stream* opened rather than a document, reopened by a public NSG
  Registry fetch of a superseded revision on the route park 4 already proved.

  **PARK 13 WAS ADJUDICATED AND CLOSED THE SAME DAY, and the classification is (a), a stream
  defect.** The deciding document was obtained — **MISB EG 0601.1**, because there is no *ST 0601.1*:
  edition 1 is an Engineering Guideline and the series became a Standard at 0601.2, which is register
  entry **KLV 15**. Its tag table states item 22 at a Len of **2**, and states it three times inside
  itself — the Len column, §7.22's format header, and §7.22's worked example `[0d22][0d2][0x1F 9B]`.
  So the two candidates that required edition 1 to *differ* from later editions are dead: **(c)** is
  dead because item 22 is present, in edition 1 and in the initial release before it, and **(b)** is
  dead because edition 1 states 2 rather than 4 or none. **The length never changed** — `uint16`/2 at
  the initial release, edition 1, .4, .8, .14a and .19 — so the emitter's four octets diverge from the
  length its **own declared edition** states, and both readings of the stamp now reach the same
  classification, which is what made (a) assertable. The qualifier is kept rather than buried: at
  edition 1 the divergence is from a *guideline*, so the defect's **factual** basis is edition 1's own
  table and its **normative** basis is `ST 0601.13-29`, the current standard's. Register entry
  **KLV 16** records that edition 1 disagrees with itself and with ST 0601.4 about its own date.
  Register entry
  **KLV 14** records the general form: the format requires an edition stamp on the wire and no held
  edition says which items each edition admits, so the item delta is unbounded in **both**
  directions from what is held.

  **One thing WAS ruled, unconditionally, and it is recorded that way so neither branch reopens
  it.** The framing layer is **correct as shipped**: the four octets arrive behind a valid, minimal,
  short-form BER length, and `walk_local_set` knows no tags at all — a walk that flagged a Required
  Length would be a walk consulting the tag table, which is the one thing it is built not to do. The
  flag is owed by the **value-decoding layer**, which does not exist and is blocked on parks 3, 5,
  11 and 12. **No fixture was written**, and that is part of the ruling rather than an omission:
  there is no codec defect to reproduce, and a synthetic fixture asserting one would encode a
  confusion as a golden file. **Still no gap opened and no field proposed**, and all 141 tag rows
  still read `not yet` — a walk that finds every item in six real packets and validates every
  checksum decodes **no value**.

  **The round's own briefing carried a false premise and it is recorded rather than dropped.** The
  walk was briefed as being over an "ST 0601.8-era" clip. That claim came from the `droneklv`
  README, which states the edition **that library supports** — a fact about a *decoder* — read here
  as a fact about the *emitter*. Withdrawn as a briefing defect, on the same rule that keeps
  settlement 3's corrected epoch premise: a premise that turned out false is evidence about how this
  section reaches conclusions.

  **A second briefing defect is filed beside it, and it is a definition rather than a premise.** The
  adjudication round's briefing defined candidate **(a)** as requiring `ST 0601.13-29` to be normative
  *at the edition the stream declares* — and that round's own Act 2(iii) refuted it, confirming from
  ST 0601.4 §3 that edition 1 is an **Engineering Guideline** whose lengths were direction rather than
  enforceable requirement. A candidate defined that way could never have been assertable. **The
  ruling's factual/normative split supersedes it** — edition 1's table for what the length *is*,
  `ST 0601.13-29` for what a divergence from it *means today* — and `ST 0601.13-29`'s **retroactivity
  stays unestablished**, carried as (a)'s standing annotation rather than shed at closure. **And the
  one unverified lead that round left did not verify.** The held clip's origin is
  `samples.ffmpeg.org`, established by byte identity, and it is **not** MISB; the test-file lead is
  closed as unverifiable from the routes this repository can reach. **Nothing here moves**: no gap
  opened, no field proposed, and the classification never depended on who published the file.

  **Park 9 was not touched, and the observation that might have touched it is filed instead.** PID
  `0x1f1` carries **204** transport packets, each beginning a PES unit, of which **198 carry a PES
  header and no payload at all** and 6 carry payload totalling exactly the 977 octets extracted.
  What a header-only PES unit on a metadata PID means is MISB ST 1402.2's to say, and ST 1402.2 is
  park 9 — not opened, not closed, not narrowed. **Park 8 was not reached either**: `0x80` never
  appears as a first length octet in the 977 octets and no length field exceeds two, so the stream
  is silent on both absences that park owns, which is what "neither is reachable from a conforming
  stream" predicted.

  and **KLV 10**. The fixture directory is `fixtures/klv` rather than
  `fixtures/stanag4609`, the same split that gives adapter `stanag4676` its fixtures in
  `fixtures/nits`, and `tests/test_cdm_harness.py` now carries that as a **planned** map entry
  beside the shipped ones — nine of them when this entry was written, ten since `cat034` landed.

  **Why there is nothing to propose, stated rather than left to inference.** Every absence in that
  row set is a *document this repository does not hold* — thirteen parks over fifteen documents,
  **four closed**, eight of the nine still open being public downloads and one behind SMPTE's paywall —
  and not a CDM shortfall. The fifteenth document is park 13's edition 1, now **held** as
  `EG0601.1.pdf`, and it is **not** a fifteenth *delegated* document: the profile delegates to
  ST 0601.14, that count stays at fourteen, and closing park 13 on a fifteenth document did not move
  it.
  The profile delegates every field dictionary it relies on: `MISP-2015.1-07` sends the KLV
  encoding to SMPTE ST 336:2017, `MISP-2015.1-08` sends the formatting to MISB ST 0107.3, and
  §4.4.4.1 sends the airborne field dictionary to MISB ST 0601.14. A schema proposal derived from
  a document nobody here has read would be a field named after a guess.

  Two places where the CDM genuinely has nowhere to put something turned up, and **both are
  already on the list**, which is the useful result rather than a disappointing one:

  - **Gap 23, an observation whose source states no time**, reached from a second direction. GMTIF
    got there through three segments that state no time *field*; this profile gets there through a
    requirement that does not apply. `MISP-2018.3-116` makes an Absolute Time timestamp mandatory
    on every Motion Imagery **frame** — which this adapter never sees — while `MISP-2018.1-97`
    makes the metadata case *conditional* on a timestamp being present, and the prose introducing
    both is circular: "it is also mandatory for Metadata packets which include a Metadata item for
    a timestamp based on Absolute Time." The two unequivocal predecessors are deprecated. So a
    **conformant** standalone KLV metadata stream may carry no absolute time at all, and §5.5
    contemplates exactly that shape of feed. A format that is *permitted* to state no instant is a
    stronger case for gap 23 than a format whose layout has no field for one, because the second
    can be read as an oversight and the first cannot.
  - **Gap 18, confidence and quality provenance**, reached from the clock rather than from the
    estimate. MISB ST 1603.2 (§4.4.2.12) carries the lock and synchronisation status of the clocks
    in a timing system, and the CDM has nowhere to say how good a source's clock was. Named here
    so whoever opens gap 18 has a second format to cite.

  And one candidate was considered and **rejected as a proposal**: the CDM's `Timestamp` renders
  exactly three decimal places, and this profile names a *Nano* Precision Time Stamp. That is not
  a new question — `FORMAT_COVERAGE.md`'s CAT021 section already settled that a source instant
  finer than the rendering is parked verbatim and re-emitted from the park, with I021/074's
  2⁻³⁰ s ≈ 0.93 ns as a finer case than this one. Adding a field for it would reopen a decision
  that has held for three adapters.

  **One premise carried into the phase was false and is recorded rather than dropped.** The phase
  began from the reading that the MISP fixes the Precision Time Stamp's *epoch*. It does not:
  `epoch`, `microsecond` and `leap` occur zero times in its 73 pages, and the only timescale it
  names it names as an example — "a well-defined reference source, such as International Atomic
  Time (TAI)". The epoch, the resolution and the choice between TAI and UTC are all in MISB
  ST 0603.5, which is park 3 — and if that document says TAI, this adapter inherits a leap-second
  dependency no other adapter here has. That is a 1.1.0 question nobody can ask yet, which is why
  it is a park and not a proposal.

- **`stanag5527` — STANAG 5527, Friendly Force Tracking Systems (FFTS) interoperability. Phase 1:
  the covering document and nothing else — no row set, no adapter code, no codec, no fixtures.**
  `stanag5527` is adapter #9. The ordinal was RESERVED under a different name and the name is what
  changed: it was held for `nffi`, which had no source in any document and none in this repository,
  and the covering document now in hand never uses the term. Under the reserved-ordinal rule the
  number did not move, so `gmti` keeps #8, `stanag4609` keeps #10 and `cat048` keeps #11.

  **This entry is weaker than the one above it and the heading has to admit that.** That heading
  says "row sets written as specifications, with no adapter code yet", and this phase has no row
  set: `FORMAT_COVERAGE.md`'s STANAG 5527 section contains no status column at all, which is a
  stronger statement of absence than a column of `not yet`. It is recorded here anyway, for the
  reason the heading was added in the first place — a Phase 1 that proposes nothing and a Phase 1
  nobody thought about look identical from this file — and the distinction between the two kinds of
  Phase 1 is stated rather than blurred.

  Pinned to one document by SHA-256: **STANAG 5527 Edition 2, 24 April 2025**
  (`2dba2026…a2d30b83`, 319 795 bytes, 5 pages). The PDF is not committed. The fixture directory is
  `fixtures/fft` rather than `fixtures/stanag5527`, the same split that gives adapter `stanag4676`
  its fixtures in `fixtures/nits` and adapter `stanag4609` its own in `fixtures/klv`, and
  `tests/test_cdm_harness.py` now carries that as a second **planned** map entry. **That directory
  ruling is PROVISIONAL** and says so at every site: the covering document supplies a payload noun
  once — nations should add "interfaces to produce/consume FFT data" — and the document that decides
  what the payload really is, ADatP-36 Edition B, is not in hand.

  **The one park now closes down one of two branches, and both are written.** Obtaining ADatP-36
  Edition B and landing a pin were assumed to be one act; they may not be. A third-party standards
  index lists two ADatP-36 records, one carrying a NATO RESTRICTED marking and one — matching
  Edition A — carrying none, and **which edition the marking attaches to is not established**;
  nothing here asserts that Edition B is classified or that it is not. Under **Branch U** the plan
  above is unchanged: a pin in `fixtures/fft/spec/`, identity and hash recorded. Under **Branch R**
  the treatment is **cite-not-carry** — promulgation identity, edition, date and the NSDD
  classification line are recorded, the bytes never enter this repository, no hash of them is taken,
  and a row set would rest on clause citations rather than quotations. The precedent is the AEDP-12
  Edition A (2014) row in `FORMAT_COVERAGE.md`'s NITS pin table, deliberate here and defective there
  — `3e0aed0` recorded that row as "the one line in this pin table that the re-verification below
  could not check", and a cite-not-carry entry records no measurement to leave unchecked. The NSDD
  visit must return **two** facts to unblock the park: the classification line and which version of
  Edition B the copy is. `tests/test_cdm_pins.py` carries the representation ahead of the entry — a
  **cited class**, disjoint from the pin set in both directions, failing loudly if a cited document
  grows bytes on disk, and legal-but-empty today. **This is repository process and not schema
  history**, which is why `docs/docs/changelog.mdx` states none of it.

  **No gap is opened, no field is proposed, and there is nothing to weigh.** The `stanag4609` entry
  above could name two gaps it reached from a new direction because it held a profile; this one
  holds five pages whose only normative act is the name of another document. The word `shall`
  occurs four times in it and not one of the four governs a data element. A schema proposal derived
  from that would not be a field named after a guess — it would be a field named after nothing.

## Proposed for the next MINOR (not yet implemented)

**This heading named 1.1.0 until 1.1.0 shipped without any of it.** The number is dropped rather
than moved to 1.2.0, for the reason this file already records about three pin records that stated
one practice as three different numbers: the durable statement is the property, and "the next
MINOR" is what these items have always meant. A version number here is a promise about scheduling
that nothing in the tree can keep, and it goes stale on exactly the event — a release — that makes
anyone look at this section.

Which release they land in is an open decision and not recorded here. What is recorded is that
1.1.0 is not it.

Both come from `FORMAT_COVERAGE.md`'s gap list, and both are deliberately deferred rather than
added in passing. **Both are now confirmed by a shipped adapter** rather than anticipated — the
TAK adapter parks a real value for each of them on every fixture it translates, which is the
evidence that was missing when they were first written down:

- **`Entity.label`** — a canonical human-readable name. A CoT callsign and a STANAG 4676 track
  number are the strings an operator reads, and today they land in `attributes`, so every
  consumer that wants to label a contact needs private knowledge of which adapter's key to
  look under. Deferred because it needs one owner naming its precedence rules across sources.
- **`Position.alt_accuracy_m`** — vertical accuracy. `accuracy_m` is horizontal only, so CoT's
  `@le` has no home. It matters for air tracks, where a 300 m vertical error decides whether
  two aircraft are deconflicted — and the TAK adapter's `air_track_due_north` fixture is
  exactly that case: `le="120.0"` on a track at 7 620 m, parked at `attributes.vertical_error_m`
  where no consumer will look for it.

- **`Kinematics.heading_deg` and `Kinematics.turn_rate_dpm`**, together and with one owner —
  `FORMAT_COVERAGE.md` gap 7. AIS carries course over ground, true heading and rate of turn as
  three separate measurements; the CDM carries the first and parks the other two. They are
  proposed as a pair because they answer one question between them — where will this be next —
  and a gap opened twice for one concept gets closed twice differently. Whoever implements it
  inherits two sentinels: heading 511 means not available, and rate of turn ±127 means "faster
  than 5° per 30 s", which is a floor, so a `turn_rate_dpm` of 127 would be a fabricated
  measurement rather than a large one.

  **ADS-B is the third adapter to park a heading, and it changes the proposal rather than
  merely confirming it.** An ADS-B heading is referenced to MAGNETIC north unless a type code 31
  frame's HRD bit says otherwise; an AIS true heading is referenced to true north. A bare
  `heading_deg` would hold two different measurements under one name, and magnetic variation in
  the Baltic is around 8° east and a function of place and date — enough to swamp the bow-against-
  track discrepancy the field exists to expose. So the pair becomes a pair plus a datum, and
  whoever implements it inherits a cross-frame join as well: ADS-B cannot state the datum in the
  same frame as the heading.

- **`Track.attributes`** — an extension bag on `Track`, the one canonical object without one.
  `Entity` has `attributes` and `Event` has `payload`; `Track` has `track_id`, `entity_id`,
  `samples` and `track_quality` and nowhere to park anything. The Legion adapter is what makes
  this concrete: a `Track` built from one page of a paginated history is a FRAGMENT, and how much
  of the history it holds — `total_count` against the carried sample count — has to be
  machine-readable or a consumer will compute a speed across a gap it does not know is there.
  Today those figures ride on the `Entity` the track belongs to, keyed by `track_id`, so a
  consumer holding both objects can read them and one holding only the `Track` cannot. The three
  alternatives were all worse: `track_quality` is a 0..1 assessment of how good a track is rather
  than how complete it is, truncating `samples` would discard real data to express a caveat, and
  the model is `extra="forbid"` by design. Whoever adds it should decide at the same time whether
  a *typed* completeness block is better than a free bag, since "how much of this is here" is a
  question every paginated source will ask.
- **`Position.baro_alt_m`** (or `Entity.baro_alt_m` — the choice is part of the work) —
  `FORMAT_COVERAGE.md` gap 9, and the strongest-evidenced of these. `Position.alt_m` is
  documented as metres above the WGS84 ellipsoid, which is what an ADS-B type code 20-22 frame
  states. Type codes 9-18 — the overwhelming majority of an air picture — state a *pressure*
  altitude against the 1013.25 hPa datum instead, and the two differ by hundreds of metres in
  ordinary weather. Every one of them is parked today, so the CDM carries no altitude at all for
  most air tracks, and deconfliction, airspace checks and any comparison against terrain all
  read one. Three things belong in the same change: ADS-B's GNSS-barometric difference field is
  exactly the offset relating the two altitudes; the decision about WHERE the field hangs is
  load-bearing — on `Position` it inherits the requirement of a coordinate, which leaves an
  altitude with no horizontal fix homeless, and this format produces that case constantly; and
  **the datum has to be carried rather than assumed**. `alt_m` says "above the ellipsoid", but a
  DO-260 version 0 transmitter broadcasts GNSS height against mean sea level and DO-260A/B
  against the ellipsoid, with the version living in a different frame. That is gap 7's
  magnetic-versus-true problem in the vertical, and the geoid separation is tens of metres, so it
  is not a rounding matter. The ADS-B adapter asserts the DO-260A/B reading and names both in
  `attributes.altitude_type`; a canonical field would have to do better than assert.

- **A sensor frame — `Position`'s sensor-relative counterpart, plus `Kinematics`'s radial
  component** — `FORMAT_COVERAGE.md` gaps 24 and 25, proposed as **one** change with two fields
  because they are one missing concept. ASTERIX CAT048 is the format that makes the case, and it
  makes it harder than any previous one: it states a target's position as a slant range and an
  azimuth **from a station whose location the format never carries** (§4.3.1 names "the radar site
  location" as the origin; no data item holds it), and its I048/120 states a Doppler speed along
  that same line of sight. `Position` requires both coordinates, so **every CAT048 `Entity` has
  `position: None`** while the record carries 32 bits of range and bearing; `Kinematics.speed_mps`
  is a ground speed, so a target crossing the beam would report zero through it while making three
  hundred knots. Both park today, under keys only that adapter knows, and so do I048/042's
  local-grid Cartesian components and I048/210's per-axis standard deviations in the same grid.

  **Deferred, and blocked on gap 14 rather than on effort.** A sensor-relative position is
  meaningless without a machine-readable identity for the sensor it is relative to, and
  `SourceRef` names the adapter and the system and cannot name the producing sensor. Adding the
  geometry half alone would yield a range and a bearing from an unnamed origin — worse than
  parking it, because it *looks* like a position. Whoever takes this on inherits four constraints
  that are already known: **a slant range is not a ground range**, and §4.3.2.2 concedes the radar
  itself converts using "either the measured height or an assumed target height", so no consumer
  can silently promote a sensor-frame fix either; **the frame's definition can live in a different
  item**, since CAT048 signals which of two transforms produced I048/042 through `TCC` in
  I048/170, so the field must carry *which* frame and not merely *that* it is relative; **the sign
  of a radial speed is undefined by the standard** — §5.2.15 makes it "implementation dependent
  and shall be described in the ICD", with a bare recommendation as the fallback, so this is gap
  7's magnetic-versus-true datum problem in a third axis; and **gap 17 overlaps**, because a
  covariance expressed in a local grid is uncarryable for exactly the reason the position in that
  grid is.

  **Amended after review.** The geometry half of this is no longer a blocker for the adapter: an
  injected `sensor_position` — a constructor argument, the injected-clock precedent — lets CAT048
  derive a geodetic `Position`, so the format is carryable today. What remains proposed is the
  ability to carry the measurement *as a measurement* rather than only its converted product, and
  one concrete sub-item now has a name of its own:

  - **A `PositionSource` member for a sensor measurement.** The enum offers `GNSS`, `INERTIAL`,
    `MANUAL` and `ESTIMATED`, and a monoradar return is none of them. CAT048 writes `ESTIMATED`
    because it is the only value that is not an outright false statement — and because it answers
    the question the enum's docstring says the field exists for, since a radar fix is not `GNSS`
    and survives jamming that a GNSS fix does not. But a direct range-and-bearing measurement,
    converted with a known site, is not an estimate, and every future sensor format will hit the
    same wall. Adding a member is a MINOR bump; naming it is the work, because it has to
    distinguish a *measurement in a sensor frame* from a *fix* without becoming a modality list.

- **A vocabulary for the life of a track** — `FORMAT_COVERAGE.md` gaps 26 and 27, proposed as one
  change because they are the two ends of one missing concept, and both come from CAT048 reversing
  a first draft that had used an existing field for each.

  **Gap 26, the end.** I048/170's `TRE` bit is "End of track lifetime (last report for this
  track)" — the only explicit terminal declaration any source in this document makes. The first
  draft wrote it into `Entity.valid_to`; that is wrong, because `valid_to` is "When it ceased" on
  an object whose `entity_id` is a 24-bit airframe address, while `TRE` ends "a track record within
  a particular track file" (I048/161). Using it would tell every consumer that did not read a basis
  key that the aircraft's state ceased.

  **Gap 27, the identity.** The first draft made I048/161 a `SourceId` when no aircraft address was
  present. That is wrong for the reason CAT021's declines table already gave: a station-scoped,
  recycled 12-bit number keyed into `entity_id` merges two airframes into one entity. Declining it
  costs real continuity — consecutive scans of one PSR track now produce different `entity_id`
  values — and that truncation is the honest price of not making a false statement.

  **Why one change.** A radar track is the smallest complete example of the thing the CDM cannot
  express: it has a start, an identity scoped to one sensor, a confidence (`CNF`, `DOU`) and an
  explicit end, and the CDM can hold none of the four *as such*. Closing only the end would let a
  consumer learn that a track stopped without being able to say which track it was. This is **gap
  15 / gap 19 territory** — a typed relation or a fifth object kind — and `Track.attributes`
  (already proposed above) is the cheap partial move that would at least give the track number and
  the status bits a home on the object they describe rather than on the `Entity` beside it.
  Whoever opens gap 19 should read both rows first.

- **A presentation profile that strips `*_basis` keys** — recorded because the need is real and
  the shape is not settled, and explicitly NOT implemented here.

  ASTERIX CAT048 is the first adapter whose prose outweighs its data: every ruling rides on every
  object as a `*_basis` string, so a golden file for a ONE-record data block runs to roughly 250
  lines. That is deliberate and it stays — the basis strings ARE the audit trail, they are what
  makes "this adapter declined to decide X, and here is the sentence that forced it" survive into
  the objects a consumer holds, and a golden file that did not carry them would let a ruling change
  without a diff. Stripping them from the stored form would be exactly the loss the never-drop rule
  exists to prevent.

  What is missing is a **view**. A map client painting a thousand contacts does not need the
  paragraph explaining why `Position.accuracy_m` is null, and a wire profile that carried it would
  spend most of its bytes on prose. So the proposal is a projection — drop keys matching `*_basis`
  and the `unavailable_fields` / `unresolved_raw` pair — with one hard constraint: **it must be a
  view and never the stored form.** The stripped object must not be what a store keeps, what a
  ledger hashes, or what a golden file records.

  **Cross-adapter, not CAT048's.** Every adapter here emits basis keys and the convention is
  already eight formats deep — `observed_at_basis`, `affiliation_basis`, `position_basis`,
  `symbol_basis`, `severity_basis`, `quality_basis`, `integrity_basis`. Whoever takes it on should
  decide three things at once: whether the projection is a function in the package or a flag on the
  serialiser, whether `attributes.source_extras` goes with it (it is data, not prose, so probably
  not), and whether a stripped object should say that it was stripped — because a consumer that
  cannot tell a basis-free object from an object whose adapter never wrote one has lost the
  distinction the keys exist to make.

Two gaps are recorded in `FORMAT_COVERAGE.md` and deliberately NOT proposed as fields here.
A gap with no proposal is a decision too, and in both cases the decision is "not yet understood
well enough to name a field for":

- **Gap 8, extent.** AIS states four dimensions from the position reference point plus a
  draught, and all of it is parked; but a bounding extent, an offset reference point and a
  draught are three different ideas, and STANAG 4676's own object-size fields should be read
  before any of them is added.
- **Gap 10, air-data speeds.** `Kinematics.speed_mps` is a speed over the ground — what AIS's
  SOG means and what an ADS-B type 19 subtype 1/2 frame states. Subtypes 3 and 4 state an
  indicated or true airspeed instead, and the difference between airspeed and ground speed is
  the wind, which is the fact worth having. It is parked and `speed_mps` is left null on those
  frames rather than filled with a number every consumer would read as a ground speed. Not
  proposed because indicated airspeed, true airspeed and Mach are three related-but-distinct
  quantities and a consumer that wants wind needs gap 7 and its datum as well: adding one
  `airspeed_mps` now would close a third of a question.

None of these is a blocker for an adapter, and that is the point of writing them down rather
than adding them: `attributes` keeps the value, so the cost of the delay is private knowledge in
consumers rather than lost data. When one lands, `tests/test_cdm_format_coverage.py::
test_the_documented_gaps_are_still_gaps` fails deliberately until the document is closed with
it — the gap cannot be fixed in code and left open in the prose.
