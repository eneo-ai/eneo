# Flows access matrix — 2026-04-12

Purpose: canonical quick-reference for the current Flow access model after service-key runtime policy refinement.

## Principal model

- **Service key** = machine runtime principal, published-flow runtime only, own-run-only.
- **Editor** = user-principal member with ordinary runtime/authoring rights according to space policy, but not a trusted operator.
- **Viewer** = read-only user-principal member, not a runtime operator.
- **Space owner / admin** = trusted in-space user-principal operator.
- **Tenant admin** = trusted tenant-wide user-principal operator.

## Access matrix

| Endpoint family | Service key | Editor | Viewer | Space owner / admin | Tenant admin |
| --- | --- | --- | --- | --- | --- |
| Draft CRUD | No | Per user-principal authoring policy | No | Yes | Yes |
| Publish / unpublish | No | No | No | Yes | Yes |
| Template management / flow-assistant authoring | No | Per user-principal authoring policy | No | Yes | Yes |
| AI Builder | No | Per user-principal authoring policy | No | Yes | Yes |
| List published flows in a space | Yes, published only in scoped space | Yes | Yes | Yes | Yes |
| `GET /api/v1/flows/{id}/published/` | Yes | Yes | Yes | Yes | Yes |
| `GET /api/v1/flows/{id}/` | No | Yes | Read-only if visible by user-principal policy | Yes | Yes |
| Run-contract / input-policy / runtime-safe graph | Yes | Yes | Yes | Yes | Yes |
| Create run | Yes | Yes | No | Yes | Yes |
| List / get / cancel / redispatch runs | Own runs only | Own runs only | No | In-scope runs | Tenant-wide runs |
| Step outputs / artifacts | Own runs only | Own runs only | No | In-scope runs | Tenant-wide runs |
| Evidence view / export | Own runs only, explicit `flow_evidence` capability required | Own runs, policy-gated | No | In-scope runs, policy-gated | Tenant-wide, policy-gated |

## Key rules

1. `GET /api/v1/flows/{id}/` remains a user-principal-oriented current-definition endpoint. Service keys should discover runnable flows through `GET /api/v1/flows/?space_id=...` and fetch a single runtime-safe flow via `GET /api/v1/flows/{id}/published/`.
2. Service keys can execute published flows, upload runtime files, and manage only the runs they created.
3. Service keys do not inherit user-principal operator powers just because the key is scoped to a space with admin-level permission.
4. User-principal run owners can inspect their own runs. Evidence for user-principal callers remains policy-gated (for example `FLOWS_TRACE`).
5. Trusted operators use user principals: space owner/admin in-space, tenant admin tenant-wide.
