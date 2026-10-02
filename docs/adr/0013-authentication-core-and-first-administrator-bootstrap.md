# ADR-0013: Authentication core and first-Administrator bootstrap

- Status: Accepted
- Date: 2026-10-02

## Context

[ADR-0007](0007-authentication.md) decided the mechanism: Django's built-in authentication with server-side sessions, secure cookies, Argon2, and a record of authentication. [ADR-0012](0012-authorization-and-role-event-integrity.md) decided how roles are held and protected, and, as amended, how the first Administrator's role event is permitted.

This ADR decides the authentication core: how a person signs in and out, what is recorded, how guessing is limited, and how the first Administrator comes to exist. The project owner specified the requirements and accepted the design on 2026-10-02.

It decides nothing about multi-factor authentication, account creation, or deployment. Those are listed under "Deferred" as later work. They are not open questions inside this decision.

## Decision

### Signing in and out

1. **Email address and password, through Django.** The email address is the identifier. Credentials are checked by Django's `authenticate` against Argon2 hashes. No external authentication library is used.
2. **Session-based.** A successful sign-in establishes a Django session held on the server in PostgreSQL. The cookie carries an identifier only. It is `Secure`, `HttpOnly`, and `SameSite=Lax`; it ends when the browser closes, and the session ends on the server 12 hours after sign-in. Development turns off `Secure`, because the development server speaks plain HTTP, and relaxes nothing else.
3. **Sign-in is POST-only.** The page is fetched with GET; credentials are accepted only by POST. They never travel in a URL.
4. **Sign-out is POST-only.** A link or an image cannot sign anyone out. It ends the session on the server, takes no destination, and is harmless when nobody is signed in.
5. **CSRF protection** applies to sign-in and to sign-out.
6. **Session fixation protection.** The session key is replaced on sign-in, so a key known beforehand is worth nothing afterwards.
7. **Safe local redirects.** After sign-in a destination is followed only if it is a path on this site. Anything else is ignored.
8. **Generic authentication failures.** A wrong password, an unknown email address, and a deactivated account produce one outcome, one page, and one log line. Throttling behaves the same whether or not an account exists. Nothing reveals whether an email address has an account.
9. **Credentials are never logged, recorded, or sent back.** Logs name an account by identifier and a refusal names nobody.
10. **One service decides.** `caipo.accounts.services.sign_in` takes an email address, a password, and a source address. In one transaction it applies the throttle, checks the credentials, and records the event. The view handles the form, the session, and the redirect, and contains no authentication logic. Django's `LoginView` is not used, because it has no place for the throttle and the record inside that transaction other than signal handlers, which the architecture does not use for workflow.

### Authentication events

11. **AuthenticationEvent is append-only.** It records `login_success`, `login_failure`, and `logout`, with the time, the user if the submitted email address belongs to an account, and the request's correlation ID. A refusal for an address with no account names nobody. It is protected by the application guards and the PostgreSQL trigger of ADR-0012, which this decision extends to a second table.
12. **Keyed hashes for the sensitive lookup dimensions.** The submitted email address and the source address are stored only as HMAC-SHA256 values under Django's `SECRET_KEY`. That is enough to count attempts that belong together and not enough to read back what was submitted. The typed address is not stored, because it is sometimes a password. No password, password hash, session identifier, or request header is stored.
13. **It is not the general audit record.** AuditEvent remains future work.

### Throttling

14. **PostgreSQL-based and bounded.** Refusals are counted from the authentication events. There is no counter store, no new infrastructure, and no Redis.
15. **The limits are exactly:**
    - 5 refused sign-ins for one keyed email address within 15 minutes
    - 20 refused sign-ins from one keyed source within 15 minutes

    When either is reached, further attempts are refused with status 429 and the password is not examined.
16. **No permanent lockout.** The limit lifts by itself as refusals leave the 15-minute window. A successful sign-in clears the count for that email address. It does not clear the count for the source, so one valid account does not buy a source fresh attempts.
17. **Attempts are counted one at a time.** Attempts for the same email address, and from the same source, hold a PostgreSQL advisory lock for the length of the transaction, so attempts sent together cannot each be counted as the first.
18. **Storage is bounded per key.** A throttled attempt is logged and stores nothing. One email address can add at most 5 rows, and one source at most 20, in any window.
19. **The limits are repository settings.** They are not read from the environment.
20. **This is application-level brute-force mitigation. It is not denial-of-service protection.** Each attempt still costs a request and several queries.
21. **The source is the network address the application process sees.** No forwarded header is read, because a client can write one.

### The first Administrator

