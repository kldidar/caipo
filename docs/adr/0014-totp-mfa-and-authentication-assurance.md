# ADR-0014: TOTP multi-factor authentication and authentication assurance

- Status: Accepted
- Date: 2026-10-02
- Amended: 2026-10-03, by decision of the project owner (see "Amendment: approval of enrolment for privileged accounts")

## Context

[ADR-0007](0007-authentication.md) rule 4 requires multi-factor authentication with TOTP for Reviewer and Administrator accounts: such an account cannot use its privileges until TOTP is enrolled. [ADR-0013](0013-authentication-core-and-first-administrator-bootstrap.md) built sign-in without a second factor and, in its point 27, kept those two roles inert behind a lookup that always answered "not enrolled". That was a placeholder for this decision.

Three things had to be decided. How a second factor is enrolled, stored, and checked. How the system represents the difference between an account that has shown a password and one that has also shown a code. And how that difference reaches the one place where authorization is decided, so that a caller who never touches HTTP is held to the same rule.

The project owner specified the requirements on 2026-10-02 and directed that this ADR be Accepted if the implementation matches it. The owner left four points to be evaluated and recorded here: the dependency, whether recovery codes are built, the policy for disabling a second factor, and how the first Administrator reaches enrolment. Each is marked "evaluated" below.

Points 1, 4, 8, 13, 20 to 22, 33, 35, and 36, and two of the consequences, were amended on 2026-10-03, before the implementation was committed. The final audit of the implementation found that a password alone was enough to establish the second factor of a Reviewer or Administrator account that had not yet enrolled, and the project owner did not accept that. The amendment is set out in its own section below, and the amended points say so.

This ADR decides nothing about deployment. How the encryption key is stored, supplied to the process, backed up, and rotated in production belongs to [ADR-0008](0008-deployment-strategy.md), which is Proposed. Multi-factor authentication is implemented in the application; it is not complete as a production deployment until that decision exists.

## Decision

### Authentication assurance

1. **Two assurance levels, stated explicitly.** `PASSWORD_AUTHENTICATED`: the account's password was checked. `MFA_VERIFIED`: the password was checked, and so was a code from the account's active second factor. There are no other levels, and anything that is not `MFA_VERIFIED` is treated as the weaker one. *Amended: the second factor must also be trusted. A code from a second factor that was enrolled on a password alone does not make a sign-in `MFA_VERIFIED`. See the amendment.*
2. **An authentication context is a value passed explicitly.** It holds the account, the assurance, and, for `MFA_VERIFIED`, the identifier of the device the code was verified against. Views pass it to services, and services pass it to the authorization decision. There is no ambient current user, no global, and no thread-local flag.
3. **Authorization is asked about a context, never about a bare account.** `can` and `require_permission` take a context. An account passed without one holds no permission: there is no assurance to decide on. Every service that requires a permission takes the acting context, so a caller that bypasses HTTP is refused exactly as a request would be.
4. **A context states a claim; the decision checks it.** `MFA_VERIFIED` counts only if the context claims it **and** the device it names is, in the database at that moment, that same account's active second factor. The claim alone is not believed, and the database row alone is not believed. Verification is therefore not inferred from a role, from a database flag, or from anything a client sends. *Amended: the device must also be trusted; see the amendment.*
5. **The server-side session carries the claim for HTTP.** After a code is accepted, the session, which is held in PostgreSQL, notes the identifier of the device. The context for each request is built from the session's account and that note. No parameter, header, or cookie is consulted. The note is checked on every decision as in point 4, so a note for another account's device, for a pending device, or for a device that has since been removed grants nothing.

### Policy

