# CAIPO full diagnostic, 2026-10-20

Technical, security, data, and research-readiness audit of the repository at `main` `4bff508` and of the local development database. Carried out by an AI agent (Claude Code) at the project owner's request, on the branch `audit/caipo-full-diagnostic`.

## 1. Executive summary

**The Phase 1 platform is in good health. CAIPO is not yet ready for research work beyond keeping the reference registry.**

- Every quality gate that CI runs passes locally: 4169 tests, ruff, formatting, mypy (strict), both import contracts, Django checks, migration consistency, the dependency audit, and the full-history secret scan. The last six CI runs on `main` passed all four jobs.
- No Critical or High defect was found. An independent probe of all 40 routes for 8 kinds of actor found no route reachable without its declared permission, no CSRF gap, and no server error under hostile input.
- The development database is intact. Its 2 countries, 5 languages, 3 institutions, and 3 names are consistent, and the audit record has exactly one `created` event for each, with no orphaned events. Nothing was written to it during the audit.
- Three Medium findings. One is data: the stored English name of Turkmenistan's statistics body does not match the body's own website. One is usability: an irreversible action takes a single click. One, documentation drift, is fixed on this branch.
- Research readiness: the platform cannot yet hold a source, document, policy, indicator, claim, or citation. That is by design. Phase 2 and later are blocked by open research, rights, and isolation decisions (spec §10), most of them the researcher's to make.

| Area | Assessment |
|---|---|
| Authentication, MFA, recovery | Implemented as ADR-0013 to 0017 decide; verified by tests and by probe |
| Authorization | Deny by default, checked at the view and again in each service; no leak found |
| Registry and audit | Implemented as ADR-0018 and 0019 decide; all 13 testing requirements present and passing |
| Data integrity (dev database) | Consistent; no fabricated dates, parents, or successors |
| Production readiness | Not intended yet; HSTS, TLS redirect, CSP, database roles, key management, and email wait for ADR-0008 |
| Research readiness | Phase 1 only. Phase 2 gate NOT READY. |

## 2. Commit, branch, and scope

| Item | Value |
|---|---|
| Repository | `github.com/kldidar/caipo` (public) |
| Audited commit | `4bff5081520527e6bd1972463994599289d757cd` (`main`, equal to `origin/main` at the start) |
| Working tree at start | Clean |
| Audit branch | `audit/caipo-full-diagnostic`, created from `4bff508` |
| Environment | WSL2, Python 3.14.4, Django 5.2.17, PostgreSQL 18.6, Redis 8.10.2, uv 0.12.21, Docker 29.8.1 |
| Date | 2026-10-20 (UTC) |

In scope: the code, tests, configuration, CI, and documentation of the repository; the local development database, read only; the GitHub CI history and the protection of `main`.

Out of scope: production (none exists), browser automation (none was available), and building any feature of a later phase.

## 3. Components and routes inspected

**Apps and layers** (import-linter, exhaustive): `config` → `web` → `registry` → `accounts` → `core`. A second contract keeps `registry` to `accounts.services` and `accounts.selectors`. Its one test-only exception (ADR-0019 point 26) is used by seven test modules, each importing only `AuditEvent` and/or `AuditEventChange`. `test_boundaries.py` checks this.

| App | What was read |
|---|---|
| `core` | Append-only base, correlation IDs, mail boundary, JSON logging |
| `accounts` | Models (User, session epoch, role, authentication, account, and audit events, TOTP devices, recovery requests), authorization table, selectors (`authentication_context`, `_proven_assurance`, `permissions_of`, `require_permission`), and the security-relevant parts of the services: client-address hashing and throttling. The 3049-line services module was spot-checked, not read line by line, and relies on its tests. |
| `registry` | Models, both migrations and their four triggers, all 13 services, all 3 selectors |
| `web` | Access declarations, middleware, sessions, sign-in redirect validation, registry views and forms, templates |
| `config` | Base, development, testing, and production settings; URL configuration |

