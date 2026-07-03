# Fable 04: Discovery Attachments Dialog Review

All evidence gathered — including that the "forced follow-up" runtime surface has no production consumer. Writing the full review now.

# Fable 04: Discovery, Attachments, Dialog Cadence, And User Questions

Reviewer: Claude Fable 5 (max effort, source-verified). Repo: `/Users/ccimen/eneo/eneo-flows-clean`, branch `refactor/flows-clean`, 2026-07-03.

## TL;DR

1. The "one option click → requirements summary" behavior is a verified four-part backend pipeline, not a frontend bug: the LLM slot classifier silently resolves the *other* core slot (`terminal_output`) at medium confidence, the architecture gate needs only two slots, the commit dispatcher chains requirements confirmation into the same turn, and the frontend auto-submits single-select answers because `requires_confirm` is never set by any discovery question.
2. Attachments structurally cannot influence discovery: `build_discovery_runtime_result` takes no file input, attachment text is built only inside the `GenerateProposal` branch, `builder_session_files` has no role column, and the context is a role-less "Reference material" blob capped at 4k/12k chars — so an uploaded Word template or law text changes nothing about which questions get asked.
3. The requirements summary renders every resolved slot as a "key decision" regardless of source, so policy defaults and model guesses are presented to the user as things they decided — the cheapest high-leverage fix in this whole review is a source-aware summary (explicit answers = decisions; model/default = assumptions to review).
4. The deterministic discovery stack (~9,000 LOC of keyword predicates across ~19 modules) is mostly scaffolding the live path already half-bypasses via the classifier; the unit tests pin the classifier-less ordering (`final_output_mode` first) while production asks `post_processing_goal` first — the tests promise a dialog production doesn't exhibit. It is also *not* reproducible today, so the audit argument for keeping it is weaker than assumed.
5. Fix cadence at the action-policy/turn-controller layer (evidence-quality gate on core slots + honest summary), feed a minimal typed attachment signal (name, type, inferred role) into discovery, and do not chase ChatGPT-style freeform chat — the structured-question UX is right for this audience; the failure is silent resolution, not structure.

---

## Ratings

| Axis | Score | One-line justification |
|---|---:|---|
| Conversation quality | 3/10 | Underspecified requests get exactly one question, then a summary built largely from defaults and model guesses; uploads are never acknowledged during discovery. |
| Architecture cleanliness | 6/10 | The turn spine (typed decisions, one-phase action policy, server-owned dispatch) is genuinely clean; the discovery rule stack around it is sprawl. |
| Maintainability | 4/10 | ~9k LOC of cross-coupled keyword predicates (`_runtime_metadata_prerequisites_resolved` chains 9 other predicates, `ai_builder_discovery_issue_rules.py:714-742`) plus a parallel LLM path that drifts from it. |
| User intent robustness | 3/10 | Medium-confidence classifier output silently becomes settled architecture fact (`planning_state_builder.py:484-486`) and then blocks all further questions (`ai_builder_action_policy.py:77-78`). |
| Attachment/file semantics | 2/10 | Role-less, discovery-blind, truncated, and invisible in the dialog. |
| Frontend/backend contract clarity | 5/10 | Generated types are mostly used, but a handwritten `AIBuilderPlanEditContext` duplicates `schema.d.ts:8711`, `ChatMessage.metadata` is `Record<string, unknown>` probed in ≥4 places, and `requires_confirm` is dead plumbing. |
| Testability | 6/10 | The spine is well tested (dispatch chaining is characterized); but the discovery characterization tests exercise a configuration production never runs. |
| Production readiness | 4/10 | Tenanted, leased, safe to run — but the flagship first-contact experience contradicts user expectation, and the rule stack will resist the iteration needed to fix it. |

---

## Conversation State Machine Map

Every user message runs one deterministic server turn (`ai_builder_planner.py:110-346`):

