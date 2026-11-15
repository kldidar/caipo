# ADR-0006: AI provider abstraction

- Status: Accepted
- Date: 2026-10-01; accepted by the project owner on 2026-11-15, with ADR-0025

## Context

The assistant needs text generation with structured output, a support-checking call, query and chunk embeddings, and optionally reranking. Hosted models change and are retired, prices change, and data-handling terms differ between providers. Generation and embedding may come from different providers, and a generation provider may offer no embedding model. The research needs every prompt to be inspectable and every interaction to record exactly which model produced it.

## Decision

### Decided

- A small internal interface with three operations: generate structured output, embed texts, and optionally rerank.
- Application code depends on this interface only. Vendor SDKs are imported only inside provider implementations; their network calls to the provider are part of the design.
- A deterministic fake provider is used in all automated tests.
- **Model identifiers and generation settings affect results, so they are held in repository-versioned settings**, not in environment variables. Secrets and endpoints come from the environment. Budgets are operational settings.
- Each call records provider, exact model identifier, settings, token counts, cost, and latency in PostgreSQL. Budget enforcement reads from those records.
- No orchestration framework. The pipeline is a short fixed sequence, and prompts are versioned files in the repository.
- Generation and embedding are selected independently.
- Document text is sent to an external provider only where the document version's recorded rights permit it.

### Decided elsewhere

The interface above is what this ADR decides. The choices that fill it are decided where they apply:

- **For the demonstrator:** [ADR-0025](0025-demonstrator-assistants.md) points 6 and 7.
  - Generation and the support check use one free tier, chosen by a measured spike.
  - The budget is zero.
  - No embedding and no reranking are used.
- **For the research platform:** the generation provider and model (B14), the embedding model (B15), whether reranking is used, the documents that may be sent to a provider (B7), and the budget. They are decided before Phase 5, in an ADR of their own, by the criteria below.

## Alternatives considered

- **Call one vendor's SDK directly throughout the code.** Less code now, but it ties tests, logging, and every call site to one vendor and makes the fake provider awkward.
- **An orchestration framework.** Adds a large dependency and hides prompt construction, for a pipeline that is a few function calls.
- **A gateway service in front of several providers.** Another component to run. Not needed for one application.
- **Self-hosted generation model.** Would give maximum control and reproducibility. **Feasibility has not been assessed.** The development machine has a GPU with 12227 MiB of memory; the WSL environment currently has 7.4 GiB of RAM allocated, which is adjustable; the production server is unspecified; and model quality in the corpus languages is unmeasured. This remains an open option until assessed.

## Consequences

- A small amount of interface code to maintain.
- Switching or comparing providers is a reviewed change to versioned settings plus an evaluation run.
- Features specific to one provider are used only behind the interface.

## Criteria for the choices decided elsewhere

These were this ADR's open points before its acceptance. They remain the criteria for the choices it leaves to other decisions.

1. **Generation provider and model.** Criteria:
   - quality on the evaluation set in all corpus languages;
   - reliable structured output;
   - data-handling terms: no training on submitted content, and the retention period;
   - cost;
   - version stability.

   Hosted and self-hosted options are both to be assessed.
2. **Embedding model.** Criteria:
   - measured retrieval quality for Turkmen, Uzbek, Russian, and English, including cross-language (blocker B15);
   - the ability to pin the version;
   - resource needs on the development machine and on the production server.

   An open-weights model that can be pinned indefinitely is preferable for reproducibility; whether one can run on the available hardware has not been assessed.
3. **Data handling.** The rights policy that determines which documents may be sent to the chosen provider (blocker B7).
4. **Budget.** Monthly limit and per-user limits (blocker B14).

## Revisit when

A provider changes terms, retires a model in use, or evaluation shows a better option.
