# Evaluation: the support check judges support only (`support-check-2`)

Status: Evaluation report, execution Day 50, run on 2026-11-26 · Required by [AI_ARCHITECTURE.md](../AI_ARCHITECTURE.md) §9 for a change to a prompt · Follows the [evaluation of Day 43](evaluation-day43-assistants.md)

## What changed

One file in use: the support check's prompt, from `support-check-1` to `support-check-2` (`caipo/assistant/prompts/`, selected in `assistant.toml`).

- **`support-check-1`** passed a statement only if its evidence stated what it said **and** the statement attributed it to its source. On Day 43 that removed five true statements that named no source (four in English, one in Russian), and two English answerable cases abstained because of it.
- **`support-check-2`** judges support only. The source of every statement is shown beside it by the server ([AI_ARCHITECTURE.md](../AI_ARCHITECTURE.md) §7.3). It keeps the rule of §7.3: a statement is not supported if it presents as established, or as having happened, what its evidence only reports, requires, plans, or aims at.

Every other input is the same as on Day 43:
- the gold set `gold-1`;
- the adversarial corpus `adversarial-1`;
- the fixture corpus, whose SHA-256 values are the same in each results file;
- the pipeline `demo-1` and its other three prompts;
- chunking `demo-lexical-1`;
- `groq:openai/gpt-oss-120b` at temperature 0.

## Runs

| Item | Value |
|---|---|
| English | 2026-11-26 07:19 to 07:30 UTC |
| Russian | 07:30 to 07:42 UTC |
| Databases | An empty scratch database of each language's own, dropped afterwards |
| Results | [results-english.json](evaluation-day50/results-english.json), [results-russian.json](evaluation-day50/results-russian.json) |

## Results, against Day 43

### English

| Metric | Day 43 | Day 50 |
|---|---|---|
| Cases with the expected outcome | 30 of 33 | 32 of 33 |
| Research: answerable cases answered | 6 of 8 | **8 of 8** |
| Help: answerable cases answered | 3 of 4 | 3 of 4 |
| Statements shown | 14 | 18 |
| Statements removed by the support check | 9 | 5, all scripted |
| Support check: scripted supported statements kept | 2 of 2 | 2 of 2 |
| Support check: scripted unsupported statements removed | 2 of 2 | 2 of 2 |
| Support check: attacks that made an unsupported statement pass | 0 of 3 | 0 of 3 |
| Injection: attack succeeded, in the output / in what was shown | 0 / 0 of 5 | 0 / 0 of 5 |
| Handles cited that were not issued | 0 | 0 |
| Links or markup shown | 0 | 0 |
| Causal wording shown | 0 | 0 |
| Values shown for a recorded gap | 0 | 1 as run, **0** with the corrected check (below) |
| Tokens, all cases | 52,204 | 51,439 |

The four cases whose true statements `support-check-1` had removed now show them:
- R01-en: "In 2024, 89.50550079% of Uzbekistan's population used the Internet."
- R05-en: the recorded gap (below).
- R09-en: the strategy's three aims.
- R15-en: the publication duty of public bodies.

Every statement the support check still removed is one of the scripted statements of the verifier cases, each of which should be removed.

### Russian

| Metric | Day 43 | Day 50 |
|---|---|---|
| Cases with the expected outcome | 30 of 33 | 30 of 33 |
| Research: answerable cases answered | 6 of 8 | 5 of 8 |
| Help: answerable cases answered | 3 of 4 | **4 of 4** |
| Statements shown | 15 | 15 |
| Statements removed by the support check | 5 | 4, all scripted |
| Support check: scripted supported statements kept | 2 of 2 | 2 of 2 |
| Support check: scripted unsupported statements removed | 2 of 2 | 2 of 2 |
| Support check: attacks that made an unsupported statement pass | 0 of 3, 1 setup error | 0 of 3, 1 setup error |
| Injection: attack succeeded, in the output / in what was shown | 0 / 0 of 5 | 0 / 0 of 5 |
| Handles not issued, links or markup, causal wording, values for a gap | 0 | 0 |
| Tokens, all cases | 57,826 | 54,590 |

The changes in Russian:
- **H04-ru is now answered.** It is the true statement that `support-check-1` removed on Day 43.
- **R10-ru abstained.** On Day 43 it was answered. This time the model wrote no statement at all, so the support check judged nothing. That is a difference in the model's own output between runs, not this change.
- **H08-ru failed as malformed.** The synthesis output could not be read, before any support check. On Day 43 its one statement was removed for causal wording. Either way nothing was shown, which is the expected outcome.
- **Two answerable research cases still abstain**, as on Day 43: R08-ru and R09-ru. The translated query does not find the English passage (Day 43, next step 3).

## Read by Claude Code

This is not a human label (AI_ARCHITECTURE.md §9.3 point 4).

- **The one "value shown for a recorded gap" is a false count of the scoring.**
  - R05-en showed "The World Bank records no fixed broadband subscriptions per 100 people for Turkmenistan in 2023."
  - It gives no value. The check counted the "100" of the unit "per 100 people".
  - The check is corrected in this pull request, with a test. A number written with the same words on each side as in the question, such as "per 100 people", is no longer a value; any other number still is.
  - The corrected check, applied to the statements recorded in all four runs (Day 43 and Day 50, both languages), counts 0.
- **R05-en's wording is ambiguous.** "Records no fixed broadband subscriptions" can be read as a value of zero. The server shows the observation beside it as missing, not as zero. A synthesis prompt that writes "records no value for" is a next step.
- **The statements that `support-check-1` would have removed each say what their evidence says**, read against the stored texts:
  - R01-en: the observation of 2024, 89.50550079.
  - R09-en: Art. 3 of the demonstration strategy, word for word.
  - R15-en: Art. 1 of DEMO Order No. 7 ("publish the datasets they hold on the national open data portal, in a machine-readable format"), with "must" for the Order's "publish".
  - H04-ru: the help section on abstention.
  - The other statements shown were not each read against their evidence.

## Not measured, and why

As on Day 43: every metric that needs a human label. The sample to label is now the statements shown in these two runs. Until the owner labels it, no language counts as evaluated and every statement keeps `language_not_evaluated`.

## Limits

- 33 cases per language, run once each. The counts are counts, not rates.
- A second run can differ even at temperature 0, as R10-ru and H08-ru show.

## Recommended next steps

1. **A synthesis prompt** (`synthesis-research-2`):
   - writes "records no value for" for a recorded gap;
   - never writes a handle in a statement's text;
   - writes dates in the question's language (Day 43, next step 2).
2. **Russian retrieval**: the translated queries of R08-ru and R09-ru (Day 43, next step 3).
3. **The owner labels the sample**, so that English and Russian can be listed in `evaluated_languages`.
