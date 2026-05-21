# Flow AI Builder Production Readiness 9/10

## Objective

Continue Flow AI Builder production-readiness hardening until the subsystem reaches a defensible 9/10 minimum score across architecture, runtime reliability, data model/schema quality, API contracts, test coverage, output quality, human readability, and human reviewability, or until a real blocker prevents further safe progress.

## Goal Kind

`open_ended`

## Current Tranche

Reconcile the dirty repo state, re-rank the next highest-ROI architecture/runtime/data/API/test slice from current evidence, pass the same implementation-ready plan through Codex, Claude, and Antigravity, implement the approved slice, verify it, run relevant live evals when available, update the scorecard, and continue to the next tranche unless a real blocker stops safe progress.

The current proposed tranche is **planning-state CAS coherence for plan proposals**: no active-turn planning-state write should use last-writer-wins unless it is explicitly named and justified.

## Non-Negotiable Constraints

- Preserve the uncommitted previous tranche as current working state.
- Preserve unrelated dirty files: `.devcontainer/docker-compose.yml`, `.devcontainer/devcontainer-lock.json`, `.gitignore`, `AGENTS.md`, `PRODUCT.md`, and `utvecklingssamtal.mp3`.
- Do not commit, stage, push, reset, clean, or revert without an explicit user request.
- Do not implement until the same revised plan passes Codex self-review, Claude, and Antigravity, or Antigravity failure is explicitly recorded as missing review coverage.
- Keep raw live-eval responses and API keys out of repo files. Summaries may be recorded without secrets.
- Prefer existing canonical owners over new files. Do not create generic `utils`, `helpers`, `manager`, `processor`, `shared`, or fake interface modules.
- Do not mark the broader goal done because one tranche passes. The broader goal is done only when the strict minimum score is at least 9/10, or a real blocker is documented.

## Stop Rule

Stop only when the tranche audit passes and the next safe tranche requires a new architecture decision, broader write scope than approved, destructive operation, unresolved peer disagreement, unavailable required credentials/service, or owner input. Otherwise update the board and continue.

## Canonical Board

Machine truth lives at:

`docs/goals/flow-ai-builder-production-readiness-9-10/state.yaml`

If this charter and `state.yaml` disagree, `state.yaml` wins for task status, active task, receipts, verification freshness, and completion truth.

## Run Command

```text
/goal Follow docs/goals/flow-ai-builder-production-readiness-9-10/goal.md. Keep executing verified tranches until the strict minimum score reaches 9/10 or a real blocker prevents safe progress. Do not stop after planning unless blocked.
```

## PM Loop

On every continuation:

1. Read this charter.
2. Read `state.yaml`.
3. Re-check `git status --short --branch` before any write.
4. Work only on the active board task.
5. Pass non-trivial plans through Claude and Antigravity as required.
6. Write a compact task receipt.
7. Update the board and scorecard.
8. Activate the next safe Worker task when peer gates pass.
9. Finish only with a Judge/PM audit receipt that maps verification back to the broader 9/10 objective.
