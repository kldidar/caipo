# Evaluation: the synthesis prompts, version 2

Status: Evaluation report, execution Day 51, run on 2026-11-26 · Required by [AI_ARCHITECTURE.md](../AI_ARCHITECTURE.md) §9 for a change to a prompt · Follows the [evaluation of Day 50](evaluation-day50-support-check-2.md)

## What changed

Two prompt files in use, each a new file. The files of version 1 are unchanged.

**`synthesis-research-2`** (Day 43 next step 2, and Day 50 next step 1):
- For a recorded gap, it writes that the source "records no value", never that the quantity was zero or that there was none.
- It writes handles only in the citations, never in a statement's text.
- It writes dates and the names of months in the question's language.

**`synthesis-help-2`**:
- It writes no handle in a statement's text.
- It shows the form of a quotation, an object with its handle and text. On Day 43, H03-en failed twice because the model gave quotations as plain strings.

Everything else is as on Day 50:
- `query-analysis-1` and `support-check-2`;
- `gold-1` and `adversarial-1`;
- the fixture corpus, the pipeline `demo-1`, and chunking `demo-lexical-1`;
- `groq:openai/gpt-oss-120b` at temperature 0.

**Tried and not kept: `query-analysis-2`.**
- **What it did:** it asked for the key words of a Russian question in English, with common alternatives joined by "or".
- **Why:** the search finds a text only if the text holds every word of the query.
- **The trial:** on five Russian cases, the model gave "goals" without "aims" for R09-ru. For R07-ru it gave "effective" for "enters into force", so R07-ru found nothing.
- **Conclusion:** Russian retrieval needs a change to the search itself, not to the prompt (next steps). The trial's results are not part of this report.

## Runs

| Item | Value |
|---|---|
| English | 2026-11-26 14:50 to 15:01 UTC |
| Russian | 15:01 to 15:13 UTC |
| Databases | An empty scratch database of each language's own, dropped afterwards |
| Results | [results-english.json](evaluation-day51/results-english.json), [results-russian.json](evaluation-day51/results-russian.json) |

## Results

| Metric | English, Day 43 → 50 → 51 | Russian, Day 43 → 50 → 51 |
|---|---|---|
| Cases with the expected outcome, of 33 | 30 → 32 → **33** | 30 → 30 → 30 |
| Research: answerable cases answered, of 8 | 6 → 8 → **8** | 6 → 5 → 5 |
| Help: answerable cases answered, of 4 | 3 → 3 → **4** | 3 → 4 → **4** |
| Cases failed | 1 → 1 → **0** | 0 → 1 → **0** |
| Statements shown | 14 → 18 → 19 | 15 → 15 → 15 |
| True statements removed by the support check | 4 → 0 → 0 | 1 → 0 → 0 |
| Scripted unsupported statements and attacks passed | 0 → 0 → 0 | 0 → 0 → 0 |
| Injection succeeded, unissued handles, links or markup, causal wording shown | 0 | 0 |
| Values shown for a recorded gap | 0 → 0 → 0 (with the check corrected on Day 50) | 0 |
| Tokens, all cases | 52,204 → 51,439 → 54,036 | 57,826 → 54,590 → 56,399 |

**The flaws of form that version 2 was written for**, in what was shown:

| Flaw | Day 43 | Day 51 |
|---|---|---|
| A handle in a statement's text | R10-ru ("Согласно П1, …") | none |
| A date in English in a Russian answer | R07-ru ("1 April 2025") | none: "1 апреля 2025 года" |
| A gap worded as a quantity ("records no … subscriptions") | R05-en, on Day 50 | none: "records no value for fixed broadband subscriptions per 100 people in Turkmenistan in 2023" |
| Quotations in the wrong form | H03-en failed | H03-en answered |

**The three Russian cases that did not give the expected outcome:**
- **R08-ru:** retrieval found nothing (no_evidence).
- **R09-ru:** retrieval missed Art. 3, which states the aims (nothing_verified).
- **R10-ru:** the expected passage was retrieved, but the model wrote no statement. It did the same on Day 50, though it answered on Day 43 and in the trial above.

R08-ru and R09-ru are the retrieval problem of Day 43, next step 3.

## Not measured, and why

As before: every metric that needs a human label. The sample to label is now the statements shown in these two runs.

## Limits

- 33 cases per language, run once each. The counts are counts, not rates.
- A run can differ from the last at temperature 0: R10-ru is answered in some runs and not in others.

## Recommended next steps

1. **Russian retrieval in the search itself.** A translated question should find a text that holds most of its words, not only one that holds all of them. This changes a retrieval setting, and is evaluated in both languages.
2. **The owner labels the sample**, so that English, and Russian if it improves, can be listed in `evaluated_languages`.
