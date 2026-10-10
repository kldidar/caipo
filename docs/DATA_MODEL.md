# Data Model

Status: Draft for owner and researcher review · Last updated: 2026-10-02

This is a conceptual domain model. Field lists name what must be captured; exact columns, types, and indexes are settled during implementation and reviewed with each migration. Decision record: [ADR-0005](adr/0005-evidence-and-provenance-model.md) (Accepted).

## 1. Modelling principles

1. **Separate the work from the copy.** A document as an intellectual work, a specific version of it, and the bytes that were obtained are three things.
2. **Cite spans, not documents.** Evidence points to an exact passage in an exact version.
3. **Provenance is append-only**, with one controlled exception for legally or privacy-required redaction (§7). Corrections add records.
4. **Extracted text and retrieval data are separate.** A Segment is extracted source text and is never changed for retrieval purposes. A RetrievalChunk is derived from Segments and can be regenerated freely.
5. **State changes are events.** Where a provenance record needs a status or a "current" pointer, the change is recorded as an append-only event and the current value is derived from the latest event. The historical record itself is not mutated.
6. **Statements are typed.** Each claim has one epistemic type; origin and confidence are separate properties.
7. **Time is explicit.** Institutions, policies, and data change. Validity periods and releases are recorded.
8. **Countries are data.** Nothing in the schema is specific to Turkmenistan or Uzbekistan.
9. **Original text is preserved.** Translation and transliteration are additional fields.
10. **Referential integrity is enforced by the database.** No generic foreign keys for evidence.

### Terminology

| Term | Meaning |
|---|---|
| **Segment** | An immutable unit of extracted text, belonging to one Extraction |
| **RetrievalChunk** | A derived unit used for search, built from one or more Segments under a versioned chunking configuration |
| **Passage** | An exact, verifiable pointer to a span of text inside one Segment. What evidence refers to. |
| **AnswerCitation** | A record that one statement in an AI answer cited a Passage or an Observation |
| "citation" (in prose) | A rendered reference shown to a reader. It is produced from a Passage or Observation and is not a stored entity. There is no `Citation` model. |

## 2. Overview

```mermaid
erDiagram
    Country |o--o{ Institution : has
    Institution ||--o{ Source : publishes
    Source ||--o{ Document : contains
    Document ||--o{ DocumentVersion : has
    DocumentVersion }o--|| Artifact : stored_as
    Artifact ||--o{ AcquisitionRecord : obtained_by
    DocumentVersion ||--o{ Extraction : extracted_into
    Extraction ||--o{ Segment : contains
    Segment ||--o{ Passage : anchors
    Segment }o--o{ RetrievalChunk : derived_into
    RetrievalChunk ||--o{ ChunkEmbedding : embedded_as
    IngestionRequest ||--o{ IngestionEvent : logs
    IngestionRequest }o--o| AcquisitionRecord : produced

    Country ||--o{ Policy : adopts
    Policy ||--o{ PolicyDocumentLink : expressed_in
    Document ||--o{ PolicyDocumentLink : expresses
    Policy ||--o{ PolicyObjective : states
    Policy ||--o{ PolicyInstrument : uses
    Policy ||--o{ PolicyEvent : has
    Policy }o--o{ Sector : targets

    Indicator ||--o{ IndicatorSeries : measured_as
    Country ||--o{ IndicatorSeries : for
    Source ||--o{ DatasetRelease : issues
    DatasetRelease ||--o{ Observation : contains
    IndicatorSeries ||--o{ Observation : has

    ResearchClaim ||--o{ Evidence : supported_by
    Evidence }o--o| Passage : cites
    Evidence }o--o| Observation : cites
    Evidence }o--o| AnalysisRun : cites
    Evidence }o--o| SearchRun : cites
    ResearchClaim ||--o{ ClaimReview : reviewed_in

    AIInteraction ||--o{ InteractionStageRecord : ran
    AIInteraction ||--o{ RetrievalHit : retrieved
    AIInteraction ||--o{ AnswerStatement : produced
    AnswerStatement ||--o{ AnswerCitation : cites
    AnswerCitation }o--o| Passage : to
    AnswerCitation }o--o| Observation : to
```

## 3. Entities

"A-O" marks append-only records (subject to §7).

### 3.1 `accounts`

**User**, roles, and permissions. A user has an email address, a lifecycle status (§4.10), the time its email address was verified, the time it first became active, and a session epoch. The status is the only place the state is stored; whether an account can be signed in to is derived from it. The session epoch is a count that starts at 0 and cannot be negative. It is part of what binds a session to its user: at 0 a session is bound exactly as Django binds it, to the password alone, so adding the column ended no session; above 0 the epoch is bound in as well, so raising it ends the user's sessions without changing the password. Only the finalisation of a recovery raises it ([ADR-0017](adr/0017-account-recovery.md) point 46), by one, in the transaction that revokes the lost device: an Administrator's authorisation, or the revocation by the break-glass command. Roles are Reader, Researcher, Reviewer, Administrator; all are authenticated. An anonymous visitor to the public research site is not a role and has no User record (ADR-0007). A user may hold several roles. Permissions are not stored: which role holds which permission is a fixed table in code.

**RoleEvent** (A-O). One change to a user's roles: user, role, event type (§4.7), acting user, reason, time. It is both the store of roles and their history: there is no current-role record to overwrite. The acting user is recorded and is never the user whose role changes. The one exception, defined in [ADR-0012](adr/0012-authorization-and-role-event-integrity.md) as amended, is the grant that creates the first Administrator, which is made by an operator at the server before any account exists: it has no acting user, names the bootstrap command and the operator's operating-system account in its reason, can only be a grant of the Administrator role, and the database allows it only once. Users referenced by a RoleEvent cannot be deleted. UPDATE and DELETE are refused by a database trigger as well as by the application. It records role changes only; the general AuditEvent below is not built yet.

