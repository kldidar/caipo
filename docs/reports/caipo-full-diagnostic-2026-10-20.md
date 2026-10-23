# CAIPO full diagnostic, 2026-10-20

Technical, security, data, and research-readiness audit of the repository at `main` `4bff508` and of the local development database. Carried out by an AI agent (Claude Code) at the project owner's request, on the branch `audit/caipo-full-diagnostic`.

**How to read this report.** Sections 2 to 7 and 14 describe the audit as carried out on 2026-10-20 against `main` `4bff508`. Each finding states what was observed then. §15, §16, and §17 are dated follow-ups and keep the state of their own day, including statements that a pull request was open or that a name was not yet entered. The Status column of the register in §8 records the status after the merges of §17, on 2026-10-23. The current status of every finding is in §1 and §18, which records the entry of the two institution names later on 2026-10-23.

## 1. Executive summary

**The Phase 1 platform is in good health. CAIPO is not yet ready for research work beyond keeping the reference registry.**

- Every quality gate that CI runs passes locally: 4169 tests, ruff, formatting, mypy (strict), both import contracts, Django checks, migration consistency, the dependency audit, and the full-history secret scan. The last six CI runs on `main` succeeded; the latest, on `4bff508`, passed all four jobs.
- No Critical or High defect was found. An independent probe of all 40 routes for 8 kinds of actor found no route reachable without its declared permission, no CSRF gap, and no server error under hostile input.
- The development database is intact. At the audit, its 2 countries, 5 languages, 3 institutions, and 3 names were consistent, and the audit record had exactly one `created` event for each, with no orphaned events. Nothing was written to it during the audit; that was checked afterwards (§5). On 2026-10-24 it holds 3 institutions, 5 names, and 18 audit events, after the two names of §15.2 were entered (§18).
- Twenty findings, all listed in the register of §8: 4 Medium, 9 Low, 7 Informational. Current status, 2026-10-24 (§18): **ten are fixed**: M3 and M4, documentation, merged in pull request #16 (`ba8a89e`); M2, L1, L2, L3, L5, L6, and L8, application, merged in pull request #17 (`e0a9cbb`); and L7, in the GitHub ruleset, which is in force. **Two are resolved in the development registry**: M1 and L9, by the two English renderings proposed in §15.2, entered on 2026-10-23 by the Administrator through the entry page. **Eight are open**: L4, measured, with a recommendation (§15.4, §18.4); and the seven Informational findings, of which I1, I2, and I5 are deferred to ADR-0008, I4 by ADR-0018, I3 needs an ADR of its own, and I6 and I7 are housekeeping. The names do not resolve I3: the registry still records no source for a name.
- Research readiness: the platform cannot yet hold a source, document, policy, indicator, claim, or citation. That is by design. Phase 2 and later are blocked by open research, rights, and isolation decisions (spec §10), most of them the researcher's to make.

| Area | Assessment |
|---|---|
| Authentication, MFA, recovery | Built under ADR-0013 to 0017; its tests pass, and the probe found no access gap. The services were spot-checked, not reviewed line by line. |
| Authorization | Deny by default, checked at the view and again in each service; no leak found |
| Registry and audit | Services, models, migrations, and views read in full against ADR-0018 and 0019; a test module exists for each of the 13 testing requirements, and all pass |
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

Out of scope: production (none exists), browser automation (none was available), and building any feature of a later phase. The follow-up of 2026-10-21 is in §15.

## 3. Components and routes inspected

**Apps and layers** (import-linter, exhaustive): `config` → `web` → `registry` → `accounts` → `core`. A second contract keeps `registry` to `accounts.services` and `accounts.selectors`. Its one test-only exception (ADR-0019 point 26) is used by seven test modules, each importing only `AuditEvent` and/or `AuditEventChange`. `test_boundaries.py` checks this.

| App | What was read |
|---|---|
| `core` | Append-only base, correlation IDs, mail boundary, JSON logging |
| `accounts` | Models (User, session epoch, role, authentication, account, and audit events, TOTP devices, recovery requests), authorization table, selectors (`authentication_context`, `_proven_assurance`, `permissions_of`, `require_permission`), and, in the services, the hashing of client addresses, found by search. The 3049-line services module was spot-checked, not read line by line; its behaviour rests on its tests. |
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
| Roles, permissions, and role events with an append-only trigger | ADR-0012 | Permission table, tests, trigger present in the database |
| Sign-in with Argon2, throttling, and authentication events; sign-out | ADR-0013 | Settings (`PASSWORD_HASHERS`, `LOGIN_THROTTLE_*`), tests |
| First-Administrator bootstrap (TTY only) | ADR-0013 | Tests (8 terminal tests in `test_first_administrator.py`) |
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

**Lock order in the registry**, reviewed by hand. A change of succession takes its row lock (`FOR NO KEY UPDATE`), then the table lock (`SHARE ROW EXCLUSIVE`). Every other write takes at most row locks, and marking a name locks the institution before the name. No cycle of waits was found between these paths. The foreign-key checks (`FOR KEY SHARE`) do not conflict with `FOR NO KEY UPDATE`.

## 5. Database state and data integrity

A backup was made before anything else and checked by restoring it.

| Item | Value |
|---|---|
| Backup | `~/caipo-backups/caipo_dev_before_audit_20261020_180112.dump`, mode `600`, PostgreSQL custom format |
| SHA-256 | `4d25052c705bf6a5f19305c0ed556c72e8306b2d7b5a83bd67e79f0c81532133` |
| Check | Restored into a throwaway database (`--exit-on-error`, exit 0). Row counts were equal to the live database in all 8 tables compared. The throwaway database was dropped. |

All later SQL inspection ran in `BEGIN TRANSACTION READ ONLY … ROLLBACK`. Five anonymous GET requests (`/registry/`, an unknown path, both health endpoints, `/login/`) were made with Django's test client under the development settings, which use this database. Afterwards, a read-only query showed no new session, no authentication, role, or audit event since the audit began at 18:00 UTC, and the row counts of the backup in every table compared.

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
- All nine protection triggers exist: five on the `accounts` event tables, four on the registry tables. Every registry constraint ADR-0018 names is present. The audit record's constraints were not queried here; they are covered by the passing tests of `test_audit_event.py`.

**Institutions asked about in the brief.** Both statistical agencies were already present, entered at 17:55 and 17:56 UTC by the only account, the bootstrapped Administrator. **Nothing was created.** Each name was checked against the body's own website on 2026-10-20:

| Stored name | Official site | Result |
|---|---|---|
| Ministry of Digital Technologies | digital.uz header: "Ministry of Digital Technologies of the Republic of Uzbekistan" | Accurate, shortened (L9) |
| National Statistics Committee of the Republic of Uzbekistan | stat.uz header and footer: the same (other variants appear elsewhere on the page) | Matches |
| State Statistics Committee of Turkmenistan | stat.gov.tm header and footer: "State Committee of Turkmenistan on Statistics" | **Does not match** (M1) |

