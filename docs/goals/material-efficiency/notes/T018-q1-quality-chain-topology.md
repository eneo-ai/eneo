# T018 Quality-Chain Topology Decision

## Decision

Proceed with a narrow Worker slice in
`backend/src/intric/flows/ai_builder/ai_builder_critic_invariants.py`: add a
topology-only semantic invariant that rejects an unrequested terminal JSON-format
tail after a final text composer.

## Why This Owner

The gap is not prompt wording, skeleton generation, or a special Q1 case. The
bad and good plans differ only in `FlowDraftSpecCore` topology:

- Accepted topology: text draft -> JSON critique -> final text.
- Rejected topology: text draft -> JSON critique -> final text -> JSON wrapper,
  optionally followed by a text unwrap.

`ai_builder_critic_invariants.py` already owns semantic topology guards such as
targeted underlag fan-in and final text composer structured-output references.
That registry is therefore the canonical owner for a general shape check over a
compiled draft.

## Constraints

- Do not use Q1 wording, Swedish/English prompt terms, or
  `PlannerPatternSignals.prefers_quality_step`.
- Do not collapse an explicit text -> JSON critique -> text revision chain.
- Do not reject explicit structured JSON terminal output.
- Do not reject DOCX/PDF/template renderer output.
- Do not reject JSON output driven by runtime form fields.
- Do not reject aggregate/compare topologies.
- Keep create-mode remediation in the existing
  `ai_builder_create_feedback.py` owner so every semantic invariant remains
  repairable through create-plan feedback.

## Acceptance Criteria

- A 4-step or 5-step terminal JSON tail after a final text composer emits the new
  semantic issue.
- A 3-step quality chain remains accepted.
- Explicit JSON terminal, document renderer, form-field-driven JSON, and
  aggregate/compare cases remain accepted.
- The more specific redundant-tail invariant takes precedence over
  `final_text_step_must_reference_relevant_structured_outputs`.
- Live supplemental Q1 no longer produces the redundant tail in repeated runs.

## Verification

- `.codex/artifacts/claude-peer-loop-t018-q1-quality-chain-topology-judge-20260506T000051Z.md`
- `.codex/artifacts/claude-peer-loop-t018-topology-only-redundant-json-tail-judge-revision-20260506T000405Z.md`
