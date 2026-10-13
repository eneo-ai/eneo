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

test("testing the stored SharePoint app posts to the test endpoint without a body", async () => {
  const calls = [];
  const integrations = initIntegrations({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { success: true, details: "Token acquired successfully" };
    }
  });

  const result = await integrations.admin.sharepoint.testStoredConnection();

  assert.deepEqual(result, { success: true, details: "Token acquired successfully" });
  assert.deepEqual(calls, [
    { endpoint: "/api/v1/admin/sharepoint/app/test", request: { method: "post" } }
  ]);
});

test("recreating all SharePoint subscriptions posts to the recreate-all endpoint", async () => {
  const calls = [];
  const integrations = initIntegrations({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { total_subscriptions: 3, expired_count: 1, recreated: 3, failed: 0, errors: [] };
    }
  });

  const result = await integrations.admin.sharepoint.recreateAllSubscriptions();

  assert.equal(result.recreated, 3);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/admin/sharepoint/subscriptions/recreate-all",
      request: { method: "post" }
    }
  ]);
});