**AuthenticationEvent** (A-O). One sign-in, refused sign-in, sign-out, change to a second factor, step of a password reset, or step of the recovery of a lost second factor: event type (§4.8), time, the user if the submitted email address, reset token, or challenge belongs to an account, the acting user for a decision on another user's enrolment request or recovery request and for nothing else, the request's correlation ID, the break-glass action (§4.8) on a break-glass event and on no other, and keyed hashes of the submitted email address and of the source address. The email-address hash is empty for a refused reset token that belongs to no account, because no email address was submitted. No password, password hash, second-factor code or secret, challenge token, reset token or its hash, session identifier, header, or raw address. It is also what sign-in throttling, second-factor throttling, and password-reset throttling count, and what the two pages that show the history of recoveries read (§4.8); no second record of that history is kept. Retention is a future data-governance decision: no period is set, and until one is, nothing deletes these events ([ADR-0013](adr/0013-authentication-core-and-first-administrator-bootstrap.md)). The keyed hashes depend on the application's secret key, so rotating it makes earlier events unmatchable to later ones by address or source. It is not the general AuditEvent.

**AccountEvent** (A-O). One step in the lifecycle of a user ([ADR-0015](adr/0015-account-lifecycle-and-email-verification.md)): event type (§4.10), time, the user, the acting user where an Administrator caused it, the request's correlation ID, and a keyed hash of the source address of a verification attempt. A refused verification whose token belongs to no user names nobody. No token, token hash, password, or email address. The acting user is never the user the event is about, except when an Administrator disables their own account. It is also what the throttling of verification attempts counts. UPDATE and DELETE are refused by a database trigger as well as by the application. It is not the general AuditEvent.

**AccountActivation.** A user that awaits verification and the token that can activate it: user, a keyed hash of the token that was sent to the user's email address, and when it was issued. A user has at most one. It is replaced when the message is sent again, removed when it is used or the user is disabled, and void after 48 hours. Operational state, not a provenance record.

**PasswordReset.** An active user whose owner asked to replace a forgotten password, and the token that can do it ([ADR-0016](adr/0016-password-reset.md)): user, a keyed hash of the token that was sent to the user's email address, when it was issued, and when it lapses, which is 1 hour later and after the time of issue by a database constraint. A user has at most one, and a token hash occurs once. It is replaced when a reset is asked for again and removed when it is used or the user is disabled; enabling the user restores nothing. It is separate from AccountActivation, and neither token is accepted in place of the other. Operational state, not a provenance record.

**MfaRecoveryRequest.** A user whose owner asked for a lost second factor to be revoked ([ADR-0017](adr/0017-account-recovery.md)): user and when the request was made. Its identifier is the number of the request, which the owner is shown and an Administrator authorises or rejects. A user has at most one, by a database constraint. A request is never changed where it stands, unlike the other operational records here: which user it is for and when it was made decide whether it may be authorised, and the number names exactly that. A new request removes the row and creates another, so it has another number, and a number is never issued twice. The model and its manager refuse an update, which is every way the application writes this table; no database trigger stands behind them, so SQL sent past the model is not refused. It holds no token and no secret, and has no field for how a person was identified. It is created when the owner asks for recovery from a sign-in that awaits its code, which removes that MfaChallenge in the same transaction. It lapses after 30 minutes and stays in the table until it is replaced. An Administrator's rejection removes it. An Administrator's authorisation removes it in the transaction that also deletes the user's TotpDevice, raises the user's session epoch, and removes the user's MfaChallenge and PasswordReset. So does the revocation by the break-glass command, which takes the number of an Administrator's current request together with the user's email address, and does exactly the same. Operational state, not a provenance record.

**AuditEvent** (A-O). One successful change that a signed-in user made to a registry record ([ADR-0018](adr/0018-registry-and-general-audit-record.md)): action and target type (§4.11), the target's public identifier as a UUID (not a foreign key, because targets live in higher layers), the acting user, the request's correlation ID, time. The acting user is required: there is no anonymous, system, or bootstrap audit event. It has no free text and no details column. The order of events is the order of their identifiers. It is written only by one service in `accounts`, inside the transaction of the change it records, and is protected by a database trigger like the other event tables. It is not RoleEvent, AuthenticationEvent, or AccountEvent, and nothing is recorded both here and there. No registry record exists yet, so nothing writes it yet.

**AuditEventChange** (A-O). One attribute that an `updated` AuditEvent changed: the event, the field (§4.11), the old value, the new value. A value is the attribute's own value in one fixed rendering: text as stored, a date in ISO 8601, a reference as the public identifier of the record referred to, nothing as the empty string. A rendered value is at most 200 characters and is never shortened: a longer one is refused. No attribute on the list of fields may be given a longer limit without a review of this schema. The old and new values differ, and a field occurs once in an event. Only an `updated` event has change records; that rule is kept by the service, because the database cannot see it. Protected by a database trigger of its own.

**RedactionRecord** (A-O, never itself redacted). Records each use of the redaction exception: actor, time, legal or privacy basis, record class, target identifier, what was removed. See §7.

**TotpDevice.** The TOTP second factor of one user ([ADR-0014](adr/0014-totp-mfa-and-authentication-assurance.md)): user, state (§4.9), the secret under authenticated encryption, the identifier of the key that encrypted it, the time step of the last code accepted, when it was created, when it was confirmed, and when and by whom its enrolment was approved. A user has at most one, in any state; a user with none is not enrolled. A device is trusted when it records an approval: by an Administrator, who is named and is never the device's own user, or by one of two things that name nobody, the first-Administrator bootstrap and the break-glass command's approval of the enrolment that follows the recovery of an Administrator ([ADR-0017](adr/0017-account-recovery.md) point 69). Only a trusted device counts towards the `MFA_VERIFIED` assurance. The secret is stored only as AES-256-GCM ciphertext (`bytea`) under a key that is not in the database, bound to the user, so it does not decrypt in another user's row; the key identifier is a keyed fingerprint that reveals nothing of the key. Operational state, not a provenance record: it is updated when it is approved and when a code is accepted, and deleted when the second factor is disabled, replaced, or its request rejected. What happened to it is recorded in AuthenticationEvent.

