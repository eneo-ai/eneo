# Flow Runtime API Consumer Contract Hardening Packet

Date: 2026-06-28

## TL;DR

Gate 0 found route, status, operation-id, runtime-path, and OpenAPI drift already protected by existing registry contract tests.
The real gap was docs-catalog completeness: consumer docs could reference valid endpoints without proving every runtime endpoint contract was mentioned somewhere consumer-facing.
`export_flow_run_evidence` was already covered by the typed FAQ pitfall matrix, so no duplicate docs were added for it.
The implementation adds docs coverage for `get_published_flow_runtime`, `cancel_flow_run`, and `redispatch_flow_run`.
A new guard now fails if any `FLOW_RUNTIME_ENDPOINT_CONTRACTS` operation ID is absent from endpoint sequences, worked examples, or typed pitfall rows.

## Gate Results

| Gate | Result | Source |
|---|---|---|
| Gate 0 endpoint registry coverage | FastAPI route/method/status/operation-id coverage already exists; docs coverage missed three operation IDs | `docs/flows/flow-runtime-api-contract-gate0.md` |
| Gate 1 API consumer journey | Runtime consumer path is already documented across designing/integrating/FAQ guides; cancellation and redispatch needed explicit robustness coverage | `backend/scripts/flow_consumer_integrating_flows_docs.py` |
| Gate 2 JSONB decision | No runtime JSONB field needed relationalization for this docs-contract slice | `docs/flows/flow-runtime-api-contract-gate0.md` |

## Chosen Lane

Lane A, narrowed to consumer docs/catalog drift:

- reuse `FLOW_RUNTIME_ENDPOINT_CONTRACTS` as the runtime endpoint source of truth;
- reuse existing docs catalog types instead of adding a second registry classification;
- count all typed consumer docs surfaces: endpoint sequences, worked examples, and pitfall rows;
- add the missing three endpoint mentions at their natural docs homes;
- regenerate docs-site guide pages.

## What Changed

| Area | Change |
|---|---|
| Docs support | Added `documented_consumer_operation_ids(...)` to compute the typed docs coverage surface from existing sequences, worked examples, and pitfall rows |
| Docs contract test | Added a guard that every runtime endpoint operation ID is covered by consumer docs |
| Designing guide source | Added the published runtime endpoint to the published-contract discovery sequence |
| Integrating guide source | Added cancellation and redispatch to the robustness sequence with endpoint-specific receipts |
| FAQ guide source | Added an empty worked-example tuple so all guide modules expose the same coverage attribute |
| Docs-site output | Regenerated `designing-flows.mdx` and `integrating-flows.mdx` |

## What Was Deliberately Not Changed

| Non-goal | Reason |
|---|---|
| Runtime behavior | The gap was docs-contract coverage, not route/service behavior |
| FastAPI route shape or OpenAPI schemas | Existing tests already proved route/OpenAPI alignment |
| Generated TypeScript client | Schema drift check passed without client changes |
| JSONB persistence | Gate 2 found no query/FK/lifecycle need for this slice |
| Registry `doc_depth` field | Docs intent belongs in the typed docs catalogs; adding 21 registry classifications would duplicate ownership |
| New docs abstraction | Existing `EndpointSequence`, `WorkedExampleHop`, and `EndpointPitfallRow` were enough |

## Red-Green Proof

The new docs-completeness test failed before docs catalog updates with exactly:

```text
get_published_flow_runtime
cancel_flow_run
redispatch_flow_run
```

After adding those docs entries, the same test passed.

## Validation Results

| Command | Result |
|---|---|
| `uv run pytest tests/unittests/flows/test_flow_docs_site_contract.py::test_flow_consumer_docs_cover_every_runtime_endpoint_contract` before docs changes | failed with the three missing operation IDs |
| `make docs:regen` | passed; regenerated Flow docs-site pages |
| `uv run pytest tests/unittests/flows/test_flow_docs_site_contract.py` | passed, 69 tests |
| `uv run pytest tests/unittests/flows/test_flow_router_crud.py::test_get_published_flow_runtime_returns_runtime_projection_for_human_reader tests/unittests/flows/test_flow_run_execution_router.py::test_cancel_flow_run_uses_terminalizer_audit_only tests/unittests/flows/test_flow_run_execution_router.py::test_redispatch_flow_run_uses_run_scoped_dispatch_and_audits` | passed, 3 tests |
| `uv run ruff check scripts/flow_consumer_designing_flows_docs.py scripts/flow_consumer_faq_docs.py scripts/flow_consumer_guide_support.py scripts/flow_consumer_integrating_flows_docs.py tests/unittests/flows/test_flow_docs_site_contract.py` | passed |
| `uv run pyright scripts/flow_consumer_designing_flows_docs.py scripts/flow_consumer_faq_docs.py scripts/flow_consumer_guide_support.py scripts/flow_consumer_integrating_flows_docs.py tests/unittests/flows/test_flow_docs_site_contract.py` | passed |
| `PYTHONPATH=scripts python3 -c "from pathlib import Path; from pre_push_check import run_schema_drift_check; run_schema_drift_check(Path.cwd())"` | passed |
| `uv run pyright` | passed |
| `uv run lint-imports --no-cache` | passed |
| Claude peer loop commit gate | passed with `GREEN_LIGHT: yes`, `MIN_SCORE: 8` |

## Remaining Production-Readiness Gaps

| Gap | Why it remains | Recommended next action |
|---|---|---|
| Single full integration golden journey | Existing tests cover endpoint receipts and critical paths, but not one single upload-run-review-resume-artifact-evidence-retention test | Add only if current separate integration coverage proves hard to review |
| Retention/purge docs depth | Retention is in developer docs and data schema, but not a first-class consumer journey | Add a focused retention guide only if API consumers need direct retention controls |
| Receipt relevance is human-reviewed | The validator proves the cited test exists, not that the test semantically proves the docs claim | Keep receipts endpoint-specific in review; avoid generic receipts |

## Next Recommended Goal

Stay on public Flow runtime API quality, but do not broaden. The next highest-value slice is a small API consumer golden integration test only if it can reuse existing fixtures and prove multiple already-documented endpoints without inventing a new harness.
