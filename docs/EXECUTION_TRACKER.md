# Execution Tracker

Status: Progress record, updated with every execution Day · Last updated: 2026-11-03

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

**Addition of 2026-11-03.** After trying the demonstrator, the owner asked for two things it did not have: registration on the site, with read-only access at once, and articles that registered people send for the owner's review before publication. Day 11 builds registration ([ADR-0021](adr/0021-registration-for-the-reader-role.md)); Day 12, contributed articles, waits for the owner's choice of licence for a contributed text (Q-15, §10).

Fri 2026-11-06 is the buffer for review, CI, and merges. A Day whose pull request is not merged by its sprint day does not stop the next one: during the sprint, the next Day's branch may be based on the open pull request (ADR-0020 point 17).

## 1. Verified repository state

Verified on 2026-11-03, after the owner's merge of #38.

| Item | Value | How verified |
|---|---|---|
| `origin/main` | `bcb9806`, the merge of #38 (Day 10), after `c66e2d4` (#37, Day 9), `2f42d68` (#36, Days 5 to 8), `9e5e9ea` (#31, Day 4), `5ba91c8` (#30, Day 3), and `7904e36` (#29, Day 2) | `git fetch`; `gh pr view 36` |
| CI on the merges | `7904e36`: run 41352450005, all four checks passed, `4494 passed in 522.91s`. `5ba91c8`: run 41353530141, all four checks passed, `4511 passed in 642.12s`. `9e5e9ea`: run 41405637271, all four checks passed, `4674 passed in 631.67s`. `2f42d68`: run 41409027896, all four checks passed, `4787 passed in 682.99s`. `c66e2d4`: run 41413845532, all four checks passed, `4787 passed in 677.49s`, test job 712 s of its new 1,500 s. `bcb9806`: run 41426022585, all four checks passed, `4807 passed in 684.88s`, test job 721 s | `gh run view`; job logs |
| Pull requests | 38 merged, none closed without merging. #1 to #31 and #36 to #38 were merged into `main`. **#32 to #35 were merged into the branches they were stacked on** (`feat/sources-policies`, `feat/indicators`, `feat/research-workspace`, `feat/polish-quality`), not into `main`, on 2026-11-02 between 07:20 and 07:23 UTC; no CI ran on them, because CI runs only for pull requests into `main`. #36 brought Days 5 to 8 to `main`, merged as `2f42d68`. Open: only the one that changes this file (Day 11) | `gh pr list`; merge bases |
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

**Evidence held outside this repository.** These exist only in Claude Code session transcripts on the owner's machine, and are to be placed in the store that package A4 designates: the B8 options brief (2026-10-27), the source-feasibility memos (2026-10-27 and 10-28), and the full audit (2026-10-28). The 2026-10-28 memo also records a process incident: full legal texts were downloaded against the metadata-only rule and then deleted, and the findings that relied on them are marked unverified. None of this evidence is a research finding of the study, and none of it is used as a reference record under ADR-0020 without being found again and verified.

## 3. Overall progress

Counted from the packages in §4. No percentage is estimated.

| Measure | Count |
|---|---|
| Master-roadmap packages | 56 (57 listed, of which G1 is REMOVED) |
| Sprint packages (S1 to S8) | 8 |
| DONE | 15 (A1, H1, H6, E1, G3, F2 and F4 in their demonstrator forms, S1 to S8) |
| AWAITING OWNER MERGE | 0; Day 11's pull request closes no package by itself |
| Sprint packages NOT STARTED or BLOCKED on another sprint package | 0 |
| Master-roadmap packages PARTIAL | 5 (A3, E2, E4, G4, J1; §12 says what is missing) |
| Master-roadmap packages BLOCKED | 41 |
| DEFERRED | 3 (D6, G6, G7) |
| Owner decisions pending | 11 (§10) |

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
| A2 | Research governance decisions | POST | BLOCKED. Q-1 and Q-6 answered (§9) | Q-2 to Q-5, Q-7, Q-8; then a Day records them in the protocol | Owner, then Day |
| A3 | Blueprint §9.2 decisions (at least P-1, P-11, P-13, P-14) | SHOULD | PARTIAL: P-13 answered, P-1 provisional (§9) | P-11, P-14 (Q-10) | Owner |
| A4 | Store for research working records outside this repository | POST | BLOCKED | Q-7 | Owner |
| A5 | Phase 1 exit, or its residual items | SHOULD | BLOCKED | Q-11 | Owner, then Day |
| A6 | Housekeeping: old backups (I6), merged branches, local `main`, leftover worktrees, Dependabot | POST | BLOCKED | Q-14 | Owner |

