# ADR-0019: Phased registry implementation

- Status: Accepted
- Date: 2026-10-11

## Context

[ADR-0018](0018-registry-and-general-audit-record.md) decided the registry and the general audit record. It was accepted before its implementation and is built in increments. Increment 1, the audit foundation, is merged: the shared append-only base in `core`, AuditEvent and AuditEventChange with their constraints and triggers, and the one service that writes them. The audit writer exists, but no registry service emits a registry audit event, because the `registry` app is not yet implemented.

ADR-0018 says what the finished registry is. It was worded for one implementing pull request, and in one place it says when something is built: the table under "Database and migrations" puts all four registry tables in the first `registry` migration. Its point 59, its thirteen testing requirements, and items 6 to 9 of its gate describe the finished registry and do not say how a part of it is judged.

What remains is the largest single change the project has had: a new app in a new layer, two import contracts, three permissions, four tables with a trigger each, the eleven write rows of the matrix in point 13, the rules of hierarchy and succession with their lock, and two pages. It divides at one place. Country and Language refer to nothing. Institution and InstitutionName refer to them, and hold every rule that depends on more than one row: cycles, succession, the names of a body, the serialized change of a parent or successor.

Dividing it there needs a decision, for three reasons:

- It contradicts the one timing statement named above. An Accepted ADR's decision is not edited, so a new ADR says so.
- A part of the registry must be judged against requirements written for the whole. Without a stated allocation, a requirement can be deferred because its number is "about institutions" when part of it is about countries.
- A page that ADR-0018 describes in its final form exists for a time without the records of the later increment. What it shows meanwhile, and to whom, should not be decided in a pull request.

The project owner set the decisions recorded below on 2026-10-10, all but the forms of the Language codes (points 29 to 32), and asked for them to be written as this ADR. A review against the text of ADR-0018 found one statement that the phased approach replaces, one exception that it records, and one check whose form ADR-0018 requires and does not state: point 7 says that the language code and the script code are "checked for form only" and gives no pattern. The project owner has decided both patterns and confirmed them on 2026-10-11, in the review of this draft. That is a separate decision from those of 2026-10-10, and it is recorded here so that Increment 2 does not choose the patterns. No other decision of ADR-0018 is touched. All three are listed under "Changes to ADR-0018".

The project owner reviewed the final text of this ADR and accepted it on 2026-10-11 ("Open points"). Its date is the date of that acceptance. The decisions on phased delivery were set on 2026-10-10 and the forms of the Language codes were confirmed on 2026-10-11, as said above. Acceptance starts no increment (point 24).

This ADR is about the order of delivery, with one addition: the two code forms of points 29 to 32, which clarify point 7 of ADR-0018 and supersede nothing in it. Beyond that it decides nothing about what the registry holds, who may write it, how a change is audited, how a record is identified, or what data it starts with.

## Decision

### The increments

1. **ADR-0018 is built in three increments.** The first is done.

    | Increment | Builds | State |
    |---|---|---|
    | 1 | The audit foundation (ADR-0018 points 24 to 48) | Merged |
    | 2 | The `registry` app, its layer and import contracts, the three permissions, Country and Language with their services, and the two pages as far as those two records go | Not started |
    | 3 | Institution and InstitutionName with their services, and the rest of both pages | Not started |

2. **Increment 2 builds**, each as ADR-0018 decides it: the `registry` package in its own layer above `accounts` and the second import contract (points 1 and 2); the three permissions with the role assignments of point 11; Country and Language (points 6 and 7) with their public identifiers; the first `registry` migration; the six Country and Language rows of the write matrix (point 13) and the reads; the browse page and the entry page (points 59 to 61) as points 11 to 15 below limit them.
3. **Increment 3 builds**: Institution and InstitutionName (points 8 to 10) with their public identifiers; the second `registry` migration; the five Institution and InstitutionName rows of the write matrix; the rules of points 18 to 23 that concern an institution or a name; and the institution content of both pages.
4. **Institution and InstitutionName are one increment.** An institution is created together with its first name, in one transaction (ADR-0018 point 20), so neither can be built without the other.
5. **An increment builds nothing of a later one.** Increment 2 contains no Institution or InstitutionName model, table, operation, selector, form, page section, disabled control, or text that announces one. An absent feature is absent.
6. **All three permissions exist from Increment 2**, because the entry page declares `REGISTRY_INSTITUTIONS_MANAGE` from the start (point 11 below). Until Increment 3 that permission admits an account to the entry page and allows no operation. Its holders are those of ADR-0018 point 11 and no others.