The sites were read through an automated fetch that turns a page into text. The owner should confirm the wording on the sites themselves (§12). Names in Turkmen, Uzbek, and Russian were not checked.

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
| 73 hostile registry POSTs: NUL bytes, 5,000-character text, `<script>`, template syntax, SQL fragments, bidi controls, invalid UUIDs, impossible and partial dates, unknown kinds, self-parent, a successor without valid-to, marking a name twice | 0 server errors. Refusals: 400 (47), 404 (4), 409 (3). The 19 accepted were valid. |
| Output escaping | `<script>` stored and shown escaped; `{{ 7*7 }}` not evaluated. No `|safe`, `mark_safe`, or `autoescape off` in the code. |
| Open redirect after sign-in | `url_has_allowed_host_and_scheme` is applied both when the destination is accepted and when it is followed |
| Client address for throttling | `REMOTE_ADDR` only, deliberately not `X-Forwarded-For` (see I2) |
| Session and cookies (base settings) | Database sessions; 12-hour lifetime; end when the browser closes; `Secure`, `HttpOnly`, `SameSite=Lax`; `X-Frame-Options: DENY`; `nosniff`; `same-origin` referrer |
| `check --deploy`, production settings, synthetic values | 2 warnings: HSTS (W004) and SSL redirect (W008), both deferred to ADR-0008 as `production.py` says |
| Secrets | gitleaks over the full history found nothing. `.env`, `/data/`, and `*.dump` are git-ignored. `data/outbox/` holds no files. |

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

**Where the 13 testing requirements of ADR-0018 stand** (allocation of ADR-0019): each was matched to the test modules that carry it, by module and test name, not test by test. All of those modules pass. Examples are requirement 5 in `test_protection_inventory.py` and the models tests, requirement 8 in `test_institution_concurrency.py` (10 tests), the second migration's supplementary tests in `test_institution_migration.py` (10 tests, reversal included), and requirement 10 in `test_boundaries.py` (`test_the_application_code_holds_no_literal_country_or_language_code`).

## 8. Findings by severity

No Critical and no High finding.

### Findings register

Every finding of the audit: the open ones first, then the fixed ones. The Finding and Evidence columns record what the audit found on `main` `4bff508` ("Before") and, for a fix, what changed ("After"). The Status column is the status on 2026-10-23, after the merges of §17. "Open" means that nothing has yet changed for it. "Fixed, merged in #16" or "#17" means that the fix is on `main`, in the merge commit named. "Fixed in the ruleset" means that the change is in force on GitHub. "Needs verification" names what the audit could not confirm itself. The evidence was checked again on 2026-10-21 against the code, the ruleset, the official sites, and an anonymous request (§14), and every status again on 2026-10-23 against the diffs of both pull requests and the settings on GitHub (§16), and after both merges against `main` `e0a9cbb` (§17). The last column says what was done, or is proposed, in the follow-up of 2026-10-21 (§15). The fixes are fixes from the findings of this audit.

**This register is kept as it stood after the merges of §17.** Later on 2026-10-23, M1 and L9 were resolved in the development registry, when the two names it proposes were entered. The current status of every finding is in §18.2.

| ID | Severity | Finding | Status | Evidence | Outcome |
|---|---|---|---|---|---|
| M1 | Medium | Turkmenistan statistics body: the stored English name is not the form the body's site uses for itself | **Open.** A correction is proposed; nothing is entered yet. Entry needs an Administrator signed in with a second factor (§15.2) | Read-only query of InstitutionName 3; stat.gov.tm/en/about-us, read on 2026-10-21: header and footer "State Committee of Turkmenistan on Statistics"; About text "State Committee of Statistics of Turkmenistan" and, in the renaming sentence, "State Statistics Committee of Turkmenistan" | Proposed: add "State Committee of Turkmenistan on Statistics" as a further English rendering, with no dates. Keep the stored name: the site itself uses it. Mark nothing |
| L4 | Low | The entry page grows with the square of the number of institutions | **Open**, measured | Measured on 2026-10-21 (§15.4): 10 institutions 78 KB; 50, 706 KB; 100, 2.3 MB and 1.1 s; 200, 8.0 MB and 3.8 s. The browse page grows linearly (184 KB at 200) | Not changed: a fix changes how the page is used. Recommended in §15.4 |
| L9 | Low | The Ministry's English name is a shortened form | **Open.** An addition is proposed; nothing is entered yet (§15.2) | digital.uz/en, read on 2026-10-21: page title and header "Ministry of Digital Technologies of the Republic of Uzbekistan" | Proposed: add the full form as a further English rendering, with no dates. Keep the short form |
| I1 | Info | Production hardening | Deferred to ADR-0008 (Proposed) | `production.py`; `check --deploy` warnings W004 and W008 (§6) | Not built: needs ADR-0008 |
| I2 | Info | Throttling by `REMOTE_ADDR` | Deferred to ADR-0008 (Proposed) | §6, "Client address for throttling" | Not changed: trust in a reverse proxy needs ADR-0008 |
| I3 | Info | The registry records no source for a name or a date | **Open**; needs an ADR | ADR-0018: registry maintenance states no claim and cites no source. M1 shows the cost | No source field added. The sources of the names in §15.2 are kept in this report only |
| I4 | Info | No page or selector reads the audit record | Deferred by ADR-0018 | ADR-0018, "Not in this milestone" | Not built: a later increment with its own permission |
| I5 | Info | The break-glass command is not recorded operationally | Deferred to ADR-0008 (Proposed) | ADR-0017; CLAUDE.md, "Not implemented" | Not built |
| I6 | Info | Older backups hold account data | Open, housekeeping | `~/caipo-backups/`, all mode `600` | Kept; none deleted, as instructed |
| I7 | Info | Fourteen local branches of merged work | Open, housekeeping | `git branch -vv` at the start | Kept |
| M2 | Medium | "Mark as entered in error" is irreversible and took one click | **Fixed**, merged in #17 (`e0a9cbb`) | Before: `registry_entry.html` line 148, a single submit button. After: a ticked confirmation is required, by the same rule as second-factor approval; tests in `test_registry_entry_safeguards.py` | A ticked confirmation before the mark |
| L1 | Low | A refusal got a bare "403 Forbidden" page | **Fixed**, merged in #17 (`e0a9cbb`) | Before: anonymous GET of `/registry/`, body `<h1>403 Forbidden</h1>`, no `Cache-Control`. After: `caipo/web/errors.py` and `web/403.html`; tests in `test_error_pages.py` | Sign-in link for an anonymous visitor; the second-factor requirement explained where it is what is missing; `no-store`; the refusal itself unchanged |
| L2 | Low | Every refusal was logged twice, once with a traceback | **Fixed**, merged in #17 (`e0a9cbb`) | Before: the same request gave `access.denied` and a `django.request` WARNING with a traceback. After: `ExpectedRefusalFilter` removes the traceback of a `PermissionDenied` only; tests in `test_error_pages.py` | Keep the structured event and the summary line; drop the traceback of an expected refusal; keep the traceback of a server error |
| L3 | Low | Per-institution forms lost what was typed when a change was refused | **Fixed**, merged in #17 (`e0a9cbb`) | Before: `_entry_page` rebuilt the three forms from stored values. After: the form a refused change came from is shown again as sent, with its field errors; tests in `test_registry_entry_safeguards.py` | Show the typed values again |
| L5 | Low | Invisible direction controls were accepted in names | **Fixed**, merged in #17 (`e0a9cbb`) | Before: probe (§6), a name with U+202E accepted. After: the services refuse U+202A to U+202E and U+2066 to U+2069 in every name; tests in `test_direction_controls.py` and `test_registry_entry_safeguards.py` | Refuse the nine controls; allow every letter and the implicit marks U+200E, U+200F, U+061C |
| L6 | Low | Dates were accepted with other digits and without zero padding | **Fixed**, merged in #17 (`e0a9cbb`) | Before: probe (§6), `１２３４-01-01` and `2020-1-1` accepted. After: `FullDateField` takes `YYYY-MM-DD` in ASCII digits only; tests in `test_registry_entry_safeguards.py` | One strict form of date |
| L7 | Low | Protection of `main`: 0 approvals, status checks not strict | **Fixed in the ruleset** on 2026-10-21 (§15.5) | Ruleset 24416842: `strict_required_status_checks_policy` changed from `false` to `true`; every other parameter compared and unchanged | Strict checks on. 0 approvals kept, so that one maintainer can merge |
| L8 | Low | No custom 404 or 500 pages | **Fixed**, merged in #17 (`e0a9cbb`) | After: `web/404.html` and `web/500.html` through `caipo/web/errors.py`; neither shows the path or the exception; tests in `test_error_pages.py` | Plain pages that disclose nothing, with `DEBUG` off (R1, §16) |
| M3 | Medium | Documentation drift | **Fixed**, merged in #16 (`ba8a89e`) | Below; fix in §9 | — |
| M4 | Medium | The development guide advised deleting the database with no warning | **Fixed**, merged in #16 (`ba8a89e`) | Below; fix in §9 | — |

