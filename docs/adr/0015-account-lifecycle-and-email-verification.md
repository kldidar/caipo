# ADR-0015: Account lifecycle, provisioning by an Administrator, and email verification

- Status: Accepted
- Date: 2026-10-03

## Context

[ADR-0007](0007-authentication.md) rule 3 says that accounts are created by an Administrator and that there is no public self-registration. [ADR-0013](0013-authentication-core-and-first-administrator-bootstrap.md) built sign-in and deferred account creation and email verification to later increments, so the first Administrator was the only account the application could create. [ADR-0014](0014-totp-mfa-and-authentication-assurance.md) added the second factor and its approval.

This ADR decides how every other account comes to exist and what states it passes through: how an Administrator creates it, how the person it is for proves that the email address is theirs, how that person gets a password that nobody else has seen, and how an account is disabled and enabled.

The project owner specified the requirements, directed the implementation, reviewed it, and accepted this ADR as implemented on 2026-10-03.

It decides nothing about password reset, account recovery, or which service delivers email. Those are listed under "Deferred".

## Decision

### Lifecycle

1. **Three states, stated explicitly.** `PENDING_VERIFICATION`: the account exists, and nobody has shown that its email address is theirs; it cannot be signed in to. `ACTIVE`: it can be signed in to, according to its roles and the second-factor policy. `DISABLED`: an Administrator disabled it; it cannot be signed in to and holds no permission. There are no other states.
2. **The state is stored once.** The account has a `status` column, and the earlier `is_active` flag is removed. What Django's authentication asks, whether an account is active, is derived from the status and cannot be set apart from it. A flag beside a status could disagree with it, and a flag alone cannot tell an account that awaits verification from one that was disabled.
3. **Two times keep what the state alone would lose.** `email_verified_at` is when the holder of the email address proved it was theirs. `activated_at` is when the account first became active. So the four things that must be told apart are: the account exists (a row), its address was verified (`email_verified_at`), it is active (`status`), it is disabled (`status`).
4. **The database holds the invariants.** The status is one of the three. An account that awaits verification was never verified and never active. An active account records when it became active. A disabled account keeps whatever history it had.
5. **A new account awaits verification unless something says otherwise.** That is the default of the column. The one path that creates an account active is the manager method the first-Administrator bootstrap uses.
6. **The first Administrator's address is not verified.** The bootstrap (ADR-0012, ADR-0014) creates that account active at the server. Nobody verified its address by email, and nothing marks it as verified.

### Creating an account

7. **Only an Administrator creates an account**, through one service. It requires a new permission, `accounts.create`, which only the Administrator role holds and which, like every Administrator permission, exists only for a sign-in verified against a trusted second factor (ADR-0014). No role check is added anywhere: the existing policy decides.
8. **There is no registration.** No page, setting, or request creates an account without an acting Administrator. The public page added by this decision activates an account that already exists and creates nothing.
9. **The Administrator names an email address and exactly one role, and never a password.** The role must be one of the four roles. It is granted by the existing role service under its own rules: the grant is a RoleEvent naming the Administrator, and it needs the permission to manage roles as well. Nothing is inherited, and the account receives no role other than the one named.
10. **A privileged role given at creation is not a privilege.** A Reviewer or Administrator account created this way is in `PENDING_VERIFICATION` like any other. Once active it holds, on its password, only the permission to manage its own second factor, and that second factor needs an Administrator's approval before the role confers anything (ADR-0014). The states it passes through are: awaiting verification; active without a second factor; second factor awaiting approval; second factor awaiting verification; second factor active. Only the last confers the role's permissions, and only to a sign-in verified with it.
11. **An Administrator that awaits verification is not an Administrator that remains.** The rule that the last Administrator cannot be removed (ADR-0012) counts active accounts.
12. **Creation is one transaction**: the account, its role event, its activation token, and the record of its creation, or none of them. The verification message is sent after that transaction. If it cannot be sent, the account exists and awaits a message, the Administrator is told, and the message is sent again.

### The password

13. **The owner of the account chooses the password, and nobody else ever has it.** There is no temporary password, none is emailed, and none is shown to the Administrator.
14. **A new account holds a password that nobody knows.** It is 256 random bits, hashed and discarded in the same statement. It is a real hash and not Django's "unusable" marker, so that a sign-in attempt for an account that awaits verification costs what an attempt for any other account costs: the time taken does not reveal that the account exists. The account cannot be signed in to in any case, because it is not active.
15. **The password is set only by activation**, with the token sent to the account's address, and it must pass the password validators. A password that fails them changes nothing and does not spend the token.

### The token

