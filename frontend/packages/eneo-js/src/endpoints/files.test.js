import assert from "node:assert/strict";
import test from "node:test";

import { initFiles } from "./files.js";

test("file deletion waits for the backend outcome", async () => {
  let resolveRequest;
  const request = new Promise((resolve) => {
    resolveRequest = resolve;
  });
  const calls = [];
  const files = initFiles({
    baseUrl: new URL("https://eneo.example.eu"),
    fetch: async (endpoint, options) => {
      calls.push({ endpoint, options });
      return request;
    }
  });

  let settled = false;
  const deletion = files.delete({ fileId: "file-1" }).finally(() => {
    settled = true;
  });
  await Promise.resolve();

  assert.equal(settled, false);
  resolveRequest();
  assert.equal(await deletion, undefined);
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/files/{id}/",
      options: {
        method: "delete",
        params: { path: { id: "file-1" } }
      }
    }
  ]);
});

test("file deletion propagates backend failures", async () => {
  const backendError = new Error("deletion rejected");
  const files = initFiles({
    baseUrl: new URL("https://eneo.example.eu"),
    fetch: async () => {
      throw backendError;
    }
  });

  await assert.rejects(files.delete({ fileId: "file-1" }), backendError);
});

test("processing signed URLs keep the existing route and defaults", async () => {
  const calls = [];
  const files = initFiles({
    baseUrl: new URL("https://eneo.example.eu"),
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return {
        url: "http://backend:8000/api/v1/files/file-1/download/?token=signed",
        expires_at: 1234
      };
    }
  });

  await files.generateSignedUrl({ fileId: "file-1" });

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/files/{id}/signed-url/",
      request: {
        method: "post",
        params: { path: { id: "file-1" } },
        requestBody: {
          "application/json": {
            content_disposition: "inline",
            expires_in: 3600
          }
        }
      }
    }
  ]);
});

test("original signed URLs use the explicit original-file route", async () => {
  const calls = [];
  const files = initFiles({
    baseUrl: new URL("https://eneo.example.eu"),
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return {
        url: "http://backend:8000/api/v1/files/file-1/original/download/?token=signed",
        expires_at: 1234
      };
    }
  });

  const result = await files.generateOriginalSignedUrl({
    fileId: "file-1",
    expiresIn: 120,
    contentDisposition: "attachment"
  });

  assert.deepEqual(result, {
    url: "https://eneo.example.eu/api/v1/files/file-1/original/download/?token=signed",
    expires_at: 1234
  });
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/files/{id}/original/signed-url/",
      request: {
        method: "post",
        params: { path: { id: "file-1" } },
        requestBody: {
          "application/json": {
            content_disposition: "attachment",
            expires_in: 120
          }
        }
      }
    }
  ]);
});