Totals after the merges of §17: 20 findings. **10 fixed**: 2 Medium merged in #16 (M3, M4); 1 Medium (M2) and 6 Low (L1, L2, L3, L5, L6, L8) merged in #17; and 1 Low in the ruleset (L7). **10 open**: 1 Medium (M1), 2 Low (L4, L9), and 7 Informational. Current totals, with M1 and L9 resolved: 10 fixed, 2 resolved, 8 open (§18.2).

### Open findings

**M1. The stored English name of Turkmenistan's statistics body is not the form the body's site uses for itself.**
- Evidence: InstitutionName 3 reads "State Statistics Committee of Turkmenistan". On stat.gov.tm/en/about-us, read on 2026-10-21, the header and footer read "State Committee of Turkmenistan on Statistics". The About text uses "State Committee of Statistics of Turkmenistan", and its renaming sentence uses "State Statistics Committee of Turkmenistan", the stored form.
- Impact: documents will be attributed to this institution. Without the body's own form, matching and citation are weaker.
- Proposed correction: add the header form as a further `english_rendering` in `eng-Latn`, with no dates. The stored name is kept and not marked as entered in error, because the site itself uses it. No date is entered: the page mentions a reorganisation by a decree of 11 October 2007, but it does not say from when each English form is used.
- Status: open. **Nothing has been entered.** Only an account signed in with a trusted second factor can make the entry, and the audit stopped before it (§15.2).
- *Update: resolved on 2026-10-23 in the development registry. The Administrator entered the proposed form as a further English rendering (§18).*
- Limitation of the registry: it cannot say which of several concurrent names of the same kind is the preferred one. A name's kind and text cannot be changed once it is saved (ADR-0018 point 19), and there is no field for preference or for a source. Both are recorded here, not in the model.

**L4. The entry page grows with the square of the number of institutions.** Each institution has a change form whose parent and successor lists name every other institution. Measured in §15.4. Left open with a recommendation.

**L9. The Ministry's English name is a shortened form.** "Ministry of Digital Technologies" against the site's "Ministry of Digital Technologies of the Republic of Uzbekistan". Proposed: add the full form as a further `english_rendering`, with no dates, and keep the short one, which is accurate. Its kind cannot be changed to show that it is the short form. Status: open. **Nothing has been entered** (§15.2). *Update: resolved on 2026-10-23 in the development registry. The Administrator entered the full form as a further English rendering (§18).*

- **I1. Production hardening waits for ADR-0008** (Proposed): HSTS, TLS redirect, the proxy header, trusted CSRF origins, CSP, database roles that stop TRUNCATE and changes to triggers, key storage and rotation, and email delivery. `production.py` lists these itself.
- **I2. Throttling by `REMOTE_ADDR`.** Behind a reverse proxy every client would share one address, and 20 failures from any of them would lock sign-in for everyone. This must be designed with ADR-0008.
- **I3. The registry records no source for a name or a date.** ADR-0018 classes registry maintenance as stating no claim and citing no source. M1 shows the cost: where a name came from is recorded nowhere in the application. Worth a decision, by ADR, before many institutions are entered.
- **I4. No page or selector reads the audit record.** Deferred by ADR-0018 to a later increment with its own permission. Until then it is read by SQL.
- **I5. The break-glass command is not recorded operationally.** Who ran it is not recorded; that waits for ADR-0008.
- **I6. Older backups in `~/caipo-backups/` hold account data.** All are mode `600`. Keep them restricted, and delete those no longer needed. None was deleted by this audit.
- **I7. Fourteen local branches of merged work remain.** Housekeeping only.

### Fixed findings

**M2. "Mark as entered in error" is irreversible and took one click. Fixed, merged in #17 (`e0a9cbb`).**
- Evidence before: `registry_entry.html` posted the mark with a single button. Elsewhere, irreversible administrative actions needed a ticked confirmation (second-factor approval, recovery authorisation).
- Fix: each mark form has a confirmation box, "I have checked that this name was entered by mistake. I understand that the mark cannot be undone." The view refuses the mark with 400, changes nothing, and says why unless the box was ticked. Only what a ticked box sends counts, as for the two existing confirmations. The service and its rules are unchanged.

**L1. A refused request got a bare "403 Forbidden" page. Fixed, merged in #17 (`e0a9cbb`).** The refusal is unchanged: the status is 403 whoever asks, and the access declarations and services decide as before. The page now says what the person can do. An anonymous visitor gets a link to sign in, which brings them back to the page they asked for by GET. An account that would hold the page's declared permission once signed in with a trusted second factor is told that, and given the two-step verification page. Any other account is told only that it has no access. The answer is `no-store`.

**L2. Every refusal was logged twice, once with a full traceback. Fixed, merged in #17 (`e0a9cbb`).** The structured event (`access.denied` or `authorization.denied`) stays, and so does Django's one-line summary of the 403. Only the traceback that Django attached to that summary is removed, and only for `PermissionDenied`. A server error keeps its traceback.

**L3. The per-institution forms lost typed input on refusal. Fixed, merged in #17 (`e0a9cbb`).** A refused change of an institution, a new name, or new dates is shown again in the form it came from, as typed and with its field errors. The other forms still show what is stored.

**L5. Bidirectional control characters were accepted in names. Fixed, merged in #17 (`e0a9cbb`).** The services refuse U+202A to U+202E and U+2066 to U+2069 in the English names of countries and languages and in the names of institutions. Every letter of every script is accepted, Cyrillic, Latin, and Turkmen and Uzbek letters among them, and so are the implicit marks U+200E, U+200F, and U+061C, which reorder nothing around them. The rule is held by the services, as the NUL rule is, and not by a database check. The development database holds no such character (§5).

**L6. Dates were accepted with non-ASCII digits and without zero padding. Fixed, merged in #17 (`e0a9cbb`).** Every date field of the entry page takes `YYYY-MM-DD` in ASCII digits with every part padded, or nothing. `2020-1-1`, full-width and Arabic-Indic digits, surrounding spaces, other separators, and impossible dates are refused before a service is called.

**L7. The ruleset required 0 approvals and non-strict status checks. Fixed in the ruleset on 2026-10-21.** Strict status checks are now on, so a pull request must be up to date with `main`, and its checks must have passed on that, before it can be merged. 0 approvals is kept, because one maintainer could not otherwise merge. Details in §15.5.

