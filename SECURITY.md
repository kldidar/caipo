# Security

## Reporting a vulnerability

Do not open a public issue for a security problem. A private reporting channel has not yet been set up; this is tracked as gate blocker B18 in [docs/PROJECT_SPECIFICATION.md](docs/PROJECT_SPECIFICATION.md#10-architecture-gate) and must be resolved before the repository is made public. The intended channel is GitHub private vulnerability reporting plus a monitored contact address.

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

Each document version has recorded rights, set by a Reviewer. With no rights determination, everything except storage for review is denied.

| Use | Requires |
|---|---|
| Text sent to an external AI provider (synthesis, support check, hosted embedding or reranking) | Right to transmit to an external provider |
| Quoted text shown to users | Right to display excerpts; otherwise the reference shows the locator without the text |
| Full text or original file shown or downloaded | Right to display in full |
| Text included in exports and data snapshots | Right to redistribute |

The rights policy itself is undecided (blocker B7).

### Web application threats

- Django's defaults for CSRF, session security, clickjacking protection, and SQL parameterisation are kept on. A strict Content Security Policy is applied.
- Document-derived text and model output are always auto-escaped.
- Permissions are checked in the service layer, deny by default.
- Rate limits apply to login, AI questions, URL submission, and uploads.
- **Multi-factor authentication is required for Administrator and Reviewer accounts.** The mechanism is to be chosen (ADR-0007).
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
