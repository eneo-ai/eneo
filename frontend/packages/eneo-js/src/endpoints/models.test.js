import assert from "node:assert/strict";
import test from "node:test";

import { initModels } from "./models.js";

test("lists forecast models and updates one through the forecast endpoint", async () => {
  const calls = [];
  const models = initModels({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return endpoint === "/api/v1/ai-models/" ? { forecast_models: [{ id: "forecast-1" }] } : {};
    }
  });

  const listed = await models.list();
  await models.update({
    forecastModel: { id: "forecast-1" },
    update: { is_org_enabled: false, display_name: "Timestral" }
  });

  assert.deepEqual(listed.forecastModels, [{ id: "forecast-1" }]);
  assert.deepEqual(calls[1], {
    endpoint: "/api/v1/forecast-models/{id}/",
    request: {
      method: "post",
      params: { path: { id: "forecast-1" } },
      requestBody: { "application/json": { is_org_enabled: false, display_name: "Timestral" } }
    }
  });
});