6. **One decision point, extended by one input.** The policy of [ADR-0012](0012-authorization-and-role-event-integrity.md) is unchanged in form: roles confer permissions, with no inheritance, and one function decides. It now takes the assurance in place of an enrolment flag. No code outside the policy module asks which role an account has or whether it has a second factor.
7. **Reviewer and Administrator confer their permissions only at `MFA_VERIFIED`.** The policy names the roles that require a second factor. On a password alone such a role confers nothing that a lesser role would, as before.
8. **One permission is available to those roles on a password: managing the account's own second factor.** *Evaluated: how the first Administrator reaches enrolment.* A new permission, `accounts.mfa.manage_own`, is held by all four roles, and it is the whole of what Reviewer and Administrator confer before a code is verified. Without it an account holding only those roles could never enrol. It allows enrolling, confirming, and disabling the account's own second factor, each with the further proofs below, and nothing else. No temporary Administrator permission exists and there is no bypass: the first Administrator signs in with a password, can reach the enrolment pages, and holds no administrative permission until a code has been verified. *Amended: the first Administrator no longer enrols through these pages. Its second factor is set up and verified by the bootstrap command, and for every other Reviewer or Administrator account this permission allows asking for an enrolment, not completing one. See the amendment.*
9. **Reader and Researcher are unchanged.** Their permissions hold at either assurance. They may enrol voluntarily (ADR-0007 rule 4).

### The second factor

10. **TOTP as authenticator applications implement it**: RFC 6238 with HMAC-SHA1, six digits, a 30-second step, and a 160-bit secret. These are constants, because changing them would invalidate every enrolled device.
11. **Clock drift.** A code is accepted for the current step and one step on either side.
12. **A code is accepted once.** The device remembers the time step of the last accepted code and accepts only a later one. A code that was observed in use, or that is older than the last one used, is refused.
13. **Three states.** Not enrolled: the account has no device. Enrolment pending: a secret has been issued and no code from it has been accepted. Active: a code proved possession. The database allows one device for an account in total, and a check constraint allows a device to be active only if it records when it was confirmed and which step confirmed it. A pending device grants nothing, is not asked for at sign-in, and is void 10 minutes after it was issued. *Amended: there are four states. An enrolment for an account whose roles require a second factor first awaits approval, and no code is accepted for it until then. See the amendment.*

### Secret storage

14. **Secrets are encrypted, not hashed**, because verification needs the secret itself. AES-256-GCM, with a fresh random nonce stored in front of the ciphertext.
15. **The key is outside the database.** It is 32 bytes, read from the environment variable `TOTP_ENCRYPTION_KEY` and from nowhere else: not from the source, the database, a request, or `SECRET_KEY`. Development and production both refuse to start without a usable key, and the test suite generates one for each run. There is no fallback key. Code that needs the key fails if the setting is absent.
16. **A ciphertext is bound to its account.** The account's identifier is authenticated with the ciphertext, so a ciphertext copied into another account's row does not decrypt there.
17. **Each ciphertext records which key encrypted it**, as a keyed fingerprint that reveals nothing about the key. A secret that cannot be decrypted, for any reason, refuses the code like a wrong one and is logged as an error. Nothing is accepted that could not be checked.
18. **The secret in clear exists only in memory and in one response.** It is generated on the server and never accepted from a client. It is shown once, in the response to the request that started the enrolment, as a Base32 key and as an `otpauth` provisioning address carrying the issuer, the account's email address, and the secret. Neither is stored, kept in the session, placed in a URL of this site, logged, or recorded in an event, and neither can be shown again; a person who lost it starts again.
19. **No QR code.** Rendering one needs a further dependency. The key is typed, or the address is opened on the device that holds the authenticator.

### Enrolment

20. **Starting requires the password again**, in the same request, whatever the session's assurance. A wrong password is recorded and counts towards the sign-in limits of ADR-0013 for the account and the source, so being signed in buys no extra password guesses. *Amended: for an account whose roles require a second factor, starting creates a request that an Administrator must approve. See the amendment.*
21. **Starting issues a secret and enables nothing.** It discards any earlier pending secret. It is refused while a second factor is active.
22. **Confirming requires a right code for the pending secret**, within its 10 minutes. Only this makes the account enrolled. The session that proved the code is raised to `MFA_VERIFIED` and given a new session key; other sessions of the account are not raised. *Amended: and, where approval is required, only after the approval. The session is raised to `MFA_VERIFIED` only if the device is trusted.*