**L8. No custom 404 or 500 pages. Fixed, merged in #17 (`e0a9cbb`).** Both are plain pages that show neither the path nor the exception. The 500 page is rendered without the request, so it depends on no session or database. They are what Django answers with `DEBUG` off, as in the testing and production settings. The development settings turn `DEBUG` on, and Django then shows its own diagnostic pages for 404 and 500, with the path, the URL patterns, and the traceback; that is intended for development and is not changed. The 403 page is the same either way (review finding R1, §16).

**M3. Documentation drift. Fixed, merged in #16 (`ba8a89e`).**
- Evidence: README's quick start told a new developer to set "the two passwords and DJANGO_SECRET_KEY", leaving out `TOTP_ENCRYPTION_KEY`. Without it every `manage.py` command stops (DEVELOPMENT.md, "First-time setup"). README's status and DEVELOPMENT.md did not mention the registry. DEVELOPMENT.md said the bootstrap creates "the only account the application can create so far" and that "no page uses" the authorization layer apart from the sign-in and second-factor pages. Both have been untrue since ADR-0015.
- Fix: §9.

**M4. The development guide advised deleting the database with no warning that its data is lost. Fixed, merged in #16 (`ba8a89e`).**
- Evidence: `docs/DEVELOPMENT.md` gave `docker compose down -v`, which deletes the database volume, as the remedy in three places: a changed `POSTGRES_PASSWORD`, starting again after the bootstrap, and a changed TOTP key. A fourth place said "Recreate that database". None said that the registry and the audit record go with it, or how to back up first. None of this was added by the audit branch; the text was on `main` `4bff508`.
- Impact: the development database now holds the owner's research reference data and its audit trail. Following the guide would destroy them, with nothing to restore them from.
- Fix: §9. The command stays in the command list, marked, because it is accurate. A new section, "Deleting the database", says what is lost, that the command never fixes a failing test, and how to back up and check the backup. Each remedy now points to that section instead of naming the command.
- Validation: the backup commands of the new section were run as written, with the output sent to a scratch directory. They produced a mode-600 dump with all 21 table-data entries, and the scratch copy was deleted.

## 9. Fixes made and regression tests

| Finding | Change | Files |
|---|---|---|
| M4 | `docs/DEVELOPMENT.md`: the "Deleting the database" section, with the backup and check steps; the four remedies point to it | `docs/DEVELOPMENT.md` |
| M3 | README status names the audit record and the registry. The quick start names `TOTP_ENCRYPTION_KEY` and points to DEVELOPMENT.md. DEVELOPMENT.md's summary names the registry. The bootstrap is "the first account", not "the only". The authorization section says which pages are public and that every other page declares a permission (checked against the probe's list). A new "The registry" section gives the 15 routes, their permissions, and how a fresh database is filled. | `README.md`, `docs/DEVELOPMENT.md` |
| — | This report | `docs/reports/caipo-full-diagnostic-2026-10-20.md` |

