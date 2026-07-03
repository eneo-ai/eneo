# Claude Peer Loop Brief: Fable Review Split And Prompt Strategy

## Goal

Review Codex's Fable usage strategy before spending scarce Claude Fable budget.

The user wants high-impact, source-backed review material for Eneo Flow AI Builder and Flows before production. The focus is long-term maintainability, clean architecture, robustness, API/data-model quality, testability, underlag/source-material semantics, input/output JSON contracts, RAG/token efficiency, repair/fallback reduction, and JSONB-vs-relational choices at 50k-user scale.

## Current Decision

Codex plans **sequential Fable sessions**, not four parallel Fable agents:

1. **Fable 01: Proposal repair boundary**.
   - Highest priority.
   - Review proposal submission, self-correction, forced tool retry, JSON-text fallback, create/edit proposal processors, create-intent normalization, create feedback, and proposal finalization.
   - Classify each repair/fallback as `MODEL_BOUNDARY`, `CONTRACT_BRITTLENESS`, or `UPSTREAM_VALIDATION`.
   - Output: `.codex/artifacts/fable-review-program-20260703/fable-01-proposal-repair-boundary-review.md`.

2. **Fable 02: Compiler/topology/runtime contracts**.
   - Run after Fable 01 returns.
   - Review whether Builder compiles valid create/edit specs directly or relies on broad post-hoc normalization.
   - Include underlag/source material, `input_bindings.question`, JSON paths, RAG query derivation, output contracts, shared publish/runtime validation.
   - Output: `.codex/artifacts/fable-review-program-20260703/fable-02-compiler-topology-runtime-contracts-review.md`.

3. **Fable 03: Planning-state/JSONB/data model**.
   - Run only if budget remains or if sessions 01/02 imply persistent state changes.
   - Review `PlanningState`, conversation JSONB, proposal JSONB, commit spine, relational extraction candidates, and 50k-user scale.
   - Output: `.codex/artifacts/fable-review-program-20260703/fable-03-planning-state-jsonb-scale-review.md`.

4. **Optional Fable 04: Discovery/attachments/dialog cadence**.
   - Not automatic.
   - Run only if sessions 01/02 do not settle the conversation/attachment discovery contract.
   - Focus on uploaded template/law/example file signals, one-click-to-summary behavior, and deterministic discovery heuristics.

## Why This Changed

Initial Codex bias was one or two broader sessions around Builder architecture and runtime dataflow. After GPT-5.5 xhigh agents and Opus review:

- Opus recommended sequential sessions, with contract/repair first.
- Repair-focused agent recommended proposal repair boundary first, compiler/topology second, planning-state/JSONB third.
- Frontend agent verified the screenshot behavior is backend turn policy, not just frontend `requires_confirm`.
- Runtime agent found RAG/full-underlag and shared validator/runtime mismatches.
- Data-model agent found JSONB is mostly disciplined, but `PlanningState` version/cap governance and conversation JSONB scale need scrutiny.

## Existing Artifacts

- `.codex/artifacts/fable-review-program-20260703/index.md`
- `.codex/artifacts/fable-review-program-20260703/fable-session-plan.md`
- `.codex/artifacts/fable-review-program-20260703/fable-source-evidence-packet.md`
- `.codex/artifacts/fable-review-program-20260703/agent-repair-fable-split-review.md`
- `.codex/artifacts/fable-review-program-20260703/agent-runtime-dataflow-review.md`
- `.codex/artifacts/fable-review-program-20260703/agent-data-model-jsonb-review.md`
- `.codex/artifacts/fable-review-program-20260703/agent-maintainability-boundaries-review.md`
- `.codex/artifacts/fable-review-program-20260703/agent-frontend-dialog-state-review.md`
- `.codex/artifacts/ask-claude-fable-ai-builder-review-split-long-20260702T223104Z.md`

## Key Evidence To Challenge

### Repair/fallback

- `ai_builder_proposal_repair.py` implements max three self-correction retries, forced-tool retry after text, JSON-object-text fallback, and retry-state handling.
- `ai_builder_create_proposal.py` and `ai_builder_edit_proposal.py` reportedly catch broad exceptions and feed them into repair-style feedback.
- `ai_builder_proposal_intent.py` has strict schema but still normalizes/recovers invalid shapes.
- `ai_builder_step_transition_policy.py` and `ai_builder_create_dataflow.py` normalize invalid mechanics after proposal generation.

### Conversation/attachments

- `ai_builder_planner_request_preparation.py` returns early for ask/commit/confirm decisions before building attachment context.
- `ai_builder_attachment_context.py` treats uploaded files as generic reference material.
- `ai_builder_server_decision_dispatch.py` can chain architecture commit into requirements confirmation in one backend turn.

### Runtime contracts

- Prior Fable/agent evidence says RAG receives full `prepared.step_input.text`.
- Builder/manual publish validation can diverge from runtime path grammar.
- `STEP_INPUT_KEY_SHAPES` drifts from runtime metadata.
- Contractless JSON field refs and array paths are risky.

### JSONB

- `flow_jsonb_ownership.py` is a real owner registry.
- `PlanningState` is typed/strict/versioned but may duplicate drifted version constants or dead caps.
- `builder_sessions.conversation` may be the main 50k-user JSONB pressure point if audit/search/pagination appears.
- `builder_plans.proposal_json` should likely remain JSONB snapshot, with stable display/query fields materialized only if evidence grows.

## Questions For Claude

Please challenge Codex's plan before we run Fable:

1. Is Fable 01 proposal repair boundary the correct first spend, or should discovery/attachments/dialog cadence or runtime underlag/RAG go first?
2. Is the three-session sequential split the right granularity, or should Codex combine/split differently?
3. Should Codex run optional Fable 04 now, or defer it until after sessions 01/02?
4. Is there a blocking clarification needed from the user before Fable 01? The only known ambiguity is whether deterministic discovery is legally/audit-required; Codex currently thinks that affects session 04 more than session 01.
5. Are we overfitting to "delete repair" and underweighting valid model-boundary defenses?
6. Are there Fable prompts that risk producing generic architecture advice instead of implementation-ready findings?
7. Apply Ponytail: what can be deleted, merged, reused, or made less AI-sloppy in the plan itself?

## Required Review Lens

- Challenge technical debt, maintainability, reliability, AI slop, duplicate/redundant code, unnecessary abstractions, ownership boundaries, typed contracts, and Ponytail's simpler/delete-first answer.
- Treat Fable as scarce. The goal is highest-ROI true findings, not maximum documents.
- Avoid generic "architecture review" advice. Judge prompt scope and artifact strategy.
- Return concrete changes Codex should make before running Fable.