**Routes:** 40, all declaring access: 9 public, 31 behind a named permission. The registry has 15: the browse page (`REGISTRY_READ`), the entry page and 5 institution POSTs (`REGISTRY_INSTITUTIONS_MANAGE`), and 8 country and language POSTs (`REGISTRY_REFERENCE_MANAGE`).

**Public routes:** `/login/`, `/login/verify/`, `/login/verify/recover/`, `/logout/`, `/activate/`, `/password-reset/`, `/password-reset/confirm/`, `/health/live/`, `/health/ready/`.

## 4. Implemented features verified against the code

Each was confirmed in code and by passing tests. Where noted, it was also confirmed by the audit's own probe.

| Feature | Decided in | Verified |
|---|---|---|
| Deny-by-default access declarations on every view | ADR-0007, NFR-11 | Code, tests, probe (0 undeclared of 40) |
| Roles, permissions, and role events with an append-only trigger | ADR-0012 | Code, tests, trigger present in the database |
| Sign-in with Argon2, throttling, and authentication events; sign-out | ADR-0013 | Code, tests |
| First-Administrator bootstrap (TTY only) | ADR-0013 | Tests |
| TOTP MFA with encrypted secrets, Administrator approval of privileged enrolment, and assurance re-checked against the database on every decision | ADR-0014 | Code (`_proven_assurance`), tests, probe |
| Account creation by an Administrator; email verification | ADR-0015 | Tests |
| Password reset | ADR-0016 | Tests |
| MFA recovery: request, authorisation, finalisation with the session epoch, completion, break-glass command, history, notices | ADR-0017 | Tests (break-glass reachable by no view: test and probe) |
| Shared append-only base; AuditEvent and AuditEventChange with triggers; `record_audit_event` | ADR-0018 Increment 1 | Code, tests, triggers in the database |
| Country and Language: form-only code checks in the service and the database; unique codes; deactivate and reactivate | ADR-0018, ADR-0019 Increment 2 | Code, tests, database constraints |
| Institution and InstitutionName: half-open dates, not-own-parent or successor, successor needs valid-to, cycle checks, the succession lock, the last-unmarked-name rule, the set-once mark | ADR-0018, ADR-0019 Increment 3 | Code, tests (10 real-concurrency tests), database constraints and triggers |
| Audit event in the transaction of every registry change, with old and new values | ADR-0018 points 35, 41, 42 | Code, atomicity tests, and the dev database (§5) |
| Health endpoints | DEVELOPMENT.md | Probe: live 200; ready 200 with database `ok`; both `no-store` |
| Structured JSON logs with correlation IDs | NFR-06 | Observed; every audit event in the dev database has a correlation ID |

**Lock order in the registry**, reviewed by hand. A change of succession takes its row lock (`FOR NO KEY UPDATE`), then the table lock (`SHARE ROW EXCLUSIVE`). Every other write takes row locks only, and marking a name locks the institution before the name. No cycle of waits was found between these paths. The foreign-key checks (`FOR KEY SHARE`) do not conflict with `FOR NO KEY UPDATE`.

## 5. Database state and data integrity

A backup was made before anything else and checked by restoring it.

| Item | Value |
|---|---|
| Backup | `~/caipo-backups/caipo_dev_before_audit_20261020_180112.dump`, mode `600`, PostgreSQL custom format |
| SHA-256 | `4d25052c705bf6a5f19305c0ed556c72e8306b2d7b5a83bd67e79f0c81532133` |
| Check | Restored into a throwaway database (`--exit-on-error`, exit 0). Row counts were equal to the live database in all 8 tables compared. The throwaway database was dropped. |

All later inspection ran in `BEGIN TRANSACTION READ ONLY … ROLLBACK`.

