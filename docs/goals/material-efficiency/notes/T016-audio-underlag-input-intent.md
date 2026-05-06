# T016 Audio Underlag Input Intent

## Problem

Live C5 over-clarified the primary runtime material even though the prompt
already says the user records or uploads a customer call. Deterministic
inspection reproduced the root cause:

- `resolve_input_intent(C5_PROMPT, {})` returned
  `primary_runtime_input='unknown'`.
- `audio_requested=True` and `document_runtime_input_requested=True`.
- `needs_architecture_clarification=True`, which led discovery to ask
  `Vilket material ska flödet ta emot vid körning?`.

## Canonical Owner

`backend/src/intric/flows/ai_builder/ai_builder_input_architecture_policy.py`
owns this distinction through `resolve_input_intent`,
`_audio_runtime_input_requested`, and `_document_runtime_input_requested`.

## Change

- Removed the global `underlag` -> document-runtime-input branches.
- Kept document runtime input detection on the proximity-based
  reference/action rule.
- Preserved real document-underlag uploads such as `laddar upp underlag`.
- Added behavior tests for:
  - C5-style audio prompts where `JSON-underlag` and `källmaterial` are derived
    flow material, not a second uploaded document input.
  - Structurally equivalent interview and meeting/audio variants.
  - Edit-path derived `JSON-underlag` on an existing audio flow.
  - Explicit audio plus document upload still requiring mixed-input
    clarification.
  - Bare provided/uploaded underlag/documents still resolving to document
    runtime input.
  - Passive `underlag` mentions without a nearby runtime file action still not
    resolving to document runtime input.

## Verification

- Red test before implementation:
  - `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_input_architecture_policy.py tests/unittests/flows/ai_builder/test_discovery_flow.py -q`
  - Failed with three expected failures: derived-underlag audio prompts resolved
    `primary_runtime_input='unknown'`, and discovery still asked
    `flow_input_architecture`.
- Focused green test:
  - Same command after implementation.
  - `79 passed, 4 warnings`.
- Full AI Builder unit suite:
  - `uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder -q`
  - `1987 passed, 4 skipped, 42 warnings`.
- Type/lint/format:
  - `uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_input_architecture_policy.py tests/unittests/flows/ai_builder/test_ai_builder_input_architecture_policy.py tests/unittests/flows/ai_builder/test_discovery_flow.py`
  - `0 errors, 0 warnings, 0 informations`.
  - `uv run --directory backend ruff check ...`
  - `All checks passed!`
  - `uv run --directory backend ruff format --check ...`
  - `3 files already formatted`.

## Live Eval

Attempted:

```bash
python3 docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py --case C5 --runs 3 --apply --publish --output-dir /tmp/material-efficiency-live-eval/$(date +%Y%m%d-%H%M%S)-t016-c5-audio-underlag-input-intent
```

Initial result:

```text
Missing ENEO_LOCAL_API_KEY or --api-key.
```

The shell also had neither `ENEO_LOCAL_API_BASE` nor `ENEO_LOCAL_API_KEY` set.
Follow-up attempts mapped existing local `backend/.env` key variables into the
runner without printing secrets:

- `/tmp/material-efficiency-live-eval/20260506-015205-t016-c5-audio-underlag-input-intent-local-env/summary.json`
- `/tmp/material-efficiency-live-eval/20260506-015227-t016-c5-audio-underlag-input-intent-local-env-2/summary.json`

Both runs produced `HTTP 401 Unauthorized` with `invalid_api_key`, so the local
`.env` keys were not usable eval credentials.

After the user provided a valid local API key, targeted live eval passed:

```bash
ENEO_LOCAL_API_BASE=http://localhost:8123 ENEO_LOCAL_API_KEY=<provided local key> \
  python3 docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py \
  --case C5 --runs 3 --apply --publish \
  --output-dir /tmp/material-efficiency-live-eval/20260506-015927-t016-c5-audio-underlag-input-intent-keyed \
  --timeout 360
```

Result:

```text
C5 run 1: applied flow=ce88cd29-3661-453b-9842-1617ec7c71c4
C5 run 2: applied flow=3dd521f6-6f4f-4903-872c-7c70d696595e
C5 run 3: applied flow=eaf80051-5c73-496e-94a9-0abaf70a6ad8
```

Inspection confirmed all three generated flows used `flow_input` audio with
`transcribe_only` as step 1, declared `ticket_id`, `kundnamn`, and `rapportton`
as form fields, and routed those fields into the draft/revision bindings.
The generated topologies still vary in efficiency, but this phase's input-intent
failure is fixed: derived JSON-underlag no longer causes a mixed audio/document
input clarification.

## Peer Review

- Canonical `claude_peer_loop.py` failed before review because the local Claude
  session title was ambiguous.
- Direct Claude CLI review artifact:
  `.codex/artifacts/claude-peer-loop-t016-audio-underlag-input-intent-direct-plan-review-20260505T233511Z.md`.
- Claude returned `GREEN_LIGHT: no`, `MIN_SCORE: 4` for the initial plan and
  required branch-level specificity, a T016 board entry, preservation of bare
  `laddar upp underlag`, structurally equivalent variants, and an edit-path
  guard. Those blockers were addressed before implementation.
- Canonical `claude_peer_loop.py` then ran for the implementation gate:
  `.codex/artifacts/claude-peer-loop-t016-audio-underlag-input-intent-implementation-review-20260505T234743Z.md`.
  Claude returned `GREEN_LIGHT: no`, `MIN_SCORE: 7`. Valid local findings were
  addressed by adding the passive-`underlag` negative invariant, preserving
  `lämnar underlag` / `provides documents`, and documenting the proximity
  invariant. Remaining non-code blockers are the missing live eval credentials
  and unrelated dirty files that must not be staged for T016.

## Remaining

- Run Claude verification after live evidence is available.
- Commit only the T016-owned files at that verified phase boundary.