16. **One token does both jobs**: it verifies the address and authorises setting the password. Presenting it shows that the person can read mail sent to that address, which is the verification.
17. **Generated on the server, 256 random bits**, from the operating system's generator.
18. **Only a keyed hash is stored**: HMAC-SHA256 under `SECRET_KEY`, as for the other tokens (ADR-0013 point 12, ADR-0014 point 24). The token itself is in the message and nowhere else: not in the database, a log, an event, or a result.
19. **Bound to one account.** The token is looked up by its hash, and the row names the account. The operation takes no account from its caller, so a token cannot activate any other account.
20. **Single use.** Activation removes the row in the transaction that activates the account, and takes the account's row lock first. Presented again, or twice at once, it is refused.
21. **It lapses after 48 hours.** Long enough for a message sent on a Friday to be read on a Monday, and no longer: the token sets a password. It is a repository setting.
22. **At most one per account.** Sending the message again replaces the token, so an earlier message stops working at once. Disabling the account removes it.
23. **Refused for an account that does not await verification**, whatever row exists: an active or disabled account is never activated by a token.

### The activation flow

24. Administrator creates the account → `PENDING_VERIFICATION` → verification message → the person opens the link → chooses a password and submits it with the token → the token is checked → in one transaction the password is set, the address is marked verified, the account becomes `ACTIVE`, and the token is removed. Nobody is signed in by this; the person signs in afterwards like anyone else.
25. **The token never reaches the server in a URL.** The link carries it after a `#`, which a browser keeps to itself: it is in no request line, no access log, no proxy log, and no Referer header. A small script served from the application's own static files moves it into the form and removes it from the address bar, and the form sends it in the body of a POST. Without the script the person pastes it into the same field. A token in a query string is ignored.
26. **One answer for every refused token.** Unknown, malformed, used, replaced, lapsed, and belonging to a disabled or already active account give the same page with the same status, and nothing that was submitted is put back into it. Sign-in already answers alike for an account that does not exist, awaits verification, or is disabled (ADR-0013 point 8).
27. **Attempts are throttled per source**: 10 refused attempts within 15 minutes, counted in PostgreSQL from the account events, one attempt at a time for a source under an advisory lock, as in ADR-0013. After that, attempts are refused unexamined with status 429 and store nothing. A token cannot be guessed in any case; this bounds the rows a source can write.

### Email

28. **One boundary.** `caipo.core.mail.deliver` takes a recipient, a subject, and a plain-text body, and reports whether the message was handed on. It knows nothing of accounts, logs nothing, and is the only place that sends mail. Which service carries the message is configuration: Django's `EMAIL_BACKEND` setting names the implementation. No library is added.
29. **No delivery service is chosen, and none is configured for production.** That belongs to the deployment decision ([ADR-0008](0008-deployment-strategy.md), Proposed). Until then the default backend refuses every message, so nothing is sent by accident and the caller is told. In production, therefore, **an account can be created and its message cannot be sent**: provisioning is not usable there until ADR-0008 names a service. The application makes no outbound connection for email today.
30. **Development and tests send nothing.** Development writes each message to a file under `data/outbox/`, which git ignores, and not to the terminal, where it would sit among the logs. Tests keep messages in memory.
31. **The message** states what it is for, carries one link, says when the link lapses and that it works once, and says to ignore it if unexpected. It is the same for every recipient apart from the link. It names no person, address, or role, and holds no password, secret, or anything about what the account can reach.

### The public address of the site

32. **Links are built from a configured address, never from a request.** `PUBLIC_BASE_URL` is the scheme and host of the site. A request's Host header, and every forwarded header, is chosen by the client, and a link built from one could send a token-bearing page to another host.
33. **Production reads it from `CAIPO_PUBLIC_URL` and refuses to start without it.** It must be `https`, with a host and optionally a port, and nothing else: no path, query, fragment, or credentials. Development uses the address of the development server and tests a fixed one; neither reads the variable.

### Disabling and enabling

34. **`disable_user` and `enable_user` are service operations for an Administrator**, each behind its own permission (`accounts.deactivate`, which existed, and `accounts.enable`), each one transaction under the lock that serializes account changes (ADR-0012). `disable_user` is the earlier `deactivate_user` under the name of the state it produces. They have no page yet.
35. **Disabling takes effect on the account's next request.** Its password signs nobody in, its sessions stop being recognised, and every context of it holds no permission. Its roles, second factor, and history are kept.
36. **The last Administrator cannot be disabled** (ADR-0012 point 6, unchanged). An Administrator may disable their own account only while another active Administrator remains.
37. **Enabling returns an account to the state it was disabled in, and never further.** An account that had been activated becomes `ACTIVE` again, with the password, roles, and second factor it had. One that had never been activated becomes `PENDING_VERIFICATION` with no token, and needs a new message. Enabling never verifies an address or activates an account by itself.
38. **Nobody enables their own account.** A disabled account can do nothing, so this cannot arise; it is refused all the same.

### Records

