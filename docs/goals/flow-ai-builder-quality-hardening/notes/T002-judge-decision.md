# T002 Judge Decision

## Decision

Select the first Worker slice as:

> Expose edit-mode `form_operations` in the `edit_flow` tool schema with a red
> schema test, then implement the smallest schema addition.

## Why This Slice

The preferred create/dataflow slice cannot honestly satisfy the board's red-test
gate in the current worktree because production and test changes for that area
are already dirty together. Reverting them to observe red would require
destructive operations against user/other-agent changes, which are forbidden.

The edit form-field slice is still genuinely red and small:

- `FlowEditDraft.form_operations` exists in `backend/src/intric/flows/ai_builder/ai_builder_edit_models.py`.
- Edit validation and compilation already consume `form_operations` in
  `backend/src/intric/flows/ai_builder/ai_builder_edit_validator.py` and
  `backend/src/intric/flows/ai_builder/ai_builder_edit_compiler.py`.
- `backend/src/intric/flows/ai_builder/ai_builder_edit_tool_schema.py` does not
  expose a top-level `form_operations` property, so the structured LLM tool does
  not teach the model how to add/modify/remove flow-level form fields in edit mode.

This directly improves Flow AI Builder output quality: an edit request such as
"lägg till inmatningsfältet ärende_id och använd det i slutrapporten" needs a
first-class form-field operation rather than a hidden or invented step patch.

## Allowed Files

- `backend/src/intric/flows/ai_builder/ai_builder_edit_tool_schema.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_edit_tool_schema.py`
- later phase receipt under `docs/goals/flow-ai-builder-quality-hardening/notes/`

## Required Red Test

Add a failing test to `test_ai_builder_edit_tool_schema.py` asserting:

- the `edit_flow` top-level parameters include `form_operations`;
- the `op` enum on `form_operations[*]`, not step operations, is exactly
  `["add", "modify", "remove"]`;
- `field_name` is required and has `type: "string"` plus `minLength: 1`;
- `field_payload` is a typed object with exactly these properties:
  `label`, `field_type`, `required`, `description`, `options`;
- `options` is an array of strings;
- `field_type` uses the same LLM-facing enum as create mode:
  `["text", "number", "date", "select", "multiselect"]`;
- new `form_operations` sub-objects set `additionalProperties: false`;
- the schema description mentions both `uses_form_fields` and that declared
  fields without step references become orphan UI controls;
- add/modify operations are documented as requiring `field_payload`, while
  remove operations are documented as omitting it.

Use the existing `_make_step` helper and the existing
`TestBuildEditFlowToolSchema` pattern in `test_ai_builder_edit_tool_schema.py`.
Do not create a new test helper or a new test file for this slice.

Observe the test fail before changing production code. The red and green states
may be recorded in the same T003 receipt; they do not need separate commits.

## Verification

Run before commit:

```bash
cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_edit_tool_schema.py -q
cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_edit_tool_schema.py tests/unittests/flows/ai_builder/test_ai_builder_edit_tool_schema.py
cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_edit_tool_schema.py tests/unittests/flows/ai_builder/test_ai_builder_edit_tool_schema.py
cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_edit_tool_schema.py tests/unittests/flows/ai_builder/test_ai_builder_edit_tool_schema.py
git diff --check -- backend/src/intric/flows/ai_builder/ai_builder_edit_tool_schema.py backend/tests/unittests/flows/ai_builder/test_ai_builder_edit_tool_schema.py docs/goals/flow-ai-builder-quality-hardening
```

If Docker becomes callable, the same backend commands may be run via
`docker exec eneo-41ae93-eneo-1 -w /workspace/backend ...`; the current tool
policy blocked even `docker ps`, so host-local validation is accepted fallback.

## Stop Conditions

- Need to edit model/compiler/validator files.
- The red test cannot be observed failing before implementation.
- The schema addition creates a broad edit-flow redesign.
- Any unrelated dirty file would need staging.

## Verified Existing Constraints

- `backend/src/intric/flows/ai_builder/ai_builder_edit_proposal.py` already calls
  `FlowEditDraft.model_validate(...)`, so a top-level `form_operations` key is
  parsed by the existing domain model once the LLM tool schema can emit it.
- `backend/src/intric/flows/ai_builder/ai_builder_form_fields.py` applies
  edit form operations only as effective names: remove discards the field name;
  add/modify add it to the available set.
- `backend/src/intric/flows/ai_builder/ai_builder_edit_validator.py` validates
  `uses_form_fields` against the effective form-field names, including fields
  added or removed by the same edit draft.
- There is no separate max-count, reserved-name, or step-name conflict rule in
  the current edit validator; this slice should not invent one.

## Deferred Work

- The existing dirty create/dataflow draft must be reviewed in a separate
  Judge task before staging. It should not be laundered into this Worker.
- The structured-field-path loosening flagged by Scout/Claude needs a targeted
  test review before that draft lands.
- The runtime prose change in `step_execution_runtime.py` remains outside this
  Worker.
- Centralizing the LLM-facing form-field type values into
  `ai_builder_flow_schema_values.py` is a follow-up. This slice may hard-code
  the create-aligned enum in `ai_builder_edit_tool_schema.py` to avoid touching
  dirty create files.
- Parser strictness such as `extra="forbid"` on `FlowEditDraft` and
  `FormFieldOperation` is a follow-up because it belongs in
  `ai_builder_edit_models.py`, outside this slice.

## T003 Receipt Template

The Worker receipt should include:

- red test command and failure summary;
- implementation summary;
- validation commands and results;
- self-review answers;
- deferred follow-ups;
- commit SHA if committed.
