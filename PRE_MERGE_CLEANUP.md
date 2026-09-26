# Pre-merge cleanup (refactor/flows-tidy-ai-builder → develop)

This branch carries program and measurement material that helped build the Flow AI Builder but does not belong
in `develop` as-is. Before opening the merge PR, resolve every row below: remove it, or record the decision to
keep it (and where it moves). Agents: flag any PR from this branch that still contains a "Remove" path.

Check what is still present:

```bash
git ls-files -- PRE_MERGE_CLEANUP.md .beads docs/goals VERIFICATION-HANDOFF.md \
  'backend/scripts/ai_builder_*' backend/scripts/fixtures/ai_builder_battle \
  backend/scripts/check_flow_run_evidence_acceptance.py scripts/gate-local \
  'backend/tests/unittests/flows/ai_builder/test_ai_builder_api_battle_harness.py' \
  'backend/tests/unittests/flows/ai_builder/test_ai_builder_battle_*' \
  'backend/tests/unittests/flows/ai_builder/test_ai_builder_edit_capability.py' \
  'backend/tests/unittests/flows/ai_builder/test_ai_builder_edit_expectation.py' \
  'backend/tests/unittests/flows/ai_builder/test_ai_builder_release_gate.py' | awk -F/ '{print $1"/"$2"/"$3}' | sort | uniq -c
```

## Remove (program tracking, not product)

| Path | What it is |
|---|---|
| `PRE_MERGE_CLEANUP.md` | This file. |
| `.beads/` | The Beads issue board used to run the program. |
| `docs/goals/` (`eneo-flows-and-builder-9-of-10/`, `flows-scale/`) | Program goals, state and measurement receipts. |
| `VERIFICATION-HANDOFF.md` | A session handoff note. |
| `backend/scripts/ai_builder_release_matrix_state.json`, `backend/scripts/ai_builder_token_baseline_r17.json` | Stored measurement state. |
| `scripts/gate-local/` | Local gate helpers for the program. |

## Decide: the Builder benchmark (measurement tooling)

The benchmark measures the Builder end to end against a live stack (create and edit cases, executed output,
preservation). It found real product defects on 2026-09-26. Either keep it as supported dev tooling, moved under
one directory (for example `backend/tools/builder_benchmark/`) with a README, or remove it and keep it in a
separate repository.

| Path | Notes |
|---|---|
| `backend/scripts/ai_builder_api_battle_test.py`, `ai_builder_receipt.py`, `ai_builder_release_gate.py`, `ai_builder_battle_compare.py`, `ai_builder_edit_expectation.py`, `ai_builder_edit_capability.py` (+ `_manifest.json`) | The harness and its gates. |
| `backend/scripts/ai_builder_*_cases.json`, `backend/scripts/fixtures/ai_builder_battle/` | Case corpora and fixtures. |
| `backend/scripts/ai_builder_failure_summary.py` | Referenced by the docs-site `ai-builder.mdx`; update the page if it goes. |
| `backend/scripts/check_flow_run_evidence_acceptance.py` | Evidence acceptance checker. |
| `backend/tests/unittests/flows/ai_builder/test_ai_builder_api_battle_harness.py`, `test_ai_builder_battle_*`, `test_ai_builder_edit_capability.py`, `test_ai_builder_edit_expectation.py`, `test_ai_builder_release_gate.py` | Tests of the tooling; they follow the tooling's decision. |

## Keep (product tooling; verify, then delete this section)

`backend/scripts/generate_flow_api_error_codes_ts.py`, `generate_flow_run_reserved_input_payload_keys_ts.py`,
`generate_flow_run_status_capabilities_ts.py`, `flow_sdk_codegen.py` (generated-client owners that contract tests
check) and `build_standard_docx_templates.py` (documented in `docs/flows/flow-developer-quickstart.md`).

## Review, probably keep

`docs/engineering/*`, `docs/flows/*`, `docs/design/ai-builder/*`, `docs/adr/*`, `docs/runbooks/flows.md` and the
docs-site pages: product and engineering documentation, reviewed with the usual docs rules in `AGENTS.md`.

## Never in any PR (outside the repository)

The coding-agent workflow lives outside this repository and needs no cleanup here: `~/.claude/skills/*`
(landing, gate and benchmark scripts), `~/dev/eneo/demo-stack/` (stacks, receipts, specs, secrets) and
`.codex/artifacts/` (gitignored review artifacts).
