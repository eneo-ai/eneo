# Four-fact information-loss matrix (implementation checklist)

Adopted in the 2026-08-05 final peer session. Each fact's every transition
must PRESERVE, DERIVE, or REJECT — never silently coerce. Fill rows while
implementing slices B/C/F; use for completion verification only (not a
survey, service, or second state model).

## 1. Prose schema (user statements → classifier → planning state → compiled contract)

| Transition | Rule | Owner | Failure code | Behavior test |
|---|---|---|---|---|
| classifier raw → parsed delta | DONE(C1 `4266fb519`): shape notation belongs to the cited mention (boundary judged after trailing []/{}); structurally malformed present delta → whole-attempt parse_failed; citation-level refusal keeps refuse-fields semantics | ai_builder_slot_classification_contract | parse_failed (existing) | shape-notation + malformed-delta classifier tests |
| parsed delta → SchemaEvidence | TODO(C): one evidence schema; `{}` unspecified, items for `[]`; unrepresentable literal → visible typed refusal | planning_state_builder | TODO | TODO |
| evidence → terminal contract | DONE(C2 `6d1df4619`): only declared_schema pins; prose/inferred are hints; user-named keys exempt from the localized-key lexicon AND source-reader alias canonicalization (verbatim survival) | ai_builder_create_compiler + assembly/plan + source_reader_contracts | n/a (semantics) | declared-only pinning + user-named-keys e2e tests |
| evidence → critic | DONE(C2): prose_output_field_names_must_survive enforces every user-named key in the outcome contract (folded, any depth) with repairable feedback; action_followup exemption narrowed to declared_schema (8e720e359) | ai_builder_critic_invariants | prose_output_field_names_must_survive | survival critic tests |

## 2. Proposal output_fields (model tool call → normalizer → planned step → compiled contract)

| Transition | Rule | Owner | Failure code | Behavior test |
|---|---|---|---|---|
| tool args → drafts | DONE(B): admission delegates to StructuredFieldDraft (typed defaults stay lossless); strings, string lists, dict-of-name maps, missing name/description, unknown types, container misuse reject the WHOLE list with first-decisive-error feedback; over-depth rejects at the step boundary; no field_N invention, no downgrades, no partial retention | ai_builder_structured_field_normalizer + proposal_intent | StructuredFieldAdmissionError → ProposalIntentArgumentError (parse) | test_ai_builder_structured_field_normalizer.py (13) |
| drafts → planned step | preserved verbatim; empty list = no fields (no "dropped" log) | assembly/create | n/a | normalizer log-noise tests (DONE 9aa10352c) |
| planned → compiled contract | terminal schema suppression only under pinned declared schema | lower.py | terminal_output_fields_suppressed_by_schema log | existing |

## 3. Result obligations (goal/slots → ResultContract → prompt/completion/critic)

| Transition | Rule | Owner | Failure code | Behavior test |
|---|---|---|---|---|
| slots → contract | required roles only for action_followup; extras per obligations | ai_builder_result_contract | n/a | existing |
| contract → prompt | five roles + extraction-producer requirement rendered (DONE 8e720e359) | render_result_contract_prompt_block | n/a | prompt-block tests (DONE) |
| contract → completion | explicit required_output_field_roles through CreateCompileContext; insertion only when roles exist; user schema never appended | assembly/create | n/a | negative open_questions topology test (DONE 9aa10352c) |
| contract → critic | folded closed vocabulary at any depth; declared-schema precedence | ai_builder_critic_invariants | action_followup_requires_followup_fields | lookalike + nested + Swedish tests (DONE) |

## 4. File-role explicitness (classifier roles → FileRoleEvidence → discovery)

| Transition | Rule | Owner | Failure code | Behavior test |
|---|---|---|---|---|
| classifier role → FileRoleEvidence | TODO(F): carry evidence_level (required for source=model, forbidden otherwise); schema version bump | planning_state(_builder) | validation error | TODO |
| evidence → docx_output_mode discovery | TODO(F): explicit authored choice wins; structural placeholders resolve; else auto-resolve only for exactly-one explicit commit-grade user-owned template role; otherwise ask | ai_builder_discovery_issue_rules | n/a | TODO 5-case distinct-behavior test |
