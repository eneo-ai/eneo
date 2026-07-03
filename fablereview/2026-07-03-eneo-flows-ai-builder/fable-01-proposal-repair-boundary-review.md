# Fable 01: Proposal Repair Boundary Review

I have everything I need. All six artifacts read, all 14 primary source files inspected plus the critic invariants, policy formatting chain, completion adapter, processor/planner event flow, and the four relevant test suites. Delivering the full review below.

---

# Fable 01 Review — Flow AI Builder Proposal Submission / Repair / Self-Correction Boundary

## TL;DR

The provider-facing repair loop is legitimate and well-built; the real brittleness is that three other layers quietly repair things too — broad `except Exception` in both proposal processors routes backend compiler bugs into LLM self-correction (`ai_builder_create_proposal.py:120`, `ai_builder_edit_proposal.py:118`), the intent parser speculatively reshapes malformed payloads before its own strict validation (`ai_builder_proposal_intent.py:412-520`), and quality feedback flattens structured issue codes into prose and then substring-matches that prose back (`ai_builder_create_feedback.py:74-120`).
`CreateFlowIntent` is genuinely strict (`extra="forbid"`, template-var bans) and the backend-key strip in front of it is a sound one-way valve, but the orphan-output-field attachment and misplaced-assumptions recovery are a second, unprincipled repair path that bypasses the principled loop — delete both.
The repair loop's "model asked a question" escape (`ai_builder_proposal_repair.py:622-624`) streams assistant text that is never persisted to the conversation, and the same keyword heuristic silently swallows the model's question on the first attempt (`ai_builder_proposal_submission.py:324-339`) — a product decision owned by a 25-line keyword function in the wrong layer.
Keep: forced tool choice, forced-tool-retry-after-text, JSON-text fallback (it routes through identical validation and costs no extra call), truncation/empty-choice terminals, the 3-retry budget, and `ToolRetryConfig`/`ProposalCompletionFn` (earned seams, not fake ones).
Tomorrow's highest-ROI slice is three small, independent changes: narrow the broad catches to a typed exception set, delete the two speculative intent recoveries, and thread issue codes end-to-end through quality feedback — no rewrite required.

---

## 1. Ratings

| Axis | Score | One-line justification |
|---|---:|---|
| Architecture cleanliness | 6/10 | The intent → compile → prepare → validate → finalize → repair pipeline is a real layered design with typed contracts, but "what makes a proposal valid" is owned by six modules, three of which silently rewrite instead of failing. |
| Maintainability | 5/10 | Individual files are readable and consistently named; the normalization cascade's ordering and interactions are pinned only by ~60 example tests, and feedback correctness depends on prose strings defined in a different module (`ai_builder_critic_invariants.py:477` ↔ `ai_builder_create_feedback.py:81`). |
| Reliability / robustness | 6/10 | Excellent at the provider boundary (truncation, empty choices, budgets, temperature escalation all terminal-safe); weak where broad catches convert bugs into repair fuel and where two text-yielding endgames skip conversation persistence. |
| Testability | 7/10 | `ProposalCompletionFn` + `ToolRetryConfig` give clean injection; 58 tests cover the loop itself. But zero tests pin the broad-catch behavior, and the substring-feedback tests feed hand-crafted prose that keeps possibly-dead branches green. |
| Production readiness | 5/10 | Telemetry taxonomy (`ProposalRepairReason`, failure branches) is production-grade; bug-masking repair, the unpersisted-text turns, and up to ~7 provider calls per proposal turn in the worst case are not. |
| Human reviewability | 5/10 | The typed contracts are a pleasure to review; the ~2,200 LOC of keyword/morphology heuristics (`ai_builder_create_dataflow.py:51-159`, `ai_builder_step_transition_policy.py:44-53`) cannot be verified correct by reading — only by trusting the example tests. |

---

## 2. Repair Boundary Map

Scope size for orientation: repair surface ≈ 1,790 LOC (submission 696 + repair 861 + contracts 199 + parsing 36), processors 483, intent 777, feedback+finalization 515, post-compile normalizers ≈ 2,240 (transition 929 + dataflow 1,190 + prep 122). Worst-case provider calls in one proposal turn: 1 initial + up to 4 self-correction-loop calls + up to 2 forced-after-text calls ≈ **7**.

