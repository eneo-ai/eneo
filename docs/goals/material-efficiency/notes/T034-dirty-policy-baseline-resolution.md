# T034 Receipt: Builder Policy Dirty Baseline Resolved

## TL;DR

- Classified the remaining dirty Flow AI Builder policy edits before starting any C3 work.
- The edits are a narrow T015 text-transform restraint cleanup, not C3 behavior.
- Removed redundant longer text-terminal phrases that were already covered by shorter phrases.
- Kept the boundary-matching comment in planner pattern signals because it documents the existing false-positive guard from T015.
- Verified the affected policy and planner-signal tests, Pyright, Ruff, and formatting.

## Problem

After T033, the next useful source-code target was C3 comparison/material-routing. Starting that work while related Flow AI Builder policy and pattern-signal files were dirty would make the C3 baseline ambiguous.

## Classification

| File | Dirty change | Classification |
|---|---|---|
| `backend/src/intric/flows/ai_builder/ai_builder_framework_policy.py` | Removes `"skriver ett kort svar"` and `"write a short answer"` from `_looks_like_text_terminal_output`. | In-scope cleanup for T015-style text-output inference. Behavior is still covered by `"kort svar"` / `"short answer"` and `"brief answer"`. |
| `backend/src/intric/flows/ai_builder/ai_builder_planner_pattern_signals.py` | Adds a short comment explaining boundary matching around direct text-transform markers. | In-scope readability note for the T015 false-positive guard. |
| `backend/tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py` | Changes the English short-answer test prompt to use `"brief answer"`. | Keeps explicit coverage for the remaining non-redundant marker. |
| `scripts/run_codex_review.sh` | Large unrelated wrapper changes. | Not part of this goal phase; left unstaged and uncommitted. |

## Verification

```bash
uv run --directory backend pytest -n 4 tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py tests/unittests/flows/ai_builder/test_ai_builder_planner_pattern_signals.py -q
# 78 passed

uv run --directory backend pyright src/intric/flows/ai_builder/ai_builder_framework_policy.py src/intric/flows/ai_builder/ai_builder_planner_pattern_signals.py tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py tests/unittests/flows/ai_builder/test_ai_builder_planner_pattern_signals.py
# 0 errors, 0 warnings, 0 informations

uv run --directory backend ruff check src/intric/flows/ai_builder/ai_builder_framework_policy.py src/intric/flows/ai_builder/ai_builder_planner_pattern_signals.py tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py tests/unittests/flows/ai_builder/test_ai_builder_planner_pattern_signals.py
# All checks passed

uv run --directory backend ruff format --check src/intric/flows/ai_builder/ai_builder_framework_policy.py src/intric/flows/ai_builder/ai_builder_planner_pattern_signals.py tests/unittests/flows/ai_builder/test_ai_builder_framework_policy.py tests/unittests/flows/ai_builder/test_ai_builder_planner_pattern_signals.py
# 4 files already formatted
```

## Outcome

The Flow AI Builder policy/pattern baseline is now safe to commit independently from the next C3 comparison/material-routing slice. The unrelated `scripts/run_codex_review.sh` changes and untracked docs/media remain outside this phase.

Peer review: `[no-peer-review]` This is a small cleanup/classification phase over already-dirty T015 files with no new behavior path, verified by the affected test files, Pyright, Ruff, and format checks. It does not choose or implement the next C3 architecture slice.

Confidence: high.
