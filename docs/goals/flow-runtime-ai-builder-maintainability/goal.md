# Flow Runtime, Flow AI Builder Maintainability, And Production Readiness

## Objective

Make Eneo Flows and Flow AI Builder production-ready with a maintainability target of **9/10**: a senior engineer should be able to understand the runtime lifecycle, public API contracts, AI Builder material routing, and data model boundaries in the first week without fear of invisible regressions.

The current branch is pre-production. There are no production users to protect, so unnecessary legacy and fallback code should be removed when local source/test/runtime proof shows it is not part of the intended product. This does **not** mean deleting blindly: every deletion must be backed by grep proof, behavior tests, and fixture/migration cleanup where relevant.

## Goal Kind

`open_ended`

## Current Tranche

Execute successive small, verified implementation phases on the current branch:

1. Reverify current source and dirty state.
2. Fix the highest-ROI runtime/API P0 slices with TDD-red behavior tests.
3. Add public API golden journeys and stable error payload behavior for Flow API consumers.
4. Consolidate typed data boundaries where they reduce future fear of change.
5. Remove pre-production legacy/fallback/dead code and dead tests after proof.
6. Improve AI Builder material efficiency and source-material routing without adding parallel architecture.

Do not stop after planning if a safe Worker slice can be activated. Commit each completed verified phase locally. Do not push.

Stay on the current branch, `feature/refactor-flows-flowai`, unless the owner explicitly asks for a different branch.

## Scope

Backend-first:

- Flow runtime lifecycle and crash/recovery behavior.
- Flow run creation, runtime input validation, review checkpoint validation, outputs/artifacts/evidence.
- Flow public API contract and OpenAPI/Swagger behavior for humans and LLM-generated clients.
- Flow JSONB/data model boundaries: metadata, published definitions, review payloads, AI Builder edit result state.
- Flow AI Builder only where it consumes Flow capabilities, material routing, form_fields/inmatningsfält, or generated-flow runtime contracts.
- Frontend only where backend error payloads and API contracts need a user-facing error path.

## Non-Goals

- No broad rewrite of Flow runtime or Flow AI Builder.
- No shallow pass-through services, generic managers, generic helpers, or speculative interfaces.
- No mechanical file splitting just to make files smaller.
- No prompt-only/model-tier fixes for backend dataflow or runtime correctness.
- No `all_previous_steps` band-aids for missing AI Builder material routing.
- No preserving legacy/fallback behavior merely out of fear; keep it only when it protects current intended product behavior, fixtures, migrations, or tests that have not yet been replaced.
- No deleting behavior without tests that protect the intended replacement behavior.
- No committing `.codex/artifacts`, local eval outputs, curl logs, temporary scripts, screenshots, API keys, `.env` files, caches, MP3s, or unrelated dirty files.
- No source comments or docstrings that say “see review packet,” “phase,” “slice,” or other internal planning vocabulary.

## Maintainability Invariants

1. **One canonical owner per concept.**
   - Terminal lifecycle: `FlowRunTerminalizer` / explicit lifecycle repository methods.
   - Run-request validation: run-contract/service boundary.
   - Review edited payload validation: `FlowRunService` before repository persistence.
   - Persistence: repositories only.
   - Runtime output-contract validation: one shared validator reused by runtime and review-edit paths.
   - Form schema: one typed parser/serializer once that slice starts.
   - Published definitions: one typed versioned model once that slice starts.
   - Flow engine truth: Flow capability/runtime modules; AI Builder consumes, never owns engine truth.

   Each Worker receipt must name the owner it deepened and explicitly say why it did not create a parallel owner.

2. **Typed boundaries over dict-shaped mechanics.**
   New or touched persistence/API/queue/runtime boundaries should use Pydantic/dataclass/TypedDict/Protocol/Enum contracts. Avoid new `Any`, `cast`, and `# type: ignore` unless the boundary reason is explicit and reviewed.

3. **Error handling is a product contract.**
   Every touched public API failure must return a stable error code, actionable message, context fields, and documented OpenAPI behavior. Frontend/web-app developers should not need backend source to handle errors.

   For touched Flow API paths, verify the real HTTP response body, not only the Python exception type or OpenAPI schema. When the backend error contract stabilizes, add or update the frontend error state that renders the failure in language a normal user can act on.

4. **Behavior tests over mock choreography.**
   Mock-call tests do not prove runtime lifecycle, persistence, race, or API consumer behavior. P0 fixes need red tests that fail on real bad behavior and pass after the fix.

5. **Comments must explain why.**
   Remove AI-slop comments: restating code, tutorial prose, vague TODOs, or comments making claims not enforced by code/tests. Good comments explain invariants, transaction boundaries, or non-obvious tradeoffs concisely.

