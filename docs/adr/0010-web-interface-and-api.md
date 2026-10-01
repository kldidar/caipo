# ADR-0010: Web interface and API style

- Status: Proposed
- Date: 2026-10-01

## Context

Users need to browse documents and policies, select passages, code policies, record searches, write and review claims, compare countries, and ask the assistant. No external system is known to need programmatic access. No JavaScript toolchain is installed in the development environment, and the project brief warns against adding technology without need.

## Decision (proposed)

- **Server-rendered pages** with Django templates and forms.
- **Small, targeted JavaScript** only where interaction needs it: passage selection, charts, and polling for an assistant answer. A lightweight library for partial page updates may be adopted if plain forms prove too clumsy; that would be decided when the need is concrete.
- **Assistant answers are displayed only after verification completes.** There is no streaming or progressive display of model text. While the pipeline runs, the page may show which stage is in progress, and nothing else.
- **No single-page application** and no separate frontend build.
- **No public API in the first release.** Data leaves the system through export files with provenance.
- **If an API is needed later**, it is read-only, versioned, and sits in the `web` app over the same selectors the pages use. The framework for it is chosen then.
- **The Django admin is an operations tool for Administrators, not the research interface.** Provenance and integrity-governed models are read-only in it (ADR-0007, SECURITY.md).

## Alternatives considered

- **Single-page application with a JSON API.** Richer interaction, but a second toolchain, a second dependency tree to audit, token-based authentication, and a larger attack surface. Not justified by the known requirements.
- **API-first with a thin client.** Useful if third parties will consume the data programmatically. That need has not been stated.
- **Django admin as the main interface.** Quick, but it bypasses the service layer, which is where permissions and integrity rules are enforced.
- **Streaming model output as it is generated.** More responsive, but it would show unverified text.

## Consequences

- One language, one toolchain, simpler security review.
- Automatic output escaping applies to all document-derived text and model output.
- Users wait for the whole verified answer. If the pipeline is slow, the wait is visible; see the latency risk in AI_ARCHITECTURE.md §8.
- Some interactions, especially passage selection in long documents, will need careful design.
- If programmatic access becomes a requirement, an API must be added.

## Open points

Acceptance requires the project owner to confirm (blocker B6):

1. No external consumer needs an API in the first release.
2. A server-rendered interface is acceptable for the intended audience.
3. Which interface languages are needed (English only, or also Russian, Turkmen, Uzbek).

## Revisit when

A concrete API consumer appears, or usability testing shows the interface cannot meet researchers' needs.
