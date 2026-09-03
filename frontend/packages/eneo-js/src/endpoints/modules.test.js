import assert from "node:assert/strict";
import test from "node:test";

import { createEneo } from "../eneo.js";
import { initModules } from "./modules.js";

test("createEneo exposes tenant-implicit module administration", () => {
  const eneo = createEneo({ baseUrl: "https://example.test" });

  assert.equal(typeof eneo.modules.list, "function");
  assert.equal(typeof eneo.modules.install, "function");
  assert.equal(typeof eneo.modules.uninstall, "function");
});

test("modules use one complete install command and no tenant parameter", async () => {
  const calls = [];
  const modules = initModules({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return {};
    }
  });
  const config = {
    redirect_uris: ["https://module.example/auth/callback"],
    service_key_id: "48e7a31a-f7fe-461d-a337-b50fd78b306e"
  };

  await modules.list();
  await modules.install({ moduleKey: "reports", config });
  await modules.uninstall({ moduleKey: "reports" });

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/admin/modules/",
      request: { method: "get" }
    },
    {
      endpoint: "/api/v1/admin/modules/{module_key}/",
      request: {
        method: "put",
        params: { path: { module_key: "reports" } },
        requestBody: { "application/json": config }
      }
    },
    {
      endpoint: "/api/v1/admin/modules/{module_key}/",
      request: {
        method: "delete",
        params: { path: { module_key: "reports" } }
      }
    }
  ]);
});
