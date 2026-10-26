# Research Protocol

Status: Draft for researcher review · Last updated: 2026-10-26

Research title: **"AI Policy and Economic Transformation in Central Asia: A Comparative Analysis of Turkmenistan and Uzbekistan"**

This protocol defines how research is conducted in CAIPO. The software enforces parts of it; the rest is researcher discipline. It was drafted during the architecture phase by the engineering side. **Sections marked DRAFT or OPEN contain proposals or undecided points that the responsible researcher must confirm, replace, or decide.** Text marked APPROVED records a decision of the project owner (§3). Text marked PROVISIONAL records a default that the project owner approved for preparing and running the pilot only (§3.7). It decides nothing for the study. Nothing in this document is a research finding.

## 1. Principles

1. Every important claim is traceable to evidence held in the system.
2. Different kinds of statements are kept distinct and labelled.
3. Uncertainty and missing information are stated, not smoothed over.
4. Sources are preserved as found, with provenance.
5. No statistic, source, quotation, or conclusion is invented, by a person or by AI.
6. Causal language is used only when the method supports it. Under the current design it does not (see §8).
7. Methods and data are recorded so that another researcher can check the work.

## 2. Research questions (DRAFT)

The questions below are proposals consistent with the research title. They are descriptive and comparative by design. Their wording depends on the two definitions in §3.1 and §3.2. A working model for both, approved by the project owner, is recorded there, but some of its points are still open (§3.5), and the questions have not yet been revised against it. They must be revised before B22 is closed (§3.5, O-11, with B8). The constraints the revised questions must meet are recorded in §3.7 (O-11). They do not revise the questions.

- **RQ1.** What policies within the project's policy domain have Turkmenistan and Uzbekistan formally adopted, and how do they compare in objectives, instruments, responsible institutions, and target sectors?
- **RQ2.** What documented evidence exists that these policies have been implemented, and how does that evidence differ in availability and kind between the two countries?
- **RQ3.** How have the indicators chosen to represent economic transformation developed in each country over the study period, and how do the trajectories compare, given differences in data availability and quality?
- **RQ4.** What temporal associations, if any, can be observed between formal policy events and indicator trajectories, and what alternative explanations exist for them?

RQ4 is exploratory. It can produce observations of association and a structured list of rival explanations. It cannot produce an estimate of policy effect.

## 3. Scope, definitions, and study period

- **Countries:** Turkmenistan and Uzbekistan.
- **Languages:** Turkmen, Uzbek (Latin and Cyrillic scripts), Russian, English.

A **covered country** is one the study includes; at present, the two above.

§3.1 to §3.8 contain four kinds of text, each marked:

- **APPROVED** text records the working model for blocker B22 that the project owner approved. It was recorded here on 2026-10-26.
- **DRAFT** text is an operational rule written to carry out that model. The responsible researcher confirms or replaces it.
- **PROVISIONAL** text records a default that the project owner approved on 2026-10-26 for preparing and running the pilot (§3.7, §3.8). It applies only to the pilot. It does not decide an OPEN point, and it does not count towards the conditions for closing B22 (§3.5).
- **OPEN** points are undecided. They are listed in §3.5 and are not answered in this protocol.

