# Prompt: make the 122-case harness and comparator a trustworthy instrument

Improve the AI Builder measurement instrument so that every future change
to the Flow AI Builder can be judged against a baseline — real
improvements confirmed, regressions caught, noise not mistaken for either.
**You are improving the instrument, not the product.** Do not change
builder, compiler, or planning code in this work.

## Files you own

- `backend/scripts/ai_builder_api_battle_test.py` — the harness. Runs
  cases against a live backend, classifies each observation, writes
  `suite-summary.json` receipts.
- `backend/scripts/ai_builder_api_battle_cases.json` — the 122-case corpus
  (`{version, description, synthetic_user_profiles, release_gate, cases}`).
- `backend/scripts/ai_builder_battle_compare.py` — compares two receipts,
  decides direction, ranks remaining blockers.
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_api_battle_harness.py`
- `backend/tests/unittests/flows/ai_builder/test_ai_builder_battle_compare.py`
  (31 tests)

Read `docs/goals/eneo-flows-and-builder-9-of-10/notes/conformance-program-plan.md`
first. It is the authority on what the metrics mean and why. In
particular: `expectation_verdict` (does the plan satisfy the case) is the
primary metric; `outcome_class` (how the proposal was produced) is
mechanics. Never report one as the other.

## Ground truth you must not re-derive

Verified on the current corpus and the 9d4237a/9216ec6 receipts:

- Conformance is ~39/122. `expected_leaf_output_fields` is the dominant
  failing check (41 distinct cases).
- Terminal output types: json 34, pdf 24, text 9, docx 4, unspecified 51.
- **Only 5 of 122 cases attach files**, and each one resolves its file ids
  from environment variables
  (`ENEO_AI_BUILDER_DOCX_TEMPLATE_FILE_ID` and similar) pointing at blobs
  someone uploaded by hand into a live space. There is no fixture corpus
  in the repository. This is the bottleneck for any file-upload expansion:
  forty more cases would mean forty more hand-provisioned env vars, and
  the corpus would stop being reproducible.
- A full 122-case pass takes ~48 minutes against the devcontainer backend.

## What to work on

Judge these yourself against the evidence; the order below is a starting
hypothesis, not a ranking to obey.

1. **Reproducible fixtures.** Design one canonical way for a case to
   declare the file it needs and have it provisioned deterministically, so
   file-bearing cases are portable and a fresh environment can run the
   suite. This unblocks everything else in this list.
2. **More coverage where the evidence says it is thin** — file-bearing
   journeys, the 51 cases with no declared terminal type, terminal types
   with 4 and 9 cases. New cases must be realistic Swedish municipal work
   (Sundsvalls kommun and comparable authorities): genuine document types,
   genuine Swedish wording, invented names, addresses, case numbers, and
   people. Never real personal data.
3. **Baseline tracking that survives a change.** The comparator must make
   "did this change help, hurt, or do nothing measurable" answerable per
   change. Consider what is missing today for that to be routine.
4. **Cost.** 48 minutes per pass shapes how often anyone measures. If
   that can come down without weakening the evidence, it is worth as much
   as new cases.

## Rules

- **Never guess or assume your way forward.** If the evidence does not
  settle a question — what a check means, whether a case's expectation is
  valid, how a fixture is provisioned — find out from the source, or stop
  and say what you could not determine. `undetermined` is an acceptable
  answer; an invented one is not. Do not infer a mechanism from a name.
- **Long-term maintainable, clean solutions.** One canonical owner per
  concern. Before adding a path, check whether an existing one can be
  deepened, moved, or deleted. Prefer deleting a rule to adding one. The
  product is prerelease with zero users: no backwards compatibility, no
  migration scaffolding, no feature flags.
- **Never weaken an expectation because the model fails it.** A case may
  be corrected only by an argument from what the product actually
  guarantees, and the justification goes in the attribution artifact, not
  in the cases JSON.
- **A new case must be able to fail.** A case that passes on day one
  because it asks for nothing measurable is worse than no case.
- Do not change scoring semantics without bumping the matching
  `*_SEMANTICS_VERSION` — the comparator refuses receipts across a
  version change, and that refusal is the safety net.
- Secrets (`ENEO_API_KEY`, `ENEO_SPACE_ID`) never enter the repository.
  They live in `/tmp/eneo-battle-key` inside the devcontainer.
- Do not stage the user's protected working files (`.devcontainer/`,
  `goal.md`, `notes/handoff.md`, `notes/hermes-*`, `state.yaml`,
  `frontend/package.json`, `SolReview/`).

## How to run it

Inside the devcontainer (`developz_devcontainer-eneo-1`), against a
backend whose `/version` matches the local HEAD:

```bash
cd /workspace/backend && source /tmp/eneo-battle-key && .venv/bin/python \
  /tmp/eneo-clean/backend/scripts/ai_builder_api_battle_test.py \
  --base-url http://localhost:8123/api/v1 --run-suite --repetitions 1 \
  --ui-language sv --model-id 90824b05-9913-4210-968f-9294eb017d31 \
  --output-dir /workspace/.codex/artifacts/<label>
```

`--base-url` must end in `/api/v1`; the harness verifies `/version`
against the local source revision and refuses otherwise. Compare two
receipts with `ai_builder_battle_compare.py BASELINE CURRENT`.

## Definition of done

`uv run pytest tests/unittests/flows/ -q` green, `ruff check` /
`ruff format --check` and `pyright --pythonpath .venv/bin/python` clean on
the exact changed paths, and one full 122-case run showing the corpus
still executes end to end. State plainly what you changed, what you
measured, and what you could not determine.