### Signing in

23. **For an account with an active second factor, the password is not a sign-in.** The sign-in service returns a challenge and no account. Nothing is signed in, no `login_success` is recorded, and the session, under a new key, holds only the challenge. To every other view the visitor is still anonymous.
24. **The pending state is a server-side record.** A challenge is a row naming the one account it can complete a sign-in for, created only by the sign-in service after the password was accepted. The session holds its random token; the database holds a keyed hash of that token. An account has at most one challenge, so a new password step replaces the earlier one. A challenge is void after 5 minutes.
25. **Verification is by POST, with a CSRF token, and takes the account from the challenge.** Nothing in the request can name an account. A right code removes the challenge, so it cannot be used again, records the sign-in, and establishes the session under another new key, as `MFA_VERIFIED`.
26. **One answer for every refused code.** A wrong code, a code already used, a lapsed or unknown challenge, a removed device, and an undecryptable secret give the same page. It reveals nothing about the clock, the secret, or the cause.
27. **Signing out ends everything.** It deletes the session, signed in or pending, and removes the pending challenge.
28. **Whether an account has a second factor is visible only after its password is accepted.** Before that, sign-in behaves as ADR-0013 describes for every account.

### Throttling

29. **Five refused codes for one account within 15 minutes.** After that, codes are refused unexamined, with status 429, until earlier refusals leave the window. The count covers sign-in, enrolment confirmation, and disabling together.
30. **Nothing resets the count early.** Not a new challenge, a new session, a new source, or an accepted code: an accepted code from the real device must not buy fresh guesses for someone else.
31. **Counted in PostgreSQL from the authentication events**, one code at a time per account under an advisory lock, as in ADR-0013. A throttled attempt stores nothing. Redis is not used.
32. **The limits are repository settings**, not read from the environment. No setting says whether a second factor is required: that is the policy of points 7 and 8.

### Disabling and recovery

33. **Disabling is self-service only, and needs both proofs again.** *Evaluated: the policy for disabling.* An account can remove only its own second factor, and only by giving its current password and a current, unused code in the same request. Being signed in at any assurance is not enough, and neither proof alone is. The operation has no parameter that could name another account. The device and its secret are deleted; the event remains. Roles that require a second factor confer nothing again until the account enrols anew. *Amended: an active second factor can also be replaced, on the same two proofs; enrolling again after disabling or replacing needs approval where enrolling did. See the amendment.*
34. **No recovery codes.** *Evaluated.* They are a second, long-lived credential that bypasses the device, and they need their own storage, display, throttling, and revocation. With accounts created by an Administrator and a small user base, the cost of a lost device is an operational recovery, not a reason to add a weaker factor now. Recovery is future work.
35. **No administrator-assisted reset.** An Administrator cannot remove another account's second factor. A person who loses their device cannot sign in, because the password alone no longer signs them in. Until recovery is designed, the only remedy is a deliberate operation on the database by its owner, outside the application: deleting that account's device row, after which the account signs in with its password and enrols again. For the only Administrator this is the same position as losing the password (ADR-0012). *Amended: still true: an Administrator approves or rejects a request that the account itself made and cannot remove or issue a second factor. For a Reviewer or Administrator the enrolment that follows the database operation needs approval, and for the only Administrator nobody can give it. See the amendment, "Consequences".*

### Records

36. **AuthenticationEvent gains seven event types**: `password_confirmation_failed`, `mfa_challenge_issued`, `mfa_enrollment_started`, `mfa_enrollment_succeeded`, `mfa_verification_failed`, `mfa_verification_succeeded`, and `mfa_disabled`. For an account with a second factor, `login_success` is recorded when the code is accepted, not when the password is. Each event names the account. None holds a code, a secret, a challenge token, a session identifier, or a password. *Amended: three more were added, and the two that record a decision name the Administrator who made it. See the amendment.*