| Table | Rows | State |
|---|---|---|
| Country | 2 | TM/TKM Turkmenistan; UZ/UZB Uzbekistan; both active |
| Language | 5 | tuk-Latn Turkmen, uzb-Latn Uzbek, uzb-Cyrl Uzbek, rus-Cyrl Russian, eng-Latn English; all active |
| Institution | 3 | 1 ministry (UZ), 2 statistical agencies (UZ, TM); no dates, parents, or successors |
| InstitutionName | 3 | One `english_rendering` in eng-Latn for each; none marked; all in NFC |
| AuditEvent | 16 | 13 `created` and 3 `updated`, all by the one Administrator, all with a correlation ID |
| AuditEventChange | 3 | `name_en` of three languages: "Uzbekistan" → "Uzbek" (twice), "Turkmenistan" → "Turkmen" |
| User | 1 | The bootstrapped Administrator (email not reproduced here) |

**Checks, all passed:**

- The two countries and five languages are present once each. Nothing was lost or duplicated.
- Every registry record has exactly one `created` audit event, and no audit event names a record that does not exist.
- Each institution's `created` event comes immediately before its first name's.
- Each renamed language's stored name equals the new value of its latest change record.
- Every institution has a name that is not marked. Every name refers to an existing, active language. Every country reference is to an active country.
- No date, parent, or successor has been entered, so nothing unsupported is recorded.
- All nine protection triggers exist: five on the `accounts` event tables, four on the registry tables. Every constraint ADR-0018 names is present.

**Institutions asked about in the brief.** Both statistical agencies were already present, entered by the owner at 17:55 and 17:56 UTC. **Nothing was created.** Each name was checked against the body's own website on 2026-10-20:

| Stored name | Official site | Result |
|---|---|---|
| Ministry of Digital Technologies | digital.uz header: "Ministry of Digital Technologies of the Republic of Uzbekistan" | Accurate, shortened (L9) |
| National Statistics Committee of the Republic of Uzbekistan | stat.uz header and footer: the same (other variants appear elsewhere on the page) | Matches |
| State Statistics Committee of Turkmenistan | stat.gov.tm header and footer: "State Committee of Turkmenistan on Statistics" | **Does not match** (M1) |

Names in Turkmen, Uzbek, and Russian were not checked.

## 6. Security and authorization assessment

**Probe method.** The audit wrote its own test module, kept outside the repository, and ran it against an exported copy of `4bff508` with a separate test database. It sent GET and POST to all 40 routes as 8 actors: anonymous; Reader, Researcher, and Reviewer on a password; Reviewer verified; Administrator on a password; Administrator verified; and a disabled Administrator with a verified session. That is 640 requests. Each actor's session was rebuilt for every request. Synthetic data only.

| Check | Result |
|---|---|
| A route answering below 400 to an actor without its permission | 0 of 640 |
| An actor with the permission refused with 403 | 0 |
| Server errors (5xx) | 0 |
| Reviewer and Administrator on a password alone | Refused on the registry and every administration page, as ADR-0014 and ADR-0018 point 12 require |
| Disabled account with a verified session | Reaches only the 9 public routes |
| POST without a CSRF token, as a verified Administrator, to every route | 40 of 40 refused with 403 |
| 73 hostile registry POSTs: NUL bytes, 5,000-character text, `<script>`, template syntax, SQL fragments, bidi controls, invalid UUIDs, impossible and partial dates, unknown kinds, self-parent, a successor without valid-to, marking the last name | 0 server errors. Refusals: 400 (47), 404 (4), 409 (3). The 19 accepted were valid. |
| Output escaping | `<script>` stored and shown escaped; `{{ 7*7 }}` shown literally. No `|safe`, `mark_safe`, or `autoescape off` in the code. |
| Open redirect after sign-in | `url_has_allowed_host_and_scheme` is applied both when the destination is accepted and when it is followed |
| Client address for throttling | `REMOTE_ADDR` only, deliberately not `X-Forwarded-For` (see I2) |
| Session and cookies (base settings) | Database sessions; 12-hour lifetime; end when the browser closes; `Secure`, `HttpOnly`, `SameSite=Lax`; `X-Frame-Options: DENY`; `nosniff`; `same-origin` referrer |
| `check --deploy`, production settings, synthetic values | 2 warnings: HSTS (W004) and SSL redirect (W008), both deferred to ADR-0008 as `production.py` says |
| Secrets | gitleaks over the full history found nothing. `.env`, `/data/`, and `*.dump` are git-ignored. `data/outbox/` is empty. |

