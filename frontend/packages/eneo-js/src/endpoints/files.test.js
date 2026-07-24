import assert from "node:assert/strict";
import test from "node:test";

import { initFiles } from "./files.js";

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
    url: "https://backend:8000/api/v1/files/file-1/original/download/?token=signed",
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
