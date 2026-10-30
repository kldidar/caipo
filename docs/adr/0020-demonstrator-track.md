# ADR-0020: Demonstrator track ahead of the research gates

- Status: Accepted
- Date: 2026-10-30

## Context

On 2026-10-30 the project owner changed how CAIPO is completed. The owner works alone: there is no separate research team, no second reader, and no technical team. Day-to-day engineering, documentation, and source discovery are delegated to Claude Code; the owner reviews and merges every pull request. The owner set a goal and a deadline: a complete, working, polished CAIPO demonstrator, to be shown to a university professor, by **2026-11-06, 23:59 Asia/Tashkent**.

The phased plan of [PROJECT_SPECIFICATION.md](../PROJECT_SPECIFICATION.md) §7 builds sources, policies, indicators, claims, and comparisons only after the gate of each phase is READY (§10). Those gates wait for research decisions (B7 to B12, B20, B22, B23), a job-system spike (B4, B21), and owner decisions that cannot be made honestly within a week. Under that plan no part of the product the owner described can be built before the deadline, although most of the software (records, pages, comparisons, exports) does not depend on how those questions are answered.

The owner asked for a way to build the product without closing any blocker early, without presenting synthetic data as evidence, and without bypassing a security, rights, or integrity rule. The owner gave this decision in the mandates of 2026-10-30 and accepts it by merging the pull request that adds this ADR.

## Decision

### What the demonstrator is

1. **A separate track.** The demonstrator is a working, reduced form of CAIPO's research workspace, built ahead of the Phase 2 to Phase 6 gates. It is not Phase 2 or any later phase. Every gate in specification §10 keeps its status, and every blocker stays open until its own closure requirements are met. Nothing built under this ADR closes a blocker or counts as evidence for closing one.
2. **Its scope.** Reduced forms of the planned apps, in their planned layers ([ARCHITECTURE.md](../ARCHITECTURE.md) §2.1): `sources` (layer 3: sources and document records, metadata only), `policies` and `indicators` (layer 5), `research` (layer 6: analysis runs and search runs), and the pages in `web` that use them. Each app follows the existing rules: services for writes, selectors for reads, permissions checked in services, an audit event for every change through `accounts.services.record_audit_event`, append-only records where [DATA_MODEL.md](../DATA_MODEL.md) marks them so, and an import contract per app.
3. **What it does not build.** No `ingestion` app: no fetch, no upload of documents or datasets through the application, no parsing, no artifact storage of documents, no Segment or Passage. No job system (ADR-0004 and ADR-0011 stay Proposed). No retrieval, embeddings, or AI assistant (ADR-0003 and ADR-0006 stay Proposed; Phase 5 stays blocked). No deployment (ADR-0008 stays Proposed). No research claims with review workflow (B13, B20).

### Two classes of data, never mixed

4. **Every record of the demonstrator apps has a data class**, held by a database check: `demonstration` or `reference`.
   - **`demonstration`**: synthetic records that exist to show what the software does. They belong only to synthetic countries, whose codes are in the ISO 3166-1 user-assigned range (`AA`, `QM` to `QZ`, `XA` to `XZ`, `ZZ`), and their titles start with `TEST` or `DEMO`. A service refuses a demonstration record for any other country. This is a rule about code ranges, not a branch on a named country.
   - **`reference`**: records of real public sources, documents, and indicator values, each with its name, URL, publisher, access date, licence or terms where verified, and the use it is suitable for (stored, processed, or reference only). A reference record may not belong to a synthetic country.
5. **Every page and export shows the class.** A page that shows demonstration records says so in a visible label on each record and a notice on the page. An export states the class of each row and has a methodology note. A result computed from demonstration data is labelled a demonstration result.
6. **No synthetic record is ever presented as country evidence**, and no demonstration record is counted in a result about a real country.

### Reference records: what is kept

