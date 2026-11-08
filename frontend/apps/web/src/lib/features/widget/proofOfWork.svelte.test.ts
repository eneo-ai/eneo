import { createWidgetClient } from "@eneo/eneo-js";
import { afterEach, expect, test, vi } from "vitest";
import { createChallenge, sha, verifySolution, type Payload } from "altcha/lib";
import { solveWithAltcha } from "@eneo/eneo-js/widgets/proof-of-work";

afterEach(() => vi.restoreAllMocks());

test("the real same-origin worker solves a signed challenge without the ALTCHA UI", async () => {
  const secret = "widget-browser-contract";
  const challenge = await createChallenge({
    algorithm: "SHA-256",
    cost: 1000,
    keyPrefix: "0",
    hmacSignatureSecret: secret,
    deriveKey: sha.deriveKey
  });
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json(challenge));
  const payload: Payload = JSON.parse(
    atob(
      await solveWithAltcha(
        createWidgetClient({ baseUrl: location.origin, publicId: "wgt_fixture" })
      )
    )
  );
  const verified = await verifySolution({
    ...payload,
    hmacSignatureSecret: secret,
    deriveKey: sha.deriveKey
  });
  expect(verified.verified).toBe(true);
  expect(fetch.mock.calls[0][1]?.credentials).toBe("omit");
  expect(document.querySelector("altcha-widget")).toBeNull();
}, 35_000);
