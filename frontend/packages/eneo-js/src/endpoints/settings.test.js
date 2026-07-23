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