| # | Branch / function | Classification | Current owner | Proposed owner | Verdict | Evidence |
|---|---|---|---|---|---|---|
| 1 | Provider error / empty choices / `finish_reason=="length"` → terminal error events | MODEL_BOUNDARY | submission + repair | keep as-is | **Keep** | `ai_builder_proposal_submission.py:240-295`, `ai_builder_proposal_repair.py:496-533` |
| 2 | Forced tool choice on first attempt | MODEL_BOUNDARY | submission | keep | **Keep** | `ai_builder_proposal_submission.py:232-239` |
| 3 | Forced-tool retry after conversational text (first attempt) | MODEL_BOUNDARY | submission → repair | keep | **Keep** | `ai_builder_proposal_submission.py:314-322`, `ai_builder_proposal_repair.py:689-781` |
| 4 | JSON-object-text fallback (parse assistant prose as tool args) | MODEL_BOUNDARY | repair | keep — same validation path, zero extra provider call, precedes the forced call | **Keep, narrow only with telemetry** | `ai_builder_proposal_repair.py:696-706, 800-845` |
| 5 | Tool-argument JSON parse failure → self-correction | MODEL_BOUNDARY | submission/repair | keep (bounded) | **Keep** | `ai_builder_proposal_submission.py:547-558`, `ai_builder_tool_parsing.py:11-18` |
| 6 | Self-correction loop, 3 retries, bumped temperature, text-feedback budget | MODEL_BOUNDARY | repair | keep | **Keep** | `ai_builder_proposal_repair.py:61, 96-133, 466-686` |
| 7 | `looks_like_information_request` bail → yield model text, end turn | CONTRACT_BRITTLENESS | repair module via keyword heuristic | turn policy layer — or delete | **Delete (or persist + rehome)** | `ai_builder_proposal_repair.py:621-624, 693`, `ai_builder_interaction_utils.py:48-72` |
| 8 | Broad `except Exception` around create parse+compile → `failure_kind="parse"` repair | CONTRACT_BRITTLENESS | create processor | typed exceptions in processor; unexpected → terminal internal error | **Delete (narrow)** | `ai_builder_create_proposal.py:120-137` |
| 9 | Broad `except Exception` around edit compile → `failure_kind="validation"` repair | CONTRACT_BRITTLENESS | edit processor | same as #8 | **Delete (narrow)** | `ai_builder_edit_proposal.py:118-123` |
| 10 | Backend-owned key strip before `CreateFlowIntent` validation | MODEL_BOUNDARY (one-way valve) | intent parser | keep + add logging of stripped keys | **Keep, instrument** | `ai_builder_proposal_intent.py:56-75, 361-386, 442-462` |
| 11 | Misplaced step-level `assumptions` folded into root | CONTRACT_BRITTLENESS | intent parser | principled repair loop | **Delete** | `ai_builder_proposal_intent.py:376-385, 448-453` |
| 12 | Orphan output-field object attached to previous step, `output_type` defaulted to `"json"`; leading orphan silently vanishes | CONTRACT_BRITTLENESS | intent parser | principled repair loop | **Delete** | `ai_builder_proposal_intent.py:484-520` (silent drop at 509-510, silent default at 520) |
| 13 | Static create retry rules ("do not emit input_source…") for keys that are stripped and can never fail validation | CONTRACT_BRITTLENESS | repair prompt builder | derive retry rules from `failure_codes` only | **Delete static rules** | `ai_builder_proposal_repair.py:380-393` vs strip at `ai_builder_proposal_intent.py:361-373` |
| 14 | Prose substring matching + `str.replace` in quality feedback | CONTRACT_BRITTLENESS | create_feedback | issue-code → remediation registry (already exists: `CREATE_CRITIC_REMEDIATION`) | **Delete / redesign** | `ai_builder_create_feedback.py:74-120` vs `ai_builder_critic_invariants.py:477,500` |
| 15 | Quality failures dropped `failure_codes` while validation failures carry them | UPSTREAM_VALIDATION (structured data lost mid-pipeline) | finalizer | thread codes through `ToolProcessingResult` | **Move earlier / fix** | `ai_builder_proposal_finalization.py:287-293` (has codes) vs `:330-333` (drops them) |
| 16 | Create-mode `uses_previous_fields`/`uses_previous_outputs`/`uses_form_fields` silent pruning | CONTRACT_BRITTLENESS (backend repairing backend) | create_dataflow | assert loudly (typed error) — inputs are backend-generated in create mode | **Redesign to fail** | `ai_builder_create_dataflow.py:195-244, 292-340`; duplicate form-field filter already at `ai_builder_create_compiler.py:180-184` |
| 17 | Targeted-underlag Swedish-morphology field selection cascade | CONTRACT_BRITTLENESS (compensates for a contract that forbids the model to declare field consumption) | create_dataflow | long-term: semantic `uses_fields` in intent + deterministic resolution — **session 02 scope** | **Keep now, redesign later** | `ai_builder_create_dataflow.py:51-159, 796-1173` |
| 18 | Terminal-artifact fold / promote / body-rename keyword rewrites | Mixed: UPSTREAM_VALIDATION for create (skeleton already owns `TERMINAL_ARTIFACT_STEP`), MODEL_BOUNDARY-ish for edit | step_transition_policy | create compiler/skeleton for create; keep for edit — **session 02 scope** | **Move later** | `ai_builder_step_transition_policy.py:294-374, 448-564`; backstop error at `ai_builder_compiled_spec_preparation.py:95-121` |
| 19 | Per-step invariant patches (template_fill reset, citation clear, input_contract clear) | CONTRACT_BRITTLENESS for create (patches compiler output pre-validation); tolerable for edit (persisted specs) | step_transition_policy | validation errors for create; runtime/publish validator for persisted specs | **Redesign later** | `ai_builder_step_transition_policy.py:802-906` |
| 20 | `hasattr` guard on typed `StepSpec` | CONTRACT_BRITTLENESS (dead defense) | step_transition_policy | none | **Delete** | `ai_builder_step_transition_policy.py:806-810` |
| 21 | Duplicate-step-name auto-rename (edit only) | MODEL_BOUNDARY (pragmatic; create fails into repair instead, consistent with `duplicate_step_name` retry rule) | step_transition_policy | keep | **Keep** | `ai_builder_step_transition_policy.py:180-242`, `ai_builder_compiled_spec_preparation.py:50` |
| 22 | MCP-ref text-match attachment bounded by user selection | MODEL_BOUNDARY (bounded enrichment, permission-fenced, logged) | intent module | keep | **Keep** | `ai_builder_proposal_intent.py:523-601` |
| 23 | Exactly-one tool call on first attempt vs first-matching-of-many in repair | MODEL_BOUNDARY (inconsistent multiplicity policy) | submission vs repair | pick one (first matching) | **Keep, unify when touched** | `ai_builder_proposal_submission.py:108` vs `ai_builder_proposal_repair.py:540-541` |
| 24 | `AIBuilderArchitectureError`: create re-raises, edit's broad catch would swallow it, submission comment claims edit propagates "by design" | UPSTREAM_VALIDATION (routing contract undefined) | scattered | one documented routing rule in the processors | **Fix with #8/#9** | `ai_builder_create_proposal.py:118-119`, `ai_builder_edit_proposal.py:118-123`, `ai_builder_proposal_submission.py:580-584`; only raise sites are create-side (`ai_builder_critic_invariants.py:1911`, `ai_builder_create_compiler.py:221`) |