**MfaChallenge.** A sign-in whose password was accepted and whose second-factor code is awaited: user, a keyed hash of the token that the pending session holds, and when it was issued. A user has at most one. It is created only by the sign-in service, removed when it is used, cancelled, or replaced, and void after five minutes. Operational state, not a provenance record.

### 3.2 `registry`

**Country.** ISO 3166 alpha-2 and alpha-3 codes, English name, active flag. Any country can be added.

**Institution.** A body that issues, implements, or publishes: ministry, legislature, regulator, statistical agency, international organisation, university, media outlet, company.
- Country, **optional** (empty for international bodies); kind; parent institution
- Valid-from and valid-to dates, and a successor link, because government bodies are renamed, merged, and dissolved
- Names in a child table **InstitutionName**: text, language, script, and kind (official, transliteration, English rendering, abbreviation)

**Language.** Language code and script code. Uzbek in Latin and Uzbek in Cyrillic are distinguishable.

### 3.3 `sources`

**Source.** A publishing channel from which documents or data are obtained, for example a legal database or a statistical portal.
- Publishing institution, source type and **source tier** ([protocol §4.1](RESEARCH_PROTOCOL.md))
- **Allowed hosts**: the only hosts from which the system will fetch for this source. Changing them requires the Reviewer role and is audited.
- Notes on independence, terms of use, and licence

**Document.** The intellectual work, independent of language and of any particular copy.
- Source, issuing institution, country or countries
- Document type: law, decree, resolution, strategy, programme, regulation, report, statistical publication, article, press release, other
- Official identifier and date of issue, where they exist
- Title in the original language, with language; English title marked as official or unofficial

**DocumentVersion.** One specific text of a document. Its fields do not change after creation.
- Document, language, script
- Kind: original, official translation, unofficial translation
- Text state: as adopted, or consolidated as amended to a date
- Artifact

**Artifact** (A-O). The stored bytes.
- SHA-256, size, detected media type, storage key
- Content-addressed: identical bytes are stored once

**AcquisitionRecord** (A-O). One successful act of obtaining an artifact. Linked to the **Artifact**; an artifact can have many acquisition records.
- Method: fetch or upload
- For a fetch: requested URL, final URL, redirect chain, resolved address, response status, selected response headers
- For an upload: the **claimed origin** (URL or description supplied by the uploader)
- **Origin verification**: `observed` (the system fetched it from the origin itself), `attested` (the uploader states the origin; the system has not verified it), or `corroborated` (a later guarded fetch from the claimed URL produced the same hash)
- Time and acting user
- A re-fetch that yields the same hash adds an acquisition record to the existing artifact. A different hash creates a new artifact and a new document version.

**DocumentReview** (A-O). A review event for a document version: event type, actor, time, reason. The version's review status is derived from the latest event (§4.2).

**RightsDetermination** (A-O). A recorded decision on what may be done with a document version. It answers six separate questions: store; workspace display (full text to authenticated research users); public excerpt display; public full display; redistribute; transmit to an external AI provider. Actor, time, basis. The current rights are those of the latest determination. With no determination, the version is available only to the Researcher who submitted it and to Reviewers, for the purpose of review, and every other use is denied. Rights are checked independently of authentication: a role never substitutes for a right, and a right never substitutes for a permission. See [RIGHTS_AND_LICENSING.md](RIGHTS_AND_LICENSING.md).

**Extraction** (A-O). The result of running one parser configuration on one version.
- Document version, parser name and version, configuration hash
- Method: embedded text, OCR, or mixed
- Quality indicators, warnings, and content flags raised by the parser (for example instruction-like text or hidden text)
- Several extractions can exist for one version.

**ExtractionSelection** (A-O). Records that an extraction was selected as current for its version: extraction, actor, time, reason. The current extraction is the one named by the latest selection. Extractions themselves are never modified to mark them current.

**Segment** (A-O). A structural unit of extracted text. Never altered for retrieval experiments.
- Extraction, order, locator (page; structural path such as chapter, article, paragraph)
- Text in the stored representation defined in §5, text hash, offsets within the extraction's full text

**Passage** (A-O). An exact pointer to a span of text within **one Segment**.
- Segment, start and end offset, the quoted text, and its hash
- A passage is verifiable against the stored extracted text of its segment. It stays verifiable when a later extraction becomes current, because the segment and the passage's own quote and hash are retained. It is not directly verifiable against the artifact bytes without re-running the same parser version or a human reading the original.

### 3.4 `ingestion`

**IngestionRequest.** A request to bring an external file into the system. Operational record, not provenance.
- Kind: document fetch, document upload, dataset fetch, dataset upload
- Requesting user, target source, target document or dataset where known, submitted URL or upload reference
- Current state and current stage (§4.1), attempt counts per stage, failure reason
- The AcquisitionRecord it produced, when it succeeds in acquiring

**IngestionEvent** (A-O). Every state or stage transition of a request: from, to, time, reason, worker. The request's current state is a convenience copy of the latest event.

A fetch that fails leaves an IngestionRequest in state `failed` and no artifact, acquisition record, or document version.

### 3.5 `indicators`

**Indicator.** A measured concept: name, definition, unit, category. Covers economic and socioeconomic measures.

**IndicatorSeries.** One indicator for one country from one source, with frequency, unit as published, and methodological notes. Two providers publishing the same indicator for the same country are two series.

**DatasetRelease** (A-O). One import of a provider's data at a point in time: source, provider's release label or date, retrieval time, raw artifact, import report. A release can be marked withdrawn by a **DatasetReleaseEvent** (A-O) with actor, time, and reason.

