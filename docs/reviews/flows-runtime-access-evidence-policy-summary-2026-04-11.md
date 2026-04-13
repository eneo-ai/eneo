# Flows Runtime Access & Evidence Policy — Discussion Summary

Date: 2026-04-11
Purpose: High-level summary for review with other agents about runtime access, evidence, classification, and service-key logic.

## Core recommendation

- **Tenant admin** is trusted everywhere.
- **Space owner** is fully trusted within their space.
- **Space admin** is also a trusted in-space operator and should be able to support/debug that space.
- **Editor/viewer** are not operators; they do not gain cross-run debug/evidence powers.
- **Service key** can only access **its own runs**, but should be able to access **its own evidence** when explicit machine evidence capabilities are granted.

## Main conclusion about classification 3

Classification 3 should **not** mean:
- “only tenant admins can export/view evidence”

That creates an unrealistic support bottleneck.

Instead, classification 3 should make the **sensitive form of export stricter**, not break supportability.

## Recommended evidence model

Treat evidence as 3 levels:

1. **Evidence view**
2. **Evidence export (redacted/default)**
3. **Evidence export (raw/full)**

This is the key design improvement.

## Why this is better

If evidence is only one binary thing, policy becomes too blunt:
- either too strict and unusable
- or too loose and risky

Splitting it into three levels gives a more logical balance.

## Recommended role behavior

### Tenant admin
- Full access everywhere
- Can always do raw/full export

### Space owner
- Full in-space access
- Can always do raw/full export in their space

### Space admin
- Trusted operator in their space
- Can view evidence
- Can export redacted/default evidence
- Can do raw/full export in classification 1–2 by default
- In classification 3, raw/full export should require an extra stronger gate/capability

### Human run owner
- Can access own-run evidence if `FLOWS_TRACE` permits it
- Own-run rights should not disappear just because the user is otherwise only an editor/viewer

### Service key
- Own runs only
- No cross-run or cross-space evidence access
- Needs explicit machine evidence capabilities:
  - `evidence_view`
  - `evidence_export_redacted`
  - `evidence_export_raw`
- In classification 3, raw/full machine export should be stricter and possibly tenant-policy-controlled

## Why service-key own-evidence access is logical

If a service key can:
- create a run
- own the run
- return the result

then it is logical that it can also explain **its own result**.

Otherwise, app-owned integrations become impossible to explain in compliance/government scenarios.

## Main policy tradeoff

The most important tradeoff is:

- **operability/support reality**
vs
- **creating a real security delta for classification 3**

The balanced answer is:
- do not block trusted in-space operators from ordinary evidence support
- do make **raw/full export** more tightly controlled in classification 3

## Strongest rejected ideas

### 1. Service keys never get evidence
Rejected because app-owned runs would become non-explainable.

### 2. Classification 3 means tenant-admin-only evidence/export
Rejected because it creates support bottlenecks and does not scale across many spaces.

### 3. Service keys inherit broad admin-like evidence powers
Rejected because it violates least privilege.

## Edge cases to pressure-test

1. Deleted employee / surviving app integration
2. Government request for explainability on a service-key-owned transcription flow
3. Space admin needs to debug a failed run in a high-security space
4. Evidence is more sensitive than outputs/artifacts
5. Leaked service key with evidence capability
6. Human run owner who is not a space admin
7. Cross-space leakage by trusted in-space roles
8. Whether class-3 raw export for service keys should be tenant-configurable

## Final high-level stance

The most logical all-around model is:
- trusted humans in a space stay trusted for support/debug
- service keys stay narrow but can explain their **own** runs when explicit machine evidence capabilities are granted
- trusted operators (tenant admin / space owner / space admin) are treated as having the operator baseline for evidence in their scope; ordinary principals still rely on `FLOWS_TRACE`
- classification 3 tightens **raw/full export**, not all evidence support
- evidence policy should be tiered, not binary

## Files to review for the detailed draft

- `.omx/plans/prd-flows-runtime-access-evidence-policy.md`
- `.omx/plans/test-spec-flows-runtime-access-evidence-policy.md`


## Final clarification

- Trusted operators (tenant admin / space owner / space admin) do **not** require a separate per-user `FLOWS_TRACE` grant for in-scope evidence access; operator trust is the baseline.
- Service-key raw/full export in classification 3 is **deny by default** and requires both the machine capability and tenant policy enablement.


## Claude second-opinion review

Claude review agreed the **policy direction is strong**, especially:
- trusted in-space admin/operator model
- service-key own-evidence access for compliance/explainability
- tiered evidence model (view / redacted export / raw export)
- classification 3 as a meaningful raw-export control instead of a tenant-admin-only bottleneck

Most valuable implementation warnings from Claude:
1. current code still blocks some approved admin evidence behavior
2. `FLOWS_TRACE` enforcement must be centralized cleanly
3. machine evidence capabilities must be explicitly modeled
4. graph/evidence-adjacent routes must not bypass the final evidence policy
5. implementation should be staged, not landed as one giant change

Claude artifact:
- `.codex/artifacts/claude-review-flow-runtime-access-evidence-policy-final-refine-20260411T171409Z.md`
