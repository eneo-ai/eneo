# T037 Judge Receipt: C2 Repair Feedback Preservation

## Result

Activated Worker T038.

## Evidence

- Targeted C2 live eval:
  `/tmp/material-efficiency-live-eval/20260506-065712-t036-c2-regression-check/summary.json`
  failed `2/2` with `self_correction_invalid_plan`.
- Public C2 artifacts had no plan and no concrete validation feedback after
  requirements confirmation.
- `ai_builder_proposal_repair.py` logs forced-tool retry validation feedback but
  returns `None`, so `request_self_correction` emits a feedback-less
  `self_correction_invalid_plan` event.
- `ai_builder_proposal_processor.py` already appends feedback when the repair
  helper provides it, so the feedback loss is at the proposal-repair boundary.

## Decision

T038 should preserve forced-tool retry feedback through a typed repair outcome
before any C2-specific validator fix. That gives live evals and API clients the
actual sanitized failure reason for C2 and future invalid-plan failures.

## Worker Scope

- Add a typed forced-tool retry outcome in `ai_builder_proposal_repair.py`.
- Preserve validation feedback for both forced tool-call failures and JSON-text
  fallback failures.
- Keep `retry_forced_proposal_after_text` returning `EventBatch | None` by
  translating the typed outcome at the wrapper boundary.
- Do not tune C2 generation behavior in this slice.

## Claude Review

- Initial plan gate:
  `.codex/artifacts/claude-peer-loop-t037-judge-c2-repair-feedback-20260506T051932Z.md`
  returned `changes_required`.
- Revised plan gate:
  `.codex/artifacts/claude-peer-loop-t037-revised-judge-c2-repair-feedback-20260506T052337Z.md`
  returned `GREEN_LIGHT: yes` with `MIN_SCORE: 8`.

## Acceptance Criteria

- Red tests prove the current feedback loss.
- Unit tests cover forced-tool validation feedback, JSON-text fallback feedback,
  invalid forced JSON parse feedback, information-request no-feedback behavior,
  architecture-error event preservation, and wrapper return-shape preservation.
- C2 live eval is rerun after the code change. If C2 still fails, the artifact
  must include concrete validation or parse feedback after the generic
  self-correction prefix.
