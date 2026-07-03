# Agent Review: Maintainability, Ownership Boundaries, And Deletion

## TL;DR

The highest maintainability risk is duplicated ownership of the same atomic Builder turn invariant: append conversation, rebuild `PlanningState`, CAS-save, and persist plan/message state in one transaction.
Slot/question identity is intentionally two-tiered, but the tiering is stringly and scattered across many maps.
Some obvious repair/fallback paths are legitimate external model-boundary defenses; do not delete them without telemetry or divergence evidence.
The best first refactors are merge/delete work: one commit spine, one slot reader, one removed router test seam.
This should inform Fable's maintainability session and implementation order.

## Ranked Findings

| Rank | Finding | Evidence | Proposed owner / fix |
|---:|---|---|---|
| 1 | Two modules own the same atomic turn-commit invariant. | `backend/src/eneo/flows/ai_builder/ai_builder_repo.py:1100`, `backend/src/eneo/flows/ai_builder/ai_builder_repo.py:1138`, `backend/src/eneo/flows/ai_builder/ai_builder_plan_store.py:83`, `backend/src/eneo/flows/ai_builder/ai_builder_plan_store.py:108` | One private repository commit spine should own compaction, conversation append, planning-state rebuild, CAS, savepoint, and rollback semantics. Plan persistence can call that spine. |
| 2 | Slot/question identity has no typed canonical registry. Requirement slots and discovery issues are valid separate tiers, but raw string IDs and metadata facets are scattered. | `backend/src/eneo/flows/ai_builder/ai_builder_slot_vocabulary.py:27`, `backend/src/eneo/flows/ai_builder/question_catalog.py:768`, `backend/src/eneo/flows/ai_builder/question_catalog.py:773`, `backend/src/eneo/flows/ai_builder/ai_builder_discovery_decision_engine.py:51`, `backend/src/eneo/flows/ai_builder/ai_builder_discovery_questions.py:253`, `backend/src/eneo/flows/ai_builder/ai_builder_create_compiler.py:542`, `backend/src/eneo/flows/ai_builder/ai_builder_architecture_derivation.py:166` | Introduce one typed slot/issue registry preserving `requirement` vs `discovery` tier. Use it to derive maps as slices touch them. |
| 3 | `_resolved_slot_value` is duplicated verbatim. | `backend/src/eneo/flows/ai_builder/ai_builder_create_compiler.py:554`, `backend/src/eneo/flows/ai_builder/ai_builder_architecture_derivation.py:185` | Move to one tiny slot-access owner or the future typed registry. |
| 4 | `_resolve_litellm_params` is a fake router test seam with `Any` types. | `backend/src/eneo/flows/ai_builder/ai_builder_router.py:225`, `backend/src/eneo/flows/ai_builder/ai_builder_router.py:643` | Delete wrapper and update tests to stub the service method directly. |
| 5 | Proposal JSON-text fallback is not currently a delete finding. | `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py:835`, `backend/src/eneo/flows/ai_builder/ai_builder_proposal_repair.py:810` | Keep unless telemetry or a divergence test proves it accepts behavior the tool-call path rejects. It routes through the same validation/repair classification. |

## Canonical Ownership Map

| Concept | Current / intended home | Keep or change |
|---|---|---|
| Portable draft flow schema | `backend/src/eneo/flows/flow_authoring_spec.py` | Keep. Good typed boundary. |
| Flow graph validity | `backend/src/eneo/flows/flow_validators.py`, `backend/src/eneo/flows/domain/flow_step_validation.py` | Keep. Builder should adapt and preflight, not duplicate. |
| Builder session/plan records | `backend/src/eneo/flows/ai_builder/ai_builder_domain_models.py` | Keep. Good domain home. |
| Conversation + `PlanningState` commit | Intended owner is `AIBuilderRepository` | Merge duplicate plan-store persistence spine into repository. |
| Requirement/discovery slot identity | Split across vocabulary, catalog, discovery maps, canonicalization, planning-state builder, compiler, and derivation | Create typed registry preserving two tiers. |
| Proposal submission/repair | Proposal submission/repair modules | Keep as real external LLM seam; reduce only with evidence. |
| HTTP/auth adapter | Router + flow access policy | Keep HTTP/auth translation at edge; delete fake test seam only. |

## Delete / Merge Candidates

| Action | Target | Notes |
|---|---|---|
| Merge | Plan-store manual state rebuild into repository private commit spine | First implementation slice; must include atomicity/CAS tests. |
| Delete | Duplicate `_resolved_slot_value` | Small safe cleanup. |
| Delete | `_resolve_litellm_params` | Test churn only. |
| Merge gradually | Parallel slot/issue maps | Do behind registry membership/tier tests. |
| Optional delete | Router pass-through helpers such as `_get_ai_builder_service` | Cosmetic only; do not prioritize unless touching router. |
| Do not delete now | JSON-text proposal fallback | Needs proof before removal. |

## From-Scratch Cleaner Shape

- Keep `FlowDraftSpecCore` and canonical Flow validators as the portable flow contract.
- Keep `AIBuilderRepository` as the persistence boundary, but make it the only owner of the atomic conversation/planning-state commit spine.
- Keep the LLM proposal seam because external model behavior is volatile and repair needs a boundary.
- Replace scattered slot/question string maps with one typed registry that derives allowed slots, question catalog membership, priorities, issue families, and persistence rules.
- Keep Builder as an adapter that creates semantic intent and lets one compiler/validator own Flow mechanics.

## Fable Follow-Up Questions

- Should the commit-spine merge happen before any larger Builder redesign because it reduces hidden persistence risk?
- What should the typed slot/issue registry own, and what should stay in question catalog or discovery policy?
- Which repair paths are valid model-boundary defenses and which merely hide internal unclear contracts?
- Is there a smaller "semantic proposal" contract that would reduce repair and mechanical normalization?
- What should tomorrow's first implementation slice be if we want maximum debt reduction without a broad rewrite?
