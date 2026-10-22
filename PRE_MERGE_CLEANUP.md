# Pre-merge cleanup (feat/flows-core-integration → develop)

This branch still carries program material from building the flow core that does not belong in `develop` as-is.
Before opening the merge PR, resolve every row below: remove it, or record the decision to keep it (and where it
moves). The AI Builder, its benchmark tooling, its goal notes and its handoff note are already gone.

Check what is still present:

```bash
git ls-files -- PRE_MERGE_CLEANUP.md .beads docs/goals \
  backend/scripts/check_flow_run_evidence_acceptance.py \
  backend/tests/unittests/flows/test_flow_run_evidence_acceptance_script.py \
  | awk -F/ '{print $1"/"$2"/"$3}' | sort | uniq -c
```

## Remove (program tracking, not product)

| Path | What it is |
|---|---|
| `PRE_MERGE_CLEANUP.md` | This file. |
| `.beads/` | The Beads issue board used to run the program. |
| `docs/goals/flows-scale/` | A measurement receipt of the flow scale work. |

## Decide: the evidence acceptance checker

| Path | Notes |
|---|---|
| `backend/scripts/check_flow_run_evidence_acceptance.py` (+ `backend/tests/unittests/flows/test_flow_run_evidence_acceptance_script.py`) | Checks a run's evidence export against the acceptance rules. Keep it as supported dev tooling with a note in `docs/flows/`, or remove it with its test. |

## Keep (product tooling; verify, then delete this section)

`backend/scripts/generate_flow_api_error_codes_ts.py`, `generate_flow_run_reserved_input_payload_keys_ts.py`,
`generate_flow_run_status_capabilities_ts.py`, `flow_sdk_codegen.py` (generated-client owners that contract tests
check) and `build_standard_docx_templates.py` (documented in `docs/flows/flow-developer-quickstart.md`).

## Review, probably keep

`docs/engineering/*`, `docs/flows/*`, `docs/adr/*`, `docs/runbooks/flows.md` and the docs-site pages: product and
engineering documentation, reviewed with the usual docs rules in `AGENTS.md`.

## Never in any PR (outside the repository)

The coding-agent workflow lives outside this repository and needs no cleanup here: `~/.claude/skills/*`
(landing, gate and benchmark scripts), `~/dev/eneo/demo-stack/` (stacks, receipts, specs, secrets) and
`.codex/artifacts/` (gitignored review artifacts).
