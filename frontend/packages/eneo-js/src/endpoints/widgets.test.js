import assert from "node:assert/strict";
import test from "node:test";

import { initWidgets } from "./widgets.js";

test("activation posts the widget id without a request body", async () => {
  const calls = [];
  const widgets = initWidgets({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { id: "widget-id" };
    }
  });

  await widgets.activate({ id: "widget-id" });

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/widgets/{id}/activate/",
      request: { method: "post", params: { path: { id: "widget-id" } } }
    }
  ]);
});