**Observation** (A-O). One value.
- Series, period, release
- Value as an exact decimal, or empty
- Status: reported, estimated, provisional, projected, missing
- Provider footnotes
- Unique per series, period, and release. A revised value arrives as an observation in a later release.

### 3.6 `policies`

**Policy.** A policy initiative as a unit of analysis: a strategy, programme, law, or regulatory framework. One policy may be expressed in several documents.
- Country, lead institution, policy type
- Title in original language and English
- Codebook version used for coding
- **No stored status.** Formal status is derived from PolicyEvents (§4.4).

**PolicyDocumentLink.** Connects a policy to documents with a role: enacting text, amendment, implementing act, official report, external assessment, commentary.

**PolicyEvent.** A **formal legal or policy lifecycle event** only. Event types: `adopted`, `amended`, `entered_into_force`, `expired`, `repealed`. Each has an effective date and links to the Passage in a formal text that establishes it.

PolicyEvent never records implementation. Funding, reported milestones, progress, and announcements of implementation are recorded as research claims of type implementation evidence (§3.7), with their own evidence, source tier, and review. If no formal text establishes a lifecycle event, it is not recorded as a PolicyEvent; what is known about it is recorded as a claim.

**PolicyObjective.** A goal the policy states, with any stated target value and date, linked to the Passage stating it.

**PolicyInstrument.** A concrete means the policy provides for, with an **InstrumentType** from the codebook, the responsible institution, any resources stated in the text, and the Passage it was coded from. It records what the text provides for, not whether it was carried out.

**Sector.** A hierarchical taxonomy of sectors. Policies and instruments link to sectors.

**PolicyRelation.** Typed link between policies: amends, supersedes, implements, refers to.

**InstrumentType** and **Sector** values come from the codebook, which is not yet written (blocker B11). They are data, not enumerations in code.

### 3.7 `research`

**ResearchClaim.** A research statement.
- Text
- Type: `documented_fact`, `policy_objective`, `implementation_evidence`, `observed_outcome`, `correlation`, `interpretation`, `negative_finding` ([protocol §5](RESEARCH_PROTOCOL.md))
- Confidence (high, moderate, low) and written rationale. This is the explicit representation of uncertainty for claims.
- Origin: `human`, or `ai_assisted` (the author declares that AI assistance was used in drafting; the claim is still authored and reviewed by people)
- Status (§4.3)
- Scope: countries, policies, period
- An approved claim's text is immutable. A revision is a new claim that supersedes the old one.

**Evidence.** Links a claim to one piece of support.
- Exactly one target: a Passage, an Observation, an AnalysisRun, or a SearchRun. Enforced by a check constraint.
- Stance: supports, contradicts, provides context
- Directness: direct statement, or indirect
- Note by the researcher
- Editable while the claim is `draft`. Cannot be changed while the claim is `in_review` or after it is `approved`.
- Evidence that has been part of a submission for review is never deleted. In a claim returned to `draft` it can be **retired** from the current evidence set; the row remains, marked retired, and the submission it belonged to remains on record.

**ClaimRelation.** Typed link between claims: builds on, contradicts, alternative to.

**ClaimReview** (A-O). One submission for review and its outcome: the exact claim text and the evidence set as submitted, the reviewer, the decision (`approved` or `returned`), comment, time, and whether it was self-review. Because the submitted text and evidence set are stored here, a returned submission stays fully traceable after the claim is edited.

**AnalysisRun** (A-O). A recorded quantitative analysis: method, parameters, inputs (series with their releases; PolicyEvents where the method is a temporal comparison), code version, result summary, output artifact hash. Can be marked invalidated by an append-only event with reason.

**SearchRun** (A-O). A recorded search for sources, used to evidence negative findings and to document corpus building.
- Query or queries, in each language searched
- Date and time of the search, and who ran it
- **Source universe**: which sources, databases, or sites were in scope
- Inclusion criteria and exclusion criteria applied
- **Sources examined**: what was actually looked at, including items found and excluded, with reasons
- Search method: manual site search, database query, corpus search inside CAIPO, or other, with enough detail to repeat it
- Outcome: `no_qualifying_source_found`, `qualifying_sources_found`, or `inconclusive`, with a written summary
- Configuration and version metadata where the search used system components (for example corpus snapshot, chunking configuration, retrieval parameters)
- Can be marked invalidated by an append-only event with reason.

A SearchRun is a record of what was done. It is never represented as a document, and "no qualifying source was found" is never represented as a Passage.

### 3.8 `retrieval` (derived, rebuildable, not provenance)

**ChunkingConfiguration.** A versioned definition of how Segments are combined or split into chunks. Stored in the repository; referenced by identifier.

**RetrievalChunk.** A unit used for search.
- Chunking configuration version
- References one or more contiguous Segments of one extraction, with the start offset in the first and the end offset in the last
- Derived search text and lexical search vector, produced by the search-side transformations in §5
- Built only from eligible segments (rule I-7)
- Can be deleted and regenerated at any time without touching Segments

**ChunkEmbedding.** A vector for one RetrievalChunk under one embedding model version. Embeddings belong to chunks, never to Segments.

### 3.9 `assistant`

**AIInteraction** (A-O). One question. Created once at the start with fields that never change: user, question, detected language, pipeline version, prompt versions, model identifiers and settings, chunking configuration version.

**InteractionStageRecord** (A-O). One row per pipeline stage executed: stage, result, timing, token counts, cost. The interaction's outcome (§4.5) is derived from its stage records. Stages add rows; they never update the interaction.

**RetrievalHit** (A-O). Each candidate retrieved: the Segment span or Observation it corresponds to, the chunking configuration version, rank and scores per retriever, whether it was placed in the model context, and the handle it was given. It references Segments and offsets, not RetrievalChunk rows, so it survives chunk regeneration.