1. **Answer interpretation** — `resolve_user_question_metadata` (`ai_builder_user_question_metadata.py:49-103`) validates a structured click, else tries deterministic freeform matching, else calls the LLM adjudicator (`ai_builder_semantic_adjudication.py:32-120`) to map free text onto the pending question's options.
2. **State rebuild + perception** — `build_discovery_runtime_result` (`ai_builder_planner_request_preparation.py:157-168` → `ai_builder_discovery_runtime.py:277-331`) rebuilds `PlanningState` from the conversation (`planning_state_builder.py:147-166`), then calls the LLM slot classifier for unresolved slots (`ai_builder_slot_classifier.py:60-156`), merges results — **medium confidence is enough to fill an empty slot** (`planning_state_builder.py:484-486`) — and applies policy defaults (`planning_state_builder.py:351-435`): `document_material_scope=flexible_document_case`, `runtime_metadata_fields=no_extra_metadata`, `docx_output_mode=generated_docx`, `pdf_generation_mode=generated_pdf`, `structured_analysis_need` derived from `post_processing_goal`.
3. **Question selection** — `analyze_discovery` (`ai_builder_discovery.py:147-226`) runs 18 issue builders (`ai_builder_discovery.py:633-652`) over keyword vagueness predicates, then the decision engine (`ai_builder_discovery_decision_engine.py:83-193`) suppresses by exposure/family/budget/confidence.
4. **Phase choice** — `resolve_turn_control` → `build_planner_action_policy` exposes exactly **one** action via `_phase_priority` (`ai_builder_action_policy.py:144-155`): ask → commit → confirm → propose. Two hard rules: only `primary_runtime_input` + `terminal_output` are core (`ai_builder_action_policy.py:25-28`), and once `architecture_commit` is set, `ask_targets = ()` forever (`ai_builder_action_policy.py:77-78`) — after commit, no question can ever legally be asked again in that session.
5. **Dispatch** — `AskCanonicalQuestion` persists a structured question (`ai_builder_server_decision_dispatch.py:112-191`); `CommitArchitecture` commits, **reloads state, re-resolves turn control, and recursively dispatches `ConfirmRequirements` in the same turn** (`ai_builder_server_decision_dispatch.py:194-246`, characterized by `test_ai_builder_server_decision_dispatch.py:166-198`); `GenerateProposal` is the only branch that reads attachments.
6. **Frontend** — single-select questions auto-submit on click unless `requires_confirm` (`FlowAIBuilderQuestion.svelte:57-60`). All discovery suggestions default `selection_mode="single"` (`ai_builder_discovery_models.py:72`), and nothing in discovery ever sets `requires_confirm=true` (`ai_builder_event_models.py:30`; the only setter in the codebase is `ai_builder_mcp_intent.py:563`). So every backend discovery question is an auto-submit radio list.

**Concrete trace of the reported scenario** ("Jag vill bygga ett transkriberingsflöde"):

- Turn 1: heuristics resolve `primary_runtime_input=audio` (prefix `transkrib`, `ai_builder_discovery_profile_builder.py:69-84`; confidence rules `planning_state_builder.py:869-915`). The slot classifier plausibly also resolves `terminal_output=structured_text` (transcription ⇒ readable text; system prompt steers exactly this way, `ai_builder_slot_classifier.py:280-330`) at medium confidence, which persists. `final_output_mode` is therefore *not* vague (`ai_builder_discovery_issue_rules.py:148-152`), and the first surviving issue is `post_processing_goal` (priority 28, `question_catalog.py:566`) → the exact question in the screenshot.
- Turn 2: the click on `Beslut, nästa steg och uppföljning` resolves `post_processing_goal` (high, structured). `runtime_metadata_fields`, `document_material_scope`, `structured_analysis_need` are already policy-defaulted. Both core slots resolved → `derive_architecture_commit_draft` succeeds (`ai_builder_architecture_derivation.py:37-84`; the `audio_transcription` pattern requires only the two core slots, `pattern_registry.py:380-383`) → commit → chained `ConfirmRequirements` → requirements summary streams in the same turn.
- The user never chose the output artifact — the single most load-bearing decision for their real workflow (Word template fill vs PDF vs plain text) — because a medium-confidence model guess filled it invisibly, and the summary then presents everything as decided.

Note the deterministic test suite promises the opposite ordering: `test_discovery_flow.py:1248-1262` asserts the **first** question for the bare transcription prompt is `final_output_mode` — but those tests call `analyze_discovery` without a classifier result, a configuration production never runs (production always classifies first, `ai_builder_discovery_runtime.py:290-305`).

---

## Attachment Signal Flow Map

```
FlowAIBuilderInput (upload; mimetypes: md/txt/pdf/docx/csv/pptx/xlsx/json — no audio,
                    builderAttachmentRules.ts:4-15)
  → file_ids in send-message body (FlowAIBuilderDriver.ts:406-408)
  → service loads ALL session files + new files each turn (ai_builder_service.py:393-425)
  → persisted to builder_session_files (session_id, file_id, tenant_id — NO role column;
    flow_tables.py:2150-2174; repo attach/list/detach ai_builder_repo.py:336-403)
  → prepare_planner_request:
      • ask / commit / confirm decisions: returns BEFORE any attachment read
        (ai_builder_planner_request_preparation.py:199-208)
      • GenerateProposal only: build_ai_builder_attachment_context
        (ai_builder_planner_request_preparation.py:219-230)
  → role-less "## Reference material" blob, 4k chars/file, 12k total
    (ai_builder_attachment_context.py:9-20, 73-78)
```

What discovery sees of an upload: **nothing except an evidence bit.** `file_ids` on the user message count as "user evidence" for the duplicate-question guard (`ai_builder_question_state.py:120-121`); no filename, mimetype, role, or excerpt reaches the profile, the vagueness rules, or the classifier prompt. `build_discovery_runtime_result` has no file parameter at all (`ai_builder_discovery_runtime.py:277-289`). The assistant never acknowledges an upload during discovery. Confidence: high — this is structural, verified at every layer.

