# ADR-0005: Evidence and provenance model

- Status: Accepted
- Date: 2026-10-02

## Context

The project's central requirement is that every important claim is traceable to evidence, that sources keep their provenance, and that different kinds of statements are never confused. This must hold in the data model, not just in guidelines, because guidelines erode.

## Decision

Twelve principles. The entities that realise them are in [DATA_MODEL.md](../DATA_MODEL.md).

1. **Three levels for documents.** The work (Document), a specific text (DocumentVersion), and the stored bytes (Artifact, addressed by SHA-256). Each successful act of obtaining the bytes is an AcquisitionRecord linked to the Artifact, and it distinguishes an origin the system observed from one an uploader attests.
2. **Extraction is versioned.** Running a parser on a version produces an Extraction with Segments. A new parser version produces a new extraction and does not alter the old one. Which extraction is current is recorded as an event, not by modifying an extraction.
3. **Segments are not retrieval units.** A Segment is immutable extracted text. A RetrievalChunk is derived from one or more Segments under a versioned chunking configuration and can be regenerated without touching Segments. Embeddings belong to RetrievalChunks.
4. **Evidence points to exact spans.** A Passage is a pointer to a character range in one Segment, storing the quoted text and its hash. It remains verifiable against the stored extracted text for as long as that text is retained. It is not a guarantee about the artifact bytes beyond what the recorded parser produced from them.
5. **Evidence has typed targets.** A claim's evidence is a Passage, an Observation, an AnalysisRun, or a SearchRun, through explicit foreign keys with a constraint that exactly one is set. No generic foreign keys.
6. **Claims carry one epistemic type.** Documented fact, policy objective, implementation evidence, observed outcome, correlation, interpretation, negative finding. Origin, confidence, and status are separate properties. There is no causal-effect type.
7. **Negative findings are evidenced by a recorded search.** A SearchRun records the query, time, source universe, inclusion and exclusion criteria, sources examined, method, outcome, and relevant configuration. "No qualifying source was found" is never represented as a document or a Passage.
8. **Policy events are formal lifecycle events only.** A PolicyEvent is adopted, amended, entered into force, expired, or repealed, each established by a Passage in a formal text. Policy status is derived from these events and stored nowhere else. Implementation information is recorded as claims of type implementation evidence, never as a policy event.
9. **Evidence requirements are enforced per type** before approval, in the service layer and with tests. Evidence cannot be changed while a claim is in review, or after it is approved.
10. **Review history is never lost.** Every submission for review records the exact claim text and evidence set that was reviewed, together with the decision. A claim returned by a reviewer goes back to draft and can be edited again, but the returned submission, its evidence set, and the reviewer's decision stay on record. Evidence that has been part of a submission is never deleted or altered; it can only be retired from the current draft, and a retired evidence item stays on record with every submission it belonged to. An approved claim never goes back to draft: it is revised by a new claim that supersedes it, and the approved record remains. No approved or returned record silently disappears.
11. **Approved research is not silently invalidated.** If evidence behind an approved claim becomes unavailable (its document version suspended, withdrawn, or redacted; its release withdrawn; its analysis or search run invalidated), the claim moves automatically to a needs-reassessment status, is no longer presented as approved, and keeps its full history until a reviewer re-approves, supersedes, or withdraws it.
12. **Provenance is append-only, with one controlled exception.** Provenance records are never updated or deleted by the application, except through a recorded redaction procedure limited to named record classes where removal is legally or privacy-required. Redaction is performed only by an Administrator, requires a recorded basis, leaves a tombstone, and writes a RedactionRecord that is itself never redacted. Enforcement is in code and at the database level.

Indicator data follows the same idea: observations belong to a dataset release, and revisions are new releases.

There is no stored `Citation` entity. A formatted citation is rendered from a Passage or Observation and its metadata. In AI answers, an AnswerCitation records that a statement cited a Passage or an Observation.

## Alternatives considered

- **Cite documents rather than spans.** Simpler, but a claim could not be checked without rereading the whole document, and AI citations could not be verified automatically.
- **Mutable records with a history library.** History becomes a side feature that can be bypassed. Making provenance append-only by construction is simpler to reason about.
- **Absolute append-only with no exception.** Cannot be kept when the law or a privacy obligation requires removal, and a rule that will be broken informally is worse than a narrow recorded exception.
- **A single free-text claim with tags.** Does not allow enforcement of evidence requirements.
- **Generic relations for evidence targets.** Fewer columns, but no referential integrity on the most important link in the system.
- **Recording implementation as policy events.** Would store reported implementation without source tier, independence, confidence, or review, bypassing the taxonomy.
- **Using Segments directly as retrieval chunks.** Would force a new extraction for every chunking experiment or allow retrieval tuning to alter evidence text.
- **Recording a negative finding as a note or a placeholder document.** A placeholder is a fabricated source. A note cannot be checked or repeated.
- **Including a causal claim type with strict gating.** The research design does not support causal claims, and the absence of the type makes misuse harder than a gate would.

## Consequences

- More tables and more rows than a simple design.
- Corrections require new records and status events, which is more work than editing.
- Researchers must select passages rather than cite loosely, and must record searches to claim absence. This is intended.
- Storage grows with every extraction and release. At this scale it is immaterial.
- Passages duplicate a small amount of text.
- Redaction removes content that later checks would need. The tombstone and RedactionRecord preserve the fact and reason.

## Outside the scope of this ADR

This ADR decides the twelve principles above and nothing else. Three neighbouring matters are deliberately not part of it and do not affect it:

1. The database technique used to enforce append-only tables (privileges, triggers, or both). It is an implementation choice made with the first provenance migration ([DATA_MODEL.md](../DATA_MODEL.md) §9).
2. A review status for coded policy records. Tracked separately as blocker B23.
3. Use of approved claims by the assistant. Tracked separately as blocker B24.

## Amendment history

- 2026-10-02: Before ratification, principle 9 was narrowed and principle 10 added, on the project owner's decision. The earlier wording froze evidence once a claim left draft, which left a returned claim uncorrectable.

## Revisit when

The research protocol is amended to support a new kind of claim, or real documents show that span-based anchoring does not work for an important document class (for example, scanned tables).
