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

test("initiate forwards a binding challenge whenever one is given", async () => {
  const { auth, calls } = recordingAuth();

  await auth.initiateAuth({ tenant: "city", bindingChallenge: "challenge" });
  await auth.initiateAuth({ tenant: "city", bindingChallenge: "" });
  await auth.initiateAuth({ tenant: "city" });

  assert.deepEqual(
    calls.map((call) => call.options.params.query),
    [
      { tenant: "city", binding_challenge: "challenge" },
      // The backend refuses an empty challenge; it must not become an unbound sign-in.
      { tenant: "city", binding_challenge: "" },
      { tenant: "city" }
    ]
  );
});

test("the callback forwards a binding verifier whenever one is given", async () => {
  const { auth, calls } = recordingAuth();

  await auth.handleAuthCallback({ code: "code", state: "state", bindingVerifier: "verifier" });
  await auth.handleAuthCallback({ code: "code", state: "state", bindingVerifier: "" });
  await auth.handleAuthCallback({ code: "code", state: "state" });

  assert.deepEqual(
    calls.map((call) => call.options.requestBody["application/json"]),
    [
      { code: "code", state: "state", binding_verifier: "verifier" },
      { code: "code", state: "state", binding_verifier: "" },
      { code: "code", state: "state" }
    ]
  );
});