---

## Question Ownership Map

| Concept | Canonical owner today | Verdict |
|---|---|---|
| Dialog cadence (ask vs commit vs confirm vs propose) | `ai_builder_action_policy.py` + `ai_builder_turn_controller.py` + `ai_builder_server_decision_dispatch.py` | Correct owner. Fix cadence **here**, never in the frontend. |
| Which question to ask next | Decision engine + issue rules + priority map (3 modules) | Over-distributed; should collapse into "unresolved slot in pattern-required order". |
| Question copy + options | `question_catalog.py` (bilingual, validated) | Correct and good. Non-slot questions still live in `ai_builder_discovery_questions.py` (507 LOC) — merge. |
| Submit behavior of an option click | `StructuredQuestionPayload.requires_confirm` (backend, `ai_builder_event_models.py:30`) | Correct owner, dead in practice — no discovery setter. |
| Answer interpretation (click/freeform) | `ai_builder_user_question_metadata.py` + semantic adjudication | Correct. |
| Slot persistence + provenance | `planning_state_builder.py` / `planning_state.py` | Correct; this is the audit artifact. |
| Requirements summary content | `ai_builder_turn_controller.py:159-187` | Correct owner, wrong behavior: renders every slot as a user decision regardless of `source`. |
| Frontend session/message state | `FlowAIBuilderDriver.ts` | Correct; Chat re-derives two projections it shouldn't (`FlowAIBuilderChat.svelte:66-77, 136-153`). |
| Attachment lifecycle | Pending: `FlowAIBuilderInput`; persisted: Driver/session/repo | Correct split; missing role semantics on the persisted side. |

---

## Ranked Findings

### F1 — P0 (product): Architecture commits on invisible evidence, then slams the door on questions

- **Problem:** A core slot resolved by a medium-confidence model guess (or shown to no one) counts fully toward commit eligibility. Once committed, `ask_targets = ()` permanently (`ai_builder_action_policy.py:77-78`), and `_dispatch_architecture_commit` chains straight into the requirements summary in the same turn (`ai_builder_server_decision_dispatch.py:206-240`).
- **Why it matters:** This is the observed UX: one click → summary. For the real target workflow (audio → transcribe → legal reference → fill Word template → PDF/DOCX), the terminal artifact and template role are precisely the facts that got guessed instead of asked.
- **Evidence:** `planning_state_builder.py:484-486` (medium fills empty slot), `ai_builder_architecture_derivation.py:46-49` (two slots suffice), `ai_builder_action_policy.py:25-28, 77-78`, `ai_builder_server_decision_dispatch.py:194-246`, `FlowAIBuilderQuestion.svelte:57-60`.
- **Owner/fix:** Action policy. Add an evidence-quality gate: core slots qualify for commit only when `source ∈ {structured_answer, flow_default, requirements_summary}` or `source == "model" and confidence == "high"`. A model-medium core slot becomes an ask target instead (the catalog question already exists). Keep the same-turn chaining — it's fine once the inputs deserve it.
- **Acceptance criteria:** Bare "transkriberingsflöde" prompt yields ≥2 questions (output artifact + goal) before any summary; a session where the classifier resolves `terminal_output` at medium never reaches `requirements_summary` without the user having seen an output question or an explicit assumption confirm.
- **Tests:** Red full-turn test with a stubbed classifier returning `terminal_output=structured_text (medium)`; assert next decision is `AskCanonicalQuestion(terminal_output)`, not `CommitArchitecture`.
- **Risk/trade-off:** +1 question for genuinely simple flows. Mitigate: model-**high** still commits; explicit text ("sammanfatta som text") resolves via heuristic-high already.
- **Confidence:** High on mechanism (every link source-verified); medium-high on the exact classifier output in the screenshot session (static analysis, not a replayed run).

### F2 — P0 (product/architecture): Attachments are planning artifacts the planner can't see until it stops asking questions

