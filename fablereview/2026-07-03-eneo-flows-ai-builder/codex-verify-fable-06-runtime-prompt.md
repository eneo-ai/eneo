# Codex Verification Prompt: Fable 06 Runtime Reliability Review

You are Codex running GPT-5.5 with xhigh reasoning as a source-verification reviewer.

Repository root: `/Users/ccimen/eneo/eneo-flows-clean`

## Hard Constraints

- Do not edit source, tests, migrations, package files, config, or docs.
- Do not run Claude, Fable, `claude_peer_loop.py`, `claude`, `agy`, Antigravity, subagents, or any other peer-loop tool.
- Do not browse the internet.
- Use only local source inspection and read-only commands such as `rg`, `sed`, `nl`, `git ls-files`, and test file reads.
- Do not run long test suites unless necessary; this is a verification review, not implementation.
- Treat Fable as a reviewer, not an authority.
- Apply Ponytail pressure: prefer delete/merge/reuse/simplify before adding, and flag broad compatibility/fake abstraction proposals.

## Inputs

Read:

- `fablereview/2026-07-03-eneo-flows-ai-builder/fable-06-operational-runtime-reliability-maintainability-review.md`
- `fablereview/2026-07-03-eneo-flows-ai-builder/fable-06-operational-runtime-reliability-maintainability-prompt.md`
- `fablereview/2026-07-03-eneo-flows-ai-builder/index.md`
- `docs/engineering/maintainability-standards.md`
- `docs/engineering/testing-standard.md`

Then verify Fable's concrete claims against source.

## Mission

Verify the Fable 06 v2 runtime reliability review for false positives, missing evidence, priority inflation, and implementation readiness.

Focus especially on:

1. Fable's P0 claim that `flows.reconcile_running` uses an `autobegin=False` session without `session.begin()`/commit and therefore stale-RUNNING recovery cannot persist or may fail on first query.
2. Fable's claim that idempotency/claim logic is strong: run claim CAS, step claim CAS, attempt idempotency, fingerprint-backed run/rerun idempotency, outbox claim behavior.
3. Fable's P1 queue/pre-fetch concern: all runtime and beat tasks sharing one Celery queue/prefetch behavior.
4. Fable's P1 webhook health gap: health endpoint missing webhook outbox/dead-letter visibility even though webhook dead-letter can fail runs.
5. Fable's step-result dual-writer concern.
6. Fable's deletion candidates: `DISPATCH_FAILURE`, `RETRIED`, `FlowRunService.execution_backend`, and executor legacy non-config constructor path.
7. Any top-ranked findings in the review that should be demoted, split, rejected, or raised.

## Required Output

Write a complete Markdown verification report with:

1. Five-line TL;DR.
2. `Verdict Matrix`
   - finding id/name;
   - Codex verdict: `verified`, `partially verified`, `unverified`, `false positive`, or `needs implementation spike`;
   - source evidence;
   - confidence.
3. `False Positives / Overclaims`
4. `Confirmed Production Blockers`
5. `Confirmed High-ROI Non-Blockers`
6. `Implementation Backlog`
   - priority;
   - owner/canonical home;
   - smallest safe change;
   - acceptance criteria;
   - tests.
7. `What Not To Fix Now`
8. `Questions For Tomorrow`
9. `Verification Commands / Files Read`

If you verify a claim, include file:line citations. If you cannot verify it directly, say so and lower confidence.