**AnswerStatement** (A-O). Each statement in the answer: text, assistant label, verification result, uncertainty flags, and whether it is cross-language ([AI_ARCHITECTURE.md](AI_ARCHITECTURE.md) §7–8).

**AnswerCitation** (A-O). Links a statement to a Passage or an Observation, with the verification result. A citation to a chunk that spans several Segments is stored as one Passage per Segment span.

Budget accounting is derived from the cost recorded in InteractionStageRecords in PostgreSQL.

### 3.10 `evaluation`

**EvalRun** and **EvalResult.** A run of the evaluation suite against a dataset version, corpus identifier, and pipeline configuration, with per-case results. Gold datasets are versioned files in the repository that refer to artifacts by hash and to segments by locator and contain no copyrighted document text.

## 4. Lifecycle states

All state names used anywhere in the project are defined here. Other documents must use these names.

### 4.1 IngestionRequest

| State | Meaning |
|---|---|
| `pending` | Accepted and waiting for a worker |
| `running` | A worker is executing the current stage |
| `retrying` | The current stage failed with a retryable error and is scheduled again |
| `succeeded` | All stages completed; an extraction or dataset release exists |
| `failed` | Stopped with a recorded reason; not retried automatically |
| `cancelled` | Stopped by a user before completion |

Stages, in order: `fetch` (or `receive` for uploads), `store`, `detect`, `parse`, `validate`. Failure reasons are a fixed list, including `blocked_by_fetch_guard`, `host_not_allowed`, `source_unreachable`, `size_limit`, `type_not_allowed`, `parser_error`, `worker_killed`, `attempt_limit`, `validation_failed`.

### 4.2 DocumentVersion review status

Derived from the latest DocumentReview event.

| Event | Resulting status | Meaning |
|---|---|---|
| `submitted` | `submitted` | Awaiting review. Not searchable or citable. |
| `approved` | `approved` | Citable and eligible for retrieval, subject to rights |
| `rejected` | `rejected` | Not accepted into the corpus |
| `suspended` | `suspended` | Temporarily removed from retrieval and from new citation while a concern is investigated |
| `reinstated` | `approved` | Suspension lifted |
| `withdrawn` | `withdrawn` | Permanently removed from use, with reason. The record remains. |

### 4.3 ResearchClaim

| Status | Meaning |
|---|---|
| `draft` | Being written, or returned by a reviewer. Text and evidence editable. |
| `in_review` | Submitted. Text and evidence cannot be changed. |
| `approved` | Passed review. Text and evidence permanently fixed. |
| `needs_reassessment` | Was approved; one or more of its supporting evidence items has become unavailable. Set automatically. |
| `disputed` | Approved but challenged, with a recorded reason |
| `withdrawn` | No longer asserted, with a recorded reason. The record remains. |

Permitted transitions:

| From | To | How |
|---|---|---|
| `draft` | `in_review` | Author submits. A ClaimReview records the submitted text and evidence set. |
| `in_review` | `approved` | Reviewer approves |
| `in_review` | `draft` | Reviewer returns the claim. The ClaimReview with its decision and the submitted evidence set remains on record. |
| `approved` | `needs_reassessment` | Automatic, when supporting evidence becomes unavailable |
| `approved` | `disputed` | Recorded challenge |
| `approved`, `needs_reassessment`, `disputed` | `withdrawn` | With a reason, including when a revised claim supersedes it |
| `needs_reassessment`, `disputed` | `approved` | A new review approves it again |

An approved claim never returns to `draft`. It is revised only by a new claim that supersedes it. No claim that has been submitted, returned, or approved is ever deleted.

An evidence item is **unavailable** when its target is a Passage whose document version is `suspended` or `withdrawn` or has been redacted, an Observation whose release is withdrawn, or an AnalysisRun or SearchRun that has been invalidated.

When that happens to an approved claim:

1. The claim moves to `needs_reassessment` automatically, with an audit event naming the cause.
2. It is no longer presented as approved. It stays visible with a notice stating that its evidence is under reassessment. It is excluded from comparisons and from exports of approved claims.
3. Nothing is deleted. The claim, its evidence links, and its review history remain.
4. A reviewer resolves it by one of: re-approving it if the remaining evidence still satisfies I-5 (recorded as a new ClaimReview); superseding it with a revised claim; or withdrawing it.
5. If a suspended document version is reinstated, the claim does not return to `approved` automatically. A reviewer re-approves it.

### 4.4 Policy formal status

Derived from PolicyEvents by effective date. Never stored.

| Derived status | Condition |
|---|---|
| `unknown` | No PolicyEvent recorded |
| `adopted_not_in_force` | `adopted` recorded, no `entered_into_force` |
| `in_force` | `entered_into_force` recorded, no later `expired` or `repealed` |
| `expired` | `expired` recorded |
| `repealed` | `repealed` recorded |

`amended` does not change status.

### 4.5 AIInteraction outcome

`answered`, `abstained`, `refused` (out of scope or blocked by the input guard), `failed`, `timed_out`.

AnswerStatement verification result: `verified`, or `removed` with a reason from a fixed list.

AnswerStatement uncertainty flags are not states. Their names and conditions are defined in one place, [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md) §8.

### 4.6 Records with invalidation or withdrawal events

DatasetRelease (`imported`, `withdrawn`), AnalysisRun and SearchRun (`valid`, `invalidated`). The status is derived from the latest event.

### 4.7 RoleEvent

Event types: `granted`, `revoked`. A user holds a role when the latest RoleEvent for that user and that role is `granted`. Holding a role and being able to use it are different things. An account that is disabled, or that awaits verification, holds its roles on record and gets nothing from them. A Reviewer or Administrator role confers its permissions only to a sign-in that verified a code from the account's active, trusted second factor; on a password alone it allows managing that second factor and nothing else ([ADR-0014](adr/0014-totp-mfa-and-authentication-assurance.md)).

### 4.8 AuthenticationEvent

