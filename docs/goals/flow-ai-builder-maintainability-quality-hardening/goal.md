# Flow AI Builder maintainability and quality hardening

## Objective

Improve Flow AI Builder toward production-ready maintainability and flow-generation quality by auditing architecture, ownership, typed contracts, runtime reliability, prompt/LLM usage, tests, and live AI Builder behavior; then execute the first safe, high-impact implementation slice with verification.

## Goal Kind

`open_ended`

## Current Tranche

Discover enough evidence across architecture, data model, AI Builder output quality, runtime reliability, API contracts, tests, comments, and complexity; choose one safe high-impact implementation slice; implement and verify that slice; then audit whether the tranche moved Flow AI Builder closer to a 9/10 maintainability bar.

This is not a planning-only goal. Planning, Scout findings, Claude review, Antigravity review, and Judge selection are setup for implementation unless the selected Worker slice is blocked by missing credentials, unsafe dirty worktree state, unavailable local services, or ambiguity that cannot be resolved from source evidence.

## Non-Negotiable Constraints

- Follow the repository `AGENTS.md` rules and the engineering standards in `docs/engineering/`.
- Stay on `feature/refactor-flows-flowai` unless switching is explicitly requested and safe.
- Preserve unrelated dirty files; do not stage, commit, push, reset, clean, or revert unrelated work.
- Do not commit or push unless the owner explicitly asks later.
- Prefer the long-term clean architecture path over compatibility workarounds; Flow AI Builder is not production-shipped.
- Do not add backward-compatible endpoints, legacy branches, speculative fallbacks, fake seams, one-implementation interfaces, or `V1` suffixes unless a real versioned migration exists.
- Prefer canonical ownership, deletion, merge, rename, or move before adding new abstractions.
- Keep strict Pyright meaningful; do not use `pyright: ignore`, `type: ignore`, broad `Any`, or untyped dict bags to force green checks.
- Use the canonical Claude peer-loop script for plan and implementation gates.
- Use Antigravity after Claude has reviewed a concrete plan or when Codex and Claude need an independent architecture challenge.
- Use complexity-optimizer discipline for performance or repeated-scan findings: scanner output is a lead, not proof.
- Keep local API keys out of files and artifacts.

## Standards To Cite

- `docs/engineering/maintainability-standards.md`
- `docs/engineering/comment-and-readability-standard.md`
- `docs/engineering/api-design-standard.md`
- `docs/engineering/testing-standard.md`
- `docs/engineering/frontend-state-standard.md`

## Current Scope

Primary focus:

- `backend/src/intric/flows/ai_builder/**`
- Flow AI Builder API routes and schemas
- AI Builder persistence, session, plan, and proposal lifecycle
- Flow creation/editing proposal pipeline
- Runtime handoff into flows
- Validation and repair loops
- Tests, evals, and manual/live API harnesses
- Comments, naming, module boundaries, data schema, and reviewability

Non-goals for this tranche:

- Broad Flow Package refactoring unrelated to AI Builder.
- Frontend UX changes unless a backend contract issue makes a small frontend update unavoidable.
- Commit, push, or PR work.
- Rebranding `intric.*` backend modules to `eneo.*`.
- Large rewrites without a narrow reviewable first slice.

## Required Artifacts

Codex should maintain the following local artifacts under `.codex/artifacts/`:

- `flow-ai-builder-maintainability-discovery.md`
- `flow-ai-builder-maintainability-plan.md`
- `flow-ai-builder-peer-synthesis.md`
- `flow-ai-builder-live-eval.md`

Large Scout outputs should be stored under `.codex/artifacts/`, not durable project docs, unless summarized in this goal board.

## Stop Rule

Stop when the first implementation tranche has an audit receipt with exact verification, or when all safe local work is blocked. Do not stop after planning, Scout review, Claude review, Antigravity review, or Judge selection if a safe Worker task can be activated.

Stop and report before implementation if:

- the Worker needs files outside its allowed scope;
- the local dirty worktree makes the slice unsafe;
- source evidence contradicts the selected approach;
- live evals would mutate a non-test space;
- local service or container failures prevent required verification and no narrow offline verification exists.

## Canonical Board

Machine truth lives at:

`docs/goals/flow-ai-builder-maintainability-quality-hardening/state.yaml`

If this charter and `state.yaml` disagree, `state.yaml` wins for task status, active task, receipts, verification freshness, and completion truth.

## Run Command

```text
/goal Follow docs/goals/flow-ai-builder-maintainability-quality-hardening/goal.md through the first safe verified implementation slice. Do not stop after planning unless blocked.
```

## PM Loop

On every continuation:

1. Read this charter.
2. Read `state.yaml`.
3. Re-check branch, dirty worktree, and current diff before writing.
4. Work only on the active board task or the current read-only Scout wave.
5. Write a compact task receipt.
6. Update the board.
7. If Judge selected a safe Worker task with `allowed_files`, `verify`, and `stop_if`, activate it and continue unless blocked.
8. Finish only with a Judge/PM audit receipt that maps receipts and verification back to the original user outcome.
