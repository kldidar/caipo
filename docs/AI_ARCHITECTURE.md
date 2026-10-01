# AI Architecture

Status: Draft for owner review · Last updated: 2026-10-01

Design of the evidence-grounded assistant. Not implemented. Provider and model choices are open ([ADR-0006](adr/0006-ai-provider-abstraction.md), [ADR-0003](adr/0003-vector-search.md)). Entity and state names are those of [DATA_MODEL.md](DATA_MODEL.md).

## 1. Goals and non-goals

### Goals

1. Answers consist only of statements that passed verification against retrieved, approved evidence.
2. It is structurally impossible for the system to display an invented reference.
3. Each statement carries a permitted label, is attributed to its source, and shows its uncertainty.
4. The system abstains when evidence is insufficient.
5. Every interaction can be audited afterwards.
6. Quality is measured per language, and changes are evaluated before release.

### Non-goals

- Answering from the model's general knowledge
- Tools, autonomous agents, or web browsing by the model
- Causal analysis or policy recommendations
- Correlation, interpretation, or negative-finding statements
- Suggesting policy codes or drafting research claims (out of scope until a separate safe design exists)
- Open-ended conversation unrelated to the corpus

## 2. Pipeline overview

```
question
  1. input guard
  2. query analysis
  3. retrieval
  4. evidence ranking
  5. evidence verification      ── insufficient → abstain
  6. synthesis
  7. citation verification      ── failing statements removed
  8. response assembly
  9. logging
```

The pipeline is a fixed sequence of ordinary functions. It is not an agent loop. Each stage has a typed input and output, is testable on its own, and writes an InteractionStageRecord.

Calls to models, all through the provider interface (§10):

| Stage | Call | Required |
|---|---|---|
| 2 | Generation, for query analysis | Optional |
| 3 | **Embedding of the query** | Yes, for vector search |
| 4 | **Reranking** | Optional |
| 6 | Generation, for synthesis | Yes |
| 7 | Generation, for the support check, one call per statement | Yes |

"The model has no tools" is the safety property. These network calls are made by the application, by design; nothing the model outputs can cause a call.

## 3. Query analysis

**Input guard.** Authentication as required by the access model, rate limit, budget check against PostgreSQL cost records, length limit. The question is untrusted text.

**Analysis produces a structured object:**

| Field | Purpose |
|---|---|
| Language of the question | Choose retrieval strategy and response language |
| Countries mentioned | Filter and balance retrieval |
| Period mentioned | Filter |
| Intent | Document lookup, policy comparison, indicator lookup, mixed, or out of scope |
| Causal framing | Whether the question asks about cause or effect |
| Search queries | One or more reformulations, including translations into corpus languages |

Rules:

- Out-of-scope questions get a fixed response without retrieval (outcome `refused`).
- A causally framed question is not refused. It is answered with what the evidence documents, and the response states that the project does not support causal conclusions ([LIMITATIONS.md](LIMITATIONS.md)).
- If analysis uses a model, its output is validated against a schema. On failure the pipeline falls back to using the raw question with no filters.
- Cross-language retrieval is an open problem: a question in one language must find passages in the others. Candidate approaches are query translation, multilingual embeddings, or both. The choice follows the retrieval spike (blocker B15).

## 4. Retrieval

Two evidence kinds, retrieved differently.

### 4.1 Text

- **Unit of retrieval:** the RetrievalChunk. Chunks are derived from Segments under a versioned chunking configuration. Segments are never changed.
- **Eligible set:** chunks built from Segments of the current extraction of document versions whose review status is `approved` and whose current rights permit transmission to an external AI provider, where an external provider is used (rule I-7).
- **Lexical search:** PostgreSQL full-text search plus trigram matching over the chunk's derived search text. PostgreSQL 18.6, the version pinned for development, provides `english` and `russian` text search configurations and none for Turkmen or Uzbek (verified 2026-10-02). For a corpus language without one, lexical search starts with unstemmed matching. The effect on recall is unknown and must be measured.
- **Vector search:** the query is embedded with the same model version as the ChunkEmbeddings and searched in pgvector. Model undecided.
- **Filters:** country, period, document type, language, applied from query analysis.
- Both retrievers return ranked candidates with scores. Each candidate is recorded as a RetrievalHit that names its Segment span, so the record survives chunk regeneration.

### 4.2 Indicator data

Numbers are never taken from the model or from free text when structured data exists. For indicator intents, the pipeline runs a structured query against Observations (indicator, country, period, latest non-withdrawn release unless specified) and passes the resulting rows as evidence with their own handles, including status flags and release identifiers.

