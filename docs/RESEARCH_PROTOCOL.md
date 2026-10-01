# Research Protocol

Status: Draft for researcher review · Last updated: 2026-10-01

Research title: **"AI Policy and Economic Transformation in Central Asia: A Comparative Analysis of Turkmenistan and Uzbekistan"**

This protocol defines how research is conducted in CAIPO. The software enforces parts of it; the rest is researcher discipline. It was drafted during the architecture phase by the engineering side. **Sections marked DRAFT or OPEN contain proposals or undecided points that the responsible researcher must confirm, replace, or decide.** Nothing in this document is a research finding.

## 1. Principles

1. Every important claim is traceable to evidence held in the system.
2. Different kinds of statements are kept distinct and labelled.
3. Uncertainty and missing information are stated, not smoothed over.
4. Sources are preserved as found, with provenance.
5. No statistic, source, quotation, or conclusion is invented, by a person or by AI.
6. Causal language is used only when the method supports it. Under the current design it does not (see §8).
7. Methods and data are recorded so that another researcher can check the work.

## 2. Research questions (DRAFT)

The questions below are proposals consistent with the research title. They are descriptive and comparative by design. Their wording depends on two definitions that are still open (§3), and they must be revised once those are settled.

- **RQ1.** What policies within the project's policy domain have Turkmenistan and Uzbekistan formally adopted, and how do they compare in objectives, instruments, responsible institutions, and target sectors?
- **RQ2.** What documented evidence exists that these policies have been implemented, and how does that evidence differ in availability and kind between the two countries?
- **RQ3.** How have the indicators chosen to represent economic transformation developed in each country over the study period, and how do the trajectories compare, given differences in data availability and quality?
- **RQ4.** What temporal associations, if any, can be observed between formal policy events and indicator trajectories, and what alternative explanations exist for them?

RQ4 is exploratory. It can produce observations of association and a structured list of rival explanations. It cannot produce an estimate of policy effect.

## 3. Scope, definitions, and study period

- **Countries:** Turkmenistan and Uzbekistan.
- **Languages:** Turkmen, Uzbek (Latin and Cyrillic scripts), Russian, English.

### 3.1 Policy domain (OPEN, blocker B22)

"AI policy" has no boundary yet in this project. The researcher must define it, and in particular decide whether broader digital-economy, data, telecommunications, and education policies are inside it. Until this is decided, "the project's policy domain" in RQ1 has no fixed meaning, and no document is included or excluded on domain grounds.

### 3.2 Economic transformation (OPEN, blocker B22)

"Economic transformation" is the title's second central concept and is not yet defined. The researcher must state what it means for this study and how it is represented by measurable indicators. Until then, no indicator is selected (§7), RQ3 has no fixed content, and the system makes no statement about whether transformation has occurred.

### 3.3 Study period (OPEN, blocker B8)

To be set by the researcher, with a stated reason for the start year.

## 4. Sources

### 4.1 Source types and source tiers

A source tier describes the source's relationship to what it reports. It is a neutral category, not a judgement of quality or truthfulness, and the letters do not form a ranking of reliability.

| Tier | Type | Typical use |
|---|---|---|
| A | Official primary legal or policy text published by the issuing authority | What a policy says |
| B | Official secondary material: government reports, statistics, press releases | Stated objectives; reported implementation |
| C | Intergovernmental and multilateral organisations | Indicators; assessments |
| D | Peer-reviewed research | Analysis and interpretation |
| E | Independent research institutes and think tanks | Analysis; implementation evidence |
| F | News media | Events; implementation evidence, with caution |
| G | Other | Case by case |

Rules:

- What a policy says is established from tier A wherever a tier A text exists. If only a secondary account exists, the claim says so.
- An official statement that something was implemented is evidence that the statement was made. It is weaker evidence that implementation occurred. Claims record this distinction (§5).
- The independence of each source from the government it reports on is recorded where known, because it bears on implementation claims.