### Dependency

37. **`cryptography`, and nothing else.** *Evaluated.* Locked at 50.0.2 (constraint `>=50.0,<51`).

| Question | Answer |
|---|---|
| What it is needed for | Authenticated encryption of TOTP secrets (AES-256-GCM), and the TOTP computation itself (`cryptography.hazmat.primitives.twofactor.totp`). One package covers both. |
| Why not the standard library alone | It has HMAC, from which TOTP could be written in a few lines, but no authenticated cipher. Encryption needs a library in any case, and that library already contains a maintained TOTP, so nothing cryptographic is written by hand. |
| Why not the existing dependencies | Django signs but does not encrypt. `argon2-cffi` hashes. Neither can keep a recoverable secret confidential. |
| Python 3.14 and Django 5.2 | Declares Python 3.14 in its package metadata and ships a wheel for it. It does not depend on Django. Its one runtime dependency, `cffi`, was already locked. |
| Maintenance | Maintained by the Python Cryptographic Authority. Six releases between May and September 2026, the latest on 2026-09-30. |
| License | Apache-2.0 OR BSD-3-Clause |
| Security history | It has had advisories, most of them in the OpenSSL it bundles. `pip-audit` reports none for the locked version, and CI runs that audit on every change. |

Considered and not chosen: **`pyotp`** (MIT; TOTP only, so `cryptography` would still be needed; it does not declare Python 3.14; its previous release was three years before the current one). **`django-otp`** (it brings its own device models, which store the secret unencrypted, its own middleware, and admin integration; it would replace the storage, state, and assurance design decided here rather than serve it).

## Amendment: approval of enrolment for privileged accounts

Decided by the project owner on 2026-10-03. It adds one requirement, trust in a device, and changes how the first Administrator gets its second factor. It weakens nothing.

### Reason

As first accepted, every account enrolled a second factor on its password. For a Reviewer or Administrator account that had not yet enrolled, the second factor therefore proved nothing that the password did not: whoever knew the password could sign in, give the password again, enrol a device of their own, and reach `MFA_VERIFIED` with every privilege of the account. The original text accepted this. The owner's decision is that **a compromised password must not be sufficient to establish a trusted second factor for an account that holds a privileged role.** Something that the holder of the password cannot supply has to stand between the request and the trust: a decision by an Administrator who is already trusted.

### Decision

