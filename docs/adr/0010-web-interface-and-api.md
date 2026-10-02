# ADR-0010: Web interface and API style

- Status: Accepted
- Date: 2026-10-02

## Context

Users need to browse documents and policies, select passages, code policies, record searches, write and review claims, compare countries, and ask the assistant. The public needs to read and cite reviewed research. No external system is known to need programmatic access. No JavaScript build toolchain is installed in the development environment, and the project brief warns against adding technology without need.

The project owner decided the interface style on 2026-10-02, which closed blocker B6.

## Decision

1. **Server-rendered pages** with Django templates and forms.
2. **HTMX** for interactive components that update part of a page: filters, passage selection flows, review actions, and polling for an assistant answer.
3. **Small, targeted JavaScript** only where HTMX is not enough, such as text selection inside a document and charts.
4. **No separate frontend application.** No React or Next.js, no single-page application, and no JavaScript build step at this stage.
5. **Django REST Framework is deferred** until there is a real API consumer or a demonstrated requirement. There is no public API at launch. Data leaves the system through export files with provenance.
6. **A versioned API must remain possible without rewriting the domain layer.** Only the `web` app knows about HTTP. Services and selectors take and return plain Python values, never request or response objects, so an API can later be added in `web` over the same selectors and services the pages use. When added, it is versioned, and read-only unless a further decision says otherwise.
7. **The public research interface is:**
   - server rendered, so content is present in the HTML without scripts
   - accessible: semantic HTML, keyboard operable, usable without JavaScript for reading
   - search-engine friendly: one stable URL per public record, descriptive titles and metadata
   - citation friendly: every public claim, document, version, and dataset release has a permanent URL built on its stable public identifier, and its page shows how to cite it
   - suitable for research browsing: filtering, comparison, and navigation from a claim to its evidence
   - able to offer interactive components through HTMX
8. **Assistant answers are displayed only after verification completes.** There is no streaming or progressive display of model text. While the pipeline runs, the page may show which stage is in progress, and nothing else.
9. **Launch language.** The application interface launches in English. The research corpus remains multilingual. Django's internationalisation infrastructure is enabled from the start and all interface text is marked for translation, so further interface languages can be added later without architectural change. No interface translations are produced yet.
10. **HTMX is used safely.** It is served from the application's own static files at a pinned version, not from a third-party host. Its features that evaluate script from attributes or responses are turned off, so it works under the strict Content Security Policy.
11. **The Django admin is an operations tool for Administrators, not the research interface.** Provenance and integrity-governed models are read-only in it (ADR-0007, SECURITY.md).

## Alternatives considered

- **Django API with a separate React or Next.js frontend.** Richer interaction, but two applications to build and deploy, a second dependency tree to audit, token-based authentication, cross-origin configuration, and a larger attack surface. Not justified by the known requirements.
- **Django templates with Django REST Framework from the start.** An API with no consumer is an unused surface to secure, test, and keep stable.
- **Templates only, without HTMX.** Simplest, but passage selection, filtering, and review flows would need full page reloads or hand-written scripts for each case.
- **Django admin as the main interface.** Quick, but it bypasses the service layer, which is where permissions and integrity rules are enforced.
- **Streaming model output as it is generated.** More responsive, but it would show unverified text.

## Consequences

- One language, one toolchain, simpler security review.
- Automatic output escaping applies to all document-derived text and model output.
- Public pages are indexable and citable by URL.
- Partial page updates need care for accessibility: focus management and announcements for assistive technology.
- Users wait for the whole verified answer. If the pipeline is slow, the wait is visible; see the latency risk in AI_ARCHITECTURE.md §8.
- Text selection in long documents is hand-written JavaScript and will need careful design.
- A mobile or third-party client has to wait for the API. Adding it later is a new piece of work in `web`, not a redesign.
- Marking all interface text for translation is a small standing cost from the first template.

## Revisit when

A concrete API consumer appears, usability testing shows the interface cannot meet researchers' needs, or a second interface language is required.