### 4.2 Inclusion criteria (DRAFT)

A document is included if it is within the policy domain and study period, its origin can be identified, and it can be stored lawfully. Exclusions and their reasons are recorded. The seed source list is an open item (blocker B9) and must be supplied and verified by the researcher. No source list is proposed here, because none has been verified.

### 4.3 Acquisition and preservation

- Each document is captured at acquisition: exact bytes, content hash, and the acquisition record.
- **Fetched** documents record the URL, time, and response details observed by the system.
- **Uploaded** documents record the origin the uploader claims. That origin is marked as attested, not verified, until a system fetch from the claimed location yields the identical file. Readers see which it is.
- Online sources may change or disappear. The captured copy, not the live URL, is the reference.
- A changed document is a new version. Old versions are kept.
- Where a document cannot lawfully be stored, displayed, or sent to an external service, the system records the restriction and applies it.

### 4.4 Language and translation

- The original-language version is authoritative for what a document says.
- Each version records whether it is an original, an official translation, or an unofficial translation.
- Machine translation may be used as a reading aid. It is labelled, it is never cited as the source text, and it never replaces the original.
- A quotation is given in the original language. A translation may accompany it and is marked with its translator or method.
- When the AI assistant writes a statement in a language different from its source passage, the statement is an AI translation or paraphrase. It is labelled as such and shown with the original passage.
- Names of institutions and documents are stored in the original script, with transliteration and English rendering as additional fields.

## 5. Epistemic taxonomy

Every claim has exactly one type. The type determines what evidence is required before the claim can be approved.

| Type | Meaning | Minimum evidence | Example of form (synthetic) |
|---|---|---|---|
| **Documented fact** | Something a source directly states or shows | At least one Passage that directly states it | "Document X, article N, states Y." |
| **Policy objective** | A goal a policy document declares | The Passage in the policy text stating the goal | "Strategy X sets the target of Y by year Z." |
| **Implementation evidence** | A source's report that a policy measure was or was not carried out, including funding, milestones, and progress | A Passage from the reporting source, with that source's tier and independence recorded | "Source S reports that institution I was established on date D." |
| **Observed outcome** | A measured value or change in an indicator | Observations from an identified provider and release | "Indicator K was V in year T according to provider P, release R." |
| **Correlation** | A stated association between measured things, including a temporal association between a formal policy event and an indicator | A recorded analysis: inputs, period, method, result | "Over period T, series A and series B moved together (method M)." |
| **Interpretation** | The researcher's reasoning about what facts mean | Links to the claims it builds on, and stated alternatives | "This pattern is consistent with explanation E; it is also consistent with F." |
| **Negative finding** | A recorded search found no qualifying source | A SearchRun with outcome "no qualifying source found" | "No qualifying source reporting X was found in sources S1–S3 as of date D (search run R)." |

Three further properties apply to every claim and are separate from its type:

- **Origin:** written by a person, or written by a person who declares AI assistance in drafting. Assistant answers shown to users are a separate category, *AI-generated synthesis*, which is never stored as a research claim.
- **Confidence:** high, moderate, or low, with a written reason. Confidence reflects source quality, corroboration, and directness. It is the explicit statement of uncertainty for a claim.
- **Status:** the claim states defined in [DATA_MODEL.md](DATA_MODEL.md) §4.3.

There is deliberately no "causal effect" claim type. Adding one requires an amendment to this protocol and a new ADR describing the research design that justifies it.

### Rules that prevent category errors

1. A policy objective is not evidence of implementation.
2. Implementation evidence is not evidence of outcome.
3. An observed outcome is not attributed to a policy within an observed outcome claim.
4. A correlation claim states the association and its method only. Any reading of it is a separate interpretation claim.
5. An interpretation must be phrased as interpretation and must name at least one alternative explanation, or state why none was identified.
6. An unsupported inference is never recorded or displayed as a documented fact.
7. Implementation is recorded only as implementation evidence claims. It is never recorded as a formal policy event (§6).
8. A statement restating what a source asserts is attributed to that source. It is not presented as independently established.

