# Limitations

Status: Draft for researcher review · Last updated: 2026-10-01

Research title: **"AI Policy and Economic Transformation in Central Asia: A Comparative Analysis of Turkmenistan and Uzbekistan"**

This document states what the research design and the system cannot support. It is meant to be cited in any output of the project.

## A note on this document's own evidence

CAIPO holds no sources yet. This document therefore contains no established empirical fact about either country.

- Sections 1 and 2 describe limitations that follow from the **design**: two cases, observational data, documents as evidence. They are stated as logical consequences or as conditions ("if", "may"), not as findings.
- Section 3 lists **empirical concerns about the two countries and the subject**. Every item there is an unverified working assumption. Before any of them is repeated in a research output, it must be entered as a claim with evidence under the [research protocol](RESEARCH_PROTOCOL.md), or removed.

The rule is the project's own: an unsupported country-specific empirical statement is never presented as established fact, including here.

## 1. No causal inference

The project does not and cannot, under its current design, establish that AI policy caused any economic outcome. The reasons are properties of the design:

1. **Two cases.** With two countries there is no variation with which to separate the effect of one factor from everything else that differs between them.
2. **No counterfactual.** There is no observable version of either country without its policies, and the project has defined no comparison group.
3. **Simultaneous changes cannot be separated.** If policy adoption coincides with other reforms, price movements, or external events, the design has no means of separating their effects.
4. **Timing.** If a policy was adopted late in the study period, few observations follow it, and slowly responding indicators may not yet reflect anything.
5. **Scale.** If the activity a policy targets is small relative to the whole economy, changes in aggregate indicators cannot be attributed to it.
6. **Direction of influence.** Economic conditions may influence which policies are adopted, and a common cause may drive both policy adoption and economic change. The design cannot rule these out.
7. **Policy on paper versus practice.** Adoption of a text does not show that it was funded, staffed, or carried out.

What the project can support is description, structured comparison, observation of temporal association, and explicit reasoning about rival explanations.

## 2. Limitations of a two-country comparison

### 2.1 Evidence may be unequal

The volume, openness, and independence of available sources may differ between the countries. Where they do:

- A difference in the number of documented policies or implementation reports may reflect a difference in publication practice, not a difference in activity.
- A negative finding means less where less is published. Negative findings are always bounded by their recorded search.
- Every comparative statement must be read together with a statement of evidence availability on each side. The system shows coverage alongside comparisons for this reason.

### 2.2 Indicator comparability

- Statistical methods, definitions, base years, and revision practices may differ between national systems.
- Where an international provider fills a gap with an estimate, the estimate and a reported value are not equivalent. They are flagged separately.
- Gaps in series may not be random. Missing data may correlate with the thing being measured.
- Monetary comparisons depend on the exchange rate used. Where more than one rate exists, converted values can mislead.
- Per-capita values inherit any uncertainty in the population figures used.
- Short annual series give few observations. Statistical summaries of them are fragile.

### 2.3 Structural differences

Where two economies differ in size, population, sectoral composition, or openness, an indicator trajectory reflects those differences first. A comparison of levels is then rarely meaningful; comparison of direction and timing is more defensible but still confounded.

### 2.4 Undefined central concepts

Two concepts in the research title are not yet defined for this project (blocker B22):

- **"AI policy".** It has no settled boundary. A country may address AI in a dedicated strategy or within broader digital-economy or sectoral documents. The comparison is sensitive to where the boundary is drawn. The boundary is a research decision that must be stated and its effect examined.
- **"Economic transformation".** Until it is defined and tied to specific indicators, the project cannot say whether or how far it has occurred, and any choice of indicators shapes the answer. The definition and its alternatives must be stated.

### 2.5 Language and translation

- Sources are in several languages and scripts. Terms for the same concept may not correspond exactly across languages.
- Translated versions of official documents may differ from the original-language text.
- Researcher language coverage limits which sources can be read in the original.

### 2.6 Source independence