6. **Deletion is allowed, but proof-gated.**
   Since the feature is pre-production, backwards compatibility is not a default reason to keep code. Keep compatibility only when it protects active tests, current fixtures, current migrations, or intended product behavior.

   Production DB proof is not required by default for Flow/AI Builder cleanup in this branch. Local proof is still required: grep proof, behavior tests, fixture/migration implications, and an owner decision.

7. **Generated flows must be smart, not just valid.**
   AI Builder output quality is part of maintainability. A flow that bloats context, drops source material, hides form fields, or relies on broad fan-in is a defect even if it runs.

8. **Long-term maintainability wins over shortcuts.**
   When a quick fix conflicts with cleaner ownership, typed contracts, durable error handling, or runtime reliability, choose the cleaner long-term solution. A slightly larger, well-scoped diff is acceptable when it reduces future fear of change and avoids a workaround that another engineer will need to undo.

9. **Ask for peer pressure on difficult design choices.**
   When the best implementation path is ambiguous and the decision affects canonical ownership, long-term reliability, public API behavior, data boundaries, or runtime lifecycle semantics, use Claude as a second opinion before committing to the direction. Do not guess through important uncertainty just to keep moving.

## Maintainability Score Rubric

Every Worker receipt must estimate the maintainability delta using this rubric:

- Canonical ownership: did the change deepen one existing owner rather than create another?
- Fear-of-change reduction: can a senior engineer now change this behavior with fewer hidden dependencies?
- Type safety: count new `Any`, `cast`, and `# type: ignore`; justify each or keep count at zero.
- Error contract quality: touched API failures have stable code, message, context, and real HTTP tests.
- Test quality: behavior/fresh-session/API tests protect the real failure, not collaborator calls.
- Comment quality: added/changed comments explain invariants or tradeoffs, not obvious code.
- Complexity: no unbounded loops, broad fan-in, hidden DB race, or token/context growth without a measured reason.
- Deletion quality: removed code has grep proof, replacement behavior tests, and fixture/migration cleanup if relevant.

Score each axis as `0` fail, `0.5` weak, or `1` pass. The receipt must record the score and name every axis below pass. A cumulative tranche reaches 9/10 maintainability when the rubric score is at least `7.2/8` and no blocker category remains open.

A phase is not 9/10 maintainable if it fixes the bug by adding another ad hoc branch to a change-magnet file without clarifying ownership.

## Claude Phase Gate

Use the Claude peer loop as a maintainability challenge before green-lighting the next big phase or any important architecture/runtime/API decision.

Claude must run from the host-installed CLI through exactly this peer-loop wrapper:

```bash
/Users/ccimen/.agents/skills/claude-peer-loop/scripts/claude_peer_loop.py
```

Do not run Claude login, OAuth recovery, or phase gates from a sandboxed/containerized environment. If authentication fails, first verify the host CLI with `claude auth status --text` and a small `claude -p` smoke test. Then run the peer-loop wrapper from the host with explicit `--model claude-opus-4-7 --effort xhigh`; do not switch to one-off `claude -p` reviews or a different script for goal gates.

Run Claude reviews with a long enough timeout for meaningful analysis. Use at least 15 minutes and prefer 20 minutes for phase gates, commit gates, and difficult architecture decisions. Iterate in the same Claude session until `GREEN_LIGHT: yes`, or document an evidence-backed disagreement before proceeding.

Gate tiering:

- P0/API/runtime/data-boundary/lifecycle implementation: run a blocking Claude commit gate before the local phase commit. A separate plan gate is required only when Judge changes canonical ownership, public API/error contract, schema/migration shape, or cannot define the red-test harness/allowed files confidently.
- Pure cleanup with a proof table and no ownership/API/schema change: self-review plus Judge review is enough. Use Claude only when deletion touches multiple owners, removes compatibility behavior, or the proof table is disputed.
- Phase-boundary or major lane transition: run a full Claude retrospective before green-lighting the next major phase.
- Important decision trigger means a decision that changes canonical ownership, public contract, persisted schema, lifecycle transaction boundary, or frontend/backend error contract. It does not mean every local implementation choice.

Required loop for big phases and important decisions:

1. Ask Claude to find areas to improve before the phase is considered green.
2. Verify Claude's concrete claims against local source evidence; do not accept false positives.
3. Revise the plan, implementation, or next-task definition when the critique is valid.
4. Resume the same Claude session and ask whether the revised state earns green light for the next phase.
5. Proceed on `GREEN_LIGHT: yes`. A `GREEN_LIGHT: no` blocks when the concern is correctness, canonical ownership, type contract, behavior-test adequacy, public API/error contract, regression risk, data-loss risk, or security risk. Stylistic, out-of-scope, duplicate-policy, or process-cost objections may be overruled only in the receipt with file:line evidence and a one-line owner rationale.

