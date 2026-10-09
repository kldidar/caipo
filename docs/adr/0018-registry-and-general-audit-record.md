# ADR-0018: Registry and the general audit record

- Status: Accepted
- Date: 2026-10-09

## Context

Phase 1 ends with countries and institutions ([PROJECT_SPECIFICATION.md](../PROJECT_SPECIFICATION.md) §7). They are the first records in CAIPO that are not about accounts, and the first that are **mutable and still have to be accountable**. Every record built so far is one of two kinds: an append-only event (RoleEvent, AuthenticationEvent, AccountEvent), or operational state whose history is kept by those events. A Country, a Language, or an Institution is neither. It is reference data that is corrected and extended in place, by named people, and everything later built on it (sources, documents, policies, indicator series) points at it.

Three things are missing for that, and each has been deferred by name until now:

- **The general audit record.** ADR-0012, 0013, 0014, 0015, and 0017 each say that AuditEvent "remains future work". [DATA_MODEL.md](../DATA_MODEL.md) §3.1 describes it in one line: actor, action, object reference by type and public identifier, time, details.
- **A shared append-only base.** `AppendOnlyModel`, `AppendOnlyQuerySet`, and `AppendOnlyError` live in `caipo/accounts/models.py`. Every later app has append-only records, and none of them may import another app's models.
- **Public identifiers.** [DATA_MODEL.md](../DATA_MODEL.md) §5 says some records carry one. None exists yet, and no format has been chosen.

The project owner set five decisions for this ADR to record (D1 to D5): who may write the registry, mutable records with an immutable audit trail, AuditEvent and its append-only enforcement, public identifiers, and initial data. This ADR records them, fills in what they leave open, and names where they do not fit the documents as they stand ("Conflicts with existing documents"). In one place it does not keep the first wording of D1: that wording made Reviewer read-only, which the accepted role model does not allow (point 14). The project owner accepted it on 2026-10-09, before its implementation.

It decides nothing about sources, documents, policies, indicators, evidence, ingestion, workers, retrieval, or the assistant, and it changes nothing in authentication, the four roles, or any existing permission.

### What was found in the code and documents

- The import contract in `pyproject.toml` has four layers: `config`, `web`, `accounts`, `core`. It is exhaustive, so a new package fails the check until it is given a layer.
- [ARCHITECTURE.md](../ARCHITECTURE.md) §2.1 puts `accounts` and `registry` in the same layer and says apps in the same layer do not import each other. It puts audit events in `accounts`, and says `core` holds "shared base classes, identifiers" and has "no reference to users".
- A service decides permissions for itself by calling `require_permission` with an `AuthenticationContext`, both of which `accounts` gives out (ADR-0012 point 1).
- `Permission` has ten values. `WORKSPACE_READ` is held by Reader, Researcher, and Reviewer. `RESEARCH_CONTRIBUTE` is held by Researcher **and Reviewer**. Administrator holds neither, by ADR-0012 point 3.
- Each of the three append-only tables is protected by its own trigger function, written out in the migration that creates the table. No migration refers to the abstract base class or to its queryset.

## Decision

### Dependency direction

1. **`registry` sits above `accounts`, in a layer of its own.** The order becomes `core`, `accounts`, `registry`, then the apps that follow. A registry service must ask `accounts` whether its actor holds a permission and must hand `accounts` the audit record to write. Neither is possible from the same layer. `accounts` imports nothing from `registry` and never will. The audit writer is in `accounts`, below every app that calls it: it is handed the target type as one of its own values and the identifier as a UUID, so writing an event needs no import upward. Neither app's migrations depend on the other's. There is no cycle, among imports or in the migration graph.
2. **`registry` uses `accounts` only through `accounts.services` and `accounts.selectors`.** It does not import `accounts.models`. The implementation adds `registry` to the layering contract and a second import-linter contract that forbids that import, so the rule is checked and not only reviewed. import-linter is already locked; this adds no dependency.
3. **`registry` holds no foreign key to User.** A registry record has no "created by" or "changed by" column. Who created or changed it is what the audit record says, and it is said in one place.
4. **`core` gains the shared append-only base and nothing that knows about users or domains.** See point 24.

### What the registry holds

