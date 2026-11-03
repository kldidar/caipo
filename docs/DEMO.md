# Demonstrating CAIPO

Status: Demonstration guide for the delivery sprint ([ADR-0020](adr/0020-demonstrator-track.md)) · Last updated: 2026-11-02

A walk-through of 5 to 10 minutes for a professor or a reviewer, and an honest account of what is real, what is simulated, and what is future work.

## Before the demonstration

1. Set up the development environment once ([DEVELOPMENT.md](DEVELOPMENT.md), "First-time setup").
2. Start from an empty database, so that what is shown is exactly what the repository creates:

   ```sh
   docker compose up -d --wait
   uv run --env-file .env python manage.py migrate
   uv run --env-file .env python manage.py seed_demo --password "<choose one>"
   uv run --env-file .env python manage.py runserver
   ```

   Verified on 2026-11-02 on an empty database: `check`, `migrate`, and `seed_demo` together took under 3 seconds, and `/health/ready/` answered `ok`.
3. Open two browser windows: one signed in as `demo.reader@caipo.test`, one as `demo.researcher@caipo.test`. Keep a third, signed out, on `http://127.0.0.1:8000/`.

## The walk-through

| Minute | Show | Say |
|---|---|---|
| 0:00 | The public home page, signed out | CAIPO is a research platform for comparing AI policy and economic transformation in Turkmenistan and Uzbekistan. Its value is trust: every statement traceable, gaps visible, results reproducible. Anonymous visitors see no records. Anyone can create an account here: it reads the workspace and adds nothing, and only after its email address is verified. |
| 0:45 | Sign in as the Reader → **Overview** | The workspace at a glance. Core AI policies and contextual entries are counted separately. Layer C has no indicator for either study country, and the page says so rather than hiding it. |
| 1:30 | **Policies**, core tab, filter *Data class: Reference data* → *Strategy for the Development of Artificial Intelligence Technologies until 2030* | A real record, by metadata only: resolution RP-358 of 14.10.2024 from lex.uz, with its address and access date. Its status, *In force*, is derived from two formal events; the database has no status column. The assignment to the core corpus is provisional and gives its reason. No text of the law is held, because its rights are not decided. |
| 2:30 | **Contextual policy registry** tab → Turkmenistan's digital-economy programme | Broader material is kept apart and never counted as AI policy. Here the signing date is not recorded, because the source does not give it, so the status is honestly *No formal event recorded*. |
| 3:15 | Core tab, filter *Demonstration data* → *DEMO National Strategy for Artificial Intelligence* | The same software on synthetic data, so that every feature can be seen: AI-related provisions with their locators and quoted text. The violet label and the notice mark synthetic records on every page; the database refuses to attach them to a real country. |
| 4:15 | **Indicators** → layer B | Real World Bank values. The lines break where Turkmenistan has no value: internet use was last reported for 2016, and ICT service exports never are. The legend says how many years hold a value. Open *Show the values* for the table. The notice: these views do not show that any policy caused anything. |
| 5:00 | Layer C | No indicator recorded. The layer is reported, not dropped, and the wording is bounded: it says nothing exists *here*, not that nothing exists. |
| 5:30 | **Analysis** → *Structural change in Turkmenistan and Uzbekistan, 2010–2024* → **Check reproducibility** | A recorded, descriptive run: every input value with the release it came from, and SHA-256 fingerprints of inputs and result. Running it again on the data held now gives *Reproduced exactly*. A missing first or last value is never filled in; the row says why the change was not computed. |
| 6:30 | **Export CSV**, open it | The export carries its provenance as notes: data class, method and version, fingerprints, the release hash, and the non-causation notice. Cells are protected against spreadsheet formula injection. |
| 7:00 | **Searches** → *Formally adopted AI-focused instrument of Turkmenistan* | How absence is recorded: a search with its queries, scope, criteria, the sources examined, and a bounded outcome, *No qualifying source found*. It is not evidence that no such instrument exists. |
| 7:45 | Researcher window → **Policies → Add a policy**: choose *Demonstration data* and *Turkmenistan* | The service refuses: demonstration records belong only to synthetic countries. Change the country to *DEMO Northland*: the policy is created, with its audit event. |
| 8:30 | **Analysis → Run an analysis**, demonstration data, layer C indicators | A new run, recorded with its fingerprints. |
| 9:00 | Phone width, or dark mode | The design system: responsive, light and dark, fonts that cover Turkmen, Uzbek, and Russian. |
| 9:30 | Close with what is not there yet (below) | The research decisions are open, and the software keeps them visibly open. |