---

## 3. Ranked Findings

### Overview

| Rank | Sev | Problem | Proposed canonical owner / fix | Confidence |
|---:|---|---|---|---|
| 1 | P1 | Broad catch-to-repair masks compiler bugs as model failures in both processors | Processors catch a typed exception set; anything else is a terminal internal error | High |
| 2 | P1 | Quality feedback is stringly: codes dropped at the finalizer, prose substring-matched downstream, coupled to prose defined in another module; the docx/pdf branches appear unreachable on create and are test-sustained | Structured issue codes end-to-end; remediation registry keyed by code (pattern already exists) | High (mechanism) / Medium (unreachability) |
| 3 | P1 | Repair "information request" bail streams unpersisted assistant text; the same heuristic silently swallows the model's question on the first attempt | Delete the bail (or persist through the one conversation spine); the turn policy layer, not a keyword function, decides whether a proposal turn may become a question turn | High |
| 4 | P2 | Speculative payload recovery inside intent parse (orphan output-field attach, misplaced-assumptions merge) bypasses the principled repair loop, mutates semantics silently, and can silently drop data | Delete both; let one repair round-trip fix malformed steps | High |
| 5 | P2 | Static create retry rules instruct the model about keys that are silently stripped and can never fail validation; no telemetry on stripped keys | Retry rules derived from `failure_codes`; log stripped backend-owned keys | High |
| 6 | P2 | Backend-repairing-backend: create-mode ref pruning guards only backend-generated refs, `uses_form_fields` is filtered twice, dead `hasattr` guard | Compiler-internal invariant violations raise typed errors; delete duplicate filter and dead guard | Medium-High |
| 7 | P2 | `AIBuilderArchitectureError` routing is inconsistent across create/edit and contradicts the submission owner's stated design | One routing rule, fixed together with Finding 1 | High |
| 8 | P3 | Multiplicity policy divergence (exactly-one vs first-matching tool call) | Unify to first-matching when the file is next touched | High |
| 9 | P3 | Terminal-artifact reconciliation lives as keyword rewriting in the transition policy while the create skeleton already owns the terminal artifact slot — two owners for terminal output | Create compiler/skeleton owns terminal artifact for create; defer to session 02 | Medium |
| 10 | P3 | Hardcoded Swedish assistant content on repair paths regardless of session language; underlag broad-composer markers are Swedish-only while sibling modules are bilingual | Localize via existing `resolve_ui_language`; language coupling for session 02 | High (fact) / Low (urgency) |

### Details

