# T012 projection compatibility decision

## Decision

Fail closed. Existing Assistant, App, default-Assistant Space, dashboard, and
`include_applications` responses currently populate persisted
`FilePublic.transcription`. Its optional type permits a genuinely absent
transcription; it does not authorize silently replacing a populated runtime
value with `null`.

Any attachment-bearing metadata response therefore needs a separately named,
additive public contract and a concrete migration consumer. That product work is
deferred. Direct File GET/list and all existing hydrated aggregate responses
remain unchanged.

## T010 contract

Narrow T010 to `GET /api/v1/spaces/{id}/applications/`. Its existing
`Applications` response contains `AssistantSparse` and `AppSparse` without
attachment fields, yet the current route loads a full Space and discards the
hydrated attachment bytes.

Implement one explicit sparse applications read projection that:

- returns the exact existing JSON, ordering, published filtering, permissions,
  collection permissions, tenant authorization, and scoped-key behavior;
- performs zero File, File-reference, object-content, payload, descriptor, or
  object-store reads;
- reuses current actor/authorization ownership instead of copying policy;
- never creates partially hydrated File, Assistant, App, or Space objects.

## Proof and stop conditions

First make the current waste observable: attach content with persisted
transcription, make byte reads fail, and prove the sparse route still needs
hydration today. The green behavior must return the unchanged response with zero
File/content SQL and zero remote adapter calls. Preserve direct File
transcription and current Assistant/App/full-Space, dashboard, execution,
history, transcription, and download behavior through focused regressions.

Stop if the implementation needs a public value change, duplicated actor policy,
a partial domain object, boolean hydration flag, generic projection framework,
new route, provider branch, cache, fallback, a file outside the frozen lease,
#569, #571, or Flow.