Event types: `login_success`, `login_failure`, `logout`, `password_confirmation_failed`, `mfa_challenge_issued`, `mfa_enrollment_started`, `mfa_enrollment_succeeded`, `mfa_verification_failed`, `mfa_verification_succeeded`, `mfa_disabled`, `mfa_enrollment_approved`, `mfa_enrollment_rejected`, `mfa_device_replaced`, `password_reset_requested`, `password_reset_succeeded`, `password_reset_failed`, `mfa_recovery_requested`, `mfa_recovery_failed`, `mfa_recovery_rejected`, `mfa_recovery_authorized`, `mfa_recovery_completed`, `mfa_recovery_break_glass`. Only a `login_failure`, a `password_reset_requested`, a `password_reset_failed`, and an `mfa_recovery_failed` can be without a user: the email address, the reset token, or the challenge that was submitted may belong to no account. `mfa_enrollment_started` records that an enrolment was requested and `mfa_enrollment_succeeded` that one was completed. `mfa_enrollment_approved`, `mfa_enrollment_rejected`, `mfa_recovery_rejected`, and `mfa_recovery_authorized` name the acting user, who is never the user the event is about; no other event names one. For an account with an active second factor, the accepted password is recorded as `mfa_challenge_issued`, and `login_success` is recorded only when the code is accepted. Every reset request that is not throttled is recorded as `password_reset_requested`, whether or not its email address has an account; a refused reset token as `password_reset_failed`, naming the user only if the token is that user's current one; and a password that was replaced as `password_reset_succeeded`. A successful reset changes the password and removes the user's PasswordReset and any MfaChallenge; it changes no status, role, or second factor ([ADR-0016](adr/0016-password-reset.md)).

The six `mfa_recovery_` event types are those of [ADR-0017](adr/0017-account-recovery.md) point 82. All six are recorded. Two by a recovery submission: `mfa_recovery_requested` when a request is created, naming the user, and `mfa_recovery_failed` when a submission is refused, naming the user only if its challenge is still that user's current one. A submission that a limit stops records nothing. Two by an Administrator's decision, each naming the user and the Administrator: `mfa_recovery_authorized` when a request is authorised, which revokes the user's device, and `mfa_recovery_rejected` when one is rejected. A decision that is not made records nothing. One by the confirmation of an enrolment: `mfa_recovery_completed`, naming the user and no acting user, when a device that an Administrator or the break-glass command approved accepts its first code while the user has an open recovery. It is recorded after that enrolment's `mfa_enrollment_succeeded`, in the same transaction, and once for a recovery. The sixth, `mfa_recovery_break_glass`, is recorded by the break-glass command and by nothing else, once for each emergency action, in the transaction that performs it. Where the command stands in for an authorisation or an approval, this event is the record of that act, and `mfa_recovery_authorized` or `mfa_enrollment_approved` is not written. The two events of a submission are also what the three limits on recovery submissions count. Whether a request was made before or after the user's latest password reset is read from the order of the identifiers of the `mfa_recovery_requested` and `password_reset_succeeded` events, not from their times; the time of the reset event is used only to count the 24 hours after it. Whether a user has an open recovery is derived, never stored: a recovery is open from the user's most recent opening event, which is an `mfa_recovery_authorized` event or an `mfa_recovery_break_glass` event whose action is `revoke_device`, until an `mfa_recovery_completed` event recorded after it, ordered by their identifiers. Whether a recovery is open and who authorised it are two questions: a recovery that the break-glass command opened is open and has no authoriser. The Administrator named in an `mfa_recovery_authorized` opening does not approve the user's next enrolment ([ADR-0017](adr/0017-account-recovery.md) point 37); a break-glass opening bars nobody. A break-glass event whose action is `approve_enrollment` opens and closes nothing. Whether a request that awaits approval was made in the open recovery is derived too: it was if the user's latest enrolment event is an `mfa_enrollment_started` event recorded after the opening event. An `mfa_recovery_break_glass` event names the user and no acting user, and states which action it records as one of exactly two values, `revoke_device` or `approve_enrollment`. The value is required on that event type and is empty, never null, on every other; a database constraint holds both rules. There is no free text. A break-glass event also records no source: its source hash is empty, by a database constraint, because the command is not a request. That constraint says nothing about the source of any other event.

The history of recoveries that is shown to people ([ADR-0017](adr/0017-account-recovery.md) point 78) is read from these events and stored nowhere else. Six event types are shown, to the user the event names and to an Administrator verified with a trusted second factor: `mfa_recovery_requested`, `mfa_recovery_rejected`, `mfa_recovery_authorized`, `mfa_recovery_completed`, `mfa_recovery_break_glass`, and `mfa_enrollment_approved`. An `mfa_enrollment_approved` event is shown only inside a recovery: when, of the user's events that open or complete a recovery, the latest before it by identifier is an opening event. `mfa_recovery_failed`, every other enrolment event, every password-reset event, and every sign-in event are never shown. Of an event that is shown, the selector gives out only its time, a label in words, the email address of its user, and the email address of its acting user. To choose the label it reads the event's type and its break-glass action as stored and maps them to fixed labels; the two values as stored do not leave the selector. It exposes no identifier of an event, and never its correlation ID or either keyed hash. The order shown is that of the identifiers, latest first, and never that of the times. No event records that a message about a recovery was sent, and nothing records that a user has seen the history.

### 4.9 TotpDevice

| State | Meaning |
|---|---|
| (no device) | Not enrolled |
| `pending_approval` | A secret has been issued to a user who holds a role that requires a second factor, and no Administrator has approved the request. No code is accepted for it. Grants nothing, is not asked for at sign-in, and is void 72 hours after it was issued. |
| `pending_verification` | A secret has been issued, any approval it needed has been given, and no code from it has been accepted. Grants nothing and is not asked for at sign-in. Void 10 minutes after it was issued if it needed no approval, and 72 hours after the approval if it did. |
| `active` | A code proved possession of the secret. This is the account's second factor. It counts towards `MFA_VERIFIED` only if it is trusted. |