**Finding 1 — Broad catch-to-repair (P1, confidence: High).**
*Why it matters:* A `KeyError` in `compile_create_intent_to_spec` becomes model feedback `"Invalid propose_flow arguments: 'foo'"` and burns up to 4 more provider calls trying to "repair" a payload that was never wrong. Telemetry then counts a model failure, so the funnel you'd use to justify deleting repair paths is polluted at the source. The create side logs only `logger.info` (`ai_builder_create_proposal.py:126-132`), so the bug is nearly invisible; the edit side at least logs `logger.error` with traceback (`ai_builder_edit_proposal.py:119`) but still feeds `f"Failed to compile edit: {exc}"` — a raw Python message — to the model as repair feedback.
*Evidence:* `ai_builder_create_proposal.py:118-137` (re-raises `AIBuilderArchitectureError`, then `except Exception` → `failure_kind="parse"`); `ai_builder_edit_proposal.py:76-83, 118-123`.
*Fix:* Create catches `ProposalIntentArgumentError` and `AIBuilderArchitectureError` only (the second re-raised, as today); Pydantic `ValidationError` from the compiler internals should be wrapped into the typed error at the compiler, not interpreted in the processor. Edit catches `pydantic.ValidationError` (parse), `BadRequestException`, `AssistantSnapshotResourceUnavailableError` (as today). Everything else propagates; the planner's existing outer error handling (or a new `PROPOSAL_COMPILE_INTERNAL` code on the existing `build_ai_builder_error_event` contract) makes it terminal.
*Acceptance criteria:* An injected `RuntimeError` in `compile_create_intent_to_spec` / `compile_edit_proposal` produces a terminal internal-error event, zero repair completions, and an `exc_info` error log; an invalid model payload still gets bounded repair.
*Tests required:* Two red tests (create/edit) monkeypatching the compiler to raise; assert repair completion fn never called and telemetry records no repair invocation. Currently **no test pins the broad-catch behavior** (grep over `backend/tests/unittests/flows/ai_builder` for `Failed to compile edit` / `create_intent_compile_failed` returns nothing), so narrowing breaks nothing.
*Risk/trade-off:* If some *expected* exception type is currently reaching the broad catch in production (e.g., a `ValueError` from a deep helper), narrowing converts a silent-repair into a user-visible error. Pre-production, that is the correct trade: you want to see it.

**Finding 2 — Stringly-typed quality feedback (P1, confidence: High on mechanism, Medium on reachability).**
*Why it matters:* The pipeline already has structured issues end-to-end — `SpecValidationError.code`, `CriticIssue.id`, `ToolProcessingResult.failure_codes`, and a code-keyed registry with completeness enforcement (`CREATE_CRITIC_REMEDIATION` + `test_create_critic_feedback_covers_every_semantic_invariant`). Yet `_create_quality_result` returns `failure_kind="quality"` **without** `failure_codes` (`ai_builder_proposal_finalization.py:330-333`) while the validation branch 40 lines earlier carries them (`:287-293`). Downstream, `format_create_quality_feedback` substring-matches Swedish prose (`"valt docx som slutartefakt"`, `ai_builder_create_feedback.py:81,88`) whose only producers are critic remediations in a different module (`ai_builder_critic_invariants.py:477,500`), and `format_create_intent_quality_feedback` does a blind `feedback.replace("output_contract", "output_fields")` across the entire feedback text (`ai_builder_create_feedback.py:105`) — which would also rewrite a step name containing that token. Worse: on the **create** path those two critic invariants are `kind="architecture"` and `enforce_architecture_critic_invariants` **raises** before any prose is formatted (`ai_builder_proposal_policy.py:165-174`, `ai_builder_critic_invariants.py:1888-1920`), so the docx/pdf substring branches appear unreachable from production create flows — they are kept green only by tests that feed the prose in by hand (`test_ai_builder_create_feedback.py:29-36`). Rewording one Swedish sentence in the critic module silently disables the branch either way.
*Fix (canonical owner):* Issues carry their `id`/`code` in `ToolProcessingResult` until the final formatting step; `format_create_quality_feedback`/`format_create_intent_quality_feedback` become code-keyed lookups (extending the existing registry pattern); delete the substring/replace logic.
*Acceptance criteria:* No `in normalized_feedback` substring checks and no `str.replace` on validation prose anywhere in the feedback chain; rewording a critic remediation string changes no repair-rule behavior.
*Tests required:* Assert code→rule mapping for `terminal_output_type_mismatch` (the reachable English validation error added at `ai_builder_compiled_spec_preparation.py:112-121`); regression test that quality-kind results carry codes.
*Risk/trade-off:* If Codex verification finds a path where architecture-critic prose does reach `format_create_quality_feedback` (e.g., some edit/scoped chain I did not fully enumerate), the branches are live and must be ported to codes rather than deleted — the redesign is the same either way.

**Finding 3 — Unpersisted text endgames and misplaced product policy (P1, confidence: High).**
*Why it matters:* Two deliberate endgames yield assistant text and end the turn: the repair info-request bail (`ai_builder_proposal_repair.py:621-624`, pinned by `test_run_tool_self_correction_still_yields_text_for_legitimate_info_request`) and `ScopedStepNotice` (`ai_builder_scoped_plan_revision.py:163-164` → `ai_builder_proposal_submission.py:596-598`). Neither path calls `store_plan_and_update_conversation` or `persist_backend_question`; the planner just streams events (`ai_builder_planner.py:265-295`), and the next turn reloads conversation from the repo (`ai_builder_planner.py:180`). So when the model asks a clarifying question mid-repair, the user answers a question the planner never recorded asking. On the *initial* attempt the same heuristic does the opposite: a first forced response that is short question-like text returns an empty outcome (`ai_builder_proposal_repair.py:693-694`), which `run_active_submission_attempt` converts into a generic `PROPOSAL_TOOL_MISSING` error (`ai_builder_proposal_submission.py:324-339`) — the user never sees the question at all. And the gate itself is a keyword blocklist (`ai_builder_interaction_utils.py:48-72`): a repair text containing "plan" or "steg" can never be an information request, regardless of content.
*Fix:* Since the server's turn controller already decided "this turn proposes", the repair loop should not unilaterally convert the turn into a question turn. Delete the bail: text responses during repair go through the existing forced-tool retry, and final failure surfaces the existing deterministic error messages (`_self_correction_user_message` already explains what to revise). If product wants the "model may ask mid-repair" feature, it must persist the text as a conversation message through the same spine as plans/questions — half-shipped is worse than either choice.
*Acceptance criteria:* Every assistant-visible output of a proposal turn is either persisted or gone; no keyword heuristic decides turn type.
*Tests required:* Red test asserting conversation state after a repair turn that ends in text (currently reveals the gap); update/delete the two pinning tests.
*Risk/trade-off:* Deleting the bail makes the builder stricter in the rare case a model genuinely needed missing info mid-repair — acceptable pre-production, and the discovery loop is the right place to gather info anyway.