#### B. Research and policy-source methodology

All research work; the owner does it as the researcher. None is needed for the demonstrator, which labels its classifications provisional (ADR-0020 point 8).

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| B1 | Languages, scripts, readers, pilot terminology lists (O-5) | POST | BLOCKED | A2, A4. Reader: the owner alone, with the blind re-check (§9) | Owner |
| B2 | Run and report the §3.8 pilot | POST | BLOCKED | B1 | Owner |
| B3 | Decide O-1 to O-3 and O-5 to O-10; O-4 after B20 | POST | BLOCKED | B2, A2 | Owner |
| B4 | B8 period design | POST | BLOCKED | A2 (Q-3, Q-5) | Owner |
| B5 | O-11: revise RQ1 to RQ4 | POST | BLOCKED | B3, B4 | Owner |
| B6 | Close B22 under its confirmed gate | POST | BLOCKED | B1 to B5, B20 (F-15), O-10 | Owner, then Day |
| B7 | B9: inclusion criteria and verified seed list | POST | BLOCKED | B6 | Owner |
| B8 | B10: scanned-share sample and OCR decision | POST | BLOCKED | A recorded right to keep sample files (Q-8) | Owner, Day |
| B9 | B7: rights policy, project-data licence, removal procedure | POST | BLOCKED | A competent rights reviewer (Q-8) | External, Owner |
| B10 | B12: indicator selection and layer assignment | POST | BLOCKED | B6, B9 | Owner |
| B11 | B11 codebook, B23 decision, English prohibited-wording list | POST | BLOCKED | B6. Q-1 is answered: the owner writes the list | Owner |
| B12 | B13 team and B20 ethics review | POST | BLOCKED. B13: the team is one person (§9); the self-review rule still needs confirming. B20 open | Q-4 | Owner, External |

#### C. Data model and ingestion readiness

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| C1 | Shared B4/B21 spike (job system and worker isolation) | POST | BLOCKED | Q-9 | Day |
| C2 | Decide ADR-0004 and ADR-0011 | POST | BLOCKED | C1, then the owner's acceptance | Day, Owner |
| C3 | DATA_MODEL, specification, AI_ARCHITECTURE amendments for F-1 to F-16 | POST | BLOCKED | B3, B6 | Day |
| C4 | ADR for the source of a registry name or date, and a preferred name (I3) | POST | BLOCKED | P-11 (Q-10) | Day, Owner |
| C5 | Phase 2 gate marked READY | POST | BLOCKED | B6, B7, B8, B9, C2, C3 | Owner, Day |

