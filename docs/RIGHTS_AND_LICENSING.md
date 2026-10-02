# Rights and licensing

Status: Software license decided by the project owner on 2026-10-02. Sections 2 to 4 describe mechanisms that are decided and a policy that is **not yet decided** (blocker B7, remaining part).

This document keeps four things apart that are easily confused. Nothing here is legal advice, and it makes no statement about the legal status of any particular document or dataset.

| # | Subject | Covered by | State |
|---|---|---|---|
| 1 | CAIPO's original software | MIT License | Decided |
| 2 | Third-party sources and documents | Their own rights holders' terms, recorded per document version | Mechanism decided; policy open |
| 3 | Data: third-party datasets, and records created by the project | Providers' terms; a licence for project-created data | Third-party: per provider. Project-created: open |
| 4 | Display and redistribution | Recorded rights, enforced by the system | Mechanism decided; policy open |

## 1. Software license

CAIPO's original software is released under the **MIT License**. The text is in [LICENSE](../LICENSE).

"Original software" means the source code, configuration, tests, and project documentation written for CAIPO and held in this repository.

**The MIT License does not cover third-party material.** It grants no rights in, and makes no claim about:

- government and legal documents
- research papers and reports
- datasets and statistics from external providers
- logos, emblems, and trademarks
- copyrighted source files of any kind
- text extracted from any of the above, including segments, passages, and quotations, that is not owned by the project

Storing such material in a CAIPO installation, or processing it with CAIPO's software, does not place it under the MIT License. Third-party software that CAIPO depends on remains under its own licence.

Contributions to the software are accepted under the same MIT License (see [CONTRIBUTING.md](../CONTRIBUTING.md)).

## 2. Source and document rights

Every document held in CAIPO comes from a third party and remains subject to that party's rights and terms of use. CAIPO does not relicense it.

**Mechanism (decided).** Each document version has a recorded **rights determination** ([DATA_MODEL.md](DATA_MODEL.md) §3.3), made by a Reviewer, with a stated basis. It answers six separate questions:

| Right | Question |
|---|---|
| Store | May the project keep a copy? |
| Workspace display | May authenticated research users read the full text for research? |
| Public excerpt display | May short quoted passages be shown to anonymous visitors? |
| Public full display | May the full text or the original file be shown to or downloaded by anonymous visitors? |
| Redistribute | May the text be included in exports and published data snapshots? |
| Provider transmission | May the text be sent to an external AI provider? |

Rules:

- **Default deny.** With no determination, a version is available only to the Researcher who submitted it and to Reviewers, for the purpose of reviewing it. Every other use is refused.
- **Rights and authentication are independent.** A right does not grant access to someone who lacks the permission, and being signed in, in any role, does not grant a use the rights do not allow. Both checks must pass every time.
- A determination can be replaced by a later one. Earlier determinations remain on record.
- Where the law requires removal, content is removed through the recorded redaction procedure ([DATA_MODEL.md](DATA_MODEL.md) §7).

**Policy (not decided).** Which kinds of document receive which rights, on what basis, and who is competent to judge, has not been defined. Until it is, no rights determination can be made on a principled basis, and so no third-party text is displayed publicly, exported, or sent to an external provider.

## 3. Database and data rights

Two different things are stored as data.

**Third-party data.** Indicator observations and dataset files come from external providers and remain subject to each provider's terms. CAIPO records the provider, the release, and the terms noted for the source. The terms of each provider must be checked before its data is displayed publicly or redistributed (blocker B12). The MIT License does not apply to this data.

**Project-created data.** Research claims, evidence links, policy coding, search runs, analysis results, and descriptive metadata are created by the project. These are not software, and the MIT License on the code does not automatically license them. **Under what licence the project releases its own research data has not been decided.** Until it is, no reuse rights in that data are granted beyond what the law allows. This is part of the remaining B7.

Project-created records can quote or embed third-party material, for example a passage quoted as evidence. A licence on project-created data would not extend to the quoted material.

## 4. Display and redistribution policy

**Mechanism (decided).**

| Use | Requires |
|---|---|
| Show a quoted passage on the public site | Version is approved, and public excerpt display is allowed |
| Show full text or the original file on the public site | Version is approved, and public full display is allowed |
| Show full text in the research workspace | The user's role permits it, and workspace display is allowed |
| Show a quoted passage in an assistant answer | Workspace display is allowed; the assistant is available only to authenticated users |
| Send text to an external AI provider | Provider transmission is allowed |
| Include text in an export or data snapshot | Redistribute is allowed |
| Show a reference without text: title, institution, date, locator, hash | Always possible for an approved version |

Where a display right is missing, the reference is still shown, with its locator and without the text, so that the evidence chain stays visible.

Spreadsheet exports neutralise cell content that could execute as a formula ([SECURITY.md](../SECURITY.md)).

**Policy (not decided).** The following are open and belong to the remaining part of blocker B7:

1. The rights policy for documents: categories, default determinations, and the basis for each.
2. The licence for project-created research data and published snapshots.
3. Whether, and where, data snapshots are deposited publicly.
4. A procedure for handling a removal request from a rights holder.

## 5. What is closed and what is open

- **Closed:** the software license (MIT), and the separation of software, document, data, and display rights set out here.
- **Open (B7, remaining part):** the four policy items in section 4. They block Phase 2, because documents cannot be ingested for use without a rights policy.
- **Open (B12):** licence terms of each indicator data provider.