5. **Four record types**: Country, Language, Institution, InstitutionName. They are mutable domain records, not provenance records and not append-only. Their accountability comes from the audit record, not from immutability.
6. **Country.** ISO 3166 alpha-2 code, alpha-3 code, English name, active flag. The two codes are checked for form only (two and three capital letters) and are each unique. The system does not hold a list of assigned codes: holding one would put reference data in code, and would refuse the synthetic countries the tests need.
7. **Language.** A language code and a script code, both required, unique as a pair, checked for form only; an English name; an active flag. A Language record is a language in a script, so Uzbek in Latin and Uzbek in Cyrillic are two records. The English name and the active flag are additions to [DATA_MODEL.md](../DATA_MODEL.md) §3.2, which lists only the two codes; D1 and D2 presuppose both.
8. **Institution.** Kind; country, optional; parent institution, optional; valid-from and valid-to dates, each optional; successor, optional. An unknown date is empty. It has no active flag: its validity period says whether it exists.
9. **InstitutionName.** Institution, text, Language, kind (`official`, `transliteration`, `english_rendering`, `abbreviation`), and valid-from and valid-to dates, each optional. The language and the script are given by the one reference to a Language record. The validity dates are an addition to [DATA_MODEL.md](../DATA_MODEL.md) §3.2, required by D2. The text is stored in Unicode Normalization Form C and is not case-folded or transliterated.
10. **An institution kind is a fixed choice in code**, with a database check: the eight kinds named in [DATA_MODEL.md](../DATA_MODEL.md) §3.2 (ministry, legislature, regulator, statistical agency, international organisation, university, media outlet, company) and no other. There is no "other" kind. A body that fits none of them is not recorded under the nearest one: the list is extended first, by a change to that document and a migration that widens the check. That needs no new ADR. Whether the eight are enough for the real institutions is the researcher's to confirm before the first one is entered (O4).

### Write authority (D1)

Three kinds of work are kept apart. A permission belongs to exactly one of them.

| Kind of work | What it is | Permissions |
|---|---|---|
| Registry maintenance | Keeping the reference records that other records point at: which countries and languages the system knows, which bodies exist, what they are called, and when. It states no claim, cites no source, and is not reviewed. | `REGISTRY_REFERENCE_MANAGE`, `REGISTRY_INSTITUTIONS_MANAGE` (new) |
| Research contribution | Adding to the evidence base: registering sources, submitting documents and datasets, coding policies, recording searches, drafting claims | `RESEARCH_CONTRIBUTE` (unchanged) |
| Research review | Deciding on the evidence base: approving documents, setting rights, changing a source's allowed hosts, approving or returning claims | `RESEARCH_REVIEW` (unchanged) |

The registry permissions are not research permissions. Holding one confers nothing of `WORKSPACE_READ`, `RESEARCH_CONTRIBUTE`, or `RESEARCH_REVIEW`, and this ADR adds no role to any existing permission and removes none.

Registry maintenance itself has two parts, with a permission each. **Reference administration** is the list of countries and languages: the system's controlled vocabulary, which is the "configuration" that the specification's role table gives to Administrator. **Institution maintenance** is the record of bodies and their names, kept by the people who work with the documents those bodies issue.

**Administrator and ADR-0012 point 3.** That point says Administrator does not receive research permissions, so that operating the system gives no say over the evidence base.

- `REGISTRY_REFERENCE_MANAGE` does not conflict with it. It is administrative control over configuration, and it confers nothing else.
- `REGISTRY_INSTITUTIONS_MANAGE` does not conflict with its wording: it is not a research permission and gives nothing that one gives. An Administrator who holds it still cannot register a source, submit a document, code a policy, record a search, draft or review a claim, or read the workspace.
- Whether it conflicts with its **purpose** rests on one classification: that maintaining institution records is registry maintenance and not a say over the evidence base. Records in the evidence base will later name institutions as publisher, issuer, and lead body, so the classification is a policy judgement and not a deduction. The project owner made it on 2026-10-09 (O2): maintaining institutions and their names is registry maintenance, and an Administrator without a research role may do it. The permission gives no authority to create or change a research claim, evidence, policy coding, or any other research contribution. Every change it allows is audited, and nothing it allows is a deletion (points 16 and 37).

11. **Three permissions are added.** No existing permission expresses any of them.

    | Permission | Value | Held by | Why an existing permission does not do |
    |---|---|---|---|
    | `REGISTRY_READ` | `registry.read` | Reader, Researcher, Reviewer, Administrator | `WORKSPACE_READ` is not held by Administrator, who must see what they manage. Granting it to Administrator would open the whole workspace to the role that ADR-0012 point 3 keeps out of it. |
    | `REGISTRY_REFERENCE_MANAGE` | `registry.reference.manage` | Administrator | The other Administrator permissions are about roles, accounts, and second factors. None means "maintain the lists of countries and languages". |
    | `REGISTRY_INSTITUTIONS_MANAGE` | `registry.institutions.manage` | Researcher, Reviewer, Administrator | `RESEARCH_CONTRIBUTE` is held by Researcher and Reviewer, but it is a research permission, and Administrator must not be given one (ADR-0012 point 3). A service requires one permission, so institution maintenance has its own. |