1. **Trust is a property of a device.** A device is trusted if an Administrator approved its enrolment, or if the first-Administrator bootstrap established it (point 13 of this amendment). Nothing else makes a device trusted, and no setting, environment variable, request, header, cookie, or session value does.
2. **Only a trusted device counts towards `MFA_VERIFIED`.** The decision of point 4 now has three conditions: the context claims a verified code, the device it names is that account's active second factor, and that device is trusted. This is one more condition in the one place where the claim is checked. The policy itself is unchanged: roles confer permissions at an assurance, and no code asks which role an account has.
3. **An untrusted device is still a second factor for signing in.** An account that enrolled without approval is asked for its code at sign-in as before. The code adds nothing to what the account may do, because nothing that Reader and Researcher hold depends on the assurance.
4. **Whether an enrolment needs approval follows from the roles on record.** It does if the account holds any role that requires a second factor, whatever else it holds. The rule is a function in the policy module, beside the list of those roles. Reader and Researcher accounts enrol by themselves, as before (ADR-0007 rule 4).
5. **Four states.** Not enrolled; **awaiting approval**; **awaiting verification**; active. An enrolment that needs approval begins awaiting approval. One that does not begins awaiting verification.
6. **The secret is issued when the request is made, and is unusable until the request is approved.** It is generated on the server, stored encrypted, and shown once to whoever made the request, as before. While the request awaits approval no code is accepted for it: a code is not examined, counts as no attempt, and activates nothing. Issuing the secret at the request, and not after the approval, is what binds the approval to one person: a secret issued after the approval could be collected by anyone who knows the password.
7. **A request has a number, and the approval names it.** The number identifies one issued secret. It is shown to the person who made the request and, beside the account's email address, to the Administrator. The Administrator is expected to ask the person for it by a means other than this system and to approve only that number. A request made later for the same account, by anyone who knows its password, replaces the earlier one, has another number, and has no approval, including when the earlier one had already been approved.
8. **Approval requires a trusted Administrator, a different account, and an explicit confirmation.** It requires the permission `accounts.mfa.approve_enrollment`, which only the Administrator role holds and which, like every Administrator permission, exists only at `MFA_VERIFIED`. It is refused for the actor's own request, by the service and by a database constraint. Over HTTP it is a POST with a CSRF token and a ticked confirmation, names the request in the path, and takes nothing else from the browser. The change of state and its record are one transaction under the account's second-factor lock.
9. **An approval enables nothing by itself.** It lets the first code be accepted. It raises no session, and the account holds no further permission until a code has activated the device and a sign-in has been verified against it.
10. **A request can be rejected**, by the same Administrator permission. The device and its secret are deleted, and the account may ask again.
11. **Lifetimes.** A request waits 72 hours for a decision, and an approved enrolment waits 72 hours from the approval for its first code, because both wait for people. An enrolment that needs no approval is still void after 10 minutes. These are repository settings.
12. **A device enrolled without approval never becomes trusted.** If an account enrols as a Reader and is granted a privileged role afterwards, or starts an enrolment before the grant and confirms it after, its device is active and untrusted, and the role confers nothing. The account replaces the device, and the new one is approved.
13. **The first Administrator is the exception, and the only one.** No trusted Administrator exists to approve it. Its second factor is therefore established by the controlled bootstrap command, at the terminal, by the person who runs it:
    - The command asks for what it asked for before, then issues a secret, writes the key to the terminal once, and asks for a code from the authenticator that was given it.
    - **Nothing is created until a right code is given.** The account, its role event, and its device are then written in one transaction, with the device active, trusted, and naming no approver. If no code is accepted in three tries, nothing exists and the command can be run again.
    - An Administrator therefore never exists without a verified second factor, and the first Administrator's password alone never signs it in.
    - The command refuses to run unless both its input and its output are a terminal, so the key is not written to a pipe or a file. It still takes no option and reads nothing from the environment.
    - There is no web page for the bootstrap, and no environment variable, setting, header, cookie, or request that performs or shortens it.
    - This changes two statements in earlier ADRs, which are not edited. ADR-0013 point 22 lists what the command asks for; it now also shows a key and asks for a code. The last paragraph of ADR-0012's amendment says that the bootstrap does not make the first Administrator able to act; the bootstrap now completes the enrolment that paragraph refers to, and the first Administrator is able to act once it has signed in with its password and a code. ADR-0007 rule 4 holds throughout.
14. **Replacing an active second factor.** *Evaluated: current proof of the second factor, or an Administrator's approval; the safer was to be chosen.* **Both are required, and neither replaces the other.** Giving up an active device requires the current password and a current, unused code from that device, in one request, exactly as disabling does: a password alone replaces nothing, and starting an enrolment is refused while a device is active. The new device then inherits nothing. It is a request like any other and, for an account whose roles require a second factor, awaits approval. Proof of the old device shows that the person held it. It does not show that the new device should be trusted, and a session that is already compromised should not be able to move the trust to a device of its choosing. Because an account has one device, the old one is given up when the new secret is issued, and the account holds no privilege until the new one is approved and verified.
15. **Disabling is unchanged, and enrolling again is a new enrolment**, with approval where approval is required.
16. **Records.** Three event types are added: `mfa_enrollment_approved`, `mfa_enrollment_rejected`, and `mfa_device_replaced`. The two decisions name the account and, as actor, the Administrator who decided; no other event names an actor, and the actor is never the account. The existing `mfa_enrollment_started` is the record that an enrolment was requested, and `mfa_enrollment_succeeded` that one was completed; they keep their names because the table is append-only and its rows cannot be renamed. No event holds a secret, a code, or a request's key.

