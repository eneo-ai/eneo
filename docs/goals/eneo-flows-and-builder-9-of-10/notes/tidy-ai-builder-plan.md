# Flow AI Builder tidy refactor plan (reviewed, v2)

Status: in execution on `refactor/flows-tidy-ai-builder`. Written 2026-08-21 against
that branch at HEAD `bb684212e` = origin, with a dirty tree of 48 tracked files
(+5,674 −566) plus 29 untracked fixture files, then challenged by the Codex peer loop
in six passes (session `tidy-ai-builder-plan-review`; section 10 records every finding
and its disposition). The original review this document replaces is kept as an
untracked working file in the lane worktree; section 9 maps each of its
recommendations to accept / modify / reject. The original is reference only and is
never committed.

Authority: this file is the execution authority for the lane, committed in slice 0.1b
beside the program's other notes. The lane worktree's `refactorplan.md` is a pointer
to this file, so exactly one copy exists and checkboxes are ticked here. `index.md`,
`refactorplan-original-review.md` and `refactorplan-implementer-prompt.md` stay local
to the lane worktree and are never committed.

How to use it: work top to bottom. One slice per commit, each with its own peer gate
and its cohort before it lands (section 2). Tick a box only when the slice's
acceptance checks and its deletions are both done and the receipt is written.

---

## 1. Verdict in one page

The original plan chose "option C, a bounded deeper Builder refactor" and that choice
stands. Its two central principles also stand: model interpretation never becomes
durable runtime behaviour without an explicit user decision, and the model never
authors Flow mechanics. Most of its detail does not stand, because the original
reviewer never saw this worktree, the tracked engineering standards, or the program
ledger:

| Original claim | Measured here | Consequence |
| --- | --- | --- |
| The create proposal contract is "transport-shaped" and must be replaced by a compact `SemanticWorkflowIntent` | Create tool schema is 5,379 B of parameters (≈1,160 tokens); per step the model authors only `name, instructions, model_ref, knowledge_refs, citations_requested, output_fields` (`ai_builder_proposal_intent.py:694-877`); no sources, bindings, review mode, renderer or reader steps | No contract rewrite. Close the boundary; shrink `output_fields` only by evidence |
| "+8–15 pp first pass, 60–85 % fewer repairs, 25–45 % fewer tokens" | Sealed 158×3 on `c974f5cf0`: 421 of 486 observations first pass, 4 repaired; floors first pass ≥ 90.78 %, repairs ≤ 2.84 %, acceptance ≥ 93.62 % | The value of this refactor is deleted complexity and one owner per concept, not accuracy. No forecasts in this plan |
| Checkpoint authorization needs decision ids, revision fingerprints and receipts | The dirty tree already binds a checkpoint to the confirmed disclosure hash; no checkpoint question exists; the harness never reads `key_decisions` | Make the checkpoint a canonical structured question (4.4). No receipt subsystem |
| Replace `CreateCompileContext` with `AuthorizedFlowIntent`; move `pattern_registry` | `CreateCompileContext` is the adopted owner to deepen; patterns are selection metadata and never model-facing | Rejected |
| Benchmark rewards accidental topology | 172 tracked cases (182 in the dirty tree), 100 % Swedish, exact-topology assertions in ≈2–4 % of cases; the release gate is a pure 14-row module | Keep the instrument; fix auto-confirmation and case-authored answers |
| Route qualification profiles, request envelopes, an `EvidenceBackedValue[T]` epistemic model | No owner, no authority, no measured defect; conflicts with the catalog-capability ruling | Rejected |

The two structural problems the original plan under-weighted are where the durable
value is:

1. The persisted conversation is pruned at write time and `PlanningState` is rebuilt
   from the pruned transcript plus a growing carry-forward list (4.2). Every incident
   class in this week's peer reviews traces back to that seam. Measured use never
   approaches the pruning threshold.
2. Language heuristics: ≈150 phrase groupings, ≈1,700 entries, 14 modules and 5,738
   lines whose primary purpose is matching Swedish and English phrases (4.5). Removing
   only the English half would keep the brittle owner and save nothing; families are
   deleted in both languages when a typed or structural owner holds the meaning.

---

## 2. Rules that bind every slice

Pointers, not copies. Read them before the first slice.

- `AGENTS.md` (main repo root) and `docs/engineering/maintainability-standards.md`:
  reuse → deepen → move → merge → delete → create; no split for length; no config flag
  instead of a product decision; one concept, one owner; delete the old path in the
  same slice. Flows and the Builder are unreleased: no compatibility readers, no dual
  writes, no migrations for disposable Builder data (regenerate the dev DB).
- `docs/engineering/testing-standard.md`: a model-authored contract is proven through
  the complete path (provider schema → typed admission → compile → domain validator).
  Tests proportional to risk; tests die with the behaviour they guarded.
- `docs/engineering/ai-review-workflow.md`: peer loop per slice. A design gate the
  peer loop cannot settle is escalated to the owner; Fable is used only if the owner
  asks for it, never scheduled by this plan.
- `docs/goals/eneo-flows-and-builder-9-of-10/notes/master-program.md`, standing
  rulings: END STATE (the model owns semantic units, instructions, names, field
  design; `CreateCompileContext` + `ai_builder_assembly` own mechanics; surface closure
  means omit AND reject, never omit-and-strip; never a second skeleton compiler); GOD
  MODULES (no standalone split slices); NO CATALOG-IDENTITY ROUTING; NON-REPAIRABLE
  CODES (a failure whose deciding inputs the model cannot observe must never consume a
  model retry); BALANCED question rule (decision 7); TEMPLATE-MODE (decision 8);
  measurement cadence and rollout order ("corpus changes come last": the broad run on
  the unchanged corpus precedes any case change); populations are derived from the
  tracked manifest and from named predicates, never from prose counts.
- `docs/goals/eneo-flows-and-builder-9-of-10/notes/conformance-program-plan.md`,
  "Verification protocol": deterministic proof is primary; stochastic runs measure
  incidence with a predeclared cohort, equal repetitions, a stated minimum detectable
  effect and a stated non-inferiority margin; three repetitions are exploratory.
- Authority (O0 in section 5): the master program's operating protocol names
  `refactor/flows-clean` as the only landing branch. This plan lands on
  `refactor/flows-tidy-ai-builder` only once the owner has confirmed O0 and slice
  0.1b has committed both the lane note in `master-program.md` and this plan as a
  tracked program note. An untracked plan never overrides a tracked rule by itself;
  until 0.1b is done, nothing else is committed.
- Measurement: every slice that changes turn control, a model-facing contract, a
  prompt, the compiler or persisted state lands only with its named cohort ×3 and a
  broad ×1 over the tracked manifest, compared against the frozen floors. A floor
  breach is a rollback and an attribution event, never a trade; the attribution
  decides the next slice.
- Never stage the owner's protected files; never `git stash` in any worktree; record
  branch, HEAD and `git status --short --untracked-files=all` at the start of each
  slice; write the implementation receipt under `.codex/artifacts/`.
- Every slice that transfers ownership or refactors an existing path names its
  deletions up front and is net-deleting; a slice that only adds is wrong there.
  A slice whose product is new capability the codebase does not have yet (harness
  assertions, a corpus release, a question catalog entry) is allowed to add, and
  must not invent a cosmetic deletion to satisfy this rule.

---

## 3. Ground truth measured in this worktree (2026-08-21)

Re-measure before citing any of these in a receipt.

Size and churn
- `backend/src/eneo/flows/ai_builder`: 133 modules, 63,416 lines. Builder tests:
  ≈130k lines, 3,310 test functions (unit + integration).
- Last 30 days in `ai_builder`: 235 commits, +160,654 / −22,497 lines. Highest churn:
  `planning_state_builder.py` 72 commits, `ai_builder_assembly/create.py` 69,
  `ai_builder_create_compiler.py` 64, `ai_builder_planner_request_preparation.py` 54.
- Unit suite on the dirty tree (`uv run pytest tests/unittests/flows/ai_builder`):
  3,906 passed, 3 failed; the failures are the import-linter tests that shell out to
  `.venv/bin/lint-imports`, absent in this lane venv (environment, not product).

Model-facing contracts
- Create tool `propose_flow`: 5,379 B parameters (5,956 B with wrapper), ≈1,160
  tokens; `output_fields` (recursive `children`, depth cap 4,
  `ai_builder_new_step_models.py:23`) is 4,108 B of it; strict projection 5,452 B
  (`ai_builder_tools.py:89-152`, create only). Tool choice is lane-aware and already
  forced: create `propose_flow`, edit/revision `required` over `propose_flow` and the
  typed `decline_flow_change` tool (`ai_builder_proposal_tool_contracts.py:304-305,
  416-419`; decline handled at `ai_builder_proposal_submission.py:671-724`).
- `result_keys` obligation projection adds ≈300 B per obligated key
  (`ai_builder_proposal_intent.py:100-145`); the model's duplicate copies are pruned at
  `ai_builder_proposal_intent.py:542-621` (omit-and-strip, which the END STATE
  forbids).
- Classifier response schema: 13,847 B with the catalog's legal values; it is
  parameterized per request by allowed slot values and schema-candidate fingerprints
  (`ai_builder_slot_classification_contract.py:1439-1513`), with ten domains (`slots,
  file_roles, checkpoint_updates, form_intake, named_result_evidence,
  example_output_constraints, schema_direction, secondary_obligations, assumptions,
  contradictions`).
- Edit tool schemas still expose `review_mode` and `model_ref` to the model
  (`ai_builder_edit_tool_schema.py:40-43,181`); `review_mode` is the only assignment of
  a review policy in edit compilation (`ai_builder_authoring_projection.py:250-251`);
  the critic (`ai_builder_critic_invariants.py:181-212`) and the apply gate
  (`ai_builder_plan_lifecycle.py:608-636`) only detect mismatches.

Admission and repair
- Ten normalizers in the create admission path; five were added within 19 hours on
  2026-08-19/20 (`ai_builder_tools.py:288-728`: punctuation debris, steps nested in
  `result_keys`, misplaced children, server-owned children, children-shape coercion;
  commits `bf2857c11`, `3a178442b`, `56dcb0280`, `6e66eea60`, `1294f8354`), each
  motivated by a captured failure under `.artifacts/ai-builder-17{4,6}-*`.
- Repair loop: `MAX_PROPOSAL_PROVIDER_CALLS = 4`
  (`ai_builder_proposal_tool_contracts.py:97`); fingerprint progression
  (`ai_builder_proposal_retry.py:132-206`); temperature 0.35 → 0.6
  (`ai_builder_service.py:108-111`); failure-code feedback recipes
  (`ai_builder_proposal_retry.py:532-583`); forced tool retry after a text-only
  response, gated by the Swedish/English keyword heuristic
  `looks_like_information_request` (`ai_builder_proposal_retry.py:72-95, 899, 987`).
- Sealed 158×3 receipt `.codex/artifacts/flow-builder-measure-20260817/sealed-158x3-c974f5cf0/ai-builder-api-battle-suite-20260817T094734/`
  (in the `eneo-flows-clean` clone)
  (`suite-summary.json` plus one bundle per observation; query: read
  `journey.outcome_class` and `proposal_telemetry_diagnostics…repair_attempts` from
  every `ai-builder-api-battle-test-*.json`): 486 observations, 421 `plan_first_pass`
  (0 repairs), 4 `plan_repaired` (3 with one repair, 1 with two), 2 `builder_error`,
  1 `provider_outcome_unknown`, 51 intended clarification stops, 7 stalls. The repairs
  and the exhausted error belong to two server-mechanics families:
  `invalid_structured_underlag_projection` (3 repairs: `complex_procurement_multi_document_matrix`
  ×2, `advanced_explicit_procurement_matrix`) and `assembly_plan_invariant_failed`
  (1 repair on `file_role_discrimination_example_output_text_terminal`, 1 exhausted
  error on `advanced_explicit_public_record_redaction_support`). No accepted plan used
  a fourth provider call; one used a third.
- Create mode lacks the in-process duplicate-step-name disambiguation that edit mode
  has (`ai_builder_step_transition_policy.py:170-198`, gated to edit in
  `ai_builder_compiled_spec_preparation.py:49-54`), so create pays a repair for it.

Checkpoint lifecycle (dirty tree)
- `CheckpointCandidate` → `CheckpointIntent` (`planning_state.py:286-334`), promotion
  on a whole-version content-free confirmation
  (`planning_state_builder.py:1006-1028`), ack-path fixed-point re-render
  (`ai_builder_planner_request_preparation.py:281-326`), checkpoint carry-forward
  (`planning_state_builder.py:576-610`), custom disclosure row
  (`ai_builder_requirements_disclosure.py:418-532`). Compiler projection and parity
  (`ai_builder_checkpoint_contract.py:84-246`, baseline resolver `:249-259`) are sound
  and stay. HEAD is worse: there the model's own "explicit" grade wrote durable intents.
