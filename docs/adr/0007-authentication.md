# ADR-0007: Authentication and access model

- Status: Accepted
- Date: 2026-10-02

## Context

Researchers, Reviewers, and Administrators change the evidence base and must be identified, because every provenance and review record names an actor. The project also exists to make its research checkable by others, which calls for public access to reviewed results. Public access raises abuse, cost, and copyright exposure, so what the public can reach has to be narrow and explicit.

The project owner decided the access model on 2026-10-02, which closed blocker B5.

## Decision

### Three surfaces

| Surface | Who | What |
|---|---|---|
| **Public research site** | Anyone, without an account | Read-only access to approved, public material |
| **Research workspace** | Authenticated accounts, according to role | Drafts, source submission, policy coding, claims, review, the research assistant |
| **Administration** | Administrators only | Users, roles, configuration, operations, redaction |

### Principals

- **Anonymous visitor.** Not a role. An unauthenticated request. It can reach only the public research site.
- **Roles**, all authenticated: Reader, Researcher, Reviewer, Administrator. Their permissions are listed in [PROJECT_SPECIFICATION.md](../PROJECT_SPECIFICATION.md) §3. There are no other roles.

### What an anonymous visitor may and may not do

May: read material that is both approved and public. That means approved research claims with their evidence references, labels, and review markers; public records and metadata; and document text or excerpts only where the document version's recorded rights allow public display.

Must not, under any configuration:

- submit sources or URLs
- trigger ingestion or any fetch
- create, edit, or review claims
- call the AI assistant
- see drafts, claims in review, or anything not approved
- see restricted documents or any text whose rights do not allow public display

### Rules

1. **Deny by default.** Every view declares the access it requires: public, a named role, or administration. A view with no declaration is refused, and a test enforces that no undeclared view exists. Permissions are checked again in the service layer.
2. **Document rights are enforced independently of authentication.** Being signed in, in any role, never substitutes for a right, and holding a right never substitutes for a permission. Both checks must pass. See [RIGHTS_AND_LICENSING.md](../RIGHTS_AND_LICENSING.md).
3. **No public self-registration at launch.** Accounts are created by an Administrator.
4. **Multi-factor authentication with TOTP is required for Reviewer and Administrator accounts.** Such an account cannot use its privileges until TOTP is enrolled. Other accounts may enrol voluntarily.
5. **The AI assistant requires an authenticated account** and is subject to per-account quotas and the usage policy. Quotas are tracked persistently in PostgreSQL, never only in a cache.
6. **Rate limiting.** Public pages are throttled per client address. Login, source submission, uploads, and assistant questions are throttled per account.
7. **Authentication mechanism.** Django's built-in authentication with server-side sessions and secure cookie settings. A custom user model from the first migration. Passwords hashed with Argon2. Audit events for authentication, role changes, and administrative actions.
8. **Administration is restricted.** The Django admin is available to Administrators only, on a non-default path, behind TOTP. Provenance and integrity-governed models are read-only in it; all writes to them go through services, and database-level protections apply to the web process's role. Admin write access is limited to operational data such as users and roles. The full list is in [SECURITY.md](../../SECURITY.md).
9. **Redaction** is an Administrator-only service operation, not an admin-interface action.
10. **Account deletion** anonymises the identity behind actor references through the redaction procedure; the records that name the actor remain.
11. **Public reads are not recorded per person.** Requests from anonymous visitors appear in ordinary access logs only.

### Not part of launch

- Self-registration
- Institutional single sign-on
- Machine-to-machine access tokens. There is no API at launch (ADR-0010).

## Alternatives considered

- **Fully public read, authenticated write, with no separate workspace.** Simpler, but it puts every approved record and the assistant in front of anonymous traffic, with the highest cost, abuse, and copyright exposure.
- **Fully authenticated application.** Lowest exposure, but it works against the purpose of making the research checkable by others.
- **External identity provider from the start.** Useful if a host institution requires single sign-on. Otherwise an extra dependency for a small user base.
- **Token-based authentication for a separate frontend.** Not needed: the interface is server-rendered (ADR-0010).
- **Public, anonymous assistant.** Exposes AI cost and abuse with no accountability.

## Consequences

- Reviewed research is publicly readable and citable without an account.
- Two audiences must be considered for every screen and every document right.
- Administrator effort to create accounts.
- A dependency is needed for TOTP. It is chosen and justified under the dependency rule when authentication is implemented.
- What the public can see of a document is governed by that document version's rights determination, not by this ADR. A version with no determination allowing public display shows none of its text publicly. The rights policy is a separate matter (blocker B7).

## Revisit when

The user base grows beyond what manual account management supports, an institution requires single sign-on, or a public API is introduced.
