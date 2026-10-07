# Security

## Reporting a vulnerability

**Report security problems privately through GitHub's private vulnerability reporting.** On the repository page, open the **Security** tab and choose **Report a vulnerability**. This creates a draft security advisory visible only to you and the maintainers.

Do not put vulnerability details in a public issue, pull request, or discussion.

If the "Report a vulnerability" button is not available, open a public issue that says only that you wish to report a security problem privately, with no details, and the maintainers will open a private channel. The project publishes no security email address.

The repository currently contains documentation, a development environment, and a Django application skeleton with no research functionality. No application is deployed.

### What to include

- What is affected: file, component, or configuration
- How to reproduce it, or a proof of concept
- What an attacker could achieve
- Any suggested fix

### Coordinated disclosure

1. **Report** privately, as above.
2. **Acknowledgement.** The maintainers confirm receipt in the advisory thread. This is a small research project without a staffed security team, so responses are best-effort and no response time is guaranteed.
3. **Assessment.** The maintainers confirm or decline the report and tell you which, with reasons.
4. **Fix.** A fix is prepared privately in the advisory's own fork, and the reporter is invited to review it.
5. **Publication.** The fix is released and the advisory is published, with credit to the reporter unless they prefer otherwise.
6. **Timing.** The project's target is to release a fix and publish the advisory within 90 days of a report. This is a target, not a guaranteed response time or a service-level commitment. Please do not disclose publicly until a fix is released or 90 days have passed since your report, whichever comes first. If the maintainers need longer, they will ask and explain why.

### Scope

In scope: the code and configuration in this repository, and any deployment operated by the project. Out of scope: third-party websites that CAIPO fetches documents from, and vulnerabilities in dependencies that are not exploitable through CAIPO, which should be reported to their own maintainers.

## Security posture in one paragraph

CAIPO deliberately pulls documents and dataset files from the open internet, parses them, stores them, and feeds their text to a language model. Each of those steps is an attack path. The design therefore assumes that any external file may be hostile, and it relies on structural controls (isolation, least privilege, server-side verification) rather than on detecting bad content.

## Assets

| Asset | Why it matters |
|---|---|
| Integrity of the evidence base | A tampered or fabricated source corrupts every conclusion built on it |
| Integrity of AI answers | A manipulated answer presented with citations is more damaging than an obviously wrong one |
| Credentials and API keys | Database, AI provider, storage |
| Internal network | The fetch worker must not become a proxy into it |
| Availability and cost | Parsing and AI calls are expensive and can be abused |
| User accounts and query logs | Research questions may be sensitive |

## Trust boundaries

1. **Internet → fetch worker.** Everything returned is untrusted bytes. The fetch worker does not interpret them.
2. **Uploaded or fetched bytes → parse worker.** Type detection and parsing run only in the parse worker. This covers documents and dataset files (CSV, XLSX, and any other format).
3. **Isolated worker output → database.** Results from the fetch and parse workers are validated by a trusted worker before being written.
4. **Stored text → model context.** Retrieved text enters the prompt as delimited data, and only if its rights permit.
5. **Model output → user.** Output is treated as untrusted until verified and is always escaped.
6. **Browser → web application.** Standard web boundary.

The zones, and the exact network, database, broker, and storage privileges of each component, are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#5-security-boundaries). Decision records: [ADR-0009](docs/adr/0009-untrusted-content-handling.md) for the principles and [ADR-0011](docs/adr/0011-worker-isolation-mechanism.md) for the isolation mechanism, which still needs a spike (blocker B21).

## Threats and required controls

### SSRF and malicious URLs

- Only authenticated users with the Researcher role or above can submit URLs. Readers and anonymous users can never cause a fetch.
- **Registered hosts only.** A URL is fetched only if its host is an allowed host of a registered Source. Adding or changing a source's allowed hosts requires the Reviewer role and is audited. A redirect to a host that is not allowed for that source is refused.
- Schemes limited to `https` and `http`. No `file`, `ftp`, `gopher`, `data`, or others.
- The hostname is resolved once; every resolved address is checked against a deny list covering loopback, private, link-local, carrier-grade NAT, multicast, reserved ranges, IPv6 equivalents, IPv4-mapped IPv6, and cloud metadata addresses. The connection is made to the validated address, so a second DNS answer cannot redirect it (DNS rebinding). An allowed hostname that resolves to a denied address is refused.
- Redirects are followed manually with the same validation at each hop, with a low hop limit.
- Non-standard ports are rejected unless explicitly allowed for a registered source.
- Hard limits on connect time, total time, and size. **The size limit applies to the decompressed body**, and a response whose compression ratio exceeds a configured bound is aborted. The body is streamed and the transfer is cut when a limit is reached.
- Credentials in URLs are rejected. No cookies, no authentication headers, and no internal headers are sent.
- Response bodies and error details are never reflected to the submitting user beyond a status category, so the fetch worker cannot be used to read internal responses.

### Fetch worker isolation

The fetch worker is the only component with general outbound internet access, and it handles hostile responses. It is therefore isolated in the same spirit as the parse worker.

| Privilege | Fetch worker |
|---|---|
| Network | Outbound to public internet addresses only. Private, loopback, link-local, and metadata ranges are blocked at network level in addition to the application check. No route to PostgreSQL or other internal services. |
| Database | None. It holds no database credentials. |
| Broker | Consumes its own queue only. It cannot publish tasks to other queues. |
| Storage | Writes to the landing area only. It cannot read the artifact store. |
| Secrets | Its broker credential only. No AI provider key. |
| Content handling | Streams, counts, and hashes bytes; writes a manifest of response metadata. **No type detection and no parsing.** |

A trusted worker validates the manifest, recomputes the hash, and records the artifact and acquisition record. Manifest fields that originate from the remote server are stored as untrusted data with length limits.

### Unsafe file parsing and malicious documents

- An allow list of formats, decided by content, not by file extension or declared content type. Initial set: PDF, HTML, plain text, DOCX, and CSV and XLSX for datasets. **Type detection runs in the parse worker**, as the first step, because it interprets untrusted bytes.
- **Dataset files are untrusted content.** CSV, XLSX, and every other dataset format are parsed in the parse worker under the same isolation as documents. The trusted side receives only structured rows and validates them.
- The parse worker has no outbound network access, no database credentials, no AI provider key, a non-root user, a read-only filesystem apart from a scratch directory, read-only access to artifacts, and CPU, memory, and wall-clock limits per file.
- Each parse runs in a child process that is killed on timeout. A parser crash fails that file only.
- **Bounded delivery.** The trusted side records each attempt in PostgreSQL before dispatching it. A parse whose worker was killed or timed out is delivered at most once more; after that the ingestion request is `failed` with reason `worker_killed`. No task is redelivered without limit. Submitting the same file hash again after such a failure is an explicit, audited action.
- Archive-based formats (DOCX, XLSX) are checked for decompressed size and entry count before extraction. Nested archives are rejected.
- XML parsing disables external entities and DTD loading.
- Macros, embedded scripts, embedded files, formulas, and PDF JavaScript are never executed. Spreadsheet cells are read as stored values; formulas are not evaluated.
- Legacy and complex formats that would need an office suite to convert are not accepted initially.
- Parser libraries are pinned, audited, and kept few.
- Page count, row count, and extracted text size are capped.

### Arbitrary file execution

- Artifacts are stored under content-hash names with no extension, outside any web root, without execute permission.
- Original files are served only as downloads with `Content-Disposition: attachment`, a generic content type, `X-Content-Type-Options: nosniff`, and a restrictive Content Security Policy. Access requires authorisation and the right to display the document.
- No code path passes a stored filename or document-derived string to a shell.
- No deserialisation of untrusted data with `pickle`, unsafe YAML loaders, or similar. Celery uses JSON serialisation only.