- No checkpoint question in `question_catalog.py`; `KNOWN_REQUIREMENT_SLOT_NAMES` has
  eleven slots (`ai_builder_slot_vocabulary.py:26-40`); architecture-impact questions
  bypass the question budget (`ai_builder_discovery_decision_engine.py:160-165`);
  compaction retains the latest interaction per question
  (`ai_builder_conversation_compaction.py:436-480`).

Persistence and turn lifecycle
- `builder_sessions.conversation` (JSONB) is pruned at write time
  (`ai_builder_repo.py:775, 1175`; the planner pre-applies the same pruning to the
  in-memory turn at `ai_builder_planner.py:367`; `ai_builder_conversation_compaction.py:43-46`:
  60 messages, 40 tail, 1 MiB, with ≈450 lines of retention rules protecting what
  rebuild needs).
- The turn lifecycle writes one message twice: the user message is persisted at turn
  claim (`ai_builder_repo.py:1175-1192`, turn state `open`), the planner then enriches
  that same message with prepared and classifier metadata and persists it again
  (`ai_builder_planner.py:430-489`), and `_merge_conversation_messages` replaces any
  message with the same `message_id` (`ai_builder_repo.py:1797-1810`). The record is
  therefore not append-only today; committed history is mutable by construction.
- `commit_turn` (`ai_builder_repo.py:1691-1760`) rebuilds `PlanningState` from the
  pruned conversation, stamps the architecture commit from a side channel
  (`_dispatch_architecture_commit`, `ai_builder_server_decision_dispatch.py:367-381`,
  appends no message of its own), then runs two carry-forward passes
  (`planning_state_builder.py:491-610`: architecture commit, mapped-file acceptance,
  attachment roles, attachment-structure slots, schema evidence, example inference,
  checkpoint state). The accepted mapped-file limit is already derived from the
  structured `mapped_file_limit` answer plus current policy
  (`planning_state_builder.py:216-290`); its carry-forward only preserves an earlier
  valid answer over a later invalid one. Prompt-time trimming is a separate owner
  (`ai_builder_planner_request_preparation.py:1001-1071`).
- Session lengths, read-only query over `builder_sessions` in the running measurement
  databases (`docker exec <db> psql -U postgres -d <db> -Atc "select count(*),
  percentile_cont(0.5) within group (order by jsonb_array_length(conversation)),
  percentile_cont(0.9) within group (order by jsonb_array_length(conversation)),
  percentile_cont(0.99) within group (order by jsonb_array_length(conversation)),
  max(jsonb_array_length(conversation)), count(*) filter (where
  jsonb_array_length(conversation)>=60), max(octet_length(conversation::text)) from
  builder_sessions"`): `developz_devcontainer-db-1/postgres` 16,013 sessions → p50 5,
  p90 14, p99 16, max 19 messages, 0 at the threshold, max 86,844 B;
  `eneo_flows_clean_devcontainer-db-1/postgres` 2,397 sessions → p50 5, p90 11, p99 14,
  max 16, 0 at the threshold, max 40,025 B. These are harness sessions (≤ 6
  interactions by construction); human session lengths are unmeasured because there
  are no production users.
- `builder_plans.proposal_json` stores the compiled `FlowDraftSpecCore` plus
  `spec_hash` (`ai_builder_domain_models.py:255-318`). Unchanged.

Language
- `ui_language` is the account locale from Paraglide (default `sv`), sent on every
  Builder request (`FlowAIBuilderDriver.ts:651`); it is not the language the user
  typed. It selects server-authored copy only (questions, disclosure, refusals,
  compiled step scaffolding). No prompt tells the model which language to answer in.
- Matching tables: 117 named module-level tables plus ≈33 inline groups, ≈1,700
  entries, across 14 modules (5,738 lines) whose primary purpose is matching, plus
  smaller tables in four more modules. A heuristic language detector is the fallback
  when `ui_language` is absent (`ai_builder_discovery_profile_builder.py:561-593`).
  Inventory by family: 4.5.
- Frontend: 6,370 message keys in both `sv.json` and `en.json`, 407 of them
  `ai_builder_*`; ten hardcoded English fallback error strings in
  `FlowAIBuilderDriver.ts` / `aiBuilderError.ts`.

Benchmark
- Tracked corpus at HEAD and on `origin/refactor/flows-clean`: 172 cases (version 8);
  the dirty tree holds 182. Fixture manifest: 10 entries at HEAD, 29 in the dirty
  tree; untracked under `backend/scripts/fixtures/ai_builder_battle/`: 10 prompt files
  and 19 attachment files (29 files; `manifest.json` itself is a modified tracked
  file). The 19 new manifest entries are the ones cases 173–182 reference through
  their `attachments` and `runtime_files` fixture names; 0.1 re-derives this and 0.4
  fails on any unreferenced or unstaged file. The master program's "158" is stale.
- 100 % Swedish prompts; 37 distinct `expected.*` keys; 643 alias groups in the JSON
  (not in Python); exact step counts in 4 cases, ordered output-mode topology in 6.
- Review cohort predicate (derived, never a prose count): a case with
  `expected.expected_review_policy`, or `expected.expected_runtime_evidence.review_checkpoint_count`,
  or the cohort tag `human_review`. Population: 9 cases at HEAD, 17 in the dirty tree.
- Harness auto-confirms every new `requirements_version` with an empty message and
  never inspects `key_decisions` (`ai_builder_api_battle_test.py:3598-3620`,
  `:4488-4501`); structured questions are answered only from case contracts
  (`:1270-1286, 4357-4459`) and an unexpected question stops the journey.
- `ai_builder_release_gate.py` (942 lines) is a pure 14-row module with N=5 and
  Wilson intervals; `ai_builder_receipt.py` and `ai_builder_battle_compare.py` are
  separate owners. `ai_builder_api_battle_test.py` is 10,246 lines, 216 defs,
  `_quality_report` alone 783 lines; its 154 tests import 66 private names.

---

## 4. Target architecture

### 4.1 Ownership after this plan

| Concept | Owner after the plan | Change |
| --- | --- | --- |
| Builder planning state | `PlanningState` (unchanged canonical owner, `docs/flows/flow-developer-quickstart.md` owner table) | derived by one pure fold (4.2) |
| Durable session record | `builder_sessions.conversation`: a bounded complete record; committed messages immutable, one mutable open-turn message | invariant (4.2) |
| Architecture commit | one typed carrier in the conversation, replayed by the fold | new (4.2) |
| Accepted mapped-file limit | derived from the structured answer and current policy (unchanged owner) | carry-forward deleted (4.2) |
| Human checkpoint | three canonical slots in `question_catalog.py`; compile-time `CheckpointIntent` derived from structured answers and, in edit, the flow's baseline | replaces candidate/promotion (4.4) |
| Understanding call | one classifier call, request-parameterized schema as today, fewer domains | audited (4.3) |
| Create proposal | `propose_flow` unchanged in shape; closed boundary | pruning and normalizers deleted by evidence (4.3) |
| Edit proposal | same step models; `review_mode` and `model_ref` removed from the model's surface; deterministic checkpoint projection in edit compilation | closed (4.4) |
| Repair | lane-aware tool choice as today; at most one repair after the initial call once the two server-mechanics families are owned | loop deleted (4.3) |
| Flow mechanics | `CreateCompileContext` + `ai_builder_assembly` (unchanged) | deepened, never renamed |
| Capability truth | `flow_capability_manifest.py` (unchanged) | none |
| Language of server copy | `ui_language` only; copy stays sv/en | heuristic detector deleted (4.5) |
| User-intent detection | typed classifier evidence with quotes + structural facts | phrase tables deleted family by family (4.5) |
| Benchmark | harness asserts disclosed decisions and answers questions from case contracts; release gate unchanged | (4.6) |

### 4.2 Data model and persistence

Problem. The conversation is both the model's transcript and the record `PlanningState`
is rebuilt from, so it is pruned for size and the rebuild compensates with
carry-forward. That seam produced the commit-drift class, the attachment-structure
slot loss (`planning_state_builder.py:620-633`), this week's checkpoint carry-forward,
≈450 lines of retention rules and 1,947 lines of compaction tests. Measured sessions
never reach the pruning threshold (section 3), so the machinery protects against a
case that has not occurred while adding a failure class that has.

Candidate design (Phase 4, design-gated; the gate answers the persistence checklist in
`maintainability-standards.md` "Persistence integrity" with the facts below). It is a
bounded complete record, not a generic event log.

- Canonical persisted owner: unchanged. `builder_sessions.conversation` stays a JSONB
  array of `ConversationMessage` on the session row; no new table, no event-store
  abstraction. `PlanningState` stays the canonical planning owner; it is already
  defined as "rebuilt each turn from the persisted conversation" (its docstring), and
  that is what lets a `BUILDER_SCHEMA_VERSION` bump regenerate state without a
  migration under the prerelease rule. The change is that the record it is rebuilt
  from is complete.
- Mutability invariant (the real one, not "append-only"): the current turn's user
  message is created at claim and may be enriched with prepared and classifier
  metadata until the turn commits; every message of a committed turn is immutable.
  `append_session_messages` after commit accepts an exact same-ID replay (retry
  idempotency via `client_turn_id` and the request fingerprint) and rejects a same-ID
  message with differing content. `_merge_conversation_messages` keeps its replace
  semantics only for the open turn's message.
- Ordering and identity: array order; `message_id` (stable, already required by
  evidence references); turn identity unchanged (`client_turn_id`, request
  fingerprint, `latest_turn_*` lifecycle columns).
- Transaction owner: unchanged (`commit_turn` savepoint: append + fold + CAS save on
  `planning_state_version`).
- Architecture commit: the one server decision that today exists only in
  `planning_state_jsonb`. It gets one typed carrier defined in
  `ai_builder_conversation_metadata.py` (an `architecture_commit` metadata key on a
  server-authored message with no user-visible content, written by `commit_turn`
  when a commit is stamped). No projection hides such a message today: the public
  transcript takes every user and assistant message (`ai_builder_router.py:409-421`)
  and the model context converts every message
  (`ai_builder_planner_request_preparation.py:1007-1013, 1075-1110`); tool messages are
  absent from the public transcript only because the role is not rendered, and they
  still reach the model. The design therefore adds one typed internal-fact predicate
  (a dedicated role or discriminator, fixed at the design gate) that both projections
  exclude explicitly, with tests that assert the fact is absent from the public
  session response and from the exact provider message list, and that the fold
  replays it. `CommitDriftError` stays (SELF_CHECK ruling).
- Accepted mapped-file limit: no new event. It is already derived from the structured
  answer and current policy; the fold takes the latest valid answer (which is what
  the carry-forward branch at `planning_state_builder.py:497-513` preserves today),
  and that branch is deleted.
- The fold: `build_planning_state(conversation, attachment_inventory, flow, policy)`
  is pure. Attachment-derived facts (roles from bytes, placeholders, declared
  schemas) are inputs computed each turn by the discovery context, not state carried
  across turns. Every `_carry_forward_*` branch is deleted.
- Cap admission instead of pruning, at one owner used by both write points, with
  bounds that exist in code rather than envelopes estimated from fixtures. The exact
  size owner is the existing serializer pair `conversation_serialized_size_bytes` /
  `_compact_json_bytes` (`ai_builder_conversation_compaction.py:145-165`); it moves
  into the cap-admission owner together with the per-message hard cap
  `MAX_SESSION_MESSAGE_BYTES` (256 KiB today, enforced only inside the compaction
  function at `:63, :84`), which then applies to every persisted message at every
  write. Only retention and pruning logic is deleted. One storage invariant bounds
  the record: every persisted message is at most `MAX_SESSION_MESSAGE_BYTES`, and
  every complete logical turn (including a chained architecture commit followed by
  a question, confirmation, proposal or refusal) appends an enumerated, fixed set of
  messages, so `MAX_MESSAGES_PER_TURN` is a constant the design gate derives from
  the branch table (counting the claimed user message and the architecture fact) and
  `commit_turn` asserts. O3 does not close until the arithmetic is written out
  against the real constants: `MAX_SESSION_MESSAGES` is 60,
  `MAX_SESSION_MESSAGE_BYTES` is 256 KiB and `MAX_SESSION_CONVERSATION_BYTES` is
  1 MiB (`ai_builder_conversation_compaction.py:43-46`), so a worst-case
  reservation of `MAX_MESSAGES_PER_TURN × MAX_SESSION_MESSAGE_BYTES` consumes the
  whole session budget several times over. Either the per-message cap for the
  reservation is far below 256 KiB, or the session budget rises, or the design is
  wrong; the gate states which, with the resulting usable turn count. If admission
  makes the commit-time breach unreachable, keep one transactional rollback proof
  rather than a matrix of tests for defenses that cannot fire. No field-specific text limits are added for storage math;
  the per-message cap already bounds them. At turn claim the owner does not do
  additive arithmetic: it builds the worst-case candidate (the current message sizes
  plus `MAX_MESSAGES_PER_TURN` messages of `MAX_SESSION_MESSAGE_BYTES`) and asks the
  moved `_conversation_size_from_message_sizes`, which already counts the JSON
  separators (`ai_builder_conversation_compaction.py:157`), whether the result stays
  within `MAX_SESSION_CONVERSATION_BYTES`, and checks
  `message_count + MAX_MESSAGES_PER_TURN ≤ MAX_SESSION_MESSAGES`. A session that
  cannot admit the turn is refused at claim with the typed `session_full` error (an
  error, never a session status; `SessionStatus` keeps its four values), zero
  provider calls, no persisted open-turn message. The constants are O3, chosen after
  4.1 so that the history allowance the reservation leaves stays far above measured
  sessions (largest measured 87 KB). At commit the owner asserts the actual
  candidate aggregate with the same function; an unexpected breach raises an
  internal invariant exception (never `AIBuilderBadRequestException`), rolls back
  conversation, planning-state and plan writes through the existing `commit_turn`
  savepoint, and is then owned by the existing turn lifecycle, not by this plan:
  the lease release (`claim_ai_builder_send_turn`, `ai_builder_send_lease.py:113-130`)
  and the transition table (`ai_builder_session_transitions.py:49-66`) already map a
  breach while `OPEN` to `FAILED_BEFORE_PROVIDER` (no provider ran; a retry is safe)
  and a breach while `PROCESSING` to `PROVIDER_OUTCOME_UNKNOWN` (a replay needs the
  explicit duplicate-spend acknowledgement; provider work is never repeated
  automatically), with an operator diagnostic outside the conversation. No
  post-commit overflow state exists. The refusal keeps apply/create of an existing
  plan available, so no work is lost; diagnostics and hydration readers
  (`ai_builder_router.py:409-465, 587-627`; `FlowAIBuilderDriver.ts:1550-1591`) see a
  complete record.
