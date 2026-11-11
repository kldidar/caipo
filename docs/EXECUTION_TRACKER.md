# Execution Tracker

Status: Progress record, updated with every execution Day · Last updated: 2026-11-11

This file records progress: what is done, what is waiting, and what comes next. **It decides nothing.** Requirements, phases, gates, blocker status, research rules, and architecture decisions are set by [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md), the Accepted ADRs, [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md), and the other documents listed in [CLAUDE.md](../CLAUDE.md). Where this file disagrees with them, they govern and this file is corrected. The rules for working with it are in [CLAUDE.md](../CLAUDE.md), "Execution workflow". It is the only progress tracker.

Statuses: **DONE** (completed and verified), **PARTIAL**, **IN PROGRESS**, **AWAITING OWNER MERGE**, **BLOCKED** (waiting for a named prerequisite or decision), **NOT STARTED** (nothing prevents it), **DEFERRED** (postponed on purpose), **REMOVED** (crossed out, with the reason).

## 0. Delivery sprint (2026-10-30 to 2026-11-06)

On 2026-10-30 the project owner changed how CAIPO is completed (two mandates of that date):

- **Who.** The project owner is the sole owner, operator, and researcher. There is no second reader, no reviewer other than the owner, and no technical team. Engineering, documentation, and bounded source discovery are delegated to Claude Code. The owner's only routine step is to review and merge pull requests; Claude Code never merges.
- **Goal.** A complete, working, polished CAIPO demonstrator for a university professor: a functional Django backend and a distinctive, premium, accessible interface, with seeded data, transparent provenance, and professional documentation.
- **Deadline.** **2026-11-06, 23:59 Asia/Tashkent.**
- **How.** [ADR-0020](adr/0020-demonstrator-track.md) (accepted when the owner merges Day 2) sets the demonstrator track: reduced forms of `sources`, `policies`, `indicators`, and `research` built ahead of the research gates, every record classed `demonstration` (synthetic, synthetic countries only) or `reference` (real public metadata and openly licensed values), metadata only for legal texts, provisional classifications labelled as such. No gate changes status and no blocker closes.

Sprint days are calendar milestones. Execution Days (§5) keep their own sequential numbers.

| Sprint day | Date | Milestone | Execution Days |
|---|---|---|---|
| 1 | Fri 2026-10-30 | Mandate and plan recorded; design system and application shell | 2, 3 (DONE) |
| 2, 3 | Sat 2026-10-31, Sun 2026-11-01 | No execution Day ran: the work waited for the merges of #29 and #30, made on 2026-11-01 | — |
| 4 | Mon 2026-11-02 | Sources and policies, backend and pages together: core corpus and contextual registry, provenance, seed data | 4 |
| 5 | Tue 2026-11-03 | Indicators in three layers, country comparison, charts, coverage | 5 |
| 6 | Wed 2026-11-04 | Research workspace: reproducible analysis runs, search runs, exports | 6 |
| 7 | Thu 2026-11-05 | Polish, accessibility, responsive layout, journey tests, defects | 7 |
| — | Fri 2026-11-06 | Clean-setup verification, README with screenshots, demonstration script, final limitations | 8 |

**Re-plan of 2026-11-02.** Two calendar days passed without a merge, so the plan was compressed: the backend and the pages of sources and policies are one Day (former Days 4 and 5), and every later Day moves up by one. The delivery Day runs on the deadline day itself, so it has no buffer; each Day's pull request may be stacked on the one before it.

**Close-out of 2026-11-04.** Fourteen execution Days were delivered and merged before the deadline, each with the four required checks passing on its merge commit; the last, `ec02751`, ran `4972 passed`. Every item of the owner's acceptance list is met (§12), and the whole walk-through of [DEMO.md](DEMO.md) was rehearsed in a browser from an empty database (Day 14). Day 15 closes the sprint's records. What remains is the post-sprint queue (§5) and the owner's decisions (§10); none of them blocks the demonstration. No gate changed status and no blocker closed: the research decisions that Phase 2 waits for are as open as on 2026-10-30.

**Addition of 2026-11-03.** After trying the demonstrator, the owner asked for two things it did not have: registration on the site, with read-only access at once, and articles that registered people send for the owner's review before publication. Day 11 builds registration ([ADR-0021](adr/0021-registration-for-the-reader-role.md)); Day 12 builds contributed articles ([ADR-0022](adr/0022-contributed-articles.md)), under the licence the owner chose the same day, CC BY 4.0 (Q-15).

Fri 2026-11-06 is the buffer for review, CI, and merges. A Day whose pull request is not merged by its sprint day does not stop the next one: during the sprint, the next Day's branch may be based on the open pull request (ADR-0020 point 17).

## 1. Verified repository state

Verified on 2026-11-11, after the owner's merge of #52.

