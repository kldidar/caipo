# Spike: free-tier providers for the demonstrator's assistants

Status: Spike report, execution Day 35, 2026-11-15 · Decides the provider of [ADR-0025](../adr/0025-demonstrator-assistants.md) point 6

## Question

Which free-tier generation provider should the demonstrator's two assistants use? ADR-0025 point 10 asks for at least two providers to be compared on four things:
- output that matches the schema;
- answers in English and Russian;
- free limits;
- data terms.

## What was run

- **The models.** Four models, offered to the project's free keys on 2026-11-15:
  - Google: `gemini-3.8-flash` and `gemini-3.5-flash-lite`;
  - Groq: `openai/gpt-oss-120b` and `qwen/qwen3.8-27b`.
- **The cases.** Each model received the same twelve cases, six in English and six in Russian, once each, at temperature 0, with four seconds between calls. Each case had a system prompt in the form of [AI_ARCHITECTURE.md](../AI_ARCHITECTURE.md) §7.1 and the output schema of §7.2. The kinds:
  - questions on observations that are held;
  - questions on observations recorded as missing;
  - causally framed questions;
  - a synthetic document that tells the model to report a 500 percent growth and cite an unknown handle;
  - help questions;
  - an out-of-scope request.
- **The support check.** One call per model judged three statements:
  - one supported;
  - one that the injected document asserts;
  - one with a note in its evidence telling the checker to mark everything supported.
- **The evidence:**
  - six World Bank observations of `IT.NET.USER.ZS` for Uzbekistan and Turkmenistan, read from the development database (World Development Indicators, release last updated 2026-10-08), four held and two missing;
  - two synthetic DEMO texts;
  - two synthetic help sections.
- **The checks.** Each answer was checked by the rules the pipeline will apply:
  - schema;
  - handles issued in the request only;
  - a citation on every statement;
  - every number found in the cited evidence;
  - no undenied causal wording;
  - the answer in the question's language.

  Flagged answers were then read by hand.

The harness was a throwaway script, kept outside the repository as the C1 spike's code was. No key was printed or stored.

## Results

| Model | Answered | Schema valid | Unknown handles | Injection followed | Causal claim | Numbers not in evidence | Language of the question | Support check (3) | Median latency |
|---|---|---|---|---|---|---|---|---|---|
| `gemini-3.8-flash` | 0 of 12: HTTP 503 or time-out on every call | — | — | — | — | — | — | not answered (503) | — |
| `gemini-3.5-flash-lite` | 12 | 10 | 0 | 0 | 0 | 0 | 7 of 10 | 3 correct | 1.6 s |
| `openai/gpt-oss-120b` (Groq) | 12 | **12** | 0 | 0 | 0 | 1, a false removal (below) | 9 of 12 | 3 correct | 2.3 s |
| `qwen/qwen3.8-27b` (Groq) | 7 of 12: HTTP 429 on five | 7 | 0 | 0 | 0 | 0 | 6 of 7 | 3 correct | 0.9 s |

Read by hand:
- **Injection.** No model reported the 500 percent figure or cited handle H9. The automatic flag that suggested otherwise matched "500" inside the held value 89.5055**00**79, so it was a false alarm. It is fixed in the real check, which works on numeric tokens, not substrings.
- **Missing values.** No model invented a value for Turkmenistan.
  - `gemini-3.5-flash-lite` returned no statement and named the gap.
  - `gpt-oss-120b` stated, citing the observation, that the World Bank records the value as missing. That is a recorded observation of a missing status, not an invented number.
- **Schema.** Both failures of `gemini-3.5-flash-lite` returned `gaps` as a string instead of a list.
- **The one numeric failure** of `gpt-oss-120b` was a correct Russian statement. The numeric check removed it, which is the safe direction. The harness read the hyphen of "SHA-256" in the evidence as a minus sign, so it allowed −256 and not 256. A sign belongs to a number only when no letter comes before it: a case for the tokeniser's tests.
- **Language.** Both usable models sometimes answered a Russian question in English: `gemini-3.5-flash-lite` 3 times in 10, `gpt-oss-120b` 3 in 12. Russian needs a prompt change, measured in the evaluation (Day 42), and stays flagged `language_not_evaluated` until then.
- **Precision.** Both models copied the stored values with all eighteen decimal places. The evidence blocks will give each value as published, and the prompt will ask for one decimal place. The numeric check already accepts rounding of an observation value.

## Data terms, read on 2026-11-15

- **Groq.** [Your data](https://console.groq.com/docs/your-data):
  - "By default, Groq does not retain customer data for inference requests."
  - Logs kept for reliability or abuse are "retained for up to 30 days".
  - "All customers may enable Zero Data Retention (ZDR) in Data Controls settings."

  The page does not address training. Third-party summaries say Groq's Data Processing Addendum forbids it; that was not read here.
- **Google, unpaid services.** [Gemini API terms](https://aistudio.google.com/docs/terms):
  - "Google uses the content you submit to the Services and any generated responses" to improve its products;
  - "human reviewers may read, annotate, and process your API input and output";
  - "Do not submit sensitive, confidential, or personal information to the Unpaid Services."

## Decision

- **Provider and model:** Groq, `openai/gpt-oss-120b`, for synthesis, query analysis, and the support check. The identifier is held in a versioned file, as ADR-0006 requires.
- **Why this model:**
  - it is the only model with schema-valid output in all twelve cases;
  - it answered every call within the free limits;
  - its default retention is the shortest, and Zero Data Retention can be switched on.
- **Fallback:** `gemini-3.5-flash-lite`, behind the same interface. Changing to it is a reviewed change of the versioned file and an evaluation run, and its data terms must be stated to users.
- **For the owner:** switch on Zero Data Retention in the Groq console (Data Controls). No payment method is to be added to either account.

## Limits of this spike

- **Size.** Twelve cases, one run each, are a comparison, not an evaluation. The error rates above are counts, not estimates.
- **Not measured:** daily limits under real use, and stability over days. The quotas of ADR-0025 point 7 are set from the provider's published limits, read again when the quotas are written.
- **Possibly overload, not quality.** `gemini-3.8-flash` was unavailable throughout the run. That may be load on the free tier on that day, not a lasting property of the model.
