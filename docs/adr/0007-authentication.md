# ADR-0007: Authentication and access model

- Status: Proposed
- Date: 2026-10-01

## Context

Researchers, Reviewers, and Administrators change the evidence base and must be identified, because every provenance and review record names an actor. Whether Readers are anonymous members of the public or authenticated users has not been decided. That choice affects cost exposure of the assistant, abuse risk, privacy obligations, and whether copyrighted documents can be displayed.

## Decision (proposed)

### Proposed regardless of the open question

- Django's built-in authentication with server-side sessions and secure cookie settings.
- A custom user model from the first migration, since changing it later is costly.
- Role-based permissions: Reader, Researcher, Reviewer, Administrator. Checked in the service layer, deny by default.
- No self-registration for roles that can write. Accounts are created by an Administrator.
- Password hashing with Argon2, rate limiting on login, and audit events for authentication and role changes.
- **Multi-factor authentication is required for Administrator and Reviewer accounts.** The mechanism is to be chosen.
- The assistant requires an authenticated user, at least initially, so that budgets and rate limits attach to an account.
- **Django admin** is restricted to Administrators on a non-default path. Models for provenance and integrity-governed records are registered read-only in it; all writes to them go through services, and database-level protections apply to the web process's role. Admin write access is limited to operational data such as users and roles. The full list is in [SECURITY.md](../../SECURITY.md).
- Redaction is an Administrator-only service operation, not an admin-interface action.
- Deleting a user account anonymises the identity behind actor references through the redaction procedure; the records that name the actor remain.

### Not yet decided

- Whether approved content is readable without an account
- Whether Readers can self-register
- Whether institutional single sign-on is needed
- Whether any machine-to-machine API access is needed, and if so its token model
- The multi-factor mechanism

## Alternatives considered

- **External identity provider from the start.** Useful if the host institution requires single sign-on. Otherwise an extra dependency for a small user base.
- **Token-based authentication for a separate frontend.** Only relevant if ADR-0010 chooses a single-page application, which is not the recommendation.
- **Fully public, anonymous assistant.** Exposes AI cost and abuse with no accountability. Not recommended for the first release.

## Consequences

- Minimal dependencies and well-understood security properties.
- Administrator effort to create accounts.
- If public read access is chosen later, the recorded rights on document versions decide what anonymous users may see.

## Open points

Acceptance requires the project owner to decide the access model (blocker B5) and to state whether institutional sign-on is required.

## Revisit when

The user base grows beyond what manual account management supports, or an institution requires single sign-on.