### Migrations

7. **The first `registry` migration creates Country and Language, and only those.** The second creates Institution and InstitutionName, in Increment 3.
8. **Each table is created with its constraints and its trigger in the migration that creates it**, as ADR-0018 point 46 requires: one function and one trigger for each table, written out as SQL, refusing every DELETE and any UPDATE of an immutable column. No registry table exists at any migration state without that protection. The list of six protected tables stays closed and unchanged.
9. **Dependencies.** The second `registry` migration depends on the first, because Institution refers to Country and InstitutionName to Language. No `registry` migration depends on an `accounts` migration, and no `accounts` migration depends on a `registry` migration (ADR-0018 point 1).
10. **Both migrations are reversible, and reversing either destroys data.**
    - Reversing the second drops Institution and InstitutionName and every record in them.
    - Reversing the first drops Country and Language and every record in them. It can be done only after the second is reversed.
    - Neither can be undone by applying the migration again: the tables return empty.
    - Audit events are not removed by either, because they are in `accounts` and name their target by public identifier. They then name records that no longer exist.
    - The pull request of each increment says this in its description, in these terms.

### Pages

11. **Both pages exist from Increment 2 with their final access declarations.** The browse page declares `REGISTRY_READ`. The entry page declares `REGISTRY_INSTITUTIONS_MANAGE`. Neither declaration changes in Increment 3. ADR-0018 calls the second page the entry page, and this ADR keeps that name.
12. **In Increment 2 the browse page lists countries and languages.** In Increment 3 it also lists institutions with their names. ADR-0018 point 59 describes the page as it is when Increment 3 is merged, and the registry is not complete before then.
13. **In Increment 2 the entry page holds the Country and Language forms**, shown and accepted only for an account that holds `REGISTRY_REFERENCE_MANAGE`. In Increment 3 it gains the Institution and InstitutionName forms for every account that reaches it.
14. **Authorization is decided on the server, twice.** The view refuses a POST of a Country or Language form from an account without `REGISTRY_REFERENCE_MANAGE`, and each service requires its permission for itself whatever the view has checked (ADR-0018 points 13 and 59). Not showing a form is a courtesy to the reader of the page and is never the check.
15. **The entry page is never blank or misleading.** In Increment 2 an account that reaches it without `REGISTRY_REFERENCE_MANAGE` (a Researcher, or a Reviewer verified with a trusted second factor) is shown a plain message: that countries and languages are maintained by an Administrator, and that the page offers this account nothing to do. The message states what is true at that time and promises nothing. In Increment 3 that account has the institution forms, the message is no longer true, and it is removed.
16. **No third page is added in any increment.** "Two pages, and no others" stands.

### What does not change

17. **Every other decision of ADR-0018 stands as written**, and each increment is held to it. Point 7 stands too: points 29 to 32 state the forms it requires and change nothing in it. In particular:
    - The role assignments of point 11: `REGISTRY_READ` for Reader, Researcher, Reviewer, and Administrator; `REGISTRY_REFERENCE_MANAGE` for Administrator only; `REGISTRY_INSTITUTIONS_MANAGE` for Researcher, Reviewer, and Administrator. None is a research permission and none confers one (points 12 and 14, and the decision O2).
    - Public identifiers are version 4 UUIDs, unique and immutable (points 49 to 54).
    - No migration and no code creates a registry record, and no real country, language, or institution appears in the repository (points 55 to 58).
    - The closed lists of actions, target types, and change fields (points 31 and 35) are neither extended nor reduced. They were created in full in Increment 1, so they already name targets and fields that nothing writes until Increment 3.
    - Every audit event is written by `accounts.services.record_audit_event`, in the transaction of the change it records, and both are committed or neither is (points 38 to 44).
    - `registry` uses `accounts` only through `accounts.services` and `accounts.selectors`, and the import contracts say so (points 1 and 2). This ADR adds no contract. It records one exception, for registry tests that inspect AuditEvent and AuditEventChange and for nothing else, in points 25 to 28 below.