39. **AccountEvent, a third append-only table**, protected by the application guards and the PostgreSQL trigger of ADR-0012. Six event types: `account_created`, `verification_sent`, `verification_succeeded`, `verification_failed`, `account_disabled`, `account_enabled`. Each names the account, except a refused verification whose token belongs to no account. What an Administrator does names that Administrator; what the owner does names no actor.
40. **It is not AuthenticationEvent, and not the general audit record.** AuthenticationEvent records sign-ins and second factors, is keyed by the submitted email address, and forbids an actor who is the account itself, which disabling one's own account requires. The general AuditEvent remains future work.
41. **It holds no token, token hash, password, or email address.** Where a verification attempt came from is kept only as a keyed hash.

## How it is enforced

- **In the policy.** The two new permissions are in the Administrator role's list and nowhere else.
- **In the services.** Each operation checks its permission inside its transaction, before it looks at anything else, so a caller without it learns nothing about accounts or inputs.
- **In the database.** The lifecycle constraints of point 4; one token row per account and a unique token hash; the event constraints of point 39; the append-only trigger.
- **By tests**, including each constraint directly, operations made at the same time, and a pass of deliberate faults placed in each of the checks above.

## Alternatives considered

- **Keeping `is_active` and adding a verified flag.** Two booleans give four combinations for three states, and cannot say what a disabled account was before.
- **Keeping `is_active` as a column beside `status`.** Two stored facts that must agree, kept so by a constraint, where one suffices.
- **Deriving the state from the events.** DATA_MODEL principle 5 applies to provenance records. An account's state is read on every request and on every authorization decision, and Django's authentication needs it on the row.
- **The Administrator sets a first password, to be changed at first sign-in.** The Administrator then knows a working credential, and it has to reach the person somehow.
- **Sending a password by email.** A credential in a mailbox, in clear, with no expiry.
- **Separate tokens for verification and for the password.** Two messages and two flows for one act by one person.
- **A signed, stateless token** (Django's password-reset token). No table, but it cannot be revoked by sending another, and its single use rests on the password hash changing.
- **The token in the path or query of the link.** Simpler, and needs no script, but the token is then in every access log between the person and the application.
- **An unusable password for a new account.** Simpler to explain. It makes a sign-in attempt for such an account measurably faster than for any other.
- **Building the link from the request.** No setting, and a Host header away from sending tokens elsewhere.
- **Adding the events to AuthenticationEvent.** One table fewer, at the cost of loosening the constraint that an actor is never the account.
- **A notification framework or a mail library.** Django sends mail; nothing else is needed for one message.
- **Public self-registration with later approval.** Forbidden by ADR-0007 rule 3.

## Consequences

- An Administrator can create accounts, and the first Administrator is no longer the only account. With ADR-0014, a second Administrator can now exist: created here, activated by its owner, and its second factor approved by the first.
- **Whoever opens the link first sets the password.** The token is a bearer credential for 48 hours. A person who can read the mailbox, or a mail system that follows links and runs scripts, could use it. The message says not to pass it on; sending it again revokes it.
- **Account creation is unusable in production until a delivery service is configured** (point 29).
- Production needs one more variable, `CAIPO_PUBLIC_URL`.
- The activation page is the first page that needs JavaScript to be convenient. It works without it.
- An Administrator sees the email addresses of accounts that await verification.
- An account that awaits verification and was never activated stays so indefinitely. Nothing removes it; an Administrator disables it.
- An existing account cannot change its email address, and an address is verified once, at activation.
- `SECRET_KEY` rotation invalidates outstanding activation tokens, as it does the other keyed hashes (ADR-0013). The messages are sent again.
- Behind a reverse proxy every visitor shares one source until ADR-0008 names the header to trust, so the activation throttle would count all visitors together. It would then refuse activations after ten refusals from anyone in fifteen minutes.
- The account-event table grows with use and has no retention period, as for authentication events.
- One migration replaces a column. Existing accounts keep their state: active stays active, deactivated becomes disabled.

## Deferred

| Deferred | Where it belongs |
|---|---|
| Password reset | A later increment |
| Account recovery, including a lost second factor | A later increment |
| Changing an account's email address, and verifying the new one | A later increment |
| Pages for disabling and enabling accounts, and for role administration | A later increment |
| The email delivery service, its credentials, and the sender address | Deployment, [ADR-0008](0008-deployment-strategy.md) |
| Telling an Administrator that a message bounced | With the delivery service |
| Removing accounts that were never activated | A data-governance decision |
| Retention of account events | A data-governance decision |
| Single sign-on, social sign-in, API tokens | Not part of launch (ADR-0007) |
| The general audit record (AuditEvent) | Its own increment |

## Revisit when

A delivery service is chosen; password reset or recovery is designed; an email address must be changeable; or the reverse proxy is defined.