### Negative findings

"No source was found" is a legitimate result, and it is recorded as what it is.

- A negative finding is evidenced by a **SearchRun**: the query, the date and time, the source universe, the inclusion and exclusion criteria, the sources actually examined, the search method, and the outcome.
- Its wording is always bounded by the search: "no qualifying source was found in [universe] as of [date]". It never says that something does not exist or did not happen.
- A negative finding is never recorded by creating a document or passage that says nothing was found.
- A negative finding becomes outdated as sources change. Its date is always shown.
- The assistant failing to retrieve evidence is not a negative finding. It is reported as an evidence gap in that answer and nothing more.

### Temporal statements about policy events and indicators

A sentence that places a policy event and an indicator movement in sequence, such as "after the adoption of X, indicator K rose", is a **correlation** claim. It is evidenced by an AnalysisRun whose method is a temporal comparison. It is acceptable only if all of the following hold, each of which is checked:

1. The event is a recorded formal PolicyEvent with its date and Passage.
2. Every indicator value comes from named Observations with provider, release, and status flags.
3. The periods compared are stated explicitly.
4. The number of observations on each side of the event is stated.
5. The wording uses only temporal connectives (after, following, before, during, in the same period) and none of the prohibited causal terms in §8.
6. The claim is displayed with the standard notice that temporal sequence does not establish causation.

Stating the event and the indicator values as two separate claims, with no connecting sentence, needs no analysis run: they are a documented fact and an observed outcome.

## 6. Policy coding

Policies are coded from documents into structured records: objectives, instruments, sectors, institutions, and formal lifecycle events.

- **Formal lifecycle events only.** A PolicyEvent is one of: adopted, amended, entered into force, expired, repealed. Each must be established by a passage in a formal text. Policy status is derived from these events and from nothing else.
- **Implementation is not coded as a policy event.** Funding, reported milestones, progress, and announcements of implementation are implementation evidence claims (§5), each with its source, source tier, independence, confidence, and review.
- A **codebook** defines each category and gives coding rules. It does not exist yet (blocker B11). The instrument typology and sector taxonomy must be chosen by the researcher, preferably adapted from an established scheme so results are comparable with other work.
- Every coded value links to the passage it was coded from.
- The codebook is versioned. Each coded record stores the codebook version used.
- Where two coders are available, a sample is coded independently and agreement is reported. Where only one coder is available, this is stated as a limitation and a re-coding check after a time interval is used instead.
- Whether coded policy records need their own review step before readers see them is undecided (blocker B23).
- AI-suggested policy coding is out of scope (§10).

## 7. Indicators

- Indicators are selected by the researcher to represent economic transformation as defined in §3.2, with a recorded reason for each (blocker B12). No indicator list is proposed here, and none can be until that definition exists.
- Each indicator has a definition, unit, provider, and methodological notes.
- Data is imported as a dated **release**. Later revisions are imported as new releases. Analysis records which release it used.
- Values are stored exactly as published. Flags record whether a value is reported, estimated, provisional, or projected.
- Missing values stay missing. No interpolation or imputation is stored as data. If an analysis uses a derived series, the derivation is part of the recorded analysis, not of the data.
- When providers disagree, both series are kept and the disagreement is recorded.
- Conversions (currency, constant prices, per capita) record the method and the conversion series used.

## 8. Comparison and inference

### What the design supports

A structured, focused comparison of two cases: the same questions asked of both countries, answered from documented evidence, with differences in evidence availability made explicit.

### What the design does not support

Causal inference about the effect of AI policy on economic outcomes. With two cases and no identified counterfactual, the design cannot separate the effect of a policy from everything else that differs or changes. The reasoning is set out in [LIMITATIONS.md](LIMITATIONS.md).

### Language rules