18. **This ADR adds no permission, field, record type, operation, page, dependency, or audit vocabulary.** It adds no check either: points 29 to 32 give the pattern of the form check that ADR-0018 point 7 already requires of the two Language codes.

### Judging an increment

19. **Each increment is judged against every requirement of ADR-0018 that applies to what it builds**, and the complete registry is judged against all of them when Increment 3 is merged. "Testing allocation" says which requirement applies where.
20. **A requirement is deferred to Increment 3 only if it cannot be met without Institution or InstitutionName.** A rule of Country or Language is tested in Increment 2 even where ADR-0018 lists it in the same sentence as an institution rule.
21. **Every increment is complete for what it builds.** The Definition of Done applies to each pull request in full. No test is weakened, skipped, or deleted to make an increment pass, and the suite that exists before an increment passes after it, including every test of authentication, account recovery, the second factor, and the audit record.
22. **Two kinds of Increment 2 test are replaced in Increment 3, and only these**: a test that the pages hold no institution content, and a test of the message of point 15. Each asserts something this ADR decides is true only until Increment 3. The Increment 3 pull request names each replaced test and the test that replaces it. Every other Increment 2 test passes unchanged.
23. **Items 6 to 9 of ADR-0018's gate apply to each increment's pull request for what it builds**: the documents named in item 6 say what that increment built and no more, the import contracts are kept, the tests allocated to it exist, and its migration is reviewed. Increment 3's pull request also confirms all four items for the registry as a whole.
24. **Accepting this ADR starts nothing.** The project owner starts each increment.

### The import boundary and its one test exception

25. **Registry runtime code does not import `accounts.models`.** Every module of `caipo.registry` outside `caipo.registry.tests` uses `accounts` only through `accounts.services` and `accounts.selectors`, as ADR-0018 point 2 says, and writes an audit event only by calling `accounts.services.record_audit_event`. Nothing in this ADR allows otherwise, in either increment.
26. **One exception, for tests only**, agreed by the project owner:

    `caipo.registry.tests.**` -> `caipo.accounts.models`

    A module under `caipo.registry.tests` may import `AuditEvent` and `AuditEventChange` from `caipo.accounts.models`, to inspect the audit records that a registry service wrote. That is the whole of the exception. Requirements 2 and 9 of ADR-0018 ask a registry test to show that an audit event is present or absent and what it holds, and nothing in `accounts.services` or `accounts.selectors` reads the audit record: ADR-0018 leaves a selector that does to a later increment, with its own permission.
27. **The exception is exactly that, and is not a general permission to import account models.** Its source is the test modules of `registry` and no other module. Its target is `caipo.accounts.models` and no other module, and from that module the two audit models and no other name: not User, and no role, session, device, recovery, or authentication-event model. A registry test that needs a user takes one from the fixtures of `caipo/accounts/tests/fixtures.py`, which the `conftest.py` at the repository root registers for the whole suite, and where it needs the User class itself it uses `get_user_model()`. The exception is for reading. A test creates no AuditEvent and no AuditEventChange through the model: `record_audit_event` stays the only code that does (ADR-0018 point 38). It changes nothing in the layering contract or in any contract of another app.
28. **How the exception is written in the import-linter configuration is settled in Increment 2**, where the contract of ADR-0018 point 2 is first added. This ADR prescribes no configuration and changes none: `pyproject.toml` is as it was. Increment 2 shows that what it wrote is this boundary and no wider: the contract fails when a registry runtime module imports `caipo.accounts.models`, and passes when a registry test module does. import-linter tells one module from another and not one name from another, so the limit to AuditEvent and AuditEventChange is kept by review of each registry test module.

### The forms of the Language codes

