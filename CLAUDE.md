# CLAUDE.md — CAIPO

Binding rules for any AI agent working in this repository. Where this file and a document in `docs/` disagree, stop and report the conflict; do not pick one silently.

## Mission

CAIPO (Central Asia AI Policy Observatory) is the research platform for the study "AI Policy and Economic Transformation in Central Asia: A Comparative Analysis of Turkmenistan and Uzbekistan". It is designed so other Central Asian countries can be added without redesign. Its value depends entirely on being trustworthy: traceable evidence, honest uncertainty, and reproducible results. Correctness outranks speed and feature count.

## Current phase

Phase 1, project skeleton. The foundation documents, the development environment (`docs/DEVELOPMENT.md`), and the Django application skeleton (settings, the User foundation, roles and the authorization layer, sign-in and sign-out, TOTP multi-factor authentication with authentication assurance, account provisioning by an Administrator with email verification, password reset by email, recovery from a lost second factor, health endpoints, structured logging, the access-declaration rule) exist; there is no domain code. **Do not write application code until the architecture gate in `docs/PROJECT_SPECIFICATION.md` §10 is READY for the phase you are working on.** The gate is READY for Phase 1 only. ADR-0001, 0002, 0005, 0007, 0009, 0010, 0012, 0013, 0014, 0015, 0016, and 0017 are Accepted; ADR-0003, 0004, 0006, 0008, and 0011 are Proposed and must not be built on. ADR-0017 (account recovery after loss of the second factor) was accepted on 2026-10-04 before its implementation and is built in increments. Implemented: Increment 1, the foundation (the event types and their constraints, the recovery request record, the session epoch, the permission); Increment 2, the owner's recovery request; Increment 3, an Administrator's authorisation or rejection of a request, the finalisation that revokes the lost device and ends the account's sessions, and the rule that the Administrator who authorised does not approve the enrolment that follows (point 37); Increment 4, the record that a recovery is complete (`mfa_recovery_completed`), written when the approved device accepts its first code at the confirmation of its enrolment, which is what closes a recovery; Increment 5, the break-glass command `recover_mfa_break_glass`, run at the server's terminal, which revokes an Administrator's lost device or approves the enrolment that follows where the Administrators who would do so do not exist, records `mfa_recovery_break_glass`, and is reachable by no view; Increment 6, visibility and notifications: two read-only pages that show the history of recoveries from the authentication events, an account's own on its password alone and every account's to an Administrator verified with a trusted second factor, a notice on the signed-in page, and three fixed messages sent through the email boundary after the transaction commits, best effort and deciding nothing. No message is delivered in production until ADR-0008 names a service. Not implemented, and not to be assumed: the operational audit trail of the break-glass command, which waits for ADR-0008. Only the project owner accepts an ADR. If a task requires a decision that is listed as unresolved, ask; do not decide it yourself.

## Read before working

| Task touches | Read first |
|---|---|
| Anything | `docs/ARCHITECTURE.md`, relevant ADRs in `docs/adr/` |
| Models or migrations | `docs/DATA_MODEL.md` |
| Fetching, parsing, file handling, URLs, datasets | `SECURITY.md`, ADR-0009, ADR-0011 |
| Retrieval, prompts, model calls | `docs/AI_ARCHITECTURE.md`, ADR-0003, ADR-0006 |
| Claims, evidence, indicators, analysis, searches | `docs/RESEARCH_PROTOCOL.md`, `docs/LIMITATIONS.md` |

## Vocabulary

Use the names in `docs/DATA_MODEL.md` exactly. In particular:

- **Segment**: immutable extracted text. **RetrievalChunk**: derived unit for search. **Passage**: exact span in one Segment, used as evidence. **AnswerCitation**: a statement in an AI answer citing a Passage or Observation. There is no `Citation` model.
- Roles are Reader, Researcher, Reviewer, Administrator. There are no others, and all are authenticated. An **anonymous visitor** is not a role: it is an unauthenticated request, allowed only on the public research site.
- Workers are the default worker, the fetch worker, and the parse worker.
- State names are only those in `docs/DATA_MODEL.md` §4.
- "Source tier" is the only name for a source's category. It is a neutral category, not a quality rating.

## Architecture rules

