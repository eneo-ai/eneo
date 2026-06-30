# ChatGPT Pro Review Packet — Eneo Flows / Flow AI Builder 9/10 Path

Date: 2026-06-30

## Five-Line TL;DR

1. Review the `refactor/flows-clean` branch as a pre-production architecture and maintainability hardening effort for Eneo Flows and Flow AI Builder.
2. Focus on the roadmap-execution commits from `799e0fae..b1974c90` (`23` commits), not the entire historical branch diff against `develop`.
3. Eneo Flows and Flow AI Builder are not in production, so deletion/reset/replay of unreleased compatibility and schema artifacts is preferred when safe and evidence-backed.
4. The target is an honest 9/10 on maintainability, clean architecture, clean code, runtime robustness, data/schema quality, tests, and API consumer DX before production.
5. Apply a delete/reuse/merge/move-first lens: do not recommend broad rewrites, fake abstractions, new helper layers, or compatibility paths unless they remove a named owner problem.

## Branch And Review Scope

- Repo: `https://github.com/eneo-ai/eneo`
- Branch: `refactor/flows-clean`
- Implementation head before this review-packet doc commit: `b1974c90 fix(flows-api): declare template delete empty response`
- Focused roadmap-execution range: `799e0fae..b1974c90`
- Focused range size: `23` commits
- Important caveat: the full branch contains older Flow/Builder feature work. Use the focused range and the review docs below for this strategic review, otherwise the useful signal will be buried in old feature-branch history.

## Reading Order

1. This packet.
2. `review-artifacts/chatgpt-pro-current-status-digest-2026-06-29.md`
3. `review-artifacts/flows-9-10-architecture-roadmap-2026-06-29.md`
4. `review-artifacts/implementation-progress-2026-06-29.md`
5. `review-artifacts/chatgpt-pro-strategy-integration-2026-06-29.md` only if you want to see how prior ChatGPT Pro strategy feedback was integrated.

Optional local-only evidence exists under ignored `review-artifacts/ultracode-independent-review-2026-06-29/` and `review-artifacts/eneo-flows-preproduction-architecture-review-2026-06-29/`, but this packet intentionally does not require committing the raw review dump. Ask for a specific artifact if a claim needs deeper audit.

## Roadmap Execution Commits To Review

```text
5677bfde fix(flows-ui): remove stale builder applying status
60880f08 fix(flows-runtime): add e2e celery services
2c21e284 refactor(flows): delete dead authoring principal helpers
3a2aeffc refactor(ai-builder): delete dead builder helper wrappers
0d83fefe refactor(flows-runtime): remove document renderer facade
73d62957 refactor(ai-builder): remove dead structured output plumbing
0a6e89da refactor(flows-runtime): delete step handler registry
68b8e91d fix(flows-runtime): guard task terminalization failures
25cbd20a fix(flows-runtime): await execution unwind before timeout terminalization
c2308404 test(flows-runtime): prove task timeout terminalization contract
c2426c8d test(flows-runtime): derive typed failure message expectation
128d2162 perf(flows-runtime): cache step security space per run
e8fb4a93 test(flows-ui): add deterministic flow browser smoke
8eff712b fix(flows-api): return GeneralError for evidence failures
fbbec45f refactor(flows-runtime): delete webhook delivery payload mirror
abf78a7a migration(flows-db): add ordinal checks and assistant FK indexes
b183fcec fix(flows): delete template assets with retention reclamation
5d2e6e12 refactor(flows-runtime): merge queued redispatch paths
21369991 refactor(flows-api): project template asset capabilities at API boundary
d36f7df4 refactor(flows-runtime): resolve template fill by asset id first
210f6369 refactor(flows-runtime): add template identity readiness audit
bce13a2d fix(flows-runtime): flag template checksum drift in run contract
b1974c90 fix(flows-api): declare template delete empty response
```

## Current Known State

- Flows proper has improved materially through runtime correctness, API envelope cleanup, schema hardening, retention cleanup, E2E smoke coverage, queued redispatch merge, and staged template identity cleanup.
- Flow AI Builder is still the risk center and is planned to ship with Flows, so do not treat it as optional afterthought work.
- PG-D4 fallback deletion is intentionally blocked until target data audit/backfill proof shows runtime `template_file_id` compatibility can be removed without breaking published template-fill flows.
- PG-10b global validation-error standardization remains a generated-client and non-Flow API decision.
- Builder PG-16+ and PG-D1 through PG-D3 are blocked until the release path is explicit: if Builder ships, these become release-hardening work; if not, backend route/settings gating is required.

## Strong Preferences

- Because Flows and Flow AI Builder are pre-production, prefer deleting never-shipped compatibility and cleaning migrations that created deleted unreleased schema artifacts.
- If a later refactor drops a Flow/Builder table, column, enum value, JSON owner, or route that is not production data, also evaluate deleting or rewriting the migration that introduced it instead of preserving dead schema history.
- Use forward migrations only when applied/shared data history must be preserved.
- Do not fake reversible downgrades that reconstruct deleted invalid state.
- Keep necessary functionality; do not delete behavior just to make the code smaller.
- Delete tests that protect removed behavior or old architecture, but keep behavior/contract tests that protect current user-visible guarantees.

## Do Not Recommend

