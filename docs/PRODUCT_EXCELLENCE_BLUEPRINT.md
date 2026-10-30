# Product Excellence Blueprint

Status: Proposal for owner and researcher review · Last updated: 2026-10-30

This document proposes the product CAIPO should become: who it serves, what they can do with it, how it looks and behaves, how it earns trust, and in what order it should be built. **It is a proposal. It authorises no implementation, decides no blocker, accepts no ADR, and changes no requirement.** Where it recommends something that would change an existing document or decision, it says so and lists the change in the owner decision register (§9) instead of making it.

Where this document and a binding document disagree, the binding document governs: [CLAUDE.md](../CLAUDE.md), [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md), [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md), [DATA_MODEL.md](DATA_MODEL.md), [ARCHITECTURE.md](ARCHITECTURE.md), [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md), [SECURITY.md](../SECURITY.md), [RIGHTS_AND_LICENSING.md](RIGHTS_AND_LICENSING.md), and the Accepted ADRs. Names of entities, roles, workers, and states are those of [DATA_MODEL.md](DATA_MODEL.md).

## How to read this document

Every statement here is one of five kinds. Sections and tables mark which.

| Mark | Kind | Who can change it |
|---|---|---|
| **[Fact]** | Verified repository fact, with the file it comes from | Nobody, except by changing that file |
| **[Observed]** | A feature of another platform, observed on its public pages on the stated date | Nobody; it may be out of date |
| **[Rec]** | Product or design recommendation made by this document | The project owner, by accepting or rejecting it |
| **[Eng]** | Technical question engineering can assess by measurement or a spike | Engineering, then the owner through an ADR |
| **[Owner]** / **[Research]** / **[Rights]** | A decision the project owner, the researcher, or a competent rights reviewer must make | Only that person |

Nothing in this document is a research finding. It contains no statistic, source, quotation, document title, or date about Turkmenistan, Uzbekistan, or any other country. All examples are visibly synthetic: country `XA` and `XB`, titles starting with `TEST`. The only country-related content is §2's record of what other platforms' pages showed on one date, including their URLs; those are observations of the platforms, not evidence about any country, and must not be cited as such.

## Contents

