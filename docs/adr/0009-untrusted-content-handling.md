# ADR-0009: Untrusted content handling: principles

- Status: Accepted
- Date: 2026-10-02

## Context

CAIPO fetches documents and dataset files from the internet, parses complex file formats, stores the results, and places extracted text in language model prompts. Government and third-party sites can be compromised, files can be crafted to exploit parsers, and document text can contain instructions aimed at a language model. The full threat model is in [SECURITY.md](../../SECURITY.md).

This ADR states the principles. How the fetch and parse workers are actually isolated is a separate, unproven question and is the subject of [ADR-0011](0011-worker-isolation-mechanism.md), which remains Proposed. Accepting these principles does not accept any mechanism.

## Decision

All external content is untrusted at every stage. This includes documents and dataset files (CSV, XLSX, and any other format). The defences are structural: they limit what a hostile input can reach, and do not depend on recognising it.

1. **One guarded fetch path, registered hosts only.** All outbound requests for documents and datasets go through a single service. It fetches only from allowed hosts of registered sources, validates scheme, resolves and checks the address against a deny list, connects to the validated address, re-validates on every redirect, and enforces time limits and a size limit on the decompressed body. Only users with the Researcher role or above can trigger it. Network-level egress rules back it up.

2. **The fetch worker is isolated and does not interpret content.** It streams, counts, and hashes bytes and records response metadata. It performs no type detection and no parsing. It holds no database credentials and no AI credentials.

3. **Formats are allow-listed by content.** Type is determined from the bytes, in the parse worker. Anything not on the list is rejected. Macros, scripts, formulas, and embedded objects are never executed.

4. **All parsing is isolated.** Untrusted bytes are interpreted only in the parse worker, which has no outbound network access, no database credentials, and no AI credentials, and runs with resource limits.

5. **Isolated output is validated.** Results from the fetch and parse workers are structured data that a trusted worker validates before anything is written to the database.

6. **Isolation requirement.** Compromise of the fetch worker or the parse worker must not yield database credentials, AI credentials, access to internal services, or the ability to enqueue arbitrary tasks. Compromise of the parse worker must additionally not yield outbound network access.

7. **Bounded delivery.** A task that kills or stalls its worker is retried a fixed small number of times, counted in PostgreSQL, and then failed.

8. **Artifacts are inert.** Stored under hash names, outside the web root, never executed, and served only as attachments with a generic content type.

9. **Approved documents only.** Only document versions with review status `approved`, set by a Reviewer, are searchable or citable. A Reviewer can suspend a version.

10. **Rights are enforced.** Text is sent to an external AI provider, shown to users, or exported only where the document version's recorded rights permit, independently of who is signed in.

11. **Retrieved text is data.** It enters prompts in delimited blocks marked as untrusted.

12. **The model has no tools.** It cannot fetch, call functions, write, or trigger any action, and has no secrets in its context. The application's own calls to the model provider are by design and are not a model capability.

13. **The server owns citations.** The model refers to evidence by request-scoped handles. The server resolves them and verifies quotes and numbers.

14. **The verifier is not trusted either.** The support-check model reads the same hostile text. Guarantees rest on deterministic checks; the support check is a filter whose robustness is measured.

15. **Output is inert, and only verified output is shown.** Rendered escaped, with no model-authored links, images, or markup, and never displayed before verification completes.

16. **Robustness is measured.** An adversarial corpus, including verifier-targeted cases, is part of the evaluation suite.

## Alternatives considered

- **Detect and filter malicious content.** Classifiers and pattern filters for injection miss novel attacks and give false assurance. Kept only as a triage aid for Reviewers.
- **Parse in the web or default worker with library-level limits.** A parser exploit would then run with database and AI credentials. This applies to dataset files as much as to documents.
- **Let the fetch worker detect file types or write to the database.** Both would put interpretation of hostile bytes, or credentials, in the one component with internet access.
- **Convert all documents through an office suite to a single format.** A very large attack surface. Not proposed for the initial format set.
- **Give the model retrieval tools.** More flexible, but every tool is something an injected instruction can invoke.
- **Antivirus scanning of uploads.** Does not protect our parsers from targeted files. May be added later to protect users who download originals. Deferred.

## Consequences

- More operational complexity: separate workers, networks, and credentials.
- Fewer supported formats at first.
- Higher latency and cost per answer because of verification.
- The assistant is less capable than an agentic design.
- A hostile document can still contain false statements that are faithfully cited. Source tiers, review, and corroboration address this, not this ADR.
- These principles are only as good as the isolation mechanism, which ADR-0011 must prove.

## Revisit when

A new format is added, the model is given any tool, multi-turn conversation is introduced, or uploads from less-trusted users are allowed.
