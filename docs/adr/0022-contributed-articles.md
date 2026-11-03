# ADR-0022: Contributed articles, published after review

- Status: Accepted
- Date: 2026-11-03

## Context

On 2026-11-03 the project owner decided that people who use CAIPO can contribute: "to add, for example, a new article, they send a request with the finished article; we read it and say whether it can be published". Registration for the Reader role ([ADR-0021](0021-registration-for-the-reader-role.md)) is the first half of that decision; this ADR is the second.

The owner chose articles that the person writes themselves, over proposals of sources, and chose the licence a contributed text is published under: the author keeps the copyright and publishes under **Creative Commons Attribution 4.0 International (CC BY 4.0)** (Q-15 of the execution tracker). The owner also approved the change of CLAUDE.md that this ADR needs, because its "Current phase" allowed no application code beyond Phase 1 except the demonstrator of ADR-0020.

The owner gave these decisions on 2026-11-03 and accepts this ADR by merging the pull request that adds it.

CAIPO's value is trust: every statement traceable, evidence typed, nothing causal claimed. A contributed article is none of that. It is a person's view, and it may say things the research protocol would never let CAIPO say. The design keeps it visibly apart.

## Decision

1. **What an article is.** A text that a signed-in account wrote and sent for review: the name the author chooses to be credited with, a title, a summary, and the text. It is its author's view. It is **not a source, not evidence, not a claim, and not a finding of CAIPO**, it is counted in no result, and nothing in the research records points to it.
2. **A new app, `articles`, beside `research`.** It imports `accounts` only through its services and selectors, and nothing of the registry, sources, policies, or indicators; the research records import nothing of it. An import contract checks both. It changes no gate and closes no blocker.
3. **Who does what.** Two permissions. `articles.submit` (write an article and send it): Reader, Researcher, and Reviewer. `articles.review` (publish, decline, withdraw): Reviewer and Administrator, both only with a verified second factor. An Administrator reviews articles although it has no say over the evidence base, because publishing an article decides what is shown, not what is true. Nobody decides about their own article.
4. **The licence is accepted when the article is sent.** The form says that the author wrote the text and publishes it under CC BY 4.0 if it is accepted; without that, nothing is sent. The licence is stored with the article, and every published article shows the author's chosen name, the licence, and a link to it. The author's account email address is never shown.
5. **Review.** An article awaits review until a reviewer **publishes** it or **declines** it with a reason that its author is shown. A published article can later be **withdrawn**, with a reason. Nothing follows a decline or a withdrawal: the author sends a new article. Whether an article awaits review, is published, was declined, or was withdrawn is derived from its decisions and never stored.
6. **Append-only.** An article is never changed after it is sent; a correction is a new article. Decisions are never changed or deleted. Both are held by database triggers. The database also holds that an article has at most one verdict and at most one withdrawal, and that a decline or a withdrawal gives a reason. Decisions about one article are made one at a time under its row lock.
7. **Who sees what.** A published article is shown to every account that may read the workspace. One that is not published is shown only to its author, and to reviewers on their own pages; for anybody else it does not exist. The reason for a decline or a withdrawal is shown only to them. Anonymous visitors see no article until the public research site is built.
8. **Labelled on every page.** Each article page and the list say that the article is its author's own text and view, not a source, not evidence, and not a finding of CAIPO, and that publication means a reviewer found it fit to show, not that its statements were checked.
9. **Text is data.** The text is stored as written, apart from surrounding space and Unicode normalisation, with limits on each part: 120, 200, 600, and 20,000 characters. A direction-control character is refused. It is rendered escaped, with its paragraphs, and never as HTML, Markdown, or a link. It is never sent to an AI provider.
10. **Limits.** At most five articles a day from one account (`ARTICLE_SUBMISSION_LIMIT`, `ARTICLE_SUBMISSION_WINDOW`), counted under a lock for the author.
11. **Records.** Sending and each decision write an audit event (`articles.article`, `articles.article_decision`), as for the demonstrator's records.

## Alternatives considered

- **Proposals of sources instead of articles.** They would feed the evidence base after a check, with no licence question. The owner chose articles.
- **CC BY-NC 4.0, or a licence to CAIPO to display only.** Both were offered; the owner chose CC BY 4.0, the common licence for open research writing.
- **Articles as research claims.** They would need an epistemic type, evidence, and the protocol's review, which a free text does not have. Keeping them apart is what lets CAIPO show them at all.
- **Editing an article after it is sent.** It would make the reviewed text and the shown text differ. A new article is sent instead.
- **Markdown or rich text.** It adds a parser and a way to inject links and markup. Plain text with paragraphs is enough.
- **Showing articles to anonymous visitors now.** The public research site is not built (ADR-0007, ADR-0008).

## Consequences

- CAIPO now stores and shows text written by people it does not know, under their chosen names. A reviewer is the only check on what it says, and the label says so.
- An article can make a causal or political claim. The label, the separation from the research records, and the review are the controls; the research protocol's rules do not apply to an author's view, and CAIPO does not endorse it.
- A reviewer who wrote an article needs another reviewer to decide about it. With one person operating the project, the owner's own articles cannot be published unless a second reviewer exists.
- Personal data: the author's chosen name is published; their email address is not. Retention of articles and decisions is undecided, as for accounts (ADR-0021).
- A rights holder's removal request is handled by withdrawing the article; the stored text stays, as for every append-only record. A procedure for removal requests is still open (B7).
- The text is the author's own work under CC BY 4.0; CAIPO's own research data licence remains undecided (B7) and is not affected.

## Revisit when

The public research site is built; a removal procedure is decided (B7); articles need comments, revisions, or co-authors; abuse is seen; or the research data licence is decided.