1. [Executive product vision and positioning](#1-executive-product-vision-and-positioning)
2. [Competitive benchmark](#2-competitive-benchmark)
3. [Information architecture and primary user journeys](#3-information-architecture-and-primary-user-journeys)
4. [Visual direction and design-system principles](#4-visual-direction-and-design-system-principles)
5. [Evidence, provenance, and AI trust contract](#5-evidence-provenance-and-ai-trust-contract)
6. [Phased roadmap](#6-phased-roadmap)
7. [Product and engineering quality metrics](#7-product-and-engineering-quality-metrics)
8. [Non-goals and risk register](#8-non-goals-and-risk-register)
9. [Owner decision register](#9-owner-decision-register)
10. [Prioritised next-action plan](#10-prioritised-next-action-plan)
11. [Repository state this proposal was written against](#11-repository-state-this-proposal-was-written-against)

---

## 1. Executive product vision and positioning

### 1.1 Vision

**[Rec]** CAIPO should be the place where a researcher can check, sentence by sentence, what is documented about AI policy and economic change in the countries it covers, and see exactly where the documentation stops.

Its unit of value is not a dashboard, a score, or a summary. It is a **traceable statement**: a typed claim, or a recorded observation, that resolves in two clicks to the exact span of the exact version of the exact file it rests on, with that file's provenance, rights, language, and review history visible, and with what is missing stated as plainly as what is present.

### 1.2 What CAIPO is for, in the project's own terms

**[Fact]** CAIPO supports one study, *"AI Policy and Economic Transformation in Central Asia: A Comparative Analysis of Turkmenistan and Uzbekistan"*, and is designed so other Central Asian countries can be added by data entry only ([PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §1, §6, NFR-08). It holds documents, structured policy records, indicators, and typed claims with evidence, and keeps them connected (§1). Its research design supports description, structured comparison, observation of temporal association, and explicit reasoning about rival explanations, and does not support causal inference ([LIMITATIONS.md](LIMITATIONS.md) §1).

The product vision has to fit inside those limits. It is therefore a vision of a **comparative evidence record**, not of an index, a ranking, or a forecast.

### 1.3 Who it serves

**[Fact]** The access model is three surfaces and four roles, decided in [ADR-0007](adr/0007-authentication.md).

| Audience | Surface | Primary need **[Rec]** |
|---|---|---|
| Anonymous visitor: other researchers, students, journalists, policy staff | Public research site | Read and cite approved claims and public records; check them against their evidence |
| Reader | Research workspace | Browse approved content, compare, ask the assistant within quota |
| Researcher | Research workspace | Build the evidence base: register sources, submit documents and datasets, code policies, record searches, draft claims |
| Reviewer | Research workspace | Approve documents, set rights, approve or return claims, suspend versions |
| Administrator | Administration | Accounts, roles, configuration, operations, redaction |

**[Rec]** The design centre is the **checking reader**: someone who did not write the claim, may not read every corpus language, and wants to know within a minute whether a statement holds up and what it rests on. A design that serves the checking reader also serves the Reviewer, whose job is the same check done formally.

### 1.4 Positioning

**[Rec]** CAIPO should position itself by what it lets a reader verify, not by its size or its novelty. Proposed positioning statement:

> CAIPO is a research record of AI policy and economic indicators for the Central Asian countries it covers. Every public statement is typed, reviewed, and linked to the exact passage or data release it rests on, in the original language, with gaps and limitations shown alongside.

It must not describe itself as the first, only, largest, most complete, or best platform of its kind. No such claim has been verified, and §2 shows several platforms with broader coverage.

### 1.5 Differentiators

**[Rec]** These are what CAIPO can credibly offer. Each follows from a decision already in the repository; none is a new capability.

| # | Differentiator | Rests on | Why it is hard to reproduce without sustained research quality |
|---|---|---|---|
| D1 | **Span-level evidence.** Statements resolve to a Passage in a Segment of a DocumentVersion, not to a document or a link. | ADR-0005 principles 4, 5; DATA_MODEL §3.3 | Every Passage is selected and reviewed by a person who read the source. That labour, not the software, is the asset. |
| D2 | **Typed statements.** Seven claim types keep a documented fact, a stated objective, reported implementation, an observed outcome, a correlation, an interpretation, and a negative finding apart, with evidence rules per type. | RESEARCH_PROTOCOL §5; I-5 | The taxonomy only has value if reviewers apply it consistently over years. |
| D3 | **Objective, implementation, and outcome kept separate.** A policy objective is never shown as evidence of implementation, and implementation never as evidence of outcome. | RESEARCH_PROTOCOL §5 rules 1–3, 7 | Requires source-by-source judgement of tier and independence. |
| D4 | **Recorded absence.** "No qualifying source was found in [universe] as of [date]" is a reviewed claim evidenced by a SearchRun, not silence. | ADR-0005 principle 7; FR-34 | A credible negative finding needs a documented, repeatable search by someone who reads the languages searched. |
| D5 | **Original-language authority.** The original text is authoritative; translations are labelled versions; machine translation is a reading aid and is never cited. | RESEARCH_PROTOCOL §4.4 | Needs readers of Turkmen, Uzbek in both scripts, Russian, and English. |
| D6 | **Versioned sources and data.** Every change to a captured document is a new version; every provider revision is a new DatasetRelease; nothing is overwritten. | FR-03, FR-21; ADR-0005 | The history only exists if capture starts early and continues. |
| D7 | **Evidence coverage shown with every comparison.** A comparison of two countries always shows how much evidence exists on each side. | LIMITATIONS §2.1, §5 | Coverage is only meaningful when the search behind it is recorded. |
| D8 | **An assistant that can only cite what it retrieved, and abstains otherwise.** | AI_ARCHITECTURE §1, §6, §7 | The guarantee is structural, but its usefulness depends on a reviewed, rights-cleared corpus and a per-language evaluation set. |

D1 to D7 are available without any AI. **[Rec]** The product should be valuable, and should launch publicly, without the assistant. D8 is an addition, not the foundation.

### 1.6 What CAIPO deliberately is not

**[Rec]** Not an index or ranking of countries. Not a readiness score. Not a news aggregator. Not an automated crawler. Not a forecasting or causal-estimation tool. Not a chatbot. §8.1 lists the full non-goals and §2.4 the rejected ideas.

---

## 2. Competitive benchmark

### 2.1 Method and limits

- Platforms were examined through their public pages on **2026-10-25**. What is reported is what those pages showed on that date, quoted or paraphrased closely. Where a page did not describe a feature, this document says "not described on the page examined", never "lacks".
- Pages were read through an automated fetch that converts a page to text. Interactive content that loads only with scripts may not have been visible. A feature reported as not described may exist.
- No platform was used as a logged-in user. No data was downloaded.
- Observations about another platform's coverage of a country are observations of that platform's page. **They are not evidence about the country**, and CAIPO must not cite them as such. In CAIPO's own terms, a page showing no entries is at most an input to a recorded search, not a negative finding.

### 2.2 Observations

#### OECD.AI Policy Navigator

Sources: [overview](https://oecd.ai/en/dashboards/overview), [all initiatives](https://oecd.ai/en/dashboards/policy-initiatives), an [initiative detail page](https://oecd.ai/en/dashboards/policy-initiatives/digital-uzbekistan-2030-3968), and country pages for [Uzbekistan](https://oecd.ai/en/dashboards/countries/Uzbekistan), [Kazakhstan](https://oecd.ai/en/dashboards/countries/Kazakhstan), and [Turkmenistan](https://oecd.ai/en/dashboards/countries/Turkmenistan). Accessed 2026-10-25.

**[Observed]**

- Describes itself as "a central resource of public AI policies and initiatives", drawing on "more than 80 jurisdictions and organisations", and "a live database updated regularly". Entries are maintained by "official contact points from countries and international organisations and OECD.AI experts". "Users can see who submitted or updated each entry and when."
- The list page showed "List of policy initiatives (2580)", with filters for country or territory, international organisation, category, status ("Proposed or under development", "Active", "Inactive – initiative complete", "Inactive – initiative not initiated"), legally binding, start year, type, AI Principles, target sectors, AI tags, and a search box; and sorting by name, start year, and last updated.
- The initiative detail page examined showed: name in original language, overview, responsible organisation, category, initiative type, status, start year, binding, target sectors, OECD AI Principles, other relevant URLs, an "Official PDF" link, and "Added by / Added on", "Updated by / Updated on". It showed a descriptive overview and metadata; it did not show quoted passages or provisions from the source text. No evaluation or monitoring field appeared.
- No export or download control was visible on the list page examined.
- Country pages exist for the three Central Asian countries checked. The Turkmenistan page displayed "It seems there are no initiatives to display." (See §2.1 on what that does and does not mean.)

#### UNIDIR AI, Peace and Security Portal

Sources: [aipolicyportal.org](https://aipolicyportal.org/), [its database page](https://aipolicyportal.org/database), the [launch event page](https://unidir.org/event/empowering-ai-policy-introducing-the-unidir-artificial-intelligence-policy-portal/). Accessed 2026-10-25.

**[Observed]**

- The site is titled "AI, Peace and Security Portal", from UNIDIR, alongside UNIDIR's cyber and space portals. It offers a language selector with Arabic, Chinese, English, French, Russian, and Spanish, and sections named Database, Map, Compare, and Search, plus a "Submission survey".
- The launch event page (15 May 2023) states that the portal covers "policies, processes, and structures related to the development and use of AI in military contexts", assembled "from national, regional, and international sources", and is "designed to foster transparency, information sharing, confidence, and capacity-building".
- The Database page displayed "Under construction" on the date of access.

#### Stanford HAI AI Index

Sources: [2026 AI Index Report page](https://hai.stanford.edu/ai-index/2026-ai-index-report), [Global AI Vibrancy Tool](https://hai.stanford.edu/ai-index/global-vibrancy-tool). Accessed 2026-10-25.

**[Observed]**

- The 2026 report page lists nine chapters, including Economy and Policy and Governance, a full PDF, a translation, and a link labelled "Access the Public Data" to a shared folder.
- The Global AI Vibrancy Tool is an "interactive visualization that facilitates cross-country comparisons of AI vibrancy". It ranks 36 countries, offers data over time for 66, and states that "users are welcomed to adjust the weights of both pillars and indicators". The page did not name the countries.

#### Other platforms found relevant

**[Observed]**

- **UNESCO Global AI Ethics and Governance Observatory** ([unesco.org/ethics-ai](https://www.unesco.org/ethics-ai/en), accessed 2026-10-25): "Country Profiles capturing detailed and comprehensive snapshots of the sociotechnical landscape of AI across countries", drawing on public data and, for countries that completed it, the Readiness Assessment Methodology; a meta-analysis of 55 national RAM reports. The page did not list which countries have profiles.
- **Global Index on Responsible AI, 2nd edition** ([arXiv:2608.18122](https://arxiv.org/abs/2608.18122), submitted 16 July 2026, accessed 2026-10-25): a composite index whose methodology describes "strengthening the distinction between framework existence and implementation", primary data from 135 country-level researchers through "a structured global survey", and "a multi-stage review and validation process".
- **Digital Policy Alert** ([about page](https://digitalpolicyalert.org/about), accessed 2026-10-25): "a public repository of policy changes affecting the digital economy", run by a Swiss non-profit, covering "50+ jurisdictions", which says it "provide[s] a link to the official source so you can independently verify the details", with notifications and an API under its terms.

### 2.3 What the platforms examined already do well

**[Rec]** Inferred from the observations above. CAIPO should learn from each and should not compete with any on its own terms.

| Strength observed | Where | Lesson for CAIPO |
|---|---|---|
| Breadth: many jurisdictions in one consistent schema | OECD.AI, UNIDIR, UNESCO, AI Index | CAIPO will not match breadth and should not try. Its schema must still map cleanly onto common categories so its records can be compared with these. |
| Per-entry accountability ("Added by", "Updated by", dates) | OECD.AI | CAIPO already records more (append-only events, reviewers). It should show it as plainly. |
| Link to the official source | OECD.AI, Digital Policy Alert | CAIPO goes further: a captured, hashed copy and an exact span. The interface must make that difference obvious, not bury it. |
| Faceted filtering by status, instrument, sector, year | OECD.AI | Adopt the interaction pattern. Facet values come from the codebook (B11), not invented. |
| Multilingual interface | UNIDIR (six UN languages) | CAIPO launches in English by decision (ADR-0010 point 9). Russian is a plausible later interface language for the region; that is an owner decision (§9, P-9). |
| Separating framework existence from implementation | GIRAI 2nd edition | Confirms CAIPO's objective / implementation / outcome separation. CAIPO makes the separation per statement, with evidence, rather than as an index variable. |
| Published data alongside a report | AI Index | CAIPO's exports must carry provenance and a manifest (FR-60, FR-61), subject to B7. |
| Tracking changes over time with official sources | Digital Policy Alert | CAIPO's version model (FR-03) supports this per document, without automated crawling (spec §2, out of scope). |

### 2.4 Problems that remain for researchers of Central Asian AI policy

**[Rec]** These are needs this project is designed around. They are stated as needs, not as findings about any country. Where they depend on empirical conditions, those conditions are the project's own **unverified** working assumptions in [LIMITATIONS.md](LIMITATIONS.md) §3, which must be evidenced before they are repeated as facts.

1. **Checking a statement against the text.** On the platform pages examined, entries offered a description and a link. A researcher who wants to verify what a document says still has to obtain the document, find the provision, and read it in its language. CAIPO's Passage model addresses exactly this step.
2. **Telling a stated aim from a reported result.** A record that a strategy exists does not say whether anything happened. Researchers need the separation of D3, with each source's tier and independence visible.
3. **Knowing what was searched when nothing was found.** An empty country page on an aggregator cannot be distinguished from a gap in that aggregator's collection. Researchers need recorded, dated, bounded searches (D4).
4. **Reading across Turkmen, Uzbek in two scripts, Russian, and English.** If sources differ in language and translation status (an assumption to be tested), researchers need the original, its translation status, and any reading aid kept visibly apart (D5).
5. **Comparing two countries whose evidence may be unequal.** If publication practice differs between the countries (LIMITATIONS §3, unverified), a count of documented policies may reflect publication rather than activity. Researchers need coverage shown next to every comparison (D7).
6. **Indicators with gaps, estimates, and revisions.** Researchers need missing values left missing, estimates flagged, and the release named (FR-22, RESEARCH_PROTOCOL §7).
7. **Documents that change or disappear.** Researchers need the captured copy and its versions, not only the live link (RESEARCH_PROTOCOL §4.3).

### 2.5 Ideas rejected

**[Rec]** Each looks attractive and would weaken the research record.

| Idea | Why rejected |
|---|---|
| A composite "AI readiness" or "policy maturity" score per country | It is a research method with weights, not a neutral display. The protocol defines none, and two cases cannot validate one. Adding one needs a protocol amendment. |
| User-adjustable weights for a ranking | Same as above, and it invites selective presentation. |
| Choropleth world or regional map as the home page | Two to five countries carry little information on a map, area encodes land size not evidence, and a map of a sensitive region is easily read politically. A list of country profiles serves better. |
| Headline counters ("1,234 documents") | A count of holdings invites reading volume as activity, which LIMITATIONS §2.1 warns against. A count appears only next to the records it counts and the coverage of the search behind them. |
| Dual-axis charts of a policy event and an indicator | Visually asserts a relationship. FR-42 forbids connecting annotations and fitted lines. Events and indicators share a time axis in separate panels instead (§4.6). |
| Interpolated or smoothed lines across missing years | Contradicts FR-22 and RESEARCH_PROTOCOL §7. |
| Sentiment analysis, word clouds, topic models of the corpus | Unvalidated in the corpus languages, not evidence of anything in the protocol's taxonomy. |
| AI-generated country summaries or "key takeaways" | Would be interpretation by a model, which AI_ARCHITECTURE §7.3 forbids; and it would sit on the page as if reviewed. |
| Streaming assistant answers | Forbidden: only verified output is displayed (ADR-0010 point 8). |
| Animated globes, particle backgrounds, scroll-driven animation | Decoration that slows reading and harms accessibility. |
| Automated monitoring of government websites | Out of scope (spec §2): no crawling without a Researcher in the loop. |
| Public comment threads on claims | Moderation burden and abuse exposure with no research value. A correction route by private report is proposed instead (§3.4, J5). |

---

## 3. Information architecture and primary user journeys

### 3.1 Principles

**[Rec]**

1. **One permanent URL per public record**, built on its public identifier, with a "How to cite" block (NFR-14, ADR-0010 point 7). The identifier never changes; the page can.
2. **Every record page answers the same five questions in the same place:** what is this, what kind of statement or record is it, what does it rest on, who checked it and when, and what is missing or uncertain.
3. **Navigation follows evidence, in both directions.** From a claim down to its Passage, Segment, version, artifact, and source; and from a source up to every claim that uses it.
4. **The public site and the workspace share one page grammar.** The workspace adds actions and drafts, never a different layout for the same record.
5. **Public pages work without JavaScript.** HTMX and small scripts enhance; they are never required to read (NFR-14, ADR-0010 point 7).

### 3.2 Sitemap (proposed)

**[Rec]** Paths are illustrative. Only the paths already built exist today (§11). `{id}` is a public identifier.

**Public research site** (anonymous visitors; also readable when signed in)

| Path | Page | Shows |
|---|---|---|
| `/` | Home | What CAIPO is, its scope and limits, entry points by country and by question. No counters. |
| `/countries/` | Countries | One entry per country with an evidence coverage summary |
| `/countries/{id}/` | Country profile | Policies with derived status, policy timeline, indicators, approved claims by type, coverage and gaps |
| `/policies/` | Policy browser | Filterable list of policies |
| `/policies/{id}/` | Policy | Formal events with their Passages, objectives, instruments, sectors, linked documents, related claims |
| `/compare/` | Comparison | Side-by-side policies or indicators for chosen countries and period, with coverage |
| `/documents/{id}/` | Document | The work, its versions, languages, translation status |
| `/documents/{id}/versions/{id}/` | Document version | Provenance, rights, review, extraction, segments where rights allow |
| `/passages/{id}/` | Passage | The exact span, in context where rights allow, and every claim citing it |
| `/claims/` | Claim browser | Approved claims, filterable by type, country, confidence, status |
| `/claims/{id}/` | Claim | Text, type, confidence and rationale, evidence, review record, status notices |
| `/indicators/{id}/` | Indicator | Definition, unit, series by country and provider, releases |
| `/releases/{id}/` | Dataset release | Provider, label, retrieval time, observations, withdrawal events |
| `/searches/{id}/` | Search run | Query, universe, criteria, sources examined, outcome, date |
| `/sources/{id}/` | Source | Publisher, source tier, independence notes, documents |
| `/institutions/{id}/` | Institution | Names over time, parent and successor, related policies. Public registry pages are deferred by ADR-0018 point 15 and need an owner decision (§9, P-10). |
| `/method/` | Method | Research protocol summary, epistemic taxonomy, source tiers, limitations, codebook version |
| `/cite/` | Citing CAIPO | How to cite records and snapshots |
| `/data/` | Data releases | Published snapshots with manifest and checksum, once B7 allows |

**Research workspace** (Reader, Researcher, Reviewer, by permission)

| Path | Page | For |
|---|---|---|
| `/workspace/` | Workspace home | The account's own drafts, review queue, recent ingestion requests |
| `/workspace/sources/` | Sources | Register a source and its allowed hosts (Researcher; host changes Reviewer) |
| `/workspace/ingest/` | Ingestion | Submit a URL or a file; list requests with their state and stage |
| `/workspace/review/documents/` | Document review | Reviewer queue of versions awaiting review, with rights determination |
| `/workspace/documents/{id}/versions/{id}/read/` | Reader view | Full text where workspace display is allowed; passage selection |
| `/workspace/coding/` | Policy coding | Code policies, events, objectives, instruments from Passages |
| `/workspace/searches/new/` | Record a search | Create a SearchRun |
| `/workspace/claims/` | Claims | Draft, submit, revise |
| `/workspace/review/claims/` | Claim review | Reviewer queue; approve or return; reassessment queue |
| `/workspace/assistant/` | Assistant | Ask a question; view verified answers and their evidence |
| `/workspace/exports/` | Exports | Build an export with provenance and manifest |
| `/registry/`, `/registry/entry/` | Registry | **Exist today** (§11) |

**Administration** (Administrator at `MFA_VERIFIED`)

| Path | Page |
|---|---|
| `/administration/accounts/`, `/administration/recoveries/`, and the enrolment and recovery request pages | **Exist today** (§11) |
| `/administration/roles/`, account disable and enable | Services exist, no page (SECURITY.md) |
| `/administration/audit/` | Reading the audit record: deferred (ADR-0018; finding I4) |
| `/administration/redaction/` | Redaction procedure (DATA_MODEL §7) |
| `/administration/operations/` | Stuck ingestion requests, attempt limits, AI budget use |

### 3.3 Which surfaces in which release

**[Rec]** The three surfaces do not need to arrive together.

| Surface | Earliest useful form | Blocked by |
|---|---|---|
| Research workspace | Ingestion and document review (Phase 2) | B4, B7, B8, B9, B10, B21, B22 |
| Administration | Already partly built; grows with each phase | Per feature |
| Public research site | Approved claims with their evidence references, and public records metadata | B7 (rights policy and project-data licence), at least one phase of approved content (Phase 4), and an owner decision on timing (§9, P-2) |

The current phase table puts comparative views and export in Phase 6 ([PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §7). This document does not change that. It recommends, as an option for the owner, a **minimal public site** after Phase 4 that shows approved claims, their evidence references, and policy records, before the full comparison and export work of Phase 6 (§9, P-2).

### 3.4 Primary user journeys

Each journey states its goal, required information, proposed interface, failure states, trust requirements, accessibility needs, and acceptance criteria. "Page condition" names an interface situation (empty, loading, and so on, §4.7); it is not a record state, and record states are only those of DATA_MODEL §4.

#### J1. Discover AI-related policy across the initial countries

| Aspect | Proposal **[Rec]** |
|---|---|
| Goal | Find which policies within the project's policy domain are recorded for each country, and how they can be filtered |
| Required information | Policy, country, lead institution, policy type, derived formal status (DATA_MODEL §4.4), formal events with dates, sectors and instrument types from the codebook, linked documents, codebook version |
| Prerequisite | **B22** defines the policy domain. Until then "AI-related policy" has no fixed meaning in this project ([RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md) §3.1), and the browser must say which definition and codebook version it uses. |
| Interface | Policy browser: a table, one row per policy, with facets for country, derived status, sector, instrument type, and year of formal events. A plain-language note above the table states the domain definition in force and links to it. Each row links to the policy page. |
| Failure states | No policy recorded for a filter: say so and show the coverage of that country (what was searched, with SearchRun dates), never "none exists". Codebook not yet written (B11): facets that depend on it are absent, with a note. |
| Trust | Derived status computed, never stored (I-14). Status shown with the event that produces it. Domain definition and codebook version on the page. |
| Accessibility | A real `<table>` with `<caption>`, `<th scope>`, sortable columns announced by `aria-sort`; facets as a form that works without JavaScript; result count announced politely on update. |
| Acceptance | (a) Every row's status matches a recomputation from its PolicyEvents. (b) An empty result names the countries and filters and links to coverage. (c) The page passes the prohibited-wording check. (d) Works with JavaScript off. |

#### J2. Open a country profile and understand its policy landscape

| Aspect | Proposal **[Rec]** |
|---|---|
| Goal | Understand, for one country, what is documented, in what kinds of statement, and where the documentation is thin |
| Required information | Country record; policies with derived status; formal event timeline; indicator series with coverage; approved claims grouped by type; negative findings with their search dates; evidence coverage summary |
| Interface | Sections in fixed order: **About this profile** (scope, period, last review date); **Policies** (compact list with status); **Formal events** (timeline, §4.6); **What is documented** (approved claims by type, one tab per type, with counts only inside each tab); **Indicators** (small multiples with missing years visible); **Coverage and gaps** (sources searched, negative findings with "as of" dates, languages not yet covered). Each section links to the full browser filtered to this country. |
| Failure states | Profile with almost no approved content: shown honestly as "in progress", with what has been searched. A section with no content says why (not yet coded, not yet searched, nothing qualifying found as of a date). |
| Trust | No country-level score, rank, or summary sentence. No model-written text. All claims shown with type, confidence, and review marker. Claims in `needs_reassessment` or `disputed` are not shown as approved (DATA_MODEL §4.3). |
| Accessibility | Headings form a logical outline; the timeline has a table equivalent; tabs are links to anchors that work without JavaScript. |
| Acceptance | (a) No element on the page states or implies a comparison with another country. (b) Every number shown links to the records it counts. (c) Coverage section present even when empty. (d) A synthetic third country `XC` renders with no code change (NFR-08). |

#### J3. Compare policy instruments across countries and periods

| Aspect | Proposal **[Rec]** |
|---|---|
| Goal | Put the same question to two or more countries and see the answers side by side, with evidence coverage on each side |
| Required information | Policies, instruments with InstrumentType, sectors, responsible institutions, formal events, period; coverage per country |
| Prerequisite | B11 (codebook), B22, B23 (whether coded records need review before readers see them) |
| Interface | Choose countries, period, and a dimension (instrument type, sector, institution). Result: one column per country, rows by category, each cell listing the coded records with links. A **coverage row** at the top of each column states what was searched and when. An evaluative sentence comparing columns is never generated. |
| Failure states | One country has no coded records for a category: the cell says "not recorded" and links to the relevant SearchRun if one exists; otherwise "not yet searched". Unequal coverage: a notice above the grid. |
| Trust | The comparison displays records, not conclusions. Interpretations of a difference are interpretation claims, written and reviewed by people, shown separately and labelled. |
| Accessibility | Grid is a table with country column headers; on narrow screens it becomes stacked sections per category with the countries in fixed order, never horizontal scroll of the page. |
| Acceptance | (a) Coverage row present for every column. (b) Empty cells distinguish "not yet searched" from "no qualifying source found as of D". (c) No ranking, ordering by count, or colour scale that implies better or worse. (d) Prohibited-wording check passes. |

#### J4. Inspect an individual document, its status, source, version, language, and provisions

| Aspect | Proposal **[Rec]** |
|---|---|
| Goal | Know exactly what this text is, where it came from, whether it is the original, whether it is current, and what it says at a given provision |
| Required information | Document (type, issuing institution, official identifier, date of issue, titles), versions (language, script, kind, text state), Artifact hash and size, AcquisitionRecords with origin verification (`observed`, `attested`, `corroborated`), DocumentReview status, current RightsDetermination, current Extraction (method, parser, quality warnings), Segments with locators |
| Interface | **Provenance strip** at the top (§4.5): version kind, language and script, review status, origin verification, extraction method, rights summary. Below, the text by Segment with locators in the margin, where rights allow display; otherwise the locators and metadata only. A **Versions** panel lists all versions with dates and a link to compare two versions' Segments. Original file download only where rights allow, as an attachment (SECURITY.md). |
| Failure states | Rights withhold display: "The text of this version is not displayed: [right] is not granted." with the reference kept (RIGHTS_AND_LICENSING §4). Version `suspended` or `withdrawn`: banner with reason and date; not citable. Extraction by OCR or with warnings: shown in the strip and next to each affected Segment. Origin `attested`: shown as "origin stated by the uploader, not verified by the system". |
| Trust | Hash and acquisition time always visible. Translation never presented as the original. Machine-translated reading aid, if any, is labelled, collapsed by default, and never selectable as a Passage. |
| Accessibility | `lang` attribute on every Segment by its version's language and script, so screen readers switch voices; locators as visible text, not only icons; text reflows at 400% zoom. |
| Acceptance | (a) Every field of the provenance strip resolves to a stored record. (b) No text shown where the relevant right is absent (tested per right). (c) `lang` set correctly for each corpus language and script. (d) An OCR extraction is never shown without its method label. |

#### J5. Trace an analytical claim to the exact evidence supporting it

| Aspect | Proposal **[Rec]** |
|---|---|
| Goal | Decide whether a claim holds up, by reading what it rests on |
| Required information | Claim text, type, confidence and rationale, origin, status, scope; Evidence items with stance and directness; each target (Passage with Segment context, Observation with release, AnalysisRun, SearchRun); ClaimReview record including self-review; ClaimRelations for interpretations |
| Interface | **Claim page**: the claim in large type, a **type badge** with words (never colour alone), confidence with rationale, status. Below, the **evidence ledger** (§4.5): one row per evidence item, grouped by stance (supports, contradicts, provides context), each showing the quoted Passage in its original language with locator, document title, source tier, and version, or the Observation with provider, release, and status flag. A **review record** shows who reviewed, when, and whether it was self-review (I-10; RESEARCH_PROTOCOL §9). Interpretation claims show the claims they build on and the alternatives they name. |
| Failure states | Claim in `needs_reassessment`: top banner "The evidence for this claim is under reassessment", the claim text kept, the cause named, excluded from comparisons (DATA_MODEL §4.3). `disputed` or `withdrawn`: banner with reason. Passage text withheld by rights: reference with locator and no text. |
| Trust | Every displayed reference resolves to a stored Passage or Observation (NFR-02). Correlation claims carry the standard non-causation notice and state observation counts (RESEARCH_PROTOCOL §5). A correction route: "Report a problem with this claim", leading to a private channel, not a public thread (§9, P-12). |
| Accessibility | Evidence ledger is a list with each item a labelled region; quote marked as `<blockquote lang="…">`; links have unique accessible names ("Passage 3 of 5: TEST Strategy, article 4"). |
| Acceptance | (a) No claim page renders a reference that does not resolve (tested with a deliberately broken link). (b) The status banner appears for every non-approved status. (c) Self-review is labelled whenever recorded. (d) Two clicks from claim to Passage in context. |

#### J6. Explore economic indicators with definitions, limitations, and missing data

| Aspect | Proposal **[Rec]** |
|---|---|
| Goal | See an indicator's values over time for one or more countries, knowing exactly what it measures, who published it, which release, and which values are missing, estimated, provisional, or projected |
| Required information | Indicator (definition, unit, category), IndicatorSeries (country, source, frequency, unit as published, methodological notes), DatasetRelease, Observations with status and footnotes, provider disagreements |
| Prerequisite | B22 (definition of economic transformation) and B12 (indicator list and licences) |
| Interface | **Definition first**, above the chart: what it measures, unit, provider, release. Then **small multiples**, one panel per country on a shared time axis and, where the unit allows, a shared value axis (§4.6), with a toggle to independent value axes clearly labelled. Below, the **data table** with every period, including missing ones, and status flags in words. Two providers for the same indicator and country are two series, shown separately, with the disagreement noted. |
| Failure states | Missing period: a visible gap and a "missing" cell; no line drawn across it. Release withdrawn: banner, values greyed and not used in comparisons. Licence does not permit public display: indicator listed with definition and provider, values withheld with the reason. |
| Trust | Values as published, exact decimals, no interpolation (FR-22). Release named on every chart. Small sample size stated ("n = 7 annual observations"). Currency conversions state method and series. |
| Accessibility | Every chart has the data table as its text alternative, adjacent and not hidden behind a control; patterns plus colour for status; keyboard-reachable data points not required because the table carries the data. |
| Acceptance | (a) No path from data to chart draws across a missing period. (b) Every chart names provider and release. (c) Table and chart agree value for value (test). (d) A withdrawn release never appears as current. |

#### J7. Ask an evidence-grounded research question and inspect the sources

| Aspect | Proposal **[Rec]** |
|---|---|
| Goal | Get a short, attributed, verified answer from the approved corpus, or a clear statement that the evidence retrieved was insufficient |
| Required information | As specified in [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md) §8: surviving statements, label, server-rendered attribution, references, uncertainty flags, evidence gaps, standing notice; for abstentions, what was searched |
| Prerequisite | Phase 5 and B14, B15, B16, B19, B24; ADR-0003 and ADR-0006 accepted |
| Interface | Workspace only, never public (ADR-0007). A question box with a short statement of what the assistant can and cannot do. While running: a stage indicator only ("Retrieving evidence", "Checking citations"), never model text (ADR-0010 point 8). Result: each statement as a card with its **assistant label** (one of four: Documented statement, Stated policy objective, Reported implementation, Recorded observation), attribution line rendered by the server, uncertainty flags in words, and references that open the Passage. A persistent **AI-generated synthesis** marker on the whole answer, visually distinct from reviewed claims (§4.4). |
| Failure states | `abstained`: "The evidence retrieved was not sufficient to answer. Searched: [filters, languages]." Explicitly not a negative finding. `refused`: fixed text. `failed`, `timed_out`: explicit message, nothing partial. Budget exhausted: "unavailable", never an ungrounded answer. |
| Trust | No reference without a handle issued in the request; quotes and numbers checked; cross-language statements labelled "AI translation or paraphrase of a source in [language]" and shown with the original; `language_not_evaluated` shown until a baseline exists. |
| Accessibility | Result inserted into a live region announced once complete; focus moved to the answer heading; labels and flags as text. |
| Acceptance | As AI_ARCHITECTURE §9, per language. In addition: (a) the AI marker is present on 100% of answers; (b) no assistant statement is ever rendered with a claim-type badge; (c) abstention page never uses the wording of a negative finding. |

#### J8. Export research results with provenance and reproducibility metadata

| Aspect | Proposal **[Rec]** |
|---|---|
| Goal | Take claims, evidence, and indicator data out of CAIPO in open formats, so a publication can cite and others can check |
| Required information | As [REPRODUCIBILITY.md](REPRODUCIBILITY.md) §11 and FR-60, FR-61: corpus manifest with hashes, redistributable text only, policy records with Passages, observations with release identifiers, claims with evidence, codebook, protocol and limitations versions, software commit |
| Prerequisite | B7 (redistribution rights, project-data licence); B12 for indicator licences |
| Interface | An export builder that shows, before building, what will be included and what will be withheld and why (rights per item). Output: a versioned bundle with a manifest and checksum; CSV with formula neutralisation (SECURITY.md); a human-readable README naming versions and limitations. |
| Failure states | Item not redistributable: included as a reference with hash and locator, without text. Claim in `needs_reassessment`: excluded from exports of approved claims (DATA_MODEL §4.3), listed in the README as excluded. |
| Trust | Export records its own parameters and software commit; the same parameters on the same data give the same bundle (deterministic order). |
| Accessibility | Builder is a standard form; the README is plain text. |
| Acceptance | (a) Formula neutralisation tested with each dangerous leading character. (b) No withheld text appears in any file of the bundle (tested). (c) Manifest hashes match stored artifacts. (d) Re-export with the same parameters is byte-identical apart from its timestamp field. |

#### J9. Detect and review changes to tracked policy documents

| Aspect | Proposal **[Rec]** |
|---|---|
| Goal | Learn that a captured document's source now serves different content, review the difference, and keep both versions |
| Required information | AcquisitionRecords for each fetch; Artifact hashes; DocumentVersions; Segment-level comparison of two extractions |
| Constraint | **[Fact]** Automated web crawling or monitoring without a Researcher in the loop is out of scope (spec §2). A re-fetch therefore starts with a Researcher. **[Rec]** A "re-check" action on a document, and a list of documents whose last acquisition is older than a chosen interval, give a Researcher what they need without monitoring. Scheduled re-fetching would change the specification and is an owner decision (§9, P-4). |
| Interface | Re-check submits an IngestionRequest for the same URL. Same hash: a new AcquisitionRecord on the existing Artifact, shown as "unchanged on [date]". Different hash: a new Artifact and DocumentVersion (FR-03), and a **version comparison** page that aligns Segments of the two current extractions and marks added, removed, and changed text. The approved version stays approved and citable; the new one awaits review. |
| Failure states | Source unreachable: request `failed` with `source_unreachable`, shown to the Researcher; the existing version is unaffected. Host no longer allowed: `host_not_allowed`. New version is a different language or translation: flagged for the Reviewer. |
| Trust | Nothing is overwritten. Claims citing the old version keep citing it. The comparison is a reading aid computed from stored Segments; it does not alter them (principle 4, DATA_MODEL §1). |
| Accessibility | Differences marked with text markers ("added", "removed") as well as colour; comparison readable as a linear list on narrow screens. |
| Acceptance | (a) A re-fetch with a different hash never modifies an existing DocumentVersion, Extraction, Segment, or Passage (test). (b) The comparison page states which two extractions it compares. (c) No re-fetch is started without a Researcher's action. |

---

## 4. Visual direction and design-system principles

### 4.1 Identity: a scholarly edition, not a dashboard

**[Rec]** CAIPO should look like a carefully typeset critical edition crossed with a statistical yearbook: generous margins, a reading measure for text, references in the margin, tables that read like tables, and a small, fixed visual vocabulary for kinds of statement. The reference points are print traditions (annotated legal editions, statistical annexes), not software dashboards.

What makes it distinctly CAIPO rather than an admin template:

1. **The margin carries the evidence.** On wide screens, references, locators, and provenance sit in a right-hand margin column aligned with the text they support, as in an annotated edition. On narrow screens they fold under each paragraph.
2. **Statement types are typographic, not decorative.** Each claim type and assistant label has a fixed short label in small capitals with a consistent mark (§4.4). A reader learns seven badges once and reads every page with them.
3. **The provenance strip** (§4.5) is the same on every record: one line of facts in a fixed order. It is the platform's signature element.
4. **Absence is drawn.** Missing data, withheld text, and unsearched areas have their own visible treatment (§4.6, §4.7). Nothing missing is ever blank space.
5. **Restraint.** One accent colour, no gradients, no illustrations of circuits or brains, no stock imagery of the region. The region appears through its languages and scripts set properly, not through ornament.

### 4.2 Typography

**[Rec]**

- **Reading text:** a serif for long text and quotations, a sans-serif for interface and tables, and a monospace for hashes and identifiers.
- **Scripts:** every chosen face must cover Latin with the Turkmen and Uzbek letters, and Cyrillic including the letters used in Uzbek Cyrillic and Russian. Coverage is tested with a synthetic specimen page before adoption, not assumed **[Eng]**.
- **Delivery:** start with system font stacks, which need no files and no dependency. A self-hosted web font is a later, separate decision with its licence checked and its files served from the application's own static files (§9, P-6). No font is loaded from a third-party host, consistent with the strict Content Security Policy (SECURITY.md).
- **Measure:** 60–75 characters for running text; quotations keep their original line breaks only where the Segment does.
- **Numbers:** tabular figures in tables; decimals aligned; units in column headers, not repeated in cells.
- **Scale:** a modest type scale (for example 1.2 ratio) so headings organise rather than shout.

### 4.3 Colour and tokens

**[Rec]**

- Colour is defined as named tokens in one stylesheet, with a light and a dark scheme following `prefers-color-scheme`. No token is used for meaning alone; every meaning also has a word or a pattern.
- Palette: near-black ink on warm off-white paper; one deep accent for links and focus; a muted secondary for metadata.
- **Countries are not given national colours or flags.** Countries in a comparison are distinguished by position and label, and where colour is needed, by a neutral categorical palette assigned in a fixed order from data, not by country code (CLAUDE.md, no country-specific code paths).
- Contrast: text and interface elements meet the contrast ratios of the accessibility target the owner sets (§9, P-1; recommended WCAG 2.2 AA). Checked with a script over the token pairs **[Eng]**.

### 4.4 The statement-type vocabulary

**[Rec]** The most important design system decision. Two separate families that must never be confused.

**Research claims** (reviewed by people; RESEARCH_PROTOCOL §5):

| Claim type | Badge text | Mark |
|---|---|---|
| `documented_fact` | DOCUMENTED FACT | solid square |
| `policy_objective` | POLICY OBJECTIVE | open square |
| `implementation_evidence` | IMPLEMENTATION EVIDENCE · tier X | square with a corner notch, tier shown |
| `observed_outcome` | OBSERVED OUTCOME | solid circle |
| `correlation` | CORRELATION | two linked open circles, with the non-causation notice always attached |
| `interpretation` | INTERPRETATION | open diamond, with "alternatives considered" always linked |
| `negative_finding` | NEGATIVE FINDING · as of D | dashed square, with the search date always visible |

**AI-generated synthesis** (never a research claim; AI_ARCHITECTURE §7.3):

| Assistant label | Badge text |
|---|---|
| Documented statement | AI · DOCUMENTED STATEMENT |
| Stated policy objective | AI · STATED POLICY OBJECTIVE |
| Reported implementation | AI · REPORTED IMPLEMENTATION |
| Recorded observation | AI · RECORDED OBSERVATION |

Rules: the AI family always carries the "AI" prefix and a distinct container (a ruled box with an "AI-generated synthesis" header); it never uses the research marks; it never appears on the public site. Review markers ("Reviewed by [role] on D", "Self-reviewed") appear only on research claims.

### 4.5 Signature components

**[Rec]** Reusable components, each a Django template include with fixed inputs. Names are proposals.

| Component | Purpose | Inputs (from selectors) | Rules |
|---|---|---|---|
| Provenance strip | One-line facts about a record | Version kind, language and script, review status, origin verification, extraction method, rights summary, hash prefix | Fixed order; every item a link to its record; withheld items shown as withheld |
| Statement badge | Type of statement | Claim type or assistant label | Text always present; mark decorative (`aria-hidden`) |
| Evidence ledger | Evidence behind a claim | Evidence items with stance, directness, target | Grouped by stance; contradicting evidence never collapsed below supporting |
| Passage quote | The exact span | Passage, Segment context, locator, language | Original language first; `lang` attribute; translation, if any, labelled and secondary; rights check before text |
| Reference without text | Rights-withheld evidence | Title, institution, date, locator, hash | Explains which right is missing |
| Status banner | Non-default record status | DocumentReview status, claim status, release withdrawal | Uses DATA_MODEL §4 status names in plain words; states cause and date |
| Coverage panel | Evidence availability | SearchRuns by country, languages covered, dates | Shown next to every comparison |
| Uncertainty flags | Server-derived flags on assistant statements | AI_ARCHITECTURE §8 flags | Words, not icons; ordered consistently |
| Formal event timeline | Policy lifecycle events | PolicyEvents with dates and Passages | Five event types only; no implementation on this axis |
| Indicator small multiple | One series per panel | Observations with status flags | §4.6 rules |
| Data table | Values behind a chart | Same as chart | Always adjacent to its chart |
| How to cite | Citation for a record | Public identifier, title, version, access date | Plain text, copyable; format per §9, P-7 |
| Page condition block | Empty, error, denied, stale, insufficient evidence | Condition and reason | §4.7 |
| Version comparison | Changes between versions | Two extractions' Segments | Text markers plus colour |

### 4.6 Data visualisation rules

**[Rec]**

1. **Small multiples over overlays.** One panel per country or series. Overlays only for two series of the same unit and provider, with a direct label on each line.
2. **Shared time axis, separate panels for events and indicators.** Formal policy events appear on their own row above indicator panels, as ticks with the event type. No line, shading, or annotation connects an event to an indicator movement (FR-42 (a)). The standard non-causation notice is shown (FR-42 (b)).
3. **Missing is drawn.** A missing period is a gap with a small "missing" mark on the axis. Lines never cross it.
4. **Status is encoded twice.** Reported values solid; estimated hatched or open; provisional dotted; projected with a distinct marker and, where shown at all, set apart from the reported range. Each with a legend in words.
5. **Small samples are stated.** The number of observations is printed on every panel.
6. **Axes are honest.** Bar charts start at zero; line charts may not, and say so when they do not. Independent value axes across panels are an explicit, labelled choice.
7. **No derived numbers without an AnalysisRun.** Growth rates, indices, ratios, and trend lines are shown only when they come from a recorded analysis, with a link to it (RESEARCH_PROTOCOL §7, §8).
8. **Rendering.** **[Eng]** Charts are first rendered on the server as inline SVG from templates, which needs no dependency and works without JavaScript. A chart library would need the dependency justification of CLAUDE.md rule 14 and a reason SVG templates cannot meet the need.

### 4.7 Page conditions

**[Rec]** Each has one component and one fixed wording pattern. "Condition" is used so as not to collide with the record states of DATA_MODEL §4.

| Condition | When | What the page shows |
|---|---|---|
| Empty | No records match | What was asked, the filters, and the coverage for that scope; never "none exists" |
| Not yet searched | No SearchRun covers the scope | "This has not been searched yet." Distinct from a negative finding |
| No qualifying source found | A negative-finding claim exists | The claim with its universe and "as of" date (RESEARCH_PROTOCOL §5) |
| Loading | An HTMX update or assistant run in progress | A stage label only; previous content stays readable; no partial model text |
| Error | A failure | What failed in plain words, that nothing was changed if so, and what to do; no traceback or internal detail (SECURITY.md) |
| Permission denied | 403 | As implemented after finding L1: sign-in for an anonymous visitor; the two-step verification hint where it applies; otherwise "no access" (SECURITY.md) |
| Rights withheld | A right is not granted | The reference without text, and which right is missing |
| Stale | A record has an "as of" date the reader should weigh: a negative finding, a release, a last acquisition | The date, prominently, and the age in plain words |
| Under reassessment | Claim `needs_reassessment` | Banner, cause, claim kept visible, excluded from comparisons |
| Suspended or withdrawn | DocumentVersion `suspended` or `withdrawn` | Banner, reason, date; not citable |
| Insufficient evidence | Assistant `abstained` | What was searched; explicitly "not a research finding" |
| Unavailable | Assistant provider or budget unavailable | "The assistant is unavailable." Browsing and search unaffected |

### 4.8 Layout and responsiveness

**[Rec]**

- **Wide (≥ 1200 px):** three zones: navigation and filters, the reading column, the evidence margin.
- **Medium (768–1199 px):** reading column with the margin folded under each paragraph; filters in a collapsible panel that is a plain form.
- **Narrow (< 768 px):** single column; tables become stacked records with labels; comparison grids become sections per category; no horizontal page scrolling.
- Focus indicators are thick, high-contrast outlines, never removed. Skip link to the main content. Motion limited to short opacity changes, disabled under `prefers-reduced-motion`.
- Every page prints cleanly: margins become footnotes, links print their target, and charts print with their tables.

### 4.9 Accessibility

**[Rec]** Target: WCAG 2.2 level AA for the public site and the workspace, as an owner decision (§9, P-1); NFR-14 currently says "accessible" without a level.

Specific needs from this corpus:

- Correct `lang` on every piece of corpus text, including both Uzbek scripts (BCP 47 tags such as `uz-Latn` and `uz-Cyrl`). **[Eng]** The Language record stores an ISO 639-3 code and an ISO 15924 script code (DATA_MODEL §3.2), and BCP 47 uses the two-letter code where one exists, so producing valid tags needs a recorded mapping, tested for each corpus language.
- Identical action buttons must have distinct accessible names (the diagnostic of 2026-10-20 §12 item 2 notes repeated "Deactivate" and "Mark as entered in error" buttons on the registry entry page).
- HTMX updates manage focus and announce results (ADR-0010 consequences).
- Charts always have adjacent tables (§4.6).
- Testing: automated checks plus manual keyboard and screen-reader passes per release **[Eng]**; any automated checker added to CI is a dependency and needs justification.

---

## 5. Evidence, provenance, and AI trust contract

### 5.1 The kinds of statement a reader must be able to tell apart

**[Rec]** Mapping of the categories asked for to the project's own types. The right-hand columns are the binding definitions.

| Reader-facing category | CAIPO representation | Evidence required | How it is shown |
|---|---|---|---|
| Primary-source fact | `documented_fact` claim, evidence a Passage from a tier A source where one exists | Passage (I-5) | DOCUMENTED FACT badge; source tier shown |
| Officially stated policy objective | `policy_objective` claim, or a PolicyObjective coded from a Passage | Passage in the policy text | POLICY OBJECTIVE badge; never near implementation without a label |
| Verified implementation evidence | `implementation_evidence` claim, with source tier and independence recorded | Passage from the reporting source | IMPLEMENTATION EVIDENCE badge with tier; "Source S reports…" wording. **Note:** the protocol does not use "verified" for implementation. An official statement is evidence that a statement was made (RESEARCH_PROTOCOL §4.1). The interface should say "reported", never "verified", for implementation. |
| Economic observation | `observed_outcome` claim, or Observation records | Observations with provider and release | OBSERVED OUTCOME badge; release and status flag |
| Statistical association | `correlation` claim | AnalysisRun | CORRELATION badge; method, period, n; non-causation notice |
| Researcher interpretation | `interpretation` claim | Linked claims; alternatives named | INTERPRETATION badge; alternatives always linked |
| AI-generated synthesis | AnswerStatement in an AIInteraction; never a claim | AnswerCitations to Passages or Observations | AI family badges and container; workspace only |
| Missing evidence | Absence of records; or `negative_finding` claim with SearchRun | SearchRun with `no_qualifying_source_found` | "Not yet searched" vs NEGATIVE FINDING · as of D |
| Conflicting evidence | Evidence with stance `contradicts`; ClaimRelation `contradicts`; two IndicatorSeries from different providers | As linked | Contradicting evidence shown with equal prominence; provider disagreement noted |
| Uncertain evidence | Confidence (high, moderate, low) with rationale on claims; uncertainty flags on assistant statements | Rationale | Confidence in words with its rationale; never a numeric probability |

### 5.2 Provenance that must be preserved and shown

**[Fact]** Already specified in DATA_MODEL §3 and ADR-0005. **[Rec]** What the interface must expose of it:

| Layer | Preserve (binding) | Show to the reader |
|---|---|---|
| Artifact | Bytes, SHA-256, size | Hash (prefix with full on demand), size, acquisition dates |
| AcquisitionRecord | Method, URLs, redirect chain, status, time, actor, origin verification | Observed / attested / corroborated, in words; final URL; time |
| DocumentVersion | Language, script, kind, text state | Original or translation, official or unofficial; as adopted or consolidated to a date |
| DocumentReview | Event history | Current status and its date; history on request |
| RightsDetermination | Six rights, basis, actor, time | Which uses are allowed, in words; basis summary |
| Extraction | Parser, version, configuration, method, quality, content flags | Method (embedded text, OCR, mixed), quality warnings |
| Segment and Passage | NFC text, locator, offsets, hash | Text where rights allow, locator always |
| DatasetRelease and Observation | Provider label, retrieval time, raw artifact, status, footnotes | Release on every value; status in words |
| ClaimReview | Submitted text and evidence set, reviewer, decision, self-review | Reviewer role and date; self-review label; history |

### 5.3 How citations resolve

**[Rec]** A reference on any page is rendered by the server from a Passage or an Observation and nothing else (NFR-02). It resolves as:

```
Claim  →  Evidence item  →  Passage  →  Segment (locator)  →  Extraction  →  DocumentVersion  →  Artifact (hash)  →  AcquisitionRecord(s)  →  Source
                          →  Observation  →  IndicatorSeries  →  DatasetRelease  →  Artifact (hash)
                          →  AnalysisRun (inputs, method, code version, output hash)
                          →  SearchRun (query, universe, criteria, sources examined, outcome, date)
```

Each arrow is a link on the page. A reader reaches the Passage in context in two steps from the claim and the stored artifact's provenance in at most four.

### 5.4 Corrections and historical versions

**[Fact]** Corrections create new records (CLAUDE.md rule 7; ADR-0005 principle 12). **[Rec]** The interface shows them as:

- **A superseded claim** links forward to its successor and is marked "superseded on D"; the successor links back.
- **A returned submission** is visible in the claim's review history to those with workspace access; the public sees only approved, current claims and their history of approvals.
- **A new document version** appears in the Versions panel; claims continue to cite the version they cited.
- **A withdrawn release** is marked; analyses that used it are not silently recomputed.
- **A redaction** leaves a tombstone: "Content removed on D under the redaction procedure; basis: [category]." The record's identity and hash remain (DATA_MODEL §7).
- **Registry corrections** (an institution name marked as entered in error) follow ADR-0018: the marked name stays readable on the record and is not shown as a current name.

### 5.5 OCR and translation are never silently authoritative

**[Rec]** Building on RESEARCH_PROTOCOL §4.4 and AI_ARCHITECTURE §8:

- Extraction method is visible wherever extracted text is shown. An OCR Segment carries an "OCR" marker; a quality warning is shown on the Segment and propagates to `low_extraction_quality` on any assistant statement citing it.
- A Passage reproduces the stored Segment, including any misreading (LIMITATIONS §4.1). The Passage page says so for OCR extractions and links to the original file where rights allow.
- Translations are versions with a kind; the provenance strip states the kind first. An unofficial translation is never the only version shown for a quotation; the original accompanies it where it exists.
- A machine translation shown as a reading aid is generated text: it is labelled, is not stored as a Segment, cannot be selected as a Passage, and is never cited. Whether such a reading aid is offered at all, and with what provider, depends on B7 and B14 (§9, P-8).

### 5.6 AI trust contract

**[Fact]** Binding rules are in CLAUDE.md "AI safety requirements" and [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md). **[Rec]** This section adds nothing to them; it states them as promises a user can rely on, for the interface copy:

1. The assistant answers only from approved documents in CAIPO whose rights allow it.
2. Every statement it shows cites evidence it retrieved for this question; a reference it made up cannot be displayed.
3. Quotes and numbers are checked against the stored text. Statements that fail are removed.
4. It does not state correlations, interpretations, causes, or that something does not exist.
5. It says when the evidence it found was insufficient.
6. You see nothing until checking is complete.
7. Every answer is recorded with the models, prompts, and evidence used.

### 5.7 Path to evaluating the assistant

**[Eng]** The evaluation design is in AI_ARCHITECTURE §9. **[Rec]** The order in which to make it real, none of which starts before Phase 5 is open:

| Step | What | Depends on |
|---|---|---|
| E1 | Assign the gold-set owner and labellers per language | B16 (owner decision) |
| E2 | Build the synthetic fixture and adversarial corpora (CI-safe) | Phase 5 gate |
| E3 | Retrieval spike on real approved documents per language, lexical first | B15; approved corpus from Phase 2 |
| E4 | Measure the deterministic checks (handle resolution, quote match, numeric check) on fixtures | E2 |
| E5 | Measure support-check agreement with human labels per language, and verifier attack success | E1, B14 |
| E6 | Record a baseline and set thresholds from it | E3–E5 |
| E7 | Release gate: no prompt, model, chunking, retrieval, or verification change ships without a full run | E6 |

Reported per language and per question/evidence language pair, never as an aggregate alone (AI_ARCHITECTURE §9.3). Malicious-document resistance is measured by the adversarial corpus for both the answer model and the verifier (§9.2).

---

## 6. Phased roadmap

**[Rec]** Three horizons over the existing phases of [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §7. The horizons do not replace the phases or their gates; each horizon starts a phase only when that phase's gate is READY.

### Horizon A: Foundation

| Aspect | Content |
|---|---|
| Phases | Phase 1 (current) and the Phase 2 gate |
| User value | None to the public yet. To the research team: an agreed definition of what is studied, a lawful basis for holding documents, a proven safe ingestion design, and an agreed product contract (this document, once reviewed). |
| Dependencies and blockers | B22, B8, B9, B7, B10 (research and rights); B4, B21 (engineering spike) |
| Deliverables | Researcher's definitions and protocol revisions (B22, B8); seed source list and inclusion criteria (B9); rights policy and project-data licence (B7); document sample report on scanned share and OCR (B10); job-system and isolation spike with its tests (B4, B21) and decisions on ADR-0004 and ADR-0011; owner decisions on this blueprint's register (§9); the versioned prohibited-wording list for English (RESEARCH_PROTOCOL §8; it does not yet exist) |
| Measurable acceptance | Every Phase 2 blocker in spec §10 closed with its evidence recorded; ADR-0004 and ADR-0011 Accepted or replaced; the gate re-marked READY for Phase 2 by the owner |
| Security and rights prerequisites | Isolation requirements 1–11 of ADR-0011 shown by tests; rights policy defines the six rights per document category |
| Out of scope | Any Phase 2 code before the gate; any public page; any AI |
| Risks | Research decisions take longer than engineering; the spike finds Celery on Python 3.14 unsuitable (ADR-0004 open point 2) |
| Exit | Phase 2 gate READY |

**[Rec]** Product work that fits Phase 1 now, if the owner wants it (§9, P-13): the design tokens and base stylesheet applied to the existing Phase 1 pages, the accessible-name fix for repeated buttons, and a synthetic specimen page for script coverage. These touch only existing templates and static files and add no dependency. They are application changes and need the owner to start them.

### Horizon B: Research MVP

| Aspect | Content |
|---|---|
| Phases | Phase 2, 3, 4, and optionally a minimal public site (§9, P-2) |
| User value | Researchers can build a reviewed, traceable evidence base. Readers and, if P-2 is accepted, the public can read approved claims with exact evidence, policy records with formal events, and indicator series with their releases. |
| Smallest coherent product | Country profiles over approved records; claim pages with the evidence ledger; document version pages with the provenance strip; indicator pages with small multiples and tables. No assistant. Comparative views (FR-40, FR-41) are Phase 6 in the specification; a minimal comparison view belongs here only if the owner accepts P-2. |
| Dependencies | Phase 2: B4, B7, B8, B9, B10, B21, B22. Phase 3: B11, B12, B23. Phase 4: B13, B20. Minimal public site: B7 public-display policy and project-data licence; P-2. |
| Deliverables | Phase 2: ingestion, guarded fetch, isolated parsing, document review, rights determinations, document and version pages. Phase 3: policy coding, formal events, indicators and releases. Phase 4: claims, evidence, SearchRuns, review, reassessment. Interface: components of §4.5 needed by these pages. |
| Measurable acceptance | All integrity rules I-1 to I-15 that apply have passing tests; journeys J1, J2, J4, J5, J6, and J9 meet their acceptance criteria (§3.4); 0 unresolved references in a full-site link check over the synthetic corpus; public pages pass the accessibility target in automated and manual checks; every public page passes the prohibited-wording check |
| Security and rights prerequisites | Fetch guard negative tests (private addresses, disallowed hosts, redirects, DNS rebinding); parser limit tests with oversized input; rights tested per right on every display path; public surface throttled per client address (ADR-0007 rule 6) |
| Out of scope | Assistant, retrieval chunks, keyword search (Phase 5), exports (Phase 6), interface translation, API |
| Risks | Reviewer capacity with a small team (B13); coded records shown before a review step is decided (B23); unequal evidence read as unequal activity |
| Exit | A checking reader can trace every approved claim to its evidence on the synthetic corpus and on the real corpus; owner confirms readiness for Phase 5 gate review |

### Horizon C: Advanced observatory

| Aspect | Content |
|---|---|
| Phases | Phase 5 and Phase 6 |
| User value | Keyword search; an evidence-grounded assistant for authenticated users; full comparative views; reproducible exports and data snapshots; version comparison for tracked documents; production deployment with backups |
| Dependencies | Phase 5: B14, B15, B16, B19, B24; ADR-0003, ADR-0006. Phase 6: B17; ADR-0008; B7 for redistribution |
| Deliverables | RetrievalChunks, lexical search, evaluation harness and baseline, assistant (J7); comparison (J3); export builder (J8); deployment |
| Measurable acceptance | Evaluation baseline per language published internally (AI_ARCHITECTURE §9); thresholds set from it; 100% of displayed assistant references resolve to Passages or Observations retrieved in the same interaction (I-9); J3, J7, J8 acceptance criteria met; restore test of backups passed |
| Security and rights prerequisites | Adversarial evaluation run; provider transmission right enforced; budgets in PostgreSQL; production database roles and key management (ADR-0008) |
| Out of scope | Multi-turn conversation; AI-suggested coding or claims; causal analysis; public assistant; public write API |
| Risks | Retrieval quality uneven across languages; support-check manipulation; cost; latency beyond a web request |
| Exit | Production deployment with monitoring and tested restore (spec §7, Phase 6) |

**[Rec]** Multilingual research workflows (for example reading aids and cross-language search) belong in Horizon C and only after B15 measures retrieval per language. They are candidates, not promises.

---

## 7. Product and engineering quality metrics

**[Rec]** No target is set for anything not yet measured. Structural guarantees have a target of 100% because the design requires it; everything else gets a baseline first.

### 7.1 Trust and integrity (structural, tested)

| Metric | Target | How measured |
|---|---|---|
| Displayed references that resolve to a stored Passage or Observation | 100% | Link check over all rendered pages of the synthetic corpus in CI; production check by query |
| Approved claims meeting their type's evidence requirement | 100% | I-5 tests; periodic query |
| Text displayed without the required right | 0 | Tests per right per display path |
| Pages failing the prohibited-wording check | 0 | Automated check over templates and rendered pages |
| Charts drawn across a missing period | 0 | Template tests |
| Claims shown as approved while `needs_reassessment` | 0 | Tests and query |
| Assistant answers shown before verification | 0 | Pipeline tests |

### 7.2 Research coverage (reported, not targeted)

| Metric | Why reported |
|---|---|
| Approved claims by type and country | Shows the balance of statement types; never presented as a ranking |
| Share of claims with at least one tier A Passage, by country | Shows dependence on secondary sources |
| Share of implementation-evidence claims from sources recorded as independent, by country | Shows self-reporting (LIMITATIONS §2.6) |
| Negative findings and their age | Shows where absence is recorded and how old it is |
| Documents by extraction method and quality warning | Shows OCR dependence |
| Review latency, self-review share | Shows review capacity (B13) |

### 7.3 Usability (baseline first)

| Metric | How measured |
|---|---|
| Time for a checking reader to reach a claim's Passage in context | Moderated task test with researchers, small sample, recorded with consent |
| Task success for J1–J9 | Same |
| Accessibility defects by severity | Automated and manual checks per release |

**[Rec]** No third-party analytics. Public reads are not recorded per person (ADR-0007 rule 11). Any usage measurement beyond ordinary access logs is an owner decision with a privacy statement (§9, P-5).

### 7.4 Engineering

| Metric | Source |
|---|---|
| CI green on every merge; checks of CLAUDE.md Definition of Done | CI |
| Full suite duration | CI |
| Server render time per page type, measured before any target is set | NFR-07 |
| Page weight of public pages without JavaScript | Measured; budget set after the first measurement |
| Dependency count and known vulnerabilities | `uv.lock`, pip-audit |
| Ingestion failures by reason; requests stuck in `running` | IngestionEvent queries |
| AI: per-language evaluation metrics, cost and latency per stage | AI_ARCHITECTURE §9.4 |

---

## 8. Non-goals and risk register

### 8.1 Non-goals

**[Rec]** In addition to the out-of-scope list of spec §2, which binds:

- Country scores, rankings, indices, or readiness ratings
- AI-written summaries of countries, policies, or comparisons
- Automated discovery or monitoring of sources
- A public assistant, chat history sharing, or multi-turn conversation at first release
- A separate frontend application, a JavaScript build step, or a chart framework without justification (ADR-0010)
- Engagement features: likes, comments, follows, newsletters built into the platform
- News aggregation
- Third-party trackers or analytics
- A promise of completeness of the corpus

### 8.2 Risk register

| # | Risk | Likelihood | Impact | Mitigation **[Rec]** | Owner |
|---|---|---|---|---|---|
| R1 | Research definitions (B22) stay open, and nothing in Phase 2 can start | Medium | High | Prioritise B22 above all product work; this document adds no work ahead of it | Researcher |
| R2 | Rights policy (B7) cannot be settled without competent advice | Medium | High | Seek competent review early; design so every page works with text withheld | Owner, rights reviewer |
| R3 | Unequal evidence read as unequal policy activity | High | High | Coverage panel on every comparison; no counters; wording rules | Product, Researcher |
| R4 | Small team makes independent review impossible | High | Medium | Self-review labelled (RESEARCH_PROTOCOL §9); disclosed in limitations | Owner (B13) |
| R5 | Polished interface lends unearned authority | Medium | High | Restraint in design; status banners; method page linked everywhere | Product |
| R6 | Politically sensitive subject; descriptive wording drifts | Medium | High | Prohibited-wording list and check; review; neutral design without flags or maps | Researcher |
| R7 | OCR misreadings cited as text | Medium | Medium | OCR marker; quality warnings; original file link; Reviewer check | Reviewer |
| R8 | Retrieval and verification uneven across languages | High | Medium | Per-language evaluation; `language_not_evaluated` flag | Engineering |
| R9 | Assistant overshadows reviewed claims | Medium | High | Assistant workspace-only; distinct AI family; launch value without AI | Product |
| R10 | Scope creep from attractive features | High | Medium | This register; §2.5; owner decision for each addition | Owner |
| R11 | Web fonts or chart libraries add supply-chain and CSP risk | Low | Medium | System fonts and server SVG first; dependency rule | Engineering |
| R12 | Public site exposes text without rights | Low | High | Rights checks per display path with negative tests; default deny | Engineering |
| R13 | Competitor observations go stale | High | Low | Dated observations; revisit before any public positioning text | Product |
| R14 | Phase plan diverges from this proposal without a recorded decision | Medium | Medium | Changes go through §9 and the spec, not through this document | Owner |

---

## 9. Owner decision register

### 9.1 Existing blockers

**[Fact]** From [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §10. All remain open. This document closes none of them. Recommended defaults are offered only where the decision is not a research or rights judgement.

| ID | Decision | Decides | Blocks | Recommended default **[Rec]** |
|---|---|---|---|---|
| B22 | Define "AI policy" and "economic transformation" | Researcher | Phase 2 | None offered. A research decision. The product needs only that the definition is written, versioned, and shown on the pages that depend on it. |
| B8 | Research questions and study period | Researcher | Phase 2 | None offered. Product need: the study period is stored and shown as the default period filter. |
| B9 | Inclusion criteria and seed source list | Researcher | Phase 2 | None offered. No source is proposed here. |
| B7 | Rights policy for documents; licence for project data; snapshot deposit; removal procedure | Owner with competent rights review | Phase 2 | None offered on substance. Product need: the policy maps each document category to the six rights, so that the interface can explain each withholding. |
| B10 | Share of scanned documents; OCR in scope | Researcher with engineering sample | Phase 2 | **[Eng]** Measure on a real sample before deciding; the interface supports OCR labelling either way. |
| B4 | Job system | Owner after spike | Phase 2 | **[Eng]** Spike as ADR-0004 open point 3 |
| B21 | Isolation mechanism | Owner after spike | Phase 2 | **[Eng]** Spike as ADR-0011 |
| B11 | Policy codebook | Researcher | Phase 3 | Adapt an established scheme for comparability (RESEARCH_PROTOCOL §6); the choice is the researcher's |
| B12 | Indicators, providers, licences | Researcher; rights review | Phase 3 | None offered |
| B23 | Review status for coded policy records | Owner | Phase 3 | **[Rec]** Yes, before public display: a coded record is a research judgement and should carry a review marker like a claim. Engineering cost is small if decided before Phase 3. |
| B13 | Team size and review model | Owner | Phase 4 | State it; self-review labelled if one person |
| B20 | Ethics review | Researcher with institution | Phase 4 | None offered |
| B14 | AI provider, embeddings, budget, data terms | Owner | Phase 5 | **[Eng]** Assess local and hosted options against AI_ARCHITECTURE §10 criteria |
| B15 | Retrieval quality per language | Engineering | Phase 5 | **[Eng]** Spike on real approved documents |
| B16 | Gold set owner and thresholds | Owner, Researcher | Phase 5 | Assign an owner per language |
| B19 | Retention of user questions | Owner | Phase 5 | **[Rec]** Shortest period that supports audit, disclosed on the assistant page |
| B24 | Approved claims as assistant evidence | Owner | Phase 5 | **[Rec]** Not at first release; revisit after evaluation |
| B17 | Hosting, jurisdiction, domain, backups | Owner | Phase 6 | None offered |

### 9.2 Product decisions raised by this document

All open. None is assumed by any other section.

| ID | Decision | Recommended default **[Rec]** | Trade-off | Would change |
|---|---|---|---|---|
| P-1 | Accessibility conformance target | WCAG 2.2 level AA for public site and workspace | Testing effort per release | NFR-14 wording |
| P-2 | Minimal public site, and optionally a minimal comparison view, after Phase 4 and before Phase 6 | Yes, limited to approved claims with evidence references, policy records, and indicator pages whose licences allow; the owner also decides whether an indicator page showing several countries counts as a Phase 6 comparison view | Earlier checkability vs an earlier public surface to secure and throttle | Spec §7 phase table |
| P-3 | Visual identity: name styling, mark, palette | Typographic wordmark only, no symbol, palette of §4.3 | Less recognisable than a logo; no imagery to misread | None |
| P-4 | Re-checking captured documents | Researcher-initiated re-check and a list of documents not checked recently; no scheduled re-fetch | Changes noticed later vs no unattended fetching | None if default kept; spec §2 if scheduled re-fetch is wanted |
| P-5 | Measuring usage | No analytics; ordinary access logs only; moderated usability tests with consent | Less usage insight vs privacy and ADR-0007 rule 11 | None |
| P-6 | Web font | System font stacks first; a self-hosted font later after script-coverage tests and licence check | Typography less distinctive at first | Static files only |
| P-7 | Citation format for records | One plain format with title, CAIPO record type, public identifier, version, URL, access date; others derived from it | Not every style supported | None |
| P-8 | Machine-translation reading aid | Not before B7 and B14 settle provider transmission; then labelled, collapsed, never stored as Segments | Harder for readers without the language vs authority of the original | AI_ARCHITECTURE if adopted |
| P-9 | Second interface language | Consider Russian after launch, as interface text only, with a translator who reads it | Translation upkeep | ADR-0010 point 9 revisit |
| P-10 | Public registry pages (institutions with their names) | Yes, read-only, with the public site; marked names shown as such | Exposure of reference data, which is low risk | ADR-0018 point 15 (needs a new ADR) |
| P-11 | Source for a registry name or date (finding I3) | Decide before many institutions are entered | Extra entry effort vs traceable reference data | Needs a new ADR (diagnostic §15.6) |
| P-12 | Correction route for public readers | A private report form or the existing private channel, no public comments | Moderation load vs openness | SECURITY.md if a form is added |
| P-13 | Apply the base stylesheet and accessible names to existing Phase 1 pages now | Yes, as a small separate change | Effort now vs consistent foundation | Templates and static files only |
| P-14 | Interface text style guide (wording for statuses, conditions, badges) | Write one, versioned with the prohibited-wording list | Small writing effort | New document |

### 9.3 Items needing competent rights review

**[Rights]** Not engineering or product decisions, and not advice:

- Whether short quoted Passages may be shown to anonymous visitors, per document category (public excerpt display)
- Whether original files may be downloaded publicly (public full display)
- Redistribution in exports and snapshots
- Transmission of text to any external AI provider or translation service
- The licence for project-created data
- Indicator providers' terms for display and redistribution
- The removal-request procedure

---

## 10. Prioritised next-action plan

**[Rec]** In order. Nothing below starts without the person named starting it.

| # | Action | Who | Unblocks | Effort |
|---|---|---|---|---|
| 1 | Review this blueprint; accept, change, or reject the §9.2 recommendations | Owner | Everything product-related | Small |
| 2 | Define the policy domain and economic transformation (B22), then confirm research questions and period (B8) | Researcher | Phase 2, J1–J3, J6 | Research |
| 3 | Provide inclusion criteria and the verified seed source list (B9) | Researcher | Phase 2 | Research |
| 4 | Commission competent rights review and decide the rights policy and project-data licence (B7) | Owner | Phase 2; public site; exports | External |
| 5 | Sample real documents for scanned share and OCR need (B10) | Researcher with engineering | Phase 2 parser scope | Small |
| 6 | Run the shared job-system and isolation spike (B4, B21) and propose decisions on ADR-0004 and ADR-0011 | Engineering, then owner | Phase 2 | Medium |
| 7 | Write the English prohibited-wording list and its check | Researcher, engineering | Wording checks on every page | Small |
| 8 | If P-13 is accepted: base stylesheet and tokens, accessible button names, script specimen page, on the existing Phase 1 pages | Engineering, started by owner | Design foundation | Small |
| 9 | If P-11 is accepted in principle: draft the ADR for sources of registry names and dates | Engineering, then owner | Registry entry at scale | Small |
| 10 | Decide B23 before Phase 3 opens | Owner | Phase 3 public display | Small |
| 11 | Write the interface text style guide (P-14) | Product with researcher | Consistent wording | Small |
| 12 | Revisit the competitive benchmark before writing any public positioning text | Product | R13 | Small |

---

## 11. Repository state this proposal was written against

**[Fact]** Inspected on 2026-10-25.

| Item | Value |
|---|---|
| Base commit | `origin/main` at `a7685ff203d465e59b68adc3ce63a4f23e820897` ("docs: record the merge of PR #20, which fixes L4 (#21)") |
| Architecture gate | READY for Phase 1; NOT READY for Phase 2 and later ([PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §10) |
| Accepted ADRs | 0001, 0002, 0005, 0007, 0009, 0010, 0012 to 0019 |
| Proposed ADRs, not built on | 0003, 0004, 0006, 0008, 0011 |
| Domain code | The registry only: countries, languages, institutions and their names, with the audit record ([CLAUDE.md](../CLAUDE.md); [SECURITY.md](../SECURITY.md) "The registry as implemented") |
| Pages that exist | Sign-in, two-step verification, sign-out, activation, password reset, second-factor management and history, administration of enrolment and recovery requests, account creation, the registry browse and entry pages, 403, 404, and 500 (`caipo/web/templates/web/`) |
| Styling | The base template has no stylesheet; no static CSS exists (`caipo/web/templates/web/base.html`, `caipo/web/static/web/`) |
| Prohibited-wording list | Required by RESEARCH_PROTOCOL §8 and REPRODUCIBILITY §2; not present in the repository |
| Open diagnostic findings | I1, I2, I5 (wait for ADR-0008), I3 (needs an ADR), I4 (deferred by ADR-0018), I6 (housekeeping) ([diagnostic report](reports/caipo-full-diagnostic-2026-10-20.md) §20.3) |

This document changed no other file, decision, ADR status, or blocker.

### 11.1 Recheck of 2026-10-30

**[Fact]** The table above is the state of 2026-10-25 and is kept as written. Rechecked on 2026-10-30 against `origin/main` at `e90ea1c215e11a4ccf95cd725a5d60df548ba100` ("docs: clarify single-reader calibration, re-check interval, and machine translation in the pilot (#26)").

Implemented and merged:

| Item | State on 2026-10-30 |
|---|---|
| Registry entry page (diagnostic finding L4) | Fixed on 2026-10-24 in #20 (`188fbbb`), before this proposal was written; the table above did not record it. Only the institution named by `?change=` has its change form; every other institution is shown as stored, with a link that opens its form ([diagnostic report](reports/caipo-full-diagnostic-2026-10-20.md) §19.1, §20.3) |
| Changes since the base commit | Five pull requests, all documentation: this proposal (#22), its link from the README (#23), and three changes to [RESEARCH_PROTOCOL.md](RESEARCH_PROTOCOL.md) (#24 to #26). No application code, migration, dependency, ADR, or CI workflow changed |
| Other rows of the table | Unchanged: the architecture gate, the ADRs, the domain code, the pages, the styling, the prohibited-wording list, and the open diagnostic findings |

Proposed and not implemented: everything this document recommends. Its recommendations (**[Rec]**) and the owner decisions of §9 remain open, and no ADR has been added after ADR-0019.
