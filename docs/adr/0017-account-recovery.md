# ADR-0017: Account recovery after loss of the second factor

- Status: Accepted
- Date: 2026-10-04

## Context

[ADR-0014](0014-totp-mfa-and-authentication-assurance.md) made the TOTP second factor the thing that Reviewer and Administrator privileges rest on, and deliberately built no way back for a person who loses the device. Its points 34 and 35 say so, and its "Deferred" table sends recovery to "a later authentication increment". [ADR-0015](0015-account-lifecycle-and-email-verification.md) and [ADR-0016](0016-password-reset.md) each deferred it again. ADR-0016 added a way back for a forgotten password and stated that it recovers nothing else.

What exists today for a lost device is an operation on the database by its owner, outside the application: deleting the account's device row. For the only Administrator that is not enough, and the operation must also write an approval (ADR-0014, amendment, "Consequences"). Nothing records that it was done, by whom, or why.

Recovery is the path by which a person who cannot show a second factor comes to hold one again. Whatever that path accepts in place of the device is, in effect, a second way to obtain everything the device protects. It is a security boundary of its own, and the place where the properties of ADR-0014 and ADR-0016 are most easily undone.

The accepted decisions fix the following, and it holds today. ADR-0014 prohibits:

- **Recovery codes** (point 34).
- **An Administrator removing or issuing another account's second factor** (point 35). Removing a second factor is self-service only and needs the password and a current code together (point 33).
- **Any path by which a password, a mailbox, or both establish a trusted second factor.** A device is trusted only if an Administrator approved its enrolment or the first-Administrator bootstrap established it (amendment, points 1 and 13).
- **Bypassing the approval model.** A new device inherits no trust, a device enrolled without approval never becomes trusted, and replacing an active device needs both proofs and then approval (amendment, points 12 and 14).

Also fixed elsewhere:

- The bootstrap works once and cannot be run again ([ADR-0012](0012-authorization-and-role-event-integrity.md) amendment, point 7; [ADR-0013](0013-authentication-core-and-first-administrator-bootstrap.md) point 23).
- A password reset changes the password and nothing else, signs nobody in, and is never a way round the second factor. No Administrator sets, sees, or starts another account's credential (ADR-0016 points 2, 3, 29, and 30).
- Nobody acts on their own roles, approves their own enrolment, or enables their own account (ADR-0012 point 5, ADR-0014 amendment point 8, ADR-0015 point 38).
- No email is delivered in production until [ADR-0008](0008-deployment-strategy.md) names a service.

What this ADR changes in ADR-0014 is listed under "Changes to ADR-0014". Everything else above stays as it is.

The project owner decided the points of this ADR on 2026-10-04 and accepted it. Accepted by project owner on 2026-10-04. Like ADR-0016, it was accepted before its implementation: nothing here is built yet.

It decides nothing about changing an email address, changing a known password while signed in, the general audit record, the rotation of the TOTP encryption key, or which service delivers email.

## Decision

In short: the owner of a Reviewer or Administrator account asks for recovery from a sign-in whose password was accepted. An Administrator who is signed in with a trusted second factor authorises that one request, which revokes the lost device. The owner then enrols a new device in the ordinary way, and a different Administrator approves it. Nobody is signed in by any of it, and no step creates a trusted device. An Administrator for whom the other Administrators this needs do not exist is recovered by a command at the server's terminal, which is equally unable to set a password or create a trusted device.

### Security properties

Binding on the design and on its implementation. Each is to be proved by tests.