Mapping a natural-language question to indicators is done by searching indicator names and definitions, not by letting the model write queries.

### 4.3 Chunking

- A ChunkingConfiguration defines how Segments are combined or split into chunks: long Segments are split with recorded offsets; short adjacent Segments may be combined. It also defines the search-side text transformations.
- Configurations are versioned files in the repository. Changing one regenerates chunks and embeddings and requires a retrieval evaluation run. It does not touch Segments, Passages, or any evidence.
- A chunk always maps back to exact Segment spans. That mapping is what turns a retrieved chunk into Passages.

## 5. Evidence ranking

1. **Fusion.** Lexical and vector rankings are combined with reciprocal rank fusion, which needs no score calibration.
2. **Reranking (optional).** A reranking call is added only if evaluation shows a gain worth its cost and latency.
3. **Diversity and balance.** Near-duplicates are collapsed (the same text in several versions or translations). For comparative questions, the selected set must include evidence for each country in the question, or the gap is noted.
4. **Preference rules, applied openly.** Original-language versions are preferred over translations of the same text. Source tier is attached as metadata and shown to the user. It is not used as a hidden score boost.
5. **Context budget.** The top candidates within a fixed token budget are selected. Each gets a short opaque handle valid for this request only.

## 6. Verification

Verification happens twice: on the evidence before synthesis, and on the answer after synthesis.

### 6.1 Evidence verification (before synthesis)

| Check | On failure |
|---|---|
| Each selected chunk's Segments belong to the current extraction of a version whose review status is `approved` (not `suspended`, `withdrawn`, or redacted) | Drop the chunk |
| The version's current rights permit transmission to the external provider in use | Drop the chunk |
| Segment text matches its stored hash | Drop; raise an integrity event |
| Each Observation belongs to a release that is not withdrawn | Drop |
| Enough relevant evidence exists | **Abstain** |
| For comparative questions, evidence exists for each country | Proceed, with the gap passed to synthesis as an explicit instruction to state it |

The sufficiency test starts as a simple rule on retrieval ranks, scores, and count, calibrated per language on the evaluation set. A model-based relevance check is added only if the simple rule proves inadequate.

Abstention returns a fixed-form response saying what was searched and that sufficient evidence was not retrieved. It makes no synthesis call. It is an evidence gap in this answer, not a research negative finding.

### 6.2 Citation verification (after synthesis)

Applied to the structured output of synthesis, statement by statement. A statement that fails a check is removed and the reason recorded.

| Check | Type |
|---|---|
| Output matches the required schema (on failure: retry once, then outcome `failed`) | Deterministic |
| Every handle was issued in this request | Deterministic |
| Every statement has at least one citation | Deterministic |
| The label is in the permitted set and allowed for the evidence kind (§7.3) | Deterministic |
| Every direct quote appears in the cited Segment span, compared after search-side whitespace and compatibility normalisation of both sides | Deterministic |
| Every numeric token passes the numeric check below | Deterministic |
| No links, images, or markup in statement text (stripped and logged) | Deterministic |
| No term from the prohibited causal-wording list | Deterministic |
| The cited evidence supports the statement, and the statement presents a source's assertion as that source's | Model-based |

If too few statements survive, the response becomes an abstention.

#### Numeric check

The purpose is to guarantee that no number appears in an answer unless it appears in that statement's cited evidence. It does not check that the number is attached to the right quantity; that is the support check's job.

1. **Tokens.** A numeric token is a maximal run of decimal digits, optionally containing group separators (space, no-break space, thin space, comma, full stop, apostrophe) and one decimal separator, optionally with a leading sign and a trailing percent sign. Digits from any Unicode script are mapped to ASCII digits first. Numbers written as words are not tokens and are not checked deterministically; the synthesis prompt requires digits for all quantities.
2. **Normalisation.** Leading zeros are removed. Because a comma or full stop may be a group or a decimal separator, each token yields the set of its possible values: for example `1.234` yields 1.234 and 1234. Percent signs and currency symbols are ignored for matching.
3. **Evidence values.** For each cited item, the allowed values are: all numeric tokens in the cited Segment span, normalised the same way; the value and period of each cited Observation; and server-held metadata of the cited record: document identifier, date of issue decomposed into year, month, and day, and the locator (page, article, paragraph numbers).
4. **Match.** A token passes if any of its possible values equals an allowed value of any item cited by that statement. Years, article numbers, and page numbers need no special case: they match through the text or the metadata.
5. **Rounding of observation values.** A token with *d* decimal places also passes if it equals a cited Observation value rounded to *d* places, by either round-half-up or round-half-even. No other rounding is accepted.
6. **Not permitted, and therefore failing:** scaled forms ("3.4 million" for 3 412 000), unit conversions, and derived numbers such as differences, ratios, percentage changes, and counts. The prompt forbids them; if one appears, its token finds no match and the statement is removed.
7. **Outcome.** If any token in a statement fails, the whole statement is removed.