- **Problem:** Files influence nothing before proposal generation; roles don't exist anywhere (`flow_tables.py:2150-2174` has no role column; `ai_builder_attachment_context.py:73-78` labels everything "Reference material").
- **Why it matters:** Uploading a Word template *is* an answer to `docx_output_mode=template_fill_docx` and strong evidence for `terminal_output=docx_document`. Today it is ignored, and discovery may commit a contradictory architecture in the same turn the file arrives.
- **Evidence:** `ai_builder_planner_request_preparation.py:199-230`, `ai_builder_discovery_runtime.py:277-289` (no file param), `ai_builder_service.py:393-425` (files loaded every turn — then dropped by non-proposal branches).
- **Owner/fix:** Two-stage. (1) Minimal signal now: pass `[(name, mimetype)]` into `build_discovery_profile` and let the classifier prompt see one line per file ("User attached: mall_beslut.docx (Word)"); a `.docx` attachment plus docx-ish intent makes `docx_output_mode` an ask target and the assistant acknowledge the file. (2) Role model next: `role` column on `builder_session_files` (`template | reference | sample_input | desired_output_example | schema | unknown`), populated by a conservative classifier pass + user-visible chip override. Roles then feed both discovery and the proposal prompt (a `template` role should route the file into template-variable extraction, not the 4k "reference" blob).
- **Acceptance criteria:** Uploading a `.docx` during discovery changes the next question or produces an acknowledgment referencing the file by name; a `template`-role file is never truncated into generic reference context.
- **Tests:** Red test: conversation + attached docx template ⇒ `docx_output_mode` question asked before commit.
- **Risk/trade-off:** Accidental uploads reshaping dialog (the Opus brief's valid concern). Mitigation: roles *unlock questions*, never *resolve slots* — an attachment can make the Builder ask, not assume.
- **Confidence:** High that the gap is structural; medium on the exact role taxonomy (product call).

### F3 — P1 (correctness/testing): The characterization tests pin a dialog production doesn't run

- **Problem:** `test_discovery_flow.py:1248-1291` asserts output-question-first for the transcription prompt; production runs the classifier first and (per F1) skips that question entirely. The deterministic ordering the tests guard is a fiction of the classifier-less configuration.
- **Why it matters:** Green tests certify conversation behavior users never see; regressions in the live cadence are invisible to CI. This also falsifies the "deterministic discovery = reproducible" assumption (see the Keep/Delete section).
- **Evidence:** `ai_builder_planner_request_preparation.py:157-168` (classifier always in path when a client exists), `test_discovery_flow.py:1248` vs the screenshot behavior; `merge_llm_resolved_slots` persistence via metadata replay `planning_state_builder.py:169-196`.
- **Owner/fix:** Add a thin full-turn harness: `prepare_planner_request` with a scripted classifier stub, asserting the *decision sequence* across turns. Keep the pure `analyze_discovery` tests, but rename/mark them as classifier-off skeleton tests.
- **Acceptance criteria:** CI contains at least one test whose failure would have caught "one question then summary" for a bare transcription prompt.
- **Confidence:** High.

### F4 — P1 (product): The requirements summary launders defaults and guesses into "key decisions"

- **Problem:** `_confirm_requirements_payload` lists **every** resolved slot as a `KeyDecisionPayload` (`ai_builder_turn_controller.py:159-187`) with no source distinction; `assumptions` is hardcoded boilerplate (`ai_builder_turn_controller.py:278-287`). `document_material_scope=flexible_document_case` (policy default) and a model-guessed output render identically to the user's explicit click.
- **Why it matters:** Even with F1 fixed, defaults will exist; the summary is the checkpoint where the user should *see* what was assumed. Today it actively hides that, which is why the jump feels presumptuous. Note the confirm gate itself already exists (`propose_plan` blocked until confirmed, `ai_builder_action_policy.py:119-121`) — the product gap is the summary's honesty, not a missing gate.
- **Owner/fix:** Turn controller. Partition by `ResolvedSlot.source`: `structured_answer`/`flow_default` → key decisions; `model`/`policy_default`/`heuristic` → assumptions list, phrased as "Antaget: … — säg till om det ska ändras". The payload already has the `assumptions` field; the frontend already renders it.
- **Acceptance criteria:** A summary for the transcription scenario shows the output format under assumptions, not decisions.
- **Tests:** Unit test on `_confirm_requirements_payload` with mixed-source slots.
- **Risk:** None meaningful; pure projection change. **This is the highest ROI-per-line fix in the review.**
- **Confidence:** High.

### F5 — P1 (maintainability + invariant): The vagueness-rule stack is oversized, cross-coupled, and leaks case-management vocabulary

- **Problem:** ~9,000 LOC of keyword scaffolding: `ai_builder_discovery_issue_rules.py` (743), `ai_builder_discovery.py` (1,059), decision engine (601), profile builder (641), signal inference (804), `ai_builder_framework_policy.py` (1,375), input architecture policy (692), clause segmenter (408), keywords (154), signal confidence (149), text matcher (82), plus `ai_builder_discovery_questions.py` (507) duplicating the catalog's copy for non-slot questions. Predicates chain into each other (`_runtime_metadata_prerequisites_resolved` calls nine siblings, `ai_builder_discovery_issue_rules.py:714-742`); priorities are tuned by magic offsets (`_dynamic_issue_priority_offset`, `ai_builder_discovery_decision_engine.py:229-259`, including a `len(text.split()) <= 7` rule). Marker lists bake in municipal case vocabulary — `kommunärende`, `tjänsteskrivelse`, `remiss`, `ärende` (`ai_builder_discovery_issue_rules.py:126-135, 470-491`; `ai_builder_discovery_decision_engine.py:560-573`; `ai_builder_discovery_profile_builder.py:347-363` `case_like_flow`) — a direct hit on the general-purpose invariant (detecting user phrasing is defensible; naming rules and issue ids around one domain is not, and `looks_like_case_document_family`'s *assumption output* "rapporter, beslut och formella dokument" steers generic users toward a specialty frame).
- **Why it matters:** Every product-behavior change (like F1) must thread this web; the LLM classifier and the keyword stack answer the same question ("which facts are unresolved?") with different logic, and they drift.
- **Owner/fix:** See "Deterministic Discovery: Keep / Delete / Replace" below.
- **Confidence:** High on size/coupling; high on the vocabulary-leak instances cited (anti-slippage flag: no phase-ID leaks found in any inspected file — the planning-vocabulary hygiene is otherwise clean).