1. **Recovery confers no assurance.** No step of recovery returns an authentication context, raises a session, or marks a device trusted. `MFA_VERIFIED` keeps the three conditions of ADR-0014: the claim, the account's active device, and trust in that device.
2. **A recovered account is not trusted until the approval path has been followed.** Its roles confer nothing more than they do today on a password until a new device has been approved and a sign-in verified against it.
3. **A compromised password alone gains nothing.** It can make a request. It cannot authorise one, and it cannot reach `MFA_VERIFIED` through one.
4. **A mailbox alone gains nothing, and a password adds nothing to a mailbox.** ADR-0016 lets whoever reads the mailbox set the password. A password and a mailbox are therefore one chain of evidence, not two. Together they create no second-factor assurance. Possession of a mailbox must not silently become a replacement for a second factor.
5. **A password reset does not compose with recovery into a takeover by mailbox alone.** A reset authorises nothing in a recovery, invalidates a request made before it, and holds a recovery back for 24 hours.
6. **An Administrator cannot silently take over another account.** No step gives an Administrator another account's password, secret, code, or token. Authorising a recovery and approving the device that follows are done by two different Administrators. Each act is recorded naming who did it and is visible to the account's owner and to the other Administrators.
7. **Nobody acts in the recovery of their own account** by their own authority. The service refuses it and a database constraint refuses its record.
8. **Nobody is signed in by recovery.** Signing in stays one path, with its throttle, its record, and its second-factor step.
9. **Recovery changes the second factor, and ends what was obtained under the old one. It changes nothing else**: not the password, the status, the email address or its verification, the roles, nor the counts that throttle sign-in and second-factor codes.
10. **Recovery does not reveal which addresses have accounts, or which accounts have a second factor.** Whether an account has one stays visible only after its password was accepted (ADR-0014 point 28).
11. **Every recovery action is rate-limited and recorded**, in PostgreSQL, in an append-only table.
12. **No secret and no evidence is logged or recorded.**
13. **Every recovery can be seen by the owner and by the other Administrators, and is delayed where the risk is highest**: a recent password reset holds it back for 24 hours.
14. **The security of recovery never rests on an email being delivered.** A message informs. No step is safe only if a message arrives, and no step waits for one.

### Scope and eligibility

15. **Recovery is for accounts whose roles require a second factor: Reviewer and Administrator.** Whether an account qualifies is decided by the existing policy function, from the roles on record, when the request is made and again when it is authorised.
16. **The account must be `ACTIVE` and have an active second factor**, trusted or not. An account whose second factor merely awaits approval or its first code needs no recovery: it signs in on its password and asks again, as ADR-0014 already allows.
17. **Reader and Researcher accounts do not use this recovery flow.** Their second factor is voluntary and confers nothing under the current policy. A Reader or Researcher who enrolled and lost the device is not helped by this decision: the remedy of ADR-0014 point 35 remains theirs.
18. **`PENDING_VERIFICATION` and `DISABLED` accounts are refused.** The first has never signed in and has no second factor. Disabling is an Administrator's decision to stop the account, and recovery does not act on it; the account is enabled first.
19. **Recovery is for a second factor its owner can no longer use.** It is not a procedure for an account that may have been compromised. That account is disabled (ADR-0015).
20. **No recovery codes.** ADR-0014 point 34 stays in force unless a later ADR changes it.

### Initiation

21. **The owner of the account starts a recovery, and nobody else can.** No Administrator can start one, so no recovery exists that nobody with the account's password asked for.
22. **A request is made from a sign-in that awaits its code.** The password was accepted and a pending second-factor challenge exists (ADR-0014 point 23). The submission takes the challenge and nothing else: no form field, parameter, header, or cookie names an account. It is a POST with a CSRF token.
23. **Creating the request uses up the challenge.** The challenge is removed in the transaction that creates the request, and nobody is signed in by it. To continue signing in, the person gives the password again.
24. **The request changes nothing about the account.** It authorises nothing. The device stays active, the sessions stay as they are, and the real owner can still sign in with the device. Nobody can remove a second factor, or lock an account, by asking.
25. **A request has a number**, shown to the person who made it and to the Administrators who may authorise it, as an enrolment request has (ADR-0014 amendment, point 7). An account has at most one request. A new one replaces it and has another number.
26. **A request lapses after 30 minutes.** The person reaches an Administrator first and asks second.
27. **The possibility of asking is shown only after the password was accepted.** No page that a person who is not signed in can reach takes an email address for recovery.

### Evidence

28. **The password is required**, because a request is made only from a sign-in whose password was accepted. It is never sufficient.
29. **Verification through the email address is not required, for safety or for operation.** No step of recovery sends a token or waits for a message, so recovery does not depend on a delivery service.
30. **A verified email address may contribute evidence**: an Administrator may use it as one of the ways of reaching the person. It is never sufficient, alone or with the password, and it is never the only authority for restoring a second factor.
31. **An address that was never verified is not evidence.** `email_verified_at` empty means that nobody showed the address to be theirs. This is the position of the first Administrator (ADR-0015 point 6), who cannot rely on that address for any part of a recovery.
32. **The evidence that is independent of the mailbox is the authorisation**: an Administrator who is already trusted identifies the person by a means other than this system and authorises the one request whose number the person gives. The system records who authorised. It cannot check that they asked.
33. **The proof is not stored.** What is recorded is that the Administrator confirmed it, never how.