**Finding 4 — Speculative intent recovery (P2, confidence: High).**
*Why:* `_attach_orphan_output_field` reinterprets a malformed steps-array entry as the previous step's output field and silently defaults `output_type` to `"json"` (`ai_builder_proposal_intent.py:505-520`) — a semantic guess the model and user never see; a *leading* orphan is dropped entirely without trace (`:509-510` returns without attaching, the `continue` at `:431-432` skips it). Misplaced-assumptions folding (`:376-385`) is milder but the same category. Both bypass the principled repair loop, which exists precisely to say "steps[2] is not a valid step" and let the model fix it with full context. Only the assumptions path logs; the orphan path has zero telemetry.
*Fix/owner:* Delete both; `extra="forbid"` + `safe_validation_issues` already produce excellent field-path feedback for the repair loop.
*Acceptance:* A payload with an orphan field object fails intent validation naming `steps[i]`; one repair round-trip fixes it in the eval harness.
*Tests:* Convert the diagnostic payloads in `ai_builder_intent_diagnostic_payloads.py` into red tests asserting rejection-with-good-feedback instead of silent recovery.
*Risk:* If small models emit orphan fields often, first-turn repair rates rise (one extra provider call per occurrence). No data exists either way — which is itself the problem; the deletion buys you the data.

**Finding 5 — Dead retry guidance + missing strip telemetry (P2, confidence: High).**
*Why:* Every create retry prompt appends "Do not emit input_source, input_type, input_bindings, output_mode, refs, ids, hashes, or timestamps" (`ai_builder_proposal_repair.py:380-393`), but those exact keys are silently stripped before validation (`ai_builder_proposal_intent.py:56-75, 361-373`) and can never be the failure being repaired. The rules waste repair-prompt tokens, misdirect the model's attention on its final attempt ("fix only the listed issues" plus three issues that aren't the issue), and mislead maintainers into thinking these keys cause failures. Meanwhile the strip itself is unlogged, so nobody can measure whether models even emit these keys anymore.
*Fix:* Keep only code-driven rules (the `duplicate_step_name` pattern at `:386-388` is the right shape); add one `logger.info` with the stripped key names in `_normalize_create_intent_arguments`.
*Acceptance/tests:* Retry feedback for a semantic failure contains only the failure and the code-driven rules; a test asserts stripped-key logging fires.
*Risk:* Negligible.

**Finding 6 — Backend-repairing-backend (P2, confidence: Medium-High).**
*Why:* In create mode the model cannot emit `uses_previous_fields`/`uses_previous_outputs` (stripped), so `_compile_safe_previous_field_refs`/`_compile_safe_previous_output_refs` (`ai_builder_create_dataflow.py:292-340`) validate refs produced by the backend's own skeleton/underlag binder — and silently drop them on error, converting binder bugs into silently narrower plans (exactly the `INTENTIONAL_PARTIAL` under-inclusion risk carried forward from the 2026-07-02 review). `uses_form_fields` is filtered twice (`ai_builder_create_compiler.py:180-184` then `ai_builder_create_dataflow.py:216-219`). The `hasattr` guard on a typed `StepSpec` (`ai_builder_step_transition_policy.py:806-810`) is dead defense that would hide attribute errors.
*Fix/owner:* Pre-production, invalid backend-generated refs should raise `AIBuilderArchitectureError` (loud, terminal, telemetried) rather than silently prune; delete the duplicate form-field filter and the `hasattr` guard.
*Acceptance:* An underlag binder emitting a ref to a non-JSON prior fails the turn visibly in tests instead of shipping a quieter plan.
*Tests:* Unit test injecting an invalid backend ref; assert typed error.
*Risk:* If the binder currently emits invalid refs in legitimate flows (masked today), turning on loud failure will surface them — that's the point, but schedule it with room to fix what it finds. Confidence is Medium-High because I did not exhaustively verify that no edit/new-step path routes model-authored refs through `normalize_create_step_mechanics` (grep shows create compiler as the only caller).

