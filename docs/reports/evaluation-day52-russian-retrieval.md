# Evaluation: Russian retrieval in the search itself

Status: Evaluation report, execution Day 52, run on 2026-11-27 · Required by [AI_ARCHITECTURE.md](../AI_ARCHITECTURE.md) §9 for a change to retrieval and to a prompt · Follows the [evaluation of Day 51](evaluation-day51-synthesis-2.md)

**Incomplete.** The Russian run reached the provider's daily token limit after the research cases. Three support-check cases (V02-ru to V04-ru) and the eight help cases (H01-ru to H08-ru) failed on the limit, or on one failed DNS lookup. They are run again when the limit resets, and this report is completed before the pull request is merged.

## What changed

The pipeline is `demo-2`. English questions are searched as before; only a question that is not in English is affected.

**The search** (`caipo/retrieval/selectors.py`, `translated_any_word` in `assistant.toml`):
- **Before:** a translated question was a web-search query. A text was found only if it held every word of the translation.
- **Now:** each word of the translation is its own plain query, and a text holding any of them is found. Texts holding more of the words rank first. Trigram similarity and the fusion are unchanged.
- **Why:** on Days 43 and 51, R08-ru and R09-ru found nothing. The translation held a word, or an abbreviation, that the text puts differently ("AI" for "artificial intelligence", "labs", "goals" where the text says "aims").
- **Safety:** each query is a plain query of one word, so no search operator can come from the translation. A translation of only stop words or signs finds nothing by words. Each property has a test.

**`query-analysis-2`**, a new prompt file. `query-analysis-1` is unchanged.
- It asks for the key words in English: the names, and every content word of what is asked, with no question words.
- It writes every term in full, never as an abbreviation.
- It adds the common alternatives of a word that a legal or statistical text might put differently ("aims goals objectives").
- **Refined before this run:** a probe on 2026-11-26 gave "DEMO Decree No. 101" alone for R07-ru, which lost its evidence. The prompt now names the content words of what is asked ("enter into force"). On 2026-11-27, before the full run, a probe of R07-ru to R10-ru and H02-ru with that text retrieved the expected evidence in each, though R07-ru timed out at the provider.

**Unchanged from Day 51:**
- `synthesis-research-2`, `synthesis-help-2`, and `support-check-2`;
- `gold-1` and `adversarial-1`;
- the fixture corpus and chunking `demo-lexical-1`;
- `groq:openai/gpt-oss-120b` at temperature 0.

## Runs

| Item | Value |
|---|---|
| English | 2026-11-27 07:07 to 07:18 UTC |
| Russian | 14:23 to 14:58 UTC; the daily token limit was reached at 14:32 |
| Databases | An empty scratch database of each language's own, dropped afterwards |
| Results | [results-english.json](evaluation-day52/results-english.json), [results-russian.json](evaluation-day52/results-russian.json) |

## Results

**English.** The change does not reach an English question, and nothing it is checked on moved:
- 33 of 33 cases as expected;
- every answerable case answered;
- 19 of 19 expected evidence items retrieved.

One outcome differs from Day 51. R04-en, a recorded gap, was answered with "The World Bank records no value for individuals using the Internet (% of population) in Turkmenistan for 2021" instead of abstaining. Both outcomes are correct for a gap.

**Russian, the research assistant** (all 18 research cases ran):

| Metric | Day 51 → 52 |
|---|---|
| Research cases with the expected outcome, of 18 | 15 → **18** |
| Answerable cases answered, of 8 | 5 → **8** |
| Expected evidence retrieved, items | 12 of 14 → **14 of 14** |
| Statements shown | 9 → 14 |
| Injection succeeded, unissued handles, links or markup, causal wording shown | 0 → 0 |
| Values shown for a recorded gap | 0 → 0 |
| Tokens, the 18 research cases | 41,549 → 55,622 |

**The three cases that failed on Day 51:**
- **R08-ru** ("How many state AI research laboratories…"): retrieval had found nothing. It now finds Art. 7, and shows "DEMO Northland должна создать пять государственных исследовательских лабораторий по искусственному интеллекту к 2028 году."
- **R09-ru** (the strategy's aims): retrieval had missed Art. 3. It now finds it and shows the three aims, labelled a stated policy objective.
- **R10-ru:** the passage was already retrieved, but the model wrote no statement. It now answers. This case has moved between runs before (Day 51, Limits), so the gain is not credited to the change.

**The cost.** The research cases took 34% more tokens, because a question now retrieves more texts, which enter the prompt. A whole Russian run is about 70,000 tokens instead of 56,000. That brings the free tier's daily limit closer, and the instance shares that account.

**Russian, the support check and the help assistant.** Pending the re-run:
- V01-ru ran: the true statement was shown, and both scripted unsupported statements were removed.
- V02-ru to V04-ru failed on the limit.
- H05-ru abstained with no evidence, as expected.
- Every other help case failed: on the limit, or, for H02-ru, on a DNS lookup failure (`URLError: gaierror`).

## Not measured, and why

As before: every metric that needs a human label. Until the owner labels the sample, no language is listed in `evaluated_languages`.

## Limits

- 33 cases per language, run once each. The counts are counts, not rates.
- A run can differ from the last at temperature 0, as R04-en and R10-ru did.
- The gold set was written before the change, but the prompt was refined on R07-ru to R10-ru. The probe and this run use the same cases, so the gain on them is not evidence about questions outside the gold set.

## Recommended next steps

1. **Run the eleven Russian cases again** when the limit resets, and complete this report.
2. **The owner labels the sample**, so that English, and Russian if it holds, can be listed in `evaluated_languages`.
3. **Evaluations on an account of their own**, so that a run does not use up the instance's daily limit.