### Authorisation and separation of duties

34. **A recovery is authorised by a trusted Administrator, for another account, with an explicit confirmation.** It requires a new permission that only the Administrator role holds and that, like every Administrator permission, exists only at `MFA_VERIFIED`. Over HTTP it is a POST with a CSRF token and a ticked confirmation, names the request by its number in the path, and takes nothing else from the browser.
35. **No Administrator authorises the recovery of their own account.** An Administrator's own account can never be recovered by that Administrator.
36. **A request can be rejected**, under the same permission and the same rule. It is removed, and the account may ask again.
37. **The Administrator who authorised a recovery does not approve the device that follows.** The approval of an enrolment is refused for an actor who authorised the account's most recent recovery, until a trusted device of the account has become active.
38. **An authorisation is refused unless**, inside its transaction and under the account's second-factor lock:
    - the request is the account's current one and has not lapsed;
    - the request was made after the account's latest successful password reset;
    - the account is still eligible;
    - the cooling-off has passed;
    - an Administrator who is able to act, and who is neither the actor nor the account, exists to approve the device that follows.
39. **An Administrator is able to act** if the account is active, holds the role on record, and has an active, trusted second factor. This is narrower than the count ADR-0012 uses for the last-Administrator rule, which that decision keeps: an Administrator who lost the device is still an Administrator on record and can do nothing.

### Privileged accounts

40. **Recovering a Reviewer takes two Administrators**: one authorises, a different one approves the new device.
41. **Recovering an Administrator takes two Administrators other than the one being recovered**, each able to act on a second factor of their own: one authorises, a different one approves the new device. Neither is the account itself. Three Administrators must therefore exist for one of them to be recovered inside the application.
42. **A Reviewer cannot authorise or approve.** Both are Administrator permissions.
43. **A Reviewer for whom two Administrators who are able to act cannot be found is not recovered** until they exist. The break-glass procedure is never used for a Reviewer.
44. **An Administrator for whom two others cannot be found is recovered by the break-glass procedure**, and by nothing else.

### The new device

45. **Authorising revokes the lost device and finalises the recovery. In one transaction:**
    - the account's device and its secret are deleted;
    - every signed-in session of the account is ended;
    - every pending second-factor challenge of the account is removed;
    - any password-reset token of the account is removed;
    - the recovery request, and any other of the account, is removed;
    - the authorisation is recorded, naming the Administrator.
46. **Ending the sessions must not change the password**, and takes effect on the account's next request, as disabling an account does. No mechanism for it exists today: Django binds a session to the password and cannot find the sessions of one account. One is built with this decision. Activation tokens are not involved: only an account that awaits verification has one, and it is not eligible.
47. **Authorising issues no secret and creates no device.** After it the account has no second factor. Its password signs it in at `PASSWORD_AUTHENTICATED`, and it enrols as ADR-0014 says any such account does: the password again, a secret shown once to whoever asked, a request number, an Administrator's approval of that number, and a first code.
48. **The new device is trusted because of that approval and its first code, and for no other reason.** It inherits nothing from the device that was lost.
49. **A recovery is complete when the new, approved device accepts its first code.** That is recorded. It signs nobody in beyond what confirming an enrolment already does in ADR-0014.

### Cooling-off after a password reset

50. **A recovery is not finalised within 24 hours of the account's latest successful password reset.** An authorisation is refused until the period has passed, and so is the break-glass procedure.
51. **A request made before the account's latest successful password reset is invalid.** It was made on a password that no longer exists. It is refused at authorisation and by the break-glass procedure, whatever its age.
52. **A request made during the period lapses before it can be authorised.** The person asks again when the period has passed.
53. **This is a control in recovery, not in password reset.** A reset does not read, write, or know of a recovery. Recovery reads when the last reset succeeded from the authentication events. One statement of ADR-0016 gains an addition and is otherwise untouched: its reset token is also removed when a recovery is finalised (point 45), as it is when the account is disabled.
54. **Why.** A reset shows that someone reads the mailbox. Without a delay, that person could pass straight from the mailbox to a password and from the password to a recovery request, and the only thing left between them and the account would be how carefully two Administrators check. The delay gives the real owner a day in which the old password stops working and the reset is noticed.