**Finding 7 — `AIBuilderArchitectureError` routing incoherence (P2, confidence: High).**
*Why:* Create processor re-raises it (`ai_builder_create_proposal.py:118-119`); the submission owner then converts it to a user-visible event for create but re-raises for edit "by design" (`ai_builder_proposal_submission.py:580-584`). But the edit processor's broad `except Exception` (`ai_builder_edit_proposal.py:118-123`) would swallow it into repair before the submission owner ever saw it — the "by design" branch is unreachable for compile-time architecture errors. Only two raise sites exist, both create-side (`ai_builder_critic_invariants.py:1911`, `ai_builder_create_compiler.py:221`), so this is latent, but the first person to add an edit-side architecture raise gets silently wrong routing.
*Fix:* Solved for free by Finding 1's typed catch set; document the one routing rule at the raise-site module.
*Acceptance/tests:* Edit-path test raising `AIBuilderArchitectureError` from the compiler asserts the intended terminal behavior, whichever is chosen.
*Risk:* None beyond deciding what edit *should* do (recommend: same sanitized terminal event as create — the current asymmetry has no stated justification).

**Findings 8–10 (P3):** covered adequately in the map rows 23, 18, and the i18n row; no additional detail changes the verdicts. Confidence: High on the facts, Low on urgency.

---

## 4. Delete / Merge / Move List

Ordered by leverage (LOC removed × future confusion avoided):

| Action | Target | LOC | Notes |
|---|---|---:|---|
| **Narrow** | Broad `except Exception` → typed set, both processors | ~20 changed | Finding 1; unblocks honest repair telemetry |
| **Delete** | Orphan output-field attach + `_looks_like_orphan_output_field` + misplaced-assumptions merge | ~90 | `ai_builder_proposal_intent.py:376-385, 412-520`; keep the strip |
| **Delete** | Info-request bail + `looks_like_information_request` + the double-gate at `_execute_forced_tool_retry` | ~40 | `ai_builder_proposal_repair.py:621-624, 693`, `ai_builder_interaction_utils.py:48-72`; also removes the unpersisted-text bug and the initial-path swallow |
| **Delete** | Substring/replace prose patching in create feedback | ~45 | `ai_builder_create_feedback.py:74-120`; replaced by code-keyed rules |
| **Delete** | Static backend-mechanics retry rules | ~10 | `ai_builder_proposal_repair.py:380-385` |
| **Delete** | `hasattr` guard on typed `StepSpec` | 5 | `ai_builder_step_transition_policy.py:806-810` |
| **Delete** | Duplicate `uses_form_fields` filter | ~5 | `ai_builder_create_dataflow.py:216-219` (compiler already filters at `ai_builder_create_compiler.py:180-184`) |
| **Merge** | Two identical `make_usage_tracked_proposal_completion` constructions | ~6 | `ai_builder_proposal_submission.py:475-479, 649-652` |
| **Merge** | Post-prepare validity check: edit checks `validation.errors` inline (`ai_builder_edit_proposal.py:147-154`), create defers to the finalizer (`ai_builder_proposal_finalization.py:258`) | ~8 | One owner (finalizer) for "compiled but invalid" |
| **Move (session 02)** | Terminal-artifact fold/promote/body-rename → create compiler/skeleton for create | ~430 eventually | `ai_builder_step_transition_policy.py:294-624`; do not touch tomorrow |
| **Keep explicitly** | JSON-text fallback, forced-after-text, retry budget/temperature state, `ToolRetryConfig`, `ProposalCompletionFn`, backend-key strip, MCP text-match attach, edit duplicate-name rename | — | Model-boundary or earned seams |

---

## 5. What Current Tests Already Cover

- **Repair loop mechanics, thoroughly** (36 tests, `test_ai_builder_proposal_repair.py`): retry budget of 3, base→bumped temperature transition, text-feedback single-use budget, truncation/empty-choices terminals, malformed correction arguments, forced-retry-after-text including JSON-text acceptance and feedback preservation, architecture-error sanitization in all three sub-paths, telemetry branches.
- **Submission dispatch** (22 tests): exactly-one tool-call policy (pinned deliberately at `test_ai_builder_proposal_submission.py:129-135`), create/edit target routing of forced retries, architecture-error asymmetry, quality-failure telemetry, finalizer invocation context.
- **Normalizer behavior by example** (42 tests transition + 18 dataflow): fold/promote/body-rename/rewire/source-material cases, idempotence of source-material underlag, aggregate/compare variants.
- **Remediation registry completeness**: every semantic critic invariant must have a create-mode remediation (`test_create_critic_feedback_covers_every_semantic_invariant`), unregistered IDs raise, mechanics tokens are asserted absent from create feedback.
- **Both text-bail behaviors are pinned as intended** (`test_run_tool_self_correction_still_yields_text_for_legitimate_info_request`, `test_run_forced_tool_retry_after_text_preserves_information_request_empty_outcome`) — the persistence gap, not the behavior, is untested.

## 6. Missing Red Tests

