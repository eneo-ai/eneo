import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { initWidgets } from "./widgets.js";

const SCHEMA = readFileSync(new URL("../types/schema.d.ts", import.meta.url), "utf8");

/**
 * The typed fetch only accepts schema paths when a caller type-checks; these
 * files are plain JS, so hold every recorded call to the generated schema here.
 * @param {{endpoint: string, request: unknown}[]} calls
 */
function assertSchemaOperations(calls) {
  for (const { endpoint, request } of calls) {
    const method = /** @type {{method: string}} */ (request).method;
    const start = SCHEMA.indexOf(`\n  "${endpoint}": {`);
    assert.notEqual(start, -1, `${endpoint} is not a path in schema.d.ts`);
    const block = SCHEMA.slice(start, SCHEMA.indexOf("\n  };", start));
    assert.match(block, new RegExp(`\\n    ${method}: operations\\[`), `${method} ${endpoint}`);
  }
}

const WIDGET_ID = "3c2b1a09-8f7e-4d6c-9b5a-4f3e2d1c0b9a";

function recordingWidgets() {
  /** @type {{endpoint: string, request: unknown}[]} */
  const calls = [];
  const widgets = initWidgets(
    /** @type {any} */ ({
      fetch: async (/** @type {string} */ endpoint, /** @type {unknown} */ request) => {
        calls.push({ endpoint, request });
        return {};
      }
    })
  );
  return { widgets, calls };
}

test("activate sends the reviewed revision, and no body without one", async () => {
  const { widgets, calls } = recordingWidgets();

  await widgets.activate({ id: WIDGET_ID });
  await widgets.activate({ id: WIDGET_ID, revision: 7 });
  // Revision 0 is a real revision, not "none".
  await widgets.activate({ id: WIDGET_ID, revision: 0 });

  const path = { path: { id: WIDGET_ID } };
  assert.deepEqual(calls, [
    { endpoint: "/api/v1/widgets/{id}/activate/", request: { method: "post", params: path } },
    {
      endpoint: "/api/v1/widgets/{id}/activate/",
      request: {
        method: "post",
        params: path,
        requestBody: { "application/json": { revision: 7 } }
      }
    },
    {
      endpoint: "/api/v1/widgets/{id}/activate/",
      request: {
        method: "post",
        params: path,
        requestBody: { "application/json": { revision: 0 } }
      }
    }
  ]);
  assert.equal(Object.hasOwn(/** @type {object} */ (calls[0].request), "requestBody"), false);
  assertSchemaOperations(calls);
});

test("editors request and withdraw activation on one path", async () => {
  const { widgets, calls } = recordingWidgets();

  await widgets.requestActivation({ id: WIDGET_ID });
  await widgets.withdrawActivationRequest({ id: WIDGET_ID });

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/widgets/{id}/activation-request/",
      request: { method: "post", params: { path: { id: WIDGET_ID } } }
    },
    {
      endpoint: "/api/v1/widgets/{id}/activation-request/",
      request: { method: "delete", params: { path: { id: WIDGET_ID } } }
    }
  ]);
  assertSchemaOperations(calls);
});

test("an admin sends a request back with the reason", async () => {
  const { widgets, calls } = recordingWidgets();

  await widgets.declineActivationRequest({
    id: WIDGET_ID,
    reason: "Lägg till kommunens webbplats som tillåten adress."
  });

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/widgets/{id}/activation-request/decline/",
      request: {
        method: "post",
        params: { path: { id: WIDGET_ID } },
        requestBody: {
          "application/json": { reason: "Lägg till kommunens webbplats som tillåten adress." }
        }
      }
    }
  ]);
  assertSchemaOperations(calls);
});

test("the review is read from the admin widget route", async () => {
  const { widgets, calls } = recordingWidgets();

  await widgets.review({ id: WIDGET_ID });

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/admin/widgets/{id}/",
      request: { method: "get", params: { path: { id: WIDGET_ID } } }
    }
  ]);
  assertSchemaOperations(calls);
});