### Loss of the password as well as the second factor

55. **Supported as two operations in sequence, when the reset channel is available.** The password is reset as ADR-0016 decides. The second factor is then recovered as this ADR decides, after the cooling-off. The first Administrator may reset its password although its address was never verified (ADR-0016 point 6); that gives it a password and no evidence.
56. **The two stay separate security boundaries.** A password reset never starts, advances, authorises, or completes a recovery. A recovery never sets a password and never issues, uses, or extends a reset token.
57. **What a mailbox alone can reach**: a password, then a wait of 24 hours, then a request, then an Administrator who must be persuaded to authorise the request's number, then another who must be persuaded to approve a device. It reaches no assurance by itself.
58. **Loss of the password, the second factor, and the email address together is not supported.** Nothing in this ADR sets or knows another person's password. If the password cannot be reset through ADR-0016, the account is not recovered by this design, and the break-glass procedure does not change that: it requires a request, and a request requires the password.

### Break-glass

59. **It exists for one case: an Administrator who lost the second factor, when the two other Administrators that the normal path requires do not exist.** That includes the only Administrator. It does not exist for a Reviewer, whatever the number of Administrators, and it does not exist for any other purpose.
60. **There is no bypass on the web.** No page, API, setting, environment variable, header, cookie, or request performs or shortens it. It is not an operation that an authenticated account can reach, whatever its role.
61. **It is a management command in the repository, `recover_mfa_break_glass`**, in the manner of `create_first_administrator`. It is interactive: it is run by a person at a terminal on the server and refuses to run unless both its input and its output are a terminal. It asks for the account, for a request number, and for a phrase typed out as confirmation. It takes no option, has no non-interactive mode, and reads nothing from the environment.
62. **It handles no secret.** It neither asks for nor accepts a password, a second-factor secret or code, or a token, by argument, by environment variable, or at the prompt, and it shows none.
63. **It can do two things, each only where the Administrator it stands in for does not exist:**
    - **Revoke the lost device**, in place of the authorisation, when two other Administrators who are able to act do not exist. It takes the number of the account's current recovery request, observes every condition of an authorisation other than the existence of the Administrators, and has every effect of point 45.
    - **Approve one pending enrolment request**, in place of the Administrator's approval. It takes that request's number. It is allowed only for the enrolment that follows a recovery of that account, and only when no Administrator who may approve it exists. The device then awaits its first code like any approved enrolment, and becomes active only when its owner gives a right code in the application.

    Where one other Administrator is able to act, the command revokes and that Administrator approves. For the only Administrator, the command does both.
64. **It does not create a trusted device.** It issues no secret, creates no device, marks nothing active, and signs nobody in. It restores the account to the state from which the ordinary enrolment establishes the new device.
65. **It sets no password** and changes no role, status, or email address. It is not a password reset, and it cannot be used as one.
66. **It refuses where the application's own path is available.** If Administrators who can authorise and approve exist, they do. It refuses an account that does not hold the Administrator role.
67. **Its event names no application actor.** The person who runs it is not an account of the application, and may have none. No account, real or invented, is recorded as having acted.
68. **Who ran it is captured by the operational audit trail of the server**, not by the application: the application has no model of operators and none is added for one command. What that trail is, and the instructions for running the command, belong to the deployment documentation under ADR-0008, which is Proposed. They do not exist yet. This ADR links to them from here when they do.
69. **This is a new, narrow exception to ADR-0014**, whose amendment says that only an Administrator's approval or the first-Administrator bootstrap makes a device trusted, and that the bootstrap is the only exception. An approval given by this command is a third source of trust. It is stated here as such, and nowhere is it implied by anything else.
70. **The bootstrap is unchanged.** It still works once. The command creates no account and no role event.

### Throttling

71. **The limits are exactly:**
    - 5 recovery requests for one account within 1 hour
    - 20 recovery requests from one keyed source within 15 minutes
    - 10 failed recovery submissions from one keyed source within 15 minutes