The specification names the researcher as the person who defines both concepts ([PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §10, B22). Where the project owner and the responsible researcher are different people, the researcher confirms the approved working model as well. **B22 remains open** until the conditions in §3.5 are met.

### 3.1 Policy domain (blocker B22: working model APPROVED, rules DRAFT, points OPEN)

**APPROVED.** The policy domain has two layers, which are kept analytically separate:

1. The **core AI policy corpus**: formally adopted public instruments of the covered countries that focus primarily on AI or contain explicitly AI-related provisions. For a broader instrument, only its AI-related provisions are coded. A whole document is not classified as AI policy merely because it contains one AI-related passage.
2. The **contextual policy registry**: relevant broader policy material, such as digital-economy, data-governance, telecommunications, and education policy. It is not automatically counted as core AI policy, and it is not automatically ingested in full.

The two layers hold public instruments. The document corpus also holds documents that are not instruments, such as official reports, statistics, research, and news (§4.1). They are sources of evidence about policies and belong to neither layer.

This protocol does not define artificial intelligence as a technology and introduces no classification of AI techniques. Whether a provision concerns AI is decided by the test in §3.1.2 and the terminology lists in §3.1.3.

Until the OPEN points in §3.5 are decided, no document is placed in either layer, or excluded from both, on a ground that depends on an open point. Such a document is escalated (§3.1.6). A pilot record made under the provisional defaults of §3.7 does not place a document in either layer or exclude it from the study. It is a pilot record (§3.8).

#### 3.1.1 Eligible public policy instrument (DRAFT, with OPEN points)

A document is an eligible public policy instrument when all three of the following hold.

1. **Public authority.** A public authority of a covered country issued or adopted it in the exercise of its public functions. Which authorities count, national and subnational, is OPEN (O-2). International commitments are OPEN (O-3).
2. **Form.** It is a law, decree, resolution, strategy, programme, or regulation, the instrument forms the data model already names ([DATA_MODEL.md](DATA_MODEL.md) §3.3), or another form the researcher makes eligible. The complete set of eligible forms and legal-status categories, including guidelines, codes, standards, and other instruments without binding force, is OPEN (O-1).
3. **Formal adoption.** A formal text establishes that the competent authority adopted or issued it, so that its adoption can be recorded as an `adopted` PolicyEvent with the Passage that establishes it (§6). A draft, a proposal, or an announced instrument whose adoption no formal text establishes is not in the core corpus. What is known about it is recorded as a claim. Whether such material can be contextual is OPEN (O-1).

#### 3.1.2 AI-focused instruments and AI-related provisions (DRAFT)

**Provision.** An identifiable unit of an instrument's text: an article, paragraph, clause, or item, or, in a strategy or programme, a stated objective, measure, action, or target. Its location is the locator of the Segment that holds it ([DATA_MODEL.md](DATA_MODEL.md) §3.3).

**Explicitly AI-related provision.** A provision for which both of these hold:

1. It names artificial intelligence, or a technique the terminology list classes as AI, by a term on the verified list for the language and script of the text (§3.1.3).
2. It provides for something about AI: an objective, measure, rule, institutional mandate, target, or resources concerning the development, adoption, use, or governance of AI, or the skills, data, research, or infrastructure that the provision designates for AI.

A mention of AI that provides for nothing, for example in a preamble or a background description, does not make a provision AI-related. It is noted in the eligibility decision as a mention.

**AI-focused instrument.** An eligible instrument whose primary subject is AI: its title, or its stated purpose or scope, names AI by a term on the verified list as what the instrument is about. An instrument whose title or stated purpose names AI together with other subjects is an ambiguous case (§3.1.6).

**Placement.**

- An AI-focused instrument is in the core corpus as a whole. Its provisions are coded under the codebook (§6).
- An instrument that is not AI-focused but has at least one explicitly AI-related provision is in the core corpus as an **instrument with AI-related provisions**. Only those provisions are coded. Its other provisions are not coded and are not counted as AI policy.
- An instrument with no explicitly AI-related provision is not in the core corpus. It is contextual material (§3.1.5), excluded, or escalated (§3.1.6).

**What does not qualify by itself.** Provisions on generic automation, digitalisation, data governance, algorithmic or automated processing, or automated decision-making are not AI-related unless they name AI by a term on the verified list. Whether a term belongs on the list is a terminology decision, made in the list with its reason (§3.1.3). It is never a default.

**Document level and provision level.** Two separate steps are involved:

- The **eligibility decision** places a document in a layer, or records it as excluded or escalated (§3.1.6).
- **Coding** (§6) records objectives, instruments, sectors, institutions, and formal events, each linked to its Passage.

The provisions identified in the eligibility decision show the coder what to code. They are not coded values themselves.

**Formal events.** An instrument with AI-related provisions has its formal lifecycle events recorded as usual, because they are events of the text that carries the provisions. An amendment that adds, changes, or removes AI-related provisions is recorded as an `amended` event. The eligibility decision is then made again for the amended version (§3.4).

**Counts.** Any count, list, or comparison of the core corpus shows AI-focused instruments and instruments with AI-related provisions separately, with the number of AI-related provisions coded from each. They are never added into one number without that breakdown.

#### 3.1.3 Terminology lists (DRAFT; contents OPEN)

Whether a provision or a title names AI is decided against a **terminology list**. This protocol proposes no term in any language.

- **One list per language and script.** A separate list exists for each language and script in which instruments are read. Each list matches a Language record ([DATA_MODEL.md](DATA_MODEL.md) §3.2), so Uzbek in Latin script and Uzbek in Cyrillic script have separate lists. No list is derived from another by translation or transliteration: every entry is verified in its own language and script.
- **What each entry records:**
  - the term as written, in Unicode Normalization Form C;
  - its language and script;
  - the sense in which it names AI or an AI technique;
  - how inflected, derived, and compound forms are matched in that language;
  - its provenance: the official text, terminology standard, dictionary, or other reference where it was found;
  - who verified it, and their reading competence in the language;
  - the date of verification.
- **Versions.** Each list has a version. A change creates a new version with a dated reason. Every eligibility decision, and every search for instruments, records the list version it used.
- **Differences between languages.** A list records the differences it knows of, such as a term whose sense is wider or narrower than its nearest counterpart in another language ([LIMITATIONS.md](LIMITATIONS.md) §2.5).
- **Where the lists are kept.** They are versioned files in the repository, kept with this protocol. Their location and format are fixed when the first list is written.
- **New terms.** A term met in reading that names AI but is not on the list is escalated (§3.1.6). If it is added, decisions made with earlier versions of the list are re-checked (§12).
- **OPEN (O-5):** who compiles and verifies each list, whether a second reader is required, and the rules for reviewing ambiguous cases.

**Known weakness.** A test based on explicit naming does not see AI that is governed through general instruments that do not name it ([LIMITATIONS.md](LIMITATIONS.md) §2.4). The contextual registry and a labelled sensitivity analysis (§3.1.5) make that effect visible. They do not remove it.

#### 3.1.4 Inclusion and exclusion rules (DRAFT)

The rules are the same for every country and every language. Each row applies the test of §3.1.2. The name of a category never qualifies or disqualifies a document by itself.

In the pilot, the rows that depend on O-1, O-2, O-3, or O-7 are read with the provisional default for that point (§3.7). Outside the pilot, every row stays as written here. The row on security, defence, surveillance, and law enforcement has no provisional default: that material is not in the pilot (§3.7, O-4).

| Material | Enters the core corpus when | What is coded | Otherwise | Where judgement cannot be avoided |
|---|---|---|---|---|
| Any AI-focused instrument | It is an eligible instrument (§3.1.1) | The whole instrument, under the codebook | — | Whether a title or stated purpose that names AI with other subjects makes AI the primary subject |
| Instruments that create, mandate, or govern a body dedicated to AI, and instruments such a body issues | They pass the same test as any instrument. The issuer alone neither qualifies nor disqualifies an instrument. A provision that creates or mandates a body for AI is AI-related. | The AI-related provisions, or the whole instrument if it is AI-focused | An instrument of such a body on a matter that is not about AI is assessed like any other | Whether a body's mandate is dedicated to AI, which is read from the instrument that founds or mandates it, not from its name |
| General digital-economy and e-government instruments | It has at least one explicitly AI-related provision | Only the AI-related provisions | Contextual material (§3.1.5) | AI named as one of several technologies to which a measure applies |
| Data governance: personal data, data localisation, cybersecurity | It has at least one explicitly AI-related provision | Only the AI-related provisions | Contextual material | Provisions on automated processing or automated decision-making that name AI by no listed term are not AI-related. The researcher may note them on the contextual entry. |
| Telecommunications, connectivity, and computing infrastructure | It has a provision that names AI and designates infrastructure, capacity, or resources for it | Only those provisions | Contextual material | Infrastructure for digital technology in general, with no listed term naming AI, is not AI-related |
| Education, skills, curricula, and research institutions | It has a provision on AI education, AI curricula, AI skills, AI research, or an institution or unit for AI | Only those provisions | General digital or ICT education is contextual material. Other education and research policy without AI-related provisions depends on O-7. | Whether a programme in a wider field names AI as part of what it provides |
| Sector-specific instruments, such as health, agriculture, industry, finance, and public administration | It has an AI-related provision within the sector | Only those provisions, with the sector taken from the codebook (B11) | Contextual material or excluded, depending on O-7. Until O-7 is decided, escalated. | The tests of the rows above. The sector is coded, never used to qualify. |
| Security, defence, surveillance, and law-enforcement instruments or provisions | OPEN (O-4), and subject to whether ethics review applies (B20, §11) | Nothing until decided | Escalated, with the reason | All of it, until decided |
| Instruments of subnational or special-status authorities | OPEN (O-2) | Nothing until decided | Escalated | — |
| International commitments a covered country signed, joined, or endorsed | OPEN (O-3) | Nothing until decided | Escalated | — |
| Instruments without binding force issued by a public authority: guidelines, codes, standards | OPEN (O-1) | Nothing until decided | Escalated | — |
| Drafts, proposals, and instruments never formally adopted | Never, because the approved model requires formal adoption | — | Recorded through claims where relevant. Whether they can be contextual material is OPEN (O-1). | Whether a formal text establishes adoption |
| Documents that are not instruments: official reports, statistics, research, news | Never, because they are sources about policies (§4.1), not instruments | — | Ingested as documents under §4 when they are needed as evidence. They belong to neither layer. | — |
| Material relevant to neither layer | — | — | Excluded, with the reason recorded where it was examined (§3.1.6) | — |

#### 3.1.5 Core AI policy corpus and contextual policy registry

| | Core AI policy corpus | Contextual policy registry |
|---|---|---|
| Holds | Instruments that pass §3.1.1 and §3.1.2 | Broader policy material in a contextual category (O-7) with no explicitly AI-related provision |
| Research role | The formally adopted policies that RQ1 and RQ2, as drafted, ask about, and the evidence of their implementation (§2, until revised) | Interpretation and sensitivity: what else a country's broader policy provides, and how the comparison depends on the boundary ([LIMITATIONS.md](LIMITATIONS.md) §2.4) |
| Counted in core results | Yes | Never by default |
| Ingested | Yes, as documents with versions, extractions, and Segments, subject to review and rights | Not by default (below) |
| Coded | Yes, at provision level for instruments with AI-related provisions | No |

**What the core corpus records for each instrument (DRAFT).** The requirements below are set against the current data model. This protocol adds no model, field, or migration; the gaps are listed in §3.6.

| Requirement | Recorded in the current data model by | Gap |
|---|---|---|
| Eligibility decision: its outcome, the rule applied, the reason, who decided, the date, and the protocol and terminology list versions | No structured record. A DocumentReview has a reason, and a SearchRun lists the sources it examined with reasons, both as text. | F-1 |
| Whether it is AI-focused or an instrument with AI-related provisions | Nothing | F-1 |
| Its AI-related provisions | Passages in its Segments. Each coded objective and instrument links to a Passage (DATA_MODEL I-13). | A provision identified but not yet coded has no record of its own (F-1) |
| Formal status | Derived from PolicyEvents (DATA_MODEL §4.4), never stored | — |
| Adoption, entry into force, amendment, expiry, repeal | PolicyEvents, with effective dates and Passages | — |
| Issuing body | The Document's issuing institution; the Policy's lead institution; Institution records with their names over time | The institution kinds may not cover every eligible issuing authority (F-5) |
| Country | The Document's country or countries; the Policy's country | — |
| Form | Document type | The list may not hold every eligible form (F-5) |
| Official identifier and date of issue | The Document, where they exist | A publication date that differs from the date of issue has no field (F-6) |
| Language and script; original or translation | DocumentVersion language, script, and kind | — |
| Source provenance | Source with its source tier; AcquisitionRecord with origin verification; Artifact hash | — |
| Version history | DocumentVersions, each with its text state (as adopted, or consolidated as amended to a date), and a new artifact for changed bytes | — |

**Contextual material (APPROVED in principle; form DRAFT).** Contextual material is examined and recorded. It is not presumed to be AI policy and is not counted in the core corpus.

- **Initial lightweight form.** Contextual material is recorded among the sources examined in a SearchRun ([DATA_MODEL.md](DATA_MODEL.md) §3.7), classified as contextual, with the reason. Nothing else is created for it: no Artifact, Document, DocumentVersion, Extraction, or Segment. Whether a contextual document may ever be ingested in full, and on what condition, is OPEN (O-8). Until it is decided, none is.
- **What each entry needs to record:**
  - the title as written, in its original language and script;
  - the country and the issuing authority;
  - the form, and the official identifier and date of issue where the text states them;
  - where it was examined, and the version or text state examined;
  - the date examined;
  - the contextual category;
  - the terminology list version used;
  - the result, worded within the examination: no explicitly AI-related provision was identified in the version examined, with that list version;
  - the reason it is recorded as contextual.
- **What the data model supports now.** A SearchRun records its queries in each language, its date and time, who ran it, the source universe, the inclusion and exclusion criteria, the sources examined with reasons, the method, and the outcome. It has no structured fields for the items it examined, no stable identifier for each item, and no link from an item to an Institution record. Contextual entries therefore cannot yet be listed across searches as a registry (F-3). SearchRun is also built in Phase 4, after documents are first ingested in Phase 2 (F-2). Where these are recorded until then is OPEN (O-10).
- **Which layer a search is for.** Each SearchRun states which layer its inclusion criteria are for, and its outcome refers to that layer. A search for core instruments that finds only contextual material has the outcome `no_qualifying_source_found`, with the contextual items listed among the sources examined.

**How contextual material may be used (DRAFT).**

- **Interpretation.** An interpretation claim may cite a SearchRun as evidence with the stance "provides context", to show that broader material was examined and what was recorded about it. What such material *says* can be cited only from a Passage of an ingested document, which needs O-8.
- **Sensitivity analysis.** To show how the boundary shapes a comparison, the researcher may present the comparison under a named alternative boundary that also counts stated contextual categories. Such a result:
  - is labelled as a sensitivity analysis;
  - names the alternative boundary and the categories it adds;
  - is shown apart from the core result and never replaces it;
  - is recorded as an interpretation claim or as a recorded analysis. AnalysisRun cannot yet take contextual entries as inputs (F-4).

#### 3.1.6 Eligibility decisions and escalation (DRAFT)

**Outcome.** Each document examined for the policy domain receives one of five outcomes:

- core corpus, AI-focused;
- core corpus, instrument with AI-related provisions;
- contextual;
- excluded;
- escalated.

**Record.** The decision records:

- the document, and the version and text state examined;
- whether it was read in the original, in a translation, or in machine translation (§3.4);
- the outcome, and the row of §3.1.4 that was applied;
- the provisions identified, by locator, and any mentions noted;
- the reason;
- who decided, and the date;
- the protocol version and the terminology list version.

**Escalation.** A document is escalated when:

- an OPEN point applies;
- a judgement named in §3.1.4 is needed;
- a term not on the list appears to name AI;
- the text could be read only in machine translation;
- no available reader reads its language.

An escalated document is in neither layer and is not excluded. It is listed with its reason until the escalation is resolved. The resolution is recorded with its reason, and each resolution of a recurring kind of case is kept, so that the same situation is treated the same way in every country and language. Once the codebook exists, it carries these resolutions forward (B11).

**Reproducibility.** Another researcher holding the same document version, protocol version, and terminology list version can check a decision against its record. Where two readers of a language are available, a sample of decisions is made independently and agreement is reported. Where only one is available, this is stated as a limitation, and a re-check after an interval is used instead, as for coding (§6). Which of these applies is part of O-5.

### 3.2 Economic transformation (blocker B22: working model APPROVED, indicators OPEN)

**APPROVED.** Economic transformation is analysed in three separate layers. They describe different phenomena, and they are not conflated or used to imply unsupported causality.

| Layer | What it represents | What it does not establish |
|---|---|---|
| **A. Structural economic change** | Change in the composition of economic output, employment, and trade, and in other suitable measures of economic structure | That digital technology or AI drove the change, or that a policy caused it. Structural change can follow from prices, reforms, external events, and other causes that the design cannot separate ([LIMITATIONS.md](LIMITATIONS.md) §1). |
| **B. Digital transformation** | The adoption and spread of digital technologies, and the development of digital-intensive activity | AI adoption or AI activity, since digital adoption is not AI adoption. Nor that structural change followed from it, or that a policy caused it. |
| **C. AI-specific outcomes** | Observable measures specifically related to AI, where reliable and comparable evidence is available | That AI policy caused them, or that they represent change in the whole economy, of which AI-related activity may be a small share ([LIMITATIONS.md](LIMITATIONS.md) §3, unverified) |

**Rules (DRAFT).**

1. **One layer per indicator.** Each indicator is assigned to exactly one layer, with a recorded reason. An indicator that could fit two layers is assigned to one, the reason says why, and it is not counted in both.
2. **Layers are reported separately.** Each layer is reported on its own for each country, with its own statement of coverage. Layers are not combined into one index or score. A combined measure would need an amendment to this protocol.
3. **No overall verdict.** No statement says that economic transformation as a whole has or has not occurred. Statements are made about named indicators in a named layer. A reading across layers is an interpretation claim that names alternative explanations (§5).
4. **Associations are not causes.** An association between layers, or between a formal policy event and an indicator in any layer, is a correlation claim with a recorded analysis and the non-causation notice (§5, §8). A stronger conclusion would need a research design that this protocol does not have (§8).
5. **What counts in layer C.** Layer C uses only measured values from identified providers (Observations). Documentary reports of AI activity, such as an institution established or a system deployed, are implementation evidence or documented facts (§5). They are not indicator values and are never converted into them. Counts of instruments in the core corpus describe policy, not outcomes, and are never used as a layer C measure.
6. **Missing, incomparable, uncertain, or unavailable data.**
   - Missing values stay missing (§7). A layer is never filled from another layer, and no layer B indicator is presented as a stand-in for layer C.
   - Estimated, provisional, and projected values keep their flags.
   - Where providers define an indicator differently, the series are kept apart and the difference is stated (§7, [LIMITATIONS.md](LIMITATIONS.md) §2.2).
   - Where a recorded search finds no reliable, comparable indicator for a layer and a country, that layer is reported as having no indicator for that country, not dropped. The result may be stated as a negative finding bounded by the search (§5).
   - Every comparison shows, for each layer and country, which indicators have values and which do not.

**OPEN (B12, after B22).** The indicators for each layer, their definitions, providers, licence terms, and selection criteria are chosen by the researcher, with a recorded reason for each (§7). This protocol names no indicator, provider, or value. Until they are chosen, RQ3 has no fixed content.

### 3.3 Study period (OPEN, blocker B8)

To be set by the researcher, with a stated reason for the start year. Which formal dates place an instrument inside the period, and whether an instrument adopted before the period but in force during it qualifies, are OPEN (O-6). The provisional pilot rule for O-6 is in §3.7. It cannot be applied to any instrument until the period is set.

### 3.4 Language, translation, and time in eligibility decisions (DRAFT)

**Language and translation.**

1. **The original decides.** Eligibility is decided on the authoritative original text (§4.4). A decision made on a translation records that it was, and which translation: official or unofficial, with its translator or method. It is checked against the original when the original is obtained.
2. **Machine translation.** A machine translation may help to find candidate provisions. A decision that rests on machine translation alone is escalated (§3.1.6) until a reader of the language confirms it.
3. **No exclusion for language.** No document is excluded or held back because its authoritative text is not in English, or because no translation exists. If no available reader reads its language, it is escalated with that reason, and the gap is reported as a limitation of coverage ([LIMITATIONS.md](LIMITATIONS.md) §2.5).
4. **Searches in every language.** Searches for instruments are run in each corpus language of the sources searched, each with that language's terminology list. The SearchRun records the languages searched and the list versions. An English-language secondary account, such as an international database's entry, can lead to an instrument but does not stand in for it: what a policy says is established from the instrument itself where it exists (§4.1).
5. **Names.** The names of instruments and institutions are recorded in the original script, with transliteration and English rendering as additional fields (§4.4).

**Time.**

6. **One version per decision.** An eligibility decision refers to one document version and its text state: as adopted, or consolidated as amended to a date ([DATA_MODEL.md](DATA_MODEL.md) §3.3).
7. **Amendments.** An amendment that adds, changes, or removes AI-related provisions leads to a new decision for the amended version. Earlier decisions stay on record. An instrument whose AI-related provisions were all removed by amendment stays in the record for the period in which it had them.
8. **The date relied on.** The temporal basis for inclusion is a date that a formal text establishes: adoption, entry into force, expiry, or repeal (PolicyEvents). The decision states which date it relies on. An unknown date stays empty; it is not inferred from a publication date or a later report.
9. **Changes to the rules.** Decisions are made under a stated protocol version and terminology list version. When either changes in a way that could alter a decision, the earlier decisions are re-checked and the re-check is recorded (§12).

### 3.5 Open decisions and conditions for closing B22

The project owner approved the working model, not every detail of it. These decisions are open, and this protocol does not answer them. For most of them the owner approved a provisional default for the pilot on 2026-10-26 (§3.7). A provisional default is not a decision of its point: every point below stays OPEN until it is decided and written into this section.

| # | Decision | Linked to | Status on 2026-10-26 |
|---|---|---|---|
| O-1 | The complete set of eligible instrument forms and legal-status categories, including instruments without binding force. Whether drafts and never-adopted instruments can be contextual material. | F-5, F-11, B7 | OPEN. Provisional pilot default (§3.7). |
| O-2 | The scope of issuing authorities: national bodies only, or subnational and special-status bodies too | F-5 | OPEN. Provisional pilot default (§3.7). |
| O-3 | The treatment of international commitments that a covered country signed, joined, or endorsed | F-12 | OPEN. Provisional pilot default (§3.7). |
| O-4 | The treatment of security, defence, surveillance, and law-enforcement instruments and provisions | B20 (§11), F-15 | OPEN. No pilot default; the material is not in the pilot. |
| O-5 | The verified terminology lists: who compiles and verifies each, whether a second reader is required, how inflected and derived forms are matched, and the rules for reviewing ambiguous cases. No list exists yet. | F-14 | OPEN. Provisional workflow for the pilot (§3.7). No list exists. |
| O-6 | Whether an instrument adopted before the study period and in force during it qualifies, and which formal dates place an instrument inside the period | B8, F-6 | OPEN. Provisional pilot rule (§3.7); it cannot be applied until B8 sets the period. |
| O-7 | Which categories of broader policy, beyond the four the approved model names (digital economy, data governance, telecommunications, and education), are contextual. In particular, whether sector policy and general research policy without AI-related provisions are contextual or excluded. | — | OPEN. Provisional pilot default (§3.7). |
| O-8 | Whether a contextual document may ever be ingested in full, and on what condition. Until decided, none is. | B7, F-13 | OPEN. Provisional pilot default: metadata only (§3.7). |
| O-9 | Confirmation or replacement of the DRAFT rules in §3.1 to §3.4, including the test for an AI-focused instrument and the one-layer rule for indicators | — | OPEN. The five outcomes are kept for the pilot; two further rules are DRAFT, to be tested (§3.7). |
| O-10 | Where eligibility decisions and contextual entries are recorded before SearchRun exists, and in what structured form | F-1, F-2, F-3, F-16 | OPEN. Provisional format for pilot records (§3.8). Publication of actual pilot records, and recording in Phase 2, are undecided. |
| O-11 | The revision of RQ1 to RQ4 against the definitions | B8 | OPEN, pending B8. Constraints recorded (§3.7). |

**Conditions for closing B22 (DRAFT).** B22 remains a Phase 2 blocker ([PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §10). It can be closed only when all of the following hold:

1. O-1 to O-9 are decided and written into this section.
2. A first verified terminology list exists, with a version, for each corpus language and script in which instruments will be read.
3. The researcher has applied the rules to a pilot sample of documents in each of those languages and scripts. The documents are read outside the system if ingestion does not yet exist. Every escalated case and its resolution are recorded, and the rules are revised where the pilot showed them to be unclear. Where two readers are available, they apply the rules independently to part of the sample and their agreement is reported. Otherwise a re-check after an interval is used, and the limitation is stated. The pilot sample does not settle the seed source list (B9).
4. The research questions are revised against the definitions (O-11, with B8).
5. O-10 is decided, so that Phase 2 can record eligibility decisions.
6. The researcher records the closure here with its date, and the gate table in the specification is updated in the same change.

A provisional default (§3.7) does not meet condition 1. The pilot of condition 3 is set out in §3.8, and condition 3 is met only when that pilot has been run and reported. If a point is later decided differently from its provisional default, in a way that could change a pilot decision, the affected pilot decisions are re-checked (§12). The researcher then records whether condition 3 still holds, or whether a further validation round is needed.

Condition 1 includes O-4, which cannot be decided until B20 is answered. The specification places B20 at a later phase than B22. What must be decided before B22 can close is set out in F-15.

These conditions are DRAFT. The project owner has not approved them as binding, and the gate table in the specification does not include them (F-9). Their DRAFT status is not a reason to close B22 on fewer conditions, and the shorter wording of the gate table is not a ground for closing B22 without them. B22 is not marked closed until the project owner has explicitly confirmed the closure gate: which conditions must hold, and that they hold.

### 3.6 Points for other documents

These points follow from §3.1 to §3.8 and belong to other documents. This protocol does not change those documents. Each point is settled in its own reviewed change.

| # | Point | Document | Settled with |
|---|---|---|---|
| F-1 | No record holds the eligibility decision: its outcome, rule, reason, decider, date, protocol and terminology list versions, and the provisions identified (§3.1.6) | DATA_MODEL | O-10, B11, B23 |
| F-2 | SearchRun is built in Phase 4, but eligibility decisions and exclusions start with ingestion in Phase 2 (§4.2) | PROJECT_SPECIFICATION §7; DATA_MODEL | O-10 |
| F-3 | A SearchRun's sources examined has no structured fields for an item and no stable identifier per item, so contextual entries cannot be listed across searches (§3.1.5) | DATA_MODEL §3.7 | O-10 |
| F-4 | AnalysisRun inputs are series, releases, and PolicyEvents, so contextual entries cannot be an input to a recorded sensitivity analysis | DATA_MODEL §3.7 | When a sensitivity analysis is first planned |
| F-5 | The document types and the eight institution kinds may not include every eligible form (O-1) or issuing authority (O-2). The data model requires such a list to be extended first. The document types have no value for a guideline, a code, or a standard, and recording one as `other` would lose its form. The institution kinds have none for a head-of-state office, a government acting as a collective body, a subnational administration, or a special-status body. Whether a given body fits an existing kind is read from the instrument that founds or mandates it and is recorded with the reason. It is never mapped to the nearest kind (DATA_MODEL §3.2). | DATA_MODEL §3.2, §3.3 | O-1, O-2 |
| F-6 | A publication date that differs from the date of issue has no field | DATA_MODEL §3.3 | O-6 |
| F-7 | Assigning each indicator to one layer needs a place to record it. Indicator has a category whose values are not defined. | DATA_MODEL §3.5 | B12 |
| F-8 | LIMITATIONS §2.4 says both concepts are not yet defined. When B22 closes, it should state the adopted definitions and the known weakness of the explicit-naming test (§3.1.3). It should also state the boundary effects of the final rules for O-2 and O-3: material outside the core boundary is not visible in core results, and its absence there says nothing about a country's policy. | LIMITATIONS | Closure of B22 |
| F-9 | The gate table describes B22 as two undefined concepts. Its "Needed" column asks only that the researcher define both and revise the research questions, and it does not refer to the conditions in §3.5. Those conditions are DRAFT, and the project owner has not approved them as binding. Neither document therefore yet states a confirmed closure gate for B22. Before B22 is marked closed, the project owner explicitly confirms the closure gate (§3.5), and the row is updated in the change that records the closure (condition 6). Until then B22 stays open, and the shorter wording of the row is not a ground for closing it. | PROJECT_SPECIFICATION §10 | Owner confirmation of the closure gate; closure of B22 |
| F-10 | Comparisons by sector, instrument type, institution, and time (FR-40) must show AI-focused instruments and instruments with AI-related provisions separately, and keep contextual material out of core results | PROJECT_SPECIFICATION §4 | Phase 6 |
| F-11 | No field records whether an instrument is binding or not binding. The separation that O-1 requires (§3.7) can therefore be neither recorded nor shown. | DATA_MODEL §3.3, §3.6 | O-1 |
| F-12 | A Policy carries one country, and a PolicyRelation links two policies. An international instrument therefore cannot be a Policy or the target of an `implements` relation. A covered country's signature, accession, ratification, or endorsement of one has no record except a claim. | DATA_MODEL §3.6 | O-3 |
| F-13 | Nothing records that a Document is contextual material. A contextual document, if ingested (O-8), would be eligible for retrieval like any approved document (AI_ARCHITECTURE §4.1), and comparisons could not keep it out of core results (F-10). | DATA_MODEL §3.3; AI_ARCHITECTURE §4.1 | O-8, before any contextual document is ingested |
| F-14 | No field holds the terminology list versions a SearchRun used (§3.1.3, §3.4 rule 4), and the data model holds no terminology list or version | DATA_MODEL §3.7 | O-5, O-10 |
| F-15 | The specification lists B22 under "Blocks Phase 2" and B20 under "Blocks Phase 4". O-4 depends on B20 (§3.7), and condition 1 of §3.5 needs O-4 decided. As the documents stand, B22 cannot close, and Phase 2 cannot open, until B20 is answered, which the gate table does not require before Phase 4. Before B22 can close, the project owner decides when B20 is answered. If it is to be answered before B22 closes, the gate table records that in a separately reviewed change to the specification. Any other resolution also needs its own reviewed change, approved by the owner, and may not bypass, narrow, or redefine B20. This protocol does not move B20 to another phase. Until then, O-4 and B20 stay open, and the material of O-4 stays out of the pilot (§3.7). | PROJECT_SPECIFICATION §10 | Owner decision on when B20 is answered, before B22 can close |
| F-16 | CONTRIBUTING says research records, recorded searches among them, are made through the application. The pilot records of §3.8 are kept outside it because the application cannot hold them yet. They are not research records of the study, and nothing is entered into the application from them without a separate reviewed decision. | CONTRIBUTING, "Research content contributions" | O-10 |

### 3.7 Provisional defaults for the pilot (PROVISIONAL, approved by the project owner on 2026-10-26)

The project owner approved the defaults below on 2026-10-26 as the working basis for preparing and running the pilot (§3.8). They are not research findings, and they are not decisions of the OPEN points. They apply only to pilot records. They change nothing in §3.1 to §3.4 for the study, and **B22 stays open** (§3.5). Each point is decided later by the researcher, with the project owner's approval where it changes the scope of the approved model, and the decision is written into §3.5. A default may then be confirmed, changed, or replaced.

In this section, "recorded as excluded", "escalated", and "recorded" refer to the pilot record (§3.8).

**O-1. Instrument forms and legal status (PROVISIONAL).**

- The pilot considers formally adopted binding instruments, and officially issued instruments without binding force, such as strategies, programmes, guidelines, codes, and standards, when §3.1.1 and §3.1.2 are met. An instrument without binding force also needs a formal text that establishes that the authority issued it (§3.1.1, condition 3).
- Each pilot decision records the legal status as binding, not binding, or uncertain, with the place in the text where it was established. An uncertain status is escalated.
- Binding and non-binding instruments are kept apart in every pilot count and comparison, as AI-focused instruments and instruments with AI-related provisions are (§3.1.2). They are never added into one total without that breakdown.
- Drafts, proposals, and instruments never adopted do not qualify (§3.1.1, condition 3). They are recorded as excluded, with the reason. Whether they can be contextual material stays OPEN and is not tested in the pilot.
- A document behind a paywall, or one whose right to be obtained or retained is unresolved, is flagged for review under B7. It is not downloaded or retained for the pilot (§3.8, point 2). The pilot decides no rights question.
- The final list of eligible forms and legal-status categories needs the researcher's verification and any necessary rights review. The data model cannot yet record every form or the legal status (F-5, F-11).

**O-2. Issuing authorities (PROVISIONAL).**

- The core boundary for the pilot is national-level public authorities of a covered country.
- An instrument issued by a subnational or special-status authority is not core under this default. It is recorded as excluded, with the issuer's level and the reason. A national instrument that establishes or governs a subnational or special-status body or regime is a national instrument, and the ordinary test applies to it.
- An issuer whose level is ambiguous is escalated.
- An exclusion under this default marks a boundary of the study. It is never presented as evidence that a country has no AI policy, at any level of government.
- Each pilot decision states whether the issuer fits one of the eight institution kinds ([DATA_MODEL.md](DATA_MODEL.md) §3.2), as read from the instrument that founds or mandates it. An issuer that fits none is recorded as fitting none. It is never mapped to an inaccurate kind. The kinds known to be missing are listed in F-5.

**O-3. International commitments (PROVISIONAL).**

- An international instrument is outside the domestic core corpus and is in neither layer.
- A covered country's relation to an international instrument is recorded only where a source establishes it. The kinds of relation are kept distinct: signature, accession, ratification, endorsement, and implementation by a named domestic instrument. In the study these are documented-fact claims with their evidence (§5). In the pilot they are noted in the record with the source that establishes them. One status is never inferred from another, and no obligation of a country is stated unless a source establishes it.
- A domestic instrument that ratifies or implements a commitment is assessed under the ordinary rules (§3.1.1, §3.1.2).
- A domestic instrument whose only relevant content is an incorporated international text is escalated where the rules do not settle the case.
- The data model cannot record an international instrument as a Policy or as the target of a relation (F-12).

**O-4. Security, defence, surveillance, and law enforcement (OPEN, pending B20).**

- No provisional default. The point stays OPEN until the researcher has confirmed whether institutional ethics review applies (B20, §11) and the project owner has decided the point.
- This material is not selected for the pilot. It stays out of the pilot until the researcher has confirmed whether institutional ethics review applies, any review that applies has given its approval, and the project owner has decided O-4. A selected document found to contain it is withdrawn from the pilot as soon as that is found. The withdrawal and its reason are recorded, the material is not assessed further, and the document is not counted in agreement results. Where possible it is replaced by another candidate with the same selection label.
- Nothing in this protocol bypasses, narrows, or redefines B20. When B20 must be answered is F-15.

**O-5. Terminology lists (PROVISIONAL workflow; no list exists).**

1. The researcher confirms in writing each language and script in which instruments will be read or searched for. Each matches a Language record. No language or script is assumed, including the script or scripts of Turkmen, which §3 does not state.
2. For each language and script, the researcher names a compiler and records their reading competence in it.
3. The compiler collects candidate terms from named references: official texts, terminology standards, dictionaries, or others. Each entry records the fields of §3.1.3: the term as written, in NFC; its language and script; the sense in which it names AI or an AI technique; the forms it matches, either listed or given by a written matching rule; its provenance; the verifier and their competence; and the date of review.
4. Preferably, a second competent reader checks every entry independently and records agreement or disagreement with its sense and its forms or matching rule. Each disagreement is resolved and recorded. A term still in doubt is marked ambiguous.
5. Where no second reader is available, the compiler checks every entry again after an interval, without consulting the earlier check. The researcher chooses the interval and records it before the first check. The limitation is stated with the list.
6. An ambiguous term stays on the list, marked ambiguous. Every match of it is escalated, and each resolution is kept (§3.1.6).
7. False hits (a match that does not name AI where it occurs) and missed terms (a term that names AI but is not on the list) are entered in the term-gap log (§3.8), each with its locator, the decision taken, and any list version that resulted.
8. Each change makes a new version with a dated reason (§3.1.3). The calibration round may change a list. The validation round uses one fixed version of each list (§3.8). The version confirmed after validation is the first verified version that condition 2 of §3.5 requires.
9. Pilot versions of a list are kept with the pilot records, because their provenance may name real documents. A list is committed to this repository, as §3.1.3 requires, only once publication of its provenance has been confirmed (O-10 below).

This protocol proposes no term in any language.

**O-6. Instruments adopted before the study period (PROVISIONAL rule; applying it depends on B8).**

- An instrument meets the time condition when its formal validity overlaps the study period. A formal text must establish that it was adopted or entered into force on or before the last day of the period. No formal text may establish that it expired or was repealed before the first day.
- The evidence is recorded: the formal dates found, with their locators; the date the decision relies on (§3.4 rule 8); where the dates were checked; and the date of that check.
- When no expiry or repeal is found, the record says so: "no expiry or repeal was found in [where checked] as of [date]". This is never recorded as proof that the instrument remained in force.
- An unknown or ambiguous date is escalated. No date is inferred from a publication date or a later report (§3.4 rule 8).
- Until B8 sets the period, the pilot records the dates and their evidence, and records that the time condition cannot yet be applied. It decides for no instrument whether it falls inside the period.
- **Effect on RQ4.** An instrument adopted before the period is part of the setting in which every indicator value in the period is observed. A temporal comparison around its adoption would rest on observations from before the period, and whether the study uses any is part of B8. In a temporal comparison around a later event, such instruments are among the alternative explanations that an interpretation has to consider (§5, rule 5). Nothing about them is stated as an effect (§8).

**O-7. Contextual categories (PROVISIONAL).**

The initial contextual taxonomy for the pilot has four categories:

1. Digital economy and e-government.
2. Data governance, including relevant personal-data, data-localisation, and cybersecurity material.
3. Telecommunications, connectivity, and computing infrastructure.
4. Education, skills, curricula, and research institutions.

- A document is contextual only if it falls in one of these categories and has no explicitly AI-related provision (§3.1.5). A category never makes a document eligible for the core corpus. A document with an explicitly AI-related provision is assessed under §3.1.2, whatever its category.
- In the pilot, the reference to O-7 in the education and research row of §3.1.4 is read with category 4. General research policy that does not concern research institutions fits none of the four categories and is escalated, with that reason.
- General sector policy without an AI-related provision is not contextual under this default. It is recorded as excluded, with the reason. A reader who judges it relevant context says so in the record, as evidence for a possible further category.
- A further category is added only by a dated revision of this protocol, reviewed like any change to §3.1 (§12).

**O-8. Full ingestion of contextual material (PROVISIONAL).**

- Contextual material is recorded as metadata only (§3.1.5, §3.8). No contextual document is ingested in full, and none is made available in full text to AI retrieval.
- A later exception may be considered only when all of the following hold:
  - a defined research claim or sensitivity analysis requires the content;
  - the reason is recorded before ingestion;
  - the applicable rights determination under B7 permits storage;
  - the contextual status stays explicit, and the material is not counted as core AI policy;
  - the AI architecture has explicit rules for distinguishing and handling contextual evidence (F-13).
- The exception is not adopted, and nothing in this protocol implements it. It needs its own decision of O-8 and the follow-ups it names.

**O-9. Operational eligibility rules (five outcomes kept; two rules DRAFT).**

- The pilot keeps the five outcomes of §3.1.6: core corpus, AI-focused; core corpus, instrument with AI-related provisions; contextual; excluded; escalated.
- §3.1.2 is kept unchanged. A mention of automation, digitalisation, algorithms, or automated decision-making makes a provision AI-related only if the provision names AI by a term on the verified list and provides for something about AI.
- Two further rules are DRAFT. They are tested in the pilot, and the researcher confirms, changes, or drops them afterwards:
  - **Mixed-subject title (DRAFT).** An instrument whose title or stated purpose names AI together with other subjects is treated as an instrument with AI-related provisions, unless its stated purpose makes AI the primary subject. Reason: placing it wrongly as AI-focused would code provisions that are not about AI as AI policy, while this placement still codes every AI-related provision.
  - **Several technologies (DRAFT).** A provision that names AI among several technologies is AI-related when its objective, measure, or rule applies to AI. The decision record marks it as applying to several technologies. A provision that names AI only as an example, or where it is unclear whether the objective, measure, or rule applies to AI, is escalated.
- During the pilot, a reader applies the rule to every case it covers and also records the case for escalation review. Agreement between readers (§3.8, point 7) is measured on the outcome the rule gives. The record also keeps the resolution of the review, so that the pilot shows how often the rule and the resolution agree.

**O-10. Records made before the application can hold them (PROVISIONAL format; publication and Phase 2 OPEN).**

- Pilot records use the metadata-only, version-controlled format of §3.8, point 9. This protocol creates no actual record and no source list.
- Whether actual pilot metadata may be published in this public repository is undecided. That includes document titles, identifiers, source addresses, and hashes. Being metadata does not make them publishable. Publishing them needs the project owner's explicit confirmation under the applicable publication and rights policy (B7). Until then, actual pilot records are kept under version control outside this public repository, in a location the project owner designates.
- How eligibility decisions are recorded in Phase 2 and later is undecided. Any application or data-model work for it (F-1, F-2, F-3, F-14) needs a separate reviewed decision before Phase 2 is implemented.

**O-11. Research questions (OPEN, pending B8).**

The questions in §2 are not revised here. The revised questions must satisfy these constraints:

- RQ1 and RQ2 distinguish AI-focused instruments from instruments with AI-related provisions.
- Contextual material does not enter core-policy counts, lists, or comparisons silently. As drafted, RQ1 refers to "policies within the project's policy domain", and under §3.1 that domain has two layers. The revision states that RQ1 concerns the core corpus, or how contextual material enters it as a labelled sensitivity analysis (§3.1.5).
- RQ3 keeps the three layers of §3.2 separate, and reports coverage and missing data for each layer and country.
- RQ4 remains exploratory and presupposes no causation (§8). It states how instruments adopted before the period are treated (O-6).
- The final wording and the study period are the researcher's decision (B8).

### 3.8 Pilot of the eligibility rules (DRAFT; record format PROVISIONAL)

**Purpose.** The pilot tests whether the rules of §3.1 to §3.4, read with the provisional defaults of §3.7 and the pilot versions of the terminology lists, give reproducible decisions in each language and script. Run as set out here, it is the pilot that condition 3 of §3.5 requires. It does not settle the seed source list (B9). It builds no corpus and ingests nothing.

**Status of results.** No pilot record or result is a research finding. A pilot decision places no document in either layer for the study. It is never cited as evidence, entered as a claim, or used as a test fixture, and nothing is carried into the application from it without a separate decision (F-16). When ingestion exists, each document receives a new eligibility decision under the protocol then in force. A pilot in which nothing was found for a category is not a negative finding (§5).

**1. Before the pilot.** The following are recorded before any candidate is read:

- the languages and scripts confirmed under §3.7, O-5, step 1;
- for each of them, the readers and their reading competence, and whether two readers are available or the blind re-check is used;
- the pilot version of each terminology list;
- the protocol version, given as the commit of this file;
- the location of the pilot records (§3.7, O-10);
- the intended size of each sample, with a reason.

**2. Candidates.** The researcher supplies the candidate documents, or verifies each candidate before it can be selected. For each candidate the researcher records how it was found (where, when, and with which queries in which language and list version). Candidates that fall under O-4 are not selected (§3.7).

B7 is open, and a document being publicly available does not by itself establish that it may be downloaded, retained, or copied. Therefore:

- The exact bytes of a candidate are obtained and retained for the pilot only after the right to obtain and retain them has been checked and recorded: what the check relied on, who made it, and when. The check serves the pilot only. It is not a rights determination ([RIGHTS_AND_LICENSING.md](RIGHTS_AND_LICENSING.md) §2), it decides no part of B7, and it permits no other use. Where the bytes are retained, the record states how they were obtained (address or description, date, and method), and they are kept as point 9 sets out.
- Where that right is unresolved, the file is not downloaded or retained for the pilot. The candidate is flagged for review under B7, and only the discovery metadata that is safe and permitted to record is recorded. Where it is uncertain whether an item of discovery metadata may be recorded, that item is not recorded, and the candidate stays unresolved until it has been reviewed.
- Only candidates whose bytes are retained under this point are read for the content classification of points 4 to 7, since each reader decision records the hash of the bytes read (point 5). A candidate whose text cannot lawfully be retained is not used for that work, and the need to fill a sample stratum is never a reason to use it.

**3. Selection and coverage.**

- The researcher draws two disjoint samples from the candidates, one for the calibration round and one for the validation round. No document is in both.
- Each sample is stratified by country, by language and script, and by the outcome the selector expects. It includes the cases the rules name as hard: mixed-subject titles, AI named among several technologies, instruments without binding force, issuers of unclear level, domestic acts concerning international commitments, amended instruments, incomplete formal dates, and documents available only in translation.
- The expected outcome is a selection label only. Readers do not see it. Where possible, the person who selects is not a reader.
- Coverage is assessed for each language and script actually used: how many documents of each expected outcome and each hard case each sample holds. A language, script, outcome, or hard case for which no candidate could be found, obtained, or lawfully retained (point 2) is recorded as a coverage limitation of the pilot. It is never read as evidence that a country lacks such a policy, or lacks AI policy at all.

**4. Rounds.**

- **Calibration.** Readers apply the rules to the calibration sample. Disagreements, escalations, and term gaps lead to revised rules and new list versions, each with its date and reason.
- **Validation.** Before it starts, the protocol version, the list versions, and the acceptance thresholds (point 7) are fixed and recorded. Readers apply them to the validation sample. Nothing found in this round changes the rules applied in it: changes are recorded for the next version. If a threshold is not met, the rules are revised and a new validation round is run on documents not used before.

**5. What each reader records.** A document that is compared (points 6 and 7) has two independent records. With two readers, each reader makes one. With one reader, the two records are the first reading and the blind re-check of point 7, made by the same person. Each record is completed without seeing the other record of the same document or the selection label. For the re-check, this means the reader does not consult the first record until the re-check record is complete. Every value is read from the document itself, or, for provenance, from the record of how it was obtained. A value the document does not state is left empty, not inferred. For each document:

- **Version and provenance:** the document version and its text state (as adopted, or consolidated as amended to a date); whether it was read in the original, an official translation, an unofficial translation, or machine translation (§3.4); the SHA-256 of the bytes read; how they were obtained (point 2).
- **Document level:** the outcome, one of the five of §3.1.6; the row of §3.1.4 applied; the reason.
- **Provision level:** for an instrument with AI-related provisions, each AI-related provision by locator; mentions noted; which provisions a DRAFT rule of §3.7, O-9, decided.
- **Legal status:** binding, not binding, or uncertain, and where in the text it was established.
- **Issuing authority:** as named in the text; its level (national, subnational, special-status, or unclear); whether it fits an institution kind (§3.7, O-2).
- **Dates:** each formal date found, with its locator; the date relied on; where and when the dates were checked; where applicable, the statement that no expiry or repeal was found (§3.7, O-6).
- **Contextual category,** if the outcome is contextual.
- **Escalation** reason and kind, if the outcome is escalated.
- The reader, the date, the protocol version, and each list version used; with one reader, whether the record is the first reading or the re-check.

**6. Disagreements, escalations, and term gaps.**

- Once both records of a document exist, whether they come from two readers or from one reader's first reading and re-check (point 5), they are compared on: the outcome; the set of AI-related provisions; the legal status; the issuer's level; the date relied on; and the contextual category.
- Each difference receives a reconciliation record: what differed, its cause (unclear rule, missing or ambiguous term, reading error, translation, open point, or another cause, described), the resolution, and any rule or list change it led to.
- Each escalation is given a kind, so that every recurring kind receives one written resolution (§3.1.6). An unresolved escalation stays listed with its reason.
- The term-gap log records false hits and missed terms (§3.7, O-5, step 7). In each sample, the reader or readers read part of the documents in full, not only where the list matches, to find terms the list misses. That part is chosen before reading.
- Withdrawals under §3.7, O-4, are recorded with their reason.

**7. Agreement, re-check, and acceptance thresholds.**

- With two readers, agreement is reported for each comparison of point 6, for each language and script and overall. The report gives the number of documents, the raw agreement, the full table of agreements and disagreements, and any chance-corrected coefficient chosen in advance. With few documents, such a coefficient is unstable, so the table is always reported with it.
- With one reader, the reader classifies the validation sample again, blind to the first reading, after an interval that the researcher chose and recorded before the first reading. The same comparisons are reported as agreement with the first reading, and the limitation is stated (§3.1.6).
- **The acceptance thresholds are a pre-validation decision of the researcher.** Before the validation round starts, the researcher records which measures are used, the statistic for each, its minimum value, and what follows if a minimum is not met. They are not changed after any validation result has been seen. This protocol sets no numerical threshold.

**8. Pilot report.** The researcher writes a report that states:

- the protocol and list versions;
- the sample design and the coverage achieved for each language and script;
- the coverage limitations;
- the agreement or re-check results against the recorded thresholds;
- the escalation kinds and their resolutions, and the term-gap results;
- every rule and list revision, with its date and reason;
- whether condition 3 of §3.5 is met.

The report contains no quotation and no text of any document. Whether it may name documents publicly depends on the confirmation in §3.7, O-10.

**9. Texts and records.**

- Full texts and exact bytes are retained only as point 2 allows. They are kept outside this public repository unless a separate rights and handling decision permits otherwise ([RIGHTS_AND_LICENSING.md](RIGHTS_AND_LICENSING.md)). They are external content and are treated as untrusted ([SECURITY.md](../SECURITY.md)).
- No text of a pilot document, in full or in part, is sent to an external AI or translation provider while the B7 decision on transmission to a provider is unresolved. This includes machine translation by an external service. After that decision, text is sent only where its rights allow it ([RIGHTS_AND_LICENSING.md](RIGHTS_AND_LICENSING.md) §2).
- Eligibility decisions in the pilot are made by the readers. As with policy coding (§10), no AI tool makes or suggests them.
- Pilot records are metadata only and are kept under version control in the location of §3.7, O-10. They hold no quotation, no full text, and no credential. They use these record types:

| Record | Holds |
|---|---|
| Pilot setup | The items of point 1, and the thresholds of point 7 once fixed, with the date they were fixed |
| Candidate | A record identifier; the country; the title as written, in its language and script; the issuing authority as named; the form; the official identifier and date of issue where the text states them; how it was found (point 2); the check of the right to obtain and retain its bytes, or that the right is unresolved; where the bytes are retained, how they were obtained, the SHA-256, and where they are kept; any flag for review under B7. Only fields that are safe and permitted to record are filled (point 2). |
| Reader decision | The items of point 5, one record for each reading of a document: one for each reader, or, with one reader, one for the first reading and one for the re-check |
| Reconciliation | The items of point 6 for one difference |
| Escalation | The document; the reason; the kind; the resolution and its date, or "unresolved" |
| Term gap | The list and its version; the term as written; the locator; false hit or missed term; the decision; the resulting version |
| Contextual entry | The items that §3.1.5 requires for contextual material |
| Withdrawal | The document; the reason; the date |

Record identifiers are local to the pilot records and carry no meaning. The format is fixed in detail when the first record is written, and it is versioned with the records. Its fields inform the record that Phase 2 will need (F-1), which is decided separately (§3.7, O-10).

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

An instrument is included in the core AI policy corpus if it passes the eligibility rules in §3.1, falls within the study period (§3.3), its origin can be identified, and it can be stored lawfully. Contextual material is recorded as set out in §3.1.5 and is not ingested by default. A document that is not an instrument is included under the same conditions of period, origin, and lawful storage when it is needed as evidence about a policy in the core corpus. Exclusions and their reasons are recorded (§3.1.6). The seed source list is an open item (blocker B9) and must be supplied and verified by the researcher. No source list is proposed here, because none has been verified.

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
- **Only the AI-related provisions of a broader instrument are coded** (§3.1.2). An AI-focused instrument is coded as a whole. The eligibility decision is not a coded value. §3.1 adds no category to the codebook and no classification of AI techniques: instrument types and sectors come from the codebook (B11).
- **Implementation is not coded as a policy event.** Funding, reported milestones, progress, and announcements of implementation are implementation evidence claims (§5), each with its source, source tier, independence, confidence, and review.
- A **codebook** defines each category and gives coding rules. It does not exist yet (blocker B11). The instrument typology and sector taxonomy must be chosen by the researcher, preferably adapted from an established scheme so results are comparable with other work.
- Every coded value links to the passage it was coded from.
- The codebook is versioned. Each coded record stores the codebook version used.
- Where two coders are available, a sample is coded independently and agreement is reported. Where only one coder is available, this is stated as a limitation and a re-coding check after a time interval is used instead.
- Whether coded policy records need their own review step before readers see them is undecided (blocker B23).
- AI-suggested policy coding is out of scope (§10).

## 7. Indicators

- Indicators are selected by the researcher to represent the three layers of economic transformation defined in §3.2, each indicator in one layer, with a recorded reason for each (blocker B12). No indicator list is proposed here, and none is selected before B22 is closed.
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

Causal inference about the effect of AI policy on economic outcomes. With two cases and no identified counterfactual, the design cannot separate the effect of a policy from everything else that differs or changes. The reasoning is set out in [LIMITATIONS.md](LIMITATIONS.md). For the same reasons, it does not support a conclusion that change in one layer of economic transformation (§3.2) caused change in another.

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
3. **Review.** A reviewer other than the author checks that the evidence supports the claim as worded, that the type is correct, and that the language rules are met. The claim and its evidence cannot be changed while it is in review. The text and evidence set as submitted are recorded with the review.
4. **Approval or return.** A returned claim goes back to draft and can be corrected and resubmitted; the returned submission, its evidence set, and the reviewer's decision stay on record. Approved claims become publicly visible, with any quoted source text shown only where the document's rights allow. Whether the assistant may use approved claims as evidence is undecided (blocker B24); until it is decided and its safety design ratified, the assistant does not use them.
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

The protocol is versioned in the repository. Changes that affect how claims are typed, evidenced, or reviewed are recorded with a date and reason, and existing claims are re-checked against the new rules where relevant. A change to §3.1, §3.2, or a terminology list is recorded in the same way. Eligibility decisions and indicator assignments made under the earlier version are re-checked where the change could alter them.

Change record:

- **2026-10-26.** §3.1 and §3.2 rewritten to record the working model for B22 that the project owner approved, with DRAFT operational rules and OPEN decisions. §3.4 to §3.6 added. The introduction, §2, §3.3, §4.2, §6, §7, §8, and this section aligned with them. Reason: the owner's approval of the working model. B22 remains open (§3.5). No claim, eligibility decision, or indicator exists yet, so nothing needed re-checking.
- **2026-10-26.** §3.7 and §3.8 added. §3.7 records the provisional pilot defaults that the project owner approved on 2026-10-26 for O-1 to O-3 and O-5 to O-10. O-4 stays open pending B20, and O-11 pending B8, with the constraints the revised questions must meet. §3.8 sets out the pilot of the eligibility rules and the format of its records. A PROVISIONAL mark was added. The status of each open point was added to §3.5, with a note on how provisional defaults relate to the closure conditions. F-5, F-8, and F-9 were made more specific, and F-11 to F-16 added. The introduction, §2, §3.1, §3.1.4, and §3.3 now refer to the new sections. §3.8 retains document bytes only after the right to obtain and retain them has been checked and recorded, and sends no document text to an AI or translation provider while B7's decision on transmission is open. Its comparison of two records covers both two readers and one reader's blind re-check. §3.5, F-9, and F-15 state that the closure conditions are DRAFT and need the owner's explicit confirmation, and what must be decided about B20 before B22 can close. Reason: the owner's approval of the defaults as the working basis for preparing the pilot. No OPEN point is decided, no closure condition is changed, and B22 remains open. No pilot has been run and no eligibility decision exists, so nothing needed re-checking.
