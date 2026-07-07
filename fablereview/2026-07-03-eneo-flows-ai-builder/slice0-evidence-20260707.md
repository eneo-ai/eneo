# Slice 0 Evidence Gate - 2026-07-07

## TL;DR

1. Fresh Slice 0 harness bundles were generated at `api-battle-tests/slice0-evidence-20260707/ai-builder-api-battle-suite-20260707T133947/`.
2. The provided API key was scoped to space `f2a4cfb3-48ba-4e23-9513-53065e48c6b0`; the user-provided URL space `bab63e20-b982-4ea7-854c-ce6f3f6b38fa` returned `insufficient_scope`.
3. `document_pdf_source_retention_balance` created a plan 3/3 and passed `terminal_document_output_mode == render_verbatim` 3/3.
4. The same PDF case passed `renderer_is_previous_step_bound` 3/3, proving the zero-LLM terminal renderer is bound to the previous composed text body in these fresh runs.
5. Slice 0 is not green: plan creation and expected-leaf retention are still flaky in the two non-PDF gate cases.

## Command

```bash
python3 backend/scripts/ai_builder_api_battle_test.py \
  --cases-file backend/scripts/ai_builder_api_context_balance_cases.json \
  --run-suite \
  --force-new \
  --timeout-seconds 900 \
  --case-id document_pdf_source_retention_balance \
  --case-id source_derived_report_fields_not_runtime_fields \
  --case-id runtime_fields_explicit_case_metadata \
  --repetitions 3 \
  --output-dir fablereview/2026-07-03-eneo-flows-ai-builder/api-battle-tests/slice0-evidence-20260707
```

Credentials were supplied through environment variables and are not recorded in this file.

## Result Matrix

| Case | Plan rate | `expected_leaf_output_fields` | `terminal_document_output_mode` | `renderer_is_previous_step_bound` | Notes |
|---|---:|---:|---:|---:|---|
| `document_pdf_source_retention_balance` | 3/3 | 2/3 | 3/3 | 3/3 | r01 also introduced source-derived metadata as form fields (`report_title`, `document_category_hint`) and missed the harness aliases for `document_date` / `conclusion_summary`. |
| `runtime_fields_explicit_case_metadata` | 1/3 | 0/1 created plans | n/a | n/a | r01/r02 ended with `self_correction_invalid_plan`; r03 created required runtime form fields but omitted `case_number` from output leaves. |
| `source_derived_report_fields_not_runtime_fields` | 2/3 | 2/2 created plans | n/a | n/a | r02 ended with `self_correction_invalid_plan`. |

## Evidence

| Artifact | Path |
|---|---|
| Suite summary | `fablereview/2026-07-03-eneo-flows-ai-builder/api-battle-tests/slice0-evidence-20260707/ai-builder-api-battle-suite-20260707T133947/suite-summary.json` |
| PDF r01 | `fablereview/2026-07-03-eneo-flows-ai-builder/api-battle-tests/slice0-evidence-20260707/ai-builder-api-battle-suite-20260707T133947/ai-builder-api-battle-test-20260707T133947-document_pdf_source_retention_balance-r01.json` |
| PDF r02 | `fablereview/2026-07-03-eneo-flows-ai-builder/api-battle-tests/slice0-evidence-20260707/ai-builder-api-battle-suite-20260707T133947/ai-builder-api-battle-test-20260707T134049-document_pdf_source_retention_balance-r02.json` |
| PDF r03 | `fablereview/2026-07-03-eneo-flows-ai-builder/api-battle-tests/slice0-evidence-20260707/ai-builder-api-battle-suite-20260707T133947/ai-builder-api-battle-test-20260707T134156-document_pdf_source_retention_balance-r03.json` |
| Runtime metadata r01 | `fablereview/2026-07-03-eneo-flows-ai-builder/api-battle-tests/slice0-evidence-20260707/ai-builder-api-battle-suite-20260707T133947/ai-builder-api-battle-test-20260707T134006-runtime_fields_explicit_case_metadata-r01.json` |
| Runtime metadata r02 | `fablereview/2026-07-03-eneo-flows-ai-builder/api-battle-tests/slice0-evidence-20260707/ai-builder-api-battle-suite-20260707T133947/ai-builder-api-battle-test-20260707T134102-runtime_fields_explicit_case_metadata-r02.json` |
| Runtime metadata r03 | `fablereview/2026-07-03-eneo-flows-ai-builder/api-battle-tests/slice0-evidence-20260707/ai-builder-api-battle-suite-20260707T133947/ai-builder-api-battle-test-20260707T134213-runtime_fields_explicit_case_metadata-r03.json` |
| Source-derived r01 | `fablereview/2026-07-03-eneo-flows-ai-builder/api-battle-tests/slice0-evidence-20260707/ai-builder-api-battle-suite-20260707T133947/ai-builder-api-battle-test-20260707T134034-source_derived_report_fields_not_runtime_fields-r01.json` |
| Source-derived r02 | `fablereview/2026-07-03-eneo-flows-ai-builder/api-battle-tests/slice0-evidence-20260707/ai-builder-api-battle-suite-20260707T133947/ai-builder-api-battle-test-20260707T134129-source_derived_report_fields_not_runtime_fields-r02.json` |
| Source-derived r03 | `fablereview/2026-07-03-eneo-flows-ai-builder/api-battle-tests/slice0-evidence-20260707/ai-builder-api-battle-suite-20260707T133947/ai-builder-api-battle-test-20260707T134222-source_derived_report_fields_not_runtime_fields-r03.json` |

## Next Action

Do not proceed to a green Slice 0 claim yet. The next local slice should target the `self_correction_invalid_plan` failure path and the source-derived metadata-as-form-fields leak. The render-verbatim terminal closure itself has fresh passing evidence.