## 7. Test and quality-gate results

All run on `4bff508`, except where noted.

| Check | Command | Result |
|---|---|---|
| Lockfile | `uv lock --check` | Exit 0; 36 packages |
| Locked install | `uv sync --locked` | Exit 0 |
| Lint | `uv run --no-sync ruff check .` | Exit 0; all checks passed |
| Formatting | `uv run --no-sync ruff format --check .` | Exit 0; 184 files |
| Types | `uv run --no-sync mypy .` | Exit 0; 149 source files |
| Import contracts | `uv run --no-sync lint-imports` | Exit 0; 2 kept, 0 broken (7 test imports covered by the exception) |
| Django checks | `manage.py check` | Exit 0; no issues |
| Migrations match models | `manage.py makemigrations --check --dry-run` | Exit 0; no changes |
| Unapplied migrations | `manage.py migrate --check`, `showmigrations` | Exit 0; all applied, `registry` 0001 and 0002 included |
| Full suite | `uv run --env-file .env pytest -rfE --tb=short` | **4169 passed**, 0 failed, 0 skipped, 0 warnings, exit 0, 9 min 16 s |
| Focused: registry | `pytest caipo/registry` and the two registry page modules | **1498 passed**, exit 0 |
| Focused: authentication and MFA | 16 modules (sign-in, authentication events, authorization, second factor and its approval, session epoch, TOTP, first Administrator, role services, and their page tests) | **903 passed**, exit 0 |
| Probe | Three tests in the audit's own module | 3 passed (§6) |
| Dependency audit | `uvx pip-audit==2.10.1 --require-hashes --disable-pip` on the exported lockfile | Exit 0; no known vulnerabilities |
| Secret scan | gitleaks v8.30.1 (pinned digest), `git` mode, full history | Exit 0; 39 commits, no leaks |
| CI on GitHub | `gh run list --branch main` | The last 6 runs on `main` passed, including `4bff508` (4 of 4 jobs) |
| Protection of `main` | `gh api …/rulesets` | Active ruleset: pull request required, the 4 CI jobs required, no deletion, no force push; 0 approvals required; status checks not strict (L7) |

The re-run after the fixes is in §9.

**Where the 13 testing requirements of ADR-0018 stand** (allocation of ADR-0019): all present and passing. Examples are requirement 5 in `test_protection_inventory.py` and the models tests, requirement 8 in `test_institution_concurrency.py` (10 tests), the second migration's supplementary tests in `test_institution_migration.py` (10 tests, reversal included), and requirement 10 in `test_boundaries.py`.

## 8. Findings by severity

No Critical and no High finding.

### Medium

**M1. Stored English name of Turkmenistan's statistics body differs from the body's own.**
- Evidence: InstitutionName 3 reads "State Statistics Committee of Turkmenistan". The header and footer of stat.gov.tm read "State Committee of Turkmenistan on Statistics" (fetched 2026-10-20).
- Impact: Documents will be attributed to this institution. A name that the body does not use weakens matching and citation.
- Validation: The read-only query of §5 and the official site.
- Recommended action, **for the owner** (research data, and a mark cannot be undone): add the site's form as a new name. Then decide whether the present one is a variant worth keeping or a name entered in error. Not changed by this audit.