12. **The policy is otherwise unchanged.** Each role's permissions stay listed in full, there is no inheritance, and a role that requires a second factor confers these permissions only to a sign-in verified with a trusted one (ADR-0014). An Administrator and a Reviewer therefore write the registry only at `MFA_VERIFIED`. A Researcher writes institutions on a password, as a Researcher does everything else.
13. **The write matrix.** Every operation is a service function that requires the permission shown, whatever the view that called it has checked. An operation not in this table does not exist.

    | Record | Operation | Permission | Administrator | Researcher | Reviewer | Reader |
    |---|---|---|---|---|---|---|
    | Country | create | `REGISTRY_REFERENCE_MANAGE` | yes | no | no | no |
    | Country | change the English name | `REGISTRY_REFERENCE_MANAGE` | yes | no | no | no |
    | Country | deactivate, reactivate | `REGISTRY_REFERENCE_MANAGE` | yes | no | no | no |
    | Language | create | `REGISTRY_REFERENCE_MANAGE` | yes | no | no | no |
    | Language | change the English name | `REGISTRY_REFERENCE_MANAGE` | yes | no | no | no |
    | Language | deactivate, reactivate | `REGISTRY_REFERENCE_MANAGE` | yes | no | no | no |
    | Institution | create, with its first name | `REGISTRY_INSTITUTIONS_MANAGE` | yes | yes | yes | no |
    | Institution | change kind, country, parent, validity dates, successor | `REGISTRY_INSTITUTIONS_MANAGE` | yes | yes | yes | no |
    | InstitutionName | add | `REGISTRY_INSTITUTIONS_MANAGE` | yes | yes | yes | no |
    | InstitutionName | change validity dates | `REGISTRY_INSTITUTIONS_MANAGE` | yes | yes | yes | no |
    | InstitutionName | mark as entered in error | `REGISTRY_INSTITUTIONS_MANAGE` | yes | yes | yes | no |
    | Any record | read | `REGISTRY_READ` | yes | yes | yes | yes |
    | Any record | delete | — | no | no | no | no |
    | Any record | change a code, a public identifier, or a name's text, language, kind, or institution; clear an entered-in-error mark | — | no | no | no | no |

14. **Reviewer holds the registry permissions that Researcher holds.** The specification describes Reviewer as "Researcher, plus", and ADR-0012 point 2 says how that is expressed: the larger role's list contains the smaller role's permissions explicitly. So `REGISTRY_READ` and `REGISTRY_INSTITUTIONS_MANAGE` are written into the Reviewer's list as they are into the Researcher's. Nothing is inherited: if the Researcher's list changes later, the Reviewer's changes only if it is edited too. A Reviewer does not hold `REGISTRY_REFERENCE_MANAGE`, because a Researcher does not. D1 as first worded made Reviewer read-only. That could be kept only by amending ADR-0012 point 2 or the specification's role table, and this ADR amends neither.
15. **Anonymous visitors read nothing here.** The registry has no public page in this milestone.

### Immutability, names, and succession (D2)

16. **Nothing in the registry is deleted.** No service deletes, every foreign key into and inside the registry is `PROTECT`, and a database trigger on each of the four tables refuses DELETE.
17. **Identity does not change.** A Country's two codes, a Language's two codes, and every record's public identifier are set once. The services offer no operation that changes them, and the same trigger refuses an UPDATE that would.
18. **Deactivation is not deletion.** A deactivated Country or Language stays, keeps everything that refers to it, and stays readable. It cannot be newly referred to: an institution cannot be given a deactivated country, nor a name a deactivated language. It can be reactivated.
19. **A name is a historical record.** An InstitutionName's institution, text, language, and kind never change after creation; the trigger refuses it. A body that is renamed gets a **new** name row, and the old row gets a valid-to date. Only the two validity dates of a name can be changed. So the table itself is the history of names, and a rename cannot overwrite what the body used to be called.
    - **A name entered by mistake is marked, not edited and not removed.** A name carries an entered-in-error mark, which is empty when the name is created, can be set once, and is never cleared; the trigger refuses clearing it. Setting it is its own audited action (point 31). A marked name stays in the table and stays readable as a marked name. It is not shown as a name of the institution, and it does not count for point 20. A mark set by mistake is answered by adding the name again.
    - A valid-to date is not used for this: it would say that the body really was called that until that day.
20. **Every institution has at least one name that is not marked as entered in error.** It is created together with its first name, in one transaction, names are never deleted, and the service refuses to mark an institution's only unmarked name: the right name is added first.
21. **Validity periods are half-open.** Valid-from is the first day, valid-to is the first day that is no longer covered. Where both are known, valid-from is before valid-to, by a database check, on Institution and on InstitutionName. Dates are full calendar dates. A date that is not known to the day is left empty: no first of January and no first of the month is entered to stand for a year or a month, because that would record a precision no source gave. The entry page says so. Nothing can enforce it.
22. **Succession.** A renamed body is the same institution. A successor is a **different** institution that took over from one that ended.
    - An institution is not its own successor or its own parent (database check).
    - An institution that names a successor has a valid-to date: it has ended (database check).
    - Where both valid-to dates are known, the successor did not end before its predecessor did (service, checked when either side changes).
    - Neither the chain of successors nor the chain of parents contains a cycle (service).
    - A successor is one institution, as [DATA_MODEL.md](../DATA_MODEL.md) §3.2 says. Several bodies may name the same successor, which records a merger. A split into several bodies cannot be recorded with one link; see Consequences.
