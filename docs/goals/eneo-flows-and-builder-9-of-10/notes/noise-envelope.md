# Noise envelope — declared before any candidate is measured

Pilot: one frozen build measured three times, 2026-08-07. Declared here so
the margin below cannot be chosen after seeing a candidate's result.

## Pilot identity

- Receipt: `/workspace/.codex/artifacts/noise-pilot-155x3/ai-builder-api-battle-suite-20260807T062153/suite-summary.json`
  (sha256 `3cbdf9cca62f76941ace007fba3469c817a5380461793a4a059a8b6bf21de7bc`)
- Product build under test: backend `DEV-b57a23aecfc5` at
  `http://localhost:8123/api/v1` (harness checkout stamped
  `DEV-9e1926266703`; exploratory mode, so `/version` was not gated)
- Instrument: harness_sha256
  `45e31f7f42088558780bdb0eb404061413e4673868937be604940c9cc858a851`,
  cases_sha256
  `b11b54e4586be19d14b79bdf8ec0e36d1d9f956f067ca1c6375d977865409240`
  (155 cases, outcome-classification semantics v3), concurrency 6,
  repetitions 3, sv, auto-confirm.

## What the same build did against itself

- Suite conformance per repetition: **47 / 47 / 50** passes of 155.
  Maximum same-build repetition-to-repetition movement: **3 cases**.
- 87/155 cases stable on `(outcome_class, expectation_verdict)` across all
  three repetitions; 68 (44%) were not.
- 38 cases changed expectation verdict across repetitions; **23 flipped
  between pass and fail** with no product change:
  advanced_explicit_change_log_analysis,
  advanced_explicit_procurement_matrix,
  attachment_json_degraderat_tidigare_beslut_kvalitet,
  docx_template_fill_tjanstgoringsintyg_generated_docx,
  easy_email_reply_with_case_metadata,
  easy_spreadsheet_case_statistics_json,
  hard_many_source_documents_exhaustive_pdf,
  interview_open_apartment_register, interview_open_building_supplements,
  interview_open_crisis_reports, interview_open_employment_certificate,
  interview_open_environmental_complaint,
  interview_open_food_poisoning_report, interview_open_procurement_review,
  interview_open_records_retention, interview_open_student_device_faults,
  interview_open_volunteer_interest, medium_document_analysis_pdf,
  ordinary_json_security_incident, ordinary_language_human_review_policy,
  ordinary_report_building_supplement,
  ordinary_report_procurement_comparison, simple_document_metadata_json

## Declared quantities

1. **Noise margin for full-suite single-run comparisons: 5 net cases.**
   Observed same-build movement was 3; three repetitions cannot see the
   tail, so the margin is rounded up, not down. Pass
   `--noise-margin 5` to `ai_builder_battle_compare.py`. A net conformance
   delta of ≤5 on a single-run pair is `no_measurable_change`, whatever it
   looks like.
2. **Case-level estimator:** proportion of repetitions reaching the modal
   `(outcome_class, expectation_verdict)` state. The comparator already
   refuses a direction for any case whose repetitions disagree.
3. **Single-run direction on the 23 flip cases proves nothing.** A
   regression or improvement confined to that list needs repeated
   measurement of both builds before it is believed.
4. **Targeted-cohort claims need repetitions, not this margin.** This
   margin covers the full-155 aggregate only. A claim about one cohort
   uses the plan's MDE rule (5 / cohort_size) and equal repetitions of
   baseline and candidate; three repetitions remain exploratory.

## Validity bounds

- The margin is tied to the instrument identity above. A harness or corpus
  change that alters what is scored re-runs the pilot; the comparator's
  identity gate enforces the refusal either way.
- Measured at concurrency 6 only. Receipts at other concurrency are
  different experiments (gated in `run_context`); whether provider error
  rate moves with load is undetermined — sequential 122 showed 8
  error-terminated observations, two concurrent runs showed 11 and 14 on
  the same cases. Suggestive, not established.
- One pilot, one build, three repetitions. This is the provisional
  envelope the plan's Slice 0 calls for, not a measured distribution.