72. **A failed recovery submission is one that reached the step that examines it and was refused there by the application itself**: its challenge is unknown, has lapsed, or was already used up, or its account is no longer eligible. It is recorded as `mfa_recovery_failed`, and that event records nothing else. An Administrator's rejection is a decision and is recorded as `mfa_recovery_rejected`. An authorisation that is refused under point 38, because the request lapsed, the cooling-off has not passed, no Administrator exists to approve, or for any other of its conditions, is neither: it records no `mfa_recovery_failed` and is not counted against the limit on failed submissions.
73. **Counted as sign-in attempts are counted** (ADR-0013 points 14, 17, 18, and 21): from the authentication events in PostgreSQL, one at a time for an account and for a source under an advisory lock, with no counter store and no Redis. Requests are counted from `mfa_recovery_requested` events and failed submissions from `mfa_recovery_failed` events. The source is the network address the process sees.
74. **The two limits by source are applied before the challenge or any account is looked up, and a submission they stop is refused with status 429.** It stores nothing, uses up no challenge, and replaces no recovery request. The response is the same in every observable respect whether or not the challenge it carried exists, so it does not reveal whether an account, a challenge, or a recovery request exists.
75. **The limit for one account is applied only after the submitted challenge has identified the account**, because nothing else in the submission does. A submission refused by it stores nothing, uses up no challenge, and replaces no request. Only a person whose password was accepted can meet it.
76. **Nothing resets a count early.** Recovery does not clear the counts of refused sign-ins or refused codes.
77. **The limits, the 30-minute lifetime of a request, and the 24-hour cooling-off are repository settings.** They are not read from the environment.

### Notifications

78. **Recovery can be seen inside the application without any message.** The owner is shown, when next signed in, that the second factor was recovered and when. The Administrators see every request, rejection, authorisation, and use of the break-glass procedure on an administration page.
79. **When a delivery service exists**, the owner of the account is sent a message when a request is made for it and when a recovery is finalised, and the other Administrators are sent one when a recovery is finalised or the break-glass procedure is used. A message goes only to an address that was verified. It goes through the existing email boundary. A message that cannot be sent is logged and changes nothing.
80. **A message** is the same for every recipient, names no person, address, or role, and carries no token and no link that acts (ADR-0016 point 44).
81. **Nothing waits for a notification.** Until ADR-0008 names a service, none is delivered, and recovery works as decided.

### Records

82. **AuthenticationEvent records recovery, with six new event types.** The names are fixed, because the table is append-only and its rows cannot be renamed.

| Event type | Recorded when | Names the account | Names an actor |
|---|---|---|---|
| `mfa_recovery_requested` | The owner creates a recovery request | Yes | No |
| `mfa_recovery_failed` | A recovery submission is refused | Only if its challenge identifies one | No |
| `mfa_recovery_rejected` | An Administrator rejects a request | Yes | Yes, the Administrator |
| `mfa_recovery_authorized` | An Administrator authorises a request, which revokes the old device | Yes | Yes, the Administrator |
| `mfa_recovery_completed` | The new, approved device accepts its first code | Yes | No |
| `mfa_recovery_break_glass` | The break-glass command performs an emergency action, `revoke_device` or `approve_enrollment` | Yes | No |

83. **The enrolment in between is recorded by the event types that exist**: `mfa_enrollment_started`, `mfa_enrollment_approved`, and `mfa_enrollment_succeeded`.
84. **Two of the six name an actor, and the actor is never the account.** The constraint that only a decision names an actor is extended to `mfa_recovery_rejected` and `mfa_recovery_authorized`. The constraint that an actor is never the account already covers them.
85. **`mfa_recovery_failed` names no actor** because nobody decided anything: the submission was refused by the application itself, and whoever sent it is the account's owner or nobody known, as for a refused sign-in or a refused reset token (ADR-0016 point 39). It names the account when the challenge it carried identifies one, and nobody otherwise. The constraint on which events may name no user is extended to it.
86. **`mfa_recovery_break_glass` is the dedicated record of a break-glass action, and names no application actor** because there is none to name (point 67). It records the account and the time. It records no network address: the command is not a request. Where the command stands in for an authorisation or an approval, this event is the record of that act; `mfa_recovery_authorized` and `mfa_enrollment_approved` are not written, because each must name an Administrator.
87. **Each `mfa_recovery_break_glass` event states which action it records, as a structured value.** The value is one of exactly two: `revoke_device` or `approve_enrollment`. It is constrained to those two, required on this event type, and absent from every other. It is not free text, and the action is never left to be inferred from the events around it. AuthenticationEvent has no structured field for such a value today. How it is stored is for the implementation, within these rules.
88. **No event and no log line holds** a password or its hash, a TOTP secret, code, or provisioning address, a challenge token, a reset token, any other token or its hash, a reset link or any other link, a session identifier, a request header, an email address or network address other than as a keyed hash, or anything about how a person was identified. There is no free-text reason, and the action of point 87 is one of two fixed values: free text is where a passport number or a telephone number would be typed.
89. **It is not the general audit record.** AuditEvent remains future work, and recovery does not wait for it.

