import assert from "node:assert/strict";
import test from "node:test";

import { initSettings } from "./settings.js";

test("organisation Skill execution block uses the typed settings routes", async () => {
  const calls = [];
  const settings = initSettings({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { skill_id: "skill-1", block: null };
    }
  });

  await settings.getSkillExecutionBlock({ skillId: "skill-1" });
  await settings.blockSkillExecution({
    skillId: "skill-1",
    reason: "Confirmed unsafe instructions"
  });
  await settings.unblockSkillExecution({
    skillId: "skill-1",
    expectedBlockId: "block-1",
    reason: "Removed the harmful revision"
  });

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/settings/skills/{skill_id}/execution-block",
      request: {
        method: "get",
        params: { path: { skill_id: "skill-1" } }
      }
    },
    {
      endpoint: "/api/v1/settings/skills/{skill_id}/execution-block",
      request: {
        method: "post",
        params: { path: { skill_id: "skill-1" } },
        requestBody: {
          "application/json": {
            reason: "Confirmed unsafe instructions"
          }
        }
      }
    },
    {
      endpoint: "/api/v1/settings/skills/{skill_id}/execution-block/unblock",
      request: {
        method: "post",
        params: { path: { skill_id: "skill-1" } },
        requestBody: {
          "application/json": {
            expected_block_id: "block-1",
            reason: "Removed the harmful revision"
          }
        }
      }
    }
  ]);
});

test("Skill runtime policy uses the typed admin settings routes", async () => {
  const calls = [];
  const policy = {
    selective_activation_enabled: true,
    max_attached_skills: 100,
    context_share_percent: 10,
    max_activations_per_turn: 3,
    editable_bounds: {
      max_attached_skills: { minimum: 1, maximum: 1000 },
      context_share_percent: { minimum: 1, maximum: 100 },
      max_activations_per_turn: { minimum: 1, maximum: 10 }
    }
  };
  const projections = { context_share_percent: 10, models: [] };
  const settings = initSettings({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return endpoint.endsWith("model-projections") ? projections : policy;
    }
  });

  assert.equal(await settings.getSkillRuntimePolicy(), policy);
  assert.equal(await settings.updateSkillRuntimePolicy(policy), policy);
  assert.equal(await settings.resetSkillRuntimePolicy(), policy);
  assert.equal(await settings.getSkillRuntimeModelProjections(), projections);

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/settings/skills/runtime-policy",
      request: { method: "get" }
    },
    {
      endpoint: "/api/v1/settings/skills/runtime-policy",
      request: {
        method: "put",
        requestBody: {
          "application/json": {
            selective_activation_enabled: true,
            max_attached_skills: 100,
            context_share_percent: 10,
            max_activations_per_turn: 3
          }
        }
      }
    },
    {
      endpoint: "/api/v1/settings/skills/runtime-policy/reset",
      request: { method: "post" }
    },
    {
      endpoint: "/api/v1/settings/skills/runtime-policy/model-projections",
      request: { method: "get" }
    }
  ]);
});
