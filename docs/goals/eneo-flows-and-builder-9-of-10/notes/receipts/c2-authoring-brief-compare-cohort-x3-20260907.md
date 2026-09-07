# Battle suite delta: DEV-20260907T111226Z -> DEV-20260907T115021Z

## Did this change help? **no_measurable_change** (net conformance -1: 0 improved, 1 regressed; declared margin 2)
Evidence: repeated — Both builds repeated; per-case instability is measured.

Conformance direction (primary): {'inconclusive': 20, 'unchanged': 14, 'regressed': 1}
Mechanics direction: {'unchanged': 29, 'improved': 2, 'regressed': 4}
Current outcomes: {'plan_repaired': 19, 'plan_first_pass': 79, 'builder_error': 5, 'stalled_unanswered_question': 2}

## Conformance regressions (the no-regression rule)
- attachment_pdf_report_exemplarform_kallgenomgang

## Conformance direction by cohort
- attachment_or_template: -1 net; {'inconclusive': 5, 'regressed': 1, 'unchanged': 4}
- audio: +0 net; {'inconclusive': 2}
- complete_everyday: +0 net; {'unchanged': 3}
- document: +0 net; {'inconclusive': 1}
- file_role_discrimination: +0 net; {'inconclusive': 1}
- form_fields: +0 net; {'inconclusive': 2, 'unchanged': 4}
- foundation: +0 net; {'inconclusive': 6, 'unchanged': 5}
- human_review: +0 net; {'unchanged': 2}
- input_field_contract: +0 net; {'inconclusive': 2, 'unchanged': 1}
- json: +0 net; {'inconclusive': 18, 'unchanged': 7}
- long_context: +0 net; {'inconclusive': 1}
- municipal_journey_v1: +0 net; {'inconclusive': 1, 'unchanged': 1}
- pdf: -1 net; {'inconclusive': 1, 'regressed': 1, 'unchanged': 2}
- persona_beginner: +0 net; {'unchanged': 1}
- persona_domain_expert: +0 net; {'unchanged': 1}
- persona_intermediate: +0 net; {'inconclusive': 1}
- persona_technical: +0 net; {'unchanged': 1}
- prompt_complete: +0 net; {'unchanged': 1}
- prompt_contract: +0 net; {'unchanged': 1}
- prompt_partial: +0 net; {'inconclusive': 1}
- prompt_vague: +0 net; {'unchanged': 1}
- single_missing_dimension: +0 net; {'inconclusive': 1}
- technical_contract: +0 net; {'inconclusive': 8, 'unchanged': 2}
- tjansteskrivelse_v1: +0 net; {'unchanged': 1}
- vague: +0 net; {'unchanged': 2}

## Unstable cases (a build disagreed with itself; no direction)
- baseline: advanced_explicit_change_log_analysis, advanced_explicit_integration_validation, advanced_explicit_lss_intake_contract, advanced_explicit_procurement_matrix, advanced_explicit_retention_inventory, attachment_json_lokalkalkyl_budgetposter_saknat_belopp, attachment_json_protokoll_remissvar_datumkonflikt, attachment_json_remissvar_per_avsandare, attachment_pdf_report_remissvar_sammanstallning, complex_social_case_timeline_redaction, easy_hr_job_application_summary, input_field_open_text_must_not_become_select, long_context_miljofarlig_verksamhet_documents_to_json, medium_school_absence_followup_json, simple_audio_minutes_actions
- current: advanced_explicit_change_log_analysis, advanced_explicit_integration_validation, advanced_explicit_lss_intake_contract, advanced_explicit_meeting_action_register, advanced_explicit_procurement_matrix, attachment_json_lokalkalkyl_budgetposter_saknat_belopp, attachment_json_protokoll_remissvar_datumkonflikt, attachment_json_remissvar_per_avsandare, attachment_pdf_report_remissvar_sammanstallning, complex_social_case_timeline_redaction, easy_hr_job_application_summary, file_role_discrimination_reference_material_criteria, hard_archive_retention_classification, input_field_open_text_must_not_become_select, input_field_required_and_optional_metadata, interview_input_citizen_feedback, long_context_miljofarlig_verksamhet_documents_to_json

Identity differences (expected between builds; an undeclared harness or corpus change would show here): ['source_revision']

## Remaining blockers (ranked, by distinct case)
- 3x proposal_parse_model
- 3x self_correction_invalid_payload

