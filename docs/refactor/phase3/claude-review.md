## Summary

The plan's worst structural problem is **circular and ordering risk in the kill-list / dependency graph itself** — synthesis #6 (delete legacy compat shims) is presented as low-cost cleanup, but several entries gate later work and several depend on work the plan defers. Specifically: synthesis.md ranks "delete `flow_repo.py` / `flow_version_repo.py` / `flow_dispatch.py` / `ai_builder_models.py` star barrel" as cleanup, but `04-dead-and-legacy.md` admits the AI Builder star barrel has 124 import sites — that is a wave-sized refactor masquerading as a kill-list bullet. The same pattern repeats for "drop top-level `file_ids`" (gated on per-step file mapping rerun design landing first, which is itself an unbuilt feature in `05-api-consumer.md`) and "drop legacy form types" (depends on the frontend FlowEditor split that `03-frontend.md` puts in a separate wave). The plan's mermaid dependency graph collapses these into single nodes and hides a real ordering problem.

Second worst: **Phase 1b concept-invariants (`11-concept-invariants.md`) is not an independent check, it is a synthesis blessing**. It reaffirms the same contracts the Phase 1 agents proposed, written in the same vocabulary. Treating its agreement as evidence of soundness is an echo-chamber risk — there is no agent in the plan whose explicit job is to disagree with the other agents' conceptual frame.

Third worst: **The "feature-gap sketches" (per-step file mapping, step rerun, human-in-the-loop pause-and-edit) are prose, not contracts.** No acceptance criteria, no pre/post-condition tables, no failure-mode enumeration, no JSON contract examples. They will be re-litigated when implementation starts.

## Alternatives

1. **Reorder the kill-list around its real dependency cost, not its surface LOC.**
   Replace synthesis #6's flat list with a topologically sorted deletion table that includes import-site count, downstream consumer count, and whether a generated-types regen blocks downstream waves. The four "deletes" are not the same shape:
   - `flow_repo.py` / `flow_version_repo.py` — true shims (low risk, can land any wave).
   - `flow_dispatch.py` — call-site count needs a number; treat as its own slice.
   - `ai_builder_models.py` star barrel — 124 imports per `04-dead-and-legacy.md`; this is a wave, not a bullet. Pull it out of the kill-list and rank it alongside the AI Builder restructure (`01-ai-builder.md`).

2. **Replace `flow_run_artifacts` and `flow_run_step_inputs` with a `flow_attempt_payload_v1` JSONB column tagged by a Pydantic schema version.** Gemini already flagged the over-extraction; the constructive alternative is to keep the JSONB but make it *typed*: a discriminated `FlowAttemptPayloadV1 | V2 | …` union with a `schema_version` column, validated on read. Cross-run analytics queries (the only thing relational extraction would buy you) are not in any user story in `05-api-consumer.md`. Pay the relational cost only when a real query appears.

