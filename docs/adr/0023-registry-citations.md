# ADR-0023: Where a registry name or date comes from

- Status: Accepted
- Date: 2026-11-11

## Context

ADR-0018 classes registry maintenance as stating no claim and citing no source. The diagnostic of 2026-10-20 (finding I3, M1) showed the cost: where an institution's name or its dates came from is recorded nowhere in the application. The sources of the names entered on 2026-10-23 exist only in the frozen diagnostic report.

The project owner asked on 2026-11-11 (Blueprint P-11) for the registry to record its sources before many institutions are entered, and accepted this decision the same day, before its implementation, which followed in execution Day 26.

The registry is in a layer below `sources` (ARCHITECTURE.md §2). It cannot point to a `sources.Source` or `sources.Document`, because foreign keys point only downward. An audit value is at most 200 characters (ADR-0018), shorter than many addresses.

## Decision

1. **A citation is a record of the registry.** `RegistryCitation` holds:
   - a public identifier;
   - the address of the page the fact was read on: `http` or `https` and no space, checked by the service and by a database check, as sources' addresses are;
   - the title of that page as written, at most 500 characters;
   - the day it was read, which is not in the future;
   - when it was recorded.

   Who recorded it is in the audit event of the change that first names it. It is append-only, and protected by a trigger that refuses every UPDATE and DELETE. A wrong citation is not corrected in place: a new one is recorded and pointed to.
2. **Each name names its citation.** `InstitutionName` gains a citation, which the services require for every new name. Names entered before this decision have none, and the pages say "No source recorded". Adding one is an audited change of that name. A name's citation, once set, never changes: the name's trigger refuses it. A later change of a name's dates keeps the name's citation, and the audit event records who changed them.
3. **An institution's dates name their citation.** `Institution` gains a citation for its valid-from and valid-to dates. The services require it whenever a date is entered, or changed while a date remains. It is cleared when both dates are cleared. A citation given with no date to cite is not used.
4. **The audit record names the citation by its identifier.** Two fields are added to `AuditField`: `citation` and `dates_citation`. Their values are the citation's public identifier, which fits the 200-character limit; the address and title are read from the citation.
5. **The pages.**
   - They ask for the address, title, and day with each new name, and with each entry or change of dates.
   - They show each name's and each institution's citation as a link that opens outside the application, with `rel="noopener noreferrer nofollow"`.
   - A name without a citation is marked "No source recorded" and offered a form that adds one.
6. **What a citation is not.** It is not a Source, a Document, or evidence (DATA_MODEL.md). Nothing is fetched or stored from the address: the registry records where a fact was read, not the page.

## Not decided here

- A preferred name among concurrent names of one kind (diagnostic §15.6). It is a separate question, for its own ADR if wanted.
- Sources for countries and languages, whose codes follow ISO 3166-1, ISO 639, and ISO 15924 and are checked by form.

## Alternatives considered

- **Free text on the name.** Simpler, but it can hold anything, cannot be checked, and is not audit-safe: the audit record holds no free text.
- **A `sources.Source` for every registry fact.** Not possible without reversing the layers, and it would make reference data look like evidence.
- **Recording sources only in a document outside the application.** It is how I3 arose.

## Consequences

- Migrations:
  - `registry` 0003 adds one table and two columns, and replaces the trigger function of InstitutionName;
  - `accounts` 0015 adds two audit field values.

  Existing rows are valid without a citation. Both migrations are reversible; reversing drops every citation.
- Entering a name or a date takes three more fields.
- DATA_MODEL.md §6 gains a rule for citations, tested in `caipo/registry/tests/test_citations.py`.

## Revisit when

The registry is opened to entries from outside the project, or a source has to be shared between the registry and the evidence base.
