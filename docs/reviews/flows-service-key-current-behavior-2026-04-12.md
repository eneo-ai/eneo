# Flows service-key current behavior review — 2026-04-12

## Purpose
Grounded review of current service-key behavior on Flow endpoints using a real service key, real space, and real published flow.

## Test fixture used
- **Service key ownership:** `service`
- **Key type:** `sk_`
- **Permission:** `admin`
- **Scope type:** `space`
- **Scope id:** `ad016afa-931d-4df6-a69d-c8f05425346a`
- **Resource permissions:** `null`
- **Published flow id:** `0f0ef93a-92d4-4225-874d-72dcd9b2ac02`
- **Flow published version:** `9`
- **Flow owner / creator:** same real human user
- **Space membership of flow owner:** `admin`

## Live tested current behavior

| Endpoint | Expected product intent | Actual result |
|---|---|---|
| `GET /api/v1/flows/?space_id=...` | Service-key discovery of runnable published flows | `403 flow_service_key_principal_not_supported` |
| `GET /api/v1/flows/{id}/` | unclear — current authoring endpoint | `403 insufficient_scope` |
| `GET /api/v1/flows/{id}/run-contract/` | should support published-flow runtime consumers | `403 insufficient_scope` |
| `GET /api/v1/flows/{id}/input-policy/` | should support published-flow runtime consumers | `403 insufficient_scope` |
| `GET /api/v1/flows/{id}/graph/` | should likely support runtime topology for published flows or own runs | `403 insufficient_scope` |
| `POST /api/v1/flows/{id}/runs/` | should support service-key-owned published runs | `403 insufficient_scope` |
| `POST /api/v1/flows/ai-builder/sessions` | should remain human-only | `403 flow_service_key_principal_not_supported` |

## Root causes found in code

### 1. Global router-level scope enforcement blocks flow path endpoints before flow logic runs
The flows router is mounted with global API-key scope enforcement for `resource_type="flow"`.

However, `user_service._resolve_space_id_for_resource()` has **no `flow` case**.
That means any path-based endpoint like `/flows/{id}/...` fails closed with `insufficient_scope` even when the flow belongs to the same space as the key.

This is the primary reason consumer/runtime endpoints currently do not work for service keys.

### 2. Flow tenant-permission helpers still blanket-block service keys
`backend/src/intric/flows/flow_permissions.py` still raises `flow_service_key_principal_not_supported` for:
- view
- manage
- trace
- ai_builder

This is why the list endpoint and AI Builder endpoints fail with the service-key-principal error instead of scope mismatch.

### 3. The runtime stack already has the right shape
The flow consumer/runtime endpoints already thread `allow_service_key_principals=True` through the flow router helpers.
The current failure is not that the design is wrong — it is that the implementation is blocked by the two layers above.

### 4. SpaceActor already supports synthetic service-key roles
`SpaceActor` already derives in-space service-key roles from:
- key scope
- key permission

This is useful foundation code, but it is **too broad to use blindly** for flow authoring/discovery because a service key with `admin` permission would otherwise look like a human space admin. Flows need a narrower, domain-specific clamp.

## Important logical conclusion
The problem is **not** that service keys are conceptually unsafe for flows.
The problem is that the implementation currently mixes:
- human authoring semantics
- runtime consumer semantics
- global scope enforcement that does not understand `flow`

That combination produces a system that is stricter than intended and inconsistent with the published API docs.

## OpenAPI / DX drift
The OpenAPI descriptions for multiple runtime endpoints currently imply service-key support on published-flow runtime surfaces, but real requests still fail.

That means the current DX is misleading:
- docs say "service-key principals may create published-flow runs in v1"
- actual tested behavior = `403 insufficient_scope`

This drift should be treated as a product/documentation defect until implementation is aligned.

## Recommended logical policy

### Human-only surfaces
Remain human-only:
- create/update/delete flow draft
- publish/unpublish
- template asset management
- flow assistant authoring endpoints
- HTTP test endpoint
- AI Builder

### Service-key supported surfaces
Support service keys for **published-flow runtime only**:
- list published flows in the scoped space
- get run contract
- get input policy
- graph for published/runtime-safe topology
- upload flow input files
- upload runtime step files
- create run
- list own runs
- get own run
- cancel own run
- redispatch own queued run
- list own step outputs
- download own artifacts
- own-run evidence according to explicit evidence capability rules

### Strong rule
A service key is a **runtime principal**, not an author.
Even when its API key permission level is `admin`, it should not automatically inherit all human space-admin flow authoring abilities.

## Strong anti-hijack guardrails
1. Service keys never mutate flow definitions
2. Service keys never access another principal's runs by default
3. Service keys never gain cross-space visibility through flow discovery
4. Human draft ownership is not bypassed by service keys
5. Human operator trust (tenant admin / space owner / space admin) remains distinct from machine-principal trust

## Main maintainability recommendation
Do **not** rewrite the flow auth model.
Make a staged fix on top of the current architecture:
1. add `flow` scope resolution
2. narrow service-key behavior by endpoint family
3. explicitly clamp discovery/read surfaces to published/runtime-safe views
4. verify OpenAPI matches real behavior