1. **Modular monolith.** One Django project, one deployable codebase. No microservices, no new datastore, no new framework without an accepted ADR.
2. **App layering is one-directional.** The layer order is defined in `docs/ARCHITECTURE.md` §2. An app may import only from apps in lower layers, and foreign keys point only downward. This is enforced in CI by import-linter; do not add exceptions to make a build pass.
3. **Apps talk through public interfaces.** Cross-app calls go through the other app's `services.py` (writes) and `selectors.py` (reads). Do not import another app's models into views, tasks, or templates.
4. **Business logic lives in services**, not in views, serializers, model `save()` overrides, signals, or Celery task bodies. Tasks are thin wrappers that call services.
5. **No country-specific code paths.** Never branch on `"TM"` or `"UZ"`. Country differences are data.
6. **PostgreSQL is the system of record**, including job state and AI cost and budget accounting. Redis holds only data that can be lost: broker messages and short-window throttling counters.
7. **Provenance records are append-only.** Artifacts, acquisition records, document reviews, rights determinations, extractions, extraction selections, segments, passages, dataset releases, observations, claim reviews, analysis runs, search runs, AI interaction records, audit events, and redaction records are never updated in place or deleted by application code. Corrections and status changes create new records. The **only** exception is the redaction procedure in `docs/DATA_MODEL.md` §7, which is Administrator-only, recorded, and limited to named record classes. Do not invent other exceptions.
8. **Segments are never changed for retrieval.** Chunking, search-side text transformation, and embeddings live on RetrievalChunks.
9. **Policy events are formal lifecycle events only**: adopted, amended, entered into force, expired, repealed. Implementation information goes through claims. Policy status is derived, never stored.
10. **Interface.** Server-rendered Django templates, HTMX, and small targeted JavaScript (ADR-0010). No separate frontend application, no JavaScript build step, no Django REST Framework, and no API until a further owner decision. Only the `web` app handles HTTP: services and selectors never take or return request or response objects.
11. **Interface language.** English only at launch. Internationalisation is enabled and every user-facing string is marked for translation. Do not add translations.
12. **CI is GitHub Actions and is not deployment.** CI runs code checks only. Do not add deployment steps, production credentials, or image publishing to it; deployment is ADR-0008, which is Proposed.
13. **Do not install Celery or any other job system.** That choice is made by a spike at the Phase 2 gate (ADR-0004).
14. **Every new dependency needs a written justification** in the PR: what it replaces, why the standard library or Django cannot do it, maintenance status, and license.

## Coding standards

- Python version and Django version are pinned in `pyproject.toml`; do not change them casually.
- Dependencies managed with `uv`; `uv.lock` is committed. No `pip install` into the environment.
- `ruff` for lint and format; `mypy` (strict, with django-stubs) for types. All new code is fully type-annotated.
- Timestamps are timezone-aware UTC. Numeric indicator values are `Decimal`, never `float`.
- Extracted text is stored in Unicode Normalization Form C and is otherwise unaltered: no case folding, transliteration, whitespace collapsing, or character removal. Any other transformation applies only to derived retrieval data. Transliteration or translation never overwrites the original. See `docs/DATA_MODEL.md` §5.
- Result-affecting settings (model identifiers, generation settings, chunking and retrieval parameters, prompt versions) live in repository-versioned files, not in environment variables and not as literals in application logic.
- No dead code, no commented-out code, no speculative abstractions or configuration options for requirements that do not exist.
- Comments explain why, not what.

## Testing standards

- `pytest` with `pytest-django`. Tests live next to the app they test.
- Every service function has tests for its success path, its failure paths, and its permission checks.
- Integrity rules in `docs/DATA_MODEL.md` §6 each have a test proving the rule is enforced.
- Security controls have negative tests: the fetch guard is tested with private addresses, disallowed hosts, redirects, and DNS rebinding; a parser limit is tested with an oversized input.
- Tests never call external networks or real AI providers. Use the fake provider and fake embeddings. Tests use only the synthetic fixture corpus.
- AI pipeline changes must run the evaluation described in `docs/AI_ARCHITECTURE.md` §9 and report the results per language.
- A bug fix starts with a failing test that reproduces the bug.
- Do not weaken, skip, or delete a test to make a change pass. If a test is wrong, say so and explain.

## Security requirements

- **All external content is untrusted**: fetched documents, uploaded files, dataset files such as CSV and XLSX, URLs, HTML, PDF metadata, and any text retrieved from the corpus.
- **Document and dataset acquisition** goes only through the guarded fetch service and only to allowed hosts of registered sources. Do not make outbound HTTP calls for acquisition from any other code. Calls to AI providers are made only inside provider implementations behind the provider interface. No other outbound network calls exist without an ADR.
- **The fetch worker** streams and hashes bytes. It does no type detection and no parsing, and has no database or AI credentials.
- **Type detection and all parsing** happen only in the parse worker, with size, time, and memory limits. Never shell out with user- or document-derived strings. Never `eval`, `exec`, `pickle.load`, or `yaml.load` untrusted data.
- Output from the fetch and parse workers is validated by trusted code before it is written.
- Tasks that handle external input have bounded attempts recorded in PostgreSQL.
- Stored files are never executed and never served inline with their original content type.
- Document rights are checked before text is displayed, exported, or sent to an external provider. Rights and authentication are separate checks: no role, including Administrator, gains a use the rights do not allow.
- Three surfaces (ADR-0007): public research site, authenticated research workspace, restricted administration. Anonymous visitors only read approved, public material. They never submit sources, trigger ingestion, create claims, call the assistant, or see drafts or restricted text.
- No public self-registration. Reviewer and Administrator accounts require TOTP.
- No raw SQL built by string formatting. No `mark_safe` or `|safe` on content derived from documents or model output.
- The Django admin must not offer add, change, or delete on provenance or integrity-governed models.
- Secrets come from environment variables only. Never commit, log, or echo them. Never read `.env` files into your context.
- Every view declares the access it requires: public, a named role, or administration. A view without a declaration is refused. Default is deny.