## Changes to ADR-0014

ADR-0014 stays Accepted and is not edited. As when ADR-0014 changed statements of ADR-0012 and ADR-0013, the statements changed are named here. They changed when this ADR was accepted, on 2026-10-04.

| ADR-0014 | Says | Becomes |
|---|---|---|
| Point 35 | No administrator-assisted reset. An Administrator cannot remove another account's second factor. | An Administrator revokes the lost device of another Reviewer or Administrator account by authorising that account's own recovery request, and in no other way. An Administrator still cannot issue a device. |
| Points 24 and 25 | A challenge completes a sign-in when a right code is given, and is removed by it | A challenge can also be used up by creating a recovery request, which signs nobody in. |
| Amendment, point 8 | Approval requires a trusted Administrator, a different account, and an explicit confirmation | And an Administrator who did not authorise the account's most recent recovery. |
| Amendment, points 1 and 13 | A device is trusted only by an Administrator's approval or the bootstrap, which is the only exception | And by the approval of the break-glass command, only for the enrolment that follows the recovery of an Administrator, where no Administrator who may approve exists. |
| Point 36 and amendment, point 16 | The event types. Only `mfa_enrollment_approved` and `mfa_enrollment_rejected` name an actor. | Six more event types. `mfa_recovery_rejected` and `mfa_recovery_authorized` also name one. |
| "Deferred": ending an account's other sessions | Deferred to session management | Built for this recovery path only: finalising a recovery ends the account's sessions. Enrolling and disabling still end none. |
| Consequences: a lost device locks its owner out until the database owner intervenes; amendment, consequences: for the only Administrator that operation must also set the approval | | No longer true of a Reviewer or Administrator whose recovery this ADR supports. Still true of every other lost device. |

Unchanged, explicitly:

- **Recovery codes remain prohibited** (point 34).
- **Inherited device trust remains prohibited** (amendment, points 12 and 14). A device enrolled after a recovery inherits nothing.
- **Enrolment and its approval work as they do today** (points 20 to 22; amendment, points 4 to 11), with the one added refusal named above.
- **The bootstrap is unchanged** and still works once (amendment, point 13).
- **A Reader or Researcher who lost a device remains outside this ADR.** Point 35 stands for those accounts as it is.

Also unchanged: one device for an account, and no enrolment while one is active (points 13 and 21); disabling by the account itself on both proofs (point 33); the two assurance levels and the policy.

## How it is to be enforced

- **In the policy.** The new permission is in the Administrator role's list and nowhere else. Which accounts are eligible is the existing function that says which roles need approval.
- **In the services.** Each operation checks its permission first and inside its transaction, takes the account's second-factor lock in the established order, and refuses the actor's own account. The approval service refuses the Administrator who authorised.
- **In the database.** The event-type and actor constraints of AuthenticationEvent are extended, and `mfa_recovery_failed` is added to the events that may name no user. A break-glass event carries one of its two actions, and no other event carries one. One pending request for an account. The constraints on the device are unchanged: they already allow an approval that names no approver.
- **In the command.** It checks for itself that the application's path is unavailable and that the account is an Administrator, and can write nothing but what point 63 lists.
- **By tests**, including each property of points 1 to 14 as an end-to-end negative scenario (a password alone, a mailbox alone, both, a reset followed at once by a request, a request made before a reset, one Administrator attempting both decisions, an Administrator acting on their own account, and the command run for a Reviewer, without a terminal, or while the normal path is available), each constraint directly, each of the three limits, that a submission throttled by source gets status 429 and the same response whether or not its challenge exists, stores nothing, and uses up nothing, that a refused authorisation records no failed submission, that each break-glass action records its own value, operations made at the same time, the absence of secrets from events and logs, that a session, a challenge, and a reset token that existed before a recovery are refused after it, and a pass of deliberate faults placed in each check.