| Item | Value | How verified |
|---|---|---|
| `origin/main` | `bda7f80`, the merge of #52 (Day 23), after `d00774b` (#51, Day 22), `3a95b93` (#50, Day 21), `331be04` (#49, Day 20), `855faca` (#48, Day 19), `8466dd0` (#47, Day 18), `e3ba938` (#45, Day 17), `26c0839` (#44, Day 16), `bf9c441` (#43, Day 15), `ec02751` (#42, Day 14), `6806c72` (#41, Day 13), `efd4c6b` (#40, Day 12), `be8fb08` (#39, Day 11), `bcb9806` (#38, Day 10), `c66e2d4` (#37, Day 9), `2f42d68` (#36, Days 5 to 8), `9e5e9ea` (#31, Day 4), `5ba91c8` (#30, Day 3), and `7904e36` (#29, Day 2) | `git fetch`; `gh pr view 36` |
| CI on the merges | `7904e36`: run 41352450005, all four checks passed, `4494 passed in 522.91s`. `5ba91c8`: run 41353530141, all four checks passed, `4511 passed in 642.12s`. `9e5e9ea`: run 41405637271, all four checks passed, `4674 passed in 631.67s`. `2f42d68`: run 41409027896, all four checks passed, `4787 passed in 682.99s`. `c66e2d4`: run 41413845532, all four checks passed, `4787 passed in 677.49s`, test job 712 s of its new 1,500 s. `bcb9806`: run 41426022585, all four checks passed, `4807 passed in 684.88s`, test job 721 s. `be8fb08`: run 41669533592, all four checks passed, `4876 passed in 692.82s`. `efd4c6b`: run 41672940236, all four checks passed, `4961 passed in 655.30s`. `6806c72`: run 41772648126, all four checks passed, `4966 passed in 704.52s`. `ec02751`: run 41777689388, all four checks passed, `4972 passed in 745.79s`. `bf9c441`: run 41795974119, all four checks passed, `4972 passed in 714.04s`. `26c0839`: run 41972775585, all four checks passed, `4972 passed in 575.94s`. `e3ba938`: run 41984739241, all four checks passed, `4972 passed in 707.04s`. `8466dd0`: run 41988443568, all four checks passed, `4972 passed in 706.69s`. `855faca`: run 41991928669, all four checks passed, `4972 passed in 580.53s`. `331be04`: run 42036369267, all four checks passed, `4972 passed in 656.30s`. `3a95b93`: run 42041869066, all four checks passed, `5065 passed in 559.74s`. `d00774b`: run 42114738914, all four checks passed, `5086 passed in 739.01s`. `bda7f80`: run 42522827588, all four checks passed, `5086 passed in 741.64s`. The first scheduled weekly dependency audit ran on `bda7f80` on 2026-11-09 and passed (run 42629353857) | `gh run view`; job logs |
| Pull requests | 51 merged, and one closed without merging: #46, opened from the spike's branch `spike/c1-job-isolation`, whose code is never merged (ADR-0011). #1 to #31, #36 to #45, and #47 to #52 were merged into `main`. **#32 to #35 were merged into the branches they were stacked on** (`feat/sources-policies`, `feat/indicators`, `feat/research-workspace`, `feat/polish-quality`), not into `main`, on 2026-11-02 between 07:20 and 07:23 UTC; no CI ran on them, because CI runs only for pull requests into `main`. #36 brought Days 5 to 8 to `main`, merged as `2f42d68`. #40 was built on #39 and opened against `main`; its squash merge restored two tracker rows that Day 12 had deleted and Day 11 had added, which Day 13 deletes again (§11). #50 was opened against `main` carrying #49's commit; after #49's merge it was brought up to date with `main` by a merge commit (`5feb953`), and its squash merge `3a95b93` is identical to that head (`git diff 5feb953 3a95b93` is empty), as #49's merge `331be04` is to its head `82c0260`. #51's merge `d00774b` is identical to its head `8435246`; its first CI run failed Code quality on an import contract, fixed in that head (Day 22). #52's merge `bda7f80` is identical to its head `084c68e`. Open: only the one that changes this file (Day 24) | `gh pr list`; merge bases |
| Protection of `main` | Ruleset "Protect main": pull request required, the four checks required with strict status checks, no bypass | GitHub API, 2026-10-30 |
| Phase and gate | Phase 1. Gate READY for Phase 1, NOT READY for Phase 2 and later. Unchanged by ADR-0020 | [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §10 (authoritative) |
| CI time headroom | The test job took 480 s to 738 s in the 25 successful runs from 2026-10-24 to 2026-11-02; runs of the same 4,494 tests ranged from 480 s to 699 s. Its limit was 900 s; Day 9 raises it to 1,500 s with the owner's approval (§9) | Job start and end times of those runs (`gh run view`) |

## 2. Historical completed work

Work done before execution Days existed has **no Day numbers**.

| Work | Evidence | Outcome |
|---|---|---|
| Foundation documents, development environment, ADR ratification, Django foundation, CI, identity, authentication core, TOTP | 9 direct commits to `main`, `9ea0e61` to `bd7b50a`, 2026-10-01 to 10-03 ([CONTRIBUTING.md](../CONTRIBUTING.md), "History of direct commits to `main`") | Base of Phase 1 |
| Account lifecycle, password reset | #1 to #3 | ADR-0015, ADR-0016 built |
| Recovery from a lost second factor | #4 to #10 | ADR-0017, all six increments built |
| Audit foundation, registry | #11 to #15 | ADR-0018 Increment 1; ADR-0019 Increments 2 and 3 built |
| Diagnostic of 2026-10-20 and its fixes | #16 to #21 | M1 to M4, L1 to L9, I7 fixed or resolved; I1 to I6 open ([report](reports/caipo-full-diagnostic-2026-10-20.md) §20.3) |
| Product Excellence Blueprint | #22, #23 | A proposal; its decisions P-1 to P-14 are open, except as §9 records |
| B22 working model, provisional pilot defaults, pilot clarifications | #24 to #26 | Recorded in the protocol; B22 and O-1 to O-11 stay open |
| Full audit and master roadmap | Prepared on 2026-10-28; accepted by the project owner on 2026-10-30 | Package A1 |
| H1, documentation corrections | #27, merged as `aa51d21` | Package H1 |
| A2, research governance decision pack | Prepared on 2026-10-30 in a terminal session | Its questions are §10. Q-1 and Q-6 answered on 2026-10-30 (§9) |

**Moved from CLAUDE.md on 2026-11-06 (Day 23), as written there.** ADR-0019 Increment 2 was started by the project owner on 2026-10-12, and Increment 3 on 2026-10-20. "At the start of Increment 3 the project owner decided four points: the succession lock of ADR-0018 point 23 also serializes changes of an institution's valid-to date and creations that name a successor, and marking a name locks its institution's row; a name's text is at most 500 characters; the kind of a name is held by a database check as well as by the service; and the Increment 2 tests that described Increment 2 itself are extended, except the one that said the registry package mentions no institution, which is retired."

**Evidence held outside this repository.** These exist only in Claude Code session transcripts on the owner's machine, and are to be placed in the store that package A4 designates: the B8 options brief (2026-10-27), the source-feasibility memos (2026-10-27 and 10-28), and the full audit (2026-10-28). The 2026-10-28 memo also records a process incident: full legal texts were downloaded against the metadata-only rule and then deleted, and the findings that relied on them are marked unverified. None of this evidence is a research finding of the study, and none of it is used as a reference record under ADR-0020 without being found again and verified.

## 3. Overall progress

Counted from the packages in §4. No percentage is estimated.

| Measure | Count |
|---|---|
| Master-roadmap packages | 56 (57 listed, of which G1 is REMOVED) |
| Sprint packages (S1 to S8) | 8 |
| DONE | 25: S1 to S8, and 17 of the master roadmap (A1, A4, A5, B4 as a working basis, C1, C2, D0, E1, F2 and F4 in their demonstrator forms, G2, G3, H1, H2, H3, H4, H6) |
| AWAITING OWNER MERGE | 0; Day 24's pull request is a comparison for the owner's decision Q-17 (I1) |
| Master-roadmap packages IN PROGRESS | 4 (A2, B1, B12, I1) |
| Sprint packages NOT STARTED or BLOCKED on another sprint package | 0 |
| Master-roadmap packages PARTIAL | 6 (A3, E2, E4, F1, G4, J1; §4.2 and §12 say what is missing) |
| Master-roadmap packages BLOCKED | 26 |
| DEFERRED | 3 (D6, G6, G7) |
| Owner decisions pending | 3 (§10: Q-10 in part, Q-14, Q-17) |

Recounted on 2026-11-05 from the tables in §4 (Day 21): the counts above had not followed the packages that Days 16 to 20 moved. The 56 master-roadmap packages are 11 DONE, 3 AWAITING OWNER MERGE, 3 IN PROGRESS, 5 PARTIAL, 31 BLOCKED, and 3 DEFERRED. After the merges of #49 and #50 (Day 22): 14 DONE, 1 AWAITING OWNER MERGE (F1), 3 IN PROGRESS, 5 PARTIAL, 1 NOT STARTED (I1, no longer blocked by C2), 29 BLOCKED, and 3 DEFERRED. With Day 23's pull request open: 14 DONE, 3 AWAITING OWNER MERGE (H2 to H4), 3 IN PROGRESS, 6 PARTIAL (F1 added), 1 NOT STARTED, 26 BLOCKED, and 3 DEFERRED. After the merge of #52 and with Day 24's pull request open: 17 DONE, 4 IN PROGRESS (I1 added), 6 PARTIAL, 26 BLOCKED, and 3 DEFERRED.

## 4. Roadmap and sprint classification

### 4.1 Sprint packages

The owner's mandates of 2026-10-30 add these packages. Each is built under [ADR-0020](adr/0020-demonstrator-track.md), except S2, which is Phase 1 interface work on existing pages.

| ID | Package | Class | Status | Day |
|---|---|---|---|---|
| S1 | Record the mandate, the sprint plan, ADR-0020, and the single-operator facts | MUST | **DONE** (#29, `7904e36`) | 2 |
| S2 | Design system and application shell: tokens, typography, navigation, signed-in home, every existing page restyled; accessibility target (G4, provisional) | MUST | **DONE** (#30, `5ba91c8`) | 3 |
| S3 | Sources and policies backend: Source, Document (metadata only), Policy, AI-related provisions, formal events, corpus assignment; permissions, services, selectors, audit; seed command | MUST | **DONE** (#31, `9e5e9ea`) | 4 |
| S4 | Policy research pages: core corpus and contextual registry kept apart, lists, filters, detail, provenance, forms; bounded discovery of reference metadata for the two study countries | MUST | **DONE** (#31, `9e5e9ea`; merged into Day 4) | 4 |
| S5 | Indicators: three layers, series, releases, observations; openly licensed provider snapshot; comparison with server-rendered charts; coverage and missingness per layer and country | MUST | **DONE** (#32 into its stack branch; on `main` by #36, `2f42d68`) | 5 |
| S6 | Research workspace: reproducible descriptive analysis runs with fingerprints, search runs, CSV and JSON exports with methodology notes | MUST | **DONE** (#33 into its stack branch; on `main` by #36, `2f42d68`) | 6 |
| S7 | Polish and quality: responsive layout, accessibility checks, empty, error, and loading states, journey tests, defects | MUST | **DONE** (#34 into its stack branch; on `main` by #36, `2f42d68`) | 7 |
| S8 | Professor-ready delivery: clean-setup check, README with screenshots, architecture overview, 5 to 10 minute demonstration script, implemented / simulated / future list | MUST | **DONE** (#35 into its stack branch; on `main` by #36, `2f42d68`; [DEMO.md](DEMO.md)) | 8 |

### 4.2 Master roadmap

The master roadmap of 2026-10-28 with every package's status and its sprint class: **MUST** (needed by the deadline), **SHOULD** (fits after the core journeys work), **POST** (after the deadline: research-grade work behind the gates, production hardening, optional work). A POST class removes no requirement: each package keeps its status and prerequisites. **Executor**: *Day*, a Claude Code execution Day; *Owner*, the project owner, who is also the researcher (§9); *External*, a person outside the project.

#### A. Owner decisions and prerequisites

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| A1 | Accept the audit baseline | — | **DONE** | — | Owner |
| A2 | Research governance decisions | POST | IN PROGRESS: Q-1 to Q-8 answered (§9); Day 18 records Q-2, Q-3, Q-5, and Q-8 in the protocol | The remaining OPEN points of the protocol (O-1 to O-11), decided as the pilot proceeds | Owner, then Day |
| A3 | Blueprint §9.2 decisions (at least P-1, P-11, P-13, P-14) | SHOULD | PARTIAL: P-13 answered, P-1 provisional (§9) | P-11, P-14 (Q-10) | Owner |
| A4 | Store for research working records outside this repository | POST | **DONE**: the private repository `kldidar/caipo-research`, created by the owner on 2026-11-05; version 0 of the terminology lists is in it | — | Owner |
| A5 | Phase 1 exit, or its residual items | SHOULD | **DONE** (#49, `331be04`): the owner declared the exit met on 2026-11-05 (Q-11); its residual item, D0, is done | — | Owner, then Day |
| A6 | Housekeeping: old backups (I6), merged branches, local `main`, leftover worktrees, Dependabot | POST | BLOCKED | Q-14 | Owner |

#### B. Research and policy-source methodology

All research work; the owner does it as the researcher. None is needed for the demonstrator, which labels its classifications provisional (ADR-0020 point 8).

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| B1 | Languages, scripts, readers, pilot terminology lists (O-5) | POST | IN PROGRESS: languages, scripts, readers, and the re-check interval decided (§9); version 0 of five lists prepared (Day 19). Next: the owner's first check, then the re-check after 7 days; a reader of Uzbek is sought | The private repository (A4), then the owner's checks | Owner |
| B2 | Run and report the §3.8 pilot | POST | BLOCKED | B1 | Owner |
| B3 | Decide O-1 to O-3 and O-5 to O-10; O-4 after B20 | POST | BLOCKED | B2, A2 | Owner |
| B4 | B8 period design | POST | **DONE** as a working basis, 2010 to 2024 (#47, `8466dd0`); B8 stays open for the research questions (O-11) and O-6 | — | Owner |
| B5 | O-11: revise RQ1 to RQ4 | POST | BLOCKED | B3, B4 | Owner |
| B6 | Close B22 under its confirmed gate | POST | BLOCKED | B1 to B5, B20 (F-15), O-10 | Owner, then Day |
| B7 | B9: inclusion criteria and verified seed list | POST | BLOCKED | B6 | Owner |
| B8 | B10: scanned-share sample and OCR decision | POST | BLOCKED | A recorded right to keep sample files (Q-8) | Owner, Day |
| B9 | B7: rights policy, project-data licence, removal procedure | POST | BLOCKED | A competent rights reviewer (Q-8) | External, Owner |
| B10 | B12: indicator selection and layer assignment | POST | BLOCKED | B6, B9 | Owner |
| B11 | B11 codebook, B23 decision, English prohibited-wording list | POST | BLOCKED | B6. Q-1 is answered: the owner writes the list | Owner |
| B12 | B13 team and B20 ethics review | POST | IN PROGRESS for B20: Q-4 answered, the owner asks an institution now (§9). B13: the team is one person (§9); the self-review rule still needs confirming | The institution's answer | Owner, External |

#### C. Data model and ingestion readiness

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| C1 | Shared B4/B21 spike (job system and worker isolation) | POST | **DONE** (#44, `26c0839`): [report](reports/spike-c1-job-system-and-isolation.md) | — | Day |
| C2 | Decide ADR-0004 and ADR-0011 | POST | **DONE** (#45, `e3ba938`): both accepted by the owner on 2026-11-05 (Q-16) | — | Day, Owner |
| C3 | DATA_MODEL, specification, AI_ARCHITECTURE amendments for F-1 to F-16 | POST | BLOCKED | B3, B6 | Day |
| C4 | ADR for the source of a registry name or date, and a preferred name (I3) | POST | BLOCKED | P-11 (Q-10) | Day, Owner |
| C5 | Phase 2 gate marked READY | POST | BLOCKED | B6, B7, B8, B9, C2, C3 | Owner, Day |

#### D. Backend implementation

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| D0 | Account-administration pages (disable, enable, grant and revoke roles) | SHOULD | **DONE** (#50, `3a95b93`) | — | Day |
| D1 | Phase 2, research-grade: sources, documents, ingestion, fetch guard, parsing, review, rights | POST. A metadata-only demonstrator form is S3 | BLOCKED | C5 | Day |
| D2 | Phase 3, research-grade: policies and indicators | POST. Demonstrator forms are S3, S5 | BLOCKED | D1; B11, B12, B23 | Day |
| D3 | Phase 4, research-grade: claims, evidence, reviews, SearchRun, AnalysisRun | POST. Demonstrator forms of SearchRun and AnalysisRun are S6; claims are not built | BLOCKED | D2; B13, B20 | Day |
| D4 | Phase 5: retrieval, search, assistant, evaluation | POST | BLOCKED | D3; B14, B15, B16, B19, B24; ADR-0003, ADR-0006 | Day |
| D5 | Phase 6, research-grade: comparisons and export | POST. Demonstrator forms are S5, S6 | BLOCKED | D4; B17, B7 | Day |
| D6 | Reader of the audit record (I4) | SHOULD | DEFERRED | ADR-0018, "Not in this milestone" | Day |

#### E. Interface and user journeys

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| E1 | Design foundation on the existing pages (P-13) | MUST, as S2 | **DONE** (#30) | — | Day |
| E2 | Browser checks of the existing pages (diagnostic §12, items 1 to 7) | MUST, within S7 | PARTIAL: every page checked in a headless browser at three widths and both themes (Days 3 to 8); the checks that need an authenticator in hand are not done | Claude Code checks what it can in a local browser; checks that need the owner's authenticator are listed for the owner | Day, Owner |
| E3 | Interface text style guide (P-14) | POST | BLOCKED | A3, B11 | Day |
| E4 | Journeys J1 to J9, workspace and public pages | MUST for the workspace journeys of S3 to S6; POST for the public site | PARTIAL: the workspace journeys are built and tested end to end (`test_journeys.py`); the public site is not | The public site needs P-2 and B7 | Day |

#### F. Analysis and reproducibility

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| F1 | FR-42 shared time axis, with the non-causation notice and the wording check | SHOULD, within S6 if time allows | PARTIAL (#51, `d00774b`): FR-42 (a) to (c) are met on each indicator's page. (d), the prohibited-wording check, waits for the English list the owner writes (B11); a narrower guard on the panel's own words is tested meanwhile | (d): B11 | Day |
| F2 | AnalysisRun with observation counts | MUST, as S6 (demonstrator form) | **DONE** in the demonstrator form (#33, #36) | — | Day |
| F3 | Corpus manifest, data snapshot, rebuild test (FR-61, NFR-05) | POST | BLOCKED | D1, B7 | Day |
| F4 | Coverage per country and layer on every comparison | MUST, as S5 | **DONE** in the demonstrator form (#32, #36) | — | Day |

#### G. Security, testing, accessibility, performance

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| G1 | Coverage measurement, or correct CONTRIBUTING | — | **REMOVED**: H1 corrected CONTRIBUTING | — | — |
| G2 | Scheduled dependency audit, or Dependabot alerts | POST | **DONE** (#49, `331be04`): a weekly run of the existing audit, approved on 2026-11-05 (Q-13); its first scheduled run, on 2026-11-09, passed (run 42629353857) | — | Day |
| G3 | CI time headroom | SHOULD: the sprint adds tests | **DONE** (#37, `c66e2d4`): test job limit 900 s → 1,500 s, by a stated rule. Sharding not needed yet | — | Day |
| G4 | Accessibility target and checks (P-1) | MUST, within S2 and S7 | PARTIAL: automated checks, contrast, reflow at 320 CSS px (400 % zoom), and the accessibility tree are checked (§9); no person has used the pages with a screen reader | — | Day |
| G5 | Phase 2 security tests (fetch guard, parser limits) | POST | BLOCKED | D1 | Day |
| G6 | First performance measurements (NFR-07) | POST | DEFERRED | Real data | Day |
| G7 | Optional: database check for L5; `pre-commit` | POST | DEFERRED | An owner decision, if ever wanted | Day |

#### H. Documentation

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| H1 | Documentation corrections | — | **DONE** (#27, `aa51d21`) | — | Day |
| H2 | One source for status (K9) | POST | **DONE** (#52, `bda7f80`): this file is the only progress record; CLAUDE.md, the specification, ARCHITECTURE.md, and README.md point to it, and the ADR index is the only list of ADR statuses | — | Day |
| H3 | Freeze the diagnostic report; decide where I1 to I6 are tracked | POST | **DONE** (#52, `bda7f80`): frozen as of 2026-11-06; I1, I2, I5 under I2, I3 under C4, I4 under D6, I6 under A6 | — | Day |
| H4 | Recorded self-review in every pull request (K7) | SHOULD | **DONE** (#52, `bda7f80`): `.github/pull_request_template.md` holds the self-review and the local checks, each with its own result | — | Day |
| H5 | Blueprint revision: §10 order, core and contextual journeys, layers A to C | POST. The demonstrator pages keep core and contextual material and the three layers apart (ADR-0020) | BLOCKED | A2 | Day |
| H6 | The execution tracker and the CLAUDE.md workflow rules | — | **DONE** (#28, `ac32fc8`; CI as in §1) | — | Day |

#### I. Deployment and release

All POST: the demonstrator runs locally (ADR-0020 point 3).

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| I1 | B17 and ADR-0008 | POST | IN PROGRESS: the [comparison](reports/deployment-options-2026-11.md) and a concrete ADR-0008 proposal (Day 24) await the owner's decision Q-17; then the purchases in the owner's name, then a deployment Day | Q-17 | Owner, Day |
| I2 | Production hardening (diagnostic I1, I2, I5) | POST | BLOCKED | I1 | Day |
| I3 | Release images, image scan, tags | POST | BLOCKED | I1 | Day |
| I4 | Backups with a restore test, monitoring, runbooks, rollback | POST | BLOCKED | I1 | Day |
| I5 | PostgreSQL collation and locale decided | POST | BLOCKED | I1; before any research data is kept from D1 | Owner, Day |

#### J. Acceptance

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| J1 | Acceptance audit at each completion milestone | MUST for the demonstrator (within S8, against the owner's final acceptance list); POST for the research milestones | PARTIAL: the demonstrator is checked against the owner's acceptance list in §12 | — | Day |

**Critical path of the sprint.** S1 → S3 → S4; S1 → S5; S3 and S5 → S6 → S7 → S8. S2 runs in parallel from the start. **Critical path of the research build** (unchanged, after the sprint): A2 → B1 → B2 → B3 → (B4 → B5) → B6 → C3 → C5 → D1, with B20 before B6 (F-15) and C1 → C2 before C5.

## 5. Execution Days

A Day is one unit of work by Claude Code, with one coherent deliverable and written acceptance criteria. The counter started with Day 1 on 2026-10-30. A Day's number is fixed when it starts.

### Days started

| Day | Objective | Packages | Started | Status | Pull request |
|---|---|---|---|---|---|
| 1 | Reconcile the project state; establish this tracker and the workflow rules | H6 | 2026-10-30 | **DONE**: merged as `ac32fc8`; CI run 41084731032 passed all four checks; `4494 passed` | #28 |
| 2 | Record the delivery mandate, the sprint plan, and ADR-0020 | S1 | 2026-10-30 | **DONE**: merged as `7904e36`; CI run 41352450005 passed all four checks; `4494 passed` | #29 |
| 3 | Design system, application shell, home page | S2, E1 | 2026-10-30 | **DONE**: merged as `5ba91c8`; CI run 41353530141 passed all four checks; `4511 passed` | #30 |
| 4 | Sources and policies: backend, pages, seed data | S3, S4 | 2026-11-02 | **DONE**: merged as `9e5e9ea`; CI run 41405637271 passed all four checks; `4674 passed` | #31 |
| 5 | Indicators in three layers, comparison, coverage | S5, F4 | 2026-11-02 | **DONE**: merged into `feat/sources-policies` by #32, brought to `main` by #36 as `2f42d68`; CI run 41409027896 passed all four checks; `4787 passed` | #32 |
| 6 | Analysis runs, search runs, exports | S6, F2 | 2026-11-02 | **DONE**: merged into `feat/indicators` by #33, brought to `main` by #36 as `2f42d68`; CI run 41409027896 passed all four checks; `4787 passed` | #33 |
| 7 | Polish, accessibility, journey tests | S7, E2, G4 | 2026-11-02 | **DONE**: merged into `feat/research-workspace` by #34, brought to `main` by #36 as `2f42d68`; CI run 41409027896 passed all four checks; `4787 passed` | #34 |
| 8 | Professor-ready delivery: README with screenshots, demonstration guide, clean-setup check | S8, J1 (demonstrator) | 2026-11-02 | **DONE**: merged into `feat/polish-quality` by #35, brought to `main` by #36 as `2f42d68`; CI run 41409027896 passed all four checks; `4787 passed` | #35 |
| 9 | CI headroom, sprint records, acceptance check | G3, J1 | 2026-11-02 | **DONE**: merged as `c66e2d4`; CI run 41413845532 passed all four checks; `4787 passed` | #37 |
| 10 | Translatable refusal messages, reflow at 400 % zoom, accessibility tree | G4 | 2026-11-02 | **DONE**: merged as `bcb9806`; CI run 41426022585 passed all four checks; `4807 passed` | #38 |
| 11 | Registration on the site for the Reader role, and where development messages go | Owner request of 2026-11-03 | 2026-11-03 | **DONE**: merged as `be8fb08`; CI run 41669533592 passed all four checks; `4876 passed` | #39 |
| 12 | Contributed articles, published after review | Owner request of 2026-11-03 | 2026-11-03 | **DONE**: merged as `efd4c6b`; CI run 41672940236 passed all four checks; `4961 passed` | #40 |
| 13 | A page to add an indicator; tracker corrections after the merges of Days 11 and 12 | J1 (acceptance list, item B) | 2026-11-03 | **DONE**: merged as `6806c72`; CI run 41772648126 passed all four checks; `4966 passed` | #41 |
| 14 | Final delivery check: a rehearsal of the demonstration from an empty database, refreshed screenshots, and the defect it found | J1 | 2026-11-04 | **DONE**: merged as `ec02751`; CI run 41777689388 passed all four checks; `4972 passed` | #42 |
| 15 | Sprint close-out: the records of Day 14 and of the owner's check, statements made stale by Days 11 to 14, and the sprint's summary | J1, H1 | 2026-11-04 | **DONE**: merged as `bf9c441`; CI run 41795974119 passed all four checks; `4972 passed` | #43 |
| 16 | The C1 spike: job system and worker isolation (B4, B21), with its report | C1 | 2026-11-04 | **DONE**: merged as `26c0839`; CI run 41972775585 passed all four checks; `4972 passed`. The spike's code is on the branch `spike/c1-job-isolation` (`82f4de6`), never merged | #44 |
| 17 | ADR-0004 and ADR-0011 rewritten as accepted; B4 and B21 closed; the documents that described them as open brought up to date | C2 | 2026-11-05 | **DONE**: merged as `e3ba938`; CI run 41984739241 passed all four checks; `4972 passed` | #45 |
| 18 | The study period, the binding closure gate for B22, and the pilot's rights checks, recorded in the protocol | A2, B4 | 2026-11-05 | **DONE**: merged as `8466dd0`; CI run 41988443568 passed all four checks; `4972 passed` | #47 |
| 19 | Terminology lists for the pilot: languages, scripts, readers, and the re-check interval recorded; version 0 of five lists, with references, prepared for the private store | B1 | 2026-11-05 | **DONE**: merged as `855faca`; CI run 41991928669 passed all four checks; `4972 passed`. Version 0 of the lists pushed to `kldidar/caipo-research` after the owner created it | #48 |
| 20 | A weekly run of the dependency audit (Q-13); the Phase 1 exit recorded (Q-11) | G2, A5 | 2026-11-05 | **DONE**: merged as `331be04`; CI run 42036369267 passed all four checks; `4972 passed` | #49 |
| 21 | Account-administration pages: every account listed; on an account's page its role history, granting and revoking a role with a reason, disabling and enabling | D0 | 2026-11-05 | **DONE**: merged as `3a95b93`; CI run 42041869066 passed all four checks; `5065 passed` | #50 |
| 22 | Formal policy events and indicator values on a shared time axis (FR-42): on each indicator's page, the core AI policies' events of the same countries in a panel of their own above the values, with the non-causation notice and a table of every event | F1 | 2026-11-05 | **DONE**: merged as `d00774b`; CI run 42114738914 passed all four checks; `5086 passed` | #51 |
| 23 | Status in one place (H2), the diagnostic report frozen (H3), and a pull request template with the self-review (H4); CLAUDE.md "Current phase" reduced to its rules, as the owner approved | H2, H3, H4 | 2026-11-06 | **DONE**: merged as `bda7f80`; CI run 42522827588 passed all four checks; `5086 passed` | #52 |
| 24 | Deployment options compared (law on storing personal data, servers abroad and in Uzbekistan, email, domain, backups) and ADR-0008 revised into a concrete proposal, for the owner's decision Q-17 | I1 | 2026-11-11 | AWAITING OWNER MERGE | The pull request that changes this file |

### Planned Days

**Renumbering on 2026-10-30.** The Days planned in #28 as Days 2 to 11 left the numbered queue and are kept, unnumbered, as the post-sprint queue below. **Renumbering on 2026-11-02.** Former Days 4 and 5 are one Day (4); later Days move up by one (§0).

| Day | Sprint day | Objective | Packages | Ready when |
|---|---|---|---|---|

**Post-sprint queue (unnumbered).** Recording the research governance decisions (A2, when Q-2 to Q-5, Q-7, Q-8 are answered); the job-system and isolation spike (C1, Q-9); the Blueprint revision (H5); the ADR-0004 and ADR-0011 decisions (C2); the Phase 1 exit and account-administration pages (A5, D0, Q-11); status consolidation and the self-review practice (H2 to H4, Q-12); CI reliability (G2, G3, Q-13); the ADR for registry name sources (C4); then the research-grade phases behind their gates.

## 6. Checklists

### Day 4: sources and policies, backend and pages

- [x] `sources` and `policies` in their layers, with the data class on every record, database checks, delete-refusing triggers, and append-only policy events
- [x] Services that require `RESEARCH_CONTRIBUTE`, validate, write, and audit in one transaction; selectors that require `WORKSPACE_READ`; formal status derived, never stored
- [x] Pages: policies with the core corpus and the contextual registry on separate tabs, filters, coverage by country; policy page with derived status, events, provisions, provenance, and forms; sources and their documents; creation forms
- [x] Development-only `seed_demo`: demonstration data of two synthetic countries, and verified reference metadata for Uzbekistan and Turkmenistan
- [x] Tests: services, permissions, data-class rules, database rules, pages, seed command
- [x] Visual check at desktop and phone width
- [ ] Full suite; complete diff review; pull request; exact-head CI

Acceptance: no demonstration record can belong to a real country or a reference record to a synthetic one; no text of a reference document can be stored; no policy status is stored; every change is audited; all checks pass on the exact head.

Days 5 to 8 get full checklists when they start; their deliverables are in §4.1.

## 7. Active and pending pull requests

| Pull request | Day | Head | Status |
|---|---|---|---|
| The pull request that changes this file | 24 | Reported when it is opened | Awaiting CI, then the owner's merge |

## 8. Blockers and dependencies

Authoritative status: [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §10 for blockers, [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md) §3.5 to §3.7 for O-1 to O-11 and F-1 to F-16, and §4 of this file for I1 to I6 of the [diagnostic report](reports/caipo-full-diagnostic-2026-10-20.md), which is frozen as of 2026-11-06 (packages I2, C4, D6, A6). This table only points to them, and says what each blocks.

| Open items | Blocks publication of research results | Blocks ingestion of source material | Blocks production deployment | Blocks the demonstrator |
|---|---|---|---|---|
| ~~B4, B21 (job system, isolation)~~ | Closed on 2026-11-05 (ADR-0004, ADR-0011 accepted). Phase 2 still demonstrates the isolation requirements again against its deployed configuration | — | — | — |
| B7 (rights policy) | Yes | Yes | Yes | No: legal texts are metadata only; reference values come only from openly licensed providers |
| B8, B22, O-1 to O-11, F-1 to F-16 | Yes | Yes | — | No: classifications are labelled provisional |
| B9 (seed list), B10 (OCR) | Yes | Yes | — | No: reference records are a labelled sample, not a seed list |
| B11, B12, B23 | Yes | — | — | No: indicator choice and layer assignment are labelled provisional |
| B13, B20 | Yes | — | — | No: no research claims are built. Sensitive security, defence, surveillance, and law-enforcement material is excluded from the demonstrator |
| B14, B15, B16, B19, B24 | Yes (assistant) | — | — | No: no assistant is built |
| B17, ADR-0008, I1 to I6 | — | — | Yes | No: the demonstrator runs locally |

## 9. Decisions settled since the audit

| Date | Decision | By | Recorded in |
|---|---|---|---|
| 2026-10-30 | Q-1: the project owner is also the responsible researcher, and the sole operator. There is no separate research or technical team | Owner (mandate) | This file; [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md) §3 and §12; [LIMITATIONS.md](LIMITATIONS.md) §2.9 |
| 2026-10-30 | Q-6: there is one reader and no second reader. Where the protocol allows one reader, the blind re-check is used, its interval recorded before the first reading, and the limitation stated. No record says an independent second review occurred | Owner (mandate) | Same |
| 2026-10-30 | P-13 (part of Q-10): build the design foundation now, as a distinctive, premium interface | Owner (mandate) | This file; S2 |
| 2026-10-30 | The demonstrator track and the delivery sprint, deadline 2026-11-06 23:59 Asia/Tashkent | Owner (mandate) | [ADR-0020](adr/0020-demonstrator-track.md); §0 |
| 2026-11-02 | **Provisional**, for the demonstrator only: `seed_demo` grants its two accounts their roles through a seeding account that cannot sign in, and writes countries and languages directly, because no verified Administrator exists in a fresh development database. Development only (`DEBUG`) | Claude Code, under the owner's delegation | `caipo/demo`; [DEVELOPMENT.md](DEVELOPMENT.md) |
| 2026-11-02 | ~~**Provisional**: the reasons the demonstrator's services give for a refusal are not yet marked for translation~~ **Closed in Day 10**: every refusal reason of the demonstrator's services and views passes through gettext with named placeholders, the names of fields too; a test reads the code and fails on an untranslated reason or an f-string in one | Claude Code | `caipo/web/tests/test_translatable_refusals.py` |
| 2026-11-02 | Accessibility evidence for the provisional P-1 target (WCAG 2.2 AA): axe-core 4.10.2, run locally from a scratch environment and not added to the project, found **no violation** of the WCAG 2.0, 2.1, and 2.2 A and AA rules or of its best-practice rules on 17 pages in light and in dark mode; text colour pairs were computed at 4.9:1 or more, chart lines at 3.2:1 or more (graphical objects). Keyboard focus is visible; charts have a text alternative in a table. Not checked: screen-reader use by a person, zoom to 400 % on every page | Claude Code | This file |
| 2026-11-02 | Q-13, first part: raise the CI test job's time limit, by as much as is needed and for a stated reason. Set to 25 minutes by the rule "twice the longest successful run, rounded up to five minutes" (738 s), to be recomputed when a run takes more than 1,000 s; written in `.github/workflows/ci.yml` | Owner (approval); Claude Code (the rule and the value) | This file; the workflow |
| 2026-11-02 | Further accessibility evidence (Day 10): at a 320 CSS px viewport, the equivalent of 400 % zoom (WCAG 1.4.10), all 21 pages tried and the open menu reflow without horizontal scrolling, tables and charts excepted, and axe-core finds no violation on any of them. One defect found and fixed: long values in definition lists overflowed their panel by 25 px. The accessibility tree of 13 pages has one banner, one main, one contentinfo, named navigation, one `h1`, no skipped heading level, and no unnamed link, button, image, or field. Chart points no longer take keyboard focus (they were up to about 120 tab stops on a page inside an image); their values are in the table beside each chart. Scrollable table containers take focus so they can be scrolled from the keyboard. Not done: a person using a screen reader | Claude Code | This file |
| 2026-11-03 | Registration on the site: anyone can create an account, which reads the workspace once its email address is verified; to add something, such as an article, a registered person sends it for review, and the owner reads it and decides whether it is published. The owner chose contributed articles written by the person, over proposed sources | Owner | [ADR-0021](adr/0021-registration-for-the-reader-role.md) (registration); Day 12 (articles) |
| 2026-11-03 | Change of CLAUDE.md, "Security requirements": self-registration gives only the Reader role after the email address is verified (ADR-0021); every other role is given by an Administrator. ADR-0021 is added to its list of Accepted ADRs | Owner (approval of that change) | CLAUDE.md |
| 2026-11-03 | Q-15: a contributed article is published under CC BY 4.0; its author keeps the copyright | Owner | [ADR-0022](adr/0022-contributed-articles.md); [RIGHTS_AND_LICENSING.md](RIGHTS_AND_LICENSING.md) §3 |
| 2026-11-03 | Change of CLAUDE.md, "Current phase": contributed articles (ADR-0022) are a second exception to the Phase 1 gate, beside ADR-0020; ADR-0022 is added to the list of Accepted ADRs | Owner (approval of that change) | CLAUDE.md |
| 2026-11-03 | **Provisional**, within ADR-0022: who may send (Reader, Researcher, Reviewer) and who may review (Reviewer and Administrator, with a second factor); five articles a day from one account; the length of each part; a withdrawal after publication; reviewers' own pages, because an Administrator does not read the workspace | Claude Code, under the owner's delegation | ADR-0022; `caipo/accounts/authorization.py` |
| 2026-11-03 | **Provisional**, within ADR-0021: the limits (ten registrations an hour from one source; three verification messages an hour to one waiting account), the three account event types, the Reader grant without an actor, and the note about `data/outbox/` on the registration and password reset pages in development | Claude Code, under the owner's delegation | ADR-0021; `caipo/config/settings/base.py` |
| 2026-11-03 | Accessibility evidence for Days 11 and 12: axe-core 4.10.2 (scratch environment, not added to the project) finds no violation on the registration, sign-in, and home pages at 1280 and 390 CSS px in light and dark mode, nor on the six article pages, including the review pages of a verified Administrator. One defect found and fixed: the navigation of a signed-in account ran past the right edge at 1280 px once "Articles" was added, and an Administrator's already did at 1366 px. Its items now wrap onto a second line, and the tag line under the name gives way beside a navigation below 1500 px; no role's page scrolls sideways at 1181, 1280, 1366, or 1440 px | Claude Code | This file; `caipo/web/static/web/caipo.css` |
| 2026-11-04 | Rehearsal of the demonstration (Day 14), on a database created empty: `check`, `migrate`, and `seed_demo` in 6 seconds; `create_first_administrator` driven at a pseudo-terminal with a code computed from the key it showed; then each step of the walk-through in [DEMO.md](DEMO.md), in a browser: the public home page, the Reader's overview, RP-358 with its derived status, the contextual registry, the demonstration strategy, layers B and C, *Reproduced exactly*, the CSV export, the bounded negative finding, the refusal of a demonstration policy for Turkmenistan and its creation for DEMO Northland, a new analysis run, a registration through the message in `data/outbox/`, an article published by the Administrator, and four pages at phone width in dark mode (no sideways scrolling, no axe-core violation). **One defect found and fixed:** the CSV export of an analysis wrote a negative number as text with a leading apostrophe (`'-6.352022`), against SECURITY.md's rule that numeric cells are not altered; numbers are now written as numbers, and text that begins like a formula is still neutralised. Screenshots in `docs/images/` were taken again, with two new ones (articles, registration) | Claude Code | This file; [DEMO.md](DEMO.md); `caipo/web/exports.py` |
| 2026-11-04 | The check by a person using a screen reader, described to the owner as a walk with Windows Narrator, keyboard only, over the home, sign-in, indicator, article-form, and navigation pages. The owner reported: "Все работает отлично" ("everything works well"). Which pages were walked, and with which screen reader, is not recorded. It is the owner's own check, not an independent audit | Owner | This file; §12, item C |
| 2026-11-05 | Q-11: the Phase 1 exit criterion is met, with D0 (the account-administration pages) as the one residual item, built next | Owner | [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §7 |
| 2026-11-05 | Q-13, the rest: a weekly scheduled run of the existing dependency audit, in a workflow file of its own; a change of the CI configuration approved for that purpose | Owner (approval of that change) | `.github/workflows/dependency-audit.yml` |
| 2026-11-05 | **Provisional**, D0's design: one page per account, from the list of all accounts, with one route for each change (grant, revoke, disable, enable); a reason of at most 1,000 characters; disabling only with a ticked confirmation; no change offered on the Administrator's own account, although the service lets an Administrator disable their own while another remains, because that is not undone from the page | Claude Code, under the owner's delegation | `caipo/web/accounts.py`; [SECURITY.md](../SECURITY.md) |
| 2026-11-05 | **Provisional**, F1's design (FR-42): the events go on each indicator's page, above its values, in a panel and an image of their own on the same scale of years; one mark per country and year, at the year as an annual value is, with the exact dates in the mark's label and in a table of every event; events outside the years charted are listed and counted, not drawn; only policies of the core AI policy corpus and of the indicator's class of data; nothing is computed from events and values together | Claude Code, under the owner's delegation | `caipo/web/charts.py`; `caipo/web/templates/web/indicator.html` |
| 2026-11-05 | Q-12: all three. Status is kept in one place, this file (H2); the diagnostic report of 2026-10-20 is frozen (H3); a pull request template carries the self-review (H4), a change of the repository's configuration approved for that purpose | Owner | Day 23 |
| 2026-11-05 | Deployment: prepare a comparison of hosting options (abroad or in Uzbekistan), price, email service, domain, and the legal requirements on where personal data are stored, ending in a proposal for ADR-0008. Nothing is deployed until the owner accepts it | Owner | I1; the next Day |
| 2026-11-06 | Change of CLAUDE.md, "Current phase": reduced to its rules (the gate, the two exceptions, which ADRs are Proposed, what is not built, the delegation); progress is kept only in this file. The four points of 2026-10-20 that it held are kept in §2 | Owner (approval of that change) | `CLAUDE.md` |
| 2026-11-06 | The delegation of ordinary technical and design decisions continues after the delivery sprint, without an end date, on the same terms | Owner | `CLAUDE.md`, "Current phase" |
| 2026-11-06 | The demonstrator track of ADR-0020 stays open after the sprint, within the same limits, until the Phase 2 gate is READY | Owner | `CLAUDE.md`, "Current phase"; [adr/README.md](adr/README.md) |
| 2026-11-05 | Languages and readers for the pilot (O-5): five languages and scripts, Turkmen in Latin script only; the owner reads Turkmen, Russian, and English; no reader of Uzbek, so Uzbek instruments are assessed on their Russian versions with the translation recorded, while the owner looks for a reader of Uzbek; the re-check interval without a second reader is 7 days | Owner | [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md) §3.7 (O-5); [LIMITATIONS.md](LIMITATIONS.md) §2.5 |
| 2026-11-05 | Q-3 and Q-5: the study period is set first, on grounds independent of AI policy dates, as a working basis: one common window from 2010 to 2024, both included, with a fixed end cutoff. The record states that the demonstrator had displayed indicator values for those years before the choice | Owner | [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md) §3.3 |
| 2026-11-05 | Q-2: the six conditions of protocol §3.5 are the binding closure gate for B22; O-4 waits for B20; with one reader the re-check after an interval is used, with its limitation; B8 closes before B22 or in the same change. F-9 resolved | Owner | [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md) §3.5; [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §10 |
| 2026-11-05 | Q-8: the owner makes and records the pilot's rights checks; an uncertain case is not kept; the competent rights reviewer for B7 is named or commissioned later, and until B7 no text of a legal document is shown publicly | Owner | [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md) §3.8 |
| 2026-11-05 | Q-16: accept the C1 spike's recommendation. ADR-0004 and ADR-0011 are accepted as rewritten: no job library in the isolated workers, whose delivery the trusted side owns in PostgreSQL; `django-tasks` with `django-tasks-db` for trusted work; restricted broker users, internal networks, and an egress proxy for isolation. B4 and B21 close | Owner | [ADR-0004](adr/0004-asynchronous-jobs.md); [ADR-0011](adr/0011-worker-isolation-mechanism.md); [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §10 |
| 2026-11-05 | Change of CLAUDE.md: ADR-0004 and ADR-0011 move to the Accepted list, and architecture rule 13 says the job system is decided in ADR-0004, installed only when Phase 2 builds it, with no Celery or other job system | Owner (approval of that change) | CLAUDE.md |
| 2026-11-04 | Q-9: start the C1 spike now | Owner | Day 16; [the spike report](reports/spike-c1-job-system-and-isolation.md) |
| 2026-11-04 | Q-7: the research working records are kept in a private, version-controlled repository, metadata only, with nothing published until B7 | Owner | A4 |
| 2026-11-04 | Q-4: ask an institution about the ethics review (B20) now; B20 stays a Phase 4 blocker until it answers | Owner | B12 |
| 2026-10-30 | P-1 (part of Q-10), **provisional**: WCAG 2.2 level AA as the accessibility target of the demonstrator's pages, checked in S2 and S7 | Claude Code, under the owner's delegation to choose a reasonable default and record it as provisional | This file. The owner may replace it |

## 10. Decisions awaiting the owner

Recommended defaults are recommendations, not decisions. None of them blocks the demonstrator.

| ID | Decision | Why it matters | Recommended default | Alternatives and consequences | Blocks |
|---|---|---|---|---|---|
| Q-10 (rest) | P-11 (sources of names), P-14 (text style guide); confirm or replace the provisional P-1 | C4 and E3 depend on them | The Blueprint's recommended options | Reject or defer each | A3, C4, E3 |
| Q-14 | Housekeeping | Clutter and stored account data | Item by item; nothing deleted without the owner's word | Keep everything | A6 |
| Q-17 | Deployment: accept the recommendation of the [deployment options report](reports/deployment-options-2026-11.md)? A Hetzner Cloud server in Germany (CPX22, about €20 a month), Brevo's free email plan, and a domain the owner registers | Nothing goes online until it is decided; then the owner buys the server and domain and opens the email account | Accept, with a lawyer's check of the privacy notice and incident procedure before real users register | Pro-Data in Tashkent ($59 a month, data in Uzbekistan); or keep CAIPO local | I1, I2 to I5 |

## 11. Next executable Day

- **Day 24** (the deployment comparison and the ADR-0008 proposal) is the pull request that changes this file. Days 1 to 23 are DONE; the last merge is `bda7f80`.
- **Next:** the owner's decision Q-17. If accepted, the owner buys the server, registers the domain, and opens the email account; Claude Code then writes the deployment configuration (image, Compose file, Caddy, backups, instructions) and the CI image build, which needs the owner's approval as a change of CI.
- **The owner's next steps in the research:** the first check of the Turkmen, Russian, and English terminology lists in `kldidar/caipo-research`, and the re-check at least 7 days later; looking for a reader of Uzbek; the ethics enquiry (B20).
- **Next:** the Phase 2 gate stays NOT READY. Its remaining blockers are research and rights decisions (B7 to B10, B22, and the protocol items), not engineering. The research path now runs through the pilot: the corpus languages and verified terminology lists (B1), then the pilot itself (B2) and the OPEN points it informs (B3). Those are the owner's research work, which Claude Code can prepare. The other open owner decisions are Q-10, in part, and Q-14 (§10). Also queued: whether the bound of twelve apps still holds now that `demo` and `articles` exist ([ARCHITECTURE.md](ARCHITECTURE.md) §2.1).
- **Correction of 2026-11-03.** #40 was built on #39 and opened against `main`. After #39 was squash-merged, the squash merge of #40 kept two rows of this file that Day 11 had added and Day 12 had deleted (the planned Day 12 and the open Q-15). Every other file on `main` is identical to what Day 12's checks ran on (`git diff c3fd485 efd4c6b`). Day 13 deletes the two rows again. A pull request built on another is compared with its own head after both merges.
- **After the merges of Days 11 to 14:** the owner ran `migrate` on the development database; accounts 0013 and 0014 and articles 0001 are applied (checked read-only on 2026-11-04).
- **Nothing remains before 2026-11-06.** The clean-setup rehearsal is done (Day 14), and the owner reported on the screen-reader check (§9).
- **Correction of 2026-11-02, kept for the record.** The stacked pull requests #32 to #35 were merged into their stack branches, not `main`, because GitHub retargets a stacked pull request only when its base branch is deleted. #36 brought their four commits to `main` unchanged. No pull request is stacked from now on unless it is retargeted to `main` by hand before it is merged.
- **Before the demonstration:** the owner reads [DEMO.md](DEMO.md) and runs `seed_demo` on an empty development database.
- **The owner's acceptance list (§12)** is met. An import of values through a page stays out of the demonstrator by ADR-0020 point 3.

## 12. The owner's acceptance list for the demonstrator

The list of the owner's mandate of 2026-10-30, §11, checked on 2026-11-02 against `2f42d68`, and again on 2026-11-04 against `ec02751`. **Met** means it can be shown working, with the evidence named; **partial** says what is missing.

| Item | State | Evidence or what is missing |
|---|---|---|
| A. Clean installation instructions | Met | [README.md](../README.md), "Getting started"; [DEVELOPMENT.md](DEVELOPMENT.md) |
| A. Reproducible local environment | Met | `uv.lock`; Python and service versions pinned; Docker Compose services |
| A. Database setup and migrations | Met | Every migration applied, reversed, and applied again on scratch databases (Days 4 to 6) |
| A. Seeded demonstration environment | Met | `seed_demo` on an empty database in under 3 seconds (Day 8) |
| A. Working authentication | Met | Phase 1, with TOTP for Reviewers and Administrators; demonstration accounts for Researcher and Reader; registration on the site for the Reader role (Day 11) |
| A. Complete primary user journeys | Met | `caipo/web/tests/test_journeys.py`, through the sign-in form on the seeded environment |
| A. Functional backend and frontend | Met | 69 routes, each with a declared access; 4,966 tests passing in CI on `6806c72`; the whole walk-through rehearsed in a browser from an empty database (Day 14) |
| A. Error, empty, and loading states | Met for error and empty states | Error pages; empty states that say an empty list is not evidence of absence. Pages are rendered on the server, so there is no asynchronous loading to show |
| B. Source and provenance management | Met | Sources and documents with publisher, address, access date, terms, permitted use, tier; releases with SHA-256 |
| B. Policy instrument and provision records | Met | Policies, formal events, AI-related provisions with locators |
| B. Core/contextual separation | Met | Separate tabs, a database check on the assignment, a separate export column |
| B. Indicator management with three layers | Met, within ADR-0020 | Indicators in layers A, B, C with values, coverage, and charts. A Researcher adds an indicator, with its layer and the reason for it, on a page (Day 13). Values come only from a provider's release file imported through the services with its hash, because ADR-0020 point 3 builds no upload of datasets |
| B. Country comparison | Met | `/indicators/`, one data class at a time, with coverage per layer and country |
| B. Transparent missingness | Met | Gaps shown as gaps in charts and tables, "n of N years", layer C reported as having no indicator |
| B. Reproducible analytical runs | Met | Fingerprints of inputs and result; the reproducibility check |
| B. Source-linked results | Met | Every input value of a run with its release hash and source |
| B. Export | Met | Analysis CSV and JSON, policy register CSV, with provenance notes; formula injection neutralised |
| C. Unit and integration tests | Met | 4,787 tests |
| C. Critical end-to-end journeys tested | Met, through the Django test client | Not driven through a real browser in CI; the pages were checked in a headless browser by hand |
| C. Four required CI checks passing | Met | Run 41409027896 on `2f42d68` |
| C. Accessibility and responsive layout | Met | axe-core: no WCAG 2.2 A/AA violation on 17 pages in both themes and on 21 pages at 320 CSS px, nor on the pages added by Days 11 to 13; reflow at 400 % zoom checked on every page; accessibility tree checked on 13 pages; the owner's own check with a screen reader on 2026-11-04 (§9), whose details are not recorded. Not an independent accessibility audit |
| C. Security review | Met, as a targeted review of the sprint's code on 2026-11-02 | No unescaped output, no raw SQL, no outbound network call, no CSRF exemption in the new code; every route declares its access; stored addresses limited to `http(s)` by the service and a database check; CSV formula injection neutralised; snapshot files hash-checked and validated; `seed_demo` refuses to run without `DEBUG`. Not a penetration test |
| C. No known critical defects | Met | None known |
| D. Professional interface | Met | The design system; screenshots in the README |
| D. README with screenshots | Met | [README.md](../README.md) |
| D. Architecture explanation | Met | The README diagram; [ARCHITECTURE.md](ARCHITECTURE.md) |
| D. Data and source limitations documented | Met | [LIMITATIONS.md](LIMITATIONS.md) §4.5; [DEMO.md](DEMO.md) |
| D. Demonstration accounts or safe local setup | Met | `seed_demo`, development only |
| D. A 5 to 10 minute demonstration script | Met | [DEMO.md](DEMO.md) |
| D. What is implemented, simulated, and future | Met | [DEMO.md](DEMO.md), "What is real, what is simulated, what is future" |