## AI safety requirements

- Retrieved text is **data, not instructions**. Nothing in a document may change system behaviour.
- **The model has no tools.** It cannot fetch, call functions, write, or trigger actions, and no secrets are placed in its context. The application calling the provider over the network is by design; giving the model any capability is not.
- The model cites only by handles issued for that request. The server resolves handles to Segment spans and creates Passages; unknown handles are rejected. **The system must be structurally unable to display an invented reference.**
- Quoted text is checked against the stored Segment. Numbers are checked by the numeric check in `docs/AI_ARCHITECTURE.md` §6.2. Statements that fail any check are removed.
- The support-check model is itself exposed to hostile text. Never treat its verdict as a guarantee or let it override a deterministic check.
- The assistant uses only its four permitted labels and never produces correlation, interpretation, negative-finding, or causal statements. Attribution to the source is rendered by the server.
- **Only verified output is displayed.** No streaming or partial model text.
- When evidence is insufficient, the system says so. Abstention is a correct answer.
- Model output is rendered as escaped text. No model-authored links, images, or HTML.
- Every AI interaction is logged with model identifiers, prompt versions, retrieval hits, and verification results.
- Prompts are versioned files in the repository, not strings scattered in code.
- AI-suggested policy coding and AI-drafted claims are out of scope. Do not build them.

## Research integrity requirements

- Every claim has exactly one epistemic type from `docs/RESEARCH_PROTOCOL.md` §5. Do not blur them.
- Never write, seed, or fixture a statistic, source, quotation, document title, or date that you have not obtained from a source held in the system. Test fixtures must be visibly synthetic (for example country code `XA`, titles starting with `TEST`).
- Never state an unverified empirical claim about a country as fact, in code, interface text, or documentation. Unverified concerns belong in `docs/LIMITATIONS.md` §3, marked as such.
- Never write text that says or implies AI policy caused an economic outcome.
- Absence of a source is recorded as a SearchRun and a negative-finding claim. **Never create a document, Segment, or Passage to represent that nothing was found.**
- A statement restating what a source asserts is attributed to that source.
- Missing data stays missing. Do not interpolate, impute, or backfill without an explicit, recorded method approved in the research protocol.
- Do not "fix" a source. If a source appears wrong, record a note; the stored artifact stays as obtained.
- An approved claim whose evidence becomes unavailable moves to `needs_reassessment`. Never leave it presented as approved, and never delete it.

## Documentation requirements

- A change that alters architecture, the data model, a security boundary, or the AI pipeline updates the corresponding document in the same PR.
- A change that reverses or adds an architectural decision adds or supersedes an ADR. Accepted ADRs are not edited to change their decision.
- Public service functions have docstrings stating preconditions, side effects, and raised errors.

## Definition of Done

A change is complete only when all applicable items are true:

- [ ] Tests exist for new behaviour and for the failure paths
- [ ] The full test suite passes
- [ ] `ruff check` and `ruff format --check` pass
- [ ] `mypy` passes
- [ ] Import-layer check passes
- [ ] Dependency audit and secret scan pass
- [ ] Migrations are reviewed: reversible or explicitly documented as not, safe on existing data, no unintended changes
- [ ] Error handling is addressed: failures are explicit, retried only where safe and within a bound, and never swallowed
- [ ] Logging is considered: useful events logged with correlation IDs, no secrets or document bodies in logs
- [ ] Documentation and ADRs are updated
- [ ] The full `git diff` has been read and contains nothing unrelated
- [ ] For AI pipeline changes: evaluation results are reported

Report what was run and what the result was. If a check could not be run, say so; do not describe it as passing.

## Prohibited shortcuts

- Starting implementation while the gate is NOT READY for that phase
- Treating a Proposed ADR as accepted
- Disabling or loosening lint, type, test, or security checks; adding `# type: ignore`, `# noqa`, or `nosec` without a specific written reason
- Catching broad exceptions to hide failures
- Editing an applied migration, or hand-editing the database to match the code
- Bypassing the fetch guard, worker isolation, rights checks, or citation verification "temporarily"
- Hard-coding secrets, model names, country codes, or URLs in application logic
- Mocking the thing under test
- Generating plausible-looking research data, sources, or citations
- Adding boilerplate, scaffolding, or abstractions "for later"
- Committing, pushing, or changing shared configuration without being asked

## `.claude/` structure

The planned structure and the rule for adding automation are in `.claude/README.md`. No agent, skill, or hook is added until a recurring need has been demonstrated.
