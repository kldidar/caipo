# ADR-0016: Password reset by email

- Status: Accepted
- Date: 2026-10-03

## Context

[ADR-0013](0013-authentication-core-and-first-administrator-bootstrap.md) built sign-in and deferred password reset. [ADR-0015](0015-account-lifecycle-and-email-verification.md) let an Administrator create accounts whose owners choose their own passwords, and stated that it decides nothing about password reset. Since then more than one account can exist, and a person who forgets their password has no way back: nobody else knows it, no Administrator can set it, and the only remedy is an operation on the database by its owner.

This ADR decides how the owner of an account replaces a forgotten password. The path is reached without being signed in and ends by changing a credential, so it is a security boundary of its own. [ADR-0014](0014-totp-mfa-and-authentication-assurance.md) made the second factor the thing that Reviewer and Administrator privileges rest on; whatever is decided here must leave that true.

The project owner specified the requirements on 2026-10-03, decided the four points that the proposal had left open and the answer that a throttled token submission gives (point 35), and accepted this ADR. Accepted by project owner on 2026-10-03. Unlike ADR-0013, 0014, and 0015, it was accepted before its implementation: nothing here is built yet.

It decides nothing about a lost second factor, account recovery, changing an email address, the general audit record, or which service delivers email. Those are listed under "Deferred".

## Decision

### Scope

1. **Password reset is for a forgotten password, and for nothing else.** A person who is not signed in asks for a message to be sent to an account's email address, and uses the token in it to choose a new password.
2. **It changes the password and nothing else.** It does not recover, disable, or replace a second factor. It does not change an email address. It signs nobody in. It is not a procedure for an account that may have been compromised.
3. **No Administrator takes part.** An Administrator cannot set, reset, or see another account's password, and cannot start a reset for another account. ADR-0015 point 13 stands: the owner of the account chooses the password, and nobody else ever has it.

### Which accounts

4. **Only an `ACTIVE` account can have its password reset.** The status of ADR-0015 decides, and nothing else is consulted.
5. **An account that awaits verification or is disabled is treated as an address with no account.** No message is sent and no token is issued. An account that awaits verification gets its password by activation, and its message is sent again by an Administrator (ADR-0015). A disabled account can do nothing until an Administrator enables it.
6. **The first Administrator is eligible although its address was never verified.** The bootstrap creates that account active at the server and nothing marks its address as verified (ADR-0015 point 6). Eligibility rests on the status, not on `email_verified_at`, so an active account whose `email_verified_at` is empty receives a reset message like any other active account. This is an explicit exception to the rule that a token-bearing message goes only to an address its holder has verified.
7. **The exception gives no privilege.** A reset changes the password. The account's second factor, its approval, and the assurance its roles require are untouched, so an Administrator whose password was reset holds, on that password, only the permission to manage its own second factor, as before (ADR-0014). Whoever controls the mailbox gains a password and no more.
8. **A reset does not verify an address.** `email_verified_at` is set by activation only. A successful reset leaves it as it was.

### Asking for a reset

9. **One answer for every request.** An address with no account, an account that awaits verification, a disabled account, an active account, and an active account whose address was never verified all give the same page with the same status, and no redirect or message that differs. So does a request that is throttled (point 23).
10. **Nothing submitted is put back into the page.** Not the email address, and not anything else. People type passwords into email fields.
11. **One logical flow for every request.** A request for an address that has an eligible account and a request for any other address go through the same steps in the application: the same locks, the same counts, one event recorded, the same answer. The one difference is that for an eligible account a token is issued and a message is handed to the email boundary. No status, response body, redirect, or message tells the two apart.
12. **The time a request takes is not equalized, and this is a known limitation.** The message is handed on inside the request, so a request for an eligible account may take measurably longer than one for any other address once a real delivery service is used. This decision adds no artificial delay and no new way of sending mail outside the request. Equalizing delivery time belongs to the email-delivery and asynchronous-job decisions ([ADR-0008](0008-deployment-strategy.md), [ADR-0004](0004-asynchronous-jobs.md), both Proposed). Until then the system does not claim that the existence of an active account cannot be inferred from timing.
13. **Asking is POST-only and CSRF-protected.** The page is fetched with GET; the address is accepted only by POST and never travels in a URL.

### The token