### F6 — P2 (product/UX): `post_processing_goal` taxonomy and cadence are wrong for transcription-style flows

- **Problem:** Eight abstract options in an auto-submit single-select (`question_catalog.py:491-556`), several semantically adjacent for this audience (`action_followup` "Beslut, nästa steg och uppföljning" vs `decision_support` "Rekommendationer och vägval" vs `extract_key_information`); goals are not mutually exclusive, yet the control is a radio. In the live path this *quality-impact* question (impact="quality", `question_catalog.py:567`) is asked while the *architecture* question (output artifact) is skipped — inverted priorities from the user's perspective. The screenshot's "duplicated rows" is most plausibly this semantic adjacency; a literal duplicate would require options sharing labels without ids, which the Driver parser tolerates (`FlowAIBuilderDriver.ts:964-968` accepts label-only options; `structuredQuestionAnswer.ts:31-33` keys by `id ?? label`; duplicate keys break the keyed `{#each}` at `FlowAIBuilderQuestion.svelte:126`).
- **Owner/fix:** Catalog: make `post_processing_goal` multi-select (`selection_mode="multi"`), which also naturally adds a confirm button (multi never auto-submits, `FlowAIBuilderQuestion.svelte:41, 214`); tighten the three overlapping option descriptions. Cadence fix comes from F1 (output question stops being skippable).
- **Acceptance criteria:** User can pick "summarize" + "decisions/follow-up" together; no radio auto-submit for this question.
- **Confidence:** High on mechanics; medium on the duplication diagnosis (screenshot not reproducible statically).

### F7 — P2 (frontend contracts): metadata probing and one handwritten wire type

- **Problem:** `ChatMessage.metadata?: Record<string, unknown>` (`protocol.ts:174`) is shape-probed in ≥4 places (`FlowAIBuilderDriver.ts:94-105, 745-750`; `FlowAIBuilderChat.svelte:70-72, 138-150`); handwritten `AIBuilderPlanEditContext` (`protocol.ts:42-49`) duplicates the generated schema (`schema.d.ts:8711`); Chat re-derives `answeredQuestionCount` and `latestUserRequestBefore` that belong on the Driver.
- **Owner/fix:** Type `metadata` as a discriminated union (`question_answer | requirements_confirmed | edit_context | none`), delete the local edit-context type, move the two Chat projections onto the Driver. Do this *before* any SSE/dialog behavior changes so those diffs stay reviewable — but it is cleanup, not the product fix.
- **Confidence:** High.

### F8 — P3 (dead surface): The forced-followup runtime and three sibling entry points have no production consumer

- **Problem:** `DiscoveryRuntimeResult.should_emit_forced_followup` + `followup`, `_count_free_discovery_turns` (`ai_builder_discovery_runtime.py:318-364`), `build_discovery_block_message_runtime` (:249), `analyze_discovery_runtime` (:92), `build_runtime_planning_state` (:225) are referenced only by their own tests (grep across `backend/`: definitions + tests only). The "ask a forced follow-up after 2 free discovery turns" behavior — which sounds like exactly the product's missing conversational persistence — literally never fires.
- **Owner/fix:** Delete the dead fields/functions and their tests, or wire the forced-followup into the turn controller deliberately. Don't leave a mechanism that looks load-bearing but isn't.
- **Confidence:** High (verified by repo-wide grep).

### F9 — P3 (robustness): Freeform "kör" et al. zero the question budget

- **Problem:** `has_build_plan_intent` includes bare `"kör"` and `"fortsätt"` (`ai_builder_discovery_decision_engine.py:476-493`); any message containing them sets the non-architecture question budget to 0 (`compute_question_budget`, :438-451). "Kör" is also just "run" in ordinary Swedish sentences ("varje körning…" is guarded by word boundaries? No — `mentions_any` is substring matching, so "körning" contains "kör").
- **Owner/fix:** Casualty of the F5 restructure; if kept short-term, switch to token matching. Confidence: high that the substring match is over-broad; medium on real-world frequency.