#### D. Backend implementation

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| D0 | Account-administration pages (disable, enable, grant and revoke roles) | SHOULD | BLOCKED | Q-11 | Day |
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
| F1 | FR-42 shared time axis, with the non-causation notice and the wording check | SHOULD, within S6 if time allows | BLOCKED | S5, S6 | Day |
| F2 | AnalysisRun with observation counts | MUST, as S6 (demonstrator form) | **DONE** in the demonstrator form (#33, #36) | — | Day |
| F3 | Corpus manifest, data snapshot, rebuild test (FR-61, NFR-05) | POST | BLOCKED | D1, B7 | Day |
| F4 | Coverage per country and layer on every comparison | MUST, as S5 | **DONE** in the demonstrator form (#32, #36) | — | Day |

#### G. Security, testing, accessibility, performance

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| G1 | Coverage measurement, or correct CONTRIBUTING | — | **REMOVED**: H1 corrected CONTRIBUTING | — | — |
| G2 | Scheduled dependency audit, or Dependabot alerts | POST | BLOCKED | Q-13 | Day |
| G3 | CI time headroom | SHOULD: the sprint adds tests | **DONE** (#37, `c66e2d4`): test job limit 900 s → 1,500 s, by a stated rule. Sharding not needed yet | — | Day |
| G4 | Accessibility target and checks (P-1) | MUST, within S2 and S7 | PARTIAL: automated checks, contrast, reflow at 320 CSS px (400 % zoom), and the accessibility tree are checked (§9); no person has used the pages with a screen reader | — | Day |
| G5 | Phase 2 security tests (fetch guard, parser limits) | POST | BLOCKED | D1 | Day |
| G6 | First performance measurements (NFR-07) | POST | DEFERRED | Real data | Day |
| G7 | Optional: database check for L5; `pre-commit` | POST | DEFERRED | An owner decision, if ever wanted | Day |

#### H. Documentation

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| H1 | Documentation corrections | — | **DONE** (#27, `aa51d21`) | — | Day |
| H2 | One source for status (K9) | POST | BLOCKED | Q-12 | Day |
| H3 | Freeze the diagnostic report; decide where I1 to I6 are tracked | POST | BLOCKED | Q-12 | Day |
| H4 | Recorded self-review in every pull request (K7) | SHOULD. Meanwhile each sprint pull request records its self-review in its description | BLOCKED | Q-12 | Day |
| H5 | Blueprint revision: §10 order, core and contextual journeys, layers A to C | POST. The demonstrator pages keep core and contextual material and the three layers apart (ADR-0020) | BLOCKED | A2 | Day |
| H6 | The execution tracker and the CLAUDE.md workflow rules | — | **DONE** (#28, `ac32fc8`; CI as in §1) | — | Day |

#### I. Deployment and release

All POST: the demonstrator runs locally (ADR-0020 point 3).

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| I1 | B17 and ADR-0008 | POST | BLOCKED | C2 | Owner, Day |
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
| 11 | Registration on the site for the Reader role, and where development messages go | Owner request of 2026-11-03 | 2026-11-03 | AWAITING OWNER MERGE | The pull request that changes this file |

### Planned Days

**Renumbering on 2026-10-30.** The Days planned in #28 as Days 2 to 11 left the numbered queue and are kept, unnumbered, as the post-sprint queue below. **Renumbering on 2026-11-02.** Former Days 4 and 5 are one Day (4); later Days move up by one (§0).

| Day | Sprint day | Objective | Packages | Ready when |
|---|---|---|---|---|
| 12 | 2026-11-04 | Contributed articles: a registered Reader writes an article and sends it for review; the owner reads it and publishes or declines it, with a reason; published articles are labelled as their author's, not as CAIPO's findings. A further ADR | Owner request of 2026-11-03 | Day 11 merged; Q-15 (licence of a contributed text) answered |

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
| The pull request that changes this file | 11 | Reported when it is opened | Awaiting CI, then the owner's merge |

## 8. Blockers and dependencies

Authoritative status: [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §10 for blockers, [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md) §3.5 to §3.7 for O-1 to O-11 and F-1 to F-16, the [diagnostic report](reports/caipo-full-diagnostic-2026-10-20.md) §20.3 for I1 to I6. This table only points to them, and says what each blocks.

| Open items | Blocks publication of research results | Blocks ingestion of source material | Blocks production deployment | Blocks the demonstrator |
|---|---|---|---|---|
| B4, B21 (job system, isolation) | — | Yes | Yes | No: no ingestion or jobs are built |
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
| 2026-11-03 | **Provisional**, within ADR-0021: the limits (ten registrations an hour from one source; three verification messages an hour to one waiting account), the three account event types, the Reader grant without an actor, and the note about `data/outbox/` on the registration and password reset pages in development | Claude Code, under the owner's delegation | ADR-0021; `caipo/config/settings/base.py` |
| 2026-10-30 | P-1 (part of Q-10), **provisional**: WCAG 2.2 level AA as the accessibility target of the demonstrator's pages, checked in S2 and S7 | Claude Code, under the owner's delegation to choose a reasonable default and record it as provisional | This file. The owner may replace it |

## 10. Decisions awaiting the owner

Recommended defaults are recommendations, not decisions. None of them blocks the demonstrator.

| ID | Decision | Why it matters | Recommended default | Alternatives and consequences | Blocks |
|---|---|---|---|---|---|
| Q-2 | Confirm the six conditions of protocol §3.5 as the binding B22 closure gate (F-9)? | Without a confirmed gate, B22 could be closed on the shorter specification row | Confirm all six as written; O-4 needs B20; the single-reader re-check is allowed with its limitation; B8 closes first or in the same change | Change conditions in a reviewed protocol change | B6, Phase 2 |
| Q-3 | Order of B22 and B8 | They depend on each other | (a) Split the B8 work: set the period first, on grounds independent of AI policy dates, before any indicator values are examined | (b) close B8 and O-11 with B22; (c) a pilot-only period; (d) protocol dependencies govern | B4, B5, H5 |
| Q-4 | When is B20 answered (F-15)? And which institution, if any? | B22 cannot close until B20 is answered | (a) Ask the institution now; B20 stays a Phase 4 blocker | Waiting keeps Phase 2 blocked | B12, B6 |
| Q-5 | B8 working basis and closure test | Fixes how the period is chosen before data is seen | P1, one common window, as a working basis only; a fixed end cutoff; the start reason recorded before values are examined | Keep P1 and P3 both open; or P3 | B4 |
| Q-7 | Where are pilot records and other working records kept? | The protocol keeps them outside this public repository (O-10) | A private, version-controlled repository; metadata records only; nothing published until B7 | A local repository with a backup | A4, B1, B2 |
| Q-8 | Who makes the pilot's rights checks, and who is the competent rights reviewer for B7? | Files may be kept for the pilot only after a recorded check | The owner makes and records the pilot checks, and an uncertain case is not kept; the owner names or commissions the B7 reviewer | A named rights adviser | B2, B8, B9 |
| Q-9 | Start the C1 spike? | Phase 2 gate work | After the sprint | Defer longer | C1, C2 |
| Q-10 (rest) | P-11 (sources of names), P-14 (text style guide); confirm or replace the provisional P-1 | C4 and E3 depend on them | The Blueprint's recommended options | Reject or defer each | A3, C4, E3 |
| Q-11 | Phase 1 exit: declare it met, with D0 as a residual item? | No document declares Phase 1 complete | Declare the exit met, with D0 residual | Keep Phase 1 open until D0 is built | A5, D0 |
| Q-12 | Status consolidation, freezing the diagnostic report, a pull request template | Status is narrated in about seven places | Approve all three after the sprint | Approve some | H2, H3, H4 |
| Q-13 (rest) | A dependency audit between changes | No scheduled audit exists; vulnerabilities published between pull requests are found only at the next one | A weekly scheduled run of the existing dependency audit in CI | Dependabot alerts (a repository setting) | G2 |
| Q-15 | Under which licence is a contributed article published? | A published text is used by others; CAIPO needs the author's permission in a stated form before it shows the text to anyone | The author keeps the copyright and publishes under CC BY 4.0, accepted by a checkbox when the article is sent; the article page shows the licence and the author's name | CC BY-NC 4.0 (no commercial reuse); or all rights reserved with a licence to CAIPO to show it only, which allows no reuse by readers | Day 12 |
| Q-14 | Housekeeping | Clutter and stored account data | Item by item; nothing deleted without the owner's word | Keep everything | A6 |

## 11. Next executable Day

- **Day 11** (registration on the site for the Reader role, ADR-0021) is the pull request that changes this file. Day 10 is DONE (`bcb9806`).
- **Day 12** (contributed articles with the owner's review) starts when Day 11 is merged and Q-15 is answered.
- **Correction of 2026-11-02, kept for the record.** The stacked pull requests #32 to #35 were merged into their stack branches, not `main`, because GitHub retargets a stacked pull request only when its base branch is deleted. #36 brought their four commits to `main` unchanged. No pull request is stacked from now on unless it is retargeted to `main` by hand before it is merged.
- **Before the demonstration:** the owner reads [DEMO.md](DEMO.md) and runs `seed_demo` on an empty development database.
- **What remains of the owner's acceptance list (§12):** a page to add an indicator (an import of values stays out of the demonstrator by ADR-0020 point 3), and a check by a person using a screen reader. Then the post-sprint queue (§5).

## 12. The owner's acceptance list for the demonstrator

The list of the owner's mandate of 2026-10-30, §11, checked on 2026-11-02 against `2f42d68`. **Met** means it can be shown working, with the evidence named; **partial** says what is missing.

| Item | State | Evidence or what is missing |
|---|---|---|
| A. Clean installation instructions | Met | [README.md](../README.md), "Getting started"; [DEVELOPMENT.md](DEVELOPMENT.md) |
| A. Reproducible local environment | Met | `uv.lock`; Python and service versions pinned; Docker Compose services |
| A. Database setup and migrations | Met | Every migration applied, reversed, and applied again on scratch databases (Days 4 to 6) |
| A. Seeded demonstration environment | Met | `seed_demo` on an empty database in under 3 seconds (Day 8) |
| A. Working authentication | Met | Phase 1, with TOTP for Reviewers and Administrators; demonstration accounts for Researcher and Reader; registration on the site for the Reader role (Day 11) |
| A. Complete primary user journeys | Met | `caipo/web/tests/test_journeys.py`, through the sign-in form on the seeded environment |
| A. Functional backend and frontend | Met | 62 routes, each with a declared access; 4,807 tests passing in CI on `bcb9806` |
| A. Error, empty, and loading states | Met for error and empty states | Error pages; empty states that say an empty list is not evidence of absence. Pages are rendered on the server, so there is no asynchronous loading to show |
| B. Source and provenance management | Met | Sources and documents with publisher, address, access date, terms, permitted use, tier; releases with SHA-256 |
| B. Policy instrument and provision records | Met | Policies, formal events, AI-related provisions with locators |
| B. Core/contextual separation | Met | Separate tabs, a database check on the assignment, a separate export column |
| B. Indicator management with three layers | Partial | Indicators in layers A, B, C with values, coverage, and charts. No page adds an indicator or imports a release: imports run through the services from committed files, because ADR-0020 point 3 builds no upload of datasets |
| B. Country comparison | Met | `/indicators/`, one data class at a time, with coverage per layer and country |
| B. Transparent missingness | Met | Gaps shown as gaps in charts and tables, "n of N years", layer C reported as having no indicator |
| B. Reproducible analytical runs | Met | Fingerprints of inputs and result; the reproducibility check |
| B. Source-linked results | Met | Every input value of a run with its release hash and source |
| B. Export | Met | Analysis CSV and JSON, policy register CSV, with provenance notes; formula injection neutralised |
| C. Unit and integration tests | Met | 4,787 tests |
| C. Critical end-to-end journeys tested | Met, through the Django test client | Not driven through a real browser in CI; the pages were checked in a headless browser by hand |
| C. Four required CI checks passing | Met | Run 41409027896 on `2f42d68` |
| C. Accessibility and responsive layout | Partial | axe-core: no WCAG 2.2 A/AA violation on 17 pages in both themes and on 21 pages at 320 CSS px; reflow at 400 % zoom checked on every page; accessibility tree checked on 13 pages (§9). Not done: a person using a screen reader |
| C. Security review | Met, as a targeted review of the sprint's code on 2026-11-02 | No unescaped output, no raw SQL, no outbound network call, no CSRF exemption in the new code; every route declares its access; stored addresses limited to `http(s)` by the service and a database check; CSV formula injection neutralised; snapshot files hash-checked and validated; `seed_demo` refuses to run without `DEBUG`. Not a penetration test |
| C. No known critical defects | Met | None known |
| D. Professional interface | Met | The design system; screenshots in the README |
| D. README with screenshots | Met | [README.md](../README.md) |
| D. Architecture explanation | Met | The README diagram; [ARCHITECTURE.md](ARCHITECTURE.md) |
| D. Data and source limitations documented | Met | [LIMITATIONS.md](LIMITATIONS.md) §4.5; [DEMO.md](DEMO.md) |
| D. Demonstration accounts or safe local setup | Met | `seed_demo`, development only |
| D. A 5 to 10 minute demonstration script | Met | [DEMO.md](DEMO.md) |
| D. What is implemented, simulated, and future | Met | [DEMO.md](DEMO.md), "What is real, what is simulated, what is future" |