These apply to claims, reports, interface text, and assistant output. The prohibited terms are kept as a versioned list in the repository for each interface language, so the rule can be tested.

| Permitted | Not permitted |
|---|---|
| "After the adoption of X, indicator K rose", as a correlation claim meeting the criteria in §5 | "X led to a rise in K" |
| "is consistent with" | "demonstrates", "proves", "resulted in", "due to" |
| "The document states the aim of…" | "The policy achieved…" without implementation and outcome evidence |
| "No qualifying source was found in … as of …" (negative finding with a SearchRun) | "There is no…", "X did not happen" |
| "Source S reports that…" | Restating a source's assertion as established fact |

### Correlation analysis

Any quantitative association is run as a recorded analysis: inputs with release identifiers, method, parameters, code version, and output. With short annual series the number of observations is small; this is reported next to every result, and results are described as exploratory.

## 9. Review workflow

1. **Draft.** A researcher writes a claim, assigns its type and confidence, and links evidence.
2. **Automatic checks.** The system verifies that the evidence requirements for the type are met and that every evidence target resolves.
3. **Review.** A reviewer other than the author checks that the evidence supports the claim as worded, that the type is correct, and that the language rules are met. Evidence is frozen from this point.
4. **Approval or return.** Approved claims become visible to readers. Whether the assistant may use approved claims as evidence is undecided (blocker B24); until it is decided and its safety design ratified, the assistant does not use them.
5. **Dispute and withdrawal.** Approved claims can be marked disputed or withdrawn with a reason. They are not deleted.
6. **Reassessment.** If evidence behind an approved claim is suspended, withdrawn, redacted, or invalidated, the claim is automatically marked as needing reassessment and is no longer presented as approved until a reviewer re-approves, supersedes, or withdraws it. Its history is preserved. See [DATA_MODEL.md](DATA_MODEL.md) §4.3.

If the project has a single researcher, independent review is not possible. In that case the approval step is recorded as self-review, labelled as such to readers, and noted as a limitation (blocker B13).

## 10. Use of AI in the research

| Use | Allowed | Condition |
|---|---|---|
| Finding relevant passages | Yes | Results are retrieval hits, not findings |
| Summarising retrieved evidence for a reader | Yes | Labelled AI-generated synthesis, attributed to its sources, with verified citations |
| Translation or cross-language paraphrase as a reading aid | Yes | Labelled; shown with the original; never cited as source text |
| Suggesting policy codes | **Out of scope** | Deferred until a separate safe design exists and is ratified |
| Drafting research claims inside the system | **Out of scope** | Same |
| Supplying facts from the model's own knowledge | No | |
| Generating citations | No | References are created only from retrieved, stored passages and observations |
| Producing correlation, interpretation, or negative-finding statements | No | These require a recorded analysis, a researcher's reasoning, or a recorded search |
| Approving claims | No | |
| Drawing causal conclusions | No | |

A researcher who uses any AI tool while drafting a claim declares it in the claim's origin. AI assistance in a published output is disclosed.

## 11. Ethics and legal considerations

- The project uses published documents and aggregate statistics. It is not designed to collect personal data about individuals other than its own users.
- Named officials appear only in their official capacity as stated in public documents.
- Copyright and terms of use of each source are respected (blocker B7). Each document version carries recorded rights that control storage, display, redistribution, and transmission to an external AI provider.
- Fetching respects site terms and reasonable rate limits.
- The researcher confirms whether institutional ethics review applies (blocker B20).
- The subject matter may be politically sensitive. Wording stays descriptive and evidence-bound.
- Where the law or a privacy obligation requires content to be removed, it is removed through the recorded redaction procedure in [DATA_MODEL.md](DATA_MODEL.md) §7. Dependent claims are reassessed, not silently kept.

## 12. Changes to this protocol

The protocol is versioned in the repository. Changes that affect how claims are typed, evidenced, or reviewed are recorded with a date and reason, and existing claims are re-checked against the new rules where relevant.