| From | To | Condition |
|---|---|---|
| (no device), or either pending state | `pending_approval` | The account gives its password again and holds a role that requires a second factor. A new secret replaces any pending one, and any approval is lost. |
| (no device), or either pending state | `pending_verification` | The account gives its password again and holds no such role. A new secret replaces any pending one. |
| `pending_approval` | `pending_verification` | An Administrator, acting at `MFA_VERIFIED` and not the device's own user, approves the request. The approval and the approver are recorded on the row. |
| `pending_approval` | `pending_verification` | The break-glass command approves the request: only for an Administrator's request made in an open recovery, and only when no Administrator who may approve it exists ([ADR-0017](adr/0017-account-recovery.md) point 63). The time of the approval is recorded on the row, and no approver. |
| `pending_approval` | (no device) | An Administrator rejects the request. The row and its secret are deleted. |
| `pending_verification` | `active` | A right code for the pending secret, within its lifetime |
| `active` | (no device) | The account gives its password and a current, unused code. The row and its secret are deleted. |
| `active` | `pending_approval` or `pending_verification` | Replacement: the account gives its password and a current, unused code. The row and its secret are deleted and a new secret is issued, by the two rules for a new enrolment above. No approval is carried over. |
| (no device) | `active`, trusted | Only for the first Administrator, by the bootstrap command, in the transaction that creates the account, after a right code was typed at the terminal |

A device is `active` if and only if it records when it was confirmed and the time step of an accepted code; a check constraint enforces this, and a unique constraint allows one device for a user.

### 4.10 User and AccountEvent

| Status | Meaning |
|---|---|
| `pending_verification` | Created by an Administrator. The email address has not been verified, the user has never been active, and cannot sign in. |
| `active` | Can sign in, according to roles and the second-factor policy |
| `disabled` | Disabled by an Administrator. Cannot sign in and holds no permission. Roles, second factor, and both times are kept. |

| From | To | Condition |
|---|---|---|
| (no user) | `pending_verification` | An Administrator, acting at `MFA_VERIFIED`, creates the user with one role. `account_created`, then `verification_sent` if the message was handed on. |
| (no user) | `active` | Only for the first Administrator, by the bootstrap command (ADR-0012, ADR-0014). The email address is not marked verified. |
| `pending_verification` | `active` | The current, unlapsed token and a password that passes validation. The address is marked verified, the token is removed. `verification_succeeded`. |
| `pending_verification` or `active` | `disabled` | An Administrator disables the user; never the last active Administrator. Any activation token and any password-reset token are removed. `account_disabled`. |
| `disabled` | `active` | An Administrator, not the user, enables a user that had been active. `account_enabled`. |
| `disabled` | `pending_verification` | An Administrator enables a user that had never been active. A new message is needed. `account_enabled`. |

AccountEvent types: `account_created`, `verification_sent`, `verification_succeeded`, `verification_failed`, `account_disabled`, `account_enabled`. Only `verification_failed` can be without a user. The four that an Administrator causes name that Administrator; the other two name no actor. Sending the verification message again changes no status and records `verification_sent`.

### 4.11 AuditEvent

Actions: `created`, `updated`, `deactivated`, `reactivated`, `marked_entered_in_error`. Target types: `registry.country`, `registry.language`, `registry.institution`, `registry.institution_name`. `created` and `updated` apply to every target type; `deactivated` and `reactivated` only to a country or a language; `marked_entered_in_error` only to an institution name. Fields of an AuditEventChange: `name_en`, `kind`, `country`, `parent`, `successor`, `valid_from`, `valid_to`. Each list is closed and is held by a database check; a later domain adds its target types with a migration that widens the check ([ADR-0018](adr/0018-registry-and-general-audit-record.md) point 31).

## 5. Conventions

- Internal primary keys are database-generated integers. Records that may be cited from outside the system (documents, versions, passages, claims, releases, search runs) also carry a stable public identifier that never changes.
- All timestamps are UTC.
- Indicator values are exact decimals.
- Enumerations that belong to the research codebook are tables. Enumerations that the code branches on (states, claim types) are fixed choices in code.
- Soft deletion is not used. Records are withdrawn through status events, with a reason.

### Stored text representation

| Layer | Representation | Permitted transformations |
|---|---|---|
| Artifact | Exact bytes as obtained | None |
| Segment text and Passage quote | Unicode text as produced by the parser, converted to Unicode Normalization Form C (NFC) | NFC only. No case folding, no compatibility folding, no transliteration, no whitespace collapsing, no removal of invisible or control characters. Such characters are kept and reported in the extraction's content flags. |
| RetrievalChunk search text | Derived | Any search-side transformation (case folding, compatibility folding, whitespace normalisation, stemming), recorded in the chunking configuration |

Offsets in Segments and Passages count Unicode code points in the NFC text. Quote verification compares text after the same search-side whitespace and compatibility normalisation is applied to both sides; it never changes stored text.

## 6. Integrity rules

Each rule is enforced in the service layer, by a database constraint where possible, and has a test.

