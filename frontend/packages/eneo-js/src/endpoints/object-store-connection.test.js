import assert from "node:assert/strict";
import test from "node:test";

import { createEneo } from "../eneo.js";
import { initObjectStoreConnection } from "./object-store-connection.js";

test("createEneo exposes the object-store connection resource", () => {
  const eneo = createEneo({ baseUrl: "https://example.test" });

  assert.equal(typeof eneo.objectStoreConnection.get, "function");
  assert.equal(typeof eneo.objectStoreConnection.create, "function");
  assert.equal(typeof eneo.objectStoreConnection.rotateCredentials, "function");
});

test("object-store connection uses separate create and credential-rotation contracts", async () => {
  const calls = [];
  const objectStoreConnection = initObjectStoreConnection({
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return { source: "admin", configured: true };
    }
  });
  const connection = {
    endpoint_url: "https://objects.example.test",
    region: "se-1",
    bucket: "eneo-content",
    access_key_id: "access",
    secret_access_key: "secret",
    addressing_style: "path"
  };
  const credentials = {
    expected_revision: 1,
    access_key_id: "next-access",
    secret_access_key: "next-secret"
  };

  await objectStoreConnection.get();
  await objectStoreConnection.create(connection);
  await objectStoreConnection.rotateCredentials(credentials);

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/admin/object-store-connection",
      request: { method: "get" }
    },
    {
      endpoint: "/api/v1/admin/object-store-connection",
      request: {
        method: "post",
        requestBody: { "application/json": connection }
      }
    },
    {
      endpoint: "/api/v1/admin/object-store-connection/credentials",
      request: {
        method: "put",
        requestBody: { "application/json": credentials }
      }
    }
  ]);
});