23. **Changes to a parent or a successor are serialized.** Whether a cycle would form depends on rows other than the one being changed, so one lock admits one such change at a time, as ADR-0012 point 12 does for role changes and for the same reason. Every other change locks only the row it changes.

### The shared append-only base

24. **`AppendOnlyModel`, `AppendOnlyQuerySet`, and `AppendOnlyError` move from `caipo/accounts/models.py` to a module of `core`**, unchanged. They are abstract, refer to no user and no domain, and are exactly the "shared base classes" [ARCHITECTURE.md](../ARCHITECTURE.md) §2.1 assigns to `core`. `accounts` then imports them from below, as every later app will.
25. **The move needs no migration and rewrites none.** No existing migration names the base class or its queryset, so the migration state is the same before and after. `core` stays out of `INSTALLED_APPS`: it has no concrete model.
26. **What the base does and does not do.** It refuses `save` on a stored record, `delete`, and the queryset's `update`, `bulk_update`, and `delete`, and says why. It is a guard against mistakes in application code. It does not see SQL sent past the model, nor a write through a manager that does not use its queryset. It is not the boundary.

### AuditEvent (D3)

27. **AuditEvent, as this ADR defines it, records one thing: that a signed-in account successfully changed a registry record through a registry service.** Its shape is general: the target is named by type and public identifier and never by a foreign key, so a later domain can use the table without a change to its columns. Its scope is not general: the only target types are the four registry records, and this ADR puts nothing else into it.
28. **It lives in `accounts`**, where [ARCHITECTURE.md](../ARCHITECTURE.md) §2.1 and [DATA_MODEL.md](../DATA_MODEL.md) §3.1 already place it. That is what lets the actor be a real foreign key to User while every domain app, all of them above `accounts`, can write to it.
29. **It is not AuthenticationEvent, RoleEvent, or AccountEvent, and it replaces none of them.** Those keep recording what they record. Nothing is copied into AuditEvent from them and nothing is written twice. The "role changes" that [ARCHITECTURE.md](../ARCHITECTURE.md) §10 lists under audit are RoleEvent. Nor does this ADR say where an event that no account initiates is recorded, such as the automatic move of a claim to `needs_reassessment` ([DATA_MODEL.md](../DATA_MODEL.md) §4.3), or where any later domain records its events. Those keep the meaning their own documents give them. A domain that wants AuditEvent for its events decides that itself, and adds its target types by point 31.
30. **Its fields, and why each is there:**

    | Field | Content | Why |
    |---|---|---|
    | identifier | Database-generated integer | The order of events is the order of their identifiers, as in ADR-0017, not of their times |
    | action | One of a closed list (point 31) | What was done |
    | target type | One of a closed list (point 31) | Which kind of record, without a foreign key into a higher layer |
    | target public identifier | UUID | Which record |
    | actor | Foreign key to User, required, `PROTECT` | Who did it |
    | correlation ID | The request's, as the other event tables hold it | Ties the event to the log lines of the same request (NFR-06) |
    | time | UTC | When |

31. **The vocabulary is closed and is held in `accounts`**, as two fixed lists with database checks: the actions `created`, `updated`, `deactivated`, `reactivated`, `marked_entered_in_error`, and the target types `registry.country`, `registry.language`, `registry.institution`, `registry.institution_name`. A further check allows `deactivated` and `reactivated` only for a country or a language, and `marked_entered_in_error` only for an institution name. `accounts` knows these names as text and imports nothing for them. A later domain adds its target types here, with a migration that widens the check.
32. **Every AuditEvent has an application actor.** The column is required. There is no actor-less audit event and no bootstrap exception: every registry write is made by a signed-in account. An event's actor is never anonymous, a system account, or free text. The table as built here therefore cannot hold a system-generated event, and this ADR does not make it able to. Whether it ever should is for the decision that first needs one.
33. **The actor is a foreign key, not a copy of an email address.** The event then names the account and holds no personal data of its own. When an account is anonymised (ADR-0007 rule 10), the events that name it stay and say nothing they should not.
34. **There is no free text.** No reason, no description, no note. AuditEvent has no field into which a person or a program can write a sentence.
35. **Changed values are recorded, in a narrow child record.** A registry record is overwritten in place. Without the value it had, the audit record would say that a country's name changed and not from what, and the earlier value would be gone. So an `updated` event has one **AuditEventChange** for each field that changed: the event, the field, the old value, the new value.
    - The field is one of a closed list with a database check: `name_en`, `kind`, `country`, `parent`, `successor`, `valid_from`, `valid_to`.
    - A value is the attribute's own value in one fixed rendering: text as stored, a date in ISO 8601, a reference as the public identifier of the record referred to, nothing as the empty string. It is bounded in length.
    - A field is on that list only if it can hold no secret and no personal data. Nothing in the registry does.
    - The old and new values differ, and a field occurs once per event, both by database constraint.
    - `created`, `deactivated`, `reactivated`, and `marked_entered_in_error` events have no change records. The action says everything, and a record's first values are the old values of its first change.