- Broad rewrites without a named duplicate owner or measured release risk.
- New generic helpers, managers, processors, service layers, factories, registries, one-implementation interfaces, or pass-through wrappers.
- Capability-descriptor/MCP work unless it adapts to a real external boundary or deletes a named duplicate owner.
- Whole-scale JSONB relationalization. Relationalize only when identity, lifecycle, FK/query/index, retention/audit, authorization, or corruption behavior requires it.
- "Builder off" plans that only hide frontend navigation while backend routes remain mounted.
- Permanent dual paths without a deletion trigger, data audit, migration check, or telemetry proof.

## Decisions Needed From ChatGPT Pro

Please answer each as a decision recommendation, not just as discussion.

### 1. Builder Ship Path

- Should Flow AI Builder ship in the first production cut with Flows?
- If yes, which Builder issues are release-blocking before production?
- If no, what exact backend route/settings/API gating must happen now, and what Builder cleanup should move after Flows proper ships?
- Is the current roadmap too optimistic or too conservative about Builder reaching 9/10?

### 2. Builder Reliability And Edit Intent

- What is the cleanest architecture for create/edit/revise intent routing so recognized edits do not fall into generic `self_correction_quality_failure`?
- What deterministic eval/golden coverage is the minimum before calling Builder robust?
- Which repair/fallback paths should be measured before deletion, and which can be deleted now because they preserve never-shipped or harmful behavior?
- Should provider truncation/tool-call malformed output fail typed before repair, and where should that owner live?
- What should be the canonical owner for Builder telemetry fields, failed-turn cost, repair attempts, and final failure classification?

### 3. API Consumer DX

- Is the proposed path to a single `GeneralError` envelope, including FastAPI 422 validation errors, worth doing before production?
- What generated-client compatibility checks are required if PG-10b changes validation errors globally?
- Is the evidence export typed-summary strategy sufficient, or should legacy open `summary` be deleted before production after typed parity?
- What API journey tests are required for an external developer to use Flows without reading backend source?
- What docs/OpenAPI/generated-client checks are missing for a true 9/10 API consumer and maintainer DX?

### 4. Data Model, Schema, JSONB, And Migrations

- Confirm or reject this migration policy: structural, data-preserving DDL gets honest reversible downgrades; lossy pre-production Flow/Builder cleanup uses reset/replay or explicit non-reversibility; never fabricate fake downgrades.
- When deleting unreleased Flow/Builder tables, columns, enum values, JSON owners, or compatibility paths, should we delete/rewrite the migration that added them when no production/shared data depends on them?
- Which Flow/Builder JSONB owners still need typed schema/version/corruption behavior before 9/10?
- Which JSONB fields should stay JSONB, and which should be relationalized because they carry identity, lifecycle, FK/query/index, retention/audit, or authorization semantics?
- What target-data audit is sufficient to delete runtime `template_file_id` fallback after PG-D4?

### 5. Runtime Robustness And Operability

- After PG-5/6/8, PG-7, PG-9, PG-11, and PG-14, what runtime reliability evidence is still missing before 9/10?
- Is queue separation needed now, or should it wait for saturation/load proof?
- What crash/load/dead-letter/operator-observability proof is required before production?
- Are there remaining duplicate runtime owners that should be merged before release?

### 6. Tests, Dead Tests, And Reviewability

- Which tests now protect deleted behavior, old compatibility, private call order, source shape, or implementation pins and should be deleted/replaced?
- What minimal test set should protect Flows and Builder without making future cleanup harder?
- Are the current E2E/browser/runtime/integration tests enough for release confidence? If not, what is the smallest high-signal addition?
- What tests should be mandatory before deleting Builder fallback/repair branches?

### 7. Overengineering And Clean Architecture

- What should be deleted, merged, moved, or reused first to reduce complexity without losing required functionality?
- Which current modules look like fake architecture, pass-through services, one-off helpers, or compatibility layers that should not survive pre-production cleanup?
- Which large files should not be split yet because deletion/merge should happen first?
- Which file/module boundaries are the highest ROI to improve for a new senior engineer joining the codebase?

## Required Output Format

Please return:

1. Five-line executive verdict.
2. Updated scorecard for Flows proper and Flow AI Builder across maintainability, clean architecture, clean code, API consumer DX, data/schema, runtime reliability, test confidence, and release readiness.
3. Top 10 release blockers, ranked by severity and confidence.
4. Top 10 delete/simplify/merge/move opportunities, with what functionality must be preserved.
5. Clear answers to the decision questions above.
6. Recommended next 5 implementation slices, each with scope, owner, acceptance criteria, tests, and stop conditions.
7. What not to do because it would create technical debt or fake architecture.
8. Any likely false positives or overstatements in the roadmap.
9. Whether the current path can honestly reach 9/10 before production, and what evidence would make that claim credible.

## Review Standard

Use these standards:

- One canonical owner per concept.
- Delete/reuse/merge/move before creating.
- No fake abstractions or one-implementation interfaces.
- Typed contracts at API/runtime/data boundaries.
- Public API changes must include OpenAPI/generated-client impact.
- Migration/schema changes must name reset/replay, reversibility, or forward-data preservation.
- Tests protect behavior, not implementation history.
- Comments should explain why, not restate code.
- A new senior engineer should understand the architecture path in week one.
