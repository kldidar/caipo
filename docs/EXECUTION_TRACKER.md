# Execution Tracker

Status: Progress record, updated with every execution Day · Last updated: 2026-11-02

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

Fri 2026-11-06 is the buffer for review, CI, and merges. A Day whose pull request is not merged by its sprint day does not stop the next one: during the sprint, the next Day's branch may be based on the open pull request (ADR-0020 point 17).

## 1. Verified repository state

Verified on 2026-11-02.

| Item | Value | How verified |
|---|---|---|
| `origin/main` | `5ba91c8`, the merge of #30 (Day 3), after `7904e36`, the merge of #29 (Day 2) | `git fetch`; `gh pr list` |
| CI on the merges | `7904e36`: run 41352450005, all four checks passed, `4494 passed in 522.91s`. `5ba91c8`: run 41353530141, all four checks passed, `4511 passed in 642.12s` | `gh run view`; job logs |
| Pull requests | 30 merged (#1 to #30), none closed without merging. Open: only the one that changes this file (Day 4) | `gh pr list` |
| Protection of `main` | Ruleset "Protect main": pull request required, the four checks required with strict status checks, no bypass | GitHub API, 2026-10-30 |
| Phase and gate | Phase 1. Gate READY for Phase 1, NOT READY for Phase 2 and later. Unchanged by ADR-0020 | [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §10 (authoritative) |
| CI time headroom | The test job took 480 s to 699 s in the runs from 2026-10-25 to 2026-10-30, with 4,494 tests. Its timeout is 900 s. The sprint adds tests, so this is a risk (Q-13) | Job start and end times of those runs |

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
| DONE | 6 (A1, H1, H6, S1, S2, E1) |
| AWAITING OWNER MERGE | 2 (S3 and S4, together in Day 4, #31: CI passed on `184fec4`, `4674 passed`) |
| IN PROGRESS | 1 (S5, Day 5) |
| Sprint packages NOT STARTED or BLOCKED on another sprint package | 3 (S6 to S8) |
| Master-roadmap packages NOT STARTED, nothing preventing them | 2 (E2, G4, within sprint packages) |
| Master-roadmap packages PARTIAL | 1 (A3) |
| Master-roadmap packages BLOCKED | 46 |
| DEFERRED | 3 (D6, G6, G7) |
| Owner decisions pending | 11 (§10) |

## 4. Roadmap and sprint classification

### 4.1 Sprint packages

The owner's mandates of 2026-10-30 add these packages. Each is built under [ADR-0020](adr/0020-demonstrator-track.md), except S2, which is Phase 1 interface work on existing pages.

| ID | Package | Class | Status | Day |
|---|---|---|---|---|
| S1 | Record the mandate, the sprint plan, ADR-0020, and the single-operator facts | MUST | **DONE** (#29, `7904e36`) | 2 |
| S2 | Design system and application shell: tokens, typography, navigation, signed-in home, every existing page restyled; accessibility target (G4, provisional) | MUST | **DONE** (#30, `5ba91c8`) | 3 |
| S3 | Sources and policies backend: Source, Document (metadata only), Policy, AI-related provisions, formal events, corpus assignment; permissions, services, selectors, audit; seed command | MUST | AWAITING OWNER MERGE (#31) | 4 |
| S4 | Policy research pages: core corpus and contextual registry kept apart, lists, filters, detail, provenance, forms; bounded discovery of reference metadata for the two study countries | MUST | AWAITING OWNER MERGE (#31, merged into Day 4) | 4 |
| S5 | Indicators: three layers, series, releases, observations; openly licensed provider snapshot; comparison with server-rendered charts; coverage and missingness per layer and country | MUST | IN PROGRESS | 5 |
| S6 | Research workspace: reproducible descriptive analysis runs with fingerprints, search runs, CSV and JSON exports with methodology notes | MUST | BLOCKED: S3, S5 | 6 |
| S7 | Polish and quality: responsive layout, accessibility checks, empty, error, and loading states, journey tests, defects | MUST | BLOCKED: S3 to S6 | 7 |
| S8 | Professor-ready delivery: clean-setup check, README with screenshots, architecture overview, 5 to 10 minute demonstration script, implemented / simulated / future list | MUST | BLOCKED: S7 | 8 |

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
| E2 | Browser checks of the existing pages (diagnostic §12, items 1 to 7) | MUST, within S7 | NOT STARTED | Claude Code checks what it can in a local browser; checks that need the owner's authenticator are listed for the owner | Day, Owner |
| E3 | Interface text style guide (P-14) | POST | BLOCKED | A3, B11 | Day |
| E4 | Journeys J1 to J9, workspace and public pages | MUST for the workspace journeys of S3 to S6; POST for the public site | BLOCKED: S3 to S6 | The public site needs P-2 and B7 | Day |

#### F. Analysis and reproducibility

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| F1 | FR-42 shared time axis, with the non-causation notice and the wording check | SHOULD, within S6 if time allows | BLOCKED | S5, S6 | Day |
| F2 | AnalysisRun with observation counts | MUST, as S6 (demonstrator form) | BLOCKED | S5 | Day |
| F3 | Corpus manifest, data snapshot, rebuild test (FR-61, NFR-05) | POST | BLOCKED | D1, B7 | Day |
| F4 | Coverage per country and layer on every comparison | MUST, as S5 | BLOCKED | S5 | Day |

#### G. Security, testing, accessibility, performance

| ID | Package | Class | Status | Waits for | Executor |
|---|---|---|---|---|---|
| G1 | Coverage measurement, or correct CONTRIBUTING | — | **REMOVED**: H1 corrected CONTRIBUTING | — | — |
| G2 | Scheduled dependency audit, or Dependabot alerts | POST | BLOCKED | Q-13 | Day |
| G3 | CI time headroom | SHOULD: the sprint adds tests | BLOCKED | Q-13 (any change to the workflow) | Day |
| G4 | Accessibility target and checks (P-1) | MUST, within S2 and S7 | NOT STARTED. Target provisional (§9) | — | Day |
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
| J1 | Acceptance audit at each completion milestone | MUST for the demonstrator (within S8, against the owner's final acceptance list); POST for the research milestones | BLOCKED | S7 | Day |

**Critical path of the sprint.** S1 → S3 → S4; S1 → S5; S3 and S5 → S6 → S7 → S8. S2 runs in parallel from the start. **Critical path of the research build** (unchanged, after the sprint): A2 → B1 → B2 → B3 → (B4 → B5) → B6 → C3 → C5 → D1, with B20 before B6 (F-15) and C1 → C2 before C5.

## 5. Execution Days

A Day is one unit of work by Claude Code, with one coherent deliverable and written acceptance criteria. The counter started with Day 1 on 2026-10-30. A Day's number is fixed when it starts.

### Days started

| Day | Objective | Packages | Started | Status | Pull request |
|---|---|---|---|---|---|
| 1 | Reconcile the project state; establish this tracker and the workflow rules | H6 | 2026-10-30 | **DONE**: merged as `ac32fc8`; CI run 41084731032 passed all four checks; `4494 passed` | #28 |
| 2 | Record the delivery mandate, the sprint plan, and ADR-0020 | S1 | 2026-10-30 | **DONE**: merged as `7904e36`; CI run 41352450005 passed all four checks; `4494 passed` | #29 |
| 3 | Design system, application shell, home page | S2, E1 | 2026-10-30 | **DONE**: merged as `5ba91c8`; CI run 41353530141 passed all four checks; `4511 passed` | #30 |
| 4 | Sources and policies: backend, pages, seed data | S3, S4 | 2026-11-02 | AWAITING OWNER MERGE | #31 |
| 5 | Indicators in three layers, comparison, coverage | S5, F4 | 2026-11-02 | IN PROGRESS (stacked on #31) | The pull request that changes this file |

### Planned Days

**Renumbering on 2026-10-30.** The Days planned in #28 as Days 2 to 11 left the numbered queue and are kept, unnumbered, as the post-sprint queue below. **Renumbering on 2026-11-02.** Former Days 4 and 5 are one Day (4); later Days move up by one (§0).

| Day | Sprint day | Objective | Packages | Ready when |
|---|---|---|---|---|
| 6 | 6 | Analysis runs, search runs, exports | S6, F2 | Day 5 open or merged |
| 7 | 7 | Polish, accessibility, responsive layout, journey tests, defects | S7, E2, G4 | Day 6 open or merged |
| 8 | Deadline day | Professor-ready delivery | S8, J1 (demonstrator) | Day 7 open or merged |

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
| The pull request that changes this file | 4 | Reported when it is opened | Awaiting CI, then the owner's merge |

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
| 2026-11-02 | **Provisional**: the reasons the demonstrator's services give for a refusal are shown in English and are not yet marked for translation; the page around them is | Claude Code, under the owner's delegation | This file; to be closed in Day 7 or after the sprint |
| 2026-10-30 | P-1 (part of Q-10), **provisional**: WCAG 2.2 level AA as the accessibility target of the demonstrator's pages, checked in S2 and S7 | Claude Code, under the owner's delegation to choose a reasonable default and record it as provisional | This file. The owner may replace it |

## 10. Decisions awaiting the owner

Recommended defaults are recommendations, not decisions. Only Q-13 can affect the sprint.

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
| Q-13 | CI timeout headroom; dependency audit between changes | The test job reached 78% of its 900 s timeout, and the sprint adds tests. A timed-out job fails a required check | Raise the test job's timeout to 1,500 s now (one line of `.github/workflows/ci.yml`); a weekly scheduled dependency audit after the sprint | Leave it and accept the risk that a sprint pull request's CI fails on time alone | G2, G3, the sprint's CI |
| Q-14 | Housekeeping | Clutter and stored account data | Item by item; nothing deleted without the owner's word | Keep everything | A6 |

## 11. Next executable Day

- **Day 4** (sources and policies) is in progress; its pull request is the one that changes this file.
- **Day 5** (indicators) starts as soon as Day 4's pull request is open, stacked on it.
- **Q-13** (CI timeout headroom) is still open and is the one decision that can affect the sprint: the test job took 642 s of its 900 s on `5ba91c8`.
