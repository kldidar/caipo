# ADR-0012: Authorization and role event integrity

- Status: Accepted
- Date: 2026-10-02
- Amended: 2026-10-02, by decision of the project owner (see "Amendment: the first-Administrator bootstrap")

## Context

[ADR-0007](0007-authentication.md) set the access model: three surfaces, four roles, deny by default, and audit of role changes. It did not say how a role is stored, how a decision is made from it, or what protects the record of who granted what.

Those choices carry most of the risk in an access system. A role kept as a field can be overwritten without trace. Role checks written into views drift apart from the checks in services. An Administrator who can change their own roles, or who can be removed when no other exists, turns one mistake or one compromised session into a loss of control. A history that the application can edit is not evidence of anything.

The project owner decided the points below on 2026-10-02, while the identity and access foundation was being built. This ADR records them. It adds to ADR-0007 and changes none of its decisions.

Points 7, 13, and 14 were amended on the same day, when the bootstrap of the first Administrator was designed. The amendment is set out in its own section below, and the amended points say so.

## Decision

### Authorization

1. **Decisions are permission-based.** Code asks whether an account holds a permission. It never asks which role an account has. A view declares the permission it requires, for example `@requires(Permission.RESEARCH_REVIEW)`, and a service requires a permission in the same way. One policy maps roles to permissions, and views and services both use it, so the HTTP boundary and the service layer cannot disagree. A service checks for itself whatever the view has checked.
2. **Roles have no implicit inheritance.** The four roles of ADR-0007 are independent. Each role's permissions are listed in full. Where the specification describes one role as another "plus" more, the larger role's list contains the smaller role's permissions explicitly.
3. **Administrator does not receive research permissions.** The Administrator role is for administrative control. A person who needs both administrative and research capabilities holds both roles.
4. **A user may hold several roles.** Their permissions are the union of what each role confers.

### Role administration

5. **Nobody modifies their own roles.** Granting or revoking a role requires an authorised Administrator as the actor and a target who is a different user. This is a separation-of-duties rule. It is enforced by the service, and by a database constraint on the role event.
6. **The final Administrator cannot be removed.** The services refuse to revoke the Administrator role from, or to deactivate, the only active account that holds it. This includes an Administrator deactivating their own account: it is allowed only while another active Administrator remains. No exception bypasses this rule, and it is enforced in the service, not in the interface.

### Role events

7. **RoleEvent is append-only.** A role is held because an event grants it and no later event revokes it. An event records the target user, the role, whether it was a grant or a revocation, the actor, the reason, and the time. There is no current-role record that could be overwritten. *Amended: one event, and only one, has no actor. See the amendment.*
8. **PostgreSQL protects RoleEvent against UPDATE and DELETE.** A trigger refuses both, for every row and every database role, however the statement was sent. It is created by the same migration that creates the table.
9. **Application guards remain.** The model and its query interface also refuse to update or delete an event. The database is the final boundary; the guards fail earlier and say why.

### Concurrency

10. **Role changes are transactional.** Each grant, revocation, or deactivation is one transaction. It takes effect completely or not at all.
11. **Role changes are serialized.** Only one such change proceeds at a time, and the actor's permission is decided after the wait, not before it. This is what keeps the final-Administrator rule true when two changes arrive together: whether an Administrator remains depends on every account at once, so locking only the accounts being changed would not be enough.
12. **The current mechanism is a table-level lock** on the role event table, held to the end of the transaction, in a mode that conflicts with itself and with inserts and does not block reads. It was chosen as the simple, correctness-first solution.

### The first Administrator

13. **The first Administrator is created by a controlled bootstrap, outside the normal role-change path.** Every normal role change requires an existing Administrator who is a different user, so the normal path cannot create the first one. *Amended: as first accepted, this point said that creating the first Administrator was intentionally not implemented and would be designed with the authentication increment. It has been; see the amendment and [ADR-0013](0013-authentication-core-and-first-administrator-bootstrap.md).*
14. **There is no shortcut.** No environment variable, database flag, setting, or request parameter may create an Administrator or grant a role. The bootstrap leaves an accountable record like any other role change. *Amended: "attributable" to an acting user became "accountable" through bootstrap metadata, because no acting user can exist; see the amendment.*

## Amendment: the first-Administrator bootstrap

Decided by the project owner on 2026-10-02. It narrows one statement of this ADR and weakens nothing else.

Before the first Administrator exists there is no account that could be the actor of a role event. Recording the new Administrator as their own actor would break point 5, and recording an invented system account would state something untrue. The bootstrap grant is therefore the one legitimate exception to "every role event records an actor".

