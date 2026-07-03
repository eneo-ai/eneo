# Fable 03 Prompt: Planning State, JSONB, Persistence, And 50k-User Scale

You are Claude Fable running a max-effort, source-backed data-model and maintainability review for Eneo Flow AI Builder and Flows.

Repository root: `/Users/ccimen/eneo/eneo-flows-clean`

## Mission

Review planning state, Builder session persistence, JSONB-vs-relational boundaries, database schema, and 50k-user scale. The user explicitly wants to know:

- which parts should still be JSONB;
- what the pros/cons are;
- whether some JSONB should logically move into relational database tables/columns;
- how to avoid long-term maintainability and scale debt.

Do not give generic "JSONB bad" advice. Judge each field using owner, version, validation boundary, query/index need, migration path, corruption behavior, retention/audit, and 50k-user scale.

## Non-Negotiable Output Rules

- Return a complete Markdown review.
- Start with a five-line TL;DR.
- Use file:line citations for concrete claims.
- Include confidence for every material finding.
- Apply Ponytail: delete, merge, move, reuse, simplify.
- Do not edit source, tests, migrations, package files, config, or docs.
- Do not write files yourself. Your stdout will be saved to:
  `.codex/artifacts/fable-review-program-20260703/fable-03-planning-state-jsonb-scale-review.md`

## Read First

Read:

- `.codex/artifacts/fable-review-program-20260703/index.md`
- `.codex/artifacts/fable-review-program-20260703/fable-source-evidence-packet.md`
- `.codex/artifacts/fable-review-program-20260703/agent-data-model-jsonb-review.md`
- `.codex/artifacts/fable-review-program-20260703/agent-maintainability-boundaries-review.md`
- `.codex/artifacts/fable-review-program-20260703/agent-repair-fable-split-review.md`

Then verify source yourself.

## Primary Source Scope

Inspect at least:

- `backend/src/eneo/database/tables/flow_tables.py`
- `backend/src/eneo/flows/infrastructure/flow_jsonb_ownership.py`
- `backend/src/eneo/flows/flow_capability_manifest.py`
- `backend/src/eneo/flows/ai_builder/planning_state.py`
- `backend/src/eneo/flows/ai_builder/planning_state_builder.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_discovery_profile_builder.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_user_question_metadata.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_conversation_metadata.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_repo.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_plan_store.py`
- `backend/src/eneo/flows/ai_builder/ai_builder_domain_models.py`
- `backend/src/eneo/flows/flow_metadata.py`
- `backend/src/eneo/flows/flow_authoring_spec.py`
- `backend/src/eneo/flows/application/flow_authoring_command_service.py`
- `backend/src/eneo/flows/api/flow_models.py`
- relevant Alembic migrations and tests only when needed to verify persisted-data claims.

## Review Workload Assumption

Use this as a concrete scale lens, not a precise forecast:

- 50k users;
- many Builder sessions;
- sessions may have 10-30 messages;
- some users upload files/templates/laws/examples;
- product may later need audit, search, support debugging, analytics, retention, and API consumer introspection.

If you need different assumptions, state them.

## Questions To Answer

1. For each relevant JSONB field, should it stay JSONB, become relational, or become JSONB plus materialized relational fields?

2. Is `builder_sessions.conversation` acceptable as JSONB long term?
   - What breaks first: row size, lock contention, pagination, audit, support search, analytics, partial loading, migration?
   - Would a `builder_session_messages` table be cleaner? If yes, what columns?

3. Is `builder_sessions.planning_state_jsonb` a justified typed snapshot?
   - Is its version/cap governance real or dead speculative machinery?
   - Is `PlanningState` the true single source of truth, or do discovery/profile/legacy question paths re-derive parallel facts?

4. Is `builder_plans.proposal_json` a justified immutable snapshot?
   - Should stable display/query fields such as draft title/output type/target kind be materialized?
   - Are nested spec strictness and hash coverage enough?

5. Should `builder_session_files` carry role metadata for uploaded file semantics?
   - Example roles: template, legal reference, sample input, desired output example, runtime input example, schema.
   - Should roles be relational, planning-state JSONB, or proposal JSON?

6. Should `flows.metadata_json.form_schema` or other authored config JSONB become relational if form fields become searchable/API-contract objects?

7. Are lifecycle statuses, transitions, locks, retry/crash recovery, and commit-spine persistence explicit enough?

8. Should duplicate commit spine logic in `ai_builder_repo.py` and `ai_builder_plan_store.py` be merged before larger refactors?

9. Which tolerant JSON reads/fallbacks need persisted-data evidence and deletion triggers?

10. What is not worth fixing now?

## Required Sections

Return:

1. `TL;DR`
2. `Ratings`
   - data model fitness;
   - JSONB discipline;
   - relational integrity;
   - maintainability;
   - scalability;
   - migration safety;
   - production readiness.
3. `Entity / Relationship Map`
   - include Builder sessions/plans/files and Flow draft/version/run tables.
4. `JSONB Decision Matrix`
   - field, current owner, keep/move/materialize, pros, cons, 50k-user risk, trigger for change, confidence.
5. `PlanningState Truth Review`
6. `Conversation Storage Review`
7. `Proposal Snapshot Review`
8. `Commit Spine / Transaction Boundary Review`
9. `Delete / Merge / Move List`
10. `What Current Tests Already Cover`
11. `Missing Red Tests`
12. `What Is Not Worth Fixing`
13. `From-Scratch Cleaner Data Model`
14. `Tomorrow Implementation Slices`
15. `Claims Codex Must Verify`
16. `Challenge This Brief`
17. `Confidence`

## Guardrails

- Do not propose relationalizing everything.
- Do not preserve pre-production compatibility unless there is persisted-data evidence.
- Do not propose generic event-sourcing, CQRS, plugin systems, or one-method repositories.
- Prefer explicit triggers: "move this to relational when X query/retention/audit need appears."