**M2. "Mark as entered in error" is irreversible and takes one click.**
- Evidence: `registry_entry.html` posts the mark with a single button. Elsewhere, irreversible administrative actions need a ticked confirmation (second-factor approval, recovery authorisation).
- Impact: A misclick marks a correct name for ever. The only remedy is to enter it again, which leaves the mistaken mark in the record.
- Recommended action: a confirmation step. **Owner decision**: it changes a page that ADR-0018 and 0019 define.

**M3. Documentation drift. Fixed on this branch.**
- Evidence: README's quick start told a new developer to set "the two passwords and DJANGO_SECRET_KEY", leaving out `TOTP_ENCRYPTION_KEY`. Without it every `manage.py` command stops (DEVELOPMENT.md, "First-time setup"). README's status and DEVELOPMENT.md did not mention the registry. DEVELOPMENT.md said the bootstrap creates "the only account the application can create so far" and that "no page uses" the authorization layer apart from the sign-in and second-factor pages. Both have been untrue since ADR-0015.
- Fix: §9.

### Low

- **L1. A refused request gets a bare "403 Forbidden" page.** It has no explanation and no link to sign in. A Reviewer or Administrator on a password alone is not told that a second factor is what is missing. The response also has no `Cache-Control`. A friendlier page, or a redirect to sign-in for anonymous visitors, is a design choice for the owner.
- **L2. Every refusal is logged twice.** Once as the application's `access.denied` or `authorization.denied`, and once by `django.request` at WARNING with a full traceback. That is noise in an append-only log stream, and not a leak: no values are in the traceback.
- **L3. The per-institution forms lose typed input on refusal.** The change, add-name, and change-dates forms show no field errors. A refused change shows one general message at the top and the stored values again.
- **L4. The entry page grows with the square of the number of institutions.** Every institution has a change form with two selects listing every other institution. With 3 institutions this is invisible. With several hundred the page becomes very large. Neither page is paginated.
- **L5. Bidirectional control characters are accepted in names and shown without isolation.** For example U+202E. Storing text as entered is ADR-0018's decision. Whether to refuse such characters, or to isolate them in display (`dir="auto"` or `<bdi>`), is a policy question.
- **L6. Dates are accepted with non-ASCII digits and without zero padding.** For example `１２３４-01-01` and `2020-1-1`. They are parsed to valid full dates, so nothing wrong is stored. Noted only.
- **L7. The ruleset requires 0 approvals and non-strict status checks.** Reasonable for one maintainer. A PR that passed against an older `main` can be merged without re-running against the new one.
- **L8. No custom 404 or 500 templates.** In production, Django's plain defaults would be shown.
- **L9. The Ministry's English name is a shortened form.** "Ministry of Digital Technologies" against the site's "Ministry of Digital Technologies of the Republic of Uzbekistan". Accurate, incomplete; the owner may add the full form.

### Informational and future work

- **I1. Production hardening waits for ADR-0008** (Proposed): HSTS, TLS redirect, the proxy header, trusted CSRF origins, CSP, database roles that stop TRUNCATE and changes to triggers, key storage and rotation, and email delivery. `production.py` lists these itself.
- **I2. Throttling by `REMOTE_ADDR`.** Behind a reverse proxy every client would share one address, and 20 failures from any of them would lock sign-in for everyone. This must be designed with ADR-0008.
- **I3. The registry records no source for a name or a date.** ADR-0018 classes registry maintenance as stating no claim and citing no source. M1 shows the cost: where a name came from is recorded nowhere. Worth a decision before many institutions are entered.
- **I4. No page or selector reads the audit record.** Deferred by ADR-0018 to a later increment with its own permission. Until then it is read by SQL.
- **I5. The break-glass command is not recorded operationally.** Who ran it is not recorded; that waits for ADR-0008.
- **I6. Older backups in `~/caipo-backups/` hold account data.** All are mode `600`. Keep them restricted, and delete those no longer needed.
- **I7. Fourteen local branches of merged work remain.** Housekeeping only.

## 9. Fixes made and regression tests

