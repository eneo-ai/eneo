# T014 planning note: MCP guidance, revision rollout, and block integrity

The canonical product contract lives in:

- `docs/enterprise-skills-roadmap.md`
- `docs/adr/marketplace-hub-package-portability-and-skills.md`
- `docs/goals/enterprise-skills-rollout/state.yaml`

This note records only the planning decision and review evidence needed to
resume safely.

## Accepted decisions

1. A Skill may explain how to use an MCP tool already exposed by its parent.
   MCP configuration, authorization, approval, health, and execution stay with
   the existing MCP owners. No Skill-owned tool grant or dependency schema ships
   now.
2. An active execution block keeps exact bindings as remediation evidence.
   Newly added or revision-changed references fail; unchanged exact pins may
   survive unrelated saves and reorder. Assistants and Personal Chat omit the
   Skill, while Apps fail before provider work.
3. Organisation-wide version adoption is an explicit tenant-admin operation
   that advances only expected existing pins. It does not call parent-save
   commands, attach missing bindings, change order/mode/other fields, or create
   silent update tracking.
4. The operation is Skill-specific, bounded, resumable, idempotent, and
   body-free. Assistants and Personal Chat ship first; Apps are a separate
   follow-up.

## Delivery order

`T013 → T014 → T015 → T016 → T008 → T017 → T018 → O2 → evidence-gated T009 → S2 → Marketplace`

T017 may not start unless T016 exposes one concrete fit/activatability function
shared by ordinary save, preview, apply, projections, and tests.

## Planning evidence

- Challenge:
  `.codex/artifacts/claude-peer-loop-enterprise-skills-mcp-guidance-fleet-rollout-and-block-semantics-20260724T092037Z.md`
  — changes required, score 7.
- Corrected blueprint:
  `.codex/artifacts/enterprise-skills-mcp-rollout-blocking-blueprint-20260724.md`.
- Verification:
  `.codex/artifacts/claude-peer-loop-enterprise-skills-mcp-guidance-fleet-rollout-and-block-semantics-verification-20260724T093304Z.md`
  — green, score 8.

Reverify every claim against current source and the active task before editing.