### How it is enforced

- **In the policy.** One function says which roles need approval. The approval permission is in the Administrator role's list, so the existing rule that Administrator permissions exist only at `MFA_VERIFIED` covers it without a role check anywhere else.
- **In the decision.** The check of a verified claim includes that the device is trusted.
- **In the services.** A code is accepted only for a device that awaits verification or is active. Approval and rejection check the permission, the state, the lifetime, and that the request is not the actor's own, inside one transaction and under the lock that every second-factor operation of that account takes.
- **In the database.** A device that awaits approval cannot be marked approved. A device cannot name its own account as approver, and cannot name an approver without being approved. An event names an actor if and only if it is a decision, and never the account it is about.
- **By tests**, including the compromised-password scenario end to end, each constraint directly, operations made at the same time, and a pass of deliberate faults placed in each of the checks above.

### Alternatives considered

- **Treating the grant of a privileged role as the approval of whatever device the account has.** It needs no new step, but the Administrator who grants a role says nothing about a device, and a device enrolled by whoever knew a Reader's password would become trusted by the promotion.
- **Issuing the secret only after the approval.** Then the approval names an account, not a secret, and whoever knows the password can collect it.
- **Verifying the code first and approving afterwards.** It would make an unapproved device active, and every decision would then rest on remembering that an active device may not count.
- **Letting a replacement inherit the trust of the device it replaces.** See point 14.
- **A third assurance level for an unapproved device.** Nothing would be conferred at it that is not conferred on a password.
- **Marking existing devices trusted in the migration.** They were enrolled on a password alone, which is the weakness being closed.
- **A one-time enrolment code that an Administrator hands to the person.** It is another credential, with its own storage, expiry, and delivery.
- **A flag on the account saying its second factor is trusted.** It would survive the device it was set for.

### Consequences

- The first Administrator is the root of trust for every other privileged account: each Reviewer and Administrator is approved by an Administrator, and the first by the person who ran the bootstrap at the server.
- Creating a Reviewer or Administrator takes two people and a step outside the system. That is the cost of the property.
- **The approval is as good as the Administrator's check.** An Administrator who approves a request without asking the person for its number has restored the earlier weakness for that request. The system records who approved; it cannot verify that they asked.
- Whoever knows a privileged account's password can still make requests for it, which replaces the owner's pending request and shows the Administrator a request the owner did not make. That delays an enrolment and gains nothing unless an Administrator approves it.
- **A system with one Administrator cannot renew that Administrator's second factor.** Replacing or disabling it leaves a request that nobody can approve, and the bootstrap cannot be run again. Deleting the device row in the database (point 35) is no longer enough for the only Administrator, for the same reason: recovery would be a deliberate operation on the database by its owner that also sets the approval, outside the application. Two Administrators are needed before either changes their second factor, as ADR-0012 already requires before either's role is changed.
- A device row deleted by the database owner for any other Reviewer or Administrator leads to a new request, which an Administrator approves.
- An account promoted from Reader or Researcher that had enrolled voluntarily must replace its device before the new role confers anything.
- An Administrator sees the email addresses of accounts that await approval.
- Devices that were active before this amendment are untrusted. No deployment exists; a development database whose Administrator enrolled before it is recreated.

## Alternatives considered

