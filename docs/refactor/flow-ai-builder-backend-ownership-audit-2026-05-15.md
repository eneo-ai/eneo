# Flow AI Builder Backend Ownership Audit

TL;DR:
- Flow AI Builder is much better than the earlier Flow runtime baseline because it already has boundary tests and several focused policy modules.
- It is still not 9/10 overall because the planner/proposal/router surfaces are broad and keep too much orchestration state in single modules.
- The canonical model owner is `ai_builder_domain_models.py`, but several runtime-facing JSON shapes still use `Any` and untyped dicts at important seams.
- The highest-ROI backend cleanup is not a broad rewrite; it is extracting named lifecycle owners around message turns, proposal processing, and apply/audit handling.
- Do not decompose the small policy modules first. The biggest reviewability gains are in the large orchestration files.

## Current Score

| Dimension | Score | Evidence | Why |
|---|---:|---|---|
| Maintainability | 7/10 | `ai_builder_service.py:166`, `ai_builder_planner.py:307`, `ai_builder_proposal_processor.py:473` | Good module inventory exists, but tracing one user message crosses service, router, planner, proposal processor, repo, plan lifecycle, and many policy helpers. |
| Code Quality | 7/10 | `ai_builder_domain_models.py:46`, `ai_builder_domain_models.py:145`, `ai_builder_create_outline.py:394` | The domain models and outline parser are typed and validated. The weaker points are broad `Any`/dict seams around LLM payloads and persisted metadata. |
| Clean Architecture | 7/10 | `test_importlinter_boundary.py:1`, `test_ai_builder_importlinter_rules.py:1` | Flow engine to AI Builder boundaries are explicitly guarded. Router still owns API response examples, auth flow, audit calls, streaming adaptation, and error event translation. |
| Separation of Concerns | 6/10 | `ai_builder_router.py:296`, `ai_builder_router.py:475`, `ai_builder_router.py:1016` | Router endpoints are not only thin adapters; they also shape SSE error handling, usage events, and audit logging. Planner/proposal processing also combine multiple phases. |
| Single Source of Truth | 7/10 | `ai_builder_domain_models.py:1`, `ai_builder_models.py:1` | Domain model ownership is clear, but `ai_builder_models.py` is still a wildcard compatibility aggregation layer. |
| Human Readability | 6/10 | `ai_builder_planner.py:997`, `ai_builder_proposal_processor.py:540`, `ai_builder_create_outline.py:562` | Local functions are often named well, but large turn/proposal methods force readers to keep too much state in working memory. |
| Human Reviewability | 6/10 | `ai_builder_proposal_processor.py:650`, `ai_builder_router.py:507`, `ai_builder_plan_lifecycle.py:84` | Small behavioral changes can touch LLM calls, persistence, SSE events, plan status, and frontend-visible error behavior at once. |
| Test Coverage | 8/10 | `backend/tests/unittests/flows/ai_builder/` inventory | The subsystem has many targeted tests and boundary tests. Remaining risk is not lack of tests; it is that some tests must understand large orchestration surfaces. |
| Error Handling Backend-To-Frontend | 7/10 | `ai_builder_router.py:268`, `ai_builder_router.py:582`, `ai_builder_router.py:1045` | Apply errors now have typed frontend handling, but SSE and HTTP errors are still partly router-shaped rather than one canonical AI Builder error contract. |

Overall score: **6/10**, because the minimum dimensions are separation of concerns, readability, and reviewability.

## Ownership Inventory