This gate applies before local commit of a P0/API/runtime/data-boundary phase, after a completed big phase, and before changing cleanup scope or canonical ownership. Use the tiering above to avoid review noise.

## Confirmed / Candidate P0 Work

The first Scout and Judge must reverify these against the current branch before activating Worker:

1. Required runtime inputs are advertised by run contract but may be bypassed when `step_inputs` is omitted.
2. Review checkpoint edits may bypass output-contract validation.
3. Executor failure terminalization may lose persisted failed state.
4. Late provider success may overwrite or mutate terminalized run state.

The first safe Worker should address exactly one P0. Combining P0s is allowed only when Judge proves they share the same red test, same canonical owner, same files, and same rollback path.

Required-input enforcement and create-run idempotency fingerprint canonicalization are separate concerns. The first can reject invalid requests without changing successful idempotency semantics. If Scout/Judge decide omitted `step_inputs` and `{}` should canonicalize identically for valid optional-input requests, that must be treated as a separate API behavior change with its own test and receipt.

## Maintainability Work After Early P0s

These are not cleanup vanity work; they reduce fear of change:

1. Public API golden journey for a future web app:
   - inspect published flow,
   - fetch run contract,
   - upload/route files,
   - create run,
   - handle missing-input error,
   - handle review checkpoint edit/approve/resume,
   - fetch output/artifact/evidence.

   This journey must assert both success behavior and at least one typed failure body. It should be usable as an executable example for human developers and LLM-generated web clients.

## Public API Golden Journey Acceptance

The public API golden journey should act as executable documentation for future web apps and LLM-generated clients.

It must assert:

1. The client can inspect a published flow and discover runtime paths.
2. The client can fetch run contract and identify required form fields, required file inputs, final output type, review steps, and template readiness.
3. Missing required runtime input returns a typed, documented HTTP error.
4. A valid run request can be created from the contract.
5. If review is present, the client can fetch active checkpoint, submit invalid edit and receive typed error, submit valid edit, approve, and resume.
6. The client can poll status and fetch final output/artifact/evidence.
7. Every touched error body contains stable `code`, `message`, and useful `context`.
8. Idempotency-key replay behavior is either asserted in the journey when touched, or explicitly deferred to `API-create-run-step-inputs-fingerprint-canonicalization`.

2. Typed JSONB boundaries:
   - choose `PublishedFlowDefinitionV1` first if runtime/contract corruption is the dominant risk,
   - choose `FlowMetadataV1` / `FlowFormSchemaV1` first if form/run-contract mismatch is dominant.

3. Pre-production legacy cleanup:
   - remove unused fallback paths after grep + tests + fixture/migration proof,
   - delete or collapse tests that only protect removed compatibility,
   - keep only compatibility that serves intended product behavior.

   Cleanup should target code that reduces fear of change: fallback branches hiding invalid state, stale test-only compatibility, dead wrappers, duplicate schema maps, obsolete comments, and tests that only preserve removed behavior.

## Cleanup Entry Gate

Do not start a source-wide cleanup or compatibility-removal Worker until at least one of these is true:

1. The cleanup is required by the active P0 fix.
2. A public behavior/API golden test already protects the intended replacement behavior.
3. Scout proves the target is source-dead and no current test/fixture/migration depends on it.

Cleanup Workers must use a proof table:

| Candidate | Intended replacement | Grep proof | Replacement behavior test path (or `queued: <test name>`) | Migration/seed implication | Decision |
|---|---|---|---|---|---|

Allowed decisions: `delete_now`, `delete_after_tests`, `delete_after_fixture_cleanup`, `keep`.

## Frontend Scope Gate

Frontend work may only be activated after the backend error contract for the touched endpoint is stable and tested.

A frontend Worker is allowed only when Scout proves one of:

- the current UI cannot show the new stable backend error code/message actionably,
- the touched Flow API path is part of the public API golden journey,
- the backend contract changed in a way that would otherwise leave users with a generic or misleading error.

Frontend Workers must stay narrow: render the existing backend error contract clearly. Do not redesign Flow UI in this tranche.

4. AI Builder material efficiency:
   - prove source/transcript/structured material loss with a red golden or disprove it,
   - keep normalizer/linter symmetry,
   - add deterministic metrics: binding byte size, fan-in width, structured field count, whole-output refs, source duplication, all_previous_steps count.

## P0 Implementation Anti-Patterns

Reject these even if tests can be made green:

- Adding a second validator when an existing validator can be extracted or reused.
- Adding a read-then-write application check where an atomic repository/SQL guard is required.
- Fixing one failure branch while leaving sibling branches with copy-pasted lifecycle logic.
- Returning generic `BadRequestException` without stable code/context for public API failures.
- Adding broad `dict[str, Any]` payloads at new persistence/API boundaries.
- Adding comments that explain the review history instead of the runtime invariant.
- Adding compatibility branches for hypothetical old users in this pre-production branch.

