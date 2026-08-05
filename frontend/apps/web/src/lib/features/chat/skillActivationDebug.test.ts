import { describe, expect, it } from "vitest";
import {
  buildSkillActivationRows,
  getUnmatchedActivationRejections,
  summarizeSkillActivation,
  type SkillActivationEvidence
} from "./skillActivationDebug";

const evidence: SkillActivationEvidence = {
  version: 1,
  effective_mode: "selective",
  fallback_reason: null,
  available: [
    {
      activation_key: "always-skill",
      skill_id: "skill-1",
      skill_revision_id: "revision-1",
      revision_number: 2,
      content_digest: "a".repeat(64),
      position: 0,
      source: "space"
    },
    {
      activation_key: "selected-skill",
      skill_id: "skill-2",
      skill_revision_id: "revision-2",
      revision_number: 4,
      content_digest: "b".repeat(64),
      position: 2,
      source: "organization"
    }
  ],
  blocked: [
    {
      activation_key: "blocked-skill",
      skill_id: "skill-3",
      skill_revision_id: "revision-3",
      revision_number: 1,
      content_digest: "c".repeat(64),
      position: 1,
      source: "space"
    }
  ],
  initially_active: ["always-skill"],
  accepted: ["selected-skill"],
  repeated: ["always-skill"],
  rejected: [{ activation_key: "blocked-skill", reason: "blocked" }],
  selected_model_id: "model-1",
  selected_model_route: "gpt-4o",
  skill_context_tokens: 320,
  skill_context_token_limit: 2_000,
  token_count_source: "litellm",
  activation_rounds: 2,
  selection_latency_ms: 14
};

describe("Skill activation debug projection", () => {
  it("keeps candidate order and exposes every recorded decision", () => {
    expect(buildSkillActivationRows(evidence)).toEqual([
      expect.objectContaining({ activationKey: "always-skill", activationMode: "always" }),
      expect.objectContaining({
        activationKey: "blocked-skill",
        activationMode: null,
        candidateState: "blocked",
        outcomes: ["blocked", "rejected"]
      }),
      expect.objectContaining({
        activationKey: "selected-skill",
        activationMode: "on_demand",
        outcomes: ["accepted"]
      })
    ]);
  });

  it("summarizes available, entered, blocked, and rejected Skills separately", () => {
    expect(summarizeSkillActivation(evidence)).toEqual({
      available: 2,
      enteredContext: 2,
      blocked: 1,
      rejected: 1
    });
  });

  it("retains rejected requests that do not match a known candidate", () => {
    const withUnknown = {
      ...evidence,
      rejected: [
        ...(evidence.rejected ?? []),
        { activation_key: "missing-skill", reason: "unknown_key" as const }
      ]
    };

    expect(getUnmatchedActivationRejections(withUnknown)).toEqual([
      { activation_key: "missing-skill", reason: "unknown_key" }
    ]);
  });

  it("matches a rejection to the revision id when no activation key was retained", () => {
    const revisionKeyed = {
      ...evidence,
      blocked: [{ ...evidence.blocked[0], activation_key: null }],
      rejected: [{ activation_key: "revision-3", reason: "blocked" as const }]
    };

    expect(getUnmatchedActivationRejections(revisionKeyed)).toEqual([]);
    expect(buildSkillActivationRows(revisionKeyed)[1]).toEqual(
      expect.objectContaining({
        activationKey: "revision-3",
        activationMode: null,
        rejectionReasons: ["blocked"]
      })
    );
  });
});