### Prompt injection

Detection of injection text is unreliable, so it is not the primary defence.

- **No tools.** The safety requirement is that the model has no tools: it cannot fetch URLs, call functions, write to the database, or trigger any action. It also has no secrets in its context. The application calls the model provider over the network through the provider interface; that is designed and permitted. What is excluded is any capability the model's output could invoke. A successful injection can at most distort the text of one answer.
- **Instruction and data separation.** System instructions are fixed and versioned. Retrieved text is inserted in clearly delimited blocks labelled as untrusted source material.
- **Server-side citation verification.** The model can reference only handles issued for this request. Quotes and numbers are checked against stored text. See [docs/AI_ARCHITECTURE.md](docs/AI_ARCHITECTURE.md#6-verification).
- **The verifier is also exposed.** The support-check model reads the same hostile passages and can be told by them to answer "supported". It is therefore not treated as a guarantee. The deterministic checks carry the guarantees; the support check's output is restricted to a fixed set of values; and verifier-targeted attacks are part of the adversarial evaluation.
- **Output is inert.** Model output is rendered as escaped text. No model-authored links, images, or HTML are rendered, which closes the exfiltration path through crafted URLs.
- **Only verified output is displayed.** No partial or streamed model text reaches a user.
- **User input is also untrusted.** The same rules apply to the question.
- **Measured.** An injection test corpus is part of the evaluation suite and attack success rate is tracked.

### Poisoned retrieval content

- Only document versions with review status `approved` are eligible for retrieval. Approval requires the Reviewer role.
- Every source has a recorded type and source tier, shown to the user next to each reference. Tier is a neutral category, not a quality rating; it does not silently change what the model says.
- Raw artifacts are hash-verified on read. A changed artifact is an integrity incident.
- A newer fetch of the same URL with different content creates a new version; it never replaces the approved one.
- The parser records content flags on the extraction (instruction-like text, hidden text). This is a triage aid for Reviewers only.
- A Reviewer can set a version to `suspended` while a concern is investigated. This removes it from retrieval and moves dependent approved claims to `needs_reassessment`. Nothing is deleted.

### Rights restrictions

Each document version has recorded rights, set by a Reviewer. With no rights determination, the version is available only to the submitting Researcher and to Reviewers for the purpose of review, and every other use is denied.

**Rights are enforced independently of authentication.** A signed-in user of any role, including an Administrator, gets no use that the rights do not allow, and a right gives nothing to a user who lacks the permission. Both checks run every time.

| Use | Requires |
|---|---|
| Text sent to an external AI provider (synthesis, support check, hosted embedding or reranking) | Provider transmission |
| Quoted text shown on the public site | Public excerpt display; otherwise the reference shows the locator without the text |
| Full text or original file shown or downloaded on the public site | Public full display |
| Full text, or a quoted passage in an assistant answer, shown in the research workspace | Workspace display, and a role that permits it |
| Text included in exports and data snapshots | Redistribute |

The mechanism is described in [docs/RIGHTS_AND_LICENSING.md](docs/RIGHTS_AND_LICENSING.md). The rights policy itself, which decides what each kind of document is granted, is undecided (blocker B7, remaining part). The MIT License on the software grants nothing in third-party documents or data.

### Access surfaces

Decided in [ADR-0007](docs/adr/0007-authentication.md).

| Surface | Who | Limits |
|---|---|---|
| Public research site | Anonymous visitors | Read-only; approved and public material only; throttled per client address |
| Research workspace | Authenticated accounts by role | Per-account throttling and assistant quotas |
| Administration | Administrators | TOTP required; non-default path; provenance models read-only |

An anonymous visitor can never submit a source or URL, trigger ingestion or a fetch, create or review a claim, call the AI assistant, or see drafts, restricted documents, or text without a public display right. Every view declares the access it requires, and a view with no declaration is refused.

Two operational endpoints, `/health/live/` and `/health/ready/`, are reachable without authentication so that a process supervisor can probe them. They return a fixed status value and no data. They are not part of the public research site. They are not throttled yet, and each readiness request opens a database connection; whether they are reachable from outside the deployment at all is settled with the deployment decision (ADR-0008, Proposed).

### Authorization as implemented

What exists now, and what does not. Nothing here means authentication is complete. The decisions behind it are recorded in [ADR-0007](docs/adr/0007-authentication.md), [ADR-0012](docs/adr/0012-authorization-and-role-event-integrity.md), and [ADR-0014](docs/adr/0014-totp-mfa-and-authentication-assurance.md).

**Implemented**

- **Roles are records, not flags.** A role is held only because an append-only RoleEvent grants it and no later event revokes it. Each event names the acting user, the time, and a reason. There is no role field, no staff flag, and no superuser flag on the user, so there is nothing to overwrite silently.
- **One place decides.** `caipo.accounts.authorization` holds the whole policy: four roles, ten permissions, two assurance levels, and which role holds which permission at which assurance. `caipo.accounts.selectors.can` and `require_permission` apply it to an authentication context: an account and the assurance it is acting at. Views and services both call these; neither contains role logic or asks whether an account has a second factor.
- **Views declare a permission, never a role.** `@requires(Permission.RESEARCH_REVIEW)` states the capability a view needs; only the policy knows which roles have it.
- **Deny by default, at every step.** No role means no permission. An unknown role or permission means no. A view with no access declaration, or a malformed one, is refused. An anonymous visitor holds no permission and reaches only views declared public.
- **Nothing from the browser is trusted.** The account and its assurance come from the server-side session, and its roles from the database, on every request. A role or a verified second factor named in a parameter, header, or cookie has no effect.
- **Services check for themselves.** A service calls `require_permission` whatever the view has already checked, and it works without an HTTP request. It is given the acting context, never a bare account: an account passed without a context holds no permission, so a caller that bypasses HTTP cannot obtain a privileged operation without the assurance it requires.
- **Second factor.** Reviewer and Administrator roles confer their permissions only to a sign-in that verified a TOTP code from the account's active, trusted second factor (ADR-0007 rule 4, ADR-0014). A second factor is trusted when an Administrator approved its enrolment, or when the first-Administrator bootstrap established it. On a password alone these roles allow one thing, managing the account's own second factor, so that the account can ask for an enrolment. The password cannot complete one. See "Multi-factor authentication as implemented" below.
- **Nothing stands in for the second factor in tests.** The earlier test-only fixture that replaced the enrolment lookup is gone, with the lookup. Tests give an account a real device, encrypted with the real cipher, and either compute real codes or use the context that the verification service returns for that device. The authorization decision is never replaced.
- **Administrator is not a superuser.** It holds the six administrative permissions, to manage roles, to create accounts, to disable them, to enable them, to approve the second-factor enrolment of another account, and to authorise or reject another account's request to recover a lost second factor, the permission every role has to manage its own second factor, and no research permission. There is no role hierarchy: a person who needs administrative and research capabilities is granted both roles explicitly.
- **Nobody changes their own roles.** Granting or revoking a role requires an authorised Administrator and a target who is a different user. The service refuses otherwise, and a database constraint refuses a role event whose actor is its own subject.
- **There is always an Administrator.** The services refuse to revoke the Administrator role from, or to disable, the only active account that holds it. An account that awaits verification is not active and does not count. An Administrator may disable their own account only while another active Administrator remains; the only Administrator attempting it is refused by the same rule, with nothing changed.
- **Role history cannot be rewritten.** A PostgreSQL trigger on the role event table refuses every UPDATE and DELETE, for any database role and however the statement was sent (migration `accounts/0002_role_events`). The application also refuses, earlier and with a clearer error. Two things the trigger does not cover are left to database privileges, which are set with deployment (ADR-0008, Proposed): TRUNCATE, and dropping or disabling the trigger, which requires owning the table. The production application role must be able to do neither. In development the application connects as the database owner, so there the trigger guards against mistakes, not against the owner.
- **Account changes happen one at a time.** Each role change, account creation, disabling, or enabling is one transaction holding a lock that admits one such change at a time, and the actor's permission is decided inside that lock. Two simultaneous changes cannot both be decided on the same earlier state, so they cannot leave the system without an Administrator or record a role twice.
- **Disabling is immediate.** A disabled account keeps its role record and loses every permission on its next request. So does an account that awaits verification: it holds nothing until it is activated. See "Account lifecycle as implemented" below.
- **Refusals and role changes are logged** by account identifier, never by email address.

**Not implemented**

- Recovery of an account after a suspected compromise, and of an account that lost its password, its second factor, and its email address together. Changing an account's email address. Password reset by email is implemented ([ADR-0016](docs/adr/0016-password-reset.md)); it changes a password and recovers nothing else. Recovery from a lost second factor is implemented except for its notifications and the page that shows its history (see the entry below).
- **Sending email in production.** No delivery service is configured, so there an account can be created and its verification message cannot be sent (see "Account lifecycle as implemented"), and a password reset can be asked for and its message cannot be sent.
- The rest of recovery from a lost second factor ([ADR-0017](docs/adr/0017-account-recovery.md)). Asking for recovery, an Administrator's authorisation or rejection of the request, the record that a recovery is complete, and the break-glass command are built (see "Asking for recovery of a lost second factor", "Authorising and rejecting a recovery request", and "The break-glass command"). Not built: notifications, and the page that shows the history of recoveries. The operational audit trail of the server, which is what records who ran the break-glass command, and the instructions for running it in a deployment wait for [ADR-0008](docs/adr/0008-deployment-strategy.md), which is Proposed. There are no recovery codes.
- Pages for role administration and for disabling and enabling accounts. Those services work for an Administrator with a verified second factor; no page calls them yet.
- Assistant quotas.
- The general audit record (AuditEvent) for administrative actions. Role changes, sign-ins, and the lifecycle of accounts are each recorded in their own table.
- A least-privilege database role for the application (see "Role history cannot be rewritten" above).
- The Django admin. It is a later increment of its own (ADR-0007 rule 8).

### Authentication as implemented

Sign-in with an email address and a password, on Django's own authentication and session machinery, followed by a TOTP code for accounts that have a second factor. The decisions are in [ADR-0013](docs/adr/0013-authentication-core-and-first-administrator-bootstrap.md) and [ADR-0014](docs/adr/0014-totp-mfa-and-authentication-assurance.md). Account creation and email verification ([ADR-0015](docs/adr/0015-account-lifecycle-and-email-verification.md)), password reset ([ADR-0016](docs/adr/0016-password-reset.md)), and the first three parts of recovery from a lost second factor ([ADR-0017](docs/adr/0017-account-recovery.md)) are implemented and described in the sections below. Nothing here is a statement about production deployment.

**Signing in and out**

- **One answer for every refusal.** A wrong password, an unknown email address, a disabled account, and an account that awaits verification get the same page, the same status, and the same log line. Nothing tells the three apart, including throttling, which behaves the same whether or not an account exists.
- **Credentials only by POST, with a CSRF token.** Signing out is POST-only with a CSRF token too, so a link or an image cannot sign anyone out. It takes no destination.
- **The session key is replaced on sign-in**, so a key known beforehand is worth nothing afterwards, and the session is deleted on the server on sign-out. For an account with a second factor it is replaced twice: when the password is accepted and again when the code is. A deactivated account, one whose password changes, or one whose lost second factor an Administrator or the break-glass command has revoked loses its sessions on the next request.
- **After sign-in, only a path on this site is followed.** Any other destination is ignored.
- **Passwords are never logged, stored in an event, or sent back in a page.** Log lines name an account by identifier only, and a refusal names nobody.

**Sessions**

| Setting | Value | In development |
|---|---|---|
| Storage | Server-side, in PostgreSQL. The cookie carries an identifier only. | Same |
| Session and CSRF cookie `Secure` | On | Off, because the development server speaks plain HTTP. This is the only relaxation. |
| Session cookie `HttpOnly` | On | Same |
| `SameSite` | `Lax` for both cookies | Same |
| Lifetime | Until the browser closes, and at most 12 hours on the server | Same |

**Sign-in records.** Each sign-in, refused sign-in, sign-out, and change to a second factor is an AuthenticationEvent: type, time, the account if the email address belongs to one, and the request's correlation ID. The table is append-only and protected by a database trigger in the same way as role events. It holds no password, password hash, second-factor code or secret, challenge token, session identifier, header, or address. What was typed as the email address, and where the request came from, are stored only as keyed hashes, because people type passwords into the email field. A refused sign-in for an address that has no account names nobody.

**Brute-force protection the application provides**

- A refused sign-in counts against the email address it named and against the network address it came from, each identified by a keyed hash. The limits are exactly 5 refusals for one keyed email address in 15 minutes, and 20 refusals from one keyed source in 15 minutes. Once either is reached, further attempts are refused with status 429 without the password being looked at.
- Nothing is locked permanently. The limit lifts by itself as refusals age out of the window, and a successful sign-in clears the count for that email address. It does not clear the count for the source, so one valid account does not buy a source fresh attempts at other accounts.
- Attempts for the same email address, or from the same source, are handled one at a time, so attempts sent together cannot each be counted as the first.
- A throttled attempt is logged and stores nothing. One source can therefore add at most 20 rows per window, and one email address at most 5, however many requests it sends.
- The limits are in repository settings and are not read from the environment.
- Redis is not used. The counts come from the sign-in records in PostgreSQL.

**What that protection does not do**

- This is application-level brute-force mitigation. It is not denial-of-service protection: each attempt still costs a request and database queries.
- Anyone can keep a known email address throttled by failing five times every fifteen minutes. That is the price of limiting guesses per account.
- An attacker using many source addresses and many email addresses is limited only per address. Limiting that needs controls in front of the application.
- The source is the address the application process sees. Behind a reverse proxy that is the proxy's address, so every visitor would share one source and twenty refusals would throttle sign-in for everyone. Extracting the real client address from a trusted proxy header is a deployment concern, deferred to ADR-0008 (Proposed). No forwarded header is read until then, because a client can write one.
- Request-rate limiting, connection limits, and filtering belong to the reverse proxy and are not built.
- The sign-in page is served without a Content Security Policy header. The page contains no script or style. The production policy is deferred to the deployment increment, with ADR-0008.

**Retention and secret rotation**

- Sign-in records are append-only, and the table grows with use. How long they are kept is a future data-governance decision; no period has been set. Application code must not delete them, and the database refuses it. A future retention policy must preserve what security and audit need and meet the legal obligations that apply.
- The keyed hashes are derived from `SECRET_KEY`. Rotating that key changes every hash, so refusals recorded before the rotation no longer count towards a limit, and earlier records can no longer be matched to later ones by email address or source. Throttling starts from zero at that moment. This is an accepted trade-off of storing no readable address.

**The first Administrator**

Every normal role change needs an existing Administrator who is a different user, and its record names that Administrator. The first Administrator is the one exception (ADR-0012, as amended): it is created by a command run by an operator at the server, and its role event is the only one without an acting user:

```sh
python manage.py create_first_administrator
```

- It works once. If any Administrator role event exists it refuses. The database allows a role event without an acting user only if it grants the Administrator role, and allows only one such event, ever.
- It must be run by a person at a terminal. It asks for the email address, the password twice without showing it, and a phrase to be typed out as confirmation.
- **It sets up the account's second factor before the account exists.** It writes a new TOTP key to the terminal, once, and asks for a code from the authenticator application that was given it. Only when a right code is typed are the account, its role event, and its second factor created, together, with the second factor active and trusted. After three codes that are not accepted the command ends having created nothing, and can be run again. It refuses to run unless its output is a terminal as well as its input, so the key is not written to a pipe or a file.
- It has no option for an email address or password and no non-interactive mode, and it reads no credential from the environment.
- The password must pass the password validators. The account, its role event, and its second factor are created together or not at all.
- The role event records that it was made by this command and the operating-system account that ran it, taken from the process and not from an environment variable.
- No web request, header, cookie, setting, environment variable, or database value creates an Administrator, nothing else in the application calls the bootstrap, and the role services refuse a change that names no actor. There is no second way to run this once it has been used.

This is the one second factor that is created trusted, with no enrolment for anybody to approve, because no Administrator exists who could approve one (ADR-0014, as amended). One other thing makes a device trusted without an Administrator: the approval that the break-glass command gives to the enrolment that follows the recovery of an Administrator, which creates and activates nothing (ADR-0017 point 69; see "The break-glass command"). The first Administrator never exists without a verified second factor: its password alone signs nobody in, and the Administrator role grants nothing until a sign-in has been verified with a code from the authenticator set up at the terminal. No temporary permission is granted, and there is no bypass, on the web or anywhere else.

### Account lifecycle as implemented

How an account other than the first Administrator's comes to exist, how its owner verifies the email address and chooses a password, and how it is disabled and enabled. The decisions are in [ADR-0015](docs/adr/0015-account-lifecycle-and-email-verification.md). Password reset by email is implemented as decided in [ADR-0016](docs/adr/0016-password-reset.md), which states its controls and its residual risks; disabling an account also removes its password-reset token. Recovery from a lost second factor is implemented, except for its notifications and the page that shows its history, as decided in [ADR-0017](docs/adr/0017-account-recovery.md): see "Multi-factor authentication as implemented". Recovery after a suspected compromise is not implemented; such an account is disabled.

**States**

| State | Meaning |
|---|---|
| `pending_verification` | The account exists. Nobody has shown that its email address is theirs. It cannot be signed in to and holds no permission. |
| `active` | It can be signed in to, according to its roles and the second-factor policy. |
| `disabled` | An Administrator disabled it. It cannot be signed in to and holds no permission. Its roles and history are kept. |

- The state is stored once, in the account's `status`. There is no separate active flag that could disagree with it.
- `email_verified_at` records when the address was verified, and `activated_at` when the account first became active. Database constraints refuse an account that awaits verification and claims either, and an active account that never became active.
- The first Administrator is created active at the server, and its address is not marked verified, because nobody verified it.

**Creating an account**

- **Only an Administrator signed in with a trusted second factor creates an account.** It needs the permission `accounts.create`, which only the Administrator role holds and which exists only at `MFA_VERIFIED`. The page and the service both check it, and nothing from the browser names the actor.
- **There is no registration.** No page, setting, or request creates an account without an acting Administrator.
- **The Administrator gives an email address and one role, and never a password.** The role must be one of the four. It is granted by the role service under its own rules and recorded as a RoleEvent naming the Administrator. Extra fields in a manipulated form are ignored: the account gets exactly one role, awaits verification, and has no password anybody knows.
- **A privileged role given at creation confers nothing yet.** A new Reviewer or Administrator must be activated, then ask for a second factor, have it approved by an Administrator, verify it, and sign in with it (ADR-0014). Until then the role gives only the permission to manage its own second factor.
- The account, its role event, its token, and the record of its creation are written in one transaction.

**The password**

- The owner of the account chooses it. No temporary password exists, none is emailed, and the Administrator never sees one.
- A new account holds a hash of 256 random bits that were discarded, not an "unusable" marker, so that a sign-in attempt for it takes as long as for any other account and its existence cannot be told from the time taken.
- The password is set only by activation and must pass the password validators.

**The token**

- 256 random bits, generated on the server. **Only its keyed hash (HMAC-SHA256) is stored.** The token is in the message and nowhere else: not in the database, a log, an event, a session, or a response.
- It is bound to one account, works once, and lapses after 48 hours. Sending the message again replaces it, and disabling the account removes it.
- It is refused for any account that does not await verification.
- **It never reaches the server in a URL.** The link carries it after a `#`, which a browser does not send. A small script from the application's own static files moves it into the form and out of the address bar, and it is sent in the body of a POST. A token in a query string is ignored. Without the script the person pastes it.
- Activation is by POST with a CSRF token, takes no account from the request, signs nobody in, and always goes to the sign-in page.
- **One answer for every refused token**: unknown, used, replaced, lapsed, or belonging to a disabled or active account. Nothing that was submitted is put back into the page.
- **Throttled per source**: 10 refused attempts in 15 minutes, then status 429 with the token unexamined and nothing stored. Counted in PostgreSQL, one attempt at a time for a source.

**Email**

- All mail goes through one function, `caipo.core.mail.deliver`. It knows nothing of accounts and logs nothing. Django's `EMAIL_BACKEND` setting names what carries the message; no provider is chosen and no library is added.
- **Nothing is sent in any environment today.** The default backend refuses every message; production inherits it until the deployment decision (ADR-0008) names a service. Development writes messages to `data/outbox/`, which git ignores. Tests keep them in memory.
- The message says what it is for, carries one link, says that the link works once and for how long, and says to ignore it if unexpected. It is the same for every recipient apart from the link, and holds no name, address, role, password, or secret.
- **Links are built from a configured address, never from a request.** Production reads `CAIPO_PUBLIC_URL`, refuses to start without it, and accepts only `https://host[:port]`. A Host or forwarded header cannot change where a link points.

**Disabling and enabling**

- Service operations for an Administrator with a verified second factor, each behind its own permission. They have no page yet.
- Disabling takes effect on the account's next request: its password signs nobody in and its sessions stop being recognised.
- The last active Administrator cannot be disabled.
- Enabling returns an account to the state it was disabled in and never further: an account that was never activated returns to awaiting verification, with no token, and needs a new message. Nobody enables their own account.

**Records**

- `AccountEvent` is append-only and protected by a database trigger like the other event tables. It records `account_created`, `verification_sent`, `verification_succeeded`, `verification_failed`, `account_disabled`, and `account_enabled`, with the account, the acting Administrator where there is one, the time, and the request's correlation ID.
- It holds no token, token hash, password, or email address. Logs name accounts by identifier.

**Residual risks**

- **Whoever opens the link first sets the password.** The token is a bearer credential for 48 hours. Someone who can read the mailbox can use it, and so could a mail system that opens links and runs scripts. Sending the message again revokes it.
- Behind a reverse proxy all visitors share one source until ADR-0008 names the header to trust, so ten refused activations by anyone would throttle everyone for fifteen minutes.
- An account that is never activated stays in the list until an Administrator disables it.
- The script on the activation page is not exercised by the automated tests, which have no browser. The tests check what it must and must not contain, and that the page works by pasting.

### Multi-factor authentication as implemented

TOTP as a second factor, and an explicit record of how strongly each sign-in was proved. The decisions are in [ADR-0014](docs/adr/0014-totp-mfa-and-authentication-assurance.md). **This is not a statement that multi-factor authentication is complete for a production deployment**: how the encryption key is stored, supplied, backed up, and rotated belongs to ADR-0008, which is Proposed.

**Assurance**

- **Two levels.** `PASSWORD_AUTHENTICATED` and `MFA_VERIFIED`. Every authorization decision is made about an authentication context: the account and the level it is acting at.
- **A verified second factor is never inferred.** Not from a role, not from a database flag, and not from anything in the request. It counts only if the server-side session notes the device a code was verified against **and** that device is, in the database at that moment, the same account's active second factor **and** that second factor is trusted. No one of these alone grants anything.
- **Trust comes from an Administrator, not from the password.** A second factor that an account enrolled on its password alone is asked for at sign-in and proves nothing more than the password. For Reader and Researcher that is all it needs to do. For Reviewer and Administrator it is not enough: their second factor counts only if an Administrator approved its enrolment, or the bootstrap established it.
- **Reviewer and Administrator permissions require `MFA_VERIFIED`.** Reader and Researcher permissions hold at either level.
- **The same rule for a direct caller.** Services take the context and decide with it, so calling a service without HTTP, or with a bare account, or with a context that claims a device it cannot show, is refused.
- **No switch.** No setting, environment variable, account attribute, header, cookie, parameter, or session value turns the requirement off. The settings that exist are an issuer name, a drift window, three lifetimes, a throttle, and the encryption key. None says whether a second factor, or its approval, is required. Tests check each of these inputs.

**Enrolment**

- An account must be signed in and must give its password again in the request that starts an enrolment. A wrong password there counts towards the sign-in limits, for the account and for the source.
- The secret is generated on the server. Nothing the browser sends can supply a secret, a state, or an account.
- Starting an enrolment enables nothing. The device is pending, grants nothing, and is not asked for at sign-in. Only a right code from the new secret makes it active.
- **A Reader or Researcher account enrols by itself.** Its enrolment awaits its first code at once and is void after 10 minutes.
- **A Reviewer or Administrator account cannot.** Its enrolment is a request that awaits approval, and until an Administrator approves it no code is accepted for it, whoever sends the code. See "Approval" below.
- The secret is shown once, in the response that started the enrolment, as a key to type and as an `otpauth` address that carries the issuer, the account's email address, and the secret, and nothing else. It is not stored in clear, not kept in the session, and cannot be shown again. There is no QR code.
- The session that proved the code gets a new session key and notes the device. It is `MFA_VERIFIED` only if that device is trusted. The account's other sessions are not raised.

**Approval**

The password of a Reviewer or Administrator account must not be enough to give that account a second factor that the system trusts. Otherwise whoever learned the password of an account that had not yet enrolled could enrol their own device and hold every privilege of the account.

- **A request has a number.** It is shown, with the key, to whoever made the request, and it identifies that one key. The Administrator sees the number, the account's email address, and when the request was made, and never the key.
- **The Administrator asks the person for the number by a means other than this system**, and approves only that number. A request made by someone else who knows the password has another number. The page says so. The system records who approved; it cannot check that they asked.
- **Who can approve.** Only an account that holds the approval permission, which is the Administrator role's and exists only for a sign-in verified against a trusted second factor. A Reviewer, an Administrator signed in with a password alone, and an Administrator whose own second factor is not trusted are all refused, by the page and again by the service.
- **Nobody approves their own request.** The service refuses it and a database constraint refuses a device that names its own account as approver.
- **How.** By POST, with a CSRF token and a ticked confirmation; without the tick nothing is approved. The request is named by its number in the path, and nothing else from the browser is used: the approver is the account of the session. The change and its record are one transaction.
- **What it does.** It lets the first code be accepted. It raises no session and confers nothing: the account has no privilege until a code has activated the device and a sign-in has been verified against it.
- **Asking again starts again.** A new request replaces the earlier one and has no approval, also when the earlier one had been approved. Whoever knows the password cannot take over an approval given to the account's owner.
- **Rejection** deletes the pending device and its key.
- **Lifetimes.** A request waits 72 hours for a decision, and an approved one 72 hours from the approval for its first code.
- **A device enrolled before the role was granted is not trusted.** An account that enrolled as a Reader and was then made a Reviewer or Administrator gets nothing from the new role until it has replaced that device and the new one has been approved.
- **Recorded.** `mfa_enrollment_started` when the request is made, `mfa_enrollment_approved` or `mfa_enrollment_rejected` naming the Administrator, and `mfa_enrollment_succeeded` when the code is accepted. No event holds the key, a code, or the address that carries the key.

**Secret storage**

- TOTP secrets are encrypted with AES-256-GCM, from the `cryptography` package. They are not hashed, because verification needs the secret.
- The key comes from the environment variable `TOTP_ENCRYPTION_KEY` and from nowhere else. It is separate from `DJANGO_SECRET_KEY`. Development and production refuse to start without a usable key; there is no fallback.
- Each ciphertext is bound to its account, so it does not decrypt if copied into another account's row, and it records which key encrypted it by a fingerprint that reveals nothing of the key.
- A secret that cannot be decrypted refuses the code and is logged as an error. Nothing is accepted that could not be checked.
- The secret, the provisioning address, and codes never appear in logs, authentication events, URLs of this site, the session, or error messages.

**Signing in with a second factor**

- For an account with an active second factor, the right password signs nobody in. The session, under a new key, holds only a pending challenge, and the visitor is still anonymous to every other view.
- The challenge is a row on the server that names the one account it can complete a sign-in for. The request cannot name an account, so a challenge cannot be moved to another one. It is removed when it is used, so it cannot be replayed; replaced by a new password step; removed on sign-out; and void after 5 minutes.
- The code is accepted by POST only, with a CSRF token.
- A code is accepted for the current 30-second step and one step either side, and only once: a code that was used, or that is older than the last one used, is refused.
- Every refused code gets the same page: a wrong code, a used one, a lapsed challenge, a removed device. Whether an account has a second factor is visible only after its password was accepted.

**Throttling of codes**

- 5 refused codes for one account within 15 minutes. After that, codes are refused unexamined with status 429 until earlier refusals leave the window.
- The count covers sign-in, enrolment, replacing, and disabling together, and nothing resets it early: not a new challenge, a new browser, another source address, or an accepted code.
- Counted in PostgreSQL from the authentication events, one code at a time for an account. A throttled attempt stores nothing. Redis is not used.
- An attacker who holds the password and guesses without pause has about one chance in 700 per day. Whoever holds the password can also keep the account's second factor throttled.

**Replacing, disabling, and recovery**

- An account can remove only its own second factor, and only with its password and a current, unused code in the same request. There is no parameter, setting, or flag that disables a second factor.
- **An active second factor is replaced only on both proofs, and the new one is approved again.** Replacing asks for the password and a current, unused code from the device being given up; starting an enrolment is refused while a second factor is active, so a password alone replaces nothing. The new device inherits no trust: for a Reviewer or Administrator it is a request that awaits approval like any other. Both protections apply, not either: the code shows that the person held the old device, and the approval is what makes the new one trusted. The old device stops working when the new key is issued, the session loses what the old device proved, and the account has no privilege until the new device is approved and verified. This is recorded as `mfa_device_replaced`.
- After disabling, enrolling again needs approval where enrolling did.
- **There are no recovery codes, and an Administrator cannot issue another account's second factor.** A Reviewer or Administrator who loses the device asks for recovery, and an Administrator revokes the lost device by authorising that request and in no other way ([ADR-0017](docs/adr/0017-account-recovery.md); see the two sections below). The account then enrols again, and a different Administrator approves. A Reader or Researcher who enrolled and lost the device is outside that decision: the remedy is still a deliberate operation on the database by its owner, deleting that account's device row, after which the account signs in with its password and enrols again.
- **The only Administrator cannot renew its own second factor, and neither can one of two.** If it replaces, disables, or loses its device, the new enrolment awaits an approval that nobody can give, and the bootstrap cannot be run again. Recovering an Administrator inside the application takes two other Administrators who are able to act. Where they do not exist, an Administrator who lost the device is recovered by the break-glass command (see "The break-glass command"). An Administrator who replaced or disabled the device by choice is not: that account has no active device, so it has no recovery to ask for, and the command approves only an enrolment that follows a recovery. For it the remedy is still a deliberate operation on the database by its owner, outside the application. A second Administrator should exist before either changes their second factor.

**Asking for recovery of a lost second factor**

The first step of [ADR-0017](docs/adr/0017-account-recovery.md). A request authorises nothing by itself: an Administrator decides on it, as the next section describes.

- **Who can ask.** Only the owner of the account, from a sign-in whose password was accepted and whose code is awaited. The offer is on the page that takes the code and on no page that a visitor who is not signed in can otherwise reach. It is the same page for every account.
- **What the request takes.** A POST with a CSRF token, and nothing else. The account is the one the pending challenge was issued to, and the challenge is held on the server: no form field, parameter, header, or cookie can name an account or a challenge.
- **Who is eligible.** An active account with an active second factor, trusted or not, that holds a role requiring one: Reviewer or Administrator. A Reader or Researcher account is refused.
- **What an accepted request does.** In one transaction it removes the pending challenge, removes any earlier request of the account, creates a new one with a new number, and records `mfa_recovery_requested`. The number is shown once, with the 30 minutes after which the request lapses.
- **What it does not do.** Nobody is signed in, and the session gains nothing. The second factor stays active and still signs the account in. The account's other sessions, password, status, and roles, and the counts that throttle sign-in and codes, are untouched.
- **Limits**, counted in PostgreSQL from the authentication events under advisory locks, as sign-in attempts are:
  - 20 requests from one source in 15 minutes, and 10 refused submissions from one source in 15 minutes. Both are applied before the challenge or any account is looked up.
  - 5 requests for one account in 1 hour, applied after the challenge has identified the account.
  - A submission stopped by any of the three gets status 429 and the same page, records nothing, uses up no challenge, replaces no request, and leaves the session as it was. Status 429 for the account limit is an implementation choice that follows the source limits (ADR-0017 point 74; ADR-0014 point 29).
- **Refusals.** An unknown, lapsed, or already used challenge and an account that is not eligible get one page and one message, and the session is left as it was. Each is recorded as `mfa_recovery_failed`, naming the account only if the challenge is still that account's current one: a lapsed challenge and an ineligible account name it, an unknown or used challenge names nobody.
- **What a response reveals.** Nothing to a visitor who has not passed an account's password. To one who has, whether that account is eligible.
- **Without a pending sign-in** there is nothing to submit: the visitor is sent to the sign-in page and nothing is recorded.
- No event and no log line holds the challenge, its hash, a session key, or an email or network address other than as a keyed hash.

**Residual risks of the request step**

- Whoever knows the password of an eligible account can make requests for it. That replaces the owner's request, and five in an hour stop the owner from asking until the hour has passed. It gains nothing unless two Administrators act on it.
- Behind a reverse proxy every visitor shares one source until the deployment decision names the header to trust (ADR-0008), so the two limits by source are then shared by everyone.
- Asking ends the sign-in it was made from. A person who finds the device afterwards gives the password again.
- A request that has lapsed stays in the table until it is replaced.

**Authorising and rejecting a recovery request**

The second step of [ADR-0017](docs/adr/0017-account-recovery.md): an Administrator decides on the request whose number the owner gives them. The design below is the one approved for this implementation.

- **Who decides.** Only an account that holds the permission `accounts.mfa.authorize_recovery`, which is the Administrator role's and exists only for a sign-in verified against a trusted second factor. A Reviewer, an Administrator signed in with a password alone, an Administrator whose own second factor is not trusted, and a disabled Administrator are refused, by the page and again by the service.
- **Nobody decides on their own request.** An Administrator who still holds a verified session and asked for recovery from another sign-in is refused, for an authorisation and for a rejection. The database refuses an event whose actor is the account it names.
- **How.** By POST, with a CSRF token. The request is named by its number in the path, and nothing else from the browser is used: the actor is the account of the session. An authorisation also needs a ticked confirmation; without the tick nothing is authorised. There is no field for how the person was identified, and nothing about that is stored.
- **The permission is checked twice.** First before anything is locked or looked up, so that a caller without it takes no lock and learns nothing about which requests exist. Then again after the locks below are held. The second check is the one that counts.
- **One transaction, and one order of locks for every decision**, authorisation or rejection:
  1. the lock on the role event table that every change to a role or to a status holds. From here the roles and the status of the actor, of the account, and of every Administrator cannot change;
  2. the lock on the account's email address that a sign-in holds, so that no sign-in for the account and no submission of its password-reset token runs alongside;
  3. the second-factor locks of the actor and of the account, always in ascending order of account identifier, so that two decisions that need the same two locks cannot each hold one and wait for the other. The actor's lock keeps the device the actor's session names from being disabled or replaced. The account's lock is the one held by whoever examines a code for it;
  4. after the permission has been decided again (next point), the account's row, and then the request's row, which is read again under the locks.
- **`MFA_VERIFIED` is decided again under the first three locks.** The actor's roles and status are held still by the first lock and the actor's device by the third, so the actor is an Administrator verified against a trusted second factor when the transaction commits, and not only when it began. An actor who gives up the device, loses the role, or is disabled while an authorisation is under way either waits until it has committed or makes it fail; the two never interleave.
- **When an authorisation is not made** (ADR-0017 point 38), all decided inside the transaction: the request is unknown, replaced, already decided, or older than 30 minutes; its `mfa_recovery_requested` event was recorded before the account's latest `password_reset_succeeded` event; 24 hours have not passed since the time of that reset; the account is no longer active, has no active second factor, or holds no role that requires one; or no Administrator who is able to act exists other than the actor and the account. Able to act means active, holding the role on record, and having an active, trusted second factor.
- **One answer for all of them.** The service returns a single outcome, unavailable, and the page answers with status 409 and one sentence, the same in every observable respect whichever condition failed. The page shown then carries no list of requests. The reason is one of six fixed values, written to the log with the actor's identifier and nothing else: no free text, no account, no request number, no address. It is not in the service's result, so no page can show it. Nothing is recorded: a decision that is not made is not a refused submission, writes no `mfa_recovery_failed`, and counts towards no limit.
- **What an authorisation does**, in that one transaction: it deletes the account's device and its secret; raises the account's `session_epoch` by one, in the database and not from a value read earlier; removes every pending second-factor challenge of the account; removes its password-reset token; removes its recovery request; and records `mfa_recovery_authorized`, naming the Administrator. If any step fails, none of it happened.
- **Sessions.** A session is recognised only if it holds the value computed from the account's password hash and session epoch. Raising the epoch therefore ends every session of the account on its next request, and only that account's. The password is not changed, and a sign-in made afterwards is recognised under the new epoch.
- **What an authorisation does not do.** It signs nobody in, returns no authentication context, creates no device, and issues no secret. It does not change the password, status, roles, email address, or the counts that throttle sign-in and codes. Afterwards the account signs in on its password at `PASSWORD_AUTHENTICATED`, where a Reviewer or Administrator role allows asking for an enrolment and nothing else.
- **A rejection** removes the request and records `mfa_recovery_rejected`, naming the Administrator. The device, the sessions, the password, the reset token, and any pending challenge are untouched, and the account may ask again. It is refused only for a request that is unknown or has lapsed, with the same single answer.
- **The Administrator who authorised does not approve the device that follows** (ADR-0017 point 37, security property 6). The rule is in the one service through which every enrolment is approved, not in a page: the approval is refused, with status 403, to the Administrator who authorised the account's open recovery. Another Administrator approves as before. A rejection of the enrolment is not refused, because it makes no device trusted.
- **What an open recovery is.** One function, `caipo.accounts.selectors.open_recovery_of`, says whether an account has an open recovery. A recovery is opened by the most recent of two kinds of event of the account: an `mfa_recovery_authorized` event, which names the Administrator who authorised, or an `mfa_recovery_break_glass` event whose action is `revoke_device`, which names nobody. It is closed by an `mfa_recovery_completed` event recorded after that one, and by nothing else: nothing is inferred from the enrolment events in between, and a break-glass event whose action is `approve_enrollment` opens and closes nothing. There is no other record of recovery state. Two questions are asked of that one answer, and they are kept apart. `has_open_recovery` says whether a recovery is open, whichever way it was opened, and decides that a first code completes it. `open_recovery_authorizer_id` says who authorised it, and decides who does not approve the enrolment that follows. A recovery that the break-glass command opened is open and has no authoriser, so it bars nobody from approving.
- **When a recovery is complete** (ADR-0017 point 49). The first code is the one given at the confirmation of the enrolment, not a later sign-in. When the service that confirms an enrolment accepts the first code of a device that an Administrator or the break-glass command approved, and the account has an open recovery, whichever way it was opened, it records `mfa_recovery_completed` after `mfa_enrollment_succeeded`, in the same transaction and under the account's second-factor lock, which every authorisation and approval for the account also holds. The event names the account and no actor. Whatever opens a recovery deletes the account's device, so an approved device that exists while a recovery is open was enrolled after it. One recovery is completed once: a confirmation sent again finds the device active and records nothing. A new request made before the first code discards the approval, a device enrolled without approval completes nothing, and an enrolment of an account with no open recovery never records the event. If the event cannot be written, the device is not activated. Completing changes nothing else and signs nobody in beyond what confirming any enrolment does: the session that gave the code is noted as verified against the new device, as ADR-0014 decides.
- **Which came first, a request or a reset, is read from the events and not from clocks.** A request and a reset of one account hold the same locks, so one is recorded wholly before the other, and the identifiers of their two events, which the database issues in sequence, say which. Their times are not compared: the clocks of two hosts can disagree or tie. A new request records its event in the transaction that replaces the earlier one, so the account's latest `mfa_recovery_requested` event is the event of its current request. Only the 24 hours are a matter of time, and they are counted from the time recorded on the reset event.
- **With a password reset.** A reset and a recovery of the same account hold the same two locks, so one runs wholly before the other. If the reset is first, the authorisation finds it and is not made. If the authorisation is first, the reset finds its token removed.

**Residual risks of the authorisation step**

- It is as strong as the Administrator's check. An authorisation given without identifying the person and asking for the number trusts whoever made the request. The system records who authorised; it cannot check that they asked.
- Two Administrators are only as independent as they are different people (ADR-0017, "Consequences").
- The Administrator who would approve the device that follows is checked to exist when the request is authorised, and is not held: that Administrator's own second factor can be given up afterwards. The account then waits for an Administrator who is able to act.
- The list of requests shows each request's number, account, and time, to every Administrator who may decide. From it an Administrator can tell that a request no longer exists or is older than 30 minutes. Nothing shows the other reasons.
- The Administrator who authorised still sees the enrolment request that follows in the list of enrolment requests, and is refused only on approving it.
- Between the authorisation and the new device, the password alone signs the account in. An account that also holds Reader or Researcher holds that role's permissions on its password during that time.
- Every decision takes the lock on the role event table, so decisions, role changes, and changes of status wait for one another. That is one short transaction each.
- A recovery after which no approved device ever accepts a first code is never recorded as complete. It stays open, and the Administrator who authorised it stays refused the approval of that account's enrolments, until an approved device of the account does accept one or a later recovery of the account is opened, by an authorisation or by the break-glass command. A recovery that a later one superseded has no `mfa_recovery_completed` event.
- A recovery whose approved device accepted its first code before `mfa_recovery_completed` was recorded has no such event, and none is written for it afterwards: the record is append-only, and what closed a recovery until then, an inference from the enrolment events, was removed on purpose and has no fallback. A development database that holds such a recovery shows it as open. The Administrator who authorised it is refused the approval of that account's enrolments, and the first code of the account's next approved device records the event at that later moment. To clear it, recreate the development database (`docs/DEVELOPMENT.md`). No production database is affected, because nothing was deployed before the event was recorded.
- No notification is sent, and no page shows the history of recoveries. An installation with fewer than three Administrators recovers an Administrator only by the break-glass command, and one with fewer than two cannot recover a Reviewer at all.

**The break-glass command**

The last resort of [ADR-0017](docs/adr/0017-account-recovery.md) (points 59 to 70), for one case: an Administrator who lost the second factor, when the other Administrators that the application's own recovery needs do not exist. That includes the only Administrator. It is never used for a Reviewer or for any other account.

```sh
python manage.py recover_mfa_break_glass
```

- **There is no way to it on the web.** No page, parameter, header, cookie, setting, or environment variable performs or shortens it, and no permission or role reaches it. Its two services take no acting account and are called by this command and by nothing else in the application.
- **It is run by a person at a terminal on the server.** It refuses to run unless both its input and its output are a terminal. It defines no option and no argument of its own, has no non-interactive mode, and reads nothing from the environment.
- **It asks for exactly three things**: the email address of the account, a request number, and a phrase typed out as confirmation. The account and the number must name the same request.
- **The phrase chooses the action.** There are two phrases, fixed in the command, and each is compared exactly as it was typed: `revoke lost second factor` and `approve enrolment after recovery`. Anything else does nothing. The action is never inferred from the state of the account.
- **It handles no secret.** It asks for no password, code, secret, or token, shows none, and nothing it asks for is typed hidden. What was typed is never written back or logged, because people type passwords where something else was asked for.
- **Revoking the lost device** stands in for an Administrator's authorisation. The number is that of the account's current recovery request, which the owner made from a sign-in whose password was accepted. Every condition of an authorisation other than the existence of the Administrators applies, decided inside the transaction: the request is the account's current one and younger than 30 minutes; it was recorded after the account's latest password reset; 24 hours have passed since that reset; and the account is active and has an active second factor. Two more are the command's own: the account holds the Administrator role, and fewer than two Administrators who are able to act exist other than the account, so that the application's path, which needs one to authorise and another to approve, is unavailable.
- **What a revocation does** is exactly what an authorisation does, by the same function: it deletes the device and its secret, raises the session epoch by one, and removes every pending challenge, the password-reset token, and the recovery request of the account. It records one `mfa_recovery_break_glass` event whose action is `revoke_device`. No `mfa_recovery_authorized` event is written, because that event must name an Administrator.
- **Approving the enrolment that follows** stands in for an Administrator's approval. The number is that of the account's enrolment request. It is done only if the request is that account's, awaits approval, and has not lapsed; the account is active and holds the Administrator role; the account has an open recovery, whichever way it was opened; the request is the current one of that recovery; and no Administrator who may approve it exists. The Administrator who authorised the recovery may not approve it, so that Administrator does not count. The 24 hours after a password reset are a condition of the revocation and not of this approval, as they are not a condition of an Administrator's approval.
- **The current enrolment of the open recovery.** The request counts as made in the recovery if the account's latest enrolment event is an `mfa_enrollment_started` event recorded after the event that opened the recovery. A request in the table that no such event accounts for is refused. An enrolment that succeeded earlier in the same recovery and was replaced afterwards does not count against the request that replaced it.
- **What an approval does**: the device awaits its first code and records the time of the approval and no approver. It records one `mfa_recovery_break_glass` event whose action is `approve_enrollment`. No `mfa_enrollment_approved` event is written.
- **What it never does.** It issues no secret, creates no device, marks no device active, signs nobody in, returns no authentication context, and sets no password. It changes no role, status, or email address, and creates no account and no role event. After an approval the owner still signs in on the password and gives the first code of the new device in the application; only that makes the device active, and it is also what records `mfa_recovery_completed`.
- **Who does what.** Where one other Administrator is able to act, the command revokes and that Administrator approves through the application: nobody authorised a recovery that the command opened, so nobody is barred. For the only Administrator the command does both. Where two others are able to act the command refuses, and they do it.
- **Locks.** Both actions take the lock on the role event table first, as every change to a role or a status does. A revocation then takes the lock on the account's email address that a sign-in holds. Both then take the second-factor locks of the account and of every active Administrator on record, in ascending order of account identifier, and then the account's row and the request's or the device's. Holding the other Administrators' second-factor locks keeps still which of them are able to act, so that what the command found is true when it commits. This is the order every other operation uses, no operation takes these locks in another order, and the command writes nothing that names another account.
- **One answer for every refusal.** The services return a single outcome, and the command prints one sentence that repeats nothing that was typed. The reason is a fixed value in the log line `mfa_recovery.break_glass_unavailable`, with the action and nothing else. A refusal changes nothing and records no event.
- **What is recorded.** The event names the account and no acting user, holds an empty source, because the command is not a request, and carries the correlation identifier of the run, which the log lines of that run carry too. It holds no free text. Success is printed only after the transaction has committed.
- **Who ran it is not recorded by the application.** The application has no model of operators, and no account is invented to stand for one. That belongs to the operational audit trail of the server, which ADR-0008 is to define and which does not exist yet.

**Residual risks of the break-glass command**

- It is a standing capability of whoever controls the server and can run a command under the application's settings. It adds nothing to what that person could already do in the database, and makes it constrained and recorded. The application cannot authenticate that person: requiring a terminal stops automation and is not authentication.
- Until ADR-0008 defines the operational audit trail, a use of the command is recorded without the name of whoever ran it.
- It is as strong as the operator's check. A revocation or an approval given without identifying the person and asking for the number trusts whoever made the request. For the only Administrator both checks are made by the operator, who may be one person.
- An Administrator who can run the command recovers their own account by it. That is the consequence ADR-0017 accepts for an installation that has nobody else, and it is refused inside the application as before.
- A recovery request lapses after 30 minutes, so the operator has to be at the terminal when the owner asks.
- The command has no limit of its own on how often it is run. A revocation uses up a recovery request, and requests are limited to five in an hour for an account.
- Besides the options Django gives every management command, such as `--settings` and `--no-color`, the command defines none. None of those carries an input of the command.
- The activation of an account that awaits verification is not held still by the command's locks. Such an account has no second factor, so it cannot become able to act while the command runs.
- Both actions hold the lock on the role event table and the second-factor locks of every Administrator for one short transaction: a sign-in of any Administrator at the code step waits for it.

**Key management assumptions**

- The key is generated randomly, never committed, and held only in the deployment's protected configuration.
- A database backup does not contain the key. The key must be backed up separately, or every second factor is lost with it.
- **Rotation is not built.** Changing the key makes every stored secret undecryptable: every enrolled account is refused at the code step until its device row is removed and it enrols again. A rotation that re-encrypts under a new key is designed with the deployment decision (ADR-0008).
- A leaked database alone does not expose TOTP secrets. A leaked database together with the key does.

**Residual risks**

- An account that requires a second factor and has not yet enrolled holds no privilege, and its password cannot establish one. What remains rests on the approving Administrator: an approval given without asking the person for the request number trusts whoever made the request.
- Whoever knows the password of such an account can still make requests in its name. That replaces the owner's pending request and delays the enrolment; it gains nothing unless an Administrator approves it.
- The first Administrator's second factor is as trustworthy as the bootstrap: whoever can run commands on the server at that moment sets it up.
- A session that existed before its account enrolled stays signed in, at the weaker assurance, until it ends.
- TOTP does not resist real-time phishing: a code typed into a hostile page can be relayed within its 30 seconds.

### Web application threats

- Django's defaults for CSRF, session security, clickjacking protection, and SQL parameterisation are kept on. A strict Content Security Policy is applied.
- Document-derived text and model output are always auto-escaped.
- Permissions are checked in the service layer, deny by default.
- Rate limits apply to public pages per client address, and to login, AI questions, URL submission, and uploads per account.
- There is no public self-registration. Accounts are created by an Administrator.
- The interface is server-rendered. HTMX is served from the application's own static files at a pinned version, with its script-evaluation features turned off. There is no API at launch (ADR-0010).
- **Multi-factor authentication with TOTP is required for Administrator and Reviewer accounts.** Such an account cannot use its privileges until TOTP is enrolled with an Administrator's approval and a code has been verified for the sign-in (ADR-0007, ADR-0014).
- **Django admin.** Restricted to Administrators, on a non-default path. Models for provenance and integrity-governed records (artifacts, acquisition records, versions, reviews, rights, extractions, segments, passages, releases, observations, claims, evidence, claim reviews, analysis and search runs, AI interaction records, audit events, redaction records) are registered read-only: no add, change, or delete. All writes to them go through services. The database-level protection on append-only tables applies to the web process's role as well, so the admin cannot bypass it even through a defect. Admin write access is limited to operational data such as users and roles.

### Export safety

Exports contain text derived from external documents. In spreadsheet formats, a text cell beginning with `=`, `+`, `-`, `@`, a tab, or a carriage return is neutralised so that it cannot be executed as a formula when opened. Numeric cells are written as numbers and are not altered.

### Cost and resource abuse

- Per-user and global budgets for AI calls, computed from cost records in PostgreSQL and checked before each call. Redis counters are used only for short-window request throttling and are not the record of spending.
- The assistant degrades to "unavailable" rather than exceeding budget.
- Queue length limits and per-source fetch rate limits.

### Secrets, supply chain, and data stores

- Secrets are provided through the environment, never committed, and scoped per container. The fetch worker and parse worker receive no database credentials and no AI provider key.
- Redis requires authentication, is reachable only on the internal network, and gives each isolated worker an account restricted to its own queue (mechanism in ADR-0011).
- Backups are encrypted before they leave the server. Keys are stored separately from the backups.
- Dependencies are locked with hashes and audited in CI. Base images are pinned by digest and scanned.
- CI uses least-privilege tokens and pinned action versions.

### Logging and privacy

- Logs never contain secrets, session tokens, document bodies, or full prompts.
- User questions are stored in the AI interaction record under a retention policy (undecided, blocker B19), not in application logs. Retention is enforced through the redaction procedure in [docs/DATA_MODEL.md](docs/DATA_MODEL.md) §7.
- Security-relevant events are logged: logins, permission denials, blocked fetches, parser kills, verification failures, index changes, rights determinations, and redactions.

## Requirements for contributors

1. A change touching fetch, parse, storage, authentication, rights, or the AI pipeline needs a security review.
2. Every control above has at least one negative test.
3. A control is never disabled to unblock a task. If a control is wrong, change it through review.

## Known residual risks

- A hostile document can still contain false statements. Verification proves that an answer matches its sources, not that the sources are true.
- A parser zero-day inside the parse worker could corrupt the output for the files processed by that worker. Isolation limits the blast radius but does not remove the risk.
- The isolation mechanism for the fetch and parse workers is not yet proven (blocker B21).
- Model-based support checks can be wrong and can be manipulated. Their error rate and attack success rate are measured, not assumed to be zero.
