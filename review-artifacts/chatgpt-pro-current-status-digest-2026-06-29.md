# ChatGPT Pro Current Status Digest

Date: 2026-06-29

## Scope

This is a short status digest for strategic review of the Eneo Flows / Flow AI Builder roadmap.
It replaces the long implementation-progress ledger for the ChatGPT Pro review package.

## Current Branch State

- Repo: `/Users/cimen/eneo/eneo-flows-clean`
- Branch: `refactor/flows-clean`
- Current implementation head before this review packet: `b1974c90 fix(flows-api): declare template delete empty response`
- Roadmap-execution review range: `799e0fae..b1974c90` (`23` commits). Do not treat the full branch diff against `develop` as the focused review scope; the branch contains older Flow feature history.
- Review artifacts are local/ignored working material unless deliberately promoted to durable repo docs. Promoted docs for outside review are the compact packet, the architecture roadmap, this digest, the strategy trace, and the tracked implementation-progress ledger.

## PG Work Completed So Far

- PG-1: fixed the build-breaking AI Builder frontend `'applying'` status drift.
- PG-2: added Flow worker/beat support to the E2E compose stack.
- PG-3a/3b/3c: deleted verified dead Flow/Builder/runtime surface, including authoring snapshot exports, dead Builder helper wrappers, document-renderer facade, and Builder structured-output pass-through plumbing.
- PG-4: deleted the decorative runtime step-handler registry; executor construction is the runtime owner.
- PG-5/PG-6/PG-8: hardened runtime task timeout/terminalization behavior and added a DB-backed task-boundary proof.
- Runtime baseline repair: rebased one stale typed-output assertion to the runtime message owner.
- PG-7: cached Space hydration per run execution for step security checks.
- PG-9: added a deterministic Flow browser smoke proving list -> editor -> History -> worker-backed run evidence.
- PG-10a: deleted the Flow evidence bespoke error payload builder and returned canonical `GeneralError` with request id for direct evidence 400/503 paths.
- PG-11: deleted the webhook delivery JSON mirror and kept relational delivery state as the owner.
- PG-12: added ordinal checks and assistant FK indexes while preserving honest migration semantics.
- PG-13: added template asset deletion with retention reclamation.
- PG-14: merged queued redispatch paths.
- PG-15: projected template asset capabilities at the API boundary instead of the domain entity.
- PG-D4.1 through PG-D4.3: staged template identity cleanup by resolving runtime template fill asset-first, adding a read-only template identity audit, and making run-contract readiness fail closed on checksum drift.
- Push-hook fix: declared `response_model=None` on the 204 template delete endpoint so global route metadata checks pass; behavior unchanged.

## Not Completed / Still Deliberately Open

- PG-D4 fallback deletion remains open until target data audit/backfill proof shows it is safe to remove the runtime `template_file_id` compatibility path.
- Evidence export typed-summary parity / legacy open `summary` deprecation remains open.
- PG-10b: app-global FastAPI `RequestValidationError` / 422 standardization remains deferred because it affects all endpoints and generated clients.
- Builder-conditional PG-16 through PG-19 and PG-D1 through PG-D3 remain open until the Builder ship/no-ship decision is explicit.
- The post-PG no-code scorecard has not run yet.
- C8 was sharpened so Builder reliability covers explicit edit/revise intent routing before repair, while create-side reliability stays with provider normalization, clarification routing, and repair bounding.
- ChatGPT Pro's strategic review was integrated into the roadmap as roadmap gates, decision-register entries, and stop rules; it did not trigger source-code changes. The integration also added a Builder audit-vocabulary delete-or-wire decision for declared but apparently un-emitted `AI_BUILDER_PLAN_PROPOSED` / `AI_BUILDER_PLAN_REJECTED`.

## Strategic Questions Still Open

- Does Flow AI Builder ship in the first production cut, or is it backend-gated while Flows proper ships?
- Is PG-10b worth doing globally now, and what generated-client / non-Flow API compatibility work does it require?
- What is the migration policy for pre-launch Flow/Builder tables and columns: keep honest reversible structural DDL, but delete/reset/replay lossy unreleased schema artifacts instead of preserving fake downgrades?
- What is the intended JSONB corruption behavior for historical/drifted Flow rows?
- Which Builder repair/fallback paths earn their complexity after telemetry, and which should be deleted?
- Should `AI_BUILDER_PLAN_PROPOSED` be emitted by the Builder lifecycle, and should `AI_BUILDER_PLAN_REJECTED` be deleted as dead audit vocabulary?
- What minimum deterministic Builder create/edit eval seam is needed before calling Builder maintainable?
- What runtime crash/load/queue evidence is required beyond the PG-5/6/8 correctness proofs?
- What dead tests or tests for deleted behavior should be removed so the suite protects current behavior instead of old architecture?
- Which migrations that created unreleased Flow/Builder tables/columns should be cleaned when the corresponding schema artifact is deleted, instead of carrying dead schema history?

## Review Goal

Use this digest only to understand what is already done. Judge the roadmap and future sequencing from the uploaded roadmap and review evidence, not from the detailed command log.
