# Maintainability-Focused Review Findings

## Executive Position

The existing production-readiness board is strong on P0 runtime/API correctness, but it under-specifies maintainability cleanup after the first P0. The next goal should keep the P0 work, then explicitly add proof-backed cleanup, error-handling contract work, typed JSONB boundaries, and AI Builder material-efficiency metrics.

Because Flows and Flow AI Builder are pre-production, legacy/backwards-compatibility paths should not be kept by default. The right bar is lower than production DB proof but higher than a grep-only deletion: grep proof + behavior tests + fixture/migration cleanup + owner review.

## Highest-ROI Maintainability Changes

### 1. Keep P0 runtime/API fixes as the first lane, but add maintainability gates to every P0

Problem: The current goal correctly lists the four P0 candidates, but it does not explicitly require each P0 fix to reduce future fear of change.

Why it matters: A P0 can be fixed with another conditional in a large file, but that may make runtime lifecycle even harder to maintain.

Recommended change:
- For every P0 Worker, require a canonical-owner statement, a no-new-Any/type-ignore check, a comment-quality check, and a self-review that answers “could this be cleaner?”

Tests required:
- Existing red behavior tests plus typecheck and Claude commit gate.

Risk/trade-off:
- Slightly slower phase completion, but better reviewability.

Confidence: high.

### 2. Public API golden journey after first two P0s

Problem: Current tests are likely fragmented around individual services and endpoints. Future web apps need one public journey proving the flow API is usable without reading backend source.

Why it matters: API consumer DX is now part of production readiness. Missing inputs, review checkpoints, outputs, artifacts, and evidence need a coherent contract.

Recommended change:
- Add one HTTP integration journey that fetches a published flow, fetches run contract, submits invalid missing input, submits valid input, handles review checkpoint, resumes, and fetches output/evidence.

Current owner:
- Flow API router / assembler / run contract service / flow run service.

Proposed canonical home:
- Public Flow API integration tests and OpenAPI contract tests.

Acceptance criteria:
- Stable error envelope for touched failures.
- Operation IDs and examples exist for touched paths.
- Frontend/LLM client can determine required input and next actions from response bodies.

Confidence: high.

### 3. Pre-production legacy cleanup lane

Problem: The review packet is conservative about compatibility. The user clarified that there are no production users, so the maintainability plan should remove obsolete fallback code after local proof.

Candidate classes:
- top-level file input fallbacks,
- old template file fallback paths,
- legacy form field type maps,
- test-only HTTP config normalizers,
- router/re-export wrappers,
- compatibility tests that only protect removed behavior.

Recommended proof levels:
- delete_now: grep proves no source callers, route tests pass.
- delete_after_tests: current tests depend on legacy; migrate tests to intended behavior first.
- delete_after_fixture_or_migration_cleanup: fixtures/migrations contain old shape; update intentionally.
- keep: protects intended current product behavior.

Risk/trade-off:
- Removing too early can break hidden test fixtures. That is why every deletion needs a replacing behavior test.

Confidence: medium-high.

### 4. Typed JSONB boundaries after P0s

Problem: Flow metadata, published definitions, and AI Builder edit results are broad JSONB contracts. This creates long-term fear of change and silent data loss.

Recommended order:
1. `PublishedFlowDefinitionV1` if lossy runtime parsing is still a top risk.
2. `FlowMetadataV1` / `FlowFormSchemaV1` if form/run-contract mismatch is the bigger risk.
3. `PersistedCompiledEditResultV1` once edit-mode review paths stabilize.

Acceptance criteria:
- strict parser with explicit schema_version,
- `extra="forbid"` or explicit unknown-key handling,
- stable errors at publish/run-contract/run-start boundaries,
- no new repo-write `Any` debt.

Confidence: high.

### 5. Error handling contract hardening

Problem: A backend can be functionally correct while frontend/API consumers still receive vague or inconsistent errors.

Recommended change:
- For touched Flow endpoints, assert real HTTP error body.
- Prefer domain/application exceptions with stable code/context over direct `HTTPException(detail=dict)`.
- Add OpenAPI examples and schema assertions when an endpoint is touched.
- Include frontend-oriented context keys: missing step IDs, expected field names, revision conflicts, artifact/file IDs, max file limits.

Acceptance criteria:
- Errors are actionable to a web app developer and an LLM-generated client.
- No endpoint touched in a P0 fix returns undocumented generic body.

Confidence: high.

### 6. Comments and AI-slop audit in touched areas

Problem: Agent-created code often adds comments that restate code, vague TODOs, decorative confidence statements, or internal planning references.

Recommended change:
- Do not run a broad source-wide comment rewrite first.
- For each touched file, remove or improve comments that fail the standard.
- Add a later Scout-only task to identify low-risk slop comments across Flow/AI Builder.

Good comments explain:
- transaction boundary,
- concurrency invariant,
- API compatibility contract,
- why a fallback remains,
- why a validation belongs in a certain layer.

Bad comments:
- restate code,
- mention phases/slices/review packets,
- explain obvious Python,
- claim safety not enforced by tests.

Confidence: high.

### 7. AI Builder material efficiency as a separate lane

Problem: Generated flows can be valid but dumb: broad fan-in, dropped source material, unused form fields, context bloat.

Recommended change:
- Do not mix with runtime P0 unless files overlap.
- Add red golden / compiled spec first.
- Keep the existing canonical source-material/dataflow owners unless red evidence proves they cannot be extended.
- Add metrics in tests: binding byte size, fan-in width, structured field count, whole-output refs, source duplication, all_previous_steps count.

Confidence: high.

### 8. Lifecycle method naming and transaction boundaries

Problem: Flow runtime currently relies on developers knowing which executor branches commit and which repository writes are lifecycle transitions.

Why it matters: Runtime lifecycle code is high fear-of-change. A new maintainer should be able to tell from the method name whether a call is safe after terminalization, whether it commits, and whether it validates a public API contract.

Recommended change:
- For each P0 runtime fix, prefer lifecycle names that encode the invariant:
  - `complete_step_if_run_active`
  - `terminalize_with_failed_step`
  - `validate_run_request_against_contract`

Acceptance criteria:
- A new senior engineer can tell from the method name whether it is safe to call after a terminal run.
- Transaction behavior is explicit in the owning service/repository receipt.
- The Worker receipt states whether the method commits, requires caller commit, or is purely validating.

Risk/trade-off:
- Names should clarify real ownership, not create wrapper methods just to satisfy the wording.

Confidence: high.

## Updated Priority Order

1. Scout current branch, dirty files, exact commands, P0 evidence, maintainability hotspots.
2. First P0 slice, likely required runtime input enforcement.
3. Review checkpoint edit validation.
4. Executor failure persistence.
5. Late output atomic guard.
6. Public API golden journey + verify-first error payload drift.
7. Pre-production legacy/dead-code cleanup Scout and first safe cleanup Worker.
8. Typed JSONB boundary slice.
9. AI Builder material-efficiency slice with metrics.
10. Proposal processor/method ownership matrix only after above.

## What Not To Do

- Do not split large files mechanically.
- Do not preserve legacy fallback for hypothetical old users.
- Do not delete compatibility without replacement tests.
- Do not add a generic lifecycle engine now.
- Do not create a parallel AI Builder material planner before red evidence.
- Do not chase every P2 before P0/API contracts are safe.

## Confidence

High on the direction. Medium on exact delete candidates until Scout runs grep/test/fixture proof on the current branch.