14. **Generated on the server, 256 random bits**, from the operating system's generator.
15. **Only a keyed hash is stored**: HMAC-SHA256 under `SECRET_KEY`, as for the other tokens (ADR-0013 point 12, ADR-0014 point 24, ADR-0015 point 18). The token itself is in the message and nowhere else.
16. **Bound to one account.** The token is looked up by its hash, and the row names the account. The operation takes no account from its caller.
17. **Single use.** A successful reset removes the row in the transaction that sets the password, and takes the account's row lock first. Presented again, or twice at once, it is refused.
18. **It lapses after 1 hour.** It is a repository setting.
19. **At most one per account.** A new request replaces the token, so an earlier message stops working at once.
20. **Disabling the account removes it**, in the transaction that disables the account, as disabling removes an activation token (ADR-0015 point 22). Enabling the account restores nothing: a new request is needed.
21. **Refused for an account that is not `ACTIVE`**, whatever row exists.
22. **The token never reaches the server in a URL.** As for activation (ADR-0015 point 25): the link carries it after a `#`, a script served from the application's own static files moves it into the form and removes it from the address bar, and the form sends it in the body of a POST. Without the script the person pastes it into the same field. A token in a query string is ignored. No log line, event, or result holds the token, its hash, the link, or a password.

### Throttling of requests

23. **Two independent limits on asking, exactly:**
    - 5 reset requests for one keyed email address within 1 hour
    - 20 reset requests from one keyed source within 15 minutes

    When either is reached, further requests issue no token and send no message. The answer is the one of point 9, not status 429: a different answer for one address would say something about it.
24. **Counted as sign-in attempts are counted** (ADR-0013 points 14, 17, 18, and 21): from the authentication events in PostgreSQL, one request at a time for a source and for an email address under an advisory lock, with no counter store. A request is counted whether or not its address has an account. A throttled request is logged and stores nothing.
25. **The source is the network address the application process sees.** No forwarded header is read. Extracting the real client address behind a reverse proxy stays with the deployment decision (ADR-0008).
26. **The limits are repository settings.** They are not read from the environment.

### Setting the password

27. **The new password must pass the password validators** already configured. A password that fails them changes nothing and does not spend the token.
28. **One transaction**: the token is checked, the password is set, the token is removed, any pending second-factor challenge is removed, and the event is recorded, or none of them.
29. **Nobody is signed in by it.** The person signs in afterwards like anyone else, and gives a second-factor code if the account has a second factor.
30. **Roles and the second factor are unchanged.** The reset reads and writes no role event and no second-factor device: not its state, its secret, or its approval. The policy that says which roles need which assurance is unchanged. A reset is not a recovery of a second factor.
31. **Sessions established under the old password stop being recognised.** Django binds a session to the password hash it was established under and checks it on every request. Sign-in uses that machinery (ADR-0013 point 2), so a changed password ends every session of the account on its next request. Nothing is added; a test proves it.
32. **A sign-in that awaits its second-factor code does not survive either.** A pending challenge (ADR-0014) exists because the old password was accepted. It is not a session, so point 31 does not reach it. A successful reset removes every pending challenge of the account; ADR-0014 allows an account one at most. Whoever held it must give the new password to get another. The device the challenge would have been answered with is not touched.
33. **Sign-in throttling is untouched.** A reset does not clear, shorten, or otherwise affect the count of refused sign-ins for the email address or the source (ADR-0013 point 16), nor the count of refused second-factor codes (ADR-0014 point 30). Only a successful sign-in clears the former, and nothing clears the latter early.
34. **One answer for every refused token.** Unknown, malformed, used, replaced, lapsed, and belonging to an account that is not active give the same page with the same status, and nothing that was submitted is put back into it.
35. **Refused tokens are throttled per source**: 10 refused submissions of a token from one keyed source within 15 minutes. This limit is on the step that sets the password and is separate from the limits of point 23, which are on asking. It works as the limit on activation attempts does (ADR-0015 point 27): counted in PostgreSQL from the `password_reset_failed` events, one attempt at a time for a source under an advisory lock. A token cannot be guessed in any case; this bounds the rows a source can write. It is a repository setting.

    When the limit is reached, further submissions from that source are refused with status 429. They are refused unexamined: the token is not looked up, so the answer is the same whether or not it belongs to an account, and a valid token is not spent. Nothing is stored. The project owner decided this answer, and decided that it differs on purpose from the page that takes a reset request, which gives its one answer even when throttled (point 23).
36. **Setting the password is POST-only and CSRF-protected.**

### Records

37. **AuthenticationEvent records it**, with three new event types: `password_reset_requested`, `password_reset_succeeded`, and `password_reset_failed`. A reset is an act on a credential, keyed by a submitted email address, and counted for throttling by that address and by source. Those are the columns and indexes AuthenticationEvent already has (ADR-0013 points 11 and 12).
38. **The keyed hashes are the existing ones.** The submitted email address and the source address are stored only as HMAC-SHA256 values under `SECRET_KEY`. A request names the account if the address belongs to one, and nobody otherwise. A refused token that belongs to no account names nobody.
39. **None of these events names an actor.** The account's owner, or nobody known, caused them.
40. **They hold no token, token hash, password, session identifier, or link.**
41. **It is not the general audit record.** AuditEvent remains future work.

### Email

