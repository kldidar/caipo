# ADR-0021: Registration on the site, for the Reader role

- Status: Accepted
- Date: 2026-11-03

## Context

[ADR-0007](0007-authentication.md) rule 3 says there is no public self-registration at launch, and [ADR-0015](0015-account-lifecycle-and-email-verification.md) point 8 says that no page, setting, or request creates an account without an acting Administrator. So every account other than the first Administrator's is created by an Administrator, who names its address and one role.

On 2026-11-03, after trying the demonstrator, the project owner decided otherwise. A person should be able to create an account themselves and get read-only access at once. To add something, for example an article, they send it for review, and the owner reads it and decides whether it is published. This ADR decides the first half: registration. Contributed articles, their review, and the licence under which a contributed text is published are a separate decision for a later ADR.

The owner gave this decision on 2026-11-03 and accepts this ADR by merging the pull request that adds it. In the same exchange the owner approved the matching change of CLAUDE.md.

## Decision

1. **What it supersedes.** ADR-0007 rule 3 and the "Self-registration" item of its list "Not part of launch", and ADR-0015 point 8 and its alternative "Public self-registration with later approval, forbidden by ADR-0007 rule 3". Everything else in those ADRs stands: an Administrator still creates accounts with any of the four roles, and the account lifecycle, the token, the activation flow, and the email boundary are unchanged.
2. **One public page, one field.** `/register/` takes an email address and nothing else: no password, no name, no role. Whoever uses it is not signed in. It is declared public, like the sign-in and activation pages.
3. **The Reader role, and only that.** A registered account receives the Reader role. No other role can be taken by registering, and the operation takes no role as input. Researcher, Reviewer, and Administrator are given by an Administrator, as before (ADR-0012, ADR-0015).
4. **The address is verified before anything is read.** The account is created in `PENDING_VERIFICATION` with a password nobody knows, exactly as ADR-0015 creates one, and receives the same verification message. Its owner opens the link and chooses a password on the same activation page, under the same token rules, lifetime, and throttle (ADR-0015 points 13 to 27). Until then the account can do nothing.
5. **The role grant names nobody.** RoleEvent's rule that every event names who made the change gains a second exception, beside the grant that creates the first Administrator: the Reader role taken by registering is granted by nobody, says so in its reason, and exists at most once for each account. The database holds this: an event without an actor can only be a grant of the Administrator role or of the Reader role, the first Administrator's grant stays unique, and an account has at most one Reader grant without an actor.
6. **Three account events, none naming an actor.** `account_registered`: a registration created the account. `registration_repeated`: a registration was asked for an address that already has an account. `registration_message_sent`: a registration had the verification message sent. `account_created` and `verification_sent` stay what an Administrator does, each naming the Administrator.
7. **One answer for every registration.** Every registration with a well-formed address gets the same page, whether the address is new, belongs to an active, disabled, or waiting account, or the registration was throttled. Nothing that was submitted is put back into the page. Every registration that is not throttled records one account event and costs one password hash, whichever way it goes.
8. **An address that already has an account.** Nothing is created and the account keeps its roles. If it awaits verification, the verification message is sent again with a new token, which replaces the earlier one, at most `ACCOUNT_REGISTRATION_MESSAGE_LIMIT` messages (3) within `ACCOUNT_REGISTRATION_WINDOW` (one hour), counting those an Administrator had sent. An active or disabled account is sent nothing.
9. **Throttling by source.** At most `ACCOUNT_REGISTRATION_SOURCE_LIMIT` registrations (10) from one source within `ACCOUNT_REGISTRATION_WINDOW`, counted in PostgreSQL from the account events under the lock that already serializes account changes, so registrations sent together cannot all be counted as the first. A throttled registration stores nothing and sends nothing. The source is the address the request came from, never a header a client can write.
10. **Logging.** The registration itself is logged as one line, the same for every registration. A message that is sent is logged as one an Administrator has sent is, with the account's number and no actor. No address, token, or link is logged.
11. **Development.** No email is sent in development (ADR-0015 point 30). The registration page and the password reset page say, after a request and only when `DEBUG` is on, that messages are written to `data/outbox/`.
12. **What a Reader reads is unchanged.** A registered account holds what the Reader role confers, the same as a Reader an Administrator created. Rights checks stay separate from roles (ADR-0007 rule 2): no account, registered or created, is shown text whose rights do not allow it.

## How it is enforced

- **In the database.** The account event types are a check; the actor rules of RoleEvent and AccountEvent are checks; the single first-Administrator grant and the single registration grant per account are partial unique indexes (`accounts/0013_self_registration`).
- **In the service.** `register_account` takes no role and no actor, creates only a Reader's account awaiting verification, and holds the account-change lock while it counts and decides.
- **By tests**, including the full path from registration to a Reader who can read and cannot add, the same answer for every kind of address, the exact limits, two registrations of one address at the same time, the migration applied and reversed, and the database rejecting an actor-less grant of any other role.

## Alternatives considered

- **Keeping provisioning by an Administrator only.** The owner did not want it for the demonstrator: a visitor could not get in without asking someone.
- **A request for access that an Administrator approves.** Every account would be vetted, at the cost of a wait. The owner chose immediate read access.
- **Registration without email verification.** Anyone could register somebody else's address, and an account would claim an address nobody had shown was theirs.
- **A CAPTCHA.** It needs an external service and an outbound call, which needs its own decision. The throttle bounds abuse for now.
- **Recording a registration as `account_created` without an actor.** It would loosen the rule that `account_created` names the Administrator who created the account.
- **Granting the Reader role through the role service with a system account as its actor.** It would put an invented actor in the record of who changed a role.

## Consequences

- **Anyone who can receive mail at an address can read the workspace.** Today it holds metadata of sources and policies, demonstration data, World Bank values, analyses, and searches, and no text of a legal document. Before drafts, restricted text, claims in review, or the assistant become readable in the workspace, what a Reader may see must be decided again.
- **Accounts accumulate.** An account that is registered and never activated stays in `PENDING_VERIFICATION`; nothing removes it, as for one an Administrator created (ADR-0015). Retention of accounts and events is a data-governance decision that is still open.
- **Personal data.** CAIPO now stores the email addresses of people it does not know. Nothing else is asked for. The page says what is kept.
- **Production.** No email delivery service is configured until ADR-0008 names one. There, a registration creates an account whose message is refused and logged, and registration is not usable until a service is configured.
- **Behind a reverse proxy** every visitor shares one source until ADR-0008 names the header to trust, so the throttle would count all visitors together: ten registrations an hour for the whole site.
- **Timing.** A registration for a new address and one for an existing address cost the same hash. A message is sent only for a new or waiting account, so the time taken to send it can still differ, as for password reset (ADR-0016).
- **The migration** changes checks and choices only. Reversing it fails once an account has registered, because the earlier checks allow no such rows.

## Revisit when

Drafts, restricted text, claims in review, or the assistant become readable in the workspace; a delivery service is chosen; abuse is seen; the public research site is built; or contributed articles are decided.
