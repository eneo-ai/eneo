# T003 Worker Receipt — Edit Form Operations Schema

## Red Test

Added `test_form_operations_schema_teaches_form_field_edits` to
`backend/tests/unittests/flows/ai_builder/test_ai_builder_edit_tool_schema.py`.

Red command:

```bash
cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_edit_tool_schema.py -q
```

Red result: `1 failed, 12 passed`. Failure was `KeyError: 'form_operations'`,
confirming the edit tool schema did not expose the already-supported
`FlowEditDraft.form_operations` contract.

## Implementation

Changed `backend/src/intric/flows/ai_builder/ai_builder_edit_tool_schema.py` only.

- Added top-level `form_operations` to the `edit_flow` tool schema.
- Added `builder_form_field_type_values()` in
  `backend/src/intric/flows/ai_builder/ai_builder_flow_schema_values.py` and
  reused it from the edit schema.
- Added a strict form-operation item schema with `op`, `field_name`, and
  `field_payload`.
- Pinned the LLM-facing form field type enum to create-mode values:
  `text`, `number`, `date`, `select`, `multiselect`.
- Kept parser/compiler/validator code untouched because `FlowEditDraft`,
  `FormFieldOperation`, validation, and compilation already support the
  contract.

## Validation

```bash
cd backend && uv run pytest tests/unittests/flows/ai_builder/test_ai_builder_edit_tool_schema.py -q
```

Result: `13 passed in 0.08s`.

```bash
cd backend && uv run pyright src/intric/flows/ai_builder/ai_builder_flow_schema_values.py src/intric/flows/ai_builder/ai_builder_edit_tool_schema.py tests/unittests/flows/ai_builder/test_ai_builder_edit_tool_schema.py
```

Result: `0 errors, 0 warnings, 0 informations`.

```bash
cd backend && uv run ruff check src/intric/flows/ai_builder/ai_builder_flow_schema_values.py src/intric/flows/ai_builder/ai_builder_edit_tool_schema.py tests/unittests/flows/ai_builder/test_ai_builder_edit_tool_schema.py
```

Result: `All checks passed!`.

```bash
cd backend && uv run ruff format --check src/intric/flows/ai_builder/ai_builder_flow_schema_values.py src/intric/flows/ai_builder/ai_builder_edit_tool_schema.py tests/unittests/flows/ai_builder/test_ai_builder_edit_tool_schema.py
```

Result: `3 files already formatted`.

```bash
git diff --check -- backend/src/intric/flows/ai_builder/ai_builder_flow_schema_values.py backend/src/intric/flows/ai_builder/ai_builder_edit_tool_schema.py backend/tests/unittests/flows/ai_builder/test_ai_builder_edit_tool_schema.py docs/goals/flow-ai-builder-quality-hardening
```

Result: passed with no output.

Docker fallback: `docker ps` was blocked by the local tool policy before Docker
execution; host-local backend validation was used.

Claude implementation review:

- Iteration 1: changes required. Accepted findings were duplicate form-field
  type values and missing top-level `edit_flow` description guidance for
  `form_operations`.
- Iteration 2: `GREEN_LIGHT: yes`, minimum score 7.

Commit-boundary checks requested by Claude:

- Intended file diff: only `ai_builder_edit_tool_schema.py`,
  `ai_builder_flow_schema_values.py`, and
  `test_ai_builder_edit_tool_schema.py` in the source/test phase diff.
- Anti-slippage grep over those files: no matches.
- Search for full `edit_flow` schema snapshots: no snapshot fixture requiring
  regeneration was found; matches were ordinary edit-flow behavior tests and
  this schema test.
- Create/edit form-field type order comparison passed:
  `['text', 'number', 'date', 'select', 'multiselect']` in both the helper and
  create outline schema.

## Self-Review

Correctness and edge cases: the schema now teaches the LLM the form-field edit
contract that the model/parser/compiler already support. It pins field name,
payload, allowed field types, options shape, strict sub-objects, and the
`uses_form_fields` relationship.

Maintainability and readability: the change is schema-only, small, and follows
the existing `ai_builder_edit_tool_schema.py` builder style. It avoids a new
module or new domain model.

Clean architecture and layer boundaries: the schema builder is the right owner
because the defect was the LLM-facing tool contract, not edit compilation or
validation.

Type contracts and pyright: focused pyright passed for touched files. No new
casts, ignores, or `Any` surfaces were added beyond the file's existing schema
builder boundary.

Duplication and abstraction: the LLM-facing form-field type values now live in
`ai_builder_flow_schema_values.py`, matching existing builder schema value
ownership and avoiding a local duplicate in `ai_builder_edit_tool_schema.py`.

Scope: the implementation is deliberately narrow. It does not try to fix parser
strictness, form-field type centralization, or the pre-existing dirty
create/dataflow draft.

Output quality impact: edit mode can now intentionally add/modify/remove
flow-level input fields and pair them with consuming steps. That improves real
flow quality because the model no longer has to smuggle runtime input needs into
step patches only.

Production-ready? Yes for this schema slice.

Would merge this phase? Yes, after implementation peer review.

Could this be cleaner or smarter? Parser `extra="forbid"` and conditional
payload validation would make the schema/parser contract stronger, but those
belong in `ai_builder_edit_models.py`, outside this schema slice.

Intentionally out of scope: live LLM evaluation, create/dataflow dirty draft
salvage, parser strictness, centralized form-field type values, and the known
bad multi-section audio-to-DOCX deterministic regression suite.

## Deferred Follow-Ups

- Consider `extra="forbid"` on `FlowEditDraft`, `FormFieldOperation`, and
  `FormFieldSpec`.
- Add conditional parser validation so `FormFieldOperation.field_payload` is
  required for add/modify and omitted for remove; today that rule is taught in
  the schema text but the parser/compiler remain permissive.
- Decide whether existing step-operation schema items should also use
  `additionalProperties: false`; this slice keeps strictness local to the new
  `form_operations` sub-schema.
- Review the existing dirty create/dataflow draft in a separate Judge task.
- Add the deterministic bad multi-section audio-to-DOCX regression coverage in a
  clean red-test phase after dirty draft disposition.

## Commit

Ready to commit after PM/Judge staging audit.