36. **AuditEvent holds none of**: a password, a secret, a token, TOTP material, a session identifier, a source address or its hash, a header, or any personal data beyond the reference to the actor.
37. **Only successful changes are recorded.** A refused or failed operation writes no AuditEvent. A refused permission is logged by `require_permission`, as it is today.

### Writing an audit event

38. **One service function in `accounts` writes it**: it takes the actor's `AuthenticationContext`, the action, the target type, the target's public identifier, and the changes, and returns nothing. It reads the correlation ID itself. It is the only code that creates an AuditEvent or an AuditEventChange.
39. **It refuses to run outside a transaction.** An audit event written on its own could outlive a change that then failed, or be missing for one that succeeded. Called with no transaction open, it raises.
40. **It validates and decides nothing.** It checks that the action, target type, and fields are from the lists and that the pair is allowed. It does not check permissions and does not know what a country is: the calling service has done both.
41. **A registry service does five things, in this order, in one transaction**: require the permission; lock the row it changes; validate; write the change; write the audit event. It then returns, and logs the change after the transaction commits, with the correlation ID and the public identifier and no values.
42. **Either both are committed or neither is.** If the audit event cannot be written, the change is rolled back. If the change fails on a constraint, the transaction is rolled back, no audit event exists, and the service raises an explicit error. Nothing is retried.
43. **A change that changes nothing is refused**, writes nothing, and records nothing.
44. **No signal, no model `save` override, and no database trigger writes an audit event.** A trigger cannot know the actor, and a signal hides the control flow that ADR-0001 keeps explicit.

### Protecting the audit record

45. **AuditEvent and AuditEventChange are append-only at two layers**, with separate jobs:

    | Layer | Refuses | Does not cover | Role |
    |---|---|---|---|
    | The shared base in `core` | Updates and deletes made through the model and its queryset | SQL sent past the model; another manager | Fails early and says why |
    | A PostgreSQL trigger on each table | UPDATE and DELETE of any row, by any database role, however sent | TRUNCATE; dropping or disabling the trigger | The boundary |
    | Database privileges (ADR-0008, Proposed) | TRUNCATE and changes to the trigger | — | Not built; in development the application connects as the owner |

46. **Six tables in this ADR have a trigger. The list is closed.**

    | Table | The trigger refuses | Kind |
    |---|---|---|
    | AuditEvent, AuditEventChange | Every UPDATE and every DELETE | Append-only, in the form of ADR-0012 point 8 |
    | Country, Language, Institution, InstitutionName | Every DELETE, and an UPDATE that changes an immutable column (points 17 and 19) | Mutable; not append-only |

    Each is one function and one trigger for its table, written out as SQL in the migration that creates the table, so that the table never exists unprotected. No helper is imported into a migration, because a helper edited later would change what an old migration does. **This is not a policy for any other table.** No Accepted ADR requires a trigger of every append-only table: ADR-0012, 0013, and 0015 each decided for a table of their own, and ADR-0005 leaves the database technique to be chosen with the first provenance migration. [DATA_MODEL.md](../DATA_MODEL.md) §9, open question 1, stays open for every table that is not one of these six.
47. **The services are responsible for what the trigger cannot know**: who may write, that the change and its event are one transaction, and that the content is from the closed lists. The trigger is responsible for the one thing the services cannot guarantee: that no code path, present or future, rewrites what was recorded.
48. **Redaction does not reach it.** [DATA_MODEL.md](../DATA_MODEL.md) §7 puts audit events outside the redaction exception, and this ADR adds no exception.

### Public identifiers (D4)

49. **A public identifier is a version 4 UUID**, generated by the application from the operating system's random source, stored in PostgreSQL's `uuid` type, and written in the canonical lower-case form with hyphens.
50. **It is unique by a database constraint and immutable** by the trigger of point 17. If a generated value collided, the insert would fail and the transaction with it; nothing retries.
51. **It carries no meaning.** It encodes no country, organisation, user, time, or sequence. That rules out UUID version 7 and any prefixed or derived scheme.
52. **It is never a credential.** Knowing an identifier gives nothing. Every read by identifier passes the same permission check as any other read, and a view is refused on its declaration before any record is looked up.
53. **The internal primary key stays** a database-generated integer, is what foreign keys use, and does not appear in a registry URL.
54. **Which records carry one, and the requirement each is traced to:**

    | Record | Public identifier | Requirement |
    |---|---|---|
    | Country, Language, Institution, InstitutionName | Yes | Each is the target of audit events, and a target is named by type and public identifier ([ARCHITECTURE.md](../ARCHITECTURE.md) §2.1). Registry pages address a record by it. |
    | User | **No** | Checked against each place one could be needed, and none needs it. The actor of an audit event is a foreign key inside `accounts`. No registry record refers to a user (point 3), so no change record renders one. No page addresses a user from outside the administration pages, which exist and are not changed here. Anonymising an account acts on the User row and needs no second identifier. Adding one would be symmetry and a migration on User. |
    | AuditEvent, AuditEventChange | No | Nothing refers to one. |

### Initial data (D5)