- Corruption: `ConversationMessage.from_persisted` already fails loud; a cached
  `planning_state_jsonb` that fails validation is rebuilt from the conversation (no
  compat reader).
- Retention: session retention is unchanged.
- Prompt-time trimming (`trim_conversation_for_context`, protected groups) is the only
  compaction left and is unchanged; the gate verifies budget behaviour on the longest
  captured sessions once the persisted record is no longer pruned.
- Readers of pruning semantics to retest, listed so the gate cannot miss them:
  `ai_builder_question_state.py:165-185` (question numbers are read off stamped
  messages precisely because order was unstable under pruning; they stay valid),
  `ai_builder_user_question_metadata.py:177`, the docs-site retry section ("survives
  conversation compaction"), `ai_builder_planner.py:367`.

Rejected alternative (Codex pass 1): keep pruning and make `planning_state_jsonb`
authoritative through typed transactional deltas, removing reconstruction branches
one owner at a time. Reason: it inverts the documented design, makes every
`BUILDER_SCHEMA_VERSION` bump a migration of authoritative state (the prerelease rule
forbids migrations for disposable Builder data), and keeps the retention rules whose
only purpose is to make pruning lossless. If the Phase 4 gate shows the fold cannot
be made deterministic, the gate is reopened with that evidence; no fallback is
predetermined here.

### 4.3 Model-facing contracts

Understanding call (classifier)
- One call per turn, as today. The schema remains parameterized by allowed slot
  values and schema-candidate fingerprints; what is rejected is the original plan's
  per-request domain pruning (`UnderstandingDelta`), which would change validation
  for no measured gain. Phase 3 is a consumer audit: each domain keeps its place
  only with a traced consumer; `checkpoint_updates` goes with Phase 1; the engine
  already ignores the classifier's own `assumptions` prose
  (`ai_builder_discovery_decision_engine.py:115-119`). Evidence rules stay.

Create proposal
- Shape unchanged. Boundary closure in two steps: first the proven defect (model
  duplicates of projected `result_keys` are pruned; END STATE says reject), then each
  raw-JSON normalizer only with captured evidence that its route no longer needs it
  (strict-capable routes already reject malformed nesting at the provider; the
  normalizers exist for non-strict routes and were added from specific captures).
- The prompt rule that asks the model to restate server-known source facts as
  `output_fields` (`ai_builder_plan_proposal_task.py:126`) is rewritten so projected
  obligations are never re-authored; a duplicate is then a rejection with the exact
  path, repaired at most once.
- `output_fields` recursion stays. A flat parent-id concept list is adopted only if
  the non-strict failure family survives the normalizer deletions; it trades malformed
  nesting for dangling or cyclic ids and is not free.
- Step-name duplicates are disambiguated in-process in create as in edit
  (deterministic, visible, lossless), so they stop costing a repair.

Edit proposal
- `review_mode` leaves both edit step schemas and `ModifyExistingStep`; `model_ref`
  leaves the modify schema (already refused by `_validate_target_step_model`,
  `ai_builder_plan_edit_context.py:505-528`). Edit compilation gains the
  deterministic checkpoint projection it lacks today (4.4).

Repair
- Tool choice stays lane-aware; typed decline stays a tool call. A text-only response
  is a provider-protocol failure: one forced tool retry (the one allowed follow-up
  call), then a typed `proposal_tool_call_missing` failure. `looks_like_information_request`
  is deleted once receipts show no legitimate prose outcome on supported routes
  (today it decides whether to show model prose as a question; questions are
  server-owned).
- Cap: `MAX_PROPOSAL_PROVIDER_CALLS` 4 → 2 (initial plus one repair), landed only
  after the two server-mechanics families in section 3 are resolved by their compile
  and assembly owners, so that the cap removes nothing an accepted plan needs (sealed
  evidence: one accepted plan in 486 used a third call, none a fourth, and both
  families are non-repairable by ruling). Deleted with the cap: fingerprint
  progression, `SELF_CORRECTION_BUMPED_TEMPERATURE`, escalating preambles,
  failure-code recipes for server-known mechanics, unreachable failed-turn branches.
  A floor breach in the cohort is a rollback.

### 4.4 Checkpoint authorization: one owner

Principle: a runtime pause is a decision the user makes through the same owner as
every other architecture-shaping decision, the question catalog and structured
answers. The model's reading is the recommendation, never the decision.

Design:
- Three catalog slots `review_checkpoint_transcript`, `review_checkpoint_structured_result`,
  `review_checkpoint_report_text` (family `human_review`, impact `architecture`),
  options `no_pause`, `pause_view`, `pause_edit`, sv/en copy and an `example`
  consequence line ("Varje körning stannar tills en person har godkänt …").
- New vocabulary set `USER_DECIDED_SLOT_NAMES` in `ai_builder_slot_vocabulary.py`:
  model evidence for these slots is never commit-grade (`ResolvedSlot.is_commit_grade`
  returns false for `source == "model"` when the name is in the set). A classifier
  reading therefore yields `recommended_option_id` + `recommended_option_evidence`
  (`ai_builder_discovery.py:857`) and an architecture-impact issue the engine asks
  ahead of confirmation, outside the ordinary budget. A question is raised only when
  a reading exists; flows without a pause never see it.
- Classifier: the `checkpoint_updates` domain is deleted; readings arrive through
  `slots` (values above). **The current-message quote rule this depends on does not
  exist for ordinary slots and Phase 1 must add it.** `_validated_evidence_level`
  (`ai_builder_slot_classification_contract.py:1402`) grades any `user_message`
  source with no `question_id` as `explicit`, without comparing its id to
  `current_user_message_id`; the comparison exists only on the checkpoint-specific
  paths at `:594-607` and `:663-702`, which this phase deletes. At typed admission,
  a slot in `USER_DECIDED_SLOT_NAMES` retains only evidence whose `message_id`
  equals `current_user_message_id`. Negative tests: an earlier user message,
  attachment-only evidence, and mixed current-user and attachment evidence.
  "Remove the review" in edit mode reads as `no_pause`.
- Create compilation: `CheckpointIntent` becomes a compile-time value (producer kind,
  operation, mode) derived in `create_compile_context_from_planning_state` from the
  three slots: `pause_*` → `set`, `no_pause` → `clear`, unanswered → no intent.
  `authorized_requirements_version` is deleted with the lifecycle it belonged to;
  nothing about authorization survives in the type.
- Edit compilation: the baseline is the flow's canonical snapshot
  (`baseline_spec_from_flow_steps`, `ai_builder_checkpoint_contract.py:249-259`);
  `compile_ordered_edit_proposal` applies `project_checkpoint_intents` with the
  derived intents over that baseline and `checkpoint_intent_mismatches(...,
  baseline_spec=...)` proves set, clear and preserve-baseline before the preview
  exists. `current_option_id` for the question is the producer's baseline review
  mode, resolved through the same resolver (never a second copy in discovery). The
  delegation rule "a recommendation while editing equals the current value"
  (`ai_builder_server_decision_dispatch.py:275-311`) is unchanged and means a
  classifier reading that differs from the baseline is shown as a proposal, not a
  recommendation.
- Compaction replay: a structured answer is retained by compaction today
  (`ai_builder_conversation_compaction.py:436-480`) and is part of the complete record
  after Phase 4, so the answer survives in both orders of landing.
- Disclosure: the slot renders as an ordinary resolved requirement with
  `question_id`; the existing "Ändra" control reopens it; no bespoke row text.
- Critic and apply gate: the critic entry `checkpoint_intent_mismatch` becomes
  unreachable on the normal path once both lanes project deterministically and is
  deleted with its tests; the apply-time parity gate stays as the postcondition.
- Deleted: `CheckpointCandidate`, `checkpoint_candidates`, persisted
  `checkpoint_intents`, `checkpoint_candidate_changes_authorized_behavior`,
  `_carry_forward_checkpoint_state`, `_merge_model_checkpoint_updates`,
  `authorize_checkpoint_candidates`, `checkpoint_candidates_require_confirmation`, the
  ack-path fixed-point block, `_checkpoint_changes_for_disclosure`,
  `_checkpoint_decision`, `ClassifiedCheckpointUpdate`, its schema and metadata
  models, and their tests.
- UX cost: one click for users whose own words raised a pause. Under the BALANCED
  rule this is "what shapes the flow": the run contract's `steps_requiring_review`
  changes and API callers block until the pause is resolved. This is a product
  decision (O1) and an explicit entry gate for Phase 1; "no separate checkpoint
  question" in today's review packets was a packet constraint, and no tracked product
  decision records it.

Why not the disclosure-hash promotion the dirty tree implements (green-lit at
iteration 3 today): it is correct and safer than HEAD, but it is a second
authorization mechanism beside structured answers, it needs carry-forward and a
fixed-point re-render to stay consistent, and the confirmation-oscillation class it
defends against disappears by construction when the decision is a replayed answer.
O2 decides whether it lands at all; the default is to hold it on a side branch and
let Phase 1 replace it without the churn of landing first.

### 4.5 Language policy

Facts: Swedish-first product; every user-facing string has sv/en keys (platform rule
in `AGENTS.md`); the corpus is 100 % Swedish; `ui_language` is the account locale and
cannot detect the prompt language; the model answers in the user's language on its
own; `test_ai_builder_vocabulary_neutrality.py` pins sv/en parity of the matchers.

Policy:
1. Keep sv/en for everything the server shows the user (questions, disclosure,
   refusals, compiled step scaffolding). When a slice touches a module with scattered
   `if ui_language == "en"` literals, move them into one copy owner for that module;
   no standalone sweep.
2. Delete the heuristic language detector; `ui_language` is the only language
   source; absent means `sv`.
3. Delete matching tables as whole families, both languages at once, only when a
   typed owner (quoted slot readings, structured answers, `edit_context`) or a
   structural owner (MIME, placeholders, declared schemas, the screen a message was
   sent from) holds the meaning. Keep language-neutral technical tokens (`pdf`,
   `docx`, `json`, `api`) where a deterministic structural rule needs them. A family
   with no owner yet is retained and listed as such; it is not a deletion target.
4. No investment in English paraphrase or translation metamorphic tests. One English
   smoke case per major archetype is enough to prove the model path;
   `test_ai_builder_vocabulary_neutrality.py` dies with the last matching family it
   guards.

Families (module, lines, tables; class a = technical token, b = open-ended intent),
with the owner that replaces each and the cohort that proves it:

| Family | Modules | Lines | Tables | Replacing owner | Cohort |
| --- | --- | --- | --- | --- | --- |
| Shared normalizer and stemming | `ai_builder_discovery_text_matcher.py` | 103 | 2 (a) | deleted last, with the last consumer | n/a |
| Input/output clause role scoping | `ai_builder_intent_markers.py`, `ai_builder_clause_segmenter.py` | 521 | 10 (b) | slots `primary_runtime_input`, `terminal_output` with quotes | input-type and terminal-output cases |
| Output intent, DOCX/PDF modes | `ai_builder_keywords.py`, `ai_builder_framework_policy.py` | 1,258 | 14 named + 5 inline (a/b) | `terminal_output` slot; `docx_output_mode` / `pdf_generation_mode` policy-derived from template evidence (decision 8) | document-output and template cases |
| Primary runtime input | `ai_builder_input_architecture_policy.py` | 664 | 14 + 3 inline (b) | `primary_runtime_input` slot, attachment structure | input-type cases |
| Runtime input fields and form intake | `ai_builder_runtime_input_fields.py`, `ai_builder_form_intake_signals.py` | 700 | 19 + 4 (b) | `form_intake` classifier domain, `runtime_metadata_fields` question | runtime-field cases |
| Edit scope | `ai_builder_edit_scope.py` | 371 | 5 (b) | structured `edit_context` + classifier | edit cases |
| Signal inference and vagueness | `ai_builder_discovery_signal_inference.py`, inline tables in `ai_builder_discovery_issue_rules.py` | ≈1,090 | 2 + ≈18 inline (b) | slot confidence and `unknown` decide vagueness; the engine asks | clarification cases (STALL-POLICY applies) |
| Actionability and specification detection | `ai_builder_discovery_decision_engine.py:422-535` (5 inline), `ai_builder_discovery_profile_builder.py:63-106, 491-513` | ≈200 | ≈17 (b) | no typed owner yet; candidate structural owner: the screen/transport the message came from (task composer vs change request vs answer) after the redesigned phase-owned UI | retained until an owner exists |
| Task intent tables | `ai_builder_discovery_profile_builder.py` (remaining tables) | ≈400 | ≈8 (b) | `post_processing_goal` slot | purpose cases |
| Report sections | `ai_builder_output_sections_signals.py` | 265 | 2 + regexes | `example_output_constraints.headings`; markdown heading parsing is structural and stays | section cases |
| Simplest one-step flow gate | `ai_builder_simple_text_transform.py` | 174 | 8 (b) | typed state (its docstring already says the disclosure is not scanned); derive from slots or delete the gate | simple text cases |
| Recognizers on model-authored step text | `ai_builder_critic_invariants.py:992-1023`, `ai_builder_step_transition_policy.py:35-43`, `ai_builder_validation_quality.py:23` | ≈60 | 4 (a/b) | gone with 4.4 and server-owned renderer placement | document cases |
| Field-name alias tables | `ai_builder_source_reader_contracts.py:36-124`, `ai_builder_primary_input_fields.py:7-28` | ≈110 | 18 (a) | FIELD-COLLIDE (exact folded-name identity) | FIELD cohort |
| Legacy id aliases | `ai_builder_canonicalization.py:8-45` | 40 | 2 (a) | delete (prerelease, disposable sessions) | none |
| Proposal prose heuristic | `ai_builder_proposal_retry.py:72-95` | 24 | 1 (b) | provider-protocol rule (4.3) | repair cohort |

### 4.6 Benchmark policy

- One generic harness capability slice (0.3b) lands before the corpus release: assert
  the disclosed `key_decisions` a case declares (topic and, where the decision is
  answered, `question_id`) before confirming; fail on an unexpected question (today's
  semantics); harness self-tests in the same commit. Confirmation itself stays
  content-free and whole-version. Case-authored answers already exist
  (`ai_builder_api_battle_test.py:1270-1286, 3622-3641`); the checkpoint-specific
  case contracts (answers for the review slots, `expected_review_policy` rows) are
  Phase 1 work (1.2), not harness work.
- Cases 173–182, their fixtures and the manifest land as a corpus release (0.4) after
  the broad run on the unchanged corpus (program rollout order), starting a new
  measurement lineage. The release inventory is derived from the case references and
  the manifest, and the gate fails on any unreferenced or unstaged fixture file.
- Cohorts are named predicates evaluated at runtime (the review cohort predicate in
  section 3 is the first), never prose counts.
- Receipts get `phase` and `owner` only where the existing failure families do not
  already carry them (check `ai_builder_receipt.py` first).
- No metamorphic generator (179–182 are authored variants), no LLM judge, no human
  rubric system here; produced-flow quality stays under FLOW-QUALITY.
- The harness is extended in place. `_quality_report` (783 lines) may be decomposed
  into one function per `expected.*` key when 0.3b or 6.1 touches it; no package split
  unless the owner asks (O5), and then as a mechanical move that keeps receipt
  identity and rewrites the 154 tests in the same commit.

---

## 5. Decisions the owner confirms

O0, O1, O2 and O3 are hard entry gates: the phase that depends on them does not start
until the owner has answered, and the answer is recorded in the receipt. O4–O8 apply
their default if the owner is silent.

| Id | Decision | Recommendation / gate |
| --- | --- | --- |
| O0 | Authority: this plan lands on `refactor/flows-tidy-ai-builder`; the program document names `refactor/flows-clean` | Gate for any commit. Owner confirms; 0.1b records it in `master-program.md` first |
| O1 | Checkpoint as a canonical question (4.4) versus the disclosure-hash promotion in the dirty tree | Gate for Phase 1. Recommendation: the question (one owner, one click only when the user asked for a pause) |
| O2 | Hold the dirty checkpoint promotion cohort (c), or land it. Three pieces of it survive O1 and are re-homed rather than discarded: the double projection moves to cohort (a); the prompt paragraph distinguishing a human pause from a dataflow step (`ai_builder_slot_classifier.py:791`) is adapted to the canonical slots in 1.1; and the exact current-user evidence filtering demonstrated at `test_ai_builder_slot_classifier.py:196` becomes the admission filter and its test in 1.1. Everything else in (c) is deleted by Phase 1 | **Answered: hold.** Preserved as a patch plus a README under `.codex/artifacts/`, never landed |
| O3 | Hard cap instead of pruning (4.2): values and refusal copy | Gate for 4.4. Set after the 4.1 measurement; the byte cap binds; refusal keeps apply/create available; proposed copy "Utkastet är fullt. Skapa flödet från planen eller starta en ny session." |
| O4 | Language: bilingual copy stays; matching families deleted in both languages; no English corpus investment | Default: yes to all three |
| O5 | Split `ai_builder_api_battle_test.py` into a package | Default: no; decompose `_quality_report` only when a slice touches it |
| O6 | Corpus population 172 → 182 | Default: accept as a corpus release after the unchanged-corpus comparison; the tracked manifest is the population owner |
| O7 | Model duplicate of a projected `result_keys` name | Default: reject with exact path (one repair), not prune |
| O8 | Delete `ai_builder_canonicalization.py` legacy id aliases | Default: yes (prerelease, sessions are disposable) |

Answered by the owner on 2026-08-21, before any commit:

- **O0: land on `refactor/flows-tidy-ai-builder`.** The operating protocol in
  `master-program.md` records the lane and points here; `refactor/flows-clean` stays
  the program's landing branch for everything else.
- **O1: the canonical structured question** (4.4). Phase 1 replaces the
  disclosure-hash promotion; the question catalog is the single authorization owner.
- **O2: hold cohort (c).** It is preserved as a patch file under `.codex/artifacts/`
  and never landed. With O1 answered this way, Phase 1 deletes most of what (c) adds.

O3 is still open and is set after the 4.1 measurement.

- **O9 (owner, 2026-08-24): quality and smartness are in scope.** The owner
  extended this plan beyond §1's "deleted complexity, not accuracy" verdict: the
  Flow AI Builder must come out of this program measurably better — higher
  conformance, not brittle, no errors, asking relevant questions — with zero
  regression tolerated on any dimension. Concretely: after Phase 0 completes, a
  conformance phase is authored from evidence, not memory: the adjudication ledger
  over the largest failing check families (starting with
  `expected_leaf_output_fields`, ~40 unique cases), each ledger entry classified
  PRODUCT-GAP / CASE-OVERSPEC / BOUNDARY with prompt quotes. PRODUCT-GAP classes
  become targeted quality slices under the same per-dimension no-regression rule
  and cohort measurement as every other slice; CASE-OVERSPEC classes become a
  corpus-wide, prompt-quote-backed contract release per the master program's
  rescored-case discipline, never a per-case loosening. Each authored slice gets
  the standard peer gate before landing.
  **First adjudication complete (2026-08-24), 12-case sample of the 40-case
  `expected_leaf_output_fields` family, full ledger in
  `.codex/artifacts/adjudication-leaf-output-fields-20260824.md`:** 5 PRODUCT-GAP,
  5 CASE-OVERSPEC, 2 boundary; 30 % of the family flips between identical-code
  runs, so ~15 of 40 cases are not adjudicable from a single run. Three product
  mechanisms identified with bundle evidence: (a) whole-plan collapse to one prose
  step with an empty contract while the instruction names every fact; (b) a
  recurring generic six-key report scaffold replacing domain fields; (c) terminal
  steps flattening per-entity arrays into run-level scalars, losing row identity.
  One matcher defect: exact-match naming penalizes plans that use the prompt's own
  words verbatim. A candidate corpus rule exists (whole-word subsequence
  containment, restricted to leaf properties with exact matching kept for entity
  identifiers): 15 of 40 resolve outright, 22 improve. Strongest evidence: for two
  flipping cases the same code produced the exact expected field names in another
  run, so those contracts are achievable and the failure is compilation variance.
  O9 slices are authored from these mechanisms, validated against repeated runs,
  never a per-case loosening.

---

## 6. Phases and slices

Format per slice: owner, reuse, delete, files, acceptance, tests, cohort, risk and
rollback, non-goals. Tick when acceptance and deletions are both done and the receipt
is written.

### Phase 0: isolate, land and baseline the dirty tree

- [x] **0.1 Read-only inventory and owner gates.** Record branch, HEAD,
  `git status --short --untracked-files=all`, `git diff --stat`; group every hunk into
  the cohorts below; derive the fixture inventory from the case references and the
  manifest (expect 10 prompts and 19 attachments, every manifest entry referenced);
  obtain O0, O1 and O2 from the owner. Nothing is staged.
- [x] **0.1b Track the authority.** After O0, one commit: this plan copied to
  `docs/goals/eneo-flows-and-builder-9-of-10/notes/tidy-ai-builder-plan.md` (with the
  local scratch paths of section 3 replaced by artifact-relative references and the
  review trail kept), the worktree-root `refactorplan.md` reduced to a one-line
  pointer, and the operating protocol of `master-program.md` amended with this lane's
  branch, a link to the tracked plan, and the corpus population note, which names
  the tracked manifest as the population owner and the pending case-id range,
  never counts (NO PROSE POPULATION CONSTANTS). This commit precedes every product
  commit; from here the tracked copy is the only authority and checkboxes are ticked
  there.
- [x] **0.1c Repair the migration graph.** `backend/alembic` has two heads at
  HEAD: `202608041200` (module auth client config, which arrived with the upstream
  SSO broker) and `202608201200` (the squashed Builder schema). `202608041200` is a
  direct child of `202608121500`; `202608201200` descends from it through
  `202608201100 → 202608201000 → 202608181000`. Both are committed, so this is not
  the dirty tree's doing, and `alembic upgrade head` fails, which takes down every
  integration fixture (414 errors, all at setup) and any candidate backend build.
  One empty merge revision joins them, in the shape the repository already uses at
  `202607301100_merge_context_usage_and_restart_safe_jobs.py`: annotated
  assignments, a tuple `down_revision`, no `op` or `sqlalchemy` import, empty
  `upgrade` and `downgrade`. Neither committed branch is re-pointed; that would
  rewrite shared history and invent an ownership that does not exist. Its own
  commit, after 0.1b and before 0.3. Acceptance: `alembic heads` returns exactly
  the merge revision; ruff check and format pass on the file;
  `tests/unit/test_alembic_migration_graph.py` and
  `tests/unittests/test_alembic_migration_contract.py` pass;
  `tests/integration/flows` reaches the tests instead of failing at setup.
  **The measurement database is created fresh, never stamped.** Two existing
  databases are on incompatible lineages and neither can be upgraded into this one:
  the repo devcontainer database is stamped `202608181700`, a revision the
  prerelease squash deleted, and the `developz` database is stamped
  `202608161930_call_transcription`, which is absent from this branch's graph
  entirely. Orphaned, not behind: no upgrade path reaches either, and `stamp head`
  would skip the DDL the Builder schema needs. So 0.3 stands up its own PostgreSQL
  for the measurement stack and migrates it from the merged graph, in the pattern
  the program already uses (`eneo-measure-api` and `eneo-measure-worker` over a
  clean read-only worktree, `/version` equal to `DEV-<sha12>`). **Nothing existing
  is dropped**: the owner's devcontainer database, its API key and its space are
  untouched. The measurement stack gets its own key and its own clean measurement
  space, which is required anyway because a measurement space must be clean.
- [x] **0.5 Lane environment.** Done in the lane venv; the devcontainer is not
  needed for the import-linter tests. `lint-imports` was already installed, but every
  console script in `backend/.venv/bin` still pointed at the worktree's former path
  under `.codex/worktrees/`, so the interpreter did not exist and `lint-imports`
  exited 255. The three import-linter tests were failing for that reason alone, not
  for a contract violation. Rewriting the shebang of the 79 affected scripts to the
  current interpreter fixed them: 23 passed. No package was reinstalled.

- [x] **0.3 Baseline on the unchanged corpus, acquired before either product
  cohort lands.**
  The cohorts ×3 and the broad ×1 run against a backend built from clean HEAD, on
  the manifest as tracked at HEAD, with the same repetitions and the same
  evaluator and model identity the candidates will use. A baseline taken after
  (a) and (b) have landed cannot attribute a regression to either, so 0.3 is
  reordered ahead of 0.2 and each cohort is then gated on its own: (a) against
  this baseline, (b) against the validated (a). This receipt is the comparison
  point for every later slice.
  Stack recipe, taken from the running `eneo-measure-api` rather than reinvented:
  bind `/workspace` to a clean read-only worktree checked out at the candidate SHA
  (its own directory, never a borrowed one), set `GIT_COMMIT=<sha12>` so `/version`
  reports `DEV-<sha12>`, mount the settings `.env` at `/runtime/.env` and run from
  `/runtime`, take the venv from a Docker volume, point `POSTGRES_HOST` at this
  lane's own fresh database and `REDIS_HOST` at its own Redis, and mount an
  artifacts directory for the rejected-proposal and raw-classifier captures. The
  worker runs `cd /workspace/backend && bash run.sh`; never `docker restart` a
  worker container. **This branch has no celery.** Flow execution runs on arq, and
  it needs three worker processes, not one: `eneo.worker.arq.WorkerSettings` (the
  general worker, 12 functions, none of them flow-related),
  `eneo.worker.platform_tasks.PlatformExecutionWorkerSettings` (which owns
  `flows.execute`) and
  `eneo.worker.platform_tasks.PlatformMaintenanceWorkerSettings` (reconcile and
  redispatch crons). **A Builder conversation completes without any of them, which
  makes this trap quiet**: the suite runs to completion and only the cases that
  execute their generated Flow fail, as `execution_failure` with "runtime execution
  timed out". Before trusting any acquisition, assert that `flow_runs` contains no
  rows stuck in `queued`; a smoke case that only reaches a plan proves nothing about
  execution. Set the measurement key's `rate_limit` to `-1`, the code's unlimited
  sentinel (`api_key_rate_limiter.py:166`), because a space-scoped key otherwise
  defaults to 5000 requests per hour and a single broad plus cohort acquisition
  exceeds it.
  Four harness guards refuse a badly set up run, and each is right, so satisfy them
  rather than working around them: the harness must be invoked **from the clean
  checkout**, because live release execution requires a clean tracked source
  revision and the lane worktree is dirty; the measurement key must be **space
  scoped**, or the capacity preflight refuses with
  `measurement_key_not_space_scoped`; `--run-suite` is the unfiltered benchmark and
  **cannot be combined** with `--case-id`, `--cohort` or `--max-cases`, so a cohort
  runs as an exploratory suite without it; and `init_db.py` creates an
  "Organization space", so select the measurement space by name rather than taking
  the first row. `app_version` in a suite receipt is the evaluator's own build and
  is a timestamp by convention, in the sealed reference too; the candidate identity
  is verified through `/version` and recorded in the slice receipt.
  Predeclared cohorts, as named predicates over the `cohorts` field of the tracked
  cases file, evaluated at run time and never restated as counts: cohort (a) is
  `attachment_or_template ∪ form_fields ∪ docx`, cohort (b) is
  `document ∪ file_role_discrimination ∪ long_context`. Against the manifest as
  tracked at HEAD those predicates currently select 52 and 15 cases; the predicate
  is the population, not the number. **Do not pass `--cohort` more than once to get
  a union**: repeating it is AND, not OR
  (`requested_cohorts.issubset(case.cohorts)`, `ai_builder_api_battle_test.py:942`),
  so two tags select only the cases carrying both. Evaluate the predicate against
  the tracked cases file at run time, then pass the resulting ids as repeated
  `--case-id`, which is OR. That keeps each cohort one invocation with an exact
  population and no pairing across runs, and it keeps the predicate rather than a
  count as the population owner. For these two predicates the AND would select zero
  cases and the harness would refuse to launch, so this particular mistake fails
  loudly; a two-tag union would not, which is why the rule is written down.
  **The two predicates overlap by 9 cases.** Movement on a shared case is not
  attributable to (a) or (b) alone, so the (b) comparison is read against the
  validated (a) candidate rather than against the 0.3 baseline, and any family
  movement is reported by unique case, never summed across the two cohorts. State the
  minimum detectable effect before the run, and report "inconclusive" when three
  repetitions cannot resolve it.
- [ ] **0.2 Land the product cohorts, one gated commit each, in this order.**
  (a) template nested placeholder materialization, `nullable`, JSON-input form-field
  merge (`ai_builder_template_attachment_contract.py`, `ai_builder_create_compiler.py`
  form-field part, `ai_builder_new_step_models.py`, `ai_builder_new_step_compiler.py`,
  `ai_builder_proposal_intent.py`, `ai_builder_step_tool_schema_fragments.py`,
  `ai_builder_architecture_derivation.py`, `flow_validators.py`,
  `runtime/template_fill_runtime.py`, their tests);
  plus, in `ai_builder_assembly/create.py`, `_TEMPLATE_SOURCE_INPUT_TYPES` and the
  `_assemble_docx_template_fill` hunks that make the reader step optional for
  JSON and text template input, and all three hunks of
  `ai_builder_create_compiler.py` including the double projection;
  (b) multi-source reader/consumer contract (the remaining hunks of
  `ai_builder_assembly/create.py`,
  `ai_builder_assembly/document_report/lowering.py`, `__init__.py`, tests);
  (c) checkpoint admission and promotion (`planning_state.py`,
  `planning_state_builder.py`, `ai_builder_slot_classification_contract.py`,
  `ai_builder_slot_classifier.py`, `ai_builder_conversation_metadata.py`,
  `ai_builder_planner_request_preparation.py`, `ai_builder_requirements_disclosure.py`,
  tests): per O2, held
  (preserved as a patch file under `.codex/artifacts/`, never landed). O2 is
  answered; there is no land-it-last option left to choose. **Cohort (c) also
  carries a known integration defect**, found while establishing this gate:
  `test_accepting_an_inferred_requirement_pins_it_and_converges`
  (`tests/integration/flows/test_ai_builder_session_api_regressions.py`) passes at
  clean HEAD, passes with cohort (a) alone, and passes on the full dirty tree with
  (c) reverse-applied, but fails with (c) present. That establishes cohort (c) is
  **necessary** for the failure, not that it fails alone: (c) was never run in
  isolation, so an interaction with (a), (b) or (d) is not excluded. The distinction
  does not affect what lands, because every tree that lands is a tree without (c). It is the only integration
  failure the uncommitted tree introduces. The mechanism is user-visible, not
  cosmetic: with (c), accepting an inferred requirement no longer carries the turn
  on to the proposal. The dispatch returns `revise_architecture` and its chained
  decision asks the canonical question "Syfte med bearbetningen" instead of
  `GenerateProposal` (`ai_builder_server_decision_dispatch.py:412-451`), so the
  person is asked again rather than shown their plan, which is exactly what the
  assertion at `test_ai_builder_session_api_regressions.py:5800` guards. Held, so
  it never reaches the branch; if O2 is ever revisited, this is fixed before (c)
  could land. This is also direct evidence for O1: the promotion path is repaired
  by replacing its owner, not by patching it inside the held cohort. Attributed
  twice, independently, by two sessions; see
  `.codex/artifacts/integration-sixth-failure-attribution-20260822.md`.
  **The landing rule's owner is the master program's measurement cadence**
  (`master-program.md`, "Measurement cadence"); this plan does not restate it.
  Per slice, this plan owns only the specifics: the named cohort predicate, the
  predeclared noise margin in cases (declared before acquisition and passed to
  `ai_builder_battle_compare.py --noise-margin`), and the comparison lineage,
  always the immediate parent. The comparator's JSON output is the canonical
  evidence; receipts summarize it and cite its path. Everything else — what the
  broad ×1 judges, which floors are frozen, what a confirmed regression means —
  is the master's wording, read there, not paraphrased here.
  Stage by hunk; never stage `.artifacts/` or protected files. Acceptance: each
  commit passes the Builder unit suite, the integration suite and its peer gate,
  **verified in a clean checkout of that commit's own SHA** — a suite run in the
  dirty union cannot prove a cohort separable. The mixed files are
  `ai_builder_assembly/create.py` (a and b) and
  `test_ai_builder_create_compiler_contract.py` (a, b and c). **No production hunk
  straddles two cohorts; one test hunk does**, so landing (a)+(b) together stays a
  fallback, not the default.
  `ai_builder_create_compiler.py` and `planning_state_builder.py` are each single
  cohort and stage whole. One test-level dependency crosses: the new
  `test_template_checkpoint_targets_used_structured_result` constructs a
  `CheckpointIntent` with (c)'s `authorized_requirements_version`; in the (a)
  commit that keyword is `evidence_level="explicit"`, which is what HEAD's model
  requires (`planning_state.py:286-322` at HEAD). **That hunk is therefore
  reconstructed by hand, not selected.** Hunk selection alone would stage a test
  that cannot import against (a)'s own model. Before the clean-checkout gate,
  read `git diff --cached` and confirm three things: the template checkpoint test
  uses `evidence_level`, no `authorized_requirements_version` change is staged,
  and no cohort (b) or (c) symbol appears.
- [x] **0.3b Harness: disclosed-decision assertions.** Generic capability and
  self-tests (4.6), against the tracked corpus. No case contract changes.
- [ ] **0.4 Corpus release.** Cases 173–182, the fixture files the manifest and the
  cases reference, the manifest, and the harness changes that depend on them, as one
  commit; the gate fails on any unreferenced or unstaged fixture file. New lineage
  starts here (O6). **Ordering, single authority: 0.4 runs after 2.1 and 2.2**, as
  section 7 states. It is listed inside Phase 0 because it belongs to the corpus,
  not because it runs there. Nothing measured against the released 182-case corpus
  is comparable to the 0.3 baseline; the first slice after 0.4 either carries a
  no-product-change 182-case baseline of its own or states that its comparison is
  against that new lineage.
### Phase 1: one authorization owner for checkpoints (4.4)

Entry gate: O1 answered (yes, the canonical question).

**This phase has one authorization-changing product-code commit; the case contracts follow separately.** At HEAD the classifier's `checkpoint_updates` create
durable `CheckpointIntent` values directly (`planning_state_builder.py:911-959`), so
any commit that also lets a question or a user-decided slot authorize a checkpoint
has two owners at once.

An earlier version of this plan tried to stage the phase as inert preparation
followed by a cutover. **That is not possible, and the reason is a dataflow, not a
preference.** A catalog template only exists if its id is in
`KNOWN_REQUIREMENT_SLOT_NAMES`, because `_build_catalog` raises otherwise
(`question_catalog.py:1136-1145`). `LLM_RESOLVABLE_SLOT_NAMES` is
`KNOWN_REQUIREMENT_SLOT_NAMES` minus `NON_LLM_RESOLVABLE_SLOT_NAMES`
(`ai_builder_slot_vocabulary.py:42-56`), and that exclusion set holds only
`docx_output_mode`, `pdf_generation_mode` and `mapped_file_limit`. So a new
checkpoint slot is model-resolvable the moment its catalog row exists: discovery
offers it to the classifier (`ai_builder_discovery_runtime.py:592`), the reading is
persisted (`planning_state_builder.py:909`), and `ResolvedSlot.is_commit_grade`
(`planning_state.py:255`) still judges it by the old rule. Adding the catalog row
before the cutover therefore activates a live model-slot path while
`checkpoint_updates` is still live: two authorization owners.

Adding the new slots to `NON_LLM_RESOLVABLE_SLOT_NAMES` temporarily would silence
that, and is rejected: it is a compatibility shim for a state that lasts one commit,
and this lane does not build those.

Design gate first: a packet with slot ids, option copy, the vocabulary rule, the
engine rule, the edit-lane projection and baseline resolver reuse, the compile-time
`CheckpointIntent` shape, and the deletion list; peer loop; a disputed owner is
escalated to the product owner.

- [ ] **1.1 Cutover.** One commit, and the only one in this phase that touches
  product code. It adds the three slots, their options, the sv/en copy and the
  `example` lines to `question_catalog.py`, the family, `USER_DECIDED_SLOT_NAMES`,
  the classifier schema fields and the admission filter that keeps only evidence
  whose `message_id` equals `current_user_message_id` for slots in
  `USER_DECIDED_SLOT_NAMES`. In the same commit it activates them:
  `ResolvedSlot.is_commit_grade` consults `USER_DECIDED_SLOT_NAMES`, so a
  model-sourced reading of a user-decided slot is never commit-grade; the issue rule
  raises an architecture-impact issue that is never assumption-safe when a
  user-decided slot has a model reading and no structured answer, and the engine asks
  it ahead of confirmation, outside the ordinary budget, with recommendation and
  evidence from the reading; edit mode supplies `current_option_id` from the
  producer's baseline review policy through the checkpoint contract's resolver;
  `create_compile_context_from_planning_state` derives compile-time
  `CheckpointIntent` values (producer kind, operation, mode; no
  `authorized_requirements_version`), `pause_*` to `set`, `no_pause` to `clear`,
  unanswered to no intent; `compile_ordered_edit_proposal` projects the derived
  intents over the baseline snapshot and proves parity with
  `checkpoint_intent_mismatches(baseline_spec=...)` before the preview; disclosure
  renders the slot as a resolved requirement with `question_id`.
  And in the same commit it deletes: `checkpoint_updates`,
  `ClassifiedCheckpointUpdate`, `_parse_checkpoint_updates`,
  `_classified_checkpoint_update_schema`,
  `SlotClassificationCheckpointUpdateMetadata`, the prompt paragraph about checkpoint
  updates (keeping the sentence that defines a checkpoint as a pause for a person),
  the candidate and intent collections on `PlanningState`, every function in the 4.4
  deletion list, the promotion path, the carry-forward, `review_mode` on both edit
  step schemas and on `ModifyExistingStep`, `model_ref` on the modify schema, and the
  critic entry `checkpoint_intent_mismatch`. `BUILDER_SCHEMA_VERSION` is bumped and
  the dev database is regenerated.
  Tests, through the complete path: asked when a reading exists and not otherwise;
  budget bypass; edit current option; delegation keeps the current value; a reading
  carries the current-message quote and attachment text never yields one; the
  admission filter rejects an earlier user message, attachment-only evidence, and
  mixed current-user and attachment evidence; answer to intent for set view, set edit
  and clear; unanswered to no intent; a stale confirmation is still rejected; the
  disclosure row carries `question_id`; set on an unreviewed producer; clear on a
  reviewed one; an unrelated edit preserves every baseline review; a model payload
  carrying `review_mode` is rejected at admission; apply parity unchanged. Delete the
  promotion, carry-forward, fixed-point, custom-row and `checkpoint_intent_mismatch`
  tests.
  This commit is large because the phase is one ownership transfer. Split it only if
  a reviewer can name the intermediate state and show that no commit in the split
  leaves two authorization owners reachable.
- [ ] **1.2 Case contracts.** Case-authored answers for the review slots in every
  case the review predicate selects; `expected_review_policy` rows assert the
  disclosed decision through 0.3b's capability. Frontend: nothing new is required
  (question rendering exists); inline rendering on the confirmation card is a separate
  UI slice under `docs/design/ai-builder`.
- [ ] **1.3 Cohort.** Review predicate cohort ×3 plus broad ×1 against the 0.3
  baseline. Acceptance: zero checkpoints compiled without a structured answer; stalls
  unchanged outside the review cohort; floors hold.

### Phase 2: closed proposal boundary (4.3)

- [ ] **2.1 Projected obligations: reject, never prune.** First product slice. Rewrite
  the prompt rule at `ai_builder_plan_proposal_task.py:126`; replace
  `_without_obligated_terminal_field_copies` and `_prune_raw_obligated_field_copies`
  with a rejection naming the exact path (O7); prove provider schema → typed
  admission → compile → final validator with a payload that duplicates a projected
  key and one that does not. Cohort: obligation cases ×3 plus broad ×1.
- [ ] **2.2 Server-mechanics repair families.** Attribute
  `invalid_structured_underlag_projection` and `assembly_plan_invariant_failed` to
  their compile/assembly owners (the observations named in section 3); fix them where
  the deciding inputs are server-known so they fail before provider use or never
  occur; they must stop consuming model retries (NON-REPAIRABLE CODES). Cohort: those
  five cases ×3.
- [ ] **2.3 Transport normalizers, one per commit.** For each of the five
  `ai_builder_tools.py` normalizers: name the capture and route that motivated it,
  state whether STRICT-CAP makes it unreachable on supported routes, delete it with
  its tests when the captured failure is absent in the cohort, keep it (documented as
  a transport adaptation with its route) otherwise. Never delete all five in one
  commit.
- [ ] **2.4 Create-side duplicate step names.** Apply the edit-mode disambiguation in
  create at compile; delete the `duplicate_step_name` repair recipe.
- [ ] **2.5 Repair loop.** After 2.2 is green: `MAX_PROPOSAL_PROVIDER_CALLS` → 2;
  delete `_ProposalRepairRetryState` progression, `SELF_CORRECTION_BUMPED_TEMPERATURE`,
  escalating preambles and server-mechanics recipes; a text-only response gets the
  forced tool retry as its one follow-up and then `proposal_tool_call_missing`;
  delete `looks_like_information_request` only if receipts show no legitimate prose
  outcome on supported routes. Delete unreachable failed-turn branches and tests.
  Cohort ×3 plus broad ×1; a floor breach rolls the slice back.

### Phase 3: understanding call audit (4.3)

- [ ] **3.1 Domain audit.** For each remaining classifier domain list the consumer
  with file:line and its retention need; delete domains with none (start with
  `assumptions` and `contradictions`); bump the schema version; delete parser,
  metadata and tests. Cohort: understanding cohort ×3.

### Phase 4: bounded complete record, pure fold (4.2)

Entry gate: O3 answered after 4.1.

- [ ] **4.1 Measure.** Repeat the session-length query of section 3 on the freshest
  databases and on any staging data; record p50/p90/p99/max messages and bytes and the
  query in the receipt.
- [ ] **4.2 Design gate.** Packet: the persistence checklist answered as in 4.2, the
  mutability invariant and the same-ID replay rule, the fold signature, the
  architecture-commit carrier (the internal-fact predicate, its exclusion in
  `_to_public_conversation` and `conversation_message_to_llm_message`, and the
  absence tests), the cap-admission owner with the complete-turn message table
  behind `MAX_MESSAGES_PER_TURN` (chained commits, the claimed user message and the
  architecture fact included), the per-message cap and the exact size helper moved
  out of compaction, the claim-time check through that helper, the commit-time
  assertion as an internal invariant exception owned by the turn lifecycle in both
  states, the refusal behaviour and copy (O3), the reader list, a determinism proof
  over the captured 172-case conversations. Peer loop first; a disputed design is
  escalated to the owner.
- [ ] **4.3 Architecture commit as a typed fact.** `commit_turn` writes the carrier
  when a commit is stamped; both projections exclude it by the predicate; the fold
  replays it; the side channel and its carry-forward branch are deleted. Tests:
  commit replay, drift check unchanged, the fact absent from the public session
  response and from the exact provider message list.
- [ ] **4.4 Pure fold, cap admission, no pruning.** `build_planning_state(conversation,
  attachment_inventory, flow, policy)`; the fold takes the latest valid mapped-file
  answer; delete both carry-forward entry points and all `_carry_forward_*` helpers;
  move `conversation_serialized_size_bytes`, `_conversation_size_from_message_sizes`,
  the compact serializer and the per-message cap into the cap-admission owner, then
  delete `compact_ai_builder_conversation`, its retention helpers and the call sites
  in `ai_builder_repo.py` and `ai_builder_planner.py`; cap admission at claim and the
  commit-time assertion as in 4.2; same-ID replay with differing content rejected
  after commit; apply/create on a full session stays allowed; docs-site retry
  section updated. Delete the compaction tests; add cap tests (user overflow refused
  at claim with zero provider calls and the reservation proven against the exact
  size helper including separators, the message count asserted for every complete
  logical turn including chained commits, a message over the per-message cap refused
  at write, exact replay accepted, differing replay rejected, and one commit-time
  rollback proof at the lease lifecycle seam) and fold-determinism tests (same inputs →
  same state; each former carry-forward case becomes a fold case). Cohort: broad ×1
  plus the attachment and template cohorts ×3.

### Phase 5: language heuristics (4.5), a candidate inventory

**Nothing below is an authorized slice and nothing below is ticked.** This is the
inventory of families whose primary purpose is phrase matching, recorded so the
work is visible, not scheduled. Twelve preauthorized slices would commit twelve
peer gates and twelve broad runs before any evidence establishes that twelve
slices exist, over a codebase Phases 1 to 4 will have changed. A family becomes a
slice only when its offline replay has identified the typed or structural owner
that settles the cases the tables settled, and that replay also names the family's
cohort. One family is activated at a time.

Gate for every family: (1) list consumers; (2) replay the captured classifier outputs
of the corpus offline and show the typed or structural owner settles every case the
tables settled, or name the cases that will now ask; (3) delete tables, functions and
tests in both languages; (4) cohort ×3 plus broad ×1; stalls are adjudicated under
STALL-POLICY, never fixed by restoring a table.

- **5.1 Language detector.** Delete `infer_discovery_language` and its fallback;
  `resolve_discovery_language` returns `ui_language` or `sv`.
- **5.2 Proposal prose heuristic** (rides 2.5 when its evidence is in).
- **5.3 Simplest one-step flow gate** (`ai_builder_simple_text_transform.py`).
- **5.4 Edit scope phrases** (`ai_builder_edit_scope.py`).
- **5.5 Runtime input fields and form intake** (`ai_builder_runtime_input_fields.py`,
  `ai_builder_form_intake_signals.py`).
- **5.6 Primary runtime input and clause scoping**
  (`ai_builder_input_architecture_policy.py`, `ai_builder_clause_segmenter.py`,
  `ai_builder_intent_markers.py`).
- **5.7 Output intent and document modes** (`ai_builder_keywords.py`,
  `ai_builder_framework_policy.py`).
- **5.8 Signal inference and vagueness rules**
  (`ai_builder_discovery_signal_inference.py`, inline tables in
  `ai_builder_discovery_issue_rules.py`).
- **5.9 Task intent tables** (`ai_builder_discovery_profile_builder.py`, except
  the actionability tables).
- **5.10 Report sections and recognizers on model-authored text**
  (`ai_builder_output_sections_signals.py`, critic and step-transition markers,
  `_VAGUE_NAMES`).
- **5.11 Field-name alias tables** ride FIELD-COLLIDE; legacy id aliases
  (`ai_builder_canonicalization.py`) are deleted (O8).
- **5.12 Actionability and specification detection. Not on the active checklist.**
  There is no justified deletion and no established owner; the candidate is the
  screen or transport the message was sent from. It returns as a slice only when
  evidence establishes that owner, and it is deliberately unticked and uncounted
  until then.
- **5.13 Shared normalizer** (`ai_builder_discovery_text_matcher.py`) and
  `test_ai_builder_vocabulary_neutrality.py` die with the last consumer.

### Phase 6: docs and burn-down

- [ ] **6.1 Receipt fields.** `phase` / `owner` receipt fields where the existing
  families do not carry them (check `ai_builder_receipt.py` first); nothing else in
  the harness.
- [ ] **6.2 Docs.** `docs/flows/flow-developer-quickstart.md` (Builder rules and owner
  table: question catalog owns the checkpoint; conversation is a bounded complete
  record with one mutable open-turn message; session cap), `docs/flows/architecture.md`
  (Builder session row), `frontend/apps/docs-site/src/content/docs/ai-builder.mdx`
  (confirmation, checkpoint question, session cap, retry section),
  `master-program.md` (close the 0.1b note: lineage and population after 0.4).
  Follow the repository's docs writing rules.
- [ ] **6.3 Burn-down.** Grep gates for every deleted symbol in this document; run
  import-linter, vulture and the full Builder suite; route the ten hardcoded English
  fallback strings in the frontend through Paraglide keys; final broad ×3 and the
  release cohort ×5 per the cadence.
- [ ] **6.4 Failure ledger (owner addition, 2026-08-24).** Production failure
  telemetry so operators and harness agents can join a user-visible Builder
  failure to its stored session, reusing the error identity that already
  exists instead of inventing a second vocabulary:
  - `builder_client_errors` table storing the STABLE part of the parsed
    `AIBuilderError` the UI rendered (`phase`, `category`, `code`,
    `request_id` — the part clients branch on; no display text leaves the
    client) plus a client-minted `client_event_id` under a
    `(tenant_id, client_event_id)` unique key — replaying a report is a no-op
    (best-effort deduplication: insert `ON CONFLICT DO NOTHING`, audit only on
    first insert). Unknown or foreign-tenant `session_id` is nulled at write
    and tenant-bound by a composite `(session_id, tenant_id)` FK. Retention:
    referential cleanup by cascade (session, then tenant) plus a 90-day TTL
    step in the existing daily data-retention worker — 90 days is the API's
    maximum queryable window, so older rows have no consumer (fixed
    invariant, owned once in `ai_builder_failure_ledger.MAX_WINDOW_DAYS` and
    read by the API bound, the CLI bound and the TTL step; deletion runs one
    batch per worker transaction, mirroring the flow-run purge loop).
  - `POST /flows/ai-builder/client-errors` (204, behind
    `FlowApiAction.BUILDER_CLIENT_ERROR_REPORT` under the standard Builder
    permission contract, audited with `AuditMetadata.minimal` recording the
    tenant-resolved session, never the client claim), with a real producer:
    `FlowAIBuilderDriver` reports every fresh client-observed parse through a
    deferred fire-and-forget seam (telemetry never queues ahead of recovery
    work; rehydrated committed-turn errors are never reported — the server
    already persisted them; a failed resume carries the caller's known
    session id, not the cleared state). `schema.d.ts` and the audit-action
    labels regenerated through the canonical pipeline.
  - Shared `ai_builder_failure_ledger.py` collector (typed `FailureSummary`
    of `FailureSection`s; the RESPONSE is bounded to 20 families × 5 samples
    with explicit `total_families`/`truncated` accounting and deterministic
    ordering — the grouping scan itself is bounded by the 90-day window and
    TTL, not by row count, a stated decision) over three stores: the builder
    latest-turn failure SNAPSHOT (`latest_turn_state` failure states plus
    committed-with-error; per-turn history is not persisted, the backend log
    owns it, and the time filter is the session's generic `updated_at` —
    current state on recently-updated sessions, not failure history), failed
    and cancelled flow runs by `error_json->>'code'`, and client errors by
    category/code (phase and category typed into the public contract as the
    canonical enums plus the client-only "client"/"network" values; `code`
    stays a pattern-bounded open identifier so a new client failure mode is
    never dropped). Consumed by `scripts/ai_builder_failure_summary.py` and
    sysadmin `GET /ai-builder/failure-summary/` (super-API-key auth); window
    ownership and the TTL mechanics are in the retention bullet above.
  - Deliberately NOT built, decided rather than missed: no admin UI; no rate
    limiter on the authenticated endpoint (per-tenant auth plus dedup; spam
    requires fresh UUIDs from an authenticated Builder user in their own
    tenant); no preaggregation or query-plan evidence (super-API-key operator
    surface, 90-day max window now also the storage TTL, prerelease volume —
    a preaggregated owner is built when real volume gives it a requirement);
    no per-turn backend failure events (the snapshot naming is honest about
    that; persisting a structured failure fact at turn terminalization is a
    recorded future candidate, owned by the turn lifecycle, not this slice).
    Acceptance: unit suites (flows + data_retention), pyright, single Alembic
    head, frontend check+lint+driver tests, and integration tests proving
    persist+audit, replay no-op, unknown-session nulling in row and audit,
    403 without the Builder permission, session-cascade retention, all three
    collector sections against canonically-constructed seeded failures, and
    explicit truncation at 21 families.

---

## 7. What to start with

1. Read-only: 0.1 (cohort inventory, fixture inventory, O0/O1/O2 with the owner).
   Then 0.1b (the plan becomes a tracked program note; the lane note in
   `master-program.md`). Then 0.5, because the deterministic gates depend on it.
2. 0.1c, the migration graph repair, then recreate the measurement database from the
   merged graph. Nothing downstream can be proven while `alembic upgrade head` fails.
3. 0.3, the baseline, on clean HEAD and the manifest as tracked there, before either
   product cohort lands. Nothing measured later is attributable without it.
4. 0.2 (a), gated against that baseline and validated in a clean checkout of its own
   SHA. Then 0.2 (b), gated against the validated (a). Cohort (c) is never landed
   (O2); it stays a patch under `.codex/artifacts/`.
5. 0.3b, the harness disclosed-decision assertions, against the tracked corpus.
6. First product slice: 2.1 (projected obligations: reject, never prune). Smallest
   diff, highest certainty, full cross-contract proof, its own cohort. Write the
   Phase 1 design-gate packet while 2.1's cohort runs.
7. Then 2.2 (the two server-mechanics families), 0.4 (the corpus release, which opens
   a new lineage), Phase 1.

---

## 8. Evidence that would change this plan

- Phase 1 raises clarification turns or stalls outside the review cohort: the issue
  rule is too eager; fix the rule, do not restore promotion.
- 2.1 or 2.3 drops acceptance below the floor on strict routes: the contract or the
  prompt is wrong, not the normalizer; roll back, attribute, fix the owner.
- 2.5 costs an accepted plan that 2.2 did not own: attribute the family; the cap
  stays at 4 until that family is server-owned.
- Phase 4's determinism proof fails, or 4.1 shows sessions near the cap: reopen the
  4.2 design gate with that evidence; no fallback is predetermined here.
- A Phase 5 family deletion increases stalls on the corpus: the classifier prompt or
  evidence rules are the owner to fix; a stall adjudicated as genuine clarification
  changes the case contract under STALL-POLICY.
- Two gate cycles on any slice do not converge: stop and reframe the slice.

---

## 9. Disposition of the original review

| Original section | Disposition | Reason |
| --- | --- | --- |
| §1 verdict: option C | accept | matches END STATE; no rewrite, no patch |
| §1 authorization transaction with decision ids and revisions | modify | one owner via structured questions (4.4); the disclosure hash already pins content |
| §2.1 shape validation is not semantic authority | accept | principle is correct |
| §2.2 duplicated semantic ownership | accept, narrow | real cases: `result_keys` duplication, edit `review_mode`; others already server-owned |
| §2.3 create contract exposes mechanical freedom | reject as stated | measured: no mechanics in create; only `output_fields` recursion and resource refs remain |
| §2.4 repair is a control-flow system | accept | Phase 2.5 |
| §2.5 heuristics own semantics | accept, extend | Phase 5, both languages |
| §2.6 benchmark rewards accidental shape | reject | ≈2–4 % exact topology; invariant style dominates |
| §3 what is sound | accept | all ten items confirmed |
| §4 option comparison numbers | reject | unmeasured; floors already exceed the claimed gains |
| §5.1 data flow diagram | accept as description | no new components |
| §5.2 three decision tiers, four material kinds | modify | one material kind exists (checkpoint); Builder cannot author outbound delivery; no enum |
| §5.3 PlanningState sub-aggregates | modify | no wholesale regrouping; the fold in 4.2 and the checkpoint removal in 4.4 are the owner-level changes |
| §6 current-to-target table | modify | `CreateCompileContext` stays; `pattern_registry` stays; classifier contract not replaced; repair module mostly deleted (agree) |
| §7 checkpoint design (candidate, authorization command, UI groups) | modify | question instead of receipts; UI: existing question rendering |
| §8 ownership matrix | accept as reference | consistent with 4.1 |
| §9 retain / replace / remove lists | modify | keep the "remove" list minus the flat concept graph and pattern removal; add pruning and carry-forward |
| §10 compact `SemanticWorkflowIntent`, flat concept graph | reject by default | evidence-gated fallback only (4.3) |
| §11.1 failure ownership taxonomy | accept | already mostly enforced by NON-REPAIRABLE CODES; use for receipts |
| §11.2 lossless normalization rules | accept | applied in 2.1–2.4 |
| §11.3–11.5 one repair, strict vs non-strict | accept | Phase 2.5 |
| §11.6–11.8 model qualification profile, probes, degradation | reject | no owner; catalog capability ruling |
| §12.1 state machine | accept as documentation | turn control is already deterministic; no state-machine class |
| §12.2 `EvidenceBackedValue[T]` | reject | generic evidence engine; typed per-fact models stay |
| §12.3–12.4 when to ask, safe defaults | accept | equals the BALANCED rule |
| §13 preserve Flow power, source records, invariants | accept | nothing to change |
| §14–15 benchmark assessment, layers, personas, material-aware confirmation | modify | keep the instrument; 4.6 and 0.3b; no persona cohort, no metamorphic framework |
| §16 output-quality evaluation, human gold set, LLM judges | defer | FLOW-QUALITY owns it |
| §17 metamorphic, failure families, cross-model, repetition | modify | repetition protocol already in the cadence; families in receipts; no matrix |
| §18 benchmark package split and case split | modify | optional (O5); alias groups are data and fine |
| §19 ten improvements | modify | ranks 1, 3, 4, 6 accepted in changed form; 2, 5, 7, 10 rejected or deferred |
| §20 slices 0–8 | replaced | section 6 |
| §21 30/60/90 | replaced | section 7 |
| §22 approaches to avoid | accept | add: no per-request classifier domain pruning, no Swedish-only tables |
| §23 product decisions | replaced | section 5 |
| §24 final recommendation and falsifiers | accept in spirit | section 8 |

---

## 10. Review trail

Receipts: 0.2 (a) in
`.codex/artifacts/implementation-receipts/0.2a-template-cohort.md`; 0.3 in `.codex/artifacts/implementation-receipts/0.3-baseline.md`;
0.1, 0.1b, 0.1c and 0.5 in
`.codex/artifacts/implementation-receipts/0.1-0.1b-0.5-inventory-authority-lane-env.md`.

Codex peer loop, session `tidy-ai-builder-plan-review`, model `gpt-5.6-sol`, effort
`xhigh`. Artifacts under `.codex/artifacts/codex-peer-loop-flow-ai-builder-refactor-plan-rewrite-*`.

Pass 1 (plan, iteration 1): `changes_required`, MIN_SCORE 8.

| Finding | Disposition | Where |
| --- | --- | --- |
| P1 Phase 0 unauthorized (branch authority, corpus order, user-owned dirty tree) | accepted | O0; Phase 0 reordered: product cohorts, unchanged-corpus baseline, then the corpus release |
| P1 D3 misstates tool choice; typed decline; cap needs evidence; floor breach is rollback | accepted | 4.3 Repair; section 3 ladder evidence; 2.2 before 2.5; rollback wording |
| P1 D1 leaves no complete edit path; `authorized_requirements_version` must not survive; reuse the baseline resolver | accepted | 4.4 edit compilation; compile-time intent; 1.5 |
| P1 D5 underspecified; keep `PlanningState` authoritative via typed deltas | accepted the specification gap, rejected the alternative | 4.2 answers the persistence checklist; "Rejected alternative" paragraph |
| P1 `session_full` is a product regression without measurement | accepted with evidence | section 3 session lengths; 4.1; O3; apply stays allowed on a full session |
| P2 D2 mixes a proven defect with unproven normalizer deletions | accepted | 2.1 first; 2.3 one normalizer per commit with route evidence |
| P2 D4 "static schema" premise is false | accepted | 4.3 Understanding: parameterized schema stays |
| P2 D6 is a direction, not a slice | accepted | 4.5 table with owner and cohort per family; 5.12 retained family |
| P2 D7 must not mutate the frozen corpus yet | accepted | 4.6, 0.3b, 0.4 |
| P3 delete the old plan's speculative content rather than soften it | accepted | original kept only as an untracked reference; section 9 |

Pass 2 (verification, iteration 2): `changes_required`, MIN_SCORE 8.

| Finding | Disposition | Where |
| --- | --- | --- |
| P1 authority override recorded too late (Phase 6) | accepted | 0.1b before any product commit; section 2 |
| P1 "append-only" is false: open-turn message is re-persisted; same-ID replace | accepted (verified `ai_builder_repo.py:1175-1192, 1797-1810`, `ai_builder_planner.py:430-489`) | 4.2 mutability invariant; 4.4 tests |
| P1 hard cap at the wrong write point | accepted | 4.2 cap admission at claim with output headroom; commit assertion |
| P1 duplicate mapped-file event; no architecture-commit carrier exists | accepted (verified `planning_state_builder.py:216-290`, `ai_builder_server_decision_dispatch.py:367-381`) | 4.2: mapped-file stays derived; one typed carrier for the commit; 4.3 |
| P1 corpus release inventory incomplete | accepted (10 prompts + 20 attachments; manifest 10 → 29) | section 3; 0.1; 0.4 derives the inventory and fails on unreferenced files |
| P1 harness work duplicated across 1.6 / 6.1 / Phase 6 | accepted | one generic slice 0.3b before the corpus release; case contracts in 1.6; 6.1 reduced to receipt fields |
| P2 "17 review cases" is a prose count | accepted | named predicate in section 3 (9 at HEAD, 17 dirty), evaluated at runtime |
| P2 O1/O2/O3 cannot default through silence | accepted | section 5: hard entry gates; O2 default is hold on a side branch |
| P2 evidence not reproducible from the packet | accepted | section 3: sealed receipt path and query; session SQL and per-database output |
| P3 do not commit the original review | accepted | header: all four working documents stay untracked |

Pass 3 (verification, iteration 3): `changes_required`, MIN_SCORE 8. Codex
independently verified the sealed call ladder (486 observations, max three calls),
the review predicate (9 / 17), the corpus populations (172 / 182) and the manifest
growth (10 → 29).

| Finding | Disposition | Where |
| --- | --- | --- |
| P1 an untracked plan cannot be the durable authority | accepted | header; section 2; 0.1b commits the plan as a tracked program note and leaves a pointer |
| P1 no projection hides a metadata-only message | accepted (verified `ai_builder_router.py:409-421`, `ai_builder_planner_request_preparation.py:1007-1013, 1075-1110`) | 4.2 carrier paragraph: typed internal-fact predicate excluded in both projections, absence tests; 4.2 gate; 4.3 |
| P1 output-token allowance does not bound persisted bytes | accepted | 4.2 cap admission: computed maximum turn envelope per terminal branch with the persistence serializer; commit never refuses; post-commit `session_full` state with a defect diagnostic; 4.4 tests |
| P2 the cap design would delete its size owner | accepted | 4.2 and 4.4: `conversation_serialized_size_bytes` and the compact serializer move into the cap-admission owner |
| P2 fixture inventory still wrong (19 attachments, not 20) | accepted (the earlier count included the modified manifest) | section 3; 0.1 |
| P2 Fable preauthorized without an owner request | accepted | section 2, Phase 1 gate, 4.2 gate: escalate to the owner; Fable only if the owner asks |
| Simplicity 6: no side-branch commit for O2 | accepted | O2 and 0.2 (c): preserved as a patch under `.codex/artifacts/`, never landed unless O2 says so |

Pass 4 (verification, iteration 4): `changes_required`, MIN_SCORE 8. Codex verified
every pass-3 disposition except the cap design; one P1 remained.

| Finding | Disposition | Where |
| --- | --- | --- |
| P1 the "maximum turn envelope" is not computable (persisted contracts unbounded); the post-commit `session_full` state is a wrong owner | accepted (verified `ai_builder_conversation_compaction.py:45-84`, `ai_builder_domain_models.py:74-78`, `ai_builder_proposal_submission.py:832`, `ai_builder_proposal_intent.py:770-790`) | 4.2: bound from code facts (per-message cap moved out of compaction, enumerated messages per terminal branch, schema limits on persisted model text); `session_full` stays a claim-time error, never a status; commit asserts and a breach rolls back through the savepoint to the existing post-provider failure owner; no post-commit state; 4.2 gate and 4.4 updated |

Pass 5 (verification, iteration 5): `changes_required`, MIN_SCORE 8. Codex accepted
the cap redesign except for two mechanical points and one redundancy.

| Finding | Disposition | Where |
| --- | --- | --- |
| P1 claim-time arithmetic omits JSON separators | accepted (verified `ai_builder_conversation_compaction.py:157`) | 4.2: the reservation builds the worst-case candidate and asks the moved `_conversation_size_from_message_sizes`; no handwritten arithmetic |
| P1 wrong failure owner (`ai_builder_proposal_submission.py:832` covers proposals only; `PlanningStatePayloadTooLargeError` is a public terminal error, not outcome-unknown) | accepted (verified `ai_builder_send_lease.py:113-130`, `ai_builder_session_transitions.py:49-66`, `ai_builder_planner.py:230, 551`) | 4.2: internal invariant exception; the turn lifecycle owns it, `OPEN → FAILED_BEFORE_PROVIDER`, `PROCESSING → PROVIDER_OUTCOME_UNKNOWN`; 4.4 tests at that seam |
| P2 field-specific schema limits redundant and unspecified | accepted, deleted | 4.2 and 4.4: one storage invariant, the per-message cap |

Pass 6 (verification, iteration 6): `green`, GREEN_LIGHT yes, MIN_SCORE 8, no
findings. Codex's standing verification items for the implementer: confirm O0 and
commit the tracked authority through 0.1b before any product change; keep the
complete-turn branch table as review evidence at the 4.2 gate; derive and test
`MAX_MESSAGES_PER_TURN` from that table, never hand-copy the value; set O3 only after
the 4.1 measurement rerun; run the implementation peer gate against a stable Phase 4
candidate, not intermediate edits. Green covers the plan; every implementation
slice is reviewed on its own.

Codex peer loop, session `tidy-ai-builder-phase0`, model `gpt-5.6-sol`, effort
`xhigh`, blocking skepticism, source packet over this plan, the Phase 0 execution
scope and the O0/O1/O2 answers. Artifact under
`.codex/artifacts/codex-peer-loop-tidy-ai-builder-phase-0-scope-*`.

Pass 1 (plan, iteration 1): `changes_required`, MIN_SCORE 8. Codex independently
verified the branch, HEAD and diff totals, the 172/182 corpus populations, and that
all 29 manifest fixtures exist, hash correctly and are referenced, as do all 20
prompts.

| Finding | Disposition | Where |
| --- | --- | --- |
| P1 cohorts (a) and (b) are not independent as mapped; `create.py` is a third mixed file; the double projection belongs to (a); `planning_state_builder.py` is not mixed | accepted, and independently reached here first (verified `ai_builder_create_compiler.py:219-286`, `create.py:96-99, 1153-1181`, `planning_state_builder.py` all five hunks) | 0.2 (a), (b) and the risk inventory |
| P1 Phase 0 measures too late to attribute a regression to (a) versus (b) | accepted | 0.3 reordered ahead of 0.2; each cohort gated on its own; section 7 |
| P1 Phase 1 exposes the question mechanism before deleting the model-authored path, leaving two authorization owners | accepted | Phase 1 entry gate; the staging this produced was itself wrong and pass 4 replaced it, see below |
| P1 the current-message quote rule 4.4 relies on does not exist for ordinary slots | accepted (verified `ai_builder_slot_classification_contract.py:1402-1425`; the comparison exists only at `:594-607` and `:663-702`, both deleted by this phase) | 4.4 classifier paragraph; the admission rule and its negative tests |
| P1 corpus-release ordering has two authorities (Phase 0 versus section 7) | accepted | 0.4: section 7 is the single authority, 0.4 after 2.1 and 2.2, with the new-lineage consequence stated |
| P2 three pieces of held cohort (c) survive O1 and must be re-homed | accepted | O2 row: double projection to (a), the human-pause prompt paragraph to 1.3, the current-user evidence filtering to 1.1 |
| P2 the 0.1b documentation candidate adds a prose population owner, against NO PROSE POPULATION CONSTANTS | accepted (verified `master-program.md:536-539`) | the lane note names the manifest and the pending case-id range, not counts; the stale "158" parenthetical removed |
| P2 "a slice that only adds is wrong" manufactures cosmetic deletions in harness, corpus and catalog slices | accepted | section 2: the rule is scoped to ownership-transfer and refactor slices |
| P2 Phase 5's thirteen preauthorized slices are premature and 5.12 proposes an owner it admits is unjustified | accepted for 5.12, rejected for the rest | 5.12 removed from the active checklist; Phase 5 stays an inventory whose families are resliced as each gate provides evidence, which the per-family gate already requires |
| P2 the Phase 4 cap reservation is not executable against the real constants, and the forced-breach matrix tests impossible defenses | accepted (verified `ai_builder_conversation_compaction.py:43-46`: 60 messages, 256 KiB per message, 1 MiB per session) | 4.2: O3 closes only with the arithmetic written out and the usable turn count stated; one rollback proof instead of the matrix |
| Assumption: nothing listens on `:8223`, so the backend identity claim is unobservable | rejected with evidence | the reviewer's sandbox has no network or Docker access; `curl http://127.0.0.1:8223/version` returns `{"version":"DEV-20260821T135557Z"}`. The finding underneath it stands and was already the plan's position: that backend is not measurement-valid, because the version is a timestamp rather than `DEV-<sha12>` and the process serves a borrowed checkout |
| Session-length evidence describes harness sessions capped at six interactions, not human use | accepted | 4.1 records the result as harness and staging evidence only; no database query establishes future human behaviour for an unreleased product |

Pass 2 (commit gate, iteration 2): `changes_required`, MIN_SCORE 8. Codex verified
each pass-1 disposition against the files rather than the description, and audited the
Alembic repair.

| Finding | Disposition | Where |
| --- | --- | --- |
| P1 the Alembic repair is right in shape but not commit-ready: unused imports fail ruff, the shape differs from precedent, and the plan has no slice owning it | accepted (verified: ruff reported 3 unused-import errors; precedent is `202607301100_merge_context_usage_and_restart_safe_jobs.py`) | new slice 0.1c; the revision rewritten to the precedent shape as `202608211200_merge_module_auth_and_ai_builder_heads.py` |
| P1 revision `202608181700` is absent from the graph, deleted by the prerelease squash, so the measurement database is orphan-stamped and cannot be upgraded; `stamp head` would skip the DDL | accepted (verified: no file in `backend/alembic/versions/` carries that revision) | 0.1c: the database is dropped and rebuilt, never stamped |
| P1 Phase 1 still permits dual authorization: 1.1 changes `is_commit_grade`, 1.2 makes the engine ask, 1.3 replaces the classifier contract, and deletion waits until 1.4 and 1.5 | accepted | Phase 1: 1.1 to 1.3 reduced to data-only preparation, 1.4 named as the single cutover commit |
| P2 the "no straddling hunk" claim is false: the new template test embeds cohort (c)'s type change, so it cannot be selected, only reconstructed | accepted | 0.2 staging note: the hunk is reconstructed by hand and `git diff --cached` is read before the gate |
| P2 the held (c) patch is not self-contained; it omits the compiler-test migration hunks | accepted | patch regenerated with those seven hunks (24 files, 2,066 lines) and a README naming what it deliberately omits and why |
| P2 Phase 5 is still a preauthorized execution plan: twelve checkboxes, twelve gates and twelve broad runs before evidence says twelve slices exist | accepted | Phase 5 is a candidate inventory; all twelve entries are no longer checkboxes and one family is activated at a time |
| P2 Phase 4 still lists the forced-breach matrix the design text rejects | accepted | reduced to one commit-time rollback proof |
| P2 0.1b's own instruction still says "172 → 182"; O2 still offers "or landed last"; section 7 says "before anything lands" although 0.1b, 0.1c and 0.5 precede it | accepted, all three | 0.1b, 0.2 (c) and section 7 |
| Correction to the implementer's brief: the two heads do not share a parent; `202608041200` is a direct child of `202608121500` while `202608201200` descends through three revisions | accepted | 0.1c states the actual topology |

Pass 3 (verification, iteration 3): `changes_required`, MIN_SCORE 8. Five of the nine
pass-2 dispositions verified fixed; the rest were narrower repeats.

| Finding | Disposition | Where |
| --- | --- | --- |
| P1 Phase 1 still had two execution authorities: the new preamble described an atomic cutover while the operative checklist still changed `is_commit_grade` in 1.1, activated the question in 1.2, removed classifier ownership in 1.3 and deferred edit compilation to 1.5 | accepted; the checklist was rewritten rather than explained around. The replacement claimed 1.1 and 1.2 were inert, which pass 4 then disproved from the slot-vocabulary dataflow | Phase 1, as corrected by pass 4: one cutover commit |
| P1 0.1c was not commit-gated: graph shape is not proof that both branches apply together | accepted | a throwaway PostgreSQL 16 was created and `alembic upgrade head` run against it: it reached `202608211200` with exactly one `alembic_version` row and no DDL conflict |
| P2 the plan still carried the absolute "no hunk straddles two cohorts" beside the test hunk that does | accepted | 0.2 now says no *production* hunk straddles and one *test* hunk does |
| P2 the pyright cleanup left an impossible assertion: `assert candidate.assistant_spec is not None` on a non-optional field | accepted (verified `ai_builder_template_attachment_contract.py:468` against `flow_authoring_spec.py:108`) | assertion deleted |
| P2 the form-field merge was typed with `dict[str, Any]` and `list[Any]` at a new schema chokepoint, although the repository owns recursive JSON types | accepted (verified `json_types.py:7-12`) | `_flow_input_schema_with_form_fields` now casts to `JsonObject` and `list[JsonValue]`; pyright stays at 0 errors |
| P3 `_add_required_string_path` hides no runtime defect: it mutates a copy, rejects incompatible shapes and publishes only after success | acknowledged, no action | the four nested-placeholder tests already cover both branches |

Pass 4 (commit gate, iteration 4): `changes_required`, MIN_SCORE 8. Run by a second
session working the same handoff; the verdict and findings were relayed verbatim and
every mechanism below was re-verified in source here before it was acted on. Codex
cleared the migration revision, the fresh-database upgrade and the cohort evidence
outright.

| Finding | Disposition | Where |
| --- | --- | --- |
| P1 Phase 1.1 cannot be inert: a catalog template must be in `KNOWN_REQUIREMENT_SLOT_NAMES` or `_build_catalog` raises, known slots are model-resolvable unless explicitly excluded, and the live discovery path then offers the slot to the classifier and persists the reading while `checkpoint_updates` is still live | accepted (verified independently: `question_catalog.py:1136-1145`, `ai_builder_slot_vocabulary.py:42-56` where the exclusion set holds only `docx_output_mode`, `pdf_generation_mode` and `mapped_file_limit`, `ai_builder_discovery_runtime.py:592`, `planning_state_builder.py:909`, `planning_state.py:255`) | Phase 1 collapsed into a single cutover commit; the inert-preparation staging is gone, and the temporary `NON_LLM_RESOLVABLE_SLOT_NAMES` exclusion that would have hidden the problem is rejected as a one-commit compatibility shim |
| P1 0.1b contained unrelated policy work: `master-program.md` is `+17 −3`, not `+13 −1`, because of the night-window hunk | accepted, and already the intent | the night window lands as its own commit before 0.1b, so 0.1b's cached diff for `master-program.md` is exactly `13 1` |
| P2 there is no frozen candidate diff; the commits are intentions until staged | accepted | each commit is staged and its `git diff --cached --name-status` and `--numstat` inspected before it is made |
| Codex correction: the bisection proves cohort (c) is necessary for the sixth failure, not sufficient, since (c) was never run alone | accepted | the O2 note now says necessary and states that an interaction with (a), (b) or (d) is not excluded; it does not affect what lands |
| Cleared: the merge revision follows precedent and has the correct two parents; one Alembic head, clean ruff; a fresh PostgreSQL reaches `202608211200`; the integration suite reaches tests | no action | 0.1c |
| Cleared: do not repair or further test cohort (c) for this gate | no action | O2 |