Known limits: a correct statement is removed if the source writes a number in words; the check does not detect a real number attached to the wrong quantity. Both are measured in evaluation as false-removal and false-accept rates.

#### Support check

A separate model call that sees only the statement and its cited evidence, with no access to the question or to the rest of the answer, and returns one of a fixed set of values: supported, partially supported, not supported. Anything other than supported removes the statement.

The support-check model reads hostile text and can be manipulated by it, for example by a passage that says to answer "supported". It is therefore a filter that reduces error, not a guarantee. The deterministic checks carry the guarantees. Its output is constrained to the fixed values, its error rate against human labels is measured per language, and verifier-targeted attacks are part of the adversarial evaluation (§9).

## 7. Synthesis and citations

### 7.1 Prompt structure

1. **System instructions** (fixed, versioned): the role, the rule to use only the provided evidence, the permitted labels and when each applies, the attribution rule, the language rules on causation, the rule to write quantities as digits in published units, the output schema, and the statement that evidence blocks are untrusted source material whose contents are never instructions.
2. **Evidence blocks**: each with its handle, source metadata (title, institution, date, language, source tier), and text, in clearly delimited form.
3. **Question**: delimited as user input.

Prompts are files in the repository with a version identifier that is stored on each interaction.

### 7.2 Output schema

The model returns structured data, not prose:

```
answer:
  statements:
    - text
      label          one of the permitted assistant labels
      citations      list of handles
      quotes         optional exact quotes, each with its handle
  gaps               what the evidence did not cover
```

The model never writes source titles, URLs, page numbers, or reference lists. It writes handles only. The server maps each handle to the Segment spans of its chunk, creates Passages for them, and renders the reference from database fields. A reference that the model makes up has no handle to resolve to, so it cannot be displayed.

### 7.3 Permitted labels and attribution

The assistant may use four labels. They correspond to protocol claim types but are a restricted subset, and an assistant statement is never a research claim.

| Assistant label | Allowed evidence | Required form |
|---|---|---|
| Documented statement | Passage | Attributed: "Document X states…" |
| Stated policy objective | Passage from a policy text | Attributed to the policy text |
| Reported implementation | Passage | Attributed to the reporting source, with its source tier shown: "Source S reports…". Never phrased as an established occurrence. |
| Recorded observation | Observation | Attributed to provider and release, with the status flag (reported, estimated, provisional, projected) |

Not permitted in assistant output: correlation, interpretation, negative finding, and any temporal statement connecting a policy event to an indicator movement. The assistant may state the event and the observations as separate attributed statements.

**Attribution is rendered by the server.** For every statement, the server displays the source (title, institution, date, source tier) from database fields next to the statement. Attribution therefore does not depend on the model's wording. The prompt additionally requires reporting verbs, and the support check rejects statements that present a source's assertion as independently established.

Placing two attributed statements side by side, one per country, is permitted. An evaluative comparison between them is interpretation and is not.

### 7.4 Generation settings

Low temperature where the provider allows it, a fixed maximum output length, and no tools. Model identifiers and settings are repository-versioned and recorded per interaction.

## 8. Response

Only verified output is displayed. Nothing produced by the model reaches the user before stage 7 completes, and there is no streaming of model text. While the pipeline runs, the interface may show which stage is in progress.

The response contains:

- The surviving statements, each with its label, its server-rendered attribution, and its references
- For each reference: document title, institution, date, language, source tier, locator, and a link to the stored version. The quoted text is shown only if the version's rights permit display of excerpts.
- **Uncertainty flags** for each statement (below)
- Evidence gaps stated by the model and those detected by the pipeline
- A standing notice: this is an AI-generated synthesis of the cited sources; it may be incomplete; it does not establish causation
- For abstentions: what was searched

All text is rendered escaped. References link only to internal records.

### Uncertainty

The assistant does not report a self-assessed confidence, because a model's stated confidence is not reliable evidence. Uncertainty is represented by flags that the server derives from the evidence, per statement:

| Flag | Condition |
|---|---|
| `single_source` | All citations come from one document |
| `non_primary_source` | No citation is from a tier A source |
| `self_reported` | A reported-implementation statement whose sources are official sources reporting on their own government |
| `translation_source` | A cited version is a translation, not the original |
| `cross_language` | The statement's language differs from the language of a cited Segment |
| `estimated_value`, `provisional_value`, `projected_value` | A cited Observation has that status |
| `low_extraction_quality` | A cited Segment's extraction has a quality warning |
| `language_not_evaluated` | Verification quality has not been measured for the cited Segment's language |

Flags are shown in plain words next to the statement.

### Cross-language statements

When a statement is written in a language different from that of a cited Segment, it is an AI translation or paraphrase. It carries the `cross_language` flag, is labelled "AI translation or paraphrase of a source in [language]", and is shown with the original passage where rights permit.

### Latency

One answer requires several sequential model calls, and the support check adds one call per statement. Support checks run concurrently, but total time may exceed web request and proxy timeouts. Each request has an overall deadline, held in repository configuration; on expiry the outcome is `timed_out` and the user gets an explicit message. Latency is measured in Phase 5. If it does not fit a web request, the pipeline moves to a background job and the page polls for the verified result (see ADR-0004).

Interactions are single-turn at first. Multi-turn conversation adds injection and context-management risk and is deferred until the single-turn pipeline is evaluated.

## 9. Evaluation

Nothing about the pipeline is assumed to work until measured. No target numbers are set in this document, because none have been measured; thresholds are set from the first baseline (blocker B16).

### 9.1 Corpora and where evaluation runs

| Corpus | Contents | Location | Used for |
|---|---|---|---|
| **Synthetic fixture corpus** | Small, fully synthetic documents and datasets written for the project, including adversarial documents. No copyrighted material. | Committed to the repository | CI |
| **Evaluation corpus** | A frozen snapshot of approved production document versions, identified by a manifest of hashes | Manifest in the repository; the documents themselves are not committed | Evaluation environment |
| **Adversarial corpus** | Synthetic hostile documents | Committed to the repository | Loaded only into an evaluation database, never into production |

The **evaluation environment** is a separate database with the same schema, on a development or staging machine that has access to the artifact store. It is not a new service. Adversarial and synthetic documents are marked approved there by the evaluation setup; rule I-7 governs production and is not weakened.

CI cannot hold the production corpus, because much of it may be copyrighted. CI therefore runs only against the synthetic fixture corpus with a deterministic fake provider and fake embeddings.

### 9.2 Gold dataset

Built and owned by the researcher (owner to be assigned, blocker B16). Versioned in the repository. Cases refer to artifacts by hash and to Segments by locator. Gold files contain questions, references, and researcher-written reference points; they contain no copyrighted document text.

| Case type | Contains | Measures |
|---|---|---|
| Answerable factual | Question, relevant Segments, reference answer points | Retrieval, faithfulness, relevance |
| Comparative | Question, relevant Segments per country | Balance, coverage |
| Indicator | Question, expected Observations | Structured lookup, numeric check |
| Unanswerable | Question with no supporting evidence in the corpus | Abstention |
| Causal bait | Question inviting a causal claim | Compliance with language rules |
| Attribution | Evidence from non-primary sources asserting implementation | Correct label and attribution |
| Cross-language | Question in one language, evidence in another | Cross-language retrieval and verification |
| Adversarial: answer model | Documents with injected instructions | Security robustness |
| Adversarial: verifier | Passages instructing the support check to answer "supported" for an unsupported statement | Verifier robustness |

### 9.3 Language-specific requirements

1. Every metric is reported separately for each corpus language (Turkmen, Uzbek in each script, Russian, English) and for each pair of question language and evidence language. An aggregate figure alone is never reported.
2. Each corpus language needs gold cases of each case type as far as the corpus allows. Where a language has too few cases for a metric, the result is reported as "not measured" for that language.
3. Support-check agreement with human labels is measured per evidence language, and separately for cross-language statements.
4. Human labelling for a language is done by someone who reads that language. Where no such labeller is available, the language is recorded as not evaluated.
5. Until a language has a measured baseline, statements citing Segments in it carry the `language_not_evaluated` flag.

### 9.4 Metrics