55. **No migration and no code creates a Country, a Language, or an Institution.** After the first Administrator exists, that Administrator enters the countries and languages through the registry's own services, so each has an actor and an audit event.
56. **No real institution appears in the repository**, in code, a migration, a fixture, or a test.
57. **No code path depends on a particular country.** The tests use only synthetic records, among them three synthetic countries under one set of rules, which is the extensibility test of [PROJECT_SPECIFICATION.md](../PROJECT_SPECIFICATION.md) §6. Synthetic codes come from the ranges the standards reserve for private use.
58. **The cost is accepted**: a fresh database has an empty registry, and a developer enters a country by hand. No requirement was found that outweighs an initial record with no accountable actor.

### Pages

59. **Two pages, and no others.** A browse page that lists countries, languages, and institutions with their names, declaring `REGISTRY_READ`. An entry page, declaring `REGISTRY_INSTITUTIONS_MANAGE`, which every account that may write anything holds; its forms for countries and languages are shown and accepted only for `REGISTRY_REFERENCE_MANAGE`, and each service checks for itself.
60. **They follow ADR-0010 and the access rule**: server-rendered, writes by POST with CSRF protection, every string marked for translation, every view declaring its access. The views hold no rule from this ADR.
61. **Nothing here registers a model with the Django admin**, which is not installed.

## Database and migrations

| Migration | Contains | Reversible |
|---|---|---|
| `accounts`, next number | AuditEvent and AuditEventChange, their constraints, and the append-only trigger of each | Yes: drops the triggers and the tables. Reversing it on a database that holds audit events destroys them, and the pull request says so. |
| `registry`, first | The four tables, their constraints, and for each a trigger that refuses DELETE and any UPDATE of its immutable columns | Yes, with the same warning for data |

- No existing migration is edited. The three existing event tables keep their triggers as they are.
- Moving the base classes to `core` produces no migration.
- No data migration exists, and no column is added to User or to any existing table.
- No PostgreSQL extension is needed.
- `registry`'s migration depends on none of `accounts`': it has no foreign key to it.

## Testing requirements

Every item is a test that fails if the rule is removed. Tests use only synthetic records.

1. **Permissions.** Each operation in point 13, for each of the four roles, for an anonymous context, for a disabled account, and for an Administrator on a password alone: allowed or refused as the matrix says, and a refusal writes nothing.
2. **Atomicity.** A change and its audit event are both present after success. With the audit write made to fail, the change is absent. With the change made to fail on a constraint, no audit event is present. Run as transactional tests, because an enclosing test transaction would hide the difference.
3. **The writer.** Refuses outside a transaction, refuses an unknown action, target type, field, and a pair that is not allowed.
4. **Append-only.** For AuditEvent and AuditEventChange: the model guards refuse, and UPDATE and DELETE sent as SQL past the model are refused by the database.
5. **Registry immutability.** DELETE on each of the four tables, an UPDATE of each immutable column, and the clearing of an entered-in-error mark, sent as SQL, are refused by the database.
6. **Each database constraint**, exercised directly: the forms and uniqueness of the codes, the date order, not-own-parent, not-own-successor, successor-needs-valid-to, the uniqueness of public identifiers, the closed lists of the audit record.
7. **Each service rule**: cycles of parents and of successors, the successor's dates, the refusal of a deactivated country or language, the refusal of a change that changes nothing, an institution created with its first name, a name marked as entered in error, the refusal to mark an institution's only unmarked name.
8. **Concurrency.** Two simultaneous changes that would together form a cycle: one is refused.
9. **Content of the audit record.** The actor, the target, and the old and new values of each changed field are what was done; a `created` event has no change records; no field holds anything from point 36.
10. **Country independence.** The same tests run for three synthetic countries, and a test finds no literal country code in the application code.
11. **Pages.** Each view declares its access; each role reaches or is refused each page; the country and language forms are refused without `REGISTRY_REFERENCE_MANAGE`.
12. **The existing suite passes unchanged in behaviour.** Tests that import the base classes change the import and nothing else.
13. **The import contracts** are kept, including the new one of point 2.

## Conflicts with existing documents

This ADR edits no other document and no Accepted ADR. The documents named below are changed in the implementing pull request.

### Resolved by this draft