## Remaining failed checks (ranked, by distinct case)
- 9x expected_leaf_output_fields
- 4x expected_output_contract_schema
- 2x min_source_ref_steps
- 2x proposed_review_policy_target
- 2x question_relevance_complete
- 1x min_steps
- 1x expected_input_contract_schema
- 1x applied_review_policy_target
- 1x applied_expected_output_contract_schema
- 1x classifier_slot:terminal_output
- 1x classifier_file_role:file_index_0
- 1x plan_created

## Per-case transitions
- **advanced_explicit_change_log_analysis** [inconclusive] conformance pass -> fail; mechanics [unchanged] plan_repaired -> plan_repaired
  - baseline_observed_states: ["builder_error/not_evaluated", "plan_repaired/pass"]
  - current_observed_states: ["plan_first_pass/fail", "plan_repaired/fail"]
  - failed_checks: {"resolved": [], "introduced": ["expected_output_contract_schema"]}
  - authoring_tokens: {"before": 16548, "after": 25589, "delta": 9041}
  - repair_economics: {"before": {"repair_token_cost": 5946, "attempt_failure_codes": ["proposal_parse_model"]}, "after": {"repair_token_cost": 14172, "attempt_failure_codes": ["proposal_parse_model", "proposal_parse_model"]}, "delta": 8226}
- **advanced_explicit_integration_validation** [inconclusive] conformance fail -> fail; mechanics [improved] plan_repaired -> plan_first_pass
  - baseline_observed_states: ["plan_first_pass/fail", "plan_repaired/fail"]
  - current_observed_states: ["builder_error/not_evaluated", "plan_first_pass/fail"]
  - authoring_tokens: {"before": 13806, "after": 9036, "delta": -4770}
  - repair_economics: {"before": {"repair_token_cost": 4228, "attempt_failure_codes": ["proposal_parse_model"]}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": -4228}
- **advanced_explicit_lss_intake_contract** [inconclusive] conformance pass -> pass; mechanics [regressed] plan_first_pass -> plan_repaired
  - baseline_observed_states: ["plan_first_pass/fail", "plan_first_pass/pass"]
  - current_observed_states: ["plan_first_pass/pass", "plan_repaired/pass"]
  - authoring_tokens: {"before": 11644, "after": 15658, "delta": 4014}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 5226, "attempt_failure_codes": ["proposal_parse_model"]}, "delta": 5226}
- **advanced_explicit_meeting_action_register** [inconclusive] conformance pass -> fail; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - current_observed_states: ["plan_first_pass/fail", "plan_first_pass/pass", "plan_repaired/pass"]
  - failed_checks: {"resolved": [], "introduced": ["expected_output_contract_schema"]}
  - authoring_tokens: {"before": 9804, "after": 10393, "delta": 589}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **advanced_explicit_privacy_assessment** [unchanged] conformance pass -> pass; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - authoring_tokens: {"before": 10405, "after": 11348, "delta": 943}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **advanced_explicit_procurement_matrix** [inconclusive] conformance not_evaluated -> not_evaluated; mechanics [unchanged] builder_error -> builder_error
  - baseline_observed_states: ["builder_error/not_evaluated", "plan_repaired/pass"]
  - current_observed_states: ["builder_error/not_evaluated", "plan_first_pass/fail"]
  - authoring_tokens: {"before": 6745, "after": 6585, "delta": -160}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **advanced_explicit_retention_inventory** [inconclusive] conformance pass -> pass; mechanics [improved] plan_repaired -> plan_first_pass
  - baseline_observed_states: ["plan_first_pass/pass", "plan_repaired/pass"]
  - authoring_tokens: {"before": 20250, "after": 9492, "delta": -10758}
  - repair_economics: {"before": {"repair_token_cost": 9499, "attempt_failure_codes": ["proposal_parse_model", "proposal_parse_model"]}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": -9499}
- **advanced_sundsvall_tjansteskrivelse_runtime_sources_docx** [unchanged] conformance fail -> fail; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - authoring_tokens: {"before": 22471, "after": 21686, "delta": -785}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **attachment_json_lokalkalkyl_budgetposter_saknat_belopp** [inconclusive] conformance fail -> pass; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - baseline_observed_states: ["plan_first_pass/fail", "plan_first_pass/pass"]
  - current_observed_states: ["plan_first_pass/pass", "plan_repaired/pass"]
  - failed_checks: {"resolved": ["expected_output_contract_schema"], "introduced": []}
  - authoring_tokens: {"before": 10831, "after": 10320, "delta": -511}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **attachment_json_protokoll_remissvar_datumkonflikt** [inconclusive] conformance pass -> not_evaluated; mechanics [regressed] plan_repaired -> builder_error
  - baseline_observed_states: ["builder_error/not_evaluated", "plan_first_pass/fail", "plan_repaired/pass"]
  - current_observed_states: ["builder_error/not_evaluated", "plan_repaired/pass"]
  - failure_codes: {"resolved": [], "introduced": ["proposal_parse_model", "self_correction_invalid_payload"]}
  - authoring_tokens: {"before": 32526, "after": 9477, "delta": -23049}
  - repair_economics: {"before": {"repair_token_cost": 16803, "attempt_failure_codes": ["proposal_parse_model", "proposal_parse_model"]}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": -16803}
- **attachment_json_remissvar_per_avsandare** [inconclusive] conformance pass -> pass; mechanics [regressed] plan_first_pass -> plan_repaired
  - baseline_observed_states: ["plan_first_pass/fail", "plan_first_pass/pass"]
  - current_observed_states: ["plan_first_pass/fail", "plan_repaired/pass"]
  - authoring_tokens: {"before": 11700, "after": 16332, "delta": 4632}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 5163, "attempt_failure_codes": ["proposal_parse_model"]}, "delta": 5163}
