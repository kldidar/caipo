# `.claude/` — planned structure

This directory is intentionally almost empty. Automation is added only when a need has occurred repeatedly and the automation's purpose can be stated in one sentence.

## Planned layout

```
.claude/
  README.md            this file
  settings.json        shared permissions and hooks (not yet created)
  agents/              subagent definitions (none yet)
  skills/              project skills (none yet)
  hooks/               hook scripts referenced by settings.json (none yet)
```

`settings.local.json` is personal and git-ignored.

## Admission rule

An agent, skill, or hook may be added when all of these hold:

1. The need has come up at least three times, or a failure it would have prevented has actually happened.
2. Its purpose fits in one sentence.
3. It does not duplicate a CI check. CI is the enforcement point; hooks are early feedback only.
4. It is fast and deterministic. A hook that takes more than a few seconds or fails intermittently is removed.

## Candidates

These are candidates, not commitments. Each becomes real only when its trigger is met.

### Hooks

| Candidate | Purpose | Create when |
|---|---|---|
| Format on edit | Run `ruff format` and `ruff check --fix` on edited Python files | Tooling exists in `pyproject.toml` |
| Secret-file guard | Block reads and edits of `.env*` and key files | `.env` files first exist |
| Migration guard | Block edits to migration files that are already on `main` | First migration is merged |

### Skills

| Candidate | Purpose | Create when |
|---|---|---|
| `verify` | Run the full Definition of Done check sequence and report results | The check commands are stable |
| `new-adr` | Create a correctly numbered ADR from the template | ADR creation has been done by hand a few times |
| `run-evals` | Run the AI evaluation suite and summarise changes against baseline | The evaluation harness exists |

### Agents

| Candidate | Purpose | Create when |
|---|---|---|
| `security-reviewer` | Review a diff against `SECURITY.md` and ADR-0009 for ingestion and AI-path changes | Ingestion code exists |
| `research-integrity-reviewer` | Review a diff for violations of the epistemic taxonomy and fabricated data in fixtures or copy | Claim and evidence code exists |
| `migration-reviewer` | Review migrations for reversibility, locking, and data safety | Production data exists |

Reviewer agents are read-only. They report findings; they do not edit.