| Concept | Current locations | Problem | Canonical home | Merge/delete path |
|---|---|---|---|---|
| AI Builder domain records and portable flow spec | `ai_builder_domain_models.py:1`, `ai_builder_models.py:1` | Domain model owner is good, but `ai_builder_models.py` re-exports everything and keeps older imports alive. | `ai_builder_domain_models.py`, with API-only models in `ai_builder_api_models.py`. | Replace direct imports from `ai_builder_models.py` in touched files over time, then delete the aggregation layer when no imports remain. |
| Session/message lifecycle | `ai_builder_service.py:185`, `ai_builder_planner.py:997`, `ai_builder_repo.py:52` | Session creation is service-owned, but message send lifecycle is mainly planner-owned and includes locks, metadata, planning state, deterministic server actions, LLM request prep, and streaming events. | A future `AIBuilderMessageTurnService` or `ai_builder_message_turn.py`, only if it owns the full turn lifecycle behind a small interface. | Extract one lifecycle owner after stabilizing typed payloads. Do not split into pass-through helpers. |
| Proposal processing | `ai_builder_proposal_processor.py:473`, `ai_builder_proposal_processor.py:540`, `ai_builder_proposal_processor.py:650` | One class owns outline parsing, create/edit draft processing, repair/self-correction, quality feedback, metadata, and persistence callbacks. | Keep `AIBuilderProposalProcessor` as facade, but extract create and edit proposal pipelines into domain-specific modules with typed phase inputs. | Start with create proposal path because it has clear parser/compile/validate/persist phases. |
| Router/API adapter behavior | `ai_builder_router.py:296`, `ai_builder_router.py:475`, `ai_builder_router.py:1016` | Router does auth, response examples, session lookup, prepared context loading, SSE event post-processing, usage event recovery, audit logging, and special stale-revision translation. | Router should remain HTTP adapter; audit and error response translation should move to focused owner(s) only when they remove real router complexity. | First extract apply audit/logging and SSE stream adaptation; keep request parsing and dependency auth in router. |
| Apply lifecycle | `ai_builder_plan_lifecycle.py:84`, `ai_builder_router.py:1040` | Plan lifecycle owns most state transitions correctly, but router still translates stale revision and logs audit. | `AIBuilderPlanLifecycle` for business transitions; router only maps exceptions and returns DTOs. | Introduce a typed `AIBuilderApplyError`/exception mapping if more apply errors become frontend-facing. |
| Outline tool parsing and normalization | `ai_builder_create_outline.py:394`, `ai_builder_create_outline.py:428`, `ai_builder_create_outline.py:562` | This is a deep module with a real boundary. It handles model slop at the outline boundary and compiles to a typed draft. | Keep here. | Do not split merely due line count; only split schema building if it blocks review. |
| Flow capability boundaries | `test_importlinter_boundary.py:1`, `test_ai_builder_importlinter_rules.py:1` | This is a strong ownership guard and should be preserved. | Existing boundary tests plus `.importlinter`. | No deletion. Add rules only for real layer boundaries. |

## Highest-ROI Cleanup Order

1. **Replace `ai_builder_models.py` wildcard imports gradually.**
   - Problem: `ai_builder_models.py:1` is a compatibility aggregation layer that hides whether a caller needs domain, API, or event models.
   - Why it matters: It makes ownership look flatter than it is and weakens import review.
   - Acceptance criteria: touched files import from `ai_builder_domain_models.py`, `ai_builder_api_models.py`, or `ai_builder_event_models.py` directly; no new imports from `ai_builder_models.py`.
   - Tests: existing AI Builder unit tests and import-linter tests.
   - Risk/trade-off: Low if done opportunistically by touched file, high if done as one huge mechanical diff.
   - Confidence: high.

2. **Extract message-turn lifecycle from `AIBuilderPlanner.send_message`.**
   - Problem: `ai_builder_planner.py:997` owns budget fallback, response format selection, session status checks, send locks, lease refresh, persisted planning state, metadata resolution, deterministic server actions, LLM prompt prep, and streaming results.
   - Why it matters: This is the main place where runtime reliability and developer reviewability are weakest.
   - Canonical home: a narrow message-turn lifecycle owner that owns lock/lease/state orchestration and calls planner-prep/proposal modules.
   - Acceptance criteria: `AIBuilderPlanner` becomes a planner/prompt engine; lifecycle lock and persisted turn state live in one named owner with behavior tests for lock loss, session status rejection, and deterministic server action chaining.
   - Tests: `test_ai_builder_planner_send_message.py`, `test_ai_builder_failure_events.py`, `test_ai_builder_orchestration_pipeline.py`, plus new lifecycle tests.
   - Risk/trade-off: Medium. This should be done in two commits: move-only extraction, then cleanup.
   - Confidence: high.

