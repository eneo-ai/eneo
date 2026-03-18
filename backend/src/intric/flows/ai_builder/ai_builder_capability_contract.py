"""AI Builder capability contract.

Documents what the framework guarantees vs what depends on the LLM.
These invariants are enforced by tests in test_ai_builder_eval_harness.py.

FRAMEWORK GUARANTEES (independent of LLM output quality):
- Hard validation catches ALL structural errors before plan storage
- Quality lint catches common design issues (missing contracts, etc.)
- Contextual quality critic catches conversation-contradicting proposals
- Invalid existing_step_ref raises BadRequestException (never silently degrades)
- Reasoning is stripped from stored conversation and API responses
- Discovery questions use backend-owned schemas (not LLM-invented)
- Token estimation uses conservative Swedish-aware //3 factor
- Stale-revision detection prevents concurrent edit conflicts
- Orphaned temp flows are cleaned up on create-mode apply failure
- Edit operations use explicit add/modify/remove with typed schemas
- Untouched steps are preserved by default in edit mode
- Step synopses (not raw instructions) are injected into system prompt

LLM-DEPENDENT BEHAVIOR (quality varies with model capability):
- Discovery question selection and phrasing
- Proposal quality (step count, instruction detail, variable usage)
- Edit operation correctness (which steps to add/modify/remove)
- Self-correction effectiveness after validation failure
- Intent classification accuracy (info request vs build request)
- Requirements summary comprehensiveness
"""

# Framework-level invariants that tests verify
FRAMEWORK_INVARIANTS = {
    "hard_validation": "All structural errors caught before plan storage",
    "quality_lint": "Common design issues flagged on all 3 proposal paths",
    "contextual_critic": "Conversation-aware quality checks on all paths",
    "invalid_ref_hard_fail": "Invalid existing_step_ref raises BadRequestException",
    "reasoning_stripped": "Reasoning never in stored conversation or API response",
    "backend_owned_discovery": "Discovery questions use server schemas",
    "conservative_token_estimation": "Swedish-aware //3 token factor",
    "stale_revision_detection": "Concurrent edit conflicts detected",
    "orphan_cleanup": "Temp flows cleaned up on create-mode failure",
    "explicit_edit_ops": "add/modify/remove with typed schemas",
    "untouched_preservation": "Unmentioned steps preserved in edit mode",
    "sanitized_instructions": "Synopses not raw instructions in prompts",
}

# LLM-dependent behaviors that eval scenarios should track over time
LLM_DEPENDENT_BEHAVIORS = {
    "discovery_quality": "Question selection and phrasing",
    "proposal_quality": "Step count, instruction detail, variable usage",
    "edit_correctness": "Which steps to add/modify/remove",
    "self_correction": "Effectiveness after validation failure",
    "intent_classification": "Info request vs build request accuracy",
    "requirements_summary": "Comprehensiveness of summary",
}