---

## Deterministic Discovery: Keep / Delete / Replace

First, a load-bearing correction to the brief's framing: **the current stack is already not reproducible.** The slot classifier sits in the deciding path of every turn (`ai_builder_planner_request_preparation.py:157-168`); its output determines which questions are suppressed and when commit fires. Temperature 0 plus a 128-entry in-process cache (`ai_builder_slot_classifier.py:22-23`) is not determinism across processes, model versions, or providers. So "keep the keyword rules because municipal audit requires identical questions for identical inputs" defends a property the system does not have. What the system *does* have — and what audit actually needs — is a persisted decision trace (`ClarificationDecisionTrace`, `ai_builder_discovery.py:655-697`) and slot provenance (`ResolvedSlot.source/evidence/confidence`). Reproducibility-by-record, not reproducibility-by-rerun.

**Keep (earns its place):**

- `PlanningState` + slot provenance/confidence — the audit artifact and the contract everything should converge on.
- The turn spine: `ai_builder_action_policy.py`, `ai_builder_turn_controller.py`, `ai_builder_server_decision_dispatch.py` — small, typed, single-phase, well-tested.
- `question_catalog.py` — canonical bilingual copy with validation; exactly the right shape.
- `derive_architecture_commit_draft` + pattern-required slots (`ai_builder_action_policy.py:201-215`) — deterministic mapping from facts to architecture is correct.
- Duplicate-question guard (`ai_builder_question_state.py:41-76`).
- The MVS 2-of-3 floor (`ai_builder_discovery.py:996-1027`) as a cheap sanity gate.
- Policy defaults that are genuinely safe (`document_material_scope=flexible_document_case`) — but rendered as assumptions per F4.
- The two LLM adjuncts (`classify_slots`, `adjudicate_pending_question_answer`) — these are the perception layer of the future design.

**Delete (scaffolding; no behavior worth preserving):**