3. **Split proposal processing by create/edit phase, not by helper count.**
   - Problem: `AIBuilderProposalProcessor` starts at `ai_builder_proposal_processor.py:473`; create path begins at `ai_builder_proposal_processor.py:540` and `ai_builder_proposal_processor.py:650`, while the same class also owns repair and retry logic later in the file.
   - Why it matters: Proposal behavior is high-risk: it decides what the AI-generated plan means and what feedback is sent back to the model.
   - Canonical home: create proposal pipeline and edit proposal pipeline with typed phase inputs and outputs.
   - Acceptance criteria: create/edit compile/validate/quality/persist phases are traceable without scrolling through unrelated repair paths.
   - Tests: keep golden tests, create compiler tests, edit compiler tests, proposal repair tests.
   - Risk/trade-off: Medium-high. Do after message-turn extraction, because the turn lifecycle currently wires much of this context.
   - Confidence: high.

4. **Create a canonical AI Builder public error contract for both HTTP and SSE.**
   - Problem: Router HTTP examples use `_ai_builder_error_response` at `ai_builder_router.py:268`; SSE errors are built in the stream catch blocks at `ai_builder_router.py:582` and `ai_builder_router.py:602`; apply stale revision is translated specially at `ai_builder_router.py:1045`.
   - Why it matters: The frontend should not need different parsing paths for apply HTTP errors and stream event errors.
   - Canonical home: `ai_builder_error.py` or an existing event/error model module if it can own both HTTP and SSE shapes without coupling to FastAPI.
   - Acceptance criteria: one typed enum/model for public AI Builder error codes, one mapper to HTTP `GeneralError`, one mapper to SSE error events, frontend discriminated union generated or mapped from that contract.
   - Tests: router response tests, SSE event tests, frontend apply error tests.
   - Risk/trade-off: Medium. Do not overbuild if only apply errors are frontend-actionable; start with cataloging existing public codes.
   - Confidence: medium-high.

5. **Keep `ai_builder_create_outline.py` deep, but type the raw model payload boundary.**
   - Problem: outline parsing intentionally accepts `dict[str, Any]` at `ai_builder_create_outline.py:394` and normalizes model mistakes at `ai_builder_create_outline.py:428`.
   - Why it matters: This is the right boundary for model slop, but the raw payload type should be named so callers know they are crossing an untrusted model-output seam.
   - Canonical home: same module, with a named `RawOutlineToolArguments` alias or Pydantic wrapper.
   - Acceptance criteria: raw model output is visibly different from compiled `FlowCreateOutline`; unsafe repair paths have focused tests.
   - Tests: existing outline parser/compiler tests.
   - Risk/trade-off: Low.
   - Confidence: medium.

## What Not To Do

- Do not split modules only by line count. `ai_builder_create_outline.py` and `ai_builder_step_skeleton.py` are large, but they are deep modules with real domain ownership.
- Do not add interfaces solely for tests. Existing boundary tests are more valuable than fake ports.
- Do not preserve `ai_builder_models.py` indefinitely as “compatibility” unless there is a concrete external import contract. This is internal pre-production code.
- Do not start with frontend AI Builder UX changes as a substitute for backend contracts. UX should consume typed errors and typed plan/session state.

## Acceptance Criteria For 9/10 Direction

- Router endpoint bodies are thin: auth/dependencies, service call, DTO response, HTTP exception mapping only.
- Message turn lifecycle has one owner, including lock lease, persisted planning state, deterministic server actions, and terminal event behavior.
- Proposal processing has typed create/edit phase boundaries and no broad `dict[str, Any]` bags except at explicit model-output or provider SDK seams.
- Public AI Builder errors have one machine-readable contract used by HTTP, SSE, frontend apply errors, and Swagger examples.
- Import ownership is obvious from import paths; wildcard aggregation imports are gone from touched code.
- All meaningful refactors are backed by behavior tests, not mock-call tests.

## Recommended Next Backend Slice

Start with **removing `ai_builder_models.py` imports from only the files touched by the current branch**, then stop. This improves ownership without a risky all-at-once mechanical rewrite.

After that, implement the message-turn lifecycle extraction as a separate goal. It has the best maintainability payoff, but it should be isolated from frontend UX and API contract changes.
