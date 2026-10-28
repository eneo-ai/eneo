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

test("testing unsaved tenant-app credentials posts them as the body", async () => {
  const calls = [];
  const integrations = initIntegrations({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { success: false, error_message: "invalid_client" };
    }
  });
  const credentials = { client_id: "c", client_secret: "s", tenant_domain: "t.onmicrosoft.com" };

  const result = await integrations.admin.sharepoint.testTenantAppCredentials(credentials);

  assert.equal(result.success, false);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/admin/sharepoint/app/test",
      request: { method: "post", requestBody: { "application/json": credentials } }
    }
  ]);
});

test("listing an item's documents sends only the query parameters that are set", async () => {
  const calls = [];
  const integrations = initIntegrations({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { items: [], total_count: 0, limit: 50, offset: 0, total_size: 0 };
    }
  });

  const page = await integrations.knowledge.listDocuments({
    knowledge: { id: "ik-1" },
    space: { id: "space-1" },
    q: "",
    sort: "updated_at",
    order: "desc",
    limit: 50,
    offset: 100
  });

  assert.equal(page.total_count, 0);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/documents/",
      request: {
        method: "get",
        params: {
          path: { id: "space-1", integration_knowledge_id: "ik-1" },
          query: { sort: "updated_at", order: "desc", limit: 50, offset: 100 }
        }
      }
    }
  ]);
});

test("listing an item's skipped documents reads the skipped endpoint", async () => {
  const calls = [];
  const skipped = { items: [{ file: "scan.pdf", reason: "No text layer" }], total: 1 };
  const integrations = initIntegrations({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return skipped;
    }
  });

  const result = await integrations.knowledge.listSkippedDocuments({
    knowledge: { id: "ik-1" },
    space: { id: "space-1" }
  });

  assert.deepEqual(result, skipped);
  assert.deepEqual(calls, [
    {
      endpoint:
        "/api/v1/spaces/{id}/knowledge/integrations/{integration_knowledge_id}/documents/skipped/",
      request: {
        method: "get",
        params: { path: { id: "space-1", integration_knowledge_id: "ik-1" } }
      }
    }
  ]);
});

test("reading a space's sync progress reads the space-wide progress endpoint", async () => {
  const calls = [];
  const progress = {
    items: [
      {
        integration_knowledge_id: "ik-1",
        sync_type: "full",
        phase: "processing",
        started_at: "2026-10-14T09:00:00Z",
        updated_at: "2026-10-14T09:02:00Z",
        total: 120,
        done: 45,
        indexed: 30,
        unchanged: 12,
        skipped: 3,
        deleted: 1
      }
    ]
  };
  const integrations = initIntegrations({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return progress;
    }
  });

  const result = await integrations.knowledge.getSyncProgress({ space: { id: "space-1" } });

  assert.deepEqual(result, progress);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/spaces/{id}/knowledge/integrations/sync-progress/",
      request: { method: "get", params: { path: { id: "space-1" } } }
    }
  ]);
});