| Finding | Change | Files |
|---|---|---|
| M3 | README status names the audit record and the registry. The quick start names `TOTP_ENCRYPTION_KEY` and points to DEVELOPMENT.md. DEVELOPMENT.md's summary names the registry. The bootstrap is "the first account", not "the only". The authorization section says which pages are public and that every other page declares a permission (checked against the probe's list). A new "The registry" section gives the 15 routes, their permissions, and how a fresh database is filled. | `README.md`, `docs/DEVELOPMENT.md` |
| — | This report | `docs/reports/caipo-full-diagnostic-2026-10-20.md` |

**No application code, test, migration, setting, or CI file was changed.** Only documentation changed, so no regression test applies.

After the fixes, every gate was run again on the branch:

| Check | Result on the branch |
|---|---|
| `uv lock --check`, `ruff check`, `ruff format --check`, `mypy .`, `lint-imports` | Exit 0 each |
| `manage.py check`; `makemigrations --check --dry-run` | No issues; no changes |
| Full suite | **4169 passed**, 0 failed, 0 skipped, exit 0, 8 min 48 s |
| Secret scan (gitleaks, full history including the audit commit) | Exit 0; 40 commits scanned, no leaks |

## 10. Features incomplete or intentionally deferred

| Feature | Status | Where decided |
|---|---|---|
| Page or selector that reads the audit record | Deferred | ADR-0018, "Not in this milestone" |
| Public page of the registry | Deferred | ADR-0018 point 15; with the public research site |
| Page to disable or enable an account | Services exist, no page | DEVELOPMENT.md, "Creating accounts" |
| Email delivery in production | No service | ADR-0008 (Proposed) |
| TOTP key rotation; production key management | Not built | ADR-0014, ADR-0008 |
| Break-glass operational audit trail | Not built | ADR-0017, ADR-0008 |
| Database roles and privileges (TRUNCATE, triggers) | Not built | ADR-0012, 0018, 0008 |
| Django admin | Not installed | ADR-0007 rule 8 |
| Job system (Celery or another) | Must not be installed before the spike | ADR-0004 (Proposed), B4 |
| Worker isolation | Not chosen | ADR-0011 (Proposed), B21 |
| Vector search, AI provider | Not chosen | ADR-0003, 0006 (Proposed), B14 |
| Deployment | Not chosen | ADR-0008 (Proposed), B17 |

## 11. Research readiness

The study needs sources, versioned documents, passages, policies with formal lifecycle events, indicator observations, typed claims with evidence, search runs for negative findings, comparison, reproducible exports, and evidence-grounded AI. Against that:

| Capability | State |
|---|---|
| Countries, languages, institutions with historical names | **Implemented and verified** |
| Accountable change history of reference data | **Implemented and verified** (AuditEvent with old and new values) |
| Authentication, roles, MFA, recovery | **Implemented and verified** |
| Reading the audit record in the application | Deferred (I4) |
| Source of a registry name or date | Not designed (I3) |
| Sources, ingestion requests, guarded fetch, artifacts, parsing, document review, rights | **Documented, not implemented**: Phase 2; gate NOT READY (B4, B7, B8, B9, B10, B21, B22) |
| Segments, passages, document versions | Documented in DATA_MODEL, not implemented (Phase 2) |
| Policy coding and policy events | Documented, not implemented (Phase 3; B11, B23) |
| Indicators, dataset releases, observations | Documented, not implemented (Phase 3; B12) |
| Claims, evidence, search runs, review | Documented, not implemented (Phase 4; B13, B20) |
| Retrieval, assistant, evaluation | Documented, Proposed ADRs (Phase 5; B14, B15, B16, B19, B24) |
| Comparative views, export, deployment | Phase 6 (B17) |

**Unresolved research decisions that block the next phase** (spec §10, RESEARCH_PROTOCOL): the definitions of "AI policy" and "economic transformation" (B22); the research questions and study period, still drafts (B8); source inclusion criteria and the seed list (B9); the share of scanned documents and OCR (B10); and the rights policy for third-party documents and for project data (B7). The engineering spikes B4 and B21 also block Phase 2.