29. **The language code is exactly three lower-case ASCII letters: `[a-z]{3}`.** This is the form of an ISO 639-3 alpha-3 code.
30. **The script code is exactly four ASCII letters, one capital followed by three lower-case: `[A-Z][a-z]{3}`.** This is the form of an ISO 15924 alpha code.
31. **Form only, and one form each.** The whole value matches its pattern, and no list of assigned codes is held or consulted: membership in a registry of codes is not required, as point 6 of ADR-0018 decides for the Country codes and for the same reasons. No other representation is accepted. A two-letter language code is refused. A value that joins a language and a script in one code is refused. So is any other alternate form that the project owner has not approved.
32. **The pair `(code, script_code)` is unique**, as ADR-0018 point 7 says. Points 29 to 31 are a supplementary clarification of that point, confirmed by the project owner on 2026-10-11. They supersede nothing in ADR-0018. Each pattern is held twice, as the forms of the Country codes are. It is a database check on Language, created with the table in the first `registry` migration (point 8): ADR-0018 lists "the forms and uniqueness of the codes" among the database constraints of its testing requirement 6, so that the form is enforced by the database is its decision and not this ADR's. It is also a rule of the Language service, which validates what is entered before it writes (ADR-0018 point 41). The two are tested apart, under requirements 6 and 7.

## Testing allocation

The thirteen requirements are those of ADR-0018, "Testing requirements", in its numbering and its wording. None is added, removed, or reworded. "Every item is a test that fails if the rule is removed" holds in each increment. Tests use only synthetic records.

| # | ADR-0018 requirement | Increment 1 (merged) | Increment 2 | Increment 3 |
|---|---|---|---|---|
| 1 | Permissions | — | Each Country and Language operation of point 13 and the read, for each of the four roles, an anonymous context, a disabled account, and an Administrator on a password alone. A refusal writes nothing. | The same for each Institution and InstitutionName operation and for the read of those records |
| 2 | Atomicity | — | The three cases, for Country and Language changes, as transactional tests | The same for Institution and InstitutionName changes, including the creation of an institution with its first name |
| 3 | The writer | All of it | Passes unchanged | Passes unchanged |
| 4 | Append-only | All of it | Passes unchanged | Passes unchanged |
| 5 | Registry immutability | — | DELETE on Country and on Language, and an UPDATE of each of their immutable columns: both codes of each, and the public identifier | DELETE on Institution and on InstitutionName, an UPDATE of each of their immutable columns, and the clearing of an entered-in-error mark |
| 6 | Each database constraint | The closed lists of the audit record | The database constraints of Country and Language, each exercised directly: the form of each Country code, two capital letters for the alpha-2 code and three for the alpha-3 code (ADR-0018 point 6); the uniqueness of each Country code, alpha-2 and alpha-3 separately (point 6); the form of the Language code, `[a-z]{3}` (ADR-0018 point 7, and point 29 of this ADR); the form of the Language script code, `[A-Z][a-z]{3}` (ADR-0018 point 7, and point 30 of this ADR); the uniqueness of the pair `(code, script_code)` (ADR-0018 point 7); the uniqueness of the public identifier of Country and of Language (point 50) | The date order on Institution and on InstitutionName; not-own-parent; not-own-successor; successor-needs-valid-to; the uniqueness of the public identifiers of Institution and InstitutionName |
| 7 | Each service rule | — | Every rule of the Country and Language services: validation of what is entered, including the refusal by the service of a code that is not in its form (ADR-0018 point 6 for Country, points 29 to 31 of this ADR for Language); deactivation and reactivation, with the record kept and readable; the refusal of a change that changes nothing (the same name, deactivating a deactivated record, reactivating an active one) | Cycles of parents and of successors; the successor's dates; the refusal to give an institution a deactivated country or a name a deactivated language; the refusal of a change that changes nothing, for Institution and InstitutionName; an institution created with its first name; a name marked as entered in error; the refusal to mark an institution's only unmarked name |
| 8 | Concurrency | — | Deferred to Increment 3 — cycle-forming concurrent changes. No hierarchy or succession exists yet. The supplementary concurrency tests of Country and Language below do not satisfy or replace this requirement. | All of it, as worded |
| 9 | Content of the audit record | — | For every Country and Language event: the actor, the target, the old and new value of `name_en`; no change records on `created`, `deactivated`, and `reactivated`; nothing from point 36 | For every Institution and InstitutionName event: the same, with each of `kind`, `country`, `parent`, `successor`, `valid_from`, and `valid_to` in its fixed rendering; no change records on `created` and `marked_entered_in_error` |
| 10 | Country independence | — | The Country tests run for three synthetic countries; the test that finds no literal country code in the application code exists from here | The Institution tests run for the three synthetic countries; the literal-code test covers the new code |
| 11 | Pages | — | Each view declares its access; each role reaches or is refused each page; the Country and Language forms are refused without `REGISTRY_REFERENCE_MANAGE`; the message of point 15; no institution content | The same access tests; the browse page lists institutions with their names; the institution forms are accepted for `REGISTRY_INSTITUTIONS_MANAGE` and the Country and Language forms still refused without `REGISTRY_REFERENCE_MANAGE` |
| 12 | The existing suite passes unchanged in behaviour | Done, with the import of the base classes changed | The whole suite | The whole suite, with the two replacements of point 22 |
| 13 | The import contracts | The existing contract kept | `registry` added to the layering contract; the contract of ADR-0018 point 2 added, with the test exception of point 26 and the demonstration of point 28; both kept | Both kept |