42. **The existing boundary is used.** `caipo.core.mail.deliver` sends the message (ADR-0015 point 28). No library is added and no delivery service is chosen: that belongs to ADR-0008. Until it is decided the default backend refuses every message, so **in production a reset can be asked for and its message cannot be sent**.
43. **The link is built from `PUBLIC_BASE_URL`**, never from a request (ADR-0015 point 32).
44. **The message** states what it is for, carries one link, says when the link lapses and that it works once, and says to ignore it if unexpected. It is the same for every recipient apart from the link, and names no person, address, or role.

## Security rationale

- **Why a reset does not touch the second factor.** A reset proves one thing: that the person can read mail sent to the account's address. For a Reviewer or Administrator, the second factor exists so that the password alone, however it was obtained, is not enough (ADR-0007 rule 4, ADR-0014). If a reset could disable or replace the second factor, a mailbox would be worth a password and a device together, and the second factor would protect nothing against anyone who could read the mail.
- **Why email alone is not a replacement for a second factor.** A mailbox is a different kind of proof from a device the person holds: it can be read by a mail provider, a forwarding rule, a shared inbox, or whoever took over the mail account. ADR-0014 point 34 declined recovery codes because they are a weaker credential that bypasses the device. A mailbox that could stand in for the device would be the same thing with less control.
- **Why nobody is signed in by a reset.** Signing in is one path with its own throttle, record, and second-factor step (ADR-0013 point 10, ADR-0014). A reset that established a session would be a second way in that skipped the code. Sending the person to the sign-in page costs one step and keeps one path.
- **Why existing sessions and pending challenges end.** A person often resets a password because they fear someone else knows it. Nothing that was obtained with the old password may outlive it: not a session, and not a sign-in that has passed the password step and awaits its code. Removing the challenge takes nothing from the second factor; it only makes the next sign-in start from the new password.
- **Why 1 hour and not the 48 hours of activation.** The activation token sets the first password of an account that holds nothing and that nobody has ever used; it has to survive a weekend because the person did not ask for it and may not read it at once (ADR-0015 point 21). A reset token replaces the password of a working account, was asked for a moment ago by the person who will use it, and is worth more to whoever intercepts it. A shorter life costs the person little.
- **Why one answer and why throttling.** The request page takes an email address from anyone. A different answer for a known address would tell an anonymous visitor who has an account, which sign-in already refuses to reveal (ADR-0013 point 8). Without a limit per address the page could be used to fill a person's mailbox; without a limit per source one source could try addresses, and add rows, without bound. The limit on refused tokens bounds the rows that the second page can be made to write.
- **Why a disabled account keeps no token.** Disabling takes effect at once (ADR-0015 point 35). A token that waited through the disabling and worked again after the account was enabled would be a credential that outlived an Administrator's decision to stop the account.
- **Why timing is not equalized here.** A fixed artificial delay hides a difference only while delivery is faster than the delay, and holds a request open for no work. Sending the message outside the request needs a job system, which is not chosen (ADR-0004). Either would be a mechanism invented for one page before the delivery service it must fit is known. The limitation is stated instead (point 12).

## How it is to be enforced

- **In the service.** One service takes a request and one sets the password. Each makes its decision inside its transaction. The views handle the form and contain no reset logic. The service that disables an account removes its reset token.
- **In the database.** One token row per account and a unique token hash. The event-type constraint of AuthenticationEvent is extended by the three types. The constraint that only a failed sign-in may name no user (ADR-0013 point 11) is extended to a reset request and a refused reset, for an address or a token that belongs to no account. The append-only trigger already covers the table.
- **By tests**, including each refusal, each constraint directly, the same token presented twice at once, the two limits on asking and the limit on refused tokens, the sameness of the answers, the absence of tokens and addresses from events and logs, that a session and a pending challenge established before a reset are refused after it, that the second factor is as it was, and that disabling an account removes its token and enabling does not bring it back.

## Alternatives considered