**Assessment:** CAIPO can be used today to build the reference registry for the study, and for nothing else. Every capability that holds evidence is in a later phase, and most of their blockers are research decisions, not engineering work.

## 12. Manual checks that still need the owner

No browser automation was available. These were not verified in a browser:

1. The rendering and layout of `/registry/` and `/registry/entry/`, including the native date picker and the select lists.
2. The keyboard and screen-reader experience of the entry page. Its many "Deactivate", "Change the dates", and "Mark as entered in error" buttons have the same text.
3. A real sign-in with an authenticator application, and the 403 a password-only Administrator sees on the registry.
4. Cookie behaviour over plain HTTP under the development settings.
5. Whether "State Committee of Turkmenistan on Statistics" is the form to record, and whether names in the national languages should be added (M1, L9).

## 13. Outstanding decisions and next steps

Decisions for the owner. This audit made none of them:

1. **M1:** how to correct the Turkmenistan agency's name.
2. **M2:** whether marking a name needs a confirmation step.
3. **I3:** whether registry names and dates should carry the source they came from. This needs an ADR, because ADR-0018 says registry maintenance cites no source.
4. **L1:** the page anonymous and under-assured users see when refused.
5. **L5:** whether names may contain bidirectional control characters.

Recommended order of next work:

1. Close the researcher-owned Phase 2 blockers: B22, then B8 and B9, then B7 and B10. Nothing research-related can be built before them.
2. Run the job-system and isolation spikes together (B4, B21), so that ADR-0004 and ADR-0011 can be decided.
3. A small interface increment for M2, L1, L3, and L5 once decided.
4. Before many institutions are entered: decide I3, and plan L4 (pagination or a page per institution, which would need an ADR because ADR-0018 allows two pages only).

## 14. Commands run, and checks not performed

**Commands run** (credentials never printed; `.env` passed to `uv run --env-file` and never read):

- `git status`, `git branch -vv`, `git fetch origin`, `git rev-parse HEAD origin/main`, `git switch -c audit/caipo-full-diagnostic`
- `docker info`, `docker compose ps`
- `docker compose exec -T postgres pg_dump --format=custom` (backup); `createdb`, `pg_restore --exit-on-error`, row counts, `dropdb` (restore check in a throwaway database)
- `psql` with `BEGIN TRANSACTION READ ONLY … ROLLBACK` (inspection of §5)
- `uv lock --check`; `uv sync --locked`; `ruff check`; `ruff format --check`; `mypy .`; `lint-imports`
- `manage.py check`; `check --deploy` (development settings, and production settings with synthetic values); `makemigrations --check --dry-run`; `showmigrations`; `migrate --check`
- `pytest` (full, and the two focused runs); the audit probe on an exported copy of HEAD with its own database
- `uv export` and `uvx pip-audit==2.10.1`; gitleaks v8.30.1 in a network-less, read-only container
- `gh auth status`; `gh run list`, `gh run view`; `gh api` (branch protection, rulesets)
- Fetches of the official sites `stat.gov.tm`, `stat.uz`, and `digital.uz`

**Not performed, and why:**

- Browser end-to-end testing: no browser automation was available (§12).
- Line-by-line review of `caipo/accounts/services.py` (3049 lines): spot-checked only; its behaviour rests on its tests.
- Reversing a migration on the development database: not done, because it destroys data. Reversibility is shown by the migration tests, which run on the test database.
- Any write to the development database: none was needed, because both agencies existed.
- A secret scan of uncommitted files: gitleaks scans commits only, as in CI. The branch is scanned after committing (§9).
- The production configuration: none exists (ADR-0008).

Detailed logs are kept outside the repository, in the session scratchpad (`logs/`). They contain no secrets: pytest output is filtered for `password=`, and the log was searched for secret-looking strings.