Increment 2 is therefore complete for Country and Language in every kind of test: permissions (1), atomicity (2), immutability (5), database constraints (6), validation and lifecycle (7), audit content (9), country independence (10), pages (11), regression (12), the import contracts (13), and the supplementary tests below for simultaneous use and for the migration.

Four allocations need their reasons stated, because each is where a requirement is easily put in the wrong increment or the wrong kind of test.

- **Requirement 6 is the database's, and requirement 7 the services'.** A requirement 6 test sends the database a row that a constraint must refuse, past the model and the service, and fails if that constraint is removed. The validation of what a person enters is a service rule, tested under requirement 7. Neither test stands for the other: a form that the service refuses is still tested against the database, and the reverse. The constraints are those of ADR-0018 and no others. Point 6 states the form of the two Country codes. Point 7 says of the Language code and the script code only that they are "checked for form only", and states no pattern. The patterns are those of points 29 and 30, which the project owner decided. This ADR adds no other constraint.
- **Requirement 7 is divided, not deferred.** Its sentence lists seven rules, six of which need an institution. "The refusal of a change that changes nothing" (point 43) applies to every service, so it is tested for Country and Language in Increment 2 and for Institution and InstitutionName in Increment 3. "Each service rule" is the requirement, and the list after it is not a limit: the Country and Language services have rules of their own, and those are Increment 2's.
- **"The refusal of a deactivated country or language" is two things.** The lifecycle of a Country or Language (it is deactivated, it stays and stays readable, it is reactivated, and a deactivation that changes nothing is refused) belongs to its own services and to Increment 2. That a deactivated record "cannot be newly referred to" (point 18) is a rule of the Institution and InstitutionName services, and nothing can refer to a Country or a Language before Increment 3. Only that second rule is deferred.
- **Requirement 8 is Increment 3's, whole and as worded.** It is one case: two simultaneous changes that would together form a cycle. It needs the parent and successor links of Institution and the lock of point 23, so it cannot be met earlier. Nothing in Increment 2 meets it, replaces it, or counts towards it.

### Supplementary tests, outside the thirteen

These are not requirements of ADR-0018 and are not numbered with them. The project owner agreed them for this phased delivery. Each asserts a rule that ADR-0018 or this ADR already states, and none adds a rule.

| Increment | Test | The rule it asserts |
|---|---|---|
| 2 | **Simultaneous creation with the same identity.** Two creations of a Country with the same alpha-2 code or the same alpha-3 code, and of a Language with the same pair of codes, run in real concurrent transactions. The database keeps the code or the pair unique: one record is stored, with one audit event. The other attempt raises the service's explicit error and leaves no record and no audit event. Nothing is retried. | ADR-0018 points 6, 7, and 42 |
| 2 | **Simultaneous operations on one record.** Two identical changes to one Country or Language (the same new name, two deactivations, two reactivations), run in real concurrent transactions. The row lock admits one, which is stored with one audit event. The other is refused as a change that changes nothing and records nothing. | ADR-0018 points 41 and 43 |
| 2 | **The first `registry` migration.** It creates Country and Language and no other table; both triggers exist once it is applied; it depends on no `accounts` migration; it reverses. | Points 7 to 10 of this ADR |
| 3 | **The second `registry` migration.** It creates Institution and InstitutionName; both triggers exist once it is applied; it depends on the first `registry` migration and on no `accounts` migration; it reverses. | Points 7 to 10 of this ADR |

The two tests of simultaneous use are integrity tests of Country and Language. They are kept in Increment 2 as allocated. They do not satisfy or replace requirement 8, and Increment 3 owes requirement 8 in full whatever Increment 2 has tested.

