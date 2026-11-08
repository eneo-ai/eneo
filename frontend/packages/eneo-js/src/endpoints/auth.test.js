import assert from "node:assert/strict";
import test from "node:test";

import { initAuth } from "./auth.js";

function recordingAuth() {
  const calls = [];
  const auth = initAuth({
    baseUrl: new URL("https://eneo.example.eu"),
    fetch: async (endpoint, options) => {
      calls.push({ endpoint, options });
      return { access_token: "eneo-token" };
    }
  });
  return { auth, calls };
}

test("the callback forwards the provider's iss parameter", async () => {
  const { auth, calls } = recordingAuth();

  await auth.handleAuthCallback({ code: "code", state: "state", iss: "https://idp.example" });

  assert.deepEqual(calls, [
    {
      endpoint: "/api/v1/auth/callback",
      options: {
        method: "post",
        requestBody: {
          "application/json": { code: "code", state: "state", iss: "https://idp.example" }
        }
      }
    }
  ]);
});

test("the callback sends no iss when the provider sent none", async () => {
  const { auth, calls } = recordingAuth();

  await auth.handleAuthCallback({ code: "code", state: "state" });

  assert.deepEqual(calls[0].options.requestBody["application/json"], {
    code: "code",
    state: "state"
  });
});