1. **Injected compiler bug does not trigger repair** (create + edit): monkeypatch `compile_create_intent_to_spec` / `compile_edit_proposal` to raise `RuntimeError`; assert zero repair completions and a terminal internal-error event. *This is the test the whole boundary is missing.*
2. **Conversation state after a text-ending repair turn**: assert the assistant question/notice is present in persisted conversation (fails today).
3. **First-attempt question-like text**: assert the user sees either the text or a specific error — not a generic `PROPOSAL_TOOL_MISSING` that hides the model's output (fails today).
4. **Quality results carry structured codes**: assert `failure_codes` non-empty for critic-driven quality failures (fails today at `ai_builder_proposal_finalization.py:330-333`).
5. **Malformed step payloads are rejected with field-path feedback, not silently recovered** (replaces the current implicit recovery expectations; drives Finding 4).
6. **Tool schema ↔ Pydantic model drift fence**: property names in `build_create_flow_tool_schema` (`ai_builder_proposal_intent.py:615-689`) must equal `CreateFlowIntent`/`SemanticStepIntent` field names — the two are hand-maintained twins today.
7. **Backend-generated ref validity is loud**: invalid underlag-binder ref raises instead of pruning (drives Finding 6).

## 7. What Is Not Worth Fixing

- **The targeted-underlag heuristic stack** (`ai_builder_create_dataflow.py:796-1173`) — deleting it without first letting the intent contract declare field consumption re-introduces the runtime crashes it was built to prevent. Session 02 decides the contract; leave it alone tomorrow. (Opus's warning on this was correct.)
- **Terminal-artifact fold/promote/body-rename** — demonstrably reduce repair loops and are alignment-backstopped by `terminal_output_type_mismatch`; moving them into the create compiler is session-02 work, not a hotfix.
- **Exactly-one vs first-matching tool-call policy** — real inconsistency, negligible impact; unify opportunistically.
- **Hardcoded Swedish assistant strings** (`ai_builder_proposal_submission.py:561`, `ai_builder_proposal_repair.py:577, 815`) and Swedish-only broad-composer markers — product is Swedish-first; batch with a future i18n pass.
- **`_ProposalRepairRetryState`, `ToolRetryConfig`, `ProposalCompletionFn`** — all earn their keep; `ToolRetryConfig` carries genuine create/edit polymorphism into a shared loop, `ProposalCompletionFn` is what makes the 36 repair tests possible without litellm. No fake seams to delete here (the agent's `_resolve_litellm_params` finding lives in the router, outside this scope).
- **`MAX_PROPOSAL_STEPS = 256`** and the completion adapter's loose-input normalization — correct boundary paranoia at an actual external boundary.
- **JSON-text fallback** — I looked for a reason to delete it and found the opposite: it routes through identical validation, costs no provider call, and municipal deployments on weaker EU/local models make text-shaped tool payloads a *plausible* failure mode. Keep; revisit only with telemetry showing it never fires.

## 8. From-Scratch Cleaner Design

Based on what this codebase has already learned, not theory — most layers exist and are right; the redesign is about *ownership*, not new machinery:

1. **Provider adapter (exists, keep):** `call_proposal_completion` + response normalization + `parse_tool_call_arguments`. All provider volatility (missing tool call, malformed JSON, truncation, text-instead-of-tool including JSON-text) is absorbed here and in the bounded repair loop. Nothing above this layer ever sees a raw provider shape.
2. **Semantic contract (exists, tighten):** `CreateFlowIntent`/`OrderedEditProposal` strict as today; backend-key strip stays as a logged one-way valve; **no other pre-validation mutation**. Schema drift-fenced against the model. The contract gains, in session 02's scope, a semantic `uses_fields` declaration so the backend stops reverse-engineering dataflow from prose.
3. **Deterministic compiler (exists, harden):** planning state owns input/output/terminal-artifact facts; the skeleton owns topology *including* terminal-artifact enforcement, so post-compile terminal rewriting becomes unnecessary for create. The compiler's only outputs are a valid spec or a typed `AIBuilderArchitectureError`-family exception. Compiler-internal invariant violations raise; they never prune, patch, or feed repair.
4. **One validation gate (mostly exists):** `validate_spec` + critic run once post-compile, emitting structured issues (`code`/`id`, severity, `step_ref`). Formatting is a pure lookup (the `CREATE_CRITIC_REMEDIATION` pattern generalized); no string inspection anywhere.
5. **One repair loop (exists, narrow):** consumes only structured issues from layers 1–2 and 4, never exceptions from layer 3. Budget and temperature escalation as today. Text endgames either persist through the same spine as plans/questions or don't exist.
6. **One persistence rule:** every assistant-visible output of a turn (plan, question, text) is committed through the repository spine before the turn ends — no stream-only assistant speech.

Notably absent: no new service, no plugin system, no orchestration framework. The delta from today is deleting ~200 LOC of misplaced repair and moving two ownerships.

## 9. Tomorrow Implementation Slices

Each slice is independent, small, and test-first:

1. **Narrow the broad catches** (Findings 1+7): typed exception sets in both processors; unexpected exceptions terminal with a new `PROPOSAL_COMPILE_INTERNAL` error code; red tests from Missing-Red-Tests #1. ~2 source files + tests, <150 LOC diff.
2. **Delete speculative intent recovery** (Finding 4): remove orphan-attach and assumptions-merge; add stripped-key logging (Finding 5's telemetry half); red tests from #5. 1 source file + tests.
3. **Thread issue codes through quality feedback** (Findings 2+5): `failure_codes` on quality results; code-keyed repair rules replacing substring/replace; prune static retry rules. ~3 source files + tests; delete the docx/pdf substrings only after Codex confirms reachability.
4. **Delete the info-request bail** (Finding 3): remove the bail, the heuristic, and the double-gate; update the two pinning tests; red test #2/#3. 2 source files.
5. **Trivia batch (optional, tier-4):** `hasattr` guard, duplicate `uses_form_fields` filter, single `make_usage_tracked_proposal_completion` construction.

## 10. Claims Codex Must Verify

1. **Reachability of the docx/pdf substring branches** (`ai_builder_create_feedback.py:80-93`): I traced create → `enforce_architecture_critic_invariants` raising before prose formatting (`ai_builder_proposal_policy.py:165-174`) and edit → `_edit_quality_result` not applying `format_create_quality_feedback`; verify no third caller routes architecture-critic prose through it (all callers: `ai_builder_create_proposal.py:226`, `ai_builder_edit_proposal.py:180`, `ai_builder_proposal_finalization.py:288, 317`, `ai_builder_scoped_plan_revision.py:201`).
2. **No upstream layer persists streamed text events** — I checked planner → processor → submission → repair and the service grep came back empty; verify the router/session layers don't persist SSE text into conversation.
3. **Initial-path question swallow**: first forced attempt returning short question-like text yields `PROPOSAL_TOOL_MISSING` without surfacing the text (`ai_builder_proposal_repair.py:693-694` → `ai_builder_proposal_submission.py:324-339`).
4. **`normalize_create_step_mechanics` has exactly one caller** (create compiler), i.e., no edit/new-step path feeds model-authored refs into the silent pruning (my grep says yes).
5. **Only two `raise AIBuilderArchitectureError` sites exist**, both create-side — the edit re-raise branch at `ai_builder_proposal_submission.py:581-582` is currently unreachable for compile-time errors.
6. **No test exercises the broad-catch-to-repair behavior** (my grep over the unit tree found none).
7. **Whether unforced repair completions are documented as deliberate** anywhere (ADR/comment) before slice 4 deletes the text-bail this design enables.
8. Frequency question only production data can answer: how often `ai_builder_semantic_step_assumptions_recovered` (`ai_builder_proposal_intent.py:434-438`) actually fires — it decides how loudly slice 2 will be felt.

## 11. Challenge This Brief

Where the upstream artifacts over-diagnose, based on my own reading:

- **"Repair is oversized, ~860 LOC / 4 layers" (Opus)** — raw LOC overstates it. A large share of `ai_builder_proposal_repair.py` is terminal-error event construction and telemetry branch logging that *any* design needs. The genuinely excess mass is the text-path machinery (~200 LOC: bail, double-gate, text-feedback budget) plus the misplaced repairs in intent/feedback. The loop core is sound.
- **"Compiler bugs look like bad model payloads" (repair agent)** — true for create (`logger.info` only), overstated for edit, which logs `logger.error` with traceback (`ai_builder_edit_proposal.py:119`); the edit-side harm is wasted repair calls and garbage model feedback, not invisibility.
- **"Challenge backend-key stripping" (repair agent)** — I disagree with deleting it. The strip is a correct one-way valve given `additionalProperties: false` is advisory across LiteLLM providers; the real gaps are the missing log line and the dead retry rules that pretend the strip doesn't exist.
- **The JSON-text fallback** — the maintainability agent's "keep until telemetry proves divergence" is right, and I'd go further: it's the *cheapest* branch in the whole loop (no provider call) and the most defensible given weak-provider deployments.
- **Possible over-reach in my own review:** Finding 6's "make pruning loud" assumes the underlag binder is *supposed* to always emit valid refs; if the binder legitimately over-generates and relies on pruning as its filter stage, the right fix is documenting that contract, not raising. The two-pass structure (`normalize → bind → normalize` at `ai_builder_create_dataflow.py:179-192`) hints pruning may be intentional post-filtering. Codex verification #4 plus a look at binder tests settles it.
- **Anti-slippage check:** no internal phase IDs, plan-section references, or planning-vocabulary leaks observed in any file read for this review.

## 12. Confidence

- **High:** Findings 1, 3, 4, 5, 7; the boundary map classifications for rows 1–15; keep-verdicts on JSON-text fallback and the seams; the tomorrow slices being safe and independent (no tests pin the behaviors being removed except the two named bail tests, which the slice updates deliberately).
- **Medium-High:** Finding 6 (depends on whether pruning is a designed filter stage — Codex #4).
- **Medium:** unreachability of the docx/pdf substring branches (traced but not exhaustively; Codex #1); the claim that no upper layer persists streamed text (three layers checked; Codex #2).
- **Low:** how much first-turn repair volume slice 2 will surface — no production frequency data exists for the recovery paths, which is itself Finding 5's point.

No findings for: fake seams to delete (`ToolRetryConfig`/`ProposalCompletionFn` are earned), internal planning-vocabulary leaks, and repair paths whose *provider-boundary* half should shrink — that half should survive production as-is.