## Changes to ADR-0018

ADR-0018 stays Accepted and is not edited. As ADR-0017 did for ADR-0014, the statements affected are named here. They changed when this ADR was accepted, on 2026-10-11, and not before.

**One statement is superseded.**

| ADR-0018 | Says | Becomes |
|---|---|---|
| "Database and migrations", the row for the first `registry` migration, column "Contains" | "The four tables, their constraints, and for each a trigger that refuses DELETE and any UPDATE of its immutable columns" | The first `registry` migration contains Country and Language; the second contains Institution and InstitutionName. Each table comes with its constraints and its trigger, in the migration that creates it. |

Only the timing is superseded: that the four tables arrive together. What each table is, its constraints, its trigger, and the "Reversible" column of that row are kept, and apply to each of the two migrations.

**One exception is recorded.** It supersedes nothing: the rule of point 2 stands for all registry runtime code.

| ADR-0018 | Says | Becomes |
|---|---|---|
| Point 2 | `registry` "does not import `accounts.models`", and a second import-linter contract forbids that import | True of every module of `caipo.registry` outside `caipo.registry.tests`. A module under `caipo.registry.tests` may import `AuditEvent` and `AuditEventChange` from `caipo.accounts.models` to inspect audit records, and nothing else from it (points 25 to 28). |

**One clarification is added.** It supersedes nothing: point 7 required the check and did not state its form.

| ADR-0018 | Says | Clarified as |
|---|---|---|
| Point 7 | "A language code and a script code, both required, unique as a pair, checked for form only" | The language code is `[a-z]{3}`, the form of an ISO 639-3 alpha-3 code. The script code is `[A-Z][a-z]{3}`, the form of an ISO 15924 alpha code. Form only, with no list of assigned codes, and no other representation (points 29 to 32). Both stay required and unique as a pair. |

**The statements below are read for a registry delivered in parts.** None is superseded: each still describes the finished registry, and only the count of migrations and of pull requests differs.

| ADR-0018 | Says | Read as |
|---|---|---|
| "Database and migrations": "`registry`'s migration depends on none of `accounts`'"; gate item 9, "Both migrations"; Consequences, "Reversing either migration" | One `registry` migration, two migrations in all | Two `registry` migrations, three in all. Every statement made of the one holds of each. |
| Point 59 | A browse page that lists countries, languages, and institutions with their names | The page when Increment 3 is merged. In Increment 2 it lists countries and languages. |
| "Testing requirements" | Thirteen requirements of the implementation | The same thirteen, each met in the increment that builds what it tests, as allocated above, and all met when Increment 3 is merged |
| Gate, items 6 to 9: "the implementing pull request is complete only when" | One pull request | Each increment's pull request, for what it builds (point 23) |

Unchanged, explicitly:

- **Every numbered point of ADR-0018**, 1 to 61, with the one test exception to point 2 and the one clarification of point 7 named above, including the layering, the four record types, the write matrix, immutability and succession, the audit record and its writer, public identifiers, and initial data.
- **Every other row and line of "Database and migrations"**, including that each table's trigger is written out in the migration that creates it and that no existing migration is edited.
- **The wording and number of the testing requirements**, and the owner decisions O1 to O5.
- **Gate items 1 to 5**, and "Not in this milestone".

## Alternatives considered

