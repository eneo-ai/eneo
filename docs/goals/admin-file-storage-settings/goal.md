# Admin-Controlled File Storage Settings

## Objective

Implement, verify, document, review, and deliver the first reviewable slice of
eneo-ai/eneo issue #569: administrators can choose the deployment-wide storage
target for eligible new files and change typed business upload limits without
restarting Eneo, while PostgreSQL remains the complete default and operator
safety ceilings remain authoritative.

## Goal Kind

`specific`

## Current Tranche

Deliver issue #569 PR 1 only from a fresh branch based on the live
`origin/develop`: persisted deployment-wide new-write storage policy, persisted
typed business upload limits, safe capability and bounded inventory facts,
admin API and UI, generated contracts, migration and documentation. Verify the
complete slice, pass the required Claude and repository review gates, and
squash-merge it to `develop` only when the exact immutable head is green.

## Ordered Roadmap After This Tranche

This Goal implements and stops after item 1. The durable order after the
current tranche is:

1. #569 PR 1 — admin-controlled placement and typed business upload limits.
2. #569 PR 2 — verified storage moves.
3. #571 PR 1 — knowledge generations.
4. #571 PR 2 — robust ingestion.
5. #571 PR 3 — publication, retrieval, and deletion.
6. Defer #586 until a concrete consumer and product contract exists.

Flow remains deferred. This ordering is roadmap context, not authorization to
begin any item after #569 PR 1 in this Goal.

## Non-Negotiable Constraints

- PostgreSQL-inline remains the complete ready-to-use default; object storage is optional.
- Policy applies deployment-wide and only to eligible new writes; existing content never moves implicitly.
- Effective upload limit is the lower of the persisted admin business policy and the applicable operator safety ceiling.
- Legacy business values are seeded exactly once during upgrade and restart-dependent duplicate business configuration is removed after ownership is verified.
- Deployment secrets, endpoints, certificates, credentials, and operator capacity safety tuning remain deployment-owned.
- Unavailable or incompatible object storage is rejected clearly; there is no fallback, dual write, third backend, provider registry, or vendor-specific branch.
- Ordinary product APIs expose no endpoint, bucket, object key, provider, credentials, or infrastructure detail.
- No per-tenant policy, routing, bucket, dedupe, automatic migration, automatic cleanup, knowledge/InfoBlob generation, Flow work, PR 2 verified moves, issue #571, or issue #586.
- The editable admin UI uses the smallest explicit session-backed authority:
  `users.is_platform_admin`, granted or revoked only through the existing
  super-key sysadmin boundary. A mutation requires both tenant Admin and the
  platform-admin flag. Do not create a control-tenant registry or generic
  authorization framework.
- Reuse and deepen existing admin settings, object-content policy/capability, File/Icon producer, API/generated-type, migration, and documentation owners.
- Use behavior-first tests and preserve constant or bounded database work.
- Do not merge with pending, stale, skipped-unexpectedly, unverified, or failing required gates.

## Stop Rule

Stop after PR 1 is merged and audited, when every safe local action is blocked,
or when continuing requires owner input, unavailable credentials, a destructive
operation outside the stated gates, or product strategy the board cannot
decide. If a required gate cannot be proven, leave the PR open and record the
exact blocker.

Do not stop after planning, discovery, or Judge selection when a safe Worker
task can be activated.

## Canonical Board

Machine truth lives at:

`docs/goals/admin-file-storage-settings/state.yaml`

If this charter and `state.yaml` disagree, `state.yaml` wins for task status,
active task, receipts, verification freshness, and completion truth.

## Canonical External Scope

- Epic: https://github.com/eneo-ai/eneo/issues/549
- Task: https://github.com/eneo-ai/eneo/issues/569
- Base revision: `2746098cc008f7e9b95eae775ae4501a11cdb5c3`
- Branch: `feature/admin-file-storage-settings`

## Run Command

```text
/goal Follow docs/goals/admin-file-storage-settings/goal.md through the first safe verified implementation slice. Do not stop after planning unless blocked.
```

## PM Loop

On every continuation:

1. Read this charter and `state.yaml`.
2. Verify the recorded repository and external issue state.
3. Work only on the active board task.
4. Assign Scout, Judge, Worker, or PM according to the task.
5. Write a compact receipt and update the board.
6. If Judge selects a safe Worker task with `allowed_files`, `verify`, and `stop_if`, activate and execute it unless blocked.
7. Finish only with a Judge or PM audit that maps current receipts and exact-head verification to the objective.