| # | Document | It says | Resolution |
|---|---|---|---|
| C1 | [ARCHITECTURE.md](../ARCHITECTURE.md) §2.1 | `accounts` and `registry` share layer 1 | `registry` is above `accounts` (point 1). ADR-0001 delegates the layer table to that document, so no ADR is superseded. The table is changed at implementation. |
| C2 | [PROJECT_SPECIFICATION.md](../PROJECT_SPECIFICATION.md) §3; ADR-0012 point 2 | "Reviewer: Researcher, plus …" | Reviewer holds what Researcher holds (point 14). No conflict remains. The role table gains the registry at implementation. |
| C3a | ADR-0012 point 3 | "Administrator does not receive research permissions" | `REGISTRY_REFERENCE_MANAGE` is administrative control over configuration and no research permission. No conflict. |
| C3b | ADR-0012 point 3 | The same, so that operating the system gives no say over the evidence base | Decided by the project owner on 2026-10-09 (O2): maintaining institutions is registry maintenance, and Administrator holds `REGISTRY_INSTITUTIONS_MANAGE`. It is not a research permission and confers none. ADR-0012 is not amended. |
| C4 | [DATA_MODEL.md](../DATA_MODEL.md) §3.2, §5 | Language has two codes; a name has no dates and no mark; registry records are not among those with a public identifier | Additions, not contradictions. The document is updated at implementation. |
| C6 | [DATA_MODEL.md](../DATA_MODEL.md) §9, open question 1 | Whether later append-only tables follow the RoleEvent pattern is open | Decided for the six tables of point 46 and for no other. |

### Requires an explicit decision of the project owner

None. C3b was the one such conflict; it was decided on 2026-10-09 and is recorded above.

### Future questions, outside this ADR

| # | Document | Question | Where it belongs |
|---|---|---|---|
| C5 | [DATA_MODEL.md](../DATA_MODEL.md) §4.3 | How the automatic move of a claim to `needs_reassessment` is recorded, and by what record | Phase 4. Not changed and not prejudged here (points 29 and 32). |
| C7 | [ARCHITECTURE.md](../ARCHITECTURE.md) §10; ADR-0007 rule 7 | Which approvals, rights determinations, index changes, and administrative actions of later domains are written to AuditEvent | Each domain's own decision |
| C8 | [DATA_MODEL.md](../DATA_MODEL.md) §9, open question 1 | The database technique for every other append-only table | With each table; ADR-0005 |
| C9 | ADR-0012, Consequences | Database privileges that stop TRUNCATE and changes to a trigger | ADR-0008 |

## Alternatives considered

- **`registry` beside `accounts`, with the view deciding permissions and writing the audit event.** It keeps the layer table. It moves a business rule into `web`, lets any other caller skip it, and breaks ADR-0012 point 1.
- **AuditEvent in `core`.** Every app could write it without `accounts`. But `core` may not refer to users, so the actor would be a bare identifier with no referential integrity, User would need a public identifier for that purpose alone, and `core` would hold a table of domain vocabulary.
- **A new `audit` app between `accounts` and `registry`.** Clean layering, and a thirteenth app where twelve is called the upper bound, to hold two tables that the documents already assign to `accounts`.
- **A `RegistryEvent` table in `registry`, as `accounts` has its three.** One table for each domain, each with its own shape, is the opposite of a general boundary, and every later reader of "who changed this" would query eight tables.
- **Reusing `RESEARCH_CONTRIBUTE` for institutions and `ROLES_MANAGE` for countries.** No new permission. Registry maintenance would then be a research permission, an Administrator could maintain institutions only by being given one, and a permission about roles would come to mean countries.
- **Reviewer read-only, as D1 was first worded.** It contradicts "Reviewer: Researcher, plus" and ADR-0012 point 2. Keeping it would mean amending an Accepted ADR for the registry alone.
- **Giving Administrator `RESEARCH_CONTRIBUTE` or `WORKSPACE_READ` so that it can maintain or see the registry.** Exactly what ADR-0012 point 3 forbids.
- **Two permissions, with reads accepting `WORKSPACE_READ` or a write permission.** One permission fewer. Every read would then ask two questions, which is the pattern ADR-0012 point 1 exists to prevent.
- **Recording only the names of changed fields.** Smaller and free of values. The earlier value of an overwritten record would be unrecoverable, which is the thing an audit of mutable records is for.
- **A JSON column of details.** Flexible, and an event schema that nothing bounds and no constraint can check.
- **Django content types and a generic foreign key for the target.** It ties the record to model names and to integers, and DATA_MODEL principle 10 rules generic foreign keys out.
- **The ISO codes as the public identifier of a country or language.** Meaningful identifiers, of a different shape for each record type, in a column that would then be text.
- **UUID version 7, or the integer key.** The first encodes a time; the second is a sequence that reveals how many records exist and invites guessing.
- **A name whose text can be edited, with the audit record keeping the old text.** The history would survive in the audit record, and the registry could no longer tell a correction from a rename.
- **No way to mark a wrong name.** Nothing to build. A name known to be wrong would be shown as a name for ever, or be given a valid-to date that states something untrue.
- **A precision beside each date (year, month, or day), or dates as text.** It would record "in 2019" honestly. It doubles the date columns and complicates every date rule, for a need that no real institution has yet shown. An empty date loses nothing that cannot be added later.
- **An "other" kind, or kinds as a table that an Administrator edits.** Either lets a body be recorded today. The first hides what the body is; the second makes a classification that analysis will group by changeable without review of the model.
- **One shared trigger function, or a helper that generates the SQL.** Less repetition. It needs either a migration in `core` that every app depends on, or application code imported into migrations.
- **A trigger that also refuses TRUNCATE.** PostgreSQL allows one. The three existing tables have none, and Django clears tables with TRUNCATE between transactional tests, so it would need its own design. It stays a matter of privilege under ADR-0008.
- **A data migration with the first countries and languages.** Convenient, and records with no actor and no audit event, written by a migration that then names particular countries.