**On the audit branch (#16), no application code, test, migration, setting, or CI file was changed.** Only documentation changed, so no regression test applies here. The application fixes are in #17, below.

After the fixes, every gate was run again on the branch, three times: after the M3 fix (commit `867013e`), after M4 and the first corrections to this report (commit `67d2c68`), and on 2026-10-21 with the findings register added to this report.

| Check | After `867013e` | After `67d2c68` | With the findings register |
|---|---|---|---|
| `uv lock --check`, `ruff check`, `ruff format --check`, `mypy .`, `lint-imports` | Exit 0 each | Exit 0 each | Exit 0 each. `ruff format` counts 185 files: 149 Python and 36 Markdown, one more than on `main` because of this report |
| `manage.py check`; `makemigrations --check --dry-run` | No issues; no changes | No issues; no changes | No issues; no changes |
| Full suite | **4169 passed**, 0 failed, 0 skipped, exit 0, 8 min 48 s | **4169 passed**, 0 failed, 0 skipped, exit 0, 8 min 52 s | **4169 passed**, 0 failed, 0 skipped, exit 0, 10 min 2 s |
| Secret scan (gitleaks, full history) | Exit 0; 40 commits scanned, no leaks | Exit 0; 41 commits scanned, no leaks | Run after the commit. A report cannot hold the scan of the commit that contains it; the result is in the pull request. |

No test reads `README.md`, `docs/DEVELOPMENT.md`, or this report (checked by search), so the documentation changes cannot change a test result.

The follow-up of 2026-10-21 changed only this report on the audit branch. Its checks are in pull request #16, where CI ran the full suite.

### Fixes of 2026-10-21, in pull request #17

On the branch `fix/audit-findings`, from `main` `4bff508`, commit `96f86ab`, followed on 2026-10-23 by `b5c3565` for the review findings R1 to R3 (§16). Merged into `main` on 2026-10-23 as `e0a9cbb` (§17).

| Finding | Change | Files | Regression tests |
|---|---|---|---|
| M2 | A ticked confirmation before a name is marked as entered in error; without it the view answers 400 and changes nothing | `caipo/web/forms.py` (`MarkEnteredInErrorForm`), `caipo/web/registry.py`, `registry_entry.html` | `test_registry_entry_safeguards.py`; the existing page tests now send the confirmation |
| L1 | Error handler for 403: sign-in link for an anonymous visitor, the second-factor requirement where it is what is missing, otherwise "no access"; `no-store`. A read-only selector, `second_factor_would_grant`, answers the question from the policy | `caipo/web/errors.py`, `web/403.html`, `caipo/config/urls.py`, `caipo/accounts/selectors.py` | `test_error_pages.py`, `test_selectors.py`; the assurance inventory in `test_second_factor.py` is extended by this one read-only use and checks that it builds no context |
| L2 | `ExpectedRefusalFilter` on `django.request` removes the traceback of a `PermissionDenied` only | `caipo/core/structured_logging.py`, `caipo/config/settings/base.py` | `test_error_pages.py` (refusal without traceback, server error with it) |
| L3 | The form a refused change came from is shown again as sent, with field errors | `caipo/web/registry.py`, `registry_entry.html` | `test_registry_entry_safeguards.py` |
| L5 | `DirectionControlError`, a kind of `InvalidEntryError`, for U+202A to U+202E and U+2066 to U+2069 in every name; its own message on the page | `caipo/registry/services.py`, `caipo/web/registry.py` | `test_direction_controls.py` (6 operations, 9 characters, 3 positions; Latin, Cyrillic, Turkmen, and Uzbek letters and the implicit marks accepted), `test_registry_entry_safeguards.py` |
| L6 | `FullDateField`: `YYYY-MM-DD`, ASCII digits, zero-padded, or nothing | `caipo/web/forms.py` | `test_registry_entry_safeguards.py` (15 refused forms on all three forms with dates) |
| L8 | Handlers for 404 and 500 and their pages; the 500 page is rendered without the request | `caipo/web/errors.py`, `web/404.html`, `web/500.html` | `test_error_pages.py` |
| — | The rules written down | `docs/DATA_MODEL.md`, `SECURITY.md`, `docs/ARCHITECTURE.md` §10 | — |

No permission, route, model, migration, or dependency is added; there are still 40 routes. Two existing tests that state exact sets were extended for what is new: the set of refusals the institution views answer gains `DirectionControlError`, and the assurance inventory gains one mention. No test was weakened, skipped, or removed.

| Check on `96f86ab` | Result |
|---|---|
| `uv lock --check`, `ruff check`, `ruff format --check` (188 files), `mypy .` (153 files), `lint-imports` (2 kept) | Exit 0 each |
| `manage.py check`; `makemigrations --check --dry-run` | No issues; no changes |
| Full suite (`pytest -rfE --tb=short`) | **4452 passed**, 0 failed, 0 skipped, exit 0, 8 min 51 s |
| Dependency audit (`pip-audit` 2.10.1 on the exported lockfile) | No known vulnerabilities; the lockfile is unchanged |
| Secret scan (gitleaks v8.30.1, full history, after the commit) | Exit 0; 43 commits scanned, no leaks |
| Raw direction controls in the repository's code and documents | None: the tests write them as `\u` escapes |
| CI on GitHub, pull request #17 at `96f86ab` | All four required jobs passed: Code quality, Django checks and tests, Dependency audit, Secret scan |

Two earlier full runs on the branch: the first gave 4451 passed and 1 failed, the assurance inventory, which was then extended as described above; the second gave 4452 passed. Comments and documents were then reworded, and the run above is on the commit that holds them.

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
5. Whether names in the national languages should be added to the three institutions. (The two English names proposed in §15.2 were entered on 2026-10-23: §18.)
6. The new 403, 404, and 500 pages, on `main` since #17 was merged (§17), and the confirmation box of "Mark as entered in error", in a browser. The 404 and 500 pages appear only with `DEBUG` off; under the development settings Django shows its diagnostic pages instead (R1, §16). The 403 page and the confirmation box can be checked under the development settings.

## 13. Outstanding decisions and next steps

As fixes from the findings of this audit: M2, L1, L2, L3, L5, L6, and L8 are fixed and merged in pull request #17 (`e0a9cbb`); M3 and M4 are fixed and merged in pull request #16 (`ba8a89e`); and L7 is fixed in the ruleset. M1 and L9 are resolved in the development registry: the two names of §15.2 were entered on 2026-10-23 (§18).

Still open, with what each needs, in §15.6: I3 (an ADR), a preferred name (an ADR), I4 (a later increment), I1, I2, and I5 (ADR-0008), L4 (a choice between the options of §15.4, refined in §18.4), a database check for L5 (a migration), and the "Update branch" button.

Recommended order of next work (the merges of #16 and #17, their record in this report, the line on the ticked confirmation in `docs/DEVELOPMENT.md`, and the entry of the two names of §15.2 are done: §17, §18):

1. Close the researcher-owned Phase 2 blockers: B22, then B8 and B9, then B7 and B10. Nothing research-related can be built before them.
2. Run the job-system and isolation spikes together (B4, B21), so that ADR-0004 and ADR-0011 can be decided.
3. Before many institutions are entered: decide I3 and the question of a preferred name, and choose a fix for L4 (§18.4).

## 14. Commands run, and checks not performed

**Commands run** (credentials never printed; `.env` passed to `uv run --env-file` and never read):

- `git status`, `git branch -vv`, `git fetch origin`, `git rev-parse HEAD origin/main`, `git switch -c audit/caipo-full-diagnostic`
- `docker info`, `docker compose ps`
- `docker compose exec -T postgres pg_dump --format=custom` (backup); `createdb`, `pg_restore --exit-on-error`, row counts, `dropdb` (restore check in a throwaway database)
- `psql` with `BEGIN TRANSACTION READ ONLY … ROLLBACK` (inspection of §5, and the later check that nothing was written)
- Django's test client, five anonymous GETs under the development settings (§5, §8 L1)
- The backup commands of DEVELOPMENT.md's new section, writing to a scratch directory, and a `pg_restore --list` of the result (M4)
- `uv lock --check`; `uv sync --locked`; `ruff check`; `ruff format --check`; `mypy .`; `lint-imports`
- `manage.py check`; `check --deploy` (development settings, and production settings with synthetic values); `makemigrations --check --dry-run`; `showmigrations`; `migrate --check`
- `pytest` (full, and the two focused runs); the audit probe on an exported copy of HEAD with its own database
- `uv export` and `uvx pip-audit==2.10.1`; gitleaks v8.30.1 in a network-less, read-only container
- `gh auth status`; `gh run list`, `gh run view`; `gh api` (branch protection, rulesets)
- Fetches of the official sites `stat.gov.tm`, `stat.uz`, and `digital.uz`

**Re-checks for the findings register, 2026-10-21, on `67d2c68`** (no application code changed):

- Reading the code behind M2, L2, L3, L4, and L8 (`registry_entry.html`, `caipo/web/registry.py`, `caipo/web/middleware.py`, Django's `response_for_exception`, a search for error templates and handlers)
- `gh api …/rulesets/24416842` and `…/branches/main/protection` (L7)
- Two anonymous GETs of `/registry/` with Django's test client under the development settings, the same kind of request as in §5. The first was refused with 400 because the client's default host, `testserver`, is not an allowed host. The second, with the host `localhost`, gave the status, headers, body, and two log lines recorded for L1 and L2

**Follow-up of 2026-10-21** (§15):

- `git status`, `git fetch`, `gh api …/pulls/16`, `gh run list` (state at the start)
- Fetches of `https://stat.uz/en/about/overview`, `https://stat.gov.tm/en/about-us`, and `https://digital.uz/en`
- `psql` with `BEGIN TRANSACTION READ ONLY … ROLLBACK`: the registry's names, row counts, and a search for direction controls
- A temporary test, deleted afterwards and never committed, that measured both pages with 10 to 200 synthetic institutions in the test database (§15.4)
- `gh api` GET, PUT, and GET again of ruleset 24416842, with the before and after compared field by field (§15.5)
- On `fix/audit-findings`: `ruff`, `mypy`, `lint-imports`, `manage.py check`, `makemigrations --check`, focused `pytest` runs, and the full suite (§9)

**Not performed, and why:**

- Browser end-to-end testing: no browser automation was available (§12).
- Line-by-line review of `caipo/accounts/services.py` (3049 lines): spot-checked only; its behaviour rests on its tests.
- Reversing a migration on the development database: not done, because it destroys data. Reversibility is shown by the migration tests, which run on the test database.
- Any write to the development database: none was needed during the audit, because both agencies existed. In the follow-up, the two names of §15.2 were not entered, because only the Administrator signed in with a second factor may enter them, and doing it without them would bypass the second factor and the audit record. None was made.
- A browser check of the pages changed in #17: no browser automation was available (§12).
- A secret scan of uncommitted files: gitleaks scans commits only, as in CI. The branch is scanned after committing (§9).
- The production configuration: none exists (ADR-0008).

Detailed logs are kept outside the repository, in the session scratchpad (`logs/`). They contain no secrets: pytest output is filtered for `password=`, and the log was searched for secret-looking strings.

## 15. Follow-up of 2026-10-21

*A dated record: it keeps the state of 2026-10-21. Both pull requests named here were merged on 2026-10-23 (§17).*

On 2026-10-21 the project owner asked for the confirmed findings to be fixed where an Accepted ADR allows it, for the names of the institutions to be brought in line with named official sources, and for every finding to carry its status, severity, evidence, and outcome. This section records what was done and what was not, and why.

### 15.1 State at the start

The branch `audit/caipo-full-diagnostic` was clean at `eee1a09`, pull request #16 was open with all four CI jobs passed, and `main` was at `4bff508`. The fixes were made on a new branch, `fix/audit-findings`, from `main`, and are in pull request #17. Neither pull request is merged.

### 15.2 Names of institutions

The official sites named by the owner were read on 2026-10-21, through an automated fetch that turns a page into text:

| Institution | Source | What it shows | Stored now | Proposed |
|---|---|---|---|---|
| National Statistics Committee of the Republic of Uzbekistan | https://stat.uz/en/about/overview | Overview, full official name: "National Statistics Committee of the Republic of Uzbekistan"; the same in the footer | The same text, `english_rendering`, `eng-Latn` | Matches. No change |
| Turkmenistan's statistics body | https://stat.gov.tm/en/about-us | Header and footer: "State Committee of Turkmenistan on Statistics". About text: "State Committee of Statistics of Turkmenistan", and "State Statistics Committee of Turkmenistan" in the sentence on its renaming | "State Statistics Committee of Turkmenistan", `english_rendering`, `eng-Latn` | Add "State Committee of Turkmenistan on Statistics" as `english_rendering` in `eng-Latn`, no dates. Keep the stored name. Mark nothing |
| Ministry of Digital Technologies | https://digital.uz/en | Page title and header: "Ministry of Digital Technologies of the Republic of Uzbekistan" | "Ministry of Digital Technologies", `english_rendering`, `eng-Latn` | Add the full form as `english_rendering` in `eng-Latn`, no dates. Keep the short form |

These links are kept in this report. **They are not stored in the registry**, which has no field for a source (I3).

**What the registry can and cannot say.** It can hold several English renderings of one institution, each with its own dates, so both corrections fit without breaking an invariant. It cannot say which of several concurrent renderings is the preferred or current one, and it cannot record that a form is short: a name's kind and text are set once (ADR-0018 point 19), and the kinds are `official`, `transliteration`, `english_rendering`, and `abbreviation`. No validity date was entered, because no source gives the first day on which a form was used. The 2007 decree that the Turkmen page mentions is a reorganisation, not the start of an English form.

**Why the two names were not entered by the audit.** Every registry write goes through a service that requires `registry.institutions.manage`, and the only account in the development database is the Administrator, who holds it only when signed in with a trusted second factor. The audit has neither that account's password nor its authenticator. A context claiming a verified second factor could be built in a Django shell from the device's identifier alone. That would pass the check without anyone entering a code, and the audit events would name the Administrator for changes they did not make. That is a bypass of the second factor and of the audit record, so the operation was stopped there. No data was changed, so no backup was needed and none was made. A read-only query on 2026-10-21 showed the registry as in §5: 2 countries, 5 languages, 3 institutions, 3 names, 16 audit events, and no name holding a direction control.

**Steps for the owner**, through the supported page:

1. Sign in at `/login/` with your password and a code from your authenticator.
2. Open `/registry/entry/`.
3. Under the Turkmenistan statistics body, in "Add a name", enter `State Committee of Turkmenistan on Statistics`, choose the English language in Latin script, choose the kind "English rendering", leave both dates empty, and add it.
4. Under the Ministry of Digital Technologies, in "Add a name", enter `Ministry of Digital Technologies of the Republic of Uzbekistan` in the same way.
5. Mark nothing. Each addition writes one `created` audit event for an institution name, under your account.

The third form on the Turkmen page, "State Committee of Statistics of Turkmenistan", is attested too. It was not part of the decision and is not proposed for entry.

### 15.3 Application fixes

M2, L1, L2, L3, L5, L6, and L8 are addressed in pull request #17, which is open and not merged, as §8 describes and §9 lists. Each is within an Accepted ADR: the entry page and the browse page remain the only registry pages (ADR-0018 point 59), every view keeps its access declaration, and no permission, route, model, migration, or dependency is added. The settings change only the logging configuration, and the root URL configuration only names the three error handlers. No service gains or loses a permission check. The new rules for names and dates are fixes from the findings L5 and L6, and are written into `docs/DATA_MODEL.md` and `SECURITY.md` in #17.

### 15.4 L4, measured

The entry page and the browse page were requested by a verified Administrator in the test database, with synthetic institutions created through the services:

| Institutions | Entry page | `<option>` elements | Time to answer | Browse page |
|---|---|---|---|---|
| 10 | 78 KB | 376 | 0.09 s | 10 KB |
| 50 | 706 KB | 5,816 | 0.33 s | 47 KB |
| 100 | 2.3 MB | 21,616 | 1.14 s | 93 KB |
| 200 | 8.0 MB | 83,216 | 3.75 s | 185 KB |

The growth is quadratic, as expected: each institution's change form offers every other institution twice, as parent and as successor. With 3 institutions it costs nothing. **Not fixed**: every fix changes how the page is used, which the owner asked not to do without need. Recommended, in order of preference: show the change form of one institution at a time on the same entry page, chosen by a link (a query parameter, so still two pages and no ADR); or paginate the institutions on the entry page. A page for each institution would need an ADR, because ADR-0018 allows two pages.

### 15.5 L7, the ruleset

The ruleset "Protect main" (24416842) was read, changed in one parameter, and read again on 2026-10-21:

| Parameter | Before | After |
|---|---|---|
| `strict_required_status_checks_policy` | `false` | `true` |
| `required_approving_review_count` | 0 | 0, unchanged |
| Required checks | Code quality, Dependency audit, Secret scan, Django checks and tests | Unchanged |
| Deletion and force push | Blocked | Unchanged |
| Bypass actors | None | Unchanged |

Why it is safe: CI runs on every pull request to `main`, with no path filter, so the required checks always run; `required_approving_review_count` is 0; nobody can bypass it. What it costs: when two pull requests are open, merging one makes the other out of date, and it must be updated from `main` and pass CI again before it can be merged. The repository's "Update branch" button is off (`allow_update_branch: false`), so that is done with git. Turning the button on is recommended and was not done.

**Other parameters of the rule for pull requests**, read on 2026-10-23. They are not in the table above; the comparison of 2026-10-21 found every parameter other than the strict policy unchanged.

| Parameter | Value |
|---|---|
| `required_review_thread_resolution` | `true` |
| `require_extra_approval_for_unattributed_changes` | `true` |
| `dismiss_stale_reviews_on_push`, `require_code_owner_review`, `require_last_push_approval` | `false` |
| `allowed_merge_methods` | merge, squash, rebase |

Observed effect, and only that: neither pull request has a review, a review comment, or a review thread, and on 2026-10-23 GitHub reported both as mergeable, with merge state `CLEAN`. Neither parameter was blocking a merge then. `required_review_thread_resolution` blocks a merge while a review thread is unresolved; that has not arisen. What `require_extra_approval_for_unattributed_changes` requires, and when, was not tested and is not stated here: no merge has been attempted on GitHub. A merge of #17 was attempted from the agent's session on 2026-10-23 and was stopped by the agent's own local safety check before any request reached GitHub, so it says nothing about the ruleset.

### 15.6 Decisions that still need an ADR or the owner

- **I3**: a source for a registry name or date. ADR-0018 says registry maintenance cites no source, so this needs a new ADR.
- **A preferred name** among concurrent names of one kind, or a "short form" kind. A field or kind on InstitutionName that ADR-0018 does not have; needs an ADR.
- **I4**: a page or selector that reads the audit record, with its own permission (ADR-0018, a later increment).
- **I1, I2, I5**: production configuration, trust in a reverse proxy, and the operational record of the break-glass command, all with ADR-0008 (Proposed).
- **L4**: which of the options in §15.4.
- **L5, in the database**: whether the rule on direction controls is also held by a database check, as the forms of the codes are. It would need a migration.
- **The "Update branch" button**: whether to turn it on (§15.5).

## 16. Review of pull request #17, and corrections, 2026-10-23

*A dated record: it keeps the state of 2026-10-23 before the merges. Both pull requests were merged later that day (§17).*

### 16.1 State

Before any change on 2026-10-23: `main` at `4bff508`; #16 open at `92bf1bd`; #17 open at `96f86ab`. All four required checks had passed on each head commit; CI's test job reported 4169 passed on `92bf1bd` and 4452 passed on `96f86ab`. **Neither pull request is merged.**

A read-only query of the development database (`BEGIN TRANSACTION READ ONLY … ROLLBACK`) showed it as in §5 and §15.2: 2 countries, 5 languages, 3 institutions, 3 names, 16 audit events, and 3 change records; no name of a country, language, or institution holding a direction control; the latest audit event at 2026-10-20 17:56 UTC. **The two names of §15.2 are not entered.** The three official sites of §15.2 were read again the same day, through the same kind of automated fetch, and show the forms quoted there.

### 16.2 Review of #17

A review of the whole diff of #17, made on 2026-10-23 by an AI agent (Claude Code) at the owner's request, found no blocker and three Low findings. All three are addressed in #17, at `b5c3565`:

| ID | Finding | Change |
|---|---|---|
| R1 | `SECURITY.md` said that the 404 and 500 pages show neither the path nor the exception. That holds only with `DEBUG` off | `SECURITY.md` says so, and that the development settings show Django's diagnostic pages instead; the development settings are unchanged. A test checks that the 403 page is the same with `DEBUG` on. This report says the same in L8 and §12 |
| R2 | The test that the 500 page is rendered without the request would also have passed had it been rendered with it | The test's request raises on any attribute read other than Python's own dunder lookups, and the rendered context must not be built from a request. The test was shown to fail when the handler was made to render with the request; the handler was then restored |
| R3 | The comment on the logging configuration said that a refusal is logged once | It says that Django's summary line of a refusal stays without its traceback, and that the structured denial event stays too |

One observation is not a defect and is left: a refused rename of a country or a language does not show the typed name again. L3 covered the institution forms only.

### 16.3 Corrections to this report

- Every status is in one of three groups: fixed (on this branch, or in the ruleset), addressed in open #17, or open (§1, §8, §13, §15.3). No fix that exists only in #17 is counted as on `main`.
- The ruleset's other parameters, and what was and was not observed of them (§15.5).
- R1 in L8 and §12.
- Rechecked against the diffs of both pull requests and the settings on GitHub: 20 findings, with the same IDs in every version of this report since M4 was added; 4 Medium, 9 Low, 7 Informational; 3 fixed, 7 addressed in open #17, 10 open.

### 16.4 What waits for the merge of #17

The table of registry routes in `docs/DEVELOPMENT.md` says that marking a name as entered in error is refused for an institution's only unmarked name. It does not yet say that the mark needs the ticked confirmation, because that behaviour is not on `main` until #17 is merged, and this branch does not hold its code. The line is added when this branch is brought up to date with `main` after #17 is merged, together with the record of that merge in this report. *Done on 2026-10-23, after the merges (§17).*

## 17. Merges of pull requests #16 and #17, 2026-10-23

*A dated record: it keeps the state of 2026-10-23 after the merges. The two names of §15.2 were entered later that day (§18).*

### 17.1 What was merged

Both pull requests were merged by the project owner on 2026-10-23, read from GitHub after the merges:

| Pull request | Final head | Merged (UTC) | Merge commit on `main` | Method |
|---|---|---|---|---|
| #16, the audit and the documentation fixes | `17a8d92544373c8e9251d39896467f6a02d5ea45` | 05:57:05 | `ba8a89ec01e104b58949b38d523d8e67e85dbb0f` | Squash |
| #17, the application fixes | `f4a23b02667ef6ef17154fc2e0d3b4fb30be1884` | 06:11:39 | `e0a9cbbf24e3eec0575bafa24227a790225012ea` | Squash |

#16 was merged first. #17 was then brought up to date with `main` by the merge commit `f4a23b0`, as the strict status checks require (§15.5). Compared with `b5c3565`, the head reviewed in §16, `f4a23b0` changes only the three files of #16: `README.md`, `docs/DEVELOPMENT.md`, and this report. The tree of `main` at `e0a9cbb` is the tree of `f4a23b0`.

All four required checks passed on each of these commits:

| Commit | Code quality | Django checks and tests | Dependency audit | Secret scan |
|---|---|---|---|---|
| `17a8d92` (#16 head) | Passed | Passed, 4169 tests | Passed | Passed |
| `ba8a89e` (`main` after #16) | Passed | Passed, 4169 tests | Passed | Passed |
| `f4a23b0` (#17 head) | Passed | Passed, 4454 tests | Passed | Passed |
| `e0a9cbb` (`main` after #17) | Passed | Passed, 4454 tests | Passed | Passed |

### 17.2 Status of the findings after the merges

Rechecked against `main` `e0a9cbb`, finding by finding:

| Group | Findings |
|---|---|
| Fixed, merged in #16 (`ba8a89e`) | M3, M4 |
| Fixed, merged in #17 (`e0a9cbb`) | M2, L1, L2, L3, L5, L6, L8 |
| Fixed in the ruleset, in force since 2026-10-21 | L7 |
| Open | M1, L9 (the two names of §15.2, not entered); L4 (§15.4); I1, I2, I5 (ADR-0008); I3 (needs an ADR); I4 (deferred by ADR-0018); I6, I7 (housekeeping) |

20 findings: 10 fixed and 10 open. No finding was added or withdrawn by the merges.

### 17.3 Changes made after the merges

- `docs/DEVELOPMENT.md`: the registry table says that marking a name as entered in error needs the ticked confirmation, and that without it the answer is 400 and nothing changes (§16.4).
- This report: the statuses of §1, §8, §9, §12, and §13; the notes at the head of §15 and §16; and this section.

Documentation only. No application code, test, migration, setting, or CI file changed.

### 17.4 Registry data

A read-only query of the development database on 2026-10-23, after both merges, in a session with `default_transaction_read_only` on, showed it as in §5, §15.2, and §16.1: 2 countries, 5 languages, 3 institutions, 3 names, and 16 audit events. **Neither name proposed in §15.2 has been entered.** They wait for an Administrator signed in with a trusted second factor at `/registry/entry/`, as §15.2 describes.

### 17.5 What remains

1. Enter the two names of §15.2.
2. The browser checks of §12, the new pages of #17 among them.
3. The decisions of §15.6, and the open findings above.

## 18. Follow-up of 2026-10-24: the two institution names, and L4 measured again

*A dated record: it keeps the state of 2026-10-24.*

### 18.1 The two names, as entered

On 2026-10-23 the two English renderings proposed in §15.2 were entered in the development registry, through the entry page, by the Administrator account. The authentication record shows a sign-in verified with a second factor at 20:10 UTC, the minute before the first entry. A read-only query on 2026-10-24, in a session with `default_transaction_read_only` on, showed:

| Table | Rows |
|---|---|
| Country | 2 |
| Language | 5 |
| Institution | 3 |
| InstitutionName | 5 |
| AuditEvent | 18: 15 `created` (2 countries, 5 languages, 3 institutions, 5 names) and 3 `updated` (languages) |
| AuditEventChange | 3 |
| User | 1 |

| Institution | Name added | Kind | Language | Dates | Audit event (UTC) |
|---|---|---|---|---|---|
| Turkmenistan's statistics body | State Committee of Turkmenistan on Statistics | `english_rendering` | `eng-Latn` | None | One `created`, 2026-10-23 20:11 |
| Ministry of Digital Technologies | Ministry of Digital Technologies of the Republic of Uzbekistan | `english_rendering` | `eng-Latn` | None | One `created`, 2026-10-23 20:13 |

**Checks, all passed:** each text is the form proposed in §15.2, character for character, and is in NFC. Neither new name has a date or is marked. The earlier names are kept and are not marked. Each new name has exactly one `created` event, with a correlation ID, by the one account. No audit event names a record that does not exist. Every institution has a name that is not marked, and no institution has a date, a parent, or a successor. Nothing was written to the database by this follow-up.

### 18.2 Status of the findings, 2026-10-24

| Group | Findings | Count |
|---|---|---|
| Fixed, merged in #16 (`ba8a89e`) | M3, M4 | 2 |
| Fixed, merged in #17 (`e0a9cbb`) | M2, L1, L2, L3, L5, L6, L8 | 7 |
| Fixed in the ruleset, in force since 2026-10-21 | L7 | 1 |
| Resolved in the development registry on 2026-10-23 | M1, L9 | 2 |
| Open | L4 (§18.4); I1, I2, I5 (ADR-0008); I3 (needs an ADR); I4 (deferred by ADR-0018); I6, I7 (housekeeping) | 8 |

20 findings: 10 fixed, 2 resolved, and 8 open. The audit's count after the merges of §17 was 10 fixed and 10 open. The register of §8 is kept as it stood then. No finding was added or withdrawn.

M1 and L9 are counted as resolved and not as fixed because no code changed. The names are data in the development database, which is not in the repository. A new database starts with an empty registry (ADR-0018 point 58) and would not hold them.

### 18.3 What the names do not resolve

- **I3 stays open.** This report records what the official sites showed: stat.gov.tm/en/about-us and digital.uz/en, read through an automated fetch on 2026-10-21 and again on 2026-10-23 (§15.2, §16.1). Those are source facts held in this report. The registry stores the names only. It records no source, no date of reading, and no link for any name, so where these forms came from cannot be traced from the application.
- **A preferred name is still not recorded.** Each of the two institutions now has two concurrent English renderings, and the registry cannot say which is preferred (§15.6). An institution is labelled by its first unmarked name (`InstitutionEntry.label`), so another institution's parent or successor list still shows the earlier forms, "State Statistics Committee of Turkmenistan" and "Ministry of Digital Technologies".
- **Names in the national languages** were not entered or checked (§12, item 5).

### 18.4 L4, measured again

The measurement of §15.4 was repeated on `main` `e025567` with a test kept outside the repository. It ran on an exported copy with its own test database and was never committed. The test created synthetic institutions through the services and requested both pages as a verified Administrator. Times are the median of three requests.

| Institutions | Entry page | `<option>` elements | Share in parent and successor lists | Time | Queries | Browse page | Browse time | Browse queries |
|---|---|---|---|---|---|---|---|---|
| 10 | 85 KB | 387 | 26% | 0.07 s | 22 | 11 KB | 0.01 s | 16 |
| 50 | 824 KB | 5,867 | 67% | 0.36 s | 22 | 49 KB | 0.02 s | 16 |
| 100 | 2.7 MB | 21,717 | 80% | 1.18 s | 22 | 97 KB | 0.02 s | 16 |
| 200 | 9.8 MB | 83,417 | 89% | 4.37 s | 22 | 193 KB | 0.03 s | 16 |

The figures are slightly above those of §15.4 because the synthetic names were longer and #17 added a confirmation box to every mark form. The growth itself is the same.

**Where it comes from.** The number of queries does not depend on the number of institutions: `selectors.institutions` reads institutions and names in two queries. All the growth is in rendering. Each institution's change form (`_institution_sections` in `caipo/web/registry.py`) offers every other institution twice, as parent and as successor: 2 × N × (N − 1) options, 79,600 of the 83,417 at 200. A refused POST renders the same page again, so a refusal costs the same.

**Recommended, the smallest change that keeps the ADRs:** the first option of §15.4, made concrete. The entry page shows the change form of at most one institution, chosen by a query parameter on the same URL (`/registry/entry/?change=<public id>`), and every other institution has a link to open its form. A refused change opens the form it came from, so L3 still holds. The add-a-name, dates, and mark forms and the creation form are unchanged. The view, its access declaration, the routes (still 40), the permissions, the models, the migrations, and the dependencies are unchanged, and no JavaScript is added. The parent and successor lists then grow linearly: at 200 institutions, an estimated 400 options (about 45 KB) instead of 79,600. The rest of the page is already linear: about 1.1 MB at 200, and less once the other fields of the change forms that are no longer shown go too.

ADR-0018 point 59 and ADR-0019 point 16 allow two pages and no others. A query parameter selects what the entry page shows and adds no page. This report reads it that way, and the owner should confirm that reading before the work starts.

**Not recommended:**

- Pagination: each page is still quadratic in its own size, and it splits a list that is short today.
- A page for each institution: a third page, which needs an ADR.
- An HTMX fragment: it needs another endpoint, and HTMX is not installed.
- Response compression: it reduces neither the rendering time nor the size of the page in the browser, and compressing pages that hold a CSRF token raises the BREACH question.
- One shared `<datalist>`: it turns a choice into free text of identifiers.

**Test plan for the change:**

1. Without `change`, the page holds no institution change form, and each institution has a link to its form.
2. With `change=<public id>`, the page holds exactly that institution's form, with its stored values selected, and the institution is not offered as its own parent or successor. `test_the_entry_page_shows_each_institution_with_what_is_stored` in `test_registry_institution_pages.py` makes its request with the parameter. Its assertions are unchanged.
3. Linear growth: with N and 2N synthetic institutions, the exact `<option>` count follows a linear formula, and the number of queries is the same for both.
4. A `change` value that is not a UUID, names no institution, names a name, is repeated, or is very long gives the page with no form open: never a 500, and the value is never shown back.
5. A refused change of an institution opens its form with the typed values and the same status. The existing L3 tests in `test_registry_entry_safeguards.py` pass unchanged.
6. Access is unchanged. The parameter gives nothing to an anonymous visitor or an account without `REGISTRY_INSTITUTIONS_MANAGE`, and the route count in `test_break_glass_unreachable.py` stays 40.
7. A successful change still redirects to `?saved=1`.
8. The full suite, `ruff`, `mypy`, and `lint-imports` pass, and the new link text is marked for translation.

### 18.5 Changes and checks

This report only: the note at its head, §1, the note above the register and the totals in §8, the M1 and L9 entries in §8, §12 item 5, §13, the note at the head of §17, and this section. No application code, test, migration, setting, CI file, or database row changed.

Commands run: `gh pr view 18`; `git fetch`, `git status`, `git worktree list`; `psql` in sessions with `default_transaction_read_only` on (counts, the names with their audit events, and the authentication event types after 19:30 UTC on 2026-10-23); `git archive` of `e025567` into a scratch directory and the measurement test run there with its own database; reading `caipo/web/registry.py`, `caipo/web/forms.py`, `registry_entry.html`, `caipo/registry/selectors.py`, ADR-0010, ADR-0018, and ADR-0019.