## Acceptance Criteria

A tranche is successful only if:

- At least one P0 is fixed with red-green behavior tests and a local commit, unless Scout/Judge blocks implementation with evidence.
- Every P0 Worker receipt answers: canonical owner, no-new-owner rationale, type-boundary impact, API/error impact, comment-quality impact, and regression risk.
- Every P0 Worker receipt names the relevant P0 implementation anti-patterns and the concrete code choice that avoids each.
- Every P0 Worker receipt includes diff counts for new `Any`, new `cast`, new `# type: ignore`, and all added/changed comments pasted verbatim for review.
- Every committed phase has strict typecheck/Pyright for changed files and targeted tests.
- Public API error behavior for touched endpoints is documented and tested.
- Frontend-visible failures are either updated to match the backend contract or explicitly queued with a blocking reason.
- No new duplicate canonical owner is introduced.
- No new unbounded dict-shaped persisted contract is introduced.
- No new AI-slop comments or internal planning vocabulary leak into source.
- A deletion/legacy cleanup checklist is produced and at least one safe pre-production cleanup slice is completed or explicitly deferred with proof.
- AI Builder generated-flow capabilities are not regressed; if touched, live V1-V5/C1-C5 smoke prompts are run when API is available.
- Final audit states whether maintainability improved, what fear-of-change was reduced, and what remains risky.
- The goal board itself is committed locally before `/goal` starts implementation work, unless the owner explicitly asks to keep the board uncommitted.

## Commit Cadence And Branch Discipline

- Stay on `feature/refactor-flows-flowai`; do not create, switch, rebase, push, or open a PR unless the owner explicitly asks.
- Commit at good reviewable intervals: after board setup, after each coherent verified P0/API/runtime/data-boundary/cleanup phase, and before starting the next major phase.
- Do not make a giant catch-all commit, and do not make noisy checkpoint commits for half-finished work.
- Do not mix board setup docs with production source changes in the same commit.
- Do not stage unrelated dirty files or local artifacts.
- Use concise human-readable commit messages that describe the behavior or maintainability improvement, not generic AI wording.
- Commit subjects and bodies must not contain internal planning vocabulary such as `P0.x`, `A.x`, `Phase N`, `slice`, `Worker`, `Scout`, `Judge`, or `Tranche`.
- Example commit subjects: `Add flow maintainability goal board`, `Validate required flow run inputs`, `Harden review checkpoint output validation`, `Guard late flow step completion`.

## Validation Commands

Discover exact repo commands first. Expected commands:

```bash
git status --short
git diff --check
cd backend && uv run pytest <targeted tests> -q
cd backend && uv run pyright <changed backend files and touched tests>
cd backend && uv run ruff check <changed backend files and touched tests>
cd backend && uv run ruff format --check <changed backend files and touched tests>
```

For public API/OpenAPI work:

```bash
cd backend && uv run pytest tests/unit/test_flow_openapi_contract.py -q
cd backend && uv run pytest tests/integration/flows -q
```

Local Docker/Postgres context is available for Scout/Worker validation when the board selects commands that need running services:

```bash
docker exec eneo-41ae93-eneo-1 <command>

docker exec -e PGPASSWORD=postgres eneo-41ae93-db-1 \
  psql -U postgres -d postgres
```

Default local database environment:

```bash
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_PORT=5432
POSTGRES_HOST=localhost
POSTGRES_DB=postgres
```

For AI Builder live smoke, if API/key are available:

- Run V1-V5 and C1-C5 prompt set across five spaces round-robin.
- Save raw outputs only in `/tmp`.
- Summarize smart vs dumb shape; do not commit outputs.

## Rollback / Recovery

- Commit each coherent verified phase locally; do not push.
- If a phase regresses behavior, revert that phase commit only.
- If a deletion breaks current intended behavior, restore and record what proof was missing.
- If a P0 fix requires a broader lifecycle design, stop after red-test evidence and Judge review.
- If local services/API credentials are unavailable, complete deterministic tests and mark live validation blocked, not skipped.

## Canonical Board

Machine truth lives at:

`docs/goals/flow-runtime-ai-builder-maintainability/state.yaml`

If this charter and `state.yaml` disagree, `state.yaml` wins for task status, active task, receipts, verification freshness, and completion truth.

## Run Command

```text
/goal Follow docs/goals/flow-runtime-ai-builder-maintainability/goal.md through successive safe verified maintainability and production-readiness phases on the current branch. Commit completed verified phases locally, but do not push. Do not stop after planning unless blocked.
```