## Alternatives considered

- **Recovery by email alone, or by email and password.** The mailbox becomes worth a password and a device together.
- **Requiring a confirmation through the verified email address for every request.** One more piece of evidence, and of the same chain as the password. Recovery would then wait for a delivery service, and the first Administrator, whose address was never verified, would be excluded.
- **Password reset that also disables the second factor.** The same thing by another route (ADR-0016).
- **An Administrator starting a recovery that the owner did not ask for.** Nothing in the system would tie the act to the owner, and an Administrator could remove any privileged account's device at any time.
- **The owner alone, with no Administrator.** It needs evidence that does not reduce to the mailbox, which is a recovery code.
- **Recovery codes.** The second, long-lived credential that ADR-0014 point 34 declined. Without a defined lifecycle (generation, storage, single use, rotation, revocation, throttling) they are a permanent password that skips the device.
- **An Administrator simply deleting another account's device.** What the database operation does today, moved into a page, with no request from the owner, no second Administrator, and no notice.
- **An Administrator directly creating a trusted device.** The Administrator would see the secret and could compute codes.
- **A pending replacement, with the old device active until the new one is approved.** No time on a password alone, but it needs two devices for one account and an enrolment while one is active, and one decision would cover both the recovery and the trust.
- **Letting the new device inherit the trust of the lost one.** ADR-0014 rejected it when the old device is present. It is weaker when it is not.
- **One Administrator for both decisions.** It works with two Administrators. An Administrator who knew a privileged account's password, or read its mailbox, could then remove its device, ask for an enrolment, approve it, and act as that person.
- **A recovery flow for Reader and Researcher accounts.** Their second factor confers nothing under the current policy. If the policy comes to require one of them, this is revisited.
- **A waiting period after every request, in place of one after a password reset.** It delays every person who lost a phone, and without a delivered notification it protects nobody.
- **A request that waits for days**, as an enrolment request does. A number that stays valid for days is a longer time in which an Administrator can be persuaded.
- **Inferring which break-glass action an event records from the events around it.** A reader of an append-only record would have to reconstruct what the one unattributed act in the system was. A free-text note would say it, and would also be a place to type who was identified and how.
- **The page that refuses a submission, and not status 429, for a submission throttled by source.** The limits by source are applied before anything is looked up, so status 429 says nothing about any challenge or account, and it tells a person why a submission is not being taken. A throttled code at the same step answers the same way (ADR-0014 point 29).
- **No limit on failed submissions, and no event for them**, leaving them to the limits on sign-in, through which every challenge is obtained. Refused submissions would then leave no record, or be recorded without a bound on the rows one source can write. The limit is not there against guessing, as for a refused reset token (ADR-0016 point 35).
- **Counting failed submissions from `mfa_recovery_rejected`.** That event is an Administrator's decision and names an actor. A refusal by the application would then be recorded as a decision nobody made.
- **Break-glass for a Reviewer when Administrators are missing.** It would turn the exception for one emergency into a general way round the two Administrators.
- **Break-glass that sets a password**, for a person who lost everything. The operator would hold a working credential, and the command would be a password reset that no mailbox and no Administrator stands behind.
- **Break-glass that issues a trusted device at the terminal**, as the bootstrap does. The secret would pass through the operator's hands, and the bootstrap's one exception would become a standing one.
- **Recording the operator in the application.** The bootstrap wrote the operating-system account into the reason of a role event. An authentication event has no such field, and an account invented to stand for the operator would record something untrue.
- **Recovery for the only Administrator inside the application.** Only the owner would be left to do it, on evidence that reduces to the mailbox.
- **Leaving the only Administrator locked out for good.** Nothing to abuse, and an installation in which no account can be created, enabled, or approved: the state ADR-0012 point 6 exists to prevent.
- **Signing the person in when recovery completes.** A second way in that skips the code.
- **Marking the account's roles as needing no second factor until it enrols again.** The switch that ADR-0014 says does not exist.
- **Leaving the account's sessions signed in after a recovery.** They would fall to the weaker assurance by themselves. A session opened by whoever holds the lost device should not survive the decision that the device is lost.
- **Security questions.** A second password of lower quality.
- **Waiting for the general audit record.** AuthenticationEvent already records every change to a second factor and can name an actor.

## Dependencies

ADR-0017 depends on:

