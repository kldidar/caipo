# Execution Tracker

Status: Progress record, updated with every execution Day · Last updated: 2026-10-30

This file records the progress of the master roadmap: what is done, what is waiting, and what comes next. **It decides nothing.** Requirements, phases, gates, blocker status, research rules, and architecture decisions are set by [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md), the Accepted ADRs, [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md), and the other documents listed in [CLAUDE.md](../CLAUDE.md). Where this file disagrees with them, they govern and this file is corrected. The rules for working with it are in [CLAUDE.md](../CLAUDE.md), "Execution workflow". It is the only progress tracker.

Statuses: **DONE** (completed and verified), **PARTIAL**, **AWAITING OWNER MERGE**, **BLOCKED** (waiting for a named prerequisite or decision), **NOT STARTED** (approved, nothing prevents it), **DEFERRED** (postponed on purpose), **REMOVED** (crossed out, with the reason).

## 1. Verified repository state

Verified on 2026-10-30.

| Item | Value | How verified |
|---|---|---|
| `origin/main` | `aa51d21fe7912365350fc2443565d60e0f8c608b`, the merge of #27 | `git fetch`; `gh pr view 27` |
| CI on `aa51d21` | Run 41024056944 (push): Code quality, Django checks and tests, Dependency audit, Secret scan all passed; `4494 passed in 636.59s` | `gh run view`; job log |
| Pull requests | 27 merged (#1 to #27), none closed without merging. Open: only the one that adds this file | `gh pr list` |
| Protection of `main` | Ruleset "Protect main": pull request required, the four checks required with strict status checks, no bypass | GitHub API, 2026-10-30 |
| Phase and gate | Phase 1. Gate READY for Phase 1, NOT READY for Phase 2 and later | [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §10 (authoritative) |
| CI time headroom | The test job took 480 s to 699 s in the 12 runs from 2026-10-25 to 2026-10-30, with the same 4,494 tests. Its timeout is 900 s | Job start and end times of those runs |

## 2. Historical completed work

Work done before this tracker existed. It has **no Day numbers**: no day-by-day record of it exists, and none is reconstructed.

| Work | Evidence | Outcome |
|---|---|---|
| Foundation documents, development environment, ADR ratification, Django foundation, CI, identity, authentication core, TOTP | 9 direct commits to `main`, `9ea0e61` to `bd7b50a`, 2026-10-01 to 10-03 ([CONTRIBUTING.md](../CONTRIBUTING.md), "History of direct commits to `main`") | Base of Phase 1 |
| Account lifecycle, password reset | #1 to #3 | ADR-0015, ADR-0016 built |
| Recovery from a lost second factor | #4 to #10 | ADR-0017, all six increments built |
| Audit foundation, registry | #11 to #15 | ADR-0018 Increment 1; ADR-0019 Increments 2 and 3 built |
| Diagnostic of 2026-10-20 and its fixes | #16 to #21 | M1 to M4, L1 to L9, I7 fixed or resolved; I1 to I6 open ([report](reports/caipo-full-diagnostic-2026-10-20.md) §20.3) |
| Product Excellence Blueprint | #22, #23 | A proposal; its decisions P-1 to P-14 are open |
| B22 working model, provisional pilot defaults, pilot clarifications | #24 to #26 | Recorded in the protocol; B22 and O-1 to O-11 stay open |
| Full audit and master roadmap | Prepared on 2026-10-28; accepted by the project owner, who on 2026-10-30 named it "the approved CAIPO master roadmap" | Package A1 |
| H1, documentation corrections (K5, K6, K8, K10, K11, Blueprint §11) | #27, merged as `aa51d21`; CI as in §1 | Package H1 |
| A2, research governance decision pack | Prepared on 2026-10-30 in a terminal session | Its eight questions are §10, Q-1 to Q-8. No answer recorded yet |

**Evidence held outside this repository.** These exist only in Claude Code session transcripts on the owner's machine, and are to be placed in the store that package A4 designates: the B8 options brief (2026-10-27), the source-feasibility memos (2026-10-27 and 10-28), and the full audit (2026-10-28). The 2026-10-28 memo also records a process incident: full legal texts were downloaded against the metadata-only rule and then deleted, and the findings that relied on them are marked unverified. None of this evidence is a research finding of the study.

## 3. Overall progress

Counted from the approved packages in §4. No percentage is estimated.

| Measure | Count |
|---|---|
| Approved packages | 56 (57 listed, of which G1 is REMOVED) |
| DONE | 2 (A1, H1) |
| Remaining | 54 |
| AWAITING OWNER MERGE | 1 (H6) |
| BLOCKED | 50 |
| NOT STARTED, nothing preventing it | 0 |
| DEFERRED | 3 (D6, G6, G7) |
| Owner decisions pending | 14 (§10, Q-1 to Q-14) |

## 4. Corrected master roadmap

The master roadmap of 2026-10-28 with every package's verified status. **Executor**: *Day*, a Claude Code execution Day; *Owner*; *Researcher*; *External*, a person outside the project. Changes since 2026-10-28: A1 and H1 are DONE; A2 is prepared; G1 is REMOVED, because H1 corrected the text it offered as an alternative; H6 is added; G3 is updated by the measurement in §1.

### A. Owner decisions and prerequisites

| ID | Package | Status | Waits for | Executor |
|---|---|---|---|---|
| A1 | Accept the audit baseline | **DONE** | — | Owner |
| A2 | Research governance decisions | **BLOCKED**: prepared, waiting for the owner's decisions | Q-1 to Q-8; then Day 2 records them | Owner, then Day |
| A3 | Blueprint §9.2 decisions (at least P-1, P-11, P-13, P-14) | BLOCKED | Q-10 | Owner |
| A4 | Store for research working records outside this repository | BLOCKED | Q-7 (decides the location); then the researcher places the evidence of §2 there | Owner, Researcher |
| A5 | Phase 1 exit, or its residual items | BLOCKED | Q-11 | Owner, then Day |
| A6 | Housekeeping: old backups (I6), merged branches, local `main`, leftover worktrees, Dependabot | BLOCKED | Q-14 | Owner |

### B. Research and policy-source methodology

| ID | Package | Status | Waits for | Executor |
|---|---|---|---|---|
| B1 | Languages, scripts, readers, pilot terminology lists (O-5) | BLOCKED | A2, A4, readers (Q-6) | Researcher |
| B2 | Run and report the §3.8 pilot | BLOCKED | B1 | Researcher |
| B3 | Decide O-1 to O-3 and O-5 to O-10; O-4 after B20 | BLOCKED | B2, A2 | Researcher, Owner |
| B4 | B8 period design (structure, start reason, end rule, date convention, observations before the period) | BLOCKED | A2 (Q-3, Q-5) | Researcher |
| B5 | O-11: revise RQ1 to RQ4 | BLOCKED | B3, B4 | Researcher |
| B6 | Close B22 under its confirmed gate | BLOCKED | B1 to B5, B20 (F-15), O-10 | Owner, then Day |
| B7 | B9: inclusion criteria and verified seed list | BLOCKED | B6 | Researcher |
| B8 | B10: scanned-share sample and OCR decision | BLOCKED | A recorded right to keep sample files (Q-8) | Researcher, Day |
| B9 | B7: rights policy, project-data licence, removal procedure | BLOCKED | A competent rights reviewer (Q-8) | External, Owner |
| B10 | B12: indicator selection and layer assignment | BLOCKED | B6, B9 | Researcher |
| B11 | B11 codebook, B23 decision, English prohibited-wording list | BLOCKED | B6 (codebook); Q-1 (who writes the wording list) | Researcher, Owner |
| B12 | B13 team and B20 ethics review | BLOCKED | Q-4, Q-6 | Researcher, External |

### C. Data model and ingestion readiness

| ID | Package | Status | Waits for | Executor |
|---|---|---|---|---|
| C1 | Shared B4/B21 spike (job system and worker isolation) | BLOCKED | Q-9 (the owner starts it, with boundaries) | Day |
| C2 | Decide ADR-0004 and ADR-0011 | BLOCKED | C1, then the owner's acceptance | Day, Owner |
| C3 | DATA_MODEL, specification, AI_ARCHITECTURE amendments for F-1 to F-16 | BLOCKED | B3, B6 | Day |
| C4 | ADR for the source of a registry name or date, and a preferred name (I3) | BLOCKED | A3 (P-11) | Day, Owner |
| C5 | Phase 2 gate marked READY | BLOCKED | B6, B7, B8, B9, C2, C3 | Owner, Day |

### D. Backend implementation

| ID | Package | Status | Waits for | Executor |
|---|---|---|---|---|
| D0 | Account-administration pages (disable, enable, grant and revoke roles) | BLOCKED | A5 (Q-11) | Day |
| D1 | Phase 2: sources, documents, ingestion, fetch guard, parsing, review, rights | BLOCKED | C5 | Day |
| D2 | Phase 3: policies and indicators | BLOCKED | D1; B11, B12, B23 | Day |
| D3 | Phase 4: claims, evidence, reviews, SearchRun, AnalysisRun | BLOCKED | D2; B13, B20 | Day |
| D4 | Phase 5: retrieval, search, assistant, evaluation | BLOCKED | D3; B14, B15, B16, B19, B24; ADR-0003, ADR-0006 | Day |
| D5 | Phase 6: comparisons and export | BLOCKED | D4; B17, B7 | Day |
| D6 | Reader of the audit record (I4) | DEFERRED | ADR-0018, "Not in this milestone" | Day |

### E. Interface and user journeys

| ID | Package | Status | Waits for | Executor |
|---|---|---|---|---|
| E1 | Design foundation on the existing pages (P-13) | BLOCKED | A3 (Q-10) | Day |
| E2 | Browser checks of the existing pages (diagnostic §12, items 1 to 7) | BLOCKED | The owner, with a browser and an Administrator signed in with a second factor | Owner, Day |
| E3 | Interface text style guide (P-14) | BLOCKED | A3, B11 | Day |
| E4 | Journeys J1 to J9, workspace and public pages | BLOCKED | H5; the phase of each journey; P-2 and B7 for the public site | Day |

### F. Analysis and reproducibility

| ID | Package | Status | Waits for | Executor |
|---|---|---|---|---|
| F1 | FR-42 shared time axis, with the non-causation notice and the wording check | BLOCKED | D2, D3, B11 | Day |
| F2 | AnalysisRun with observation counts; sensitivity input for contextual material (F-4) | BLOCKED | D3 | Day |
| F3 | Corpus manifest, data snapshot, rebuild test (FR-61, NFR-05) | BLOCKED | D1, B7 | Day |
| F4 | Coverage per country and layer on every comparison | BLOCKED | D3, D5 | Day |

### G. Security, testing, accessibility, performance

| ID | Package | Status | Waits for | Executor |
|---|---|---|---|---|
| G1 | Coverage measurement, or correct CONTRIBUTING | **REMOVED**: H1 corrected CONTRIBUTING. Adding a coverage tool would be a new decision with a dependency justification | — | — |
| G2 | Scheduled dependency audit, or Dependabot alerts | BLOCKED | Q-13 | Day |
| G3 | CI time headroom | BLOCKED. The headroom is smaller than the audit recorded (§1) | Q-13 (any change to the workflow) | Day |
| G4 | Accessibility target and checks (P-1) | BLOCKED | A3 (Q-10) | Day |
| G5 | Phase 2 security tests (fetch guard, parser limits) | BLOCKED | D1 | Day |
| G6 | First performance measurements (NFR-07) | DEFERRED | Real data | Day |
| G7 | Optional: database check for L5; `pre-commit` | DEFERRED | An owner decision, if ever wanted | Day |

### H. Documentation

| ID | Package | Status | Waits for | Executor |
|---|---|---|---|---|
| H1 | Documentation corrections | **DONE** (#27, `aa51d21`) | — | Day |
| H2 | One source for status (K9): reduce the status narratives to pointers | BLOCKED | Q-12 | Day |
| H3 | Freeze the diagnostic report; decide where I1 to I6 are tracked | BLOCKED | Q-12 | Day |
| H4 | Recorded self-review in every pull request (K7), for example a template | BLOCKED | Q-12 | Day |
| H5 | Blueprint revision: the §10 order, and journeys for core versus contextual material and layers A to C (K1, K13) | BLOCKED | A2 | Day |
| H6 | This execution tracker and the CLAUDE.md workflow rules | **AWAITING OWNER MERGE** (Day 1) | The owner's merge | Day |

### I. Deployment and release

| ID | Package | Status | Waits for | Executor |
|---|---|---|---|---|
| I1 | B17 and ADR-0008 | BLOCKED | C2 | Owner, Day |
| I2 | Production hardening (diagnostic I1, I2, I5) | BLOCKED | I1 | Day |
| I3 | Release images, image scan, tags | BLOCKED | I1 | Day |
| I4 | Backups with a restore test, monitoring, runbooks, rollback | BLOCKED | I1 | Day |
| I5 | PostgreSQL collation and locale decided | BLOCKED | I1; before any data is kept from D1 | Owner, Day |

### J. Acceptance

| ID | Package | Status | Waits for | Executor |
|---|---|---|---|---|
| J1 | Acceptance audit at each of the four completion milestones | BLOCKED | The first milestone: methodologically ready for ingestion | Day |

**Critical path.** A2 → B1 → B2 → B3 → (B4 → B5) → B6 → C3 → C5 → D1, with B20 needed before B6 (F-15) and C1 → C2 needed before C5. Most of it is research done by the researcher; the Days on it record decisions and amend documents.

## 5. Execution Days

A Day is one unit of work by Claude Code, in one or more sessions, with one coherent deliverable and written acceptance criteria. The counter starts with Day 1 on 2026-10-30. A Day's number is fixed when it starts. Planned Days are numbered in their planned order; if a planned Day is blocked and a later one can run first, the queue is renumbered, and the change is recorded here.

### Days started

| Day | Objective | Packages | Started | Status | Pull request |
|---|---|---|---|---|---|
| 1 | Reconcile the project state; establish this tracker and the workflow rules | H6 | 2026-10-30 | AWAITING OWNER MERGE | The pull request that adds this file |

### Planned Days

Provisional numbers. **Ready when** names what must hold before the Day can start.

| Day | Objective | Packages | Ready when |
|---|---|---|---|
| 2 | Record the research governance decisions | A2 (and the decision parts of A4, B12) | Day 1 merged; Q-1 to Q-8 answered |
| 3 | Job-system and worker-isolation spike | C1 | Q-9 answered |
| 4 | Revise the Blueprint's order and journeys | H5 | Day 2 merged |
| 5 | Prepare the ADR-0004 and ADR-0011 decisions from the spike | C2 | Day 3 merged; then the owner decides |
| 6 | Design foundation on the existing pages | E1, G4 (target only) | Q-10 answered (P-1, P-13) |
| 7 | Phase 1 exit and account-administration pages | A5, D0 | Q-11 answered |
| 8 | Status consolidation, diagnostic report frozen, self-review practice | H2, H3, H4 | Q-12 answered |
| 9 | CI reliability: dependency audit schedule and time headroom | G2, G3 | Q-13 answered |
| 10 | Browser checks of the existing pages, with the owner | E2 | The owner is available with a browser |
| 11 | ADR for the source of registry names and dates | C4 | Q-10 answered (P-11) |

**After Day 11 (not yet numbered).** Days that record research outcomes as the researcher completes them (B4, B5, B6, B8 closure records); the F-point amendments of C3, one reviewed change per group; the Phase 2 gate change (C5); then Phase 2 (D1 with G5) and the later phases, which are planned in Days only when their gates are near.

**Estimate, not a promise.** Days 2 to 11, plus about 7 to 10 further Days for research records, the F-points, and the Phase 2 gate: about 17 to 20 Days of engineering work before Phase 2 can start. The research packages run on the researcher's time and are not counted in Days. Phases 2 to 6 are not estimated in Days until C5.

## 6. Checklists for the upcoming Days

### Day 1: reconcile the project state; establish this tracker and the workflow rules

Deliverable: this file, the "Execution workflow" section of CLAUDE.md, and a link from the README, in one documentation pull request.

- [x] Fetch `origin/main` and verify its SHA and CI
- [x] Reconcile the 27 merged pull requests, the direct commits, the audit, the A2 pack, and the session records
- [x] Classify every roadmap package, with evidence, and count progress
- [x] Write this tracker
- [x] Add the workflow rules to CLAUDE.md, checked against its existing rules
- [x] Link the tracker from the README documentation map
- [x] Quality checks: `git diff --check`, links, `ruff`, `mypy`, `lint-imports`
- [x] Review the complete diff
- [ ] Create the pull request
- [ ] Verify CI on its exact head and read the pytest summary
- [ ] The owner merges; the merge and its CI are verified

Acceptance: every section this file requires exists; every package has a status with its evidence or prerequisite; no decision, gate, blocker status, research question, or date is changed; the CLAUDE.md rules contradict no existing rule; the four required checks pass on the exact head.

### Day 2: record the research governance decisions

Ready when Day 1 is merged and Q-1 to Q-8 are answered.

- [ ] Record the answers to Q-1 to Q-8 in [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md) (§3 for decision authority, §3.5 for the closure gate and the sequencing, §3.7 or §3.8 for readers, records, and rights checks), with the date, and add a §12 change record
- [ ] If Q-4 is answered (a): a separate reviewed change to the specification adds the F-15 note on B20, without moving B20 from Phase 4
- [ ] No blocker closed; B22, B8, B20, and O-1 to O-11 stay open; no date, research question, or gate changed
- [ ] Update this tracker: Day 1 marked DONE with its merge SHA and CI; A2 status
- [ ] Quality checks; complete diff review; pull request(s); exact-head CI

Acceptance: each answer is recorded as the owner gave it, attributed and dated; every changed sentence traces to an answer; CI passes on the exact head.

### Day 3: job-system and worker-isolation spike (C1)

Ready when Q-9 is answered. Proposed boundaries: a throwaway branch that is never merged; nothing added to the lockfile of `main`; the candidates of [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §10, B4 (a stable Celery release, `django-tasks`, Dramatiq, one more only if justified) on Python 3.14; ADR-0011's requirements as the test plan; synthetic data only; no outbound network beyond package installation.

- [ ] Write the test plan from ADR-0011 and ADR-0004's open points
- [ ] Build the minimal harness on the spike branch
- [ ] Demonstrate each requirement with a test, or show why it cannot be met
- [ ] Write the spike report, including what was not verified, as a documentation pull request
- [ ] Quality checks on the report pull request; complete diff review; exact-head CI

Acceptance: every requirement is shown with a test result or recorded as not met; no dependency reaches `main`; the report proposes and decides nothing; ADR-0004 and ADR-0011 stay Proposed.

### Day 4: revise the Blueprint's order and journeys (H5)

Ready when Day 2 is merged.

- [ ] Revise Blueprint §10 action 2 to the order the owner chose in Q-3
- [ ] Revise the journeys so core and contextual material, and layers A, B, and C, stay separate (K13)
- [ ] Keep every recommendation a proposal: no proposed feature is presented as approved
- [ ] Update this tracker; quality checks; complete diff review; pull request; exact-head CI

Acceptance: no conflict remains between the Blueprint and the protocol's dependencies; the Blueprint still decides nothing.

### Days 5 to 11

Each also includes: update this tracker; quality checks; complete diff review; pull request; exact-head CI. Each is detailed further when it comes next in the queue.

- **Day 5 (C2).** Ready when Day 3 is merged. Draft the proposed changes to ADR-0004 and ADR-0011 from the spike's results, each statement traced to a test. Acceptance: both ADRs stay Proposed until the owner accepts them; nothing is installed on `main`.
- **Day 6 (E1, target of G4).** Ready when Q-10 is answered. Design tokens and a base stylesheet as static files; navigation and landmarks in the base template; distinct accessible names for repeated buttons; a synthetic script-specimen page if P-13 includes it. Acceptance: no new dependency and no JavaScript build step (ADR-0010); template tests for the accessible names; route count and access declarations updated if a page is added; manual browser check listed for Day 10.
- **Day 7 (A5, D0).** Ready when Q-11 is answered. Record the Phase 1 exit in the specification as the owner decides; pages to disable and enable an account and to grant and revoke a role, through the existing services and permissions. Acceptance: tests for access per role, refusals, and the role and account events; the exact route count and permission sets extended where tests state them.
- **Day 8 (H2, H3, H4).** Ready when Q-12 is answered. Reduce the status narratives to pointers to the specification; freeze the diagnostic report and track I1 to I6 where the owner decides; add the self-review practice. Acceptance: no status statement left that disagrees with the specification; no decision changed.
- **Day 9 (G2, G3).** Ready when Q-13 is answered. The chosen dependency-audit schedule; the chosen timeout and sharding plan. Acceptance: CI still deploys nothing and holds no secret; the change is the one the owner approved.
- **Day 10 (E2).** Ready when the owner is available. Work through diagnostic §12 items 1 to 7 with the owner and record the results. Acceptance: each item recorded as checked, failed (with a follow-up), or not checkable.
- **Day 11 (C4).** Ready when Q-10 (P-11) is answered. Draft the ADR for the source of a registry name or date and a preferred name, as Proposed. Acceptance: the ADR decides nothing until the owner accepts it.

## 7. Active and pending pull requests

| Pull request | Day | Head | Status |
|---|---|---|---|
| The pull request that adds this file | 1 | Reported when it is opened | Awaiting CI, then the owner's merge |

## 8. Blockers and dependencies

Authoritative status: [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §10 for blockers, [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md) §3.5 to §3.7 for O-1 to O-11 and F-1 to F-16, the [diagnostic report](reports/caipo-full-diagnostic-2026-10-20.md) §20.3 for I1 to I6. This table only points to them.

| Blocks | Open items | Package |
|---|---|---|
| Phase 2 | B4, B21 (shared spike); B7 (rights policy); B8 (period and questions); B9 (seed list); B10 (OCR); B22 (domain, under the closure gate of protocol §3.5) | C1, C2, B9, B4, B5, B7, B8, B1 to B6 |
| Phase 2, through F-15 | B20 must be answered before B22 can close, although the specification lists it under Phase 4 | B12 |
| Phase 3 | B11, B12, B23 | B11, B10 |
| Phase 4 | B13, B20 | B12 |
| Phase 5 | B14, B15, B16, B19, B24 | D4 |
| Phase 6 | B17 | I1 |
| B22 closure | O-1 to O-11, all OPEN; provisional defaults do not count | B3, B5 |
| Other documents | F-1 to F-16, all unsettled | C3 |
| Not phase-gated | I1, I2, I5 (ADR-0008); I3 (needs an ADR); I4 (deferred by ADR-0018); I6 (housekeeping) | I2, C4, D6, A6 |

## 9. Decisions settled since the audit

None. A1 is the owner's acceptance of the audit baseline; it settles no research or architecture decision.

## 10. Decisions awaiting the owner

Recommended defaults are recommendations, not decisions. Q-1 to Q-8 are the A2 decision pack of 2026-10-30.

| ID | Decision | Why it matters | Recommended default | Alternatives and consequences | Blocks |
|---|---|---|---|---|---|
| Q-1 | Is the project owner also the responsible researcher? If not, who is? | No research decision can be validly recorded without it | State the fact. If the same person: each record says which role acted, and the single-person limitation is stated | A separate researcher decides the content of B8, B9, and B22; the owner approves scope changes and closure gates | Day 2, all of B |
| Q-2 | Confirm the six conditions of protocol §3.5 as the binding B22 closure gate (F-9)? | Without a confirmed gate, B22 could be closed on the shorter specification row | Confirm all six as written; O-4 needs B20 (no exception); the single-reader re-check is allowed with its limitation; B8 closes first or in the same change | Change conditions, with reasons, in a reviewed protocol change. Keeping only the specification row is not recommended | B6, Phase 2 |
| Q-3 | Order of B22 and B8 | They depend on each other; the Blueprint's order cannot be followed | (a) Split the B8 work: set the period first, on grounds independent of AI policy dates, before any indicator values are examined; write the questions with O-11; B8 closes with or just before B22 | (b) close B8 and O-11 together with B22; (c) a pilot-only period; (d) protocol dependencies govern, the Blueprint is fixed later | B4, B5, H5 |
| Q-4 | When is B20 answered (F-15)? And which institution, if any? | B22 cannot close until B20 is answered | (a) The researcher asks the institution now; B20 stays a Phase 4 blocker; a separate reviewed change adds the F-15 note to the specification | Waiting until Phase 4 keeps Phase 2 blocked. With no institution, the specification row cannot be met as written and needs a separate decision | B12, B6 |
| Q-5 | B8 working basis and closure test | Fixes how the period is chosen before data is seen | P1, one common window, as a working basis only; a fixed end cutoff; the start reason recorded before values are examined. Closure test: §3.3 states period, start reason, end rule, date convention, and use of earlier observations; §2 revised to the O-11 constraints; one reviewed change with the specification row and the owner's confirmation | Keep P1 and P3 both open; or P3, which needs §3.3 and §4.2 reworded | B4 |
| Q-6 | Who reads which language and script; is a second reader available? | The pilot records its readers before any candidate is read (§3.8 point 1) | State the people who exist. One reader: the blind re-check, with its limitation; seek a second reader where possible | A team of named readers gives agreement between readers, which is stronger evidence | B1, B2, B12 |
| Q-7 | Where are pilot records and other working records kept? | The protocol keeps them outside this public repository, in a place the owner designates (O-10) | A private, version-controlled repository with access for the owner and the researcher only; metadata records only; kept document files outside git, with their hashes recorded; nothing published until B7 | A local repository with a backup | A4, B1, B2 |
| Q-8 | Who makes the pilot's rights checks, and who is the competent rights reviewer for B7? | Files may be kept for the pilot only after a recorded check; B7 needs a competent reviewer | The researcher makes and records the pilot checks, and an uncertain case is not kept; the owner names or commissions the B7 reviewer now | A named rights adviser makes the pilot checks too | B2, B8, B9 |
| Q-9 | Start the C1 spike with the boundaries of §6, Day 3? | The only Phase 2 gate work engineering can do while research proceeds | Yes, with those boundaries | Defer it until the research decisions are made | C1, C2 |
| Q-10 | Blueprint decisions P-1 (accessibility target), P-11 (sources of names), P-13 (design foundation now), P-14 (text style guide) | E1, G4, and C4 depend on them | The Blueprint's recommended options for each | Reject or defer each | A3, E1, G4, C4 |
| Q-11 | Phase 1 exit: declare it met, with D0 as a residual Phase 1 item or as later work? | No document declares Phase 1 complete; account administration has no page | Declare the exit met, with D0 as a residual Phase 1 item | Keep Phase 1 open until D0 is built | A5, D0 |
| Q-12 | Status consolidation (including CLAUDE.md "Current phase"), freezing the diagnostic report, a pull request template | Status is narrated in about seven places | Approve all three as Day 8 | Approve some; or keep the current practice | H2, H3, H4 |
| Q-13 | Dependency audit between changes; CI timeout headroom | No scheduled audit exists; the test job reached 78% of its timeout | A weekly scheduled run of the existing dependency audit in CI; raise the test job's timeout and plan sharding | Dependabot alerts (a repository setting); leave the timeout and accept the risk of failed runs | G2, G3 |
| Q-14 | Housekeeping: old backups, merged branches, local `main`, leftover worktrees, Dependabot setting | Clutter and stored account data | Decide item by item; nothing is deleted without the owner's word | Keep everything | A6 |

## 11. Next executable Day

**Day 1 is awaiting the owner's merge.** After the merge, the next Day is the first planned Day whose "Ready when" holds:

- **Day 2** as soon as Q-1 to Q-8 are answered;
- **Day 3** as soon as Q-9 is answered, independently of Day 2;
- otherwise no Day can start, and the questions above are what unblocks them.