- **Keeping an enrolment flag as the input to the policy.** It answers "has this account a second factor", not "did this sign-in show one". A stolen password would then carry every privilege of an enrolled account.
- **A flag in the session, trusted as it stands.** Simpler, but it survives the removal of the device, and it cannot be told from a flag written for another account.
- **A separate record of authenticated sessions in the application's own table.** It would duplicate Django's server-side sessions and need its own expiry and clean-up. The device check in point 4 gives the property that matters without it.
- **Keeping the pending state only in the session.** Then the service that accepts a code could be called for any account by a caller that never passed the password step. The challenge row makes the order password, then code, a property of the service layer.
- **A signed, stateless challenge token.** No table, but it cannot be used up, so it could be replayed until it expired.
- **Signing the account in after the password and restricting it until the code.** This is the fully authenticated session before verification that the requirement forbids, and every view would have to remember the restriction.
- **A new kind of access declaration, "any signed-in account", for the enrolment pages.** It would add a second way to decide access beside permissions. A permission keeps one decision point.
- **Hashing the secret.** Verification needs the secret.
- **Encrypting with a key derived from `SECRET_KEY`.** Rotating the signing key would then destroy every second factor, and one leaked value would expose both.
- **Fernet.** Authenticated, but it has no associated data, so a ciphertext could be moved between accounts.
- **Resetting the throttle on success.** It hands an attacker who knows the password five fresh guesses each time the real person signs in.
- **Disabling with the password alone, or with a signed-in session alone.** Either makes the second factor removable by whoever holds the first.
- **Recovery codes now.** See point 34.

## Consequences

- Reviewer and Administrator privileges work, for the first time, for an account that has enrolled and signed in with a code. The first Administrator can now grant roles. *Amended: "enrolled" means enrolled with an Administrator's approval, or by the bootstrap.*
- Every service that needs a permission takes a context in place of an account. Code written against the earlier signatures is refused, not silently allowed.
- A decision at `MFA_VERIFIED` costs one more query than a decision on a password.
- An account that requires a second factor and has not enrolled holds no privilege, and whoever knows its password cannot give it a second factor that confers one: that needs an Administrator's approval. *Amended: as first accepted, this point said that such an account was protected by its password alone until it enrolled, that whoever knew the password could enrol their own device, and that this was accepted. It no longer is; see the amendment.*
- An enrolled account always signs in with a code, whatever its role. A session that existed before the account enrolled stays signed in at the weaker assurance until it ends; it gains nothing from the enrolment.
- Signing in again within the same 30 seconds as the last accepted code means waiting for the next code.
- **Whoever knows an account's password can keep its second factor throttled** with five wrong codes every fifteen minutes. This needs the password, so it is narrower than the equivalent for passwords in ADR-0013.
- **Five guesses per fifteen minutes against three acceptable codes in a million** is about one chance in 700 per day for an attacker who already holds the password and guesses without pause. Accepted for launch; the limit is a repository setting.
- **Key management.** The key must be generated randomly, kept out of the repository and out of database backups, and backed up separately, because a backup of the database is useless for second factors without it. How that is done in production is ADR-0008.
- **Key rotation is not built.** Changing `TOTP_ENCRYPTION_KEY` makes every stored secret undecryptable: every enrolled account is refused at the code step and cannot sign in, and recovery is the database operation of point 35 for each of them. A rotation that re-encrypts stored secrets under a new key needs both keys at once and a procedure, and is designed with ADR-0008. The stored key identifier exists so that such a procedure can tell which key a row is under.
- **A leaked key together with a leaked database** exposes every TOTP secret. A leaked database alone does not.
- A lost device locks its owner out until the database owner intervenes (point 35).
- The challenge and device tables are operational state, not provenance records: they are updated and deleted. What happened is in the append-only authentication events.
- One runtime dependency is added.

## Deferred

| Deferred | Where it belongs |
|---|---|
| Production storage, supply, backup, and rotation of the encryption key | Deployment, [ADR-0008](0008-deployment-strategy.md) |
| Recovery codes, administrator-assisted reset, and account recovery in general, including recovery of the only Administrator's second factor | A later authentication increment |
| Telling the person that their request was approved or rejected | With notifications, a later increment. Until then they are told by the Administrator, or see it on their page. |
| QR code on the enrolment page | When a dependency for it is justified |
| Ending an account's other sessions when it enrols or disables | With session management, a later increment |
| The Django admin behind TOTP (ADR-0007 rule 8) | Its own increment |
| The general audit record (AuditEvent) | Its own increment |

## Revisit when

Account recovery is designed; the deployment decision defines key management; a second kind of factor is wanted; or the throttle proves too strict or too loose in use.
