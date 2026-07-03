# Peer Loop Brief: Fable 07 Evidence And Legal Transparency

## Decision Under Review

Run a single Fable max-effort pass next for evidence, provenance, auditability, and legal/public-record transparency.

## User Direction

The user rejected the security/tenant-boundary pass as the next Fable spend and prefers Fable 07, 05, or 08. Codex recommends Fable 07 first within that preference.

## Why Fable 07 First

Fable 07 is the highest-ROI next pass among the user's preferred options because it answers whether Eneo can disclose and explain "what exactly happened" in a flow run:

- exact flow version and step definitions used;
- exact prompt/source material sent into each model step;
- model/provider/settings such as temperature and completion kwargs;
- files, template assets, generated files, transcription/extraction status;
- RAG query, selected chunks, scores, knowledge/file provenance;
- timestamps, actor/service principal/API key context, run/retry/review/rerun events;
- outputs, artifacts, evidence bundle, export manifest;
- redactions, omissions, retention/purge explanations.

This is product/legal/compliance critical and also prepares the later API consumer DX pass because API shape should expose the evidence truth, not invent it.

## Proposed Prompt

Use:

`fablereview/2026-07-03-eneo-flows-ai-builder/fable-07-evidence-legal-transparency-v2-prompt.md`

Save Fable output to:

`fablereview/2026-07-03-eneo-flows-ai-builder/fable-07-evidence-legal-transparency-v2-review.md`

## Scope Guardrails

- This is not a generic compliance platform review.
- This is not a tenant authorization/security review, except where evidence access sensitivity and redaction are directly relevant.
- This is not the public API consumer DX pass; it may flag API/export shape only where evidence cannot be disclosed clearly.
- This is not the runtime crash-recovery review; it should reuse Fable 06 findings only where crash/retry/rerun affect evidence completeness.
- Apply Ponytail: prefer one typed evidence/export manifest owner, delete/merge duplicate evidence/provenance concepts, avoid broad best-effort stories that make missing data look complete.

## Prompt Budget Decision

Claude peer-loop iteration 1 confirmed Fable 07 is the right next target under the user's 07/05/08 preference, but required trimming because prior Fable failures were effectively all-or-nothing buffered. Codex revised the prompt so the disclosure inventory matrix, ranked findings, owner reconciliation, capture traceability, and missing red tests are the authoritative deliverable. The prompt now removes repeated narrative sections and seeds the strict export manifest vs live debug projection reconciliation.

## Question For Claude

Is Fable 07 v2 the right next scarce Fable pass under the user's 07/05/08 preference, and is the prompt focused enough? Challenge whether it should be narrower, whether API DX should go first, whether dead-code inventory should precede it, and what should be deleted or simplified from the prompt before spending Fable.
