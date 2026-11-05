## What and why

<!-- One change that does one thing. Say what it is for, and the owner decision or ADR it rests on. -->

- Day and packages (`docs/EXECUTION_TRACKER.md`):
- Built on another pull request: no <!-- or: yes, #N, which is merged first -->

## What changed

<!-- By layer or group of files. Say what was deliberately left out. -->

## Self-review

The author's recorded self-review (`CONTRIBUTING.md`, "Solo operation"). Tick only what holds; explain anything that does not.

In the order of the review checklist:

- [ ] No research integrity or security rule is broken. For a change to fetch, parse, authentication, rights, redaction, or the AI pipeline, the security checklist of `SECURITY.md` was worked through, and its result is written below.
- [ ] It is correct, and the tests prove it: new behaviour and its failure paths are tested, and a bug fix starts with a test that failed before it.
- [ ] It respects the architecture rules and uses the vocabulary of `docs/DATA_MODEL.md`.
- [ ] It is as simple as it can be: no dead code, no speculative option, nothing "for later".

Then:

- [ ] I read the full `git diff` against `main`, and nothing unrelated is in it, or each exception is named below.
- [ ] No check was loosened: no new `# type: ignore`, `# noqa`, `nosec`, import-linter exception, or skipped test without a written reason below.
- [ ] Migrations are reviewed: each is reversible or says why not, and is safe on existing data. Or there is none.
- [ ] Failures are explicit and never swallowed. Logs carry the correlation ID and no secret or document text.
- [ ] Interface text is marked for translation and states or implies no causal effect.
- [ ] Documentation and ADRs are updated, and the tracker records this Day.
- [ ] For an AI pipeline change: the evaluation results per language are below.

Found and not changed:

## Checks

Each command is run on its own and its own exit code is read, never through a pipe that can hide it. A check that could not be run is named with the reason, and is not described as passing.

| Check | Command | Result |
|---|---|---|
| Lock file | `uv lock --check` | |
| Lint | `uv run ruff check .` | |
| Format | `uv run ruff format --check .` | |
| Types | `uv run mypy .` | |
| Import layers | `uv run lint-imports` | |
| Migrations | `uv run python manage.py makemigrations --check --dry-run` | |
| Tests | `uv run pytest` | <!-- the summary line --> |

CI's pytest summary, read from the job log after the run:

## Owner decisions needed

<!-- None, or each decision with a recommended default and what it blocks. -->
