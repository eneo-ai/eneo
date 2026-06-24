# Flow AI Builder Capability Refactor Plan

## Five-line TL;DR

1. Finish Phase 4 Flow AI Builder runtime deletion before platform capability implementation.
2. Keep this document as the phase-order and merge-gate packet; do not duplicate detailed slice design here.
3. Treat PR #480 and Dify as references, not architectures to copy.
4. Every implementation slice must delete a named duplicate owner or remove a named wrong-layer dependency in the same migration.
5. Stop after Phase 4 with a Phase 5A go/no-go packet; do not implement Assistant configuration, shared descriptors, or MCP in this goal.

## Document Precedence

This packet owns **implementation order, gates, and stop conditions**.

Related docs keep their existing ownership:

- [Eneo Capabilities And MCP Architecture Opinion](./eneo-capabilities-mcp-architecture-opinion.md)
  owns the long-term capability/MCP rationale.
- [Flow AI Builder Phase 4: Question Recovery Completion Boundary](./flow-ai-builder-phase4-question-recovery-completion-boundary.md)
  owns the detailed question-recovery completion slice and its failure-mode-to-test mapping.
- This document owns the active goal sequence: Phase 4 completion, then a Phase 5A go/no-go packet, then stop.

If a later decision record supersedes any of these, it should explicitly say so and delete or shrink stale guidance in the same change.

## Architecture Rule

```text
Eneo capabilities describe what is possible.
Domain commands decide and perform what is allowed.
Adapters expose them.
MCP never becomes the owner.
```

## Current Evidence For The Active Goal

| Finding | Evidence |
| --- | --- |
| Proposal completion already has a current provider boundary. | `backend/src/intric/flows/ai_builder/ai_builder_litellm_completion.py:94` defines `call_proposal_completion`. |
| Question recovery no longer calls provider proposal completion directly. | `backend/src/intric/flows/ai_builder/ai_builder_question_recovery.py:81` receives `repair_completion`; `backend/src/intric/flows/ai_builder/ai_builder_question_recovery.py:294` awaits it with `ctx.completion_request(...)`. |
| The first Phase 4 slice was dependency inversion, not deletion of the executor. | `call_proposal_completion` survives at `backend/src/intric/flows/ai_builder/ai_builder_litellm_completion.py:94`; active submission still calls it at `backend/src/intric/flows/ai_builder/ai_builder_proposal_submission.py:261`; the usage-tracked factory wraps it at `backend/src/intric/flows/ai_builder/ai_builder_litellm_completion.py:143`. |
| Question recovery still needs LiteLLM context for discovery runtime. | The boundary doc records that the completion import is the smell, not all `litellm_client` usage. |
| `ProposalTurnContext.completion_request(...)` is the existing typed request builder. | `backend/src/intric/flows/ai_builder/ai_builder_proposal_tool_contracts.py:144`. |
| Flow Capability Manifest already owns engine feature truth. | `backend/src/intric/flows/flow_capability_manifest.py:454` defines `CAPABILITY_REGISTRY`. |
| Builder/FCM duplication is explicit and test-held. | `backend/src/intric/flows/flow_capability_manifest.py:121`, `backend/src/intric/flows/flow_capability_manifest.py:470`, `backend/src/intric/flows/flow_capability_manifest.py:495`, `backend/src/intric/flows/flow_capability_manifest.py:526`, and `backend/src/intric/flows/flow_capability_manifest.py:572` describe mirrored Builder/runtime mappings. |
| Flow authoring already has the command shape we want to reuse, not generalize. | `backend/src/intric/flows/application/flow_authoring_command.py:127` owns preview/prepare/apply through `FlowAuthoringCommandService`. |
| Flow-managed Assistant mutation is already blocked outside Flow. | `backend/src/intric/assistants/assistant_service.py:117` rejects direct Flow-managed assistant mutation. |
| Standalone Assistant update is production-risky and broad. | `backend/src/intric/assistants/assistant_service.py:489` starts a large optional-argument update path with permission, governance, resource, prompt, and persistence behavior. |
| Assistant prompt clearing already had a tri-state bug class. | `backend/src/intric/assistants/assistant_service.py:601` documents the empty-string prompt clear regression. |
| Governance and knowledge/MCP exclusivity live in Assistant update today. | `backend/src/intric/assistants/assistant_service.py:731` and `backend/src/intric/assistants/assistant_service.py:761`. |
| PR #480 is available locally as source material. | Git refs `github-pr/480/base` and `github-pr/480/head` exist locally. |

## Accepted Long-Term Direction

Use the long-term direction from the capability/MCP opinion doc:

- make Eneo capability-addressable, not MCP-first;
- keep feature manifests, command/query contracts, scoped availability, and adapter/tool exposure separate;
- use MCP as an external adapter only;
- do not copy PR #480's fused registry/handler/MCP-loopback shape;
- do not copy Dify native graph JSON generation, repair stack, Graphon runtime, loops, or branching;
- use Dify only as reference for compact dynamic projection plus authoritative server-side validation.

