# T024 Next Maintainability Slice Decision

## TL;DR

Do not start T008 cleanup as the next implementation task.
Do not start a typed `FlowMetadataV1` Worker directly yet.
Claude found a valid blocker: `metadata_json` has 151 hits across 26 Flow files and `form_schema` has 81 hits across 10 Flow files, so a direct Worker risks creating a parallel typed owner instead of replacing raw readers.
The next active task should be a read-only typed-data-boundary Scout that inventories Flow metadata/form-schema/published-definition inner-payload readers and produces a staged migration plan.
Make the current board update a docs-only commit before source implementation.

## Decision

Activate a typed-data-boundary Scout, not a Worker.

The Scout must cover these boundaries together:

- `metadata_json` readers/writers across `backend/src/intric/flows/**`
- `form_schema` readers/writers across `backend/src/intric/flows/**`
- `PublishedFlowDefinition.metadata_json` inner payload typing
- existing AI Builder partial metadata shape `FlowMetadataPatch`
- cleanup dependencies unlocked by a typed metadata/form-schema owner

## Why This Outranks Alternatives

| Alternative | Decision | Reason |
|---|---|---|
| Narrow cleanup Worker | Defer | T007 found no safe source-code `delete_now` candidate. Cleanup candidates require replacement tests or fixture/migration proof. |
| Direct typed metadata/form-schema Worker | Defer | Too likely to create a parallel owner without a reader inventory and staged migration plan. |
| Published-definition/template-asset Scout only | Broaden | `PublishedFlowDefinition` already exists as an outer typed dataclass; the remaining issue is its raw inner `metadata_json` payload, which overlaps with the metadata/form-schema boundary. |
| AI Builder material-efficiency Scout | Defer | Important, but T010 still needs a captured red flow/material-loss symptom; typed metadata ownership currently reduces broader fear of change. |

## Evidence

| Evidence | Result |
|---|---|
| `rg -n "metadata_json" backend/src/intric/flows -g '*.py' \| wc -l` | 151 hits |
| `rg -l "metadata_json" backend/src/intric/flows -g '*.py' \| wc -l` | 26 files |
| `rg -n "form_schema" backend/src/intric/flows -g '*.py' \| wc -l` | 81 hits |
| `rg -l "form_schema" backend/src/intric/flows -g '*.py' \| wc -l` | 10 files |
| `backend/src/intric/flows/published_definition.py:30` | `PublishedFlowDefinition` already exists as a frozen dataclass. |
| `backend/src/intric/flows/published_definition.py:36` | The remaining published-definition gap is raw `metadata_json: JsonObject \| None`. |
| `backend/src/intric/flows/published_definition.py:118` | `parse_published_definition` casts raw `metadata_json` instead of parsing a typed inner model. |
| `backend/src/intric/flows/ai_builder/ai_builder_edit_models.py:117` | `FlowMetadataPatch` is already a partial typed metadata shape and must not become a parallel owner. |
| `backend/src/intric/flows/flow_validators_form.py:216` | `normalize_legacy_form_schema` is a cleanup target, but it should be replaced by the typed owner rather than deleted first. |

## Claude Review

Claude iteration 1 returned:

- `VERDICT: changes_required`
- `GREEN_LIGHT: no`
- `MIN_SCORE: 6`
- Artifact: `.codex/artifacts/claude-peer-loop-t024-next-maintainability-slice-decision-20260511T020846Z.md`

Claude iteration 2 returned:

- `VERDICT: green`
- `GREEN_LIGHT: yes`
- `MIN_SCORE: 8`
- Artifact: `.codex/artifacts/claude-peer-loop-t024-next-maintainability-slice-decision-iteration-2-20260511T021228Z.md`

Accepted feedback:

- A direct `FlowMetadataV1` Worker is too broad without first inventorying raw metadata/form-schema readers.
- A typed boundary Scout should treat `form_schema`, `metadata_json`, and published-definition inner payload typing as one ownership problem.
- `PublishedFlowDefinitionV1` wording is misleading because `PublishedFlowDefinition` already exists; the gap is inner payload typing.
- `FlowStepResult.step_id` cleanup is promising, but likely belongs after a separate type-tightening decision rather than this immediate cleanup Worker.
- AI Builder `required_slot_names`/`has_new_evidence` should not be pre-classified as cleanup-eligible by the Flow cleanup Scout; keep it for a dedicated AI Builder Scout/Judge decision.
- T025 should include stop conditions for material-routing scope bleed and too many read-write metadata writers.
- T025 should require the Scout's proposed Worker slices to stay reviewable, with a normal target of at most six source/test files per slice and a named closer slice that retires remaining dict readers.

Rejected feedback:

- None. Claude's blockers were consistent with the goal's single-source-of-truth and no-parallel-owner rules.

## Next Task Definition

The next active task should be T025: a read-only typed-data-boundary Scout.

Expected output:

- Reader inventory table for all 26 `metadata_json` files and 10 `form_schema` files.
- Classification per reader: `read_only`, `read_write`, `validator`, `serializer`, `published_snapshot`, `ai_builder_patch`, `runtime_contract`, or `test_only`.
- Canonical owner recommendation for `FlowMetadataV1` / `FlowFormSchemaV1`.
- Decision on whether `FlowFormSchemaV1` is a standalone model or nested inside `FlowMetadataV1`.
- Relationship to existing `FlowMetadataPatch`.
- 2-3 Worker migration sequence with allowed files and validation commands.
- Red replacement tests for legacy normalization deletion.
- Explicit decision on whether `FlowStepResult.step_id` type-tightening is separate.
- Claude plan gate requirement before activating the first typed-boundary Worker.

Commit timing:

- Commit the current board and notes as a docs-only local commit before any source Worker starts.
- T025 is read-only and can proceed after the board commit; the first typed-boundary Worker must not start while the board update is uncommitted.

## Human Maintainability Impact

This decision should make `backend/src/intric/flows/flow_validators_form.py`, `backend/src/intric/flows/published_definition.py`, `backend/src/intric/flows/flow_run_contract_service.py`, and AI Builder metadata handling easier to change. Today each reader must understand raw JSON shape. The intended future state is one parser/serializer owner that makes invalid metadata hard to consume and removes repeated dict-walking logic.
