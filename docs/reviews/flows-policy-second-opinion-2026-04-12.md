# Flows access policy second-opinion review — 2026-04-12

Purpose: capture the latest multi-perspective review of the current Flows access / evidence / service-key model and record which follow-up ideas are actually worth pursuing.

## Overall verdict

The current model is strong and should be preserved. It already has a clean separation between:
- user-principal authoring
- published runtime
- user-principal operator trust
- service-key machine trust
- evidence tiering

This is not a policy that needs redesign. It benefits from targeted polishing only.

## Scores (pragmatic)

- API consumer DX: ~8/10 today; 9/10 is realistic with small follow-ups. 10/10 would likely require larger runtime UX features such as event/webhook push.
- Security: ~8.5/10 today; 9/10 is realistic with small hardening/documentation additions.
- Enterprise practicality: ~8.5/10 today; 9–9.5/10 is realistic because the tiered evidence model is already strong.
- Maintainability: ~8/10 today; 8.5–9/10 is realistic with small centralization cleanups.

## Important filter on the Claude review

Claude re-identified two historical problems as top improvements:
1. missing `flow` scope resolution
2. blanket service-key blocking in the flow permission layer

Those were already valid findings earlier, but they are now **implemented/fixed** in the current branch. They are not remaining work items.

## High-value remaining improvements

### 1. Published-flow metadata projection for service keys
Current model intentionally keeps `GET /api/v1/flows/{id}/` user-principal-only because it returns the current draft/current-definition view.

That is still slightly awkward for API consumer DX because a service key can list published flows but cannot fetch a simple single-flow published projection.

Recommended future improvement:
- add a service-key-safe published projection, e.g. minimal metadata only
- or add a dedicated published endpoint/projection for runtime consumers

### 2. Centralize service-key principal detection fully
There is still value in keeping one canonical helper for service-key-principal detection and avoiding future drift across modules.

### 3. Document service-key rotation consequences for historical runs
The own-run-only model is correct, but if a service key is rotated/replaced, runs owned by the old key should not silently look “shared” with the new key. This should be documented clearly for operators and API consumers.

### 4. Add creation-time guidance/warnings for evidence capability combinations
Not necessarily a hard validation failure, but a key-creation/admin UX improvement could warn when a requested evidence capability will still be classification-policy-gated.

### 5. Keep policy checks centralized and matrix-tested
No policy rewrite needed. Just keep the authorization seams centralized so future endpoints do not drift.

## Recommendation

Keep the current model.

Do not loosen service keys into human-authoring/admin equivalents.
Do not redesign the evidence model.
Do not widen editor/viewer powers by default.

Pursue only the targeted improvements above if the goal is to push:
- API consumer DX closer to 9/10
- maintainability toward 9/10
- enterprise practicality toward 9/10+
- security toward 9/10
