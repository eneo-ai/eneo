# Claude Reconciliation 5 — Permission Policy

## Claude Verdict

- Artifact: `.codex/artifacts/claude-peer-loop-batch-8-step-rerun-permission-policy-20260502T105014Z.md`
- Verdict: green
- Green light: yes
- Minimum score: 9

## Accepted Changes

| Claude point | Codex action | Evidence |
|---|---|---|
| Pin service-key denial both with and without `allow_service_key_principals=True`. | Added the default-denial assertion to the rerun service-key test. | `backend/tests/unittests/flows/test_flow_access_policy.py` |
| Make the coarse `FLOWS` alias behavior explicit for rerun. | Added `FlowApiAction.RERUN` to the existing coarse-alias shipped-action matrix. | `backend/tests/unittests/flows/test_flow_access_policy.py` |
| Record the renamed permission tests. | Journal records the rename from misleading `legacy` wording to `coarse` permission wording. | `docs/refactor/execution/batch-8-step-rerun/journal.md` |

## Decision

`FlowApiAction.RERUN` is an implemented user-principal action owned by the canonical flow access policy. It requires `FLOWS_MANAGE`; `FLOWS_RUN` and `FLOWS_VIEW` are insufficient. The existing coarse `FLOWS` alias continues to grant shipped Flow capabilities through `has_permission`, matching current edit/run behavior.

Service-key rerun remains denied in Batch 8. A future service-key rerun capability would need an explicit policy change instead of a router-only `allow_service_key_principals=True` flag.
