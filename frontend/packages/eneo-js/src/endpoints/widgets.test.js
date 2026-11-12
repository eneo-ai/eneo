import assert from "node:assert/strict";
import test from "node:test";

import { initWidgets } from "./widgets.js";

test("an acknowledgement sends the ids of the servers and tools the admin was shown", async () => {
  const calls = [];
  const widgets = initWidgets({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { id: "widget-id" };
    }
  });

  await widgets.acknowledgeExternalTools({
    widget: { id: "widget-id" },
    servers: [
      {
        id: "server-id",
        name: "Ärenden",
        tools: [
          { id: "tool-a", name: "Sök" },
          { id: "tool-b", name: "Skapa" }
        ]
      }
    ]
  });
  await widgets.activate({ id: "widget-id" });

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/widgets/{id}/acknowledge-external-tools/",
      request: {
        method: "post",
        params: { path: { id: "widget-id" } },
        requestBody: {
          "application/json": { servers: [{ id: "server-id", tool_ids: ["tool-a", "tool-b"] }] }
        }
      }
    },
    {
      endpoint: "/api/v1/widgets/{id}/activate/",
      request: { method: "post", params: { path: { id: "widget-id" } } }
    }
  ]);
});
