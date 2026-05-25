# New Codex Session Prompt

Use this prompt in a brand new Codex session.

```text
We are continuing Flows clean architecture work in /Users/ccimen/eneo/eneo.

Goal: remove the hidden complexity that makes Flows hard to debug, change, and review, then bring Flows proper, not Flow AI Builder, to a defensible 9/10 strict score floor across maintainability, code quality, clean architecture, separation of concerns, single source of truth, human readability, human reviewability, data integrity, API consumer DX, API maintainer DX, runtime reliability, and testability.

Use the score ladder, not blind 9/10 chasing:
- 6/10: known normal-path bugs fixed; public Flow API errors consistent; tests reviewable enough to proceed.
- 7/10: published runtime contract canonical; frontend generated-contract fallbacks removed; core API journey contract-tested.
- 8/10: webhook delivery durable; step identity stable; runtime file lifecycle explicit; service-key permission matrix coherent.
- 9/10: long-term polish complete: typed public/lifecycle JSONB ownership, mature health/readiness, clean frontend state ownership, and unneeded compatibility paths deleted.

Important branch and repo rules:
- Work in /Users/ccimen/eneo/eneo.
- Continue on branch feature/refactor-flows-flowai.
- Do not create, switch, merge, delete, or push branches unless I explicitly ask.
- Do not stage, commit, push, reset, clean, or revert unless I explicitly ask.
- Preserve unrelated dirty/untracked files.
- This is Flows proper only. Do not broaden into Flow AI Builder except where a Flow runtime/authoring file directly depends on a shared Flow contract.
- Prefer maintainability, typed ownership, single source of truth, and human reviewability over minimal diff size.
- Do not hide typing failures with Any, dict[str, Any], pyright ignores, as any, @ts-ignore, or speculative compatibility fallbacks.
- Do not add fake interfaces, generic adapters, pass-through services, or future-flexibility layers.
- Before adding or preserving Flow logic, find the existing owner and decide whether to reuse, extend, move, merge, delete, or create. Creating a parallel path requires a Judge-approved reason plus migration/deletion trigger.
- Do not copy scattered logic into new files and call it architecture. Move or reuse the existing logic behind the canonical owner.
- If creating a new module, class, or function, explain why existing owners are insufficient.
- If a temporary parallel path remains, document owner, reason, migration/deletion trigger, and test or preflight proving continued need.
- Reuse through canonical owners and small typed boundaries, not generic helpers, managers, processors, service locators, plugin systems, event buses, god modules, or one-implementation ports.
- Delete confirmed dead Flow code, legacy compatibility paths, and obsolete tests when evidence proves they are no longer needed.
- Do not run repo-wide dead-code cleanup. Cleanup scope is Flows proper plus directly coupled Flow contract/frontend generated-type usage.
- Do not delete tests by themselves; remove tests only in the same PR as the removed behavior or compatibility path they protected.
- For every Flow runtime concept, there must be one backend entry point that computes truth. Enforce this with guard tests where possible.
- Delete /input-policy/ unless a real caller cannot use /run-contract/; if retained, it must be a pure projection.
- Keep step behavior and output format separate: StepHandler by output_mode, OutputFormatSpec by output_type. OutputFormatSpec owns prompt instructions, native JSON-mode preference, validation/rendering requirements, and renderer selection. OutputRenderer is a leaf adapter for byte rendering only. Do not build a plugin SDK.

Start by reading:
- AGENTS.md
- docs/goals/flows-clean-architecture-2026-05-25/goal.md
- docs/goals/flows-clean-architecture-2026-05-25/state.yaml
- docs/goals/flows-clean-architecture-2026-05-25/notes/source-material-index.md
- docs/goals/flows-clean-architecture-2026-05-25/notes/roadmap-and-taskfiles.md
- docs/goals/flows-clean-architecture-2026-05-25/notes/step-handler-and-renderer-architecture.md
- FLOWS_FULL_DATA_SCHEMA_AND_PERMISSIONS_MAP_2026-05-25.md
- FLOWS_ARCHITECTURE_REVIEW_2026-05-25.md
- flows-clean-architecture-2026-05-25/00-master-goal.md
- flows-clean-architecture-2026-05-25/06-commit-roadmap.md

Then follow the Goal Maker board:

/goal Follow docs/goals/flows-clean-architecture-2026-05-25/goal.md through the first safe verified implementation slice. Do not stop after planning unless blocked.

The current active task should be T001. Treat it as read-only:
- Reconfirm the current source evidence for the first safe tranche.
- Specifically verify whether FlowTemplateAssetService.upload_asset still calls a missing FileService.save_docx_template through Any/cast.
- Verify whether Flow API scope mismatch still returns raw HTTPException detail instead of the documented GeneralError envelope.
- Identify exact tests and verification commands for the first safe Worker task.

After T001, run the Judge step T002 to choose the first Worker task.

Expected first Worker if evidence still matches:
1. fix(flows): persist DOCX template assets through typed file service
2. or fix(flows-api): return GeneralError for Flow scope mismatches

Do not jump directly to runtime input retention, service-key identity, step identity, webhook outbox, or schema migrations before the board reaches those tasks. Those require Judge/product-decision gates and source preflight.

After the first three safe commits, there is an explicit Flow-scoped dead/duplicate/legacy/compatibility inventory task. Treat it as read-only. Deletion or consolidation requires Judge approval and either zero-reference evidence, duplicated-logic evidence with canonical owner, or persisted-data/caller preflight.

T023 must inventory duplicate/scattered reusable Flow logic, not only dead code. For every duplicated/scattered concept, record:

| Concept | Current locations | Behavior differences | Canonical owner | Merge/delete path |
|---|---|---|---|---|

Also include zero-reference dead-code candidates, legacy-but-live compatibility paths, fallback paths that hide invalid state and need preflight, tests that only protect compatibility behavior, and candidates for merge/consolidation.

T024 must classify findings as `delete_now`, `merge_or_consolidate`, `needs_preflight`, or `keep_temporarily`. It must reject deletion/consolidation without evidence and reject creating a new implementation when reuse, merge, move, deepen, or delete is the right move.

Runtime compatibility preflight must include both mutable draft rows and immutable published snapshots in `flow_versions.definition_json`; published snapshots are the runtime boundary, so draft-only evidence is insufficient before deleting fallback behavior.

T025 may only delete or consolidate exact T024-approved candidates. Keep the slice small and reviewable; include behavior-preserving tests when logic is moved or merged; remove tests only when the behavior they protected is removed in the same PR. Any test removal must have line-level preservation/deletion boundaries, and any symbol deletion must include post-change zero-symbol and export cleanup checks. When unrelated dirty/untracked files are present, T025 must also verify in a clean checkout with only its patch applied.

Every proposed Worker after T023 must include:

Consolidation effect:
- Reused existing owner:
- Logic moved from:
- Logic deleted:
- Duplicate path removed:
- New code added:
- Why existing owners were insufficient:
- Guard/test preventing duplicate logic from returning:
- Net Flow logic surface area: reduced | preserved | increased
- If increased, why the increase is necessary:

After the published-contract tranche, the next new architecture tranche is step behavior/output-format isolation:
- map current output_mode dispatch and all output_type concerns in executor.py and step_execution_runtime.py: prompt instructions, native JSON-mode decisions, validation/rendering requirements, and byte rendering;
- approve a minimal StepExecutionResult or StepExecutionOutput extension, OutputFormatSpec, OutputRenderer, and StepHandler design from source evidence;
- introduce output format specs, renderers, and handlers in behavior-preserving slices;
- add guard tests so DOCX/PDF/template-fill logic does not become scattered again.
- T007 must deepen the published runtime contract owner, not create a second runtime input-policy path.
- T008 must remove frontend fallback/mirror logic once backend contract is canonical, not create another frontend contract shape.
- T017 must map duplicate/scattered output behavior and identify which code should be moved behind owners instead of copied.
- T018 must reject designs that copy current runtime logic into new files instead of moving/reusing it behind the approved owner.
- T019 must move existing output_type policy into OutputFormatSpec, not duplicate prompt/JSON/rendering logic.
- T020 must move existing output_mode behavior into StepHandlers, not copy executor logic.
- T021 guard tests must prevent duplicate runtime dispatch from coming back.

Retention and service-key tasks are blocked in state.yaml until the owner provides product/data decisions. Do not auto-activate them just because the run instruction says not to stop after planning.

When a task completes:
- update docs/goals/flows-clean-architecture-2026-05-25/state.yaml with a compact receipt;
- record commands run and pass/fail;
- activate the next safe task unless a stop rule applies;
- do not mark the whole goal complete unless a Judge/PM audit verifies every dimension is at least 9/10.

When peer-reviewing or self-reviewing each non-trivial task, explicitly answer:
- What existing owner did I reuse or deepen?
- What duplicate logic disappeared?
- What old path was deleted?
- What new code was added, and why were existing owners insufficient?
- What prevents this duplicate from returning?
- Is this simpler for a maintainer, or just split into more files?
```

## Short Version

```text
/goal Follow docs/goals/flows-clean-architecture-2026-05-25/goal.md through the first safe verified implementation slice. Do not stop after planning unless blocked.
```

Use the longer prompt above when the new session lacks context.
