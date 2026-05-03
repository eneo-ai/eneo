# Batch 11.1d Claude Reconciliation — Edit-Path Mechanics

## TL;DR

1. Claude rejected the first 11.1d plan because it duplicated create-validator
   mechanics in edit validation and underspecified modify-patch derivation.
2. The accepted design adds one shared per-new-step mechanics validator, one
   edit-only fill pass, and a compiler adapter that reuses the existing output
   mode derivation owner.
3. User-authored invalid edit mechanics remain validation feedback, not
   architecture errors.
4. Final implementation verification reached `GREEN_LIGHT: yes`, minimum score
   `8/10`.
5. Claude's non-blocking coverage questions were answered with extra tests before
   commit.

## Iteration 1

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-1d-edit-path-mechanics-plan-20260503T032518Z.md` |
| Verdict | `changes_required` |
| Green light | `no` |
| Minimum score | `6` |

Accepted findings:

| Finding | Resolution |
|---|---|
| Edit validation would duplicate create-validator mechanics. | Added `validate_new_step_mechanics` as the shared per-new-step owner. |
| Modify-patch output-mode derivation was underspecified. | Derive against the merged persisted step plus patch, not patch fields alone. |
| Incompatible user-authored edit fields should not become architecture errors. | Kept them on the validation feedback path before compile/store. |
| `normalize_edit_draft_mechanics` should not become a fill owner. | Added a separate `fill_edit_draft_mechanics` pass after cleanup normalization. |
| First-step source rules needed explicit treatment. | Shared validator covers first-step and non-first `flow_input` rules by step index. |

Rejected findings:

| Finding | Reason |
|---|---|
| None. | All blocking findings were accepted and folded into the revised plan. |

## Iteration 2

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-1d-edit-path-mechanics-plan-verification-20260503T032907Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `7` |

Accepted non-blocking findings:

| Finding | Resolution |
|---|---|
| Keep the modify-patch derivation helper private to the edit compiler. | Implemented `_derive_modify_patch_output_mode` in `ai_builder_edit_compiler.py`. |
| Keep flow-level form-field declaration rules in the create validator. | Only per-step unknown form refs moved to the shared validator. |
| Preserve template-fill DOCX when modify patch omits output mechanics. | Added compiler coverage. |
| Proposal feedback should include offending field/value. | Added proposal processor coverage for `output_mode 'template_fill'` with `output_type 'pdf'`. |
| Keep the edit-only type downgrade warning. | Left `type_downgrade_risk` in `validate_edit_draft`. |

## Iteration 3

| Item | Value |
|---|---|
| Artifact | `.codex/artifacts/claude-peer-loop-batch-11-1d-edit-path-mechanics-implementation-verification-20260503T034729Z.md` |
| Verdict | `green` |
| Green light | `yes` |
| Minimum score | `8` |

Accepted findings:

| Finding | Resolution |
|---|---|
| The synthetic `NewStepDraft` adapter is acceptable but should not become a parallel derivation owner. | Kept it as a private compiler adapter and recorded future extraction only if `derive_new_step_output_mode` needs more fields. |
| Delivery mode is reconstructed from persisted step mechanics in edit derivation. | Documented the invariant in the journal and added DOCX-to-PDF coverage. |
| Shared edit add validation should prove more than runtime upload rules. | Added edit add coverage for `media_source_mismatch` and `citations_require_llm_text_step`. |
| Feedback must include field/value pairs. | Proposal processor test asserts `output_mode 'template_fill'` and `output_type 'pdf'`. |
| Confirm non-first runtime defaults are not filled. | `test_fill_edit_draft_mechanics_does_not_default_non_first_file_step` covers it. |

## Remaining Disagreements

No implementation disagreement remains.

Claude called out a possible future improvement: if `derive_new_step_output_mode`
starts depending on additional `NewStepDraft` fields, extract a narrower core
function that takes only input type, output type, and document delivery mode.
That is not needed in this slice because the current derivation reads only those
mechanics fields.

## Confidence

High. The final peer review was green, the accepted findings were implemented,
and the extra tests added after Claude's non-blocking questions made the edit
shared-validator and compiler-derivation contracts more explicit without
changing source behavior after green light.