7. **Metadata only for legal and policy documents.** A reference document is registered with its title as written, its official identifier and date where the text states them, its issuing institution, and its official URL. Its full text is not downloaded or kept while its rights are unresolved (B7), and no part of it is sent to an external AI, translation, or other processing service.
8. **Classifications are provisional.** Whether a reference document belongs to the core AI policy corpus or the contextual policy registry ([RESEARCH_PROTOCOL.md](../RESEARCH_PROTOCOL.md) §3.1.5), and which layer an indicator belongs to (§3.2), are recorded as provisional working assignments with a reason, and shown as provisional. They are not eligibility decisions under §3.1.6 and not the indicator selection of B12, which stay open.
9. **Indicator values from openly licensed providers.** Reference observations come only from a provider whose licence allows storage and redistribution with attribution, verified and recorded with the source. A provider's file is obtained once during development, committed with its URL, access date, licence, and SHA-256, and loaded by a management command from the committed file. The application makes no outbound network call to obtain it. Values are stored as published: missing values stay missing, provider flags are kept, nothing is interpolated.
10. **Bounded discovery.** Source discovery for reference records is bounded. A source that cannot be reached or whose terms cannot be established is recorded as a limitation and not searched again. The reference set is a sample for demonstration, never described as complete coverage, and an absent record is never presented as proof that a policy or value does not exist.

### Deviations from the planned data model

11. **No Passage to cite.** Without ingestion there are no Segments, so a policy event, an instrument, or an AI-related provision of the demonstrator cites a document record and a locator (for example an article number) instead of a Passage (DATA_MODEL I-13). For a demonstration document, the provision text may be stored, because it is synthetic.
12. **Corpus assignment as a record.** The demonstrator records a policy's provisional corpus assignment (core or contextual) and its reason as a field of its own, and lists contextual entries as records, instead of only as items of a SearchRun (protocol §3.1.5; gaps F-1 and F-3).
13. **These forms are for the demonstrator.** The research-grade build of Phases 2 to 6 decides its own forms through the F-points and the phase gates. Demonstrator records are never migrated into research records automatically.

### Analysis

14. **Reproducible, descriptive only.** An analysis run computes descriptive measures over stored observations (coverage, first and last values, absolute and relative change between two periods). It records its method and method version, its parameters, its inputs, the code version, and a SHA-256 fingerprint of its inputs and result, so a re-run can show whether the result is the same. It produces no correlation, causal, or interpretive statement, and every result shows the non-causation notice of protocol §8.

### Interface

15. **ADR-0010 still governs.** Server-rendered templates, HTMX, and small targeted JavaScript; no JavaScript build step and no separate frontend. The design system is static CSS. Charts are rendered on the server as SVG with a text alternative. Fonts and scripts are served from the application, not from a third-party network.
16. **Access.** Every demonstrator page requires sign-in and a named permission. The public research site of ADR-0007 is not built by this ADR. A development-only command may create demonstration accounts; it refuses to run unless `DEBUG` is on.

### Process

17. **Sprint execution.** The work is run as execution Days in [EXECUTION_TRACKER.md](../EXECUTION_TRACKER.md), each in its own pull request that the project owner reviews and merges. During the sprint, one implementation pull request may be based on another open one, because the owner merges by hand and the deadline does not allow waiting; each such pull request says so.

## Alternatives considered

- **Keep the phased plan.** Nothing of the described product can be built by the deadline: Phase 2 waits for research the owner cannot complete in a week. Rejected by the owner.
- **Close blockers with provisional answers.** Would make the gates mean nothing and present unverified research decisions as settled. Rejected.
- **A static mock-up or a separate frontend prototype.** Would not show working software and would break ADR-0010. Rejected by the owner.
- **One `demonstrator` app holding everything.** Simpler to remove, but it would not show the planned architecture, and the research-grade build would gain nothing from it. Rejected in favour of reduced forms of the planned apps, with the data class kept on every record.
- **Synthetic data for Turkmenistan and Uzbekistan.** Would make the demonstration look complete and would risk synthetic values being read as evidence about those countries. Rejected: synthetic records belong only to synthetic countries.

## Consequences

- The owner can show a working product by the deadline, with real metadata and real openly licensed values where they exist, and synthetic records where they do not.
- The research-grade build later changes or replaces the demonstrator forms of points 11 and 12. That cost is accepted.
- More code exists before its research rules are settled. The data class, the provisional labels, and the gates that keep their status limit the risk that it is mistaken for research.
- Reviewing a stacked pull request is harder. Each states its base.

## Revisit when

- The Phase 2 gate becomes READY: the research-grade build then decides what of the demonstrator is kept, changed, or removed.
- A reference source's terms change or turn out not to permit what is recorded.
- The project owner ends the sprint or changes its scope.
