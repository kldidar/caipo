# ADR-0003: Vector search with pgvector and hybrid retrieval

- Status: Proposed
- Date: 2026-10-01

## Context

The assistant must find relevant text across documents in Turkmen, Uzbek, Russian, and English, often for a question asked in a different language. Lexical search alone cannot match across languages. Vector search can, but its quality depends on how well the embedding model covers each language, which has not been measured for any corpus language.

The corpus is small: at most hundreds of thousands of segments.

## Decision (proposed)

- The unit of retrieval is the **RetrievalChunk**, derived from Segments under a versioned chunking configuration. Segments are never altered for retrieval.
- Store embeddings in PostgreSQL with the pgvector extension, as ChunkEmbeddings. **Embeddings belong to RetrievalChunks, never to Segments.**
- Retrieve with both lexical and vector search over chunks and combine the rankings with reciprocal rank fusion.
- Start with exact vector search. Add an approximate index only if measured latency requires it.
- Store each embedding with its model identifier and version. Never mix models in one search.
- Chunks and embeddings are derived data. They can be deleted and rebuilt, and changing the chunking configuration or embedding model regenerates them without touching evidence.

## Alternatives considered

- **Dedicated vector database.** A second datastore with its own consistency, backup, and security concerns. No benefit at this scale.
- **Lexical search only.** Simplest, but cannot serve cross-language questions.
- **Vector search only.** Weak on exact terms such as document numbers, institution names, and legal references, which matter in this domain.
- **Embedding Segments directly.** Couples retrieval tuning to provenance records.
- **Translate the whole corpus to one language and search that.** Makes retrieval depend on machine translation quality and conflicts with the rule that originals are authoritative. May still be useful as an additional retrieval signal; to be examined in the spike.

## Consequences

- No new datastore. Index and source data stay consistent in one transaction.
- Changing the embedding model or chunking configuration requires regenerating chunks or embeddings and rerunning evaluation.
- Retrieval quality is unproven until measured.

## Open points

Acceptance requires:

1. An embedding model is selected (ADR-0006), including its vector dimension and whether it runs locally or as a service. Local feasibility has not been assessed.
2. A retrieval spike on a sample of real documents in each language measures recall for lexical, vector, and fused retrieval, including cross-language questions (blocker B15).
3. The spike shows the hybrid approach is adequate, or identifies what must change.

## Revisit when

The corpus grows beyond what a single PostgreSQL instance searches acceptably, or evaluation shows a retrieval quality ceiling attributable to the store.