22. **A controlled management command.** `create_first_administrator` is run by a person at a terminal on the server. It asks for the email address, the password twice without showing it, and a phrase typed out as confirmation.
23. **It cannot be repeated.** It refuses if any Administrator role event exists, and the database allows one actor-less role event at most. The exception this makes to the role-event rules is defined in ADR-0012.
24. **No credential in an environment variable or a command-line argument.** The command has no option for an email address or a password and no non-interactive mode, reads nothing from the environment, and refuses to run without a terminal.
25. **The password passes Django's password validation**, and the account and its role event are created together or not at all.
26. **No public Administrator registration.** There is no web page, setting, environment variable, or database flag that creates an Administrator.

### Multi-factor authentication

27. **No MFA bypass in production.** Reviewer and Administrator privileges require an enrolled second factor (ADR-0007 rule 4). No second factor exists yet, so those privileges are unavailable, including to the first Administrator, who can sign in and do nothing administrative. The lookup that answers whether an account is enrolled returns no unconditionally and reads no setting, environment variable, request, session, or database value. The stand-in used by the test suite exists only inside the test process and is not part of the application.

## Alternatives considered

- **Django's `LoginView` with signals for the record and the throttle.** Less code, but both would sit outside the transaction that checks the password.
- **A third-party throttling package.** A dependency for something the event table already answers.
- **Redis counters.** Redis is not an accepted runtime dependency (ADR-0004 is Proposed), and sign-in would then depend on a second store.
- **A separate counter table.** It duplicates what the events say and needs its own clean-up.
- **Locking an account until an Administrator unlocks it.** It turns one mistake, or one attacker, into a locked account.
- **Storing the submitted email address and the network address in clear.** More useful to an investigator. It also stores mistyped passwords, and personal data for which no retention rule exists.
- **Trusting `X-Forwarded-For`.** Without a defined proxy it lets anyone choose their own source.
- **Bootstrap from environment variables or a non-interactive flag.** A credential there is readable by other processes and kept in history, and it is the hidden path ADR-0012 forbids.
- **A first grant attributed to the new Administrator or to an invented system account.** The first breaks the rule that nobody changes their own roles; the second records something untrue.

## Consequences

- Sign-in works with no new dependency and no new service.
- Every attempt costs several queries and holds a lock for the length of a password hash. Attempts for one email address, and from one source, are not concurrent.
- Anyone can keep a known email address throttled by failing five times every fifteen minutes. This is accepted as the cost of limiting guesses per account.
- An attacker using many sources and many email addresses is limited only per key. Limiting that belongs in front of the application.
- **Secret rotation.** The keyed hashes are derived from `SECRET_KEY`. Rotating it changes every key, so refusals recorded before the rotation no longer count towards a limit and earlier events can no longer be matched to later ones by address or source. Throttling starts from zero at that moment. This is an explicit, accepted trade-off of keeping no readable address.
- **Retention.** AuthenticationEvent is append-only and the table grows with use. Its retention is a future data-governance decision; no period is set here. Until that decision exists, application code must not delete events, silently or otherwise, and the database refuses it. A future retention policy must preserve what security and audit need and meet the legal obligations that apply, and it will need a privileged, recorded procedure, because the application's own role cannot remove these rows.
- If the only Administrator's credentials are lost, the bootstrap cannot be run again. Recovery is a deliberate operation on the database by its owner.

## Deferred

These are outside this decision. Each is a later increment or depends on deployment. None is an open question about what is decided above.

| Deferred | Where it belongs |
|---|---|
| TOTP enrolment and verification | A later authentication increment. Until then Reviewer and Administrator privileges are unavailable (point 27). |
| Account creation by an Administrator | A later increment. The first Administrator is the only account the application creates. |
| Password reset | A later increment |
| Email verification | A later increment |
| Account recovery | A later increment |
| Retention policy for authentication events | A data-governance decision (see Consequences) |
| Trusted client-source extraction behind a reverse proxy | Deployment, [ADR-0008](0008-deployment-strategy.md). Behind a proxy, the address the process sees is the proxy's, so every visitor would share one source. Which header to trust is defined with the proxy. |
| Production Content Security Policy | Deployment and the first pages with content, with ADR-0008 |
| Least-privilege database roles | Deployment, ADR-0008. They are what stops TRUNCATE and changes to the append-only triggers. |
| Django admin | After TOTP (ADR-0007 rule 8) |
| Redirecting an anonymous request for a protected page to sign-in | With the first workspace page. Such a request is answered 403 today. |
| The general audit record (AuditEvent) | Its own increment |

## Revisit when

TOTP is implemented; the deployment decision defines the reverse proxy; a retention policy is decided; or sign-in volume makes counting from the event table too slow.
