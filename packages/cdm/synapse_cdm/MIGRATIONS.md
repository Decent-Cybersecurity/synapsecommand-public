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
2. **All thirteen harnesses are green**, and at least one of them run against the INSTALLED wheel
   rather than the source tree — `gates/wheel_install.py` does both halves and is the gate this
   condition means. The workflow runs it with `--mutation-check`, so the release build also proves
   the gate can still fail. Neither the count nor the roster is written down anywhere that a
   fourteenth adapter would not update: the gate derives it, after a written-down ten replayed ten
   of twelve adapters and reported the ten as a pass.
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
   conditions 1 through 3 it does not wait for a tag. Run it before typing a number:

   ```bash
   python gates/bump_derivation.py --mutation-check
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
git tag -a v1.2.1 -m "..."                           # annotated, never lightweight
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

### Unreleased

**Nothing here is in any release.** The distribution on the index is **1.2.1**, and a reader who
ran `pip install synapse-cdm` does not have what this section describes.

**What moved inside the distribution: this file, and nothing else.** No adapter, no harness flag or
check, no fixture set, no dependency, no importable name — so the arc since `v1.2.1` derives
**PATCH** and the next release is at least **1.2.2**.

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

**And the arc would be NONE without this file.** The only distribution member this round touches is
`MIGRATIONS.md` itself, so the PATCH floor rests entirely on a shipped document moving. Had the
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

**No adapter, no codec and no fixture changed**, so none of the above touches an octet. The register
is a record of what the standards say about themselves, and this round read six PDFs and promoted no
tag row.


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

**What did NOT move.** No park closed and no document was fetched, so the download count stays at
**9 of 10** and the park arithmetic is unchanged in every term — thirteen parks, three closed, ten
open. **All 115 tag rows that read `not yet` still read `not yet`**: this round read six editions and
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
  **three closed**, nine of the ten still open being public downloads and one behind SMPTE's paywall —
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
