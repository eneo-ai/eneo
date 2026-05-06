# T027 Judge Next Worker

## Decision

Activate T028 for E1 edit-path malformed `add_payload.output_fields` normalization.

## Why This Slice

E1 has a concrete live failure: `self_correction_invalid_payload` from strict `FlowEditDraft` parsing when an added step declares nested `field_type="object"` fields without child `fields`.

C3 remains a topology/material-routing quality concern, but it applied in the available live runs and does not yet have a falsifiable backend invariant for a small Worker.

The E1 run-1 HTTP 500 is explicitly out of scope because no local stack trace ties `error_id a4ebb454` to the same output-field parse path.

## Canonical Owner Decision

The create path already has loose structured-field coercion, but it is private to `ai_builder_create_outline.py`. The next Worker must extract that logic into one shared owner:

- `backend/src/intric/flows/ai_builder/ai_builder_structured_field_normalizer.py`

Both create-outline parsing and edit pre-parse normalization should import from that owner. `StructuredFieldDraft` remains strict.

## Claude Review

Claude required three iterations:

- `.codex/artifacts/claude-peer-loop-t027-judge-next-worker-20260506T022026Z.md`: changes required; make extraction mandatory.
- `.codex/artifacts/claude-peer-loop-t027-judge-next-worker-revised-20260506T022404Z.md`: changes required; remove compatibility wrapper, add idempotency/create-path/patch tests, avoid hardcoded live flow ID.
- `.codex/artifacts/claude-peer-loop-t027-judge-next-worker-final-20260506T022650Z.md`: `GREEN_LIGHT: yes`, `MIN_SCORE: 8`.

## Selected Worker

T028 should extract the shared structured-field normalizer, rename the edit loose-argument normalizer without compatibility wrappers, add behavior tests, then rerun local verification and a create-then-edit live E1 confidence check.
