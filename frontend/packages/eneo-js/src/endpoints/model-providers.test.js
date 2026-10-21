import assert from "node:assert/strict";
import test from "node:test";

import { initModelProviders } from "./model-providers.js";

test("outbound header routes use the typed model-provider paths", async () => {
  const calls = [];
  const providers = initModelProviders({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return {};
    }
  });

  await providers.getOutboundHeaderOptions();
  await providers.previewOutboundHeaders({ id: "provider-1" }, { userId: "user-1" });

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/admin/model-providers/outbound-headers/options/",
      request: { method: "get" }
    },
    {
      endpoint: "/api/v1/admin/model-providers/{provider_id}/outbound-headers/preview/",
      request: {
        method: "post",
        params: { path: { provider_id: "provider-1" } },
        requestBody: { "application/json": { user_id: "user-1" } }
      }
    }
  ]);
});
