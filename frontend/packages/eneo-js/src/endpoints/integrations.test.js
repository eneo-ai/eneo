import assert from "node:assert/strict";
import test from "node:test";

import { initIntegrations } from "./integrations.js";

test("restarting the service-account sign-in posts to the reauth endpoint without a body", async () => {
  const calls = [];
  const integrations = initIntegrations({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { auth_url: "https://login.microsoftonline.com/x", state: "state-1" };
    }
  });

  const result = await integrations.admin.sharepoint.restartServiceAccountAuth();

  assert.deepEqual(result, { auth_url: "https://login.microsoftonline.com/x", state: "state-1" });
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/admin/sharepoint/service-account/auth/reauth",
      request: { method: "post" }
    }
  ]);
});