| # | Rule |
|---|---|
| I-1 | Append-only records cannot be updated or deleted by application roles, except through the redaction procedure in §7 |
| I-2 | An artifact's stored bytes match its recorded hash |
| I-3 | A passage's quoted text equals the text at its offsets in its segment, and its hash matches |
| I-4 | Evidence has exactly one target |
| I-5 | A claim cannot be approved unless the evidence requirement for its type is met: `documented_fact`, `policy_objective`, and `implementation_evidence` need a supporting Passage; `observed_outcome` needs an Observation; `correlation` needs an AnalysisRun; `interpretation` needs at least one linked claim; `negative_finding` needs a SearchRun with outcome `no_qualifying_source_found` |
| I-6 | Evidence supporting an approved claim must be available (§4.3). If it becomes unavailable, the claim moves to `needs_reassessment`. |
| I-7 | RetrievalChunks are built only from Segments of the current extraction of `approved` document versions whose current rights permit the uses the retrieval pipeline makes of them |
| I-8 | An observation is unique per series, period, and release |
| I-9 | An AnswerCitation refers to a Passage whose Segment span, or an Observation, was a RetrievalHit in the same interaction |
| I-10 | A claim is approved by someone other than its author, unless recorded as self-review |
| I-11 | Evidence cannot be changed while a claim is `in_review` or after it is `approved`. Evidence that has been part of a submission is never deleted, only retired from a draft. Every ClaimReview keeps the text and evidence set it reviewed. |
| I-12 | A document version's fields do not change after creation |
| I-13 | Every PolicyEvent, PolicyObjective, and PolicyInstrument links to a Passage. A PolicyEvent's type is one of the five formal lifecycle types. |
| I-14 | Policy formal status is never stored; it is computed from PolicyEvents |
| I-15 | A Passage is never created to represent the absence of a source |
| I-16 | Embeddings reference RetrievalChunks only |

## 7. Redaction exception

Append-only is the rule. It has one exception, because some deletions are legally or ethically required and a rule that cannot be kept will be broken informally.

**Record classes that may be redacted**

| Class | Typical reason |
|---|---|
| AI interaction content: question text, raw model output, answer text | Retention policy; privacy request |
| Artifact bytes, and the Segment text, Passage quotes, and derived chunks of a document version | Copyright takedown; legal order |
| Personal data in user-linked records: the identity behind an actor reference | Account deletion; privacy request |

Nothing else may be redacted. Observations, claims, reviews, audit events, and redaction records themselves are outside the exception.

**Procedure**

1. Only an Administrator can perform it, through a dedicated service operation. It is not available through the Django admin or any general interface.
2. A basis must be recorded: the legal or privacy ground and a reference.
3. Content is removed. The record's identity, hashes, timestamps, and metadata remain as a tombstone, so that references to it still resolve and its former existence stays provable.
4. A RedactionRecord is written. It is never redacted.
5. Dependent records are handled by the normal rules: a redacted document version makes its evidence unavailable, so claims move to `needs_reassessment` (§4.3); derived chunks and embeddings are removed.
6. Scheduled retention of AI interaction content uses the same operation, with the retention policy as its basis.

The retention period and the rights policy that trigger these are undecided (blockers B19, B7).

## 8. Changes from the initial entity list

| Initial | In this model | Reason |
|---|---|---|
| Source | Source, plus Artifact and AcquisitionRecord | The channel, the bytes, and the act of obtaining them have different lifecycles |
| Document, DocumentVersion | Kept; language and translation kind on the version; review and rights as events | Translations are versions of the same work; history must not be mutated |
| — | Extraction, ExtractionSelection, Segment | A citation needs a stable address, and re-parsing must not break old citations |
| — | RetrievalChunk, ChunkEmbedding | Retrieval experiments must not alter extracted text |
| — | IngestionRequest, IngestionEvent | Job state must live in PostgreSQL, including failures that produce no artifact |
| Citation | **Passage** (the anchor) and **AnswerCitation** (a use of it in an AI answer) | "Citation" mixed a pointer into a text with an instance of citing. Formatted citations are derived output. |
| Evidence | Kept, with a target that is a Passage, an Observation, an AnalysisRun, or a SearchRun | Outcome claims are evidenced by data; negative findings by a recorded search |
| Policy | Kept, plus PolicyDocumentLink, PolicyEvent (formal events only), PolicyObjective, PolicyRelation | Objectives and formal events are coded from text; implementation goes through claims |
| PolicySector | Sector, shared and hierarchical | A taxonomy, not a property of policy alone |
| EconomicIndicator | Indicator, IndicatorSeries | Socioeconomic indicators are in scope; the same concept from two providers must not be merged |
| IndicatorObservation | Observation, tied to a DatasetRelease | Providers revise data; analysis must name the vintage it used |
| ResearchClaim | Kept, plus ClaimRelation, ClaimReview, AnalysisRun, SearchRun; `negative_finding` type added | Interpretation builds on other claims; review, analysis, and searches must be recorded |
| AIInteraction | Kept, plus InteractionStageRecord, RetrievalHit, AnswerStatement, AnswerCitation | Needed to audit and evaluate each stage without mutating the interaction |
| — | "AI-generated synthesis" and "uncertainty" are properties, not claim types | They are orthogonal to what kind of statement is made |

## 9. Open questions

1. How append-only is enforced at the database level: role privileges, triggers, or both. Decided for RoleEvent by the project owner on 2026-10-02 ([ADR-0012](adr/0012-authorization-and-role-event-integrity.md)): a trigger that refuses UPDATE and DELETE, created in the migration that creates the table (`accounts/0002_role_events`). Decided in the same form for AuditEvent and AuditEventChange by [ADR-0018](adr/0018-registry-and-general-audit-record.md) point 46 (`accounts/0009_audit_event`). Still open: whether every other later append-only table follows the same pattern, and the least-privilege database roles that must deny TRUNCATE and changes to the trigger, which wait for the deployment decision (ADR-0008).
2. Whether segments need a finer structural model for legal texts (article, part, clause) than a generic path. Depends on real documents (blocker B10).
3. How tables inside documents are represented.
4. Whether multi-country documents need more than a many-to-many link.
5. Period representation for non-annual data.
6. Retention period for AI interaction content (blocker B19).
7. Whether approved research claims may be offered to the assistant as evidence, and how answers relying on them would be labelled (blocker B24). Until decided, they are not.
8. Whether coded policy records (Policy, PolicyObjective, PolicyInstrument, PolicyEvent) need their own review status before being shown to readers (blocker B23).
