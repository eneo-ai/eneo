# Retrospective 6 — Branding And Namespace ADR Closure

## TL;DR

1. Slice 10.6 closes Batch 10's branding/namespace decision gap without renaming packages or creating aliases.
2. Eneo is now recorded as the product-facing Flow/AI Builder brand, while `intric.*` and `@intric/intric-js` remain stable until dedicated migration ADRs.
3. Flow import barrels are documented as deletion candidates after import proof, not a preservation layer.
4. One concrete English translation mismatch now renders `Eneo logo`; generated Paraglide output stayed unstaged.
5. Claude final implementation verification returned `GREEN_LIGHT: yes` with minimum score `8`.

## Outcome

Implemented the closure with:

- `Eneo Branding And Namespace Migration` ADR backlog row
- PRD-010 ADR inventory update
- Phase 5 `Branding And Namespace Policy` proposal
- architecture-map rewrite for Flow root import barrels and `ai_builder_models.py`
- architecture-map removal of `legacy drift` wording for AI Builder session state
- English `intric_logo` value changed from `Intric logo` to `Eneo logo`
- explicit follow-ups for zero-importer barrel deletion, imported-barrel retargeting, compatibility-deletion ADR default, translation-key migration, Flow error-key namespace review, and pre-release branding sweep

## What Stayed Clean

| Area | Result |
|---|---|
| Package namespace | No `intric.*` Python rename and no parallel `eneo.*` package or re-export namespace. |
| Generated client package | No `@intric/intric-js` rename or `@eneo/*` alias. |
| User-facing brand | Net-new Flow/AI Builder product-facing surfaces are directed to Eneo. |
| Import barrels | Docs now treat barrels as ambiguous ownership and deletion candidates after import retargeting/proof. |
| Translation value | The concrete English mismatch is fixed without changing translation keys or generated code. |
| API wire keys | `intric_error_code` is recorded as a future namespace ADR concern, not a branding cleanup. |
| User-owned files | Batch 11 docs, `docs/refactor/implementation-order.md`, `scripts/run_codex_review.sh`, and `PRODUCT.md` remain outside this slice. |

## Validation

| Command | Result |
|---|---|
| `git diff --check -- frontend/apps/web/messages/en.json docs/FLOWS_AND_AI_BUILDER_ARCHITECTURE.md docs/refactor/architecture-decision-backlog.md docs/refactor/prd/PRD-010-documentation-and-adrs.md docs/refactor/phase5/agents-md-additions.md docs/refactor/execution/batch-10-operability-cleanup-docs` | Passed |
| `cd frontend/apps/web && bun run i18n:compile` | Passed |
| `rg -n "compatibility shims\|compatibility aggregator\|legacy drift\|keeps older imports\|useful for compatibility\|backwards compatibility\|deprecated" docs/FLOWS_AND_AI_BUILDER_ARCHITECTURE.md` | Passed: no output |
| `rg -n '"intric_logo": "Intric logo"' frontend/apps/web/messages/en.json frontend/apps/web/src/lib/paraglide` | Passed: no output |
| `./scripts/gate-local/anti_slippage.sh --worktree` | Passed: `anti-slippage: worktree clean` |
| `rg -l "from intric\\.flows\\.flow import\|import intric\\.flows\\.flow" backend/src backend/tests \| wc -l` | `46` |
| `rg -l "from intric\\.flows\\.ai_builder\\.ai_builder_models import\|import intric\\.flows\\.ai_builder\\.ai_builder_models" backend/src backend/tests \| wc -l` | `112` |
| `rg -l "from intric\\.flows\\.(flow_repo\|flow_run_service\|flow_version_repo) import\|import intric\\.flows\\.(flow_repo\|flow_run_service\|flow_version_repo)" backend/src backend/tests \| wc -l` | `0` |

## Claude Loop

| Iteration | Artifact | Verdict |
|---|---|---|
| Plan review | `.codex/artifacts/claude-peer-loop-batch-10-branding-namespace-closure-plan-20260502T225646Z.md` | `changes_required`, `GREEN_LIGHT: no` |
| Plan verification 1 | `.codex/artifacts/claude-peer-loop-batch-10-branding-namespace-closure-plan-verification-20260502T230603Z.md` | `changes_required`, `GREEN_LIGHT: no` |
| Plan verification 2 | `.codex/artifacts/claude-peer-loop-batch-10-branding-namespace-closure-plan-verification-2-20260502T230935Z.md` | `green`, `GREEN_LIGHT: yes` |
| Implementation verification | `.codex/artifacts/claude-peer-loop-batch-10-branding-namespace-closure-implementation-20260502T231554Z.md` | `green`, `GREEN_LIGHT: yes` |

Accepted changes:

- fixed the concrete translation value instead of deferring all branding cleanup
- split zero-importer barrel deletion from imported-barrel retargeting
- moved compatibility-deletion ADR tightening to a separate follow-up
- recorded `intric_error_code` as a wire-contract namespace decision
- kept i18n compile as validation while leaving generated output unstaged

## Carry Forward

| Item | Owner | Next action |
|---|---|---|
| Zero-importer Flow barrels | Flow backend architecture | Confirm no static/dynamic references, then delete `flow_repo.py`, `flow_run_service.py`, and `flow_version_repo.py` in a small source cleanup. |
| Imported Flow barrels | Flow backend architecture | Retarget `flow.py` and `ai_builder_models.py` imports to canonical modules before deleting the barrels. |
| Compatibility deletion ADR default | Flow architecture | Update the existing ADR row in a separate policy slice. |
| Translation key migration | Frontend i18n | Move the single `m.intric_logo()` call site to `m.eneo_logo()` or document why both keys remain. |
| Flow error-key namespace review | API maintainer | Decide `intric_error_code` naming through the namespace migration ADR because it is a wire contract. |
| Batch 11 Flow AI Builder reliability | Batch 11 | Read the Batch 11 plan after Batch 10 is committed and improve reliability ownership where needed. |

## Confidence

High. The diff is small, the decision ownership is explicit, the validation gates passed, and Claude gave implementation green after reviewing the actual wording.