Where most available material comes from official sources, implementation claims rest largely on self-reporting. Independent corroboration may be limited or absent. Claims record the independence of their sources so that this is visible.

### 2.7 Source stability

Online sources can change, move, or become unreachable. Documents captured by the project are preserved, but documents never captured cannot be recovered, and the corpus reflects what was reachable at the time of collection from where it was collected.

### 2.8 Coding judgement

Classifying instruments, sectors, and objectives involves judgement. With few coders, agreement cannot be fully assessed. The codebook and the coded passages are published so that others can check.

### 2.9 Review independence

If the project has one researcher, claims are self-reviewed. This is labelled on each claim.

## 3. Empirical working assumptions (all unverified)

These are concerns to investigate, not findings. None has a source in CAIPO.

About the subject:

- AI-specific policies in one or both countries may be recent relative to any plausible study period.
- AI-related economic activity may be a small share of either economy.

About the two countries:

- The two economies may differ substantially in size, population, sectoral composition, and openness.
- The volume, openness, and independence of published sources may differ substantially between them.
- Publicly available official statistics may be considerably sparser for Turkmenistan than for Uzbekistan, and international databases may have more gaps or more estimated values for it.
- The reliability of some official macroeconomic figures may have been questioned by international institutions.
- An official exchange rate may diverge from market rates in one of the countries.
- One economy may be substantially more dependent on hydrocarbon exports.
- Uzbekistan may have undergone broad economic reforms during the likely study period, which would be a major confounder for any indicator change there.
- Population estimates for one of the countries may be contested.
- The accessibility of official websites from outside the country may be inconsistent.
- National statistical methods, base years, and revision practices may differ between the two.

Each item needs a source, a date, and a claim record before use.

## 4. Limitations of the system

### 4.1 Corpus

- The corpus is selected by researchers, not exhaustive. It reflects their search and inclusion decisions.
- Text extraction is imperfect, especially for scanned documents, tables, and multi-column layouts. Extraction quality is recorded per document; low-quality extractions limit both search and citation.
- A passage is verified against the stored extracted text. If extraction misread the original, the passage faithfully reproduces the misreading.
- An uploaded document's origin is the uploader's statement unless the system has corroborated it.

### 4.2 Retrieval

- Search quality has not been measured for any corpus language (blocker B15). It may be uneven across languages. No claim is made here about which languages are better served.
- A relevant passage that is not retrieved cannot inform an answer. The assistant's silence on a point is not evidence that the corpus is silent on it, and it is not a negative finding.
- Documents whose rights do not permit transmission to an external AI provider are not available to the assistant.

### 4.3 AI assistant

- Verification checks that an answer is supported by its cited passages. It does not check that the passages are true.
- Automated support checks have an error rate. Some unsupported statements may pass and some supported ones may be removed. The rates are measured in evaluation, per language, and reported.
- The support-check model reads the same retrieved text as the answer model and can be manipulated by it.
- A statement written in a different language from its source is an AI translation or paraphrase and may be inexact. It is labelled.
- The assistant can reproduce a source's framing or bias. Attribution to the source makes this visible but does not remove it.
- Language model output is not deterministic. The same question may yield differently worded answers. Each answer is logged, but it cannot be regenerated identically.
- Models and their behaviour change over time. Evaluation results apply to the recorded model version only.
- The assistant does not replace reading the sources.

### 4.4 Reproducibility

- External data providers revise their data. The project preserves the releases it imported but cannot guarantee a provider still serves them.
- Documents under copyright may not be redistributable, so an external party may need to obtain them independently, using the recorded hashes to confirm they have the same file.
- Content removed under the redaction procedure is no longer available for checking. Its former existence, hash, and the reason for removal remain on record.

## 5. How limitations are surfaced

- Comparative views show evidence coverage for each country.
- Indicator views show missing values, estimate flags, provider, and release.
- Assistant answers carry a standing notice that they are AI-generated synthesis, attribute each statement to its source, show uncertainty flags, and state when evidence was insufficient.
- Claims under reassessment are shown as such.
- Exports include this document's version.