- **All four tables in the first migration, with services for Country and Language only**, as ADR-0018 words it. It needs no new ADR. Institution and InstitutionName would exist in every database with no service that writes them, and their constraints would be reviewed and applied one increment before the rules that exercise them are written. Whatever that later work showed to be wrong in them could not be corrected in place, because an applied migration is not edited.
- **The whole remaining registry in one pull request.** It is what ADR-0018's wording assumes. The change would be too large to review with the care that the hierarchy and succession rules need, and the simple half would wait for the hard half.
- **A dated amendment inside ADR-0018.** The ADR process allows one when the project owner decides it. It would put a delivery plan inside the decision it delivers and leave the index showing one ADR where two decisions were made. The owner chose a separate ADR.
- **Splitting further**: Country and Language apart, or Institution apart from InstitutionName. The first gains nothing, since the two are alike and small. The second is not possible (point 4).
- **Institutions first.** Institution and InstitutionName need Country and Language to refer to.
- **An entry page that declares `REGISTRY_REFERENCE_MANAGE` in Increment 2 and changes its declaration in Increment 3.** No account would see a page with nothing to do. A view's declared access would change between increments, point 59 would be untrue of the code for a time, and the access tests would be rewritten instead of extended.
- **An institution section on the pages in Increment 2, empty or marked as coming.** It shows the shape of the finished page. It is interface for something that does not exist, which the coding standards rule out, and a reader of the page cannot tell an empty registry from an unbuilt one.
- **Adding `REGISTRY_INSTITUTIONS_MANAGE` only in Increment 3.** The permission would arrive with its first operation. The entry page could not make its final declaration in Increment 2.
- **Leaving the forms of the Language codes to the Increment 2 pull request.** ADR-0018 point 7 would be implemented as it reads. A pattern that every later record depends on would be chosen in review of code and held in a migration that cannot then be edited, and the project owner has already decided it.
- **A selector in `accounts` that reads the audit record, for the registry tests to use.** No exception to the import contract would be needed. It is production code built for tests, and ADR-0018 leaves reading the audit record to a later increment with its own permission.
- **Registry tests that read the audit tables with SQL.** No import of `accounts.models` at all. The tests would be tied to table and column names, and would be harder to read than the rule they check.
- **Counting the Increment 2 tests of simultaneous use as ADR-0018's requirement 8.** It would give every increment a concurrency row. It would reinterpret a requirement of an Accepted ADR, and the cycle test could then be argued to be already covered.
- **Deferring every test that ADR-0018 words with an institution in it.** Simpler to allocate. Country and Language would be merged without tests of their own refusal of an empty change and of their lifecycle, and the first registry services that emit a registry audit event would be merged without a test under simultaneous use. The shared writer, `record_audit_event`, exists already and has its own tests.

## Consequences

- Each pull request is small enough to review against the points it implements, and the first registry services that emit a registry audit event, through the `record_audit_event` writer that already exists, are the simplest that will ever do so.
- Between the two increments the registry holds countries and languages and nothing else. That state is complete and tested, and it is not the registry of ADR-0018 until Increment 3 is merged.
- A Researcher, and a Reviewer verified with a trusted second factor, hold `REGISTRY_INSTITUTIONS_MANAGE` during that time and can do nothing with it but reach a page that tells them so.
- The pages change between increments, so two kinds of test written for Increment 2 are replaced in Increment 3 (point 22). This is the one place where an earlier increment's tests do not pass unchanged, and it is named in advance so that it is not mistaken for weakening a test.
- There are two `registry` migrations where ADR-0018 counted one. Reversing either destroys the records in its tables and leaves audit events that name them.
- The audit vocabulary names institution targets and fields before any code can write them. This was already true after Increment 1.
- The increments carry four supplementary tests that ADR-0018 does not list. They assert no new rule.
- Registry test modules may import AuditEvent and AuditEventChange from `accounts.models`, and registry runtime modules may import nothing from it. The import contract must tell the two kinds of module apart, and Increment 2 has to show that it does. That a test imports those two models and no other is kept by review.
- A Language is entered under one form of each code. A language or a script that has no code in those forms cannot be entered until the project owner approves another form.
- A reader of ADR-0018 must read this ADR to know that its migration table is not what was built, and to find the forms that its point 7 requires. The index says so beside ADR-0018.

## Open points

None. The one open point was the project owner's acceptance.

1. **Resolved on 2026-10-11.** The project owner reviewed the final text of this ADR and explicitly accepted it. The status and date say so, and the index, the specification's table, and `CLAUDE.md` list ADR-0019 as Accepted.

Nothing else was open. The forms of the Language codes are decided (points 29 to 32) and are not left to Increment 2. The import-linter configuration of point 28 is implementation, verified in Increment 2, and no decision waits on it.

## Revisit when

Increment 3 cannot be built on the Country and Language tables as Increment 2 created them; a requirement of ADR-0018 turns out to fit neither increment; a language or script must be entered whose code does not fit the forms of points 29 and 30; a further registry record type is proposed; or the project owner decides that a later ADR is delivered in phases, at which point the rules under "Judging an increment" may belong in the ADR process and not in this ADR.