- **attachment_pdf_report_ekonomisk_konsekvens_lokalkalkyl** [unchanged] conformance fail -> fail; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - failed_checks: {"resolved": [], "introduced": ["expected_leaf_output_fields"]}
  - authoring_tokens: {"before": 13233, "after": 12415, "delta": -818}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **attachment_pdf_report_exemplarform_kallgenomgang** [regressed] conformance pass -> fail; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - failed_checks: {"resolved": [], "introduced": ["expected_leaf_output_fields"]}
  - authoring_tokens: {"before": 17042, "after": 15884, "delta": -1158}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **attachment_pdf_report_remissvar_sammanstallning** [inconclusive] conformance pass -> fail; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - baseline_observed_states: ["plan_first_pass/fail", "plan_first_pass/pass"]
  - current_observed_states: ["plan_first_pass/fail", "plan_first_pass/pass"]
  - failed_checks: {"resolved": [], "introduced": ["expected_leaf_output_fields"]}
  - authoring_tokens: {"before": 16855, "after": 15580, "delta": -1275}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **complex_social_case_timeline_redaction** [inconclusive] conformance fail -> fail; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - baseline_observed_states: ["plan_first_pass/fail", "plan_first_pass/pass"]
  - current_observed_states: ["plan_first_pass/fail", "plan_first_pass/pass"]
  - failed_checks: {"resolved": ["min_json_steps", "min_source_ref_steps"], "introduced": []}
  - authoring_tokens: {"before": 11249, "after": 10916, "delta": -333}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **declared_terminal_everyday_fardtjanst_json** [unchanged] conformance fail -> fail; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - authoring_tokens: {"before": 10849, "after": 10095, "delta": -754}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **docx_template_fill_vague_mall_ifyllning_interview** [unchanged] conformance pass -> pass; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - authoring_tokens: {"before": 11560, "after": 10444, "delta": -1116}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **easy_hr_job_application_summary** [inconclusive] conformance pass -> pass; mechanics [unchanged] plan_repaired -> plan_repaired
  - baseline_observed_states: ["plan_first_pass/pass", "plan_repaired/pass"]
  - current_observed_states: ["plan_first_pass/pass", "plan_repaired/pass"]
  - authoring_tokens: {"before": 17562, "after": 27033, "delta": 9471}
  - repair_economics: {"before": {"repair_token_cost": 6464, "attempt_failure_codes": ["proposal_parse_model"]}, "after": {"repair_token_cost": 15309, "attempt_failure_codes": ["proposal_parse_model", "proposal_parse_model"]}, "delta": 8845}