Do not repeat those decisions in implementation slices. Each slice should name the duplicate owner it deletes or the wrong-layer dependency it removes, plus the canonical owner that remains.

## Phase Order

```mermaid
flowchart LR
  P4["Phase 4"]
  Packet["Phase 5A go/no-go packet"]
  Stop["STOP"]
  Future["Future goal selected separately"]

  P4 --> Packet --> Stop
  Packet -. recommendation only .-> Future
```

This document must not declare the order of future implementation phases.
The Phase 5A packet owns the next go/no-go recommendation.

## Phase 4 Scope

Phase 4 may touch only Flow AI Builder runtime/planner/proposal code and tests unless a direct shared owner requires a narrow dependency update.

### Implemented Primary Slice

Question-recovery completion ownership. The detailed design and test matrix live in [Flow AI Builder Phase 4: Question Recovery Completion Boundary](./flow-ai-builder-phase4-question-recovery-completion-boundary.md).

The implemented target:

- `call_proposal_completion` remains the current proposal-completion provider boundary;
- active first-pass proposal submission may still call it directly through `ctx.completion_request(...)`;
- question recovery no longer imports or calls it directly;
- question recovery receives the tracked completion callable as an explicit dependency from the owner that has the active turn context;
- question recovery still uses discovery LiteLLM context where discovery runtime requires it;
- `counts_as_repair=True`, retry exhaustion, backend-owned questions, and streaming order survived the slice.

The request object carries turn data only: `ProposalTurnContext` and the
original tool call. The executable completion dependency belongs in the
function argument list, beside the repository, discovery LiteLLM client, and
temperature dependencies.

### Candidate Follow-up Slices

These are candidates, not automatic work. Each requires preflight proof of a canonical replacement before implementation.

| Candidate | Required Deletion Gate |
| --- | --- |
| Proposal completion callable cleanup | Reassess `ProposalCompletionFn` only if replacing it reduces total production code and ownership-guard complexity. |
| Planner orchestration repair consolidation | Fold `ai_builder_orchestration_pipeline.py` repair behavior into the typed turn runner only if tests prove identical retry/error semantics. |
| Builder step capability duplicates | Defer unless the whole change stays Builder-local and mechanically deletes a duplicate owner. Otherwise this belongs in a later Flow capability-deduplication slice. |
| Prompt hard-rule duplication | Defer unless every touched rule stays within Builder runtime/planner ownership. Future capability work should enforce: every model-visible capability claim must have canonical enforcement. |
| Capability projection complexity | Shrink `ai_builder_capability_projection.py` only if Phase 4 typed-turn deletion or FCM projection makes state fields unnecessary. |

## Phase 4 Completion Criteria

Phase 4 is complete only when these requirements are proven against the current
worktree and recorded in the final packet.

| Metric | Phase 4 completion requirement |
| --- | --- |
| Direct proposal-provider owner | Only the current proposal-completion provider boundary owns provider proposal completion. |
| Question recovery | Zero imports from `ai_builder_litellm_completion`. |
| Manual completion-request construction | Zero `ProposalCompletionRequest(...)` construction in question recovery. |
| Usage accounting | One owner records proposal-completion usage; repair count remains preserved. |
| Retry ownership | The final packet lists each remaining retry loop by file/function and records either the product-visible retry semantics plus guard test, or the consolidation/deletion commit. |
| Phase 4 modules | Explicit keep/delete disposition exists for planner, question recovery, proposal repair, and orchestration pipeline. |
| Complexity | Before/after production file count, production LOC, `dict[str, Any]` count, and direct provider-caller count are recorded. |
| Documentation | This plan and the question-recovery boundary doc match the actual post-change symbols. |
| Baseline failures | Any pre-existing failure claim records baseline SHA, exact command, failing node ids, and output artifact or checksum. |
| Stop | Phase 5A packet is written; no Phase 5 implementation has started. |

## Baseline Commands For First Source Slice

The first source commit after this planning update must record the baseline SHA
immediately before source edits. For this slice, the source baseline was
`dfe1e71c0`, and the baseline commands ran from docs-only commit `76f6afde0`
before source edits. Treat `76f6afde0` as a docs-only wrapper around the same
source behavior when comparing baseline results.

Run these exact focused commands before the question-recovery source change:

```bash
docker exec -w /workspace/backend eneo-flows-clean_devcontainer-eneo-1 \
  /home/vscode/.local/bin/uv run pytest \
  tests/unittests/flows/ai_builder/test_ai_builder_question_recovery.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py \
  tests/unittests/flows/ai_builder/test_ai_builder_import_ownership.py

docker exec -w /workspace/backend eneo-flows-clean_devcontainer-eneo-1 \
  /home/vscode/.local/bin/uv run ruff check \
  src/intric/flows/ai_builder/ai_builder_question_recovery.py \
  src/intric/flows/ai_builder/ai_builder_proposal_processor.py \
  tests/unittests/flows/ai_builder/test_ai_builder_question_recovery.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py \
  tests/unittests/flows/ai_builder/test_ai_builder_import_ownership.py

docker exec -w /workspace/backend eneo-flows-clean_devcontainer-eneo-1 \
  /home/vscode/.local/bin/uv run pyright \
  src/intric/flows/ai_builder \
  tests/unittests/flows/ai_builder/test_ai_builder_question_recovery.py \
  tests/unittests/flows/ai_builder/test_ai_builder_proposal_processor.py

docker exec -w /workspace/backend eneo-flows-clean_devcontainer-eneo-1 \
  /home/vscode/.local/bin/uv run lint-imports --no-cache
```

If any command fails before source edits, record the command, baseline SHA,
failing node ids, and artifact/checksum before continuing.

## Phase 4 Acceptance Gates

- No Flow runtime/API/persistence/XYFlow changes.
- No Phase 5A Assistant configuration implementation.
- No shared descriptor layer.
- No MCP adapter, MCP Apps, internal Builder-to-MCP calls, tool search, AI SDK, LangGraph, Dify/Graphon runtime, loops, or branching.
- Every code slice names:
  - what duplicate owner it deletes/shrinks or what wrong-layer dependency it removes;
  - the canonical owner that remains;
  - the behavior tests that protect the user-visible behavior.
- Focused tests must include the failure-mode guards owned by the boundary doc.
- Pyright and ruff pass for touched backend files.
- Broader Flow AI Builder tests pass before completion, or failures are proven pre-existing with command output.

## Phase 5A Go/No-Go Packet

The packet is the stop condition after Phase 4. It must decide whether to start canonical Assistant configuration as a future goal. It must not implement that future goal.

Required facts:

| Topic | Question To Answer |
| --- | --- |
| Caller matrix | Which HTTP/UI/service paths call `AssistantService.update_assistant` and related mutation methods today? |
| Audit owner | Where are Assistant mutation audit facts emitted today: service, router, decorator, repository, or missing? |
| Revision/concurrency | Does Assistant have a revision or optimistic-concurrency field today? |
| Idempotency | Is any Assistant update idempotency currently enforced? |
| Governance parity | Which governance checks must survive a future command service? |
| Flow-managed boundary | Which current checks already prevent standalone mutation of Flow-managed assistants? |
| PR #480 reuse | Which ideas can be reused without importing fused registry/MCP-loopback architecture? |
| Deletion targets | Which optional-argument, adapter-specific, or duplicated mutation paths could a Phase 5A refactor delete? |
| Tests | Which red tests must exist before Phase 5A source changes? |
| Risk | Which production surfaces make Phase 5A higher-risk than Flow-only work? |

Non-binding sketches may include:

- possible `AssistantExecutionSpec`;
- possible tri-state patch shape;
- possible inspect/prepare/preview/apply service shape;
- possible reuse boundary for Flow materialization.

These sketches are not implementation contracts. Future Phase 5A must design them under its own goal and tests.

## PR #480 Use Rule

Do not cherry-pick PR #480 broadly.

Use it as source material for:

- typed input models;
- server-bound target identity;
- confirmation before mutation;
- service reuse;
- schema derivation.

Do not carry forward as canonical:

- fused descriptor/handler/permission/audit/localization/form rendering;
- one MCP tool per setting as the authoritative write API;
- native Eneo loopback MCP;
- process-local elicitation as product state;
- adapter-owned audit;
- untyped `dict[str, Any]` capability result payloads;
- per-field MCP tools as the canonical Assistant write API;
- confirmation inside an apply transaction; confirmation must happen before
  apply opens a write transaction;
- independent Assistant-tool mutation of Flow-managed Assistants.

## Merge Gate

```text
A capability abstraction does not land unless the same migration:
1. deletes a named duplicate behavioral owner;
2. leaves no production dual path or compatibility shim;
3. reduces the number of modules, business-rule implementations, or untyped boundaries;
4. moves meaningful behavior tests to the canonical owner;
5. leaves adapters with translation only;
6. documents the net production LOC/file/owner delta.
```

This gate applies to code and durable docs. Do not add broad architecture documents that do not sharpen implementation order, delete stale guidance, or become an accepted decision record.

For new capability abstractions, this is a stricter bar than ordinary Phase 4
consolidation: removing a wrong-layer dependency can justify a narrow cleanup
slice, but a new capability abstraction must delete or consolidate an existing
duplicate owner in the same migration.

## Next Step After This Slice

Do not start Phase 5A.

Do not treat "finish Phase 4" as one source-code goal. Stop and re-audit the
remaining Phase 4 candidates before selecting another slice. Each next slice
needs its own preflight proof, red guard where practical, deletion gate, and
focused validation.
