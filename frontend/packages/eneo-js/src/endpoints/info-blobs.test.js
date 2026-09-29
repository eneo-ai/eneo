import assert from "node:assert/strict";
import test from "node:test";

import { initInfoBlobs } from "./info-blobs.js";

test("original signed URLs use the explicit InfoBlob original route", async () => {
  const calls = [];
  const infoBlobs = initInfoBlobs({
    baseUrl: new URL("https://eneo.example.eu"),
    fetch: async (endpoint, request) => {
      calls.push({ endpoint, request });
      return {
        url: "http://backend:8000/api/v1/info-blobs/blob-1/original/download/?token=signed",
        expires_at: 1234
      };
    }
  });

  const result = await infoBlobs.generateOriginalSignedUrl({
    infoBlobId: "blob-1",
    expiresIn: 120,
    contentDisposition: "attachment"
  });

  assert.deepEqual(result, {
    url: "https://eneo.example.eu/api/v1/info-blobs/blob-1/original/download/?token=signed",
    expires_at: 1234
  });
  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/info-blobs/{id}/original/signed-url/",
      request: {
        method: "post",
        params: { path: { id: "blob-1" } },
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

test("original signed URLs leave optional defaults to the backend", async () => {
  let requestBody;
  const infoBlobs = initInfoBlobs({
    baseUrl: new URL("https://eneo.example.eu"),
    fetch: async (_endpoint, request) => {
      requestBody = request.requestBody["application/json"];
      return {
        url: "https://eneo.example.eu/api/v1/info-blobs/blob-1/original/download/?token=signed",
        expires_at: 1234
      };
    }
  });

  await infoBlobs.generateOriginalSignedUrl({ infoBlobId: "blob-1" });

  assert.deepEqual(JSON.parse(JSON.stringify(requestBody)), {});
});