- **easy_preschool_incident_note_json** [unchanged] conformance pass -> pass; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - authoring_tokens: {"before": 17547, "after": 17094, "delta": -453}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **file_role_discrimination_reference_material_criteria** [inconclusive] conformance pass -> pass; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - current_observed_states: ["plan_first_pass/pass", "plan_repaired/pass"]
  - authoring_tokens: {"before": 11724, "after": 10913, "delta": -811}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **hard_archive_retention_classification** [inconclusive] conformance fail -> pass; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - current_observed_states: ["plan_first_pass/pass", "plan_repaired/pass"]
  - failed_checks: {"resolved": ["min_steps"], "introduced": []}
  - authoring_tokens: {"before": 10790, "after": 12610, "delta": 1820}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **hard_municipal_company_board_packet** [unchanged] conformance fail -> fail; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - authoring_tokens: {"before": 16404, "after": 16825, "delta": 421}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **input_field_open_text_must_not_become_select** [inconclusive] conformance pass -> pass; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - baseline_observed_states: ["plan_first_pass/pass", "plan_repaired/pass"]
  - current_observed_states: ["plan_first_pass/pass", "plan_repaired/pass"]
  - authoring_tokens: {"before": 17866, "after": 17286, "delta": -580}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **input_field_required_and_optional_metadata** [inconclusive] conformance pass -> pass; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - current_observed_states: ["plan_first_pass/pass", "plan_repaired/pass"]
  - authoring_tokens: {"before": 18164, "after": 17430, "delta": -734}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **input_field_single_select_permit_case_type** [unchanged] conformance pass -> pass; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - authoring_tokens: {"before": 17010, "after": 17663, "delta": 653}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **interview_input_citizen_feedback** [inconclusive] conformance fail -> fail; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - current_observed_states: ["plan_first_pass/fail", "plan_first_pass/pass", "plan_repaired/pass"]
  - failed_checks: {"resolved": ["expected_question_event_count", "max_question_event_count", "question_relevance_complete"], "introduced": []}
  - questions: {"before": ["primary_runtime_input", "runtime_metadata_fields"], "after": ["primary_runtime_input"]}
  - authoring_tokens: {"before": 10123, "after": 10254, "delta": 131}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **interview_open_procurement_review** [unchanged] conformance pass -> pass; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - authoring_tokens: {"before": 12188, "after": 10919, "delta": -1269}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **long_context_miljofarlig_verksamhet_documents_to_json** [inconclusive] conformance fail -> fail; mechanics [regressed] plan_first_pass -> stalled_unanswered_question
  - baseline_observed_states: ["plan_first_pass/fail", "plan_first_pass/pass", "stalled_unanswered_question/fail"]
  - current_observed_states: ["plan_first_pass/pass", "stalled_unanswered_question/fail"]
  - failed_checks: {"resolved": ["min_source_ref_steps", "min_steps"], "introduced": ["plan_created"]}
  - questions: {"before": [], "after": ["comparison_scope"]}
  - authoring_tokens: {"before": 14353, "after": 8398, "delta": -5955}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **medium_decision_letter_template_attachment** [unchanged] conformance pass -> pass; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - authoring_tokens: {"before": 18706, "after": 17936, "delta": -770}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **medium_school_absence_followup_json** [inconclusive] conformance fail -> fail; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - baseline_observed_states: ["plan_first_pass/fail", "plan_repaired/fail"]
  - authoring_tokens: {"before": 11661, "after": 10931, "delta": -730}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **ordinary_json_lss_completeness** [unchanged] conformance pass -> pass; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - authoring_tokens: {"before": 10673, "after": 10212, "delta": -461}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **ordinary_json_security_incident** [unchanged] conformance pass -> pass; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - authoring_tokens: {"before": 10028, "after": 9489, "delta": -539}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **simple_audio_minutes_actions** [inconclusive] conformance pass -> pass; mechanics [unchanged] plan_repaired -> plan_repaired
  - baseline_observed_states: ["plan_first_pass/pass", "plan_repaired/pass"]
  - authoring_tokens: {"before": 14881, "after": 14996, "delta": 115}
  - repair_economics: {"before": {"repair_token_cost": 4782, "attempt_failure_codes": ["proposal_parse_model"]}, "after": {"repair_token_cost": 4973, "attempt_failure_codes": ["proposal_parse_model"]}, "delta": 191}
- **text_terminal_apt_avvikelsesammanfattning** [unchanged] conformance pass -> pass; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - authoring_tokens: {"before": 10851, "after": 9826, "delta": -1025}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
- **text_terminal_etjanst_svar_med_granskning** [unchanged] conformance fail -> fail; mechanics [unchanged] plan_first_pass -> plan_first_pass
  - authoring_tokens: {"before": 10193, "after": 9945, "delta": -248}
  - repair_economics: {"before": {"repair_token_cost": 0, "attempt_failure_codes": []}, "after": {"repair_token_cost": 0, "attempt_failure_codes": []}, "delta": 0}
