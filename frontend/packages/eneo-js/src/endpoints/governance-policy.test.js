import assert from "node:assert/strict";
import test from "node:test";

import { initGovernancePolicy } from "./governance-policy.js";

test("governance policy update forwards the reasoning policy", async () => {
  const calls = [];
  const governancePolicy = initGovernancePolicy({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return {};
    }
  });
  const reasoningPolicy = {
    default_effort: "medium",
    allow_user_override: true
  };

  await governancePolicy.update({ reasoning_policy: reasoningPolicy });

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/admin/governance-policy/",
      request: {
        method: "put",
        requestBody: {
          "application/json": { reasoning_policy: reasoningPolicy }
        }
      }
    }
  ]);
});
