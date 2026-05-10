# T005 Judge Next Slice

Select `P0-review-edit-contract-validation`.

Reason: it is the highest-ROI safe next step because it closes an API-visible human-review contract gap, unblocks the public API golden journey, and has a direct DB/API red test. The canonical owner is `FlowRunService.edit_review_checkpoint` validating with `output_processing.validate_against_contract` before `FlowRunRepository` persists checkpoint and step-result projection changes. No new validator, wrapper service, or repository-owned schema validation should be added.

Claude plan gate is not required now because ownership, error-code reuse, allowed files, and red-test harness are concrete. Claude commit gate remains required before committing the Worker result.
