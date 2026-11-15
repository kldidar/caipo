# ADR-0025: An evidence-bound assistant and a help assistant in the demonstrator

- Status: Accepted
- Date: 2026-11-15; accepted by the project owner the same day, with ADR-0006

## Context

The assistant designed in [AI_ARCHITECTURE.md](../AI_ARCHITECTURE.md) is Phase 5. It waits for:
- the research corpus (Phases 2 to 4);
- an embedding model (ADR-0003, Proposed);
- a provider and a budget (ADR-0006, Proposed).

The demonstrator of ADR-0020 has no assistant. On 2026-11-15 the project owner asked for two:

1. one that answers questions about the demonstrator's data;
2. a help window, opened from the bottom right corner of each page, that answers questions about the site and how to use it.

The owner set two conditions: nothing may be spent on the project, and the result is to be shown publicly.

The demonstrator holds two kinds of material an assistant could answer from:
- **reference Observations:** World Bank values for Turkmenistan and Uzbekistan, held as exact decimals;
- **demonstration records:** synthetic, of two synthetic countries.

It holds no text of a real document (ADR-0020 point 5; B7 is open).

## Decision

1. **One pipeline, the one already designed.** Both assistants run the fixed sequence of AI_ARCHITECTURE.md §2:
   - input guard, query analysis, retrieval, evidence verification with abstention, synthesis;
   - citation verification: handles issued per request, the quote check, the numeric check of §6.2, the support check, the permitted labels, and no causal wording;
   - response assembly and logging.

   Nothing in this ADR weakens a rule of that document or of CLAUDE.md's AI safety requirements. Where the demonstrator does less, this ADR says so below.

2. **The research assistant** answers from two kinds of evidence:
   - **reference Observations**, by the structured query of §4.2, never from model text;
   - **demonstration texts**: synthetic texts written for the demonstration documents, labelled as such on every page.

   It never answers from the model's general knowledge. Questions about a real document's text get the abstention, because no such text is held. It is a page of the research workspace, for an authenticated account.

3. **The help assistant** answers only from the **help corpus**: pages of help written for CAIPO, in the repository, versioned, and shown on the site.
   - Each statement cites a section of a help page, and the server renders the link.
   - A question outside the help corpus gets a fixed reply that says what the help covers.
   - It is opened by a button at the bottom right of every page of the workspace, for an authenticated account. The panel is a small form sent with HTMX, inside ADR-0010's limits: no build step and no streaming. It shows only the verified answer.

4. **Demonstrator forms of the data model.** These are reduced forms, like those of DATA_MODEL.md §7a.
   - **Segment** (`sources`): the text of a demonstration document, in NFC, immutable, hashed. A database check refuses a Segment on a reference document.
   - **RetrievalChunk** (`retrieval`): derived from Segments and from help sections, with the PostgreSQL search fields.
   - **AIInteraction, InteractionStageRecord, RetrievalHit, AnswerStatement, AnswerCitation** (`assistant`): as in DATA_MODEL.md §3.9, append-only by trigger.
     - An AnswerCitation names a Passage, an Observation, or a help section.
     - A Passage is created by the server for a cited Segment span, as designed.

   The `retrieval` and `assistant` apps take their planned layers, 7 and 8, of ARCHITECTURE.md §2.1.

5. **Retrieval is lexical only:** PostgreSQL full-text search and trigram matching. No embedding, no pgvector, and no vector search. ADR-0003 stays Proposed.
   - Questions in Russian are translated into English for search by the query-analysis call. That call's output is validated against its schema, as §3 requires.
   - The demonstration texts and the help corpus are in English.
   - Answers are given in English or Russian, the language of the question.
   - Russian is evaluated separately and marked `language_not_evaluated` until it is.

6. **The provider: one free tier, behind ADR-0006's interface.** ADR-0006 was accepted with this ADR. This ADR decides two of ADR-0006's former open points for the demonstrator:
   - **Generation and the support check:** one provider's free tier, chosen by a measured spike (point 10): Groq, `openai/gpt-oss-120b`, on 2026-11-15 ([spike report](../reports/spike-day35-free-providers.md)). The model identifier and settings are held in a versioned file.
   - **Budget:** zero. No billing account or payment method is attached to the provider account, so no call can be charged.

   The embedding model (ADR-0006 open point 2) and the rights policy for real documents (open point 3) are not needed here.

7. **Quotas below the free tier.** Each account has a daily limit of questions, and the instance has a daily limit across all accounts. Both are held in a versioned file, set below the provider's free limits, and counted in PostgreSQL. A question over a limit gets a fixed reply and makes no call.
   - Each answer makes at most three model calls: query analysis, synthesis, and one support check that judges every statement of the answer in one call. This differs from AI_ARCHITECTURE.md §6.2, which makes one call per statement.
   - The support check still sees only the statements and their evidence, never the question. Its verdict still cannot override a deterministic check.

8. **What reaches the provider:**
   - the question;
   - the demonstration texts;
   - the reference Observations;
   - the help text.

   Nothing else: no account data, no audit record, no secret. Each assistant states, next to its input, that questions are sent to the named provider, under that provider's terms for its free tier, and should not contain personal information.

9. **Logging.** Every interaction is recorded as AI_ARCHITECTURE.md §11 requires: model identifiers, prompt versions, retrieval hits, verification results, timings, and token counts. Cost is not recorded, because it is zero. The question is stored with the interaction.

10. **Evidence before release.** Neither assistant is shown to anyone outside the project until:
    - **a spike** compares at least two free-tier providers on schema-valid output, on answers in English and Russian, and on their free limits and data terms, and records the choice;
    - **an evaluation** runs on a gold set of questions for each assistant, in English and in Russian. It includes questions that must be refused or abstained from, and documents and questions that try prompt injection, including attacks on the support check. The results are reported per language, as AI_ARCHITECTURE.md §9 requires, and published in the repository.

## Alternatives considered

- **Wait for Phase 5.** It keeps the order of the gates, but nothing would be shown in time. Phase 5 still follows Phases 2 to 4 for the research corpus.
- **A paid model.** Its answers may be better, but the owner will spend nothing.
- **Vector search with a free embedding service.** It handles cross-language questions better, but it adds a second provider and ADR-0003's open questions. For a small English corpus, lexical search is enough to measure.
- **A help window without the pipeline**, answering from the model alone. It is simpler, but it would state invented facts about the site, which is exactly what CAIPO is built to prevent.
- **Answers from the model's general knowledge about the two countries.** These are unverifiable, and excluded by AI_ARCHITECTURE.md §1.

## Consequences

- The demonstrator gains its most visible feature and the evidence that it is safe: the evaluation and its attacks.
- Free tiers have daily limits that change. When a limit is reached, the assistants say so and stop until the next day.
- Two apps and their migrations are added. One new dependency, the provider's client or none if plain HTTPS is enough, is justified in its pull request.
- CLAUDE.md's list of Proposed ADRs and the current-phase exceptions change when this ADR and ADR-0006 are accepted. That change needs the owner's approval on its own.
- Real document text stays out until the owner decides the rights of official texts (B7). Adding it later changes the corpus, not the pipeline.

## Conditions

These were open points of the proposal. They are settled or carried into the work:

1. ADR-0006 was accepted with this ADR on 2026-11-15.
2. The owner approves the wording of the notice of point 8, in the pull request that adds it.

## Revisit when

- A free tier ends or changes its terms or data handling.
- Real document text is admitted.
- Phase 5's research-grade assistant is built.