## Consequences

- The registry can be corrected freely, and every correction says who made it, when, and what the value was before.
- `accounts` holds the vocabulary of the audit record, so each new domain changes a list in `accounts` and adds a migration there.
- The specification's role table does not mention the registry. It gains it at implementation; no role's existing line changes.
- An Administrator can maintain institutions without holding a research role, and gains nothing in the evidence base by it.
- A wrong audit event cannot be corrected. A wrong registry value is corrected by a further change, which is itself recorded.
- A name entered with a mistake stays in the table, marked. The mark cannot be undone.
- A body that fits none of the eight kinds cannot be recorded until the list is extended.
- A split of one body into several cannot be recorded as succession. The bodies can be recorded; the links cannot.
- A date known only to the year or month is left empty, and what is known of it is recorded nowhere in the registry.
- Nothing in the application reads the audit record in this milestone. It is read by a database query until a page is designed.
- The audit record can be trusted as far as the database can, with the same limit as ADR-0012: TRUNCATE and the trigger itself are protected only by privileges that ADR-0008 has not yet defined.
- Reversing either migration on real data destroys it.

## Not in this milestone

| Excluded | Where it belongs |
|---|---|
| Source, Document, DocumentVersion, Artifact, and everything else in `sources` | Phase 2 |
| Ingestion, the job system, workers, OCR | Phase 2; ADR-0004, ADR-0011 |
| Policy, Indicator, Evidence, claims | Phases 3 and 4 |
| Retrieval, vector search, the assistant, any AI provider | Phase 5; ADR-0003, ADR-0006 |
| RedactionRecord and the redaction procedure | Its own decision |
| A page or selector that reads the audit record | A later increment, with its own permission |
| Events that no account initiates, and the events of any other domain | Their own decisions (C5, C7) |
| Any change to authentication, roles, existing permissions, or the three existing event tables | Not planned |
| A public page for the registry | With the public research site |
| The Django admin | Its own increment (ADR-0007 rule 8) |
| Database roles and privileges | ADR-0008 |
| Retention of audit events | A data-governance decision |
| Any new dependency | None is needed |

## Owner decisions at acceptance

The project owner accepted this ADR on 2026-10-09 and decided the five questions it had left open. None remains open.

| # | Question | Decision | Where it is written |
|---|---|---|---|
| O1 | How is an institution name that was entered by mistake dealt with? | It receives a set-once entered-in-error mark, which cannot be removed or reversed. The name is not edited and not deleted. | Points 19, 20, 31 |
| O2 | Does an Administrator who holds no research role create and maintain institutions and their names? | Yes, through `REGISTRY_INSTITUTIONS_MANAGE`, which is registry maintenance only. It gives no research-contribution or research-review authority. | The introduction to "Write authority", points 11 and 13, C3b |
| O3 | Must a date known only to the year or the month be recordable as such? | No. A date is a full date, or empty when the exact date is unknown. There is no date-precision field. | Point 21 |
| O4 | Which kinds of institution exist? | The eight in [DATA_MODEL.md](../DATA_MODEL.md) §3.2, and no "other" kind. Their adequacy is confirmed before the first real institution is entered. | Point 10 |
| O5 | Does the audit record keep the old and new values of a change, or only which fields changed? | The old and new values, in AuditEventChange, under the closed list of fields. No JSON. | Point 35 |

## Architecture gate: before implementation starts

The Phase 1 gate is READY, and countries and institutions are Phase 1. Implementation of this ADR nevertheless starts only when all of these are true. The first four were met on 2026-10-09; the fifth holds for as long as the implementation lasts.

1. The project owner has accepted this ADR, and its status and date say so.
2. O1 to O5 are decided, and no open point remains, as the ADR process requires of an Accepted ADR.
3. The resolutions of C1, C2, C3a, C3b, C4, and C6 stand.
4. `CLAUDE.md`, the ADR index, and the specification's table list ADR-0018 as Accepted.
5. No new dependency is required. If one turns out to be, implementation stops and it is justified first.

And the implementing pull request is complete only when:

6. [ARCHITECTURE.md](../ARCHITECTURE.md) §2.1, [DATA_MODEL.md](../DATA_MODEL.md) §3.1, §3.2, §5, and §9, [SECURITY.md](../../SECURITY.md), and the specification's §3 and §7 say what was built.
7. The import contracts include `registry` and the contract of point 2, and are kept.
8. Every test in "Testing requirements" exists and the full suite passes, with `ruff`, `mypy`, the dependency audit, and the secret scan.
9. Both migrations have been reviewed as the Definition of Done requires.

## Revisit when

A second domain writes audit events; an audit event without an actor is needed; a page must show the audit record; the deployment decision defines database roles; a real split of an institution must be recorded; the registry gets a public page; or a retention policy is set.
