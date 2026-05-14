# Crawler Reliability, Robustness, And Transparency

## Objective

Complete the crawler reliability roadmap in `docs/crawler-reliability-robustness-transparency-plan.md` with durable ownership boundaries, typed contracts, TDD, Pyright-strict validation, and no quick workarounds.

## Goal Kind

`open_ended`

## Current Tranche

Finish the terminal ownership tranche first: all crawler terminal `CrawlRuns` and `Jobs` row writes should go through the canonical `TerminalEvent` plus `commit_terminal(...)` seam, and private `TaskManager` escape paths must stay removed. Then audit the tranche before moving to lifecycle, worker adapter, admin visibility, and frontend polish.

## Non-Negotiable Constraints

- Prefer long-term reliability and clean architecture over minimum diff.
- Use TDD vertical slices: one behavior test, minimal implementation, refactor, verify.
- Keep terminal row commits separate from post-commit reactors such as audit, circuit breaker, website timestamps, and slot release.
- Use Scrapy and ARQ built-ins where they fit; do not reimplement queue/crawler capabilities without evidence.
- Preserve unrelated dirty files, especially `.devcontainer/*`.
- Do not use broad `Any`, type ignores, private-field mutation, or raw string status parsing for new write paths.
- Keep generated/frontend API contract changes separate from backend domain ownership work when possible.

## Stop Rule

Stop when the active tranche audit passes, all safe local work is blocked, verification fails twice for the same reason, or continuing requires owner input, credentials, destructive operations, or a broader product decision.

Do not stop after planning if a safe implementation task remains active and verified.

## Canonical Board

Machine truth lives at:

`docs/goals/crawler-reliability-robustness-transparency/state.yaml`

If this charter and `state.yaml` disagree, `state.yaml` wins for task status, active task, receipts, verification freshness, and completion truth.

## Run Command

```text
/goal Follow docs/goals/crawler-reliability-robustness-transparency/goal.md through the active verified implementation slice. Do not stop after planning unless blocked.
```

## PM Loop

On every `/goal` continuation:

1. Read this charter.
2. Read `state.yaml`.
3. Work only on the active board task.
4. Write a compact task receipt.
5. Update the board.
6. Activate the next safe task if it has allowed files, verification commands, and stop conditions.
7. Finish only with a PM audit receipt that maps receipts and verification back to the original user outcome.