- **An Administrator sets or resets the password.** The Administrator then knows a working credential, and it has to reach the person somehow. ADR-0015 point 13 rejected this for the first password, and the reasons are the same for a later one. It also turns one compromised Administrator session into every account's password.
- **A reset that also disables or replaces the second factor.** One flow for every lost credential, and a mailbox would then be enough to take over a privileged account. A lost second factor is a separate design (see "Deferred").
- **Signing the person in after a successful reset.** One step fewer. It needs either a second sign-in path without the second-factor step or the step repeated inside the reset.
- **AccountEvent for the records.** A reset could be seen as a step in an account's lifecycle. AccountEvent has no keyed email address, which the limit per address needs, and its events are about the state of an account, which a reset does not change (ADR-0015 points 39 and 40).
- **The 48-hour lifetime of the activation token.** One setting fewer. See "Security rationale".
- **Throttling by source only.** Many sources could then send unlimited messages to one address. And behind a reverse proxy, until ADR-0008 is decided, every visitor shares one source, so the limit per source alone would be either the only protection or a limit on everyone at once.
- **Status 429 for a throttled reset request**, as sign-in gives. Sign-in's limit is reached only by refusals, which say nothing about an account. Here one of the two limits is per email address, the page otherwise always gives one answer, and a throttled request gives it too.
- **The refused-token page, and not status 429, for a throttled token submission.** It would match the request page. The limit on token submissions is per source only and is applied before the token is looked up, so status 429 says nothing about any token or account, and it tells a person why a valid link is not being accepted. Activation answers the same way (ADR-0015 point 27).
- **No limit on refused tokens**, because a token cannot be guessed. The limit is not there against guessing; without it one source could write events without bound.
- **A fixed delay on every request, or sending the message from a background job.** See "Security rationale", and point 12.
- **Leaving a pending second-factor challenge in place.** It lapses within five minutes by itself (ADR-0014). For those minutes a person who knew the old password and the device's code could still complete a sign-in begun before the reset.
- **Keeping the token of a disabled account**, refused while the account is disabled. It would work again if the account were enabled within the hour.
- **A signed, stateless token** (Django's password-reset token). No table, but it cannot be revoked by asking again or by disabling the account, and its single use rests on the password hash changing. ADR-0015 rejected it for activation for the same reasons.
- **Requiring a verified address.** Consistent with activation, and it would leave the first Administrator, whose address is never verified, without a reset.

## Consequences

- A person who forgets their password can replace it without anyone else being involved, within limits on how often and for how long.
- A password reset is never a way round the second factor. A Reviewer or Administrator who resets a password still needs a code from the approved device before the role confers anything.
- **A person who has lost both password and device is not helped.** Nor is a person who has lost only the device. Both need the recovery design that is still deferred.
- **Whoever opens the link first sets the password.** The token is a bearer credential for 1 hour. A person who can read the mailbox can take the password of an account without a second factor, and with it the account. For Reader and Researcher accounts that have not enrolled voluntarily, the mailbox is therefore as strong as the account gets.
- **Timing may reveal that an address has an active account** (point 12). The answers are the same; the time taken is not guaranteed to be. This stays open until email delivery and the job system are decided.
- **Reset is unusable in production until a delivery service is configured** (point 42), as account creation is.
- **The first Administrator's address receives a credential-bearing message without ever having been verified** (point 6). If that address was mistyped at the bootstrap, the message goes to whoever holds the mistyped address. They gain the password and not the second factor.
- **Anyone can keep an address from being reset** by asking five times an hour for it, and anyone can make the person's latest message stop working by asking again (point 19). This is accepted as the cost of limiting messages per address, as ADR-0013 accepts it for sign-in.
- **Throttling can inconvenience the person it protects.** A person who asks five times in an hour waits, and is not told why, because a throttled request gives the same answer as any other.
- Behind a reverse proxy every visitor shares one source until ADR-0008 names the header to trust. Twenty requests from anyone in fifteen minutes would then stop resets for everyone, and ten refused tokens from anyone would stop every reset from being completed for that time.
- A person who resets a password while a sign-in of theirs awaits its code starts that sign-in again.
- Disabling an account does one more thing than ADR-0015 describes: it removes the account's reset token as well as its activation token.
- `SECRET_KEY` rotation invalidates outstanding reset tokens and starts the counts from zero, as it does for the other keyed hashes (ADR-0013).
- The authentication event table gains rows from two unauthenticated pages, bounded per address and per source by points 23 and 35. It still has no retention period.
- Two more public pages take input from anonymous visitors.
- One migration adds a table and changes two constraints on AuthenticationEvent. It changes no existing row.

## Deferred

| Deferred | Where it belongs |
|---|---|
| Recovery from a lost second factor, recovery codes, administrator-assisted reset of a second factor | A later authentication increment (ADR-0014) |
| Account recovery after a suspected compromise | A later authentication increment |
| Changing a known password while signed in | A later increment |
| Changing an account's email address | A later increment (ADR-0015) |
| The email delivery service, its credentials, and the sender address | Deployment, [ADR-0008](0008-deployment-strategy.md) |
| Equalizing the time a reset request takes | With email delivery and the job system, ADR-0008 and [ADR-0004](0004-asynchronous-jobs.md) |
| The real client address behind a reverse proxy | Deployment, ADR-0008 |
| Telling the person, by a second message, that their password was changed | With notifications, a later increment |
| Retention of authentication events | A data-governance decision |
| The general audit record (AuditEvent) | Its own increment |

## Revisit when

A delivery service is chosen; the reverse proxy is defined; a job system is chosen; recovery from a lost second factor is designed; or the limits prove too strict or too loose in use.
