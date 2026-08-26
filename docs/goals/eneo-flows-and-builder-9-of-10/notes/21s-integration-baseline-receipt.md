# 2.1-S integration adjudication receipt (frozen 2026-08-25 20:12 CEST)

Trees: candidate = /private/tmp/eneo-worker-21s at 170ef38ff6aa748ad7b6bbafee31eee2d099d5fc
plus the staged 2.1-S diff (sha256 of git diff --cached at adjudication
time recorded below; the diff lands as the next commit on
measure/21s-chain, which becomes the durable identity); base = /private/tmp/eneo-21-candidate at the
same 170ef38ff, clean. Command form for every run:

    export PYTHONPATH=<tree>/backend/src
    set -a; source /Users/ccimen/eneo/eneo-flows-clean/backend/.env; set +a
    <tree>/backend/.venv/bin/python -m pytest <nodeids> -q

Both runs used the same command form: pytest with the shared test env
(eneo-flows-clean backend/.env) and tree-local PYTHONPATH.

## Candidate tree: /private/tmp/eneo-worker-21s (170ef38ff + staged 2.1-S)

Full tests/integration/flows run (20:28 min): 11 failed, 412 passed.
Focused rerun (session file + 2 named): 9 failed, 103 passed (4:25).
Failing nodeids (candidate):
- tests/integration/flows/test_ai_builder_session_api_regressions.py::test_ai_builder_same_turn_key_replays_without_provider_or_duplicates
- tests/integration/flows/test_ai_builder_session_api_regressions.py::test_ai_builder_disconnect_after_committed_event_replays_without_provider
- tests/integration/flows/test_ai_builder_session_api_regressions.py::test_ai_builder_latest_turn_replay_and_conflict_survive_compaction
- tests/integration/flows/test_ai_builder_session_api_regressions.py::test_ai_builder_same_turn_key_rejects_different_request_before_provider
- tests/integration/flows/test_ai_builder_session_api_regressions.py::test_ai_builder_api_does_not_repeat_report_disposition_after_structured_answer
- tests/integration/flows/test_ai_builder_session_api_regressions.py::test_ai_builder_api_repeated_output_question_after_freeform_label_recovers_without_internal_error
- tests/integration/flows/test_ai_builder_session_api_regressions.py::test_ai_builder_api_named_content_fields_can_be_edited_on_the_card
- tests/integration/flows/test_flow_consumer_api_contract.py::test_flow_runtime_file_delete_rejects_attached_run_input
- tests/integration/flows/test_flow_consumer_api_contract.py::test_flow_runtime_file_delete_hides_other_principal_attached_file
- tests/integration/flows/test_flow_run_listing_and_evidence_measurement.py::test_flow_run_listing_and_evidence_measurement_contract
- tests/integration/flows/test_flow_run_repository.py::test_provenance_measurement_and_bounded_attempt_read

## Base tree: /private/tmp/eneo-21-candidate (CLEAN 170ef38ff, no diff)

Run A (session file + delete-rejects + provenance-read; 4:25):
3 failed, 109 passed. Failing nodeids (base):
- tests/integration/flows/test_ai_builder_session_api_regressions.py::test_ai_builder_api_does_not_repeat_report_disposition_after_structured_answer
- tests/integration/flows/test_flow_consumer_api_contract.py::test_flow_runtime_file_delete_rejects_attached_run_input
- tests/integration/flows/test_flow_run_repository.py::test_provenance_measurement_and_bounded_attempt_read

Run B (the two remaining unknowns; 21s): 2 failed:
- tests/integration/flows/test_flow_consumer_api_contract.py::test_flow_runtime_file_delete_hides_other_principal_attached_file
- tests/integration/flows/test_flow_run_listing_and_evidence_measurement.py::test_flow_run_listing_and_evidence_measurement_contract

## Adjudication

Base ∩ candidate = the 5 residual failures (pre-existing at
170ef38ff, untouched by the 2.1-S diff). Candidate-only = the 6
session-API failures, all 2.1-S-caused, fixed in pass 3 (session file
now 109 passed / 1 pre-existing failure — verified independently by
the orchestrator, 5:20 run).

Result lines, verbatim:
- candidate full tests/integration/flows: `11 failed, 412 passed in 1228.16s`
- candidate focused (session file + 2 named): `9 failed, 103 passed in 265.38s`
- base run A (session file + delete-rejects + provenance-read):
  `3 failed, 109 passed in 265.77s`
- base run B (delete-hides + listing-measurement): `2 failed in 21.08s`
- candidate session file after pass-3 fixes (orchestrator rerun):
  `1 failed, 109 passed in 320.81s` — sole failure the pre-existing
  test_ai_builder_api_does_not_repeat_report_disposition_after_structured_answer
- candidate session file after pass-4 ingestion change (orchestrator rerun):
  `1 failed, 109 passed in 332.35s` — same sole failure


Candidate identity: sha256 of the staged diff EXCLUDING this receipt
(command: git diff --cached -- ':!docs/goals/eneo-flows-and-builder-9-of-10/notes/21s-integration-baseline-receipt.md' | shasum -a 256),
taken at commit time (owner-directed close of the gate loop): 3e7ea20c333ac78d7d7cd6dfcb11c12b3919773a1d0fb7e73a1399b340cce08f
The enclosing commit on measure/21s-chain is the durable identity.