- **ADR-0014**, which it changes as listed above and otherwise keeps.
- **ADR-0016**, which it leaves true and composes with.
- **ADR-0012** for the separation of duties and the last-Administrator rule, **ADR-0013** for throttling, records, and the bootstrap, and **ADR-0015** for the account states, the email boundary, and the creation of further Administrators.
- **ADR-0008** (Proposed) for email delivery, the trusted source address, key management, and the operational audit trail and instructions of the break-glass command. Nothing here is built on it. Recovery asks, authorises, enrols, and approves without it. Until it is decided: no notification is delivered; a person who lost the password as well cannot reset it; behind a reverse proxy every visitor shares one source; and a use of the break-glass command is recorded by the application without the name of whoever ran it.

Loss of the TOTP encryption key makes every device undecryptable at once. That is key management, which belongs to ADR-0008, and recovery is not its substitute.

Future work that depends on ADR-0017:

- The implementation of recovery, with the mechanism that ends an account's sessions, and the revision of the "lost device" texts in SECURITY.md, DATA_MODEL.md, and DEVELOPMENT.md.
- The deployment documentation for the break-glass command, with ADR-0008.
- Changing an account's email address: a new address changes what the mailbox proves.
- Recovery after a suspected compromise.
- Notifications as a general facility.
- Any procedure under ADR-0008 for a lost or rotated encryption key that expects accounts to enrol again.

## Consequences

- A Reviewer or Administrator who loses a device can get a new one inside the application, with a record of who decided what.
- **It is as strong as the Administrators' checks.** An authorisation or an approval given without asking the person for the number trusts whoever made the request. There are two such checks, by two people.
- **Two Administrators are only as independent as they are different people.** One Administrator can create another account, grant it the Administrator role, and approve its enrolment (ADR-0015). That is recorded and visible to the others. It is not prevented.
- **It takes people and time.** Two Administrators for a Reviewer, three in all for an Administrator, a step outside the system for each, and a day after a password reset.
- **A request must be authorised within 30 minutes.** An Administrator has to be reachable when the person asks. A request that lapses is made again, up to five times in an hour.
- **Asking ends the sign-in it was made from.** The challenge is used up, so a person who finds the device after asking gives the password again to sign in with it.
- **Between the authorisation and the new device, the password alone signs the account in.** With a privileged role only, that allows asking for an enrolment and nothing else. An account that also holds Reader or Researcher holds that role's permissions on its password during that time, which it did not while the lost device stood in front of its sign-in.
- Whoever knows the password of an eligible account can make requests for it. That replaces the owner's request, and five in an hour stop the owner from asking until the hour has passed. It gains nothing unless two Administrators act on it.
- Behind a reverse proxy every visitor shares one source until ADR-0008 names the header to trust. Twenty requests, or ten failed submissions, from anyone in fifteen minutes would then stop every recovery request for that time.
- **A Reader or Researcher who enrolled voluntarily and lost the device is still locked out.**
- **A Reviewer in an installation with fewer than two Administrators who are able to act is locked out** until there are two.
- **An account that lost its password, its device, and its email address is lost.**
- An installation with one or two Administrators recovers an Administrator only by the break-glass command.
- The command is a standing capability of whoever controls the server. It adds nothing to what that person could already do in the database, and makes it constrained and recorded. The application's record of it does not say who ran it.
- **A sole Administrator who replaces or disables the second factor by choice is not helped**: that account has no active device and so is not eligible. ADR-0014's warning stands, and a second Administrator should exist first.
- A recovery removes the account's password-reset token, which is one more way that token is removed than ADR-0016 describes.
- The authentication event table gains rows from recovery submissions, bounded per account and per source by point 71. It still has no retention period.
- Implementation: six event types, a structured action on the break-glass event, and changed constraints on an append-only table, one new permission, a pending-request record, a way to end an account's sessions, new administration pages, a change to the approval service, a management command, and a migration.
- **Until this ADR is built, nothing changes in the application**: a lost device is the database operation of ADR-0014 point 35.

## Revisit when

A delivery service is chosen; the deployment decision defines the operational audit trail; the reverse proxy is defined; session management is designed; a second kind of second factor is wanted; an email address becomes changeable; the authentication-assurance policy gives Reader or Researcher a required second factor; the limits prove too strict or too loose in use; or the number of Administrators in a real installation makes the separation of duties decided here unworkable.
