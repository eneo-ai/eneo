# Batch 1 — Claude Reconciliation 1

## Review Artifact

- `.codex/artifacts/claude-peer-loop-batch-1-api-source-truth-implementation-20260429T195651Z.md`
- Phase: implementation verification
- Iteration: 3
- Result: `GREEN_LIGHT: yes`
- Minimum score: 8

## Accepted Findings

No accepted blocking or partial findings.

Claude verified that:

- `OffsetPaginatedResponse[T]` is present and used for Flow list/run-list responses.
- Flow upload OpenAPI ownership no longer depends on the Flow-specific `server/main.py` postprocessor.
- Evidence export documents the JSON schema and `Content-Disposition` header at the route and validates the payload before returning a raw attachment response.
- Flow list and run-list routes over-fetch `limit + 1`, return `has_more`, and have OpenAPI pins for the generated component names.
- `intric-js` separates idempotency-intent normalization from request-body construction and adds `flows.published.get`.
- The generated schema patch is narrow and internally consistent with this batch's OpenAPI delta.
- Tier B public/persisted surfaces remain deferred.

## Non-Blocking Notes

| Finding | Codex disposition |
|---|---|
| Returned dictionaries include literal `count` even though `PaginatedResponse.count` is computed from `items`. | Defer. The literal value matches `len(items)` and keeps direct router tests readable. Record as pagination-consolidation cleanup. |
| `schema.d.ts` was manually patched and full regeneration still needs cleanup. | Accepted as carry-forward. Batch 5 owns full generated-client reconciliation. |
| `_normalizeRunIntent` and `_buildRunRequestBody` duplicate some normalization steps. | Defer. The explicit split avoids a boolean flag and keeps intent vs. body ownership clear. |
| Generated `schema.d.ts` uses "Successful Response" rather than the evidence route's custom 200 description. | Defer. Header and response schema are present; this is generator output polish, not a contract issue. |
| Published-runtime path assertion is a partial spot check. | Defer. The contract test covers the consumer sequence; tighter path projection assertions can be added when the projection stabilizes further. |
| `_retag_flow_ai_builder_operations` remains in `server/main.py`. | Planned Tier B. Delete only after AI Builder route/tag composition owns tags without postprocessing. |
| Claude reported an old plan-title iteration mismatch. | No action. Current plan title is `Batch 1 — API Source Truth Plan`, without an iteration suffix. |

## Verification Questions Answered

- FastAPI response serialization emits `count == len(items)` through the inherited computed field. The current returned dictionaries also set the same value for direct router-call tests; future pagination consolidation should remove the redundancy or convert `count` to a regular field.
- The `schema.d.ts` diff is limited to the two Flow pagination component definitions, two Flow list response refs, and the evidence export `Content-Disposition` header.
- `FlowRunPublic` exposes `tenant_id`; the API integration fixture is admin-scoped but not relying on a hidden admin-only response projection.
- Docker validation did not run because host tool policy rejected `docker ps` before execution. Local fallback validation passed.
- Frontend caller audit found app callers using `items` fallbacks, not generated pagination component names or `count`.

## Final Decision

Proceed to the commit boundary. No implementation changes are required before user review of the staging list.