1. **Normal role events require an actor.** Every grant and revocation made through the role services names the Administrator who made it, and that Administrator is never the target. Points 5 to 12 apply to them unchanged.
2. **The single first-Administrator bootstrap grant is the only permitted actor-less role event.**
3. **It can represent only the creation of the Administrator role.** An event without an actor that grants any other role, or that revokes anything, is refused.
4. **It is created only by the controlled bootstrap command**, `create_first_administrator`, run by a person at a terminal on the server. Nothing else in the application calls the operation that writes it.
5. **It carries bootstrap metadata sufficient for operational accountability.** Its reason states that it was made by that command and names the operating-system account that ran it, taken from the process and not from an environment variable. The command's use is also logged, under the account identifier it created.
6. **No normal application input can create it.** No web request, environment variable, HTTP header, cookie, database value, setting, or other normal application input creates an actor-less Administrator event, and the role services refuse a role change that names no actor.
7. **No second actor-less event may ever be created.** Once any Administrator role event exists, the bootstrap refuses to run, whatever has since happened to that account.

How this is enforced:

- **In the database.** One check constraint allows an event to be without an actor only if it is a grant of the Administrator role. One unique index allows at most one event without an actor in the whole table. Both hold for every writer, including SQL sent outside the application. The constraint that an actor is never the event's own subject, and the trigger that refuses UPDATE and DELETE, are unchanged, so the bootstrap event cannot be edited into something else or removed to make room for another.
- **In the application.** The bootstrap operation runs under the same lock as every other role change, refuses if any Administrator role event exists, and creates the account and its event in one transaction. The command refuses to run without a terminal, takes no credential as an argument, and reads none from the environment.
- **By tests.** Tests exercise each database constraint directly, each refusal of the command, and the absence of any other caller.

The bootstrap does not make the first Administrator able to act. Point 4 of ADR-0007, that Reviewer and Administrator accounts cannot use their privileges until TOTP is enrolled, applies to it like any other.

## Alternatives considered

- **Role checks in views and services.** Fewer moving parts at first, but the same rule ends up written in many places and the copies diverge.
- **A role hierarchy, with Administrator at the top.** Convenient, but it makes the person who operates the system a reviewer of the research by default, and it hides what each role can do behind inheritance.
- **One role per user.** Simpler to store. It forces either a hierarchy or new combined roles whenever one person legitimately has two functions.
- **A role field on the user, with a separate log of changes.** The field and the log can disagree, and the field can be changed without the log.
- **Allowing an Administrator to change their own roles.** Needed nowhere, and it removes the one check that a second person provides.
- **Enforcing the final-Administrator rule in the interface.** Any caller that does not go through that interface would bypass it.
- **Append-only by application code alone.** Any SQL not sent through the model, and any defect in the model, could rewrite history.
- **Append-only by database privileges alone.** It depends on the application connecting with a restricted role, which is a deployment matter not yet decided (ADR-0008). A trigger holds in every environment. Privileges are still required for what a trigger cannot cover; see Consequences.
- **Row-level locks on the affected users.** More concurrent, but two changes to different users could each see the other's Administrator still in place and together remove the last one.

## Consequences

- What a role can do is read in one place, and a new feature adds a permission there rather than a role check in a view.
- An Administrator who also does research must be granted a research role, which is one more step and one more record.
- At least two Administrators are needed before any Administrator's roles can be changed, and the system cannot be left with none.
- The role history can be trusted as far as the database can: the trigger does not stop TRUNCATE, and a database role that owns the table can drop or disable the trigger. The production application role must be able to do neither. That is set with the deployment decision (ADR-0008, Proposed). In development the application connects as the database owner.
- A mistaken role event cannot be corrected in place. It is corrected by a further event.
- Role changes cannot run in parallel. They are rare, administrative operations, so this is accepted.
- Exactly one role event in the system has no acting user. Its accountability rests on the bootstrap metadata and on control of who can run commands on the server. *Amended: as first accepted, this point said that no Administrator could exist in a real deployment until the bootstrap was designed.*
- If the only Administrator's credentials are lost, the bootstrap cannot be run again. Recovery would be a deliberate operation on the database by its owner, outside the application.
- The general audit record (AuditEvent) is not part of this decision and is not built. A deactivation is logged, not yet recorded.

## Revisit when

Contention on role changes is demonstrated and requires a more granular design than table-level serialization; the general audit record is introduced; or least-privilege database roles are defined with the deployment decision.