3. **For pause/resume, mandate a "checkpoint message" pattern instead of an `awaiting_review` worker-blocking status.**
   The Celery worker terminates at the checkpoint, persists `next_step_pointer` + `awaiting_review_token` into the run row, and emits an outbox event. Resume re-dispatches a fresh task that picks up the pointer. This avoids worker starvation (Gemini's concern) AND keeps step-execution idempotent — both requirements appear elsewhere in the plan but are not connected in `02-flow-runtime.md`'s pause sketch.

4. **DAG-aware rerun invalidation via `flow_step_dependencies`** (Gemini already identified the bug at `05-api-consumer.md:166-167`; the constructive fix is one query): a recursive CTE rooted at the rerun step that returns transitively dependent step IDs. The endpoint should return `invalidated_step_ids: UUID[]`, not `invalidated_step_orders: int[]`.

5. **For the AI Builder ScopeFilter bypass at `ai_builder_router.py:128-210`**, do not just "centralize the policy module" as `09-api-maintainer.md` proposes. The actual fix is to delete `Request.state.api_key_scope_*` reads from the router and require AI Builder principals to flow through the same `FlowPrincipal` factory as every other flow consumer. A typed policy module that still reads raw request state is the same bug with extra ceremony.

6. **For the FlowEditor authoring-state problem in `03-frontend.md`**, the proposed split (Driver / Service / Route mutations) risks re-creating the same mirror problem (`FlowAIBuilderService.svelte.ts:266-280`'s `#applyState` copies all driver state). Use a single Svelte 5 `$state` store owned by the route, with the Service as a *view* not a copy. The "split into three layers" instinct comes from React-shaped thinking, not Svelte 5.

## Risks or Blind Spots

These are concerns I do not see Gemini, the Phase 1 agents, or the synthesis raising:

1. **Audit outbox + terminalization is presented as one ROI item but they collide.** `02-flow-runtime.md` makes terminalization the contract — every run reaches a terminal state. `12-observability-operability.md` proposes an audit outbox where audit-on-terminalization is enqueued. What happens when the outbox is full or down? The plan does not specify whether terminalization fails-closed (run stays running, audit guaranteed) or fails-open (run terminalizes, audit lost). Both have downstream consequences and neither is named. This is the kind of cross-agent gap the synthesis is supposed to catch.

2. **F1 (generated frontend types) ranked #4 but has a hidden cycle.** `03-frontend.md` proposes deleting `resources.d.ts:153-530` manual types in favor of OpenAPI-generated types. But `09-api-maintainer.md` documents that `server/main.py:209-225` and `313-335` post-process the OpenAPI schema. So the generated types are downstream of the OpenAPI surgery, which is downstream of the multipart upload refactor (Gemini's "fix at source" point). F1 cannot land cleanly until the OpenAPI generator is honest. The plan ranks F1 as cleanup; it is actually a multi-wave dependency.

3. **The fine-grained permission taxonomy in `06-data-model.md` (9 permissions: flow.view, flow.run, flow.pause, flow.resume, flow.review, flow.publish, flow.delete, flow.audit.view, flow.ai_builder) has no migration story for existing role assignments.** The plan deletes `FLOWS_MANAGE` but does not specify what each existing assignment maps to. "Pause" and "resume" specifically — does an existing flow-runner get them by default? The answer matters because a default-grant gives every existing user pause-resume capability against runs they did not start. This is the kind of permission expansion that pre-production cleanup is supposed to *prevent*, not encode.

4. **Test inversion (159 unit / 10 integration in `08-tests.md`) is not in the top-20 ROI ranking.** It should be. Every wave the plan ranks #1-#10 changes a contract that is currently asserted in private-internal unit tests (executor `_mark_run_failed`, status enum literals, etc.). Without flipping the test pyramid first, every contract change is invisible to the test suite until production. The synthesis's #1 (status lifecycle consolidation) cannot be safely landed against the current test profile.

5. **Idempotency TTL (`06-data-model.md`) introduces a time-based conflict surface without a retention policy for the completed-run query interface.** If TTL = 7 days and a client retries a 30-day-old idempotency key, what does the API return — 404 or "duplicate"? The plan proposes the index but not the read-side semantics. This is the same shape of bug as the original idempotency design it is meant to fix.

6. **The synthesis claims `FlowRunService` should be split into ~3 services.** But the proposed split (orchestration / read / cancel) shares the same SQLAlchemy session and the same transactional boundary. Three services with one transaction = one service with worse imports. The split is cosmetic unless transactional boundaries are also separated, which the plan does not address.

7. **No reviewer is assigned to the AI Builder *prompt* surface.** `01-ai-builder.md` (which I could not read in full due to size) covers the code, but the FCM/knowledge-pack/critic-prompt corpus that the LLM actually sees has no audit. Given CLAUDE.md's hard rules about specialty-scope and form_fields semantics, the absence of a "prompt-as-contract" reviewer is structural — the plan can refactor the code clean and ship a regression in the LLM's behavior the next day.

8. **Kill-list and feature-list compete for the same engineer-weeks but are presented as independent.** Synthesis ranks both #6 (deletes) and #11+ (new feature gaps) without an explicit "kill before build" sequencing. Empirically, every feature gap implemented on top of the legacy shim doubles the deletion blast radius — this is a real ordering choice the plan elides.

9. **The "do-not-do" list in synthesis is short and unjustified.** A pre-production refactor of this scope should have a longer list of *explicitly rejected* alternatives, with reasons. The brevity suggests the plan considered fewer alternatives than it generated, which is a known failure mode of multi-agent reviews — agents converge before exploring.

## Recommended Next Step

Before any wave starts, produce three artifacts that the current plan lacks:

1. **A topologically sorted execution table** replacing the current ROI ranking, with columns: wave, slice, blocking dependencies (other slices), import-site / call-site count, test pyramid impact, and whether it changes a public contract that needs OpenAPI regen. Re-rank by what unblocks the most downstream work, not by stand-alone ROI.

2. **Acceptance-criteria contracts for each feature-gap sketch** (per-step file mapping, step rerun, pause/resume). One JSON contract example per endpoint, one pre/post-condition table per state transition, one failure-mode enumeration per long-running operation. Treat the sketches as design specs, not narrative.

3. **A cross-cutting "fail-closed vs fail-open" table** for every new asynchronous boundary the plan introduces (audit outbox, idempotency TTL, awaiting_review checkpoint, generated types CI). Each row says what the system does when the boundary fails, and which agent's contract is violated. This is the artifact that would have caught the audit-outbox-vs-terminalization collision above.

If only one of these three: do (1). The execution-order risk is the single highest-cost mistake the plan can ship.

## Confidence

Medium-high on the structural critiques (kill-list ordering, F1 cycle, audit-outbox collision, ScopeFilter bypass, test inversion, permissions migration gap) — these are grounded in direct quotes from `synthesis.md`, `04-dead-and-legacy.md`, `06-data-model.md`, `09-api-maintainer.md`, `08-tests.md`, and `12-observability-operability.md`.

Medium on the FlowRunService-split critique and the Driver/Service mirror critique — both depend on implementation choices the plan leaves unspecified, so the plan *could* land them correctly.

Lower on the "no prompt-as-contract reviewer" point — I could not read `01-ai-builder.md` in full (token limit), so it is possible the prompt corpus is covered there. If it is not, the gap stands.


Artifact saved to /Users/ccimen/eneo/eneo/.codex/artifacts/ask-claude-phase3-refactor-plan-attack-25min-20260428T185751Z.md
