# Data Model

Status: Draft for owner and researcher review · Last updated: 2026-10-01

This is a conceptual domain model. Field lists name what must be captured; exact columns, types, and indexes are settled during implementation and reviewed with each migration. Decision record: [ADR-0005](adr/0005-evidence-and-provenance-model.md) (Proposed).

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

**User**, roles, and permissions. Roles are Reader, Researcher, Reviewer, Administrator.

**AuditEvent** (A-O). Actor, action, object reference by type and public identifier (not a foreign key, because targets live in higher layers), time, details.

**RedactionRecord** (A-O, never itself redacted). Records each use of the redaction exception: actor, time, legal or privacy basis, record class, target identifier, what was removed. See §7.

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

**RightsDetermination** (A-O). A recorded decision on what may be done with a document version: store, display in full, display excerpts, redistribute, transmit to an external AI provider. Actor, time, basis. The current rights are those of the latest determination. With no determination, every right except storage for review is denied.

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
- Editable while the claim is a draft. **Frozen** (append-only) once the claim leaves draft.

**ClaimRelation.** Typed link between claims: builds on, contradicts, alternative to.

**ClaimReview** (A-O). A review decision: reviewer, decision, comment, time, and whether it was self-review.

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
| `draft` | Being written. Evidence editable. |
| `in_review` | Submitted. Evidence frozen. |
| `approved` | Passed review. Text and evidence frozen. |
| `needs_reassessment` | Was approved; one or more of its supporting evidence items has become unavailable. Set automatically. |
| `disputed` | Approved but challenged, with a recorded reason |
| `withdrawn` | No longer asserted, with a recorded reason. The record remains. |

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
| I-11 | Evidence on a claim that has left `draft` cannot be changed or removed |
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

1. How append-only is enforced at the database level: role privileges, triggers, or both. To be decided with the first provenance migration.
2. Whether segments need a finer structural model for legal texts (article, part, clause) than a generic path. Depends on real documents (blocker B10).
3. How tables inside documents are represented.
4. Whether multi-country documents need more than a many-to-many link.
5. Period representation for non-annual data.
6. Retention period for AI interaction content (blocker B19).
7. Whether approved research claims may be offered to the assistant as evidence, and how answers relying on them would be labelled (blocker B24). Until decided, they are not.
8. Whether coded policy records (Policy, PolicyObjective, PolicyInstrument, PolicyEvent) need their own review status before being shown to readers (blocker B23).
