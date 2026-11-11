# Interface text

Status: Style guide (Blueprint P-14), decided by the project owner on 2026-11-11 · Last updated: 2026-11-11

This guide says how CAIPO's pages and messages are worded. It applies to every template and every user-facing string in code.

- Rules marked **(tested)** are checked by `caipo/web/tests/test_interface_text.py`.
- The prohibited-wording list of the research protocol (B11) is a separate list, which the owner writes. When it exists it is added to that test; this guide does not stand in for it.

## 1. Voice

- Use plain English, short sentences, and the active voice. Say what happened or what to do.
- English only at launch. Every string is marked for translation (CLAUDE.md, rule 11). Refusal messages are tested by `test_translatable_refusals.py`.
- A button names its action as a verb phrase: "Grant the role", "Disable the account", "Send the message again". Not "Submit" or "OK".
- Under its heading, a page says in one sentence what it is for, and whether it changes anything ("This page changes nothing").

## 2. Cause and effect

- **No text states or implies that a policy, a technology, or anything else caused, drove, led to, or had an effect on an outcome.**
- Words of cause appear only in a sentence that denies them, such as "They do not show that any policy caused any change" **(tested)**. These words are: cause, effect, impact, led to, due to, thanks to, as a result, drove, driven by, boost, contributed to, attributable.
- Every comparison, chart, and export carries the standard non-causation notice: **"Not a causal analysis."** followed by its sentence, from `web/includes/non_causation.html`.
- A pattern, a coincidence in time, or a difference between countries is described as what was recorded, never as a finding about why.

## 3. Absence and missing data

- **An empty list is not evidence that something does not exist.** Say one of these:
  - "No X is recorded here";
  - "This has not been searched yet";
  - "No qualifying source was found as of DATE" (Blueprint §4.7).
- Words of non-existence ("does not exist", "no such X exists") appear only in a sentence that denies them, such as "It is not evidence that no such policy exists" **(tested)**.
- A missing value is shown as missing: "no value", or an empty cell, never zero and never filled in.
- "n of N years" states how much is held.

## 4. Statuses, conditions, and badges

- **Record states** use the labels of their model choices (`AccountStatus`, `AuditAction`, `PolicyEventType`, and so on), never a new word for the same state.
- **Conditions** use one wording each:

  | Condition | Wording |
  |---|---|
  | Empty | "No X is recorded here.", with what was asked |
  | Not yet searched | "This has not been searched yet." |
  | Denied | The error page's sentence; it never says whether a record exists |
  | Error | What failed, whether anything was changed, and what to do |

- **Badges:**
  - "Demo data": synthetic, ADR-0020;
  - "Reference": real public material;
  - "Provisional": a working assignment, not a research decision;
  - "verified" and "not verified": the terms of a source.

  A badge is never the only carrier of its meaning: the page also says it in words.

## 5. Numbers, dates, and names

- Values are shown rounded to two decimals at most, and the page says that they are stored exactly as published.
- Dates are ISO 8601: `2026-11-11`. Times are UTC and say so: "When (UTC)".
- A title is shown as written, with its English title beside it where one is recorded. A transliteration or translation never replaces the original.
- Synthetic records are named so that they cannot be mistaken for real ones: titles start with `DEMO` or `TEST`.

## 6. People and accounts

- Roles are named with a capital: Reader, Researcher, Reviewer, Administrator.
- A page addressed to its reader says "you". A record of what someone did names their account's email address, never a guess at their name.
- Where telling the causes of a refusal apart would reveal something, security messages give the same answer whatever the cause (SECURITY.md).