- The dead runtime surface (F8).
- `ai_builder_signal_confidence.py` word-overlap confidence scoring (:126-149) and the `low_confidence_*` issue injection (`ai_builder_discovery.py:164-188`) — the classifier's own confidence + `unknown` protocol supersedes it.
- `_dynamic_issue_priority_offset` magic offsets and the `≤7 words` rule (`ai_builder_discovery_decision_engine.py:229-259`).
- Case-management marker lists and their assumptions (`looks_like_case_document_family`, `implies_single_case`'s `ärende` needles, `case_like_flow` needles) — invariant violation regardless of the restructure.
- Substring-based `has_build_plan_intent` budget zeroing (F9).

**Replace (one concept, one owner):**

- The 18 issue builders + ~20 `_is_vague` predicates collapse into a single rule: *an ask candidate is a slot that is unresolved, model-`unknown`, or model-`medium` on an architecture-impact question, ordered by catalog `priority_base` within the pattern's `required_architectural_slots`.* The classifier (extended with attachment signals per F2) is the only free-text perception; deterministic parsing remains for structured clicks. Non-slot gates that encode real capability limits (`external_delivery_unsupported`, `comparison_scope_conflict`, `flow_input_architecture`) survive as explicit named gates — they are product policy, not phrasing heuristics.

**Two recommendations by audit posture:**

- **If per-question audit reproducibility is legally required:** keep the *decider* deterministic — the slot-driven rule above is fully deterministic given classifier output — and persist classifier inputs/outputs (already done via `slot_classification_metadata`, prompt hash included) so any question can be explained after the fact. Delete the keyword predicates anyway; they add nondeterminism-masking, not determinism.
- **If not required:** same architecture, plus let the classifier propose the next question directly (constrained to catalog ids) with the deterministic policy as legality check. Either way the deletion set is identical; the audit question only changes who *ranks* candidates.

---

## Frontend Contract Cleanup

Priority order (all subordinate to the backend cadence fixes):

1. Type `ChatMessage.metadata` as a discriminated union; delete the four ad-hoc probes (`FlowAIBuilderDriver.ts:94-105, 745-750`; `FlowAIBuilderChat.svelte:70-72, 138-150`).
2. Delete handwritten `AIBuilderPlanEditContext` (`protocol.ts:42-49`); use `components["schemas"]["AIBuilderPlanEditContext"]` (`schema.d.ts:8711`).
3. Harden `#parseStructuredQuestion` (`FlowAIBuilderDriver.ts:947-973`): derive guaranteed-unique option keys (index-suffix fallback) so label-only duplicate options can't break the keyed each (`FlowAIBuilderQuestion.svelte:126`).
4. Move `answeredQuestionCount` and `latestUserRequestBefore` from Chat onto the Driver as projections.
5. Keep the pending-upload vs persisted-attachment lifecycle split exactly as is (`FlowAIBuilderInput.svelte:47-51`); when F2's roles land, the chip UI (`FlowAIBuilderInput.svelte:208-294`) is the natural place for a role badge/picker.
6. Add one UI-copy line distinguishing "builder context files" from "runtime input" near the attach button — users will try to upload the meeting audio here and silently can't (`builderAttachmentRules.ts:4-15` allows no audio, correctly).

---

## What Current Tests Already Cover

- Same-turn commit→confirm chaining is deliberately characterized (`test_ai_builder_server_decision_dispatch.py:166-198`) — the behavior is intentional, not accidental.
- Deterministic question ordering for bare prompts, classifier-off (`test_discovery_flow.py:1248-1318`, 82 tests in that file).
- Catalog integrity: 71 tests (`test_question_catalog.py`), including dangling-reference guards from the Pattern Registry.
- Planning-state building/merging: 63 tests (`test_planning_state_builder.py`); question state, action policy, turn controller, dispatch, attachment context, slot classifier, semantic adjudication all have dedicated files.
- Vagueness rules have direct unit tests (`test_discovery_issue_builders.py`, `test_discovery_mvs_gate.py`, `test_discovery_output_vagueness_rule.py`) — which is also why deleting them is safe to sequence: the tests document the behaviors to consciously keep or drop.

## Missing Red Tests

1. **Full-turn cadence with classifier stub** (F1/F3): stubbed `classify_slots` returns `terminal_output` at medium ⇒ assert next decision is a question, not commit. Red today.
2. **Attachment-aware discovery** (F2): docx template attached mid-discovery ⇒ `docx_output_mode` asked or acknowledged before commit. Red today (no code path).
3. **Source-aware summary** (F4): mixed-source slots ⇒ policy/model slots land in `assumptions`, not `key_decisions`. Red today.
4. **`requires_confirm` end-to-end**: backend sets it on an architecture-impact question ⇒ frontend renders confirm button (component test) and backend payload round-trips (`exclude_unset=True` in `ai_builder_backend_question_persistence.py:101-108` currently drops it from persisted tool args — assert it survives hydration once actually set).
5. **Post-commit question lockout**: characterize `ask_targets == ()` after commit (`ai_builder_action_policy.py:77-78`) so the F1 gate change is a visible diff, and add the edit-path variant.
6. **Substring budget bug** (F9): "varje körning ska…" must not zero the question budget. Red today.

## What Is Not Worth Fixing

- The `_dispatch_question` text-only fallback path (`ai_builder_server_decision_dispatch.py:171-191`) — rare; leave until the discovery restructure.
- Tuning attachment truncation caps before roles exist — caps are the wrong variable; role routing is.
- Accepting audio as a builder attachment — correct as-is; fix with copy, not capability.
- Tuning `compute_question_budget` thresholds — delete with F5 instead of polishing.
- The per-process classifier cache and its eviction policy — irrelevant at current scale.
- Micro-copy polish of option descriptions beyond the three overlapping `post_processing_goal` options.
- Merging Driver and the Svelte service facade — the boundary is earning its keep.

## From-Scratch Cleaner Discovery Design

If rebuilt from today's learnings, four layers with one owner each:

1. **Fact ledger** — `PlanningState` as-is: slots with value/source/confidence/evidence, versioned, persisted. (Exists; keep.)
2. **Perception** — one structured-JSON LLM call per turn (the slot classifier, extended): input = conversation text + pending-question bias + *attachment signals* (name, type, inferred role, and for a `.docx` template the extracted `{{variable}}` names); output = slot values with confidence, `unknown` protocol, contradictions, secondary obligations. Deterministic parsing only for button clicks and file formats. No keyword vagueness predicates anywhere.
3. **Dialog policy (deterministic)** — ask the highest-priority slot that the chosen/likely pattern requires and the ledger can't answer at commit-grade evidence (explicit, flow-default, or model-high); named capability gates (external delivery, comparison conflict) interleave by explicit priority. Commit when the pattern's required slots are commit-grade; then chain to a **source-aware** requirements summary where everything not explicitly chosen is a labeled assumption with a one-tap "ändra" affordance. The confirm gate before proposal stays exactly as today.
4. **Presentation** — question catalog (exists) + `requires_confirm` reserved for the rare destructive/contradiction gates; multi-select where goals compose.

The striking thing is how much of this already exists: the ledger, the catalog, the pattern-required slots, the action policy, the trace. The rebuild is mostly *deletion* (the keyword stack) plus two behavior changes (evidence gate, honest summary) plus one new input (attachment signals). That is the strongest possible sign the spine is right and the accretion is not.

## Tomorrow Implementation Slices

| # | Slice | Size | Files |
|---|---|---|---|
| 1 | Source-aware requirements summary (F4): partition key_decisions vs assumptions by `ResolvedSlot.source` | S | `ai_builder_turn_controller.py` + tests |
| 2 | Commit evidence gate (F1): model-medium core slots become ask targets, not commit fuel | M | `ai_builder_action_policy.py` (+ derivation guard) + red full-turn test |
| 3 | Attachment presence signal (F2 stage 1): file name/type lines into profile + classifier prompt; assistant acknowledges uploads | M | `ai_builder_discovery_runtime.py`, `ai_builder_planner_request_preparation.py`, classifier prompt |
| 4 | `post_processing_goal` → multi-select + copy dedupe (F6) | S | `question_catalog.py`, i18n check |
| 5 | Delete dead forced-followup surface (F8) + substring budget fix (F9) | S | `ai_builder_discovery_runtime.py`, decision engine |
| 6 | Frontend contract cleanup (F7) as one reviewable PR | M | `protocol.ts`, Driver, Chat |
| 7 | `builder_session_files.role` migration + conservative role classification (F2 stage 2) | L | table, repo, service, UI chips — after 1-3 prove out |

Slices 1-3 are the day-one set; they convert the observed scenario from "one click → presumptuous summary" into "click → output-artifact question → honest summary" without touching the heuristic stack. The F5 deletion program is a separate multi-slice track gated on the audit-posture decision.

## Claims Codex Must Verify

1. The live-turn trace for "Jag vill bygga ett transkriberingsflöde" — that the classifier actually resolves `terminal_output` at medium/high on turn 1 in the deployed model config. My reconstruction is static; replay a session with logging (`slot_classification_metadata` is persisted on the user message, so an existing session's metadata can confirm it).
2. That nothing else sets `requires_confirm` (my grep found only `ai_builder_mcp_intent.py:563`) and that MCP intents don't depend on the current auto-submit default.
3. That `should_emit_forced_followup` / `build_discovery_block_message_runtime` / `analyze_discovery_runtime` / `build_runtime_planning_state` truly have no production consumers (my grep: definitions + tests only) — check dynamic imports/routers before deleting.
4. That removing `low_confidence_*` issue injection (`ai_builder_discovery.py:164-188`) doesn't orphan a UX path some E2E test exercises.
5. `ai_builder_clause_segmenter.py` (408 LOC) and `ai_builder_keywords.py` consumers — I did not trace their full consumer graph; they may serve the proposal/underlag side, in which case they leave the F5 deletion set.
6. Whether `exclude_unset=True` in `_persisted_question_arguments` drops a future explicitly-set `requires_confirm=False` vs `True` asymmetrically (it persists set-True correctly; verify hydration).
7. The interaction of the F1 evidence gate with the **edit path** (`flow is not None`): flow defaults resolve slots at source `flow_default` (commit-grade), which I believe keeps edit sessions from over-asking — verify with edit-path tests.

## Challenge This Brief

- **"Make it more ChatGPT-like" is the wrong north star for this product.** The structured single-question cadence is a strength for municipality non-developers (progressive disclosure, no prompt-writing burden). What users actually experienced is not "too structured" but "concluded without asking". Fix silent resolution and summary honesty; do not add freeform multi-question chat, which would trade a debuggable state machine for prompt magic.
- **`requires_confirm` is a red herring as a primary lever.** Sprinkling confirm buttons on every question slows everyone to protect against a backend problem (invisible slot resolution) that confirm buttons don't fix. Use it only for contradiction/destructive gates.
- **The brief's "attachment context appears only in proposal generation" is confirmed — but full-role plumbing is not the first move.** Name/type signals + acknowledgment deliver most of the product value at ~5% of the cost; the relational role column should follow evidence from real sessions, not precede it.
- **"Deterministic heuristics are load-bearing for audit" deserves active pushback** (see Keep/Delete): the classifier already breaks rerun-determinism; the audit story must rest on the persisted trace either way, which frees you to delete the keyword stack.
- **The strongest defense of the current shape:** every piece of the jump pipeline is individually reasonable (one phase per turn, derive-don't-ask, defaults for safe slots, chaining to reduce round-trips) and each is tested. The system failed by composition, not by any single bad module — which is exactly why the fix belongs at the composition points (action policy gate, summary projection) and not in another heuristic.

## Confidence

- **High:** the four-part jump mechanism and every file:line link in it; attachments-blind discovery being structural; the dead forced-followup surface; the tests-vs-production divergence mechanism; `requires_confirm` being unset by discovery; the summary's source-blindness; the vocabulary-leak citations.
- **Medium-high:** that the classifier resolved `terminal_output` (rather than some other resolution path) in the specific screenshot session — the only claim resting on reconstruction rather than direct evidence.
- **Medium:** the exact attachment role taxonomy; the duplicate-row diagnosis for the screenshot; the size of the F5 deletion set at its edges (clause segmenter, keywords) pending consumer traces.
- **Low:** none of the material findings rest on low-confidence claims; where I could not verify (live replay, screenshot), I flagged it in "Claims Codex Must Verify".
