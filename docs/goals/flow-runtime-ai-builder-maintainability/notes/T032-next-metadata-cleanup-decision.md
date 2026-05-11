# T032 Next Metadata Cleanup Decision

## TL;DR

Delete the orphan `validate_flow_care_data_policy` adapter before starting the typed `published_definition.py` accessor.
The deletion has exact grep proof and is smaller than the published-definition slice.
Move the adapter's write-error coverage to the canonical metadata owner test file instead of losing it.
No Claude plan gate is required for this narrow cleanup because ownership and test scope are clear.
Keep `published_definition.py` queued as the next typed-boundary candidate after this deletion.

## Decision

Activate a narrow Worker to delete `validate_flow_care_data_policy` and its adapter-only test dependency.

Do not start `published_definition.py` yet. It is still required, but it touches published snapshot parsing and runtime contract readers; the orphan adapter deletion is a better immediate cleanup because it removes known dead public surface after T031.

## Evidence

| Candidate | Evidence | Decision |
|---|---|---|
| Delete `validate_flow_care_data_policy` | `git grep -n "validate_flow_care_data_policy" -- backend` shows only `backend/src/intric/flows/flow_care_data_policy.py:21` plus `backend/tests/unittests/flows/test_flow_care_data_policy.py:7`, `:78`, and `:83`. | Delete now. |
| Preserve care-data write-error coverage | `backend/tests/unittests/flows/test_flow_care_data_policy.py:53-83` still tests write errors through the adapter. | Move equivalent tests to `backend/tests/unittests/flows/test_flow_metadata.py` against `parse_flow_metadata(..., mode=WRITE)`. |
| Published-definition typed accessor | `backend/src/intric/flows/published_definition.py:118-126` still casts `metadata_json` to `JsonObject`; runtime readers still consume `published_definition.metadata_json`. | Defer one slice; needs a scoped plan because it affects published snapshots/runtime contract readers. |

## Proposed Worker T033

Objective:

> Delete the orphan `validate_flow_care_data_policy` adapter and move its write-error coverage to the canonical `FlowMetadataV1` parser tests without changing runtime care-data read behavior.

Allowed files:

- `backend/src/intric/flows/flow_care_data_policy.py`
- `backend/tests/unittests/flows/test_flow_care_data_policy.py`
- `backend/tests/unittests/flows/test_flow_metadata.py`

Red tests / proof:

- `parse_flow_metadata(..., mode=WRITE)` raises the same `BadRequestException` messages for non-object `care_data_policy`, unknown fields, non-boolean `sensitive`, unsupported `approval_mode`, and unsupported `pre_approval_visibility`.
- `resolve_flow_care_data_policy(...)` persisted-read tests still pass.
- `git grep -n "validate_flow_care_data_policy" -- backend` returns no hits after deletion.

Verification:

```bash
cd backend && uv run pytest \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_care_data_policy.py \
  tests/unittests/flows/test_flow_service.py \
  -q

cd backend && uv run pyright \
  src/intric/flows/flow_metadata.py \
  src/intric/flows/flow_care_data_policy.py \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_care_data_policy.py \
  tests/unittests/flows/test_flow_service.py

cd backend && uv run ruff check \
  src/intric/flows/flow_metadata.py \
  src/intric/flows/flow_care_data_policy.py \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_care_data_policy.py \
  tests/unittests/flows/test_flow_service.py

cd backend && uv run ruff format --check \
  src/intric/flows/flow_metadata.py \
  src/intric/flows/flow_care_data_policy.py \
  tests/unittests/flows/test_flow_metadata.py \
  tests/unittests/flows/test_flow_care_data_policy.py \
  tests/unittests/flows/test_flow_service.py
```

Stop if:

- any production caller remains for `validate_flow_care_data_policy`;
- write-error message coverage cannot move cleanly to `test_flow_metadata.py`;
- runtime care-data persisted-read behavior changes;
- new `Any`, casts, `# type: ignore`, or Pyright ignores are added;
- deletion requires touching FlowService, published-definition, AI Builder, routers, migrations, frontend, generated clients, or unrelated dirty files.

## Claude Gate

No Claude plan gate is required. This is a proof-backed deletion of an orphan adapter with exact grep evidence, not an ambiguous ownership/schema decision.

Run a host Claude self-review only if the deletion expands beyond the allowed files or if verification fails in a way that suggests hidden behavior.