Questions it is worth being ready for:

- *How do you know a value was not altered?* Each release is identified by the SHA-256 of the files obtained, the files are checked against their manifest before being read, and observations are append-only at the database.
- *Why so few real policies?* The reference records come from a bounded search, recorded as search runs. Building the full corpus is research work behind the gates (B9, B22).
- *Can it compare policy dates with indicator changes?* It could compute it, and deliberately does not yet: the protocol allows such a comparison only as a correlation with a recorded design, which is not settled.
- *What about the AI assistant?* Designed in [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md) and not built; it waits for provider, retrieval, and evaluation decisions (B14 to B16, B19, B24).

## What is real, what is simulated, what is future

### Real and working

- Accounts with four roles and permission checks on every page and every write; sign-in with throttling; TOTP two-step verification required for Reviewers and Administrators; provisioning, registration on the site for the Reader role ([ADR-0021](adr/0021-registration-for-the-reader-role.md)), email verification, password reset, and recovery of a lost second factor ([SECURITY.md](../SECURITY.md)). In development no email is sent: each message, with its link, is written to `data/outbox/`.
- The registry, and the general audit record of every change.
- Sources, documents (metadata), policies with formal events and AI-related provisions, indicators, dataset releases, observations, analysis runs, search runs, and their pages, forms, and exports ([DATA_MODEL.md](DATA_MODEL.md) §7a).
- Integrity enforced by PostgreSQL: data-class checks, append-only and delete-refusing triggers, the missing-value rule, the no-reference-text rule.
- About 4,800 automated tests, including end-to-end journeys on the seeded environment; strict type checking; import-layer contracts; CI on every pull request.

### Real data, used within its limits

- Metadata of Uzbekistan's resolution RP-358 of 14.10.2024 (lex.uz), and of Turkmenistan's resolution approving the digital-economy programme for 2026–2028 (a government news report of 2 February 2026).
- Eight World Bank indicators for Turkmenistan and Uzbekistan, 2010–2024, release of 2026-10-08, under CC BY 4.0.
- Two search runs that record the bounded searches behind these records.
- Limits: the set is a sample from a bounded search, not a verified seed list; core or contextual assignments and layer assignments are provisional working assignments; the original providers behind the World Bank's data (ITU, ILO, IMF, national offices) were not checked separately.

### Simulated

- Everything marked **Demo data**: the countries DEMO Northland and DEMO Southland, their sources, documents, policies, provisions, indicators, observations, one search run, and one analysis run. They exist to show the software and say nothing about any real country.
- The two demonstration accounts, created by a development-only command that refuses to run unless `DEBUG` is on.

### Future work

- **Research decisions** that the gates wait for: the policy domain and its eligibility rules (B22), the study period (B8), the seed source list (B9), the indicator selection (B12), the codebook (B11), the rights policy (B7), the ethics review (B20).
- **Document ingestion**: guarded fetching, isolated parsing, extraction into segments, and passages as exact evidence (Phase 2; B4, B10, B21).
- **Research claims** with typed evidence and review (Phase 4; B13).
- **Retrieval and the AI assistant**, with verified citations and an evaluation baseline (Phase 5).
- **The public research site**, and **deployment** with backups and monitoring (Phase 6; B17, ADR-0008).

The full list, with every blocker and its status, is in [PROJECT_SPECIFICATION.md](PROJECT_SPECIFICATION.md) §10 and [EXECUTION_TRACKER.md](EXECUTION_TRACKER.md).