| Dimension | Metric | How computed |
|---|---|---|
| Retrieval quality | Recall at k, mean reciprocal rank, nDCG, per language and per retriever | Against gold Segments. Deterministic. |
| Citation correctness | Citation precision: share of citations that support their statement. Citation recall: share of statements fully supported by their citations. | Human labels on a sample; model judge on the rest |
| Faithfulness | Share of statements supported by the cited evidence | As above |
| Hallucination rate | Share of statements in final responses not supported by any cited evidence; also measured before verification, to see what verification catches | As above |
| Answer relevance | Whether the answer addresses the question; coverage of reference answer points | Human labels and model judge |
| Abstention | Rate of abstaining on unanswerable cases and of wrongly abstaining on answerable ones | Deterministic |
| Attribution and labels | Share of statements with a permitted, correct label; share of source assertions correctly attributed | Human labels |
| Causal compliance | Share of causal-bait cases with no prohibited causal statement | Pattern check plus human review |
| Numeric check | False-removal and false-accept rates | Human-labelled sample |
| Security robustness | Attack success rate against the answer model: share of adversarial cases where injected content changed behaviour (followed an instruction, emitted a planted string, produced markup or links, cited outside the retrieved set) | Deterministic checks for planted markers |
| Verifier robustness | Attack success rate against the support check: share of verifier-adversarial cases where an unsupported statement was returned as supported | Deterministic, from known labels |
| Verifier quality | Agreement of the support check with human labels; false-accept and false-reject rates, per language | Human-labelled sample |
| Cost and latency | Tokens, cost, time per stage, and share of requests exceeding the deadline | From stage records |

### 9.5 Model-based judging

Where a model judges output, the judge prompt is versioned, the judge is validated against human labels with agreement reported per language, and results are shown with that agreement. A judge that has not been validated is not used for a release decision.

### 9.6 Levels

| Level | Content | Corpus | Runs in | When |
|---|---|---|---|---|
| Unit | Deterministic verification checks, numeric check, handle resolution, schema validation, with a fake provider and fake embeddings | Synthetic fixture | CI | Every commit |
| Retrieval regression | Retrieval metrics on the gold set. No generation calls. Query embedding calls are made, and are external calls if the embedding model is hosted. | Evaluation corpus | Evaluation environment | Every change to chunking, retrieval, or embeddings |
| Full | All metrics with real model calls | Evaluation and adversarial corpora | Evaluation environment | Before any release that changes prompts, models, chunking, retrieval, or verification |

Each run is stored with dataset version, corpus manifest identifier, pipeline version, chunking configuration version, prompt versions, model identifiers, and results. A change that makes a tracked metric worse than the agreed threshold does not ship without a recorded decision.

### 9.7 Limits of evaluation

The gold set is small and built by few people. Results indicate, they do not guarantee. Human-labelled samples carry their own disagreement. This is reported with the results.

## 10. Provider abstraction

A small internal interface with three operations: generate structured output, embed texts, and (optionally) rerank. Each implementation records provider and exact model identifier.

- Application code depends on the interface, never on a vendor SDK. Vendor SDKs are used inside provider implementations, and their network calls to the provider are part of the design.
- A deterministic fake implementation is used in tests.
- Model identifiers and generation settings affect results, so they live in repository-versioned settings, not in environment variables. The environment holds only secrets and endpoints.
- No orchestration framework is used. The pipeline is short and fixed, and every prompt must be visible in the repository.

Selection criteria for the provider and models (blocker B14): quality on the evaluation set in all corpus languages, support for structured output, data-handling terms (no training on submitted content; retention), cost, and stability of model versions. Whether generation or embedding models can run on local hardware has not been assessed; the recorded hardware is in [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §9.

## 11. Logging and privacy

Each interaction stores: question, analysis, retrieval hits with scores, selected evidence, prompt versions, model identifiers and settings, chunking configuration version, raw output, verification results per statement, final response, timings, tokens, and cost.

Questions may reveal a user's research interests. Retention, access, and user notice are an open decision (blocker B19); retention is applied through the redaction procedure in DATA_MODEL.md §7. Application logs record identifiers and outcomes, not question text.

## 12. Open questions

1. Provider and model selection (B14).
2. Embedding model and whether it runs locally or as a service; local feasibility not yet assessed (B14).
3. Cross-language retrieval strategy and lexical search quality per language (B15).
4. Whether a reranker is worth its cost.
5. Whether approved research claims are offered to the assistant as evidence, and how answers that rely on them are labelled (B24). Until decided and ratified, they are not.
6. Sending document text to an external provider: the rights policy that determines which documents permit it (B7).
7. Whether the pipeline fits a web request or must run as a background job (measured in Phase 5).
